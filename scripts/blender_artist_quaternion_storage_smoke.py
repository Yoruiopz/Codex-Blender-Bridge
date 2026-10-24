"""Opt-in raw native quaternion-storage research, never a production setter.

The isolated background runner owns this entire disposable process. No bridge
tool is registered or invoked. Requested Float32 storage and the independently
predicted evaluated local matrix are separate, explicitly bounded assertions.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import struct
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
sys.path.insert(0, str(ROOT / "scripts"))

CORE = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
NORM_TOLERANCE = 1e-6
MATRIX_TOLERANCE = 3e-6
MIN_NORMAL = float.fromhex("0x1p-126")


def float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def quaternion_profile(requested: tuple[float, ...]) -> tuple[list[float], dict[str, float]]:
    """Independent provided-input qualification; no native readback or mathutils."""
    assert len(requested) == 4
    assert all(type(value) is float and math.isfinite(value) for value in requested)
    assert all(value == 0. or MIN_NORMAL <= abs(value) <= 1. for value in requested)
    rounded = [float32(value) for value in requested]
    assert all(value == 0. or MIN_NORMAL <= abs(value) <= 1. for value in rounded)
    norms = {"requested_norm": math.sqrt(sum(value * value for value in requested)),
             "float32_norm": math.sqrt(sum(value * value for value in rounded))}
    assert all(abs(value - 1.) <= NORM_TOLERANCE for value in norms.values())
    return rounded, norms


def expected_matrix(quaternion: list[float], location: list[float], scale: list[float]) -> list[list[float]]:
    """Predict local rotation from the independent rounded request, not output.

    Matrix composition normalizes a temporary numeric copy. This never changes
    the requested raw storage or becomes a normalization policy for a tool.
    """
    norm = math.sqrt(sum(value * value for value in quaternion))
    w, x, y, z = (value / norm for value in quaternion)
    rotation = [[1. - 2. * (y*y + z*z), 2. * (x*y - z*w), 2. * (x*z + y*w)],
                [2. * (x*y + z*w), 1. - 2. * (x*x + z*z), 2. * (y*z - x*w)],
                [2. * (x*z - y*w), 2. * (y*z + x*w), 1. - 2. * (x*x + y*y)]]
    return [[*(rotation[row][column] * scale[column] for column in range(3)), location[row]]
            for row in range(3)] + [[0., 0., 0., 1.]]


def matrix_error(expected: list[list[float]], observed: list[list[float]]) -> float:
    assert len(observed) == 4 and all(len(row) == 4 for row in observed)
    assert all(math.isfinite(value) for row in observed for value in row)
    return max(abs(expected[row][column] - observed[row][column]) for row in range(4) for column in range(4))


def callbacks() -> dict[str, list[str]]:
    result = {}
    for name in ("depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post"):
        handlers = list(getattr(bpy.app.handlers, name))
        assert len(handlers) <= 32
        result[name] = [getattr(handler, "__module__", "") + "." + getattr(handler, "__qualname__", "")
                        for handler in handlers]
    return result


def owned_profile() -> tuple[Path, str, dict[str, Any]]:
    """Refuse an unowned invocation before acquiring process-exit authority."""
    cli = {"background": "--background" in sys.argv, "factory_startup": "--factory-startup" in sys.argv,
           "disable_autoexec": "--disable-autoexec" in sys.argv}
    native_background = bool(getattr(bpy.app, "background", False))
    main_thread = threading.current_thread() is threading.main_thread()
    assert native_background and all(cli.values()), "Use the isolated background runner"
    assert main_thread
    process_token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert re.fullmatch(r"[a-f0-9]{32}", process_token), "The isolated runner must own this process"
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    assert len(str(folder).encode("utf-8")) <= 4096
    paths = {}
    for name in ("TEMP", "TMP", "TMPDIR", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        raw = os.environ[name]
        assert len(raw.encode("utf-8")) <= 4096 and not any(ord(character) < 32 for character in raw)
        requested = Path(raw)
        assert requested.is_absolute()
        resolved = requested.resolve(strict=True)
        assert resolved.is_dir() and len(str(resolved).encode("utf-8")) <= 4096
        if name in {"TEMP", "TMP", "TMPDIR"}:
            assert resolved == folder
        else:
            assert resolved.is_relative_to(folder)
        paths[name] = {"requested": raw, "resolved": str(resolved)}
    assert bpy.data.filepath == "", "Never run against an opened project"
    return folder, process_token, {"owned_folder_resolved": str(folder), "paths": paths, "cli": cli,
                                   "native_background": native_background, "main_thread": main_thread}


def main() -> None:
    folder, process_token, profile_attestation = owned_profile()
    from blender_artist_target_verification_smoke import (
        bits,
        channels,
        object_schema,
        stored_context,
        token,
    )
    from native_character_evidence import rest

    scene, layer = bpy.context.scene, bpy.context.scene.view_layers[0]
    assert len(bpy.data.objects) <= 16 and len(bpy.data.scenes) == 1
    context_before_setup = stored_context(scene, layer)
    callback_before = callbacks()

    def triangle(name: str, offset: float) -> Any:
        mesh = bpy.data.meshes.new(name + " Mesh")
        mesh.from_pydata([(offset, 0., 0.), (offset + .75, 0., 0.), (offset, .5, 0.)], [], [(0, 1, 2)])
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        return obj

    work = triangle("Quaternion Storage Working Prop", 0.)
    protected = triangle("Quaternion Storage Protected Peer", 5.)
    work.rotation_mode = "QUATERNION"
    work.location, work.scale = (.125, -.25, .5), (1.25, .75, -1.)
    work.rotation_euler = (.125, -.25, .5)
    work.rotation_axis_angle = (.75, 0., 1., -0.)
    work.rotation_quaternion = (.5, .5, .5, .5)
    work.lock_location, work.lock_scale, work.lock_rotation = (False,) * 3, (False,) * 3, (False,) * 3
    work.lock_rotation_w = work.lock_rotations_4d = False
    layer.update()
    for obj in layer.objects:
        obj.select_set(False, view_layer=layer)
    protected.select_set(True, view_layer=layer)
    layer.objects.active = protected
    layer.update()
    context_before_probe = stored_context(scene, layer)
    assert context_before_probe["active"] == protected.name
    assert not work.select_get(view_layer=layer) and protected.select_get(view_layer=layer)
    assert work.parent is None and work.data.users == 1
    assert work.library is None and work.override_library is None
    assert work.data.library is None and work.data.override_library is None
    assert work.is_editable and work.data.is_editable
    assert work.animation_data is None and work.data.animation_data is None and work.data.shape_keys is None
    assert not work.constraints and not work.modifiers and work.instance_type == "NONE"
    assert work.rigid_body is None and work.rigid_body_constraint is None and work.soft_body is None
    assert not work.particle_systems and (work.field is None or work.field.type == "NONE")
    assert not any(work.lock_rotation) and not work.lock_rotation_w and not work.lock_rotations_4d
    assert tuple(work.delta_location) == (0., 0., 0.) and tuple(work.delta_scale) == (1., 1., 1.)
    assert tuple(work.delta_rotation_euler) == (0., 0., 0.) and tuple(work.delta_rotation_quaternion) == (1., 0., 0., 0.)
    assert all(type(consumer) in (bpy.types.Collection, bpy.types.Scene)
               for consumer in bpy.data.user_map(subset={work}).get(work, ()))
    schema = object_schema(work)
    assert schema["exact_native_object_type"] and schema["canonical_pointer"] == schema["actual_pointer"]
    for field in CORE:
        descriptor = schema["properties"][field]
        assert descriptor is not None and not descriptor["is_runtime"] and not descriptor["is_readonly"]
        assert not descriptor["is_registered"] and not descriptor["is_registered_optional"]
    descriptor = schema["properties"]["rotation_quaternion"]
    assert descriptor["type"] == "FLOAT" and descriptor["array_length"] == 4 and descriptor["is_array"]

    def projection() -> dict[str, Any]:
        objects = sorted(bpy.data.objects, key=lambda obj: obj.name)
        assert len(objects) <= 16
        users = bpy.data.user_map(subset={work, work.data, protected, protected.data})
        assert all(len(consumers) <= 16 for consumers in users.values())
        return {"context": stored_context(scene, layer), "filepath": bpy.data.filepath,
                "working_mesh": rest(work), "protected_mesh": rest(protected),
                "objects": [{"object": token(obj), "data": token(obj.data), "mode": obj.mode,
                    "parent": token(obj.parent), "children": sorted(child.name for child in obj.children),
                    "collections": sorted(collection.name for collection in obj.users_collection),
                    "scene_owners": sorted(owner.name for owner in obj.users_scene),
                    "visibility": [obj.hide_viewport, obj.hide_render, obj.hide_select],
                    "rotation_locks": [list(obj.lock_rotation), obj.lock_rotation_w, obj.lock_rotations_4d],
                    "other_locks": [list(obj.lock_location), list(obj.lock_scale)],
                    "delta_channels": {field: [struct.pack("<f", value).hex() for value in getattr(obj, field)]
                        for field in ("delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")},
                    "parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
                    "component_identities": [[component.name, component.as_pointer()] for component in (*obj.modifiers, *obj.constraints)],
                    "animation_absent": obj.animation_data is None,
                    "data_users": None if obj.data is None else obj.data.users,
                    "core_bits": {key: value for key, value in bits(channels(obj)).items()
                                  if obj != work or key != "rotation_quaternion"}}
                    for obj in objects],
                "native_consumers": [{"owner": token(owner), "consumers": sorted(
                    [{"identity": token(consumer), "references": consumer.user_of_id(owner)} for consumer in consumers],
                    key=lambda value: (value["identity"]["name"], value["identity"]["pointer"]))}
                    for owner, consumers in sorted(users.items(), key=lambda item: item[0].name)],
                "callbacks": callbacks(), "scene": token(scene), "view_layer": {"name": layer.name, "pointer": layer.as_pointer()}}

    preserved = projection()
    root_half = math.sqrt(.5)
    general_norm = math.sqrt(.1**2 + .2**2 + .3**2 + .4**2)
    cases = (("identity_signed_zero", (1., -0., 0., -0.)),
             ("quarter_x", (root_half, root_half, -0., 0.)),
             ("quarter_y", (root_half, 0., root_half, -0.)),
             ("quarter_z", (root_half, -0., 0., root_half)),
             ("negative_quarter_y", (-root_half, -0., -root_half, 0.)),
             ("general_exact_unit", (.5, -.5, .5, -.5)),
             ("general_stdlib_normalized_seed", tuple(value / general_norm for value in (.1, .2, .3, .4))))
    path = folder / "artist-quaternion-storage-evidence.json"
    assert not path.exists()
    sources = (Path(__file__), ROOT / "scripts/blender_artist_target_verification_smoke.py",
               ROOT / "scripts/native_character_evidence.py", ROOT / "scripts/blender_artist_sidebar_smoke.py")
    source_paths = {str(source.relative_to(ROOT)): str(source.resolve(strict=True)) for source in sources}
    assert all(len(value.encode("utf-8")) <= 4096 for value in source_paths.values())
    data = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "process_id": os.getpid(), "process_instance": process_token, "main_thread_only": True,
            "profile": "owned_unlocked_static_single_user_mesh_existing_quaternion",
            "schema": schema, "context_before_setup": context_before_setup,
            "context_before_probe": context_before_probe,
            "profile_attestation": profile_attestation,
            "preserved_projection": preserved, "callback_inventory_before": callback_before,
            "norm_tolerance": NORM_TOLERANCE, "evaluated_matrix_absolute_tolerance": MATRIX_TOLERANCE,
            "expected_matrix_basis": "stdlib WXYZ rotation of independently Float32-rounded input, temporary numeric normalization, then original local scale/location",
            "raw_storage_basis": "independent stdlib Float32 assignment bits; no normalization/sign canonicalization",
            "authority": {"typed_bridge_calls": 0, "permission_provider_calls": 0, "bridge_registered": False,
                          "mode": "fixture-owned raw native API; production permissions not exercised"},
            "source_paths": source_paths,
            "source_sha256": {str(source.relative_to(ROOT)): hashlib.sha256(source.read_bytes()).hexdigest() for source in sources},
            "cases": [], "raw_probe_setter_calls": 0, "completed": False,
            "limits": {"research_only": True, "public_quaternion_argument_available": False,
                       "artist_goal_verified": False, "protected_workflow_verified": False,
                       "whole_native_state_preservation_verified": False, "undo_or_recovery_verified": False,
                       "project_saved": False, "fixture_native_save": False, "capture_performed": False,
                       "windows_qualified": False, "release_readiness": "NOT_ASSESSED"},
            "termination": "fixture-only owned os._exit after evidence/stdio flush; no native quit/save callbacks"}

    def flush() -> None:
        path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")

    try:
        for name, requested in cases:
            before = channels(work)
            expected, norms = quaternion_profile(requested)
            assert all(descriptor["hard_min"] <= value <= descriptor["hard_max"] for value in (*requested, *expected))
            desired = copy.deepcopy(before)
            desired["rotation_quaternion"] = expected
            predicted_bits = bits(desired)
            predicted_matrix = expected_matrix(expected, before["location"], before["scale"])
            row = {"name": name, "requested_wxyz": requested, "norms": norms,
                   "before_channels": before, "expected_channels": desired, "expected_bits": predicted_bits,
                   "expected_evaluated_local_matrix": predicted_matrix, "context_before": stored_context(scene, layer)}
            if name == "general_stdlib_normalized_seed":
                row["provided_input_preparation"] = {"raw_seed_wxyz": [.1, .2, .3, .4],
                    "stdlib_normalizer": general_norm, "normalized_requested_wxyz": requested,
                    "independently_float32_rounded_wxyz": expected,
                    "scope": "Fixture prepares a unit request before native entry; no RNA normalization claim"}
            data["cases"].append(row)
            flush()  # Retain the independent prediction before the native setter.
            assert threading.current_thread() is threading.main_thread()
            work.rotation_quaternion = requested
            data["raw_probe_setter_calls"] += 1
            row["immediate_raw_channels"] = channels(work)
            row["immediate_raw_bits"] = bits(row["immediate_raw_channels"])
            layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            observed_matrix = [list(vector) for vector in work.evaluated_get(graph).matrix_local]
            row["evaluated_local_matrix"] = observed_matrix
            row["evaluated_matrix_maximum_absolute_error"] = matrix_error(predicted_matrix, observed_matrix)
            row["after_evaluation_raw_channels"] = channels(work)
            row["after_evaluation_raw_bits"] = bits(row["after_evaluation_raw_channels"])
            row["context_after"] = stored_context(scene, layer)
            row["preserved_projection_after"] = projection()
            row["preserved_projection_equal"] = row["preserved_projection_after"] == preserved
            assert row["immediate_raw_bits"] == predicted_bits
            assert row["after_evaluation_raw_bits"] == predicted_bits
            assert row["evaluated_matrix_maximum_absolute_error"] <= MATRIX_TOLERANCE
            assert row["context_before"] == row["context_after"] and row["preserved_projection_equal"]
            flush()
        positive, negative = (next(row for row in data["cases"] if row["name"] == name)
                              for name in ("quarter_y", "negative_quarter_y"))
        data["q_and_negative_q_matrix_error"] = matrix_error(positive["evaluated_local_matrix"], negative["evaluated_local_matrix"])
        assert data["q_and_negative_q_matrix_error"] <= MATRIX_TOLERANCE
        assert positive["expected_bits"]["rotation_quaternion"] != negative["expected_bits"]["rotation_quaternion"]
        data["context_after"] = stored_context(scene, layer)
        data["callback_inventory_after"] = callbacks()
        data["final_preserved_projection"] = projection()
        assert data["context_after"] == context_before_probe and data["callback_inventory_after"] == callback_before
        assert data["final_preserved_projection"] == preserved
        data["completed"] = True
        flush()
        print("BLENDER_ARTIST_QUATERNION_STORAGE_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "build_hash": data["build_hash"],
            "evidence_file": str(path), "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "process_instance": process_token, "raw_probe_setter_calls": data["raw_probe_setter_calls"],
            "all_six_raw_core_channel_bits_verified": True, "all_declared_preserved_projections_equal": True,
            "separate_evaluated_local_matrix_oracle_verified": True, **data["limits"]}, allow_nan=False), flush=True)
    except BaseException as error:
        data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        flush()
        raise


if __name__ == "__main__":
    owned_profile()
    from blender_artist_sidebar_smoke import owned_process_exit

    exit_code = 1
    try:
        main()
        exit_code = 0
    except BaseException:
        traceback.print_exc()
    finally:
        owned_process_exit(exit_code)
