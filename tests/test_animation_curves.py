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


class Record(NS):
    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__


class Items(list):
    active = None

    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Action(Record):
    @property
    def users(self):
        return int(self.env.obj.animation_data.action is self) + int(self.use_fake_user) + self.external_users

    @users.setter
    def users(self, value):
        self.external_users = value - int(self.env.obj.animation_data.action is self) - int(self.use_fake_user)


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.animation_curves")
    curve = NS(data_path="location", array_index=0, extrapolation="CONSTANT",
               keyframe_points=[Point(1, 0), Point(11, 10)], sampled_points=[], update=lambda: None)
    env = NS()
    action = Action(name="Original", env=env, external_users=0, use_fake_user=False, fcurves=[curve], is_action_layered=False,
                    library=None, override_library=None, is_editable=True)
    data = Record(action=action, use_tweak_mode=False, drivers=[], nla_tracks=Items())
    obj = env.obj = Record(name="Actor", type="EMPTY", data=None, animation_data=data, library=None, override_library=None,
                          is_editable=True, update_tag=lambda **kwargs: None)
    obj.user_of_id = lambda owner: int(obj.animation_data.action is owner)
    scene = Record(name="Scene", objects=Items([obj]))
    obj.users_scene, obj.users_collection = [scene], []
    actions = Items([action])
    outside = Record(name="Protected", session_uid=None, bl_rna=NS(identifier="Object"), library=None, override_library=None, is_editable=True)
    outside.user_of_id = lambda owner: owner.external_users
    obj.bl_rna = NS(identifier="Object")
    bpy = NS(data=NS(actions=actions, objects=Items([obj]), filepath="",
                     user_map=lambda *, subset: {owner: {item for item in (obj, outside) if item.user_of_id(owner)} if isinstance(owner, Action) else set() for owner in subset}),
             context=NS(scene=scene, mode="OBJECT", view_layer=NS(objects=Items([obj]))))
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry(enabled_toolsets=("animation",))
    mod.register_tools(registry)
    mod.animation_lifecycle.register_tools(registry)
    flags = {"paused": False, "emergency_stopped": False}
    grants = {item.value: True for item in permissions.Permission}
    obj._context = registry_module.ToolContext(state=NS(snapshot=lambda: flags), permissions=permissions.PermissionManager(lambda: grants), registry=registry, checkpoints=None)
    obj._flags, obj._grants, obj._bpy = flags, grants, bpy

    def make_copy():
        created = Action(name="Original.001", env=env, external_users=0, use_fake_user=False,
                         fcurves=copy.deepcopy(action.fcurves), is_action_layered=False,
                         library=None, override_library=None, is_editable=True)
        actions.append(created)
        return created

    action.copy = make_copy
    monkeypatch.setattr(mod, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(mod, "require_blender", lambda: bpy)
    monkeypatch.setattr(mod.animation_lifecycle, "require_blender", lambda: bpy)
    return mod, obj, action, curve


def test_curve_edit_reports_poststate_and_preserves_other_curve(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    protected.array_index = 1
    action.fcurves.append(protected)
    result = mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "index": 0,
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
        mod.curve_edit(obj._context, payload)
    assert [mod._point_state(p) for p in curve.keyframe_points] == before


@pytest.mark.parametrize("value", [[], {}, 1, "CUBIC"])
def test_invalid_extrapolation_is_structured_and_nonmutating(fixture, value):
    mod, obj, _, curve = fixture
    with pytest.raises(mod.BridgeError) as caught:
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "extrapolation": value})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert curve.extrapolation == "CONSTANT"


@pytest.mark.parametrize("field,value", [
    ("users", 2), ("library", object()), ("override_library", object()), ("is_editable", False),
])
def test_curve_edit_protects_shared_and_nonlocal_action(fixture, field, value):
    mod, obj, action, curve = fixture
    setattr(action, field, value)
    with pytest.raises(mod.BridgeError) as caught:
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR"})
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
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location",
                             "extrapolation": "LINEAR", "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["possible_mutation"] is False
    assert curve.extrapolation == "CONSTANT"
    assert [mod._point_state(p) for p in curve.keyframe_points] == before


