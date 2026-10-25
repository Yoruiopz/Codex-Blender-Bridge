# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed installed background reader; never imports the add-on or source scripts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

MAX_FILE = 256 * 1024 * 1024
MAX_EXPECTED = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 1048576
MAX_PACKED_BYTES = 20 * 1024 * 1024
MAX_SCHEMA_DIAGNOSTIC = 256 * 1024
FAILURE_STAGES = frozenset({"build_validation", "program_validation", "input_validation", "runtime_validation",
                            "expected_projection", "reader_preferences", "native_open", "image_preload",
                            "projection_capture", "projection_compare", "final_input_validation"})
PROFILE_REASON_PATTERN = r"[A-Z][A-Z0-9_]*(?::[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)?"


def require(value, reason):
    if not value:
        raise ValueError(reason)


def _failure(cause, stage, profile_refused):
    """Export fixed phase/type facts and only an exact profile code argument."""
    require(stage in FAILURE_STAGES, "Invalid fixed reader failure stage")
    name = type(cause).__name__
    if type(name) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) is None:
        name = "Exception"
    error = {"code": "NATIVE_SAVE_READER_FAILED", "type": name, "failure_stage": stage}
    if type(cause) is profile_refused and stage in {"expected_projection", "projection_capture"}:
        args = cause.args
        if (type(args) is tuple and len(args) == 1 and type(args[0]) is str and 0 < len(args[0]) <= 160
                and re.fullmatch(PROFILE_REASON_PATTERN, args[0]) is not None):
            error["profile_reason"] = args[0]
    return error


def _write_schema_sidecar(bundle, request, request_sha256, row, census):
    """Best-effort failure evidence; never a source of save authority."""
    if census is None or row["status"] != "failed":
        return
    try:
        value = {"schema": "native_save_schema_sidecar_v1", "token": row["token"],
                 "process_id": row["process_id"], "blender_version": row["blender_version"],
                 "build_hash": row["build_hash"], "program": row["program"],
                 "saved_sha256": request["saved_sha256"], "projection_sha256": request["projection_sha256"],
                 "request_sha256": request_sha256, "census": census}
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        if not 0 < len(raw) <= MAX_SCHEMA_DIAGNOSTIC:
            return
        descriptor = os.open(bundle / "schema-census.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        # Diagnostics must not replace the original reader failure or publish.
        return


def file_hash(path, maximum):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
            and not stat.S_IMODE(before.st_mode) & 0o077 and 0 < before.st_size <= maximum,
            "Invalid owned reader input")
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    result = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        current = os.fstat(descriptor)
        require((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) == identity, "Reader input changed")
        count = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            count += len(block)
            require(count <= maximum, "Reader input budget")
            result.update(block)
        current = path.lstat()
        require(count == identity[2] and (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) == identity,
                "Reader input changed")
    finally:
        os.close(descriptor)
    return result.hexdigest()


def _prime_verified_packed_images(data, expected):
    """Decode only verified packed inputs in this fresh reader's owned Main.

    Expected dimensions bound the declared input before any decode-triggering
    size, channels or pixels getter. Every packed payload and role is proved
    first; the ordinary capture still checks the complete decoded projection.
    This helper must never be used to warm an active source project.
    """
    rows = expected.get("images")
    require(type(rows) is list and len(rows) <= 4, "Reader image inventory schema")
    fields = {"name", "fake_user", "native_animation_descriptor_present", "source", "filepath", "size",
              "colorspace", "alpha_mode", "packed_sha256", "packed_bytes", "pixels_sha256"}
    names, pixels, packed_bytes = set(), 0, 0
    for row in rows:
        require(type(row) is dict and set(row) == fields, "Reader image row schema")
        name, size = row["name"], row["size"]
        require(type(name) is str and 0 < len(name.encode()) <= 255 and name not in names,
                "Reader image name schema")
        names.add(name)
        require(row["source"] == "FILE" and type(row["fake_user"]) is bool
                and type(row["native_animation_descriptor_present"]) is bool,
                "Reader packed FILE image required")
        require(all(type(row[key]) is str for key in ("filepath", "colorspace", "alpha_mode"))
                and row["colorspace"] and row["alpha_mode"], "Reader image role schema")
        require(type(size) is list and len(size) == 2
                and all(type(value) is int and 0 < value <= 4096 for value in size), "Reader image size schema")
        pixels += size[0] * size[1]
        require(pixels <= MAX_IMAGE_PIXELS, "Reader image pixel budget")
        count = row["packed_bytes"]
        require(type(count) is int and count > 0, "Reader packed byte schema")
        packed_bytes += count
        require(packed_bytes <= MAX_PACKED_BYTES, "Reader packed byte budget")
        require(all(type(row[key]) is str and re.fullmatch(r"[0-9a-f]{64}", row[key]) is not None
                    for key in ("packed_sha256", "pixels_sha256")), "Reader image digest schema")

    require(len(data.images) == len(rows), "Reader image inventory changed")
    images = list(data.images)
    require(len(images) == len(rows), "Reader image inventory changed")
    owners = {image.name: image for image in images}
    require(len(owners) == len(images) and set(owners) == names, "Reader image names changed")
    for row in rows:
        image = owners[row["name"]]
        require(image.source == "FILE" and image.filepath == row["filepath"]
                and image.colorspace_settings.name == row["colorspace"] and image.alpha_mode == row["alpha_mode"]
                and image.use_fake_user is row["fake_user"], "Reader packed image roles changed")
        packed = image.packed_file
        require(packed is not None and type(packed.size) is int and packed.size == row["packed_bytes"],
                "Reader packed image byte size changed")
        payload = bytes(packed.data)
        require(len(payload) == row["packed_bytes"]
                and hashlib.sha256(payload).hexdigest() == row["packed_sha256"], "Reader packed image bytes changed")

    # No decode-triggering getter runs until *all* declared inputs pass above.
    for image in images:
        image.pixels[0]
        require(image.has_data, "Reader packed image decode failed")


