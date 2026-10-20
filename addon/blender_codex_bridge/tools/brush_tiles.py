"""Conservative segment bands and bounded per-tile brush coverage, no Blender."""

from __future__ import annotations

import math

TILE_SIZE = 64


def segment_tiles(a: tuple, b: tuple, box: tuple, radius: float):
    """Yield clipped tile rectangles covering a segment's entire capsule.

    Limit each tile-row to the segment interval within that row expanded by the
    radius. This avoids visiting a long diagonal's entire enclosing rectangle.
    One pixel of extra horizontal slack is conservative under float rounding;
    every yielded rectangle remains inside the original clipped bounding box.
    """
    x0, y0, x1, y1 = box
    if x0 >= x1 or y0 >= y1:
        return
    dx, dy = b[0] - a[0], b[1] - a[1]
    for ty in range(y0 // TILE_SIZE * TILE_SIZE, y1, TILE_SIZE):
        low, high = max(y0, ty), min(y1, ty + TILE_SIZE)
        if dy:
            ends = ((low - radius - a[1]) / dy, (high + radius - a[1]) / dy)
            begin, end = max(0., min(ends)), min(1., max(ends))
            if begin > end:
                continue
        else:
            begin, end = 0., 1.
        xs = (a[0] + dx * begin, a[0] + dx * end)
        left = max(x0, math.floor(min(xs) - radius) - 1)
        right = min(x1, math.ceil(max(xs) + radius) + 1)
        for tx in range(left // TILE_SIZE * TILE_SIZE, right, TILE_SIZE):
            yield (tx, ty), (max(left, tx), low, min(right, tx + TILE_SIZE), high)


def comparison_rows(tiles: set[tuple[int, int]], width: int, height: int):
    """Visit union tiles in global row-major order, not tile-major example order."""
    bands: dict[int, list[int]] = {}
    for tx, ty in sorted(tiles, key=lambda key: (key[1], key[0])):
        bands.setdefault(ty, []).append(tx)
    for ty, columns in bands.items():
        for y in range(ty, min(height, ty + TILE_SIZE)):
            for tx in columns:
                for x in range(tx, min(width, tx + TILE_SIZE)):
                    yield y * width + x
