from __future__ import annotations

# Shared pytest fixtures are deliberately imported under their public names.
# ruff: noqa: F811
import asyncio
import copy
import importlib
import math
import struct
import weakref
from array import array
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError
from test_image_paint import Image, paint_tools  # noqa: F401
from test_paint_jobs import finish, jobs  # noqa: F401

from mcp_server.tools.image_surface_paint import (
    ImageSurfacePaintTools,
    OrthographicProjector,
    SurfaceStroke,
)

PROJECTOR = {"origin": [0., 0., 1.], "direction": [0., 0., -1.], "up": [0., 1., 0.],
             "width": 2., "height": 2., "near": 0., "far": 2.}
STROKE = {"points": [[.5, .5]], "radius_world": .6, "hardness": 1., "color": [1., .25, .5, 1.]}


@pytest.fixture
def surface(addon_package):
    return importlib.import_module(f"{addon_package}.tools.image_surface_paint")


def frozen(surface, width=8, height=8, **extra):
    triangles = [surface.Triangle(1, 0, ((-1., -1., 0.), (1., -1., 0.), (1., 1., 0.)), ((0., 0.), (1., 0.), (1., 1.))),
                 surface.Triangle(1, 0, ((-1., -1., 0.), (1., 1., 0.), (-1., 1., 0.)), ((0., 0.), (1., 1.), (0., 1.)))]
    return {"width": width, "height": height, "values": array("f", [0., 0., 0., 1.])*(width*height),
            "triangles": triangles, "target_id": 1, "faces": frozenset({0}), "projector": surface.projector_spec(PROJECTOR),
            "strokes": surface._strokes([STROKE]), "mask": None, "role": "DATA", "srgb": False, "associated": False, **extra}


def consume(work):
    phases = []
    while True:
        try:
            phases.append(next(work)["phase"])
        except StopIteration as done:
            return done.value, phases


@pytest.mark.parametrize("a,b", [
    ((-0., 0., -0.), (1., -1., 1.)),
    ((1e8, 1., -1e8), (1e8, 1., 1e8)),
    ((.1, -.2, .3), (.7, .8, -.9)),
    ((1e-9, -1e9, 1e-6), (-1e9, 1e-9, -.125)),
])
def test_fixed_vector_math_preserves_builtin_sum_bits_and_default_start(surface, a, b):
    assert struct.pack("<d", surface._dot3(a, b)) == struct.pack("<d", surface._dot(a, b))
    assert struct.pack("<3d", *surface._sub3(a, b)) == struct.pack("<3d", *surface._sub(a, b))
    world = (a, b, (-b[0], -a[1], -0.))
    for bary in ((.1, .2, .7), (1., -0., 0.), (.5, .5, -1e-10)):
        expected = tuple(sum(bary[i]*world[i][axis] for i in range(3)) for axis in range(3))
        assert struct.pack("<3d", *surface._world_point(bary, world)) == struct.pack("<3d", *expected)


@pytest.mark.parametrize("uv", [
    ((-0., 0.), (1., -0.), (1., 1.)),
    ((0., 0.), (1., 1.), (-0., 1.)),
    ((1., 1.), (1., -0.), (0., 0.)),
    ((-.1234567, .7654321), (.9876543, -.3456789), (.4567891, .8912345)),
    ((-1000.25, 2000.5), (3000.125, -4000.25), (999.75, 1333.125)),
])
def test_cached_uv_terms_preserve_full_float64_barycentric_bits(surface, uv):
    terms = surface._uv_terms(uv)
    for point in (*uv, (-0., 0.), (.5, .5), (.1, .9), (1e-13, -1e-13), (1.+1e-13, 1.-1e-13)):
        actual = surface._bary_prepared(point, terms)
        expected = surface._bary(point, uv)
        assert struct.pack("<3d", *actual) == struct.pack("<3d", *expected)


@pytest.mark.parametrize("points", [
    [[.5, .5]],
    [[-0., 0.], [.2, .8], [.2, .8], [1., 1.]],
    [[(index % 2)*.75, ((index*7) % 13)/13] for index in range(128)],
])
@pytest.mark.parametrize("hardness", [0., .371, 1.])
def test_cached_stroke_segments_preserve_complete_coverage_float64_bits(surface, points, hardness):
    stroke = surface._strokes([{**STROKE, "points": points, "hardness": hardness,
                                "opacity": .123456789, "radius_world": .421357}])[0]
    for width, height in ((2., 2.), (1.234567, 7.654321)):
        projector = {"width": width, "height": height}
        segments = surface._stroke_segments(stroke, projector)
        assert len(segments) == max(1, len(points)-1)
        for u, v in ((-0., 0.), (.5, .5), (.1, .9), (.25, .125), (1., 1.), (1e-13, 1.-1e-13)):
            actual = surface._coverage_prepared(u, v, stroke, projector, segments)
            expected = surface._coverage(u, v, stroke, projector)
            assert struct.pack("<d", actual) == struct.pack("<d", expected)


