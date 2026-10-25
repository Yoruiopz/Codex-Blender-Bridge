"""Geometry-only preview DTO validation, framing math and PNG evidence.

Pure standard-library helpers shared by source capture and its isolated worker.
This module never accesses Blender, starts processes or performs file I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zlib
from typing import Any

SCHEMA = "stock_geometry_preview_v1"
MAX_VERTICES, MAX_EDGES, MAX_POLYGONS, MAX_CORNERS = 512, 1024, 512, 2048
MAX_BYTES = 2 * 1024 * 1024
SIZE, SAMPLES = 128, 8
LOCAL_LIMIT, LOCATION_LIMIT, WORLD_LIMIT = 1024.0, 8192.0, 65536.0
ROTATION_LIMIT = 16 * math.pi
MIN_SCALE, MAX_SCALE = 1e-4, 64.0
DEFAULT_DELTAS = {"delta_location": (0., 0., 0.), "delta_rotation_euler": (0., 0., 0.),
                  "delta_rotation_quaternion": (1., 0., 0., 0.), "delta_scale": (1., 1., 1.)}


class PreviewRefused(ValueError):
    """Unsupported bounded geometry-preview input."""


def _require(value: Any, message: str) -> None:
    if not value:
        raise PreviewRefused(message)


def _keys(value: Any, expected: set[str]) -> None:
    _require(type(value) is dict and set(value) == expected, "Unexpected DTO keys or container")


def _name(value: Any) -> str:
    _require(type(value) is str and value and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value), "Exact name required")
    try:
        _require(len(value.encode("utf-8")) <= 63, "Name exceeds native UTF-8 bound")
    except UnicodeError as exc:
        raise PreviewRefused("Invalid UTF-8 name") from exc
    return value


def _bits(value: Any, limit: float) -> str:
    _require(type(value) in {int, float}, "Finite numeric channel required")
    _require(abs(value) <= limit and math.isfinite(value), "Numeric magnitude outside profile")
    try:
        raw = struct.pack("<f", value)
    except (OverflowError, struct.error) as exc:
        raise PreviewRefused("Channel is not native Float32 safe") from exc
    _require(math.isfinite(struct.unpack("<f", raw)[0]), "Nonfinite native Float32")
    return raw.hex()


def _float(value: Any, limit: float) -> float:
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{8}", value), "Exact Float32 hex required")
    result = struct.unpack("<f", bytes.fromhex(value))[0]
    _require(math.isfinite(result) and abs(result) <= limit, "Unsafe Float32 value")
    return result


def _vector(values: Any, count: int, limit: float) -> list[float]:
    _require(type(values) is list and len(values) == count, "Unexpected vector shape")
    return [_float(x, limit) for x in values]


def canonical(value: dict[str, Any]) -> bytes:
    """Call after typed validation; no arbitrary objects or executable payloads."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def make_dto(name: str, vertices: Any, edges: Any, polygons: Any, *,
             location=(0., 0., 0.), rotation=(0., 0., 0.), scale=(1., 1., 1.)) -> dict[str, Any]:
    for rows, minimum, maximum in ((vertices, 3, MAX_VERTICES), (edges, 3, MAX_EDGES),
                                    (polygons, 1, MAX_POLYGONS)):
        _require(type(rows) in {list, tuple} and minimum <= len(rows) <= maximum,
                 "Geometry count outside profile")
    for row in vertices:
        _require(type(row) in {list, tuple} and len(row) == 3, "Unexpected source vertex shape")
    for row in edges:
        _require(type(row) in {list, tuple} and len(row) == 2, "Unexpected source edge shape")
    _require(all(type(row) in {list, tuple} and 3 <= len(row) <= 64 for row in polygons) and
             sum(len(row) for row in polygons) <= MAX_CORNERS, "Corner budget exceeded")
    for channels in (location, rotation, scale):
        _require(type(channels) in {list, tuple} and len(channels) == 3, "Unexpected source transform shape")
    value = {"schema": SCHEMA, "object_name": _name(name),
             "mesh": {"vertices": [[_bits(x, LOCAL_LIMIT) for x in v] for v in vertices],
                      "edges": [list(e) for e in edges], "polygons": [list(p) for p in polygons]},
             "transform": {"rotation_mode": "XYZ", "location": [_bits(x, LOCATION_LIMIT) for x in location],
                           "rotation_euler": [_bits(x, ROTATION_LIMIT) for x in rotation],
                           "scale": [_bits(x, MAX_SCALE) for x in scale],
                           **{k: [_bits(x, MAX_SCALE) for x in v] for k, v in DEFAULT_DELTAS.items()}},
             "render": {"width": SIZE, "height": SIZE, "samples": SAMPLES,
                        "style": "opaque_flat_geometry"}}
    return validate_dto(value)


