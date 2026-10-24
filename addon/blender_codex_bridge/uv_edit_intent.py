"""Private plain-data UV planning; no native access or public handler integration.

The bounded profile retains complete map/corner values independently of setters.
Four-index keys describe authored topology, never native identity. Selection,
ownership, permissions, native lifetimes and recovery belong to a future guard.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, NoReturn

from .errors import BridgeError, ErrorCode

MAX_CORNERS = 512
MAX_MAPS = 8
MAX_SNAPSHOT_RECORDS = 4096
MAX_WRITES = 4096
MAX_SNAPSHOT_WRITE_PRODUCT = 2_097_152
MAX_UV = 1_000_000.
MIN_NORMAL = float.fromhex("0x1p-126")
MAX_ROTATION = math.tau * 1_000
CornerKey = tuple[int, int, int, int]
Pair = tuple[float, float]
PairBits = tuple[str, str]


def _fail(message: str, *, unsupported: bool = False, selection: bool = False) -> NoReturn:
    code = ErrorCode.NOT_IMPLEMENTED if unsupported else ErrorCode.INVALID_SELECTION if selection else ErrorCode.INVALID_ARGUMENT
    raise BridgeError(code, message)


def _key(value: Any) -> CornerKey:
    if (type(value) not in (tuple, list) or len(value) != 4
            or any(type(item) is not int or not 0 <= item <= 2**31 - 1 for item in value)
            or any(item > 200_000 for item in value[:2])):
        _fail("A UV corner key requires four bounded nonnegative integer indices.")
    return value[0], value[1], value[2], value[3]


def _name(value: Any) -> str:
    if type(value) is not str or not value or "\0" in value:
        _fail("A UV map name requires 1-63 UTF-8 bytes without NUL.")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        _fail("A UV map name must contain valid UTF-8 characters.")
    if len(encoded) > 63:
        _fail("A UV map name exceeds 63 UTF-8 bytes.")
    return value


def _number(value: Any, *, source: bool = False, result: bool = False, rotation: bool = False) -> float:
    if type(value) not in (float, int):
        _fail("UV numeric values require exact built-in numbers.")
    limit = MAX_ROTATION if rotation else MAX_UV
    if not -limit <= value <= limit:
        _fail("UV numeric value exceeds the finite supported range.", unsupported=source or result)
    number = float(value)
    if not math.isfinite(number):
        _fail("UV numeric value must be finite.", unsupported=source or result)
    if number != 0. and abs(number) < MIN_NORMAL:
        _fail("Nonzero subnormal UV values are outside the private storage profile.", unsupported=True)
    return number


def _bits(value: Pair) -> PairBits:
    return struct.pack("<f", value[0]).hex(), struct.pack("<f", value[1]).hex()


def _pair(value: Any, *, source: bool = False, result: bool = False) -> tuple[Pair, Pair, PairBits]:
    if type(value) not in (list, tuple) or len(value) != 2:
        _fail("UV pairs require two plain numeric values.")
    requested = (_number(value[0], source=source, result=result), _number(value[1], source=source, result=result))
    rounded = struct.unpack("<ff", struct.pack("<ff", *requested))
    for number in rounded:
        _number(number, source=source, result=True)
    if source and any(a != b for a, b in zip(requested, rounded, strict=True)):
        _fail("Source UV coordinates must already be exact native Float32 values.", unsupported=True)
    return requested, rounded, _bits(rounded)


def _f64(value: Pair) -> PairBits:
    return struct.pack("<d", value[0]).hex(), struct.pack("<d", value[1]).hex()


def _encoded(value: Any, width: int) -> bool:
    return (type(value) is tuple and len(value) == 2 and all(type(item) is str and len(item) == width
            and all(char in "0123456789abcdef" for char in item) for item in value))


def _freeze(value: Any, *, float_bits: bool = False, depth: int = 0) -> Any:
    if depth > 6:
        _fail("UV parameter nesting exceeds the private plain-data profile.")
    kind = type(value)
    if kind in (type(None), bool, int, str):
        return (kind.__name__, value)
    if kind is float:
        return ("float64", struct.pack("<d", value).hex()) if float_bits else ("float", value)
    if kind in (list, tuple):
        return (kind.__name__, tuple(_freeze(item, float_bits=float_bits, depth=depth + 1) for item in value))
    if kind is dict and all(type(key) is str for key in value):
        return ("dict", tuple((key, _freeze(value[key], float_bits=float_bits, depth=depth + 1)) for key in sorted(value)))
    _fail("UV parameters contain a non-plain value.")


@dataclass(frozen=True, slots=True)
class UVCorner:
    key: CornerKey
    uv: Pair
    uv_bits: PairBits
    pin_uv: bool

    def __post_init__(self) -> None:
        if type(self.key) is not tuple or _key(self.key) != self.key or type(self.uv) is not tuple:
            _fail("UVCorner values require immutable native-value tuples.")
        _, values, encoded = _pair(self.uv, source=True)
        if not _encoded(self.uv_bits, 8) or self.uv != values or self.uv_bits != encoded or type(self.pin_uv) is not bool:
            _fail("UVCorner storage bits or Boolean pin state are inconsistent.")


@dataclass(frozen=True, slots=True)
class UVMap:
    name: str
    corners: tuple[UVCorner, ...]

    def __post_init__(self) -> None:
        _name(self.name)
        if type(self.corners) is not tuple or not self.corners or any(type(corner) is not UVCorner for corner in self.corners):
            _fail("UVMap requires an immutable nonempty corner inventory.")
        if len(self.corners) > MAX_CORNERS:
            _fail("UV map exceeds the private corner budget.", unsupported=True)
        if len({corner.key[:2] for corner in self.corners}) != len(self.corners):
            _fail("A UV map contains duplicate face/corner keys.")


@dataclass(frozen=True, slots=True)
class UVSnapshot:
    maps: tuple[UVMap, ...]

    def __post_init__(self) -> None:
        if type(self.maps) is not tuple or not self.maps or any(type(layer) is not UVMap for layer in self.maps):
            _fail("UVSnapshot requires immutable complete map records.")
        if len(self.maps) > MAX_MAPS or sum(len(layer.corners) for layer in self.maps) > MAX_SNAPSHOT_RECORDS:
            _fail("UV snapshot exceeds the private map/value budget.", unsupported=True)
        if len({layer.name for layer in self.maps}) != len(self.maps):
            _fail("UV map names must be unique.")
        keys = tuple(corner.key for corner in self.maps[0].corners)
        if any(tuple(corner.key for corner in layer.corners) != keys for layer in self.maps):
            _fail("All UV maps must contain the identical ordered corner-key inventory.")


@dataclass(frozen=True, slots=True)
class UVPairIntent:
    requested: Pair
    requested_float64_le: PairBits
    rounded: Pair
    rounded_float32_le: PairBits

    def __post_init__(self) -> None:
        if any(type(value) is not tuple for value in (
                self.requested, self.requested_float64_le, self.rounded, self.rounded_float32_le)):
            _fail("UV pair intent requires immutable value/bit tuples.")
        requested, rounded, encoded = _pair(self.requested)
        _pair(self.rounded, source=True)
        if (not _encoded(self.requested_float64_le, 16) or not _encoded(self.rounded_float32_le, 8)
                or self.requested_float64_le != _f64(requested) or self.rounded != rounded or self.rounded_float32_le != encoded):
            _fail("UV pair intent values and storage bits disagree.")


@dataclass(frozen=True, slots=True)
class UVWrite:
    key: CornerKey
    uv: Pair | None = None
    uv_bits: PairBits | None = None
    pin_uv: bool | None = None
    requested_uv: Pair | None = None
    requested_float64_le: PairBits | None = None

    def __post_init__(self) -> None:
        if type(self.key) is not tuple:
            _fail("UV writes require immutable corner keys.")
        _key(self.key)
        if self.uv is None:
            if type(self.pin_uv) is not bool or any(value is not None for value in (
                    self.uv_bits, self.requested_uv, self.requested_float64_le)):
                _fail("Pin-only writes cannot carry coordinate fields.")
        else:
            if self.pin_uv is not None or any(type(value) is not tuple for value in (
                    self.uv, self.uv_bits, self.requested_uv, self.requested_float64_le)):
                _fail("Coordinate-only writes require immutable request/value/bit tuples.")
            requested, rounded, encoded = _pair(self.requested_uv, result=True)
            _pair(self.uv, source=True)
            if (not _encoded(self.uv_bits, 8) or not _encoded(self.requested_float64_le, 16)
                    or self.uv != rounded or self.uv_bits != encoded or self.requested_float64_le != _f64(requested)):
                _fail("Coordinate write values and independently predicted bits disagree.")


def _immutable(value: Any, depth: int = 0) -> bool:
    if depth > 20:
        return False
    return type(value) in (type(None), bool, int, float, str) or (
        type(value) is tuple and len(value) <= MAX_SNAPSHOT_RECORDS and all(_immutable(item, depth + 1) for item in value))


@dataclass(frozen=True, slots=True)
class UVPlan:
    operation: str
    layer_name: str
    before: UVSnapshot
    expected: UVSnapshot
    parameters: Any
    requested_float64_le: Any
    rounded_parameters: tuple[tuple[str, UVPairIntent], ...]
    scope_keys: tuple[CornerKey, ...]
    writes: tuple[UVWrite, ...]
    target_corners: int
    coordinate_changes: int
    pin_changes: int
    skipped_pinned_corners: int
    snapshot_records: int
    snapshot_values: int
    snapshot_write_product: int

    def __post_init__(self) -> None:
        _name(self.layer_name)
        if (type(self.operation) is not str or self.operation not in {"coordinates_set", "transform", "pin"}
                or type(self.before) is not UVSnapshot or type(self.expected) is not UVSnapshot
                or type(self.writes) is not tuple or any(type(write) is not UVWrite for write in self.writes)
                or type(self.scope_keys) is not tuple or any(type(key) is not tuple for key in self.scope_keys)
                or type(self.rounded_parameters) is not tuple
                or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or type(row[1]) is not UVPairIntent
                       for row in self.rounded_parameters)
                or not _immutable(self.parameters) or not _immutable(self.requested_float64_le)):
            _fail("UVPlan requires deeply immutable plain data and typed value records.")
        for key in self.scope_keys:
            _key(key)
        if any(type(value) is not int or value < 0 for value in (
                self.target_corners, self.coordinate_changes, self.pin_changes, self.skipped_pinned_corners,
                self.snapshot_records, self.snapshot_values, self.snapshot_write_product)):
            _fail("UVPlan counters require bounded exact nonnegative integers.")


def freeze_snapshot(maps: Any) -> UVSnapshot:
    """Detach exact built-in records; source values are validated, never rounded."""
    if type(maps) is not dict or not maps:
        _fail("A plain nonempty mapping of UV names to corner records is required.")
    if len(maps) > MAX_MAPS:
        _fail("UV snapshot exceeds the private map budget.", unsupported=True)
    layers = []
    for name, rows in maps.items():
        _name(name)
        if type(rows) not in (list, tuple) or not rows:
            _fail("UV map records require a nonempty plain list or tuple.")
        if len(rows) > MAX_CORNERS:
            _fail("UV map exceeds the private corner budget.", unsupported=True)
        corners = []
        for row in rows:
            if (type(row) is not dict or any(type(key) is not str for key in row)
                    or set(row) != {"face", "corner", "vertex", "edge", "uv", "pin_uv"}):
                _fail("UV corner records require exactly face/corner/vertex/edge/uv/pin_uv.")
            key = _key(tuple(row[field] for field in ("face", "corner", "vertex", "edge")))
            _, uv, encoded = _pair(row["uv"], source=True)
            corners.append(UVCorner(key, uv, encoded, row["pin_uv"]))
        layers.append(UVMap(name, tuple(corners)))
    return UVSnapshot(tuple(layers))


def _indices(record: Any, fields: set[str]) -> tuple[int, int]:
    if type(record) is not dict or any(type(key) is not str for key in record) or set(record) != fields:
        _fail("UV request corner records have unsupported fields.")
    indices = record["face_index"], record["corner_index"]
    if any(type(value) is not int or not 0 <= value <= 200_000 for value in indices):
        _fail("UV request face/corner indices must be bounded exact integers.")
    return indices


def plan_edit(snapshot: UVSnapshot, operation: str, layer_name: str, params: Any, scope_keys: Any) -> UVPlan:
    """Predict one bounded authored edit; this function performs no native action."""
    if type(snapshot) is not UVSnapshot or type(operation) is not str or operation not in {"coordinates_set", "transform", "pin"}:
        _fail("A validated UVSnapshot and supported private operation are required.")
    _name(layer_name)
    layer = next((item for item in snapshot.maps if item.name == layer_name), None)
    if layer is None:
        _fail("The requested UV map is absent from the frozen snapshot.")
    if type(params) is not dict or any(type(key) is not str for key in params):
        _fail("UV operation parameters must be an exact plain dictionary.")
    allowed = {"coordinates_set": {"updates"}, "transform": {"corners", "offset", "scale", "pivot", "rotation", "respect_pins"},
               "pin": {"corners", "pinned"}}[operation]
    if set(params) - allowed:
        _fail("UV parameters contain unsupported fields.")
    if type(scope_keys) not in (list, tuple) or not scope_keys:
        _fail("An explicit nonempty plain allowed corner scope is required.")
    if len(scope_keys) > MAX_CORNERS:
        _fail("UV scope exceeds the private corner budget.", unsupported=True)
    scope = tuple(_key(key) for key in scope_keys)
    lookup = {corner.key: corner for corner in layer.corners}
    if len(set(scope)) != len(scope):
        _fail("UV scope contains duplicate keys.")
    if any(key not in lookup for key in scope):
        _fail("UV scope differs from the frozen topology.", selection=True)
    scoped = {key[:2]: key for key in scope}
    targets: list[tuple[CornerKey, UVPairIntent | None]] = []
    rounded_parameters: list[tuple[str, UVPairIntent]] = []

    def pair_intent(raw: Any, *, result: bool = False) -> UVPairIntent:
        requested, rounded, encoded = _pair(raw, result=result)
        return UVPairIntent(requested, _f64(requested), rounded, encoded)

    if operation == "coordinates_set":
        updates = params.get("updates")
        if type(updates) is not list or not updates:
            _fail("Coordinate updates require a nonempty plain list.")
        if len(updates) > MAX_CORNERS:
            _fail("Coordinate updates exceed the private write budget.", unsupported=True)
        for update in updates:
            indices = _indices(update, {"face_index", "corner_index", "uv"})
            if indices not in scoped:
                _fail("A UV coordinate update is outside the allowed scope.", selection=True)
            targets.append((scoped[indices], pair_intent(update["uv"])))
    else:
        records = params.get("corners")
        keys = list(scope)
        if records is not None:
            if type(records) is not list or not records:
                _fail("Explicit UV corners require a nonempty plain list.")
            if len(records) > MAX_CORNERS:
                _fail("Explicit UV corners exceed the private write budget.", unsupported=True)
            keys = []
            for record in records:
                indices = _indices(record, {"face_index", "corner_index"})
                if indices not in scoped:
                    _fail("A requested UV corner is outside the allowed scope.", selection=True)
                keys.append(scoped[indices])
        targets = [(key, None) for key in keys]
    if len({key for key, _ in targets}) != len(targets):
        _fail("A UV corner may be targeted only once.")
    pinned = params.get("pinned", True) if operation == "pin" else None
    respect_pins = params.get("respect_pins", True)
    if (operation == "pin" and type(pinned) is not bool) or (operation == "transform" and type(respect_pins) is not bool):
        _fail("UV pin options require exact Boolean values.")
    if operation == "transform":
        for field, default in (("offset", (0., 0.)), ("scale", (1., 1.)), ("pivot", (0., 0.))):
            rounded_parameters.append((field, pair_intent(params.get(field, default))))
        pairs = {name: value.rounded for name, value in rounded_parameters}
        offset, scale, pivot = pairs["offset"], pairs["scale"], pairs["pivot"]
        rotation = _number(params.get("rotation", 0.), rotation=True)
        cosine, sine = math.cos(rotation), math.sin(rotation)
        transformed = []
        for key, _ in targets:
            corner = lookup[key]
            if respect_pins and corner.pin_uv:
                continue
            x, y = (corner.uv[0] - pivot[0]) * scale[0], (corner.uv[1] - pivot[1]) * scale[1]
            value = (pivot[0] + offset[0] + cosine * x - sine * y,
                     pivot[1] + offset[1] + sine * x + cosine * y)
            transformed.append((key, pair_intent(value, result=True)))
        skipped = len(targets) - len(transformed)
        targets = transformed
    else:
        skipped = 0
    replacements = dict(lookup)
    writes = []
    coordinate_changes = pin_changes = 0
    for key, pair in targets:
        before = lookup[key]
        if pair is not None and before.uv_bits != pair.rounded_float32_le:
            replacements[key] = UVCorner(key, pair.rounded, pair.rounded_float32_le, before.pin_uv)
            writes.append(UVWrite(key, pair.rounded, pair.rounded_float32_le, None, pair.requested, pair.requested_float64_le))
            coordinate_changes += 1
        elif operation == "pin" and pinned is not before.pin_uv:
            replacements[key] = UVCorner(key, before.uv, before.uv_bits, pinned)
            writes.append(UVWrite(key, pin_uv=pinned))
            pin_changes += 1
    records_count = sum(len(item.corners) for item in snapshot.maps)
    product = records_count * 3 * max(1, len(writes))
    if len(writes) > MAX_WRITES or product > MAX_SNAPSHOT_WRITE_PRODUCT:
        _fail("UV snapshot-times-write verification budget is exceeded.", unsupported=True)
    expected_layer = UVMap(layer.name, tuple(replacements[corner.key] for corner in layer.corners))
    expected = UVSnapshot(tuple(expected_layer if item is layer else item for item in snapshot.maps))
    return UVPlan(operation, layer_name, snapshot, expected, _freeze(params), _freeze(params, float_bits=True),
                  tuple(rounded_parameters), scope, tuple(writes), len(targets), coordinate_changes, pin_changes, skipped,
                  records_count, records_count * 3, product)
