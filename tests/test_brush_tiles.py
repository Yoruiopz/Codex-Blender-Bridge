from __future__ import annotations

import importlib
import math
import random
import sys
import tracemalloc
from array import array

import pytest


@pytest.fixture
def kernel(addon_package):
    return importlib.import_module(f"{addon_package}.tools.pixel_brush")


def legacy(source, width, strokes, role, srgb=False):
    """Pre-tiled mathematical reference: original full rectangles/double coverage.

    Deliberately does not call the tile planner, comparison walker or paint kernel.
    This is a compatibility oracle, not an independent artistic-quality verdict.
    """
    result = array("f", source)
    if srgb:
        for i in range(0, len(result), 4):
            for channel in range(3):
                v = source[i + channel]
                result[i + channel] = v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
    baseline = array("f", result)
    for stroke in strokes:
        coverage = {}
        r, hardness = stroke["radius"], stroke["hardness"]
        for a, b, (x0, y0, x1, y1) in stroke["regions"]:
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = dx*dx + dy*dy
            for y in range(y0, y1):
                for x in range(x0, x1):
                    vx, vy = x + .5 - a[0], y + .5 - a[1]
                    t = max(0., min(1., (vx*dx + vy*dy)/length)) if length else 0.
                    distance = math.hypot(vx-t*dx, vy-t*dy)
                    if distance >= r:
                        continue
                    q = 1. if distance <= r*hardness else (r-distance)/(r*(1-hardness))
                    coverage[y*width+x] = max(coverage.get(y*width+x, 0.),
                        max(0., min(1., q*q*(3-2*q))) * stroke["opacity"])
        color = stroke["color"]
        for index, amount in coverage.items():
            if not amount:
                continue
            offset = index*4
            if role == "DATA":
                for channel in range(4):
                    result[offset+channel] = result[offset+channel]*(1-amount)+color[channel]*amount
            else:
                amount *= color[3]
                if stroke["blend"] == "ERASE_ALPHA":
                    result[offset+3] *= 1-amount
                else:
                    alpha = amount + result[offset+3]*(1-amount)
                    if alpha:
                        for channel in range(3):
                            result[offset+channel] = (color[channel]*amount + result[offset+channel]*result[offset+3]*(1-amount))/alpha
                    result[offset+3] = alpha
    changed = [i//4 for i in range(0, len(result), 4) if result[i:i+4] != baseline[i:i+4]]
    return result, len(changed), [[i % width, i//width] for i in changed[:64]]


@pytest.mark.parametrize("seed", range(45))
def test_tiles_match_original_pixels_counts_and_global_example_order(kernel, seed):
    rng = random.Random(seed)
    width, height = rng.choice([1, 17, 63, 64, 65, 127, 129]), rng.choice([1, 31, 63, 65, 129])
    role, srgb = ("DATA", False) if seed % 3 == 0 else ("COLOR", seed % 3 == 1)
    source = array("f", [rng.random() for _ in range(width*height*4)])
    raw = []
    for _ in range(3):
        points = [[rng.choice([0., .5, 1., rng.random()]), rng.choice([0., .5, 1., rng.random()])] for _ in range(rng.randint(1, 4))]
        raw.append({"points": points, "radius_pixels": rng.choice([.5, 2., 8., 64.]),
                    "color": [rng.random() for _ in range(4)], "hardness": rng.choice([0., .8, 1.]),
                    "opacity": rng.choice([0., .25, 1.]),
                    "blend": "ERASE_ALPHA" if role == "COLOR" and rng.random() < .3 else "MIX"})
    prepared, _ = kernel.prepare(raw, width, height, role)
    expected, count, examples = legacy(source, width, prepared, role, srgb)
    actual, info = kernel.paint(source, width, height, prepared, role, srgb=srgb)
    assert actual == expected
    assert info["painted_pixels"] == count and info["changed_pixel_examples"] == examples
    assert info["coverage_scratch_max_bytes"] <= 64*64*8 and info["baseline_copy_bytes"] == 0


def test_long_diagonal_plans_narrow_tile_bands_instead_of_full_rectangle(kernel):
    strokes, tests = kernel.prepare([{"points": [[0., 0.], [1., 1.]], "radius_pixels": 16., "color": [1., 0., 0., 1.]}], 4096, 4096, "COLOR")
    assert tests < 4096*4096//8 and len(strokes[0]["tiles"]) < 256
    assert tests == sum((b[2]-b[0])*(b[3]-b[1]) for regions in strokes[0]["tiles"].values() for _a, _c, b in regions)


def test_preparation_checks_cancellation_before_pixel_allocation(kernel):
    def stop():
        raise RuntimeError("cancel tile planning")
    with pytest.raises(RuntimeError, match="tile planning"):
        kernel.prepare([{"points": [[0., 0.], [1., 1.]], "radius_pixels": 16., "color": [1., 0., 0., 1.]}], 4096, 4096, "COLOR", check=stop)


def test_coverage_and_baseline_storage_are_bounded_not_image_sized(kernel):
    source = array("f", [0., 0., 0., 1.]) * (128*128)
    prepared, _ = kernel.prepare([{"points": [[.5, .5]], "radius_pixels": 128., "color": [1., 0., 0., 1.]}], 128, 128, "COLOR")
    def peak(function):
        tracemalloc.start()
        try:
            result = function()
            return result, tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    (actual, info), tiled_peak = peak(lambda: kernel.paint(source, 128, 128, prepared, "COLOR"))
    (expected, _, _), old_peak = peak(lambda: legacy(source, 128, prepared, "COLOR"))
    assert actual == expected and tiled_peak < old_peak / 2
    assert info["coverage_scratch_max_bytes"] == 32768
    assert info["private_pixel_buffers_peak_estimate_bytes"] == 2*len(source)*4 + 32768


def test_digest_hashes_buffer_without_materializing_a_second_bytes_image(kernel):
    import hashlib
    source = array("f", [0.1, .2, .3, 1.]) * (256*256)
    encoded = array("f", source)
    if sys.byteorder != "little":
        encoded.byteswap()
    expected = hashlib.sha256(encoded.tobytes()).hexdigest()
    tracemalloc.start()
    try:
        assert kernel.digest(source) == expected
        if sys.byteorder == "little":
            assert tracemalloc.get_traced_memory()[1] < len(source)*source.itemsize//8
    finally:
        tracemalloc.stop()
