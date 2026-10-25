from __future__ import annotations

import asyncio
import copy
import importlib
import struct
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.animation_curves import AnimationCurveTools, load_definitions


class Point:
    def __init__(self, frame, value):
        self.co = [float(frame), float(value)]
        self.interpolation = "BEZIER"
        self.easing = "AUTO"
        self.handle_left_type = self.handle_right_type = "FREE"
        self.handle_left = [float(frame) - 1, float(value)]
        self.handle_right = [float(frame) + 1, float(value)]

    @property
    def co_ui(self):
        return self.co


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
    # Explicit portable host model; these stand-ins do not qualify native RNA,
    # active-owner witness or checkpoint weak-role behavior.
    obj.session_uid, obj.as_pointer = 101, lambda: 1001
    action.session_uid, action.as_pointer = 102, lambda: 1002
    scene.session_uid, scene.as_pointer = 103, lambda: 1003
    scene.frame_current, scene.frame_subframe = 3, .25
    obj.select_get = lambda **_: True
    monkeypatch.setattr(mod, "_curve_pointer", lambda owner: getattr(owner, "_native_pointer", id(owner)))
    monkeypatch.setattr(mod, "_curve_native_screen", lambda *_: None)
    monkeypatch.setattr(mod, "_curve_write_schema", lambda *_: None)
    monkeypatch.setattr(mod, "_curve_object_state", lambda owner, **_: (
        owner.name, getattr(owner, "type", None), tuple(getattr(owner, "location", ()))))
    class Roles:
        def check_after_read(self):
            pass
        def authored(self):
            return ("PORTABLE_ROLE_MODEL",)
        def after_native_push(self):
            completion = importlib.import_module(f"{addon_package}.checkpoint_completion")
            completion.claim_native_push_delegate(self)
    monkeypatch.setattr(mod, "_curve_roles", lambda *_: (Roles(), NS(check=lambda *_: None)))
    obj._leaf_calls, obj._leaf_live = [], []
    obj._leaf_effect = obj._read_fault = obj._leaf_precheck = None
    role = Roles()

    def plain(value):
        if type(value) is dict:
            return tuple((key, plain(item)) for key, item in sorted(value.items()))
        if type(value) in (list, tuple):
            return tuple(plain(item) for item in value)
        return value

    class FakeLeaf:
        # Explicit portable simulation only: it never qualifies native RNA.
        def __init__(self, owner, field, value):
            self.owner, self.field, self.value = owner, field, value
            obj._leaf_live.append(self)

        def __call__(self):
            assert self.owner is not None
            call = (self.field, self.value)
            obj._leaf_calls.append(call)
            effect = obj._leaf_effect
            if effect is not None:
                effect("before", self.owner, self.field, self.value, len(obj._leaf_calls))
            setattr(self.owner, self.field, list(struct.unpack("<ff", struct.pack("<ff", *self.value))))
            if effect is not None:
                effect("after", self.owner, self.field, self.value, len(obj._leaf_calls))

        def clear(self):
            self.owner = None
            obj._leaf_live.remove(self)

    class PortableReader:
        def __init__(self, context, params):
            self.bpy, self.context, self.params = bpy, context, params
            self.ids = mod._curve_id(obj), mod._curve_id(action)
            self.scene = bpy.context.scene
            self.layer = bpy.context.view_layer
            self.origin = (context.state, context.permissions, context.checkpoints)
            self._extra_before = obj.__dict__.get("_model_origin", None)

        def check_origin(self):
            if (self.context.state, self.context.permissions, self.context.checkpoints) != self.origin:
                raise mod.BridgeError("NOT_IMPLEMENTED", "Portable original services changed")

        def prepare(self):
            return mod._prepare_curve_edit(self.params)

        def roles(self):
            return role, NS(check=lambda *_: None)

        def action_content(self, owner):
            if obj._read_fault is not None:
                obj._read_fault(owner)
            source = mod.scope.action_content(owner)
            # The source reader fallback deliberately has no co_ui descriptor.
            # This explicit model supplies the native getter alias independently.
            curves = tuple((handle, (metadata, tuple((*point, ("co_ui", dict(point)["co"]))
                                                   for point in points), modifiers))
                           for handle, (metadata, points, modifiers) in source[3])
            return (*source[:3], curves, *source[4:])

        def resolve(self):
            self.check_origin()
            if bpy.data.objects.get(obj.name) is not obj or obj.animation_data is None:
                raise mod.BridgeError("INVALID_ARGUMENT", "Portable target membership changed")
            current = obj.animation_data.action
            if current is not action or (mod._curve_id(obj), mod._curve_id(current)) != self.ids:
                raise mod.BridgeError("INVALID_ARGUMENT", "Portable original native ID changed")
            selected = self.prepare()
            return selected["object"], selected["action"], selected["curve"]

        def preservation(self, roles):
            current, owned, _curve = self.resolve()
            others = tuple((mod._curve_id(owner), owner.name, mod._curve_structure(owner), self.action_content(owner))
                           for owner in bpy.data.actions if owner is not owned)
            return (mod._curve_structure(owned), plain(mod.scope.action_users(bpy, owned)),
                    mod.scope.binding(current), mod.scope.animation_context(current),
                    bpy.data.filepath, mod._curve_pointer(bpy.context.scene),
                    mod._curve_pointer(bpy.context.view_layer), bpy.context.mode,
                    int(scene.frame_current), float(scene.frame_subframe),
                    tuple(getattr(current, "location", ())), others, roles.authored())

        def leaf(self, old_curve, field, frame, value, *, expected, preservation, roles):
            # Model a last native-reader effect before the required final CAS.
            if obj._leaf_precheck is not None:
                obj._leaf_precheck()
            _current, owner, fresh = self.resolve()
            if (not kernel.same(self.action_content(owner), expected)
                    or not kernel.same(self.preservation(roles), preservation)):
                raise mod.BridgeError("INVALID_ARGUMENT", "Portable final complete prefix CAS failed")
            assert mod._curve_pointer(old_curve) == mod._curve_pointer(fresh)
            points = [point for point in fresh.keyframe_points
                      if struct.pack("<f", point.co[0]) == struct.pack("<f", frame)]
            if len(points) != 1:
                raise mod.BridgeError("INVALID_ARGUMENT", "Portable exact point missing")
            mod._curve_write_schema(bpy, points[0], field, value)
            return FakeLeaf(points[0], field, value)

    kernel = importlib.import_module(f"{addon_package}.tools._curve_edit_intent")
    monkeypatch.setattr(mod, "_make_curve_reader", PortableReader)
    return mod, obj, action, curve



