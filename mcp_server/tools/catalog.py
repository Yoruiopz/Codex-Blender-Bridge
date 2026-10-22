"""Metadata used by the lazy registry independently of MCP SDK registration."""

from __future__ import annotations

from ..tool_registry import ToolDefinition, remote_tool
from .animation import (
    ANIMATION_TOOL_DATA,
)
from .animation import (
    load_animation_definitions as _load_base_animation_definitions,
)
from .animation_curves import TOOL_DATA as ANIMATION_CURVE_TOOL_DATA
from .animation_curves import load_definitions as _load_animation_curve_definitions
from .animation_lifecycle import DESTRUCTIVE_TOOL_NAMES as ACTION_DESTRUCTIVE_TOOL_NAMES
from .animation_lifecycle import TOOL_DATA as ACTION_LIFECYCLE_TOOL_DATA
from .animation_lifecycle import load_definitions as _load_action_lifecycle_definitions
from .artist import TOOL_DATA as _BASE_ARTIST_TOOL_DATA
from .artist import load_definitions as _load_base_artist_definitions
from .asset_delivery import TOOL_DATA as BASE_ASSET_DELIVERY_TOOL_DATA
from .asset_delivery import load_definitions as _load_base_asset_delivery_definitions
from .asset_import import DESTRUCTIVE_TOOL_NAMES as ASSET_IMPORT_DESTRUCTIVE_TOOL_NAMES
from .asset_import import TOOL_DATA as ASSET_IMPORT_TOOL_DATA
from .asset_import import load_definitions as _load_asset_import_definitions
from .batch import TOOL_DATA as BATCH_TOOL_DATA
from .batch import TOOL_NAMES as BATCH_TOOL_NAMES
from .batch import load_definitions as load_batch_definitions
from .constraints import (
    DESTRUCTIVE_TOOL_NAMES as CONSTRAINT_DESTRUCTIVE_TOOL_NAMES,
)
from .constraints import TOOL_DATA as CONSTRAINT_TOOL_DATA
from .constraints import TOOL_NAMES as CONSTRAINT_TOOL_NAMES
from .constraints import load_definitions as load_constraint_definitions
from .deformation import TOOL_DATA as DEFORMATION_TOOL_DATA
from .deformation import load_definitions as _load_deformation_definitions
from .geometry_node_groups import DESTRUCTIVE_TOOL_NAMES as GEOMETRY_GROUP_DESTRUCTIVE_TOOL_NAMES
from .geometry_node_groups import TOOL_DATA as GEOMETRY_GROUP_TOOL_DATA
from .geometry_node_groups import load_definitions as _load_geometry_group_definitions
from .geometry_nodes import DESTRUCTIVE_TOOL_NAMES as GEOMETRY_DESTRUCTIVE_TOOL_NAMES
from .geometry_nodes import TOOL_DATA as GEOMETRY_TOOL_DATA
from .geometry_nodes import load_definitions as _load_base_geometry_definitions
from .geometry_zone_lifecycle import DESTRUCTIVE_TOOL_NAMES as GEOMETRY_ZONE_DESTRUCTIVE_TOOL_NAMES
from .geometry_zone_lifecycle import TOOL_DATA as GEOMETRY_ZONE_TOOL_DATA
from .geometry_zone_lifecycle import load_definitions as _load_geometry_zone_definitions
from .image_portability import TOOL_DATA as IMAGE_PORTABILITY_TOOL_DATA
from .image_portability import load_definitions as _load_image_portability_definitions
from .image_recovery import DESTRUCTIVE_TOOL_NAMES as IMAGE_RECOVERY_DESTRUCTIVE_TOOL_NAMES
from .image_recovery import TOOL_DATA as IMAGE_RECOVERY_TOOL_DATA
from .image_recovery import load_definitions as _load_image_recovery_definitions
from .image_recovery_jobs import DESTRUCTIVE_TOOL_NAMES as IMAGE_RECOVERY_JOB_DESTRUCTIVE_TOOL_NAMES
from .image_recovery_jobs import TOOL_DATA as IMAGE_RECOVERY_JOB_TOOL_DATA
from .image_recovery_jobs import load_definitions as _load_image_recovery_job_definitions
from .image_surface_paint import TOOL_DATA as IMAGE_SURFACE_PAINT_TOOL_DATA
from .image_surface_paint import load_definitions as _load_image_surface_paint_definitions
from .interaction import TOOL_DATA as INTERACTION_TOOL_DATA
from .interaction import TOOL_NAMES as INTERACTION_TOOL_NAMES
from .interaction import load_definitions as load_interaction_definitions
from .layout import LAYOUT_TOOL_DATA, LAYOUT_TOOL_NAMES
from .layout import load_definitions as load_layout_definitions
from .materials import (
    MATERIAL_TOOL_DATA,
)
from .materials import (
    load_material_definitions as _load_base_material_definitions,
)
from .mesh_slide import TOOL_DATA as MESH_SLIDE_TOOL_DATA
from .mesh_slide import load_definitions as _load_mesh_slide_definitions
from .mesh_surface import TOOL_DATA as MESH_SURFACE_TOOL_DATA
from .mesh_surface import load_definitions as _load_mesh_surface_definitions
from .modifiers import DESTRUCTIVE_TOOL_NAMES as MODIFIER_DESTRUCTIVE_TOOL_NAMES
from .modifiers import TOOL_DATA as MODIFIER_TOOL_DATA
from .modifiers import TOOL_NAMES as MODIFIER_TOOL_NAMES
from .modifiers import load_definitions as load_modifier_definitions
from .nla_lifecycle import DESTRUCTIVE_TOOL_NAMES as NLA_DESTRUCTIVE_TOOL_NAMES
from .nla_lifecycle import TOOL_DATA as NLA_TOOL_DATA
from .nla_lifecycle import load_definitions as _load_nla_definitions
from .nodes import NODE_TOOL_DATA, NODE_TOOL_NAMES, load_node_definitions
from .python_exec import PYTHON_TOOL_NAMES
from .python_exec import load_definitions as load_python_definitions
from .render import RENDER_TOOL_DATA, RENDER_TOOL_NAMES
from .render import load_definitions as load_render_definitions
from .rig_drivers import DESTRUCTIVE_TOOL_NAMES as RIG_DRIVER_DESTRUCTIVE_TOOL_NAMES
from .rig_drivers import TOOL_DATA as RIG_DRIVER_TOOL_DATA
from .rig_drivers import load_definitions as _load_rig_driver_definitions
from .rig_ik import DESTRUCTIVE_TOOL_NAMES as RIG_IK_DESTRUCTIVE_TOOL_NAMES
from .rig_ik import TOOL_DATA as RIG_IK_TOOL_DATA
from .rig_ik import load_definitions as _load_rig_ik_definitions
from .rigging import RIGGING_TOOL_DATA
from .rigging import load_rigging_definitions as _load_base_rigging_definitions
from .rigid_body import TOOL_DATA as RIGID_BODY_TOOL_DATA
from .rigid_body import load_definitions as _load_rigid_body_definitions
from .scene_edit import SCENE_EDIT_TOOL_DATA as BASE_SCENE_EDIT_TOOL_DATA
from .scene_edit import load_definitions as _load_base_scene_edit_definitions
from .scene_variants import TOOL_DATA as SCENE_VARIANT_TOOL_DATA
from .scene_variants import load_definitions as _load_scene_variant_definitions
from .surface_brushes import TOOL_DATA as SURFACE_BRUSH_TOOL_DATA
from .surface_brushes import load_definitions as _load_surface_brush_definitions
from .task_plan import TOOL_DATA as TASK_PLAN_TOOL_DATA
from .task_plan import load_definitions as _load_task_plan_definitions
from .uv import DESTRUCTIVE_TOOL_NAMES as UV_DESTRUCTIVE_TOOL_NAMES
from .uv import TOOL_DATA as UV_TOOL_DATA
from .uv import load_definitions as _load_base_uv_definitions
from .uv_refine import TOOL_DATA as UV_REFINE_TOOL_DATA
from .uv_refine import load_definitions as _load_uv_refine_definitions
from .weight_brushes import TOOL_DATA as WEIGHT_BRUSH_TOOL_DATA
from .weight_brushes import load_definitions as _load_weight_brush_definitions

