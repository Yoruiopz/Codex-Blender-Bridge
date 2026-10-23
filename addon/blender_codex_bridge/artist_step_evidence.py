"""Runtime step provenance; records facts, never completion or live authority."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .artist_target_intent import TargetIntent, public_intent
from .entry_effects import bounded_entry_effects
from .errors import BridgeError, invalid_argument
from .task_plans import TaskPlanStore, get_task_plans

MAX_RECEIPTS = 32
TARGET_VERIFY_METHOD = "task.plan.verify_transform"
TARGET_SCOPE = "authored_core_transform_channels"


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
    target_intent: TargetIntent | None = None


@dataclass(frozen=True, slots=True)
class TargetVerifyCall:
    """Frozen intent/facts plus retained Python identities; never native owners."""

    store: TaskPlanStore = field(compare=False, repr=False)
    plan: dict[str, Any] = field(compare=False, repr=False)
    receipt: dict[str, Any] = field(compare=False, repr=False)
    association: StepAssociation
    requested_revision: int
    receipt_id: str
    operation_id: str
    target_intent: TargetIntent
    mutation_revision: int
    completed_mutation_revision: int
    plan_origin: tuple[Any, ...]
    receipt_origin: tuple[Any, ...]


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


def _plain_keys(value: Any, maximum: int) -> bool:
    """Reject custom keys before any dictionary lookup can compare them."""
    return (type(value) is dict and len(value) <= maximum
            and all(type(key) is str and len(key) <= 128 for key in value))


def _plan_origin(plan: Any) -> tuple[Any, ...]:
    """Bound passive values without serializers, adapters or native readers."""
    if (not _plain_keys(plan, 6) or set(plan) != {"schema_version", "plan_id", "revision", "goal", "steps", "protected_objects"}
            or type(plan["schema_version"]) is not int or plan["schema_version"] != 1
            or type(plan["plan_id"]) is not str or re.fullmatch(r"plan_[a-f0-9]{32}", plan["plan_id"]) is None
            or type(plan["revision"]) is not int or not 1 <= plan["revision"] <= 1_000_000_000):
        raise invalid_argument("The current plan has no bounded target-verification provenance.")

    def text(value: Any, maximum: int, *, empty: bool = False) -> str:
        if type(value) is not str or len(value) > maximum or (not empty and not value.strip()):
            raise invalid_argument("The current plan has malformed target-verification text.")
        try:
            value.encode("utf-8")
        except UnicodeError as error:
            raise invalid_argument("The current plan has invalid target-verification text.") from error
        return value

    steps, protected = plan["steps"], plan["protected_objects"]
    if type(steps) is not list or not 1 <= len(steps) <= 32 or type(protected) is not list or len(protected) > 32:
        raise invalid_argument("The current plan exceeds its bounded target-verification scope.")
    contents = []
    for step in steps:
        if (not _plain_keys(step, 4) or set(step) != {"id", "description", "status", "note"}
                or type(step["id"]) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", step["id"]) is None
                or type(step["status"]) is not str or step["status"] not in {"pending", "in_progress", "completed", "blocked"}):
            raise invalid_argument("The current plan step has no bounded target-verification identity.")
        contents.append((step["id"], text(step["description"], 500), step["status"], text(step["note"], 500, empty=True)))
    if len({step[0] for step in contents}) != len(contents):
        raise invalid_argument("Current plan step identities are not unique.")
    names = tuple(text(name, 63) for name in protected)
    if len(set(names)) != len(names):
        raise invalid_argument("Current protected names are not unique.")
    return (plan["schema_version"], plan["plan_id"], plan["revision"], text(plan["goal"], 2000), tuple(contents), names)


def _target_receipt(store: TaskPlanStore, step_id: str) -> dict[str, Any]:
    receipts = store.step_receipts
    if type(receipts) is not list or len(receipts) > MAX_RECEIPTS:
        raise invalid_argument("Target verification requires the bounded runtime receipt journal.")
    for receipt in reversed(receipts):
        if not _plain_keys(receipt, 64) or type(receipt.get("step_id")) is not str:
            raise invalid_argument("The runtime receipt journal has malformed provenance.")
        if receipt["step_id"] == step_id:
            return receipt
    raise invalid_argument("The step has no retained outer operation receipt; apply a step-linked preview first.")


def _receipt_origin(receipt: dict[str, Any]) -> tuple[Any, ...]:
    if not _plain_keys(receipt, 64):
        raise invalid_argument("The receipt requires bounded plain field names.")
    keys = ("receipt_id", "step_id", "step_description", "plan_id", "runtime_id", "evidence_epoch", "preview_id",
            "preview_revision", "requested_revision", "completed_revision", "completed_mutation_revision", "generation",
            "operation_id", "method", "success", "outcome", "error_code", "handler_entered", "execution_started",
            "possible_mutation", "undo_boundary_created", "undo_boundary_finalized")
    values = tuple(receipt.get(key) for key in keys)
    if any(type(value) not in (str, int, bool, type(None)) or (type(value) is str and len(value) > 512) for value in values):
        raise invalid_argument("The receipt has malformed target-verification facts.")
    counters = {"evidence_epoch", "preview_revision", "requested_revision", "completed_revision",
                "completed_mutation_revision", "generation"}
    flags = {"success", "handler_entered", "undo_boundary_created", "undo_boundary_finalized"}
    optional = {"error_code", "execution_started", "possible_mutation"}
    for key, value in zip(keys, values, strict=True):
        if key in counters:
            valid = type(value) is int and value >= 0 and value.bit_length() <= 128
        elif key in flags:
            valid = type(value) is bool
        elif key in optional:
            valid = value is None or type(value) is (str if key == "error_code" else bool)
        else:
            valid = type(value) is str
        if not valid:
            raise invalid_argument("The receipt has an invalid target-verification fact type.", field=key)
    return tuple((key, type(value).__name__, value) for key, value in zip(keys, values, strict=True))


def _capture_target_verify(context: Any, params: Any) -> TargetVerifyCall | None:
    """No plan-store creation and no reads outside bounded runtime Python data."""
    if not _plain_keys(params, 3) or set(params) != {"step_id", "receipt_id", "expected_revision"}:
        return None
    step_id, receipt_id, expected = params.get("step_id"), params.get("receipt_id"), params.get("expected_revision")
    if (type(step_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", step_id) is None
            or type(receipt_id) is not str or re.fullmatch(r"step_receipt_[a-f0-9]{32}", receipt_id) is None
            or type(expected) is not int or not 1 <= expected <= 1_000_000_000):
        return None
    store = getattr(context.state, "_artist_task_plans", None)
    if (type(store) is not TaskPlanStore or store.plan is None or type(store.runtime_id) is not str
            or any(type(value) is not int for value in
                   (store.evidence_epoch, store.protection_generation, store.evidence_revision))):
        return None
    try:
        origin = _plan_origin(store.plan)
        if expected != store.plan["revision"]:
            return None
        association = associate(store, step_id)
        receipt = _target_receipt(store, step_id)
        facts = _receipt_origin(receipt)
        intent = receipt.get("target_intent")
        if (receipt.get("receipt_id") != receipt_id or receipt.get("step_description") != association.description
                or receipt.get("plan_id") != association.plan_id or receipt.get("runtime_id") != association.runtime_id
                or receipt.get("evidence_epoch") != association.epoch or receipt.get("generation") != association.generation
                or receipt.get("method") != "task.plan.apply_preview" or receipt.get("success") is not True
                or receipt.get("outcome") != "completed" or receipt.get("handler_entered") is not True
                or type(receipt.get("operation_id")) is not str or not receipt["operation_id"]
                or type(receipt.get("completed_mutation_revision")) is not int
                or receipt["completed_mutation_revision"] != store.evidence_revision or type(intent) is not TargetIntent):
            return None
        return TargetVerifyCall(store, store.plan, receipt, association, expected, receipt_id, receipt["operation_id"],
                                intent, store.evidence_revision, receipt["completed_mutation_revision"], origin, facts)
    except BridgeError:
        return None  # Malformed or stale provenance never becomes a fresh baseline.


def capture_call(context: Any, request: Any) -> StepCall | TargetVerifyCall | None:
    """Capture optional provenance before any executor entry providers run."""
    context.artist_step_entry_captured = True
    context.artist_step_entry = None
    if request.method == TARGET_VERIFY_METHOD:
        context.artist_step_entry = _capture_target_verify(context, request.params)
        return context.artist_step_entry
    if request.method != "task.plan.apply_preview":
        return None
    store = get_task_plans(context.state)
    identifier = request.params.get("preview_id")
    preview = store.previews.get(identifier) if type(identifier) is str else None
    association = preview.get("step_association") if preview is not None else None
    revision = request.params.get("expected_revision")
    if matches(store, association) and type(revision) is int:
        intent = preview.get("target_intent")
        context.artist_step_entry = StepCall(store, association, identifier, revision,
                                            intent if type(intent) is TargetIntent else None)
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
            or entry.preview_id != identifier or entry.requested_revision != params.get("expected_revision")
            or entry.target_intent is not preview.get("target_intent")):
        raise invalid_argument("The executor's retained preview/step association changed before application.")


def record_terminal(context: Any, request: Any, record: Any, evidence: Any, *, entry: StepCall | TargetVerifyCall | None, modifying: bool,
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


def _record_terminal(store: TaskPlanStore, entry: StepCall | TargetVerifyCall | None, request: Any, record: Any, evidence: Any, *,
                     handler_entered: bool, undo_created: bool, undo_finalized: bool) -> str | None:
    if (request.method != "task.plan.apply_preview" or record is None or not isinstance(entry, StepCall)
            or entry.store is not store or not matches(store, entry.association, generation=False)):
        return None
    details = evidence if isinstance(evidence, Mapping) else {}
    started = details.get("execution_started")
    possible = details.get("possible_mutation")
    identifier = "step_receipt_" + uuid.uuid4().hex
    receipt = {"receipt_id": identifier, "step_id": entry.association.step_id,
        "step_description": entry.association.description, "runtime_id": entry.association.runtime_id,
        "evidence_epoch": entry.association.epoch,
        "plan_id": entry.association.plan_id, "preview_id": entry.preview_id,
        "preview_revision": entry.association.preview_revision, "requested_revision": entry.requested_revision,
        "completed_revision": store.plan["revision"], "generation": entry.association.generation,
        "completed_mutation_revision": store.evidence_revision, "target_intent": entry.target_intent,
        "operation_id": record.operation_id, "method": record.tool, "success": record.success,
        "outcome": "completed" if record.success else "failed" if handler_entered or started is True else "rejected",
        "error_code": record.error_code, "handler_entered": handler_entered,
        "execution_started": started if type(started) is bool else None,
        "possible_mutation": possible if type(possible) is bool else None,
        "undo_boundary_created": bool(undo_created), "undo_boundary_finalized": bool(undo_finalized),
        "recovery_evidence": deepcopy(record.recovery_evidence), "protected_observation": None,
        "target_observation": None}
    effects = bounded_entry_effects(getattr(record, "entry_effects", None))
    if effects is not None:
        receipt["entry_effects"] = effects
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


def require_target_verify_entry(context: Any, params: Mapping[str, Any]) -> TargetVerifyCall:
    entry = getattr(context, "artist_step_entry", None)
    if not getattr(context, "artist_step_entry_captured", False) or type(entry) is not TargetVerifyCall:
        raise invalid_argument(
            "Target verification requires the exact latest successful outer step receipt in the current runtime generation; inspect and apply a step-linked preview first.",
            target_verification_available=False,
        )
    check_target_verify_entry(context, entry, params)
    return entry


def check_target_verify_entry(context: Any, entry: TargetVerifyCall, params: Mapping[str, Any] | None = None) -> None:
    """Pure provenance CAS; callers finish live providers before native reads."""
    if type(entry) is not TargetVerifyCall or getattr(context, "artist_step_entry", None) is not entry:
        raise invalid_argument("The captured target-verification invocation changed; no observation was attached.")
    if params is not None and (not _plain_keys(params, 3)
            or set(params) != {"step_id", "receipt_id", "expected_revision"} or type(params.get("step_id")) is not str
            or type(params.get("receipt_id")) is not str or params["step_id"] != entry.association.step_id
            or params["receipt_id"] != entry.receipt_id or type(params.get("expected_revision")) is not int
            or params["expected_revision"] != entry.requested_revision):
        raise invalid_argument("Target-verification parameters changed after entry; no observation was attached.")
    store = getattr(context.state, "_artist_task_plans", None)
    if (store is not entry.store or type(store) is not TaskPlanStore or store.plan is not entry.plan
            or type(store.runtime_id) is not str or type(store.evidence_epoch) is not int
            or type(store.protection_generation) is not int or type(store.evidence_revision) is not int
            or _plan_origin(store.plan) != entry.plan_origin or not matches(store, entry.association)
            or store.evidence_revision != entry.mutation_revision
            or store.plan["revision"] != entry.requested_revision):
        raise invalid_argument("The plan, step or runtime generation changed during target verification; no observation was attached.")
    receipt = _target_receipt(store, entry.association.step_id)
    if (receipt is not entry.receipt or receipt.get("target_intent") is not entry.target_intent
            or _receipt_origin(receipt) != entry.receipt_origin
            or receipt.get("completed_mutation_revision") != entry.completed_mutation_revision
            or entry.completed_mutation_revision != store.evidence_revision):
        raise invalid_argument("The latest step receipt or target intent changed during verification; no observation was attached.")
    flags = context.state.snapshot()
    if (context.registry.executing_mutators or store.executing_mutators or store.applying_preview is not None
            or (flags.get("is_executing") and flags.get("current_method") != TARGET_VERIFY_METHOD)
            or (context.jobs is not None and context.jobs.active is not None)):
        raise invalid_argument("Finish the current writer or job before verifying a target receipt; no observation was attached.")


def _observation_copy(value: Any) -> Any:
    """Copy bounded exact JSON types; never invoke custom copy/adaptor methods."""
    remaining = [2048, 16384]

    def visit(item: Any, depth: int = 0) -> Any:
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 8:
            raise invalid_argument("Target observation exceeds its bounded plain-data profile.")
        kind = type(item)
        if item is None or kind is bool:
            return item
        if kind is int:
            if item.bit_length() > 128:
                raise invalid_argument("Target observation contains an unbounded integer.")
            return item
        if kind is float:
            if not math.isfinite(item):
                raise invalid_argument("Target observation contains a nonfinite value.")
            return item
        if kind is str:
            remaining[1] -= len(item)
            if len(item) > 2048 or remaining[1] < 0:
                raise invalid_argument("Target observation exceeds its bounded text profile.")
            return item
        if kind is list:
            if len(item) > remaining[0]:
                raise invalid_argument("Target observation exceeds its bounded item profile.")
            return [visit(child, depth + 1) for child in item]
        if kind is dict:
            if len(item) > remaining[0] or any(type(key) is not str or len(key) > 128 for key in item):
                raise invalid_argument("Target observation requires bounded plain field names.")
            return {visit(key, depth + 1): visit(child, depth + 1) for key, child in item.items()}
        raise invalid_argument("Target observation requires plain JSON data without adapters.")

    return visit(value)


def append_target_observation(context: Any, entry: TargetVerifyCall, evidence: dict[str, Any], *,
                              before_attach: Callable[[], None]) -> dict[str, Any]:
    """Attach bounded recorded facts after pure CAS, never step completion."""
    check_target_verify_entry(context, entry)
    if not _plain_keys(evidence, 2048) or type(evidence.get("status")) is not str or evidence["status"] not in {
            "channels_match", "channels_differ", "target_missing", "target_replaced"}:
        raise invalid_argument("Target observation requires a known bounded comparison outcome.")
    observation = _observation_copy(evidence)
    observation.update(
        observation_id="target_observation_" + uuid.uuid4().hex,
        receipt_id=entry.receipt_id, operation_id=entry.operation_id,
        generation=entry.association.generation, evidence_epoch=entry.association.epoch,
        mutation_revision=entry.mutation_revision, scope=TARGET_SCOPE,
        validity="recorded", current_scene_verified=False, user_goal_verified=False,
    )
    returned = _observation_copy(observation)
    check_target_verify_entry(context, entry)
    # Internal canonical lifecycle/spec hook, never a wire callback or live
    # permission provider. Keep the attachment immediately after it.
    before_attach()
    entry.receipt["target_observation"] = observation
    return returned


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
        intent = receipt.pop("target_intent", None)
        receipt["target_expectation"] = public_intent(intent) if type(intent) is TargetIntent else None
        target = receipt.get("target_observation")
        if target is not None:
            stale_target = (target["generation"] != store.protection_generation
                or target["evidence_epoch"] != store.evidence_epoch
                or target["mutation_revision"] != store.evidence_revision)
            target["validity"] = "stale" if stale_target else "recorded"
            target["current_scene_verified"] = False
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
        "target_observation_scope": TARGET_SCOPE,
        "max_receipts": MAX_RECEIPTS, "truncated": store.receipts_truncated,
        "incomplete": store.receipts_incomplete, "receipts": receipts}
