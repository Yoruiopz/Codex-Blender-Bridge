"""Native-effect facts survive failed publication without reading native state."""

from __future__ import annotations

import importlib
import json
from dataclasses import FrozenInstanceError

import pytest


@pytest.fixture
def effects(addon_package):
    return importlib.import_module(f"{addon_package}.scene_job_effects")


def phase(module, name="frame_2_set", *, operation="frame_set", body_name=None, target=(2, 0.)):
    return module.NativePhasePlan(name, (module.NativeCallPlan(operation, body_name, target),))


def test_plan_and_journal_are_frozen_but_preallocated_bits_are_writable(effects):
    plan = phase(effects)
    journal = effects.SceneNativeEffects((plan,))
    row, flags, status = journal.rows[0], journal.rows[0].calls[0], journal.status
    for owner, name, value in ((plan, "phase", "changed"), (plan.calls[0], "target", None),
                               (journal, "plans", ()), (journal, "rows", ()),
                               (journal, "status", effects.EffectsStatus())):
        with pytest.raises(FrozenInstanceError):
            setattr(owner, name, value)
    for owner in (plan, plan.calls[0], journal, row, flags, status):
        assert not hasattr(owner, "__dict__")
    flags.entered = flags.returned = True
    row.verified = row.sample_recorded = True
    status.sealed = True
    assert journal.rows[0] is row and row.calls[0] is flags and journal.status is status


@pytest.mark.parametrize("target", [None, False, 0, -0., 1048574, .25, "", "frozen", (7, .25),
                                    ((1, 3), (0., False))])
def test_admits_only_bounded_immutable_primitive_targets(effects, target):
    journal = effects.SceneNativeEffects((phase(effects, target=target),))
    journal.rows[0].calls[0].entered = True
    assert effects.snapshot_native_effects(journal)["last_entered"]["phase"] == "frame_2_set"


@pytest.mark.parametrize("target", [[], {}, object(), float("inf"), float("nan"),
                                    1 << 129, "x" * 129, (None,) * 9, (((0,),),), "\ud800",
                                    ("x" * 128,) * 7, "\U0001f30d" * 128, "\x01" * 128,
                                    RuntimeError("not primitive evidence")])
def test_rejects_native_mutable_nonfinite_or_oversized_targets(effects, target):
    with pytest.raises(effects.BridgeError) as caught:
        effects.SceneNativeEffects((phase(effects, target=target),))
    assert caught.value.context["reason"] == "SCENE_NATIVE_EFFECT_PLAN_INVALID"


@pytest.mark.parametrize("value", [[], [()], (object(),)])
def test_refuses_unknown_plan_containers_without_iteration(effects, value):
    with pytest.raises(effects.BridgeError):
        effects.SceneNativeEffects(value)


@pytest.mark.parametrize("name", ["", "x" * 129, 1])
def test_bounds_phase_names(effects, name):
    with pytest.raises(effects.BridgeError):
        effects.SceneNativeEffects((phase(effects, name),))


@pytest.mark.parametrize("operation", ["BAKE", "frame_set ", "__getattr__", None])
def test_refuses_unreviewed_operations(effects, operation):
    with pytest.raises(effects.BridgeError):
        effects.SceneNativeEffects((phase(effects, operation=operation),))


def test_bounds_body_names_and_unique_inventory(effects):
    valid = tuple(effects.NativeCallPlan("matrix_capture", "Body" + str(index), 2) for index in range(16))
    effects.SceneNativeEffects((effects.NativePhasePlan("sample", valid),))
    for extra in (effects.NativeCallPlan("matrix_capture", "Body16"),
                  effects.NativeCallPlan("matrix_capture", ""),
                  effects.NativeCallPlan("matrix_capture", "x" * 64)):
        with pytest.raises(effects.BridgeError):
            effects.SceneNativeEffects((effects.NativePhasePlan("sample", (*valid, extra)),))


