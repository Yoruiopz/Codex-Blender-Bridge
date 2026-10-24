from __future__ import annotations

import copy
import importlib
import json
import struct
from types import SimpleNamespace as NS

import pytest


def point(frame, value):
    return NS(co=[float(frame), float(value)], interpolation="LINEAR",
              handle_left=[float(frame) - .5, float(value)],
              handle_right=[float(frame) + .5, float(value)])


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.animation_curve_sampling")
    calls = []

    def evaluate(frame):
        calls.append(("evaluate", frame))
        return frame * 2 + 1

    def update():
        raise AssertionError("Read-only sampling must not normalize stored data")

    curve = NS(data_path="location", array_index=0, group=NS(name="Movement"), mute=True, lock=True,
               extrapolation="LINEAR", keyframe_points=[point(1, 3), point(11, 23)],
               sampled_points=[], modifiers=[], driver=None, update=update, evaluate=evaluate)
    action = NS(name="Walk", fcurves=[curve], is_action_layered=False, users=2,
                library=None, override_library=None, is_editable=True)
    obj = NS(name="Actor", animation_data=NS(action=action, use_tweak_mode=False),
             library=None, override_library=None, is_editable=True)

    def get_object(name, *, allow_active):
        assert name == "Actor" and allow_active is False
        calls.append("get_object")
        return obj

    monkeypatch.setattr(mod, "get_object", get_object)
    return mod, obj, action, curve, calls


def sample(fixture, *, context=None, **params):
    return fixture[0].curve_sample(context, {"object_name": "Actor", "data_path": "location", "frames": [1, 6], **params})


def test_raw_values_preserve_order_duplicates_and_all_stored_state(fixture):
    _, obj, action, curve, calls = fixture
    before = copy.deepcopy((vars(obj), vars(action), vars(curve)))
    result = sample(fixture, frames=[11, 1, 6, 1])
    assert result == {
        "object": "Actor", "action": "Walk", "slot_identifier": None,
        "data_path": "location", "index": 0, "group": "Movement", "mute": True, "lock": True,
        "extrapolation": "LINEAR", "point_count": 2, "sample_count": 4,
        "samples": [{"requested_frame": 11., "evaluated_frame": 11., "value": 23.},
                    {"requested_frame": 1., "evaluated_frame": 1., "value": 3.},
                    {"requested_frame": 6., "evaluated_frame": 6., "value": 13.},
                    {"requested_frame": 1., "evaluated_frame": 1., "value": 3.}],
        "evaluation_scope": "ACTIVE_ACTION_FCURVE", "scene_evaluated": False,
        "includes_nla": False, "includes_drivers": False, "includes_constraints": False, "includes_deformation": False,
    }
    json.dumps(result, allow_nan=False)
    assert (vars(obj), vars(action), vars(curve)) == before
    assert calls == ["get_object", ("evaluate", 11.), ("evaluate", 1.), ("evaluate", 6.), ("evaluate", 1.)]


def test_float32_effective_times_are_used_and_not_hidden(fixture):
    requested = 1.1
    expected = struct.unpack("!f", struct.pack("!f", requested))[0]
    assert requested != expected
    result = sample(fixture, frames=[requested])
    assert result["samples"] == [{"requested_frame": requested, "evaluated_frame": expected, "value": expected * 2 + 1}]
    assert fixture[4][-1] == ("evaluate", expected)


def test_supported_bounds_single_point_and_ungrouped_curve(fixture):
    _, _, _, curve, calls = fixture
    curve.keyframe_points, curve.group = [point(1, 3)], None
    result = sample(fixture, frames=[-1_000_000, 1_000_000] * 64)
    assert result["sample_count"] == 128 and result["point_count"] == 1 and result["group"] is None
    assert len(calls) == 129


