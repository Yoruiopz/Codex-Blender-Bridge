from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.catalog import DESTRUCTIVE_TOOL_NAMES, load_mesh_definitions
from mcp_server.tools.mesh import MeshTools


@dataclass(eq=False)
class Element:
    index: int
    select: bool = True
    hide: bool = False
    link_faces: list = field(default_factory=list)
    link_edges: list = field(default_factory=list)
    verts: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    is_boundary: bool = True
    loops: list = field(default_factory=list)
    material_index: int = 0


@pytest.fixture
def repair(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.mesh_repair")
    vertices = [Element(i) for i in range(4)]
    edges = [Element(i, verts=[vertices[i], vertices[(i + 1) % 4]]) for i in range(4)]
    for edge in edges:
        for vertex in edge.verts:
            vertex.link_edges.append(edge)
    bm = SimpleNamespace(verts=vertices, edges=edges, faces=[],
                         loops=SimpleNamespace(layers=SimpleNamespace(uv={})))
    obj = SimpleNamespace(name="Prop", data=SimpleNamespace(users=1, materials=[object(), object()]))
    monkeypatch.setattr(module, "_active_edit_mesh", lambda _: (
        None, obj, bm, {"VERT": bm.verts, "EDGE": bm.edges},
    ))
    calls = []

    def subdivide(mesh, **kwargs):
        calls.append(("subdivide", kwargs))
        mesh.verts.append(Element(len(mesh.verts)))

    def find(mesh, **kwargs):
        calls.append(("find", kwargs))
        return {"targetmap": {vertices[1]: vertices[0]}}

    def weld(mesh, **kwargs):
        calls.append(("weld", kwargs))
        for vertex in kwargs["targetmap"]:
            mesh.verts.remove(vertex)

    def fill(mesh, **kwargs):
        calls.append(("fill", kwargs))
        face = Element(len(mesh.faces))
        mesh.faces.append(face)
        return {"faces": [face]}

    monkeypatch.setattr(module, "bmesh", SimpleNamespace(ops=SimpleNamespace(
        subdivide_edges=subdivide, find_doubles=find, weld_verts=weld, holes_fill=fill,
    )))
    finishes = []

    def finish(obj, mesh, *, destructive, before):
        finishes.append(destructive)
        return {"object": obj.name, "mesh_counts_before": before,
                "mesh_counts_after": module._mesh_counts(mesh)}

    monkeypatch.setattr(module, "_finish", finish)
    context = SimpleNamespace(check_cancelled=None)
    return module, obj, bm, calls, finishes, context


@pytest.mark.parametrize("tool,extra", [
    ("subdivide_selected", {"cuts": True}), ("subdivide_selected", {"cuts": 33}),
    ("subdivide_selected", {"cuts": 0}), ("subdivide_selected", {"cuts": 1.5}),
    ("merge_by_distance", {"distance": float("nan")}),
    ("merge_by_distance", {"distance": float("inf")}),
    ("merge_by_distance", {"distance": True}),
    ("merge_by_distance", {"distance": 0}),
    ("merge_by_distance", {"distance": 1e7}),
    ("fill_holes", {"material_index": True}), ("fill_holes", {"material_index": 2}),
    ("fill_holes", {"material_index": -1}),
])
def test_repair_rejects_bad_parameters_before_ops(repair, tool, extra):
    module, _, _, calls, finishes, context = repair
    with pytest.raises(Exception) as error:
        getattr(module, tool)(context, {"object_name": "Prop", **extra})
    assert error.value.code == "INVALID_ARGUMENT"
    assert not calls and not finishes


@pytest.mark.parametrize("tool", ["subdivide_selected", "merge_by_distance", "fill_holes"])
@pytest.mark.parametrize("extra", [{"unknown": True}, {"object_name": ""}, {"selection_id": False}])
def test_repair_requires_explicit_valid_scope(repair, tool, extra):
    module, _, _, calls, finishes, context = repair
    with pytest.raises(Exception) as error:
        getattr(module, tool)(context, {"object_name": "Prop", **extra})
    assert error.value.code == "INVALID_ARGUMENT"
    assert not calls and not finishes


@pytest.mark.parametrize("tool", ["subdivide_selected", "merge_by_distance", "fill_holes"])
@pytest.mark.parametrize("restriction", ["shared", "linked", "shape_keys", "hidden", "empty", "large"])
def test_repair_rejects_unsafe_targets(repair, monkeypatch, tool, restriction):
    module, obj, bm, calls, finishes, context = repair
    if restriction == "shared":
        obj.data.users = 2
    elif restriction == "linked":
        obj.library = object()
    elif restriction == "shape_keys":
        obj.data.shape_keys = object()
    else:
        sequence = bm.verts if tool == "merge_by_distance" else bm.edges
        if restriction == "large":
            monkeypatch.setattr(module, "MAX_SELECTED", 2)
        for element in sequence:
            if restriction == "hidden":
                element.hide = True
            if restriction == "empty":
                element.select = False
    with pytest.raises(Exception) as error:
        getattr(module, tool)(context, {"object_name": "Prop"})
    assert error.value.code in {"NOT_IMPLEMENTED", "INVALID_SELECTION"}
    assert not calls and not finishes


@pytest.mark.parametrize("tool", ["subdivide_selected", "merge_by_distance", "fill_holes"])
def test_hidden_incident_faces_are_not_modified(repair, tool):
    module, _, bm, calls, _, context = repair
    face = Element(0, hide=True, verts=bm.verts)
    for element in [*bm.verts, *bm.edges]:
        element.link_faces = [face]
    with pytest.raises(Exception) as error:
        getattr(module, tool)(context, {"object_name": "Prop"})
    assert error.value.code == "INVALID_SELECTION" and not calls


def test_subdivision_growth_budget_and_reference_scope(repair, monkeypatch):
    module, _, bm, calls, finishes, context = repair
    monkeypatch.setattr(module, "validate_selection_reference", lambda *args: {"edges": [1]})
    result = module.subdivide_selected(context, {"object_name": "Prop", "selection_id": "fresh", "cuts": 2})
    assert calls[0][1]["edges"] == [bm.edges[1]]
    assert calls[0][1]["smooth"] == 0 and calls[0][1]["use_grid_fill"]
    assert result["cuts"] == 2 and result["affected_objects"] == ["Prop"]
    assert result["selection_reference_invalidated"] and finishes == [True]
    calls.clear()
    bm.edges[0].link_faces = [Element(0, verts=[bm.verts[0]] * 1024)]
    # The estimate must reject BEFORE native subdivision, even with a small edge selection.
    monkeypatch.setattr(module, "MAX_MESH_ELEMENTS", 100)
    with pytest.raises(Exception) as error:
        module.subdivide_selected(context, {"object_name": "Prop", "cuts": 32})
    assert error.value.code == "INVALID_ARGUMENT" and not calls


def test_merge_uses_selected_vertices_and_reports_collapse(repair):
    module, _, bm, calls, finishes, context = repair
    excluded = bm.verts[-1]
    excluded.select = False
    result = module.merge_by_distance(context, {"object_name": "Prop", "distance": .01})
    assert excluded not in calls[0][1]["verts"]
    assert excluded in bm.verts and result["merged_vertices"] == 1
    assert result["warnings"] and finishes == [True]


def test_merge_noop_preserves_reference_and_does_not_weld(repair, monkeypatch):
    module, _, _, calls, finishes, context = repair
    monkeypatch.setattr(module.bmesh.ops, "find_doubles", lambda *a, **kw: {"targetmap": {}})
    result = module.merge_by_distance(context, {"object_name": "Prop"})
    assert not result["changed"] and not result["selection_reference_invalidated"]
    assert result["merged_vertices"] == 0 and not finishes and not calls


def test_merge_rejects_escaped_native_target_before_weld(repair, monkeypatch):
    module, _, bm, calls, _, context = repair
    monkeypatch.setattr(module.bmesh.ops, "find_doubles", lambda *a, **kw: {
        "targetmap": {bm.verts[0]: Element(100)},
    })
    with pytest.raises(Exception) as error:
        module.merge_by_distance(context, {"object_name": "Prop"})
    assert error.value.code == "OPERATION_FAILED" and not calls


@pytest.mark.parametrize("restriction", ["interior", "open", "branch", "oversize"])
def test_fill_requires_bounded_closed_boundary_loops(repair, monkeypatch, restriction):
    module, _, bm, calls, _, context = repair
    if restriction == "interior":
        bm.edges[0].is_boundary = False
    elif restriction == "open":
        bm.edges[0].select = False
    elif restriction == "branch":
        bm.edges.append(Element(4, verts=[bm.verts[0], bm.verts[2]]))
    else:
        monkeypatch.setattr(module, "MAX_HOLE_SIDES", 3)
    with pytest.raises(Exception) as error:
        module.fill_holes(context, {"object_name": "Prop"})
    assert error.value.code in {"INVALID_SELECTION", "INVALID_ARGUMENT"}
    assert not calls


def test_fill_sets_only_new_face_material_and_uvs(repair):
    module, _, bm, calls, finishes, context = repair
    old_face = Element(0, material_index=0)
    bm.faces.append(old_face)
    result = module.fill_holes(context, {"object_name": "Prop", "material_index": 1})
    assert old_face.material_index == 0 and bm.faces[-1].material_index == 1
    assert result["boundary_loops"] == result["created_faces"] == 1
    assert result["new_face_uv_policy"] == "ZERO_INITIALIZED_UNPINNED"
    assert calls[0][0] == "fill" and finishes == [True]


def test_partial_fill_failure_retains_mutation_evidence(repair, monkeypatch):
    module, _, _, _, _, context = repair
    monkeypatch.setattr(module.bmesh.ops, "holes_fill", lambda *a, **kw: {"faces": []})
    with pytest.raises(Exception) as error:
        module.fill_holes(context, {"object_name": "Prop"})
    assert error.value.context["execution_started"] and error.value.context["verification_required"]


@pytest.mark.parametrize("tool", ["subdivide_selected", "merge_by_distance", "fill_holes"])
def test_precanceled_repair_does_not_enter_native_operator(repair, tool):
    module, _, _, calls, _, context = repair

    def cancel():
        raise RuntimeError("canceled")

    context.check_cancelled = cancel
    with pytest.raises(RuntimeError, match="canceled"):
        getattr(module, tool)(context, {"object_name": "Prop"})
    assert not calls


def test_repair_registry_permissions_checkpoint_and_wrappers(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.mesh_repair").register_tools(registry)
    definitions = {tool.name: tool for tool in load_mesh_definitions()}
    calls: list[Any] = []

    class Registry:
        async def call(self, method, arguments):
            calls.append((method, arguments))
            return {}

    tools = MeshTools(Registry())
    for tool in ("subdivide_selected", "merge_by_distance", "fill_holes"):
        name = f"mesh.{tool}"
        spec = registry.get(name)
        assert spec.modifies and spec.automatic_checkpoint and spec.toolset == "mesh"
        assert {p.value for p in spec.permissions} == {"EDIT_MESH"}
        assert definitions[name].modifying and definitions[name].required_permissions == ("EDIT_MESH",)
        asyncio.run(getattr(tools, f"mesh_{tool}")("Prop", selection_id="fresh"))
        assert calls[-1][0] == name
        assert calls[-1][1]["object_name"] == "Prop" and calls[-1][1]["selection_id"] == "fresh"
        assert name in {binding.name for binding in tools.bindings()}
    assert "mesh.merge_by_distance" in DESTRUCTIVE_TOOL_NAMES
