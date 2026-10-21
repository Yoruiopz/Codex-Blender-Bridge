"""Typed structured image-brush schemas, independent of Blender."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

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


def _mask_name(value: str) -> str:
    if not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("Mask name must be nonblank without control characters")
    if len(value.encode("utf-8")) > 63:
        raise ValueError("Mask name must fit 63 UTF-8 bytes")
    return value


class ImageMask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    image_name: Annotated[StrictStr, Field(min_length=1, max_length=63), AfterValidator(_mask_name)]
    channel: Literal["R", "G", "B", "A"] = "R"
    invert: StrictBool = False


class ImagePaintTools:
    registry: Any

    async def image_create(self, new_name: StrictStr, width: Dimension, height: Dimension,
                           role: Literal["COLOR", "DATA"] = "COLOR", color: RGBA | None = None) -> Any:
        """Create a NEW unique local generated float RGBA texture in Object Mode, up to 4096/axis and 16,777,216 pixels (4K square). Native allocation/transfers/readback are not preemptible or included in job CPU budgets. COLOR is straight-alpha scene-linear Rec.709 RGB [0,16]; DATA is Non-Color RGBA [0,1]. Alpha [0,1] in both. Default opaque black. EDIT_MATERIALS required, not file/Python/save/deletion grants. Failed owned allocation cleanup additionally needs live DELETE_OBJECTS; denied cleanup retains possible-mutation/recovery evidence. No overwrite, binding, packing or file write. Use image.paint_job_start above 1,048,576 pixels; inspect with include_statistics=false for larger digests/samples. Independently verify pixels, appearance and recovery; unsaved images/history are not durable delivery."""
        values = {"new_name": new_name, "width": width, "height": height, "role": role}
        if color is not None:
            values["color"] = color
        return await self.registry.call("image.create", values)

    async def image_paint_version(self, image_name: StrictStr, new_name: StrictStr,
                                  strokes: Annotated[list[BrushStroke], Field(min_length=1, max_length=32)],
                                  mask: ImageMask | None = None) -> Any:
        """Paint a NEW named image version, never edit/rebind the original. Object Mode; loaded local unanimated STRAIGHT-alpha RGBA, <=1,048,576 pixels. Sources: byte sRGB (explicit linear conversion), Linear Rec.709 or Non-Color; float-sRGB and other OCIO roles unsupported. FILE reads additionally require approved-folder/external-file consent, including packed FILEs. UV points [0,1] use bottom-left origin; radius .5-256 image pixels, clipped/no wrapping; 32 strokes, 128 points/stroke, 256 total segments, 2M candidate tests. COLOR MIX is straight-alpha source-over; ERASE_ALPHA preserves RGB. DATA MIX interpolates all four channels, no color transform. Maximum smoothstep coverage per stroke avoids join overdraw; strokes accumulate in order. Optional mask selects an unanimated loaded local RGBA image's raw R/G/B/A channel (default R), finite [0,1], optionally inverted, with normalized pixel-centre bilinear edge-clamped sampling across different dimensions. No implicit luminance, color transform or unpremultiply; Non-Color recommended. Mask <=1M pixels synchronously; source and full mask preserved/revalidated. EDIT_MATERIALS required; FILE masks also need live external-file/path consent. Failed-allocation removal needs live DELETE_OBJECTS; denied cleanup retains truthful possible-mutation/recovery evidence. No native viewport/surface projection, sculpt/vertex masks, file writes or durable pixel undo; independently inspect the new pixels and both input digests, bind explicitly, capture and verify native recovery."""
        values: dict[str, Any] = {"image_name": image_name, "new_name": new_name, "strokes": [stroke.model_dump() for stroke in strokes]}
        if mask is not None:
            values["mask"] = mask.model_dump()
        return await self.registry.call("image.paint_version", values)

    async def image_inspect_pixels(self, image_name: StrictStr,
                                   samples: Annotated[list[Pixel], Field(max_length=64)] | None = None,
                                   include_statistics: StrictBool = True) -> Any:
        """Inspect already-loaded local simple RGBA buffers. Default include_statistics=true supports <=1,048,576 pixels and full digest/channel ranges/nonfinite counts. Explicit false allows <=16,777,216 pixels (4096/axis) for a COMPLETE float32 little-endian digest and up to 64 exact bottom-left [x,y] samples, but returns null ranges/nonfinite counts and analysis_complete=false: no statistics or finite-pixel certification. Raw stored floats, not display values or color conversion. INSPECT_SCENE required; FILE reads also need approved path and ACCESS_EXTERNAL_FILES. Native whole-buffer copying/hash are bounded but not preemptible. No lazy loading/reload, arrays returned wholesale, mutation or appearance certification."""
        return await self.registry.call("image.inspect_pixels", {"image_name": image_name, "samples": samples or [],
                                                               "include_statistics": include_statistics})

    async def image_paint_job_start(self, image_name: StrictStr, new_name: StrictStr,
                                   strokes: Annotated[list[BrushStroke], Field(min_length=1, max_length=32)],
                                   time_limit_seconds: Annotated[StrictFloat, Field(ge=1, le=300, allow_inf_nan=False)] = 60.,
                                   mask: ImageMask | None = None) -> Any:
        """Accept one source-frozen image paint job, NOT a completed painting. Supports <=16,777,216 pixels (4096/axis); synchronous painting remains <=1,048,576. Same brush/consent/color rules. Optional raw-channel UV image mask uses R/G/B/A (default R), invert=false, normalized pixel-centre bilinear edge-clamped resampling; no color transform/unpremultiply/luminance. Mask may differ in size, up to 4096/axis and 16M pixels. Freeze complete mask digest/identity/metadata plus selected-channel array; validate entire selected channel [0,1] cooperatively. FILE source OR mask requires live external-file/path consent; both images are revalidated before/after the checkpoint and after publication. 64x64 double-precision coverage tiles and conservative segment bands bound scratch work; 2M candidate tests, 32 strokes/256 segments. Large jobs may need an explicit larger time_limit_seconds (up to 300), not a larger private CPU-slice setting. Poll jobs.inspect/list (INSPECT_SCENE), retain owner connection until terminal. Workload reports pixel-buffer estimates excluding plan metadata/native/GPU/undo memory, NOT a process memory cap. Pause holds private CPU work while deadline continues; cancel/disconnect/deadline/emergency discards precommit work. Source identity/metadata/animation/pixels and live grants are rechecked before one native undo-guarded Object Mode publication. Native copying/allocation/update/readback/validation and undo are not preemptible. Late failures can retain an image when DELETE_OBJECTS cleanup is denied; inspect possible_mutation and recovery flags, never assume CANCELLED means rollback. Session-local, one active job, no batch nesting, automatic binding, saving or generic bake queue. After SUCCEEDED inspect large new/old/mask digests with include_statistics=false, bind explicitly, capture and verify recovery."""
        values = {"image_name": image_name, "new_name": new_name,
            "strokes": [stroke.model_dump() for stroke in strokes], "time_limit_seconds": time_limit_seconds}
        if mask is not None:
            values["mask"] = mask.model_dump()
        return await self.registry.call("image.paint_job_start", values)

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, handler, handler.__doc__ or "") for name, handler in (
            ("image.create", self.image_create), ("image.paint_version", self.image_paint_version),
            ("image.paint_job_start", self.image_paint_job_start),
            ("image.inspect_pixels", self.image_inspect_pixels)))
