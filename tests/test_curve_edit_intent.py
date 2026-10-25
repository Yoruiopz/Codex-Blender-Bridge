"""Independent whole-Action expectations for the Blender-free FREE-handle plan."""

from __future__ import annotations

import importlib
import math
import struct
from dataclasses import FrozenInstanceError

import pytest


@pytest.fixture
def kernel(addon_package):
    return importlib.import_module(f"{addon_package}.tools._curve_edit_intent")


def point(frame, *, left=None, right=None):
    return (
        ("co", (frame, 2.)), ("co_ui", (frame, 2.)),
        ("interpolation", "BEZIER"), ("easing", "AUTO"),
        ("handle_left_type", "FREE"), ("handle_right_type", "FREE"),
        ("handle_left", left if left is not None else (frame - .5, 1.)),
        ("handle_right", right if right is not None else (frame + .5, 3.)),
        ("select_control_point", True), ("type", "KEYFRAME"), ("amplitude", 0.),
    )


def action(*, points=None):
    return (
        (("name", "Authored"), ("use_frame_range", False), ("frame_start", -0.)),
        ((7, "OBSubject", True),),
        (("Layer", (("Strip", 1., 250.),)),),
        (
            (7, ((("data_path", "location"), ("array_index", 0),
                  ("extrapolation", "CONSTANT"), ("color", (.25, .5, .75))),
                 points if points is not None else (point(1.), point(3.), point(5.)), ())),
            (7, ((("data_path", "protected"), ("array_index", 1)),
                 ((('co', (1., 8.)), ("select_control_point", False)),),
                 (("NOISE", (("strength", .25),)),))),
        ),
        (("Marker", 12, True),),
        (("Group", (("lock", True), ("color", (.1, .2, .3)))),),
    )


def replace_point(state, index, **fields):
    """Test-owned reconstruction; no production replacement/comparison helper."""
    metadata, slots, layers, curves, markers, groups = state
    slot, (properties, points, modifiers) = curves[0]
    changed = tuple(tuple((name, fields.get(name, value)) for name, value in row)
                    if ordinal == index else row for ordinal, row in enumerate(points))
    return (metadata, slots, layers,
            ((slot, (properties, changed, modifiers)), *curves[1:]), markers, groups)


def replace_curve_properties(state, **fields):
    metadata, slots, layers, curves, markers, groups = state
    slot, (properties, points, modifiers) = curves[0]
    properties = tuple((name, fields.get(name, value)) for name, value in properties)
    return (metadata, slots, layers,
            ((slot, (properties, points, modifiers)), *curves[1:]), markers, groups)


def fail(kernel, invoke, code="NOT_IMPLEMENTED"):
    with pytest.raises(kernel.BridgeError) as caught:
        invoke()
    assert caught.value.code == code


def test_complete_prefixes_are_hand_predicted_and_preserve_other_action_fields(kernel):
    original = action()
    plan = kernel.plan_edit(original, 0, ((3., {
        "handle_right": [3.1, -0.], "co": [3., 9.],
    }), (1., {"handle_left": [-.1, 4.]})), None)
    states = [original]
    states.append(replace_point(states[-1], 1, co=(3., 9.), co_ui=(3., 9.)))
    states.append(replace_point(states[-1], 1, handle_right=(3.0999999046325684, -0.)))
    states.append(replace_point(states[-1], 0, handle_left=(-.10000000149011612, 4.)))
    assert [step.field for step in plan.steps] == ["co", "handle_right", "handle_left"]
    assert [step.frame for step in plan.steps] == [3., 3., 1.]
    for index, step in enumerate(plan.steps):
        assert step.before == states[index]
        assert step.expected == states[index+1]
        assert step.before is (plan.before if index == 0 else plan.steps[index-1].expected)
    assert plan.expected == states[-1]
    assert struct.pack("<ff", *plan.steps[1].value).hex() == "6666464000000080"
    assert plan.expected[0:3] == original[0:3]
    assert plan.expected[3][1:] == original[3][1:]
    assert plan.expected[4:] == original[4:]
    # co_ui changes only as the raw co getter's independently predicted alias.
    selected = dict(plan.expected[3][0][1][1][1])
    assert selected["co"] == selected["co_ui"] == (3., 9.)
    assert selected["handle_left"] == dict(original[3][0][1][1][1])["handle_left"]
    assert selected["select_control_point"] is True and selected["amplitude"] == 0.
    assert original == action()


