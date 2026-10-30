# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed owned inspection-file facts, without providers or live Blender data.

This private prerequisite is not yet attached to runtime jobs. Its caller must
retain the exact journal before entering the writer; the later cloth integration
must establish that ownership, including failed admission and history eviction.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from types import MemberDescriptorType

from .errors import BridgeError, ErrorCode

MAX_SNAPSHOTS = 256
_BOOLS = (
    "reserved", "directory_entered", "directory_returned", "native_entered", "native_returned",
    "parser_entered", "parser_returned", "identity_verified", "consumed", "cleanup_entered",
    "cleanup_returned", "stopped", "failed",
)
_TEXT = ("root", "directory", "filepath")


def refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, "Owned inspection-file evidence is unavailable.",
                       {"reason": reason, "verification_required": True, "durable_backup_qualified": False})


@dataclass(slots=True, eq=False)
class SnapshotCell:
    reserved: bool = False
    root: str = ""
    directory: str = ""
    filepath: str = ""
    root_identity: tuple = ()
    directory_identity: tuple = ()
    file_identity: tuple = ()
    file_sha256: str | None = None
    file_bytes: int | None = None
    available_memory_bytes: int | None = None
    available_disk_bytes: int | None = None
    directory_entered: bool = False
    directory_returned: bool = False
    native_entered: bool = False
    native_returned: bool = False
    parser_entered: bool = False
    parser_returned: bool = False
    identity_verified: bool = False
    consumed: bool = False
    cleanup_entered: bool = False
    cleanup_returned: bool = False
    stopped: bool = False
    failed: bool = False
    native_seconds: float | None = None


_CELL_KIND = SnapshotCell
_CELL_SLOTS = tuple((name, vars(SnapshotCell)[name]) for name in SnapshotCell.__slots__)


def _valid_class() -> None:
    if SnapshotCell is not _CELL_KIND:
        raise refused("SNAPSHOT_CELL_CLASS_CHANGED")
    namespace = type.__dict__["__dict__"].__get__(_CELL_KIND)
    if (namespace.get("__getattribute__", object.__getattribute__) is not object.__getattribute__
            or namespace.get("__setattr__", object.__setattr__) is not object.__setattr__
            or "__getattr__" in namespace
            or any(type(slot) is not MemberDescriptorType or namespace.get(name) is not slot
                   for name, slot in _CELL_SLOTS)):
        raise refused("SNAPSHOT_CELL_CLASS_CHANGED")


def cell_slots(cell: SnapshotCell) -> tuple:
    """Retain C member descriptors before native entry, never a stopped getter."""
    _valid_class()
    if type(cell) is not SnapshotCell:
        raise refused("SNAPSHOT_CELL_TYPE_CHANGED")
    return _CELL_SLOTS


def _plain_cell(cell: SnapshotCell) -> dict:
    _valid_class()
    if type(cell) is not SnapshotCell:
        raise refused("SNAPSHOT_CELL_TYPE_CHANGED")
    values = {name: slot.__get__(cell, SnapshotCell) for name, slot in _CELL_SLOTS}
    if any(type(values[name]) is not bool for name in _BOOLS):
        raise refused("SNAPSHOT_CELL_BOOLEAN_CHANGED")
    for name in _TEXT:
        value = values[name]
        if type(value) is not str or len(value) > 4096 or "\0" in value:
            raise refused("SNAPSHOT_CELL_PATH_CHANGED")
    for name, lengths in (("root_identity", (0, 2)), ("directory_identity", (0, 2)), ("file_identity", (0, 4))):
        value = values[name]
        if (type(value) is not tuple or len(value) not in lengths
                or any(type(item) is not int or item < 0 for item in value)):
            raise refused("SNAPSHOT_CELL_IDENTITY_CHANGED")
    digest = values["file_sha256"]
    if digest is not None and (type(digest) is not str or len(digest) != 64
                               or any(char not in "0123456789abcdef" for char in digest)):
        raise refused("SNAPSHOT_CELL_DIGEST_CHANGED")
    size = values["file_bytes"]
    if size is not None and (type(size) is not int or not 0 < size <= 1024**3):
        raise refused("SNAPSHOT_CELL_SIZE_CHANGED")
    for name in ("available_memory_bytes", "available_disk_bytes"):
        value = values[name]
        if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
            raise refused("SNAPSHOT_CELL_RESOURCES_CHANGED")
    seconds = values["native_seconds"]
    if seconds is not None and (type(seconds) is not float or not 0 <= seconds < float("inf")):
        raise refused("SNAPSHOT_CELL_DURATION_CHANGED")
    for later, earlier in (("directory_returned", "directory_entered"), ("native_entered", "directory_returned"),
                           ("native_returned", "native_entered"), ("parser_entered", "native_returned"),
                           ("parser_returned", "parser_entered"), ("identity_verified", "parser_returned"),
                           ("consumed", "identity_verified"), ("cleanup_returned", "cleanup_entered")):
        if values[later] and not values[earlier]:
            raise refused("SNAPSHOT_CELL_PREFIX_CHANGED")
    if values["reserved"]:
        if not all(values[name] for name in _TEXT) or len(values["root_identity"]) != 2:
            raise refused("SNAPSHOT_CELL_RESERVATION_CHANGED")
    elif any(values[name] for name in _BOOLS if name != "reserved"):
        raise refused("SNAPSHOT_CELL_UNRESERVED_EFFECT")
    values["retained_directory_possible"] = values["directory_entered"] and not values["cleanup_returned"]
    values["retained_file_possible"] = values["native_entered"] and not values["cleanup_returned"]
    values["native_completion_means_source_preserved"] = False
    for name in ("root_identity", "directory_identity", "file_identity"):
        values[name] = list(values[name])
    return values


