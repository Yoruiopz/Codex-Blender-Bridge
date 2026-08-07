"""Static MCP wrappers and lazy definitions for material shader node graphs."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

SocketValue = bool | int | float | str | list[float]

NODE_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    (
        "nodes.inspect",
        "Inspect a complete bounded material shader graph.",
        False,
        ("INSPECT_SCENE",),
    ),
    (
        "nodes.add",
        "Add a validated shader node to one material graph.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "nodes.remove",
        "Remove one exact shader node and its incident links.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "nodes.rename",
        "Rename one exact shader node without collisions.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "nodes.set_input",
        "Set one exact material-node input default value.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "nodes.link",
        "Link exact material-node output and input sockets.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "nodes.unlink",
        "Remove links between exact material-node sockets.",
        True,
        ("EDIT_MATERIALS",),
    ),
)
NODE_TOOL_NAMES = tuple(item[0] for item in NODE_TOOL_DATA)


def load_definitions() -> tuple[ToolDefinition, ...]:
    """Return lazy-registry definitions without importing the MCP SDK."""

    return tuple(
        remote_tool(
            name,
            toolset="nodes",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in NODE_TOOL_DATA
    )


load_node_definitions = load_definitions


class NodeTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def nodes_inspect(
        self,
        material_name: str,
        max_nodes: int = 100,
        max_links: int = 300,
        max_sockets_per_direction: int = 32,
    ) -> Any:
        """Inspect all shader nodes and links with explicit response limits."""

        return await self.registry.call(
            "nodes.inspect",
            {
                "material_name": material_name,
                "max_nodes": max_nodes,
                "max_links": max_links,
                "max_sockets_per_direction": max_sockets_per_direction,
            },
        )

    async def nodes_add(
        self,
        material_name: str,
        node_type: str,
        name: str | None = None,
        label: str | None = None,
        location: list[float] | None = None,
    ) -> Any:
        """Add a Blender ShaderNode type with an optional exact name and position."""

        return await self.registry.call(
            "nodes.add",
            params(
                material_name=material_name,
                node_type=node_type,
                name=name,
                label=label,
                location=location,
            ),
        )

    async def nodes_remove(self, material_name: str, node_name: str) -> Any:
        """Remove one exact shader node and its incident links."""

        return await self.registry.call(
            "nodes.remove",
            {"material_name": material_name, "node_name": node_name},
        )

    async def nodes_rename(
        self,
        material_name: str,
        node_name: str,
        new_name: str,
    ) -> Any:
        """Rename one exact shader node without allowing a name collision."""

        return await self.registry.call(
            "nodes.rename",
            {
                "material_name": material_name,
                "node_name": node_name,
                "new_name": new_name,
            },
        )

    async def nodes_set_input(
        self,
        material_name: str,
        node_name: str,
        socket_name: str,
        value: SocketValue,
        socket_index: int | None = None,
    ) -> Any:
        """Set one named input; use its index only to disambiguate duplicate names."""

        return await self.registry.call(
            "nodes.set_input",
            params(
                material_name=material_name,
                node_name=node_name,
                socket_name=socket_name,
                value=value,
                socket_index=socket_index,
            ),
        )

    async def nodes_link(
        self,
        material_name: str,
        from_node: str,
        from_socket: str,
        to_node: str,
        to_socket: str,
        replace_existing: bool = False,
        from_socket_index: int | None = None,
        to_socket_index: int | None = None,
    ) -> Any:
        """Link exact sockets, optionally replacing a single-input destination link."""

        return await self.registry.call(
            "nodes.link",
            params(
                material_name=material_name,
                from_node=from_node,
                from_socket=from_socket,
                to_node=to_node,
                to_socket=to_socket,
                replace_existing=replace_existing,
                from_socket_index=from_socket_index,
                to_socket_index=to_socket_index,
            ),
        )

    async def nodes_unlink(
        self,
        material_name: str,
        from_node: str,
        from_socket: str,
        to_node: str,
        to_socket: str,
        from_socket_index: int | None = None,
        to_socket_index: int | None = None,
    ) -> Any:
        """Unlink exact output and input sockets; a missing link is a no-op."""

        return await self.registry.call(
            "nodes.unlink",
            params(
                material_name=material_name,
                from_node=from_node,
                from_socket=from_socket,
                to_node=to_node,
                to_socket=to_socket,
                from_socket_index=from_socket_index,
                to_socket_index=to_socket_index,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("nodes.inspect", self.nodes_inspect, self.nodes_inspect.__doc__ or ""),
            MCPToolBinding("nodes.add", self.nodes_add, self.nodes_add.__doc__ or ""),
            MCPToolBinding("nodes.remove", self.nodes_remove, self.nodes_remove.__doc__ or ""),
            MCPToolBinding("nodes.rename", self.nodes_rename, self.nodes_rename.__doc__ or ""),
            MCPToolBinding("nodes.set_input", self.nodes_set_input, self.nodes_set_input.__doc__ or ""),
            MCPToolBinding("nodes.link", self.nodes_link, self.nodes_link.__doc__ or ""),
            MCPToolBinding("nodes.unlink", self.nodes_unlink, self.nodes_unlink.__doc__ or ""),
        )


__all__ = [
    "NODE_TOOL_DATA",
    "NODE_TOOL_NAMES",
    "NodeTools",
    "load_definitions",
    "load_node_definitions",
]
