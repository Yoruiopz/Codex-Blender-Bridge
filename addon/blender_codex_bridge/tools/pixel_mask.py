"""Raw-channel UV mask sampling; no Blender dependencies or color conversion."""

from __future__ import annotations

import math


def sample(mask: dict, x: int, y: int, width: int, height: int) -> float:
    mw, mh, values = mask["width"], mask["height"], mask["values"]
    if (mw, mh) == (width, height):
        value = values[y * mw + x]
    else:
        # Align normalized pixel centres, clamp at image edges, never wrap.
        fx = max(0., min(mw - 1., (x + .5) / width * mw - .5))
        fy = max(0., min(mh - 1., (y + .5) / height * mh - .5))
        x0, y0 = math.floor(fx), math.floor(fy)
        x1, y1 = min(x0 + 1, mw - 1), min(y0 + 1, mh - 1)
        a, b = fx - x0, fy - y0
        bottom = values[y0 * mw + x0] * (1 - a) + values[y0 * mw + x1] * a
        top = values[y1 * mw + x0] * (1 - a) + values[y1 * mw + x1] * a
        value = bottom * (1 - b) + top * b
    value = max(0., min(1., value))
    return 1 - value if mask["invert"] else value
