"""Bounded object-owned two-bone IK with explicit independent controls and skin scope."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, int_param, reject_unknown_params, require_blender
from ._object_safety import require_local_editable_id
from ._object_scope import (
    MutationGuard,
    _ordinary_scene_membership,
    datablock_identity,
    require_object_scope,
)
from .shader_scope import name

LOGGER = logging.getLogger(__name__)
MAX_BONES, MAX_MESHES, MAX_USERS = 256, 8, 256
_FIELDS = (
    "name", "target", "subtarget", "pole_target", "pole_subtarget", "chain_count", "iterations",
    "use_tail", "use_stretch", "use_location", "use_rotation", "weight", "orient_weight",
    "reference_axis", "lock_location_x", "lock_location_y", "lock_location_z",
    "lock_rotation_x", "lock_rotation_y", "lock_rotation_z", "ik_type", "limit_mode",
    "distance", "head_tail", "use_bbone_shape", "owner_space", "target_space", "space_object",
    "space_subtarget", "mute", "influence", "pole_angle",
)
_POSE_FIELDS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
                "lock_location", "lock_rotation", "lock_scale", "lock_ik_x", "lock_ik_y", "lock_ik_z",
                "use_ik_limit_x", "use_ik_limit_y", "use_ik_limit_z", "ik_min_x", "ik_min_y", "ik_min_z",
                "ik_max_x", "ik_max_y", "ik_max_z", "ik_stiffness_x", "ik_stiffness_y", "ik_stiffness_z",
                "ik_stretch", "ik_linear_weight", "ik_rotation_weight", "use_ik_linear_control", "use_ik_rotation_control", "rotation_mode")


def _key(value: Any) -> int | None:
    return None if value is None else datablock_identity(value)


def _value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Character ownership metadata contains a nonfinite number.")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "as_pointer") or hasattr(value, "name"):
        return ("ID", _key(value))
    return tuple(_value(item) for item in value)


def _object(bpy: Any, raw: Any) -> Any:
    exact = name(raw, "object_name")
    if len(bpy.context.scene.objects) > 65536:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Explicit character lookup exceeds 65536 scene objects.")
    matches = list(islice((obj for obj in bpy.context.scene.objects if obj.name == exact), 2))
    if len(matches) != 1:
        raise invalid_argument("Object must resolve exactly in the current scene.", object_name=exact)
    return matches[0]


def _bone(rig: Any, raw: Any) -> Any:
    exact = name(raw, "bone_name")
    if rig.type != "ARMATURE" or rig.pose is None or len(rig.pose.bones) > MAX_BONES:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK requires an armature with at most 256 pose bones.")
    bone = rig.pose.bones.get(exact)
    if bone is None:
        raise invalid_argument("Exact pose bone does not exist.", bone_name=exact)
    return bone


def _constraint(bone: Any, exact: str) -> Any:
    matches = [item for item in bone.constraints if item.name == exact]
    if len(matches) > 1:
        raise invalid_argument("Constraint name is ambiguous.")
    constraint = matches[0] if matches else None
    if constraint is not None and constraint.type != "IK":
        raise invalid_argument("The named constraint exists and is not IK.")
    return constraint


def _configuration(constraint: Any) -> dict[str, Any] | None:
    if constraint is None:
        return None
    result = {field: _value(getattr(constraint, field)) for field in _FIELDS if hasattr(constraint, field)}
    rna = getattr(constraint, "bl_rna", None)
    if rna is not None:
        properties = rna.properties
        if len(properties) > 128:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK RNA property inventory exceeds 128 fields.")
        for prop in properties:
            if prop.is_readonly:
                continue
            if prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "An IK property has an unreviewed ownership snapshot type.")
            result[prop.identifier] = _value(getattr(constraint, prop.identifier))
    # Unknown constraint custom properties are not silently treated as operation-owned state.
    try:
        custom_count = len(constraint.keys()) if hasattr(constraint, "keys") else 0
    except TypeError:
        # Native constraints expose bpy_struct.keys even where IDProperties are
        # unavailable (4.5/5.2); this means there is no custom-property payload.
        custom_count = 0
    if custom_count:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK constraints with custom properties require a broader lifecycle contract.")
    return result


def _summary(constraint: Any) -> dict[str, Any] | None:
    if constraint is None:
        return None
    result = _configuration(constraint)
    assert result is not None
    for field in ("target", "pole_target", "space_object"):
        if field in result:
            result[field] = getattr(getattr(constraint, field), "name", None)
    return result


def _static(obj: Any) -> None:
    animation = getattr(obj, "animation_data", None)
    if obj.parent is not None or len(obj.constraints) or getattr(obj, "instance_collection", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK scope requires objects without parents, object constraints or collection instances.", {"object": obj.name})
    if animation is not None and (animation.action is not None or len(animation.drivers) or len(animation.nla_tracks) or animation.use_tweak_mode):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Actions, drivers and NLA need a broader combined IK workflow.", {"object": obj.name})


def _membership(bpy: Any, obj: Any, user: Any) -> bool:
    for collection in obj.users_collection:
        if _key(user) == _key(collection):
            return collection.user_of_id(obj) == 1
    return _ordinary_scene_membership(bpy.context.scene, user, obj)


def _scope(bpy: Any, params: Mapping[str, Any], *, constraint: Any) -> tuple[Any, Any, Any, Any, Any, list[Any]]:
    rig = _object(bpy, params.get("object_name"))
    root, tip = _bone(rig, params.get("root_bone_name")), _bone(rig, params.get("tip_bone_name"))
    target, pole = _object(bpy, params.get("target_object")), _object(bpy, params.get("pole_object"))
    raw_meshes = params.get("affected_meshes")
    if not isinstance(raw_meshes, list) or len(raw_meshes) > MAX_MESHES or any(not isinstance(item, str) for item in raw_meshes) or len(set(raw_meshes)) != len(raw_meshes):
        raise invalid_argument("affected_meshes must explicitly list zero to eight distinct mesh object names.")
    meshes = [_object(bpy, item) for item in raw_meshes]
    if len({_key(mesh) for mesh in meshes}) != len(meshes):
        raise invalid_argument("affected_meshes must resolve to distinct exact objects.")
    if _key(target) == _key(pole) or any(item.type != "EMPTY" or item.data is not None for item in (target, pole)):
        raise invalid_argument("Target and pole must be distinct existing Empty objects.")
    if tip.parent != root or not tip.bone.use_connect or list(root.children) != [tip] or len(tip.children):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK requires one connected two-bone branch: root has only the tip child and the tip has no children.")
    if getattr(rig.pose, "ik_solver", "LEGACY") != "LEGACY":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Only Blender's legacy IK solver is reviewed.")
    if getattr(rig.data, "pose_position", "POSE") != "POSE":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK editing requires armature Pose Position without changing the data setting.")
    if constraint is not None and (
        getattr(constraint, "ik_type", "COPY_POSE") != "COPY_POSE"
        or constraint.target not in (None, target) or constraint.pole_target not in (None, pole)
        or constraint.subtarget or constraint.pole_subtarget
        or getattr(constraint, "space_object", None) is not None
        or getattr(constraint, "owner_space", "WORLD") != "WORLD"
        or getattr(constraint, "target_space", "WORLD") != "WORLD"
    ):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing IK must use these exact object controls (or unbound slots), no bone subtargets/custom spaces, and COPY_POSE mode.")
    for bone in (root, tip):
        if not math.isfinite(bone.bone.length) or bone.bone.length <= 1e-6:
            raise invalid_argument("IK rest bones must have finite length greater than 0.000001.")
        if getattr(bone.bone, "bbone_segments", 1) != 1:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Bendy-bone IK requires a separate reviewed deformation workflow.")
    require_local_editable_id(rig.data, operation="Two-bone IK")
    for obj in (rig, target, pole, *meshes):
        require_object_scope(bpy, obj, operation="Two-bone IK")
        _static(obj)
    for bone in rig.pose.bones:
        if len(bone.constraints) > 1 or any(_key(item) != _key(constraint) for item in bone.constraints):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Other pose constraints require a broader reviewed IK dependency workflow.")
    for mesh in meshes:
        if mesh.type != "MESH" or len(mesh.modifiers) != 1:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Each affected skin must have one explicit armature modifier only.")
        modifier = mesh.modifiers[0]
        if modifier.type != "ARMATURE" or modifier.object != rig or not modifier.use_vertex_groups or modifier.use_bone_envelopes or modifier.use_deform_preserve_volume or modifier.use_multi_modifier or modifier.vertex_group:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Affected skin requires plain vertex-group armature deformation without envelopes, preserve volume, masks or multi-modifier blending.")
        require_local_editable_id(mesh.data, operation="Two-bone IK skin scope")
    objects = [rig, target, pole, *meshes]
    try:
        users = bpy.data.user_map(subset=set(objects))
        for obj in objects:
            direct = users.get(obj, ())
            if len(direct) > MAX_USERS:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK direct-consumer scope exceeds 256 datablocks.")
            for user in direct:
                if _membership(bpy, obj, user):
                    continue
                if obj == rig and any(user == mesh and mesh.user_of_id(rig) == 1 for mesh in meshes):
                    continue
                if obj in (target, pole) and user == rig and constraint is not None:
                    expected = int(constraint.target == obj) + int(constraint.pole_target == obj)
                    if expected and rig.user_of_id(obj) == expected:
                        continue
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "IK has an incoming reference outside its explicit rig, control and skin scope.", {"object": obj.name, "consumer": getattr(user, "name", None)})
    except BridgeError:
        raise
    except Exception as error:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cannot prove IK direct-reference ownership.") from error
    return rig, root, tip, target, pole, meshes


def _environment(scope: tuple[Any, Any, Any, Any, Any, list[Any]]) -> Any:
    rig, root, tip, target, pole, meshes = scope
    bones = []
    for bone in rig.pose.bones:
        rest = bone.bone
        bones.append((_key(bone), bone.name, _key(bone.parent), _key(rest), _value(rest.head_local), _value(rest.tail_local),
                      rest.use_connect, rest.use_deform,
                      tuple((field, _value(getattr(rest, field))) for field in ("matrix_local", "inherit_scale", "use_local_location", "use_inherit_rotation", "use_relative_parent", "bbone_segments") if hasattr(rest, field)),
                      tuple((field, _value(getattr(bone, field))) for field in _POSE_FIELDS if hasattr(bone, field))))
    objects = tuple((_key(obj), obj.name, _key(getattr(obj, "data", None)), _value(obj.matrix_world)) for obj in (rig, target, pole, *meshes))
    skin = tuple((_key(mesh.modifiers[0]), _key(mesh.data), bool(mesh.modifiers[0].show_viewport), bool(mesh.modifiers[0].show_render)) for mesh in meshes)
    return objects, tuple(bones), skin, _key(root), _key(tip)


class _Boundary:
    def __init__(self, bpy: Any, context: ToolContext, params: Mapping[str, Any], method: str, constraint: Any):
        self.bpy, self.context, self.params, self.method = bpy, context, params, method
        self.guard = MutationGuard(bpy, context, method)
        self.constraint, self.key = constraint, _key(constraint)
        self.expected = _configuration(constraint)
        scope = _scope(bpy, params, constraint=constraint)
        self.frozen = _environment(scope)
        for obj in (scope[0], scope[3], scope[4], *scope[5]):
            self.guard.remember(obj, bpy.data.objects)
            if obj.data is not None:
                self.guard.remember(obj.data)

    def check(self, *, delete: bool = False) -> tuple[Any, Any, Any, Any, Any, list[Any]]:
        self.guard.check(dependencies=False)
        flags = self.context.state.snapshot()
        if flags.get("emergency_stopped"):
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "IK mutation emergency-stopped.")
        if flags.get("paused"):
            raise BridgeError(ErrorCode.AGENT_PAUSED, "IK mutation paused.")
        self.context.require(Permission.EDIT_ANIMATION)
        if delete:
            self.context.require(Permission.DELETE_OBJECTS)
        scope = _scope(self.bpy, self.params, constraint=self.constraint)
        if _environment(scope) != self.frozen:
            raise invalid_argument("IK owner, controls, rest/pose channels or skin identity changed after inspection.")
        current = _constraint(scope[2], self.params["constraint_name"])
        # A newly allocated constraint is allowed to retain its temporary name only
        # before its explicit requested name has been assigned.
        if self.constraint is not None and _key(current) != self.key:
            if self.expected is None or self.expected.get("name") == self.params["constraint_name"]:
                raise invalid_argument("IK constraint was replaced or renamed; automatic writes/recovery refused.")
            if not any(_key(item) == self.key for item in scope[2].constraints):
                raise invalid_argument("Allocated IK constraint no longer belongs to the exact tip bone.")
            current = self.constraint
        if _key(current) != self.key or _configuration(current) != self.expected:
            raise invalid_argument("IK constraint configuration changed outside this operation.")
        return scope


def _name(params: Mapping[str, Any]) -> str:
    exact = name(params.get("constraint_name"), "constraint_name")
    if len(exact.encode("utf-8")) > 63:
        raise invalid_argument("constraint_name must fit Blender's 63-byte name limit.")
    return exact


def _result(scope: tuple[Any, Any, Any, Any, Any, list[Any]], constraint: Any) -> dict[str, Any]:
    rig, root, tip, target, pole, meshes = scope
    return {"object": rig.name, "root_bone_name": root.name, "tip_bone_name": tip.name,
            "constraint": _summary(constraint), "target_object": target.name, "pole_object": pole.name,
            "affected_objects": [rig.name, *[mesh.name for mesh in meshes]], "affected_bones": [root.name, tip.name],
            "direct_consumer_scope_complete": True, "full_dependency_graph_verified": False,
            "verification_required": True, "evaluated_goal_verified": False, "project_saved": False}


def ik_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "tip_bone_name", "constraint_name"})
    bpy = require_blender()
    rig = _object(bpy, params.get("object_name"))
    tip = _bone(rig, params.get("tip_bone_name"))
    exact = _name(params)
    if len(tip.constraints) > 64:
        raise invalid_argument("IK inspection exceeds 64 tip constraints.")
    if context.check_cancelled:
        context.check_cancelled()
    # Re-resolve after the callback rather than reading a stale bone wrapper.
    current = _object(bpy, params.get("object_name"))
    if _key(current) != _key(rig) or _key(_bone(current, params.get("tip_bone_name"))) != _key(tip):
        raise invalid_argument("IK inspection identity changed.")
    return {"object": rig.name, "tip_bone_name": tip.name, "constraint": _summary(_constraint(tip, exact)),
            "scope": "Stored IK settings only; evaluated deformation and visual quality require separate evidence."}


def ik_configure(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "root_bone_name", "tip_bone_name", "target_object", "pole_object", "affected_meshes",
                                   "constraint_name", "create", "pole_angle", "influence", "iterations", "use_stretch"})
    bpy = require_blender()
    exact = _name(params)
    rig = _object(bpy, params.get("object_name"))
    tip = _bone(rig, params.get("tip_bone_name"))
    constraint = _constraint(tip, exact)
    create = bool_param(params, "create", False)
    if constraint is None and not create:
        raise invalid_argument("A missing IK constraint requires explicit create=true.")
    if constraint is not None and create:
        raise invalid_argument("create=true requires an unused exact constraint name.")
    angle = float_param(params, "pole_angle", 0.0, minimum=-math.pi, maximum=math.pi)
    influence = float_param(params, "influence", 1.0, minimum=0.0, maximum=1.0)
    iterations = int_param(params, "iterations", 128, minimum=1, maximum=512)
    stretch = bool_param(params, "use_stretch", False)
    boundary = _Boundary(bpy, context, {**params, "constraint_name": exact}, "rig.ik_configure", constraint)
    scope = boundary.check()
    affected_names = [scope[0].name, *[mesh.name for mesh in scope[5]]]
    if constraint is not None and getattr(constraint, "ik_type", "COPY_POSE") != "COPY_POSE":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Distance IK needs a separate reviewed contract.")
    original = _configuration(constraint)
    original_values = {field: getattr(constraint, field) for field in _FIELDS if constraint is not None and hasattr(constraint, field)}
    attempted: list[str] = []
    created = allocation_attempted = False
    try:
        if constraint is None:
            # The exact empty channel was checked after the last callback above.
            allocation_attempted = True
            constraint = tip.constraints.new("IK")
            created = True
            boundary.constraint, boundary.key = constraint, _key(constraint)
            boundary.expected = _configuration(constraint)
        desired = {"name": exact, "target": scope[3], "pole_target": scope[4], "subtarget": "", "pole_subtarget": "",
                   "chain_count": 2, "iterations": iterations, "use_tail": True, "use_stretch": stretch,
                   "use_location": True, "use_rotation": False, "influence": influence, "pole_angle": angle, "mute": False}
        for field, value in desired.items():
            boundary.check()
            if _value(getattr(constraint, field)) == _value(value):
                continue
            previous = getattr(constraint, field)
            attempted.append(field)
            try:
                setattr(constraint, field, value)
            finally:
                observed = getattr(constraint, field)
                if _value(observed) == _value(value) or (isinstance(value, float) and math.isclose(observed, value, abs_tol=1e-6)):
                    assert boundary.expected is not None
                    boundary.expected[field] = _value(observed)
                elif _value(observed) != _value(previous):
                    # Unknown partial writes must not be adopted as owned state.
                    LOGGER.error("IK setter retained an unexpected value for %s", field)
            if _value(observed) != _value(value) and not (isinstance(value, float) and math.isclose(observed, value, abs_tol=1e-6)):
                raise RuntimeError("Blender did not retain a requested IK setting.")
        bpy.context.view_layer.update()
        scope = boundary.check()
        return {"created": created, **_result(scope, constraint)}
    except Exception as error:
        LOGGER.exception("Two-bone IK configuration failed")
        restored = False
        try:
            boundary.check(delete=created)
            if created:
                tip.constraints.remove(constraint)
                boundary.constraint, boundary.key, boundary.expected = None, None, None
            else:
                for field in reversed(attempted):
                    boundary.check()
                    setattr(constraint, field, original_values[field])
                    if _value(getattr(constraint, field)) != _value(original_values[field]):
                        raise RuntimeError("Blender did not restore an original IK setting.")
                    assert boundary.expected is not None
                    boundary.expected[field] = _value(original_values[field])
            bpy.context.view_layer.update()
            boundary.check()
            restored = _configuration(_constraint(tip, exact)) == original
        except Exception:
            LOGGER.exception("IK configuration compensation refused or failed")
        retained = None
        retained_owned = False
        observed_names: list[str] = []
        try:
            current = next((item for item in tip.constraints if _key(item) == boundary.key), None)
            observed_names = [item.name for item in islice(tip.constraints, 16)]
            if current is not None:
                retained = current.name
                retained_owned = _configuration(current) == boundary.expected
        except Exception:
            LOGGER.exception("Could not inspect retained IK allocation after the primary failure")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "IK configuration failed; inspect retained state before continuing.",
                          {"execution_started": allocation_attempted or bool(attempted), "rollback_verified": restored,
                           "possible_mutation": not restored and (allocation_attempted or bool(attempted)), "verification_required": True,
                           "retained_constraint_name": retained, "retained_configuration_matches_owned_write": retained_owned,
                           "observed_tip_constraint_names": observed_names, "cleanup_skipped": not restored,
                           "affected_objects": affected_names}) from error


def ik_remove(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "root_bone_name", "tip_bone_name", "target_object", "pole_object", "affected_meshes", "constraint_name", "confirm"})
    if not bool_param(params, "confirm", False):
        raise invalid_argument("IK removal requires confirm=true.")
    bpy = require_blender()
    exact = _name(params)
    rig = _object(bpy, params.get("object_name"))
    tip = _bone(rig, params.get("tip_bone_name"))
    constraint = _constraint(tip, exact)
    if constraint is None:
        raise invalid_argument("Exact IK constraint does not exist.")
    boundary = _Boundary(bpy, context, {**params, "constraint_name": exact}, "rig.ik_remove", constraint)
    scope = boundary.check(delete=True)
    removed = False
    original_key = _key(constraint)
    try:
        tip.constraints.remove(constraint)
        removed = True
        boundary.constraint, boundary.key, boundary.expected = None, None, None
        bpy.context.view_layer.update()
        boundary.check()
        return {"removed": True, "removed_constraint_name": exact, "automatic_recreation_attempted": False, **_result(scope, None)}
    except Exception as error:
        try:
            present = any(_key(item) == original_key for item in tip.constraints)
        except (ReferenceError, AttributeError):
            present = None
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "IK removal could not be verified; inspect the exact bone before retrying.",
                          {"execution_started": True, "removal_returned_successfully": removed, "original_constraint_present": present, "possible_mutation": True,
                           "rollback_verified": False, "verification_required": True}) from error


def register_tools(registry: ToolRegistry) -> None:
    for tool_name, handler, modifies, permissions, description in (
        ("rig.ik_inspect", ik_inspect, False, (Permission.INSPECT_SCENE,), "Inspect one exact stored pose-bone IK constraint; no evaluated-quality verdict."),
        ("rig.ik_configure", ik_configure, True, (Permission.EDIT_ANIMATION,), "Create/configure explicit two-bone IK with independent Empty controls and enumerated skin scope."),
        ("rig.ik_remove", ik_remove, True, (Permission.EDIT_ANIMATION, Permission.DELETE_OBJECTS), "Confirm removal of one exact scoped IK constraint; native checkpoint recovery remains explicit."),
    ):
        registry.register(tool_name, handler, toolset="rigging", modifies=modifies, permissions=permissions, description=description)
