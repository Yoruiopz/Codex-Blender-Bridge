# SPDX-License-Identifier: GPL-3.0-or-later
"""One fixed, isolated-background reader of an immutable owned native save copy.

This is process/directory ownership with race detection, not an OS sandbox.
Every action receives the caller's live gate; only exact owned input/profile and
installed reader code reach the child. No Blender import or source Main access.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from types import MappingProxyType

from .errors import BridgeError
from .native_save_files import MAX_FILE_BYTES, READ_BYTES, refused
from .native_save_profile import (
    DECLARED_RNA,
    LEGACY_IMAGE_PIXELS,
    MAX_MANIFEST,
    OPTIONAL_RNA,
    SCHEMA,
    ProfileRefused,
    bind_resource_directory,
    check_large_resources,
    projection_image_pixels,
    validate_resource_facts,
)

REQUEST_SCHEMA = "native_save_reader_request_v1"
RECEIPT_SCHEMA = "native_save_reader_receipt_v1"
MAX_SCHEMA_DIAGNOSTIC = 256 * 1024
FAILURE_STAGES = frozenset({"build_validation", "program_validation", "input_validation", "runtime_validation",
                            "expected_projection", "reader_preferences", "native_open", "image_preload",
                            "projection_capture", "projection_compare", "final_input_validation"})
PROFILE_REASON_PATTERN = r"[A-Z][A-Z0-9_]*(?::[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)?"
PROFILE_KEYS = ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR")
RECEIPT_KEYS = {"schema", "status", "token", "saved_sha256", "projection_sha256", "actual_projection_sha256",
                "program", "process_id", "blender_version", "build_hash", "native_open_invoked",
                "native_open_completed", "declared_projection_reopened", "source_process_contacted",
                "source_restore_writes", "reader_project_save_invoked", "native_effect_inventory_complete",
                "timings", "peak_memory", "error"}


def _file_id(path):
    value = path.lstat()
    if (not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400):
        raise refused("READER_FILE_NOT_ORDINARY")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _read(path, maximum, *, private=False):
    before = _file_id(path)
    info = path.lstat()
    if not 0 < before[2] <= maximum or (private and (
        info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077
    )):
        raise refused("READER_FILE_SHAPE_OR_BUDGET")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if _stat_id(os.fstat(descriptor)) != before:
            raise refused("READER_FILE_CHANGED")
        data = bytearray()
        while len(data) <= maximum:
            block = os.read(descriptor, min(READ_BYTES, maximum + 1 - len(data)))
            if not block:
                break
            data.extend(block)
        if len(data) != before[2] or _stat_id(os.fstat(descriptor)) != before or _file_id(path) != before:
            raise refused("READER_FILE_CHANGED")
        return bytes(data)
    finally:
        os.close(descriptor)


def _stat_id(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _digest(value):
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _identifier(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value) is not None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate schema diagnostic key")
        result[key] = value
    return result


def _valid_census(value):
    """Validate metadata shape only; reported RNA mismatches are diagnostics."""
    if (type(value) is not dict or set(value) != {"schema", "classes", "mismatches", "scope", "python_methods"}
            or value["schema"] != "native_save_class_metadata_v1"
            or value["scope"] != "declared descriptors/functions only; no ID values or hidden-storage proof"
            or type(value["classes"]) is not dict or set(value["classes"]) != set(DECLARED_RNA)
            or len(value["classes"]) > 64):
        return False
    layouts = {}
    count = 0
    for name, required in DECLARED_RNA.items():
        fields = {}
        for optional, layout in ((False, required), (True, OPTIONAL_RNA.get(name, ""))):
            for item in layout.split():
                field = item.split(":", 1)[0]
                fields[field] = optional
        layouts[name] = fields
        row = value["classes"][name]
        if (not _identifier(name) or type(row) is not dict or set(row) != {"present", "fields", "functions"}
                or type(row["present"]) is not bool or type(row["fields"]) is not dict
                or type(row["functions"]) is not list or len(row["functions"]) > 256
                or not all(_identifier(item) for item in row["functions"])
                or len(set(row["functions"])) != len(row["functions"])):
            return False
        if not row["present"]:
            if row["fields"] or row["functions"]:
                return False
            continue
        if set(row["fields"]) != set(fields) or len(fields) > 64:
            return False
        for name_, optional in fields.items():
            count += 1
            field = row["fields"][name_]
            if (count > 512 or type(field) is not dict or set(field) != {"optional", "metadata"}
                    or field["optional"] is not optional):
                return False
            metadata = field["metadata"]
            if metadata is None:
                continue
            if (type(metadata) is not dict or set(metadata) not in (
                    {"identifier", "type", "is_runtime", "is_readonly"},
                    {"identifier", "type", "is_runtime", "is_readonly", "array_length"})
                    or not _identifier(metadata["identifier"]) or type(metadata["type"]) is not str or metadata["type"] not in {
                        "BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER", "COLLECTION"}
                    or type(metadata["is_runtime"]) is not bool or type(metadata["is_readonly"]) is not bool):
                return False
            if "array_length" in metadata and (type(metadata["array_length"]) is not int
                                               or not 0 <= metadata["array_length"] <= 65536):
                return False
    mismatches = value["mismatches"]
    if type(mismatches) is not list or len(mismatches) > 512:
        return False
    for item in mismatches:
        if (type(item) is not dict or set(item) not in ({"class", "reason"}, {"class", "field", "reason"})
                or type(item["class"]) is not str or item["class"] not in layouts
                or type(item["reason"]) is not str or item["reason"] not in {
                    "CLASS_MISSING", "FIELD_MISSING", "FIELD_METADATA_MISMATCH", "FIELD_SHAPE_MISMATCH",
                    "COMPOSITOR_SCHEMA_MISSING", "AS_POINTER_METHOD_MISSING"}
                or ("field" in item and (type(item["field"]) is not str or item["field"] not in layouts[item["class"]]))):
            return False
    methods = value["python_methods"]
    return (type(methods) is dict and set(methods) == {"ID.as_pointer", "bpy_prop_array.foreach_get"}
            and type(methods["ID.as_pointer"]) is bool
            and methods["bpy_prop_array.foreach_get"] == "C wrapper source binding; not an RNA function")


def _write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        stream = os.fdopen(descriptor, "wb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o400)


class SaveReaderProcess:
    __slots__ = (
        "_launch_resource_check",
        "_process",
        "_receipt_raw",
        "_schema_observed",
        "_sealed",
        "binary",
        "binary_id",
        "binary_sha256",
        "build_hash",
        "cleanup_status",
        "expected_raw",
        "folder",
        "folder_id",
        "image_pixels",
        "input_ids",
        "launch_wall_ms",
        "prepared",
        "profile",
        "program",
        "projection_sha256",
        "reader",
        "reaped",
        "request_sha256",
        "saved_id",
        "saved_path",
        "saved_sha256",
        "shutdown_wait_ms",
        "token",
        "version",
    )

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise refused("READER_FACTS_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, _name):
        raise refused("READER_FACTS_IMMUTABLE")

    def __init__(self, binary, saved_path, expected_raw, build_hash, version, expected_file_sha):
        self.binary = Path(binary).resolve(strict=True)
        self.binary_id = _file_id(self.binary)
        if not 0 < self.binary_id[2] <= 1024 * 1024 * 1024:
            raise refused("READER_BINARY_BUDGET")
        self.saved_path = Path(saved_path)
        self.saved_id = _file_id(self.saved_path)
        if not 0 < self.saved_id[2] <= MAX_FILE_BYTES or not _digest(expected_file_sha):
            raise refused("READER_INPUT_BUDGET")
        self.saved_sha256 = expected_file_sha
        if type(expected_raw) is not bytes or not 0 < len(expected_raw) <= MAX_MANIFEST:
            raise refused("READER_PROJECTION_BUDGET")
        expected = json.loads(expected_raw)
        if (type(expected) is not dict or expected.get("schema") != SCHEMA
                or json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() != expected_raw):
            raise refused("READER_PROJECTION_ENCODING")
        self.expected_raw, self.projection_sha256 = expected_raw, hashlib.sha256(expected_raw).hexdigest()
        self.image_pixels = projection_image_pixels(expected)
        if type(build_hash) is not str or not 1 <= len(build_hash) <= 64 or type(version) is not str or not 1 <= len(version) <= 128:
            raise refused("READER_BUILD_UNAVAILABLE")
        self.build_hash, self.version = build_hash, version
        self.reader = Path(__file__).with_name("native_save_reader.py").resolve(strict=True)
        self.profile = self.reader.with_name("native_save_profile.py")
        self.program = MappingProxyType({path.name: hashlib.sha256(_read(path, 256 * 1024)).hexdigest()
                                        for path in (self.reader, self.profile)})
        self.token, self.folder, self.folder_id = uuid.uuid4().hex, None, None
        self.binary_sha256 = self.input_ids = None
        self.request_sha256 = None
        self.prepared = False
        self._process = self._receipt_raw = None
        self._schema_observed = None
        self._launch_resource_check = None
        self.launch_wall_ms = self.shutdown_wait_ms = None
        self.cleanup_status, self.reaped = "not_created", True
        object.__setattr__(self, "_sealed", True)

    @property
    def process(self):
        return self._process

    def _owned(self):
        if self.folder is None:
            raise refused("READER_STAGING_MISSING")
        info = self.folder.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700 or (info.st_dev, info.st_ino) != self.folder_id):
            raise refused("READER_STAGING_CHANGED")

    def _program(self):
        if _file_id(self.binary) != self.binary_id:
            raise refused("READER_BINARY_CHANGED")
        for path in (self.reader, self.profile):
            if hashlib.sha256(_read(path, 256 * 1024)).hexdigest() != self.program[path.name]:
                raise refused("READER_PROGRAM_CHANGED")

    def fingerprint_steps(self, gate):
        if self.folder is not None or self.prepared or self._process is not None:
            raise refused("READER_ALREADY_PREPARED")
        gate()
        digest = hashlib.sha256()
        with self.binary.open("rb") as stream:
            count = 0
            while True:
                gate()
                block = stream.read(READ_BYTES)
                if not block:
                    break
                count += len(block)
                if count > self.binary_id[2]:
                    raise refused("READER_BINARY_CHANGED")
                digest.update(block)
                yield {"phase": "verifying_reader_runtime", "completed": count, "total": self.binary_id[2]}
        self._program()
        object.__setattr__(self, "binary_sha256", digest.hexdigest())
        gate()
        folder = Path(tempfile.mkdtemp(prefix="blender-codex-native-save-reader-"))
        object.__setattr__(self, "folder", folder)
        info = folder.lstat()
        object.__setattr__(self, "folder_id", (info.st_dev, info.st_ino))
        object.__setattr__(self, "cleanup_status", "pending")
        self._owned()
        for name in (*PROFILE_KEYS, "TMPDIR", "working"):
            gate()
            (folder / name.lower()).mkdir(mode=0o700)
        gate()
        if _file_id(self.saved_path) != self.saved_id:
            raise refused("SAVED_PROJECT_CHANGED")
        source_fd = os.open(self.saved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        digest, count = hashlib.sha256(), 0
        try:
            destination_fd = os.open(folder / "saved.blend", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            if _stat_id(os.fstat(source_fd)) != self.saved_id:
                os.close(destination_fd)
                raise refused("SAVED_PROJECT_CHANGED")
            try:
                destination = os.fdopen(destination_fd, "wb")
            except BaseException:
                os.close(destination_fd)
                raise
            with destination:
                while True:
                    gate()
                    block = os.read(source_fd, READ_BYTES)
                    if not block:
                        break
                    count += len(block)
                    if count > self.saved_id[2]:
                        raise refused("SAVED_PROJECT_CHANGED")
                    destination.write(block)
                    digest.update(block)
                    yield {"phase": "freezing_reader_input", "completed": count, "total": self.saved_id[2]}
                destination.flush()
                os.fsync(destination.fileno())
            if (count != self.saved_id[2] or digest.hexdigest() != self.saved_sha256
                    or _stat_id(os.fstat(source_fd)) != self.saved_id or _file_id(self.saved_path) != self.saved_id):
                raise refused("SAVED_PROJECT_CHANGED")
        finally:
            os.close(source_fd)
        gate()
        os.chmod(folder / "saved.blend", 0o400)
        _write(folder / "expected.json", self.expected_raw)
        request = {"schema": REQUEST_SCHEMA, "token": self.token, "saved_sha256": self.saved_sha256,
                   "projection_sha256": self.projection_sha256, "binary_sha256": self.binary_sha256,
                   "build_hash": self.build_hash, "blender_version": self.version, "program": dict(self.program)}
        request_raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        _write(folder / "request.json", request_raw)
        object.__setattr__(self, "request_sha256", hashlib.sha256(request_raw).hexdigest())
        object.__setattr__(self, "input_ids", tuple((name, _file_id(folder / name))
                                                   for name in ("saved.blend", "expected.json", "request.json")))
        object.__setattr__(self, "prepared", True)

    def launch(self, gate):
        gate()
        if not self.prepared or self._process is not None or self.folder is None or self.input_ids is None:
            raise refused("READER_LAUNCH_PHASE")
        self._owned()
        self._program()
        for name, expected in self.input_ids:
            if _file_id(self.folder / name) != expected:
                raise refused("READER_INPUT_CHANGED")
        environment = {key: os.environ[key] for key in (
            "PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "LIBGL_ALWAYS_SOFTWARE",
            "GALLIUM_DRIVER", "MESA_LOADER_DRIVER_OVERRIDE", "LP_NUM_THREADS") if key in os.environ}
        environment.update({key: str(self.folder / key.lower()) for key in PROFILE_KEYS})
        temporary = str(self.folder / "tmpdir")
        environment.update(TEMP=temporary, TMP=temporary, TMPDIR=temporary, NO_AT_BRIDGE="1", GSETTINGS_BACKEND="memory")
        command = [str(self.binary), "--background", "--factory-startup", "--disable-autoexec", "--threads", "1",
                   "--python-exit-code", "1", "--python-expr", "import sys; sys.dont_write_bytecode = True",
                   "--python", str(self.reader), "--", "--bundle", str(self.folder), "--token", self.token]
        if self.image_pixels > LEGACY_IMAGE_PIXELS:
            try:
                directory = bind_resource_directory(str(self.folder))
                if directory.ancestry[-1][1:] != self.folder_id:
                    raise refused("READER_STAGING_CHANGED")
                facts = check_large_resources(self.image_pixels, directory)
                validate_resource_facts(facts)
            except ProfileRefused as cause:
                raise refused("READER_LARGE_IMAGE_RESOURCES_UNAVAILABLE") from cause
            object.__setattr__(self, "_launch_resource_check", facts)
            self._owned()
        gate()
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=self.folder / "working", env=environment, shell=False,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        object.__setattr__(self, "_process", process)
        object.__setattr__(self, "reaped", False)
        object.__setattr__(self, "launch_wall_ms", (time.monotonic() - started) * 1000)

    def poll(self):
        if self._process is None:
            raise refused("READER_NOT_LAUNCHED")
        value = self._process.poll()
        if value is not None:
            object.__setattr__(self, "reaped", True)
        return value

    def _receipt(self, row):
        if self._process is None:
            raise refused("READER_NOT_LAUNCHED")
        if type(row) is not dict or set(row) not in (RECEIPT_KEYS, RECEIPT_KEYS | {"resource_checks"}):
            raise refused("READER_RECEIPT_SCHEMA")
        checks, phases = row.get("resource_checks"), []
        if checks is not None:
            if self.image_pixels <= LEGACY_IMAGE_PIXELS or type(checks) is not list or len(checks) > 7:
                raise refused("READER_RESOURCE_RECEIPT_SCHEMA")
            for check in checks:
                if type(check) is not dict or set(check) != {"phase", "facts"}:
                    raise refused("READER_RESOURCE_RECEIPT_SCHEMA")
                phase = check["phase"]
                if type(phase) is not str or phase not in {"before_open", "before_packed_decode", "before_capture"}:
                    raise refused("READER_RESOURCE_RECEIPT_SCHEMA")
                try:
                    validate_resource_facts(check["facts"])
                except ProfileRefused as cause:
                    raise refused("READER_RESOURCE_RECEIPT_FACTS") from cause
                if check["facts"]["aggregate_image_pixels"] != self.image_pixels:
                    raise refused("READER_RESOURCE_RECEIPT_FACTS")
                phases.append(phase)
            expected_phases = ["before_open"] + ["before_packed_decode"] * phases.count("before_packed_decode")
            decode_count = len(json.loads(self.expected_raw)["images"]) + 1
            if phases.count("before_packed_decode") > decode_count:
                raise refused("READER_RESOURCE_RECEIPT_ORDER")
            if "before_capture" in phases:
                if phases.count("before_packed_decode") != decode_count:
                    raise refused("READER_RESOURCE_RECEIPT_ORDER")
                expected_phases.append("before_capture")
            if phases and phases != expected_phases:
                raise refused("READER_RESOURCE_RECEIPT_ORDER")
            if row.get("status") == "succeeded" and (len(phases) < 3 or phases[-1] != "before_capture"):
                raise refused("READER_RESOURCE_RECEIPT_INCOMPLETE")
        elif "resource_checks" in row or (self.image_pixels > LEGACY_IMAGE_PIXELS and row.get("status") == "succeeded"):
            raise refused("READER_RESOURCE_RECEIPT_INCOMPLETE")
        if self.image_pixels > LEGACY_IMAGE_PIXELS and row.get("status") == "failed":
            error = row.get("error")
            stage = error.get("failure_stage") if type(error) is dict else None
            if type(stage) is not str:
                raise refused("READER_RESOURCE_RECEIPT_SCHEMA")
            if stage in {"build_validation", "program_validation", "input_validation", "runtime_validation"}:
                if "resource_checks" in row:
                    raise refused("READER_RESOURCE_RECEIPT_PHASE")
            elif stage == "expected_projection":
                if phases not in ([], ["before_open"]):
                    raise refused("READER_RESOURCE_RECEIPT_PHASE")
            elif stage in {"reader_preferences", "native_open", "image_preload", "projection_capture",
                           "projection_compare", "final_input_validation"}:
                if not phases or phases[0] != "before_open":
                    raise refused("READER_RESOURCE_RECEIPT_INCOMPLETE")
                if stage in {"reader_preferences", "native_open"} and phases != ["before_open"]:
                    raise refused("READER_RESOURCE_RECEIPT_PHASE")
                if stage == "image_preload" and "before_capture" in phases:
                    raise refused("READER_RESOURCE_RECEIPT_PHASE")
                if stage in {"projection_capture", "projection_compare", "final_input_validation"}:
                    decode_count = len(json.loads(self.expected_raw)["images"]) + 1
                    if phases.count("before_packed_decode") != decode_count:
                        raise refused("READER_RESOURCE_RECEIPT_INCOMPLETE")
                    if stage != "projection_capture" and phases[-1] != "before_capture":
                        raise refused("READER_RESOURCE_RECEIPT_INCOMPLETE")
        fixed = {"schema": RECEIPT_SCHEMA, "token": self.token, "saved_sha256": self.saved_sha256,
                 "projection_sha256": self.projection_sha256, "program": dict(self.program),
                 "blender_version": self.version, "build_hash": self.build_hash,
                 "source_process_contacted": False, "source_restore_writes": 0,
                 "reader_project_save_invoked": False, "native_effect_inventory_complete": False}
        if any(type(row[key]) is not type(value) or row[key] != value for key, value in fixed.items()):
            raise refused("READER_RECEIPT_IDENTITY")
        if type(row["process_id"]) is not int or row["process_id"] != self._process.pid:
            raise refused("READER_RECEIPT_PROCESS")
        for name in ("native_open_invoked", "native_open_completed", "declared_projection_reopened"):
            if type(row[name]) is not bool:
                raise refused("READER_RECEIPT_FLAGS")
        if row["native_open_completed"] and not row["native_open_invoked"]:
            raise refused("READER_RECEIPT_PHASES")
        if row["status"] == "succeeded":
            if (row["error"] is not None or row["actual_projection_sha256"] != self.projection_sha256
                    or not all(row[name] for name in ("native_open_invoked", "native_open_completed", "declared_projection_reopened"))):
                raise refused("READER_COMPARISON_INCOMPLETE")
        elif row["status"] == "failed":
            error = row["error"]
            if (type(error) is not dict or set(error) not in (
                    {"code", "type", "failure_stage"}, {"code", "type", "failure_stage", "profile_reason"})
                    or error["code"] != "NATIVE_SAVE_READER_FAILED" or type(error["type"]) is not str
                    or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", error["type"]) is None
                    or type(error["failure_stage"]) is not str or error["failure_stage"] not in FAILURE_STAGES
                    or row["declared_projection_reopened"] is not False
                    or (row["actual_projection_sha256"] is not None and not _digest(row["actual_projection_sha256"]))):
                raise refused("READER_FAILURE_RECEIPT")
            stage = error["failure_stage"]
            if "profile_reason" in error and (
                error["type"] != "ProfileRefused" or stage not in {"expected_projection", "projection_capture"}
                or type(error["profile_reason"]) is not str or not 0 < len(error["profile_reason"]) <= 160
                or re.fullmatch(PROFILE_REASON_PATTERN, error["profile_reason"]) is None
            ):
                raise refused("READER_PROFILE_REASON_SCHEMA")
            if (stage in {"build_validation", "program_validation", "input_validation", "runtime_validation",
                          "expected_projection", "reader_preferences"} and row["native_open_invoked"]) or (
                stage == "native_open" and (not row["native_open_invoked"] or row["native_open_completed"])
            ) or (stage in {"image_preload", "projection_capture", "projection_compare", "final_input_validation"}
                  and not row["native_open_completed"]) or (
                stage in {"image_preload", "projection_capture"} and row["actual_projection_sha256"] is not None
            ) or (stage in {"projection_compare", "final_input_validation"} and row["actual_projection_sha256"] is None):
                raise refused("READER_FAILURE_STAGE_PHASE")
        else:
            raise refused("READER_RECEIPT_STATUS")
        timings = row["timings"]
        if type(timings) is not dict or set(timings) != {"worker_elapsed_seconds", "native_open_seconds", "projection_seconds"}:
            raise refused("READER_TIMING_SCHEMA")
        for name, value in timings.items():
            if value is None and name != "worker_elapsed_seconds" and row["status"] == "failed":
                continue
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 86400:
                raise refused("READER_TIMING_VALUE")
        if (not row["native_open_invoked"] and (
            timings["native_open_seconds"] is not None or timings["projection_seconds"] is not None
            or row["actual_projection_sha256"] is not None
        )) or (row["native_open_invoked"] and timings["native_open_seconds"] is None) or (
            not row["native_open_completed"] and (timings["projection_seconds"] is not None
                                                  or row["actual_projection_sha256"] is not None)
        ) or (row["actual_projection_sha256"] is not None and timings["projection_seconds"] is None):
            raise refused("READER_TIMING_PHASES")
        memory = row["peak_memory"]
        if (type(memory) is not dict or set(memory) != {"available", "metric", "scope", "value", "unit", "platform"}
                or memory != {"available": True, "metric": "ru_maxrss", "scope": "RUSAGE_SELF",
                              "value": memory.get("value"), "unit": "KiB", "platform": "linux"}
                or type(memory.get("available")) is not bool or type(memory.get("value")) is not int
                or not 0 <= memory["value"] <= 2**53 - 1):
            raise refused("READER_MEMORY_SCHEMA")
        return row

    def _schema_diagnostic(self, *, observe=False):
        if self.folder is None or self._process is None:
            return {"available": False, "reason": "NOT_PRODUCED"}
        try:
            self._owned()
            path = self.folder / "schema-census.json"
            info = path.lstat()
            if info.st_size > MAX_SCHEMA_DIAGNOSTIC:
                return {"available": False, "reason": "OVER_BUDGET"}
            identity = _file_id(path)
            raw = _read(path, MAX_SCHEMA_DIAGNOSTIC, private=True)
            if _file_id(path) != identity:
                return {"available": False, "reason": "INVALID"}
            observed = identity, hashlib.sha256(raw).hexdigest()
            if self._schema_observed is not None and self._schema_observed != observed:
                return {"available": False, "reason": "CHANGED"}
            value = json.loads(raw, object_pairs_hook=_unique_object)
            if type(value) is not dict or set(value) != {"schema", "token", "process_id", "blender_version",
                    "build_hash", "program", "saved_sha256", "projection_sha256", "request_sha256", "census"}:
                return {"available": False, "reason": "INVALID"}
            expected = {"schema": "native_save_schema_sidecar_v1", "token": self.token,
                        "process_id": self._process.pid, "blender_version": self.version, "build_hash": self.build_hash,
                        "program": dict(self.program), "saved_sha256": self.saved_sha256,
                        "projection_sha256": self.projection_sha256, "request_sha256": self.request_sha256}
            if (not _digest(self.request_sha256)
                    or any(type(value[key]) is not type(item) or value[key] != item for key, item in expected.items())):
                return {"available": False, "reason": "BINDING_MISMATCH"}
            if not _valid_census(value["census"]):
                return {"available": False, "reason": "INVALID"}
            if observe and self._schema_observed is None:
                object.__setattr__(self, "_schema_observed", observed)
        except FileNotFoundError:
            return {"available": False, "reason": "NOT_PRODUCED"}
        except (OSError, ValueError, TypeError, KeyError, RecursionError, BridgeError):
            return {"available": False, "reason": "INVALID"}
        return {"available": True, "reason": "AVAILABLE"}

    def result(self, gate):
        gate()
        code = self.poll()
        if code is None:
            raise refused("READER_STILL_RUNNING")
        if type(code) is not int:
            raise refused("READER_EXIT_STATUS_INVALID")
        try:
            self._owned()
            if self.folder is None:
                raise refused("READER_STAGING_MISSING")
            raw = _read(self.folder / "reader.json", 64 * 1024, private=True)
            row = self._receipt(json.loads(raw))
        except (OSError, UnicodeError, ValueError) as cause:
            raise refused("READER_RECEIPT_INVALID") from cause
        object.__setattr__(self, "_receipt_raw", raw)
        gate()
        if code != 0 or row["status"] != "succeeded":
            error = refused("NATIVE_SAVE_READER_FAILED")
            if row["status"] == "failed":
                error.context["reader_failure"] = dict(row["error"])
                diagnostic = self._schema_diagnostic(observe=True)
                gate()
                error.context["reader_schema_diagnostic"] = diagnostic
            raise error
        return json.loads(raw)

    def close(self, *, remove_files=True):
        process = self._process
        if process is not None and not self.reaped:
            started = time.monotonic()
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=.1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=.2)
                else:
                    process.wait(timeout=.1)
                object.__setattr__(self, "reaped", True)
            except (OSError, subprocess.TimeoutExpired):
                object.__setattr__(self, "reaped", False)
            object.__setattr__(self, "shutdown_wait_ms", (time.monotonic() - started) * 1000)
        if self.folder is None or self.cleanup_status == "complete":
            return self.evidence()
        if not self.reaped or not remove_files:
            object.__setattr__(self, "cleanup_status", "retained_process_unknown" if not self.reaped else "retained_permission_denied")
            return self.evidence()
        try:
            self._owned()
            allowed = {key.lower() for key in PROFILE_KEYS} | {"tmpdir", "working", "saved.blend", "expected.json", "request.json", "reader.json", "schema-census.json"}
            if any(path.name not in allowed for path in self.folder.iterdir()):
                raise refused("READER_STAGING_UNKNOWN_ENTRY")
            sidecar_present = os.path.lexists(self.folder / "schema-census.json")
            if sidecar_present and (self._schema_observed is None or not self._schema_diagnostic()["available"]):
                raise refused("READER_DIAGNOSTIC_UNVERIFIED")
            count = size = 0
            for directory, directories, files in os.walk(self.folder, followlinks=False):
                for name in (*directories, *files):
                    count += 1
                    path = Path(directory) / name
                    info = path.lstat()
                    if (count > 512 or info.st_uid != os.getuid() or not
                            (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
                        raise refused("READER_STAGING_UNVERIFIED")
                    size += info.st_size if stat.S_ISREG(info.st_mode) else 0
                    if size > MAX_FILE_BYTES + MAX_MANIFEST + 32 * 1024 * 1024:
                        raise refused("READER_STAGING_BUDGET")
            self._owned()
            if os.path.lexists(self.folder / "schema-census.json") != sidecar_present or (
                sidecar_present and not self._schema_diagnostic()["available"]
            ):
                raise refused("READER_DIAGNOSTIC_CHANGED")
            shutil.rmtree(self.folder)
            object.__setattr__(self, "cleanup_status", "complete")
        except (OSError, ValueError, BridgeError):
            object.__setattr__(self, "cleanup_status", "retained_unverified")
        return self.evidence()

    def evidence(self):
        result = {"worker_reaped": self.reaped, "worker_exit_code": self._process.returncode if self._process else None,
                "staging_cleanup": self.cleanup_status,
                "retained_staging_path": str(self.folder) if self.folder and self.cleanup_status != "complete" else None,
                "launch_wall_ms": self.launch_wall_ms,
                "launch_wall_scope": "OS Popen return only; excludes input copy, child initialization and native reader work",
                "shutdown_wait_ms": self.shutdown_wait_ms,
                "worker_receipt": json.loads(self._receipt_raw) if self._receipt_raw else None,
                "parent_peak_memory_measured": False, "OS_launch_memory_measured": False,
                "parent_native_blocking_measured": False, "filesystem_sandbox": False}
        if self._launch_resource_check is not None:
            result["launch_resource_check"] = dict(self._launch_resource_check)
        return result
