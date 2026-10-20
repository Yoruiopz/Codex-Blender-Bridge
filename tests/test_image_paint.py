from __future__ import annotations

import asyncio
import importlib
import math
from array import array
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.image_paint import BrushStroke, ImagePaintTools


def stroke(**values):
    return {
        "points": [[0.5, 0.5]],
        "radius_pixels": 2.0,
        "color": [1.0, 0.2, 0.0, 1.0],
        "hardness": 1.0,
        **values,
    }


@pytest.fixture
def kernel(addon_package):
    return importlib.import_module(f"{addon_package}.tools.pixel_brush")


def test_color_brush_source_over_is_linear_and_original_array_is_not_modified(kernel):
    source = array("f", [0.2, 0.4, 0.6, 0.5]) * 9
    prepared, tests = kernel.prepare(
        [stroke(radius_pixels=1.0, opacity=0.5, color=[1.0, 0.0, 0.0, 0.5])], 3, 3, "COLOR"
    )
    result, summary = kernel.paint(source, 3, 3, prepared, "COLOR")
    assert source == array("f", [0.2, 0.4, 0.6, 0.5]) * 9 and tests == 9
    alpha = 0.25 + 0.5 * 0.75
    expected = [
        (1 * 0.25 + 0.2 * 0.5 * 0.75) / alpha,
        0.4 * 0.5 * 0.75 / alpha,
        0.6 * 0.5 * 0.75 / alpha,
        alpha,
    ]
    assert list(result[16:20]) == pytest.approx(expected) and summary["painted_pixels"] == 1
    assert result[:4] == source[:4]


def test_byte_srgb_is_converted_explicitly_not_treated_as_scene_linear(kernel):
    source = array("f", [0.5, 0.25, 0.125, 0.5])
    prepared, _ = kernel.prepare([stroke(opacity=0.0)], 1, 1, "COLOR")
    result, summary = kernel.paint(source, 1, 1, prepared, "COLOR", srgb=True)
    assert list(result) == pytest.approx(
        [0.21404114048223255, 0.05087608817155679, 0.014349874706802563, 0.5]
    )
    assert summary["source_srgb_converted_to_linear"] and summary["painted_pixels"] == 0


def test_data_mix_preserves_data_interpretation_and_erase_changes_only_alpha(kernel):
    values = array("f", [0.2, 0.4, 0.6, 0.8])
    prepared, _ = kernel.prepare([stroke(opacity=0.5, color=[1.0, 0.0, 0.2, 0.2])], 1, 1, "DATA")
    result, _ = kernel.paint(values, 1, 1, prepared, "DATA")
    assert list(result) == pytest.approx([0.6, 0.2, 0.4, 0.5])
    prepared, _ = kernel.prepare([stroke(opacity=0.5, blend="ERASE_ALPHA")], 1, 1, "COLOR")
    result, _ = kernel.paint(values, 1, 1, prepared, "COLOR")
    assert result[:3] == values[:3] and result[3] == pytest.approx(0.4)


def test_segment_joins_use_maximum_coverage_but_separate_strokes_accumulate(kernel):
    values = array("f", [0.0, 0.0, 0.0, 1.0]) * 25
    single = stroke(points=[[0.1, 0.5], [0.9, 0.5]], radius_pixels=1.0, opacity=0.5)
    duplicate = {**single, "points": [[0.1, 0.5], [0.9, 0.5], [0.1, 0.5], [0.1, 0.5]]}
    a, _ = kernel.paint(values, 5, 5, kernel.prepare([single], 5, 5, "COLOR")[0], "COLOR")
    b, _ = kernel.paint(values, 5, 5, kernel.prepare([duplicate], 5, 5, "COLOR")[0], "COLOR")
    c, _ = kernel.paint(values, 5, 5, kernel.prepare([single, single], 5, 5, "COLOR")[0], "COLOR")
    assert a == b and c[48] > a[48]


