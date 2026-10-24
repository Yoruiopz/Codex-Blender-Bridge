"""Public rigid-evaluation jobs; opt in through the isolated native runner.

Raw scene creation/reference/reset actions belong to this disposable fixture and
run only without a Scene owner. The worker handles JSON/TCP and plain controls;
all Blender access stays on the main thread. This does not save or bake a project.
Importing this module starts no timer, thread, server or add-on registration.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import socket
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW, START = "rigid_body.evaluate_preview", "rigid_body.evaluate_job_start"
FRAMES, CALLER_TIME, TOLERANCE = (5, 6, 7), (9, .375), 1.e-6
SOURCE_COMMITS = {
    (4, 5, 14): "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
    (5, 2, 2): "d13f752e3b9c4f8c261cda552b1021f8bcc0382c",
}
CASES = ("moving", "zero_motion", *(f"{reason}_{stage}"
    for stage in ("early", "late") for reason in ("cancel", "permission", "disconnect", "external_edit")))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def detached(value):
    return json.loads(json.dumps(value, allow_nan=False))


def persist(name, value):
    path = Path(tempfile.gettempdir()) / name
    raw = (json.dumps(value, indent=2, allow_nan=False)+"\n").encode()
    temporary = path.with_suffix(path.suffix+".next")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return {"evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest()}


class Client:
    """No Blender access: only bounded fixture TCP requests and JSON results."""

    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.stream, self.sequence = self.socket.makefile("rb"), 0

    def request(self, method, **params):
        self.sequence += 1
        identifier = f"rigid_evaluation_{self.sequence}"
        self.socket.sendall((json.dumps({"id": identifier, "method": method, "params": params,
            "protocol_version": "1.0", "timeout_ms": 20000})+"\n").encode())
        response = json.loads(self.stream.readline())
        assert response["id"] == identifier, response
        return response

    def call(self, method, **params):
        response = self.request(method, **params)
        assert response["ok"], response
        return response["result"]

    def close(self):
        self.stream.close()
        self.socket.close()


class Fixture:
    def __init__(self, bpy, bridge, get_runtime, permission, manager, make_scene, context_state):
        self.bpy, self.bridge, self.get_runtime = bpy, bridge, get_runtime
        self.permission, self.manager = permission, manager
        self.make_scene, self.context_state = make_scene, context_state
        self.main_thread = threading.get_ident()
        self.controls, self.done, self.turn_done = queue.Queue(), threading.Event(), threading.Event()
        self.result = {}
        self.state = {"cases": {}, "ticks": [], "stamps": [], "pushes": [], "fixture_actions": [], "polls": []}
        self.current, self.tick_number = None, 0

    def main_thread_only(self):
        assert threading.get_ident() == self.main_thread

    def control(self, action, **params):
        event, result = threading.Event(), []
        self.controls.put((action, params, event, result))
        assert event.wait(30), ("Main-thread control timed out", action)
        assert result and result[0] is True, result
        return result[1]

    def metadata(self):
        return {"process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "source_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "blender_version": self.bpy.app.version_string, "native_build_hash": self.build,
            "cases": self.state["cases"], "project_saved": False, "bake_requested": False,
            "cache_coverage": "NOT_ASSESSED", "physical_correctness": "NOT_ASSESSED",
            "full_recovery_acceptance": False, "release_readiness": "NOT_ASSESSED"}

    def progress(self, observation):
        self.main_thread_only()
        # Main-thread state only; the worker can concurrently update result.
        persist("rigid-evaluation-jobs-progress.json", {"observation": observation,
            "process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "state": self.state, "terminal_success": False})

    def raw_sample(self, frame):
        self.main_thread_only()
        assert self.runtime.jobs.active is None, "Raw evaluation must not interleave a Scene owner"
        self.scene.frame_set(frame, subframe=0.)
        self.bpy.context.view_layer.update()
        graph = self.bpy.context.evaluated_depsgraph_get()
        matrices = {}
        for obj in self.bodies:
            values = [float(value) for line in obj.evaluated_get(graph).matrix_world for value in line]
            assert len(values) == 16 and all(math.isfinite(value) for value in values)
            matrices[obj.name] = values
        return {"frame": frame, "matrices": matrices}

    def prepare_case(self, case):
        self.main_thread_only()
        assert self.runtime.jobs.active is None
        self.grants[self.permission.EDIT_ANIMATION.value] = True
        self.runtime.state.set_paused(False)
        self.current = case
        self.scene.gravity = (0., 0., 0. if case == "zero_motion" else -9.81)
        self.bodies[0].location.x = 0.
        cache, world = self.scene.rigidbody_world.point_cache, self.scene.rigidbody_world
        # Explicit new fixture action; never stopped-driver cleanup or recovery.
        cache.frame_end, cache.frame_start = FRAMES[-1], FRAMES[0]
        world.time_scale = world.time_scale
        reference = [self.raw_sample(frame) for frame in FRAMES]
        active_names = [obj.name for obj in self.bodies[:2]]
        displacements = {name: reference[-1]["matrices"][name][11]-reference[0]["matrices"][name][11]
                         for name in active_names}
        if case == "zero_motion":
            assert all(abs(value) <= TOLERANCE for value in displacements.values()), displacements
        else:
            assert all(value < -TOLERANCE for value in displacements.values()), displacements
        initial_end = 250 if case == "moving" else 3
        cache.frame_start, cache.frame_end = 1, initial_end
        world.time_scale = world.time_scale
        self.scene.frame_set(CALLER_TIME[0], subframe=CALLER_TIME[1])
        self.bpy.context.view_layer.update()
        context = self.context_state()
        assert context["frame"] == CALLER_TIME[0] and context["subframe"] == CALLER_TIME[1]
        self.state["cases"][case] = {"reference": reference, "reference_sha256": digest(reference),
            "raw_active_z_displacements": displacements,
            "initial_context": context, "initial_range": [cache.frame_start, cache.frame_end],
            "driver": {"samples": [], "journal": []}}
        self.state["fixture_actions"].append({"case": case, "action": "fresh_raw_reference_and_reset",
            "old_owner_reused": False, "raw_evaluation_before_public_start": True,
            "reference_frames": list(FRAMES), "caller_time": list(CALLER_TIME),
            "range_reset": [1, initial_end], "gravity": list(self.scene.gravity)})
        self.progress("raw_reference_before_public_start_"+case)
        return {"scene_name": self.scene.name, "body_names": [obj.name for obj in self.bodies],
            "constraint_names": [], "frame_start": FRAMES[0], "frame_end": FRAMES[-1], "time_limit_seconds": 60}

    def copy_driver(self, driver):
        # Only retained Python values: no evaluated RNA reads during ownership.
        journal = [{"phase": plan.phase, "verified": row.verified, "sample_recorded": row.sample_recorded,
            "calls": [{"operation": call.operation, "body_name": call.body_name, "target": call.target,
                       "entered": bits.entered, "returned": bits.returned}
                      for call, bits in zip(plan.calls, row.calls, strict=True)]}
                   for plan, row in zip(driver.native_effects.plans, driver.native_effects.rows, strict=True)]
        return detached({"samples": driver.samples, "journal": journal,
                         "index": driver.index, "phase": driver.phase, "done": driver.done})

    def observe(self):
        self.main_thread_only()
        cache = self.scene.rigidbody_world.point_cache
        record = self.state["cases"][self.current]
        copied = record["driver"]
        pending = self.runtime.checkpoints._pending
        return {"driver": detached(copied), "context": self.context_state(),
            "range": [cache.frame_start, cache.frame_end], "baked": cache.is_baked,
            "body_a_x": float(self.bodies[0].location.x),
            "marker": self.scene.get("_codex_bridge_undo_marker"),
            "pending_marker": None if pending is None else pending.before_marker,
            "stamp_count": len(self.state["stamps"]), "push_count": len(self.state["pushes"]),
            "ledger": detached(self.runtime.jobs.recovery_ledger),
            "active_job_id": self.runtime.jobs.active.job_id if self.runtime.jobs.active else None}

    def apply(self, action, params):
        self.main_thread_only()
        if action == "prepare":
            return self.prepare_case(params["case"])
        if action == "resume":
            self.turn_done.clear()
            self.runtime.state.set_paused(False)
        elif action == "observe":
            return self.observe()
        elif action == "deny_animation":
            self.grants[self.permission.EDIT_ANIMATION.value] = False
        elif action == "allow_animation":
            self.grants[self.permission.EDIT_ANIMATION.value] = True
        elif action == "external_edit":
            self.bodies[0].location.x += .125
            self.state["fixture_actions"].append({"case": self.current,
                "action": "external_authored_edit_during_paused_owner", "body_a_x": float(self.bodies[0].location.x)})
        elif action == "record":
            assert self.runtime.jobs.active is None
            terminal = params["terminal"]
            record = self.state["cases"][self.current]
            record.update(terminal=terminal, final=self.observe())
            self.verify_case(self.current, record)
        elif action == "capacity_prepare":
            assert self.runtime.jobs.active is None and len(self.runtime.jobs.recovery_ledger) == 8
            self.runtime.state.set_paused(False)
            self.state["fixture_actions"].append({"action": "unpause_after_last_owner_for_capacity_refusal",
                                                   "old_owner_reused": False})
        elif action == "capacity_before":
            assert self.runtime.jobs.active is None and len(self.runtime.jobs.recovery_ledger) == 8
            return self.observe()
        elif action == "final":
            assert self.runtime.jobs.active is None and len(self.runtime.jobs.recovery_ledger) == 8
            assert set(self.state["cases"]) == set(CASES)
            assert all("terminal" in record for record in self.state["cases"].values())
            assert all(row["start_delivered"] for row in self.state["stamps"]+self.state["pushes"])
            assert all(row["start_delivered"] for row in self.state["ticks"]
                       if row["index_after"] > row["index_before"])
            self.state["retained_recovery_ledger"] = detached(self.runtime.jobs.recovery_ledger)
            self.state["pending_checkpoint_receipts"] = [self.runtime.checkpoints.pending_status(row.handle)
                for row in self.runtime.checkpoints._owned_pending.values()]
            abandoned = [row for row in self.state["pending_checkpoint_receipts"] if row["state"] == "ABANDONED"]
            assert len(abandoned) == 8
        else:
            raise AssertionError(action)
        return None

    def verify_case(self, case, record):
        terminal, final, driver = record["terminal"], record["final"], record["driver"]
        success = case in {"moving", "zero_motion"}
        checkpoint = terminal["checkpoint"]
        assert checkpoint["state"] == ("FINALIZED" if success else "ABANDONED"), checkpoint
        assert checkpoint["before_verified"] and checkpoint["after_verified"] is success
        assert checkpoint["native_snapshots_completed"] == (2 if success else 1)
        assert not checkpoint["durable_backup_created"] and not checkpoint["native_cache_recovery_guaranteed"]
        actual = terminal["native_effects"]
        assert actual["sealed"] and not actual["evidence_incomplete"] and not actual["snapshot_allocation_failed"]
        for operation, counts in actual["counts_by_operation"].items():
            calls = [call for phase in driver["journal"] for call in phase["calls"] if call["operation"] == operation]
            assert counts == {"entered": sum(call["entered"] for call in calls),
                              "returned": sum(call["returned"] for call in calls)}, (operation, counts, calls)
        assert actual["phases_verified"] == sum(row["verified"] for row in driver["journal"])
        assert actual["sample_recorded_count"] == len(driver["samples"])
        range_phases = ["set_frame_start", "set_frame_end"] if case == "moving" else ["set_frame_end", "set_frame_start"]
        expected_phases = [*range_phases, "reset_world",
            *(f"frame_{frame}_{operation}" for frame in FRAMES for operation in ("set", "update", "sample")),
            "restore_caller_frame", "restore_caller_update"]
        assert [row["phase"] for row in driver["journal"]] == expected_phases
        assert driver["journal"][0]["calls"][0]["target"] == ([5, 250] if case == "moving" else [1, 7])
        verified_prefix = 14 if success else (1 if case.endswith("early") else 9)
        for index, row in enumerate(driver["journal"]):
            expected_bit = index < verified_prefix
            assert row["verified"] is expected_bit
            assert row["sample_recorded"] is (expected_bit and row["phase"].endswith("_sample"))
            assert all(call["entered"] is expected_bit and call["returned"] is expected_bit for call in row["calls"])
        final_row = driver["journal"][verified_prefix-1]
        for key, call in (("last_entered", final_row["calls"][-1]),
                          ("last_returned", final_row["calls"][-1]), ("last_verified", final_row["calls"][0])):
            assert actual[key] == {"index": verified_prefix-1, "phase": final_row["phase"],
                "operation": call["operation"], "body_name": call["body_name"], "target": call["target"]}
        for key in ("active", "selected", "mode", "context_active", "context_object", "context_selected"):
            assert final["context"][key] == record["initial_context"][key], (case, key)
        assert not final["baked"]
        pushes = [row for row in self.state["pushes"] if row["job_id"] == terminal["job_id"]]
        assert len(pushes) == (2 if success else 1)
        if success:
            samples = driver["samples"]
            assert [row["frame"] for row in samples] == list(FRAMES)
            error = max(abs(value-other) for left, right in zip(samples, record["reference"], strict=True)
                        for name in left["matrices"]
                        for value, other in zip(left["matrices"][name], right["matrices"][name], strict=True))
            record["maximum_absolute_matrix_error"] = error
            assert error <= TOLERANCE, (case, error)
            result = terminal["result"]
            assert result["matrix_samples_sha256"] == digest(samples) == record["reference_sha256"]
            assert result["frames_sampled"] == 3 and result["matrices_sampled"] == 9
            assert result["all_requested_integer_frames_sampled"] and result["caller_time_restored"]
            assert result["active_selection_mode_preserved"] and result["proposed_cache_range_retained"]
            assert not result["baked"] and not result["bake_completed"] and not result["project_saved"]
            assert result["cache_coverage"] == result["physical_correctness"] == "NOT_ASSESSED"
            for endpoint in result["endpoints"]:
                name = endpoint["body_name"]
                assert endpoint["first_matrix"] == samples[0]["matrices"][name]
                assert endpoint["last_matrix"] == samples[-1]["matrices"][name]
                assert endpoint["displacement_xyz"] == [samples[-1]["matrices"][name][i]-samples[0]["matrices"][name][i]
                                                       for i in (3, 7, 11)]
            assert final["context"] == record["initial_context"]
            assert final["range"] == [5, 7]
            expected = {"cache_frame_start_set": 1, "cache_frame_end_set": 1, "world_reset": 1,
                "frame_set": 4, "view_layer_update": 4, "depsgraph_get": 3,
                "evaluated_get": 9, "matrix_capture": 9}
            assert actual["phases_verified"] == actual["phases_planned"] == 14
            assert actual["calls_planned"] == 32
        else:
            entered = [row for row in driver["journal"] if any(call["entered"] for call in row["calls"])]
            assert entered[-1]["phase"] == ("set_frame_end" if case.endswith("early") else "frame_6_sample")
            assert len(driver["samples"]) == (0 if case.endswith("early") else 2)
            assert not any(call["entered"] for row in driver["journal"] if row["phase"].startswith("restore_caller")
                           for call in row["calls"])
            ledger = self.runtime.jobs.recovery_ledger[terminal["job_id"]]
            assert ledger["checkpoint"] == checkpoint and ledger["summary"]["native_effects"] == actual
            early = case.endswith("early")
            expected = {"cache_frame_start_set": 0 if early else 1, "cache_frame_end_set": 1,
                "world_reset": 0 if early else 1, "frame_set": 0 if early else 2,
                "view_layer_update": 0 if early else 2, "depsgraph_get": 0 if early else 2,
                "evaluated_get": 0 if early else 6, "matrix_capture": 0 if early else 6}
            assert final["range"] == ([1, 7] if early else [5, 7])
            assert [final["context"]["frame"], final["context"]["subframe"]] == (list(CALLER_TIME) if early else [6, 0.])
        assert actual["counts_by_operation"] == {operation: {"entered": count, "returned": count}
                                                 for operation, count in expected.items()}

    def worker(self, port):
        client = Client(port)
        try:
            def inspect(identifier):
                value = client.call("jobs.inspect", job_id=identifier)
                self.result.setdefault("polls", []).append({"job_id": identifier, "state": value["state"],
                    "phase": value["phase"], "revision": value["revision"]})
                return value

            def terminal(identifier):
                deadline = time.monotonic()+25
                while time.monotonic() < deadline:
                    value = inspect(identifier)
                    if value["terminal"]:
                        return value
                    time.sleep(.01)
                raise AssertionError("Paused pure checks did not retire the stopped owner")

            last_params = None
            for case in CASES:
                params = self.control("prepare", case=case)
                preview = client.call(PREVIEW, **params)
                assert preview["bake_requested"] is False and preview["proposed_cache_range_retained"]
                accepted = client.call(START, **params, expected_fingerprint=preview["expected_fingerprint"])
                assert accepted["accepted"] and not accepted["terminal"]
                assert not accepted["checkpoint"]["before_verified"]
                assert all(counts == {"entered": 0, "returned": 0}
                           for counts in accepted["native_effects"]["counts_by_operation"].values())
                identifier = accepted["job_id"]
                self.result.setdefault("accepted", {})[case] = {"preview": preview, "start": accepted}
                value = inspect(identifier)
                while True:
                    observed = self.control("observe")
                    entered = [row["phase"] for row in observed["driver"]["journal"] if any(call["entered"] for call in row["calls"])]
                    target = "set_frame_end" if case.endswith("early") else "frame_6_sample"
                    if case in {"moving", "zero_motion"} and value["terminal"]:
                        assert value["state"] == "SUCCEEDED", value
                        break
                    if (case not in {"moving", "zero_motion"} and entered and entered[-1] == target
                            and any(row["phase"] == target and row["verified"] for row in observed["driver"]["journal"])):
                        break
                    assert not value["terminal"], value
                    self.control("resume")
                    assert self.turn_done.wait(10), "No actual main-thread runtime tick returned"
                    value = inspect(identifier)
                if case not in {"moving", "zero_motion"}:
                    before = self.control("observe")
                    reason = case.rsplit("_", 1)[0]
                    if reason == "cancel":
                        assert client.call("jobs.cancel", job_id=identifier)["cancel_requested"]
                    elif reason == "permission":
                        self.control("deny_animation")
                    elif reason == "disconnect":
                        client.close()
                        client = Client(port)
                    else:
                        self.control("external_edit")
                    # Stop checks may finish while paused: never await a new
                    # domain-turn signal from an already retired owner.
                    value = terminal(identifier)
                    code = {"cancel": "TIMEOUT", "permission": "PERMISSION_DENIED",
                            "disconnect": "TIMEOUT", "external_edit": "INVALID_ARGUMENT"}[reason]
                    assert value["error"]["code"] == code, value
                    if reason == "disconnect":
                        assert value["error"]["context"]["connection_disconnected"]
                    after = self.control("observe")
                    for key in ("driver", "context", "range", "marker", "stamp_count", "push_count"):
                        assert before[key] == after[key], (case, key, before, after)
                    assert after["body_a_x"] == before["body_a_x"]+(.125 if reason == "external_edit" else 0.)
                    self.control("allow_animation")
                    for _ in range(3):
                        assert inspect(identifier)["terminal"]
                        time.sleep(.015)
                    later = self.control("observe")
                    assert later == after, (case, after, later)
                    self.result.setdefault("stopped_comparisons", {})[case] = {"before": before, "after": after, "later": later}
                self.control("record", terminal=value)
                self.result.setdefault("terminals", {})[case] = value
                last_params = params
            self.control("capacity_prepare")
            before = self.control("capacity_before")
            preview = client.call(PREVIEW, **last_params)
            denied = client.request(START, **last_params, expected_fingerprint=preview["expected_fingerprint"])
            assert not denied["ok"] and denied["error"]["code"] == "OPERATION_FAILED", denied
            assert denied["error"]["context"]["reason"] == "SCENE_RECOVERY_LEDGER_FULL", denied
            status = client.call("bridge.status")
            cached = {}
            for case, previous in self.result["terminals"].items():
                if case in {"moving", "zero_motion"}:
                    continue
                value = inspect(previous["job_id"])
                assert value["terminal"] and value["checkpoint"] == previous["checkpoint"]
                assert value["native_effects"] == previous["native_effects"]
                cached[case] = value
            after = self.control("capacity_before")
            assert after == before, (before, after)
            self.result["capacity_refusal"] = {"response": denied, "before": before, "after": after,
                                              "status": status, "cached_stopped_inspection": cached}
            self.control("final")
        except Exception:
            self.result["failure"] = traceback.format_exc()
        finally:
            client.close()
            self.done.set()

    def setup(self):
        try:
            self.main_thread_only()
            bpy = self.bpy
            version, self.build = tuple(bpy.app.version), bpy.app.build_hash
            self.build = self.build.decode("ascii") if isinstance(self.build, bytes) else self.build
            assert version in SOURCE_COMMITS and self.build in {SOURCE_COMMITS[version], SOURCE_COMMITS[version][:12]}
            assert not bpy.app.background and os.environ.get("BRIDGE_TEST_PROCESS_TOKEN")
            bpy.context.preferences.use_preferences_save = False
            self.bridge.register()
            self.runtime = self.get_runtime()
            self.grants = {p.value: p not in {self.permission.EXECUTE_PYTHON,
                self.permission.ACCESS_EXTERNAL_FILES, self.permission.SAVE_PROJECT} for p in self.permission}
            self.runtime.permissions = self.runtime.executor.permissions = self.manager(lambda: dict(self.grants))
            self.runtime.registry.enable_toolset("simulation")
            self.scene, self.bodies, _sentinel = self.make_scene("Public Rigid Evaluation", (0., 0., -9.81))
            assert self.runtime.jobs.recovery_limit == 8
            assert self.runtime.registry.get(START).handler.__module__.endswith(".rigid_body_jobs")
            original_tick = self.runtime.jobs.tick
            original_stamp, original_snapshot = self.runtime.checkpoints._stamp, self.runtime.checkpoints._snapshot

            def stamp(blender, *, guard=None):
                job = self.runtime.jobs.active
                assert job is not None and job.lifetime.delivered.is_set()
                row = {"case": self.current, "job_id": job.job_id, "tick": self.tick_number,
                       "start_delivered": job.lifetime.delivered.is_set(), "returned": False}
                self.state["stamps"].append(row)
                value = original_stamp(blender, guard=guard)
                row["returned"] = True
                return value

            def snapshot(blender, label, *, guard=None):
                job = self.runtime.jobs.active
                assert job is not None and job.lifetime.delivered.is_set()
                row = {"case": self.current, "job_id": job.job_id, "tick": self.tick_number,
                       "label": label, "start_delivered": job.lifetime.delivered.is_set(), "returned": False}
                self.state["pushes"].append(row)
                value = original_snapshot(blender, label, guard=guard)
                row.update(returned=True, marker=value)
                return value

            def tick():
                self.main_thread_only()
                self.tick_number += 1
                job = self.runtime.jobs.active
                driver = job.driver if job is not None else None
                before = driver.index if driver is not None else 0
                phase = job.phase if job is not None else None
                try:
                    return original_tick()
                finally:
                    if driver is not None:
                        copied = self.copy_driver(driver)
                        self.state["cases"][self.current]["driver"] = copied
                        assert 0 <= copied["index"]-before <= 1
                        self.state["ticks"].append({"case": self.current, "tick": self.tick_number,
                            "job_id": job.job_id, "phase_before": phase, "index_before": before,
                            "index_after": copied["index"], "start_delivered": job.lifetime.delivered.is_set()})
                        if copied["index"] != before or job.phase != phase or self.runtime.jobs.active is None:
                            self.progress("runtime_tick_"+str(self.tick_number))
                    if self.runtime.jobs.active is not None:
                        self.runtime.state.set_paused(True)
                    self.turn_done.set()

            self.runtime.checkpoints._stamp, self.runtime.checkpoints._snapshot = stamp, snapshot
            self.runtime.jobs.tick = tick
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            self.runtime.start_server("127.0.0.1", port, request_timeout=30)
            self.started = time.monotonic()
            bpy.app.timers.register(self.supervise, first_interval=.005)
            threading.Thread(target=self.worker, args=(port,), name="RigidEvaluationSocketFixture", daemon=True).start()
        except Exception:
            self.fail("setup", traceback.format_exc())
        return None

    def fail(self, phase, failure):
        print(failure, file=sys.stderr, flush=True)
        receipt = persist("rigid-evaluation-jobs-failure.json", {"phase": phase, "traceback": failure,
            "process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "state": self.state, "worker": self.result, "terminal_success": False,
            "failure_path_native_cleanup_attempted": False})
        print("RIGID_EVALUATION_JOBS_FAILED " + json.dumps(receipt), flush=True)
        self.bpy.ops.wm.quit_blender()

    def supervise(self):
        try:
            self.main_thread_only()
            while not self.controls.empty():
                action, params, event, result = self.controls.get_nowait()
                try:
                    result.extend([True, self.apply(action, params)])
                except Exception:
                    result.append(traceback.format_exc())
                finally:
                    event.set()
            if not self.done.is_set() and time.monotonic()-self.started < 240:
                return .005
            assert self.done.is_set(), "Fixture deadline expired"
            assert "failure" not in self.result, self.result.get("failure")
            receipt = persist("rigid-evaluation-jobs-evidence.json", {**self.metadata(), **self.state,
                "socket_evidence": self.result, "terminal_success": True,
                "public_registered_starters": [PREVIEW, START], "main_thread_only_blender_access": True,
                "maximum_domain_phases_per_tick": 1, "stopped_native_restore_cleanup_performed": False})
            self.runtime.stop_server()
            print("BLENDER_RIGID_EVALUATION_JOBS_OK " + json.dumps({"blender_version": self.bpy.app.version_string,
                **receipt, "terminal_cases": len(CASES), "stopped_cases": 8,
                "public_registered_starters": [PREVIEW, START], "project_saved": False,
                "bake_completed": False, "release_readiness": "NOT_ASSESSED"}), flush=True)
            self.bpy.ops.wm.quit_blender()
        except Exception:
            self.fail("supervise", traceback.format_exc())
        return None


def main():
    import bpy

    sys.path[:0] = [str(ROOT), str(ROOT / "addon")]
    import blender_codex_bridge
    from blender_codex_bridge.permissions import Permission, PermissionManager
    from blender_codex_bridge.runtime import get_runtime

    from scripts.blender_rigid_lifecycle_probe_smoke import context_state, make_scene

    fixture = Fixture(bpy, blender_codex_bridge, get_runtime, Permission, PermissionManager, make_scene, context_state)
    bpy.app.timers.register(fixture.setup, first_interval=1.)


if __name__ == "__main__":
    main()
