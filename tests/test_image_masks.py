from __future__ import annotations

# Shared pytest fixtures are deliberately imported under their public names.
# ruff: noqa: F811
import asyncio
import math
from array import array
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError
from test_image_paint import Image, kernel, paint_tools, stroke  # noqa: F401
from test_paint_jobs import finish, jobs  # noqa: F401

from mcp_server.tools.image_paint import BrushStroke, ImageMask, ImagePaintTools


def mask_values(values, width, height, invert=False):
    return {"values": array("f", values), "width": width, "height": height, "invert": invert}


@pytest.mark.parametrize("invert", [False, True])
def test_bilinear_uv_pixel_centres_are_edge_clamped_without_color_transform(kernel, invert):
    source = array("f", [0., 0., 0., 1.]) * 8
    prepared, _ = kernel.prepare([stroke(radius_pixels=256., color=[1., 1., 1., 1.])], 4, 2, "COLOR")
    mask = mask_values([0., 1.], 2, 1, invert)
    output, info = kernel.paint(source, 4, 2, prepared, "COLOR", mask=mask)
    expected = [0., .25, .75, 1.]
    if invert:
        expected = [1-v for v in expected]
    assert list(output[::4]) == pytest.approx(expected * 2)
    assert info["painted_pixels"] == 6 and info["mask_channel_bytes"] == 8
    assert mask["values"] == array("f", [0., 1.]) and source[0] == 0


def test_two_dimensional_bilinear_interpolation_and_equal_size_exact_sampling(kernel):
    sample = __import__(kernel.__package__ + ".pixel_mask", fromlist=["sample"]).sample
    mask = mask_values([0., .25, .5, 1.], 2, 2)
    assert sample(mask, 1, 1, 3, 3) == .4375
    assert [sample(mask, x, y, 2, 2) for y in range(2) for x in range(2)] == list(mask["values"])


@pytest.mark.parametrize("role,blend,expected", [
    ("COLOR", "MIX", [.4, .3, .45, 1.]),
    ("COLOR", "ERASE_ALPHA", [.2, .4, .6, .75]),
    ("DATA", "MIX", [.4, .3, .45, 1.]),
])
def test_mask_weights_max_coverage_before_color_alpha_data_mix_or_erase(kernel, role, blend, expected):
    source = array("f", [.2, .4, .6, 1.])
    repeated = stroke(points=[[.5, .5]]*3, color=[1., 0., 0., 1.], opacity=.5, blend=blend)
    prepared, _ = kernel.prepare([repeated], 1, 1, role)
    output, _ = kernel.paint(source, 1, 1, prepared, role, mask=mask_values([.5], 1, 1))
    assert list(output) == pytest.approx(expected)


def test_zero_mask_still_converts_entire_srgb_source_but_counts_no_brush_changes(kernel):
    source = array("f", [.5, .25, .125, 1.]) * 4
    prepared, _ = kernel.prepare([stroke()], 2, 2, "COLOR")
    output, info = kernel.paint(source, 2, 2, prepared, "COLOR", srgb=True, mask=mask_values([0.], 1, 1))
    assert output[0] == pytest.approx(.21404114) and info["painted_pixels"] == 0
    assert info["source_srgb_converted_to_linear"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -.1, 1.1])
def test_complete_mask_channel_is_validated_even_outside_brush_footprint(kernel, bad):
    prepared, _ = kernel.prepare([stroke(points=[[0., 0.]], radius_pixels=.5)], 4, 4, "DATA")
    values = [1.] * 16
    values[-1] = bad
    with pytest.raises(Exception, match="selected raw mask channel"):
        kernel.paint(array("f", [0., 0., 0., 1.])*16, 4, 4, prepared, "DATA", mask=mask_values(values, 4, 4))


def test_mask_validation_yields_and_can_cancel_before_normalization(kernel):
    prepared, _ = kernel.prepare([stroke()], 1, 1, "DATA")
    work = kernel.paint_steps(array("f", [0., 0., 0., 1.]), 1, 1, prepared, "DATA", mask=mask_values([1.]*1024, 32, 32))
    assert next(work) == {"phase": "validating_mask", "completed": 0, "total": 1024}
    assert next(work)["completed"] == 256
    work.close()


@pytest.mark.parametrize("raw", [True, [], {}, {"image_name": ""}, {"image_name": "Original", "channel": "LUMINANCE"},
    {"image_name": "Original", "invert": 1}, {"image_name": "Original", "channel": []},
    {"image_name": "Original", "extra": True}])
