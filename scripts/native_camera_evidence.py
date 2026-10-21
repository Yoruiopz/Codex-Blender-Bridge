"""Compare complete native PNG readback on its RGBA8 storage grid, not float noise."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence


def rgba8(values: Sequence[float]) -> bytes:
    if len(values) % 4 or len(values) > 4096 * 4096 * 4:
        raise ValueError("Camera evidence needs bounded complete RGBA pixels")
    result = bytearray(len(values))
    for index, value in enumerate(values):
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("RGBA8 camera readback must be finite and normalized")
        result[index] = min(255, math.floor(value * 255 + .5))
    return bytes(result)


def compare_rgba8(before: bytes, after: bytes, width: int, height: int) -> dict:
    if type(width) is not int or type(height) is not int or not (1 <= width <= 4096 and 1 <= height <= 4096):
        raise ValueError("Camera dimensions must be positive bounded integers")
    if not isinstance(before, bytes) or not isinstance(after, bytes) or len(before) != width * height * 4 or len(after) != len(before):
        raise ValueError("Both captures must contain the complete declared RGBA8 image")
    return {
        "width": width, "height": height, "pixels_compared": width * height,
        "changed_pixels": sum(before[i:i+4] != after[i:i+4] for i in range(0, len(before), 4)),
        "max_channel_error_rgba8": max(abs(a-b) for a, b in zip(before, after, strict=True)),
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "scope": "Complete matched RGBA8 camera images; artistic quality requires visual review",
    }
