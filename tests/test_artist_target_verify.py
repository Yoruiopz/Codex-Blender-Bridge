"""Handler/lifecycle integration; native channel reading has separate tests."""

from __future__ import annotations

import copy
import importlib
import json
import struct
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from test_artist_loop import loop, preview, rna_env  # noqa: F401
from test_artist_step_evidence import journal  # noqa: F401


def bits(channels):
    return tuple((field, value if type(value) is str else tuple(struct.pack("<f", item).hex() for item in value))
                 for field, value in channels.items())


@pytest.fixture
def target_verify(journal, addon_package, monkeypatch):  # noqa: F811
    env = journal.env
    helper = importlib.import_module(f"{addon_package}.artist_target_intent")
    module = importlib.import_module(f"{addon_package}.tools.artist_target_verify")
    channels = {"location": (0., 0., 0.), "rotation_mode": "XYZ", "rotation_euler": (0., 0., 0.),
                "rotation_quaternion": (1., 0., 0., 0.), "rotation_axis_angle": (0., 0., 1., 0.), "scale": (1., 1., 1.)}
    expected = {**channels, "location": (1., 2., 3.)}
    intent = helper.TargetIntent(availability="available", reason=None, object_name=env.obj.name,
        session_uid=1, pointer=1, before_channels=tuple(channels.items()), expected_channels=tuple(expected.items()),
        before_bits=bits(channels), expected_bits=bits(expected), requested_fields=("location",))
    bound = preview(env, step_id="revise")
    # This adapter fixture has no native RNA identity/schema. Supply immutable
    # qualified test intent before the actual executor's apply-entry snapshot.
    journal.store.previews[bound["preview_id"]]["target_intent"] = intent
    applied = journal.apply(bound)
    assert applied.ok, applied.error
    receipt = journal.store.step_receipts[-1]
    public = helper.public_intent(intent)
    observed = {"status": "observed", "identity": public["identity"],
                "channels": copy.deepcopy(public["expected"]), "float32_le": copy.deepcopy(public["expected_float32_le"])}
    reads, hooks = [], []

    def reader(_bpy, captured):
        reads.append(captured)
        for hook in hooks:
            hook()
        return copy.deepcopy(observed)

    monkeypatch.setattr(helper, "read_target", reader)
    monkeypatch.setattr(module, "require_blender", lambda: object())
    parameters = {"step_id": "revise", "receipt_id": applied.result["step_receipt_id"], "expected_revision": 1}

    def request(**overrides):
        return journal.protocol.Request(id="verify-target", method=module.METHOD, params={**parameters, **overrides})

    def verify(**overrides):
        return journal.executor.execute_request(request(**overrides))

    return NS(journal=journal, env=env, helper=helper, module=module, intent=intent, receipt=receipt,
              observed=observed, reads=reads, hooks=hooks, parameters=parameters, request=request, verify=verify)


def test_matches_attach_bounded_historical_evidence_without_native_history_or_completion(target_verify):
    case = target_verify
    before = len(case.journal.checkpoints), case.env.context.state.history(50), case.journal.store.evidence_revision
    response = case.verify()
    assert response.ok, response.error
    result = response.result
    observation = result["target_observation"]
    assert observation["status"] == "channels_match" and not observation["differences"]
    assert result["operation_id"] == case.receipt["operation_id"]
    assert result["receipt_id"] == case.receipt["receipt_id"]
    assert not result["user_goal_verified"] and not result["current_scene_verified"]
    assert len(case.reads) == 1 and case.reads[0] is case.intent
    assert (len(case.journal.checkpoints), case.env.context.state.history(50), case.journal.store.evidence_revision) == before
    inspection = case.journal.inspect()
    assert inspection["scope"] == "protected_objects_only"  # Preserve the legacy field.
    retained = inspection["receipts"][-1]
    assert retained["target_observation"]["validity"] == "recorded"
    assert not retained["target_observation"]["current_scene_verified"]
    assert retained["protected_observation"] is None
    assert retained["target_expectation"]["availability"] == "available"
    assert case.journal.store.plan["steps"][0]["status"] == "pending"
    json.dumps(inspection, allow_nan=False)


def test_manual_channel_difference_never_becomes_new_expectation(target_verify):
    case = target_verify
    case.observed["channels"]["location"][0] = 9.
    case.observed["float32_le"]["location"][0] = struct.pack("<f", 9.).hex()
    response = case.verify()
    assert response.ok, response.error
    observation = response.result["target_observation"]
    assert observation["status"] == "channels_differ"
    assert observation["expected"]["location"] == [1., 2., 3.]
    assert observation["observed"]["location"] == [9., 2., 3.]
    assert observation["differences"][0]["different_components"] == [0]
    assert case.receipt["target_intent"] is case.intent


@pytest.mark.parametrize("status,expected", [("missing", "target_missing"), ("replaced", "target_replaced")])
def test_missing_and_replaced_statuses_do_not_claim_channel_coverage(target_verify, status, expected):
    case = target_verify
    case.observed.clear()
    case.observed.update(status=status, identity=None if status == "missing" else {"object_name": case.intent.object_name, "session_uid": 2, "pointer": 2})
    response = case.verify()
    assert response.ok, response.error
    observation = response.result["target_observation"]
    assert observation["status"] == expected and observation["compared_fields"] == []
    assert not observation["comparison_complete"] and observation["observed"] is None


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_current_read_only_verification_remains_available_under_pause_or_stop(target_verify, flag):
    case = target_verify
    getattr(case.env.context.state, "set_" + flag)(True)
    response = case.verify()
    assert response.ok, response.error
    assert response.result["target_observation"]["status"] == "channels_match"


