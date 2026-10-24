"""Always-available bridge, checkpoint, and local registry wrappers."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictInt, StrictStr

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class CoreTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def bridge_status(self) -> Any:
        """Report Blender bridge, project, mode, and permission status."""

        return await self.registry.call("bridge.status")

    async def bridge_task_set(self, description: str) -> Any:
        """Show the current high-level task in Blender's bridge panel."""

        return await self.registry.call("bridge.task.set", {"description": description})

    async def jobs_inspect(self, job_id: Annotated[StrictStr, Field(pattern=r"^job_[0-9a-f]{32}$")]) -> Any:
        """Inspect session-local image painting, export/reimport, snapshot/recovery and bounded rigid-evaluation jobs: state/revision, progress, final result/error and retained effects. INSPECT_SCENE required. SUCCEEDED is completion; start acceptance is not. Scene native_effects reports selected declared intervals, not complete native state or cache coverage. CANCELLED/FAILED can retain partial frame/cache effects without context restoration; unresolved Scene receipts survive ordinary 32-entry display-history eviction. Image external effects and packed recovery evidence keep their separate meanings. Packed memory needs an authorized save for durability, and native undo does not remove disk output. Polling does not evict operation history."""
        return await self.registry.call("jobs.inspect", {"job_id": job_id})

    async def jobs_list(self, limit: Annotated[StrictInt, Field(ge=1, le=32)] = 10) -> Any:
        """List bounded session-local image and rigid-evaluation jobs, newest first (active then terminal), plus unresolved Scene receipts beyond display-history eviction. INSPECT_SCENE required; explicit truncation, one shared active job and 32 terminal summaries. Inspect native_effects for selected rigid intervals and external_effects/recovery_evidence/evidence_observation_unknown for image jobs. Packed memory requires an authorized save; export files can survive cancellation and native undo. No durable queue, general solver or asynchronous bake claim."""
        return await self.registry.call("jobs.list", {"limit": limit})

    async def jobs_cancel(self, job_id: Annotated[StrictStr, Field(pattern=r"^job_[0-9a-f]{32}$")]) -> Any:
        """Request cancellation of an exact image or rigid-evaluation job, even while paused. Does not authorize scene changes, restoration or deletion. Poll terminal status; cancellation takes effect at cooperative safe points, cannot preempt native calls and never promises rollback. Inspect possible-mutation/recovery, selected native interval and external-file evidence. Stopped rigid evaluation retains partial frame/cache state; published image files survive cancel/native undo."""
        return await self.registry.call("jobs.cancel", {"job_id": job_id})

    async def bridge_task_clear(self) -> Any:
        """Clear the current task from Blender's bridge panel."""

        return await self.registry.call("bridge.task.clear")

    async def checkpoint_create(self, description: str | None = None) -> Any:
        """Create a logical checkpoint before meaningful modification."""

        return await self.registry.call(
            "checkpoint.create", params(description=description)
        )

    async def checkpoint_undo_last(
        self,
        confirm_global_undo: bool = False,
        restore_snapshot: bool = False,
    ) -> Any:
        """Confirm global-undo risk; opt into restore_snapshot for verified operation-boundary navigation."""

        return await self.registry.call(
            "checkpoint.undo_last",
            {"confirm_global_undo": confirm_global_undo, "restore_snapshot": restore_snapshot},
        )

    async def checkpoint_list(self, limit: int = 50) -> Any:
        """List checkpoint labels, history and unverified/expired native recovery availability. Recovery controls remain available without INSPECT_SCENE, but detailed asynchronous-job file/image evidence is redacted unless that Blender permission is enabled; local audit records are retained unchanged."""

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
            MCPToolBinding("jobs.inspect", self.jobs_inspect, self.jobs_inspect.__doc__ or ""),
            MCPToolBinding("jobs.list", self.jobs_list, self.jobs_list.__doc__ or ""),
            MCPToolBinding("jobs.cancel", self.jobs_cancel, self.jobs_cancel.__doc__ or ""),
            MCPToolBinding("bridge.status", self.bridge_status, self.bridge_status.__doc__ or ""),
            MCPToolBinding("bridge.task.set", self.bridge_task_set, self.bridge_task_set.__doc__ or ""),
            MCPToolBinding("bridge.task.clear", self.bridge_task_clear, self.bridge_task_clear.__doc__ or ""),
            MCPToolBinding("checkpoint.create", self.checkpoint_create, self.checkpoint_create.__doc__ or ""),
            MCPToolBinding("checkpoint.undo_last", self.checkpoint_undo_last, self.checkpoint_undo_last.__doc__ or ""),
            MCPToolBinding("checkpoint.list", self.checkpoint_list, self.checkpoint_list.__doc__ or ""),
            MCPToolBinding("toolsets.list", self.toolsets_list, self.toolsets_list.__doc__ or ""),
            MCPToolBinding("toolsets.enable", self.toolsets_enable, self.toolsets_enable.__doc__ or ""),
            MCPToolBinding("toolsets.disable", self.toolsets_disable, self.toolsets_disable.__doc__ or ""),
        )
