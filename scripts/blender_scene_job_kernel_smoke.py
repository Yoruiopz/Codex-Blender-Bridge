"""Internal Scene job kernel integration; run through the isolated native runner.

The network worker owns JSON/TCP only. All Blender and fixture-control work runs
on the main thread. No public simulation job or project save is implemented.
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

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "addon")]

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.scene_job_reservations import TURN_METHOD  # noqa: E402
from blender_codex_bridge.tool_registry import check_final_mutation  # noqa: E402
from blender_codex_bridge.tools import _rigid_body_scope as scope  # noqa: E402
from blender_codex_bridge.tools import _scene_checkpoint_roles as roles  # noqa: E402
from blender_codex_bridge.tools import rigid_body  # noqa: E402

from scripts.blender_rigid_lifecycle_probe_smoke import context_state, make_scene  # noqa: E402

START = "fixture.scene_job_start"
INSPECT = "jobs.inspect"
FOREIGN = "fixture.scene_job_foreign"
EVALUATE = "fixture.scene_job_evaluate"
SOURCE_COMMITS = {
    (4, 5, 14): "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
    (5, 2, 2): "d13f752e3b9c4f8c261cda552b1021f8bcc0382c",
}
FRAMES, TOLERANCE = (1, 2, 3), 1.e-6
CONTROLS, DONE, RESULT = queue.Queue(), threading.Event(), {}
TURN_DONE = threading.Event()
STATE = {"phase_calls": [], "scheduler_turns": [], "polls": [], "cases": {},
         "scheduler_tick": 0, "inside_scheduler": False, "foreign_entries": 0,
         "evaluation_entries": 0, "done": False}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def persist(name, value):
    path = Path(tempfile.gettempdir()) / name
    raw = (json.dumps(value, indent=2, allow_nan=False)+"\n").encode()
    temporary = path.with_suffix(path.suffix+".next")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return {"evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest()}


def evidence():
    return {"process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "source_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "blender_version": bpy.app.version_string,
            "native_build_hash": STATE.get("native_build_hash"),
            "native_source_commit": SOURCE_COMMITS[tuple(bpy.app.version)],
            "phase_calls": STATE["phase_calls"], "scheduler_turns": STATE["scheduler_turns"],
            "readonly_polls": STATE["polls"], "cases": STATE["cases"],
            "foreign_handler_entries": STATE["foreign_entries"],
            "evaluation_handler_entries": STATE["evaluation_entries"],
            "project_saved": False, "cache_durability_verified": False,
            "public_rigid_job_implemented": False, "full_recovery_acceptance": False,
            "release_readiness": "NOT_ASSESSED"}


class Client:
    """Socket and JSON access only; this class never accesses Blender state."""

    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.stream, self.sequence = self.socket.makefile("rb"), 0

    def request(self, method, **params):
        self.sequence += 1
        identifier = f"scene_kernel_{self.sequence}"
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


def control(action, **params):
    event, result = threading.Event(), []
    CONTROLS.put((action, params, event, result))
    assert event.wait(30), ("Main-thread fixture control timed out", action)
    assert result and result[0] is True, result
    return result[1] if len(result) > 1 else None


def stable_context(value):
    return {key: item for key, item in value.items() if key not in {"frame", "subframe"}}


def falling_motion(rows, names):
    matrices = {row["frame"]: row["matrices"] for row in rows}
    assert set(matrices) == set(FRAMES)
    displacement = {name: matrices[3][name][11]-matrices[1][name][11] for name in names[:2]}
    assert all(value < -TOLERANCE for value in displacement.values()), displacement
    return displacement


class FixtureBoundary(rigid_body._Boundary):
    """Existing rigid CAS with the kernel's actual internal turn authority."""

    def _authority(self):
        self.context.require(*rigid_body.PERMISSIONS)
        self._final()

    def _final(self):
        check_final_mutation(self.context, TURN_METHOD)


