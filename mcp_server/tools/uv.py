"""Lazy MCP wrappers and definitions for structured UV operations."""

from __future__ import annotations

import math
from typing import Any

from pydantic import ConfigDict, StrictBool, StrictFloat, with_config
from typing_extensions import TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
    ("uv.coordinates_set", "Set exact face-corner UV coordinates within a validated face selection reference.", True),
    ("uv.transform", "Transform selected-face UV corners using explicit pivot, scale, rotation and offset; respect pins by default.", True),
    ("uv.pin", "Pin or unpin selected-face UV corners without changing their coordinates.", True),
    ("uv.layer_create", "Create a zero UV layer or copy UVs/pins in Object Mode; copy per-layer selection where available, otherwise preserve mesh-global selection.", True),
    ("uv.layer_rename", "Rename an Object Mode UV layer; named consumers are not rewritten.", True),
    ("uv.layer_activate", "Activate an Object Mode UV layer and optionally make it the render/clone layer.", True),
    ("uv.layer_remove", "Remove an Object Mode UV layer only with explicit data-loss confirmation.", True),
    ("uv.inspect", "Inspect bounded UV layers, selection, bounds, and island connectivity.", False),
    ("uv.unwrap", "Unwrap selected faces with explicit method and margin.", True),
    ("uv.smart_project", "Smart-project selected faces using bounded projection settings.", True),
    ("uv.pack_islands", "Pack selected UV islands using bounded margin settings.", True),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"uv.unwrap", "uv.smart_project", "uv.pack_islands", "uv.coordinates_set", "uv.transform", "uv.layer_remove"})


@with_config(ConfigDict(strict=True, extra="forbid"))
class UVCorner(TypedDict):
    face_index: int
    corner_index: int


@with_config(ConfigDict(strict=True, extra="forbid"))
class UVCoordinateUpdate(UVCorner):
    uv: list[float]


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

    async def uv_coordinates_set(
        self, object_name: str, uv_layer: str, selection_id: str, updates: list[UVCoordinateUpdate],
    ) -> Any:
        """Set 1-20,000 unique face/corner UVs on one local single-user active Edit Mode mesh. Requires a face selection reference; indices outside it are rejected before mutation. Coordinates are finite within +/-1e6, explicitly editable even when pinned. Preserves pins, selection and other layers; reinspect afterwards."""
        return await self.registry.call("uv.coordinates_set", params(
            object_name=object_name, uv_layer=uv_layer, selection_id=selection_id, updates=updates,
        ))

    async def uv_transform(
        self, object_name: str, uv_layer: str, selection_id: str | None = None,
        offset: list[StrictFloat] | None = None, scale: list[StrictFloat] | None = None,
        pivot: list[StrictFloat] | None = None, rotation: StrictFloat = 0.0, respect_pins: StrictBool = True,
        corners: list[UVCorner] | None = None,
    ) -> Any:
        """Transform selected/referenced-face UVs on one local single-user active Edit Mode mesh. Optional exact corners require a face selection_id. Scale about explicit pivot (default origin), rotate counterclockwise in radians, then offset. Two-component vectors default to zero offset/pivot and unit scale. Skip pinned corners by default. No implicit island/UV-editor selection, packing or layer activation."""
        return await self.registry.call("uv.transform", params(
            object_name=object_name, uv_layer=uv_layer, selection_id=selection_id,
            offset=offset, scale=scale, pivot=pivot, rotation=rotation, respect_pins=respect_pins,
            corners=corners,
        ))

    async def uv_pin(
        self, object_name: str, uv_layer: str, pinned: StrictBool = True, selection_id: str | None = None,
        corners: list[UVCorner] | None = None,
    ) -> Any:
        """Pin/unpin selected/referenced-face UVs on one local single-user active Edit Mode mesh; preserve coordinates, selection and other layers. Optional exact corners require a face selection_id and allow individual anchors. Never infer scope from UV-editor selection."""
        return await self.registry.call("uv.pin", params(
            object_name=object_name, uv_layer=uv_layer, pinned=pinned, selection_id=selection_id,
            corners=corners,
        ))

    async def uv_layer_create(self, object_name: str, new_name: str, copy_from: str | None = None) -> Any:
        """Create one of at most eight named UV layers on a local single-user Object Mode mesh (<=200,000 corners). Zero/unpinned by default; optional copy_from copies UVs and pins. UV selection is copied/zeroed when per-layer (4.5), otherwise preserved mesh-globally (5.1); inspect uv_selection_policy. Preserve existing active/render/clone roles; the first layer receives Blender defaults. Never switch modes implicitly."""
        return await self.registry.call("uv.layer_create", params(object_name=object_name, new_name=new_name, copy_from=copy_from))

    async def uv_layer_rename(self, object_name: str, uv_layer: str, new_name: str) -> Any:
        """Rename a UV layer on a local single-user Object Mode mesh. Reject name collisions with any mesh attribute. Named material/Geometry Nodes consumers are NOT rewritten; inspect dependencies."""
        return await self.registry.call("uv.layer_rename", params(object_name=object_name, uv_layer=uv_layer, new_name=new_name))

    async def uv_layer_activate(
        self, object_name: str, uv_layer: str, for_render: StrictBool = False, for_clone: StrictBool = False,
    ) -> Any:
        """Activate a local single-user Object Mode mesh UV layer. True for_render/for_clone also assigns that role; false leaves those roles unchanged. Does not alter UV coordinates or selection."""
        return await self.registry.call("uv.layer_activate", params(
            object_name=object_name, uv_layer=uv_layer, for_render=for_render, for_clone=for_clone,
        ))

    async def uv_layer_remove(self, object_name: str, uv_layer: str, confirm_remove: StrictBool = False) -> Any:
        """Remove a local single-user Object Mode mesh UV layer only with confirm_remove=true. Coordinates/pins/UV selection are lost; active roles may fall back and named consumers are not rewritten. Use a checkpoint and reinspection."""
        return await self.registry.call("uv.layer_remove", params(
            object_name=object_name, uv_layer=uv_layer, confirm_remove=confirm_remove,
        ))

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
            MCPToolBinding("uv.coordinates_set", self.uv_coordinates_set, self.uv_coordinates_set.__doc__ or ""),
            MCPToolBinding("uv.transform", self.uv_transform, self.uv_transform.__doc__ or ""),
            MCPToolBinding("uv.pin", self.uv_pin, self.uv_pin.__doc__ or ""),
            MCPToolBinding("uv.layer_create", self.uv_layer_create, self.uv_layer_create.__doc__ or ""),
            MCPToolBinding("uv.layer_rename", self.uv_layer_rename, self.uv_layer_rename.__doc__ or ""),
            MCPToolBinding("uv.layer_activate", self.uv_layer_activate, self.uv_layer_activate.__doc__ or ""),
            MCPToolBinding("uv.layer_remove", self.uv_layer_remove, self.uv_layer_remove.__doc__ or ""),
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
