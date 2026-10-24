"""Structured object transform operations."""

from __future__ import annotations

import math
import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ..artist_target_intent import (
    CORE_FIELDS,
    TargetIntent,
    capture_intent,
    compare_target,
    read_target,
)
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry, _checkpoint_parameters
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

QUATERNION_BITS = "__quaternion_core_float32_bits__"
MIN_NORMAL_FLOAT32 = float.fromhex("0x1p-126")
QUATERNION_NORM_TOLERANCE = 1e-6


def quaternion_request(params: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """Validate a raw WXYZ request without normalization or native access."""
    if any(name in params for name in ("rotation", "rotation_euler", "rotation_mode")):
        raise invalid_argument("rotation_quaternion cannot accompany rotation, rotation_euler or rotation_mode.")
    raw = params.get("rotation_quaternion")
    if type(raw) not in (list, tuple) or len(raw) != 4 or any(type(value) not in (int, float) for value in raw):
        raise invalid_argument("rotation_quaternion requires exactly four finite WXYZ numbers; booleans are not numbers.")
    requested = []
    rounded = []
    for value in raw:
        try:
            value = float(value)
        except (OverflowError, ValueError) as error:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Quaternion components exceed the qualified Float32 storage profile.") from error
        if not math.isfinite(value):
            raise invalid_argument("rotation_quaternion components must be finite.")
        if abs(value) > 1. or (value != 0. and abs(value) < MIN_NORMAL_FLOAT32):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Quaternion components require normal Float32 storage or signed zero, with magnitude at most one.")
        converted = struct.unpack("<f", struct.pack("<f", value))[0]
        if converted != 0. and abs(converted) < MIN_NORMAL_FLOAT32:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Quaternion rounding falls outside the qualified normal Float32 profile.")
        requested.append(value)
        rounded.append(converted)
    if any(abs(math.sqrt(sum(value * value for value in values)) - 1.) > QUATERNION_NORM_TOLERANCE
           for values in (requested, rounded)):
        raise invalid_argument("rotation_quaternion must be unit length within 1e-6 before and after Float32 rounding; it is never normalized.")
    return tuple(requested)


def quaternion_profile(bpy: Any, obj: Any) -> None:
    """The new field's narrow native scope, before any checkpoint or write."""
    from . import artist_loop
    from ._artist_scope_profile import _rna
    from ._object_rna_mutation import _closure
    from ._object_safety import require_single_user_object_data

    def refuse() -> None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "Absolute quaternion authoring requires one local editable static unlocked single-user Mesh in existing QUATERNION mode.")

    if type(obj) is not getattr(getattr(bpy, "types", None), "Object", None):
        refuse()
    artist_loop.pre_closure(bpy)
    _rna(obj, reads=frozenset({"type", "mode", "data", "rotation_mode", "users_scene", "parent", "children",
        "modifiers", "constraints", "animation_data", "lock_rotation", "lock_rotation_w", "lock_rotations_4d",
        "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale"}))
    artist_loop.require_profile(bpy, (obj,))
    if obj.type != "MESH" or obj.rotation_mode != "QUATERNION" or obj.mode != "OBJECT" or bpy.context.mode != "OBJECT":
        refuse()
    data = obj.data
    if type(data) is not getattr(bpy.types, "Mesh", None) or data.bl_rna.as_pointer() != bpy.types.Mesh.bl_rna.as_pointer():
        refuse()
    _rna(data, reads=frozenset({"users", "animation_data", "shape_keys", "library", "override_library", "is_editable"}))
    require_single_user_object_data(obj, operation="Absolute quaternion authoring")
    if (len(obj.users_scene) != 1 or obj.users_scene[0] != bpy.context.scene or obj.parent is not None or len(obj.children)
            or len(obj.modifiers) or len(obj.constraints) or obj.animation_data is not None or data.animation_data is not None
            or data.shape_keys is not None or any(obj.lock_rotation) or obj.lock_rotation_w or obj.lock_rotations_4d):
        refuse()
    defaults = {"delta_location": (0., 0., 0.), "delta_rotation_euler": (0., 0., 0.),
                "delta_rotation_quaternion": (1., 0., 0., 0.), "delta_scale": (1., 1., 1.)}
    if any(tuple(getattr(obj, name)) != expected for name, expected in defaults.items()):
        refuse()
    objects, references = _closure(bpy, obj)
    if (len(objects) != 1 or objects[0] != obj
            or any(record[3][0] not in {"COLLECTION", "MEMBERSHIP", "SCENE_REFERENCES"} for record in references)):
        refuse()
    # Observation descriptors may be readonly. Mutation requires the canonical
    # writable core descriptors in addition to the independent intent profile.
    properties = bpy.types.Object.bl_rna.properties
    if any(properties.get(name) is None or properties.get(name).is_readonly for name in CORE_FIELDS):
        refuse()


def _core_bits(values: Any) -> tuple[Any, ...]:
    channels = dict(values)
    return tuple((field, channels[field] if field == "rotation_mode" else
                  tuple(struct.pack("<f", value).hex() for value in channels[field])) for field in CORE_FIELDS)


@dataclass(frozen=True, slots=True)
class QuaternionPreviewOrigin:
    parameters: Any
    intent: TargetIntent


