"""Typed snapshot/recovery jobs through real socket/timer and fresh processes.

All bpy, fault injection and panel calls run on the isolated main thread. The
worker performs JSON/socket I/O only. Run exclusively through the native runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import socket
import sys
import threading
import time
import traceback
from array import array
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from blender_image_delivery_smoke import Client  # noqa: E402
from native_resources import linux_available_memory, linux_process_memory  # noqa: E402

CONTROLS, DONE, RESULT = queue.Queue(), threading.Event(), {}


def digest(values):
    return hashlib.sha256(values).hexdigest()


def pixels(image):
    values = array("f", [0.]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return values


def control(action, **params):
    event, result = threading.Event(), []
    CONTROLS.put((action, params, event, result))
    assert event.wait(90), f"Main-thread fixture timeout: {action}"
    assert result and result[0] is True, result
    return result[1] if len(result) > 1 else None


def scenario(port, phase, bundle, rows, large):
    client, polls, outcomes, acceptance = Client(port), [], [], {}
    def start(row, name=None, limit=300.):
        started = time.perf_counter()
        value = client.call("image.snapshot_job_start", image_name=row["name"],
            new_name=name or row["snapshot"], time_limit_seconds=limit)
        acceptance[value["job_id"]] = time.perf_counter()-started
        assert value["accepted"] and not value["job_completed"] and not value["undo_boundary_created"], value
        return value["job_id"], started
    def wait(job, started):
        deadline, phases, revision = time.monotonic()+360, set(), 0
        while time.monotonic() < deadline:
            stamp = time.perf_counter()
            value = client.call("jobs.inspect", job_id=job)
            polls.append(time.perf_counter()-stamp)
            assert value["revision"] >= revision
            revision = value["revision"]
            phases.add(value["progress"]["phase"])
            if value["terminal"]:
                assert not value["external_effects"] and not value["evidence_observation_unknown"], value
                outcomes.append({"image": value["new_image"], "state": value["state"],
                    "elapsed_seconds": time.perf_counter()-started, "poll_phases": sorted(phases),
                    "start_response_seconds": acceptance[job],
                    "revision": revision, "execution_started": value["execution_started"],
                    "undo_boundary_finalized": value["undo_boundary_finalized"],
                    "recovery_evidence": value["recovery_evidence"]})
                return value
            time.sleep(.005)
        raise AssertionError("Recovery job did not terminate")
    def restore(row, *, expect_success=True):
        preview_started = time.perf_counter()
        inspected = client.call("image.recovery_job_preview", image_name=row["name"],
            snapshot_name=row["snapshot"], allow_shared=True)
        preview_seconds = time.perf_counter()-preview_started
        assert not inspected["mutation_performed"] and not inspected["snapshot_pixels_verified"], inspected
        started = time.perf_counter()
        accepted = client.call("image.restore_snapshot_job_start", image_name=row["name"],
            snapshot_name=row["snapshot"], expected_target_fingerprint=inspected["expected_target_fingerprint"],
            confirm_replace_packed_bytes=inspected["requires_confirm_replace_packed_bytes"], allow_shared=True,
            time_limit_seconds=300.)
        acceptance[accepted["job_id"]] = time.perf_counter()-started
        value = wait(accepted["job_id"], started)
        outcomes[-1]["preview_seconds"] = preview_seconds
        if expect_success:
            assert value["state"] == "SUCCEEDED" and value["recovery_evidence"]["complete_pixels_verified"], value
            assert value["result"]["mode"] == inspected["mode"], value
        else:
            assert value["state"] == "FAILED" and value["error"]["code"] == "PERMISSION_DENIED", value
            assert value["execution_started"] and value["undo_boundary_finalized"], value
            assert value["error"]["context"]["possible_mutation"], value
            assert value["recovery_evidence"]["snapshot_retained"] and not value["recovery_evidence"]["complete_pixels_verified"], value
        control("verify", row=row)
        return value
    try:
        main = rows[0]
        if phase == "writer":
            # Distinct real owner lifetimes, no synthetic direct generator check.
            identifier, stamp = start(main, "Cancelled Snapshot")
            client.call("jobs.cancel", job_id=identifier)
            value = wait(identifier, stamp)
            assert value["state"] == "CANCELLED" and not value["execution_started"], value
            identifier, stamp = start(main, "Disconnected Snapshot")
            client.close()
            client = Client(port)
            value = wait(identifier, stamp)
            assert value["state"] == "CANCELLED" and not value["execution_started"], value
            assert value["error"]["context"]["connection_disconnected"], value
            if not large:
                identifier, stamp = start(main, "Expired Snapshot", 1.)
                control("pause")
                value = wait(identifier, stamp)
                assert value["state"] == "CANCELLED" and value["error"]["context"]["job_deadline_expired"], value
                control("resume")
                identifier, stamp = start(main, "Denied Snapshot")
                control("deny")
                value = wait(identifier, stamp)
                assert value["state"] == "FAILED" and value["error"]["code"] == "PERMISSION_DENIED", value
                control("allow")
                identifier, stamp = start(main, "Stale Snapshot")
                control("stale")
                value = wait(identifier, stamp)
                assert value["state"] == "FAILED" and not value["execution_started"], value
                control("unstale")
            identifier, stamp = start(main)
            control("panel")
            control("manual_transform")
            value = wait(identifier, stamp)
            assert value["state"] == "SUCCEEDED" and value["undo_boundary_finalized"], value
            assert value["recovery_evidence"]["snapshot_retained"] and not value["recovery_evidence"]["project_saved"], value
            control("verify", row=main)
            if not large:
                undone = client.call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
                assert undone["snapshot_marker_verified"], undone
                control("verify_undo")
                identifier, stamp = start(main)
                assert wait(identifier, stamp)["state"] == "SUCCEEDED"
            control("change", row=main)
            if not large:
                control("arm_late_restore")
                restore(main, expect_success=False)
                control("disarm_late_restore")
            restore(main)
            for row in rows[1:]:
                identifier, stamp = start(row)
                value = wait(identifier, stamp)
                assert value["state"] == "SUCCEEDED", value
                control("unload", row=row)
                restore(row)
            # This is explicitly separate from snapshot completion/durability.
            client.call("project.save", filepath=str(bundle/"image-recovery-jobs.blend"))
            control("manifest")
        else:
            # GENERATED getters allocate default generated pixels, never FILE reads.
            control("allocate_generated")
            for row in rows:
                restore(row)
            control("panel")
        control("final")
        RESULT.update(outcomes=outcomes, poll_count=len(polls), poll_max_seconds=max(polls),
            poll_median_seconds=sorted(polls)[len(polls)//2],
            typed_tools_verified=True, real_socket_timer=True, fresh_process_reader=phase == "reader",
            native_transfers_interruptible=False, constrained_memory_acceptance=False,
            project_saved_separately=phase == "writer", automatic_external_reload=False,
            reviewed_visual_acceptance=False, release_readiness="NOT_ASSESSED")
    except Exception:
        RESULT["failure"] = traceback.format_exc()
    finally:
        client.close()
        DONE.set()


class Layout:
    """An unbound native panel draw catches workload-key errors, not appearance."""
    def __init__(self):
        self.labels = []
    def __getattr__(self, name):
        def draw(*args, **kwargs):
            if name == "label":
                self.labels.append(kwargs.get("text", ""))
            return self
        return draw


def provider_faults(runtime, domain, storage):
    """Actual native write boundaries with the worker's pure lifetime check.

    The driver boundary is invoked directly for deterministic fault placement;
    separate socket jobs below verify scheduler checkpoints and handoff.
    """
    from blender_codex_bridge.errors import BridgeError
    from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime
    results = []
    values = array("f", [-0., -.125, 65536., -2., .1234567, 2., 4., 2.])
    payload = b"".join(step.data for step in domain.pixel_codecs.encode_steps(values, 2, 1, "EXR32_RAW", "DATA"))
    for operation in ("snapshot_allocate", "snapshot_metadata", "restore_loaded", "restore_unloaded"):
        for fault in ("cancel", "disconnect", "deadline", "toolset"):
            name = operation + " " + fault
            original = bpy.data.images.new("Fault Original " + name, 2, 1, alpha=True, float_buffer=True)
            original.colorspace_settings.name, original.alpha_mode = "Non-Color", "CHANNEL_PACKED"
            original.pixels.foreach_set(values)
            original.update()
            if operation == "restore_unloaded":
                original.source, original.filepath = "FILE", ""
                original.pack(data=payload, data_len=len(payload))
                tuple(original.size)
            lifetime = RequestLifetime(ConnectionLifetime())
            lifetime.acknowledge(True)
            context = runtime.executor.context
            context.request_lifecycle = lifetime
            snapshot_name = "Fault Snapshot " + name
            if operation.startswith("restore"):
                storage.pack_version(context, {"image_name": original.name, "new_name": snapshot_name, "mode": "CURRENT_PIXELS"})
                if operation == "restore_unloaded":
                    original.buffers_free()
                else:
                    original.pixels.foreach_set(array("f", [1.])*8)
                    original.update()
                inspected = domain.recovery_job_preview(context, {"image_name": original.name, "snapshot_name": snapshot_name})
                domain.restore_snapshot_job_start(context, {"image_name": original.name, "snapshot_name": snapshot_name,
                    "expected_target_fingerprint": inspected["expected_target_fingerprint"], "confirm_replace_packed_bytes": True})
            else:
                domain.snapshot_job_start(context, {"image_name": original.name, "new_name": snapshot_name})
            job = runtime.jobs.active
            job.in_commit = True
            worker = runtime.jobs._context(job)
            source_provider = runtime.permissions._source
            measured = []
            def measure(measured=measured, source_provider=source_provider):
                measured.append(True)
                return source_provider()
            runtime.permissions._source = measure
            try:
                domain._gate(worker, original)
            finally:
                runtime.permissions._source = source_provider
            calls, injected = [], []
            before_pixels = digest(pixels(original)) if original.has_data else None
            before_packed = hashlib.sha256(bytes(original.packed_file.data)).hexdigest() if original.packed_file else None
            native_identity, driver = original.as_pointer(), job.driver
            def provider(source_provider=source_provider, operation=operation, driver=driver,
                         calls=calls, measured=measured, fault=fault, job=job, lifetime=lifetime, injected=injected):
                grants = source_provider()
                if operation != "snapshot_metadata" or driver.output is not None:
                    calls.append(True)
                    if len(calls) == len(measured):
                        if fault == "cancel":
                            job.cancel_reason = "Final native provider fault"
                        elif fault == "disconnect":
                            lifetime.connection.disconnected.set()
                        elif fault == "deadline":
                            job.deadline = 0
                        else:
                            runtime.registry.disable_toolset("materials")
                        injected.append(True)
                return grants
            runtime.permissions._source = provider
            caught = None
            try:
                if operation.startswith("snapshot"):
                    driver._publish(worker, job, payload, digest(values))
                else:
                    driver._publish(worker, job, values, payload)
            except BridgeError as error:
                caught = error
                assert injected == [True]
                assert error.code == ("TOOLSET_DISABLED" if fault == "toolset" else "TIMEOUT"), error
                assert original.as_pointer() == native_identity
                assert (hashlib.sha256(bytes(original.packed_file.data)).hexdigest() if original.packed_file else None) == before_packed
                assert (digest(pixels(original)) if original.has_data else None) == before_pixels
                if operation == "snapshot_metadata":
                    output = bpy.data.images[snapshot_name]
                    assert output.source == "GENERATED" and output.filepath == "" and output.packed_file is None
                    assert storage.METADATA_KEY not in output and storage.OWNER_KEY not in output
                elif operation == "snapshot_allocate":
                    assert bpy.data.images.get(snapshot_name) is None
                results.append({"operation": operation, "fault": fault, "next_native_write_blocked": True})
            finally:
                runtime.permissions._source = source_provider
                runtime.registry.enable_toolset("materials")
                job.in_commit = False
                runtime.jobs._finish(job, "CANCELLED", caught)
            assert caught is not None, "Provider fault unexpectedly allowed native publication"
    return results


def run(*, large=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    bundle, phase = args.bridge_bundle.resolve(strict=True), args.bridge_phase
    prefix = "BLENDER_IMAGE_RECOVERY_JOBS" + ("_LARGE" if large else "")
    opened = []
    def setup():
        try:
            assert not bpy.app.background
            headroom = linux_available_memory() if sys.platform == "linux" else None
            if large:
                assert headroom is not None and headroom >= 8*1024**3, "4K fixture requires measured 8 GiB headroom"
            if phase == "reader" and not opened:
                opened.append(True)
                bpy.ops.wm.open_mainfile(filepath=str(bundle/"image-recovery-jobs.blend"), load_ui=False, use_scripts=False)
                # The old timer's context is invalid until the UI event loop
                # returns from file loading. Inspect only in a new timer turn.
                bpy.app.timers.register(setup, first_interval=1.)
                return None
            bpy.context.preferences.use_preferences_save = False
            bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
            from blender_codex_bridge import pixel_codecs, ui
            from blender_codex_bridge.preferences import get_preferences
            from blender_codex_bridge.runtime import get_runtime
            from blender_codex_bridge.tools import image_portability as storage
            from blender_codex_bridge.tools import image_recovery_jobs as domain
            runtime, prefs = get_runtime(), get_preferences()
            prefs.allow_execute_python = prefs.allow_delete_objects = False
            prefs.allow_external_files = prefs.allow_save_project = prefs.allow_edit_materials = True
            prefs.paint_job_budget_ms = 4 if large else 1
            runtime.registry.enable_toolset("materials")
            rows, native_calls = [], []
            width = 4096 if large else 256
            pattern = array("f", [-0., -.125, 65536., -2., .1234567, 2., 4., 2., .5, .25, .75, 0., 1., 2., 3., 1.])
            def protect(image):
                material = bpy.data.materials.new("Protected " + image.name)
                material.use_nodes = material.use_fake_user = True
                node = material.node_tree.nodes.new("ShaderNodeTexImage")
                node.image = image
                return {"material": material.name, "node": node.name}
            if phase == "writer":
                values = pattern * (width*width//4)
                image = bpy.data.images.new("Original Data", width, width, alpha=True, float_buffer=True)
                image.colorspace_settings.name, image.alpha_mode = "Non-Color", "CHANNEL_PACKED"
                image.pixels.foreach_set(values)
                image.update()
                rows.append({"name": image.name, "snapshot": "Retained Data", "digest": digest(values), "owner": protect(image)})
                del values
                if not large:
                    cases = [(False, space, alpha) for space in ("sRGB", "Linear Rec.709", "Non-Color")
                        for alpha in ("STRAIGHT", "CHANNEL_PACKED")]
                    cases += [(True, "Non-Color", "STRAIGHT"), (True, "Non-Color", "CHANNEL_PACKED"), (True, "Linear Rec.709", "CHANNEL_PACKED")]
                    folder = bundle/"missing-sources"
                    folder.mkdir()
                    prefs.texture_directory = str(folder)
                    for index, (floating, space, alpha) in enumerate(cases):
                        initial = array("f", [.1, .2, .3, 1.]) * 256
                        payload = b"".join(step.data for step in pixel_codecs.encode_steps(initial, 16, 16,
                            "EXR32_RAW" if floating else "PNG8", "DATA"))
                        path = folder/(str(index) + (".exr" if floating else ".png"))
                        path.write_bytes(payload)
                        image = bpy.data.images.load(str(path), check_existing=False)
                        image.name = "Role Original " + str(index)
                        image.colorspace_settings.name, image.alpha_mode = space, alpha
                        edited = pattern * 64 if floating else array("f", (channel/255 for i in range(256)
                            for channel in (i, 255-i, i*37%256, i*73%256)))
                        image.pixels.foreach_set(edited)
                        image.update()
                        path.unlink()
                        rows.append({"name": image.name, "snapshot": "Role Snapshot " + str(index),
                            "digest": digest(pixels(image)), "owner": protect(image), "colorspace": space,
                            "alpha_mode": alpha, "is_float": floating})
                bpy.data.objects["Cube"].name = "Manual Protected Cube"
                if not large:
                    RESULT["final_provider_native_boundary_faults"] = provider_faults(runtime, domain, storage)
            else:
                rows = json.loads((bundle/"image-recovery-jobs-manifest.json").read_text())["rows"]
                for row in rows:
                    assert bpy.data.images[row["snapshot"]][storage.OWNER_KEY] == bpy.data.images[row["name"]]
                    assert bpy.data.images[row["snapshot"]].filepath == ""
            identities = {row["name"]: bpy.data.images[row["name"]].as_pointer() for row in rows}
            selection = sorted(obj.name for obj in bpy.context.selected_objects)
            active = bpy.context.view_layer.objects.active.name
            original_publish = domain.SnapshotDriver._publish
            original_restore = domain.RestoreDriver._publish
            original_gate, late_restore = domain._gate, []
            def gate(context, image=None, *, modifying=True):
                if (late_restore and image is bpy.data.images.get(rows[0]["name"]) and image.has_data
                        and digest(pixels(image)) == rows[0]["digest"]):
                    prefs.allow_edit_materials = False
                    late_restore.clear()
                return original_gate(context, image, modifying=modifying)
            domain._gate = gate
            def timed(original):
                def publish(self, *args):
                    stamp = time.perf_counter()
                    try:
                        return original(self, *args)
                    finally:
                        native_calls.append({"operation": type(self).__name__, "native_publication_seconds": time.perf_counter()-stamp})
                return publish
            domain.SnapshotDriver._publish, domain.RestoreDriver._publish = timed(original_publish), timed(original_restore)
            def verify(row):
                original, snapshot = bpy.data.images[row["name"]], bpy.data.images[row["snapshot"]]
                assert original.as_pointer() == identities[row["name"]]
                assert snapshot[storage.OWNER_KEY] == original and snapshot.packed_file is not None
                assert digest(pixels(original)) == row["digest"] and digest(pixels(snapshot)) == row["digest"]
                owner = row["owner"]
                assert bpy.data.materials[owner["material"]].node_tree.nodes[owner["node"]].image == original
                if "colorspace" in row:
                    assert (original.colorspace_settings.name, original.alpha_mode, bool(original.is_float)) == (row["colorspace"], row["alpha_mode"], row["is_float"])
                return True
            def apply(action, params):
                if action in {"pause", "resume"}:
                    runtime.state.set_paused(action == "pause")
                elif action in {"deny", "allow"}:
                    prefs.allow_edit_materials = action == "allow"
                elif action in {"stale", "unstale"}:
                    image = bpy.data.images[rows[0]["name"]]
                    values = pixels(image)
                    values[0] = 1. if action == "stale" else -0.
                    image.pixels.foreach_set(values)
                    image.update()
                elif action == "manual_transform":
                    bpy.data.objects["Manual Protected Cube"].location.z = .375
                elif action == "verify_undo":
                    assert bpy.data.images.get(rows[0]["snapshot"]) is None
                    assert abs(bpy.data.objects["Manual Protected Cube"].location.z - .375) < 1e-6
                    for row in rows:
                        original = bpy.data.images[row["name"]]
                        assert digest(pixels(original)) == row["digest"]
                        owner = row["owner"]
                        assert bpy.data.materials[owner["material"]].node_tree.nodes[owner["node"]].image == original
                        identities[row["name"]] = original.as_pointer()
                    RESULT["manual_transform_preserved_by_snapshot_creation_undo"] = True
                elif action == "arm_late_restore":
                    late_restore.append(True)
                elif action == "disarm_late_restore":
                    assert not late_restore and not prefs.allow_edit_materials
                    prefs.allow_edit_materials = True
                    RESULT["post_write_revocation_retained_snapshot_and_actual_pixels"] = True
                elif action == "panel":
                    layout = Layout()
                    ui.BCB_PT_bridge_panel.draw(SimpleNamespace(layout=layout), bpy.context)
                    assert any("pixels/payload estimate" in label for label in layout.labels), layout.labels
                    RESULT["native_panel_draw_recovery_workload"] = True
                    original_list = runtime.jobs.list
                    retained = original_list(limit=1)
                    retained["jobs"][0]["recovery_evidence"] = {"snapshot_retained": True}
                    retained["jobs"][0]["evidence_observation_unknown"] = ["recovery_evidence"]
                    try:
                        runtime.jobs.list = lambda limit=3: retained
                        unknown_layout = Layout()
                        ui.BCB_PT_bridge_panel.draw(SimpleNamespace(layout=unknown_layout), bpy.context)
                        assert any("could not be observed" in label for label in unknown_layout.labels)
                        assert not any("Packed snapshot retained" in label for label in unknown_layout.labels)
                        RESULT["native_panel_unknown_recovery_hides_stale_retention"] = True
                    finally:
                        runtime.jobs.list = original_list
                elif action == "change":
                    image = bpy.data.images[params["row"]["name"]]
                    values = array("f", [1.]) * len(image.pixels)
                    image.pixels.foreach_set(values)
                    image.update()
                elif action == "unload":
                    image = bpy.data.images[params["row"]["name"]]
                    image.buffers_free()
                    assert not image.has_data
                elif action == "verify":
                    return verify(params["row"])
                elif action == "allocate_generated":
                    image = bpy.data.images[rows[0]["name"]]
                    assert image.source == "GENERATED"
                    assert digest(pixels(image)) != rows[0]["digest"]
                elif action == "manifest":
                    (bundle/"image-recovery-jobs-manifest.json").write_text(json.dumps({"rows": rows}, indent=2)+"\n")
                elif action == "final":
                    assert runtime.jobs.active is None
                    assert all(not job.prepared and job.work is None and job.driver is None for job in runtime.jobs.history)
                    assert all(bpy.data.images.get(name) is None for name in ("Cancelled Snapshot", "Disconnected Snapshot", "Expired Snapshot", "Denied Snapshot", "Stale Snapshot"))
                    assert abs(bpy.data.objects["Manual Protected Cube"].location.z - .375) < 1e-6
                    assert sorted(obj.name for obj in bpy.context.selected_objects) == selection
                    assert bpy.context.view_layer.objects.active.name == active and bpy.context.mode == "OBJECT"
                    assert not prefs.allow_execute_python and not prefs.allow_delete_objects
                    for row in rows:
                        verify(row)
                else:
                    raise AssertionError(action)
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            runtime.start_server("127.0.0.1", port, request_timeout=90)
            stamp = time.monotonic()
            def supervise():
                while not CONTROLS.empty():
                    action, params, event, result = CONTROLS.get_nowait()
                    try:
                        value = apply(action, params)
                        result.extend((True, value))
                    except Exception:
                        result.extend((False, traceback.format_exc()))
                    finally:
                        event.set()
                if not DONE.is_set() and time.monotonic()-stamp < 1200:
                    return .005
                try:
                    assert DONE.is_set(), "Native fixture deadline expired"
                    assert "failure" not in RESULT, RESULT.get("failure")
                    runtime.stop_server()
                    RESULT.update(phase=phase, blender_version=bpy.app.version_string, image_size=[width, width],
                        process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid(),
                        native_publications=native_calls, available_bytes_before_allocation=headroom,
                        memory=linux_process_memory() if sys.platform == "linux" else {"supported": False},
                        machine=platform.machine(), processor=platform.processor(), scheduler_budget_ms=prefs.paint_job_budget_ms,
                        cpu_model=(next((line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                            if line.startswith("model name")), None) if sys.platform == "linux" else platform.processor()),
                        preservation_scope="Exact native Image IDs, complete channels, declared roles and direct material consumers; not arbitrary transitive dependencies")
                    (bundle/("image-recovery-jobs-"+phase+".json")).write_text(json.dumps(RESULT, indent=2)+"\n")
                    print(prefix+"_"+phase.upper()+"_OK "+json.dumps(RESULT), flush=True)
                except Exception:
                    traceback.print_exc()
                finally:
                    domain.SnapshotDriver._publish, domain.RestoreDriver._publish = original_publish, original_restore
                    domain._gate = original_gate
                    runtime.emergency_stop()
                    bpy.ops.wm.quit_blender()
                return None
            bpy.app.timers.register(supervise, first_interval=.005)
            threading.Thread(target=scenario, args=(port, phase, bundle, rows, large), name="RecoveryJobSocketFixture", daemon=True).start()
        except Exception:
            traceback.print_exc()
            bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(setup, first_interval=1.)


if __name__ == "__main__":
    run()
