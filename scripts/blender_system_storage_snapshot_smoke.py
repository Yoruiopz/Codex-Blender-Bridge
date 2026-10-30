"""Owned stock-Blender serialization/raw-storage prerequisite, never a public tool.

Import is cold. The native writer is synchronous; parser bounds do not bound
native allocation or blocking. A serialized inspection proof is not a backup.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import sys
import threading
import time
import traceback
from contextlib import suppress
from pathlib import Path

SCHEMA = "system_storage_snapshot_prerequisite_v1"
PROFILE = "STOCK_VIEW_LAYER_RAW_CYCLES_V1"
MARKER = "BLENDER_SYSTEM_STORAGE_SNAPSHOT_OK "
REPORT = "system-storage-snapshot.json"
MAX_REPORT = 4 * 1024**2
BUILDS = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}
CASES = ("absent", "valid", "malformed_scalar", "writer_failure", "permission_denial", "stop_before", "stop_after")
SOURCES = ("scripts/blender_system_storage_snapshot_smoke.py", "scripts/run_blender_checks.py",
           "scripts/blender_glb_stage_smoke.py", "scripts/blender_artist_sidebar_smoke.py",
           "addon/blender_codex_bridge/blend_storage_sdna.py", "addon/blender_codex_bridge/native_save_profile.py")
NAMES = ("pass_debug_sample_count", "use_pass_volume_direct", "use_pass_volume_indirect",
         "use_pass_shadow_catcher", "use_denoising", "denoising_store_passes")
EXTRA_NAMES = ("pass_render_time", "use_pass_volume_scatter", "use_pass_volume_transmit", "use_pass_volume_majorant",
               "denoising_pass_follow_reflections", "denoising_pass_use_albedo_roughness_weighting")
FAMILIES = ("scenes", "collections", "objects", "meshes", "materials", "worlds", "images", "cameras", "lights",
            "armatures", "actions", "node_groups", "texts", "screens", "workspaces", "window_managers")


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


def source_hashes(root):
    return {name: ordinary_file(root / name, 1024**2)["sha256"] for name in SOURCES}


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


def attempt(writer, inspect_storage, original_getter, *, authorized=True, stopped=False, stop_after_native=False):
    """Private fixture control model; no canonical Runtime/TCP claims.

    After a stop the attempt performs no parser/getter/source inspection or
    cleanup. A distinct fixture-controller observation may inspect afterwards.
    """
    row = {"status": None, "native_entries": 0, "parser_entries": 0, "getter_entries": 0,
           "calls_after_stop": 0, "storage": None, "getter_value": None, "error": None,
           "bridge_cleanup_performed": False}
    if not authorized:
        row["status"] = "DENIED"
        return row
    if stopped:
        row["status"] = "STOPPED_BEFORE"
        return row
    row["native_entries"] += 1
    try:
        writer()
    except Exception as error:
        row.update(status="WRITER_FAILED", error={"type": type(error).__name__})
        return row
    if stop_after_native:
        row["status"] = "STOPPED_AFTER"
        return row
    row["parser_entries"] += 1
    try:
        proof = inspect_storage()
    except ValueError as error:
        row.update(status="REFUSED", error={"type": type(error).__name__, "reason": getattr(error, "reason", None)})
        return row
    row["storage"] = proof
    if proof["storage"]["state"] == "GROUP":
        row["getter_entries"] += 1
        row["getter_value"] = original_getter()
    row["status"] = "INSPECTED"
    return row


def validate_full(full, *, process_instance, sources, binary):
    """Fail closed on missing phases, stale receipts or broad qualification flags."""
    try:
        fixed = {"schema": SCHEMA, "profile": PROFILE, "completed": True,
                 "process_instance": process_instance, "source_sha256": sources, "binary": binary,
                 "canonical_runtime_qualified": False, "durable_backup_qualified": False,
                 "dirty_current_pixel_backup_qualified": False, "hidden_Main_passivity_claimed": False,
                 "native_memory_cap_claimed": False, "native_calls_preemptible": False, "windows_qualified": False,
                 "constrained_memory_native_qualified": False}
        if type(full) is not dict or any(type(full.get(key)) is not type(value) or full.get(key) != value
                                        for key, value in fixed.items()):
            return False
        version = full["version"]
        if (type(full.get("process_id")) is not int or full["process_id"] <= 0 or type(version) is not list
                or len(version) != 3 or any(type(value) is not int for value in version)
                or tuple(version) not in BUILDS or full["build_hash"] != BUILDS[tuple(version)]
                or full["declared_names"] != list(NAMES if version[0] == 4 else NAMES + EXTRA_NAMES)):
            return False
        rows = full["cases"]
        if type(rows) is not list or any(type(row) is not dict for row in rows) or [row.get("case") for row in rows] != list(CASES):
            return False
        expected = {"absent": (1, 1, 0, "INSPECTED"), "valid": (1, 1, 1, "INSPECTED"),
                    "malformed_scalar": (1, 1, 0, "REFUSED"), "writer_failure": (1, 0, 0, "WRITER_FAILED"),
                    "permission_denial": (0, 0, 0, "DENIED"), "stop_before": (0, 0, 0, "STOPPED_BEFORE"),
                    "stop_after": (1, 0, 0, "STOPPED_AFTER")}
        for row in rows:
            wanted = expected[row["case"]]
            if (any(type(row[key]) is not int for key in ("native_entries", "parser_entries", "getter_entries", "calls_after_stop"))
                    or tuple(row[key] for key in ("native_entries", "parser_entries", "getter_entries", "status")) != wanted
                    or row["calls_after_stop"] != 0 or row["bridge_cleanup_performed"] is not False
                    or row["before"] != row["after"] or row["fresh_controller_inspection"] is not True
                    or not valid_source_snapshot(row["before"])
                    or row["source_preserved"] is not True or type(row["native_seconds"]) not in {int, float}
                    or not 0 <= row["native_seconds"] <= 300):
                return False
            for stage in ("resources_before", "resources_after"):
                resource = row[stage]
                if (type(resource) is not dict or resource["measurement_is_reservation"] is not False
                        or any(type(resource[key]) is not int or resource[key] < 0
                               for key in ("available_memory_bytes", "host_available_memory_bytes", "visible_cgroup_levels", "disk_free_bytes"))):
                    return False
            if (row["resources_before"]["available_memory_bytes"] < 8 * 1024**3
                    or row["resources_before"]["disk_free_bytes"] < 2 * 1024**3):
                return False
            if row["case"] == "absent" and row["storage"]["storage"]["state"] != "ABSENT":
                return False
            raw_settings = row["before"]["raw_settings"]
            if row["case"] == "absent":
                if raw_settings != {"present": False, "values": []}:
                    return False
            else:
                expected_raw = [[name, bool(index % 2)] for index, name in enumerate(full["declared_names"])]
                if row["case"] == "malformed_scalar":
                    expected_raw = [[name, "wrong scalar storage" if name == "use_denoising" else value]
                                    for name, value in expected_raw]
                if (raw_settings["present"] is not True
                        or [[name, value] for name, _kind, value in raw_settings["values"]] != expected_raw):
                    return False
            if row["case"] == "valid":
                storage = row["storage"]["storage"]
                if (storage["state"] != "GROUP" or type(row["getter_value"]) is not bool
                        or {item["name"] for item in storage["children"]} != set(full["declared_names"])
                        or any(item["type"] not in {1, 10} for item in storage["children"])):
                    return False
                raw_value = next(item["value"] for item in storage["children"] if item["name"] == "use_denoising")
                if type(raw_value) is not int or row["getter_value"] is not bool(raw_value):
                    return False
                if {item["name"]: item["value"] for item in storage["children"]} != {
                        name: int(index % 2) for index, name in enumerate(full["declared_names"])}:
                    return False
            if row["case"] == "malformed_scalar" and (row["error"]["reason"] != "RAW_PROPERTY_TYPE_UNQUALIFIED"
                                                       or row["raw_wrong_scalar_retained"] is not True):
                return False
            if row["case"] == "writer_failure" and row["error"]["type"] not in {"OSError", "RuntimeError"}:
                return False
        peak = full["peak_memory"]
        return (full["source_unchanged"] is True and full["one_use_no_yield_proof"] is True
                and peak["metric"] == "ru_maxrss" and peak["units"] == "KiB"
                and type(peak["value"]) is int and peak["value"] > 0
                and type(full["elapsed_seconds"]) in (float, int) and 0 <= full["elapsed_seconds"] <= 300)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


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


class Fixture:
    def __init__(self, root, folder, bpy, attestation):
        self.root, self.folder, self.bpy, self.attestation = root, folder, bpy, attestation
        self.started, self.getter_calls = time.monotonic(), 0
        self.sources = source_hashes(root)
        binary = ordinary_file(Path(bpy.app.binary_path).resolve(strict=True), 1024**3)
        self.binary = {key: binary[key] for key in ("path", "sha256")}
        self.data = {"schema": SCHEMA, "profile": PROFILE, "completed": False,
                     "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": os.getpid(),
                     "blender_version": bpy.app.version_string, "version": list(bpy.app.version),
                     "build_hash": bpy.app.build_hash.decode(), "source_sha256": self.sources, "binary": self.binary,
                     "attestation": attestation, "cases": [], "failure": None,
                     "canonical_runtime_qualified": False, "durable_backup_qualified": False,
                     "dirty_current_pixel_backup_qualified": False, "hidden_Main_passivity_claimed": False,
                     "native_memory_cap_claimed": False, "native_calls_preemptible": False, "windows_qualified": False,
                     "constrained_memory_native_qualified": False,
                     "one_use_no_yield_proof": True,
                     "observation_scope": "Retained Main identity/users/names/flags, authored mesh/material/image pixels/packed bytes and explicit context; not full hidden memory/UI equality"}

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

    def flush(self):
        raw = canonical(self.data) + b"\n"
        assert len(raw) <= MAX_REPORT
        target = self.folder / REPORT
        temporary = target.with_suffix(".next")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def resources(self):
        import shutil

        from blender_codex_bridge.native_save_profile import available_memory_facts
        values = available_memory_facts()
        values["disk_free_bytes"] = shutil.disk_usage(self.folder).free
        values["measurement_is_reservation"] = False
        return values

    def run(self):
        try:
            self.setup()
            from blender_codex_bridge.blend_storage_sdna import inspect_view_layer_storage
            group = None
            for case in CASES:
                assert time.monotonic() - self.started < 240
                if case == "absent":
                    self.layer.property_unset("cycles")
                    assert self.layer.is_property_set("cycles", ghost=False) is False
                    group = None
                else:
                    if group is None:
                        group = self.layer.cycles
                    # Raw mapping aliases this held group's actual USER/SYSTEM
                    # backing store. Setup ends before the operation baseline.
                    author_owned_settings(group, self.names, malformed=case == "malformed_scalar")
                before = self.snapshot(group)
                resources_before = self.resources()
                assert resources_before["available_memory_bytes"] >= 8 * 1024**3
                assert resources_before["disk_free_bytes"] >= 2 * 1024**3
                destination = self.folder / (case + ".blend")
                if case == "writer_failure":
                    destination = self.folder / "missing-parent" / "cannot-write.blend"
                assert not destination.exists()
                seconds = []
                def writer(destination=destination, seconds=seconds):
                    started = time.monotonic()
                    try:
                        self.bpy.data.libraries.write(str(destination), {self.scene}, path_remap="NONE", fake_user=False, compress=False)
                    finally:
                        seconds.append(time.monotonic() - started)
                def inspect_storage(destination=destination):
                    return inspect_view_layer_storage(str(destination), self.scene.name, self.layer.name,
                                                      allowed_names=self.names)
                def original_getter():
                    self.getter_calls += 1
                    return self.layer.cycles.use_denoising
                row = attempt(writer, inspect_storage, original_getter, authorized=case != "permission_denial",
                              stopped=case == "stop_before", stop_after_native=case == "stop_after")
                row.update(case=case, native_seconds=sum(seconds), before=before,
                           # A separate fixture controller observes after the
                           # attempt has terminated, including stopped attempts.
                           after=self.snapshot(group), fresh_controller_inspection=True)
                row["resources_before"] = resources_before
                row["resources_after"] = self.resources()
                row["source_preserved"] = row["before"] == row["after"]
                if case == "malformed_scalar":
                    row["raw_wrong_scalar_retained"] = group["use_denoising"] == "wrong scalar storage"
                row["retained_files"] = sorted(path.name for path in self.folder.glob(case + ".blend*") if path.is_file())
                row["file_receipt"] = ordinary_file(destination, 1024**3) if destination.is_file() else None
                self.data["cases"].append(row)
                self.flush()
            self.data["source_unchanged"] = source_hashes(self.root) == self.sources
            self.data["elapsed_seconds"] = time.monotonic() - self.started
            import resource
            self.data["peak_memory"] = {"metric": "ru_maxrss", "units": "KiB", "value": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            self.data["completed"] = True
            assert validate_full(self.data, process_instance=self.data["process_instance"], sources=self.sources, binary=self.binary)
            self.flush()
            receipt = ordinary_file(self.folder / REPORT, MAX_REPORT)
            summary = {key: self.data[key] for key in ("schema", "profile", "completed", "blender_version", "version", "build_hash",
                       "process_instance", "process_id", "source_sha256", "binary")}
            summary["full_receipt"] = receipt
            print(MARKER + canonical(summary).decode(), flush=True)
        except BaseException:
            self.data["completed"] = False
            self.data["failure"] = traceback.format_exc()
            self.flush()
            print(self.data["failure"], file=sys.stderr, flush=True)
            os._exit(1)
        self.bpy.ops.wm.quit_blender()
        return None


def main():
    sys.path.insert(0, str(Path(__file__).resolve(strict=True).parents[1]))
    from scripts.blender_glb_stage_smoke import owned_entry
    root, folder, bpy, attestation = owned_entry()
    assert threading.current_thread() is threading.main_thread()
    fixture = Fixture(root, folder, bpy, attestation)
    bpy.app.timers.register(fixture.run, first_interval=.2)


if __name__ == "__main__":
    main()
