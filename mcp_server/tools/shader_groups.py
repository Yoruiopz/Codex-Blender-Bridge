"""Typed MCP shader-group lifecycle; Blender remains the authorization authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params

GroupPath = Annotated[list[StrictStr], Field(max_length=8, description=(
    "Path from the material root through up to eight exact ShaderNodeGroup instance names, not datablock names. "
    "Omit for the root. Nested mutations require Object Mode and complete transitive ownership evidence; "
    "isolate shared parent groups before editing only one user."
))]
ShaderValue = StrictBool | StrictInt | StrictFloat | StrictStr | Annotated[list[StrictFloat], Field(max_length=4)]
SocketType = Literal["NodeSocketFloat", "NodeSocketInt", "NodeSocketBool", "NodeSocketVector", "NodeSocketColor", "NodeSocketShader"]
SHADER_GROUP_TOOL_DATA = (
    ("shader_group.inspect", "Inspect a bounded shader-group graph, interface and transitive parent ownership evidence.", False, ("INSPECT_SCENE",)),
    ("shader_group.create", "Create a new empty local shader group with input/output nodes.", True, ("EDIT_MATERIALS",)),
    ("shader_group.interface_add", "Add one typed interface socket to an explicitly scoped shader group.", True, ("EDIT_MATERIALS",)),
    ("shader_group.bind", "Bind/clear an exact unlinked group instance after dependency and file-policy checks.", True, ("EDIT_MATERIALS",)),
    ("shader_group.copy_for_node", "Copy one shader-group instance, preserving input defaults and links; nested data remains shared.", True, ("EDIT_MATERIALS",)),
    ("shader_group.remove", "Remove a confirmed unused shader-group datablock without forced unlink or deleting nested data.", True, ("EDIT_MATERIALS", "DELETE_OBJECTS")),
)


class ShaderGroupTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def shader_group_inspect(self, group_name: StrictStr, max_nodes: StrictInt = 100, max_links: StrictInt = 300,
                                   max_sockets_per_direction: StrictInt = 32) -> Any:
        """Read a named ShaderNodeTree/interface with bounded transitive parent/material/world/light user evidence. Ownership limits: 32 groups/100 owner IDs/material-slot objects. Incomplete evidence is not a safe edit scope. No image-buffer reload or pixel reads."""
        return await self.registry.call("shader_group.inspect", params(group_name=group_name, max_nodes=max_nodes,
            max_links=max_links, max_sockets_per_direction=max_sockets_per_direction))

    async def shader_group_create(self, group_name: StrictStr) -> Any:
        """Object Mode: create a unique empty ShaderNodeTree and its input/output nodes. No implicit reuse, attachment or save. Add typed interface sockets, create a ShaderNodeGroup instance, bind it, then use nodes.* with group_path to author its body."""
        return await self.registry.call("shader_group.create", {"group_name": group_name})

    async def shader_group_interface_add(self, group_name: StrictStr, name: StrictStr, in_out: Literal["INPUT", "OUTPUT"] = "INPUT",
                                         socket_type: SocketType = "NodeSocketFloat", default_value: ShaderValue | None = None,
                                         allow_shared: StrictBool = False) -> Any:
        """Object Mode: append one of six reviewed shader interface socket types, up to 128 items. Inspect users; shared dependencies require explicit allow_shared, linked/read-only owners block editing. On failure, removing the new socket alone is not proof of global instance rollback: reinspect or recover the checkpoint."""
        return await self.registry.call("shader_group.interface_add", params(group_name=group_name, name=name,
            in_out=in_out, socket_type=socket_type, default_value=default_value, allow_shared=allow_shared))

    async def shader_group_bind(self, material_name: StrictStr, node_name: StrictStr, group_name: StrictStr | None,
                                group_path: GroupPath | None = None, allow_shared: StrictBool = False) -> Any:
        """Object Mode: assign a named group or explicit null to clear an unlinked ShaderNodeGroup instance. Clear a different previous binding first. Checks recursion and up to 32 local groups/16 loaded images; FILE images require live external-file permission and approved PNG/JPEG source checks. Script/IES dependencies are not supported. Existing graph links are never implicitly discarded."""
        return await self.registry.call("shader_group.bind", {"material_name": material_name, "node_name": node_name,
            "group_name": group_name, **params(group_path=group_path, allow_shared=allow_shared)})

    async def shader_group_copy_for_node(self, material_name: StrictStr, node_name: StrictStr, new_name: StrictStr,
                                         group_path: GroupPath | None = None, allow_shared: StrictBool = False) -> Any:
        """Object Mode: explicitly isolate one bound group instance. Copy the material first when only one shared-material object is in scope, then isolate each shared parent before editing deeper children. Verifies input defaults/links and original user count. Nested groups/images remain shared. FILE dependencies require approved-source external-file checks, not implicit loading. Failure retains measured recovery evidence."""
        return await self.registry.call("shader_group.copy_for_node", params(material_name=material_name, node_name=node_name,
            new_name=new_name, group_path=group_path, allow_shared=allow_shared))

    async def shader_group_remove(self, group_name: StrictStr, confirm_unused: StrictBool = False) -> Any:
        """Object Mode: remove one exact confirmed unused local shader group with no fake user. Requires material-edit and deletion grants. Never force-unlinks users, deletes nested groups/images or files, or saves the project."""
        return await self.registry.call("shader_group.remove", {"group_name": group_name, "confirm_unused": confirm_unused})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods: tuple[Callable[..., Any], ...] = (self.shader_group_inspect, self.shader_group_create, self.shader_group_interface_add,
                   self.shader_group_bind, self.shader_group_copy_for_node, self.shader_group_remove)
        return tuple(MCPToolBinding(data[0], method, method.__doc__ or "") for data, method in zip(SHADER_GROUP_TOOL_DATA, methods, strict=True))
