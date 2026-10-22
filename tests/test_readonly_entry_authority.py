"""Pause/stop block writers while inspection retains owner and policy gates."""

from __future__ import annotations

import importlib
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def access(addon_package):
    def module(name):
        return importlib.import_module(f"{addon_package}.{name}")
    tools, permissions = module("tool_registry"), module("permissions")
    registry = tools.ToolRegistry(enabled_toolsets=("scene_edit",))
    state = module("state").BridgeState()
    lifetime = module("request_lifecycle").RequestLifetime(module("request_lifecycle").ConnectionLifetime())
    grants = {permission.value: True for permission in permissions.Permission}
    actions, handlers, bookkeeping = [lambda: None], [], []
    def provider():
        actions[0]()
        return dict(grants)
    checkpoints = NS(finish_editor_session=lambda **_kwargs: bookkeeping.append("finalize"),
                     editor_session_status=lambda: None)
    context = tools.ToolContext(state, permissions.PermissionManager(provider), registry, checkpoints)
    executor_type = module("executor").MainThreadExecutor
    class FixedContextExecutor(executor_type):
        @property
        def context(self):
            return context
    executor = FixedContextExecutor(command_queue=module("command_queue").CommandQueue(), registry=registry,
                                    state=state, permissions=context.permissions, checkpoints=checkpoints)
    case = NS(module=module, tools=tools, registry=registry, state=state, lifetime=lifetime,
              grants=grants, actions=actions, handlers=handlers, bookkeeping=bookkeeping, context=context,
              executor=executor, queued=None)
    def handler(_context, _params):
        handlers.append(True)
        return {"inspected": True}
    case.spec = registry.register("scene.fixture", handler, modifies=False, toolset="scene_edit",
                                  permissions=(permissions.Permission.INSPECT_SCENE,), automatic_checkpoint=False)
    def invoke(entry, method="scene.fixture", params=None):
        request = module("protocol").Request("readonly-authority", method, params or {}, _lifecycle=lifetime)
        queued = module("command_queue").QueuedRequest(request, deadline=float("inf"))
        assert queued.try_start()
        case.queued = queued
        context.request_lifecycle, context.check_final_request = lifetime, queued.check_active
        if entry == "direct":
            return registry.dispatch(method, request.params, context)
        response = executor.execute_request(request, check_cancelled=queued.check_active)
        if not response.ok:
            raise module("errors").BridgeError(response.error["code"], response.error["message"], response.error.get("context"))
        return response.result
    case.invoke = invoke
    return case


def stop(case, flag):
    (case.state.set_paused if flag == "pause" else case.state.set_emergency_stopped)(True)


@pytest.mark.parametrize("entry", ("direct", "executor"))
@pytest.mark.parametrize("flag", ("pause", "emergency"))
@pytest.mark.parametrize("when", ("initial", "provider"))
def test_readonly_inspection_remains_available_while_mutations_are_stopped(access, entry, flag, when):
    case = access
    if when == "initial":
        stop(case, flag)
    else:
        case.actions[0] = lambda: stop(case, flag)
    assert case.invoke(entry) == {"inspected": True}
    assert case.handlers == [True] and case.context.handler_entries == 1
    assert case.bookkeeping == [] and case.registry.executing_mutators == 0


@pytest.mark.parametrize("entry", ("direct", "executor"))
@pytest.mark.parametrize("flag,code", (("pause", "AGENT_PAUSED"), ("emergency", "EMERGENCY_STOPPED")))
@pytest.mark.parametrize("when", ("initial", "provider"))
def test_modifying_spec_still_denies_before_handler_or_checkpoint(access, entry, flag, code, when):
    case = access
    case.registry._tools[case.spec.name] = replace(case.spec, modifies=True)
    if when == "initial":
        stop(case, flag)
    else:
        case.actions[0] = lambda: stop(case, flag)
    with pytest.raises(case.module("errors").BridgeError) as caught:
        case.invoke(entry)
    assert caught.value.code == code
    assert case.handlers == case.bookkeeping == [] and case.context.handler_entries == 0


@pytest.mark.parametrize("entry", ("direct", "executor"))
@pytest.mark.parametrize("loss,code", (("cancel", "TIMEOUT"), ("deadline", "TIMEOUT"),
    ("disconnect", "TIMEOUT"), ("permission", "PERMISSION_DENIED"),
    ("toolset", "TOOLSET_DISABLED"), ("identity", "NOT_IMPLEMENTED")))
def test_paused_readonly_call_still_denies_authority_lost_in_last_provider(access, entry, loss, code):
    case = access
    case.state.set_paused(True)
    case.state.set_emergency_stopped(True)
    def lose_authority():
        if loss == "cancel":
            case.queued.cancel_pending(case.module("errors").BridgeError("TIMEOUT", "Owned cancellation"))
        elif loss == "deadline":
            case.lifetime.deadline = 0.
        elif loss == "disconnect":
            case.lifetime.connection.disconnected.set()
        elif loss == "permission":
            case.grants["INSPECT_SCENE"] = False
        elif loss == "toolset":
            case.registry.disable_toolset("scene_edit")
        else:
            case.registry._tools[case.spec.name] = replace(case.spec)
    case.actions[0] = lose_authority
    with pytest.raises(case.module("errors").BridgeError) as caught:
        case.invoke(entry)
    assert caught.value.code == code
    assert case.handlers == case.bookkeeping == [] and case.context.handler_entries == 0


