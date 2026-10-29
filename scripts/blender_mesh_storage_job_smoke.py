"""Private five-process qualification of bounded mesh storage Scene jobs.

Import is inert. Root launches this fixture only through run_blender_checks and
the unchanged private display helper. No public or MCP registration is added.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import dis
import hashlib
import json
import math
import os
import platform
import queue
import shutil
import socket
import stat
import struct
import sys
import threading
import time
import traceback
from array import array
from pathlib import Path
from types import CellType, CodeType, FrameType, FunctionType, MappingProxyType, ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "MESH_STORAGE_OWNED_JOB_NATIVE_V1"
MARKER = "BLENDER_MESH_STORAGE_OWNED_JOB_OK "
REPORT = "mesh-storage-job.json"
PHASES = ("success", "cancel", "native_failure", "adversarial", "history_eviction")
CASES = {"success": {"two_rows", "recovery"}, "cancel": {"cancel_after_first"},
         "native_failure": {"failure_after_second_native"},
         "adversarial": {"permission_denial", "invalid_context", "stale_preview", "protected_scope_denial",
                         "undelivered", "pause_revoke", "disconnect"},
         "history_eviction": {"seed_cancel", "history_eviction"}}
ASSERTIONS = {"source_unchanged", "selected_active_mesh", "canonical_runtime", "original_helper_bytes",
              "no_public_registration", "all_prefix_recorded", "no_native_after_accepted_stop", "protected_measured"}
LIMITATIONS = dict.fromkeys(("public_tool", "mcp", "blender_4_5", "windows", "paired_4k_image_lifecycle",
    "full_protected_hierarchy", "physical_cache_passivity", "atomic_rollback", "durable_backup",
    "installed_package", "full_artist_workflow", "unselected_SINGLE_logical_values"), False)
BUILD = b"d13f752e3b9c"
HELPER_SHA256 = "a22034b857cc661b24ff611c4dce72a8b0c503e384b5c56f0141aa0abd915d99"
MAX_REPORT = 8 * 1024 * 1024
SELECTED = (".uv_select_face", "UVSingle")
CONTROL_CASE = "mesh_storage_first_job_control"
CONTROL_PROFILE = "MESH_STORAGE_FIRST_JOB_UNTRACED_CONTROL_V1"
CONTROL_MARKER = "BLENDER_MESH_STORAGE_FIRST_JOB_CONTROL_DIAGNOSTIC "
CONTROL_REPORT = "mesh-storage-first-job-control.json"
CONTROL_FLAGS = dict.fromkeys(("source_frame_observer_installed", "native_access_counter_observed",
    "checkpoint_boundary_observed", "complete_five_phase_qualified", "preservation_qualified",
    "cancel_disconnect_qualified", "recovery_qualified", "durable_backup_qualified",
    "full_artist_workflow_qualified", "public_tool_qualified", "installed_qualified", "release_acceptance",
    "windows_qualified"), False)
SOURCES = ("scripts/blender_mesh_storage_job_smoke.py", "scripts/run_blender_checks.py",
           "scripts/blender_artist_sidebar_smoke.py",
           "scripts/native_resources.py")
_SEAL_FRAME_LOCALS = FrameType.__dict__["f_locals"]
_SEAL_TYPE_DICT = type.__dict__["__dict__"]


def _seal_locals_kind():
    # Optimized Python3.13 frames expose a native, non-exported locals proxy.
    return type(_SEAL_FRAME_LOCALS.__get__(sys._getframe(), FrameType))


_SEAL_LOCALS_KIND = _seal_locals_kind()
_SEAL_LOCALS_ITEMS = _SEAL_TYPE_DICT.__get__(_SEAL_LOCALS_KIND)["items"]


def _seal_lookup(namespace, key):
    # Literal dict lookup can dispatch a colliding foreign key's equality.
    if type(namespace) is dict and len(namespace) <= 4096:
        supplied = dict.items(namespace)
    elif type(namespace) is _SEAL_LOCALS_KIND and len(namespace) <= 4096:
        supplied = _SEAL_LOCALS_ITEMS(namespace)
    else:
        return None
    for label, value in supplied:
        if type(label) is str and label == key:
            return value
    return None


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


def seal_diagnostic_config(module):
    """Bind the actual original verifier and its raise sites before observation."""
    assert type(module) is ModuleType
    namespace = ModuleType.__getattribute__(module, "__dict__")
    owner = namespace["SourceSeal"]
    assert type(owner) is type
    function = type.__dict__["__dict__"].__get__(owner)["verify"]
    assert type(function) is FunctionType and type(function.__code__) is CodeType
    path = Path(namespace["__file__"]).resolve(strict=True)
    assert Path(function.__code__.co_filename).resolve(strict=True) == path
    tree = ast.parse(path.read_bytes())
    classes = [node for node in tree.body if type(node) is ast.ClassDef and node.name == "SourceSeal"]
    assert len(classes) == 1
    verifiers = [node for node in classes[0].body if type(node) is ast.FunctionDef and node.name == "verify"]
    assert len(verifiers) == 1
    sections = {}
    for node in verifiers[0].body:
        if type(node) is not ast.For:
            continue
        names = [value.id for value in node.target.elts]
        section = {("module", "saved"): "module", ("owner", "mro", "saved"): "class",
                   ("fn", "code", "namespace", "defaults", "keywords", "items", "closure"): "function"}.get(tuple(names))
        if names == ["table", "saved"]:
            section = "builtins" if type(node.iter) is ast.Name else "watch"
        assert section is not None
        sections.update({child.lineno: section for child in ast.walk(node) if type(child) is ast.Raise})
    offsets = frozenset(row.offset for row in dis.get_instructions(function) if row.opname == "RAISE_VARARGS")
    assert sections and offsets
    return function.__code__, sections, offsets, owner


def seal_failure_record(frame, config):
    """Actual owned verifier facts; no RNA/provider, repr or foreign comparison.

    This observes its compiler-owned locals under the fixture's original hook.
    It does not promise passivity for a frame rewritten by another trace hook.
    """
    code, sections, offsets, seal_kind = config
    if (type(frame) is not FrameType or type(code) is not CodeType or frame.f_code is not code
            or frame.f_lasti not in offsets or frame.f_lineno not in sections):
        return None
    local = _SEAL_FRAME_LOCALS.__get__(frame, FrameType)
    def lookup(name):
        return _seal_lookup(local, name)
    section = sections[frame.f_lineno]
    result = {"schema": "STORAGE_SOURCE_SEAL_FAILURE_V1", "section": section,
              "line": frame.f_lineno, "offset": frame.f_lasti, "code_id": id(code)}

    def identity(value):
        return {"object_id": id(value), "type_id": id(type(value))}

    def token(value):
        kind = type(value)
        if kind is str and len(value) <= 256:
            return ("str", value)
        if kind is bytes and len(value) <= 64:
            return ("bytes_hex", value.hex())
        if kind is tuple and len(value) <= 4 and all(type(part) is str and len(part) <= 64 for part in value):
            return ("tuple_of_str", value)
        return None

    def entries(value, *, native_class_fields=False):
        kind = type(value)
        assert (kind is dict or kind is tuple or (native_class_fields and kind is MappingProxyType)) and len(value) <= 4096
        supplied = dict.items(value) if kind is dict else MappingProxyType.items(value) if kind is MappingProxyType else value
        rows, foreign = {}, 0
        for pair in supplied:
            assert type(pair) is tuple and len(pair) == 2
            name = token(pair[0])
            if name is None:
                foreign += 1
            else:
                rows[name] = identity(pair[1])
        return rows, foreign

    def row_index(rows, owner, width):
        assert type(rows) is tuple and len(rows) <= 4096
        for index, row in enumerate(rows):
            assert type(row) is tuple and len(row) == width
            if row[0] is owner:
                return index
        return None

    if section == "function":
        function = lookup("fn")
        result["owner"] = identity(function)
        if type(function) is FunctionType:
            result["function_name"] = function.__name__[:256] if type(function.__name__) is str else None
            fields = (("code", lookup("code"), function.__code__), ("globals", lookup("namespace"), function.__globals__),
                      ("defaults", lookup("defaults"), function.__defaults__),
                      ("kwdefaults", lookup("keywords"), function.__kwdefaults__))
            result["function_fields"] = [{"field": name, "held": identity(old), "current": identity(now)}
                                         for name, old, now in fields if old is not now]
            index, cell, old_value = lookup("index"), lookup("cell"), lookup("value")
            if type(index) is int and 0 <= index <= 64 and type(cell) is CellType:
                result["closure_index"] = index
                result["held_closure_value"] = identity(old_value)
                try:
                    result["current_closure_value"] = identity(CellType.__dict__["cell_contents"].__get__(cell))
                except ValueError:
                    result["current_closure_cell_empty"] = True
        current, saved = lookup("keywords"), lookup("items")
        owner_index = row_index(lookup("functions"), function, 7)
    else:
        owner = lookup("module") if section == "module" else lookup("owner") if section == "class" else lookup("table")
        result["owner"] = identity(owner)
        current = ModuleType.__getattribute__(owner, "__dict__") if section == "module" and type(owner) is ModuleType else _SEAL_TYPE_DICT.__get__(owner) if section == "class" and type(owner) is type else owner if type(owner) is dict else None
        saved = lookup("saved")
        if section == "watch":
            seal = lookup("self")
            assert type(seal) is seal_kind
            saved_rows = tuple.__getitem__(seal, 5)
        else:
            saved_rows = lookup("rows") if section == "module" else lookup("classes") if section == "class" else lookup("tables")
        owner_index = row_index(saved_rows, owner, 3 if section == "class" else 2)
        if section == "class":
            result["held_mro"] = identity(lookup("mro"))
            if type(owner) is type:
                result["current_mro"] = identity(type.__dict__["__mro__"].__get__(owner))
    result["tuple_index"] = owner_index
    if current is not None and saved is not None:
        old, old_foreign = entries(saved)
        now, now_foreign = entries(current, native_class_fields=section == "class")
        changes = [{"field": name, "held": old.get(name), "current": now.get(name)}
                   for name in sorted(old.keys() | now.keys()) if old.get(name) != now.get(name)]
        result.update(held_count=len(saved), current_count=len(current), held_foreign_keys=old_foreign,
                      current_foreign_keys=now_foreign, changed_fields=changes[:16],
                      changed_field_count=len(changes), changed_fields_truncated=len(changes) > 16)
        labels = {pair[0]: pair[1] for pair in saved if type(pair) is tuple and len(pair) == 2
                  and type(pair[0]) is str and pair[0] in {"__name__", "__qualname__", "__module__"}
                  and type(pair[1]) is str and len(pair[1]) <= 256}
        if labels:
            result["held_owner_labels"] = labels
    return result


def source_fingerprints():
    files = (*sorted((ROOT / "addon").rglob("*.py")), *(ROOT / name for name in SOURCES))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def domain_file(path, *, maximum=1024**3, expected=None, capture=False, sync=False, minimum=1, links=1):
    """Bounded regular-file read; a raced FIFO cannot block the open."""
    path = Path(path)
    assert path.is_absolute() and len(path.parts) <= 32 and not any(part in {".", ".."} for part in path.parts)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    directory, fd = os.open("/", directory_flags), None
    chunks, digest, count = [], hashlib.sha256(), 0
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and 1 <= before.st_nlink <= links
        assert minimum <= before.st_size <= maximum
        if sync:
            os.fsync(fd)
        while block := os.read(fd, min(1024 * 1024, maximum + 1 - count)):
            count += len(block)
            assert count <= maximum
            digest.update(block)
            if capture:
                chunks.append(block)
        after, named = os.fstat(fd), path.lstat()
        def identity(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink
        assert identity(before) == identity(after) == identity(named)
        assert count == before.st_size
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)
    binding = {"path": str(path), "bytes": count, "sha256": digest.hexdigest()}
    if expected is not None:
        assert binding == expected
    return (binding, b"".join(chunks)) if capture else binding


def domain_new(path, payload, *, maximum=MAX_REPORT):
    assert type(payload) is bytes and 0 < len(payload) <= maximum
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:offset + 1024 * 1024])
            assert written > 0
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    expected = {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    return domain_file(path, maximum=maximum, expected=expected)


def graph_mesh_metadata(mesh):
    """Original metadata only, including record pointers, never Attribute.data."""
    counts = {name: len(getattr(mesh, name)) for name in ("vertices", "edges", "polygons", "loops")}
    assert all(type(value) is int and 0 <= value <= 131_072 for value in counts.values())
    rows = []
    for attribute in mesh.attributes:
        assert len(rows) < 64
        rows.append([attribute.name, attribute.domain, attribute.data_type, attribute.storage_type, attribute.as_pointer()])
    assert len({row[0] for row in rows}) == len(rows)
    names = [layer.name for layer in mesh.uv_layers]
    assert len(names) <= 8 and len(set(names)) == len(names)
    return {"mesh": {"kind": "Mesh", "name": mesh.name, "pointer": format(mesh.as_pointer(), "x"),
                     "session_uid": str(mesh.session_uid)},
            "counts": counts, "attributes": sorted(rows), "uv_names": names}


def graph_main_id_inventory(data):
    """Owned setup census of Main ID identity, users and fake-user state."""
    properties = tuple(data.bl_rna.properties)
    assert len(properties) <= 128
    result = []
    for prop in properties:
        if prop.type != "COLLECTION":
            continue
        items = getattr(data, prop.identifier)
        assert len(items) <= 512
        rows = [[item.name, item.as_pointer(), item.session_uid, item.users, item.use_fake_user] for item in items]
        result.append([prop.identifier, sorted(rows)])
    return sorted(result)


def graph_owned_copy_oracle(data, mesh):
    """OWNED SETUP ONLY: materialize a disposable copy, then remove that ID.

    This RNA copy algorithm is independent of BMesh. Initial SINGLE values are
    setup evidence, never replayed as a later independent logical observation.
    """
    original, ids = graph_mesh_metadata(mesh), graph_main_id_inventory(data)
    counts = original["counts"]
    domains = {"POINT": "vertices", "EDGE": "edges", "FACE": "polygons", "CORNER": "loops"}
    specs = [[*row[:4], counts[domains[row[1]]]] for row in original["attributes"]]
    assert len(specs) <= 32
    logical, copy = {}, None
    try:
        copy = mesh.copy()
        assert copy is not mesh and copy.as_pointer() != mesh.as_pointer()
        assert graph_mesh_metadata(mesh) == original
        for name, domain, kind, _storage, count in specs:
            if kind not in {"BOOLEAN", "FLOAT2"}:
                assert _storage == "ARRAY"
                continue
            # Reacquire after each prior materializing COPY getter.
            attribute = copy.attributes.get(name)
            assert attribute is not None and (attribute.name, attribute.domain, attribute.data_type) == (name, domain, kind)
            values = attribute.data
            assert len(values) == count
            if kind == "BOOLEAN":
                plain = [item.value for item in values]
                assert all(type(value) is bool for value in plain)
            else:
                assert kind == "FLOAT2" and domain == "CORNER"
                plain = []
                for item in values:
                    pair = tuple(item.vector)
                    assert len(pair) == 2 and all(type(value) is float and math.isfinite(value) for value in pair)
                    plain.append([struct.pack("<f", value).hex() for value in pair])
            logical[name] = plain
            del attribute, values
            assert graph_mesh_metadata(mesh) == original
        assert graph_mesh_metadata(mesh) == original
    finally:
        if copy is not None:
            data.meshes.remove(copy)
        assert graph_mesh_metadata(mesh) == original
        assert graph_main_id_inventory(data) == ids
    raw = json.dumps(logical, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    return {"algorithm": "OWNED_SETUP_MESH_COPY_RNA_MATERIALIZE_COPY_ONLY_V1",
        "logical_values_sha256": hashlib.sha256(raw).hexdigest(), "logical_value_count": sum(map(len, logical.values())),
        "physical_inventory": specs, "original_metadata": original, "setup_logical_values": logical,
        "copy_removed_before_read_boundary": True, "original_metadata_unchanged": True,
        "Main_ID_identity_users_fake_user_inventory_restored": True, "raw_data_buffer_pointers_observed": False,
        "setup_owned_factory_only": True, "generic_attribute_inventory_proves_legacy_CustomData_absence": False,
        "postboundary_independent_SINGLE_values_observed": False}


def identity(value):
    return [value.name, value.session_uid, value.as_pointer()]


def selected_inventory(mesh):
    """Observe headers without entering a SINGLE data getter."""
    counts = {"FACE": len(mesh.polygons), "CORNER": len(mesh.loops)}
    rows = []
    for name in SELECTED:
        attribute = mesh.attributes.get(name)
        assert attribute is not None
        rows.append([name, attribute.domain, attribute.data_type, attribute.storage_type, counts[attribute.domain]])
    return rows


def attribute_values(attribute, count):
    assert attribute.storage_type == "ARRAY", "Independent original observer cannot materialize SINGLE storage"
    assert type(count) is int and 0 <= count <= 32
    # Exact official 5.2.2 class census: integer pairs use .value, whereas
    # Float2/FloatVector expose .vector. Equal widths do not imply equal fields.
    layouts = {"BOOLEAN": ("value", 0, "BOOLEAN"), "INT": ("value", 0, "INT"),
               "INT32_2D": ("value", 2, "INT"), "FLOAT2": ("vector", 2, "FLOAT"),
               "FLOAT_VECTOR": ("vector", 3, "FLOAT")}
    assert attribute.data_type in layouts, "Independent ARRAY observer has no qualified datatype layout"
    field, width, kind = layouts[attribute.data_type]
    values = attribute.data
    assert len(values) == count
    result = []
    for item in values:
        value = getattr(item, field)
        row = tuple(value) if width else (value,)
        assert len(row) == (width or 1)
        if kind == "FLOAT":
            assert all(type(part) is float and math.isfinite(part) for part in row)
            bits = [struct.pack("<f", part) for part in row]
            assert all(struct.unpack("<f", raw)[0] == part for raw, part in zip(bits, row, strict=True))
            plain = [raw.hex() for raw in bits]
        elif kind == "INT":
            assert all(type(part) is int and -(2**31) <= part < 2**31 for part in row)
            plain = list(row)
        else:
            assert kind == "BOOLEAN" and type(value) is bool
            plain = [value]
        result.append(plain if width else plain[0])
    assert len(result) == count
    return result


def unselected_attribute_headers(mesh):
    """Complete unselected headers; SINGLE headers never prove logical values."""
    counts = {"POINT": len(mesh.vertices), "EDGE": len(mesh.edges),
              "FACE": len(mesh.polygons), "CORNER": len(mesh.loops)}
    rows = []
    for attribute in mesh.attributes:
        if attribute.name in SELECTED:
            continue
        assert len(rows) < 32 and attribute.storage_type in {"ARRAY", "SINGLE"}
        assert attribute.domain in counts and attribute.data_type in {"BOOLEAN", "INT", "INT32_2D", "FLOAT2", "FLOAT_VECTOR"}
        rows.append([attribute.name, attribute.domain, attribute.data_type,
                     attribute.storage_type, counts[attribute.domain]])
    assert len({row[0] for row in rows}) == len(rows)
    return sorted(rows)


def original_array_values(mesh):
    """Read every original unselected ARRAY; never materialize an unselected SINGLE."""
    counts = {"POINT": len(mesh.vertices), "EDGE": len(mesh.edges),
              "FACE": len(mesh.polygons), "CORNER": len(mesh.loops)}
    rows = []
    for attribute in mesh.attributes:
        if attribute.name in SELECTED:
            continue
        assert attribute.storage_type in {"ARRAY", "SINGLE"}, "Unknown unselected attribute storage"
        if attribute.storage_type == "SINGLE":
            continue
        rows.append([attribute.name, attribute.domain, attribute.data_type,
                     attribute_values(attribute, counts[attribute.domain])])
    return sorted(rows)


def snapshot(bpy, target):
    """Separately authorized fixture inspection, never stopped-job cleanup."""
    obj, mesh = bpy.data.objects[target["object_name"]], bpy.data.meshes[target["mesh_name"]]
    image = bpy.data.images[target["image_name"]]
    pixels = array("f", [0.]) * 16
    assert tuple(image.size) == (2, 2) and image.has_data
    image.pixels.foreach_get(pixels)
    packed = bytes(image.packed_file.data)
    assert 0 < len(packed) <= 65536
    selected = selected_inventory(mesh)
    material = bpy.data.materials[target["material_name"]]
    node = material.node_tree.nodes[target["node_name"]]
    assert node.image is image
    protected = {"Main_ids": graph_main_id_inventory(bpy.data),
        "image": {"identity": identity(image), "pixels_float32_le": b"".join(struct.pack("<f", v) for v in pixels).hex(),
                  "packed_sha256": hashlib.sha256(packed).hexdigest(), "packed_bytes": len(packed),
                  "color_space": image.colorspace_settings.name, "alpha_mode": image.alpha_mode,
                  "is_dirty": image.is_dirty, "has_data": image.has_data},
        "material_bindings": [[identity(material), identity(material.node_tree), node.name, node.as_pointer(),
                               identity(node.image), [identity(slot.material) for slot in obj.material_slots]]],
        "unselected_attribute_headers": unselected_attribute_headers(mesh),
        "original_ARRAY_values": original_array_values(mesh)}
    return {"object_identity": identity(obj), "mesh_identity": identity(mesh),
            "uv_roles": [mesh.uv_layers.active_index, [[layer.name, layer.active_render, layer.active_clone]
                                                      for layer in mesh.uv_layers]],
            "selected_storage": selected,
            "selected_values": {name: attribute_values(mesh.attributes[name], count)
                                for name, _domain, _kind, storage, count in selected if storage == "ARRAY"},
            "protected": protected}


def constant_mesh(bpy, obj, label):
    """Owned setup: stock GN constants copied before the production baseline."""
    group = bpy.data.node_groups.new("B2 constants " + label, "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    previous, output = group.nodes.new("NodeGroupInput"), group.nodes.new("NodeGroupOutput")
    for name, domain, kind, value in (("PrepareFaceConstant", "FACE", "BOOLEAN", True),
                                      ("UVSingle", "CORNER", "FLOAT2", (.25, -.5, 0.))):
        node = group.nodes.new("GeometryNodeStoreNamedAttribute")
        node.domain, node.data_type = domain, kind
        node.inputs["Name"].default_value, node.inputs["Selection"].default_value = name, True
        node.inputs["Value"].default_value = value
        group.links.new(previous.outputs["Geometry"], node.inputs["Geometry"])
        previous = node
    group.links.new(previous.outputs["Geometry"], output.inputs["Geometry"])
    modifier = obj.modifiers.new("B2 owned constants", "NODES")
    modifier.node_group = group
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh, seed = evaluated.data.copy(), obj.data
    assert all(mesh.attributes[name].storage_type == "SINGLE" for name in ("PrepareFaceConstant", "UVSingle"))
    assert mesh.attributes.get(".uv_select_face") is None
    mesh.attributes["PrepareFaceConstant"].name = ".uv_select_face"
    obj.data = mesh
    obj.modifiers.remove(modifier)
    assert seed.users == group.users == 0
    bpy.data.meshes.remove(seed)
    bpy.data.node_groups.remove(group)
    assert all(row[3] == "SINGLE" for row in selected_inventory(mesh))
    return mesh


class Client:
    """Only protocol bytes and threading events run on the worker."""
    def __init__(self, port, transcript):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=60)
        self.stream, self.sequence, self.transcript = self.socket.makefile("rb"), 0, transcript

    def call(self, method, *, ok=True, **params):
        self.sequence += 1
        request = {"id": f"b2_{id(self)}_{self.sequence}", "method": method, "params": params,
                   "protocol_version": "1.0", "timeout_ms": 60000}
        row = {"request": request, "response": None}
        self.transcript.append(row)
        assert len(self.transcript) <= 2048
        self.socket.sendall(canonical(request) + b"\n")
        raw = self.stream.readline(MAX_REPORT + 1)
        assert 0 < len(raw) <= MAX_REPORT
        response = json.loads(raw)
        row["response"] = response
        assert type(response) is dict and response["id"] == request["id"], response
        if ok is None:
            return response
        assert response["ok"] is ok, response
        return response["result"] if ok else response["error"]

    def close(self):
        with contextlib.suppress(OSError):
            self.socket.shutdown(socket.SHUT_RDWR)
        self.stream.close()
        self.socket.close()


class Observer:
    """Constant-time code dispatch; native rows and stop prefixes stay bounded.

    Counts cover the named bridge boundaries, not hidden Blender activity.
    Status RPC authorization remains active and is excluded from stopped B2
    domain provider counts. Independent fixture inspection is a separate action.
    """
    def __init__(self, runtime, domain, primitive):
        from blender_codex_bridge import current_pixels_graph as graph
        from blender_codex_bridge.executor import MainThreadExecutor
        from blender_codex_bridge.job_controller import CooperativeJobController
        from blender_codex_bridge.scene_jobs import SceneJobs
        from blender_codex_bridge.tool_registry import ToolRegistry
        self.runtime, self.domain, self.primitive = runtime, domain, primitive
        self.codes = {"rpc": MainThreadExecutor._invoke_owned.__code__,
            "turn": ToolRegistry.invoke_scene_turn.__code__, "prepare": primitive.prepare.__code__,
            "field": primitive._Access.field.__code__, "catalog": graph._Reader.catalog.__code__,
            "provider": runtime.permissions._source.__code__, "cancel": CooperativeJobController.cancel.__code__,
            "finish": SceneJobs._finish.__code__}
        self.counts = dict.fromkeys(("native_entries", "native_returns", "provider_entries", "provider_returns",
            "prepare_entries", "prepare_returns", "materialize_entries", "materialize_returns",
            "after_accepted_stop_native_entries", "after_accepted_stop_provider_entries"), 0)
        self.events, self.stops, self.rpc_stack, self.provider_stack = [], [], [], []
        self.case, self.turn, self.turn_depth, self.prepare_depth = "setup", 0, 0, 0
        self.current_attribute, self.stopped, self.first_prepare = None, False, threading.Event()
        self.materialize_stack, self.native_started = [], []
        self.c_intervals = []
        self.seal_diagnostic = seal_diagnostic_config(domain.source)
        self.codes["source_seal"] = self.seal_diagnostic[0]
        self.seal_failure = None
        self.seal_diagnostic_error = {"schema": "STORAGE_SOURCE_SEAL_FAILURE_V1", "diagnostic_failed": True}

    def emit(self, kind, *, boundary, attribute=None):
        assert len(self.events) < 4096
        job = self.runtime.jobs.active
        row = {"sequence": len(self.events) + 1, "case": self.case, "kind": kind,
            "monotonic": time.monotonic(), "job_id": None if job is None else job.job_id,
            "native_count": self.counts["native_entries"], "provider_count": self.counts["provider_entries"],
            "turn": self.turn, "attribute": attribute, "boundary": boundary}
        self.events.append(row)
        return row

    def begin(self, case):
        assert self.runtime.jobs.active is None
        self.case, self.stopped = case, False
        self.first_prepare.clear()

    def domain_active(self):
        return self.turn_depth > 0 or self.prepare_depth > 0 or bool(
            self.rpc_stack and self.rpc_stack[-1].startswith("mesh.attribute_storage_prepare"))

    def accept_stop(self, kind, job):
        if self.stopped:
            return
        row = self.emit("stop_accepted", boundary="job_stop")
        self.stopped = True
        self.stops.append({"case": self.case, "job_id": job.job_id, "accepted_sequence": row["sequence"],
            "native_at_accept": self.counts["native_entries"], "provider_at_accept": self.counts["provider_entries"],
            "kind": kind})

    def profile(self, frame, event, argument):
        code = frame.f_code
        if code is self.codes.get("source_seal") and event == "return" and self.seal_failure is None:
            try:
                self.seal_failure = seal_failure_record(frame, self.seal_diagnostic)
            except Exception:
                self.seal_failure = self.seal_diagnostic_error
        if event in {"c_call", "c_return", "c_exception"}:
            if code is not self.codes["prepare"] or getattr(argument, "__name__", None) != "foreach_get":
                return
            cells, index = frame.f_locals.get("cells"), frame.f_locals.get("index")
            if cells is None or index is None:
                return
            cell = cells[index]
            if not cell["materialize_entered"] or cell["materialize_returned"]:
                return
            name = cell["name"]
            if event == "c_call":
                self.counts["native_entries"] += 1
                self.counts["materialize_entries"] += 1
                if self.stopped:
                    self.counts["after_accepted_stop_native_entries"] += 1
                self.native_started.append(time.monotonic())
                self.emit("materialize_enter", boundary="helper_prepare_C_foreach", attribute=name)
            else:
                self.counts["native_returns"] += 1
                self.counts["materialize_returns"] += event == "c_return"
                self.c_intervals.append({"case": self.case, "attribute": name,
                    "seconds": time.monotonic() - self.native_started.pop(), "returned": event == "c_return"})
                self.emit("materialize_return" if event == "c_return" else "materialize_exception",
                          boundary="helper_prepare_C_foreach", attribute=name)
            return
        if event not in {"call", "return"}:
            return
        if code is self.codes["rpc"]:
            if event == "call":
                self.rpc_stack.append(frame.f_locals["request"].method)
            else:
                self.rpc_stack.pop()
        elif code is self.codes["turn"]:
            if event == "call":
                self.turn_depth += 1
                self.turn += 1
                self.emit("turn_enter", boundary="scene_turn")
            else:
                self.emit("turn_return", boundary="scene_turn")
                self.turn_depth -= 1
        elif code is self.codes["prepare"]:
            if event == "call":
                self.prepare_depth += 1
                self.current_attribute = frame.f_locals["plan"].targets[0].name
                self.counts["prepare_entries"] += 1
                self.emit("prepare_enter", boundary="helper_prepare", attribute=self.current_attribute)
            else:
                self.counts["prepare_returns"] += 1
                self.emit("prepare_return", boundary="helper_prepare", attribute=self.current_attribute)
                self.prepare_depth -= 1
                if self.counts["prepare_returns"] == 1:
                    self.first_prepare.set()
        elif code is self.codes["field"] or code is self.codes["catalog"]:
            if self.domain_active():
                self.counts["native_entries" if event == "call" else "native_returns"] += 1
                if event == "call" and self.stopped:
                    self.counts["after_accepted_stop_native_entries"] += 1
        elif code is self.codes["provider"]:
            if event == "call":
                active = self.domain_active()
                self.provider_stack.append(active)
                if active:
                    self.counts["provider_entries"] += 1
                    if self.stopped:
                        self.counts["after_accepted_stop_provider_entries"] += 1
            elif self.provider_stack.pop():
                self.counts["provider_returns"] += 1
        elif code is self.codes["cancel"] and event == "return" and type(argument) is dict:
            job = self.runtime.jobs.active
            if argument.get("cancel_requested") and job is not None and job.cancel_reason:
                self.accept_stop("CANCEL_ACCEPTED_BY_MAIN_THREAD", job)
        elif code is self.codes["finish"] and event == "call" and frame.f_locals["state"] != "SUCCEEDED":
            self.accept_stop("TERMINAL_FAILURE_ACCEPTED_BY_MAIN_THREAD", frame.f_locals["job"])

    def summary(self):
        return {"scope": "BRIDGE_B2_ACTIVE_DOMAIN_ONLY",
            "covered_boundaries": ["helper_access_field", "graph_catalog", "helper_prepare_C_foreach"],
            "counts": dict(self.counts), "events": list(self.events), "stops": list(self.stops),
            "native_C_intervals": list(self.c_intervals), "status_RPC_authorization_excluded": True,
            "all_hidden_Blender_native_calls_claimed": False, "wrapper_exit_counts_include_exception": True,
            "prepare_exit_counts_include_exception": True}


class FaultInjector:
    """A separate trace hook preserves the observational profile after fault."""
    def __init__(self, code, return_line, observer, failure):
        self.code, self.return_line, self.observer, self.failure = code, return_line, observer, failure
        self.fired = False

    def trace(self, frame, event, _argument):
        if frame.f_code is not self.code:
            return None
        if (event == "line" and frame.f_lineno == self.return_line
                and self.observer.counts["materialize_returns"] == 2 and not self.fired):
            self.fired = True
            raise self.failure
        return self.trace


def materialize_trace_lines(primitive):
    """Bind the sole nonempty materializing call in the pinned helper."""
    path = Path(primitive.__file__)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == HELPER_SHA256
    tree = ast.parse(path.read_bytes())
    prepare = [node for node in tree.body if type(node) is ast.FunctionDef and node.name == "prepare"]
    assert len(prepare) == 1
    matches = [node for node in ast.walk(prepare[0]) if type(node) is ast.Expr
        and type(node.value) is ast.Call and type(node.value.func) is ast.Name
        and node.value.func.id == "foreach" and len(node.value.args) == 3
        and type(node.value.args[0]) is ast.Name and node.value.args[0].id == "data"
        and type(node.value.args[2]) is ast.Name and node.value.args[2].id == "output"]
    assert len(matches) == 1
    call = matches[0]
    lines = path.read_text().splitlines()
    returned = call.end_lineno + 1
    assert lines[returned - 1].strip() == 'cells[index]["materialize_returned"] = True'
    return call.lineno, returned


class OwnedMeshObserverHooks:
    """TRACE for Python boundaries; original C profiling only at materialization.

    An intentional trace fault clears tracing in CPython. Before that fault the
    original independent profile takes over, preserving all unwind/stop facts.
    This fixture adapter never changes the qualified helper or its guards.
    """
    def __init__(self, codes, observe, network, acknowledge_code, call_line, returned_line, fault=None):
        self.codes = {id(code): code for code in codes.values()}
        self.prepare = codes["prepare"]
        self.observe, self.network, self.acknowledge = observe, network, acknowledge_code
        self.call_line, self.returned_line, self.fault = call_line, returned_line, fault
        self.getters = (sys.getprofile, sys.gettrace, threading.getprofile, threading.gettrace)
        self.setters = (sys.setprofile, sys.settrace, threading.setprofile, threading.settrace)
        self.baseline = tuple(getter() for getter in self.getters)
        assert all(value is None for value in self.baseline), "Owned fixture requires unused observer hooks"
        self.active, self.failed, self.fallback, self.window = False, False, False, None
        # Retain bound-method identities for both CPython hooks and assertions.
        self.called, self.local = self._called, self._local
        self.c_profile, self.worker = self._c_profile, self._worker

    def install(self):
        assert all(getter() is value for getter, value in zip(self.getters, self.baseline, strict=True))
        self.active = True
        try:
            self.setters[3](self.worker)
            self.setters[1](self.called)
        except BaseException:
            self.failed = True
            self.restore()
            raise

    def _called(self, frame, event, value):
        if self.fallback or event != "call":
            return None
        code = frame.f_code
        if self.codes.get(id(code)) is not code:
            return None
        frame.f_trace_lines = code is self.prepare
        frame.f_trace_opcodes = False
        try:
            self.observe(frame, event, value)
        except BaseException:
            self.failed = True
            raise
        return self.local

    def _local(self, frame, event, value):
        if self.fallback:
            return None
        try:
            if frame.f_code is self.prepare:
                if event == "line":
                    if self.window is frame and frame.f_lineno != self.call_line:
                        # Also close a window whose arguments completed without
                        # a recognized C callback; never leak it into guards.
                        self.window = None
                        self.setters[0](self.baseline[0])
                    if frame.f_lineno == self.call_line:
                        assert self.window is None and self.getters[0]() is self.baseline[0]
                        self.window = frame
                        self.setters[0](self.c_profile)
                    fault = self.fault
                    if (fault is not None and frame.f_lineno == self.returned_line
                            and fault.observer.counts["materialize_returns"] == 2 and not fault.fired):
                        assert self.window is None
                        self.fallback = True
                        self.setters[0](self.observe)
                    if fault is not None:
                        fault.trace(frame, event, value)
                elif event in {"exception", "return"} and self.window is frame:
                    # Argument evaluation can fail before the actual C call.
                    self.window = None
                    self.setters[0](self.baseline[0])
            if not self.fallback and event == "return":
                self.observe(frame, event, value)
        except BaseException as error:
            if not (self.fallback and self.fault is not None and self.fault.fired
                    and error is self.fault.failure):
                self.failed = True
            raise
        return None if self.fallback else self.local

    def _c_profile(self, frame, event, value):
        if (self.window is not frame or frame.f_code is not self.prepare
                or event not in {"c_call", "c_return", "c_exception"}):
            return
        matching = False
        try:
            matching = getattr(value, "__name__", None) == "foreach_get"
            self.observe(frame, event, value)
        except BaseException:
            self.failed = True
            raise
        finally:
            if matching and event in {"c_return", "c_exception"}:
                self.window = None
                try:
                    self.setters[0](self.baseline[0])
                except BaseException:
                    self.failed = True
                    raise

    def _worker(self, frame, event, value):
        if event == "call" and frame.f_code is self.acknowledge:
            try:
                self.network(frame, event, value)
            except BaseException:
                self.failed = True
                raise
        return None

    def check(self):
        assert self.active and not self.failed and self.window is None
        expected = (self.observe, None, self.baseline[2], self.worker) if self.fallback else (
            self.baseline[0], self.called, self.baseline[2], self.worker)
        assert all(getter() is value for getter, value in zip(self.getters, expected, strict=True)), \
            "Owned observer hooks changed or the intentional trace fault was not observed"

    def restore(self):
        self.active, self.window = False, None
        failure = None
        for setter, value in zip(self.setters, self.baseline, strict=True):
            try:
                setter(value)
            except BaseException as error:
                if failure is None:
                    failure = error
        if failure is not None:
            self.failed = True
            raise failure


class Fixture:
    def __init__(self, bpy, options, token, sources, display, *, observe=True):
        self.bpy, self.options, self.token, self.sources, self.display = bpy, options, token, sources, display
        self.started, self.phase = time.monotonic(), options.bridge_phase
        self.controls, self.done = queue.Queue(), threading.Event()
        self.failure, self.cases, self.targets = None, {}, {}
        self.delivery_hold, self.delivery_entered, self.delivery_release = False, threading.Event(), threading.Event()
        self.delivery_expired, self.port, self.fault = False, None, None
        self.observer, self.runtime, self.prefs, self.hooks = None, None, None, None
        assert type(observe) is bool
        self.observe = observe

    def fail(self):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        if self.hooks is not None:
            try:
                self.hooks.restore()
            except BaseException:
                self.failure = (self.failure or "") + "\nOwned observer restoration failed."
        self.delivery_release.set()
        raw = {"schema": SCHEMA, "completed": False, "phase": self.phase,
            "process_instance": self.token, "process_id": os.getpid(), "failure": self.failure,
            "cases": self.cases, "targets": self.targets,
            "native_trace": None if self.observer is None else self.observer.summary(),
            "source_seal_failure": None if self.observer is None else self.observer.seal_failure,
            "source_fingerprints": self.sources, "source_unchanged": source_fingerprints() == self.sources}
        domain_new(self.options.bridge_report.with_suffix(".failure.json"), canonical(raw))
        print(self.failure, file=sys.stderr, flush=True)
        owned_process_exit(1)

    def seed(self, label, material, image):
        bpy = self.bpy
        seed = bpy.data.meshes.new("B2 seed " + label)
        seed.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)], shade_flat=False)
        obj = bpy.data.objects.new("B2 owner " + label, seed)
        bpy.context.scene.collection.objects.link(obj)
        mesh = constant_mesh(bpy, obj, label)
        mesh.name = "B2 mesh " + label
        mesh.materials.append(material)
        oracle = graph_owned_copy_oracle(bpy.data, mesh)
        assert all(row[3] == "SINGLE" for row in selected_inventory(mesh))
        assert oracle["setup_logical_values"][".uv_select_face"] == [True]
        assert oracle["setup_logical_values"]["UVSingle"] == [["0000803e", "000000bf"]] * 3
        self.targets[label] = {"object_name": obj.name, "mesh_name": mesh.name, "image_name": image.name,
            "material_name": material.name, "node_name": "B2 image consumer",
            "oracle_values": {name: oracle["setup_logical_values"][name] for name in SELECTED},
            "owned_setup_attribute_metadata": oracle["original_metadata"],
            "original_SINGLE_preserved_during_owned_setup_copy": True,
            "owned_copy_removed_before_baseline": True}
        if self.phase == "history_eviction":
            # This phase measures retained history using real no-op ARRAY jobs.
            # Its explicit owned setup is separate from SINGLE qualification.
            for name, _domain, _kind, _storage, count in selected_inventory(mesh):
                attribute = mesh.attributes[name]
                if attribute.data_type == "BOOLEAN":
                    buffer = memoryview(bytearray(count)).cast("?")
                    attribute.data.foreach_get("value", buffer)
                else:
                    buffer = array("f", [0.]) * (2 * count)
                    attribute.data.foreach_get("vector", buffer)
            assert all(row[3] == "ARRAY" for row in selected_inventory(mesh))
            self.targets[label]["history_setup_explicit_ARRAY"] = True

    def setup(self):
        try:
            from blender_codex_bridge import pixel_codecs
            from blender_codex_bridge import runtime as runtime_module
            from blender_codex_bridge.preferences import get_preferences
            from blender_codex_bridge.tools import mesh_storage as domain

            bpy = self.bpy
            bpy.context.preferences.use_preferences_save = False
            bpy.context.preferences.edit.use_global_undo = True
            bpy.context.preferences.edit.undo_steps = 256
            assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
            self.prefs = get_preferences()
            self.prefs.auto_start = False
            self.runtime, self.domain, self.primitive = runtime_module.get_runtime(), domain, domain.primitive
            assert type(self.runtime) is runtime_module.BridgeRuntime and self.runtime._registered
            assert runtime_module.native_save_permission_provider_intact()
            assert not self.runtime.server.running
            self.prefs.allow_inspect_scene = self.prefs.allow_edit_mesh = True
            self.prefs.allow_execute_python = self.prefs.allow_delete_objects = False
            self.prefs.allow_external_files = self.prefs.allow_save_project = self.prefs.allow_edit_scene = False
            self.prefs.paint_job_budget_ms = 1
            old, edited = array("f", [0., .25, .5, 1.]) * 4, array("f", [-0., .5, 2., 1.]) * 4
            encoded = b"".join(step.data for step in pixel_codecs.encode_steps(old, 2, 2, "EXR32_RAW", "DATA"))
            path = self.options.bridge_bundle / "fixture-image.exr"
            path.write_bytes(encoded)
            image = bpy.data.images.load(str(path), check_existing=False)
            image.name = "B2 protected dirty image"
            image.colorspace_settings.name, image.alpha_mode = "Non-Color", "CHANNEL_PACKED"
            image.pack(data=encoded, data_len=len(encoded))
            image.pixels.foreach_set(edited)
            image.update()
            material = bpy.data.materials.new("B2 protected image material")
            material.use_nodes = True
            texture = material.node_tree.nodes.new("ShaderNodeTexImage")
            texture.name, texture.image = "B2 image consumer", image
            labels = sorted(CASES[self.phase]) if self.phase == "adversarial" else ["main"]
            for label in labels:
                self.seed(label, material, image)
            self.select(labels[0])
            self.runtime_identity = {"process_instance": self.token, "runtime_id": id(self.runtime),
                "registry_id": id(self.runtime.registry), "queue_id": id(self.runtime.command_queue)}
            self.nonce = hashlib.sha256(canonical(self.runtime_identity)).hexdigest()[:32]
            assert self.primitive.BUILD == BUILD and tuple(bpy.app.version) == self.primitive.VERSION
            assert hashlib.sha256(Path(self.primitive.__file__).read_bytes()).hexdigest() == HELPER_SHA256
            self.provider = self.runtime.permissions._source
            self.provider_fact = (self.provider, self.provider.__code__, self.provider.__globals__,
                                  self.provider.__defaults__, self.provider.__kwdefaults__, self.provider.__closure__)
            domain.register_private(self.runtime.registry)
            self.runtime.registry.enable_toolset("geometry")
            self.observer = Observer(self.runtime, domain, self.primitive)
            self.binary_sha256 = domain_file(Path(bpy.app.binary_path))["sha256"]
            from blender_codex_bridge.request_lifecycle import RequestLifetime
            self.ack_code = RequestLifetime.acknowledge.__code__
            if self.phase == "native_failure":
                from blender_codex_bridge.errors import BridgeError
                lines = Path(self.primitive.__file__).read_text().splitlines()
                returns = [index + 1 for index, line in enumerate(lines)
                           if line.strip() == 'cells[index]["materialize_returned"] = True']
                assert len(returns) == 2 and "foreach(data," in lines[returns[1] - 2]
                self.fault = FaultInjector(self.primitive.prepare.__code__, returns[1], self.observer,
                    BridgeError("OPERATION_FAILED", "Owned fault after second real C return before journal marker.",
                                {"fixture_injected_after_native_return": True}))
            self.profile_callback = self.observer.profile
            call_line, returned_line = materialize_trace_lines(self.primitive)
            if self.observe:
                self.hooks = OwnedMeshObserverHooks(self.observer.codes, self.profile_callback,
                    self.network_profile, self.ack_code, call_line, returned_line, self.fault)
                self.hooks.install()
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
            probe.close()
            self.runtime.start_server("127.0.0.1", self.port, request_timeout=60)
            bpy.app.timers.register(self.supervise, first_interval=.005)
            threading.Thread(target=self.scenario, name="B2TypedSocketFixture", daemon=True).start()
        except Exception:
            self.failure = traceback.format_exc()
            self.fail()
        return None

    def network_profile(self, frame, event, _argument):
        if event != "call" or frame.f_code is not self.ack_code or not self.delivery_hold:
            return
        work = frame.f_back.f_locals.get("work")
        if work is not None and work.request.method == self.domain.contract.START:
            self.delivery_entered.set()
            if not self.delivery_release.wait(10):
                self.delivery_expired = True

    def select(self, label):
        bpy = self.bpy
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        obj = bpy.data.objects[self.targets[label]["object_name"]]
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.context.view_layer.update()
        assert obj.type == "MESH" and bpy.context.view_layer.objects.active is obj

    def control(self, action, **parameters):
        event, result = threading.Event(), []
        self.controls.put((action, parameters, event, result))
        assert event.wait(60), "Owned main-thread fixture control did not complete within its bound"
        assert result[0], result[1]
        return result[1]

    def apply(self, action, parameters):
        if action == "begin":
            self.select(parameters["target"])
            self.observer.begin(parameters["case"])
            return snapshot(self.bpy, self.targets[parameters["target"]])
        if action == "snapshot":
            return snapshot(self.bpy, self.targets[parameters["target"]])
        if action == "grants":
            self.prefs.allow_edit_mesh = parameters["edit"]
            return {"edit_mesh": self.prefs.allow_edit_mesh}
        if action == "mode":
            assert self.bpy.ops.object.mode_set(mode=parameters["mode"]) == {"FINISHED"}
            return {"mode": self.bpy.context.mode}
        if action == "manual_drift":
            obj = self.bpy.data.objects[self.targets[parameters["target"]]["object_name"]]
            before = list(obj.location)
            obj.location.x += .125
            return {"before_transform": before, "after_transform": list(obj.location), "owned_manual_action": True}
        if action == "pause":
            self.runtime.state.set_paused(parameters["paused"])
            return {"paused": self.runtime.state.snapshot()["paused"]}
        if action == "stop_intent":
            row = self.observer.emit("stop_intent", boundary="job_stop")
            return {"caller_intent_monotonic": parameters["caller_monotonic"], "main_thread_notice": row}
        if action == "fault_observer":
            assert self.fault.fired and sys.getprofile() is self.profile_callback
            return {"injected_after_native_return_before_journal_return_marker": True,
                    "observational_profile_remained_active": True}
        if action == "delivery_hold":
            self.delivery_hold, self.delivery_expired = True, False
            self.delivery_entered.clear()
            self.delivery_release.clear()
            return True
        if action == "undelivered_probe":
            job = self.runtime.jobs.active
            assert self.delivery_entered.is_set() and job is not None
            assert not job.lifetime.delivered.is_set() and not job.execution_started
            return {"actual_response_bytes_received_before_authoritative_ack": True,
                "delivery_ack_held": True, "delivered": job.lifetime.delivered.is_set(),
                "execution_started": job.execution_started, "job_id": job.job_id,
                "native_count": self.observer.counts["native_entries"],
                "preparation_count": self.observer.counts["prepare_entries"]}
        if action == "release_delivery":
            self.delivery_hold = False
            self.delivery_release.set()
            return {"gate_wait_expired": self.delivery_expired}
        if action == "records":
            job_id = parameters.get("job_id")
            stop = next((row for row in reversed(self.observer.stops) if row["case"] == self.observer.case), None)
            counts = self.observer.counts
            return {"stop_counts": {"provider_before": 0 if stop is None else stop["provider_at_accept"],
                "provider_after": 0 if stop is None else counts["provider_entries"],
                "native_before": 0 if stop is None else stop["native_at_accept"],
                "native_after": 0 if stop is None else counts["native_entries"]},
                "history": self.runtime.state.history(100),
                "recovery": [value for key, value in self.runtime.jobs.recovery_ledger.items()
                             if job_id is None or key == job_id],
                "terminal_ids": [job.job_id for job in self.runtime.jobs.history],
                "provider_intact": (self.provider, self.provider.__code__, self.provider.__globals__,
                    self.provider.__defaults__, self.provider.__kwdefaults__, self.provider.__closure__) == self.provider_fact}
        raise AssertionError("Unknown owned fixture action")

    def wait(self, client, identifier):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            summary = client.call("jobs.inspect", job_id=identifier)
            if summary["terminal"]:
                return summary
            time.sleep(.01)
        raise AssertionError("Real Scene job did not terminate within its original 60 second bound")

    def preview(self, client, label):
        target = self.targets[label]
        return client.call(self.domain.contract.PREVIEW, object_name=target["object_name"],
            mesh_name=target["mesh_name"], attribute_names=list(SELECTED))

    def start(self, client, label, preview, *, ok=True):
        target = self.targets[label]
        return client.call(self.domain.contract.START, ok=ok, object_name=target["object_name"],
            mesh_name=target["mesh_name"], attribute_names=list(SELECTED),
            expected_preparation_fingerprint=preview["expected_preparation_fingerprint"],
            confirm_materialize_storage=True, confirm_retained_partial_preparation=True)

    def case(self, name, target, requests):
        before = self.control("begin", case=name, target=target)
        row = {"requests": requests, "assertions": {}, "evidence": {"before": before,
            "oracle_values": self.targets[target]["oracle_values"], "terminal": None, "journal": None,
            "stop_counts": {"provider_before": 0, "provider_after": 0, "native_before": 0, "native_after": 0},
            "history": [], "recovery": []}}
        self.cases[name] = row
        return row

    def finish_case(self, name, label, terminal=None):
        row = self.cases[name]
        before, after = row["evidence"]["before"], self.control("snapshot", target=label)
        records = self.control("records", job_id=None if terminal is None else terminal["job_id"])
        assert records["provider_intact"]
        assert before["object_identity"] == after["object_identity"]
        assert before["mesh_identity"] == after["mesh_identity"] and before["uv_roles"] == after["uv_roles"]
        assert before["protected"] == after["protected"], {"before": before["protected"], "after": after["protected"]}
        assert records["stop_counts"]["native_before"] == records["stop_counts"]["native_after"]
        assert records["stop_counts"]["provider_before"] == records["stop_counts"]["provider_after"]
        row["evidence"].update(after=after, terminal=terminal,
            journal=None if terminal is None else terminal["storage_effects"],
            stop_counts=records["stop_counts"], history=records["history"], recovery=records["recovery"])
        row["assertions"] = dict.fromkeys(("complete", "protected_preserved", "original_ids_preserved",
            "uv_roles_preserved", "expected_outcome", "no_late_domain_reads_or_writes"), True)
        return row

    def cancelled(self, client, control_client, label, name, *, undelivered=False):
        preview = self.preview(client, label)
        if undelivered:
            self.control("delivery_hold")
        accepted = self.start(client, label, preview)
        assert accepted["accepted"] and not accepted["terminal"]
        if undelivered:
            assert self.delivery_entered.wait(10)
            probe = self.control("undelivered_probe")
            assert probe["preparation_count"] == 0
            self.cases[name]["evidence"]["delivery_probe"] = probe
        else:
            assert self.observer.first_prepare.wait(60), "First unchanged helper return was not observed"
        self.cases[name]["evidence"]["caller_intent"] = self.control("stop_intent", caller_monotonic=time.monotonic())
        receipt = control_client.call("jobs.cancel", job_id=accepted["job_id"])
        assert receipt["cancel_requested"]
        if undelivered:
            release = self.control("release_delivery")
            assert release["gate_wait_expired"] is False
        terminal = self.wait(control_client, accepted["job_id"])
        assert terminal["state"] == "CANCELLED", terminal
        return terminal

    def ordinary_phase(self):
        name = {"success": "two_rows", "cancel": "cancel_after_first",
                "native_failure": "failure_after_second_native", "history_eviction": "seed_cancel"}[self.phase]
        requests = []
        row = self.case(name, "main", requests)
        client, control_client = Client(self.port, requests), Client(self.port, requests)
        try:
            if self.phase in {"cancel", "history_eviction"}:
                terminal = self.cancelled(client, control_client, "main", name)
            else:
                preview = self.preview(client, "main")
                accepted = self.start(client, "main", preview)
                terminal = self.wait(client, accepted["job_id"])
                assert terminal["state"] == ("SUCCEEDED" if self.phase == "success" else "FAILED"), terminal
            self.finish_case(name, "main", terminal)
            if self.phase == "history_eviction":
                row["evidence"]["history_setup_explicit_ARRAY"] = True
            if self.phase == "success":
                assert row["evidence"]["after"]["selected_values"] == row["evidence"]["oracle_values"]
                events = [event for event in self.observer.events if event["kind"] == "materialize_enter"]
                assert len(events) == 2 and len({event["turn"] for event in events}) == 2
                recovery_requests = []
                recovery = self.case("recovery", "main", recovery_requests)
                recovery_client = Client(self.port, recovery_requests)
                try:
                    before = recovery["evidence"]["before"]
                    response = recovery_client.call("checkpoint.undo_last", confirm_global_undo=True, ok=None)
                    measured_after = self.control("snapshot", target="main")
                    # Retain a measurement even when the conservative recovery
                    # path refuses. No identity or safety guarantee is inferred.
                    measurement = {"kind": "authorized_native_undo_measurement",
                        "request_id": recovery_requests[-1]["request"]["id"], "response": response,
                        "before": before, "after": measured_after, "safety_qualified": False}
                    recovery["evidence"].update(after=measured_after, recovery=[measurement],
                        history=[], terminal=None, journal=None,
                        stop_counts={"provider_before": 0, "provider_after": 0, "native_before": 0, "native_after": 0})
                    recovery["assertions"] = {"complete": True, "actual_undo_response_retained": True,
                        "before_after_measured": True, "restore_safety_qualified": False}
                finally:
                    recovery_client.close()
            elif self.phase == "native_failure":
                observation = self.control("fault_observer")
                journal = terminal["storage_effects"]["rows"]
                assert journal[0]["verified"] and journal[1]["materialize_entered"]
                assert not journal[1]["materialize_returned"]
                row["evidence"].update(observation)
            elif self.phase == "history_eviction":
                self.history_phase(client, control_client, terminal)
        finally:
            client.close()
            control_client.close()

    def history_phase(self, client, control_client, seed):
        requests = []
        row = self.case("history_eviction", "main", requests)
        client.transcript, control_client.transcript = requests, requests
        actual = []
        for _ in range(33):
            preview = self.preview(client, "main")
            accepted = self.start(client, "main", preview)
            terminal = self.wait(client, accepted["job_id"])
            assert terminal["state"] == "SUCCEEDED", terminal
            assert all(item["action"] == "NOOP_ALREADY_ARRAY" and item["verified"]
                       for item in terminal["storage_effects"]["rows"])
            actual.append(terminal)
        retained = control_client.call("jobs.inspect", job_id=seed["job_id"])
        assert retained["terminal_history_evicted"] and retained["recovery_receipt_retained"]
        assert retained["storage_effects"] == seed["storage_effects"]
        self.finish_case("history_eviction", "main", retained)
        row["evidence"].update(completed_noop_jobs=actual, retained_seed=retained,
                               history_setup_explicit_ARRAY=True)

    def adversarial_phase(self):
        for name in ("permission_denial", "invalid_context", "stale_preview", "protected_scope_denial",
                     "undelivered", "pause_revoke", "disconnect"):
            requests = []
            row = self.case(name, name, requests)
            client, control_client = Client(self.port, requests), Client(self.port, requests)
            terminal, owner_closed = None, False
            try:
                if name == "permission_denial":
                    self.control("grants", edit=False)
                    error = self.preview_denied(client, name)
                    assert error["code"] == "PERMISSION_DENIED", error
                    row["evidence"]["denial"] = error
                    self.control("grants", edit=True)
                elif name == "invalid_context":
                    self.control("mode", mode="EDIT")
                    row["evidence"]["before"] = self.control("snapshot", target=name)
                    error = self.preview_denied(client, name)
                    assert error["code"] == "NOT_IMPLEMENTED", error
                    row["evidence"]["denial"] = error
                elif name == "stale_preview":
                    preview = self.preview(client, name)
                    row["evidence"]["manual_edit"] = self.control("manual_drift", target=name)
                    row["evidence"]["before"] = self.control("snapshot", target=name)
                    error = self.start(client, name, preview, ok=False)
                    assert error["context"]["reason"] == "STORAGE_PREVIEW_STALE", error
                    row["evidence"]["denial"] = error
                elif name == "protected_scope_denial":
                    plan = client.call("task.plan.set", goal="Retain the owned protected mesh",
                        steps=[{"id": "preserve", "description": "Do not modify the named mesh"}],
                        protected_objects=[self.targets[name]["object_name"]])
                    revision = plan["plan"]["revision"]
                    client.call("task.plan.enforce", enabled=True, expected_revision=revision)
                    preview = self.preview(client, name)
                    error = self.start(client, name, preview, ok=False)
                    assert error["context"].get("protected_scope_violation") is True, error
                    row["evidence"]["denial"] = error
                    client.call("task.plan.enforce", enabled=False, expected_revision=revision)
                    client.call("task.plan.clear")
                elif name == "undelivered":
                    terminal = self.cancelled(client, control_client, name, name, undelivered=True)
                elif name == "pause_revoke":
                    preview = self.preview(client, name)
                    self.control("delivery_hold")
                    accepted = self.start(client, name, preview)
                    assert self.delivery_entered.wait(10)
                    row["evidence"]["delivery_probe"] = self.control("undelivered_probe")
                    self.control("pause", paused=True)
                    assert not self.control("release_delivery")["gate_wait_expired"]
                    paused = control_client.call("jobs.inspect", job_id=accepted["job_id"])
                    assert not paused["terminal"]
                    self.control("grants", edit=False)
                    terminal = self.wait(control_client, accepted["job_id"])
                    assert terminal["state"] == "FAILED" and terminal["error"]["code"] == "PERMISSION_DENIED", terminal
                    row["evidence"]["paused_job"] = paused
                elif name == "disconnect":
                    preview = self.preview(client, name)
                    accepted = self.start(client, name, preview)
                    assert self.observer.first_prepare.wait(60)
                    row["evidence"]["caller_intent"] = self.control("stop_intent", caller_monotonic=time.monotonic())
                    client.close()
                    owner_closed = True
                    terminal = self.wait(control_client, accepted["job_id"])
                    assert terminal["state"] == "CANCELLED", terminal
                    row["evidence"]["actual_owner_socket_closed"] = True
                self.finish_case(name, name, terminal)
                if name == "invalid_context":
                    self.control("mode", mode="OBJECT")
                if name == "pause_revoke":
                    self.control("grants", edit=True)
                    self.control("pause", paused=False)
            finally:
                self.delivery_release.set()
                if not owner_closed:
                    client.close()
                control_client.close()

    def preview_denied(self, client, label):
        target = self.targets[label]
        return client.call(self.domain.contract.PREVIEW, ok=False, object_name=target["object_name"],
            mesh_name=target["mesh_name"], attribute_names=list(SELECTED))

    def scenario(self):
        try:
            if self.phase == "adversarial":
                self.adversarial_phase()
            else:
                self.ordinary_phase()
        except Exception:
            self.failure = traceback.format_exc()
        finally:
            self.done.set()

    def supervise(self):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        try:
            while not self.controls.empty():
                action, parameters, event, result = self.controls.get_nowait()
                try:
                    result.extend((True, self.apply(action, parameters)))
                except Exception:
                    result.extend((False, traceback.format_exc()))
                finally:
                    event.set()
            assert time.monotonic() - self.started <= 300, "Original bounded native phase expired"
            if not self.done.is_set():
                return .005
            assert self.failure is None, self.failure
            assert self.runtime.jobs.active is None
            assert source_fingerprints() == self.sources
            assert set(self.cases) == CASES[self.phase]
            counts = self.observer.counts
            assert counts["after_accepted_stop_native_entries"] == counts["after_accepted_stop_provider_entries"] == 0
            assert not self.delivery_expired
            assert self.bpy.context.view_layer.objects.active.type == "MESH"
            assert not self.prefs.allow_execute_python and not self.prefs.allow_external_files and not self.prefs.allow_save_project
            self.hooks.check()
            self.hooks.restore()
            from scripts.native_resources import linux_available_memory, linux_process_memory
            proof = {"schema": SCHEMA, "completed": True, "phase": self.phase,
                "process_instance": self.token, "process_id": os.getpid(), "runtime_nonce": self.nonce,
                "runtime_identity": self.runtime_identity, "source_build": self.bpy.app.build_hash.decode("ascii"),
                "blender_version": self.bpy.app.version_string, "source_fingerprints": self.sources,
                "source_snapshot_sha256": hashlib.sha256(canonical(self.sources)).hexdigest(),
                "binary_sha256": self.binary_sha256, "helper_sha256": HELPER_SHA256,
                "private_display": self.display, "cases": self.cases, "native_trace": self.observer.summary(),
                "assertions": dict.fromkeys(ASSERTIONS, True), "limitations": dict(LIMITATIONS),
                "transport": {"host": "127.0.0.1", "socket_json": True, "runtime_timer_queue": True,
                              "direct_dispatch": False, "manual_scheduler_drain": False},
                "resources": {"available_memory_bytes": linux_available_memory(),
                    "peak_rss_bytes": linux_process_memory()["peak_resident_bytes"],
                    "available_disk_bytes": shutil.disk_usage(self.options.bridge_bundle).free},
                "hardware": {"system": platform.system(), "machine": platform.machine(),
                    "processor": platform.processor(), "cpu_count": os.cpu_count()},
                "seconds": time.monotonic() - self.started}
            assert math.isfinite(proof["seconds"])
            raw = canonical(proof)
            assert len(raw) <= MAX_REPORT
            binding = domain_new(self.options.bridge_report, raw)
            compact = {name: proof[name] for name in ("schema", "completed", "phase", "process_instance", "process_id",
                "runtime_nonce", "source_build", "blender_version", "source_snapshot_sha256", "binary_sha256")}
            compact["full_receipt"] = binding
            print(MARKER + canonical(compact).decode(), flush=True)
            self.runtime.stop_server()
            owned_process_exit(0)
        except Exception:
            self.failure = traceback.format_exc()
            self.fail()
        return None


def control_hook_state():
    state = [getter() for getter in (sys.getprofile, sys.gettrace, threading.getprofile, threading.gettrace)]
    assert all(value is None for value in state), "Untraced control requires all four hooks absent"
    return state


def control_result_facts(before, after, oracle, terminal, outcome):
    selected = after["selected_values"] == oracle
    return {"selected_values_match": selected,
        "protected_sample_equal": before["protected"] == after["protected"] and before["uv_roles"] == after["uv_roles"],
        "identities_sample_equal": all(before[key] == after[key] for key in ("object_identity", "mesh_identity")),
        "product_success": (outcome == "JOB_TERMINAL" and terminal is not None
            and terminal["terminal"] is True and terminal["state"] == "SUCCEEDED" and selected
            and all(row[3] == "ARRAY" for row in after["selected_storage"]))}


class FirstJobControl(Fixture):
    """One unobserved real job sample; never five-phase acceptance evidence."""
    def __init__(self, bpy, options, token, sources, display):
        assert options.bridge_phase == "success" and tuple(bpy.app.version) == (5, 2, 2)
        assert bpy.app.build_hash == BUILD
        control_hook_state()
        super().__init__(bpy, options, token, sources, display, observe=False)
        self.control_build = bpy.app.build_hash.decode("ascii")
        self.control_version = bpy.app.version_string
        self.control_data = {"hooks": {}, "requests": [], "timings": [], "terminal": None}

    def settled(self):
        from blender_codex_bridge.executor import MainThreadExecutor
        codes = {id(fn.__code__): fn.__code__ for fn in (MainThreadExecutor.execute_request,
            MainThreadExecutor._invoke_owned, MainThreadExecutor._drain_timer)}
        frame, depth, present = sys._getframe(), 0, False
        try:
            while frame is not None:
                assert depth < 64, "Unsettled control stack depth"
                code = frame.f_code
                if codes.get(id(code)) is code:
                    present = True
                frame, depth = frame.f_back, depth + 1
        finally:
            frame = None
        main_thread_id = self.runtime.executor._main_thread_id
        assert type(main_thread_id) is int, "Control requires its actual main thread identity"
        result = {"job_active": self.runtime.jobs.active is not None,
            "is_executing": self.runtime.state.is_executing,
            "executing_mutators": self.runtime.registry.executing_mutators,
            "executor_frame_present": present,
            "main_thread": threading.get_ident() == main_thread_id}
        assert (result["job_active"] is False and result["is_executing"] is False
                and type(result["executing_mutators"]) is int and result["executing_mutators"] == 0
                and result["executor_frame_present"] is False and result["main_thread"] is True), \
            "Control snapshot requires a settled Runtime after its executor turn returned"
        return result

    def apply(self, action, parameters):
        assert action == "control_snapshot" and parameters["stage"] in {"before", "after"}
        # These checks are pure Python and must all precede any RNA access.
        settled, hooks = self.settled(), control_hook_state()
        return {"snapshot": snapshot(self.bpy, self.targets["main"]), "hooks": hooks, "settled": settled}

    def timed(self, client, stage, method, **parameters):
        started, cpu = time.monotonic(), time.process_time()
        response = client.call(method, ok=None, **parameters)
        self.control_data["timings"].append({"stage": stage,
            "request_id": self.control_data["requests"][-1]["request"]["id"],
            "sent_at": started, "received_at": time.monotonic(), "cpu_seconds": time.process_time() - cpu})
        assert type(response["ok"]) is bool
        if not response["ok"]:
            error = response["error"]
            assert type(error) is dict and type(error.get("code")) is str and error["code"]
            assert type(error.get("message")) is str and 0 < len(error["message"]) <= 4096
        return response

    def scenario(self):
        client = None
        try:
            data = self.control_data
            data["hooks"]["worker_before"] = control_hook_state()
            before = self.control("control_snapshot", stage="before")
            data["before"], data["hooks"]["main_before"] = before["snapshot"], before["hooks"]
            client = Client(self.port, data["requests"])
            target = self.targets["main"]
            parameters = {"object_name": target["object_name"], "mesh_name": target["mesh_name"],
                          "attribute_names": list(SELECTED)}
            preview = self.timed(client, "preview", self.domain.contract.PREVIEW, **parameters)
            data["outcome"] = "PREVIEW_REFUSED"
            if preview["ok"]:
                accepted = self.timed(client, "start", self.domain.contract.START, **parameters,
                    expected_preparation_fingerprint=preview["result"]["expected_preparation_fingerprint"],
                    confirm_materialize_storage=True, confirm_retained_partial_preparation=True,
                    time_limit_seconds=60)
                data["outcome"] = "START_REFUSED"
                if accepted["ok"]:
                    identifier = accepted["result"]["job_id"]
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        inspected = self.timed(client, "inspect", "jobs.inspect", job_id=identifier)
                        assert inspected["ok"], "Control lost its accepted job terminal response"
                        if inspected["result"]["terminal"]:
                            data["terminal"] = inspected["result"]
                            break
                        time.sleep(.01)
                    assert data["terminal"] is not None, "Accepted control job did not settle in its original 60s poll bound"
                    data["outcome"] = "JOB_TERMINAL"
            after = self.control("control_snapshot", stage="after")
            data["after"], data["settled"] = after["snapshot"], after["settled"]
            data["hooks"]["main_after"] = after["hooks"]
            data["hooks"]["worker_after"] = control_hook_state()
            data["setup_oracle_values"] = target["oracle_values"]
            data.update(control_result_facts(data["before"], data["after"],
                                            data["setup_oracle_values"], data["terminal"], data["outcome"]))
        except Exception:
            self.failure = traceback.format_exc()
        finally:
            if client is not None:
                client.close()
            self.done.set()

    def fail(self):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        # No observer, provider, Runtime or RNA inspection forms diagnostics.
        raw = {"schema": CONTROL_PROFILE, "completed": False, "diagnostic_only": True,
            "phase": self.phase, "process_id": os.getpid(), "process_instance": self.token,
            "failure": self.failure, "partial": self.control_data, "flags": dict(CONTROL_FLAGS)}
        domain_new(self.options.bridge_report.with_suffix(".failure.json"), canonical(raw))
        print(self.failure, file=sys.stderr, flush=True)
        owned_process_exit(1)

    def supervise(self):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        try:
            while not self.controls.empty():
                action, parameters, event, result = self.controls.get_nowait()
                try:
                    result.extend((True, self.apply(action, parameters)))
                except Exception:
                    result.extend((False, traceback.format_exc()))
                finally:
                    event.set()
            assert time.monotonic() - self.started <= 300, "Original bounded native phase expired"
            if not self.done.is_set():
                return .005
            assert self.failure is None, self.failure
            assert self.hooks is None and self.observe is False
            control_hook_state()
            self.settled()
            assert source_fingerprints() == self.sources
            encoded = canonical(self.sources)
            full = {"schema": CONTROL_PROFILE, "completed": True, "diagnostic_only": True, "phase": self.phase,
                "process_id": os.getpid(), "process_instance": self.token, "runtime_nonce": self.nonce,
                "runtime_identity": self.runtime_identity, "source_build": self.control_build,
                "blender_version": self.control_version, "binary_sha256": self.binary_sha256,
                "helper_sha256": HELPER_SHA256, "source_fingerprints": self.sources,
                "source_snapshot_sha256": hashlib.sha256(encoded).hexdigest(), "private_display": self.display,
                "transport": {"host": "127.0.0.1", "socket_json": True, "runtime_timer_queue": True,
                              "direct_dispatch": False, "manual_scheduler_drain": False},
                "flags": dict(CONTROL_FLAGS), **self.control_data, "seconds": time.monotonic() - self.started}
            binding = domain_new(self.options.bridge_report, canonical(full))
            compact = {key: full[key] for key in ("schema", "completed", "diagnostic_only", "process_id",
                "process_instance", "source_build", "blender_version", "binary_sha256",
                "source_snapshot_sha256", "product_success")}
            compact["full_receipt"] = binding
            print(CONTROL_MARKER + canonical(compact).decode("ascii"), flush=True)
            owned_process_exit(0)
        except Exception:
            self.failure = traceback.format_exc()
            self.fail()
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-phase", choices=PHASES, required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    parser.add_argument("--bridge-report", type=Path, required=True)
    parser.add_argument("--bridge-untraced-control", action="store_true")
    arguments = sys.argv[sys.argv.index("--") + 1:] if argv is None and "--" in sys.argv else argv
    options = parser.parse_args(arguments)
    assert sys.platform == "linux" and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    parent, report = options.bridge_report.parent, options.bridge_report
    expected_report = CONTROL_REPORT if options.bridge_untraced_control else REPORT
    assert report.is_absolute() and report.name == expected_report and not report.exists() and not report.is_symlink()
    assert parent.resolve(strict=True) == parent and stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert parent.stat().st_uid == os.getuid()
    assert all(os.environ.get(key) == str(parent) for key in ("TEMP", "TMP", "TMPDIR"))
    for key in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        directory = parent / ("worker-profile-" + key.lower())
        assert os.environ.get(key) == str(directory) and directory.is_dir() and not directory.is_symlink()
    assert Path.cwd() == parent / "working" and "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ
    assert options.bridge_bundle.is_absolute() and options.bridge_bundle.resolve(strict=True) == options.bridge_bundle
    assert stat.S_IMODE(options.bridge_bundle.stat().st_mode) == 0o700 and not options.bridge_bundle.is_symlink()
    token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(token) == 32 and all(char in "0123456789abcdef" for char in token)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "addon"))
    import bpy

    from scripts.blender_artist_sidebar_smoke import private_display_manifest
    assert not bpy.app.background and tuple(bpy.app.version) == (5, 2, 2) and bpy.app.build_hash == BUILD
    assert bpy.app.build_type == b"Release"
    private_display_manifest()
    display = domain_file(Path(os.environ["BRIDGE_TEST_PRIVATE_UI_MANIFEST"]), maximum=16384)
    assert bpy.ops.wm.read_factory_settings(use_empty=True) == {"FINISHED"}
    sources = source_fingerprints()
    assert sources["addon/blender_codex_bridge/mesh_storage_prepare.py"] == HELPER_SHA256
    fixture_type = FirstJobControl if options.bridge_untraced_control else Fixture
    fixture = fixture_type(bpy, options, token, sources, display)
    bpy.app.timers.register(fixture.setup, first_interval=.05)


if __name__ == "__main__":
    main()
