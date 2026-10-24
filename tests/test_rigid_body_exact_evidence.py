"""Registered rigid-cache calls must preserve typed captured custom evidence."""

from __future__ import annotations

import importlib
import json
import math
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from test_rigid_body_lifecycle import rigid_case  # noqa: F401

PAYLOADS = (
    pytest.param(False, 0, id="bool-to-int"),
    pytest.param(0, 0., id="int-to-float"),
    pytest.param({"values": [False, {"selected": False}]},
                 {"values": [0, {"selected": 0}]}, id="nested-bool-to-int"),
    pytest.param(0., -0., id="positive-to-negative-zero"),
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@pytest.fixture
def exact_case(rigid_case, monkeypatch):  # noqa: F811 - imported pytest fixture
    case = rigid_case
    reader = importlib.import_module(f"{case.module.__package__}._object_rna_mutation")._custom
    owner, captures = {"payload": None}, []
    original = case.module.scope.snapshot

    def snapshot(bpy, scene, params):
        result = original(bpy, scene, params)
        # This is the actual production custom-value reader used by object_state
        # inside the real rigid scope. The fake profile retains its other native
        # ownership/budget behavior; every action below enters the public tool.
        custom = reader(owner)
        captures.append(custom)
        return {**result, "protected": (*result["protected"], ("custom-owner", custom))}

    monkeypatch.setattr(case.module.scope, "snapshot", snapshot)
    return NS(case=case, owner=owner, reader=lambda: reader(owner), captures=captures)


def observed_call(env, params):
    case = env.case
    try:
        result = case.registry.dispatch("rigid_body.cache", params, case.context)
    except case.errors.BridgeError as error:
        outcome = {"error": error.code, "primary_error_type": error.context.get("primary_error_type"),
                   "frame_recovery": error.context.get("frame_recovery")}
        value = (error, None)
    else:
        outcome = {"completed": result["completed"],
                   "authored_settings_preserved": result["authored_settings_preserved"],
                   "frame_recovery": result["frame_recovery"]}
        value = (None, result)
    print("RIGID_CACHE_EXACT_OBSERVATION " + canonical({
        "method": "rigid_body.cache", "path": "ToolRegistry.dispatch",
        "native_execution": False, "custom_projection": env.reader(),
        "native_calls": case.physics.native_calls, "resets": case.physics.resets,
        "frame_calls": case.physics.frame_calls, **outcome}))
    return value


def assert_no_native_work(case):
    assert not case.physics.native_calls and not case.physics.frame_calls and case.physics.resets == 0


@pytest.mark.parametrize("before,after", PAYLOADS)
def test_registered_cache_refuses_provider_typed_drift_after_handler_preview(exact_case, before, after):
    env, case = exact_case, exact_case.case
    env.owner["payload"] = deepcopy(before)
    params = case.proposal()
    frozen = canonical(env.reader())
    changed = []

    def granting_provider():
        # First capture is the caller's preview; second is cache()'s own fresh
        # preview. This provider runs after that complete baseline and before
        # reset, range/frame writes or native cache work.
        if len(env.captures) >= 2 and not changed:
            assert_no_native_work(case)
            env.owner["payload"] = deepcopy(after)
            changed.append(canonical(env.reader()))

    case.provider.hook = granting_provider
    error, result = observed_call(env, params)
    assert changed and changed[0] != frozen
    assert error is not None, result
    assert error.code == "INVALID_ARGUMENT" and error.context["execution_started"] is False
    assert canonical(env.reader()) == changed[0]
    assert_no_native_work(case)


@pytest.mark.parametrize("before,after", PAYLOADS)
def test_registered_cache_stale_preview_control_already_distinguishes_types(exact_case, before, after):
    env, case = exact_case, exact_case.case
    env.owner["payload"] = deepcopy(before)
    params = case.proposal()
    old_projection = canonical(env.reader())
    env.owner["payload"] = deepcopy(after)
    assert canonical(env.reader()) != old_projection
    error, result = observed_call(env, params)
    assert error is not None, result
    assert error.code == "INVALID_ARGUMENT"
    assert_no_native_work(case)


@pytest.mark.parametrize("before,after", PAYLOADS)
def test_registered_cache_accepts_unchanged_typed_custom_evidence(exact_case, before, after):
    env, case = exact_case, exact_case.case
    env.owner["payload"] = deepcopy(before)
    original = canonical(env.reader())
    error, result = observed_call(env, case.proposal())
    assert error is None
    assert result["completed"] and result["authored_settings_preserved"]
    assert canonical(env.reader()) == original


@pytest.mark.parametrize("operation", ["BAKE", "FREE", "INVALIDATE"])
@pytest.mark.parametrize("before,after", PAYLOADS)
def test_registered_cache_refuses_typed_drift_in_owned_publication(exact_case, operation, before, after):
    env, case = exact_case, exact_case.case
    env.owner["payload"] = deepcopy(before)
    case.cache.is_baked = operation == "FREE"
    params = case.proposal(operation)
    original = canonical(env.reader())
    at_drift = []

    def drift(*_args):
        if not at_drift:
            env.owner["payload"] = deepcopy(after)
            at_drift.append((canonical(env.reader()), len(case.physics.frame_calls), case.physics.resets))

    if operation == "INVALIDATE":
        case.physics.frame_hook = drift
    else:
        case.physics.after_native = drift
    error, result = observed_call(env, params)
    assert at_drift and at_drift[0][0] != original
    assert error is not None, result
    assert error.code == "INVALID_ARGUMENT"
    assert not error.context["frame_recovery"]["verified"]
    assert len(case.physics.frame_calls) == at_drift[0][1]
    assert case.physics.resets == at_drift[0][2]
    assert canonical(env.reader()) == at_drift[0][0]
    assert [call[0] for call in case.physics.native_calls] == ([] if operation == "INVALIDATE" else [operation])


@pytest.mark.parametrize("before,after", PAYLOADS)
def test_native_failure_keeps_primary_and_refuses_compensation_after_typed_drift(exact_case, before, after):
    env, case = exact_case, exact_case.case
    env.owner["payload"] = deepcopy(before)
    params = case.proposal()
    original = canonical(env.reader())
    at_drift = []

    def drift():
        env.owner["payload"] = deepcopy(after)
        at_drift.append((canonical(env.reader()), len(case.physics.frame_calls)))

    case.physics.after_native, case.physics.fail_native = drift, True
    error, result = observed_call(env, params)
    assert result is None and error is not None
    assert at_drift and at_drift[0][0] != original
    assert error.code == "OPERATION_FAILED" and error.context["primary_error_type"] == "RuntimeError"
    assert isinstance(error.__cause__, RuntimeError)
    assert str(error.__cause__) == "native bake failed after partial work"
    assert not error.context["frame_recovery"]["verified"]
    assert not error.context["frame_recovery"]["attempted"]
    assert len(case.physics.frame_calls) == at_drift[0][1]
    assert canonical(env.reader()) == at_drift[0][0]
    assert case.cache.is_baked
    assert [call[0] for call in case.physics.native_calls] == ["BAKE"]  # No implicit FREE.


def test_normalized_owned_subframe_cannot_claim_exact_caller_time_restoration(exact_case, monkeypatch):
    env, case = exact_case, exact_case.case
    case.scene.frame_subframe = -0.
    assert math.copysign(1., case.scene.frame_subframe) == -1.
    original = case.scene.frame_set

    def normalized(frame, *, subframe=0.):
        original(frame, subframe=0. if subframe == 0. else subframe)

    monkeypatch.setattr(case.scene, "frame_set", normalized)
    error, result = observed_call(env, case.proposal())
    assert math.copysign(1., case.scene.frame_subframe) == 1.  # Model really normalized the returned value.
    assert error is not None, result
    assert error.code == "OPERATION_FAILED"
    assert error.context["frame_recovery"]["attempted"]
    assert not error.context["frame_recovery"]["verified"]
    assert case.cache.is_baked and [call[0] for call in case.physics.native_calls] == ["BAKE"]
