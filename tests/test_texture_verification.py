from __future__ import annotations

import hashlib
import importlib
from array import array

import pytest


@pytest.fixture
def verification(addon_package):
    return importlib.import_module(addon_package+".texture_verification")


def drain(work):
    progress = []
    while True:
        try:
            progress.append(next(work))
        except StopIteration as completed:
            return completed.value, progress


def test_raw_full_bit_comparison_includes_signed_zero_and_bounded_quantum(verification):
    values = array("f", [-0., -3., 65536., -2.])*8193
    result, progress = drain(verification.compare_steps(values, array("f", values), "EXR32_RAW", "DATA", srgb=False, check=lambda: None))
    assert result["exact_raw_float32_bits_verified"] and result["all_channels_compared"] == len(values)
    assert result["native_pixels_sha256_float32_le"] == hashlib.sha256(values).hexdigest()
    assert len(progress) == 3
    changed = array("f", values)
    changed[-4] = 0.
    with pytest.raises(verification.BridgeError, match="bits differ"):
        drain(verification.compare_steps(values, changed, "EXR32_RAW", "DATA", srgb=False, check=lambda: None))


@pytest.mark.parametrize("format,expected", [("PNG8", [64/255,128/255,191/255,128/255]),
    ("PNG16", [16384/65535,32768/65535,49151/65535,32768/65535])])
def test_quantized_data_reference_is_independent_and_checks_last_channel(verification, format, expected):
    values = array("f", [.25,.5,.75,.5])*257
    native = array("f", expected)*257
    result, progress = drain(verification.compare_steps(values, native, format, "DATA", srgb=False, check=lambda: None))
    assert result["all_channels_compared"] == 1028 and result["native_channel_tolerance"] == 2**-23
    assert len(progress) == 2 and not result["exact_raw_float32_bits_verified"]
    native[-1] += .001
    with pytest.raises(verification.BridgeError, match="channel allowance"):
        drain(verification.compare_steps(values, native, format, "DATA", srgb=False, check=lambda: None))


def test_native_png16_color_reference_accounts_for_association_not_raw_encoded_samples(verification):
    source = array("f", [.25,.5,.75,0.])
    result, _ = drain(verification.compare_steps(source, array("f", [0.,0.,0.,0.]), "PNG16", "COLOR", srgb=False, check=lambda: None))
    assert result["native_channel_tolerance"] == 2/65535 and result["native_buffer_interpretation"] == "Linear associated"
    with pytest.raises(verification.BridgeError):
        drain(verification.compare_steps(source, source, "PNG16", "COLOR", srgb=False, check=lambda: None))


def test_conventional_exr_reference_uses_associated_color_and_relative_hdr_allowance(verification):
    source = array("f", [.25,32.,-8.,.5])
    result, _ = drain(verification.compare_steps(source, array("f", [.125,16.,-4.,.5]), "EXR32", "COLOR", srgb=False, check=lambda: None))
    assert result["maximum_absolute_channel_error"] == 0. and not result["exact_raw_float32_bits_verified"]


def test_private_associated_normalization_keeps_input_alpha_and_refuses_undefined_hidden_color(verification):
    values = array("f", [.05,.1,.15,.25])*257
    _, progress = drain(verification.normalize_steps(values, associated=True, check=lambda: None))
    assert list(values[:4]) == pytest.approx([.2,.4,.6,.25]) and len(progress) == 2
    with pytest.raises(verification.invalid_argument("x").__class__, match="zero-alpha"):
        drain(verification.normalize_steps(array("f", [1.,0.,0.,0.]), associated=True, check=lambda: None))


def test_native_comparison_and_normalization_are_cooperatively_cancellable(verification):
    def stop():
        raise RuntimeError("cancel")
    values = array("f", [.2,.4,.6,1.])*1024
    for work in (verification.normalize_steps(values, associated=True, check=stop),
                 verification.compare_steps(values, values, "EXR32_RAW", "DATA", srgb=False, check=stop)):
        with pytest.raises(RuntimeError, match="cancel"):
            next(work)
