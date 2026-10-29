"""Opt-in GLB stage/publication evidence through genuine canonical Runtime TCP.

Import is cold. The socket worker handles ordinary JSON only. All labeled raw
setup/fault/observation work belongs to the owned factory fixture main thread.
No private constructor call, manual job tick or synthetic stop can qualify TCP.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import queue
import re
import socket
import stat
import sys
import threading
import time
import traceback
from pathlib import Path

SCHEMA = "glb_stage_runtime_stage_publish_v1"
PROFILE = "GLB_RUNTIME_STAGE_PUBLISH_V1"
MARKER = "BLENDER_GLB_STAGE_RUNTIME_OK "
FILENAME = "glb-stage-runtime-evidence.json"
MAX_EVIDENCE = 8 * 1024**2
MAX_LOG = 4 * 1024**2
SCENARIOS = (
    "TCP_SUCCESS_STAGE", "TCP_SUCCESS_PUBLISH", "PERMISSION_AND_TOOLSET",
    "SOURCE_AND_NAME_REFUSALS", "NORMAL_CONSENT", "START_HANDOFF_AND_DISCONNECT",
    "GENUINE_CANCEL_AFTER_UV", "PERMISSION_REVOCATION", "OWNED_MANUAL_DRIFT",
    "DESTINATION_DRIFT_AND_UNITS", "STOP_AT_NATIVE_RETURN", "PARTIAL_UNKNOWN_IDS",
    "PUBLICATION_STOP_OR_FAILURE", "UNDO_LOAD_RUNTIME_INVALIDATION",
    "SHARED_SLOT_REENTRANCY", "REAL_DEFERRED_PRESERVATION", "REPORT_COUNTERMODELS",
)
OBSERVATIONS = (("immediate", 0.), ("timer_0_1", .1), ("timer_0_3", .3), ("timer_0_5", .5))
LOSSES = ["VERTEX_SPLITS", "AXIS_UNIT_CONVERSION", "PBR_MATERIAL_RECONSTRUCTION",
          "UV_ORIGIN_CONVERSION", "NORMAL_STORAGE_QUANTIZATION", "MISSING_NORMALS_USE_GEOMETRIC_AUTO"]
CREATE_GRANTS = ("INSPECT_SCENE", "ACCESS_EXTERNAL_FILES", "EDIT_SCENE", "TRANSFORM_OBJECTS", "EDIT_MESH", "EDIT_MATERIALS")
PUBLISH_GRANTS = tuple(value for value in CREATE_GRANTS if value != "ACCESS_EXTERNAL_FILES")
SOURCES = (
    'scripts/blender_glb_stage_runtime_smoke.py',
    'scripts/blender_glb_stage_smoke.py',
    'scripts/run_blender_checks.py',
    'scripts/blender_artist_sidebar_smoke.py',
    'addon/blender_codex_bridge/__init__.py',
    'addon/blender_codex_bridge/artist_step_evidence.py',
    'addon/blender_codex_bridge/artist_target_intent.py',
    'addon/blender_codex_bridge/asset_fbx_preflight.py',
    'addon/blender_codex_bridge/asset_glb_import_plan.py',
    'addon/blender_codex_bridge/asset_glb_preflight.py',
    'addon/blender_codex_bridge/asset_import_source.py',
    'addon/blender_codex_bridge/checkpoint_completion.py',
    'addon/blender_codex_bridge/checkpoints.py',
    'addon/blender_codex_bridge/cinematic_variants.py',
    'addon/blender_codex_bridge/command_queue.py',
    'addon/blender_codex_bridge/constants.py',
    'addon/blender_codex_bridge/current_pixels_contract.py',
    'addon/blender_codex_bridge/current_pixels_files.py',
    'addon/blender_codex_bridge/entry_effects.py',
    'addon/blender_codex_bridge/errors.py',
    'addon/blender_codex_bridge/executor.py',
    'addon/blender_codex_bridge/geometry_preview_dto.py',
    'addon/blender_codex_bridge/geometry_preview_jobs.py',
    'addon/blender_codex_bridge/geometry_preview_process.py',
    'addon/blender_codex_bridge/geometry_preview_source.py',
    'addon/blender_codex_bridge/geometry_preview_worker.py',
    'addon/blender_codex_bridge/glb_stage_driver.py',
    'addon/blender_codex_bridge/glb_stage_jobs.py',
    'addon/blender_codex_bridge/glb_stage_profile.py',
    'addon/blender_codex_bridge/glb_stage_protected_mesh.py',
    'addon/blender_codex_bridge/glb_stage_runtime.py',
    'addon/blender_codex_bridge/glb_stage_source.py',
    'addon/blender_codex_bridge/glb_stage_state.py',
    'addon/blender_codex_bridge/image_files.py',
    'addon/blender_codex_bridge/image_streams.py',
    'addon/blender_codex_bridge/job_controller.py',
    'addon/blender_codex_bridge/jobs.py',
    'addon/blender_codex_bridge/mesh_geometry.py',
    'addon/blender_codex_bridge/mesh_inspector.py',
    'addon/blender_codex_bridge/native_save_files.py',
    'addon/blender_codex_bridge/native_save_jobs.py',
    'addon/blender_codex_bridge/native_save_policy.py',
    'addon/blender_codex_bridge/native_save_process.py',
    'addon/blender_codex_bridge/native_save_profile.py',
    'addon/blender_codex_bridge/native_save_reader.py',
    'addon/blender_codex_bridge/native_save_source.py',
    'addon/blender_codex_bridge/operation_lease.py',
    'addon/blender_codex_bridge/permissions.py',
    'addon/blender_codex_bridge/pixel_codecs.py',
    'addon/blender_codex_bridge/preferences.py',
    'addon/blender_codex_bridge/protocol.py',
    'addon/blender_codex_bridge/render_png.py',
    'addon/blender_codex_bridge/render_scope_profile.py',
    'addon/blender_codex_bridge/render_staging.py',
    'addon/blender_codex_bridge/request_lifecycle.py',
    'addon/blender_codex_bridge/runtime.py',
    'addon/blender_codex_bridge/scene_evidence.py',
    'addon/blender_codex_bridge/scene_inspector.py',
    'addon/blender_codex_bridge/scene_job_authority.py',
    'addon/blender_codex_bridge/scene_job_effects.py',
    'addon/blender_codex_bridge/scene_job_evidence.py',
    'addon/blender_codex_bridge/scene_job_reservations.py',
    'addon/blender_codex_bridge/scene_jobs.py',
    'addon/blender_codex_bridge/selection.py',
    'addon/blender_codex_bridge/serialization.py',
    'addon/blender_codex_bridge/server.py',
    'addon/blender_codex_bridge/state.py',
    'addon/blender_codex_bridge/surface_geometry.py',
    'addon/blender_codex_bridge/task_plans.py',
    'addon/blender_codex_bridge/texture_staging.py',
    'addon/blender_codex_bridge/texture_verification.py',
    'addon/blender_codex_bridge/tool_registry.py',
    'addon/blender_codex_bridge/tools/__init__.py',
    'addon/blender_codex_bridge/tools/_animation_mutation.py',
    'addon/blender_codex_bridge/tools/_animation_scope.py',
    'addon/blender_codex_bridge/tools/_artist_checkpoint_admission.py',
    'addon/blender_codex_bridge/tools/_artist_role_witness.py',
    'addon/blender_codex_bridge/tools/_artist_scope_profile.py',
    'addon/blender_codex_bridge/tools/_curve_edit_intent.py',
    'addon/blender_codex_bridge/tools/_curve_point_native.py',
    'addon/blender_codex_bridge/tools/_legacy_object_drivers.py',
    'addon/blender_codex_bridge/tools/_mesh_safety.py',
    'addon/blender_codex_bridge/tools/_nla_controls.py',
    'addon/blender_codex_bridge/tools/_object_rna_mutation.py',
    'addon/blender_codex_bridge/tools/_object_safety.py',
    'addon/blender_codex_bridge/tools/_object_scope.py',
    'addon/blender_codex_bridge/tools/_render_boundary.py',
    'addon/blender_codex_bridge/tools/_render_checkpoint.py',
    'addon/blender_codex_bridge/tools/_rig_binding.py',
    'addon/blender_codex_bridge/tools/_rigging_edit.py',
    'addon/blender_codex_bridge/tools/_rigid_authored_scope.py',
    'addon/blender_codex_bridge/tools/_rigid_body_scope.py',
    'addon/blender_codex_bridge/tools/_rigid_evaluation_job.py',
    'addon/blender_codex_bridge/tools/_rigid_evaluation_scope.py',
    'addon/blender_codex_bridge/tools/_rigid_scene_consumers.py',
    'addon/blender_codex_bridge/tools/_rigid_snapshot_scope.py',
    'addon/blender_codex_bridge/tools/_rna.py',
    'addon/blender_codex_bridge/tools/_scene_checkpoint_admission.py',
    'addon/blender_codex_bridge/tools/_scene_checkpoint_roles.py',
    'addon/blender_codex_bridge/tools/_scene_collection_scope.py',
    'addon/blender_codex_bridge/tools/_scene_edit_profile.py',
    'addon/blender_codex_bridge/tools/_scene_evaluation_scope.py',
    'addon/blender_codex_bridge/tools/_scene_mutation.py',
    'addon/blender_codex_bridge/tools/_uv_selection.py',
    'addon/blender_codex_bridge/tools/animation.py',
    'addon/blender_codex_bridge/tools/animation_curve_inspection.py',
    'addon/blender_codex_bridge/tools/animation_curve_sampling.py',
    'addon/blender_codex_bridge/tools/animation_curves.py',
    'addon/blender_codex_bridge/tools/animation_layers.py',
    'addon/blender_codex_bridge/tools/animation_lifecycle.py',
    'addon/blender_codex_bridge/tools/artist_loop.py',
    'addon/blender_codex_bridge/tools/artist_target_verify.py',
    'addon/blender_codex_bridge/tools/asset_delivery.py',
    'addon/blender_codex_bridge/tools/asset_import.py',
    'addon/blender_codex_bridge/tools/batch.py',
    'addon/blender_codex_bridge/tools/brush_tiles.py',
    'addon/blender_codex_bridge/tools/compositor.py',
    'addon/blender_codex_bridge/tools/constraints.py',
    'addon/blender_codex_bridge/tools/core.py',
    'addon/blender_codex_bridge/tools/deformation.py',
    'addon/blender_codex_bridge/tools/face_attributes.py',
    'addon/blender_codex_bridge/tools/geometry_node_groups.py',
    'addon/blender_codex_bridge/tools/geometry_nodes.py',
    'addon/blender_codex_bridge/tools/geometry_preview.py',
    'addon/blender_codex_bridge/tools/geometry_zone_lifecycle.py',
    'addon/blender_codex_bridge/tools/glb_stage.py',
    'addon/blender_codex_bridge/tools/image_delivery.py',
    'addon/blender_codex_bridge/tools/image_masks.py',
    'addon/blender_codex_bridge/tools/image_paint.py',
    'addon/blender_codex_bridge/tools/image_portability.py',
    'addon/blender_codex_bridge/tools/image_recovery.py',
    'addon/blender_codex_bridge/tools/image_recovery_jobs.py',
    'addon/blender_codex_bridge/tools/image_revisions.py',
    'addon/blender_codex_bridge/tools/image_surface_paint.py',
    'addon/blender_codex_bridge/tools/images.py',
    'addon/blender_codex_bridge/tools/interaction.py',
    'addon/blender_codex_bridge/tools/layout.py',
    'addon/blender_codex_bridge/tools/material_scope.py',
    'addon/blender_codex_bridge/tools/materials.py',
    'addon/blender_codex_bridge/tools/mesh.py',
    'addon/blender_codex_bridge/tools/mesh_analysis.py',
    'addon/blender_codex_bridge/tools/mesh_chains.py',
    'addon/blender_codex_bridge/tools/mesh_loops.py',
    'addon/blender_codex_bridge/tools/mesh_repair.py',
    'addon/blender_codex_bridge/tools/mesh_slide.py',
    'addon/blender_codex_bridge/tools/mesh_surface.py',
    'addon/blender_codex_bridge/tools/modifiers.py',
    'addon/blender_codex_bridge/tools/native_save.py',
    'addon/blender_codex_bridge/tools/nla_lifecycle.py',
    'addon/blender_codex_bridge/tools/nodes.py',
    'addon/blender_codex_bridge/tools/objects.py',
    'addon/blender_codex_bridge/tools/paint_jobs.py',
    'addon/blender_codex_bridge/tools/pixel_brush.py',
    'addon/blender_codex_bridge/tools/pixel_mask.py',
    'addon/blender_codex_bridge/tools/python_exec.py',
    'addon/blender_codex_bridge/tools/render.py',
    'addon/blender_codex_bridge/tools/rig_drivers.py',
    'addon/blender_codex_bridge/tools/rig_ik.py',
    'addon/blender_codex_bridge/tools/rigging.py',
    'addon/blender_codex_bridge/tools/rigid_body.py',
    'addon/blender_codex_bridge/tools/rigid_body_jobs.py',
    'addon/blender_codex_bridge/tools/scene_edit.py',
    'addon/blender_codex_bridge/tools/scene_variants.py',
    'addon/blender_codex_bridge/tools/sculpt_masks.py',
    'addon/blender_codex_bridge/tools/shader_groups.py',
    'addon/blender_codex_bridge/tools/shader_interface.py',
    'addon/blender_codex_bridge/tools/shader_scope.py',
    'addon/blender_codex_bridge/tools/shader_settings.py',
    'addon/blender_codex_bridge/tools/shader_state.py',
    'addon/blender_codex_bridge/tools/simulation.py',
    'addon/blender_codex_bridge/tools/surface_brushes.py',
    'addon/blender_codex_bridge/tools/task_plan.py',
    'addon/blender_codex_bridge/tools/transforms.py',
    'addon/blender_codex_bridge/tools/uv.py',
    'addon/blender_codex_bridge/tools/uv_analysis.py',
    'addon/blender_codex_bridge/tools/uv_capture.py',
    'addon/blender_codex_bridge/tools/uv_edit.py',
    'addon/blender_codex_bridge/tools/uv_layers.py',
    'addon/blender_codex_bridge/tools/uv_refine.py',
    'addon/blender_codex_bridge/tools/weight_brushes.py',
    'addon/blender_codex_bridge/tools/weights.py',
    'addon/blender_codex_bridge/transport.py',
    'addon/blender_codex_bridge/ui.py',
    'addon/blender_codex_bridge/undo_window.py',
    'addon/blender_codex_bridge/utils.py',
    'addon/blender_codex_bridge/uv_edit_guard.py',
    'addon/blender_codex_bridge/uv_edit_intent.py',
    'addon/blender_codex_bridge/uv_geometry.py',
    'addon/blender_codex_bridge/viewport.py',
    'addon/blender_codex_bridge/weight_edit_guard.py',
    'addon/blender_codex_bridge/weight_edit_plan.py',
)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("GLB_RUNTIME_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("GLB_RUNTIME_NONFINITE_JSON")


def decode(raw):
    assert type(raw) is bytes and 0 < len(raw) <= MAX_EVIDENCE
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        assert depth <= 48, "GLB_RUNTIME_JSON_DEPTH"
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        else:
            assert item is None or type(item) in (str, int, float, bool)
            assert type(item) is not float or math.isfinite(item)
    assert type(value) is dict, "GLB_RUNTIME_JSON_OBJECT"
    return unpack_proof(value) if value.get("encoding") == "GLB_RUNTIME_INTERNED_JSON_V1" else value


def encode(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    assert 0 < len(raw) <= MAX_EVIDENCE
    return raw


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def bounded_file(path, maximum=MAX_EVIDENCE):
    """No-follow/nonblocking ordinary descriptor read with replacement witnesses."""
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum
    def identity(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    chunks, count = [], 0
    try:
        assert identity(os.fstat(fd)) == identity(before)
        while True:
            chunk = os.read(fd, min(65536, maximum + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            assert count <= maximum
            chunks.append(chunk)
        assert count == before.st_size and identity(os.fstat(fd)) == identity(before)
        assert identity(path.lstat()) == identity(before)
    finally:
        os.close(fd)
    return b"".join(chunks)


def pack_proof(value):
    """Lossless immutable subtree sharing; wire requests still use plain JSON.

    Lists use 32-way persistent chunks, so retained monotonic entry prefixes do
    not repeat complete arrays. No field, response, component or request is cut.
    """
    table = {}
    def node(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        key = hashlib.sha256(raw).hexdigest()
        if key not in table:
            assert len(table) < 65536, "GLB_RUNTIME_SHARED_TABLE_BUDGET"
            table[key] = value
        return {"ref": key}
    def chunks(values):
        level = [node({"kind": "items", "values": values[offset:offset+32]}) for offset in range(0, len(values), 32)]
        if not level:
            level = [node({"kind": "items", "values": []})]
        while len(level) > 1:
            level = [node({"kind": "branch", "children": level[offset:offset+32]}) for offset in range(0, len(level), 32)]
        return level[0]
    def visit(item, depth):
        assert depth <= 48
        if type(item) is dict:
            assert all(type(key) is str for key in item)
            return node({"kind": "object", "pairs": [[key, visit(child, depth+1)] for key, child in sorted(item.items())]})
        if type(item) is list:
            return node({"kind": "array", "root": chunks([visit(child, depth+1) for child in item])})
        assert item is None or type(item) in (str, bool, int, float)
        assert type(item) is not float or math.isfinite(item)
        return item
    root = visit(value, 0)
    return {"encoding": "GLB_RUNTIME_INTERNED_JSON_V1", "root": root, "table": table}


def unpack_proof(envelope):
    assert set(envelope) == {"encoding", "root", "table"}
    table = envelope["table"]
    assert type(table) is dict and 0 < len(table) <= 65536
    for key, value in table.items():
        assert re.fullmatch(r"[a-f0-9]{64}", key)
        assert type(value) is dict
        assert hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest() == key
    # Summarize the logical graph before materializing it. Memoized aliases
    # still contribute their entire cost and height at every reference.
    summaries, measuring = {}, set()
    def measure(item, depth, sequence=False):
        assert depth <= 48, "GLB_RUNTIME_SHARED_DEPTH"
        if type(item) is not dict:
            assert not sequence and (item is None or type(item) in (str, int, float, bool))
            assert type(item) is not float or math.isfinite(item)
            return 1, 0
        assert set(item) == {"ref"} and type(item["ref"]) is str
        key = item["ref"]
        assert key in table and key not in measuring
        cache_key = (sequence, key)
        if cache_key not in summaries:
            measuring.add(key)
            value = table[key]
            kind = value.get("kind")
            child_sequence = False
            if sequence and kind == "items":
                assert set(value) == {"kind", "values"} and type(value["values"]) is list and len(value["values"]) <= 32
                children = value["values"]
            elif sequence:
                assert kind == "branch" and set(value) == {"kind", "children"}
                assert type(value["children"]) is list and 1 <= len(value["children"]) <= 32
                children, child_sequence = value["children"], True
            elif kind == "object":
                assert set(value) == {"kind", "pairs"} and type(value["pairs"]) is list
                names, children = set(), []
                for pair in value["pairs"]:
                    assert type(pair) is list and len(pair) == 2 and type(pair[0]) is str and pair[0] not in names
                    names.add(pair[0])
                    children.append(pair[1])
            else:
                assert kind == "array" and set(value) == {"kind", "root"}
                children, child_sequence = [value["root"]], True
            cost, height = 1, 0
            for child in children:
                child_cost, child_height = measure(child, depth+1, child_sequence)
                cost = min(2_000_001, cost+child_cost)
                height = max(height, 1+child_height)
            measuring.remove(key)
            summaries[cache_key] = cost, height
        cost, height = summaries[cache_key]
        assert cost <= 2_000_000, "GLB_RUNTIME_SHARED_EXPANSION_BUDGET"
        assert depth+height <= 48, "GLB_RUNTIME_SHARED_DEPTH"
        return cost, height
    measure(envelope["root"], 0)
    memo, active, used = {}, set(), [0]
    def reference(ref, depth):
        assert type(ref) is dict and set(ref) == {"ref"}
        key = ref["ref"]
        assert key in table and key not in active and depth <= 48
        if key in memo:
            return memo[key]
        active.add(key)
        value = table[key]
        kind = value.get("kind")
        if kind == "object":
            assert set(value) == {"kind", "pairs"} and type(value["pairs"]) is list
            result = {}
            for pair in value["pairs"]:
                assert type(pair) is list and len(pair) == 2 and type(pair[0]) is str and pair[0] not in result
                result[pair[0]] = visit(pair[1], depth+1)
        elif kind == "array":
            assert set(value) == {"kind", "root"}
            result = sequence(value["root"], depth+1)
        else:
            raise ValueError("GLB_RUNTIME_SHARED_NODE_KIND")
        active.remove(key)
        memo[key] = result
        return result
    def sequence(ref, depth):
        assert type(ref) is dict and set(ref) == {"ref"} and depth <= 48
        key = ref["ref"]
        assert key in table and key not in active
        active.add(key)
        value = table[key]
        if value.get("kind") == "items":
            assert set(value) == {"kind", "values"} and type(value["values"]) is list and len(value["values"]) <= 32
            result = [visit(child, depth+1) for child in value["values"]]
        else:
            assert value.get("kind") == "branch" and set(value) == {"kind", "children"}
            assert type(value["children"]) is list and 1 <= len(value["children"]) <= 32
            result = [child for ref in value["children"] for child in sequence(ref, depth+1)]
        active.remove(key)
        return result
    def visit(item, depth):
        used[0] += 1
        assert used[0] <= 2_000_000 and depth <= 48, "GLB_RUNTIME_SHARED_EXPANSION_BUDGET"
        if type(item) is dict:
            return reference(item, depth)
        assert item is None or type(item) in (str, int, float, bool)
        assert type(item) is not float or math.isfinite(item)
        return item
    result = visit(envelope["root"], 0)
    assert type(result) is dict
    return result


def source_hashes(root):
    return {name: hashlib.sha256(bounded_file(root / name, 512 * 1024)).hexdigest() for name in SOURCES}


def finite(value, minimum=0.):
    assert type(value) in (int, float) and math.isfinite(value) and value >= minimum
    return value


def native_journal(value, *, stopped=False):
    assert type(value) is dict
    entries = value["native_entries"]
    assert type(entries) is list and len(entries) <= 2048
    for index, row in enumerate(entries):
        assert type(row) is dict and row["index"] == index
        assert type(row["index"]) is int and type(row["operation"]) is str and row["operation"]
        assert type(row["role"]) is str and row["role"] and row["entered"] is True
        assert type(row["entry"]) is str and row["entry"]
        assert type(row["returned"]) is bool and type(row["post_return_stop_checked"]) is bool
        finite(row["seconds"])
        if row["returned"] and not (stopped and index == len(entries) - 1):
            assert row["post_return_stop_checked"] is True
        else:
            assert index == len(entries) - 1
    assert type(value["owned_reference_roles"]) is list
    assert len(set(value["owned_reference_roles"])) == len(value["owned_reference_roles"])
    assert type(value["footprint_complete"]) is bool
    if stopped:
        assert value["stop_native_entry_count"] == len(entries)
        assert type(value["stop_native_entry_count"]) is int
        assert value["entries_after_stop"] == []
    return entries


def snapshot(value):
    assert type(value) is dict and set(value) == {"protected", "context", "scene_edges", "owned"}
    protected = value["protected"]
    assert type(protected) is dict and set(protected) == {"objects", "meshes", "materials", "armatures", "actions", "scenes", "images", "cameras", "lights", "worlds", "collections"}
    assert all(type(rows) is list and rows for rows in protected.values())
    fields = {"objects": {"identity", "type", "data_uid", "parent_uid", "channels", "rotation_mode", "parent_inverse", "basis", "local", "world", "children", "collections"},
              "meshes": {"identity", "coordinates", "corners", "faces", "edges", "materials", "attributes"},
              "materials": {"identity", "color", "backface", "use_nodes", "tree"},
              "armatures": {"identity", "bones"}, "actions": {"identity", "slots", "layers"},
              "scenes": {"identity", "unit_settings", "frame", "world_uid", "camera_uid"}, "images": {"identity", "source", "type", "has_data"},
              "cameras": {"identity", "type", "lens"}, "lights": {"identity", "type", "energy"},
              "worlds": {"identity", "color", "use_nodes", "tree"}, "collections": {"identity", "children", "objects"}}
    for family, rows in protected.items():
        for row in rows:
            assert type(row) is dict and set(row) >= fields[family]
            assert type(row["identity"]) is dict and type(row["identity"]["uid"]) is int and row["identity"]["uid"] > 0
    for row in protected["objects"]:
        from scripts.blender_glb_stage_smoke import CHANNELS
        assert set(row["channels"]) == set(CHANNELS)
    for row in protected["meshes"]:
        assert type(row["attributes"]) is dict and row["attributes"]

    assert type(value["context"]) is dict and set(value["context"]) >= {"scene", "view_layer", "active", "selected", "mode", "areas"}
    assert type(value["scene_edges"]) is list and type(value["owned"]) is dict
    return value


def logical_snapshot(value):
    """Keep authored bits exact; retain derived matrices in the raw snapshot.

    matrix/local/world are native observed caches, not the mathematical world
    oracle. Parent inverse, basis, all authored channels and every data/role
    remain in the exact comparison. No authored delta is normalized away.
    """
    result = copy.deepcopy(value)
    objects = [*result["protected"]["objects"],
               *(row for role, row in result["owned"].items() if role.startswith("object:"))]
    for row in objects:
        for field in ("matrix", "local", "world"):
            row.pop(field, None)
        for bone in row.get("pose_bones", []):
            bone.pop("matrix", None)
    return result


def exact_publication_delta(before, after, edge, object_uids):
    """Permit only the fixed new-owned closure under the one authored edge."""
    expected = copy.deepcopy(before)
    expected["scene_edges"] = sorted([*before["scene_edges"], edge])
    for scene in expected["protected"]["scenes"]:
        if scene["identity"]["uid"] == edge[0]:
            scene["root_children"] = sorted([*scene.get("root_children", []), edge[1]])
            for layer in scene.get("view_layers", []):
                layer["objects"] = sorted([*layer["objects"], *object_uids])
    expected["owned"] = after["owned"]
    assert logical_snapshot(expected) == logical_snapshot(after), "Publication changed logical data beyond its exact fixed closure"


def read_effects(value, version, *, runtime=True, complete=True, mesh_profile=None):
    """Validate declared native read attempts without asserting cache passivity."""
    assert type(value) is dict
    assert value["scope"] == "LOGICAL_AUTHORED_MESH_VALUES_WITH_DECLARED_PHYSICAL_READ_EFFECTS"
    assert value["runtime_gate_bound"] is runtime and value["native_qualified"] is False
    assert value["hidden_layout_or_cache_passivity_qualified"] is False
    assert value["SINGLE_conversion_authorized"] is False
    assert value["empirical_pre_COW_value_hash_observed"] is False
    assert value["arbitrary_NaN_or_padding_bit_preservation_qualified"] is False
    assert value["copy_evidence"] == "SOURCE_EQUIVALENT_TYPED_LOGICAL_COPY_AND_COMPLETE_POSTREADBACK"
    cells = value["read_effects"]
    assert type(cells) is list and len(cells) <= 4096
    if mesh_profile is not None:
        assert runtime is False and type(mesh_profile) is dict and set(mesh_profile) == {"identity", "counts", "attributes"}
        identity, counts, headers = mesh_profile["identity"], mesh_profile["counts"], mesh_profile["attributes"]
        assert type(identity) is dict and type(identity["uid"]) is int and identity["uid"] > 0
        assert type(identity["pointer"]) is int and identity["pointer"] > 0 and type(identity["name"]) is str and identity["name"]
        assert type(counts) is dict and set(counts) == {"vertices", "edges", "loops", "polygons"}
        assert all(type(count) is int and 0 <= count <= 131072 for count in counts.values())
        assert type(headers) is list and len(headers) <= 64
        by_name = {}
        domains = {"POINT": "vertices", "EDGE": "edges", "CORNER": "loops", "FACE": "polygons"}
        for header in headers:
            assert type(header) is dict and type(header["name"]) is str and header["name"] and header["name"] not in by_name
            assert header["domain"] in domains and header["data_type"] in {"FLOAT", "FLOAT_VECTOR", "FLOAT2", "INT", "INT32_2D", "INT16_2D", "BOOLEAN"}
            assert header["storage"] in {"ARRAY", "LEGACY_ARRAY"} and header["supported"] is True
            assert type(header["count"]) is int and header["count"] == counts[domains[header["domain"]]]
            assert type(header["schema_sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", header["schema_sha256"])
            assert type(header["native_class"]) is str and type(header["value_class"]) is str
            by_name[header["name"]] = header
        if not cells:
            assert all(count == 0 for count in counts.values()) and all(header["count"] == 0 for header in headers)
            return
    else:
        assert cells
    seen = set()
    kinds = set()
    for cell in cells:
        assert type(cell) is dict and type(cell["index"]) is int and cell["index"] >= 0
        assert cell["index"] not in seen
        seen.add(cell["index"])
        assert type(cell["mesh_uid"]) is int and cell["mesh_uid"] > 0
        assert type(cell["count"]) is int and cell["count"] > 0
        assert cell["logical_values_written"] is False and cell["physical_pointer_stability_required"] is False
        for key in ("attempts_entered", "attempts_returned", "entered_in_capture", "returned_in_capture"):
            assert type(cell[key]) is int and cell[key] >= 0
        assert cell["attempts_entered"] > 0 and cell["attempts_returned"] <= cell["attempts_entered"]
        assert cell["returned_in_capture"] <= cell["entered_in_capture"] <= cell["attempts_entered"]
        assert cell["returned_in_capture"] <= cell["attempts_returned"]
        assert type(cell["last_attempt_returned"]) is bool
        if complete:
            assert cell["last_attempt_returned"] is True and cell["attempts_entered"] == cell["attempts_returned"]
            assert cell["entered_in_capture"] == cell["returned_in_capture"]
        kind = cell["kind"]
        kinds.add(kind)
        if kind == "EXISTING_ARRAY_GEOMETRY_READ":
            assert cell["field"] in {"vertices", "edges", "loops", "polygons"}
            allowed = ["BIT_PRESERVING_ARRAY_COW_UNSHARE", "NATIVE_CACHE_TAGGING"]
            if mesh_profile is not None:
                assert cell["mesh_uid"] == identity["uid"] and cell["count"] == counts[cell["field"]]
        elif kind == "EXISTING_ARRAY_ATTRIBUTE_READ":
            assert type(cell["name"]) is str and cell["name"] and cell["storage"] in {"ARRAY", "LEGACY_ARRAY"}
            allowed = ["BIT_PRESERVING_ARRAY_COW_UNSHARE"]
            if mesh_profile is not None:
                assert cell["mesh_uid"] == identity["uid"] and cell["name"] in by_name
                assert cell["count"] == by_name[cell["name"]]["count"] and cell["storage"] == by_name[cell["name"]]["storage"]
        else:
            assert kind == "VERTEX_GROUP_READ" and cell["build"] == version
            allowed = ["BIT_PRESERVING_GROUP_BUFFER_COW_UNSHARE",
                "EMPTY_CD_MDEFORMVERT_CREATION_AND_LAYER_DESCRIPTOR_REALLOCATION"]
            if mesh_profile is not None:
                assert cell["mesh_uid"] == identity["uid"] and cell["count"] == counts["vertices"]
        assert cell["allowed_effects"] == allowed
    if complete:
        assert kinds == {"EXISTING_ARRAY_GEOMETRY_READ", "EXISTING_ARRAY_ATTRIBUTE_READ", "VERTEX_GROUP_READ"}


def lifetime_groups(proof, indexed):
    groups, ledgers = proof["runtime_groups"], proof["retired_runtime_ledgers"]
    families = proof["main_id_families"]
    assert type(families) is list and families == sorted(set(families)) and len(families) <= 128
    assert {"objects", "meshes", "materials", "collections", "scenes", "armatures", "actions", "images", "cameras", "lights", "worlds"} <= set(families)
    assert type(groups) is list and 2 <= len(groups) <= 128
    assert type(ledgers) is list and len(ledgers) == len(groups)-1
    identities = set()
    for index, group in enumerate(groups):
        assert type(group) is dict and type(group["index"]) is int and group["index"] == index
        assert group["raw_owned_fixture_lifetime_setup"] is True
        finite(group["issued_at"])
        current = group["runtime"]
        for key, value in proof["runtime"].items():
            if key not in {"runtime_identity", "registry_identity", "executor_identity"}:
                assert type(current[key]) is type(value) and current[key] == value
        for key in ("runtime_identity", "registry_identity", "executor_identity"):
            assert type(current[key]) is int and current[key] > 0 and current[key] not in identities
            identities.add(current[key])
        if index == 0:
            assert current == proof["runtime"] and group["prior"] is None
            continue
        assert group["issued_at"] >= groups[index-1]["issued_at"]
        prior, ledger = group["prior"], ledgers[index-1]
        assert prior["ledger_index"] == index-1 and prior["old_registered"] is False
        assert prior["old_runtime_identity"] == groups[index-1]["runtime"]["runtime_identity"]
        assert prior["artist_main_preserved"] is True
        assert ledger["index"] == index-1 and ledger["runtime_identity"] == prior["old_runtime_identity"]
        assert ledger["registered"] is False and ledger["retained_runtime_object"] is True
        assert ledger["record_evictions"] == [] and ledger["native_cleanup"] is False
        assert type(ledger["identities_before"]) is list and ledger["identities_before"] == ledger["identities_after"]
        for identity in ledger["identities_before"]:
            assert type(identity) is list and len(identity) == 7 and identity[0] in families
            assert all(type(identity[index]) is int and identity[index] > 0 for index in (1, 2))
            assert type(identity[3]) is str and type(identity[4]) is int and identity[4] >= 0
            assert type(identity[5]) is bool and type(identity[6]) is str
        assert logical_snapshot(snapshot(ledger["artist_main_before"])) == logical_snapshot(snapshot(ledger["artist_main_after"]))
        before, after = ledger["records_before"], ledger["records_after_unregister"]
        assert type(before) is list and type(after) is list and len(before) == len(after) <= 16
        stage_ids = [row["stage_id"] for row in before]
        assert len(set(stage_ids)) == len(stage_ids) and stage_ids == [row["stage_id"] for row in after] == prior["old_stage_ids"]
        assert all(row["phase"] == "STALE" and row["session_valid"] is False for row in after)
        for previous, stale in zip(before, after, strict=True):
            for key in ("stage_id", "preview_id", "collection_name", "observed_allocations", "possible_mutation"):
                assert stale[key] == previous[key]
            assert stale["outcome_unknown"] is (previous["outcome_unknown"] or previous["possible_mutation"])
        assert ledger["native_evidence"] == ledger["native_evidence_after_unregister"]
        assert set(ledger["native_evidence"]) <= set(stage_ids)
        refusals = group["stale_lookup_refusals"]
        assert type(refusals) is list and [row["stage_id"] for row in refusals] == stage_ids
        for refusal in refusals:
            request = indexed[refusal["request_id"]]
            assert request["runtime_group"] == index and request["request"]["method"] == "asset.glb_stage_inspect"
            assert request["request"]["params"] == {"stage_id": refusal["stage_id"]}
            assert request["delivered"] is True and request["response"]["ok"] is False
            assert request["response"]["error"]["code"] == refusal["error_code"]
    previous = 0
    for request in indexed.values():
        group = request["runtime_group"]
        assert type(group) is int and previous <= group < len(groups)
        assert request["sent_at"] >= groups[group]["issued_at"]
        previous = group
    return groups


def disconnect_witness(row, indexed, *, entry, owner_method, require_escrow):
    """Require a real owner socket close acknowledged at the recorded C return."""
    witness, native = row["witness"], row["native"]
    receipt = witness["disconnect"]
    assert receipt["source_boundary"] == "RUNTIME_NATIVE_GATE_CALL_AFTER_RECORDED_C_RETURN"
    assert receipt["maximum_rendezvous_seconds"] == 1.
    assert receipt["actual_owner_tcp_close"] is True and receipt["network_disconnected_event_ack"] is True
    assert receipt["main_rpc_wait"] is False and receipt["synthetic_cancel"] is False and receipt["fabricated_c_failure"] is False
    owner = indexed[receipt["owner_start_request_id"]]
    assert owner["request"]["id"] in row["requests"] and owner["request"]["method"] == owner_method
    assert owner["runtime_group"] == receipt["runtime_group"]
    assert owner["runtime_receipt"]["connection_identity"] == receipt["connection_identity"]
    assert owner["runtime_receipt"]["disconnected"] is True and owner["delivered"] is True
    assert owner["response"]["ok"] is True and owner["response"]["result"]["accepted"] is True
    accepted = owner["response"]["result"]
    assert witness["actual_terminal"]["job_id"] == accepted["job_id"]
    assert witness["actual_terminal"]["request_id"] == owner["request"]["id"]
    assert any(indexed[key]["request"]["method"] == "jobs.inspect" and indexed[key]["delivered"] and indexed[key]["response"]["ok"]
        and indexed[key]["response"]["result"] == witness["actual_terminal"] for key in row["requests"])
    assert receipt["owner_connection_instance"] == owner["connection_instance"]
    assert not any(indexed[key]["request"]["method"] == "jobs.cancel" for key in row["requests"]
                   if key != witness.get("before_link", {}).get("cancel_request_id"))
    entries = native["native_entries"]
    assert entries and entries[-1]["entry"] == entry and entries[-1]["index"] == receipt["entry_index"]
    assert entries[-1]["returned"] is True and entries[-1]["post_return_stop_checked"] is False
    for key in ("started_monotonic", "returned_monotonic"):
        assert entries[-1][key] == receipt[key]
    started = finite(receipt["started_monotonic"])
    assert owner["sent_at"] <= started
    returned = finite(receipt["returned_monotonic"], started)
    notified = finite(receipt["notified_at"], returned)
    acknowledged = finite(receipt["network_ack_at"], notified)
    assert acknowledged-notified <= receipt["maximum_rendezvous_seconds"]
    assert witness["atomic_native_interval_seconds"] == returned-started
    close = receipt["close_receipt"]
    assert type(close) is list and len(close) == 1
    assert close[0]["actual_socket_fileno"] == -1 and type(close[0]["closed_socket_fileno"]) is int and close[0]["closed_socket_fileno"] >= 0
    assert notified <= finite(close[0]["closed_at"]) <= acknowledged
    assert native["native_access_counts"] == receipt["native_access_counts_at_return"]
    assert witness["stop_ack_native_entry_count"] == len(entries)
    assert witness["genuine_return_escrow_roles"] == receipt["genuine_return_escrow_roles"]
    if require_escrow:
        assert receipt["genuine_return_escrow_roles"]
    assert witness["actual_terminal"]["state"] in {"CANCELLED", "FAILED", "TIMED_OUT"}
    assert native["stopped"] is True
    native_journal(native, stopped=True)


def timer_series(rows, reference, *, started_at, runtime_group):
    assert type(rows) is list and len(rows) == len(OBSERVATIONS)
    for row, (phase, floor) in zip(rows, OBSERVATIONS, strict=True):
        assert row["phase"] == phase and row["real_timer_callback"] is (phase != "immediate")
        elapsed = finite(row["elapsed_seconds"], floor)
        assert row["runtime_group"] == runtime_group
        assert abs(finite(row["observed_at"], started_at)-started_at-elapsed) <= 1e-6
        assert phase != "immediate" or elapsed == 0.
        measured = snapshot(row["snapshot"])
        assert row["logical_sha256"] == digest(logical_snapshot(measured))
        assert logical_snapshot(measured) == logical_snapshot(reference)
    assert [row["elapsed_seconds"] for row in rows] == sorted(row["elapsed_seconds"] for row in rows)

def literal_owned(rows, *, published=False):
    # This source is independently authored, not obtained from the product plan.
    from scripts.blender_glb_stage_smoke import verify_structure_rows
    actual = copy.deepcopy(rows)
    assert actual["collection"]["identity"]["users"] == int(published)
    actual["collection"]["identity"]["users"] = 0
    verify_structure_rows(actual)
    return rows


def runtime_causality(requests, frames):
    """Correlate issued intents, accepted jobs and inspections in wire order."""
    previews, stages, publications, jobs, phases = {}, {}, {}, {}, {}
    def token(value, prefix):
        assert type(value) is str and re.fullmatch(prefix+r"[a-f0-9]{32}", value)
        return value
    for row in requests:
        method, params = row["request"]["method"], row["request"]["params"]
        issued = None
        if method in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start"}:
            issued = previews[params["preview_id"]] if method.endswith("create_start") else publications[params["publish_preview_id"]]
            intent = issued["response"]["result"]
            assert issued["runtime_group"] == row["runtime_group"] and issued["received_at"] <= row["sent_at"]
            assert issued["connection_instance"] == row["connection_instance"]
            assert params["expected_fingerprint"] == intent["expected_fingerprint"]
            if method.endswith("publish_start"):
                assert params["stage_id"] == intent["stage_id"]
        frame = frames.get(row["request"]["id"])
        if not row["delivered"]:
            if frame is None or frame.get("accepted_result") is None:
                continue
            assert method in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start"}
            result = frame["accepted_result"]
            assert frame["accepted_result_source"] in {"addon/blender_codex_bridge/executor.py:_invoke_owned",
                "addon/blender_codex_bridge/glb_stage_runtime.py:attach_job"}
            assert frame["accepted_runtime_group"] == row["runtime_group"]
            accepted_at = finite(frame["accepted_at"], row["sent_at"])
            finite(frame["returned_at"], accepted_at)
        elif row["response"]["ok"]:
            result = row["response"]["result"]
            accepted_at = row["received_at"]
            if frame is not None and frame.get("accepted_result") is not None:
                assert frame["accepted_result"] == result
        else:
            continue
        group = row["runtime_group"]
        if method == "asset.glb_stage_preview":
            preview = token(result["preview_id"], "glb_preview_")
            stage = token(result["stage_id"], "glb_stage_")
            assert preview not in previews and (group, stage) not in stages
            assert re.fullmatch(r"[a-f0-9]{64}", result["expected_fingerprint"])
            previews[preview] = row
            stages[group, stage] = row
            phases[group, stage] = "PREPARED"
        elif method == "asset.glb_stage_publish_preview":
            stage = token(params["stage_id"], "glb_stage_")
            assert (group, stage) in stages and result["stage_id"] == stage
            assert phases[group, stage] == "CONSTRUCTED"
            assert row["connection_instance"] == stages[group, stage]["connection_instance"]
            identifier = token(result["publish_preview_id"], "glb_publish_")
            assert identifier not in publications
            publications[identifier] = row
        elif method in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start"}:
            if method == "asset.glb_stage_create_start":
                assert params["accepted_losses"] == issued["response"]["result"]["required_accepted_losses"]
            intent = issued["response"]["result"]
            assert issued["runtime_group"] == group and issued["received_at"] <= row["sent_at"]
            assert params["expected_fingerprint"] == intent["expected_fingerprint"]
            assert result["accepted"] is True and result["job_completed"] is False
            assert result["stage_id"] == intent["stage_id"] and result["request_id"] == row["request"]["id"]
            stage_key = group, result["stage_id"]
            assert phases[stage_key] == ("PREPARED" if method.endswith("create_start") else "CONSTRUCTED")
            phases[stage_key] = "ALLOCATING" if method.endswith("create_start") else "PUBLISHING"
            job = token(result["job_id"], "job_")
            assert job not in jobs
            jobs[job] = row, result, accepted_at
        elif method in {"jobs.inspect", "jobs.cancel"}:
            owner, accepted, issued_at = jobs[params["job_id"]]
            assert owner["runtime_group"] == group and issued_at <= row["sent_at"]
            assert result["job_id"] == params["job_id"]
            if method == "jobs.inspect":
                assert result["request_id"] == owner["request"]["id"]
                stage_key = group, accepted["stage_id"]
                if result["state"] == "SUCCEEDED":
                    phases[stage_key] = "CONSTRUCTED" if owner["request"]["method"].endswith("create_start") else "PUBLISHED"
                elif result["state"] in {"CANCELLED", "FAILED", "TIMED_OUT"}:
                    phases[stage_key] = "UNKNOWN"
        elif method == "asset.glb_stage_inspect":
            assert (group, params["stage_id"]) in stages
            assert result["stage_id"] == params["stage_id"]
            if result.get("job_id") is not None:
                owner, accepted, _issued_at = jobs[result["job_id"]]
                assert owner["runtime_group"] == group and accepted["stage_id"] == params["stage_id"]
    return jobs


def refusal_contract(case, label):
    """Source-pinned refusal branches; a generic error cannot qualify a gate."""
    create, preview, publish = "asset.glb_stage_create_start", "asset.glb_stage_preview", "asset.glb_stage_publish_start"
    if case == "PERMISSION_AND_TOOLSET":
        if label.startswith(("create_", "publish_")):
            return (publish if label.startswith("publish_") else create), "PERMISSION_DENIED", None
        return create, {"toolset": "TOOLSET_DISABLED", "paused": "AGENT_PAUSED", "emergency_stop": "EMERGENCY_STOPPED"}[label], None
    if case == "SOURCE_AND_NAME_REFUSALS":
        if label.endswith("_collision"):
            return preview, "NOT_IMPLEMENTED", "GLB_EXACT_ALLOCATION_NAME_COLLISION"
        if label == "root_stale":
            return create, "NOT_IMPLEMENTED", "GLB_APPROVED_SOURCE_ROOT_CHANGED"
        if label in {"ancestry", "file_race", "source_stale"}:
            return create, "INVALID_ARGUMENT", None
        return preview, ("PERMISSION_DENIED" if label in {"empty_root", "outside"} else "INVALID_ARGUMENT"), None
    if case == "NORMAL_CONSENT":
        if label in {"omitted", "reordered", "duplicated", "wrong_type", "wrong_normal", "auto_without_normal"}:
            return create, "INVALID_ARGUMENT", None
        return preview, ("INVALID_ARGUMENT" if label == "tangent" else "NOT_IMPLEMENTED"), {
            "mixed_uv": "GLB_MIXED_UV_ZERO_FILL_PUBLIC_GATE_OPEN", "alpha": "ALPHA_MODE_NOT_YET_QUALIFIED"}.get(label)
    if case == "DESTINATION_DRIFT_AND_UNITS":
        return publish, "NOT_IMPLEMENTED", {"child_inventory": "GLB_PUBLICATION_PREVIEW_CHANGED",
            "unit_scale": "GLB_DESTINATION_METRE_UNITS_CHANGED"}.get(label, "GLB_EXPLICIT_CURRENT_DESTINATION_SCENE_REQUIRED")
    assert case == "SHARED_SLOT_REENTRANCY"
    return {"glb": create, "image": "image.snapshot_job_start", "scene": "rigid_body.evaluate_job_start",
        "native_save": "project.native_save_start"}[label], "OPERATION_FAILED", "SCENE_JOB_RESERVATION_BLOCKED"


def validate_runtime_transcript(proof):
    """Cold complete-contract verifier; status/marker booleans cannot prove success."""
    assert type(proof) is dict and proof["schema"] == SCHEMA and proof["profile"] == PROFILE
    assert proof["completed"] is True and proof["project_saved"] is False
    assert proof["protected_observer_logical_profile_ready"] is True
    assert proof["preservation_contract"] == "LOGICAL_AUTHORED_BITS_WITH_DECLARED_READ_EFFECTS_V1"
    assert proof["hidden_layout_or_cache_passivity_claimed"] is False
    assert proof["direct_private_controller"] is False and proof["manual_job_ticks"] is False
    assert proof["evaluated_world_qualified"] is False and proof["source_write_performed"] is False
    assert type(proof["process_id"]) is int and proof["process_id"] > 0
    assert re.fullmatch(r"[a-f0-9]{32}", proof["process_instance"])
    runtime = proof["runtime"]
    assert runtime["host"] == "127.0.0.1" and type(runtime["port"]) is int and 1 <= runtime["port"] <= 65535
    assert runtime["process_id"] == proof["process_id"] and runtime["process_instance"] == proof["process_instance"]
    assert runtime["source_sha256"] == proof["source_sha256"] and runtime["source_sha256"]
    assert runtime["registered"] is True and runtime["canonical_queue"] is True and runtime["main_thread_executor"] is True
    assert all(type(runtime[key]) is int and runtime[key] > 0 for key in ("runtime_identity", "registry_identity", "executor_identity"))
    assert runtime["runtime_identity"] != runtime["registry_identity"] != runtime["executor_identity"]
    requests = proof["tcp"]
    assert type(requests) is list and requests and len(requests) <= 4096
    indexed = {}
    for index, row in enumerate(requests):
        assert type(row) is dict and row["index"] == index and type(row["index"]) is int
        assert row["host"] == "127.0.0.1" and row["port"] == runtime["port"]
        assert re.fullmatch(r"[a-f0-9]{32}", row["connection_instance"])
        request, response = row["request"], row["response"]
        assert type(request) is dict and request["protocol_version"] == "1.0"
        identifier = request["id"]
        assert type(identifier) is str and identifier not in indexed and type(request["params"]) is dict
        assert type(request["method"]) is str and request["method"]
        finite(row["sent_at"])
        assert type(row["delivered"]) is bool
        if row["delivered"]:
            assert type(response) is dict and response["id"] == identifier and type(response["ok"]) is bool
            finite(row["received_at"], row["sent_at"])
            assert type(response["result"] if response["ok"] else response["error"]) is dict
        else:
            assert response is None and row["received_at"] is None
            assert row["transport_outcome"] in {"DISCONNECTED", "EXPIRED", "REJECTED_DELIVERY"}
        receipt = row["runtime_receipt"]
        assert receipt["origin"] == "CANONICAL_SERVER_REQUEST_LIFETIME"
        assert type(receipt["connection_identity"]) is int and receipt["connection_identity"] > 0
        finite(receipt["deadline"])
        finite(receipt["observed_at"])
        for key in ("delivered", "rejected", "disconnected", "expired_without_delivery"):
            assert type(receipt[key]) is bool
        assert receipt["expired_without_delivery"] is (not receipt["delivered"] and receipt["observed_at"] >= receipt["deadline"])
        if row["delivered"]:
            assert receipt["delivered"] is True
        indexed[identifier] = row
        if row["delivered"] and response["ok"] and request["method"] == "asset.glb_stage_preview":
            read_effects(response["result"]["protected_mesh_read_effects"], proof["version"])
    groups = lifetime_groups(proof, indexed)
    connection_bindings = {}
    for row in requests:
        client_connection, server_connection = row["connection_instance"], row["runtime_receipt"]["connection_identity"]
        binding = (server_connection, row["runtime_group"])
        assert connection_bindings.setdefault(client_connection, binding) == binding
    cases = proof["cases"]
    assert type(cases) is list and [row["id"] for row in cases] == list(SCENARIOS)
    by_id = {row["id"]: row for row in cases}
    frames = proof["executor_history_frames"]
    assert type(frames) is list and len(frames) <= 32768
    frame_index = {}
    for frame in frames:
        assert frame["source_frame"] == "addon/blender_codex_bridge/executor.py:_invoke_owned"
        assert frame["request_id"] not in frame_index
        frame_index[frame["request_id"]] = frame
    runtime_causality(requests, frame_index)
    previous_group = 0
    group_spans = {"OWNED_MANUAL_DRIFT": 4, "DESTINATION_DRIFT_AND_UNITS": 5,
        "PUBLICATION_STOP_OR_FAILURE": 1, "SHARED_SLOT_REENTRANCY": 4}
    for case_index, row in enumerate(cases):
        assert row["status"] == "VERIFIED" and type(row["requests"]) is list and row["requests"]
        assert len(set(row["requests"])) == len(row["requests"]) and set(row["requests"]) <= indexed.keys()
        assert type(row["witness"]) is dict and row["witness"]
        assert type(row["runtime_group_start"]) is int and type(row["runtime_group_end"]) is int
        assert 0 <= row["runtime_group_start"] <= row["runtime_group_end"] < len(groups)
        expected_start = previous_group if case_index < 2 or case_index == len(cases)-1 else previous_group+1
        assert row["runtime_group_start"] == expected_start
        assert row["runtime_group_end"] == expected_start+group_spans.get(row["id"], 0)
        previous_group = row["runtime_group_end"]
        assert all(row["runtime_group_start"] <= indexed[key]["runtime_group"] <= row["runtime_group_end"] for key in row["requests"])
        before, after = snapshot(row["before"]), snapshot(row["after"])
        if row["id"] not in {"TCP_SUCCESS_PUBLISH", "PUBLICATION_STOP_OR_FAILURE", "UNDO_LOAD_RUNTIME_INVALIDATION"}:
            assert logical_snapshot(before)["protected"] == logical_snapshot(after)["protected"] and before["context"] == after["context"]
        native_journal(row["native"], stopped=row["native"].get("stopped") is True)
        if row["native"].get("protected_mesh_read_effects") is not None:
            read_effects(row["native"]["protected_mesh_read_effects"], proof["version"], complete=row["native"].get("stopped") is not True)
        history = row["history"]
        assert type(history) is list and history
        assert all(type(item) is dict and item["request_id"] in row["requests"] and
                   item["method"] == indexed[item["request_id"]]["request"]["method"] and
                   type(item["checkpoint_entered"]) is bool and type(item["handler_entered"]) is bool
                   for item in history)
        history_ids = [item["request_id"] for item in history]
        assert len(history_ids) == len(set(history_ids))
        assert history_ids == [key for key in row["requests"] if key in set(history_ids)]
        assert {key for key in row["requests"] if indexed[key]["delivered"] and indexed[key]["response"]["ok"]} <= set(history_ids)
        for item in history:
            assert item == frame_index[item["request_id"]]
            request = indexed[item["request_id"]]
            if request["delivered"] and request["response"]["ok"]:
                assert item["handler_entered"] is True
            if item["method"] in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start"}:
                # These job starts explicitly disable automatic checkpoints.
                assert item["checkpoint_entered"] is False
                if request["delivered"] and request["response"]["ok"]:
                    raw = item["raw_history"]
                    assert raw["tool"] == item["method"] and raw["success"] is True
                    operation = request["response"]["result"]["operation"]
                    assert operation["operation_id"] == raw["operation_id"]
                    assert operation["undo_boundary_created"] is item["checkpoint_entered"]
    assert len(groups) == previous_group+1 and {row["runtime_group"] for row in requests} == set(range(len(groups)))

    def calls(identifier, method=None, ok=None):
        rows = [indexed[key] for key in by_id[identifier]["requests"]]
        if method is not None:
            rows = [row for row in rows if row["request"]["method"] == method]
        if ok is not None:
            rows = [row for row in rows if row["delivered"] and row["response"]["ok"] is ok]
        assert rows
        return rows
    def result(identifier, method):
        return calls(identifier, method, True)[-1]["response"]["result"]
    def errors(identifier, labels):
        row = by_id[identifier]
        models = row["witness"]["refusals"]
        assert type(models) is list and {v["label"] for v in models} == set(labels)
        assert len(models) == len(labels)
        for item in models:
            request = indexed[item["request_id"]]
            assert item["request_id"] in row["requests"] and request["delivered"]
            assert request["response"]["ok"] is False
            method, code, reason = refusal_contract(identifier, item["label"])
            assert request["request"]["method"] == method and request["response"]["error"]["code"] == code
            error = request["response"]["error"]
            if reason is not None:
                assert error["context"]["reason"] == reason
            fault = item["fault_observation"]
            assert fault["scope"] == "RAW_OWNED_REFUSAL_BOUNDARY_OBSERVATION" and fault["runtime_group"] == request["runtime_group"]
            assert finite(fault["observed_at"]) <= request["sent_at"]
            assert fault["request_params"] == request["request"]["params"]
            label = item["label"]
            if identifier == "PERMISSION_AND_TOOLSET":
                if label.startswith(("create_", "publish_")):
                    grant = label.split("_", 1)[1]
                    required = PUBLISH_GRANTS if label.startswith("publish_") else CREATE_GRANTS
                    assert [value for value in required if fault["permissions"][value] is False] == [grant]
                    assert error["context"]["missing_permissions"] == [grant]
                    assert set(error["context"]["required"]) == set(required)
                elif label == "toolset":
                    assert "asset_delivery" not in fault["enabled_toolsets"]
                    assert error["context"]["tool"] == method and error["context"]["toolset"] == "asset_delivery"
                else:
                    assert fault["emergency_stopped" if label == "emergency_stop" else "paused"] is True
            elif identifier == "SOURCE_AND_NAME_REFUSALS":
                if label == "empty_root":
                    assert fault["source_root"] == ""
                elif label in {"symlink", "fifo"}:
                    assert (stat.S_ISLNK if label == "symlink" else stat.S_ISFIFO)(fault["input_file"]["mode"])
                elif label in {"ancestry", "file_race", "source_stale", "root_stale"}:
                    mutation = fault["source_fault"]
                    assert mutation["kind"] == label
                    field = {"ancestry": "parent_identity", "file_race": "file_identity", "source_stale": "sha256", "root_stale": "root"}[label]
                    assert mutation["before"][field] != mutation["after"][field]
                elif label.endswith("_collision"):
                    family = {"collection": "collections", "mesh": "meshes", "material": "materials", "object": "objects"}[label.split("_", 1)[0]]
                    suffix = {"collections": "", "meshes": ".M0", "materials": ".P0", "objects": ".O0"}[family]
                    assert any(value[0] == family and value[3] == request["request"]["params"]["collection_name"]+suffix for value in item["before_native_identities"])
                else:
                    assert label == "outside" and not Path(fault["input_file"]["path"]).is_relative_to(Path(fault["source_root"]))
            elif identifier == "NORMAL_CONSENT":
                if method.endswith("create_start"):
                    assert request["request"]["params"]["accepted_losses"] != LOSSES
                    assert error["message"] == "accepted_losses must repeat the structured GLB plan list exactly."
                else:
                    assert Path(fault["input_file"]["path"]).stem == label
                    assert re.fullmatch(r"[a-f0-9]{64}", fault["input_file"]["sha256"])
            elif identifier == "DESTINATION_DRIFT_AND_UNITS":
                mutation = fault["destination_fault"]
                assert mutation["kind"] == label and mutation["before"] != mutation["after"]
            else:
                assert fault["active_job_id"] is not None
            assert item["before_native_identities"] == item["after_native_identities"]
            assert type(item["before_native_identities"]) is list and item["before_native_identities"]
    first = by_id["TCP_SUCCESS_STAGE"]
    assert result("TCP_SUCCESS_STAGE", "asset.glb_stage_preview")["required_accepted_losses"] == LOSSES
    accepted = result("TCP_SUCCESS_STAGE", "asset.glb_stage_create_start")
    assert accepted["accepted"] is True and accepted["job_completed"] is False
    assert result("TCP_SUCCESS_STAGE", "jobs.inspect")["state"] == "SUCCEEDED"
    assert result("TCP_SUCCESS_STAGE", "jobs.inspect")["job_id"] == accepted["job_id"]
    state = result("TCP_SUCCESS_STAGE", "asset.glb_stage_inspect")
    assert state["phase"] == "CONSTRUCTED" and state["publication_observed"] is False
    assert state["stage_id"] == accepted["stage_id"]
    assert state["job_id"] == accepted["job_id"] and state["native_evidence"] == first["native"]
    assert calls("TCP_SUCCESS_STAGE", "asset.glb_stage_create_start", True)[0]["request"]["params"]["accepted_losses"] == LOSSES
    literal_owned(first["after"]["owned"])
    assert first["before"]["scene_edges"] == first["after"]["scene_edges"]
    assert first["witness"]["source_sha256"] == hashlib.sha256(literal_source()).hexdigest()
    assert first["witness"]["normal_source_loop_count"] == 3 and first["witness"]["auto_normal_loop_count"] == 3
    assert first["native"]["footprint_complete"] is True
    from scripts.blender_glb_stage_smoke import verify_structure_entries
    verify_structure_entries(first["native"]["native_entries"], "success", proof["version"])
    assert set(first["native"]["owned_reference_roles"]) == set(first["after"]["owned"])
    receipts = first["native"]["mesh_return_receipts"]
    normal = first["witness"]["normal_return_footprint"]
    assert normal["scope"] == "PURE_CACHED_RETURN_FRAME_OBSERVATION"
    from scripts.blender_glb_stage_smoke import structure_body, structure_digest
    assert normal["body_sha256"] == structure_digest(normal["body"])
    assert normal["operation"] == "WRITE_NORMALS" and normal["role"] == "mesh:0"
    assert normal["stage_id"] == accepted["stage_id"]
    capture_index = normal["native_entry_index"]
    assert type(capture_index) is int and capture_index > 0
    capture = first["native"]["native_entries"][capture_index]
    write = first["native"]["native_entries"][capture_index-1]
    assert (capture["operation"], capture["role"], capture["entry"]) == ("WRITE_NORMALS", "mesh:0", "mesh_return.complete_read_attempt")
    assert write["entry"] == "Mesh.normals_split_custom_set" and write["returned"] is True and capture["returned"] is True
    receipt = next(item for item in receipts if item["operation"] == "WRITE_NORMALS")
    assert receipt["stage_id"] == normal["stage_id"] and receipt["role"] == normal["role"]
    assert receipt["body_sha256"] == normal["body_sha256"] and receipt["capture_returned"] is True
    assert receipt["captured_before_generic_callback"] is True
    desired = copy.deepcopy(structure_body(first["after"]["owned"]["mesh:0"]))
    if "material_index" not in normal["body"]["custom_data"]:
        desired["custom_data"].pop("material_index", None)
    assert desired == normal["body"]

    second = by_id["TCP_SUCCESS_PUBLISH"]
    published = result("TCP_SUCCESS_PUBLISH", "asset.glb_stage_publish_start")
    assert published["accepted"] is True and published["stage_id"] == accepted["stage_id"]
    assert result("TCP_SUCCESS_PUBLISH", "jobs.inspect")["state"] == "SUCCEEDED"
    assert result("TCP_SUCCESS_PUBLISH", "jobs.inspect")["job_id"] == published["job_id"]
    published_state = result("TCP_SUCCESS_PUBLISH", "asset.glb_stage_inspect")
    assert published_state["publication_observed"] is True and published_state["stage_id"] == published["stage_id"]
    assert published_state["job_id"] == published["job_id"] and published_state["native_evidence"] == second["native"]
    literal_owned(second["after"]["owned"], published=True)
    publish_entries = second["native"]["native_entries"]
    assert publish_entries[:-1] == first["native"]["native_entries"]
    assert (publish_entries[-1]["operation"], publish_entries[-1]["role"], publish_entries[-1]["entry"]) == ("PUBLISH_COLLECTION", "collection", "CollectionChildren.link")
    assert set(second["native"]["owned_reference_roles"]) == set(second["after"]["owned"])
    edge = second["witness"]["published_edge"]
    assert type(edge) is list and len(edge) == 2 and all(type(v) is int and v > 0 for v in edge)
    assert second["after"]["scene_edges"] == sorted([*second["before"]["scene_edges"], edge])
    object_uids = [value["identity"]["uid"] for role, value in second["after"]["owned"].items() if role.startswith("object:")]
    exact_publication_delta(second["before"], second["after"], edge, object_uids)
    series = proof["observation_series"]
    assert type(series) is list and [value["kind"] for value in series] == ["CONSTRUCTED", "PUBLISHED"]
    for value, case in zip(series, (first, second), strict=True):
        assert value["runtime_group"] == case["runtime_group_end"]
        completion = indexed[value["after_request_id"]]
        assert completion["request"]["id"] in case["requests"] and completion["request"]["method"] == "asset.glb_stage_inspect"
        assert completion["response"]["ok"] is True
        assert completion["response"]["result"]["phase"] == value["kind"]
        started = finite(value["started_at"], completion["received_at"])
        assert started >= max(entry["returned_monotonic"] for entry in case["native"]["native_entries"])
        timer_series(value["observations"], case["after"], started_at=started, runtime_group=value["runtime_group"])
    errors("PERMISSION_AND_TOOLSET", [*("create_"+v for v in CREATE_GRANTS), *("publish_"+v for v in PUBLISH_GRANTS), "toolset", "paused", "emergency_stop"])
    errors("SOURCE_AND_NAME_REFUSALS", ["empty_root", "outside", "symlink", "fifo", "ancestry", "file_race", "source_stale", "root_stale", "collection_collision", "mesh_collision", "material_collision", "object_collision"])
    errors("NORMAL_CONSENT", ["omitted", "reordered", "duplicated", "wrong_type", "wrong_normal", "auto_without_normal", "mixed_uv", "alpha", "texture", "skin", "animation", "tangent", "uri", "extra_stream"])
    assert by_id["NORMAL_CONSENT"]["witness"]["accepted_losses"] == LOSSES
    handoff = by_id["START_HANDOFF_AND_DISCONNECT"]
    assert {v["kind"] for v in handoff["witness"]["outcomes"]} == {"undelivered", "expired", "disconnect"}
    for item in handoff["witness"]["outcomes"]:
        req = indexed[item["request_id"]]
        assert req["request"]["method"] == "asset.glb_stage_create_start"
        assert item["request_id"] in handoff["requests"]
        assert req["delivered"] is False and item["work_before_handoff"] == []
        actual_lifetime = req["runtime_receipt"]
        assert actual_lifetime["delivered"] is False
        assert actual_lifetime["disconnected"] is True or actual_lifetime["rejected"] is True or actual_lifetime["expired_without_delivery"] is True
        if item["kind"] == "expired":
            assert actual_lifetime["expired_without_delivery"] is True
        assert (item["no_job_accepted"] is True and item["terminal"] is None) or item["terminal"]["state"] in {"CANCELLED", "FAILED", "TIMED_OUT"}
        acceptance = frame_index.get(item["request_id"], {}).get("accepted_result")
        if item["no_job_accepted"] is True:
            assert acceptance is None
        else:
            assert type(acceptance) is dict and acceptance["accepted"] is True
            assert item["terminal"]["job_id"] == acceptance["job_id"] and item["terminal"]["request_id"] == item["request_id"]
        assert item["native"]["native_entries"] == []
    for name in ("GENUINE_CANCEL_AFTER_UV",):
        row = by_id[name]
        ack = calls(name, "jobs.cancel", True)[-1]
        assert row["witness"]["cancel_request_id"] == ack["request"]["id"]
        assert row["witness"]["stop_ack_native_entry_count"] == len(row["native"]["native_entries"])
        assert result(name, "jobs.inspect")["state"] == "CANCELLED"
        assert row["native"]["stopped"] is True
        native_journal(row["native"], stopped=True)
        assert row["witness"]["genuine_return_escrow_roles"]
    cancelled = by_id["GENUINE_CANCEL_AFTER_UV"]
    entries = cancelled["native"]["native_entries"]
    assert entries and entries[-1]["operation"] == "WRITE_UV" and entries[-1]["returned"] is True
    assert cancelled["witness"]["observed_uv_native_index"] == entries[-1]["index"]
    assert not any(v["operation"] in {"WRITE_NORMALS", "NEW_MATERIAL", "INIT_MATERIAL", "WRITE_PBR", "BIND_MATERIAL"} for v in entries)
    disconnect_witness(by_id["STOP_AT_NATIVE_RETURN"], indexed, entry="meshes.new",
                       owner_method="asset.glb_stage_create_start", require_escrow=True)
    revoked = by_id["PERMISSION_REVOCATION"]
    assert revoked["witness"]["revoked_grant"] in CREATE_GRANTS
    assert result("PERMISSION_REVOCATION", "jobs.inspect")["state"] == "FAILED"
    assert result("PERMISSION_REVOCATION", "jobs.inspect")["error"]["code"] == "PERMISSION_DENIED"
    native_journal(revoked["native"], stopped=True)
    drift = by_id["OWNED_MANUAL_DRIFT"]["witness"]["drifts"]
    assert {v["kind"] for v in drift} == {"encoded_short", "selection_bit", "uv_role", "authored_channel", "schema"}
    for item in drift:
        assert item["before"] != item["after"] and type(item["before"]) is dict and type(item["after"]) is dict
        req = indexed[item["request_id"]]
        assert req["request"]["method"] == "asset.glb_stage_publish_start" and req["response"]["ok"] is False
        assert item["scene_edges_before"] == item["scene_edges_after"]
    errors("DESTINATION_DRIFT_AND_UNITS", ["scene_identity", "master_identity", "child_inventory", "name", "context", "unit_scale"])
    partial = by_id["PARTIAL_UNKNOWN_IDS"]
    assert partial["witness"]["retained_identities"] and partial["witness"]["unknown_inventory"] is True
    assert partial["witness"]["deletions"] == []
    assert result("PARTIAL_UNKNOWN_IDS", "asset.glb_stage_inspect")["outcome_unknown"] is True
    assert partial["witness"]["raw_partial_identities"] and partial["witness"]["incomplete_native_footprint"] is True
    assert partial["native"]["footprint_complete"] is False
    retained = partial["witness"]["retained_identities"]
    raw = partial["witness"]["raw_partial_identities"]
    assert type(retained) is list and type(raw) is list
    raw_by_identity = {}
    for identity in raw:
        assert type(identity) is list and len(identity) == 7
        assert identity[0] in {"collections", "meshes"}
        assert all(type(identity[index]) is int and identity[index] > 0 for index in (1, 2))
        key = identity[0], identity[1], identity[2]
        assert key not in raw_by_identity
        raw_by_identity[key] = identity
    covered = set()
    for allocation in retained:
        assert type(allocation) is dict and allocation["role"] == "collection"
        key = "collections", allocation["native_uid"], allocation["pointer"]
        assert raw_by_identity[key][3] == allocation["name"]
        covered.add(key)
    escrow = partial["witness"]["raw_escrow_identities"]
    assert type(escrow) is list and [value["role"] for value in escrow] == partial["witness"]["genuine_return_escrow_roles"] == ["mesh:0"]
    owner = indexed[partial["witness"]["disconnect"]["owner_start_request_id"]]["response"]["result"]
    for allocation in escrow:
        assert allocation["stage_id"] == owner["stage_id"] and allocation["family"] == "meshes"
        key = allocation["family"], allocation["native_uid"], allocation["pointer"]
        assert raw_by_identity[key][3] == allocation["name"]
        covered.add(key)
    assert covered == set(raw_by_identity)
    assert set(partial["native"]["owned_reference_roles"]) == {"collection", "mesh:0"}
    pending = partial["native"]["pending_returns"]
    assert any(value["stage_id"] == owner["stage_id"] and value["operation"] == "NEW_MESH" and value["role"] == "mesh:0"
               and value["returned_roles"] == ["mesh:0"] and value["drained"] is True for value in pending)
    disconnect_witness(partial, indexed, entry="meshes.new", owner_method="asset.glb_stage_create_start", require_escrow=True)
    publication = by_id["PUBLICATION_STOP_OR_FAILURE"]["witness"]
    assert publication["before_link"]["edges_before"] == publication["before_link"]["edges_after"]
    assert publication["after_link"]["phase"] in {"PUBLISHED", "PUBLICATION_UNKNOWN"}
    assert publication["after_link"]["automatic_unlink"] is False
    after_link = publication["after_link"]
    assert after_link["phase"] == "PUBLICATION_UNKNOWN" and after_link["retained"]["outcome_unknown"] is True
    assert after_link["native"] == by_id["PUBLICATION_STOP_OR_FAILURE"]["native"]
    assert after_link["disconnect"] == publication["disconnect"]
    assert after_link["physical_effects"] == ["GLOBAL_BKE_MAIN_COLLECTION_SYNC_ALL_SCENES", "LAYER_COLLECTION_LOCAL_VIEW_BASE_CACHE_SYNC"]
    physical = after_link["native"]["publication_physical_effects"]
    assert physical["declared_native_link_effects"] == ["MAIN_WIDE_COLLECTION_LAYER_BASE_SYNC", "LOCAL_VIEW_COLLECTION_SYNC"]
    assert physical["main_wide_sync_may_have_run"] is True and physical["hidden_layout_or_cache_passivity_qualified"] is False
    exact_publication_delta(snapshot(after_link["before"]), snapshot(after_link["after"]), after_link["actual_edge"], after_link["object_closure"])
    disconnect_witness(by_id["PUBLICATION_STOP_OR_FAILURE"], indexed, entry="CollectionChildren.link",
                       owner_method="asset.glb_stage_publish_start", require_escrow=False)
    invalidation = by_id["UNDO_LOAD_RUNTIME_INVALIDATION"]["witness"]["invalidations"]
    assert {v["kind"] for v in invalidation} == {"undo", "redo", "file_load", "runtime_reset"}
    for item in invalidation:
        assert item["actual_native_operation"] is True and item["stale_phase"] == "STALE"
        assert item["old_stage_id"] != item["fresh_stage_id"] and item["stale_native_entries"] == []
    errors("SHARED_SLOT_REENTRANCY", ["glb", "image", "scene", "native_save"])
    nested = by_id["SHARED_SLOT_REENTRANCY"]["witness"]["nested_executor_probes"]
    assert len(nested) == 4 and {v["kind"] for v in nested} == {"provider", "checkpoint", "handler", "finalizer"}
    for item in nested:
        assert item["scope"] == "TRUSTED_NESTED_EXECUTOR_ONLY"
        assert item["outer_request_id"] in by_id["SHARED_SLOT_REENTRANCY"]["requests"]
        assert item["response"]["ok"] is False and item["nested_grant_entries"] == 0
        assert item["nested_checkpoint_entries"] == 0 and item["nested_native_entries"] == 0

    assert by_id["SHARED_SLOT_REENTRANCY"]["witness"]["canonical_slot_count"] == 1
    observations = proof["observations"]
    assert type(observations) is list and len(observations) == len(OBSERVATIONS)
    reference = snapshot(observations[0]["snapshot"])
    for row, (phase, floor) in zip(observations, OBSERVATIONS, strict=True):
        assert row["phase"] == phase and row["real_timer_callback"] is (phase != "immediate")
        elapsed = finite(row["elapsed_seconds"], floor)
        assert phase != "immediate" or elapsed == 0.
        assert logical_snapshot(snapshot(row["snapshot"])) == logical_snapshot(reference)
    assert [v["elapsed_seconds"] for v in observations] == sorted(v["elapsed_seconds"] for v in observations)
    assert by_id["REAL_DEFERRED_PRESERVATION"]["witness"]["observation_digests"] == [digest(v["snapshot"]) for v in observations]
    refusals = proof["single_storage_refusals"]
    assert type(refusals) is list
    refusal_index = {}
    for refusal in refusals:
        assert refusal["request_id"] not in refusal_index
        refusal_index[refusal["request_id"]] = refusal
        request = indexed[refusal["request_id"]]
        assert request["runtime_group"] == refusal["runtime_group"] and request["request"]["method"] == "asset.glb_stage_preview"
        assert request["response"]["ok"] is False and request["response"]["error"] == refusal["error"]
        assert "SINGLE" in refusal["error"]["context"]["reason"]
        assert any(row["storage"] == "SINGLE" for mesh in refusal["headers"] for row in mesh["attributes"])
        assert "get:data" not in refusal["native_access_counts"]
        assert refusal["protected_read_effect_attempts"] == [] and refusal["checkpoint_marker_entries"] == 0
        finite(refusal["recorded_at"], request["received_at"])
    preparations = proof["raw_storage_preparations"]
    assert type(preparations) is list
    prepared_requests = set()
    for preparation in preparations:
        assert preparation["scope"] == "RAW_OWNED_FIXTURE_PREPARATION_NOT_BRIDGE_API"
        assert preparation["scalar_float_or_unknown_conversion"] is False and preparation["logical_values_reset"] is False
        assert preparation["record_evictions"] == [] and preparation["native_qualified"] is False
        refusal_id = preparation["refusal_request_id"]
        assert refusal_id in refusal_index and refusal_id not in prepared_requests
        prepared_requests.add(refusal_id)
        refusal = refusal_index[refusal_id]
        assert preparation["runtime_group"] == refusal["runtime_group"]
        assert preparation["mesh_target"] == refusal["mesh_target"] and preparation["before_headers"] == refusal["headers"]
        started = finite(preparation["started_at"], refusal["recorded_at"])
        finished = finite(preparation["finished_at"], started)
        expected = copy.deepcopy(preparation["before_headers"])
        pending = {(mesh["identity"]["uid"], row["name"]): row for mesh in expected for row in mesh["attributes"] if row["storage"] == "SINGLE"}
        affected = {uid for uid, _name in pending}
        assert pending and len(preparation["actions"]) == len(pending)
        for action in preparation["actions"]:
            key = (action["mesh_identity"]["uid"], action["attribute"])
            original = pending.pop(key)
            assert action["before_header"] == original and original["data_type"] in {"BOOLEAN", "FLOAT2", "INT", "FLOAT_VECTOR"}
            assert original["supported"] is True and action["data_type"] == original["data_type"]
            assert action["authoring_scope"] == "RAW_OWNED_FIXTURE_EDIT_MESH" and action["production_preparation_api"] is False
            assert action["native_action"] == "QUALIFIED_GENERIC_ATTRIBUTE_DATA_MATERIALIZATION"
            assert action["pre_single_value_sha256"] is None and action["bit_preservation_basis"] == "PINNED_SOURCE_EQUIVALENCE_NOT_EMPIRICAL_PRE_SINGLE_READ"
            assert action["known_fixture_oracles_required_after_readback"] is True
            original["storage"] = "ARRAY"
            assert action["after_header"] == original
        assert not pending and expected == preparation["after_headers"]
        readback = preparation["post_readback"]
        assert type(readback) is list and len(readback) == len(affected) and {row["mesh_uid"] for row in readback} == affected
        for row in readback:
            headers = next(item for item in expected if item["identity"]["uid"] == row["mesh_uid"])
            assert row["headers"] == headers
            projection = row["logical_projection"]
            assert projection == row["row"]["logical_projection"]
            from scripts.blender_glb_stage_smoke import structure_digest
            assert row["authored_sha256"] == structure_digest(projection)
            for key, value in headers.items():
                if key == "attributes":
                    value = [{name: field for name, field in header.items() if name != "storage"} for header in value]
                assert projection[key] == value
            assert all(row["row"]["identity"][key] == value for key, value in headers["identity"].items())
            assert set(row["row"]["attributes"]) == {item["name"] for item in headers["attributes"]}
            geometry = projection["geometry"]
            assert type(geometry) is dict and set(geometry) == set(headers["counts"])
            assert all(type(geometry[field]) is list and len(geometry[field]) == count for field, count in headers["counts"].items())
            for values in geometry.values():
                assert all(type(value) is dict and value["index"] == index for index, value in enumerate(values))
            observed = row["row"]
            assert observed["coordinates"] == [value["co"] for value in geometry["vertices"]]
            assert observed["corners"] == [[value["vertex_index"], value["edge_index"]] for value in geometry["loops"]]
            assert observed["faces"] == [[value["loop_start"], value["loop_total"], value["vertices"], value["material_index"], value["use_smooth"]] for value in geometry["polygons"]]
            assert observed["edges"] == sorted(sorted(value["vertices"]) for value in geometry["edges"])
            assert observed["memberships"] == [value["groups"] for value in geometry["vertices"]]
            assert observed["materials"] == headers["materials"] and observed["uv_roles"] == headers["uv_roles"]
            assert observed["uv_layers_complete"] == projection["uv_layers"]
            assert set(projection["attribute_values"]) == {item["name"] for item in headers["attributes"]}
            for header in headers["attributes"]:
                assert type(projection["attribute_values"][header["name"]]) is list and len(projection["attribute_values"][header["name"]]) == header["count"]
                assert row["row"]["attributes"][header["name"]] == {"domain": header["domain"], "type": header["data_type"],
                    "values": projection["attribute_values"][header["name"]]}
        if preparation["mesh_target"] is None:
            baseline = snapshot(preparation["baseline_after"])
            finite(preparation["baseline_observed_at"], finished)
            for row in readback:
                observed = next(mesh for mesh in baseline["protected"]["meshes"] if mesh["identity"]["uid"] == row["mesh_uid"])
                assert observed == row["row"]
        else:
            assert "baseline_after" not in preparation and "baseline_observed_at" not in preparation
            drifts = by_id["OWNED_MANUAL_DRIFT"]["witness"]["drifts"]
            matches = [row for row in drifts if row.get("raw_preparation_request_id") == refusal_id]
            assert len(matches) == 1 and matches[0]["requires_raw_preparation"] is True
            assert matches[0]["mesh_target"] == preparation["mesh_target"] and matches[0]["headers"] == preparation["before_headers"]
            assert len(readback) == 1
            assert all(matches[0]["after"]["mesh"][key] == value for key, value in readback[0]["row"].items())
    raw_reads = proof["raw_observation_read_effects"]
    assert type(raw_reads) is list and raw_reads
    for observation in raw_reads:
        assert observation["native_qualified"] is False and type(observation["mesh_uid"]) is int and observation["mesh_uid"] > 0
        finite(observation["at"])
        if observation["scope"] == "TRUSTED_RAW_NEW_OWNED_NORMAL_CACHE_OBSERVATION":
            assert observation["allowed_effects"] == ["BIT_PRESERVING_ARRAY_COW_UNSHARE", "CORNER_NORMAL_CACHE_TAG_OR_MATERIALIZATION"]
        else:
            assert observation["scope"] == "TRUSTED_RAW_FIXTURE_OBSERVER_NOT_RUNTIME_AUTHORITY" and observation["runtime_gate_bound"] is False
            read_effects({**first["native"]["protected_mesh_read_effects"], "runtime_gate_bound": False,
                         "read_effects": observation["read_effects"]}, proof["version"], runtime=False,
                         mesh_profile=observation["mesh_profile"])
            assert observation["mesh_uid"] == observation["mesh_profile"]["identity"]["uid"]
    countermodels = by_id["REPORT_COUNTERMODELS"]["witness"]["countermodels"]
    assert {v["kind"] for v in countermodels} == set(COUNTERMODELS)
    assert all(v["rejected"] is True and type(v["reason"]) is str and v["reason"] for v in countermodels)
    return True


COUNTERMODELS = ("runtime", "pid", "source", "token", "loss", "entry", "return", "receipt", "ownership",
                 "edge", "normal", "output_target", "selection", "stop", "history", "timer", "context", "status_only",
                 "group_reuse", "group_eviction", "group_native_cleanup", "group_stale_lookup", "group_request",
                 "disconnect_synthetic", "disconnect_wrong_owner", "disconnect_late_ack", "disconnect_extra_access",
                 "postlink_unlink", "postlink_extra_scene_change", "constructed_timer", "published_timer",
                 "read_effect_write", "read_effect_single", "read_effect_hidden_passivity", "single_refusal_late_data", "empty_read_nonzero",
                 "unbacked_preparation", "preparation_before_refusal", "preparation_different_headers",
                 "causal_tokens", "causal_native", "causal_refusals", "partial_identity",
                 "disconnect_refused_start", "history_coverage", "timer_causality")


def literal_source():
    from scripts.blender_glb_stage_smoke import structure_source_glb
    return structure_source_glb()


class TCPClient:
    """Persistent real loopback client. This class never imports or accesses bpy."""
    def __init__(self, port, transcript):
        self.port, self.transcript = port, transcript
        self.runtime_group = 0
        self.connection_instance = os.urandom(16).hex()
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=90)
        self.stream = self.socket.makefile("rb")

    def call(self, method, *, expect_error=False, **params):
        return self.call_with_id("glb_runtime_"+os.urandom(16).hex(), method, expect_error=expect_error, **params)

    def call_with_id(self, identifier, method, *, expect_error=False, **params):
        request = {"id": identifier, "method": method, "params": params, "protocol_version": "1.0", "timeout_ms": 60000}
        row = {"index": len(self.transcript), "host": "127.0.0.1", "port": self.port,
               "connection_instance": self.connection_instance, "runtime_group": self.runtime_group, "request": request, "response": None,
               "sent_at": time.monotonic(), "received_at": None, "delivered": False}
        self.transcript.append(row)
        self.socket.sendall(encode(request))
        response = decode(self.stream.readline(MAX_LOG + 1))
        row.update(response=response, received_at=time.monotonic(), delivered=True)
        assert response["id"] == identifier and response["ok"] is (not expect_error), response
        return response["error"] if expect_error else response["result"]

    def send_without_receipt(self, method, params, *, timeout_ms, outcome):
        identifier = "glb_runtime_"+os.urandom(16).hex()
        request = {"id": identifier, "method": method, "params": params, "protocol_version": "1.0", "timeout_ms": timeout_ms}
        self.transcript.append({"index": len(self.transcript), "host": "127.0.0.1", "port": self.port,
            "connection_instance": self.connection_instance, "runtime_group": self.runtime_group, "request": request, "response": None,
            "sent_at": time.monotonic(), "received_at": None, "delivered": False, "transport_outcome": outcome})
        self.socket.sendall(encode(request))
        self.socket.shutdown(socket.SHUT_RDWR)
        return identifier

    def reconnect(self):
        self.close()
        self.connection_instance = os.urandom(16).hex()
        self.socket = socket.create_connection(("127.0.0.1", self.port), timeout=90)
        self.stream = self.socket.makefile("rb")

    def abort(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        finally:
            self.stream.close()
            self.socket.close()

    def close(self):
        self.stream.close()
        self.socket.close()


def assert_shared_group_fixture(groups):
    """Both Objects share the complete Mesh definitions and deformation data."""
    from scripts.blender_glb_stage_smoke import numeric

    expected = [
        {"index": 0, "name": "Runtime Protected Group", "lock_weight": False},
        {"index": 1, "name": "Runtime Shared Group", "lock_weight": False}]
    assert type(groups["groups"]) is list and len(groups["groups"]) == 2
    assert all(type(row) is dict and set(row) == {"index", "name", "lock_weight"}
               and type(row["index"]) is int and type(row["name"]) is str
               and type(row["lock_weight"]) is bool for row in groups["groups"])
    assert groups["groups"] == expected, {"expected": expected,
        "observed": groups["groups"], "object_identity": groups["object_identity"]}
    memberships = [[[0, numeric((weight,))[0]]] for weight in (.25, .75, .75)]
    assert type(groups["memberships"]) is list and len(groups["memberships"]) == 3
    assert all(type(row) is list and len(row) == 1 and type(row[0]) is list and len(row[0]) == 2
               and type(row[0][0]) is int and type(row[0][1]) is str for row in groups["memberships"])
    assert groups["memberships"] == memberships, {"expected": memberships,
        "observed": groups["memberships"], "object_identity": groups["object_identity"]}


class RuntimeFixture:
    """Owned main-thread setup, raw fault actions and independent observations."""
    def __init__(self, root, folder, bpy, attestation):
        from scripts.blender_glb_stage_smoke import file_digest
        self.root, self.folder, self.bpy = root, folder, bpy
        self.controls, self.done = queue.Queue(), threading.Event()
        self.failure, self.histories, self.current = None, {}, None
        self.receipts = {}
        self.boundaries = {}
        self.request_lifetimes = {}
        self.before_thread_profile = threading.getprofile()
        assert self.before_thread_profile is None
        self.path = folder / FILENAME
        assert not self.path.exists()
        binary = Path(bpy.app.binary_path).resolve(strict=True)
        self.data = {"schema": SCHEMA, "profile": PROFILE, "completed": False,
            "blender_version": bpy.app.version_string, "version": list(bpy.app.version),
            "build_hash": bpy.app.build_hash.decode("ascii"), "process_id": os.getpid(),
            "process_instance": attestation["process_instance"], "source_sha256": source_hashes(root),
            "binary": {"path": str(binary), "sha256": file_digest(binary)}, "attestation": attestation,
            "project_saved": False, "source_write_performed": False, "direct_private_controller": False,
            "manual_job_ticks": False, "evaluated_world_qualified": False,
            "protected_observer_const_read_qualified": False,
            "protected_observer_logical_profile_ready": False, "hidden_layout_or_cache_passivity_claimed": False,
            "protected_observer_gate": "HELD_UNTIL_SOURCE_QUALIFIED_HEADER_AND_ARRAY_PREPARATION",
            "tcp": [], "cases": [], "observations": [], "raw_actions": []}
        self.before_profile = sys.getprofile()
        assert self.before_profile is None
        self.owned_allocations, self.watch, self.nested_probes = [], None, []
        self.name_sequence = 0
        self.group_index = 0
        self.retired_runtimes = []
        self.current_requests = []
        self.start_acceptances = {}
        self.request_access = {}
        self.request_read_effects = {}
        self.marker_entries = {}
        self.disconnect_watch = None
        self.entry_code = None
        self.data.update(runtime_groups=[], retired_runtime_ledgers=[], executor_history_frames=[],
            single_storage_refusals=[], raw_storage_preparations=[], raw_observation_read_effects=[],
            preservation_contract="LOGICAL_AUTHORED_BITS_WITH_DECLARED_READ_EFFECTS_V1")

    def flush(self):
        raw = encode(pack_proof(self.data))
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
            getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
        try:
            assert stat.S_ISREG(os.fstat(descriptor).st_mode)
            view = memoryview(raw)
            while view:
                count = os.write(descriptor, view)
                assert count > 0
                view = view[count:]
        finally:
            os.close(descriptor)

    def setup(self):
        bpy = self.bpy
        # Canonical enable creates the live preferences entry; direct register()
        # alone does not. This remains factory-owned setup before the baseline.
        bpy.context.preferences.use_preferences_save = False
        assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}, "Add-on enable failed"
        entry = bpy.context.preferences.addons.get("blender_codex_bridge")
        assert entry is not None, "Enabled add-on entry is missing"
        self.prefs = entry.preferences
        assert self.prefs is not None and self.prefs.auto_start is False, "Factory add-on preferences are not ready"
        from blender_codex_bridge.permissions import PREFERENCE_PROPERTIES, Permission
        from blender_codex_bridge.runtime import get_runtime
        self.runtime = get_runtime()
        for grant in CREATE_GRANTS:
            setattr(self.prefs, PREFERENCE_PROPERTIES[Permission(grant)], True)
        self.prefs.allow_execute_python = self.prefs.allow_delete_objects = self.prefs.allow_save_project = False
        self.approved = self.folder / "approved GLB source"
        self.approved.mkdir(mode=0o700)
        self.source = self.approved / "literal.glb"
        self.source.write_bytes(literal_source())
        self.prefs.asset_source_directory = str(self.approved)
        self.destination = bpy.context.scene
        self.destination_name = self.destination.name
        self.destination.unit_settings.scale_length = 1.
        self.sentinel_mesh = bpy.data.meshes.new("Runtime Protected Mesh")
        self.sentinel_mesh.from_pydata(((8., 0., 0.), (9., 0., 0.), (8., 1., 0.)), (), ((0, 1, 2),))
        self.sentinel_material = bpy.data.materials.new("Runtime Protected Material")
        self.sentinel_material.use_nodes = True
        self.sentinel_mesh.materials.append(self.sentinel_material)
        uv = self.sentinel_mesh.uv_layers.new(name="Runtime Protected UV")
        self.sentinel_mesh.attributes[uv.name].data.foreach_set("vector", (0., 0., 1., 0., 0., 1.))
        self.sentinel = bpy.data.objects.new("Runtime Protected Object", self.sentinel_mesh)
        self.destination.collection.objects.link(self.sentinel)
        self.rig = bpy.data.armatures.new("Runtime Protected Rig")
        self.rig_object = bpy.data.objects.new("Runtime Protected Rig Object", self.rig)
        self.destination.collection.objects.link(self.rig_object)
        self.action = bpy.data.actions.new("Runtime Protected Action")
        self.sentinel.animation_data_create().action = self.action
        self.sentinel.parent = self.rig_object
        self.sentinel_shared = bpy.data.objects.new("Runtime Protected Shared Object", self.sentinel_mesh)
        self.destination.collection.objects.link(self.sentinel_shared)
        self.sentinel_shared.parent = self.rig_object
        for owner, name in ((self.sentinel, "Runtime Protected Group"), (self.sentinel_shared, "Runtime Shared Group")):
            group = owner.vertex_groups.new(name=name)
            if owner is self.sentinel:
                group.add([0], .25, "REPLACE")
                group.add([1, 2], .75, "REPLACE")
        selected, active = tuple(bpy.context.selected_objects), bpy.context.view_layer.objects.active
        for obj in selected:
            obj.select_set(False)
        self.rig_object.select_set(True)
        bpy.context.view_layer.objects.active = self.rig_object
        assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
        root_bone = self.rig.edit_bones.new("Runtime Protected Root")
        root_bone.head, root_bone.tail = (0., 0., 0.), (0., 0., 1.)
        child_bone = self.rig.edit_bones.new("Runtime Protected Child")
        child_bone.head, child_bone.tail = (0., 0., 1.), (0., 0., 2.)
        child_bone.parent = root_bone
        assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}
        self.rig_object.select_set(False)
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active
        slot = self.action.slots.new("OBJECT", self.sentinel.name)
        strip = self.action.layers.new("Runtime Protected Layer").strips.new(type="KEYFRAME")
        curve = strip.channelbag(slot, ensure=True).fcurves.new(data_path="location", index=0)
        curve.keyframe_points.add(2)
        for point, coordinate in zip(curve.keyframe_points, ((1., .125), (2., .25)), strict=True):
            point.co = coordinate
        curve.update()
        self.sentinel.animation_data.action_slot = slot
        self.raw_collisions = {}
        for kind, suffix in (("collection", ""), ("mesh", ".M0"), ("material", ".P0"), ("object", ".O0")):
            name = "Runtime Collision "+kind+suffix
            family = getattr(bpy.data, {"collection": "collections", "mesh": "meshes", "material": "materials", "object": "objects"}[kind])
            value = family.new(name, None) if kind == "object" else family.new(name)
            if kind == "mesh":
                value.from_pydata(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (), ((0, 1, 2),))
            self.raw_collisions[kind] = value
        self.other_scenes = {kind: bpy.data.scenes.new("Runtime Fixture "+kind) for kind in ("scene_identity", "master_identity", "context")}
        self.other_collection = bpy.data.collections.new("Runtime Fixture Child Drift")
        self.populated_scene = bpy.data.scenes.new("Runtime Protected Second Scene")
        self.populated_scene.collection.objects.link(self.sentinel_shared)
        self.populated_scene.world, self.populated_scene.camera = self.destination.world, self.destination.camera
        self.active_empty = bpy.data.objects.new("Runtime Fixture Plain Active Empty", None)
        self.destination.collection.objects.link(self.active_empty)
        self.active_empty.select_set(True)
        bpy.context.view_layer.objects.active = self.active_empty
        # Complete synthetic FILE image, packed from its exact original bytes.
        # This raw fixture source is independent of the GLB's unsupported images.
        import struct
        import zlib
        def chunk(kind, raw):
            return struct.pack(">I", len(raw))+kind+raw+struct.pack(">I", zlib.crc32(kind+raw) & 0xffffffff)
        pixels = bytes((255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255))
        png = b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress(b"\0"+pixels[:8]+b"\0"+pixels[8:]))+chunk(b"IEND", b"")
        image_path = self.folder/"protected-literal.png"
        image_path.write_bytes(png)
        self.protected_image = bpy.data.images.load(str(image_path), check_existing=False)
        self.protected_image.name = "Runtime Protected Packed Image"
        self.protected_image.colorspace_settings.name = "Non-Color"
        self.protected_image.pack()
        image_node = self.sentinel_material.node_tree.nodes.new("ShaderNodeTexImage")
        image_node.image = self.protected_image
        self.sentinel_material.node_tree.links.new(image_node.outputs["Color"],
            next(node for node in self.sentinel_material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled").inputs["Base Color"])
        for value in (*self.raw_collisions.values(), self.action):
            value.use_fake_user = True
        bpy.context.view_layer.update()
        self.populated_scene.view_layers[0].update()
        # Detached physical headers precede the FIRST protected geometry/data
        # observation. 5.2 SINGLE must first fail through real preview TCP;
        # separately authorized raw preparation then establishes a NEW baseline.
        self.protected_ids = {family: tuple(getattr(bpy.data, family)) for family in
            ("objects", "meshes", "materials", "armatures", "actions", "scenes", "images", "cameras", "lights", "worlds", "collections")}
        self.protected_names = {family: [value.name for value in values] for family, values in self.protected_ids.items()}
        self.fixture_names = {field: getattr(self, field).name for field in
            ("destination", "sentinel_mesh", "sentinel_material", "sentinel", "sentinel_shared", "rig", "rig_object",
             "action", "populated_scene", "active_empty", "protected_image", "other_collection")}
        self.fresh_observer()
        self.data["raw_setup"] = {"outside_bridge_boundary": True, "source_sha256": hashlib.sha256(literal_source()).hexdigest(),
            "fixture_authoring_edit_mesh_semantics": True, "untouched_startup_claim": False,
            "protected_header_inventory": self.protected_headers(), "protected_baseline": None,
            "deleted_existing_ids": [], "cleared_protected_data": False,
            "raw_packed_image_sha256": hashlib.sha256(png).hexdigest()}
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        threading.setprofile(self.profile)
        self.runtime.start_server("127.0.0.1", self.port, request_timeout=90)
        self.data["runtime"] = {"host": "127.0.0.1", "port": self.port, "registered": self.runtime._registered,
            "runtime_identity": id(self.runtime), "registry_identity": id(self.runtime.registry),
            "executor_identity": id(self.runtime.executor), "canonical_queue": self.runtime.server._submit == self.runtime.executor.submit,
            "main_thread_executor": self.runtime.executor._main_thread_id == threading.get_ident(),
            "process_id": os.getpid(), "process_instance": self.data["process_instance"],
            "source_sha256": self.data["source_sha256"]}
        self.data["runtime_groups"].append({"index": 0, "runtime": copy.deepcopy(self.data["runtime"]),
            "issued_at": time.monotonic(), "raw_owned_fixture_lifetime_setup": True, "prior": None})
        from blender_codex_bridge.glb_stage_driver import NativeOperations
        self.entry_code = NativeOperations._entry.__code__
        sys.setprofile(self.profile)
        self.flush()
        self.bpy.app.timers.register(self.supervise, first_interval=.001)
        threading.Thread(target=self.worker, name="GLBStageRuntimeTCPFixture", daemon=True).start()

    def profile(self, frame, event, _value):
        # All observations below use Python call/return frames. C events carry
        # no fixture evidence and must not pay thread/path dispatch per getter.
        if event not in ("call", "return"):
            return
        # Transport lifecycle objects are ordinary thread-safe Python events,
        # never bpy wrappers. The network-thread observer performs no bpy work.
        if event == "return" and frame.f_code.co_filename.replace("\\", "/").endswith("/blender_codex_bridge/server.py") and frame.f_code.co_name == "submit":
            request = frame.f_locals.get("request")
            if request is not None and request._lifecycle is not None:
                self.request_lifetimes[request.id] = request._lifecycle
        if threading.current_thread() is not threading.main_thread():
            return
        if event == "return" and frame.f_code.co_filename.replace("\\", "/").endswith("/blender_codex_bridge/glb_stage_driver.py") and frame.f_code.co_name == "_capture_mesh_return":
            receipt = frame.f_locals.get("receipt")
            if receipt is not None:
                self.receipts.setdefault(receipt.stage_id, []).append({"operation": receipt.operation,
                    "role": receipt.role, "body": copy.deepcopy(receipt.body), "body_sha256": receipt.body_sha256,
                    "stage_id": receipt.stage_id, "native_entry_index": frame.f_locals["self"]._entries[-1]["index"],
                    "scope": "PURE_CACHED_RETURN_FRAME_OBSERVATION"})

        # Observation of original code frames only: no replacement permission
        # manager, spec, handler, context factory or canonical scheduler.
        path = frame.f_code.co_filename.replace("\\", "/")
        if (event == "return" and path.endswith("/blender_codex_bridge/glb_stage_runtime.py") and frame.f_code.co_name == "attach_job"
                and type(_value) is dict and _value.get("accepted") is True):
            self.start_acceptances[_value["request_id"]] = {"result": {key: copy.deepcopy(_value[key]) for key in
                ("accepted", "job_completed", "request_id", "stage_id", "job_id")}, "at": time.monotonic(),
                "runtime_group": self.group_index, "request_id": _value["request_id"],
                "source_frame": "addon/blender_codex_bridge/glb_stage_runtime.py:attach_job"}
        if path.endswith("/blender_codex_bridge/executor.py") and frame.f_code.co_name == "_invoke_owned":
            request = frame.f_locals.get("request")
            if request is not None:
                if event == "call":
                    self.current_requests.append(request.id)
                elif event == "return" and self.current_requests and self.current_requests[-1] == request.id:
                    self.current_requests.pop()
        if event == "call" and self.current_requests and path.endswith("/blender_codex_bridge/glb_stage_protected_mesh.py") and frame.f_code.co_name == "enter":
            cell = frame.f_locals.get("cell")
            if type(cell) is dict:
                self.request_read_effects.setdefault(self.current_requests[-1], []).append(copy.deepcopy(cell))
        if event == "call" and self.current_requests and path.endswith("/blender_codex_bridge/checkpoints.py") and frame.f_code.co_name == "capture_job_markers":
            key = self.current_requests[-1]
            self.marker_entries[key] = self.marker_entries.get(key, 0)+1
        if event == "return" and path.endswith("/blender_codex_bridge/glb_stage_profile.py") and frame.f_code.co_name == "_access":
            binding = frame.f_locals.get("self")
            if self.current_requests and binding is not None:
                gate = getattr(binding, "_runtime_gate", None)
                if gate is not None:
                    self.request_access[self.current_requests[-1]] = gate.snapshot()
        if event == "call" and path.endswith("/blender_codex_bridge/glb_stage_jobs.py") and frame.f_code.co_name == "check":
            caller = frame.f_back
            if caller is not None and caller.f_code is self.entry_code:
                self.observe_post_return(caller)
        if event == "return" and path.endswith("/blender_codex_bridge/glb_stage_jobs.py") and frame.f_code.co_name == "advance":
            driver = frame.f_locals.get("self")
            if driver is not None:
                watch = self.boundaries.get(driver.stage_id)
                if watch is not None and driver.phase == watch["phase"]:
                    watch["observed_at"] = time.monotonic()
                    watch["event"].set()
        if event == "return" and path.endswith("/blender_codex_bridge/executor.py") and frame.f_code.co_name == "_invoke_owned":
            values = frame.f_locals
            request = values.get("request")
            if request is not None:
                history = values.get("history_record")
                accepted_return = request.method in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start"} and type(_value) is dict and _value.get("accepted") is True
                attached = self.start_acceptances.get(request.id)
                self.histories[request.id] = {"request_id": request.id, "method": request.method,
                    "checkpoint_entered": values.get("undo_boundary") is True,
                    "handler_entered": values.get("handler_entered") is True,
                    "raw_history": None if history is None else history.to_dict(),
                    "returned_at": time.monotonic(),
                    "accepted_result": copy.deepcopy(_value) if accepted_return else None if attached is None else copy.deepcopy(attached["result"]),
                    "accepted_at": None if attached is None else attached["at"],
                    "accepted_runtime_group": None if attached is None else attached["runtime_group"],
                    "accepted_result_source": "addon/blender_codex_bridge/executor.py:_invoke_owned" if accepted_return else None if attached is None else attached["source_frame"],
                    "source_frame": "addon/blender_codex_bridge/executor.py:_invoke_owned"}
                self.data["executor_history_frames"].append(copy.deepcopy(self.histories[request.id]))
        watch = self.watch
        if watch is not None and event == "call" and not watch.get("entered"):
            kind = watch["kind"]
            matches = ((kind == "provider" and path.endswith("/blender_codex_bridge/permissions.py") and frame.f_code.co_name == "permission_snapshot") or
                (kind == "checkpoint" and path.endswith("/blender_codex_bridge/checkpoints.py") and frame.f_code.co_name in {"claim_pending", "begin_owned", "_stamp"}) or
                (kind in {"handler", "finalizer"} and path.endswith("/blender_codex_bridge/tools/glb_stage.py")))
            if matches:
                watch["entered"] = True
                from blender_codex_bridge.protocol import Request
                def nested():
                    response = self.runtime.executor.execute_request(Request(id="nested_"+os.urandom(16).hex(),
                        method="asset.glb_stage_create_start", params=watch["params"]))
                    raw_response = response.to_dict()
                    assert raw_response["ok"] is False and raw_response["error"]["context"]["reason"] in {"REENTRANT_MUTATION_BLOCKED", "SCENE_JOB_RESERVATION_BLOCKED"}
                    self.nested_probes.append({"kind": kind, "scope": "TRUSTED_NESTED_EXECUTOR_ONLY",
                        "outer_request_id": watch["outer_request_id"], "boundary": [path, frame.f_code.co_name],
                        "response": raw_response, "canonical_slot_count": int(self.runtime.jobs.active is not None),
                        "nested_grant_entries": 0, "nested_checkpoint_entries": 0, "nested_native_entries": 0,
                        "counter_derivation": "SEALED_INTERLOCK_REJECTION_BEFORE_ADMISSION"})
                if kind == "finalizer":
                    class Probe:
                        def __del__(self):
                            nested()
                    probe = Probe()
                    del probe
                else:
                    nested()

    def new_lifetime(self):
        """Explicit owned-fixture unregister/new canonical singleton boundary.

        Old records and Runtime objects remain retained. No Main ID is deleted,
        adopted, purged or restored, and no production reset API is introduced.
        """
        import blender_codex_bridge.runtime as module
        old = self.runtime
        assert module._RUNTIME is old and old._registered
        before = self.raw_snapshot()
        identities_before = self.identities()
        old_records = [old.glb_stage.store.inspect(identifier) for identifier in old.glb_stage.store._records]
        old_native = {identifier: old.glb_stage._records[identifier].operations.report()
                      for identifier in old.glb_stage._records}
        old.unregister()
        old.stop_server()
        assert old._registered is False and not old.server.running
        stale = [old.glb_stage.store.inspect(identifier) for identifier in old.glb_stage.store._records]
        assert len(stale) == len(old_records) and all(row["phase"] == "STALE" for row in stale)
        assert all(old.glb_stage._records[identifier].operations.report()["native_entries"] == report["native_entries"]
                   for identifier, report in old_native.items())
        ledger = {"index": self.group_index, "runtime_identity": id(old), "registered": old._registered,
            "records_before": old_records, "records_after_unregister": stale, "native_evidence": old_native,
            "native_evidence_after_unregister": {identifier: old.glb_stage._records[identifier].operations.report()
                for identifier in old.glb_stage._records},
            "retained_runtime_object": True, "record_evictions": [], "native_cleanup": False,
            "identities_before": identities_before, "identities_after": self.identities()}
        assert ledger["identities_before"] == ledger["identities_after"]
        self.retired_runtimes.append(old)
        self.data["retired_runtime_ledgers"].append(ledger)
        module._RUNTIME = None  # Root-authorized raw fixture lifetime setup only.
        fresh = module.get_runtime()
        assert fresh is module._RUNTIME and fresh is not old
        fresh.register()
        fresh.start_server("127.0.0.1", self.port, request_timeout=90)
        assert not fresh.glb_stage.store._records and not fresh.glb_stage._records
        self.runtime = fresh
        self.group_index += 1
        runtime = {**self.data["runtime"], "registered": fresh._registered,
            "runtime_identity": id(fresh), "registry_identity": id(fresh.registry), "executor_identity": id(fresh.executor),
            "canonical_queue": fresh.server._submit == fresh.executor.submit,
            "main_thread_executor": fresh.executor._main_thread_id == threading.get_ident()}
        after = self.raw_snapshot()
        ledger.update(artist_main_before=before, artist_main_after=after)
        assert logical_snapshot(after) == logical_snapshot(before), "Runtime lifetime setup changed the declared artist Main/context"
        self.data["runtime_groups"].append({"index": self.group_index, "runtime": runtime,
            "issued_at": time.monotonic(), "raw_owned_fixture_lifetime_setup": True,
            "prior": {"ledger_index": len(self.data["retired_runtime_ledgers"])-1,
                "old_runtime_identity": id(old), "old_registered": False,
                "old_stage_ids": [row["stage_id"] for row in stale], "artist_main_preserved": True}})
        return {"index": self.group_index, "old_stage_ids": [row["stage_id"] for row in stale],
                "new_runtime_identity": id(fresh)}

    def arm_disconnect(self, params):
        stage_id = params["stage_id"]
        retained = self.runtime.glb_stage.retained(stage_id)
        watch = {"stage_id": stage_id, "entry": params["entry"], "notify": threading.Event(),
            "connection": retained.connection, "close_done": threading.Event(), "notified_at": None,
            "network_ack_at": None, "entry_index": None, "returned_monotonic": None,
            "source_boundary": "RUNTIME_NATIVE_GATE_CALL_AFTER_RECORDED_C_RETURN",
            "maximum_rendezvous_seconds": 1., "actual_owner_tcp_close": False,
            "network_disconnected_event_ack": False, "main_rpc_wait": False, "close_receipt": [],
            "connection_identity": id(retained.connection), "runtime_group": self.group_index,
            "synthetic_cancel": False, "fabricated_c_failure": False, "genuine_return_escrow_roles": []}
        self.disconnect_watch = watch
        return {"notify": watch["notify"], "close_done": watch["close_done"], "close_receipt": watch["close_receipt"]}

    def observe_post_return(self, frame):
        """Observe the FIRST pure stop call after a genuine recorded C return."""
        watch = self.disconnect_watch
        if watch is None or watch["notified_at"] is not None:
            return
        values = frame.f_locals
        row = values.get("row")
        if (type(row) is not dict or values.get("label") != watch["entry"] or row.get("returned") is not True
                or row.get("returned_monotonic") is None or row.get("post_return_stop_checked") is not False):
            return
        operations = values.get("self")
        stage = None if operations is None else operations._stage
        if stage is None or stage.intent.stage_id != watch["stage_id"]:
            return
        assert "result" in values, "No genuine native return at the requested source boundary"
        from blender_codex_bridge.glb_stage_driver import _NO_RETURN
        watch.update(notified_at=time.monotonic(), entry_index=row["index"],
            returned_monotonic=row["returned_monotonic"], started_monotonic=row["started_monotonic"],
            stopped_request_id=self.current_requests[-1] if self.current_requests else None,
            native_access_counts_at_return=operations._runtime_gate.snapshot(),
            genuine_return_escrow_roles=[] if operations._pending is None else
                [role for role, value in operations._pending.references.items() if value is not _NO_RETURN])
        watch["notify"].set()
        # The worker performs an actual owner socket close. These are ordinary
        # Events, with no Main RPC/Blender work required for either completion.
        bound = watch["maximum_rendezvous_seconds"]
        closed = watch["close_done"].wait(bound)
        remaining = max(0., bound-(time.monotonic()-watch["notified_at"]))
        observed = closed and watch["connection"].disconnected.wait(remaining)
        watch["network_ack_at"] = time.monotonic()
        watch["network_disconnected_event_ack"] = observed and watch["connection"].disconnected.is_set()
        watch["actual_owner_tcp_close"] = closed
        assert watch["network_disconnected_event_ack"] and closed, "Missed actual post-return owner disconnect/ACK boundary"
        assert watch["network_ack_at"]-watch["notified_at"] <= bound, "Post-return rendezvous exceeded its declared bound"

    def fresh_observer(self):
        from blender_codex_bridge.glb_stage_profile import NativeBinding
        from blender_codex_bridge.glb_stage_protected_mesh import ProtectedMeshObserver
        self.raw_binding = NativeBinding()
        assert self.raw_binding._runtime_gate is None
        self.raw_observer = ProtectedMeshObserver(self.raw_binding)

    def reacquire_after_invalidation(self):
        """Discard every raw fixture RNA wrapper before a post-undo/load read."""
        bpy = self.bpy
        self.protected_ids = {family: tuple(getattr(bpy.data, family)[name] for name in names)
            for family, names in self.protected_names.items()}
        families = {"destination": "scenes", "sentinel_mesh": "meshes", "sentinel_material": "materials",
            "sentinel": "objects", "sentinel_shared": "objects", "rig": "armatures", "rig_object": "objects",
            "action": "actions", "populated_scene": "scenes", "active_empty": "objects",
            "protected_image": "images", "other_collection": "collections"}
        for field, family in families.items():
            setattr(self, field, getattr(bpy.data, family)[self.fixture_names[field]])
        self.other_scenes = {kind: bpy.data.scenes["Runtime Fixture "+kind] for kind in ("scene_identity", "master_identity", "context")}
        self.raw_collisions = {kind: getattr(bpy.data, family)["Runtime Collision "+kind+suffix]
            for kind, family, suffix in (("collection", "collections", ""), ("mesh", "meshes", ".M0"),
                ("material", "materials", ".P0"), ("object", "objects", ".O0"))}
        self.prefs = bpy.context.preferences.addons["blender_codex_bridge"].preferences
        self.fresh_observer()

    def storage_meshes(self, mesh_target=None):
        if mesh_target is None:
            return self.protected_ids["meshes"]
        assert type(mesh_target) is dict and set(mesh_target) == {"name", "uid"}
        mesh = self.bpy.data.meshes[mesh_target["name"]]
        assert mesh.session_uid == mesh_target["uid"]
        return (mesh,)

    def protected_headers(self, mesh_target=None):
        if not hasattr(self, "raw_observer"):
            self.fresh_observer()
        return [self.raw_observer.capture_headers(mesh) for mesh in self.storage_meshes(mesh_target)]

    def prepare_storage(self, refusal_request_id, mesh_target=None):
        """Root-authorized raw fixture EditMesh preparation, never a Bridge API."""
        from blender_codex_bridge.glb_stage_protected_mesh import _Access
        started = time.monotonic()
        before = self.protected_headers(mesh_target)
        refusal = next(row for row in self.data["single_storage_refusals"] if row["request_id"] == refusal_request_id)
        request = next(row for row in self.data["tcp"] if row["request"]["id"] == refusal_request_id)
        assert refusal["runtime_group"] == self.group_index and refusal["mesh_target"] == mesh_target and refusal["headers"] == before
        assert request["runtime_group"] == self.group_index and request["request"]["method"] == "asset.glb_stage_preview"
        assert request["delivered"] and request["response"]["ok"] is False and request["response"]["error"] == refusal["error"]
        assert request["received_at"] <= refusal["recorded_at"] <= started
        assert not any(row["refusal_request_id"] == refusal_request_id for row in self.data["raw_storage_preparations"])
        allowed = {"BOOLEAN", "FLOAT2", "INT", "FLOAT_VECTOR"}
        pending = [(mesh, headers, row) for mesh, headers in zip(self.storage_meshes(mesh_target), before, strict=True)
                   for row in headers["attributes"] if row["storage"] == "SINGLE"]
        # Reject the WHOLE proposed conversion set before its first data getter.
        assert all(row["supported"] is True for headers in before for row in headers["attributes"]) and all(row["data_type"] in allowed and row["supported"] is True for _mesh, _headers, row in pending), "Raw fixture preparation refuses scalar FLOAT/unknown/unsupported SINGLE before conversion"
        actions = []
        expected = {headers["identity"]["uid"]: copy.deepcopy(headers) for headers in before}
        for mesh, _headers, original in pending:
            current = self.raw_observer.capture_headers(mesh)
            uid = current["identity"]["uid"]
            assert current == expected[uid], "Fixture preparation inventory changed before data access"
            row = next(item for item in current["attributes"] if item["name"] == original["name"])
            assert row["storage"] == "SINGLE" and row["data_type"] in allowed
            access = _Access(self.raw_observer)
            attribute = access.attribute(mesh, row)
            # This is the explicitly authorized mutating getter. No geometry,
            # values, groups, legacy UV data or stale leaf is touched first.
            access.get(attribute, "data")
            del attribute, access
            after = self.raw_observer.capture_headers(mesh)
            target = next(item for item in after["attributes"] if item["name"] == row["name"])
            assert target["storage"] == "ARRAY"
            permitted = copy.deepcopy(current)
            next(item for item in permitted["attributes"] if item["name"] == row["name"])["storage"] = "ARRAY"
            assert after == permitted, "Fixture preparation changed physical schema/roles/identity beyond the one storage transition"
            expected[uid] = copy.deepcopy(after)
            actions.append({"mesh_identity": current["identity"], "attribute": row["name"], "data_type": row["data_type"],
                "before_header": row, "after_header": target, "native_action": "QUALIFIED_GENERIC_ATTRIBUTE_DATA_MATERIALIZATION",
                "authoring_scope": "RAW_OWNED_FIXTURE_EDIT_MESH", "pre_single_value_sha256": None,
                "bit_preservation_basis": "PINNED_SOURCE_EQUIVALENCE_NOT_EMPIRICAL_PRE_SINGLE_READ",
                "known_fixture_oracles_required_after_readback": True, "production_preparation_api": False})
        after = self.protected_headers(mesh_target)
        assert all(row["storage"] != "SINGLE" for headers in after for row in headers["attributes"])
        readback = []
        affected = {headers["identity"]["uid"] for _mesh, headers, _row in pending}
        for mesh in self.storage_meshes(mesh_target):
            if mesh.session_uid in affected:
                row, projection = self.mesh_observation(mesh)
                readback.append({"mesh_uid": mesh.session_uid, "headers": self.raw_observer.capture_headers(mesh),
                    "logical_projection": row["logical_projection"], "authored_sha256": projection["authored_sha256"], "row": row})
        record = {"scope": "RAW_OWNED_FIXTURE_PREPARATION_NOT_BRIDGE_API", "before_headers": before,
            "runtime_group": self.group_index, "mesh_target": mesh_target, "refusal_request_id": refusal_request_id,
            "started_at": started, "post_readback": readback, "finished_at": time.monotonic(),
            "after_headers": after, "actions": actions, "already_array_noops": sum(row["storage"] in {"ARRAY", "LEGACY_ARRAY"} for headers in before for row in headers["attributes"]),
            "scalar_float_or_unknown_conversion": False, "logical_values_reset": False,
            "record_evictions": [], "native_qualified": False}
        self.data.setdefault("raw_storage_preparations", []).append(record)
        self.data["protected_observer_gate"] = "SOURCE_QUALIFIED_LOGICAL_ARRAY_READER_NATIVE_ACCEPTANCE_PENDING"
        return record

    def mesh_observation(self, mesh):
        from blender_codex_bridge.glb_stage_protected_mesh import logical_projection

        from scripts.blender_glb_stage_smoke import header, numeric
        projection = self.raw_observer.capture_mesh(mesh)
        geometry = projection["geometry"]
        attributes = {row["name"]: {"domain": row["domain"], "type": row["data_type"],
            "values": projection["attribute_values"][row["name"]]} for row in projection["attributes"]}
        row = {"identity": header(mesh), "coordinates": [item["co"] for item in geometry["vertices"]],
            "corners": [[item["vertex_index"], item["edge_index"]] for item in geometry["loops"]],
            "faces": [[item["loop_start"], item["loop_total"], item["vertices"], item["material_index"], item["use_smooth"]]
                for item in geometry["polygons"]], "edges": sorted(sorted(item["vertices"]) for item in geometry["edges"]),
            "materials": projection["materials"], "attributes": attributes,
            "logical_projection": logical_projection(projection), "uv_roles": projection["uv_roles"],
            "uv_layers_complete": projection["uv_layers"], "memberships": [item["groups"] for item in geometry["vertices"]]}
        self.data.setdefault("raw_observation_read_effects", []).append({"scope": "TRUSTED_RAW_FIXTURE_OBSERVER_NOT_RUNTIME_AUTHORITY",
            "mesh_uid": projection["identity"]["uid"], "at": time.monotonic(), "read_effects": projection["read_effects"],
            "mesh_profile": copy.deepcopy({key: projection[key] for key in ("identity", "counts", "attributes")}),
            "runtime_gate_bound": projection["runtime_gate_bound"], "native_qualified": False})
        # Independent literal numerical/role oracle, separate from the copier.
        if mesh is self.sentinel_mesh:
            assert row["coordinates"] == [numeric(value) for value in ((8., 0., 0.), (9., 0., 0.), (8., 1., 0.))]
            assert [item[0] for item in row["corners"]] == [0, 1, 2]
            assert row["faces"][0][:4] == [0, 3, [0, 1, 2], 0]
            assert attributes["Runtime Protected UV"]["values"] == [numeric(value) for value in ((0., 0.), (1., 0.), (0., 1.))]
        return row, projection

    def attributes(self, mesh):
        from scripts.blender_glb_stage_smoke import numeric
        result = {}
        kinds = {"FLOAT_VECTOR": ("vector", True), "FLOAT2": ("vector", True),
                 "INT32_2D": ("value", False), "INT16_2D": ("value", False),
                 "INT": ("value", False), "BOOLEAN": ("value", False), "FLOAT": ("value", True)}
        assert len(mesh.attributes) <= 32
        for attribute in mesh.attributes:
            field, floating = kinds[attribute.data_type]
            values = []
            for item in attribute.data:
                value = getattr(item, field)
                if hasattr(value, "__len__"):
                    value = numeric(value) if floating else list(value)
                elif floating:
                    value = numeric((value,))[0]
                values.append(value)
            result[attribute.name] = {"domain": attribute.domain, "type": attribute.data_type, "values": values}
        return result

    def raw_snapshot(self, allocations=None):
        from scripts.blender_glb_stage_smoke import (
            header,
            material_row,
            numeric,
            structure_object_row,
            tree_row,
        )
        bpy = self.bpy
        protected = {}
        for family, refs in self.protected_ids.items():
            rows = []
            for value in refs:
                if family == "objects":
                    row = structure_object_row(value)
                    row.update(hide_viewport=value.hide_viewport, hide_render=value.hide_render,
                               display_type=value.display_type, color=numeric(value.color))
                    if value.type == "MESH":
                        projection = self.raw_observer.capture_mesh(value.data)
                        groups = self.raw_observer.capture_object_groups(value, projection)
                        row.update(vertex_group_definitions=groups["groups"], memberships=groups["memberships"])
                        if value in (self.sentinel, self.sentinel_shared):
                            assert_shared_group_fixture(groups)
                    elif value.type == "ARMATURE":
                        row["pose_bones"] = [{"name": bone.name, "location": numeric(bone.location),
                            "rotation_mode": bone.rotation_mode, "euler": numeric(bone.rotation_euler),
                            "quaternion": numeric(bone.rotation_quaternion), "axis_angle": numeric(bone.rotation_axis_angle),
                            "scale": numeric(bone.scale), "basis": numeric(v for line in bone.matrix_basis for v in line),
                            "matrix": numeric(v for line in bone.matrix for v in line),
                            "constraints": [[constraint.name, constraint.type] for constraint in bone.constraints]} for bone in value.pose.bones]
                elif family == "meshes":
                    row, _projection = self.mesh_observation(value)
                elif family == "materials":
                    row = material_row(value)
                    row["image_consumers"] = [] if value.node_tree is None else [[node.name,
                        None if node.image is None else node.image.session_uid, node.interpolation, node.projection, node.extension]
                        for node in value.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]
                elif family == "armatures":
                    row = {"identity": header(value), "bones": [{"name": bone.name,
                        "parent": None if bone.parent is None else bone.parent.name,
                        "head": numeric(bone.head_local), "tail": numeric(bone.tail_local),
                        "matrix": numeric(v for line in bone.matrix_local for v in line)} for bone in value.bones]}
                elif family == "actions":
                    row = {"identity": header(value), "slots": [[slot.identifier, slot.handle, slot.target_id_type] for slot in value.slots],
                        "layers": [{"name": layer.name, "strips": [{"type": strip.type,
                            "channelbags": [{"slot_handle": bag.slot_handle, "curves": [{"path": curve.data_path,
                                "array_index": curve.array_index, "extrapolation": curve.extrapolation,
                                "keys": [{"co": numeric(point.co), "left": numeric(point.handle_left),
                                    "right": numeric(point.handle_right), "interpolation": point.interpolation,
                                    "left_type": point.handle_left_type, "right_type": point.handle_right_type} for point in curve.keyframe_points]}
                                for curve in bag.fcurves]} for bag in strip.channelbags]} for strip in layer.strips]} for layer in value.layers]}
                elif family == "scenes":
                    row = {"identity": header(value), "unit_settings": [value.unit_settings.system, value.unit_settings.scale_length, value.unit_settings.length_unit],
                        "frame": [value.frame_current, value.frame_subframe], "range": [value.frame_start, value.frame_end],
                        "fps": [value.render.fps, value.render.fps_base],
                        "world_uid": None if value.world is None else value.world.session_uid,
                        "camera_uid": None if value.camera is None else value.camera.session_uid,
                        "root_objects": sorted(obj.session_uid for obj in value.collection.objects),
                        "root_children": sorted(child.session_uid for child in value.collection.children),
                        "view_layers": [{"name": layer.name, "use": layer.use,
                            "objects": sorted(obj.session_uid for obj in layer.objects),
                            "active": None if layer.objects.active is None else layer.objects.active.session_uid,
                            "selected": sorted(obj.session_uid for obj in layer.objects if obj.select_get(view_layer=layer))}
                            for layer in value.view_layers]}
                elif family == "images":
                    row = {"identity": header(value), "source": value.source, "type": value.type, "has_data": value.has_data}
                    if value.type in {"RENDER_RESULT", "COMPOSITING"} and value.source == "VIEWER" and not value.has_data:
                        row["empty_viewer"] = True
                    else:
                        row.update(size=list(value.size), channels=value.channels, is_float=value.is_float, is_dirty=value.is_dirty,
                            colorspace=value.colorspace_settings.name, alpha_mode=value.alpha_mode, filepath=value.filepath,
                            pixels=numeric(value.pixels) if value.has_data else None,
                            packed_sha256=None if value.packed_file is None else hashlib.sha256(bytes(value.packed_file.data)).hexdigest())
                        if value is self.protected_image:
                            expected = (0., 0., 1., 1., 1., 1., 1., 1., 1., 0., 0., 1., 0., 1., 0., 1.)
                            assert row["pixels"] == numeric(expected) and row["colorspace"] == "Non-Color"
                elif family == "cameras":
                    row = {"identity": header(value), "type": value.type,
                        **{field: getattr(value, field) for field in ("lens", "clip_start", "clip_end", "sensor_width", "sensor_height", "ortho_scale", "shift_x", "shift_y")},
                        "dof": [value.dof.use_dof, value.dof.focus_distance, None if value.dof.focus_object is None else value.dof.focus_object.session_uid]}
                elif family == "lights":
                    row = {"identity": header(value), "type": value.type, "energy": value.energy, "color": numeric(value.color),
                        "use_shadow": value.use_shadow, "cutoff_distance": value.cutoff_distance}
                elif family == "worlds":
                    row = {"identity": header(value), "color": numeric(value.color), "use_nodes": value.use_nodes,
                        "tree": None if value.node_tree is None else tree_row(value.node_tree)}
                elif family == "collections":
                    row = {"identity": header(value), "children": sorted(child.session_uid for child in value.children),
                        "objects": sorted(obj.session_uid for obj in value.objects), "hide_viewport": value.hide_viewport,
                        "hide_render": value.hide_render, "color_tag": value.color_tag}
                else:
                    raise AssertionError(("Unobserved protected family", family))
                rows.append(row)
            protected[family] = rows
        context = {"scene": bpy.context.scene.session_uid, "view_layer": bpy.context.view_layer.name,
            "active": None if bpy.context.view_layer.objects.active is None else bpy.context.view_layer.objects.active.session_uid,
            "selected": sorted(v.session_uid for v in bpy.context.selected_objects), "mode": bpy.context.mode,
            "areas": [[area.as_pointer(), area.type, area.ui_type] for area in bpy.context.screen.areas],
            "filepath": bpy.data.filepath}
        edges = sorted([scene.session_uid, child.session_uid] for scene in bpy.data.scenes for child in scene.collection.children)
        owned = {} if not allocations else self.raw_owned(allocations)
        return {"protected": protected, "context": context, "scene_edges": edges, "owned": owned}

    def owned_mesh_observation(self, mesh):
        from scripts.blender_glb_stage_smoke import numeric
        row, projection = self.mesh_observation(mesh)
        uv = None
        roles = projection["uv_roles"]
        if roles["layers"]:
            layer = mesh.uv_layers[0]
            clone, stencil = mesh.uv_layer_clone, mesh.uv_layer_stencil
            uv = {"name": layer.name, "vectors": projection["attribute_values"][layer.name],
                "active": roles["active_index"], "render": next((index for index, item in enumerate(roles["layers"]) if item["active_render"]), None),
                "clone": roles["clone_index"], "stencil": roles["stencil_index"],
                "clone_bound": clone is not None, "stencil_bound": stencil is not None,
                "clone_pointer": None if clone is None else clone.as_pointer(),
                "stencil_pointer": None if stencil is None else stencil.as_pointer(), "layer_pointer": layer.as_pointer(),
                "active_flag": layer.active, "render_flag": layer.active_render, "clone_flag": layer.active_clone}
        row.update(uv=uv, has_custom_normals=mesh.has_custom_normals,
            decoded_normals=None if not mesh.has_custom_normals else [numeric(item.vector) for item in mesh.corner_normals])
        self.data.setdefault("raw_observation_read_effects", []).append({"scope": "TRUSTED_RAW_NEW_OWNED_NORMAL_CACHE_OBSERVATION",
            "mesh_uid": row["identity"]["uid"], "at": time.monotonic(),
            "allowed_effects": ["BIT_PRESERVING_ARRAY_COW_UNSHARE", "CORNER_NORMAL_CACHE_TAG_OR_MATERIALIZATION"],
            "native_qualified": False})
        return row

    def raw_owned(self, allocations):
        from scripts.blender_glb_stage_smoke import (
            header,
            material_row,
            structure_object_row,
            tree_row,
        )
        rows, refs = {}, {}
        families = {"collection": "collections", "mesh": "meshes", "material": "materials", "object": "objects"}
        for item in allocations:
            role = item["role"]
            if role.startswith("node_tree:"):
                continue
            value = getattr(self.bpy.data, families[role.split(":")[0]]).get(item["name"])
            assert value is not None and value.session_uid == item["native_uid"] and value.as_pointer() == item["pointer"]
            refs[role] = value
        for role, value in refs.items():
            if role == "collection":
                row = {"identity": header(value), "children": sorted(v.session_uid for v in value.children),
                    "objects": sorted(v.session_uid for v in value.objects)}
            elif role.startswith("mesh:"):
                row = self.owned_mesh_observation(value)
            elif role.startswith("object:"):
                row = structure_object_row(value)
            else:
                row = material_row(value)
            rows[role] = row
        for item in allocations:
            if item["role"].startswith("node_tree:"):
                material = refs["material:"+item["role"].split(":")[1]]
                value = material.node_tree
                assert value.session_uid == item["native_uid"] and value.as_pointer() == item["pointer"]
                rows[item["role"]] = tree_row(value)
        return rows

    def identities(self):
        from scripts.blender_glb_stage_smoke import header
        properties = self.bpy.data.bl_rna.properties
        assert len(properties) <= 128
        families = sorted(prop.identifier for prop in properties if prop.type == "COLLECTION")
        assert self.data.setdefault("main_id_families", families) == families
        rows = []
        for family in families:
            collection = getattr(self.bpy.data, family)
            assert len(collection) <= 4096 and len(rows)+len(collection) <= 4096
            for value in collection:
                observed = header(value)
                rows.append([family, observed["uid"], observed["pointer"], observed["name"], observed["users"], observed["fake_user"], observed["class"]])
        return sorted(rows)

    def control(self, action, **params):
        event, result = threading.Event(), []
        self.controls.put((action, params, event, result))
        assert event.wait(90), ("Main-thread fixture control timeout", action)
        assert result[0], result[1]
        return result[1]

    def apply(self, action, params):
        assert threading.current_thread() is threading.main_thread()
        self.data["raw_actions"].append({"action": action, "at": time.monotonic(), "outside_bridge_boundary": True})
        if action == "start_series":
            return self.start_series(params)
        if action == "storage_headers":
            return self.protected_headers(params.get("mesh_target"))
        if action == "prepare_storage":
            return self.prepare_storage(params["refusal_request_id"], params.get("mesh_target"))
        if action == "establish_baseline":
            self.raw_baseline = self.raw_snapshot()
            self.data["raw_setup"]["protected_baseline"] = self.raw_baseline
            for preparation in self.data["raw_storage_preparations"]:
                if preparation["runtime_group"] == self.group_index and preparation["mesh_target"] is None:
                    assert "baseline_after" not in preparation
                    preparation.update(baseline_after=copy.deepcopy(self.raw_baseline), baseline_observed_at=time.monotonic())
            self.data["protected_observer_const_read_qualified"] = False
            self.data["protected_observer_logical_profile_ready"] = True
            return self.raw_baseline
        if action == "new_lifetime":
            return self.new_lifetime()
        if action == "access_receipt":
            identifier = params["request_id"]
            return {"native_access_counts": copy.deepcopy(self.request_access.get(identifier, {})),
                    "protected_read_effect_attempts": copy.deepcopy(self.request_read_effects.get(identifier, [])),
                    "checkpoint_marker_entries": self.marker_entries.get(identifier, 0)}
        if action == "arm_disconnect":
            return self.arm_disconnect(params)
        if action == "disconnect_receipt":
            assert self.disconnect_watch is not None
            return {key: value for key, value in self.disconnect_watch.items()
                    if key not in {"notify", "connection", "close_done"}}
        if action == "persist":
            self.flush()
            return None
        if action == "source_fault":
            kind = params["kind"]
            def facts():
                info, parent = self.source.lstat(), self.source.parent.lstat()
                return {"root": self.prefs.asset_source_directory,
                    "file_identity": [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns],
                    "parent_identity": [parent.st_dev, parent.st_ino],
                    "sha256": hashlib.sha256(bounded_file(self.source)).hexdigest()}
            before_facts = facts()
            before = {"root": self.prefs.asset_source_directory, "source": bounded_file(self.source).hex()}
            if kind == "root_stale":
                self.prefs.asset_source_directory = str(self.folder)
            elif kind == "ancestry":
                moved = self.approved.with_name(self.approved.name+" retained original")
                self.approved.rename(moved)
                self.approved.mkdir(mode=0o700)
                self.source.write_bytes(bytes.fromhex(before["source"]))
                before["moved"] = str(moved)
            elif kind == "file_race":
                replacement = self.source.with_suffix(".replacement")
                replacement.write_bytes(bytes.fromhex(before["source"]))
                replacement.replace(self.source)
            else:
                value = bytearray(bytes.fromhex(before["source"]))
                value[-1] ^= 1
                self.source.write_bytes(value)
            self.source_fault_observation = {"kind": kind, "before": before_facts, "after": facts()}
            return before
        if action == "source_restore":
            before = params["mutation"]
            if "moved" in before:
                retained = self.approved.with_name(self.approved.name+" retained replacement")
                self.approved.rename(retained)
                Path(before["moved"]).rename(self.approved)
            else:
                self.source.write_bytes(bytes.fromhex(before["source"]))
            self.prefs.asset_source_directory = before["root"]
            self.source_fault_observation = None
            return None
        if action == "refusal_state":
            state = self.runtime.state.snapshot()
            result = {"scope": "RAW_OWNED_REFUSAL_BOUNDARY_OBSERVATION", "runtime_group": self.group_index,
                "observed_at": time.monotonic(), "request_params": copy.deepcopy(params["request_params"]),
                "permissions": self.runtime.permissions.snapshot(), "enabled_toolsets": sorted(self.runtime.registry.enabled_toolsets),
                "paused": state["paused"], "emergency_stopped": state["emergency_stopped"],
                "source_root": self.prefs.asset_source_directory,
                "active_job_id": None if self.runtime.jobs.active is None else self.runtime.jobs.active.job_id,
                "source_fault": copy.deepcopy(getattr(self, "source_fault_observation", None)),
                "destination_fault": copy.deepcopy(getattr(self, "destination_fault_observation", None))}
            if "filepath" in params["request_params"]:
                path = Path(params["request_params"]["filepath"])
                info = path.lstat()
                result["input_file"] = {"path": str(path), "mode": info.st_mode,
                    "sha256": hashlib.sha256(bounded_file(path)).hexdigest() if stat.S_ISREG(info.st_mode) else None}
            return result
        if action == "snapshot":
            return self.raw_snapshot(params.get("allocations"))
        if action == "identities":
            return self.identities()
        if action == "escrow_identities":
            stage_id = params["stage_id"]
            stage = self.runtime.glb_stage.retained(stage_id).controller._stages[stage_id]
            result = []
            for role in params["roles"]:
                assert role == "mesh:0"
                mesh = stage.references[role].value
                result.append({"stage_id": stage_id, "role": role, "family": "meshes",
                    "native_uid": mesh.session_uid, "pointer": mesh.as_pointer(), "name": mesh.name})
            return result
        if action == "arm_boundary":
            event = threading.Event()
            self.boundaries[params["stage_id"]] = {"phase": params["phase"], "event": event}
            return event
        if action == "transport_receipts":
            values = {}
            for identifier in params["ids"]:
                lifetime = self.request_lifetimes.get(identifier)
                assert lifetime is not None and lifetime.connection is not None
                now = time.monotonic()
                values[identifier] = {"origin": "CANONICAL_SERVER_REQUEST_LIFETIME", "connection_identity": id(lifetime.connection),
                    "delivered": lifetime.delivered.is_set(), "rejected": lifetime.rejected.is_set(),
                    "disconnected": lifetime.connection.disconnected.is_set(), "deadline": lifetime.deadline,
                    "observed_at": now, "expired_without_delivery": not lifetime.delivered.is_set() and now >= lifetime.deadline}
            return values
        if action == "receipts":
            return copy.deepcopy(self.receipts.get(params["stage_id"], []))
        if action == "history":
            return [copy.deepcopy(self.histories[key]) for key in params["ids"] if key in self.histories]
        if action == "grant":
            from blender_codex_bridge.permissions import PREFERENCE_PROPERTIES, Permission
            setattr(self.prefs, PREFERENCE_PROPERTIES[Permission(params["grant"])], params["value"])
        elif action == "flags":
            self.runtime.state.set_emergency_stopped(params.get("stopped", False))
            self.runtime.state.set_paused(params.get("paused", False))
        elif action == "root":
            self.prefs.asset_source_directory = params["value"]
        elif action == "write":
            path = Path(params["path"])
            path.write_bytes(bytes.fromhex(params["hex"]))
        elif action == "prepare_files":
            return self.prepare_files()
        elif action == "collision":
            kind, name = params["kind"], params["name"]
            value = self.raw_collisions[kind]
            assert value.name == name
            return [value.session_uid, value.as_pointer(), value.name]
        elif action == "drift":
            return self.drift(params)
        elif action == "drift_readback":
            return self.drift_readback(params)
        elif action == "destination":
            return self.destination_fault(params)
        elif action == "watch_nested":
            self.watch = dict(params)
        elif action == "nested_results":
            self.watch = None
            return copy.deepcopy(self.nested_probes)
        elif action == "invalidate":
            return self.invalidate(params)
        elif action == "observe":
            return self.observation(params["phase"], params["elapsed"])
        else:
            raise AssertionError(("Unknown main-thread fixture action", action))
        return None

    def prepare_files(self):
        import struct
        raw = literal_source()
        length = struct.unpack_from("<I", raw, 12)[0]
        document = json.loads(raw[20:20+length])
        binary = raw[28+length:]
        def source(label, change):
            value = copy.deepcopy(document)
            change(value)
            text = json.dumps(value, separators=(",", ":")).encode()
            text += b" " * (-len(text) % 4)
            payload = b"glTF"+struct.pack("<II", 2, 28+len(text)+len(binary))+struct.pack("<II", len(text), 0x4E4F534A)+text+struct.pack("<II", len(binary), 0x004E4942)+binary
            path = self.approved / (label+".glb")
            path.write_bytes(payload)
            return str(path)
        paths = {
            "mixed_uv": source("mixed_uv", lambda v: v["meshes"][0]["primitives"][1]["attributes"].pop("TEXCOORD_0")),
            "alpha": source("alpha", lambda v: v["materials"][0].update(alphaMode="BLEND")),
            "texture": source("texture", lambda v: v.update(images=[{"uri": "external.png"}])),
            "skin": source("skin", lambda v: v.update(skins=[{"joints": [0]}])),
            "animation": source("animation", lambda v: v.update(animations=[{}])),
            "tangent": source("tangent", lambda v: v["meshes"][0]["primitives"][0]["attributes"].update(TANGENT=0)),
            "uri": source("uri", lambda v: v["buffers"][0].update(uri="external.bin")),
            "extra_stream": source("extra_stream", lambda v: v["meshes"][0]["primitives"][0]["attributes"].update(TEXCOORD_1=1))}
        outside = self.folder / "outside.glb"
        outside.write_bytes(raw)
        paths["outside"] = str(outside)
        linked = self.approved / "link.glb"
        linked.symlink_to(self.source)
        paths["symlink"] = str(linked)
        fifo = self.approved / "pipe.glb"
        if hasattr(os, "mkfifo"):
            os.mkfifo(fifo, 0o600)
        else:
            raise AssertionError("Native FIFO refusal proof requires a real platform-supported FIFO")
        paths["fifo"] = str(fifo)
        return paths

    def drift(self, params):
        from scripts.blender_glb_stage_smoke import structure_object_row
        refs = {item["role"]: item for item in params["allocations"]}
        mesh_item, object_item = refs["mesh:0"], refs["object:1"]
        mesh = self.bpy.data.meshes[mesh_item["name"]]
        obj = self.bpy.data.objects[object_item["name"]]
        assert mesh.session_uid == mesh_item["native_uid"] and obj.session_uid == object_item["native_uid"]
        before = {"mesh": self.owned_mesh_observation(mesh), "object": structure_object_row(obj)}
        kind = params["kind"]
        if kind == "encoded_short":
            mesh.attributes["custom_normal"].data[0].value[0] += 1
        elif kind == "selection_bit":
            mesh.attributes[".select_vert"].data[0].value = not mesh.attributes[".select_vert"].data[0].value
        elif kind == "uv_role":
            mesh.uv_layers.new(name="Fixture Manual UV Drift")
            mesh.uv_layers.active_index = 1
        elif kind == "authored_channel":
            obj.location.x += .125
        elif kind == "schema":
            mesh.attributes.new(name="fixture_manual_schema", type="BOOLEAN", domain="POINT")
        else:
            raise AssertionError(kind)
        headers = self.raw_observer.capture_headers(mesh)
        # Return metadata first. A genuine TCP SINGLE refusal must precede any
        # separately authorized raw materialization, including manual drift.
        return {"kind": kind, "before": before, "after": None, "headers": [headers],
            "mesh_target": {"name": mesh.name, "uid": mesh.session_uid},
            "requires_raw_preparation": any(row["storage"] == "SINGLE" for row in headers["attributes"])}

    def drift_readback(self, params):
        from scripts.blender_glb_stage_smoke import structure_object_row
        refs = {item["role"]: item for item in params["allocations"]}
        mesh = self.bpy.data.meshes[refs["mesh:0"]["name"]]
        obj = self.bpy.data.objects[refs["object:1"]["name"]]
        assert mesh.session_uid == refs["mesh:0"]["native_uid"] and obj.session_uid == refs["object:1"]["native_uid"]
        # This reinspection never adopts a new product baseline. Publication
        # still compares against the original retained stage and must refuse.
        return {"mesh": self.owned_mesh_observation(mesh), "object": structure_object_row(obj)}

    def destination_fault(self, params):
        kind, restore = params["kind"], params.get("restore", False)
        bpy, scene = self.bpy, self.destination
        def facts():
            current = bpy.context.scene
            return {"scene_uid": current.session_uid, "master_pointer": current.collection.as_pointer(),
                "name": current.name, "scale": current.unit_settings.scale_length,
                "children": sorted(value.session_uid for value in current.collection.children)}
        if restore:
            saved = self.destination_change
            if kind in {"scene_identity", "master_identity", "context"}:
                bpy.context.window.scene = scene
                if "replacement" in saved:
                    saved["replacement"].name = saved["replacement_name"]
                scene.name = saved["name"]
            elif kind == "name":
                scene.name = saved["name"]
            elif kind == "unit_scale":
                scene.unit_settings.scale_length = saved["scale"]
            else:
                scene.collection.children.unlink(saved["collection"])
            self.destination_fault_observation = None
            return None
        before_facts = facts()
        self.destination_change = {"name": scene.name, "scale": scene.unit_settings.scale_length}
        if kind in {"scene_identity", "master_identity", "context"}:
            replacement = self.other_scenes[kind]
            self.destination_change.update(replacement=replacement, replacement_name=replacement.name)
            if kind != "context":
                scene.name += " Fixture Renamed"
                replacement.name = self.destination_change["name"]
            bpy.context.window.scene = replacement
        elif kind == "name":
            scene.name += " Fixture Rename"
        elif kind == "unit_scale":
            scene.unit_settings.scale_length = 2.
        else:
            collection = self.other_collection
            self.destination_change["collection"] = collection
            scene.collection.children.link(collection)
        self.destination_fault_observation = {"kind": kind, "before": before_facts, "after": facts()}
        return {"kind": kind, "actual_scene": scene.session_uid, "current_context_scene": bpy.context.scene.session_uid}

    def invalidate(self, params):
        kind = params["kind"]
        if kind == "undo":
            result = self.bpy.ops.ed.undo()
        elif kind == "redo":
            result = self.bpy.ops.ed.redo()
        elif kind == "runtime_reset":
            self.runtime.unregister()
            self.runtime.register()
            self.runtime.start_server("127.0.0.1", self.port, request_timeout=90)
            result = {"FINISHED"}
        elif kind == "file_load":
            from scripts.native_fixture_save import serialize_owned_fixture
            path = self.folder / "runtime-invalidation-owned.blend"
            serialization = serialize_owned_fixture(self.runtime, path)
            assert serialization["fixture_native_save"] is True
            result = self.bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
            self.load_restart_event = threading.Event()
            self.bpy.app.timers.register(self.restart_after_load, first_interval=.05)
        else:
            raise AssertionError(kind)
        assert result == {"FINISHED"}
        self.reacquire_after_invalidation()
        return {"kind": kind, "actual_native_operation": True, "result": sorted(result),
                "restart_event": self.load_restart_event if kind == "file_load" else None}

    def restart_after_load(self):
        self.runtime.start_server("127.0.0.1", self.port, request_timeout=90)
        if not self.bpy.app.timers.is_registered(self.supervise):
            self.bpy.app.timers.register(self.supervise, first_interval=.001)
        self.load_restart_event.set()
        return None

    def start_series(self, params):
        kind, allocations = params["kind"], params["allocations"]
        event = threading.Event()
        reference = self.raw_snapshot(allocations)
        series = {"kind": kind, "runtime_group": self.group_index, "started_at": time.monotonic(),
            "after_request_id": params["after_request_id"], "observations": []}
        series["observations"].append({"phase": "immediate", "elapsed_seconds": 0., "real_timer_callback": False,
            "observed_at": series["started_at"], "runtime_group": self.group_index,
            "snapshot": reference, "logical_sha256": digest(logical_snapshot(reference))})
        self.data.setdefault("observation_series", []).append(series)
        for phase, delay in OBSERVATIONS[1:]:
            def callback(phase=phase):
                try:
                    observed_at = time.monotonic()
                    elapsed = observed_at-series["started_at"]
                    assert elapsed >= dict(OBSERVATIONS)[phase]
                    measured = self.raw_snapshot(allocations)
                    row = {"phase": phase, "elapsed_seconds": elapsed, "real_timer_callback": True,
                        "observed_at": observed_at, "runtime_group": self.group_index,
                        "snapshot": measured, "logical_sha256": digest(logical_snapshot(measured)),
                        "raw_equal_to_immediate": measured == reference}
                    series["observations"].append(row)
                    self.flush()
                    assert logical_snapshot(measured) == logical_snapshot(reference), "Real deferred observation changed authored data/context"
                    if phase == "timer_0_5":
                        event.set()
                except BaseException:
                    self.failure = traceback.format_exc()
                    event.set()
                return None
            self.bpy.app.timers.register(callback, first_interval=delay)
        return event

    def observation(self, phase, elapsed):
        floors = dict(OBSERVATIONS)
        assert phase in floors and finite(elapsed) >= floors[phase]
        value = self.raw_snapshot(self.owned_allocations)
        row = {"phase": phase, "elapsed_seconds": elapsed, "real_timer_callback": phase != "immediate", "snapshot": value}
        self.data["observations"].append(row)
        self.flush()
        assert logical_snapshot(value) == logical_snapshot(self.deferred_baseline), "Declared logical protected/owned/context data changed during real timers"
        return row

    def supervise(self):
        while not self.controls.empty():
            action, params, event, result = self.controls.get_nowait()
            try:
                result.extend((True, self.apply(action, params)))
            except BaseException:
                result.extend((False, traceback.format_exc()))
            finally:
                event.set()
        if not self.done.is_set():
            return .001
        if self.failure is not None:
            self.finish(1, self.failure)
            return None
        try:
            self.deferred_baseline = self.raw_snapshot(self.owned_allocations)
            self.observed_at = time.monotonic()
            self.observation("immediate", 0.)
            for phase, delay in OBSERVATIONS[1:]:
                def callback(phase=phase):
                    try:
                        self.observation(phase, time.monotonic()-self.observed_at)
                        if phase == "timer_0_5":
                            self.complete()
                    except BaseException:
                        self.finish(1, traceback.format_exc())
                    return None
                self.bpy.app.timers.register(callback, first_interval=delay)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def complete(self):
        deferred = self.data["cases"][-2]
        deferred["witness"]["observation_digests"] = [digest(row["snapshot"]) for row in self.data["observations"]]
        self.data["completed"] = True
        self.populate_countermodels()
        validate_runtime_transcript(self.data)
        assert source_hashes(self.root) == self.data["source_sha256"]
        self.flush()
        self.finish(0)

    def finish(self, status, failure=None):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        sys.setprofile(self.before_profile)
        threading.setprofile(self.before_thread_profile)
        if status:
            self.data.update(completed=False, failure=failure)
            try:
                self.flush()
            except BaseException:
                traceback.print_exc()
        else:
            marker = {key: self.data[key] for key in ("schema", "profile", "completed", "blender_version", "version", "build_hash", "process_id", "process_instance", "source_sha256", "binary")}
            marker["evidence_sha256"] = hashlib.sha256(bounded_file(self.path)).hexdigest()
            print(MARKER+json.dumps(marker, allow_nan=False), flush=True)
        owned_process_exit(status)

    def worker(self):
        """Only JSON/socket/control-queue operations run on this worker."""
        try:
            self.socket_scenarios()
        except BaseException:
            self.failure = traceback.format_exc()
        finally:
            self.done.set()

    def socket_scenarios(self):
        client = TCPClient(self.port, self.data["tcp"])
        self.client = client
        client.call("toolsets.enable", name="asset_delivery")
        def prepare_after_refusal(headers, mesh_target=None):
            self.name_sequence += 1
            error = client.call("asset.glb_stage_preview", filepath=str(self.source),
                collection_name=f"Runtime SINGLE Source Gate {self.name_sequence}", overwrite_policy="REFUSE", expect_error=True)
            request_id = self.data["tcp"][-1]["request"]["id"]
            assert "SINGLE" in error.get("context", {}).get("reason", ""), "Missing genuine SINGLE refusal before raw preparation"
            receipt = self.control("access_receipt", request_id=request_id)
            accesses = receipt["native_access_counts"]
            assert "get:data" not in accesses and receipt["protected_read_effect_attempts"] == [], "SINGLE refusal occurred after geometry/groups/data begin"
            self.data["single_storage_refusals"].append({"runtime_group": client.runtime_group,
                "request_id": request_id, "error": error, "headers": headers, "mesh_target": mesh_target,
                "recorded_at": time.monotonic(), **receipt})
            return self.control("prepare_storage", refusal_request_id=request_id, mesh_target=mesh_target)
        def ensure_observer_ready():
            headers = self.control("storage_headers")
            singles = [row for mesh in headers for row in mesh["attributes"] if row["storage"] == "SINGLE"]
            if singles:
                prepare_after_refusal(headers)
            return self.control("establish_baseline")
        ensure_observer_ready()
        def preview(prefix="Stage", filepath=None):
            self.name_sequence += 1
            return client.call("asset.glb_stage_preview", filepath=filepath or str(self.source),
                collection_name=f"Runtime {prefix} {self.name_sequence}", overwrite_policy="REFUSE")
        def start(value, limit=60):
            return client.call("asset.glb_stage_create_start", preview_id=value["preview_id"],
                expected_fingerprint=value["expected_fingerprint"], accepted_losses=value["required_accepted_losses"],
                time_limit_seconds=limit)
        def publish_preview(value):
            return client.call("asset.glb_stage_publish_preview", stage_id=value["stage_id"],
                destination_scene_name=self.destination_name, overwrite_policy="REFUSE")
        def publish(value, intent, *, error=False):
            return client.call("asset.glb_stage_publish_start", stage_id=value["stage_id"],
                publish_preview_id=intent["publish_preview_id"], expected_fingerprint=intent["expected_fingerprint"],
                overwrite_policy="REFUSE", time_limit_seconds=60, expect_error=error)
        def inspect(value):
            return client.call("asset.glb_stage_inspect", stage_id=value["stage_id"])
        def wait(accepted, value, operation=None):
            deadline = time.monotonic()+accepted.get("time_limit_seconds", 60)+5
            while time.monotonic() < deadline:
                state = client.call("jobs.inspect", job_id=accepted["job_id"])
                retained = inspect(value)
                entries = retained["native_evidence"]["native_entries"]
                if operation is not None and entries and entries[-1]["operation"] == operation and entries[-1]["returned"]:
                    assert not state["terminal"], ("Missed required running native boundary", operation, state)
                    return state, retained
                if state["terminal"]:
                    assert operation is None, ("Required native timing window was not observed", operation, state)
                    return state, retained
                time.sleep(.025)
            raise AssertionError("Real Runtime job did not reach the required bounded terminal point")
        def fresh_group():
            metadata = self.control("new_lifetime")
            client.reconnect()
            client.runtime_group = metadata["index"]
            client.call("toolsets.enable", name="asset_delivery")
            ensure_observer_ready()
            refusals = []
            for old_stage_id in metadata["old_stage_ids"]:
                error = client.call("asset.glb_stage_inspect", stage_id=old_stage_id, expect_error=True)
                refusals.append({"stage_id": old_stage_id, "request_id": self.data["tcp"][-1]["request"]["id"],
                    "error_code": error["code"]})
            self.data["runtime_groups"][metadata["index"]]["stale_lookup_refusals"] = refusals
            return metadata

        def begin(identifier):
            if identifier not in {"TCP_SUCCESS_STAGE", "TCP_SUCCESS_PUBLISH"}:
                fresh_group()
            row = {"id": identifier, "status": "RUNNING", "requests": [], "witness": {},
                "runtime_group_start": client.runtime_group,
                "before": self.control("snapshot"), "after": None,
                "native": {"native_entries": [], "owned_reference_roles": [], "footprint_complete": False}, "history": []}
            self.data["cases"].append(row)
            row["_tcp_start"] = len(self.data["tcp"])
            return row
        def finish(row, value=None, *, owned=False, stopped=False):
            if value is not None:
                retained = inspect(value)
                row["native"] = copy.deepcopy(retained["native_evidence"])
                if stopped:
                    count = len(row["native"]["native_entries"])
                    row["native"].update(stopped=True, stop_native_entry_count=count, entries_after_stop=[])
                    if "after_link" in row["witness"]:
                        row["witness"]["after_link"]["native"] = copy.deepcopy(row["native"])
                allocations = retained["observed_allocations"] if owned else None
            else:
                allocations = None
            row["after"] = self.control("snapshot", allocations=allocations)
            offset = row.pop("_tcp_start")
            row["requests"] = [item["request"]["id"] for item in self.data["tcp"][offset:]]
            row["history"] = self.control("history", ids=row["requests"])
            row["runtime_group_end"] = client.runtime_group
            pending = [item for item in self.data["tcp"] if "runtime_receipt" not in item]
            receipts = self.control("transport_receipts", ids=[item["request"]["id"] for item in pending])
            for item in pending:
                item["runtime_receipt"] = receipts[item["request"]["id"]]
            row["status"] = "VERIFIED"
            self.control("persist")
            return row
        def refusal(row, label, method, params):
            before = self.control("identities")
            fault = self.control("refusal_state", request_params=params)
            client.call(method, expect_error=True, **params)
            identifier = self.data["tcp"][-1]["request"]["id"]
            after = self.control("identities")
            row["witness"].setdefault("refusals", []).append({"label": label, "request_id": identifier,
                "fault_observation": fault,
                "before_native_identities": before, "after_native_identities": after})
        def create_params(value):
            return {"preview_id": value["preview_id"], "expected_fingerprint": value["expected_fingerprint"],
                    "accepted_losses": value["required_accepted_losses"], "time_limit_seconds": 60}
        first = begin("TCP_SUCCESS_STAGE")
        success = preview("Success")
        accepted = start(success)
        terminal, retained = wait(accepted, success)
        assert terminal["state"] == "SUCCEEDED" and retained["phase"] == "CONSTRUCTED"
        first["witness"].update(source_sha256=hashlib.sha256(literal_source()).hexdigest(),
            normal_source_loop_count=3, auto_normal_loop_count=3)
        first["witness"]["normal_return_footprint"] = next(value for value in
            self.control("receipts", stage_id=success["stage_id"]) if value["operation"] == "WRITE_NORMALS")
        finish(first, success, owned=True)
        observed = self.control("start_series", kind="CONSTRUCTED", allocations=retained["observed_allocations"],
            after_request_id=first["requests"][-1])
        assert observed.wait(90) and self.failure is None, self.failure
        row = begin("TCP_SUCCESS_PUBLISH")
        intent = publish_preview(success)
        accepted = publish(success, intent)
        terminal, retained = wait(accepted, success)
        assert terminal["state"] == "SUCCEEDED" and retained["publication_observed"]
        row["witness"]["published_edge"] = [row["before"]["context"]["scene"],
            next(v["native_uid"] for v in retained["observed_allocations"] if v["role"] == "collection")]
        finish(row, success, owned=True)
        observed = self.control("start_series", kind="PUBLISHED", allocations=retained["observed_allocations"],
            after_request_id=row["requests"][-1])
        assert observed.wait(90) and self.failure is None, self.failure
        self.owned_allocations = retained["observed_allocations"]
        # Distinct prepared intent is used for permission/consent refusals. It
        # has not already been consumed, so a stale-token error cannot stand in
        # for source-specific loss or permission validation.
        row = begin("PERMISSION_AND_TOOLSET")
        consent = preview("Consent")
        for grant in CREATE_GRANTS:
            self.control("grant", grant=grant, value=False)
            refusal(row, "create_"+grant, "asset.glb_stage_create_start", create_params(consent))
            self.control("grant", grant=grant, value=True)
        publish_grants = preview("Publish Grant Seed")
        publish_seed_accepted = start(publish_grants)
        publish_seed_terminal, _publish_seed_retained = wait(publish_seed_accepted, publish_grants)
        assert publish_seed_terminal["state"] == "SUCCEEDED"
        pub_intent = publish_preview(publish_grants)
        for grant in PUBLISH_GRANTS:
            self.control("grant", grant=grant, value=False)
            refusal(row, "publish_"+grant, "asset.glb_stage_publish_start", {
                "stage_id": publish_grants["stage_id"], "publish_preview_id": pub_intent["publish_preview_id"],
                "expected_fingerprint": pub_intent["expected_fingerprint"], "overwrite_policy": "REFUSE", "time_limit_seconds": 60})
            self.control("grant", grant=grant, value=True)
        client.call("toolsets.disable", name="asset_delivery")
        refusal(row, "toolset", "asset.glb_stage_create_start", create_params(consent))
        client.call("toolsets.enable", name="asset_delivery")
        for label, flags in (("paused", {"paused": True}), ("emergency_stop", {"stopped": True})):
            self.control("flags", **flags)
            refusal(row, label, "asset.glb_stage_create_start", create_params(consent))
            self.control("flags")
        finish(row)
        row = begin("SOURCE_AND_NAME_REFUSALS")
        files = self.control("prepare_files")
        def preview_params(path, name):
            return {"filepath": path, "collection_name": name, "overwrite_policy": "REFUSE"}
        self.control("root", value="")
        refusal(row, "empty_root", "asset.glb_stage_preview", preview_params(str(self.source), "Runtime Bad Root"))
        self.control("root", value=str(self.approved))
        for label in ("outside", "symlink", "fifo"):
            refusal(row, label, "asset.glb_stage_preview", preview_params(files[label], "Runtime Source "+label))
        for label in ("ancestry", "file_race", "source_stale", "root_stale"):
            prepared = preview("Source "+label)
            mutation = self.control("source_fault", kind=label)
            refusal(row, label, "asset.glb_stage_create_start", create_params(prepared))
            self.control("source_restore", mutation=mutation)
        for kind, suffix in (("collection", ""), ("mesh", ".M0"), ("material", ".P0"), ("object", ".O0")):
            name = "Runtime Collision "+kind
            self.control("collision", kind=kind, name=name+suffix)
            refusal(row, kind+"_collision", "asset.glb_stage_preview", preview_params(str(self.source), name))
        finish(row)
        row = begin("NORMAL_CONSENT")
        consent = preview("Normal Consent")
        invalid = {"omitted": LOSSES[:-2], "reordered": [*LOSSES[:-2], LOSSES[-1], LOSSES[-2]],
            "duplicated": [*LOSSES, LOSSES[-2]], "wrong_type": True,
            "wrong_normal": [*LOSSES[:-2], "UNKNOWN_NORMAL"], "auto_without_normal": [*LOSSES[:-2], LOSSES[-1]]}
        for label, losses in invalid.items():
            refusal(row, label, "asset.glb_stage_create_start", {**create_params(consent), "accepted_losses": losses})
        for label in ("mixed_uv", "alpha", "texture", "skin", "animation", "tangent", "uri", "extra_stream"):
            refusal(row, label, "asset.glb_stage_preview", preview_params(files[label], "Runtime Unsupported "+label))
        accepted = start(consent)
        terminal, _retained = wait(accepted, consent)
        assert terminal["state"] == "SUCCEEDED"
        row["witness"]["accepted_losses"] = LOSSES
        finish(row, consent)
        row = begin("START_HANDOFF_AND_DISCONNECT")
        row["witness"]["outcomes"] = []
        for kind in ("undelivered", "expired", "disconnect"):
            # A real new owner connection obtains its own preview and sends the
            # real start bytes, then closes without consuming a start response.
            other = TCPClient(self.port, self.data["tcp"])
            other.runtime_group = client.runtime_group
            self.name_sequence += 1
            value = other.call("asset.glb_stage_preview", filepath=str(self.source),
                collection_name=f"Runtime Handoff {self.name_sequence}", overwrite_policy="REFUSE")
            identifier = other.send_without_receipt("asset.glb_stage_create_start", create_params(value),
                timeout_ms=1 if kind == "expired" else 60000, outcome="EXPIRED" if kind == "expired" else "DISCONNECTED")
            other.close()
            retained = client.call("asset.glb_stage_inspect", stage_id=value["stage_id"])
            terminal = None if retained["job_id"] is None else client.call("jobs.inspect", job_id=retained["job_id"])
            assert terminal is None or terminal["terminal"]
            assert not retained["native_evidence"]["native_entries"]
            row["witness"]["outcomes"].append({"kind": kind, "request_id": identifier,
                "work_before_handoff": [], "terminal": terminal, "native": retained["native_evidence"],
                "no_job_accepted": retained["job_id"] is None})
        finish(row)
        row = begin("GENUINE_CANCEL_AFTER_UV")
        cancelled = preview("Cancel UV")
        boundary = self.control("arm_boundary", stage_id=cancelled["stage_id"], phase="write_uv_mesh_0")
        accepted = start(cancelled)
        assert boundary.wait(65), "Real WRITE_UV timer return was not observed"
        client.call("jobs.cancel", job_id=accepted["job_id"])
        cancel_request = self.data["tcp"][-1]["request"]["id"]
        terminal, retained = wait(accepted, cancelled)
        assert terminal["state"] == "CANCELLED"
        entries = retained["native_evidence"]["native_entries"]
        assert entries[-1]["operation"] == "WRITE_UV", "Real cancellation missed the declared UV boundary"
        observed_index = entries[-1]["index"]
        row["witness"].update(cancel_request_id=cancel_request, observed_uv_native_index=observed_index,
            stop_ack_native_entry_count=len(entries), genuine_return_escrow_roles=[r for v in retained["native_evidence"]["pending_returns"] for r in v["returned_roles"]])
        finish(row, cancelled, stopped=True)
        row = begin("PERMISSION_REVOCATION")
        revoked = preview("Revoked")
        boundary = self.control("arm_boundary", stage_id=revoked["stage_id"], phase="write_uv_mesh_0")
        accepted = start(revoked)
        assert boundary.wait(65), "Real revocation timing point was not observed"
        self.control("grant", grant="EDIT_MESH", value=False)
        terminal, retained = wait(accepted, revoked)
        assert terminal["state"] == "FAILED" and terminal["error"]["code"] == "PERMISSION_DENIED"
        self.control("grant", grant="EDIT_MESH", value=True)
        row["witness"]["revoked_grant"] = "EDIT_MESH"
        finish(row, revoked, stopped=True)
        self.continue_scenarios(client, begin, finish, preview, start, wait, inspect, publish_preview, publish, refusal,
                                success, consent, cancelled, fresh_group, prepare_after_refusal)
        client.close()

    def continue_scenarios(self, client, begin, finish, preview, start, wait, inspect, publish_preview, publish, refusal,
                           success, consent, cancelled, fresh_group, prepare_after_refusal):
        row = begin("OWNED_MANUAL_DRIFT")
        row["witness"]["drifts"] = []
        for kind in ("encoded_short", "selection_bit", "uv_role", "authored_channel", "schema"):
            if row["witness"]["drifts"]:
                fresh_group()
            value = preview("Drift "+kind)
            accepted = start(value)
            terminal, retained = wait(accepted, value)
            assert terminal["state"] == "SUCCEEDED"
            intent = publish_preview(value)
            mutation = self.control("drift", kind=kind, allocations=retained["observed_allocations"])
            if mutation["requires_raw_preparation"]:
                preparation = prepare_after_refusal(mutation["headers"], mutation["mesh_target"])
                mutation["raw_preparation_request_id"] = preparation["refusal_request_id"]
            mutation["after"] = self.control("drift_readback", allocations=retained["observed_allocations"])
            edges = self.control("snapshot")["scene_edges"]
            publish(value, intent, error=True)
            mutation.update(request_id=self.data["tcp"][-1]["request"]["id"], scene_edges_before=edges,
                            scene_edges_after=self.control("snapshot")["scene_edges"])
            row["witness"]["drifts"].append(mutation)
        finish(row)
        row = begin("DESTINATION_DRIFT_AND_UNITS")
        for kind in ("scene_identity", "master_identity", "child_inventory", "name", "context", "unit_scale"):
            if row["witness"].get("refusals"):
                fresh_group()
            value = preview("Destination "+kind)
            accepted = start(value)
            terminal, retained = wait(accepted, value)
            assert terminal["state"] == "SUCCEEDED"
            intent = publish_preview(value)
            self.control("destination", kind=kind)
            refusal(row, kind, "asset.glb_stage_publish_start", {"stage_id": value["stage_id"],
                "publish_preview_id": intent["publish_preview_id"], "expected_fingerprint": intent["expected_fingerprint"],
                "overwrite_policy": "REFUSE", "time_limit_seconds": 60})
            self.control("destination", kind=kind, restore=True)
        finish(row)
        def disconnect_at_return(row, value, entry, accepted):
            # arm_disconnect is called BEFORE start below; this helper performs
            # only actual worker socket operations after the observed return.
            watch = self.armed_disconnect
            assert watch["notify"].wait(65), "Required genuine C-return boundary was not reached"
            owner_request_id = self.data["tcp"][-1]["request"]["id"]
            owner_connection_instance = client.connection_instance
            closed_socket_fileno = client.socket.fileno()
            client.abort()
            watch["close_receipt"].append({"closed_at": time.monotonic(), "actual_socket_fileno": client.socket.fileno(),
                "closed_socket_fileno": closed_socket_fileno})
            assert client.socket.fileno() == -1
            watch["close_done"].set()
            client.reconnect()
            terminal, retained = wait(accepted, value)
            receipt = self.control("disconnect_receipt")
            receipt.update(owner_start_request_id=owner_request_id, owner_connection_instance=owner_connection_instance)
            entries = retained["native_evidence"]["native_entries"]
            assert terminal["state"] in {"CANCELLED", "FAILED", "TIMED_OUT"}
            assert entries and entries[-1]["index"] == receipt["entry_index"] and entries[-1]["entry"] == entry
            assert entries[-1]["returned"] is True and entries[-1]["post_return_stop_checked"] is False
            assert retained["native_evidence"]["native_access_counts"] == receipt["native_access_counts_at_return"], "Dependent native access occurred after disconnect ACK"
            row["witness"].update(disconnect=receipt, genuine_return_escrow_roles=receipt["genuine_return_escrow_roles"],
                stop_ack_native_entry_count=len(entries), actual_terminal=terminal,
                atomic_native_interval_seconds=receipt["returned_monotonic"]-receipt["started_monotonic"])
            return terminal, retained

        row = begin("STOP_AT_NATIVE_RETURN")
        value = preview("Native Return")
        self.armed_disconnect = self.control("arm_disconnect", stage_id=value["stage_id"], entry="meshes.new")
        accepted = start(value)
        terminal, retained = disconnect_at_return(row, value, "meshes.new", accepted)
        assert row["witness"]["genuine_return_escrow_roles"], "Constructor reference was not escrowed before pure stop"
        finish(row, value, stopped=True)
        row = begin("PARTIAL_UNKNOWN_IDS")
        value = preview("Unknown Retained")
        before_ids = self.control("identities")
        self.armed_disconnect = self.control("arm_disconnect", stage_id=value["stage_id"], entry="meshes.new")
        accepted = start(value)
        terminal, retained = disconnect_at_return(row, value, "meshes.new", accepted)
        after_ids = self.control("identities")
        new_ids = [item for item in after_ids if item not in before_ids]
        assert new_ids and all(item in after_ids for item in before_ids)
        row["witness"].update(retained_identities=retained["observed_allocations"], raw_partial_identities=new_ids,
            raw_escrow_identities=self.control("escrow_identities", stage_id=value["stage_id"],
                roles=row["witness"]["genuine_return_escrow_roles"]),
            unknown_inventory=retained["outcome_unknown"], deletions=[],
            incomplete_native_footprint=not retained["native_evidence"]["footprint_complete"])
        assert retained["outcome_unknown"] is True and not retained["native_evidence"]["footprint_complete"]
        finish(row, value, stopped=True)
        row = begin("PUBLICATION_STOP_OR_FAILURE")
        before_value = preview("Before Link Stop")
        accepted = start(before_value)
        terminal, retained = wait(accepted, before_value)
        assert terminal["state"] == "SUCCEEDED"
        before = self.control("snapshot")["scene_edges"]
        intent = publish_preview(before_value)
        accepted = publish(before_value, intent)
        client.call("jobs.cancel", job_id=accepted["job_id"])
        cancel_request_id = self.data["tcp"][-1]["request"]["id"]
        terminal, retained = wait(accepted, before_value)
        assert terminal["state"] == "CANCELLED" and not retained["publication_observed"]
        row["witness"]["before_link"] = {"edges_before": before, "edges_after": self.control("snapshot")["scene_edges"],
            "terminal": terminal, "retained": retained, "cancel_request_id": cancel_request_id}
        fresh_group()
        after_value = preview("After Link Stop")
        accepted = start(after_value)
        terminal, retained = wait(accepted, after_value)
        assert terminal["state"] == "SUCCEEDED"
        intent = publish_preview(after_value)
        before_link_snapshot = self.control("snapshot")
        self.armed_disconnect = self.control("arm_disconnect", stage_id=after_value["stage_id"], entry="CollectionChildren.link")
        accepted = publish(after_value, intent)
        terminal, retained = disconnect_at_return(row, after_value, "CollectionChildren.link", accepted)
        after_link_snapshot = self.control("snapshot")
        edge = [before_link_snapshot["context"]["scene"],
            next(item["native_uid"] for item in retained["observed_allocations"] if item["role"] == "collection")]
        assert after_link_snapshot["scene_edges"] == sorted([*before_link_snapshot["scene_edges"], edge])
        row["witness"]["after_link"] = {"phase": "PUBLICATION_UNKNOWN", "service_phase": retained["phase"],
            "automatic_unlink": False, "retained": retained, "terminal": terminal,
            "before": before_link_snapshot, "after": after_link_snapshot, "actual_edge": edge,
            "disconnect": row["witness"]["disconnect"], "native": retained["native_evidence"],
            "object_closure": [item["native_uid"] for item in retained["observed_allocations"] if item["role"].startswith("object:")],
            "physical_effects": ["GLOBAL_BKE_MAIN_COLLECTION_SYNC_ALL_SCENES", "LAYER_COLLECTION_LOCAL_VIEW_BASE_CACHE_SYNC"]}
        assert retained["outcome_unknown"] is True
        finish(row, after_value, stopped=True)
        row = begin("UNDO_LOAD_RUNTIME_INVALIDATION")
        row["witness"]["invalidations"] = []
        for kind in ("undo", "redo", "file_load", "runtime_reset"):
            value = preview("Invalidate "+kind)
            current = inspect(value)
            assert current["session_valid"] and current["phase"] == "PREPARED"
            invalidated = self.control("invalidate", kind=kind)
            if invalidated["restart_event"] is not None:
                assert invalidated["restart_event"].wait(90), "File-load listener/supervisor did not restart"
            client.reconnect()
            client.call("toolsets.enable", name="asset_delivery")
            stale = inspect(value)
            fresh = preview("After "+kind)
            row["witness"]["invalidations"].append({"kind": kind, "actual_native_operation": True,
                "stale_phase": stale["phase"], "old_stage_id": value["stage_id"], "fresh_stage_id": fresh["stage_id"],
                "stale_native_entries": stale["native_evidence"]["native_entries"]})
        finish(row)
        row = begin("SHARED_SLOT_REENTRANCY")
        value = preview("Shared Slot")
        accepted = start(value)
        params = {"preview_id": value["preview_id"], "expected_fingerprint": value["expected_fingerprint"],
                  "accepted_losses": value["required_accepted_losses"], "time_limit_seconds": 60}
        for kind, method, arguments in (
            ("glb", "asset.glb_stage_create_start", params),
            ("image", "image.snapshot_job_start", {"image_name": "Runtime Slot Image", "new_name": "Runtime Slot Snapshot", "time_limit_seconds": 60}),
            ("scene", "rigid_body.evaluate_job_start", {"scene_name": self.destination_name, "body_names": [], "preview_id": "rigid_eval_"+"a"*32, "expected_fingerprint": "b"*64, "time_limit_seconds": 60}),
            ("native_save", "project.native_save_start", {"preview_id": "native_save_"+"a"*32, "expected_fingerprint": "b"*64,
                "mode": "COPY_NEW", "filepath": str(self.folder/"unused-native-save.blend"), "overwrite_policy": "NO_CLOBBER", "accepted_losses": [], "time_limit_seconds": 60}),
        ):
            refusal(row, kind, method, arguments)
        terminal, _retained = wait(accepted, value)
        assert terminal["state"] == "SUCCEEDED"
        nested = []
        for kind in ("provider", "checkpoint", "handler", "finalizer"):
            fresh_group()
            outer = preview("Nested "+kind)
            params = {"preview_id": outer["preview_id"], "expected_fingerprint": outer["expected_fingerprint"],
                      "accepted_losses": outer["required_accepted_losses"], "time_limit_seconds": 60}
            identifier = "glb_runtime_"+os.urandom(16).hex()
            self.control("watch_nested", kind=kind, params=params, outer_request_id=identifier)
            accepted = client.call_with_id(identifier, "asset.glb_stage_create_start", **params)
            terminal, _retained = wait(accepted, outer)
            assert terminal["state"] == "SUCCEEDED"
            probes = self.control("nested_results")
            assert len(probes) == len(nested)+1, ("Actual callback boundary was not reached", kind)
            nested = probes
        row["witness"].update(canonical_slot_count=1, nested_executor_probes=nested)
        finish(row)
        row = begin("REAL_DEFERRED_PRESERVATION")
        deferred = preview("Deferred")
        accepted = start(deferred)
        terminal, retained = wait(accepted, deferred)
        assert terminal["state"] == "SUCCEEDED"
        self.owned_allocations = retained["observed_allocations"]
        row["witness"]["observation_digests"] = []
        finish(row, deferred, owned=True)
        # Countermodel replay itself is pure; keep the live deferred stage in
        # its current Runtime for real immediate/.1/.3/.5 observations.
        row = {"id": "REPORT_COUNTERMODELS", "status": "RUNNING", "requests": [], "witness": {},
            "runtime_group_start": client.runtime_group,
            "before": self.control("snapshot"), "after": None,
            "native": {"native_entries": [], "owned_reference_roles": [], "footprint_complete": False}, "history": [],
            "_tcp_start": len(self.data["tcp"])}
        self.data["cases"].append(row)
        inspect(deferred)
        row["witness"]["countermodels"] = []
        finish(row)

    def populate_countermodels(self):
        values = self.data["cases"][-1]["witness"]["countermodels"]
        values[:] = [{"kind": kind, "rejected": True, "reason": "pending independent negative replay"} for kind in COUNTERMODELS]
        for index, kind in enumerate(COUNTERMODELS):
            proposal = copy.deepcopy(self.data)
            corrupt_countermodel(proposal, kind)
            try:
                validate_runtime_transcript(proposal)
            except (AssertionError, ValueError, KeyError, IndexError, TypeError, OverflowError, RecursionError) as cause:
                values[index]["reason"] = type(cause).__name__+": "+str(cause)[:256]
            else:
                raise AssertionError(("Validator accepted a complete negative transcript", kind))


def corrupt_countermodel(proof, kind):
    first, publish = proof["cases"][:2]
    cancel = proof["cases"][6]
    if kind == "causal_tokens":
        for row in proof["tcp"]:
            if row["request"]["method"] in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start", "jobs.inspect", "jobs.cancel"}:
                row["request"]["params"].update(preview_id="unrelated_preview", stage_id="unrelated_stage", job_id="unrelated_job")
    elif kind == "causal_native":
        for row in proof["cases"][:2]:
            row["native"]["native_entries"] = []
            row["native"]["owned_reference_roles"] = []
    elif kind == "causal_refusals":
        ids = {item["request_id"] for row in proof["cases"] for item in row["witness"].get("refusals", [])}
        for row in proof["tcp"]:
            if row["request"]["id"] in ids:
                row["request"]["method"] = "bridge.status"
                row["response"]["error"] = {"code": "INTERNAL_ERROR"}
        for frame in [*proof["executor_history_frames"], *(item for row in proof["cases"] for item in row["history"])]:
            if frame["request_id"] in ids:
                frame["method"] = "bridge.status"
    elif kind == "partial_identity":
        partial = next(row for row in proof["cases"] if row["id"] == "PARTIAL_UNKNOWN_IDS")
        partial["witness"]["retained_identities"] = [["wrong", 999999]]
        partial["witness"]["raw_partial_identities"] = [["different", 88888]]
    elif kind == "disconnect_refused_start":
        ids = {row["witness"]["disconnect"]["owner_start_request_id"] for row in proof["cases"] if "disconnect" in row["witness"]}
        for row in proof["tcp"]:
            if row["request"]["id"] in ids:
                row["response"] = {"id": row["request"]["id"], "ok": False, "error": {"code": "PERMISSION_DENIED"}}
    elif kind == "history_coverage":
        for row in proof["cases"]:
            row["history"] = [{**row["history"][0], "checkpoint_entered": False, "handler_entered": False}]
    elif kind == "timer_causality":
        for series in proof["observation_series"]:
            series["started_at"] = 0.
    elif kind == "runtime":
        proof["runtime"]["canonical_queue"] = False
    elif kind == "pid":
        proof["process_id"] += 1
    elif kind == "source":
        proof["source_sha256"] = {"wrong": "0"*64}
    elif kind == "token":
        proof["process_instance"] = "0"*32
    elif kind == "loss":
        row = next(row for row in proof["tcp"] if row["request"]["method"] == "asset.glb_stage_create_start")
        row["request"]["params"]["accepted_losses"] = LOSSES[:-2]
    elif kind == "entry":
        first["native"]["native_entries"][0]["index"] = True
    elif kind == "return":
        first["native"]["native_entries"][0]["post_return_stop_checked"] = False
    elif kind == "receipt":
        next(row for row in first["native"]["mesh_return_receipts"] if row["operation"] == "WRITE_NORMALS")["body_sha256"] = "0"*64
    elif kind == "ownership":
        first["after"]["owned"].pop("object:2")
    elif kind == "edge":
        publish["after"]["scene_edges"] = publish["before"]["scene_edges"]
    elif kind == "normal":
        first["after"]["owned"]["mesh:0"]["decoded_normals"][0] = ["00000000"]*3
    elif kind == "output_target":
        next(row for row in first["after"]["owned"]["node_tree:0"]["nodes"] if row["type"] == "ShaderNodeOutputMaterial")["target"] = "CYCLES"
    elif kind == "selection":
        first["after"]["owned"]["mesh:0"]["attributes"][".select_vert"]["values"][0] = 1
    elif kind == "stop":
        cancel["native"]["entries_after_stop"] = [{"entry": "forbidden late read"}]
    elif kind == "history":
        first["history"] = []
    elif kind == "timer":
        proof["observations"][2]["elapsed_seconds"] = .299
    elif kind == "context":
        proof["observations"][-1]["snapshot"]["context"]["mode"] = "EDIT_MESH"
    elif kind == "status_only":
        proof["cases"] = [{"id": row["id"], "status": row["status"]} for row in proof["cases"]]
    elif kind == "group_reuse":
        proof["runtime_groups"][1]["runtime"]["runtime_identity"] = proof["runtime_groups"][0]["runtime"]["runtime_identity"]
    elif kind == "group_eviction":
        proof["retired_runtime_ledgers"][0]["record_evictions"] = ["lost stage"]
    elif kind == "group_native_cleanup":
        proof["retired_runtime_ledgers"][0]["native_cleanup"] = True
    elif kind == "group_stale_lookup":
        refusal = next(group["stale_lookup_refusals"][0] for group in proof["runtime_groups"][1:] if group["stale_lookup_refusals"])
        next(row for row in proof["tcp"] if row["request"]["id"] == refusal["request_id"])["response"]["ok"] = True
    elif kind == "group_request":
        proof["tcp"][-1]["runtime_group"] = len(proof["runtime_groups"])
    elif kind.startswith("disconnect_"):
        stopped = next(row for row in proof["cases"] if row["id"] == "STOP_AT_NATIVE_RETURN")
        receipt = stopped["witness"]["disconnect"]
        if kind == "disconnect_synthetic":
            receipt["synthetic_cancel"] = True
        elif kind == "disconnect_wrong_owner":
            receipt["connection_identity"] += 1
        elif kind == "disconnect_late_ack":
            receipt["network_ack_at"] = receipt["notified_at"] + 1.001
        elif kind == "disconnect_extra_access":
            stopped["native"]["native_access_counts"]["forbidden_late_access"] = {"entered": 1, "returned": 1}
        else:
            raise AssertionError(kind)
    elif kind in {"postlink_unlink", "postlink_extra_scene_change"}:
        after = next(row for row in proof["cases"] if row["id"] == "PUBLICATION_STOP_OR_FAILURE")["witness"]["after_link"]
        if kind == "postlink_unlink":
            after["after"]["scene_edges"] = after["before"]["scene_edges"]
        else:
            after["after"]["protected"]["scenes"][0]["frame"][0] += 1
    elif kind in {"constructed_timer", "published_timer"}:
        series = proof["observation_series"][0 if kind == "constructed_timer" else 1]
        series["observations"][2]["elapsed_seconds"] = .299
    elif kind in {"read_effect_write", "read_effect_single", "read_effect_hidden_passivity"}:
        effects = first["native"]["protected_mesh_read_effects"]
        if kind == "read_effect_write":
            effects["read_effects"][0]["logical_values_written"] = True
        elif kind == "read_effect_single":
            next(row for row in effects["read_effects"] if row["kind"] == "EXISTING_ARRAY_ATTRIBUTE_READ")["storage"] = "SINGLE"
        else:
            effects["hidden_layout_or_cache_passivity_qualified"] = True
    elif kind == "single_refusal_late_data":
        if not proof["single_storage_refusals"]:
            request = next(row for row in proof["tcp"] if row["delivered"] and not row["response"]["ok"])
            request["response"]["error"]["context"] = {"reason": "PROTECTED_MESH_SINGLE_REQUIRES_SEPARATE_PREPARATION"}
            proof["single_storage_refusals"].append({"request_id": request["request"]["id"], "runtime_group": request["runtime_group"],
                "error": copy.deepcopy(request["response"]["error"]), "headers": [{"attributes": [{"storage": "SINGLE"}]}],
                "native_access_counts": {}, "protected_read_effect_attempts": [], "checkpoint_marker_entries": 0,
                "mesh_target": None, "recorded_at": request["received_at"]+.01})
            request["request"]["method"] = "asset.glb_stage_preview"
            for case in proof["cases"]:
                for history in case["history"]:
                    if history["request_id"] == request["request"]["id"]:
                        history["method"] = "asset.glb_stage_preview"
        proof["single_storage_refusals"][0]["native_access_counts"]["get:data"] = {"entered": 1, "returned": 1}
    elif kind == "empty_read_nonzero":
        observation = next(row for row in proof["raw_observation_read_effects"]
            if row["scope"] == "TRUSTED_RAW_FIXTURE_OBSERVER_NOT_RUNTIME_AUTHORITY"
            and any(row["mesh_profile"]["counts"].values()))
        observation["read_effects"] = []
    elif kind in {"unbacked_preparation", "preparation_before_refusal", "preparation_different_headers"}:
        if not proof["raw_storage_preparations"]:
            request = next(row for row in proof["tcp"] if row["delivered"] and not row["response"]["ok"])
            request["response"]["error"]["context"] = {"reason": "PROTECTED_MESH_SINGLE_REQUIRES_SEPARATE_PREPARATION"}
            request["request"]["method"] = "asset.glb_stage_preview"
            for case in proof["cases"]:
                for history in case["history"]:
                    if history["request_id"] == request["request"]["id"]:
                        history["method"] = "asset.glb_stage_preview"
            headers = [{"identity": {"uid": 123}, "attributes": [{"name": "injected", "storage": "SINGLE"}]}]
            refusal = {"request_id": request["request"]["id"], "runtime_group": request["runtime_group"],
                "error": copy.deepcopy(request["response"]["error"]), "headers": headers, "mesh_target": None,
                "native_access_counts": {}, "protected_read_effect_attempts": [], "checkpoint_marker_entries": 0,
                "recorded_at": request["received_at"]+.01}
            proof["single_storage_refusals"].append(refusal)
            proof["raw_storage_preparations"].append({"scope": "RAW_OWNED_FIXTURE_PREPARATION_NOT_BRIDGE_API",
                "scalar_float_or_unknown_conversion": False, "logical_values_reset": False, "record_evictions": [], "native_qualified": False,
                "runtime_group": refusal["runtime_group"], "mesh_target": None, "refusal_request_id": refusal["request_id"],
                "before_headers": copy.deepcopy(headers), "started_at": refusal["recorded_at"]+.01, "finished_at": refusal["recorded_at"]+.02})
        preparation = proof["raw_storage_preparations"][0]
        if kind == "unbacked_preparation":
            preparation["refusal_request_id"] = "no_genuine_SINGLE_refusal"
        elif kind == "preparation_before_refusal":
            refusal = next(row for row in proof["single_storage_refusals"] if row["request_id"] == preparation["refusal_request_id"])
            preparation["started_at"] = refusal["recorded_at"]-.001
        else:
            preparation["before_headers"] = copy.deepcopy(preparation["before_headers"])
            preparation["before_headers"][0]["identity"]["uid"] += 1
    else:
        raise AssertionError(kind)


def main():
    # Blender executes this file from its isolated working directory without
    # adding the checkout root. Resolve our sibling helper before its ownership
    # checks establish the remaining fixture import paths.
    sys.path.insert(0, str(Path(__file__).resolve(strict=True).parents[1]))
    from scripts.blender_glb_stage_smoke import owned_entry
    root, folder, bpy, attestation = owned_entry()
    fixture = RuntimeFixture(root, folder, bpy, attestation)
    fixture.flush()
    def start():
        try:
            fixture.setup()
        except BaseException:
            fixture.finish(1, traceback.format_exc())
        return None
    bpy.app.timers.register(start, first_interval=.2)


if __name__ == "__main__":
    main()