def check_quaternion_preview(preview: Mapping[str, Any]) -> QuaternionPreviewOrigin | None:
    """Pure creation-time parameter/intent proof, including unlinked previews."""
    params = preview["params"]
    origin = preview.get("quaternion_origin")
    if "rotation_quaternion" not in params:
        if origin is not None:
            raise invalid_argument("The quaternion preview's original request was removed; preview again.")
        return None
    if (type(origin) is not QuaternionPreviewOrigin or type(origin.intent) is not TargetIntent
            or origin.intent.availability != "available" or preview.get("target_intent") is not origin.intent
            or _checkpoint_parameters(params) != origin.parameters):
        raise invalid_argument("The quaternion preview's original parameters or independent intent changed; preview again.")
    return origin


class QuaternionBoundary(Boundary):
    """Reuse existing lifecycle/CAS, with exact core bits for this field only."""

    def __init__(self, bpy: Any, context: Any, method: str, obj: Any, intent: TargetIntent, *, checkpoint_roles: Any = None):
        if type(intent) is not TargetIntent or intent.availability != "available":
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Quaternion authoring requires a complete independent six-channel intent.")
        self.quaternion_intent = intent
        super().__init__(bpy, context, method, obj, transform=True, artist_profile=True, checkpoint_roles=checkpoint_roles)
        if dict(self.original)[QUATERNION_BITS] != intent.before_bits:
            raise invalid_argument("Quaternion source channels changed before the retained boundary was captured.")

    def _owned(self) -> Any:
        values = super()._owned()
        return (*values, (QUATERNION_BITS, _core_bits(values)))

    def _predict(self, owner: Any, name: str, requested: Any) -> Any:
        predicted = super()._predict(owner, name, requested)
        bits = _core_bits(predicted)
        return tuple((field, bits if field == QUATERNION_BITS else value) for field, value in predicted)

    def restore_transform(self) -> None:
        original = dict(self.original)
        wanted = dict(original[QUATERNION_BITS])
        for field in ("rotation_mode", "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale"):
            if dict(_core_bits(self._owned()))[field] != wanted[field]:
                self.write(self.obj, field, original[field])
        self.check()


def quaternion_boundary(bpy: Any, context: Any, method: str, obj: Any, params: Mapping[str, Any], *,
                        intent: TargetIntent | None = None, checkpoint_roles: Any = None) -> QuaternionBoundary:
    quaternion_request(params)
    quaternion_profile(bpy, obj)
    if intent is None:
        intent = capture_intent(bpy, obj, dict(params))
    if type(intent) is not TargetIntent or intent.availability != "available":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Quaternion authoring requires a qualified independent six-channel Float32 intent.",
                          {"reason": getattr(intent, "reason", "intent_unavailable")})
    return QuaternionBoundary(bpy, context, method, obj, intent, checkpoint_roles=checkpoint_roles)


def _verify_quaternion_result(boundary: QuaternionBoundary, *, before: bool = False) -> None:
    intent = boundary.quaternion_intent
    if before:
        intent = replace(intent, expected_channels=intent.before_channels, expected_bits=intent.before_bits)
    result = compare_target(intent, read_target(boundary.bpy, intent))
    if result["status"] != "channels_match":
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Quaternion authoring did not match its independently frozen six-channel bits.")
    boundary.check_after_read()


def _rotation_value(params: Mapping[str, Any]) -> tuple[float, float, float]:
    for name in ("rotation", "delta", "euler"):
        if name in params:
            return vector3(params[name], name)
    raise invalid_argument("A three-component 'rotation' value is required (radians).")


def set_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    parsed_quaternion = quaternion_request(params) if "rotation_quaternion" in params else None
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    require_local_object(obj, operation="Object transform editing")
    if not any(name in params for name in ("location", "rotation", "rotation_euler", "rotation_quaternion", "scale")):
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

    reject_unknown_params(params, {"object_name", "location", "rotation", "rotation_euler", "rotation_quaternion", "scale", "rotation_mode"})
    values = [("rotation_mode", effective_rotation_mode), ("location", parsed_location), ("rotation_euler", parsed_rotation),
              ("rotation_quaternion", parsed_quaternion), ("scale", parsed_scale)]
    return _commit(bpy, context, "transform.set", obj, tuple(RNAAssignment(name, value) for name, value in values if value is not None))


def _commit(bpy: Any, context: ToolContext, method: str, obj: Any, assignments: tuple[RNAAssignment, ...]) -> dict[str, Any]:
    from ._artist_checkpoint_admission import cached
    retained = cached(context, method, obj)
    quaternion = method == "transform.set" and any(assignment.name == "rotation_quaternion" for assignment in assignments)
    if quaternion and type(retained) is not QuaternionBoundary:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Quaternion authoring requires its original registered pre-checkpoint admission.")
    boundary = retained or Boundary(bpy, context, method, obj, transform=True)
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
        result = {"changed": True, "affected_objects": boundary.affected, "verified": True, **serialize_transform(obj)}
        if quaternion:
            _verify_quaternion_result(boundary)
        return result
    except Exception as error:
        if isinstance(error, BridgeError) and "rollback_verified" in error.context:
            if quaternion and error.context["rollback_verified"] is True:
                try:
                    _verify_quaternion_result(boundary, before=True)
                except Exception:
                    raise boundary.failure(error, restored=False) from error
            raise
        restored = False
        try:
            boundary.restore_transform()
            boundary.check()
            bpy.context.view_layer.update()
            boundary.check()
            candidate = boundary.expected == boundary.original
            if candidate and quaternion:
                _verify_quaternion_result(boundary, before=True)
            restored = candidate
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
