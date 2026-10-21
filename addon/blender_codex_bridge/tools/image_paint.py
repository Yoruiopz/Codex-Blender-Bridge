"""Copy-on-write generated textures, bounded brush strokes and independent pixel evidence."""

from __future__ import annotations

import logging
import math
from array import array
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import bool_param, reject_unknown_params, require_blender
from . import image_masks, images
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
    context.require(*required)
    state = getattr(context, "state", None)
    if modifying and state is not None:
        flags = state.snapshot()
        if flags["emergency_stopped"]:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Pixel modifications were emergency-stopped before their next safe action.")
        if flags["paused"]:
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Pixel modifications were paused before their next safe action.")


def _read(context: Any, image: Any, *, modifying=False, maximum_pixels=brush.MAX_PIXELS) -> tuple[array, int, int, dict | None]:
    _require(context, image, modifying=modifying)
    source = images.source_reference(context, image) if image.source == "FILE" else None
    file = images.binding_source(context, image, source=source)
    if (image.source, image.type) not in {("FILE", "IMAGE"), ("GENERATED", "UV_TEST")} or image.channels != 4:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Pixel tools support loaded simple four-channel RGBA images only.")
    width, height = brush.size(*(int(value) for value in image.size), maximum_pixels=maximum_pixels)
    if len(image.pixels) != width * height * 4:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Pixel buffer length does not match its complete RGBA dimensions.")
    _require(context, image, modifying=modifying)
    if source is not None:
        source.check(context)
        context.require(Permission.EDIT_MATERIALS if modifying else Permission.INSPECT_SCENE,
                        Permission.ACCESS_EXTERNAL_FILES)
    values = array("f", [0]) * (width * height * 4)
    image.pixels.foreach_get(values)
    _require(context, image, modifying=modifying)
    if source is not None:
        source.check(context)
        context.require(Permission.EDIT_MATERIALS if modifying else Permission.INSPECT_SCENE,
                        Permission.ACCESS_EXTERNAL_FILES)
        file = {**file, "source_reference": source.evidence()}
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
        _require(context, modifying=True)
        image.use_fake_user = False
        image.colorspace_settings.name = SPACES[role]
        # Pixels are our explicit unassociated RGBA contract, not a native file
        # decoder's associated float ImBuf. CHANNEL_PACKED prevents implicit
        # alpha/color coupling in both 4.5 and 5.1 renderers and keeps hidden RGB.
        image.alpha_mode = "CHANNEL_PACKED"
        _require(context, modifying=True)
        image.pixels.foreach_set(values)
        image.update()
        _require(context, modifying=True)
        actual, w, h, _ = _read(context, image, modifying=True)
        if (image.name != name or image.source != "GENERATED" or not image.is_float or image.alpha_mode != "CHANNEL_PACKED"
                or image.colorspace_settings.name != SPACES[role] or (w, h) != (width, height)
                or brush.digest(actual) != brush.digest(values)):
            raise RuntimeError("Generated image metadata or complete float32 pixels did not match readback")
        _require(context, modifying=True)
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
            "buffer_alpha_interpretation": "Independent straight RGBA; native CHANNEL_PACKED prevents implicit float alpha coupling",
            "file_written": False, "bound_to_nodes": False, "verification_required": True}


def source_role(source: Any) -> tuple[str, bool]:
    animation = getattr(source, "animation_data", None)
    animated = animation is not None and (getattr(animation, "action", None) is not None
               or len(getattr(animation, "drivers", ())) or len(getattr(animation, "nla_tracks", ())))
    native_associated = source.is_float and source.colorspace_settings.name == "Linear Rec.709"
    alpha_supported = source.alpha_mode in {"STRAIGHT", "CHANNEL_PACKED"} or (native_associated and source.alpha_mode == "PREMUL")
    if not alpha_supported or animated:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Painting requires an unanimated reviewed straight/channel-packed source or explicitly premultiplied linear float source.")
    space = source.colorspace_settings.name
    if space not in {"sRGB", "Linear Rec.709", "Non-Color"} or (space == "sRGB" and source.is_float):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed sources are byte-buffer sRGB or Linear Rec.709/Non-Color; other OCIO/float-sRGB semantics are not guessed.")
    return ("DATA" if space == "Non-Color" else "COLOR"), space == "sRGB"


