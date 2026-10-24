"""Hand-derived storage/scope contracts for the private Blender-free UV planner."""

from __future__ import annotations

import copy
import importlib
import math
from dataclasses import FrozenInstanceError, replace

import pytest


@pytest.fixture
def kernel(addon_package):
    return importlib.import_module(f"{addon_package}.uv_edit_intent")


def records():
    first = [{"face": 0, "corner": 0, "vertex": 0, "edge": 0, "uv": [0., .25], "pin_uv": True},
             {"face": 0, "corner": 1, "vertex": 1, "edge": 1, "uv": [1., .25], "pin_uv": False},
             {"face": 1, "corner": 0, "vertex": 1, "edge": 2, "uv": [.5, .75], "pin_uv": False}]
    second = copy.deepcopy(first)
    for row in second:
        row["uv"] = [2., 3.]
        row["pin_uv"] = False
    return {"UV": first, "Protected": second}


def scope(snapshot):
    return [corner.key for corner in snapshot.maps[0].corners]


def error_code(kernel, callback, expected):
    with pytest.raises(kernel.BridgeError) as error:
        callback()
    assert error.value.code == expected


def test_decimal_rounding_signed_zero_and_pinned_coordinate_assignment_are_independent(kernel):
    snapshot = kernel.freeze_snapshot(records())
    plan = kernel.plan_edit(snapshot, "coordinates_set", "UV", {"updates": [
        {"face_index": 0, "corner_index": 0, "uv": [-0., .1]},
    ]}, scope(snapshot))
    target = plan.expected.maps[0].corners[0]
    assert target.uv == (-0., .10000000149011612)
    assert target.uv_bits == ("00000080", "cdcccc3d") and target.pin_uv is True
    assert plan.writes[0].requested_float64_le == ("0000000000000080", "9a9999999999b93f")
    assert plan.writes[0].uv_bits == target.uv_bits and plan.writes[0].pin_uv is None
    assert (plan.coordinate_changes, plan.pin_changes, plan.target_corners) == (1, 0, 1)
    assert plan.expected.maps[1] is snapshot.maps[1]
    assert plan.expected.maps[0].corners[1:] == snapshot.maps[0].corners[1:]
    assert snapshot.maps[0].corners[0].uv_bits == ("00000000", "0000803e")


def test_signed_zero_only_coordinate_write_is_a_real_changed_field(kernel):
    raw = records()
    raw["UV"][0]["uv"] = [0., 0.]
    snapshot = kernel.freeze_snapshot(raw)
    plan = kernel.plan_edit(snapshot, "coordinates_set", "UV", {"updates": [
        {"face_index": 0, "corner_index": 0, "uv": [-0., 0.]},
    ]}, scope(snapshot))
    assert plan.before.maps[0].corners[0].uv == plan.expected.maps[0].corners[0].uv
    assert plan.coordinate_changes == len(plan.writes) == 1
    assert plan.before.maps[0].corners[0].uv_bits != plan.expected.maps[0].corners[0].uv_bits


def test_hand_derived_quarter_turn_respects_pins_and_protected_scope(kernel):
    snapshot = kernel.freeze_snapshot(records())
    plan = kernel.plan_edit(snapshot, "transform", "UV", {
        "pivot": [1, 1], "scale": [2, 1], "rotation": math.pi / 2, "offset": [2, 3],
    }, scope(snapshot)[:2])
    assert plan.expected.maps[0].corners[1].uv == (3.75, 4.)
    assert plan.expected.maps[0].corners[1].uv_bits == ("00007040", "00008040")
    assert plan.expected.maps[0].corners[0] is snapshot.maps[0].corners[0]
    assert plan.expected.maps[0].corners[2] is snapshot.maps[0].corners[2]
    assert plan.expected.maps[1] is snapshot.maps[1]
    assert (plan.target_corners, plan.skipped_pinned_corners, plan.coordinate_changes) == (1, 1, 1)


