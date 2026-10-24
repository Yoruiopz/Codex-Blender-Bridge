"""Raw quaternion validation and retained provenance, without fake native admission.

Successful native authoring/compensation is qualified by the opt-in Blender
fixture. These tests never relax the production native type/profile gates.
"""
from __future__ import annotations

import importlib
import math
import struct
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def quaternion(addon_package):
    return NS(
        transforms=importlib.import_module(f"{addon_package}.tools.transforms"),
        loop=importlib.import_module(f"{addon_package}.tools.artist_loop"),
        admission=importlib.import_module(f"{addon_package}.tools._artist_checkpoint_admission"),
        registry=importlib.import_module(f"{addon_package}.tool_registry"),
        state=importlib.import_module(f"{addon_package}.state"),
        permissions=importlib.import_module(f"{addon_package}.permissions"),
    )


def request(quaternion, values, **other):
    return quaternion.transforms.quaternion_request({"rotation_quaternion": values, **other})


@pytest.mark.parametrize("values", [
    [1, 0, 0, 0], [-1., -0., 0., -0.],
    [math.sqrt(.5), math.sqrt(.5), -0., 0.],
    [math.sqrt(.5), -0., math.sqrt(.5), 0.],
    [math.sqrt(.5), -0., 0., math.sqrt(.5)],
    [-math.sqrt(.5), -0., -0., -math.sqrt(.5)],
    [value / math.sqrt(.3) for value in (.1, .2, .3, .4)],
    [1. - .9e-6, 0., 0., 0.],
])
def test_request_retains_raw_wxyz_and_zero_signs_without_normalization(quaternion, values):
    before = deepcopy(values)
    parsed = request(quaternion, values)
    assert tuple(value.hex() for value in parsed) == tuple(float(value).hex() for value in values)
    assert [float(value).hex() for value in values] == [float(value).hex() for value in before]
    assert abs(math.sqrt(sum(value * value for value in parsed)) - 1.) <= 1e-6


@pytest.mark.parametrize("values", [
    None, "1,0,0,0", {}, [1., 0., 0.], [1., 0., 0., 0., 0.],
    [True, 0., 0., 0.], [1., False, 0., 0.], ["1", 0., 0., 0.],
    [float("nan"), 0., 0., 0.], [float("inf"), 0., 0., 0.],
    [0., 0., 0., 0.], [.5, 0., 0., 0.], [1. - 1.1e-6, 0., 0., 0.],
])
def test_invalid_numeric_requests_are_invalid_argument(quaternion, values):
    with pytest.raises(quaternion.transforms.BridgeError) as caught:
        request(quaternion, values)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("values", [
    [1.00000001, 0., 0., 0.], [1., 2. ** -127, 0., 0.],
    [1., -2. ** -150, 0., 0.], [10 ** 400, 0., 0., 0.],
])
def test_finite_unqualified_storage_is_explicitly_not_implemented(quaternion, values):
    with pytest.raises(quaternion.transforms.BridgeError) as caught:
        request(quaternion, values)
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_minimum_normal_component_is_supported_and_rounding_norm_is_independent(quaternion):
    assert request(quaternion, [1., 2. ** -126, -0., 0.])[1] == 2. ** -126
    # Requested norm is inside the bound; independent native rounding crosses it.
    raw = .999999001
    assert abs(raw - 1.) < 1e-6
    rounded = struct.unpack("<f", struct.pack("<f", raw))[0]
    assert abs(rounded - 1.) > 1e-6
    with pytest.raises(quaternion.transforms.BridgeError) as caught:
        request(quaternion, [raw, 0., 0., 0.])
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("name,value", [
    ("rotation", [0., 0., 0.]), ("rotation_euler", None),
    ("rotation_mode", None), ("rotation_mode", "QUATERNION"),
])
def test_any_rotation_field_presence_conflicts_even_null(quaternion, name, value):
    with pytest.raises(quaternion.transforms.BridgeError) as caught:
        request(quaternion, [1., 0., 0., 0.], **{name: value})
    assert caught.value.code == "INVALID_ARGUMENT"


