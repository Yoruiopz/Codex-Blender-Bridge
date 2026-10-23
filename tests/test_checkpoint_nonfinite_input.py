"""Nonfinite guarded requests fail before admission or authored execution."""

from __future__ import annotations

import importlib
import math
from typing import Any

import pytest
from test_checkpoint_admission_executor import (
    assert_context_restored,
    editor_session,
    guarded_executor,
    recovery_records,
)

assert guarded_executor  # Reuse retained native/checkpoint recovery evidence.

NONFINITE = (
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="positive-infinity"),
    pytest.param(-math.inf, id="negative-infinity"),
)
ENTRIES = ("executor", "registry-dispatch", "registry-invoke")


@pytest.fixture
def scale_executor(guarded_executor: Any, monkeypatch: Any) -> Any:
    case = guarded_executor
    package = case.executor_module.__package__
    transforms = importlib.import_module(f"{package}.tools.transforms")
    admission = importlib.import_module(f"{package}.tools._artist_checkpoint_admission")
    permissions = importlib.import_module(f"{package}.permissions")
    case.unexpected_entries = []

    def forbidden(name: str) -> Any:
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            case.unexpected_entries.append(name)
            pytest.fail(f"Invalid parameters reached {name}")

        return fail

    # Register the real scale handler and its guarded ToolSpec. Each entry that
    # could touch Blender or user providers must remain behind parameter checks.
    monkeypatch.setattr(admission, "factory", forbidden("admission factory"))
    monkeypatch.setattr(transforms, "require_blender", forbidden("scale handler"))
    transforms.register_tools(case.registry)
    case.registry.enable_toolset("objects")
    case.scale_spec = case.registry.get("transform.scale")
    assert case.scale_spec.handler is transforms.scale
    assert case.scale_spec.checkpoint_admission_factory is not None
    case.context.permissions = permissions.PermissionManager(forbidden("permission provider"))
    case.context.check_cancelled = forbidden("cancellation provider")
    return case


def call_scale(case: Any, entry: str, value: Any) -> Any:
    params = {"object_name": "Cube", "factor": value}
    if entry == "executor":
        return case.executor.dispatch("transform.scale", params)
    if entry == "registry-dispatch":
        return case.registry.dispatch("transform.scale", params, case.context)
    return case.registry.invoke(case.scale_spec, params, case.context)


def nested_value(shape: str, value: Any) -> Any:
    if shape == "list":
        return [1.0, [value]]
    if shape == "tuple":
        return (1.0, (value,))
    if shape == "dict":
        return {"nested": {"factor": value}}
    return value


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("shape", ("scalar", "list", "tuple", "dict"))
@pytest.mark.parametrize("value", NONFINITE)
def test_nonfinite_scale_is_invalid_before_providers_or_checkpoint_writes(
    scale_executor: Any, entry: str, shape: str, value: float,
) -> None:
    case = scale_executor
    session = editor_session(case)
    before_records = recovery_records(case)
    before_scene = dict(case.stack.scene)
    before_frames = list(case.stack.frames)
    before_cursor = case.stack.cursor
    before_history = case.state.history()

    with pytest.raises(case.checkpoint.BridgeError) as caught:
        call_scale(case, entry, nested_value(shape, value))

    error = caught.value
    assert error.code == "INVALID_ARGUMENT"
    assert error.context["checkpoint_parameters_finite"] is False
    assert not error.context.get("execution_started", False)
    assert not error.context.get("possible_mutation", False)
    assert case.unexpected_entries == []
    assert case.context.handler_entries == 0 and case.handlers == []
    assert case.captures == [] and case.checks == []
    assert case.checkpoint_calls == [] and case.pushes == []
    assert dict(case.stack.scene) == before_scene
    assert case.stack.frames == before_frames and case.stack.cursor == before_cursor
    assert recovery_records(case) == before_records
    assert case.manager._editor_session is session
    assert_context_restored(case)

    history = case.state.history()
    if entry == "executor":
        assert len(history) == len(before_history) + 1
        assert history[0]["tool"] == "transform.scale"
        assert history[0]["success"] is False
        assert history[0]["error_code"] == "INVALID_ARGUMENT"
        assert history[0]["affected_objects"] == []
        assert history[1:] == before_history
        assert not case.state.snapshot()["is_executing"]
    else:
        assert history == before_history


