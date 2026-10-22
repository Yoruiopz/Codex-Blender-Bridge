"""Explicit Action versions and bounded existing F-curve authoring."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from contextlib import suppress
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, int_param, reject_unknown_params, require_blender
from . import _animation_scope as scope
from . import animation_lifecycle
from ._object_safety import require_local_object, require_owned_action
from ._rna import bounded_name

LOGGER = logging.getLogger(__name__)


class _Boundary:
    """Live authority and exact CAS around each native authoring write."""

    def __init__(self, bpy: Any, context: ToolContext, params: Mapping[str, Any], obj: Any, action: Any, method: str, curve: Any = None):
        self.bpy, self.context, self.params, self.obj, self.action, self.curve = bpy, context, params, obj, action, curve
        self.guard = scope.Guard(bpy, context, method)
        self.guard.remember(obj, bpy.data.objects)
        self.guard.remember(action, bpy.data.actions)
        scope.editable_action(action)
        self.scope = scope.affected_scope(bpy, obj, params.get("affected_objects", []))
        self.binding, self.animation = scope.binding(obj), scope.animation_context(obj)
        self.data_key = scope.key(getattr(obj, "data", None))
        self.users = scope.action_users(bpy, action)
        self.expected = scope.action_content(action)
        self.protected = self._protected(self.expected)

    def _protected(self, content: tuple[Any, ...]) -> tuple[Any, ...]:
        if self.curve is None:
            return content
        inventory = scope.curve_inventory(self.action)
        selected = [ordinal for ordinal, (_, curve) in enumerate(inventory) if scope.key(curve) == scope.key(self.curve)]
        if len(selected) != 1:
            raise invalid_argument("Exact F-curve identity changed.")
        curves = list(content[3])
        curves[selected[0]] = (curves[selected[0]][0], "OWNED_CURVE")
        return (*content[:3], tuple(curves), *content[4:])

    def check(self) -> None:
        self.guard.gate()
        obj, _data, action = _active(self.params, edit=self.curve is not None)
        if scope.key(obj) != scope.key(self.obj) or scope.key(action) != scope.key(self.action) or scope.key(getattr(obj, "data", None)) != self.data_key:
            raise invalid_argument("Exact animation object, data or Action changed.")
        if scope.binding(obj) != self.binding or scope.animation_context(obj) != self.animation:
            raise invalid_argument("Action/slot binding or NLA context changed outside this operation.")
        if scope.affected_scope(self.bpy, obj, self.params.get("affected_objects", [])) != self.scope:
            raise invalid_argument("Animation affected-object scope changed.")
        if scope.action_users(self.bpy, action) != self.users or scope.action_content(action) != self.expected:
            raise invalid_argument("Animation content or consumers changed; stale writes and compensation refused.")

    def observe_owned_curve(self) -> None:
        observed = scope.action_content(self.action)
        if self._protected(observed) != self.protected:
            raise invalid_argument("Protected Action channels or metadata changed during native curve editing.")
        self.expected = observed

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
    reject_unknown_params(params, {"object_name", "new_name", "affected_objects"})
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
    boundary = _Boundary(bpy, context, params, obj, source, "animation.action_copy")
    object_name, source_name = obj.name, source.name
    boundary.check()
    created = None
    created_state = None

    def fresh_copy() -> None:
        boundary.check()
        assert created is not None
        scope.editable_action(created)
        if bpy.data.actions.get(created.name) != created or scope.action_content(created) != boundary.expected or scope.action_users(bpy, created)["real_users"]:
            raise invalid_argument("New Action copy changed or acquired a consumer; no further setup/binding is permitted.")
        if (created.name, bool(created.use_fake_user)) != created_state:
            raise invalid_argument("New Action copy metadata changed outside this operation.")

    try:
        created = source.copy()
        boundary.guard.remember(created, bpy.data.actions)
        created_state = (created.name, bool(created.use_fake_user))
        fresh_copy()
        created.name = name
        created_state = (name, bool(created.use_fake_user))
        fresh_copy()
        created.use_fake_user = False
        created_state = (name, False)
        fresh_copy()
        if created.name != name:
            raise RuntimeError("Blender could not preserve the explicit Action name.")
        target_slot = None
        if old_identifier is not None:
            choices = [slot for slot in created.slots if slot.identifier == old_identifier]
            if len(choices) != 1:
                raise RuntimeError("Copied Action did not preserve its active slot identity.")
            target_slot = choices[0]
        animation_lifecycle.action_bind(context, {"object_name": obj.name, "action_name": name,
            "expected_action_name": source.name, "slot_identifier": getattr(target_slot, "identifier", None),
            "affected_objects": params.get("affected_objects", []), "allow_session_only_previous": True})
        if data.action != created or (target_slot is not None and data.action_slot != target_slot):
            raise RuntimeError("Independent Action binding did not verify.")
    except Exception as exc:
        LOGGER.exception("Action copy or guarded binding failed; allocations remain for explicit inspection")
        # Binding has its own live/CAS compensation. Never replay a stale binding
        # here or remove an allocation after cancellation/ownership changes.
        restored, retained_name = False, None
        with suppress(ReferenceError, AttributeError):
            restored = scope.binding(obj) == boundary.binding
        with suppress(ReferenceError, AttributeError):
            retained_name = getattr(created, "name", None)
        raise BridgeError(
            exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Action version creation failed; inspect retained data before retrying.",
            {**(exc.context if isinstance(exc, BridgeError) else {}), "object": object_name, "source_action": source_name,
             "retained_action": retained_name, "rollback_verified": restored,
             "possible_mutation": created is not None or not restored},
        ) from exc
    return {
        "object": obj.name, "affected_objects": [obj.name, *params.get("affected_objects", [])], "source_action": source.name,
        "action": created.name, "slot_identifier": old_identifier, "independent_version": True,
        "source_retained_in_session": True, "source_users_after": int(source.users),
        "source_fake_user": bool(source.use_fake_user),
        "source_save_retention": "REFERENCED" if source.users-int(source.use_fake_user) else "FAKE_USER" if source.use_fake_user else "SESSION_ONLY",
    }


def curve_edit(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Edit exact existing keyframes; no implicit insertion, channel or slot guesses."""
    reject_unknown_params(params, {"object_name", "data_path", "index", "keyframes", "extrapolation", "slot_identifier", "affected_objects"})
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
    boundary = _Boundary(require_blender(), context, params, obj, action, "animation.curve_edit", curve)
    object_name, action_name = obj.name, action.name

    def write(field: str, value: Any, frame: float | None = None) -> None:
        boundary.check()
        # Never reuse a KeyframePoint wrapper across a live callback or a
        # native write which can reallocate Blender's point storage.
        owner = curve if frame is None else next(point for point in curve.keyframe_points if float(point.co[0]) == frame)
        try:
            setattr(owner, field, value)
        finally:
            boundary.observe_owned_curve()

    def update() -> None:
        boundary.check()
        try:
            curve.update()
        finally:
            boundary.observe_owned_curve()

    try:
        if extrapolation is not None:
            write("extrapolation", extrapolation)
        for frame, values in prepared:
            for field, value in values.items():
                write(field, value, frame)
                point = next(point for point in curve.keyframe_points if float(point.co[0]) == frame)
                if field in _ENUMS and getattr(point, field) != value:
                    raise RuntimeError(f"Immediate keyframe readback failed for {field}.")
        update()
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
        boundary.check()
    except Exception as exc:
        restored = False
        try:
            write("extrapolation", old_extrapolation)
            for saved in before:
                for field in _POINT_FIELDS:
                    write(field, saved[field], saved["frame"])
            update()
            boundary.check()
            restored = curve.extrapolation == old_extrapolation and [_point_state(point) for point in curve.keyframe_points] == before
        except Exception:
            LOGGER.exception("Curve compensation refused or failed")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED, "F-curve edit failed; reinspect before continuing.",
                          {**(exc.context if isinstance(exc, BridgeError) else {}), "object": object_name, "action": action_name, "rollback_verified": restored,
                           "possible_mutation": not restored}) from exc
    return {
        "object": obj.name, "affected_objects": [obj.name, *params.get("affected_objects", [])], "action": action.name,
        "data_path": path, "index": index, "slot_identifier": slot,
        "extrapolation": curve.extrapolation, "edited_frames": [frame for frame, _ in prepared],
        "keyframes": [_point_state(point) for point in curve.keyframe_points], "truncated": False,
    }


def register_tools(registry: ToolRegistry) -> None:
    common = {"permissions": (Permission.EDIT_ANIMATION,), "toolset": "animation", "modifies": True}
    registry.register("animation.action_copy", action_copy, description="Copy and bind an independent named active Action; unreferenced source retention is session-only.", **common)
    registry.register("animation.curve_edit", curve_edit, description="Edit bounded existing active-Action keyframe interpolation, easing and handles.", **common)