def source_associated(source: Any) -> bool:
    return source.is_float and source.colorspace_settings.name != "Non-Color" and (source.alpha_mode == "PREMUL" or (source.source == "FILE" and source.alpha_mode != "CHANNEL_PACKED"))


def prepare_paint(context: Any, params: Mapping[str, Any], *, allow_large=False) -> dict:
    reject_unknown_params(params, {"image_name", "new_name", "strokes", "mask"})
    mask_spec = image_masks.specification(params.get("mask"))
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
    role, srgb = source_role(source)
    width, height = brush.size(*(int(value) for value in source.size), maximum_pixels=brush.MAX_PIXELS if allow_large else brush.MAX_SYNC_PIXELS)
    strokes, tests = brush.prepare(params.get("strokes"), width, height, role,
                                   check=lambda: _require(context, source, modifying=True))
    values, _, _, source_file = _read(context, source, modifying=True)
    before = brush.digest(values)
    mask = image_masks.freeze(context, bpy, mask_spec, read=_read,
        maximum_pixels=brush.MAX_PIXELS if allow_large else brush.MAX_SYNC_PIXELS,
        source=source, source_values=values, source_file=source_file)
    return {"source": source, "source_name": source_name, "name": name, "width": width, "height": height,
            "role": role, "values": values, "strokes": strokes, "tests": tests, "srgb": srgb,
            "source_file": source_file, "source_digest": before, "mask": mask,
            "source_identity": image_masks.identity(source), "source_metadata": image_masks.metadata(source),
            "associated": source_associated(source)}


def validate_source_reference(prepared: dict) -> None:
    source = images.image_exact(require_blender(), prepared["source_name"])
    if (image_masks.identity(source) != prepared["source_identity"]
            or image_masks.metadata(source) != prepared["source_metadata"]):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Painting source identity/metadata changed; reinspect before further edits.", {"stale_source": True})
    source_role(source)


def require_paint(context: Any, prepared: dict) -> None:
    _require(context, prepared["source"], modifying=True)
    if prepared.get("mask") is not None:
        _require(context, prepared["mask"]["image"], modifying=True)


def masked_memory_estimate(prepared: dict) -> dict:
    mask = prepared.get("mask")
    if mask is None:
        return {}
    kernel = mask["kernel"]
    channel_bytes = len(kernel["values"]) * kernel["values"].itemsize
    # Conservative overestimate: generator source/output, retained source readback,
    # a complete mask RGBA revalidation and packed channel plus coverage scratch.
    return {"private_pixel_buffers_peak_estimate_bytes": 3 * prepared["width"] * prepared["height"] * 16
                + 5 * channel_bytes + brush.TILE_SIZE**2 * 8,
            "mask_channel_bytes": channel_bytes,
            "memory_estimate_scope": "Conservative source/output/readback and mask RGBA/channel arrays plus coverage scratch; excludes plan metadata, Blender/native/GPU/undo/file buffers and allocator overhead."}


def finish_paint(context: Any, prepared: dict, result: array, evidence: dict) -> dict:
    source, source_name, name = prepared["source"], prepared["source_name"], prepared["name"]
    width, height, role = prepared["width"], prepared["height"], prepared["role"]
    before = prepared["source_digest"]
    require_paint(context, prepared)
    validate_source_reference(prepared)
    image_masks.validate(context, require_blender(), prepared.get("mask"), read=_read)
    new = _new(context, require_blender(), name, width, height, role, result)
    # Reinspect the entire original after allocation/readback, not just its size.
    # If this check fails, retain the created version and truthful mutation evidence
    # for confirmed recovery; do not delete an image with unexpected consumers.
    try:
        retained, _, _, _ = _read(context, source, modifying=True)
        if brush.digest(retained) != before:
            raise RuntimeError("Original source pixels changed during copy-on-write painting")
        validate_source_reference(prepared)
        image_masks.validate(context, require_blender(), prepared.get("mask"), read=_read)
        require_paint(context, prepared)
    except Exception as exc:
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Paint version exists but input preservation could not be verified; recover output and reinspect both inputs. Native undo may not restore externally edited image pixels.",
                          {**(exc.context if isinstance(exc, BridgeError) else {}),
                           "execution_started": True, "requested_image": name, "possible_mutation": True,
                           "input_preservation_verified": False, "verification_required": True}) from exc
    return {"painted_image": images._summary(new), "source_image": source_name, "role": role,
            "source_pixels_sha256_float32_le": before, "pixels_sha256_float32_le": brush.digest(result),
            "source_pixels_unchanged": True, "candidate_pixel_tests": prepared["tests"], **evidence,
            **masked_memory_estimate(prepared), "mask": image_masks.evidence(prepared.get("mask")),
            "buffer_alpha_interpretation": "Independent straight RGBA; native CHANNEL_PACKED prevents implicit float alpha coupling",
            "file_written": False, "bound_to_nodes": False, "source_file_at_read": prepared["source_file"],
            "stroke_coordinates": "UV [0,1], bottom-left origin; radius in image pixels, clipped at edges, no wrapping",
            "verification_required": True, "full_texture_paint_workflow_verified": False}


