"""Actual executor receipts remain runtime provenance, never completion claims."""
from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from test_artist_loop import arm, loop, preview, rna_env  # noqa: F401

from mcp_server.tools.task_plan import TaskPlanTools


@pytest.fixture
def journal(loop, addon_package):  # noqa: F811
    executor_module = importlib.import_module(f"{addon_package}.executor")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    evidence = importlib.import_module(f"{addon_package}.artist_step_evidence")
    checkpoints = []
    executor = executor_module.MainThreadExecutor(command_queue=queue.CommandQueue(), registry=loop.context.registry,
        state=loop.context.state, permissions=loop.context.permissions,
        checkpoints=NS(before_modification=lambda _, **_kw: checkpoints.append("before") or True,
                       after_modification=lambda _, **_kw: checkpoints.append("after") or True))
    retained = {"baseline"}
    fake_evidence = NS(has_snapshot=lambda identifier: identifier in retained,
                       compare=lambda *_args: {"status": "unchanged_within_scope", "coverage_complete": True})
    executor.evidence = loop.context.evidence = fake_evidence
    store = loop.data.get_task_plans(loop.context.state)
    store.baseline = {"snapshot_id": "baseline", "captured_revision": 1, "coverage_complete": True, "fields": ["transforms"]}

    def apply(result=None, **overrides):
        result = result or preview(loop, step_id="revise")
        return executor.execute_request(protocol.Request(id="untrusted-client-id", method="task.plan.apply_preview",
            params={"preview_id": result["preview_id"], "expected_revision": store.require_plan()["revision"], **overrides}))

    def inspect():
        return loop.plans.inspect_plan(loop.context, {})["step_evidence"]

    def compare():
        return loop.plans.compare_plan(loop.context, {"step_id": "revise", "expected_revision": store.require_plan()["revision"]})

    return NS(env=loop, store=store, executor=executor, protocol=protocol, evidence=evidence,
              checkpoints=checkpoints, retained=retained, apply=apply, inspect=inspect, compare=compare)


def test_success_receipt_uses_final_outer_record_and_does_not_complete_step(journal):
    response = journal.apply()
    assert response.ok, response.error
    receipt = journal.inspect()["receipts"][0]
    record = journal.env.context.state.history()[0]
    assert receipt["operation_id"] == record["operation_id"] == response.result["operation"]["operation_id"]
    assert receipt["operation_id"] != "untrusted-client-id"
    assert receipt["receipt_id"] == response.result["step_receipt_id"]
    assert receipt["method"] == "task.plan.apply_preview" and receipt["outcome"] == "completed"
    assert journal.checkpoints == ["before", "after"]
    assert receipt["undo_boundary_created"] and receipt["undo_boundary_finalized"]
    assert receipt["protected_observation"] is None
    assert journal.store.plan["steps"][0]["status"] == "pending"
    assert not journal.inspect()["user_goal_verified"]


@pytest.mark.parametrize("denied", [False, True])
def test_history_failure_marks_existing_step_journal_incomplete_without_fabricating_receipt(journal, monkeypatch, denied):
    attempts = []

    def broken_history(**_kwargs):
        attempts.append(True)
        raise RuntimeError("modeled step history failure")

    if denied:
        journal.env.grants["TRANSFORM_OBJECTS"] = False
    monkeypatch.setattr(journal.env.context.state, "record_operation", broken_history)
    response = journal.apply()
    assert not response.ok
    assert response.error["code"] == ("PERMISSION_DENIED" if denied else "OPERATION_FAILED")
    assert response.error["context"]["history_outcome_unknown"]
    assert attempts == [True]
    assert journal.inspect()["incomplete"] is True and journal.inspect()["receipts"] == []
    assert journal.env.data.get_task_plans(journal.env.context.state) is journal.store
    assert journal.checkpoints == ([] if denied else ["before", "after"])
    assert journal.store.plan["steps"][0]["status"] == "pending"


