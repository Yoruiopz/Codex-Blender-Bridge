from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from mcp_server.tools.catalog import load_mesh_definitions
from mcp_server.tools.mesh import MeshTools


@pytest.fixture
def seams(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.mesh")
    edges = [SimpleNamespace(index=i, select=i < 2, hide=False, seam=i == 2) for i in range(4)]
    bm = SimpleNamespace(edges=edges, verts=[], faces=[])
    obj = SimpleNamespace(name="Cube", data=SimpleNamespace(users=1))
    monkeypatch.setattr(module, "_active_edit_mesh", lambda _: (None, obj, bm, {}))
    updates = []
    monkeypatch.setattr(module, "bmesh", SimpleNamespace(update_edit_mesh=lambda *a, **kw: updates.append(kw)))
    return module, obj, bm, updates


def test_seams_preserve_unselected_edges_and_selection(seams):
    module, _, bm, updates = seams
    selected = [edge.select for edge in bm.edges]
    result = module.mark_seams(None, {"object_name": "Cube"})
    assert [edge.seam for edge in bm.edges] == [True, True, True, False]
    assert [edge.select for edge in bm.edges] == selected
    assert result["changed_edges"] == 2 and result["seam_count_after"] == 3
    assert updates == [{"loop_triangles": False, "destructive": False}]
    assert not module.mark_seams(None, {"object_name": "Cube"})["changed"]
    assert len(updates) == 1
    cleared = module.mark_seams(None, {"object_name": "Cube", "seam": False})
    assert cleared["seam_count_after"] == 1
    assert bm.edges[2].seam


@pytest.mark.parametrize("params", [
    {"unknown": True}, {"object_name": ""}, {"object_name": "Cube", "seam": 1},
    {"object_name": "Cube", "selection_id": False},
])
def test_seams_reject_invalid_inputs_before_mutation(seams, params):
    module, _, bm, updates = seams
    with pytest.raises(Exception) as caught:
        module.mark_seams(None, params)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert not updates and not bm.edges[0].seam


@pytest.mark.parametrize("restriction", ["shared", "library", "override", "hidden", "empty"])
def test_seams_reject_unsafe_scope(seams, restriction):
    module, obj, bm, updates = seams
    if restriction == "shared":
        obj.data.users = 2
    elif restriction == "library":
        obj.data.library = object()
    elif restriction == "override":
        obj.override_library = object()
    elif restriction == "hidden":
        bm.edges[0].hide = True
    else:
        for edge in bm.edges:
            edge.select = False
    with pytest.raises(Exception) as caught:
        module.mark_seams(None, {"object_name": "Cube"})
    assert caught.value.code in {"NOT_IMPLEMENTED", "INVALID_SELECTION"}
    assert not updates and not bm.edges[0].seam


def test_seams_respect_reference_scope(seams, monkeypatch):
    module, _, bm, _ = seams
    monkeypatch.setattr(module, "validate_selection_reference", lambda *args: {"edges": [3]})
    result = module.mark_seams(None, {"object_name": "Cube", "selection_id": "valid"})
    assert result["edge_indices"] == [3]
    assert bm.edges[3].seam and not bm.edges[0].seam


def test_seams_restore_flags_on_update_failure(seams, monkeypatch):
    module, _, bm, _ = seams
    calls = []

    def update(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("injected update failure")

    monkeypatch.setattr(module.bmesh, "update_edit_mesh", update)
    with pytest.raises(Exception) as caught:
        module.mark_seams(None, {"object_name": "Cube"})
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_performed"] is True
    assert [edge.seam for edge in bm.edges] == [False, False, True, False]


def test_seams_bound_returned_edge_indices(seams):
    module, _, bm, _ = seams
    bm.edges = [SimpleNamespace(index=i, select=True, hide=False, seam=False) for i in range(300)]
    result = module.mark_seams(None, {"object_name": "Cube"})
    assert result["target_edge_count"] == result["changed_edges"] == 300
    assert len(result["edge_indices"]) == 256 and result["edge_indices_truncated"]


def test_seams_report_failed_rollback(seams, monkeypatch, caplog):
    module, _, _, _ = seams

    def update(*args, **kwargs):
        raise RuntimeError("update and recovery failure")

    monkeypatch.setattr(module.bmesh, "update_edit_mesh", update)
    with pytest.raises(Exception) as caught:
        module.mark_seams(None, {"object_name": "Cube"})
    assert caught.value.context["rollback_performed"] is False
    assert caught.value.context["verification_required"] is True
    assert "Failed to restore seam flags" in caplog.text


def test_seams_registry_checkpoint_permission_and_wrapper(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.mesh").register_tools(registry)
    spec = registry.get("mesh.mark_seams")
    assert spec.modifies and spec.automatic_checkpoint
    assert {permission.value for permission in spec.permissions} == {"EDIT_MESH"}
    definition = next(tool for tool in load_mesh_definitions() if tool.name == "mesh.mark_seams")
    assert definition.modifying and definition.required_permissions == ("EDIT_MESH",)
    calls = []

    class Registry:
        async def call(self, method, arguments):
            calls.append((method, arguments))
            return {"changed": True}

    tools = MeshTools(Registry())
    asyncio.run(tools.mesh_mark_seams("Cube", False, "selection"))
    assert calls == [("mesh.mark_seams", {"object_name": "Cube", "seam": False, "selection_id": "selection"})]
    assert "mesh.mark_seams" in {binding.name for binding in tools.bindings()}
