from __future__ import annotations

import pytest

from scripts.native_camera_evidence import compare_rgba8, rgba8


def test_readback_noise_within_same_byte_is_not_a_changed_pixel():
    before = rgba8([.25, .5, .75, 1.])
    after = rgba8([.25 + 1e-8, .5 + 1e-8, .75 - 1e-8, 1.])
    assert compare_rgba8(before, after, 1, 1)["changed_pixels"] == 0


def test_complete_rgba_including_alpha_and_last_pixel_is_compared():
    before = bytes([10, 20, 30, 255] * 2)
    after = bytes([11, 20, 30, 255, 10, 20, 30, 252])
    result = compare_rgba8(before, after, 2, 1)
    assert result["pixels_compared"] == result["changed_pixels"] == 2
    assert result["max_channel_error_rgba8"] == 3
    assert result["before_sha256"] != result["after_sha256"]


@pytest.mark.parametrize("values", [[0.], [0., 0., float("nan"), 1.], [0., 0., 0., 2.], [-.1, 0., 0., 1.]])
def test_invalid_readback_is_not_silently_clipped(values):
    with pytest.raises(ValueError):
        rgba8(values)


@pytest.mark.parametrize("a,b,w,h", [(b"", b"", 0, 1), (b"0000", b"0000", True, 1), (b"0000", b"000", 1, 1), (b"0000", b"0000", 2, 1)])
def test_incomplete_or_invalid_captures_are_rejected(a, b, w, h):
    with pytest.raises(ValueError):
        compare_rgba8(a, b, w, h)
