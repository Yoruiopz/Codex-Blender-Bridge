"""Metadata used by the lazy registry independently of MCP SDK registration."""

from __future__ import annotations

from ..tool_registry import ToolDefinition, remote_tool

CORE_REMOTE_TOOLS: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("bridge.status", "Report Blender bridge, project, mode, and permission status.", False, ()),
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
    ("mesh.inspect", "Inspect compact mesh and topology statistics.", False),
    ("mesh.recalculate_normals", "Recalculate normals for the selected mesh region.", True),
    ("mesh.delete_selected", "Delete selected mesh elements.", True),
    ("mesh.dissolve_selected", "Dissolve selected mesh elements.", True),
    ("mesh.extrude_selected", "Extrude the selected mesh region by an explicit offset.", True),
    ("mesh.inset_selected", "Inset selected faces with explicit thickness and depth.", True),
    ("mesh.bevel_selected", "Bevel selected mesh elements with explicit width and segments.", True),
)
MESH_TOOL_NAMES = tuple(item[0] for item in MESH_TOOL_DATA)

MATERIAL_TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
    ("material.inspect", "Inspect material users, node trees, textures, and Principled values.", False),
)
MATERIAL_TOOL_NAMES = tuple(item[0] for item in MATERIAL_TOOL_DATA)

MODIFYING_TOOL_NAMES = frozenset(
    name
    for name, _, modifying, _ in (*CORE_REMOTE_TOOLS, *OBJECT_TOOL_DATA)
    if modifying
) | frozenset(
    name for name, _, modifying in (*LOCAL_TOOLSET_TOOLS, *MESH_TOOL_DATA, *MATERIAL_TOOL_DATA)
    if modifying
)

# MCP annotations are advisory; Blender permissions remain authoritative.
DESTRUCTIVE_TOOL_NAMES = frozenset(
    {
        "checkpoint.undo_last",
        "project.save",
        "viewport.capture",
        "object.delete",
        "mesh.delete_selected",
    }
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
            required_permissions=("EDIT_MESH",) if modifying else ("INSPECT_SCENE",),
        )
        for name, description, modifying in MESH_TOOL_DATA
    )


def load_material_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="materials",
            description=description,
            modifying=modifying,
            required_permissions=("EDIT_MATERIALS",) if modifying else ("INSPECT_SCENE",),
        )
        for name, description, modifying in MATERIAL_TOOL_DATA
    )
