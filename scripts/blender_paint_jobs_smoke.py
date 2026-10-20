"""Real socket/timer cooperative painting and recovery on a private test desktop.

The worker owns JSON/socket I/O only; bpy and fixture controls stay on the main thread.
"""
from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
CONTROLS = queue.Queue()
DONE = threading.Event()
RESULT = {}


class Client:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=15)
        self.stream = self.socket.makefile("rb")
        self.sequence = 0

    def call(self, method, **params):
        self.sequence += 1
        identifier = f"native_job_{self.sequence}"
        self.socket.sendall((json.dumps({"id": identifier, "method": method, "params": params,
            "protocol_version": "1.0", "timeout_ms": 10000}) + "\n").encode())
        result = json.loads(self.stream.readline())
        assert result["id"] == identifier and result["ok"], result
        return result["result"]

    def close(self):
        self.stream.close()
        self.socket.close()


def control(action):
    event, result = threading.Event(), []
    CONTROLS.put((action, event, result))
    assert event.wait(10), f"Main-thread fixture control timed out: {action}"
    assert result == [True], result


def scenario(port, source_digest, captures):
    """No bpy or runtime calls in this network thread."""
    client, samples = Client(port), []
    brush = {"points": [[.15, .15], [.85, .85]], "radius_pixels": 64.,
             "color": [.8, .2, .05, 1.], "opacity": .75, "hardness": 1.}
    try:
        def start(name, limit=60.):
            value = client.call("image.paint_job_start", image_name="Job Canvas", new_name=name,
                                strokes=[brush], time_limit_seconds=limit)
            assert value["accepted"] and not value["painting_completed"]
            assert not value["undo_boundary_created"] and value["state"] == "QUEUED"
            return value["job_id"]

        def wait(job_id):
            revisions, phases = [], set()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                stamp = time.perf_counter()
                value = client.call("jobs.inspect", job_id=job_id)
                samples.append(time.perf_counter() - stamp)
                phases.add(value["progress"]["phase"])
                revisions.append(value["revision"])
                assert revisions == sorted(revisions), revisions
                if value["terminal"]:
                    return value, {"polls": len(revisions), "phases": sorted(phases)}
                time.sleep(.015)
            raise AssertionError("Native job never terminated")

        def capture(name="Paint Panel"):
            return client.call("viewport.capture", object_name=name, shading="material", view="current",
                               include_overlays=False, resolution=[768, 512])["path"]

        def unchanged():
            assert client.call("image.inspect_pixels", image_name="Job Canvas")["pixels_sha256_float32_le"] == source_digest

        def undo():
            value = client.call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert value["snapshot_marker_verified"], value

        job_id = start("Completed Paint")
        interleaved = client.call("transform.set", object_name="Paint Panel", location=[0., 0., .25])
        assert abs(interleaved["location"][2] - .25) < 1e-6
        captures["interleaved_before"] = capture()
        outcome, progress = wait(job_id)
        assert outcome["state"] == "SUCCEEDED" and outcome["undo_boundary_finalized"], outcome
        assert progress["polls"] > 2 and "normalizing" in progress["phases"], progress
        painted = client.call("image.inspect_pixels", image_name="Completed Paint", samples=[[256, 256], [0, 511]])
        assert painted["pixels_sha256_float32_le"] == outcome["result"]["pixels_sha256_float32_le"]
        assert all(abs(a-b) < 1e-6 for a, b in zip(painted["samples"][0]["rgba"], [.6125, .175, .1125, 1.], strict=True)), painted
        unchanged()
        client.call("nodes.set_image", material_name="Working Canvas", node_name="Albedo", image_name="Completed Paint")
        captures["painted"], captures["protected_after"] = capture(), capture("Protected Panel")
        undo()
        undo()
        control("verify_interleaved_recovery")
        unchanged()
        captures["recovered"], captures["protected_recovered"] = capture(), capture("Protected Panel")

        cancelled = start("Cancelled Paint")
        client.call("jobs.cancel", job_id=cancelled)
        value, _ = wait(cancelled)
        assert value["state"] == "CANCELLED" and not value["execution_started"], value

        disconnected = start("Disconnected Paint")
        client.close()
        client = Client(port)
        value, _ = wait(disconnected)
        assert value["state"] == "CANCELLED" and not value["execution_started"], value
        assert value["error"]["context"]["connection_disconnected"], value

        expired = start("Paused Expiry", 1.)
        control("pause")
        for _ in range(10):
            value = client.call("jobs.inspect", job_id=expired)
            if value["state"] == "PAUSED":
                break
            time.sleep(.01)
        assert value["state"] == "PAUSED", value
        value, _ = wait(expired)
        assert value["state"] == "CANCELLED" and value["error"]["context"]["job_deadline_expired"], value
        control("resume")

        denied = start("Permission Denied")
        control("deny_materials")
        value, _ = wait(denied)
        assert value["state"] == "FAILED" and value["error"]["code"] == "PERMISSION_DENIED", value
        control("allow_materials")

        stale = start("Stale Source")
        control("change_source")
        value, _ = wait(stale)
        assert value["state"] == "FAILED" and value["error"]["context"]["stale_source"], value
        control("restore_source")
        unchanged()

        control("arm_post_write_cancel")
        retained = start("Retained Paint")
        value, _ = wait(retained)
        control("disarm_post_write_cancel")
        error = value["error"]["context"]
        assert value["state"] == "CANCELLED" and error["possible_mutation"], value
        assert error["cleanup_permission_denied"] and not error["rollback_verified"], value
        assert value["undo_boundary_finalized"], value
        client.call("image.inspect_pixels", image_name="Retained Paint")
        undo()

        control("arm_post_write_cancel")
        paused_publication = start("Paused Publication")
        value, _ = wait(paused_publication)
        control("disarm_post_write_cancel")
        assert value["state"] == "FAILED" and value["error"]["code"] == "AGENT_PAUSED", value
        assert value["error"]["context"]["possible_mutation"] and value["undo_boundary_finalized"], value
        client.call("image.inspect_pixels", image_name="Paused Publication")
        control("resume")
        undo()
        control("verify_final")
        unchanged()
        RESULT.update(progress=progress, inspect_poll_count=len(samples), inspect_poll_max_seconds=max(samples),
                      inspect_poll_median_seconds=sorted(samples)[len(samples)//2])
    except Exception:
        RESULT["failure"] = traceback.format_exc()
    finally:
        client.close()
        DONE.set()


def setup():
    try:
        assert not bpy.app.background
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        from blender_codex_bridge.tools import image_paint

        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = prefs.allow_external_files = False
        prefs.paint_job_budget_ms = 1
        for toolset in ("materials", "nodes", "objects", "interaction"):
            runtime.registry.enable_toolset(toolset)
        def call(method, **params):
            return runtime.dispatch(method, params)
        original = call("image.create", new_name="Job Canvas", width=512, height=512, color=[.05, .1, .3, 1.])
        panel = bpy.data.objects["Cube"]
        panel.name = "Paint Panel"
        panel.data.clear_geometry()
        panel.data.from_pydata([(-1, -.5, 0), (1, -.5, 0), (1, .5, 0), (-1, .5, 0)], [], [(0, 1, 2, 3)])
        uv = panel.data.uv_layers.new(name="Canvas UV")
        for loop, coordinate in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
            loop.uv = coordinate
        material = panel.active_material
        material.name = "Protected Canvas"
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name, node.image = "Albedo", bpy.data.images["Job Canvas"]
        material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
        uv_node = material.node_tree.nodes.new("ShaderNodeUVMap")
        uv_node.uv_map = "Canvas UV"
        material.node_tree.links.new(uv_node.outputs["UV"], node.inputs["Vector"])
        protected = panel.copy()
        protected.name, protected.location.x = "Protected Panel", 3.5
        bpy.context.scene.collection.objects.link(protected)
        call("material.copy_for_object", object_name="Paint Panel", slot_index=0, new_name="Working Canvas")
        baseline = call("scene.snapshot", object_names=["Protected Panel", "Camera", "Light"])
        selection = sorted(obj.name for obj in bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active.name
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((0, 0, 1)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 2.5
        def capture(name):
            return call("viewport.capture", object_name=name, shading="material", view="current",
                        include_overlays=False, resolution=[768, 512])["path"]
        captures = {"before": capture("Paint Panel"), "protected_before": capture("Protected Panel")}
        pixels = list(bpy.data.images["Job Canvas"].pixels[:])
        original_read = image_paint._read
        def fault(context, image, *, modifying=False):
            value = original_read(context, image, modifying=modifying)
            if image.name in {"Retained Paint", "Paused Publication"}:
                if image.name == "Retained Paint":
                    runtime.jobs.cancel_all("fixture stop after native write, deletion not consented")
                else:
                    runtime.state.set_paused(True)
                context.check_cancelled()
            return value
        def apply(action):
            if action in {"pause", "resume"}:
                runtime.state.set_paused(action == "pause")
            elif action in {"deny_materials", "allow_materials"}:
                prefs.allow_edit_materials = action == "allow_materials"
            elif action in {"change_source", "restore_source"}:
                image = bpy.data.images["Job Canvas"]
                values = list(pixels)
                if action == "change_source":
                    values[0] = .9
                image.pixels.foreach_set(values)
                image.update()
            elif action == "arm_post_write_cancel":
                image_paint._read = fault
            elif action == "disarm_post_write_cancel":
                image_paint._read = original_read
            elif action in {"verify_interleaved_recovery", "verify_final"}:
                assert bpy.data.images.get("Completed Paint") is None
                assert abs(bpy.data.objects["Paint Panel"].location.z - .25) < 1e-6
                assert bpy.data.materials["Working Canvas"].node_tree.nodes["Albedo"].image.name == "Job Canvas"
                if action == "verify_final":
                    assert runtime.jobs.active is None
                    assert all(bpy.data.images.get(name) is None for name in (
                        "Cancelled Paint", "Disconnected Paint", "Paused Expiry", "Permission Denied", "Stale Source", "Retained Paint", "Paused Publication"))
                    assert all(not job.prepared and job.work is None for job in runtime.jobs.history)
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
            if not DONE.is_set() and time.monotonic() - started < 150:
                return .005
            try:
                assert DONE.is_set(), "Fixture timer deadline expired"
                assert "failure" not in RESULT, RESULT.get("failure")
                comparison = call("scene.compare", snapshot_id=baseline["snapshot_id"])
                assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope", comparison
                assert not any((prefs.allow_execute_python, prefs.allow_save_project, prefs.allow_delete_objects, prefs.allow_external_files))
                runtime.stop_server()
                print("BLENDER_PAINT_JOBS_OK " + json.dumps({"blender": bpy.app.version_string,
                    "real_network_and_timer": True, "source_digest": original["pixels_sha256_float32_le"],
                    "captures": captures, **RESULT, "interleaved_edit_preserved_by_job_undo": True,
                    "post_write_denial_recovered": True, "project_saved": False, "user_preferences_saved": False,
                    "general_long_operation_lifecycle_verified": False}), flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                image_paint._read = original_read
                runtime.emergency_stop()
                bpy.ops.wm.quit_blender()
            return None
        bpy.app.timers.register(supervise, first_interval=.005)
        threading.Thread(target=scenario, args=(port, original["pixels_sha256_float32_le"], captures),
                         name="BridgePaintJobNetworkFixture", daemon=True).start()
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(setup, first_interval=1.)
