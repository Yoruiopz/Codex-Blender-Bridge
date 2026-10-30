# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded detached ViewLayer IDProperty inspection of native .blend bytes.

This private prerequisite imports no Blender modules and never wraps an RNA
pointer. File limits constrain this reader, not native serialization. A result
describes one stored group, not a project backup or complete scene projection.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import stat
import struct
from dataclasses import dataclass

MAX_FILE = 1024**3
MAX_BLOCKS = 131072
MAX_DNA = 16 * 1024**2
MAX_NAMES = 65536
MAX_TYPES = 8192
MAX_FIELDS = 131072
MAX_SCENES = 128
MAX_LAYERS = 64
MAX_PROPERTIES = 256
MAX_PROPERTY_BYTES = 65536
MAX_NAME_BYTES = 1024
READ_SIZE = 1024**2
IDP_INT, IDP_GROUP, IDP_BOOLEAN = 1, 6, 10
SCHEMA = "blend_view_layer_raw_storage_v1"
CYCLES_NAMES = (
    "pass_debug_sample_count", "use_pass_volume_direct", "use_pass_volume_indirect",
    "use_pass_shadow_catcher", "use_denoising", "denoising_store_passes",
)
CYCLES_502_NAMES = (
    *CYCLES_NAMES,
    "pass_render_time", "use_pass_volume_scatter", "use_pass_volume_transmit",
    "use_pass_volume_majorant", "denoising_pass_follow_reflections",
    "denoising_pass_use_albedo_roughness_weighting",
)
# Detached layouts from retained native format405/502 fixture files. The new
# native prerequisite must independently verify these on its exact binaries.
LAYOUT_PINS = (
    (405, "95d1d4ae88833395af7e1a1ed155f0918c8409ab7c31b7a7c05ba25053c7b8d5"),
    (502, "4fa1bdba7c1e088978f75e4d7107bcf71d6fb333befa7141cb6f58061d71d57d"),
)
LAYOUT_STRUCTS = ("ID", "Scene", "ViewLayer", "IDProperty", "IDPropertyData", "ListBase")
_ARRAY = re.compile(r"\[([0-9]+)\]")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


class StorageSnapshotError(ValueError):
    def __init__(self, reason: str, **context):
        super().__init__(reason)
        self.reason = reason
        self.context = context


def _refuse(reason: str, **context):
    raise StorageSnapshotError(reason, **context)


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii")


def _text(value, label):
    if type(value) is not str or not value or "\0" in value:
        _refuse("INPUT_TEXT_UNQUALIFIED", field=label)
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as cause:
        raise StorageSnapshotError("INPUT_TEXT_UNQUALIFIED", field=label) from cause
    if length > MAX_NAME_BYTES:
        _refuse("INPUT_TEXT_UNQUALIFIED", field=label)
    return value


@dataclass(frozen=True, slots=True)
class _Block:
    code: bytes
    size: int
    old: int
    sdna: int
    count: int
    offset: int


@dataclass(frozen=True, slots=True)
class _Field:
    name: str
    type_name: str
    offset: int
    size: int
    pointer: bool
    count: int


