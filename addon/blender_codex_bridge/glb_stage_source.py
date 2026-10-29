"""Fixed-limit GLB source snapshots; no Blender, staging or write authority.

The caller must establish current inspect/external-file permission before entry.
The check callback is a trusted cancellation/grant signal, never authorization
by itself. Descriptor-relative no-follow traversal is currently required; other
platforms fail closed rather than receiving an unqualified path fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .errors import BridgeError, ErrorCode, invalid_argument
from .image_files import _absolute

MAX_BYTES = 8 * 1024**2
BLOCK_BYTES = 65536
MIN_BYTES = 28
MAX_PATH_BYTES = 4096
MAX_ANCESTRY_TEXT_BYTES = 128 * 1024
MAX_METADATA_BYTES = 512 * 1024
MAX_IDENTITY = 2**64 - 1


def _path_text(value: str) -> None:
    try:
        valid = (type(value) is str and 1 <= len(value.encode("utf8")) <= MAX_PATH_BYTES
                 and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    except UnicodeError:
        valid = False
    if not valid:
        raise invalid_argument("GLB source paths must be control-free bounded UTF-8 strings.")


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _regular(value: os.stat_result) -> None:
    if not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise invalid_argument("GLB source must be an ordinary file, never a link/device.")
    if not MIN_BYTES <= value.st_size <= MAX_BYTES:
        raise invalid_argument("GLB source must contain 28 bytes through 8 MiB.")


def _directory(value: os.stat_result) -> tuple[int, int]:
    if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise invalid_argument("GLB source ancestry cannot contain links or reparse points.")
    return value.st_dev, value.st_ino


def _pins(path: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple((str(p), *_directory(p.lstat())) for p in (*reversed(path.parents), path))


def _open_directory(path: Path, check: Callable[[], None]) -> int:
    """Return one owned directory fd; close every intermediate fd on all exits."""
    if (os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "GLB source requires qualified descriptor-relative no-follow traversal.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    check()
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            check()
            following = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        _directory(os.fstat(descriptor))
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@dataclass(frozen=True, slots=True)
class GLBSource:
    path: str
    approved_root: str
    ancestry: tuple[tuple[str, int, int], ...]
    file_identity: tuple[int, int, int, int]
    payload: bytes
    sha256: str

    def validate(self) -> None:
        """Pure integrity, not live path validation or a permission grant."""
        _path_text(self.path)
        _path_text(self.approved_root)
        path, root = Path(self.path), Path(self.approved_root)
        expected = tuple(str(p) for p in (*reversed(path.parent.parents), path.parent))
        if (type(self.path) is not str or type(self.approved_root) is not str
                or not path.is_absolute() or not root.is_absolute()
                or str(path) != self.path or str(root) != self.approved_root
                or root == Path(root.anchor) or not path.is_relative_to(root)
                or path.suffix.lower() != ".glb"
                or type(self.payload) is not bytes
                or not MIN_BYTES <= len(self.payload) <= MAX_BYTES
                or type(self.file_identity) is not tuple or len(self.file_identity) != 4
                or any(type(v) is not int for v in self.file_identity)
                or not 0 <= self.file_identity[0] <= MAX_IDENTITY
                or not 0 < self.file_identity[1] <= MAX_IDENTITY
                or self.file_identity[2] != len(self.payload)
                or not -(2**63) <= self.file_identity[3] < 2**63
                or type(self.ancestry) is not tuple or not 1 <= len(self.ancestry) <= 1024
                or any(type(row) is not tuple or len(row) != 3 or type(row[0]) is not str
                       or any(type(v) is not int for v in row[1:])
                       or not 0 <= row[1] <= MAX_IDENTITY or not 0 < row[2] <= MAX_IDENTITY
                       for row in self.ancestry)
                or tuple(row[0] for row in self.ancestry) != expected
                or sum(len(row[0].encode("utf8")) for row in self.ancestry) > MAX_ANCESTRY_TEXT_BYTES
                or type(self.sha256) is not str or len(self.sha256) != 64
                or self.sha256 != hashlib.sha256(self.payload).hexdigest()):
            raise invalid_argument("GLB source snapshot integrity changed.")

    def metadata_bytes(self) -> bytes:
        """Canonical bounded source metadata; includes ancestry, not payload."""
        self.validate()
        value = {"path": self.path, "approved_root": self.approved_root,
                 "ancestry": self.ancestry, "file_identity": self.file_identity,
                 "sha256": self.sha256}
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_METADATA_BYTES:
            raise invalid_argument("GLB source metadata exceeds its fixed byte budget.")
        return raw

    @property
    def accounted_bytes(self) -> int:
        metadata = self.metadata_bytes()
        return len(self.payload) + len(metadata)

    def verify(self, approved_root: str, check: Callable[[], None] = lambda: None) -> None:
        self.validate()
        current = read_glb_source(self.path, approved_root, check)
        if current != self:
            raise invalid_argument("GLB source identity, approval or complete bytes changed; preview again.")

    def proof(self) -> dict:
        self.validate()
        return {"filepath": self.path, "approved_source_directory": self.approved_root,
                "file_identity": list(self.file_identity), "file_bytes": len(self.payload),
                "file_sha256": self.sha256, "source_write_performed": False}


def read_glb_source(filepath: str, approved_root: str,
                    check: Callable[[], None] = lambda: None) -> GLBSource:
    """Read at most 8 MiB, checking every <=64 KiB; never follow path links.

    No GLB parsing occurs here. The unchanged pure planner must independently
    validate these complete bytes before a future backend can use them. Identity
    checks detect races; this is not a sandbox against hostile filesystem actors.
    """
    check()
    if type(filepath) is not str or type(approved_root) is not str:
        raise invalid_argument("GLB source and approval must be exact strings.")
    if not approved_root:
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "Choose an Approved Asset Source Folder first.")
    _path_text(filepath)
    _path_text(approved_root)
    root, path = _absolute(approved_root, "Asset source folder"), _absolute(filepath, "GLB source")
    if root == Path(root.anchor) or not path.is_relative_to(root):
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "GLB source is outside an approved local subdirectory.")
    if path.suffix.lower() != ".glb":
        raise invalid_argument("Structured GLB source requires the .glb extension.")
    if len(path.parent.parts) > 1024:
        raise invalid_argument("GLB source ancestry exceeds its fixed budget.")
    for candidate in (root, path):
        if any(PureWindowsPath(part).is_reserved() or part.endswith((".", " "))
               for part in candidate.parts[1:]):
            raise invalid_argument("GLB source cannot contain reserved or ambiguous path components.")
    if len(path.parts) > 1 and path.parts[1] in {"dev", "proc", "sys"}:
        raise invalid_argument("Device/process paths cannot be GLB sources.")
    directory = descriptor = None
    try:
        check()
        ancestry = _pins(path.parent)
        if (len(ancestry) > 1024
                or sum(len(row[0].encode("utf8")) for row in ancestry) > MAX_ANCESTRY_TEXT_BYTES):
            raise invalid_argument("GLB source ancestry exceeds its fixed budget.")

        def validate() -> None:
            if (_pins(path.parent) != ancestry or (directory is not None
                    and _directory(os.fstat(directory)) != ancestry[-1][1:])):
                raise invalid_argument("GLB source ancestry changed during reading.")

        directory = _open_directory(path.parent, check)
        validate()
        check()
        validate()
        before = path.lstat()
        _regular(before)
        flags = (os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        descriptor = os.open(path.name, flags, dir_fd=directory)
        first = os.fstat(descriptor)
        _regular(first)
        if _identity(first) != _identity(before):
            raise invalid_argument("GLB source changed while its read handle opened.")
        blocks, count = [], 0
        while count < first.st_size:
            check()
            validate()
            current = path.lstat()
            _regular(current)
            if (_identity(os.fstat(descriptor)) != _identity(first)
                    or _identity(current) != _identity(first)):
                raise invalid_argument("GLB source changed during complete-byte reading.")
            block = os.read(descriptor, min(BLOCK_BYTES, first.st_size - count))
            if not block:
                raise invalid_argument("GLB source became incomplete while reading.")
            blocks.append(block)
            count += len(block)
        check()
        validate()
        final, current = os.fstat(descriptor), path.lstat()
        _regular(current)
        if _identity(final) != _identity(first) or _identity(current) != _identity(first):
            raise invalid_argument("GLB source changed during complete-byte reading.")
        payload = b"".join(blocks)
        snapshot = GLBSource(str(path), str(root), ancestry, _identity(first), payload,
                             hashlib.sha256(payload).hexdigest())
        snapshot.validate()
        return snapshot
    except OSError as cause:
        raise invalid_argument("GLB source requires readable ordinary local file/directory ancestry.") from cause
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)
