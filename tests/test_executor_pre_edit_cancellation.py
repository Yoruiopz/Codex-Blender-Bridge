from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.mark.parametrize("entry", ["executor", "batch"])
@pytest.mark.parametrize("where", ["provider", "scope"])
@pytest.mark.parametrize("stop", ["queued", "queued_deadline", "disconnect", "lifetime_deadline", "toolset", "pause", "emergency"])
def test_authority_lost_in_preflight_never_enters_checkpoint(addon_package, entry, where, stop):
    """Exercise real lifetime flags, including loss after the last scope read."""
    executor_mod = importlib.import_module(f"{addon_package}.executor")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    state_mod = importlib.import_module(f"{addon_package}.state")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    queue_mod = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    plans = importlib.import_module(f"{addon_package}.task_plans")
    batch = importlib.import_module(f"{addon_package}.tools.batch")
    errors = importlib.import_module(f"{addon_package}.errors")
    calls = []
    state = state_mod.BridgeState()
    registry = registry_mod.ToolRegistry(enabled_toolsets=("objects",))
    lifetime = lifecycle.RequestLifetime(lifecycle.ConnectionLifetime())
    request = protocol.Request(id="stopped-preflight", method="object.fixture", params={}, _lifecycle=lifetime)
    queued = queue_mod.QueuedRequest(request, deadline=float("inf"))
    assert queued.try_start()
    fired = False

    def lose_authority():
        nonlocal fired
        if fired:
            return
        fired = True
        if stop == "queued":
            queued.cancel_pending(errors.BridgeError("TIMEOUT", "Caller canceled"))
        elif stop == "queued_deadline":
            queued.deadline = 0.
        elif stop == "disconnect":
            lifetime.connection.disconnected.set()
        elif stop == "lifetime_deadline":
            lifetime.deadline = 0.
        elif stop == "toolset":
            registry.disable_toolset("objects")
        elif stop == "pause":
            state.set_paused(True)
        else:
            state.set_emergency_stopped(True)

    reads = {"provider": 0, "scope": 0}

    def last_preflight_read(kind):
        reads[kind] += 1
        # Batch preflights the whole list once before its live child preflight.
        if where == kind and reads[kind] == (2 if entry == "batch" else 1):
            lose_authority()

    def provider():
        last_preflight_read("provider")
        return {"TRANSFORM_OBJECTS": True}

    def resolve(_context, _params):
        last_preflight_read("scope")
        return {"scope_complete": True}

    registry.register("object.fixture", lambda *_: calls.append("handler"), toolset="objects", modifies=True,
                      permissions=(permissions.Permission.TRANSFORM_OBJECTS,), protected_scope_resolver=resolve)
    if where == "scope":
        plans.get_task_plans(state).protection = {"test_policy": True}
    checkpoints = NS(before_modification=lambda _, **_kwargs: calls.append("checkpoint") or True,
                     after_modification=lambda _: calls.append("finalize") or True)
    executor = executor_mod.MainThreadExecutor(command_queue=queue_mod.CommandQueue(), registry=registry,
                                              state=state, permissions=permissions.PermissionManager(provider),
                                              checkpoints=checkpoints)
    if entry == "executor":
        response = executor.execute_request(request, check_cancelled=queued.check_active)
        assert not response.ok
        code = response.error["code"]
    else:
        context = executor.context
        context.check_cancelled = queued.check_active
        context.check_final_request = queued.check_active
        context.request_lifecycle = lifetime
        with pytest.raises(errors.BridgeError) as caught:
            batch.batch_execute(context, {"steps": [{"method": "object.fixture"}]})
        code = caught.value.code
        assert not caught.value.context["failed_step_started"]
        assert not caught.value.context["execution_started"]
    expected = {"toolset": "TOOLSET_DISABLED", "pause": "AGENT_PAUSED", "emergency": "EMERGENCY_STOPPED"}.get(stop, "TIMEOUT")
    assert fired and code == expected
    assert calls == []


def test_cancellation_during_checkpoint_setup_prevents_handler_start(addon_package):
    executor_mod = importlib.import_module(f"{addon_package}.executor")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    state_mod = importlib.import_module(f"{addon_package}.state")
    permission_mod = importlib.import_module(f"{addon_package}.permissions")
    queue_mod = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    cancelled = False
    calls = []
    finalization = []

    def before(_tool, **_kwargs):
        nonlocal cancelled
        cancelled = True
        return True

    def check():
        if cancelled:
            raise errors.BridgeError(errors.ErrorCode.TIMEOUT, "Canceled during snapshot setup")

    registry = registry_mod.ToolRegistry()
    registry.register("fixture.edit", lambda *_: calls.append("edited"), modifies=True)
    executor = executor_mod.MainThreadExecutor(
        command_queue=queue_mod.CommandQueue(),
        registry=registry,
        state=state_mod.BridgeState(),
        permissions=permission_mod.PermissionManager(lambda: {}),
        checkpoints=NS(before_modification=before,
                       after_modification=lambda _: finalization.append("after") or True,
                       finish_editor_session=lambda: finalization.append("finish"),
                       editor_session_status=lambda: {"state": "deferred", "group_id": "existing-group"}),
    )
    response = executor.execute_request(
        protocol.Request(id="cancel-after-checkpoint", method="fixture.edit", params={}),
        check_cancelled=check,
    )
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert calls == []
    assert finalization == []
    assert response.error["context"]["undo_group"]["state"] == "deferred"
    assert response.error["context"]["requested_edit_started"] is False
