"""Read-only image-mask freeze/revalidation, separate from the brush kernel."""

from __future__ import annotations

from array import array
from collections.abc import Callable, Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..utils import bool_param, reject_unknown_params
from . import images
from . import pixel_brush as brush

CHANNELS = {"R": 0, "G": 1, "B": 2, "A": 3}


def specification(raw: Any) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise invalid_argument("'mask' must be a typed image/channel/invert object.")
    reject_unknown_params(raw, {"image_name", "channel", "invert"})
    channel = raw.get("channel", "R")
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise invalid_argument("Mask channel must be R, G, B or A.")
    return {"image_name": images._name(raw, "image_name"), "channel": channel,
            "invert": bool_param(raw, "invert", False)}


def identity(image: Any) -> tuple:
    return (image.as_pointer() if hasattr(image, "as_pointer") else id(image),
            getattr(image, "session_uid", None))


def metadata(image: Any) -> dict:
    result = images._summary(image)
    if result["filepath_truncated"]:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Mask path exceeds its complete metadata verification window.")
    return {key: value for key, value in result.items() if key != "users"}


def unanimated(image: Any) -> None:
    animation = getattr(image, "animation_data", None)
    if animation is not None and (getattr(animation, "action", None) is not None
            or len(getattr(animation, "drivers", ())) or len(getattr(animation, "nla_tracks", ()))):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV-image masks must be unanimated; evaluated/animated mask semantics are not guessed.")


def freeze(context: Any, bpy: Any, spec: dict | None, *, read: Callable,
           maximum_pixels: int, source: Any, source_values: array, source_file: dict | None) -> dict | None:
    if spec is None:
        return None
    image = images.image_exact(bpy, spec["image_name"])
    images.binding_source(context, image)
    unanimated(image)
    brush.size(*(int(value) for value in image.size), maximum_pixels=maximum_pixels)
    before, original_identity = metadata(image), identity(image)
    if image is source:
        rgba, width, height, file = source_values, *source.size, source_file
    else:
        rgba, width, height, file = read(context, image, modifying=True, maximum_pixels=maximum_pixels)
    if metadata(image) != before or identity(image) != original_identity:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Mask changed during capture; reinspect before painting.", {"stale_mask": True})
    channel = rgba[CHANNELS[spec["channel"]]::4]
    return {"image": image, "name": spec["image_name"], "identity": original_identity, "metadata": before,
            "file": file, "digest": brush.digest(rgba), "channel_digest": brush.digest(channel),
            "kernel": {"values": channel, "width": int(width), "height": int(height), "invert": spec["invert"]},
            "channel": spec["channel"], "requires_external_files": image.source == "FILE"}


def validate(context: Any, bpy: Any, mask: dict | None, *, read: Callable) -> None:
    if mask is None:
        return
    try:
        image = images.image_exact(bpy, mask["name"])
    except BridgeError as exc:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Mask name is missing or ambiguous; reinspect before restarting.", {"stale_mask": True}) from exc
    if identity(image) != mask["identity"] or metadata(image) != mask["metadata"]:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Mask identity/metadata changed; reinspect before restarting.", {"stale_mask": True})
    unanimated(image)
    values, width, height, file = read(context, image, modifying=True)
    if ((width, height) != (mask["kernel"]["width"], mask["kernel"]["height"])
            or brush.digest(values) != mask["digest"] or file != mask["file"]
            or metadata(image) != mask["metadata"]):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Mask pixels or approved file changed; reinspect before restarting.", {"stale_mask": True})
    mask["image"] = image


def evidence(mask: dict | None) -> dict | None:
    if mask is None:
        return None
    return {"image_name": mask["name"], "channel": mask["channel"], "invert": mask["kernel"]["invert"],
            "size": [mask["kernel"]["width"], mask["kernel"]["height"]],
            "pixels_sha256_float32_le": mask["digest"], "channel_sha256_float32_le": mask["channel_digest"],
            "pixels_unchanged": True, "value_space": "Raw stored channel [0,1]; no color/alpha transform",
            "sampling": "Normalized UV pixel-centre bilinear, edge-clamped; equal dimensions sample exactly",
            "colorspace": mask["metadata"]["colorspace"], "alpha_mode": mask["metadata"]["alpha_mode"],
            "source_file_at_read": mask["file"]}
