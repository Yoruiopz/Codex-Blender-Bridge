"""Real socket/timer export/reimport, full 4K raw data and native undo evidence.

Run through run_blender_checks.py: private Windows desktop or an isolated Linux test display.
The worker owns sockets/JSON, never bpy. All fixture faults run on the main thread.
"""
from __future__ import annotations

import hashlib
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

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"addon"), str(ROOT/"scripts")]
CONTROLS, DONE, RESULT = queue.Queue(), threading.Event(), {}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


class Client:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=90)
        self.stream, self.sequence = self.socket.makefile("rb"), 0

    def call(self, method, **params):
        self.sequence += 1
        request = {"id": f"delivery_{self.sequence}", "method": method, "params": params,
                   "protocol_version": "1.0", "timeout_ms": 60000}
        self.socket.sendall((json.dumps(request)+"\n").encode())
        result = json.loads(self.stream.readline())
        assert result["id"] == request["id"] and result["ok"], result
        return result["result"]

    def close(self):
        self.stream.close()
        self.socket.close()


def control(action, **params):
    event, result = threading.Event(), []
    CONTROLS.put((action, params, event, result))
    assert event.wait(90), f"Main-thread fixture control timeout: {action}"
    assert result and result[0] is True, result
    return result[1] if len(result) > 1 else None


