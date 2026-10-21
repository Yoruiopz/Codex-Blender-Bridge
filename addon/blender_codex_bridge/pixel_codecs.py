"""Streaming texture encoders, not a filesystem API or registered export tool.

PNG uses unassociated RGBA8/16; EXR32 follows premultiplied COLOR convention.
EXR32_RAW preserves stored straight RGB (including hidden zero-alpha RGB) and
requires explicit STRAIGHT/CHANNEL_PACKED interpretation by the reopening app.
Only standard-library dependencies; see docs/texture-delivery.md for contracts.
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from array import array
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .errors import invalid_argument
from .tools.pixel_brush import MAX_PIXELS, size, srgb_to_linear

FORMATS = frozenset({"PNG8", "PNG16", "EXR32", "EXR32_RAW"})
BLOCK_BYTES = 65536
PIXEL_QUANTUM = 256
MAX_ENCODED_BYTES = MAX_PIXELS * 16 + 1048576


@dataclass(frozen=True, slots=True)
class EncodingStep:
    data: bytes
    pixels_completed: int
    pixels_total: int


def linear_to_srgb(value: float) -> float:
    return value * 12.92 if value <= .0031308 else 1.055 * value**(1/2.4) - .055


def interpretation(format: str, role: str) -> dict:
    if format not in FORMATS or role not in {"COLOR", "DATA"}:
        raise invalid_argument("Choose PNG8/PNG16/EXR32/EXR32_RAW and COLOR/DATA explicitly.")
    png = format.startswith("PNG")
    return {"format": format, "role": role, "extension": ".png" if png else ".exr",
            "colorspace": ("sRGB" if png else "Linear Rec.709") if role == "COLOR" else "Non-Color",
            "alpha_mode": "CHANNEL_PACKED" if role == "DATA" else "PREMUL" if format == "EXR32" else "STRAIGHT",
            "reopen_alpha_mode": "CHANNEL_PACKED" if format == "EXR32_RAW" or role == "DATA" else "PREMUL" if format == "EXR32" else "STRAIGHT",
            "native_buffer_model": "LINEAR_ASSOCIATED" if role == "COLOR" and format in {"PNG16", "EXR32"} else "ENCODED_STRAIGHT" if role == "COLOR" and format == "PNG8" else "RAW_CHANNELS",
            "bit_depth": 8 if format == "PNG8" else 16 if png else 32,
            "raw_zero_alpha_rgb_preserved": format != "EXR32" or role == "DATA",
            "view_transform_applied": False,
            "requires_explicit_alpha_interpretation": format == "EXR32_RAW" or role == "DATA"}


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind+payload) & 0xffffffff)


def _attribute(name: str, kind: str, payload: bytes) -> bytes:
    return name.encode("ascii") + b"\0" + kind.encode("ascii") + b"\0" + struct.pack("<I", len(payload)) + payload


def exr_header(width: int, height: int, format: str, role: str) -> bytes:
    layout = interpretation(format, role)
    if not format.startswith("EXR"):
        raise invalid_argument("An EXR header requires an EXR encoding.")
    size(width, height)
    channels = b"".join(name + b"\0" + struct.pack("<iB3xii", 2, 0, 1, 1) for name in (b"A", b"B", b"G", b"R")) + b"\0"
    box = struct.pack("<iiii", 0, 0, width-1, height-1)
    return (struct.pack("<II", 20000630, 2)
            + _attribute("channels", "chlist", channels)
            + _attribute("compression", "compression", b"\0")
            + _attribute("dataWindow", "box2i", box) + _attribute("displayWindow", "box2i", box)
            + _attribute("lineOrder", "lineOrder", b"\0")
            + _attribute("pixelAspectRatio", "float", struct.pack("<f", 1.))
            + _attribute("screenWindowCenter", "v2f", struct.pack("<ff", 0., 0.))
            + _attribute("screenWindowWidth", "float", struct.pack("<f", 1.))
            + _attribute("bcbRole", "string", role.encode("ascii"))
            + _attribute("bcbAlphaMode", "string", layout["alpha_mode"].encode("ascii")) + b"\0")


def _pixel(values: array, offset: int, format: str, role: str, srgb: bool) -> tuple[float, ...]:
    rgba = tuple(values[offset:offset+4])
    if any(not math.isfinite(v) for v in rgba):
        raise invalid_argument("Texture delivery requires every stored channel to be finite.")
    if role == "COLOR" and not 0 <= rgba[3] <= 1:
        raise invalid_argument("COLOR delivery requires alpha within [0,1].")
    if srgb and any(not 0 <= v <= 1 for v in rgba):
        raise invalid_argument("Byte-sRGB delivery requires stored channels within [0,1].")
    if format.startswith("PNG"):
        if any(not 0 <= v <= 1 for v in rgba):
            raise invalid_argument("PNG cannot preserve HDR/signed channels; choose float EXR explicitly, no clipping is performed.")
        if role == "COLOR" and not srgb:
            rgba = tuple(linear_to_srgb(v) if i < 3 else v for i, v in enumerate(rgba))
        maximum = 255 if format == "PNG8" else 65535
        return tuple(min(maximum, max(0, math.floor(v * maximum + .5))) for v in rgba)
    if srgb:
        rgba = tuple(srgb_to_linear(v) if i < 3 else v for i, v in enumerate(rgba))
    if format == "EXR32" and role == "COLOR":
        rgba = tuple(v * rgba[3] if i < 3 else v for i, v in enumerate(rgba))
    return rgba


def encode_steps(values: array, width: int, height: int, format: str, role: str, *, srgb: bool = False,
                 check: Callable[[], None] = lambda: None) -> Iterator[EncodingStep]:
    """Yield bounded blocks/safe points; caller owns consent, staging and publication.

    An empty block is a CPU safe point, not end-of-stream. The source is borrowed
    read-only and must stay frozen. Output is deliberately not published here:
    late invalid pixels, cancellation or encoder errors can leave a partial stream.
    """
    layout = interpretation(format, role)
    size(width, height)
    if not isinstance(values, array) or values.typecode != "f" or values.itemsize != 4 or len(values) != width*height*4:
        raise invalid_argument("Encoding needs a complete float32 RGBA source buffer.")
    if type(srgb) is not bool or (srgb and role != "COLOR"):
        raise invalid_argument("sRGB conversion is an explicit COLOR-only boolean.")
    check()
    total = width * height
    if format.startswith("PNG"):
        yield EncodingStep(b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, layout["bit_depth"], 6, 0, 0, 0)), 0, total)
        if role == "COLOR":
            yield EncodingStep(_png_chunk(b"sRGB", b"\0"), 0, total)
        compressor = zlib.compressobj(level=6)
    else:
        header = exr_header(width, height, format, role)
        offsets_start, stride = len(header) + height*8, 8 + width*16
        table = b"".join(struct.pack("<Q", offsets_start+y*stride) for y in range(height))
        yield EncodingStep(header+table, 0, total)
    for row_index in range(height):
        source_y = height - 1 - row_index  # Blender bottom-left -> file top-left.
        row = array("B" if format == "PNG8" else "H" if format == "PNG16" else "f")
        for x in range(width):
            completed = row_index * width + x
            if completed % PIXEL_QUANTUM == 0:
                check()
                yield EncodingStep(b"", completed, total)
            pixel = _pixel(values, (source_y*width+x)*4, format, role, srgb)
            row.extend(pixel)
        completed = (row_index+1)*width
        if format.startswith("PNG"):
            if format == "PNG16" and sys.byteorder == "little":
                row.byteswap()
            payload = compressor.compress(b"\0"+row.tobytes())
            for start in range(0, len(payload), BLOCK_BYTES):
                yield EncodingStep(_png_chunk(b"IDAT", payload[start:start+BLOCK_BYTES]), completed, total)
        else:
            yield EncodingStep(struct.pack("<ii", row_index, width*16), completed, total)
            for channel in (3, 2, 1, 0):
                planar = row[channel::4]
                if sys.byteorder != "little":
                    planar.byteswap()
                yield EncodingStep(planar.tobytes(), completed, total)
        # Even compressible short rows must return control, not loop for an image.
        check()
        yield EncodingStep(b"", completed, total)
    if format.startswith("PNG"):
        payload = compressor.flush()
        for start in range(0, len(payload), BLOCK_BYTES):
            yield EncodingStep(_png_chunk(b"IDAT", payload[start:start+BLOCK_BYTES]), total, total)
        yield EncodingStep(_png_chunk(b"IEND", b""), total, total)
    check()
