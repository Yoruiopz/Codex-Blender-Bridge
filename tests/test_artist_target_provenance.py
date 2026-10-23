"""Immutable target expectations bind only to current finalized step receipts."""
from __future__ import annotations

import importlib
import json
import math
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace as NS

import pytest
from test_artist_loop import loop, preview, rna_env  # noqa: F401
from test_artist_step_evidence import journal  # noqa: F401


@pytest.fixture
def target_journal(journal, addon_package, monkeypatch):  # noqa: F811
    helper = importlib.import_module(f"{addon_package}.artist_target_intent")
    # Native numeric prediction/descriptor behavior has separate helper tests.
    # This fixture gives provenance a pre-existing immutable qualified intent.
    channels = (("location", (1., 2., 3.)), ("rotation_mode", "XYZ"),
                ("rotation_euler", (0., 0., 0.)), ("rotation_quaternion", (1., 0., 0., 0.)),
                ("rotation_axis_angle", (0., 0., 1., 0.)), ("scale", (1., 1., 1.)))
    bits = (("location", ("0000803f", "00000040", "00004040")), ("rotation_mode", "XYZ"),
            ("rotation_euler", ("00000000",) * 3),
            ("rotation_quaternion", ("0000803f", "00000000", "00000000", "00000000")),
            ("rotation_axis_angle", ("00000000", "00000000", "0000803f", "00000000")),
            ("scale", ("0000803f",) * 3))
    intent = helper.TargetIntent(availability="available", reason=None, object_name=journal.env.obj.name,
        session_uid=1, pointer=123, before_channels=channels, expected_channels=channels,
        before_bits=bits, expected_bits=bits, requested_fields=("location",))
    monkeypatch.setattr(journal.env.loop, "capture_intent", lambda *_args: intent)

    def params():
        receipt = journal.store.step_receipts[-1]
        return {"step_id": "revise", "receipt_id": receipt["receipt_id"],
                "expected_revision": journal.store.plan["revision"]}

    def enter(arguments=None):
        arguments = params() if arguments is None else arguments
        request = NS(method="task.plan.verify_transform", params=arguments)
        journal.evidence.capture_call(journal.env.context, request)
        entry = journal.evidence.require_target_verify_entry(journal.env.context, arguments)
        return entry, arguments

    def append(entry, evidence, *, before_attach=lambda: None):
        return journal.evidence.append_target_observation(journal.env.context, entry, evidence,
                                                         before_attach=before_attach)

    return NS(**vars(journal), helper=helper, intent=intent, params=params, enter=enter, append=append)


def test_preview_and_final_receipt_keep_independent_immutable_intent(target_journal):
    j = target_journal
    shown = preview(j.env, step_id="revise")
    assert shown["target_expectation"]["availability"] == "available"
    assert shown["target_expectation"]["expected_float32_le"]["location"] == ["0000803f", "00000040", "00004040"]
    assert j.apply(shown).ok
    receipt = j.store.step_receipts[-1]
    assert receipt["target_intent"] is j.intent
    assert receipt["completed_mutation_revision"] == j.store.evidence_revision
    assert receipt["runtime_id"] == j.store.runtime_id and receipt["evidence_epoch"] == j.store.evidence_epoch
    assert receipt["step_description"] == j.store.plan["steps"][0]["description"]
    inspection = j.inspect()
    assert inspection["scope"] == "protected_objects_only"
    assert inspection["target_observation_scope"] == "authored_core_transform_channels"
    assert "target_intent" not in inspection["receipts"][0]
    json.dumps(inspection, allow_nan=False)
    inspection["receipts"][0]["target_expectation"]["expected"]["location"][0] = 99.
    assert dict(j.intent.expected_channels)["location"][0] == 1.
    with pytest.raises(FrozenInstanceError):
        j.intent.object_name = "Other"


def test_unavailable_expectation_is_visible_before_apply_and_preserves_apply(target_journal, monkeypatch):
    j = target_journal
    unavailable = j.helper.TargetIntent(reason="rotation_mode_conversion")
    monkeypatch.setattr(j.env.loop, "capture_intent", lambda *_args: unavailable)
    shown = preview(j.env, step_id="revise")
    assert shown["target_expectation"]["availability"] == "unavailable"
    assert shown["target_expectation"]["reason"] == "rotation_mode_conversion"
    assert j.apply(shown).ok
    entry, _params = j.enter()
    assert entry.target_intent is unavailable
    assert j.env.obj.location == (1., 2., 3.)