class _DNA:
    def __init__(self, raw):
        self.raw, self.cursor = raw, 0
        self._tag(b"SDNA")
        self._tag(b"NAME")
        self.names = self._strings(self._count(MAX_NAMES))
        self._align()
        self._tag(b"TYPE")
        self.types = self._strings(self._count(MAX_TYPES))
        if len(set(self.types)) != len(self.types):
            _refuse("SDNA_DUPLICATE_TYPE")
        self._align()
        self._tag(b"TLEN")
        self.lengths = tuple(self._number("H") for _ in self.types)
        self._align()
        self._tag(b"STRC")
        count = self._count(MAX_TYPES)
        self.structs = []
        self.by_name = {}
        total_fields = 0
        for index in range(count):
            type_index, field_count = self._number("H"), self._number("H")
            if type_index >= len(self.types):
                _refuse("SDNA_TYPE_INDEX")
            name = self.types[type_index]
            if name in self.by_name:
                _refuse("SDNA_DUPLICATE_STRUCT")
            total_fields += field_count
            if total_fields > MAX_FIELDS:
                _refuse("SDNA_FIELD_BUDGET")
            fields = []
            for _ in range(field_count):
                ft, fn = self._number("H"), self._number("H")
                if ft >= len(self.types) or fn >= len(self.names):
                    _refuse("SDNA_FIELD_INDEX")
                fields.append((ft, self.names[fn]))
            self.by_name[name] = index
            self.structs.append((name, self.lengths[type_index], tuple(fields)))
        if self.cursor != len(raw):
            _refuse("SDNA_TRAILING_BYTES")
        self.layouts = {}

    def _take(self, count):
        if count < 0 or self.cursor + count > len(self.raw):
            _refuse("SDNA_TRUNCATED")
        data = self.raw[self.cursor:self.cursor + count]
        self.cursor += count
        return data

    def _number(self, code):
        return struct.unpack("<" + code, self._take(struct.calcsize("<" + code)))[0]

    def _count(self, maximum):
        value = self._number("I")
        if not 0 < value <= maximum:
            _refuse("SDNA_COUNT_BUDGET")
        return value

    def _tag(self, value):
        if self._take(4) != value:
            _refuse("SDNA_TAG")

    def _align(self):
        self._take((-self.cursor) % 4)

    def _strings(self, count):
        values = []
        for _ in range(count):
            end = self.raw.find(b"\0", self.cursor, min(len(self.raw), self.cursor + MAX_NAME_BYTES + 1))
            if end < 0:
                _refuse("SDNA_STRING_BUDGET")
            try:
                values.append(self.raw[self.cursor:end].decode("ascii"))
            except UnicodeError as cause:
                raise StorageSnapshotError("SDNA_STRING_ENCODING") from cause
            self.cursor = end + 1
        return tuple(values)

    def layout(self, name):
        if name in self.layouts:
            return self.layouts[name]
        index = self.by_name.get(name)
        if index is None:
            _refuse("SDNA_REQUIRED_STRUCT_MISSING", struct=name)
        _, size, definitions = self.structs[index]
        if not 0 < size <= MAX_PROPERTY_BYTES:
            _refuse("SDNA_STRUCT_BUDGET", struct=name)
        fields, offset = {}, 0
        for type_index, declarator in definitions:
            match = _IDENTIFIER.search(declarator)
            if match is None:
                _refuse("SDNA_FIELD_DECLARATOR")
            field_name, count = match[0], 1
            for dimension in _ARRAY.findall(declarator):
                if len(dimension) > 10:
                    _refuse("SDNA_ARRAY_BUDGET")
                count *= int(dimension)
                if not 0 < count <= MAX_FILE:
                    _refuse("SDNA_ARRAY_BUDGET")
            pointer = "*" in declarator
            length = (8 if pointer else self.lengths[type_index]) * count
            if length < 0 or offset + length > size or field_name in fields:
                _refuse("SDNA_LAYOUT_UNQUALIFIED", struct=name)
            fields[field_name] = _Field(field_name, self.types[type_index], offset, length, pointer, count)
            offset += length
        if offset != size:
            _refuse("SDNA_IMPLICIT_PADDING_UNQUALIFIED", struct=name)
        result = index, size, fields
        self.layouts[name] = result
        return result


