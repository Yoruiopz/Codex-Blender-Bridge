"""Private actual-queue snapshot/cleanup prerequisite, not a shipping caller.

An empty, fixture-owned registry uses one already allowed method name. No
shipping registration, native method, executor or lifecycle service is replaced.
The JSON worker never accesses Blender. Evidence copies are not backups.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
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
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
cleanup = importlib.import_module("scripts.blender_storage_snapshot_cleanup_smoke")
gateway = cleanup.gateway
CASE = "storage_snapshot_dispatch"
SCHEMA = "storage_snapshot_actual_dispatch_v1"
PROFILE = "STOCK_OWNED_STORAGE_ACTUAL_DISPATCH_V1"
REQUEST_BINDING = "ACTUAL_QUEUED_EXECUTOR_LOOPBACK_REQUEST"
PHASES = ("success_denial", "stops", "failures")
MARKERS = {phase: "BLENDER_STORAGE_DISPATCH_" + phase.upper() + "_OK " for phase in PHASES}
CASES = {"success_denial": ("success", "deny_inspect", "deny_save", "deny_external", "deny_capture"),
         "stops": ("cancel_after_writer", "disconnect_after_writer", "pause_after_unlink"),
         "failures": ("unlink_failure", "file_replace")}
METHOD = "simulation.cache_preview"
MAX_REPORT = 8 * 1024**2
FALSE_FLAGS = ("shipping_caller_qualified", "runtime_retention_qualified", "full_authored_preservation_qualified",
               "durable_backup_qualified", "current_pixels_backup_qualified", "cache_pairing_qualified",
               "native_calls_preemptible", "windows_qualified", "installed_package_qualified",
               "native_memory_cap_claimed", "hidden_Main_passivity_claimed", "full_executor_after_stop_qualified")


def source_names(root=ROOT):
    return ("scripts/blender_storage_snapshot_dispatch_smoke.py", *cleanup.source_names(root))


def source_fingerprints():
    return {name: gateway.ordinary_file(ROOT / name, 1024**2)["sha256"] for name in source_names()}


def response_valid(value, identifier):
    return (type(value) is dict and value.get("id") == identifier and value.get("protocol_version") == "1.0"
            and type(value.get("ok")) is bool and ((value["ok"] and "result" in value and "error" not in value)
                or (not value["ok"] and type(value.get("error")) is dict and "result" not in value)))


def validate_full(full, *, phase, process_instance, sources, binary, process_id):
    """Require nonvacuous actual queue/transport facts and exact phase outcomes."""
    try:
        expected = {"schema": SCHEMA, "profile": PROFILE, "phase": phase, "completed": True,
                    "process_instance": process_instance, "process_id": process_id,
                    "source_fingerprints": sources, "binary": binary, "source_unchanged": True,
                    "actual_dispatch_qualified": True, "transport_qualified": True,
                    "request_binding_kind": REQUEST_BINDING,
                    "stop_observation_scope": "STORAGE_OPERATION_AND_CLEANUP_ONLY",
                    "native_undo_pushes": 0, "hooks_restored": True, "services_stopped": True}
        if (type(full) is not dict or phase not in PHASES or type(process_id) is not int or process_id <= 0
                or any(type(full.get(k)) is not type(v) or full.get(k) != v for k, v in expected.items())
                or any(full.get(flag) is not False for flag in FALSE_FLAGS)):
            return False
        rows, wire, sent, terminal = full["cases"], full["wire"], full["sent"], full["terminal"]
        if (type(rows) is not list or [row.get("name") for row in rows] != list(CASES[phase])
                or type(wire) is not list or not 2 <= len(wire) <= 128
                or type(full["request_ids"]) is not list or len(set(full["request_ids"])) != len(full["request_ids"])
                or type(full["dispatch"]) is not list or not full["dispatch"] or type(sent) is not list
                or type(terminal) is not list):
            return False
        if (any(type(item) is not dict or set(item) != {"id", "action", "case"} for item in sent)
                or [item["id"] for item in sent] != full["request_ids"]
                or [identifier for row in rows for identifier in row["requests"]] != full["request_ids"]):
            return False
        wire_by_id, sent_by_id, terminal_by_id = {}, {item["id"]: item for item in sent}, {}
        observed = set()
        for row in wire:
            if (type(row) is not dict or set(row) != {"id", "response", "sha256"}
                    or not response_valid(row["response"], row["id"]) or row["id"] in observed
                    or hashlib.sha256(gateway.canonical(row["response"])).hexdigest() != row["sha256"]):
                return False
            observed.add(row["id"])
            wire_by_id[row["id"]] = row["response"]
        missing = {row["requests"][0] for row in rows if row["name"] == "disconnect_after_writer"}
        if observed != set(full["request_ids"]) - missing:
            return False
        for row in terminal:
            if (type(row) is not dict or set(row) != {"id", "completed", "state", "response"}
                    or row["id"] in terminal_by_id or row["completed"] is not True or row["state"] != "completed"
                    or not response_valid(row["response"], row["id"])
                    or (row["id"] in wire_by_id and row["response"] != wire_by_id[row["id"]])):
                return False
            terminal_by_id[row["id"]] = row["response"]
        dispatch_ids = []
        for row in full["dispatch"]:
            if (type(row) is not dict or set(row) != {"id", "action", "case", "queued_running", "actual_closure", "main_thread"}
                    or row["action"] not in {"capture", "cleanup", "inspect"} or row["case"] not in CASES[phase]
                    or any(row[key] is not True for key in ("queued_running", "actual_closure", "main_thread"))):
                return False
            dispatch_ids.append(row["id"])
            if sent_by_id.get(row["id"]) != {key: row[key] for key in ("id", "action", "case")}:
                return False
        if len(set(dispatch_ids)) != len(dispatch_ids) or any(identifier not in full["request_ids"] for identifier in dispatch_ids):
            return False
        if set(dispatch_ids) != set(terminal_by_id):
            return False
        for row in rows:
            name = row["name"]
            actions = ["capture", "cleanup", "inspect"]
            if name == "deny_capture":
                actions = ["capture", "inspect"]
            elif name.startswith("deny_") or name in {"pause_after_unlink", "unlink_failure"}:
                actions = ["capture", "cleanup", "cleanup", "inspect"]
            case_sent = [{"id": identifier, "action": action, "case": name} for identifier, action in zip(row["requests"], actions, strict=True)]
            if [sent_by_id[identifier] for identifier in row["requests"]] != case_sent:
                return False
            denied_index = 0 if name == "deny_capture" else 1 if name.startswith("deny_") else None
            expected_dispatch = [item["id"] for index, item in enumerate(case_sent) if index != denied_index]
            if [item["id"] for item in full["dispatch"] if item["case"] == name] != expected_dispatch:
                return False
            derived = []
            for item in case_sent:
                response = wire_by_id.get(item["id"], terminal_by_id.get(item["id"]))
                if response is None:
                    return False
                if not response["ok"]:
                    derived.append(response["error"]["code"])
                elif item["action"] == "cleanup":
                    receipt = response["result"]["cleanup"]
                    if not cleanup.plain_cleanup(receipt):
                        return False
                    derived.append("complete" if receipt["complete"] else "retained_unknown")
                elif response["result"].get({"inspect": "healthy", "capture": "captured"}[item["action"]]) is not True:
                    return False
            if derived != row["outcomes"]:
                return False
            if (row["before"] != row["after"] or row["source_preserved"] is not True
                    or not gateway.valid_source_snapshot(row["before"]["home"])
                    or type(row["requests"]) is not list or not row["requests"]
                    or not set(row["requests"]).issubset(full["request_ids"])
                    or type(row["events"]) is not list or len(row["events"]) > 8192
                    or type(row["healthy_after"]) is not bool or row["healthy_after"] is not True):
                return False
            for event in row["events"]:
                if (type(event) is not dict or set(event) != {"event", "name", "after_stop"}
                        or type(event["after_stop"]) is not bool
                        or event["event"] not in {"c_call", "c_return", "c_exception", "native_read", "provider"}
                        or event["name"] not in {*cleanup.OS_NAMES, "writer", "source_or_parser", "require", "native_check"}
                        or (event["after_stop"] and event["name"] != "close")):
                    return False
            if name == "deny_capture":
                if row["journal"] is not None or row["copy"] is not None or row["events"] or row["handler_entries"] != 1:
                    return False  # Only the later healthy inspect may enter.
                if row["outcomes"] != ["PERMISSION_DENIED"]:
                    return False
                continue
            if any(sum(event["event"] == kind and event["name"] == "writer" for event in row["events"]) != 1
                   for kind in ("c_call", "c_return")):
                return False
            if name in {"cancel_after_writer", "disconnect_after_writer", "pause_after_unlink"} and not any(
                    event["after_stop"] and event["name"] == "close" for event in row["events"]):
                return False
            if name == "unlink_failure" and not any(event["event"] == "c_exception" and event["name"] == "unlink" for event in row["events"]):
                return False
            journal = row["journal"]
            if (type(journal) is not dict or len(journal["snapshots"]) != 1 or not cleanup.file_record(row["copy"]["copy"])
                    or not cleanup.plain_cleanup(row["cleanup"])):
                return False
            cell = journal["snapshots"][0]
            unknown = name in {"cancel_after_writer", "disconnect_after_writer"}
            if (cell["native_entered"] is not True or cell["native_returned"] is not True
                    or cell["consumed"] is not (not unknown) or cell["parser_entered"] is not (not unknown)
                    or row["cleanup"]["original_file_identity_known"] is not (not unknown)
                    or (row["copy"]["original_binding"] is None) is not unknown):
                return False
            if unknown:
                if (row["cleanup"]["retained_unknown"] is not True or row["cleanup"]["unlink_entered"] is not False
                        or cell["file_identity"] != [] or row["outcomes"] != ["TIMEOUT", "retained_unknown"]
                        or row["stop_applied"] is not True):
                    return False
            elif name == "file_replace":
                if row["outcomes"] != ["NOT_IMPLEMENTED"] or row["cleanup"]["unlink_entered"] is not False:
                    return False
            else:
                expected_outcomes = {"success": ["complete"], "deny_inspect": ["PERMISSION_DENIED", "complete"],
                                     "deny_save": ["PERMISSION_DENIED", "complete"], "deny_external": ["PERMISSION_DENIED", "complete"],
                                     "pause_after_unlink": ["AGENT_PAUSED", "complete"], "unlink_failure": ["OPERATION_FAILED", "complete"]}[name]
                if row["outcomes"] != expected_outcomes or row["cleanup"]["complete"] is not True:
                    return False
            if name in {"pause_after_unlink", "unlink_failure"} and row["stop_applied"] is not True:
                return False
        return True
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError):
        return False


def validate_retained(full, bundle):
    """Cold-read copies bound to original receipts, never mint cleanup authority."""
    import stat

    def integers(value, length):
        return type(value) is list and len(value) == length and all(type(item) is int and item >= 0 for item in value)

    def directory(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise ValueError("STORAGE_DISPATCH_DIRECTORY_METADATA")
        return info

    def regular(path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError("STORAGE_DISPATCH_FILE_METADATA")
        return info

    reader_name = "_bcb_dispatch_cold_sdna"
    spec = importlib.util.spec_from_file_location(reader_name, ROOT / "addon/blender_codex_bridge/blend_storage_sdna.py")
    if spec is None or spec.loader is None:
        raise ValueError("STORAGE_DISPATCH_READER_REQUIRED")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(reader_name)
    sys.modules[reader_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(reader_name, None)
        else:
            sys.modules[reader_name] = previous
    names = module.CYCLES_NAMES if full["version"][0] == 4 else module.CYCLES_502_NAMES
    for row in full["cases"]:
        prefix = full["phase"] + "-" + row["name"]
        root, sentinel = bundle / (prefix + "-owned"), bundle / (prefix + "-sentinel.bin")
        copy_root = bundle / (prefix + "-evidence")
        root_info = directory(root)
        directory(copy_root)
        sentinel_info = regular(sentinel)
        if (row["owned_root"] != str(root) or stat.S_IMODE(sentinel_info.st_mode) != 0o600
                or gateway.ordinary_file(sentinel, 65536) != row["sentinel"]
                or sentinel.read_bytes() != b"PROTECTED INDEPENDENT SENTINEL"):
            raise ValueError("STORAGE_DISPATCH_SENTINEL_CHANGED")
        targets = row["raw_targets"]
        if (type(targets) is not list or len(targets) != 2 or targets[0] == targets[1]
                or any(type(target) is not dict or set(target) != {"scene_name", "view_layer_name"}
                       or any(type(value) is not str or not value or len(value) > 128 for value in target.values())
                       for target in targets)
                or targets != row["before"]["targets"] or targets != row["after"]["targets"]):
            raise ValueError("STORAGE_DISPATCH_TARGET_BINDING")
        if row["name"] == "deny_capture":
            if list(root.iterdir()) or list(copy_root.iterdir()):
                raise ValueError("STORAGE_DISPATCH_DENIAL_CREATED_ARTIFACT")
            continue
        copy = row["copy"]
        if (type(copy) is not dict or set(copy) != {"owner_index", "original_path", "original_identity", "original_binding",
                                                "original_sha256", "copy", "retained_parser"}
                or type(copy["owner_index"]) is not int or copy["owner_index"] != 0
                or {path.name for path in copy_root.iterdir()} != {"0.blend"}):
            raise ValueError("STORAGE_DISPATCH_COPY_INVENTORY")
        path = copy_root / "0.blend"
        info = regular(path)
        if stat.S_IMODE(info.st_mode) != 0o600 or not cleanup.file_record(copy["copy"]):
            raise ValueError("STORAGE_DISPATCH_COPY_METADATA")
        before_copy = gateway.ordinary_file(path, 1024**3)
        if before_copy != copy["copy"] or copy["original_sha256"] != before_copy["sha256"]:
            raise ValueError("STORAGE_DISPATCH_COPY_CHANGED")
        snapshots = row["journal"]["snapshots"]
        if type(snapshots) is not list or len(snapshots) != 1 or type(snapshots[0]) is not dict:
            raise ValueError("STORAGE_DISPATCH_ORIGINAL_JOURNAL")
        cell = snapshots[0]
        child = Path(cell["directory"])
        leaf = child.name
        receipt = row["cleanup"]
        unknown = row["name"] in {"cancel_after_writer", "disconnect_after_writer"}
        identity, binding = copy["original_identity"], copy["original_binding"]
        if (cell["root"] != str(root) or child.parent != root or len(leaf) != 44 or not leaf.startswith("bcb-storage-")
                or any(ch not in "0123456789abcdef" for ch in leaf[12:])
                or cell["filepath"] != str(child / "snapshot.blend") or copy["original_path"] != cell["filepath"]
                or not integers(cell["root_identity"], 2) or cell["root_identity"] != [root_info.st_dev, root_info.st_ino]
                or not integers(cell["directory_identity"], 2)
                or not integers(identity, 4) or not 0 < identity[2] <= 1024**3 or identity[2] != before_copy["bytes"]
                or not cleanup.plain_cleanup(receipt) or receipt["root"] != str(root) or receipt["directory_leaf"] != leaf
                or receipt["original_file_identity_known"] is not (not unknown)):
            raise ValueError("STORAGE_DISPATCH_ORIGINAL_BINDING")
        if unknown:
            if (binding is not None or cell["file_identity"] != [] or cell["file_bytes"] is not None
                    or cell["file_sha256"] is not None or receipt["retained_unknown"] is not True
                    or receipt["unlink_entered"] is not False or receipt["complete"] is not False):
                raise ValueError("STORAGE_DISPATCH_UNKNOWN_OWNER_ADOPTED")
        elif (not integers(binding, 8) or binding[:2] != identity[:2] or binding[2] != os.geteuid()
                or binding[3] > 0o7777 or binding[4] != 1 or binding[5:7] != identity[2:]
                or not integers(cell["file_identity"], 4) or cell["file_identity"] != identity
                or type(cell["file_bytes"]) is not int or cell["file_bytes"] != identity[2]
                or cell["file_sha256"] != before_copy["sha256"]):
            raise ValueError("STORAGE_DISPATCH_KNOWN_OWNER_CHANGED")
        if type(copy["retained_parser"]) is not list or len(copy["retained_parser"]) != 2:
            raise ValueError("STORAGE_DISPATCH_COPY_TARGETS")
        for target, proof in zip(targets, copy["retained_parser"], strict=True):
            actual = module.inspect_view_layer_storage(str(path), target["scene_name"], target["view_layer_name"], allowed_names=names)
            if proof != {"target": target, "result": actual}:
                raise ValueError("STORAGE_DISPATCH_COPY_PARSE")
        if gateway.ordinary_file(path, 1024**3) != before_copy:
            raise ValueError("STORAGE_DISPATCH_COPY_CHANGED_DURING_PARSE")
        if receipt["complete"]:
            if child.exists() or list(root.iterdir()):
                raise ValueError("STORAGE_DISPATCH_CLEANUP_INCOMPLETE")
        else:
            child_info = directory(child)
            if {item.name for item in root.iterdir()} != {leaf} or cell["directory_identity"] != [child_info.st_dev, child_info.st_ino]:
                raise ValueError("STORAGE_DISPATCH_RETAINED_DIRECTORY_CHANGED")
            original = child / ("snapshot.blend-original" if row["name"] == "file_replace" else "snapshot.blend")
            original_info = regular(original)
            if ([original_info.st_dev, original_info.st_ino, original_info.st_size, original_info.st_mtime_ns] != identity
                    or gateway.ordinary_file(original, 1024**3)["sha256"] != copy["original_sha256"]):
                raise ValueError("STORAGE_DISPATCH_RETAINED_ORIGINAL_CHANGED")
            expected_names = {"snapshot.blend"}
            if row["name"] == "file_replace":
                expected_names.add("snapshot.blend-original")
                foreign = Path(cell["filepath"])
                regular(foreign)
                if foreign.read_bytes() != b"FOREIGN REPLACEMENT":
                    raise ValueError("STORAGE_DISPATCH_REPLACEMENT_CHANGED")
            if {item.name for item in child.iterdir()} != expected_names:
                raise ValueError("STORAGE_DISPATCH_RETAINED_FOREIGN_ENTRY")
    return True


class NativeObserver(cleanup.FSObserver):
    def __init__(self, fixture, name, operation, events, context):
        super().__init__(fixture, name, operation, events)
        from blender_codex_bridge import storage_snapshot as adapter
        self.read_codes = {adapter._field.__code__, adapter._pointer.__code__, adapter._id.__code__, adapter.inspect_view_layer_storage.__code__}
        self.context = context

    def observe(self, frame, event, argument):
        if event == "call" and frame.f_code in self.read_codes:
            self.events.append({"event": "native_read", "name": "source_or_parser", "after_stop": self.stopped})
        if event in {"c_call", "c_return", "c_exception"} and self.operation is not None:
            native = self.operation.native
            if native is not None and argument is native.writer:
                self.events.append({"event": event, "name": "writer", "after_stop": self.stopped})
                if event == "c_return" and self.name in {"cancel_after_writer", "disconnect_after_writer"}:
                    if self.name == "cancel_after_writer":
                        from blender_codex_bridge.errors import BridgeError, ErrorCode
                        owner = self.context.check_cancelled.__self__
                        assert owner.cancel_pending(BridgeError(ErrorCode.TIMEOUT, "Owned fixture cooperative cancellation")) is False
                    else:
                        self.fixture.writer_returned.set()
                        assert self.fixture.worker_closed.wait(5)
                        assert self.context.request_lifecycle.connection.disconnected.wait(5)
                    self.stopped = self.applied = True
        super().observe(frame, event, argument)


class Client:
    def __init__(self, port, fixture):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.stream = self.socket.makefile("rb")
        self.fixture = fixture

    def send(self, action, name):
        identifier = os.urandom(16).hex()
        self.fixture.request_ids.append(identifier)
        self.fixture.sent.append({"id": identifier, "action": action, "case": name})
        self.socket.sendall(gateway.canonical({"protocol_version": "1.0", "id": identifier, "method": METHOD,
                                              "params": {"action": action, "case": name}, "timeout_ms": 60000}) + b"\n")
        return identifier

    def receive(self, identifier):
        raw = self.stream.readline(256 * 1024)
        assert raw.endswith(b"\n") and len(raw) < 256 * 1024
        result = json.loads(raw)
        assert response_valid(result, identifier)
        self.fixture.wire.append({"id": identifier, "response": result,
                                  "sha256": hashlib.sha256(gateway.canonical(result)).hexdigest()})
        return result

    def call(self, action, name):
        return self.receive(self.send(action, name))

    def close(self):
        # shutdown makes EOF observable even while the makefile owns an FD.
        self.socket.shutdown(socket.SHUT_RDWR)
        self.stream.close()
        self.socket.close()


class Fixture(cleanup.Fixture):
    def __init__(self, bpy, options, attestation):
        super().__init__(bpy, options, attestation)
        self.sources = source_fingerprints()
        self.data.update(schema=SCHEMA, profile=PROFILE, source_fingerprints=self.sources,
                         actual_dispatch_qualified=False, transport_qualified=False, request_binding_kind=REQUEST_BINDING,
                         stop_observation_scope="STORAGE_OPERATION_AND_CLEANUP_ONLY",
                         **dict.fromkeys(FALSE_FLAGS, False))
        self.controls, self.done = queue.Queue(), threading.Event()
        self.writer_returned, self.worker_closed = threading.Event(), threading.Event()
        self.request_ids, self.wire, self.dispatch = [], [], []
        self.sent, self.terminal, self.owners = [], [], {}
        self.rows, self.operations, self.journals = {}, {}, {}
        self.denied = set()
        self.worker_failure = None
        self.worker_close_failure = None
        self.server = self.executor = self.state = None
        self.deadline = time.monotonic() + 270

    def permissions(self):
        from blender_codex_bridge.permissions import Permission
        assert threading.current_thread() is threading.main_thread()
        required = {"INSPECT_SCENE", "SAVE_PROJECT", "ACCESS_EXTERNAL_FILES"}
        return {item.value: item.value in required and item.value not in self.denied for item in Permission}

    def handle(self, context, params):
        from blender_codex_bridge import storage_snapshot as adapter
        from blender_codex_bridge.command_queue import QueuedRequest
        from blender_codex_bridge.executor import MainThreadExecutor
        action, name = params.get("action"), params.get("case")
        assert set(params) == {"action", "case"} and name in CASES[self.options.bridge_phase]
        assert action in {"capture", "cleanup", "inspect"}
        owner = context.check_cancelled.__self__
        closure = context.check_final_request
        codes = tuple(code for code in MainThreadExecutor._invoke_owned.__code__.co_consts
                      if getattr(code, "co_freevars", None) == ("queued_owner",))
        assert (type(owner) is QueuedRequest and owner.state == "running" and owner.request.id == context.request_id
                and closure.__code__ in codes and closure.__globals__ is vars(importlib.import_module(MainThreadExecutor.__module__))
                and closure.__closure__[0].cell_contents is owner)
        self.dispatch.append({"id": context.request_id, "action": action, "case": name, "queued_running": True,
                              "actual_closure": True, "main_thread": threading.current_thread() is threading.main_thread()})
        self.owners[context.request_id] = owner
        row = self.rows[name]
        if action == "inspect":
            assert self.executor.registry.executing_mutators == 1  # This owned registration declares file mutation.
            return {"healthy": True}
        if action == "capture":
            operation = adapter.SnapshotOperation(context, self.bpy, self.scenes, row["owned_root"], self.journals[name])
            self.operations[name] = operation
            observer = NativeObserver(self, name, operation, row["events"], context)
            try:
                with observer:
                    operation.run().consume(context, self.bpy, self.scenes)
            finally:
                row["stop_applied"] = observer.applied
            return {"captured": True}
        operation = self.operations[name]
        attempts = row.get("cleanup_attempts", 0)
        row["cleanup_attempts"] = attempts + 1
        observer_name = {"pause_after_unlink": "stop_after_unlink"}.get(name, name) if attempts == 0 else "success"
        # The inherited observer only uses runtime.state for its pause actor.
        observer = NativeObserver(self, observer_name, operation, row["events"], context)
        try:
            with observer:
                receipt = adapter.cleanup_step(context, self.journals[name], operation.cleanup_owner)
        finally:
            row["stop_applied"] = row["stop_applied"] or observer.applied
        return {"cleanup": receipt}

    def control(self, action, name):
        event, result = threading.Event(), {}
        self.controls.put((action, name, event, result))
        assert event.wait(30), "Main-thread fixture control did not complete"
        assert result.get("ok"), result

    def main_control(self, action, name):
        from blender_codex_bridge import storage_snapshot as adapter
        from blender_codex_bridge.storage_snapshot_effects import SnapshotJournal
        if action == "begin":
            prefix = self.options.bridge_phase + "-" + name
            root, destination = self.folder / (prefix + "-owned"), self.folder / (prefix + "-evidence")
            root.mkdir(mode=0o700)
            destination.mkdir(mode=0o700)
            self.rows[name] = {"name": name, "owned_root": str(root), "raw_targets": self.data["target_pair"],
                               "before": self.complete_snapshot(), "events": [], "copy": None, "cleanup": None,
                               "stop_applied": False, "requests": [], "outcomes": [], "healthy_after": False,
                               "sentinel": cleanup.create_file(self.folder / (prefix + "-sentinel.bin"), b"PROTECTED INDEPENDENT SENTINEL")}
            self.journals[name] = SnapshotJournal(1)
            self.writer_returned.clear()
            self.worker_closed.clear()
            if name == "deny_capture":
                self.denied = {"SAVE_PROJECT"}
        elif action == "copy":
            prefix = self.options.bridge_phase + "-" + name
            self.rows[name]["copy"] = self.copy_native(self.operations[name], self.folder / (prefix + "-evidence"), 0)
        elif action == "deny":
            self.denied = {{"deny_inspect": "INSPECT_SCENE", "deny_save": "SAVE_PROJECT", "deny_external": "ACCESS_EXTERNAL_FILES"}[name]}
        elif action == "grant":
            self.denied.clear()
            self.state.paused = self.state.emergency_stopped = False
            if name == "unlink_failure":
                os.chmod(self.operations[name].cell.directory, 0o700)
        elif action == "replace":
            path = Path(self.operations[name].cell.filepath)
            path.rename(path.with_name(path.name + "-original"))
            cleanup.create_file(path, b"FOREIGN REPLACEMENT")
        elif action == "finish":
            row = self.rows[name]
            row["after"] = self.complete_snapshot()
            row["source_preserved"] = row["before"] == row["after"]
            row["handler_entries"] = sum(item["case"] == name for item in self.dispatch)
            for identifier in row["requests"]:
                owner = self.owners.get(identifier)
                if owner is not None:
                    assert owner.completed.is_set() and owner.response is not None
                    self.terminal.append({"id": identifier, "state": owner.state, "completed": owner.completed.is_set(),
                                          "response": owner.response.to_dict()})
            row["journal"] = None if name == "deny_capture" else self.journals[name].snapshot()
            if name != "deny_capture":
                row["cleanup"] = adapter.cleanup_receipt(self.journals[name], self.operations[name].cleanup_owner)
        else:
            raise AssertionError("Unknown fixture control")

    def worker(self, port):
        client = None
        try:
            client = Client(port, self)
            for name in CASES[self.options.bridge_phase]:
                self.control("begin", name)
                start = len(self.request_ids)
                outcomes = []
                if name == "disconnect_after_writer":
                    client.send("capture", name)
                    assert self.writer_returned.wait(30)
                    client.close()
                    client = None
                    self.worker_closed.set()
                    self.control("copy", name)
                    client = Client(port, self)
                    outcomes.append("TIMEOUT")
                else:
                    result = client.call("capture", name)
                    if name in {"cancel_after_writer", "deny_capture"}:
                        assert not result["ok"] and result["error"]["code"] == ("PERMISSION_DENIED" if name == "deny_capture" else "TIMEOUT")
                        outcomes.append(result["error"]["code"])
                    else:
                        assert result["ok"], result
                    if name != "deny_capture":
                        self.control("copy", name)
                if name.startswith("deny_") and name != "deny_capture":
                    self.control("deny", name)
                if name == "file_replace":
                    self.control("replace", name)
                if name != "deny_capture":
                    result = client.call("cleanup", name)
                    if name.startswith("deny_") or name in {"pause_after_unlink", "unlink_failure", "file_replace"}:
                        assert not result["ok"], result
                        outcomes.append(result["error"]["code"])
                    else:
                        assert result["ok"], result
                        outcomes.append("complete" if result["result"]["cleanup"]["complete"] else "retained_unknown")
                if name.startswith("deny_") or name in {"pause_after_unlink", "unlink_failure"}:
                    self.control("grant", name)
                    if name != "deny_capture":
                        result = client.call("cleanup", name)
                        assert result["ok"] and result["result"]["cleanup"]["complete"], result
                        outcomes.append("complete")
                healthy = client.call("inspect", name)
                assert healthy["ok"] and healthy["result"]["healthy"]
                self.rows[name].update(outcomes=outcomes, requests=self.request_ids[start:], healthy_after=True)
                self.control("finish", name)
        except BaseException as error:
            self.worker_failure = gateway.exception_receipt(error)
        finally:
            if client is not None:
                try:
                    client.close()
                except OSError as error:
                    self.worker_close_failure = gateway.exception_receipt(error)
                    if self.worker_failure is None:
                        self.worker_failure = self.worker_close_failure
            self.done.set()

    def setup_dispatch(self):
        from blender_codex_bridge.checkpoints import CheckpointManager
        from blender_codex_bridge.command_queue import CommandQueue
        from blender_codex_bridge.executor import MainThreadExecutor
        from blender_codex_bridge.permissions import Permission, PermissionManager
        from blender_codex_bridge.server import LocalBridgeServer
        from blender_codex_bridge.state import BridgeState
        from blender_codex_bridge.tool_registry import ToolRegistry
        self.setup()
        self.data["target_pair"] = self.complete_snapshot()["targets"]
        self.runtime.executor.stop()  # Factory-only add-on idle timer; no jobs.
        registry, self.state = ToolRegistry(enabled_toolsets=("simulation",)), BridgeState()
        registry.register(METHOD, self.handle, toolset="simulation", modifies=True, automatic_checkpoint=False,
                          batchable=False, permissions=(Permission.INSPECT_SCENE, Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES))
        self.executor = MainThreadExecutor(command_queue=CommandQueue(), registry=registry, state=self.state,
                                           permissions=PermissionManager(self.permissions), checkpoints=CheckpointManager())
        # The original cleanup observer's explicit pause actor needs this owned state.
        from types import SimpleNamespace
        self.runtime = SimpleNamespace(state=self.state)
        self.executor.start()
        self.server = LocalBridgeServer(submit=self.executor.submit, state=self.state)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        self.server.start("127.0.0.1", port, request_timeout=60)
        self.push_position = self.executor.checkpoints._window.position
        threading.Thread(target=self.worker, args=(port,), daemon=True, name="OwnedStorageDispatchJSONWorker").start()

    def cached_failure(self, error=None):
        """Retain already cached diagnostics; never inspect stopped services.

        Partial case rows and decoded wire data contain only fixture-created
        builtin values. In particular, do not read an operation, queue owner,
        Blender field, provider, resource sampler or source verifier here.
        """
        primary = self.worker_failure
        if primary is None:
            primary = gateway.exception_receipt(error)
        return {"completed": False, "actual_dispatch_qualified": False, "transport_qualified": False,
                "failure": primary, "worker_failure": self.worker_failure, "worker_close_failure": self.worker_close_failure,
                "cases": [self.rows[name] for name in CASES[self.options.bridge_phase] if name in self.rows],
                "wire": self.wire, "sent": self.sent, "terminal": self.terminal,
                "request_ids": self.request_ids, "dispatch": self.dispatch}

    def tick(self):
        try:
            assert time.monotonic() < self.deadline
            while True:
                try:
                    action, name, event, result = self.controls.get_nowait()
                except queue.Empty:
                    break
                try:
                    self.main_control(action, name)
                    result["ok"] = True
                finally:
                    event.set()
            if not self.done.is_set():
                return .01
            if self.worker_failure is not None:
                self.data.update(self.cached_failure())
                self.flush()
                self.finish(1)
                return None
            self.server.stop()
            self.executor.stop()
            assert self.state.connected_clients == 0 and not self.server.running
            assert self.executor.command_queue.pending_count == 0
            assert self.executor.registry.executing_mutators == 0 and not self.state.is_executing
            self.data.update(cases=[self.rows[name] for name in CASES[self.options.bridge_phase]], wire=self.wire,
                             sent=self.sent, terminal=self.terminal,
                             request_ids=self.request_ids, dispatch=self.dispatch, actual_dispatch_qualified=True,
                             transport_qualified=True, source_unchanged=source_fingerprints() == self.sources,
                             hooks_restored=all(value is None for value in (sys.getprofile(), threading.getprofile(), sys.gettrace(), threading.gettrace())),
                             native_undo_pushes=self.executor.checkpoints._window.position - self.push_position,
                             services_stopped=True, completed=True)
            assert validate_full(self.data, phase=self.options.bridge_phase, process_instance=self.data["process_instance"],
                                 sources=self.sources, binary=self.binary, process_id=os.getpid())
            assert validate_retained(self.data, self.folder)
            self.flush()
            marker = {key: self.data[key] for key in ("schema", "profile", "phase", "completed", "process_id", "process_instance",
                      "source_fingerprints", "binary", "version", "build_hash", "blender_version")}
            marker["full_receipt"] = gateway.ordinary_file(self.path, MAX_REPORT)
            print(MARKERS[self.options.bridge_phase] + gateway.canonical(marker).decode(), flush=True)
            self.finish(0)
        except BaseException as error:
            self.data.update(self.cached_failure(error))
            self.flush()
            self.finish(1)

    def finish(self, status):
        if self.server is not None:
            self.server.stop()
        if self.executor is not None:
            self.executor.stop()
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        owned_process_exit(status)

    def run(self):
        try:
            self.setup_dispatch()
            self.bpy.app.timers.register(self.tick, first_interval=.01)
        except BaseException as error:
            self.data.update(self.cached_failure(error))
            self.flush()
            self.finish(1)


def main(argv=None):
    assert threading.current_thread() is threading.main_thread()
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv and sys.dont_write_bytecode
    token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(token) == 32 and all(ch in "0123456789abcdef" for ch in token)
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        assert Path(os.environ[key]).resolve(strict=True) == folder
    for key in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        assert Path(os.environ[key]).resolve(strict=True).parent == folder
    assert Path.cwd().resolve(strict=True) == folder / "working"
    sys.path[:0] = [str(ROOT), str(ROOT / "addon")]
    from scripts.blender_artist_sidebar_smoke import private_display_manifest
    attestation = private_display_manifest()
    import bpy
    assert sys.platform == "linux" and not bpy.app.background and bpy.data.filepath == ""
    assert gateway.BUILDS.get(tuple(bpy.app.version)) == bpy.app.build_hash.decode()
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=PHASES, required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    options = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if argv is None else argv)
    fixture = Fixture(bpy, options, attestation)
    bpy.app.timers.register(fixture.run, first_interval=.01)


if __name__ == "__main__":
    main()
