from __future__ import annotations

import copy
import hashlib
import importlib
import math
import struct
import weakref
from array import array
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest


class Pixels:
    def __init__(self, values):
        self.values = array("f", values)
        self.reads = 0

    def __len__(self):
        return len(self.values)

    def foreach_get(self, target):
        self.reads += 1
        target[:] = self.values

    def foreach_set(self, _values):
        pytest.fail("Read-only mask sampling must not write image pixels")


@pytest.fixture
def sampler(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.sculpt_masks")
    uv = NS(
        name="Mask UV",
        data=[
            NS(uv=list(pair))
            for pair in (
                (0.25, 0.25),
                (0.75, 0.25),
                (0.25, 0.75),
                (0.75, 0.75),
                (0.25, 0.75),
                (0.75, 0.75),
            )
        ],
    )
    mesh = NS(
        name="Base",
        users=1,
        library=None,
        override_library=None,
        is_editmode=False,
        vertices=[
            NS(co=list(co))
            for co in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
        ],
        edges=[NS(vertices=pair) for pair in ((0, 1), (1, 2), (2, 0), (2, 3), (3, 0))],
        loops=[NS(vertex_index=index) for index in (0, 1, 2, 0, 2, 3)],
        polygons=[NS(loop_start=0, loop_total=3), NS(loop_start=3, loop_total=3)],
        uv_layers=[uv],
    )
    obj = NS(
        name="Subject",
        type="MESH",
        data=mesh,
        mode="OBJECT",
        library=None,
        override_library=None,
        material_slots=[NS(material=NS(name="Protected"), link="DATA")],
    )
    image = NS(
        name="Mask",
        source="GENERATED",
        type="UV_TEST",
        channels=4,
        has_data=True,
        library=None,
        override_library=None,
        size=(2, 2),
        animation_data=None,
        colorspace_settings=NS(name="sRGB"),
        alpha_mode="PREMUL",
        is_float=True,
        is_dirty=True,
        pixels=Pixels(
            [0.0, 0.25, 0.5, 0.75, 0.25, 0.5, 0.75, 1.0, 0.5, 0.75, 1.0, 0.0, 1.0, 0.0, 0.25, 0.5]
        ),
    )
    scene = NS(name="Scene", frame_current=23, frame_subframe=0.125)
    native = NS(
        mode="OBJECT",
        scene=scene,
        selected_objects=[obj],
        window=None,
        view_layer=NS(name="ViewLayer", objects=NS(active=obj)),
    )
    bpy = NS(data=NS(objects=[obj], images=[image]), context=native)
    grants = {"INSPECT_SCENE": True}
    calls = []

    def require(*permissions):
        calls.append(tuple(p.value for p in permissions))
        if any(not grants.get(p.value, False) for p in permissions):
            raise module.BridgeError("PERMISSION_DENIED", "Denied")

    context = NS(require=require, check_cancelled=None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    return NS(
        module=module,
        obj=obj,
        mesh=mesh,
        uv=uv,
        image=image,
        bpy=bpy,
        context=context,
        grants=grants,
        calls=calls,
        require=require,
    )


def sample(env, **values):
    return env.module.sculpt_mask_sample(
        env.context,
        {
            "object_name": "Subject",
            "uv_layer": "Mask UV",
            "vertex_indices": [3, 0, 1, 2],
            "image_name": "Mask",
            "corner_reduction": "MIN",
            **values,
        },
    )


def native_values(env):
    """Independent declared native endpoint; instrumentation counters excluded."""
    return copy.deepcopy(
        {
            "vertices": [list(v.co) for v in env.mesh.vertices],
            "edges": [list(e.vertices) for e in env.mesh.edges],
            "loops": [loop.vertex_index for loop in env.mesh.loops],
            "faces": [[p.loop_start, p.loop_total] for p in env.mesh.polygons],
            "uv": [list(item.uv) for item in env.uv.data],
            "pixels": list(env.image.pixels.values),
            "colorspace": env.image.colorspace_settings.name,
            "alpha_mode": env.image.alpha_mode,
            "mode": env.bpy.context.mode,
            "selection": [obj.name for obj in env.bpy.context.selected_objects],
            "active": env.bpy.context.view_layer.objects.active.name,
            "frame": [env.bpy.context.scene.frame_current, env.bpy.context.scene.frame_subframe],
            "materials": [[slot.material.name, slot.link] for slot in env.obj.material_slots],
        }
    )


def test_ordered_snapshot_mask_and_complete_native_inputs_remain_unchanged(sampler):
    before = native_values(sampler)
    result = sample(sampler)
    assert result["vertex_indices"] == [3, 0, 1, 2]
    assert result["mask_weights"] == [1.0, 0.0, 0.25, 0.5]
    assert result["corner_counts"] == [1, 2, 1, 2] and result["seam_vertices"] == [0]
    assert result["snapshot_only"] and not result["live_image_binding"]
    assert (
        not result["geometry_modified"]
        and not result["image_modified"]
        and not result["scene_evaluated"]
    )
    evidence = result["input_evidence"]
    assert (
        evidence["image_size"] == [2, 2]
        and evidence["colorspace"] == "sRGB"
        and evidence["alpha_mode"] == "PREMUL"
    )
    for key in (
        "image_pixels_sha256_float32_le",
        "channel_sha256_float32_le",
        "uv_sha256_float32_le",
        "topology_sha256",
        "geometry_sha256_float32_le",
    ):
        assert len(evidence[key]) == 64
    assert (
        evidence["complete_pixels_and_inputs_unchanged"] and evidence["image_identity_session_only"]
    )
    assert native_values(sampler) == before and sampler.image.pixels.reads == 2
    assert all(call == ("INSPECT_SCENE",) for call in sampler.calls)


@pytest.mark.parametrize(
    "channel,ends", [("R", (0.0, 1.0)), ("G", (0.25, 0.0)), ("B", (0.5, 0.25)), ("A", (0.75, 0.5))]
)
@pytest.mark.parametrize("invert", [False, True])
@pytest.mark.parametrize("reduction", ["MIN", "MAX", "MEAN"])
def test_all_raw_channels_and_inversion_before_explicit_seam_reduction(
    sampler, channel, ends, invert, reduction
):
    expected = [1 - v if invert else v for v in ends]
    expected = (
        min(expected)
        if reduction == "MIN"
        else max(expected)
        if reduction == "MAX"
        else sum(expected) / 2
    )
    result = sample(
        sampler, vertex_indices=[0], channel=channel, invert=invert, corner_reduction=reduction
    )
    assert result["mask_weights"] == [expected]
    assert (
        result["sampling"]["invert_before_corner_reduction"]
        and not result["sampling"]["color_alpha_transform"]
    )


@pytest.mark.parametrize(
    "uv,expected",
    [
        ((0.0, 0.0), 0.0),
        ((1.0, 0.0), 0.25),
        ((0.0, 1.0), 0.5),
        ((1.0, 1.0), 1.0),
        ((0.5, 0.5), 0.4375),
    ],
)
def test_uv_pixel_centres_interpolate_and_image_edges_clamp(sampler, uv, expected):
    sampler.uv.data[0].uv = sampler.uv.data[3].uv = uv
    assert sample(sampler, vertex_indices=[0])["mask_weights"] == [expected]


def test_nonsquare_three_by_two_image_and_effective_float32_uv(sampler):
    sampler.image.size = (3, 2)
    sampler.image.pixels = Pixels(
        [
            component
            for value in (0.0, 0.25, 0.5, 0.625, 0.75, 1.0)
            for component in (value, 0.0, 0.0, 1.0)
        ]
    )
    sampler.uv.data[0].uv = sampler.uv.data[3].uv = (1 / 3, 0.5)
    effective = struct.unpack("<f", struct.pack("<f", 1 / 3))[0]
    result = sample(sampler, vertex_indices=[0])
    a = effective * 3 - 0.5
    expected = ((0.0 * (1 - a) + 0.25 * a) + (0.625 * (1 - a) + 0.75 * a)) / 2
    assert result["mask_weights"] == [expected] and expected != 0.40625


def test_unselected_channels_are_never_color_converted_or_normalized(sampler):
    sampler.image.pixels.values[1] = 4.0
    sampler.image.pixels.values[2] = math.nan
    result = sample(sampler, vertex_indices=[0])
    assert result["mask_weights"] == [0.0] and sampler.image.pixels.values[1] == 4.0
    assert math.isnan(sampler.image.pixels.values[2])


@pytest.mark.parametrize(
    "channel,expected", [("R", 0.34375), ("G", 0.640625), ("B", 0.71875), ("A", 0.515625)]
)
@pytest.mark.parametrize("invert", [False, True])
def test_asymmetric_off_centre_two_axis_bilinear_has_independent_channel_oracle(
    sampler, channel, expected, invert
):
    sampler.image.pixels = Pixels(
        [0.0, 0.25, 0.5, 1.0, 1.0, 0.5, 0.25, 0.75, 0.25, 1.0, 0.75, 0.5, 0.75, 0.0, 1.0, 0.0]
    )
    sampler.uv.data[0].uv = sampler.uv.data[3].uv = [0.375, 0.625]
    result = sample(sampler, vertex_indices=[0], channel=channel, invert=invert)
    assert result["mask_weights"] == [1.0 - expected if invert else expected]


@pytest.mark.parametrize("size,uv", [((1, 3), (0.623, 0.375)), ((3, 1), (0.375, 0.623))])
def test_single_axis_images_keep_bilinear_sampling_on_the_other_axis(sampler, size, uv):
    sampler.image.size = size
    sampler.image.pixels = Pixels([0.0, 0.0, 0.0, 1.0, 0.25, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0])
    sampler.uv.data[0].uv = sampler.uv.data[3].uv = uv
    assert sample(sampler, vertex_indices=[0])["mask_weights"] == [0.15625]


@pytest.mark.parametrize("invert,expected", [(False, 1 / 3), (True, 2 / 3)])
def test_mean_keeps_repeated_uv_corner_multiplicity(sampler, invert, expected):
    sampler.uv.data[3].uv = [0.25, 0.25]
    sampler.mesh.loops.extend(NS(vertex_index=index) for index in (0, 1, 2))
    sampler.mesh.polygons.append(NS(loop_start=6, loop_total=3))
    sampler.uv.data.extend(NS(uv=list(uv)) for uv in ((0.75, 0.25), (0.75, 0.25), (0.25, 0.75)))
    result = sample(
        sampler, vertex_indices=[0], channel="G", invert=invert, corner_reduction="MEAN"
    )
    assert result["mask_weights"] == [expected]
    assert result["corner_counts"] == [3] and result["seam_vertices"] == [0]


@pytest.mark.parametrize("field", ["object_name", "uv_layer", "image_name"])
@pytest.mark.parametrize("name", ["n" * 63, "é" * 31 + "n"])
def test_names_at_exact_63_utf8_byte_boundary_match_typed_schema(sampler, field, name):
    owner = {"object_name": sampler.obj, "uv_layer": sampler.uv, "image_name": sampler.image}[field]
    owner.name = name
    assert sample(sampler, **{field: name})[field if field != "object_name" else "object"] == name


@pytest.mark.parametrize("field", ["object_name", "uv_layer", "image_name"])
@pytest.mark.parametrize("name", ["n" * 64, "é" * 32])
def test_names_exceeding_63_utf8_bytes_fail_before_providers(sampler, field, name):
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler, **{field: name})
    assert caught.value.code == "INVALID_ARGUMENT" and not sampler.calls


def test_single_pixel_and_full_1024_vertex_request_boundary(sampler):
    sampler.image.size = (1, 1)
    sampler.image.pixels = Pixels([0.25, 0.5, 0.75, 1.0])
    sampler.mesh.vertices = [NS(co=[0.0, 0.0, 0.0]) for _ in range(1024)]
    sampler.mesh.edges = []
    sampler.mesh.loops = [NS(vertex_index=index) for index in range(1024)]
    sampler.mesh.polygons = [NS(loop_start=0, loop_total=1024)]
    sampler.uv.data = [NS(uv=[0.5, 0.5]) for _ in range(1024)]
    result = sample(sampler, vertex_indices=list(range(1024)))
    assert result["mask_weights"] == [0.25] * 1024 and result["corner_counts"] == [1] * 1024


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_name", None),
        ("object_name", ""),
        ("object_name", " "),
        ("object_name", 1),
        ("object_name", "x" * 257),
        ("uv_layer", ""),
        ("uv_layer", "bad\nname"),
        ("image_name", None),
        ("image_name", "\ud800"),
        ("vertex_indices", None),
        ("vertex_indices", []),
        ("vertex_indices", [0] * 1025),
        ("vertex_indices", [0, 0]),
        ("vertex_indices", [True]),
        ("vertex_indices", [0.0]),
        ("vertex_indices", ["0"]),
        ("vertex_indices", [-1]),
        ("vertex_indices", [100_000]),
        ("vertex_indices", (0,)),
        ("vertex_indices", [10**1000]),
        ("channel", None),
        ("channel", []),
        ("channel", "r"),
        ("channel", "LUMINANCE"),
        ("corner_reduction", None),
        ("corner_reduction", []),
        ("corner_reduction", "AUTO"),
        ("invert", 1),
        ("invert", "false"),
        ("unexpected", True),
    ],
)
def test_malformed_request_precedes_live_provider_or_blender_lookup(
    sampler, monkeypatch, field, value
):
    monkeypatch.setattr(
        sampler.module,
        "require_blender",
        lambda: pytest.fail("Malformed requests precede Blender access"),
    )
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler, **{field: value})
    assert caught.value.code == "INVALID_ARGUMENT" and not sampler.calls