def test_transform_rounds_pair_parameters_before_arithmetic(kernel):
    raw = records()
    raw["UV"][1]["uv"] = [0., 0.]
    snapshot = kernel.freeze_snapshot(raw)
    plan = kernel.plan_edit(snapshot, "transform", "UV", {"offset": [.1, .2], "corners": [
        {"face_index": 0, "corner_index": 1},
    ]}, scope(snapshot))
    pair = dict(plan.rounded_parameters)["offset"]
    assert pair.requested == (.1, .2)
    assert pair.requested_float64_le == ("9a9999999999b93f", "9a9999999999c93f")
    assert pair.rounded == (.10000000149011612, .20000000298023224)
    assert pair.rounded_float32_le == ("cdcccc3d", "cdcc4c3e")
    assert plan.expected.maps[0].corners[1].uv == pair.rounded


def test_transform_false_respect_pins_and_zero_sign_math_follow_existing_formula(kernel):
    raw = records()
    raw["UV"][0]["uv"] = [-0., 0.]
    snapshot = kernel.freeze_snapshot(raw)
    plan = kernel.plan_edit(snapshot, "transform", "UV", {"respect_pins": False}, scope(snapshot)[:1])
    assert plan.skipped_pinned_corners == 0 and plan.coordinate_changes == 1
    assert plan.expected.maps[0].corners[0].uv_bits == ("00000000", "00000000")
    assert plan.expected.maps[0].corners[0].pin_uv is True


def test_pin_writes_carry_no_coordinate_fields_and_repeated_pin_is_noop(kernel):
    snapshot = kernel.freeze_snapshot(records())
    plan = kernel.plan_edit(snapshot, "pin", "UV", {}, scope(snapshot))
    assert (plan.coordinate_changes, plan.pin_changes, len(plan.writes)) == (0, 2, 2)
    assert all(write.pin_uv is True and write.uv is write.uv_bits is write.requested_uv is write.requested_float64_le is None
               for write in plan.writes)
    assert [row.uv_bits for row in plan.expected.maps[0].corners] == [row.uv_bits for row in snapshot.maps[0].corners]
    repeated = kernel.plan_edit(plan.expected, "pin", "UV", {}, scope(snapshot))
    assert repeated.writes == () and repeated.pin_changes == repeated.coordinate_changes == 0
    skipped = kernel.plan_edit(plan.expected, "transform", "UV", {}, scope(snapshot))
    assert skipped.target_corners == 0 and skipped.skipped_pinned_corners == 3 and not skipped.writes


def test_snapshot_requests_scope_and_expected_values_are_deeply_detached(kernel):
    raw = records()
    snapshot = kernel.freeze_snapshot(raw)
    params = {"updates": [{"face_index": 0, "corner_index": 1, "uv": [.1, -0.]}]}
    keys = scope(snapshot)
    plan = kernel.plan_edit(snapshot, "coordinates_set", "UV", params, keys)
    original = repr(plan)
    raw["UV"][0]["uv"][0] = 99.
    params["updates"][0]["uv"][0] = 8.
    keys.clear()
    assert repr(plan) == original
    with pytest.raises(FrozenInstanceError):
        plan.coordinate_changes = 2
    with pytest.raises(TypeError):
        plan.expected.maps[0].corners[0].uv[0] = 2.
    error_code(kernel, lambda: replace(plan, parameters=["mutable"]), "INVALID_ARGUMENT")


def test_frozen_requested_parameter_bits_distinguish_zero_sign_and_plain_numeric_types(kernel):
    snapshot = kernel.freeze_snapshot(records())
    a = kernel.plan_edit(snapshot, "transform", "UV", {"offset": [0., 0.]}, scope(snapshot))
    b = kernel.plan_edit(snapshot, "transform", "UV", {"offset": [-0., 0.]}, scope(snapshot))
    c = kernel.plan_edit(snapshot, "transform", "UV", {"offset": [0, 0]}, scope(snapshot))
    assert a.requested_float64_le != b.requested_float64_le
    assert a.parameters != c.parameters and a.requested_float64_le != c.requested_float64_le


