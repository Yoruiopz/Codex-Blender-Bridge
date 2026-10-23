"""Independent native-channel predictions and context-free target observations."""

from __future__ import annotations

import ast
import importlib
import json
import math
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def intent_case(addon_package):
    module = importlib.import_module(f"{addon_package}.artist_target_intent")

    def prop(name, kind, length=0):
        values = dict(identifier=name, type=kind, is_runtime=False, is_registered=False,
                      is_registered_optional=False, is_array=bool(length))
        # Native String/Enum properties need not expose a numeric array length.
        if kind in {"FLOAT", "INT"}:
            values["array_length"] = length
        if kind == "FLOAT":
            values.update(hard_min=-3.4028234663852886e38, hard_max=3.4028234663852886e38)
        return NS(**values)

    properties = {name: prop(name, kind) for name, kind in (("name", "STRING"), ("session_uid", "INT"), ("rotation_mode", "ENUM"))}
    properties.update({name: prop(name, "FLOAT", length) for name, length in module.VECTOR_LENGTHS.items()})
    schema = NS(identifier="Object", properties=properties, as_pointer=lambda: 2000)

    class NativeObject:
        bl_rna = schema

        def __init__(self, *, name="Working", uid=5, pointer=100):
            object.__setattr__(self, "_reads", [])
            object.__setattr__(self, "_writes", [])
            object.__setattr__(self, "_traps", set())
            for field, value in dict(name=name, session_uid=uid, pointer=pointer, rotation_mode="XYZ",
                    location=(0., 0., 0.), rotation_euler=(.125, -.25, .5),
                    rotation_quaternion=(.5, .5, .5, .5), rotation_axis_angle=(.75, 1., 0., 0.), scale=(1., 1., 1.)).items():
                object.__setattr__(self, field, value)

        def __getattribute__(self, name):
            if name in module.CORE_FIELDS:
                object.__getattribute__(self, "_reads").append(name)
                if name in object.__getattribute__(self, "_traps"):
                    raise AssertionError("Unqualified native channel getter: " + name)
            return object.__getattribute__(self, name)

        def __setattr__(self, name, value):
            if not name.startswith("_"):
                self._writes.append(name)
            object.__setattr__(self, name, value)

        def as_pointer(self):
            return self.pointer

    class Lookup(dict):
        def __init__(self, *args):
            super().__init__(*args)
            self.lookups = []

        def get(self, name):
            self.lookups.append(name)
            return super().get(name)

    class Bpy:
        @property
        def context(self):
            raise AssertionError("A core-channel observation must never touch context")

    obj = NativeObject()
    bpy = Bpy()
    bpy.types = NS(Object=NativeObject)
    bpy.data = NS(objects=Lookup({obj.name: obj}))
    return NS(module=module, obj=obj, bpy=bpy, properties=properties, schema=schema,
              NativeObject=NativeObject, capture=lambda **params: module.capture_intent(bpy, obj, params))


def apply_expected(case, intent):
    for field, value in intent.expected_channels:
        setattr(case.obj, field, value)
    case.obj._reads.clear()
    case.obj._writes.clear()


def test_independent_decimal_rounding_and_signed_zero_are_frozen_before_apply(intent_case):
    case = intent_case
    params = {"location": [.1, .2, -0.]}
    intent = case.module.capture_intent(case.bpy, case.obj, params)
    assert intent.availability == "available" and intent.reason is None
    expected = dict(intent.expected_channels)
    bits = dict(intent.expected_bits)
    assert expected["location"] == (13421773 / 134217728, 13421773 / 67108864, -0.)
    assert bits["location"] == ("cdcccc3d", "cdcc4c3e", "00000080")
    params["location"][0] = 99.
    assert dict(intent.expected_channels)["location"][0] == 13421773 / 134217728
    with pytest.raises(FrozenInstanceError):
        intent.pointer = 9
    assert not case.obj._writes
    apply_expected(case, intent)
    observed = case.module.read_target(case.bpy, intent)
    compared = case.module.compare_target(intent, observed)
    assert compared["status"] == "channels_match" and not compared["differences"]
    assert compared["comparison_complete"] and not compared["user_goal_verified"]
    assert not compared["scene_evaluated"] and not compared["includes_parent_or_delta_transforms"]
    assert not case.obj._writes and case.bpy.data.objects.lookups == ["Working"]