ARTIST_TOOL_DATA = (*_BASE_ARTIST_TOOL_DATA, *((name, "weights", True, ("EDIT_MESH",), description)
                                       for name, description in WEIGHT_BRUSH_TOOL_DATA),
                    *((name, "animation_layers", modifies, permissions, description)
                      for name, description, modifies, permissions in NLA_TOOL_DATA),
                    *((name, "simulation", modifies, permissions, description)
                      for name, description, modifies, permissions in RIGID_BODY_TOOL_DATA))


def load_artist_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_artist_definitions(), *_load_weight_brush_definitions(), *_load_nla_definitions(), *_load_rigid_body_definitions())

ASSET_DELIVERY_TOOL_DATA = (*BASE_ASSET_DELIVERY_TOOL_DATA, *ASSET_IMPORT_TOOL_DATA)
ASSET_DELIVERY_TOOL_NAMES = tuple(item[0] for item in ASSET_DELIVERY_TOOL_DATA)


def load_asset_delivery_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_asset_delivery_definitions(), *_load_asset_import_definitions())

ANIMATION_TOOL_DATA = (*ANIMATION_TOOL_DATA, *((name, description, True, ("EDIT_ANIMATION",))
                                           for name, description in ANIMATION_CURVE_TOOL_DATA), *ACTION_LIFECYCLE_TOOL_DATA)
