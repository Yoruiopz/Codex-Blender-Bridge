"""Actual registered preference route; private isolated runner only.

No project writer, namespace operation, cloth caller or recovery is exercised.
The original Runtime/provider and main-thread TCP dispatch remain intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDS = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}
CASE = "storage_snapshot_root_approval"
PHASE = "registered_route"
SCHEMA = "storage_snapshot_registered_root_approval_v1"
PROFILE = "STOCK_REGISTERED_PREFERENCES_ROOT_APPROVAL_V1"
MARKER = "BLENDER_STORAGE_ROOT_APPROVAL_OK "
METHOD = "fixture.storage_root_approval"
CASES = ("positive_repeated", "manual_root_drift", "denied_inspect", "denied_save", "denied_external_files",
         "paused_after_capture", "emergency_after_capture")
EXPECTED = {"positive_repeated": None, "manual_root_drift": "NOT_IMPLEMENTED", "denied_inspect": "PERMISSION_DENIED",
            "denied_save": "PERMISSION_DENIED", "denied_external_files": "PERMISSION_DENIED",
            "paused_after_capture": "AGENT_PAUSED", "emergency_after_capture": "EMERGENCY_STOPPED"}
LIMITATIONS = ("shipping_caller_qualified", "snapshot_writer_qualified", "post_C_root_check_qualified",
               "cloth_G0_qualified", "durable_backup_qualified", "full_artist_workflow_qualified", "windows_qualified")
MAX_REPORT = 2 * 1024**2
COMPONENTS = ("canonical_runtime", "state", "registry", "permissions", "checkpoints", "jobs", "storage_service",
              "storage_origin", "executor_storage", "original_factory", "queued_request", "main_thread")


def canonical(value):
    from scripts.blender_storage_snapshot_adapter_smoke import canonical as encode
    return encode(value)


def ordinary_file(path, maximum):
    from scripts.blender_storage_snapshot_adapter_smoke import ordinary_file as read
    return read(path, maximum)


def exception_receipt(error):
    from scripts.blender_storage_snapshot_adapter_smoke import exception_receipt as receipt
    return receipt(error)


def runtime_plain_json(value):
    from scripts.blender_storage_snapshot_adapter_smoke import runtime_plain_json as plain
    return plain(value)


def source_names(root=ROOT):
    from scripts.blender_storage_snapshot_adapter_smoke import source_names as adapter_source_names
    return (*adapter_source_names(root), "scripts/blender_storage_root_approval_smoke.py")


def fingerprints(root=ROOT):
    return {name: ordinary_file(root / name, 1024**2)["sha256"] for name in source_names(root)}


def validate(full, *, sources, binary, process_instance, process_id):
    """Cold finite receipt validation; synthetic tests do not qualify native RNA."""
    try:
        fields = {"schema", "profile", "phase", "completed", "version", "build_hash", "blender_version", "binary",
                  "process_instance", "process_id", "source_fingerprints", "source_unchanged", "private_display",
                  "private_display_binding", "cases", "sent", "wire", "terminal", "fixture_only_registration",
                  "original_preferences_provider", "python_disabled", "services_stopped", "observer_restored",
                  "case_deadline_seconds", "limitations", "capture_scope", "fixture_metadata_permission", "resources"}
        if (type(full) is not dict or set(full) != fields or not runtime_plain_json(full)
                or full["schema"] != SCHEMA or full["profile"] != PROFILE or full["phase"] != PHASE
                or full["completed"] is not True or full["source_fingerprints"] != sources or full["binary"] != binary
                or type(process_id) is not int or process_id <= 0 or full["process_id"] != process_id
                or type(process_instance) is not str or len(process_instance) != 32
                or any(ch not in "0123456789abcdef" for ch in process_instance)
                or type(full["process_id"]) is not int or full["process_instance"] != process_instance
                or any(full[name] is not True for name in ("source_unchanged", "fixture_only_registration",
                    "original_preferences_provider", "python_disabled", "services_stopped", "observer_restored"))
                or full["case_deadline_seconds"] != 300 or type(full["case_deadline_seconds"]) is not int
                or type(full["limitations"]) is not dict or set(full["limitations"]) != set(LIMITATIONS)
                or any(value is not False for value in full["limitations"].values())
                or full["capture_scope"] != "pre-provider native route metadata/preferences-owner getters; project_directory value after helper authorization"
                or full["fixture_metadata_permission"] != "EDIT_SCENE; helper separately requires INSPECT_SCENE,SAVE_PROJECT,ACCESS_EXTERNAL_FILES"):
            return False
        version = full["version"]
        if (type(version) is not list or len(version) != 3 or any(type(v) is not int for v in version)
                or BUILDS.get(tuple(version)) != full["build_hash"]
                or full["blender_version"] not in {".".join(map(str, version)), ".".join(map(str, version)) + " LTS"}):
            return False
        display, binding = full["private_display"], full["private_display_binding"]
        if (type(display) is not dict or type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"}
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= 16384
                or display.get("manifest_path") != binding["path"] or display.get("manifest_sha256") != binding["sha256"]
                or type(display.get("manifest")) is not dict
                or any(display["manifest"].get(key) is not True for key in ("input_disabled", "owned_process", "tcp_disabled"))):
            return False
        resources = full["resources"]
        if (type(resources) is not dict or set(resources) != {"available_memory_bytes", "available_disk_bytes"}
                or any(type(value) is not int for value in resources.values())
                or resources["available_memory_bytes"] < 8 * 1024**3
                or resources["available_disk_bytes"] < 2 * 1024**3):
            return False
        rows, sent, wire, terminal = (full[key] for key in ("cases", "sent", "wire", "terminal"))
        if (any(type(items) is not list or len(items) != len(CASES) for items in (rows, sent, wire, terminal))
                or [row.get("name") for row in rows] != list(CASES)
                or len({item.get("id") for item in sent}) != len(CASES)):
            return False
        for name, row, request, delivered, original in zip(CASES, rows, sent, wire, terminal, strict=True):
            if (type(row) is not dict or set(row) != {"name", "handler_entered", "components", "captured", "observations",
                    "approved_root_retained", "failure", "route_entries", "root_read_entries"}
                    or row["name"] != name or row["handler_entered"] is not True or row["captured"] is not True
                    or type(row["components"]) is not dict or set(row["components"]) != set(COMPONENTS)
                    or any(value is not True for value in row["components"].values())
                    or set(request) != {"id", "case"} or request["case"] != name
                    or type(request["id"]) is not str or len(request["id"]) != 32
                    or any(c not in "0123456789abcdef" for c in request["id"])
                    or set(delivered) != {"id", "response", "sha256"} or delivered["id"] != request["id"]
                    or hashlib.sha256(canonical(delivered["response"])).hexdigest() != delivered["sha256"]
                    or set(original) != {"id", "completed", "state", "response"} or original["id"] != request["id"]
                    or original["completed"] is not True or original["state"] != "completed"
                    or canonical(original["response"]) != canonical(delivered["response"])):
                return False
            response = delivered["response"]
            if (type(response) is not dict or set(response) != {"id", "ok", "protocol_version", "timestamp", "result" if name == "positive_repeated" else "error"}
                    or response.get("id") != request["id"] or type(response.get("ok")) is not bool
                    or response.get("protocol_version") != "1.0" or type(response.get("timestamp")) is not str):
                return False
            if any(type(row[key]) is not int or row[key] < 0 for key in ("route_entries", "root_read_entries")):
                return False
            if name == "positive_repeated":
                result = response.get("result")
                if (type(result) is not dict or set(result) != {"observed", "operation"}
                        or type(result["operation"]) is not dict
                        or set(result["operation"]) != {"operation_id", "undo_boundary_created", "undo_boundary_finalized"}
                        or any(result["operation"][key] is not False for key in ("undo_boundary_created", "undo_boundary_finalized"))):
                    return False
                identifier = result["operation"]["operation_id"]
                if (type(identifier) is not str or len(identifier) != 13 or not identifier.startswith("op_")
                        or any(c not in "0123456789abcdef" for c in identifier[3:])):
                    return False
                if (response["ok"] is not True or response.get("result", {}).get("observed") is not True
                        or row["failure"] is not None or row["observations"] != ["original", "original", "original"]
                        or row["approved_root_retained"] is not True or row["root_read_entries"] != 3
                        or row["route_entries"] != 4):
                    return False
            else:
                failure = row["failure"]
                if (response["ok"] is not False or response.get("error", {}).get("code") != EXPECTED[name]
                        or type(failure) is not dict or failure.get("code") != EXPECTED[name]):
                    return False
                if name == "manual_root_drift":
                    if (failure.get("reason") != "ROOT_APPROVAL_VALUE_CHANGED" or row["observations"] != ["original"]
                            or row["approved_root_retained"] is not True or row["root_read_entries"] != 2
                            or row["route_entries"] != 3):
                        return False
                elif (row["observations"] != [] or row["approved_root_retained"] is not None
                        or row["root_read_entries"] != 0 or row["route_entries"] != 1):
                    return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return False


class Fixture:
    def __init__(self, bpy, options, attestation):
        self.bpy, self.options, self.display = bpy, options, attestation
        self.folder, self.path = options.bridge_bundle, options.bridge_bundle / "registered_route.json"
        self.sources = fingerprints()
        self.binary = ordinary_file(Path(bpy.app.binary_path).resolve(), 1024**3)
        self.binary.pop("bytes")
        self.controls, self.done = queue.Queue(), threading.Event()
        self.rows, self.sent, self.wire, self.owners = {}, [], [], {}
        self.worker_error = None
        self.runtime = self.prefs = None
        self.original_profile = None
        self.active = None
        self.deadline = time.monotonic() + 270
        self.roots = (self.folder / "approved-root", self.folder / "changed-root")
        self.data = {"schema": SCHEMA, "profile": PROFILE, "phase": PHASE, "completed": False,
            "version": list(bpy.app.version), "build_hash": bpy.app.build_hash.decode(), "blender_version": bpy.app.version_string,
            "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": os.getpid(), "binary": self.binary,
            "source_fingerprints": self.sources, "private_display": attestation,
            "private_display_binding": ordinary_file(Path(attestation["manifest_path"]), 16384)}

    def flush(self):
        self.path.write_bytes(canonical(self.data))
        os.chmod(self.path, 0o600)

    def observe(self, frame, event, argument):
        if event == "return" and frame.f_code is self.try_start_code and argument is True:
            owner = frame.f_locals["self"]
            if owner.request.method == METHOD:
                self.owners[owner.request.id] = owner
        if self.active is not None and event == "call":
            if frame.f_code is self.route_code:
                self.active["route_entries"] += 1
            if frame.f_code is self.read_code:
                self.active["root_read_entries"] += 1

    def components(self, context):
        from blender_codex_bridge import runtime as module
        from blender_codex_bridge.command_queue import QueuedRequest
        runtime = self.runtime
        owner = context.check_cancelled.__self__
        facts = {"canonical_runtime": module.get_runtime() is runtime and runtime._registered,
            **{name: getattr(context, name) is getattr(runtime, name) for name in
               ("state", "registry", "permissions", "checkpoints", "jobs")},
            "storage_service": context.storage_snapshots is runtime.storage_snapshots,
            "storage_origin": runtime.storage_snapshots is runtime._storage_snapshot_origin,
            "executor_storage": runtime.executor.storage_snapshots is runtime.storage_snapshots,
            "original_factory": runtime.jobs.context_factory is self.factory and self.factory.__code__ is self.factory_code
                and self.factory.__closure__[0].cell_contents is runtime,
            "queued_request": type(owner) is QueuedRequest and owner is self.owners[context.request_id]
                and owner.state == "running" and owner.request.id == context.request_id,
            "main_thread": threading.current_thread() is threading.main_thread()}
        assert all(facts.values()) and context.jobs is not None
        return facts

    def handler(self, context, params):
        from blender_codex_bridge.storage_snapshot_approval import LocalRootApproval
        name = params["case"]
        assert set(params) == {"case"} and name in CASES
        row = self.rows[name]
        row["handler_entered"], row["components"] = True, self.components(context)
        self.active = row
        try:
            value = LocalRootApproval.capture(context)
            row["captured"] = True
            if name == "paused_after_capture":
                self.runtime.state.set_paused(True)
            elif name == "emergency_after_capture":
                self.runtime.state.set_emergency_stopped(True)
            approved = value.authorize()
            assert approved.approved_root == str(self.roots[0])
            row["observations"].append("original")
            row["approved_root_retained"] = True
            if name == "manual_root_drift":
                self.prefs.project_directory = str(self.roots[1])
                approved.read_current()
                raise AssertionError("Changed local root was adopted")
            for _ in range(2):
                assert approved.read_current() == str(self.roots[0])
                row["observations"].append("original")
            return {"observed": True}
        except BaseException as error:
            if name == "manual_root_drift" and row["approved_root_retained"] is not None:
                row["approved_root_retained"] = approved.approved_root == str(self.roots[0])
            row["failure"] = exception_receipt(error)
            raise
        finally:
            self.active = None

    def control(self, name):
        event, result = threading.Event(), {}
        self.controls.put((name, event, result))
        assert event.wait(30) and result.get("ok") is True

    def worker(self, port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=60) as client, client.makefile("rb") as stream:
                for name in CASES:
                    self.control(name)
                    identifier = os.urandom(16).hex()
                    self.sent.append({"id": identifier, "case": name})
                    client.sendall(canonical({"protocol_version": "1.0", "id": identifier, "method": METHOD,
                        "params": {"case": name}, "timeout_ms": 60000}) + b"\n")
                    raw = stream.readline(256*1024)
                    assert raw.endswith(b"\n") and len(raw) < 256*1024
                    response = json.loads(raw)
                    assert response.get("id") == identifier
                    self.wire.append({"id": identifier, "response": response,
                                      "sha256": hashlib.sha256(canonical(response)).hexdigest()})
                    assert response["ok"] is (EXPECTED[name] is None), response
                    if EXPECTED[name] is not None:
                        assert response["error"]["code"] == EXPECTED[name], response
        except BaseException as error:
            self.worker_error = exception_receipt(error)
        finally:
            self.done.set()

    def setup(self):
        from blender_codex_bridge import runtime as module
        from blender_codex_bridge import storage_snapshot_approval as approval
        from blender_codex_bridge.command_queue import QueuedRequest
        from blender_codex_bridge.permissions import Permission
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.storage_snapshot import available_memory_facts
        memory = available_memory_facts()["available_memory_bytes"]
        disk = os.statvfs(self.folder)
        available_disk = disk.f_bavail * disk.f_frsize
        self.data["resources"] = {"available_memory_bytes": memory, "available_disk_bytes": available_disk}
        assert memory >= 8 * 1024**3 and available_disk >= 2 * 1024**3
        self.bpy.context.preferences.use_preferences_save = False
        self.bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        self.runtime, self.prefs = module.get_runtime(), get_preferences()
        assert self.runtime._registered and self.prefs is not None
        for root in self.roots:
            root.mkdir(mode=0o700)
        self.runtime.registry.register(METHOD, self.handler, modifies=True,
            automatic_checkpoint=False, batchable=False, permissions=(Permission.EDIT_SCENE,))
        self.factory = self.runtime.jobs.context_factory
        self.factory_code = self.factory.__code__
        assert self.factory_code in module._RUNTIME_CONSTRUCTOR_CODE.co_consts
        self.try_start_code = QueuedRequest.try_start.__code__
        self.route_code, self.read_code = approval._route.__code__, approval.LocalRootApproval._read_root.__code__
        self.original_profile = sys.getprofile()
        assert all(value is None for value in (self.original_profile, threading.getprofile(), sys.gettrace(), threading.gettrace()))
        sys.setprofile(self.observe)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        self.runtime.start_server("127.0.0.1", port, request_timeout=60)
        threading.Thread(target=self.worker, args=(port,), daemon=True, name="OwnedRootApprovalJSONWorker").start()
        self.bpy.app.timers.register(self.tick, first_interval=.01)

    def tick(self):
        try:
            assert time.monotonic() < self.deadline, "Owned root approval fixture deadline"
            while True:
                try:
                    name, event, result = self.controls.get_nowait()
                except queue.Empty:
                    break
                try:
                    self.runtime.state.set_paused(False)
                    self.runtime.state.set_emergency_stopped(False)
                    self.prefs.allow_inspect_scene = self.prefs.allow_save_project = self.prefs.allow_external_files = True
                    self.prefs.project_directory = str(self.roots[0])
                    denied = {"denied_inspect": "allow_inspect_scene", "denied_save": "allow_save_project",
                              "denied_external_files": "allow_external_files"}.get(name)
                    if denied:
                        setattr(self.prefs, denied, False)
                    self.rows[name] = {"name": name, "handler_entered": False, "components": {}, "captured": False,
                        "observations": [], "approved_root_retained": None, "failure": None,
                        "route_entries": 0, "root_read_entries": 0}
                    result["ok"] = True
                finally:
                    event.set()
            if not self.done.is_set():
                return .01
            if self.worker_error is not None:
                raise AssertionError("Owned worker failed")
            from blender_codex_bridge import runtime as module
            assert module.native_save_permission_provider_intact()
            self.runtime.stop_server()
            self.runtime.executor.stop()
            sys.setprofile(self.original_profile)
            self.data.update(completed=True, source_unchanged=fingerprints() == self.sources,
                cases=[self.rows[name] for name in CASES], sent=self.sent, wire=self.wire,
                terminal=[{"id": item["id"], "completed": self.owners[item["id"]].completed.is_set(),
                    "state": self.owners[item["id"]].state,
                    "response": self.owners[item["id"]].response.to_dict()} for item in self.sent],
                fixture_only_registration=True, original_preferences_provider=True,
                python_disabled=self.prefs.allow_execute_python is False,
                services_stopped=not self.runtime.server.running and self.runtime.state.connected_clients == 0
                    and self.runtime.command_queue.pending_count == 0 and not self.runtime.state.is_executing,
                observer_restored=sys.getprofile() is self.original_profile,
                case_deadline_seconds=300, limitations=dict.fromkeys(LIMITATIONS, False),
                capture_scope="pre-provider native route metadata/preferences-owner getters; project_directory value after helper authorization",
                fixture_metadata_permission="EDIT_SCENE; helper separately requires INSPECT_SCENE,SAVE_PROJECT,ACCESS_EXTERNAL_FILES")
            assert validate(self.data, sources=self.sources, binary=self.binary,
                process_instance=self.data["process_instance"], process_id=os.getpid())
            self.flush()
            payload = {key: self.data[key] for key in ("schema", "profile", "phase", "completed", "version", "build_hash",
                "blender_version", "binary", "process_instance", "process_id", "source_fingerprints", "private_display_binding")}
            payload["full_receipt"] = ordinary_file(self.path, MAX_REPORT)
            print(MARKER + canonical(payload).decode(), flush=True)
            from scripts.blender_artist_sidebar_smoke import owned_process_exit
            owned_process_exit(0)
        except BaseException as error:
            self.fail(error)
        return None

    def fail(self, error):
        self.data.update(completed=False, failure=exception_receipt(error), worker_failure=self.worker_error,
                         cached_cases=list(self.rows.values()), wire=self.wire, sent=self.sent)
        if self.runtime is not None:
            self.runtime.server.stop()
            self.runtime.executor.stop()
        sys.setprofile(self.original_profile)
        self.flush()
        print(canonical(self.data["failure"]).decode(), file=sys.stderr, flush=True)
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        owned_process_exit(1)


def main(argv=None):
    assert threading.current_thread() is threading.main_thread()
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv and sys.dont_write_bytecode
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    assert all(Path(os.environ[key]).resolve(strict=True) == folder for key in ("TEMP", "TMP", "TMPDIR"))
    assert Path.cwd().resolve() == folder / "working"
    sys.path[:0] = [str(ROOT), str(ROOT / "addon")]
    from scripts.blender_artist_sidebar_smoke import private_display_manifest
    attestation = private_display_manifest()
    import bpy
    assert sys.platform == "linux" and not bpy.app.background and bpy.data.filepath == ""
    assert BUILDS.get(tuple(bpy.app.version)) == bpy.app.build_hash.decode()
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=(PHASE,), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    options = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if argv is None else argv)
    fixture = Fixture(bpy, options, attestation)
    def begin():
        try:
            fixture.setup()
        except BaseException as error:
            fixture.fail(error)
    bpy.app.timers.register(begin, first_interval=.01)


if __name__ == "__main__":
    main()
