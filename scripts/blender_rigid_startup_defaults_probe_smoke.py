"""Ordinary interactive startup rigid defaults/ownership research, not a tool.

Run only through the isolated native runner. The factory Scene and every
pre-existing ID remain present. No cache bake, project save, preferences save,
public setup API or counter normalization is performed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from addon import blender_codex_bridge  # noqa: E402
from addon.blender_codex_bridge.errors import BridgeError  # noqa: E402
from addon.blender_codex_bridge.tools import _rigid_body_scope as cache_scope  # noqa: E402
from addon.blender_codex_bridge.tools._object_rna_mutation import object_state  # noqa: E402
from scripts.blender_rigid_lifecycle_probe_smoke import context_state, cube  # noqa: E402

MARKER = "BLENDER_RIGID_STARTUP_DEFAULTS_PROBE_OK "
BUILDS = {
    "62c1db4208e8": ("62c1db4208e862312bc36db5bc15d4a6dbcfa3e3", "7532f8fd4f4f703c205eba61c53b37470ae2d595"),
    "d13f752e3b9c": ("d13f752e3b9c4f8c261cda552b1021f8bcc0382c", "a39a8dbc3f56700b7904f3885fa284a06eb15272"),
}
SCALAR = frozenset({"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"})


def identity(owner: Any) -> Any:
    if owner is None:
        return None
    return {"type": owner.bl_rna.identifier, "pointer": owner.as_pointer(),
            "session_uid": getattr(owner, "session_uid", None), "name": getattr(owner, "name", None)}


def plain(value: Any, *, depth: int = 0) -> Any:
    assert depth <= 8
    if value is None or type(value) in {str, bool, int}:
        assert not isinstance(value, str) or len(value) <= 4096
        return value
    if type(value) is float:
        assert math.isfinite(value)
        return value
    if isinstance(value, bpy.types.ID):
        return {"ID": identity(value)}
    if hasattr(value, "as_pointer"):
        return {"RNA": identity(value)}
    if hasattr(value, "keys"):
        names = list(value.keys())
        assert len(names) <= 128
        return {str(name): plain(value[name], depth=depth + 1) for name in sorted(names)}
    items = list(value)
    assert len(items) <= 256
    return [plain(item, depth=depth + 1) for item in items]


def custom(owner: Any) -> Any:
    try:
        names = list(owner.keys())
    except TypeError as error:
        assert "doesn't support IDProperties" in str(error)
        return {}
    assert len(names) <= 128
    return {name: plain(owner[name]) for name in sorted(names)}


def native_fields(owner: Any, *, collection_type: str | None = None) -> dict[str, Any]:
    """Capture native defaults after screening descriptors, without runtime getters."""
    if collection_type is None:
        rna = owner.bl_rna
        canonical = getattr(bpy.types, rna.identifier)
        assert rna == canonical.bl_rna
    else:
        # A bpy_prop_collection exposes its collection-wrapper selectors through
        # the canonical collection StructRNA, rather than the entry fixed_type.
        rna = getattr(bpy.types, collection_type).bl_rna
        assert rna.identifier == collection_type
    properties = list(rna.properties)
    assert len(properties) <= 512
    values, schema, excluded = {}, {}, {}
    for prop in properties:
        field = prop.identifier
        if field == "rna_type":
            continue
        schema[field] = {"type": prop.type, "readonly": prop.is_readonly,
                         "runtime": prop.is_runtime, "array_length": getattr(prop, "array_length", 0)}
        if prop.is_runtime:
            excluded[field] = "UNREAD_RUNTIME"
            continue
        if prop.type in SCALAR | {"POINTER"}:
            values[field] = plain(getattr(owner, field))
        else:
            excluded[field] = prop.type
    return {"identity": identity(owner) if collection_type is None else {"collection_type": collection_type},
            "values": values, "schema": schema, "excluded": excluded,
            "custom": custom(owner) if collection_type is None else {}}


def descriptor(owner: Any, name: str, kind: str) -> Any:
    prop = owner.bl_rna.properties.get(name)
    assert prop is not None and prop.type == kind and not prop.is_runtime
    return getattr(owner, name)


def has_id_reference(value: Any) -> bool:
    if isinstance(value, dict):
        return "ID" in value or any(has_id_reference(item) for item in value.values())
    return isinstance(value, list) and any(has_id_reference(item) for item in value)


def scene_roles(scene: Any) -> dict[str, Any]:
    """Record exact-build native Scene roles; never change native counters."""
    build = bpy.app.build_hash.decode("ascii")
    assert build in BUILDS
    ctx, wm = bpy.context, bpy.context.window_manager
    assert len(bpy.data.scenes) == 1 and bpy.data.scenes[0] == scene
    assert list(descriptor(wm, "windows", "COLLECTION")) == [ctx.window]
    assert descriptor(ctx.window, "scene", "POINTER") == scene
    assert descriptor(ctx.window, "view_layer", "POINTER") == ctx.view_layer
    assert descriptor(ctx.window, "workspace", "POINTER") == ctx.workspace
    assert descriptor(ctx.workspace, "use_pin_scene", "BOOLEAN") is False
    raw = {"window_manager": custom(wm), "window": custom(ctx.window), "workspace": custom(ctx.workspace)}
    assert not has_id_reference(raw), "Raw UI ID aliases prevent native role inference"
    incoming = list(bpy.data.user_map(subset={scene}).get(scene, ()))
    external = [owner for owner in incoming if owner != scene]
    assert external == [wm]
    references = int(wm.user_of_id(scene))
    assert references == 2, "This research pins the ordinary startup's two native Scene roles"
    assert int(scene.users) - int(bool(scene.use_fake_user)) == 1
    loopback = [owner for owner in incoming if owner == scene]
    if loopback:
        assert len(loopback) == 1 and scene.user_of_id(scene) == 1
        assert scene.original == scene and not scene.is_evaluated and scene.use_extra_user
    return {"wm_reference_count": references, "scene_users": int(scene.users),
            "scene_fake_user": bool(scene.use_fake_user), "scene_self_references": int(scene.user_of_id(scene)),
            "scene_original": identity(scene.original), "scene_extra_user": bool(scene.use_extra_user),
            "actual_scene": identity(scene), "actual_window": identity(ctx.window),
            "actual_workspace": identity(ctx.workspace), "main_scenes": len(bpy.data.scenes),
            "actual_windows": len(wm.windows), "workspace_unpinned": True, "raw_ui_properties": raw,
            "inferred_roles": ["win.scene USER_ONE"] + (["win.unpinned_scene NOP"] if references == 2 else []),
            "unpinned_scene_publicly_readable": "unpinned_scene" in ctx.window.bl_rna.properties,
            "upstream_commit": BUILDS[build][0], "wm_cc_git_blob": BUILDS[build][1],
            "upstream_exact_bytes_receipt_sha256": "7bd654cff7f1ff7eafda0096b6701eba0d2fa9de2f514a64f48c8d606093dcfe",
            "count_normalization_performed": False}


def physics_defaults(scene: Any, bodies: list[Any]) -> dict[str, Any]:
    world = descriptor(scene, "rigidbody_world", "POINTER")
    assert world is not None
    cache = descriptor(world, "point_cache", "POINTER")
    container = descriptor(cache, "point_caches", "COLLECTION")
    entries = list(container)
    assert len(entries) <= 8
    result = {"world": native_fields(world),
              "effector_weights": native_fields(descriptor(world, "effector_weights", "POINTER")),
              "point_cache": native_fields(cache),
              "point_cache_collection_selectors": native_fields(container, collection_type="PointCaches"),
              "point_cache_collection": [native_fields(entry) for entry in entries],
              "bodies": {obj.name: native_fields(obj.rigid_body) for obj in bodies if obj.rigid_body is not None}}
    assert "active_index" in result["point_cache_collection_selectors"]["values"]
    leaves = [result[key] for key in ("world", "effector_weights", "point_cache", "point_cache_collection_selectors")]
    leaves += result["point_cache_collection"] + list(result["bodies"].values())
    result["unread_native_fields"] = [
        {"owner": leaf["identity"], "field": field, "reason": reason}
        for leaf in leaves for field, reason in leaf["excluded"].items()
        if not (leaf is result["point_cache"] and field == "point_caches" and reason == "COLLECTION")
    ]
    result["complete_default_vector"] = not result["unread_native_fields"]
    assert result["complete_default_vector"], result["unread_native_fields"]
    return result


def cache_admission(scene: Any, bodies: list[Any]) -> dict[str, Any]:
    """Report current product helper compatibility, including honest refusals."""
    try:
        captured = cache_scope.snapshot(bpy, scene, {"body_names": [obj.name for obj in bodies], "constraint_names": []})
    except BridgeError as error:
        return {"complete": False, "error": error.to_dict(), "existing_helper_unchanged": True}
    return {"complete": True, "snapshot_sha256": digest(captured), "existing_helper_unchanged": True}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def identities() -> dict[str, Any]:
    return {prop.identifier: [identity(owner) for owner in getattr(bpy.data, prop.identifier)]
            for prop in bpy.data.bl_rna.properties
            if prop.type == "COLLECTION" and prop.identifier != "all_ids"}


def run_case(scene: Any, count: int) -> dict[str, Any]:
    original_context = context_state()
    before_ids = identities()
    original_objects = {obj.name: object_state(obj, exclude_object_rna=frozenset({"active_selection_set"}))
                        for obj in scene.objects}
    before_roles = scene_roles(scene)
    assert scene.rigidbody_world is None
    body_collection = bpy.data.collections.new(f"Owned Startup Probe {count} Bodies")
    constraint_collection = bpy.data.collections.new(f"Owned Startup Probe {count} Constraints")
    for collection in (body_collection, constraint_collection):
        scene.collection.children.link(collection)
    bodies = [cube(body_collection, f"Owned Startup Probe {count} Body {index}",
                   location=(index * 3., 6., index + 3.)) for index in range(count)]
    body_channels = {obj.name: object_state(obj, exclude_object_rna=frozenset({"active_selection_set"})) for obj in bodies}
    calls = []

    def operator(label: str, op: Any, *, obj: Any = None, **kwargs: Any) -> None:
        override = {"scene": scene, "view_layer": bpy.context.view_layer}
        if obj is not None:
            override.update(object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj])
        stamp = time.monotonic()
        with bpy.context.temp_override(**override):
            assert op.poll(), label
            assert op("EXEC_DEFAULT", **kwargs) == {"FINISHED"}, label
        calls.append({"stage": label, "seconds": time.monotonic() - stamp, "native_preemptible": False})
        assert context_state() == original_context

    operator("world_add", bpy.ops.rigidbody.world_add)
    unbound = physics_defaults(scene, bodies)
    world = scene.rigidbody_world
    world.time_scale, world.substeps_per_frame, world.solver_iterations = .75, 1, 4
    world.point_cache.frame_start, world.point_cache.frame_end = 1, 3
    world.collection = body_collection
    allocated = physics_defaults(scene, bodies)
    assert len(allocated["bodies"]) == count
    assert all(obj.rigid_body.type == "ACTIVE" and obj.rigid_body.collision_shape == "CONVEX_HULL" for obj in bodies)
    world.constraints = constraint_collection
    allocated_pointers = {obj.name: obj.rigid_body.as_pointer() for obj in bodies}
    for index, obj in enumerate(bodies):
        operator(f"body_role_{index}", bpy.ops.rigidbody.object_add, obj=obj,
                 type="PASSIVE" if index == count - 1 else "ACTIVE")
        assert obj.rigid_body.as_pointer() == allocated_pointers[obj.name]
        obj.rigid_body.collision_shape = "BOX"
    configured = physics_defaults(scene, bodies)
    roles_after_setup = scene_roles(scene)
    admission_before_checkpoint = cache_admission(scene, bodies)
    operator("native_undo_push", bpy.ops.ed.undo_push, message="Owned ordinary rigid defaults research")
    roles_after_checkpoint = scene_roles(scene)
    admission_after_checkpoint = cache_admission(scene, bodies)
    for admission in (admission_before_checkpoint, admission_after_checkpoint):
        assert admission["complete"] is False, "Keep this unchanged-helper compatibility failure explicit"
        assert admission["error"] == {
            "code": "NOT_IMPLEMENTED",
            "message": "The simulation Scene has external consumers outside the current window context.",
        }
    protected_after = {obj.name: object_state(obj, exclude_object_rna=frozenset({"active_selection_set"}))
                       for obj in scene.objects if obj.name in original_objects}
    body_channels_after = {obj.name: object_state(obj, exclude_object_rna=frozenset({"active_selection_set"})) for obj in bodies}
    assert protected_after == original_objects
    assert body_channels_after == body_channels
    world.constraints, world.collection = None, None
    operator("world_remove", bpy.ops.rigidbody.world_remove)
    for index, obj in reversed(list(enumerate(bodies))):
        operator(f"body_remove_{index}", bpy.ops.rigidbody.object_remove, obj=obj)
        assert obj.rigid_body is None and list(obj.users_collection) == [body_collection]
    assert scene.rigidbody_world is None and context_state() == original_context
    protected_after_cleanup = {
        obj.name: object_state(obj, exclude_object_rna=frozenset({"active_selection_set"}))
        for obj in scene.objects if obj.name in original_objects
    }
    body_channels_after_cleanup = {
        obj.name: object_state(obj, exclude_object_rna=frozenset({"active_selection_set"})) for obj in bodies
    }
    assert protected_after_cleanup == original_objects
    assert body_channels_after_cleanup == body_channels
    after_ids = identities()
    originals_present = all(all(item in after_ids[family] for item in owners) for family, owners in before_ids.items())
    assert originals_present
    return {"body_count": count, "ordinary_scene": identity(scene), "original_context": original_context,
            "original_ids_all_preserved": originals_present, "original_object_authored_state_preserved": True,
            "body_authored_state_preserved": True, "authored_comparisons_after_cleanup": True,
            "roles_before": before_roles,
            "unbound_constructor_defaults": unbound, "populated_binding_defaults": allocated,
            "configured_physics": configured, "roles_after_setup": roles_after_setup,
            "roles_after_checkpoint": roles_after_checkpoint,
            "existing_cache_admission_before_checkpoint": admission_before_checkpoint,
            "existing_cache_admission_after_checkpoint": admission_after_checkpoint,
            "world_and_all_body_settings_removed": True, "cleanup_membership_preserved": True,
            "fixture_owned_ids_retained": [identity(body_collection), identity(constraint_collection),
                                           *(identity(obj) for obj in bodies)],
            "operator_calls": calls,
            "full_shader_uv_light_linking_preservation_qualified": False,
            "canonical_request_recovery_qualified": False}


def main() -> None:
    assert not bpy.app.background
    assert os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"), "Use the isolated native runner"
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    scene = bpy.context.scene
    assert len(bpy.data.scenes) == 1
    assert {"Cube", "Camera", "Light"}.issubset(scene.objects.keys()), "Preserve the ordinary factory startup Scene"
    rows = [run_case(scene, count) for count in (1, 16)]
    report = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode("ascii"),
              "ordinary_startup_scene_preserved": True, "factory_scene_replaced_or_emptied": False,
              "complete_default_vector_research": all(
                  row[stage]["complete_default_vector"] for row in rows
                  for stage in ("unbound_constructor_defaults", "populated_binding_defaults", "configured_physics")
              ), "cases": rows,
              "public_setup_api_added": False, "product_counter_admission_changed": False,
              "canonical_request_recovery_qualified": False, "project_saved": False,
              "release_readiness": "NOT_ASSESSED"}
    path = Path(os.environ["TMPDIR"]) / "rigid-startup-defaults-research.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(MARKER + json.dumps({"blender_version": bpy.app.version_string, "build_hash": report["build_hash"],
        "evidence": str(path), "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "body_counts": [row["body_count"] for row in rows],
        "existing_cache_admission_complete": [row["existing_cache_admission_after_checkpoint"]["complete"] for row in rows],
        "ordinary_startup_scene_preserved": True, "public_setup_api_added": False,
        "release_readiness": "NOT_ASSESSED"}), flush=True)


def timer() -> None:
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()


bpy.app.timers.register(timer, first_interval=.25)