@pytest.mark.parametrize("value", [True, "1", None, object(), [1], [1, 2, 3]])
def test_malformed_coordinate_values_fail_before_any_plan(kernel, value):
    snapshot = kernel.freeze_snapshot(records())
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "coordinates_set", "UV", {"updates": [
        {"face_index": 0, "corner_index": 0, "uv": value},
    ]}, scope(snapshot)), "INVALID_ARGUMENT")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e7, -(10**1000)])
def test_request_numeric_public_range_errors_stay_invalid_argument(kernel, value):
    snapshot = kernel.freeze_snapshot(records())
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "transform", "UV", {"offset": [value, 0]}, scope(snapshot)), "INVALID_ARGUMENT")


@pytest.mark.parametrize("value", [.1, float("nan"), float("inf"), 1e-40, 1e-50, 1e7])
def test_unqualified_source_storage_is_never_silently_rounded_or_repaired(kernel, value):
    raw = records()
    raw["UV"][0]["uv"][0] = value
    error_code(kernel, lambda: kernel.freeze_snapshot(raw), "NOT_IMPLEMENTED")


def test_exact_source_normal_boundary_and_signed_zero_are_preserved(kernel):
    raw = records()
    raw["UV"][0]["uv"] = [2**-126, -0.]
    source = kernel.freeze_snapshot(raw).maps[0].corners[0]
    assert source.uv_bits == ("00008000", "00000080")


def test_subnormal_request_and_transformed_result_profiles_are_explicitly_unsupported(kernel):
    snapshot = kernel.freeze_snapshot(records())
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "transform", "UV", {"offset": [1e-40, 0]}, scope(snapshot)), "NOT_IMPLEMENTED")
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "transform", "UV", {"scale": [1e6, 1e6], "offset": [1, 0]}, scope(snapshot)), "NOT_IMPLEMENTED")


@pytest.mark.parametrize("name", ["", "bad\0name", "x" * 64, "é" * 32, "\ud800", 1])
def test_names_have_exact_utf8_bounds_without_normalization(kernel, name):
    error_code(kernel, lambda: kernel.freeze_snapshot({name: records()["UV"]}), "INVALID_ARGUMENT")


def test_distinct_unicode_names_remain_distinct_and_ordered(kernel):
    snapshot = kernel.freeze_snapshot({"é": records()["UV"], "e\u0301": records()["Protected"]})
    assert [layer.name for layer in snapshot.maps] == ["é", "e\u0301"]


@pytest.mark.parametrize("mutation", ["reordered", "missing", "different_vertex", "duplicate"])
def test_all_map_inventories_must_match_exact_ordered_four_index_keys(kernel, mutation):
    raw = records()
    if mutation == "reordered":
        raw["Protected"].reverse()
    elif mutation == "missing":
        raw["Protected"].pop()
    elif mutation == "different_vertex":
        raw["Protected"][0]["vertex"] = 9
    else:
        raw["Protected"][1] = copy.deepcopy(raw["Protected"][0])
    error_code(kernel, lambda: kernel.freeze_snapshot(raw), "INVALID_ARGUMENT")


@pytest.mark.parametrize("pin", [0, 1, None, "false"])
def test_native_pin_flags_must_be_actual_booleans(kernel, pin):
    raw = records()
    raw["UV"][0]["pin_uv"] = pin
    error_code(kernel, lambda: kernel.freeze_snapshot(raw), "INVALID_ARGUMENT")


def test_scope_and_update_keys_are_validated_before_planning(kernel):
    snapshot = kernel.freeze_snapshot(records())
    keys = scope(snapshot)
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "pin", "UV", {}, keys * 2), "INVALID_ARGUMENT")
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "pin", "UV", {}, [(0, 0, 99, 0)]), "INVALID_SELECTION")
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "coordinates_set", "UV", {"updates": [
        {"face_index": 1, "corner_index": 0, "uv": [0., 0.]},
    ]}, keys[:2]), "INVALID_SELECTION")
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "pin", "UV", {"corners": [
        {"face_index": True, "corner_index": 0},
    ]}, keys), "INVALID_ARGUMENT")
    update = {"face_index": 0, "corner_index": 0, "uv": [0., 0.]}
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "coordinates_set", "UV", {"updates": [update, update]}, keys), "INVALID_ARGUMENT")