def test_apply_provider_cannot_replace_retained_intent_or_rewrite_failed_receipt(target_journal):
    j = target_journal
    shown = preview(j.env, step_id="revise")
    fired = []

    def provider():
        if not fired:
            fired.append(True)
            j.store.previews[shown["preview_id"]]["target_intent"] = replace(j.intent, object_name="Other")

    j.env.provider[0] = provider
    response = j.apply(shown)
    assert not response.ok and j.env.obj.location == (0., 0., 0.)
    assert j.store.step_receipts[-1]["target_intent"] is j.intent
    assert j.store.step_receipts[-1]["success"] is False


def test_verify_entry_does_not_create_missing_store_or_read_native_data(target_journal):
    j = target_journal
    context = NS(state=NS())
    request = NS(method="task.plan.verify_transform", params={"step_id": "revise",
        "receipt_id": "step_receipt_" + "a" * 32, "expected_revision": 1})
    assert j.evidence.capture_call(context, request) is None
    assert not hasattr(context.state, "_artist_task_plans")
    with pytest.raises(j.env.module.BridgeError):
        j.evidence.require_target_verify_entry(context, request.params)
    assert not hasattr(context.state, "_artist_task_plans")


def test_status_note_correction_before_invocation_uses_current_revision(target_journal):
    j = target_journal
    assert j.apply().ok
    j.env.plans.update_plan(j.env.context, {"step_id": "revise", "note": "Compare the intended result",
                                         "status": "in_progress", "expected_revision": 1})
    entry, params = j.enter()
    assert params["expected_revision"] == entry.requested_revision == 2
    assert entry.receipt["completed_revision"] == 1
    j.evidence.check_target_verify_entry(j.env.context, entry, params)


@pytest.mark.parametrize("fault", [
    "store", "runtime_id", "epoch", "generation", "writer", "new_receipt", "eviction", "receipt_identity",
    "operation", "intent", "bool_success", "bool_revision", "bool_generation", "plan_revision", "plan_goal", "step_description",
    "plan_identity", "step_status", "context_slot",
])
def test_captured_verify_entry_rejects_provider_time_provenance_drift(target_journal, fault):
    j = target_journal
    assert j.apply().ok
    entry, params = j.enter()
    if fault == "store":
        j.env.context.state._artist_task_plans = j.env.data.TaskPlanStore()
    elif fault == "runtime_id":
        j.store.runtime_id = "another_runtime"
    elif fault == "epoch":
        j.store.evidence_epoch += 1
    elif fault == "generation":
        j.store.invalidate_handles()
    elif fault == "writer":
        j.store.evidence_revision += 1
    elif fault == "new_receipt":
        newer = dict(entry.receipt, receipt_id="step_receipt_" + "b" * 32, operation_id="op_new")
        j.store.step_receipts.append(newer)
    elif fault == "eviction":
        j.store.step_receipts.clear()
    elif fault == "receipt_identity":
        j.store.step_receipts[-1] = dict(entry.receipt)
    elif fault == "operation":
        entry.receipt["operation_id"] = "op_other"
    elif fault == "intent":
        entry.receipt["target_intent"] = replace(j.intent)
    elif fault == "bool_success":
        entry.receipt["success"] = 1
    elif fault == "bool_revision":
        entry.receipt["completed_mutation_revision"] = True
    elif fault == "bool_generation":
        assert entry.receipt["generation"] == 1
        entry.receipt["generation"] = True
    elif fault == "plan_revision":
        j.store.plan["revision"] += 1
    elif fault == "plan_goal":
        j.store.plan["goal"] = "Another brief at the same revision"
    elif fault == "step_description":
        j.store.plan["steps"][0]["description"] = "A different step with the same ID"
    elif fault == "plan_identity":
        j.store.plan = deepcopy(j.store.plan)
    elif fault == "step_status":
        j.store.plan["steps"][0]["status"] = "completed"
    else:
        j.env.context.artist_step_entry = None
    with pytest.raises(j.env.module.BridgeError):
        j.evidence.check_target_verify_entry(j.env.context, entry, params)
    assert entry.receipt["target_observation"] is None