ANIMATION_TOOL_NAMES = tuple(item[0] for item in ANIMATION_TOOL_DATA)
GEOMETRY_TOOL_DATA = (*GEOMETRY_TOOL_DATA, *GEOMETRY_GROUP_TOOL_DATA, *GEOMETRY_ZONE_TOOL_DATA)
GEOMETRY_TOOL_NAMES = tuple(item[0] for item in GEOMETRY_TOOL_DATA)
MATERIAL_TOOL_DATA = (*MATERIAL_TOOL_DATA, *IMAGE_PORTABILITY_TOOL_DATA, *IMAGE_SURFACE_PAINT_TOOL_DATA, *IMAGE_RECOVERY_TOOL_DATA, *IMAGE_RECOVERY_JOB_TOOL_DATA)
MATERIAL_TOOL_NAMES = tuple(item[0] for item in MATERIAL_TOOL_DATA)
SCENE_EDIT_TOOL_DATA = (*BASE_SCENE_EDIT_TOOL_DATA, *SCENE_VARIANT_TOOL_DATA)
SCENE_EDIT_TOOL_NAMES = tuple(item[0] for item in SCENE_EDIT_TOOL_DATA)
RIGGING_TOOL_DATA = (*RIGGING_TOOL_DATA, *RIG_DRIVER_TOOL_DATA, *RIG_IK_TOOL_DATA, *DEFORMATION_TOOL_DATA)
RIGGING_TOOL_NAMES = tuple(item[0] for item in RIGGING_TOOL_DATA)
UV_TOOL_DATA = (*UV_TOOL_DATA, *((name, description, modifies)
                               for name, description, modifies, _ in UV_REFINE_TOOL_DATA))
UV_TOOL_NAMES = tuple(item[0] for item in UV_TOOL_DATA)


def load_rigging_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_rigging_definitions(), *_load_rig_driver_definitions(), *_load_rig_ik_definitions(), *_load_deformation_definitions())


def load_uv_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_uv_definitions(), *_load_uv_refine_definitions())


def load_animation_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_animation_definitions(), *_load_animation_curve_definitions(), *_load_action_lifecycle_definitions())


def load_geometry_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_geometry_definitions(), *_load_geometry_group_definitions(), *_load_geometry_zone_definitions())


def load_material_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_material_definitions(), *_load_image_portability_definitions(), *_load_image_surface_paint_definitions(), *_load_image_recovery_definitions(), *_load_image_recovery_job_definitions())


def load_scene_edit_definitions() -> tuple[ToolDefinition, ...]:
    return (*_load_base_scene_edit_definitions(), *_load_scene_variant_definitions())

