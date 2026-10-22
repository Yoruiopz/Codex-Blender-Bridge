"""Strict shader interface plans; Blender owns live authorization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA = (
    ("shader_group.interface_preview", "Preview one bounded shader interface rename/reorder/default plan with exact full-scope fingerprint.", False, ("INSPECT_SCENE",)),
    ("shader_group.interface_edit", "Apply one exact shader interface preview with complete bounded graph/owner CAS and guarded compensation.", True, ("INSPECT_SCENE", "EDIT_MATERIALS")),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
Name = Annotated[StrictStr, Field(min_length=1, max_length=63)]
Operation = Literal["RENAME", "MOVE", "SET_DEFAULT"]
Index = Annotated[StrictInt, Field(ge=0, le=127)]
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
Value = StrictBool | StrictInt | StrictFloat | Annotated[list[StrictFloat | StrictInt], Field(min_length=3, max_length=4)]


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="nodes", description=description, modifying=modifying,
        required_permissions=permissions) for name, description, modifying, permissions in TOOL_DATA)


class ShaderInterfaceTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def shader_group_interface_preview(self, group_name: Name, socket_identifier: Name,
        operation: Operation, new_name: Name | None = None, to_index: Index | None = None, value: Value | None = None) -> Any:
        """Read-only structural preview for one exact local ShaderNodeTree interface socket. RENAME needs new_name, MOVE needs a final same-direction to_index, SET_DEFAULT needs value; unrelated optional fields are rejected. Flat interfaces, complete bounded local unanimated definitions/root owners and reviewed builtin nodes are required. Returns all affected material/object/world/light owners and a fingerprint bound to actual graph state plus this exact operation. Existing instance defaults are protected; input definition defaults initialize new consumer inputs. Images are binding metadata only, without pixel reads or reload. Type conversion/removal and animation maintenance are unsupported."""
        return await self.registry.call("shader_group.interface_preview", params(group_name=group_name,
            socket_identifier=socket_identifier, operation=operation, new_name=new_name, to_index=to_index, value=value))

    async def shader_group_interface_edit(self, group_name: Name, socket_identifier: Name,
        operation: Operation, expected_fingerprint: Fingerprint, new_name: Name | None = None,
        to_index: Index | None = None, value: Value | None = None, allow_shared: StrictBool = False) -> Any:
        """Apply the exact current interface_preview with INSPECT_SCENE and EDIT_MATERIALS. Explicit allow_shared covers every reported affected owner. Native stable identifiers, all links and existing instance defaults are preserved, with live stop/consent/toolset/cancellation/context/full-scope checks immediately before writes and compensation. Unexpected outputs, replaced IDs, lost consent, canceled/expired requests or disconnected owners refuse compensation and report measured partial state; logical history is not a disk backup. No conversion, socket deletion, file access, texture reload or project save occurs. Reinspect and use visual comparison for subsequent appearance-changing workflows."""
        return await self.registry.call("shader_group.interface_edit", params(group_name=group_name,
            socket_identifier=socket_identifier, operation=operation, expected_fingerprint=expected_fingerprint,
            new_name=new_name, to_index=to_index, value=value, allow_shared=allow_shared))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods: tuple[Callable[..., Any], ...] = (self.shader_group_interface_preview, self.shader_group_interface_edit)
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in zip(TOOL_NAMES, methods, strict=True))
