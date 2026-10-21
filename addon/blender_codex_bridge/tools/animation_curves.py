"""Explicit Action versions and bounded existing F-curve authoring."""

from __future__ import annotations

import math
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, int_param, reject_unknown_params, require_blender
from ._object_safety import require_local_object, require_owned_action
from ._rna import bounded_name

_MAX_POINTS = 1024
_POINT_FIELDS = (
    "interpolation", "easing", "handle_left_type", "handle_right_type", "handle_left", "handle_right",
)
_ENUMS = {
    "interpolation": {"CONSTANT", "LINEAR", "BEZIER"},
    "easing": {"AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"},
    "handle_left_type": {"FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"},
    "handle_right_type": {"FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"},
}


def _active(params: Mapping[str, Any], *, edit: bool) -> tuple[Any, Any, Any]:
    obj = get_object(params.get("object_name"), allow_active=False)
    require_local_object(obj, operation="Action authoring")
    data = obj.animation_data
    if data is None or data.action is None:
        raise invalid_argument("The named object must have an active Action.")
    if getattr(data, "use_tweak_mode", False):
        raise invalid_argument("Exit NLA tweak mode before Action authoring.")
    if edit:
        require_owned_action(obj, operation="F-curve authoring")
    return obj, data, data.action


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_argument(f"{name} must be a finite bounded number.")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise invalid_argument(f"{name} must be a finite bounded number.") from exc
    if not math.isfinite(result) or abs(result) > 1_000_000:
        raise invalid_argument(f"{name} must be finite and within +/-1,000,000.")
    return result


def _point_state(point: Any) -> dict[str, Any]:
    return {
        "frame": float(point.co[0]), "value": float(point.co[1]),
        "interpolation": str(point.interpolation), "easing": str(point.easing),
        "handle_left_type": str(point.handle_left_type), "handle_right_type": str(point.handle_right_type),
        "handle_left": [float(v) for v in point.handle_left],
        "handle_right": [float(v) for v in point.handle_right],
    }


def _bounded_items(items: Any, limit: int, label: str) -> list[Any]:
    values = list(islice(items, limit + 1))
    if len(values) > limit:
        raise invalid_argument(f"Action exceeds the {limit}-{label} authoring budget.")
    return values


def _curve_inventory(action: Any) -> list[tuple[int | None, Any]]:
    if not getattr(action, "is_action_layered", False):
        return [(None, curve) for curve in _bounded_items(action.fcurves, 1024, "curve")]
    _bounded_items(getattr(action, "slots", ()), 64, "slot")
    found = []
    for layer in _bounded_items(action.layers, 16, "layer"):
        for strip in _bounded_items(layer.strips, 32, "strip"):
            bags = getattr(strip, "channelbags", None)
            if bags is None:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This layered Action strip has no reviewed channelbag API.")
            for bag in _bounded_items(bags, 64, "channelbag"):
                for curve in _bounded_items(bag.fcurves, 1024, "curve"):
                    found.append((bag.slot_handle, curve))
                    if len(found) > 1024:
                        raise invalid_argument("Action exceeds the 1024-curve authoring budget.")
    return found


def _slot_curves(data: Any, action: Any, requested_slot: Any) -> tuple[list[Any], str | None]:
    if not getattr(action, "is_action_layered", False):
        if requested_slot is not None:
            raise invalid_argument("Legacy Actions do not have slots.")
        return [curve for _, curve in _curve_inventory(action)], None
    slot = getattr(data, "action_slot", None)
    if slot is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Layered Action authoring requires an assigned active slot.")
    identifier = str(slot.identifier)
    if requested_slot is not None and requested_slot != identifier:
        raise invalid_argument("slot_identifier must identify this object's active Action slot.", active_slot=identifier)
    return [curve for handle, curve in _curve_inventory(action) if handle == slot.handle], identifier


