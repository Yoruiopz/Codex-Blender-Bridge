"""Always-available project metadata and save wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class ProjectTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def project_info(self) -> Any:
        """Inspect filepath, dirty state, scenes, timing, render, and Blender version."""

        return await self.registry.call("project.info")

    async def project_save(self, filepath: str | None = None) -> Any:
        """Save the project when allowed; filepath performs an explicit Save As."""

        return await self.registry.call("project.save", params(filepath=filepath))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("project.info", self.project_info, self.project_info.__doc__ or ""),
            MCPToolBinding("project.save", self.project_save, self.project_save.__doc__ or ""),
        )
