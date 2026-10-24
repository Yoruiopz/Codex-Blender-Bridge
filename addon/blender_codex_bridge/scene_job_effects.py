"""Preallocated native-call facts, without callbacks or execution authority.

Trusted Scene adapters mark exact slot booleans around their innermost native
calls. Terminal readers use this retained journal, never the stopped driver.
An entered boundary can have effects even when its call does not return; normal
return is not verification of native state, cache contents or recoverability.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from .errors import BridgeError, ErrorCode
from .scene_job_evidence import plain

MAX_PHASES, MAX_CALLS_PER_PHASE, MAX_CALLS, MAX_BODIES = 101, 33, 1125, 16
OPERATIONS = (
    "cache_frame_start_set", "cache_frame_end_set", "world_reset", "frame_set",
    "view_layer_update", "depsgraph_get", "evaluated_get", "matrix_capture",
)


def _invalid(*, plan: bool = False) -> BridgeError:
    return BridgeError(
        ErrorCode.INVALID_ARGUMENT if plan else ErrorCode.OPERATION_FAILED,
        "Scene native-effect evidence has no reviewed bounded shape.",
        {"reason": "SCENE_NATIVE_EFFECT_PLAN_INVALID" if plan else "SCENE_NATIVE_EFFECTS_INVALID",
         "verification_required": True},
    )


@dataclass(frozen=True, slots=True)
class NativeCallPlan:
    operation: str
    body_name: str | None = None
    target: Any = None


@dataclass(frozen=True, slots=True)
class NativePhasePlan:
    phase: str
    calls: tuple[NativeCallPlan, ...]


@dataclass(slots=True)
class NativeCallBits:
    entered: bool = False
    returned: bool = False


@dataclass(slots=True)
class NativePhaseBits:
    calls: tuple[NativeCallBits, ...]
    verified: bool = False
    sample_recorded: bool = False


@dataclass(slots=True)
class EffectsStatus:
    sealed: bool = False
    evidence_incomplete: bool = False
    snapshot_allocation_failed: bool = False


def _text(value: Any, maximum: int) -> bool:
    if type(value) is not str or not 1 <= len(value) <= maximum:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _target(value: Any, remaining: list[int], depth: int = 0) -> None:
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 2:
        raise _invalid(plan=True)
    kind = type(value)
    if kind is tuple and len(value) <= 8:
        remaining[1] -= 2 + max(0, len(value) - 1)
        for item in value:
            _target(item, remaining, depth + 1)
    elif (value is None or kind is bool or (kind is int and value.bit_length() <= 128)
          or (kind is float and math.isfinite(value))
          or (kind is str and (value == "" or _text(value, 128)))):
        remaining[1] -= len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    else:
        raise _invalid(plan=True)
    if remaining[1] < 0:
        raise _invalid(plan=True)


def _validate_plans(plans: Any) -> int:
    if type(plans) is not tuple or len(plans) > MAX_PHASES:
        raise _invalid(plan=True)
    total, bodies = 0, set()
    for phase in plans:
        if (type(phase) is not NativePhasePlan or not _text(phase.phase, 128)
                or type(phase.calls) is not tuple or len(phase.calls) > MAX_CALLS_PER_PHASE):
            raise _invalid(plan=True)
        total += len(phase.calls)
        if total > MAX_CALLS:
            raise _invalid(plan=True)
        for call in phase.calls:
            if type(call) is not NativeCallPlan or type(call.operation) is not str or call.operation not in OPERATIONS:
                raise _invalid(plan=True)
            if call.body_name is not None:
                if not _text(call.body_name, 63):
                    raise _invalid(plan=True)
                bodies.add(call.body_name)
                if len(bodies) > MAX_BODIES:
                    raise _invalid(plan=True)
            _target(call.target, [8, 512])
    return total


@dataclass(frozen=True, slots=True, eq=False)
class SceneNativeEffects:
    plans: tuple[NativePhasePlan, ...]
    rows: tuple[NativePhaseBits, ...]
    status: EffectsStatus

    def __init__(self, plans: tuple[NativePhasePlan, ...]):
        _validate_plans(plans)
        rows = tuple(NativePhaseBits(tuple(NativeCallBits() for _ in phase.calls)) for phase in plans)
        object.__setattr__(self, "plans", plans)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "status", EffectsStatus())


def _copy_target(value: Any) -> Any:
    # Plans already admitted immutable tuples; each descriptor gets its own
    # detached JSON array, including when several facts name the same target.
    return [_copy_target(item) for item in value] if type(value) is tuple else value


def _descriptor(index: int | None, phase: NativePhasePlan | None,
                call: NativeCallPlan | None) -> dict | None:
    if phase is None:
        return None
    return {"index": index, "phase": phase.phase,
            "operation": None if call is None else call.operation,
            "body_name": None if call is None else call.body_name,
            "target": None if call is None else _copy_target(call.target)}


def _snapshot(journal: SceneNativeEffects) -> dict:
    total = _validate_plans(journal.plans)
    if type(journal.rows) is not tuple or len(journal.rows) != len(journal.plans):
        raise _invalid()
    status = journal.status
    if any(type(value) is not bool for value in
           (status.sealed, status.evidence_incomplete, status.snapshot_allocation_failed)):
        raise _invalid()
    counts = {operation: {"entered": 0, "returned": 0} for operation in OPERATIONS}
    entered_index = returned_index = verified_index = None
    entered_phase = returned_phase = verified_phase = None
    entered_call = returned_call = None
    verified_count = samples = 0
    for index, (plan, row) in enumerate(zip(journal.plans, journal.rows, strict=True)):
        if (type(row) is not NativePhaseBits or type(row.calls) is not tuple
                or len(row.calls) != len(plan.calls)
                or type(row.verified) is not bool or type(row.sample_recorded) is not bool):
            raise _invalid()
        for call, bits in zip(plan.calls, row.calls, strict=True):
            if (type(bits) is not NativeCallBits or type(bits.entered) is not bool
                    or type(bits.returned) is not bool or (bits.returned and not bits.entered)):
                raise _invalid()
            if bits.entered:
                counts[call.operation]["entered"] += 1
                entered_index, entered_phase, entered_call = index, plan, call
            if bits.returned:
                counts[call.operation]["returned"] += 1
                returned_index, returned_phase, returned_call = index, plan, call
        if row.verified:
            verified_count += 1
            verified_index, verified_phase = index, plan
        samples += int(row.sample_recorded)
    return {"schema_version": 1, "phases_planned": len(journal.plans), "calls_planned": total,
            "phases_verified": verified_count, "sample_recorded_count": samples,
            "counts_by_operation": counts,
            "last_entered": _descriptor(entered_index, entered_phase, entered_call),
            "last_returned": _descriptor(returned_index, returned_phase, returned_call),
            "last_verified": _descriptor(verified_index, verified_phase,
                verified_phase.calls[0] if verified_phase is not None and verified_phase.calls else None),
            "sealed": status.sealed, "evidence_incomplete": status.evidence_incomplete,
            "snapshot_allocation_failed": status.snapshot_allocation_failed,
            "flag_semantics": "BOUNDARY_ENTRY_ATTEMPTED_AND_NORMAL_RETURN_ONLY_NO_NATIVE_STATE_OR_RECOVERY_CLAIM"}


def snapshot_native_effects(journal: SceneNativeEffects) -> dict:
    """Copy retained literal facts only; allocation failure remains retryable.

    Sealing is the caller's terminal-lifecycle decision. This function does not
    run providers, driver properties, native getters, cleanup or authorization.
    """
    if type(journal) is not SceneNativeEffects or type(journal.status) is not EffectsStatus:
        raise _invalid()
    status = journal.status
    try:
        return plain(_snapshot(journal), field="native_effects", byte_limit=8192, item_limit=512)
    except MemoryError:
        status.evidence_incomplete = True
        status.snapshot_allocation_failed = True
        raise
    except BridgeError:
        status.evidence_incomplete = True
        raise
