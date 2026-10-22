"""Initial checkpoint writes obey ownership loss without discarding old recovery."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_snapshots import NativeStack, Scene


@pytest.fixture
def authority(addon_package, monkeypatch):
    checkpoint = importlib.import_module(f"{addon_package}.checkpoints")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    permissions = importlib.import_module(f"{addon_package}.permissions")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    stack, registry = NativeStack(), registry_mod.ToolRegistry()
    monkeypatch.setattr(checkpoint, "require_blender", lambda: stack.bpy)
    manager = checkpoint.CheckpointManager()
    old_checkpoint = manager.create("Retained earlier recovery")
    registry.register("fixture.edit", lambda *_: None, modifies=True)
    context = registry_mod.ToolContext(state, permissions.PermissionManager(lambda: {}), registry, manager)
    lifetime = lifecycle.RequestLifetime(lifecycle.ConnectionLifetime())
    queued = queue.QueuedRequest(protocol.Request("checkpoint-owner", "fixture.edit"), deadline=float("inf"))
    assert queued.try_start()
    context.request_lifecycle, context.check_final_request = lifetime, queued.check_active
    original = checkpoint.BridgeError("TIMEOUT", "Exact primary guard failure")

    def guard():
        try:
            registry_mod.check_final_mutation(context, "fixture.edit")
        except checkpoint.BridgeError:
            raise original from None

    def stop(kind):
        if kind == "cancel":
            queued.cancel_pending(checkpoint.BridgeError("TIMEOUT", "Caller canceled"))
        else:
            lifetime.deadline = 0.

    return NS(module=checkpoint, manager=manager, stack=stack, context=context, guard=guard,
              stop=stop, original=original, old_checkpoint=old_checkpoint)


@pytest.mark.parametrize("route", ["before", "create"])
@pytest.mark.parametrize("kind", ["cancel", "expiry"])
def test_marker_reader_loss_denies_before_every_owned_write(authority, route, kind):
    env = authority
    original_scene = env.stack.scene

    class Reader(Scene):
        def get(self, key, default=None):
            result = super().get(key, default)
            if key == env.module.MARKER_KEY:
                env.stop(kind)
            return result

    scene = Reader(original_scene)
    env.stack.scene = env.stack.bpy.context.scene = scene
    env.stack.bpy.data.scenes = [scene]
    before = dict(scene), len(env.stack.frames), env.manager.list(), env.manager._window.position
    with pytest.raises(env.module.BridgeError) as caught:
        if route == "before":
            env.manager.before_modification("fixture.edit", before_write=env.guard)
        else:
            env.manager.create("Rejected new checkpoint", before_write=env.guard)
    assert caught.value is env.original and caught.value.code == "TIMEOUT"
    assert caught.value.context["checkpoint_bookkeeping"] == {
        "marker_writes_completed": 0, "native_snapshots_completed": 0,
        "next_write_rejected": "delete_marker", "compensation_performed": False,
    }
    assert (dict(scene), len(env.stack.frames), env.manager.list(), env.manager._window.position) == before


@pytest.mark.parametrize("kind", ["cancel", "expiry"])
def test_loss_after_first_marker_delete_reports_partial_state_without_next_write(authority, kind):
    env = authority
    original_scene = env.stack.scene

    class Deletion(Scene):
        def __delitem__(self, key):
            super().__delitem__(key)
            env.stop(kind)

    scene = Deletion(original_scene)
    other = Scene({env.module.MARKER_KEY: env.manager._prefix + "a" * 32})
    env.stack.scene = env.stack.bpy.context.scene = scene
    env.stack.bpy.data.scenes = [scene, other]
    before_frames, previous = len(env.stack.frames), env.manager.list()
    with pytest.raises(env.module.BridgeError) as caught:
        env.manager.before_modification("fixture.edit", before_write=env.guard)
    assert caught.value is env.original
    evidence = caught.value.context["checkpoint_bookkeeping"]
    assert evidence["marker_writes_completed"] == 1 and evidence["native_snapshots_completed"] == 0
    assert evidence["next_write_rejected"] == "delete_marker" and not evidence["compensation_performed"]
    assert caught.value.context["possible_mutation"] and caught.value.context["verification_required"]
    assert env.module.MARKER_KEY not in scene and env.module.MARKER_KEY in other
    assert len(env.stack.frames) == before_frames and env.manager.list() == previous


def test_last_preference_reader_loss_denies_native_push_but_reports_markers(authority, monkeypatch):
    env = authority
    step_limit = env.manager._step_limit

    def read(blender):
        value = step_limit(blender)
        env.stop("cancel")
        return value

    monkeypatch.setattr(env.manager, "_step_limit", read)
    frames, position = len(env.stack.frames), env.manager._window.position
    with pytest.raises(env.module.BridgeError) as caught:
        env.manager.before_modification("fixture.edit", before_write=env.guard)
    assert caught.value is env.original
    evidence = caught.value.context["checkpoint_bookkeeping"]
    assert evidence["marker_writes_completed"] == 2 and evidence["native_snapshots_completed"] == 0
    assert evidence["next_write_rejected"] == "native_undo_push"
    assert len(env.stack.frames) == frames and env.manager._window.position == position


def test_successful_push_is_retained_if_following_stamp_rejects(authority, monkeypatch):
    env = authority
    push = env.stack.bpy.ops.ed.undo_push

    def snapshot(**kwargs):
        value = push(**kwargs)
        env.stop("cancel")
        return value

    monkeypatch.setattr(env.stack.bpy.ops.ed, "undo_push", snapshot)
    frames, position = len(env.stack.frames), env.manager._window.position
    with pytest.raises(env.module.BridgeError) as caught:
        env.manager.before_modification("fixture.edit", before_write=env.guard)
    assert caught.value is env.original
    evidence = caught.value.context["checkpoint_bookkeeping"]
    assert evidence["native_snapshots_completed"] == 1 and evidence["marker_writes_completed"] == 2
    assert len(env.stack.frames) == frames + 1 and env.manager._window.position == position + 1
    assert env.manager._pending is not None and env.manager.list() == [env.old_checkpoint]


def test_editor_session_is_retained_when_new_request_guard_rejects(authority):
    env = authority
    env.stack.scene.session_uid = 11
    env.stack.bpy.context.active_object = NS(name="Mesh", session_uid=22)
    session = env.module.MeshEditSession(env.module.UndoStep("existing edit", "before", 1), "group", 11, 22, "Mesh")
    env.manager._editor_session = session
    env.stop("cancel")
    frames = len(env.stack.frames)
    with pytest.raises(env.module.BridgeError) as caught:
        env.manager.before_modification("fixture.edit", before_write=env.guard)
    assert caught.value is env.original and env.manager._editor_session is session
    assert len(env.stack.frames) == frames and env.manager.list() == [env.old_checkpoint]
    # Finalizing an actual earlier writer remains available after caller loss.
    assert env.manager.finish_editor_session()["state"] == "finalized"


def test_explicit_create_handler_supplies_canonical_guard(authority, addon_package):
    env = authority
    core = importlib.import_module(f"{addon_package}.tools.core")
    core.register_tools(env.context.registry)
    original_scene = env.stack.scene

    class Reader(Scene):
        def get(self, key, default=None):
            value = super().get(key, default)
            env.stop("cancel")
            return value

    scene = Reader(original_scene)
    env.stack.scene = env.stack.bpy.context.scene = scene
    env.stack.bpy.data.scenes = [scene]
    frames, before = len(env.stack.frames), dict(scene)
    with pytest.raises(env.module.BridgeError) as caught:
        env.context.registry.dispatch("checkpoint.create", {"description": "Explicit denied checkpoint"}, env.context)
    assert caught.value.code == "TIMEOUT" and caught.value.context["checkpoint_authority_rejected"]
    assert len(env.stack.frames) == frames and dict(scene) == before
