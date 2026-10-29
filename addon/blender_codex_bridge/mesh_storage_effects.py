"""Bounded retained storage-call cells; terminal reads never consult a driver.

The aggregate retains the helper's original plain cells, not its plan or native
Object/Mesh wrappers. Entries can remain uncertain after interruption. An undo
boundary or retained ARRAY data is not an independent durable backup.
"""

from __future__ import annotations

from .errors import BridgeError, ErrorCode
from .mesh_storage_prepare import PreparationJournal


def _invalid():
    return BridgeError(ErrorCode.OPERATION_FAILED, "Storage preparation evidence is not a bounded retained journal.",
                       {"reason": "MESH_STORAGE_EFFECTS_INVALID", "verification_required": True})


class MeshStorageJournal:
    __slots__ = ("cells", "names", "sealed")

    def __init__(self, names):
        if (type(names) is not tuple or not 1 <= len(names) <= 32
                or any(type(name) is not str or not 1 <= len(name) <= 63 for name in names)
                or len(set(names)) != len(names)):
            raise _invalid()
        self.names, self.cells, self.sealed = names, [None] * len(names), False

    def attach(self, index, helper, *, _kind=PreparationJournal,
               _dict=PreparationJournal.__dict__["__dict__"]):
        """Retain the one-row helper cell BEFORE that helper is allowed entry."""
        if self.sealed or type(index) is not int or not 0 <= index < len(self.names) or self.cells[index] is not None:
            raise _invalid()
        if type(helper) is not _kind:
            raise _invalid()
        fields = _dict.__get__(helper, _kind)
        if type(fields) is not dict or any(type(key) is not str for key in fields):
            raise _invalid()
        cells = fields.get("_cells")
        if type(cells) is not tuple or len(cells) != 1 or type(cells[0]) is not dict:
            raise _invalid()
        row = cells[0]
        if any(type(key) is not str for key in row) or type(row.get("name")) is not str or row["name"] != self.names[index]:
            raise _invalid()
        self.cells[index] = row

    def seal(self):
        seal_storage_effects(self)


def seal_storage_effects(journal, *, _kind=MeshStorageJournal,
                         _sealed=MeshStorageJournal.__dict__["sealed"]):
    if type(journal) is not _kind:
        raise _invalid()
    _sealed.__set__(journal, True)


def snapshot_storage_effects(journal, *, _kind=MeshStorageJournal,
                             _names=MeshStorageJournal.__dict__["names"],
                             _cells=MeshStorageJournal.__dict__["cells"],
                             _sealed=MeshStorageJournal.__dict__["sealed"]):
    """Only held native slots and exact builtin cells; no driver/provider/RNA."""
    if type(journal) is not _kind:
        raise _invalid()
    names, cells, sealed = _names.__get__(journal, _kind), _cells.__get__(journal, _kind), _sealed.__get__(journal, _kind)
    if (type(names) is not tuple or type(cells) is not list or not 1 <= len(names) <= 32
            or len(cells) != len(names) or type(sealed) is not bool
            or any(type(name) is not str or not 1 <= len(name) <= 63 for name in names)
            or len(set(names)) != len(names)):
        raise _invalid()
    flags = ("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
             "after_storage_observed", "verified", "baseline_conflict")
    keys = (*flags, "name", "action", "entry_kind", "before_storage", "after_storage", "readback_entries",
            "readback_returns", "logical_values_sha256", "retained_physical_transition")
    rows = []
    for name, cell in zip(names, cells, strict=True):
        if cell is None:
            rows.append({"name": name, "helper_attached": False})
            continue
        if (type(cell) is not dict or len(cell) != len(keys) or any(type(key) is not str for key in cell)
                or any(key not in cell for key in keys)):
            raise _invalid()
        if any(type(cell[key]) is not bool for key in flags):
            raise _invalid()
        if (type(cell["name"]) is not str or cell["name"] != name
                or type(cell["action"]) is not str or cell["action"] not in ("MATERIALIZE_SINGLE", "NOOP_ALREADY_ARRAY")
                or type(cell["entry_kind"]) is not str or cell["entry_kind"] not in
                ("FOREACH_GET", "FULL_SLICE_ZERO_DOMAIN", "NOOP_ALREADY_ARRAY")
                or type(cell["before_storage"]) is not str or cell["before_storage"] not in ("SINGLE", "ARRAY")
                or (cell["after_storage"] is not None and
                    (type(cell["after_storage"]) is not str or cell["after_storage"] != "ARRAY"))
                or type(cell["retained_physical_transition"]) is not str or cell["retained_physical_transition"] not in
                ("NOT_ENTERED", "NOOP_ALREADY_ARRAY", "ENTERED_OUTCOME_UNKNOWN", "OBSERVED_SINGLE_TO_ARRAY")):
            raise _invalid()
        entered, returned = cell["readback_entries"], cell["readback_returns"]
        digest = cell["logical_values_sha256"]
        if (type(entered) is not int or type(returned) is not int or not 0 <= returned <= entered <= 128
                or (digest is not None and (type(digest) is not str or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)))):
            raise _invalid()
        if ((cell["data_lookup_returned"] and not cell["data_lookup_entered"])
                or (cell["materialize_entered"] and not cell["data_lookup_returned"])
                or (cell["materialize_returned"] and not cell["materialize_entered"])
                or (cell["after_storage_observed"] and cell["after_storage"] != "ARRAY")):
            raise _invalid()
        if cell["verified"] and cell["action"] == "MATERIALIZE_SINGLE" and (
                not cell["materialize_returned"] or not cell["after_storage_observed"] or digest is None or returned < 1):
            raise _invalid()
        rows.append({"helper_attached": True, **dict(cell)})
    return {"schema": "mesh_storage_retained_effects_v1", "rows": rows, "sealed": sealed,
            "materialization_entered": any(row.get("materialize_entered", False) for row in rows),
            "native_lookup_entered": any(row.get("data_lookup_entered", False) for row in rows),
            "physical_cache_passivity_claimed": False, "verification_required": True,
            "inverse_attempted": False, "requires_fresh_image_preview": True,
            "independently_measured_SINGLE_pre_values": False, "project_saved": False,
            "durable_backup": False}
