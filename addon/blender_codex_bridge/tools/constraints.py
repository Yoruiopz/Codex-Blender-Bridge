"""Structured object-constraint inspection and editing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, require_blender
from ._rna import (
    apply_assignments,
    bounded_name,
    prepare_assignments,
    serialize_properties,
    settings_mapping,
)

_MAX_CONSTRAINTS = 100
_COMMON_PROPERTIES = frozenset({"influence", "mute", "owner_space"})
_TARGET_PROPERTIES = frozenset({"target"})
_PROPERTIES: dict[str, frozenset[str]] = {
    "CHILD_OF": frozenset(
        {
            "target",
            "subtarget",
            "use_location_x",
            "use_location_y",
            "use_location_z",
            "use_rotation_x",
            "use_rotation_y",
            "use_rotation_z",
            "use_scale_x",
            "use_scale_y",
            "use_scale_z",
        }
    ),
    "CLAMP_TO": frozenset({"target", "main_axis", "use_cyclic"}),
    "COPY_LOCATION": frozenset(
        {"target", "subtarget", "head_tail", "use_x", "use_y", "use_z", "invert_x", "invert_y", "invert_z", "use_offset", "mix_mode", "target_space"}
    ),
    "COPY_ROTATION": frozenset(
        {"target", "subtarget", "head_tail", "use_x", "use_y", "use_z", "invert_x", "invert_y", "invert_z", "mix_mode", "euler_order", "target_space"}
    ),
    "COPY_SCALE": frozenset(
        {"target", "subtarget", "head_tail", "use_x", "use_y", "use_z", "power", "use_make_uniform", "use_offset", "use_add", "mix_mode", "target_space"}
    ),
    "COPY_TRANSFORMS": frozenset(
        {"target", "subtarget", "head_tail", "mix_mode", "remove_target_shear", "target_space"}
    ),
    "DAMPED_TRACK": frozenset({"target", "subtarget", "head_tail", "track_axis"}),
    "FLOOR": frozenset(
        {"target", "subtarget", "floor_location", "offset", "use_rotation", "use_sticky", "target_space"}
    ),
    "FOLLOW_PATH": frozenset(
        {"target", "offset", "offset_factor", "forward_axis", "up_axis", "use_curve_follow", "use_fixed_location", "use_curve_radius"}
    ),
    "LIMIT_DISTANCE": frozenset({"target", "subtarget", "head_tail", "distance", "limit_mode", "target_space"}),
    "LIMIT_LOCATION": frozenset(
        {"min_x", "min_y", "min_z", "max_x", "max_y", "max_z", "use_min_x", "use_min_y", "use_min_z", "use_max_x", "use_max_y", "use_max_z", "use_transform_limit"}
    ),
    "LIMIT_ROTATION": frozenset(
        {"min_x", "min_y", "min_z", "max_x", "max_y", "max_z", "use_limit_x", "use_limit_y", "use_limit_z", "use_transform_limit", "euler_order"}
    ),
    "LIMIT_SCALE": frozenset(
        {"min_x", "min_y", "min_z", "max_x", "max_y", "max_z", "use_min_x", "use_min_y", "use_min_z", "use_max_x", "use_max_y", "use_max_z", "use_transform_limit"}
    ),
    "LOCKED_TRACK": frozenset({"target", "subtarget", "head_tail", "track_axis", "lock_axis"}),
    "MAINTAIN_VOLUME": frozenset({"mode", "free_axis", "volume"}),
    "SHRINKWRAP": frozenset(
        {"target", "distance", "shrinkwrap_type", "wrap_mode", "project_axis", "project_limit", "use_project_opposite", "cull_face", "track_axis"}
    ),
    "STRETCH_TO": frozenset(
        {"target", "subtarget", "head_tail", "rest_length", "bulge", "volume", "keep_axis", "bulge_min", "bulge_max", "use_bulge_min", "use_bulge_max", "smooth"}
    ),
    "TRACK_TO": frozenset({"target", "subtarget", "head_tail", "track_axis", "up_axis", "use_target_z"}),
    "TRANSFORM": frozenset(
        {
            "target", "subtarget", "map_from", "map_to", "from_rotation_mode", "to_euler_order",
            "from_min_x", "from_min_y", "from_min_z", "from_max_x", "from_max_y", "from_max_z",
            "to_min_x", "to_min_y", "to_min_z", "to_max_x", "to_max_y", "to_max_z",
            "map_to_x_from", "map_to_y_from", "map_to_z_from", "mix_mode", "mix_mode_rot", "mix_mode_scale", "target_space",
        }
    ),
}
_REQUIRES_TARGET = frozenset(
    {
        "CHILD_OF",
        "CLAMP_TO",
        "COPY_LOCATION",
        "COPY_ROTATION",
        "COPY_SCALE",
        "COPY_TRANSFORMS",
        "DAMPED_TRACK",
        "FLOOR",
        "FOLLOW_PATH",
        "LIMIT_DISTANCE",
        "LOCKED_TRACK",
        "SHRINKWRAP",
        "STRETCH_TO",
        "TRACK_TO",
        "TRANSFORM",
    }
)


def _allowed(constraint_type: str) -> frozenset[str]:
    try:
        return _COMMON_PROPERTIES | _PROPERTIES[constraint_type]
    except KeyError as exc:
        raise invalid_argument(
            f"Constraint type '{constraint_type}' is not available through the structured tool.",
            constraint_type=constraint_type,
            supported_types=sorted(_PROPERTIES),
        ) from exc


def _object(params: Mapping[str, Any]) -> Any:
    return get_object(params.get("object_name"), allow_active=False)


def _named_constraint(obj: Any, raw_name: Any) -> Any:
    name = bounded_name(raw_name, "constraint_name")
    constraint = obj.constraints.get(name)
    if constraint is None:
        raise invalid_argument(
            f"Object '{obj.name}' has no constraint named '{name}'.",
            object=obj.name,
            constraint_name=name,
            available_constraints=[item.name for item in list(obj.constraints)[:_MAX_CONSTRAINTS]],
        )
    return constraint


def _summary(constraint: Any) -> dict[str, Any]:
    specific = _PROPERTIES.get(str(constraint.type))
    allowed = _COMMON_PROPERTIES | (specific or frozenset())
    return {
        "name": constraint.name,
        "type": constraint.type,
        "structured_settings_supported": specific is not None,
        "settings": serialize_properties(constraint, allowed),
    }


def _validate_prospective_target(constraint: Any, assignments: Any) -> None:
    target = getattr(constraint, "target", None)
    for assignment in assignments:
        if assignment.name == "target":
            target = assignment.value
    if constraint.type in _REQUIRES_TARGET and target is None:
        raise invalid_argument(
            f"Constraint type '{constraint.type}' requires an explicit target object.",
            constraint_type=constraint.type,
            property="target",
        )


def inspect_constraints(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = _object(params)
    raw_name = params.get("constraint_name")
    if raw_name is not None:
        return {"object": obj.name, "constraint": _summary(_named_constraint(obj, raw_name))}
    total = len(obj.constraints)
    constraints = [_summary(item) for item in list(obj.constraints)[:_MAX_CONSTRAINTS]]
    return {
        "object": obj.name,
        "constraint_count": total,
        "constraints": constraints,
        "truncated": total > len(constraints),
        "maximum_returned": _MAX_CONSTRAINTS,
    }


def add_constraint(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _object(params)
    constraint_type = bounded_name(params.get("constraint_type"), "constraint_type", maximum=64).upper()
    allowed = _allowed(constraint_type)
    requested_name = params.get("constraint_name")
    name = bounded_name(requested_name, "constraint_name") if requested_name is not None else None
    settings = settings_mapping(params, required=constraint_type in _REQUIRES_TARGET)
    if len(obj.constraints) >= _MAX_CONSTRAINTS:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            f"Object '{obj.name}' has reached the structured constraint limit.",
            {"maximum_constraints": _MAX_CONSTRAINTS},
        )
    try:
        constraint = obj.constraints.new(type=constraint_type)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            f"Blender could not create a {constraint_type} object constraint.",
            {"object": obj.name, "constraint_type": constraint_type},
        ) from exc
    try:
        if name is not None:
            constraint.name = name
        assignments = prepare_assignments(
            constraint,
            settings,
            allowed=allowed,
            object_pointers=_TARGET_PROPERTIES,
            bpy=bpy,
        )
        _validate_prospective_target(constraint, assignments)
        apply_assignments(constraint, assignments)
    except Exception:
        obj.constraints.remove(constraint)
        raise
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "created": _summary(constraint),
        "constraint_count_after": len(obj.constraints),
    }


def set_constraint(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _object(params)
    constraint = _named_constraint(obj, params.get("constraint_name"))
    assignments = prepare_assignments(
        constraint,
        settings_mapping(params),
        allowed=_allowed(str(constraint.type)),
        object_pointers=_TARGET_PROPERTIES,
        bpy=bpy,
    )
    _validate_prospective_target(constraint, assignments)
    apply_assignments(constraint, assignments)
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "constraint": _summary(constraint),
        "updated_properties": [item.name for item in assignments],
    }


def remove_constraint(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = _object(params)
    constraint = _named_constraint(obj, params.get("constraint_name"))
    removed = {"name": constraint.name, "type": constraint.type}
    try:
        obj.constraints.remove(constraint)
    except (ReferenceError, RuntimeError) as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not remove the requested object constraint.",
            {"object": obj.name, "constraint": removed["name"]},
        ) from exc
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "removed": removed,
        "constraint_count_after": len(obj.constraints),
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "constraint.inspect",
        inspect_constraints,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="constraints",
        description="Inspect bounded object constraints and allowlisted settings.",
    )
    modifying = {
        "permissions": (Permission.TRANSFORM_OBJECTS,),
        "toolset": "constraints",
        "modifies": True,
    }
    registry.register("constraint.add", add_constraint, description="Add an allowlisted object constraint with an explicit target where required.", **modifying)
    registry.register("constraint.set", set_constraint, description="Set direct allowlisted RNA properties on one object constraint.", **modifying)
    registry.register("constraint.remove", remove_constraint, description="Remove one explicitly named object constraint.", **modifying)


__all__ = [
    "add_constraint",
    "inspect_constraints",
    "register_tools",
    "remove_constraint",
    "set_constraint",
]
