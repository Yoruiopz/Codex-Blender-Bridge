"""Bounded standard-library bitmap preflight, never a native image decoder.

Read/hash the complete file without a file-sized bytes copy. PNG inflation is
output-capped and validates scanline/filter framing (including Adam7), not pixel
values. EXR accepts only the explicitly reviewed plain RGBA FLOAT layout.
"""

from __future__ import annotations

import hashlib
import math
import struct
import zlib
from collections.abc import Callable, Iterator
from typing import BinaryIO

from .errors import BridgeError, ErrorCode, invalid_argument
from .image_files import _dimensions

READ_BYTES = 65536
MAX_CHUNKS = 16384
MAX_JPEG_MARKERS = 4096
MAX_ANCILLARY_BYTES = 262144
MAX_HEADER_BYTES = 65536
MAX_ATTRIBUTES = 64
MAX_ATTRIBUTE_BYTES = 4096
REC709_CHROMATICITIES = (.64, .33, .30, .60, .15, .06, .3127, .3290)


def _unsupported(message: str):
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message)


class Reader:
    def __init__(self, stream: BinaryIO, total: int, check: Callable[[], None]):
        self.stream, self.total, self.check = stream, total, check
        self.position = 0
        self.digest = hashlib.sha256()

    def read(self, count: int) -> bytes:
        self.check()
        if not 0 <= count <= READ_BYTES or count > self.total-self.position:
            raise invalid_argument("Texture fields exceed their bounded read or remaining-file budget.")
        data = self.stream.read(count)
        if len(data) != count:
            raise invalid_argument("Texture file ended before its declared fields/data.")
        self.position += count
        self.digest.update(data)
        return data

    def progress(self, phase="reading_file", **extra) -> dict:
        return {"phase": phase, "completed": self.position, "total": self.total, **extra}

    def cstring(self, *, allow_empty=False) -> str:
        value = bytearray()
        for _ in range(32):
            byte = self.read(1)
            if byte == b"\0":
                if not value and not allow_empty:
                    raise invalid_argument("EXR attribute/type names cannot be empty.")
                try:
                    return value.decode("ascii")
                except UnicodeError as exc:
                    raise invalid_argument("Reviewed EXR names must be short ASCII strings.") from exc
            if byte[0] < 32 or byte[0] > 126:
                raise invalid_argument("Reviewed EXR names must contain printable ASCII.")
            value.extend(byte)
        raise _unsupported("EXR long names are not reviewed; use short standard attribute/channel names.")


