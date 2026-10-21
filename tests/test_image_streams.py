from __future__ import annotations

import hashlib
import importlib
import io
import struct
import zlib
from array import array
from types import SimpleNamespace as NS

import pytest
from test_image_assets import chunk, jpeg
from test_image_assets import tools as shared_image_tools

image_tools = shared_image_tools


@pytest.fixture
def stream_modules(addon_package):
    return NS(streams=importlib.import_module(f"{addon_package}.image_streams"),
              files=importlib.import_module(f"{addon_package}.image_files"),
              codecs=importlib.import_module(f"{addon_package}.pixel_codecs"))


def drain(work):
    progress = []
    while True:
        try:
            progress.append(next(work))
        except StopIteration as done:
            return done.value, progress


class BoundedReads(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.requests = []

    def read(self, count=-1):
        assert 0 <= count <= 65536, "unbounded/file-sized source read"
        self.requests.append(count)
        return super().read(count)


def inspect(modules, data, suffix, *, check=lambda: None):
    stream = BoundedReads(data)
    result, progress = drain(modules.streams.preflight_stream(stream, suffix, len(data), check=check))
    assert stream.tell() == len(data) and result["file_sha256"] == hashlib.sha256(data).hexdigest()
    assert result["streaming_preflight"] and not result["pixel_contents_verified"]
    return result, progress, stream


def make_png(raw, width=2, height=2, depth=8, color=6, interlace=0, *, before=b"", compressed=None, after=b""):
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace))
            + before + chunk(b"IDAT", zlib.compress(raw) if compressed is None else compressed) + after + chunk(b"IEND", b""))


def make_exr(modules, width=3, height=2, *, attributes=None, format="EXR32_RAW", role="DATA"):
    header = modules.codecs.exr_header(width, height, format, role)
    if attributes is not None:
        header = struct.pack("<II", 20000630, 2) + b"".join(
            modules.codecs._attribute(name, kind, data) for name, kind, data in attributes) + b"\0"
    start, stride = len(header)+height*8, width*16+8
    return (header + b"".join(struct.pack("<Q", start+y*stride) for y in range(height))
            + b"".join(struct.pack("<ii", y, width*16)+bytes(width*16) for y in range(height)))


def exr_attributes(modules):
    data = modules.codecs.exr_header(3, 2, "EXR32_RAW", "DATA")
    offset, result = 8, []
    while data[offset]:
        end = data.index(0, offset)
        name, offset = data[offset:end].decode(), end+1
        end = data.index(0, offset)
        kind = data[offset:end].decode()
        length = struct.unpack_from("<I", data, end+1)[0]
        offset = end+5
        result.append((name, kind, data[offset:offset+length]))
        offset += length
    return result


@pytest.mark.parametrize("format", ["PNG8", "PNG16", "EXR32", "EXR32_RAW"])
@pytest.mark.parametrize("role", ["COLOR", "DATA"])
def test_all_encoder_streams_receive_complete_independent_file_proof(stream_modules, format, role):
    source = array("f", [.25, .5, .75, .5, .1, .2, .3, 0., 1., .75, .5, 1., 0., .5, 1., 1.])
    data = b"".join(step.data for step in stream_modules.codecs.encode_steps(source, 2, 2, format, role))
    suffix = ".png" if format.startswith("PNG") else ".exr"
    result, progress, stream = inspect(stream_modules, data, suffix)
    assert (result["width"], result["height"]) == (2, 2) and progress
    assert max(stream.requests) <= 65536
    if suffix == ".exr":
        assert result["channels"] == ["A", "B", "G", "R"] and result["compression"] == "NONE"
        assert result["interpretation_hints"]["bcbRole"] == role