@pytest.mark.parametrize(("first", "second"), [
    (0., -0.), (False, 0), (True, 1), (1, 1.), (1., 1.0000000000000002),
    (("x", (False,)), ("x", (0,))),
])
def test_exact_comparison_and_digest_distinguish_numeric_storage_types(kernel, first, second):
    assert not kernel.same(first, second)
    assert kernel.digest(first) != kernel.digest(second)
    assert kernel.same(first, first) and kernel.digest(first) == kernel.digest(first)
    assert len(kernel.digest(first)) == 64


def test_float32_noops_filter_before_prefixes_but_signed_zero_is_authored(kernel):
    original = action(points=(point(1., left=(.10000000149011612, 0.)),))
    noop = kernel.plan_edit(original, 0, ((1., {
        "handle_left": [.1, 0.], "co": [1., 2.],
    }),), None)
    assert noop.steps == () and noop.expected is noop.before
    changed = kernel.plan_edit(original, 0, ((1., {"handle_left": [.1, -0.]}),), None)
    assert len(changed.steps) == 1
    assert not kernel.same(changed.before, changed.expected)
    assert struct.pack("<ff", *changed.steps[0].value).hex() == "cdcccc3d00000080"


def test_plan_is_detached_from_mutable_requests_and_frozen(kernel):
    pair = [.1, 0.]
    fields = {"handle_left": pair}
    plan = kernel.plan_edit(action(), 0, ((1., fields),), None)
    remembered = kernel.digest(plan.expected)
    pair[:] = [999., 999.]
    fields.clear()
    assert kernel.digest(plan.expected) == remembered
    assert plan.steps[0].value == (.10000000149011612, 0.)
    with pytest.raises(FrozenInstanceError):
        plan.steps[0].value = ()
    with pytest.raises(FrozenInstanceError):
        plan.before = ()


@pytest.mark.parametrize(("part", "field", "replacement"), [
    (0, "handle_left_type", "AUTO"), (2, "handle_right_type", "ALIGNED"),
    (0, "co", (1., math.inf)), (0, "handle_left", (.1, 0.)),
    (0, "handle_right", (True, 0.)), (0, "handle_left", (1e-40, 0.)),
    (0, "co", (1., 1000001.)),
])
def test_source_profile_rejects_unsupported_authored_points(kernel, part, field, replacement):
    source = replace_point(action(), part, **{field: replacement})
    fail(kernel, lambda: kernel.plan_edit(source, 0, ((1., {"handle_left": [.5, 4.]}),), None))


@pytest.mark.parametrize("frames", [(1., 1.), (2., 1.), (-0., 0.)])
def test_all_source_times_must_be_strictly_sorted_and_unique(kernel, frames):
    source = action(points=tuple(point(frame) for frame in frames))
    fail(kernel, lambda: kernel.plan_edit(source, 0, (), "LINEAR"))


@pytest.mark.parametrize("first_bits,second_bits,gap_bits,supported", [
    ("00000000", "09d7233c", "09d7233c", False),  # Immediately below native 0.01f.
    ("00000000", "0ad7233c", "0ad7233c", False),  # Equality merges too.
    ("00000000", "0bd7233c", "0bd7233c", True),   # Immediately above it.
    ("000080af", "0ad7233c", "0ad7233c", False),  # -2^-32: double gap >0.01, float gap equals 0.01f.
    ("0ad723bc", "00000000", "0ad7233c", False),
])
def test_native_float32_deduplication_boundary_precedes_prefix_allocation(
    kernel, monkeypatch, first_bits, second_bits, gap_bits, supported,
):
    first, second = (struct.unpack("<f", bytes.fromhex(value))[0] for value in (first_bits, second_bits))
    assert first < second
    assert struct.pack("<f", second-first).hex() == gap_bits
    if first_bits == "000080af":
        assert second-first > .01  # A Python-double comparison would wrongly admit this pair.
    source = action(points=tuple(point(frame, left=(frame, 1.), right=(frame, 3.)) for frame in (first, second)))
    assert struct.pack("<f", kernel.NATIVE_KEYFRAME_MERGE_THRESHOLD).hex() == "0ad7233c"
    if supported:
        plan = kernel.plan_edit(source, 0, ((first, {"handle_left": [first, 4.]}),), None)
        assert kernel.same(plan.expected, replace_point(source, 0, handle_left=(first, 4.)))
    else:
        monkeypatch.setattr(kernel, "_replace_curve", lambda *_: pytest.fail("Deduplication preflight must precede prefixes"))
        fail(kernel, lambda: kernel.plan_edit(source, 0, (), "LINEAR"))


