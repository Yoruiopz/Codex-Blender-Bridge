"""Authored admission starts before the first arbitrary entry provider."""

from __future__ import annotations

import importlib
from dataclasses import replace

import pytest
from test_checkpoint_admission_executor import guarded_executor

assert guarded_executor  # Explicitly reuse the guarded request/checkpoint fixture.


@pytest.mark.parametrize("entry", ("direct", "executor_provider", "executor_callback"))
def test_first_entry_callback_cannot_become_the_authored_baseline(guarded_executor, entry):
    case = guarded_executor
    permission = importlib.import_module(f"{case.executor_module.__package__}.permissions")
    fired = []

    def change():
        if not fired:
            fired.append(True)
            case.static["profile"] = "newer manual authored edit"

    def provider():
        change()
        return {item.value: True for item in permission.Permission}

    frames = len(case.stack.frames)
    if entry != "executor_callback":
        case.context.permissions = permission.PermissionManager(provider)
    if entry == "direct":
        with pytest.raises(case.checkpoint.BridgeError) as caught:
            case.registry.dispatch("scene.guarded", {"value": 9}, case.context)
        assert caught.value is case.denial
    else:
        protocol = importlib.import_module(f"{case.executor_module.__package__}.protocol")
        response = case.executor.execute_request(protocol.Request("first-authored", "scene.guarded", {"value": 9}),
                                                 check_cancelled=change if entry == "executor_callback" else None)
        assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
    assert fired == [True] and len(case.captures) == 1 and case.handlers == []
    assert case.captures[0].frozen == (("profile", "valid"),)
    assert case.static["profile"] == "newer manual authored edit"
    assert len(case.stack.frames) == frames and case.pushes == []


@pytest.mark.parametrize("denial", ("permission", "cancellation"))
def test_bounded_factory_error_is_deferred_until_authorization_succeeds(guarded_executor, denial):
    case = guarded_executor
    attempted = []

    def factory(_context, _params):
        attempted.append(True)
        raise case.checkpoint.BridgeError("NOT_IMPLEMENTED", "Bounded private descriptor profile unavailable")

    spec = case.registry.get("scene.guarded")
    case.registry._tools[spec.name] = replace(spec, checkpoint_admission_factory=factory)
    permission = importlib.import_module(f"{case.executor_module.__package__}.permissions")
    if denial == "permission":
        case.context.permissions = permission.PermissionManager(lambda: {})

    def cancelled():
        raise case.checkpoint.BridgeError("TIMEOUT", "Owned arbitrary cancellation")

    protocol = importlib.import_module(f"{case.executor_module.__package__}.protocol")
    response = case.executor.execute_request(protocol.Request("deferred-error", "scene.guarded", {"value": 9}),
                                             check_cancelled=cancelled if denial == "cancellation" else None)
    assert not response.ok and response.error["code"] == ("PERMISSION_DENIED" if denial == "permission" else "TIMEOUT")
    assert attempted == [True] and case.handlers == [] and case.pushes == []
    assert "descriptor" not in str(response.error)


@pytest.mark.parametrize("loss", ("spec", "registry"))
def test_binding_identity_includes_concrete_spec_and_registry(guarded_executor, loss):
    case = guarded_executor
    params = {"value": 9}
    with case.registry.checkpoint_admission(case.spec, params, case.context) as binding:
        if loss == "spec":
            case.registry._tools[case.spec.name] = replace(case.spec, handler=lambda _c, _p: {"foreign": True})
        else:
            other = case.registry_module.ToolRegistry(enabled_toolsets=("scene_edit",))
            other._tools[case.spec.name] = case.spec
            case.context.registry = other
        with pytest.raises(case.checkpoint.BridgeError) as caught:
            binding.check_after_read()
        assert caught.value.context["checkpoint_admission_valid"] is False
    assert case.handlers == [] and case.pushes == []