def test_invalid_mask_specs_reject_before_read_or_allocation(paint_tools, monkeypatch, raw):
    module, context, images, _, _ = paint_tools
    monkeypatch.setattr(module, "_read", lambda *_a, **_k: pytest.fail("mask syntax must precede reads"))
    with pytest.raises(module.BridgeError):
        module.paint_version(context, {"image_name": "Original", "new_name": "Output", "strokes": [stroke()], "mask": raw})
    assert len(images) == 1


def add_mask(env):
    image = Image("Mask", 2, 1)
    image.colorspace_settings.name = "sRGB"
    image.alpha_mode = "PREMUL"  # Raw channel, no unpremultiply or color transform.
    image.is_float = False
    image.pixels.values = array("f", [.5, 4., math.nan, 1., .25, 4., math.nan, 1.])
    env.append(image)
    return image


def test_raw_channel_mask_preserves_both_inputs_with_no_inspection_grant(paint_tools):
    module, context, images, _, grants = paint_tools
    mask = add_mask(images)
    grants["INSPECT_SCENE"] = grants["ACCESS_EXTERNAL_FILES"] = False
    before = module.brush.digest(mask.pixels.values)
    result = module.paint_version(context, {"image_name": "Original", "new_name": "Output", "strokes": [stroke()],
        "mask": {"image_name": "Mask", "channel": "R"}})
    assert result["mask"]["pixels_unchanged"] and result["source_pixels_unchanged"]
    assert result["mask"]["colorspace"] == "sRGB" and result["mask"]["alpha_mode"] == "PREMUL"
    assert result["mask"]["pixels_sha256_float32_le"] == before == module.brush.digest(mask.pixels.values)
    assert result["mask_channel_bytes"] == 8 and not result["bound_to_nodes"]
    assert result["private_pixel_buffers_peak_estimate_bytes"] >= 3*4*4*16 + 5*8


def test_source_can_be_its_own_mask_without_a_second_initial_capture(paint_tools, monkeypatch):
    module, context, images, _, _ = paint_tools
    read, reads = module._read, []
    def observed(context, image, **kwargs):
        reads.append(image.name)
        return read(context, image, **kwargs)
    monkeypatch.setattr(module, "_read", observed)
    result = module.paint_version(context, {"image_name": "Original", "new_name": "Output", "strokes": [stroke()],
        "mask": {"image_name": "Original", "channel": "A"}})
    assert result["mask"]["image_name"] == "Original" and reads.count("Original") == 4
    assert images[0].pixels.values == array("f", [.2, .4, .6, 1.])*16


@pytest.mark.parametrize("change", ["pixels", "metadata", "identity", "missing", "animation", "ambiguous"])
def test_job_revalidates_mask_before_checkpoint_and_publication(jobs, change):
    env = jobs
    mask = add_mask(env.images)
    env.manager.start(env.context(), {"image_name": "Original", "new_name": "Output", "strokes": [stroke()],
        "mask": {"image_name": "Mask"}}, 60.)
    if change == "pixels":
        mask.pixels.values[1] = 3.  # Even a non-selected channel change invalidates the frozen source.
    elif change == "metadata":
        mask.alpha_mode = "STRAIGHT"
    elif change == "identity":
        env.images[-1] = Image("Mask", 2, 1)
    elif change == "missing":
        env.images.remove(mask)
    elif change == "ambiguous":
        env.images.append(Image("Mask", 2, 1))
    else:
        mask.animation_data = NS(action=object(), drivers=[], nla_tracks=[])
    result = finish(env)
    assert result["state"] == "FAILED" and not result["execution_started"] and not env.marks
    assert env.images.get("Output") is None and env.manager.history[0].prepared == {}


def test_mask_change_during_checkpoint_is_rechecked_and_boundary_finalized(jobs):
    env = jobs
    mask = add_mask(env.images)
    env.checkpoints.before_modification = lambda _label: setattr(mask, "alpha_mode", "STRAIGHT") or True
    env.manager.start(env.context(), {"image_name": "Original", "new_name": "Output", "strokes": [stroke()],
        "mask": {"image_name": "Mask"}}, 60.)
    result = finish(env)
    assert result["state"] == "FAILED" and result["undo_boundary_finalized"] and not result["execution_started"]
    assert env.images.get("Output") is None


def test_mask_changed_after_publication_retains_output_with_truthful_recovery_evidence(paint_tools, monkeypatch):
    module, context, images, _, grants = paint_tools
    mask = add_mask(images)
    grants["DELETE_OBJECTS"] = False
    original = module._new
    def changed(*args):
        output = original(*args)
        mask.pixels.values[0] = .8
        return output
    monkeypatch.setattr(module, "_new", changed)
    with pytest.raises(module.BridgeError) as error:
        module.paint_version(context, {"image_name": "Original", "new_name": "Output", "strokes": [stroke()],
            "mask": {"image_name": "Mask"}})
    assert error.value.context["possible_mutation"] and error.value.context["stale_mask"]
    assert images.get("Output") is not None


