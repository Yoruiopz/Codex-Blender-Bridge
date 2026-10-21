"""Typed paired-zone and nested interface maintenance; no bake operators."""

from __future__ import annotations

from typing import Any, Literal

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

SocketValue = bool | int | float | str | list[float]
ZoneType = Literal["FLOAT", "INT", "BOOLEAN", "VECTOR", "RGBA"]
InterfaceOperation = Literal["RENAME", "MOVE", "SET_DEFAULT"]
TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("geometry_nodes.zone_inspect", "Inspect paired zone item identifiers/types within 32 items; no cache-state assertion.", False, ("INSPECT_SCENE",)),
    ("geometry_nodes.zone_item_convert", "Convert one unlinked paired numeric zone item preserving identifiers with explicit replacement defaults.", True, ("EDIT_MESH",)),
    ("geometry_nodes.interface_edit", "Rename/reorder/set one nested interface socket default while preserving existing consumer values.", True, ("EDIT_MESH",)),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"geometry_nodes.zone_item_convert", "geometry_nodes.interface_edit"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(tool_name, toolset="geometry_nodes", description=description, modifying=modifying,
                             required_permissions=permissions)
                 for tool_name, description, modifying, permissions in TOOL_DATA)


class GeometryZoneLifecycleTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def geometry_nodes_zone_inspect(self, group_name: str, output_name: str) -> Any:
        """Inspect paired repeat/simulation items and exact boundary socket identifiers; no disk IO or cache status."""
        return await self.registry.call("geometry_nodes.zone_inspect", params(group_name=group_name, output_name=output_name))

    async def geometry_nodes_zone_item_convert(self, group_name: str, output_name: str, socket_identifier: str,
                                               socket_type: ZoneType, input_value: SocketValue, output_value: SocketValue,
                                               allow_shared: bool = False) -> Any:
        """Convert one unlinked numeric/bool/vector/color item and set both paired input defaults; attached caches refused."""
        return await self.registry.call("geometry_nodes.zone_item_convert", params(group_name=group_name,
            output_name=output_name, socket_identifier=socket_identifier, socket_type=socket_type,
            input_value=input_value, output_value=output_value, allow_shared=allow_shared))

    async def geometry_nodes_interface_edit(self, group_name: str, socket_identifier: str, operation: InterfaceOperation,
                                            new_name: str | None = None, to_index: int | None = None,
                                            value: SocketValue | None = None, allow_shared: bool = False) -> Any:
        """Rename, move to final direction-local index or change an INPUT default; existing consumers retain their values."""
        return await self.registry.call("geometry_nodes.interface_edit", params(group_name=group_name,
            socket_identifier=socket_identifier, operation=operation, new_name=new_name, to_index=to_index,
            value=value, allow_shared=allow_shared))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(tool_name, getattr(self, tool_name.replace(".", "_")), description)
                     for tool_name, description, _, _ in TOOL_DATA)