@pytest.mark.parametrize("fault", ["denial", "partial", "generic", "after_checkpoint"])
def test_failure_receipt_uses_actual_final_error_record(journal, fault):
    env = journal.env
    result = preview(env, step_id="revise", scale=[2., 2., 2.])
    if fault == "denial":
        env.grants["TRANSFORM_OBJECTS"] = False
    elif fault == "partial":
        env.provider[0] = lambda: env.grants.update(TRANSFORM_OBJECTS=False) if env.obj.location == (1., 2., 3.) else None
    elif fault == "generic":
        spec = env.context.registry.get("task.plan.apply_preview")
        def fail(*_args):
            raise RuntimeError("injected native wrapper failure")
        env.context.registry._tools[spec.name] = replace(spec, handler=fail)
    else:
        def fail(*_args, **_kw):
            raise env.module.BridgeError("OPERATION_FAILED", "injected finalization failure")
        journal.executor.checkpoints.after_modification = fail
    response = journal.apply(result)
    assert not response.ok
    receipt = journal.inspect()["receipts"][0]
    record = env.context.state.history()[0]
    assert receipt["operation_id"] == record["operation_id"] == response.error["context"]["operation_id"]
    assert receipt["receipt_id"] == response.error["context"]["step_receipt_id"]
    assert receipt["error_code"] == record["error_code"] == response.error["code"]
    assert receipt["outcome"] == ("rejected" if fault == "denial" else "failed")
    assert receipt["undo_boundary_created"] is (fault != "denial")
    assert receipt["undo_boundary_finalized"] is (fault in {"partial", "generic"})
    if fault == "partial":
        assert receipt["possible_mutation"] is True and env.obj.location == (1., 2., 3.)
    assert env.context.state.history()[0]["success"] is False
    assert journal.store.plan["steps"][0]["status"] == "pending"


def test_preview_binding_cannot_be_retargeted_by_entry_provider(journal):
    env = journal.env
    bound = preview(env, step_id="revise")
    unbound = preview(env)
    fired = []
    def provider():
        if not fired:
            fired.append(True)
            journal.store.previews[bound["preview_id"]] = journal.store.previews[unbound["preview_id"]]
    env.provider[0] = provider
    response = journal.apply(bound)
    assert not response.ok and "consumption ownership" in response.error["message"]
    assert env.obj.location == (0., 0., 0.)
    receipt = journal.inspect()["receipts"][0]
    assert receipt["preview_id"] == bound["preview_id"] and receipt["step_id"] == "revise"


@pytest.mark.parametrize("fault", ["replace", "reset", "clear", "load"])
def test_prior_call_cannot_attach_to_reused_plan_and_step_ids(journal, fault):
    env = journal.env
    bound = preview(env, step_id="revise")
    original = json.loads(env.data.encode_saved(journal.store.plan))
    fired = []
    def provider():
        if fired:
            return
        fired.append(True)
        if fault == "reset":
            env.context.state.reset()
        elif fault == "clear":
            journal.store.clear()
        elif fault == "replace":
            journal.store.replace({key: original[key] for key in ("goal", "steps", "protected_objects")}, journal.store.scope, 1)
        else:
            journal.store.reset_step_evidence()
            journal.store.invalidate_handles()
        # Reused external IDs must not restore runtime provenance.
        current = env.data.get_task_plans(env.context.state)
        current.plan = original
    env.provider[0] = provider
    response = journal.apply(bound)
    assert not response.ok and env.obj.location == (0., 0., 0.)
    assert not env.data.get_task_plans(env.context.state).inspect()["step_evidence"]["receipts"]


def test_unbound_and_direct_registry_applications_do_not_fabricate_outer_receipts(journal):
    assert journal.apply(preview(journal.env)).ok
    assert not journal.inspect()["receipts"]
    bound = preview(journal.env, step_id="revise", location=[3., 2., 1.])
    journal.env.context.registry.dispatch("task.plan.apply_preview",
        {"preview_id": bound["preview_id"], "expected_revision": 1}, journal.env.context)
    assert not journal.inspect()["receipts"]


def test_correction_preserves_original_association_and_requires_current_revision(journal):
    result = preview(journal.env, step_id="revise")
    journal.env.plans.update_plan(journal.env.context, {"step_id": "revise", "note": "Move right", "expected_revision": 1})
    response = journal.apply(result)
    assert response.ok, response.error
    receipt = journal.inspect()["receipts"][0]
    assert (receipt["preview_revision"], receipt["requested_revision"], receipt["completed_revision"]) == (1, 2, 2)


def test_observations_are_explicit_scoped_and_stale_after_history_move(journal):
    assert journal.apply().ok
    journal.env.plans.compare_plan(journal.env.context, {})
    assert journal.inspect()["receipts"][0]["protected_observation"] is None
    result = journal.compare()
    observation = result["step_evidence"]["receipts"][0]["protected_observation"]
    assert observation["scope"] == "protected_objects_only" and observation["validity"] == "recorded"
    assert not observation["user_goal_verified"] and not observation["current_scene_verified"]
    journal.env.context.state.client_connected()
    journal.env.context.state.client_disconnected()
    assert journal.inspect()["receipts"][0]["protected_observation"] == observation
    journal.store.invalidate_handles()
    receipt = journal.inspect()["receipts"][0]
    assert receipt["history_state"] == "historical_after_generation_change"
    assert receipt["protected_observation"]["validity"] == "stale"
    journal.compare()
    assert journal.inspect()["receipts"][0]["protected_observation"]["validity"] == "recorded"
    assert journal.inspect()["receipts"][0]["history_state"] == "historical_after_generation_change"
    journal.retained.clear()
    assert journal.inspect()["receipts"][0]["protected_observation"]["validity"] == "unknown"


