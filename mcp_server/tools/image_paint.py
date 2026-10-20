"""Typed structured image-brush schemas, independent of Blender."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from ._common import MCPToolBinding

Unit = Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)]
UV = Annotated[list[Unit], Field(min_length=2, max_length=2)]


def _alpha(values: list[float]) -> list[float]:
    if values[3] > 1:
        raise ValueError("Alpha must be within [0,1]")
    return values


RGBA = Annotated[list[Annotated[StrictFloat, Field(ge=0, le=16, allow_inf_nan=False)]], Field(min_length=4, max_length=4), AfterValidator(_alpha)]
Pixel = Annotated[list[Annotated[StrictInt, Field(ge=0, le=4095)]], Field(min_length=2, max_length=2)]
Dimension = Annotated[StrictInt, Field(ge=1, le=4096)]


class BrushStroke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    points: Annotated[list[UV], Field(min_length=1, max_length=128)]
    radius_pixels: Annotated[StrictFloat, Field(ge=.5, le=256, allow_inf_nan=False)]
    color: RGBA
    opacity: Unit = 1.
    hardness: Unit = .8
    blend: Literal["MIX", "ERASE_ALPHA"] = "MIX"


class ImagePaintTools:
    registry: Any

    async def image_create(self, new_name: StrictStr, width: Dimension, height: Dimension,
                           role: Literal["COLOR", "DATA"] = "COLOR", color: RGBA | None = None) -> Any:
        """Create a NEW unique local generated float RGBA texture in Object Mode, up to 4096/axis and 1,048,576 pixels. COLOR is straight-alpha scene-linear Rec.709 RGB [0,16]; DATA is Non-Color RGBA [0,1]. Alpha [0,1] in both. Default opaque black. Normal creation needs EDIT_MATERIALS, not file/Python/save/deletion grants. Removing a failed owned allocation additionally needs live DELETE_OBJECTS; denied cleanup retains the image with possible-mutation evidence for confirmed recovery. No overwrite, binding, packing or file write. Verify pixels, bind explicitly and capture appearance; unsaved image data/history is not durable delivery."""
        values = {"new_name": new_name, "width": width, "height": height, "role": role}
        if color is not None:
            values["color"] = color
        return await self.registry.call("image.create", values)

    async def image_paint_version(self, image_name: StrictStr, new_name: StrictStr,
                                  strokes: Annotated[list[BrushStroke], Field(min_length=1, max_length=32)]) -> Any:
        """Paint a NEW named image version, never edit/rebind the original. Object Mode; loaded local unanimated STRAIGHT-alpha RGBA, <=1,048,576 pixels. Sources: byte sRGB (explicit linear conversion), Linear Rec.709 or Non-Color; float-sRGB and other OCIO roles unsupported. FILE reads additionally require approved-folder/external-file consent, including packed FILEs. UV points [0,1] use bottom-left origin; radius .5-256 image pixels, clipped/no wrapping; 32 strokes, 128 points/stroke, 256 total segments, 2M candidate tests. COLOR MIX is straight-alpha source-over; ERASE_ALPHA preserves RGB. DATA MIX interpolates all four channels, no color transform. Maximum smoothstep coverage per stroke avoids join overdraw; strokes accumulate in order. EDIT_MATERIALS required. Failed-allocation removal needs live DELETE_OBJECTS; denied cleanup retains truthful possible-mutation/recovery evidence. No native viewport/surface projection, painting masks, file writes or durable pixel undo; independently inspect the new pixels and old-source digest, bind explicitly, capture and verify native recovery."""
        return await self.registry.call("image.paint_version", {"image_name": image_name, "new_name": new_name,
                                         "strokes": [stroke.model_dump() for stroke in strokes]})

    async def image_inspect_pixels(self, image_name: StrictStr,
                                   samples: Annotated[list[Pixel], Field(max_length=64)] | None = None) -> Any:
        """Inspect already-loaded local simple RGBA buffers up to 1,048,576 pixels: full float32 little-endian digest, finite channel ranges/counts and up to 64 exact [x,y] samples from bottom-left origin. Raw stored floats, not display values or implicit color conversion. INSPECT_SCENE required; FILE data also needs approved path and ACCESS_EXTERNAL_FILES. No lazy loading/reload, pixels returned wholesale, mutation or appearance certification."""
        return await self.registry.call("image.inspect_pixels", {"image_name": image_name, "samples": samples or []})

    async def image_paint_job_start(self, image_name: StrictStr, new_name: StrictStr,
                                   strokes: Annotated[list[BrushStroke], Field(min_length=1, max_length=32)],
                                   time_limit_seconds: Annotated[StrictFloat, Field(ge=1, le=300, allow_inf_nan=False)] = 60.) -> Any:
        """Accept one source-frozen image.paint_version job, NOT a completed painting. Same brush/image/consent limits as the synchronous tool. Poll jobs.inspect/list (INSPECT_SCENE); retain the owning connection until terminal. CPU brush phases yield between main-thread slices. Cancellation/disconnect/deadline/emergency stop discards precommit work; pause holds it but deadline continues. Source identity/metadata/pixels and live grants are rechecked before one native undo-guarded publication in Object Mode. A missing native undo boundary refuses publication. Source copying, final validation, native image creation and readback are bounded but not preemptible. Late failure may retain an image when DELETE_OBJECTS cleanup is denied; inspect possible_mutation and finalized recovery flags, never assume CANCELLED means rollback. Session-local, not durable, one active job; no batch nesting, automatic binding, Python, saving or general bake jobs. Verify new/old pixels and appearance independently after SUCCEEDED."""
        return await self.registry.call("image.paint_job_start", {"image_name": image_name, "new_name": new_name,
            "strokes": [stroke.model_dump() for stroke in strokes], "time_limit_seconds": time_limit_seconds})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, handler, handler.__doc__ or "") for name, handler in (
            ("image.create", self.image_create), ("image.paint_version", self.image_paint_version),
            ("image.paint_job_start", self.image_paint_job_start),
            ("image.inspect_pixels", self.image_inspect_pixels)))