def edit(mod, context, params):
    """Exercise actual registered admission and canonical invocation lease."""
    return context.registry.dispatch("animation.curve_edit", params, context)


def request(obj, **values):
    return {"object_name": obj.name, "data_path": "location", "index": 0,
            "keyframes": [{"frame": 11, "co": [11., 12.], "handle_left": [10., 13.]}], **values}


def authored(mod, action):
    return copy.deepcopy(mod.scope.action_content(action))


def test_raw_points_report_poststate_and_preserve_other_curves_and_handles(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    protected.array_index = 1
    action.fcurves.append(protected)
    protected_before = mod.scope.curve_content(protected)
    original_right = list(curve.keyframe_points[1].handle_right)
    curve.update = lambda: pytest.fail("Raw point writer must never sort, recalculate or update")
    result = edit(mod, obj._context, request(obj))
    assert curve.keyframe_points[1].co == [11., 12.]
    assert curve.keyframe_points[1].handle_left == [10., 13.]
    assert curve.keyframe_points[1].handle_right == original_right
    assert mod.scope.curve_content(protected) == protected_before
    assert result["authored_profile"] == "RAW_FREE_POINT_V1"
    assert result["keyframes"][1]["co"] == [11., 12.]
    assert result["edited_frames"] == [11.]
    facts = result["recovery_evidence"]
    assert facts["owned_field_attempts"] == facts["owned_field_verified"] == 2
    assert facts["native_update_attempts"] == facts["native_update_verified"] == 0
    assert facts["expected_sha256"] == facts["observed_sha256"]
    assert not result["persistent_non_ID_identity_qualified"]
    assert obj._leaf_live == []


@pytest.mark.parametrize("edits", [
    None, {}, [None], [{"frame": True, "co": [1, 1]}],
    [{"frame": float("inf"), "co": [1, 1]}], [{"frame": 100, "co": [100, 1]}],
    [{"frame": 1}], [{"frame": 1, "unknown": True}], [{"frame": 1, "co": [1, True]}],
    [{"frame": 1, "co": [1, float("nan")]}], [{"frame": 1, "co": [1]}],
    [{"frame": 1, "handle_left": [0, float("inf")]}],
    [{"frame": 1, "co": [1, 1]}] * 2, [{"frame": 1, "co": [1, 1]}] * 257,
])
def test_invalid_later_edit_never_partially_applies_earlier_valid_edit(fixture, edits):
    mod, obj, action, _curve = fixture
    before = authored(mod, action)
    payload = request(obj, keyframes=edits)
    if isinstance(edits, list):
        payload["keyframes"] = [{"frame": 11, "co": [11., 42.]}, *edits]
    with pytest.raises(mod.BridgeError):
        edit(mod, obj._context, payload)
    assert authored(mod, action) == before and obj._leaf_calls == []


@pytest.mark.parametrize("field,value", [
    ("interpolation", "LINEAR"), ("easing", "EASE_IN"),
    ("handle_left_type", "FREE"), ("handle_right_type", "AUTO"),
])
def test_retained_enum_fields_refuse_explicitly_before_native_acquisition(fixture, monkeypatch, field, value):
    mod, obj, action, _curve = fixture
    monkeypatch.setattr(mod, "_make_curve_reader", lambda *_: pytest.fail("Unsupported enum acquired native source"))
    before = authored(mod, action)
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj, keyframes=[{"frame": 11, field: value}]))
    assert caught.value.code == "NOT_IMPLEMENTED" and authored(mod, action) == before


