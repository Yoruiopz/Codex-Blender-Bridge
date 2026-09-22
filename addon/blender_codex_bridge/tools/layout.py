"""Bounded scene targeting and transactional layout of independent objects.

Layout positions are object origins, never inferred surface bounds. Mutations
deliberately reject dependencies that can override transforms or move descendants.
"""

from __future__ import annotations

import fnmatch
import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, get_object, int_param, require_blender, vector3

LOGGER = logging.getLogger(__name__)
MAX_TARGETS = 128
MAX_QUERY_SCAN = 100_000
MAX_COMPONENT = 1.0e12
_CHANNELS = ("location", "rotation_euler", "scale")
_EULER_MODES = {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}


def _known(params: Mapping[str, Any], names: set[str]) -> None:
    unknown = set(params) - names - {"_task", "task_description"}
    if unknown:
        raise invalid_argument("Unknown parameters.", parameters=sorted(unknown))


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise invalid_argument(f"'{label}' must be a non-empty string of at most 256 characters.")
    return value


def _vector(value: Any, label: str) -> tuple[float, float, float]:
    result = vector3(value, label)
    if any(abs(component) > MAX_COMPONENT for component in result):
        raise invalid_argument(f"'{label}' components must not exceed {MAX_COMPONENT:g} in magnitude.")
    return result


def _enum(params: Mapping[str, Any], name: str, default: str, choices: set[str]) -> str:
    value = params.get(name, default)
    if not isinstance(value, str) or value.upper() not in choices:
        raise invalid_argument(f"Unsupported '{name}'.", supported=sorted(choices))
    return value.upper()


def _close(actual: Sequence[float], expected: Sequence[float]) -> bool:
    return all(math.isclose(float(a), float(b), rel_tol=1.0e-6, abs_tol=1.0e-5) for a, b in zip(actual, expected, strict=True))


def _origin(obj: Any, depsgraph: Any) -> tuple[float, float, float]:
    values = tuple(float(value) for value in obj.evaluated_get(depsgraph).matrix_world.translation)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Object has a non-finite evaluated world origin.", {"object": obj.name})
    return values  # type: ignore[return-value]


def _summary(obj: Any, depsgraph: Any) -> dict[str, Any]:
    return {
        "object": obj.name,
        "type": obj.type,
        "world_origin": list(_origin(obj, depsgraph)),
        "location": [float(value) for value in obj.location],
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": [float(value) for value in obj.rotation_euler],
        "scale": [float(value) for value in obj.scale],
        "dimensions": [float(value) for value in obj.dimensions],
    }