def test_explicit_corner_reduction_cannot_be_omitted(sampler):
    with pytest.raises(sampler.module.BridgeError) as caught:
        sampler.module.sculpt_mask_sample(
            sampler.context,
            {
                "object_name": "Subject",
                "uv_layer": "Mask UV",
                "image_name": "Mask",
                "vertex_indices": [0],
            },
        )
    assert caught.value.code == "INVALID_ARGUMENT" and not sampler.calls


@pytest.mark.parametrize(
    "change",
    [
        "missing_object",
        "ambiguous_object",
        "not_mesh",
        "wrong_mode",
        "object_mode",
        "edit_mesh",
        "missing_uv",
        "ambiguous_uv",
        "vertex_outside",
        "missing_corner",
        "uv_length",
        "uv_nan",
        "uv_outside",
        "bad_edge",
        "bad_loop",
        "bad_face",
        "uncovered_loops",
    ],
)
def test_unsupported_or_inconsistent_mesh_scope_precedes_pixel_read(sampler, change):
    if change == "missing_object":
        sampler.bpy.data.objects.clear()
    elif change == "ambiguous_object":
        sampler.bpy.data.objects.append(copy.copy(sampler.obj))
    elif change == "not_mesh":
        sampler.obj.type = "CURVE"
    elif change == "wrong_mode":
        sampler.bpy.context.mode = "EDIT_MESH"
    elif change == "object_mode":
        sampler.obj.mode = "SCULPT"
    elif change == "edit_mesh":
        sampler.mesh.is_editmode = True
    elif change == "missing_uv":
        sampler.mesh.uv_layers.clear()
    elif change == "ambiguous_uv":
        sampler.mesh.uv_layers.append(copy.copy(sampler.uv))
    elif change == "vertex_outside":
        sampler.mesh.vertices.pop()
    elif change == "missing_corner":
        sampler.mesh.vertices.append(NS(co=[2.0, 0.0, 0.0]))
    elif change == "uv_length":
        sampler.uv.data.pop()
    elif change == "uv_nan":
        sampler.uv.data[0].uv = [math.nan, 0.0]
    elif change == "uv_outside":
        sampler.uv.data[0].uv = [1.01, 0.0]
    elif change == "bad_edge":
        sampler.mesh.edges[0].vertices = (0, 100)
    elif change == "bad_loop":
        sampler.mesh.loops[0].vertex_index = 100
    elif change == "bad_face":
        sampler.mesh.polygons[0].loop_start = 1
    else:
        sampler.mesh.polygons.pop()
    with pytest.raises(sampler.module.BridgeError):
        sample(sampler, vertex_indices=[4] if change == "missing_corner" else [3, 0, 1, 2])
    assert sampler.image.pixels.reads == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "FILE"),
        ("source", "TILED"),
        ("type", "RENDER_RESULT"),
        ("channels", 3),
        ("has_data", False),
        ("library", object()),
        ("override_library", object()),
        ("size", (4096, 4097)),
        ("size", (0, 1)),
        ("size", (1.0, 1)),
        ("size", (4097, 1)),
        ("animation_data", NS(action=object(), drivers=[], nla_tracks=[])),
        ("animation_data", NS(action=None, drivers=[object()], nla_tracks=[])),
        ("animation_data", NS(action=None, drivers=[], nla_tracks=[object()])),
    ],
)
def test_unsupported_image_profile_fails_without_buffer_read(sampler, field, value):
    setattr(sampler.image, field, value)
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == "NOT_IMPLEMENTED" and sampler.image.pixels.reads == 0


