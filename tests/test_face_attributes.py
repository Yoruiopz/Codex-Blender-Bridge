from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.mesh import MeshTools


class Face:
    def __init__(self, index):
        self.fail = 0
        self.index, self.smooth, self.material_index, self.select, self.hide = index, False, 0, True, False
    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)
        if key == "material_index" and getattr(self, "fail", 0):
            self.fail -= 1
            raise RuntimeError("Injected post-assignment failure")


@pytest.fixture
def face_attributes(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.face_attributes")
    faces = [Face(index) for index in range(3)]
    bm = NS(faces=faces)
    obj = NS(name="Shell", data=NS(), material_slots=[NS(material=object()), NS(material=object())])
    grants = {"EDIT_MESH": True, "EDIT_MATERIALS": True}
    def require(*permissions):
        if any(not grants[p.value] for p in permissions):
            raise module.BridgeError("PERMISSION_DENIED", "permission denied")
    context = NS(require=require, check_cancelled=None)
    monkeypatch.setattr(module, "_active_edit_mesh", lambda *_: (None, obj, bm, None))
    monkeypatch.setattr(module, "require_local_single_user_mesh", lambda *_: None)
    monkeypatch.setattr(module, "validate_selection_reference", lambda *_: {"faces": [0, 2]})
    monkeypatch.setattr(module.mesh, "bmesh", NS(update_edit_mesh=lambda *_a, **_k: None))
    return module, context, obj, bm, grants


def params(**values):
    return {"object_name": "Shell", "selection_id": "fresh-reference", **values}


def test_only_referenced_faces_change_and_smooth_does_not_require_material_permission(face_attributes):
    module, context, _, bm, grants = face_attributes
    grants["EDIT_MATERIALS"] = False
    result = module.set_face_attributes(context, params(smooth=True))
    assert [face.smooth for face in bm.faces] == [True, False, True]
    assert result["attributes_verified"] and not result["topology_changed"] and not result["selection_changed"]
    grants["EDIT_MATERIALS"] = True
    module.set_face_attributes(context, params(material_index=1, smooth=False))
    assert [face.material_index for face in bm.faces] == [1, 0, 1]
    assert not any(face.smooth for face in bm.faces)


@pytest.mark.parametrize("values", [{}, {"smooth": 1}, {"smooth": None}, {"material_index": True},
    {"material_index": -1}, {"material_index": 256}, {"material_index": 2}, {"arbitrary": True},
    {"smooth": True, "selection_id": ""}])
def test_invalid_attributes_never_mutate(face_attributes, values):
    module, context, _, bm, _ = face_attributes
    with pytest.raises(module.BridgeError):
        module.set_face_attributes(context, params(**values))
    assert not any(face.smooth or face.material_index for face in bm.faces)


def test_missing_material_permission_precedes_material_read_and_mutation(face_attributes):
    module, context, obj, bm, grants = face_attributes
    grants["EDIT_MATERIALS"] = False
    del obj.material_slots
    with pytest.raises(module.BridgeError) as caught:
        module.set_face_attributes(context, params(material_index=1))
    assert caught.value.code == "PERMISSION_DENIED" and not any(face.material_index for face in bm.faces)


@pytest.mark.parametrize("kind", ["hidden", "empty_material", "shared", "stale", "empty_faces"])
def test_unsupported_scope_rejected_before_assignment(face_attributes, monkeypatch, kind):
    module, context, obj, bm, _ = face_attributes
    if kind == "hidden":
        bm.faces[2].hide = True
    elif kind == "empty_material":
        obj.material_slots[1].material = None
    elif kind == "empty_faces":
        monkeypatch.setattr(module, "validate_selection_reference", lambda *_: {"faces": []})
    else:
        def reject(*_a):
            raise module.BridgeError("NOT_IMPLEMENTED" if kind == "shared" else "INVALID_SELECTION", "scope denied")
        monkeypatch.setattr(module, "require_local_single_user_mesh" if kind == "shared" else "validate_selection_reference", reject)
    with pytest.raises(module.BridgeError):
        module.set_face_attributes(context, params(material_index=1))
    assert not any(face.material_index for face in bm.faces)


@pytest.mark.parametrize("failures,verified", [(1, True), (2, False)])
def test_partial_assignment_failure_restoration_is_measured(face_attributes, failures, verified):
    module, context, _, bm, _ = face_attributes
    bm.faces[0].fail = failures
    with pytest.raises(module.BridgeError) as caught:
        module.set_face_attributes(context, params(material_index=1))
    assert caught.value.context["rollback_verified"] is verified
    assert caught.value.context["possible_mutation"] is not verified
    assert caught.value.context["execution_started"] and caught.value.context["verification_required"]


def test_cancel_after_update_retains_error_and_measured_restoration(face_attributes, monkeypatch):
    module, context, _, bm, _ = face_attributes
    cancelled = [False]
    def check():
        if cancelled[0]:
            raise module.BridgeError("TIMEOUT", "cancelled")
    context.check_cancelled = check
    def update(*_a, **_k):
        cancelled[0] = True
    monkeypatch.setattr(module.mesh.bmesh, "update_edit_mesh", update)
    with pytest.raises(module.BridgeError) as caught:
        module.set_face_attributes(context, params(smooth=True))
    assert caught.value.code == "TIMEOUT" and caught.value.context["rollback_verified"]
    assert not any(face.smooth for face in bm.faces)


def test_mcp_strict_optional_attributes_and_forwarding():
    hints = get_type_hints(MeshTools.mesh_set_face_attributes, include_extras=True)
    for field, value in (("smooth", 1), ("material_index", True), ("material_index", 256)):
        with pytest.raises(ValidationError):
            TypeAdapter(hints[field]).validate_python(value)
    calls = []
    async def call(method, values):
        calls.append((method, values))
    asyncio.run(MeshTools(NS(call=call)).mesh_set_face_attributes("Shell", "ref", smooth=False, material_index=1))
    assert calls == [("mesh.set_face_attributes", {"object_name": "Shell", "selection_id": "ref", "smooth": False, "material_index": 1})]


def test_referenced_face_budget_rejects_before_assignment(face_attributes, monkeypatch):
    module, context, _, bm, _ = face_attributes
    monkeypatch.setattr(module, "MAX_FACES", 1)
    with pytest.raises(module.BridgeError) as caught:
        module.set_face_attributes(context, params(smooth=True))
    assert caught.value.code == "INVALID_SELECTION" and not any(face.smooth for face in bm.faces)


def test_registry_declares_static_mesh_gate_and_checkpoint(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.face_attributes")
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    module.register_tools(registry)
    spec = registry.get("mesh.set_face_attributes")
    assert spec.modifies and spec.automatic_checkpoint and spec.toolset == "mesh"
    assert spec.permissions == frozenset({module.Permission.EDIT_MESH})
