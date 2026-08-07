"""Structured render inspection, configuration, and execution wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

RENDER_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("render.inspect", "Inspect an explicit scene's bounded render configuration.", False, ("INSPECT_SCENE",)),
    ("render.configure", "Configure engine, resolution, samples, image settings, and approved output path.", True, ("EDIT_RENDER",)),
    ("render.execute", "Render an explicit scene to a managed or approved local file and replace Render Result.", True, ("EDIT_RENDER", "CAPTURE_VIEWPORT")),
)
RENDER_TOOL_NAMES = tuple(item[0] for item in RENDER_TOOL_DATA)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="render",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in RENDER_TOOL_DATA
    )


class RenderTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def render_inspect(self, scene_name: str) -> Any:
        """Inspect an explicit scene's render engine, output, resolution, and samples."""

        return await self.registry.call("render.inspect", {"scene_name": scene_name})

    async def render_configure(
        self,
        scene_name: str,
        engine: str | None = None,
        width: int | None = None,
        height: int | None = None,
        resolution_percentage: int | None = None,
        fps: float | None = None,
        samples: int | None = None,
        film_transparent: bool | None = None,
        file_format: str | None = None,
        color_mode: str | None = None,
        use_file_extension: bool | None = None,
        output_filepath: str | None = None,
    ) -> Any:
        """Configure an explicit scene's render settings with bounded typed values."""

        return await self.registry.call(
            "render.configure",
            params(
                scene_name=scene_name,
                engine=engine,
                width=width,
                height=height,
                resolution_percentage=resolution_percentage,
                fps=fps,
                samples=samples,
                film_transparent=film_transparent,
                file_format=file_format,
                color_mode=color_mode,
                use_file_extension=use_file_extension,
                output_filepath=output_filepath,
            ),
        )

    async def render_execute(
        self,
        scene_name: str,
        filepath: str | None = None,
        file_format: str = "PNG",
        width: int | None = None,
        height: int | None = None,
        resolution_percentage: int | None = None,
        overwrite: bool = False,
    ) -> Any:
        """Render a scene to a managed temporary image or approved explicit path."""

        return await self.registry.call(
            "render.execute",
            params(
                scene_name=scene_name,
                filepath=filepath,
                file_format=file_format,
                width=width,
                height=height,
                resolution_percentage=resolution_percentage,
                overwrite=overwrite,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("render.inspect", self.render_inspect, self.render_inspect.__doc__ or ""),
            MCPToolBinding("render.configure", self.render_configure, self.render_configure.__doc__ or ""),
            MCPToolBinding("render.execute", self.render_execute, self.render_execute.__doc__ or ""),
        )


__all__ = ["RENDER_TOOL_DATA", "RENDER_TOOL_NAMES", "RenderTools", "load_definitions"]
