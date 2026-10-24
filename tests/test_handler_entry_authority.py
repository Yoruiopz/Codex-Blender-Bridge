"""Prepared modifying calls cannot enter after their last canonical safe point."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def env(addon_package):
    def module(name):
        return importlib.import_module(f"{addon_package}.{name}")
    registry_mod, queue, protocol = module("tool_registry"), module("command_queue"), module("protocol")
    permissions, plans = module("permissions"), module("task_plans")
    registry = registry_mod.ToolRegistry(enabled_toolsets=("objects",))
    module("tools.batch").register_tools(registry)
    registry.enable_toolset("batch")
    state, lifetime_mod = module("state").BridgeState(), module("request_lifecycle")
    lifetime = lifetime_mod.RequestLifetime(lifetime_mod.ConnectionLifetime())
    request = protocol.Request("last-preflight", "object.fixture", {}, _lifecycle=lifetime)
    queued = queue.QueuedRequest(request, deadline=float("inf"))
    assert queued.try_start()
    calls, markers = [], []
    provider_action = [lambda: None]

    def provider():
        provider_action[0]()
        return {"TRANSFORM_OBJECTS": True}

    def checkpoint(_label, *, before_write, after_read=None, after_native_push=None):
        before_write()
        if after_read is not None:
            after_read()
        markers.append("before")
        if after_native_push is not None:
            after_native_push()
        return True

    checkpoints = NS(before_modification=checkpoint,
                     after_modification=lambda _: markers.append("after") or True,
                     finish_editor_session=lambda: markers.append("old-editor-finalize"),
                     editor_session_status=lambda: {"state": "deferred"})
    executor = module("executor").MainThreadExecutor(command_queue=queue.CommandQueue(), registry=registry,
        state=state, permissions=permissions.PermissionManager(provider), checkpoints=checkpoints)
    context = executor.context
    context.request_lifecycle, context.check_final_request = lifetime, queued.check_active
    return NS(module=module, registry=registry, state=state, plans=plans, queued=queued, lifetime=lifetime,
              request=request, calls=calls, markers=markers, executor=executor, context=context,
              provider_action=provider_action, permissions=permissions, errors=module("errors"))


def cancel(env):
    env.queued.cancel_pending(env.errors.BridgeError("TIMEOUT", "Owner canceled during final preflight"))


def test_direct_registry_dispatch_provider_loss_denies_actual_entry_and_balances_counters(env):
    env.registry.register("object.fixture", lambda *_: env.calls.append("edit"), toolset="objects", modifies=True,
                          permissions=(env.permissions.Permission.TRANSFORM_OBJECTS,))
    env.provider_action[0] = lambda: cancel(env)
    with pytest.raises(env.errors.BridgeError) as caught:
        env.registry.dispatch("object.fixture", {}, env.context)
    assert caught.value.code == "TIMEOUT"
    assert env.calls == env.markers == [] and env.context.handler_entries == 0
    assert env.registry.executing_mutators == env.plans.get_task_plans(env.state).executing_mutators == 0


@pytest.mark.parametrize("where", ["provider", "scope"])
def test_second_batch_step_final_preflight_loss_keeps_only_previous_writer_recovery(env, where):
    batch = env.module("tools.batch")
    first_entered = []

    def first(_context, _params):
        env.calls.append("first")
        first_entered.append(True)
        return {"object": "First"}

    def resolve(_context, _params):
        if where == "scope" and first_entered:
            cancel(env)
        return {"scope_complete": True}

    env.registry.register("object.first", first, toolset="objects", modifies=True, protected_scope_resolver=resolve,
                          permissions=(env.permissions.Permission.TRANSFORM_OBJECTS,))
    env.registry.register("object.second", lambda *_: env.calls.append("late second"), toolset="objects", modifies=True,
                          protected_scope_resolver=resolve, permissions=(env.permissions.Permission.TRANSFORM_OBJECTS,))
    if where == "scope":
        env.plans.get_task_plans(env.state).protection = {"fixture": True}
    else:
        env.provider_action[0] = lambda: cancel(env) if first_entered else None
    with pytest.raises(env.errors.BridgeError) as caught:
        batch.batch_execute(env.context, {"steps": [{"method": "object.first"}, {"method": "object.second"}]})
    assert caught.value.code == "TIMEOUT" and caught.value.context["completed_steps"] == 1
    assert not caught.value.context["failed_step_started"] and caught.value.context["execution_started"]
    assert env.calls == ["first"] and env.markers == ["before", "after"]
    assert env.context.handler_entries == 1
    assert env.registry.executing_mutators == env.plans.get_task_plans(env.state).executing_mutators == 0


def test_protected_executor_reprepare_loss_never_enters_handler_or_after_snapshot(env):
    reads = []

    def resolve(_context, _params):
        reads.append(True)
        if len(reads) == 2:
            cancel(env)
        return {"scope_complete": True}

    env.registry.register("object.fixture", lambda *_: env.calls.append("late edit"), toolset="objects", modifies=True,
                          protected_scope_resolver=resolve)
    env.plans.get_task_plans(env.state).protection = {"fixture": True}
    response = env.executor.execute_request(env.request, check_cancelled=env.queued.check_active)
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert env.calls == [] and env.markers == ["before"]
    assert not response.error["context"]["requested_edit_started"]
    assert not response.error["context"]["undo_boundary_finalized"]
    assert env.registry.executing_mutators == env.plans.get_task_plans(env.state).executing_mutators == 0


@pytest.mark.parametrize("stop", ["pause", "emergency"])
def test_explicit_local_recovery_keeps_its_existing_stop_override(env, stop):
    env.registry.register("checkpoint.restore_last", lambda *_: env.calls.append("recovered") or {},
                          modifies=True, remote=False, automatic_checkpoint=False)
    if stop == "pause":
        env.state.set_paused(True)
    else:
        env.state.set_emergency_stopped(True)
    env.executor.dispatch("checkpoint.restore_last", allow_recovery=True)
    assert env.calls == ["recovered"]


def test_explicit_local_recovery_override_cannot_ignore_owner_loss(env):
    env.registry.register("checkpoint.restore_last", lambda *_: env.calls.append("late recovery"),
                          modifies=True, remote=False, automatic_checkpoint=False,
                          permissions=(env.permissions.Permission.TRANSFORM_OBJECTS,))
    env.state.set_paused(True)
    env.provider_action[0] = lambda: cancel(env)
    with pytest.raises(env.errors.BridgeError) as caught:
        env.executor._invoke(env.module("protocol").Request("local-recovery", "checkpoint.restore_last"),
                             allow_recovery=True, check_cancelled=env.queued.check_active)
    assert caught.value.code == "TIMEOUT" and env.calls == []
    assert env.markers == []


@pytest.mark.parametrize("where", ["provider", "checkpoint_reader", "after_checkpoint"])
def test_batch_local_budget_stops_next_checkpoint_write_or_handler(env, monkeypatch, where):
    batch = env.module("tools.batch")
    clock, reads = [0.], []
    monkeypatch.setattr(batch.time, "monotonic", lambda: clock[0])
    env.registry.register("object.fixture", lambda *_: env.calls.append("late edit"), toolset="objects", modifies=True,
                          permissions=(env.permissions.Permission.TRANSFORM_OBJECTS,))

    def provider():
        reads.append(True)
        if where == "provider" and len(reads) == 2:
            clock[0] = 2.

    def checkpoint(_label, *, before_write, after_read=None, after_native_push=None):
        if where == "checkpoint_reader":
            clock[0] = 2.
        before_write()
        if after_read is not None:
            after_read()
        env.markers.append("before")
        if after_native_push is not None:
            after_native_push()
        if where == "after_checkpoint":
            clock[0] = 2.
        return True

    env.provider_action[0] = provider
    env.context.checkpoints.before_modification = checkpoint
    with pytest.raises(env.errors.BridgeError) as caught:
        batch.batch_execute(env.context, {"steps": [{"method": "object.fixture"}], "time_limit_seconds": 1.})
    assert caught.value.code == "TIMEOUT" and not caught.value.context["failed_step_started"]
    assert env.calls == []
    assert env.markers == (["before"] if where == "after_checkpoint" else [])
    assert env.context.handler_entries == 0


def test_rejected_batch_wrapper_does_not_finalize_old_editor_work(env):
    env.registry.register("object.fixture", lambda *_: env.calls.append("late child"), toolset="objects", modifies=True,
                          permissions=(env.permissions.Permission.TRANSFORM_OBJECTS,))
    env.provider_action[0] = lambda: cancel(env)
    request = env.module("protocol").Request("batch-wrapper", "batch.execute", {"steps": [{"method": "object.fixture"}]},
                                             _lifecycle=env.lifetime)
    response = env.executor.execute_request(request, check_cancelled=env.queued.check_active)
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert response.error["context"]["execution_started"] is False
    assert response.error["context"]["undo_group"]["state"] == "deferred"
    assert env.calls == env.markers == []
