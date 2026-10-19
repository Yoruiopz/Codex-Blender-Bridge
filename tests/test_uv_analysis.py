from __future__ import annotations

import asyncio
import importlib
import math
import random
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.uv import UVTools, load_definitions


@pytest.fixture
def geometry(addon_package):
    return importlib.import_module(f"{addon_package}.uv_geometry")


def triangle(module, *, index=0, face=0, uv=((0., 0.), (1., 0.), (0., 1.)), scale=1.):
    return module.UVTriangle(index, face, uv, ((0., 0., 0.), (scale, 0., 0.), (0., scale, 0.)))


@pytest.mark.parametrize("scale,density", [(1., 1024.), (2., 512.), (.5, 2048.)])
def test_world_scale_and_isotropic_density(geometry, scale, density):
    result = geometry.triangle_metrics(triangle(geometry, scale=scale), (1024, 1024))
    assert result["world_area"] == pytest.approx(.5 * scale * scale)
    assert result["uv_area"] == .5 and result["density"] == pytest.approx(density)
    assert result["sigma_min"] == result["sigma_max"] == pytest.approx(density)
    assert result["anisotropy"] == pytest.approx(1.)


def test_directional_singular_values_and_rectangular_resolution(geometry):
    stretched = geometry.triangle_metrics(triangle(geometry, uv=((0, 0), (2, 0), (0, 1))), (1024, 1024))
    assert stretched["sigma_min"] == 1024 and stretched["sigma_max"] == 2048
    assert stretched["anisotropy"] == 2 and stretched["density"] == pytest.approx(1024 * math.sqrt(2))
    rectangle = geometry.triangle_metrics(triangle(geometry), (2048, 1024))
    assert rectangle["anisotropy"] == 2 and rectangle["density"] == stretched["density"]
    shear = geometry.triangle_metrics(triangle(geometry, uv=((0, 0), (1, 0), (1, 1))), (1024, 1024))
    assert shear["anisotropy"] == pytest.approx((3 + math.sqrt(5)) / 2)


def test_rotation_and_mirror_do_not_invent_stretch(geometry):
    for uv in (((0, 0), (0, 1), (-1, 0)), ((0, 0), (-1, 0), (0, 1))):
        result = geometry.triangle_metrics(triangle(geometry, uv=uv), (1024, 1024))
        assert result["anisotropy"] == pytest.approx(1) and result["density"] == pytest.approx(1024)
    assert result["mirrored"] and result["uv_signed_area"] == -.5


@pytest.mark.parametrize("uv,scale,field", [(((0, 0), (0, 0), (0, 0)), 1, "near_zero_uv"),
    (((0, 0), (1, 0), (0, 1)), 0, "near_zero_world")])
def test_degenerate_directional_metrics_are_undefined(geometry, uv, scale, field):
    result = geometry.triangle_metrics(triangle(geometry, uv=uv, scale=scale), (1024, 1024))
    assert result[field] and result["sigma_min"] is result["sigma_max"] is result["anisotropy"] is None


@pytest.mark.parametrize("uv", [((float("nan"), 0), (1, 0), (0, 1)), ((1e9, 0), (1, 0), (0, 1))])
def test_invalid_uv_data_is_not_serialized_as_metrics(geometry, uv):
    result = geometry.triangle_metrics(triangle(geometry, uv=uv), (1024, 1024))
    assert result == {"valid": False, "reason": "non_finite_or_out_of_range_uv"}


@pytest.mark.parametrize("second,area", [(((0, 0), (1, 0), (0, 1)), .5),
    (((.5, 0), (1.5, 0), (.5, 1)), .125), (((.1, .1), (.2, .1), (.1, .2)), .005),
    (((1, 0), (1, 1), (0, 1)), 0), (((1, 0), (2, 0), (1, 1)), 0)])
def test_triangle_overlap_area_and_boundary_touch(geometry, second, area):
    observed, _ = geometry.intersection_area(((0, 0), (1, 0), (0, 1)), second)
    assert observed == pytest.approx(area, abs=1e-12)