def test_free_handles_accept_bounded_coordinates(fixture):
    mod, obj, _, curve = fixture
    result = mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "keyframes": [{
        "frame": 1, "handle_left_type": "FREE", "handle_right_type": "FREE",
        "handle_left": [0, -1], "handle_right": [4, 2],
    }]})
    assert tuple(curve.keyframe_points[0].handle_right) == (4, 2)
    assert result["keyframes"][0]["handle_left"] == [0, -1]


def test_layered_curve_authoring_uses_only_bound_slot(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    action.is_action_layered = True
    obj.animation_data.action_slot = NS(identifier="OBActor", handle=7, target_id_type="OBJECT")
    action.slots = [obj.animation_data.action_slot, NS(identifier="OBProtected", handle=9, target_id_type="OBJECT")]
    action.layers = [NS(strips=[NS(channelbags=[NS(slot_handle=9, fcurves=[protected], groups=[]), NS(slot_handle=7, fcurves=[curve], groups=[])])])]
    result = mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "slot_identifier": "OBActor", "extrapolation": "LINEAR"})
    assert result["slot_identifier"] == "OBActor"
    assert protected.extrapolation == "CONSTANT"
    assert curve.extrapolation == "LINEAR"
    with pytest.raises(mod.BridgeError):
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "slot_identifier": "Other", "extrapolation": "LINEAR"})


def test_unknown_layered_api_fails_explicitly(fixture):
    mod, obj, action, _ = fixture
    action.is_action_layered = True
    obj.animation_data.action_slot = NS(identifier="OBActor", handle=7)
    action.layers = [NS(strips=[NS()])]
    with pytest.raises(mod.BridgeError) as caught:
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR"})
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_action_copy_makes_explicit_independent_version_without_changing_source(fixture):
    mod, obj, source, curve = fixture
    source.users = 2
    result = mod.action_copy(obj._context, {"object_name": obj.name, "new_name": "Revision"})
    assert obj.animation_data.action is not source
    assert obj.animation_data.action.name == "Revision"
    assert source.name == "Original" and source.fcurves[0] is curve
    assert obj.animation_data.action.use_fake_user is False
    assert result["independent_version"] and result["source_retained_in_session"]


def test_action_copy_failure_reports_retained_allocation_and_restores_binding(fixture):
    mod, obj, source, _ = fixture
    retained = source.copy()
    source.copy = lambda: retained

    class Data:
        use_tweak_mode = False
        drivers = ()
        nla_tracks = Items()
        action = source

        def __setattr__(self, name, value):
            if name == "action" and value is retained:
                raise RuntimeError("Injected binding failure")
            object.__setattr__(self, name, value)

    obj.animation_data = Data()
    with pytest.raises(mod.BridgeError) as caught:
        mod.action_copy(obj._context, {"object_name": obj.name, "new_name": "Revision"})
    assert obj.animation_data.action is source
    assert caught.value.context["rollback_verified"]
    assert caught.value.context["retained_action"] == "Revision"
    assert caught.value.context["possible_mutation"]


def test_action_copy_name_collision_prevents_allocation(fixture, monkeypatch):
    mod, obj, source, _ = fixture
    monkeypatch.setattr(mod, "require_blender", lambda: NS(data=NS(actions=NS(get=lambda name: source))))
    with pytest.raises(mod.BridgeError) as caught:
        mod.action_copy(obj._context, {"object_name": obj.name, "new_name": "Existing"})
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
    scoped = asyncio.run(tools.animation_curve_edit("Actor", "location", extrapolation="LINEAR", affected_objects=["Skin"]))
    assert scoped["affected_objects"] == ["Skin"]
    copied = asyncio.run(tools.animation_action_copy("Actor", "Revision", affected_objects=["Skin"]))
    assert copied == {"object_name": "Actor", "new_name": "Revision", "affected_objects": ["Skin"]}


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
    mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR",
                         "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
    assert curve.keyframe_points[0].interpolation == "CONSTANT"
    assert original.keyframe_points[0].interpolation == "BEZIER"