def run(bundle, token):
    import bpy

    started = time.monotonic()
    info = bundle.lstat()
    require(bundle.is_absolute() and bundle.resolve(strict=True) == bundle and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "Private reader bundle required")
    require(re.fullmatch(r"[0-9a-f]{32}", token) is not None, "Invalid reader token")
    require(bpy.app.background and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv,
            "Fresh factory background reader required")
    request_path, expected_path, saved_path = bundle / "request.json", bundle / "expected.json", bundle / "saved.blend"
    request_sha256 = file_hash(request_path, 64 * 1024)
    request_raw = request_path.read_bytes()
    require(hashlib.sha256(request_raw).hexdigest() == request_sha256, "Reader request changed")
    request = json.loads(request_raw)
    require(type(request) is dict and set(request) == {"schema", "token", "saved_sha256", "projection_sha256",
            "binary_sha256", "build_hash", "blender_version", "program"}
            and request["schema"] == "native_save_reader_request_v1" and request["token"] == token,
            "Reader request identity mismatch")
    row = {"schema": "native_save_reader_receipt_v1", "status": "failed", "token": token,
           "saved_sha256": request["saved_sha256"], "projection_sha256": request["projection_sha256"],
           "actual_projection_sha256": None, "program": request["program"], "process_id": os.getpid(),
           "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode("ascii"),
           "native_open_invoked": False, "native_open_completed": False, "declared_projection_reopened": False,
           "source_process_contacted": False, "source_restore_writes": 0, "reader_project_save_invoked": False,
           "native_effect_inventory_complete": False, "timings": {"worker_elapsed_seconds": 0.,
           "native_open_seconds": None, "projection_seconds": None}, "peak_memory": None, "error": None}
    stage, profile_refused, census = "build_validation", None, None
    try:
        require(request["blender_version"] == row["blender_version"] and request["build_hash"] == row["build_hash"],
                "Reader build mismatch")
        stage = "program_validation"
        require(set(request["program"]) == {"native_save_reader.py", "native_save_profile.py"}, "Reader program schema")
        parent = Path(__file__).resolve().parent
        for name, expected in request["program"].items():
            path = parent / name
            require(not path.is_symlink() and path.stat().st_size <= 256 * 1024
                    and hashlib.sha256(path.read_bytes()).hexdigest() == expected, "Reader program changed")
        stage = "input_validation"
        require(file_hash(saved_path, MAX_FILE) == request["saved_sha256"], "Saved input hash mismatch")
        require(file_hash(expected_path, MAX_EXPECTED) == request["projection_sha256"], "Expected projection hash mismatch")
        stage = "runtime_validation"
        binary = Path(bpy.app.binary_path)
        require(not binary.is_symlink() and binary.is_file() and binary.stat().st_size <= 1024 * 1024 * 1024,
                "Reader executable shape")
        binary_hash = hashlib.sha256()
        with binary.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                binary_hash.update(block)
        require(binary_hash.hexdigest() == request["binary_sha256"], "Reader binary hash mismatch")
        sys.path.insert(0, str(parent))
        from native_save_profile import SCHEMA, ProfileRefused, canonical, capture, schema_census

        profile_refused = ProfileRefused
        stage = "expected_projection"
        try:
            census = schema_census(bpy.types)
        except Exception:
            census = None
        expected_raw = expected_path.read_bytes()
        expected = json.loads(expected_raw)
        require(type(expected) is dict and expected.get("schema") == SCHEMA and canonical(expected) == expected_raw,
                "Expected projection framing")
        stage = "reader_preferences"
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
        stage = "native_open"
        row["native_open_invoked"] = True
        native_started = time.monotonic()
        try:
            result = bpy.ops.wm.open_mainfile(filepath=str(saved_path), load_ui=False, use_scripts=False)
        finally:
            row["timings"]["native_open_seconds"] = time.monotonic() - native_started
        require(result == {"FINISHED"}, "Native reader open failed")
        row["native_open_completed"] = True
        projection_started = time.monotonic()
        try:
            stage = "image_preload"
            _prime_verified_packed_images(bpy.data, expected)
            stage = "projection_capture"
            actual = capture(bpy.data)
        finally:
            row["timings"]["projection_seconds"] = time.monotonic() - projection_started
        stage = "projection_compare"
        row["actual_projection_sha256"] = hashlib.sha256(actual.raw).hexdigest()
        require(actual.raw == expected_raw, "Saved authored projection changed")
        stage = "final_input_validation"
        require(file_hash(saved_path, MAX_FILE) == request["saved_sha256"], "Reader input changed during open")
        row["declared_projection_reopened"] = True
        row["status"] = "succeeded"
    except Exception as cause:
        row["error"] = _failure(cause, stage, profile_refused)
        _write_schema_sidecar(bundle, request, request_sha256, row, census)
    finally:
        import resource

        row["peak_memory"] = {"available": True, "metric": "ru_maxrss", "scope": "RUSAGE_SELF",
                              "value": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "unit": "KiB", "platform": sys.platform}
        row["timings"]["worker_elapsed_seconds"] = time.monotonic() - started
        raw = (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        require(len(raw) <= 64 * 1024, "Reader receipt budget")
        descriptor = os.open(bundle / "reader.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return 0 if row["status"] == "succeeded" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    return run(args.bundle, args.token)


if __name__ == "__main__":
    raise SystemExit(main())
