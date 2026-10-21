"""Bounded typed current-frame evaluated character evidence."""

from __future__ import annotations

from typing import Any, Literal

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("rig.deformation_inspect", "Measure current-frame evaluated pose/skin, deform weights, edge strain and stored IK limits; no quality verdict.", False, ("INSPECT_SCENE",)),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(tool_name, toolset="rigging", description=description, modifying=modifying, required_permissions=permissions)
                 for tool_name, description, modifying, permissions in TOOL_DATA)


class DeformationTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def rig_deformation_inspect(self, object_name: str, mesh_object: str, bone_names: list[str], vertex_indices: list[int],
                                       coordinate_space: Literal["LOCAL", "WORLD"], target_object: str | None = None,
                                       tip_bone_name: str | None = None, max_influences: int = 4, weight_tolerance: float = 0.0001) -> Any:
        """Measure explicitly sampled skin/pose at the current frame; LOCAL means mesh-local vertices and armature-local bones."""
        return await self.registry.call("rig.deformation_inspect", params(object_name=object_name, mesh_object=mesh_object,
            bone_names=bone_names, vertex_indices=vertex_indices, coordinate_space=coordinate_space, target_object=target_object,
            tip_bone_name=tip_bone_name, max_influences=max_influences, weight_tolerance=weight_tolerance))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(tool_name, getattr(self, tool_name.replace(".", "_")), description)
                     for tool_name, description, _, _ in TOOL_DATA)
