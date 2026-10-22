"""Opt-in, tiny three-process asset-only packaging research; not a saver."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import sys
import time
import traceback
import zlib
from pathlib import Path

import bpy

PREFIX = "BLENDER_PORTABLE_BLEND_WORKER_"
PHASE = os.environ["BRIDGE_TEST_PORTABLE_BLEND_PHASE"]
BUNDLE = Path(os.environ["TMPDIR"]).parent / "portable-blend-worker-bundle"
SCRIPT_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SUPPORTED = {"scenes", "collections", "objects", "meshes", "cameras", "worlds", "materials", "images"}
UI = {"window_managers", "screens", "workspaces"}
PIXELS = bytes([255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 64, 128, 64, 32, 0])
PREPARED = False
STARTUP_PROFILE = None
READER_STATE = None
CAMERA_PANORAMA_FIELDS = (
    "panorama_type", "fisheye_fov", "fisheye_lens", "latitude_min", "latitude_max",
    "longitude_min", "longitude_max", "fisheye_polynomial_k0", "fisheye_polynomial_k1",
    "fisheye_polynomial_k2", "fisheye_polynomial_k3", "fisheye_polynomial_k4",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    return {"version": list(bpy.app.version), "hash": bpy.app.build_hash.decode("ascii")}


def plain(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return [plain(item) for item in value]


def props(owner):
    return {key: plain(owner[key]) if not hasattr(owner[key], "to_dict") else owner[key].to_dict()
            for key in sorted(owner.keys())}


def fields(owner, names):
    return {key: plain(getattr(owner, key)) for key in names}


def inventory():
    result = {}
    for prop in bpy.data.bl_rna.properties:
        if prop.type == "COLLECTION" and prop.identifier != "all_ids":
            values = list(getattr(bpy.data, prop.identifier))
            if values:
                result[prop.identifier] = values
    assert set(result) <= SUPPORTED | UI, sorted(set(result) - SUPPORTED - UI)
    assert sum(len(values) for values in result.values()) <= 64
    return result


def ref(value):
    return None if value is None else {"type": value.bl_rna.identifier, "name": value.name}


def node_tree(tree):
    if tree is None:
        return None
    assert len(tree.nodes) <= 16 and len(tree.links) <= 32
    return {
        "nodes": [{"name": node.name, "type": node.bl_idname,
                   "location": list(node.location), "mute": node.mute,
                   "image": ref(node.image) if node.type == "TEX_IMAGE" else None,
                   "inputs": [{"identifier": socket.identifier, "name": socket.name,
                               "default": plain(socket.default_value) if hasattr(socket, "default_value") else None}
                              for socket in node.inputs]}
                  for node in tree.nodes],
        "links": sorted([link.from_node.name, link.from_socket.identifier,
                         link.to_node.name, link.to_socket.identifier] for link in tree.links),
    }


def assets():
    result = {}
    for family, owners in inventory().items():
        if family in UI:
            continue
        records = []
        for owner in sorted(owners, key=lambda value: value.name):
            assert owner.library is None and owner.override_library is None
            assert owner.asset_data is None
            animation_descriptor = owner.bl_rna.properties.get("animation_data")
            if animation_descriptor is not None:
                assert owner.animation_data is None
            record = {"name": owner.name, "fake_user": owner.use_fake_user, "custom": props(owner)}
            record["native_animation_descriptor_present"] = animation_descriptor is not None
            if family == "objects":
                assert not owner.modifiers and not owner.constraints
                record.update(fields(owner, ("location", "rotation_mode", "rotation_euler", "scale", "hide_render", "hide_viewport")))
                record.update(data=ref(owner.data), parent=ref(owner.parent),
                              collections=sorted(value.name for value in owner.users_collection))
            elif family == "collections":
                record.update(objects=sorted(value.name for value in owner.objects),
                              children=sorted(value.name for value in owner.children))
            elif family == "meshes":
                assert not owner.has_custom_normals and owner.shape_keys is None
                record.update(vertices=[list(value.co) for value in owner.vertices],
                              edges=[list(value.vertices) for value in owner.edges],
                              polygons=[list(value.vertices) for value in owner.polygons],
                              polygon_materials=[value.material_index for value in owner.polygons],
                              polygon_smooth=[value.use_smooth for value in owner.polygons],
                              materials=[ref(value) for value in owner.materials],
                              uv_active_index=owner.uv_layers.active_index,
                              uv_layers=[{"name": layer.name, "active_render": layer.active_render,
                                          "active_clone": layer.active_clone,
                                          "uv": [list(item.uv) for item in layer.data]} for layer in owner.uv_layers])
            elif family == "cameras":
                record.update(fields(owner, ("type", "lens", "ortho_scale", "sensor_fit", "sensor_width", "sensor_height", "clip_start", "clip_end", "shift_x", "shift_y")))
                record["panorama_native_fields"] = fields(owner, CAMERA_PANORAMA_FIELDS)
            elif family == "scenes":
                record.update(camera=ref(owner.camera), world=ref(owner.world),
                              objects=sorted(value.name for value in owner.objects),
                              collection_children=sorted(value.name for value in owner.collection.children),
                              units=fields(owner.unit_settings, ("system", "scale_length", "length_unit", "system_rotation")),
                              frames=fields(owner, ("frame_start", "frame_end", "frame_current", "frame_subframe")))
            elif family in {"materials", "worlds"}:
                record.update(use_nodes=owner.use_nodes, tree=node_tree(owner.node_tree))
                if family == "materials":
                    record["diffuse_color"] = list(owner.diffuse_color)
            elif family == "images":
                assert owner.has_data and owner.packed_file is not None
                assert owner.size[:] == (2, 2)
                record.update(fields(owner, ("source", "filepath", "alpha_mode")))
                record.update(size=list(owner.size), colorspace=owner.colorspace_settings.name,
                              pixels=list(owner.pixels[:]), packed_sha256=hashlib.sha256(bytes(owner.packed_file.data)).hexdigest())
            records.append(record)
        result[family] = records
    assert sum(len(values) for values in result.values()) <= 32
    return result


def flags(snapshot):
    return {family: {item["name"]: item["fake_user"] for item in values}
            for family, values in snapshot.items()}


def with_flags(snapshot, flag):
    result = json.loads(json.dumps(snapshot))
    for values in result.values():
        for item in values:
            item["fake_user"] = flag
    return result


def load_verified_packed_images(expected):
    expected_images = {item["name"]: item for item in expected["images"]}
    assert set(bpy.data.images.keys()) == set(expected_images)
    # Freeze and prove every input before a pixel getter may populate native cache.
    for image in bpy.data.images:
        item = expected_images[image.name]
        assert image.packed_file is not None and image.source == item["source"]
        assert hashlib.sha256(bytes(image.packed_file.data)).hexdigest() == item["packed_sha256"]
        assert image.filepath == item["filepath"]
        assert image.colorspace_settings.name == item["colorspace"]
        assert image.alpha_mode == item["alpha_mode"]
    for image in bpy.data.images:
        image.pixels[0]
        assert image.has_data


def predict_serialization(snapshot):
    expected = json.loads(json.dumps(snapshot))
    native_inputs = {}
    conversions = []
    native_build = build()["hash"]
    assert native_build in {"62c1db4208e8", "d13f752e3b9c"}
    for record in snapshot["cameras"]:
        camera = bpy.data.cameras[record["name"]]
        descriptor = camera.bl_rna.properties["panorama_type"]
        assert descriptor.is_runtime is False
        numeric_enum = descriptor.enum_items[record["panorama_native_fields"]["panorama_type"]].value
        compatibility = dict(record["panorama_native_fields"], panorama_type=numeric_enum)
        native_inputs[record["name"]] = {"native_fields": record["panorama_native_fields"],
                                        "native_panorama_enum_integer": numeric_enum,
                                        "predicted_compatibility_properties": compatibility}
        assert "cycles" not in record["custom"]
        if native_build == "62c1db4208e8":
            target = next(item for item in expected["cameras"] if item["name"] == record["name"])
            target["custom"]["cycles"] = compatibility
            conversions.append({"family": "cameras", "name": record["name"],
                                "kind": "NATIVE_SERIALIZED_CAMERA_COMPATIBILITY_ADDITION",
                                "raw_custom_storage_preserved": False, "added_cycles": compatibility})
    return {"expected_asset_projection": expected, "native_camera_inputs": native_inputs,
            "declared_conversions": conversions, "raw_custom_storage_preserved": not conversions,
            "computed_before_libraries_write": True,
            "source": "Exact camera_blend_write temporary compatibility IDProperty copy; no output readback adoption"}


def live():
    return {"filepath": bpy.data.filepath, "dirty": bpy.data.is_dirty,
            "scene": bpy.context.scene.as_pointer(), "window": bpy.context.window.as_pointer(),
            "active": ref(bpy.context.view_layer.objects.active),
            "selected": sorted(value.name for value in bpy.context.selected_objects),
            "ids": {family: [(owner.name, owner.as_pointer(), owner.session_uid, owner.users, owner.use_fake_user)
                             for owner in values] for family, values in inventory().items()}}


def preferences():
    paths = bpy.context.preferences.filepaths
    return {"file_preview_type": paths.file_preview_type, "save_version": paths.save_version,
            "asset_libraries": [{"name": value.name, "path": value.path} for value in paths.asset_libraries],
            "addons": sorted(bpy.context.preferences.addons.keys()),
            "autoexec": bpy.context.preferences.filepaths.use_scripts_auto_execute}


def callbacks():
    return {name: [{"module": getattr(item, "__module__", None), "name": getattr(item, "__qualname__", None)}
                   for item in getattr(bpy.app.handlers, name)]
            for name in dir(bpy.app.handlers) if isinstance(getattr(bpy.app.handlers, name), list)}


def environment():
    names = ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "TMPDIR")
    result = {name: os.environ[name] for name in names}
    for value in result.values():
        path = Path(value)
        assert path.is_dir() and not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    return {"directories": result, "variable_names": sorted(os.environ), "cwd": os.getcwd(),
            "filesystem_sandbox": False, "network_sandbox": False}


def png(path):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    rows = b"\x00" + PIXELS[:8] + b"\x00" + PIXELS[8:]
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def phase_record():
    return {"phase": PHASE, "process_id": os.getpid(), "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
            "build": build(), "script_sha256": SCRIPT_SHA, "environment": environment(),
            "preferences_before": preferences(), "callbacks_before": callbacks()}


def write_json(path, value):
    assert not path.exists()
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def require_previous(name):
    path = BUNDLE / (name + ".json")
    data = json.loads(path.read_text())
    assert data["phase"] == name and data["build"] == build() and data["script_sha256"] == SCRIPT_SHA
    assert data["process_id"] != os.getpid() and data["process_instance"] != os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    assert stat.S_IMODE(BUNDLE.stat().st_mode) == 0o700 and not BUNDLE.is_symlink()
    return data, sha(path)


def writer():
    assert not bpy.app.background
    BUNDLE.mkdir(mode=0o700)
    record = phase_record()
    record["factory_startup_before_empty_reset"] = STARTUP_PROFILE
    scene = bpy.context.scene
    scene.name = "PortableWorkerScene"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.1
    scene["portable_worker_inert_note"] = "Research data only; no authority"
    collection = bpy.data.collections.new("PortableWorkerCollection")
    scene.collection.children.link(collection)
    mesh = bpy.data.meshes.new("PortableWorkerMesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    uv = mesh.uv_layers.new(name="WorkerUV")
    for item, value in zip(uv.data, ((0, 0), (1, 0), (0, 1)), strict=True):
        item.uv = value
    obj = bpy.data.objects.new("PortableWorkerObject", mesh)
    collection.objects.link(obj)
    obj.location = (0.2, -0.3, 0.5)
    camera = bpy.data.cameras.new("PortableWorkerCameraData")
    camera_obj = bpy.data.objects.new("PortableWorkerCamera", camera)
    collection.objects.link(camera_obj)
    scene.camera = camera_obj
    world = bpy.data.worlds.new("PortableWorkerWorld")
    world.use_nodes = True
    scene.world = world
    material = bpy.data.materials.new("PortableWorkerMaterial")
    material.use_nodes = True
    mesh.materials.append(material)
    for name, role, alpha in (("Color", "sRGB", "STRAIGHT"), ("Mask", "Non-Color", "CHANNEL_PACKED")):
        path = BUNDLE / (name + ".png")
        png(path)
        image = bpy.data.images.load(str(path), check_existing=False)
        image.name = "PortableWorker" + name
        image.colorspace_settings.name = role
        image.alpha_mode = alpha
        image.pack()
        image.filepath = "//" + path.name
        image.pixels[0]
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name = "Worker" + name
        node.image = image
        target = material.node_tree.nodes.get("Principled BSDF").inputs["Base Color" if name == "Color" else "Roughness"]
        material.node_tree.links.new(node.outputs["Color"], target)
    orphan = bpy.data.meshes.new("PortableWorkerOrphan")
    orphan.use_fake_user = True
    before, before_live = assets(), live()
    serialization = predict_serialization(before)
    assert flags(before)["meshes"][orphan.name] is True
    roots = {owner for family, owners in inventory().items() if family not in UI for owner in owners}
    target = BUNDLE / "asset closure.blend"
    assert not target.exists()
    started = time.perf_counter()
    bpy.data.libraries.write(str(target), roots, path_remap="NONE", fake_user=True, compress=False)
    record["library_write_blocking_seconds"] = time.perf_counter() - started
    assert assets() == before and live() == before_live
    for name in ("Color", "Mask"):
        (BUNDLE / (name + ".png")).rename(BUNDLE / (name + ".source-unavailable"))
    sentinel = BUNDLE / "outside-worker-sentinel.txt"
    sentinel.write_text("Task-owned sentinel outside the helper profile.\n")
    record.update(source_assets=before, source_live_before=before_live, source_live_after=live(),
                  predicted_serialization=serialization,
                  payload_sha256=sha(target), payload_bytes=target.stat().st_size,
                  original_flags=flags(before), sentinel_sha256=sha(sentinel),
                  serialized_ui_ids=False, source_unchanged=True)
    write_json(BUNDLE / "writer.json", record)
    return record


def worker():
    assert bpy.app.background
    source, previous_sha = require_previous("writer")
    record = phase_record()
    payload = BUNDLE / "asset closure.blend"
    assert sha(payload) == source["payload_sha256"]
    target = BUNDLE / "normalized asset.blend"
    assert not target.exists()
    assert bpy.ops.wm.open_mainfile(filepath=str(payload), load_ui=False, use_scripts=False) == {"FINISHED"}
    load_verified_packed_images(source["source_assets"])
    actual_before = assets()
    expected_delivery = source["predicted_serialization"]["expected_asset_projection"]
    expected_before = with_flags(expected_delivery, True)
    record["opened_projection_matches_predicted_serialization"] = actual_before == expected_before
    record["opened_projection"] = actual_before
    if actual_before != expected_before:
        write_json(BUNDLE / "worker-before-refusal.json", record)
        raise AssertionError("Asset-only open changed protected projection beyond predicted fake-user flags")
    expected_flags = source["original_flags"]
    for family, values in inventory().items():
        if family not in UI:
            for owner in values:
                owner.use_fake_user = expected_flags[family][owner.name]
    assert assets() == expected_delivery
    prefs = bpy.context.preferences.filepaths
    prefs.file_preview_type = "NONE"
    prefs.save_version = 0
    record["preferences_for_disposable_worker_save"] = preferences()
    started = time.perf_counter()
    assert bpy.ops.wm.save_as_mainfile(filepath=str(target), check_existing=False, copy=True,
                                     relative_remap=False, compress=False) == {"FINISHED"}
    record["native_save_blocking_seconds"] = time.perf_counter() - started
    assert assets() == expected_delivery
    assert sha(payload) == source["payload_sha256"]
    assert sha(BUNDLE / "outside-worker-sentinel.txt") == source["sentinel_sha256"]
    record.update(previous_record_sha256=previous_sha, previous_process_id=source["process_id"],
                  previous_process_instance=source["process_instance"], normalized_sha256=sha(target),
                  normalized_bytes=target.stat().st_size, restored_original_flags=expected_flags,
                  source_writer_record_sha256=previous_sha, callbacks_after=callbacks(),
                  asset_projection_after=assets(), production_safe_save_verified=False)
    record["declared_conversions"] = source["predicted_serialization"]["declared_conversions"]
    record["raw_custom_storage_preserved"] = source["predicted_serialization"]["raw_custom_storage_preserved"]
    write_json(BUNDLE / "worker.json", record)
    return record


def reader_open():
    assert not bpy.app.background
    worker_record, previous_sha = require_previous("worker")
    source, source_sha = require_previous("writer")
    assert worker_record["source_writer_record_sha256"] == source_sha
    record = phase_record()
    target = BUNDLE / "normalized asset.blend"
    assert sha(target) == worker_record["normalized_sha256"]
    assert bpy.ops.wm.open_mainfile(filepath=str(target), load_ui=False, use_scripts=False) == {"FINISHED"}
    # Return only plain immutable handoff data across the destroyed UI context.
    return worker_record, previous_sha, source, record


def reader():
    assert READER_STATE is not None
    worker_record, previous_sha, source, record = READER_STATE
    assert sha(BUNDLE / "worker.json") == previous_sha
    assert sha(BUNDLE / "normalized asset.blend") == worker_record["normalized_sha256"]
    assert bpy.context.window is not None
    record["verified_after_native_ui_reentry"] = True
    load_verified_packed_images(source["source_assets"])
    reopened = assets()
    record.update(previous_record_sha256=previous_sha, previous_process_id=worker_record["process_id"],
                  previous_process_instance=worker_record["process_instance"], asset_projection=reopened,
                  original_projection=source["source_assets"], flags_preserved=flags(reopened) == source["original_flags"],
                  complete_tiny_asset_projection_preserved=reopened == source["source_assets"],
                  complete_declared_delivery_projection_preserved=reopened == source["predicted_serialization"]["expected_asset_projection"],
                  declared_conversions=source["predicted_serialization"]["declared_conversions"],
                  raw_custom_storage_preserved=source["predicted_serialization"]["raw_custom_storage_preserved"],
                  production_safe_save_verified=False, full_project_delivery_verified=False,
                  windows_qualified=False, filesystem_sandbox=False, network_sandbox=False)
    write_json(BUNDLE / "reader.json", record)
    assert reopened == source["predicted_serialization"]["expected_asset_projection"]
    assert sha(BUNDLE / "outside-worker-sentinel.txt") == source["sentinel_sha256"]
    return record


def run():
    global PREPARED, STARTUP_PROFILE, READER_STATE
    try:
        if PHASE == "writer" and not PREPARED:
            STARTUP_PROFILE = {"preferences": preferences(), "callbacks": callbacks()}
            assert bpy.ops.wm.read_factory_settings(use_empty=True) == {"FINISHED"}
            PREPARED = True
            # Factory reset replaced the screen. Re-enter after its native UI update.
            return 0.5
        if PHASE == "reader" and not PREPARED:
            READER_STATE = reader_open()
            PREPARED = True
            return 0.5
        record = {"writer": writer, "worker": worker, "reader": reader}[PHASE]()
        print(PREFIX + PHASE.upper() + "_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "phase": PHASE,
            "process_id": os.getpid(), "process_instance": record["process_instance"],
            "record_sha256": sha(BUNDLE / (PHASE + ".json")), "research_only": True,
            "production_safe_save_verified": False}), flush=True)
        if not bpy.app.background:
            bpy.ops.wm.quit_blender()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        if not bpy.app.background:
            os._exit(1)
        raise
    return None


if bpy.app.background:
    run()
else:
    bpy.app.timers.register(run, first_interval=0.1, persistent=True)
