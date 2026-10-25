"""Owned real-runtime history/reporting failures through actual loopback RPC.

Import-safe and opt-in. The worker owns JSON/TCP only; Blender, fault injection
and passive code-identity observations stay on the main thread. No core method,
checkpoint delegate, response builder or serializer is replaced by this fixture.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALUE = "Owned executor history containment value"
WRITE, DENIED, BAD_ERROR, START, HEALTHY = ("fixture.history." + name for name in
    ("write", "denied", "bad_error", "start", "healthy"))
MARKER = "BLENDER_EXECUTOR_HISTORY_CONTAINMENT_OK "
BUILDS = {(4, 5, 14): "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
          (5, 2, 2): "d13f752e3b9c4f8c261cda552b1021f8bcc0382c"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def worker(port: int, done: threading.Event, result: dict[str, Any]) -> None:
    """No Blender references cross this transport boundary."""
    connection = stream = None
    try:
        connection = socket.create_connection(("127.0.0.1", port), timeout=15.)
        stream = connection.makefile("rb")
        rows = []

        def call(method: str) -> dict[str, Any]:
            assert len(rows) < 32
            identifier = "history_native_" + str(len(rows))
            connection.sendall(canonical({"id": identifier, "method": method, "params": {},
                "protocol_version": "1.0", "timeout_ms": 10000})+b"\n")
            raw = stream.readline(256*1024)
            assert raw.endswith(b"\n") and len(raw) < 256*1024
            response = json.loads(raw)
            assert response["id"] == identifier and response["protocol_version"] == "1.0"
            assert b"private serialization detail" not in raw
            rows.append({"method": method, "response": response, "wire_sha256": hashlib.sha256(raw).hexdigest()})
            return response

        for method, code in [(WRITE, "OPERATION_FAILED"), (DENIED, "PERMISSION_DENIED"),
                             (BAD_ERROR, "SERVER_ERROR"), (START, "OPERATION_FAILED")]:
            failed = call(method)
            assert not failed["ok"] and failed["error"]["code"] == code, failed
            if method != BAD_ERROR:
                facts = failed["error"]["context"]
                assert facts["history_recording_failed"] and facts["history_outcome_unknown"]
                assert facts["history_record_verified"] is False and facts["history_retry_attempted"] is False
            else:
                assert failed["error"]["context"]["execution_outcome_unknown"]
            if method == START:
                for _ in range(16):
                    listing = call("jobs.list")
                    assert listing["ok"], listing
                    jobs = listing["result"]["jobs"]
                    if jobs and jobs[0]["terminal"]:
                        assert jobs[0]["state"] in {"FAILED", "CANCELLED"}
                        break
                    time.sleep(.02)
                else:
                    raise AssertionError("Rejected start never retired")
            healthy = call(HEALTHY)
            assert healthy["ok"] and healthy["result"]["value"] == 1, healthy
            assert healthy["result"]["active_job"] is None and healthy["result"]["executing_mutators"] == 0
        assert call(HEALTHY)["ok"]  # A subsequent timer/queue turn stays usable.
        result.update(complete=True, rows=rows)
    except Exception:
        result["failure"] = traceback.format_exc()
    finally:
        for owned in (stream, connection):
            if owned is not None:
                try:
                    owned.close()
                except Exception as error:
                    result["close_failure"] = type(error).__name__
        done.set()


class Fixture:
    def __init__(self, bpy: Any, folder: Path, process: str, attestation: dict[str, Any]):
        self.bpy, self.path, self.process = bpy, folder/"executor-history-containment.json", process
        assert not self.path.exists()
        self.runtime: Any = None
        self.current: str | None = None
        self.code_names: dict[Any, str] = {}
        self.rows: dict[str, Any] = {}
        self.calls = {"write": 0, "denied": 0, "bad_error": 0, "start": 0, "healthy": 0,
            "bad_value": 0, "driver_created": 0, "driver_advanced": 0}
        self.history_events: list[Any] = []
        self.outside: dict[str, int] = {}
        self.profile_failures = 0
        self.job: Any = None
        self.done, self.worker_result = threading.Event(), {}
        self.deadline, self.settled = time.monotonic()+45., 0
        self.data: dict[str, Any] = {"complete": False, "process_instance": process,
            "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "owned_profile": attestation, "limits": {"Windows_qualified": False, "release_acceptance": False,
                "native_undo_executed": False, "project_saved": False, "public_tools_added": False,
                "failure_injection_scope": "Owned runtime history writer only; actual native runtime/transport/serializer"}}

    def protected(self) -> dict[str, Any]:
        bpy = self.bpy
        assert bpy.context.mode == "OBJECT" and len(bpy.data.scenes) == 1
        scene, layer = bpy.context.scene, bpy.context.view_layer
        return {"context": [scene.as_pointer(), scene.session_uid, layer.as_pointer(),
            bpy.context.window.as_pointer(), int(scene.frame_current), float(scene.frame_subframe).hex(),
            layer.objects.active.as_pointer(), sorted((obj.as_pointer(), bool(obj.select_get())) for obj in scene.objects)],
            "objects": [(obj.as_pointer(), obj.session_uid, obj.name, obj.type,
                [list(row) for row in obj.matrix_world],
                None if obj.data is None else (obj.data.as_pointer(), obj.data.session_uid))
                for obj in sorted(bpy.data.objects, key=lambda obj: obj.name)],
            "meshes": [(mesh.as_pointer(), mesh.session_uid,
                [list(vertex.co) for vertex in mesh.vertices], [list(edge.vertices) for edge in mesh.edges],
                [list(poly.vertices) for poly in mesh.polygons],
                [(slot.as_pointer(), slot.session_uid) if slot is not None else None for slot in mesh.materials])
                for mesh in bpy.data.meshes]}

    def observe_profile(self, frame: Any, event: str, argument: Any) -> None:
        """Copy Python facts only; never call native/provider/history code."""
        try:
            name = self.code_names.get(frame.f_code)
            if name == "request":
                if event == "call":
                    request = frame.f_locals["request"]
                    self.current = request.id
                    self.rows[request.id] = {"method": request.method, "calls": {}, "history_attempts": 0,
                        "providers": 0, "providers_after_history": 0, "native_at_history": None}
                elif event == "return":
                    self.current = None
            elif name is not None and event == "call":
                counters = self.rows[self.current]["calls"] if self.current is not None else self.outside
                counters[name] = counters.get(name, 0)+1
        except Exception:
            self.profile_failures += 1

    def provider(self) -> dict[str, bool]:
        from blender_codex_bridge.permissions import Permission
        assert threading.current_thread() is threading.main_thread()
        if self.current is not None:
            row = self.rows[self.current]
            row["providers"] += 1
            row["providers_after_history"] += int(row["history_attempts"] > 0)
        return {permission.value: permission in {Permission.INSPECT_SCENE, Permission.EDIT_SCENE}
                for permission in Permission}

    def record_history(self, **details: Any) -> Any:
        assert threading.current_thread() is threading.main_thread()
        if self.current is not None:
            row = self.rows[self.current]
            row["history_attempts"] += 1
            if row["native_at_history"] is None:
                row["native_at_history"] = dict(row["calls"])
        self.history_events.append({"request_id": self.current, "tool": details["tool"], "success": details["success"]})
        record = self.original_history(**details)  # Real append occurs before the injected exception.
        if details["tool"] in {WRITE, DENIED, START}:
            raise RuntimeError("Owned fixture history append outcome unavailable")
        return record

    def register_tools(self) -> None:
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.permissions import Permission
        from blender_codex_bridge.scene_jobs import start_admission
        from blender_codex_bridge.tool_registry import check_final_mutation

        fixture = self

        def write(context: Any, _params: Any) -> dict[str, Any]:
            context.require(Permission.EDIT_SCENE)
            check_final_mutation(context, WRITE)
            self.calls["write"] += 1
            self.bpy.context.scene[VALUE] += 1
            return {"value": int(self.bpy.context.scene[VALUE])}

        def denied(_context: Any, _params: Any) -> None:
            self.calls["denied"] += 1
            raise AssertionError("Denied native handler entered")

        class InvalidReportingValue:
            @property
            def name(self) -> str:
                fixture.calls["bad_value"] += 1
                raise RuntimeError("private serialization detail")

        def bad_error(_context: Any, _params: Any) -> None:
            self.calls["bad_error"] += 1
            raise BridgeError("PERMISSION_DENIED", "Owned unrenderable primary denial",
                              {"invalid": InvalidReportingValue()})

        def healthy(_context: Any, _params: Any) -> dict[str, Any]:
            self.calls["healthy"] += 1
            return {"value": int(self.bpy.context.scene[VALUE]), "active_job": self.runtime.jobs.status()["active"],
                "executing_mutators": self.runtime.registry.executing_mutators}

        class Driver:
            kind, label = "fixture.rejected_history_start", "Owned failed history handoff"
            required_permissions = (Permission.EDIT_SCENE,)
            phase, done, result = "never_enter", False, None

            def __init__(self, _context: Any, _params: Any):
                fixture.calls["driver_created"] += 1

            def check_after_read(self, _context: Any) -> None:
                if fixture.bpy.context.mode != "OBJECT" or fixture.bpy.context.scene[VALUE] != 1:
                    raise BridgeError("NOT_IMPLEMENTED", "Owned failed-start scope changed")

            def native_push_delegates(self) -> tuple:
                return ()  # No native phase is authorized by a rejected start.

            def advance(self, _context: Any) -> None:
                fixture.calls["driver_advanced"] += 1
                raise AssertionError("Rejected start performed later work")

        def start(context: Any, params: Any) -> dict[str, Any]:
            self.calls["start"] += 1
            result = context.jobs.start_scene(context, params, time_limit=10.)
            self.job = context.jobs.active
            assert self.job is not None and not self.job.lifetime.delivered.is_set()
            return result

        registry = self.runtime.registry
        registry.register(WRITE, write, modifies=True, permissions=(Permission.EDIT_SCENE,))
        registry.register(DENIED, denied, modifies=True, permissions=(Permission.EDIT_MESH,))
        registry.register(BAD_ERROR, bad_error, permissions=(Permission.INSPECT_SCENE,))
        registry.register(HEALTHY, healthy, permissions=(Permission.INSPECT_SCENE,))
        registry.register(START, start, modifies=True, permissions=(Permission.EDIT_SCENE,), automatic_checkpoint=False,
            batchable=False, exclusive_mutation=True, checkpoint_owns_finalization=True,
            checkpoint_admission_factory=start_admission(Driver))

    def flush(self) -> None:
        self.data.update(requests=self.rows, calls=self.calls, outside_request_finalization_calls=self.outside,
            history_attempts=self.history_events, profile_capture_failures=self.profile_failures,
            worker=self.worker_result)
        raw = canonical(self.data)+b"\n"
        assert len(raw) <= 2*1024*1024
        self.path.write_bytes(raw)

    def setup(self) -> None:
        try:
            from blender_codex_bridge.checkpoints import CheckpointManager
            from blender_codex_bridge.permissions import PermissionManager
            from blender_codex_bridge.runtime import BridgeRuntime

            assert tuple(self.bpy.app.version) in BUILDS and self.bpy.app.build_hash.decode() in {
                BUILDS[tuple(self.bpy.app.version)], BUILDS[tuple(self.bpy.app.version)][:12]}
            self.bpy.context.scene[VALUE] = 0
            self.data["protected_before"] = self.protected()
            self.runtime = BridgeRuntime()
            permissions = PermissionManager(self.provider)
            self.runtime.permissions = self.runtime.executor.permissions = permissions
            self.register_tools()
            self.runtime.register()
            self.original_history = self.runtime.state.record_operation
            self.runtime.state.record_operation = self.record_history
            self.code_names = {inspect.unwrap(getattr(CheckpointManager, name)).__code__: name for name in
                ("before_modification", "after_modification", "finish_editor_session", "_snapshot")}
            self.code_names[self.runtime.executor.execute_request.__func__.__code__] = "request"
            assert sys.getprofile() is None
            sys.setprofile(self.observe_profile)
            self.push_position = self.runtime.checkpoints._window.position
            with socket.socket() as reserved:
                reserved.bind(("127.0.0.1", 0))
                port = reserved.getsockname()[1]
            self.runtime.start_server("127.0.0.1", port, request_timeout=10.)
            self.data["source_sha256"] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                "scripts/blender_executor_history_containment_smoke.py", "addon/blender_codex_bridge/executor.py",
                "addon/blender_codex_bridge/artist_step_evidence.py", "addon/blender_codex_bridge/runtime.py",
                "addon/blender_codex_bridge/request_lifecycle.py", "addon/blender_codex_bridge/server.py",
                "addon/blender_codex_bridge/scene_jobs.py", "addon/blender_codex_bridge/checkpoints.py")}
            binary = Path(self.bpy.app.binary_path).resolve(strict=True)
            sha = hashlib.sha256()
            with binary.open("rb") as stream:
                while block := stream.read(1024*1024):
                    sha.update(block)
            self.data.update(binary_path=str(binary), binary_sha256=sha.hexdigest())
            threading.Thread(target=worker, args=(port, self.done, self.worker_result),
                name="OwnedHistoryContainmentJSONWorker", daemon=True).start()
            self.bpy.app.timers.register(self.tick, first_interval=.05)
            self.flush()
        except Exception:
            self.finish(False)

    def verify(self) -> None:
        assert self.worker_result.get("complete") and "failure" not in self.worker_result
        assert "close_failure" not in self.worker_result
        assert self.profile_failures == 0
        assert self.calls == {"write": 1, "denied": 0, "bad_error": 1, "start": 1, "healthy": 5,
            "bad_value": 1, "driver_created": 1, "driver_advanced": 0}
        assert self.protected() == self.data["protected_before"]
        assert self.bpy.context.scene[VALUE] == 1
        assert self.runtime.registry.executing_mutators == 0 and self.runtime.jobs.active is None
        assert self.runtime.registry._scene_reservations.owner is None
        assert self.runtime.checkpoints._window.position-self.push_position == 2
        self.data["owned_native_snapshots_completed"] = 2
        for row in self.rows.values():
            assert row["providers_after_history"] == 0
            if row["method"] in {WRITE, DENIED, BAD_ERROR, START, HEALTHY}:
                assert row["history_attempts"] == 1
                assert row["calls"] == row["native_at_history"], "History failure repeated native finalization"
            expected = {"before_modification": 1, "after_modification": 1,
                "finish_editor_session": 1, "_snapshot": 2} if row["method"] == WRITE else {}
            assert row["calls"] == expected, row
        assert self.outside == {}, self.outside
        history = self.runtime.state.history(32)
        for method in (WRITE, DENIED, BAD_ERROR, START):
            assert len([row for row in history if row["tool"] == method]) == 1
        assert self.job is not None and self.job.lifetime.rejected.is_set() and not self.job.lifetime.delivered.is_set()
        assert self.job.state in {"CANCELLED", "FAILED"} and self.job.execution_started is False
        assert self.job.effects["domain_phases_completed"] == 0
        assert self.job.checkpoint["native_snapshots_completed"] == self.job.checkpoint["marker_writes_completed"] == 0
        self.data["failed_start"] = {"summary": self.job.summary(), "checkpoint": self.job.checkpoint,
            "start_delivery_rejected": True, "start_delivery_succeeded": False, "driver_advances": 0}
        self.data["history"] = history

    def tick(self) -> float | None:
        try:
            assert time.monotonic() < self.deadline, "Owned native history fixture exceeded its deadline"
            if not self.done.is_set():
                self.flush()
                return .05
            self.settled += 1
            if self.settled < 3:
                return .05
            self.verify()
            self.finish(True)
        except Exception:
            self.finish(False)
        return None

    def finish(self, success: bool) -> None:
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        sys.setprofile(None)
        self.data["complete"] = success
        if not success:
            self.data["failure"] = traceback.format_exc()
        try:
            self.flush()
            payload = {"blender_version": self.bpy.app.version_string, "process_instance": self.process,
                "process_id": os.getpid(), "evidence_file": str(self.path),
                "evidence_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest()}
            print((MARKER if success else "BLENDER_EXECUTOR_HISTORY_CONTAINMENT_FAILED ")+json.dumps(payload), flush=True)
        finally:
            owned_process_exit(0 if success else 1)


def main() -> None:
    import bpy

    sys.path[:0] = [str(ROOT), str(ROOT/"addon")]
    from scripts.blender_artist_sidebar_smoke import private_display_manifest

    assert not bpy.app.background and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert threading.current_thread() is threading.main_thread()
    display = private_display_manifest()
    process = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(process) == 32 and all(char in "0123456789abcdef" for char in process)
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    for key in ("TEMP", "TMP", "TMPDIR", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        path = Path(os.environ[key])
        assert path.is_absolute() and path.resolve(strict=True).is_relative_to(folder)
    assert bpy.data.filepath == ""
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    fixture = Fixture(bpy, folder, process, {"display": display, "factory_startup": True,
        "disable_autoexec": True, "serialization_disabled": True,
        "termination": "Owned os._exit without save/quit/native-undo execution"})
    bpy.app.timers.register(fixture.setup, first_interval=1.)


if __name__ == "__main__":
    main()