def test_canvas_metadata_change_after_publication_is_not_false_input_preservation(paint_tools, monkeypatch):
    module, context, images, _, _ = paint_tools
    add_mask(images)
    original = module._new
    def changed(*args):
        result = original(*args)
        images[0].alpha_mode = "PREMUL"
        return result
    monkeypatch.setattr(module, "_new", changed)
    with pytest.raises(module.BridgeError) as error:
        module.paint_version(context, {"image_name": "Original", "new_name": "Output", "strokes": [stroke()], "mask": {"image_name": "Mask"}})
    assert error.value.context["stale_source"] and not error.value.context["input_preservation_verified"]
    assert error.value.context["possible_mutation"] and images.get("Output") is not None


def test_file_mask_requires_live_external_grant_even_when_canvas_is_generated(jobs, monkeypatch):
    env = jobs
    mask = add_mask(env.images)
    mask.source, mask.type = "FILE", "IMAGE"
    monkeypatch.setattr(env.paint.images, "preflight_file", lambda *_args: ("approved", {"size": 1}))
    env.manager.start(env.context(), {"image_name": "Original", "new_name": "Output", "strokes": [stroke()],
        "mask": {"image_name": "Mask"}}, 60.)
    env.grants["ACCESS_EXTERNAL_FILES"] = False
    result = finish(env)
    assert result["state"] == "FAILED" and result["error"]["code"] == "PERMISSION_DENIED"
    assert not result["execution_started"] and not env.marks and env.images.get("Output") is None


@pytest.mark.parametrize("fields", [{"image_name": ""}, {"image_name": "a"*64}, {"image_name": " "},
    {"image_name": "\u00e9"*32}, {"image_name": "bad\nname"}, {"image_name": "Mask", "invert": 1},
    {"image_name": "Mask", "channel": "r"}, {"image_name": "Mask", "unknown": True}])
def test_mcp_mask_is_strict_and_bounded(fields):
    with pytest.raises(ValidationError):
        ImageMask.model_validate(fields)


def test_mcp_wrappers_forward_typed_optional_mask_only():
    class Registry:
        async def call(self, method, params):
            return {"method": method, "params": params}
    async def run():
        tools = ImagePaintTools()
        tools.registry = Registry()
        mask = ImageMask(image_name="Mask", channel="B", invert=True)
        stroke = BrushStroke(points=[[.5, .5]], radius_pixels=2., color=[1., 0., 0., 1.])
        assert (await tools.image_paint_version("Source", "Output", [stroke], mask))["params"]["mask"] == mask.model_dump()
        assert (await tools.image_paint_job_start("Source", "Output", [stroke], mask=mask))["params"]["mask"] == mask.model_dump()
        assert "mask" not in (await tools.image_paint_version("Source", "Output", [stroke]))["params"]
    asyncio.run(run())


def test_synchronous_mask_limit_is_checked_before_mask_buffer_read(paint_tools, monkeypatch):
    module, context, images, _, _ = paint_tools
    mask = Image("Mask")
    mask.size = [1025, 1024]
    images.append(mask)
    original = module._read
    def read(context, image, **kwargs):
        assert image is not mask, "Oversize synchronous mask must be rejected before read"
        return original(context, image, **kwargs)
    monkeypatch.setattr(module, "_read", read)
    with pytest.raises(module.BridgeError, match="1,048,576"):
        module.paint_version(context, {"image_name": "Original", "new_name": "Output", "strokes": [stroke()], "mask": {"image_name": "Mask"}})
    assert images.get("Output") is None


def test_cancel_during_cooperative_mask_validation_releases_channel_and_handles(jobs):
    env = jobs
    mask = Image("Mask", 512, 512)
    env.images.append(mask)
    env.manager.start(env.context(), {"image_name": "Original", "new_name": "Output", "strokes": [stroke()], "mask": {"image_name": "Mask"}}, 60.)
    env.manager.tick()
    assert env.manager.active.progress["phase"] == "validating_mask"
    assert env.manager.active.prepared["mask"]["kernel"]["values"]
    env.manager.cancel(env.manager.active.job_id)
    terminal = finish(env)
    assert terminal["state"] == "CANCELLED" and not terminal["execution_started"]
    assert env.manager.history[0].work is None and env.manager.history[0].prepared == {}
    assert env.images.get("Output") is None
