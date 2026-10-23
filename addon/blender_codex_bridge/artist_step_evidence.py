"""Runtime step provenance; records facts, never completion or live authority."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .errors import invalid_argument
from .task_plans import TaskPlanStore, get_task_plans

MAX_RECEIPTS = 32


@dataclass(frozen=True, slots=True)
class StepAssociation:
    runtime_id: str
    epoch: int
    plan_id: str
    step_id: str
    description: str
    preview_revision: int
    generation: int


@dataclass(frozen=True, slots=True)
class StepCall:
    store: TaskPlanStore
    association: StepAssociation
    preview_id: str
    requested_revision: int


def associate(store: TaskPlanStore, step_id: Any) -> StepAssociation:
    plan = store.require_plan()
    if not isinstance(step_id, str):
        raise invalid_argument("step_id must name an exact current plan step.")
    step = next((step for step in plan["steps"] if step["id"] == step_id), None)
    if step is None:
        raise invalid_argument("The current plan has no step with this exact step_id.")
    return StepAssociation(store.runtime_id, store.evidence_epoch, plan["plan_id"], step_id,
                           step["description"], plan["revision"], store.protection_generation)


def matches(store: TaskPlanStore, association: Any, *, generation: bool = True) -> bool:
    if not isinstance(association, StepAssociation) or store.plan is None:
        return False
    return (association.runtime_id == store.runtime_id and association.epoch == store.evidence_epoch
        and association.plan_id == store.plan["plan_id"]
        and (not generation or association.generation == store.protection_generation)
        and any(step["id"] == association.step_id and step["description"] == association.description for step in store.plan["steps"]))


def capture_call(context: Any, request: Any) -> StepCall | None:
    """Capture optional provenance before any executor entry providers run."""
    context.artist_step_entry_captured = True
    context.artist_step_entry = None
    if request.method != "task.plan.apply_preview":
        return None
    store = get_task_plans(context.state)
    identifier = request.params.get("preview_id")
    preview = store.previews.get(identifier) if type(identifier) is str else None
    association = preview.get("step_association") if preview is not None else None
    revision = request.params.get("expected_revision")
    if matches(store, association) and type(revision) is int:
        context.artist_step_entry = StepCall(store, association, identifier, revision)
    return context.artist_step_entry


def check_apply(context: Any, identifier: str, preview: Mapping[str, Any], params: Mapping[str, Any]) -> None:
    association = preview.get("step_association")
    store = get_task_plans(context.state)
    if association is not None and not matches(store, association):
        raise invalid_argument("The preview's plan step or runtime generation changed; preview again.")
    if not getattr(context, "artist_step_entry_captured", False):
        return  # Direct registry calls have no outer executor operation receipt.
    entry = context.artist_step_entry
    if association is None and entry is None:
        return
    if (not isinstance(entry, StepCall) or entry.store is not store or entry.association != association
            or entry.preview_id != identifier or entry.requested_revision != params.get("expected_revision")):
        raise invalid_argument("The executor's retained preview/step association changed before application.")


def record_terminal(context: Any, request: Any, record: Any, evidence: Any, *, entry: StepCall | None, modifying: bool,
                    handler_entered: bool, undo_created: bool, undo_finalized: bool) -> str | None:
    """One pure bookkeeping hook after the actual outer operation is finalized.

    No permissions, Blender access, callbacks, request dispatch or raw result
    retention. A replaced/loaded/reset plan never adopts an earlier call's fact.
    Terminal bookkeeping never creates a runtime plan store.
    """
    store = None
    try:
        store = getattr(context.state, "_artist_task_plans", None)
        if not isinstance(store, TaskPlanStore):
            return None
        if modifying:
            store.evidence_revision += 1
        return _record_terminal(store, entry, request, record, evidence, handler_entered=handler_entered,
                                undo_created=undo_created, undo_finalized=undo_finalized)
    except Exception:
        # Provenance bookkeeping must never replace a primary outcome or create
        # a second history record. Report the incomplete journal on inspection.
        if isinstance(store, TaskPlanStore):
            store.receipts_incomplete = True
        return None


def _record_terminal(store: TaskPlanStore, entry: StepCall | None, request: Any, record: Any, evidence: Any, *,
                     handler_entered: bool, undo_created: bool, undo_finalized: bool) -> str | None:
    if (request.method != "task.plan.apply_preview" or record is None or not isinstance(entry, StepCall)
            or entry.store is not store or not matches(store, entry.association, generation=False)):
        return None
    details = evidence if isinstance(evidence, Mapping) else {}
    started = details.get("execution_started")
    possible = details.get("possible_mutation")
    identifier = "step_receipt_" + uuid.uuid4().hex
    receipt = {"receipt_id": identifier, "step_id": entry.association.step_id,
        "plan_id": entry.association.plan_id, "preview_id": entry.preview_id,
        "preview_revision": entry.association.preview_revision, "requested_revision": entry.requested_revision,
        "completed_revision": store.plan["revision"], "generation": entry.association.generation,
        "operation_id": record.operation_id, "method": record.tool, "success": record.success,
        "outcome": "completed" if record.success else "failed" if handler_entered or started is True else "rejected",
        "error_code": record.error_code, "handler_entered": handler_entered,
        "execution_started": started if type(started) is bool else None,
        "possible_mutation": possible if type(possible) is bool else None,
        "undo_boundary_created": bool(undo_created), "undo_boundary_finalized": bool(undo_finalized),
        "recovery_evidence": deepcopy(record.recovery_evidence), "protected_observation": None}
    if len(store.step_receipts) == MAX_RECEIPTS:
        store.step_receipts.pop(0)
        store.receipts_truncated = True
    store.step_receipts.append(receipt)
    return identifier


def latest(store: TaskPlanStore, step_id: str) -> dict[str, Any]:
    for receipt in reversed(store.step_receipts):
        if receipt["step_id"] == step_id:
            return receipt
    raise invalid_argument("The step has no retained outer operation receipt; apply a step-linked preview first.")


def observe(store: TaskPlanStore, association: StepAssociation, receipt_id: str, baseline: Mapping,
            mutation_revision: int, evidence: Mapping) -> None:
    if (not matches(store, association) or store.evidence_revision != mutation_revision
            or latest(store, association.step_id)["receipt_id"] != receipt_id
            or store.baseline is None or store.baseline["snapshot_id"] != baseline["snapshot_id"]):
        raise invalid_argument("The plan, latest operation or protected baseline changed during comparison; no step evidence was attached.")
    latest(store, association.step_id)["protected_observation"] = {
        "status": evidence["status"], "coverage_complete": evidence["coverage_complete"],
        "snapshot_id": baseline["snapshot_id"], "baseline_revision": baseline["captured_revision"],
        "generation": store.protection_generation, "mutation_revision": mutation_revision,
        "scope": "protected_objects_only", "user_goal_verified": False}


def inspect_receipts(store: TaskPlanStore, evidence: Any = None) -> dict[str, Any]:
    receipts = deepcopy(store.step_receipts)
    for receipt in receipts:
        receipt["history_state"] = ("current_runtime_generation" if receipt["generation"] == store.protection_generation
                                     else "historical_after_generation_change")
        observation = receipt["protected_observation"]
        if observation is None:
            continue
        stale = (observation["generation"] != store.protection_generation
            or observation["mutation_revision"] != store.evidence_revision
            or store.baseline is None or observation["snapshot_id"] != store.baseline["snapshot_id"])
        available = evidence is not None and evidence.has_snapshot(observation["snapshot_id"])
        observation["validity"] = "stale" if stale else "recorded" if available else "unknown"
        observation["current_scene_verified"] = False
    return {"runtime_only": True, "scope": "protected_objects_only", "user_goal_verified": False,
        "max_receipts": MAX_RECEIPTS, "truncated": store.receipts_truncated,
        "incomplete": store.receipts_incomplete, "receipts": receipts}