@pytest.mark.parametrize("fault", ["mutation", "replace", "baseline", "denial", "cancel"])
def test_compare_does_not_attach_across_callback_changes(journal, fault):
    assert journal.apply().ok
    def compare(*_args):
        if fault == "mutation":
            journal.store.evidence_revision += 1
        elif fault == "replace":
            journal.store.reset_step_evidence()
        elif fault == "baseline":
            journal.store.baseline = {**journal.store.baseline, "snapshot_id": "other"}
        elif fault == "denial":
            journal.env.grants["INSPECT_SCENE"] = False
        else:
            def cancelled():
                raise journal.env.module.BridgeError("OPERATION_FAILED", "caller cancelled")
            journal.env.context.check_final_request = cancelled
        return {"status": "unchanged_within_scope", "coverage_complete": True}
    journal.executor.evidence.compare = compare
    with pytest.raises(journal.env.module.BridgeError):
        journal.compare()
    assert not journal.inspect()["receipts"] or journal.inspect()["receipts"][0]["protected_observation"] is None


def test_later_mutator_invalidates_previous_observation(journal):
    assert journal.apply().ok
    journal.compare()
    request = journal.protocol.Request(id="later", method="transform.set", params={"object_name": "Owner", "location": [4., 5., 6.]})
    assert journal.executor.execute_request(request).ok
    assert journal.inspect()["receipts"][0]["protected_observation"]["validity"] == "stale"


def test_direct_registry_writer_in_final_compare_provider_cannot_attach_old_evidence(journal):
    assert journal.apply().ok
    env = journal.env
    env.context.registry.register("fixture.protected_edit", lambda *_: setattr(env.protected, "location", (8., 0., 0.)), modifies=True)
    armed = []
    def compare(*_args):
        armed.append(True)
        return {"status": "unchanged_within_scope", "coverage_complete": True}
    def provider():
        if armed:
            armed.clear()
            env.context.registry.dispatch("fixture.protected_edit", {}, env.context)
    journal.executor.evidence.compare = compare
    env.provider[0] = provider
    with pytest.raises(env.module.BridgeError, match="changed during comparison"):
        journal.compare()
    assert env.protected.location == (8., 0., 0.)
    assert journal.inspect()["receipts"][0]["protected_observation"] is None


def test_terminal_receipt_retains_local_association_after_context_slot_change(journal):
    result = preview(journal.env, step_id="revise")
    spec = journal.env.context.registry.get("task.plan.apply_preview")
    def fail(context, _params):
        context.artist_step_entry = None
        raise journal.env.module.BridgeError("OPERATION_FAILED", "injected after changing context slot")
    journal.env.context.registry._tools[spec.name] = replace(spec, handler=fail)
    response = journal.apply(result)
    assert not response.ok
    receipt = journal.inspect()["receipts"][0]
    assert receipt["preview_id"] == result["preview_id"]
    assert receipt["operation_id"] == response.error["context"]["operation_id"]


@pytest.mark.parametrize("step_id", ["missing", "Revise", "", 1, True, [], {}])
def test_step_binding_requires_exact_current_step(journal, step_id):
    with pytest.raises(journal.env.module.BridgeError):
        preview(journal.env, step_id=step_id)
    assert not journal.inspect()["receipts"] and journal.env.obj.location == (0., 0., 0.)


def test_associated_compare_requires_revision_and_prior_outer_receipt(journal):
    for params in ({"step_id": "revise"}, {"step_id": "revise", "expected_revision": True},
                   {"expected_revision": 1}, {"step_id": "revise", "expected_revision": 1}):
        with pytest.raises(journal.env.module.BridgeError):
            journal.env.plans.compare_plan(journal.env.context, params)
    assert not journal.inspect()["receipts"]


def test_bounded_defensive_journal_and_saved_v1_remain_passive(journal):
    for index in range(journal.evidence.MAX_RECEIPTS + 2):
        result = preview(journal.env, step_id="revise", location=[float(index), 0., 0.])
        assert journal.apply(result).ok
    result = journal.inspect()
    assert len(result["receipts"]) == result["max_receipts"] == 32 and result["truncated"]
    result["receipts"][-1]["operation_id"] = "forged"
    assert journal.inspect()["receipts"][-1]["operation_id"] != "forged"
    raw = journal.env.data.encode_saved(journal.store.plan)
    assert "operation_id" not in raw and "receipt_id" not in raw and "step_evidence" not in raw
    saved = json.loads(raw)
    saved["step_evidence"] = result
    with pytest.raises(journal.env.module.BridgeError):
        journal.env.data.decode_saved(json.dumps(saved))