class RigidDriver:
    """Fixture-only whole-world evaluation; no bake or cache-coverage claim."""

    kind = "fixture.rigid_scene_evaluation"
    required_permissions = rigid_body.PERMISSIONS

    def __init__(self, context, params):
        assert set(params) == {"case"} and params["case"] in {"complete", "cancel", "permission", "disconnect", "external_edit"}
        self.case, self.label = params["case"], "Owned Scene kernel " + params["case"]
        self.scene = bpy.context.scene
        self.params = STATE["rigid_params"]
        self.initial_context = context_state()
        frozen = scope.snapshot(bpy, self.scene, self.params)
        self.roles = roles.Plan(bpy, self.scene)
        self.authored_roles = self.roles.authored()
        self.boundary = FixtureBoundary(bpy, context, self.scene, self.params, frozen)
        self.samples, self.phase, self.done, self.result = [], "reset", False, None
        self.operations = [("reset", self.boundary.reset)]
        for frame in FRAMES:
            self.operations.extend((
                (f"frame_{frame}_set", lambda frame=frame: self.set_frame(frame, 0.)),
                (f"frame_{frame}_update", self.update),
                (f"frame_{frame}_sample", lambda frame=frame: self.sample(frame)),
            ))
        self.operations.extend((
            ("restore_caller_frame", lambda: self.set_frame(self.initial_context["frame"], self.initial_context["subframe"])),
            ("restore_caller_update", self.update),
            ("verify_complete", self.verify_complete),
        ))
        self.index = 0
        STATE["cases"][self.case] = {"initial_context": self.initial_context,
            "initial_scope_sha256": digest(frozen), "samples": self.samples,
            "native_intervals": self.boundary.timings,
            "driver_done": False, "native_cleanup_attempted": False,
            "automatic_stopped_context_restore_attempted": False}
        STATE["drivers"][self.case] = self

    def check_after_read(self, context):
        self.boundary.context = context
        self.roles.check_after_read()
        assert self.roles.authored() == self.authored_roles
        scene = scope.current_scene(bpy, self.params["scene_name"])
        if scene != self.scene or scope.snapshot(bpy, scene, self.params) != self.boundary.expected:
            raise BridgeError("INVALID_ARGUMENT", "Fixture rigid authored scope changed; partial effects are retained.",
                              {"scope_complete": False})

    def native_push_delegates(self):
        return (self.roles,)

    def after_native_push(self):
        self.roles.after_native_push()

    def set_frame(self, frame, subframe):
        self.boundary.check()
        expected = {**self.boundary.expected["owned"], "frame": (frame, subframe)}
        setter = self.scene.frame_set
        self.boundary._native_interval("scene_frame_set", lambda: setter(frame, subframe=subframe))
        self.boundary.started = True
        self.boundary._accept(expected)

    def update(self):
        self.boundary.check()
        update = bpy.context.view_layer.update
        self.boundary._native_interval("view_layer_update", update)
        self.boundary._accept(self.boundary.expected["owned"])

    def sample(self, frame):
        self.boundary.check()
        graph_getter = bpy.context.evaluated_depsgraph_get
        graph = self.boundary._native_interval("evaluated_depsgraph_get", graph_getter)
        matrices = {}
        for name in self.boundary.expected["body_names"]:
            obj = bpy.data.objects[name]
            self.boundary._final()
            values = [float(value) for row in obj.evaluated_get(graph).matrix_world for value in row]
            self.boundary._final()
            assert len(values) == 16 and all(math.isfinite(value) for value in values)
            matrices[name] = values
        self.boundary._accept(self.boundary.expected["owned"])
        self.samples.append({"frame": frame, "matrices": matrices})

    def verify_complete(self):
        self.boundary.check()
        assert context_state() == self.initial_context
        error = rigid_body._difference(STATE["reference"], self.samples)
        motion = falling_motion(self.samples, self.params["body_names"])
        assert error <= TOLERANCE, error
        self.result = {"complete_matrices_compared": True, "maximum_matrix_error": error,
            "active_body_z_displacement": motion, "caller_context": context_state(),
            "cache_contents_hashed": False, "bake_completed": False}
        STATE["cases"][self.case].update(driver_done=True, result=self.result)

    def advance(self, context):
        self.boundary.context = context
        assert STATE["inside_scheduler"], "A Scene phase ran outside the runtime job tick"
        self.check_after_read(context)
        check_final_mutation(context, TURN_METHOD)
        phase, callback = self.operations[self.index]
        self.phase = phase
        row = {"case": self.case, "phase": phase, "scheduler_tick": STATE["scheduler_tick"],
               "start_response_delivered": context.request_lifecycle.delivered.is_set(),
               "native_intervals_before": len(self.boundary.timings)}
        STATE["phase_calls"].append(row)
        assert row["start_response_delivered"], row
        started = time.perf_counter()
        try:
            callback()
        finally:
            row.update(seconds=time.perf_counter()-started, native_intervals_after=len(self.boundary.timings))
        self.index += 1
        self.done = self.index == len(self.operations)
        self.phase = "complete" if self.done else self.operations[self.index][0]
        return {"phase": phase, "completed": self.index, "total": len(self.operations)}


