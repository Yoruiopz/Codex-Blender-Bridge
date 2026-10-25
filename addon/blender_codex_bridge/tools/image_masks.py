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
CHANNEL_QUANTUM = 4096


def channel_copy(rgba: array, channel_index: int, *, check=lambda: None,
                 quantum: int = CHANNEL_QUANTUM) -> array:
    """Copy exact raw F32 values with bounded strided-copy scratch.

    Allocation of the complete destination is not preemptible. The supplied
    check runs around each bounded copy; callers own permission/range semantics.
    No arbitrary live provider is added to a caller's frozen-read proof.
    """
    if (type(channel_index) is not int or not 0 <= channel_index <= 3
            or type(quantum) is not int or not 1 <= quantum <= CHANNEL_QUANTUM
            or len(rgba) % 4):
        raise invalid_argument("Raw channel copying requires complete RGBA and a bounded copy quantum.")
    check()
    pixels = len(rgba) // 4
    result = array("f", [0.]) * pixels
    check()
    for start in range(0, pixels, quantum):
        check()
        end = min(pixels, start + quantum)
        result[start:end] = rgba[start*4+channel_index:end*4+channel_index:4]
        check()
    return result


def _copy_check(context: Any) -> None:
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    for name in ("check_final_request", "check_final_job"):
        hook = getattr(context, name, None)
        if hook is not None:
            hook()


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
    channel = channel_copy(rgba, CHANNELS[spec["channel"]], check=lambda: _copy_check(context))
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
