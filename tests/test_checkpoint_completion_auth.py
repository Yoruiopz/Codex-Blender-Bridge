"""Native checkpoint completion requires an exact retained manager push."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from copy import copy, deepcopy
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_authority import NativeStack


@pytest.fixture
def completion_env(addon_package, monkeypatch):
    checkpoints = importlib.import_module(f"{addon_package}.checkpoints")
    completion = importlib.import_module(f"{addon_package}.checkpoint_completion")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    stack, registry = NativeStack(), registry_module.ToolRegistry()
    monkeypatch.setattr(checkpoints, "require_blender", lambda: stack.bpy)
    manager = checkpoints.CheckpointManager()
    context = registry_module.ToolContext(state, permissions.PermissionManager(lambda: {}), registry, manager)
    completed, final_checks = [], []
    hooks = NS(before=None, after=None)
    method = "fixture.completed_edit"

    class Guard:
        def __call__(self):
            if hooks.before is not None:
                hooks.before()
            self.check_after_read()

        def check_after_read(self):
            registry_module.check_final_mutation(context, method)

        def after_native_push(self):
            completion.claim_native_push_completion(context, method, self)
            completed.append((len(stack.frames), manager._window.position))
            if hooks.after is not None:
                hooks.after()

    guard = Guard()
    spec = registry.register(method, lambda *_: None, modifies=True,
                             checkpoint_admission_factory=lambda *_: guard)
    return NS(checkpoints=checkpoints, completion=completion, registry_module=registry_module, permissions=permissions,
              manager=manager, stack=stack, registry=registry, context=context, spec=spec, params={},
              guard=guard, hooks=hooks, completed=completed, final_checks=final_checks,
              error=checkpoints.BridgeError)


@contextmanager
def authorized(env, *, manager=None, permit_copy=None, final_check=None):
    manager = env.manager if manager is None else manager
    final_check = (lambda: env.final_checks.append(len(env.completed))) if final_check is None else final_check
    with (env.registry.mutation_entry(env.spec, env.params, env.context) as permit,
          env.registry.checkpoint_admission(env.spec, env.params, env.context) as binding,
          env.registry.native_push_completion(permit if permit_copy is None else permit_copy(permit), binding,
                                               manager, final_check=final_check) as consumer):
        yield binding, consumer


def before(env, binding, consumer, *, manager=None):
    manager = env.manager if manager is None else manager
    return manager.before_modification(env.spec.name, before_write=binding,
                                       after_read=binding.check_after_read, after_native_push=consumer)


def test_real_finished_push_runs_completion_after_native_position_is_retained(completion_env):
    env = completion_env
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer)
        assert env.completed == [(2, 1)] and env.final_checks == [1]
        env.stack.scene["value"] = 7
        assert env.manager.after_modification(env.spec.name, before_write=binding,
            after_read=binding.check_after_read, after_native_push=consumer)
        assert env.completed == [(2, 1), (3, 2)] and env.final_checks == [1, 2]
        assert env.manager._native_push_pending == {}
    assert env.context.checkpoint_admission is None and not binding.active


def test_one_manager_call_delivers_each_actual_push_when_finishing_old_editor_session(completion_env):
    env = completion_env
    assert env.manager.before_modification("Earlier editor operation")
    env.stack.scene.session_uid = 11
    env.stack.bpy.context.active_object = NS(name="Mesh", session_uid=22)
    env.manager._editor_session = env.checkpoints.MeshEditSession(
        env.manager._pending, "prior-editor", 11, 22, "Mesh")
    env.manager._pending = None
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer)
        assert env.completed == [(3, 2), (4, 3)] and env.final_checks == [1, 2]
        assert env.manager._editor_session is None
        assert env.manager._pending.label == env.spec.name
        assert env.manager._native_push_pending == {}


@pytest.mark.parametrize("event", ("absent", "object", "constructed", "copied"))
def test_binding_and_domain_hook_cannot_claim_a_completion_without_a_push(completion_env, event):
    env = completion_env
    supplied = {"absent": None, "object": object(), "constructed": env.completion.NativePushEvent(),
                "copied": copy(env.completion.NativePushEvent())}[event]
    with authorized(env) as (binding, _consumer):
        for callback in (lambda: binding.after_native_push(supplied), env.guard.after_native_push):
            with pytest.raises(env.error) as caught:
                callback()
            assert caught.value.context["native_push_completion_valid"] is False
        assert env.completed == [] and len(env.stack.frames) == 1
        assert env.checkpoints.MARKER_KEY not in env.stack.scene


@pytest.mark.parametrize("duplicate", (copy, deepcopy))
def test_copied_event_cannot_substitute_or_replay_real_completion(completion_env, monkeypatch, duplicate):
    env, received = completion_env, []
    original = env.registry_module.CheckpointAdmissionBinding.after_native_push

    def inspect(binding, event=None):
        received.append(event)
        assert not hasattr(event, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            event.relabel = "forged"
        with pytest.raises(env.error) as forged:
            original(binding, duplicate(event))
        assert forged.value.context["native_push_completion_valid"] is False
        original(binding, event)
        with pytest.raises(env.error) as replay:
            original(binding, event)
        assert replay.value.context["native_push_completion_valid"] is False

    monkeypatch.setattr(env.registry_module.CheckpointAdmissionBinding, "after_native_push", inspect)
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer)
        with pytest.raises(env.error) as replay:
            original(binding, received[0])
        assert replay.value.context["native_push_completion_valid"] is False
        assert env.completed == [(2, 1)] and env.final_checks == [1]


@pytest.mark.parametrize("duplicate", (copy, deepcopy))
def test_copied_consumer_cannot_arm_manager_or_authorize_direct_call(completion_env, duplicate):
    env = completion_env
    with authorized(env) as (binding, consumer):
        assert not hasattr(consumer, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            consumer.manager = env.manager
        for candidate in (consumer, duplicate(consumer)):
            with pytest.raises(env.error) as caught:
                candidate()
            assert caught.value.context["native_push_completion_valid"] is False
        with pytest.raises(env.error) as copied:
            before(env, binding, duplicate(consumer))
        assert copied.value.context["native_push_completion_valid"] is False
        assert before(env, binding, consumer)
        assert env.completed == [(2, 1)]


def test_copied_invocation_permit_cannot_create_consumer(completion_env):
    env = completion_env
    with pytest.raises(env.error) as caught, authorized(env, permit_copy=copy):
        pytest.fail("A copied permit must not create a native completion consumer")
    assert caught.value.context["native_push_completion_valid"] is False
    assert env.completed == [] and len(env.stack.frames) == 1


def test_wrong_manager_is_refused_before_any_blender_reader(completion_env, monkeypatch):
    env = completion_env
    other = env.checkpoints.CheckpointManager()

    def forbidden(**_kwargs):
        pytest.fail("Wrong manager must be refused before reading Blender")

    monkeypatch.setattr(other, "_ensure_undo_enabled", forbidden)
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer, manager=other)
        assert caught.value.context["native_push_completion_valid"] is False
        assert before(env, binding, consumer)
    assert env.completed == [(2, 1)] and other._window.position == 0


def test_consumer_scope_exit_retires_authority_even_while_binding_is_active(completion_env):
    env = completion_env
    with (env.registry.mutation_entry(env.spec, env.params, env.context) as permit,
          env.registry.checkpoint_admission(env.spec, env.params, env.context) as binding):
        with env.registry.native_push_completion(permit, binding, env.manager, final_check=lambda: None) as consumer:
            pass
        assert binding.active
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        assert caught.value.context["native_push_completion_valid"] is False
    assert env.completed == [] and len(env.stack.frames) == 1
    assert env.checkpoints.MARKER_KEY not in env.stack.scene


def test_reentrant_manager_call_cannot_borrow_armed_consumer(completion_env):
    env = completion_env
    with authorized(env) as (binding, consumer):
        env.hooks.before = lambda: before(env, binding, consumer)
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        assert caught.value.context["native_push_completion_valid"] is False
        assert caught.value.context["checkpoint_bookkeeping"] == {
            "marker_writes_completed": 0, "native_snapshots_completed": 0,
            "next_write_rejected": "set_marker", "compensation_performed": False,
        }
    assert env.completed == [] and len(env.stack.frames) == 1
    assert env.checkpoints.MARKER_KEY not in env.stack.scene


@pytest.mark.parametrize("source", ("domain", "final_check"))
def test_completion_denial_preserves_primary_error_and_measured_native_state(completion_env, source):
    env = completion_env
    old = env.manager.create("Retain earlier recovery")
    frames, position = len(env.stack.frames), env.manager._window.position
    primary = env.error("TIMEOUT", "Exact completion refusal")

    def reject():
        raise primary

    if source == "domain":
        env.hooks.after = reject
    with authorized(env, final_check=reject if source == "final_check" else None) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        assert caught.value is primary
        assert primary.context["checkpoint_bookkeeping"] == {
            "marker_writes_completed": 2, "native_snapshots_completed": 1,
            "next_write_rejected": "after_native_undo_push", "compensation_performed": False,
        }
        assert primary.context["possible_mutation"] and primary.context["verification_required"]
        assert len(env.stack.frames) == frames + 1 and env.manager._window.position == position + 1
        assert env.manager.list() == [old] and env.manager._native_push_pending == {}
        with pytest.raises(env.error) as retry:
            before(env, binding, consumer)
        assert retry.value is primary
        assert len(env.stack.frames) == frames + 1 and len(env.completed) == 1


@pytest.mark.parametrize("outcome", ("cancelled", "raised", "undo_zero", "marker_only"))
def test_no_completion_without_finished_native_push(completion_env, monkeypatch, outcome):
    env = completion_env
    if outcome in {"cancelled", "raised"}:
        def unsuccessful(**_kwargs):
            if outcome == "raised":
                raise RuntimeError("Native undo push failed")
            return {"CANCELLED"}
        monkeypatch.setattr(env.stack.bpy.ops.ed, "undo_push", unsuccessful)
    elif outcome == "undo_zero":
        env.stack.bpy.context.preferences.edit.undo_steps = 0
    else:
        env.stack.bpy.context.mode = "EDIT_MESH"
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer) is False
    assert env.completed == env.final_checks == []
    assert len(env.stack.frames) == 1 and env.manager._window.position == 0
    assert env.manager._native_push_pending == {}
    assert (env.checkpoints.MARKER_KEY in env.stack.scene) is (outcome != "undo_zero")


def test_legacy_observer_remains_callable_after_real_push(completion_env):
    env, observed = completion_env, []
    assert env.manager.before_modification(env.spec.name, before_write=lambda: None,
        after_read=lambda: None, after_native_push=lambda: observed.append(len(env.stack.frames)))
    assert observed == [2] and env.completed == []
    assert env.manager._native_push_pending == {}


def test_late_provider_disabling_undo_emits_no_completion(completion_env):
    env = completion_env

    def provider():
        env.stack.bpy.context.preferences.edit.undo_steps = 0
        return {"EDIT_SCENE": True}

    env.context.permissions = env.permissions.PermissionManager(provider)
    env.hooks.before = lambda: env.context.require(env.permissions.Permission.EDIT_SCENE)
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        assert caught.value.code == "BLENDER_CONTEXT_ERROR"
        assert caught.value.context["checkpoint_bookkeeping"]["native_snapshots_completed"] == 0
    assert env.completed == env.final_checks == []
    assert len(env.stack.frames) == 1 and env.manager._window.position == 0
    assert env.manager._native_push_pending == {}


@pytest.mark.parametrize("failure", ("bind", "cleanup"))
def test_binder_failure_restores_context_and_preserves_exact_primary(completion_env, failure):
    env, captured = completion_env, []
    previous = (None, object(), "enclosing", {"old": True}, object())
    (env.context.checkpoint_admission, env.context.checkpoint_call_id, env.context.checkpoint_method,
     env.context.checkpoint_params, env.context.checkpoint_finalization_owner) = previous
    primary = env.error("TIMEOUT", "Exact admission lifecycle failure")

    def bind(binding):
        captured.append(binding)
        if failure == "bind":
            raise primary

        def cleanup():
            raise RuntimeError("Secondary cleanup failure must not replace the primary")

        return cleanup

    env.guard.bind_checkpoint = bind
    with (pytest.raises(env.error) as caught,
          env.registry.checkpoint_admission(env.spec, env.params, env.context)):
        raise primary
    assert caught.value is primary and len(captured) == 1 and not captured[0].active
    restored = (env.context.checkpoint_admission, env.context.checkpoint_call_id, env.context.checkpoint_method,
                env.context.checkpoint_params, env.context.checkpoint_finalization_owner)
    assert all(actual is expected for actual, expected in zip(restored, previous, strict=True))
    assert env.completed == [] and len(env.stack.frames) == 1