def action_copy(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Create and bind one explicitly named independent active Action version."""
    del context
    reject_unknown_params(params, {"object_name", "new_name"})
    obj, data, source = _active(params, edit=False)
    name = bounded_name(params.get("new_name"), "new_name", maximum=63)
    if len(name.encode("utf-8")) > 63:
        raise invalid_argument("new_name must fit 63 UTF-8 bytes.")
    bpy = require_blender()
    if bpy.data.actions.get(name) is not None:
        raise invalid_argument("An Action with new_name already exists.", action=name)
    old_slot = getattr(data, "action_slot", None)
    old_identifier = getattr(old_slot, "identifier", None)
    if getattr(source, "is_action_layered", False) and old_slot is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Assign an active slot before copying a layered Action.")
    points = 0
    for _, curve in _curve_inventory(source):
        if len(curve.keyframe_points) > 1024 or len(getattr(curve, "sampled_points", ())):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action copies support unsampled curves with at most 1024 keyframes each.")
        points += len(curve.keyframe_points)
        if points > 16384 or len(getattr(curve, "modifiers", ())) > 32:
            raise invalid_argument("Action copy exceeds the 16384-keyframe or 32-modifier-per-curve budget.")
    created = None
    try:
        created = source.copy()
        created.name = name
        created.use_fake_user = False
        if created.name != name:
            raise RuntimeError("Blender could not preserve the explicit Action name.")
        target_slot = None
        if old_identifier is not None:
            choices = [slot for slot in created.slots if slot.identifier == old_identifier]
            if len(choices) != 1:
                raise RuntimeError("Copied Action did not preserve its active slot identity.")
            target_slot = choices[0]
        data.action = created
        if target_slot is not None:
            data.action_slot = target_slot
        if data.action != created or (target_slot is not None and data.action_slot != target_slot):
            raise RuntimeError("Independent Action binding did not verify.")
    except Exception as exc:
        restored = False
        try:
            data.action = source
            if old_slot is not None:
                data.action_slot = old_slot
            restored = data.action == source and (old_slot is None or data.action_slot == old_slot)
        except Exception:
            pass
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Action version creation failed; inspect retained data before retrying.",
            {"object": obj.name, "source_action": source.name,
             "retained_action": getattr(created, "name", None), "rollback_verified": restored,
             "possible_mutation": created is not None or not restored},
        ) from exc
    return {
        "object": obj.name, "affected_objects": [obj.name], "source_action": source.name,
        "action": created.name, "slot_identifier": old_identifier, "independent_version": True,
        "source_retained_in_session": True, "source_users_after": int(source.users),
        "source_fake_user": bool(source.use_fake_user),
        "source_save_retention": "REFERENCED" if source.users else "SESSION_ONLY",
    }


def curve_edit(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Edit exact existing keyframes; no implicit insertion, channel or slot guesses."""
    del context
    reject_unknown_params(params, {"object_name", "data_path", "index", "keyframes", "extrapolation", "slot_identifier"})
    obj, data, action = _active(params, edit=True)
    path = bounded_name(params.get("data_path"), "data_path", maximum=512)
    index = int_param(params, "index", 0, minimum=0, maximum=16384)
    curves, slot = _slot_curves(data, action, params.get("slot_identifier"))
    matches = [curve for curve in curves if curve.data_path == path and curve.array_index == index]
    if len(matches) != 1:
        raise invalid_argument("Choose exactly one existing F-curve by data_path, index and active slot.", matches=len(matches))
    curve = matches[0]
    points = list(islice(curve.keyframe_points, _MAX_POINTS + 1))
    if len(points) > _MAX_POINTS or len(getattr(curve, "sampled_points", ())):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Authoring supports at most 1024 existing unsampled keyframes.")
    edits = params.get("keyframes", [])
    if not isinstance(edits, list) or len(edits) > 256:
        raise invalid_argument("keyframes must contain at most 256 existing-frame edits.")
    extrapolation = params.get("extrapolation")
    if extrapolation is not None and (not isinstance(extrapolation, str) or extrapolation not in {"CONSTANT", "LINEAR"}):
        raise invalid_argument("extrapolation must be CONSTANT or LINEAR.")
    if not edits and extrapolation is None:
        raise invalid_argument("At least one keyframe edit or extrapolation is required.")
    prepared = []
    seen = set()
    for edit in edits:
        if not isinstance(edit, Mapping):
            raise invalid_argument("Each keyframe edit must be an object.")
        reject_unknown_params(edit, {"frame", *_POINT_FIELDS})
        frame = _number(edit.get("frame"), "frame")
        candidates = [point for point in points if abs(float(point.co[0]) - frame) <= 1e-6]
        if len(candidates) != 1 or id(candidates[0]) in seen:
            raise invalid_argument("Each edit must identify one distinct existing frame.", frame=frame)
        point = candidates[0]
        seen.add(id(point))
        values = {}
        for field in _POINT_FIELDS:
            if field not in edit:
                continue
            value = edit[field]
            if field in _ENUMS:
                if not isinstance(value, str) or value not in _ENUMS[field]:
                    raise invalid_argument(f"Unsupported {field}.", supported=sorted(_ENUMS[field]))
            else:
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise invalid_argument(f"{field} requires [frame, value].")
                value = tuple(_number(item, field) for item in value)
                kind = edit.get(f"{field}_type", getattr(point, f"{field}_type"))
                if kind != "FREE":
                    raise invalid_argument("Explicit handle coordinates require the corresponding FREE handle type.")
            values[field] = value
        if not values:
            raise invalid_argument("Each frame requires an interpolation/easing/handle change.")
        prepared.append((float(point.co[0]), values))
    before = [_point_state(point) for point in points]
    old_extrapolation = curve.extrapolation
    try:
        if extrapolation is not None:
            curve.extrapolation = extrapolation
        points = list(curve.keyframe_points)
        for frame, values in prepared:
            point = next(point for point in points if float(point.co[0]) == frame)
            for field, value in values.items():
                setattr(point, field, value)
                if field in _ENUMS and getattr(point, field) != value:
                    raise RuntimeError(f"Immediate keyframe readback failed for {field}.")
        curve.update()
        # FCurve.update may reorder/reallocate native points; old RNA wrappers
        # must not be used for readback or recovery after that call.
        points = list(curve.keyframe_points)
        for frame, values in prepared:
            point = next(point for point in points if float(point.co[0]) == frame)
            for field, value in values.items():
                observed = getattr(point, field)
                if field.startswith("handle_") and not field.endswith("_type"):
                    if any(abs(float(a) - b) > max(1e-5, abs(b) * 1e-6) for a, b in zip(observed, value, strict=True)):
                        raise RuntimeError("Native handle readback did not match the requested value.")
                elif observed != value:
                    raise RuntimeError(f"Native keyframe {field} readback {observed!r} did not match {value!r} at frame {frame}.")
    except Exception as exc:
        restored = False
        try:
            curve.extrapolation = old_extrapolation
            for saved in before:
                point = next(point for point in curve.keyframe_points if float(point.co[0]) == saved["frame"])
                for field in _POINT_FIELDS:
                    setattr(point, field, saved[field])
            curve.update()
            restored = curve.extrapolation == old_extrapolation and [_point_state(point) for point in curve.keyframe_points] == before
        except Exception:
            pass
        raise BridgeError(ErrorCode.OPERATION_FAILED, "F-curve edit failed; reinspect before continuing.",
                          {"object": obj.name, "action": action.name, "rollback_verified": restored,
                           "possible_mutation": not restored}) from exc
    return {
        "object": obj.name, "affected_objects": [obj.name], "action": action.name,
        "data_path": path, "index": index, "slot_identifier": slot,
        "extrapolation": curve.extrapolation, "edited_frames": [frame for frame, _ in prepared],
        "keyframes": [_point_state(point) for point in curve.keyframe_points], "truncated": False,
    }


def register_tools(registry: ToolRegistry) -> None:
    common = {"permissions": (Permission.EDIT_ANIMATION,), "toolset": "animation", "modifies": True}
    registry.register("animation.action_copy", action_copy, description="Copy and bind an independent named active Action; unreferenced source retention is session-only.", **common)
    registry.register("animation.curve_edit", curve_edit, description="Edit bounded existing active-Action keyframe interpolation, easing and handles.", **common)