@pytest.mark.parametrize("case", [
    "plain", "stencil", "inverted_stencil", "polyline", "single_point", "edge_ambiguity",
    "uv_overlap", "coincident_occluder", "occluded", "backfacing", "signed_zero",
    "srgb", "associated", "zero_alpha", "degenerate_uv", "degenerate_world",
    "candidate_limit", "ray_limit", "segment_limit", "invalid_stencil",
])
def test_cached_projection_preserves_full_pixels_refusals_and_safe_point_sequence(surface, monkeypatch, case):
    prepared = frozen(surface, width=65, height=3)
    prepared["strokes"] = surface._strokes([{**STROKE, "points": [[.2, .4], [.8, .6]],
                                            "radius_world": .431357, "hardness": .37, "opacity": .37}])
    if case in {"stencil", "inverted_stencil", "invalid_stencil"}:
        channel = array("f", [0., .2, .4, .6, .8, 1.])
        if case == "invalid_stencil":
            channel[-1] = float("nan")
        prepared["mask"] = {"kernel": {"width": 3, "height": 2, "values": channel,
                                       "invert": case == "inverted_stencil"}}
    if case == "polyline":
        prepared["strokes"] = surface._strokes([
            {**STROKE, "points": [[.1, .1], [.3, .7], [.3, .7], [.9, .9]], "opacity": .7},
            {**STROKE, "points": [[.8, .2]], "hardness": 0., "opacity": .3},
        ])
    if case == "single_point":
        prepared["strokes"] = surface._strokes([STROKE])
    if case == "edge_ambiguity":
        split = 32.5/65
        triangles = []
        for left, right, depth in ((0., split, 0.), (split, 1., .1)):
            uv = ((left, 0.), (right, 0.), (right, 1.), (left, 1.))
            world = tuple((2*u-1, 2*v-1, depth) for u, v in uv)
            for a, b, c in ((0, 1, 2), (0, 2, 3)):
                triangles.append(surface.Triangle(1, 0, (world[a], world[b], world[c]), (uv[a], uv[b], uv[c])))
        prepared["triangles"] = triangles
        prepared["strokes"][0]["opacity"] = 0.  # Whole ownership proof still applies outside paint.
    if case == "uv_overlap":
        prepared["triangles"].append(replace(prepared["triangles"][0], face=7))
    if case in {"coincident_occluder", "occluded"}:
        depth = 0. if case == "coincident_occluder" else .5
        for triangle in list(prepared["triangles"]):
            prepared["triangles"].append(surface.Triangle(9, 0, tuple((x, y, z+depth) for x, y, z in triangle.world), None))
    if case == "backfacing":
        prepared["triangles"] = [replace(t, world=(t.world[0], t.world[2], t.world[1]), uv=(t.uv[0], t.uv[2], t.uv[1]))
                                 for t in prepared["triangles"]]
    if case == "signed_zero":
        prepared["values"] = array("f", [-0., 0., -0., 1.])*(65*3)
        prepared["triangles"] = [replace(t, world=tuple((x, y, -0.) for x, y, _z in t.world)) for t in prepared["triangles"]]
        prepared["strokes"][0]["opacity"] = 0.
    if case in {"srgb", "associated", "zero_alpha"}:
        rgba = [.5, .25, 1., .5] if case == "srgb" else [.1, .2, .3, .5] if case == "associated" else [0., 0., 0., 0.]
        prepared.update(role="COLOR", srgb=case == "srgb", associated=case != "srgb", values=array("f", rgba)*(65*3))
        prepared["strokes"] = surface._strokes([{**STROKE, "color": [2., .2, .7, .37],
                                                "blend": "ERASE_ALPHA" if case == "zero_alpha" else "MIX"}])
    if case == "degenerate_uv":
        prepared["triangles"][0] = replace(prepared["triangles"][0], uv=((0., 0.),)*3)
    if case == "degenerate_world":
        prepared["triangles"][0] = replace(prepared["triangles"][0], world=((0., 0., 0.), (1., 1., 1.), (2., 2., 2.)))
    if case in {"candidate_limit", "ray_limit", "segment_limit"}:
        field = {"candidate_limit": "candidates", "ray_limit": "rays", "segment_limit": "segments"}[case]
        prepared["strokes"][0]["radius"] = 3.
        prepared["limits"] = replace(surface._limits(), **{field: 1})

    def run(data):
        checks, progress, before = [], [], data["values"].tobytes()
        work = surface.projection_steps(data, lambda: checks.append(True))
        try:
            while True:
                progress.append(next(work))
        except StopIteration as finished:
            values, evidence = finished.value
            outcome = ("result", values.tobytes(), evidence)
        except surface.BridgeError as error:
            outcome = ("error", error.code, error.message, error.context)
        assert data["values"].tobytes() == before
        return outcome, progress, len(checks), data.get("tests")

    optimized = run(copy.deepcopy(prepared))
    with monkeypatch.context() as reference:
        reference.setattr(surface, "_sub3", surface._sub)
        reference.setattr(surface, "_dot3", surface._dot)
        reference.setattr(surface, "_world_point", lambda bary, world: tuple(
            sum(bary[i]*world[i][axis] for i in range(3)) for axis in range(3)))
        reference.setattr(surface, "_uv_terms", lambda uv: uv)
        reference.setattr(surface, "_bary_prepared", surface._bary)
        reference.setattr(surface, "_stroke_segments", lambda _stroke, _projector: None)
        reference.setattr(surface, "_coverage_prepared", lambda u, v, stroke, projector, _segments:
                          surface._coverage(u, v, stroke, projector))
        expected = run(copy.deepcopy(prepared))
    assert optimized == expected


def parameters(**extra):
    return {"image_name": "Original", "new_name": "Projected", "object_name": "Target", "uv_layer": "UV",
            "face_indices": [0], "projector": copy.deepcopy(PROJECTOR), "strokes": [copy.deepcopy(STROKE)], **extra}


