from __future__ import annotations

import asyncio
import importlib
import math
import random
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.catalog import load_mesh_definitions
from mcp_server.tools.mesh import MeshTools


@pytest.fixture
def geometry(addon_package):
    return importlib.import_module(f"{addon_package}.mesh_geometry")


def tri(g, points=((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), *, index=0, ids=None, face=None):
    return g.MeshTriangle(index, index if face is None else face, ids or tuple(range(index * 3, index * 3 + 3)), tuple(points))


def check(g, triangles, **params):
    return g.intersection_analysis(triangles, epsilon=1e-6, max_pair_tests=params.get("pairs", 1000),
                                   max_reports=params.get("reports", 10), check_cancelled=params.get("cancel"))


@pytest.mark.parametrize("points,kind", [
    (((.5, -.5, -1.), (.5, 1.5, -1.), (.5, .5, 1.)), "crossing"),
    (((.5, -.5, 0.), (.5, 1.5, 0.), (.5, .5, 1.)), "boundary_contact"),
    (((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), "coplanar_overlap"),
    (((0., 0., 1e-7), (1., 0., 1e-7), (0., 1., 1e-7)), "coplanar_overlap"),
])
def test_classifies_positive_contacts_symmetrically(geometry, points, kind):
    a, b = tri(geometry), tri(geometry, points, index=1)
    result = geometry.triangle_contact(a, b, 1e-6)
    assert result["kind"] == geometry.triangle_contact(b, a, 1e-6)["kind"] == kind
    report = check(geometry, [a, b])
    assert report["complete"] and report["triangle_pairs"][kind] == 1 and report["face_pairs"] == 1


@pytest.mark.parametrize("points", [
    ((0., 0., 1.), (1., 0., 1.), (0., 1., 1.)),
    ((1., 0., 0.), (2., 0., 0.), (1., 1., 0.)),
    ((1., 0., -1.), (1., 1., -1.), (1., 0., 1.)),
])
def test_separated_edge_or_point_contacts_are_not_positive_overlap(geometry, points):
    assert geometry.triangle_contact(tri(geometry), tri(geometry, points, index=1), 1e-6) is None


def test_topological_shared_edge_is_not_crossing_but_coplanar_fold_is(geometry):
    a = tri(geometry, ((0., 0., 0.), (2., 0., 0.), (0., 2., 0.)))
    hinge = tri(geometry, ((0., 0., 0.), (2., 0., 0.), (1., 1., 1.)), index=1, ids=(0, 1, 3))
    fold = tri(geometry, ((0., 0., 0.), (2., 0., 0.), (1., 1., 0.)), index=1, ids=(0, 1, 3))
    assert geometry.triangle_contact(a, hinge, 1e-6) is None
    assert geometry.triangle_contact(a, fold, 1e-6)["kind"] == "coplanar_overlap"


def test_shared_vertex_does_not_hide_a_crossing(geometry):
    a = tri(geometry)
    b = tri(geometry, ((0., 0., 0.), (.5, .5, -1.), (.5, .5, 1.)), index=1, ids=(0, 3, 4))
    result = geometry.triangle_contact(a, b, 1e-6)
    assert result is not None and result["segment_length_world"] > 0


def test_degenerate_precision_and_near_parallel_cases_stay_incomplete(geometry):
    collapsed = tri(geometry, ((0., 0., 0.),) * 3)
    assert check(geometry, [collapsed])["near_zero_triangles_skipped"] == 1
    shifted = tri(geometry, ((1e12, 0., 0.), (1e12 + 1, 0., 0.), (1e12, 1., 0.)))
    report = check(geometry, [shifted])
    assert not report["complete"] and report["precision_limited_triangles"] == 1
    a = tri(geometry, ((-1., -1., 0.), (1., -1., 0.), (0., 1., 0.)))
    b = tri(geometry, ((-1., -1., -1e-9), (1., -1., -1e-9), (0., 1., 1e-9)), index=1)
    report = geometry.intersection_analysis([a, b], epsilon=1e-12, max_pair_tests=100, max_reports=1)
    assert not report["complete"] and report["triangle_pairs"]["near_parallel_ambiguous"] == 1


def test_pair_budget_and_detail_limits_are_independent(geometry):
    triangles = [tri(geometry, index=i) for i in range(4)]
    partial = check(geometry, triangles, pairs=1)
    assert not partial["complete"] and partial["pair_budget_exhausted"] and partial["pair_tests"] == 1
    complete = check(geometry, triangles, reports=1)
    assert complete["complete"] and complete["examples_truncated"] and complete["triangle_pairs"]["coplanar_overlap"] == 6


def test_translations_rotations_and_winding_do_not_change_contact(geometry):
    a = tri(geometry)
    b = tri(geometry, ((.5, -.5, -1.), (.5, 1.5, -1.), (.5, .5, 1.)), index=1)
    for angle in (0., .42, 1.7):
        def move(p, angle=angle):
            return (math.cos(angle) * p[0] - math.sin(angle) * p[1] + 101.,
                    math.sin(angle) * p[0] + math.cos(angle) * p[1] - 40., p[2] + 12.)
        for reverse in (False, True):
            aa = tri(geometry, [move(p) for p in a.points])
            bb = tri(geometry, [move(p) for p in (b.points[::-1] if reverse else b.points)], index=1)
            assert geometry.triangle_contact(aa, bb, 1e-6)["kind"] == "crossing"


def test_clean_planar_grid_is_complete_with_default_pair_budget(geometry):
    side = 64
    triangles = []
    for y in range(side):
        for x in range(side):
            points = ((x / side, y / side, 0.), ((x + 1) / side, y / side, 0.),
                      ((x + 1) / side, (y + 1) / side, 0.), (x / side, (y + 1) / side, 0.))
            base = y * (side + 1) + x
            ids = (base, base + 1, base + side + 2, base + side + 1)
            for corners in ((0, 1, 2), (0, 2, 3)):
                triangles.append(tri(geometry, [points[i] for i in corners], index=len(triangles),
                                     ids=tuple(ids[i] for i in corners), face=y * side + x))
    report = check(geometry, triangles, pairs=250_000)
    assert report["complete"] and sum(report["triangle_pairs"].values()) == 0
    assert report["pair_tests"] < 250_000 and report["grid_axes"] == [0, 1]


def test_cancellation_propagates(geometry):
    def cancelled():
        raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        check(geometry, [tri(geometry)], cancel=cancelled)


@pytest.mark.parametrize("axes", [(0, 1, 2), (1, 2, 0), (2, 0, 1)])
def test_coplanar_projection_uses_every_normal_axis(geometry, axes):
    points = [tuple(p[i] for i in axes) for p in ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))]
    result = geometry.triangle_contact(tri(geometry, points), tri(geometry, points, index=1), 1e-6)
    assert result["kind"] == "coplanar_overlap" and result["projected_overlap_area"] == pytest.approx(.5)


