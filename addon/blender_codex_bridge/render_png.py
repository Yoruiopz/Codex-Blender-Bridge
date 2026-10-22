"""Bounded validation of our native renderer's PNG bytes, not an image importer.

Native render metadata is checksum-verified opaque data and is never decoded as
EXIF/ICC/text. Image-source admission keeps its separate stricter metadata policy.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

from .errors import invalid_argument

MAX_PIXELS = 1_048_576
MAX_BYTES = 64 * 1024 * 1024
MAX_METADATA = 256 * 1024
OPAQUE_METADATA = frozenset(
    {
        b"cHRM",
        b"gAMA",
        b"sRGB",
        b"pHYs",
        b"tEXt",
        b"zTXt",
        b"iTXt",
        b"eXIf",
        b"iCCP",
        b"cICP",
        b"mDCv",
        b"cLLi",
        b"oFFs",
    }
)


def verify(path: Path, check: Callable[[], None]) -> dict:
    check()
    expected_bytes = path.stat().st_size
    if not 0 < expected_bytes <= MAX_BYTES:
        raise invalid_argument("Native PNG exceeds its file bound.")
    with path.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            raise invalid_argument("Native render did not produce PNG bytes.")
        digest, rows_digest = hashlib.sha256(), hashlib.sha256()
        digest.update(b"\x89PNG\r\n\x1a\n")
        header = None
        image_started = image_ended = ended = False
        decoder = zlib.decompressobj()
        decoded = metadata = rows = 0
        row = bytearray()
        chunks = 0
        while not ended:
            check()
            raw = stream.read(8)
            if len(raw) != 8 or chunks >= 4096:
                raise invalid_argument("Native PNG chunks are truncated or exceed their budget.")
            length, kind = struct.unpack(">I4s", raw)
            if length > MAX_BYTES:
                raise invalid_argument("Native PNG chunk exceeds its byte budget.")
            if kind not in {b"IHDR", b"IDAT", b"IEND"} | OPAQUE_METADATA:
                raise invalid_argument(
                    "Native PNG contains an unreviewed chunk.",
                    chunk=kind.decode("ascii", errors="replace"),
                )
            if kind in OPAQUE_METADATA:
                metadata += length
                if metadata > MAX_METADATA:
                    raise invalid_argument("Native PNG metadata exceeds 256 KiB.")
            body = stream.read(length)
            crc = stream.read(4)
            if (
                len(body) != length
                or len(crc) != 4
                or zlib.crc32(kind + body) & 0xFFFFFFFF != struct.unpack(">I", crc)[0]
            ):
                raise invalid_argument("Native PNG chunk is truncated or has an invalid checksum.")
            digest.update(raw + body + crc)
            if header is None:
                if kind != b"IHDR" or length != 13:
                    raise invalid_argument("Native PNG must begin with one standard IHDR.")
                width, height, depth, color, compression, filtering, interlace = struct.unpack(
                    ">IIBBBBB", body
                )
                if (
                    not 0 < width * height <= MAX_PIXELS
                    or not width
                    or not height
                    or depth not in {8, 16}
                    or color not in {0, 2, 4, 6}
                    or compression
                    or filtering
                    or interlace
                ):
                    raise invalid_argument(
                        "Native PNG encoding, dimensions or pixel budget is unreviewed."
                    )
                components = {0: 1, 2: 3, 4: 2, 6: 4}[color]
                row_size = 1 + width * components * (depth // 8)
                expected_decoded = row_size * height
                header = {"width": width, "height": height, "bit_depth": depth, "color_type": color}
            elif kind == b"IHDR":
                raise invalid_argument("Native PNG contains a duplicate IHDR.")
            elif kind == b"IDAT":
                if image_ended:
                    raise invalid_argument("Native PNG image-data chunks must be consecutive.")
                image_started = True
                try:
                    data = decoder.decompress(body, expected_decoded + 1 - decoded)
                except zlib.error as error:
                    raise invalid_argument(
                        "Native PNG image-data deflate stream is invalid."
                    ) from error
                decoded += len(data)
                if decoded > expected_decoded or decoder.unconsumed_tail or decoder.unused_data:
                    raise invalid_argument(
                        "Native PNG image-data stream exceeds its exact decoded size."
                    )
                rows_digest.update(data)
                row.extend(data)
                complete = len(row) // row_size
                for index in range(complete):
                    if index % 1024 == 0:
                        check()
                    if row[index * row_size] > 4:
                        raise invalid_argument("Native PNG uses an invalid row filter.")
                del row[: complete * row_size]
                rows += complete
            elif kind == b"IEND":
                if (
                    length
                    or not image_started
                    or not decoder.eof
                    or decoded != expected_decoded
                    or rows != height
                    or row
                ):
                    raise invalid_argument(
                        "Native PNG has incomplete image data or an invalid end marker."
                    )
                ended = True
            elif image_started:
                image_ended = True
            chunks += 1
        if stream.read(1) or stream.tell() != expected_bytes:
            raise invalid_argument("Native PNG has trailing or changed bytes.")
    check()
    return {
        **header,
        "file_sha256": digest.hexdigest(),
        "file_bytes": expected_bytes,
        "encoded_png_verified": True,
        "decoded_scanline_bytes": decoded,
        "decoded_scanline_sha256": rows_digest.hexdigest(),
        "opaque_metadata_bytes": metadata,
    }
