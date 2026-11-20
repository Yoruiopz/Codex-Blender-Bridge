"""Always-available project metadata and save wrappers."""

from __future__ import annotations

from typing import Any

from pydantic import StrictBool

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class ProjectTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def project_info(self) -> Any:
        """Inspect filepath, dirty state, scenes, timing, render, and Blender version."""

        return await self.registry.call("project.info")

    async def project_save(self, filepath: str | None = None, overwrite: bool = False) -> Any:
        """Save the current Blender project or Save As an absolute .blend path. Supply a path for the first save and set overwrite=True to replace an existing Save As target. Return the actual saved path or a structured error."""

        return await self.registry.call("project.save", params(filepath=filepath, overwrite=overwrite))

    async def project_save_dialog_state(self) -> Any:
        """Read Blender's native Save or Save As dialog and its proposed path if available. Use project.save with the intended absolute .blend path to save."""

        return await self.registry.call("project.save_dialog_state")

    async def project_checkpoint_status(self) -> Any:
        """Recheck the last retained project checkpoint's bytes and return its ID for recovery."""

        return await self.registry.call("project.checkpoint_status")

    async def project_checkpoint_reopen(
        self, checkpoint_id: str, confirm_reopen: bool, use_verified_backup: StrictBool = False,
    ) -> Any:
        """Reopen a verified checkpoint from a clean Object Mode project. Set confirm_reopen after confirming project replacement. Set use_verified_backup only to select the exact Blender backup reported by checkpoint status."""

        return await self.registry.call("project.checkpoint_reopen", params(
            checkpoint_id=checkpoint_id, confirm_reopen=confirm_reopen,
            use_verified_backup=True if use_verified_backup else None,
        ))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("project.info", self.project_info, self.project_info.__doc__ or ""),
            MCPToolBinding("project.save", self.project_save, self.project_save.__doc__ or ""),
            MCPToolBinding("project.save_dialog_state", self.project_save_dialog_state, self.project_save_dialog_state.__doc__ or ""),
            MCPToolBinding("project.checkpoint_status", self.project_checkpoint_status, self.project_checkpoint_status.__doc__ or ""),
            MCPToolBinding("project.checkpoint_reopen", self.project_checkpoint_reopen, self.project_checkpoint_reopen.__doc__ or ""),
        )