@pytest.mark.parametrize("value,code", [("LINEAR", "NOT_IMPLEMENTED"), ("CONSTANT", "NOT_IMPLEMENTED"),
                                        ([], "INVALID_ARGUMENT"), ({}, "INVALID_ARGUMENT"),
                                        (1, "INVALID_ARGUMENT"), ("CUBIC", "INVALID_ARGUMENT")])
def test_extrapolation_contract_preserved_and_refused_before_native_acquisition(fixture, monkeypatch, value, code):
    mod, obj, action, _curve = fixture
    monkeypatch.setattr(mod, "_make_curve_reader", lambda *_: pytest.fail("Unsupported extrapolation acquired native source"))
    before = authored(mod, action)
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj, extrapolation=value))
    assert caught.value.code == code and authored(mod, action) == before


@pytest.mark.parametrize("field,value", [("users", 2), ("library", object()),
                                         ("override_library", object()), ("is_editable", False)])
def test_shared_or_nonlocal_action_refused_before_any_assignment(fixture, field, value):
    mod, obj, action, _curve = fixture
    setattr(action, field, value)
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert caught.value.code == "NOT_IMPLEMENTED" and obj._leaf_calls == []


@pytest.mark.parametrize("kind", ["AUTO", "AUTO_CLAMPED", "ALIGNED", "VECTOR"])
def test_reactive_source_handle_refused_before_any_assignment(fixture, kind):
    mod, obj, action, curve = fixture
    curve.keyframe_points[0].handle_left_type = kind
    before = authored(mod, action)
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert authored(mod, action) == before and obj._leaf_calls == []


@pytest.mark.parametrize("field,pair", [("co", [12., 5.]), ("handle_left", [12., 5.]),
                                        ("handle_right", [10., 5.])])
def test_raw_profile_refuses_relocation_or_crossed_handles(fixture, field, pair):
    mod, obj, action, _curve = fixture
    before = authored(mod, action)
    with pytest.raises(mod.BridgeError):
        edit(mod, obj._context, request(obj, keyframes=[{"frame": 11, field: pair}]))
    assert authored(mod, action) == before and obj._leaf_calls == []


def test_identical_requested_values_are_verified_without_native_assignment(fixture):
    mod, obj, _action, curve = fixture
    result = edit(mod, obj._context, request(obj, keyframes=[{"frame": 11, "co": [11., 10.]}]))
    assert curve.keyframe_points[1].co == [11., 10.]
    assert result["recovery_evidence"]["owned_field_attempts"] == 0
    assert obj._leaf_calls == []


def test_co_and_handle_rounding_are_independent_float32_and_preserve_zero_sign(fixture):
    mod, obj, _action, curve = fixture
    result = edit(mod, obj._context, request(obj, keyframes=[{"frame": 1, "co": [1., .1], "handle_left": [-0., -.1]}]))
    point = curve.keyframe_points[0]
    assert struct.pack("<ff", *point.co) == struct.pack("<ff", 1., .1)
    assert struct.pack("<ff", *point.handle_left) == struct.pack("<ff", -0., -.1)
    assert point.handle_right == [2., 0.]
    assert struct.pack("<ff", *result["keyframes"][0]["co"]) == struct.pack("<ff", 1., .1)


@pytest.mark.parametrize("change", ["pause", "emergency", "permission", "cancel", "toolset", "session",
                                    "binding", "content", "consumer", "object_uid", "action_uid", "frame"])