def setup_fake(surface, bpy, monkeypatch):
    record = {"object_name": "Target", "mesh_name": "TargetMesh", "mesh_id": 2, "object_id": 1,
              "positions": [(-1., -1., 0.), (1., -1., 0.), (1., 1., 0.), (-1., 1., 0.)], "uv_name": "UV",
              "faces": [((0, 1, 2, 3), False, 0)], "revision": 0}
    triangles = frozen(surface)["triangles"]
    bpy.context.view_layer = NS(update=lambda: None)
    bpy.data.user_map = lambda **_kwargs: {}
    monkeypatch.setattr(surface, "require_blender", lambda: bpy)
    monkeypatch.setattr(surface, "_mesh_record", lambda *_a: (copy.deepcopy(record), list(triangles)))
    return record, triangles


@pytest.fixture
def live(surface, paint_tools, monkeypatch):
    paint, context, images, bpy, grants = paint_tools
    record, triangles = setup_fake(surface, bpy, monkeypatch)
    return NS(surface=surface, paint=paint, context=context, images=images, bpy=bpy, grants=grants, record=record, triangles=triangles)


def test_analytic_world_disk_complete_pixels_and_shared_uv_diagonal_dedup(surface):
    prepared = frozen(surface)
    (output, info), phases = consume(surface.projection_steps(prepared))
    expected = [float(math.hypot(-1+(x+.5)/4, -1+(y+.5)/4) < .6) for y in range(8) for x in range(8)]
    assert list(output[::4]) == expected and info["painted_pixels"] == sum(expected)
    assert prepared["values"] == array("f", [0., 0., 0., 1.])*64
    assert "validating_geometry" in phases and "comparing" in phases


def test_named_opaque_half_occluder_and_self_occlusion(surface):
    prepared = frozen(surface)
    blocker = surface.Triangle(9, 0, ((0., -1., .5), (1., -1., .5), (1., 1., .5)), None)
    blocker2 = surface.Triangle(9, 0, ((0., -1., .5), (1., 1., .5), (0., 1., .5)), None)
    prepared["triangles"] += [blocker, blocker2]
    prepared["strokes"][0]["radius"] = 3.
    (output, evidence), _ = consume(surface.projection_steps(prepared))
    assert list(output[::4]) == [float(x < 4) for y in range(8) for x in range(8)]
    assert evidence["occluded_candidates"] == 32
    # Identical opaque geometry is an explicit ambiguity, never guessed visibility.
    prepared["triangles"][-2:] = [surface.Triangle(9, 0, triangle.world, None) for triangle in prepared["triangles"][:2]]
    with pytest.raises(surface.BridgeError, match="Coincident"):
        consume(surface.projection_steps(prepared))


def test_uv_overlap_including_unscoped_faces_rejects_before_pixel_work(surface):
    prepared = frozen(surface)
    prepared["triangles"].append(surface.Triangle(1, 9, prepared["triangles"][0].world, prepared["triangles"][0].uv))
    with pytest.raises(surface.BridgeError, match="overlap"):
        consume(surface.projection_steps(prepared))


@pytest.mark.parametrize("face_index", [0, 9])
def test_coincident_same_target_face_interiors_with_distinct_uvs_are_not_guessed(surface, face_index):
    prepared = frozen(surface)
    # This face is outside painted UV scope, but occupies the same world surface.
    first = prepared["triangles"][0]
    prepared["triangles"] = [surface.Triangle(1, 0, triangle.world, tuple((u*.5, v) for u, v in triangle.uv)) for triangle in prepared["triangles"]]
    prepared["triangles"].append(surface.Triangle(1, face_index, first.world, ((.9, .9), (1., .9), (1., 1.))))
    with pytest.raises(surface.BridgeError, match="Coincident target triangle"):
        consume(surface.projection_steps(prepared))


def test_distinct_surface_points_at_shared_uv_boundary_fail_closed(surface):
    prepared = frozen(surface, width=1, height=1)
    second = prepared["triangles"][1]
    prepared["triangles"][1] = surface.Triangle(1, 0, tuple((x, y, z+.1) for x, y, z in second.world), second.uv)
    with pytest.raises(surface.BridgeError, match="distinct surface points"):
        consume(surface.projection_steps(prepared))


@pytest.mark.parametrize("reverse", [False, True])
def test_shared_uv_boundary_front_back_disagreement_rejects_in_either_native_order(surface, reverse):
    prepared = frozen(surface, width=1, height=1)
    back = surface.Triangle(1, 0, ((-1., -1., 0.), (1., 1., 0.), (1., -1., 0.)), ((0., 0.), (1., 1.), (1., 0.)))
    front = surface.Triangle(1, 1, ((-1., -1., 0.), (1., 1., 0.), (-1., 1., 0.)), ((0., 0.), (1., 1.), (0., 1.)))
    prepared["triangles"] = [front, back] if reverse else [back, front]
    prepared["faces"] = frozenset({0, 1})
    with pytest.raises(surface.BridgeError, match="ambiguous front-facing"):
        consume(surface.projection_steps(prepared))


@pytest.mark.parametrize("invert", [False, True])
def test_raw_projector_stencil_bilinear_clamp_and_zero_outside_even_inverted(surface, invert):
    mask = {"width": 2, "height": 2, "values": array("f", [0., 1., 1., 0.]), "invert": invert}
    assert surface.sample_stencil(mask, .5, .5) == .5
    assert surface.sample_stencil(mask, 0, 0) == float(invert)
    assert surface.sample_stencil(mask, -.001, .5) == 0.
    assert surface.sample_stencil(mask, .5, 1.001) == 0.
    prepared = frozen(surface, mask={"kernel": mask})
    prepared["strokes"][0]["radius"] = 3.
    (output, _), phases = consume(surface.projection_steps(prepared))
    expected = []
    for y in range(8):
        for x in range(8):
            a, b = max(0., min(1., (x+.5)/4-.5)), max(0., min(1., (y+.5)/4-.5))
            value = a*(1-b)+(1-a)*b
            expected.append(1-value if invert else value)
    assert list(output[::4]) == pytest.approx(expected) and "validating_stencil" in phases