@pytest.mark.parametrize("failed", [False, True])
def test_bookkeeping_failure_preserves_primary_outcome_and_single_history(journal, monkeypatch, failed):
    def fail():
        raise RuntimeError("injected journal allocation failure")
    result = preview(journal.env, step_id="revise")
    monkeypatch.setattr(journal.evidence, "_record_terminal", lambda *_args, **_kw: fail())
    if failed:
        journal.env.grants["TRANSFORM_OBJECTS"] = False
    response = journal.apply(result)
    assert response.ok is (not failed)
    assert len(journal.env.context.state.history()) == 1
    assert journal.inspect()["incomplete"] and not journal.inspect()["receipts"]


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("replacement", ["absent", "foreign"])
def test_terminal_does_not_recreate_disappeared_store_or_mask_primary_outcome(
    journal, monkeypatch, failed, replacement
):
    env = journal.env
    bound = preview(env, step_id="revise")
    state, foreign = env.context.state, object()
    primary = env.module.BridgeError("INVALID_ARGUMENT", "injected primary apply failure")
    if failed:
        spec = env.context.registry.get("task.plan.apply_preview")

        def fail(*_args):
            raise primary

        env.context.registry._tools[spec.name] = replace(spec, handler=fail)
    original_record = state.record_operation
    constructors = []

    def allocation_failure(_self):
        constructors.append(True)
        raise MemoryError("a terminal hook must not allocate a replacement store")

    def record_then_drop_store(**kwargs):
        record = original_record(**kwargs)
        if replacement == "absent":
            state.__dict__.pop("_artist_task_plans", None)
        else:
            state._artist_task_plans = foreign
        monkeypatch.setattr(env.data.TaskPlanStore, "__init__", allocation_failure)
        return record

    monkeypatch.setattr(state, "record_operation", record_then_drop_store)
    response = journal.apply(bound)
    assert response.ok is (not failed)
    history = state.history()
    assert len(history) == 1 and history[0]["success"] is (not failed)
    assert constructors == [] and journal.store.step_receipts == []
    assert getattr(state, "_artist_task_plans", None) is (None if replacement == "absent" else foreign)
    if failed:
        assert response.error["code"] == primary.code
        assert response.error["message"] == primary.message
        assert "step_receipt_id" not in response.error["context"]
    else:
        assert response.result["operation"]["operation_id"] == history[0]["operation_id"]
        assert "step_receipt_id" not in response.result


@pytest.mark.parametrize("failed", [False, True])
def test_terminal_revision_allocation_failure_preserves_outcome_and_marks_existing_journal(
    journal, monkeypatch, failed
):
    env = journal.env
    bound = preview(env, step_id="revise")
    primary = env.module.BridgeError("INVALID_ARGUMENT", "injected primary apply failure")
    if failed:
        spec = env.context.registry.get("task.plan.apply_preview")

        def fail(*_args):
            raise primary

        env.context.registry._tools[spec.name] = replace(spec, handler=fail)

    class UnallocatableRevision:
        def __add__(self, _amount):
            raise MemoryError("injected revision integer allocation failure")

    original_record = env.context.state.record_operation

    def record_then_fail_revision(**kwargs):
        record = original_record(**kwargs)
        journal.store.evidence_revision = UnallocatableRevision()
        return record

    monkeypatch.setattr(env.context.state, "record_operation", record_then_fail_revision)
    response = journal.apply(bound)
    assert response.ok is (not failed)
    assert len(env.context.state.history()) == 1
    assert journal.store.receipts_incomplete is True
    assert journal.store.step_receipts == []
    if failed:
        assert response.error["code"] == primary.code
        assert response.error["message"] == primary.message


def test_additive_mcp_step_arguments_preserve_existing_calls():
    calls = []
    class Registry:
        async def call(self, method, params=None):
            calls.append((method, params))
            return {}
    tools = TaskPlanTools(Registry())
    asyncio.run(tools.task_plan_preview_transform("ref", 1, location=[1., 2., 3.], step_id="revise"))
    asyncio.run(tools.task_plan_compare(100, step_id="revise", expected_revision=1))
    asyncio.run(tools.task_plan_compare())
    assert calls == [("task.plan.preview_transform", {"reference_id": "ref", "expected_revision": 1, "location": [1., 2., 3.], "step_id": "revise"}),
                     ("task.plan.compare", {"max_elements": 100, "step_id": "revise", "expected_revision": 1}),
                     ("task.plan.compare", {})]