def test_intersections_are_symmetric_and_bounded(geometry):
    generator = random.Random(137)
    for _ in range(80):
        first = tuple((generator.random(), generator.random()) for _ in range(3))
        second = tuple((generator.random(), generator.random()) for _ in range(3))
        area, _ = geometry.intersection_area(first, second)
        reverse, _ = geometry.intersection_area(second, first)
        assert area == pytest.approx(reverse, abs=1e-12)
        assert -1e-12 <= area <= min(abs(geometry.signed_area(first)), abs(geometry.signed_area(second))) + 1e-12


def test_shared_diagonals_do_not_overlap_and_stacked_faces_do(geometry):
    first = triangle(geometry, uv=((0, 0), (1, 0), (1, 1)))
    second = triangle(geometry, index=1, uv=((0, 0), (1, 1), (0, 1)))
    clean = geometry.overlap_analysis([first, second], max_pair_tests=100, max_reports=10)
    assert clean["complete"] and clean["positive_triangle_pairs"] == 0
    stacked = geometry.overlap_analysis([first, triangle(geometry, index=2, face=1, uv=first.uv)], max_pair_tests=100, max_reports=10)
    assert stacked["complete"] and stacked["positive_triangle_pairs"] == stacked["face_pairs"] == 1
    assert stacked["summed_pairwise_uv_area"] == .5


def test_overlap_budgets_and_detail_truncation_are_separate(geometry):
    triangles = [triangle(geometry, index=i, face=i) for i in range(3)]
    partial = geometry.overlap_analysis(triangles, max_pair_tests=1, max_reports=1)
    assert not partial["complete"] and partial["pair_budget_exhausted"] and partial["pair_tests"] == 1
    full = geometry.overlap_analysis(triangles, max_pair_tests=100, max_reports=1)
    assert full["complete"] and full["positive_triangle_pairs"] == full["face_pairs"] == 3
    assert full["examples_truncated"] and len(full["examples"]) == 1


def test_overlap_invalid_uvs_are_incomplete(geometry):
    result = geometry.overlap_analysis([triangle(geometry, uv=((float("inf"), 0), (1, 0), (0, 1)))], max_pair_tests=100, max_reports=1)
    assert not result["complete"] and result["invalid_uv_triangles"] == 1


def test_clean_8192_triangle_grid_finishes_with_default_pair_budget(geometry):
    triangles = []
    for y in range(64):
        for x in range(64):
            a, b = (x / 64, y / 64), ((x + 1) / 64, y / 64)
            c, d = ((x + 1) / 64, (y + 1) / 64), (x / 64, (y + 1) / 64)
            for uv in ((a, b, c), (a, c, d)):
                triangles.append(triangle(geometry, index=len(triangles), face=y * 64 + x, uv=uv))
    result = geometry.overlap_analysis(triangles, max_pair_tests=200_000, max_reports=1)
    assert result["complete"] and not result["positive_triangle_pairs"]
    assert result["pair_tests"] < 200_000


def test_grid_and_large_triangle_fallback_match_brute_force(geometry):
    generator = random.Random(339)
    triangles = [triangle(geometry)]
    for index in range(1, 300):
        x, y = generator.random() * .9, generator.random() * .9
        triangles.append(triangle(geometry, index=index, face=index, uv=((x, y), (x + .02, y), (x, y + .02))))
    brute = 0
    for index, first in enumerate(triangles):
        for second in triangles[index + 1:]:
            area, tolerance = geometry.intersection_area(first.uv, second.uv)
            brute += int(area > tolerance)
    result = geometry.overlap_analysis(triangles, max_pair_tests=1_000_000, max_reports=1)
    assert result["complete"] and result["processed_large_triangles"] > 0
    assert result["positive_triangle_pairs"] == brute


