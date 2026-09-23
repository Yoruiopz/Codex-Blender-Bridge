from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("owner,restriction", [
    ("mesh", "shared"), ("object", "library"), ("mesh", "library"),
    ("object", "override_library"), ("mesh", "override_library"),
])
def test_mesh_ownership_rejects_unsafe_assets(addon_package, owner, restriction):
    module = importlib.import_module(f"{addon_package}.tools._mesh_safety")
    obj = SimpleNamespace(name="Target", data=SimpleNamespace(users=1))
    if restriction == "shared":
        obj.data.users = 2
    else:
        setattr(obj if owner == "object" else obj.data, restriction, object())
    with pytest.raises(Exception) as caught:
        module.require_local_single_user_mesh(obj)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["object"] == "Target"


def test_mesh_ownership_accepts_local_single_user(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._mesh_safety")
    module.require_local_single_user_mesh(SimpleNamespace(name="Target", data=SimpleNamespace(users=1)))


def test_edit_mesh_rejects_before_bmesh_access(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.mesh")
    obj = SimpleNamespace(name="Target", type="MESH", mode="EDIT", data=SimpleNamespace(users=2))
    monkeypatch.setattr(module, "get_object", lambda name: obj)
    monkeypatch.setattr(module, "bmesh", SimpleNamespace(from_edit_mesh=lambda data: pytest.fail("BMesh accessed")))
    with pytest.raises(Exception) as caught:
        module._edit_bmesh({"object_name": "Target"})
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_uv_rejects_before_operator_or_layer_creation(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.uv")
    obj = SimpleNamespace(name="Target", type="MESH", mode="EDIT", data=SimpleNamespace(users=2))
    bpy = SimpleNamespace(context=SimpleNamespace(
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=obj)), objects_in_mode_unique_data=[obj],
    ))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    operator = SimpleNamespace(poll=lambda: pytest.fail("Operator queried before ownership check"))
    with pytest.raises(Exception) as caught:
        module._operation_context(obj, {}, operator=operator)
    assert caught.value.code == "NOT_IMPLEMENTED"