@pytest.mark.parametrize("width,height", [(1, 1), (2, 3), (9, 9), (17, 10)])
@pytest.mark.parametrize("depth,color,channels", [(1, 0, 1), (8, 2, 3), (16, 6, 4)])
def test_adam7_and_subbyte_scanline_framing(stream_modules, width, height, depth, color, channels):
    raw = bytearray()
    # Independent range-based pass construction, not the parser's integer ceil implementation.
    for x, y, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8),
                         (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)):
        w, h = len(range(x, width, dx)), len(range(y, height, dy))
        if w and h:
            raw.extend((b"\0" + bytes((w*channels*depth+7)//8))*h)
    result, _, _ = inspect(stream_modules, make_png(raw, width, height, depth, color, 1), ".png")
    assert result["interlace"] == 1 and result["png_scanline_layout_verified"]


@pytest.mark.parametrize("depth,color,channels", [(1, 0, 1), (2, 0, 1), (4, 0, 1), (8, 0, 1),
    (16, 0, 1), (8, 2, 3), (16, 2, 3), (8, 4, 2), (16, 4, 2), (8, 6, 4), (16, 6, 4)])
def test_png_review_preserves_existing_grayscale_rgb_alpha_depths(stream_modules, depth, color, channels):
    stride = (9*channels*depth+7)//8
    raw = b"".join(bytes([row])+bytes(stride) for row in range(5))
    result, _, _ = inspect(stream_modules, make_png(raw, 9, 5, depth, color), ".png")
    assert result["color_type"] == color and result["bit_depth"] == depth


def test_palette_transparency_and_bounded_unknown_ancillary(stream_modules):
    palette = chunk(b"PLTE", b"\0\0\0\xff\xff\xff") + chunk(b"tRNS", b"\0\xff")
    data = make_png(b"\0\x10", 2, 1, 4, 3, before=palette+chunk(b"vpAg", b"bounded"))
    result, _, _ = inspect(stream_modules, data, ".png")
    assert result["color_type"] == 3


@pytest.mark.parametrize("case", ["short_rows", "too_many_rows", "bad_filter", "zlib_truncated", "zlib_extra",
    "zlib_bad", "trailing", "checksum", "interleaved_idat", "palette_missing", "palette_large", "bad_transparency",
    "unknown_critical", "compressed_metadata", "animation", "exif", "large_metadata", "many_metadata", "bad_chunk_name"])
def test_bad_png_cannot_reach_native_decoder(stream_modules, case):
    raw, kwargs = b"\0"+b"\xff"*8, {"width": 2, "height": 1}
    if case == "short_rows":
        kwargs["height"] = 2
    elif case == "too_many_rows":
        raw *= 10000
    elif case == "bad_filter":
        raw = b"\5"+bytes(8)
    elif case == "zlib_truncated":
        kwargs["compressed"] = zlib.compress(raw)[:-1]
    elif case == "zlib_extra":
        kwargs["compressed"] = zlib.compress(raw)+zlib.compress(b"")
    elif case == "zlib_bad":
        kwargs["compressed"] = b"not zlib"
    elif case == "interleaved_idat":
        kwargs["after"] = chunk(b"tEXt", b"name\0value")+chunk(b"IDAT", b"x")
    elif case.startswith("palette"):
        kwargs.update(color=3, depth=1)
        if case == "palette_large":
            kwargs["before"] = chunk(b"PLTE", bytes(9))
    elif case == "bad_transparency":
        kwargs["before"] = chunk(b"tRNS", b"\0\0")
    elif case == "unknown_critical":
        kwargs["before"] = chunk(b"BADC", b"")
    elif case in {"compressed_metadata", "animation", "exif"}:
        kwargs["before"] = chunk({"compressed_metadata": b"iCCP", "animation": b"acTL", "exif": b"eXIf"}[case], b"x")
    elif case == "large_metadata":
        kwargs["before"] = chunk(b"tEXt", bytes(65537))
    elif case == "many_metadata":
        kwargs["before"] = chunk(b"vpAg", bytes(65536))*5
    elif case == "bad_chunk_name":
        kwargs["before"] = chunk(b"vpgg", b"")
    data = make_png(raw, **kwargs)
    if case == "trailing":
        data += b"extra"
    elif case == "checksum":
        data = data[:-1]+bytes([data[-1]^1])
    with pytest.raises(stream_modules.streams.BridgeError):
        inspect(stream_modules, data, ".png")


def test_inflation_returns_safe_points_even_for_tiny_compressed_payload(stream_modules):
    data = make_png((b"\0"+bytes(512*8))*512, 512, 512, 16, 6)
    result, progress, stream = inspect(stream_modules, data, ".png")
    inflated = [step["inflated_bytes"] for step in progress if step["phase"] == "inflating_png"]
    assert len(data) < 10000 and len(inflated) > 16 and inflated[-1] == 512*(512*8+1)
    assert max(stream.requests) <= 65536 and result["file_bytes"] == len(data)


def test_png_chunk_budget_supports_full_encoder_height_not_4096_total_chunks(stream_modules):
    raw = b"\0\0"*4096
    # Empty IDATs are valid. A row-streaming 4K encoder can likewise emit one
    # IDAT per row plus flush/IHDR/IEND, exceeding the old total-chunk ceiling.
    payload = (b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 4096, 8, 0, 0, 0, 0))
               +chunk(b"IDAT", b"")*4096+chunk(b"IDAT", zlib.compress(raw))+chunk(b"IEND", b""))
    result, progress, _ = inspect(stream_modules, payload, ".png")
    assert result["height"] == 4096 and len(progress) > 4096


@pytest.mark.parametrize("marker", [0xc0, 0xc2])
def test_jpeg_retains_bounded_header_only_contract_and_complete_digest(stream_modules, marker):
    result, _, _ = inspect(stream_modules, jpeg(marker), ".jpg")
    assert result["format"] == "JPEG" and not result["jpeg_codestream_verified"]


@pytest.mark.parametrize("flag", [1, 2|0x200, 2|0x400, 2|0x800, 2|0x1000])
def test_exr_version_tiled_deep_multipart_long_name_flags_fail_before_header(stream_modules, flag):
    data = struct.pack("<II", 20000630, flag)
    with pytest.raises(stream_modules.streams.BridgeError) as error:
        inspect(stream_modules, data, ".exr")
    assert error.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("case", ["duplicate", "missing", "unknown", "wrong_type", "compressed", "different_windows",
    "negative_origin", "huge", "half", "sampling", "extra_channel", "descending", "bad_aspect", "attribute_size",
    "chromaticities", "unknown_role", "short_name"])
def test_exr_metadata_and_allocation_bounds(stream_modules, case):
    attrs = exr_attributes(stream_modules)
    def replace(name, kind, payload):
        return [(n, kind if n == name else k, payload if n == name else p) for n, k, p in attrs]
    if case == "duplicate":
        attrs.append(attrs[0])
    elif case == "missing":
        attrs = [a for a in attrs if a[0] != "dataWindow"]
    elif case == "unknown":
        attrs.append(("unreviewed", "blob", b"x"))
    elif case == "wrong_type":
        attrs = replace("dataWindow", "string", bytes(16))
    elif case == "compressed":
        attrs = replace("compression", "compression", b"\3")
    elif case == "different_windows":
        attrs = replace("displayWindow", "box2i", struct.pack("<iiii", 0, 0, 3, 2))
    elif case == "negative_origin":
        attrs = replace("dataWindow", "box2i", struct.pack("<iiii", -1, 0, 2, 1))
    elif case == "huge":
        attrs = replace("dataWindow", "box2i", struct.pack("<iiii", 0, 0, 999999, 999999))
        attrs = [(n, k, struct.pack("<iiii", 0, 0, 999999, 999999) if n == "displayWindow" else p) for n, k, p in attrs]
    elif case in {"half", "sampling", "extra_channel"}:
        payload = bytearray(attrs[0][2])
        if case == "half":
            struct.pack_into("<i", payload, 2, 1)
        elif case == "sampling":
            struct.pack_into("<i", payload, 10, 2)
        else:
            payload[-1:] = b"Z\0"+struct.pack("<iB3xii", 2, 0, 1, 1)+b"\0"
        attrs = replace("channels", "chlist", bytes(payload))
    elif case == "descending":
        attrs = replace("lineOrder", "lineOrder", b"\1")
    elif case == "bad_aspect":
        attrs = replace("pixelAspectRatio", "float", struct.pack("<f", float("nan")))
    elif case == "attribute_size":
        attrs.append(("comments", "string", bytes(4097)))
    elif case == "chromaticities":
        attrs.append(("chromaticities", "chromaticities", struct.pack("<8f", *([.5]*8))))
    elif case == "unknown_role":
        attrs = replace("bcbRole", "string", b"guessed")
    else:
        attrs.append(("x"*32, "string", b"x"))
    with pytest.raises(stream_modules.streams.BridgeError):
        inspect(stream_modules, make_exr(stream_modules, attributes=attrs), ".exr")


@pytest.mark.parametrize("case", ["offset", "duplicate_offset", "line_y", "line_size", "truncated", "trailing"])
def test_exr_rows_and_offset_table_require_complete_exact_layout(stream_modules, case):
    data = bytearray(make_exr(stream_modules))
    header_length = len(stream_modules.codecs.exr_header(3, 2, "EXR32_RAW", "DATA"))
    start = header_length+16
    if case == "offset":
        struct.pack_into("<Q", data, header_length, len(data)+100)
    elif case == "duplicate_offset":
        struct.pack_into("<Q", data, header_length+8, start)
    elif case == "line_y":
        struct.pack_into("<i", data, start, -1)
    elif case == "line_size":
        struct.pack_into("<i", data, start+4, 400000)
    elif case == "truncated":
        data = data[:-1]
    else:
        data += b"x"
    with pytest.raises(stream_modules.streams.BridgeError):
        inspect(stream_modules, bytes(data), ".exr")


def test_large_exr_exceeds_old_32m_limit_without_file_sized_reader_copy(stream_modules, tmp_path):
    data = make_exr(stream_modules, 4096, 513)
    assert len(data) > 32*1024*1024
    path = tmp_path / "large.exr"
    path.write_bytes(data)
    (resolved, proof), progress = drain(stream_modules.files.preflight_steps(str(path), str(tmp_path)))
    assert resolved == path and proof["file_sha256"] == hashlib.sha256(data).hexdigest()
    assert len(progress) > 512 and proof["maximum_read_bytes"] == 65536


def test_cancel_between_read_slices_and_generator_close_release_file(stream_modules, tmp_path):
    path = tmp_path / "source.exr"
    path.write_bytes(make_exr(stream_modules, 128, 129))
    canceled = False
    def check():
        if canceled:
            raise stream_modules.files.BridgeError("TIMEOUT", "canceled")
    work = stream_modules.files.preflight_steps(str(path), str(tmp_path), check=check)
    next(work)
    canceled = True
    with pytest.raises(stream_modules.files.BridgeError, match="canceled"):
        next(work)
    path.rename(tmp_path / "closed.exr")  # On Windows also proves no retained open file handle.


def test_file_change_during_preflight_invalidates_complete_proof(stream_modules, tmp_path):
    path = tmp_path / "source.exr"
    path.write_bytes(make_exr(stream_modules))
    work = stream_modules.files.preflight_steps(str(path), str(tmp_path))
    next(work)
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(stream_modules.files.BridgeError):
        drain(work)


def test_public_exr_load_requires_explicit_role_and_preserves_file(image_tools, stream_modules):
    module, _, images, _, context, path = image_tools
    exr = path.with_suffix(".exr")
    exr.write_bytes(make_exr(stream_modules, 2, 2))
    original = images.load
    def load(*args, **kwargs):
        image = original(*args, **kwargs)
        image.is_float, image.channels = True, 4
        image.alpha_mode = "CHANNEL_PACKED"
        return image
    images.load = load
    for params in ({}, {"colorspace": "Non-Color"}, {"colorspace": "Non-Color", "alpha_mode": "PREMUL"}):
        with pytest.raises(module.BridgeError) as error:
            module.load_image(context, {"filepath": str(exr), "new_name": "Bad", **params})
        assert error.value.code == "INVALID_ARGUMENT" and not images
    result = module.load_image(context, {"filepath": str(exr), "new_name": "Raw", "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED"})
    assert result["loaded"] and result["source_file"]["format"] == "EXR" and not result["file_written"]
    assert result["source_file"]["file_sha256"] == hashlib.sha256(exr.read_bytes()).hexdigest()
    assert module.binding_source(context, images.get("Raw"))["format"] == "EXR"


@pytest.mark.parametrize("action", ["revoke", "root", "pause", "stop"])
def test_live_changes_before_native_decode_are_authoritative(image_tools, monkeypatch, action):
    module, _, images, grants, context, path = image_tools
    flags = {"paused": False, "emergency_stopped": False}
    context.state = NS(snapshot=lambda: dict(flags))
    calls = 0
    def changed():
        nonlocal calls
        calls += 1
        if calls == 8:
            if action == "revoke":
                grants["ACCESS_EXTERNAL_FILES"] = False
            elif action == "root":
                monkeypatch.setattr(module, "_root", lambda: "")
            else:
                flags["paused" if action == "pause" else "emergency_stopped"] = True
    context.check_cancelled = changed
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Stopped"})
    assert error.value.code in {"PERMISSION_DENIED", "AGENT_PAUSED", "EMERGENCY_STOPPED"}
    assert not images


def test_consent_revoked_inside_read_checkpoint_is_rechecked_before_io(image_tools, monkeypatch):
    module, _, images, grants, context, path = image_tools
    def preflight(raw, root, check):
        context.check_cancelled = lambda: grants.update(ACCESS_EXTERNAL_FILES=False)
        check()
        pytest.fail("Read checkpoint allowed IO after revoking external-file permission")
    monkeypatch.setattr(module, "preflight_file", preflight)
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Denied"})
    assert error.value.code == "PERMISSION_DENIED" and not images


def test_native_mutation_gate_rechecks_edit_after_lifecycle_callback(image_tools):
    module, _, _, grants, context, _ = image_tools
    context.check_cancelled = lambda: grants.update(EDIT_MATERIALS=False)
    with pytest.raises(module.BridgeError) as error:
        module._load_gate(context)
    assert error.value.code == "PERMISSION_DENIED"


def test_approved_folder_changed_after_proof_stops_before_native_load(image_tools, monkeypatch):
    module, _, images, _, context, path = image_tools
    original = module.preflight_file
    def preflight(*args):
        proof = original(*args)
        context.check_cancelled = lambda: monkeypatch.setattr(module, "_root", lambda: "")
        return proof
    monkeypatch.setattr(module, "preflight_file", preflight)
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Denied"})
    assert error.value.code == "PERMISSION_DENIED" and not images
