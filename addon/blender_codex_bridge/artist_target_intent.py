"""Immutable core-channel intent and bounded, context-free Object observations.

This profile predicts ordinary native Float32 assignments independently before
application. It does not predict rotation-mode conversion, evaluated transforms,
parent/delta effects or appearance. No function here accesses Blender context.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any

from .errors import BridgeError, ErrorCode

PROFILE = "OBJECT_CORE_CHANNELS_FLOAT32_V1"
SCOPE = "authored_core_transform_channels"
CORE_FIELDS = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
VECTOR_LENGTHS = {"location": 3, "rotation_euler": 3, "rotation_quaternion": 4, "rotation_axis_angle": 4, "scale": 3}
EULER_MODES = frozenset({"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"})
ROTATION_MODES = EULER_MODES | {"QUATERNION", "AXIS_ANGLE"}
MIN_NORMAL = float.fromhex("0x1p-126")
MAX_MAGNITUDE = 1_000_000.
QUATERNION_NORM_TOLERANCE = 1e-6
Channels = tuple[tuple[str, str | tuple[float, ...]], ...]
Bits = tuple[tuple[str, str | tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class TargetIntent:
    profile: str = PROFILE
    availability: str = "unavailable"
    reason: str | None = "native_schema_unavailable"
    object_name: str | None = None
    session_uid: int | None = None
    pointer: int | None = None
    before_channels: Channels = ()
    expected_channels: Channels = ()
    before_bits: Bits = ()
    expected_bits: Bits = ()
    requested_fields: tuple[str, ...] = ()


class _Unavailable(Exception):
    pass


def _unsupported(reason: str) -> None:
    raise _Unavailable(reason)


def _pointer(value: Any) -> int:
    method = getattr(value, "as_pointer", None)
    if not callable(method):
        _unsupported("native_identity_unavailable")
    pointer = method()
    if type(pointer) is not int or pointer <= 0 or pointer.bit_length() > 64:
        _unsupported("native_identity_unavailable")
    return pointer


def _properties(bpy: Any, obj: Any) -> Any:
    native = getattr(getattr(bpy, "types", None), "Object", None)
    if native is None or type(obj) is not native:
        _unsupported("native_object_type_unavailable")
    canonical = getattr(native, "bl_rna", None)
    actual = getattr(obj, "bl_rna", None)
    if (canonical is None or actual is None or getattr(actual, "identifier", None) != "Object"
            or _pointer(canonical) != _pointer(actual)):
        _unsupported("native_object_schema_unavailable")
    properties = getattr(canonical, "properties", None)
    if properties is None or not callable(getattr(properties, "get", None)):
        _unsupported("native_object_schema_unavailable")
    return properties


def _descriptor(properties: Any, name: str, kind: str, length: int = 0) -> Any:
    prop = properties.get(name)
    if (prop is None or getattr(prop, "identifier", None) != name or getattr(prop, "type", None) != kind
            or any(getattr(prop, flag, False) for flag in ("is_runtime", "is_registered", "is_registered_optional"))
            or getattr(prop, "array_length", 0) != length
            or bool(getattr(prop, "is_array", False)) != bool(length)):
        _unsupported("native_descriptor_unavailable:" + name)
    return prop


def _identity(properties: Any, obj: Any) -> tuple[str, int, int]:
    _descriptor(properties, "name", "STRING")
    _descriptor(properties, "session_uid", "INT")
    name, uid, pointer = obj.name, obj.session_uid, _pointer(obj)
    if type(name) is not str or not name or len(name.encode("utf-8")) > 63:
        _unsupported("native_name_unavailable")
    if type(uid) is not int or uid <= 0 or uid.bit_length() > 64:
        _unsupported("native_identity_unavailable")
    return name, uid, pointer


def _channel_properties(properties: Any) -> dict[str, Any]:
    result = {"rotation_mode": _descriptor(properties, "rotation_mode", "ENUM")}
    for field, length in VECTOR_LENGTHS.items():
        prop = _descriptor(properties, field, "FLOAT", length)
        lower, upper = getattr(prop, "hard_min", None), getattr(prop, "hard_max", None)
        if (type(lower) not in (float, int) or type(upper) not in (float, int)
                or not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper):
            _unsupported("native_numeric_range_unavailable:" + field)
        result[field] = prop
    return result


def _float32(value: float) -> tuple[float, str]:
    if type(value) is not float or not math.isfinite(value):
        _unsupported("nonfinite_or_non_native_float")
    try:
        raw = struct.pack("<f", value)
    except (OverflowError, struct.error) as error:
        raise _Unavailable("float32_overflow") from error
    result = struct.unpack("<f", raw)[0]
    if not math.isfinite(result):
        _unsupported("float32_overflow")
    return result, raw.hex()


def _read_channels(obj: Any, properties: dict[str, Any]) -> tuple[Channels, Bits]:
    # All descriptors are validated before the first core-channel value read.
    del properties
    mode = obj.rotation_mode
    if type(mode) is not str or mode not in ROTATION_MODES:
        _unsupported("native_rotation_mode_unavailable")
    channels: dict[str, Any] = {"rotation_mode": mode}
    bits: dict[str, Any] = {"rotation_mode": mode}
    for field, length in VECTOR_LENGTHS.items():
        vector = getattr(obj, field)
        if len(vector) != length:
            _unsupported("native_vector_shape_unavailable:" + field)
        values, encoded = [], []
        for index in range(length):
            value = vector[index]
            converted, binary = _float32(value)
            if converted != value:
                _unsupported("native_float32_storage_unavailable:" + field)
            values.append(value)
            encoded.append(binary)
        channels[field], bits[field] = tuple(values), tuple(encoded)
    return tuple((field, channels[field]) for field in CORE_FIELDS), tuple((field, bits[field]) for field in CORE_FIELDS)


def _qualified(value: float) -> None:
    if abs(value) > MAX_MAGNITUDE:
        _unsupported("numeric_magnitude_outside_profile")
    if value != 0. and abs(value) < MIN_NORMAL:
        _unsupported("subnormal_value_outside_profile")


def capture_intent(bpy: Any, obj: Any, parsed_params: dict[str, Any]) -> TargetIntent:
    """Capture immutable expectations without restricting legacy preview/apply.

    An unsupported observation profile is retained as unavailable. No prediction
    is obtained from a handler response, adopted write boundary or native output.
    """
    name, uid, pointer = None, None, None
    before, before_bits = (), ()
    requested = tuple(field for field in ("location", "rotation", "scale", "rotation_mode", "rotation_quaternion") if field in parsed_params)
    try:
        properties = _properties(bpy, obj)
        name, uid, pointer = _identity(properties, obj)
        descriptors = _channel_properties(properties)
        before, before_bits = _read_channels(obj, descriptors)
        values, encoded = dict(before), dict(before_bits)
        if "rotation_quaternion" in parsed_params:
            if any(field in parsed_params for field in ("rotation", "rotation_euler", "rotation_mode")):
                _unsupported("quaternion_rotation_arguments_conflict")
            if values["rotation_mode"] != "QUATERNION":
                _unsupported("quaternion_existing_mode_required")
        mode = parsed_params.get("rotation_mode", values["rotation_mode"])
        if mode != values["rotation_mode"] or ("rotation" in parsed_params and mode not in EULER_MODES):
            _unsupported("rotation_mode_conversion_unavailable")
        if not any(field in parsed_params for field in ("location", "rotation", "scale", "rotation_quaternion")):
            _unsupported("no_requested_transform_channels")
        for field, old in before:
            if field != "rotation_mode":
                for value in old:
                    _qualified(value)
        for request, field, width in (("location", "location", 3), ("rotation", "rotation_euler", 3),
                                     ("scale", "scale", 3), ("rotation_quaternion", "rotation_quaternion", 4)):
            if request not in parsed_params:
                continue
            raw = parsed_params[request]
            if type(raw) not in (list, tuple) or len(raw) != width:
                _unsupported("unqualified_requested_vector:" + field)
            original, expected, binaries = [], [], []
            for value in raw:
                if type(value) not in (int, float):
                    _unsupported("unqualified_requested_number:" + field)
                try:
                    value = float(value)
                except (OverflowError, ValueError) as error:
                    raise _Unavailable("unqualified_requested_number:" + field) from error
                if not math.isfinite(value):
                    _unsupported("unqualified_requested_number:" + field)
                _qualified(value)
                if field == "rotation_quaternion" and abs(value) > 1.:
                    _unsupported("quaternion_component_outside_profile")
                if not descriptors[field].hard_min <= value <= descriptors[field].hard_max:
                    _unsupported("requested_native_clamping_unavailable:" + field)
                rounded, binary = _float32(value)
                _qualified(rounded)
                if not descriptors[field].hard_min <= rounded <= descriptors[field].hard_max:
                    _unsupported("requested_native_clamping_unavailable:" + field)
                original.append(value)
                expected.append(rounded)
                binaries.append(binary)
            if field == "rotation_quaternion":
                if abs(math.sqrt(sum(value * value for value in original)) - 1.) > QUATERNION_NORM_TOLERANCE:
                    _unsupported("quaternion_norm_outside_profile")
                if abs(math.sqrt(sum(value * value for value in expected)) - 1.) > QUATERNION_NORM_TOLERANCE:
                    _unsupported("quaternion_rounded_norm_outside_profile")
            values[field], encoded[field] = tuple(expected), tuple(binaries)
        return TargetIntent(availability="available", reason=None, object_name=name, session_uid=uid, pointer=pointer,
            before_channels=before, expected_channels=tuple((field, values[field]) for field in CORE_FIELDS),
            before_bits=before_bits, expected_bits=tuple((field, encoded[field]) for field in CORE_FIELDS), requested_fields=requested)
    except (_Unavailable, AttributeError, ReferenceError, TypeError, UnicodeError) as error:
        return TargetIntent(reason=str(error) if isinstance(error, _Unavailable) else "native_profile_unavailable",
            object_name=name, session_uid=uid, pointer=pointer, before_channels=before, before_bits=before_bits, requested_fields=requested)


def _plain_channels(channels: Channels | Bits) -> dict[str, Any]:
    return {field: list(value) if type(value) is tuple else value for field, value in channels}


def public_intent(intent: TargetIntent) -> dict[str, Any]:
    return {"profile": intent.profile, "availability": intent.availability, "reason": intent.reason,
        "scope": SCOPE, "identity": {"object_name": intent.object_name, "session_uid": intent.session_uid, "pointer": intent.pointer},
        "before": _plain_channels(intent.before_channels), "expected": _plain_channels(intent.expected_channels),
        "before_float32_le": _plain_channels(intent.before_bits), "expected_float32_le": _plain_channels(intent.expected_bits),
        "requested_fields": list(intent.requested_fields), "compared_fields": list(CORE_FIELDS),
        "numeric_profile": {"maximum_magnitude": MAX_MAGNITUDE, "minimum_nonzero_normal_float32": MIN_NORMAL},
        "includes_parent_or_delta_transforms": False, "scene_evaluated": False, "user_goal_verified": False}


def read_target(bpy: Any, intent: TargetIntent) -> dict[str, Any]:
    """Read exact target identity before fixed native core channels, no context."""
    if type(intent) is not TargetIntent or intent.availability != "available":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The receipt has no qualified target-channel expectation.")
    try:
        obj = bpy.data.objects.get(intent.object_name)
        if obj is None:
            return {"status": "missing", "identity": None}
        properties = _properties(bpy, obj)
        name, uid, pointer = _identity(properties, obj)
        identity = {"object_name": name, "session_uid": uid, "pointer": pointer}
        if (name, uid, pointer) != (intent.object_name, intent.session_uid, intent.pointer):
            return {"status": "replaced", "identity": identity}
        descriptors = _channel_properties(properties)
        channels, bits = _read_channels(obj, descriptors)
        return {"status": "observed", "identity": identity,
                "channels": _plain_channels(channels), "float32_le": _plain_channels(bits)}
    except (_Unavailable, AttributeError, ReferenceError, TypeError, UnicodeError) as error:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The target's native core-channel reader is unavailable.",
                          {"profile": PROFILE, "reason": str(error) if isinstance(error, _Unavailable) else "native_profile_unavailable"}) from error


def compare_target(intent: TargetIntent, observed: dict[str, Any]) -> dict[str, Any]:
    """Compare retained independent intent; never infer artistic completion."""
    if type(intent) is not TargetIntent or intent.availability != "available":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The receipt has no qualified target-channel expectation.")
    status = observed.get("status")
    if status not in {"missing", "replaced", "observed"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The target observation has an unreviewed shape.")
    expected = public_intent(intent)
    result = {"profile": PROFILE, "scope": SCOPE, "expected_identity": expected["identity"],
        "observed_identity": observed["identity"], "compared_fields": list(CORE_FIELDS) if status == "observed" else [],
        "comparison_complete": status == "observed", "expected": expected["expected"],
        "expected_float32_le": expected["expected_float32_le"], "observed": observed.get("channels"),
        "observed_float32_le": observed.get("float32_le"), "differences": [],
        "includes_parent_or_delta_transforms": False, "scene_evaluated": False, "user_goal_verified": False}
    if status != "observed":
        result["status"] = "target_missing" if status == "missing" else "target_replaced"
        return result
    if set(observed["channels"]) != set(CORE_FIELDS) or set(observed["float32_le"]) != set(CORE_FIELDS):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The target observation has an incomplete channel shape.")
    for field in CORE_FIELDS:
        wanted, actual = expected["expected_float32_le"][field], observed["float32_le"][field]
        if wanted != actual:
            difference = {"field": field, "expected": expected["expected"][field], "observed": observed["channels"][field],
                          "expected_float32_le": wanted, "observed_float32_le": actual}
            if type(wanted) is list and type(actual) is list:
                difference["different_components"] = [index for index, pair in enumerate(zip(wanted, actual, strict=True)) if pair[0] != pair[1]]
            result["differences"].append(difference)
    result["status"] = "channels_differ" if result["differences"] else "channels_match"
    return result
