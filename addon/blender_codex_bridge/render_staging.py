"""One private native PNG output and owned atomic no-clobber publication.

Directory identity/pin checks are race detection, not a host/filesystem sandbox.
A failed or stopped request retains output when exact authorized cleanup cannot
be proved. Published files are never removed by cleanup or Blender undo.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .image_files import _absolute, _local_drive
from .preferences import get_preferences
from .render_png import verify as verify_png
from .texture_staging import _ancestors, _directory_id, _DirectoryPins
from .utils import require_blender

MAX_BYTES, READ_BYTES = 64 * 1024 * 1024, 1024 * 1024


def native_render_effects(boundary: Any) -> dict:
    return {
        "render_result_replaced": True
        if boundary.native_completed
        else None
        if boundary.native_started
        else False,
        "render_result_replacement_possible": bool(boundary.native_started),
    }


def _identity(path: Path) -> tuple:
    result = path.lstat()
    if not stat.S_ISREG(result.st_mode) or getattr(result, "st_file_attributes", 0) & 0x400:
        raise invalid_argument("Render output must be an unchanged ordinary file.")
    return result.st_dev, result.st_ino, result.st_size, result.st_mtime_ns


def _root() -> str:
    return _read_root()[0]


def _read_root() -> tuple[str, tuple]:
    """Native raw storage CAS, never the runtime StringProperty getter."""
    from . import preferences

    owner = get_preferences()
    if owner is None:
        return "", ("missing_preferences",)
    bpy = require_blender()
    canonical = getattr(preferences, "BlenderCodexBridgePreferences", None)
    if canonical is None or type(owner) is not canonical or owner.bl_rna != canonical.bl_rna:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Render paths require the canonical bridge preferences owner.",
        )
    prop = owner.bl_rna.properties.get("asset_directory")
    if (
        prop is None
        or prop.type != "STRING"
        or prop.is_readonly
        or not prop.is_runtime
        or prop.subtype != "DIR_PATH"
        or prop.default != ""
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Approved Asset Folder requires its reviewed bridge descriptor.",
        )
    # Missing storage means the declared empty default. A replaced RNA getter
    # cannot acquire authority or execute after the final grant provider.
    try:
        raw = bpy.types.bpy_struct.get(owner, "asset_directory", "")
    except TypeError as error:
        # Newer native AddonPreferences can keep runtime fields in system
        # properties, distinct from public IDProperties. No runtime getter
        # fallback is safe here; a reviewed raw-system API is separate work.
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "This Blender preferences owner has no reviewed raw Asset Folder storage reader.",
        ) from error
    if type(raw) is not str or len(raw) > 4096 or any(ord(c) < 32 for c in raw):
        raise invalid_argument(
            "Approved Asset Folder raw storage is not a bounded ordinary string."
        )
    try:
        if len(raw.encode("utf-8")) > 4096:
            raise invalid_argument("Approved Asset Folder exceeds its UTF-8 path bound.")
    except UnicodeError as error:
        raise invalid_argument("Approved Asset Folder has invalid Unicode storage.") from error
    return raw, (
        int(owner.as_pointer()),
        int(owner.bl_rna.as_pointer()),
        int(prop.as_pointer()),
        prop.type,
        bool(prop.is_runtime),
        bool(prop.is_readonly),
        prop.subtype,
        prop.default,
    )


def _approved(raw: str, root_raw: str) -> tuple[Path, tuple]:
    if not root_raw:
        raise BridgeError(
            ErrorCode.PERMISSION_DENIED,
            "Choose an Approved Asset Folder in Blender before external render output.",
        )
    root, target = _absolute(root_raw, "Asset folder"), _absolute(raw, "Render output")
    if target.suffix.lower() != ".png":
        raise invalid_argument("The reviewed render output requires an explicit .png extension.")
    for path in (root, target):
        if any(
            PureWindowsPath(part).is_reserved() or part.endswith((".", " "))
            for part in path.parts[1:]
        ):
            raise invalid_argument(
                "Render paths cannot use reserved devices or trailing dots/spaces."
            )
    try:
        resolved_root, parent = root.resolve(strict=True), target.parent.resolve(strict=True)
        if (
            resolved_root == Path(resolved_root.anchor)
            or not resolved_root.is_dir()
            or not parent.is_relative_to(resolved_root)
        ):
            raise invalid_argument(
                "Render output must be inside the approved ordinary local subdirectory."
            )
        if not _local_drive(parent) or (
            os.name != "nt" and len(parent.parts) > 1 and parent.parts[1] in {"dev", "proc", "sys"}
        ):
            raise invalid_argument("Render output needs an ordinary local directory.")
        ancestry = tuple(
            (str(p), _directory_id(p)) for p in (*_ancestors(root), *_ancestors(target.parent))
        )
    except OSError as error:
        raise invalid_argument("Render output needs existing ordinary local ancestry.") from error
    return parent / target.name, ancestry


class Staging:
    def __init__(self, boundary: Any, raw: str | None, *, overwrite: bool = False):
        self.boundary, self.raw, self.overwrite = boundary, raw, overwrite
        self.managed = raw is None
        self.root_raw = None
        self.root_descriptor = None
        self.root = self.path = self.directory = self.payload = None
        self.root_id = self.directory_id = self.payload_inode = self.sealed_identity = None
        self.pins = None
        self.sha256 = self.bytes = None
        self.png_proof = None
        self.published = self.attempted = self.verified = False
        self.publication_outcome_unknown = False
        self.cleanup_status = "not_created"
        boundary.check()
        if raw is not None:
            self.root_raw, self.root_descriptor = _read_root()
            self.path, self.ancestry = _approved(raw, self.root_raw)
            self.root = self.path.parent
            self.root_id = _directory_id(self.root)
            self._unused()
        else:
            self.ancestry = ()
        boundary.filesystem_checks.append(self.validate)

    def _unused(self) -> None:
        try:
            self.path.lstat()
        except FileNotFoundError:
            return
        if self.overwrite:
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Overwriting an existing render needs separate fingerprint-bound publication; no file was changed.",
            )
        raise invalid_argument("Render output already exists; no file was changed.")

    def validate(self) -> None:
        if self.raw is not None and (
            _read_root() != (self.root_raw, self.root_descriptor)
            or _approved(self.raw, self.root_raw) != (self.path, self.ancestry)
        ):
            raise invalid_argument(
                "Approved render path or ancestry changed; publication and cleanup are refused."
            )
        if self.root is not None and _directory_id(self.root) != self.root_id:
            raise invalid_argument("Render output parent identity changed.")
        if self.directory is not None and _directory_id(self.directory) != self.directory_id:
            raise invalid_argument("Private render staging identity changed.")
        if self.payload_inode is not None and _identity(self.payload)[:2] != self.payload_inode:
            raise invalid_argument("Private native render output identity changed.")

    def open(self) -> None:
        if self.root is None:
            self.boundary.check()
            base = Path(tempfile.gettempdir()).resolve(strict=True)
            for ancestor in _ancestors(base):
                _directory_id(ancestor)
            self.boundary.final()
            self.root = Path(tempfile.mkdtemp(prefix="blender-codex-render-", dir=base))
            self.root_id = _directory_id(self.root)
            self.path = self.root / ("render_" + uuid.uuid4().hex + ".png")
            self.cleanup_status = "pending"
        self.boundary.check()
        self._unused()
        self.boundary.final()
        self.directory = Path(tempfile.mkdtemp(prefix=".native-", dir=self.root))
        self.directory_id = _directory_id(self.directory)
        self.cleanup_status = "pending"
        self.pins = _DirectoryPins(self.directory)
        self.payload = self.directory / "payload.png"
        self.boundary.check()
        descriptor = os.open(self.payload, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            result = os.fstat(descriptor)
            self.payload_inode = result.st_dev, result.st_ino
        finally:
            os.close(descriptor)

    def _hash(self, path: Path, *, callbacks: bool) -> tuple[str, int, tuple]:
        if callbacks:
            self.boundary.check()
        else:
            self.boundary.final()
        self.validate()
        before = _identity(path)
        if before[:2] != self.payload_inode or not 0 < before[2] <= MAX_BYTES:
            raise invalid_argument("Native render output is empty, changed, or exceeds 64 MiB.")
        digest, count = hashlib.sha256(), 0
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        )
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != before:
                raise invalid_argument("Render output changed while its read handle opened.")
            while True:
                self.boundary.final()
                chunk = os.read(descriptor, READ_BYTES)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_BYTES:
                    raise invalid_argument("Native render output grew beyond 64 MiB.")
                digest.update(chunk)
            final = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (
            _identity(path) != before
            or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) != before
            or count != before[2]
        ):
            raise invalid_argument("Render output changed during complete-byte verification.")
        return digest.hexdigest(), count, before

    def capture(self) -> None:
        # Freeze native output before another callback-backed provider can run.
        digest, size, identity = self._hash(self.payload, callbacks=False)
        if {p.name for p in self.directory.iterdir()} != {self.payload.name}:
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Native render emitted unreviewed sidecars; private staging is retained.",
            )
        proof = verify_png(self.payload, self.boundary.final)
        if proof["file_sha256"] != digest or proof["file_bytes"] != size:
            raise invalid_argument("Native PNG changed during complete encoded-image validation.")
        self.sha256, self.bytes, self.sealed_identity = digest, size, identity
        self.png_proof = proof

    def publish(self) -> None:
        self.boundary.check()
        if self.sealed_identity is None:
            raise invalid_argument("Render output must have a complete sealed native byte proof.")
        actual = self._hash(self.payload, callbacks=False)
        if actual != (self.sha256, self.bytes, self.sealed_identity):
            raise invalid_argument("Sealed native render output changed before publication.")
        self._unused()
        self.boundary.final()
        self.attempted = True
        try:
            os.link(self.payload, self.path)
        except FileExistsError as error:
            raise invalid_argument(
                "Render target appeared after preflight; no existing file was replaced."
            ) from error
        except OSError:
            # Some filesystem failures do not prove whether the directory entry
            # was installed. Do not infer absence or remove an uncertain target.
            self.publication_outcome_unknown = True
            raise
        self.published = True
        self.verified = self._hash(self.path, callbacks=False) == (
            self.sha256,
            self.bytes,
            self.sealed_identity,
        )
        if not self.verified:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED, "Published render bytes could not be verified."
            )

    def evidence(self) -> dict:
        return {
            "filepath": str(self.path) if self.path else None,
            "publication_attempted": self.attempted,
            "file_published": None if self.publication_outcome_unknown else self.published,
            "publication_outcome_unknown": self.publication_outcome_unknown,
            "published_bytes_verified": self.verified,
            "file_sha256": self.sha256 if self.published else None,
            "file_bytes": self.bytes if self.published else None,
            "native_undo_removes_external_file": False,
            "crash_durability_verified": False,
            "retained_staging_path": str(self.payload)
            if self.payload is not None and self.cleanup_status != "complete"
            else None,
            "staging_cleanup": self.cleanup_status,
            **native_render_effects(self.boundary),
            "native_png": self.png_proof,
        }

    def cleanup(self) -> None:
        try:
            if self.payload is not None:
                self.boundary.check()
                actual = _identity(self.payload)
                if (
                    self.sealed_identity is None
                    or actual != self.sealed_identity
                    or self._hash(self.payload, callbacks=False)
                    != (self.sha256, self.bytes, self.sealed_identity)
                ):
                    raise invalid_argument(
                        "Unsealed or changed native output is retained instead of deleting unknown bytes."
                    )
                self.boundary.final()
                self.payload.unlink()
                self.payload_inode = None
            if self.directory is not None:
                if self.pins is not None:
                    self.pins.close()
                    self.pins = None
                self.boundary.check()
                if list(self.directory.iterdir()):
                    raise invalid_argument("Unowned native sidecars prevent staging cleanup.")
                self.boundary.final()
                self.directory.rmdir()
                self.directory = None
            if self.managed and not self.published and self.root is not None:
                self.boundary.check()
                if list(self.root.iterdir()):
                    raise invalid_argument("Unowned managed output prevents directory cleanup.")
                self.boundary.final()
                self.root.rmdir()
                self.root = None
            self.cleanup_status = "complete"
        except Exception as error:
            self.cleanup_status = "retained_" + (
                error.code if isinstance(error, BridgeError) else type(error).__name__
            )
        finally:
            if self.pins is not None:
                self.pins.close()
                self.pins = None
