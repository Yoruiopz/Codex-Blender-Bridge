"""Standard-library preflight for explicitly approved, bounded PNG/JPEG texture files."""

from __future__ import annotations

import hashlib
import os
import stat
import struct
import zlib
from pathlib import Path

from .errors import BridgeError, ErrorCode, invalid_argument

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_DIMENSION = 8192
MAX_PIXELS = 16_777_216


def _local_drive(path: Path) -> bool:
    if os.name != "nt":
        return True
    import ctypes

    return ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) in {2, 3, 5, 6}


def _absolute(raw: str, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 4096 or any(ord(c) < 32 for c in raw):
        raise invalid_argument(f"{label} must be a non-empty bounded path without control characters.")
    try:
        raw.encode("utf-8")
    except UnicodeError as exc:
        raise invalid_argument(f"{label} must be valid UTF-8 text.") from exc
    if raw.startswith(("\\\\", "//")):
        raise invalid_argument(f"{label} cannot be a UNC/network or Blender-relative path.")
    candidate = Path(raw)
    if not candidate.is_absolute() or ".." in candidate.parts or candidate.is_reserved():
        raise invalid_argument(f"{label} must be an absolute local path without traversal/device components.")
    if any(":" in part for part in candidate.parts[1:]) or not _local_drive(candidate):
        raise invalid_argument(f"{label} cannot use alternate streams or a mapped network drive.")
    return candidate


def approved_file(raw: str, root_raw: str) -> Path:
    """Call only AFTER ACCESS_EXTERNAL_FILES authorization; resolution probes the filesystem."""
    if not root_raw:
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "Choose an approved texture folder in Blender's bridge settings first.")
    root_candidate, candidate = _absolute(root_raw, "Texture folder"), _absolute(raw, "Texture file")
    try:
        root = root_candidate.resolve(strict=True)
        if root == Path(root.anchor) or not root.is_dir():
            raise invalid_argument("The approved texture folder must be an existing subdirectory, not a volume root.")
        target = candidate.resolve(strict=True)
        if not target.is_relative_to(root):
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Texture file is outside Blender's approved texture folder.")
        if os.name != "nt" and len(target.parts) > 1 and target.parts[1] in {"dev", "proc", "sys"}:
            raise invalid_argument("Device/process files cannot be texture sources.")
        if not _local_drive(target) or not stat.S_ISREG(target.stat().st_mode):
            raise invalid_argument("Texture source must be a regular local file.")
    except (OSError, RuntimeError) as exc:
        raise invalid_argument("Texture source or approved folder could not be resolved.") from exc
    if target.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed texture loading supports PNG and 8-bit JPEG only.")
    return target


def _dimensions(width: int, height: int) -> None:
    if not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION or width * height > MAX_PIXELS:
        raise invalid_argument("Texture exceeds dimension/pixel limits.", width=width, height=height,
                               maximum_dimension=MAX_DIMENSION, maximum_pixels=MAX_PIXELS)


def bitmap_header(data: bytes, suffix: str) -> dict:
    if suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This bitmap format is not reviewed.")
    if suffix.lower() == ".png":
        if len(data) < 45 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise invalid_argument("Texture is not a complete PNG header.")
        offset, chunks, header, ended, image_data = 8, 0, None, False, False
        while offset + 12 <= len(data):
            length = struct.unpack_from(">I", data, offset)[0]
            kind = data[offset + 4:offset + 8]
            end = offset + 12 + length
            if end > len(data) or chunks >= 4096:
                raise invalid_argument("PNG chunks are truncated or exceed the chunk budget.")
            payload = data[offset + 8:offset + 8 + length]
            expected = struct.unpack_from(">I", data, offset + 8 + length)[0]
            if zlib.crc32(kind + payload) & 0xffffffff != expected:
                raise invalid_argument("PNG chunk checksum is invalid.")
            if chunks == 0:
                if kind != b"IHDR" or length != 13:
                    raise invalid_argument("PNG must begin with one standard IHDR.")
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
                _dimensions(width, height)
                allowed = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
                if depth not in allowed.get(color, set()) or compression or filtering or interlace not in {0, 1}:
                    raise invalid_argument("PNG header uses invalid encoding parameters.")
                header = {"format": "PNG", "width": width, "height": height, "bit_depth": depth}
            elif kind == b"IHDR":
                raise invalid_argument("PNG contains duplicate IHDR chunks.")
            if kind in {b"acTL", b"fcTL", b"fdAT"}:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animated PNG textures are not yet supported.")
            # Do not feed unbounded compressed metadata to native profile/text parsers.
            if kind in {b"iCCP", b"zTXt", b"iTXt"}:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "PNG iCCP/zTXt/iTXt metadata is not yet reviewed; use a plain PNG export.")
            if kind == b"IDAT" and length:
                image_data = True
            if kind == b"IEND":
                if length or end != len(data):
                    raise invalid_argument("PNG has invalid IEND/trailing data.")
                ended = True
                break
            offset, chunks = end, chunks + 1
        if not ended or header is None or not image_data:
            raise invalid_argument("PNG is missing image data or its final chunk.")
        return header
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise invalid_argument("Texture is not a JPEG header.")
    offset, segments = 2, 0
    while offset < len(data) and segments < 4096:
        if data[offset] != 255:
            raise invalid_argument("JPEG marker header is malformed.")
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xd8, 0xd9, 0x01} or 0xd0 <= marker <= 0xd7:
            raise invalid_argument("Unexpected standalone JPEG header marker.")
        if offset + 2 > len(data):
            break
        length = struct.unpack_from(">H", data, offset)[0]
        if length < 2 or offset + length > len(data):
            raise invalid_argument("JPEG segment is truncated.")
        if marker in {0xc0, 0xc2}:
            if length < 8:
                raise invalid_argument("JPEG frame header is truncated.")
            depth, height, width, components = struct.unpack_from(">BHHB", data, offset + 2)
            _dimensions(width, height)
            if depth != 8 or components not in {1, 3, 4} or length != 8 + components * 3:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Only reviewed 8-bit baseline/progressive JPEG frames are supported.")
            return {"format": "JPEG", "width": width, "height": height, "bit_depth": depth}
        if marker in {0xc1, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This JPEG frame encoding is not reviewed.")
        if marker == 0xda:
            break
        offset += length
        segments += 1
    raise invalid_argument("A reviewed JPEG frame header was not found.")


def preflight_file(raw: str, root: str) -> tuple[Path, dict]:
    path = approved_file(raw, root)
    try:
        before = path.stat()
        if not 0 < before.st_size <= MAX_FILE_BYTES:
            raise invalid_argument("Texture file exceeds the 32 MiB limit or is empty.")
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        after = path.stat()
    except OSError as exc:
        raise invalid_argument("Texture file could not be read.") from exc
    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns
    if len(data) != before.st_size or identity(before) != identity(after):
        raise invalid_argument("Texture file changed during preflight; retry only after inspecting its source.")
    header = bitmap_header(data, path.suffix)
    return path, {**header, "file_bytes": len(data), "file_sha256": hashlib.sha256(data).hexdigest(),
                  "_identity": identity(after)}