@pytest.mark.parametrize("change", ["missing", "ambiguous", "buffer_length"])
def test_exact_image_and_complete_buffer_required(sampler, change):
    if change == "missing":
        sampler.bpy.data.images.clear()
    elif change == "ambiguous":
        sampler.bpy.data.images.append(copy.copy(sampler.image))
    else:
        sampler.image.pixels.values.pop()
    with pytest.raises(sampler.module.BridgeError):
        sample(sampler)
    assert sampler.image.pixels.reads == 0


@pytest.mark.parametrize("bad", [-0.1, 1.1, math.inf, -math.inf, math.nan])
def test_entire_chosen_channel_is_validated_even_outside_sampled_footprint(sampler, bad):
    sampler.image.pixels.values[12] = bad
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler, vertex_indices=[1])
    assert caught.value.code == "NOT_IMPLEMENTED" and sampler.image.pixels.reads == 1


def final_provider(env, callback):
    fired = []

    def require(*permissions):
        env.require(*permissions)
        if env.image.pixels.reads and not fired:
            fired.append(True)
            callback()

    env.context.require = require
    return fired


@pytest.mark.parametrize(
    "change",
    [
        "pixels",
        "other_channel",
        "negative_zero_pixel",
        "uv",
        "negative_zero_uv",
        "coordinates",
        "negative_zero_coordinate",
        "topology",
        "roles",
        "image_identity",
        "object_identity",
        "frame",
        "mode",
        "image_unloaded",
        "request",
    ],
)
def test_final_provider_changes_are_preserved_and_snapshot_refused(sampler, change):
    request = {
        "object_name": "Subject",
        "uv_layer": "Mask UV",
        "vertex_indices": [0],
        "image_name": "Mask",
        "corner_reduction": "MIN",
    }
    provider_state = []

    def alter():
        if change == "pixels":
            sampler.image.pixels.values[0] = 0.875
        elif change == "other_channel":
            sampler.image.pixels.values[1] = 0.875
        elif change == "negative_zero_pixel":
            sampler.image.pixels.values[0] = -0.0
        elif change == "uv":
            sampler.uv.data[0].uv = [0.5, 0.5]
        elif change == "negative_zero_uv":
            sampler.uv.data[0].uv = [-0.0, 0.25]
        elif change == "coordinates":
            sampler.mesh.vertices[0].co[2] = 2.0
        elif change == "negative_zero_coordinate":
            sampler.mesh.vertices[0].co[0] = -0.0
        elif change == "topology":
            sampler.mesh.loops[0].vertex_index = 1
        elif change == "roles":
            sampler.image.alpha_mode = "STRAIGHT"
        elif change == "image_identity":
            sampler.bpy.data.images[0] = copy.copy(sampler.image)
        elif change == "object_identity":
            sampler.bpy.data.objects[0] = copy.copy(sampler.obj)
        elif change == "frame":
            sampler.bpy.context.scene.frame_current = 50
        elif change == "mode":
            sampler.obj.mode = "SCULPT"
        elif change == "image_unloaded":
            sampler.image.has_data = False
        else:
            request["channel"] = "B"
        provider_state.append(native_values(sampler))

    fired = final_provider(sampler, alter)
    with pytest.raises(sampler.module.BridgeError) as caught:
        sampler.module.sculpt_mask_sample(sampler.context, request)
    assert caught.value.code == "OPERATION_FAILED" and caught.value.context["stale_mask_inputs"]
    assert fired == [True] and native_values(sampler) == provider_state[0]


