"""Private stock DTO -> fresh-worker experiment; launch only through the runner.

No source serialization, context sync, rendering, mutation provider or child
launcher occurs in capture. The reader phase is the runner's separate worker.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import struct
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
SOURCE_REFS = {(4, 5, 14): "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
               (5, 2, 2): "d13f752e3b9c4f8c261cda552b1021f8bcc0382c"}
WRITER_MARKER = "BLENDER_ISOLATED_ASSET_PREVIEW_WRITER_OK "
WORKER_MARKER = "BLENDER_ISOLATED_ASSET_PREVIEW_WORKER_OK "


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def owned_file(path: Path, maximum: int) -> bytes:
    assert not path.is_symlink()
    meta = path.stat()
    assert stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and 0 < meta.st_size <= maximum
    raw = path.read_bytes()
    assert len(raw) == meta.st_size
    return raw


def binary_identity(path: Path) -> dict[str, Any]:
    """Stream a bounded executable fingerprint before the measured source turn."""
    resolved = path.resolve(strict=True)
    meta = resolved.stat()
    assert stat.S_ISREG(meta.st_mode) and 0 < meta.st_size <= 1024 * 1024 * 1024
    hasher, count = hashlib.sha256(), 0
    with resolved.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            assert count <= meta.st_size
            hasher.update(chunk)
    after = resolved.stat()
    assert count == meta.st_size and (meta.st_size, meta.st_mtime_ns, meta.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
    return {"path": str(resolved), "bytes": count, "sha256": hasher.hexdigest()}


def freeze(path: Path, raw: bytes) -> str:
    assert not path.exists() and not path.is_symlink()
    with path.open("xb") as stream:
        assert stream.write(raw) == len(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)
    return digest(raw)


def owned_profile() -> tuple[str, Path, dict[str, Any]]:
    """Do not acquire owned-exit authority before all operational checks pass."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", required=True, choices=("writer", "reader"))
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    assert "--" in sys.argv, "Use the phased isolated runner"
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert sys.platform == "linux", "Only the reviewed Linux development profile is qualified for this experiment"
    assert threading.current_thread() is threading.main_thread()
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert bool(bpy.app.background) == (args.bridge_phase == "reader")
    assert ("--background" in sys.argv) == (args.bridge_phase == "reader")
    process = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert re.fullmatch(r"[a-f0-9]{32}", process), "Use the phased isolated runner"
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    assert folder.is_dir() and folder != Path("/tmp")
    paths = {}
    for key in ("TEMP", "TMP", "TMPDIR", "HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS",
                "BLENDER_USER_DATAFILES", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        path = Path(os.environ[key])
        assert path.is_absolute() and not path.is_symlink()
        resolved = path.resolve(strict=True)
        assert resolved.is_dir() and resolved.is_relative_to(folder)
        if key in {"TEMP", "TMP", "TMPDIR"}:
            assert resolved == folder
        paths[key] = str(resolved)
    assert Path.cwd().resolve().is_relative_to(folder)
    bundle = args.bridge_bundle
    assert bundle.is_absolute() and not bundle.is_symlink() and bundle.resolve(strict=True) == bundle
    assert bundle.parent == folder.parent and bundle.name == "isolated_asset_preview_probe-bundle"
    assert bundle.is_dir() and bundle.stat().st_uid == os.getuid()
    assert not bpy.data.filepath
    version = tuple(bpy.app.version)
    source_ref = SOURCE_REFS[version]
    build_hash = bpy.app.build_hash.decode("ascii")
    assert source_ref.startswith(build_hash) and len(build_hash) >= 12
    assert bpy.app.build_type.decode("ascii") == "Release"
    display = None
    if args.bridge_phase == "writer":
        from blender_artist_sidebar_smoke import private_display_manifest
        display = private_display_manifest()
    return args.bridge_phase, bundle, {
        "phase": args.bridge_phase, "role": "source_writer" if args.bridge_phase == "writer" else "render_worker",
        "process_instance": process, "process_id": os.getpid(), "blender_version": bpy.app.version_string,
        "build_hash": build_hash, "source_ref": source_ref, "build_type": "Release", "main_thread": True,
        "binary_identity": binary_identity(Path(bpy.app.binary_path)),
        "paths": paths, "private_display": display,
        "script_sha256": digest(Path(__file__).read_bytes()),
        "helper_sha256": digest((ROOT / "scripts" / "native_isolated_asset_preview.py").read_bytes()),
        "public_tool_registered": False, "windows_qualified": False,
        "whole_project_save_qualified": False, "current_viewport_qualified": False,
        "original_material_appearance_qualified": False, "complete_H02_or_F01_qualified": False,
    }


def bits(values: Any) -> list[str]:
    return [struct.pack("<f", value).hex() for value in values]


def token(owner: Any) -> list[int]:
    return [int(owner.as_pointer()), int(owner.session_uid)]


def raw_selection(layer: Any) -> list[list[Any]]:
    """FIXTURE ONLY: exact Release-pinned raw Base filter, never production API.

    Iteration does not ensure pending Base sync. Debug builds assert a stronger
    precondition and are refused by owned_profile. This cannot establish a
    supported raw unsynchronized Base identity guarantee for a public tool.
    """
    return sorted([[obj.name, *token(obj)] for obj in layer.objects.selected])


def writer(bundle: Path, record: dict[str, Any]) -> dict[str, Any]:
    from blender_codex_bridge.task_plans import TaskPlanStore, contents
    from native_isolated_asset_preview import capture

    assert not bpy.app.background and {obj.name for obj in bpy.data.objects} == {"Cube", "Camera", "Light"}
    bpy.context.preferences.use_preferences_save = False
    window = bpy.context.window
    scene = bpy.data.scenes.new("Owned Isolated Geometry Source")
    window.scene = scene
    layer = window.view_layer
    vertices = [(-1., -1., -.5), (1., -1., -.5), (1., 1., -.5), (-1., 1., -.5),
                (-1., -1., .5), (1., -1., .5), (1., 1., .5), (-1., 1., .5)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new("Owned Isolated Source Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    target = bpy.data.objects.new("Owned Isolated Preview Target", mesh)
    scene.collection.objects.link(target)
    target.rotation_mode = "XYZ"
    target.location, target.rotation_euler, target.scale = (.25, -.5, .75), (.2, -.3, .5), (1.1, .8, 1.2)
    material = bpy.data.materials.new("Owned Protected Original Material")
    material.diffuse_color = (.3, .4, .5, .6)
    mesh.materials.append(material)
    protected = bpy.data.objects.new("Owned Protected Pending Hidden Selection", None)
    scene.collection.objects.link(protected)
    protected.location = (7., 8., 9.)
    target["preview_keep_ref"] = protected  # Known USER ID reference; DTO must not traverse or copy it.
    actor = bpy.data.objects.new("Owned Unrelated Dirty Animated Object", None)
    scene.collection.objects.link(actor)
    action = bpy.data.actions.new("Owned Unrelated Raw Action")
    slot = action.slots.new("OBJECT", actor.name)
    action_layer = action.layers.new("Owned Raw Layer")
    strip = action_layer.strips.new(type="KEYFRAME")
    bag = strip.channelbag(slot, ensure=True)
    curve = bag.fcurves.new(data_path="location", index=0)
    curve.keyframe_points.add(2)
    for point, frame, value in zip(curve.keyframe_points, (1., 10.), (20., 30.), strict=True):
        point.co = frame, value
        point.handle_left_type = point.handle_right_type = "FREE"
        point.handle_left, point.handle_right = (frame - 1., value), (frame + 1., value)
        point.interpolation = "LINEAR"
    curve.update()
    actor.animation_data_create().action = action
    actor.animation_data.action_slot = slot
    layer.update()  # Setup only, before pending state and armed baseline.
    for obj in layer.objects:
        obj.select_set(False, view_layer=layer)
    protected.select_set(True, view_layer=layer)
    layer.objects.active = protected
    layer.update()  # Last source evaluation before measurement.
    protected.hide_set(True, view_layer=layer)  # Ensures before setting BASE_HIDDEN, then leaves sync pending.
    actor.location = (0., 0., 0.)  # Deliberately disagrees with the current-frame Action value 20.
    assert bits(actor.location)[0] == "00000000" and bits(curve.keyframe_points[0].co)[1] == "0000a041"
    assert raw_selection(layer) == [[protected.name, *token(protected)]]

    def projection() -> dict[str, Any]:
        # Literal prebound fields only. No bpy.context/active/mode/evaluated fields.
        return {"target": {"identity": token(target), "mesh_identity": token(mesh),
                    "mesh": {"vertices": [bits(v.co) for v in mesh.vertices],
                             "edges": [list(e.vertices) for e in mesh.edges],
                             "polygons": [list(p.vertices) for p in mesh.polygons]},
                    "channels": {key: bits(getattr(target, key)) for key in
                                 ("location", "rotation_euler", "scale", "delta_location", "delta_rotation_euler",
                                  "delta_rotation_quaternion", "delta_scale")}},
                "unrelated_actor": {"identity": token(actor), "location": bits(actor.location),
                    "action_identity": token(action), "slot_handle": int(slot.handle),
                    "data_path": curve.data_path, "array_index": curve.array_index,
                    "points": [{"co": bits(p.co), "left": bits(p.handle_left), "right": bits(p.handle_right),
                                "interpolation": p.interpolation} for p in curve.keyframe_points]},
                "known_USER_reference": {"owner_identity": token(target), "property": "preview_keep_ref",
                    "value_identity": token(target["preview_keep_ref"]), "owner_users": target.users,
                    "referenced_users": protected.users},
                "protected": {"identity": token(protected), "location": bits(protected.location),
                              "material_identity": token(material), "material_diffuse": bits(material.diffuse_color),
                              "material_bindings": [token(m) for m in mesh.materials]},
                "scene_identity": token(scene), "raw_selected_fixture_only": raw_selection(layer)}

    # Runtime metadata is armed privately; this does not invoke or qualify public protection admission.
    store = TaskPlanStore()
    store.replace(contents("Geometry preview without changing protected data",
                           [{"id": "preview", "description": "Inspect bounded geometry preview"}],
                           [protected.name, actor.name]), scope=None)
    store.baseline = {"fixture_projection": projection(), "scope": "literal fields and Release-only raw-selected diagnostic"}
    store.protection = {"fixture_only_armed": True, "generation": store.protection_generation}
    before = projection()
    metadata = copy.deepcopy(vars(store))
    baseline_identity, protection_identity = id(store.baseline), id(store.protection)
    dto = capture(bpy, target.name)
    after = projection()
    assert after == before, "Source literal projection changed during DTO capture"
    assert vars(store) == metadata and id(store.baseline) == baseline_identity and id(store.protection) == protection_identity
    assert dto["mesh"] == before["target"]["mesh"]
    for key, value in before["target"]["channels"].items():
        assert dto["transform"][key] == value
    dto_sha = freeze(bundle / "geometry.json", canonical(dto))
    positive = {"source_projection_before": before, "source_projection_after": after,
                "complete_measured_projection_preserved": True, "known_USER_ID_reference_and_user_counts_preserved": True,
                "unrelated_dirty_raw_x": before["unrelated_actor"]["location"][0],
                "unrelated_current_frame_key_x": before["unrelated_actor"]["points"][0]["co"][1],
                "task_plan_metadata_before": metadata, "task_plan_metadata_after": copy.deepcopy(vars(store)),
                "task_plan_baseline_and_protection_identity_preserved": True, "task_plan_metadata_remained_armed": True,
                "task_plan_public_protection_admission_qualified": False,
                "source_context_getters_after_baseline": 0, "source_evaluation_calls_after_baseline": 0,
                "source_restore_writes": 0, "source_serialization_calls": 0, "single_main_thread_turn_no_yield": True,
                "hidden_storage_or_full_Main_purity_claim": False, "raw_Base_supported_public_guarantee": False}
    # Separate destructive counterexample control after the positive interval; never repair or adopt it.
    selected_before_control = raw_selection(layer)
    _ = tuple(bpy.context.selected_objects)
    selected_after_control = raw_selection(layer)
    assert selected_before_control == before["raw_selected_fixture_only"] and selected_after_control == []
    assert bits(actor.location) == before["unrelated_actor"]["location"]
    assert vars(store) == metadata and store.protection is not None
    return {**record, "dto_sha256": dto_sha, "positive": positive,
            "negative_sync_control": {"after_positive_proof": True, "getter": "bpy.context.selected_objects",
                "before": selected_before_control, "after": selected_after_control, "expected_pending_selection_lost": True,
                "repaired": False, "positive_baseline_rebased": False},
            "completed": True, "source_process_will_exit_before_worker": True}


def worker(bundle: Path, record: dict[str, Any]) -> dict[str, Any]:
    from native_isolated_asset_preview import MAX_BYTES, render_worker, validate_dto

    assert bpy.app.background and {obj.name for obj in bpy.data.objects} == {"Cube", "Camera", "Light"}
    assert len(bpy.data.scenes) == 1
    previous_raw = owned_file(bundle / "writer.json", 512 * 1024)
    previous = json.loads(previous_raw)
    assert previous["completed"] is True and previous["phase"] == "writer"
    assert previous["process_instance"] != record["process_instance"] and previous["process_id"] != record["process_id"]
    for field in ("blender_version", "build_hash", "source_ref", "binary_identity", "script_sha256", "helper_sha256"):
        assert previous[field] == record[field], "Source/program/build changed across process boundary"
    assert previous["positive"]["complete_measured_projection_preserved"] is True
    assert previous["positive"]["task_plan_metadata_remained_armed"] is True
    raw = owned_file(bundle / "geometry.json", MAX_BYTES)
    assert digest(raw) == previous["dto_sha256"]
    dto = validate_dto(json.loads(raw))
    assert canonical(dto) == raw, "DTO encoding changed"
    result = render_worker(bpy, dto, bundle / "preview.png")
    assert result["input_sha256"] == previous["dto_sha256"]
    assert all(-.8 <= v <= .8 for values in result["projected_bounds"].values() for v in values)
    return {**record, "writer_receipt_sha256": digest(previous_raw), "dto_sha256": digest(raw), "render": result,
            "fresh_process_verified": True, "source_process_contacted": False, "source_restore_writes": 0,
            "user_properties_or_ID_references_copied": False,
            "visual_review_performed": False, "completed": True}


def main() -> None:
    phase, bundle, record = owned_profile()
    # Exit authority is acquired only after the checks above, including private UI ownership.
    from blender_artist_sidebar_smoke import owned_process_exit

    status = 1
    try:
        result = writer(bundle, record) if phase == "writer" else worker(bundle, record)
        assert digest(Path(__file__).read_bytes()) == record["script_sha256"]
        assert digest((ROOT / "scripts" / "native_isolated_asset_preview.py").read_bytes()) == record["helper_sha256"]
        receipt = bundle / ("writer.json" if phase == "writer" else "worker.json")
        receipt_sha = freeze(receipt, canonical(result))
        marker = WRITER_MARKER if phase == "writer" else WORKER_MARKER
        print(marker + json.dumps({**record, "completed": True, "receipt": str(receipt), "receipt_sha256": receipt_sha}), flush=True)
        status = 0
    except Exception:
        print("BLENDER_ISOLATED_ASSET_PREVIEW_FAILURE " + traceback.format_exc(), flush=True)
    finally:
        owned_process_exit(status)


if __name__ == "__main__":
    main()
