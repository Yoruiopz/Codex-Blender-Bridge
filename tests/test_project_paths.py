"""Legacy save stays typed but never enters its unsafe native backend."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def save_env(addon_package, monkeypatch):
    def module(name):
        return importlib.import_module(f"{addon_package}.{name}")
    core, registry_mod, permission = module("tools.core"), module("tool_registry"), module("permissions")
    state, queue, protocol = module("state").BridgeState(), module("command_queue"), module("protocol")
    registry = registry_mod.ToolRegistry()
    core.register_tools(registry)
    grants = {"SAVE_PROJECT": True, "ACCESS_EXTERNAL_FILES": True}
    action, calls = [lambda: None], []

    def provider():
        calls.append("provider")
        action[0]()
        return dict(grants)

    def no_blender():
        calls.append("blender")
        raise AssertionError("Unavailable saving must not access Blender or path readers")

    monkeypatch.setattr(core, "require_blender", no_blender)
    markers = []
    checkpoints = NS(finish_editor_session=lambda: markers.append("finish"),
                     editor_session_status=lambda: {"state": "deferred", "group_id": "old-session"})
    executor = module("executor").MainThreadExecutor(command_queue=queue.CommandQueue(), registry=registry,
        state=state, permissions=permission.PermissionManager(provider), checkpoints=checkpoints)
    context = executor.context
    lifetime_mod = module("request_lifecycle")
    lifetime = lifetime_mod.RequestLifetime(lifetime_mod.ConnectionLifetime())
    request = protocol.Request("save-denial", "project.save", {}, _lifecycle=lifetime)
    queued = queue.QueuedRequest(request, deadline=float("inf"))
    assert queued.try_start()
    context.request_lifecycle, context.check_final_request = lifetime, queued.check_active
    return NS(module=module, core=core, registry=registry, context=context, executor=executor, state=state,
              grants=grants, action=action, calls=calls, markers=markers, lifetime=lifetime,
              request=request, queued=queued, errors=module("errors"))


@pytest.mark.parametrize("filepath", [None, "/owned/new.blend", "/existing/current.blend", "relative.blend", "//server/private.blend", "bad\0path.blend"])
def test_save_refuses_before_blender_or_destination_probe(save_env, filepath):
    env = save_env
    with pytest.raises(env.errors.BridgeError) as caught:
        env.core.save_project(env.context, {} if filepath is None else {"filepath": filepath})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["reason"] == "UNOBSERVABLE_NATIVE_SAVE_SIDE_EFFECTS"
    assert caught.value.context["execution_started"] is False
    assert caught.value.context["native_save_invoked"] is False
    assert caught.value.context["project_saved"] is False and caught.value.context["bridge_file_writes"] is False
    assert env.calls == ["provider"] and env.markers == []


@pytest.mark.parametrize("filepath", ["", " ", 42, [], {}])
def test_save_argument_errors_do_not_touch_blender_or_provider(save_env, filepath):
    env = save_env
    with pytest.raises(env.errors.BridgeError) as caught:
        env.core.save_project(env.context, {"filepath": filepath})
    assert caught.value.code == "INVALID_ARGUMENT" and caught.value.context["native_save_invoked"] is False
    assert env.calls == env.markers == []


@pytest.mark.parametrize("missing", ["SAVE_PROJECT", "ACCESS_EXTERNAL_FILES"])
def test_last_grant_snapshot_preserves_permission_denial(save_env, missing):
    env = save_env
    env.grants[missing] = False
    with pytest.raises(env.errors.BridgeError) as caught:
        env.core.save_project(env.context, {"filepath": "/never/probed.blend"})
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["required"] == ["SAVE_PROJECT", "ACCESS_EXTERNAL_FILES"]
    assert caught.value.context["missing_permissions"] == [missing]
    assert env.calls == ["provider"] and env.markers == []


@pytest.mark.parametrize("stop", ["queued", "disconnect", "deadline", "pause", "emergency"])
def test_last_provider_stop_preserves_canonical_denial(save_env, stop):
    env = save_env

    def lose_authority():
        if stop == "queued":
            env.queued.cancel_pending(env.errors.BridgeError("TIMEOUT", "Caller canceled"))
        elif stop == "disconnect":
            env.lifetime.connection.disconnected.set()
        elif stop == "deadline":
            env.lifetime.deadline = 0.
        elif stop == "pause":
            env.state.set_paused(True)
        else:
            env.state.set_emergency_stopped(True)

    env.action[0] = lose_authority
    with pytest.raises(env.errors.BridgeError) as caught:
        env.core.save_project(env.context, {"filepath": "/never/probed.blend"})
    assert caught.value.code == {"pause": "AGENT_PAUSED", "emergency": "EMERGENCY_STOPPED"}.get(stop, "TIMEOUT")
    assert caught.value.context["native_save_invoked"] is False and env.markers == []


def test_original_permission_error_identity_is_preserved(save_env):
    env = save_env
    original = env.errors.BridgeError("PERMISSION_DENIED", "Exact permission denial")

    def deny():
        raise original

    env.action[0] = deny
    with pytest.raises(env.errors.BridgeError) as caught:
        env.core.save_project(env.context, {})
    assert caught.value is original and env.markers == []


def test_current_file_refusal_does_not_require_external_path_grant(save_env):
    env = save_env
    env.grants["ACCESS_EXTERNAL_FILES"] = False
    with pytest.raises(env.errors.BridgeError) as caught:
        env.core.save_project(env.context, {})
    assert caught.value.code == "NOT_IMPLEMENTED" and "blender" not in env.calls


@pytest.mark.parametrize("outcome", ["unsupported", "permission", "cancel"])
def test_executor_save_refusal_does_not_finalize_old_editor_work(save_env, outcome):
    env = save_env
    reads = []

    def last_grant():
        reads.append(True)
        if len(reads) == 2:
            if outcome == "permission":
                env.grants["SAVE_PROJECT"] = False
            elif outcome == "cancel":
                env.queued.cancel_pending(env.errors.BridgeError("TIMEOUT", "Caller canceled"))

    env.action[0] = last_grant
    response = env.executor.execute_request(env.request, check_cancelled=env.queued.check_active)
    assert not response.ok and response.error["code"] == {"unsupported": "NOT_IMPLEMENTED", "permission": "PERMISSION_DENIED", "cancel": "TIMEOUT"}[outcome]
    assert response.error["context"]["execution_started"] is False
    assert response.error["context"]["undo_group"]["group_id"] == "old-session"
    assert env.markers == [] and "blender" not in env.calls


@pytest.mark.parametrize("method", ["fixture.failed_writer", "project.save"])
def test_unrecognized_or_unmeasured_failures_keep_conservative_finalization(save_env, method):
    env = save_env
    if method == "project.save":
        def unexpected():
            if len(env.calls) == 2:
                raise RuntimeError("Unknown provider failure")
        env.action[0] = unexpected
    else:
        def failed(_context, _params):
            raise env.errors.BridgeError("OPERATION_FAILED", "A different writer cannot spoof save refusal", {
                "execution_started": False, "native_save_invoked": False})
        env.registry.register(method, failed, modifies=True, automatic_checkpoint=False)
    response = env.executor.execute_request(env.module("protocol").Request("other-writer", method, {}))
    assert not response.ok and response.error["code"] == "OPERATION_FAILED"
    assert env.markers == ["finish"]


def test_save_registration_and_mcp_schema_remain_compatible(save_env):
    import inspect

    from mcp_server.tools.catalog import CORE_DEFINITIONS
    from mcp_server.tools.project import ProjectTools
    env = save_env
    spec = env.registry.get("project.save")
    assert spec.modifies and not spec.automatic_checkpoint and spec.toolset == "core"
    assert spec.remote and {item.value for item in spec.permissions} == {"SAVE_PROJECT"}
    tool = next(item for item in CORE_DEFINITIONS if item.name == "project.save")
    assert set(tool.required_permissions) == {"SAVE_PROJECT"}
    signature = inspect.signature(ProjectTools.project_save)
    assert list(signature.parameters) == ["self", "filepath"]
    assert signature.parameters["filepath"].default is None
