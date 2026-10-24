"""Independent WXYZ assignment intent without mode conversion or normalization."""

from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError

import pytest
from test_artist_target_intent import intent_case as intent_case

ROOT_HALF = math.sqrt(.5)
FLOAT32_ROOT_HALF = .7071067690849304
CASES = [
    ([1., -0., 0., -0.], (1., -0., 0., -0.), ("0000803f", "00000080", "00000000", "00000080")),
    ([ROOT_HALF, ROOT_HALF, -0., 0.], (FLOAT32_ROOT_HALF, FLOAT32_ROOT_HALF, -0., 0.),
     ("f304353f", "f304353f", "00000080", "00000000")),
    ([ROOT_HALF, 0., ROOT_HALF, -0.], (FLOAT32_ROOT_HALF, 0., FLOAT32_ROOT_HALF, -0.),
     ("f304353f", "00000000", "f304353f", "00000080")),
    ([ROOT_HALF, -0., 0., ROOT_HALF], (FLOAT32_ROOT_HALF, -0., 0., FLOAT32_ROOT_HALF),
     ("f304353f", "00000080", "00000000", "f304353f")),
    ([-ROOT_HALF, -0., -ROOT_HALF, 0.], (-FLOAT32_ROOT_HALF, -0., -FLOAT32_ROOT_HALF, 0.),
     ("f30435bf", "00000080", "f30435bf", "00000000")),
    ([.5, -.5, .5, -.5], (.5, -.5, .5, -.5), ("0000003f", "000000bf", "0000003f", "000000bf")),
    ([value / math.sqrt(30.) for value in (1., 2., 3., 4.)],
     (.18257418274879456, .3651483654975891, .547722578048706, .7302967309951782),
     ("baf43a3e", "baf4ba3e", "8c370c3f", "baf43a3f")),
]


@pytest.fixture
def quaternion_case(intent_case):
    case = intent_case
    case.obj.rotation_mode = "QUATERNION"
    case.obj.location = (.125, -.25, .5)
    case.obj.scale = (1.25, -.75, 2.5)
    case.obj.rotation_euler = (.125, -0., .5)
    case.obj.rotation_axis_angle = (.75, 1., -0., 0.)
    case.obj._reads.clear()
    case.obj._writes.clear()
    return case


@pytest.mark.parametrize(("requested", "expected", "encoded"), CASES)
def test_wxyz_expectation_uses_fixed_float32_values_and_bits_without_touching_other_channels(
        quaternion_case, requested, expected, encoded):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=requested)
    assert intent.availability == "available" and intent.reason is None
    assert dict(intent.expected_channels)["rotation_quaternion"] == expected
    assert dict(intent.expected_bits)["rotation_quaternion"] == encoded
    assert intent.requested_fields == ("rotation_quaternion",)
    for field in case.module.CORE_FIELDS:
        if field != "rotation_quaternion":
            assert dict(intent.expected_channels)[field] == dict(intent.before_channels)[field]
            assert dict(intent.expected_bits)[field] == dict(intent.before_bits)[field]
    assert dict(intent.before_bits)["rotation_euler"][1] == "00000080"
    assert dict(intent.before_bits)["rotation_axis_angle"][2] == "00000080"
    assert intent.object_name == "Working" and intent.session_uid == 5 and intent.pointer == 100
    assert not case.obj._writes
    case.obj.rotation_quaternion = expected  # Fixed literal native-storage stand-in, never adopted from intent.
    case.obj._writes.clear()
    result = case.module.compare_target(intent, case.module.read_target(case.bpy, intent))
    assert result["status"] == "channels_match" and result["differences"] == []
    assert not case.obj._writes


def test_near_unit_input_is_rounded_without_renormalizing_it(quaternion_case):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=[.9999991, 0., 0., -0.])
    assert intent.availability == "available"
    assert dict(intent.expected_channels)["rotation_quaternion"] == (.9999991059303284, 0., 0., -0.)
    assert dict(intent.expected_channels)["rotation_quaternion"][0] != 1.
    assert dict(intent.expected_bits)["rotation_quaternion"][-1] == "00000080"
    assert not case.obj._writes