def query_scene(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Query current view-layer objects with measured evaluated world origins."""

    del context
    _known(params, {"name_pattern", "object_types", "collection_name", "selected", "visible", "origin_min", "origin_max", "offset", "limit"})
    pattern = _name(params.get("name_pattern", "*"), "name_pattern")
    raw_types = params.get("object_types", [])
    if not isinstance(raw_types, list) or len(raw_types) > 32:
        raise invalid_argument("'object_types' must be a list of at most 32 type names.")
    object_types = {_name(value, "object_types").upper() for value in raw_types}
    selected = bool_param(params, "selected", False) if "selected" in params else None
    visible = bool_param(params, "visible", False) if "visible" in params else None
    minimum = _vector(params["origin_min"], "origin_min") if "origin_min" in params else None
    maximum = _vector(params["origin_max"], "origin_max") if "origin_max" in params else None
    if minimum is not None and maximum is not None and any(a > b for a, b in zip(minimum, maximum, strict=True)):
        raise invalid_argument("Every 'origin_min' component must be <= 'origin_max'.")
    offset = int_param(params, "offset", 0, minimum=0, maximum=MAX_QUERY_SCAN)
    limit = int_param(params, "limit", 50, minimum=1, maximum=200)
    bpy = require_blender()
    view_layer = bpy.context.view_layer
    collection = None
    if "collection_name" in params:
        name = _name(params["collection_name"], "collection_name")
        collection = bpy.data.collections.get(name)
        if collection is None and bpy.context.scene.collection.name == name:
            collection = bpy.context.scene.collection
        if collection is None:
            raise invalid_argument("Collection does not exist.", collection=name)
    view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    candidates: list[tuple[Any, tuple[float, float, float]]] = []
    scanned = 0
    scan_truncated = False
    for obj in view_layer.objects:
        if scanned == MAX_QUERY_SCAN:
            scan_truncated = True
            break
        scanned += 1
        if not fnmatch.fnmatchcase(obj.name, pattern) or (object_types and obj.type not in object_types):
            continue
        if collection is not None and obj.name not in collection.all_objects:
            continue
        if selected is not None and obj.select_get(view_layer=view_layer) != selected:
            continue
        if visible is not None and obj.visible_get(view_layer=view_layer) != visible:
            continue
        origin = _origin(obj, depsgraph)
        if minimum is not None and any(value < bound for value, bound in zip(origin, minimum, strict=True)):
            continue
        if maximum is not None and any(value > bound for value, bound in zip(origin, maximum, strict=True)):
            continue
        candidates.append((obj, origin))
    candidates.sort(key=lambda item: item[0].name)
    page = candidates[offset:offset + limit]
    next_offset = offset + len(page) if offset + len(page) < len(candidates) else None
    return {
        "scene": bpy.context.scene.name,
        "view_layer": view_layer.name,
        "scope": "CURRENT_VIEW_LAYER",
        "measurement": "EVALUATED_WORLD_ORIGINS",
        "objects": [
            {
                "object": obj.name,
                "type": obj.type,
                "world_origin": list(origin),
                "selected": bool(obj.select_get(view_layer=view_layer)),
                "visible": bool(obj.visible_get(view_layer=view_layer)),
                "parent": obj.parent.name if obj.parent else None,
            }
            for obj, origin in page
        ],
        "scanned_count": scanned,
        "matched_count": len(candidates),
        "returned_count": len(page),
        "offset": offset,
        "next_offset": next_offset,
        "matches_complete": not scan_truncated,
        "scan_truncated": scan_truncated,
        "result_truncated": scan_truncated or next_offset is not None,
    }


def _target_names(value: Any, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= MAX_TARGETS:
        raise invalid_argument(f"'object_names' must contain {minimum} to {MAX_TARGETS} explicit object names.")
    names = [_name(item, "object_names") for item in value]
    if len(set(names)) != len(names):
        raise invalid_argument("Duplicate object names are not allowed.")
    return names


def _targets(names: list[str]) -> tuple[Any, list[Any]]:
    bpy = require_blender()
    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.INVALID_MODE, "Layout editing requires Object mode; no mode or selection is changed.")
    objects = [get_object(name, allow_active=False) for name in names]
    for obj in objects:
        if obj.name not in bpy.context.view_layer.objects:
            raise invalid_argument("Layout targets must belong to the current view layer.", object=obj.name)
        if not getattr(obj, "is_editable", True) or obj.library is not None or obj.override_library is not None:
            raise invalid_argument("Layout targets must be local editable objects without library overrides.", object=obj.name)
        animation = obj.animation_data
        if (
            obj.parent is not None or len(obj.children) or len(obj.constraints)
            or obj.rigid_body is not None
            or (animation is not None and (animation.action is not None or len(animation.drivers) or len(animation.nla_tracks)))
        ):
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Layout supports independent objects only: no parents, children, constraints, rigid bodies, actions, drivers, or NLA tracks.",
                {"object": obj.name},
            )
        if (
            any(float(value) != 0.0 for value in obj.delta_location)
            or any(float(value) != 0.0 for value in obj.delta_rotation_euler)
            or tuple(float(value) for value in obj.delta_rotation_quaternion) != (1.0, 0.0, 0.0, 0.0)
            or any(float(value) != 1.0 for value in obj.delta_scale)
        ):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Layout does not support non-default delta transforms.", {"object": obj.name})
    bpy.context.view_layer.update()
    return bpy, objects


def _validate_changes(obj: Any, changes: Mapping[str, Sequence[float]]) -> None:
    for channel, value in changes.items():
        if channel == "rotation_euler" and obj.rotation_mode not in _EULER_MODES:
            raise invalid_argument("Explicit rotations require an existing Euler rotation mode.", object=obj.name, rotation_mode=obj.rotation_mode)
        locks = getattr(obj, "lock_rotation" if channel == "rotation_euler" else f"lock_{channel}")
        if any(locked and float(new) != float(old) for locked, new, old in zip(locks, value, getattr(obj, channel), strict=True)):
            raise invalid_argument("Layout does not bypass locked transform components.", object=obj.name, channel=channel)


def _commit(bpy: Any, edits: list[tuple[Any, dict[str, tuple[float, float, float]]]]) -> dict[str, Any]:
    for obj, changes in edits:
        _validate_changes(obj, changes)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    before = [_summary(obj, depsgraph) for obj, _changes in edits]
    saved = [(obj, {channel: tuple(getattr(obj, channel)) for channel in _CHANNELS}) for obj, _changes in edits]
    try:
        for obj, changes in edits:
            for channel, value in changes.items():
                setattr(obj, channel, value)
        bpy.context.view_layer.update()
        for obj, changes in edits:
            if any(not _close(getattr(obj, channel), value) for channel, value in changes.items()):
                raise RuntimeError("Blender did not retain the requested transform channels.")
            if "location" in changes and not _close(_origin(obj, depsgraph), changes["location"]):
                raise RuntimeError("Evaluated world origin does not match the requested location.")
        after = [_summary(obj, depsgraph) for obj, _changes in edits]
    except Exception as exc:
        LOGGER.exception("Layout edit failed; restoring all transform snapshots")
        restored = True
        for obj, snapshot in saved:
            for channel, value in snapshot.items():
                try:
                    setattr(obj, channel, value)
                except Exception:
                    LOGGER.exception("Failed to restore layout channel %s on %s", channel, obj.name)
                    restored = False
        try:
            bpy.context.view_layer.update()
            restored = restored and all(_close(getattr(obj, channel), value) for obj, snapshot in saved for channel, value in snapshot.items())
        except Exception:
            LOGGER.exception("Failed to verify layout rollback")
            restored = False
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Layout edit failed; original transform channels were restored." if restored else "Layout edit failed and rollback is incomplete; reinspect and recover from the checkpoint.",
            {
                "execution_started": True,
                "affected_objects": [obj.name for obj, _changes in edits],
                "rollback_complete": restored,
                "mutation_outcome_unknown": not restored,
                "verification_required": True,
                "exception_type": type(exc).__name__,
            },
        ) from exc
    return {
        "changed": any(before_item != after_item for before_item, after_item in zip(before, after, strict=True)),
        "affected_objects": [obj.name for obj, _changes in edits],
        "measurement": "EVALUATED_WORLD_ORIGINS",
        "before": before,
        "objects": after,
        "verified": True,
    }


def transform_batch(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    _known(params, {"edits"})
    raw = params.get("edits")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TARGETS:
        raise invalid_argument(f"'edits' must contain 1 to {MAX_TARGETS} transform records.")
    names: list[str] = []
    values: list[dict[str, tuple[float, float, float]]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise invalid_argument("Every transform edit must be an object.")
        _known(item, {"object_name", "location", "rotation", "scale"})
        names.append(_name(item.get("object_name"), "object_name"))
        changes = {"rotation_euler" if name == "rotation" else name: _vector(item[name], name) for name in ("location", "rotation", "scale") if name in item}
        if not changes:
            raise invalid_argument("Every transform edit requires location, rotation, or scale.")
        values.append(changes)
    _target_names(names)
    bpy, objects = _targets(names)
    return _commit(bpy, list(zip(objects, values, strict=True)))


def align_objects(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    _known(params, {"object_names", "axis", "target", "reference_object"})
    names = _target_names(params.get("object_names"), minimum=2)
    axis = _enum(params, "axis", "X", {"X", "Y", "Z"})
    target = _enum(params, "target", "CENTER", {"MIN", "MAX", "CENTER", "REFERENCE"})
    reference = params.get("reference_object")
    if target == "REFERENCE":
        if _name(reference, "reference_object") not in names:
            raise invalid_argument("The explicit reference object must be among object_names.")
    elif reference is not None:
        raise invalid_argument("'reference_object' is valid only when target is REFERENCE.")
    bpy, objects = _targets(names)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origins = [_origin(obj, depsgraph) for obj in objects]
    index = "XYZ".index(axis)
    positions = [origin[index] for origin in origins]
    coordinate = {
        "MIN": min(positions), "MAX": max(positions), "CENTER": (min(positions) + max(positions)) * 0.5,
        "REFERENCE": positions[names.index(reference)] if reference is not None else 0.0,
    }[target]
    edits = []
    for obj, origin in zip(objects, origins, strict=True):
        location = list(origin)
        location[index] = coordinate
        edits.append((obj, {"location": tuple(location)}))
    return {"axis": axis, "target": target, "coordinate": coordinate, **_commit(bpy, edits)}


def distribute_objects(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    _known(params, {"object_names", "axis"})
    names = _target_names(params.get("object_names"), minimum=3)
    axis = _enum(params, "axis", "X", {"X", "Y", "Z"})
    bpy, objects = _targets(names)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    index = "XYZ".index(axis)
    ordered = sorted(((obj, _origin(obj, depsgraph)) for obj in objects), key=lambda item: (item[1][index], item[0].name))
    start, end = ordered[0][1][index], ordered[-1][1][index]
    spacing = (end - start) / (len(ordered) - 1)
    edits = []
    for number, (obj, origin) in enumerate(ordered):
        location = list(origin)
        # Preserve endpoint coordinates exactly, including float rounding.
        if 0 < number < len(ordered) - 1:
            location[index] = start + spacing * number
        edits.append((obj, {"location": tuple(location)}))
    return {"axis": axis, "spacing": spacing, "order": [obj.name for obj, _origin_value in ordered], "endpoints_preserved": True, **_commit(bpy, edits)}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("scene.query", query_scene, toolset="layout", permissions=(Permission.INSPECT_SCENE,), description="Query bounded current-view-layer objects by glob, type, collection, visibility, selection, and evaluated world origin.")
    common = {"toolset": "layout", "permissions": (Permission.TRANSFORM_OBJECTS,), "modifies": True}
    registry.register("object.transform_batch", transform_batch, description="Prevalidate and apply up to 128 explicit independent-object transforms in one logical operation.", **common)
    registry.register("object.align", align_objects, description="Align explicit independent objects by evaluated world origins along one axis.", **common)
    registry.register("object.distribute", distribute_objects, description="Space explicit independent object origins evenly on one world axis while preserving endpoints.", **common)


__all__ = ["register_tools"]
