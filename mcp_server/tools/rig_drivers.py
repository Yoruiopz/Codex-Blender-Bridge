"""Typed MCP control-property and non-scripted pose-driver definitions."""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import NotRequired, TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

Channel = Literal["location", "rotation_euler", "scale"]
DriverType = Literal["AVERAGE", "SUM", "MIN", "MAX"]


class DriverVariable(TypedDict):
    kind: Literal["PROPERTY", "TRANSFORM"]
    object_name: str
    bone_name: NotRequired[str]
    property_name: NotRequired[str]
    transform_type: NotRequired[Literal["LOC_X", "LOC_Y", "LOC_Z", "ROT_X", "ROT_Y", "ROT_Z", "SCALE_X", "SCALE_Y", "SCALE_Z"]]
    transform_space: NotRequired[Literal["WORLD_SPACE", "LOCAL_SPACE", "TRANSFORM_SPACE"]]


TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("rig.property_inspect", "Inspect one exact numeric object or pose-bone control property.", False, ("INSPECT_SCENE",)),
    ("rig.property_set", "Create or set an explicit bounded numeric rig control with dependency review.", True, ("EDIT_ANIMATION",)),
    ("rig.driver_inspect", "Inspect a driver on an exact pose-bone transform component.", False, ("INSPECT_SCENE",)),
    ("rig.driver_add", "Add a non-scripted pose-bone driver from reviewed numeric controls or transforms.", True, ("EDIT_ANIMATION",)),
    ("rig.driver_remove", "Remove one exact reviewed pose-bone transform driver.", True, ("EDIT_ANIMATION",)),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"rig.driver_remove"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(tool_name, toolset="rigging", description=description, modifying=modifying, required_permissions=permissions)
                 for tool_name, description, modifying, permissions in TOOL_DATA)


class RigDriverTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def rig_property_inspect(self, object_name: str, property_name: str, bone_name: str | None = None) -> Any:
        """Inspect one exact stored numeric control without evaluating a supplied RNA path."""
        return await self.registry.call("rig.property_inspect", params(object_name=object_name, bone_name=bone_name, property_name=property_name))

    async def rig_property_set(self, object_name: str, property_name: str, value: float | int,
                               bone_name: str | None = None, create: bool = False) -> Any:
        """Set an explicit numeric object/pose-bone control; missing properties require create=true."""
        return await self.registry.call("rig.property_set", params(object_name=object_name, bone_name=bone_name,
                                       property_name=property_name, value=value, create=create))

    async def rig_driver_inspect(self, object_name: str, bone_name: str, channel: Channel, index: int = 0) -> Any:
        """Inspect one exact pose-bone transform driver and its bounded source metadata."""
        return await self.registry.call("rig.driver_inspect", params(object_name=object_name, bone_name=bone_name, channel=channel, index=index))

    async def rig_driver_add(self, object_name: str, bone_name: str, channel: Channel, variables: list[DriverVariable],
                             index: int = 0, driver_type: DriverType = "AVERAGE") -> Any:
        """Add a non-scripted bone driver from exact numeric properties or transform sources after bounded cycle review."""
        return await self.registry.call("rig.driver_add", params(object_name=object_name, bone_name=bone_name,
                                       channel=channel, index=index, driver_type=driver_type, variables=variables))

    async def rig_driver_remove(self, object_name: str, bone_name: str, channel: Channel, index: int = 0) -> Any:
        """Remove one reviewed exact pose-bone transform driver; checkpoint recovery remains explicit."""
        return await self.registry.call("rig.driver_remove", params(object_name=object_name, bone_name=bone_name, channel=channel, index=index))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(tool_name, getattr(self, tool_name.replace(".", "_")), description)
                     for tool_name, description, _, _ in TOOL_DATA)
