"""Structured object transform operations."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import (
    bool_param,
    float_param,
    get_object,
    reject_unknown_params,
    require_blender,
    serialize_transform,
    vector3,
)
from ._object_rna_mutation import Boundary, _close
from ._object_safety import require_local_object, require_unkeyed_object_data
from ._rna import RNAAssignment, apply_assignments


def _rotation_value(params: Mapping[str, Any]) -> tuple[float, float, float]:
    for name in ("rotation", "delta", "euler"):
        if name in params:
            return vector3(params[name], name)
    raise invalid_argument("A three-component 'rotation' value is required (radians).")


def set_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    require_local_object(obj, operation="Object transform editing")
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

    reject_unknown_params(params, {"object_name", "location", "rotation", "rotation_euler", "scale", "rotation_mode"})
    values = [("rotation_mode", effective_rotation_mode), ("location", parsed_location), ("rotation_euler", parsed_rotation), ("scale", parsed_scale)]
    return _commit(bpy, context, "transform.set", obj, tuple(RNAAssignment(name, value) for name, value in values if value is not None))


def _commit(bpy: Any, context: ToolContext, method: str, obj: Any, assignments: tuple[RNAAssignment, ...]) -> dict[str, Any]:
    from ._artist_checkpoint_admission import cached
    boundary = cached(context, method, obj) or Boundary(bpy, context, method, obj, transform=True)
    for assignment in assignments:
        field = assignment.name
        locks = getattr(obj, "lock_rotation" if field.startswith("rotation_") else f"lock_{field}", ())
        if field in {"location", "rotation_euler", "scale"} and any(locked and float(new) != float(old) for locked, new, old in zip(locks, assignment.value, getattr(obj, field), strict=False)):
            raise invalid_argument("Transform edits do not bypass locked components.", property=field)
    try:
        apply_assignments(obj, assignments, boundary=boundary)
        # Updating may evaluate consumers. The following gate still compares
        # persistent channels, rigs, Actions and object-owned configuration.
        boundary.check()
        bpy.context.view_layer.update()
        boundary.check()
        return {"changed": True, "affected_objects": boundary.affected, "verified": True, **serialize_transform(obj)}
    except Exception as error:
        if isinstance(error, BridgeError) and "rollback_verified" in error.context:
            raise
        restored = False
        try:
            boundary.restore_transform()
            boundary.check()
            bpy.context.view_layer.update()
            boundary.check()
            restored = boundary.expected == boundary.original
        except Exception:
            pass
        raise boundary.failure(error, restored=restored) from error


def _matrix_changes(obj: Any, matrix: Any, *, world: bool) -> tuple[RNAAssignment, ...]:
    import mathutils
    defaults = {"delta_location": (0., 0., 0.), "delta_rotation_euler": (0., 0., 0.),
                "delta_rotation_quaternion": (1., 0., 0., 0.), "delta_scale": (1., 1., 1.)}
    if any(not _close(tuple(getattr(obj, field)), value) for field, value in defaults.items()):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Matrix transform deltas require identity delta channels for exact channel prediction.")
    if world and obj.parent is not None:
        if obj.parent_type != "OBJECT":
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "World transform deltas do not yet predict bone or vertex parenting.")
        parent = obj.parent.matrix_world @ obj.matrix_parent_inverse
        if abs(parent.determinant()) < 1e-12:
            raise invalid_argument("Parent transform is singular; exact world-to-local conversion is unavailable.")
        matrix = parent.inverted() @ matrix
    location, rotation, scale_value = matrix.decompose()
    if not _close(tuple(tuple(row) for row in mathutils.Matrix.LocRotScale(location, rotation, scale_value)), tuple(tuple(row) for row in matrix)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Requested matrix contains shear which cannot be represented by exact object channels.")
    if obj.rotation_mode == "QUATERNION":
        channel, value = "rotation_quaternion", tuple(rotation)
    elif obj.rotation_mode == "AXIS_ANGLE":
        axis, angle = rotation.to_axis_angle()
        channel, value = "rotation_axis_angle", (angle, *axis)
    else:
        channel, value = "rotation_euler", tuple(rotation.to_euler(obj.rotation_mode, obj.rotation_euler))
    return (RNAAssignment("location", tuple(location)), RNAAssignment(channel, value), RNAAssignment("scale", tuple(scale_value)))


def translate(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    require_local_object(obj, operation="Object transform editing")
    reject_unknown_params(params, {"object_name", "offset", "translation", "delta", "vector", "space"})
    delta = vector3(params.get("offset", params.get("translation", params.get("delta", params.get("vector")))), "translation")
    space = str(params.get("space", "WORLD")).upper()
    if space not in {"WORLD", "LOCAL"}:
        raise invalid_argument("'space' must be WORLD or LOCAL.")
    import mathutils
    direction = mathutils.Vector(delta)
    if space == "LOCAL":
        direction = obj.matrix_world.to_quaternion() @ direction
    matrix = obj.matrix_world.copy()
    matrix.translation += direction
    return {"translation": list(delta), "space": space, **_commit(bpy, context, "transform.translate", obj, _matrix_changes(obj, matrix, world=True))}


def rotate(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    require_local_object(obj, operation="Object transform editing")
    reject_unknown_params(params, {"object_name", "rotation", "delta", "euler", "space"})
    rotation = _rotation_value(params)
    space = str(params.get("space", "LOCAL")).upper()
    if space not in {"WORLD", "LOCAL"}:
        raise invalid_argument("'space' must be WORLD or LOCAL.")
    import mathutils
    delta = mathutils.Euler(rotation, "XYZ").to_quaternion()
    location, current, scale_value = (obj.matrix_world if space == "WORLD" else obj.matrix_basis).decompose()
    matrix = mathutils.Matrix.LocRotScale(location, delta @ current if space == "WORLD" else current @ delta, scale_value)
    return {"rotation_delta": list(rotation), "space": space,
            **_commit(bpy, context, "transform.rotate", obj, _matrix_changes(obj, matrix, world=space == "WORLD"))}


def scale(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    require_local_object(obj, operation="Object transform editing")
    reject_unknown_params(params, {"object_name", "factor", "factors", "scale", "space"})
    raw = params.get("factors", params.get("factor", params.get("scale")))
    factors = (float_param({"factor": raw}, "factor", 1.0),)*3 if isinstance(raw, (int, float)) and not isinstance(raw, bool) else vector3(raw, "factors")
    space = str(params.get("space", "LOCAL")).upper()
    if space not in {"WORLD", "LOCAL"}:
        raise invalid_argument("'space' must be WORLD or LOCAL.")
    if space == "WORLD":
        import mathutils
        location, rotation, current = obj.matrix_world.decompose()
        matrix = mathutils.Matrix.LocRotScale(location, rotation, tuple(float(current[index])*factors[index] for index in range(3)))
        assignments = _matrix_changes(obj, matrix, world=True)
    else:
        assignments = (RNAAssignment("scale", tuple(float(obj.scale[index])*factors[index] for index in range(3))),)
    return {"scale_factors": list(factors), "space": space, **_commit(bpy, context, "transform.scale", obj, assignments)}


def apply_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    require_unkeyed_object_data(obj, operation="Transform application")
    reject_unknown_params(params, {"object_name", "location", "rotation", "scale"})
    location, rotation, scale_value = bool_param(params, "location", False), bool_param(params, "rotation", False), bool_param(params, "scale", True)
    if not (location or rotation or scale_value):
        raise invalid_argument("At least one of location, rotation, or scale must be true.")
    if obj.animation_data is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Applying transforms to animated objects requires a separately qualified animation-retargeting contract.")
    boundary = Boundary(bpy, context, "transform.apply", obj, transform=True)
    fields = set()
    if location:
        fields.add("location")
    if rotation:
        fields.update({"rotation_euler", "rotation_quaternion", "rotation_axis_angle"})
    if scale_value:
        fields.add("scale")
    def operation():
        boundary.check()
        with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
            if not bpy.ops.object.transform_apply.poll():
                raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Transform apply is unavailable in the current context.")
        # Poll may run after the last live grant check. Revalidate authority
        # and persistent state outside the selection override, then enter the
        # same native context with only the pure final gate before the write.
        boundary.check()
        with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
            boundary.final()
            started = time.monotonic()
            try:
                return bpy.ops.object.transform_apply(location=location, rotation=rotation, scale=scale_value, properties=False)
            finally:
                boundary.native_seconds = time.monotonic()-started
    boundary.native_apply(operation, applied_channels=frozenset(fields))
    return {"changed": True, "affected_objects": boundary.affected, "applied": {"location": location, "rotation": rotation, "scale": scale_value},
            "verified": True, "native_call_interruptible": False, "native_blocking_seconds": boundary.native_seconds, "mesh_rollback_available": False, **serialize_transform(obj)}


def register_tools(registry: ToolRegistry) -> None:
    from ._artist_checkpoint_admission import factory
    from .artist_loop import prepare_transform_scope
    common = {
        "permissions": (Permission.TRANSFORM_OBJECTS,),
        "toolset": "objects",
        "modifies": True,
        "checkpoint_admission_factory": None,
        "checkpoint_batch_reviewed": True,
    }
    for method, handler, description in (
        ("transform.set", set_transform, "Set exact transform components."),
        ("transform.translate", translate, "Translate an object in world or local space."),
        ("transform.rotate", rotate, "Rotate an object by Euler-radian deltas."),
        ("transform.scale", scale, "Multiply an object's scale by deterministic factors."),
    ):
        registry.register(method, handler, description=description, protected_scope_resolver=prepare_transform_scope,
                          **{**common, "checkpoint_admission_factory": lambda context, params, method=method: factory(method, context, params)})
    registry.register("transform.apply", apply_transform, description="Apply selected object transform channels.",
                      permissions=(Permission.TRANSFORM_OBJECTS, Permission.EDIT_MESH), toolset="objects", modifies=True)