def test_intent_equality_and_comparison_preserve_signed_zero(intent_case):
    case = intent_case
    positive = case.capture(location=[0., 0., 0.])
    negative = case.capture(location=[-0., 0., 0.])
    assert positive.expected_channels == negative.expected_channels and positive != negative
    result = case.module.compare_target(negative, case.module.read_target(case.bpy, negative))
    assert result["status"] == "channels_differ"
    assert result["differences"][0]["different_components"] == [0]
    assert result["differences"][0]["expected_float32_le"][0] == "00000080"
    assert result["differences"][0]["observed_float32_le"][0] == "00000000"


@pytest.mark.parametrize("mode", ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX", "QUATERNION", "AXIS_ANGLE"])
def test_location_scale_keep_mode_and_every_inactive_rotation_literal(intent_case, mode):
    case = intent_case
    case.obj.rotation_mode = mode
    case.obj._writes.clear()
    intent = case.capture(location=[.1, -.2, .3], scale=[-2., .5, 1.25])
    assert intent.availability == "available"
    before, expected = dict(intent.before_channels), dict(intent.expected_channels)
    for field in ("rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle"):
        assert expected[field] == before[field]
    apply_expected(case, intent)
    result = case.module.compare_target(intent, case.module.read_target(case.bpy, intent))
    assert result["status"] == "channels_match" and not case.obj._writes


@pytest.mark.parametrize("mode", ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"])
def test_euler_assignment_predicts_only_same_mode_without_converting_inactive_channels(intent_case, mode):
    case = intent_case
    case.obj.rotation_mode = mode
    intent = case.capture(rotation=[.25, -.5, .75], rotation_mode=mode)
    assert intent.availability == "available"
    before, expected = dict(intent.before_channels), dict(intent.expected_channels)
    assert expected["rotation_euler"] == (.25, -.5, .75)
    for field in ("location", "rotation_mode", "rotation_quaternion", "rotation_axis_angle", "scale"):
        assert before[field] == expected[field]


@pytest.mark.parametrize(("mode", "params"), [
    ("XYZ", {"location": [1., 2., 3.], "rotation_mode": "ZYX"}),
    ("QUATERNION", {"rotation": [.1, .2, .3]}),
    ("AXIS_ANGLE", {"rotation": [.1, .2, .3], "rotation_mode": "XYZ"}),
])
def test_unqualified_mode_conversion_is_unavailable_without_native_writes(intent_case, mode, params):
    case = intent_case
    case.obj.rotation_mode = mode
    case.obj._writes.clear()
    intent = case.module.capture_intent(case.bpy, case.obj, params)
    assert intent.availability == "unavailable" and intent.reason == "rotation_mode_conversion_unavailable"
    assert not case.obj._writes


@pytest.mark.parametrize("value", [1e-40, -1e-40, 1_000_001., -1_000_001., math.inf, math.nan, True, 1 << 2000])
def test_nonfinite_extreme_subnormal_and_non_numeric_intent_is_explicitly_unavailable(intent_case, value):
    case = intent_case
    intent = case.capture(location=[value, 0., 0.])
    assert intent.availability == "unavailable" and intent.reason
    assert not case.obj._writes


def test_native_clamping_is_not_predicted_as_a_success(intent_case):
    case = intent_case
    case.properties["scale"].hard_min, case.properties["scale"].hard_max = -2., 2.
    intent = case.capture(scale=[3., 1., 1.])
    assert intent.availability == "unavailable" and intent.reason == "requested_native_clamping_unavailable:scale"
    assert not case.obj._writes


@pytest.mark.parametrize(("field", "flag", "value"), [
    ("location", "is_runtime", True), ("rotation_mode", "is_registered", True),
    ("scale", "is_registered_optional", True), ("rotation_euler", "type", "INT"),
    ("rotation_quaternion", "array_length", 3), ("rotation_axis_angle", "is_array", False),
])
def test_every_core_descriptor_is_screened_before_the_first_channel_getter(intent_case, field, flag, value):
    case = intent_case
    setattr(case.properties[field], flag, value)
    case.obj._traps.update(case.module.CORE_FIELDS)
    intent = case.capture(location=[1., 2., 3.])
    assert intent.availability == "unavailable" and intent.reason.startswith("native_descriptor_unavailable:")
    assert not case.obj._reads and not case.obj._writes


def test_a_legacy_descriptor_free_preview_gets_unavailable_without_reading_new_getters(intent_case):
    class Legacy:
        @property
        def name(self):
            raise AssertionError("No fallback getter may run")
    intent = intent_case.module.capture_intent(NS(), Legacy(), {"location": [1., 2., 3.]})
    assert intent.availability == "unavailable" and intent.object_name is None


@pytest.mark.parametrize("field", ["uid", "pointer"])
def test_replacement_is_reported_before_any_replacement_channel_value(intent_case, field):
    case = intent_case
    intent = case.capture(location=[1., 2., 3.])
    replacement = case.NativeObject(uid=6 if field == "uid" else 5, pointer=101 if field == "pointer" else 100)
    replacement._traps.update(case.module.CORE_FIELDS)
    case.bpy.data.objects["Working"] = replacement
    observed = case.module.read_target(case.bpy, intent)
    assert observed["status"] == "replaced" and not replacement._reads
    result = case.module.compare_target(intent, observed)
    assert result["status"] == "target_replaced" and not result["comparison_complete"]
    assert not result["compared_fields"] and not result["user_goal_verified"]


def test_missing_exact_name_is_explicit_and_lookup_does_not_scan_other_objects(intent_case):
    case = intent_case
    intent = case.capture(location=[1., 2., 3.])
    del case.bpy.data.objects["Working"]
    observed = case.module.read_target(case.bpy, intent)
    result = case.module.compare_target(intent, observed)
    assert observed == {"status": "missing", "identity": None}
    assert result["status"] == "target_missing" and not result["comparison_complete"]
    assert case.bpy.data.objects.lookups == ["Working"]


def test_manual_native_drift_is_not_adopted_as_expected_output(intent_case):
    case = intent_case
    intent = case.capture(location=[1., 2., 3.])
    apply_expected(case, intent)
    case.obj.location = (1., 99., 3.)
    case.obj._writes.clear()
    result = case.module.compare_target(intent, case.module.read_target(case.bpy, intent))
    assert result["status"] == "channels_differ"
    assert result["differences"][0]["expected"] == [1., 2., 3.]
    assert result["differences"][0]["observed"] == [1., 99., 3.]
    assert result["differences"][0]["different_components"] == [1]
    assert dict(intent.expected_channels)["location"] == (1., 2., 3.) and not case.obj._writes


def test_a_later_huge_finite_manual_value_still_reports_drift(intent_case):
    case = intent_case
    intent = case.capture(location=[1., 2., 3.])
    apply_expected(case, intent)
    case.obj.location = (float(1 << 30), 2., 3.)
    result = case.module.compare_target(intent, case.module.read_target(case.bpy, intent))
    assert result["status"] == "channels_differ"


def test_read_rechecks_native_descriptors_and_finite_values(intent_case):
    case = intent_case
    intent = case.capture(location=[1., 2., 3.])
    case.properties["scale"].is_runtime = True
    case.obj._reads.clear()
    case.obj._traps.update(case.module.CORE_FIELDS)
    with pytest.raises(case.module.BridgeError) as caught:
        case.module.read_target(case.bpy, intent)
    assert caught.value.code == "NOT_IMPLEMENTED" and not case.obj._reads
    case.obj._traps.clear()
    case.properties["scale"].is_runtime = False
    case.obj.location = (math.nan, 0., 0.)
    with pytest.raises(case.module.BridgeError) as caught:
        case.module.read_target(case.bpy, intent)
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_unavailable_intent_is_refused_before_looking_up_blender_data(intent_case):
    case = intent_case
    intent = case.module.TargetIntent()
    with pytest.raises(case.module.BridgeError) as caught:
        case.module.read_target(NS(), intent)
    assert caught.value.code == "NOT_IMPLEMENTED" and not case.bpy.data.objects.lookups


def test_public_data_is_plain_bounded_and_never_claims_evaluated_or_artistic_success(intent_case):
    case = intent_case
    public = case.module.public_intent(case.capture(location=[1., 2., 3.]))
    assert json.loads(json.dumps(public, allow_nan=False)) == public
    assert public["compared_fields"] == list(case.module.CORE_FIELDS)
    assert public["numeric_profile"]["maximum_magnitude"] == 1_000_000.
    assert not any(public[field] for field in ("user_goal_verified", "scene_evaluated", "includes_parent_or_delta_transforms"))
    assert len(json.dumps(public)) < 4096


def test_helper_contains_no_context_or_evaluation_api_reads(intent_case):
    source = Path(intent_case.module.__file__).read_text()
    tree = ast.parse(source)
    forbidden = {"context", "evaluated_get", "evaluated_depsgraph_get", "matrix_world", "selected_objects", "view_layer"}
    assert not [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in forbidden]