@pytest.mark.parametrize("index,fields", [
    (0, {"handle_left": (2., 1.)}),
    (0, {"handle_right": (0., 3.)}),
    (0, {"handle_left": (2., 1.), "handle_right": (0., 3.)}),
    (2, {"handle_left": (6., 1.)}),  # Also inspect unedited points.
    (2, {"handle_right": (4., 3.)}),
])
def test_source_free_handle_clamping_or_swapping_is_refused_before_prefixes(kernel, monkeypatch, index, fields):
    source = replace_point(action(), index, **fields)
    monkeypatch.setattr(kernel, "_replace_curve", lambda *_: pytest.fail("Every original handle must be preflighted"))
    fail(kernel, lambda: kernel.plan_edit(source, 0, ((1., {"handle_left": [.5, 4.]}),), None))


@pytest.mark.parametrize("fields", [
    {"handle_left": [2., 1.]}, {"handle_right": [0., 3.]},
    {"handle_left": [2., 1.], "handle_right": [0., 3.]},
    {"handle_left": [1.0000001192092896, 1.]},  # Adjacent binary32 value above the key.
    {"handle_right": [.9999999403953552, 3.]},  # Adjacent binary32 value below the key.
])
def test_requested_free_handle_clamping_or_swapping_is_refused_before_prefixes(kernel, monkeypatch, fields):
    monkeypatch.setattr(kernel, "_replace_curve", lambda *_: pytest.fail("Every request must be preflighted before prefixes"))
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((3., {"co": [3., 9.]}), (1., fields)), None))


def test_free_handle_boundary_and_requests_rounded_to_it_preserve_exact_predictions(kernel):
    source = action(points=(point(1., left=(1., 1.), right=(1., 3.)),))
    fail(kernel, lambda: kernel.plan_edit(source, 0, (), "LINEAR"))
    left, right = 1.+2.**-25, 1.-2.**-26
    assert left > 1. and right < 1.
    plan = kernel.plan_edit(source, 0, ((1., {"handle_left": [left, -0.], "handle_right": [right, 4.]}),), None)
    assert [step.value for step in plan.steps] == [(1., -0.), (1., 4.)]
    assert struct.pack("<ff", *plan.steps[0].value).hex() == "0000803f00000080"
    assert kernel.same(plan.expected, replace_point(source, 0, handle_left=(1., -0.), handle_right=(1., 4.)))


@pytest.mark.parametrize(("field", "value"), [("interpolation", "BACK"), ("easing", "UNKNOWN")])
def test_unedited_source_enum_outside_qualified_point_profile_is_refused(kernel, field, value):
    source = replace_point(action(), 2, **{field: value})
    # This point is unedited; the complete raw-point source profile still
    # requires every point to have reviewed interpolation/easing semantics.
    fail(kernel, lambda: kernel.plan_edit(source, 0, ((1., {"handle_left": [.5, 4.]}),), None))


def test_full_curve_modifier_inventory_is_not_adopted(kernel):
    source = action()
    slot, (props, points, _modifiers) = source[3][0]
    curves = ((slot, (props, points, (("NOISE",),))), *source[3][1:])
    source = (*source[:3], curves, *source[4:])
    fail(kernel, lambda: kernel.plan_edit(source, 0, (), "LINEAR"))


@pytest.mark.parametrize("source", [
    (), ((),)*6, ((), (), (), ((7, ()),), (), ()), [], (1, *action()[1:]),
])
def test_malformed_full_action_source_is_refused(kernel, source):
    fail(kernel, lambda: kernel.plan_edit(source, 0, (), "LINEAR"))