class _Reader:
    def __init__(self, descriptor, size):
        self.fd, self.size, self.blocks = descriptor, size, []
        header = self.read(0, min(17, size))
        if header.startswith(b"BLENDER-v405"):
            self.version, self.format, cursor, block_struct = 405, 0, 12, struct.Struct("<4siQii")
        elif header == b"BLENDER17-01v0502":
            self.version, self.format, cursor, block_struct = 502, 1, 17, struct.Struct("<4siQqq")
        else:
            _refuse("BLEND_HEADER_UNQUALIFIED")
        dna, ended = None, False
        while cursor < size:
            remaining = size - cursor
            if remaining == 8 and self.read(cursor, 8) == b"ENDB\0\0\0\0":
                ended, cursor = True, size
                break
            if remaining < block_struct.size:
                _refuse("BLEND_BLOCK_TRUNCATED")
            values = block_struct.unpack(self.read(cursor, block_struct.size))
            if self.format:
                code, sdna, old, length, count = values
            else:
                code, length, old, sdna, count = values
            cursor += block_struct.size
            if length < 0 or count < 0 or sdna < 0 or length > size - cursor:
                _refuse("BLEND_BLOCK_RANGE")
            if code == b"ENDB":
                if length != 0 or cursor != size:
                    _refuse("BLEND_END_BLOCK")
                ended = True
                break
            if len(self.blocks) >= MAX_BLOCKS:
                _refuse("BLEND_BLOCK_BUDGET")
            block = _Block(code, length, old, sdna, count, cursor)
            self.blocks.append(block)
            if code == b"DNA1":
                if dna is not None or length > MAX_DNA:
                    _refuse("SDNA_BLOCK_UNQUALIFIED")
                dna = self.read(cursor, length)
            cursor += length
        if not ended or dna is None:
            _refuse("BLEND_INCOMPLETE")
        self.dna = _DNA(dna)
        if any(block.sdna >= len(self.dna.structs) for block in self.blocks):
            _refuse("BLEND_SDNA_INDEX")
        layouts = []
        for name in LAYOUT_STRUCTS:
            _, size, fields = self.dna.layout(name)
            layouts.append([name, size, [[field.name, field.type_name, field.offset, field.size,
                                        field.pointer, field.count] for field in fields.values()]])
        self.layout_fingerprint = hashlib.sha256(_canonical(layouts)).hexdigest()
        if (self.version, self.layout_fingerprint) not in LAYOUT_PINS:
            _refuse("SDNA_NATIVE_LAYOUT_UNQUALIFIED")
        self.addressed = sorted((block for block in self.blocks if block.old and block.size), key=lambda block: block.old)
        self.starts = [block.old for block in self.addressed]
        maximum = 0
        self.ends = []
        for block in self.addressed:
            if block.old + block.size > 2**64:
                _refuse("BLEND_ADDRESS_OVERFLOW")
            maximum = max(maximum, block.old + block.size)
            self.ends.append(maximum)
        self.property_bytes = 0
        self.property_offsets = set()

    def read(self, offset, count):
        if offset < 0 or count < 0 or offset + count > self.size or count > MAX_DNA:
            _refuse("READ_RANGE")
        os.lseek(self.fd, offset, os.SEEK_SET)
        data = os.read(self.fd, count)
        if len(data) != count:
            _refuse("FILE_TRUNCATED")
        return data

    def resolve(self, address, name):
        index, size, _ = self.dna.layout(name)
        if self.format:
            # Format1 stores stable identifiers, not address ranges. Identifier
            # hints advance by sixteen regardless of the serialized block size.
            # Never interpret another block's payload length as an ID interval.
            left = bisect.bisect_left(self.starts, address)
            right = bisect.bisect_right(self.starts, address)
            if right - left != 1:
                _refuse("BLEND_POINTER_UNQUALIFIED", struct=name)
            block = self.addressed[left]
            if block.sdna != index or block.count != 1 or block.size != size:
                _refuse("BLEND_POINTER_UNQUALIFIED", struct=name)
            return block.offset
        candidates, overlaps = [], 0
        cursor = bisect.bisect_right(self.starts, address) - 1
        while cursor >= 0 and self.ends[cursor] > address:
            block = self.addressed[cursor]
            delta = address - block.old
            if 0 <= delta < block.size:
                overlaps += 1
            if (delta >= 0 and delta + size <= block.size and block.sdna == index
                    and delta % size == 0 and block.count * size == block.size):
                candidates.append(block.offset + delta)
            cursor -= 1
        if overlaps != 1 or len(candidates) != 1:
            _refuse("BLEND_POINTER_UNQUALIFIED", struct=name)
        return candidates[0]

    def field(self, owner, struct_name, name, type_name, *, pointer=False, count=None):
        fields = self.dna.layout(struct_name)[2]
        field = fields.get(name)
        if (field is None or field.type_name != type_name or field.pointer is not pointer
                or (count is not None and field.count != count)):
            _refuse("SDNA_REQUIRED_FIELD_UNQUALIFIED", struct=struct_name, field=name)
        return owner + field.offset, field

    def pointer(self, owner, struct_name, name, type_name):
        offset, field = self.field(owner, struct_name, name, type_name, pointer=True, count=1)
        if field.size != 8:
            _refuse("SDNA_POINTER_WIDTH")
        return struct.unpack("<Q", self.read(offset, 8))[0]

    def integer(self, owner, struct_name, name, code, type_name):
        offset, field = self.field(owner, struct_name, name, type_name, count=1)
        if field.size != struct.calcsize("<" + code):
            _refuse("SDNA_PRIMITIVE_WIDTH")
        return struct.unpack("<" + code, self.read(offset, field.size))[0]

    def string(self, owner, struct_name, name):
        offset, field = self.field(owner, struct_name, name, "char")
        if field.count != field.size or not 1 <= field.size <= MAX_NAME_BYTES:
            _refuse("SDNA_NAME_ARRAY")
        raw = self.read(offset, field.size)
        end = raw.find(b"\0")
        if end < 0:
            _refuse("RAW_NAME_UNTERMINATED")
        try:
            return raw[:end].decode("utf-8")
        except UnicodeError as cause:
            raise StorageSnapshotError("RAW_NAME_ENCODING") from cause

    def list_nodes(self, owner, struct_name, list_field, target, maximum):
        offset, _ = self.field(owner, struct_name, list_field, "ListBase", count=1)
        current = self.pointer(offset, "ListBase", "first", "void")
        last = self.pointer(offset, "ListBase", "last", "void")
        if bool(current) != bool(last):
            _refuse("RAW_LIST_ENDPOINTS")
        seen, previous = set(), 0
        while current:
            if current in seen or len(seen) >= maximum:
                _refuse("RAW_LIST_CYCLE_OR_BUDGET")
            seen.add(current)
            record = self.resolve(current, target)
            if self.pointer(record, target, "prev", target) != previous:
                _refuse("RAW_LIST_PREVIOUS_POINTER")
            yield record
            previous, current = current, self.pointer(record, target, "next", target)
        if previous != last:
            _refuse("RAW_LIST_TAIL")

    def property(self, offset):
        if offset not in self.property_offsets:
            self.property_offsets.add(offset)
            self.property_bytes += self.dna.layout("IDProperty")[1]
            if len(self.property_offsets) > MAX_PROPERTIES or self.property_bytes > MAX_PROPERTY_BYTES:
                _refuse("RAW_PROPERTY_BYTE_OR_NODE_BUDGET")
        return {"name": self.string(offset, "IDProperty", "name"),
                "type": self.integer(offset, "IDProperty", "type", "b", "char"),
                "subtype": self.integer(offset, "IDProperty", "subtype", "B", "char"),
                "flag": self.integer(offset, "IDProperty", "flag", "H", "short"),
                "len": self.integer(offset, "IDProperty", "len", "i", "int"),
                "totallen": self.integer(offset, "IDProperty", "totallen", "i", "int")}

    def group(self, offset):
        header = self.property(offset)
        if header["type"] != IDP_GROUP:
            _refuse("RAW_GROUP_TYPE", raw_type=header["type"])
        data, _ = self.field(offset, "IDProperty", "data", "IDPropertyData", count=1)
        rows = []
        for child in self.list_nodes(data, "IDPropertyData", "group", "IDProperty", MAX_PROPERTIES):
            rows.append((child, self.property(child)))
        if header["len"] != len(rows) or len({row["name"] for _, row in rows}) != len(rows):
            _refuse("RAW_GROUP_LENGTH_OR_NAMES")
        return header, rows

    def inspect(self, scene_name, layer_name, property_name, allowed):
        scene_index, scene_size, _ = self.dna.layout("Scene")
        scenes, found = 0, []
        for block in self.blocks:
            if block.sdna != scene_index or block.code == b"DNA1":
                continue
            if block.count * scene_size != block.size:
                _refuse("SCENE_BLOCK_LAYOUT")
            scenes += block.count
            if scenes > MAX_SCENES:
                _refuse("SCENE_COUNT_BUDGET")
            for index in range(block.count):
                scene = block.offset + index * scene_size
                id_offset, _ = self.field(scene, "Scene", "id", "ID", count=1)
                if self.string(id_offset, "ID", "name") == "SC" + scene_name:
                    found.append(scene)
        if len(found) != 1:
            _refuse("SCENE_IDENTITY_UNQUALIFIED")
        layers = []
        for layer in self.list_nodes(found[0], "Scene", "view_layers", "ViewLayer", MAX_LAYERS):
            if self.string(layer, "ViewLayer", "name") == layer_name:
                layers.append(layer)
        if len(layers) != 1:
            _refuse("VIEW_LAYER_IDENTITY_UNQUALIFIED")
        storage = "id_properties" if self.version == 405 else "system_properties"
        root_address = self.pointer(layers[0], "ViewLayer", storage, "IDProperty")
        result = {"scene_name": scene_name, "view_layer_name": layer_name, "property_name": property_name,
                  "storage": "USER" if self.version == 405 else "SYSTEM", "state": "ABSENT",
                  "root_present": bool(root_address), "root_header": None, "property": None,
                  "children": [], "scope": "One named raw group; other root payloads are not inspected"}
        if not root_address:
            return result
        root, rows = self.group(self.resolve(root_address, "IDProperty"))
        result["root_header"] = root
        matches = [(offset, row) for offset, row in rows if row["name"] == property_name]
        if not matches:
            return result
        group_offset, _ = matches[0]
        group_header, children = self.group(group_offset)
        result.update(state="GROUP", property=group_header)
        for offset, row in children:
            if row["name"] not in allowed:
                _refuse("RAW_PROPERTY_NAME_UNQUALIFIED", name=row["name"])
            if row["type"] not in (IDP_INT, IDP_BOOLEAN):
                _refuse("RAW_PROPERTY_TYPE_UNQUALIFIED", name=row["name"], raw_type=row["type"])
            data, _ = self.field(offset, "IDProperty", "data", "IDPropertyData", count=1)
            row["value"] = self.integer(data, "IDPropertyData", "val", "i", "int")
            row["value2"] = self.integer(data, "IDPropertyData", "val2", "i", "int")
            if row["type"] == IDP_BOOLEAN and row["value"] not in (0, 1):
                _refuse("RAW_BOOLEAN_REPRESENTATION_UNQUALIFIED", name=row["name"])
            result["children"].append(row)
        return result


