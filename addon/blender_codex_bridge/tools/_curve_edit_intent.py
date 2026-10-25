"""Pure, independently predicted Action prefixes for raw FREE-point edits.

Inputs are plain snapshots from the qualified Action reader. Native identity,
descriptors, sampled-point refusal, permissions and lifecycle belong to the
caller. This plan is data, never authority to mutate or adopt native readback.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Any, NoReturn

from ..errors import BridgeError, ErrorCode

MAX_ITEMS = 65_536
MAX_DEPTH = 32
MAX_STRING_BYTES = 4096
MAX_STEPS = 1537
MAX_WORK = 2_097_152
MAX_POINTS = 1024
MAX_EDITS = 256
MAX_VALUE = 1_000_000.
MIN_NORMAL = float.fromhex("0x1p-126")
# BEZT_BINARYSEARCH_THRESH is 0.01f in both qualified native sources. Keep
# its exact binary32 representation; deduplication compares a float subtraction.
NATIVE_KEYFRAME_MERGE_THRESHOLD = struct.unpack("<f", bytes.fromhex("0ad7233c"))[0]
FIELDS = ("co", "handle_left", "handle_right")
ENUMS = {
    "interpolation": frozenset({"CONSTANT", "LINEAR", "BEZIER"}),
    "easing": frozenset({"AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"}),
    "handle_left_type": frozenset({"FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"}),
    "handle_right_type": frozenset({"FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"}),
    "extrapolation": frozenset({"CONSTANT", "LINEAR"}),
}


def _fail(message: str, *, request: bool = False) -> NoReturn:
    raise BridgeError(ErrorCode.INVALID_ARGUMENT if request else ErrorCode.NOT_IMPLEMENTED, message)


def _plain(value: Any, budget: list[int], depth: int = 0) -> Any:
    """Detach before providers; exact built-ins prevent adapter callbacks."""
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_DEPTH:
        _fail("Curve snapshot exceeds its bounded item/depth profile.")
    kind = type(value)
    if kind in (type(None), bool):
        return value
    if kind is int:
        if not -(2**64) <= value < 2**64:
            _fail("Curve snapshot integer exceeds its bounded profile.")
        return value
    if kind is float:
        if not math.isfinite(value):
            _fail("Curve snapshot contains a nonfinite value.")
        return value
    if kind is str:
        if len(value) > MAX_STRING_BYTES:
            _fail("Curve snapshot string exceeds its bounded profile.")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError as error:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve snapshot strings require valid UTF-8.") from error
        if size > MAX_STRING_BYTES:
            _fail("Curve snapshot string exceeds its bounded profile.")
        return value
    if kind is tuple:
        return tuple(_plain(item, budget, depth+1) for item in value)
    _fail("Curve snapshots require only plain immutable tuples and scalars.")


def _typed(value: Any) -> Any:
    kind = type(value)
    if kind is tuple:
        return ("tuple", tuple(_typed(item) for item in value))
    if kind is float:
        return ("float64", struct.pack("<d", value).hex())
    return (kind.__name__, value)


def same(first: Any, second: Any) -> bool:
    """Exact bounded comparison, including float zero signs and bool/int types."""
    return bool(_typed(_plain(first, [MAX_ITEMS])) == _typed(_plain(second, [MAX_ITEMS])))


def digest(snapshot: Any) -> str:
    data = _typed(_plain(snapshot, [MAX_ITEMS]))
    return hashlib.sha256(json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _props(value: Any) -> dict[str, Any]:
    if type(value) is not tuple:
        _fail("Curve source properties require immutable records.")
    result = {}
    for row in value:
        if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                or not row[0] or row[0] in result):
            _fail("Curve source property records are missing, malformed or duplicated.")
        result[row[0]] = row[1]
    return result


def _source_pair(value: Any) -> tuple[float, float]:
    if type(value) is not tuple or len(value) != 2:
        _fail("Curve points and handles require exact stored Float32 pairs.")
    for number in value:
        if (type(number) is not float or not math.isfinite(number) or abs(number) > MAX_VALUE
                or (number != 0. and abs(number) < MIN_NORMAL)):
            _fail("Curve point/handle source exceeds the finite normal Float32 profile.")
        rounded = struct.unpack("<f", struct.pack("<f", number))[0]
        if struct.pack("<d", number) != struct.pack("<d", rounded):
            _fail("Curve point/handle source must already be exact Float32 storage.")
    return value


def _request_pair(value: Any) -> tuple[float, float]:
    if type(value) not in (tuple, list) or len(value) != 2:
        _fail("Requested curve point or handle requires a plain numeric pair.", request=True)
    requested = []
    for number in value:
        if type(number) not in (int, float) or not -MAX_VALUE <= number <= MAX_VALUE:
            _fail("Requested curve coordinates require finite numbers within +/-1,000,000.", request=True)
        number = float(number)
        if not math.isfinite(number):
            _fail("Requested curve coordinates require finite numbers.", request=True)
        if number != 0. and abs(number) < MIN_NORMAL:
            _fail("Subnormal requested coordinates need a separately qualified storage profile.")
        requested.append(number)
    result = struct.unpack("<ff", struct.pack("<ff", *requested))
    _source_pair(result)  # Also reject any unsupported rounded result.
    return result


def _enum(field: str, value: Any) -> str:
    if type(value) is not str or value not in ENUMS[field]:
        _fail("Requested curve enum is not supported.", request=True)
    _fail("Curve enum and extrapolation edits require a separate native update profile.")


def _replace_prop(properties: tuple, field: str, value: Any) -> tuple:
    return tuple((name, value if name == field else old) for name, old in properties)


def _replace_curve(state: tuple, ordinal: int, field: str, point: int | None, value: Any) -> tuple:
    handle, curve = state[3][ordinal]
    properties, points, modifiers = curve
    if point is None:
        properties = _replace_prop(properties, field, value)
    else:
        def changed(row: tuple) -> tuple:
            result = _replace_prop(row, field, value)
            # The co_ui getter aliases co; its translating setter is never used.
            return _replace_prop(result, "co_ui", value) if field == "co" else result
        points = tuple(changed(row) if index == point else row for index, row in enumerate(points))
    curves = tuple((handle, (properties, points, modifiers)) if index == ordinal else old
                   for index, old in enumerate(state[3]))
    return (*state[:3], curves, *state[4:])


@dataclass(frozen=True, slots=True)
class CurveStep:
    field: str
    frame: float | None
    value: Any
    before: tuple
    expected: tuple


@dataclass(frozen=True, slots=True)
class CurveIntent:
    before: tuple
    expected: tuple
    steps: tuple[CurveStep, ...]


def plan_edit(full_action_content: Any, curve_ordinal: int, prepared: Any,
              extrapolation: Any) -> CurveIntent:
    """Precompute complete raw-point prefixes; no full curve update is permitted."""
    budget = [MAX_ITEMS]
    before = _plain(full_action_content, budget)
    items = MAX_ITEMS-budget[0]
    if (type(before) is not tuple or len(before) != 6
            or any(type(part) is not tuple for part in before)
            or not 1 <= len(before[3]) <= 1024):
        _fail("Curve planning requires the complete six-part Action snapshot.")
    if type(curve_ordinal) is not int or not 0 <= curve_ordinal < len(before[3]):
        _fail("Select one existing curve ordinal.", request=True)
    for entry in before[3]:
        if type(entry) is not tuple or len(entry) != 2 or type(entry[1]) is not tuple or len(entry[1]) != 3:
            _fail("Action curve inventory is malformed.")
    _slot, curve = before[3][curve_ordinal]
    properties, points, modifiers = curve
    props = _props(properties)
    if (props.get("extrapolation") not in ENUMS["extrapolation"]
            or type(props.get("extrapolation")) is not str or type(points) is not tuple
            or not 1 <= len(points) <= MAX_POINTS or type(modifiers) is not tuple or modifiers):
        _fail("Selected curve requires existing unsampled points, no modifiers and reviewed extrapolation.")
    records, frames = [], {}
    previous = None
    for index, row in enumerate(points):
        record = _props(row)
        if any(field not in record for field in (
            *FIELDS, "co_ui", "handle_left_type", "handle_right_type", "interpolation", "easing",
        )):
            _fail("Curve point source lacks its complete editable-field records.")
        time, _value = _source_pair(record["co"])
        if not same(_source_pair(record["co_ui"]), record["co"]):
            _fail("The source co_ui read alias differs from its raw control point.")
        left = _source_pair(record["handle_left"])
        right = _source_pair(record["handle_right"])
        if left[0] > time or right[0] < time:
            _fail("Source FREE handles must bracket their existing control point.")
        if (type(record["handle_left_type"]) is not str or record["handle_left_type"] != "FREE"
                or type(record["handle_right_type"]) is not str or record["handle_right_type"] != "FREE"):
            _fail("Every selected-curve point must already have two FREE handles.")
        if (type(record["interpolation"]) is not str or type(record["easing"]) is not str
                or record["interpolation"] not in ENUMS["interpolation"]
                or record["easing"] not in ENUMS["easing"]):
            _fail("Curve source interpolation/easing exceeds the qualified enum profile.")
        if previous is not None and not previous < time:
            _fail("Selected curve times must be strictly increasing and unique.")
        if previous is not None:
            native_gap = struct.unpack("<f", struct.pack("<f", time - previous))[0]
            if native_gap <= NATIVE_KEYFRAME_MERGE_THRESHOLD:
                _fail("Selected curve times fall within the native Float32 key-deduplication threshold.")
        previous = time
        frames[struct.pack("<f", time)] = index
        records.append(record)
    if type(prepared) is not tuple or len(prepared) > MAX_EDITS:
        _fail("Curve edits require a bounded plain tuple of prepared records.", request=True)
    if not prepared and extrapolation is None:
        _fail("Supply curve fields or extrapolation.", request=True)
    operations = []
    if extrapolation is not None:
        _enum("extrapolation", extrapolation)
    seen = set()
    for row in prepared:
        if type(row) is not tuple or len(row) != 2 or type(row[0]) is not float or type(row[1]) is not dict:
            _fail("Prepared curve edits require a stored float frame and a plain field dictionary.", request=True)
        frame, fields = row
        if (not math.isfinite(frame) or abs(frame) > MAX_VALUE
                or (frame != 0. and abs(frame) < MIN_NORMAL)):
            _fail("Prepared curve frame is outside its stored profile.", request=True)
        encoded = struct.pack("<f", frame)
        if struct.unpack("<f", encoded)[0] != frame or encoded not in frames or encoded in seen:
            _fail("Prepared frame must identify one distinct exact stored point.", request=True)
        seen.add(encoded)
        known = (*FIELDS, *(field for field in ENUMS if field != "extrapolation"))
        if not fields or any(type(name) is not str or name not in known for name in fields):
            _fail("Prepared curve fields are empty or unknown.", request=True)
        for field in ENUMS:
            if field in fields:
                _enum(field, fields[field])  # Valid public enum syntax is an explicit profile refusal.
        point = frames[encoded]
        for field in FIELDS:
            if field not in fields:
                continue
            value = _request_pair(fields[field])
            if field == "co" and struct.pack("<f", value[0]) != encoded:
                _fail("Raw control-point edits initially preserve the exact existing frame.")
            if ((field == "handle_left" and value[0] > frame)
                    or (field == "handle_right" and value[0] < frame)):
                _fail("Requested FREE handle must stay on its admitted side of the point.")
            if not same(records[point][field], value):
                operations.append((field, frame, point, value))
    # Before allocating any full-state prefix, reserve the complete finite work.
    if len(operations) > MAX_STEPS or items*max(1, len(operations)) > MAX_WORK:
        _fail("Curve intent exceeds its joint snapshot/write work budget.")
    current, steps = before, []
    for field, frame, point, value in operations:
        expected = _replace_curve(current, curve_ordinal, field, point, value)
        steps.append(CurveStep(field, frame, value, current, expected))
        current = expected
    return CurveIntent(before, current, tuple(steps))