def test_missing_or_duplicate_source_properties_are_refused(kernel):
    original = action()
    for fields in [(*point(1.), ("co", (1., 2.))), point(1.)[1:]]:
        fail(kernel, lambda fields=fields: kernel.plan_edit(action(points=(fields,)), 0, (), "LINEAR"))
    malformed = replace_curve_properties(original, extrapolation=True)
    fail(kernel, lambda: kernel.plan_edit(malformed, 0, (), "LINEAR"))


class Adapter:
    def __iter__(self):
        raise AssertionError("Source adapters must never be called")

    def __float__(self):
        raise AssertionError("Numeric adapters must never be called")


class FloatAdapter(float):
    pass


@pytest.mark.parametrize("foreign", [Adapter(), FloatAdapter(1.), {}, [1.]])
def test_complete_source_rejects_adapters_and_mutable_foreign_values_without_access(kernel, foreign):
    source = (foreign, *action()[1:])
    fail(kernel, lambda: kernel.plan_edit(source, 0, (), "LINEAR"))


@pytest.mark.parametrize("ordinal", [True, -1, 2, 0., "0"])
def test_curve_selector_is_a_plain_existing_ordinal(kernel, ordinal):
    fail(kernel, lambda: kernel.plan_edit(action(), ordinal, (), "LINEAR"), "INVALID_ARGUMENT")


@pytest.mark.parametrize("prepared", [
    [], ((1, {"handle_left": [.5, 4.]}),), ([1., {"handle_left": [.5, 4.]}],),
    ((1., {}),), ((1., {"missing": 1}),), ((1., {True: "AUTO"}),),
    ((2., {"handle_left": [.5, 4.]}),), ((math.nan, {"handle_left": [.5, 4.]}),),
    ((.1, {"handle_left": [.5, 4.]}),),
    ((1., {"handle_left": [.5, 4.]}), (1., {"handle_right": [1.5, 4.]})),
])
def test_malformed_prepared_requests_are_invalid_arguments(kernel, prepared):
    fail(kernel, lambda: kernel.plan_edit(action(), 0, prepared, None), "INVALID_ARGUMENT")


def test_absent_fields_and_extrapolation_are_invalid(kernel):
    fail(kernel, lambda: kernel.plan_edit(action(), 0, (), None), "INVALID_ARGUMENT")


@pytest.mark.parametrize(("field", "value"), [
    ("interpolation", "AUTO"), ("easing", "LINEAR"), ("handle_left_type", "UNKNOWN"),
    ("interpolation", True), ("easing", Adapter()),
    ("handle_left", [True, 0.]), ("handle_left", [math.nan, 0.]),
    ("handle_right", [math.inf, 0.]), ("handle_left", [1000001., 0.]),
    ("handle_left", [FloatAdapter(1.), 0.]), ("handle_left", Adapter()),
    ("handle_right", [0.]),
])
def test_invalid_requested_types_or_enum_values_are_invalid_arguments(kernel, field, value):
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {field: value}),), None), "INVALID_ARGUMENT")


@pytest.mark.parametrize("handle_type", ["ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"])
def test_valid_nonfree_public_enum_is_explicitly_unsupported(kernel, handle_type):
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {"handle_left_type": handle_type}),), None))


def test_subnormal_result_profile_is_unsupported_and_signed_frame_is_exact(kernel):
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {"handle_left": [1e-40, 0.]}),), None))
    source = action(points=(point(-0.),))
    fail(kernel, lambda: kernel.plan_edit(source, 0, ((0., {"co": [0., 4.]}),), None), "INVALID_ARGUMENT")
    accepted = kernel.plan_edit(source, 0, ((-0., {"co": [-0., 4.]}),), None)
    assert struct.pack("<d", accepted.steps[0].frame).hex() == "0000000000000080"


@pytest.mark.parametrize("metadata", [2**65, "x"*4097, "é"*2049, "\ud800", math.inf])
def test_complete_snapshot_scalar_budgets_and_nonfinite_values_are_refused(kernel, metadata):
    fail(kernel, lambda: kernel.plan_edit((metadata, *action()[1:]), 0, (), "LINEAR"))


