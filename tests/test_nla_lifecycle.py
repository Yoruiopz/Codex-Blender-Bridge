from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest
from nla_test_support import Tracks, make_env

from mcp_server.tools.nla_lifecycle import (
    DESTRUCTIVE_TOOL_NAMES,
    TOOL_DATA,
    TOOL_NAMES,
    NlaLifecycleTools,
    load_definitions,
)


@pytest.fixture
def lifecycle(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.nla_lifecycle")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    env = make_env(module, monkeypatch, permissions)
    env.bpy.app, env.bpy.context.window = NS(background=True, translations=NS(pgettext_data=lambda value: value)), None
    env.track = env.tracks.new()
    env.track.name = "Motion"
    env.source = env.action()
    env.permission = permissions.Permission
    return module, env


def clip_params(**extra):
    return {"object_name": "Actor", "affected_objects": [], "track_name": "Motion",
            "strip_name": "Walk", "action_name": "Walk", "frame_start": 1, **extra}


def test_metadata_and_typed_wrappers_preserve_explicit_scope(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.nla_lifecycle")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()
    module.register_tools(registry)
    definitions = load_definitions()
    assert registry.list_tools() == tuple(sorted(TOOL_NAMES))
    assert tuple(item.name for item in definitions) == TOOL_NAMES
    assert all(item.toolset == "animation_layers" and item.modifying for item in definitions)
    assert all(item.required_permissions == ("EDIT_ANIMATION",) for item in definitions)
    assert {"nla.transition_remove"} == DESTRUCTIVE_TOOL_NAMES
    for name, _, _, permissions in TOOL_DATA:
        spec = registry.get(name)
        assert spec.modifies and spec.automatic_checkpoint
        assert tuple(permission.value for permission in spec.permissions) == permissions
    calls = []
    async def call(name, params):
        calls.append((name, params))
    tools = NlaLifecycleTools(NS(call=call))
    asyncio.run(tools.nla_clip_add("Actor", ["Skin"], "Motion", "Walk", "Walk", 12, "OBActor"))
    asyncio.run(tools.nla_transition_add("Actor", [], "Motion", "Left", "Right", "Blend"))
    asyncio.run(tools.nla_transition_remove("Actor", [], "Motion", "Left", "Right", "Blend", True))
    asyncio.run(tools.nla_track_reorder("Actor", [], ["Motion", "Protected"]))
    assert calls[0][1]["slot_identifier"] == "OBActor" and calls[0][1]["affected_objects"] == ["Skin"]
    assert calls[2][1]["confirm"] is True and calls[3][1]["track_names"] == ["Motion", "Protected"]


def test_exact_clip_add_preserves_action_and_existing_neighbor(lifecycle):
    module, env = lifecycle
    original = env.track.strips.new("Neighbor", 40, env.source)
    original.select = False
    result = module.clip_add(env.context, clip_params())
    assert result["added"] and not result["action_channels_changed"]
    assert env.track.strips[-1] is original and original.frame_start == 40 and original.select is False
    assert result["action_content_digests"][0]["name"] == "Walk"
    assert len(env.track.strips) == 2 and env.source.users == 2


@pytest.mark.parametrize("condition,code", [
    ("denied", "PERMISSION_DENIED"), ("pause", "AGENT_PAUSED"),
    ("stop", "EMERGENCY_STOPPED"), ("cancel", "TIMEOUT"),
    ("linked", "NOT_IMPLEMENTED"), ("override", "NOT_IMPLEMENTED"),
])
def test_clip_write_boundary_rejects_revoked_or_foreign_scope(lifecycle, condition, code):
    module, env = lifecycle
    if condition == "denied":
        env.grants[env.permission.EDIT_ANIMATION.value] = False
    elif condition in {"pause", "stop"}:
        env.flags["paused" if condition == "pause" else "emergency_stopped"] = True
    elif condition == "cancel":
        def cancelled():
            raise module.BridgeError(module.ErrorCode.TIMEOUT, "Disconnected fixture")
        env.context.check_cancelled = cancelled
    else:
        setattr(env.obj, "library" if condition == "linked" else "override_library", object())
    with pytest.raises(module.BridgeError) as caught:
        module.clip_add(env.context, clip_params())
    assert caught.value.code == code and not env.track.strips


def test_permission_provider_interleaving_cannot_be_adopted_before_write(lifecycle):
    module, env = lifecycle
    original_require = env.context.require
    invocations = 0
    def provider(*permissions):
        nonlocal invocations
        original_require(*permissions)
        invocations += 1
        if invocations == 2:
            env.track.mute = True
    env.context.require = provider
    with pytest.raises(module.BridgeError) as caught:
        module.clip_add(env.context, clip_params())
    assert caught.value.context["stale_nla_scope"] and not env.track.strips
    assert env.track.mute is True


def test_permission_revoked_after_constructor_retains_named_strip_without_cleanup(lifecycle, monkeypatch):
    module, env = lifecycle
    original = env.track.strips.new
    def allocate(*args):
        result = original(*args)
        env.grants[env.permission.EDIT_ANIMATION.value] = False
        return result
    monkeypatch.setattr(env.track.strips, "new", allocate)
    with pytest.raises(module.BridgeError) as caught:
        module.clip_add(env.context, clip_params())
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]
    assert caught.value.context["retained_strip_name"] == "Walk"
    assert len(env.track.strips) == 1 and env.source.users == 1


def test_same_name_action_replacement_after_preflight_refuses_clip_write(lifecycle, monkeypatch):
    module, env = lifecycle
    original_require = env.context.require
    def provider(*permissions):
        original_require(*permissions)
        if len(env.actions) == 1:
            env.source.name = "Renamed Manually"
            env.action("Walk")
    env.context.require = provider
    with pytest.raises(module.BridgeError):
        module.clip_add(env.context, clip_params())
    assert not env.track.strips
    assert env.actions.get("Walk") is not env.source


@pytest.mark.parametrize("params", [
    {"strip_name": ""}, {"strip_name": "界"*22}, {"strip_name": "a\n"},
    {"frame_start": True}, {"frame_start": 100_001}, {"slot_identifier": "unknown"},
    {"unknown": True},
])
def test_clip_malformed_or_unreviewed_input_has_no_side_effect(lifecycle, params):
    module, env = lifecycle
    with pytest.raises(module.BridgeError):
        module.clip_add(env.context, clip_params(**params))
    assert not env.track.strips


def test_overlap_and_animated_shared_data_channels_fail_before_new_binding(lifecycle):
    module, env = lifecycle
    env.track.strips.new("Existing", 1, env.source)
    with pytest.raises(module.BridgeError):
        module.clip_add(env.context, clip_params())
    assert len(env.track.strips) == 1
    env.track.strips.clear()
    env.source.fcurves = [NS(data_path="data.materials[0].diffuse_color", array_index=0,
                            keyframe_points=[], sampled_points=[], modifiers=[])]
    with pytest.raises(module.BridgeError) as caught:
        module.clip_add(env.context, clip_params())
    assert caught.value.code == "NOT_IMPLEMENTED" and not env.track.strips


def test_transition_requires_real_ui_and_removal_requires_confirmation(lifecycle):
    module, env = lifecycle
    env.track.strips.new("Left", 1, env.source)
    env.track.strips.new("Right", 21, env.source)
    params = {"object_name": "Actor", "track_name": "Motion", "affected_objects": [],
              "left_strip": "Left", "right_strip": "Right"}
    with pytest.raises(module.BridgeError) as caught:
        module.transition_add(env.context, {**params, "new_name": "Blend"})
    assert caught.value.code == "NOT_IMPLEMENTED" and not caught.value.context["possible_mutation"]
    with pytest.raises(module.BridgeError):
        module.transition_remove(env.context, {**params, "transition_name": "Blend"})
    assert len(env.track.strips) == 2


@pytest.mark.parametrize("names", [[], ["Motion", "Motion"], ["missing"], "Motion", [1]])
def test_reorder_requires_exact_complete_permutation(lifecycle, names):
    module, env = lifecycle
    with pytest.raises(module.BridgeError):
        module.track_reorder(env.context, {"track_names": names})
    assert env.tracks[0] is env.track


@pytest.fixture
def legacy(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.animation_layers")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    env = make_env(module, monkeypatch, permissions, tracks=Tracks())
    env.track = env.tracks.new()
    env.track.name = "Motion"
    env.source = env.action()
    env.data.action = env.source
    env.permission = permissions.Permission
    return module, env


@pytest.mark.parametrize("state,code", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")])
def test_legacy_solo_live_stop_prevents_all_writes(legacy, state, code):
    module, env = legacy
    env.flags[state] = True
    with pytest.raises(module.BridgeError) as caught:
        module.nla_solo_track(env.context, {"track_name": "Motion", "enabled": True})
    assert caught.value.code == code and env.track.is_solo is False


def test_legacy_permission_revocation_between_solo_writes_never_compensates_without_consent(legacy):
    module, env = legacy
    other = env.tracks.new()
    other.name, other.is_solo = "Previous", True
    count = 0
    def checkpoint():
        nonlocal count
        count += 1
        if count >= 2:
            env.grants[env.permission.EDIT_ANIMATION.value] = False
    env.context.check_cancelled = checkpoint
    with pytest.raises(module.BridgeError) as caught:
        module.nla_solo_track(env.context, {"track_name": "Motion", "enabled": True, "replace_existing": True})
    assert caught.value.code == "PERMISSION_DENIED" and caught.value.context["possible_mutation"]
    assert not other.is_solo and not env.track.is_solo
    assert not caught.value.context["rollback_verified"]


def test_legacy_manual_interleaving_preserves_the_manual_change_and_refuses_followup(legacy):
    module, env = legacy
    calls = 0
    def manual():
        nonlocal calls
        calls += 1
        if calls == 1:
            env.track.mute = True
    env.context.check_cancelled = manual
    with pytest.raises(module.BridgeError) as caught:
        module.nla_solo_track(env.context, {"track_name": "Motion", "enabled": True})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert env.track.mute and not env.track.is_solo


def test_legacy_constructor_partial_failure_does_not_delete_foreign_allocation(legacy, monkeypatch):
    module, env = legacy
    allocate = env.tracks.new
    def foreign(**kwargs):
        result = allocate(**kwargs)
        result.mute = True  # Simulate a callback changing the new constructor scope.
        return result
    monkeypatch.setattr(env.tracks, "new", foreign)
    with pytest.raises(module.BridgeError) as caught:
        module.nla_push_down(env.context, {"track_name": "New", "strip_name": "Walk"})
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]
    assert caught.value.context["retained_track"]["name"] == "NlaTrack"
    assert len(env.tracks) == 2 and env.tracks[-1].mute
    assert env.data.action is env.source


@pytest.mark.parametrize("field,value", [("use_animated_influence", True)])
def test_legacy_influence_allocation_without_native_preferences_fails_before_writes(legacy, monkeypatch, field, value):
    module, env = legacy
    strip = env.track.strips.new("Walk", 1, env.source)
    monkeypatch.setattr(module, "prepare_assignments", lambda *args, **kwargs: [NS(name=field, value=value)])
    with pytest.raises(module.BridgeError) as caught:
        module.nla_edit(env.context, {"track_name": "Motion", "strip_name": "Walk", "settings": {field: value}})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert getattr(strip, field) is False


def test_legacy_timing_model_accounts_for_aliases_native_storage_and_blend_clamping(legacy):
    module, _env = legacy
    settings = {"frame_start": 1., "frame_end": 11., "frame_start_raw": 1., "frame_start_ui": 1.,
                "frame_end_raw": 11., "frame_end_ui": 11., "action_frame_start": 1.,
                "action_frame_end": 11., "scale": 1., "repeat": 1., "blend_in": 3., "blend_out": 2.}
    after = module._strip_stage(settings, "scale", .5)
    assert after["frame_end"] == after["frame_end_ui"] == after["frame_end_raw"] == 6.
    assert after["blend_in"] == 3. and after["blend_out"] == 2.
    with pytest.raises(module.BridgeError):
        module._strip_stage(settings, "frame_end", .5)


def test_constructor_scope_cannot_adopt_a_callback_reversed_new_clip(lifecycle, monkeypatch):
    module, env = lifecycle
    original = env.track.strips.new
    def manual(*args):
        result = original(*args)
        result.use_reverse = True
        return result
    monkeypatch.setattr(env.track.strips, "new", manual)
    with pytest.raises(module.BridgeError) as caught:
        module.clip_add(env.context, clip_params())
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]
    assert env.track.strips[0].use_reverse is True


def test_auto_blend_prediction_protects_other_strip_before_a_native_setter(legacy, monkeypatch):
    module, env = legacy
    strip = env.track.strips.new("Walk", 1, env.source)
    other = env.tracks.new()
    neighbor = other.strips.new("Protected", 7, env.source)
    neighbor.use_auto_blend = True
    before = [(item.blend_in, item.blend_out, item.use_auto_blend) for track in env.tracks for item in track.strips]
    monkeypatch.setattr(module, "prepare_assignments", lambda *args, **kwargs: [NS(name="use_auto_blend", value=True)])
    with pytest.raises(module.BridgeError) as caught:
        module.nla_edit(env.context, {"track_name": "Motion", "strip_name": "Walk", "settings": {"use_auto_blend": True}})
    assert caught.value.code == "NOT_IMPLEMENTED" and "protected_strip_native_id" in caught.value.context
    assert [(item.blend_in, item.blend_out, item.use_auto_blend) for track in env.tracks for item in track.strips] == before
    assert not strip.use_auto_blend


def test_complete_control_snapshot_rejects_scripted_or_unknown_control_paths(legacy):
    module, env = legacy
    strip = env.track.strips.new("Walk", 1, env.source)
    for path, driver in (("location", None), ("influence", object())):
        strip.fcurves = [NS(data_path=path, array_index=0, driver=driver, keyframe_points=[])]
        with pytest.raises(module.BridgeError) as caught:
            module._LegacyNlaGuard(env.context, env.obj, "nla.edit_strip")
        assert caught.value.code == "NOT_IMPLEMENTED"


def test_editor_records_temporary_setting_before_a_post_setter_denial(lifecycle):
    module, _env = lifecycle
    editor = module._Editor.__new__(module._Editor)
    path = ("editor", "only_selected")
    owner = NS(show_only_selected=False)
    expected = {path: False}
    def set_field(target, field, value, changed_path, _observed=None):
        setattr(target, field, value)
        expected[changed_path] = value
        raise module.BridgeError("PERMISSION_DENIED", "Revoked after native setter")
    editor.proof, editor.restore = NS(expected=expected, set=set_field), []
    with pytest.raises(module.BridgeError):
        editor.setting(owner, "show_only_selected", True, path)
    assert editor.restore == [(owner, "show_only_selected", False, path)]
    assert owner.show_only_selected is True


@pytest.mark.parametrize("state,code", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")])
def test_legacy_permission_provider_cannot_pause_then_allow_a_write(legacy, state, code):
    module, env = legacy
    original_require = env.context.require
    def provider(*permissions):
        original_require(*permissions)
        env.flags[state] = True
    env.context.require = provider
    with pytest.raises(module.BridgeError) as caught:
        module.nla_solo_track(env.context, {"track_name": "Motion", "enabled": True})
    assert caught.value.code == code and not env.track.is_solo


def test_transition_constructor_rejects_foreign_settings_and_controls(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._nla_controls")
    strip = NS(name="Transition", type="TRANSITION", active=False, action=None, action_slot=None,
               action_slot_handle=0, last_slot_identifier="", frame_start=11., frame_end=21.,
               action_frame_start=0., action_frame_end=0., extrapolation="HOLD", blend_type="REPLACE",
               scale=1., repeat=1., influence=0., blend_in=0., blend_out=0., select=True, mute=False,
               use_auto_blend=True, use_reverse=False, use_sync_length=False, fcurves=[], modifiers=[], strips=[])
    assert module.new_transition(strip, "Transition", 11., 21.)
    strip.use_reverse = True
    assert not module.new_transition(strip, "Transition", 11., 21.)
    strip.use_reverse = False
    strip.fcurves = [NS(data_path="influence", array_index=0, driver=object(), keyframe_points=[])]
    with pytest.raises(module.BridgeError):
        module.new_transition(strip, "Transition", 11., 21.)


def test_native_transition_default_name_is_bounded_and_explicitly_unique(lifecycle):
    module, env = lifecycle
    env.track.strips.new("Transition", 40, env.source)
    env.track.strips.new("Transition.001", 60, env.source)
    proof = NS(bpy=env.bpy, obj=env.obj)
    assert module._transition_constructor_name(proof) == "Transition.002"


def test_constructor_failure_reports_observed_retained_child_name(lifecycle, monkeypatch):
    module, env = lifecycle
    original = env.track.strips.new
    def foreign(*args):
        result = original(*args)
        result.name = "Renamed During Constructor"
        return result
    monkeypatch.setattr(env.track.strips, "new", foreign)
    with pytest.raises(module.BridgeError) as caught:
        module.clip_add(env.context, clip_params())
    assert caught.value.context["requested_strip_name"] == "Walk"
    assert caught.value.context["retained_strip_name"] == "Renamed During Constructor"
    assert caught.value.context["retained_strip_native_id"] == id(env.track.strips[0])


@pytest.mark.parametrize("changed", ["mode", "project", "view_layer"])
@pytest.mark.parametrize("domain", ["lifecycle", "legacy"])
def test_last_permission_provider_session_switch_prevents_native_write(request, monkeypatch, domain, changed):
    module, env = request.getfixturevalue(domain)
    original_require = env.context.require
    count = 0
    def provider(*permissions):
        nonlocal count
        original_require(*permissions)
        count += 1
        if count == 2:  # After Guard's session check, inside last authority read.
            if changed == "mode":
                env.bpy.context.mode = "POSE"
            elif changed == "project":
                env.bpy.data.filepath = "/another-session.blend"
            else:
                env.bpy.context.view_layer = NS(objects=env.bpy.context.view_layer.objects)
    env.context.require = provider
    with pytest.raises(module.BridgeError) as caught:
        if domain == "lifecycle":
            module.clip_add(env.context, clip_params())
        else:
            module.nla_solo_track(env.context, {"track_name": "Motion", "enabled": True})
    assert not env.track.strips and not env.track.is_solo
    assert not caught.value.context.get("possible_mutation", False)
