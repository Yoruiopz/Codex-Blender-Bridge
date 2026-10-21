"""Typed projected paint: socket/timer work, measured COW consumers and UI evidence.

Run through run_blender_checks.py only; isolated factory fixture, no user project.
"""
from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
import traceback
from array import array
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from blender_paint_jobs_smoke import Client  # noqa: E402
from blender_surface_projection_probe_smoke import PROJECTOR, mesh  # noqa: E402

CONTROLS, DONE, RESULT = queue.Queue(), threading.Event(), {}
PARAMS = {"image_name": "Surface Source", "object_name": "Surface Panel", "uv_layer": "UV", "face_indices": [0],
          "projector": PROJECTOR, "strokes": [{"points": [[.25, .5], [.75, .5]], "radius_world": .3,
              "hardness": 1., "color": [.8, .2, .05, 1.], "opacity": .75}],
          "stencil": {"image_name": "Surface Stencil", "channel": "R"}}


def control(action):
    event, result = threading.Event(), []
    CONTROLS.put((action, event, result))
    assert event.wait(15), action
    assert result == [True], result


def scenario(port, captures, source_digest, stencil_digest, reference_digest):
    client = None
    try:
        client = Client(port)
        def start(name):
            value = client.call("image.paint_surface_job_start", **PARAMS, new_name=name, time_limit_seconds=60.)
            assert value["accepted"] and not value["painting_completed"] and not value["projection_work_started"]
            assert not value["undo_boundary_created"] and value["state"] == "QUEUED", value
            return value["job_id"]
        def wait(job):
            phases, revisions, deadline = set(), [], time.monotonic()+75
            while time.monotonic() < deadline:
                value = client.call("jobs.inspect", job_id=job)
                phases.add(value["progress"]["phase"])
                revisions.append(value["revision"])
                assert revisions == sorted(revisions)
                if value["terminal"]:
                    return value, sorted(phases)
                time.sleep(.01)
            raise AssertionError("Projected job did not terminate")
        def pixels(name):
            return client.call("image.inspect_pixels", image_name=name)
        def capture(name):
            return client.call("viewport.capture", object_name=name, shading="material", view="current",
                               include_overlays=False, resolution=[768, 512])["path"]
        def undo():
            value = client.call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert value["snapshot_marker_verified"], value

        completed = start("Surface Job")
        value, phases = wait(completed)
        assert value["state"] == "SUCCEEDED" and value["undo_boundary_finalized"], value
        assert value["result"]["pixels_sha256_float32_le"] == reference_digest
        assert pixels("Surface Job")["pixels_sha256_float32_le"] == reference_digest
        assert pixels("Surface Source")["pixels_sha256_float32_le"] == source_digest
        assert pixels("Surface Stencil")["pixels_sha256_float32_le"] == stencil_digest
        client.call("nodes.set_image", material_name="Surface Working", node_name="Albedo", image_name="Surface Job")
        captures["projected"], captures["protected_after"] = capture("Surface Panel"), capture("Surface Protected")
        undo()  # Explicit binding recovery precedes creation recovery.
        undo()
        control("verify_recovery")
        assert pixels("Surface Source")["pixels_sha256_float32_le"] == source_digest
        captures["recovered"] = capture("Surface Panel")

        stale = start("Stale Surface Job")
        control("change_uv")
        value, _ = wait(stale)
        assert value["state"] == "FAILED" and value["error"]["context"]["stale_geometry"], value
        assert not value["execution_started"] and not value["undo_boundary_created"]
        control("restore_uv")

        cancelled = start("Cancelled Surface Job")
        client.call("jobs.cancel", job_id=cancelled)
        value, _ = wait(cancelled)
        assert value["state"] == "CANCELLED" and not value["execution_started"], value

        disconnected = start("Disconnected Surface Job")
        client.close()
        client = Client(port)
        value, _ = wait(disconnected)
        assert value["state"] == "CANCELLED" and not value["execution_started"], value

        assert pixels("Surface Source")["pixels_sha256_float32_le"] == source_digest
        assert pixels("Surface Stencil")["pixels_sha256_float32_le"] == stencil_digest
        control("verify_final")
        RESULT.update(projected_job_phases=phases, synchronous_job_complete_pixels_equal=True,
                      stale_uv_refused_before_publication=True, precommit_cancel_verified=True,
                      owner_disconnect_verified=True, measured_output_creation_recovery_verified=True)
    except Exception:
        RESULT["failure"] = traceback.format_exc()
    finally:
        if client is not None:
            client.close()
        DONE.set()