@pytest.mark.parametrize("scale,epsilon", [(1e-8, 1e-12), (1e4, 1e-6)])
def test_coplanar_clipping_tolerance_scales_with_world_geometry(geometry, scale, epsilon):
    points = ((0., 0., 0.), (scale, 0., 0.), (0., scale, 0.))
    result = geometry.triangle_contact(tri(geometry, points), tri(geometry, points, index=1), epsilon)
    assert result["kind"] == "coplanar_overlap"
    assert result["projected_overlap_area"] == pytest.approx(.5 * scale * scale, abs=1e-30)
    assert result["projected_area_tolerance"] < result["projected_overlap_area"]


def test_random_pair_contact_classification_is_symmetric(geometry):
    generator = random.Random(42)
    for _ in range(100):
        points = [tuple(generator.uniform(-1, 1) for _ in range(3)) for _ in range(6)]
        a, b = tri(geometry, points[:3]), tri(geometry, points[3:], index=1)
        first = geometry.triangle_contact(a, b, 1e-6)
        second = geometry.triangle_contact(b, a, 1e-6)
        assert (first or {}).get("kind") == (second or {}).get("kind")


@pytest.mark.parametrize("issue", ["clean", "topology", "empty", "triangle_budget", "missing_tessellation", "degenerate"])
def test_analysis_never_reports_incomplete_evidence_clean(addon_package, geometry, monkeypatch, issue):
    module = importlib.import_module(f"{addon_package}.tools.mesh_analysis")
    metadata = {"counts": {"faces": 1}, "topology": {"counts": {}, "examples": {}},
                "tessellation": {"triangle_budget_exceeded": False, "incomplete_face_count": 0}}
    triangles = [tri(geometry)]
    if issue == "topology":
        metadata["topology"]["counts"]["wire_edges"] = 1
    elif issue == "empty":
        metadata["counts"]["faces"] = 0
        triangles.clear()
    elif issue == "triangle_budget":
        metadata["tessellation"]["triangle_budget_exceeded"] = True
    elif issue == "missing_tessellation":
        metadata["tessellation"]["incomplete_face_count"] = 1
    elif issue == "degenerate":
        triangles[:] = [tri(geometry, ((0., 0., 0.),) * 3)]
    monkeypatch.setattr(module, "_collect", lambda *_: (metadata, triangles))
    result = module.analyze(SimpleNamespace(check_cancelled=None), {"object_name": "Mesh"})
    expected = "numeric_checks_passed" if issue == "clean" else ("needs_review" if issue == "topology" else "incomplete")
    assert result["verification"]["status"] == expected and not result["verification"]["user_goal_verified"]