def test_inspection_denial_precedes_native_input_reads(sampler, monkeypatch):
    sampler.grants["INSPECT_SCENE"] = False
    monkeypatch.setattr(
        sampler.module,
        "require_blender",
        lambda: pytest.fail("Denied inspection must not touch Blender"),
    )
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == "PERMISSION_DENIED" and not sampler.image.pixels.reads


def test_final_permission_loss_preserves_inputs_and_primary_denial(sampler):
    before = native_values(sampler)
    final_provider(sampler, lambda: sampler.grants.update(INSPECT_SCENE=False))
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == "PERMISSION_DENIED" and native_values(sampler) == before


def test_live_cancellation_callback_before_final_frozen_read_preserves_its_uv_edit(sampler):
    fired = []

    def change_uv():
        if sampler.image.pixels.reads and not fired:
            sampler.uv.data[0].uv = [0.5, 0.5]
            fired.append(True)

    sampler.context.check_cancelled = change_uv
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert (
        caught.value.code == "OPERATION_FAILED"
        and sampler.uv.data[0].uv == [0.5, 0.5]
        and fired == [True]
    )


def test_named_sampling_never_reads_selection_or_view_layer_context_getters(sampler):
    class NoSelectionContext(NS):
        def __getattribute__(self, name):
            if name in {"selected_objects", "view_layer"}:
                pytest.fail("Named UV sampling must not normalize or inspect selection context")
            return super().__getattribute__(name)

    sampler.bpy.context = NoSelectionContext(**vars(sampler.bpy.context))
    assert sample(sampler)["mask_weights"] == [1.0, 0.0, 0.25, 0.5]


