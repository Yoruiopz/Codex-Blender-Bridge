# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed current-pixel backup files, not a general filesystem interface.

The source-qualified caller supplies current grants, cancellation, approved-root
and native-prefix CAS checks before every action. Only ``current.exr`` uses the
existing output policy; every other name is a fixed sibling in that pinned
parent. Published backups and uncertain staging survive failure and cleanup.
File and directory fsync plus independent complete readback establish measured
filesystem durability, not immunity to hardware failure or hostile processes.
All descriptors close before a cooperative yield. No cleanup performs IO.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import threading
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .current_pixels_contract import parse_manifest, validate_receipt
from .errors import BridgeError, ErrorCode, invalid_argument
from .texture_staging import approved_output

BLOCK_BYTES = 1024 * 1024
MAX_PAYLOAD_BYTES = 257 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_JOURNAL_BYTES = 64 * 1024
MAX_JOURNAL_EVENTS = 64
SUFFIXES = {"oldpacked": ".oldpacked.bin", "current": ".current.exr",
            "manifest": ".manifest.json", "journal": ".events.jsonl"}


def refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, "Current-pixel backup evidence could not be verified.",
                       {"reason": reason, "verification_required": True})


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise invalid_argument(label + " must be bounded exact text.")
    try:
        if len(value.encode("utf-8")) > 4096:
            raise invalid_argument(label + " exceeds the path budget.")
    except UnicodeError as cause:
        raise invalid_argument(label + " must be valid UTF-8.") from cause
    return value


