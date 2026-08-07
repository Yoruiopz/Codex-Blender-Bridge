"""Always-available bridge, checkpoint, and local registry wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class CoreTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def bridge_status(self) -> Any:
        """Report Blender bridge, project, mode, and permission status."""

        return await self.registry.call("bridge.status")

    async def checkpoint_create(self, description: str | None = None) -> Any:
        """Create a logical checkpoint before meaningful modification."""

        return await self.registry.call(
            "checkpoint.create", params(description=description)
        )

    async def checkpoint_undo_last(
        self,
        confirm_global_undo: bool = False,
    ) -> Any:
        """Use Blender global undo only after explicitly acknowledging interleaving risk."""

        return await self.registry.call(
            "checkpoint.undo_last",
            {"confirm_global_undo": confirm_global_undo},
        )

    async def checkpoint_list(self, limit: int = 50) -> Any:
        """List recent checkpoints and operation history."""

        return await self.registry.call("checkpoint.list", {"limit": limit})

    async def toolsets_list(self) -> dict[str, Any]:
        """List local MCP toolsets and whether each is enabled and loaded."""

        return self.registry.list()

    async def toolsets_enable(self, name: str) -> dict[str, Any]:
        """Enable a local MCP domain toolset."""

        result = await self.registry.call("toolsets.enable", {"name": name})
        assert isinstance(result, dict)
        return result

    async def toolsets_disable(self, name: str) -> dict[str, Any]:
        """Disable a local MCP domain toolset; core cannot be disabled."""

        result = await self.registry.call("toolsets.disable", {"name": name})
        assert isinstance(result, dict)
        return result

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("bridge.status", self.bridge_status, self.bridge_status.__doc__ or ""),
            MCPToolBinding("checkpoint.create", self.checkpoint_create, self.checkpoint_create.__doc__ or ""),
            MCPToolBinding("checkpoint.undo_last", self.checkpoint_undo_last, self.checkpoint_undo_last.__doc__ or ""),
            MCPToolBinding("checkpoint.list", self.checkpoint_list, self.checkpoint_list.__doc__ or ""),
            MCPToolBinding("toolsets.list", self.toolsets_list, self.toolsets_list.__doc__ or ""),
            MCPToolBinding("toolsets.enable", self.toolsets_enable, self.toolsets_enable.__doc__ or ""),
            MCPToolBinding("toolsets.disable", self.toolsets_disable, self.toolsets_disable.__doc__ or ""),
        )
