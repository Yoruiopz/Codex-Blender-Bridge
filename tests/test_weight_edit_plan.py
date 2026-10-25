from __future__ import annotations

import importlib
import math
import struct
from dataclasses import FrozenInstanceError, replace

import pytest


@pytest.fixture
def plan(addon_package):
    return importlib.import_module(f"{addon_package}.weight_edit_plan")


@pytest.fixture
def snapshot(plan):
    groups = (plan.GroupState(0, "A", 101, False), plan.GroupState(1, "B", 102, False),
              plan.GroupState(2, "Locked", 103, True))
    fields = (((0, 0.25), (1, 0.5), (2, 0.125)), ((0, 0.0), (2, 0.25)), ((1, 1.0),), ())
    return plan.MembershipSnapshot(groups, tuple(
        tuple((group, plan.f32_bits(value)) for group, value in row) for row in fields
    ))


def assign(**kwargs):
    return {"object_name": "Target", "group_name": "A", "vertex_indices": [0],
            "weight": 0.75, **kwargs}


def normalize(**kwargs):
    return {"object_name": "Target", "group_names": ["A", "B"], "vertex_indices": [0],
            **kwargs}


def test_pure_module_import_does_not_load_blender(plan, monkeypatch):
    import builtins

    original = builtins.__import__

    def checked(name, *args, **kwargs):
        if name in {"bpy", "bmesh", "mathutils"}:
            pytest.fail("Pure planner imported a Blender runtime")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked)
    assert importlib.reload(plan).WeightPlanError.__base__ is ValueError


def test_assign_preserves_unwritten_memberships_and_original(plan, snapshot):
    original = plan.digest(snapshot)
    result = plan.plan_edit(snapshot, "weights.assign", assign(vertex_indices=[2, 0], weight=0.1))
    expected_bits = struct.pack("<f", 0.1).hex()
    assert [field.vertex for field in result.writes] == [2, 0]
    assert [field.before for field in result.writes] == [None, "0000803e"]
    assert all(field.after == expected_bits for field in result.writes)
    assert result.requested_memberships == 2
    assert plan.membership(result.expected, 0, 2) == plan.f32_bits(0.125)
    assert result.expected.memberships[1] == snapshot.memberships[1]
    assert result.expected.memberships[3] == snapshot.memberships[3]
    assert plan.digest(snapshot) == original and result.before is snapshot


def test_remove_does_not_create_absent_memberships_or_rewrite_other_groups(plan, snapshot):
    result = plan.plan_edit(snapshot, "weights.assign", assign(vertex_indices=[3, 0], weight=None))
    assert result.requested_memberships == 2
    assert len(result.writes) == 1 and result.writes[0].vertex == 0
    assert result.writes[0].after is None
    assert plan.membership(result.expected, 0, 0) is None
    assert result.expected.memberships[3] == ()
    assert result.expected.memberships[0] == snapshot.memberships[0][1:]


def test_signed_zero_is_distinct_from_positive_zero_and_absence(plan, snapshot):
    negative = plan.replace_member(snapshot, 1, 0, plan.f32_bits(-0.0))
    assert plan.membership(negative, 1, 0) == "00000080"
    no_op = plan.plan_edit(negative, "weights.assign", assign(vertex_indices=[1], weight=-0.0))
    assert no_op.writes == () and no_op.requested_memberships == 1
    changed = plan.plan_edit(negative, "weights.assign", assign(vertex_indices=[1], weight=0.0))
    assert len(changed.writes) == 1 and changed.writes[0].after == "00000000"
    removed = plan.plan_edit(negative, "weights.assign", assign(vertex_indices=[1], weight=None))
    assert removed.writes[0].after is None
    assert len({plan.digest(s) for s in (negative, changed.expected, removed.expected)}) == 3


def test_normalization_uses_original_values_and_preserves_untouched_total(plan, snapshot):
    result = plan.plan_edit(snapshot, "weights.normalize", normalize(group_names=["B", "A"]))
    assert [field.group.index for field in result.writes] == [1, 0]
    assert result.requested_memberships == 2
    # Independent arithmetic uses the literal original values and the protected .125.
    assert plan.membership(result.expected, 0, 1) == struct.pack("<f", (0.5 / 0.75) * 0.875).hex()
    assert plan.membership(result.expected, 0, 0) == struct.pack("<f", (0.25 / 0.75) * 0.875).hex()
    assert plan.membership(result.expected, 0, 2) == "0000003e"
    assert result.expected.memberships[1:] == snapshot.memberships[1:]


