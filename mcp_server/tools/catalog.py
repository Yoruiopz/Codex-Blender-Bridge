"""Metadata used by the lazy registry independently of MCP SDK registration."""

from __future__ import annotations

from ..tool_registry import ToolDefinition, remote_tool
from .animation import (
    ANIMATION_TOOL_DATA,
    ANIMATION_TOOL_NAMES,
    load_animation_definitions,
)
from .batch import TOOL_DATA as BATCH_TOOL_DATA
from .batch import TOOL_NAMES as BATCH_TOOL_NAMES
from .batch import load_definitions as load_batch_definitions
from .constraints import (
    DESTRUCTIVE_TOOL_NAMES as CONSTRAINT_DESTRUCTIVE_TOOL_NAMES,
)
from .constraints import TOOL_DATA as CONSTRAINT_TOOL_DATA
from .constraints import TOOL_NAMES as CONSTRAINT_TOOL_NAMES
from .constraints import load_definitions as load_constraint_definitions
from .geometry_nodes import DESTRUCTIVE_TOOL_NAMES as GEOMETRY_DESTRUCTIVE_TOOL_NAMES
from .geometry_nodes import TOOL_DATA as GEOMETRY_TOOL_DATA
from .geometry_nodes import TOOL_NAMES as GEOMETRY_TOOL_NAMES
from .geometry_nodes import load_definitions as load_geometry_definitions
from .interaction import TOOL_DATA as INTERACTION_TOOL_DATA
from .interaction import TOOL_NAMES as INTERACTION_TOOL_NAMES
from .interaction import load_definitions as load_interaction_definitions
from .layout import LAYOUT_TOOL_DATA, LAYOUT_TOOL_NAMES
from .layout import load_definitions as load_layout_definitions
from .materials import (
    MATERIAL_TOOL_DATA,
    MATERIAL_TOOL_NAMES,
    load_material_definitions,
)
from .modifiers import DESTRUCTIVE_TOOL_NAMES as MODIFIER_DESTRUCTIVE_TOOL_NAMES
from .modifiers import TOOL_DATA as MODIFIER_TOOL_DATA
from .modifiers import TOOL_NAMES as MODIFIER_TOOL_NAMES
from .modifiers import load_definitions as load_modifier_definitions
from .nodes import NODE_TOOL_DATA, NODE_TOOL_NAMES, load_node_definitions
from .python_exec import PYTHON_TOOL_NAMES
from .python_exec import load_definitions as load_python_definitions
from .render import RENDER_TOOL_DATA, RENDER_TOOL_NAMES
from .render import load_definitions as load_render_definitions
from .rigging import RIGGING_TOOL_DATA, RIGGING_TOOL_NAMES, load_rigging_definitions
from .scene_edit import SCENE_EDIT_TOOL_DATA, SCENE_EDIT_TOOL_NAMES
from .scene_edit import load_definitions as load_scene_edit_definitions
from .uv import DESTRUCTIVE_TOOL_NAMES as UV_DESTRUCTIVE_TOOL_NAMES
from .uv import TOOL_DATA as UV_TOOL_DATA
from .uv import TOOL_NAMES as UV_TOOL_NAMES
from .uv import load_definitions as load_uv_definitions

CORE_REMOTE_TOOLS: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("bridge.status", "Report Blender bridge, project, mode, and permission status.", False, ()),
    ("bridge.task.set", "Show the current high-level Codex task in Blender's UI.", False, ()),
    ("bridge.task.clear", "Clear the current high-level task from Blender's UI.", False, ()),
    ("project.info", "Inspect project metadata and render settings.", False, ("INSPECT_SCENE",)),
    ("scene.inspect", "Return a compact authoritative structural scene representation.", False, ("INSPECT_SCENE",)),
    ("scene.summary", "Return an LLM-oriented structural and textual scene summary.", False, ("INSPECT_SCENE",)),
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
    ("checkpoint.list", "List recent agent checkpoints and operation history.", False, ()),
    ("project.save", "Save the current project when Blender-side permission allows it.", True, ("SAVE_PROJECT",)),
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
)

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
    ("transform.apply", "Apply selected transform components to object data.", True, ("TRANSFORM_OBJECTS",)),
)
OBJECT_TOOL_NAMES = tuple(item[0] for item in OBJECT_TOOL_DATA)

MESH_TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
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
MESH_TOOL_NAMES = tuple(item[0] for item in MESH_TOOL_DATA)


def _modifying_four(values: tuple[tuple[str, str, bool, tuple[str, ...]], ...]) -> set[str]:
    return {name for name, _description, modifying, _permissions in values if modifying}


def _modifying_three(values: tuple[tuple[str, str, bool], ...]) -> set[str]:
    return {name for name, _description, modifying in values if modifying}


MODIFYING_TOOL_NAMES = frozenset(
    _modifying_four(CORE_REMOTE_TOOLS)
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
)

# MCP annotations are advisory; Blender permissions remain authoritative.  Err
# conservative for operations that delete data, bake/apply state, write files,
# replace Render Result, or execute a broad script.
DESTRUCTIVE_TOOL_NAMES = frozenset(
    {
        "checkpoint.undo_last",
        "project.save",
        "viewport.capture",
        "object.delete",
        "transform.apply",
        "mesh.delete_selected",
        "mesh.dissolve_selected",
        "material.delete",
        "material.slot_remove",
        "nodes.remove",
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
    )


__all__ = [
    "ANIMATION_TOOL_NAMES",
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