def test_maximum_phase_and_call_plan_is_bounded_in_summary(effects):
    # 34 full rows plus three calls are 1125 cells; remaining rows may be pure
    # verification rows. The summary never dumps those cells or their targets.
    full = tuple(effects.NativeCallPlan("frame_set", target=(index, 0.)) for index in range(33))
    plans = tuple(effects.NativePhasePlan("phase_" + str(index), full if index < 34 else
        full[:3] if index == 34 else ()) for index in range(101))
    journal = effects.SceneNativeEffects(plans)
    for row in journal.rows:
        for bits in row.calls:
            bits.entered = bits.returned = True
        row.verified = True
    result = effects.snapshot_native_effects(journal)
    assert result["phases_planned"] == result["phases_verified"] == 101
    assert result["calls_planned"] == 1125
    assert result["counts_by_operation"]["frame_set"] == {"entered": 1125, "returned": 1125}
    assert len(json.dumps(result).encode()) <= 8192 and "rows" not in result
    with pytest.raises(effects.BridgeError):
        effects.SceneNativeEffects((*plans, effects.NativePhasePlan("extra", ())))
    with pytest.raises(effects.BridgeError):
        effects.SceneNativeEffects((*plans[:34], effects.NativePhasePlan("too_many", full[:4])))
    with pytest.raises(effects.BridgeError):
        effects.SceneNativeEffects((effects.NativePhasePlan("too_wide", (*full, full[0])),))


def test_partial_call_return_and_sample_bits_keep_distinct_meaning(effects):
    plans = (phase(effects), effects.NativePhasePlan("frame_2_sample", (
        effects.NativeCallPlan("depsgraph_get", target=2),
        effects.NativeCallPlan("evaluated_get", "BodyA", 2),
        effects.NativeCallPlan("matrix_capture", "BodyA", 2),
        effects.NativeCallPlan("evaluated_get", "BodyB", 2))))
    journal = effects.SceneNativeEffects(plans)
    journal.rows[0].calls[0].entered = journal.rows[0].calls[0].returned = True
    journal.rows[0].verified = True
    for bits in journal.rows[1].calls[:3]:
        bits.entered = bits.returned = True
    journal.rows[1].calls[3].entered = True
    result = effects.snapshot_native_effects(journal)
    assert result["counts_by_operation"]["evaluated_get"] == {"entered": 2, "returned": 1}
    assert result["last_entered"]["body_name"] == "BodyB"
    assert result["last_returned"]["body_name"] == "BodyA"
    assert result["last_verified"]["phase"] == "frame_2_set"
    assert result["sample_recorded_count"] == 0 and not result["sealed"]
    assert "NO_NATIVE_STATE_OR_RECOVERY_CLAIM" in result["flag_semantics"]


def test_snapshots_are_detached_and_do_not_implicitly_seal(effects):
    journal = effects.SceneNativeEffects((phase(effects),))
    bits = journal.rows[0].calls[0]
    bits.entered = bits.returned = True
    journal.rows[0].verified = True
    result = effects.snapshot_native_effects(journal)
    result["last_entered"]["target"][0] = 999
    result["counts_by_operation"]["frame_set"]["entered"] = 99
    result["last_returned"]["target"][1] = .5
    fresh = effects.snapshot_native_effects(journal)
    assert fresh["last_entered"]["target"] == fresh["last_returned"]["target"] == [2, 0.]
    assert fresh["counts_by_operation"]["frame_set"]["entered"] == 1
    assert not journal.status.sealed and not fresh["sealed"]


def test_no_native_objects_or_subclass_getters_are_resolved(effects):
    accessed = []

    class Trap:
        def __getattribute__(self, name):
            accessed.append(name)
            raise AssertionError("no external getters")

    class ForeignPlan(effects.NativeCallPlan):
        def __getattribute__(self, name):
            accessed.append(name)
            raise AssertionError("no subclass getters")

    for plans in ((Trap(),), (effects.NativePhasePlan("read", (Trap(),)),),
                  (effects.NativePhasePlan("read", (ForeignPlan("frame_set"),)),),
                  (phase(effects, target=Trap()),)):
        with pytest.raises(effects.BridgeError):
            effects.SceneNativeEffects(plans)
    with pytest.raises(effects.BridgeError):
        effects.snapshot_native_effects(Trap())
    journal = effects.SceneNativeEffects((phase(effects),))
    journal.rows[0].calls = (Trap(),)
    with pytest.raises(effects.BridgeError):
        effects.snapshot_native_effects(journal)
    assert accessed == []


