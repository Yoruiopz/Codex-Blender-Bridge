"""Bounded UV-coordinate raster evidence, not a screenshot or a quality verdict."""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, int_param, reject_unknown_params
from ..viewport import _cleanup_managed_captures, _managed_capture_path
from .mesh import _id_name
from .uv import _edit_data, _mesh_object, _uses_edit_data

MAX_FACES = 4_096
MAX_CORNERS = 16_384
MAX_RASTER_STEPS = 4_000_000


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _faces(params: Mapping[str, Any], context: ToolContext) -> tuple[str, str, list[list[tuple[float, float, bool]]], str]:
    _id_name(params.get("object_name"), "object_name")
    name = _id_name(params.get("uv_layer"), "uv_layer")
    selected_only = bool_param(params, "selected_only", False)
    reference = params.get("selection_id")
    if reference is not None and (not isinstance(reference, str) or not reference):
        raise invalid_argument("'selection_id' must be a non-empty string.")
    obj = _mesh_object(params)
    edit = _uses_edit_data(obj)
    if reference is not None and obj.mode != "EDIT":
        raise BridgeError(ErrorCode.INVALID_MODE, "UV selection references require Edit Mode.")
    if edit:
        _bm, layer, faces = _edit_data(obj, name, reference, selected_only or reference is not None)
    else:
        layer = obj.data.uv_layers.get(name)
        if layer is None:
            raise invalid_argument("The named UV layer does not exist.")
        faces = [face for face in obj.data.polygons if not selected_only or face.select]
    if len(faces) > MAX_FACES:
        raise invalid_argument("UV capture exceeds its face budget; narrow selected/reference scope.", maximum_faces=MAX_FACES)
    records = []
    total = 0
    for index, face in enumerate(faces):
        count = len(face.loops) if edit else face.loop_total
        total += count
        if total > MAX_CORNERS:
            raise invalid_argument("UV capture exceeds its corner budget; narrow selected/reference scope.", maximum_corners=MAX_CORNERS)
        points = []
        for corner in range(count):
            data = face.loops[corner][layer] if edit else layer.data[face.loop_start + corner]
            u, v = float(data.uv[0]), float(data.uv[1])
            if not math.isfinite(u) or not math.isfinite(v):
                raise invalid_argument("UV capture contains non-finite coordinates; repair/narrow the scope first.")
            if max(abs(u), abs(v)) > 1_000_000:
                raise invalid_argument("UV capture exceeds its safe coordinate magnitude of 1,000,000.")
            points.append((u, v, bool(data.pin_uv)))
        records.append(points)
        if index % 64 == 0:
            _check(context)
    if not total:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "No UV corners were found in the capture scope.")
    return obj.name, layer.name, records, "LIVE_EDIT_BMESH" if edit else "OBJECT_MESH_DATA"


def _clip(a: tuple[float, float], b: tuple[float, float], bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    minimum_u, minimum_v, maximum_u, maximum_v = bounds
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - minimum_u), (dx, maximum_u - a[0]),
                 (-dy, a[1] - minimum_v), (dy, maximum_v - a[1])):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            low = max(low, q / p)
        else:
            high = min(high, q / p)
        if low > high:
            return None
    return a[0] + low * dx, a[1] + low * dy, a[0] + high * dx, a[1] + high * dy


