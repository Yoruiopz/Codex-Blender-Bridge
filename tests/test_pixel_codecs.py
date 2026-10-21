from __future__ import annotations

import importlib
import math
import struct
import zlib
from array import array

import pytest


@pytest.fixture
def codecs(addon_package):
    return importlib.import_module(f"{addon_package}.pixel_codecs")


def encoded(codecs, values, width, height, format, role="DATA", **kwargs):
    return b"".join(step.data for step in codecs.encode_steps(array("f", values), width, height, format, role, **kwargs))


def png_pixels(data):
    offset, payload, header = 8, b"", None
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind, chunk = data[offset+4:offset+8], data[offset+8:offset+8+length]
        assert zlib.crc32(kind+chunk) & 0xffffffff == struct.unpack_from(">I", data, offset+8+length)[0]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        if kind == b"IDAT":
            payload += chunk
        offset += 12+length
    width, height, depth, color, compression, filtering, interlace = header
    assert (color, compression, filtering, interlace) == (6, 0, 0, 0)
    raw, rows = zlib.decompress(payload), []
    stride = 1 + width*4*(depth//8)
    assert len(raw) == stride * height
    for y in range(height):
        row = raw[y*stride:(y+1)*stride]
        assert row[0] == 0
        rows.append(list(row[1:]) if depth == 8 else list(struct.unpack(">"+"H"*(width*4), row[1:])))
    return depth, rows


def exr_pixels(data):
    assert struct.unpack_from("<II", data) == (20000630, 2)
    offset, attributes = 8, {}
    while data[offset]:
        end = data.index(0, offset)
        name = data[offset:end].decode()
        offset = end+1
        end = data.index(0, offset)
        kind = data[offset:end].decode()
        length = struct.unpack_from("<I", data, end+1)[0]
        offset = end+5
        attributes[name] = (kind, data[offset:offset+length])
        offset += length
    offset += 1
    x0, y0, x1, y1 = struct.unpack("<iiii", attributes["dataWindow"][1])
    assert x0 == y0 == 0 and attributes["compression"][1] == b"\0"
    width, height, rows = x1+1, y1+1, []
    for y in range(height):
        block = struct.unpack_from("<Q", data, offset+y*8)[0]
        yy, count = struct.unpack_from("<ii", data, block)
        assert yy == y and count == width*16
        planar = struct.unpack_from("<"+"f"*(width*4), data, block+8)
        rows.append([planar[channel*width+x] for x in range(width) for channel in (3, 2, 1, 0)])
    assert len(data) == block+8+count
    return rows, attributes


@pytest.mark.parametrize("format,maximum", [("PNG8", 255), ("PNG16", 65535)])
def test_png_endianness_quantization_flip_and_zero_alpha_rgb(codecs, format, maximum):
    data = encoded(codecs, [0., .5, 1., 0., 1., .25, .75, 1.], 1, 2, format)
    depth, rows = png_pixels(data)
    assert depth == (8 if maximum == 255 else 16)
    assert rows == [[maximum, math.floor(.25*maximum+.5), math.floor(.75*maximum+.5), maximum],
                    [0, math.floor(.5*maximum+.5), maximum, 0]]


def test_png_color_is_srgb_encoded_without_a_view_transform_or_alpha_gamma(codecs):
    data = encoded(codecs, [.25, .5, 1., .5], 1, 1, "PNG16", "COLOR")
    _, rows = png_pixels(data)
    expected = [math.floor(v*65535+.5) for v in (.5370987304831942, .7353569830524495, 1., .5)]
    assert rows[0] == expected and b"sRGB" in data
    byte = encoded(codecs, [.25, .5, 1., .5], 1, 1, "PNG16", "COLOR", srgb=True)
    assert png_pixels(byte)[1][0] == [16384, 32768, 65535, 32768]


@pytest.mark.parametrize("format,role", [("EXR32", "DATA"), ("EXR32_RAW", "DATA"), ("EXR32_RAW", "COLOR")])
def test_float_exr_raw_channels_hdr_signed_orientation_and_metadata(codecs, format, role):
    values = [-.125, 65536., 1.234567, 0., 3., 2., -1., .25]
    source = array("f", values)
    rows, attrs = exr_pixels(encoded(codecs, values, 1, 2, format, role))
    assert rows == [list(source[4:]), list(source[:4])]
    assert attrs["bcbRole"] == ("string", role.encode())
    assert attrs["bcbAlphaMode"][1] == (b"CHANNEL_PACKED" if role == "DATA" else b"STRAIGHT")


def test_conventional_color_exr_is_premultiplied_and_raw_variant_preserves_hidden_rgb(codecs):
    values = [4., 2., 1., .25, 3., 2., 1., 0.]
    rows, attrs = exr_pixels(encoded(codecs, values, 2, 1, "EXR32", "COLOR"))
    assert rows[0] == [1., .5, .25, .25, 0., 0., 0., 0.]
    assert attrs["bcbAlphaMode"][1] == b"PREMUL"
    raw, _ = exr_pixels(encoded(codecs, values, 2, 1, "EXR32_RAW", "COLOR"))
    assert raw[0] == values


@pytest.mark.parametrize("format", ["PNG8", "PNG16", "EXR32", "EXR32_RAW"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_pixels_reject_explicitly_without_silent_replacement(codecs, format, bad):
    with pytest.raises(Exception, match="finite"):
        encoded(codecs, [bad, 0., 0., 1.], 1, 1, format)


@pytest.mark.parametrize("format", ["PNG8", "PNG16"])
@pytest.mark.parametrize("value", [-.1, 1.1, 16.])
def test_png_refuses_hdr_or_signed_channels_instead_of_clipping(codecs, format, value):
    with pytest.raises(Exception, match="no clipping"):
        encoded(codecs, [value, 0., 0., 1.], 1, 1, format)


def test_encoding_is_read_only_bounded_and_cooperatively_cancellable(codecs):
    source = array("f", [.2, .4, .6, 1.]) * 8192
    before, calls = source.tobytes(), []
    def check():
        calls.append(True)
        if len(calls) == 6:
            raise RuntimeError("cancelled")
    steps = codecs.encode_steps(source, 4096, 2, "EXR32_RAW", "DATA", check=check)
    observed = []
    with pytest.raises(RuntimeError, match="cancelled"):
        for step in steps:
            observed.append(step.pixels_completed)
            assert len(step.data) <= codecs.BLOCK_BYTES + 12
    assert max(observed) <= 1024 and source.tobytes() == before


def test_bad_layout_format_role_and_buffer_reject_before_any_bytes(codecs):
    for dims, format, role, source in [((0,1), "PNG8", "DATA", array("f", [0.]*4)),
        ((1,1), "JPEG", "DATA", array("f", [0.]*4)), ((1,1), "EXR32", "AUTO", array("f", [0.]*4)),
        ((1,1), "PNG8", "DATA", array("d", [0.]*4)), ((1,1), "PNG8", "DATA", array("f", [0.]*3))]:
        with pytest.raises(type(codecs.invalid_argument("x"))):
            next(codecs.encode_steps(source, *dims, format, role))
