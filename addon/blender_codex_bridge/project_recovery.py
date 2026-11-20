"""Persist the latest verified project-save fingerprint in Blender's user config."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

from .errors import BridgeError, ErrorCode
from .utils import require_blender

INDEX_NAME = "blender-codex-bridge-checkpoint-v1.json"
MAX_INDEX_BYTES = 16 * 1024
MAX_PROJECT_BYTES = 4 * 1024**3
HASH_CHUNK_BYTES = 1024**2
CHECKPOINT_ID = re.compile(r"checkpoint_[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_KEYS = {"schema", "checkpoint_id", "filepath", "file_sha256", "file_bytes", "saved_at",
         "fresh_process_reopen_verified"}
# Blender can write plain, legacy gzip, or Zstandard containers. These
# prefixes qualify the observed writer output for hashing, not for decoding.
_BLEND_CONTAINER_PREFIXES = (b"BLENDER", b"\x1f\x8b\x08", b"\x28\xb5\x2f\xfd")
_SIGNATURE_FIELDS = ("device", "file_id", "size", "modified_time", "creation_or_change_time")


class EvidenceError(Exception):
    """Saved evidence could not be checked or persisted."""

    def __init__(self, reason: str, **facts: Any):
        self.reason = reason
        self.facts = facts
        super().__init__(reason)


def unavailable(reason: str, **facts: Any) -> dict[str, Any]:
    return {"state": "unavailable", "reason": reason, **facts}


def refusal(reason: str, message: str, **facts: Any) -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, message, {"reason": reason, **facts})


def _index_path(*, create: bool) -> Path:
    try:
        root = require_blender().utils.user_resource("CONFIG", create=create)
    except (BridgeError, AttributeError, RuntimeError):
        raise EvidenceError("RECOVERY_CONFIG_UNAVAILABLE") from None
    if type(root) is not str or not root or not Path(root).is_absolute():
        raise EvidenceError("RECOVERY_CONFIG_UNAVAILABLE")
    directory = Path(root)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or _is_reparse(info):
        raise EvidenceError("RECOVERY_CONFIG_UNAVAILABLE")
    return directory / INDEX_NAME


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _signature(info: os.stat_result, *, windows: bool = os.name == "nt") -> tuple[int, int, int, int, int]:
    # Recent Windows Python reports creation time via lstat().st_ctime_ns
    # but change time via fstat().st_ctime_ns. Compare the shared creation
    # field there, and verify handle change time across the read separately.
    timestamp = getattr(info, "st_birthtime_ns", info.st_ctime_ns) if windows else info.st_ctime_ns
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, timestamp


def _check_signature(observed: tuple[int, int, int, int, int],
                     expected: tuple[int, int, int, int, int], phase: str) -> None:
    if observed != expected:
        changed = [field for field, actual, original in zip(_SIGNATURE_FIELDS, observed, expected, strict=True)
                   if actual != original]
        raise EvidenceError("RECOVERY_FILE_CHANGED", verification_phase=phase, changed_fields=changed)


def file_signature(path: Path, maximum: int = MAX_PROJECT_BYTES) -> tuple[int, int, int, int, int]:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or _is_reparse(info)
            or not 0 < info.st_size <= maximum):
        raise EvidenceError("RECOVERY_FILE_SHAPE_OR_LIMIT")
    return _signature(info)


def _open_verified(path: Path, expected: tuple[int, int, int, int, int]) -> tuple[BinaryIO, int]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or _is_reparse(observed):
            raise EvidenceError("RECOVERY_FILE_CHANGED", verification_phase="open_signature",
                                changed_fields=["file_type"])
        _check_signature(_signature(observed), expected, "open_signature")
        return os.fdopen(descriptor, "rb"), observed.st_ctime_ns
    except BaseException:
        os.close(descriptor)
        raise


def _check_descriptor(stream: BinaryIO, expected: tuple[int, int, int, int, int], change_time: int) -> None:
    observed = os.fstat(stream.fileno())
    _check_signature(_signature(observed), expected, "stream_signature")
    if observed.st_ctime_ns != change_time:
        raise EvidenceError("RECOVERY_FILE_CHANGED", verification_phase="stream_signature",
                            changed_fields=["descriptor_change_time"])


@dataclass(frozen=True, slots=True)
class ProjectBytes:
    signature: tuple[int, int, int, int, int]
    sha256: str

    @property
    def size(self) -> int:
        return self.signature[2]


def hash_project_bytes(path: Path, check: Callable[[], None]) -> ProjectBytes:
    """Measure complete regular-file bytes, checking the request between chunks."""
    check()
    expected = file_signature(path)
    digest = hashlib.sha256()
    observed = 0
    stream, change_time = _open_verified(path, expected)
    with stream:
        while True:
            check()
            chunk = stream.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            if observed == 0 and not chunk.startswith(_BLEND_CONTAINER_PREFIXES):
                raise EvidenceError("RECOVERY_NOT_BLEND_FILE")
            digest.update(chunk)
            observed += len(chunk)
            if observed > expected[2]:
                raise EvidenceError("RECOVERY_FILE_CHANGED", verification_phase="stream_length",
                                    changed_fields=["size"])
        check()
        if observed != expected[2]:
            raise EvidenceError("RECOVERY_FILE_CHANGED", verification_phase="stream_length",
                                changed_fields=["size"])
        _check_descriptor(stream, expected, change_time)
    _check_signature(file_signature(path), expected, "final_path_signature")
    return ProjectBytes(expected, digest.hexdigest())


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise EvidenceError("RECOVERY_INDEX_INVALID")
    return value


def _validated(record: Any) -> dict[str, Any]:
    if (type(record) is not dict or set(record) != _KEYS
            or type(record["schema"]) is not int or record["schema"] != 1
            or type(record["checkpoint_id"]) is not str or not CHECKPOINT_ID.fullmatch(record["checkpoint_id"])
            or type(record["filepath"]) is not str or len(record["filepath"].encode("utf-8")) > 4096
            or not Path(record["filepath"]).is_absolute() or Path(record["filepath"]).suffix.lower() != ".blend"
            or any(ord(char) < 32 or ord(char) == 127 for char in record["filepath"])
            or type(record["file_sha256"]) is not str or not _SHA256.fullmatch(record["file_sha256"])
            or type(record["file_bytes"]) is not int or not 0 < record["file_bytes"] <= MAX_PROJECT_BYTES
            or type(record["fresh_process_reopen_verified"]) is not bool
            or type(record["saved_at"]) is not str or len(record["saved_at"]) > 40):
        raise EvidenceError("RECOVERY_INDEX_INVALID")
    try:
        saved_at = datetime.fromisoformat(record["saved_at"])
    except ValueError:
        raise EvidenceError("RECOVERY_INDEX_INVALID") from None
    if saved_at.tzinfo is None:
        raise EvidenceError("RECOVERY_INDEX_INVALID")
    return record


def read_index() -> dict[str, Any] | None:
    """Read the last complete receipt. A missing index is a normal initial state."""
    try:
        path = _index_path(create=False)
        expected = file_signature(path, MAX_INDEX_BYTES)
    except FileNotFoundError:
        return None
    stream, change_time = _open_verified(path, expected)
    with stream:
        raw = stream.read(MAX_INDEX_BYTES + 1)
        _check_descriptor(stream, expected, change_time)
    if len(raw) != expected[2] or file_signature(path, MAX_INDEX_BYTES) != expected:
        raise EvidenceError("RECOVERY_INDEX_CHANGED")
    try:
        return _validated(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))
    except (ValueError, RecursionError):
        raise EvidenceError("RECOVERY_INDEX_INVALID") from None


def _write_index(record: dict[str, Any], check: Callable[[], None]) -> None:
    check()
    path = _index_path(create=True)
    raw = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
    descriptor, name = tempfile.mkstemp(prefix=".bcb-checkpoint-", dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        check()
        os.replace(pending, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        pending.unlink(missing_ok=True)


def summarize(record: dict[str, Any], *, state: str = "available") -> dict[str, Any]:
    return {"state": state, **{key: value for key, value in record.items() if key != "schema"},
            "verification": "fresh_process_reopen" if record["fresh_process_reopen_verified"] else "saved_bytes"}


def record_verified_save(*, filepath: str, file_sha256: str, file_bytes: int,
                         fresh_process_reopen_verified: bool, check: Callable[[], None] = lambda: None) -> dict[str, Any]:
    """Commit one receipt after a successful call has independently measured its output."""
    try:
        record = _validated({
            "schema": 1, "checkpoint_id": "checkpoint_" + uuid4().hex, "filepath": filepath,
            "file_sha256": file_sha256, "file_bytes": file_bytes, "saved_at": datetime.now(timezone.utc).isoformat(),
            "fresh_process_reopen_verified": fresh_process_reopen_verified,
        })
        _write_index(record, check)
    except (EvidenceError, OSError, ValueError):
        return unavailable("RECOVERY_INDEX_WRITE_FAILED")
    return summarize(record)


def save_recovery_checkpoint(path: Path, check: Callable[[], None]) -> dict[str, Any]:
    """Measure output from a successful regular native save and record its digest."""
    try:
        saved = hash_project_bytes(path, check)
    except EvidenceError as error:
        return unavailable(error.reason, **error.facts)
    except OSError:
        return unavailable("RECOVERY_FILE_READ_FAILED")
    return record_verified_save(filepath=str(path), file_sha256=saved.sha256, file_bytes=saved.size,
                                fresh_process_reopen_verified=False, check=check)
