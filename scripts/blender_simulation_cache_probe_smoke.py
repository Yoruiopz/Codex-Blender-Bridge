"""Private native cache research; execute only through the isolated native runner.

No public bridge API is added. Every scene, cache, project and deletion sentinel is
created by this fixture. Fluid FREE uses the UI event loop on Blender 4.5; FINISHED
alone is not completion evidence. No global pause/break/cancel operator is invoked.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.native_cache_evidence import compare_files, snapshot_files  # noqa: E402

MARKER = "BLENDER_SIMULATION_CACHE_PROBE_OK "
POINT_CACHE_FIELDS = ("frame_start", "frame_end", "frame_step", "is_baked", "is_baking",
                      "is_outdated", "is_frame_skip", "use_disk_cache", "use_external",
                      "use_library_path", "filepath", "name", "index", "info")
FLUID_FIELDS = ("cache_type", "cache_directory", "cache_frame_start", "cache_frame_end",
                "cache_frame_pause_data", "cache_frame_pause_noise", "cache_frame_pause_mesh",
                "cache_frame_pause_particles", "cache_frame_pause_guide", "cache_resumable",
                "cache_data_format", "has_cache_baked_data", "has_cache_baked_any",
                "is_cache_baking_data", "is_cache_baking_any", "has_cache_baked_noise",
                "has_cache_baked_mesh", "has_cache_baked_particles", "has_cache_baked_guide",
                "cache_mesh_format", "resolution_max", "domain_type", "use_noise", "use_mesh",
                "export_manta_script")


def values(owner, fields):
    return {name: getattr(owner, name) for name in fields if hasattr(owner, name)}


def rna(owner, fields):
    properties = owner.bl_rna.properties
    result = {"type": owner.bl_rna.identifier, "property_names": sorted(properties.keys()),
              "reviewed_properties": {}}
    for name in fields:
        prop = properties.get(name)
        if prop is None:
            continue
        entry = {"type": prop.type, "readonly": prop.is_readonly}
        if prop.type == "ENUM":
            entry["choices"] = [item.identifier for item in prop.enum_items]
        if prop.type in {"INT", "FLOAT"}:
            entry.update(hard_min=prop.hard_min, hard_max=prop.hard_max)
        result["reviewed_properties"][name] = entry
    return result


def operators():
    result = {}
    for group, names in (("ptcache", ("bake", "free_bake", "bake_all", "free_bake_all")),
                         ("rigidbody", ("world_add", "object_add", "world_remove")),
                         ("fluid", ("bake_data", "free_data", "bake_all", "free_all", "pause_bake"))):
        for name in names:
            operator = getattr(getattr(bpy.ops, group), name)
            result[group + "." + name] = {
                "parameters": [prop.identifier for prop in operator.get_rna_type().properties
                               if prop.identifier != "rna_type"],
                "poll_in_startup_context": operator.poll(),
            }
    jobs = {}
    for kind in ("OBJECT_SIM_FLUID", "POINTCACHE", "OBJECT_BAKE", "RENDER"):
        try:
            jobs[kind] = {"accepted": True, "running": bpy.app.is_job_running(kind)}
        except (TypeError, ValueError) as error:
            jobs[kind] = {"accepted": False, "error": str(error)[:1024]}
    return {"operators": result, "job_type_queries": jobs,
            "interface_lock_readable": hasattr(bpy.context.window_manager, "is_interface_locked")}


def cube(scene, name, *, size=1., location=(0., 0., 0.)):
    extent = size / 2
    mesh = bpy.data.meshes.new(name + " Mesh")
    mesh.from_pydata([(x * extent, y * extent, z * extent)
                      for x, y, z in ((-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
                                      (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1))], [],
                     [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
                      (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.location = location
    return obj


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def scene(name):
    result = bpy.data.scenes.new(name)
    bpy.context.window.scene = result
    result.frame_start, result.frame_end = 1, 3
    result.gravity = (0., 0., -9.81)
    return result


def positions(objects, frames):
    result = []
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        result.append({obj.name: list(obj.evaluated_get(depsgraph).matrix_world.translation)
                       for obj in objects})
    return result


def measured_call(operator, **kwargs):
    active_scene = bpy.context.scene
    assert not bpy.context.window_manager.is_interface_locked
    before = {"frame": active_scene.frame_current, "subframe": active_scene.frame_subframe,
              "interface_locked": bpy.context.window_manager.is_interface_locked}
    started = time.monotonic()
    result = operator("EXEC_DEFAULT", **kwargs)
    locked = bpy.context.window_manager.is_interface_locked
    after = {"interface_locked": locked}
    if not locked:
        after.update(frame=active_scene.frame_current, subframe=active_scene.frame_subframe)
    assert result == {"FINISHED"}, result
    return {"result": sorted(result), "blocking_ms": round((time.monotonic() - started) * 1000, 3),
            "context_before": before, "context_at_return": after}


def point_cache_call(obj, cache, operation):
    with bpy.context.temp_override(scene=bpy.context.scene, object=obj, active_object=obj,
                                    point_cache=cache):
        operator = bpy.ops.ptcache.bake if operation == "BAKE" else bpy.ops.ptcache.free_bake
        assert operator.poll()
        return measured_call(operator, **({"bake": True} if operation == "BAKE" else {}))


def rigid_probe(owned):
    active_scene = scene("Owned Rigid Cache Probe")
    bodies = [cube(active_scene, "Owned Rigid A", location=(0., 0., 3.)),
              cube(active_scene, "Owned Rigid B", location=(4., 0., 5.))]
    for obj in bodies:
        activate(obj)
        assert bpy.ops.rigidbody.object_add(type="ACTIVE") == {"FINISHED"}
        obj.rigid_body.collision_shape = "BOX"
    world = active_scene.rigidbody_world
    world.substeps_per_frame, world.solver_iterations = 1, 4
    cache = world.point_cache
    cache.frame_start, cache.frame_end, cache.frame_step = 1, 3, 1
    assert not cache.use_disk_cache and not cache.use_external
    active_scene.frame_set(1, subframe=.25)
    before_files = snapshot_files(owned)
    fractional_bake = point_cache_call(bodies[0], cache, "BAKE")
    fractional_state = values(cache, POINT_CACHE_FIELDS)
    fractional_samples = positions(bodies, [3, 1, 2])
    fractional_complete = all(fractional_samples[0][obj.name][2] < fractional_samples[1][obj.name][2]
                              for obj in bodies)
    fractional_free = point_cache_call(bodies[0], cache, "FREE")
    # Native point-cache bake changes integer cfra but preserves fractional time.
    # This explicit fixture reset/normalization is distinct from claiming FREE
    # deletes a cache or that FINISHED proves a complete bake.
    world.time_scale = 1.
    active_scene.frame_set(1, subframe=0.)
    first = point_cache_call(bodies[0], cache, "BAKE")
    assert cache.is_baked
    first_state = values(cache, POINT_CACHE_FIELDS)
    # Visit the last frame first: forward evaluation after an empty bake could
    # otherwise populate a cache and conceal incomplete native bake coverage.
    shuffled = positions(bodies, [3, 1, 2])
    baked = [shuffled[index] for index in (1, 2, 0)]
    assert all(baked[-1][obj.name][2] < baked[0][obj.name][2] for obj in bodies), baked
    active_scene.gravity = (0., 0., 0.)
    bpy.context.view_layer.update()
    invalidated_state = values(cache, POINT_CACHE_FIELDS)
    after_change = positions(bodies, [3, 1, 2])
    first_free = point_cache_call(bodies[0], cache, "FREE")
    assert not cache.is_baked
    second = point_cache_call(bodies[0], cache, "BAKE")
    assert cache.is_baked
    shuffled = positions(bodies, [3, 1, 2])
    rebaked_without_reset = [shuffled[index] for index in (1, 2, 0)]
    second_free = point_cache_call(bodies[0], cache, "FREE")
    # FREE only clears the baked bit. A world RNA setting with the native reset
    # callback is a distinct invalidation action, not an implicit part of FREE.
    world.time_scale = .5
    bpy.context.view_layer.update()
    explicit_invalidation = values(cache, POINT_CACHE_FIELDS)
    active_scene.frame_set(1)
    reset_bake = point_cache_call(bodies[0], cache, "BAKE")
    shuffled = positions(bodies, [3, 1, 2])
    rebaked = [shuffled[index] for index in (1, 2, 0)]
    assert rebaked != baked, (baked, rebaked)
    reset_free = point_cache_call(bodies[0], cache, "FREE")
    after_memory_files = snapshot_files(owned)
    assert after_memory_files == before_files, compare_files(before_files, after_memory_files)
    return {
        "rna": {"cache": rna(cache, POINT_CACHE_FIELDS),
                "world": rna(world, ("collection", "constraints", "enabled", "time_scale",
                                     "substeps_per_frame", "solver_iterations"))},
        "cache_owner": "SCENE_RIGID_BODY_WORLD", "world_objects": [obj.name for obj in bodies],
        "fractional_bake": fractional_bake, "fractional_state": fractional_state,
        "fractional_last_frame_first_positions": fractional_samples,
        "fractional_bake_last_frame_motion_verified": fractional_complete,
        "fractional_free": fractional_free,
        "one_cache_bake_affects_both_bodies": True, "first_bake": first, "first_state": first_state,
        "baked_positions": baked, "state_after_gravity_change": invalidated_state,
        "positions_after_gravity_change": after_change,
        "first_free": first_free, "rebake_without_explicit_reset": second,
        "rebake_without_reset_positions": rebaked_without_reset,
        "free_then_bake_recomputed_changed_gravity": rebaked_without_reset != baked,
        "second_free": second_free, "after_world_setting_invalidation": explicit_invalidation,
        "reset_bake": reset_bake, "rebaked_positions": rebaked, "reset_free": reset_free,
        "memory_cache_created_no_files": True,
        "disk_cache_lifecycle": "NOT_PROVEN; an earlier isolated disk-toggle attempt crashed natively",
    }


def fluid_state(settings):
    result = values(settings, FLUID_FIELDS)
    result["interface_locked"] = bpy.context.window_manager.is_interface_locked
    return result


def densities(obj, frames):
    result = []
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        settings = obj.evaluated_get(depsgraph).modifiers[0].domain_settings
        samples = array("f", settings.density_grid)
        assert 0 < len(samples) <= 32768, len(samples)
        result.append({"frame": frame, "samples": len(samples), "sum": sum(samples),
                       "nonzero": sum(value != 0 for value in samples),
                       "sha256_float32_native": hashlib.sha256(samples.tobytes()).hexdigest()})
    return result


def fluid_free(obj, settings, evidence):
    activate(obj)
    started = time.monotonic()
    evidence["operator"] = measured_call(bpy.ops.fluid.free_data)
    locked = bpy.context.window_manager.is_interface_locked
    evidence["at_return"] = {"interface_locked": locked, "cache_flags_observed": not locked}
    if not locked:
        evidence["at_return"]["cache"] = fluid_state(settings)
    evidence["returned_while_interface_locked"] = locked
    # Never inspect/mutate a graph while an owned native free job holds the interface.
    while bpy.context.window_manager.is_interface_locked:
        assert time.monotonic() - started < 60, "Owned fluid FREE did not unlock in 60 seconds"
        yield .05
    evidence["completion_elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    evidence["after_unlock"] = fluid_state(settings)
    assert not settings.has_cache_baked_data and not settings.is_cache_baking_any


def fluid_probe(owned, evidence):
    active_scene = scene("Owned Fluid Cache Probe")
    target = cube(active_scene, "Owned Gas Domain", size=4.)
    activate(target)
    modifier = target.modifiers.new("Owned Fluid Domain", "FLUID")
    modifier.fluid_type = "DOMAIN"
    settings = modifier.domain_settings
    cache_directory = owned / "owned-fluid-cache"
    cache_directory.mkdir()
    settings.cache_directory = str(cache_directory)
    settings.cache_type, settings.domain_type = "MODULAR", "GAS"
    settings.cache_frame_start, settings.cache_frame_end = 1, 3
    settings.resolution_max = 16
    settings.use_adaptive_domain, settings.use_noise = False, False
    choices = {item.identifier for item in settings.bl_rna.properties["cache_data_format"].enum_items}
    settings.cache_data_format = "UNI" if "UNI" in choices else "OPENVDB"
    if hasattr(settings, "cache_resumable"):
        settings.cache_resumable = True
    flows = bpy.data.collections.new("Owned Fluid Flows")
    effectors = bpy.data.collections.new("Owned Empty Fluid Effectors")
    active_scene.collection.children.link(flows)
    active_scene.collection.children.link(effectors)
    settings.fluid_group, settings.effector_group = flows, effectors
    source = cube(active_scene, "Owned Smoke Source", size=1.)
    flows.objects.link(source)
    active_scene.collection.objects.unlink(source)
    flow_modifier = source.modifiers.new("Owned Fluid Flow", "FLUID")
    flow_modifier.fluid_type = "FLOW"
    flow = flow_modifier.flow_settings
    flow.flow_type, flow.flow_behavior, flow.density = "SMOKE", "GEOMETRY", 1.
    bpy.context.view_layer.update()
    activate(target)
    active_scene.frame_set(5, subframe=.25)
    evidence["rna"] = rna(settings, FLUID_FIELDS)
    evidence["before"] = fluid_state(settings)
    evidence["before_files"] = snapshot_files(cache_directory)
    evidence["bake"] = measured_call(bpy.ops.fluid.bake_data)
    evidence["after_bake"] = fluid_state(settings)
    assert settings.has_cache_baked_data and not settings.is_cache_baking_any
    evidence["baked_density"] = densities(target, [1, 2, 3])
    assert all(item["nonzero"] for item in evidence["baked_density"])
    evidence["bake_files"] = snapshot_files(cache_directory)
    assert evidence["bake_files"]
    flow.density = 2.
    bpy.context.view_layer.update()
    evidence["after_flow_density_change"] = fluid_state(settings)
    evidence["density_after_change"] = densities(target, [3, 1, 2])
    # Prove native deletion scope only with disposable files owned by this fixture.
    for folder in ("config", "data", "script", "noise", "mesh", "particles", "guiding"):
        path = cache_directory / folder
        path.mkdir(exist_ok=True)
        (path / "owned-deletion-sentinel.txt").write_text("fixture owns this sentinel", encoding="utf-8")
    keep = cache_directory / "keep-owned-root-sentinel.txt"
    keep.write_text("retain outside native deleted children", encoding="utf-8")
    other = owned / "other-cache"
    other.mkdir()
    (other / "keep.txt").write_text("another owned cache directory", encoding="utf-8")
    other_before = snapshot_files(other)
    evidence["before_free_files"] = snapshot_files(cache_directory)
    evidence["free"] = {}
    yield from fluid_free(target, settings, evidence["free"])
    evidence["after_free_files"] = snapshot_files(cache_directory)
    evidence["free_file_effects"] = compare_files(evidence["before_free_files"], evidence["after_free_files"])
    assert all(not (cache_directory / folder).exists()
               for folder in ("config", "data", "script", "noise", "mesh", "particles"))
    assert (cache_directory / "guiding/owned-deletion-sentinel.txt").is_file()
    assert keep.is_file() and snapshot_files(other) == other_before
    evidence["free_data_recursively_deleted_dependent_cache_children"] = True
    evidence["guiding_root_and_other_directory_retained"] = True
    activate(target)
    evidence["rebake"] = measured_call(bpy.ops.fluid.bake_data)
    assert settings.has_cache_baked_data
    evidence["rebaked_density"] = densities(target, [1, 2, 3])
    assert evidence["rebaked_density"] != evidence["baked_density"]
    evidence["rebaked_files"] = snapshot_files(cache_directory)
    evidence["final_free"] = {}
    yield from fluid_free(target, settings, evidence["final_free"])
    evidence["final_files"] = snapshot_files(cache_directory)


def protected_scene_state(scene_value):
    return {obj.name: {"type": obj.type, "matrix": [list(row) for row in obj.matrix_world],
                       "vertices": [list(vertex.co) for vertex in obj.data.vertices]
                       if obj.type == "MESH" else None}
            for obj in scene_value.objects}


def run(owned):
    original_scene = bpy.context.scene
    protected = protected_scene_state(original_scene)
    evidence = {
        "blender_version": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode(), "platform": sys.platform,
        "native_api_research_only": True, "release_readiness": "NOT_ASSESSED",
        "explicit_fixture_consent": {"EDIT_SCENE": True, "EDIT_MESH": True, "EDIT_ANIMATION": True,
                                     "ACCESS_EXTERNAL_FILES": True, "DELETE_OBJECTS": True,
                                     "SAVE_PROJECT": True},
        "owned_root": str(owned), "api": operators(),
        "native_calls_interruptible": False, "global_pause_operator_invoked": False,
        "ownership_specific_native_cancel_proven": False,
    }
    evidence["rigid_body"] = rigid_probe(owned)
    yield .01
    evidence["fluid"] = {}
    yield from fluid_probe(owned, evidence["fluid"])
    assert protected_scene_state(original_scene) == protected
    evidence["original_factory_scene_preserved"] = True
    evidence["project_saved"] = False
    manifest = owned / "simulation-cache-probe.json"
    manifest.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(MARKER + json.dumps({
        "blender_version": bpy.app.version_string,
        "native_api_research_only": True, "release_readiness": "NOT_ASSESSED",
        "manifest": str(manifest), "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "rigid_world_scope_verified": True, "rigid_memory_free_rebake_verified": True,
        "rigid_disk_cache_lifecycle_proven": False, "fluid_free_rebake_verified": True,
        "fluid_free_returned_before_unlock": evidence["fluid"]["free"]["returned_while_interface_locked"],
        "fluid_recursive_deletion_verified_on_owned_sentinels": True,
        "ownership_specific_native_cancel_proven": False,
        "original_factory_scene_preserved": True,
    }), flush=True)


if __name__ == "__main__":
    assert bpy.app.factory_startup and not bpy.app.background, "Use the isolated INTERACTIVE runner case"
    token = os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    assert len(token) == 32 and all(char in "0123456789abcdef" for char in token)
    temporary = Path(os.environ["TMPDIR"]).resolve(strict=True)
    assert Path(os.environ["BLENDER_USER_CONFIG"]).resolve(strict=True).parent == temporary
    assert Path(os.environ["BLENDER_USER_SCRIPTS"]).resolve(strict=True).parent == temporary
    owned = temporary / "simulation-cache-probe"
    owned.mkdir()
    work = run(owned)
    started = time.monotonic()

    def tick():
        try:
            assert time.monotonic() - started < 180, "Fixture lifecycle exceeded its owned budget"
            return next(work)
        except StopIteration:
            bpy.ops.wm.quit_blender()
            return None
        except BaseException:
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)

    bpy.app.timers.register(tick, first_interval=.1)
