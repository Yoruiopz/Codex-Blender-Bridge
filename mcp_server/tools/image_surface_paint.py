"""Typed orthographic base-surface painting; independent of Blender imports."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding
from .image_paint import RGBA, UV, ImageMask, Unit, _mask_name

Name = Annotated[StrictStr, Field(min_length=1, max_length=63), AfterValidator(_mask_name)]
WorldNumber = Annotated[StrictFloat, Field(ge=-1e9, le=1e9, allow_inf_nan=False)]
WorldPoint = Annotated[list[WorldNumber], Field(min_length=3, max_length=3)]
Positive = Annotated[StrictFloat, Field(ge=1e-8, le=1e6, allow_inf_nan=False)]
Faces = Annotated[list[Annotated[StrictInt, Field(ge=0, le=2047)]], Field(min_length=1, max_length=256)]
TOOL_DATA = (
    ("image.paint_surface_version", "Project bounded orthographic world strokes/raw stencils through explicit opaque geometry into a NEW UV image; preserve inputs and verify pixels/appearance.", True, ("EDIT_MATERIALS", "INSPECT_SCENE")),
    ("image.paint_surface_job_start", "Accept one frozen-input surface paint job; private overlap/projection/visibility/painting yields after delivery, poll final pixel/recovery evidence.", True, ("EDIT_MATERIALS", "INSPECT_SCENE")),
)


class OrthographicProjector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    origin: WorldPoint
    direction: WorldPoint
    up: WorldPoint
    width: Positive
    height: Positive
    near: Annotated[StrictFloat, Field(ge=0, le=1e6, allow_inf_nan=False)]
    far: Positive

    @model_validator(mode="after")
    def reviewed_frame(self):
        if self.far <= self.near:
            raise ValueError("far must exceed near")
        length = sum(value*value for value in self.direction)**.5
        up_length = sum(value*value for value in self.up)**.5
        if length < 1e-12 or up_length < 1e-12:
            raise ValueError("direction and up must be nonzero")
        a, b = [v/length for v in self.direction], [v/up_length for v in self.up]
        cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
        if sum(value*value for value in cross)**.5 < 1e-12:
            raise ValueError("direction and up must be independent")
        return self


class SurfaceStroke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    points: Annotated[list[UV], Field(min_length=1, max_length=128)]
    radius_world: Positive
    color: RGBA
    hardness: Unit = .8
    opacity: Unit = 1.
    blend: Literal["MIX", "ERASE_ALPHA"] = "MIX"


class ImageSurfacePaintTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def image_paint_surface_version(self, image_name: Name, new_name: Name, object_name: Name, uv_layer: Name,
                                         face_indices: Faces, projector: OrthographicProjector,
                                         strokes: Annotated[list[SurfaceStroke], Field(min_length=1, max_length=32)],
                                         occluder_objects: Annotated[list[Name], Field(max_length=8)] | None = None,
                                         stencil: ImageMask | None = None) -> Any:
        """Project explicit orthographic WORLD strokes onto scoped base faces/UV texel centres, creating a NEW unique float image. Requires EDIT_MATERIALS + INSPECT_SCENE, Object Mode; independent visible unanimated base mesh, no parent/constraint/modifier/shape keys, positive nonsingular transform. Explicit UV layer entirely [0,1]; 1-256 distinct nonhidden faces, <=4096 vertices/2048 faces per object, <=512 target/1024 total triangles, <=8 named additional opaque occluders. Complete target self-occludes; other scene objects/material transparency are not inferred. Front-facing only; ambiguous coincident depth, distinct surface UV boundary mapping, degenerate geometry and positive-area scoped UV overlap fail closed. Projector origin/direction/up define a normalized world frame, width/height and near/far; stroke points normalized bottom-left, radius in world plane, smoothstep hardness/max segment coverage, <=32 strokes/256 total segments. Source/stencil loaded local unanimated RGBA <=1,048,576 pixels; byte sRGB converts explicitly, linear COLOR source-over/ERASE_ALPHA, Non-Color DATA MIX only. Raw stencil R/G/B/A, finite [0,1], bilinear pixel-centre edge clamp inside projector, ZERO outside even inverted; no luminance/color/unpremultiply. FILE inputs need live approved-folder/external-file consent. Copy-on-write preserves source, stencil, geometry, consumers and context; no binding/file write/save. Native allocation/copy/readback/full input validation are bounded but uninterruptible. Failed owned allocation cleanup needs live DELETE_OBJECTS; retained effects require reinspection. Inspect complete pixels, explicitly bind/capture/compare and verify recovery; no full PAINT/undo/Windows acceptance claim."""
        values = self._values(image_name, new_name, object_name, uv_layer, face_indices, projector, strokes, occluder_objects, stencil)
        return await self.registry.call("image.paint_surface_version", values)

    async def image_paint_surface_job_start(self, image_name: Name, new_name: Name, object_name: Name, uv_layer: Name,
                                           face_indices: Faces, projector: OrthographicProjector,
                                           strokes: Annotated[list[SurfaceStroke], Field(min_length=1, max_length=32)],
                                           occluder_objects: Annotated[list[Name], Field(max_length=8)] | None = None,
                                           stencil: ImageMask | None = None,
                                           time_limit_seconds: Annotated[StrictFloat, Field(ge=1, le=300, allow_inf_nan=False)] = 60.) -> Any:
        """Accept a frozen-input orthographic surface paint JOB, not completed painting. Same geometry/UV/stencil/color/consent contract as image.paint_surface_version, with job-only source and stencil admission up to16,777,216 pixels each (4096 square); synchronous surface versions remain1M. Shared single image-job owner; overlap checks, projection, visibility rays, stencil validation and private painting yield AFTER delivery, with explicit <=33,554,432 each candidate/ray-triangle/segment tests. More complex work can exceed these limits after acceptance. Complete selected-UV ownership and ambiguity checks use64x64 tiles with <=16KiB scratch; normalized-source comparison retains no full baseline. No large footprint precomputation at acceptance. Native bounded source/stencil/geometry capture, tessellation/dependency update, final complete revalidation/copy/allocation/readback and undo are not preemptible; CPU slice is not a hard latency/memory cap. Poll jobs.inspect/list and retain owner connection. Pause holds private work while deadline runs; cancellation/disconnect/emergency before publication discards private work. Live permissions, source/stencil FILE proofs and exact geometry/UV/transform scope revalidate after checkpoint callbacks before new-image writes. One finalized native publication boundary, no generic bake queue/batch nesting. Late failure/cancel may retain a new image; inspect possible_mutation, requested/retained output and recovery evidence, never infer rollback from CANCELLED. No binding/save/file export; independently inspect complete pixels/inputs, bind/capture/compare and verify native recovery. Reported private-buffer estimates include guarded reentrant input/output readbacks and exclude native/GPU/undo/allocator costs; this is not out-of-core. Real4K native completion within300s, memory/cancellation and appearance qualification require direct retained evidence. Session-local foundation, not full PAINT or platform release acceptance."""
        values = self._values(image_name, new_name, object_name, uv_layer, face_indices, projector, strokes, occluder_objects, stencil)
        values["time_limit_seconds"] = time_limit_seconds
        return await self.registry.call("image.paint_surface_job_start", values)

    @staticmethod
    def _values(image_name, new_name, object_name, uv_layer, faces, projector, strokes, occluders, stencil):
        values = {"image_name": image_name, "new_name": new_name, "object_name": object_name, "uv_layer": uv_layer,
                  "face_indices": faces, "projector": projector.model_dump(), "strokes": [stroke.model_dump() for stroke in strokes]}
        if occluders is not None:
            values["occluder_objects"] = occluders
        if stencil is not None:
            values["stencil"] = stencil.model_dump()
        return values

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, handler, handler.__doc__ or "") for name, handler in (
            ("image.paint_surface_version", self.image_paint_surface_version),
            ("image.paint_surface_job_start", self.image_paint_surface_job_start)))


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="materials", description=description, modifying=modifies,
                             required_permissions=permissions) for name, description, modifies, permissions in TOOL_DATA)
