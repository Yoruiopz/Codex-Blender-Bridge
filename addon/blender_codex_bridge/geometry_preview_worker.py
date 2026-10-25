"""Installed fixed background renderer for bounded authored geometry previews.

Importing this module does not load Blender, register the add-on, start a child,
read a project or execute a render. CLI inputs only identify an owned private
bundle and random token; scene content comes from the fixed geometry DTO.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import struct
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

if __package__:
    from . import geometry_preview_dto as _dto
else:
    # Blender --python executes this installed file without importing __init__.
    # The only module path is a fixed sibling, never a field from the DTO/CLI.
    _path = Path(__file__).resolve(strict=True).with_name("geometry_preview_dto.py")
    _spec = importlib.util.spec_from_file_location("_bridge_geometry_preview_dto", _path)
    if _spec is None or _spec.loader is None:
        raise ImportError("Installed geometry preview DTO module unavailable")
    _dto = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_dto)

WORKER_SCHEMA = "geometry_preview_worker_v1"
MAX_RECEIPT_BYTES = 64 * 1024
MAX_PNG_BYTES = _dto.MAX_BYTES
DEFAULT_DELTAS = _dto.DEFAULT_DELTAS
LOCAL_LIMIT, LOCATION_LIMIT = _dto.LOCAL_LIMIT, _dto.LOCATION_LIMIT
MAX_SCALE, ROTATION_LIMIT = _dto.MAX_SCALE, _dto.ROTATION_LIMIT
SIZE, SAMPLES = _dto.SIZE, _dto.SAMPLES
PreviewRefused = _dto.PreviewRefused
_bits, _vector, _world_points, _bounds, _require = (
    _dto._bits, _dto._vector, _dto._world_points, _dto._bounds, _dto._require
)
validate_dto, canonical = _dto.validate_dto, _dto.canonical
camera_fit, projected_bounds, validate_png = _dto.camera_fit, _dto.projected_bounds, _dto.validate_png


def validate_bundle(bundle: Path, token: str) -> Path:
    """Reject borrowed paths, links and non-private ownership before file reads."""
    _require(type(token) is str and re.fullmatch(r"[a-f0-9]{32}", token), "Invalid worker token")
    _require(isinstance(bundle, Path) and bundle.is_absolute(), "Absolute owned bundle required")
    _require(hasattr(os, "getuid"), "Owned bundles require the qualified POSIX profile")
    try:
        meta = bundle.lstat()
        _require(stat.S_ISDIR(meta.st_mode) and not bundle.is_symlink(), "Bundle is not a plain directory")
        _require(bundle.resolve(strict=True) == bundle, "Canonical bundle required")
        _require(meta.st_uid == os.getuid() and stat.S_IMODE(meta.st_mode) == 0o700,
                 "Private current-user bundle required")
    except OSError as exc:
        raise PreviewRefused("Owned bundle unavailable") from exc
    return bundle


def _read_owned_file(path: Path, maximum: int) -> bytes:
    """Read at most the declared cap and check the opened file's identity."""
    try:
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1,
                 "Expected an owned regular file")
        _require(stat.S_IMODE(before.st_mode) & 0o077 == 0 and 0 < before.st_size <= maximum,
                 "Private file outside size or permission bounds")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            def identity(metadata):
                return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
            _require(identity(opened) == identity(before), "Input file identity changed")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            _require(identity(after) == identity(before) and len(raw) == before.st_size,
                     "Input changed during bounded read")
        final = path.lstat()
        _require(identity(final) == identity(before) and stat.S_ISREG(final.st_mode),
                 "Input file replaced during bounded read")
        return raw
    except OSError as exc:
        raise PreviewRefused("Owned input unavailable") from exc


def read_dto(bundle: Path) -> tuple[dict[str, Any], str]:
    raw = _read_owned_file(bundle / "dto.json", _dto.MAX_BYTES)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PreviewRefused("Invalid DTO encoding") from exc
    value = validate_dto(value)
    _require(canonical(value) == raw, "Canonical DTO encoding required")
    return value, hashlib.sha256(raw).hexdigest()


def _runtime_identity(bpy: Any) -> dict[str, Any]:
    _require(threading.current_thread() is threading.main_thread(), "Worker requires the main thread")
    _require(bpy.app.background is True and bpy.data.filepath == "", "Factory background worker required")
    version, build = bpy.app.version_string, bpy.app.build_hash
    _require(type(version) is str and 0 < len(version) <= 64 and type(build) is bytes,
             "Invalid Blender identity")
    try:
        build_hash = build.decode("ascii")
    except UnicodeError as exc:
        raise PreviewRefused("Invalid Blender build hash") from exc
    _require(re.fullmatch(r"[a-f0-9]{8,64}", build_hash), "Invalid Blender build hash")
    return {"blender_version": version, "build_hash": build_hash, "process_id": os.getpid()}