def test_normalization_does_not_create_missing_selected_groups(plan, snapshot):
    result = plan.plan_edit(snapshot, "weights.normalize", normalize(vertex_indices=[2]))
    assert result.requested_memberships == 1
    assert result.writes == () and result.expected == snapshot
    assert plan.membership(result.expected, 2, 0) is None


def test_owned_prefixes_and_reverse_original_values_reconstruct_exact_original(plan, snapshot):
    result = plan.plan_edit(snapshot, "weights.assign", assign(vertex_indices=[0, 1, 2, 3]))
    current = snapshot
    for field in result.writes:
        assert plan.membership(current, field.vertex, field.group.index) == field.before
        current = plan.replace_member(current, field.vertex, field.group.index, field.after)
    assert current == result.expected
    for field in reversed(result.writes):
        current = plan.replace_member(current, field.vertex, field.group.index, field.before)
    assert current == snapshot and plan.digest(current) == plan.digest(snapshot)


def test_immutable_records_reject_mutation_and_snapshot_preserves_pointer_facts(plan, snapshot):
    result = plan.plan_edit(snapshot, "weights.assign", assign())
    with pytest.raises(FrozenInstanceError):
        result.writes[0].after = "00000000"
    with pytest.raises(FrozenInstanceError):
        snapshot.groups[0].pointer = 999
    replacement = replace(snapshot.groups[0], pointer=999)
    changed_group = replace(snapshot, groups=(replacement, *snapshot.groups[1:]))
    assert changed_group != snapshot
    assert plan.digest(changed_group) != plan.digest(snapshot)


@pytest.mark.parametrize("value", [True, False, "0.5", -0.001, 1.0001,
                                  float("nan"), float("inf"), -float("inf"),
                                  pytest.param(10**10_000, id="huge-int")])
def test_invalid_assign_values_fail_before_float_conversion(plan, snapshot, value):
    with pytest.raises(plan.WeightPlanError):
        plan.plan_edit(snapshot, "weights.assign", assign(weight=value))


@pytest.mark.parametrize("bits", ["0000807f", "0000c07f", "000080bf", "0000803F", "", "00", 0, None])
def test_invalid_stored_float_bits_are_refused(plan, snapshot, bits):
    damaged = replace(snapshot, memberships=(((0, bits),), *snapshot.memberships[1:]))
    with pytest.raises(plan.WeightPlanError):
        plan.validate_snapshot(damaged)


@pytest.mark.parametrize("indices", [[], [0, 0], [True], [-1], [4], [0.0], (0,), list(range(1001))])
def test_indices_remain_explicit_unique_bounded_and_in_range(plan, snapshot, indices):
    with pytest.raises(plan.WeightPlanError):
        plan.plan_edit(snapshot, "weights.assign", assign(vertex_indices=indices))


@pytest.mark.parametrize("kwargs", [dict(group_name="Missing"), dict(group_name="Locked"),
                                    dict(group_name=""), dict(object_name=""),
                                    dict(object_name="x\x00"), dict(object_name="\ud800"),
                                    dict(object_name="😀" * 16)])
def test_literal_target_names_and_locks_are_enforced(plan, snapshot, kwargs):
    with pytest.raises(plan.WeightPlanError):
        plan.plan_edit(snapshot, "weights.assign", assign(**kwargs))


@pytest.mark.parametrize("names", [[], ["A", "A"], ["Missing"], ["Locked"], [1], ("A",),
                                 ["A"] * 33])
def test_normalize_target_groups_must_be_exact_unlocked_existing_names(plan, snapshot, names):
    with pytest.raises(plan.WeightPlanError):
        plan.plan_edit(snapshot, "weights.normalize", normalize(group_names=names))


def test_zero_selected_total_and_excess_untouched_total_are_refused(plan, snapshot):
    with pytest.raises(plan.WeightPlanError, match="zero"):
        plan.plan_edit(snapshot, "weights.normalize", normalize(vertex_indices=[1]))
    excessive = plan.replace_member(snapshot, 0, 1, plan.f32_bits(1))
    excessive = plan.replace_member(excessive, 0, 2, plan.f32_bits(1))
    with pytest.raises(plan.WeightPlanError, match="untouched"):
        plan.plan_edit(excessive, "weights.normalize", normalize(group_names=["A"]))


@pytest.mark.parametrize("members", [((0, "00000000"), (0, "0000803f")),
                                    ((1, "00000000"), (0, "0000803f")),
                                    ((3, "00000000"),), ((False, "00000000"),),
                                    ([0, "00000000"],)])
def test_snapshot_rejects_duplicate_unknown_unordered_or_mutable_members(plan, snapshot, members):
    with pytest.raises(plan.WeightPlanError):
        plan.validate_snapshot(replace(snapshot, memberships=(members, *snapshot.memberships[1:])))


