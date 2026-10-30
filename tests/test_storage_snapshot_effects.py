"""Literal inspection-file receipts survive failures without a stopped driver."""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def effects(addon_package):
    return importlib.import_module(addon_package + ".storage_snapshot_effects")


def reserve(effects, count=2):
    journal = effects.SnapshotJournal(count)
    row = journal.reserve("/owned", "/owned/session", "/owned/session/snapshot.blend", (1, 2))
    return journal, row


@pytest.mark.parametrize("capacity", [True, 0, -1, 257, 1.0, "1", None])
def test_capacity_refuses_before_allocating_cells(effects, capacity):
    with pytest.raises(effects.BridgeError, match="evidence"):
        effects.SnapshotJournal(capacity)


def test_journal_preallocates_distinct_cells_and_never_evicts_owned_receipts(effects):
    journal, first = reserve(effects)
    first.directory_entered = first.directory_returned = first.native_entered = True
    second = journal.reserve("/owned", "/owned/second", "/owned/second/snapshot.blend", (1, 2))
    assert first is not second and journal.rows[0] is first
    before = journal.snapshot()
    with pytest.raises(effects.BridgeError, match="evidence"):
        journal.reserve("/owned", "/owned/third", "/owned/third/snapshot.blend", (1, 2))
    assert journal.snapshot() == before
    assert before["snapshots"][0]["retained_file_possible"] is True
    assert before["runtime_retention_qualified"] is False
    assert before["full_source_preservation_qualified"] is False


@pytest.mark.parametrize("field,value", [
    ("native_entered", 1), ("native_returned", True), ("file_bytes", True),
    ("file_sha256", "wrong"), ("native_seconds", float("nan")), ("root_identity", [1, 2]),
    ("file_identity", (1, 2, True, 4)), ("consumed", True), ("filepath", object()),
])
def test_malformed_literal_or_impossible_prefix_never_becomes_partial_success(effects, field, value):
    journal, row = reserve(effects)
    setattr(row, field, value)
    with pytest.raises(effects.BridgeError, match="evidence"):
        journal.snapshot()


@pytest.mark.parametrize("owner,field", [("cell", "native_entered"), ("journal", "rows")])
def test_replaced_slot_refuses_before_a_foreign_getter(effects, monkeypatch, owner, field):
    journal, row = reserve(effects)
    calls = []
    cls = type(row) if owner == "cell" else type(journal)
    with monkeypatch.context() as patch:
        patch.setattr(cls, field, property(lambda *_: calls.append("foreign")))
        with pytest.raises(effects.BridgeError, match="evidence"):
            effects._snapshot_journal(journal)
    assert calls == []


@pytest.mark.parametrize("owner", ["cell", "journal"])
def test_changed_getattribute_is_not_called_by_terminal_reader(effects, monkeypatch, owner):
    journal, row = reserve(effects)
    calls = []
    cls = type(row) if owner == "cell" else type(journal)
    with monkeypatch.context() as patch:
        patch.setattr(cls, "__getattribute__", lambda *_: calls.append("foreign"))
        with pytest.raises(effects.BridgeError, match="evidence"):
            effects._snapshot_journal(journal)
    assert calls == []


def test_foreign_class_binding_is_refused_before_metaclass_attributes(effects, monkeypatch):
    journal, _row = reserve(effects)
    calls = []

    class ForeignMeta(type):
        def __getattribute__(cls, name):
            calls.append(name)
            raise AssertionError(name)

    class Foreign(metaclass=ForeignMeta):
        pass

    with monkeypatch.context() as patch:
        patch.setattr(effects, "SnapshotCell", Foreign)
        with pytest.raises(effects.BridgeError, match="evidence"):
            effects._snapshot_journal(journal)
    assert calls == []


def test_snapshot_allocation_failure_leaves_the_exact_owner_for_retry(effects, monkeypatch):
    journal, row = reserve(effects)
    row.directory_entered = row.directory_returned = row.native_entered = True
    row.stopped = row.failed = True
    with monkeypatch.context() as patch:
        def exhausted(_row):
            raise MemoryError("owned report allocation model")
        patch.setattr(effects, "_plain_cell", exhausted)
        with pytest.raises(MemoryError):
            journal.snapshot()
    assert journal.rows[0] is row
    snapshot = journal.snapshot()["snapshots"][0]
    assert snapshot["native_entered"] and not snapshot["native_returned"]
    assert snapshot["stopped"] and snapshot["retained_file_possible"]
    assert snapshot["filepath"] == "/owned/session/snapshot.blend"


def test_retained_raw_slots_can_record_c_return_without_replaced_properties(effects, monkeypatch):
    journal, row = reserve(effects)
    slots = dict(effects.cell_slots(row))
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(type(row), "native_returned", property(lambda *_: calls.append("foreign")))
        slots["native_returned"].__set__(row, True)
        with pytest.raises(effects.BridgeError):
            effects._snapshot_journal(journal)
    assert calls == [] and row.native_returned is True


def test_journal_preallocates_detached_cleanup_cells_without_recycling(effects):
    journal, row = reserve(effects)
    owners, first, slots = effects.cleanup_state(journal, row)
    assert len(owners) == 2 and owners[0] is first and owners[1] is not first
    assert dict(slots)["owner"].__get__(first, type(first)) is None
    for name, slot in slots:
        if name != "owner":
            assert slot.__get__(first, type(first)) is False
    assert journal.snapshot()["snapshots"][0]["cleanup_entered"] is False


def test_cleanup_owner_cannot_be_minted_from_receipt_paths(effects):
    journal, row = reserve(effects)
    with pytest.raises(effects.BridgeError) as failure:
        effects.mint_cleanup_owner(journal, row, "/owned", "bcb-storage-" + "0" * 32,
                                   (1, 2, 0, 0o700), (1, 3, 0, 0o700))
    assert failure.value.context["reason"] == "SNAPSHOT_OWNER_NOT_ISSUED"
    assert effects.cleanup_state(journal, row)[1].owner is None


def test_replaced_private_cleanup_slot_refuses_without_foreign_getter(effects, monkeypatch):
    journal, row = reserve(effects)
    _owners, state, _slots = effects.cleanup_state(journal, row)
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(type(state), "owner", property(lambda *_: calls.append("foreign")))
        with pytest.raises(effects.BridgeError):
            effects.cleanup_state(journal, row)
    assert calls == []
