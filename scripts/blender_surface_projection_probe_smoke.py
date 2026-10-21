"""Analytic native orthographic/UV/occlusion/raw-stencil probes, no public schema.

Run only through run_blender_checks.py. Inputs are disposable factory fixtures.
"""
from __future__ import annotations

import json
import math
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace as NS

import bpy  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.tools import image_paint, image_surface_paint  # noqa: E402

PROJECTOR = {"origin": [0., 0., 1.], "direction": [0., 0., -1.], "up": [0., 1., 0.],
             "width": 2., "height": 2., "near": 0., "far": 2.}
CONTEXT = NS(require=lambda *permissions: None, check_cancelled=None,
             state=NS(snapshot=lambda: {"paused": False, "emergency_stopped": False}))


def mesh(name, vertices, faces, uv=None):
    data = bpy.data.meshes.new(name+"Data")
    data.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    if uv is not None:
        layer = data.uv_layers.new(name="UV")
        for item, value in zip(layer.data, uv, strict=True):
            item.uv = value
    return obj


def image(name, width=8, height=8):
    image_paint.create_image(CONTEXT, {"new_name": name, "width": width, "height": height,
                                     "role": "DATA", "color": [0., 0., 0., 1.]})
    return bpy.data.images[name]


def run(obj, canvas, name, radius=.6, **extra):
    prepared = image_surface_paint.prepare_surface(CONTEXT, {
        "image_name": canvas.name, "new_name": name, "object_name": obj.name, "uv_layer": "UV",
        "face_indices": list(range(len(obj.data.polygons))), "projector": PROJECTOR,
        "strokes": [{"points": [[.5, .5]], "radius_world": radius, "hardness": 1., "color": [1., .25, .5, 1.]}], **extra,
    })
    work = image_surface_paint.projection_steps(prepared)
    phases = set()
    while True:
        try:
            phases.add(next(work)["phase"])
        except StopIteration as done:
            return prepared, done.value, phases


def assert_oracle(values, width, height, fn):
    for y in range(height):
        for x in range(width):
            expected = fn(x, y)
            actual = values[(y*width+x)*4]
            assert abs(actual-expected) < 2e-6, (x, y, actual, expected)


def main():
    quad = mesh("ProjectionQuad", [(-1., -1., 0.), (1., -1., 0.), (1., 1., 0.), (-1., 1., 0.)],
                [(0, 1, 2, 3)], [(0., 0.), (1., 0.), (1., 1.), (0., 1.)])
    canvas = image("ProjectionSource")
    prepared, (values, evidence), phases = run(quad, canvas, "AnalyticProjection")
    assert_oracle(values, 8, 8, lambda x, y: float(math.hypot(-1+(x+.5)/4, -1+(y+.5)/4) < .6))
    published = image_surface_paint.publish(CONTEXT, prepared, (values, evidence))
    assert published["source_pixels_unchanged"] and not published["bound_to_nodes"]
    source = array("f", [0.])*len(canvas.pixels)
    canvas.pixels.foreach_get(source)
    assert all(source[index] == (1. if index % 4 == 3 else 0.) for index in range(len(source)))

    stencil = image("ProjectionStencil", 2, 2)
    stencil.pixels.foreach_set(array("f", [0., 0., 0., 1., 1., 0., 0., 1., 1., 0., 0., 1., 0., 0., 0., 1.]))
    stencil.update()
    _prepared, (masked, _evidence), _ = run(quad, canvas, "StencilProjection", radius=3.,
                                           stencil={"image_name": stencil.name, "channel": "R", "invert": False})
    def bilinear(x, y):
        a = max(0., min(1., (x+.5)/4-.5))
        b = max(0., min(1., (y+.5)/4-.5))
        return a*(1-b)+(1-a)*b
    assert_oracle(masked, 8, 8, bilinear)
    _prepared, (inverse, _evidence), _ = run(quad, canvas, "InverseProjection", radius=3.,
                                            stencil={"image_name": stencil.name, "channel": "R", "invert": True})
    assert_oracle(inverse, 8, 8, lambda x, y: 1-bilinear(x, y))
    assert image_surface_paint.sample_stencil({"width": 2, "height": 2, "values": [0., 1., 1., 0.], "invert": True}, -.1, .5) == 0.

    blocker = mesh("ProjectionBlocker", [(0., -1., .5), (1., -1., .5), (1., 1., .5), (0., 1., .5)], [(0, 1, 2, 3)])
    _prepared, (blocked, blocked_evidence), _ = run(quad, canvas, "OccludedProjection", radius=3., occluder_objects=[blocker.name])
    assert_oracle(blocked, 8, 8, lambda x, y: float(x < 4))
    assert blocked_evidence["occluded_candidates"] == 32

    seam = mesh("ProjectionSeam", [(-1., -1., 0.), (0., -1., 0.), (0., 1., 0.), (-1., 1., 0.),
                                    (0., -1., 0.), (1., -1., 0.), (1., 1., 0.), (0., 1., 0.)],
                [(0, 1, 2, 3), (4, 5, 6, 7)],
                [(0., 0.), (.45, 0.), (.45, 1.), (0., 1.), (.55, 0.), (1., 0.), (1., 1.), (.55, 1.)])
    seam_canvas = image("SeamSource", 16, 8)
    _prepared, (seam_values, _evidence), _ = run(seam, seam_canvas, "SeamProjection", radius=.5)
    def seam_oracle(x, y):
        u, v = (x+.5)/16, (y+.5)/8
        if .45 < u < .55:
            return 0.
        world_x = -1+u/.45 if u <= .45 else (u-.55)/.45
        return float(math.hypot(world_x, -1+2*v) < .5)
    assert_oracle(seam_values, 16, 8, seam_oracle)
    assert any(seam_values[(y*16+6)*4] for y in range(8)) and any(seam_values[(y*16+9)*4] for y in range(8))

    overlap = mesh("ProjectionOverlap", [(-1., -1., 0.), (0., -1., 0.), (0., 1., 0.), (-1., 1., 0.),
                                          (0., -1., 0.), (1., -1., 0.), (1., 1., 0.), (0., 1., 0.)],
                   [(0, 1, 2, 3), (4, 5, 6, 7)], [(0., 0.), (1., 0.), (1., 1.), (0., 1.)]*2)
    try:
        run(overlap, canvas, "MustNotAllocate")
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    else:
        raise AssertionError("Overlapping UVs must fail before publication")
    assert bpy.data.images.get("MustNotAllocate") is None
    print("BLENDER_CODEX_SURFACE_PROJECTION_PROBE_OK " + json.dumps({
        "blender_version": bpy.app.version_string, "analytic_complete_pixels": True,
        "seam_projection_verified": True, "opaque_occlusion_verified": True,
        "raw_stencil_bilinear_invert_outside_verified": True, "uv_overlap_refused": True,
        "private_phases": sorted(phases), "source_preserved": True,
        "full_paint_acceptance_verified": False, "project_saved": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