def test_metadata_strict_schema_and_forwarding(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.mesh_analysis").register_tools(registry)
    spec = registry.get("mesh.analyze")
    definition = next(d for d in load_mesh_definitions() if d.name == spec.name)
    assert not spec.modifies and not definition.modifying
    assert {p.value for p in spec.permissions} == set(definition.required_permissions) == {"INSPECT_SCENE"}
    calls = []

    class Registry:
        async def call(self, method, params):
            calls.append((method, params))
            return {}

    asyncio.run(MeshTools(Registry()).mesh_analyze("Mesh", max_reports=2))
    assert calls[0][0] == "mesh.analyze" and calls[0][1]["max_reports"] == 2
    hints = get_type_hints(MeshTools.mesh_analyze, include_extras=True)
    for field, value in (("max_reports", True), ("max_pair_tests", "1"), ("distance_tolerance", True)):
        with pytest.raises(ValidationError):
            TypeAdapter(hints[field]).validate_python(value)


@pytest.mark.parametrize("params", [{"object_name": "Mesh", "max_triangles": True},
    {"object_name": "Mesh", "distance_tolerance": float("nan")}, {"object_name": "Mesh", "unknown": 0},
    {"object_name": "Mesh", "max_pair_tests": 1_000_001}, {"object_name": "Mesh", "max_reports": 0}])
def test_validation_precedes_blender(addon_package, monkeypatch, params):
    module = importlib.import_module(f"{addon_package}.tools.mesh_analysis")
    monkeypatch.setattr(module, "_collect", lambda *_: pytest.fail("Invalid input reached Blender"))
    with pytest.raises(Exception) as error:
        module.analyze(SimpleNamespace(check_cancelled=None), params)
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e20])
def test_local_preflight_prevents_native_work(addon_package, monkeypatch, value):
    module = importlib.import_module(f"{addon_package}.tools.mesh_analysis")
    obj = SimpleNamespace(name="Mesh", type="MESH", mode="OBJECT", data=SimpleNamespace(
        vertices=[SimpleNamespace(co=(value, 0., 0.))], edges=[], polygons=[], loops=[], is_editmode=False))
    monkeypatch.setattr(module, "get_object", lambda *_, **__: obj)
    monkeypatch.setattr(module, "require_blender", lambda: SimpleNamespace(context=SimpleNamespace(view_layer=SimpleNamespace(
        objects={"Mesh": obj}, update=lambda: pytest.fail("Unsafe positions reached dependency graph")))))
    monkeypatch.setattr(module, "bmesh", SimpleNamespace(new=lambda: pytest.fail("Unsafe positions reached conversion")))
    with pytest.raises(Exception) as error:
        module._collect(SimpleNamespace(check_cancelled=None), "Mesh", 1e-6, 100, 2)
    assert error.value.code == "INVALID_ARGUMENT" and error.value.context["invalid_vertex_count"] == 1
