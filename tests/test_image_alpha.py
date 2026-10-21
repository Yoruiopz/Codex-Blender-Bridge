from __future__ import annotations

from array import array

import pytest
from test_image_paint import Image, kernel, paint_tools, stroke  # noqa: F401

# Shared pytest fixtures are imported intentionally.
# ruff: noqa: F811


def test_generated_raw_rgba_uses_channel_packed_native_alpha_and_keeps_hidden_rgb(paint_tools):
    module, context, images, _, _ = paint_tools
    result = module.create_image(context, {"new_name": "Raw", "width": 1, "height": 1, "color": [.25,.5,.75,0.]})
    assert result["image"]["alpha_mode"] == "CHANNEL_PACKED"
    assert list(images.get("Raw").pixels.values) == [.25,.5,.75,0.]
    painted = module.paint_version(context, {"image_name": "Raw", "new_name": "Painted", "strokes": [stroke(opacity=0.)]})
    assert painted["source_pixels_unchanged"] and painted["painted_image"]["alpha_mode"] == "CHANNEL_PACKED"
    assert list(images.get("Painted").pixels.values) == [.25,.5,.75,0.]


def test_associated_float_source_is_normalized_before_straight_source_over_and_counting(kernel):
    source = array("f", [.0625,.125,.1875,.25])
    prepared, _ = kernel.prepare([stroke(opacity=0.)], 1, 1, "COLOR")
    result, info = kernel.paint(source, 1, 1, prepared, "COLOR", associated=True)
    assert list(result) == [.25,.5,.75,.25] and info["painted_pixels"] == 0
    assert info["source_associated_converted_to_straight"] and not info["source_srgb_converted_to_linear"]
    prepared, _ = kernel.prepare([stroke(opacity=.5, color=[1.,0.,0.,.5])], 1, 1, "COLOR")
    result, info = kernel.paint(source, 1, 1, prepared, "COLOR", associated=True)
    alpha = .25 + .25*.75
    assert list(result) == pytest.approx([(1*.25+.25*.25*.75)/alpha, .5*.25*.75/alpha, .75*.25*.75/alpha, alpha])
    assert info["painted_pixels"] == 1 and list(source) == [.0625,.125,.1875,.25]


@pytest.mark.parametrize("values,role,srgb", [([1.,0.,0.,0.], "COLOR", False),
    ([1.,0.,0.,.001], "COLOR", False), ([0.,0.,0.,1.], "DATA", False), ([0.,0.,0.,1.], "COLOR", True)])
def test_ambiguous_or_out_of_contract_association_is_not_silently_inferred(kernel, values, role, srgb):
    prepared, _ = kernel.prepare([stroke(opacity=0.)], 1, 1, role)
    with pytest.raises(type(kernel.invalid_argument("x"))):
        kernel.paint(array("f", values), 1, 1, prepared, role, srgb=srgb, associated=True)


def test_float_file_color_uses_actual_associated_buffer_not_file_alpha_label(paint_tools, monkeypatch):
    module, context, images, _, _ = paint_tools
    source = Image("Float File", 1, 1)
    source.source, source.type = "FILE", "IMAGE"
    source.pixels.values = array("f", [.0625,.125,.1875,.25])
    images.append(source)
    monkeypatch.setattr(module.images, "preflight_file", lambda *_args: ("approved", {"size": 1}))
    result = module.paint_version(context, {"image_name": "Float File", "new_name": "Straight", "strokes": [stroke(opacity=0.)]})
    assert result["source_associated_converted_to_straight"] and result["source_pixels_unchanged"]
    assert list(images.get("Straight").pixels.values) == [.25,.5,.75,.25]
    source.alpha_mode = "CHANNEL_PACKED"
    result = module.paint_version(context, {"image_name": "Float File", "new_name": "Raw", "strokes": [stroke(opacity=0.)]})
    assert not result["source_associated_converted_to_straight"]
    assert list(images.get("Raw").pixels.values) == [.0625,.125,.1875,.25]


def test_explicit_generated_premultiplied_color_is_supported_without_relabeling_source(paint_tools):
    module, context, images, _, _ = paint_tools
    source = images[0]
    source.alpha_mode = "PREMUL"
    source.pixels.values = array("f", [.0625,.125,.1875,.25])*16
    result = module.paint_version(context, {"image_name": "Original", "new_name": "Straight", "strokes": [stroke(opacity=0.)]})
    assert result["source_associated_converted_to_straight"] and result["source_pixels_unchanged"]
    assert source.alpha_mode == "PREMUL" and list(images.get("Straight").pixels.values[:4]) == [.25,.5,.75,.25]
