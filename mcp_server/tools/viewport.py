"""Always-available visual inspection wrapper."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class ViewportTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def viewport_capture(
        self,
        view: str = "current",
        shading: str = "solid",
        include_overlays: bool = True,
        object_name: str | None = None,
        resolution: list[int] | None = None,
    ) -> Any:
        """Capture a viewport PNG for qualitative visual verification."""

        return await self.registry.call(
            "viewport.capture",
            params(
                view=view,
                shading=shading,
                include_overlays=include_overlays,
                object_name=object_name,
                resolution=resolution,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("viewport.capture", self.viewport_capture, self.viewport_capture.__doc__ or ""),
        )
