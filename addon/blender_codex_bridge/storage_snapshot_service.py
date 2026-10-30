# SPDX-License-Identifier: GPL-3.0-or-later
"""Private retention for qualified snapshot primitives; no registered caller.

The owner is an in-process lifetime identity, not proof of Runtime authority.
Callers must authorize separately, then supply source-qualified local approval
text and a PURE live ``check`` gate before filesystem access. Purity is a caller
precondition, never inferred from an arbitrary Callable. Runtime attachment,
preference/source admission and new method allowlisting are not implemented here.
This module never runs the native writer or serializes an ownership capability.
"""
from __future__ import annotations

import os
import stat
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .storage_snapshot import SnapshotOperation, cleanup_step
from .storage_snapshot_effects import (
    MAX_SNAPSHOTS,
    SnapshotJournal,
    SnapshotOwner,
    cleanup_receipt,
    cleanup_state,
)

# The service shares the qualified primitive's total lifetime cell ceiling.
# Each reservation owns its full journal permanently, including unused cells.
MAX_SERVICE_SNAPSHOTS = MAX_SNAPSHOTS


def refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, "Retained snapshot ownership is unavailable.",
                       {"reason": reason, "verification_required": True,
                        "shipping_caller_qualified": False, "durable_backup_qualified": False})


def _text(value: str) -> str:
    if type(value) is not str:
        raise invalid_argument("Storage paths must be exact text.")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise invalid_argument("Storage paths must be valid UTF-8.") from error
    if (not value or length > 4096 or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise invalid_argument("Storage paths must be bounded ordinary local text.")
    return value


def _paths(approved_root: str, subdirectory: str) -> tuple[Path, Path]:
    root, relative = Path(_text(approved_root)), Path(_text(subdirectory))
    if (not root.is_absolute() or root == Path(root.anchor) or approved_root.startswith("//")
            or str(root) != approved_root or os.path.normpath(approved_root) != approved_root
            or any(part in {"", ".", ".."} for part in approved_root.split("/")[1:])):
        raise invalid_argument("The approved folder must be an exact absolute non-root path.")
    if (relative.is_absolute() or str(relative) != subdirectory
            or any(part in {"", ".", ".."} for part in subdirectory.split("/"))):
        raise invalid_argument("The scratch subdirectory must be an exact relative existing path.")
    parent = root / relative
    _text(str(parent))
    return root, parent


def _filesystem(check: Callable[[], None] | None, function: Callable, *args, **kwargs):
    if check is not None:
        check()
    result = function(*args, **kwargs)
    if check is not None:
        check()
    return result


def _ancestry(path: Path, check: Callable[[], None] | None) -> tuple:
    rows = []
    for current in (*reversed(path.parents), path):
        info = _filesystem(check, current.lstat)
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise refused("STORAGE_SERVICE_ANCESTRY_NOT_ORDINARY")
        rows.append((str(current), info.st_dev, info.st_ino))
    # Every exact lexical component was lstat'ed: no symlink/reparse traversal.
    return tuple(rows)


def _directory(info: os.stat_result) -> tuple:
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid()):
        raise refused("STORAGE_SERVICE_NAMESPACE_NOT_PRIVATE")
    return info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)


@dataclass(slots=True)
class _Receipt:
    identifier: str
    journal: SnapshotJournal
    capacity: int
    attempts: int = 0


