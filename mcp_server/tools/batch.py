"""One-round-trip serial structured workflows. Blender authorizes every step."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("batch.plan", "Preflight 1-32 structured steps for shape and static permissions, not scene state or handler arguments.", False, ()),
    ("batch.execute", "Run 1-32 structured steps serially; one logical undo marker, stop on error, no atomic rollback.", True, ()),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="batch", description=description, modifying=modifies)
                 for name, description, modifies, _permissions in TOOL_DATA)


class BatchTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def plan(self, steps: list[dict[str, Any]], label: str = "Structured edit") -> Any:
        """Check step shape/toolsets/static permissions only; does not simulate edits or validate Blender targets.

        Each step is {id?: string, method: dotted tool name, params: object}.
        Enable the batch toolset AND each child toolset first. No scripts, render,
        capture, save, undo, lifecycle, nested batches, or result substitutions.
        """
        return await self.registry.call("batch.plan", {"steps": steps, "label": label})

    async def execute(
        self, steps: list[dict[str, Any]], label: str = "Structured edit", time_limit_seconds: float = 10.0
    ) -> Any:
        """Run 1-32 explicit {id?, method, params} steps sequentially in one Blender request.

        Stops on first error/deadline/disconnect at step boundaries. Partial work
        remains and must be reinspected. One best-effort logical undo marker, not
        atomic rollback. Each result is capped at 16 KiB with explicit truncation.
        Blender C calls cannot be interrupted. Prefer short independent structured
        actions with known exact names; inspect and capture separately afterward.
        """
        return await self.registry.call("batch.execute", {
            "steps": steps, "label": label, "time_limit_seconds": time_limit_seconds,
        })

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (MCPToolBinding("batch.plan", self.plan, self.plan.__doc__ or ""),
                MCPToolBinding("batch.execute", self.execute, self.execute.__doc__ or ""))