def test_action_copy_budget_rejects_before_native_allocation(fixture):
    mod, obj, source, curve = fixture
    curve.keyframe_points = [Point(i, 0) for i in range(1025)]
    with pytest.raises(mod.BridgeError) as caught:
        mod.action_copy(obj._context, {"object_name": obj.name, "new_name": "TooLarge"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert obj.animation_data.action is source


@pytest.mark.parametrize("change", ["pause", "emergency", "permission", "cancel", "toolset", "session", "binding", "content", "consumer"])
def test_curve_live_boundary_refuses_changes_before_first_write(fixture, change):
    mod, obj, action, curve = fixture

    def callback():
        if change == "pause":
            obj._flags["paused"] = True
        elif change == "emergency":
            obj._flags["emergency_stopped"] = True
        elif change == "permission":
            obj._grants["EDIT_ANIMATION"] = False
        elif change == "cancel":
            raise mod.BridgeError(mod.ErrorCode.OPERATION_FAILED, "Canceled")
        elif change == "toolset":
            obj._context.registry.disable_toolset("animation")
        elif change == "session":
            obj._bpy.data.filepath = "/changed-session.blend"
        elif change == "binding":
            obj.animation_data.action = None
        elif change == "content":
            curve.keyframe_points[0].interpolation = "CONSTANT"
        else:
            action.external_users += 1

    obj._context.check_cancelled = callback
    with pytest.raises(mod.BridgeError):
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR"})
    assert curve.extrapolation == "CONSTANT"


@pytest.mark.parametrize("change", ["pause", "emergency", "permission", "cancel", "manual_key", "consumer", "binding"])
def test_postwrite_authority_and_manual_changes_prevent_stale_curve_compensation(fixture, change):
    mod, obj, action, curve = fixture
    fired = False

    def callback():
        nonlocal fired
        if curve.extrapolation != "LINEAR":
            return
        if change == "cancel":
            raise mod.BridgeError(mod.ErrorCode.OPERATION_FAILED, "Canceled")
        if fired:
            return
        fired = True
        if change == "pause":
            obj._flags["paused"] = True
        elif change == "emergency":
            obj._flags["emergency_stopped"] = True
        elif change == "permission":
            obj._grants["EDIT_ANIMATION"] = False
        elif change == "manual_key":
            curve.keyframe_points[0].interpolation = "CONSTANT"
        elif change == "consumer":
            action.external_users += 1
        else:
            obj.animation_data.action = None

    obj._context.check_cancelled = callback
    with pytest.raises(mod.BridgeError) as error:
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR",
                                     "keyframes": [{"frame": 1, "interpolation": "LINEAR"}]})
    assert not error.value.context["rollback_verified"] and error.value.context["possible_mutation"]
    assert curve.extrapolation == "LINEAR"
    assert curve.keyframe_points[0].interpolation == ("CONSTANT" if change == "manual_key" else "BEZIER")


@pytest.mark.parametrize("change", ["pause", "permission", "new_consumer", "source_content"])
def test_allocated_copy_is_retained_without_further_writes_after_changed_authority_or_ownership(fixture, change):
    mod, obj, source, curve = fixture
    created = None

    def callback():
        nonlocal created
        if len(obj._bpy.data.actions) < 2:
            return
        created = obj._bpy.data.actions[1]
        if change == "pause":
            obj._flags["paused"] = True
        elif change == "permission":
            obj._grants["EDIT_ANIMATION"] = False
        elif change == "new_consumer":
            created.external_users = 1
        else:
            curve.keyframe_points[0].interpolation = "CONSTANT"

    obj._context.check_cancelled = callback
    with pytest.raises(mod.BridgeError) as error:
        mod.action_copy(obj._context, {"object_name": obj.name, "new_name": "Revision"})
    assert created is not None and created in obj._bpy.data.actions
    assert created.name == "Original.001" and obj.animation_data.action is source
    assert error.value.context["retained_action"] == "Original.001" and error.value.context["possible_mutation"]


def test_curve_recovery_never_overwrites_a_protected_channel_changed_by_failed_native_update(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    protected.array_index = 1
    action.fcurves.append(protected)

    def update():
        protected.keyframe_points[0].interpolation = "CONSTANT"
        raise RuntimeError("Injected native update changed a protected channel")

    curve.update = update
    with pytest.raises(mod.BridgeError) as error:
        mod.curve_edit(obj._context, {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR"})
    assert not error.value.context["rollback_verified"]
    assert protected.keyframe_points[0].interpolation == "CONSTANT" and curve.extrapolation == "LINEAR"