@pytest.mark.parametrize("field,value", [("step_id", "other"), ("receipt_id", "step_receipt_" + "c" * 32),
                                         ("expected_revision", True), ("expected_revision", 2)])
def test_verify_entry_keeps_original_parameter_values(target_journal, field, value):
    j = target_journal
    assert j.apply().ok
    entry, params = j.enter()
    params[field] = value
    with pytest.raises(j.env.module.BridgeError):
        j.evidence.check_target_verify_entry(j.env.context, entry, params)


@pytest.mark.parametrize("fault", ["failed", "older", "generation", "writer", "description"])
def test_noncurrent_or_failed_receipts_cannot_become_fresh_expectations(target_journal, fault):
    j = target_journal
    if fault == "failed":
        j.env.grants["TRANSFORM_OBJECTS"] = False
        assert not j.apply().ok
    else:
        assert j.apply().ok
    params = j.params()
    if fault == "older":
        assert j.apply(preview(j.env, step_id="revise", location=[2., 3., 4.])).ok
    elif fault == "generation":
        j.store.invalidate_handles()
    elif fault == "writer":
        j.store.evidence_revision += 1
    elif fault == "description":
        j.store.plan["steps"][0]["description"] = "Reused ID, changed brief"
    assert j.evidence.capture_call(j.env.context, NS(method="task.plan.verify_transform", params=params)) is None
    with pytest.raises(j.env.module.BridgeError):
        j.evidence.require_target_verify_entry(j.env.context, params)


@pytest.mark.parametrize("fault", ["applying", "mutator", "job", "execution"])
def test_verification_refuses_a_live_writer_or_job(target_journal, fault):
    j = target_journal
    assert j.apply().ok
    entry, params = j.enter()
    if fault == "applying":
        j.store.applying_preview = {}
    elif fault == "mutator":
        j.store.executing_mutators = 1
    elif fault == "job":
        j.env.context.jobs = NS(active=object())
    else:
        j.env.context.state.begin_execution("fixture.writer")
    with pytest.raises(j.env.module.BridgeError, match="writer or job"):
        j.evidence.check_target_verify_entry(j.env.context, entry, params)


def test_nested_registered_writer_invalidates_prior_verification(target_journal):
    j = target_journal
    assert j.apply().ok
    entry, params = j.enter()
    registry = j.env.context.registry
    entered = []

    def writer(context, _params):
        entered.append(registry.executing_mutators)
        with pytest.raises(j.env.module.BridgeError):
            j.evidence.check_target_verify_entry(context, entry, params)
        return {"blocked_prior_observation": True}

    registry.register("fixture.observe_inside_writer", writer, modifies=True, automatic_checkpoint=False)
    result = registry.dispatch("fixture.observe_inside_writer", {}, j.env.context)
    assert result["blocked_prior_observation"] and entered == [1]
    assert entry.receipt["target_observation"] is None


def test_target_observation_needs_no_protected_baseline_and_is_defensive(target_journal):
    j = target_journal
    assert j.apply().ok
    j.store.baseline = None
    entry, _params = j.enter()
    history, checkpoints = j.env.context.state.history(), list(j.checkpoints)
    evidence = {"status": "channels_match", "expected_float32_le": {"location": ["0000803f"]},
                "observed_float32_le": {"location": ["0000803f"]}, "differences": []}
    observation = j.append(entry, evidence)
    assert observation["receipt_id"] == entry.receipt_id and observation["operation_id"] == entry.operation_id
    assert observation["observation_id"].startswith("target_observation_")
    assert observation["validity"] == "recorded" and not observation["current_scene_verified"]
    assert not observation["user_goal_verified"] and j.store.plan["steps"][0]["status"] == "pending"
    observation["expected_float32_le"]["location"][0] = "forged"
    evidence["differences"].append({"field": "forged"})
    shown = j.inspect()["receipts"][0]
    assert shown["protected_observation"] is None
    assert shown["target_observation"]["expected_float32_le"]["location"] == ["0000803f"]
    assert shown["target_observation"]["differences"] == []
    assert j.env.context.state.history() == history and j.checkpoints == checkpoints
    json.dumps(j.inspect(), allow_nan=False)


