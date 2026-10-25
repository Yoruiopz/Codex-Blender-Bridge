"""One fixed official-Blender child and a bounded task-owned staging directory."""

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
from typing import Any

from .geometry_preview_dto import (
    DEFAULT_DELTAS,
    MAX_BYTES,
    camera_fit,
    canonical,
    projected_bounds,
    validate_dto,
    validate_png,
    world_bounds,
)
from .geometry_preview_source import refused

PROFILE_KEYS = (
    "HOME",
    "BLENDER_USER_CONFIG",
    "BLENDER_USER_SCRIPTS",
    "BLENDER_USER_DATAFILES",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR",
)


def file_id(path: Path) -> tuple:
    row = path.lstat()
    if not stat.S_ISREG(row.st_mode) or path.is_symlink():
        raise refused("WORKER_FILE_CHANGED")
    return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns


def bounded_read(path: Path, maximum: int, *, private: bool = False) -> bytes:
    before = file_id(path)
    meta = path.lstat()
    if private and (
        meta.st_uid != os.getuid() or meta.st_nlink != 1 or stat.S_IMODE(meta.st_mode) & 0o077
    ):
        raise refused("WORKER_FILE_NOT_PRIVATE")
    if not 0 < before[2] <= maximum:
        raise refused("WORKER_OUTPUT_BUDGET")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        value = os.fstat(descriptor)
        if (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns) != before:
            raise refused("WORKER_FILE_CHANGED")
        raw = os.read(descriptor, maximum + 1)
        if len(raw) != before[2] or file_id(path) != before:
            raise refused("WORKER_FILE_CHANGED")
        return raw
    finally:
        os.close(descriptor)