def paint_version(context: Any, params: Mapping[str, Any]) -> dict:
    prepared = prepare_paint(context, params)
    result, evidence = brush.paint(prepared["values"], prepared["width"], prepared["height"], prepared["strokes"],
                                   prepared["role"], srgb=prepared["srgb"],
                                   associated=prepared["associated"],
                                   mask=prepared["mask"]["kernel"] if prepared["mask"] else None,
                                   check=lambda: require_paint(context, prepared))
    return finish_paint(context, prepared, result, evidence)


def inspect_pixels(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "samples", "include_statistics"})
    statistics = bool_param(params, "include_statistics", True)
    image = images.image_exact(require_blender(), images._name(params, "image_name"))
    raw = params.get("samples", [])
    if not isinstance(raw, list) or len(raw) > 64:
        raise invalid_argument("Supply at most 64 integer pixel [x,y] samples.")
    points = []
    for point in raw:
        if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < brush.MAX_DIMENSION for v in point):
            raise invalid_argument("Each pixel sample must be two nonnegative integers.")
        points.append(point)
    values, width, height, file = _read(context, image, maximum_pixels=brush.MAX_SYNC_PIXELS if statistics else brush.MAX_PIXELS)
    if any(x >= width or y >= height for x, y in points):
        raise invalid_argument("A pixel sample lies outside the image dimensions.")
    minima, maxima, invalid = [math.inf] * 4, [-math.inf] * 4, 0
    for index, value in enumerate(values if statistics else ()):
        if index % 16384 == 0:
            _require(context, image)
        if not math.isfinite(value):
            invalid += 1
            continue
        channel = index % 4
        minima[channel], maxima[channel] = min(minima[channel], value), max(maxima[channel], value)
    return {"image": images._summary(image), "pixel_count": width * height,
            "pixels_sha256_float32_le": brush.digest(values), "nonfinite_channels": invalid if statistics else None,
            "channel_min": [v if math.isfinite(v) else None for v in minima] if statistics else None,
            "channel_max": [v if math.isfinite(v) else None for v in maxima] if statistics else None,
            "samples": [{"pixel": p, "rgba": [v if math.isfinite(v) else None for v in values[(p[1] * width + p[0]) * 4:(p[1] * width + p[0]) * 4 + 4]]} for p in points],
            "value_space": "Raw stored-buffer floats, not display values or an implicit color transform",
            "alpha_interpretation_warning": "File alpha_mode describes file representation, not necessarily stored float ImBuf association; native float COLOR files may already be linear/associated",
            "source_file_at_read": file, "analysis_complete": statistics, "appearance_verified": False,
            "statistics_included": statistics, "pixel_digest_complete": True,
            "analysis_scope": "Complete pixel digest/samples and channel statistics" if statistics else "Complete pixel digest/samples only; channel ranges/nonfinite scan omitted"}


def register_tools(registry: Any) -> None:
    registry.register("image.create", create_image, toolset="materials", modifies=True, permissions=(Permission.EDIT_MATERIALS,),
                      description="Create a bounded new floating-point linear-color/data texture; verify complete pixels, never overwrite or write files.")
    registry.register("image.paint_version", paint_version, toolset="materials", modifies=True, permissions=(Permission.EDIT_MATERIALS,),
                      description="Paint bounded UV-image strokes with optional raw-channel mask/inversion/resampling into a new version, preserving both inputs; FILE reads require approved-path/external-file consent.")
    registry.register("image.inspect_pixels", inspect_pixels, toolset="materials", permissions=(Permission.INSPECT_SCENE,),
                      description="Inspect complete loaded RGBA digests/samples; default statistics <=1M pixels, explicit include_statistics=false for <=16M with no ranges/nonfinite scan; FILE reads require approved-path/external-file consent.")
