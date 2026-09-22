from __future__ import annotations

import asyncio
import importlib
import time
from types import SimpleNamespace

import pytest

from mcp_server.errors import BridgeError as MCPBridgeError
from mcp_server.tool_registry import create_default_registry


@pytest.fixture
def batch_env(addon_package: str):
    batch = importlib.import_module(f"{addon_package}.tools.batch")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    calls = []
    undo = []
    grants = {p.value: True for p in permissions.Permission}
    registry = registry_module.ToolRegistry(enabled_toolsets=("batch", "objects", "python"))
    batch.register_tools(registry)

    def edit(_context, params):
        calls.append(params)
        return {"object": params.get("object_name", "Cube"), "changed": True}

    registry.register("object.test", edit, toolset="objects", modifies=True,
                      permissions=(permissions.Permission.TRANSFORM_OBJECTS,))
    registry.register("python.execute", edit, toolset="python", modifies=True)
    registry.register("checkpoint.undo_last", edit, modifies=True)
    context = registry_module.ToolContext(
        state_module.BridgeState(), permissions.PermissionManager(lambda: grants), registry,
        SimpleNamespace(before_modification=lambda label: undo.append(("before", label)) or True,
                        after_modification=lambda label: undo.append(("after", label))),
    )
    return SimpleNamespace(module=batch, context=context, registry=registry, calls=calls, undo=undo,
                           grants=grants, errors=errors)


def _steps(count=2):
    return [{"method": "object.test", "params": {"object_name": f"Cube{i}"}} for i in range(count)]


def test_batch_is_one_checkpoint_with_per_step_history(batch_env):
    env = batch_env
    result = env.module.batch_execute(env.context, {"steps": _steps()})
    assert result["completed_steps"] == 2
    assert result["atomic"] is False
    assert result["affected_objects"] == ["Cube0", "Cube1"]
    assert [item[0] for item in env.undo] == ["before", "after"]
    assert len(env.context.state.history()) == 2


@pytest.mark.parametrize("steps", [[], _steps(33), [{"method": 1}], [{"method": "object.test", "params": []}],
                                     [{"method": "object.test", "id": "x"}] * 2,
                                     [{"method": "object.test", "unknown": True}]])
def test_batch_rejects_bad_shape_before_edit(batch_env, steps):
    env = batch_env
    with pytest.raises(env.errors.BridgeError):
        env.module.batch_execute(env.context, {"steps": steps})
    assert env.calls == env.undo == []


@pytest.mark.parametrize("method", ["python.execute", "checkpoint.undo_last", "batch.execute", "missing.tool"])
def test_batch_preflights_all_methods_before_edit(batch_env, method):
    env = batch_env
    with pytest.raises(env.errors.BridgeError):
        env.module.batch_execute(env.context, {"steps": [*_steps(1), {"method": method}]})
    assert env.calls == env.undo == []


def test_batch_preflights_permissions(batch_env):
    env = batch_env
    env.grants["TRANSFORM_OBJECTS"] = False
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.batch_execute(env.context, {"steps": _steps()})
    assert caught.value.code == "PERMISSION_DENIED"
    assert env.calls == env.undo == []


@pytest.mark.parametrize("stop", ["permission", "pause", "emergency", "cancel", "deadline"])
def test_batch_rechecks_gates_between_steps(batch_env, monkeypatch, stop):
    env = batch_env

    def first(context, _params):
        env.calls.append("first")
        if stop == "permission":
            env.grants["TRANSFORM_OBJECTS"] = False
        elif stop == "pause":
            context.state.set_paused(True)
        elif stop == "emergency":
            context.state.set_emergency_stopped(True)
        elif stop == "cancel":
            def cancelled():
                raise env.errors.BridgeError("TIMEOUT", "Disconnected")
            context.check_cancelled = cancelled
        else:
            monkeypatch.setattr(env.module.time, "monotonic", lambda: time.perf_counter() + 100000)
        return {"object": "Changed"}

    env.registry.register("object.first", first, toolset="objects", modifies=True)
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.batch_execute(env.context, {"steps": [{"method": "object.first"}, *_steps(1)]})
    assert env.calls == ["first"]
    assert caught.value.context["completed_steps"] == 1
    assert caught.value.context["failed_step_started"] is False
    assert caught.value.context["verification_required"] is True
    assert [item[0] for item in env.undo] == ["before", "after"]


def test_batch_tracks_failing_first_mutation_and_skips_rest(batch_env):
    env = batch_env

    def fail(_context, _params):
        env.calls.append("partial")
        raise ValueError("local secret diagnostic")

    env.registry.register("object.fail", fail, toolset="objects", modifies=True)
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.batch_execute(env.context, {"steps": [{"method": "object.fail"}, *_steps()]})
    assert env.calls == ["partial"]
    assert caught.value.context["failed_step_started"] is True
    assert caught.value.context["execution_started"] is True
    assert caught.value.context["rollback_performed"] is False
    assert "local secret" not in str(caught.value.context)
    assert env.context.state.history()[0]["success"] is False
    assert [item[0] for item in env.undo] == ["before", "after"]


def test_batch_read_only_and_plan_do_not_checkpoint(batch_env):
    env = batch_env
    env.registry.register("scene.inspect", lambda _c, _p: {"scene": "Scene"})
    result = env.module.batch_plan(env.context, {"steps": _steps()})
    assert "NOT handler arguments" in result["preflight_scope"]
    assert env.calls == env.undo == []
    result = env.module.batch_execute(env.context, {"steps": [{"method": "scene.inspect"}]})
    assert result["verification_required"] is False
    assert env.undo == []


def test_batch_bounds_large_invalid_and_cyclic_results(batch_env):
    env = batch_env
    cycle = []
    cycle.append(cycle)
    for result in ({"object": "Cube", "data": "x" * 100000}, cycle, {"nan": float("nan")}):
        assert env.module._bounded_result(result)["result_truncated"] is True
    assert env.module._bounded_result({"value": 3}) == {"value": 3}


def test_queued_disconnect_signals_running_batch(addon_package):
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    queued = queue.QueuedRequest(protocol.Request("cancel", "batch.execute"))
    assert queued.try_start()
    assert queued.cancel_pending(errors.BridgeError("SERVER_ERROR", "Disconnected")) is False
    with pytest.raises(errors.BridgeError) as caught:
        queued.check_active()
    assert caught.value.context["cancellation_requested"] is True
    queued.resolve(protocol.Response.success("cancel", {"stopped": True}))
    assert queued.response.ok


def test_queued_running_deadline_is_cooperative(addon_package):
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    queued = queue.QueuedRequest(protocol.Request("deadline", "batch.execute"))
    assert queued.try_start()
    queued.deadline = 0
    with pytest.raises(errors.BridgeError) as caught:
        queued.check_active()
    assert caught.value.context["deadline_expired"] is True


def test_mcp_batch_cannot_bypass_child_enablement():
    calls = []

    class Client:
        async def request(self, method, params=None, **_kwargs):
            calls.append(method)
            return {"ok": True}

    registry = create_default_registry(Client())
    registry.enable("batch")
    with pytest.raises(MCPBridgeError) as caught:
        asyncio.run(registry.call("batch.execute", {"steps": [{"method": "object.create"}]}))
    assert caught.value.code == "TOOLSET_DISABLED"
    assert calls == []
    registry.enable("objects")
    asyncio.run(registry.call("batch.execute", {"steps": [{"method": "object.create"}]}))
    assert calls == ["batch.execute"]