def validate_dto(value: Any) -> dict[str, Any]:
    _keys(value, {"schema", "object_name", "mesh", "transform", "render"})
    _require(value["schema"] == SCHEMA, "Unsupported geometry schema")
    _name(value["object_name"])
    mesh, transform = value["mesh"], value["transform"]
    _keys(mesh, {"vertices", "edges", "polygons"})
    _keys(transform, {"rotation_mode", "location", "rotation_euler", "scale", *DEFAULT_DELTAS})
    _require(transform["rotation_mode"] == "XYZ", "Only authored XYZ transforms are supported")
    for name, limit in (("location", LOCATION_LIMIT), ("rotation_euler", ROTATION_LIMIT)):
        _vector(transform[name], 3, limit)
    scales = _vector(transform["scale"], 3, MAX_SCALE)
    _require(all(abs(x) >= MIN_SCALE for x in scales), "Degenerate source scale")
    for key, expected in DEFAULT_DELTAS.items():
        _vector(transform[key], len(expected), MAX_SCALE)
        _require(transform[key] == [_bits(x, MAX_SCALE) for x in expected], "Nondefault delta transform")
    _keys(value["render"], {"width", "height", "samples", "style"})
    _require(value["render"] == {"width": SIZE, "height": SIZE, "samples": SAMPLES,
                                  "style": "opaque_flat_geometry"}, "Fixed render profile required")
    for name in ("width", "height", "samples"):
        _require(type(value["render"][name]) is int, "Exact render integer required")
    for name, minimum, maximum in (("vertices", 3, MAX_VERTICES), ("edges", 3, MAX_EDGES),
                                    ("polygons", 1, MAX_POLYGONS)):
        _require(type(mesh[name]) is list and minimum <= len(mesh[name]) <= maximum,
                 "Geometry count outside profile")
    for vertex in mesh["vertices"]:
        _vector(vertex, 3, LOCAL_LIMIT)
    count = len(mesh["vertices"])
    seen = set()
    for edge in mesh["edges"]:
        _require(type(edge) is list and len(edge) == 2 and all(type(i) is int and 0 <= i < count for i in edge)
                 and edge[0] != edge[1], "Invalid edge")
        pair = tuple(sorted(edge))
        _require(pair not in seen, "Duplicate edge")
        seen.add(pair)
    corners = 0
    for polygon in mesh["polygons"]:
        _require(type(polygon) is list and 3 <= len(polygon) <= 64 and
                 all(type(i) is int and 0 <= i < count for i in polygon) and
                 len(set(polygon)) == len(polygon), "Invalid polygon")
        corners += len(polygon)
        _require(corners <= MAX_CORNERS, "Corner budget exceeded")
        _require(all(tuple(sorted((polygon[i - 1], polygon[i]))) in seen for i in range(len(polygon))),
                 "Polygon boundary missing from edges")
    points = _world_points(value)
    bounds = _bounds(points)
    extent = max(b - a for a, b in zip(bounds["min"], bounds["max"], strict=True))
    magnitude = max(abs(x) for p in points for x in p)
    _require(extent >= max(1e-4, magnitude * 2**-16), "Geometry below preview precision floor")
    raw = canonical(value)
    _require(len(raw) <= MAX_BYTES, "DTO byte budget exceeded")
    return json.loads(raw)


def _world_points(dto: dict[str, Any]) -> list[list[float]]:
    t = dto["transform"]
    location = _vector(t["location"], 3, LOCATION_LIMIT)
    angles = _vector(t["rotation_euler"], 3, ROTATION_LIMIT)
    scale = _vector(t["scale"], 3, MAX_SCALE)
    cx, cy, cz = (math.cos(x) for x in angles)
    sx, sy, sz = (math.sin(x) for x in angles)
    result = []
    for raw in dto["mesh"]["vertices"]:
        x, y, z = (v * s for v, s in zip(_vector(raw, 3, LOCAL_LIMIT), scale, strict=True))
        y, z = cx * y - sx * z, sx * y + cx * z
        x, z = cy * x + sy * z, -sy * x + cy * z
        x, y = cz * x - sz * y, sz * x + cz * y
        p = [a + b for a, b in zip((x, y, z), location, strict=True)]
        _require(all(math.isfinite(v) and abs(v) <= WORLD_LIMIT for v in p), "Unsafe world-space bounds")
        result.append(p)
    return result


def _bounds(points: list[list[float]]) -> dict[str, list[float]]:
    return {"min": [min(p[i] for p in points) for i in range(3)],
            "max": [max(p[i] for p in points) for i in range(3)]}


def world_bounds(dto: dict[str, Any]) -> dict[str, list[float]]:
    return _bounds(_world_points(dto))


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _normal(v) -> list[float]:
    length = math.sqrt(_dot(v, v))
    return [x / length for x in v]