@pytest.mark.parametrize("field,value", [
    ("users", 7), ("library", "linked.blend"), ("override_library", "override"), ("is_editable", False),
])
def test_shared_linked_noneditable_and_tweak_mode_data_can_be_read(fixture, field, value):
    _, obj, action, _, _ = fixture
    setattr(action, field, value)
    if field != "users":
        setattr(obj, field, value)
    obj.animation_data.use_tweak_mode = True
    assert sample(fixture)["action"] == "Walk"


def layered(fixture):
    _, obj, action, curve, _ = fixture
    other = copy.copy(curve)
    other.evaluate = lambda _frame: pytest.fail("Another slot must never be evaluated")
    slot = obj.animation_data.action_slot = NS(identifier="OBActor", handle=7)
    action.is_action_layered = True
    action.slots = [slot, NS(identifier="OBOther", handle=9)]
    action.layers = [NS(strips=[NS(channelbags=[NS(slot_handle=9, fcurves=[other]), NS(slot_handle=7, fcurves=[curve])])])]


def test_layered_active_slot_is_exact_even_when_another_slot_matches(fixture):
    layered(fixture)
    assert sample(fixture)["slot_identifier"] == "OBActor"
    assert sample(fixture, slot_identifier="OBActor")["samples"][1]["value"] == 13


@pytest.mark.parametrize("mode,code", [
    ("missing", "INVALID_ARGUMENT"), ("ambiguous", "INVALID_ARGUMENT"),
    ("other_index", "INVALID_ARGUMENT"), ("legacy_slot", "INVALID_ARGUMENT"),
    ("wrong_slot", "INVALID_ARGUMENT"), ("unassigned", "NOT_IMPLEMENTED"),
    ("unknown_layered_api", "NOT_IMPLEMENTED"), ("no_action", "INVALID_ARGUMENT"), ("no_animation", "INVALID_ARGUMENT"),
])
def test_exact_selector_refusals_precede_evaluation(fixture, mode, code):
    mod, obj, action, curve, calls = fixture
    params = {}
    if mode == "missing":
        action.fcurves = []
    elif mode == "ambiguous":
        action.fcurves.append(copy.copy(curve))
    elif mode == "other_index":
        params["index"] = 1
    elif mode == "legacy_slot":
        params["slot_identifier"] = "OBActor"
    elif mode == "no_action":
        obj.animation_data.action = None
    elif mode == "no_animation":
        obj.animation_data = None
    else:
        layered(fixture)
        if mode == "wrong_slot":
            params["slot_identifier"] = "OBOther"
        elif mode == "unassigned":
            obj.animation_data.action_slot = None
        else:
            action.layers = [NS(strips=[NS()])]
    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture, **params)
    assert caught.value.code == code and calls == ["get_object"]


@pytest.mark.parametrize("field,value", [
    ("object_name", None), ("object_name", ""), ("object_name", " "), ("object_name", 7), ("object_name", "x" * 257),
    ("data_path", None), ("data_path", ""), ("data_path", 7), ("data_path", "x" * 513),
    ("index", True), ("index", 0.0), ("index", "0"), ("index", -1), ("index", 16385),
    ("slot_identifier", 7), ("slot_identifier", ""), ("slot_identifier", "x" * 257),
    ("frames", None), ("frames", []), ("frames", [1] * 129), ("frames", (1,)), ("frames", "1"),
    ("frames", [True]), ("frames", ["1"]), ("frames", [None]), ("frames", [1_000_001]),
    ("frames", [-1_000_001]), ("frames", [float("nan")]), ("frames", [float("inf")]),
    ("frames", [-float("inf")]), ("frames", [10**10000]), ("unrecognized", 1),
])
def test_all_malformed_requested_inputs_fail_before_object_lookup(fixture, field, value):
    mod, _, _, _, calls = fixture
    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture, **{field: value})
    assert caught.value.code == "INVALID_ARGUMENT" and calls == []