def test_bottom_left_clipping_pixel_radius_and_soft_falloff(kernel):
    values = array("f", [0.0, 0.0, 0.0, 1.0]) * 24
    prepared, _ = kernel.prepare(
        [stroke(points=[[0.0, 0.0]], radius_pixels=2.0, hardness=0.0)], 6, 4, "COLOR"
    )
    result, info = kernel.paint(values, 6, 4, prepared, "COLOR")
    assert 0 < result[4] < result[0] < 1 and result[(3 * 6 + 5) * 4] == 0
    assert all(x < 2 and y < 2 for x, y in info["changed_pixel_examples"])


@pytest.mark.parametrize(
    "change",
    [
        {"points": []},
        {"points": [[-1.0, 0.0]]},
        {"points": [[True, 0.0]]},
        {"points": [[0.5, 0.5]] * 129},
        {"radius_pixels": 0},
        {"radius_pixels": 257},
        {"hardness": 2},
        {"opacity": float("nan")},
        {"color": [0, 0, 0, 2]},
        {"color": [17, 0, 0, 1]},
        {"blend": "UNKNOWN"},
        {"extra": 1},
    ],
)
def test_bad_brushes_are_rejected_before_painting(kernel, change):
    with pytest.raises(kernel.invalid_argument("x").__class__):
        kernel.prepare([stroke(**change)], 32, 32, "COLOR")


def test_segment_and_candidate_budgets_reject_preallocation(kernel):
    with pytest.raises(Exception, match="256 brush"):
        kernel.prepare([stroke(points=[[0.5, 0.5]] * 128)] * 3, 4, 4, "COLOR")
    with pytest.raises(Exception, match="candidate"):
        kernel.prepare(
            [stroke(points=[[0, 0], [1, 1]], radius_pixels=256.0)] * 4, 1024, 1024, "COLOR"
        )
    with pytest.raises(Exception, match="DATA"):
        kernel.prepare([stroke(blend="ERASE_ALPHA")], 1, 1, "DATA")
    for dimensions in ((True, 4), (4097, 1), (4096, 4096)):
        with pytest.raises(type(kernel.invalid_argument("x"))):
            kernel.size(*dimensions)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 17.0])
def test_invalid_existing_pixels_are_not_silently_clamped(kernel, value):
    prepared, _ = kernel.prepare([stroke()], 1, 1, "COLOR")
    with pytest.raises(Exception, match="finite"):
        kernel.paint(array("f", [value, 0, 0, 1]), 1, 1, prepared, "COLOR")


def test_kernel_checks_cancellation_during_source_and_stroke_work(kernel):
    calls = []

    def check():
        calls.append(True)
        if len(calls) == 3:
            raise RuntimeError("cancelled")

    prepared, _ = kernel.prepare([stroke(radius_pixels=64.0)], 64, 64, "COLOR")
    with pytest.raises(RuntimeError, match="cancelled"):
        kernel.paint(
            array("f", [0.0, 0.0, 0.0, 1.0]) * 4096, 64, 64, prepared, "COLOR", check=check
        )


class Pixels:
    def __init__(self, values):
        self.values = array("f", values)

    def __len__(self):
        return len(self.values)

    def foreach_get(self, output):
        output[:] = self.values

    def foreach_set(self, values):
        self.values = array("f", values)


class Image:
    def __init__(self, name, width=4, height=4):
        self.name, self.size, self.source, self.type, self.channels = (
            name,
            [width, height],
            "GENERATED",
            "UV_TEST",
            4,
        )
        self.pixels, self.users = Pixels([0.2, 0.4, 0.6, 1.0] * (width * height)), 0
        self.colorspace_settings, self.alpha_mode = NS(name="Linear Rec.709"), "STRAIGHT"
        self.library = self.override_library = self.animation_data = None
        self.is_editable = self.has_data = self.is_float = True
        self.is_multiview = self.is_dirty = self.use_fake_user = False
        self.filepath, self.packed_file = "", None

    def update(self):
        self.is_dirty = True


class Images(list):
    def get(self, name):
        return next((image for image in self if image.name == name), None)

    def new(self, name, width, height, **_kwargs):
        image = Image(name, width, height)
        self.append(image)
        return image

    def remove(self, image, **_kwargs):
        super().remove(image)