CORE_REMOTE_TOOLS: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("jobs.inspect", "Inspect session-local image-job progress, result/error and file/recovery evidence.", False, ("INSPECT_SCENE",)),
    ("jobs.list", "List bounded session-local image jobs; no durable queue.", False, ("INSPECT_SCENE",)),
    ("jobs.cancel", "Request safe-point image-job cancellation, not rollback; available while paused.", False, ()),
    ("bridge.status", "Report Blender bridge, project, mode, and permission status.", False, ()),
    ("bridge.task.set", "Show the current high-level Codex task in Blender's UI.", False, ()),
    ("bridge.task.clear", "Clear the current high-level task from Blender's UI.", False, ()),
    ("project.info", "Inspect project metadata and render settings.", False, ("INSPECT_SCENE",)),
    ("scene.inspect", "Return a compact authoritative structural scene representation.", False, ("INSPECT_SCENE",)),
    ("scene.summary", "Return an LLM-oriented structural and textual scene summary.", False, ("INSPECT_SCENE",)),
    ("scene.snapshot", "Capture bounded structural evidence for explicitly named objects and fields.", False, ("INSPECT_SCENE",)),
    ("scene.compare", "Compare current measured object fields with a session snapshot; report incomplete coverage.", False, ("INSPECT_SCENE",)),
    ("selection.inspect", "Inspect active and selected objects or mesh elements.", False, ("INSPECT_SCENE",)),
    ("object.inspect", "Inspect one object without dumping raw vertex coordinates.", False, ("INSPECT_SCENE",)),
    (
        "viewport.capture",
        "Capture a viewport image; temporary settings are restored but Render Result is replaced.",
        True,
        ("CAPTURE_VIEWPORT",),
    ),
    ("checkpoint.create", "Create a logical agent undo checkpoint.", True, ()),
    (
        "checkpoint.undo_last",
        "Use Blender global undo only with explicit acknowledgement of user-interleaving risk.",
        True,
        (),
    ),
    ("checkpoint.list", "List checkpoint labels, operation history and conservative recovery availability.", False, ()),
    ("project.save", "Project saving is unavailable until native save side effects can be bounded.", True, ("SAVE_PROJECT",)),
)

LOCAL_TOOLSET_TOOLS: tuple[tuple[str, str, bool], ...] = (
    ("toolsets.list", "List local MCP toolsets and their enablement state.", False),
    ("toolsets.enable", "Enable a lazy local MCP domain toolset.", True),
    ("toolsets.disable", "Disable a local MCP domain toolset.", True),
)

CORE_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(
    remote_tool(
        name,
        description=description,
        modifying=modifying,
        required_permissions=permissions,
    )
    for name, description, modifying, permissions in CORE_REMOTE_TOOLS
) + tuple(
    remote_tool(name, description=description, modifying=modifying)
    for name, description, modifying in LOCAL_TOOLSET_TOOLS
) + _load_task_plan_definitions()

OBJECT_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("object.create", "Create a structured Blender object primitive.", True, ("TRANSFORM_OBJECTS",)),
    ("object.delete", "Delete one object when destructive permission is granted.", True, ("DELETE_OBJECTS",)),
    ("object.duplicate", "Duplicate an object, optionally with linked data.", True, ("TRANSFORM_OBJECTS",)),
    ("object.rename", "Rename an object deterministically.", True, ("TRANSFORM_OBJECTS",)),
    ("object.set_parent", "Set or clear an object's parent.", True, ("TRANSFORM_OBJECTS",)),
    ("object.move_to_collection", "Move or additionally link an object to a collection.", True, ("TRANSFORM_OBJECTS",)),
    ("transform.set", "Set absolute location, rotation, or scale values.", True, ("TRANSFORM_OBJECTS",)),
    ("transform.translate", "Apply a deterministic translation delta.", True, ("TRANSFORM_OBJECTS",)),
    ("transform.rotate", "Apply a deterministic Euler rotation delta in radians.", True, ("TRANSFORM_OBJECTS",)),
    ("transform.scale", "Apply a deterministic multiplicative scale.", True, ("TRANSFORM_OBJECTS",)),
    ("transform.apply", "Apply selected transform components to object data.", True, ("TRANSFORM_OBJECTS", "EDIT_MESH")),
)
OBJECT_TOOL_NAMES = tuple(item[0] for item in OBJECT_TOOL_DATA)

