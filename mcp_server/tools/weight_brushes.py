"""Typed MCP wrappers for bounded geometry-aware skin weights."""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params


class WeightDab(TypedDict):
    center: list[float]
    radius: float
    strength: float
    weight: float


class GroupMapping(TypedDict):
    source_group: str
    target_group: str


TOOL_DATA = (
    ("weights.brush_stroke", "Apply 1-32 explicit bounded spherical weight dabs to named vertices/group, preserving other memberships; no auto normalization."),
    ("weights.mirror_geometric", "Reflect explicit source vertices across an explicit LOCAL/WORLD plane; require unique one-to-one bounded correspondence and exact group mapping."),
    ("weights.transfer_surface", "Transfer explicit mapped groups through closest base-mesh triangles and barycentric weights, rejecting distant/ambiguous correspondence."),
)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="weights", description=description, modifying=True,
                             required_permissions=("EDIT_MESH",)) for name, description in TOOL_DATA)


class WeightBrushTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def weights_brush_stroke(
        self, object_name: str, group_name: str, vertex_indices: list[int], strokes: list[WeightDab],
        coordinate_space: Literal["LOCAL", "WORLD"], blend_mode: Literal["MIX", "ADD", "SUBTRACT"],
        falloff: Literal["CONSTANT", "LINEAR", "SMOOTH"], protected_groups: list[str] | None = None,
    ) -> Any:
        """Brush explicit base vertices of one unlocked group; locked/unmentioned groups remain unchanged."""
        return await self.registry.call("weights.brush_stroke", params(
            object_name=object_name, group_name=group_name, vertex_indices=vertex_indices, strokes=strokes,
            coordinate_space=coordinate_space, blend_mode=blend_mode, falloff=falloff,
            protected_groups=protected_groups,
        ))

    async def weights_mirror_geometric(
        self, object_name: str, source_vertex_indices: list[int], vertex_indices: list[int],
        group_mapping: list[GroupMapping], axis: Literal["X", "Y", "Z"], plane_offset: float,
        coordinate_space: Literal["LOCAL", "WORLD"], max_distance: float,
        protected_groups: list[str] | None = None,
    ) -> Any:
        """Mirror frozen source weights to unique nearby counterparts across an explicit metric plane."""
        return await self.registry.call("weights.mirror_geometric", params(
            object_name=object_name, source_vertex_indices=source_vertex_indices, vertex_indices=vertex_indices,
            group_mapping=group_mapping, axis=axis, plane_offset=plane_offset,
            coordinate_space=coordinate_space, max_distance=max_distance, protected_groups=protected_groups,
        ))

    async def weights_transfer_surface(
        self, source_object: str, object_name: str, source_polygon_indices: list[int], vertex_indices: list[int],
        group_mapping: list[GroupMapping], coordinate_space: Literal["LOCAL", "WORLD"], max_distance: float,
        protected_groups: list[str] | None = None,
    ) -> Any:
        """Sample explicit base polygons; LOCAL uses the target's local frame for both meshes, WORLD uses world distance."""
        return await self.registry.call("weights.transfer_surface", params(
            source_object=source_object, object_name=object_name, source_polygon_indices=source_polygon_indices,
            vertex_indices=vertex_indices, group_mapping=group_mapping, coordinate_space=coordinate_space,
            max_distance=max_distance, protected_groups=protected_groups,
        ))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, handler, handler.__doc__ or "") for name, handler in (
            ("weights.brush_stroke", self.weights_brush_stroke),
            ("weights.mirror_geometric", self.weights_mirror_geometric),
            ("weights.transfer_surface", self.weights_transfer_surface),
        ))
