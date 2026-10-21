"""Raw UV masks: native pixels, resampling, live jobs, preservation and recovery.

Run only through run_blender_checks.py (private non-input desktop on Windows).
"""
from __future__ import annotations

import json
import queue
import socket
import struct
import sys
import tempfile
import threading
import time
import traceback
import zlib
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from blender_paint_jobs_smoke import Client  # noqa: E402

CONTROLS, DONE, RESULT = queue.Queue(), threading.Event(), {}
BRUSH = {"points": [[.05, .5], [.95, .5]], "radius_pixels": 12., "hardness": 1.,
         "color": [.8, .2, .05, 1.], "opacity": .75}


def assert_rgba(actual, expected):
    assert all(abs(a-b) < 1e-6 for a, b in zip(actual, expected, strict=True)), (actual, expected)


def control(action):
    event, result = threading.Event(), []
    CONTROLS.put((action, event, result))
    assert event.wait(15), action
    assert result == [True], result


def scenario(port, captures, source_digest, mask_digest):
    client = None
    try:
        client = Client(port)
        def start(name, mask="Mask Pattern", invert=False):
            accepted = client.call("image.paint_job_start", image_name="Job Canvas", new_name=name,
                strokes=[{**BRUSH, "radius_pixels": 64.}], time_limit_seconds=60.,
                mask={"image_name": mask, "channel": "R", "invert": invert})
            assert accepted["accepted"] and accepted["workload"]["mask"]["channel"] == "R"
            return accepted["job_id"]
        def wait(job_id):
            deadline, phases = time.monotonic()+70, set()
            while time.monotonic() < deadline:
                value = client.call("jobs.inspect", job_id=job_id)
                phases.add(value["progress"]["phase"])
                if value["terminal"]:
                    return value, sorted(phases)
                time.sleep(.01)
            raise AssertionError("Mask job never terminated")
        def pixels(name, samples=None):
            return client.call("image.inspect_pixels", image_name=name, samples=samples or [])
        def capture(name="Mask Panel"):
            return client.call("viewport.capture", object_name=name, shading="material", view="current",
                include_overlays=False, resolution=[768, 512])["path"]
        def undo():
            assert client.call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)["snapshot_marker_verified"]

        job = start("Masked Job")
        client.call("transform.set", object_name="Mask Panel", location=[0., 0., .25])
        captures["interleaved_before"] = capture()
        value, phases = wait(job)
        assert value["state"] == "SUCCEEDED" and value["undo_boundary_finalized"], value
        measured = pixels("Masked Job", [[128, 256], [384, 256]])
        assert_rgba(measured["samples"][0]["rgba"], [.6125, .175, .1125, 1.])
        assert_rgba(measured["samples"][1]["rgba"], [.05, .1, .3, 1.])
        assert measured["pixels_sha256_float32_le"] == value["result"]["pixels_sha256_float32_le"]
        assert pixels("Job Canvas")["pixels_sha256_float32_le"] == source_digest
        assert pixels("Mask Pattern")["pixels_sha256_float32_le"] == mask_digest
        client.call("nodes.set_image", material_name="Mask Working", node_name="Albedo", image_name="Masked Job")
        captures["masked_job"], captures["protected_after"] = capture(), capture("Mask Protected")
        undo()
        undo()
        control("verify_recovery")
        captures["recovered"], captures["protected_recovered"] = capture(), capture("Mask Protected")

        inverse = start("Inverse Job", invert=True)
        value, _ = wait(inverse)
        assert value["state"] == "SUCCEEDED" and value["result"]["mask"]["invert"], value
        measured = pixels("Inverse Job", [[128, 256], [384, 256]])
        assert_rgba(measured["samples"][0]["rgba"], [.05, .1, .3, 1.])
        assert_rgba(measured["samples"][1]["rgba"], [.6125, .175, .1125, 1.])
        client.call("nodes.set_image", material_name="Mask Working", node_name="Albedo", image_name="Inverse Job")
        captures["inverse_job"] = capture()
        undo()
        undo()

        large = start("Large Mask Job", "Large Mask")
        value, large_phases = wait(large)
        assert value["state"] == "SUCCEEDED" and value["workload"]["large_image_requires_job"], value
        assert value["result"]["mask"]["size"] == [1025, 1024]
        assert "validating_mask" in large_phases, large_phases
        assert_rgba(pixels("Large Mask Job", [[256,256]])["samples"][0]["rgba"], [.33125,.1375,.20625,1.])
        undo()

        control("arm_late_mask_change")
        late = start("Late Mask")
        value, _ = wait(late)
        control("disarm_late_mask_change")
        assert value["state"] == "FAILED" and value["error"]["context"]["stale_mask"], value
        assert value["error"]["context"]["possible_mutation"] and value["undo_boundary_finalized"], value
        pixels("Late Mask")  # Retained output, not a claimed rollback or unauthorized delete.
        undo()
        # Global undo removes owned output, not externally changed ImBuf pixels.
        # Never silently undo/rewrite a user's mask edit. The fixture explicitly
        # restores its own injected change afterward, separately from recovery.
        assert pixels("Mask Pattern")["pixels_sha256_float32_le"] != mask_digest
        control("restore_mask")
        assert pixels("Mask Pattern")["pixels_sha256_float32_le"] == mask_digest

        stale = start("Stale Mask")
        control("change_mask")
        value, _ = wait(stale)
        assert value["state"] == "FAILED" and value["error"]["context"]["stale_mask"], value
        assert not value["execution_started"] and not value["undo_boundary_created"]
        control("restore_mask")

        denied = start("Denied File Mask", "File Mask")
        control("deny_external")
        value, _ = wait(denied)
        assert value["state"] == "FAILED" and value["error"]["code"] == "PERMISSION_DENIED", value
        assert not value["execution_started"]
        control("allow_external")

        cancelled = start("Cancelled Mask")
        client.call("jobs.cancel", job_id=cancelled)
        value, _ = wait(cancelled)
        assert value["state"] == "CANCELLED" and not value["execution_started"], value
        assert pixels("Job Canvas")["pixels_sha256_float32_le"] == source_digest
        assert pixels("Mask Pattern")["pixels_sha256_float32_le"] == mask_digest
        # Last: native undo of an external alpha-role edit may invalidate an
        # existing generated ImBuf. Record that limitation, never regenerate it
        # implicitly and then pretend input pixels were recovered.
        control("arm_late_canvas_change")
        late_canvas = start("Late Canvas")
        value, _ = wait(late_canvas)
        control("disarm_late_mask_change")
        assert value["state"] == "FAILED" and value["error"]["context"]["stale_source"], value
        assert not value["error"]["context"]["input_preservation_verified"] and value["undo_boundary_finalized"]
        pixels("Late Canvas")
        undo()
        control("verify_canvas_output_recovered")
        control("verify_final")
        RESULT.update(job_phases=phases, masked_job_verified=True, inverse_job_verified=True,
            large_mask_validation_phases=large_phases, large_mask_verified=True, post_write_mask_failure_output_recovered=True,
            external_mask_pixel_edit_retained_by_native_undo=True, fixture_restored_own_injected_mask_edit=True,
            post_write_canvas_metadata_change_refused=True, late_canvas_output_recovered=True,
            stale_mask_refused=True, file_mask_live_grant_refused=True, precommit_cancel_verified=True)
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
        from blender_codex_bridge.tools import image_paint
        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = prefs.allow_external_files = False
        prefs.paint_job_budget_ms = 1
        for toolset in ("materials", "nodes", "objects"):
            runtime.registry.enable_toolset(toolset)
        def call(method, **params):
            return runtime.dispatch(method, params)
        def pixels(name, samples=None):
            return call("image.inspect_pixels", image_name=name, samples=samples or [])
        source = call("image.create", new_name="Source", width=128, height=64, color=[.05, .1, .3, 1.])
        job_source = call("image.create", new_name="Job Canvas", width=512, height=512, color=[.05, .1, .3, 1.])
        canvas_alpha_before = bpy.data.images["Job Canvas"].alpha_mode
        call("image.create", new_name="Mask Base", width=16, height=8, role="DATA", color=[0., 0., 0., 1.])
        patterned = call("image.paint_version", image_name="Mask Base", new_name="Mask Pattern",
            strokes=[{"points": [[.25, .5]], "radius_pixels": 2.5, "hardness": 1., "color": [1., 1., 1., 1.]}])
        mask_digest = patterned["pixels_sha256_float32_le"]
        for channel in ("R", "G", "B", "A"):
            version = call("image.paint_version", image_name="Source", new_name="Channel " + channel,
                strokes=[BRUSH], mask={"image_name": "Mask Pattern", "channel": channel})
            measured = pixels("Channel " + channel, [[32, 32], [96, 32], [50, 32]])
            assert_rgba(measured["samples"][0]["rgba"], [.6125, .175, .1125, 1.])
            assert_rgba(measured["samples"][1]["rgba"], [.6125, .175, .1125, 1.] if channel == "A" else [.05, .1, .3, 1.])
            # Different-resolution interpolation: fx=5.8125; columns 5=1,6=0.
            assert_rgba(measured["samples"][2]["rgba"], [.6125, .175, .1125, 1.] if channel == "A" else [.15546875, .1140625, .26484375, 1.])
            assert version["mask"]["pixels_unchanged"]
        zero = call("image.paint_version", image_name="Source", new_name="Zero Mask", strokes=[BRUSH], mask={"image_name": "Mask Base"})
        assert zero["painted_pixels"] == 0 and zero["pixels_sha256_float32_le"] == source["pixels_sha256_float32_le"]
        call("image.create", new_name="Large Mask", width=1025, height=1024, role="DATA", color=[.5,.5,.5,1.])
        try:
            call("image.paint_version", image_name="Source", new_name="Oversize Sync Mask", strokes=[BRUSH], mask={"image_name": "Large Mask"})
        except image_paint.BridgeError as error:
            assert error.code == "INVALID_ARGUMENT" and bpy.data.images.get("Oversize Sync Mask") is None
        else:
            raise AssertionError("Large synchronous mask was not refused")

        # Owned fixture PNG, loaded through the actual approved-path typed tool.
        directory = tempfile.TemporaryDirectory(prefix="bridge-mask-file-")
        folder = Path(directory.name)
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)
        path = folder / "mask.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 4, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0"+bytes((128,64,32,128))*8)*4)) + chunk(b"IEND", b""))
        prefs.texture_directory, prefs.allow_external_files = str(folder), True
        call("image.load", filepath=str(path), new_name="File Mask")
        call("image.paint_version", image_name="Source", new_name="Raw File Mask", strokes=[BRUSH], mask={"image_name": "File Mask"})
        sample = pixels("Raw File Mask", [[32,32]])["samples"][0]["rgba"]
        amount = .75 * (128/255)
        assert_rgba(sample, [.05*(1-amount)+.8*amount, .1*(1-amount)+.2*amount, .3*(1-amount)+.05*amount, 1.])
        assert pixels("Source")["pixels_sha256_float32_le"] == source["pixels_sha256_float32_le"]
        assert pixels("Mask Pattern")["pixels_sha256_float32_le"] == mask_digest

        panel = bpy.data.objects["Cube"]
        panel.name = "Mask Panel"
        panel.data.clear_geometry()
        panel.data.from_pydata([(-1,-.5,0),(1,-.5,0),(1,.5,0),(-1,.5,0)], [], [(0,1,2,3)])
        uv = panel.data.uv_layers.new(name="Canvas UV")
        for loop, co in zip(uv.data, [(0,0),(1,0),(1,1),(0,1)], strict=True):
            loop.uv = co
        material = panel.active_material
        material.name = "Mask Original"
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name, node.image = "Albedo", bpy.data.images["Source"]
        material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
        uv_node = material.node_tree.nodes.new("ShaderNodeUVMap")
        uv_node.uv_map = "Canvas UV"
        material.node_tree.links.new(uv_node.outputs["UV"], node.inputs["Vector"])
        protected = panel.copy()
        protected.name, protected.location.x = "Mask Protected", 3.5
        bpy.context.scene.collection.objects.link(protected)
        call("material.copy_for_object", object_name="Mask Panel", slot_index=0, new_name="Mask Working")
        baseline = call("scene.snapshot", object_names=["Mask Protected", "Camera", "Light"])
        selection, active = sorted(obj.name for obj in bpy.context.selected_objects), bpy.context.view_layer.objects.active.name
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((0,0,1)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 2.5
        def capture(name):
            return call("viewport.capture", object_name=name, shading="material", view="current",
                include_overlays=False, resolution=[768,512])["path"]
        captures = {"before": capture("Mask Panel"), "protected_before": capture("Mask Protected")}
        original_mask = bpy.data.images["Mask Pattern"].pixels[0]
        original_read = image_paint._read
        def late_mask_change(context, image, **kwargs):
            value = original_read(context, image, **kwargs)
            if image.name == "Late Mask":
                bpy.data.images["Mask Pattern"].pixels[0] = .123
            if image.name == "Late Canvas":
                bpy.data.images["Job Canvas"].alpha_mode = "PREMUL"
            return value
        def apply(action):
            if action == "change_mask":
                bpy.data.images["Mask Pattern"].pixels[0] = .123
            elif action == "restore_mask":
                bpy.data.images["Mask Pattern"].pixels[0] = original_mask
            elif action == "deny_external":
                prefs.allow_external_files = False
            elif action == "allow_external":
                prefs.allow_external_files = True
            elif action in {"arm_late_mask_change", "arm_late_canvas_change"}:
                image_paint._read = late_mask_change
            elif action == "disarm_late_mask_change":
                image_paint._read = original_read
            elif action == "verify_canvas_output_recovered":
                assert bpy.data.images.get("Late Canvas") is None
                assert bpy.data.images["Job Canvas"].alpha_mode == canvas_alpha_before
                RESULT["canvas_buffer_loaded_after_external_metadata_undo"] = bool(bpy.data.images["Job Canvas"].has_data)
                RESULT["late_canvas_input_pixel_recovery_verified"] = False  # No independent full digest if buffer invalidated.
            elif action in {"verify_recovery", "verify_final"}:
                assert bpy.data.images.get("Masked Job") is None
                assert bpy.data.materials["Mask Working"].node_tree.nodes["Albedo"].image.name == "Source"
                assert abs(bpy.data.objects["Mask Panel"].location.z-.25) < 1e-6
                if action == "verify_final":
                    for name in ("Inverse Job", "Stale Mask", "Denied File Mask", "Cancelled Mask", "Large Mask Job", "Late Mask", "Late Canvas"):
                        assert bpy.data.images.get(name) is None, name
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
                assert DONE.is_set() and "failure" not in RESULT, RESULT.get("failure", "Mask fixture expired")
                comparison = call("scene.compare", snapshot_id=baseline["snapshot_id"])
                assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope", comparison
                assert not any((prefs.allow_execute_python, prefs.allow_save_project, prefs.allow_delete_objects))
                print("BLENDER_IMAGE_MASKS_OK " + json.dumps({"blender": bpy.app.version_string,
                    "captures": captures, "all_rgba_channels_verified": True, "bilinear_resampling_verified": True,
                    "raw_srgb_file_channel_verified": True, "zero_mask_verified": True,
                    "source_digest": job_source["pixels_sha256_float32_le"], "mask_digest": mask_digest,
                    "protected_scope_unchanged": True, "project_saved": False, "user_preferences_saved": False, **RESULT}), flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                runtime.emergency_stop()
                image_paint._read = original_read
                directory.cleanup()
                bpy.ops.wm.quit_blender()
            return None
        bpy.app.timers.register(supervise, first_interval=.005)
        threading.Thread(target=scenario, args=(port,captures,job_source["pixels_sha256_float32_le"],mask_digest),
            daemon=True, name="BridgeMaskNetworkFixture").start()
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(setup, first_interval=1.)