MESH_TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
    ("mesh.set_face_attributes", "Set smooth shading and/or an existing material-slot index on bounded referenced faces; material changes additionally require EDIT_MATERIALS.", True),
    ("mesh.analyze", "Inspect bounded base-mesh topology, adjacent winding and triangle crossing/contact candidates with explicit completeness.", False),
    ("mesh.edge_ring_inspect", "Preview paginated measured edges and expected topology for a complete connected quad ring.", False),
    ("mesh.loop_cut", "Cut the entire connected quad ring with evenly spaced cuts, including unselected faces.", True),
    ("mesh.bridge_loops", "Bridge two referenced closed boundary/wire loops without vertex merging; unequal loops produce triangles.", True),
    ("mesh.subdivide_selected", "Subdivide selected edges without smoothing under a conservative growth budget.", True),
    ("mesh.merge_by_distance", "Weld only selected vertices within an explicit local-space distance.", True),
    ("mesh.fill_holes", "Cap complete disjoint boundary loops with bounded n-gons; new face UVs start at zero.", True),
    ("mesh.mark_seams", "Mark or clear UV seams on selected edges of one local single-user Edit Mode mesh.", True),
    ("mesh.create", "Create a fully prevalidated arbitrary mesh object from bounded topology arrays.", True),
    ("mesh.inspect", "Inspect compact mesh and topology statistics.", False),
    ("mesh.recalculate_normals", "Recalculate normals for the selected mesh region.", True),
    ("mesh.delete_selected", "Delete selected mesh elements.", True),
    ("mesh.dissolve_selected", "Dissolve selected mesh elements.", True),
    ("mesh.extrude_selected", "Extrude the selected mesh region by an explicit offset.", True),
    ("mesh.inset_selected", "Inset selected faces with explicit thickness and depth.", True),
    ("mesh.bevel_selected", "Bevel selected mesh elements with explicit width and segments.", True),
)
MESH_TOOL_DATA = (*MESH_TOOL_DATA, *((name, description, modifies)
    for name, description, modifies, _ in (*MESH_SLIDE_TOOL_DATA, *SURFACE_BRUSH_TOOL_DATA, *MESH_SURFACE_TOOL_DATA)))
MESH_TOOL_NAMES = tuple(item[0] for item in MESH_TOOL_DATA)


def _modifying_four(values: tuple[tuple[str, str, bool, tuple[str, ...]], ...]) -> set[str]:
    return {name for name, _description, modifying, _permissions in values if modifying}


def _modifying_three(values: tuple[tuple[str, str, bool], ...]) -> set[str]:
    return {name for name, _description, modifying in values if modifying}


MODIFYING_TOOL_NAMES = frozenset(
    {name for name, _, modifies, _, _ in ARTIST_TOOL_DATA if modifies}
    | _modifying_four(CORE_REMOTE_TOOLS)
    | _modifying_three(LOCAL_TOOLSET_TOOLS)
    | _modifying_four(OBJECT_TOOL_DATA)
    | _modifying_three(MESH_TOOL_DATA)
    | _modifying_four(MATERIAL_TOOL_DATA)
    | _modifying_four(NODE_TOOL_DATA)
    | _modifying_three(UV_TOOL_DATA)
    | _modifying_three(MODIFIER_TOOL_DATA)
    | _modifying_three(CONSTRAINT_TOOL_DATA)
    | _modifying_four(ANIMATION_TOOL_DATA)
    | _modifying_four(RIGGING_TOOL_DATA)
    | _modifying_four(SCENE_EDIT_TOOL_DATA)
    | _modifying_four(RENDER_TOOL_DATA)
    | set(PYTHON_TOOL_NAMES)
    | _modifying_four(BATCH_TOOL_DATA)
    | _modifying_four(INTERACTION_TOOL_DATA)
    | _modifying_four(LAYOUT_TOOL_DATA)
    | _modifying_four(GEOMETRY_TOOL_DATA)
    | _modifying_four(ASSET_DELIVERY_TOOL_DATA)
    | {name for name, modifying, _permissions, _description in TASK_PLAN_TOOL_DATA if modifying}
)

