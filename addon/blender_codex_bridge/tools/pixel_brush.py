"""Bounded UV-image brush math, independent of Blender and UI operators."""

from __future__ import annotations

import hashlib
import math
import sys
from array import array
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from ..errors import invalid_argument
from .brush_tiles import TILE_SIZE, comparison_rows, segment_tiles

MAX_PIXELS = 16_777_216
MAX_SYNC_PIXELS = 1_048_576
MAX_DIMENSION = 4096
MAX_STROKES = 32
MAX_POINTS = 128
MAX_SEGMENTS = 256
MAX_TESTS = 2_000_000


def number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_argument(f"'{name}' must be a finite number.")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise invalid_argument(f"'{name}' must be finite.") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise invalid_argument(f"'{name}' must be within [{minimum}, {maximum}].")
    return result


def vector(value: Any, name: str, size: int, maximum: float = 1.) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != size:
        raise invalid_argument(f"'{name}' must contain exactly {size} numbers.")
    return tuple(number(item, name, 0., 1. if index == 3 else maximum) for index, item in enumerate(value))


def size(width: Any, height: Any, *, maximum_pixels: int = MAX_PIXELS) -> tuple[int, int]:
    if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_DIMENSION for value in (width, height)):
        raise invalid_argument("Image dimensions must be integers from 1 to 4096.")
    if width * height > maximum_pixels:
        raise invalid_argument(f"This pixel operation is bounded to {maximum_pixels:,} pixels; use cooperative paint jobs or digest-only inspection for larger images.")
    return width, height


def digest(values: array) -> str:
    if sys.byteorder != "little":  # SHA representation is portable, not host-endian.
        values = array("f", values)
        values.byteswap()
    return hashlib.sha256(values).hexdigest()


def prepare(strokes: Any, width: int, height: int, role: str, *, check=lambda: None) -> tuple[list[dict], int]:
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= MAX_STROKES:
        raise invalid_argument("Supply 1-32 typed brush strokes.")
    prepared, tests, segments = [], 0, 0
    for stroke in strokes:
        allowed = {"points", "radius_pixels", "color", "opacity", "hardness", "blend"}
        if not isinstance(stroke, Mapping) or set(stroke) - allowed:
            raise invalid_argument("Brush strokes contain only reviewed brush fields.")
        raw = stroke.get("points")
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_POINTS:
            raise invalid_argument("Each stroke needs 1-128 UV points.")
        points = [(uv[0] * width, uv[1] * height) for uv in (vector(point, "points", 2) for point in raw)]
        radius = number(stroke.get("radius_pixels"), "radius_pixels", .5, 256.)
        color = vector(stroke.get("color"), "color", 4, 16. if role == "COLOR" else 1.)
        opacity = number(stroke.get("opacity", 1.), "opacity", 0., 1.)
        hardness = number(stroke.get("hardness", .8), "hardness", 0., 1.)
        blend = stroke.get("blend", "MIX")
        if blend not in ("MIX", "ERASE_ALPHA") or (role == "DATA" and blend != "MIX"):
            raise invalid_argument("COLOR supports MIX/ERASE_ALPHA; DATA supports weighted RGBA MIX only.")
        pairs = list(pairwise(points)) if len(points) > 1 else [(points[0], points[0])]
        segments += len(pairs)
        if segments > MAX_SEGMENTS:
            raise invalid_argument("A paint operation supports at most 256 brush segments.")
        regions = []
        tiles: dict[tuple[int, int], list] = {}
        for a, b in pairs:
            box = (max(0, math.floor(min(a[0], b[0]) - radius)), max(0, math.floor(min(a[1], b[1]) - radius)),
                   min(width, math.ceil(max(a[0], b[0]) + radius)), min(height, math.ceil(max(a[1], b[1]) + radius)))
            for key, clipped in segment_tiles(a, b, box, radius):
                check()
                tests += (clipped[2] - clipped[0]) * (clipped[3] - clipped[1])
                if tests > MAX_TESTS:
                    raise invalid_argument("Brush tiled regions exceed 2,000,000 candidate pixel tests; split the logical work explicitly.")
                tiles.setdefault(key, []).append((a, b, clipped))
            regions.append((a, b, box))
        prepared.append({"regions": regions, "tiles": tiles, "radius": radius, "color": color, "opacity": opacity,
                         "hardness": hardness, "blend": blend})
    return prepared, tests


def srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def paint_steps(source: array, width: int, height: int, strokes: list[dict], role: str, *, srgb=False, check=lambda: None):
    """Yield bounded CPU work progress; no Blender calls or mutation between yields."""
    result = array("f", source)
    for offset in range(0, len(result), 4):
        if offset % 1024 == 0:
            check()
            yield {"phase": "normalizing", "completed": offset // 4, "total": width * height}
        if any(not math.isfinite(source[offset + channel]) or not 0 <= source[offset + channel] <= (1. if srgb or role == "DATA" or channel == 3 else 16.) for channel in range(4)):
            raise invalid_argument("Painting requires finite nonnegative RGB within its role bound and alpha within [0,1].")
        if srgb:
            for channel in range(3):
                result[offset + channel] = srgb_to_linear(source[offset + channel])
    touched: set[tuple[int, int]] = set()
    max_coverage_bytes = 0
    for stroke_index, stroke in enumerate(strokes):
        # Maximum coverage per stroke avoids repeated opacity buildup at joins,
        # repeated points and overlapping segments. Separate strokes do accumulate.
        visits = 0
        applied = 0
        total_visits = sum((box[2] - box[0]) * (box[3] - box[1]) for regions in stroke["tiles"].values() for _a, _b, box in regions)
        total_apply = sum(min(TILE_SIZE, width - tx) * min(TILE_SIZE, height - ty) for tx, ty in stroke["tiles"])
        radius, hardness = stroke["radius"], stroke["hardness"]
        for (tx, ty), regions in stroke["tiles"].items():
            touched.add((tx, ty))
            tw, th = min(TILE_SIZE, width - tx), min(TILE_SIZE, height - ty)
            coverage = array("d", [0.]) * (tw * th)
            max_coverage_bytes = max(max_coverage_bytes, len(coverage) * coverage.itemsize)
            for a, b, (x0, y0, x1, y1) in regions:
                dx, dy = b[0] - a[0], b[1] - a[1]
                length2 = dx * dx + dy * dy
                for y in range(y0, y1):
                    for x in range(x0, x1):
                        visits += 1
                        if visits % 256 == 0:
                            check()
                            yield {"phase": "coverage", "stroke": stroke_index + 1, "strokes": len(strokes), "completed": visits, "total": total_visits}
                        vx, vy = x + .5 - a[0], y + .5 - a[1]
                        t = max(0., min(1., (vx * dx + vy * dy) / length2)) if length2 else 0.
                        distance = math.hypot(vx - t * dx, vy - t * dy)
                        if distance >= radius:
                            continue
                        fraction = 1. if distance <= radius * hardness else (radius - distance) / (radius * (1 - hardness))
                        value = max(0., min(1., fraction * fraction * (3 - 2 * fraction))) * stroke["opacity"]
                        index = (y - ty) * tw + x - tx
                        if value > coverage[index]:
                            coverage[index] = value
            color = stroke["color"]
            for index, value in enumerate(coverage):
                if applied % 256 == 0:
                    check()
                    yield {"phase": "applying", "stroke": stroke_index + 1, "strokes": len(strokes), "completed": applied, "total": total_apply}
                applied += 1
                if not value:
                    continue
                offset = ((ty + index // tw) * width + tx + index % tw) * 4
                if role == "DATA":
                    for channel in range(4):
                        result[offset + channel] = result[offset + channel] * (1 - value) + color[channel] * value
                else:
                    value *= color[3]
                    if stroke["blend"] == "ERASE_ALPHA":
                        result[offset + 3] *= 1 - value
                    else:
                        alpha = value + result[offset + 3] * (1 - value)
                        if alpha:
                            for channel in range(3):
                                result[offset + channel] = (color[channel] * value + result[offset + channel] * result[offset + 3] * (1 - value)) / alpha
                        result[offset + 3] = alpha
            del coverage
    changed = []
    count = 0
    total_compare = sum(min(TILE_SIZE, width - tx) * min(TILE_SIZE, height - ty) for tx, ty in touched)
    baseline_rgb = array("f", [0., 0., 0.])
    for compared, index in enumerate(comparison_rows(touched, width, height)):
        offset = index * 4
        if compared % 256 == 0:
            check()
            yield {"phase": "comparing", "completed": compared, "total": total_compare}
        if srgb:
            for channel in range(3):
                baseline_rgb[channel] = srgb_to_linear(source[offset + channel])
            differs = any(result[offset + channel] != baseline_rgb[channel] for channel in range(3)) or result[offset + 3] != source[offset + 3]
        else:
            differs = any(result[offset + channel] != source[offset + channel] for channel in range(4))
        if differs:
            count += 1
            if len(changed) < 64:
                changed.append([offset // 4 % width, offset // 4 // width])
    check()
    return result, {"painted_pixels": count, "changed_pixel_examples": changed,
                    "examples_truncated": count > len(changed), "source_srgb_converted_to_linear": srgb,
                    "coverage_tile_size": TILE_SIZE, "coverage_scratch_max_bytes": max_coverage_bytes,
                    "baseline_copy_bytes": 0, "comparison_pixels": total_compare,
                    "pixel_array_bytes": len(result) * result.itemsize,
                    "private_pixel_buffers_peak_estimate_bytes": 2 * len(result) * result.itemsize + max(max_coverage_bytes, 12),
                    "memory_estimate_scope": "Source/output pixel arrays and bounded coverage/comparison scratch only; excludes plan metadata, Blender/native/GPU/undo/file buffers and allocator overhead."}


def paint(source: array, width: int, height: int, strokes: list[dict], role: str, *, srgb=False, check=lambda: None) -> tuple[array, dict]:
    work = paint_steps(source, width, height, strokes, role, srgb=srgb, check=check)
    while True:
        try:
            next(work)
        except StopIteration as completed:
            return completed.value