def scenario(port, folder, digests, captures):
    client, polls, outcomes, starts = Client(port), [], [], {}
    def start(source, name, format="EXR32_RAW", limit=300.):
        suffix = ".png" if format.startswith("PNG") else ".exr"
        started = time.perf_counter()
        value = client.call("image.export_job_start", image_name=source, new_name=name,
                            filepath=str(Path(folder)/(name+suffix)), format=format, time_limit_seconds=limit)
        assert value["accepted"] and not value["export_completed"] and not value["undo_boundary_created"]
        starts[value["job_id"]] = started
        return value["job_id"]
    def wait(identifier):
        deadline, phases, revision = time.monotonic()+360, set(), 0
        while time.monotonic() < deadline:
            started = time.perf_counter()
            value = client.call("jobs.inspect", job_id=identifier)
            polls.append(time.perf_counter()-started)
            assert value["revision"] >= revision
            revision = value["revision"]
            phases.add(value["progress"]["phase"])
            if value["terminal"]:
                value["observed_phases"] = sorted(phases)
                effects, result, error = value["external_effects"], value.get("result") or {}, value.get("error") or {}
                outcomes.append({"name": value["new_image"], "state": value["state"], "job_id": identifier,
                    "duration_seconds": time.perf_counter()-starts[identifier], "revision": value["revision"],
                    "execution_started": value["execution_started"], "undo_boundary_finalized": value["undo_boundary_finalized"],
                    "observed_phases": sorted(phases), "file_published": effects.get("file_published"),
                    "file_bytes": effects.get("file_bytes"), "file_sha256": effects.get("file_sha256"),
                    "filepath": effects.get("filepath"), "staging_cleanup": effects.get("staging_cleanup"),
                    "retained_staging_path": effects.get("retained_staging_path"), "error_code": error.get("code"),
                    "possible_mutation": error.get("context", {}).get("possible_mutation"),
                    "source_associated_converted_to_straight": result.get("source_associated_converted_to_straight"),
                    "pixel_verification": result.get("pixel_verification")})
                print(f"DELIVERY_FIXTURE {value['new_image']}: {value['state']}", flush=True)
                return value
            time.sleep(.025)
        raise AssertionError("Delivery job did not terminate")
    def undo():
        assert client.call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)["snapshot_marker_verified"]
    try:
        for role in ("COLOR", "DATA"):
            source = "Color Source" if role == "COLOR" else "Data Source"
            for format in ("PNG8", "PNG16", "EXR32", "EXR32_RAW"):
                name = role+"_"+format
                identifier = start(source, name, format)
                if role == "COLOR" and format == "PNG8":
                    client.call("transform.set", object_name="Cube", location=[0., 0., .125])
                value = wait(identifier)
                assert value["state"] == "SUCCEEDED" and value["undo_boundary_finalized"], value
                assert value["result"]["pixel_verification"]["all_channels_compared"] == 8*4*4
                assert value["external_effects"]["file_published"] and value["external_effects"]["staging_cleanup"] == "removed"
                if role == "COLOR":
                    client.call("nodes.set_image", material_name="Delivery Material", node_name="Texture", image_name=name)
                    captures[name] = control("render", name=name)
                    undo()
                undo()
                control("verify_undo", name=name, path=value["external_effects"]["filepath"], digest=value["external_effects"]["file_sha256"])
                assert client.call("image.inspect_pixels", image_name=source)["pixels_sha256_float32_le"] == digests[source]

        identifier = start("Large Data Source", "Full4K")
        client.call("transform.set", object_name="Cube", location=[0., 0., .25])
        value = wait(identifier)
        assert value["state"] == "SUCCEEDED" and value["undo_boundary_finalized"], value
        verified = value["result"]["pixel_verification"]
        assert verified["exact_raw_float32_bits_verified"] and verified["all_channels_compared"] == 4096*4096*4
        assert verified["native_pixels_sha256_float32_le"] == digests["Large Data Source"]
        assert value["external_effects"]["file_bytes"] == 268501384
        assert "encoding" in value["observed_phases"] and len(polls) > 4
        inspected = client.call("image.inspect_pixels", image_name="Full4K", include_statistics=False,
                                samples=[[0,0],[4095,0],[0,4095],[4095,4095]])
        assert inspected["pixels_sha256_float32_le"] == digests["Large Data Source"]
        undo()
        control("verify_undo", name="Full4K", path=value["external_effects"]["filepath"], digest=value["external_effects"]["file_sha256"])
        assert client.call("image.inspect_pixels", image_name="Large Data Source", include_statistics=False)["pixels_sha256_float32_le"] == digests["Large Data Source"]

        for name, action in (("Cancelled", "cancel"), ("Disconnected", "disconnect"), ("Paused", "pause"),
                             ("Denied", "deny"), ("AfterFile", "fault_file"), ("AfterNative", "fault_native")):
            if action.startswith("fault"):
                control(action)
            identifier = start("Control Source", name, limit=1. if action == "pause" else 60.)
            if action == "cancel":
                client.call("jobs.cancel", job_id=identifier)
            elif action == "disconnect":
                client.close()
                client = Client(port)
            elif action in {"pause", "deny"}:
                control(action)
            value = wait(identifier)
            assert value["state"] == ("FAILED" if action == "deny" else "CANCELLED"), value
            control("reset")
            if action.startswith("fault"):
                assert value["external_effects"]["file_published"] and value["error"]["context"]["possible_mutation"], value
                assert not value["error"]["context"]["rollback_verified"]
                if action == "fault_native":
                    assert value["undo_boundary_finalized"]
                    undo()
                control("verify_undo", name=name, path=value["external_effects"]["filepath"], digest=value["external_effects"]["file_sha256"])
            else:
                assert not value["external_effects"]["file_published"] and not value["execution_started"], value
        records = client.call("checkpoint.list", limit=20)["operation_history"]
        audit = next(record["job_evidence"] for record in records if (record.get("job_evidence") or {}).get("job_id") == value["job_id"])
        assert audit["external_effects"]["filepath"] == value["external_effects"]["filepath"]
        control("deny_inspection")
        hidden = client.call("checkpoint.list", limit=20)["operation_history"]
        assert any(record.get("job_evidence_redacted") for record in hidden)
        assert all(record.get("job_evidence") is None for record in hidden)
        assert value["external_effects"]["file_sha256"] not in json.dumps(hidden)
        assert "external_effects" not in client.call("bridge.status")["jobs"]["last_terminal"]
        control("reset")
        restored = client.call("checkpoint.list", limit=20)["operation_history"]
        assert any((record.get("job_evidence") or {}).get("job_id") == value["job_id"] for record in restored)
        RESULT.update(outcomes=outcomes, history_inspection_redaction_verified=True, inspect_poll_count=len(polls), inspect_poll_max_seconds=max(polls),
                      inspect_poll_median_seconds=sorted(polls)[len(polls)//2])
    except Exception:
        RESULT["failure"] = traceback.format_exc()
    finally:
        client.close()
        DONE.set()


def setup():
    try:
        assert not bpy.app.background, "Use the isolated UI runner for native undo"
        bpy.context.preferences.use_preferences_save = False
        from blender_image_streams_smoke import file_hash as independent_hash
        from blender_large_paint_smoke import check_memory_headroom

        available = check_memory_headroom()
        assert available >= 8*1024**3, "Full4K fixture requires8GiB host headroom; no memory-pressure induction"
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge import texture_staging, texture_verification
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_delete_objects = False
        prefs.allow_edit_materials = prefs.allow_external_files = prefs.allow_save_project = True
        prefs.paint_job_budget_ms = 8
        for toolset in ("materials", "nodes", "objects"):
            runtime.registry.enable_toolset(toolset)
        folder = Path(__import__("os").environ["TEMP"])/"texture-delivery"
        folder.mkdir()
        prefs.texture_directory = str(folder)
        def call(method, **params):
            return runtime.dispatch(method, params)
        scene, selection = call("scene.inspect"), call("selection.inspect")
        digests = {}
        for name, role, size in (("Color Source", "COLOR", (8,4)), ("Data Source", "DATA", (8,4)), ("Control Source", "DATA", (512,512))):
            result = call("image.create", new_name=name, role=role, width=size[0], height=size[1], color=[.25,.5,.75,.25])
            digests[name] = result["pixels_sha256_float32_le"]
            bpy.data.images[name].use_fake_user = True
        large = bpy.data.images.new("Large Data Source", 4096, 4096, alpha=True, float_buffer=True)
        large.colorspace_settings.name, large.alpha_mode, large.use_fake_user = "Non-Color", "CHANNEL_PACKED", True
        values = array("f", [.25,-.125,65536.,-2.])*(4096*4096)
        for (x,y), rgba in { (0,0):[-0.,1.,2.,3.], (4095,0):[4.,5.,6.,7.], (0,4095):[-1.,-2.,-3.,-4.], (4095,4095):[8.,9.,10.,11.] }.items():
            offset = (y*4096+x)*4
            values[offset:offset+4] = array("f", rgba)
        digests[large.name] = hashlib.sha256(values).hexdigest()
        large.pixels.foreach_set(values)
        large.update()
        del values, large
        assert call("image.inspect_pixels", image_name="Large Data Source", include_statistics=False)["pixels_sha256_float32_le"] == digests["Large Data Source"]

        panel, camera = bpy.data.objects["Cube"], bpy.data.objects["Camera"]
        panel.data.clear_geometry()
        panel.data.from_pydata([(-1,-.5,0),(1,-.5,0),(1,.5,0),(-1,.5,0)], [], [(0,1,2,3)])
        uv = panel.data.uv_layers.new(name="DeliveryUV")
        for loop, coordinate in zip(uv.data, [(0,0),(1,0),(1,1),(0,1)], strict=True):
            loop.uv = coordinate
        material = panel.active_material
        material.name, material.use_nodes = "Delivery Material", True
        nodes = material.node_tree.nodes
        nodes.clear()
        texture, output = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeOutputMaterial")
        texture.name, texture.image = "Texture", bpy.data.images["Color Source"]
        emission, transparent, mix = nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeBsdfTransparent"), nodes.new("ShaderNodeMixShader")
        for source, destination in ((texture.outputs["Color"], emission.inputs["Color"]), (texture.outputs["Alpha"], mix.inputs[0]),
                                    (transparent.outputs[0], mix.inputs[1]), (emission.outputs[0], mix.inputs[2]), (mix.outputs[0], output.inputs[0])):
            material.node_tree.links.new(source, destination)
        camera.location, camera.rotation_euler = (0,0,3), (0,0,0)
        camera.data.type, camera.data.ortho_scale = "ORTHO", 2.5
        scene_data = bpy.context.scene
        scene_data.camera, scene_data.render.engine = camera, "CYCLES"
        scene_data.cycles.device, scene_data.cycles.samples = "CPU", 1
        scene_data.cycles.use_denoising = False
        scene_data.render.resolution_x = scene_data.render.resolution_y = 32
        scene_data.render.resolution_percentage = 100
        scene_data.view_settings.view_transform = "Standard"
        def render(name):
            path = folder/(name+"-camera.png")
            bpy.ops.render.render()
            bpy.data.images["Render Result"].save_render(str(path))
            return str(path)
        captures = {"before": render("before")}
        protected = call("scene.snapshot", object_names=["Camera", "Light"])
        selected = sorted(obj.name for obj in bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active.name
        original_publish, original_compare = texture_staging.TextureStaging.publish, texture_verification.compare_steps
        def publish(resource):
            result = original_publish(resource)
            if resource.path.stem == "AfterFile":
                runtime.jobs.cancel_all("fixture cancellation after atomic publication")
            return result
        def compare(*args, **kwargs):
            runtime.jobs.cancel_all("fixture cancellation after finalized native reimport")
            yield from original_compare(*args, **kwargs)
        def apply(action, params):
            if action == "render":
                return render(params["name"])
            if action == "verify_undo":
                assert bpy.data.images.get(params["name"]) is None
                assert independent_hash(Path(params["path"])) == params["digest"]
                assert abs(bpy.data.objects["Cube"].location.z-(.25 if params["name"] in {"Full4K", "AfterFile", "AfterNative"} else .125)) < 1e-6
            elif action == "pause":
                runtime.state.set_paused(True)
            elif action == "deny":
                prefs.allow_external_files = False
            elif action == "deny_inspection":
                prefs.allow_inspect_scene = False
            elif action == "fault_file":
                texture_staging.TextureStaging.publish = publish
            elif action == "fault_native":
                texture_verification.compare_steps = compare
            elif action == "reset":
                runtime.state.set_paused(False)
                prefs.allow_external_files = True
                prefs.allow_inspect_scene = True
                texture_staging.TextureStaging.publish = original_publish
                texture_verification.compare_steps = original_compare
            else:
                raise AssertionError(action)
        probe = socket.socket()
        probe.bind(("127.0.0.1",0))
        port = probe.getsockname()[1]
        probe.close()
        runtime.start_server("127.0.0.1", port, request_timeout=60)
        started = time.monotonic()
        def supervise():
            while not CONTROLS.empty():
                action, params, event, result = CONTROLS.get_nowait()
                try:
                    result.extend((True, apply(action, params)))
                except Exception:
                    result.append(traceback.format_exc())
                finally:
                    event.set()
            if not DONE.is_set() and time.monotonic()-started < 800:
                return .005
            try:
                assert DONE.is_set() and "failure" not in RESULT, RESULT.get("failure", "Fixture timed out")
                comparison = call("scene.compare", snapshot_id=protected["snapshot_id"])
                assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope", comparison
                assert sorted(obj.name for obj in bpy.context.selected_objects) == selected
                assert bpy.context.view_layer.objects.active.name == active and bpy.context.mode == selection["mode"] == "OBJECT"
                assert runtime.jobs.active is None and not prefs.allow_execute_python and not prefs.allow_delete_objects
                assert all(not job.prepared and job.work is None and job.driver is None for job in runtime.jobs.history)
                assert bpy.data.filepath == "" and not bpy.context.preferences.use_preferences_save
                print("BLENDER_IMAGE_DELIVERY_OK "+json.dumps({"blender": bpy.app.version_string, "initial_scene": scene["scene"],
                    "captures": captures, "observations": RESULT, "host_available_bytes_at_start": available,
                    "protected_objects_and_source_pixels_verified": True, "project_saved": False, "user_preferences_saved": False,
                    "scope": "Typed full-size cooperative export/reimport and explicit external/native recovery; not crash durability, fresh-process, packing or full artist acceptance"}), flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                texture_staging.TextureStaging.publish, texture_verification.compare_steps = original_publish, original_compare
                runtime.emergency_stop()
                bpy.ops.wm.quit_blender()
            return None
        bpy.app.timers.register(supervise, first_interval=.005)
        threading.Thread(target=scenario, args=(port, str(folder), digests, captures), daemon=True,
                         name="ImageDeliveryNetworkFixture").start()
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(setup, first_interval=1.)