@pytest.mark.parametrize("entry", ("direct", "executor"))
def test_provider_cannot_downgrade_retained_writer_before_stop_classification(access, entry):
    case = access
    writer = replace(case.spec, modifies=True)
    case.registry._tools[writer.name] = writer
    def downgrade():
        case.registry._tools[writer.name] = replace(writer, modifies=False)
        case.state.set_paused(True)
    case.actions[0] = downgrade
    with pytest.raises(case.module("errors").BridgeError) as caught:
        case.invoke(entry)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert case.handlers == case.bookkeeping == [] and case.context.handler_entries == 0


@pytest.mark.parametrize("registry_present", (False, True))
def test_unretained_raw_mutation_gate_remains_conservative(access, registry_present):
    case = access
    case.state.set_paused(True)
    if not registry_present:
        case.context.registry = None
    with pytest.raises(case.module("errors").BridgeError) as caught:
        case.tools.check_final_mutation(case.context, case.spec.name)
    assert caught.value.code == "AGENT_PAUSED"


def test_explicit_final_gate_rejects_replacement_of_retained_writer(access):
    case = access
    writer = replace(case.spec, modifies=True)
    case.registry._tools[writer.name] = replace(writer, modifies=False)
    case.state.set_paused(True)
    with pytest.raises(case.module("errors").BridgeError) as caught:
        case.tools.check_final_mutation(case.context, writer.name, expected_spec=writer)
    assert caught.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("loss,code", (("deadline", "TIMEOUT"), ("disconnect", "TIMEOUT"),
    ("toolset", "TOOLSET_DISABLED"), ("same_spec_flags", "NOT_IMPLEMENTED"),
    ("readonly_to_writer", "NOT_IMPLEMENTED")))
def test_prepared_readonly_call_rechecks_authority_at_actual_handler_entry(access, loss, code):
    case = access
    case.state.set_paused(True)
    case.state.set_emergency_stopped(True)
    case.context.request_lifecycle = case.lifetime
    prepared = case.registry.prepare_call(case.spec.name, {}, case.context)
    if loss == "deadline":
        case.lifetime.deadline = 0.
    elif loss == "disconnect":
        case.lifetime.connection.disconnected.set()
    elif loss == "toolset":
        case.registry.disable_toolset("scene_edit")
    else:
        case.registry._tools[case.spec.name] = replace(case.spec, modifies=loss == "readonly_to_writer")
    with pytest.raises(case.module("errors").BridgeError) as caught:
        case.registry.invoke(prepared, {}, case.context)
    assert caught.value.code == code
    assert case.handlers == case.bookkeeping == [] and case.context.handler_entries == 0


@pytest.mark.parametrize("entry", ("direct", "executor"))
@pytest.mark.parametrize("flag", ("pause", "emergency"))
def test_registered_job_inspection_cancel_and_nonmodifying_controls_remain_usable(access, monkeypatch, entry, flag):
    case = access
    core = case.module("tools.core")
    core.register_tools(case.registry)
    monkeypatch.setattr(core, "require_blender", lambda: NS(
        app=NS(version_string="fixture"), data=NS(filepath=""),
        context=NS(scene=NS(name="Scene"), view_layer=NS(objects=NS(active=None)), mode="OBJECT")))
    case.module("tools.paint_jobs").register_tools(case.registry)
    events = []
    case.context.jobs = NS(inspect=lambda _id: events.append("inspect") or {"phase": "paused"},
                           list=lambda _limit: events.append("list") or {"jobs": []},
                           cancel=lambda _id: events.append("cancel") or {"cancel_requested": True},
                           status=lambda: {"active_job": None})
    stop(case, flag)
    assert case.registry.get("bridge.status").modifies is False
    status = case.invoke(entry, "bridge.status")
    assert status["agent"]["paused"] is True
    assert status["agent"]["emergency_stopped"] is (flag == "emergency")
    job = {"job_id": "job_" + "0" * 32}
    for name, params in (("jobs.inspect", job), ("jobs.list", {}), ("jobs.cancel", job),
                         ("toolsets.list", {}), ("toolsets.enable", {"name": "materials"})):
        assert case.registry.get(name).modifies is False
        case.invoke(entry, name, params)
    assert events == ["inspect", "list", "cancel"] and case.bookkeeping == []
    assert case.registry.get("image.paint_job_start").modifies is True
    with pytest.raises(case.module("errors").BridgeError) as caught:
        case.invoke(entry, "image.paint_job_start", {})
    assert caught.value.code == ("AGENT_PAUSED" if flag == "pause" else "EMERGENCY_STOPPED")
    assert events == ["inspect", "list", "cancel"]
