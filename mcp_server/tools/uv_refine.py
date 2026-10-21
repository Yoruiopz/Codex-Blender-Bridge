"""Strict explicit-corner UV align/stitch/relax wrappers."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, StrictStr, with_config
from typing_extensions import TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

TOOL_DATA = (
    ("uv.align", "Align explicit UV corners to an exact U/V coordinate while preserving pins and face orientation.", True, ("EDIT_MESH",)),
    ("uv.stitch", "Copy explicit same-vertex UV corner correspondences to fixed anchors without welding mesh topology.", True, ("EDIT_MESH",)),
    ("uv.relax", "Relax one complete explicit UV island with fixed boundaries/pins and bounded displacement.", True, ("EDIT_MESH",)),
)
TOOL_NAMES = tuple(row[0] for row in TOOL_DATA)


@with_config(ConfigDict(strict=True, extra="forbid"))
class RefineCorner(TypedDict):
    face_index: Annotated[StrictInt, Field(ge=0, le=199_999)]
    corner_index: Annotated[StrictInt, Field(ge=0, le=199_999)]


@with_config(ConfigDict(strict=True, extra="forbid"))
class StitchPair(TypedDict):
    source: RefineCorner
    target: RefineCorner


Coordinate = Annotated[StrictFloat, Field(ge=-1e6, le=1e6, allow_inf_nan=False)]


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="uv", description=description,
        modifying=modifying, required_permissions=permissions)
        for name, description, modifying, permissions in TOOL_DATA)


class UVRefineTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def uv_align(self, object_name: StrictStr, uv_layer: StrictStr, selection_id: StrictStr,
        corners: Annotated[list[RefineCorner], Field(min_length=1, max_length=20000)],
        axis: Literal["U", "V"], value: Coordinate) -> Any:
        """Align explicit face corners in a fresh referenced Edit Mesh scope. Pins stay fixed; a pinned corner off the requested line rejects before editing. Preserves all other UV layers, pin/selection state and mesh geometry; rejects triangle/quad fan collapse/inversion. Explicit target UV units, no implicit UV-editor selection or artistic-quality verdict."""
        return await self.registry.call("uv.align", {"object_name": object_name, "uv_layer": uv_layer,
            "selection_id": selection_id, "corners": corners, "axis": axis, "value": value})

    async def uv_stitch(self, object_name: StrictStr, uv_layer: StrictStr, selection_id: StrictStr,
        pairs: Annotated[list[StitchPair], Field(min_length=1, max_length=2048)],
        max_distance: Annotated[StrictFloat, Field(ge=1e-9, le=1e6, allow_inf_nan=False)] = .25) -> Any:
        """Copy fixed source corners to explicit unique target corners of the SAME mesh vertex, within max_distance in UV units. Both corners must lie in fresh face-reference scope. Anchors cannot also be targets; pinned targets cannot move. Preserves geometry/pins/other layers/context; no topology welding, automatic seam correspondence or complete-island merge claim."""
        return await self.registry.call("uv.stitch", {"object_name": object_name, "uv_layer": uv_layer,
            "selection_id": selection_id, "pairs": pairs, "max_distance": max_distance})

    async def uv_relax(self, object_name: StrictStr, uv_layer: StrictStr, selection_id: StrictStr,
        face_indices: Annotated[list[Annotated[StrictInt, Field(ge=0, le=199999)]], Field(min_length=1, max_length=4096)],
        iterations: Annotated[StrictInt, Field(ge=1, le=50)] = 10,
        strength: Annotated[StrictFloat, Field(ge=1e-6, le=.5, allow_inf_nan=False)] = .5,
        max_displacement: Annotated[StrictFloat, Field(ge=1e-9, le=1000., allow_inf_nan=False)] = .25) -> Any:
        """Relax exactly one complete current UV island explicitly enumerated inside a fresh face-selection reference. Continuity uses exact matching UVs across shared manifold edges; no near-coordinate welding. Uniform Laplacian smoothing fixes boundary and pinned nodes; at most 4096 corners/200000 node-iterations. Planning rejects per-face fan inversions and displacement beyond the explicit UV bound before any write. Not conformal unwrap, texel-density or artistic-quality certification."""
        return await self.registry.call("uv.relax", {"object_name": object_name, "uv_layer": uv_layer,
            "selection_id": selection_id, "face_indices": face_indices, "iterations": iterations,
            "strength": strength, "max_displacement": max_displacement})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in (
            ("uv.align", self.uv_align), ("uv.stitch", self.uv_stitch), ("uv.relax", self.uv_relax)))