def setup():
    try:
        assert not bpy.app.background
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = prefs.allow_external_files = False
        prefs.paint_job_budget_ms = 1
        for toolset in ("materials", "nodes", "objects"):
            runtime.registry.enable_toolset(toolset)
        # Keep the factory cube out of the view of the disposable paint panel.
        bpy.data.objects["Cube"].location.x = -4.
        def call(method, **params):
            return runtime.dispatch(method, params)
        source = call("image.create", new_name="Surface Source", width=256, height=256, color=[.05, .1, .3, 1.])
        stencil = call("image.create", new_name="Surface Stencil", width=2, height=2, role="DATA", color=[.5, 0., 0., 1.])
        target = mesh("Surface Panel", [(-1., -1., 0.), (1., -1., 0.), (1., 1., 0.), (-1., 1., 0.)],
                      [(0, 1, 2, 3)], [(0., 0.), (1., 0.), (1., 1.), (0., 1.)])
        material = bpy.data.materials.new("Surface Original")
        material.use_nodes = True
        albedo = material.node_tree.nodes.new("ShaderNodeTexImage")
        albedo.name, albedo.image = "Albedo", bpy.data.images["Surface Source"]
        material.node_tree.links.new(albedo.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
        uv = material.node_tree.nodes.new("ShaderNodeUVMap")
        uv.uv_map = "UV"
        material.node_tree.links.new(uv.outputs["UV"], albedo.inputs["Vector"])
        target.data.materials.append(material)
        protected = target.copy()
        protected.data = target.data.copy()
        protected.name, protected.location.x = "Surface Protected", 3.5
        bpy.context.scene.collection.objects.link(protected)
        call("material.copy_for_object", object_name=target.name, slot_index=0, new_name="Surface Working")
        bpy.context.view_layer.update()
        baseline = call("scene.snapshot", object_names=["Surface Protected", "Cube", "Camera", "Light"])
        selection = sorted(obj.name for obj in bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active.name
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((0, 0, 1)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 2.5
        def capture(name):
            return call("viewport.capture", object_name=name, shading="material", view="current", include_overlays=False, resolution=[768, 512])["path"]
        captures = {"before": capture(target.name), "protected_before": capture(protected.name)}
        from blender_codex_bridge.tools import image_paint
        original_new, acquired = image_paint._new, {}
        def new_with_acquired_consumer(context, bpy_module, name, *args, **kwargs):
            original_check = context.check_cancelled
            def acquire():
                original_check()
                output = bpy.data.images.get(name)
                if output is not None and not acquired:
                    values = array("f", [0.])*len(output.pixels)
                    output.pixels.foreach_get(values)
                    acquired.update(name=output.name, pixels=image_paint.brush.digest(values),
                                    alpha_mode=output.alpha_mode, colorspace=output.colorspace_settings.name)
                    # An injected interleaving fixture edit, not a product step.
                    bpy.data.materials["Surface Working"].node_tree.nodes["Albedo"].image = output
            context.check_cancelled = acquire
            try:
                return original_new(context, bpy_module, name, *args, **kwargs)
            finally:
                context.check_cancelled = original_check
        image_paint._new = new_with_acquired_consumer
        try:
            try:
                call("image.paint_surface_version", **PARAMS, new_name="Acquired Surface Output")
            except image_paint.BridgeError as error:
                assert error.context["stale_output"] and error.context["possible_mutation"], error.to_dict()
                assert error.context["retained_image_name"] == "Acquired Surface Output"
            else:
                raise AssertionError("An output acquired by another consumer must not be painted")
        finally:
            image_paint._new = original_new
        output = bpy.data.images["Acquired Surface Output"]
        values = array("f", [0.])*len(output.pixels)
        output.pixels.foreach_get(values)
        assert image_paint.brush.digest(values) == acquired["pixels"]
        assert output.alpha_mode == acquired["alpha_mode"] and output.colorspace_settings.name == acquired["colorspace"]
        assert bpy.data.materials["Surface Working"].node_tree.nodes["Albedo"].image == output
        # Explicit typed correction of the fixture's injected binding. The
        # product retained the consumer edit and untouched allocated image.
        call("nodes.set_image", material_name="Surface Working", node_name="Albedo", image_name="Surface Source")
        RESULT["acquired_output_consumer_blocks_all_metadata_and_pixel_writes"] = True
        RESULT["fixture_restored_own_injected_binding_explicitly"] = True
        sync = call("image.paint_surface_version", **PARAMS, new_name="Surface Sync")
        assert sync["source_pixels_unchanged"] and sync["geometry_and_uv_inputs_unchanged"]
        assert sync["painted_pixels"] > 0 and not sync["bound_to_nodes"]
        def apply(action):
            if action == "change_uv":
                bpy.data.objects["Surface Panel"].data.uv_layers["UV"].data[0].uv.x = .02
            elif action == "restore_uv":
                bpy.data.objects["Surface Panel"].data.uv_layers["UV"].data[0].uv.x = 0.
            elif action in {"verify_recovery", "verify_final"}:
                assert bpy.data.images.get("Surface Job") is None
                assert bpy.data.materials["Surface Working"].node_tree.nodes["Albedo"].image.name == "Surface Source"
                if action == "verify_final":
                    for name in ("Stale Surface Job", "Cancelled Surface Job", "Disconnected Surface Job"):
                        assert bpy.data.images.get(name) is None
                    assert runtime.jobs.active is None and all(not job.prepared and job.work is None for job in runtime.jobs.history)
                    assert sorted(obj.name for obj in bpy.context.selected_objects) == selection
                    assert bpy.context.view_layer.objects.active.name == active and bpy.context.mode == "OBJECT"
            else:
                raise AssertionError(action)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        runtime.start_server("127.0.0.1", port, request_timeout=15)
        started = time.monotonic()
        def supervise():
            while not CONTROLS.empty():
                action, event, result = CONTROLS.get_nowait()
                try:
                    apply(action)
                    result.append(True)
                except Exception:
                    result.append(traceback.format_exc())
                finally:
                    event.set()
            if not DONE.is_set() and time.monotonic()-started < 150:
                return .005
            try:
                assert DONE.is_set() and "failure" not in RESULT, RESULT.get("failure", "Projected fixture expired")
                comparison = call("scene.compare", snapshot_id=baseline["snapshot_id"])
                assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope", comparison
                assert not any((prefs.allow_execute_python, prefs.allow_save_project, prefs.allow_delete_objects, prefs.allow_external_files))
                print("BLENDER_SURFACE_PAINT_OK " + json.dumps({"blender": bpy.app.version_string, "captures": captures,
                    "protected_consumers_unchanged": True, "source_stencil_preserved": True,
                    "source_digest": source["pixels_sha256_float32_le"], "stencil_digest": stencil["pixels_sha256_float32_le"],
                    "full_paint_acceptance_verified": False, "project_saved": False, "user_preferences_saved": False, **RESULT}), flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                runtime.emergency_stop()
                bpy.ops.wm.quit_blender()
            return None
        bpy.app.timers.register(supervise, first_interval=.005)
        threading.Thread(target=scenario, args=(port,captures,source["pixels_sha256_float32_le"],stencil["pixels_sha256_float32_le"],sync["pixels_sha256_float32_le"]),
                         daemon=True, name="BridgeSurfacePaintNetworkFixture").start()
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(setup, first_interval=1.)
