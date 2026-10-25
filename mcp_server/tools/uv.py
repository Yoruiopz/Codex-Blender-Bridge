"""Lazy MCP wrappers and definitions for structured UV operations."""

from __future__ import annotations

import math
from typing import Any

from pydantic import ConfigDict, StrictBool, StrictFloat, StrictInt, with_config
from typing_extensions import TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
    ("uv.analyze", "Measure bounded triangulated UV overlap/winding, pixel anisotropy and world-unit texel density, with explicit completeness.", False),
    ("uv.capture_layout", "Capture a bounded UV-coordinate PNG without scene/UI/render changes; not a quality verdict.", False),
    ("uv.coordinates_set", "Set explicit face-corner UVs within a validated face reference. Bounded standalone local Edit Mode admission and exact before/after checks; inspect reported partial state after failure.", True),
    ("uv.transform", "Scale scoped UVs about a pivot, rotate, then offset; respect pins by default. Bounded standalone local Edit Mode admission and exact before/after checks; inspect partial failures.", True),
    ("uv.pin", "Pin or unpin scoped UV corners while preserving coordinates. Bounded standalone local Edit Mode admission and exact before/after checks; inspect reported partial state after failure.", True),
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
            required_permissions=("INSPECT_SCENE", "CAPTURE_VIEWPORT") if name == "uv.capture_layout" else
            (("EDIT_MESH",) if modifying else ("INSPECT_SCENE",)),
        )
        for name, description, modifying in TOOL_DATA
    )


class UVTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def uv_analyze(
        self, object_name: str, uv_layer: str, selected_only: StrictBool = False,
        selection_id: str | None = None, face_indices: list[StrictInt] | None = None,
        texture_resolution: list[StrictInt] | None = None, max_triangles: StrictInt = 8192,
        max_pair_tests: StrictInt = 200_000, max_reports: StrictInt = 64,
        anisotropy_warning: StrictFloat = 4., density_target: StrictFloat | None = None,
        density_tolerance: StrictFloat = .2,
    ) -> Any:
        """Read-only UV diagnostics using native base-mesh tessellation (Object/Edit Mode). Checks positive-area triangle intersections, mirrored/folded UVs, pixel-direction singular-value anisotropy and density in pixels per world unit, NOT meters. Declared resolution defaults to hypothetical 1024x1024; no image is inferred. Optional explicit face indices must stay within selected/referenced scope. Budget-limited/invalid/tessellation-missing coverage is incomplete, never clean. Max 20,000 triangles / 1,000,000 broadphase pair tests; reports bounded to 256. Stacks/mirrors may be intentional; no artistic/evaluated-mesh or Blender-overlay-equivalence claim. Reinspect/capture and compare the brief."""
        return await self.registry.call("uv.analyze", params(
            object_name=object_name, uv_layer=uv_layer, selected_only=selected_only, selection_id=selection_id,
            face_indices=face_indices, texture_resolution=texture_resolution, max_triangles=max_triangles,
            max_pair_tests=max_pair_tests, max_reports=max_reports, anisotropy_warning=anisotropy_warning,
            density_target=density_target, density_tolerance=density_tolerance,
        ))

    async def uv_capture_layout(
        self, object_name: str, uv_layer: str, selected_only: StrictBool = False,
        selection_id: str | None = None, size: StrictInt = 512, view: str = "UNIT_TILE",
    ) -> Any:
        """Create a managed temporary PNG from measured UV corners (Object/Edit Mode). Blue edges, red pins; U right/V up with equal scale. UNIT_TILE shows 0-1 and reports outside-view corners; FIT includes all scoped UVs. At most 4,096 faces/16,384 corners; narrow selected/reference scope if larger. Not a screenshot or overlap/stretch/texel-density verdict. No scene/UI/Render Result mutation; requires inspection and capture permissions, not external-file access."""
        return await self.registry.call("uv.capture_layout", params(
            object_name=object_name, uv_layer=uv_layer, selected_only=selected_only,
            selection_id=selection_id, size=size, view=view,
        ))

    async def uv_coordinates_set(
        self, object_name: str, uv_layer: str, selection_id: str, updates: list[UVCoordinateUpdate],
    ) -> Any:
        """Set explicit unique face/corner UVs within a validated face selection reference; corners outside it are refused. Coordinates remain explicitly editable when pinned. Standalone calls require an admitted local single-user active Edit Mode mesh. Live authority and exact retained before/after checks guard edits while preserving pins, selection and other layers. Unsupported state is refused; interruption or failure can leave reported partial state. Reinspect before retrying."""
        return await self.registry.call("uv.coordinates_set", params(
            object_name=object_name, uv_layer=uv_layer, selection_id=selection_id, updates=updates,
        ))

    async def uv_transform(
        self, object_name: str, uv_layer: str, selection_id: str | None = None,
        offset: list[StrictFloat] | None = None, scale: list[StrictFloat] | None = None,
        pivot: list[StrictFloat] | None = None, rotation: StrictFloat = 0.0, respect_pins: StrictBool = True,
        corners: list[UVCorner] | None = None,
    ) -> Any:
        """Transform selected/referenced-face UVs; optional exact corners require a face selection_id. Scale about explicit pivot (default origin), rotate counterclockwise in radians, then offset; defaults are zero offset/pivot and unit scale. Skip pinned corners by default. Standalone calls require an admitted local single-user active Edit Mode mesh with live authority and exact retained before/after checks, preserving selection and other layers. Unsupported state is refused; interruption or failure can leave reported partial state. Reinspect before retrying. Scope comes from faces, never implicit UV-editor selection."""
        return await self.registry.call("uv.transform", params(
            object_name=object_name, uv_layer=uv_layer, selection_id=selection_id,
            offset=offset, scale=scale, pivot=pivot, rotation=rotation, respect_pins=respect_pins,
            corners=corners,
        ))

    async def uv_pin(
        self, object_name: str, uv_layer: str, pinned: StrictBool = True, selection_id: str | None = None,
        corners: list[UVCorner] | None = None,
    ) -> Any:
        """Pin/unpin selected/referenced-face UV corners while preserving coordinates, selection and other layers. Optional exact corners require a face selection_id and allow individual anchors; never infer scope from UV-editor selection. Standalone calls require an admitted local single-user active Edit Mode mesh with live authority and exact retained before/after checks. Unsupported state is refused; interruption or failure can leave reported partial state. Reinspect before retrying."""
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
            MCPToolBinding("uv.analyze", self.uv_analyze, self.uv_analyze.__doc__ or ""),
            MCPToolBinding("uv.capture_layout", self.uv_capture_layout, self.uv_capture_layout.__doc__ or ""),
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
