"""Retained helper cells are evidence, never inverse or execution authority."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def effects(addon_package):
    return importlib.import_module(addon_package + ".mesh_storage_effects")


def helper(effects, name="uv", *, converted=False):
    value = object.__new__(effects.PreparationJournal)
    row = dict.fromkeys(("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
                         "after_storage_observed", "verified", "baseline_conflict"), False)
    row.update(name=name, action="MATERIALIZE_SINGLE", entry_kind="FOREACH_GET", before_storage="SINGLE",
               after_storage=None, readback_entries=0, readback_returns=0, logical_values_sha256=None,
               retained_physical_transition="NOT_ENTERED")
    if converted:
        for flag in ("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
                     "after_storage_observed", "verified"):
            row[flag] = True
        row.update(after_storage="ARRAY", readback_entries=2, readback_returns=2,
                   logical_values_sha256="a" * 64, retained_physical_transition="OBSERVED_SINGLE_TO_ARRAY")
    value._cells, value._plan = (row,), object()
    return value, row


def test_fixed_selection_attaches_original_cells_without_retaining_helper_plan(effects):
    retained = effects.MeshStorageJournal(("uv", "hidden"))
    original, cell = helper(effects)
    retained.attach(0, original)
    assert retained.cells[0] is cell
    assert all(value is not original and value is not original._plan for value in retained.cells)
    before = effects.snapshot_storage_effects(retained)
    cell["data_lookup_entered"] = True
    after = effects.snapshot_storage_effects(retained)
    assert not before["rows"][0]["data_lookup_entered"] and after["rows"][0]["data_lookup_entered"]
    assert after["rows"][1] == {"name": "hidden", "helper_attached": False}
    assert not after["inverse_attempted"] and not after["durable_backup"] and not after["project_saved"]


@pytest.mark.parametrize("names", [(), [], ("uv", "uv"), (True,), ("",), ("x" * 64,), tuple(str(x) for x in range(33))])
def test_refuses_invalid_or_unbounded_selection(effects, names):
    with pytest.raises(effects.BridgeError):
        effects.MeshStorageJournal(names)


@pytest.mark.parametrize("index", [-1, 1, True, 0., "0", None])
def test_refuses_nonliteral_or_out_of_scope_index(effects, index):
    retained = effects.MeshStorageJournal(("uv",))
    original, _cell = helper(effects)
    with pytest.raises(effects.BridgeError):
        retained.attach(index, original)
    assert retained.cells == [None]


def test_never_replaces_an_attached_or_sealed_row(effects):
    retained = effects.MeshStorageJournal(("uv", "later"))
    original, cell = helper(effects)
    retained.attach(0, original)
    with pytest.raises(effects.BridgeError):
        retained.attach(0, original)
    effects.seal_storage_effects(retained)
    second, _row = helper(effects, "later")
    with pytest.raises(effects.BridgeError):
        retained.attach(1, second)
    assert retained.cells == [cell, None]


def test_wrong_row_identity_refused_before_attachment(effects):
    retained = effects.MeshStorageJournal(("uv",))
    original, _cell = helper(effects, "foreign")
    with pytest.raises(effects.BridgeError):
        retained.attach(0, original)
    assert retained.cells == [None]


@pytest.mark.parametrize("field,value", [("materialize_entered", 1), ("readback_entries", True),
    ("readback_returns", -1), ("readback_entries", 129), ("after_storage", object()),
    ("logical_values_sha256", "bad"), ("retained_physical_transition", "UNKNOWN"),
    ("materialize_returned", True), ("verified", True)])
def test_refuses_forged_scalar_and_impossible_outcome_facts(effects, field, value):
    retained = effects.MeshStorageJournal(("uv",))
    original, row = helper(effects)
    retained.attach(0, original)
    row[field] = value
    with pytest.raises(effects.BridgeError):
        effects.snapshot_storage_effects(retained)
    assert retained.cells[0] is row


@pytest.mark.parametrize("missing", ["materialize_returned", "after_storage_observed", "logical_values_sha256"])
def test_verified_materialized_row_requires_recorded_return_and_hash(effects, missing):
    retained = effects.MeshStorageJournal(("uv",))
    original, row = helper(effects, converted=True)
    retained.attach(0, original)
    row[missing] = None if missing == "logical_values_sha256" else False
    with pytest.raises(effects.BridgeError):
        effects.snapshot_storage_effects(retained)


def test_verified_then_conflicted_row_keeps_past_observations(effects):
    retained = effects.MeshStorageJournal(("uv",))
    original, row = helper(effects, converted=True)
    retained.attach(0, original)
    row["baseline_conflict"] = True
    result = effects.snapshot_storage_effects(retained)
    assert result["rows"][0]["verified"] and result["rows"][0]["baseline_conflict"]
    assert result["materialization_entered"]


def test_foreign_namespace_key_refused_before_lookup_callbacks(effects):
    calls = []

    class Key(str):
        def __hash__(self):
            return hash("name")

        def __eq__(self, _other):
            calls.append("foreign equality")
            return True

    retained = effects.MeshStorageJournal(("uv",))
    original, cell = helper(effects)
    cell.pop("name")
    cell[Key("name")] = "uv"
    calls.clear()
    with pytest.raises(effects.BridgeError):
        retained.attach(0, original)
    assert calls == [] and retained.cells == [None]


def test_terminal_snapshot_uses_held_native_slots_without_properties(effects, monkeypatch):
    calls = []
    retained = effects.MeshStorageJournal(("uv",))
    original, _cell = helper(effects, converted=True)
    retained.attach(0, original)

    def forbidden(_self):
        calls.append("foreign property")
        raise AssertionError

    for name in ("names", "cells", "sealed"):
        monkeypatch.setattr(effects.MeshStorageJournal, name, property(forbidden))
    snapshot = effects.snapshot_storage_effects(retained)
    assert snapshot["rows"][0]["verified"] and calls == []


def test_snapshot_is_detached_from_later_helper_changes(effects):
    retained = effects.MeshStorageJournal(("uv",))
    original, row = helper(effects, converted=True)
    retained.attach(0, original)
    snapshot = effects.snapshot_storage_effects(retained)
    row["baseline_conflict"] = True
    assert snapshot["rows"][0]["baseline_conflict"] is False
    assert effects.snapshot_storage_effects(retained)["rows"][0]["baseline_conflict"] is True
