"""Actual private stored-settings gateway; isolated runner only.

This fixture does not register a public tool, replace a provider or native
method, or qualify Runtime job retention/cache pairing. Native calls block.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import stat
import struct
import sys
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path
from types import CodeType, FrameType, FunctionType, ModuleType, TracebackType

ROOT = Path(__file__).resolve().parents[1]
CASE = "storage_snapshot_adapter"
SCHEMA = "storage_snapshot_actual_adapter_v1"
PROFILE = "STOCK_VIEW_LAYER_STORAGE_ADAPTER_V1"
PHASES = ("absent", "valid", "malformed", "permission_controls", "stop_controls", "writer_failure", "turn_binding")
MARKERS = {phase: "BLENDER_STORAGE_ADAPTER_" + phase.upper() + "_OK " for phase in PHASES}
CASES = {"absent": ("absent",), "valid": ("valid",), "malformed": ("malformed",),
         "permission_controls": ("deny_inspect", "deny_save", "deny_external", "revoke_second"),
         "stop_controls": ("paused", "emergency", "stop_after"),
         "writer_failure": ("writer_failure",), "turn_binding": ("late_consume", "duplicate_consume")}
BUILDS = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}
MAX_REPORT = 8 * 1024**2
NAMES = ("pass_debug_sample_count", "use_pass_volume_direct", "use_pass_volume_indirect",
         "use_pass_shadow_catcher", "use_denoising", "denoising_store_passes")
EXTRA_NAMES = ("pass_render_time", "use_pass_volume_scatter", "use_pass_volume_transmit", "use_pass_volume_majorant",
               "denoising_pass_follow_reflections", "denoising_pass_use_albedo_roughness_weighting")
FAMILIES = ("scenes", "collections", "objects", "meshes", "materials", "worlds", "images", "cameras", "lights",
            "armatures", "actions", "node_groups", "texts", "screens", "workspaces", "window_managers")
FALSE_FLAGS = ("runtime_retention_qualified", "full_authored_preservation_qualified", "durable_backup_qualified",
               "cache_pairing_qualified", "native_calls_preemptible", "windows_qualified", "installed_package_qualified",
               "cleanup_qualified", "native_memory_cap_claimed", "hidden_Main_passivity_claimed")
COUNTERS = ("provider", "writer_entered", "writer_returned", "parser", "native_reads")
_EXCEPTION_ARGS = BaseException.__dict__["args"]
_EXCEPTION_DICT = BaseException.__dict__["__dict__"]
_EXCEPTION_TRACEBACK = BaseException.__dict__["__traceback__"]
_TYPE_NAME = type.__dict__["__name__"]
_TYPE_MODULE = type.__dict__["__module__"]
_TYPE_MRO = type.__dict__["__mro__"]
_TYPE_DICT = type.__dict__["__dict__"]
_PROPERTY_GETTER = property.__dict__["fget"]
_FRAME_LOCALS_GET = FrameType.__dict__["f_locals"]
_SOURCE_ACCESSOR_PATH = str(ROOT / "addon/blender_codex_bridge/tools/_cloth_cache_source.py")


def _diagnostic_locals_type():
    # Python3.13 optimized frames expose a builtin FrameLocalsProxy that its
    # types module does not export. Capture the exact native type before use.
    return type(_FRAME_LOCALS_GET.__get__(sys._getframe(), FrameType))


_FRAME_LOCALS_KIND = _diagnostic_locals_type()
_FRAME_LOCALS_ITEMS = _TYPE_DICT.__get__(_FRAME_LOCALS_KIND)["items"]


def _diagnostic_lookup(namespace, key):
    # Even an exact dict can contain a foreign key colliding with a literal
    # hash. Iterate held native items and compare only exact string keys.
    if type(namespace) is dict and len(namespace) <= 4096:
        for label, value in dict.items(namespace):
            if type(label) is str and label == key:
                return value
    elif type(namespace) is _FRAME_LOCALS_KIND and len(namespace) <= 4096:
        for label, value in _FRAME_LOCALS_ITEMS(namespace):
            if type(label) is str and label == key:
                return value
    return None


def exception_receipt(error, *, source_codes=()):
    """Bounded local fixture facts; never format an exception or live value."""
    kind = type(error)
    values = _EXCEPTION_DICT.__get__(error, BaseException)
    values = values if type(values) is dict else {}
    args = _EXCEPTION_ARGS.__get__(error, BaseException)
    message = args[0][:2048] if type(args) is tuple and args and type(args[0]) is str else None
    code = _diagnostic_lookup(values, "code")
    context = _diagnostic_lookup(values, "context")
    context_reason = _diagnostic_lookup(context, "reason")
    reason = context_reason if type(context_reason) is str else _diagnostic_lookup(values, "reason")
    error_name = _TYPE_NAME.__get__(kind)
    receipt = {"type": error_name[:128] if type(error_name) is str else None,
               "code": code[:128] if type(code) is str else None,
               "reason": reason[:256] if type(reason) is str else None,
               "message": message, "frames": [], "frames_truncated": False,
               "source_accessor": None}
    node = _EXCEPTION_TRACEBACK.__get__(error, BaseException)
    prior = None
    count = 0
    while type(node) is TracebackType:
        if count == 24:
            receipt["frames_truncated"] = True
            break
        frame, lineno = node.tb_frame, node.tb_lineno
        code_object = frame.f_code
        filename, function_name = code_object.co_filename, code_object.co_name
        receipt["frames"].append({"file": filename[:1024] if type(filename) is str else None,
                                  "function": function_name[:128] if type(function_name) is str else None, "line": lineno})
        if (type(source_codes) is tuple and len(source_codes) == 2
                and all(type(value) is CodeType for value in source_codes) and code_object is source_codes[0]
                and type(function_name) is str and function_name == "_function"
                and type(filename) is str and filename == _SOURCE_ACCESSOR_PATH):
            locals_now = _FRAME_LOCALS_GET.__get__(frame, FrameType)
            function = _diagnostic_lookup(locals_now, "function")
            function_kind = type(function)
            kind_module, kind_name = _TYPE_MODULE.__get__(function_kind), _TYPE_NAME.__get__(function_kind)
            candidate = {"callable_type": {"module": kind_module[:256] if type(kind_module) is str else None,
                                           "name": kind_name[:128] if type(kind_name) is str else None},
                         "function_module": None, "function_qualname": None,
                         "owner_module": None, "owner_name": None, "property_getters": []}
            if function_kind is FunctionType:
                module_name, function_name = function.__module__, function.__qualname__
                candidate["function_module"] = module_name[:256] if type(module_name) is str else None
                candidate["function_qualname"] = function_name[:256] if type(function_name) is str else None
            if (prior is not None and prior.f_code is source_codes[1] and type(prior.f_code.co_name) is str
                    and prior.f_code.co_name == "capture_cloth_sources"):
                parent_locals = _FRAME_LOCALS_GET.__get__(prior, FrameType)
                module, name, owner = (_diagnostic_lookup(parent_locals, key) for key in ("module", "name", "value"))
                if type(module) is ModuleType:
                    module_name = _diagnostic_lookup(ModuleType.__getattribute__(module, "__dict__"), "__name__")
                    candidate["owner_module"] = module_name[:256] if type(module_name) is str else None
                candidate["owner_name"] = name[:256] if type(name) is str else None
                # A MappingProxyType can wrap arbitrary Python mappings. Only
                # the native type dictionary descriptor supplies trusted items.
                if any(base is type for base in _TYPE_MRO.__get__(type(owner))):
                    fields = _TYPE_DICT.__get__(owner)
                    for index, (label, value) in enumerate(fields.items()):
                        if index == 4096:
                            break
                        if (type(label) is str and type(value) is property
                                and _PROPERTY_GETTER.__get__(value, property) is function):
                            candidate["property_getters"].append(label[:128])
                            if len(candidate["property_getters"]) == 8:
                                break
            receipt["source_accessor"] = candidate
        prior = frame
        count += 1
        node = node.tb_next
    return receipt


def source_names(root=ROOT):
    return ("scripts/blender_storage_snapshot_adapter_smoke.py", "scripts/run_blender_checks.py",
            "scripts/blender_artist_sidebar_smoke.py", *tuple(str(p.relative_to(root)) for p in
                                                            sorted((root / "addon").rglob("*.py"))))


def source_fingerprints():
    return {name: ordinary_file(ROOT / name, 1024**2)["sha256"] for name in source_names()}


def read_report(path):
    from scripts.run_blender_checks import _cloth_file, _cloth_nonfinite, _cloth_unique
    sha, raw = _cloth_file(path, MAX_REPORT, content=True)
    value = json.loads(raw, object_pairs_hook=_cloth_unique, parse_constant=_cloth_nonfinite)
    assert type(value) is dict
    return value, sha


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def ordinary_file(path, maximum):
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum
    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    digest, total = hashlib.sha256(), 0
    try:
        assert identity(os.fstat(descriptor)) == identity(before)
        while chunk := os.read(descriptor, 65536):
            total += len(chunk)
            assert total <= maximum
            digest.update(chunk)
        assert total == before.st_size and identity(os.fstat(descriptor)) == identity(before)
        assert identity(path.lstat()) == identity(before)
    finally:
        os.close(descriptor)
    return {"path": str(path), "bytes": total, "sha256": digest.hexdigest()}

def author_owned_settings(group, names, *, malformed=False):
    """Author known fixture cells before the protected operation baseline.

    RNA-created scalar properties have STATIC_TYPE. Delete each known raw cell
    before recreating it, including after the prior malformed-scalar case.
    This setup uses a held legitimate group and never reads typed RNA values.
    """
    for index, name in enumerate(names):
        with suppress(KeyError):
            del group[name]
        setattr(group, name, bool(index % 2))
    if malformed:
        del group["use_denoising"]
        group["use_denoising"] = "wrong scalar storage"

def valid_source_snapshot(value):
    """Require a populated measured fixture, not vacuous before==after values."""
    try:
        if type(value) is not dict or set(value) != {"ids", "filepath", "dirty", "context", "mesh", "materials", "image", "raw_settings"}:
            return False
        ids = value["ids"]
        if type(ids) is not dict or set(ids) != set(FAMILIES) or not 0 < sum(map(len, ids.values())) <= 128:
            return False
        for rows in ids.values():
            if type(rows) is not list:
                return False
            for row in rows:
                if (type(row) is not list or len(row) != 5 or type(row[0]) is not str or not row[0]
                        or any(type(item) is not int or item < 0 for item in row[1:4])
                        or row[1] == 0 or row[2] == 0 or type(row[4]) is not bool):
                    return False
        image = value["image"]
        settings = value["raw_settings"]
        if (type(settings) is not dict or set(settings) != {"present", "values"}
                or type(settings["present"]) is not bool or type(settings["values"]) is not list
                or len(settings["values"]) > 12):
            return False
        for row in settings["values"]:
            if (type(row) is not list or len(row) != 3 or type(row[0]) is not str
                    or row[1] not in ("bool", "int", "str") or type(row[2]).__name__ != row[1]):
                return False
        return (type(value["dirty"]) is bool and type(value["filepath"]) is str and len(value["context"]) == 8
                and type(value["context"][-1]) is bool
                and len(value["mesh"]["vertices"]) >= 3 and len(value["mesh"]["polygons"]) >= 1
                and len(value["materials"]) >= 1 and image["size"] == [2, 2] and image["channels"] == 4
                and image["has_data"] is True and image["dirty"] is True
                and all(type(image[key]) is str and len(image[key]) == 64
                        and all(char in "0123456789abcdef" for char in image[key])
                        for key in ("pixels_sha256_float32", "packed_sha256")))
    except (KeyError, TypeError, ValueError):
        return False


class SourceOracle:
    def setup(self):
            bpy = self.bpy
            assert sys.platform == "linux" and BUILDS.get(tuple(bpy.app.version)) == bpy.app.build_hash.decode()
            bpy.context.preferences.use_preferences_save = False
            self.scene, self.layer = bpy.context.scene, bpy.context.view_layer
            self.names = NAMES if bpy.app.version[0] == 4 else NAMES + EXTRA_NAMES
            self.data["declared_names"] = list(self.names)
            self.data["target"] = {"scene_name": self.scene.name, "view_layer_name": self.layer.name}
            # Factory-only authored PNG, current buffer and material before baseline.
            import zlib
            def chunk(kind, raw):
                return struct.pack(">I", len(raw)) + kind + raw + struct.pack(">I", zlib.crc32(kind + raw) & 0xffffffff)
            pixels = bytes((255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0, 255, 255, 255, 255))
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
            png += chunk(b"IDAT", zlib.compress(b"\0" + pixels[:8] + b"\0" + pixels[8:])) + chunk(b"IEND", b"")
            path = self.folder / "owned-source.png"
            path.write_bytes(png)
            self.image = bpy.data.images.load(str(path), check_existing=False)
            self.image.name = "Snapshot Protected Dirty Image"
            self.image.pack()
            current = list(self.image.pixels[:])
            current[0], current[3] = .25, .5
            self.image.pixels.foreach_set(current)
            assert self.image.is_dirty and self.image.has_data and len(current) == 16
            material = bpy.data.materials.new("Snapshot Protected Material")
            material.use_nodes = True
            node = material.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = self.image
            self.obj = next(value for value in self.scene.objects if value.type == "MESH")
            self.obj.data.materials.append(material)
            self.layer.update()
            self.retained = tuple(value for family in FAMILIES for value in getattr(bpy.data, family))
            assert len(self.retained) <= 128
            self.data["source_fixture_scope"] = {"factory_owned": True, "image_size": [2, 2], "dirty_current_buffer": True,
                                                "raw_setup_before_each_operation_baseline": True,
                                                "current_pixels_serialized_backup_claimed": False}

    def snapshot(self, group=None):
            bpy = self.bpy
            ids = {family: sorted([[value.name, value.as_pointer(), value.session_uid, value.users, value.use_fake_user]
                                   for value in getattr(bpy.data, family)]) for family in FAMILIES}
            image = self.image
            pixels = image.pixels[:]
            assert len(pixels) == 16 and image.has_data and image.packed_file is not None
            raw = struct.pack("<16f", *pixels)
            materials = []
            for material in bpy.data.materials:
                nodes, links = [], []
                if material.use_nodes:
                    for node in material.node_tree.nodes:
                        nodes.append([node.name, node.bl_idname, node.as_pointer(),
                                      node.image.as_pointer() if node.bl_idname == "ShaderNodeTexImage" and node.image else None])
                    links = sorted([[link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier]
                                    for link in material.node_tree.links])
                materials.append([material.name, material.as_pointer(), material.use_nodes,
                                  material.node_tree.as_pointer() if material.use_nodes else None,
                                  list(material.diffuse_color), sorted(nodes), links])
            settings = []
            if group is not None:
                for name in self.names:
                    value = group[name]  # Fixture-authored finite literal cells, not arbitrary storage.
                    assert type(value) in (bool, int, str)
                    settings.append([name, type(value).__name__, value])
            return {"ids": ids, "filepath": bpy.data.filepath, "dirty": bpy.data.is_dirty,
                    "context": [bpy.context.mode, bpy.context.scene.as_pointer(), bpy.context.view_layer.name,
                                self.layer.objects.active.as_pointer() if self.layer.objects.active else None,
                                sorted(value.as_pointer() for value in bpy.context.selected_objects),
                                self.scene.frame_current, self.scene.frame_subframe,
                                self.layer.is_property_set("cycles", ghost=False)],
                    "mesh": {"vertices": [list(value.co) for value in self.obj.data.vertices],
                             "edges": [list(value.vertices) for value in self.obj.data.edges],
                             "polygons": [list(value.vertices) for value in self.obj.data.polygons],
                             "materials": [value.as_pointer() for value in self.obj.data.materials]},
                    "materials": sorted(materials),
                    "raw_settings": {"present": group is not None, "values": settings},
                    "image": {"identity": image.as_pointer(), "has_data": image.has_data, "dirty": image.is_dirty,
                              "size": list(image.size), "channels": image.channels, "filepath": image.filepath,
                              "color": image.colorspace_settings.name, "alpha": image.alpha_mode,
                              "pixels_sha256_float32": hashlib.sha256(raw).hexdigest(),
                              "packed_sha256": hashlib.sha256(image.packed_file.data).hexdigest()}}


def projection_matches(projection, raw, target):
    """Compare every detached projection field against the independent parser."""
    storage = raw["storage"]
    fields = ("name", "type", "subtype", "flag", "len", "totallen")
    def header(value):
        return None if value is None else [value[key] for key in fields]
    expected = {"scene": target["scene_identity"], "layer": target["layer_identity"],
                "state": storage["state"], "storage": storage["storage"],
                "root_present": storage["root_present"], "root": header(storage["root_header"]),
                "group": header(storage["property"]),
                "children": [[*[child[key] for key in fields], child["value"], child["value2"]]
                             for child in storage["children"]],
                "storage_fingerprint": raw["storage_fingerprint"]}
    return projection == expected


def expected_prefix(name):
    """Finite per-case native and parser expectations; no missing cases pass."""
    if name in {"absent", "valid", "duplicate_consume", "late_consume"}:
        return 2, 1, 1, 2
    if name == "malformed":
        return 2, 1, 1, 2
    if name == "revoke_second":
        return 2, 0, 0, 0
    if name in {"deny_inspect", "deny_save", "deny_external"}:
        return 1, 0, 0, 0
    if name in {"paused", "emergency"}:
        return 0, 0, 0, 0
    if name == "stop_after":
        return 2, 1, 1, 0
    if name == "writer_failure":
        return 2, 1, 0, 0
    raise ValueError("UNKNOWN_ADAPTER_CASE")


def expected_outcome(name):
    if name in {"absent", "valid"}:
        return "SUCCESS"
    if name in {"late_consume", "duplicate_consume"}:
        return "CONSUME_REFUSED"
    return "REFUSED"


def validate_full(full, *, phase, process_instance, sources, binary, process_id):
    """Cold structural qualifier; runner independently reopens native files."""
    try:
        fixed = {"schema": SCHEMA, "profile": PROFILE, "phase": phase, "completed": True,
                 "process_instance": process_instance, "source_fingerprints": sources,
                 "binary": binary, "process_id": process_id, "native_adapter_qualified": True,
                 "source_unchanged": True, **dict.fromkeys(FALSE_FLAGS, False)}
        if (phase not in PHASES or type(full) is not dict or type(process_id) is not int or process_id <= 0
                or any(type(full.get(key)) is not type(value) or full.get(key) != value for key, value in fixed.items())):
            return False
        version = full["version"]
        if (type(version) is not list or len(version) != 3 or any(type(v) is not int for v in version)
                or tuple(version) not in BUILDS or full["build_hash"] != BUILDS[tuple(version)]):
            return False
        if (type(full["elapsed_seconds"]) is not float or not 0 <= full["elapsed_seconds"] <= 300
                or full["peak_memory"]["metric"] != "ru_maxrss" or full["peak_memory"]["units"] != "KiB"
                or type(full["peak_memory"]["value"]) is not int or full["peak_memory"]["value"] <= 0):
            return False
        rows = full["cases"]
        if type(rows) is not list or [row["name"] for row in rows] != list(CASES[phase]):
            return False
        for row in rows:
            name, counts = row["name"], row["counts"]
            if (row["outcome"] != expected_outcome(name) or type(row["source_preserved"]) is not bool
                    or not row["source_preserved"] or row["before"] != row["after"]
                    or not valid_source_snapshot(row["before"]["home"])
                    or len(row["before"]["targets"]) != 2 or row["before"]["targets"] != row["raw_targets"]
                    or type(row["before"]["raw_settings"]) is not list
                    or len(row["before"]["raw_settings"]) != 2):
                return False
            if (set(counts) != {*COUNTERS, "after_stop"}
                    or any(type(counts[key]) is not int or counts[key] < 0 for key in COUNTERS)
                    or tuple(counts[key] for key in COUNTERS[:4]) != expected_prefix(name)
                    or type(counts["after_stop"]) is not dict or set(counts["after_stop"]) != set(COUNTERS)
                    or any(type(value) is not int or value != 0 for value in counts["after_stop"].values())):
                return False
            names = NAMES if version[0] == 4 else NAMES + EXTRA_NAMES
            for index, raw in enumerate(row["before"]["raw_settings"]):
                if type(raw["present"]) is not bool or raw["present"] is not (name != "absent"):
                    return False
                expected_raw = [] if name == "absent" else [
                    [key, "str" if name == "malformed" and index == 1 and key == "use_denoising" else None,
                     "wrong scalar storage" if name == "malformed" and index == 1 and key == "use_denoising"
                     else (ordinal + index) % 2] for ordinal, key in enumerate(names)]
                if len(raw["values"]) != len(expected_raw):
                    return False
                for actual, expected in zip(raw["values"], expected_raw, strict=True):
                    if (len(actual) != 3 or actual[0] != expected[0] or actual[2] != expected[2]
                            or actual[1] not in ({"str"} if expected[1] == "str" else {"bool", "int"})):
                        return False
            if ((counts["writer_entered"] and counts["native_reads"] == 0)
                    or (not counts["provider"] and counts["native_reads"])):
                return False
            snapshots = row["journal"]["snapshots"]
            if (row["journal"]["runtime_retention_qualified"] is not False
                    or row["journal"]["durable_backup_qualified"] is not False
                    or row["journal"]["full_source_preservation_qualified"] is not False):
                return False
            allocated = name not in {"deny_inspect", "deny_save", "deny_external", "paused", "emergency"}
            if len(snapshots) != int(allocated):
                return False
            if allocated:
                cell = snapshots[0]
                if (cell["native_entered"] is not bool(counts["writer_entered"])
                        or cell["native_returned"] is not bool(counts["writer_returned"])
                        or cell["cleanup_entered"] is not False or cell["cleanup_returned"] is not False
                        or cell["directory_returned"] is not True or cell["reserved"] is not True):
                    return False
                if counts["writer_returned"] and (type(cell["native_seconds"]) is not float
                                                  or not 0 <= cell["native_seconds"] <= 300):
                    return False
                if cell["consumed"] is not (name in {"absent", "valid", "duplicate_consume"}):
                    return False
                if (cell["parser_entered"] is not bool(counts["parser"])
                        or cell["parser_returned"] is not (counts["parser"] == 2 and name != "malformed")
                        or cell["identity_verified"] is not (name in {"absent", "valid", "late_consume", "duplicate_consume"})
                        or cell["retained_directory_possible"] is not True
                        or cell["retained_file_possible"] is not bool(counts["writer_entered"])):
                    return False
            if counts["writer_returned"]:
                if row["native_file"] is None or len(row["retained_parser"]) != 2:
                    return False
                for index, proof in enumerate(row["retained_parser"]):
                    if proof["target"] != row["raw_targets"][index]:
                        return False
                    if name == "malformed" and index == 1:
                        if proof.get("error", {}).get("reason") != "RAW_PROPERTY_TYPE_UNQUALIFIED":
                            return False
                    else:
                        result = proof["result"]
                        storage = result["storage"]
                        if storage["state"] != ("ABSENT" if name == "absent" else "GROUP"):
                            return False
                        if name != "absent":
                            names = NAMES if version[0] == 4 else NAMES + EXTRA_NAMES
                            if {child["name"]: child["value"] for child in storage["children"]} != {
                                    key: (ordinal + index) % 2 for ordinal, key in enumerate(names)}:
                                return False
                if name in {"absent", "valid", "duplicate_consume"} and (len(row["projections"]) != 2 or any(not projection_matches(
                        projection, proof["result"], target) for projection, proof, target in
                        zip(row["projections"], row["retained_parser"], row["target_identities"], strict=True))):
                    return False
            elif row["native_file"] is not None or row["retained_parser"]:
                return False
            if (name.startswith("deny_") or name == "revoke_second") and row["error"]["code"] != "PERMISSION_DENIED":
                return False
            if name in {"late_consume", "duplicate_consume"} and row["error"]["reason"] != "SNAPSHOT_ONE_USE_OR_TURN_CHANGED":
                return False
            if name in {"paused", "emergency", "stop_after"} and row["error"]["code"] != (
                    "AGENT_PAUSED" if name == "paused" else "EMERGENCY_STOPPED"):
                return False
            if name == "malformed":
                error = row["error"]
                if (error.get("canonical_storage_error") is not True or error.get("type") != "StorageSnapshotError"
                        or error.get("code") is not None or error.get("message") != "RAW_PROPERTY_TYPE_UNQUALIFIED"
                        or error.get("reason") != "RAW_PROPERTY_TYPE_UNQUALIFIED"):
                    return False
            if name == "writer_failure" and row["error"]["type"] not in {"OSError", "RuntimeError", "PermissionError"}:
                return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


class Observer:
    """Original source observer and explicit fixture control actors only."""
    def __init__(self, fixture, name):
        from blender_codex_bridge import storage_snapshot as adapter
        from blender_codex_bridge.tool_registry import ToolContext
        self.fixture, self.name, self.adapter = fixture, name, adapter
        self.counts = dict.fromkeys(COUNTERS, 0)
        self.after_stop = dict.fromkeys(COUNTERS, 0)
        self.stopped, self.operation = False, None
        self.require_code = ToolContext.require.__code__
        self.parser_code = adapter.inspect_view_layer_storage.__code__
        self.read_codes = {adapter._field.__code__, adapter._pointer.__code__, adapter._id.__code__}
        self.original = None

    def increment(self, key):
        self.counts[key] += 1
        if self.stopped:
            self.after_stop[key] += 1

    def observe(self, frame, event, argument):
        if event == "call":
            code = frame.f_code
            if code is self.require_code:
                self.increment("provider")
                if self.counts["provider"] == 2:
                    if self.name == "revoke_second":
                        self.fixture.prefs.allow_save_project = False
                    elif self.name == "writer_failure":
                        os.chmod(self.operation.cell.directory, 0o500)
            elif code is self.parser_code:
                self.increment("parser")
            elif code in self.read_codes:
                self.increment("native_reads")
        elif event in {"c_call", "c_return", "c_exception"} and self.operation is not None:
            native = self.operation.native
            if native is not None and argument is native.writer:
                if event == "c_call":
                    self.increment("writer_entered")
                elif event == "c_return":
                    self.increment("writer_returned")
                    if self.name == "stop_after":
                        self.fixture.runtime.state.emergency_stopped = True
                        self.stopped = True

    def __enter__(self):
        assert all(value is None for value in (sys.getprofile(), sys.gettrace(),
                                               threading.getprofile(), threading.gettrace()))
        self.original = (sys.getprofile(), threading.getprofile(), sys.gettrace(), threading.gettrace())
        try:
            sys.setprofile(self.observe)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_):
        old = self.original
        # All four cleanup calls are attempted even if an earlier one fails.
        failures = []
        for setter, value in zip((sys.setprofile, threading.setprofile, sys.settrace, threading.settrace), old, strict=True):
            try:
                setter(value)
            except BaseException as error:
                failures.append(error)
        if failures:
            raise failures[0]


class Fixture(SourceOracle):
    def __init__(self, bpy, options, attestation):
        self.bpy, self.options = bpy, options
        self.folder = options.bridge_bundle.resolve(strict=True)
        self.started = time.monotonic()
        self.path = self.folder / (options.bridge_phase + ".json")
        assert not self.path.exists() and not options.bridge_bundle.is_symlink()
        binary = ordinary_file(Path(bpy.app.binary_path).resolve(strict=True), 1024**3)
        self.binary = {key: binary[key] for key in ("path", "sha256")}
        self.sources = source_fingerprints()
        self.data = {"schema": SCHEMA, "profile": PROFILE, "phase": options.bridge_phase,
                     "completed": False, "version": list(bpy.app.version), "build_hash": bpy.app.build_hash.decode(),
                     "blender_version": bpy.app.version_string, "process_id": os.getpid(),
                     "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "binary": self.binary,
                     "source_fingerprints": self.sources, "private_display": attestation,
                     "cases": [], "native_adapter_qualified": False, **dict.fromkeys(FALSE_FLAGS, False)}
        self.runtime = self.prefs = None
        self.source_codes = ()

    def setup(self):
        super().setup()
        bpy = self.bpy
        self.second = bpy.data.scenes.new("Adapter Second Scene")
        self.scenes = (self.scene, self.second)
        self.layers = tuple(scene.view_layers[0] for scene in self.scenes)
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        from blender_codex_bridge.tools import _cloth_cache_source
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        self.runtime, self.prefs = get_runtime(), get_preferences()
        assert self.runtime._registered and self.prefs is not None
        self.runtime.registry.enable_toolset("simulation")
        self.prefs.allow_save_project = self.prefs.allow_external_files = self.prefs.allow_inspect_scene = True
        assert self.prefs.allow_execute_python is False
        self.context = self.runtime.executor.context
        self.context.checkpoint_method = "simulation.cache_preview"
        self.source_codes = (_cloth_cache_source._function.__code__, _cloth_cache_source.capture_cloth_sources.__code__)
        self.groups = []
        for index, layer in enumerate(self.layers):
            if self.options.bridge_phase == "absent":
                layer.property_unset("cycles")
                assert layer.is_property_set("cycles", ghost=False) is False
                self.groups.append(None)
            else:
                group = layer.cycles
                author_owned_settings(group, self.names)
                for ordinal, name in enumerate(self.names):
                    setattr(group, name, bool((ordinal + index) % 2))
                if self.options.bridge_phase == "malformed" and index == 1:
                    del group["use_denoising"]
                    group["use_denoising"] = "wrong scalar storage"
                self.groups.append(group)

    def complete_snapshot(self):
        home = super().snapshot(self.groups[0])
        mesh = self.obj.data
        home["mesh"]["loops"] = [[loop.vertex_index, loop.edge_index] for loop in mesh.loops]
        home["mesh"]["uv"] = [[layer.name, layer.active_render, layer.active_clone,
                                  [list(item.uv) for item in layer.data]] for layer in mesh.uv_layers]
        nodes = []
        for material in self.bpy.data.materials:
            if not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                defaults = []
                for socket in node.inputs:
                    if socket.type == "SHADER":
                        value = None
                    else:
                        raw = socket.default_value
                        value = raw if type(raw) in {str, bool, int, float} else list(raw)
                    defaults.append([socket.identifier, socket.type, value])
                nodes.append([material.name, node.name, list(node.location), node.width, node.mute, defaults])
        targets, settings, clocks = [], [], []
        for scene, layer, group in zip(self.scenes, self.layers, self.groups, strict=True):
            targets.append({"scene_name": scene.name, "view_layer_name": layer.name})
            values = [] if group is None else [[name, type(group[name]).__name__, group[name]] for name in self.names]
            settings.append({"present": layer.is_property_set("cycles", ghost=False), "values": values})
            clocks.append([scene.as_pointer(), layer.as_pointer(), scene.frame_current, scene.frame_subframe])
        objects = [[obj.as_pointer(), obj.data.as_pointer() if obj.data else None, obj.parent.as_pointer() if obj.parent else None,
                    list(obj.location), list(obj.rotation_euler), list(obj.scale), obj.hide_render]
                   for obj in self.bpy.data.objects]
        return {"home": home, "targets": targets, "raw_settings": settings, "clocks": clocks,
                "node_defaults": nodes, "objects": objects}

    def target_identities(self):
        return [{"scene_identity": [scene.as_pointer(), scene.session_uid, scene.name],
                 "layer_identity": [layer.as_pointer(), layer.name]}
                for scene, layer in zip(self.scenes, self.layers, strict=True)]

    def run_operation(self, operation, observer, *, late=False):
        observer.operation = operation
        witness = operation.run()
        if late:
            return witness
        projections = witness.consume(self.context, self.bpy, self.scenes)
        if observer.name == "duplicate_consume":
            self.current_projections = json.loads(canonical([dataclasses.asdict(value) for value in projections]))
            witness.consume(self.context, self.bpy, self.scenes)
        return projections

    def run_case(self, name):
        from blender_codex_bridge import storage_snapshot as adapter
        from blender_codex_bridge.blend_storage_sdna import StorageSnapshotError
        from blender_codex_bridge.storage_snapshot_effects import SnapshotJournal
        storage_error_kind = StorageSnapshotError  # Hold exact parser class before operation/provider entry.
        self.runtime.state.paused = self.runtime.state.emergency_stopped = False
        self.prefs.allow_save_project = self.prefs.allow_external_files = self.prefs.allow_inspect_scene = True
        denial = {"deny_inspect": "allow_inspect_scene", "deny_save": "allow_save_project", "deny_external": "allow_external_files"}
        if name in denial:
            setattr(self.prefs, denial[name], False)
        if name in {"paused", "emergency"}:
            setattr(self.runtime.state, "paused" if name == "paused" else "emergency_stopped", True)
        root = self.folder / (self.options.bridge_phase + "-" + name + "-owned")
        root.mkdir(mode=0o700)
        journal = SnapshotJournal(1)
        operation = adapter.SnapshotOperation(self.context, self.bpy, self.scenes, str(root), journal)
        before = self.complete_snapshot()
        self.current_projections = []
        observer = Observer(self, name)
        error = None
        outcome = "SUCCESS"
        try:
            with observer:
                result = self.run_operation(operation, observer, late=name == "late_consume")
                if name == "late_consume":
                    result.consume(self.context, self.bpy, self.scenes)
                self.current_projections = json.loads(canonical([dataclasses.asdict(value) for value in result]))
        except BaseException as caught:
            error = exception_receipt(caught, source_codes=self.source_codes)
            error["canonical_storage_error"] = type(caught) is storage_error_kind
            outcome = "CONSUME_REFUSED" if name in {"late_consume", "duplicate_consume"} else "REFUSED"
        # Controller observations are outside bridge execution and hooks. Retain
        # every artifact; do not call cleanup, recovery, undo or a stopped API.
        after = self.complete_snapshot()
        row = {"name": name, "outcome": outcome, "error": error, "before": before, "after": after,
               "source_preserved": before == after, "owned_root": str(root),
               "counts": {**observer.counts, "after_stop": observer.after_stop},
               "journal": journal.snapshot(), "raw_targets": before["targets"],
               "target_identities": self.target_identities(), "projections": self.current_projections,
               "native_file": None, "retained_parser": []}
        cells = row["journal"]["snapshots"]
        if cells and cells[0]["native_returned"]:
            path = Path(cells[0]["filepath"])
            row["native_file"] = ordinary_file(path, 1024**3)
            for target in row["raw_targets"]:
                proof = {"target": target}
                try:
                    proof["result"] = adapter.inspect_view_layer_storage(str(path), **target, allowed_names=self.names)
                except ValueError as caught:
                    proof["error"] = {"type": type(caught).__name__, "reason": getattr(caught, "reason", None)}
                row["retained_parser"].append(proof)
        return row

    def flush(self):
        raw = canonical(self.data) + b"\n"
        assert len(raw) <= MAX_REPORT
        temporary = self.path.with_suffix(".next")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def run(self):
        status = 1
        try:
            self.setup()
            self.flush()
            for name in CASES[self.options.bridge_phase]:
                assert time.monotonic() - self.started < 270
                self.data["cases"].append(self.run_case(name))
                self.flush()
            import resource
            self.data.update(source_unchanged=source_fingerprints() == self.sources,
                             elapsed_seconds=float(time.monotonic() - self.started),
                             peak_memory={"metric": "ru_maxrss", "units": "KiB", "value": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
                             completed=True, native_adapter_qualified=True)
            assert validate_full(self.data, phase=self.options.bridge_phase, process_instance=self.data["process_instance"],
                                 sources=self.sources, binary=self.binary, process_id=os.getpid())
            self.flush()
            payload = {key: self.data[key] for key in ("schema", "profile", "phase", "completed", "blender_version", "version",
                       "build_hash", "process_instance", "process_id", "source_fingerprints", "binary")}
            payload["full_receipt"] = ordinary_file(self.path, MAX_REPORT)
            print(MARKERS[self.options.bridge_phase] + canonical(payload).decode(), flush=True)
            status = 0
        except BaseException as caught:
            self.data.update(completed=False, native_adapter_qualified=False,
                             failure=exception_receipt(caught, source_codes=self.source_codes))
            self.flush()
            print(canonical(self.data["failure"]).decode(), file=sys.stderr, flush=True)
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        owned_process_exit(status)



def main(argv=None):
    assert threading.current_thread() is threading.main_thread()
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv and sys.dont_write_bytecode
    token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(token) == 32 and all(value in "0123456789abcdef" for value in token)
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        assert Path(os.environ[key]).resolve(strict=True) == folder
    for key in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        assert Path(os.environ[key]).resolve(strict=True).parent == folder
    assert Path.cwd().resolve() == folder / "working"
    sys.path[:0] = [str(ROOT), str(ROOT / "addon")]
    from scripts.blender_artist_sidebar_smoke import private_display_manifest
    attestation = private_display_manifest()  # Before bpy context or exit authority.
    import bpy
    assert sys.platform == "linux" and not bpy.app.background and bpy.data.filepath == ""
    assert BUILDS.get(tuple(bpy.app.version)) == bpy.app.build_hash.decode()
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=PHASES, required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    values = sys.argv[sys.argv.index("--")+1:] if argv is None else argv
    options = parser.parse_args(values)
    fixture = Fixture(bpy, options, attestation)
    bpy.app.timers.register(fixture.run, first_interval=.01)



# Separate opt-in diagnostic. The original seven-phase adapter remains unchanged.
RUNTIME_CASE = "storage_snapshot_runtime_context"
RUNTIME_PROFILE = "STOCK_RUNTIME_JOBS_CONTEXT_QUEUED_REQUEST_DIAGNOSTIC_V1"
RUNTIME_SCHEMA = "storage_snapshot_runtime_jobs_context_v1"
RUNTIME_MARKER = "BLENDER_STORAGE_RUNTIME_JOBS_CONTEXT_OK "
RUNTIME_METHOD = "simulation.cache_context_prepare"
RUNTIME_SCENARIOS = ("success", "permission_denial", "factory_crossbinding")
RUNTIME_FALSE = ("shipping_caller_qualified", "canonical_job_resumption_qualified", "durable_backup_qualified",
    "current_pixels_backup_qualified", "large_image_qualified", "full_authored_preservation_qualified",
    "full_executor_after_stop_qualified", "history_retention_qualified", "restart_recovery_qualified",
    "runtime_retention_qualified", "installed_package_qualified", "windows_qualified", "full_artist_workflow_qualified",
    "native_calls_preemptible", "native_memory_cap_claimed", "hidden_Main_passivity_claimed")
RUNTIME_COMPONENTS = ("jobs_non_null", "runtime_singleton", "registry", "state", "permissions", "checkpoints",
    "evidence", "glb_stage", "service_executor", "factory_origin", "queued_owner", "original_closure", "main_thread")
RUNTIME_CELL_TRUE = ("reserved", "directory_entered", "directory_returned", "native_entered", "native_returned",
    "parser_entered", "parser_returned", "identity_verified", "consumed", "cleanup_entered", "cleanup_returned")


def runtime_plain_json(value, depth=0):
    if depth > 64:
        return False
    kind = type(value)
    if kind in (str, bool, int) or value is None:
        return True
    if kind is float:
        return -float("inf") < value < float("inf")
    if kind is list:
        return len(value) <= 65536 and all(runtime_plain_json(item, depth+1) for item in value)
    if kind is dict:
        return len(value) <= 65536 and all(type(key) is str and runtime_plain_json(item, depth+1) for key, item in value.items())
    return False


def runtime_target_identity(value, target):
    return (type(value) is dict and set(value) == {"scene_identity", "layer_identity"}
        and type(value["scene_identity"]) is list and len(value["scene_identity"]) == 3
        and all(type(item) is int and item > 0 for item in value["scene_identity"][:2])
        and type(value["scene_identity"][2]) is str and value["scene_identity"][2] == target["scene_name"]
        and type(value["layer_identity"]) is list and len(value["layer_identity"]) == 2
        and type(value["layer_identity"][0]) is int and value["layer_identity"][0] > 0
        and type(value["layer_identity"][1]) is str and value["layer_identity"][1] == target["view_layer_name"])


def runtime_projection_matches(projection, raw, target):
    storage = raw["storage"]
    fields = ("name", "type", "subtype", "flag", "len", "totallen")
    def header(value):
        return None if value is None else [value[key] for key in fields]
    expected = {"scene": target["scene_identity"], "layer": target["layer_identity"],
        "state": storage["state"], "storage": storage["storage"], "root_present": storage["root_present"],
        "root": header(storage["root_header"]), "group": header(storage["property"]),
        "children": [[*[child[key] for key in fields], child["value"], child["value2"]] for child in storage["children"]],
        "storage_fingerprint": raw["storage_fingerprint"]}
    return canonical(projection) == canonical(expected)


def runtime_success_result(value, outcome):
    if (type(value) is not dict or set(value) != {outcome, "operation"} or value[outcome] is not True
            or type(value["operation"]) is not dict
            or set(value["operation"]) != {"operation_id", "undo_boundary_created", "undo_boundary_finalized"}):
        return False
    operation = value["operation"]
    identifier = operation["operation_id"]
    return (type(identifier) is str and len(identifier) == 13 and identifier.startswith("op_")
        and all(char in "0123456789abcdef" for char in identifier[3:])
        and operation["undo_boundary_created"] is False and operation["undo_boundary_finalized"] is False)


def runtime_journal(value):
    if (type(value) is not dict or set(value) != {"schema", "capacity", "snapshots", "runtime_retention_qualified",
            "durable_backup_qualified", "full_source_preservation_qualified", "native_calls_preemptible"}
            or value["schema"] != "owned_storage_inspection_effects_v1" or type(value["capacity"]) is not int
            or value["capacity"] != 1 or type(value["snapshots"]) is not list or len(value["snapshots"]) != 1
            or any(value[key] is not False for key in ("runtime_retention_qualified", "durable_backup_qualified",
                "full_source_preservation_qualified", "native_calls_preemptible"))):
        return False
    cell = value["snapshots"][0]
    return (type(cell) is dict and set(cell) == {*RUNTIME_CELL_TRUE, "stopped", "failed", "root", "directory", "filepath",
            "root_identity", "directory_identity", "file_identity", "file_sha256", "file_bytes", "available_memory_bytes",
            "available_disk_bytes", "native_seconds", "retained_directory_possible", "retained_file_possible",
            "native_completion_means_source_preserved"}
        and all(cell[key] is True for key in RUNTIME_CELL_TRUE)
        and all(cell[key] is False for key in ("stopped", "failed", "retained_directory_possible", "retained_file_possible",
            "native_completion_means_source_preserved")))


def runtime_source_names(root=ROOT):
    return (*source_names(root), "scripts/blender_storage_snapshot_cleanup_smoke.py")


def runtime_source_fingerprints():
    return {name: ordinary_file(ROOT / name, 1024**2)["sha256"] for name in runtime_source_names()}


def validate_runtime_context(full, *, process_instance, process_id, sources, binary):
    """Strict separate diagnostic schema; synthetic validation is not native proof."""
    try:
        fields = {"schema", "profile", "phase", "completed", "process_instance", "process_id", "version", "build_hash",
            "blender_version", "binary", "source_fingerprints", "source_unchanged", "private_display", "source_fixture_scope",
            "declared_names", "target_pair", "cases", "sent", "wire", "terminal", "dispatch", "fixture_only_registration",
            "original_preferences_provider", "python_disabled", "jobs_non_null", "hooks_restored", "services_stopped",
            "native_undo_pushes", "case_deadline_seconds", "limitations", "private_display_binding"}
        if (type(full) is not dict or not runtime_plain_json(full) or set(full) != fields or full["schema"] != RUNTIME_SCHEMA
                or full["profile"] != RUNTIME_PROFILE or full["phase"] != "runtime_context" or full["completed"] is not True
                or full["process_instance"] != process_instance or type(process_id) is not int or process_id <= 0
                or type(full["process_id"]) is not int or full["process_id"] != process_id
                or full["source_fingerprints"] != sources or full["binary"] != binary
                or any(full[name] is not True for name in ("source_unchanged", "fixture_only_registration", "original_preferences_provider",
                    "python_disabled", "jobs_non_null", "hooks_restored", "services_stopped"))
                or type(full["native_undo_pushes"]) is not int or full["native_undo_pushes"] != 0
                or type(full["case_deadline_seconds"]) is not int or full["case_deadline_seconds"] != 300
                or type(full["limitations"]) is not dict or set(full["limitations"]) != set(RUNTIME_FALSE)
                or any(value is not False for value in full["limitations"].values())):
            return False
        if (type(process_instance) is not str or len(process_instance) != 32
                or any(ch not in "0123456789abcdef" for ch in process_instance)
                or canonical(full["source_fixture_scope"]) != canonical({"factory_owned": True, "image_size": [2, 2],
                    "dirty_current_buffer": True, "raw_setup_before_each_operation_baseline": True,
                    "current_pixels_serialized_backup_claimed": False})):
            return False
        display, binding = full["private_display"], full["private_display_binding"]
        if (type(display) is not dict or type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"}
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= 16384
                or display.get("manifest_path") != binding["path"] or display.get("manifest_sha256") != binding["sha256"]
                or type(display.get("manifest")) is not dict
                or any(display["manifest"].get(key) is not True for key in ("input_disabled", "owned_process", "tcp_disabled"))):
            return False
        version = full["version"]
        if (type(version) is not list or len(version) != 3 or any(type(x) is not int for x in version)
                or BUILDS.get(tuple(version)) != full["build_hash"]
                or full["blender_version"] not in {".".join(map(str, version)), ".".join(map(str, version)) + " LTS"}
                or full["declared_names"] != list(NAMES if version[0] == 4 else NAMES + EXTRA_NAMES)):
            return False
        target = full["target_pair"]
        if (type(target) is not list or len(target) != 2 or target[0] == target[1]
                or any(type(row) is not dict or set(row) != {"scene_name", "view_layer_name"}
                    or any(type(x) is not str or not x or len(x) > 128 for x in row.values()) for row in target)):
            return False
        rows = full["cases"]
        if type(rows) is not list or [row.get("name") for row in rows] != list(RUNTIME_SCENARIOS):
            return False
        sent, wire, terminal, dispatch = full["sent"], full["wire"], full["terminal"], full["dispatch"]
        if (any(type(x) is not list for x in (sent, wire, terminal, dispatch)) or len(sent) != 6
                or len(wire) != 6 or len(terminal) != 6 or len(dispatch) != 4
                or any(type(x) is not dict or set(x) != {"id", "action", "case"} for x in sent)):
            return False
        ids = [x["id"] for x in sent]
        if len(set(ids)) != 6 or any(type(x) is not str or len(x) != 32 or any(ch not in "0123456789abcdef" for ch in x) for x in ids):
            return False
        responses = {}
        for item in wire:
            if (type(item) is not dict or set(item) != {"id", "response", "sha256"}
                    or item["id"] not in ids or item["id"] in responses
                    or hashlib.sha256(canonical(item["response"])).hexdigest() != item["sha256"]):
                return False
            response = item["response"]
            if (type(response) is not dict or response.get("id") != item["id"] or response.get("protocol_version") != "1.0"
                    or type(response.get("ok")) is not bool
                    or type(response.get("timestamp")) is not str or not 0 < len(response["timestamp"]) <= 128
                    or set(response) != {"id", "protocol_version", "ok", "timestamp", "result" if response["ok"] else "error"}
                    or (response["ok"] and type(response["result"]) is not dict)
                    or (not response["ok"] and (type(response["error"]) is not dict
                        or set(response["error"]) not in ({"code", "message"}, {"code", "message", "context"})
                        or type(response["error"].get("code")) is not str or type(response["error"].get("message")) is not str
                        or ("context" in response["error"] and type(response["error"]["context"]) is not dict)))):
                return False
            responses[item["id"]] = response
        if [x["id"] for x in terminal] != ids:
            return False
        for item in terminal:
            if (type(item) is not dict or set(item) != {"id", "state", "completed", "response", "counts"}
                    or item["state"] != "completed" or item["completed"] is not True
                    or canonical(item["response"]) != canonical(responses[item["id"]])
                    or type(item["counts"]) is not dict or set(item["counts"]) != {"provider", "domain", "writer_entered", "writer_returned"}
                    or any(type(x) is not int or not 0 <= x <= 4096 for x in item["counts"].values())):
                return False
        terminal_by_id = {x["id"]: x for x in terminal}
        expected_dispatch = [ids[0], ids[1], ids[3], ids[5]]
        if [x.get("id") for x in dispatch] != expected_dispatch:
            return False
        for item in dispatch:
            if (type(item) is not dict or set(item) != {"id", "action", "case", "components"}
                    or {key: item[key] for key in ("id", "action", "case")} != sent[ids.index(item["id"])]
                    or type(item["components"]) is not dict or set(item["components"]) != set(RUNTIME_COMPONENTS)
                    or any(x is not True for x in item["components"].values())):
                return False
        for index, row in enumerate(rows):
            if (type(row) is not dict or set(row) != {"name", "requests", "before", "after", "source_preserved", "owned_root",
                    "evidence_root", "journal", "copy", "cleanup", "witness_consumed", "factory_restored", "healthy_after",
                    "projections", "target_identities"}
                    or row["requests"] != ids[2*index:2*index+2] or canonical(row["before"]) != canonical(row["after"])
                    or row["source_preserved"] is not True or row["factory_restored"] is not True or row["healthy_after"] is not True
                    or type(row["before"]) is not dict or set(row["before"]) != {"home", "targets", "raw_settings", "clocks", "node_defaults", "objects"}
                    or row["before"]["targets"] != target or not valid_source_snapshot(row["before"]["home"])
                    or type(row["target_identities"]) is not list or len(row["target_identities"]) != 2
                    or any(not runtime_target_identity(identity, item) for identity, item in zip(row["target_identities"], target, strict=True))):
                return False
            capture, inspect = (responses[x] for x in row["requests"])
            capture_counts = terminal_by_id[row["requests"][0]]["counts"]
            inspect_counts = terminal_by_id[row["requests"][1]]["counts"]
            if (sent[2*index] != {"id": ids[2*index], "action": "capture", "case": row["name"]}
                    or sent[2*index+1] != {"id": ids[2*index+1], "action": "inspect", "case": row["name"]}
                    or inspect.get("ok") is not True or not runtime_success_result(inspect["result"], "healthy")
                    or inspect_counts["domain"] != 0 or inspect_counts["writer_entered"] != 0 or inspect_counts["writer_returned"] != 0
                    or inspect_counts["provider"] < 1):
                return False
            if row["name"] == "success":
                cleanup = row["cleanup"]
                if (capture.get("ok") is not True or not runtime_success_result(capture["result"], "captured")
                        or row["witness_consumed"] is not True or capture_counts["domain"] != 1
                        or capture_counts["writer_entered"] != 1 or capture_counts["writer_returned"] != 1 or capture_counts["provider"] < 1
                        or not runtime_journal(row["journal"])
                        or type(row["copy"]) is not dict or type(cleanup) is not dict
                        or type(row["projections"]) is not list or len(row["projections"]) != 2
                        or len(row["copy"].get("retained_parser", [])) != 2
                        or any(not runtime_projection_matches(projection, proof["result"], identity)
                            for projection, proof, identity in zip(row["projections"], row["copy"]["retained_parser"], row["target_identities"], strict=True))
                        or cleanup.get("complete") is not True or cleanup.get("original_file_identity_known") is not True
                        or cleanup.get("durable_backup_qualified") is not False or cleanup.get("current_pixels_backup_qualified") is not False):
                    return False
                cell = row["journal"]["snapshots"][0]
                if (any(cell.get(key) is not True for key in ("native_entered", "native_returned", "consumed", "cleanup_entered", "cleanup_returned"))
                        or type(cell.get("available_memory_bytes")) is not int or cell["available_memory_bytes"] < 8*1024**3
                        or type(cell.get("available_disk_bytes")) is not int or cell["available_disk_bytes"] < 2*1024**3
                        or type(cell.get("native_seconds")) not in (float, int) or not 0 <= cell["native_seconds"] <= 300):
                    return False
            else:
                code = "PERMISSION_DENIED" if row["name"] == "permission_denial" else "NOT_IMPLEMENTED"
                if (capture.get("ok") is not False or capture["error"].get("code") != code
                        or any(capture_counts[key] != 0 for key in ("domain", "writer_entered", "writer_returned"))
                        or (row["name"] == "permission_denial" and capture_counts["provider"] < 1)
                        or (row["name"] == "factory_crossbinding" and (capture_counts["provider"] != 0
                            or capture["error"].get("context", {}).get("reason") != "GLB_CANONICAL_CONTEXT_COMPONENT_CHANGED"))
                        or row["journal"] is not None or row["copy"] is not None or row["cleanup"] is not None
                        or row["witness_consumed"] is not False or row["projections"] != []):
                    return False
        operation_ids = [response["result"]["operation"]["operation_id"] for response in responses.values() if response["ok"]]
        return len(operation_ids) == len(set(operation_ids)) == 4
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        return False


def validate_runtime_retained(full, bundle):
    """Cold-parse owned evidence, retaining original file identity as a receipt."""
    import importlib.util

    from scripts import blender_storage_snapshot_cleanup_smoke as cleanup
    if type(full) is not dict or not runtime_plain_json(full):
        raise ValueError("RUNTIME_CONTEXT_PLAIN_METADATA_REQUIRED")
    name = "_bcb_runtime_context_sdna"
    spec = importlib.util.spec_from_file_location(name, ROOT / "addon/blender_codex_bridge/blend_storage_sdna.py")
    if spec is None or spec.loader is None:
        raise ValueError("RUNTIME_CONTEXT_READER_REQUIRED")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    names = module.CYCLES_NAMES if full["version"][0] == 4 else module.CYCLES_502_NAMES
    def integers(value, length):
        return type(value) is list and len(value) == length and all(type(item) is int and item >= 0 for item in value)
    for row in full["cases"]:
        root, evidence = bundle / (row["name"] + "-owned"), bundle / (row["name"] + "-evidence")
        for path in (root, evidence):
            info = path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid()
                    or path.is_symlink()):
                raise ValueError("RUNTIME_CONTEXT_DIRECTORY_CHANGED")
        if row["owned_root"] != str(root) or row["evidence_root"] != str(evidence) or list(root.iterdir()):
            raise ValueError("RUNTIME_CONTEXT_ROOT_NOT_EMPTY")
        if row["name"] != "success":
            if list(evidence.iterdir()):
                raise ValueError("RUNTIME_CONTEXT_DENIAL_ARTIFACT")
            continue
        copy, cell, receipt = row["copy"], row["journal"]["snapshots"][0], row["cleanup"]
        if (type(copy) is not dict or set(copy) != {"owner_index", "original_path", "original_identity", "original_binding", "original_sha256", "copy", "retained_parser"}
                or type(copy["owner_index"]) is not int or copy["owner_index"] != 0
                or type(copy["retained_parser"]) is not list or len(copy["retained_parser"]) != 2
                or not integers(copy["original_identity"], 4) or not integers(copy["original_binding"], 8)
                or not integers(cell.get("file_identity"), 4) or not integers(cell.get("root_identity"), 2)
                or not integers(cell.get("directory_identity"), 2) or type(cell.get("file_bytes")) is not int
                or type(cell.get("root")) is not str or cell["root"] != str(root)
                or not cleanup.plain_cleanup(receipt)):
            raise ValueError("RUNTIME_CONTEXT_OWNER_METADATA_TYPES")
        leaf = Path(cell["directory"]).name
        if len(leaf) != 44 or not leaf.startswith("bcb-storage-") or any(ch not in "0123456789abcdef" for ch in leaf[12:]):
            raise ValueError("RUNTIME_CONTEXT_OWNER_DIRECTORY_LEAF")
        path = evidence / "0.blend"
        info = path.lstat()
        if (set(p.name for p in evidence.iterdir()) != {"0.blend"} or not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid() or info.st_nlink != 1
                or not cleanup.file_record(copy["copy"]) or ordinary_file(path, 1024**3) != copy["copy"]
                or copy["owner_index"] != 0 or copy["original_sha256"] != cell["file_sha256"]
                or copy["original_sha256"] != copy["copy"]["sha256"] or copy["original_identity"] != cell["file_identity"]
                or cell["file_bytes"] != info.st_size or len(copy["original_binding"]) != 8
                or copy["original_binding"][:2] != copy["original_identity"][:2]
                or copy["original_binding"][2] != os.geteuid() or copy["original_binding"][3:5] != [0o600, 1]
                or copy["original_binding"][5:7] != copy["original_identity"][2:]):
            raise ValueError("RUNTIME_CONTEXT_ORIGINAL_COPY_BINDING")
        original = Path(copy["original_path"])
        child = Path(cell["directory"])
        root_info = root.stat()
        if (original != child / "snapshot.blend" or child.parent != root or child.exists() or cell["filepath"] != str(original)
                or cell["root_identity"] != [root_info.st_dev, root_info.st_ino]
                or receipt["root"] != str(root) or receipt["directory_leaf"] != child.name
                or not cleanup.plain_cleanup(receipt) or receipt["complete"] is not True
                or len(copy["retained_parser"]) != 2):
            raise ValueError("RUNTIME_CONTEXT_CLEANUP_BINDING")
        for target, proof, projection, identity in zip(full["target_pair"], copy["retained_parser"],
                row["projections"], row["target_identities"], strict=True):
            actual = module.inspect_view_layer_storage(str(path), **target, allowed_names=names)
            if (canonical(proof) != canonical({"target": target, "result": actual})
                    or not runtime_projection_matches(projection, actual, identity)):
                raise ValueError("RUNTIME_CONTEXT_COLD_PROJECTION_CHANGED")
        if ordinary_file(path, 1024**3) != copy["copy"]:
            raise ValueError("RUNTIME_CONTEXT_COPY_CHANGED_DURING_PARSE")
    return True


class RuntimeContextDiagnostic(Fixture):
    """One original Runtime TCP route; no SceneJobs resumption is claimed."""
    def __init__(self, bpy, options, attestation):
        super().__init__(bpy, options, attestation)
        import queue
        self.sources = runtime_source_fingerprints()
        self.data = {key: self.data[key] for key in ("process_instance", "process_id", "version", "build_hash", "blender_version",
                                                    "binary", "private_display")}
        self.data.update(private_display_binding=ordinary_file(Path(attestation["manifest_path"]), 16384),
            schema=RUNTIME_SCHEMA, profile=RUNTIME_PROFILE, phase="runtime_context", source_fingerprints=self.sources,
            completed=False, case_deadline_seconds=300, limitations=dict.fromkeys(RUNTIME_FALSE, False))
        self.controls, self.done = queue.Queue(), threading.Event()
        self.rows, self.owners, self.counts = {}, {}, {}
        self.sent, self.wire, self.dispatch = [], [], []
        self.current_request = None
        self.active_operation = None
        self.worker_error = None
        self.worker_close_error = None
        self.deadline = time.monotonic() + 270
        self.original = None

    def observe(self, frame, event, argument):
        code = frame.f_code
        if code is self.try_start_code and event == "return" and argument is True:
            owner = frame.f_locals["self"]
            if owner.request.method == RUNTIME_METHOD:
                identifier = owner.request.id
                self.owners[identifier] = owner
                self.counts[identifier] = dict.fromkeys(("provider", "domain", "writer_entered", "writer_returned"), 0)
                self.current_request = identifier
        elif code is self.resolve_code and event == "return":
            owner = frame.f_locals["self"]
            if owner.request.id == self.current_request:
                self.current_request = None
        if self.current_request is None:
            return
        counts = self.counts[self.current_request]
        if event == "call" and code is self.provider_code:
            counts["provider"] += 1
        operation = self.active_operation
        if operation is not None and event in {"c_call", "c_return"}:
            native = operation.native
            if native is not None and argument is native.writer:
                counts["writer_entered" if event == "c_call" else "writer_returned"] += 1

    def components(self, context):
        from blender_codex_bridge import executor as executor_module
        from blender_codex_bridge import runtime as runtime_module
        from blender_codex_bridge.command_queue import QueuedRequest
        runtime, execution = self.runtime, self.runtime.executor
        owner, closure = context.check_cancelled.__self__, context.check_final_request
        codes = tuple(code for code in execution._invoke_owned.__code__.co_consts
                      if type(code) is CodeType and code.co_freevars == ("queued_owner",))
        factory = runtime.jobs.context_factory
        result = {"jobs_non_null": context.jobs is runtime.jobs and context.jobs is not None,
            "runtime_singleton": runtime_module.get_runtime() is runtime and runtime._registered,
            "registry": context.registry is runtime.registry is execution.registry,
            "state": context.state is runtime.state is execution.state,
            "permissions": context.permissions is runtime.permissions is execution.permissions,
            "checkpoints": context.checkpoints is runtime.checkpoints is execution.checkpoints,
            "evidence": context.evidence is execution.evidence,
            "glb_stage": context.glb_stage is runtime.glb_stage is execution.glb_stage,
            "service_executor": runtime.glb_stage._executor_origin is execution,
            "factory_origin": factory is self.factory and factory.__code__ is self.factory_code
                and factory.__globals__ is vars(runtime_module) and len(factory.__closure__) == 1
                and factory.__closure__[0].cell_contents is runtime,
            "queued_owner": type(owner) is QueuedRequest and self.owners.get(context.request_id) is owner
                and owner.state == "running" and owner.request.id == context.request_id,
            "original_closure": type(closure) is FunctionType and closure.__code__ in codes
                and closure.__globals__ is vars(executor_module) and len(closure.__closure__) == 1
                and closure.__closure__[0].cell_contents is owner,
            "main_thread": threading.current_thread() is threading.main_thread()}
        assert all(value is True for value in result.values())
        return result

    def handle_runtime(self, context, params):
        from blender_codex_bridge import storage_snapshot as adapter
        from blender_codex_bridge.storage_snapshot_effects import SnapshotJournal

        from scripts import blender_storage_snapshot_cleanup_smoke as cleanup
        assert set(params) == {"action", "case"} and params["case"] in RUNTIME_SCENARIOS and params["action"] in {"capture", "inspect"}
        self.dispatch.append({"id": context.request_id, **params, "components": self.components(context)})
        if params["action"] == "inspect":
            return {"healthy": True}
        row = self.rows[params["case"]]
        self.counts[context.request_id]["domain"] += 1
        journal = SnapshotJournal(1)
        operation = adapter.SnapshotOperation(context, self.bpy, self.scenes, row["owned_root"], journal)
        self.active_operation = operation
        try:
            witness = operation.run()
            projections = witness.consume(context, self.bpy, self.scenes)
            row["projections"] = json.loads(canonical([dataclasses.asdict(value) for value in projections]))
            row["witness_consumed"] = True
            row["copy"] = cleanup.Fixture.copy_native(self, operation, Path(row["evidence_root"]), 0)
            row["cleanup"] = adapter.cleanup_step(context, journal, operation.cleanup_owner)
            row["journal"] = journal.snapshot()
        finally:
            self.active_operation = None
        return {"captured": True}

    def control(self, action, name):
        event, result = threading.Event(), {}
        self.controls.put((action, name, event, result))
        assert event.wait(30) and result.get("ok"), result

    def main_control(self, action, name):
        assert threading.current_thread() is threading.main_thread()
        if action == "begin":
            root, evidence = self.folder / (name + "-owned"), self.folder / (name + "-evidence")
            root.mkdir(mode=0o700)
            evidence.mkdir(mode=0o700)
            self.rows[name] = {"name": name, "requests": [], "before": self.complete_snapshot(), "after": None,
                "source_preserved": False, "owned_root": str(root), "evidence_root": str(evidence), "journal": None,
                "copy": None, "cleanup": None, "witness_consumed": False, "factory_restored": False, "healthy_after": False,
                "projections": [], "target_identities": self.target_identities()}
            if name == "permission_denial":
                self.prefs.allow_save_project = False
            if name == "factory_crossbinding":
                assert self.runtime.glb_stage._executor_origin is self.runtime.executor
                self.runtime.glb_stage._executor_origin = None
        elif action == "restore":
            self.runtime.glb_stage._executor_origin = self.runtime.executor
            self.prefs.allow_save_project = True
            self.rows[name]["factory_restored"] = True
        elif action == "finish":
            row = self.rows[name]
            row["after"] = self.complete_snapshot()
            row["source_preserved"] = row["before"] == row["after"]
            row["healthy_after"] = True
        else:
            raise AssertionError("Unknown Runtime context fixture control")

    def worker_runtime(self, port):
        import socket
        client = stream = None
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=30)
            stream = client.makefile("rb")
            for name in RUNTIME_SCENARIOS:
                self.control("begin", name)
                for action in ("capture", "inspect"):
                    if action == "inspect":
                        self.control("restore", name)
                    identifier = os.urandom(16).hex()
                    self.sent.append({"id": identifier, "action": action, "case": name})
                    self.rows[name]["requests"].append(identifier)
                    client.sendall(canonical({"protocol_version": "1.0", "id": identifier, "method": RUNTIME_METHOD,
                        "params": {"action": action, "case": name}, "timeout_ms": 60000}) + b"\n")
                    raw = stream.readline(256*1024)
                    assert raw.endswith(b"\n") and len(raw) < 256*1024
                    response = json.loads(raw)
                    assert type(response) is dict and response.get("id") == identifier
                    self.wire.append({"id": identifier, "response": response, "sha256": hashlib.sha256(canonical(response)).hexdigest()})
                    if action == "inspect":
                        assert response["ok"] and response["result"]["healthy"], response
                    elif name == "success":
                        assert response["ok"] and response["result"]["captured"], response
                    else:
                        assert not response["ok"] and response["error"]["code"] == ("PERMISSION_DENIED" if name == "permission_denial" else "NOT_IMPLEMENTED"), response
                self.control("finish", name)
        except BaseException as error:
            self.worker_error = exception_receipt(error)
        finally:
            callbacks = []
            if client is not None:
                callbacks.append(lambda: client.shutdown(socket.SHUT_RDWR))
            if stream is not None:
                callbacks.append(stream.close)
            if client is not None:
                callbacks.append(client.close)
            for callback in callbacks:
                try:
                    callback()
                except BaseException as error:
                    if self.worker_close_error is None:
                        self.worker_close_error = exception_receipt(error)
                    if self.worker_error is None:
                        self.worker_error = self.worker_close_error
            self.done.set()

    def setup_runtime(self):
        import socket

        from blender_codex_bridge import runtime as runtime_module
        from blender_codex_bridge.command_queue import QueuedRequest
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.permissions import Permission
        self.setup()  # Original factory scene and original registered Runtime/provider.
        self.data.pop("target")
        self.data["declared_names"] = list(self.names)
        self.data["target_pair"] = self.complete_snapshot()["targets"]
        self.runtime.state.set_paused(False)
        self.runtime.state.set_emergency_stopped(False)
        try:
            self.runtime.registry.get(RUNTIME_METHOD)
        except BridgeError as error:
            assert error.code == "METHOD_NOT_FOUND"
        else:
            raise AssertionError("Fixture method already registered; refusing replacement")
        self.runtime.registry.register(RUNTIME_METHOD, self.handle_runtime, toolset="simulation", modifies=True,
            automatic_checkpoint=False, batchable=False,
            permissions=(Permission.INSPECT_SCENE, Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES))
        self.factory = self.runtime.jobs.context_factory
        self.factory_code = self.factory.__code__
        assert self.factory_code in runtime_module._RUNTIME_CONSTRUCTOR_CODE.co_consts
        assert self.factory_code.co_names == ("checked_executor_context", "executor")
        assert runtime_module.native_save_permission_provider_intact() and self.prefs.allow_execute_python is False
        self.push_position = self.runtime.checkpoints._window.position
        self.try_start_code, self.resolve_code = QueuedRequest.try_start.__code__, QueuedRequest.resolve.__code__
        self.provider_code = runtime_module.permission_snapshot.__code__
        self.original = (sys.getprofile(), threading.getprofile(), sys.gettrace(), threading.gettrace())
        assert all(value is None for value in self.original)
        sys.setprofile(self.observe)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        self.runtime.start_server("127.0.0.1", port, request_timeout=60)
        threading.Thread(target=self.worker_runtime, args=(port,), daemon=True, name="OwnedRuntimeContextJSONWorker").start()

    def tick_runtime(self):
        import queue
        try:
            assert time.monotonic() < self.deadline, "Runtime context diagnostic exceeded owned deadline"
            while True:
                try:
                    action, name, event, result = self.controls.get_nowait()
                except queue.Empty:
                    break
                try:
                    self.main_control(action, name)
                    result["ok"] = True
                finally:
                    event.set()
            if not self.done.is_set():
                return .01
            if self.worker_error is not None:
                self.fail_runtime()
                return None
            from blender_codex_bridge import runtime as runtime_module
            assert runtime_module.native_save_permission_provider_intact() and self.prefs.allow_execute_python is False
            self.runtime.stop_server()
            self.runtime.executor.stop()
            Observer.__exit__(self)
            self.data.update(completed=True, source_unchanged=runtime_source_fingerprints() == self.sources,
                cases=[self.rows[name] for name in RUNTIME_SCENARIOS], sent=self.sent, wire=self.wire, dispatch=self.dispatch,
                terminal=[{"id": item["id"], "state": self.owners[item["id"]].state,
                    "completed": self.owners[item["id"]].completed.is_set(), "response": self.owners[item["id"]].response.to_dict(),
                    "counts": dict(self.counts[item["id"]])} for item in self.sent], fixture_only_registration=True,
                original_preferences_provider=True, python_disabled=True, jobs_non_null=self.runtime.jobs is not None,
                hooks_restored=all(value is None for value in (sys.getprofile(), threading.getprofile(), sys.gettrace(), threading.gettrace())),
                services_stopped=not self.runtime.server.running and self.runtime.state.connected_clients == 0
                    and self.runtime.command_queue.pending_count == 0 and self.runtime.registry.executing_mutators == 0
                    and not self.runtime.state.is_executing,
                native_undo_pushes=self.runtime.checkpoints._window.position-self.push_position)
            assert validate_runtime_context(self.data, process_instance=self.data["process_instance"], process_id=os.getpid(),
                sources=self.sources, binary=self.binary)
            assert validate_runtime_retained(self.data, self.folder)
            self.flush()
            payload = {key: self.data[key] for key in ("schema", "profile", "phase", "completed", "blender_version", "version",
                "build_hash", "process_instance", "process_id", "source_fingerprints", "binary", "private_display_binding")}
            payload["full_receipt"] = ordinary_file(self.path, MAX_REPORT)
            print(RUNTIME_MARKER + canonical(payload).decode(), flush=True)
            from scripts.blender_artist_sidebar_smoke import owned_process_exit
            owned_process_exit(0)
        except BaseException as error:
            self.fail_runtime(error)
        return None


    def cached_runtime_failure(self, error=None):
        """Already cached plain evidence only; no owner/native/provider inspection."""
        primary = self.worker_error
        if primary is None:
            primary = exception_receipt(error)
        return {"completed": False, "failure": primary, "worker_failure": self.worker_error,
            "worker_close_failure": self.worker_close_error,
            "cases": [self.rows[name] for name in RUNTIME_SCENARIOS if name in self.rows],
            "sent": self.sent, "wire": self.wire, "dispatch": self.dispatch, "counts": self.counts}

    def fail_runtime(self, error=None):
        cached = self.cached_runtime_failure(error)
        cleanup_errors = []
        # Only explicit fixture actor restoration and original owned-service
        # teardown follows. executor.stop may consult owned Blender timers;
        # no storage operation/provider/recovery or scene reinspection follows.
        if self.runtime is not None:
            for callback in (lambda: setattr(self.runtime.glb_stage, "_executor_origin", self.runtime.executor),
                             self.runtime.server.stop, self.runtime.executor.stop):
                try:
                    callback()
                except BaseException as cleanup_error:
                    cleanup_errors.append(exception_receipt(cleanup_error))
        if self.original is not None:
            try:
                Observer.__exit__(self)
            except BaseException as cleanup_error:
                cleanup_errors.append(exception_receipt(cleanup_error))
        self.data.update(cached, fixture_cleanup_errors=cleanup_errors)
        self.flush()
        print(canonical(cached["failure"]).decode(), file=sys.stderr, flush=True)
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        owned_process_exit(1)

    def run_runtime(self):
        try:
            self.setup_runtime()
            self.bpy.app.timers.register(self.tick_runtime, first_interval=.01)
        except BaseException as error:
            self.fail_runtime(error)


def runtime_context_main(argv=None):
    assert threading.current_thread() is threading.main_thread()
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv and sys.dont_write_bytecode
    token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(token) == 32 and all(value in "0123456789abcdef" for value in token)
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    assert all(Path(os.environ[key]).resolve(strict=True) == folder for key in ("TEMP", "TMP", "TMPDIR"))
    assert all(Path(os.environ[key]).resolve(strict=True).parent == folder for key in
               ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"))
    assert Path.cwd().resolve() == folder / "working"
    sys.path[:0] = [str(ROOT), str(ROOT / "addon")]
    from scripts.blender_artist_sidebar_smoke import private_display_manifest
    attestation = private_display_manifest()
    import bpy
    assert sys.platform == "linux" and not bpy.app.background and bpy.data.filepath == ""
    assert BUILDS.get(tuple(bpy.app.version)) == bpy.app.build_hash.decode()
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-runtime-context", action="store_true", required=True)
    parser.add_argument("--bridge-phase", choices=("runtime_context",), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    options = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if argv is None else argv)
    fixture = RuntimeContextDiagnostic(bpy, options, attestation)
    bpy.app.timers.register(fixture.run_runtime, first_interval=.01)


if __name__ == "__main__":
    if "--bridge-runtime-context" in sys.argv:
        runtime_context_main()
    else:
        main()