def test_selection_is_not_a_sampling_input_and_provider_selection_changes_are_retained(sampler):
    fired = final_provider(sampler, lambda: setattr(sampler.bpy.context, "selected_objects", []))
    assert sample(sampler)["mask_weights"] == [1.0, 0.0, 0.25, 0.5]
    assert fired == [True] and sampler.bpy.context.selected_objects == []


def test_timeout_during_final_pure_check_is_not_replaced_with_stale_input_error(sampler):
    expired = []

    def check():
        if expired:
            raise sampler.module.BridgeError("TIMEOUT", "Owner disconnected")

    sampler.context.request_lifecycle = NS(check=check)
    final_provider(sampler, lambda: expired.append(True))
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == "TIMEOUT"


def test_mesh_drift_during_final_pixel_read_cannot_return_a_stale_mask(sampler):
    original = sampler.image.pixels.foreach_get

    def read(target):
        original(target)
        if sampler.image.pixels.reads == 2:
            sampler.uv.data[0].uv = [0.5, 0.5]

    sampler.image.pixels.foreach_get = read
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == "OPERATION_FAILED"
    assert sampler.uv.data[0].uv == [0.5, 0.5]


@pytest.mark.parametrize("field", ["library", "override_library"])
def test_shared_or_linked_base_mesh_can_be_read_without_edit_authority(sampler, field):
    sampler.mesh.users = 8
    setattr(sampler.mesh, field, NS(name="Library"))
    setattr(sampler.obj, field, NS(name="Library"))
    assert sample(sampler)["mask_weights"] == [1.0, 0.0, 0.25, 0.5]


