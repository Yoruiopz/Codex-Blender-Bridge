"""Private owned-snapshot cleanup qualification; isolated native runner only.

Evidence copies are synthetic test evidence, never application recovery backups.
No public tool, source/native method or permission provider is replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import CodeType, FunctionType

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
gateway = importlib.import_module("scripts.blender_storage_snapshot_adapter_smoke")
CASE = "storage_snapshot_cleanup"
SCHEMA = "storage_snapshot_owned_cleanup_v1"
PROFILE = "STOCK_OWNED_STORAGE_CLEANUP_V1"
PHASES = ("success", "permission_denial", "ownership_tamper", "stop_retry", "partial_failure", "sixteen_captures")
MARKERS = {phase: "BLENDER_STORAGE_CLEANUP_" + phase.upper() + "_OK " for phase in PHASES}
CASES = {
    "success": ("consume_cleanup", "retire_before_consume", "malformed_cleanup", "idempotent"),
    "permission_denial": ("deny_inspect", "deny_save", "deny_external", "paused", "emergency"),
    "ownership_tamper": ("file_replace", "symlink", "hardlink", "root_replace", "child_replace", "extra_entry", "file_mode"),
    "stop_retry": ("stop_after_unlink", "unknown_after_writer_stop"),
    "partial_failure": ("unlink_failure", "rmdir_failure"),
    "sixteen_captures": ("sixteen_captures",),
}
MAX_REPORT = 8 * 1024**2
BUILDS = gateway.BUILDS
FALSE_FLAGS = (*(name for name in gateway.FALSE_FLAGS if name != "cleanup_qualified"),
    "restart_recovery_qualified", "history_retention_qualified", "large_image_qualified", "full_artist_workflow_qualified",
    "canonical_dispatch_qualified", "transport_qualified", "current_pixels_backup_qualified",
)
REQUEST_BINDING = "SOURCE_QUALIFIED_REPLICA_FRESH_QUEUED_REQUEST"
OS_NAMES = ("open", "close", "lstat", "fstat", "stat", "scandir", "unlink", "rmdir", "geteuid")
ERROR_FIELDS = {"type", "code", "reason", "message", "frames", "frames_truncated", "source_accessor", "stage"}
ROW_FIELDS = {"name", "owned_root", "raw_targets", "before", "after", "source_preserved", "sentinel",
              "journal_before", "journal_after", "evidence_copies", "cleanup_receipts", "errors", "events", "after_stop",
              "actor", "retirement", "outcome"}


def source_names(root=ROOT):
    return ("scripts/blender_storage_snapshot_cleanup_smoke.py", "scripts/blender_storage_snapshot_adapter_smoke.py",
            "scripts/run_blender_checks.py", "scripts/blender_artist_sidebar_smoke.py",
            *tuple(str(path.relative_to(root)) for path in sorted((root / "addon").rglob("*.py"))))


def source_fingerprints():
    return {name: gateway.ordinary_file(ROOT / name, 1024**2)["sha256"] for name in source_names()}


def canonical(value):
    return gateway.canonical(value)


def read_report(path):
    return gateway.read_report(path)


def create_file(path, data):
    """Fixture-only create-if-absent/fsync, never a product cleanup authority."""
    assert type(data) is bytes and 0 < len(data) <= 1024**3
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        cursor = 0
        while cursor < len(data):
            written = os.write(descriptor, data[cursor:cursor + 65536])
            assert written > 0
            cursor += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return gateway.ordinary_file(path, 1024**3)


def evidence_copy(source, destination):
    """Bind the native original, copy its bytes once and fsync before deletion."""
    before = gateway.ordinary_file(source, 1024**3)
    info = source.lstat()
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        actual = os.fstat(descriptor)
        assert (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns) == (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        assert actual.st_uid == os.geteuid() and actual.st_nlink == 1
        chunks, total = [], 0
        while chunk := os.read(descriptor, 65536):
            total += len(chunk)
            assert total <= 1024**3
            chunks.append(chunk)
        raw = b"".join(chunks)
        assert len(raw) == before["bytes"] and hashlib.sha256(raw).hexdigest() == before["sha256"]
        actual = os.fstat(descriptor)
        assert (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns) == (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    finally:
        os.close(descriptor)
    copied = create_file(destination, raw)
    assert copied["bytes"] == before["bytes"] and copied["sha256"] == before["sha256"]
    assert gateway.ordinary_file(source, 1024**3) == before
    return before, [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns], copied


def plain_cleanup(receipt):
    fields = {"schema", "root", "directory_leaf", "original_file_identity_known", "unlink_entered", "unlink_returned",
              "rmdir_entered", "rmdir_returned", "failed", "retained_unknown", "close_failed", "complete",
              "runtime_retention_qualified", "durable_backup_qualified", "current_pixels_backup_qualified",
              "hostile_same_uid_namespace_races_qualified"}
    return (type(receipt) is dict and set(receipt) == fields
            and receipt["schema"] == "owned_storage_cleanup_effects_v1"
            and all(type(value) is bool for key, value in receipt.items() if key not in {"schema", "root", "directory_leaf"})
            and type(receipt["root"]) is str and type(receipt["directory_leaf"]) is str
            and len(receipt["directory_leaf"]) == 44 and receipt["directory_leaf"].startswith("bcb-storage-")
            and all(ch in "0123456789abcdef" for ch in receipt["directory_leaf"][12:])
            and all(receipt[key] is False for key in ("runtime_retention_qualified", "durable_backup_qualified",
                                                      "current_pixels_backup_qualified", "hostile_same_uid_namespace_races_qualified"))
            and (not receipt["unlink_returned"] or receipt["unlink_entered"])
            and (not receipt["rmdir_returned"] or receipt["rmdir_entered"])
            and receipt["complete"] is (receipt["rmdir_returned"] and not receipt["close_failed"]))


def file_record(value):
    return (type(value) is dict and set(value) == {"path", "bytes", "sha256"}
            and type(value["path"]) is str and type(value["bytes"]) is int and 0 < value["bytes"] <= 1024**3
            and type(value["sha256"]) is str and len(value["sha256"]) == 64
            and all(ch in "0123456789abcdef" for ch in value["sha256"]))


def expected_outcome(name):
    if name in {"consume_cleanup", "idempotent", "sixteen_captures"}:
        return "CLEANED"
    if name == "retire_before_consume":
        return "RETIRED"
    if name == "malformed_cleanup":
        return "MALFORMED_CLEANED"
    if name in CASES["permission_denial"]:
        return "DENIED"
    if name in CASES["ownership_tamper"]:
        return "TAMPER_REFUSED"
    if name == "unknown_after_writer_stop":
        return "UNKNOWN_RETAINED"
    if name == "stop_after_unlink":
        return "STOP_RETRIED"
    return "PARTIAL_RETRIED"


def validate_full(full, *, phase, process_instance, sources, binary, process_id):
    """Bound complete fixed-case facts; the runner independently parses copies."""
    try:
        expected = {"schema": SCHEMA, "profile": PROFILE, "phase": phase, "completed": True,
                    "process_instance": process_instance, "source_fingerprints": sources, "binary": binary,
                    "process_id": process_id, "source_unchanged": True, "cleanup_qualified": True,
                    "request_binding_kind": REQUEST_BINDING,
                    **dict.fromkeys(FALSE_FLAGS, False)}
        if (type(full) is not dict or phase not in PHASES or type(process_id) is not int or process_id <= 0
                or any(type(full.get(key)) is not type(value) or full.get(key) != value for key, value in expected.items())
                or type(full.get("version")) is not list or len(full["version"]) != 3
                or any(type(value) is not int for value in full["version"])
                or BUILDS.get(tuple(full["version"])) != full.get("build_hash")
                or type(full.get("elapsed_seconds")) is not float or not 0 <= full["elapsed_seconds"] <= 300
                or full["peak_memory"]["metric"] != "ru_maxrss" or full["peak_memory"]["units"] != "KiB"
                or type(full["peak_memory"]["value"]) is not int or full["peak_memory"]["value"] <= 0
                or type(full.get("cases")) is not list or [row.get("name") for row in full["cases"]] != list(CASES[phase])):
            return False
        for row in full["cases"]:
            if (type(row) is not dict or set(row) != ROW_FIELDS or type(row["before"]) is not dict
                    or row["source_preserved"] is not True or row["before"] != row["after"]
                    or gateway.valid_source_snapshot(row["before"]["home"]) is not True
                    or type(row["before"]["targets"]) is not list or len(row["before"]["targets"]) != 2
                    or row["outcome"] != expected_outcome(row["name"]) or not file_record(row["sentinel"])
                    or type(row["raw_targets"]) is not list or len(row["raw_targets"]) != 2
                    or row["raw_targets"] != row["before"]["targets"]):
                return False
            count = 16 if row["name"] == "sixteen_captures" else 1
            before, after = row["journal_before"], row["journal_after"]
            for journal in (before, after):
                if (type(journal) is not dict or journal.get("schema") != "owned_storage_inspection_effects_v1"
                        or type(journal.get("capacity")) is not int or journal["capacity"] != count
                        or type(journal.get("snapshots")) is not list
                        or len(journal["snapshots"]) != count
                        or any(journal.get(flag) is not False for flag in ("runtime_retention_qualified", "durable_backup_qualified",
                                                                         "full_source_preservation_qualified", "native_calls_preemptible"))):
                    return False
            copies, receipts = row["evidence_copies"], row["cleanup_receipts"]
            if (type(copies) is not list or len(copies) != count or type(receipts) is not list or len(receipts) != count
                    or [copy.get("owner_index") for copy in copies] != list(range(count))
                    or [receipt.get("owner_index") for receipt in receipts] != list(range(count))):
                return False
            for index, (copy, cleanup) in enumerate(zip(copies, receipts, strict=True)):
                first, last = before["snapshots"][index], after["snapshots"][index]
                if (type(copy) is not dict or set(copy) != {"owner_index", "original_path", "original_identity", "original_binding",
                                                         "original_sha256", "copy", "retained_parser"}
                        or type(copy["owner_index"]) is not int
                        or copy["original_path"] != first["filepath"] or not file_record(copy["copy"])
                        or copy["copy"]["sha256"] != copy["original_sha256"]
                        or type(copy["original_identity"]) is not list or len(copy["original_identity"]) != 4
                        or any(type(value) is not int for value in copy["original_identity"])
                        or copy["copy"]["bytes"] != copy["original_identity"][2]
                        or first["file_identity"] not in ([], copy["original_identity"])
                        or first["file_sha256"] not in (None, copy["original_sha256"])
                        or type(copy["retained_parser"]) is not list or len(copy["retained_parser"]) != 2
                        or type(cleanup) is not dict or set(cleanup) != {"owner_index", "receipt"}
                        or type(cleanup["owner_index"]) is not int
                        or not plain_cleanup(cleanup["receipt"])
                        or cleanup["receipt"]["root"] != row["owned_root"]
                        or first["root"] != row["owned_root"] or first["directory"] != str(Path(row["owned_root"]) / cleanup["receipt"]["directory_leaf"])
                        or any(last[key] != first[key] for key in ("root", "directory", "filepath", "root_identity", "directory_identity",
                                                                  "file_identity", "file_bytes", "file_sha256", "native_entered", "native_returned"))):
                    return False
                done = row["name"] not in {*CASES["permission_denial"], *CASES["ownership_tamper"], "unknown_after_writer_stop"}
                if cleanup["receipt"]["complete"] is not done:
                    return False
                if done and (last["cleanup_entered"] is not True or last["cleanup_returned"] is not True):
                    return False
                unknown = row["name"] == "unknown_after_writer_stop"
                if (cleanup["receipt"]["original_file_identity_known"] is unknown
                        or (unknown and (copy["original_binding"] is not None or first["file_identity"] != []
                                         or cleanup["receipt"]["retained_unknown"] is not True
                                         or cleanup["receipt"]["unlink_entered"] is not False))):
                    return False
                if not unknown and (type(copy["original_binding"]) is not list or len(copy["original_binding"]) != 8
                                    or any(type(value) is not int for value in copy["original_binding"])):
                    return False
                if (first["native_entered"] is not True or first["native_returned"] is not True
                        or first["reserved"] is not True or first["directory_returned"] is not True
                        or first["cleanup_entered"] is not False or first["cleanup_returned"] is not False
                        or first["consumed"] is not (row["name"] not in {"malformed_cleanup", "retire_before_consume", "unknown_after_writer_stop"})):
                    return False
                names = gateway.NAMES if full["version"][0] == 4 else gateway.NAMES + gateway.EXTRA_NAMES
                for target_index, proof in enumerate(copy["retained_parser"]):
                    if type(proof) is not dict or proof.get("target") != row["raw_targets"][target_index]:
                        return False
                    if row["name"] == "malformed_cleanup" and target_index == 1:
                        if proof != {"target": row["raw_targets"][target_index], "error": {
                                "type": "StorageSnapshotError", "reason": "RAW_PROPERTY_TYPE_UNQUALIFIED"}}:
                            return False
                    elif (set(proof) != {"target", "result"} or type(proof["result"]) is not dict
                            or proof["result"]["storage"]["state"] != "GROUP"
                            or {child["name"]: child["value"] for child in proof["result"]["storage"]["children"]}
                            != {key: (ordinal + target_index) % 2 for ordinal, key in enumerate(names)}):
                        return False
            events = row["events"]
            if type(events) is not list or len(events) > 8192:
                return False
            for event in events:
                if (type(event) is not dict or set(event) != {"event", "name", "after_stop"}
                        or event["event"] not in {"c_call", "c_return", "c_exception", "provider", "native_read"}
                        or event["name"] not in {*OS_NAMES, "require", "native_check"}
                        or type(event["after_stop"]) is not bool):
                    return False
                if event["after_stop"] and event["name"] != "close":
                    return False
            if row["after_stop"] != [event for event in events if event["after_stop"]]:
                return False
            if row["name"] in CASES["permission_denial"] and any(event["event"].startswith("c_") for event in events):
                return False
            if row["name"] not in CASES["permission_denial"] and not any(event["event"] == "c_return" and event["name"] == "open" for event in events):
                return False
            if row["name"] not in {*CASES["permission_denial"], *CASES["ownership_tamper"], "unknown_after_writer_stop"} and (
                    sum(event["event"] == "c_return" and event["name"] == "unlink" for event in events) != count
                    or sum(event["event"] == "c_return" and event["name"] == "rmdir" for event in events) != count):
                return False
            actor, retirement = row["actor"], row["retirement"]
            if (type(actor) is not dict or set(actor) != {"applied", "removed", "retry_with_fresh_context", "fault_kind", "request_ids", "contexts_created"}
                    or any(type(actor[key]) is not bool for key in ("applied", "removed", "retry_with_fresh_context"))
                    or type(actor["contexts_created"]) is not int or not 2 <= actor["contexts_created"] <= 64
                    or type(actor["request_ids"]) is not list or len(actor["request_ids"]) != actor["contexts_created"]
                    or any(type(value) is not str or len(value) != 32
                           or any(ch not in "0123456789abcdef" for ch in value) for value in actor["request_ids"])
                    or len(set(actor["request_ids"])) != len(actor["request_ids"])
                    or type(retirement) is not dict or set(retirement) != {"consume_refused", "native_checks_after_retirement", "reason"}
                    or type(retirement["consume_refused"]) is not bool or type(retirement["native_checks_after_retirement"]) is not int
                    or retirement["native_checks_after_retirement"] != 0):
                return False
            if row["name"] == "retire_before_consume" and (retirement["consume_refused"] is not True
                                                            or retirement["reason"] != "SNAPSHOT_WITNESS_RETIRED"):
                return False
            if row["name"] in {"stop_after_unlink", "unlink_failure", "rmdir_failure"} and (
                    not actor["applied"] or not actor["removed"] or not actor["retry_with_fresh_context"]):
                return False
            errors = row["errors"]
            if type(errors) is not list or any(type(error) is not dict or set(error) != ERROR_FIELDS for error in errors):
                return False
            if row["name"] in CASES["permission_denial"]:
                code = "PERMISSION_DENIED" if row["name"].startswith("deny_") else "AGENT_PAUSED" if row["name"] == "paused" else "EMERGENCY_STOPPED"
                if len(errors) != 1 or errors[0]["stage"] != "cleanup" or errors[0]["code"] != code:
                    return False
            if row["name"] in CASES["ownership_tamper"] and (len(errors) != 1 or errors[0]["stage"] != "cleanup"
                    or not actor["applied"] or actor["removed"] or any(receipt["receipt"]["unlink_entered"] for receipt in receipts)):
                return False
            if row["name"] == "stop_after_unlink" and (not row["after_stop"] or len(errors) != 1
                    or errors[0]["code"] != "AGENT_PAUSED" or errors[0]["stage"] != "cleanup"):
                return False
            if row["name"] == "unknown_after_writer_stop" and (len(errors) != 1 or errors[0]["stage"] != "capture"
                    or errors[0]["code"] != "EMERGENCY_STOPPED"):
                return False
            if row["name"] == "malformed_cleanup" and not any(error["type"] == "StorageSnapshotError"
                                                               and error["reason"] == "RAW_PROPERTY_TYPE_UNQUALIFIED" for error in errors):
                return False
            if row["name"] in {"unlink_failure", "rmdir_failure"} and not any(event["event"] == "c_exception"
                                                                              and event["name"] == row["name"].split("_")[0]
                                                                              for event in events):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        return False


class FSObserver:
    """Observe original production filesystem C events; never substitute them."""
    def __init__(self, fixture, name, operation, events):
        from blender_codex_bridge import storage_snapshot as adapter
        from blender_codex_bridge.tool_registry import ToolContext
        self.fixture, self.name, self.operation, self.events = fixture, name, operation, events
        self.api = {id(function): key for key, function in adapter._CLEANUP_OS_ORIGINS}
        self.require = ToolContext.require.__code__
        self.native = adapter._NativeSource.check.__code__
        self.filename = adapter.__file__
        self.stopped = self.applied = False
        self.original = None
        self.extra = None

    def observe(self, frame, event, argument):
        code = frame.f_code
        if event == "call" and code in {self.require, self.native}:
            self.events.append({"event": "provider" if code is self.require else "native_read",
                                "name": "require" if code is self.require else "native_check", "after_stop": self.stopped})
            return
        if event not in {"c_call", "c_return", "c_exception"} or code.co_filename != self.filename:
            return
        name = self.api.get(id(argument))
        if name is None:
            return
        self.events.append({"event": event, "name": name, "after_stop": self.stopped})
        assert len(self.events) <= 8192
        if self.applied:
            return
        if self.name == "stop_after_unlink" and event == "c_return" and name == "unlink":
            self.fixture.runtime.state.paused = True
            self.stopped = self.applied = True
        elif self.name == "unlink_failure" and event == "c_call" and name == "unlink":
            os.chmod(self.operation.cell.directory, 0o500)
            self.applied = True
        elif self.name == "rmdir_failure" and event == "c_call" and name == "rmdir":
            self.extra = Path(self.operation.cell.directory) / "foreign-failure-sentinel"
            create_file(self.extra, b"FIXTURE ACTOR OWNED FAILURE SENTINEL")
            self.applied = True

    def __enter__(self):
        self.original = (sys.getprofile(), threading.getprofile(), sys.gettrace(), threading.gettrace())
        assert all(value is None for value in self.original)
        try:
            sys.setprofile(self.observe)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_):
        failures = []
        for setter, value in zip((sys.setprofile, threading.setprofile, sys.settrace, threading.settrace), self.original, strict=True):
            try:
                setter(value)
            except BaseException as error:
                failures.append(error)
        if failures:
            raise failures[0]


class Fixture(gateway.Fixture):
    def __init__(self, bpy, options, attestation):
        super().__init__(bpy, options, attestation)
        self.sources = source_fingerprints()
        self.data.update(schema=SCHEMA, profile=PROFILE, source_fingerprints=self.sources, cases=[], cleanup_qualified=False,
                         request_binding_kind=REQUEST_BINDING,
                         **dict.fromkeys(FALSE_FLAGS, False))
        self.context_count = 0
        self.request_ids = []

    def fresh_context(self):
        from blender_codex_bridge import executor as executor_module
        from blender_codex_bridge.command_queue import QueuedRequest
        from blender_codex_bridge.protocol import Request
        from blender_codex_bridge.request_lifecycle import RequestLifetime
        context = self.runtime.executor.context
        context.checkpoint_method = "simulation.cache_preview"
        request_id = os.urandom(16).hex()
        lifetime = RequestLifetime.local()
        request = Request(id=request_id, method=context.checkpoint_method, params={}, _lifecycle=lifetime)
        queued_owner = QueuedRequest(request, deadline=time.monotonic() + 60)
        assert queued_owner.try_start()
        code, = (code for code in executor_module.MainThreadExecutor._invoke_owned.__code__.co_consts
                 if type(code) is CodeType and code.co_freevars == ("queued_owner",))
        cell, = (lambda: queued_owner).__closure__
        context.request_lifecycle, context.request_id = lifetime, request_id
        context.check_cancelled = queued_owner.check_active
        context.check_final_request = FunctionType(code, vars(executor_module), closure=(cell,))
        self.context_count += 1
        self.request_ids.append(request_id)
        return context

    def reset(self):
        self.runtime.state.paused = self.runtime.state.emergency_stopped = False
        self.prefs.allow_save_project = self.prefs.allow_external_files = self.prefs.allow_inspect_scene = True
        for index, group in enumerate(self.groups):
            gateway.author_owned_settings(group, self.names)
            for ordinal, name in enumerate(self.names):
                setattr(group, name, bool((ordinal + index) % 2))

    def copy_native(self, operation, destination, index):
        from blender_codex_bridge.blend_storage_sdna import (
            StorageSnapshotError,
            inspect_view_layer_storage,
        )
        source = Path(operation.cell.filepath)
        original, identity, copied = evidence_copy(source, destination / (str(index) + ".blend"))
        proofs = []
        for target in self.data["target_pair"]:
            try:
                result = inspect_view_layer_storage(str(destination / (str(index) + ".blend")),
                    target["scene_name"], target["view_layer_name"], allowed_names=self.names)
            except StorageSnapshotError as error:
                proofs.append({"target": target, "error": {"type": "StorageSnapshotError", "reason": error.reason}})
            else:
                proofs.append({"target": target, "result": result})
        binding = tuple.__getitem__(operation.cleanup_owner, 6)
        return {"owner_index": index, "original_path": original["path"], "original_identity": identity,
                "original_binding": None if binding is None else list(binding), "original_sha256": original["sha256"],
                "copy": copied, "retained_parser": proofs}

    def run_case(self, name):
        from blender_codex_bridge import storage_snapshot as adapter
        from blender_codex_bridge.storage_snapshot_effects import SnapshotJournal
        self.reset()
        if name == "malformed_cleanup":
            del self.groups[1]["use_denoising"]
            self.groups[1]["use_denoising"] = "wrong scalar storage"
        root = self.folder / (self.options.bridge_phase + "-" + name + "-owned")
        root.mkdir(mode=0o700)
        destination = self.folder / (self.options.bridge_phase + "-" + name + "-evidence")
        destination.mkdir(mode=0o700)
        sentinel = create_file(self.folder / (self.options.bridge_phase + "-" + name + "-sentinel.bin"), b"PROTECTED INDEPENDENT SENTINEL")
        count = 16 if name == "sixteen_captures" else 1
        journal = SnapshotJournal(count)
        before, errors, copies, receipts, events, rows_before = self.complete_snapshot(), [], [], [], [], []
        request_start = len(self.request_ids)
        actor = {"applied": False, "removed": False, "retry_with_fresh_context": False, "fault_kind": None,
                 "request_ids": [], "contexts_created": 0}
        retirement = {"consume_refused": False, "native_checks_after_retirement": 0, "reason": None}
        for index in range(count):
            context = self.fresh_context()
            operation = adapter.SnapshotOperation(context, self.bpy, self.scenes, str(root), journal)
            observer = gateway.Observer(self, "stop_after" if name == "unknown_after_writer_stop" else "valid")
            observer.operation = operation
            try:
                with observer:
                    witness = operation.run()
                    if name != "retire_before_consume":
                        witness.consume(context, self.bpy, self.scenes)
            except BaseException as error:
                errors.append({**gateway.exception_receipt(error), "stage": "capture"})
                if name not in {"malformed_cleanup", "unknown_after_writer_stop"}:
                    # The outer failure receipt must retain the original typed
                    # refusal, including resource floors, instead of masking it.
                    raise
            copies.append(self.copy_native(operation, destination, index))
            rows_before.append(journal.snapshot()["snapshots"][index])
            self.runtime.state.paused = self.runtime.state.emergency_stopped = False
            path = Path(operation.cell.filepath)
            if name in {"file_replace", "symlink"}:
                path.rename(path.with_name("original-owned.blend"))
                path.symlink_to(Path(sentinel["path"])) if name == "symlink" else create_file(path, b"FOREIGN REPLACEMENT")
            elif name == "hardlink":
                os.link(path, self.folder / (self.options.bridge_phase + "-" + name + "-foreign-hardlink.blend"))
            elif name == "root_replace":
                root.rename(root.with_name(root.name + "-original"))
                root.mkdir(mode=0o700)
            elif name == "child_replace":
                directory = path.parent
                directory.rename(directory.with_name(directory.name + "-original"))
                directory.mkdir(mode=0o700)
            elif name == "extra_entry":
                create_file(path.parent / "foreign-entry", b"FOREIGN ENTRY")
            elif name == "file_mode":
                path.chmod(0o600 if stat.S_IMODE(path.stat().st_mode) != 0o600 else 0o644)
            if name in CASES["ownership_tamper"]:
                actor.update(applied=True, fault_kind=name)
            denial = {"deny_inspect": "allow_inspect_scene", "deny_save": "allow_save_project", "deny_external": "allow_external_files"}
            if name in denial:
                setattr(self.prefs, denial[name], False)
            if name in {"paused", "emergency"}:
                setattr(self.runtime.state, "paused" if name == "paused" else "emergency_stopped", True)
            cleanup = FSObserver(self, name, operation, events)
            try:
                with cleanup:
                    result = adapter.cleanup_step(self.fresh_context(), journal, operation.cleanup_owner)
                    if name == "retire_before_consume":
                        try:
                            witness.consume(context, self.bpy, self.scenes)
                        except BaseException as error:
                            error = gateway.exception_receipt(error)
                            retirement.update(consume_refused=True, reason=error["reason"])
                            errors.append({**error, "stage": "consume"})
                    if name == "idempotent":
                        event_count = len(events)
                        assert adapter.cleanup_step(self.fresh_context(), journal, operation.cleanup_owner) == result
                        assert len(events) == event_count
            except BaseException as error:
                errors.append({**gateway.exception_receipt(error), "stage": "cleanup"})
                if name not in {*CASES["permission_denial"], *CASES["ownership_tamper"],
                                "stop_after_unlink", "unlink_failure", "rmdir_failure"}:
                    raise
            if name in {"stop_after_unlink", "unlink_failure", "rmdir_failure"}:
                actor.update(applied=cleanup.applied, fault_kind=name)
                assert cleanup.applied
                if name in {"unlink_failure", "rmdir_failure"}:
                    assert any(event["event"] == "c_exception" and event["name"] == name.split("_")[0] for event in events)
                self.runtime.state.paused = self.runtime.state.emergency_stopped = False
                if name == "unlink_failure":
                    path.parent.chmod(0o700)
                if cleanup.extra is not None:
                    assert cleanup.extra.read_bytes() == b"FIXTURE ACTOR OWNED FAILURE SENTINEL"
                    cleanup.extra.unlink()
                actor["removed"] = True
                with FSObserver(self, "retry", operation, events):
                    adapter.cleanup_step(self.fresh_context(), journal, operation.cleanup_owner)
                actor["retry_with_fresh_context"] = True
            if name == "retire_before_consume":
                retirement["native_checks_after_retirement"] = sum(event["event"] == "native_read" for event in events)
                assert retirement["consume_refused"] and retirement["reason"] == "SNAPSHOT_WITNESS_RETIRED"
            receipts.append({"owner_index": index, "receipt": adapter.cleanup_receipt(journal, operation.cleanup_owner)})
            if name in CASES["ownership_tamper"]:
                original_path = path
                if name in {"file_replace", "symlink"}:
                    original_path = path.with_name("original-owned.blend")
                elif name == "root_replace":
                    original_path = root.with_name(root.name + "-original") / path.parent.name / path.name
                elif name == "child_replace":
                    original_path = path.parent.with_name(path.parent.name + "-original") / path.name
                assert gateway.ordinary_file(original_path, 1024**3)["sha256"] == copies[-1]["original_sha256"]
                assert receipts[-1]["receipt"]["unlink_entered"] is False
            if name == "file_replace":
                assert path.read_bytes() == b"FOREIGN REPLACEMENT"
            elif name == "symlink":
                assert path.is_symlink() and path.read_bytes() == b"PROTECTED INDEPENDENT SENTINEL"
            elif name == "hardlink":
                assert path.stat().st_nlink == 2
            elif name in {"root_replace", "child_replace"}:
                assert not list(root.iterdir()) if name == "root_replace" else not list(path.parent.iterdir())
            elif name == "extra_entry":
                assert (path.parent / "foreign-entry").read_bytes() == b"FOREIGN ENTRY"
            if name == "unknown_after_writer_stop":
                assert gateway.ordinary_file(path, 1024**3)["sha256"] == copies[-1]["original_sha256"]
            assert gateway.ordinary_file(Path(sentinel["path"]), 1024**3) == sentinel
        self.runtime.state.paused = self.runtime.state.emergency_stopped = False
        self.prefs.allow_save_project = self.prefs.allow_external_files = self.prefs.allow_inspect_scene = True
        after = self.complete_snapshot()
        assert before == after
        actor["request_ids"] = self.request_ids[request_start:]
        actor["contexts_created"] = len(actor["request_ids"])
        journal_before = journal.snapshot()
        journal_before["snapshots"] = rows_before
        return {"name": name, "owned_root": str(root), "raw_targets": self.data["target_pair"], "before": before, "after": after,
                "source_preserved": True, "sentinel": sentinel, "journal_before": journal_before, "journal_after": journal.snapshot(),
                "evidence_copies": copies, "cleanup_receipts": receipts, "errors": errors, "events": events,
                "after_stop": [event for event in events if event["after_stop"]], "actor": actor, "retirement": retirement,
                "outcome": expected_outcome(name)}

    def run(self):
        status = 1
        try:
            self.setup()
            self.data["target_pair"] = self.complete_snapshot()["targets"]
            for name in CASES[self.options.bridge_phase]:
                assert time.monotonic() - self.started < 270
                self.data["cases"].append(self.run_case(name))
                self.flush()
            import resource
            self.data.update(source_unchanged=source_fingerprints() == self.sources, completed=True, cleanup_qualified=True,
                             elapsed_seconds=float(time.monotonic() - self.started),
                             peak_memory={"metric": "ru_maxrss", "units": "KiB", "value": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
            assert validate_full(self.data, phase=self.options.bridge_phase, process_instance=self.data["process_instance"],
                                 sources=self.sources, binary=self.binary, process_id=os.getpid())
            self.flush()
            marker = {key: self.data[key] for key in ("schema", "profile", "phase", "completed", "process_id", "process_instance",
                      "source_fingerprints", "binary", "version", "build_hash", "blender_version")}
            marker["full_receipt"] = gateway.ordinary_file(self.path, MAX_REPORT)
            print(MARKERS[self.options.bridge_phase] + canonical(marker).decode(), flush=True)
            status = 0
        except BaseException as error:
            self.data.update(completed=False, cleanup_qualified=False, failure=gateway.exception_receipt(error))
            self.flush()
            print(canonical(self.data["failure"]).decode(), file=sys.stderr, flush=True)
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        owned_process_exit(status)


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
    assert BUILDS.get(tuple(bpy.app.version)) == bpy.app.build_hash.decode()
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=PHASES, required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    options = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if argv is None else argv)
    fixture = Fixture(bpy, options, attestation)
    bpy.app.timers.register(fixture.run, first_interval=.01)


if __name__ == "__main__":
    main()