class CustomFloat(float):
    def __float__(self) -> float:
        pytest.fail("Checkpoint validation invoked a custom numeric conversion")


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("value", (0.0, -0.0, 1e308, -1e-308))
def test_finite_values_still_reach_the_guarded_writer(guarded_executor: Any, entry: str, value: float) -> None:
    case, params = guarded_executor, {"value": value}
    if entry == "executor":
        result = case.executor.dispatch("scene.guarded", params)
    elif entry == "registry-dispatch":
        result = case.registry.dispatch("scene.guarded", params, case.context)
    else:
        result = case.registry.invoke(case.spec, params, case.context)
    assert result["value"] == value and case.stack.scene["value"] == value
    assert math.copysign(1.0, case.stack.scene["value"]) == math.copysign(1.0, value)
    assert len(case.captures) == len(case.handlers) == case.context.handler_entries == 1
    assert_context_restored(case)


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize(
    "value",
    (
        pytest.param(CustomFloat(math.inf), id="custom-numeric-type"),
        pytest.param([0] * 4097, id="item-budget"),
        pytest.param("x" * 4097, id="string-budget"),
    ),
)
def test_unsupported_or_unbounded_parameters_keep_not_implemented(
    scale_executor: Any, entry: str, value: Any,
) -> None:
    case = scale_executor
    before_records = recovery_records(case)
    before_scene = dict(case.stack.scene)
    frames = len(case.stack.frames)

    with pytest.raises(case.checkpoint.BridgeError) as caught:
        call_scale(case, entry, value)

    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context == {"checkpoint_parameters_bounded": False}
    assert case.unexpected_entries == []
    assert case.context.handler_entries == 0
    assert case.checkpoint_calls == [] and case.pushes == []
    assert len(case.stack.frames) == frames and dict(case.stack.scene) == before_scene
    assert recovery_records(case) == before_records
    assert_context_restored(case)


@pytest.mark.parametrize("value", NONFINITE)
def test_nonfinite_parameter_drift_after_a_write_retains_mutation_evidence(
    guarded_executor: Any, value: float,
) -> None:
    case = guarded_executor
    before_steps = tuple(case.manager._undo_steps)
    frames = len(case.stack.frames)
    primary_errors = []

    def partial_writer(context: Any, params: Any) -> Any:
        case.stack.scene["value"] = 13
        params["value"] = value
        try:
            context.checkpoint_admission.check_after_read()
        except case.checkpoint.BridgeError as error:
            primary_errors.append((error, dict(error.context), context.checkpoint_admission))
            raise
        pytest.fail("Nonfinite parameter drift admitted another write")

    case.handler_hook = partial_writer
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 13})

    primary, original_context, binding = primary_errors[0]
    assert caught.value is primary and primary.code == "INVALID_ARGUMENT"
    assert original_context == {"checkpoint_parameters_finite": False}
    assert binding.stopped is primary
    assert primary.context["execution_started"] is True
    assert primary.context["possible_mutation"] is True
    assert primary.context["verification_required"] is True
    assert primary.context["checkpoint_finalization_refused"]["code"] == "INVALID_ARGUMENT"
    assert primary.context["checkpoint_finalization_refused"]["primary_error_preserved"] is True
    assert case.stack.scene["value"] == 13
    assert len(case.handlers) == case.context.handler_entries == 1
    assert case.manager._pending is not None
    assert tuple(case.manager._undo_steps) == before_steps
    assert len(case.stack.frames) == frames + 1 and len(case.pushes) == 1
    assert case.pushes[0]["message"] == "Codex Before: scene.guarded"
    assert case.state.history()[0]["success"] is False
    assert case.state.history()[0]["error_code"] == "INVALID_ARGUMENT"
    assert_context_restored(case)
