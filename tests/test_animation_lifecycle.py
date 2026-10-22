from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.animation_lifecycle import (
    DESTRUCTIVE_TOOL_NAMES,
    TOOL_DATA,
    TOOL_NAMES,
    ActionLifecycleTools,
    load_definitions,
)


class Items(list):
    active = None

    def get(self, name):
        return next((item for item in self if item.name == name), None)


class ID(dict):
    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

    def __init__(self, name, **attributes):
        super().__init__()
        self.name, self.library, self.override_library, self.is_editable = name, None, None, True
        self.__dict__.update(attributes)


class Slots(Items):
    def new(self, target_id_type, name):
        slot = NS(identifier="OB"+name, handle=len(self)+1, target_id_type=target_id_type)
        self.append(slot)
        return slot


class Strips(Items):
    def new(self, *, type):
        bags = Items()

        def channelbag(slot, ensure=False):
            existing = next((bag for bag in bags if bag.slot_handle == slot.handle), None)
            if existing is not None or not ensure:
                return existing
            result = NS(slot_handle=slot.handle, fcurves=Items(), groups=Items())
            bags.append(result)
            return result

        strip = NS(type=type, channelbags=bags, channelbag=channelbag)
        self.append(strip)
        return strip


class Layers(Items):
    def new(self, name):
        layer = NS(name=name, strips=Strips())
        self.append(layer)
        return layer


class Action(ID):
    def __init__(self, name, env):
        super().__init__(name, slots=Slots(), layers=Layers(), is_action_layered=True, is_action_legacy=False,
                         use_fake_user=False, asset_data=None, pose_markers=Items(), groups=Items())
        self.env = env

    @property
    def users(self):
        return sum(obj.user_of_id(self) for obj in self.env.objects) + int(self.use_fake_user)


class Actions(Items):
    def __init__(self, env):
        super().__init__()
        self.env = env

    def new(self, name):
        action = Action(name, self.env)
        self.append(action)
        return action

    def remove(self, action, *, do_unlink):
        assert do_unlink is False
        if action.users:
            raise RuntimeError("Action still in use")
        super().remove(action)


class AnimData:
    def __init__(self):
        self._action = self._slot = None
        self.use_tweak_mode, self.use_nla = False, True
        self.drivers, self.nla_tracks = [], Items()
        self.action_blend_type, self.action_extrapolation, self.action_influence = "REPLACE", "HOLD", 1.
        self.fail_once = None

    @property
    def action(self):
        return self._action

    @action.setter
    def action(self, value):
        prior_slot = self._slot
        self._action = value
        self._slot = next((slot for slot in getattr(value, "slots", ()) if prior_slot is not None and slot.identifier == prior_slot.identifier), None)
        if self.fail_once == "action":
            self.fail_once = None
            raise RuntimeError("Partial Action binding setter")

    @property
    def action_slot(self):
        return self._slot

    @action_slot.setter
    def action_slot(self, slot):
        self._slot = slot
        if self.fail_once == "slot":
            self.fail_once = None
            raise RuntimeError("Partial slot setter")