@pytest.mark.parametrize("bad", [math.nan, math.inf, -.1, 1.1])
def test_entire_stencil_channel_validates_even_outside_stroke(surface, bad):
    prepared = frozen(surface, mask={"kernel": {"width": 2, "height": 2, "values": [0., 0., 0., bad], "invert": False}})
    with pytest.raises(surface.BridgeError, match="Complete selected stencil"):
        consume(surface.projection_steps(prepared))


@pytest.mark.parametrize("change", [{"direction": [0., 0., 0.]}, {"up": [0., 0., -1.]}, {"far": 0.},
                                    {"near": 2., "far": 1.}, {"width": math.nan}, {"height": True}, {"perspective": True}])
def test_projector_rejects_ambiguous_nonfinite_unknown_frames_before_blender(surface, change):
    with pytest.raises(surface.BridgeError):
        surface.projector_spec({**PROJECTOR, **change})


@pytest.mark.parametrize("change", [{"radius_world": 0.}, {"points": []}, {"points": [[True, .5]]}, {"color": [0., 0., 0., 2.]},
                                    {"blend": "INVENT"}, {"extra": 1}, {"opacity": math.inf}])
def test_projected_stroke_syntax_and_budgets(surface, change):
    with pytest.raises(surface.BridgeError):
        surface._strokes([{**STROKE, **change}])
    with pytest.raises(surface.BridgeError, match="256"):
        surface._strokes([{**STROKE, "points": [[.5, .5]]*128}]*3)


@pytest.mark.parametrize("bound", ["MAX_CANDIDATES", "MAX_RAY_TESTS", "MAX_STROKE_TESTS"])
def test_work_budgets_fail_before_publication_and_preserve_input(surface, monkeypatch, bound):
    prepared = frozen(surface)
    prepared["strokes"][0]["radius"] = 3.
    monkeypatch.setattr(surface, bound, 1)
    with pytest.raises(surface.BridgeError, match="Projection exceeds 1 ") as caught:
        consume(surface.projection_steps(prepared))
    assert caught.value.context == {"limit": 1, "observed": 2}
    assert prepared["values"] == array("f", [0., 0., 0., 1.])*64


def test_private_projection_is_cooperative_before_raster_and_cancellable(surface):
    prepared = frozen(surface, width=64, height=64)
    checks = []
    def check():
        checks.append(True)
        if len(checks) == 5:
            raise RuntimeError("cancelled")
    work = surface.projection_steps(prepared, check)
    assert next(work)["phase"] == "validating_geometry"
    with pytest.raises(RuntimeError, match="cancelled"):
        consume(work)
    assert prepared["values"] == array("f", [0., 0., 0., 1.])*4096


def test_new_image_preserves_complete_source_and_geometry(live):
    env = live
    before = env.paint.brush.digest(env.images[0].pixels.values)
    record = copy.deepcopy(env.record)
    result = env.surface.paint_surface_version(env.context, parameters())
    assert result["source_pixels_unchanged"] and result["geometry_and_uv_inputs_unchanged"]
    assert result["painted_pixels"] and not result["bound_to_nodes"] and not result["file_written"]
    assert env.paint.brush.digest(env.images[0].pixels.values) == before and env.record == record
    assert result["painted_image"]["name"] == "Projected" and not result["full_texture_paint_workflow_verified"]


@pytest.mark.parametrize("grant", ["EDIT_MATERIALS", "INSPECT_SCENE"])
def test_both_live_permissions_required_before_read_and_write(live, grant):
    live.grants[grant] = False
    with pytest.raises(live.surface.BridgeError, match="permission denied"):
        live.surface.paint_surface_version(live.context, parameters())
    assert len(live.images) == 1


@pytest.mark.parametrize("change", ["geometry", "source_pixels", "source_identity", "source_metadata", "mode", "output_name", "permission"])
def test_frozen_scope_changes_before_publication_never_allocate(live, change):
    env = live
    prepared = env.surface.prepare_surface(env.context, parameters())
    output, _ = consume(env.surface.projection_steps(prepared))
    if change == "geometry":
        env.record["revision"] += 1
    elif change == "source_pixels":
        env.images[0].pixels.values[0] = .9
    elif change == "source_identity":
        env.images[0] = Image("Original")
    elif change == "source_metadata":
        env.images[0].alpha_mode = "CHANNEL_PACKED"
    elif change == "mode":
        env.bpy.context.mode = "EDIT_MESH"
    elif change == "output_name":
        env.images.append(Image("Projected"))
    else:
        env.grants["INSPECT_SCENE"] = False
    with pytest.raises(env.surface.BridgeError):
        env.surface.publish(env.context, prepared, output)
    assert len(env.images) == (2 if change == "output_name" else 1)


@pytest.mark.parametrize("allow_delete", [False, True])
def test_every_native_callback_revalidates_geometry_before_next_image_write(live, monkeypatch, allow_delete):
    env = live
    env.grants["DELETE_OBJECTS"] = allow_delete
    original_new = env.images.new
    def allocate(*args, **kwargs):
        image = original_new(*args, **kwargs)
        # Native allocation has happened; the following safe point must observe
        # a callback's geometry change and cannot write pixels into this image.
        env.context.check_cancelled = lambda: env.record.update(revision=1)
        image.pixels.foreach_set = lambda _values: pytest.fail("stale geometry must block pixel publication")
        return image
    monkeypatch.setattr(env.images, "new", allocate)
    with pytest.raises(env.surface.BridgeError) as error:
        env.surface.paint_surface_version(env.context, parameters())
    # New guarded cleanup retains the output when frozen input authority is stale,
    # including with a deletion grant; no hidden cleanup writes through stale scope.
    assert error.value.context["possible_mutation"] and error.value.context["execution_started"]
    assert env.images.get("Projected") is not None


