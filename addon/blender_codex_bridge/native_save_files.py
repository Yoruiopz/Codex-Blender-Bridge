# SPDX-License-Identifier: GPL-3.0-or-later
"""Approved native project paths and owned Copy publication.

Callers supply live authoritative gates before filesystem access. Native Save and
Save As remain non-atomic expected-path operations. Only Copy final publication
uses create-if-absent; cleanup never deletes a final file or native backup.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument

MAX_FILE_BYTES = 256 * 1024 * 1024
READ_BYTES = 1024 * 1024
MODES = frozenset({"COPY_NEW", "SAVE_CURRENT", "SAVE_AS"})
OVERWRITE = frozenset({"NO_CLOBBER", "NATIVE_NEW_EXPECTED", "NATIVE_REPLACE_EXPECTED"})


def refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, "Native project file evidence could not be verified.",
                       {"reason": reason, "verification_required": True})


def _path(raw: str, label: str) -> Path:
    if type(raw) is not str:
        raise invalid_argument(label + " must be exact absolute text.")
    try:
        length = len(raw.encode("utf-8"))
    except UnicodeError as cause:
        raise invalid_argument(label + " must be valid UTF-8 text.") from cause
    if (not raw or length > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)
            or raw.startswith("//") or "\\" in raw):
        raise invalid_argument(label + " must be an exact absolute ordinary local path.")
    path = Path(raw)
    if not path.is_absolute() or any(part in {".", ".."} for part in raw.split("/")):
        raise invalid_argument(label + " cannot contain relative path components.")
    return path


def _directory(path: Path) -> tuple[int, int]:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise refused("PROJECT_DIRECTORY_NOT_ORDINARY")
    return value.st_dev, value.st_ino


def _ancestry(path: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple((str(value), *_directory(value)) for value in (*reversed(path.parents), path))


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    identity: tuple[int, int, int, int]
    sha256: str

    def summary(self) -> dict[str, Any]:
        return {"filepath": self.path, "file_sha256": self.sha256, "file_bytes": self.identity[2]}


def hash_steps(path: Path, check: Callable[[], None]) -> Generator[dict[str, Any], None, FileRecord]:
    check()
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400
            or not 0 < before.st_size <= MAX_FILE_BYTES):
        raise refused("PROJECT_FILE_SHAPE_OR_BUDGET")
    expected = _identity(before)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    digest, read = hashlib.sha256(), 0
    try:
        if _identity(os.fstat(descriptor)) != expected:
            raise refused("PROJECT_FILE_CHANGED")
        while True:
            check()
            block = os.read(descriptor, READ_BYTES)
            if not block:
                break
            read += len(block)
            if read > expected[2]:
                raise refused("PROJECT_FILE_CHANGED")
            digest.update(block)
            yield {"phase": "hashing_project_file", "completed": read, "total": expected[2]}
        check()
        if read != expected[2] or _identity(os.fstat(descriptor)) != expected or _identity(path.lstat()) != expected:
            raise refused("PROJECT_FILE_CHANGED")
    finally:
        os.close(descriptor)
    return FileRecord(str(path), expected, digest.hexdigest())


def _record(path: Path, check: Callable[[], None]) -> FileRecord | None:
    check()
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    steps = hash_steps(path, check)
    while True:
        try:
            next(steps)
        except StopIteration as result:
            value = result.value
            if type(value) is not FileRecord:
                raise refused("PROJECT_HASH_RESULT_INVALID") from None
            return value


def _same(record: FileRecord | None, path: Path, check: Callable[[], None]):
    if _record(path, check) != record:
        raise refused("PROJECT_FILE_PLAN_CHANGED")


@dataclass(frozen=True, slots=True)
class FilePlan:
    root: Path
    path: Path
    current_path: Path | None
    mode: str
    overwrite_policy: str
    save_version: int
    ancestry: tuple[tuple[str, int, int], ...]
    current_ancestry: tuple[tuple[str, int, int], ...]
    destination: FileRecord | None
    current: FileRecord | None
    backups: tuple[FileRecord | None, ...]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.summary(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def summary(self) -> dict[str, Any]:
        return {"approved_project_folder": str(self.root), "filepath": str(self.path), "mode": self.mode,
                "overwrite_policy": self.overwrite_policy, "save_version": self.save_version,
                "current_filepath": str(self.current_path) if self.current_path else None,
                "destination": self.destination.summary() if self.destination else None,
                "original": self.current.summary() if self.current else None,
                "backups": [value.summary() if value else None for value in self.backups],
                "ancestry": self.ancestry, "current_ancestry": self.current_ancestry,
                "native_destination_race_excluded": self.mode == "COPY_NEW"}

    def check_ancestry(self, check: Callable[[], None]):
        check()
        if _ancestry(self.path.parent) != self.ancestry:
            raise refused("PROJECT_DIRECTORY_CHANGED")
        if self.current_path and _ancestry(self.current_path.parent) != self.current_ancestry:
            raise refused("PROJECT_DIRECTORY_CHANGED")

    def check(self, check: Callable[[], None] = lambda: None):
        self.check_ancestry(check)
        _same(self.destination, self.path, check)
        if self.current_path and self.current_path != self.path:
            _same(self.current, self.current_path, check)
        for index, record in enumerate(self.backups, 1):
            _same(record, Path(str(self.path) + str(index)), check)
        self.check_ancestry(check)


def freeze_plan(root_raw: str, filepath: str, mode: str, overwrite_policy: str,
                current_filepath: str | None, save_version: int,
                check: Callable[[], None] = lambda: None) -> FilePlan:
    check()  # Before even root/path resolution.
    if not root_raw:
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "Choose an Approved Project Folder in Blender first.")
    if type(mode) is not str or mode not in MODES or type(overwrite_policy) is not str or overwrite_policy not in OVERWRITE:
        raise invalid_argument("Choose an exact supported native save mode and overwrite policy.")
    if type(save_version) is not int or not 0 <= save_version <= 3:
        raise invalid_argument("Native save currently requires Blender backup versions from 0 through 3.")
    root, path = _path(root_raw, "Approved Project Folder"), _path(filepath, "Project destination")
    if path.suffix != ".blend":
        raise invalid_argument("The exact project destination must end in .blend.")
    current = _path(current_filepath, "Current project") if current_filepath else None
    if filepath.endswith("/") or (current_filepath and current_filepath.endswith("/")):
        raise invalid_argument("A project filepath cannot end in a directory separator.")
    try:
        check()
        ancestry = _ancestry(path.parent)
        _ancestry(root)
        if root == Path(root.anchor) or root.resolve(strict=True) != root or path.parent.resolve(strict=True) != path.parent:
            raise invalid_argument("Project folders must be ordinary existing subdirectories, not roots or aliases.")
        if not path.is_relative_to(root) or (current and not current.is_relative_to(root)):
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Project paths must be inside the Approved Project Folder.")
        current_ancestry = _ancestry(current.parent) if current else ()
        if current and (current.suffix != ".blend" or current.parent.resolve(strict=True) != current.parent):
            raise invalid_argument("The current project must be an ordinary approved .blend path.")
        destination = _record(path, check)
        original = destination if current == path else _record(current, check) if current else None
        if current and original is None:
            raise refused("CURRENT_PROJECT_FILE_MISSING")
        if mode == "COPY_NEW":
            if overwrite_policy != "NO_CLOBBER" or destination is not None or current == path:
                raise invalid_argument("Copy requires NO_CLOBBER and an unused destination distinct from the current file.")
        elif mode == "SAVE_CURRENT":
            if current != path or destination is None or overwrite_policy != "NATIVE_REPLACE_EXPECTED":
                raise invalid_argument("Save Current requires the exact existing current file and NATIVE_REPLACE_EXPECTED.")
        elif (overwrite_policy == "NATIVE_NEW_EXPECTED" and destination is None) or (
            overwrite_policy == "NATIVE_REPLACE_EXPECTED" and destination is not None
        ):
            pass
        else:
            raise invalid_argument("Save As requires explicit expected-new or expected-replacement native policy.")
        backups = tuple(_record(Path(str(path) + str(index)), check) for index in range(1, save_version + 1)) if mode != "COPY_NEW" else ()
        result = FilePlan(root, path, current, mode, overwrite_policy, save_version, ancestry,
                          current_ancestry, destination, original, backups)
        result.check(check)
        return result
    except (OSError, RuntimeError) as cause:
        raise invalid_argument("Project saving needs ordinary existing local parent directories and bounded regular files.") from cause


class NativeSaveFiles:
    """An owned Copy stage or direct native path, never a native save caller."""

    def __setattr__(self, name, value):
        if name in {"plan", "native_path", "folder", "folder_id"} and getattr(self, name, None) is not None:
            raise refused("PROJECT_FILE_OWNER_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __init__(self, plan: FilePlan):
        if type(plan) is not FilePlan:
            raise refused("PROJECT_FILE_PLAN_REQUIRED")
        self.plan = plan
        self.native_path: Path | None = None
        self.folder: Path | None = None
        self.folder_id: tuple[int, int] | None = None
        self.observed: FileRecord | None = None
        self.observed_backups: tuple[FileRecord | None, ...] = ()
        self.prepared = self.native_completed = self._native_return_seen = self._native_started = False
        self.publication_attempted = self.published = self.publication_unknown = False
        self.published_verified = False
        self.cleanup_status = "not_created"

    def _stage(self):
        if self.folder is None or self.folder_id != _directory(self.folder):
            raise refused("PROJECT_STAGING_CHANGED")
        meta = self.folder.lstat()
        if meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
            raise refused("PROJECT_STAGING_NOT_PRIVATE")

    def prepare(self, check: Callable[[], None] = lambda: None) -> Path:
        if self.prepared or self.native_path is not None or self.folder is not None or self.folder_id is not None:
            raise refused("PROJECT_FILES_ALREADY_PREPARED")
        self.plan.check(check)
        self.prepared = True
        if self.plan.mode == "COPY_NEW":
            check()
            self.folder = Path(tempfile.mkdtemp(prefix=".blender-codex-project-", dir=self.plan.path.parent))
            self.folder_id = _directory(self.folder)
            self.cleanup_status = "pending"
            self.native_path = self.folder / "project.blend"
            self._stage()
        else:
            self.native_path = self.plan.path
        return self.native_path

    def native_started(self):
        if not self.prepared or self._native_started:
            raise refused("INVALID_NATIVE_FILE_START")
        self._native_started = True
        if self.plan.mode != "COPY_NEW":
            self.publication_attempted = True
            self.publication_unknown = True

    def native_returned(self, success: bool):
        if not self.prepared or type(success) is not bool or self._native_return_seen:
            raise refused("INVALID_NATIVE_FILE_COMPLETION")
        if not self._native_started:
            self.native_started()
        self._native_return_seen = True
        self.native_completed = success
        if self.plan.mode != "COPY_NEW":
            self.publication_attempted = True
            self.publication_unknown = True  # Native callbacks may already have changed/deleted the file.

    def observe_steps(self, check: Callable[[], None] = lambda: None):
        if not self.prepared or self.native_path is None:
            raise refused("PROJECT_FILES_NOT_PREPARED")
        self.plan.check_ancestry(check)
        if self.folder is not None:
            self._stage()
        record = yield from hash_steps(self.native_path, check)
        self.observed = record
        if self.plan.mode != "COPY_NEW":
            self.published, self.publication_unknown = True, False
            self.published_verified = True
            records = []
            for index in range(1, self.plan.save_version + 1):
                path = Path(str(self.plan.path) + str(index))
                backup = _record(path, check)
                records.append(backup)
                if self.plan.destination is not None:
                    source = self.plan.destination if index == 1 else self.plan.backups[index - 2]
                    expected = source or self.plan.backups[index - 1]
                else:
                    expected = self.plan.backups[index - 1]
                if (backup.sha256 if backup else None) != (expected.sha256 if expected else None):
                    self.observed_backups = tuple(records)
                    raise refused("NATIVE_BACKUP_CONTENT_CHANGED")
            self.observed_backups = tuple(records)
        if self.plan.current_path and self.plan.current_path != self.plan.path:
            _same(self.plan.current, self.plan.current_path, check)
        self.plan.check_ancestry(check)
        return self.observed

    def check_saved(self, check: Callable[[], None] = lambda: None):
        if self.native_path is None or self.observed is None:
            raise refused("SAVED_FILE_NOT_OBSERVED")
        try:
            self.plan.check_ancestry(check)
            if self.folder is not None and self.cleanup_status != "complete":
                self._stage()
            if self.cleanup_status != "complete" or self.plan.mode != "COPY_NEW":
                _same(self.observed, self.native_path, check)
            if self.published and self.plan.mode == "COPY_NEW":
                record = _record(self.plan.path, check)
                if record is None or record.sha256 != self.observed.sha256 or record.identity != self.observed.identity:
                    raise refused("PUBLISHED_PROJECT_CHANGED")
            for record in self.observed_backups:
                if record is not None:
                    _same(record, Path(record.path), check)
            if self.plan.current_path and self.plan.current_path != self.plan.path:
                _same(self.plan.current, self.plan.current_path, check)
        except (BridgeError, OSError):
            self.published_verified = False
            raise

    def publish(self, check: Callable[[], None] = lambda: None):
        if self.plan.mode != "COPY_NEW" or self.published or self.publication_attempted:
            raise refused("INVALID_PROJECT_PUBLICATION")
        self.plan.check(check)
        self.check_saved(check)
        native = self.native_path
        if native is None:
            raise refused("PROJECT_STAGING_MISSING")
        check()
        self.publication_attempted = True
        try:
            os.link(native, self.plan.path)
        except FileExistsError as cause:
            raise refused("PROJECT_DESTINATION_COLLISION") from cause
        except OSError as cause:
            self.publication_unknown = True
            raise refused("PROJECT_PUBLICATION_UNKNOWN") from cause
        self.published = True
        self.check_saved(check)
        self.published_verified = True
        return self.effects()

    def effects(self):
        artifacts = []
        if self.observed:
            if self.plan.mode != "COPY_NEW" or self.published:
                artifacts.append({**self.observed.summary(), "filepath": str(self.plan.path)})
            if self.plan.mode == "COPY_NEW" and self.cleanup_status != "complete":
                artifacts.append(self.observed.summary())
        artifacts.extend(record.summary() for record in self.observed_backups if record)
        return {"filepath": str(self.plan.path), "file_sha256": self.observed.sha256 if self.published and self.observed else None,
                "file_bytes": self.observed.identity[2] if self.published and self.observed else None,
                "publication_attempted": self.publication_attempted, "file_published": self.published,
                "publication_outcome_unknown": self.publication_unknown,
                "published_bytes_verified": self.published_verified,
                "native_undo_removes_external_file": False, "crash_durability_verified": False,
                "retained_staging_path": str(self.folder) if self.folder and self.cleanup_status != "complete" else None,
                "staging_cleanup": self.cleanup_status, "artifacts": artifacts[:4],
                "artifacts_truncated": len(artifacts) > 4,
                "artifacts_incomplete": (self._native_started and self.observed is None)
                or (self.plan.mode != "COPY_NEW" and self.observed is not None
                and len(self.observed_backups) != self.plan.save_version)}

    def close(self, *, remove_files: bool = True):
        if self.folder is None or self.cleanup_status == "complete":
            return self.effects()
        if not remove_files:
            self.cleanup_status = "retained_permission_denied"
            return self.effects()
        try:
            self._stage()
            names = list(self.folder.iterdir())
            if names:
                native = self.native_path
                if native is None or names != [native] or self.observed is None:
                    raise refused("PROJECT_STAGING_UNVERIFIED")
                _same(self.observed, native, lambda: None)
                self._stage()
                native.unlink()
            self._stage()
            self.folder.rmdir()
            self.cleanup_status = "complete"
        except (OSError, BridgeError):
            self.cleanup_status = "retained_unverified"
        return self.effects()
