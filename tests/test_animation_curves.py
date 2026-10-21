from __future__ import annotations

import asyncio
import copy
import importlib
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.animation_curves import AnimationCurveTools, load_definitions


class Point:
    def __init__(self, frame, value):
        self.co = [float(frame), float(value)]
        self.interpolation = "BEZIER"
        self.easing = "AUTO"
        self.handle_left_type = self.handle_right_type = "AUTO_CLAMPED"
        self.handle_left = [float(frame) - 1, float(value)]
        self.handle_right = [float(frame) + 1, float(value)]


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.animation_curves")
    curve = NS(data_path="location", array_index=0, extrapolation="CONSTANT",
               keyframe_points=[Point(1, 0), Point(11, 10)], sampled_points=[], update=lambda: None)
    action = NS(name="Original", users=1, use_fake_user=False, fcurves=[curve], is_action_layered=False,
                library=None, override_library=None, is_editable=True)
    data = NS(action=action, use_tweak_mode=False)
    obj = NS(name="Actor", animation_data=data, library=None, override_library=None,
             is_editable=True, update_tag=lambda **kwargs: None)
    monkeypatch.setattr(mod, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(mod, "require_blender", lambda: NS(data=NS(actions=NS(get=lambda name: None))))
    return mod, obj, action, curve


def test_curve_edit_reports_poststate_and_preserves_other_curve(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    protected.array_index = 1
    action.fcurves.append(protected)
    result = mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "index": 0,
                                  "keyframes": [{"frame": 1, "interpolation": "LINEAR"}],
                                  "extrapolation": "LINEAR"})
    assert curve.keyframe_points[0].interpolation == "LINEAR"
    assert protected.keyframe_points[0].interpolation == "BEZIER"
    assert result["edited_frames"] == [1]
    assert result["truncated"] is False and len(result["keyframes"]) == 2
    assert curve.extrapolation == "LINEAR"


@pytest.mark.parametrize("edits", [
    None, {}, [None], [{"frame": True, "interpolation": "LINEAR"}],
    [{"frame": float("inf"), "interpolation": "LINEAR"}],
    [{"frame": 100, "interpolation": "LINEAR"}], [{"frame": 1}],
    [{"frame": 1, "interpolation": "BOUNCE"}], [{"frame": 1, "unknown": True}],
    [{"frame": 1, "handle_left": [0, 1]}],
    [{"frame": 1, "handle_left_type": "FREE", "handle_left": [0, True]}],
    [{"frame": 1, "handle_left_type": "FREE", "handle_left": [float("nan"), 0]}],
    [{"frame": 1, "handle_left_type": "FREE", "handle_left": [0]}],
    [{"frame": 1, "interpolation": "LINEAR"}] * 2,
    [{"frame": 1, "interpolation": "LINEAR"}] * 257,
])
def test_invalid_edit_never_changes_earlier_valid_keyframe(fixture, edits):
    mod, obj, _, curve = fixture
    before = [mod._point_state(p) for p in curve.keyframe_points]
    payload = {"object_name": obj.name, "data_path": "location", "keyframes": edits}
    if isinstance(edits, list):
        payload["keyframes"] = [{"frame": 11, "interpolation": "CONSTANT"}, *edits]
    with pytest.raises(mod.BridgeError):
        mod.curve_edit(None, payload)
    assert [mod._point_state(p) for p in curve.keyframe_points] == before


@pytest.mark.parametrize("value", [[], {}, 1, "CUBIC"])
def test_invalid_extrapolation_is_structured_and_nonmutating(fixture, value):
    mod, obj, _, curve = fixture
    with pytest.raises(mod.BridgeError) as caught:
        mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "extrapolation": value})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert curve.extrapolation == "CONSTANT"


@pytest.mark.parametrize("field,value", [
    ("users", 2), ("library", object()), ("override_library", object()), ("is_editable", False),
])
def test_curve_edit_protects_shared_and_nonlocal_action(fixture, field, value):
    mod, obj, action, curve = fixture
    setattr(action, field, value)
    with pytest.raises(mod.BridgeError) as caught:
        mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert curve.extrapolation == "CONSTANT"


def test_curve_update_failure_restores_entire_curve(fixture):
    mod, obj, _, curve = fixture
    before = [mod._point_state(p) for p in curve.keyframe_points]
    calls = []

    def update():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Injected update failure")

    curve.update = update
    with pytest.raises(mod.BridgeError) as caught:
        mod.curve_edit(None, {"object_name": obj.name, "data_path": "location",
                             "extrapolation": "LINEAR", "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["possible_mutation"] is False
    assert curve.extrapolation == "CONSTANT"
    assert [mod._point_state(p) for p in curve.keyframe_points] == before


def test_free_handles_accept_bounded_coordinates(fixture):
    mod, obj, _, curve = fixture
    result = mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "keyframes": [{
        "frame": 1, "handle_left_type": "FREE", "handle_right_type": "FREE",
        "handle_left": [0, -1], "handle_right": [4, 2],
    }]})
    assert tuple(curve.keyframe_points[0].handle_right) == (4, 2)
    assert result["keyframes"][0]["handle_left"] == [0, -1]