@pytest.fixture
def analysis(addon_package, monkeypatch, geometry):
    module = importlib.import_module(f"{addon_package}.tools.uv_analysis")
    triangles = [triangle(geometry, index=i, face=i) for i in range(3)]
    metadata = {"object": "Mesh", "uv_layer": "UV", "mode": "OBJECT", "scoped_face_count": 3,
                "requested_triangle_count": 3, "tessellation_incomplete_faces": 0,
                "tessellation_incomplete_examples": [], "triangle_budget_exceeded": False}
    monkeypatch.setattr(module, "_collect", lambda *args: (dict(metadata), triangles))
    return module, triangles, metadata, SimpleNamespace(check_cancelled=None)


@pytest.mark.parametrize("params", [{"texture_resolution": [True, 10]}, {"texture_resolution": [0, 10]}, {"texture_resolution": [1]},
    {"max_triangles": 0}, {"max_pair_tests": True}, {"max_reports": 257}, {"anisotropy_warning": .5},
    {"density_target": float("nan")}, {"density_tolerance": -1}, {"unknown": 1}])
def test_analysis_parameter_validation(analysis, params):
    module, _, _, context = analysis
    with pytest.raises(Exception) as error:
        module.analyze(context, params)
    assert error.value.code == "INVALID_ARGUMENT"


def test_incomplete_overlap_cannot_report_numeric_success(analysis):
    module, _, _, context = analysis
    result = module.analyze(context, {"max_pair_tests": 1, "max_reports": 1})
    assert not result["analysis_complete"] and result["analysis_truncated"]
    assert result["verification"]["status"] == "incomplete" and not result["verification"]["user_goal_verified"]


def test_triangle_budget_does_not_emit_partial_metrics(analysis):
    module, _, metadata, context = analysis
    metadata["triangle_budget_exceeded"] = True
    result = module.analyze(context, {})
    assert not result["analysis_complete"] and result["metrics"] is None
    assert result["overlap"]["reason"] == "TRIANGLE_BUDGET"


def test_missing_native_tessellation_is_not_complete(analysis):
    module, _, metadata, context = analysis
    metadata["tessellation_incomplete_faces"] = 1
    assert not module.analyze(context, {})["analysis_complete"]


def test_face_density_and_reports_are_bounded(analysis):
    module, _, _, context = analysis
    result = module.analyze(context, {"max_reports": 1, "density_target": 512., "density_tolerance": .01})
    assert result["analysis_complete"] and result["face_reports_truncated"]
    assert len(result["face_reports"]) == 1 and result["metrics"]["density_min"] == 1024
    assert result["face_reports"][0]["outside_density_target"]
    assert result["verification"]["status"] == "needs_review"
    assert result["resolution_source"] == "DEFAULT_1024_ASSUMPTION"


def test_density_target_does_not_hide_variation_inside_a_face(analysis, geometry):
    module, triangles, metadata, context = analysis
    triangles[:] = [triangle(geometry, uv=((0, 0), (1, 0), (1, 1))),
        geometry.UVTriangle(1, 0, ((0, 0), (1, 1), (-1, 2)), ((0, 0, 0), (1, 1, 0), (0, 1, 0)))]
    metadata["scoped_face_count"], metadata["requested_triangle_count"] = 1, 2
    target = 1024 * math.sqrt(2)
    result = module.analyze(context, {"density_target": target, "density_tolerance": .01})
    face = result["face_reports"][0]
    assert face["density"] == pytest.approx(target)
    assert face["outside_density_target"] and result["verification"]["status"] == "needs_review"
    assert face["worst_triangle_index"] == 1 and face["min_directional_density"] > 0
    assert result["metrics"]["density_min"] == pytest.approx(1024)
    assert result["metrics"]["density_max"] == pytest.approx(1024 * math.sqrt(3))