@pytest.mark.parametrize("change", [dict(index=4), dict(pointer=0), dict(pointer=True),
                                   dict(locked=1), dict(name="B"), dict(pointer=102),
                                   dict(pointer=2**64), pytest.param(dict(pointer=10**10_000), id="huge-pointer")])
def test_snapshot_group_inventory_cannot_lose_identity_lock_or_uniqueness(plan, snapshot, change):
    group = replace(snapshot.groups[0], **change)
    with pytest.raises(plan.WeightPlanError):
        plan.validate_snapshot(replace(snapshot, groups=(group, *snapshot.groups[1:])))


def test_snapshot_and_changed_write_limits_are_independent(plan, snapshot):
    with pytest.raises(plan.WeightPlanError):
        plan.validate_snapshot(replace(snapshot, memberships=((),) * 513))
    many = replace(snapshot, memberships=((),) * 257)
    with pytest.raises(plan.WeightPlanError, match="Changed membership"):
        plan.plan_edit(many, "weights.assign", assign(vertex_indices=list(range(257))))
    no_op = replace(snapshot, memberships=(((0, plan.f32_bits(0.75)),),) * 512)
    result = plan.plan_edit(no_op, "weights.assign", assign(vertex_indices=list(range(512))))
    assert result.writes == () and result.requested_memberships == 512


def test_broader_guard_can_reserve_compensation_and_marker_work(plan):
    assert plan.comparison_budget(5000, 256, 0) == 7_865_536
    with pytest.raises(plan.WeightPlanError, match="Joint"):
        plan.comparison_budget(6000, 256, 0)
    with pytest.raises(plan.WeightPlanError, match="Joint"):
        plan.comparison_budget(65_536, 0, 200)
    for args in [(0, 1, 0), (65_537, 0, 0), (1, 257, 0), (1, 0, 201), (True, 0, 0)]:
        with pytest.raises(plan.WeightPlanError):
            plan.comparison_budget(*args)


def test_request_schema_and_method_are_unchanged_and_not_extended(plan, snapshot):
    for params in ({**assign(), "allow_shared": True}, {k: v for k, v in assign().items() if k != "weight"}):
        with pytest.raises(plan.WeightPlanError):
            plan.plan_edit(snapshot, "weights.assign", params)
    with pytest.raises(plan.WeightPlanError):
        plan.plan_edit(snapshot, "weights.smooth", assign())
    assert math.copysign(1, plan.f32_value(plan.f32_bits(-0.0))) == -1


@pytest.mark.parametrize("method,params", [
    ("weights.assign", assign(weight=None)),
    ("weights.assign", assign(weight=-0.0)),
    ("weights.assign", assign(vertex_indices=[0, 10_000_000])),
    ("weights.normalize", normalize()),
])
def test_plain_request_validation_precedes_native_range_and_group_readers(plan, method, params):
    assert plan.validate_request(method, params) is None


@pytest.mark.parametrize("method,params", [
    ("weights.smooth", assign()),
    ("weights.assign", {k: v for k, v in assign().items() if k != "weight"}),
    ("weights.assign", {**assign(), "allow_shared": True}),
    ("weights.assign", assign(weight=float("nan"))),
    ("weights.assign", assign(weight=True)),
    ("weights.assign", assign(vertex_indices=[])),
    ("weights.assign", assign(vertex_indices=[False])),
    ("weights.assign", assign(vertex_indices=[-1])),
    ("weights.assign", assign(vertex_indices=[0, 0])),
    ("weights.assign", assign(vertex_indices=[0.0])),
    ("weights.assign", assign(vertex_indices=(0,))),
    ("weights.assign", assign(object_name="")),
    ("weights.assign", assign(group_name="\x00")),
    ("weights.normalize", normalize(group_names=["A", "A"])),
    ("weights.normalize", normalize(group_names=["A"] * 33)),
    ("weights.normalize", normalize(group_names=("A",))),
])
def test_request_validation_refuses_invalid_shape_without_a_snapshot(plan, method, params):
    with pytest.raises(plan.WeightPlanError):
        plan.validate_request(method, params)


def test_plan_rejects_bad_request_before_observing_a_snapshot(plan, monkeypatch):
    monkeypatch.setattr(plan, "validate_snapshot", lambda _: pytest.fail("Snapshot was observed"))
    with pytest.raises(plan.WeightPlanError, match=r"weight|fields"):
        plan.plan_edit(object(), "weights.assign", {k: v for k, v in assign().items() if k != "weight"})