def test_permission_denial_precedes_target_reader(target_verify):
    case = target_verify
    case.env.grants["INSPECT_SCENE"] = False
    response = case.verify()
    assert not response.ok and response.error["code"] == "PERMISSION_DENIED"
    assert case.reads == [] and case.receipt["target_observation"] is None


@pytest.mark.parametrize("cause,code", [
    ("permission", "PERMISSION_DENIED"),
    ("stale_receipt", "INVALID_ARGUMENT"),
    ("unsupported", "NOT_IMPLEMENTED"),
])
def test_refused_verification_retains_only_existing_failed_call_audit(target_verify, cause, code):
    case = target_verify
    if cause == "permission":
        case.env.grants["INSPECT_SCENE"] = False
    elif cause == "stale_receipt":
        case.journal.store.evidence_revision += 1
    else:
        case.receipt["target_intent"] = replace(case.intent, availability="unavailable", reason="unqualified")
    state = case.env.context.state
    previous = state.history(50)
    checkpoint_count = len(case.journal.checkpoints)
    revision = case.journal.store.evidence_revision
    response = case.verify()
    assert not response.ok and response.error["code"] == code
    history = state.history(50)
    assert len(history) == len(previous) + 1 and history[1:] == previous
    audit = history[0]
    assert audit["tool"] == case.module.METHOD and audit["success"] is False
    assert audit["error_code"] == code and audit["affected_objects"] == []
    for field in ("external_effects", "recovery_evidence", "job_evidence"):
        assert audit.get(field) is None
    assert len(case.journal.checkpoints) == checkpoint_count
    assert case.journal.store.evidence_revision == revision
    assert case.reads == [] and case.receipt["target_observation"] is None


def test_unqualified_expectation_refuses_without_target_read(target_verify):
    case = target_verify
    case.receipt["target_intent"] = replace(case.intent, availability="unavailable", reason="rotation_mode_conversion_unavailable")
    response = case.verify()
    assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
    assert response.error["context"]["verification_available"] is False
    assert response.error["context"]["target_channels_read"] is False
    assert case.reads == [] and case.receipt["target_observation"] is None


def test_entry_provider_revision_change_is_rejected_before_reader(target_verify):
    case = target_verify
    changed = []

    def provider():
        if not changed:
            changed.append(True)
            case.journal.store.plan["revision"] += 1

    case.env.provider[0] = provider
    response = case.verify()
    assert changed and not response.ok and response.error["code"] == "INVALID_ARGUMENT"
    assert case.reads == [] and case.receipt["target_observation"] is None


def test_provenance_drift_during_read_does_not_attach_observation(target_verify):
    case = target_verify
    case.hooks.append(lambda: setattr(case.journal.store, "evidence_revision", case.journal.store.evidence_revision + 1))
    response = case.verify()
    assert not response.ok and response.error["code"] == "INVALID_ARGUMENT"
    assert len(case.reads) == 1 and case.receipt["target_observation"] is None


def test_cancellation_after_static_read_does_not_attach_observation(target_verify, addon_package):
    case = target_verify
    queue = importlib.import_module(f"{addon_package}.command_queue")
    errors = importlib.import_module(f"{addon_package}.errors")
    request = case.request()
    queued = queue.QueuedRequest(request)
    assert queued.try_start()
    case.hooks.append(lambda: queued.cancel_pending(errors.BridgeError("TIMEOUT", "Canceled after read")))
    response = case.journal.executor.execute_request(request, check_cancelled=queued.check_active)
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert len(case.reads) == 1 and case.receipt["target_observation"] is None


def test_disconnect_after_static_read_does_not_attach_observation(target_verify, addon_package):
    case = target_verify
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    owner = lifecycle.ConnectionLifetime()
    lifetime = lifecycle.RequestLifetime(connection=owner)
    lifetime.delivered.set()
    request = replace(case.request(), _lifecycle=lifetime)
    case.hooks.append(owner.disconnected.set)
    response = case.journal.executor.execute_request(request)
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert response.error["context"]["connection_disconnected"]
    assert len(case.reads) == 1 and case.receipt["target_observation"] is None


def test_cancellation_during_observation_copy_prevents_final_attachment(target_verify, addon_package, monkeypatch):
    case = target_verify
    queue = importlib.import_module(f"{addon_package}.command_queue")
    errors = importlib.import_module(f"{addon_package}.errors")
    evidence = importlib.import_module(f"{addon_package}.artist_step_evidence")
    request = case.request()
    queued = queue.QueuedRequest(request)
    assert queued.try_start()
    original = evidence._observation_copy
    copied = []

    def copy_then_cancel(value):
        result = original(value)
        copied.append(True)
        queued.cancel_pending(errors.BridgeError("TIMEOUT", "Canceled during observation preparation"))
        return result

    monkeypatch.setattr(evidence, "_observation_copy", copy_then_cancel)
    response = case.journal.executor.execute_request(request, check_cancelled=queued.check_active)
    assert copied and not response.ok and response.error["code"] == "TIMEOUT"
    assert len(case.reads) == 1 and case.receipt["target_observation"] is None


@pytest.mark.parametrize("override", [
    {"step_id": "x y"}, {"step_id": "x" * 65}, {"receipt_id": "step_receipt_BAD"},
    {"expected_revision": True}, {"expected_revision": 1.}, {"expected_revision": 0},
    {"expected_revision": 1_000_000_001}, {"unknown": "field"},
])
def test_invalid_wire_arguments_never_read_target(target_verify, override):
    case = target_verify
    response = case.verify(**override)
    assert not response.ok and response.error["code"] == "INVALID_ARGUMENT"
    assert case.reads == [] and case.receipt["target_observation"] is None
