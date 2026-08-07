"""Structured armature, pose, constraint, and mesh-binding operations."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import (
    bool_param,
    float_param,
    get_collection,
    get_object,
    int_param,
    preserved_object_context,
    require_blender,
    vector3,
)

_MAX_COORDINATE = 1_000_000.0
_MAX_BONES = 2_048
_MAX_CONSTRAINTS = 2_048
_CONSTRAINT_TYPES = {
    "CHILD_OF",
    "COPY_LOCATION",
    "COPY_ROTATION",
    "COPY_SCALE",
    "DAMPED_TRACK",
    "IK",
    "LIMIT_LOCATION",
    "LIMIT_ROTATION",
    "LIMIT_SCALE",
    "TRACK_TO",
}
_TARGET_CONSTRAINT_TYPES = {
    "CHILD_OF",
    "COPY_LOCATION",
    "COPY_ROTATION",
    "COPY_SCALE",
    "DAMPED_TRACK",
    "IK",
    "TRACK_TO",
}
_ROTATION_MODES = {
    "QUATERNION",
    "XYZ",
    "XZY",
    "YXZ",
    "YZX",
    "ZXY",
    "ZYX",
    "AXIS_ANGLE",
}


def _required_name(
    params: Mapping[str, Any],
    key: str,
    *,
    maximum: int = 256,
) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument(f"'{key}' must be a non-empty string.", parameter=key)
    value = value.strip()
    if len(value) > maximum or any(ord(character) < 32 for character in value):
        raise invalid_argument(
            f"'{key}' must contain at most {maximum} printable characters.",
            parameter=key,
        )
    return value


def _optional_name(params: Mapping[str, Any], key: str, *, maximum: int = 256) -> str | None:
    if params.get(key) is None:
        return None
    return _required_name(params, key, maximum=maximum)


def _bounded_vector3(value: Any, name: str, *, default: Sequence[float] | None = None) -> tuple[float, float, float]:
    result = vector3(value, name, default=default)
    if any(abs(component) > _MAX_COORDINATE for component in result):
        raise invalid_argument(
            f"'{name}' components must be between {-_MAX_COORDINATE:g} and {_MAX_COORDINATE:g}.",
            parameter=name,
        )
    return result


def _bounded_sequence(value: Any, name: str, length: int) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != length:
        raise invalid_argument(f"'{name}' must contain exactly {length} numbers.", parameter=name)
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise invalid_argument(f"'{name}' must contain exactly {length} numbers.", parameter=name)
    try:
        result = tuple(float(item) for item in value)
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(f"'{name}' must contain finite numbers.", parameter=name) from exc
    if not all(math.isfinite(item) and abs(item) <= _MAX_COORDINATE for item in result):
        raise invalid_argument(f"'{name}' values must be finite and bounded.", parameter=name)
    return result


def _armature_object(params: Mapping[str, Any]) -> Any:
    obj = get_object(params.get("object_name"), allow_active=False)
    if obj.type != "ARMATURE":
        raise invalid_argument(
            "The named object must be an armature.",
            object=obj.name,
            object_type=obj.type,
        )
    return obj


def _bone_or_error(armature: Any, bone_name: str, *, edit: bool = False) -> Any:
    collection = armature.data.edit_bones if edit else armature.data.bones
    bone = collection.get(bone_name)
    if bone is None:
        candidates = [item.name for item in islice(collection, 128)]
        raise invalid_argument(
            f"Bone '{bone_name}' does not exist on armature '{armature.name}'.",
            object=armature.name,
            bone_name=bone_name,
            available_bones=candidates,
            available_bones_truncated=len(collection) > len(candidates),
        )
    return bone


def _ensure_object_mode() -> None:
    bpy = require_blender()
    active = bpy.context.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        try:
            result = bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError as exc:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Blender could not leave the active object's current mode.",
                {"active_object": active.name, "current_mode": active.mode},
            ) from exc
        if "FINISHED" not in result:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Blender could not enter Object Mode.")


def _select_only(*objects: Any, active: Any) -> None:
    bpy = require_blender()
    view_layer = bpy.context.view_layer
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    for obj in objects:
        if view_layer.objects.get(obj.name) is None:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                f"Object '{obj.name}' is not in the active view layer.",
            )
        if obj.hide_get() or obj.hide_viewport:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                f"Object '{obj.name}' must be visible for this contextual operation.",
            )
        obj.select_set(True)
    view_layer.objects.active = active


@contextmanager
def _edit_armature(armature: Any) -> Iterator[Any]:
    bpy = require_blender()
    with preserved_object_context():
        _ensure_object_mode()
        _select_only(armature, active=armature)
        try:
            result = bpy.ops.object.mode_set(mode="EDIT")
        except RuntimeError as exc:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Blender could not enter Armature Edit Mode.",
                {"object": armature.name},
            ) from exc
        if "FINISHED" not in result:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Blender could not enter Armature Edit Mode.")
        try:
            yield armature.data.edit_bones
        finally:
            if armature.mode == "EDIT":
                with suppress(RuntimeError):
                    bpy.ops.object.mode_set(mode="OBJECT")


def _bone_state(bone: Any) -> dict[str, Any]:
    child_count = len(bone.children)
    children = list(islice(bone.children, 64))
    return {
        "name": bone.name,
        "parent": bone.parent.name if bone.parent else None,
        "children": [child.name for child in children],
        "children_truncated": child_count > 64,
        "head_local": [float(value) for value in bone.head_local],
        "tail_local": [float(value) for value in bone.tail_local],
        "matrix_local": [
            [float(value) for value in row] for row in bone.matrix_local
        ],
        "length": float(bone.length),
        "use_connect": bool(bone.use_connect),
        "use_deform": bool(bone.use_deform),
        "inherit_scale": str(getattr(bone, "inherit_scale", "FULL")),
    }


def _constraint_state(constraint: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": constraint.name,
        "type": constraint.type,
        "influence": float(constraint.influence),
        "mute": bool(constraint.mute),
    }
    target = getattr(constraint, "target", None)
    if target is not None:
        result["target"] = target.name
    subtarget = getattr(constraint, "subtarget", "")
    if subtarget:
        result["subtarget"] = str(subtarget)
    for attribute in ("chain_count", "track_axis", "up_axis", "owner_space", "target_space"):
        if hasattr(constraint, attribute):
            value = getattr(constraint, attribute)
            result[attribute] = int(value) if isinstance(value, int) else str(value)
    return result


def _pose_bone_state(pose_bone: Any, *, max_constraints: int = 64) -> dict[str, Any]:
    constraint_count = len(pose_bone.constraints)
    constraints = list(islice(pose_bone.constraints, max_constraints))
    return {
        "name": pose_bone.name,
        "location": [float(value) for value in pose_bone.location],
        "rotation_mode": pose_bone.rotation_mode,
        "rotation_euler": [float(value) for value in pose_bone.rotation_euler],
        "rotation_quaternion": [float(value) for value in pose_bone.rotation_quaternion],
        "scale": [float(value) for value in pose_bone.scale],
        "constraint_count": constraint_count,
        "constraints": [_constraint_state(item) for item in constraints],
        "constraints_truncated": constraint_count > max_constraints,
    }


def inspect_rig(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    armature = _armature_object(params)
    max_bones = int_param(params, "max_bones", 256, minimum=1, maximum=_MAX_BONES)
    max_constraints = int_param(
        params,
        "max_constraints",
        512,
        minimum=1,
        maximum=_MAX_CONSTRAINTS,
    )
    bone_count = len(armature.data.bones)
    bones = list(islice(armature.data.bones, max_bones))
    serialized_bones: list[dict[str, Any]] = []
    pose_bones: list[dict[str, Any]] = []
    constraints_used = 0
    constraints_truncated = False
    for bone in bones:
        serialized_bones.append(_bone_state(bone))
        pose_bone = armature.pose.bones.get(bone.name)
        if pose_bone is None:
            continue
        remaining = max(0, max_constraints - constraints_used)
        pose_state = _pose_bone_state(pose_bone, max_constraints=remaining)
        included = len(pose_state["constraints"])
        constraints_used += included
        constraints_truncated = constraints_truncated or bool(pose_state["constraints_truncated"])
        pose_bones.append(pose_state)
    return {
        "object": armature.name,
        "data": armature.data.name,
        "mode": armature.mode,
        "display_type": armature.data.display_type,
        "bone_count": bone_count,
        "bones": serialized_bones,
        "pose_bones": pose_bones,
        "truncated": {
            "bones": len(serialized_bones) < bone_count,
            "constraints": constraints_truncated,
        },
    }


def create_rig(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    name = _required_name(params, "name", maximum=63)
    if bpy.data.objects.get(name) is not None:
        raise invalid_argument(f"An object named '{name}' already exists.")
    data_name = _optional_name(params, "data_name", maximum=63) or f"{name}Armature"
    if bpy.data.armatures.get(data_name) is not None:
        raise invalid_argument(f"An armature data block named '{data_name}' already exists.")
    collection_name = _optional_name(params, "collection")
    collection = get_collection(collection_name)
    location = _bounded_vector3(params.get("location"), "location", default=(0.0, 0.0, 0.0))
    display_type = str(params.get("display_type", "OCTAHEDRAL")).strip().upper()
    if display_type not in {"BBONE", "ENVELOPE", "OCTAHEDRAL", "STICK", "WIRE"}:
        raise invalid_argument("Unsupported armature display type.")
    root_name = _optional_name(params, "root_bone_name", maximum=63) or "Root"
    root_head = _bounded_vector3(params.get("root_head"), "root_head", default=(0.0, 0.0, 0.0))
    root_tail = _bounded_vector3(params.get("root_tail"), "root_tail", default=(0.0, 0.0, 1.0))
    if math.dist(root_head, root_tail) <= 1e-8:
        raise invalid_argument("Root bone head and tail must be distinct.")
    data = bpy.data.armatures.new(data_name)
    armature = bpy.data.objects.new(name, data)
    try:
        collection.objects.link(armature)
        armature.location = location
        data.display_type = display_type
        with _edit_armature(armature) as edit_bones:
            root = edit_bones.new(root_name)
            root.head = root_head
            root.tail = root_tail
    except Exception:
        bpy.data.objects.remove(armature, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
        raise
    bone = data.bones.get(root_name)
    return {
        "created": True,
        "object": armature.name,
        "data": data.name,
        "collection": collection.name,
        "location": [float(value) for value in armature.location],
        "root_bone": _bone_state(bone),
    }


def add_bone(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    armature = _armature_object(params)
    bone_name = _required_name(params, "bone_name", maximum=63)
    if armature.data.bones.get(bone_name) is not None:
        raise invalid_argument(f"Bone '{bone_name}' already exists on '{armature.name}'.")
    if len(armature.data.bones) >= _MAX_BONES:
        raise invalid_argument("The armature has reached the structured bone safety limit.")
    head = _bounded_vector3(params.get("head"), "head")
    tail = _bounded_vector3(params.get("tail"), "tail")
    if math.dist(head, tail) <= 1e-8:
        raise invalid_argument("Bone head and tail must be distinct.")
    parent_name = _optional_name(params, "parent_name", maximum=63)
    use_connect = bool_param(params, "use_connect", False)
    use_deform = bool_param(params, "use_deform", True)
    roll = float_param(params, "roll", 0.0, minimum=-1_000.0, maximum=1_000.0)
    with _edit_armature(armature) as edit_bones:
        parent = _bone_or_error(armature, parent_name, edit=True) if parent_name else None
        if use_connect and parent is None:
            raise invalid_argument("Connected bones require 'parent_name'.")
        if use_connect and math.dist(head, tuple(parent.tail)) > 1e-6:
            raise invalid_argument("A connected bone's head must equal its parent's tail.")
        bone = edit_bones.new(bone_name)
        bone.head = head
        bone.tail = tail
        bone.roll = roll
        bone.use_deform = use_deform
        bone.parent = parent
        bone.use_connect = use_connect
    created = armature.data.bones.get(bone_name)
    return {"created": True, "object": armature.name, "bone": _bone_state(created)}


def update_bone(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    armature = _armature_object(params)
    bone_name = _required_name(params, "bone_name", maximum=63)
    new_name = _optional_name(params, "new_name", maximum=63)
    parent_name = _optional_name(params, "parent_name", maximum=63)
    clear_parent = bool_param(params, "clear_parent", False)
    if parent_name is not None and clear_parent:
        raise invalid_argument("Use either 'parent_name' or 'clear_parent', not both.")
    supplied = {
        "new_name": new_name is not None,
        "head": params.get("head") is not None,
        "tail": params.get("tail") is not None,
        "roll": params.get("roll") is not None,
        "parent": parent_name is not None or clear_parent,
        "use_connect": params.get("use_connect") is not None,
        "use_deform": params.get("use_deform") is not None,
    }
    if not any(supplied.values()):
        raise invalid_argument("At least one bone property update is required.")
    existing = _bone_or_error(armature, bone_name)
    if new_name is not None and new_name != existing.name:
        collision = armature.data.bones.get(new_name)
        if collision is not None:
            raise invalid_argument(f"Bone '{new_name}' already exists on '{armature.name}'.")
    head = (
        _bounded_vector3(params.get("head"), "head")
        if supplied["head"]
        else tuple(float(value) for value in existing.head_local)
    )
    tail = (
        _bounded_vector3(params.get("tail"), "tail")
        if supplied["tail"]
        else tuple(float(value) for value in existing.tail_local)
    )
    roll = (
        float_param(params, "roll", 0.0, minimum=-1_000.0, maximum=1_000.0)
        if supplied["roll"]
        else None
    )
    use_deform = (
        bool_param(params, "use_deform", bool(existing.use_deform))
        if supplied["use_deform"]
        else None
    )
    requested_parent = (
        _bone_or_error(armature, parent_name)
        if parent_name is not None
        else (None if clear_parent else existing.parent)
    )
    cursor = requested_parent
    while cursor is not None:
        if cursor == existing:
            raise invalid_argument("Bone parenting would create a cycle.")
        cursor = cursor.parent
    use_connect = (
        bool_param(params, "use_connect", bool(existing.use_connect))
        if supplied["use_connect"]
        else (False if clear_parent else bool(existing.use_connect))
    )
    if use_connect and requested_parent is None:
        raise invalid_argument("A connected bone must have a parent.")
    if use_connect:
        parent_tail = tuple(float(value) for value in requested_parent.tail_local)
        if supplied["head"] and math.dist(head, parent_tail) > 1e-6:
            raise invalid_argument("A connected bone's head must equal its parent's tail.")
        head = parent_tail
    if math.dist(head, tail) <= 1e-8:
        raise invalid_argument("Bone head and tail must remain distinct.")
    with _edit_armature(armature):
        bone = _bone_or_error(armature, bone_name, edit=True)
        if new_name is not None and new_name != bone.name:
            bone.name = new_name
        if parent_name is not None:
            parent = _bone_or_error(armature, parent_name, edit=True)
            bone.parent = parent
        elif clear_parent:
            bone.use_connect = False
            bone.parent = None
        bone.head = head
        bone.tail = tail
        if roll is not None:
            bone.roll = roll
        if use_deform is not None:
            bone.use_deform = use_deform
        bone.use_connect = use_connect
        resulting_name = bone.name
    result = armature.data.bones.get(resulting_name)
    return {"updated": True, "object": armature.name, "bone": _bone_state(result)}


def remove_bone(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    armature = _armature_object(params)
    bone_name = _required_name(params, "bone_name", maximum=63)
    reparent_children = bool_param(params, "reparent_children", False)
    with _edit_armature(armature) as edit_bones:
        bone = _bone_or_error(armature, bone_name, edit=True)
        if len(bone.children) > _MAX_BONES:
            raise invalid_argument("The bone has too many children for a structured removal.")
        children = list(bone.children)
        if children and not reparent_children:
            raise invalid_argument(
                "The bone has children; set 'reparent_children' to true to preserve their hierarchy.",
                child_bones=[child.name for child in children[:64]],
            )
        parent = bone.parent
        child_names = [child.name for child in children]
        if reparent_children:
            for child in children:
                child.use_connect = False
                child.parent = parent
        edit_bones.remove(bone)
    return {
        "removed": True,
        "object": armature.name,
        "bone_name": bone_name,
        "reparented_children": child_names if reparent_children else [],
        "new_parent": parent.name if reparent_children and parent else None,
        "bone_count": len(armature.data.bones),
    }


def pose_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    armature = _armature_object(params)
    if armature.mode == "EDIT":
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "Pose transforms cannot be changed while the armature is in Edit Mode.",
            {"object": armature.name, "current_mode": armature.mode},
        )
    bone_name = _required_name(params, "bone_name", maximum=63)
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        _bone_or_error(armature, bone_name)
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The armature has no pose channel for the bone.")
    location_value = params.get("location")
    euler_value = params.get("rotation_euler")
    quaternion_value = params.get("rotation_quaternion")
    axis_angle_value = params.get("rotation_axis_angle")
    scale_value = params.get("scale")
    rotation_values = [value is not None for value in (euler_value, quaternion_value, axis_angle_value)]
    if sum(rotation_values) > 1:
        raise invalid_argument("Provide only one rotation representation.")
    rotation_mode_value = params.get("rotation_mode")
    if rotation_mode_value is not None:
        if not isinstance(rotation_mode_value, str):
            raise invalid_argument("'rotation_mode' must be a string.")
        rotation_mode = rotation_mode_value.strip().upper()
        if rotation_mode not in _ROTATION_MODES:
            raise invalid_argument("Unsupported pose rotation mode.", supported=sorted(_ROTATION_MODES))
    else:
        rotation_mode = None
    if not any((location_value is not None, any(rotation_values), scale_value is not None, rotation_mode is not None)):
        raise invalid_argument("At least one pose transform value is required.")
    location = (
        _bounded_vector3(location_value, "location") if location_value is not None else None
    )
    euler = (
        _bounded_vector3(euler_value, "rotation_euler") if euler_value is not None else None
    )
    quaternion = (
        _bounded_sequence(quaternion_value, "rotation_quaternion", 4)
        if quaternion_value is not None
        else None
    )
    if quaternion is not None and math.sqrt(sum(value * value for value in quaternion)) <= 1e-8:
        raise invalid_argument("'rotation_quaternion' must have non-zero length.")
    axis_angle = (
        _bounded_sequence(axis_angle_value, "rotation_axis_angle", 4)
        if axis_angle_value is not None
        else None
    )
    if axis_angle is not None and math.sqrt(sum(value * value for value in axis_angle[1:])) <= 1e-8:
        raise invalid_argument("The axis-angle rotation axis must have non-zero length.")
    scale = _bounded_vector3(scale_value, "scale") if scale_value is not None else None
    if rotation_mode is not None:
        pose_bone.rotation_mode = rotation_mode
    if location is not None:
        pose_bone.location = location
    if euler is not None:
        if pose_bone.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
            pose_bone.rotation_mode = "XYZ"
        pose_bone.rotation_euler = euler
    if quaternion is not None:
        pose_bone.rotation_mode = "QUATERNION"
        pose_bone.rotation_quaternion = quaternion
    if axis_angle is not None:
        pose_bone.rotation_mode = "AXIS_ANGLE"
        pose_bone.rotation_axis_angle = axis_angle
    if scale is not None:
        pose_bone.scale = scale
    armature.update_tag(refresh={"OBJECT"})
    return {"updated": True, "object": armature.name, "pose_bone": _pose_bone_state(pose_bone)}


def add_constraint(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    armature = _armature_object(params)
    bone_name = _required_name(params, "bone_name", maximum=63)
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        _bone_or_error(armature, bone_name)
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The armature has no pose channel for the bone.")
    constraint_type = _required_name(params, "constraint_type", maximum=64).upper()
    if constraint_type not in _CONSTRAINT_TYPES:
        raise invalid_argument("Unsupported pose constraint type.", supported=sorted(_CONSTRAINT_TYPES))
    name = _optional_name(params, "name", maximum=63)
    if name is not None and pose_bone.constraints.get(name) is not None:
        raise invalid_argument(f"Constraint '{name}' already exists on pose bone '{bone_name}'.")
    target_name = _optional_name(params, "target_object")
    if constraint_type in _TARGET_CONSTRAINT_TYPES and target_name is None:
        raise invalid_argument(f"Constraint type '{constraint_type}' requires 'target_object'.")
    target = get_object(target_name, allow_active=False) if target_name else None
    subtarget = _optional_name(params, "subtarget", maximum=63)
    if subtarget is not None:
        if target is None or target.type != "ARMATURE":
            raise invalid_argument("'subtarget' requires an armature target object.")
        _bone_or_error(target, subtarget)
    influence = float_param(params, "influence", 1.0, minimum=0.0, maximum=1.0)
    chain_count = int_param(params, "chain_count", 0, minimum=0, maximum=255)
    constraint = pose_bone.constraints.new(type=constraint_type)
    try:
        if name is not None:
            constraint.name = name
        constraint.influence = influence
        if target is not None:
            constraint.target = target
        if subtarget is not None:
            constraint.subtarget = subtarget
        if constraint_type == "IK":
            constraint.chain_count = chain_count
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pose_bone.constraints.remove(constraint)
        raise
    return {
        "created": True,
        "object": armature.name,
        "bone_name": bone_name,
        "constraint": _constraint_state(constraint),
    }


def remove_constraint(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    armature = _armature_object(params)
    bone_name = _required_name(params, "bone_name", maximum=63)
    constraint_name = _required_name(params, "constraint_name", maximum=63)
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        _bone_or_error(armature, bone_name)
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The armature has no pose channel for the bone.")
    constraint = pose_bone.constraints.get(constraint_name)
    if constraint is None:
        raise invalid_argument(
            f"Constraint '{constraint_name}' does not exist on pose bone '{bone_name}'.",
            available_constraints=[item.name for item in islice(pose_bone.constraints, 128)],
            available_constraints_truncated=len(pose_bone.constraints) > 128,
        )
    pose_bone.constraints.remove(constraint)
    return {
        "removed": True,
        "object": armature.name,
        "bone_name": bone_name,
        "constraint_name": constraint_name,
        "remaining_constraints": [item.name for item in pose_bone.constraints],
    }


def _ensure_armature_modifier(mesh: Any, armature: Any) -> Any:
    for modifier in mesh.modifiers:
        if modifier.type == "ARMATURE" and modifier.object == armature:
            return modifier
    modifier = mesh.modifiers.new(name=f"{armature.name} Deform", type="ARMATURE")
    modifier.object = armature
    return modifier


def _bind_empty_groups(mesh: Any, armature: Any, *, parent: bool) -> dict[str, Any]:
    if len(armature.data.bones) > _MAX_BONES:
        raise invalid_argument("The armature exceeds the structured deform-bone limit.")
    if len(mesh.vertex_groups) > 4_096 or len(mesh.modifiers) > 4_096:
        raise invalid_argument("The mesh has too many existing groups or modifiers for safe binding.")
    deform_bones = [bone for bone in armature.data.bones if bone.use_deform]
    existing_groups = {group.name for group in mesh.vertex_groups}
    existing_modifiers = {modifier.name for modifier in mesh.modifiers}
    previous_parent = mesh.parent
    previous_matrix = mesh.matrix_world.copy()
    created_groups: list[str] = []
    try:
        for bone in deform_bones:
            if mesh.vertex_groups.get(bone.name) is None:
                mesh.vertex_groups.new(name=bone.name)
                created_groups.append(bone.name)
        modifier = _ensure_armature_modifier(mesh, armature)
        if parent:
            matrix_world = mesh.matrix_world.copy()
            mesh.parent = armature
            mesh.matrix_world = matrix_world
    except Exception:
        mesh.parent = previous_parent
        mesh.matrix_world = previous_matrix
        for group in list(mesh.vertex_groups):
            if group.name not in existing_groups:
                mesh.vertex_groups.remove(group)
        for item in list(mesh.modifiers):
            if item.name not in existing_modifiers:
                mesh.modifiers.remove(item)
        raise
    return {
        "created_vertex_groups": created_groups,
        "modifier": modifier.name,
    }


def _bind_automatic(mesh: Any, armature: Any) -> dict[str, Any]:
    bpy = require_blender()
    if len(mesh.data.vertices) > 2_000_000:
        raise invalid_argument("Automatic weights are limited to meshes with at most 2,000,000 vertices.")
    if len(mesh.vertex_groups) > 4_096 or len(mesh.modifiers) > 4_096:
        raise invalid_argument("The mesh has too many existing groups or modifiers for safe rollback tracking.")
    existing_groups = {group.name for group in mesh.vertex_groups}
    existing_modifiers = {modifier.name for modifier in mesh.modifiers}
    previous_parent = mesh.parent
    previous_matrix = mesh.matrix_world.copy()
    try:
        with preserved_object_context():
            _ensure_object_mode()
            _select_only(mesh, armature, active=armature)
            if not bpy.ops.object.parent_set.poll():
                raise BridgeError(
                    ErrorCode.BLENDER_CONTEXT_ERROR,
                    "Automatic weights are unavailable in the current Blender context.",
                )
            result = bpy.ops.object.parent_set(type="ARMATURE_AUTO", keep_transform=True)
            if "FINISHED" not in result:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Automatic weight binding did not finish.")
    except Exception:
        mesh.parent = previous_parent
        mesh.matrix_world = previous_matrix
        for group in list(mesh.vertex_groups):
            if group.name not in existing_groups:
                mesh.vertex_groups.remove(group)
        for modifier in list(mesh.modifiers):
            if modifier.name not in existing_modifiers:
                mesh.modifiers.remove(modifier)
        raise
    modifier = next(
        (item for item in mesh.modifiers if item.type == "ARMATURE" and item.object == armature),
        None,
    )
    if mesh.parent != armature or modifier is None:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Automatic weights returned without the expected armature parent and modifier.",
        )
    return {
        "created_vertex_groups": sorted(
            group.name for group in mesh.vertex_groups if group.name not in existing_groups
        ),
        "modifier": modifier.name,
    }


def bind_mesh(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    mesh = get_object(params.get("mesh_object"), allow_active=False)
    if mesh.type != "MESH":
        raise invalid_argument("'mesh_object' must name a mesh object.", object_type=mesh.type)
    armature_name = params.get("armature_object")
    armature = get_object(armature_name, allow_active=False)
    if armature.type != "ARMATURE":
        raise invalid_argument("'armature_object' must name an armature object.", object_type=armature.type)
    method = str(params.get("method", "EMPTY_GROUPS")).strip().upper()
    if method not in {"AUTOMATIC", "EMPTY_GROUPS"}:
        raise invalid_argument("'method' must be AUTOMATIC or EMPTY_GROUPS.")
    parent = bool_param(params, "parent", True)
    if method == "AUTOMATIC" and not parent:
        raise invalid_argument("Automatic weights require 'parent' to be true.")
    binding = (
        _bind_automatic(mesh, armature)
        if method == "AUTOMATIC"
        else _bind_empty_groups(mesh, armature, parent=parent)
    )
    return {
        "bound": True,
        "method": method,
        "object": mesh.name,
        "armature": armature.name,
        "parent": mesh.parent.name if mesh.parent else None,
        "vertex_group_count": len(mesh.vertex_groups),
        **binding,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "rig.inspect",
        inspect_rig,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="rigging",
        description="Inspect a bounded armature hierarchy, pose transforms, and constraints.",
    )
    edit = {
        "permissions": (Permission.EDIT_ANIMATION,),
        "toolset": "rigging",
        "modifies": True,
    }
    registry.register(
        "rig.create",
        create_rig,
        permissions=(Permission.EDIT_ANIMATION, Permission.TRANSFORM_OBJECTS),
        toolset="rigging",
        modifies=True,
        description="Create an armature object with one explicit root bone.",
    )
    registry.register("rig.bone_add", add_bone, description="Add one explicit edit bone.", **edit)
    registry.register(
        "rig.bone_update",
        update_bone,
        description="Update one edit bone's geometry, hierarchy, name, or deform flags.",
        **edit,
    )
    registry.register(
        "rig.bone_remove",
        remove_bone,
        permissions=(Permission.EDIT_ANIMATION, Permission.DELETE_OBJECTS),
        toolset="rigging",
        modifies=True,
        description="Remove one explicit bone, rejecting children unless reparenting is acknowledged.",
    )
    registry.register(
        "rig.pose_transform",
        pose_transform,
        permissions=(Permission.EDIT_ANIMATION, Permission.TRANSFORM_OBJECTS),
        toolset="rigging",
        modifies=True,
        description="Set explicit pose-bone transform channels with finite values.",
    )
    registry.register(
        "rig.constraint_add",
        add_constraint,
        description="Add a supported pose-bone constraint with an explicit target where required.",
        **edit,
    )
    registry.register(
        "rig.constraint_remove",
        remove_constraint,
        description="Remove one named pose-bone constraint.",
        **edit,
    )
    registry.register(
        "rig.bind_mesh",
        bind_mesh,
        permissions=(Permission.EDIT_ANIMATION, Permission.TRANSFORM_OBJECTS),
        toolset="rigging",
        modifies=True,
        description="Bind a named mesh to an armature using empty groups or contextual automatic weights.",
    )


__all__ = ["register_tools"]
