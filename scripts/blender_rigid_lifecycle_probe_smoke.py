"""Small owned rigid-body lifecycle research; run through the isolated runner.

No product API, disk-cache flags or global cancellation operators are used.
The writer measures complete shuffled matrices and same-value invalidation; the
reader starts from a saved first frame so forward evaluation cannot conceal an
unserialized memory cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.blender_simulation_cache_probe_smoke import POINT_CACHE_FIELDS  # noqa: E402
from scripts.native_cache_evidence import snapshot_files  # noqa: E402

WRITER = "BLENDER_RIGID_LIFECYCLE_PROBE_WRITER_OK "
READER = "BLENDER_RIGID_LIFECYCLE_PROBE_READER_OK "
FRAMES = (3, 1, 2)


def identity(owner):
    return {"type": owner.bl_rna.identifier, "name": owner.name,
            "session_uid": owner.session_uid}


def context_state():
    context = bpy.context
    layer = context.view_layer
    return {"scene": identity(context.scene), "view_layer": layer.name,
            "active": layer.objects.active.name if layer.objects.active else None,
            "selected": sorted(obj.name for obj in layer.objects if obj.select_get()),
            "context_active": context.active_object.name if context.active_object else None,
            "context_object": context.object.name if context.object else None,
            "context_selected": sorted(obj.name for obj in context.selected_objects),
            "mode": context.mode, "frame": context.scene.frame_current,
            "subframe": context.scene.frame_subframe}


def cache_state(cache):
    return {key: getattr(cache, key) for key in POINT_CACHE_FIELDS if hasattr(cache, key)}


def plain_properties(owner):
    """Retain the complete native scalar/array RNA inventory for this fixture."""
    result, excluded, definitions = {}, {}, {}
    for prop in owner.bl_rna.properties:
        key = prop.identifier
        if key == "rna_type":
            continue
        value = getattr(owner, key)
        if prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            result[key] = list(value) if getattr(prop, "is_array", False) else value
            definitions[key] = {"type": prop.type, "writable": not prop.is_readonly,
                                "array_length": getattr(prop, "array_length", 0)}
        elif prop.type == "POINTER" and (value is None or isinstance(value, bpy.types.ID)):
            result[key] = None if value is None else identity(value)
        else:
            excluded[key] = prop.type
    return {"values": result, "scalar_definitions": definitions,
            "non_scalar_properties": excluded}


def matrix(obj, depsgraph):
    return [float(value) for row in obj.evaluated_get(depsgraph).matrix_world for value in row]


def sample(scene, bodies, frames=FRAMES):
    assert bpy.context.scene is scene
    rows = []
    for frame in frames:
        scene.frame_set(frame, subframe=0.)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        rows.append({"frame": frame, "matrices": {obj.name: matrix(obj, graph) for obj in bodies}})
    return rows


def max_delta(left, right, left_bodies, right_bodies):
    assert [row["frame"] for row in left] == [row["frame"] for row in right]
    return max(abs(a-b) for lr, rr in zip(left, right, strict=True)
               for lo, ro in zip(left_bodies, right_bodies, strict=True)
               for a, b in zip(lr["matrices"][lo.name], rr["matrices"][ro.name], strict=True))


def cube(collection, name, *, location, scale=(1., 1., 1.)):
    mesh = bpy.data.meshes.new(name + " Mesh")
    mesh.from_pydata([(x*.5, y*.5, z*.5) for x, y, z in
        ((-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
         (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1))], [],
        [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
         (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location, obj.scale = location, scale
    return obj


def make_scene(label, gravity):
    scene = bpy.data.scenes.new(label)
    bpy.context.window.scene = scene
    scene.frame_start, scene.frame_end = 1, 3
    scene.gravity = gravity
    collection = bpy.data.collections.new(label + " Bodies")
    constraints = bpy.data.collections.new(label + " Constraints")
    scene.collection.children.link(collection)
    scene.collection.children.link(constraints)
    assert bpy.ops.rigidbody.world_add() == {"FINISHED"}
    world = scene.rigidbody_world
    world.collection, world.constraints = collection, constraints
    world.time_scale, world.substeps_per_frame, world.solver_iterations = .75, 1, 4
    world.point_cache.frame_start, world.point_cache.frame_end = 1, 3
    world.point_cache.frame_step = 1
    bodies = [cube(collection, label + " A", location=(0., 0., 3.)),
              cube(collection, label + " B", location=(4., 0., 5.)),
              cube(collection, label + " Floor", location=(0., 0., -1.), scale=(20., 20., .2))]
    context = bpy.context
    for index, obj in enumerate(bodies):
        with context.temp_override(scene=scene, view_layer=scene.view_layers[0],
                object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
            assert bpy.ops.rigidbody.object_add(type="ACTIVE" if index < 2 else "PASSIVE") == {"FINISHED"}
        obj.rigid_body.collision_shape = "BOX"
    sentinel = bpy.data.objects.new(label + " Context Sentinel", None)
    scene.collection.objects.link(sentinel)
    for obj in scene.objects:
        obj.select_set(False)
    sentinel.select_set(True)
    scene.view_layers[0].objects.active = sentinel
    bpy.context.view_layer.update()
    assert not world.point_cache.use_disk_cache and not world.point_cache.use_external
    return scene, bodies, sentinel


def point_call(scene, obj, operation):
    cache = scene.rigidbody_world.point_cache
    before = context_state()
    started = time.monotonic()
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0],
                                  object=obj, active_object=obj, point_cache=cache):
        effective_override = context_state()
        operator = bpy.ops.ptcache.bake if operation == "BAKE" else bpy.ops.ptcache.free_bake
        assert operator.poll()
        status = operator("EXEC_DEFAULT", **({"bake": True} if operation == "BAKE" else {}))
    after = context_state()
    assert status == {"FINISHED"}, status
    for key in ("scene", "view_layer", "active", "selected", "mode"):
        assert before[key] == after[key], (operation, key, before, after)
    return {"operation": operation, "status": sorted(status),
            "blocking_ms": (time.monotonic()-started)*1000,
            "before": before, "effective_override": effective_override,
            "after": after, "cache": cache_state(cache)}


def invalidate(world, *, toggle):
    before = world.time_scale
    if toggle:
        world.time_scale = .5 if before != .5 else .75
    world.time_scale = before
    assert world.time_scale == before
    return {"strategy": "toggle_then_restore" if toggle else "same_value_setter",
            "time_scale_before": before, "time_scale_after": world.time_scale,
            "cache": cache_state(world.point_cache)}


def normalized_bake(scene, bodies, *, toggle):
    original = (scene.frame_current, scene.frame_subframe)
    reset = invalidate(scene.rigidbody_world, toggle=toggle)
    assert not scene.rigidbody_world.point_cache.is_baked
    scene.frame_set(1, subframe=0.)
    started = time.monotonic()
    reference = sample(scene, bodies, frames=(1, 2, 3))
    reference_ms = (time.monotonic()-started)*1000
    reference_cache = cache_state(scene.rigidbody_world.point_cache)
    before_native_reset = invalidate(scene.rigidbody_world, toggle=toggle)
    scene.frame_set(1, subframe=0.)
    call = point_call(scene, bodies[0], "BAKE")
    samples = sample(scene, bodies)
    reference_shuffled = [{row["frame"]: row for row in reference}[frame] for frame in FRAMES]
    error = max_delta(samples, reference_shuffled, bodies, bodies)
    assert error < 1e-7, (error, samples, reference)
    scene.frame_set(original[0], subframe=original[1])
    assert (scene.frame_current, scene.frame_subframe) == original
    return {"invalidation": reset, "native": call, "samples": samples,
            "unbaked_sequential_reference": reference, "reference_blocking_ms": reference_ms,
            "reference_cache": reference_cache, "reset_after_reference": before_native_reset,
            "baked_vs_unbaked_reference_maximum_error": error,
            "caller_time_before": list(original), "caller_time_after": [scene.frame_current, scene.frame_subframe],
            "cache_after_time_restore": cache_state(scene.rigidbody_world.point_cache)}


def ownership(scene, bodies):
    world = scene.rigidbody_world
    ids = {scene, scene.collection, world.collection, world.constraints, *bodies,
           *(obj.data for obj in bodies)}
    user_map = bpy.data.user_map(subset=ids)
    rows = []
    for owner in sorted(ids, key=lambda item: (item.bl_rna.identifier, item.name)):
        rows.append({**identity(owner), "users": owner.users, "fake_user": owner.use_fake_user,
                     "direct_user_map_count": len(user_map.get(owner, ())),
                     "direct_users": sorted(({**identity(user), "references": int(user.user_of_id(owner))}
                                             for user in user_map.get(owner, ())),
                                            key=lambda item: (item["type"], item["name"])),
                     **({"users_scene": sorted(item.name for item in owner.users_scene),
                         "users_collection": sorted(item.name for item in owner.users_collection)}
                        if isinstance(owner, bpy.types.Object) else {})})
    other = bpy.data.scenes.new("Owned Shared-Collection Observer")
    other.collection.children.link(world.collection)
    shared = {"collection_users": world.collection.users,
              "collection_direct_users": [{**identity(user), "references": int(user.user_of_id(world.collection))}
                                          for user in bpy.data.user_map(subset={world.collection}).get(world.collection, ())],
              "body_users_scene": {obj.name: sorted(item.name for item in obj.users_scene) for obj in bodies}}
    other.collection.children.unlink(world.collection)
    assert all(list(obj.users_scene) == [scene] for obj in bodies)
    collection = world.collection
    reference_roles = {"root_child_references": int(scene.collection.user_of_id(collection)),
                       "scene_references": int(scene.user_of_id(collection)),
                       "native_users": collection.users,
                       "current_layer_child_points_to_collection":
                           scene.view_layers[0].layer_collection.children[collection.name].collection is collection}
    world.collection = None
    reference_roles["without_world_pointer"] = {"scene_references": int(scene.user_of_id(collection)),
                                                 "native_users": collection.users}
    world.collection = collection
    extra_layer = scene.view_layers.new("Owned Reference Count Layer")
    extra_layer.update()
    reference_roles["with_second_layer"] = {"scene_references": int(scene.user_of_id(collection)),
                                             "native_users": collection.users,
                                             "new_layer_child_points_to_collection":
                                                 extra_layer.layer_collection.children[collection.name].collection is collection}
    scene.view_layers.remove(extra_layer)
    reference_roles["restored"] = {"scene_references": int(scene.user_of_id(collection)),
                                   "native_users": collection.users, "view_layers": len(scene.view_layers)}
    assert reference_roles["root_child_references"] == 1
    assert reference_roles["without_world_pointer"] == {"scene_references": 2, "native_users": 1}
    assert reference_roles["with_second_layer"] == {"scene_references": 4, "native_users": 2,
                                                    "new_layer_child_points_to_collection": True}
    assert reference_roles["restored"] == {"scene_references": 3, "native_users": 2, "view_layers": 1}
    return {"owned_ids": rows, "shared_collection_observation": shared,
            "body_collection_reference_roles": reference_roles,
            "world_properties": plain_properties(world),
            "effector_weights": plain_properties(world.effector_weights),
            "body_properties": {obj.name: plain_properties(obj.rigid_body) for obj in bodies}}


def marker(prefix, payload):
    print(prefix + json.dumps({**payload, "blender": bpy.app.version_string,
          "phase": "writer" if prefix == WRITER else "reader",
          "process_id": os.getpid(), "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
          "release_readiness": "NOT_ASSESSED", "public_api_added": False,
          "disk_cache_flags_touched": False, "global_cancel_used": False}), flush=True)


def writer(bundle):
    bpy.context.preferences.use_preferences_save = False
    scene, bodies, sentinel = make_scene("Owned Lifecycle", (0., 0., -9.81))
    authored = ownership(scene, bodies)
    assert bpy.context.view_layer.objects.active is sentinel
    temp = Path(os.environ["TMPDIR"])
    before_files = snapshot_files(temp)
    scene.frame_set(7, subframe=.25)
    fractional = point_call(scene, bodies[0], "BAKE")
    fractional_samples = sample(scene, bodies)
    fractional["samples"] = fractional_samples
    point_call(scene, bodies[0], "FREE")
    scene.frame_set(7, subframe=.25)
    baseline = normalized_bake(scene, bodies, toggle=False)
    assert baseline["samples"][0]["matrices"][bodies[0].name][11] < baseline["samples"][1]["matrices"][bodies[0].name][11]
    scene.gravity = (0., 0., 0.)
    bpy.context.view_layer.update()
    # Revisit the still-baked old motion before FREE, matching the prior
    # stale-cache sequence. FREE alone does not promise native solver reset.
    changed_gravity_before_free = sample(scene, bodies)
    point_call(scene, bodies[0], "FREE")
    stale_bake = point_call(scene, bodies[0], "BAKE")
    stale_samples = sample(scene, bodies)
    stale_bake["samples"] = stale_samples
    point_call(scene, bodies[0], "FREE")
    scene.frame_set(7, subframe=.25)
    zero = normalized_bake(scene, bodies, toggle=False)
    zero_scene, zero_bodies, _zero_sentinel = make_scene("Owned Zero Control", (0., 0., 0.))
    zero_control = normalized_bake(zero_scene, zero_bodies, toggle=False)
    zero_delta = max_delta(zero["samples"], zero_control["samples"], bodies, zero_bodies)
    assert zero_delta < 1e-7, (zero_delta, zero, zero_control)
    stale_previous_error = max_delta(stale_samples, baseline["samples"], bodies, bodies)
    stale_zero_error = max_delta(stale_samples, zero_control["samples"], bodies, zero_bodies)
    bpy.context.window.scene = scene
    scene.gravity = (0., 0., -4.905)
    point_call(scene, bodies[0], "FREE")
    scene.frame_set(7, subframe=.25)
    half = normalized_bake(scene, bodies, toggle=True)
    half_scene, half_bodies, _half_sentinel = make_scene("Owned Half Control", (0., 0., -4.905))
    half_control = normalized_bake(half_scene, half_bodies, toggle=False)
    half_delta = max_delta(half["samples"], half_control["samples"], bodies, half_bodies)
    assert half_delta < 1e-7, (half_delta, half, half_control)
    bpy.context.window.scene = scene
    assert snapshot_files(temp) == before_files, "Memory-only cache sequence wrote files in the owned temp tree"
    assert scene.rigidbody_world.time_scale == .75
    assert context_state()["active"] == sentinel.name
    assert (scene.frame_current, scene.frame_subframe) == (7, .25)
    # Deliberate fixture-only save at frame1 avoids file-open forward evaluation
    # filling absent frame2/3 data before the fresh reader tests last-frame first.
    scene.frame_set(1, subframe=0.)
    project = bundle / "rigid-memory.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(project)) == {"FINISHED"}
    report = {"fractional_negative": fractional, "baseline": baseline, "free_only_after_gravity_change": stale_bake,
              "gravity_changed_while_baked_samples": changed_gravity_before_free,
              "free_only_previous_gravity_maximum_error": stale_previous_error,
              "free_only_zero_gravity_control_maximum_error": stale_zero_error,
              "free_only_recomputed_zero_gravity": stale_zero_error < 1e-7,
              "same_value_invalidation_zero_gravity": zero, "same_value_zero_control_error": zero_delta,
              "toggle_restore_invalidation_half_gravity": half, "toggle_half_control_error": half_delta,
              "ownership": authored, "memory_sequence_created_no_files": True,
              "protected_active_selection_preserved": True, "caller_fractional_time_restored": True,
              "scene_name": scene.name, "body_names": [obj.name for obj in bodies], "sentinel_name": sentinel.name,
              "expected_samples": half["samples"], "cache_at_save": cache_state(scene.rigidbody_world.point_cache),
              "saved_frame": scene.frame_current, "saved_subframe": scene.frame_subframe,
              "project": project.name, "project_sha256": hashlib.sha256(project.read_bytes()).hexdigest()}
    evidence = bundle / "rigid-lifecycle-writer.json"
    evidence.write_text(json.dumps(report, indent=2), encoding="utf-8")
    marker(WRITER, {"evidence": evidence.name, "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                   "same_value_invalidation_error": zero_delta, "toggle_restore_invalidation_error": half_delta,
                   "caller_fractional_time_restored": True, "project_sha256": report["project_sha256"]})


def reader(bundle):
    expected = json.loads((bundle / "rigid-lifecycle-writer.json").read_text())
    project = bundle / expected["project"]
    assert hashlib.sha256(project.read_bytes()).hexdigest() == expected["project_sha256"]
    bpy.ops.wm.open_mainfile(filepath=str(project))
    scene = bpy.data.scenes[expected["scene_name"]]
    bpy.context.window.scene = scene
    bodies = [bpy.data.objects[name] for name in expected["body_names"]]
    initial_cache = cache_state(scene.rigidbody_world.point_cache)
    assert scene.frame_current == 1 and scene.frame_subframe == 0.
    assert scene.rigidbody_world.time_scale == .75
    assert all(obj in scene.rigidbody_world.collection.objects.values() for obj in bodies)
    actual = sample(scene, bodies)
    error = max_delta(actual, expected["expected_samples"], bodies, bodies)
    result = {"initial_cache": initial_cache, "cache_at_save": expected["cache_at_save"],
              "last_frame_first_samples": actual, "last_frame_first_maximum_error": error,
              "reopened_baked_flag": initial_cache["is_baked"],
              "playback_matches_saved_bake": error < 1e-7,
              "bounded_saved_memory_cache_playback_proven": initial_cache["is_baked"] and error < 1e-7,
              "general_cache_durability_proven": False,
              "project_file_unchanged": hashlib.sha256(project.read_bytes()).hexdigest() == expected["project_sha256"]}
    path = bundle / "rigid-lifecycle-reader.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    marker(READER, {**result, "evidence": path.name, "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    bundle = args.bridge_bundle.resolve(strict=True)
    (writer if args.bridge_phase == "writer" else reader)(bundle)


if __name__ == "__main__":
    main()