class StorageSnapshotService:
    """Create-only private roots and original journals retained until Runtime exit.

    One service binds its first approved-root/subdirectory pair. It never adopts
    an existing namespace, deletes its outer root, recycles a receipt or refunds
    an allocated budget. A caller must calculate its worst-case writer count
    before reserving; this service does not invent a cloth phase budget.
    """
    __slots__ = ("_allocated", "_binding", "_close_failed", "_created", "_leaf", "_owner",
                 "_plan", "_ready", "_receipts", "_root")

    def __init__(self, runtime_owner: Any):
        if runtime_owner is None:
            raise invalid_argument("A private Runtime lifetime owner is required.")
        self._owner = runtime_owner
        self._receipts: dict[str, _Receipt] = {}
        self._allocated = 0
        self._leaf = "bcb-storage-service-" + os.urandom(16).hex()
        self._root: str | None = None
        self._plan: tuple | None = None
        self._binding: tuple | None = None
        self._created = self._ready = False
        self._close_failed = False

    def _owned(self, owner: Any) -> None:
        if owner is not self._owner:
            raise refused("STORAGE_SERVICE_OWNER_CHANGED")
        if threading.current_thread() is not threading.main_thread():
            raise refused("STORAGE_SERVICE_MAIN_THREAD_REQUIRED")

    def _receipt(self, owner: Any, identifier: str) -> _Receipt:
        self._owned(owner)
        if (type(identifier) is not str or len(identifier) != 32
                or any(char not in "0123456789abcdef" for char in identifier)):
            raise refused("STORAGE_SERVICE_RECEIPT_NOT_ISSUED")
        receipt = self._receipts.get(identifier)
        if receipt is None:
            raise refused("STORAGE_SERVICE_RECEIPT_NOT_ISSUED")
        return receipt

    @staticmethod
    def _platform() -> None:
        if sys.platform != "linux":
            raise refused("STORAGE_SERVICE_PLATFORM_UNQUALIFIED")

    def _namespace(self, approved_root: str, check: Callable[[], None]) -> None:
        self._platform()
        if (not self._ready or self._root is None or self._plan is None or self._binding is None
                or type(approved_root) is not str or approved_root != self._plan[0]):
            raise refused("STORAGE_SERVICE_APPROVAL_OR_NAMESPACE_CHANGED")
        if (_ancestry(Path(self._plan[1]), check) != self._plan[2]
                or _directory(_filesystem(check, os.lstat, self._root)) != self._binding):
            raise refused("STORAGE_SERVICE_APPROVAL_OR_NAMESPACE_CHANGED")
        check()
        # No callback after the final path/identity comparison. A gate that
        # drifted the path cannot turn the next operation into adoption.
        if (_ancestry(Path(self._plan[1]), None) != self._plan[2]
                or _directory(os.lstat(self._root)) != self._binding):
            raise refused("STORAGE_SERVICE_APPROVAL_OR_NAMESPACE_CHANGED")

    def reserve(self, owner: Any, approved_root: str, scratch_subdirectory: str,
                snapshot_budget: int, *, check: Callable[[], None]) -> str:
        """Reserve immutable lifetime capacity before any SnapshotOperation.

        Authorization must precede the call. The held PURE gate checks live
        local approval/control/source/lifetime without permission providers or
        foreign callbacks. Caller text and the opaque owner alone grant nothing.
        Scratch ancestry must already exist; only the unpredictable namespace is
        created. Failed namespace creation remains listed and is never adopted.
        """
        self._owned(owner)
        self._platform()
        if (type(snapshot_budget) is not int or not 1 <= snapshot_budget <= MAX_SERVICE_SNAPSHOTS
                or self._allocated + snapshot_budget > MAX_SERVICE_SNAPSHOTS):
            raise refused("STORAGE_SERVICE_CAPACITY")
        root, parent = _paths(approved_root, scratch_subdirectory)
        if self._plan is not None:
            if (str(root), str(parent)) != self._plan[:2]:
                raise refused("STORAGE_SERVICE_APPROVAL_OR_NAMESPACE_CHANGED")
            self._namespace(approved_root, check)
        check()
        ancestry = _ancestry(parent, check)
        if not any(row[0] == str(root) for row in ancestry):
            raise refused("STORAGE_SERVICE_APPROVED_ROOT_REQUIRED")
        namespace = parent / self._leaf
        _text(str(namespace))
        identifier = os.urandom(16).hex()
        if identifier in self._receipts:
            raise refused("STORAGE_SERVICE_RECEIPT_COLLISION")
        receipt = _Receipt(identifier, SnapshotJournal(snapshot_budget), snapshot_budget)
        # Retain before create/open or any subsequent callback can fail.
        self._receipts[identifier] = receipt
        self._allocated += snapshot_budget
        if self._plan is not None:
            return identifier
        self._plan = str(root), str(parent), ancestry
        self._root = str(namespace)
        check()
        if _ancestry(parent, check) != ancestry:
            raise refused("STORAGE_SERVICE_APPROVAL_OR_NAMESPACE_CHANGED")
        check()
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        in_error = False
        try:
            check()  # FD is retained before this post-open gate.
            info = _filesystem(check, os.fstat, descriptor)
            if (info.st_dev, info.st_ino) != ancestry[-1][1:]:
                raise refused("STORAGE_SERVICE_PARENT_CHANGED")
            check()
            # Callback-free final ancestry/FD CAS after the last supplied gate.
            # Never create through a stale parent FD following provider drift.
            current = os.fstat(descriptor)
            if (_ancestry(parent, None) != ancestry
                    or (current.st_dev, current.st_ino) != ancestry[-1][1:]):
                raise refused("STORAGE_SERVICE_PARENT_CHANGED")
            os.mkdir(self._leaf, 0o700, dir_fd=descriptor)
            self._created = True  # Literal return retained before the next gate.
            check()
            self._binding = _directory(_filesystem(check, os.stat, self._leaf, dir_fd=descriptor, follow_symlinks=False))
            if (_directory(_filesystem(check, os.lstat, namespace)) != self._binding
                    or _filesystem(check, os.listdir, namespace)):
                raise refused("STORAGE_SERVICE_NAMESPACE_CHANGED")
            check()
            if _ancestry(parent, check) != ancestry:
                raise refused("STORAGE_SERVICE_APPROVAL_OR_NAMESPACE_CHANGED")
            self._ready = True
        except BaseException:
            in_error = True
            raise
        finally:
            try:
                os.close(descriptor)
            except BaseException:
                self._close_failed = True
                self._ready = False
                if not in_error:
                    raise
        return identifier

    def operation(self, owner: Any, identifier: str, context: Any, bpy: Any,
                  scenes: tuple, *, approved_root: str, check: Callable[[], None]) -> SnapshotOperation:
        """Return an original operation; caller runs/consumes in its own activation."""
        receipt = self._receipt(owner, identifier)
        if receipt.attempts >= receipt.capacity:
            raise refused("STORAGE_SERVICE_RECEIPT_CAPACITY")
        self._namespace(approved_root, check)
        receipt.attempts += 1  # Constructor/source failure cannot recycle a turn.
        return SnapshotOperation(context, bpy, scenes, self._root, receipt.journal)

    def cleanup(self, owner: Any, identifier: str, context: Any, *, approved_root: str,
                check: Callable[[], None]) -> dict:
        """Fresh request, current approval, original journal-held owners only.

        No caller path or serialized ownership is accepted. Unknown/unissued
        owners remain retained. The original cleanup primitive renews its own
        required permissions/control and retires witnesses before deletion.
        """
        receipt = self._receipt(owner, identifier)
        self._namespace(approved_root, check)
        for cell in receipt.journal.rows:
            _owners, state, slots = cleanup_state(receipt.journal, cell)
            original = dict(slots)["owner"].__get__(state, type(state))
            if original is None:
                continue
            if type(original) is not SnapshotOwner or tuple.__getitem__(original, 0) is not receipt.journal:
                raise refused("STORAGE_SERVICE_ORIGINAL_OWNER_CHANGED")
            self._namespace(approved_root, check)
            cleanup_step(context, receipt.journal, original)
        return self.receipt(owner, identifier)

    def receipt(self, owner: Any, identifier: str) -> dict:
        """Cached Python facts only: no gate, provider, filesystem or native reads."""
        receipt = self._receipt(owner, identifier)
        artifacts = []
        journal = receipt.journal.snapshot()
        for cell in receipt.journal.rows:
            _owners, state, slots = cleanup_state(receipt.journal, cell)
            original = dict(slots)["owner"].__get__(state, type(state))
            if original is not None:
                artifacts.append(cleanup_receipt(receipt.journal, original))
        return {"schema": "private_storage_snapshot_service_receipt_v1", "receipt_id": identifier,
                "capacity": receipt.capacity, "attempts": receipt.attempts,
                "namespace": self._root, "namespace_created": self._created, "namespace_ready": self._ready,
                "descriptor_close_failed": self._close_failed,
                "journal": journal, "original_owners": artifacts,
                "shipping_caller_qualified": False, "durable_backup_qualified": False,
                "current_pixels_backup_qualified": False}

    def receipts(self, owner: Any) -> tuple[dict, ...]:
        self._owned(owner)
        return tuple(self.receipt(owner, identifier) for identifier in self._receipts)
