"""Bounded animation inspection and explicit keyframe editing."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, get_object, int_param, require_blender

_MAX_ABS_FRAME = 1_000_000.0
_MAX_DATA_PATH_LENGTH = 512
_MAX_GROUP_NAME_LENGTH = 128


def _required_string(
    params: Mapping[str, Any],
    name: str,
    *,
    maximum: int,
) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument(f"'{name}' must be a non-empty string.", parameter=name)
    value = value.strip()
    if len(value) > maximum or any(ord(character) < 32 for character in value):
        raise invalid_argument(
            f"'{name}' must contain at most {maximum} printable characters.",
            parameter=name,
        )
    return value


def _data_path(params: Mapping[str, Any]) -> str:
    return _required_string(
        params,
        "data_path",
        maximum=_MAX_DATA_PATH_LENGTH,
    )


def _frame_param(params: Mapping[str, Any], name: str, default: float) -> float:
    return float_param(
        params,
        name,
        default,
        minimum=-_MAX_ABS_FRAME,
        maximum=_MAX_ABS_FRAME,
    )


def _index_param(params: Mapping[str, Any]) -> int:
    return int_param(params, "index", -1, minimum=-1, maximum=16_384)


def _fcurve_identity(curve: Any) -> int:
    try:
        return int(curve.as_pointer())
    except (AttributeError, TypeError, ValueError):
        return id(curve)


def _action_fcurves(action: Any) -> Iterable[tuple[Any, int | None]]:
    """Yield legacy and layered Action curves without duplicating compatibility views."""

    seen: set[int] = set()
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        for curve in legacy:
            identity = _fcurve_identity(curve)
            if identity not in seen:
                seen.add(identity)
                yield curve, None
    for layer in getattr(action, "layers", ()):  # Blender 4.4+ layered actions.
        for strip in getattr(layer, "strips", ()):
            for channelbag in getattr(strip, "channelbags", ()):
                slot_handle = getattr(channelbag, "slot_handle", None)
                for curve in getattr(channelbag, "fcurves", ()):
                    identity = _fcurve_identity(curve)
                    if identity not in seen:
                        seen.add(identity)
                        yield curve, int(slot_handle) if slot_handle is not None else None


def _serialize_keyframe(point: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "frame": float(point.co[0]),
        "value": float(point.co[1]),
        "interpolation": str(point.interpolation),
    }
    easing = getattr(point, "easing", None)
    if easing is not None:
        result["easing"] = str(easing)
    return result


def _serialize_curve(
    curve: Any,
    *,
    slot_handle: int | None,
    remaining_keyframes: int,
) -> tuple[dict[str, Any], int, bool]:
    points = curve.keyframe_points
    point_count = len(points)
    included = list(islice(points, remaining_keyframes))
    result: dict[str, Any] = {
        "data_path": str(curve.data_path),
        "array_index": int(curve.array_index),
        "group": curve.group.name if getattr(curve, "group", None) else None,
        "mute": bool(curve.mute),
        "keyframe_count": point_count,
        "keyframes": [_serialize_keyframe(point) for point in included],
    }
    if slot_handle is not None:
        result["slot_handle"] = slot_handle
    truncated = len(included) < point_count
    return result, len(included), truncated


def _inspect_action(
    action: Any,
    *,
    max_curves: int,
    max_keyframes: int,
) -> dict[str, Any]:
    observed_curves = list(islice(_action_fcurves(action), max_curves + 1))
    curves_truncated = len(observed_curves) > max_curves
    serialized: list[dict[str, Any]] = []
    keyframes_used = 0
    keyframes_truncated = False
    for curve, slot_handle in observed_curves[:max_curves]:
        remaining = max(0, max_keyframes - keyframes_used)
        item, used, truncated = _serialize_curve(
            curve,
            slot_handle=slot_handle,
            remaining_keyframes=remaining,
        )
        serialized.append(item)
        keyframes_used += used
        keyframes_truncated = keyframes_truncated or truncated
    slot_collection = getattr(action, "slots", ())
    slot_count = len(slot_collection)
    slots = [
        {
            "identifier": str(getattr(slot, "identifier", "")),
            "display_name": str(getattr(slot, "display_name", "")),
            "target_id_type": str(getattr(slot, "target_id_type", "")),
            "handle": int(getattr(slot, "handle", 0)),
        }
        for slot in islice(slot_collection, 256)
    ]
    return {
        "name": action.name,
        "frame_range": [float(value) for value in action.frame_range],
        "is_layered": bool(getattr(action, "is_action_layered", False)),
        "slot_count": slot_count,
        "slots": slots,
        "fcurve_count": len(observed_curves),
        "fcurve_count_exact": not curves_truncated,
        "fcurves": serialized,
        "truncated": {
            "fcurves": curves_truncated,
            "keyframes": keyframes_truncated,
            "slots": len(slots) < slot_count,
        },
    }


def _matching_curves(action: Any, data_path: str, index: int) -> tuple[list[dict[str, Any]], bool]:
    matches: list[dict[str, Any]] = []
    scan_limit = 4_096
    scanned = 0
    truncated = False
    for curve, slot_handle in islice(_action_fcurves(action), scan_limit + 1):
        scanned += 1
        if scanned > scan_limit:
            truncated = True
            break
        if curve.data_path != data_path or (index != -1 and curve.array_index != index):
            continue
        item, _, truncated = _serialize_curve(
            curve,
            slot_handle=slot_handle,
            remaining_keyframes=32,
        )
        item["keyframes_truncated"] = truncated
        matches.append(item)
        if len(matches) >= 32:
            truncated = True
            break
    return matches, truncated


def _validate_resolvable_data_path(obj: Any, data_path: str) -> None:
    try:
        obj.path_resolve(data_path)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise invalid_argument(
            "The data path does not resolve on the named object.",
            object=obj.name,
            data_path=data_path,
        ) from exc


def inspect_animation(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    max_curves = int_param(params, "max_curves", 128, minimum=1, maximum=512)
    max_keyframes = int_param(params, "max_keyframes", 1_000, minimum=1, maximum=10_000)
    animation_data = obj.animation_data
    action = animation_data.action if animation_data is not None else None
    result: dict[str, Any] = {
        "object": obj.name,
        "has_animation_data": animation_data is not None,
        "action": None,
    }
    if action is not None:
        result["action"] = _inspect_action(
            action,
            max_curves=max_curves,
            max_keyframes=max_keyframes,
        )
        slot = getattr(animation_data, "action_slot", None)
        if slot is not None:
            result["action_slot"] = {
                "identifier": str(getattr(slot, "identifier", "")),
                "handle": int(getattr(slot, "handle", 0)),
            }
    drivers = animation_data.drivers if animation_data is not None else ()
    driver_count = len(drivers)
    result["driver_count"] = driver_count
    result["drivers"] = [
        {"data_path": str(curve.data_path), "array_index": int(curve.array_index)}
        for curve in islice(drivers, 128)
    ]
    result["drivers_truncated"] = driver_count > 128
    return result


def set_frame(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    scene = bpy.context.scene
    requested = _frame_param(params, "frame", float(scene.frame_current_final))
    integer_frame = math.floor(requested)
    subframe = requested - integer_frame
    scene.frame_set(integer_frame, subframe=subframe)
    return {
        "scene": scene.name,
        "requested_frame": requested,
        "frame": int(scene.frame_current),
        "subframe": float(scene.frame_subframe),
        "frame_final": float(scene.frame_current_final),
    }


def set_range(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    scene = bpy.context.scene
    start = int_param(
        params,
        "start",
        int(scene.frame_start),
        minimum=-int(_MAX_ABS_FRAME),
        maximum=int(_MAX_ABS_FRAME),
    )
    end = int_param(
        params,
        "end",
        int(scene.frame_end),
        minimum=-int(_MAX_ABS_FRAME),
        maximum=int(_MAX_ABS_FRAME),
    )
    if end < start:
        raise invalid_argument("'end' must be greater than or equal to 'start'.")
    use_preview = bool_param(params, "use_preview", False)
    preview_start = int_param(
        params,
        "preview_start",
        start,
        minimum=start,
        maximum=end,
    )
    preview_end = int_param(
        params,
        "preview_end",
        end,
        minimum=start,
        maximum=end,
    )
    if preview_end < preview_start:
        raise invalid_argument("'preview_end' must be at least 'preview_start'.")
    scene.frame_start = start
    scene.frame_end = end
    scene.use_preview_range = use_preview
    if use_preview:
        scene.frame_preview_start = preview_start
        scene.frame_preview_end = preview_end
    return {
        "scene": scene.name,
        "frame_start": int(scene.frame_start),
        "frame_end": int(scene.frame_end),
        "use_preview_range": bool(scene.use_preview_range),
        "preview_start": int(scene.frame_preview_start),
        "preview_end": int(scene.frame_preview_end),
    }


def insert_keyframe(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    data_path = _data_path(params)
    _validate_resolvable_data_path(obj, data_path)
    bpy = require_blender()
    frame = _frame_param(params, "frame", float(bpy.context.scene.frame_current_final))
    index = _index_param(params)
    group_value = params.get("group")
    if group_value is not None:
        group = _required_string(params, "group", maximum=_MAX_GROUP_NAME_LENGTH)
    else:
        group = ""
    options_value = params.get("options", [])
    if not isinstance(options_value, Sequence) or isinstance(options_value, (str, bytes)):
        raise invalid_argument("'options' must be an array of strings.")
    if len(options_value) > 8 or any(not isinstance(value, str) for value in options_value):
        raise invalid_argument("'options' must contain at most eight strings.")
    options = {value.strip().upper() for value in options_value}
    allowed = {"INSERTKEY_NEEDED", "INSERTKEY_VISUAL", "INSERTKEY_REPLACE", "INSERTKEY_AVAILABLE", "INSERTKEY_CYCLE_AWARE"}
    if len(options) > len(allowed) or not options <= allowed:
        raise invalid_argument("Unsupported keyframe insertion option.", supported=sorted(allowed))
    try:
        inserted = bool(
            obj.keyframe_insert(
                data_path=data_path,
                index=index,
                frame=frame,
                group=group,
                options=options,
            )
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not insert the requested keyframe.",
            {"object": obj.name, "data_path": data_path, "detail": str(exc)},
        ) from exc
    action = obj.animation_data.action if obj.animation_data else None
    matching, matching_truncated = (
        _matching_curves(action, data_path, index) if action else ([], False)
    )
    return {
        "inserted": inserted,
        "object": obj.name,
        "data_path": data_path,
        "array_index": index,
        "frame": frame,
        "action": action.name if action else None,
        "matching_fcurves": matching,
        "matching_fcurves_truncated": matching_truncated,
    }


def delete_keyframe(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    data_path = _data_path(params)
    _validate_resolvable_data_path(obj, data_path)
    bpy = require_blender()
    frame = _frame_param(params, "frame", float(bpy.context.scene.frame_current_final))
    index = _index_param(params)
    group_value = params.get("group")
    if group_value is not None:
        group = _required_string(params, "group", maximum=_MAX_GROUP_NAME_LENGTH)
    else:
        group = ""
    try:
        deleted = bool(
            obj.keyframe_delete(
                data_path=data_path,
                index=index,
                frame=frame,
                group=group,
            )
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not delete the requested keyframe.",
            {"object": obj.name, "data_path": data_path, "detail": str(exc)},
        ) from exc
    action = obj.animation_data.action if obj.animation_data else None
    matching, matching_truncated = (
        _matching_curves(action, data_path, index) if action else ([], False)
    )
    return {
        "deleted": deleted,
        "object": obj.name,
        "data_path": data_path,
        "array_index": index,
        "frame": frame,
        "action": action.name if action else None,
        "matching_fcurves": matching,
        "matching_fcurves_truncated": matching_truncated,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "animation.inspect",
        inspect_animation,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="animation",
        description="Inspect one object's action, bounded F-curves, keyframes, slots, and drivers.",
    )
    common = {
        "permissions": (Permission.EDIT_ANIMATION,),
        "toolset": "animation",
        "modifies": True,
    }
    registry.register(
        "animation.set_frame",
        set_frame,
        description="Set the scene's current frame and subframe explicitly.",
        automatic_checkpoint=False,
        **common,
    )
    registry.register(
        "animation.set_range",
        set_range,
        description="Set scene playback and optional preview frame ranges.",
        **common,
    )
    registry.register(
        "animation.keyframe_insert",
        insert_keyframe,
        description="Insert a keyframe on an explicit object RNA data path.",
        **common,
    )
    registry.register(
        "animation.keyframe_delete",
        delete_keyframe,
        description="Delete a keyframe from an explicit object RNA data path.",
        **common,
    )


__all__ = ["register_tools"]