@pytest.mark.parametrize("acquired", ["counted_consumer", "id_map_consumer", "renamed"])
def test_output_scope_changes_in_first_postallocation_callback_prevent_all_further_writes(live, monkeypatch, acquired):
    env, writes, consumer = live, [], NS(image=None)
    env.grants["DELETE_OBJECTS"] = False
    original_new = env.images.new
    class WatchedImage(Image):
        def __setattr__(self, key, value):
            if key in {"use_fake_user", "alpha_mode"}:
                writes.append(key)
            super().__setattr__(key, value)
    class WatchedSpace:
        def __init__(self, name):
            self._name = name
        @property
        def name(self):
            return self._name
        @name.setter
        def name(self, value):
            writes.append("colorspace")
            self._name = value
    def allocate(*args, **kwargs):
        image = original_new(*args, **kwargs)
        image.__class__ = WatchedImage
        image.colorspace_settings = WatchedSpace(image.colorspace_settings.name)
        image.pixels.foreach_set = lambda _values: writes.append("pixels")
        def acquire():
            if acquired == "renamed":
                image.name = "Retained Renamed Output"
            else:
                consumer.image = image
                if acquired == "counted_consumer":
                    image.users = 1
                else:
                    # Native ID maps can reveal references beyond the public
                    # counter. Do not rely on users==0 as complete privacy proof.
                    env.bpy.data.user_map = lambda **_kwargs: {image: [consumer]}
        env.context.check_cancelled = acquire
        return image
    monkeypatch.setattr(env.images, "new", allocate)
    with pytest.raises(env.surface.BridgeError) as error:
        env.surface.paint_surface_version(env.context, parameters())
    assert writes == [] and error.value.context["possible_mutation"]
    actual = "Retained Renamed Output" if acquired == "renamed" else "Projected"
    assert error.value.context["retained_image_name"] == actual
    assert env.images.get(actual) is not None
    if acquired != "renamed":
        assert consumer.image is env.images.get(actual)


def test_consumer_attached_by_final_readback_callback_is_retained_and_never_succeeds(live, monkeypatch):
    env, consumer = live, NS(image=None)
    env.grants["DELETE_OBJECTS"] = False
    original_read = env.paint._read
    def read(context, image, **kwargs):
        result = original_read(context, image, **kwargs)
        if image.name == "Projected":
            consumer.image, image.users = image, 1
        return result
    monkeypatch.setattr(env.paint, "_read", read)
    with pytest.raises(env.surface.BridgeError) as error:
        env.surface.paint_surface_version(env.context, parameters())
    assert error.value.context["stale_output"] and error.value.context["possible_mutation"]
    assert error.value.context["retained_image_name"] == "Projected" and consumer.image is env.images.get("Projected")


def test_job_reports_actual_renamed_retained_allocation_in_error_and_effects(surface, jobs, monkeypatch):
    env = jobs
    setup_fake(surface, env.bpy, monkeypatch)
    surface.register_tools(env.context().registry)
    env.grants["DELETE_OBJECTS"] = False
    original_read = env.paint._read
    def read(context, image, **kwargs):
        result = original_read(context, image, **kwargs)
        if image.name == "Projected":
            image.name = "Actual Retained Output"
        return result
    monkeypatch.setattr(env.paint, "_read", read)
    env.manager.start_surface_paint(env.context(), parameters(), 60.)
    done = finish(env)
    assert done["state"] == "FAILED" and done["error"]["context"]["retained_image_name"] == "Actual Retained Output"
    assert done["external_effects"]["last_observed_projected_image_name"] == "Actual Retained Output"
    assert env.images.get("Actual Retained Output") is not None


def test_refreshed_geometry_rechecks_global_caps_and_face_scope(live):
    env = live
    def update():
        env.record["faces"][0] = ((0, 1, 2, 3), True, 0)
    env.bpy.context.view_layer.update = update
    with pytest.raises(env.surface.BridgeError, match="Refreshed projection face"):
        env.surface.prepare_surface(env.context, parameters())
    assert len(env.images) == 1


def test_source_and_stencil_can_be_same_image_but_late_raw_channel_change_is_stale(live):
    env = live
    prepared = env.surface.prepare_surface(env.context, parameters(stencil={"image_name": "Original", "channel": "R"}))
    output, _ = consume(env.surface.projection_steps(prepared))
    env.images[0].pixels.values[-4] = .8
    with pytest.raises(env.surface.BridgeError, match="pixels or approved FILE"):
        env.surface.publish(env.context, prepared, output)
    assert len(env.images) == 1


def test_file_proof_is_frozen_and_live_consent_not_replaced_by_loaded_pixels(live, monkeypatch):
    env = live
    original = env.paint._read
    proof = {"sha256": "initial"}
    def read(context, image, **kwargs):
        values, width, height, _file = original(context, image, **kwargs)
        return values, width, height, dict(proof)
    monkeypatch.setattr(env.paint, "_read", read)
    prepared = env.surface.prepare_surface(env.context, parameters())
    output, _ = consume(env.surface.projection_steps(prepared))
    proof["sha256"] = "changed"
    with pytest.raises(env.surface.BridgeError, match="approved FILE proof"):
        env.surface.publish(env.context, prepared, output)
    assert len(env.images) == 1