def test_rounding_must_not_move_an_accepted_raw_norm_outside_the_profile(quaternion_case):
    case = quaternion_case
    requested = .99999901
    assert abs(requested - 1.) < 1e-6
    intent = case.capture(rotation_quaternion=[requested, 0., 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "quaternion_rounded_norm_outside_profile"
    assert not intent.expected_channels and not intent.expected_bits and not case.obj._writes


def test_quaternion_and_position_scale_predictions_are_independent_and_keep_existing_field_order(quaternion_case):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=[1., -0., 0., -0.], scale=[-2., .5, 1.25], location=[.1, .2, -0.])
    assert intent.availability == "available"
    assert intent.requested_fields == ("location", "scale", "rotation_quaternion")
    assert dict(intent.expected_channels)["location"] == (13421773 / 134217728, 13421773 / 67108864, -0.)
    assert dict(intent.expected_bits)["location"] == ("cdcccc3d", "cdcc4c3e", "00000080")
    assert dict(intent.expected_bits)["rotation_quaternion"] == ("0000803f", "00000080", "00000000", "00000080")
    assert dict(intent.expected_channels)["scale"] == (-2., .5, 1.25)
    assert dict(intent.expected_channels)["rotation_mode"] == "QUATERNION"
    assert not case.obj._writes


def test_original_inputs_and_later_native_changes_cannot_replace_retained_intent(quaternion_case):
    case = quaternion_case
    params = {"rotation_quaternion": [ROOT_HALF, 0., ROOT_HALF, -0.]}
    intent = case.module.capture_intent(case.bpy, case.obj, params)
    params["rotation_quaternion"][:] = [1., 0., 0., 0.]
    case.obj.rotation_quaternion = (-FLOAT32_ROOT_HALF, -0., -FLOAT32_ROOT_HALF, 0.)
    case.obj._writes.clear()
    assert dict(intent.expected_bits)["rotation_quaternion"] == ("f304353f", "00000000", "f304353f", "00000080")
    result = case.module.compare_target(intent, case.module.read_target(case.bpy, intent))
    assert result["status"] == "channels_differ"
    assert result["differences"][0]["field"] == "rotation_quaternion"
    assert result["differences"][0]["different_components"] == [0, 1, 2, 3]
    with pytest.raises(FrozenInstanceError):
        intent.expected_channels = ()
    assert not case.obj._writes


def test_signed_zero_changes_are_detected_even_when_quaternion_values_compare_equal(quaternion_case):
    case = quaternion_case
    positive = case.capture(rotation_quaternion=[1., 0., 0., 0.])
    negative = case.capture(rotation_quaternion=[1., -0., 0., 0.])
    assert positive.expected_channels == negative.expected_channels and positive != negative
    case.obj.rotation_quaternion = (1., 0., 0., 0.)
    case.obj._writes.clear()
    result = case.module.compare_target(negative, case.module.read_target(case.bpy, negative))
    assert result["status"] == "channels_differ"
    assert result["differences"][0]["different_components"] == [1]
    assert not case.obj._writes


@pytest.mark.parametrize("mode", ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX", "AXIS_ANGLE"])
def test_quaternion_never_predicts_an_existing_mode_conversion(quaternion_case, mode):
    case = quaternion_case
    case.obj.rotation_mode = mode
    case.obj._writes.clear()
    intent = case.capture(rotation_quaternion=[1., 0., 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "quaternion_existing_mode_required"
    assert not case.obj._writes


@pytest.mark.parametrize("conflict", [
    {"rotation": [0., 0., 0.]}, {"rotation_euler": [0., 0., 0.]},
    {"rotation_mode": "QUATERNION"}, {"rotation_mode": "XYZ"},
])
def test_any_euler_or_mode_argument_conflicts_with_quaternion_prediction(quaternion_case, conflict):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=[1., 0., 0., 0.], **conflict)
    assert intent.availability == "unavailable" and intent.reason == "quaternion_rotation_arguments_conflict"
    assert not intent.expected_channels and not case.obj._writes


@pytest.mark.parametrize("requested", [None, "1,0,0,0", [], [1., 0., 0.], [1., 0., 0., 0., 0.]])
def test_malformed_vector_is_unavailable_without_partial_intent(quaternion_case, requested):
    case = quaternion_case
    intent = case.capture(location=[1., 2., 3.], rotation_quaternion=requested)
    assert intent.availability == "unavailable" and intent.reason == "unqualified_requested_vector:rotation_quaternion"
    assert not intent.expected_channels and not intent.expected_bits and not case.obj._writes


@pytest.mark.parametrize("value", [True, "1", None, math.inf, math.nan, 1 << 2000])
def test_component_values_require_exact_finite_numbers(quaternion_case, value):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=[value, 0., 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "unqualified_requested_number:rotation_quaternion"
    assert not case.obj._writes


@pytest.mark.parametrize("base", [int, float])
def test_numeric_subclasses_are_refused_without_running_conversion_callbacks(quaternion_case, base):
    class NumericSubclass(base):
        def __float__(self):
            raise AssertionError("A retained request must not invoke numeric conversion callbacks")

    case = quaternion_case
    intent = case.capture(rotation_quaternion=[NumericSubclass(1), 0., 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "unqualified_requested_number:rotation_quaternion"
    assert not case.obj._writes


@pytest.mark.parametrize("requested", [[0., 0., 0., 0.], [.5, 0., 0., 0.], [.1, .2, .3, .4]])
def test_nonunit_values_are_not_normalized_to_manufacture_available_expectations(quaternion_case, requested):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=requested)
    assert intent.availability == "unavailable" and intent.reason == "quaternion_norm_outside_profile"
    assert not case.obj._writes


@pytest.mark.parametrize("value", [1.000001, -1.000001])
def test_component_magnitude_bound_applies_even_with_near_unit_norm(quaternion_case, value):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=[value, 0., 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "quaternion_component_outside_profile"
    assert not case.obj._writes


@pytest.mark.parametrize("value", [1e-40, -1e-40, 2.**-126 * (1 - 2.**-30)])
def test_subnormal_raw_components_are_not_silently_rounded_into_the_profile(quaternion_case, value):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=[1., value, 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "subnormal_value_outside_profile"
    assert not case.obj._writes


def test_minimum_normal_component_is_accepted_with_qualified_unit_norm(quaternion_case):
    case = quaternion_case
    intent = case.capture(rotation_quaternion=[1., 2.**-126, 0., -0.])
    assert intent.availability == "available"
    assert dict(intent.expected_bits)["rotation_quaternion"] == ("0000803f", "00008000", "00000000", "00000080")
    assert not case.obj._writes


def test_quaternion_descriptor_clamping_is_not_predicted_as_success(quaternion_case):
    case = quaternion_case
    case.properties["rotation_quaternion"].hard_max = .75
    intent = case.capture(rotation_quaternion=[1., 0., 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "requested_native_clamping_unavailable:rotation_quaternion"
    assert not case.obj._writes


def test_quaternion_descriptor_failure_precedes_all_native_channel_getters(quaternion_case):
    case = quaternion_case
    case.properties["rotation_quaternion"].is_runtime = True
    case.obj._traps.update(case.module.CORE_FIELDS)
    intent = case.capture(rotation_quaternion=[1., 0., 0., 0.])
    assert intent.availability == "unavailable" and intent.reason == "native_descriptor_unavailable:rotation_quaternion"
    assert not case.obj._reads and not case.obj._writes


def test_public_quaternion_intent_keeps_the_existing_profile_and_historical_scope(quaternion_case):
    case = quaternion_case
    public = case.module.public_intent(case.capture(rotation_quaternion=[1., -0., 0., -0.]))
    assert public["profile"] == "OBJECT_CORE_CHANNELS_FLOAT32_V1"
    assert public["scope"] == "authored_core_transform_channels"
    assert public["compared_fields"] == list(case.module.CORE_FIELDS)
    assert public["requested_fields"] == ["rotation_quaternion"]
    assert public["user_goal_verified"] is public["scene_evaluated"] is public["includes_parent_or_delta_transforms"] is False
    assert json.loads(json.dumps(public, allow_nan=False)) == public
    assert not case.obj._writes
