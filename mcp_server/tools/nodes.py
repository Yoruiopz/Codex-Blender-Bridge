"""Static MCP wrappers and lazy definitions for material shader node graphs."""

from __future__ import annotations

from typing import Any

from pydantic import StrictBool, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params
from .shader_groups import SHADER_GROUP_TOOL_DATA, GroupPath, ShaderGroupTools
from .shader_settings import SHADER_SETTINGS_TOOL_DATA, ShaderSettingsTools

SocketValue = bool | int | float | str | list[float]

NODE_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("nodes.set_image", "Bind/clear a loaded image and validated sampling settings on an exact root material image node; FILE sources require external-file policy checks.", True, ("EDIT_MATERIALS",)),
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
    *SHADER_GROUP_TOOL_DATA,
    *SHADER_SETTINGS_TOOL_DATA,
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

    async def nodes_set_image(
        self, material_name: StrictStr, node_name: StrictStr, image_name: StrictStr | None,
        interpolation: StrictStr | None = None, projection: StrictStr | None = None, extension: StrictStr | None = None,
        allow_shared: StrictBool = False,
        group_path: GroupPath | None = None,
    ) -> Any:
        """Object Mode Image Texture binding at the material root or explicit group_path, or null to clear. Local loaded single-view FILE/GENERATED images only; FILE sources also require live external-file permission and approved-folder/header checks. No implicit reload or pixel edits. Sampling enum names are validated against native RNA before mutation. Inspect material and transitive group ownership first; shared scope requires explicit allow_shared. Verify image identity, settings, graph links and a material/texture capture; buffer/file currency is not certified."""
        return await self.registry.call("nodes.set_image", {"material_name": material_name, "node_name": node_name,
            "image_name": image_name, **params(interpolation=interpolation, projection=projection, extension=extension, allow_shared=allow_shared, group_path=group_path)})

    async def nodes_inspect(
        self,
        material_name: str,
        max_nodes: int = 100,
        max_links: int = 300,
        max_sockets_per_direction: int = 32,
        group_path: GroupPath | None = None,
    ) -> Any:
        """Inspect shader nodes/links at the material root or explicit group_path with bounds/truncation. Nested inspection includes transitive ownership evidence; it does not recursively expand every referenced group."""

        return await self.registry.call(
            "nodes.inspect",
            {
                "material_name": material_name,
                "max_nodes": max_nodes,
                "max_links": max_links,
                "max_sockets_per_direction": max_sockets_per_direction,
                **params(group_path=group_path),
            },
        )

    async def nodes_add(
        self,
        material_name: str,
        node_type: str,
        name: str | None = None,
        label: str | None = None,
        location: list[float] | None = None,
        allow_shared: bool = False,
        group_path: GroupPath | None = None,
    ) -> Any:
        """Add a shader node at the material root or group_path; nested graphs also admit NodeGroupInput/NodeGroupOutput. Shared material/group scope requires allow_shared after inspection."""

        return await self.registry.call(
            "nodes.add",
            params(
                material_name=material_name,
                node_type=node_type,
                name=name,
                label=label,
                location=location,
                allow_shared=allow_shared,
                group_path=group_path,
            ),
        )

    async def nodes_remove(self, material_name: str, node_name: str, allow_shared: bool = False, group_path: GroupPath | None = None) -> Any:
        """Remove a node and its links; inspect usage before consenting with allow_shared."""

        return await self.registry.call(
            "nodes.remove",
            {"material_name": material_name, "node_name": node_name, "allow_shared": allow_shared, **params(group_path=group_path)},
        )

    async def nodes_rename(
        self,
        material_name: str,
        node_name: str,
        new_name: str,
        allow_shared: bool = False,
        group_path: GroupPath | None = None,
    ) -> Any:
        """Rename a node without collisions; shared material edits require allow_shared."""

        return await self.registry.call(
            "nodes.rename",
            {
                "material_name": material_name,
                "node_name": node_name,
                "new_name": new_name,
                "allow_shared": allow_shared,
                **params(group_path=group_path),
            },
        )

    async def nodes_set_input(
        self,
        material_name: str,
        node_name: str,
        socket_name: str,
        value: SocketValue,
        socket_index: int | None = None,
        allow_shared: bool = False,
        group_path: GroupPath | None = None,
    ) -> Any:
        """Set an exact input; index disambiguates sockets; shared materials require allow_shared."""

        return await self.registry.call(
            "nodes.set_input",
            params(
                material_name=material_name,
                node_name=node_name,
                socket_name=socket_name,
                value=value,
                socket_index=socket_index,
                allow_shared=allow_shared,
                group_path=group_path,
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
        allow_shared: bool = False,
        group_path: GroupPath | None = None,
    ) -> Any:
        """Link exact sockets with explicit replacement; shared materials require allow_shared."""

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
                allow_shared=allow_shared,
                group_path=group_path,
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
        allow_shared: bool = False,
        group_path: GroupPath | None = None,
    ) -> Any:
        """Unlink exact sockets; shared materials require allow_shared; missing links are no-ops."""

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
                allow_shared=allow_shared,
                group_path=group_path,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("nodes.set_image", self.nodes_set_image, self.nodes_set_image.__doc__ or ""),
            MCPToolBinding("nodes.inspect", self.nodes_inspect, self.nodes_inspect.__doc__ or ""),
            MCPToolBinding("nodes.add", self.nodes_add, self.nodes_add.__doc__ or ""),
            MCPToolBinding("nodes.remove", self.nodes_remove, self.nodes_remove.__doc__ or ""),
            MCPToolBinding("nodes.rename", self.nodes_rename, self.nodes_rename.__doc__ or ""),
            MCPToolBinding("nodes.set_input", self.nodes_set_input, self.nodes_set_input.__doc__ or ""),
            MCPToolBinding("nodes.link", self.nodes_link, self.nodes_link.__doc__ or ""),
            MCPToolBinding("nodes.unlink", self.nodes_unlink, self.nodes_unlink.__doc__ or ""),
            *ShaderGroupTools(self.registry).bindings(),
            *ShaderSettingsTools(self.registry).bindings(),
        )


__all__ = [
    "NODE_TOOL_DATA",
    "NODE_TOOL_NAMES",
    "NodeTools",
    "load_definitions",
    "load_node_definitions",
]