@pytest.mark.parametrize("fault", ["writer", "generation", "epoch"])
def test_target_observations_are_recorded_facts_and_become_stale(target_journal, fault):
    j = target_journal
    assert j.apply().ok
    entry, _params = j.enter()
    j.append(entry, {"status": "channels_differ", "differences": []})
    if fault == "writer":
        j.store.evidence_revision += 1
    elif fault == "generation":
        j.store.invalidate_handles()
    else:
        j.store.evidence_epoch += 1
    observed = j.inspect()["receipts"][0]["target_observation"]
    assert observed["status"] == "channels_differ" and observed["validity"] == "stale"
    assert not observed["current_scene_verified"] and not observed["user_goal_verified"]


def test_mcp_reconnect_keeps_receipt_expectations_without_creating_new_evidence(target_journal):
    j = target_journal
    assert j.apply().ok
    entry, params = j.enter()
    j.env.context.state.client_connected()
    j.env.context.state.client_disconnected()
    j.evidence.check_target_verify_entry(j.env.context, entry, params)
    assert j.inspect()["receipts"][0]["target_observation"] is None


def test_final_canonical_guard_runs_after_preparation_and_before_attachment(target_journal):
    j = target_journal
    assert j.apply().ok
    entry, _params = j.enter()
    calls = []

    def canceled():
        calls.append("final")
        assert entry.receipt["target_observation"] is None
        raise j.env.module.BridgeError("TIMEOUT", "Caller canceled in final safe point")

    with pytest.raises(j.env.module.BridgeError, match="final safe point"):
        j.append(entry, {"status": "channels_match"}, before_attach=canceled)
    assert calls == ["final"] and entry.receipt["target_observation"] is None


@pytest.mark.parametrize("value", [math.nan, math.inf, 1 << 129, "x" * 2049, [[[[[[[[[[0]]]]]]]]]]])
def test_unbounded_or_nonfinite_observations_do_not_attach(target_journal, value):
    j = target_journal
    assert j.apply().ok
    entry, _params = j.enter()
    with pytest.raises(j.env.module.BridgeError):
        j.append(entry, {"status": "channels_match", "value": value})
    assert entry.receipt["target_observation"] is None


def test_observation_copy_does_not_invoke_custom_adapters(target_journal):
    j = target_journal
    assert j.apply().ok
    entry, _params = j.enter()
    called = []

    class Adapter:
        def __deepcopy__(self, _memo):
            called.append("copy")
            raise AssertionError("No custom copy callback is allowed")

    with pytest.raises(j.env.module.BridgeError, match="without adapters"):
        j.append(entry, {"status": "channels_match", "adapter": Adapter()})
    assert called == [] and entry.receipt["target_observation"] is None


@pytest.mark.parametrize("container", ["params", "plan", "step", "receipt", "receipt_origin", "observation"])
def test_provenance_rejects_custom_dictionary_keys_before_lookup(target_journal, container):
    j = target_journal
    assert j.apply().ok
    entry, params = j.enter()
    called = []
    if container == "params":
        original, field = params, "step_id"
    elif container == "plan":
        original, field = j.store.plan, "goal"
    elif container == "step":
        original, field = j.store.plan["steps"][0], "description"
    elif container in {"receipt", "receipt_origin"}:
        original, field = entry.receipt, "step_id"
    else:
        original, field = {"status": "channels_match"}, "status"

    class Key:
        def __hash__(self):
            return hash(field)

        def __eq__(self, other):
            called.append(other)
            return False

    malformed = dict(original)
    value = malformed.pop(field)
    malformed[Key()] = value
    called.clear()
    if container == "receipt_origin":
        with pytest.raises(j.env.module.BridgeError):
            j.evidence._receipt_origin(malformed)
    elif container == "observation":
        with pytest.raises(j.env.module.BridgeError):
            j.append(entry, malformed)
    else:
        original.clear()
        original.update(malformed)
        with pytest.raises(j.env.module.BridgeError):
            j.evidence.check_target_verify_entry(j.env.context, entry, params)
        assert j.evidence.capture_call(j.env.context, NS(method="task.plan.verify_transform", params=params)) is None
    assert called == [] and entry.receipt["target_observation"] is None


def test_terminal_hook_stores_intent_without_public_serialization(target_journal, monkeypatch):
    j = target_journal

    def forbidden(*_args):
        raise AssertionError("Terminal bookkeeping must not serialize or inspect native state")

    monkeypatch.setattr(j.evidence, "public_intent", forbidden)
    assert j.apply().ok
    assert j.store.step_receipts[-1]["target_intent"] is j.intent
