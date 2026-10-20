"""4K tiled job, complete digest-only evidence, cancellation and native recovery.

Isolated UI fixture; use run_blender_checks.py, never a visible desktop fallback.
Requires 8 GiB available host RAM on Windows before starting the owned workload.
"""
from __future__ import annotations

import ctypes
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
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from blender_paint_jobs_smoke import Client  # noqa: E402

DONE = threading.Event()
CONTROLS = queue.Queue()
RESULT = {}


def process_memory():
    if sys.platform != "win32":
        return {"supported": False, "scope": "Windows process memory probe only; not zero memory"}
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("faults", w.DWORD), *[(key, ctypes.c_size_t) for key in (
            "peak", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]]
    kernel, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    assert psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return {"supported": True, "resident_bytes": counters.working, "peak_resident_bytes": counters.peak,
            "scope": "Whole isolated Blender process lifetime, including native/GPU staging/undo; not attributable private-array memory or a cap"}


def check_memory_headroom():
    if sys.platform == "win32":
        from ctypes import wintypes as w
        class Memory(ctypes.Structure):
            _fields_ = [("length", w.DWORD), ("load", w.DWORD), *[(key, ctypes.c_ulonglong) for key in (
                "total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]]
        status = Memory()
        status.length = ctypes.sizeof(status)
        assert ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx(ctypes.byref(status))
        assert status.available >= 8 * 1024**3, "4K fixture needs 8 GiB available RAM; no pressure/fallback test was run"
        return status.available
    return None


def control(action):
    event, result = threading.Event(), []
    CONTROLS.put((action, event, result))
    assert event.wait(15), f"4K fixture control timed out: {action}"
    assert result == [True], result


def scenario(port, source_digest, captures):
    """Socket-only worker; never touches bpy or the runtime."""
    client = None
    samples = []
    brush = {"points": [[.15, .15], [.85, .85]], "radius_pixels": 64., "hardness": 1.,
             "color": [.8, .2, .05, 1.], "opacity": .75}
    try:
        client = Client(port)
        def start(name):
            value = client.call("image.paint_job_start", image_name="4K Source", new_name=name,
                                strokes=[brush], time_limit_seconds=300.)
            assert value["accepted"] and not value["painting_completed"]
            assert value["workload"]["image_size"] == [4096, 4096]
            assert value["workload"]["large_image_requires_job"]
            return value["job_id"]
        def inspect(job_id):
            stamp = time.perf_counter()
            value = client.call("jobs.inspect", job_id=job_id)
            samples.append(time.perf_counter()-stamp)
            return value
        def wait(job_id):
            deadline = time.monotonic() + 320
            revision = 0
            phases = set()
            while time.monotonic() < deadline:
                value = inspect(job_id)
                assert value["revision"] >= revision
                revision = value["revision"]
                phases.add(value["progress"]["phase"])
                if value["terminal"]:
                    return value, sorted(phases)
                time.sleep(.05)
            raise AssertionError("4K job never became terminal")
        def pixels(name, points=None):
            value = client.call("image.inspect_pixels", image_name=name, samples=points or [], include_statistics=False)
            assert value["pixel_digest_complete"] and not value["statistics_included"] and not value["analysis_complete"]
            assert value["pixel_count"] == 4096**2 and value["channel_min"] is None
            return value
        def capture(name="4K Panel"):
            return client.call("viewport.capture", object_name=name, shading="material", view="current",
                               include_overlays=False, resolution=[768, 512])["path"]
        def undo():
            value = client.call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert value["snapshot_marker_verified"], value

        started = time.perf_counter()
        job = start("4K Painted")
        client.call("transform.set", object_name="4K Panel", location=[0., 0., .25])
        captures["interleaved_before"] = capture()
        finished, phases = wait(job)
        paint_seconds = time.perf_counter()-started
        assert finished["state"] == "SUCCEEDED" and finished["undo_boundary_finalized"], finished
        evidence = finished["result"]
        assert evidence["baseline_copy_bytes"] == 0 and evidence["coverage_scratch_max_bytes"] <= 32768
        assert evidence["candidate_pixel_tests"] < 2_000_000 and evidence["painted_pixels"] > 100_000
        measured = pixels("4K Painted", [[2048, 2048], [0, 4095]])
        assert measured["pixels_sha256_float32_le"] == evidence["pixels_sha256_float32_le"]
        assert all(abs(a-b) < 1e-6 for a,b in zip(measured["samples"][0]["rgba"], [.6125, .175, .1125, 1.], strict=True)), measured
        assert all(abs(a-b) < 1e-6 for a,b in zip(measured["samples"][1]["rgba"], [.05, .1, .3, 1.], strict=True)), measured
        assert pixels("4K Source")["pixels_sha256_float32_le"] == source_digest
        client.call("nodes.set_image", material_name="4K Working", node_name="Albedo", image_name="4K Painted")
        captures["painted"], captures["protected_after"] = capture(), capture("4K Protected")
        control("memory_after_commit")
        undo()
        undo()
        control("verify_recovery")
        assert pixels("4K Source")["pixels_sha256_float32_le"] == source_digest
        captures["recovered"], captures["protected_recovered"] = capture(), capture("4K Protected")

        cancelled = start("4K Cancelled")
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            value = inspect(cancelled)
            if value["state"] == "RUNNING" and value["progress"]["completed"] > 0:
                break
            assert not value["terminal"], value
            time.sleep(.02)
        else:
            raise AssertionError("No observed 4K CPU progress before cancellation")
        client.call("jobs.cancel", job_id=cancelled)
        value, _ = wait(cancelled)
        assert value["state"] == "CANCELLED" and not value["execution_started"]
        assert not value["error"]["context"]["possible_mutation"] and not value["undo_boundary_created"]
        control("verify_final")
        assert pixels("4K Source")["pixels_sha256_float32_le"] == source_digest
        RESULT.update(paint_wall_seconds=paint_seconds, phases=phases,
            candidate_pixel_tests=evidence["candidate_pixel_tests"], painted_pixels=evidence["painted_pixels"],
            coverage_scratch_max_bytes=evidence["coverage_scratch_max_bytes"],
            private_pixel_buffers_peak_estimate_bytes=evidence["private_pixel_buffers_peak_estimate_bytes"],
            inspect_poll_count=len(samples), inspect_poll_median_seconds=sorted(samples)[len(samples)//2],
            inspect_poll_max_seconds=max(samples))
    except Exception:
        RESULT["failure"] = traceback.format_exc()
    finally:
        if client is not None:
            client.close()
        DONE.set()


def setup():
    try:
        assert not bpy.app.background
        available = check_memory_headroom()
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        from blender_codex_bridge.tools import image_paint
        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = prefs.allow_external_files = False
        prefs.paint_job_budget_ms = 8
        for toolset in ("materials", "nodes", "objects"):
            runtime.registry.enable_toolset(toolset)
        def call(method, **params):
            return runtime.dispatch(method, params)
        # Actual post-write stop signals on the ordinary (non-job) canvas path.
        # The wrapper injects only the signal after native readback; allocation,
        # pixel writes, authoritative checks and confirmed undo remain real.
        original_read = image_paint._read
        for flag, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            def stopped_read(context, image, _flag=flag, **kwargs):
                value = original_read(context, image, **kwargs)
                if image.name == "Stopped Canvas":
                    getattr(runtime.state, "set_" + _flag)(True)
                return value
            image_paint._read = stopped_read
            try:
                call("image.create", new_name="Stopped Canvas", width=4, height=4, role="DATA")
            except BridgeError as error:
                assert error.code == code and error.context["possible_mutation"], error.to_dict()
                assert error.context["cleanup_permission_denied"] and error.context["undo_boundary_finalized"]
                assert bpy.data.images.get("Stopped Canvas") is not None
            else:
                raise AssertionError("Post-write canvas stop incorrectly reported success")
            finally:
                image_paint._read = original_read
                runtime.state.set_paused(False)
                runtime.state.set_emergency_stopped(False)
            recovered = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert recovered["snapshot_marker_verified"] and bpy.data.images.get("Stopped Canvas") is None
        stamp = time.perf_counter()
        created = call("image.create", new_name="4K Source", width=4096, height=4096, color=[.05, .1, .3, 1.])
        create_seconds = time.perf_counter()-stamp
        try:
            call("image.paint_version", image_name="4K Source", new_name="4K Sync Denied",
                 strokes=[{"points": [[.5, .5]], "radius_pixels": 2., "color": [1., 0., 0., 1.]}])
        except BridgeError as error:
            assert error.code == "INVALID_ARGUMENT" and bpy.data.images.get("4K Sync Denied") is None
        else:
            raise AssertionError("Large synchronous painting was not refused")
        panel = bpy.data.objects["Cube"]
        panel.name = "4K Panel"
        panel.data.clear_geometry()
        panel.data.from_pydata([(-1, -.5, 0), (1, -.5, 0), (1, .5, 0), (-1, .5, 0)], [], [(0, 1, 2, 3)])
        uv = panel.data.uv_layers.new(name="Canvas UV")
        for loop, co in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
            loop.uv = co
        material = panel.active_material
        material.name = "4K Original"
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name, node.image = "Albedo", bpy.data.images["4K Source"]
        material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
        uv_node = material.node_tree.nodes.new("ShaderNodeUVMap")
        uv_node.uv_map = "Canvas UV"
        material.node_tree.links.new(uv_node.outputs["UV"], node.inputs["Vector"])
        protected = panel.copy()
        protected.name, protected.location.x = "4K Protected", 3.5
        bpy.context.scene.collection.objects.link(protected)
        call("material.copy_for_object", object_name="4K Panel", slot_index=0, new_name="4K Working")
        baseline = call("scene.snapshot", object_names=["4K Protected", "Camera", "Light"])
        selection = sorted(obj.name for obj in bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active.name
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((0, 0, 1)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 2.5
        def capture(name):
            return call("viewport.capture", object_name=name, shading="material", view="current",
                        include_overlays=False, resolution=[768, 512])["path"]
        captures = {"before": capture("4K Panel"), "protected_before": capture("4K Protected")}
        memory = {"before_jobs": process_memory()}
        def apply(action):
            if action == "memory_after_commit":
                memory["after_commit"] = process_memory()
            elif action in {"verify_recovery", "verify_final"}:
                assert bpy.data.images.get("4K Painted") is None
                assert abs(bpy.data.objects["4K Panel"].location.z - .25) < 1e-6
                assert bpy.data.materials["4K Working"].node_tree.nodes["Albedo"].image.name == "4K Source"
                if action == "verify_final":
                    assert bpy.data.images.get("4K Cancelled") is None and runtime.jobs.active is None
                    assert all(not job.prepared and job.work is None for job in runtime.jobs.history)
                    assert sorted(obj.name for obj in bpy.context.selected_objects) == selection
                    assert bpy.context.view_layer.objects.active.name == active and bpy.context.mode == "OBJECT"
                    memory["after_cancel_recovery"] = process_memory()
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
            if not DONE.is_set() and time.monotonic()-started < 400:
                return .005
            try:
                assert DONE.is_set(), "Large-paint fixture timer expired"
                assert "failure" not in RESULT, RESULT.get("failure")
                compared = call("scene.compare", snapshot_id=baseline["snapshot_id"])
                assert compared["coverage_complete"] and compared["status"] == "unchanged_within_scope", compared
                assert not any((prefs.allow_execute_python, prefs.allow_save_project, prefs.allow_delete_objects, prefs.allow_external_files))
                print("BLENDER_LARGE_PAINT_OK " + json.dumps({"blender": bpy.app.version_string,
                    "image_size": [4096, 4096], "create_seconds": create_seconds, "host_available_bytes_at_start": available,
                    "process_memory": memory, "captures": captures, **RESULT,
                    "source_digest": created["pixels_sha256_float32_le"], "project_saved": False,
                    "post_write_canvas_pause_emergency_recovered": True,
                    "user_preferences_saved": False, "memory_pressure_acceptance_verified": False}), flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                runtime.emergency_stop()
                bpy.ops.wm.quit_blender()
            return None
        bpy.app.timers.register(supervise, first_interval=.005)
        threading.Thread(target=scenario, args=(port, created["pixels_sha256_float32_le"], captures), daemon=True,
                         name="BridgeLargePaintNetworkFixture").start()
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(setup, first_interval=1.)