def native_mesh_fake():
    data = NS(vertices=[NS(co=(-1., -1., 0.)), NS(co=(1., -1., 0.)), NS(co=(0., 1., 0.))],
              polygons=[NS(vertices=(0, 1, 2), hide=False, material_index=0)], loops=[NS(vertex_index=i) for i in range(3)],
              edges=[NS(vertices=pair) for pair in ((0, 1), (1, 2), (2, 0))],
              uv_layers={"UV": NS(data=[NS(uv=point) for point in ((0., 0.), (1., 0.), (.5, 1.))])},
              loop_triangles=[NS(polygon_index=0, loops=(0, 1, 2))], calc_loop_triangles=lambda: None,
              animation_data=None, shape_keys=None, is_editmode=False, name="MeshData", users=2)
    obj = NS(name="Mesh", type="MESH", mode="OBJECT", data=data, parent=None, constraints=[], animation_data=None,
             modifiers=[], hide_viewport=False, hide_get=lambda: False, material_slots=[],
             matrix_world=((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.)),
             location=(0., 0., 0.), rotation_mode="XYZ", rotation_euler=(0., 0., 0.), rotation_quaternion=(1., 0., 0., 0.),
             rotation_axis_angle=(0., 0., 0., 1.), scale=(1., 1., 1.), delta_location=(0., 0., 0.), delta_rotation_euler=(0., 0., 0.),
             delta_rotation_quaternion=(1., 0., 0., 0.), delta_scale=(1., 1., 1.))
    return NS(data=NS(objects=[obj]), context=NS(view_layer=NS(objects={obj.name: obj}))), obj


def test_read_only_shared_mesh_is_valid_and_rna_triangle_wrappers_are_frozen(surface):
    bpy, obj = native_mesh_fake()
    record, triangles = surface._mesh_record(bpy, "Mesh", "UV")
    assert record["mesh_users"] == 2
    obj.data.vertices[0].co = (7., 8., 9.)
    obj.data.loop_triangles[0].loops = (1, 2, 0)
    assert triangles[0].world[0] == (-1., -1., 0.) and record["positions"][0] == (-1., -1., 0.)


def test_authored_transform_edit_is_detected_before_matrix_update(surface):
    bpy, obj = native_mesh_fake()
    before, _ = surface._mesh_record(bpy, "Mesh", "UV")
    obj.location = (1., 0., 0.)
    after, _ = surface._mesh_record(bpy, "Mesh", "UV")
    assert before["matrix"] == after["matrix"] and before != after


@pytest.mark.parametrize("field,value", [("parent", object()), ("animation_data", object()), ("constraints", [object()]), ("modifiers", [object()])])
def test_unsupported_derived_geometry_dependencies_reject_explicitly(surface, field, value):
    bpy, obj = native_mesh_fake()
    setattr(obj, field, value)
    with pytest.raises(surface.BridgeError) as error:
        surface._mesh_record(bpy, "Mesh", "UV")
    assert error.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("blend,expected", [("MIX", [7/15, 4/15, .4, .75]), ("ERASE_ALPHA", [.2, .4, .6, .25])])
def test_projected_color_straight_source_over_or_erase_with_stencil(surface, blend, expected):
    prepared = frozen(surface, width=1, height=1, role="COLOR", values=array("f", [.2, .4, .6, .5]))
    prepared["strokes"] = surface._strokes([{**STROKE, "radius_world": 3., "color": [1., 0., 0., 1.], "blend": blend}])
    prepared["mask"] = {"kernel": {"width": 1, "height": 1, "values": [.5], "invert": False}}
    (output, _), _phases = consume(surface.projection_steps(prepared))
    # Half-coverage red contributes .5 while old alpha contributes .25.
    if blend == "MIX":
        expected = [.55/.75, .1/.75, .15/.75, .75]
    assert list(output) == pytest.approx(expected)