@pytest.fixture
def lifecycle(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.animation_lifecycle")
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    env = NS(objects=Items())
    actions = Actions(env)
    source, target = actions.new("Source"), actions.new("Target")
    for action in (source, target):
        slot = action.slots.new("OBJECT", "Actor")
        action.layers.new("Layer").strips.new(type="KEYFRAME").channelbag(slot, ensure=True)
    obj = ID("Actor", type="EMPTY", data=None, mode="OBJECT", animation_data=AnimData(), rotation_mode="XYZ",
             bl_rna=NS(identifier="Object"))
    env.objects.append(obj)
    obj.animation_data.action, obj.animation_data.action_slot = source, source.slots[0]
    obj.user_of_id = lambda action: int(obj.animation_data is not None and obj.animation_data.action == action) + sum(
        int(strip.action == action) for track in (() if obj.animation_data is None else obj.animation_data.nla_tracks) for strip in track.strips)

    def create():
        obj.animation_data = AnimData()
        return obj.animation_data

    obj.animation_data_create, obj.animation_data_clear = create, lambda: setattr(obj, "animation_data", None)
    scene = ID("Scene", objects=env.objects)
    obj.users_scene, obj.users_collection = [scene], []
    external = {}

    def users(*, subset):
        return {value: {owner for owner in env.objects if owner.user_of_id(value)} | external.get(value, set()) for value in subset}

    bpy = NS(data=NS(actions=actions, objects=env.objects, user_map=users, filepath=""),
             context=NS(scene=scene, mode="OBJECT", view_layer=NS(objects=env.objects)))
    flags = {"paused": False, "emergency_stopped": False}
    grants = {permission.value: True for permission in permission_module.Permission}
    registry = registry_module.ToolRegistry(enabled_toolsets=("animation",))
    module.register_tools(registry)
    context = registry_module.ToolContext(state=NS(snapshot=lambda: dict(flags)), permissions=permission_module.PermissionManager(lambda: grants),
                                          registry=registry, checkpoints=None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    return NS(module=module, context=context, bpy=bpy, obj=obj, source=source, target=target, actions=actions,
              objects=env.objects, flags=flags, grants=grants, external=external)


def bind(fixture, **changes):
    return fixture.module.action_bind(fixture.context, {"object_name": "Actor", "action_name": "Target", "expected_action_name": "Source",
        "slot_identifier": "OBActor", "affected_objects": [], "allow_session_only_previous": True, **changes})


def test_addon_mcp_metadata_and_explicit_null_wrapper_contract(lifecycle):
    assert set(lifecycle.context.registry.list_tools()) == set(TOOL_NAMES)
    assert tuple(item.name for item in load_definitions()) == TOOL_NAMES
    assert tuple(item.name for item in ActionLifecycleTools(None).bindings()) == TOOL_NAMES
    assert {"animation.action_update", "animation.action_remove"} == DESTRUCTIVE_TOOL_NAMES
    for tool_name, _, modifies, permissions in TOOL_DATA:
        spec = lifecycle.context.registry.get(tool_name)
        assert spec.modifies == modifies and {item.value for item in spec.permissions} == set(permissions)

    class Registry:
        async def call(self, tool_name, params):
            return tool_name, params

    result = asyncio.run(ActionLifecycleTools(Registry()).animation_action_bind("Actor", None, "Source", []))
    assert result == ("animation.action_bind", {"object_name": "Actor", "action_name": None, "expected_action_name": "Source",
                                              "affected_objects": [], "allow_session_only_previous": False})


def test_create_inspect_rename_retain_clear_and_remove_without_hidden_binding(lifecycle):
    mod, context = lifecycle.module, lifecycle.context
    created = mod.action_create(context, {"action_name": "New", "slot_name": "Motion", "keep_on_save": True})
    assert created["keep_on_save"] and created["slot_identifier"] == "OBMotion" and not created["bound"]
    assert lifecycle.obj.animation_data.action == lifecycle.source
    changed = mod.action_update(context, {"action_name": "New", "new_name": "Renamed", "keep_on_save": False})
    assert changed["action"] == "Renamed" and changed["retention"] == "SESSION_ONLY"
    inspected = mod.action_inspect(context, {"action_name": "Renamed"})
    assert inspected["real_users"] == 0 and inspected["content_complete_within_limits"]
    removed = mod.action_remove(context, {"action_name": "Renamed", "confirm": True})
    assert removed["removed"] and lifecycle.actions.get("Renamed") is None


def test_bind_exact_slot_and_clear_preserve_source_keys_and_explicit_retention_warning(lifecycle):
    content = lifecycle.module.scope.action_content(lifecycle.source)
    result = bind(lifecycle)
    assert result["previous_session_only"] and result["source_channels_preserved"]
    assert lifecycle.obj.animation_data.action == lifecycle.target and lifecycle.obj.animation_data.action_slot == lifecycle.target.slots[0]
    assert lifecycle.module.scope.action_content(lifecycle.source) == content
    bind(lifecycle, action_name=None, expected_action_name="Target", slot_identifier=None)
    assert lifecycle.obj.animation_data.action is None and lifecycle.obj.animation_data.action_slot is None


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_unknown_parameters_fail_before_blender(lifecycle, tool_name):
    with pytest.raises(lifecycle.module.BridgeError) as error:
        getattr(lifecycle.module, tool_name.split(".")[1])(None, {"unknown": True})
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("change", [{"expected_action_name": None}, {"slot_identifier": None}, {"slot_identifier": "Other"},
    {"affected_objects": [None]}, {"affected_objects": ["Actor"]}, {"allow_session_only_previous": False},
    {"allow_session_only_previous": "yes"}])
def test_ambiguous_or_unacknowledged_binding_fails_without_assigning(lifecycle, change):
    with pytest.raises(lifecycle.module.BridgeError):
        bind(lifecycle, **change)
    assert lifecycle.obj.animation_data.action == lifecycle.source


@pytest.mark.parametrize("permission", ["EDIT_ANIMATION", "DELETE_OBJECTS"])
def test_clearing_persistent_retention_requires_independent_live_deletion_consent(lifecycle, permission):
    lifecycle.target.use_fake_user = True
    lifecycle.grants[permission] = False
    with pytest.raises(lifecycle.module.BridgeError) as error:
        lifecycle.module.action_update(lifecycle.context, {"action_name": "Target", "keep_on_save": False})
    assert error.value.code == "PERMISSION_DENIED" and lifecycle.target.use_fake_user
    assert error.value.context["missing_permissions"] == [permission]


@pytest.mark.parametrize("problem", ["linked", "override", "in_use", "retained", "no_confirm"])
def test_unused_remove_never_unlinks_or_unpins_implicitly(lifecycle, problem):
    target = lifecycle.target
    if problem == "linked":
        target.library = object()
    elif problem == "override":
        target.override_library = object()
    elif problem == "in_use":
        lifecycle.obj.animation_data.action = target
    elif problem == "retained":
        target.use_fake_user = True
    with pytest.raises(lifecycle.module.BridgeError):
        lifecycle.module.action_remove(lifecycle.context, {"action_name": "Target", "confirm": problem != "no_confirm"})
    assert target in lifecycle.actions


@pytest.mark.parametrize("change", ["pause", "emergency", "permission", "cancel", "owner_id", "action_id", "slot", "content", "context", "consumer"])
def test_binding_final_gate_rechecks_exact_ids_content_context_and_live_consent(lifecycle, change):
    def callback():
        if change in {"pause", "emergency"}:
            lifecycle.flags["paused" if change == "pause" else "emergency_stopped"] = True
        elif change == "permission":
            lifecycle.grants["EDIT_ANIMATION"] = False
        elif change == "cancel":
            raise lifecycle.module.BridgeError(lifecycle.module.ErrorCode.OPERATION_FAILED, "Canceled")
        elif change == "owner_id":
            lifecycle.objects[:] = [ID("Actor")]
        elif change == "action_id":
            lifecycle.actions.remove(lifecycle.target, do_unlink=False)
            lifecycle.actions.new("Target")
        elif change == "slot":
            lifecycle.target.slots[0].identifier = "OBNewSlot"
        elif change == "content":
            lifecycle.target.layers[0].name = "New Layer"
        elif change == "context":
            lifecycle.obj.animation_data.use_nla = False
        else:
            lifecycle.external[lifecycle.obj] = {ID("Outside", bl_rna=NS(identifier="NodeTree"))}

    lifecycle.context.check_cancelled = callback
    with pytest.raises(lifecycle.module.BridgeError):
        bind(lifecycle)
    assert lifecycle.obj.animation_data.action == lifecycle.source


@pytest.mark.parametrize("failure", ["action", "slot"])
def test_known_partial_binding_setter_restores_exact_previous_action_and_slot(lifecycle, failure):
    lifecycle.obj.animation_data.fail_once = failure
    with pytest.raises(lifecycle.module.BridgeError) as error:
        bind(lifecycle)
    assert error.value.context["rollback_verified"] and not error.value.context["possible_mutation"]
    assert lifecycle.obj.animation_data.action == lifecycle.source and lifecycle.obj.animation_data.action_slot == lifecycle.source.slots[0]


@pytest.mark.parametrize("change", ["pause", "emergency", "cancel", "permission", "newer_binding", "newer_slot", "source_content"])
def test_postwrite_changes_refuse_stale_binding_compensation(lifecycle, change):
    fired = False
    other_slot = lifecycle.target.slots.new("OBJECT", "Other")

    def callback():
        nonlocal fired
        if lifecycle.obj.animation_data.action != lifecycle.target:
            return
        if change == "cancel":
            raise lifecycle.module.BridgeError(lifecycle.module.ErrorCode.OPERATION_FAILED, "Canceled")
        if fired:
            return
        fired = True
        if change in {"pause", "emergency"}:
            lifecycle.flags["paused" if change == "pause" else "emergency_stopped"] = True
        elif change == "permission":
            lifecycle.grants["EDIT_ANIMATION"] = False
        elif change == "newer_binding":
            lifecycle.obj.animation_data.action = None
        elif change == "newer_slot":
            lifecycle.obj.animation_data.action_slot = other_slot
        else:
            lifecycle.source.layers[0].name = "Manual source edit"

    lifecycle.context.check_cancelled = callback
    with pytest.raises(lifecycle.module.BridgeError) as error:
        bind(lifecycle)
    assert not error.value.context["rollback_verified"] and error.value.context["possible_mutation"]
    assert lifecycle.obj.animation_data.action == (None if change == "newer_binding" else lifecycle.target)
    if change == "newer_slot":
        assert lifecycle.obj.animation_data.action_slot == other_slot


def test_final_gate_same_name_action_replacement_is_not_removed(lifecycle):
    replacement = None

    def callback():
        nonlocal replacement
        if replacement is None:
            lifecycle.actions.remove(lifecycle.target, do_unlink=False)
            replacement = lifecycle.actions.new("Target")

    lifecycle.context.check_cancelled = callback
    with pytest.raises(lifecycle.module.BridgeError):
        lifecycle.module.action_remove(lifecycle.context, {"action_name": "Target", "confirm": True})
    assert replacement in lifecycle.actions


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
@pytest.mark.parametrize("callback", ["permission_provider", "registry_prepare"])
def test_live_stop_created_by_last_authority_callback_prevents_allocation(lifecycle, flag, callback):
    if callback == "permission_provider":
        manager = type(lifecycle.context.permissions)

        def source():
            lifecycle.flags[flag] = True
            return lifecycle.grants

        lifecycle.context.permissions = manager(source)
        lifecycle.context.registry = None
    else:
        lifecycle.context.registry = NS(prepare=lambda *args: lifecycle.flags.update({flag: True}),
                                        get=lambda _: NS(toolset="animation"), enabled_toolsets=("animation",))
    with pytest.raises(lifecycle.module.BridgeError) as error:
        lifecycle.module.action_create(lifecycle.context, {"action_name": "Must Not Allocate", "slot_name": "Owner", "keep_on_save": False})
    assert error.value.code == ("AGENT_PAUSED" if flag == "paused" else "EMERGENCY_STOPPED")
    assert lifecycle.actions.get("Must Not Allocate") is None


def test_particle_context_reference_is_exactly_counted_frozen_and_never_hides_an_extra_scene_user(lifecycle):
    scene, obj = lifecycle.bpy.context.scene, lifecycle.obj
    particle = NS(object=obj, brush=NS(name="Particle Brush"))
    scene.tool_settings = NS(particle_edit=particle)
    scene.collection = NS(objects=Items([obj]), user_of_id=lambda owner: 1)
    scene.view_layers = [lifecycle.bpy.context.view_layer]
    scene.user_of_id = lambda owner: 3
    lifecycle.external[obj] = {scene}
    first = lifecycle.module.scope.affected_scope(lifecycle.bpy, obj, [])
    assert first[1][0][3] == "PARTICLE_EDIT_CONTEXT"
    particle.brush.name = "Changed Brush"
    assert lifecycle.module.scope.affected_scope(lifecycle.bpy, obj, []) != first
    scene.user_of_id = lambda owner: 4
    with pytest.raises(lifecycle.module.BridgeError):
        lifecycle.module.scope.affected_scope(lifecycle.bpy, obj, [])
