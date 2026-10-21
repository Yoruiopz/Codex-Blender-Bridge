"""Cooperative, independent native-pixel references for reviewed texture delivery.

Does not call the encoder's pixel conversion or quantizer. No Blender or IO.
Native float buffers and file samples have intentionally different semantics.
"""

from __future__ import annotations

import hashlib
import math
import struct
import sys
from array import array
from collections.abc import Callable, Iterator

from .errors import BridgeError, ErrorCode, invalid_argument


def normalize_steps(values: array, *, associated: bool, check: Callable[[], None]) -> Iterator[dict]:
    """Only our private frozen copy changes; no guessed additive zero-alpha RGB."""
    if not associated:
        return
    for offset in range(0, len(values), 4):
        if offset % 1024 == 0:
            check()
            yield {"phase": "normalizing_source", "completed": offset//4, "total": len(values)//4}
        alpha = values[offset+3]
        if not math.isfinite(alpha) or not 0 <= alpha <= 1:
            raise invalid_argument("Associated COLOR export requires finite alpha within [0,1].")
        if not alpha and any(values[offset+c] != 0 for c in range(3)):
            raise invalid_argument("Associated zero-alpha RGB cannot be inferred as straight color; choose an explicit independent source.")
        for channel in range(3):
            value = values[offset+channel] / alpha if alpha else 0.
            if not math.isfinite(value) or abs(value) > 3.4028234663852886e38:
                raise invalid_argument("Normalized texture channels must fit finite float32.")
            values[offset+channel] = value


def _linear(value: float) -> float:
    return value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4


def _encoded(value: float) -> float:
    return 12.92*value if value <= .0031308 else 1.055*value**(1/2.4)-.055


def compare_steps(source: array, native: array, format: str, role: str, *, srgb: bool,
                  check: Callable[[], None]) -> Iterator[dict]:
    """Verify EVERY native channel against a separately computed file reference.

    PNG16 COLOR uses an explicitly predeclared OCIO allowance, not exact bits.
    Raw float paths verify bit patterns (including negative zero) in 64 KiB blocks.
    """
    if len(source) != len(native) or len(source) % 4:
        raise invalid_argument("Decoded texture does not have the complete expected RGBA footprint.")
    exact = format.startswith("EXR") and (role == "DATA" or (format == "EXR32_RAW" and not srgb))
    digest = hashlib.sha256()
    total = len(source)//4
    maximum = 0.
    tolerance = 0. if exact else 2/65535 if format == "PNG16" and role == "COLOR" else 2**-23
    if exact:
        expected_bytes, actual_bytes = memoryview(source).cast("B"), memoryview(native).cast("B")
        for start in range(0, len(expected_bytes), 65536):
            check()
            expected, actual = expected_bytes[start:start+65536], actual_bytes[start:start+65536]
            if expected != actual:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Decoded raw EXR float32 bits differ from the frozen source.", {"pixel_roundtrip_verified": False})
            if sys.byteorder == "little":
                digest.update(actual)
            else:
                block = array("f")
                block.frombytes(actual)
                block.byteswap()
                digest.update(block)
            yield {"phase": "verifying_decoded_pixels", "completed": min(total, (start+65536)//16), "total": total}
    else:
        for offset in range(0, len(source), 4):
            if offset % 1024 == 0:
                check()
                yield {"phase": "verifying_decoded_pixels", "completed": offset//4, "total": total}
            values = list(source[offset:offset+4])
            if format.startswith("PNG"):
                if role == "COLOR" and not srgb:
                    values[:3] = [_encoded(v) for v in values[:3]]
                scale = 255 if format == "PNG8" else 65535
                values = [math.floor(v*scale+.5)/scale for v in values]
                if format == "PNG16" and role == "COLOR":
                    values[:3] = [_linear(v)*values[3] for v in values[:3]]
            else:
                if srgb:
                    values[:3] = [_linear(v) for v in values[:3]]
                if format == "EXR32" and role == "COLOR":
                    values[:3] = [v*values[3] for v in values[:3]]
                values = struct.unpack("<4f", struct.pack("<4f", *values))
            observed = native[offset:offset+4]
            for expected, actual in zip(values, observed, strict=True):
                difference = abs(expected-actual)
                # EXR color can contain HDR values: one relative float32 ULP.
                allowance = tolerance if format.startswith("PNG") else tolerance*max(1., abs(expected))
                if not math.isfinite(actual) or difference > allowance:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Decoded texture exceeds its declared native channel allowance.",
                                      {"pixel_roundtrip_verified": False, "pixel_index": offset//4,
                                       "absolute_error": difference if math.isfinite(difference) else None,
                                       "absolute_allowance": allowance})
                maximum = max(maximum, difference)
            digest.update(struct.pack("<4f", *observed))
    check()
    return {"pixel_roundtrip_verified": True, "all_channels_compared": len(source),
            "native_pixels_sha256_float32_le": digest.hexdigest(),
            "exact_raw_float32_bits_verified": exact, "maximum_absolute_channel_error": maximum,
            "native_channel_tolerance": tolerance,
            "tolerance_scope": "Absolute PNG; relative-to-max(1,abs(reference)) for non-raw EXR",
            "quantization": "None" if format.startswith("EXR") else format,
            "native_buffer_interpretation": "Linear associated" if role == "COLOR" and format in {"PNG16", "EXR32"} else "Independent channels"}
