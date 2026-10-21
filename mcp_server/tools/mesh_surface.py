"""Typed explicit base-surface projection wrappers."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictFloat, StrictInt, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

TOOL_DATA = (
    ("mesh.surface_projection_preview", "Preview fresh selected vertices fitted to explicit base reference polygons with measured correspondence.", False, ("INSPECT_SCENE",)),
    ("mesh.project_to_surface", "Apply an exact current bounded base-surface projection preview, preserving supported custom data.", True, ("EDIT_MESH",)),
)
TOOL_NAMES = tuple(row[0] for row in TOOL_DATA)
Polygons = Annotated[list[Annotated[StrictInt, Field(ge=0, le=19_999)]], Field(min_length=1, max_length=256)]
Distance = Annotated[StrictFloat, Field(ge=1e-9, le=1e6, allow_inf_nan=False)]
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="mesh", description=description,
        modifying=modifying, required_permissions=permissions)
        for name, description, modifying, permissions in TOOL_DATA)


class MeshSurfaceTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def mesh_surface_projection_preview(self, object_name: StrictStr, selection_id: StrictStr,
        source_object: StrictStr, source_polygon_indices: Polygons, max_distance: Distance) -> Any:
        """Inspect one explicit local single-user Edit mesh and a distinct visible unmodified Object Mode base reference. Fit all 1-256 fresh referenced vertices to the nearest point of 1-256 named source polygons (at most 2048 source triangles and 262144 pairs). WORLD displacement must fit max_distance. Preview rounds to native float32 local coordinates, checks residual <=1e-6 world units, all target triangle/quad fans and bounded target contact completeness. Reject ambiguity, shape keys/custom normals/modifiers, unsupported attribute data, hidden affected geometry and unverified contact budgets. Returns a frozen source/target/context fingerprint and at most 64 correspondence records; no evaluated topology, offsets, automatic remesh or whole-scene collision claim."""
        return await self.registry.call("mesh.surface_projection_preview", {"object_name": object_name,
            "selection_id": selection_id, "source_object": source_object,
            "source_polygon_indices": source_polygon_indices, "max_distance": max_distance})

    async def mesh_project_to_surface(self, object_name: StrictStr, selection_id: StrictStr,
        source_object: StrictStr, source_polygon_indices: Polygons, max_distance: Distance,
        expected_fingerprint: Fingerprint) -> Any:
        """Apply exactly the current preview. Direct coordinate writes preserve topology, selection, untouched vertices, material bindings, all UV layers/pins and supported custom/deform/color data; source geometry stays unchanged. Every write gate checks current consent, exact native session, source identities/transforms/data and protected target data. Local recovery only restores still-owned outputs with live edit permission; cancellation, replaced data or revoked permission can require explicit native checkpoint recovery. Independently inspect distance, wire topology and silhouette afterward."""
        return await self.registry.call("mesh.project_to_surface", {"object_name": object_name,
            "selection_id": selection_id, "source_object": source_object,
            "source_polygon_indices": source_polygon_indices, "max_distance": max_distance,
            "expected_fingerprint": expected_fingerprint})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in (
            ("mesh.surface_projection_preview", self.mesh_surface_projection_preview),
            ("mesh.project_to_surface", self.mesh_project_to_surface)))