def registered(sampler):
    module = importlib.import_module(
        sampler.module.__package__.rsplit(".", 1)[0] + ".tool_registry"
    )
    registry = module.ToolRegistry(enabled_toolsets=("mesh",))
    sampler.module.register_tools(registry)
    sampler.context.registry = registry
    return registry


def test_registered_read_only_identity_metadata_and_pause_stop_allow_inspection(sampler):
    registry = registered(sampler)
    spec = registry.get("mesh.sculpt_mask_sample")
    assert not spec.modifies and spec.toolset == "mesh"
    assert {p.value for p in spec.permissions} == {"INSPECT_SCENE"}
    sampler.context.state = NS(snapshot=lambda: {"paused": True, "emergency_stopped": True})
    assert sample(sampler)["mask_weights"] == [1.0, 0.0, 0.25, 0.5]


@pytest.mark.parametrize(
    "change,code", [("disable", "TOOLSET_DISABLED"), ("replace", "NOT_IMPLEMENTED")]
)
def test_final_toolset_or_exact_spec_loss_is_checked_without_new_provider_calls(
    sampler, change, code
):
    registry = registered(sampler)
    spec = registry.get("mesh.sculpt_mask_sample")

    def alter():
        if change == "disable":
            registry.disable_toolset("mesh")
        else:
            registry._tools[spec.name] = replace(spec, description="Changed")

    fired = final_provider(sampler, alter)
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == code and fired == [True]


