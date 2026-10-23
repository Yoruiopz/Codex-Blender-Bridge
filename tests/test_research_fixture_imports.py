"""Importing native fixture helpers must never start their owned experiment."""

from __future__ import annotations

import importlib
import runpy
import socket
import sys
import threading
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = (
    "scripts.blender_rigid_timer_probe_smoke",
    "scripts.blender_rigid_lifecycle_probe_smoke",
    "scripts.blender_scene_job_kernel_smoke",
    "scripts.blender_rigid_evaluation_jobs_smoke",
    "scripts.blender_simulation_cache_probe_smoke",
    "scripts.blender_camera_focus_smoke",
    "scripts.blender_animation_curve_sampling_smoke",
    "scripts.blender_surface_publication_probe",
    "scripts.blender_sculpt_mask_smoke",
    "scripts.blender_character_revision_smoke",
    "scripts.blender_artist_target_verification_smoke",
    "scripts.native_character_revision_evidence",
    "scripts.native_character_evidence",
    "scripts.native_cache_evidence",
)


@pytest.fixture
def fixture_imports(addon_package, monkeypatch):
    events = []

    def forbidden(name):
        def call(*_args, **_kwargs):
            events.append(name)
            pytest.fail(f"Fixture import unexpectedly ran {name}")
        return call

    def module(name, **values):
        value = ModuleType(name)
        value.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    permissions = importlib.import_module(f"{addon_package}.permissions")
    errors = importlib.import_module(f"{addon_package}.errors")
    package = module("blender_codex_bridge", register=forbidden("addon.register"), __path__=[])
    module("blender_codex_bridge.errors", BridgeError=errors.BridgeError)
    module("blender_codex_bridge.permissions", Permission=permissions.Permission,
           PermissionManager=forbidden("PermissionManager construction"))
    module("blender_codex_bridge.command_queue", QueuedRequest=forbidden("QueuedRequest construction"))
    module("blender_codex_bridge.protocol", Request=forbidden("Request construction"))
    module("blender_codex_bridge.request_lifecycle", RequestLifetime=NS(local=forbidden("local request")))
    module("blender_codex_bridge.runtime", get_runtime=forbidden("get_runtime"))
    module("blender_codex_bridge.scene_job_reservations", TURN_METHOD="jobs._scene_turn")
    module("blender_codex_bridge.tool_registry", check_final_mutation=forbidden("mutation gate"))
    tools = module("blender_codex_bridge.tools", __path__=[])
    for name in ("_rigid_body_scope", "_scene_checkpoint_roles", "surface_brushes", "rig_ik"):
        setattr(tools, name, module(f"blender_codex_bridge.tools.{name}"))
    tools.rigid_body = module("blender_codex_bridge.tools.rigid_body", _Boundary=type("Boundary", (), {}),
                              PERMISSIONS=(permissions.Permission.EDIT_SCENE,))
    package.tools = tools
    timers = []

    def register(callback, **kwargs):
        timers.append((callback.__name__, kwargs))

    module("bpy", app=NS(timers=NS(register=register)),
           ops=NS(wm=NS(quit_blender=forbidden("quit_blender"))))
    monkeypatch.setattr(threading, "Thread", forbidden("worker construction"))
    monkeypatch.setattr(socket, "create_connection", forbidden("socket connection"))
    for name in ("write_text", "write_bytes", "mkdir", "replace"):
        monkeypatch.setattr(Path, name, forbidden(f"Path.{name}"))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(ROOT))
    scripts = importlib.import_module("scripts")
    previous = {name: getattr(scripts, name.rsplit(".", 1)[1], None) for name in HELPERS}
    for name in HELPERS:
        monkeypatch.delitem(sys.modules, name, raising=False)
    try:
        yield NS(events=events, timers=timers)
    finally:
        for name in HELPERS:
            sys.modules.pop(name, None)
            attribute = name.rsplit(".", 1)[1]
            if previous[name] is not None:
                setattr(scripts, attribute, previous[name])
            elif hasattr(scripts, attribute):
                delattr(scripts, attribute)


