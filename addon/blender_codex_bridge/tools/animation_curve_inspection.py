"""Read exact active-Action curve handles through bounded point pages."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, int_param, reject_unknown_params
from ._rna import bounded_name
from .animation_curves import _slot_curves


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve inspection requires finite numeric coordinates.", {"field": field}) from exc
    if not math.isfinite(number):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve inspection requires finite numeric coordinates.", {"field": field})
    return number


def _coordinates(value: Any, field: str) -> list[float]:
    if len(value) != 2:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve inspection requires two-dimensional keyframe coordinates.", {"field": field})
    return [_finite(value[axis], field) for axis in range(2)]


def _keyframe(point: Any) -> dict[str, Any]:
    co = _coordinates(point.co, "co")
    return {
        "frame": co[0], "value": co[1],
        "interpolation": str(point.interpolation), "easing": str(point.easing),
        "handle_left_type": str(point.handle_left_type), "handle_right_type": str(point.handle_right_type),
        "handle_left": _coordinates(point.handle_left, "handle_left"),
        "handle_right": _coordinates(point.handle_right, "handle_right"),
    }


def curve_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Inspect exactly one curve without updating or evaluating native animation."""
    del context
    reject_unknown_params(params, {"object_name", "data_path", "index", "slot_identifier", "point_offset", "point_limit"})
    object_name = bounded_name(params.get("object_name"), "object_name", maximum=256)
    path = bounded_name(params.get("data_path"), "data_path", maximum=512)
    index = int_param(params, "index", 0, minimum=0, maximum=16384)
    offset = int_param(params, "point_offset", 0, minimum=0, maximum=1_000_000)
    limit = int_param(params, "point_limit", 64, minimum=1, maximum=256)
    requested_slot = params.get("slot_identifier")
    if requested_slot is not None:
        requested_slot = bounded_name(requested_slot, "slot_identifier", maximum=256)
    obj = get_object(object_name, allow_active=False)
    data = obj.animation_data
    if data is None or data.action is None:
        raise invalid_argument("The named object must have an active Action.")
    action = data.action
    curves, slot = _slot_curves(data, action, requested_slot)
    matches = [curve for curve in curves if curve.data_path == path and curve.array_index == index]
    if len(matches) != 1:
        raise invalid_argument("Choose exactly one existing F-curve by data_path, index and active slot.", matches=len(matches))
    curve = matches[0]
    if len(getattr(curve, "sampled_points", ())):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Sampled F-curves do not provide the reviewed keyframe/handle inspection contract.")
    points = curve.keyframe_points
    count = len(points)
    if count > 1_000_000:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve inspection supports at most 1,000,000 keyframe points.", {"point_count": count})
    if offset > count:
        raise invalid_argument("point_offset must not exceed the curve's point count.", point_count=count)
    end = min(count, offset + limit)
    # Native collections support indexed reads: never traverse skipped points.
    keyframes = [_keyframe(points[ordinal]) for ordinal in range(offset, end)]
    group = curve.group
    return {
        "object": obj.name, "action": action.name, "slot_identifier": slot,
        "data_path": str(curve.data_path), "index": int(curve.array_index),
        "group": str(group.name) if group is not None else None,
        "mute": bool(curve.mute), "lock": bool(curve.lock), "extrapolation": str(curve.extrapolation),
        "point_count": count, "point_offset": offset, "point_limit": limit, "returned_points": len(keyframes),
        "keyframes": keyframes, "truncated": end < count, "next_offset": end if end < count else None,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "animation.curve_inspect", curve_inspect,
        permissions=(Permission.INSPECT_SCENE,), toolset="animation", modifies=False,
        description="Inspect an exact active-Action curve's extrapolation and paged keyframes with full Bezier handles; never update or evaluate animation.",
    )