def test_live_boundary_changes_before_first_assignment_are_refused(fixture, change):
    mod, obj, action, curve = fixture
    def callback():
        assert obj._leaf_live == []
        if change == "pause":
            obj._flags["paused"] = True
        elif change == "emergency":
            obj._flags["emergency_stopped"] = True
        elif change == "permission":
            obj._grants["EDIT_ANIMATION"] = False
        elif change == "cancel":
            raise mod.BridgeError("OPERATION_FAILED", "Canceled")
        elif change == "toolset":
            obj._context.registry.disable_toolset("animation")
        elif change == "session":
            obj._bpy.data.filepath = "/new.blend"
        elif change == "binding":
            obj.animation_data.action = None
        elif change == "content":
            curve.keyframe_points[0].easing = "EASE_IN"
        elif change == "consumer":
            action.external_users += 1
        elif change == "object_uid":
            obj.session_uid += 1
        elif change == "action_uid":
            action.session_uid += 1
        else:
            obj._bpy.context.scene.frame_current += 1
    obj._context.check_cancelled = callback
    with pytest.raises(mod.BridgeError):
        edit(mod, obj._context, request(obj))
    assert curve.keyframe_points[1].co == [11., 10.] and obj._leaf_calls == []


@pytest.mark.parametrize("change", ["pause", "emergency", "permission", "cancel", "manual", "consumer", "binding"])
def test_postwrite_changes_prevent_stale_recovery_and_keep_measured_partial(fixture, change):
    mod, obj, action, curve = fixture
    fired = []
    def source():
        assert obj._leaf_live == []
        if not obj._leaf_calls or fired:
            return obj._grants
        fired.append(True)
        if change == "pause":
            obj._flags["paused"] = True
        elif change == "emergency":
            obj._flags["emergency_stopped"] = True
        elif change == "permission":
            obj._grants["EDIT_ANIMATION"] = False
        elif change == "cancel":
            raise mod.BridgeError("OPERATION_FAILED", "Canceled after write")
        elif change == "manual":
            curve.keyframe_points[0].easing = "EASE_IN"
        elif change == "consumer":
            action.external_users += 1
        else:
            obj.animation_data.action = None
        return obj._grants
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    facts = caught.value.context["recovery_evidence"]
    assert fired == [True] and curve.keyframe_points[1].co == [11., 12.]
    assert facts["owned_field_attempts"] == 1 and facts["restoration_attempts"] == 0
    assert not facts["rollback_verified"] and facts["possible_mutation"]
    assert obj._leaf_live == []


@pytest.mark.parametrize("failure_phase,verified,restored", [("before", 1, 1), ("after", 2, 2)])
def test_native_shaped_failure_restores_only_attempted_measured_prefix(fixture, failure_phase, verified, restored):
    mod, obj, action, _curve = fixture
    before = authored(mod, action)
    def effect(phase, _point, _field, _value, call):
        if call == 2 and phase == failure_phase:
            raise RuntimeError("Controlled one-shot portable setter failure")
    obj._leaf_effect = effect
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    facts = caught.value.context["recovery_evidence"]
    assert authored(mod, action) == before
    assert facts["owned_field_attempts"] == 2 and facts["owned_field_verified"] == verified
    assert facts["restored_fields"] == restored and facts["restoration_attempts"] == restored
    assert facts["rollback_verified"] and not facts["possible_mutation"]
    assert facts["native_update_attempts"] == 0 and obj._leaf_live == []


def test_owned_setter_extra_unpredicted_change_is_not_adopted(fixture):
    mod, obj, _action, curve = fixture
    def effect(phase, _point, _field, _value, call):
        if call == 1 and phase == "after":
            curve.keyframe_points[1].handle_right[1] = 777.
    obj._leaf_effect = effect
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    facts = caught.value.context["recovery_evidence"]
    assert curve.keyframe_points[1].co == [11., 12.] and curve.keyframe_points[1].handle_right[1] == 777.
    assert facts["state_known"] and facts["observed_sha256"] != facts["expected_sha256"]
    assert facts["owned_field_verified"] == 0 and facts["restoration_attempts"] == 0
    assert facts["retained_partial"] and not facts["rollback_verified"]