def _prefix(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", value) is None:
        raise invalid_argument("Backup prefix must be 1-48 ASCII letters, digits, underscores or hyphens.")
    return value


def _directory(path: Path) -> tuple[int, int]:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise refused("BACKUP_DIRECTORY_NOT_ORDINARY")
    return value.st_dev, value.st_ino


def _ancestry(path: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple((str(item), *_directory(item)) for item in (*reversed(path.parents), path))


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_uid


def _regular(value: os.stat_result, *, links: int) -> None:
    if (not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400
            or value.st_nlink != links or (hasattr(os, "getuid") and value.st_uid != os.getuid())):
        raise refused("BACKUP_FILE_NOT_OWNED_ORDINARY_SINGLE_LINK")


def _absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise invalid_argument("Backup output already exists; overwrite and automatic rename are forbidden.")


def _limit(kind: str) -> int:
    if type(kind) is not str or kind not in SUFFIXES:
        raise invalid_argument("Only the fixed current-pixel backup siblings are supported.")
    return MAX_MANIFEST_BYTES if kind == "manifest" else MAX_JOURNAL_BYTES if kind == "journal" else MAX_PAYLOAD_BYTES


def _expected(kind: str, size: Any, digest: Any) -> None:
    if (type(size) is not int or not 1 <= size <= _limit(kind)
            or type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
        raise invalid_argument("Backup length and SHA256 must be complete, bounded exact facts.")


@dataclass(frozen=True, slots=True)
class BackupPlan:
    approved_root: str
    root: Path
    parent: Path
    prefix: str
    journal_enabled: bool
    create_only: bool
    ancestry: tuple[tuple[str, int, int], ...]
    root_ancestry: tuple[tuple[str, int, int], ...]

    def path(self, kind: str) -> Path:
        _limit(kind)
        if kind == "journal" and not self.journal_enabled:
            raise invalid_argument("This backup plan has no event journal.")
        return self.parent / (self.prefix + SUFFIXES[kind])

    def summary(self) -> dict[str, Any]:
        return {"approved_root": self.approved_root, "backup_directory": str(self.parent),
                "backup_prefix": self.prefix, "event_journal": self.journal_enabled,
                "create_only": self.create_only, "ancestry": self.ancestry,
                "root_ancestry": self.root_ancestry,
                "paths": {kind: str(self.path(kind)) for kind in SUFFIXES
                          if kind != "journal" or self.journal_enabled}}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.summary(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def check(self, check: Callable[[], None]) -> None:
        check()  # Current native/file grants and caller's exact live root check precede probes.
        root, current = approved_output(str(self.path("current")), self.approved_root, ".exr")
        if (root != self.root or current.parent != self.parent
                or _ancestry(self.parent) != self.ancestry or _ancestry(self.root) != self.root_ancestry):
            raise refused("BACKUP_DIRECTORY_OR_APPROVED_ROOT_CHANGED")


def _plan(directory: str, prefix: str, approved_root: str, journal_enabled: bool,
          create_only: bool, check: Callable[[], None]) -> BackupPlan:
    check()
    _text(directory, "Backup directory")
    _text(approved_root, "Approved texture folder")
    prefix = _prefix(prefix)
    if type(journal_enabled) is not bool:
        raise invalid_argument("Event journal must be an exact Boolean.")
    directory_path = Path(directory)
    if not directory_path.is_absolute() or any(part in {".", ".."} for part in directory.replace("\\", "/").split("/")):
        raise invalid_argument("Backup directory must be exact absolute text without traversal.")
    check()
    root, current = approved_output(str(directory_path / (prefix + SUFFIXES["current"])), approved_root, ".exr")
    plan = BackupPlan(approved_root, root, current.parent, prefix, journal_enabled, create_only,
                      _ancestry(current.parent), _ancestry(root))
    plan.check(check)
    if create_only:
        for kind in SUFFIXES:
            if kind == "journal" and not journal_enabled:
                continue
            plan.check(check)
            _absent(plan.path(kind))
    return plan


def freeze_backup_plan(backup_directory: str, prefix: str, approved_root: str,
                       journal_enabled: bool, check: Callable[[], None]) -> BackupPlan:
    """Read-only future-output plan; caller must already hold current grants."""
    return _plan(backup_directory, prefix, approved_root, journal_enabled, True, check)


def freeze_recovery_plan(manifest_path: str, approved_root: str,
                         check: Callable[[], None]) -> BackupPlan:
    """Derive fixed read-only siblings; files alone never authorize recovery."""
    check()
    path = Path(_text(manifest_path, "Backup manifest"))
    suffix = SUFFIXES["manifest"]
    if not path.name.endswith(suffix):
        raise invalid_argument("Recovery needs an exact fixed backup manifest path.")
    return _plan(str(path.parent), path.name[:-len(suffix)], approved_root, True, False, check)


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    identity: tuple[int, int, int, int, int]
    sha256: str

    def summary(self) -> dict[str, Any]:
        return {"filepath": self.path, "file_bytes": self.identity[2], "file_sha256": self.sha256}


class BackupFiles:
    """One pinned plan, at most one staging path and four cached file receipts.

    Source validation/codec provenance is the domain's responsibility. Blocks
    are internal qualified codec or frozen packed/manifest bytes, never RPC data.
    The ``check`` callback is the sole caller-authority interface and must check
    current grants, root string, cancellation and the complete expected prefix.
    No descriptor survives a yield; close() only latches resource retirement.
    """

    def __init__(self, plan: BackupPlan):
        if type(plan) is not BackupPlan:
            raise invalid_argument("Use the exact frozen backup plan.")
        self.plan = plan
        self.thread = threading.get_ident()
        self.stage: Path | None = None
        self.stage_identity: tuple[int, int, int, int, int] | None = None
        self.records: dict[str, FileRecord] = {}
        self.uncertain: set[str] = set()
        self.attempted = False
        self.publication_attempted = False
        self.failed = False
        self.closed = False
        self.stage_status = "not_created"
        self.journal_events = 0
        self.journal_prefix = b""
        self.file_parent_fsync: set[str] = set()
        self.complete_readback_verified = False
        self.recovery_manifest_record: FileRecord | None = None
        self.recovery_payloads: dict[str, tuple[int, str]] = {}

    def _gate(self, check: Callable[[], None]) -> None:
        if threading.get_ident() != self.thread:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Backup files must remain on their owning workflow thread.")
        self.plan.check(check)

    def _writable(self, check: Callable[[], None]) -> None:
        self._gate(check)
        if self.closed or self.failed or not self.plan.create_only:
            raise refused("BACKUP_RESOURCE_NOT_WRITABLE")

    def _stage(self, *, links: int) -> os.stat_result:
        if self.stage is None or self.stage_identity is None:
            raise refused("BACKUP_STAGING_NOT_OWNED")
        value = self.stage.lstat()
        _regular(value, links=links)
        if _identity(value) != self.stage_identity:
            raise refused("BACKUP_STAGING_CHANGED")
        return value

    def _sync_parent(self, check: Callable[[], None]) -> None:
        self._gate(check)
        descriptor = os.open(self.plan.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            value = os.fstat(descriptor)
            if (value.st_dev, value.st_ino) != self.plan.ancestry[-1][1:] or not stat.S_ISDIR(value.st_mode):
                raise refused("BACKUP_DIRECTORY_CHANGED")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read(self, path: Path, kind: str, expected_bytes: int | None, expected_sha256: str | None,
              check: Callable[[], None], *, capture: bool, links: int,
              identity: tuple[int, int, int, int, int] | None = None
              ) -> Generator[dict[str, Any], None, tuple[bytes | None, FileRecord]]:
        self._gate(check)
        before = path.lstat()
        _regular(before, links=links)
        frozen = _identity(before)
        if not 1 <= before.st_size <= _limit(kind) or (expected_bytes is not None and before.st_size != expected_bytes):
            raise refused("BACKUP_LENGTH_CHANGED_OR_EXCEEDED")
        if identity is not None and frozen != identity:
            raise refused("BACKUP_FILE_IDENTITY_CHANGED")
        digest, offset = hashlib.sha256(), 0
        captured = bytearray() if capture else None
        while offset < before.st_size:
            self._gate(check)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(descriptor)
                _regular(opened, links=links)
                if _identity(opened) != frozen:
                    raise refused("BACKUP_FILE_IDENTITY_CHANGED")
                os.lseek(descriptor, offset, os.SEEK_SET)
                block = os.read(descriptor, min(BLOCK_BYTES, before.st_size - offset))
                if not block or _identity(os.fstat(descriptor)) != frozen:
                    raise refused("BACKUP_READBACK_INCOMPLETE_OR_CHANGED")
            finally:
                os.close(descriptor)
            digest.update(block)
            offset += len(block)
            if captured is not None:
                captured.extend(block)
            yield {"phase": "verifying_" + kind, "completed": offset, "total": before.st_size}
        self._gate(check)
        after = path.lstat()
        _regular(after, links=links)
        if _identity(after) != frozen or offset != before.st_size or (expected_sha256 is not None and digest.hexdigest() != expected_sha256):
            raise refused("BACKUP_FULL_READBACK_MISMATCH")
        return bytes(captured) if captured is not None else None, FileRecord(str(path), frozen, digest.hexdigest())

    def read_steps(self, kind: str, expected_bytes: int, expected_sha256: str,
                   check: Callable[[], None], *, capture: bool = False
                   ) -> Generator[dict[str, Any], None, FileRecord | tuple[bytes, FileRecord]]:
        _expected(kind, expected_bytes, expected_sha256)
        if kind not in {"oldpacked", "current"}:
            raise invalid_argument("Payload reads use only manifest-bound oldpacked/current siblings.")
        if type(capture) is not bool:
            raise invalid_argument("Capture must be an exact Boolean.")
        if not self.plan.create_only:
            if self.recovery_manifest_record is None:
                raise refused("RECOVERY_MANIFEST_NOT_VERIFIED")
            if (expected_bytes, expected_sha256) != self.recovery_payloads[kind]:
                raise refused("RECOVERY_PAYLOAD_DOES_NOT_MATCH_MANIFEST")
            manifest = self.recovery_manifest_record
            yield from self._read(self.plan.path("manifest"), "manifest", manifest.identity[2], manifest.sha256,
                                  check, capture=False, links=1, identity=manifest.identity)
        data, record = yield from self._read(self.plan.path(kind), kind, expected_bytes, expected_sha256,
                                             check, capture=capture, links=1)
        return (data, record) if data is not None else record

    def read_manifest_steps(self, check: Callable[[], None]
                            ) -> Generator[dict[str, Any], None, tuple[dict[str, Any], FileRecord]]:
        data, record = yield from self._read(self.plan.path("manifest"), "manifest", None, None,
                                             check, capture=True, links=1)
        assert data is not None
        manifest = parse_manifest(data)
        if manifest["backup_prefix"] != self.plan.prefix:
            raise refused("MANIFEST_DOES_NOT_MATCH_PINNED_SIBLINGS")
        if self.recovery_manifest_record is not None and record != self.recovery_manifest_record:
            raise refused("RECOVERY_MANIFEST_BASELINE_CHANGED")
        self.recovery_manifest_record = record
        self.recovery_payloads = {kind: (manifest["backups"][kind]["bytes"], manifest["backups"][kind]["sha256"])
                                  for kind in ("oldpacked", "current")}
        return manifest, record

    def publish_steps(self, kind: str, blocks: Iterable[bytes], expected_bytes: int,
                      expected_sha256: str, check: Callable[[], None]
                      ) -> Generator[dict[str, Any], None, FileRecord]:
        """Create once; final files never clobber, retry, auto-delete or inverse."""
        _expected(kind, expected_bytes, expected_sha256)
        if kind == "journal":
            raise invalid_argument("Use the bounded strict event journal path.")
        return (yield from self._publish(kind, blocks, expected_bytes, expected_sha256, check))

    def _publish(self, kind: str, blocks: Iterable[bytes], expected_bytes: int,
                 expected_sha256: str, check: Callable[[], None]
                 ) -> Generator[dict[str, Any], None, FileRecord]:
        self._writable(check)
        if (kind in self.records or self.stage is not None
                or (kind == "manifest" and not {"oldpacked", "current"} <= self.records.keys())
                or (kind in {"oldpacked", "current"} and "manifest" in self.records)):
            raise refused("BACKUP_PUBLICATION_ORDER_OR_REUSE")
        target = self.plan.path(kind)
        self._gate(check)
        _absent(target)
        try:
            self._gate(check)
            self.attempted = True
            descriptor, name = tempfile.mkstemp(prefix=".blender-codex-current-pixels-", suffix=".staging", dir=self.plan.parent)
            self.stage = Path(name)
            self.stage_status = "retained_unverified"
            try:
                self.stage_identity = _identity(os.fstat(descriptor))
            finally:
                os.close(descriptor)
            digest, written = hashlib.sha256(), 0
            iterator = iter(blocks)
            while True:
                self._gate(check)  # Before advancing the source-qualified internal stream.
                try:
                    block = next(iterator)
                except StopIteration:
                    break
                if type(block) is not bytes or not block or len(block) > BLOCK_BYTES or written + len(block) > expected_bytes:
                    raise invalid_argument("Qualified backup stream exceeded its exact bounded byte plan.")
                self._gate(check)
                self._stage(links=1)
                descriptor = os.open(self.stage, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
                try:
                    if _identity(os.fstat(descriptor)) != self.stage_identity:
                        raise refused("BACKUP_STAGING_CHANGED")
                    count = os.write(descriptor, block)
                    self.stage_identity = _identity(os.fstat(descriptor))
                    if count != len(block):
                        raise refused("BACKUP_SHORT_WRITE")
                finally:
                    os.close(descriptor)
                written += count
                digest.update(block)
                yield {"phase": "writing_" + kind, "completed": written, "total": expected_bytes}
            if written != expected_bytes or digest.hexdigest() != expected_sha256:
                raise refused("BACKUP_SOURCE_LENGTH_OR_HASH_MISMATCH")
            self._gate(check)
            self._stage(links=1)
            descriptor = os.open(self.stage, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                if _identity(os.fstat(descriptor)) != self.stage_identity:
                    raise refused("BACKUP_STAGING_CHANGED")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._sync_parent(check)
            data, _ = yield from self._read(self.stage, kind, expected_bytes, expected_sha256, check,
                                            capture=kind == "manifest", links=1, identity=self.stage_identity)
            if kind == "manifest":
                assert data is not None
                manifest = parse_manifest(data)
                if manifest["backup_prefix"] != self.plan.prefix:
                    raise refused("MANIFEST_DOES_NOT_MATCH_PINNED_SIBLINGS")
                for name in ("oldpacked", "current"):
                    record = self.records[name]
                    supplied = manifest["backups"][name]
                    if supplied["bytes"] != record.identity[2] or supplied["sha256"] != record.sha256:
                        raise refused("MANIFEST_BACKUP_DESCRIPTOR_MISMATCH")
            self._gate(check)
            self._stage(links=1)
            _absent(target)
            self.publication_attempted = True
            self.uncertain.add(kind)
            os.link(self.stage, target, follow_symlinks=False)  # Atomic create-if-absent, never replace.
            self._sync_parent(check)
            _, record = yield from self._read(target, kind, expected_bytes, expected_sha256, check,
                                              capture=False, links=2, identity=self.stage_identity)
            # Retirement is limited to the exact verified successful stage. Lost
            # consent/identity/durability always retains it; never delete a backup.
            self._gate(check)
            self._stage(links=2)
            if _identity(target.lstat()) != record.identity:
                raise refused("BACKUP_PUBLICATION_CHANGED_BEFORE_STAGE_RETIREMENT")
            os.unlink(self.stage)
            self.stage_status = "successful_stage_retired"
            self.stage = None
            self.stage_identity = None
            self._sync_parent(check)
            self.records[kind] = record
            self.file_parent_fsync.add(kind)
            self.uncertain.discard(kind)
            return record
        except BaseException:
            self.failed = True
            raise

    def verify_steps(self, check: Callable[[], None]
                     ) -> Generator[dict[str, Any], None, tuple[FileRecord, ...]]:
        """Independently reopen all three immutable files before native effects."""
        required = {"oldpacked", "current", "manifest"}
        self.complete_readback_verified = False
        if not required <= self.records.keys() or not required <= self.file_parent_fsync or self.uncertain:
            raise refused("BACKUPS_NOT_COMPLETE")
        records = []
        for kind in ("oldpacked", "current", "manifest"):
            before = self.records[kind]
            try:
                _, record = yield from self._read(self.plan.path(kind), kind, before.identity[2], before.sha256,
                                                  check, capture=False, links=1, identity=before.identity)
            except BaseException:
                self.uncertain.add(kind)
                self.failed = True
                raise
            records.append(record)
        self.complete_readback_verified = True
        return tuple(records)

    def append_event_steps(self, event: dict[str, Any], check: Callable[[], None]
                           ) -> Generator[dict[str, Any], None, FileRecord]:
        """Known strict facts only; every append checks the exact owned prefix."""
        facts = validate_receipt(event)
        encoded = json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
        self._writable(check)
        if not self.plan.journal_enabled or self.journal_events >= MAX_JOURNAL_EVENTS or len(self.journal_prefix) + len(encoded) > MAX_JOURNAL_BYTES:
            raise refused("JOURNAL_EVENT_OR_BYTE_BUDGET")
        if "manifest" not in self.records:
            raise refused("JOURNAL_REQUIRES_DURABLE_BACKUPS")
        expected = self.journal_prefix + encoded
        digest = hashlib.sha256(expected).hexdigest()
        if self.journal_events == 0:
            record = yield from self._publish("journal", (encoded,), len(encoded), digest, check)
        else:
            before = self.records["journal"]
            try:
                yield from self._read(self.plan.path("journal"), "journal", before.identity[2], before.sha256,
                                      check, capture=False, links=1, identity=before.identity)
                self._writable(check)
                path = self.plan.path("journal")
                value = path.lstat()
                _regular(value, links=1)
                if _identity(value) != before.identity:
                    raise refused("JOURNAL_PREFIX_CHANGED")
                descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
                try:
                    if _identity(os.fstat(descriptor)) != before.identity:
                        raise refused("JOURNAL_PREFIX_CHANGED")
                    self.uncertain.add("journal")
                    if os.write(descriptor, encoded) != len(encoded):
                        raise refused("JOURNAL_SHORT_WRITE")
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._sync_parent(check)
                _, record = yield from self._read(path, "journal", len(expected), digest, check,
                                                  capture=False, links=1)
                if record.identity[:2] != before.identity[:2] or record.identity[4] != before.identity[4]:
                    raise refused("JOURNAL_FILE_REPLACED")
                self.records["journal"] = record
                self.file_parent_fsync.add("journal")
                self.uncertain.discard("journal")
            except BaseException:
                self.uncertain.add("journal")
                self.failed = True
                raise
        self.journal_prefix = expected
        self.journal_events += 1
        return record

    def evidence(self) -> dict[str, Any]:
        """Cached facts only: no authority callback, path probe or live read."""
        kinds = [kind for kind in SUFFIXES if kind in self.records or kind in self.uncertain]
        artifacts = []
        for kind in kinds:
            record = self.records.get(kind)
            artifacts.append({"filepath": str(self.plan.path(kind)),
                              "file_bytes": record.identity[2] if record and kind not in self.uncertain else None,
                              "file_sha256": record.sha256 if record and kind not in self.uncertain else None})
        return {"publication_attempted": self.publication_attempted,
                "file_published": bool(self.records), "publication_outcome_unknown": bool(self.uncertain),
                "published_bytes_verified": bool(self.records) and not self.uncertain,
                "crash_durability_verified": False, "native_undo_removes_external_file": False,
                "retained_staging_path": str(self.stage) if self.stage else None,
                "staging_cleanup": self.stage_status, "artifacts": artifacts,
                "artifacts_incomplete": bool(self.uncertain), "artifacts_truncated": False,
                "file_and_parent_fsync_verified": [kind for kind in SUFFIXES
                                                   if kind in self.file_parent_fsync and kind not in self.uncertain],
                "durable_backups_verified": (self.complete_readback_verified
                                             and not self.failed and not self.uncertain)}

    def close(self) -> None:
        """Release-only terminal action; no path, provider or cleanup effects."""
        self.closed = True
