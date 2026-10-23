"""Typed explicit open-chain bridge previews and publication."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictInt, StrictStr

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding

Index = Annotated[StrictInt, Field(ge=0, le=19_999)]
Material = Annotated[StrictInt, Field(ge=0, le=255)]
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]


class MeshChainTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def mesh_bridge_chains_preview(self, object_name: StrictStr, selection_id: StrictStr,
        rail_a_start: Index, rail_a_end: Index, rail_b_start: Index, rail_b_end: Index,
        material_index: Material = 0) -> Any:
        """Read-only preview of exactly two equal disjoint open boundary/wire chains, 2-64 vertices each, from a fresh edge selection. Four explicit endpoint indices choose direction and correspondence; no inferred pairing or winding. Planned quads are (a[i],a[i+1],b[i+1],b[i]); existing boundary winding must agree. Requires one active local editable single-user Edit mesh without modifiers, shape keys or custom normals, <=20000 output elements and bounded supported custom-data proof. Returns full ordered rails, faces/count deltas and a session/context/data fingerprint. Reject branches/cycles, hidden/interior edges, existing connecting edges and degenerate/folded quad fans. No general collision, evaluated topology or aesthetic-quality claim."""
        return await self.registry.call("mesh.bridge_chains_preview", {"object_name": object_name,
            "selection_id": selection_id, "rail_a_start": rail_a_start, "rail_a_end": rail_a_end,
            "rail_b_start": rail_b_start, "rail_b_end": rail_b_end, "material_index": material_index})

    async def mesh_bridge_chains(self, object_name: StrictStr, selection_id: StrictStr,
        rail_a_start: Index, rail_a_end: Index, rail_b_start: Index, rail_b_end: Index,
        expected_fingerprint: Fingerprint, material_index: Material = 0) -> Any:
        """Apply the exact current open-chain preview, adding k-1 quads/k connecting edges and merging no vertices. Preserve all original supported custom data, UV coordinates/pins, material bindings, vertex weights and selection/context. New faces use the existing material index and verified zero/unpinned UVs; unwrap separately. Rechecks live authority, exact native session and complete bounded old/published state before each write, retaining pre-checkpoint admission. Each verified face/material receives guarded normal/tessellation synchronization before another allocation. Nonbatchable. Failure/stop can leave partial, unverified and unsynchronized topology; no catch-time update/deletion runs after lost authority. derived_cache_sync counters retain earlier work without certifying current topology, safe evaluation or native recovery. rollback_verified remains false; confirmed Edit-session recovery requires separately established availability and native evidence. Capture wireframe/checker appearance; no project save or full ASSET-01 acceptance."""
        return await self.registry.call("mesh.bridge_chains", {"object_name": object_name,
            "selection_id": selection_id, "rail_a_start": rail_a_start, "rail_a_end": rail_a_end,
            "rail_b_start": rail_b_start, "rail_b_end": rail_b_end, "material_index": material_index,
            "expected_fingerprint": expected_fingerprint})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in (
            ("mesh.bridge_chains_preview", self.mesh_bridge_chains_preview),
            ("mesh.bridge_chains", self.mesh_bridge_chains)))