def test_protected_curve_change_by_failed_setter_is_retained_without_compensation(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    protected.array_index = 1
    action.fcurves.append(protected)
    def effect(phase, _point, _field, _value, call):
        if call == 1 and phase == "after":
            protected.keyframe_points[0].easing = "EASE_OUT"
            raise RuntimeError("Controlled setter side effect on protected curve")
    obj._leaf_effect = effect
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert protected.keyframe_points[0].easing == "EASE_OUT"
    facts = caught.value.context["recovery_evidence"]
    assert facts["restoration_attempts"] == 0 and not facts["rollback_verified"]


def test_readback_failure_after_attempt_records_unknown_state_without_replaying(fixture):
    mod, obj, _action, curve = fixture
    failed, later_providers = [], []
    def read(_action):
        if obj._leaf_calls:
            failed.append(True)
            raise MemoryError("Portable complete Action read failure")
    def source():
        if failed:
            later_providers.append(True)
        return obj._grants
    obj._read_fault = read
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    facts = caught.value.context["recovery_evidence"]
    assert failed == [True] and later_providers == []
    assert curve.keyframe_points[1].co == [11., 12.]
    assert facts["owned_field_attempts"] == 1 and facts["owned_field_verified"] == 0
    assert not facts["state_known"] and facts["observed_sha256"] is None
    assert facts["restoration_attempts"] == 0 and obj._leaf_live == []


@pytest.mark.parametrize("change", ["content", "point_identity", "object_pose"])
def test_final_leaf_complete_cas_refuses_last_reader_changes(fixture, change):
    mod, obj, _action, curve = fixture
    retained = []
    def last_reader():
        if change == "content":
            curve.keyframe_points[0].easing = "EASE_OUT"
        elif change == "point_identity":
            old = curve.keyframe_points[1]
            curve.keyframe_points[1] = copy.deepcopy(old)
            retained.append(old)  # No allocator-ABA simulation.
        else:
            obj.location = [3., 2., 1.]
    obj._leaf_precheck = last_reader
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert obj._leaf_calls == [] and curve.keyframe_points[1].co == [11., 10.]
    assert caught.value.context["recovery_evidence"]["restoration_attempts"] == 0


def test_same_content_new_native_point_identity_is_not_adopted(fixture):
    mod, obj, _action, curve = fixture
    retained = []
    def source():
        if not retained:
            old = curve.keyframe_points[1]
            curve.keyframe_points[1] = copy.deepcopy(old)
            retained.append(old)
        return obj._grants
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert obj._leaf_calls == [] and caught.value.context["recovery_evidence"]["owned_field_attempts"] == 0


def test_retained_whole_action_plan_cannot_be_replaced_or_rebased(fixture):
    mod, obj, _action, curve = fixture
    params = request(obj)
    spec = obj._context.registry.get("animation.curve_edit")
    with (obj._context.registry.mutation_entry(spec, params, obj._context),
          obj._context.registry.checkpoint_admission(spec, params, obj._context) as binding):
        writer = binding.callback
        frozen = writer.plan.before
        writer.plan = replace(writer.plan)
        with pytest.raises(mod.BridgeError):
            writer.execute()
        assert writer._plan.before is frozen and obj._leaf_calls == []
    assert curve.keyframe_points[1].co == [11., 10.]


@pytest.mark.parametrize("service", ["state", "request_lifecycle", "check_final_request", "check_final_job", "checkpoints", "permissions"])
def test_provider_cannot_replace_original_caller_services(fixture, service):
    mod, obj, _action, _curve = fixture
    invoked = []
    replacements = {"state": NS(snapshot=lambda: invoked.append(True) or {}),
                    "request_lifecycle": NS(check=lambda: invoked.append(True)),
                    "check_final_request": lambda: invoked.append(True),
                    "check_final_job": lambda: invoked.append(True), "checkpoints": object(),
                    "permissions": NS(require=lambda *_: invoked.append(True))}
    def source():
        binding = obj._context.checkpoint_admission
        if binding is not None and binding.callback.in_gate:
            setattr(obj._context, service, replacements[service])
        return obj._grants
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError):
        edit(mod, obj._context, request(obj))
    assert obj._leaf_calls == [] and invoked == []


def test_permission_denial_latches_without_later_regrant_or_compensation(fixture):
    mod, obj, _action, curve = fixture
    denied, late = [], []
    def source():
        if denied:
            late.append(True)
            return obj._grants
        if obj._leaf_calls:
            denied.append(True)
            return {**obj._grants, "EDIT_ANIMATION": False}
        return obj._grants
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert denied == [True] and late == [] and curve.keyframe_points[1].co == [11., 12.]
    assert caught.value.context["recovery_evidence"]["restoration_attempts"] == 0


def test_manual_edit_during_recovery_prevents_stale_compensation(fixture):
    mod, obj, _action, curve = fixture
    failed = []
    def effect(phase, _point, _field, _value, call):
        if call == 2 and phase == "before":
            failed.append(True)
            raise RuntimeError("Controlled setter failure")
    def source():
        if failed:
            curve.keyframe_points[0].easing = "EASE_IN_OUT"
        return obj._grants
    obj._leaf_effect = effect
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    facts = caught.value.context["recovery_evidence"]
    assert curve.keyframe_points[1].co == [11., 12.] and curve.keyframe_points[0].easing == "EASE_IN_OUT"
    assert facts["restoration_attempts"] == 0 and not facts["rollback_verified"]


