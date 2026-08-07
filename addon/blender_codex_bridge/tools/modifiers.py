"""Structured object modifier inspection and editing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import clear_selection_references
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, preserved_object_context, require_blender
from ._rna import (
    apply_assignments,
    bounded_name,
    prepare_assignments,
    serialize_properties,
    settings_mapping,
)

_MAX_MODIFIERS = 100
_COMMON_PROPERTIES = frozenset(
    {
        "show_viewport",
        "show_render",
        "show_in_editmode",
        "show_on_cage",
        "show_expanded",
    }
)
_PROPERTIES: dict[str, frozenset[str]] = {
    "ARMATURE": frozenset(
        {
            "object",
            "vertex_group",
            "invert_vertex_group",
            "use_deform_preserve_volume",
            "use_vertex_groups",
            "use_bone_envelopes",
        }
    ),
    "ARRAY": frozenset(
        {
            "count",
            "fit_type",
            "use_relative_offset",
            "relative_offset_displace",
            "use_constant_offset",
            "constant_offset_displace",
            "use_object_offset",
            "offset_object",
            "use_merge_vertices",
            "use_merge_vertices_cap",
            "merge_threshold",
            "start_cap",
            "end_cap",
        }
    ),
    "BEVEL": frozenset(
        {
            "width",
            "segments",
            "limit_method",
            "angle_limit",
            "affect",
            "profile",
            "use_clamp_overlap",
            "loop_slide",
            "miter_outer",
            "miter_inner",
            "material",
        }
    ),
    "BOOLEAN": frozenset({"operation", "solver", "operand_type", "object"}),
    "BUILD": frozenset({"frame_start", "frame_duration", "use_reverse", "use_random_order", "seed"}),
    "CAST": frozenset(
        {
            "cast_type",
            "factor",
            "radius",
            "size",
            "use_radius_as_size",
            "use_transform",
            "object",
            "use_x",
            "use_y",
            "use_z",
            "vertex_group",
            "invert_vertex_group",
        }
    ),
    "CURVE": frozenset({"object", "deform_axis", "vertex_group"}),
    "DECIMATE": frozenset(
        {
            "ratio",
            "decimate_type",
            "angle_limit",
            "use_collapse_triangulate",
            "use_dissolve_boundaries",
            "symmetry_axis",
            "use_symmetry",
            "vertex_group",
            "vertex_group_factor",
            "invert_vertex_group",
        }
    ),
    "DISPLACE": frozenset(
        {"strength", "mid_level", "direction", "space", "vertex_group", "texture_coords", "uv_layer", "texture_coords_object"}
    ),
    "EDGE_SPLIT": frozenset({"split_angle", "use_edge_angle", "use_edge_sharp"}),
    "LATTICE": frozenset({"object", "strength", "vertex_group", "invert_vertex_group"}),
    "MASK": frozenset({"mode", "vertex_group", "armature", "invert_vertex_group", "threshold"}),
    "MESH_DEFORM": frozenset({"object", "precision", "use_dynamic_bind", "vertex_group", "invert_vertex_group"}),
    "MIRROR": frozenset(
        {
            "use_axis",
            "use_bisect_axis",
            "use_bisect_flip_axis",
            "use_clip",
            "use_mirror_merge",
            "merge_threshold",
            "mirror_object",
            "use_mirror_u",
            "use_mirror_v",
            "offset_u",
            "offset_v",
        }
    ),
    "NODES": frozenset(),
    "NORMAL_EDIT": frozenset(
        {"mode", "target", "offset", "mix_mode", "mix_factor", "mix_limit", "no_polynors_fix", "vertex_group", "invert_vertex_group"}
    ),
    "REMESH": frozenset(
        {"mode", "octree_depth", "scale", "sharpness", "use_smooth_shade", "use_remove_disconnected", "threshold"}
    ),
    "SCREW": frozenset(
        {"object", "angle", "steps", "render_steps", "screw_offset", "iterations", "axis", "use_merge_vertices", "merge_threshold", "use_normal_calculate", "use_normal_flip", "use_stretch_u", "use_stretch_v"}
    ),
    "SHRINKWRAP": frozenset(
        {"target", "auxiliary_target", "wrap_method", "wrap_mode", "offset", "project_limit", "use_project_x", "use_project_y", "use_project_z", "use_negative_direction", "use_positive_direction", "cull_face", "vertex_group", "invert_vertex_group"}
    ),
    "SIMPLE_DEFORM": frozenset(
        {"deform_method", "deform_axis", "factor", "angle", "limits", "lock_x", "lock_y", "lock_z", "origin", "vertex_group", "invert_vertex_group"}
    ),
    "SMOOTH": frozenset({"factor", "iterations", "use_x", "use_y", "use_z", "vertex_group", "invert_vertex_group"}),
    "SOLIDIFY": frozenset(
        {"thickness", "offset", "use_even_offset", "use_quality_normals", "material_offset", "material_offset_rim", "use_rim", "use_rim_only", "vertex_group", "invert_vertex_group"}
    ),
    "SUBSURF": frozenset(
        {"levels", "render_levels", "subdivision_type", "use_limit_surface", "uv_smooth", "show_only_control_edges", "boundary_smooth"}
    ),
    "TRIANGULATE": frozenset({"quad_method", "ngon_method", "min_vertices", "keep_custom_normals"}),
    "UV_WARP": frozenset(
        {"object_from", "object_to", "bone_from", "bone_to", "center", "axis_u", "axis_v", "uv_layer", "vertex_group", "invert_vertex_group"}
    ),
    "WARP": frozenset(
        {"object_from", "object_to", "strength", "falloff_type", "falloff_radius", "texture_coords", "uv_layer", "texture_coords_object", "vertex_group", "invert_vertex_group"}
    ),
    "WAVE": frozenset(
        {"use_x", "use_y", "use_cyclic", "use_normal", "use_normal_x", "use_normal_y", "use_normal_z", "time_offset", "lifetime", "damping_time", "falloff_radius", "start_position_x", "start_position_y", "height", "width", "narrowness", "speed", "vertex_group", "texture_coords", "uv_layer", "texture_coords_object"}
    ),
    "WIREFRAME": frozenset(
        {"thickness", "offset", "use_replace", "use_even_offset", "use_relative_offset", "use_boundary", "material_offset", "crease_weight", "use_crease", "vertex_group", "invert_vertex_group"}
    ),
}
_OBJECT_POINTERS = frozenset(
    {
        "armature",
        "auxiliary_target",
        "end_cap",
        "mirror_object",
        "object",
        "object_from",
        "object_to",
        "offset_object",
        "origin",
        "start_cap",
        "target",
        "texture_coords_object",
    }
)


def _allowed(modifier_type: str) -> frozenset[str]:
    try:
        return _COMMON_PROPERTIES | _PROPERTIES[modifier_type]
    except KeyError as exc:
        raise invalid_argument(
            f"Modifier type '{modifier_type}' is not available through the structured tool.",
            modifier_type=modifier_type,
            supported_types=sorted(_PROPERTIES),
        ) from exc


def _object(params: Mapping[str, Any]) -> Any:
    return get_object(params.get("object_name"), allow_active=False)


def _named_modifier(obj: Any, raw_name: Any) -> Any:
    name = bounded_name(raw_name, "modifier_name")
    modifier = obj.modifiers.get(name)
    if modifier is None:
        raise invalid_argument(
            f"Object '{obj.name}' has no modifier named '{name}'.",
            object=obj.name,
            modifier_name=name,
            available_modifiers=[item.name for item in obj.modifiers[:_MAX_MODIFIERS]],
        )
    return modifier


def _summary(modifier: Any) -> dict[str, Any]:
    specific = _PROPERTIES.get(str(modifier.type))
    allowed = _COMMON_PROPERTIES | (specific or frozenset())
    return {
        "name": modifier.name,
        "type": modifier.type,
        "structured_settings_supported": specific is not None,
        "settings": serialize_properties(modifier, allowed),
    }


def inspect_modifiers(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = _object(params)
    raw_name = params.get("modifier_name")
    if raw_name is not None:
        modifier = _named_modifier(obj, raw_name)
        return {"object": obj.name, "modifier": _summary(modifier)}
    total = len(obj.modifiers)
    modifiers = [_summary(item) for item in obj.modifiers[:_MAX_MODIFIERS]]
    return {
        "object": obj.name,
        "modifier_count": total,
        "modifiers": modifiers,
        "truncated": total > len(modifiers),
        "maximum_returned": _MAX_MODIFIERS,
    }


def add_modifier(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _object(params)
    modifier_type = bounded_name(params.get("modifier_type"), "modifier_type", maximum=64).upper()
    allowed = _allowed(modifier_type)
    requested_name = params.get("modifier_name")
    name = (
        bounded_name(requested_name, "modifier_name")
        if requested_name is not None
        else modifier_type.replace("_", " ").title()
    )
    if len(obj.modifiers) >= _MAX_MODIFIERS:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            f"Object '{obj.name}' has reached the structured modifier limit.",
            {"maximum_modifiers": _MAX_MODIFIERS},
        )
    settings = settings_mapping(params, required=False)
    try:
        modifier = obj.modifiers.new(name=name, type=modifier_type)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            f"Blender could not create a {modifier_type} modifier.",
            {"object": obj.name, "modifier_type": modifier_type},
        ) from exc
    try:
        assignments = prepare_assignments(
            modifier,
            settings,
            allowed=allowed,
            object_pointers=_OBJECT_POINTERS,
            bpy=bpy,
        )
        apply_assignments(modifier, assignments)
    except Exception:
        obj.modifiers.remove(modifier)
        raise
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "created": _summary(modifier),
        "modifier_count_after": len(obj.modifiers),
    }


def set_modifier(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _object(params)
    modifier = _named_modifier(obj, params.get("modifier_name"))
    assignments = prepare_assignments(
        modifier,
        settings_mapping(params),
        allowed=_allowed(str(modifier.type)),
        object_pointers=_OBJECT_POINTERS,
        bpy=bpy,
    )
    apply_assignments(modifier, assignments)
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "modifier": _summary(modifier),
        "updated_properties": [item.name for item in assignments],
    }


def remove_modifier(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = _object(params)
    modifier = _named_modifier(obj, params.get("modifier_name"))
    removed = {"name": modifier.name, "type": modifier.type}
    try:
        obj.modifiers.remove(modifier)
    except (ReferenceError, RuntimeError) as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not remove the requested modifier.",
            {"object": obj.name, "modifier": removed["name"]},
        ) from exc
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "removed": removed,
        "modifier_count_after": len(obj.modifiers),
    }


def apply_modifier(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _object(params)
    modifier = _named_modifier(obj, params.get("modifier_name"))
    if obj.mode != "OBJECT":
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "Applying a modifier requires the explicit target object to be in Object Mode.",
            {"object": obj.name, "current_mode": obj.mode, "required_mode": "OBJECT"},
        )
    if obj.name not in bpy.context.view_layer.objects:
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            f"Object '{obj.name}' is not in the active view layer.",
        )
    applied = {"name": modifier.name, "type": modifier.type}
    try:
        with preserved_object_context():
            for selected in list(bpy.context.selected_objects):
                selected.select_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            if not bpy.ops.object.modifier_apply.poll():
                raise BridgeError(
                    ErrorCode.BLENDER_CONTEXT_ERROR,
                    "Blender's modifier apply operation is unavailable in the current context.",
                    {"object": obj.name, "modifier": modifier.name},
                )
            result = bpy.ops.object.modifier_apply(modifier=modifier.name)
            if "FINISHED" not in result:
                raise BridgeError(
                    ErrorCode.OPERATION_FAILED,
                    "Blender canceled the requested modifier apply operation.",
                    {"object": obj.name, "modifier": modifier.name},
                )
    except BridgeError:
        raise
    except RuntimeError as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not apply the requested modifier.",
            {"object": obj.name, "modifier": applied["name"]},
        ) from exc
    if obj.type == "MESH":
        clear_selection_references(obj.name)
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "applied": applied,
        "modifier_count_after": len(obj.modifiers),
        "remaining_modifiers": [item.name for item in obj.modifiers[:_MAX_MODIFIERS]],
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "modifier.inspect",
        inspect_modifiers,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="modifiers",
        description="Inspect bounded, allowlisted modifier settings for an explicit object.",
    )
    modifying = {
        "permissions": (Permission.TRANSFORM_OBJECTS,),
        "toolset": "modifiers",
        "modifies": True,
    }
    registry.register("modifier.add", add_modifier, description="Add and configure an allowlisted modifier.", **modifying)
    registry.register("modifier.set", set_modifier, description="Set direct allowlisted RNA properties on one modifier.", **modifying)
    registry.register("modifier.remove", remove_modifier, description="Remove one explicitly named modifier.", **modifying)
    registry.register("modifier.apply", apply_modifier, description="Apply one modifier in a validated Object Mode context.", **modifying)


__all__ = [
    "add_modifier",
    "apply_modifier",
    "inspect_modifiers",
    "register_tools",
    "remove_modifier",
    "set_modifier",
]
