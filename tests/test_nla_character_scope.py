from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest
from nla_test_support import ID, make_env

from mcp_server.tools.artist import ArtistTools


@pytest.fixture
def character(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.animation_layers")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    env = make_env(module, monkeypatch, permissions)
    env.source = env.action()
    env.data.action = env.source
    skin = ID("Skin", type="MESH", data=ID("SkinData"), animation_data=None,
              bl_rna=NS(identifier="Object"), users_collection=[], users_scene=[env.bpy.context.scene])
    skin.select_get = lambda: False
    skin.user_of_id = lambda owner: 2 if owner is env.obj else 0
    env.bpy.data.objects.append(skin)
    original = env.bpy.data.user_map
    def consumers(*, subset):
        result = original(subset=subset)
        if env.obj in subset:
            result[env.obj] = {skin}
        return result
    env.bpy.data.user_map = consumers
    env.skin = skin
    return module, env


@pytest.mark.parametrize("operation", ["push_down", "add_strip"])
def test_first_character_track_requires_complete_explicit_skin_scope(character, operation):
    module, env = character
    handler = module.nla_push_down if operation == "push_down" else module.nla_add
    params = {"track_name": "First", "strip_name": "Walk"}
    if operation == "add_strip":
        params.update(action_name="Walk", frame_start=1)
    with pytest.raises(module.BridgeError) as caught:
        handler(env.context, params)
    assert caught.value.code == "NOT_IMPLEMENTED" and not env.tracks
    result = handler(env.context, {**params, "affected_objects": ["Skin"]})
    assert result["affected_objects"] == ["Actor", "Skin"]
    assert len(env.tracks) == 1 and env.tracks[0].strips[0].action is env.source
    assert env.data.action is (None if operation == "push_down" else env.source)


def test_first_character_pushdown_compare_and_swap_preserves_old_binding(character):
    module, env = character
    with pytest.raises(module.BridgeError) as caught:
        module.nla_push_down(env.context, {"track_name": "First", "strip_name": "Walk",
            "affected_objects": ["Skin"], "expected_action_name": "Different"})
    assert caught.value.code == "INVALID_ARGUMENT" and not env.tracks
    assert env.data.action is env.source


def test_verified_strip_constructor_failure_compensates_without_replacing_source(character, monkeypatch):
    module, env = character
    original = module._LegacyNlaGuard.add_strip

    def create_then_fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("Failure after the complete private strip constructor was verified")

    monkeypatch.setattr(module._LegacyNlaGuard, "add_strip", create_then_fail)
    with pytest.raises(module.BridgeError) as caught:
        module.nla_push_down(env.context, {
            "track_name": "First", "strip_name": "Walk", "affected_objects": ["Skin"],
            "expected_action_name": env.source.name,
        })
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["possible_mutation"] is False
    assert not env.tracks and env.data.action is env.source
    assert env.source.users == 1


def test_unverified_constructor_allocation_is_retained_for_reinspection(character, monkeypatch):
    module, env = character
    original = module._LegacyNlaGuard.add_strip

    def create_then_forget_verification(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.created_strip_ids.clear()
        raise RuntimeError("No retained proof that this strip is bridge-owned")

    monkeypatch.setattr(module._LegacyNlaGuard, "add_strip", create_then_forget_verification)
    with pytest.raises(module.BridgeError) as caught:
        module.nla_push_down(env.context, {
            "track_name": "First", "strip_name": "Walk", "affected_objects": ["Skin"],
        })
    assert caught.value.context["rollback_verified"] is False
    assert caught.value.context["possible_mutation"] is True
    assert len(env.tracks) == 1 and len(env.tracks[0].strips) == 1
    assert env.tracks[0].strips[0].action is env.source and env.data.action is env.source


def test_character_closure_change_after_preflight_prevents_first_track(character):
    module, env = character
    original_require = env.context.require
    called = False
    def provider(*permissions):
        nonlocal called
        original_require(*permissions)
        if not called:
            called = True
            env.skin.user_of_id = lambda owner: 3 if owner is env.obj else 0
    env.context.require = provider
    with pytest.raises(module.BridgeError) as caught:
        module.nla_push_down(env.context, {"track_name": "First", "strip_name": "Walk", "affected_objects": ["Skin"]})
    assert caught.value.code == "INVALID_ARGUMENT" and not env.tracks
    assert env.skin.user_of_id(env.obj) == 3


@pytest.mark.parametrize("operation", ["legacy_push_down", "clip_add"])
def test_final_permission_provider_cancellation_prevents_the_next_native_allocation(character, addon_package, monkeypatch, operation):
    legacy, env = character
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    if operation == "legacy_push_down":
        module, helper, method, handler = legacy, "_nla_authority", "nla.push_down", legacy.nla_push_down
        params = {"track_name": "First", "strip_name": "Walk", "affected_objects": ["Skin"]}
    else:
        module = importlib.import_module(f"{addon_package}.tools.nla_lifecycle")
        monkeypatch.setattr(module, "require_blender", lambda: env.bpy)
        env.bpy.app, env.bpy.context.window = NS(background=True), None
        track = env.tracks.new()
        track.name = "Motion"
        helper, method, handler = "_quiet_authority", "nla.clip_add", module.clip_add
        params = {"object_name": "Actor", "track_name": "Motion", "strip_name": "Walk", "action_name": "Walk",
                  "frame_start": 1, "affected_objects": ["Skin"]}
    queued = queue_module.QueuedRequest(protocol.Request(id="late-cancel", method=method, params=params))
    assert queued.try_start()
    env.context.check_cancelled = queued.check_active
    original_authority, original_require = getattr(module, helper), env.context.require
    inside_final_provider = False

    def final_authority(*args):
        nonlocal inside_final_provider
        inside_final_provider = True
        try:
            return original_authority(*args)
        finally:
            inside_final_provider = False

    def provider(*required):
        original_require(*required)
        if inside_final_provider:
            queued.cancel_pending(module.BridgeError("TIMEOUT", "Caller canceled inside permission provider"))

    monkeypatch.setattr(module, helper, final_authority)
    env.context.require = provider
    with pytest.raises(module.BridgeError) as caught:
        handler(env.context, params)
    assert caught.value.code == "TIMEOUT" and caught.value.context["possible_mutation"] is False
    assert all(not track.strips for track in env.tracks) and env.data.action is env.source
    if operation == "legacy_push_down":
        assert not env.tracks


@pytest.mark.parametrize("scope", [["Skin", "Skin"], ["Actor", "Skin"], ["Missing"], "Skin", ["Skin", "Missing"]])
def test_bad_character_scope_has_no_first_track_side_effect(character, scope):
    module, env = character
    with pytest.raises(module.BridgeError):
        module.nla_push_down(env.context, {"track_name": "First", "strip_name": "Walk", "affected_objects": scope})
    assert not env.tracks and env.data.action is env.source


def test_mcp_legacy_nla_additive_scope_preserves_old_omitted_payloads():
    calls = []
    async def call(name, params):
        calls.append((name, params))
    tools = ArtistTools(NS(call=call))
    asyncio.run(tools.nla_push_down("Rig", "Motion", "Left"))
    assert calls[-1] == ("nla.push_down", {"object_name": "Rig", "track_name": "Motion", "strip_name": "Left"})
    asyncio.run(tools.nla_push_down("Rig", "Motion", "Left", ["Skin"], "Walk"))
    assert calls[-1][1]["affected_objects"] == ["Skin"] and calls[-1][1]["expected_action_name"] == "Walk"
    asyncio.run(tools.nla_add_strip("Rig", "Motion", "Left", "Walk", affected_objects=["Skin"]))
    asyncio.run(tools.nla_edit_track("Rig", "Motion", settings={"mute": True}, affected_objects=["Skin"]))
    asyncio.run(tools.nla_edit_strip("Rig", "Motion", "Left", settings={"mute": True}, affected_objects=["Skin"]))
    asyncio.run(tools.nla_solo_track("Rig", "Motion", True, affected_objects=["Skin"]))
    assert all(params["affected_objects"] == ["Skin"] for _, params in calls[1:])