@dataclass(slots=True, eq=False)
class _CleanupState:
    # Detached Python/file facts only; never a native ID, frame or driver.
    owner: object = None
    unlink_entered: bool = False
    unlink_returned: bool = False
    rmdir_entered: bool = False
    rmdir_returned: bool = False
    failed: bool = False
    retained_unknown: bool = False
    close_failed: bool = False


_CLEANUP_KIND = _CleanupState
_CLEANUP_SLOTS = tuple((name, vars(_CleanupState)[name]) for name in _CleanupState.__slots__)
_OWNER_ISSUER = object()


class SnapshotOwner(tuple):
    """Opaque original ownership, never reconstructed from journal receipts.

    This private structured boundary is not an arbitrary-Python sandbox. No
    public endpoint accepts an owner, ownership facts or filesystem paths.
    """
    __slots__ = ()

    def __new__(cls, issuer, journal, cell, root, leaf, root_binding, directory_binding, file_binding=None):
        if issuer is not _OWNER_ISSUER or cls is not _OWNER_KIND:
            raise refused("SNAPSHOT_OWNER_NOT_ISSUED")
        return tuple.__new__(cls, (journal, cell, root, leaf, root_binding, directory_binding, file_binding))


_OWNER_KIND = SnapshotOwner


def cleanup_state(journal, cell):
    """Return exact preallocated owner state without foreign dispatch."""
    cell_slots(cell)
    rows = _journal_rows(journal)
    namespace = type.__dict__["__dict__"].__get__(_JOURNAL_KIND)
    if namespace.get("_owners") is not _JOURNAL_OWNERS:
        raise refused("SNAPSHOT_OWNER_TABLE_CHANGED")
    owners = _JOURNAL_OWNERS.__get__(journal, _JOURNAL_KIND)
    if type(owners) is not tuple or len(owners) != len(rows):
        raise refused("SNAPSHOT_OWNER_TABLE_CHANGED")
    if _CleanupState is not _CLEANUP_KIND:
        raise refused("SNAPSHOT_CLEANUP_CLASS_CHANGED")
    cleanup_namespace = type.__dict__["__dict__"].__get__(_CLEANUP_KIND)
    if (cleanup_namespace.get("__getattribute__", object.__getattribute__) is not object.__getattribute__
            or cleanup_namespace.get("__setattr__", object.__setattr__) is not object.__setattr__
            or "__getattr__" in cleanup_namespace
            or any(cleanup_namespace.get(name) is not slot or type(slot) is not MemberDescriptorType
                   for name, slot in _CLEANUP_SLOTS)):
        raise refused("SNAPSHOT_CLEANUP_CLASS_CHANGED")
    for row, state in zip(rows, owners, strict=True):
        if type(state) is not _CLEANUP_KIND:
            raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
        if row is cell:
            return owners, state, _CLEANUP_SLOTS
    raise refused("SNAPSHOT_CLEANUP_CELL_NOT_ISSUED")


def mint_cleanup_owner(journal, cell, root, leaf, root_binding, directory_binding, file_binding=None):
    """Only the original native operation can issue original file ownership."""
    from . import storage_snapshot as snapshot
    frame = sys._getframe(1)
    if frame.f_code is not snapshot._OPERATION_RUN_CODE or frame.f_globals is not vars(snapshot):
        raise refused("SNAPSHOT_OWNER_NOT_ISSUED")
    _owners, state, slots = cleanup_state(journal, cell)
    owner = SnapshotOwner(_OWNER_ISSUER, journal, cell, root, leaf, root_binding, directory_binding, file_binding)
    dict(slots)["owner"].__set__(state, owner)
    return owner


