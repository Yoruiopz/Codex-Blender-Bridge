"""Lazy MCP wrappers and definitions for structured UV operations."""

from __future__ import annotations

import math
from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
    ("uv.inspect", "Inspect bounded UV layers, selection, bounds, and island connectivity.", False),
    ("uv.unwrap", "Unwrap selected faces with explicit method and margin.", True),
    ("uv.smart_project", "Smart-project selected faces using bounded projection settings.", True),
    ("uv.pack_islands", "Pack selected UV islands using bounded margin settings.", True),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"uv.unwrap", "uv.smart_project", "uv.pack_islands"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="uv",
            description=description,
            modifying=modifying,
            required_permissions=("EDIT_MESH",) if modifying else ("INSPECT_SCENE",),
        )
        for name, description, modifying in TOOL_DATA
    )


class UVTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def uv_inspect(
        self,
        object_name: str,
        uv_layer: str | None = None,
        selected_only: bool = False,
        selection_id: str | None = None,
        max_islands: int = 100,
        include_coordinates: bool = False,
        coordinate_offset: int = 0,
        max_coordinates: int = 100,
    ) -> Any:
        """Inspect UV-layer/island state; optionally return up to 256 face-corner coordinates per page."""

        return await self.registry.call(
            "uv.inspect",
            params(
                object_name=object_name,
                uv_layer=uv_layer,
                selected_only=selected_only,
                selection_id=selection_id,
                max_islands=max_islands,
                include_coordinates=include_coordinates,
                coordinate_offset=coordinate_offset,
                max_coordinates=max_coordinates,
            ),
        )

    async def uv_unwrap(
        self,
        object_name: str,
        selection_id: str | None = None,
        uv_layer: str | None = None,
        create_if_missing: bool = True,
        method: str = "ANGLE_BASED",
        fill_holes: bool = True,
        correct_aspect: bool = True,
        use_subsurf_data: bool = False,
        margin: float = 0.001,
    ) -> Any:
        """Unwrap selected faces; a selection ID safely scopes a prior inspection."""

        return await self.registry.call(
            "uv.unwrap",
            params(
                object_name=object_name,
                selection_id=selection_id,
                uv_layer=uv_layer,
                create_if_missing=create_if_missing,
                method=method,
                fill_holes=fill_holes,
                correct_aspect=correct_aspect,
                use_subsurf_data=use_subsurf_data,
                margin=margin,
            ),
        )

    async def uv_smart_project(
        self,
        object_name: str,
        selection_id: str | None = None,
        uv_layer: str | None = None,
        create_if_missing: bool = True,
        angle_limit: float = math.radians(66.0),
        island_margin: float = 0.0,
        area_weight: float = 0.0,
        correct_aspect: bool = True,
        scale_to_bounds: bool = False,
    ) -> Any:
        """Smart-project selected faces with bounded angle, margin, and weighting."""

        return await self.registry.call(
            "uv.smart_project",
            params(
                object_name=object_name,
                selection_id=selection_id,
                uv_layer=uv_layer,
                create_if_missing=create_if_missing,
                angle_limit=angle_limit,
                island_margin=island_margin,
                area_weight=area_weight,
                correct_aspect=correct_aspect,
                scale_to_bounds=scale_to_bounds,
            ),
        )

    async def uv_pack_islands(
        self,
        object_name: str,
        selection_id: str | None = None,
        uv_layer: str | None = None,
        create_if_missing: bool = False,
        rotate: bool = True,
        scale: bool = True,
        margin: float = 0.001,
    ) -> Any:
        """Pack selected islands on an existing UV layer."""

        return await self.registry.call(
            "uv.pack_islands",
            params(
                object_name=object_name,
                selection_id=selection_id,
                uv_layer=uv_layer,
                create_if_missing=create_if_missing,
                rotate=rotate,
                scale=scale,
                margin=margin,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("uv.inspect", self.uv_inspect, self.uv_inspect.__doc__ or ""),
            MCPToolBinding("uv.unwrap", self.uv_unwrap, self.uv_unwrap.__doc__ or ""),
            MCPToolBinding("uv.smart_project", self.uv_smart_project, self.uv_smart_project.__doc__ or ""),
            MCPToolBinding("uv.pack_islands", self.uv_pack_islands, self.uv_pack_islands.__doc__ or ""),
        )


__all__ = [
    "DESTRUCTIVE_TOOL_NAMES",
    "TOOL_DATA",
    "TOOL_NAMES",
    "UVTools",
    "load_definitions",
]