def _png(size: int, pixels: bytearray) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    raw = b"".join(b"\0" + pixels[row * size * 3:(row + 1) * size * 3] for row in range(size))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def capture_layout(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "selected_only", "selection_id", "size", "view"})
    size = int_param(params, "size", 512, minimum=256, maximum=1_024)
    view = params.get("view", "UNIT_TILE")
    if not isinstance(view, str) or view not in {"UNIT_TILE", "FIT"}:
        raise invalid_argument("'view' must be UNIT_TILE or FIT.")
    obj, layer, faces, data_state = _faces(params, context)
    points = [point for face in faces for point in face]
    if view == "FIT":
        low_u, high_u = min(p[0] for p in points), max(p[0] for p in points)
        low_v, high_v = min(p[1] for p in points), max(p[1] for p in points)
        span = max(high_u - low_u, high_v - low_v, 1e-6) * 1.1
        center_u, center_v = (low_u + high_u) * .5, (low_v + high_v) * .5
        bounds = (center_u - span * .5, center_v - span * .5, center_u + span * .5, center_v + span * .5)
    else:
        bounds = (-.05, -.05, 1.05, 1.05)
    pixels = bytearray((245, 247, 250)) * (size * size)
    raster_steps, lines = 0, 0

    def pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < size and 0 <= y < size:
            offset = (y * size + x) * 3
            pixels[offset:offset + 3] = bytes(color)

    def project(u: float, v: float) -> tuple[int, int]:
        return (max(0, min(size - 1, round((u - bounds[0]) / (bounds[2] - bounds[0]) * (size - 1)))),
                max(0, min(size - 1, round((bounds[3] - v) / (bounds[3] - bounds[1]) * (size - 1)))))

    def line(a: tuple[float, float], b: tuple[float, float], color: tuple[int, int, int]) -> None:
        nonlocal raster_steps, lines
        clipped = _clip(a, b, bounds)
        if clipped is None:
            return
        x, y = project(clipped[0], clipped[1])
        end_x, end_y = project(clipped[2], clipped[3])
        dx, dy = abs(end_x - x), -abs(end_y - y)
        raster_steps += max(dx, -dy) + 1
        lines += 1
        if raster_steps > MAX_RASTER_STEPS:
            raise invalid_argument("UV capture exceeds the raster-work budget; narrow scope or reduce size.", maximum_raster_steps=MAX_RASTER_STEPS)
        if lines % 128 == 0:
            _check(context)
        step_x, step_y = 1 if x < end_x else -1, 1 if y < end_y else -1
        error = dx + dy
        while True:
            pixel(x, y, color)
            if x == end_x and y == end_y:
                break
            twice = error * 2
            if twice >= dy:
                error += dy
                x += step_x
            if twice <= dx:
                error += dx
                y += step_y

    for value in (0., .25, .5, .75, 1.):
        color = (100, 110, 125) if value in {0., 1.} else (220, 225, 230)
        line((value, 0), (value, 1), color)
        line((0, value), (1, value), color)
    for index, face in enumerate(faces):
        for first, second in zip(face, face[1:] + face[:1], strict=True):
            line(first[:2], second[:2], (30, 95, 180))
        if index % 64 == 0:
            _check(context)
    outside = 0
    for u, v, pinned in points:
        if not (bounds[0] <= u <= bounds[2] and bounds[1] <= v <= bounds[3]):
            outside += 1
            continue
        if pinned:
            x, y = project(u, v)
            for delta_x in range(-2, 3):
                for delta_y in range(-2, 3):
                    pixel(x + delta_x, y + delta_y, (210, 45, 55))
    payload = _png(size, pixels)
    _check(context)
    path = _managed_capture_path()
    with path.open("xb") as stream:
        stream.write(payload)
    _cleanup_managed_captures(path.parent)
    return {"object": obj, "uv_layer": layer, "path": str(path), "mime_type": "image/png",
            "mesh_data_state": data_state,
            "width": size, "height": size, "source": "uv_coordinate_raster", "view": view,
            "view_bounds": {"min": list(bounds[:2]), "max": list(bounds[2:])},
            "face_count": len(faces), "corner_count": len(points), "outside_view_corners": outside,
            "pinned_corners": sum(point[2] for point in points), "analysis_truncated": False,
            "raster_steps": raster_steps,
            "orientation": "U right, V up; equal UV scale on both axes",
            "legend": {"blue": "UV face edges", "red": "pinned corners", "gray": "0-1 tile and quarter grid"},
            "temporary": True, "scene_changed": False, "render_result_replaced": False,
            "limitations": "Coordinate plot, not a UV-editor screenshot, texture preview or overlap/stretch/texel-density verdict. Narrowed scope omits other faces; coincident edges can visually hide overlap."}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("uv.capture_layout", capture_layout, permissions=(Permission.INSPECT_SCENE, Permission.CAPTURE_VIEWPORT),
                      toolset="uv", description="Capture a bounded managed UV-coordinate PNG without changing scene/UI/render state.")