def scenario(port):
    """Real TCP start/ACK/control flow; no Blender/runtime calls on this thread."""
    client, outcomes = Client(port), {}
    try:
        def inspect(identifier):
            started = time.perf_counter()
            value = client.call(INSPECT, job_id=identifier)
            RESULT.setdefault("socket_polls", []).append({"job_id": identifier,
                "seconds": time.perf_counter()-started, "state": value["state"],
                "revision": value["revision"]})
            client.call("bridge.status")
            return value

        def step(identifier):
            control("resume")
            assert TURN_DONE.wait(10), "An actual runtime job tick did not return"
            return inspect(identifier)

        def wait_terminal(identifier):
            limit = time.monotonic()+20
            while time.monotonic() < limit:
                value = inspect(identifier)
                if value["terminal"]:
                    return value
                time.sleep(.01)
            raise AssertionError("Stopped Scene owner never reached a terminal record")

        for case in ("complete", "cancel", "permission", "disconnect", "external_edit"):
            control("prepare_case", case=case)
            accepted = client.call(START, case=case)
            assert accepted["accepted"] and not accepted.get("terminal", False), accepted
            identifier = accepted["job_id"]
            value = inspect(identifier)
            for method in (FOREIGN, EVALUATE):
                response = client.request(method)
                assert not response["ok"], response
                error = response["error"]
                assert error["code"] == "OPERATION_FAILED", error
                assert error["context"]["reason"] == "SCENE_JOB_RESERVATION_BLOCKED", error
                RESULT.setdefault("entry_refusals", []).append({"case": case, "method": method, "error": error})
            while True:
                observation = control("observe", case=case)
                if case == "complete" and value["terminal"]:
                    break
                if case != "complete" and observation["last_domain_phase"] == "frame_2_set":
                    break
                assert not value["terminal"], value
                value = step(identifier)
            if case == "complete":
                assert value["state"] == "SUCCEEDED", value
            else:
                before = control("observe", case=case)
                if case == "cancel":
                    assert client.call("jobs.cancel", job_id=identifier)["cancel_requested"]
                elif case == "permission":
                    control("deny_animation")
                elif case == "disconnect":
                    client.close()
                    client = Client(port)
                else:
                    control("external_edit")
                # Pure paused preflight can retire any stopped owner before a
                # resume request. Poll its cached terminal receipt; an already
                # retired job has no later runtime tick to signal TURN_DONE.
                value = wait_terminal(identifier)
                assert value["terminal"] and value["state"] in {"CANCELLED", "FAILED"}, value
                expected_code = {"cancel": "TIMEOUT", "permission": "PERMISSION_DENIED",
                    "disconnect": "TIMEOUT", "external_edit": "INVALID_ARGUMENT"}[case]
                assert value["error"]["code"] == expected_code, value
                if case == "disconnect":
                    assert value["error"]["context"]["connection_disconnected"], value
                after = control("observe", case=case)
                assert after["domain_phase_count"] == before["domain_phase_count"], (before, after)
                assert after["native_call_count"] == before["native_call_count"], (before, after)
                assert after["undo_push_count"] == before["undo_push_count"], (before, after)
                assert after["checkpoint_stamp_count"] == before["checkpoint_stamp_count"], (before, after)
                assert after["scene_marker"] == before["scene_marker"], (before, after)
                assert after["frame"] == before["frame"] == [2, 0.], (before, after)
                assert after["caller_context_restored"] is False, after
                if case == "external_edit":
                    assert abs(after["body_a_x"]-before["body_a_x"]-.125) < TOLERANCE, (before, after)
                control("allow_animation")
                # Continue polling after termination to detect a deferred tail.
                for _ in range(3):
                    assert inspect(identifier)["terminal"]
                    time.sleep(.015)
                later = control("observe", case=case)
                for key in ("domain_phase_count", "native_call_count", "undo_push_count",
                            "checkpoint_stamp_count", "scene_marker", "frame", "body_a_x"):
                    assert later[key] == after[key], (key, after, later)
            outcomes[case] = value
            control("record_terminal", case=case, terminal=value)
        control("final_verify")
        RESULT["terminal_outcomes"] = outcomes
    except Exception:
        RESULT["failure"] = traceback.format_exc()
    finally:
        client.close()
        DONE.set()