def test_rejects_custom_containers_and_numbers_without_running_callbacks(kernel):
    class BadDict(dict):
        def items(self):
            raise AssertionError("custom callback")

    class BadFloat(float):
        def __float__(self):
            raise AssertionError("custom numeric callback")

    error_code(kernel, lambda: kernel.freeze_snapshot(BadDict(records())), "INVALID_ARGUMENT")
    snapshot = kernel.freeze_snapshot(records())
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "transform", "UV", BadDict(), scope(snapshot)), "INVALID_ARGUMENT")
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "transform", "UV", {"offset": [BadFloat(1), 0]}, scope(snapshot)), "INVALID_ARGUMENT")


def test_nonplain_dictionary_keys_are_rejected_before_hash_or_equality_callbacks(kernel):
    class Key:
        armed = False

        def __hash__(self):
            if self.armed:
                raise AssertionError("validation invoked a custom hash")
            return 17

    key = Key()
    bad = {key: 0}
    key.armed = True
    error_code(kernel, lambda: kernel.freeze_snapshot({"UV": [bad]}), "INVALID_ARGUMENT")
    snapshot = kernel.freeze_snapshot(records())
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "pin", "UV", {"corners": [bad]}, scope(snapshot)), "INVALID_ARGUMENT")


def test_value_record_constructors_reject_mutable_or_callback_bearing_payloads(kernel):
    class BadString(str):
        def __eq__(self, other):
            raise AssertionError("validation invoked custom equality")

    error_code(kernel, lambda: kernel.UVCorner((0, 0, 0, 0), (0., 0.),
        (BadString("00000000"), "00000000"), False), "INVALID_ARGUMENT")
    error_code(kernel, lambda: kernel.UVWrite((0, 0, 0, 0), uv=[0., 0.]), "INVALID_ARGUMENT")
    error_code(kernel, lambda: kernel.UVWrite((0, 0, 0, 0), pin_uv=True, requested_uv=(0., 0.)), "INVALID_ARGUMENT")


def large_snapshot(kernel):
    rows = [{"face": 0, "corner": i, "vertex": i, "edge": i, "uv": [0., 0.], "pin_uv": False} for i in range(512)]
    return kernel.freeze_snapshot({str(index): copy.deepcopy(rows) for index in range(8)})


def test_scalar_snapshot_value_times_write_budget_has_a_measured_boundary(kernel):
    snapshot = large_snapshot(kernel)
    updates = [{"face_index": 0, "corner_index": index, "uv": [.25, .5]} for index in range(171)]
    accepted = kernel.plan_edit(snapshot, "coordinates_set", "0", {"updates": updates[:170]}, scope(snapshot))
    assert accepted.snapshot_records == 4096 and accepted.snapshot_values == 12_288
    assert accepted.snapshot_write_product == 2_088_960
    error_code(kernel, lambda: kernel.plan_edit(snapshot, "coordinates_set", "0", {"updates": updates}, scope(snapshot)), "NOT_IMPLEMENTED")


def test_map_corner_and_plain_request_limits_are_bounded(kernel):
    rows = records()["UV"]
    error_code(kernel, lambda: kernel.freeze_snapshot({str(i): rows for i in range(9)}), "NOT_IMPLEMENTED")
    error_code(kernel, lambda: kernel.freeze_snapshot({"UV": rows * 171}), "NOT_IMPLEMENTED")
    snapshot = kernel.freeze_snapshot(records())
    for operation, params in (("pin", {"pinned": 1}), ("transform", {"respect_pins": 1}),
                              ("transform", {"rotation": math.tau * 1001}), ("pin", {"unknown": []})):
        error_code(kernel, lambda operation=operation, params=params: kernel.plan_edit(
            snapshot, operation, "UV", params, scope(snapshot)), "INVALID_ARGUMENT")