@pytest.mark.parametrize("name,helper", [
    ("scripts.blender_rigid_timer_probe_smoke", "checkpointed_cache"),
    ("scripts.blender_rigid_lifecycle_probe_smoke", "make_scene"),
    ("scripts.blender_scene_job_kernel_smoke", "RigidDriver"),
    ("scripts.blender_rigid_evaluation_jobs_smoke", "Fixture"),
    ("scripts.blender_simulation_cache_probe_smoke", "values"),
    ("scripts.blender_camera_focus_smoke", "main"),
    ("scripts.blender_animation_curve_sampling_smoke", "main"),
    ("scripts.blender_surface_publication_probe", "main"),
    ("scripts.blender_sculpt_mask_smoke", "main"),
    ("scripts.blender_character_revision_smoke", "main"),
    ("scripts.blender_artist_target_verification_smoke", "main"),
    ("scripts.native_character_revision_evidence", "lbs_vertices"),
])
def test_importing_helper_fixture_does_not_start_experiment(fixture_imports, name, helper):
    imported = importlib.import_module(name)
    assert callable(getattr(imported, helper))
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("name,expected", [
    ("blender_rigid_timer_probe_smoke.py", [("heartbeat", {"first_interval": .01}), ("tick", {"first_interval": 1.})]),
    ("blender_scene_job_kernel_smoke.py", [("setup", {"first_interval": 1.})]),
    ("blender_rigid_evaluation_jobs_smoke.py", [("setup", {"first_interval": 1.})]),
])
def test_explicit_fixture_entrypoint_schedules_only_its_own_timers(fixture_imports, name, expected):
    runpy.run_path(str(ROOT / "scripts" / name), run_name="__main__")
    assert fixture_imports.timers == expected and fixture_imports.events == []


