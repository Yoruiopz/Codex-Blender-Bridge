"""Lazy, typed MCP definitions for bounded Geometry Nodes authoring."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

SocketValue = bool | int | float | str | list[float]
TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    (
        "geometry_nodes.inspect",
        "Inspect a bounded geometry graph, interface, and direct users.",
        False,
        ("INSPECT_SCENE",),
    ),
    (
        "geometry_nodes.create",
        "Create a geometry node group with geometry IO and optional passthrough.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.interface_add",
        "Add a typed interface socket to an explicit geometry node group.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.node_add",
        "Add a compatible geometry node with validated settings.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.node_set_properties",
        "Configure allowlisted direct scalar/enum properties of a geometry node.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.node_set_input",
        "Set an exact geometry node input's scalar or vector default.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.node_remove",
        "Remove an exact geometry node and its incident links.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.link",
        "Link exact compatible geometry-node sockets without graph cycles.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.unlink",
        "Remove links between exact geometry-node sockets.",
        True,
        ("EDIT_MESH",),
    ),
    (
        "geometry_nodes.attach",
        "Attach an explicit geometry node group to an exact named object modifier.",
        True,
        ("EDIT_MESH", "TRANSFORM_OBJECTS"),
    ),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"geometry_nodes.node_remove", "geometry_nodes.unlink"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="geometry_nodes",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in TOOL_DATA
    )


class GeometryNodeTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def geometry_nodes_inspect(
        self,
        group_name: str,
        max_nodes: int = 100,
        max_links: int = 300,
        max_sockets_per_direction: int = 32,
        max_interface_items: int = 64,
    ) -> Any:
        """Inspect exact graph state, bounded sockets/interface, direct users, and editable node settings."""
        return await self.registry.call(
            "geometry_nodes.inspect",
            params(
                group_name=group_name,
                max_nodes=max_nodes,
                max_links=max_links,
                max_sockets_per_direction=max_sockets_per_direction,
                max_interface_items=max_interface_items,
            ),
        )

    async def geometry_nodes_create(self, group_name: str, passthrough: bool = True) -> Any:
        """Create a new named GeometryNodeTree with Geometry IO and optional passthrough link."""
        return await self.registry.call(
            "geometry_nodes.create", params(group_name=group_name, passthrough=passthrough)
        )

    async def geometry_nodes_interface_add(
        self,
        group_name: str,
        name: str,
        in_out: str = "INPUT",
        socket_type: str = "NodeSocketFloat",
        default_value: SocketValue | None = None,
        allow_shared: bool = False,
    ) -> Any:
        """Add a Geometry/Float/Int/Bool/Vector/Color/String interface socket; acknowledge shared graph edits explicitly."""
        return await self.registry.call(
            "geometry_nodes.interface_add",
            params(
                group_name=group_name,
                name=name,
                in_out=in_out,
                socket_type=socket_type,
                default_value=default_value,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_node_add(
        self,
        group_name: str,
        node_type: str,
        name: str | None = None,
        location: list[float] | None = None,
        settings: dict[str, Any] | None = None,
        allow_shared: bool = False,
    ) -> Any:
        """Add a reviewed built-in node with optional allowlisted settings. Inspect supported_node_types first; file/import/script nodes and nested/zone graphs are not exposed."""
        return await self.registry.call(
            "geometry_nodes.node_add",
            params(
                group_name=group_name,
                node_type=node_type,
                name=name,
                location=location,
                settings=settings,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_node_set_properties(
        self,
        group_name: str,
        node_name: str,
        settings: dict[str, Any],
        allow_shared: bool = False,
    ) -> Any:
        """Set validated direct properties such as operation, domain, data_type, mode, location, or label; no pointers or arbitrary paths."""
        return await self.registry.call(
            "geometry_nodes.node_set_properties",
            params(
                group_name=group_name,
                node_name=node_name,
                settings=settings,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_node_set_input(
        self,
        group_name: str,
        node_name: str,
        socket_name: str,
        value: SocketValue,
        socket_index: int | None = None,
        allow_shared: bool = False,
    ) -> Any:
        """Set an exact scalar/vector input default; use socket_index to disambiguate duplicate names. Datablock pointers are unsupported."""
        return await self.registry.call(
            "geometry_nodes.node_set_input",
            params(
                group_name=group_name,
                node_name=node_name,
                socket_name=socket_name,
                value=value,
                socket_index=socket_index,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_node_remove(
        self,
        group_name: str,
        node_name: str,
        allow_shared: bool = False,
    ) -> Any:
        """Remove exactly one geometry node and its incident links after an automatic checkpoint."""
        return await self.registry.call(
            "geometry_nodes.node_remove",
            params(group_name=group_name, node_name=node_name, allow_shared=allow_shared),
        )

    async def geometry_nodes_link(
        self,
        group_name: str,
        from_node: str,
        from_socket: str,
        to_node: str,
        to_socket: str,
        replace_existing: bool = False,
        from_socket_index: int | None = None,
        to_socket_index: int | None = None,
        allow_shared: bool = False,
    ) -> Any:
        """Link compatible sockets, reject cycles, and replace occupied single-input sockets only when explicitly requested."""
        return await self.registry.call(
            "geometry_nodes.link",
            params(
                group_name=group_name,
                from_node=from_node,
                from_socket=from_socket,
                to_node=to_node,
                to_socket=to_socket,
                replace_existing=replace_existing,
                from_socket_index=from_socket_index,
                to_socket_index=to_socket_index,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_unlink(
        self,
        group_name: str,
        from_node: str,
        from_socket: str,
        to_node: str,
        to_socket: str,
        from_socket_index: int | None = None,
        to_socket_index: int | None = None,
        allow_shared: bool = False,
    ) -> Any:
        """Remove links only between exact output and input sockets; missing links are a no-op."""
        return await self.registry.call(
            "geometry_nodes.unlink",
            params(
                group_name=group_name,
                from_node=from_node,
                from_socket=from_socket,
                to_node=to_node,
                to_socket=to_socket,
                from_socket_index=from_socket_index,
                to_socket_index=to_socket_index,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_attach(
        self,
        group_name: str,
        object_name: str,
        modifier_name: str,
        replace_existing_group: bool = False,
    ) -> Any:
        """Attach a geometry-output group to a named NODES modifier, creating it or explicitly replacing a prior group."""
        return await self.registry.call(
            "geometry_nodes.attach",
            params(
                group_name=group_name,
                object_name=object_name,
                modifier_name=modifier_name,
                replace_existing_group=replace_existing_group,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods = (
            ("geometry_nodes.inspect", self.geometry_nodes_inspect),
            ("geometry_nodes.create", self.geometry_nodes_create),
            ("geometry_nodes.interface_add", self.geometry_nodes_interface_add),
            ("geometry_nodes.node_add", self.geometry_nodes_node_add),
            ("geometry_nodes.node_set_properties", self.geometry_nodes_node_set_properties),
            ("geometry_nodes.node_set_input", self.geometry_nodes_node_set_input),
            ("geometry_nodes.node_remove", self.geometry_nodes_node_remove),
            ("geometry_nodes.link", self.geometry_nodes_link),
            ("geometry_nodes.unlink", self.geometry_nodes_unlink),
            ("geometry_nodes.attach", self.geometry_nodes_attach),
        )
        return tuple(
            MCPToolBinding(name, handler, handler.__doc__ or "") for name, handler in methods
        )


__all__ = [
    "DESTRUCTIVE_TOOL_NAMES",
    "TOOL_DATA",
    "TOOL_NAMES",
    "GeometryNodeTools",
    "load_definitions",
]
