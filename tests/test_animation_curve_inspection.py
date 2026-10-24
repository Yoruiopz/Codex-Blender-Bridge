from __future__ import annotations

import copy
import importlib
import json
from types import SimpleNamespace as NS

import pytest


def point(frame, value):
    return NS(co=[float(frame), float(value)], interpolation="BEZIER", easing="EASE_IN_OUT",
              handle_left_type="FREE", handle_right_type="ALIGNED",
              handle_left=[float(frame) - 0.5, float(value) - 2],
              handle_right=[float(frame) + 0.75, float(value) + 3])


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.animation_curve_inspection")
    calls = []
    curve = NS(data_path="location", array_index=0, group=NS(name="Movement"), mute=True, lock=True,
               extrapolation="LINEAR", keyframe_points=[point(1, 0), point(11, 10)], sampled_points=[],
               update=lambda: calls.append("update"), evaluate=lambda frame: calls.append("evaluate"))
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


def inspect(fixture, **params):
    mod, _, _, _, _ = fixture
    return mod.curve_inspect(None, {"object_name": "Actor", "data_path": "location", **params})


def test_exact_curve_metadata_and_full_handles_without_native_updates(fixture):
    _, obj, action, curve, calls = fixture
    before = copy.deepcopy((vars(obj), vars(action), vars(curve)))
    result = inspect(fixture)
    assert result == {
        "object": "Actor", "action": "Walk", "slot_identifier": None,
        "data_path": "location", "index": 0, "group": "Movement", "mute": True, "lock": True,
        "extrapolation": "LINEAR", "point_count": 2, "point_offset": 0, "point_limit": 64,
        "returned_points": 2, "truncated": False, "next_offset": None,
        "keyframes": [{"frame": 1.0, "value": 0.0, "interpolation": "BEZIER", "easing": "EASE_IN_OUT",
                       "handle_left_type": "FREE", "handle_right_type": "ALIGNED",
                       "handle_left": [0.5, -2.0], "handle_right": [1.75, 3.0]},
                      {"frame": 11.0, "value": 10.0, "interpolation": "BEZIER", "easing": "EASE_IN_OUT",
                       "handle_left_type": "FREE", "handle_right_type": "ALIGNED",
                       "handle_left": [10.5, 8.0], "handle_right": [11.75, 13.0]}],
    }
    json.dumps(result, allow_nan=False)
    assert (vars(obj), vars(action), vars(curve)) == before
    assert calls == ["get_object"]


@pytest.mark.parametrize("field,value", [
    ("users", 7), ("library", "linked.blend"), ("override_library", "override"), ("is_editable", False),
])
def test_shared_linked_and_noneditable_data_remain_readable(fixture, field, value):
    _, obj, action, _, calls = fixture
    setattr(action, field, value)
    if field != "users":
        setattr(obj, field, value)
    obj.animation_data.use_tweak_mode = True
    assert inspect(fixture)["action"] == "Walk"
    assert calls == ["get_object"]


def test_point_pages_tail_and_empty_terminal_are_explicit(fixture):
    first = inspect(fixture, point_limit=1)
    assert (first["point_count"], first["returned_points"], first["truncated"], first["next_offset"]) == (2, 1, True, 1)
    assert first["keyframes"][0]["frame"] == 1
    last = inspect(fixture, point_offset=first["next_offset"], point_limit=1)
    assert last["keyframes"][0]["frame"] == 11
    assert last["returned_points"] == 1 and last["truncated"] is False and last["next_offset"] is None
    terminal = inspect(fixture, point_offset=2)
    assert terminal["keyframes"] == [] and terminal["returned_points"] == 0
    assert terminal["truncated"] is False and terminal["next_offset"] is None


def test_large_offset_reads_only_bounded_indices(fixture):
    _, _, _, curve, _ = fixture
    reads = []

    class Points:
        def __len__(self):
            return 1_000_000

        def __getitem__(self, ordinal):
            assert 0 <= ordinal < len(self)
            reads.append(ordinal)
            return point(ordinal, ordinal * 2)

    curve.keyframe_points = Points()
    result = inspect(fixture, point_offset=999_999, point_limit=256)
    assert reads == [999_999]
    assert result["keyframes"][0]["value"] == 1_999_998
    assert result["point_count"] == 1_000_000 and result["returned_points"] == 1
    assert result["truncated"] is False and result["next_offset"] is None
    reads.clear()
    terminal = inspect(fixture, point_offset=1_000_000, point_limit=256)
    assert terminal["returned_points"] == 0 and terminal["truncated"] is False
    assert terminal["next_offset"] is None and reads == []
    result = inspect(fixture, point_offset=999_000, point_limit=256)
    assert reads == list(range(999_000, 999_256))
    assert result["returned_points"] == 256 and result["next_offset"] == 999_256


def test_total_point_budget_refuses_before_any_point_read(fixture):
    mod, _, _, curve, _ = fixture
    reads = []

    class Points:
        def __len__(self):
            return 1_000_001

        def __getitem__(self, ordinal):
            reads.append(ordinal)
            return point(ordinal, ordinal)

    curve.keyframe_points = Points()
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context == {"point_count": 1_000_001} and reads == []