def inspect_view_layer_storage(path, scene_name, view_layer_name, *, property_name="cycles", allowed_names=None):
    """Return detached typed bytes or raise before any native/RNA getter.

    The caller must separately bind this file to one live source operation.
    This reader has no authority to resolve an original Blender pointer.
    """
    if type(path) is not str or not os.path.isabs(path) or "\0" in path:
        _refuse("INPUT_PATH_UNQUALIFIED")
    try:
        path_bytes = len(path.encode("utf-8"))
    except UnicodeError as cause:
        raise StorageSnapshotError("INPUT_PATH_UNQUALIFIED") from cause
    if path_bytes > 4096:
        _refuse("INPUT_PATH_UNQUALIFIED")
    scene_name = _text(scene_name, "scene_name")
    view_layer_name = _text(view_layer_name, "view_layer_name")
    property_name = _text(property_name, "property_name")
    if allowed_names is not None:
        if type(allowed_names) is not tuple or not 0 < len(allowed_names) <= 64:
            _refuse("INPUT_ALLOWED_NAMES_UNQUALIFIED")
        for name in allowed_names:
            _text(name, "allowed_name")
        if len(set(allowed_names)) != len(allowed_names):
            _refuse("INPUT_ALLOWED_NAMES_UNQUALIFIED")
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_FILE:
        _refuse("FILE_SHAPE_OR_BUDGET")
    expected = _identity(before)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        if _identity(os.fstat(descriptor)) != expected:
            _refuse("FILE_IDENTITY_CHANGED")
        reader = _Reader(descriptor, before.st_size)
        names = allowed_names if allowed_names is not None else (CYCLES_NAMES if reader.version == 405 else CYCLES_502_NAMES)
        data = reader.inspect(scene_name, view_layer_name, property_name, names)
        digest = hashlib.sha256()
        os.lseek(descriptor, 0, os.SEEK_SET)
        remaining = before.st_size
        while remaining:
            raw = os.read(descriptor, min(READ_SIZE, remaining))
            if not raw:
                _refuse("FILE_TRUNCATED")
            digest.update(raw)
            remaining -= len(raw)
        if (_identity(os.fstat(descriptor)) != expected or _identity(os.lstat(path)) != expected
                or os.read(descriptor, 1)):
            _refuse("FILE_IDENTITY_CHANGED")
        return {"schema": SCHEMA, "file_version": reader.version, "file_format": reader.format,
                "layout_fingerprint": reader.layout_fingerprint,
                "pointer_bytes": 8, "endianness": "little", "file_bytes": before.st_size,
                "file_sha256": digest.hexdigest(), "file_identity": list(expected),
                "storage": data, "storage_fingerprint": hashlib.sha256(_canonical(data)).hexdigest(),
                "original_RNA_getter_invoked": False, "durable_backup_qualified": False}
    finally:
        os.close(descriptor)