def test_mcp_analysis_registry_wrapper_and_strict_schema(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.uv_analysis").register_tools(registry)
    spec = registry.get("uv.analyze")
    definition = next(item for item in load_definitions() if item.name == spec.name)
    assert not spec.modifies and not definition.modifying
    assert {p.value for p in spec.permissions} == set(definition.required_permissions) == {"INSPECT_SCENE"}
    calls = []

    class Registry:
        async def call(self, method, arguments):
            calls.append((method, arguments))
            return {}

    tools = UVTools(Registry())
    asyncio.run(tools.uv_analyze("Mesh", "UV", face_indices=[1], texture_resolution=[2048, 1024]))
    assert calls[0][0] == "uv.analyze" and calls[0][1]["face_indices"] == [1]
    assert calls[0][1]["texture_resolution"] == [2048, 1024]
    for field, value in (("face_indices", [True]), ("texture_resolution", [True, 1024]),
                         ("max_pair_tests", "100"), ("selected_only", 1), ("density_target", True)):
        with pytest.raises(ValidationError):
            TypeAdapter(get_type_hints(UVTools.uv_analyze, include_extras=True)[field]).validate_python(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e30])
def test_unsafe_object_positions_are_rejected_before_native_work(addon_package, monkeypatch, value):
    module = importlib.import_module(f"{addon_package}.tools.uv_analysis")
    obj = SimpleNamespace(name="Mesh", mode="OBJECT", data=SimpleNamespace(
        vertices=[SimpleNamespace(co=(value, 0, 0))], edges=[], polygons=[], loops=[],
    ))
    monkeypatch.setattr(module, "_mesh_object", lambda _: obj)
    monkeypatch.setattr(module, "require_blender", lambda: SimpleNamespace(context=SimpleNamespace(view_layer=SimpleNamespace(
        objects={"Mesh": obj}, update=lambda: pytest.fail("Unsafe geometry reached dependency evaluation"),
    ))))
    monkeypatch.setattr(module, "bmesh", SimpleNamespace(new=lambda: pytest.fail("Unsafe geometry reached native conversion")))
    with pytest.raises(Exception) as error:
        module._collect(SimpleNamespace(check_cancelled=None), {"object_name": "Mesh", "uv_layer": "UV"}, 100)
    assert error.value.code == "INVALID_ARGUMENT" and error.value.context["invalid_vertex_count"] == 1


def test_invalid_position_examples_are_bounded(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.uv_analysis")
    with pytest.raises(Exception) as error:
        module._check_positions(SimpleNamespace(check_cancelled=None), [SimpleNamespace(co=(float("nan"), 0, 0))] * 70)
    assert error.value.context["invalid_vertex_count"] == 70
    assert len(error.value.context["vertex_indices"]) == 64 and error.value.context["vertex_indices_truncated"]


def test_unsafe_edit_positions_do_not_reach_graph_evaluation(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.uv_analysis")
    obj = SimpleNamespace(name="Mesh", mode="EDIT", data=object())
    bm = SimpleNamespace(verts=[SimpleNamespace(co=(float("nan"), 0, 0))], edges=[], faces=[])
    monkeypatch.setattr(module, "_mesh_object", lambda _: obj)
    monkeypatch.setattr(module, "bmesh", SimpleNamespace(from_edit_mesh=lambda _: bm))
    monkeypatch.setattr(module, "require_blender", lambda: SimpleNamespace(context=SimpleNamespace(view_layer=SimpleNamespace(
        objects={"Mesh": obj}, update=lambda: pytest.fail("Unsafe edit geometry reached dependency evaluation"),
    ))))
    with pytest.raises(Exception) as error:
        module._collect(SimpleNamespace(check_cancelled=None), {"object_name": "Mesh", "uv_layer": "UV"}, 100)
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("extra", [{"face_indices": []}, {"face_indices": [True]}, {"face_indices": [0, 0]},
    {"face_indices": [-1]}, {"face_indices": "0"}, {"selection_id": False}, {"selected_only": 1}])
def test_collector_scope_is_strict_before_blender_access(addon_package, monkeypatch, extra):
    module = importlib.import_module(f"{addon_package}.tools.uv_analysis")
    monkeypatch.setattr(module, "_mesh_object", lambda *args: pytest.fail("Invalid scope reached Blender access"))
    with pytest.raises(Exception) as error:
        module._collect(SimpleNamespace(check_cancelled=None), {"object_name": "Mesh", "uv_layer": "UV", **extra}, 100)
    assert error.value.code == "INVALID_ARGUMENT"