class Scanlines:
    """Count filtered bytes with bounded state, no reconstructed image allocation."""

    def __init__(self, width: int, height: int, channels: int, depth: int, interlace: int):
        passes = ((0, 0, 1, 1),) if not interlace else (
            (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
            (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
        self.passes = []
        for x, y, dx, dy in passes:
            w, h = max(0, (width-x+dx-1)//dx), max(0, (height-y+dy-1)//dy)
            if w and h:
                self.passes.append(((w*channels*depth+7)//8, h))
        self.expected = sum((stride+1)*rows for stride, rows in self.passes)
        self.received, self.current, self.row, self.remaining = 0, 0, 0, 0
        self.filter_needed = True

    def feed(self, data: bytes) -> None:
        if self.received + len(data) > self.expected:
            raise invalid_argument("PNG inflated data exceeds the IHDR/Adam7 scanline budget.")
        self.received += len(data)
        offset = 0
        while offset < len(data):
            if self.current >= len(self.passes):
                raise invalid_argument("PNG contains extra scanline data.")
            stride, rows = self.passes[self.current]
            if self.filter_needed:
                if data[offset] > 4:
                    raise invalid_argument("PNG scanline uses an invalid filter byte.")
                offset += 1
                self.filter_needed, self.remaining = False, stride
            consumed = min(self.remaining, len(data)-offset)
            offset += consumed
            self.remaining -= consumed
            if not self.remaining:
                self.filter_needed = True
                self.row += 1
                if self.row == rows:
                    self.current += 1
                    self.row = 0


def _png(reader: Reader) -> Iterator[dict]:
    if reader.read(8) != b"\x89PNG\r\n\x1a\n":
        raise invalid_argument("Texture is not a PNG file.")
    header, lines, inflater = None, None, zlib.decompressobj()
    seen, ancillary, palette, idat, idat_closed = set(), 0, None, False, False
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    for index in range(MAX_CHUNKS):
        length, kind = struct.unpack(">I", reader.read(4))[0], reader.read(4)
        if any(not (65 <= c <= 90 or 97 <= c <= 122) for c in kind) or kind[2] & 32:
            raise invalid_argument("PNG chunk names/reserved bits are invalid.")
        if length > reader.total-reader.position-4:
            raise invalid_argument("PNG chunk extends beyond the remaining file.")
        if not index and (kind != b"IHDR" or length != 13):
            raise invalid_argument("PNG must begin with one standard IHDR.")
        if kind == b"IHDR" and index:
            raise invalid_argument("PNG has duplicate IHDR chunks.")
        if kind in {b"acTL", b"fcTL", b"fdAT", b"iCCP", b"zTXt", b"iTXt", b"eXIf"}:
            raise _unsupported("Animated PNG and compressed/profile/EXIF metadata are not reviewed; use a plain texture export.")
        if kind not in {b"IHDR", b"IDAT", b"IEND", b"PLTE"} and not kind[0] & 32:
            raise _unsupported("Unknown critical PNG chunks are not supported.")
        if kind != b"IDAT":
            if length > READ_BYTES:
                raise invalid_argument("PNG metadata exceeds its per-chunk byte budget.")
            ancillary += length
            if ancillary > MAX_ANCILLARY_BYTES:
                raise invalid_argument("PNG metadata exceeds its cumulative byte budget.")
            if idat:
                idat_closed = True
        if (kind in {b"PLTE", b"tRNS", b"sRGB", b"gAMA", b"cHRM", b"pHYs", b"sBIT", b"bKGD", b"tIME"}
                and (kind in seen or (idat and kind not in {b"tIME"}))):
            raise invalid_argument("PNG metadata is duplicated or incorrectly ordered.")
        crc = zlib.crc32(kind)
        if kind == b"IDAT":
            if idat_closed or header is None or (header["color_type"] == 3 and palette is None):
                raise invalid_argument("PNG IDAT sequence/palette ordering is invalid.")
            idat = True
            remaining = length
            while remaining:
                data = reader.read(min(READ_BYTES, remaining))
                crc, remaining = zlib.crc32(data, crc), remaining-len(data)
                pending, again = data, True
                while pending or again:
                    reader.check()
                    try:
                        output = inflater.decompress(pending, READ_BYTES)
                    except zlib.error as exc:
                        raise invalid_argument("PNG IDAT zlib stream is invalid.") from exc
                    pending = inflater.unconsumed_tail
                    if inflater.unused_data:
                        raise invalid_argument("PNG IDAT contains trailing/concatenated zlib data.")
                    lines.feed(output)
                    again = len(output) == READ_BYTES
                    yield reader.progress("inflating_png", inflated_bytes=lines.received, expected_inflated_bytes=lines.expected)
        else:
            data = reader.read(length)
            crc = zlib.crc32(data, crc)
            if kind == b"IHDR":
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
                _dimensions(width, height)
                allowed = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
                if depth not in allowed.get(color, set()) or compression or filtering or interlace not in {0, 1}:
                    raise invalid_argument("PNG IHDR encoding parameters are invalid.")
                header = {"format": "PNG", "width": width, "height": height, "bit_depth": depth,
                          "color_type": color, "interlace": interlace}
                lines = Scanlines(width, height, channels[color], depth, interlace)
            elif kind == b"PLTE":
                if not length or length % 3 or length > 768 or header["color_type"] in {0, 4}:
                    raise invalid_argument("PNG palette is invalid for its color type.")
                palette = length//3
                if header["color_type"] == 3 and palette > 2**header["bit_depth"]:
                    raise invalid_argument("PNG palette exceeds its sample depth.")
            elif kind == b"tRNS":
                color = header["color_type"]
                if (color == 3 and (palette is None or not 0 < length <= palette)) or (color != 3 and length != {0: 2, 2: 6}.get(color, -1)):
                    raise invalid_argument("PNG transparency metadata is invalid for its color type.")
            elif kind == b"IEND":
                if length or reader.position+4 != reader.total or not idat or not inflater.eof or lines.received != lines.expected:
                    raise invalid_argument("PNG lacks complete scanlines/zlib termination or has invalid IEND/trailing data.")
            expected_lengths = {b"sRGB": 1, b"gAMA": 4, b"cHRM": 32, b"pHYs": 9, b"tIME": 7}
            if kind in expected_lengths and length != expected_lengths[kind]:
                raise invalid_argument("PNG standard metadata has an invalid length.")
            if kind == b"sRGB" and data[0] > 3:
                raise invalid_argument("PNG sRGB rendering intent is invalid.")
        if struct.unpack(">I", reader.read(4))[0] != crc & 0xffffffff:
            raise invalid_argument("PNG chunk checksum is invalid.")
        seen.add(kind)
        yield reader.progress()
        if kind == b"IEND":
            return {**header, "png_scanline_layout_verified": True, "pixel_contents_verified": False}
    raise invalid_argument("PNG exceeded the chunk budget or is missing IEND.")


def _attribute(attributes: dict, name: str, kind: str, length: int) -> bytes:
    value = attributes.get(name)
    if value is None or value[0] != kind or len(value[1]) != length:
        raise invalid_argument("EXR lacks a required, correctly typed fixed-size attribute.", attribute=name)
    return value[1]


def _exr(reader: Reader) -> Iterator[dict]:
    if reader.read(4) != struct.pack("<I", 20000630):
        raise invalid_argument("Texture is not an OpenEXR file.")
    if struct.unpack("<I", reader.read(4))[0] != 2:
        raise _unsupported("Reviewed EXR is version-2 single-part scanline data, without tiled/deep/multipart/long-name flags.")
    attributes = {}
    known = {"channels", "compression", "dataWindow", "displayWindow", "lineOrder", "pixelAspectRatio",
             "screenWindowCenter", "screenWindowWidth", "chromaticities", "bcbRole", "bcbAlphaMode",
             "comments", "owner", "capDate"}
    for _ in range(MAX_ATTRIBUTES+1):
        name = reader.cstring(allow_empty=True)
        if not name:
            break
        if name in attributes:
            raise invalid_argument("EXR contains a duplicate attribute.")
        if name not in known:
            raise _unsupported("This EXR attribute is not reviewed; use a plain RGBA FLOAT texture export.")
        kind, length = reader.cstring(), struct.unpack("<I", reader.read(4))[0]
        if length > MAX_ATTRIBUTE_BYTES or reader.position+length > MAX_HEADER_BYTES or len(attributes) >= MAX_ATTRIBUTES:
            raise invalid_argument("EXR attribute/header budget exceeded.")
        attributes[name] = kind, reader.read(length)
        yield reader.progress("reading_exr_header")
    else:
        raise invalid_argument("EXR attribute count exceeds its budget.")
    if reader.position > MAX_HEADER_BYTES:
        raise invalid_argument("EXR header exceeds its byte budget.")
    channels = attributes.get("channels")
    if channels is None or channels[0] != "chlist":
        raise invalid_argument("EXR needs a correctly typed channel list.")
    offset, data = 0, channels[1]
    for expected in (b"A", b"B", b"G", b"R"):
        if data[offset:offset+2] != expected+b"\0" or len(data) < offset+18:
            raise _unsupported("Reviewed EXR needs exactly the alphabetic A/B/G/R channels.")
        sample, linear, reserved, x, y = struct.unpack_from("<iB3sii", data, offset+2)
        if sample != 2 or linear not in {0, 1} or reserved != b"\0\0\0" or x != 1 or y != 1:
            raise _unsupported("Reviewed EXR needs FLOAT32 channels with unit sampling and standard reserved bits.")
        offset += 18
    if data[offset:] != b"\0":
        raise _unsupported("Additional EXR channels/layers are not reviewed.")
    if _attribute(attributes, "compression", "compression", 1) != b"\0":
        raise _unsupported("EXR compression is not reviewed; choose uncompressed FLOAT RGBA.")
    window = _attribute(attributes, "dataWindow", "box2i", 16)
    x0, y0, x1, y1 = struct.unpack("<iiii", window)
    if x0 or y0 or x1 < 0 or y1 < 0 or _attribute(attributes, "displayWindow", "box2i", 16) != window:
        raise _unsupported("Reviewed EXR requires equal zero-origin data/display windows without crop/overscan.")
    width, height = x1+1, y1+1
    _dimensions(width, height)
    if _attribute(attributes, "lineOrder", "lineOrder", 1) != b"\0":
        raise _unsupported("Reviewed EXR requires increasing scanline order.")
    for name, kind, count in (("pixelAspectRatio", "float", 1), ("screenWindowCenter", "v2f", 2), ("screenWindowWidth", "float", 1)):
        floats = struct.unpack("<"+"f"*count, _attribute(attributes, name, kind, count*4))
        if not all(math.isfinite(value) for value in floats) or (count == 1 and floats[0] <= 0):
            raise invalid_argument("EXR aspect/screen metadata must be finite and valid.")
    chromaticities = None
    if "chromaticities" in attributes:
        chromaticities = struct.unpack("<8f", _attribute(attributes, "chromaticities", "chromaticities", 32))
        if any(not math.isfinite(a) or abs(a-b) > 1e-5 for a, b in zip(chromaticities, REC709_CHROMATICITIES, strict=True)):
            raise _unsupported("Non-Rec.709 EXR chromaticities need explicit reviewed color conversion; not guessed.")
    hints = {}
    for name in ("bcbRole", "bcbAlphaMode", "comments", "owner", "capDate"):
        if name in attributes:
            kind, data = attributes[name]
            if kind != "string":
                raise invalid_argument("EXR text metadata must use a bounded string attribute.")
            if name.startswith("bcb"):
                allowed = {"COLOR", "DATA"} if name == "bcbRole" else {"STRAIGHT", "PREMUL", "CHANNEL_PACKED", "NONE"}
                if data not in {v.encode("ascii") for v in allowed}:
                    raise invalid_argument("EXR bridge interpretation hint is invalid.")
                hints[name] = data.decode("ascii")
    start, stride = reader.position+height*8, 8+width*16
    if start+height*stride != reader.total:
        raise invalid_argument("EXR byte length does not match the complete reviewed scanline layout.")
    table = reader.read(height*8)
    if any(value != start+index*stride for index, (value,) in enumerate(struct.iter_unpack("<Q", table))):
        raise invalid_argument("EXR offset table is duplicated, overlapping, non-contiguous or out of bounds.")
    for row in range(height):
        if struct.unpack("<ii", reader.read(8)) != (row, width*16):
            raise invalid_argument("EXR scanline coordinates or byte counts do not match their verified layout.")
        remaining = width*16
        while remaining:
            count = min(remaining, READ_BYTES)
            reader.read(count)
            remaining -= count
            yield reader.progress("reading_exr_pixels")
    return {"format": "EXR", "width": width, "height": height, "bit_depth": 32,
            "channels": ["A", "B", "G", "R"], "compression": "NONE", "chromaticities": list(chromaticities) if chromaticities else None,
            "interpretation_hints": hints, "pixel_contents_verified": False}


def _jpeg(reader: Reader) -> Iterator[dict]:
    if reader.read(2) != b"\xff\xd8":
        raise invalid_argument("Texture is not a JPEG file.")
    header = None
    for _ in range(MAX_JPEG_MARKERS):
        if reader.read(1) != b"\xff":
            raise invalid_argument("JPEG marker header is malformed.")
        for _fill in range(64):
            marker = reader.read(1)[0]
            if marker != 255:
                break
        else:
            raise _unsupported("JPEG marker padding exceeds its reviewed budget.")
        if marker in {0xd8, 0xd9, 1} or 0xd0 <= marker <= 0xd7:
            raise invalid_argument("Unexpected standalone JPEG header marker.")
        length = struct.unpack(">H", reader.read(2))[0]
        if length < 2:
            raise invalid_argument("JPEG segment length is invalid.")
        payload = reader.read(length-2)
        if marker in {0xc0, 0xc2}:
            if len(payload) < 6:
                raise invalid_argument("JPEG frame header is truncated.")
            depth, height, width, components = struct.unpack_from(">BHHB", payload)
            _dimensions(width, height)
            if depth != 8 or components not in {1, 3, 4} or length != 8+components*3:
                raise _unsupported("Only reviewed 8-bit baseline/progressive JPEG frames are supported.")
            header = {"format": "JPEG", "width": width, "height": height, "bit_depth": 8,
                      "pixel_contents_verified": False, "jpeg_codestream_verified": False}
            break
        if marker in {0xc1, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}:
            raise _unsupported("This JPEG frame encoding is not reviewed.")
        if marker == 0xda:
            raise invalid_argument("JPEG scan precedes a reviewed frame header.")
        yield reader.progress("reading_jpeg_header")
    if header is None:
        raise invalid_argument("JPEG has no reviewed frame header within the marker budget.")
    while reader.position < reader.total:
        reader.read(min(READ_BYTES, reader.total-reader.position))
        yield reader.progress()
    return header


def preflight_stream(stream: BinaryIO, suffix: str, file_bytes: int, *, check: Callable[[], None]) -> Iterator[dict]:
    reader = Reader(stream, file_bytes, check)
    parsers = {".png": _png, ".jpg": _jpeg, ".jpeg": _jpeg, ".exr": _exr}
    parser = parsers.get(suffix.lower())
    if parser is None:
        raise _unsupported("This texture file format is not reviewed.")
    header = yield from parser(reader)
    reader.check()
    if reader.position != file_bytes:
        raise invalid_argument("Texture preflight did not consume the complete file.")
    return {**header, "file_bytes": file_bytes, "file_sha256": reader.digest.hexdigest(),
            "streaming_preflight": True, "maximum_read_bytes": READ_BYTES}
