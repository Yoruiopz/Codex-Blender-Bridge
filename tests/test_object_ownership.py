"""Adversarial ownership checks for object, data and Action mutations."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


def _object(**fields):
    defaults = {
        "name": "Owned", "type": "MESH", "mode": "OBJECT",
        "library": None, "override_library": None, "is_editable": True,
        "data": SimpleNamespace(name="OwnedData", users=1, library=None,
                                override_library=None, is_editable=True, shape_keys=None),
        "animation_data": None,
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def _assert_unsupported(module, call):
    with pytest.raises(module.BridgeError) as error:
        call()
    assert error.value.code == module.ErrorCode.NOT_IMPLEMENTED


@pytest.mark.parametrize("field,value", [
    ("library", object()), ("override_library", object()), ("is_editable", False),
])
@pytest.mark.parametrize("module_name,handler", [
    ("transforms", "set_transform"), ("transforms", "translate"),
    ("transforms", "rotate"), ("transforms", "scale"),
    ("modifiers", "add_modifier"), ("modifiers", "set_modifier"),
    ("modifiers", "remove_modifier"), ("constraints", "add_constraint"),
    ("constraints", "set_constraint"), ("constraints", "remove_constraint"),
    ("animation", "insert_keyframe"), ("animation", "delete_keyframe"),
    ("rigging", "pose_transform"), ("rigging", "add_constraint"),
    ("rigging", "remove_constraint"),
])
def test_nonlocal_object_rejected_before_mutation(
    addon_package, monkeypatch, module_name, handler, field, value,
):
    module = importlib.import_module(f"{addon_package}.tools.{module_name}")
    obj = _object(type="ARMATURE" if module_name == "rigging" else "MESH")
    setattr(obj, field, value)
    monkeypatch.setattr(module, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(module, "require_blender", lambda: SimpleNamespace())
    original = dict(vars(obj))
    _assert_unsupported(module, lambda: getattr(module, handler)(None, {"object_name": obj.name}))
    assert vars(obj) == original


@pytest.mark.parametrize("module_name,handler", [
    ("transforms", "apply_transform"), ("modifiers", "apply_modifier"),
])
@pytest.mark.parametrize("ownership", ["shared", "library", "override", "readonly", "shape_keys"])
def test_data_application_rejected_before_operator_context_changes(
    addon_package, monkeypatch, module_name, handler, ownership,
):
    module = importlib.import_module(f"{addon_package}.tools.{module_name}")
    obj = _object()
    field, value = {
        "shared": ("users", 2), "library": ("library", object()),
        "override": ("override_library", object()), "readonly": ("is_editable", False),
        "shape_keys": ("shape_keys", object()),
    }[ownership]
    setattr(obj.data, field, value)
    monkeypatch.setattr(module, "get_object", lambda *args, **kwargs: obj)
    # No context/ops exist: ownership must fail before selection or mode changes.
    monkeypatch.setattr(module, "require_blender", lambda: SimpleNamespace())
    _assert_unsupported(module, lambda: getattr(module, handler)(None, {"object_name": obj.name}))
    assert obj.data.users == (2 if ownership == "shared" else 1)


@pytest.mark.parametrize("handler", ["insert_keyframe", "delete_keyframe"])
@pytest.mark.parametrize("action_scope", ["shared", "library", "override", "readonly"])
def test_keyframe_edit_cannot_change_protected_action(
    addon_package, monkeypatch, handler, action_scope,
):
    module = importlib.import_module(f"{addon_package}.tools.animation")
    action = SimpleNamespace(name="Protected", users=1, use_fake_user=False,
                             library=None, override_library=None, is_editable=True)
    field, value = {
        "shared": ("users", 2), "library": ("library", object()),
        "override": ("override_library", object()), "readonly": ("is_editable", False),
    }[action_scope]
    setattr(action, field, value)
    calls = []
    obj = _object(animation_data=SimpleNamespace(action=action),
                  keyframe_insert=lambda **kwargs: calls.append(kwargs),
                  keyframe_delete=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(module, "get_object", lambda *args, **kwargs: obj)
    _assert_unsupported(module, lambda: getattr(module, handler)(None, {
        "object_name": obj.name, "data_path": "location", "frame": 1,
    }))
    assert calls == []


@pytest.mark.parametrize("handler", ["insert_keyframe", "delete_keyframe"])
def test_object_keyframes_allow_shared_mesh_and_fake_user_action(
    addon_package, monkeypatch, handler,
):
    module = importlib.import_module(f"{addon_package}.tools.animation")
    action = SimpleNamespace(name="OwnAction", users=2, use_fake_user=True,
                             library=None, override_library=None, is_editable=True)
    calls = []
    obj = _object(animation_data=SimpleNamespace(action=action),
                  path_resolve=lambda path: (0.0, 0.0, 0.0),
                  keyframe_insert=lambda **kwargs: calls.append(kwargs) or True,
                  keyframe_delete=lambda **kwargs: calls.append(kwargs) or True)
    obj.data.users = 2
    monkeypatch.setattr(module, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(module, "require_blender", lambda: SimpleNamespace(
        context=SimpleNamespace(scene=SimpleNamespace(frame_current_final=1.0))))
    monkeypatch.setattr(module, "_matching_curves", lambda *args: ([], False))
    result = getattr(module, handler)(None, {"object_name": obj.name, "data_path": "location"})
    assert result["object"] == obj.name
    assert len(calls) == 1


def test_object_transform_allows_shared_linked_mesh_data(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.transforms")
    obj = _object(rotation_mode="XYZ", location=(0, 0, 0))
    obj.data.users = 2
    obj.data.library = object()
    monkeypatch.setattr(module, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(module, "serialize_transform", lambda target: {"object": target.name})
    result = module.set_transform(None, {"object_name": obj.name, "location": [1, 2, 3]})
    assert obj.location == (1.0, 2.0, 3.0)
    assert result["changed"] is True


@pytest.mark.parametrize("field,value", [
    ("users", 2), ("library", object()), ("override_library", object()), ("is_editable", False),
])
def test_armature_edit_rejects_shared_or_nonlocal_data_before_mode_change(
    addon_package, field, value,
):
    module = importlib.import_module(f"{addon_package}.tools.rigging")
    armature = _object(type="ARMATURE")
    setattr(armature.data, field, value)
    with pytest.raises(module.BridgeError) as error, module._edit_armature(armature):
        pytest.fail("Unsafe armature edit entered its mutation context")
    assert error.value.code == module.ErrorCode.NOT_IMPLEMENTED


def test_binding_rejects_shared_mesh_before_adding_groups(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.rigging")
    mesh = _object()
    mesh.data.users = 2
    monkeypatch.setattr(module, "get_object", lambda *args, **kwargs: mesh)
    _assert_unsupported(module, lambda: module.bind_mesh(None, {
        "mesh_object": mesh.name, "armature_object": "Rig", "method": "EMPTY_GROUPS",
    }))