def cleanup_receipt(journal, owner):
    """Provider/RNA/filesystem-free status; never serialize the capability."""
    if SnapshotOwner is not _OWNER_KIND or type(owner) is not _OWNER_KIND or tuple.__len__(owner) != 7:
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    issued_journal, cell, root, leaf, _root, _directory, file_binding = tuple.__iter__(owner)
    if issued_journal is not journal:
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    if (type(root) is not str or not root or len(root) > 4096 or "\0" in root
            or type(leaf) is not str or len(leaf) != 44 or not leaf.startswith("bcb-storage-")
            or any(ch not in "0123456789abcdef" for ch in leaf[12:])):
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    _owners, state, slots = cleanup_state(journal, cell)
    values = {name: slot.__get__(state, _CLEANUP_KIND) for name, slot in slots}
    if values.pop("owner") is not owner or any(type(value) is not bool for value in values.values()):
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    if ((values["unlink_returned"] and not values["unlink_entered"])
            or (values["rmdir_returned"] and not values["rmdir_entered"])):
        raise refused("SNAPSHOT_CLEANUP_PREFIX_CHANGED")
    return {"schema": "owned_storage_cleanup_effects_v1", "root": root, "directory_leaf": leaf,
            "original_file_identity_known": file_binding is not None, **values,
            "complete": values["rmdir_returned"] and not values["close_failed"],
            "runtime_retention_qualified": False,
            "durable_backup_qualified": False, "current_pixels_backup_qualified": False,
            "hostile_same_uid_namespace_races_qualified": False}


@dataclass(frozen=True, slots=True, eq=False)
class SnapshotJournal:
    """A caller-retained bounded owner; no callback, driver or RNA references."""
    rows: tuple
    _owners: tuple

    def __init__(self, capacity: int):
        if type(capacity) is not int or not 1 <= capacity <= MAX_SNAPSHOTS:
            raise refused("SNAPSHOT_JOURNAL_CAPACITY")
        if _CleanupState is not _CLEANUP_KIND:
            raise refused("SNAPSHOT_CLEANUP_CLASS_CHANGED")
        object.__setattr__(self, "rows", tuple(SnapshotCell() for _ in range(capacity)))
        object.__setattr__(self, "_owners", tuple(_CleanupState() for _ in range(capacity)))

    def reserve(self, root: str, directory: str, filepath: str, root_identity: tuple) -> SnapshotCell:
        # Validate all existing cells before selecting a free one. A corrupt
        # slot cannot silently become an evicted or freshly rebaselined receipt.
        _snapshot_journal(self)
        if (any(type(value) is not str or not value or len(value) > 4096 or "\0" in value
                for value in (root, directory, filepath))
                or type(root_identity) is not tuple or len(root_identity) != 2
                or any(type(value) is not int or value < 0 for value in root_identity)):
            raise refused("SNAPSHOT_RESERVATION_SHAPE")
        row = next((row for row in _journal_rows(self) if row.reserved is False), None)
        if row is None:
            raise refused("SNAPSHOT_JOURNAL_FULL")
        row.root, row.directory, row.filepath = root, directory, filepath
        row.root_identity = root_identity
        row.reserved = True
        return row

    def snapshot(self) -> dict:
        return _snapshot_journal(self)


_JOURNAL_KIND = SnapshotJournal
_JOURNAL_ROWS = vars(SnapshotJournal)["rows"]
_JOURNAL_OWNERS = vars(SnapshotJournal)["_owners"]


def _journal_rows(journal):
    if SnapshotJournal is not _JOURNAL_KIND or type(journal) is not _JOURNAL_KIND:
        raise refused("SNAPSHOT_JOURNAL_SHAPE")
    namespace = type.__dict__["__dict__"].__get__(_JOURNAL_KIND)
    if (namespace.get("__getattribute__", object.__getattribute__) is not object.__getattribute__
            or "__getattr__" in namespace or namespace.get("rows") is not _JOURNAL_ROWS):
        raise refused("SNAPSHOT_JOURNAL_CLASS_CHANGED")
    rows = _JOURNAL_ROWS.__get__(journal, _JOURNAL_KIND)
    if type(rows) is not tuple or not 1 <= len(rows) <= MAX_SNAPSHOTS:
        raise refused("SNAPSHOT_JOURNAL_SHAPE")
    return rows


def _snapshot_journal(journal):
    rows = [_plain_cell(row) for row in _journal_rows(journal)]
    return {"schema": "owned_storage_inspection_effects_v1", "capacity": len(rows),
            "snapshots": [row for row in rows if row["reserved"]],
            "runtime_retention_qualified": False, "durable_backup_qualified": False,
            "full_source_preservation_qualified": False, "native_calls_preemptible": False}
