"""Actual executor error containment when operation bookkeeping fails."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def env(addon_package):
    def load(name):
        return importlib.import_module(f"{addon_package}.{name}")

    state = load("state").BridgeState()
    registry = load("tool_registry").ToolRegistry()
    calls = []
    checkpoints = NS(
        finish_editor_session=lambda: calls.append("editor_finalization"),
        editor_session_status=lambda: None,
    )
    executor = load("executor").MainThreadExecutor(
        command_queue=load("command_queue").CommandQueue(), registry=registry, state=state,
        permissions=load("permissions").PermissionManager(lambda: {}), checkpoints=checkpoints,
    )
    return NS(load=load, state=state, registry=registry, calls=calls, executor=executor)


@pytest.mark.parametrize("outcome", ["success", "bridge_error", "ordinary_error", "unknown_method"])
@pytest.mark.parametrize("append_first", [False, True])
def test_history_failure_is_never_retried_and_primary_bridge_error_survives(env, monkeypatch, outcome, append_first):
    attempts = []
    original = env.state.record_operation

    def broken_history(**kwargs):
        attempts.append(kwargs)
        if append_first:
            original(**kwargs)
        raise RuntimeError("modeled history failure")

    def handler(*_):
        env.calls.append("handler")
        if outcome == "bridge_error":
            raise env.load("errors").BridgeError("PERMISSION_DENIED", "Original denial", {"original": True})
        if outcome == "ordinary_error":
            raise ValueError("modeled operation failure")
        return {"changed": True}

    if outcome != "unknown_method":
        env.registry.register("history.fixture", handler, modifies=True, automatic_checkpoint=False)
    monkeypatch.setattr(env.state, "record_operation", broken_history)
    request = env.load("protocol").Request(id="history-owner", method="history.fixture", params={})
    response = env.executor.execute_request(request)
    assert not response.ok and response.id == request.id
    expected = {"bridge_error": "PERMISSION_DENIED", "unknown_method": "METHOD_NOT_FOUND"}.get(outcome, "OPERATION_FAILED")
    assert response.error["code"] == expected
    facts = response.error["context"]
    assert facts["history_recording_failed"] and facts["history_outcome_unknown"]
    assert facts["history_record_verified"] is False and facts["history_retry_attempted"] is False
    assert len(attempts) == 1
    assert len(env.state.history(10)) == int(append_first)
    if outcome == "bridge_error":
        assert response.error["message"] == "Original denial" and facts["original"]
    if outcome == "unknown_method":
        assert env.calls == []
    else:
        assert env.calls == ["handler", "editor_finalization"]
        assert env.registry.executing_mutators == 0
        assert env.load("task_plans").get_task_plans(env.state).executing_mutators == 0
    if outcome == "success":
        assert facts["execution_started"] is True
        assert facts["detail"] == "Operation history recording failed."
        assert "modeled history failure" not in str(response.error)


def test_final_response_boundary_contains_secondary_reporting_failure_without_retry(env, monkeypatch):
    calls = []

    def broken_invoke(*_args, **_kwargs):
        calls.append("invoke")
        raise RuntimeError("private reporting detail must not reach response")

    monkeypatch.setattr(env.executor, "_invoke", broken_invoke)
    request = env.load("protocol").Request(id="outer-owner", method="history.fixture", params={})
    response = env.executor.execute_request(request)
    assert not response.ok and response.id == request.id
    assert response.error["code"] == "SERVER_ERROR"
    assert response.error["context"] == {
        "error_reporting_failed": True, "execution_outcome_unknown": True,
        "possible_mutation": True, "verification_required": True,
    }
    assert "private reporting detail" not in str(response.error)
    assert calls == ["invoke"] and env.calls == [] and env.state.history(10) == []


@pytest.mark.parametrize("outcome", ["success", "bridge_error"])
def test_fallback_contains_envelope_normalization_failure_without_reinvocation(env, monkeypatch, outcome):
    calls = []

    class InvalidReportingValue:
        @property
        def name(self):
            calls.append("bad_value")
            raise RuntimeError("private serialization detail")

    def invoke(*_args, **_kwargs):
        calls.append("invoke")
        result = {"invalid": InvalidReportingValue()}
        if outcome == "bridge_error":
            raise env.load("errors").BridgeError("PERMISSION_DENIED", "Primary denial", result)
        return result

    monkeypatch.setattr(env.executor, "_invoke", invoke)
    protocol = env.load("protocol")
    request = protocol.Request(id="serialization-owner", method="history.fixture", params={})
    response = env.executor.execute_request(request)
    assert not response.ok and response.error["code"] == "SERVER_ERROR"
    assert response.error["context"]["error_reporting_failed"]
    encoded = protocol.encode_response(response)
    assert encoded.endswith(b"\n") and b"serialization-owner" in encoded
    assert b"private serialization detail" not in encoded
    assert calls == ["invoke", "bad_value"] and env.calls == [] and env.state.history(10) == []


def test_fallback_does_not_call_a_failing_error_envelope_builder_twice(env, monkeypatch):
    calls = []
    protocol = env.load("protocol")

    def invoke(*_args, **_kwargs):
        calls.append("invoke")
        raise env.load("errors").BridgeError("PERMISSION_DENIED", "Primary denial")

    def broken_failure(*_args, **_kwargs):
        calls.append("failure_builder")
        raise RuntimeError("modeled failure builder")

    monkeypatch.setattr(env.executor, "_invoke", invoke)
    monkeypatch.setattr(protocol.Response, "failure", broken_failure)
    response = env.executor.execute_request(protocol.Request(id="builder-owner", method="history.fixture", params={}))
    assert not response.ok and response.error["code"] == "SERVER_ERROR"
    assert calls == ["invoke", "failure_builder"] and env.calls == []
    assert protocol.encode_response(response).endswith(b"\n")