def _peak_memory() -> dict[str, Any]:
    result = {"available": False, "metric": "ru_maxrss", "scope": "RUSAGE_SELF",
              "value": None, "unit": None, "platform": sys.platform}
    if sys.platform == "linux":
        try:
            import resource

            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if type(value) in {int, float} and math.isfinite(value) and 0 <= value < 2**63:
                result.update(available=True, value=int(value), unit="KiB")
        except (ImportError, OSError):
            pass
    return result


@contextmanager
def _private_creation_mode():
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def _write_receipt(bundle: Path, value: dict[str, Any]) -> None:
    raw = canonical(value)
    _require(len(raw) <= MAX_RECEIPT_BYTES, "Worker receipt exceeds byte budget")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(bundle / "worker.json", flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        _require(stream.write(raw) == len(raw), "Worker receipt write incomplete")
        stream.flush()
        os.fsync(stream.fileno())


def render_worker(bpy: Any, value: Any, output: Path) -> dict[str, Any]:
    """Fixed trusted worker code only. The source process must never call this."""
    _require(bpy.app.background is True, "Render only in the runner-owned background worker")
    _require(isinstance(output, Path), "Owned output Path required")
    _require(output.is_absolute() and not output.is_symlink() and output.parent.resolve(strict=True) == output.parent,
             "Canonical owned worker output required")
    dto = validate_dto(value)
    _require(not output.exists(), "Worker output exists")
    from mathutils import Matrix

    mesh = bpy.data.meshes.new("Isolated Preview Worker Mesh")
    vertices = [_vector(v, 3, LOCAL_LIMIT) for v in dto["mesh"]["vertices"]]
    mesh.from_pydata(vertices, dto["mesh"]["edges"], dto["mesh"]["polygons"])
    obj = bpy.data.objects.new("Isolated Preview Worker Object", mesh)
    scene = bpy.data.scenes.new("Isolated Preview Worker Scene")
    scene.collection.objects.link(obj)
    t = dto["transform"]
    obj.rotation_mode = "XYZ"
    for name in ("location", "rotation_euler", "scale", *DEFAULT_DELTAS):
        setattr(obj, name, _vector(t[name], 4 if name == "delta_rotation_quaternion" else 3,
                                  LOCATION_LIMIT if name == "location" else
                                  ROTATION_LIMIT if name == "rotation_euler" else MAX_SCALE))
    actual_vertices = [[_bits(x, LOCAL_LIMIT) for x in v.co] for v in mesh.vertices]
    _require(actual_vertices == dto["mesh"]["vertices"], "Reconstructed vertex bits differ")
    _require(sorted(tuple(sorted(e.vertices)) for e in mesh.edges) ==
             sorted(tuple(sorted(e)) for e in dto["mesh"]["edges"]), "Reconstructed complete edge set differs")
    _require([list(p.vertices) for p in mesh.polygons] == dto["mesh"]["polygons"], "Reconstructed faces differ")
    for name in ("location", "rotation_euler", "scale", *DEFAULT_DELTAS):
        _require([struct.pack("<f", x).hex() for x in getattr(obj, name)] == t[name], "Worker raw channels differ")
    # A single new opaque geometry material; original material appearance is not copied.
    material = bpy.data.materials.new("Isolated Preview Worker Opaque")
    material.diffuse_color = (.55, .7, .9, 1.)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (.55, .7, .9, 1.)
    bsdf.inputs["Roughness"].default_value = .65
    mesh.materials.append(material)
    for p in mesh.polygons:
        p.use_smooth = False
    camera_data = bpy.data.cameras.new("Isolated Preview Worker Camera")
    camera = bpy.data.objects.new("Isolated Preview Worker Camera", camera_data)
    scene.collection.objects.link(camera)
    fit = camera_fit(dto)
    camera_rows = [[*(fit[axis][i] for axis in ("right", "up", "back")), fit["location"][i]] for i in range(3)]
    camera_rows.append([0., 0., 0., 1.])
    camera.matrix_world = Matrix(camera_rows)
    camera_data.type = "ORTHO"
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.ortho_scale = fit["ortho_scale"]
    camera_data.clip_start, camera_data.clip_end = fit["clip_start"], fit["clip_end"]
    scene.camera = camera
    light_data = bpy.data.lights.new("Isolated Preview Worker Area", "AREA")
    light = bpy.data.objects.new("Isolated Preview Worker Area", light_data)
    scene.collection.objects.link(light)
    light.matrix_world = camera.matrix_world.copy()
    light_data.energy, light_data.size = 1000., max(fit["ortho_scale"], 1.)
    world = bpy.data.worlds.new("Isolated Preview Worker World")
    world.use_nodes = True
    world.node_tree.nodes.get("Background").inputs["Color"].default_value = (.1, .1, .1, 1.)
    scene.world = world
    scene.render.engine = "CYCLES"
    scene.cycles.device, scene.cycles.samples = "CPU", SAMPLES
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.seed = 0
    scene.render.threads_mode, scene.render.threads = "FIXED", 1
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode, scene.render.image_settings.color_depth = "RGBA", "8"
    scene.render.filepath = str(output)
    scene.render.use_file_extension = False
    scene.render.use_stamp = False
    # Explicit worker-only evaluation; never used for the source capture.
    scene.view_layers[0].update()
    observed = [list(obj.matrix_world @ v.co) for v in mesh.vertices]
    expected = _world_points(dto)
    _require(all(abs(a - b) <= max(1e-5, abs(b) * 2**-19)
                 for p, q in zip(observed, expected, strict=True) for a, b in zip(p, q, strict=True)),
             "Worker world bounds differ from independently composed input")
    _require(bpy.ops.render.render(write_still=True, scene=scene.name) == {"FINISHED"}, "Worker render failed")
    png = validate_png(_read_owned_file(output, MAX_PNG_BYTES))
    return {"input_sha256": hashlib.sha256(canonical(dto)).hexdigest(), "geometry_reconstructed": True,
            "raw_channels_reconstructed": True,
            "raw_channel_scope": ["location", "rotation_mode", "rotation_euler", "scale", *DEFAULT_DELTAS],
            "inactive_rotation_channels_copied": False, "edge_identity_scope": "Complete undirected edge set, not native edge allocation/order",
            "world_bounds": _bounds(observed), "camera_fit": fit, "projected_bounds": projected_bounds(dto, fit),
            "png": png, "render_engine": "CYCLES", "device": "CPU", "samples": SAMPLES, "threads": 1,
            "source_process_contacted": False, "source_restore_writes": 0,
            "user_properties_or_ID_references_copied": False,
            "original_material_appearance_copied": False, "project_saved": False}


def run_bundle(bpy: Any, bundle: Path, token: str) -> dict[str, Any]:
    """Consume only declared private files; parent publication is a separate step."""
    started = time.monotonic()
    bundle = validate_bundle(bundle, token)
    identity = _runtime_identity(bpy)
    for name in ("worker.json", "preview.png"):
        path = bundle / name
        _require(not path.exists() and not path.is_symlink(), "Worker output already exists")
    result = {"schema": WORKER_SCHEMA, "status": "failed", "token": token,
              "dto_sha256": None, **identity}
    render_seconds = None
    with _private_creation_mode():
        try:
            value, digest = read_dto(bundle)
            result["dto_sha256"] = digest
            render_started = time.monotonic()
            try:
                rendered = render_worker(bpy, value, bundle / "preview.png")
            finally:
                render_seconds = round(max(0., time.monotonic() - render_started), 6)
            _require(rendered["input_sha256"] == digest, "Rendered DTO identity changed")
            result.update(rendered)
            result["status"] = "succeeded"
        except Exception as exc:
            result["error"] = {"code": "GEOMETRY_PREVIEW_WORKER_FAILED",
                               "type": type(exc).__name__[:64]}
        result["timings"] = {
            "worker_elapsed_seconds": round(max(0., time.monotonic() - started), 6),
            "render_and_validation_seconds": render_seconds,
            "clock": "time.monotonic", "scope": "worker_process",
        }
        result["peak_memory"] = _peak_memory()
        _write_receipt(bundle, result)
    return result


def main(argv: list[str] | None = None) -> int:
    """Fixed installed Blender --python entry; no child process is launched here."""
    if argv is None:
        _require("--" in sys.argv, "Use the fixed background worker command")
        argv = sys.argv[sys.argv.index("--") + 1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args(argv)
    _require(all(flag in sys.argv for flag in ("--background", "--factory-startup", "--disable-autoexec")),
             "Factory background command required")
    validate_bundle(args.bundle, args.token)
    import bpy

    result = run_bundle(bpy, args.bundle, args.token)
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