def camera_fit(dto: dict[str, Any]) -> dict[str, Any]:
    bounds = world_bounds(dto)
    center = [(a + b) * .5 for a, b in zip(bounds["min"], bounds["max"], strict=True)]
    back = _normal((1.5, -2.5, 1.8))
    right = _normal((-back[1], back[0], 0.))
    up = [back[1] * right[2] - back[2] * right[1],
          back[2] * right[0] - back[0] * right[2],
          back[0] * right[1] - back[1] * right[0]]
    points = _world_points(dto)
    relative = [[a - b for a, b in zip(p, center, strict=True)] for p in points]
    radius = max(math.sqrt(_dot(p, p)) for p in relative)
    half = max(max(abs(_dot(p, axis)) for p in relative) for axis in (right, up))
    distance = radius * 4 + 1.
    return {"center": center, "right": right, "up": up, "back": back,
            "location": [a + distance * b for a, b in zip(center, back, strict=True)],
            "ortho_scale": max(half * 2 * 1.3, .001),
            "clip_start": max(.0001, distance - radius * 2), "clip_end": distance + radius * 4 + 1.}


def projected_bounds(dto: dict[str, Any], fit: dict[str, Any]) -> dict[str, list[float]]:
    points = []
    for p in _world_points(dto):
        relative = [a - b for a, b in zip(p, fit["center"], strict=True)]
        points.append([2 * _dot(relative, axis) / fit["ortho_scale"] for axis in (fit["right"], fit["up"])])
    return {"min": [min(p[i] for p in points) for i in range(2)],
            "max": [max(p[i] for p in points) for i in range(2)]}


def validate_png(data: bytes) -> dict[str, Any]:
    """Independent bounded PNG decoding/CRC/alpha evidence; not artistic approval."""
    _require(type(data) is bytes and 8 < len(data) <= MAX_BYTES and data[:8] == b"\x89PNG\r\n\x1a\n",
             "Invalid PNG envelope")
    offset, compressed, header, ended = 8, bytearray(), None, False
    while offset < len(data):
        _require(offset + 12 <= len(data), "Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        _require(length <= MAX_BYTES and offset + length + 12 <= len(data), "PNG chunk outside bounds")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        _require(zlib.crc32(kind + payload) & 0xffffffff == crc, "PNG CRC differs")
        if header is None:
            _require(kind == b"IHDR" and length == 13, "PNG must start with IHDR")
            header = struct.unpack(">IIBBBBB", payload)
            _require(header == (SIZE, SIZE, 8, 6, 0, 0, 0), "Expected fixed noninterlaced RGBA8 PNG")
        elif kind == b"IHDR":
            raise PreviewRefused("Duplicate PNG header")
        elif kind == b"IDAT":
            _require(not ended and len(compressed) + length <= MAX_BYTES, "PNG data budget exceeded")
            compressed.extend(payload)
        elif kind == b"IEND":
            _require(length == 0 and offset + 12 == len(data), "Invalid PNG end")
            ended = True
        else:
            _require(kind[:1].islower(), "Unsupported critical PNG chunk")
        offset += length + 12
    _require(ended and compressed, "Incomplete PNG")
    expected = SIZE * (1 + SIZE * 4)
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(compressed, expected + 1)
    except zlib.error as exc:
        raise PreviewRefused("Invalid PNG compressed stream") from exc
    _require(len(raw) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
             "PNG decompression size/trailing stream mismatch")
    previous, points = bytearray(SIZE * 4), []
    for y in range(SIZE):
        start = y * (1 + SIZE * 4)
        mode, row = raw[start], bytearray(raw[start + 1:start + 1 + SIZE * 4])
        _require(mode <= 4, "Unknown PNG filter")
        for i in range(len(row)):
            a, b, c = (row[i - 4] if i >= 4 else 0), previous[i], (previous[i - 4] if i >= 4 else 0)
            if mode == 1:
                row[i] = (row[i] + a) & 255
            elif mode == 2:
                row[i] = (row[i] + b) & 255
            elif mode == 3:
                row[i] = (row[i] + (a + b) // 2) & 255
            elif mode == 4:
                p = a + b - c
                distances = (abs(p - a), abs(p - b), abs(p - c))
                predictor = (a, b, c)[distances.index(min(distances))]
                row[i] = (row[i] + predictor) & 255
        points.extend((x, y) for x in range(SIZE) if row[x * 4 + 3] >= 128)
        previous = row
    _require(points, "PNG contains no opaque geometry")
    bounds = [min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points)]
    _require(bounds[0] >= 2 and bounds[1] >= 2 and bounds[2] < SIZE - 2 and bounds[3] < SIZE - 2,
             "Geometry clipped at PNG boundary")
    return {"width": SIZE, "height": SIZE, "foreground_pixels": len(points), "alpha_bbox": bounds,
            "sha256": hashlib.sha256(data).hexdigest(), "visual_review_performed": False}

