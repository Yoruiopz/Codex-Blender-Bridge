"""Read-only current-frame skin and evaluated-pose evidence, never an artistic verdict."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import float_param, int_param, reject_unknown_params, require_blender
from .rig_ik import _FIELDS, _POSE_FIELDS, _bone, _key, _object, _value

MAX_VERTICES, MAX_EDGES, MAX_FACES, MAX_LOOPS, MAX_GROUPS = 4096, 8192, 4096, 16384, 128
_EPSILON = 1e-9
LOGGER = logging.getLogger(__name__)


def _vec(value: Any) -> tuple[float, float, float]:
    result = tuple(float(item) for item in value)
    if len(result) != 3 or any(not math.isfinite(item) or abs(item) > 1e9 for item in result):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Deformation coordinates must be finite and bounded by 1000000000.")
    return result  # type: ignore[return-value]


def _minus(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float]:
    return tuple(a - b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _length(value: Sequence[float]) -> float:
    return math.sqrt(sum(item * item for item in value))


def _triangle_area(points: list[tuple[float, float, float]], triangle: Sequence[int]) -> float:
    first, second, third = (points[index] for index in triangle)
    left, right = _minus(second, first), _minus(third, first)
    return .5 * _length((left[1]*right[2]-left[2]*right[1], left[2]*right[0]-left[0]*right[2], left[0]*right[1]-left[1]*right[0]))


def _point(matrix: Any, value: Any, world: bool) -> tuple[float, float, float]:
    return _vec(matrix @ value if world else value)


def _topology(data: Any) -> Any:
    if len(data.vertices) > MAX_VERTICES or len(data.edges) > MAX_EDGES or len(data.polygons) > MAX_FACES or len(data.loops) > MAX_LOOPS:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Deformation mesh exceeds 4096 vertices, 8192 edges, 4096 faces or 16384 loops.")
    return (len(data.vertices), tuple(tuple(edge.vertices) for edge in data.edges), tuple(tuple(face.vertices) for face in data.polygons))


def _constraints(rig: Any) -> Any:
    result, total = [], 0
    for bone in rig.pose.bones:
        total += len(bone.constraints)
        if total > 128:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Deformation source snapshot exceeds 128 pose constraints.")
        for constraint in bone.constraints:
            # Only static reviewed IK metadata is needed by this first inspector.
            # Other constraints fail explicitly rather than giving incoherent evidence.
            if constraint.type != "IK":
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Current deformation diagnostics support IK pose constraints only.")
            result.append((_key(bone), _key(constraint), tuple((field, _value(getattr(constraint, field))) for field in _FIELDS if hasattr(constraint, field))))
    return tuple(result)


def _source(bpy: Any, params: Mapping[str, Any]) -> tuple[Any, Any, list[Any], Any, Any]:
    rig, mesh = _object(bpy, params.get("object_name")), _object(bpy, params.get("mesh_object"))
    raw_bones = params.get("bone_names")
    if not isinstance(raw_bones, list) or not 1 <= len(raw_bones) <= 32 or any(not isinstance(item, str) for item in raw_bones) or len(set(raw_bones)) != len(raw_bones):
        raise invalid_argument("bone_names must contain one to 32 distinct explicit names.")
    bones = [_bone(rig, item) for item in raw_bones]
    if bpy.context.mode not in {"OBJECT", "POSE"} or mesh.mode != "OBJECT":
        raise BridgeError(ErrorCode.INVALID_MODE, "Deformation inspection requires Object or Pose Mode and an Object Mode mesh.")
    if mesh.type != "MESH" or mesh.data.shape_keys is not None or len(mesh.modifiers) != 1:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Skin diagnostics require one armature modifier, no shape keys or other modifiers.")
    modifier = mesh.modifiers[0]
    if modifier.type != "ARMATURE" or modifier.object != rig or not modifier.use_vertex_groups or modifier.use_bone_envelopes or modifier.use_deform_preserve_volume or modifier.use_multi_modifier or modifier.vertex_group or not modifier.show_viewport:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Skin diagnostics require enabled plain vertex-group armature deformation without envelopes, masks, preserve volume or multi-modifier blending.")
    _topology(mesh.data)
    if len(mesh.vertex_groups) > MAX_GROUPS or sum(len(vertex.groups) for vertex in mesh.data.vertices) > 65536:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Weight evidence exceeds 128 groups or 65536 memberships.")
    target = None if params.get("target_object") is None else _object(bpy, params["target_object"])
    tip_name = params.get("tip_bone_name")
    if (target is None) != (tip_name is None):
        raise invalid_argument("target_object and tip_bone_name must be supplied together.")
    tip = None if tip_name is None else _bone(rig, tip_name)
    return rig, mesh, bones, target, tip


def _snapshot(bpy: Any, scope: tuple[Any, Any, list[Any], Any, Any]) -> Any:
    rig, mesh, _bones, target, tip = scope
    groups = tuple((group.index, group.name, bool(group.lock_weight)) for group in mesh.vertex_groups)
    rest_pose = tuple((_key(bone), _key(bone.bone), bone.name, _key(bone.parent), _value(bone.bone.head_local),
                       _value(bone.bone.tail_local), bool(bone.bone.use_deform),
                       tuple((field, _value(getattr(bone.bone, field))) for field in ("matrix_local", "inherit_scale", "use_local_location", "use_inherit_rotation", "bbone_segments") if hasattr(bone.bone, field)),
                       tuple((field, _value(getattr(bone, field))) for field in _POSE_FIELDS if hasattr(bone, field))) for bone in rig.pose.bones)
    return (_key(bpy.context.scene), _key(bpy.context.view_layer), getattr(bpy.data, "filepath", None), bpy.context.mode,
            int(bpy.context.scene.frame_current), float(bpy.context.scene.frame_subframe),
            tuple((_key(obj), _key(obj.data), obj.name, _value(obj.matrix_world)) for obj in (rig, mesh)),
            _key(mesh.modifiers[0]), _topology(mesh.data), tuple(_vec(vertex.co) for vertex in mesh.data.vertices), groups,
            tuple(tuple((item.group, float(item.weight)) for item in vertex.groups) for vertex in mesh.data.vertices),
            rest_pose, _constraints(rig), None if target is None else (_key(target), target.name, _value(target.matrix_world), _key(tip)))


def _joint(bone: Any, evaluated: Any, matrix: Any, world: bool) -> dict[str, Any]:
    posed = evaluated.pose.bones.get(bone.name)
    if posed is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Evaluated pose is missing an explicit bone.")
    head, tail = _point(matrix, posed.head, world), _point(matrix, posed.tail, world)
    angle = None
    if posed.parent is not None:
        parent_axis = _minus(_point(matrix, posed.parent.tail, world), _point(matrix, posed.parent.head, world))
        axis = _minus(tail, head)
        denominator = _length(parent_axis) * _length(axis)
        if denominator > _EPSILON:
            cosine = sum(a*b for a, b in zip(parent_axis, axis, strict=True)) / denominator
            angle = math.acos(max(-1., min(1., cosine)))
    limits = {axis: {"enabled": bool(getattr(bone, f"use_ik_limit_{axis}")), "minimum_radians": float(getattr(bone, f"ik_min_{axis}")),
                     "maximum_radians": float(getattr(bone, f"ik_max_{axis}")), "locked": bool(getattr(bone, f"lock_ik_{axis}"))} for axis in "xyz"}
    if not math.isfinite(bone.bone.length) or any(not math.isfinite(item[key]) for item in limits.values() for key in ("minimum_radians", "maximum_radians")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rest length and native IK limit observations must be finite.")
    return {"name": bone.name, "parent": None if bone.parent is None else bone.parent.name,
            "use_deform": bool(bone.bone.use_deform), "head": list(head), "tail": list(tail),
            "evaluated_length": _length(_minus(tail, head)), "rest_length_armature_local": float(bone.bone.length),
            "degenerate_rest": bone.bone.length <= _EPSILON, "degenerate_pose": _length(_minus(tail, head)) <= _EPSILON,
            "unsigned_parent_axis_angle_radians": angle, "stored_ik_limits": limits,
            "ik_limit_satisfaction_assessed": False}


def deformation_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "mesh_object", "bone_names", "vertex_indices", "coordinate_space", "target_object", "tip_bone_name", "max_influences", "weight_tolerance"})
    space = params.get("coordinate_space")
    if not isinstance(space, str) or space not in {"LOCAL", "WORLD"}:
        raise invalid_argument("coordinate_space must explicitly be LOCAL or WORLD.")
    indices = params.get("vertex_indices")
    if not isinstance(indices, list) or not 1 <= len(indices) <= 256 or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in indices) or len(set(indices)) != len(indices):
        raise invalid_argument("vertex_indices must contain one to 256 distinct nonnegative integers.")
    max_influences = int_param(params, "max_influences", 4, minimum=1, maximum=16)
    tolerance = float_param(params, "weight_tolerance", 0.0001, minimum=0.0, maximum=0.1)
    bpy = require_blender()
    scope = _source(bpy, params)
    frozen = _snapshot(bpy, scope)

    def stable(*, callback: bool = True) -> tuple[Any, Any, list[Any], Any, Any]:
        if callback and context.check_cancelled:
            context.check_cancelled()
        context.require(Permission.INSPECT_SCENE)
        current = _source(bpy, params)
        if _snapshot(bpy, current) != frozen:
            raise invalid_argument("Deformation source, frame, identity or pose changed during inspection; remeasure.")
        return current

    rig, mesh, bones, target, tip = stable()
    if max(indices) >= len(mesh.data.vertices):
        raise invalid_argument("A requested vertex index is outside the base mesh.")
    groups = {group.index: group for group in mesh.vertex_groups}
    deform_names = {bone.name for bone in rig.data.bones if bone.use_deform}
    all_bone_names = {bone.name for bone in rig.data.bones}
    if len(groups) != len(mesh.vertex_groups):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Vertex-group indices are ambiguous.")
    weights = []
    for index in indices:
        membership = []
        seen = set()
        for item in mesh.data.vertices[index].groups:
            if item.group in seen or item.group not in groups or not math.isfinite(item.weight) or not 0 <= item.weight <= 1:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Sampled weight membership is invalid or nonfinite.")
            seen.add(item.group)
            group = groups[item.group]
            membership.append({"group": group.name, "weight": float(item.weight), "deforming": group.name in deform_names, "locked": bool(group.lock_weight)})
        deform = [item for item in membership if item["deforming"]]
        total = sum(item["weight"] for item in deform)
        count = sum(item["weight"] > tolerance for item in deform)
        weights.append({"vertex_index": index, "memberships": membership, "deform_weight_sum": total,
                        "unweighted": total <= tolerance, "deform_sum_differs_from_one": abs(total-1.0) > tolerance,
                        "deform_influence_count_above_tolerance": count, "exceeds_declared_influence_limit": count > max_influences})
    bpy.context.view_layer.update()
    stable()
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated_rig, evaluated_mesh = rig.evaluated_get(graph), mesh.evaluated_get(graph)
    failure: Exception | None = None
    try:
        geometry = evaluated_mesh.to_mesh()
        if geometry is None or _topology(geometry) != _topology(mesh.data):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Evaluated skin topology differs from the base mesh; vertex correspondence is not inferred.")
        world = space == "WORLD"
        base_points = [_point(mesh.matrix_world, vertex.co, world) for vertex in mesh.data.vertices]
        evaluated_points = [_point(evaluated_mesh.matrix_world, vertex.co, world) for vertex in geometry.vertices]
        mesh.data.calc_loop_triangles()
        triangles = tuple(tuple(item.vertices) for item in mesh.data.loop_triangles)
        if len(triangles) > MAX_LOOPS or any(len(triangle) != 3 or any(index < 0 or index >= len(base_points) for index in triangle) for triangle in triangles):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native base triangulation is invalid or exceeds 16384 triangles.")
        base_areas = [_triangle_area(base_points, triangle) for triangle in triangles]
        evaluated_areas = [_triangle_area(evaluated_points, triangle) for triangle in triangles]
        samples = [{"vertex_index": index, "base": list(base_points[index]), "evaluated": list(evaluated_points[index]),
                    "displacement": list(_minus(evaluated_points[index], base_points[index])),
                    "displacement_length": _length(_minus(evaluated_points[index], base_points[index]))} for index in indices]
        ratios, zero_base_edges, collapsed_edges = [], 0, 0
        for edge in mesh.data.edges:
            left, right = edge.vertices
            before = _length(_minus(base_points[left], base_points[right]))
            after = _length(_minus(evaluated_points[left], evaluated_points[right]))
            zero_base_edges += int(before <= _EPSILON)
            collapsed_edges += int(after <= _EPSILON)
            if before > _EPSILON:
                ratios.append(after / before)
        joints = [_joint(bone, evaluated_rig, evaluated_rig.matrix_world, world) for bone in bones]
        endpoint = None
        if target is not None:
            evaluated_target = target.evaluated_get(graph)
            evaluated_tip = evaluated_rig.pose.bones.get(tip.name)
            if evaluated_tip is None:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Evaluated endpoint bone is missing.")
            tip_world = _point(evaluated_rig.matrix_world, evaluated_tip.tail, True)
            target_world = _vec(evaluated_target.matrix_world.translation)
            endpoint = {"tip_bone_name": tip.name, "target_object": target.name, "coordinate_space": "WORLD",
                        "tip": list(tip_world), "target": list(target_world), "distance": _length(_minus(tip_world, target_world))}
    except Exception as error:
        failure = error
        raise
    finally:
        try:
            evaluated_mesh.to_mesh_clear()
        except Exception as cleanup:
            LOGGER.exception("Temporary evaluated deformation mesh cleanup failed")
            if failure is None:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Temporary evaluated deformation mesh could not be released.", {"evaluated_mesh_release_failed": True}) from cleanup
            raise BridgeError(failure.code if isinstance(failure, BridgeError) else ErrorCode.OPERATION_FAILED,
                              failure.message if isinstance(failure, BridgeError) else "Deformation inspection failed.",
                              {**(failure.context if isinstance(failure, BridgeError) else {}), "evaluated_mesh_release_failed": True,
                               "primary_exception_type": type(failure).__name__}) from failure
    stable(callback=False)
    return {"object": rig.name, "mesh_object": mesh.name, "frame": int(bpy.context.scene.frame_current), "subframe": float(bpy.context.scene.frame_subframe),
            "geometry_coordinate_space": "WORLD" if world else "MESH_LOCAL", "bone_coordinate_space": "WORLD" if world else "ARMATURE_LOCAL",
            "sampled_vertex_count": len(indices), "sampled_bone_count": len(bones), "complete_weight_coverage": len(indices) == len(mesh.data.vertices),
            "vertex_samples": samples, "weights": weights, "bones": joints, "endpoint_target": endpoint,
            "unmatched_groups": sorted(group.name for group in mesh.vertex_groups if group.name not in all_bone_names),
            "nondeforming_bone_groups": sorted(group.name for group in mesh.vertex_groups if group.name in all_bone_names - deform_names),
            "topology_correspondence_verified": True, "base_vertex_count": len(base_points), "edge_length_ratio": {
                "minimum": min(ratios) if ratios else None, "maximum": max(ratios) if ratios else None,
                "mean": sum(ratios)/len(ratios) if ratios else None, "measured_edge_count": len(ratios),
                "degenerate_base_edge_count": zero_base_edges, "degenerate_evaluated_edge_count": collapsed_edges},
            "max_influences": max_influences, "weight_tolerance": tolerance,
            "base_triangulation_area": {"triangle_count": len(triangles), "base_total": sum(base_areas), "evaluated_total": sum(evaluated_areas),
                                        "degenerate_base_triangle_count": sum(area <= _EPSILON for area in base_areas),
                                        "degenerate_evaluated_triangle_count": sum(area <= _EPSILON for area in evaluated_areas)},
            "full_dependency_graph_verified": False,
            "quality_verdict": "NOT_ASSESSED", "visual_verification_required": True,
            "limitations": ["Current frame only; no timeline, modifier, weight or pose changes.",
                            "Deform-only weight sums are observations, not proof of poor Blender deformation.",
                            "Stored native IK limits and unsigned joint angles do not certify solver limit satisfaction.",
                            "Base topology correspondence does not prove collision-free or artistically acceptable skinning."],
            "project_saved": False}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("rig.deformation_inspect", deformation_inspect, toolset="rigging", modifies=False,
                      permissions=(Permission.INSPECT_SCENE,), description="Measure current-frame evaluated pose/skin, deform weights, edge strain and stored IK limits; no quality verdict.")