@pytest.mark.parametrize("field,value", [("verified", 1), ("sample_recorded", "yes")])
def test_refuses_nonliteral_phase_flags(effects, field, value):
    journal = effects.SceneNativeEffects((phase(effects),))
    setattr(journal.rows[0], field, value)
    with pytest.raises(effects.BridgeError):
        effects.snapshot_native_effects(journal)
    assert journal.status.evidence_incomplete


def test_counts_only_predeclared_operations_without_completion_claims(effects):
    calls = tuple(effects.NativeCallPlan(operation) for operation in effects.OPERATIONS)
    journal = effects.SceneNativeEffects((effects.NativePhasePlan("declared", calls),))
    for index, bits in enumerate(journal.rows[0].calls):
        bits.entered = True
        bits.returned = index % 2 == 0
    result = effects.snapshot_native_effects(journal)
    assert tuple(result["counts_by_operation"]) == effects.OPERATIONS
    assert sum(row["entered"] for row in result["counts_by_operation"].values()) == 8
    assert sum(row["returned"] for row in result["counts_by_operation"].values()) == 4
    assert result["phases_verified"] == result["sample_recorded_count"] == 0


@pytest.mark.parametrize("field,value", [("entered", 1), ("returned", "yes")])
def test_refuses_nonliteral_bits_and_marks_incomplete(effects, field, value):
    journal = effects.SceneNativeEffects((phase(effects),))
    setattr(journal.rows[0].calls[0], field, value)
    with pytest.raises(effects.BridgeError):
        effects.snapshot_native_effects(journal)
    assert journal.status.evidence_incomplete and not journal.status.snapshot_allocation_failed


def test_refuses_return_without_entered(effects):
    journal = effects.SceneNativeEffects((phase(effects),))
    journal.rows[0].calls[0].returned = True
    with pytest.raises(effects.BridgeError):
        effects.snapshot_native_effects(journal)
    assert journal.status.evidence_incomplete


@pytest.mark.parametrize("fault", ["_snapshot", "plain"])
def test_snapshot_memory_failure_is_sticky_and_preserves_same_exception(effects, monkeypatch, fault):
    journal = effects.SceneNativeEffects((phase(effects),))
    journal.rows[0].calls[0].entered = journal.rows[0].calls[0].returned = True
    journal.status.sealed = True
    original, failure = getattr(effects, fault), MemoryError("one allocation failed")

    def broken(*_args, **_kwargs):
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(effects, fault, broken)
        with pytest.raises(MemoryError) as caught:
            effects.snapshot_native_effects(journal)
        assert caught.value is failure
    assert getattr(effects, fault) is original
    result = effects.snapshot_native_effects(journal)
    assert result["evidence_incomplete"] and result["snapshot_allocation_failed"] and result["sealed"]
    assert result["counts_by_operation"]["frame_set"] == {"entered": 1, "returned": 1}


def test_call_return_is_retained_when_later_bookkeeping_fails(effects):
    journal = effects.SceneNativeEffects((phase(effects),))
    bits = journal.rows[0].calls[0]
    native_changes = []

    def callback():
        native_changes.append("frame changed")

    with pytest.raises(MemoryError):
        bits.entered = True
        callback()
        bits.returned = True
        raise MemoryError("post-return timing append")
    result = effects.snapshot_native_effects(journal)
    assert native_changes == ["frame changed"]
    assert result["counts_by_operation"]["frame_set"] == {"entered": 1, "returned": 1}
    assert result["last_verified"] is None
