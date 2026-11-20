"""Checkpoint integration models; these do not qualify native Scene readers."""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_snapshots import NativeStack, Scene

LABEL = "Record edited texture backup"


@pytest.fixture
def checkpoint_env(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.current_pixels_checkpoint")
    checkpoints = importlib.import_module(f"{addon_package}.checkpoints")
    registry = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state")
    trace = []

    class ObservedScene(Scene):
        def get(self, *args):
            trace.append("marker_read")
            return super().get(*args)

    stack = NativeStack()
    stack.scene = ObservedScene(value=0)
    stack.frames = [dict(stack.scene)]
    stack.bpy.context.scene = stack.scene
    stack.bpy.data.scenes = [stack.scene]
    manager = checkpoints.CheckpointManager()
    context = registry.ToolContext(
        state=state.BridgeState(),
        permissions=permissions.PermissionManager(lambda: {}),
        registry=registry.ToolRegistry(),
        checkpoints=manager,
    )
    model = {"frame": 1, "particle_object": None, "particle_settings": ("PARTICLES", False), "denial": None}

    def check():
        trace.append("check")
        if model["denial"] is not None:
            raise model["denial"]

    def read_state(bpy, scene, supplied_check):
        # Explicit synthetic native-read assumptions: the interface test does
        # not replace a source-qualified descriptor or ParticleEdit proof.
        assert bpy is stack.bpy
        trace.append("state_read")
        return id(scene), model["frame"], model["particle_object"], model["particle_settings"]

    monkeypatch.setattr(module, "require_blender", lambda: stack.bpy)
    monkeypatch.setattr(checkpoints, "require_blender", lambda: stack.bpy)
    monkeypatch.setattr(module, "_read_state", read_state)
    return NS(module=module, checkpoints=checkpoints, registry=registry, stack=stack,
              manager=manager, context=context, model=model, check=check, trace=trace)


def capture(env):
    return env.module.capture(env.context, check=env.check)


def before(env, proof):
    proof.check_before_checkpoint()
    assert env.manager.before_modification(
        LABEL, before_write=lambda: proof.with_provider(env.check),
        after_read=proof.check_after_read, after_native_push=proof.check_after_push,
    )
    proof.bind_before_pending(LABEL)


def after(env, proof):
    proof.before_finalization()
    assert env.manager.after_modification(
        LABEL, before_write=lambda: proof.with_provider(env.check),
        after_read=proof.check_after_read, after_native_push=proof.check_after_push,
    )
    proof.check_finalized()


def test_capture_and_observation_make_no_native_push_or_marker_write(checkpoint_env):
    env = checkpoint_env
    proof = capture(env)
    proof.check_after_read()
    proof.check_after_push()  # Observation grants no completed-push authority.
    assert env.stack.cursor == 0 and env.stack.scene == {"value": 0}
    assert env.manager._pending is None and not env.manager._undo_steps


@pytest.mark.parametrize("conflict", ["pending", "editor", "owned_claim", "owned_pending", "recovery"])
def test_capture_refuses_unrelated_recovery_ownership_without_clearing_it(checkpoint_env, conflict):
    env = checkpoint_env
    sentinel = object()
    if conflict == "pending":
        env.manager._pending = sentinel
    elif conflict == "editor":
        env.manager._editor_session = sentinel
    elif conflict == "owned_claim":
        env.manager._owned_claim = sentinel
    elif conflict == "owned_pending":
        env.manager._owned_pending[1] = sentinel
    else:
        env.manager.recovery_in_progress = True
    with pytest.raises(env.module.BridgeError):
        capture(env)
    assert env.stack.cursor == 0 and env.stack.scene == {"value": 0}
    assert (env.manager._pending is sentinel if conflict == "pending" else
            env.manager._editor_session is sentinel if conflict == "editor" else
            env.manager._owned_claim is sentinel if conflict == "owned_claim" else
            env.manager._owned_pending.get(1) is sentinel if conflict == "owned_pending" else
            env.manager.recovery_in_progress is True)


@pytest.mark.parametrize("foreign", ["context", "manager"])
def test_capture_requires_exact_services(checkpoint_env, foreign):
    env = checkpoint_env
    if foreign == "context":
        context = NS(checkpoints=env.manager, state=env.context.state)
    else:
        class ForeignManager(env.checkpoints.CheckpointManager):
            pass

        context = env.context
        context.checkpoints = ForeignManager()
    with pytest.raises(env.module.BridgeError):
        env.module.capture(context, check=env.check)
    assert env.stack.cursor == 0


def test_actual_manager_before_and_after_keep_one_owned_undo_step(checkpoint_env):
    env = checkpoint_env
    proof = capture(env)
    before(env, proof)
    owned = env.manager._pending
    assert type(owned) is env.checkpoints.UndoStep and owned.label == LABEL
    assert env.stack.cursor == 1 and env.checkpoints.MARKER_KEY in env.stack.scene
    proof.with_provider(env.check)
    proof.check_after_read()
    assert env.manager._pending is owned
    after(env, proof)
    assert env.stack.cursor == 2 and env.manager._pending is None
    assert len(env.manager._undo_steps) == 1
    assert env.manager._undo_steps[0].before_marker == owned.before_marker


@pytest.mark.parametrize("field,value", [("frame", 2), ("particle_object", "other-native-object"),
                                          ("particle_settings", ("HAIR", True))])
def test_scene_or_particle_drift_never_advances_a_baseline(checkpoint_env, field, value):
    env = checkpoint_env
    proof = capture(env)
    env.model[field] = value
    for observe in (proof.check_after_read, proof.check_after_push):
        with pytest.raises(env.module.BridgeError):
            observe()
    assert env.stack.cursor == 0 and env.stack.scene == {"value": 0}


def test_changed_particle_state_during_native_push_stops_before_binding(checkpoint_env):
    env = checkpoint_env
    proof = capture(env)
    original_push = env.stack.bpy.ops.ed.undo_push

    def push(**kwargs):
        result = original_push(**kwargs)
        env.model["particle_object"] = "new-weak-native-reference"
        return result

    env.stack.bpy.ops.ed.undo_push = push
    proof.check_before_checkpoint()
    with pytest.raises(env.module.BridgeError):
        env.manager.before_modification(
            LABEL, before_write=lambda: proof.with_provider(env.check),
            after_read=proof.check_after_read, after_native_push=proof.check_after_push,
        )
    assert env.stack.cursor == 1 and env.manager._pending is None
    assert not env.manager._undo_steps


@pytest.mark.parametrize("fault", ["marker", "pending"])
def test_provider_cannot_replace_marker_or_pending_even_with_the_same_label(checkpoint_env, fault):
    env = checkpoint_env
    proof = capture(env)
    before(env, proof)
    original = env.manager._pending
    replacement = env.checkpoints.UndoStep(original.label, original.before_marker, original.sequence)

    def provider():
        if fault == "marker":
            env.stack.scene[env.checkpoints.MARKER_KEY] = "manual marker"
        else:
            env.manager._pending = replacement

    with pytest.raises(env.module.BridgeError):
        proof.with_provider(provider)
    assert env.stack.cursor == 1
    if fault == "pending":
        assert env.manager._pending is replacement
    else:
        assert env.stack.scene[env.checkpoints.MARKER_KEY] == "manual marker"


def test_preexisting_marker_drift_refuses_before_calling_provider(checkpoint_env):
    env = checkpoint_env
    proof = capture(env)
    env.stack.scene[env.checkpoints.MARKER_KEY] = "manual marker"
    calls = []
    with pytest.raises(env.module.BridgeError):
        proof.with_provider(lambda: calls.append("provider"))
    assert calls == [] and env.stack.scene[env.checkpoints.MARKER_KEY] == "manual marker"


def test_binding_rejects_a_different_pending_label_without_adopting_it(checkpoint_env):
    env = checkpoint_env
    proof = capture(env)
    proof.check_before_checkpoint()
    assert env.manager.before_modification(
        LABEL, before_write=lambda: proof.with_provider(env.check),
        after_read=proof.check_after_read, after_native_push=proof.check_after_push,
    )
    pending = env.manager._pending
    with pytest.raises(env.module.BridgeError):
        proof.bind_before_pending("another operation")
    assert env.manager._pending is pending and env.stack.cursor == 1


def test_finalization_requires_the_owned_pending_to_be_cleared_by_the_manager(checkpoint_env):
    env = checkpoint_env
    proof = capture(env)
    before(env, proof)
    owned = env.manager._pending
    proof.before_finalization()
    with pytest.raises(env.module.BridgeError):
        proof.check_finalized()
    assert env.manager._pending is owned and env.stack.cursor == 1


def test_last_safe_point_preserves_canonical_bridge_error_identity(checkpoint_env):
    env = checkpoint_env
    proof = capture(env)
    env.trace.clear()
    proof.check_after_read()
    assert "state_read" in env.trace and "marker_read" in env.trace
    assert env.trace[-1] == "check"
    denial = env.module.BridgeError("TIMEOUT", "canonical owner disconnected")
    env.model["denial"] = denial
    with pytest.raises(env.module.BridgeError) as caught:
        proof.check_after_read()
    assert caught.value is denial
    assert env.stack.cursor == 0


@pytest.mark.parametrize("changed", [None, "inventory_scene", "context_scene_uid", "window_scene_uid", "window_layer"])
def test_native_scene_and_view_layer_wrappers_compare_native_identity(addon_package, monkeypatch, changed):
    """Wrapper churn is modeled; the stock descriptor prerequisites are not qualified here."""
    module = importlib.import_module(f"{addon_package}.current_pixels_checkpoint")

    class Wrapper:
        def __init__(self, pointer, uid=None, **fields):
            self.pointer, self.session_uid = pointer, uid
            vars(self).update(fields)

        def as_pointer(self):
            return self.pointer

        def __eq__(self, _other):
            raise AssertionError("RNA wrapper equality does not establish native identity")

    settings, particle = Wrapper(50), Wrapper(60)
    scene = Wrapper(10, 11, library=None, override_library=None, is_editable=True,
                    animation_data=None, user_of_id=lambda _owner: 0,
                    tool_settings=settings, original=Wrapper(10, 11))
    settings.particle_edit = particle
    particle.object = particle.brush = None
    layer = Wrapper(20, objects=NS(active=None))
    window = Wrapper(30, scene=Wrapper(10, 11), view_layer=Wrapper(20))
    bpy = NS(app=NS(build_hash=b"62c1db4208e8", version=(4, 5, 14)),
             data=NS(scenes=[Wrapper(10, 11)], objects=[]),
             context=NS(mode="OBJECT", scene=Wrapper(10, 11), view_layer=layer, window=window))
    # Deliberately distinct Python objects represent every repeated RNA lookup.
    assert bpy.data.scenes[0] is not scene and bpy.context.scene is not scene
    assert window.scene is not scene and window.view_layer is not layer
    monkeypatch.setattr(module.proof, "descriptors", lambda _bpy, _owner: ())
    monkeypatch.setattr(module.proof, "primitive", lambda _bpy, _owner: ((), ()))
    monkeypatch.setattr(module.proof, "runtime", lambda _bpy: ())
    monkeypatch.setattr(module, "_pointer", lambda _bpy, owner, name, _kind: getattr(owner, name))
    monkeypatch.setattr(module, "_settings", lambda _bpy, _owner: ())
    reasons = {"inventory_scene": "SINGLE_CURRENT_SCENE_REQUIRED",
               "context_scene_uid": "CURRENT_OBJECT_MODE_REQUIRED",
               "window_scene_uid": "CURRENT_WINDOW_LAYER_REQUIRED",
               "window_layer": "CURRENT_WINDOW_LAYER_REQUIRED"}
    if changed == "inventory_scene":
        bpy.data.scenes[0].pointer = 12
    elif changed == "context_scene_uid":
        bpy.context.scene.session_uid = 12
    elif changed == "window_scene_uid":
        window.scene.session_uid = 12
    elif changed == "window_layer":
        window.view_layer.pointer = 21
    checks = []
    if changed is not None:
        with pytest.raises(module.BridgeError) as caught:
            module._read_state(bpy, scene, lambda: checks.append("check"))
        assert caught.value.context["reason"] == reasons[changed]
    else:
        result = module._read_state(bpy, scene, lambda: checks.append("check"))
        assert result[:4] == ((10, 11), 20, 30, ((10, 11), 20))
        assert checks == ["check", "check"]
