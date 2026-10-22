"""Approved read-only sources and private immutable-by-contract native input copies.

No user output paths or source writes. Identity/hash checks are race detection,
not an OS sandbox against other processes or arbitrary installed native handlers.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .errors import BridgeError, ErrorCode, invalid_argument
from .image_files import _absolute, _local_drive
from .texture_staging import _ancestors, _directory_id

MAX_BYTES = 64 * 1024 * 1024
BLOCK = 65536


def _identity(value: os.stat_result) -> tuple:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _regular(value: os.stat_result) -> None:
    if not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise invalid_argument("Asset input must be an ordinary file, never a link/reparse point.")


def _read(
    path: Path, check: Callable[[], None], validate: Callable[[], None] = lambda: None
) -> tuple[bytes, tuple]:
    check()
    validate()
    before = path.lstat()
    _regular(before)
    if not 1 <= before.st_size <= MAX_BYTES:
        raise invalid_argument("Asset source must contain 1 byte through 64 MiB.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        first = os.fstat(descriptor)
        _regular(first)
        if _identity(first) != _identity(before):
            raise invalid_argument("Asset source changed while its read handle opened.")
        blocks, count = [], 0
        while True:
            check()
            validate()
            block = os.read(descriptor, min(BLOCK, MAX_BYTES + 1 - count))
            if not block:
                break
            blocks.append(block)
            count += len(block)
            if count > MAX_BYTES:
                raise invalid_argument("Asset source grew beyond its byte budget.")
        final = os.fstat(descriptor)
        current = path.lstat()
        _regular(current)
        if (
            _identity(first) != _identity(final)
            or _identity(current) != _identity(first)
            or count != first.st_size
        ):
            raise invalid_argument("Asset source changed during complete-byte reading.")
        return b"".join(blocks), _identity(first)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class SourceSnapshot:
    path: Path
    root: Path
    ancestry: tuple
    file_identity: tuple
    payload: bytes
    sha256: str

    def verify(self, approved_root: str, check: Callable[[], None] = lambda: None) -> None:
        current = read_source(str(self.path), self.path.suffix[1:].upper(), approved_root, check)
        if (
            current.root != self.root
            or current.ancestry != self.ancestry
            or current.file_identity != self.file_identity
            or current.sha256 != self.sha256
        ):
            raise invalid_argument(
                "Approved asset source identity or complete bytes changed; preview again."
            )

    def proof(self) -> dict:
        return {
            "filepath": str(self.path),
            "approved_source_directory": str(self.root),
            "file_identity": list(self.file_identity),
            "file_bytes": len(self.payload),
            "file_sha256": self.sha256,
        }


def read_source(
    filepath: str, format: str, approved_root: str, check: Callable[[], None] = lambda: None
) -> SourceSnapshot:
    """Caller must gate ACCESS_EXTERNAL_FILES before any path probes or callbacks."""
    check()
    if not approved_root:
        raise BridgeError(
            ErrorCode.PERMISSION_DENIED,
            "Choose a separate Approved Asset Source Folder in Blender first.",
        )
    if format not in ("GLB", "FBX"):
        raise invalid_argument("Asset source format must be GLB or FBX.")
    root, path = _absolute(approved_root, "Asset source folder"), _absolute(filepath, "Asset input")
    if path.suffix.lower() != "." + format.lower():
        raise invalid_argument("Asset source extension must match its declared format.")
    for current in (root, path):
        if any(
            PureWindowsPath(part).is_reserved() or part.endswith((".", " "))
            for part in current.parts[1:]
        ):
            raise invalid_argument(
                "Asset input cannot use reserved devices or trailing dots/spaces."
            )
    try:
        pins = tuple((str(parent), _directory_id(parent)) for parent in _ancestors(path.parent))
        root_pins = tuple((str(parent), _directory_id(parent)) for parent in _ancestors(root))
        resolved_root, resolved_path = root.resolve(strict=True), path.resolve(strict=True)
        if resolved_root == Path(resolved_root.anchor) or not _local_drive(resolved_root):
            raise invalid_argument(
                "Approved asset source must be an ordinary local subdirectory, not a volume root."
            )
        if not resolved_path.is_relative_to(resolved_root):
            raise BridgeError(
                ErrorCode.PERMISSION_DENIED,
                "Asset source is outside the separately approved READ folder.",
            )
        if (
            os.name != "nt"
            and len(resolved_path.parts) > 1
            and resolved_path.parts[1] in ("dev", "proc", "sys")
        ):
            raise invalid_argument("Device/process paths cannot be asset sources.")

        def validate():
            if pins != tuple(
                (str(parent), _directory_id(parent)) for parent in _ancestors(path.parent)
            ) or root_pins != tuple(
                (str(parent), _directory_id(parent)) for parent in _ancestors(root)
            ):
                raise invalid_argument("Asset source ancestry changed during read.")
            if (
                root.resolve(strict=True) != resolved_root
                or path.parent.resolve(strict=True) / path.name != resolved_path
            ):
                raise invalid_argument("Approved source confinement changed during reading.")

        payload, file_identity = _read(path, check, validate)
        validate()
        return SourceSnapshot(
            path,
            resolved_root,
            (pins, root_pins),
            file_identity,
            payload,
            hashlib.sha256(payload).hexdigest(),
        )
    except OSError as error:
        raise invalid_argument(
            "Asset source must be a readable, existing ordinary local file."
        ) from error


class OwnedInput:
    """Owned internal source copy, with conservative non-recursive cleanup."""

    def __init__(self, source: SourceSnapshot):
        self.source = source
        self.directory: Path | None = None
        self.path: Path | None = None
        self.directory_identity: tuple | None = None
        self.file_identity: tuple | None = None
        self.cleanup_status = "not_created"
        self.written_bytes = 0

    def create(self, check: Callable[[], None]) -> None:
        check()
        parent = Path(tempfile.gettempdir()).resolve(strict=True)
        if parent.is_relative_to(self.source.root):
            raise invalid_argument(
                "Internal native input staging must be outside the approved READ source folder."
            )
        self.directory = Path(tempfile.mkdtemp(prefix="blender-codex-input-", dir=parent))
        self.directory_identity = _directory_id(self.directory)
        self.cleanup_status = "retained"
        os.chmod(self.directory, 0o700)
        self.path = self.directory / ("input" + self.source.path.suffix.lower())
        descriptor = os.open(
            self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600
        )
        try:
            self.file_identity = _identity(os.fstat(descriptor))
            for offset in range(0, len(self.source.payload), BLOCK):
                check()
                block = memoryview(self.source.payload)[offset : offset + BLOCK]
                while block:
                    count = os.write(descriptor, block)
                    if not count:
                        raise OSError("No progress writing owned input.")
                    self.written_bytes += count
                    block = block[count:]
            os.fsync(descriptor)
            self.file_identity = _identity(os.fstat(descriptor))
        finally:
            # Capture even partial owned writes so cleanup can delete only its own
            # unchanged resource; errors never adopt a later path replacement.
            try:
                self.file_identity = _identity(os.fstat(descriptor))
            finally:
                os.close(descriptor)
        self.verify(check)

    def _owned(self) -> None:
        if (
            self.directory is None
            or self.path is None
            or _directory_id(self.directory) != self.directory_identity
        ):
            raise invalid_argument("Private import input directory ownership changed.")
        if set(self.directory.iterdir()) != {self.path}:
            raise invalid_argument(
                "Private import input gained unexpected entries; cleanup is refused."
            )
        current = self.path.lstat()
        _regular(current)
        if _identity(current) != self.file_identity:
            raise invalid_argument("Private import input file identity changed.")

    def verify(self, check: Callable[[], None] = lambda: None) -> None:
        check()
        self._owned()
        payload, identity = _read(self.path, check, self._owned)
        if (
            identity != self.file_identity
            or hashlib.sha256(payload).hexdigest() != self.source.sha256
        ):
            raise invalid_argument(
                "Private native import input differs from validated complete source bytes."
            )
        self._owned()

    def cleanup(self, check: Callable[[], None]) -> None:
        if self.directory is None:
            return
        try:
            check()
            self._owned()
            payload, identity = _read(self.path, lambda: None, self._owned)
            if (
                identity != self.file_identity
                or payload != self.source.payload[: self.written_bytes]
            ):
                raise invalid_argument("Owned private input content changed; cleanup is refused.")
            # No callbacks between exact ownership validation and deletion.
            self.path.unlink()
            self.directory.rmdir()
            self.cleanup_status = "removed"
        except Exception:
            self.cleanup_status = "retained_ownership_or_consent_not_proven"

    def evidence(self) -> dict:
        return {
            "internal_input_staging": True,
            "staging_cleanup": self.cleanup_status,
            "retained_staging_path": str(self.directory)
            if self.directory and self.cleanup_status != "removed"
            else None,
            "source_file_written": False,
            "user_output_file_written": False,
            "native_undo_removes_internal_staging": False,
            "input_sha256": self.source.sha256,
            "input_bytes": len(self.source.payload),
        }