def test_preview_parse_preserves_original_wxyz_and_legacy_euler_conversion(quaternion):
    obj = NS(name="Working", rotation_mode="QUATERNION")
    values = [math.sqrt(.5), math.sqrt(.5), -0., 0.]
    parsed = quaternion.loop._preview_params({"rotation_quaternion": values, "location": [.1, .2, -0.]}, obj)
    assert parsed["object_name"] == "Working" and "rotation_mode" not in parsed
    assert [value.hex() for value in parsed["rotation_quaternion"]] == [value.hex() for value in values]
    assert parsed["rotation_quaternion"] is not values
    assert quaternion.loop._preview_params({"rotation": [.1, .2, .3]}, obj) == {
        "object_name": "Working", "rotation": [.1, .2, .3], "rotation_mode": "XYZ"}


def retained_preview(quaternion):
    params = {"object_name": "Working", "rotation_quaternion": [math.sqrt(.5), math.sqrt(.5), -0., 0.]}
    intent = quaternion.transforms.TargetIntent(availability="available")
    origin = quaternion.transforms.QuaternionPreviewOrigin(quaternion.registry._checkpoint_parameters(params), intent)
    return {"params": params, "target_intent": intent, "quaternion_origin": origin, "step_association": None}


def test_unlinked_preview_retains_creation_time_independent_intent(quaternion):
    preview = retained_preview(quaternion)
    origin = quaternion.transforms.check_quaternion_preview(preview)
    assert origin is preview["quaternion_origin"] and origin.intent is preview["target_intent"]
    with pytest.raises(FrozenInstanceError):
        origin.intent = replace(origin.intent)
    assert quaternion.transforms.check_quaternion_preview(preview) is origin


@pytest.mark.parametrize("change", ["zero_sign", "intent_identity", "request_removed", "field_added_to_legacy", "unavailable"])
def test_preview_changes_do_not_adopt_a_new_intent_or_numeric_equal_zero(quaternion, change):
    preview = retained_preview(quaternion)
    if change == "zero_sign":
        preview["params"]["rotation_quaternion"][2] = 0.
    elif change == "intent_identity":
        preview["target_intent"] = replace(preview["target_intent"])
    elif change == "request_removed":
        del preview["params"]["rotation_quaternion"]
    elif change == "field_added_to_legacy":
        del preview["quaternion_origin"]
    else:
        intent = quaternion.transforms.TargetIntent()
        preview["target_intent"] = intent
        preview["quaternion_origin"] = quaternion.transforms.QuaternionPreviewOrigin(
            quaternion.registry._checkpoint_parameters(preview["params"]), intent)
    with pytest.raises(quaternion.transforms.BridgeError) as caught:
        quaternion.transforms.check_quaternion_preview(preview)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_legacy_preview_does_not_require_quaternion_proof(quaternion):
    assert quaternion.transforms.check_quaternion_preview({"params": {"location": [1., 2., 3.]}}) is None


@pytest.mark.parametrize("change", [None, "params_zero", "intent", "origin", "origin_slot", "params_identity"])
def test_admission_keeps_original_unlinked_preview_proof_through_callbacks(quaternion, change):
    # Exercise only the pure retained-owner CAS, with no native capture or writer.
    preview = retained_preview(quaternion)
    origin = preview["quaternion_origin"]
    guard = object.__new__(quaternion.admission.Admission)
    guard.preview, guard.quaternion_origin = preview, origin
    guard._quaternion_origin_identity = origin
    guard._quaternion_intent_identity = origin.intent
    guard._quaternion_params = preview["params"]
    guard.boundary = object.__new__(quaternion.transforms.QuaternionBoundary)
    guard.boundary.quaternion_intent = origin.intent
    if change == "params_zero":
        preview["params"]["rotation_quaternion"][2] = 0.
    elif change == "intent":
        guard.boundary.quaternion_intent = replace(origin.intent)
    elif change == "origin":
        preview["quaternion_origin"] = replace(origin)
    elif change == "origin_slot":
        guard.quaternion_origin = replace(origin)
    elif change == "params_identity":
        preview["params"] = deepcopy(preview["params"])
    if change is None:
        guard._check_quaternion_owner()
    else:
        with pytest.raises(quaternion.transforms.BridgeError) as caught:
            guard._check_quaternion_owner()
        assert caught.value.code == "INVALID_ARGUMENT"