def test_cooperative_job_does_not_build_footprint_before_handoff(surface, jobs, monkeypatch):
    env = jobs
    setup_fake(surface, env.bpy, monkeypatch)
    surface.register_tools(env.context().registry)
    original = surface.projection_steps
    calls = []
    def tracked(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(surface, "projection_steps", tracked)
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle = lifetime
    result = env.manager.start_surface_paint(context, parameters(), 60.)
    assert result["accepted"] and not result["projection_work_started"] and not result["painting_completed"]
    assert not calls and not env.marks
    env.manager.tick()
    assert not calls and not env.marks and env.manager.active.work is None
    lifetime.acknowledge(True)
    done = finish(env)
    assert done["state"] == "SUCCEEDED" and done["undo_boundary_finalized"] and len(env.marks) == 2
    assert calls and env.images.get("Projected") is not None
    assert env.manager.history[0].prepared == {} and env.manager.history[0].driver is None


@pytest.mark.parametrize("failure", ["cancel", "stale_geometry", "checkpoint_geometry", "permission", "source_pixels"])
def test_surface_jobs_fail_closed_before_output_and_share_existing_lifecycle(surface, jobs, monkeypatch, failure):
    env = jobs
    record, _triangles = setup_fake(surface, env.bpy, monkeypatch)
    surface.register_tools(env.context().registry)
    env.manager.start_surface_paint(env.context(), parameters(), 60.)
    if failure == "cancel":
        env.manager.cancel(env.manager.active.job_id)
    elif failure == "stale_geometry":
        record["revision"] += 1
    elif failure == "checkpoint_geometry":
        env.checkpoints.before_modification = lambda _label: record.update(revision=1) or True
    elif failure == "permission":
        env.grants["INSPECT_SCENE"] = False
    else:
        env.images[0].pixels.values[0] = .9
    done = finish(env)
    assert done["state"] == ("CANCELLED" if failure == "cancel" else "FAILED")
    assert env.images.get("Projected") is None and not done["execution_started"]
    assert not done["error"]["context"]["possible_mutation"]


def test_surface_schema_is_strict_and_mcp_routes_only_reviewed_method():
    projector = OrthographicProjector.model_validate(PROJECTOR)
    stroke = SurfaceStroke.model_validate(STROKE)
    calls = []
    async def call(method, values):
        calls.append((method, values))
        return {"accepted": True}
    tools = ImageSurfacePaintTools(NS(call=call))
    asyncio.run(tools.image_paint_surface_job_start("Original", "Projected", "Target", "UV", [0], projector, [stroke], time_limit_seconds=30.))
    assert calls == [("image.paint_surface_job_start", {**parameters(), "strokes": [stroke.model_dump()], "time_limit_seconds": 30.})]
    assert {binding.name for binding in tools.bindings()} == {"image.paint_surface_version", "image.paint_surface_job_start"}
    for change in ({"direction": [0., 0., 0.]}, {"up": [0., 0., -1.]}, {"far": .01, "near": 1.}, {"width": True}):
        with pytest.raises(ValidationError):
            OrthographicProjector.model_validate({**PROJECTOR, **change})
    with pytest.raises(ValidationError):
        SurfaceStroke.model_validate({**STROKE, "radius_world": True})


@pytest.mark.parametrize("size", [63, 64, 65, 129])
def test_tiled_projection_matches_complete_independent_disk_at_tile_edges(surface, size):
    prepared = frozen(surface, width=size, height=size)
    prepared["strokes"][0]["radius"] = .61327
    source = prepared["values"].tobytes()
    (actual, evidence), _phases = consume(surface.projection_steps(prepared))
    expected, examples = array("f"), []
    for y in range(size):
        for x in range(size):
            inside = math.hypot(-1+2*(x+.5)/size, -1+2*(y+.5)/size) < .61327
            expected.extend([1., .25, .5, 1.] if inside else [0., 0., 0., 1.])
            if inside:
                examples.append([x, y])
    assert actual.tobytes() == expected.tobytes()
    assert prepared["values"].tobytes() == source
    assert evidence["painted_pixels"] == len(examples)
    assert evidence["changed_pixel_examples"] == examples[:64]
    assert evidence["baseline_copy_bytes"] == 0
    assert evidence["ownership_scratch_max_bytes"] <= 64*64*4
    assert evidence["candidate_pixel_tests"] == 2*size*size


def test_owners_are_released_before_next_tile_and_no_full_baseline_is_allocated(surface, monkeypatch):
    prepared = frozen(surface, width=129, height=65)
    prior_owner = []
    allocations = []

    class CheckedArray(array):
        def __mul__(self, count):
            if self.typecode == "i":
                assert count <= 64*64
                assert not prior_owner or prior_owner[-1]() is None
            result = super().__mul__(count)
            if self.typecode == "i":
                prior_owner.append(weakref.ref(result))
                allocations.append(len(result)*result.itemsize)
            return result

    def allocate(kind, values=()):
        if kind == "f":
            assert len(values) <= 3, "a full normalized baseline was allocated"
        return CheckedArray(kind, values)

    monkeypatch.setattr(surface, "array", allocate)
    (_actual, evidence), _phases = consume(surface.projection_steps(prepared))
    assert len(allocations) == 6 and max(allocations) == 16384
    assert all(ref() is None for ref in prior_owner)
    assert evidence["ownership_scratch_max_bytes"] == 16384


@pytest.mark.parametrize("reverse", [False, True])
def test_shared_uv_ambiguity_on_a_tile_edge_is_never_pruned(surface, reverse):
    size, split = 129, 64.5/129
    prepared = frozen(surface, width=size, height=1)
    triangles = []
    for left, right, depth in ((0., split, 0.), (split, 1., .1)):
        uv = ((left, 0.), (right, 0.), (right, 1.), (left, 1.))
        world = tuple((2*u-1, 2*v-1, depth) for u, v in uv)
        for a, b, c in ((0, 1, 2), (0, 2, 3)):
            triangles.append(surface.Triangle(1, 0, (world[a], world[b], world[c]), (uv[a], uv[b], uv[c])))
    prepared["triangles"] = list(reversed(triangles)) if reverse else triangles
    prepared["strokes"][0]["opacity"] = 0.  # Ambiguity outside actual paint still refuses.
    with pytest.raises(surface.BridgeError, match="distinct surface points"):
        consume(surface.projection_steps(prepared))


@pytest.mark.parametrize("srgb,associated,rgba,expected", [
    (True, False, [.5, .25, 1., .5], [.21404114048223255, .05087608817155679, 1., .5]),
    (False, True, [.1, .2, .3, .5], [.2, .4, .6, .5]),
    (False, True, [0., 0., 0., 0.], [0., 0., 0., 0.]),
    (False, False, [.2, .4, .6, 0.], [.2, .4, .6, 0.]),
])
def test_baseline_free_comparison_excludes_normalization_from_brush_counts(surface, srgb, associated, rgba, expected):
    prepared = frozen(surface, width=65, height=3, role="COLOR", srgb=srgb, associated=associated,
                      values=array("f", rgba)*(65*3))
    prepared["strokes"][0]["opacity"] = 0.
    (actual, evidence), _phases = consume(surface.projection_steps(prepared))
    assert actual == array("f", expected)*(65*3)
    assert evidence["painted_pixels"] == 0 and evidence["changed_pixel_examples"] == []
    assert evidence["baseline_copy_bytes"] == 0 and evidence["comparison_pixels"] == 195


@pytest.mark.parametrize("phase", ["raster_tiles", "projecting", "stroke_coverage", "checking_visibility", "comparing"])
def test_each_tiled_private_phase_remains_cancellable_without_changing_inputs(surface, phase):
    prepared = frozen(surface, width=65, height=65)
    before = prepared["values"].tobytes()
    checks, arm = [], []

    def check():
        checks.append(1)
        if arm:
            raise surface.BridgeError("TIMEOUT", "owned cancellation")

    work = surface.projection_steps(prepared, check)
    try:
        while next(work)["phase"] != phase:
            pass
        arm.append(True)
        with pytest.raises(surface.BridgeError, match="owned cancellation"):
            consume(work)
    finally:
        work.close()
    assert checks and prepared["values"].tobytes() == before


def test_sync_and_job_profiles_preserve_distinct_finite_work_budgets(surface):
    prepared = frozen(surface)
    prepared["strokes"][0]["radius"] = 3.
    prepared["limits"] = replace(surface._limits(), candidates=127)
    with pytest.raises(surface.BridgeError) as caught:
        consume(surface.projection_steps(prepared))
    assert caught.value.context == {"limit": 127, "observed": 128}
    prepared["limits"] = surface._limits(allow_large=True)
    (_actual, evidence), _phases = consume(surface.projection_steps(prepared))
    assert evidence["candidate_pixel_tests"] == 128
    assert evidence["maximum_candidate_pixel_tests"] == 33_554_432
    assert evidence["maximum_visibility_triangle_tests"] == 33_554_432
    assert evidence["maximum_stroke_segment_tests"] == 33_554_432
    assert surface._limits().pixels == 1_048_576
    assert surface.brush.size(4096, 4096, maximum_pixels=prepared["limits"].pixels) == (4096, 4096)
    for dimensions in ((4097, 4096), (4096, 4097)):
        with pytest.raises(surface.BridgeError):
            surface.brush.size(*dimensions, maximum_pixels=prepared["limits"].pixels)


@pytest.mark.parametrize("field", ["candidates", "rays", "segments"])
def test_job_profile_still_refuses_each_actual_counter_overrun(surface, field):
    prepared = frozen(surface)
    prepared["strokes"][0]["radius"] = 3.
    prepared["limits"] = replace(surface._limits(allow_large=True), **{field: 1})
    with pytest.raises(surface.BridgeError) as caught:
        consume(surface.projection_steps(prepared))
    assert caught.value.context == {"limit": 1, "observed": 2}


def test_only_job_admission_reads_complete_source_above_sync_cap(live):
    env = live
    image = env.images[0]
    image.size = [1025, 1024]
    image.pixels.values = array("f", [.2, .4, .6, 1.])*(1025*1024)
    digest = env.paint.brush.digest(image.pixels.values)
    with pytest.raises(env.surface.BridgeError, match="1,048,576"):
        env.surface.prepare_surface(env.context, parameters())
    prepared = env.surface.prepare_surface(env.context, parameters(), allow_large=True)
    assert prepared["width"]*prepared["height"] > 1_048_576
    assert env.paint.brush.digest(prepared["values"]) == digest
    assert prepared["limits"].pixels == 16_777_216 and len(env.images) == 1


def test_job_preparation_also_admits_distinct_stencil_above_sync_cap(live):
    env = live
    stencil = Image("Stencil")
    stencil.size = [1025, 1024]
    stencil.pixels.values = array("f", [.25, .5, .75, 1.])*(1025*1024)
    env.images.append(stencil)
    args = parameters(stencil={"image_name": "Stencil", "channel": "G"})
    with pytest.raises(env.surface.BridgeError, match="1,048,576"):
        env.surface.prepare_surface(env.context, args)
    prepared = env.surface.prepare_surface(env.context, args, allow_large=True)
    assert prepared["mask"]["kernel"]["width"] == 1025
    assert len(prepared["mask"]["kernel"]["values"]) == 1025*1024
    assert all(value == .5 for value in prepared["mask"]["kernel"]["values"])
    assert env.surface.workload(prepared)["large_image_requires_job"]


def test_input_validation_releases_source_readback_before_reading_stencil(live, monkeypatch):
    env = live
    env.images.append(Image("Stencil"))
    prepared = env.surface.prepare_surface(env.context, parameters(stencil={"image_name": "Stencil"}))
    read, source_refs = env.paint._read, []

    def observed(context, image, **kwargs):
        if image.name == "Stencil":
            assert source_refs and source_refs[-1]() is None
        result = read(context, image, **kwargs)
        if image.name == "Original":
            source_refs.append(weakref.ref(result[0]))
        return result

    monkeypatch.setattr(env.paint, "_read", observed)
    env.surface.validate_inputs(env.context, prepared)
    assert len(source_refs) == 1 and source_refs[0]() is None


def test_memory_ledger_counts_reentrant_readbacks_and_large_stencil_without_allocating_4k(surface):
    class ChannelLength:
        def __len__(self):
            return 4096*4096

    prepared = {"width": 4096, "height": 4096, "limits": surface._limits(allow_large=True),
                "mask": {"kernel": {"values": ChannelLength()}}}
    evidence = surface.workload(prepared)
    assert evidence["frozen_source_pixel_bytes"] == 256*1024**2
    assert evidence["kernel_pixel_buffers_peak_estimate_bytes"] == 576*1024**2+16384+12
    assert evidence["private_pixel_buffers_peak_estimate_bytes"] == 1088*1024**2+16384+12
    assert "input and output readbacks" in evidence["estimate_excludes"]
