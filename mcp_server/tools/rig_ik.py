"""Typed explicit two-bone IK contracts; controls and affected skins are named."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("rig.ik_inspect", "Inspect one exact stored pose-bone IK constraint; no evaluated-quality verdict.", False, ("INSPECT_SCENE",)),
    ("rig.ik_configure", "Create/configure explicit two-bone IK with independent Empty controls and enumerated skin scope.", True, ("EDIT_ANIMATION",)),
    ("rig.ik_remove", "Confirm removal of one exact scoped IK constraint; native checkpoint recovery remains explicit.", True, ("EDIT_ANIMATION", "DELETE_OBJECTS")),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"rig.ik_remove"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(tool_name, toolset="rigging", description=description, modifying=modifying, required_permissions=permissions)
                 for tool_name, description, modifying, permissions in TOOL_DATA)


class RigIKTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def rig_ik_inspect(self, object_name: str, tip_bone_name: str, constraint_name: str) -> Any:
        """Read stored settings of one exact IK constraint, without a visual or deformation verdict."""
        return await self.registry.call("rig.ik_inspect", params(object_name=object_name, tip_bone_name=tip_bone_name, constraint_name=constraint_name))

    async def rig_ik_configure(self, object_name: str, root_bone_name: str, tip_bone_name: str, target_object: str,
                               pole_object: str, affected_meshes: list[str], constraint_name: str, create: bool = False,
                               pole_angle: float = 0.0, influence: float = 1.0, iterations: int = 128, use_stretch: bool = False) -> Any:
        """Create or configure one connected two-bone branch; angles are radians and every affected skin must be enumerated."""
        return await self.registry.call("rig.ik_configure", params(object_name=object_name, root_bone_name=root_bone_name,
            tip_bone_name=tip_bone_name, target_object=target_object, pole_object=pole_object, affected_meshes=affected_meshes,
            constraint_name=constraint_name, create=create, pole_angle=pole_angle, influence=influence, iterations=iterations, use_stretch=use_stretch))

    async def rig_ik_remove(self, object_name: str, root_bone_name: str, tip_bone_name: str, target_object: str,
                            pole_object: str, affected_meshes: list[str], constraint_name: str, confirm: bool = False) -> Any:
        """Remove one exact scoped IK constraint only after confirm=true; no implicit identity-changing recreation."""
        return await self.registry.call("rig.ik_remove", params(object_name=object_name, root_bone_name=root_bone_name,
            tip_bone_name=tip_bone_name, target_object=target_object, pole_object=pole_object, affected_meshes=affected_meshes,
            constraint_name=constraint_name, confirm=confirm))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(tool_name, getattr(self, tool_name.replace(".", "_")), description)
                     for tool_name, description, _, _ in TOOL_DATA)