@pytest.fixture
def paint_tools(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.image_paint")
    images = Images([Image("Original")])
    bpy = NS(
        data=NS(images=images),
        context=NS(mode="OBJECT"),
        types=NS(
            ColorManagedInputColorspaceSettings=NS(
                bl_rna=NS(
                    properties={
                        "name": NS(
                            enum_items=[NS(identifier=space) for space in module.SPACES.values()]
                        )
                    }
                )
            )
        ),
    )
    grants = {p.value: True for p in module.Permission}

    def require(*permissions):
        if any(not grants[p.value] for p in permissions):
            raise module.BridgeError("PERMISSION_DENIED", "permission denied")

    context = NS(require=require, check_cancelled=None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module.images, "require_blender", lambda: bpy)
    return module, context, images, bpy, grants


def test_new_texture_and_version_have_exact_pixels_without_mutating_or_binding_source(paint_tools):
    module, context, images, _, grants = paint_tools
    grants["INSPECT_SCENE"] = grants["ACCESS_EXTERNAL_FILES"] = False
    result = module.create_image(
        context, {"new_name": "Blank", "width": 4, "height": 4, "color": [0, 0, 0, 0]}
    )
    assert result["pixels_verified"] and not result["bound_to_nodes"] and not result["file_written"]
    before = module.brush.digest(images[0].pixels.values)
    result = module.paint_version(
        context, {"image_name": "Original", "new_name": "Painted", "strokes": [stroke()]}
    )
    assert (
        result["source_pixels_unchanged"]
        and result["painted_pixels"] > 0
        and result["candidate_pixel_tests"] == 16
    )
    assert module.brush.digest(images[0].pixels.values) == before and images[0].users == 0


def test_independent_pixel_inspection_uses_raw_values_and_sanitizes_nonfinite(paint_tools):
    module, context, images, _, _ = paint_tools
    images[0].pixels.values[0] = math.nan
    result = module.inspect_pixels(context, {"image_name": "Original", "samples": [[0, 0]]})
    assert result["analysis_complete"] and result["nonfinite_channels"] == 1
    assert result["samples"][0]["rgba"][0] is None and len(result["pixels_sha256_float32_le"]) == 64


@pytest.mark.parametrize(
    "kind",
    [
        "unloaded",
        "shared_library",
        "channels",
        "animated",
        "alpha",
        "float_srgb",
        "ocio",
        "mode",
        "name_exists",
        "permission",
    ],
)
def test_unsupported_source_or_scope_never_creates_version(paint_tools, kind):
    module, context, images, bpy, grants = paint_tools
    image = images[0]
    if kind == "unloaded":
        image.has_data = False
    elif kind == "shared_library":
        image.library = object()
    elif kind == "channels":
        image.channels = 3
    elif kind == "animated":
        image.animation_data = NS(action=object())
    elif kind == "alpha":
        image.alpha_mode = "PREMUL"
    elif kind == "float_srgb":
        image.colorspace_settings.name = "sRGB"
    elif kind == "ocio":
        image.colorspace_settings.name = "Unreviewed Role"
    elif kind == "mode":
        bpy.context.mode = "EDIT_MESH"
    elif kind == "name_exists":
        images.append(Image("Painted"))
    elif kind == "permission":
        grants["EDIT_MATERIALS"] = False
    before = list(images)
    with pytest.raises(module.BridgeError):
        module.paint_version(
            context, {"image_name": "Original", "new_name": "Painted", "strokes": [stroke()]}
        )
    assert list(images) == before


@pytest.mark.parametrize("unexpected_user", [False, True])
def test_native_write_failure_cleans_only_unused_new_image(
    paint_tools, monkeypatch, unexpected_user
):
    module, context, images, _, _ = paint_tools
    original_new = images.new

    def fault(*args, **kwargs):
        image = original_new(*args, **kwargs)

        def update():
            image.users = int(unexpected_user)
            raise RuntimeError("injected after pixel write")

        image.update = update
        return image

    monkeypatch.setattr(images, "new", fault)
    with pytest.raises(module.BridgeError) as caught:
        module.paint_version(
            context, {"image_name": "Original", "new_name": "Painted", "strokes": [stroke()]}
        )
    assert caught.value.context["rollback_verified"] is not unexpected_user
    assert caught.value.context["possible_mutation"] is unexpected_user
    assert bool(images.get("Painted")) is unexpected_user and images[0].name == "Original"


def test_file_source_is_permission_gated_even_for_cached_pixels(paint_tools):
    module, context, images, _, grants = paint_tools
    images[0].source = "FILE"
    grants["ACCESS_EXTERNAL_FILES"] = False
    for method, values in (
        (module.inspect_pixels, {"image_name": "Original"}),
        (
            module.paint_version,
            {"image_name": "Original", "new_name": "Painted", "strokes": [stroke()]},
        ),
    ):
        with pytest.raises(module.BridgeError) as caught:
            method(context, values)
        assert caught.value.code == "PERMISSION_DENIED"
    assert len(images) == 1


def test_brush_schema_and_wrapper_forwarding_are_strict_and_bounded():
    for values in (
        stroke(radius_pixels=True),
        stroke(points=[[2.0, 0.0]]),
        stroke(color=[0, 0, 0, 2]),
        stroke(extra=True),
    ):
        with pytest.raises(ValidationError):
            BrushStroke(**values)
    hints = get_type_hints(ImagePaintTools.image_create, include_extras=True)
    for value in (True, 0, 4097):
        with pytest.raises(ValidationError):
            TypeAdapter(hints["width"]).validate_python(value)
    calls = []

    async def call(method, values):
        calls.append((method, values))

    tool = ImagePaintTools()
    tool.registry = NS(call=call)
    asyncio.run(tool.image_paint_version("Original", "Painted", [BrushStroke(**stroke())]))
    assert calls[0][0] == "image.paint_version" and calls[0][1]["strokes"][0]["blend"] == "MIX"


def test_registry_permissions_and_modification_metadata(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.image_paint")
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    module.register_tools(registry)
    for name in ("image.create", "image.paint_version"):
        spec = registry.get(name)
        assert spec.modifies and spec.automatic_checkpoint and spec.toolset == "materials"
        assert spec.permissions == frozenset({module.Permission.EDIT_MATERIALS})
    assert not registry.get("image.inspect_pixels").modifies


@pytest.mark.parametrize(
    "change",
    [
        {"role": []},
        {"role": "UNKNOWN"},
        {"color": [0, 0, 0, 2]},
        {"role": "DATA", "color": [1.1, 0, 0, 1]},
        {"width": 4096, "height": 4096},
    ],
)
def test_invalid_new_image_parameters_never_allocate(paint_tools, change):
    module, context, images, _, _ = paint_tools
    with pytest.raises(module.BridgeError):
        module.create_image(context, {"new_name": "Invalid", "width": 4, "height": 4, **change})
    assert len(images) == 1


def test_revocation_after_native_pixel_write_is_not_published(paint_tools, monkeypatch):
    module, context, images, _, grants = paint_tools
    native_new = images.new

    def allocate(*args, **kwargs):
        image = native_new(*args, **kwargs)
        image.update = lambda: grants.update(EDIT_MATERIALS=False)
        return image

    monkeypatch.setattr(images, "new", allocate)
    with pytest.raises(module.BridgeError) as caught:
        module.create_image(context, {"new_name": "Denied", "width": 4, "height": 4})
    assert caught.value.code == "PERMISSION_DENIED" and caught.value.context["rollback_verified"]
    assert images.get("Denied") is None


def test_cancellation_during_cpu_work_prevents_allocation(paint_tools):
    module, context, images, _, _ = paint_tools
    checks = []

    def check():
        checks.append(True)
        if len(checks) == 7:
            raise module.BridgeError("TIMEOUT", "cancelled")

    context.check_cancelled = check
    with pytest.raises(module.BridgeError) as caught:
        module.paint_version(
            context, {"image_name": "Original", "new_name": "Cancelled", "strokes": [stroke()]}
        )
    assert caught.value.code == "TIMEOUT" and images.get("Cancelled") is None


@pytest.mark.parametrize("kind", ["readback", "missing_space", "budget", "buffer_length"])
def test_failed_verification_or_unsupported_buffer_is_explicit(paint_tools, monkeypatch, kind):
    module, context, images, bpy, _ = paint_tools
    if kind == "readback":
        native_new = images.new

        def allocate(*args, **kwargs):
            image = native_new(*args, **kwargs)
            image.pixels.foreach_set = lambda *_: None
            return image

        monkeypatch.setattr(images, "new", allocate)
    elif kind == "missing_space":
        bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"].enum_items = []
    elif kind == "budget":
        images[0].size = [4096, 4096]
    else:
        images[0].pixels.values.pop()
    with pytest.raises(module.BridgeError):
        module.paint_version(
            context, {"image_name": "Original", "new_name": "Failed", "strokes": [stroke()]}
        )
    assert images.get("Failed") is None


def test_postallocation_source_verification_failure_retains_truthful_mutation_evidence(
    paint_tools, monkeypatch
):
    module, context, images, _, _ = paint_tools
    native_read = module._read

    def fault(ctx, image, **kwargs):
        if image.name == "Original" and images.get("Painted") is not None:
            raise module.BridgeError("OPERATION_FAILED", "source readback failed")
        return native_read(ctx, image, **kwargs)

    monkeypatch.setattr(module, "_read", fault)
    with pytest.raises(module.BridgeError) as caught:
        module.paint_version(
            context, {"image_name": "Original", "new_name": "Painted", "strokes": [stroke()]}
        )
    assert (
        caught.value.context["possible_mutation"] and caught.value.context["verification_required"]
    )
    assert images.get("Painted") is not None


@pytest.mark.parametrize("samples", [[[True, 0]], [[0, 4096]], [[4, 0]], [[0]], [[0, 0]] * 65])
def test_bad_sample_requests_are_bounded(paint_tools, samples):
    module, context, _, _, _ = paint_tools
    with pytest.raises(module.BridgeError):
        module.inspect_pixels(context, {"image_name": "Original", "samples": samples})


def test_inspection_nonfinite_values_are_safe_protocol_json(paint_tools):
    import json

    module, context, images, _, _ = paint_tools
    images[0].pixels.values[:4] = array("f", [math.nan, math.inf, -math.inf, 1.0])
    result = module.inspect_pixels(context, {"image_name": "Original", "samples": [[0, 0]]})
    assert result["nonfinite_channels"] == 3
    json.dumps(result, allow_nan=False)


def test_encoded_srgb_outside_unit_interval_is_not_interpreted_as_hdr(kernel):
    prepared, _ = kernel.prepare([stroke()], 1, 1, "COLOR")
    with pytest.raises(type(kernel.invalid_argument("x")), match="finite"):
        kernel.paint(array("f", [2.0, 0.0, 0.0, 1.0]), 1, 1, prepared, "COLOR", srgb=True)


@pytest.mark.parametrize("hardness", [0.0, 0.1, 0.8, 1 - 1e-15, 1.0])
def test_coverage_rounding_never_leaks_outside_unit_data_range(kernel, hardness):
    for delta in (0.0, 1e-14, 0.01, 0.124999999999999):
        prepared, _ = kernel.prepare(
            [
                stroke(
                    points=[[0.125 + delta, 0.125]],
                    radius_pixels=0.5,
                    hardness=hardness,
                    color=[0.0, 0.0, 0.0, 0.0],
                )
            ],
            4,
            4,
            "DATA",
        )
        result, _ = kernel.paint(array("f", [1.0] * 64), 4, 4, prepared, "DATA")
        assert all(0 <= value <= 1 for value in result)


def test_cleanup_denial_retains_owned_image_and_reports_possible_mutation(paint_tools, monkeypatch):
    module, context, images, _, grants = paint_tools
    grants["DELETE_OBJECTS"] = False
    original = images.new

    def allocate(*args, **kwargs):
        image = original(*args, **kwargs)

        def failed():
            raise RuntimeError("post-write failure with deletion disabled")

        image.update = failed
        return image

    monkeypatch.setattr(images, "new", allocate)
    with pytest.raises(module.BridgeError) as caught:
        module.create_image(context, {"new_name": "Retained", "width": 4, "height": 4})
    assert (
        not caught.value.context["rollback_verified"] and caught.value.context["possible_mutation"]
    )
    assert caught.value.context["cleanup_permission_denied"] and images.get("Retained") is not None