@pytest.fixture
def scene_worker(fixture_imports, monkeypatch):
    script = importlib.import_module("scripts.blender_scene_job_kernel_smoke")

    def run(*, retire_at="stop", drift=None):
        state = NS(case=None, terminal=False, progressed=False, pending_stop=None, polls_left=0,
                   body_a_x=0., resumes=[], waits=[], observations=[], recorded={}, requests=[],
                   stopped_observations=0, final_verified=False, clients_closed=0, sleeps=[])

        def stop():
            state.pending_stop = state.case
            state.terminal = retire_at == "stop"
            state.polls_left = 1

        def summary():
            if state.pending_stop and not state.terminal:
                if state.polls_left:
                    state.polls_left -= 1
                else:
                    state.terminal = True
            value = {"job_id": state.case, "terminal": state.terminal,
                     "state": "SUCCEEDED" if state.case == "complete" and state.terminal else
                              "FAILED" if state.terminal else "RUNNING",
                     "revision": int(state.progressed)+int(state.terminal)}
            if state.pending_stop:
                value["error"] = {"code": {"cancel": "TIMEOUT", "permission": "PERMISSION_DENIED",
                    "disconnect": "TIMEOUT", "external_edit": "INVALID_ARGUMENT"}[state.case],
                    "context": {"connection_disconnected": state.case == "disconnect"}}
            return value

        class Client:
            def __init__(self, port):
                assert port == 12345

            def call(self, method, **params):
                if method == script.START:
                    assert params == {"case": state.case}
                    return {"accepted": True, "job_id": state.case, "terminal": False}
                if method == script.INSPECT:
                    assert params == {"job_id": state.case}
                    return summary()
                if method == "bridge.status":
                    return {}
                assert method == "jobs.cancel" and params == {"job_id": state.case}
                stop()
                return {"cancel_requested": True}

            def request(self, method):
                assert method in {script.FOREIGN, script.EVALUATE}
                state.requests.append((state.case, method))
                return {"ok": False, "error": {"code": "OPERATION_FAILED",
                    "context": {"reason": "SCENE_JOB_RESERVATION_BLOCKED"}}}

            def close(self):
                state.clients_closed += 1
                if state.case == "disconnect" and not state.terminal:
                    stop()

        def control(action, **params):
            if action == "prepare_case":
                state.case, state.terminal, state.progressed = params["case"], False, False
                state.pending_stop, state.body_a_x, state.stopped_observations = None, 0., 0
            elif action == "resume":
                assert not state.pending_stop, "A stopped owner has no later timer turn"
                state.resumes.append(state.case)
                state.progressed = True
                state.terminal = state.case == "complete"
            elif action == "observe":
                assert params == {"case": state.case}
                value = {"last_domain_phase": "frame_2_set" if state.progressed else None,
                         "domain_phase_count": int(state.progressed), "native_call_count": 33,
                         "undo_push_count": 1, "checkpoint_stamp_count": 3,
                         "scene_marker": "owned-before", "frame": [2, 0.],
                         "caller_context_restored": False, "body_a_x": state.body_a_x}
                if state.pending_stop:
                    state.stopped_observations += 1
                    if state.case == "external_edit" and drift:
                        when = 2 if drift == "late_native_call_count" else 1
                        if state.stopped_observations == when:
                            field = "native_call_count" if drift == "late_native_call_count" else drift
                            value[field] = {"scene_marker": "foreign", "frame": [3, 0.],
                                "caller_context_restored": True, "body_a_x": .25}.get(field, 999)
                state.observations.append((state.case, bool(state.pending_stop), value.copy()))
                return value
            elif action in {"deny_animation", "external_edit"}:
                if action == "external_edit":
                    state.body_a_x += .125
                stop()
            elif action == "allow_animation":
                assert state.terminal
            elif action == "record_terminal":
                assert params["case"] == state.case and params["terminal"]["terminal"]
                state.recorded[state.case] = params["terminal"]
            else:
                assert action == "final_verify" and len(state.recorded) == 5
                state.final_verified = True

        def wait(timeout):
            assert timeout == 10 and state.resumes[-1] == state.case
            assert not state.pending_stop, "A retired owner cannot signal TURN_DONE"
            state.waits.append(state.case)
            return True

        clock = iter(range(1000))
        monkeypatch.setattr(script, "Client", Client)
        monkeypatch.setattr(script, "control", control)
        monkeypatch.setattr(script, "TURN_DONE", NS(wait=wait))
        monkeypatch.setattr(script, "DONE", threading.Event())
        monkeypatch.setattr(script, "RESULT", {})
        monkeypatch.setattr(script, "time", NS(perf_counter=lambda: 0.,
                            monotonic=lambda: next(clock), sleep=state.sleeps.append))
        script.scenario(12345)
        assert script.DONE.is_set()
        return state, script.RESULT

    return run


@pytest.mark.parametrize("retire_at", ["stop", "poll"])
def test_scene_worker_polls_all_stopped_owners_without_resuming(scene_worker, retire_at):
    state, result = scene_worker(retire_at=retire_at)
    assert "failure" not in result, result.get("failure")
    cases = ["complete", "cancel", "permission", "disconnect", "external_edit"]
    assert state.resumes == state.waits == cases
    assert list(result["terminal_outcomes"]) == list(state.recorded) == cases
    assert state.final_verified and state.clients_closed == 2
    assert len(result["entry_refusals"]) == len(state.requests) == 10
    for case in cases[1:]:
        observations = [row for name, stopped, row in state.observations if name == case and stopped]
        assert len(observations) == 2  # Immediate and delayed no-tail assertions both ran.
        assert all(row["native_call_count"] == 33 for row in observations)
        assert all(row["caller_context_restored"] is False for row in observations)
    assert state.recorded["external_edit"]["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("drift", [
    "domain_phase_count", "native_call_count", "undo_push_count", "checkpoint_stamp_count",
    "scene_marker", "frame", "caller_context_restored", "body_a_x", "late_native_call_count",
])
def test_scene_worker_keeps_stopped_evidence_assertions(scene_worker, drift):
    state, result = scene_worker(drift=drift)
    assert "AssertionError" in result.get("failure", ""), result
    assert "external_edit" not in state.recorded and not state.final_verified
    assert state.resumes == ["complete", "cancel", "permission", "disconnect", "external_edit"]