def test_layered_curve_authoring_uses_only_bound_slot(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    action.is_action_layered = True
    obj.animation_data.action_slot = NS(identifier="OBActor", handle=7)
    action.layers = [NS(strips=[NS(channelbags=[NS(slot_handle=9, fcurves=[protected]), NS(slot_handle=7, fcurves=[curve])])])]
    result = mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "slot_identifier": "OBActor", "extrapolation": "LINEAR"})
    assert result["slot_identifier"] == "OBActor"
    assert protected.extrapolation == "CONSTANT"
    assert curve.extrapolation == "LINEAR"
    with pytest.raises(mod.BridgeError):
        mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "slot_identifier": "Other", "extrapolation": "LINEAR"})


def test_unknown_layered_api_fails_explicitly(fixture):
    mod, obj, action, _ = fixture
    action.is_action_layered = True
    obj.animation_data.action_slot = NS(identifier="OBActor", handle=7)
    action.layers = [NS(strips=[NS()])]
    with pytest.raises(mod.BridgeError) as caught:
        mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR"})
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_action_copy_makes_explicit_independent_version_without_changing_source(fixture):
    mod, obj, source, curve = fixture
    source.users = 2
    source.copy = lambda: NS(name="Original.001", users=0, use_fake_user=True,
                            fcurves=copy.deepcopy(source.fcurves))
    result = mod.action_copy(None, {"object_name": obj.name, "new_name": "Revision"})
    assert obj.animation_data.action is not source
    assert obj.animation_data.action.name == "Revision"
    assert source.name == "Original" and source.fcurves[0] is curve
    assert obj.animation_data.action.use_fake_user is False
    assert result["independent_version"] and result["source_retained_in_session"]


def test_action_copy_failure_reports_retained_allocation_and_restores_binding(fixture):
    mod, obj, source, _ = fixture
    retained = NS(name="Retained", users=0, use_fake_user=False)
    source.copy = lambda: retained

    class Data:
        use_tweak_mode = False
        action = source

        def __setattr__(self, name, value):
            if name == "action" and value is retained:
                raise RuntimeError("Injected binding failure")
            object.__setattr__(self, name, value)

    obj.animation_data = Data()
    with pytest.raises(mod.BridgeError) as caught:
        mod.action_copy(None, {"object_name": obj.name, "new_name": "Revision"})
    assert obj.animation_data.action is source
    assert caught.value.context["rollback_verified"]
    assert caught.value.context["retained_action"] == "Revision"
    assert caught.value.context["possible_mutation"]


def test_action_copy_name_collision_prevents_allocation(fixture, monkeypatch):
    mod, obj, source, _ = fixture
    monkeypatch.setattr(mod, "require_blender", lambda: NS(data=NS(actions=NS(get=lambda name: source))))
    with pytest.raises(mod.BridgeError) as caught:
        mod.action_copy(None, {"object_name": obj.name, "new_name": "Existing"})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert obj.animation_data.action is source


def test_mcp_definitions_and_typed_wrapper_forwarding():
    definitions = load_definitions()
    assert {item.name for item in definitions} == {"animation.action_copy", "animation.curve_edit"}
    calls = []

    class Registry:
        async def call(self, name, params):
            calls.append((name, params))
            return params

    tools = AnimationCurveTools(Registry())
    result = asyncio.run(tools.animation_curve_edit("Actor", "location", keyframes=[{"frame": 1, "interpolation": "LINEAR"}]))
    assert result == {"object_name": "Actor", "data_path": "location", "index": 0,
                      "keyframes": [{"frame": 1, "interpolation": "LINEAR"}]}
    assert len(tools.bindings()) == 2
    assert calls[0][0] == "animation.curve_edit"


def test_extrapolation_rna_update_reacquires_native_points(fixture):
    mod, obj, action, original = fixture

    class ReallocatingCurve:
        data_path = "location"
        array_index = 0
        sampled_points = ()
        update = staticmethod(lambda: None)

        def __init__(self):
            self.keyframe_points = original.keyframe_points
            self._extrapolation = "CONSTANT"

        @property
        def extrapolation(self):
            return self._extrapolation

        @extrapolation.setter
        def extrapolation(self, value):
            self.keyframe_points = copy.deepcopy(self.keyframe_points)
            self._extrapolation = value

    curve = ReallocatingCurve()
    action.fcurves = [curve]
    mod.curve_edit(None, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR",
                         "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
    assert curve.keyframe_points[0].interpolation == "CONSTANT"
    assert original.keyframe_points[0].interpolation == "BEZIER"


def test_action_copy_budget_rejects_before_native_allocation(fixture):
    mod, obj, source, curve = fixture
    curve.keyframe_points = [Point(i, 0) for i in range(1025)]
    with pytest.raises(mod.BridgeError) as caught:
        mod.action_copy(None, {"object_name": obj.name, "new_name": "TooLarge"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert obj.animation_data.action is source
