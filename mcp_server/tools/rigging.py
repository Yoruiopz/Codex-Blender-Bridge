"""Lazy MCP wrappers and definitions for structured armature operations."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

RIGGING_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    (
        "rig.inspect",
        "Inspect a bounded armature hierarchy, pose transforms, and constraints.",
        False,
        ("INSPECT_SCENE",),
    ),
    (
        "rig.create",
        "Create an armature object with one explicit root bone.",
        True,
        ("EDIT_ANIMATION", "TRANSFORM_OBJECTS"),
    ),
    (
        "rig.bone_add",
        "Add one explicit edit bone to a named armature.",
        True,
        ("EDIT_ANIMATION",),
    ),
    (
        "rig.bone_update",
        "Update explicit edit-bone geometry, hierarchy, name, or deform flags.",
        True,
        ("EDIT_ANIMATION",),
    ),
    (
        "rig.bone_remove",
        "Remove one explicit bone with optional child reparenting.",
        True,
        ("DELETE_OBJECTS", "EDIT_ANIMATION"),
    ),
    (
        "rig.pose_transform",
        "Set finite pose-bone transform channels explicitly.",
        True,
        ("EDIT_ANIMATION", "TRANSFORM_OBJECTS"),
    ),
    (
        "rig.constraint_add",
        "Add a supported named pose-bone constraint.",
        True,
        ("EDIT_ANIMATION",),
    ),
    (
        "rig.constraint_remove",
        "Remove one named pose-bone constraint.",
        True,
        ("EDIT_ANIMATION",),
    ),
    (
        "rig.bind_mesh",
        "Bind a mesh using empty groups or contextual automatic weights.",
        True,
        ("EDIT_ANIMATION", "TRANSFORM_OBJECTS"),
    ),
)
RIGGING_TOOL_NAMES = tuple(item[0] for item in RIGGING_TOOL_DATA)


def load_rigging_definitions() -> tuple[ToolDefinition, ...]:
    """Return lazy-registry definitions without importing Blender or MCP SDK classes."""

    return tuple(
        remote_tool(
            name,
            toolset="rigging",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in RIGGING_TOOL_DATA
    )


class RiggingTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def rig_inspect(
        self,
        object_name: str,
        max_bones: int = 256,
        max_constraints: int = 512,
    ) -> Any:
        """Inspect one named armature without unbounded bone or constraint output."""

        return await self.registry.call(
            "rig.inspect",
            {
                "object_name": object_name,
                "max_bones": max_bones,
                "max_constraints": max_constraints,
            },
        )

    async def rig_create(
        self,
        name: str,
        data_name: str | None = None,
        collection: str | None = None,
        location: list[float] | None = None,
        display_type: str = "OCTAHEDRAL",
        root_bone_name: str = "Root",
        root_head: list[float] | None = None,
        root_tail: list[float] | None = None,
    ) -> Any:
        """Create an armature with one explicit root bone and return its state."""

        return await self.registry.call(
            "rig.create",
            params(
                name=name,
                data_name=data_name,
                collection=collection,
                location=location,
                display_type=display_type,
                root_bone_name=root_bone_name,
                root_head=root_head,
                root_tail=root_tail,
            ),
        )

    async def rig_bone_add(
        self,
        object_name: str,
        bone_name: str,
        head: list[float],
        tail: list[float],
        parent_name: str | None = None,
        use_connect: bool = False,
        use_deform: bool = True,
        roll: float = 0.0,
    ) -> Any:
        """Add one armature-local edit bone with explicit geometry and parent."""

        return await self.registry.call(
            "rig.bone_add",
            params(
                object_name=object_name,
                bone_name=bone_name,
                head=head,
                tail=tail,
                parent_name=parent_name,
                use_connect=use_connect,
                use_deform=use_deform,
                roll=roll,
            ),
        )

    async def rig_bone_update(
        self,
        object_name: str,
        bone_name: str,
        new_name: str | None = None,
        head: list[float] | None = None,
        tail: list[float] | None = None,
        roll: float | None = None,
        parent_name: str | None = None,
        clear_parent: bool = False,
        use_connect: bool | None = None,
        use_deform: bool | None = None,
    ) -> Any:
        """Update only supplied properties on one named edit bone."""

        return await self.registry.call(
            "rig.bone_update",
            params(
                object_name=object_name,
                bone_name=bone_name,
                new_name=new_name,
                head=head,
                tail=tail,
                roll=roll,
                parent_name=parent_name,
                clear_parent=clear_parent,
                use_connect=use_connect,
                use_deform=use_deform,
            ),
        )

    async def rig_bone_remove(
        self,
        object_name: str,
        bone_name: str,
        reparent_children: bool = False,
    ) -> Any:
        """Remove one bone, rejecting children unless reparenting is explicit."""

        return await self.registry.call(
            "rig.bone_remove",
            {
                "object_name": object_name,
                "bone_name": bone_name,
                "reparent_children": reparent_children,
            },
        )

    async def rig_pose_transform(
        self,
        object_name: str,
        bone_name: str,
        location: list[float] | None = None,
        rotation_mode: str | None = None,
        rotation_euler: list[float] | None = None,
        rotation_quaternion: list[float] | None = None,
        rotation_axis_angle: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> Any:
        """Set explicit finite transform channels on one pose bone."""

        return await self.registry.call(
            "rig.pose_transform",
            params(
                object_name=object_name,
                bone_name=bone_name,
                location=location,
                rotation_mode=rotation_mode,
                rotation_euler=rotation_euler,
                rotation_quaternion=rotation_quaternion,
                rotation_axis_angle=rotation_axis_angle,
                scale=scale,
            ),
        )

    async def rig_constraint_add(
        self,
        object_name: str,
        bone_name: str,
        constraint_type: str,
        name: str | None = None,
        target_object: str | None = None,
        subtarget: str | None = None,
        influence: float = 1.0,
        chain_count: int = 0,
    ) -> Any:
        """Add a supported constraint to one named pose bone."""

        return await self.registry.call(
            "rig.constraint_add",
            params(
                object_name=object_name,
                bone_name=bone_name,
                constraint_type=constraint_type,
                name=name,
                target_object=target_object,
                subtarget=subtarget,
                influence=influence,
                chain_count=chain_count,
            ),
        )

    async def rig_constraint_remove(
        self,
        object_name: str,
        bone_name: str,
        constraint_name: str,
    ) -> Any:
        """Remove one explicit constraint from one named pose bone."""

        return await self.registry.call(
            "rig.constraint_remove",
            {
                "object_name": object_name,
                "bone_name": bone_name,
                "constraint_name": constraint_name,
            },
        )

    async def rig_bind_mesh(
        self,
        mesh_object: str,
        armature_object: str,
        method: str = "EMPTY_GROUPS",
        parent: bool = True,
    ) -> Any:
        """Bind one mesh to one armature using an explicit weighting method."""

        return await self.registry.call(
            "rig.bind_mesh",
            {
                "mesh_object": mesh_object,
                "armature_object": armature_object,
                "method": method,
                "parent": parent,
            },
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(
            MCPToolBinding(name, handler, handler.__doc__ or "")
            for name, handler in (
                ("rig.inspect", self.rig_inspect),
                ("rig.create", self.rig_create),
                ("rig.bone_add", self.rig_bone_add),
                ("rig.bone_update", self.rig_bone_update),
                ("rig.bone_remove", self.rig_bone_remove),
                ("rig.pose_transform", self.rig_pose_transform),
                ("rig.constraint_add", self.rig_constraint_add),
                ("rig.constraint_remove", self.rig_constraint_remove),
                ("rig.bind_mesh", self.rig_bind_mesh),
            )
        )


__all__ = [
    "RIGGING_TOOL_DATA",
    "RIGGING_TOOL_NAMES",
    "RiggingTools",
    "load_rigging_definitions",
]