@pytest.mark.parametrize("size", [(4096, 4096), (4096, 257), (1, 4096)])
def test_image_policy_admits_exact_4k_without_allocating_or_reading_native_pixels(sampler, size):
    class LengthOnlyPixels:
        def __len__(self):
            return size[0] * size[1] * 4

        def foreach_get(self, _target):
            pytest.fail("This policy test must not claim an actual 4K read")

    sampler.image.size = size
    sampler.image.pixels = LengthOnlyPixels()
    image, metadata = sampler.module._image(sampler.bpy, "Mask")
    assert image is sampler.image and metadata["size"] == size
    assert sampler.module.MAX_PIXELS == 16_777_216


def chunk_image(sampler):
    """Small multi-chunk input; real 4K allocation belongs to native qualification."""
    sampler.image.size = (128, 65)
    sampler.image.pixels = Pixels([0.25, 0.5, 0.75, 1.0] * (128 * 65))
    for item in sampler.uv.data:
        item.uv = [0.5 / 128, 0.5 / 65]


def test_multichunk_read_has_complete_independent_rgba_and_raw_channel_hashes(sampler):
    chunk_image(sampler)
    sampler.image.pixels.values[-2] = -0.0
    raw = sampler.image.pixels.values
    rgba_bytes = struct.pack("<" + "f" * len(raw), *raw)
    channel = [raw[index] for index in range(2, len(raw), 4)]
    channel_bytes = struct.pack("<" + "f" * len(channel), *channel)
    before = native_values(sampler)
    result = sample(sampler, channel="B")
    assert result["mask_weights"] == [0.75] * 4
    assert result["input_evidence"]["image_pixels_sha256_float32_le"] == hashlib.sha256(rgba_bytes).hexdigest()
    assert result["input_evidence"]["channel_sha256_float32_le"] == hashlib.sha256(channel_bytes).hexdigest()
    assert native_values(sampler) == before and sampler.image.pixels.reads == 2


@pytest.mark.parametrize("bad", [-0.01, 1.01, math.nan, math.inf])
def test_channel_validation_reaches_the_unsampled_tail_after_multiple_copy_chunks(sampler, bad):
    chunk_image(sampler)
    sampler.image.pixels.values[-4] = bad
    before = sampler.image.pixels.values.tobytes()
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler, vertex_indices=[1])
    assert caught.value.code == "NOT_IMPLEMENTED" and sampler.image.pixels.reads == 1
    assert sampler.image.pixels.values.tobytes() == before