def test_item_and_depth_limits_are_enforced_before_any_prefix(kernel, monkeypatch):
    def forbidden(*_args):
        raise AssertionError("No prefix may be constructed before complete preflight")

    monkeypatch.setattr(kernel, "_replace_curve", forbidden)
    deep = 0
    for _ in range(34):
        deep = (deep,)
    fail(kernel, lambda: kernel.plan_edit((deep, *action()[1:]), 0, (), "LINEAR"))
    monkeypatch.setattr(kernel, "MAX_ITEMS", 30)
    fail(kernel, lambda: kernel.plan_edit(action(), 0, (), "LINEAR"))


@pytest.mark.parametrize("limit", ["MAX_WORK", "MAX_STEPS"])
def test_joint_work_or_write_budget_refuses_before_full_prefix_allocation(kernel, monkeypatch, limit):
    def forbidden(*_args):
        raise AssertionError("No prefix may be constructed before complete preflight")

    monkeypatch.setattr(kernel, "_replace_curve", forbidden)
    monkeypatch.setattr(kernel, limit, 1)
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {
        "co": [1., 4.], "handle_left": [.5, 4.],
    }),), None))


def test_source_point_and_request_record_counts_are_separate_finite_limits(kernel, monkeypatch):
    monkeypatch.setattr(kernel, "MAX_POINTS", 2)
    fail(kernel, lambda: kernel.plan_edit(action(), 0, (), "LINEAR"))
    monkeypatch.setattr(kernel, "MAX_POINTS", 1024)
    monkeypatch.setattr(kernel, "MAX_EDITS", 0)
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {"easing": "AUTO"}),), None), "INVALID_ARGUMENT")


def test_drift_anywhere_in_the_complete_action_is_refused_by_prefix_comparison(kernel):
    plan = kernel.plan_edit(action(), 0, ((1., {"co": [1., 4.]}),), None)
    owned_drift = replace_point(plan.expected, 1, handle_left=(42., 1.))
    protected_drift = (*plan.expected[:4], (("Marker", 13, True),), plan.expected[5])
    type_drift = ((("name", "Authored"), ("use_frame_range", 0), ("frame_start", -0.)),
                  *plan.expected[1:])
    assert not kernel.same(plan.expected, owned_drift)
    assert not kernel.same(plan.expected, protected_drift)
    assert not kernel.same(plan.expected, type_drift)
    assert kernel.same(plan.steps[0].before, action())
    assert kernel.same(plan.steps[0].expected, plan.expected)


def test_comparison_and_digest_reject_foreign_observation_without_adapters(kernel):
    fail(kernel, lambda: kernel.same(action(), Adapter()))
    fail(kernel, lambda: kernel.digest(Adapter()))


@pytest.mark.parametrize("field,value", [
    ("interpolation", "BEZIER"), ("interpolation", "LINEAR"),
    ("easing", "AUTO"), ("easing", "EASE_IN"),
    ("handle_left_type", "FREE"), ("handle_right_type", "FREE"),
])
def test_valid_public_enum_requests_including_noops_are_explicit_profile_refusals(
    kernel, monkeypatch, field, value,
):
    monkeypatch.setattr(kernel, "_replace_curve", lambda *_: pytest.fail("No prefix for enum profile"))
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {field: value}),), None))


@pytest.mark.parametrize("extrapolation", ["CONSTANT", "LINEAR"])
def test_extrapolation_even_if_unchanged_cannot_enter_point_only_prefixes(kernel, monkeypatch, extrapolation):
    monkeypatch.setattr(kernel, "_replace_curve", lambda *_: pytest.fail("No prefix for curve update"))
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {"co": [1., 9.]}),), extrapolation))


@pytest.mark.parametrize("changed_x", [0., 2., 1.0000001192092896])
def test_time_changes_are_unsupported_even_when_remaining_sorted(kernel, monkeypatch, changed_x):
    monkeypatch.setattr(kernel, "_replace_curve", lambda *_: pytest.fail("No prefix may relocate keys"))
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {"co": [changed_x, 9.]}),), None))


@pytest.mark.parametrize("frame,requested_x", [(0., -0.), (-0., 0.)])
def test_control_point_x_preserves_signed_zero_frame_bits(kernel, frame, requested_x):
    source = action(points=(point(frame),))
    fail(kernel, lambda: kernel.plan_edit(source, 0, ((frame, {"co": [requested_x, 9.]}),), None))


