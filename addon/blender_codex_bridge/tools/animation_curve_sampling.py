"""Bounded direct values of one exact stored active-Action F-curve."""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, int_param, reject_unknown_params
from ._rna import bounded_name
from .animation_curves import _slot_curves

LOGGER = logging.getLogger(__name__)


def _check_request(context: ToolContext) -> None:
    """Use only the scheduler's pure lifecycle hooks, never provider callbacks."""
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    hook = getattr(context, "check_final_request", None)
    if hook is not None:
        hook()


def _frames(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 128:
        raise invalid_argument("frames must contain from 1 to 128 finite numbers.")
    result = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid_argument("frames must contain finite numbers within +/-1,000,000.")
        try:
            number = float(value)
        except (ValueError, OverflowError) as exc:
            raise invalid_argument("frames must contain finite numbers within +/-1,000,000.") from exc
        if not math.isfinite(number) or abs(number) > 1_000_000:
            raise invalid_argument("frames must contain finite numbers within +/-1,000,000.")
        effective = struct.unpack("<f", struct.pack("<f", number))[0]
        result.append((number, effective))
    return result


def _coordinates(raw: Any, field: str) -> tuple[float, float]:
    try:
        if len(raw) != 2:
            raise ValueError("Not a two-dimensional coordinate")
        result = float(raw[0]), float(raw[1])
        if not all(math.isfinite(value) for value in result):
            raise ValueError("Nonfinite coordinate")
    except (TypeError, ValueError, OverflowError, IndexError) as exc:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve sampling requires finite two-dimensional coordinates.", {"field": field}) from exc
    return result


def _validate_curve(context: ToolContext, curve: Any) -> int:
    if len(getattr(curve, "sampled_points", ())):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Sampled F-curves require a separate evaluation contract.")
    if len(getattr(curve, "modifiers", ())) or getattr(curve, "driver", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve sampling does not evaluate modifiers or drivers.")
    points = curve.keyframe_points
    count = len(points)
    if not 1 <= count <= 1024:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve sampling requires from 1 to 1024 keyframes.", {"point_count": count})
    if curve.extrapolation not in {"CONSTANT", "LINEAR"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve sampling supports CONSTANT or LINEAR extrapolation.")
    previous = -math.inf
    for ordinal in range(count):
        _check_request(context)
        point = points[ordinal]
        frame, _value = _coordinates(point.co, "co")
        _coordinates(point.handle_left, "handle_left")
        _coordinates(point.handle_right, "handle_right")
        if frame <= previous:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve sampling requires strictly increasing stored keyframe times.")
        if point.interpolation not in {"CONSTANT", "LINEAR", "BEZIER"}:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve sampling supports CONSTANT, LINEAR or BEZIER interpolation.")
        previous = frame
    if not callable(getattr(curve, "evaluate", None)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This F-curve has no reviewed native evaluation API.")
    return count


def curve_sample(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Compute stored curve values without advancing or evaluating the scene."""
    reject_unknown_params(params, {"object_name", "data_path", "frames", "index", "slot_identifier"})
    object_name = bounded_name(params.get("object_name"), "object_name", maximum=256)
    path = bounded_name(params.get("data_path"), "data_path", maximum=512)
    frames = _frames(params.get("frames"))
    index = int_param(params, "index", 0, minimum=0, maximum=16384)
    requested_slot = params.get("slot_identifier")
    if requested_slot is not None:
        requested_slot = bounded_name(requested_slot, "slot_identifier", maximum=256)
    _check_request(context)
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
    count = _validate_curve(context, curve)
    samples = []
    for ordinal, (requested, effective) in enumerate(frames):
        _check_request(context)
        try:
            value = float(curve.evaluate(effective))
        except Exception as exc:
            LOGGER.exception("Native stored F-curve evaluation failed")
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Native stored F-curve evaluation failed.", {"sample_index": ordinal}) from exc
        _check_request(context)
        if not math.isfinite(value):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native stored F-curve evaluation returned a nonfinite value.", {"sample_index": ordinal})
        samples.append({"requested_frame": requested, "evaluated_frame": effective, "value": value})
    group = curve.group
    result = {
        "object": obj.name, "action": action.name, "slot_identifier": slot,
        "data_path": str(curve.data_path), "index": int(curve.array_index),
        "group": str(group.name) if group is not None else None,
        "mute": bool(curve.mute), "lock": bool(curve.lock), "extrapolation": str(curve.extrapolation),
        "point_count": count, "sample_count": len(samples), "samples": samples,
        "evaluation_scope": "ACTIVE_ACTION_FCURVE", "scene_evaluated": False,
        "includes_nla": False, "includes_drivers": False,
        "includes_constraints": False, "includes_deformation": False,
    }
    _check_request(context)
    return result


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "animation.curve_sample", curve_sample,
        permissions=(Permission.INSPECT_SCENE,), toolset="animation", modifies=False,
        description="Sample bounded direct values of one exact active-Action curve; no scene, NLA, driver, constraint or deformation evaluation.",
    )
