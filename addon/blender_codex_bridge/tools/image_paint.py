"""Copy-on-write generated textures, bounded brush strokes and independent pixel evidence."""

from __future__ import annotations

import logging
import math
from array import array
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import reject_unknown_params, require_blender
from . import images
from . import pixel_brush as brush

LOGGER = logging.getLogger(__name__)
SPACES = {"COLOR": "Linear Rec.709", "DATA": "Non-Color"}


def _role(params: Mapping[str, Any]) -> str:
    role = params.get("role", "COLOR")
    if not isinstance(role, str) or role not in SPACES:
        raise invalid_argument("'role' must be COLOR or DATA.")
    return role


def _require(context: Any, image: Any | None = None, *, modifying=False) -> None:
    required = [Permission.EDIT_MATERIALS] if modifying else [Permission.INSPECT_SCENE]
    if image is not None and image.source == "FILE":
        required.append(Permission.ACCESS_EXTERNAL_FILES)
    context.require(*required)
    images._check(context)


def _read(context: Any, image: Any, *, modifying=False) -> tuple[array, int, int, dict | None]:
    _require(context, image, modifying=modifying)
    file = images.binding_source(context, image)
    if (image.source, image.type) not in {("FILE", "IMAGE"), ("GENERATED", "UV_TEST")} or image.channels != 4:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Pixel tools support loaded simple four-channel RGBA images only.")
    width, height = brush.size(*(int(value) for value in image.size))
    if len(image.pixels) != width * height * 4:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Pixel buffer length does not match its complete RGBA dimensions.")
    _require(context, image, modifying=modifying)
    values = array("f", [0]) * (width * height * 4)
    image.pixels.foreach_get(values)
    _require(context, image, modifying=modifying)
    return values, width, height, file


def _new(context: Any, bpy: Any, name: str, width: int, height: int, role: str, values: array) -> Any:
    _require(context, modifying=True)
    spaces = {item.identifier for item in bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"].enum_items}
    if SPACES[role] not in spaces:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The reviewed linear/data space is unavailable in this OCIO configuration.")
    if bpy.data.images.get(name) is not None:
        raise invalid_argument("The new image name already exists; no implicit overwrite or reuse is allowed.")
    image = None
    before = len(bpy.data.images)
    try:
        image = bpy.data.images.new(name, width, height, alpha=True, float_buffer=True)
        image.use_fake_user = False
        image.colorspace_settings.name = SPACES[role]
        image.alpha_mode = "STRAIGHT"
        _require(context, modifying=True)
        image.pixels.foreach_set(values)
        image.update()
        _require(context, modifying=True)
        actual, w, h, _ = _read(context, image, modifying=True)
        if (image.name != name or image.source != "GENERATED" or not image.is_float or image.alpha_mode != "STRAIGHT"
                or image.colorspace_settings.name != SPACES[role] or (w, h) != (width, height) or actual != values):
            raise RuntimeError("Generated image metadata or complete float32 pixels did not match readback")
        return image
    except Exception as exc:
        LOGGER.exception("New pixel image failed; attempting only owned zero-user image cleanup")
        restored = False
        cleanup_denied = False
        try:
            if image is not None:
                _removed, cleanup_denied = images.cleanup_created_image(context, bpy, image)
            restored = bpy.data.images.get(name) is None and len(bpy.data.images) == before
        except Exception:
            LOGGER.exception("Pixel-image cleanup could not be verified")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Pixel-image creation failed; reinspect the requested image and recovery evidence.",
                          {"execution_started": True, "requested_image": name, "rollback_verified": restored,
                           "possible_mutation": not restored, "cleanup_permission_denied": cleanup_denied,
                           "verification_required": True}) from exc


def create_image(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"new_name", "width", "height", "role", "color"})
    name, role = images._name(params, "new_name"), _role(params)
    width, height = brush.size(params.get("width"), params.get("height"))
    color = brush.vector(params.get("color", [0., 0., 0., 1.]), "color", 4, 16. if role == "COLOR" else 1.)
    _require(context, modifying=True)
    bpy = require_blender()
    images._object_mode(bpy)
    values = array("f", color) * (width * height)
    image = _new(context, bpy, name, width, height, role, values)
    return {"created": True, "image": images._summary(image), "role": role,
            "pixels_sha256_float32_le": brush.digest(values), "pixels_verified": True,
            "file_written": False, "bound_to_nodes": False, "verification_required": True}