def test_control_point_value_signed_zero_updates_both_read_aliases_and_no_handles(kernel):
    original = replace_point(action(), 1, co=(3., 0.), co_ui=(3., 0.))
    plan = kernel.plan_edit(original, 0, ((3., {"co": [3., -0.]}),), None)
    expected = replace_point(original, 1, co=(3., -0.), co_ui=(3., -0.))
    assert len(plan.steps) == 1 and plan.steps[0].field == "co"
    assert plan.steps[0].frame == 3. and plan.steps[0].before == original
    assert kernel.same(plan.expected, expected) and not kernel.same(plan.before, plan.expected)
    row = dict(plan.expected[3][0][1][1][1])
    assert struct.pack("<ff", *row["co"]).hex() == struct.pack("<ff", *row["co_ui"]).hex() == "0000404000000080"
    assert row["handle_left"] == dict(original[3][0][1][1][1])["handle_left"]
    assert row["handle_right"] == dict(original[3][0][1][1][1])["handle_right"]


def test_control_point_reads_must_start_with_complete_exact_native_alias(kernel, monkeypatch):
    original = action()
    bad_aliases = [
        replace_point(original, 1, co_ui=(3., 4.)),
        replace_point(original, 1, co=(3., -0.), co_ui=(3., 0.)),
        replace_point(original, 1, co_ui=(3., .1)),
    ]
    slot, (properties, points, modifiers) = original[3][0]
    missing = tuple(tuple((name, value) for name, value in row if name != "co_ui")
                    if index == 1 else row for index, row in enumerate(points))
    bad_aliases.append((*original[:3], ((slot, (properties, missing, modifiers)), *original[3][1:]), *original[4:]))
    monkeypatch.setattr(kernel, "_replace_curve", lambda *_: pytest.fail("Source alias must preflight"))
    for source in bad_aliases:
        fail(kernel, lambda source=source: kernel.plan_edit(source, 0, ((1., {"handle_left": [.5, 4.]}),), None))


def test_retained_original_fields_form_independent_inverse_point_prefixes(kernel):
    original = action()
    changed = kernel.plan_edit(original, 0, ((3., {
        "co": [3., 9.], "handle_left": [2., -0.], "handle_right": [4., 12.],
    }),), None)
    inverse = kernel.plan_edit(changed.expected, 0, ((3., {
        "co": [3., 2.], "handle_left": [2.5, 1.], "handle_right": [3.5, 3.],
    }),), None)
    inverse_expected = [changed.expected]
    inverse_expected.append(replace_point(inverse_expected[-1], 1, co=(3., 2.), co_ui=(3., 2.)))
    inverse_expected.append(replace_point(inverse_expected[-1], 1, handle_left=(2.5, 1.)))
    inverse_expected.append(replace_point(inverse_expected[-1], 1, handle_right=(3.5, 3.)))
    assert [step.field for step in inverse.steps] == ["co", "handle_left", "handle_right"]
    for index, step in enumerate(inverse.steps):
        assert kernel.same(step.before, inverse_expected[index])
        assert kernel.same(step.expected, inverse_expected[index + 1])
    assert kernel.same(inverse.expected, original)
    assert kernel.same(changed.before, original)
    # Pure inverse data is not permission, recovery authority or native identity proof.
    assert not hasattr(inverse, "permission") and not hasattr(inverse, "native_target")


@pytest.mark.parametrize("value", [True, math.nan, math.inf, 1000001., FloatAdapter(1.), Adapter()])
def test_control_point_value_requires_plain_bounded_finite_numeric_input(kernel, value):
    fail(kernel, lambda: kernel.plan_edit(action(), 0, ((1., {"co": [1., value]}),), None), "INVALID_ARGUMENT")


def test_control_point_noop_filter_uses_rounded_float32_storage(kernel):
    original = replace_point(action(), 1, co=(3., .10000000149011612), co_ui=(3., .10000000149011612))
    plan = kernel.plan_edit(original, 0, ((3., {"co": [3., .1]}),), None)
    assert plan.steps == () and plan.expected is plan.before
    fail(kernel, lambda: kernel.plan_edit(original, 0, ((3., {"co": [3., 1e-40]}),), None))