class PreviewProcess:
    """No Blender API here; callers supply live authority at each action."""

    __slots__ = (
        "_sealed",
        "binary",
        "binary_id",
        "binary_sha256",
        "build_hash",
        "cleanup_status",
        "directory_id",
        "dto_module",
        "folder",
        "input_sha",
        "launch_ms",
        "process",
        "program",
        "raw",
        "receipt",
        "shutdown_wait_ms",
        "token",
        "version",
        "worker",
    )

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise refused("PROCESS_FACTS_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise refused("PROCESS_FACTS_IMMUTABLE")

    def __init__(self, binary: str, raw: bytes, build_hash: str, version: str | None = None):
        self.binary = Path(binary).resolve(strict=True)
        self.binary_id = file_id(self.binary)
        if not 0 < self.binary_id[2] <= 1024 * 1024 * 1024:
            raise refused("BINARY_BUDGET")
        self.worker = Path(__file__).with_name("geometry_preview_worker.py").resolve(strict=True)
        self.dto_module = self.worker.with_name("geometry_preview_dto.py")
        self.program = {
            p.name: hashlib.sha256(bounded_read(p, 256 * 1024)).hexdigest()
            for p in (self.worker, self.dto_module)
        }
        self.raw = canonical(validate_dto(json.loads(raw)))
        if self.raw != raw:
            raise refused("DTO_ENCODING_CHANGED")
        self.input_sha = hashlib.sha256(raw).hexdigest()
        self.build_hash, self.token = build_hash, uuid.uuid4().hex
        self.version = version
        self.folder: Path | None = None
        self.directory_id = None
        self.process: Any = None
        self.launch_ms = None
        self.shutdown_wait_ms = None
        self.binary_sha256 = None
        self.cleanup_status = "not_created"
        self.receipt = None
        self.program = MappingProxyType(self.program)
        object.__setattr__(self, "_sealed", True)

    def fingerprint_steps(self, gate):
        digest = hashlib.sha256()
        gate()
        with self.binary.open("rb") as stream:
            count = 0
            while True:
                gate()
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > self.binary_id[2]:
                    raise refused("BINARY_CHANGED")
                digest.update(chunk)
                yield {
                    "phase": "verifying_runtime",
                    "completed_bytes": count,
                    "total_bytes": self.binary_id[2],
                }
        if count != self.binary_id[2] or file_id(self.binary) != self.binary_id:
            raise refused("BINARY_CHANGED")
        object.__setattr__(self, "binary_sha256", digest.hexdigest())

    def validate(self):
        if self.folder is not None:
            row = self.folder.lstat()
            if (
                not stat.S_ISDIR(row.st_mode)
                or stat.S_IMODE(row.st_mode) != 0o700
                or row.st_uid != os.getuid()
                or (row.st_dev, row.st_ino) != self.directory_id
                or self.folder.resolve() != self.folder
            ):
                raise refused("STAGING_CHANGED")

    def launch(self, gate):
        gate()
        if self.process is not None or self.folder is not None or self.binary_sha256 is None:
            raise refused("WORKER_ALREADY_STARTED")
        object.__setattr__(
            self,
            "folder",
            Path(tempfile.mkdtemp(prefix="blender-codex-geometry-")).resolve(strict=True),
        )
        self.folder.chmod(0o700)
        row = self.folder.lstat()
        object.__setattr__(self, "directory_id", (row.st_dev, row.st_ino))
        object.__setattr__(self, "cleanup_status", "pending")
        gate()
        self.validate()
        environment = {
            key: os.environ[key]
            for key in (
                "PATH",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
                "LIBGL_ALWAYS_SOFTWARE",
                "GALLIUM_DRIVER",
                "MESA_LOADER_DRIVER_OVERRIDE",
                "LP_NUM_THREADS",
            )
            if key in os.environ
        }
        for key in PROFILE_KEYS:
            gate()
            self.validate()
            path = self.folder / ("profile_" + key.lower())
            path.mkdir(mode=0o700)
            environment[key] = str(path)
        gate()
        self.validate()
        working = self.folder / "working"
        working.mkdir(mode=0o700)
        environment.update(
            TEMP=str(self.folder),
            TMP=str(self.folder),
            TMPDIR=str(self.folder),
            PYTHONDONTWRITEBYTECODE="1",
            GSETTINGS_BACKEND="memory",
            NO_AT_BRIDGE="1",
        )
        gate()
        self.validate()
        with (self.folder / "dto.json").open("xb") as stream:
            stream.write(self.raw)
        (self.folder / "dto.json").chmod(0o400)
        for path in (self.worker, self.dto_module):
            if (
                hashlib.sha256(bounded_read(path, 256 * 1024)).hexdigest()
                != self.program[path.name]
            ):
                raise refused("INSTALLED_WORKER_CHANGED")
        if file_id(self.binary) != self.binary_id:
            raise refused("BINARY_CHANGED")
        gate()
        self.validate()
        command = [
            str(self.binary),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--threads",
            "1",
            "--python-exit-code",
            "1",
            "--python-expr",
            "import sys; sys.dont_write_bytecode = True",
            "--python",
            str(self.worker),
            "--",
            "--bundle",
            str(self.folder),
            "--token",
            self.token,
        ]
        started = time.perf_counter()
        object.__setattr__(
            self,
            "process",
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=working,
                env=environment,
                shell=False,
                start_new_session=True,
            ),
        )
        object.__setattr__(self, "launch_ms", (time.perf_counter() - started) * 1000)

    def poll(self):
        return None if self.process is None else self.process.poll()

    def result(self, gate) -> tuple[bytes, dict]:
        gate()
        self.validate()
        if self.process is None or self.process.poll() is None:
            raise refused("WORKER_NOT_REAPED")
        if self.process.returncode != 0:
            try:
                failed = json.loads(
                    bounded_read(self.folder / "worker.json", 64 * 1024, private=True)
                )
                self._failed_receipt(failed)
                object.__setattr__(self, "receipt", failed)
            except Exception as cause:
                # No unverifiable worker-provided text or invented metrics leave this boundary.
                if self.receipt is None:
                    error = refused("WORKER_EXIT_FAILED_WITHOUT_AUTHENTICATED_RECEIPT")
                    error.context.update(
                        worker_exit_code=self.process.returncode, worker_receipt_available=False
                    )
                    raise error from cause
            error = refused("WORKER_EXIT_FAILED")
            error.context.update(
                worker_exit_code=self.process.returncode,
                worker_receipt_available=True,
                worker_evidence=self.receipt,
            )
            raise error
        raw = bounded_read(self.folder / "worker.json", 64 * 1024, private=True)
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as cause:
            raise refused("WORKER_RECEIPT_SHAPE") from cause
        if (
            type(row) is not dict
            or row.get("schema") != "geometry_preview_worker_v1"
            or row.get("status") != "succeeded"
            or row.get("token") != self.token
            or row.get("dto_sha256") != self.input_sha
            or row.get("build_hash") != self.build_hash
            or row.get("process_id") != self.process.pid
            or row.get("geometry_reconstructed") is not True
            or row.get("raw_channels_reconstructed") is not True
            or row.get("render_engine") != "CYCLES"
            or row.get("device") != "CPU"
            or type(row.get("process_id")) is not int
            or type(row.get("samples")) is not int
            or type(row.get("threads")) is not int
            or row.get("samples") != 8
            or row.get("threads") != 1
        ):
            raise refused("WORKER_RECEIPT_CHANGED")
        expected_keys = {
            "schema",
            "status",
            "token",
            "dto_sha256",
            "blender_version",
            "build_hash",
            "process_id",
            "input_sha256",
            "geometry_reconstructed",
            "raw_channels_reconstructed",
            "raw_channel_scope",
            "inactive_rotation_channels_copied",
            "edge_identity_scope",
            "world_bounds",
            "camera_fit",
            "projected_bounds",
            "png",
            "render_engine",
            "device",
            "samples",
            "threads",
            "source_process_contacted",
            "source_restore_writes",
            "user_properties_or_ID_references_copied",
            "original_material_appearance_copied",
            "project_saved",
            "timings",
            "peak_memory",
        }
        if (
            set(row) != expected_keys
            or type(row["blender_version"]) is not str
            or not 0 < len(row["blender_version"]) <= 64
        ):
            raise refused("WORKER_RECEIPT_SHAPE")
        if self.version is not None and row["blender_version"] != self.version:
            raise refused("WORKER_VERSION_CHANGED")
        if (
            row["edge_identity_scope"]
            != "Complete undirected edge set, not native edge allocation/order"
            or type(row["edge_identity_scope"]) is not str
        ):
            raise refused("WORKER_GEOMETRY_SCOPE_CHANGED")
        if row["input_sha256"] != self.input_sha or row["raw_channel_scope"] != [
            "location",
            "rotation_mode",
            "rotation_euler",
            "scale",
            *DEFAULT_DELTAS,
        ]:
            raise refused("WORKER_GEOMETRY_SCOPE_CHANGED")
        for flag in (
            "inactive_rotation_channels_copied",
            "source_process_contacted",
            "user_properties_or_ID_references_copied",
            "original_material_appearance_copied",
            "project_saved",
        ):
            if row[flag] is not False:
                raise refused("WORKER_SOURCE_SCOPE_CHANGED")
        if type(row["source_restore_writes"]) is not int or row["source_restore_writes"] != 0:
            raise refused("WORKER_SOURCE_SCOPE_CHANGED")
        self._metrics(row)
        try:
            canonical(row)  # Reject nonfinite JSON values before retention.
        except (ValueError, TypeError, RecursionError) as cause:
            raise refused("WORKER_RECEIPT_SHAPE") from cause
        dto = json.loads(self.raw)
        fit = camera_fit(dto)
        if canonical(row["camera_fit"]) != canonical(fit) or canonical(
            row["projected_bounds"]
        ) != canonical(projected_bounds(dto, fit)):
            raise refused("WORKER_CAMERA_CHANGED")
        expected = world_bounds(json.loads(self.raw))
        actual = row.get("world_bounds")
        if type(actual) is not dict or set(actual) != {"min", "max"}:
            raise refused("WORKER_BOUNDS_CHANGED")
        for key in ("min", "max"):
            if (
                type(actual[key]) is not list
                or len(actual[key]) != 3
                or any(
                    type(a) is not float
                    or not math.isfinite(a)
                    or abs(a - b) > max(1e-5, abs(b) * 2**-19)
                    for a, b in zip(actual[key], expected[key], strict=True)
                )
            ):
                raise refused("WORKER_BOUNDS_CHANGED")
        png = bounded_read(self.folder / "preview.png", MAX_BYTES, private=True)
        proof = validate_png(png)
        if type(row["png"]) is not dict or canonical(row["png"]) != canonical(proof):
            raise refused("WORKER_IMAGE_CHANGED")
        gate()
        self.validate()
        object.__setattr__(self, "receipt", row)
        return png, {
            "worker": row,
            "parent_validated_png": proof,
            "binary_sha256": self.binary_sha256,
            "program_sha256": dict(self.program),
            "launch_wall_ms": self.launch_ms,
            "parent_native_blocking_measured": False,
            "worker_native_blocking_measured": False,
            "launch_wall_scope": "Parent Popen call only; excludes child initialization and render",
            "parent_peak_memory_measured": False,
            "OS_launch_memory_measured": False,
        }

    def _metrics(self, row, *, failed=False):
        timings, peak = row["timings"], row["peak_memory"]
        if (
            type(timings) is not dict
            or set(timings)
            != {"worker_elapsed_seconds", "render_and_validation_seconds", "clock", "scope"}
            or timings["clock"] != "time.monotonic"
            or timings["scope"] != "worker_process"
        ):
            raise refused("WORKER_TIMINGS_CHANGED")
        for key in ("worker_elapsed_seconds", "render_and_validation_seconds"):
            value = timings[key]
            if failed and key == "render_and_validation_seconds" and value is None:
                continue
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not 0 <= value <= 3600
            ):
                raise refused("WORKER_TIMINGS_CHANGED")
        elapsed, render = (
            timings["worker_elapsed_seconds"],
            timings["render_and_validation_seconds"],
        )
        if render is not None and render > elapsed + 1e-6:
            raise refused("WORKER_TIMINGS_CHANGED")
        if (
            type(peak) is not dict
            or set(peak) != {"available", "metric", "scope", "value", "unit", "platform"}
            or peak["metric"] != "ru_maxrss"
            or peak["scope"] != "RUSAGE_SELF"
            or peak["platform"] != "linux"
            or type(peak["available"]) is not bool
        ):
            raise refused("WORKER_MEMORY_SHAPE")
        if peak["available"]:
            if (
                type(peak["value"]) is not int
                or not 0 <= peak["value"] < 2**63
                or peak["unit"] != "KiB"
            ):
                raise refused("WORKER_MEMORY_SHAPE")
        elif peak["value"] is not None or peak["unit"] is not None:
            raise refused("WORKER_MEMORY_SHAPE")

    def _failed_receipt(self, row):
        keys = {
            "schema",
            "status",
            "token",
            "dto_sha256",
            "blender_version",
            "build_hash",
            "process_id",
            "error",
            "timings",
            "peak_memory",
        }
        if (
            type(row) is not dict
            or set(row) != keys
            or row["schema"] != "geometry_preview_worker_v1"
            or row["status"] != "failed"
            or row["token"] != self.token
            or row["dto_sha256"] not in {None, self.input_sha}
            or row["build_hash"] != self.build_hash
            or type(row["process_id"]) is not int
            or row["process_id"] != self.process.pid
            or type(row["blender_version"]) is not str
            or not 0 < len(row["blender_version"]) <= 64
            or (self.version is not None and row["blender_version"] != self.version)
        ):
            raise refused("WORKER_FAILURE_RECEIPT_CHANGED")
        error = row["error"]
        if (
            type(error) is not dict
            or set(error) != {"code", "type"}
            or error["code"] != "GEOMETRY_PREVIEW_WORKER_FAILED"
            or type(error["type"]) is not str
            or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", error["type"]) is None
        ):
            raise refused("WORKER_FAILURE_RECEIPT_CHANGED")
        self._metrics(row, failed=True)
        if (
            row["dto_sha256"] is None
            and row["timings"]["render_and_validation_seconds"] is not None
        ):
            raise refused("WORKER_FAILURE_RECEIPT_CHANGED")
        canonical(row)

    def close(self) -> dict:
        """Revoke publication first in caller; exact owned cleanup needs no grant."""
        if self.cleanup_status == "complete":
            return self.evidence()
        started = time.perf_counter()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    object.__setattr__(self, "cleanup_status", "process_reap_unknown")
                    object.__setattr__(
                        self, "shutdown_wait_ms", (time.perf_counter() - started) * 1000
                    )
                    return self.evidence()
        object.__setattr__(self, "shutdown_wait_ms", (time.perf_counter() - started) * 1000)
        if self.folder is not None:
            self.validate()
            allowed = {
                "dto.json",
                "preview.png",
                "worker.json",
                "working",
                *("profile_" + key.lower() for key in PROFILE_KEYS),
            }
            if any(path.name not in allowed for path in self.folder.iterdir()):
                object.__setattr__(self, "cleanup_status", "unexpected_entries_retained")
                return self.evidence()
            # Validate a bounded ordinary owned tree before deleting private data.
            rows, total = [], 0
            for path in self.folder.rglob("*"):
                row = path.lstat()
                rows.append((path, row.st_dev, row.st_ino, row.st_size))
                total += row.st_size if stat.S_ISREG(row.st_mode) else 0
                if (
                    len(rows) > 512
                    or total > 32 * 1024 * 1024
                    or row.st_uid != os.getuid()
                    or not (stat.S_ISREG(row.st_mode) or stat.S_ISDIR(row.st_mode))
                    or path.is_symlink()
                ):
                    object.__setattr__(self, "cleanup_status", "unowned_entries_retained")
                    return self.evidence()
            for path, device, inode, size in reversed(rows):
                row = path.lstat()
                if (row.st_dev, row.st_ino, row.st_size) != (device, inode, size):
                    object.__setattr__(self, "cleanup_status", "changed_entries_retained")
                    return self.evidence()
            shutil.rmtree(self.folder)
        object.__setattr__(self, "cleanup_status", "complete")
        object.__setattr__(self, "raw", b"")
        return self.evidence()

    def evidence(self):
        return {
            "worker_pid": self.process.pid if self.process else None,
            "worker_reaped": self.process is None or self.process.poll() is not None,
            "staging_cleanup": self.cleanup_status,
            "retained_staging_path": str(self.folder)
            if self.folder is not None and self.cleanup_status != "complete"
            else None,
            "shutdown_wait_ms": self.shutdown_wait_ms,
            "worker_receipt": self.receipt,
            "worker_exit_code": self.process.returncode if self.process else None,
            "scene_changed": False,
            "preview_file_published": False,
        }