def test_nested_structured_and_raw_handler_entry_are_refused(fixture):
    mod, obj, _action, _curve = fixture
    params, blocked = request(obj), []
    def source():
        for invoke in (lambda: edit(mod, obj._context, params), lambda: mod.curve_edit(obj._context, params)):
            with pytest.raises(mod.BridgeError) as caught:
                invoke()
            blocked.append(caught.value.context["reason"])
        return obj._grants
    obj._context.permissions._source = source
    result = edit(mod, obj._context, params)
    assert blocked and set(blocked) == {"REENTRANT_MUTATION_BLOCKED"}
    assert result["recovery_evidence"]["owned_field_verified"] == 2
    assert obj._context.registry._mutation_interlock.owner is None


def test_output_format_failure_retains_completed_write_evidence(fixture, monkeypatch):
    mod, obj, _action, curve = fixture
    def failed(_writer):
        raise MemoryError("Controlled primitive output format failure")
    monkeypatch.setattr(mod, "_curve_result", failed)
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    facts = caught.value.context["recovery_evidence"]
    assert curve.keyframe_points[1].co == [11., 12.]
    assert facts["owned_field_verified"] == 2 and facts["native_update_attempts"] == 0
    assert facts["retained_partial"] and facts["verification_required"]


def test_late_descriptor_refusal_latches_before_attempt_or_regrant(fixture, monkeypatch):
    mod, obj, _action, _curve = fixture
    invalid, refused, late = [], [], []
    def schema(*_):
        if invalid:
            refused.append(True)
            raise mod.BridgeError("NOT_IMPLEMENTED", "Portable native descriptor became readonly")
    def source():
        if refused:
            late.append(True)
            invalid.clear()
        else:
            invalid.append(True)
        return obj._grants
    monkeypatch.setattr(mod, "_curve_write_schema", schema)
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert refused == [True] and late == [] and obj._leaf_calls == []
    assert caught.value.context["recovery_evidence"]["restoration_refused"] == "INVALID_NATIVE_SCOPE"


@pytest.mark.parametrize("drift", ["extra_user", "slot_name", "point_identity"])
def test_unedited_action_structural_metadata_and_identity_remain_protected(fixture, drift):
    mod, obj, _action, curve = fixture
    peer = Action(name="OtherMotion", env=NS(), external_users=0, use_fake_user=False,
                  fcurves=[copy.deepcopy(curve)], is_action_layered=False, library=None,
                  override_library=None, is_editable=True, session_uid=104, as_pointer=lambda: 1004,
                  slots=[NS(name="PeerSlot", identifier="OBPeer", handle=9, target_id_type="OBJECT")])
    peer.env.obj = NS(animation_data=NS(action=None))
    obj._bpy.data.actions.append(peer)
    retained = []
    def source():
        if drift == "extra_user":
            peer.use_extra_user = True
        elif drift == "slot_name":
            peer.slots[0].name = "ChangedSlot"
        elif not retained:
            old = peer.fcurves[0].keyframe_points[0]
            peer.fcurves[0].keyframe_points[0] = copy.deepcopy(old)
            retained.append(old)
        return obj._grants
    obj._context.permissions._source = source
    with pytest.raises(mod.BridgeError):
        edit(mod, obj._context, request(obj))
    assert obj._leaf_calls == [] and curve.keyframe_points[1].co == [11., 10.]


def test_layered_raw_authoring_changes_only_the_bound_slot(fixture):
    mod, obj, action, curve = fixture
    protected = copy.deepcopy(curve)
    action.is_action_layered = True
    obj.animation_data.action_slot = NS(identifier="OBActor", handle=7, target_id_type="OBJECT")
    action.slots = [obj.animation_data.action_slot, NS(identifier="OBProtected", handle=9, target_id_type="OBJECT")]
    action.layers = [NS(strips=[NS(channelbags=[NS(slot_handle=9, fcurves=[protected], groups=[]),
                                               NS(slot_handle=7, fcurves=[curve], groups=[])])])]
    before = mod.scope.curve_content(protected)
    result = edit(mod, obj._context, request(obj, slot_identifier="OBActor"))
    assert result["slot_identifier"] == "OBActor" and mod.scope.curve_content(protected) == before
    assert curve.keyframe_points[1].co == [11., 12.]