@pytest.mark.parametrize("kind", ["sampled", "modifier", "driver", "empty", "too_many", "no_api", "extrapolation", "interpolation", "duplicate", "unsorted"])
def test_unsupported_stored_data_is_rejected_before_evaluation(fixture, kind):
    mod, _, _, curve, calls = fixture
    if kind == "sampled":
        curve.sampled_points, curve.keyframe_points = [NS(co=[1, 2])], []
    elif kind == "modifier":
        curve.modifiers = [NS(type="NOISE")]
    elif kind == "driver":
        curve.driver = NS()
    elif kind == "empty":
        curve.keyframe_points = []
    elif kind == "too_many":
        curve.keyframe_points = [point(n, n) for n in range(1025)]
    elif kind == "no_api":
        curve.evaluate = None
    elif kind == "extrapolation":
        curve.extrapolation = "UNKNOWN"
    elif kind == "interpolation":
        curve.keyframe_points[-1].interpolation = "SINE"
    elif kind == "duplicate":
        curve.keyframe_points[-1].co[0] = 1
    else:
        curve.keyframe_points.reverse()
    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED" and calls == ["get_object"]


@pytest.mark.parametrize("field", ["co", "handle_left", "handle_right"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_complete_keyframe_coordinates_are_finite_before_any_sample(fixture, field, invalid):
    mod, _, _, curve, calls = fixture
    getattr(curve.keyframe_points[-1], field)[1] = invalid
    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED" and caught.value.context == {"field": field}
    assert calls == ["get_object"]


def test_complete_point_budget_is_validated_with_bounded_native_indices(fixture):
    _, _, _, curve, _ = fixture
    reads = []

    class Points:
        def __len__(self):
            return 1024

        def __getitem__(self, index):
            reads.append(index)
            return point(index, index)

    curve.keyframe_points = Points()
    assert sample(fixture)["point_count"] == 1024
    assert reads == list(range(1024))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_native_results_never_produce_partial_success(fixture, bad):
    mod, _, _, curve, _ = fixture
    curve.evaluate = lambda _frame: bad
    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED" and caught.value.context == {"sample_index": 0}


def test_native_failure_is_structured_without_returning_raw_traceback(fixture):
    mod, _, _, curve, _ = fixture

    def fail(_frame):
        raise RuntimeError("private native diagnostic")

    curve.evaluate = fail
    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture)
    assert caught.value.code == "OPERATION_FAILED" and caught.value.context == {"sample_index": 0}
    assert "private native diagnostic" not in json.dumps(caught.value.to_dict())


def test_pure_request_safe_points_stop_between_samples_without_provider_callbacks(fixture):
    mod, _, _, _, calls = fixture

    def check():
        if ("evaluate", 1.) in calls:
            raise mod.BridgeError(mod.ErrorCode.TIMEOUT, "Canceled")

    def forbidden():
        pytest.fail("Arbitrary check_cancelled providers must not be invoked")

    context = NS(request_lifecycle=None, check_final_request=check, check_cancelled=forbidden)
    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture, context=context)
    assert caught.value.code == "TIMEOUT" and calls == ["get_object", ("evaluate", 1.)]


def test_lifecycle_expiry_stops_before_any_blender_lookup(fixture):
    mod, _, _, _, calls = fixture

    def expire():
        raise mod.BridgeError(mod.ErrorCode.TIMEOUT, "Expired")

    with pytest.raises(mod.BridgeError) as caught:
        sample(fixture, context=NS(request_lifecycle=NS(check=expire), check_final_request=None))
    assert caught.value.code == "TIMEOUT" and calls == []


def test_registry_metadata_is_read_only_inspection_not_animation_mutation(addon_package):
    mod = importlib.import_module(f"{addon_package}.tools.animation_curve_sampling")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    permission = importlib.import_module(f"{addon_package}.permissions").Permission
    registry = registry_mod.ToolRegistry(enabled_toolsets={"animation"})
    mod.register_tools(registry)
    spec = registry.get("animation.curve_sample")
    assert spec.toolset == "animation" and spec.modifies is False
    assert spec.permissions == frozenset({permission.INSPECT_SCENE}) and spec.batchable is True