def test_empty_curve_is_complete_and_ungrouped(fixture):
    _, _, _, curve, _ = fixture
    curve.keyframe_points, curve.group = [], None
    result = inspect(fixture)
    assert result["point_count"] == result["returned_points"] == 0
    assert result["group"] is None and result["truncated"] is False


def layered(fixture):
    _, obj, action, curve, _ = fixture
    other = copy.deepcopy(curve)
    other.extrapolation = "CONSTANT"
    slot = obj.animation_data.action_slot = NS(identifier="OBActor", handle=7)
    action.is_action_layered = True
    action.slots = [slot, NS(identifier="OBOther", handle=9)]
    action.layers = [NS(strips=[NS(channelbags=[NS(slot_handle=9, fcurves=[other]),
                                                 NS(slot_handle=7, fcurves=[curve])])])]
    return other


def test_layered_selection_uses_only_assigned_slot(fixture):
    other = layered(fixture)
    assert inspect(fixture)["slot_identifier"] == "OBActor"
    assert inspect(fixture, slot_identifier="OBActor")["extrapolation"] == "LINEAR"
    assert other.extrapolation == "CONSTANT"


def test_layered_slot_must_match_assigned_slot(fixture):
    mod = fixture[0]
    layered(fixture)
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture, slot_identifier="OBOther")
    assert caught.value.code == "INVALID_ARGUMENT"


def test_layered_requires_assigned_slot_and_reviewed_native_api(fixture):
    mod, obj, action, _, _ = fixture
    layered(fixture)
    obj.animation_data.action_slot = None
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED"
    obj.animation_data.action_slot = action.slots[0]
    action.layers = [NS(strips=[NS()])]
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("mode", ["missing", "ambiguous", "other_index", "legacy_slot"])
def test_exact_selection_refuses_missing_ambiguous_or_invalid_slot(fixture, mode):
    mod, _, action, curve, _ = fixture
    params = {}
    if mode == "missing":
        action.fcurves = []
    elif mode == "ambiguous":
        action.fcurves.append(copy.deepcopy(curve))
    elif mode == "other_index":
        params["index"] = 1
    else:
        params["slot_identifier"] = "OBActor"
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture, **params)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("absent", ["animation_data", "action"])
def test_explicit_object_requires_active_action(fixture, absent):
    mod, obj, _, _, _ = fixture
    if absent == "animation_data":
        obj.animation_data = None
    else:
        obj.animation_data.action = None
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("field,value", [
    ("object_name", None), ("object_name", ""), ("object_name", " "), ("object_name", 7), ("object_name", "x" * 257),
    ("data_path", None), ("data_path", ""), ("data_path", 7), ("data_path", "x" * 513),
    ("index", True), ("index", 0.0), ("index", "0"), ("index", -1), ("index", 16385),
    ("slot_identifier", 7), ("slot_identifier", ""), ("slot_identifier", "x" * 257),
    ("point_offset", True), ("point_offset", 0.0), ("point_offset", "0"), ("point_offset", -1),
    ("point_offset", 1_000_001), ("point_offset", 3), ("point_offset", None),
    ("point_limit", True), ("point_limit", 1.0), ("point_limit", "1"), ("point_limit", 0),
    ("point_limit", 257), ("point_limit", None), ("unrecognized", 1),
])
def test_bounded_input_validation(fixture, field, value):
    mod = fixture[0]
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture, **{field: value})
    assert caught.value.code == "INVALID_ARGUMENT"


def test_sampled_curves_are_explicitly_unsupported_even_without_keyframes(fixture):
    mod, _, _, curve, _ = fixture
    curve.sampled_points, curve.keyframe_points = [NS(co=[1, 2])], []
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("field", ["co", "handle_left", "handle_right"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_native_coordinates_must_be_finite_json_numbers(fixture, field, invalid):
    mod, _, _, curve, _ = fixture
    getattr(curve.keyframe_points[0], field)[1] = invalid
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED" and caught.value.context == {"field": field}


def test_native_handle_coordinates_are_exactly_two_dimensional(fixture):
    mod, _, _, curve, _ = fixture
    curve.keyframe_points[0].handle_left.append(4)
    with pytest.raises(mod.BridgeError) as caught:
        inspect(fixture)
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_registration_is_read_only_and_batchable_like_animation_inspect(addon_package):
    mod = importlib.import_module(f"{addon_package}.tools.animation_curve_inspection")
    animation = importlib.import_module(f"{addon_package}.tools.animation")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permission = importlib.import_module(f"{addon_package}.permissions").Permission
    registry = registry_module.ToolRegistry()
    mod.register_tools(registry)
    animation.register_tools(registry)
    spec = registry.get("animation.curve_inspect")
    assert spec.toolset == "animation" and spec.modifies is False
    assert spec.permissions == frozenset({permission.INSPECT_SCENE})
    assert spec.batchable == registry.get("animation.inspect").batchable is True
