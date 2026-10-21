"""Typed previewed explicit-rail mesh slide wrappers."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, StrictStr, with_config
from typing_extensions import TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

TOOL_DATA = (
    ("mesh.slide_preview", "Preview bounded selected vertex/edge slides along explicit topology rails.", False, ("INSPECT_SCENE",)),
    ("mesh.vertex_slide", "Apply fingerprinted vertex slides on explicit neighboring rails, preserving topology and UVs.", True, ("EDIT_MESH",)),
    ("mesh.edge_slide", "Apply fingerprinted selected-chain edge slides on explicit neighboring rails.", True, ("EDIT_MESH",)),
)
TOOL_NAMES = tuple(row[0] for row in TOOL_DATA)


@with_config(ConfigDict(strict=True, extra="forbid"))
class SlideTarget(TypedDict):
    vertex_index: Annotated[StrictInt, Field(ge=0, le=199_999)]
    target_vertex_index: Annotated[StrictInt, Field(ge=0, le=199_999)]


Targets = Annotated[list[SlideTarget], Field(min_length=1, max_length=4096)]
Factor = Annotated[StrictFloat, Field(ge=0., le=.95, allow_inf_nan=False)]
Distance = Annotated[StrictFloat, Field(ge=1e-9, le=1e6, allow_inf_nan=False)]
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="mesh", description=description,
        modifying=modifying, required_permissions=permissions)
        for name, description, modifying, permissions in TOOL_DATA)


class MeshSlideTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def mesh_slide_preview(self, object_name: StrictStr, selection_id: StrictStr,
        mode: Literal["VERTEX", "EDGE"], targets: Targets, factor: Factor, max_distance: Distance) -> Any:
        """Preview one active local single-user Edit Mesh with a fresh selection reference. Each explicit moving vertex targets one adjacent visible stationary rail vertex; factor 0..0.95 interpolates in local space, bounded by max_distance. Edge mode requires one complete connected nonbranching selected chain/loop with one rail per endpoint vertex. Reject shape keys, hidden/nonmanifold rails and triangle/quad fan collapse/inversion. Returns source/UV fingerprint and up to 64 measured points; no inferred rail side, surface projection, collision or full retopology claim."""
        return await self.registry.call("mesh.slide_preview", {"object_name": object_name,
            "selection_id": selection_id, "mode": mode, "targets": targets,
            "factor": factor, "max_distance": max_distance})

    async def mesh_vertex_slide(self, object_name: StrictStr, selection_id: StrictStr,
        targets: Targets, factor: Factor, max_distance: Distance, expected_fingerprint: Fingerprint) -> Any:
        """Apply exactly a current VERTEX slide preview. Direct coordinate writes preserve topology, selection, all UV layers/pins and non-target vertices; verify shape and native recovery independently. Cancellation/local failure attempts scoped restoration only with live mesh-edit permission. A revoked grant or interleaved replacement can require explicit native recovery."""
        return await self.registry.call("mesh.vertex_slide", {"object_name": object_name,
            "selection_id": selection_id, "targets": targets, "factor": factor,
            "max_distance": max_distance, "expected_fingerprint": expected_fingerprint})

    async def mesh_edge_slide(self, object_name: StrictStr, selection_id: StrictStr,
        targets: Targets, factor: Factor, max_distance: Distance, expected_fingerprint: Fingerprint) -> Any:
        """Apply exactly a current EDGE slide preview to the referenced chain/loop; explicit per-vertex neighboring rails determine direction. Preserves mesh topology/material assignment/UVs/selection. This is a bounded coordinate revision, not automatic surface retopology or global self-intersection acceptance."""
        return await self.registry.call("mesh.edge_slide", {"object_name": object_name,
            "selection_id": selection_id, "targets": targets, "factor": factor,
            "max_distance": max_distance, "expected_fingerprint": expected_fingerprint})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in (
            ("mesh.slide_preview", self.mesh_slide_preview), ("mesh.vertex_slide", self.mesh_vertex_slide),
            ("mesh.edge_slide", self.mesh_edge_slide)))
