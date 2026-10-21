"""Typed wrappers for reviewed nested GN groups and modifier constants."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

SocketValue = bool | int | float | str | list[float]
TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("geometry_nodes.group_bind", "Bind a reviewed nested GN group through a uniquely named instance.", True, ("EDIT_MESH",)),
    ("geometry_nodes.group_copy_for_node", "Copy one nested GN instance root while retaining referenced descendants.", True, ("EDIT_MESH",)),
    ("geometry_nodes.group_link", "Link exact socket identifiers in a reviewed nested GN graph.", True, ("EDIT_MESH",)),
    ("geometry_nodes.group_set_input", "Set an unlinked constant by exact socket identifier in a reviewed GN graph.", True, ("EDIT_MESH",)),
    ("geometry_nodes.group_remove", "Remove only an explicitly confirmed unused GN group.", True, ("EDIT_MESH", "DELETE_OBJECTS")),
    ("geometry_nodes.group_attach", "Attach a recursively reviewed nested GN graph to one mesh object.", True, ("EDIT_MESH", "TRANSFORM_OBJECTS")),
    ("geometry_nodes.modifier_inspect", "Inspect stored GN modifier inputs by stable interface identifiers.", False, ("INSPECT_SCENE",)),
    ("geometry_nodes.modifier_set_input", "Set an object-owned GN modifier constant without changing the shared graph.", True, ("EDIT_MESH", "TRANSFORM_OBJECTS")),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"geometry_nodes.group_remove", "geometry_nodes.group_link"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(tool_name, toolset="geometry_nodes", description=description, modifying=modifying,
                             required_permissions=permissions)
                 for tool_name, description, modifying, permissions in TOOL_DATA)


class GeometryNodeGroupTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def geometry_nodes_group_bind(self, parent_group_name: str, child_group_name: str, node_name: str,
                                        allow_shared: bool = False) -> Any:
        """Create one exact nested group instance after recursive allowlist and parent-user review."""
        return await self.registry.call("geometry_nodes.group_bind", params(parent_group_name=parent_group_name,
                                        child_group_name=child_group_name, node_name=node_name, allow_shared=allow_shared))

    async def geometry_nodes_group_copy_for_node(self, parent_group_name: str, node_name: str,
                                                 new_group_name: str, allow_shared: bool = False) -> Any:
        """Copy one child-root tree and rebind its instance; referenced descendants remain shared."""
        return await self.registry.call("geometry_nodes.group_copy_for_node", params(parent_group_name=parent_group_name,
                                        node_name=node_name, new_group_name=new_group_name, allow_shared=allow_shared))

    async def geometry_nodes_group_link(self, group_name: str, from_node: str, from_socket_identifier: str,
                                        to_node: str, to_socket_identifier: str, replace_existing: bool = False,
                                        allow_shared: bool = False) -> Any:
        """Link current exact socket identifiers; occupied inputs require explicit replacement consent."""
        return await self.registry.call("geometry_nodes.group_link", params(group_name=group_name, from_node=from_node,
                                        from_socket_identifier=from_socket_identifier, to_node=to_node,
                                        to_socket_identifier=to_socket_identifier, replace_existing=replace_existing, allow_shared=allow_shared))

    async def geometry_nodes_group_set_input(self, group_name: str, node_name: str, socket_identifier: str,
                                             value: SocketValue, allow_shared: bool = False) -> Any:
        """Set a reviewed enabled unlinked scalar/vector input through its stable identifier."""
        return await self.registry.call("geometry_nodes.group_set_input", params(group_name=group_name, node_name=node_name,
                                        socket_identifier=socket_identifier, value=value, allow_shared=allow_shared))

    async def geometry_nodes_group_remove(self, group_name: str, confirm_unused: bool = False) -> Any:
        """Delete an explicitly confirmed unused local GN tree without unlinking any consumers."""
        return await self.registry.call("geometry_nodes.group_remove", params(group_name=group_name, confirm_unused=confirm_unused))

    async def geometry_nodes_group_attach(self, group_name: str, object_name: str, modifier_name: str,
                                          replace_existing_group: bool = False) -> Any:
        """Attach a recursively reviewed nested graph to one exact mesh object modifier."""
        return await self.registry.call("geometry_nodes.group_attach", params(group_name=group_name, object_name=object_name,
                                        modifier_name=modifier_name, replace_existing_group=replace_existing_group))

    async def geometry_nodes_modifier_inspect(self, object_name: str, modifier_name: str) -> Any:
        """Inspect exact interface identifiers, stored constants and attribute-use flags without evaluating geometry."""
        return await self.registry.call("geometry_nodes.modifier_inspect", params(object_name=object_name, modifier_name=modifier_name))

    async def geometry_nodes_modifier_set_input(self, object_name: str, modifier_name: str, socket_identifier: str,
                                                value: SocketValue) -> Any:
        """Set an object-owned constant; attribute-driven/animated inputs are refused before mutation."""
        return await self.registry.call("geometry_nodes.modifier_set_input", params(object_name=object_name,
                                        modifier_name=modifier_name, socket_identifier=socket_identifier, value=value))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(tool_name, getattr(self, tool_name.replace(".", "_")), description)
                     for tool_name, description, _, _ in TOOL_DATA)
