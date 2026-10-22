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
    class Owner(SimpleNamespace):
        __eq__ = object.__eq__
        __ne__ = object.__ne__
        __hash__ = object.__hash__

    class Items(list):
        active = None

        def get(self, name):
            return next((item for item in self if item.name == name), None)

    curves = Items(SimpleNamespace(data_path="location", array_index=index, extrapolation="CONSTANT",
                                  keyframe_points=[SimpleNamespace(co=[1., 0.], interpolation="BEZIER", easing="AUTO")],
                                  sampled_points=[], modifiers=[], group=None, mute=False) for index in range(3))
    action = Owner(name="OwnAction", users=2, use_fake_user=True, is_action_layered=False,
                   library=None, override_library=None, is_editable=True, fcurves=curves,
                   layers=[], slots=[], groups=[], pose_markers=[], asset_data=None)
    calls = []
    obj = Owner(**vars(_object(animation_data=SimpleNamespace(action=action, use_tweak_mode=False, drivers=[], nla_tracks=Items()),
                                path_resolve=lambda path: (0.0, 0.0, 0.0))))
    obj.user_of_id = lambda value: int(value is action)
    obj.bl_rna = SimpleNamespace(identifier="Object", properties=[])

    def insert(**kwargs):
        calls.append(kwargs)
        # The guard independently checks the existing exact requested values.
        return True

    def delete(**kwargs):
        calls.append(kwargs)
        for curve in curves:
            curve.keyframe_points.clear()
        return True

    obj.keyframe_insert, obj.keyframe_delete = insert, delete
    obj.data.users = 2
    scene = Owner(name="Scene", frame_current=1, frame_subframe=0., frame_current_final=1., frame_start=1,
                  frame_end=250, use_preview_range=False, frame_preview_start=0, frame_preview_end=0,
                  library=None, override_library=None, is_editable=True, objects=Items([obj]))
    obj.users_scene, obj.users_collection = [scene], []
    bpy = SimpleNamespace(context=SimpleNamespace(scene=scene, view_layer=SimpleNamespace(objects=Items([obj])), mode="OBJECT"),
                          data=SimpleNamespace(filepath="", scenes=Items([scene]), objects=Items([obj]), actions=Items([action]),
                              user_map=lambda *, subset: {value: {obj} if value is action else set() for value in subset}))
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry(enabled_toolsets=("animation",))
    module.register_tools(registry)
    context = registry_module.ToolContext(state=SimpleNamespace(snapshot=lambda: {"paused": False, "emergency_stopped": False}),
        permissions=permission_module.PermissionManager(lambda: {"EDIT_ANIMATION": True}), registry=registry, checkpoints=None)
    monkeypatch.setattr(module, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    result = getattr(module, handler)(context, {"object_name": obj.name, "data_path": "location"})
    assert result["object"] == obj.name
    assert len(calls) == 1
    assert result["protected_channels_preserved"]


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
