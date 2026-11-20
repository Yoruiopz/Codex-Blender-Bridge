"""Static GLB/FBX export, typed import, and saved-project reopen across three processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import stat
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = "blender_codex_bridge"
CASE = "static_asset_delivery"
MARKERS = {phase: f"BLENDER_STATIC_DELIVERY_{phase.upper()}_OK " for phase in ("writer", "importer", "reader")}
FORMATS = ("GLB", "FBX")
ASSETS = {format: f"static sample.{format.lower()}" for format in FORMATS}
COLLECTIONS = {format: f"Imported static {format}" for format in FORMATS}
SOURCE_DIR = "exported assets"
RETAINED_DIR = "retained delivery artifacts"
PROJECT = "imported static assets.blend"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
WORLD_TOLERANCE = 1e-5
SENTINEL = "Unrelated delivery sentinel"
EXPORT_DIAGNOSTICS = "BRIDGE_TEST_STATIC_DELIVERY_EXPORT_DIAGNOSTICS"


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_file(path, limit):
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
    assert not getattr(before, "st_file_attributes", 0) & 0x400
    assert 0 < before.st_size <= limit
    with path.open("rb") as stream:
        assert _identity(os.fstat(stream.fileno())) == _identity(before)
        data = stream.read(limit + 1)
        assert _identity(os.fstat(stream.fileno())) == _identity(before)
    assert len(data) == before.st_size and _identity(path.lstat()) == _identity(before)
    return data


def file_proof(path):
    data = _read_file(path, MAX_FILE_BYTES)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def phase_receipt(bundle, phase):
    raw = _read_file(bundle / f"{phase}.json", MAX_RECEIPT_BYTES)
    receipt = json.loads(raw)
    assert receipt["phase"] == phase and receipt["completed"] is True
    assert re.fullmatch("[0-9a-f]{32}", receipt["process_instance"])
    assert type(receipt["process_id"]) is int and receipt["process_id"] > 0
    assert receipt["using_registered_executor_timer"] is True
    return receipt, hashlib.sha256(raw).hexdigest()


def compare_geometry(expected, observed):
    """Match world vertices and face membership while allowing format vertex splits."""
    original = expected["points"]
    candidates = observed["points"]
    assert 1 <= len(original) <= len(candidates) <= 64
    assert all(len(point) == 3 and all(math.isfinite(value) for value in point) for point in original + candidates)
    assert len(set(map(tuple, original))) == len(original)
    assert 1 <= len(expected["faces"]) == len(observed["faces"]) <= 64
    assert all(len(face) == 3 and len(set(face)) == 3 and
               all(type(index) is int and 0 <= index < len(points) for index in face)
               for faces, points in ((expected["faces"], original), (observed["faces"], candidates))
               for face in faces)
    matches, largest_error = [], 0.
    for point in candidates:
        errors = [max(abs(a - b) for a, b in zip(point, other, strict=True)) for other in original]
        match = [index for index, error in enumerate(errors) if error <= WORLD_TOLERANCE]
        assert len(match) == 1, ("World position not uniquely represented", point, original)
        matches.append(match[0])
        largest_error = max(largest_error, errors[match[0]])
    assert set(matches) == set(range(len(original)))
    actual_faces = sorted(tuple(sorted(matches[index] for index in face)) for face in observed["faces"])
    wanted_faces = sorted(tuple(sorted(face)) for face in expected["faces"])
    assert actual_faces == wanted_faces, ("Triangle membership changed", wanted_faces, actual_faces)
    return {"maximum_world_coordinate_error": largest_error, "unique_world_vertices": len(original),
            "source_triangles": len(wanted_faces), "observed_vertices_with_splits": len(candidates)}


def geometry(obj):
    assert obj.type == "MESH"
    return {"points": [list(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices],
            "faces": [list(face.vertices) for face in obj.data.polygons]}


def hierarchy(objects):
    return {obj.name: {"type": obj.type, "parent": obj.parent.name if obj.parent else None}
            for obj in objects}


def scene_facts(bpy):
    scene = bpy.context.scene
    return {"mode": bpy.context.mode, "name": scene.name, "units": scene.unit_settings.system,
            "metres": float(scene.unit_settings.scale_length),
            "frame": [scene.frame_current, scene.frame_subframe],
            "fps": [scene.render.fps, scene.render.fps_base]}


def observe_export_source(bpy, objects):
    """Read owned static preview and context facts, without calling the exporter."""
    context, scene = bpy.context, bpy.context.scene
    layer = context.view_layer
    observations = {
        **scene_facts(bpy),
        "scene_identity": (scene.session_uid, scene.as_pointer()),
        "view_layer_identity": layer.as_pointer(),
        "frame_range": [scene.frame_start, scene.frame_end],
        "selection": [obj.name for obj in layer.objects if obj.select_get(view_layer=layer)],
        "active": layer.objects.active.name if layer.objects.active else None,
        "scene_object_inventory": [(obj.name, obj.session_uid) for obj in bpy.data.objects],
        "source_object_count": len(objects),
    }
    for obj in objects:
        mesh = obj.data
        fields = {
            "name": obj.name, "type": obj.type, "identity": (obj.session_uid, obj.as_pointer()),
            "parent": obj.parent.name if obj.parent else None,
            "matrix_basis": [list(row) for row in obj.matrix_basis],
            "matrix_parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
            "matrix_world": [list(row) for row in obj.matrix_world],
            "animation_present": obj.animation_data is not None,
        }
        if mesh is not None:
            fields.update(
                data_identity=(mesh.session_uid, mesh.as_pointer()),
                vertices=[list(vertex.co) for vertex in mesh.vertices],
                triangles=[list(polygon.vertices) for polygon in mesh.polygons],
                weights=[[(group.group, group.weight) for group in vertex.groups] for vertex in mesh.vertices],
                smooth=[bool(polygon.use_smooth) for polygon in mesh.polygons],
                uv=[list(loop.uv) for loop in mesh.uv_layers[0].data] if mesh.uv_layers else [],
            )
        observations.update({f"{obj.type.lower()}.{field}": value for field, value in fields.items()})
    return observations


def export_change_summary(before, after):
    """Report only field names, frame values and counts. Raw RNA identities stay local."""
    changed = [
        field for field in sorted(before.keys() | after.keys())
        if json.dumps(before.get(field), allow_nan=False) != json.dumps(after.get(field), allow_nan=False)
    ]
    return {
        "changed_fields": changed,
        "numeric_representation_only": [field for field in changed if before.get(field) == after.get(field)],
        "frame_before": before["frame"], "frame_after": after["frame"],
        "source_object_count_before": before["source_object_count"], "source_object_count_after": after["source_object_count"],
        "scene_object_count_before": len(before["scene_object_inventory"]),
        "scene_object_count_after": len(after["scene_object_inventory"]),
        "selected_count_before": len(before["selection"]), "selected_count_after": len(after["selection"]),
        "active_changed": "active" in changed,
    }


def sentinel_facts(bpy, *, identities=False):
    obj = bpy.data.objects[SENTINEL]
    facts = {"geometry": geometry(obj), "data": obj.data.name,
             "material": [obj.data.materials[0].name, list(obj.data.materials[0].diffuse_color)],
             "collections": sorted(collection.name for collection in obj.users_collection),
             "transform": [list(row) for row in obj.matrix_world]}
    if identities:
        layer = bpy.context.view_layer
        facts.update(ids=[item.session_uid for item in (obj, obj.data, obj.data.materials[0], bpy.context.scene)],
                     active=layer.objects.active.name if layer.objects.active else None,
                     selection=sorted(item.name for item in layer.objects if item.select_get()))
    return facts


def setup_owned_scene(bpy):
    scene = bpy.context.scene
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC", 1.
    scene.render.fps, scene.render.fps_base = 30, 1.
    scene.frame_set(3, subframe=.25)
    obj = bpy.data.objects["Cube"]
    obj.name = SENTINEL
    obj.location = (-3.125, 2.5, .25)
    material = bpy.data.materials.new("Unrelated delivery material")
    material.diffuse_color = (.2, .4, .6, 1.)
    obj.data.materials.clear()
    obj.data.materials.append(material)
    bpy.context.view_layer.update()


def author_asset(bpy, format):
    scene = bpy.context.scene
    root = bpy.data.objects.new(f"Static {format} Parent", None)
    scene.collection.objects.link(root)
    root.location, root.rotation_euler.z = (2.125, -1.25, .625), .31
    mesh = bpy.data.meshes.new(f"Static {format} Mesh Data")
    mesh.from_pydata([(.12, .25, 0.), (1.2, .1, .2), (.25, 1.5, .375), (.8, 1.1, .75)],
                     [], [(0, 1, 2), (1, 3, 2)])
    mesh.update()
    obj = bpy.data.objects.new(f"Static {format} Mesh", mesh)
    scene.collection.objects.link(obj)
    obj.parent = root
    obj.location, obj.scale = (.75, .5, .25), (1.2, .8, 1.1)
    bpy.context.view_layer.update()
    return root, obj


class Scenario:
    def __init__(self, bpy, runtime, prefs, bundle, phase, token, rpc_worker):
        self.bpy, self.runtime, self.prefs, self.bundle = bpy, runtime, prefs, bundle
        self.phase, self.rpc_worker = phase, rpc_worker
        self.assets = bundle / SOURCE_DIR
        self.retained = bundle / RETAINED_DIR
        self.project = bundle / "saved projects" / PROJECT
        self.observe_export_failure = os.environ.get(EXPORT_DIAGNOSTICS) == "1"
        self.deadline = time.monotonic() + 100.
        self.stage = "starting"
        self.evidence = {
            "phase": phase, "blender_version": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode("ascii"), "platform": sys.platform,
            "process_instance": token, "process_id": os.getpid(),
            "using_registered_executor_timer": bpy.app.timers.is_registered(runtime.executor._timer_callback),
            "methods": [],
        }
        assert self.evidence["using_registered_executor_timer"] is True
        self.flow = {"writer": self.writer, "importer": self.importer, "reader": self.reader}[phase]()
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.port = port.getsockname()[1]
        assert runtime.start_server("127.0.0.1", self.port, request_timeout=18.) == ("127.0.0.1", self.port)

    def call(self, method, params=None, *, error=None):
        assert len(self.evidence["methods"]) < 48
        self.stage = method
        request = {"id": f"delivery-{self.phase}-{len(self.evidence['methods'])}", "protocol_version": "1.0",
                   "method": method, "params": {} if params is None else params, "timeout_ms": 18000}
        outcome = {}
        thread = threading.Thread(target=self.rpc_worker, args=(self.port, request, outcome), daemon=True)
        thread.start()
        while thread.is_alive():
            yield
        if "error" in outcome:
            raise outcome["error"]
        response = outcome["response"]
        code = response.get("error", {}).get("code")
        self.evidence["methods"].append({"method": method, "ok": response["ok"], "code": code})
        if error is not None:
            assert response["ok"] is False and code == error and response["error"]["message"], response
            return response["error"]
        assert response["ok"] is True, response
        return response["result"]

    def writer(self):
        bpy, prefs = self.bpy, self.prefs
        assert not bpy.data.filepath and prefs.asset_directory == ""
        assert not prefs.all_dangerous_permissions and not prefs.allow_unrestricted_project_texture_paths
        self.assets.mkdir(mode=0o700)
        self.project.parent.mkdir(mode=0o700)
        setup_owned_scene(bpy)
        authored = {format: author_asset(bpy, format) for format in FORMATS}
        scene, sentinel = scene_facts(bpy), sentinel_facts(bpy, identities=True)
        prefs.asset_directory = str(self.assets)
        prefs.allow_inspect_scene = prefs.allow_external_files = prefs.allow_edit_scene = True
        yield from self.call("toolsets.enable", {"name": "asset_delivery"})
        yield from self.call("asset.export_preview", {"object_names": [SENTINEL], "format": "GLB",
                                                     "include_animation": False}, error="NOT_IMPLEMENTED")
        records = {}
        for format, (root, obj) in authored.items():
            args = {"object_names": [root.name, obj.name], "format": format, "include_animation": False}
            expected = {"hierarchy": hierarchy((root, obj)), "geometry": geometry(obj), "mesh": obj.name}
            preview = yield from self.call("asset.export_preview", args)
            assert preview["unit_scale_metres"] == 1. and preview["file_written"] is False
            assert preview["required_accepted_losses"] == ["VERTEX_SPLITS", "AXIS_CONVERSION"], preview
            target = self.assets / ASSETS[format]
            request = {**args, "filepath": str(target), "expected_fingerprint": preview["fingerprint"],
                       "accepted_losses": preview["required_accepted_losses"]}
            prefs.allow_save_project = False
            yield from self.call("asset.export", request, error="PERMISSION_DENIED")
            prefs.allow_save_project = True
            yield from self.call("asset.export", {**request, "accepted_losses": []}, error="INVALID_ARGUMENT")
            assert not target.exists()
            before = observe_export_source(bpy, (root, obj)) if self.observe_export_failure else None
            try:
                result = yield from self.call("asset.export", request)
            except Exception:
                if before is not None:
                    try:
                        after = observe_export_source(bpy, (root, obj))
                        diagnostic = export_change_summary(before, after)
                        diagnostic.update(format=format, blender_version=self.evidence["blender_version"],
                                          build_hash=self.evidence["build_hash"], platform=self.evidence["platform"])
                        print("BLENDER_STATIC_DELIVERY_EXPORT_FAILURE " + json.dumps(diagnostic, allow_nan=False), flush=True)
                    except Exception as observation_error:
                        print(f"Static delivery export failure observation aborted: {type(observation_error).__name__}",
                              file=sys.stderr, flush=True)
                raise
            effects = result["external_effects"]
            proof = file_proof(target)
            assert result["format"] == format and result["affected_objects"] == args["object_names"], result
            assert result["source_and_context_preserved"] and result["native_context_restored"], result
            assert effects["file_published"] and effects["published_bytes_verified"] and effects["staging_cleanup"] == "removed"
            assert Path(effects["filepath"]) == target and effects["file_sha256"] == proof["sha256"]
            assert effects["file_bytes"] == proof["bytes"] and not result["native_roundtrip_verified"]
            yield from self.call("asset.export", request, error="INVALID_ARGUMENT")
            assert file_proof(target) == proof and geometry(obj) == expected["geometry"]
            assert hierarchy((root, obj)) == expected["hierarchy"]
            assert scene_facts(bpy) == scene and sentinel_facts(bpy, identities=True) == sentinel
            records[format] = {"asset": ASSETS[format], "proof": proof, "expected": expected,
                               "declared_export_losses": result["accepted_losses"]}
        assert {path.name for path in self.assets.iterdir()} == set(ASSETS.values())
        self.evidence.update(artifacts=records, units=scene["metres"], writer_preservation=True,
                             material_scope_refusal=True, no_overwrite=True)

    def _prior(self, phase):
        record, digest = phase_receipt(self.bundle, phase)
        assert record["process_instance"] != self.evidence["process_instance"]
        assert record["process_id"] != self.evidence["process_id"]
        for key in ("blender_version", "build_hash", "platform"):
            assert self.evidence[key] == record[key]
        self.evidence[f"{phase}_receipt_sha256"] = digest
        return record

    def _snapshot_import(self, format, expected):
        bpy = self.bpy
        collection = bpy.data.collections[COLLECTIONS[format]]
        assert collection.name in bpy.context.scene.collection.children
        observed_hierarchy = hierarchy(collection.objects)
        assert observed_hierarchy == expected["hierarchy"], (observed_hierarchy, expected["hierarchy"])
        obj = collection.objects[expected["mesh"]]
        assert not any(slot.material for slot in obj.material_slots) and obj.animation_data is None and not obj.modifiers
        observed = geometry(obj)
        comparison = compare_geometry(expected["geometry"], observed)
        return {"hierarchy": observed_hierarchy, "geometry": observed, **comparison}

    def importer(self):
        bpy, prefs = self.bpy, self.prefs
        writer = self._prior("writer")
        assert not bpy.data.filepath and prefs.asset_source_directory == "" and prefs.project_directory == ""
        assert writer["units"] == 1. and set(writer["artifacts"]) == set(FORMATS)
        setup_owned_scene(bpy)
        scene, sentinel = scene_facts(bpy), sentinel_facts(bpy, identities=True)
        prefs.asset_source_directory, prefs.project_directory = str(self.assets), str(self.project.parent)
        prefs.allow_inspect_scene = prefs.allow_edit_scene = prefs.allow_transform_objects = True
        prefs.allow_edit_mesh = prefs.allow_edit_materials = prefs.allow_edit_animation = prefs.allow_delete_objects = True
        yield from self.call("toolsets.enable", {"name": "asset_delivery"})
        records = {}
        for format, record in writer["artifacts"].items():
            target = self.assets / ASSETS[format]
            proof = record["proof"]
            assert record["asset"] == target.name and file_proof(target) == proof
            args = {"filepath": str(target), "format": format, "include_animation": False}
            prefs.allow_external_files = False
            yield from self.call("asset.import_preview", args, error="PERMISSION_DENIED")
            prefs.allow_external_files = True
            preview = yield from self.call("asset.import_preview", args)
            assert preview["source"]["file_sha256"] == proof["sha256"] and preview["source"]["file_bytes"] == proof["bytes"]
            expected_count = len(record["expected"]["hierarchy"])
            assert preview["objects"] == expected_count and preview["file_written"] is False
            request = {**args, "collection_name": COLLECTIONS[format], "expected_fingerprint": preview["fingerprint"],
                       "accepted_losses": preview["required_accepted_losses"]}
            yield from self.call("asset.import", {**request, "expected_fingerprint": "0" * 64}, error="INVALID_ARGUMENT")
            assert bpy.data.collections.get(COLLECTIONS[format]) is None and file_proof(target) == proof
            result = yield from self.call("asset.import", request)
            assert result["imported"] and result["collection"] == COLLECTIONS[format], result
            assert result["protected_measured_state_preserved"] and result["owned_allocation_inventory_complete"], result
            assert result["external_effects"]["staging_cleanup"] == "removed"
            assert not result["fresh_process_reopen_verified"] and not result["project_saved"]
            assert set(result["imported_objects"]) == set(record["expected"]["hierarchy"])
            assert not result["imported_materials"] and not result["imported_images"]
            assert file_proof(target) == proof and result["source"]["file_sha256"] == proof["sha256"]
            assert scene_facts(bpy) == scene and sentinel_facts(bpy, identities=True) == sentinel
            assert all(not scene.name.startswith("Bridge Private Asset Import") for scene in bpy.data.scenes)
            records[format] = {**self._snapshot_import(format, record["expected"]), "artifact": proof,
                               "declared_import_losses": result["accepted_losses"]}
        request = {"filepath": str(self.project), "overwrite": False}
        prefs.allow_save_project = False
        yield from self.call("project.save", request, error="PERMISSION_DENIED")
        assert not self.project.exists()
        prefs.allow_save_project = True
        saved = yield from self.call("project.save", request)
        summary = file_proof(self.project)
        assert saved["saved"] and Path(saved["filepath"]) == self.project, saved
        assert saved["recovery_checkpoint"]["file_sha256"] == summary["sha256"], saved
        yield from self.call("project.save", request, error="INVALID_ARGUMENT")
        assert file_proof(self.project) == summary and sentinel_facts(bpy, identities=True) == sentinel
        assert self.assets.resolve(strict=True) == self.assets and not self.retained.exists()
        assert {path.name for path in self.assets.iterdir()} == set(ASSETS.values())
        self.assets.rename(self.retained)
        assert not self.assets.exists()
        for format in FORMATS:
            assert file_proof(self.retained / ASSETS[format]) == records[format]["artifact"]
        self.evidence.update(imports=records, project={"name": PROJECT, **summary}, scene=scene,
                             sentinel=sentinel_facts(bpy), importer_preservation=True, no_overwrite=True,
                             source_directory_removed=True)

    def reader(self):
        bpy = self.bpy
        writer, importer = self._prior("writer"), self._prior("importer")
        assert importer["writer_receipt_sha256"] == self.evidence["writer_receipt_sha256"]
        assert importer["project"] == {"name": PROJECT, **file_proof(self.project)}
        assert importer["source_directory_removed"] is True and not self.assets.exists()
        status = yield from self.call("bridge.status")
        assert Path(status["filepath"]) == self.project and bpy.data.is_saved and not bpy.data.is_dirty
        assert scene_facts(bpy) == importer["scene"] and sentinel_facts(bpy) == importer["sentinel"]
        records = {}
        for format in FORMATS:
            exported, imported = writer["artifacts"][format], importer["imports"][format]
            target = self.retained / ASSETS[format]
            assert file_proof(target) == exported["proof"] == imported["artifact"]
            observed = self._snapshot_import(format, exported["expected"])
            assert observed == {key: imported[key] for key in observed}
            records[format] = observed
        assert file_proof(self.project) == {key: importer["project"][key] for key in ("bytes", "sha256")}
        self.evidence.update(reopened=records, project=importer["project"], fresh_process_reopen=True,
                             original_sources_absent=True, sentinel_preserved=True)

    def tick(self):
        try:
            assert threading.current_thread() is threading.main_thread()
            assert time.monotonic() < self.deadline, f"Timed out in {self.stage}"
            try:
                next(self.flow)
            except StopIteration:
                self.evidence["completed"] = True
                payload = json.dumps(self.evidence, allow_nan=False, sort_keys=True)
                assert len(payload.encode("utf-8")) + 1 <= MAX_RECEIPT_BYTES
                with (self.bundle / f"{self.phase}.json").open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                print(MARKERS[self.phase] + payload, flush=True)
                window = self.bpy.context.window_manager.windows[0]
                with self.bpy.context.temp_override(window=window):
                    self.bpy.ops.wm.quit_blender("EXEC_DEFAULT")
                return None
            return .025
        except Exception:
            print(f"Static delivery {self.phase} failed in {self.stage}", file=sys.stderr, flush=True)
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)


def main():
    import addon_utils
    import bpy

    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=MARKERS, required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    token = os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    assert re.fullmatch("[0-9a-f]{32}", token)
    assert not bpy.app.background and {"--factory-startup", "--disable-autoexec"} <= set(sys.argv)
    assert tuple(bpy.app.version[:2]) == (4, 5) and bpy.app.build_type == b"Release", "Requires official Blender 4.5 LTS"
    bundle = args.bridge_bundle.resolve(strict=True)
    assert bundle == args.bridge_bundle and bundle.name == f"{CASE}-bundle" and bundle.is_dir() and not bundle.is_symlink()
    temp = Path(os.environ["TEMP"])
    assert temp.parent == bundle.parent and temp.name == f"{CASE}-{args.bridge_phase}-temp"
    for name in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        path = Path(os.environ[name])
        assert path.parent == temp and path.is_dir() and not path.is_symlink()
    assert not (bundle / f"{args.bridge_phase}.json").exists()
    if args.bridge_phase == "reader":
        importer, _digest = phase_receipt(bundle, "importer")
        assert importer["source_directory_removed"] is True and not (bundle / SOURCE_DIR).exists()
        project = bundle / "saved projects" / PROJECT
        assert project.resolve(strict=True) == project
        assert importer["project"] == {"name": PROJECT, **file_proof(project)}
        assert bpy.ops.wm.open_mainfile(filepath=str(project), load_ui=False, use_scripts=False) == {"FINISHED"}
    assert not any(name == ADDON or name.startswith(ADDON + ".") for name in sys.modules)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "addon"))
    from scripts.blender_persistent_save_smoke import rpc_worker

    assert addon_utils.enable(ADDON, default_set=True, persistent=True) is not None
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime

    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    prefs = get_preferences()
    assert prefs is not None
    scenario = Scenario(bpy, get_runtime(), prefs, bundle, args.bridge_phase, token, rpc_worker)
    bpy.app.timers.register(scenario.tick, first_interval=.05)


if __name__ == "__main__":
    main()
