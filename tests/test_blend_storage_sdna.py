"""Detached raw storage models; no result qualifies native writer effects."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import struct
from typing import ClassVar

import pytest


@pytest.fixture
def reader(addon_package):
    return importlib.import_module(addon_package + ".blend_storage_sdna")


class BlendModel:
    """Small self-contained native-format files with explicit model layouts."""

    definitions = (
        ("ListBase", (("void", "*first"), ("void", "*last"))),
        ("ID", (("char", "name[66]"), ("char", "_pad[6]"))),
        ("Scene", (("ID", "id"), ("ListBase", "view_layers"))),
        ("ViewLayer", (("ViewLayer", "*next"), ("ViewLayer", "*prev"), ("char", "name[64]"),
                       ("IDProperty", "*id_properties"), ("IDProperty", "*system_properties"))),
        ("IDPropertyData", (("void", "*pointer"), ("ListBase", "group"), ("int", "val"), ("int", "val2"))),
        ("IDProperty", (("IDProperty", "*next"), ("IDProperty", "*prev"), ("char", "type"),
                        ("char", "subtype"), ("short", "flag"), ("char", "name[64]"), ("char", "_pad[4]"),
                        ("IDPropertyData", "data"), ("int", "len"), ("int", "totallen"))),
    )
    sizes: ClassVar[dict[str, int]] = {"void": 0, "char": 1, "short": 2, "int": 4, "ListBase": 16, "ID": 72, "Scene": 88,
             "ViewLayer": 96, "IDPropertyData": 32, "IDProperty": 128}

    def __init__(self, version):
        self.version = version
        self.layouts = {}
        self.indices = {name: index for index, (name, _) in enumerate(self.definitions)}
        for name, definitions in self.definitions:
            fields, offset = {}, 0
            for typ, declarator in definitions:
                count = int(declarator.partition("[")[2].partition("]")[0]) if "[" in declarator else 1
                field = declarator.lstrip("*").partition("[")[0]
                pointer = declarator.startswith("*")
                size = (8 if pointer else self.sizes[typ]) * count
                fields[field] = (typ, offset, size, pointer, count)
                offset += size
            assert offset == self.sizes[name]
            self.layouts[name] = fields
        self.blocks = []

    def record(self, name):
        return bytearray(self.sizes[name])

    def put(self, record, name, field, value):
        typ, offset, size, pointer, _ = self.layouts[name][field]
        if type(value) is str:
            raw = value.encode() + b"\0"
            assert len(raw) <= size
            record[offset:offset + len(raw)] = raw
        else:
            code = "Q" if pointer else {"char": "b", "short": "H", "int": "i"}[typ]
            struct.pack_into("<" + code, record, offset, value)

    def embed(self, record, name, field, child):
        _, offset, size, _, _ = self.layouts[name][field]
        assert len(child) == size
        record[offset:offset + size] = child

    def linked(self, first, last):
        value = self.record("ListBase")
        self.put(value, "ListBase", "first", first)
        self.put(value, "ListBase", "last", last)
        return value

    def prop(self, name, typ=6, *, first=0, last=0, length=0, value=0, flag=0, next_address=0, previous=0):
        record = self.record("IDProperty")
        for field, item in (("name", name), ("type", typ), ("flag", flag), ("len", length),
                            ("next", next_address), ("prev", previous)):
            self.put(record, "IDProperty", field, item)
        data = self.record("IDPropertyData")
        self.embed(data, "IDPropertyData", "group", self.linked(first, last))
        self.put(data, "IDPropertyData", "val", value)
        self.embed(record, "IDProperty", "data", data)
        return record

    def add(self, name, address, record, code=b"DATA"):
        self.blocks.append((code, address, self.indices[name], 1, bytes(record)))

    def dna(self):
        types = list(self.sizes)
        names = list(dict.fromkeys(field for _, definitions in self.definitions for _, field in definitions))
        result = bytearray(b"SDNANAME" + struct.pack("<I", len(names)))
        result += b"\0".join(value.encode() for value in names) + b"\0"
        result += b"\0" * (-len(result) % 4)
        result += b"TYPE" + struct.pack("<I", len(types))
        result += b"\0".join(value.encode() for value in types) + b"\0"
        result += b"\0" * (-len(result) % 4)
        result += b"TLEN" + struct.pack("<" + "H" * len(types), *(self.sizes[name] for name in types))
        result += b"\0" * (-len(result) % 4)
        result += b"STRC" + struct.pack("<I", len(self.definitions))
        for name, definitions in self.definitions:
            result += struct.pack("<HH", types.index(name), len(definitions))
            for typ, field in definitions:
                result += struct.pack("<HH", types.index(typ), names.index(field))
        return bytes(result)

    def pin(self):
        rows = []
        for name in ("ID", "Scene", "ViewLayer", "IDProperty", "IDPropertyData", "ListBase"):
            fields = [[field, typ, offset, size, pointer, count]
                      for field, (typ, offset, size, pointer, count) in self.layouts[name].items()]
            rows.append([name, self.sizes[name], fields])
        raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        return self.version, hashlib.sha256(raw).hexdigest()

    def output(self):
        header = b"BLENDER-v405" if self.version == 405 else b"BLENDER17-01v0502"
        result = bytearray(header)
        for code, address, index, count, raw in [*self.blocks, (b"DNA1", 0, 0, 1, self.dna())]:
            result += self.block_header(code, len(raw), address, index, count)
            result += raw
        result += self.block_header(b"ENDB", 0, 0, 0, 0)
        return bytes(result)

    def block_header(self, code, size, address, index, count):
        return (struct.pack("<4siQii", code, size, address, index, count) if self.version == 405 else
                struct.pack("<4siQqq", code, index, address, size, count))


@pytest.fixture(params=[405, 502])
def blend_model(request, reader, monkeypatch):
    model = BlendModel(request.param)
    # Miniature layouts are explicit models, never an alternate public mode.
    monkeypatch.setattr(reader, "LAYOUT_PINS", (model.pin(),))
    return model


def complete_model(model, *, root=True, target=True, target_type=6, children=(("enabled", 10, 1, 0),),
                   other_storage=False, property_name="cycles"):
    scene = model.record("Scene")
    identifier = model.record("ID")
    model.put(identifier, "ID", "name", "SCScene")
    model.embed(scene, "Scene", "id", identifier)
    model.embed(scene, "Scene", "view_layers", model.linked(0x2000, 0x2000))
    model.add("Scene", 0x1000, scene, b"SC\0\0")
    layer = model.record("ViewLayer")
    model.put(layer, "ViewLayer", "name", "Layer")
    field = "id_properties" if model.version == 405 else "system_properties"
    if other_storage:
        field = "system_properties" if field == "id_properties" else "id_properties"
    model.put(layer, "ViewLayer", field, 0x3000 if root else 0)
    model.add("ViewLayer", 0x2000, layer)
    if root:
        model.add("IDProperty", 0x3000, model.prop("root", first=0x4000 if target else 0,
                                                  last=0x4000 if target else 0, length=int(target)))
    if root and target:
        addresses = [0x5000 + index * 0x100 for index in range(len(children))]
        model.add("IDProperty", 0x4000, model.prop(property_name, target_type, first=addresses[0] if addresses else 0,
                                                  last=addresses[-1] if addresses else 0, length=len(children)))
        for index, (name, typ, value, flag) in enumerate(children):
            model.add("IDProperty", addresses[index], model.prop(name, typ, value=value, flag=flag,
                next_address=addresses[index + 1] if index + 1 < len(addresses) else 0,
                previous=addresses[index - 1] if index else 0))
    return model


def inspect(reader, tmp_path, model, **kwargs):
    path = tmp_path / "snapshot.blend"
    raw = model.output()
    path.write_bytes(raw)
    return reader.inspect_view_layer_storage(str(path), "Scene", "Layer", allowed_names=("enabled", "second"), **kwargs)


def test_both_native_headers_keep_complete_raw_representation(reader, blend_model, tmp_path):
    model = complete_model(blend_model, children=(("enabled", 1, 2, 128), ("second", 10, 0, 0)))
    proof = inspect(reader, tmp_path, model)
    stored = proof["storage"]
    assert proof["file_version"] == model.version
    assert proof["layout_fingerprint"] == model.pin()[1]
    assert stored["state"] == "GROUP"
    assert stored["storage"] == ("USER" if model.version == 405 else "SYSTEM")
    assert [(row["name"], row["type"], row["value"], row["flag"]) for row in stored["children"]] == [
        ("enabled", 1, 2, 128), ("second", 10, 0, 0)]
    assert proof["file_sha256"] == hashlib.sha256(model.output()).hexdigest()
    assert not proof["original_RNA_getter_invoked"] and not proof["durable_backup_qualified"]


@pytest.mark.parametrize("case", ["root_absent", "target_absent", "empty_group"])
def test_absence_and_empty_group_are_distinct(reader, blend_model, tmp_path, case):
    model = complete_model(blend_model, root=case != "root_absent", target=case != "target_absent", children=())
    proof = inspect(reader, tmp_path, model)
    assert proof["storage"]["root_present"] is (case != "root_absent")
    assert proof["storage"]["state"] == ("GROUP" if case == "empty_group" else "ABSENT")
    assert proof["storage"]["children"] == []


def test_wrong_store_is_not_used_as_a_fallback(reader, blend_model, tmp_path):
    proof = inspect(reader, tmp_path, complete_model(blend_model, other_storage=True))
    assert proof["storage"]["state"] == "ABSENT"
    assert proof["storage"]["root_present"] is False


@pytest.mark.parametrize("raw_type", [1, 7, 9, 10])
def test_malformed_top_property_refuses_without_following_payload(reader, blend_model, tmp_path, raw_type):
    model = complete_model(blend_model, target_type=raw_type)
    with pytest.raises(reader.StorageSnapshotError, match="RAW_GROUP_TYPE"):
        inspect(reader, tmp_path, model)


@pytest.mark.parametrize("raw_type", [0, 2, 5, 6, 7, 8, 9])
def test_nested_array_and_id_values_refuse_before_payload_wrapping(reader, blend_model, tmp_path, raw_type):
    model = complete_model(blend_model, children=(("enabled", raw_type, 0, 0),))
    with pytest.raises(reader.StorageSnapshotError, match="RAW_PROPERTY_TYPE_UNQUALIFIED"):
        inspect(reader, tmp_path, model)


@pytest.mark.parametrize("raw_value", [-1, 2, 256])
def test_noncanonical_boolean_bytes_refuse_without_normalization(reader, blend_model, tmp_path, raw_value):
    model = complete_model(blend_model, children=(("enabled", 10, raw_value, 0),))
    with pytest.raises(reader.StorageSnapshotError, match="RAW_BOOLEAN_REPRESENTATION_UNQUALIFIED"):
        inspect(reader, tmp_path, model)


def test_unknown_array_size_never_causes_payload_expansion(reader, blend_model, tmp_path):
    model = complete_model(blend_model, children=(("enabled", 9, 0, 0),))
    code, address, dna, count, raw = model.blocks[-1]
    record = bytearray(raw)
    model.put(record, "IDProperty", "len", 2**31 - 1)
    data = model.layouts["IDProperty"]["data"][1]
    struct.pack_into("<Q", record, data, 0xDEADBEEF)
    model.blocks[-1] = code, address, dna, count, bytes(record)
    with pytest.raises(reader.StorageSnapshotError, match="RAW_PROPERTY_TYPE_UNQUALIFIED"):
        inspect(reader, tmp_path, model)


def test_unknown_and_duplicate_child_names_refuse(reader, blend_model, tmp_path):
    model = complete_model(blend_model, children=(("unexpected", 1, 1, 0),))
    with pytest.raises(reader.StorageSnapshotError, match="RAW_PROPERTY_NAME_UNQUALIFIED"):
        inspect(reader, tmp_path, model)
    model.blocks.clear()
    complete_model(model, children=(("enabled", 1, 1, 0), ("enabled", 1, 0, 0)))
    with pytest.raises(reader.StorageSnapshotError, match="RAW_GROUP_LENGTH_OR_NAMES"):
        inspect(reader, tmp_path, model)


@pytest.mark.parametrize("mutation", ["dangling", "cycle", "previous", "tail", "group_length", "address_alias"])
def test_pointer_and_list_faults_are_not_partial_success(reader, blend_model, tmp_path, mutation):
    model = complete_model(blend_model)
    index = 2 if mutation in {"tail", "group_length"} else 4
    code, address, dna, count, raw = model.blocks[index]
    record = bytearray(raw)
    if mutation == "dangling":
        model.put(record, "IDProperty", "next", 0xDEADBEEF)
    elif mutation == "cycle":
        model.put(record, "IDProperty", "next", 0x5000)
    elif mutation == "previous":
        model.put(record, "IDProperty", "prev", 0xDEADBEEF)
    elif mutation == "tail":
        data_offset = model.layouts["IDProperty"]["data"][1]
        struct.pack_into("<Q", record, data_offset + 16, 0xDEADBEEF)
    elif mutation == "group_length":
        model.put(record, "IDProperty", "len", 2)
    else:
        model.blocks.append(model.blocks[index])
    model.blocks[index] = code, address, dna, count, bytes(record)
    with pytest.raises(reader.StorageSnapshotError):
        inspect(reader, tmp_path, model)


def test_modern_stable_identifiers_are_not_pointer_ranges(reader, blend_model, tmp_path):
    model = complete_model(blend_model)
    # Format1 hints may differ by sixteen while their payloads are much larger.
    # This unrelated identifier must not masquerade as containing a ViewLayer.
    model.blocks.append((b"TEST", 0x1FF0, 0, 1, bytes(4096)))
    if model.version == 502:
        assert inspect(reader, tmp_path, model)["storage"]["state"] == "GROUP"
    else:
        with pytest.raises(reader.StorageSnapshotError, match="BLEND_POINTER_UNQUALIFIED"):
            inspect(reader, tmp_path, model)


@pytest.mark.parametrize("change", ["value", "raw_type", "flag", "absence"])
def test_storage_fingerprint_never_adopts_raw_changes(reader, blend_model, tmp_path, change):
    model = complete_model(blend_model)
    original = inspect(reader, tmp_path, model)
    model.blocks.clear()
    options = {"value": (("enabled", 10, 0, 0),), "raw_type": (("enabled", 1, 1, 0),),
               "flag": (("enabled", 10, 1, 128),), "absence": ()}
    complete_model(model, children=options[change])
    changed = inspect(reader, tmp_path, model)
    assert original["storage_fingerprint"] != changed["storage_fingerprint"]


def test_unpinned_layout_is_refused(reader, blend_model, tmp_path, monkeypatch):
    monkeypatch.setattr(reader, "LAYOUT_PINS", ())
    with pytest.raises(reader.StorageSnapshotError, match="SDNA_NATIVE_LAYOUT_UNQUALIFIED"):
        inspect(reader, tmp_path, complete_model(blend_model))


@pytest.mark.parametrize("limit,value", [("MAX_FILE", 8), ("MAX_BLOCKS", 1), ("MAX_DNA", 32),
    ("MAX_NAMES", 1), ("MAX_TYPES", 1), ("MAX_FIELDS", 1), ("MAX_LAYERS", 0),
    ("MAX_PROPERTIES", 2), ("MAX_PROPERTY_BYTES", 128)])
def test_every_independent_resource_budget_refuses(reader, blend_model, tmp_path, monkeypatch, limit, value):
    model = complete_model(blend_model)
    monkeypatch.setattr(reader, limit, value)
    with pytest.raises(reader.StorageSnapshotError):
        inspect(reader, tmp_path, model)


def test_default_cycles_profile_retains_every_pinned_declaration(reader, blend_model, tmp_path):
    expected = ("pass_debug_sample_count", "use_pass_volume_direct", "use_pass_volume_indirect",
                "use_pass_shadow_catcher", "use_denoising", "denoising_store_passes")
    if blend_model.version == 502:
        expected += ("pass_render_time", "use_pass_volume_scatter", "use_pass_volume_transmit",
                     "use_pass_volume_majorant", "denoising_pass_follow_reflections",
                     "denoising_pass_use_albedo_roughness_weighting")
    model = complete_model(blend_model, children=tuple((name, 1, index, 0) for index, name in enumerate(expected)))
    path = tmp_path / "cycles.blend"
    path.write_bytes(model.output())
    proof = reader.inspect_view_layer_storage(str(path), "Scene", "Layer")
    assert tuple(row["name"] for row in proof["storage"]["children"]) == expected
    assert tuple(row["value"] for row in proof["storage"]["children"]) == tuple(range(len(expected)))


@pytest.mark.parametrize("kind", ["header", "negative_block", "truncated", "trailing", "missing_DNA"])
def test_malformed_files_are_bounded(reader, blend_model, tmp_path, kind):
    model = complete_model(blend_model)
    raw = bytearray(model.output())
    if kind == "header":
        raw[:4] = b"\x28\xb5\x2f\xfd"
    elif kind == "negative_block":
        size_offset = (12 + 4) if model.version == 405 else (17 + 16)
        struct.pack_into("<i" if model.version == 405 else "<q", raw, size_offset, -1)
    elif kind == "truncated":
        del raw[-10:]
    elif kind == "trailing":
        raw += b"extra"
    else:
        position = raw.index(b"DNA1")
        raw[position:position + 4] = b"DATA"
    path = tmp_path / "bad.blend"
    path.write_bytes(raw)
    with pytest.raises(reader.StorageSnapshotError):
        reader.inspect_view_layer_storage(str(path), "Scene", "Layer", allowed_names=("enabled",))


def test_foreign_input_protocols_are_never_called(reader, tmp_path):
    calls = []

    class Foreign:
        def __fspath__(self):
            calls.append("path")
            return str(tmp_path)

    with pytest.raises(reader.StorageSnapshotError, match="INPUT_PATH_UNQUALIFIED"):
        reader.inspect_view_layer_storage(Foreign(), "Scene", "Layer")
    assert calls == []


def test_symlink_and_nonregular_input_refuse_before_open(reader, blend_model, tmp_path):
    target = tmp_path / "target.blend"
    target.write_bytes(complete_model(blend_model).output())
    link = tmp_path / "link.blend"
    link.symlink_to(target)
    for path in (link, tmp_path):
        with pytest.raises(reader.StorageSnapshotError, match="FILE_SHAPE_OR_BUDGET"):
            reader.inspect_view_layer_storage(str(path), "Scene", "Layer")


def test_file_mutation_is_not_certified(reader, blend_model, tmp_path, monkeypatch):
    path = tmp_path / "snapshot.blend"
    path.write_bytes(complete_model(blend_model).output())
    original = os.read
    calls = 0

    def changing_read(fd, count):
        nonlocal calls
        result = original(fd, count)
        calls += 1
        if calls == 3:
            with path.open("ab") as stream:
                stream.write(b"changed")
        return result

    monkeypatch.setattr(reader.os, "read", changing_read)
    with pytest.raises(reader.StorageSnapshotError, match="FILE_IDENTITY_CHANGED"):
        reader.inspect_view_layer_storage(str(path), "Scene", "Layer", allowed_names=("enabled",))


def test_owned_descriptor_closes_after_refusal(reader, blend_model, tmp_path, monkeypatch):
    path = tmp_path / "snapshot.blend"
    path.write_bytes(complete_model(blend_model, target_type=9).output())
    original, opened = os.open, []

    def tracked_open(*args, **kwargs):
        fd = original(*args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(reader.os, "open", tracked_open)
    with pytest.raises(reader.StorageSnapshotError, match="RAW_GROUP_TYPE"):
        reader.inspect_view_layer_storage(str(path), "Scene", "Layer")
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


@pytest.mark.skipif(not hasattr(os, "mkfifo") or not getattr(os, "O_NONBLOCK", 0), reason="POSIX FIFO race")
def test_regular_to_fifo_race_does_not_block_or_read_replacement(reader, blend_model, tmp_path, monkeypatch):
    path = tmp_path / "snapshot.blend"
    path.write_bytes(complete_model(blend_model).output())
    original = os.open

    def raced_open(requested, flags):
        assert flags & os.O_NONBLOCK
        path.unlink()
        os.mkfifo(path)
        return original(requested, flags)

    # Restore the shared os module before pytest may remove a passed tmp_path.
    # shutil's descriptor-based cleanup also calls os.open, with dir_fd.
    with monkeypatch.context() as race_patch:
        race_patch.setattr(reader.os, "open", raced_open)
        with pytest.raises(reader.StorageSnapshotError, match="FILE_IDENTITY_CHANGED"):
            reader.inspect_view_layer_storage(str(path), "Scene", "Layer")
    assert os.open is original
