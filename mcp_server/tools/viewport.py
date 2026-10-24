"""Always-available visual inspection wrapper."""

from __future__ import annotations

from typing import Any

from pydantic import StrictBool

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
        frame_object: StrictBool = False,
    ) -> Any:
        """Capture a viewport PNG; optionally frame an exact named object in a desktop Object-mode view. Temporary settings are restored; Render Result is replaced."""

        return await self.registry.call(
            "viewport.capture",
            params(
                view=view,
                shading=shading,
                include_overlays=include_overlays,
                object_name=object_name,
                resolution=resolution,
                frame_object=frame_object,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("viewport.capture", self.viewport_capture, self.viewport_capture.__doc__ or ""),
        )