def test_native_profile_does_not_accept_descriptor_free_objects(quaternion):
    with pytest.raises(quaternion.transforms.BridgeError) as caught:
        quaternion.transforms.quaternion_profile(NS(types=NS()), NS(type="MESH", rotation_mode="QUATERNION"))
    assert caught.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("allowed,code", [(True, "INVALID_ARGUMENT"), (False, "PERMISSION_DENIED")])
def test_registered_invalid_request_never_enters_native_capture_or_checkpoint(quaternion, monkeypatch, allowed, code):
    registry = quaternion.registry.ToolRegistry(enabled_toolsets=("objects",))
    quaternion.transforms.register_tools(registry)
    calls = []
    def forbidden():
        calls.append("native")
        raise AssertionError("Malformed quaternion must be rejected before native access")
    monkeypatch.setattr(quaternion.admission, "require_blender", forbidden)
    permissions = quaternion.permissions.PermissionManager(lambda: {"TRANSFORM_OBJECTS": allowed})
    context = quaternion.registry.ToolContext(state=quaternion.state.BridgeState(), permissions=permissions,
                                               registry=registry, checkpoints=None)
    with pytest.raises(quaternion.transforms.BridgeError) as caught:
        registry.dispatch("transform.set", {"object_name": "Working", "rotation_quaternion": [0., 0., 0., 0.]}, context)
    assert caught.value.code == code
    assert calls == [] and context.handler_entries == 0 and context.checkpoint_admission is None


@pytest.mark.parametrize("oracle_passes", [True, False])
def test_already_compensated_error_requires_independent_original_oracle(quaternion, monkeypatch, oracle_passes):
    # This private classification seam never enters public native admission.
    module = quaternion.transforms
    boundary = object.__new__(module.QuaternionBoundary)
    boundary.started, boundary.native_seconds = True, None
    boundary.objects = (NS(name="Working"),)
    original_error = module.BridgeError("OPERATION_FAILED", "Native setter compensated", {"rollback_verified": True})
    monkeypatch.setattr(quaternion.admission, "cached", lambda *_: boundary)
    def fail(*_args, **_kwargs):
        raise original_error
    monkeypatch.setattr(module, "apply_assignments", fail)
    observed = []
    def verify(actual, *, before=False):
        observed.append((actual, before))
        if not oracle_passes:
            raise module.BridgeError("OPERATION_FAILED", "Original native bits unavailable or different")
    monkeypatch.setattr(module, "_verify_quaternion_result", verify)
    with pytest.raises(module.BridgeError) as caught:
        module._commit(None, None, "transform.set", NS(),
                       (module.RNAAssignment("rotation_quaternion", (1., -0., 0., 0.)),))
    assert observed == [(boundary, True)]
    if oracle_passes:
        assert caught.value is original_error
    else:
        assert caught.value is not original_error
        assert caught.value.context["rollback_verified"] is False
        assert caught.value.context["possible_mutation"] is True
        assert caught.value.context["verification_required"] is True


def test_core_bits_distinguish_signed_zero_in_each_channel(quaternion):
    values = {"rotation_mode": "QUATERNION", "location": (.1, .2, -.0), "rotation_euler": (.1, .2, .3),
              "rotation_quaternion": (1., -.0, .0, -.0), "rotation_axis_angle": (.1, .2, .3, .4), "scale": (1., 2., 3.)}
    bits = dict(quaternion.transforms._core_bits(values.items()))
    assert bits["rotation_mode"] == "QUATERNION" and len(bits) == 6
    assert bits["location"][2] == "00000080"
    assert bits["rotation_quaternion"] == ("0000803f", "00000080", "00000000", "00000080")
    values["rotation_quaternion"] = (1., .0, -.0, .0)
    assert dict(quaternion.transforms._core_bits(values.items()))["rotation_quaternion"] != bits["rotation_quaternion"]