def test_profile_factory_refusal_preserves_live_permission_denial_precedence(fixture):
    mod, obj, _action, curve = fixture
    curve.keyframe_points[1].handle_left = [12., 0.]
    obj._grants["EDIT_ANIMATION"] = False
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    assert caught.value.code == "PERMISSION_DENIED" and obj._leaf_calls == []


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

def test_action_copy_budget_rejects_before_native_allocation(fixture):
    mod, obj, source, curve = fixture
    curve.keyframe_points = [Point(i, 0) for i in range(1025)]
    with pytest.raises(mod.BridgeError) as caught:
        mod.action_copy(obj._context, {"object_name": obj.name, "new_name": "TooLarge"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert obj.animation_data.action is source

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

@pytest.fixture
def setter_metadata(addon_package, monkeypatch):
    """Descriptor-only portable model; does not qualify a native setter."""
    module = importlib.import_module(f"{addon_package}.tools.animation_curves")
    native = importlib.import_module(f"{addon_package}.tools._scene_mutation")
    descriptors = []
    monkeypatch.setattr(native, "descriptors", lambda *_: descriptors)
    return module, descriptors

@pytest.mark.parametrize("field,value", [("extrapolation", "LINEAR"), ("interpolation", "BEZIER"),
                                         ("easing", "EASE_IN"), ("handle_left_type", "FREE"),
                                         ("handle_right_type", "FREE")])
@pytest.mark.parametrize("array_bomb", [False, True])
def test_enum_setter_uses_declared_nonnumeric_metadata_without_array_api(setter_metadata, field, value, array_bomb):
    module, descriptors = setter_metadata
    class NonArrayEnum(NS):
        @property
        def array_length(self):
            pytest.fail("Source-defined EnumProperty has no numeric array API")
    kind = NonArrayEnum if array_bomb else NS
    prop = kind(identifier=field, type="ENUM", is_readonly=False, is_runtime=False,
                is_registered=False, enum_items=[NS(identifier=value)])
    if not array_bomb:
        assert not hasattr(prop, "array_length")
    descriptors.append(prop)
    module._curve_write_schema(object(), object(), field, value)

@pytest.mark.parametrize("length", [None, False, True, 0, 1, 3, 2.0, "2"])
def test_coordinate_setter_requires_exact_explicit_float2_length(setter_metadata, length):
    module, descriptors = setter_metadata
    descriptors.append(NS(identifier="handle_left", type="FLOAT", is_readonly=False, is_runtime=False,
                          is_registered=False, array_length=length))
    with pytest.raises(module.BridgeError) as caught:
        module._curve_write_schema(object(), object(), "handle_left", (0., 0.))
    assert caught.value.code == "NOT_IMPLEMENTED"

def test_coordinate_setter_refuses_missing_numeric_metadata_instead_of_defaulting(setter_metadata):
    module, descriptors = setter_metadata
    descriptors.append(NS(identifier="handle_left", type="FLOAT", is_readonly=False, is_runtime=False,
                          is_registered=False))
    with pytest.raises(module.BridgeError) as caught:
        module._curve_write_schema(object(), object(), "handle_left", (0., 0.))
    assert caught.value.code == "NOT_IMPLEMENTED"

def test_coordinate_setter_preserves_exact_float2_hard_range_check(setter_metadata):
    module, descriptors = setter_metadata
    descriptors.append(NS(identifier="handle_left", type="FLOAT", is_readonly=False, is_runtime=False,
                          is_registered=False, array_length=2, hard_min=-1., hard_max=1.))
    module._curve_write_schema(object(), object(), "handle_left", (-0., 1.))
    with pytest.raises(module.BridgeError) as caught:
        module._curve_write_schema(object(), object(), "handle_left", (-1., 1.0001))
    assert caught.value.code == "NOT_IMPLEMENTED"

@pytest.mark.parametrize("invalid", [None, False, 1])
def test_enum_descriptor_items_require_typed_identifiers(setter_metadata, invalid):
    module, descriptors = setter_metadata
    descriptors.append(NS(identifier="extrapolation", type="ENUM", is_readonly=False, is_runtime=False,
                          is_registered=False, enum_items=[NS(identifier=invalid), NS(identifier="LINEAR")]))
    with pytest.raises(module.BridgeError) as caught:
        module._curve_write_schema(object(), object(), "extrapolation", "LINEAR")
    assert caught.value.code == "NOT_IMPLEMENTED"

def test_enum_setter_rejects_unavailable_value_and_oversized_inventory(setter_metadata):
    module, descriptors = setter_metadata
    prop = NS(identifier="extrapolation", type="ENUM", is_readonly=False, is_runtime=False,
              is_registered=False, enum_items=[NS(identifier="CONSTANT")])
    descriptors.append(prop)
    with pytest.raises(module.BridgeError):
        module._curve_write_schema(object(), object(), "extrapolation", "LINEAR")
    prop.enum_items = [NS(identifier="LINEAR")] * 257
    with pytest.raises(module.BridgeError) as caught:
        module._curve_write_schema(object(), object(), "extrapolation", "LINEAR")
    assert caught.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("change", ["expected", "params", "internal_params"])
def test_provider_cannot_adopt_observed_baseline_or_change_original_intent(fixture, change):
    mod, obj, _action, curve = fixture
    params = request(obj)
    spec = obj._context.registry.get("animation.curve_edit")
    with (obj._context.registry.mutation_entry(spec, params, obj._context),
          obj._context.registry.checkpoint_admission(spec, params, obj._context) as binding):
        writer = binding.callback
        frozen = writer.plan.before
        def source():
            if change == "expected":
                curve.keyframe_points[0].easing = "EASE_OUT"
                writer.expected = writer.reader.action_content(obj.animation_data.action)
            elif change == "params":
                params["keyframes"][0]["co"][1] = 99.
            else:
                writer.params["keyframes"][0]["co"][1] = 99.
            return obj._grants
        obj._context.permissions._source = source
        with pytest.raises(mod.BridgeError):
            writer.execute()
        assert writer.plan.before is frozen and obj._leaf_calls == []


def test_provider_replaced_wrappers_are_resolved_fresh_without_dropping_point_identity(fixture):
    mod, obj, _action, curve = fixture
    class Ephemeral(Point):
        invalid = False
        def __getattribute__(self, field):
            if field in {"co", "co_ui", *mod._POINT_FIELDS} and object.__getattribute__(self, "invalid"):
                raise ReferenceError("Expired portable point wrapper")
            return super().__getattribute__(field)
        def __setattr__(self, field, value):
            if field in mod._POINT_FIELDS and object.__getattribute__(self, "invalid"):
                pytest.fail("Point wrapper retained across a provider was written")
            super().__setattr__(field, value)
    curve.keyframe_points = [Ephemeral(1, 0), Ephemeral(11, 10)]
    for i, point in enumerate(curve.keyframe_points):
        point._native_pointer = 2000 + i
    expired = []
    def source():
        assert obj._leaf_live == []
        previous, replacement = curve.keyframe_points, []
        for point in previous:
            fresh = Ephemeral(*point.co)
            fresh.__dict__.update(copy.deepcopy(point.__dict__))
            replacement.append(fresh)
        curve.keyframe_points = replacement
        for point in previous:
            point.invalid = True
            expired.append(point)
        return obj._grants
    obj._context.permissions._source = source
    result = edit(mod, obj._context, request(obj))
    assert expired and all(point.invalid for point in expired)
    assert curve.keyframe_points[1].co == [11., 12.]
    assert result["recovery_evidence"]["owned_field_verified"] == 2
    assert [point._native_pointer for point in curve.keyframe_points] == [2000, 2001]


def test_control_interruption_releases_leaf_and_preserves_unknown_effect_evidence(fixture):
    mod, obj, _action, curve = fixture
    def effect(phase, _point, _field, _value, _call):
        if phase == "after":
            raise KeyboardInterrupt("Controlled portable interruption")
    obj._leaf_effect = effect
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj))
    facts = caught.value.context["recovery_evidence"]
    assert obj._leaf_live == [] and curve.keyframe_points[1].co == [11., 12.]
    assert facts["owned_field_attempts"] == 1 and facts["owned_field_verified"] == 0
    assert not facts["state_known"] and facts["observed_sha256"] is None
    assert facts["restoration_attempts"] == 0 and facts["restoration_refused"] == "NATIVE_INTERRUPTED"


def test_setter_no_effect_is_measured_as_original_and_never_claimed_success(fixture):
    mod, obj, action, _curve = fixture
    before = authored(mod, action)
    def effect(phase, point, field, _value, _call):
        if phase == "after":
            assert field == "co"
            point.co = [11., 10.]
    obj._leaf_effect = effect
    with pytest.raises(mod.BridgeError) as caught:
        edit(mod, obj._context, request(obj, keyframes=[{"frame": 11, "co": [11., 12.]}]))
    facts = caught.value.context["recovery_evidence"]
    assert authored(mod, action) == before and facts["owned_field_attempts"] == 1
    assert facts["owned_field_verified"] == facts["restoration_attempts"] == 0
    assert facts["rollback_verified"] and not facts["possible_mutation"]
