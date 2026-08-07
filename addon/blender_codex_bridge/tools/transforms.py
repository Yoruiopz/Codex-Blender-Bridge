"""Structured object transform operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import (
    bool_param,
    float_param,
    get_object,
    preserved_object_context,
    require_blender,
    serialize_transform,
    vector3,
)


def _rotation_value(params: Mapping[str, Any]) -> tuple[float, float, float]:
    for name in ("rotation", "delta", "euler"):
        if name in params:
            return vector3(params[name], name)
    raise invalid_argument("A three-component 'rotation' value is required (radians).")


def set_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    if not any(name in params for name in ("location", "rotation", "rotation_euler", "scale")):
        raise invalid_argument("At least one transform component is required.")
    parsed_location = vector3(params["location"], "location") if "location" in params else None
    rotation_value = params.get("rotation", params.get("rotation_euler"))
    parsed_rotation = vector3(rotation_value, "rotation") if rotation_value is not None else None
    parsed_scale = vector3(params["scale"], "scale") if "scale" in params else None
    rotation_mode = params.get("rotation_mode")
    euler_modes = {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}
    if rotation_mode is not None:
        if not isinstance(rotation_mode, str):
            raise invalid_argument("'rotation_mode' must be a string.")
        rotation_mode = rotation_mode.upper()
        if rotation_mode not in {*euler_modes, "QUATERNION", "AXIS_ANGLE"}:
            raise invalid_argument("Unsupported rotation mode.", rotation_mode=rotation_mode)
    if parsed_rotation is not None and rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
        raise invalid_argument("Three-component rotation values require an Euler rotation mode.")
    effective_rotation_mode = rotation_mode
    if parsed_rotation is not None and effective_rotation_mode is None and obj.rotation_mode not in euler_modes:
        effective_rotation_mode = "XYZ"

    # Commit only after every argument has been validated.
    if effective_rotation_mode is not None:
        obj.rotation_mode = effective_rotation_mode
    if parsed_location is not None:
        obj.location = parsed_location
    if parsed_rotation is not None:
        obj.rotation_euler = parsed_rotation
    if parsed_scale is not None:
        obj.scale = parsed_scale
    return {"changed": True, **serialize_transform(obj)}


def translate(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    raw = params.get(
        "offset",
        params.get("translation", params.get("delta", params.get("vector"))),
    )
    delta = vector3(raw, "translation")
    space = str(params.get("space", "WORLD")).upper()
    if space not in {"WORLD", "LOCAL"}:
        raise invalid_argument("'space' must be WORLD or LOCAL.")
    mathutils = __import__("mathutils")
    direction = mathutils.Vector(delta)
    if space == "LOCAL":
        direction = obj.matrix_world.to_quaternion() @ direction
    matrix = obj.matrix_world.copy()
    matrix.translation = matrix.translation + direction
    obj.matrix_world = matrix
    bpy.context.view_layer.update()
    return {"changed": True, "translation": list(delta), "space": space, **serialize_transform(obj)}


def rotate(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    rotation = _rotation_value(params)
    space = str(params.get("space", "LOCAL")).upper()
    if space not in {"WORLD", "LOCAL"}:
        raise invalid_argument("'space' must be WORLD or LOCAL.")
    mathutils = __import__("mathutils")
    delta_quaternion = mathutils.Euler(rotation, "XYZ").to_quaternion()
    if space == "WORLD":
        location, current_rotation, scale = obj.matrix_world.decompose()
        obj.matrix_world = mathutils.Matrix.LocRotScale(
            location,
            delta_quaternion @ current_rotation,
            scale,
        )
    else:
        location, current_rotation, scale = obj.matrix_basis.decompose()
        obj.matrix_basis = mathutils.Matrix.LocRotScale(
            location,
            current_rotation @ delta_quaternion,
            scale,
        )
    return {"changed": True, "rotation_delta": list(rotation), "space": space, **serialize_transform(obj)}


def scale(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    raw = params.get("factors", params.get("factor", params.get("scale")))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        factors = (float_param({"factor": raw}, "factor", 1.0),) * 3
    else:
        factors = vector3(raw, "factors")
    space = str(params.get("space", "LOCAL")).upper()
    if space not in {"WORLD", "LOCAL"}:
        raise invalid_argument("'space' must be WORLD or LOCAL.")
    if space == "WORLD":
        mathutils = __import__("mathutils")
        location, rotation, current_scale = obj.matrix_world.decompose()
        obj.matrix_world = mathutils.Matrix.LocRotScale(
            location,
            rotation,
            tuple(float(current_scale[index]) * factors[index] for index in range(3)),
        )
    else:
        obj.scale = tuple(float(obj.scale[index]) * factors[index] for index in range(3))
    return {
        "changed": True,
        "scale_factors": list(factors),
        "space": space,
        **serialize_transform(obj),
    }


def apply_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    location = bool_param(params, "location", False)
    rotation = bool_param(params, "rotation", False)
    scale_value = bool_param(params, "scale", True)
    if not (location or rotation or scale_value):
        raise invalid_argument("At least one of location, rotation, or scale must be true.")
    with preserved_object_context():
        active = bpy.context.view_layer.objects.active
        if active is not None and active.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            result = bpy.ops.object.transform_apply(
                location=location,
                rotation=rotation,
                scale=scale_value,
                properties=False,
            )
        except RuntimeError as exc:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Blender could not apply the transform in the current context.",
                {"detail": str(exc)},
            ) from exc
        if "FINISHED" not in result:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Transform application did not finish.")
        resulting = serialize_transform(obj)
    return {
        "changed": True,
        "applied": {"location": location, "rotation": rotation, "scale": scale_value},
        **resulting,
    }


def register_tools(registry: ToolRegistry) -> None:
    common = {
        "permissions": (Permission.TRANSFORM_OBJECTS,),
        "toolset": "objects",
        "modifies": True,
    }
    registry.register("transform.set", set_transform, description="Set exact transform components.", **common)
    registry.register("transform.translate", translate, description="Translate an object in world or local space.", **common)
    registry.register("transform.rotate", rotate, description="Rotate an object by Euler-radian deltas.", **common)
    registry.register("transform.scale", scale, description="Multiply an object's scale by deterministic factors.", **common)
    registry.register("transform.apply", apply_transform, description="Apply selected object transform channels.", **common)