def paint_version(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "new_name", "strokes"})
    source_name, name = images._name(params, "image_name"), images._name(params, "new_name")
    # Validate syntax/counts without Blender/file work first. The actual image
    # dimensions and data role get their own authoritative footprint validation.
    brush.prepare(params.get("strokes"), 1, 1, "COLOR")
    _require(context, modifying=True)
    bpy = require_blender()
    images._object_mode(bpy)
    source = images.image_exact(bpy, source_name)
    if bpy.data.images.get(name) is not None:
        raise invalid_argument("The new image name already exists; no implicit overwrite or reuse is allowed.")
    # The same loaded-source/file consent checks as binding run before getters
    # that can acquire a buffer. No implicit decode/reload or color-role mutation.
    images.binding_source(context, source)
    animation = getattr(source, "animation_data", None)
    animated = animation is not None and (getattr(animation, "action", None) is not None
               or len(getattr(animation, "drivers", ())) or len(getattr(animation, "nla_tracks", ())))
    if source.alpha_mode != "STRAIGHT" or animated:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Painting requires unanimated STRAIGHT-alpha source data.")
    space = source.colorspace_settings.name
    if space not in {"sRGB", "Linear Rec.709", "Non-Color"} or (space == "sRGB" and source.is_float):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed sources are byte-buffer sRGB or Linear Rec.709/Non-Color; other OCIO/float-sRGB semantics are not guessed.")
    role = "DATA" if space == "Non-Color" else "COLOR"
    width, height = brush.size(*(int(value) for value in source.size))
    strokes, tests = brush.prepare(params.get("strokes"), width, height, role)
    values, _, _, source_file = _read(context, source, modifying=True)
    before = brush.digest(values)
    result, evidence = brush.paint(values, width, height, strokes, role, srgb=space == "sRGB", check=lambda: _require(context, source, modifying=True))
    _require(context, source, modifying=True)
    new = _new(context, bpy, name, width, height, role, result)
    # Reinspect the entire original after allocation/readback, not just its size.
    # If this check fails, retain the created version and truthful mutation evidence
    # for confirmed recovery; do not delete an image with unexpected consumers.
    try:
        retained, _, _, _ = _read(context, source, modifying=True)
        if brush.digest(retained) != before:
            raise RuntimeError("Original source pixels changed during copy-on-write painting")
    except Exception as exc:
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Paint version exists but original-source preservation could not be verified; recover or reinspect.",
                          {"execution_started": True, "requested_image": name, "possible_mutation": True,
                           "verification_required": True}) from exc
    return {"painted_image": images._summary(new), "source_image": source_name, "role": role,
            "source_pixels_sha256_float32_le": before, "pixels_sha256_float32_le": brush.digest(result),
            "source_pixels_unchanged": True, "candidate_pixel_tests": tests, **evidence,
            "file_written": False, "bound_to_nodes": False, "source_file_at_read": source_file,
            "stroke_coordinates": "UV [0,1], bottom-left origin; radius in image pixels, clipped at edges, no wrapping",
            "verification_required": True, "full_texture_paint_workflow_verified": False}


def inspect_pixels(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "samples"})
    image = images.image_exact(require_blender(), images._name(params, "image_name"))
    raw = params.get("samples", [])
    if not isinstance(raw, list) or len(raw) > 64:
        raise invalid_argument("Supply at most 64 integer pixel [x,y] samples.")
    points = []
    for point in raw:
        if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < brush.MAX_DIMENSION for v in point):
            raise invalid_argument("Each pixel sample must be two nonnegative integers.")
        points.append(point)
    values, width, height, file = _read(context, image)
    if any(x >= width or y >= height for x, y in points):
        raise invalid_argument("A pixel sample lies outside the image dimensions.")
    minima, maxima, invalid = [math.inf] * 4, [-math.inf] * 4, 0
    for index, value in enumerate(values):
        if index % 16384 == 0:
            _require(context, image)
        if not math.isfinite(value):
            invalid += 1
            continue
        channel = index % 4
        minima[channel], maxima[channel] = min(minima[channel], value), max(maxima[channel], value)
    return {"image": images._summary(image), "pixel_count": width * height,
            "pixels_sha256_float32_le": brush.digest(values), "nonfinite_channels": invalid,
            "channel_min": [v if math.isfinite(v) else None for v in minima],
            "channel_max": [v if math.isfinite(v) else None for v in maxima],
            "samples": [{"pixel": p, "rgba": [v if math.isfinite(v) else None for v in values[(p[1] * width + p[0]) * 4:(p[1] * width + p[0]) * 4 + 4]]} for p in points],
            "value_space": "Raw stored-buffer floats, not display values or an implicit color transform",
            "source_file_at_read": file, "analysis_complete": True, "appearance_verified": False}


def register_tools(registry: Any) -> None:
    registry.register("image.create", create_image, toolset="materials", modifies=True, permissions=(Permission.EDIT_MATERIALS,),
                      description="Create a bounded new floating-point linear-color/data texture; verify complete pixels, never overwrite or write files.")
    registry.register("image.paint_version", paint_version, toolset="materials", modifies=True, permissions=(Permission.EDIT_MATERIALS,),
                      description="Paint bounded UV-image brush strokes into a new image version, preserving the original; FILE sources also require approved-path/external-file consent.")
    registry.register("image.inspect_pixels", inspect_pixels, toolset="materials", permissions=(Permission.INSPECT_SCENE,),
                      description="Inspect bounded loaded RGBA pixels with complete digest/ranges and up to 64 samples; FILE sources require approved-path/external-file consent, no implicit loading.")