@pytest.mark.parametrize("loss", ["disconnect", "deadline", "disable", "replace"])
def test_chunk_copy_uses_retained_pure_lifecycle_without_permission_callbacks(sampler, monkeypatch, loss):
    chunk_image(sampler)
    registry = registered(sampler)
    spec = registry.get("mesh.sculpt_mask_sample")
    lifecycle = importlib.import_module(sampler.module.__package__.rsplit(".", 1)[0] + ".request_lifecycle")
    lifetime = lifecycle.RequestLifetime(connection=lifecycle.ConnectionLifetime())
    sampler.context.request_lifecycle = lifetime
    original = sampler.module.image_masks.channel_copy
    checks = []

    def copy_with_loss(rgba, index, *, check):
        def checked():
            checks.append(True)
            if len(checks) == 4:  # After the first bounded chunk, not a live provider.
                if loss == "disconnect":
                    lifetime.connection.disconnected.set()
                elif loss == "deadline":
                    lifetime.deadline = -math.inf
                elif loss == "disable":
                    registry.disable_toolset("mesh")
                else:
                    registry._tools[spec.name] = replace(spec, description="Replaced")
            check()
        return original(rgba, index, check=checked)

    monkeypatch.setattr(sampler.module.image_masks, "channel_copy", copy_with_loss)
    before = native_values(sampler)
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == {"disconnect": "TIMEOUT", "deadline": "TIMEOUT", "disable": "TOOLSET_DISABLED", "replace": "NOT_IMPLEMENTED"}[loss]
    assert len(checks) == 4 and len(sampler.calls) == 2
    assert sampler.image.pixels.reads == 1 and native_values(sampler) == before


def test_initial_rgba_is_released_before_independent_final_readback(sampler, monkeypatch):
    chunk_image(sampler)
    original = sampler.module._pixels
    first = []

    def read(*args):
        if first:
            assert first[0]() is None
        values = original(*args)
        if not first:
            first.append(weakref.ref(values))
        return values

    monkeypatch.setattr(sampler.module, "_pixels", read)
    assert sample(sampler)["mask_weights"] == [0.25] * 4
    assert sampler.image.pixels.reads == 2


def test_channel_allocation_failure_never_mutates_native_inputs(sampler, monkeypatch):
    before = native_values(sampler)

    def fail(*_args, **_kwargs):
        raise MemoryError("Controlled private channel allocation failure")

    monkeypatch.setattr(sampler.module.image_masks, "channel_copy", fail)
    with pytest.raises(MemoryError):
        sample(sampler)
    assert sampler.image.pixels.reads == 1 and native_values(sampler) == before


@pytest.mark.parametrize("loss,code", [("disable", "TOOLSET_DISABLED"), ("replace", "NOT_IMPLEMENTED")])
def test_selected_channel_validation_retains_spec_before_hash_or_new_provider(sampler, monkeypatch, loss, code):
    chunk_image(sampler)
    registry = registered(sampler)
    spec = registry.get("mesh.sculpt_mask_sample")
    copy_channel = sampler.module.image_masks.channel_copy
    digest = sampler.module.pixel_brush.digest
    validation = []

    def copy_then_revoke(*args, **kwargs):
        channel = copy_channel(*args, **kwargs)
        validation.append(True)
        if loss == "disable":
            registry.disable_toolset("mesh")
        else:
            registry._tools[spec.name] = replace(spec, description="Replaced before validation")
        return channel

    def digest_before_loss(values):
        assert not validation, "Validation must observe revoked identity before hashing the channel"
        return digest(values)

    monkeypatch.setattr(sampler.module.image_masks, "channel_copy", copy_then_revoke)
    monkeypatch.setattr(sampler.module.pixel_brush, "digest", digest_before_loss)
    before = native_values(sampler)
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == code and validation == [True]
    assert len(sampler.calls) == 2 and sampler.image.pixels.reads == 1
    assert native_values(sampler) == before


@pytest.mark.parametrize("failed_read", [1, 2])
def test_failed_complete_pixel_read_never_changes_native_inputs(sampler, monkeypatch, failed_read):
    original = sampler.image.pixels.foreach_get

    def read(target):
        if sampler.image.pixels.reads + 1 == failed_read:
            sampler.image.pixels.reads += 1
            raise OSError("Controlled native-read failure")
        original(target)

    monkeypatch.setattr(sampler.image.pixels, "foreach_get", read)
    before = native_values(sampler)
    with pytest.raises(sampler.module.BridgeError) as caught:
        sample(sampler)
    assert caught.value.code == "OPERATION_FAILED"
    assert sampler.image.pixels.reads == failed_read and native_values(sampler) == before