# MCP annotations are advisory; Blender permissions remain authoritative.  Err
# conservative for operations that delete data, bake/apply state, write files,
# replace Render Result, or execute a broad script.
DESTRUCTIVE_TOOL_NAMES = frozenset(
    {name for name, _, modifies, _, _ in ARTIST_TOOL_DATA if modifies}
    | {
        "checkpoint.undo_last",
        "project.save",
        "asset.export",
        "viewport.capture",
        "object.delete",
        "transform.apply",
        "mesh.delete_selected",
        "mesh.dissolve_selected",
        "mesh.merge_by_distance",
        "mesh.vertex_slide",
        "mesh.edge_slide",
        "mesh.sculpt_brush",
        "mesh.project_to_surface",
        "color_attribute.paint",
        "color_attribute.rename",
        "color_attribute.remove",
        "material.delete",
        "image.remove",
        "image.restore_pixels",
        "shader_group.remove",
        "material.slot_remove",
        "nodes.remove",
        "nodes.set_color_ramp",
        "nodes.unlink",
        "animation.keyframe_delete",
        "rig.bone_remove",
        "rig.constraint_remove",
        "rig.bind_mesh",
        "collection.delete",
        "render.execute",
        "python.execute",
        "batch.execute",
    }
    | set(UV_DESTRUCTIVE_TOOL_NAMES)
    | set(MODIFIER_DESTRUCTIVE_TOOL_NAMES)
    | set(CONSTRAINT_DESTRUCTIVE_TOOL_NAMES)
    | set(GEOMETRY_DESTRUCTIVE_TOOL_NAMES)
    | set(GEOMETRY_GROUP_DESTRUCTIVE_TOOL_NAMES)
    | set(RIG_DRIVER_DESTRUCTIVE_TOOL_NAMES)
    | set(RIG_IK_DESTRUCTIVE_TOOL_NAMES)
    | set(GEOMETRY_ZONE_DESTRUCTIVE_TOOL_NAMES)
    | set(ACTION_DESTRUCTIVE_TOOL_NAMES)
    | set(NLA_DESTRUCTIVE_TOOL_NAMES)
    | set(ASSET_IMPORT_DESTRUCTIVE_TOOL_NAMES)
    | set(IMAGE_RECOVERY_DESTRUCTIVE_TOOL_NAMES)
    | set(IMAGE_RECOVERY_JOB_DESTRUCTIVE_TOOL_NAMES)
    | {name for name, _, modifies, _ in UV_REFINE_TOOL_DATA if modifies}
)


def load_object_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="objects",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in OBJECT_TOOL_DATA
    )


def load_mesh_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="mesh",
            description=description,
            modifying=modifying,
            required_permissions=(
                ("EDIT_MESH", "TRANSFORM_OBJECTS")
                if name == "mesh.create"
                else (("EDIT_MESH",) if modifying else ("INSPECT_SCENE",))
            ),
        )
        for name, description, modifying in MESH_TOOL_DATA
        if name not in {item[0] for item in (*MESH_SLIDE_TOOL_DATA, *SURFACE_BRUSH_TOOL_DATA, *MESH_SURFACE_TOOL_DATA)}
    ) + _load_mesh_slide_definitions() + _load_surface_brush_definitions() + _load_mesh_surface_definitions()


__all__ = [
    "ANIMATION_TOOL_NAMES",
    "ASSET_DELIVERY_TOOL_NAMES",
    "BATCH_TOOL_NAMES",
    "CONSTRAINT_TOOL_NAMES",
    "CORE_DEFINITIONS",
    "DESTRUCTIVE_TOOL_NAMES",
    "GEOMETRY_TOOL_NAMES",
    "INTERACTION_TOOL_NAMES",
    "LAYOUT_TOOL_NAMES",
    "MATERIAL_TOOL_NAMES",
    "MESH_TOOL_NAMES",
    "MODIFIER_TOOL_NAMES",
    "MODIFYING_TOOL_NAMES",
    "NODE_TOOL_NAMES",
    "OBJECT_TOOL_NAMES",
    "PYTHON_TOOL_NAMES",
    "RENDER_TOOL_NAMES",
    "RIGGING_TOOL_NAMES",
    "SCENE_EDIT_TOOL_NAMES",
    "UV_TOOL_NAMES",
    "load_animation_definitions",
    "load_artist_definitions",
    "load_asset_delivery_definitions",
    "load_batch_definitions",
    "load_constraint_definitions",
    "load_geometry_definitions",
    "load_interaction_definitions",
    "load_layout_definitions",
    "load_material_definitions",
    "load_mesh_definitions",
    "load_modifier_definitions",
    "load_node_definitions",
    "load_object_definitions",
    "load_python_definitions",
    "load_render_definitions",
    "load_rigging_definitions",
    "load_scene_edit_definitions",
    "load_uv_definitions",
]
