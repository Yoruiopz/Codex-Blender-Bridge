"""Owned, bounded texture-file staging. Internal foundation, NOT an export tool.

Only our streaming codec can populate this resource. Callers still own source
freezing, jobs/history/checkpoints, native reimport and pixel/appearance checks.
Atomic publication is no-clobber, not a crash-durability or filesystem sandbox
claim. Published files are never removed by cleanup or Blender undo.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import tempfile
import threading
from array import array
from collections.abc import Callable, Iterator
from pathlib import Path, PureWindowsPath
from typing import Any

from . import pixel_codecs
from .errors import BridgeError, ErrorCode, invalid_argument
from .image_files import _absolute, _local_drive
from .permissions import Permission

LOGGER = logging.getLogger(__name__)
READ_BYTES = 65536
REQUIRED = (Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT)


def _identity(value: os.stat_result) -> tuple:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _directory_id(path: Path) -> tuple:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise invalid_argument("Texture output directories cannot be links/reparse points.")
    return value.st_dev, value.st_ino


def _ancestors(path: Path) -> list[Path]:
    return [*reversed(path.parents), path]


class _DirectoryPins:
    """Windows directory handles deny deletion/rename while staging is owned.

    Not a desktop/window API. POSIX uses identity/resolve checks; no claim of
    exclusion against a hostile process renaming a directory between syscalls.
    """

    def __init__(self, parent: Path):
        self.handles: list[Any] = []
        self.close_handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes as w

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
        create.restype = w.HANDLE
        self.close_handle = kernel.CloseHandle
        self.close_handle.argtypes, self.close_handle.restype = [w.HANDLE], w.BOOL
        attributes = kernel.GetFileInformationByHandleEx
        attributes.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        attributes.restype = w.BOOL
        try:
            for path in _ancestors(parent):
                # GENERIC_READ, SHARE_READ|SHARE_WRITE (not SHARE_DELETE),
                # OPEN_EXISTING, BACKUP_SEMANTICS|OPEN_REPARSE_POINT.
                # Attribute-only handles do NOT participate in delete-sharing
                # exclusion on Windows. A real directory read handle is needed.
                handle = create(str(path), 0x80000000, 3, None, 3, 0x02200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.handles.append(handle)
                info = (w.DWORD * 2)()
                if not attributes(handle, 9, info, ctypes.sizeof(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if info[0] & 0x400 or not info[0] & 0x10:
                    raise invalid_argument("Texture output ancestry must contain only ordinary local directories.")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        while self.handles:
            self.close_handle(self.handles.pop())


def approved_output(raw: str, root_raw: str, extension: str) -> tuple[Path, Path]:
    """Filesystem probes: caller MUST already hold all REQUIRED live grants."""
    if not root_raw:
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "Choose an approved texture folder in Blender first.")
    if extension not in {".png", ".exr"}:
        raise invalid_argument("Only reviewed PNG/EXR texture output extensions are supported.")
    root, target = _absolute(root_raw, "Texture folder"), _absolute(raw, "Texture output")
    for path in (root, target):
        if any(PureWindowsPath(part).is_reserved() or part.endswith((".", " ")) for part in path.parts[1:]):
            raise invalid_argument("Texture paths cannot use reserved devices or trailing dots/spaces.")
    if target.suffix.lower() != extension:
        raise invalid_argument("The explicit output extension must match the chosen texture encoding.")
    try:
        resolved_root, parent = root.resolve(strict=True), target.parent.resolve(strict=True)
        if resolved_root == Path(resolved_root.anchor) or not resolved_root.is_dir():
            raise invalid_argument("The approved texture folder must be an existing subdirectory, not a volume root.")
        if not parent.is_relative_to(resolved_root):
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Texture output is outside Blender's approved texture folder.")
        if os.name != "nt" and len(parent.parts) > 1 and parent.parts[1] in {"dev", "proc", "sys"}:
            raise invalid_argument("Device/process directories cannot receive texture output.")
        for ancestor in _ancestors(target.parent):
            _directory_id(ancestor)  # Reject even links resolving back inside the approved tree.
        for ancestor in _ancestors(root):
            _directory_id(ancestor)
        if not _local_drive(parent):
            raise invalid_argument("Texture output must use a local drive.")
        return resolved_root, parent / target.name
    except (OSError, RuntimeError) as exc:
        raise invalid_argument("Texture output needs an existing, ordinary local parent directory.") from exc


class TextureStaging:
    """One owned codec stream, sealed hash proof and explicit no-clobber publish.

    Constructing has no filesystem effects. Drain encode_steps(), then publish().
    Always call cleanup(), even after exceptions or generator.close(); its evidence
    must survive in the caller's audit record. Revoked consent retains staging,
    never silently unlinks it. Only exact owned staging is eligible for cleanup.
    """

    def __init__(self, context: Any, filepath: str, root: Callable[[], str], format: str, role: str):
        self.context, self.raw, self.root = context, filepath, root
        self.layout = pixel_codecs.interpretation(format, role)
        self.thread = threading.get_ident()
        self.path: Path | None = None
        self.stage: Path | None = None
        self.folder: Path | None = None
        self.parent_id: tuple | None = None
        self.stage_id: tuple | None = None
        self.pins: _DirectoryPins | None = None
        self.stream: Any = None
        self.bytes = 0
        self.maximum_block_bytes = 0
        self.encoding_steps = 0
        self.digest = hashlib.sha256()
        self.sealed = False
        self.published = False
        self.publication_attempted = False
        self.published_verified = False
        self.closed = False
        self.attempted = False
        self.cleanup_status = "not_created"

    def _main(self) -> None:
        if threading.get_ident() != self.thread:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Texture staging must stay on its owning main-thread workflow.")

    def _authorize(self, *, cleanup=False) -> None:
        self._main()
        self.context.require(*REQUIRED)  # BEFORE path/root probes or external IO.
        if not cleanup:
            check = getattr(self.context, "check_cancelled", None)
            if check:
                check()
            state = getattr(self.context, "state", None)
            flags = state.snapshot() if state else {}
            if flags.get("emergency_stopped"):
                raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Texture staging emergency-stopped.")
            if flags.get("paused"):
                raise BridgeError(ErrorCode.AGENT_PAUSED, "Texture staging is paused.")
        # Trusted lifecycle callbacks can change live consent. The final gate
        # belongs after those callbacks, immediately before the IO action.
        self.context.require(*REQUIRED)

    def _location(self) -> None:
        folder, path = approved_output(self.raw, self.root(), self.layout["extension"])
        if (folder, path, _directory_id(path.parent)) != (self.folder, self.path, self.parent_id):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Approved texture output location changed; reinspect before retrying.", {"stale_output_location": True})

    def _owned(self) -> None:
        if self.stage is None or self.stage_id is None or _identity(self.stage.lstat()) != self.stage_id:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Staging identity/content metadata changed; no cleanup or publication is authorized.")

    def _absent(self) -> None:
        try:
            self.path.lstat()  # Includes broken symlinks; exists() alone is insufficient.
        except FileNotFoundError:
            return
        raise invalid_argument("Texture output already exists; overwrite and automatic rename are forbidden.")

    def _open(self) -> None:
        self._authorize()
        if self.closed or self.attempted:
            raise invalid_argument("A staging resource can encode only once.")
        self.attempted = True
        self.folder, self.path = approved_output(self.raw, self.root(), self.layout["extension"])
        self.pins = _DirectoryPins(self.path.parent)
        self.parent_id = _directory_id(self.path.parent)
        self._authorize()
        self._location()
        self._absent()
        self._authorize()
        descriptor, name = tempfile.mkstemp(prefix=".blender-codex-", suffix=".staging", dir=self.path.parent)
        self.stage = Path(name)
        self.stage_id = _identity(os.fstat(descriptor))
        self.cleanup_status = "pending"
        try:
            self.stream = os.fdopen(descriptor, "w+b", buffering=0)
        except BaseException:
            os.close(descriptor)
            raise

    def _append(self, data: bytes) -> None:
        self._authorize()
        self._location()
        self._owned()
        if not isinstance(data, bytes) or len(data) > pixel_codecs.BLOCK_BYTES + 12 or self.bytes + len(data) > pixel_codecs.MAX_ENCODED_BYTES:
            raise invalid_argument("Texture encoder exceeded its bounded block/file budget.")
        if data:
            self._authorize()
            try:
                count = self.stream.write(data)
            finally:
                self.stage_id = _identity(os.fstat(self.stream.fileno()))
            if count != len(data):
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Texture staging write was incomplete.")
            self.bytes += count
            self.digest.update(data)
            self.maximum_block_bytes = max(self.maximum_block_bytes, len(data))

    def encode_steps(self, values: array, width: int, height: int, *, srgb=False) -> Iterator[dict]:
        """Bound CPU/IO work; partial bytes remain private until completely sealed.

        Cleanup is explicit rather than hidden in generator finalization so callers
        can preserve retained-file evidence on deadline/revocation/generator close.
        """
        self._open()
        for step in pixel_codecs.encode_steps(values, width, height, self.layout["format"], self.layout["role"],
                                             srgb=srgb, check=self._authorize):
            self.encoding_steps += 1
            if step.data:
                self._append(step.data)
            yield {"phase": "encoding", "completed": step.pixels_completed, "total": step.pixels_total,
                   "staged_bytes": self.bytes}
        self._authorize()
        self.stream.flush()
        os.fsync(self.stream.fileno())
        yield from self._verify_steps(published=False)
        self.stream.close()
        self.stream = None
        self.sealed = True

    def _verify_steps(self, *, published: bool) -> Iterator[dict]:
        self._authorize()
        self._location()
        self._owned()
        path = self.path if published else self.stage
        self._authorize()
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or _identity(before) != self.stage_id or before.st_size != self.bytes:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Texture file identity/size does not match its complete encoded stream.")
        digest, count = hashlib.sha256(), 0
        with path.open("rb") as stream:
            if _identity(os.fstat(stream.fileno())) != self.stage_id:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Texture file changed while opening verification.")
            while count < self.bytes:
                self._authorize()
                self._location()  # Approved folder can change between cooperative read slices.
                block = stream.read(min(READ_BYTES, self.bytes-count))
                if not block:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Texture file ended during complete verification.")
                digest.update(block)
                count += len(block)
                yield {"phase": "verifying_published_file" if published else "verifying_staging",
                       "completed": count, "total": self.bytes}
            after = os.fstat(stream.fileno())
        self._authorize()
        self._location()
        self._owned()
        if digest.digest() != self.digest.digest() or _identity(after) != self.stage_id or _identity(path.lstat()) != self.stage_id:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Texture file changed or its complete hash did not match.")

    def publish(self) -> dict:
        self._authorize()
        if not self.sealed or self.closed or self.published:
            raise invalid_argument("Publication requires one completely sealed, unpublished staging resource.")
        self._location()
        self._owned()
        self._absent()
        self._authorize()
        self.publication_attempted = True
        try:
            # Atomic create-if-absent on the same filesystem. No replace/rename
            # fallback: unsupported hard links must fail, never silently clobber.
            os.link(self.stage, self.path, follow_symlinks=False)
        except OSError as exc:
            LOGGER.exception("Texture no-clobber publication failed")
            raise BridgeError(ErrorCode.OPERATION_FAILED, "No-clobber texture publication did not confirm success; reinspect the exact target. No overwrite fallback was attempted.",
                              {"publication_attempted": True, "publication_outcome_unknown": True,
                               "verification_required": True}) from exc
        self.published = True  # Set BEFORE any potentially failing late check.
        self._authorize()
        self._location()
        self._owned()
        if _identity(self.path.lstat()) != self.stage_id:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Published texture identity could not be verified; retain file evidence.")
        return self.evidence()

    def verify_published_steps(self) -> Iterator[dict]:
        self._main()
        self.published_verified = False
        if not self.published or self.closed:
            raise invalid_argument("Only this resource's published file can receive a streaming hash proof.")
        yield from self._verify_steps(published=True)
        self.published_verified = True

    def evidence(self) -> dict:
        return {"file_published": self.published, "filepath": str(self.path) if self.path else None,
                "publication_attempted": self.publication_attempted,
                "publication_outcome_unknown": self.publication_attempted and not self.published,
                # A failed/short write can put bytes on disk without accepting
                # the complete block into the encoder hash. Do not underreport
                # those partial bytes when cleanup is subsequently denied.
                "file_bytes": self.stage_id[2] if self.stage_id else 0,
                "encoded_bytes_hashed": self.bytes,
                "file_sha256": self.digest.hexdigest() if self.sealed else None,
                "encoded_stream_sealed": self.sealed, "published_file_hash_verified": self.published_verified,
                "maximum_emitted_block_bytes": self.maximum_block_bytes, "encoding_steps": self.encoding_steps,
                "staging_cleanup": self.cleanup_status,
                "retained_staging_path": str(self.stage) if self.stage and self.cleanup_status not in {"removed", "absent"} else None,
                "external_file_survives_native_undo": self.published,
                "native_decode_verified": False, "pixel_roundtrip_verified": False,
                "crash_durability_verified": False, "encoding": dict(self.layout)}

    def cleanup(self) -> dict:
        """Release handles; remove only unchanged owned staging with live consent.

        Cancellation/pause/stop do not prevent reducing private temporary state;
        permission revocation does. Never touch the final published path.
        """
        self._main()
        if self.closed:
            return self.evidence()
        try:
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            if self.stage is not None:
                self._authorize(cleanup=True)
                self._location()
                try:
                    self._owned()
                except FileNotFoundError:
                    self.cleanup_status = "absent"
                else:
                    self.stage.unlink()
                    self.cleanup_status = "removed"
        except BridgeError as exc:
            self.published_verified = False
            self.cleanup_status = "retained_permission_denied" if exc.code == ErrorCode.PERMISSION_DENIED.value else "retained_identity_or_location_changed"
            LOGGER.warning("Owned texture staging retained: %s", self.cleanup_status)
        except OSError:
            self.cleanup_status = "retained_io_error"
            LOGGER.exception("Owned texture staging cleanup failed")
        finally:
            if self.pins:
                self.pins.close()
            self.closed = True
        return self.evidence()