def setup():
    try:
        version, build = tuple(bpy.app.version), bpy.app.build_hash
        build = build.decode("ascii") if isinstance(build, bytes) else build
        assert version in SOURCE_COMMITS and build in {SOURCE_COMMITS[version], SOURCE_COMMITS[version][:12]}
        STATE["native_build_hash"] = build
        assert not bpy.app.background and os.environ.get("BRIDGE_TEST_PROCESS_TOKEN")
        bpy.context.preferences.use_preferences_save = False
        blender_codex_bridge.register()
        from blender_codex_bridge import scene_jobs
        from blender_codex_bridge.scene_job_reservations import TURN_METHOD
        assert TURN_METHOD == "jobs._scene_turn"
        runtime = get_runtime()
        assert isinstance(runtime.jobs, scene_jobs.SceneJobs)
        STATE.update(runtime=runtime, drivers={}, undo_pushes=[], checkpoint_stamps=[], fixture_actions=[])
        grants = {permission.value: permission not in {
            Permission.EXECUTE_PYTHON, Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT,
        } for permission in Permission}
        provider_counts = {FOREIGN: 0, EVALUATE: 0}

        def provider():
            entries = runtime.registry._mutation_interlock._entries
            method = entries[-1].spec.name if entries else None
            if method in provider_counts:
                provider_counts[method] += 1
            return dict(grants)

        runtime.permissions = runtime.executor.permissions = PermissionManager(provider)
        runtime.registry.enable_toolset("simulation")
        scene, bodies, _sentinel = make_scene("Owned Scene Kernel World", (0., 0., -9.81))
        scene.frame_set(7, subframe=.25)
        initial_context = context_state()
        rigid_params = {"scene_name": scene.name, "body_names": [body.name for body in bodies],
            "constraint_names": [], "frame_start": 1, "frame_end": 3}
        STATE["rigid_params"] = rigid_params
        from scripts.blender_rigid_timer_probe_smoke import checkpointed_cache
        control_result = checkpointed_cache(runtime, rigid_params, "BAKE")
        STATE["reference"] = control_result["motion"]["samples"]
        falling_motion(STATE["reference"], rigid_params["body_names"])
        checkpointed_cache(runtime, rigid_params, "FREE")
        assert context_state() == initial_context
        STATE["typed_native_control"] = control_result

        def start_handler(context, params):
            before = context_state()
            marker = scene.get("_codex_bridge_undo_marker")
            stamps = len(STATE["checkpoint_stamps"])
            assert context.request_lifecycle is not None and not context.request_lifecycle.delivered.is_set()
            result = context.jobs.start_scene(context, params, time_limit=60.)
            assert context_state() == before and scene.get("_codex_bridge_undo_marker") == marker
            assert len(STATE["checkpoint_stamps"]) == stamps
            STATE["cases"][params["case"]]["acceptance"] = {
                "delivered_before_handler_return": context.request_lifecycle.delivered.is_set(),
                "scene_and_checkpoint_unchanged": True, "response": result}
            return result

        runtime.registry.register(START, start_handler, toolset="core", modifies=True,
            permissions=rigid_body.PERMISSIONS, automatic_checkpoint=False, batchable=False,
            exclusive_mutation=True, checkpoint_owns_finalization=True,
            checkpoint_admission_factory=scene_jobs.start_admission(lambda context, params: RigidDriver(context, params)))

        def foreign(context, _params):
            STATE["foreign_entries"] += 1
            scene.gravity.x += .125
            return {"changed": True}

        def evaluate(context, _params):
            STATE["evaluation_entries"] += 1
            bpy.context.view_layer.update()
            return {"evaluated": True}

        runtime.registry.register(FOREIGN, foreign, toolset="core", modifies=True,
            permissions=(Permission.EDIT_SCENE,), automatic_checkpoint=False)
        runtime.registry.register(EVALUATE, evaluate, toolset="core", modifies=False,
            permissions=(Permission.INSPECT_SCENE,))

        STATE["image_budget_callback_calls"] = 0

        def forbidden_image_budget():
            STATE["image_budget_callback_calls"] += 1
            raise AssertionError("Scene scheduling invoked the image configuration callback")

        runtime.jobs.budget_ms = forbidden_image_budget
        original_tick, original_inspect = runtime.jobs.tick, runtime.jobs.inspect
        original_stamp, original_snapshot = runtime.checkpoints._stamp, runtime.checkpoints._snapshot

        def tracked_stamp(blender, *, guard=None):
            job = runtime.jobs.active
            assert job is not None and job.lifetime.delivered.is_set(), "Checkpoint write preceded start delivery"
            STATE["checkpoint_stamps"].append({"job_id": job.job_id, "scheduler_tick": STATE["scheduler_tick"],
                "start_response_delivered": job.lifetime.delivered.is_set()})
            return original_stamp(blender, guard=guard)

        def tracked_snapshot(blender, label, *, guard=None):
            job = runtime.jobs.active
            assert job is not None and job.lifetime.delivered.is_set()
            result = original_snapshot(blender, label, guard=guard)
            STATE["undo_pushes"].append({"job_id": job.job_id, "label": label,
                "scheduler_tick": STATE["scheduler_tick"], "marker": result,
                "start_response_delivered": job.lifetime.delivered.is_set()})
            return result

        def tracked_tick():
            STATE["scheduler_tick"] += 1
            tick = STATE["scheduler_tick"]
            job = runtime.jobs.active
            before = len(STATE["phase_calls"])
            pending = runtime.checkpoints._pending
            row = {"tick": tick, "job_id": job.job_id if job else None,
                "phase_count_before": before, "pending_before": None if pending is None else pending.before_marker,
                "start_delivered": bool(job and job.lifetime.delivered.is_set())}
            STATE["scheduler_turns"].append(row)
            STATE["inside_scheduler"] = True
            try:
                return original_tick()
            finally:
                STATE["inside_scheduler"] = False
                pending = runtime.checkpoints._pending
                row.update(phase_count_after=len(STATE["phase_calls"]),
                    pending_after=None if pending is None else pending.before_marker)
                assert len(STATE["phase_calls"])-before <= 1, row
                if runtime.jobs.active is not None:
                    runtime.state.set_paused(True)
                persist("scene-job-kernel-progress.json", {**evidence(), "terminal_success": False})
                TURN_DONE.set()

        def tracked_inspect(job_id):
            result = original_inspect(job_id)
            entries = runtime.registry._mutation_interlock._entries
            if entries and entries[-1].spec.name == INSPECT:
                STATE["polls"].append({"job_id": job_id, "scheduler_tick": STATE["scheduler_tick"],
                    "state": result["state"], "revision": result["revision"],
                    "phase": result["progress"]["phase"], "inside_job_tick": STATE["inside_scheduler"]})
            return result

        runtime.checkpoints._stamp, runtime.checkpoints._snapshot = tracked_stamp, tracked_snapshot
        runtime.jobs.tick, runtime.jobs.inspect = tracked_tick, tracked_inspect

        def observe(case):
            driver = STATE["drivers"][case]
            rows = [row for row in STATE["phase_calls"] if row["case"] == case]
            pending = runtime.checkpoints._pending
            return {"last_domain_phase": rows[-1]["phase"] if rows else None,
                "domain_phase_count": len(rows), "native_call_count": sum(
                    row["stage"] not in {"scope_comparison", "scope_publication_readback"}
                    for row in driver.boundary.timings),
                "undo_push_count": len(STATE["undo_pushes"]),
                "checkpoint_stamp_count": len(STATE["checkpoint_stamps"]),
                "scene_marker": scene.get("_codex_bridge_undo_marker"),
                "pending_marker": None if pending is None else pending.before_marker,
                "frame": [scene.frame_current, scene.frame_subframe], "body_a_x": float(bodies[0].location.x),
                "caller_context_restored": context_state() == driver.initial_context,
                "context": context_state()}

        def apply(action, params):
            if action == "resume":
                TURN_DONE.clear()
                runtime.state.set_paused(False)
            elif action == "observe":
                return observe(params["case"])
            elif action == "prepare_case":
                assert runtime.jobs.active is None
                before = context_state()
                # Explicit fresh fixture action after prior ownership ended.
                scene.frame_set(7, subframe=.25)
                bpy.context.view_layer.update()
                STATE["fixture_actions"].append({"action": "fresh_caller_time_reset", "case": params["case"],
                    "before": before, "after": context_state(), "old_owner_reused": False})
                runtime.state.set_paused(False)
            elif action in {"deny_animation", "allow_animation"}:
                grants[Permission.EDIT_ANIMATION.value] = action == "allow_animation"
            elif action == "external_edit":
                bodies[0].location.x += .125
                STATE["fixture_actions"].append({"action": "external_authored_edit", "body_a_x": float(bodies[0].location.x)})
            elif action == "record_terminal":
                case = params["case"]
                assert runtime.jobs.active is None
                terminal = params["terminal"]
                checkpoint = terminal["checkpoint"]
                assert checkpoint["state"] == ("FINALIZED" if case == "complete" else "ABANDONED"), checkpoint
                assert checkpoint["before_verified"] and checkpoint["after_verified"] == (case == "complete"), checkpoint
                assert checkpoint["native_snapshots_completed"] == (2 if case == "complete" else 1), checkpoint
                assert not checkpoint["durable_backup_created"] and not checkpoint["native_cache_recovery_guaranteed"]
                STATE["cases"][case].update(terminal=terminal, retained=observe(case))
            elif action == "final_verify":
                assert runtime.jobs.active is None
                assert STATE["foreign_entries"] == STATE["evaluation_entries"] == 0
                assert STATE["image_budget_callback_calls"] == 0
                assert all(value == 0 for value in provider_counts.values()), provider_counts
                assert len(STATE["cases"]) == 5 and all("terminal" in case for case in STATE["cases"].values())
                assert all(row["start_response_delivered"] for row in STATE["phase_calls"]+STATE["checkpoint_stamps"]+STATE["undo_pushes"])
                assert STATE["polls"] and all(not row["inside_job_tick"] for row in STATE["polls"])
                turns = {row["tick"]: row for row in STATE["scheduler_turns"]}
                for case, retained in STATE["cases"].items():
                    phases = [row for row in STATE["phase_calls"] if row["case"] == case]
                    assert phases, case
                    markers = [turns[row["scheduler_tick"]]["pending_before"] for row in phases]
                    assert markers[0] is not None and len(set(markers)) == 1, (case, markers)
                    assert all(turns[row["scheduler_tick"]]["pending_after"] == markers[0] for row in phases), case
                    retained["pending_checkpoint_marker_across_domain_phases"] = markers[0]
                    identifier = retained["terminal"]["job_id"]
                    pushes = [row for row in STATE["undo_pushes"] if row["job_id"] == identifier]
                    assert len(pushes) == (2 if case == "complete" else 1), (case, pushes)
                assert len({row["scheduler_tick"] for row in STATE["phase_calls"]}) == len(STATE["phase_calls"])
                receipts = [runtime.checkpoints.pending_status(record.handle)
                    for record in runtime.checkpoints._owned_pending.values()]
                abandoned = {row["pending_id"]: row for row in receipts if row["state"] == "ABANDONED"}
                assert len(abandoned) == 4, abandoned
                for case, retained in STATE["cases"].items():
                    if case != "complete":
                        checkpoint = retained["terminal"]["checkpoint"]
                        assert abandoned[checkpoint["pending_id"]] == checkpoint
                STATE["retained_abandoned_checkpoint_receipts"] = receipts
                ledger = runtime.jobs.recovery_ledger
                for case, retained in STATE["cases"].items():
                    if case != "complete":
                        terminal = retained["terminal"]
                        assert ledger[terminal["job_id"]]["checkpoint"] == terminal["checkpoint"]
                STATE["recovery_ledger"] = {identifier: {
                    key: entry[key] for key in ("checkpoint", "effects", "error", "phase") if key in entry}
                    for identifier, entry in ledger.items()}
                # A new explicit fixture action restores caller time only after
                # the last stopped owner has released its reservation.
                scene.frame_set(7, subframe=.25)
                bpy.context.view_layer.update()
                assert context_state() == initial_context
                assert abs(bodies[0].location.x-.125) < TOLERANCE
                STATE["final_context"] = context_state()
                STATE["fixture_actions"].append({"action": "final_fresh_caller_time_restore", "old_owner_reused": False})
            else:
                raise AssertionError(action)

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        runtime.start_server("127.0.0.1", port, request_timeout=30)
        started = time.monotonic()

        def supervise():
            try:
                while not CONTROLS.empty():
                    action, params, event, result = CONTROLS.get_nowait()
                    try:
                        value = apply(action, params)
                        result.extend([True, value])
                    except Exception:
                        result.append(traceback.format_exc())
                    finally:
                        event.set()
                if not DONE.is_set() and time.monotonic()-started < 180:
                    return .005
                assert DONE.is_set(), "Fixture timer deadline expired"
                assert "failure" not in RESULT, RESULT.get("failure")
                result = {**evidence(), "socket_evidence": RESULT,
                    "checkpoint_stamps": STATE["checkpoint_stamps"], "undo_pushes": STATE["undo_pushes"],
                    "typed_native_control": STATE["typed_native_control"],
                    "fixture_actions": STATE["fixture_actions"], "final_context": STATE["final_context"],
                    "foreign_provider_entries": provider_counts,
                    "retained_abandoned_checkpoint_receipts": STATE["retained_abandoned_checkpoint_receipts"],
                    "recovery_ledger": STATE["recovery_ledger"],
                    "one_domain_phase_per_actual_scheduler_tick": True,
                    "effective_scene_slice_budget_ms": 4.,
                    "image_budget_callback_calls": STATE["image_budget_callback_calls"],
                    "real_socket_and_start_delivery": True, "terminal_success": True}
                receipt = persist("scene-job-kernel-evidence.json", result)
                runtime.stop_server()
                STATE["done"] = True
                print("BLENDER_SCENE_JOB_KERNEL_OK " + json.dumps({"blender_version": bpy.app.version_string,
                    **receipt, "real_socket_and_start_delivery": True,
                    "one_domain_phase_per_actual_scheduler_tick": True,
                    "terminal_cases": len(STATE["cases"]), "public_rigid_job_implemented": False,
                    "full_recovery_acceptance": False, "release_readiness": "NOT_ASSESSED"}), flush=True)
                bpy.ops.wm.quit_blender()
                return None
            except Exception:
                STATE["done"] = True
                failure = traceback.format_exc()
                print(failure, file=sys.stderr, flush=True)
                receipt = persist("scene-job-kernel-failure.json", {**evidence(), "traceback": failure,
                    "worker": RESULT, "terminal_success": False, "failure_path_native_cleanup_attempted": False})
                print("SCENE_JOB_KERNEL_FAILED " + json.dumps(receipt), flush=True)
                bpy.ops.wm.quit_blender()
                return None

        bpy.app.timers.register(supervise, first_interval=.005)
        threading.Thread(target=scenario, args=(port,), name="SceneJobKernelSocketFixture", daemon=True).start()
    except Exception:
        failure = traceback.format_exc()
        print(failure, file=sys.stderr, flush=True)
        receipt = persist("scene-job-kernel-setup-failure.json", {
            "traceback": failure, "process_id": os.getpid(),
            "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "source_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "terminal_success": False, "failure_path_native_cleanup_attempted": False})
        print("SCENE_JOB_KERNEL_FAILED " + json.dumps(receipt), flush=True)
        bpy.ops.wm.quit_blender()
    return None


def main():
    bpy.app.timers.register(setup, first_interval=1.)


if __name__ == "__main__":
    main()
