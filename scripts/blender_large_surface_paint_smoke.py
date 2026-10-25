"""Owned 4096² surface/stencil job and scoped sculpt-mask native benchmark.

Opt-in private interactive runner only. Complete Float32 hashes use packed arrays
and row-stream independent oracles; evidence never contains full pixel buffers.
No viewport capture, project save, native undo or broader artist acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import socket
import struct
import sys
import tempfile
import threading
import time
import traceback
from array import array
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
SIZE = 4096
SOURCE = (0.125, 0.25, 0.5, 1.0)
COLOR = (1.0, 0.5, 0.0, 1.0)
SAMPLES = [
    (0, 0),
    (0, 4095),
    (1088, 2048),
    (2016, 2048),
    (2047, 2048),
    (2048, 2048),
    (2112, 2048),
    (2303, 2303),
    (2016, 2303),
    (2016, 2304),
    (4095, 4095),
]
PROJECTOR = {
    "origin": [0.0, 0.0, 1.0],
    "direction": [0.0, 0.0, -1.0],
    "up": [0.0, 1.0, 0.0],
    "width": 2.0,
    "height": 2.0,
    "near": 0.0,
    "far": 2.0,
}
PARAMS = {
    "image_name": "4K Surface Source",
    "object_name": "4K Surface Quad",
    "uv_layer": "UV",
    "face_indices": [0],
    "projector": PROJECTOR,
    "strokes": [
        {
            "points": [[0.25, 0.5], [0.75, 0.5]],
            "radius_world": 0.125,
            "hardness": 1.0,
            "color": list(COLOR),
            "opacity": 0.5,
        }
    ],
    "stencil": {"image_name": "4K Surface Stencil", "channel": "R"},
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def token(owner: Any) -> dict[str, Any] | None:
    return (
        None
        if owner is None
        else {
            "name": owner.name,
            "pointer": owner.as_pointer(),
            "session_uid": getattr(owner, "session_uid", None),
        }
    )


def digest(values: array) -> str:
    assert values.typecode == "f" and values.itemsize == 4 and sys.byteorder == "little"
    packed = memoryview(values).cast("B")
    result = hashlib.sha256()
    for offset in range(0, len(packed), 1024 * 1024):
        result.update(packed[offset : offset + 1024 * 1024])
    return result.hexdigest()


def stencil_rgba(x: int) -> tuple[float, float, float, float]:
    return (float((x // 64) % 2), 0.25, 0.5, 1.0)


def oracle_rgba(x: int, y: int) -> tuple[float, ...]:
    # Independent analytic capsule in the provided quad's world XY plane.
    wx, wy = -1.0 + (x + 0.5) / 2048.0, -1.0 + (y + 0.5) / 2048.0
    dx = max(-0.5 - wx, 0.0, wx - 0.5)
    amount = 0.5 * stencil_rgba(x)[0] if dx * dx + wy * wy < 0.125**2 else 0.0
    return tuple(
        struct.unpack("<f", struct.pack("<f", a * (1.0 - amount) + b * amount))[0]
        for a, b in zip(SOURCE, COLOR, strict=True)
    )


def independent_oracles() -> dict[str, Any]:
    source_row = array("f", SOURCE) * SIZE
    stencil_row = array("f", (value for x in range(SIZE) for value in stencil_rgba(x)))
    expected = {name: hashlib.sha256() for name in ("source", "stencil", "output")}
    channel = {name: hashlib.sha256() for name in "RGBA"}
    channel_rows = [
        array("f", (stencil_rgba(x)[index] for x in range(SIZE))).tobytes() for index in range(4)
    ]
    source_bytes, stencil_bytes = source_row.tobytes(), stencil_row.tobytes()
    changed = 0
    for y in range(SIZE):
        expected["source"].update(source_bytes)
        expected["stencil"].update(stencil_bytes)
        for index, name in enumerate("RGBA"):
            channel[name].update(channel_rows[index])
        wy = -1.0 + (y + 0.5) / 2048.0
        if abs(wy) >= 0.125:
            expected["output"].update(source_bytes)
            continue
        row = array("f", source_row)
        for x in range(SIZE):
            rgba = oracle_rgba(x, y)
            if rgba != SOURCE:
                changed += 1
                row[x * 4 : x * 4 + 4] = array("f", rgba)
        expected["output"].update(memoryview(row).cast("B"))
    return {
        "sha256_float32_le": {name: value.hexdigest() for name, value in expected.items()},
        "stencil_channel_sha256_float32_le": {
            name: value.hexdigest() for name, value in channel.items()
        },
        "painted_pixels": changed,
        "samples": [{"xy": [x, y], "rgba": list(oracle_rgba(x, y))} for x, y in SAMPLES],
        "source_rgba": list(SOURCE),
        "stencil_pattern": "R=(x//64)%2,G=.25,B=.5,A=1; every row repeats",
        "oracle_scope": "Complete row-stream hashes; analytic hard capsule and exact power-of-two DATA mixing, independent of production helpers",
    }


def enable_fixture_addon() -> Any:
    """Enable the owned factory add-on and require its real preferences entry."""
    from blender_codex_bridge.preferences import get_preferences

    result = bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
    assert result == {"FINISHED"}, result
    addon = bpy.context.preferences.addons.get("blender_codex_bridge")
    assert addon is not None, "Enabled add-on has no Blender preferences entry"
    prefs = get_preferences()
    assert prefs is not None, "Live add-on preferences unavailable"
    assert prefs.auto_start is False, "Factory add-on must not auto-start a listener"
    return prefs


def owned_entry() -> tuple[Path, str, dict[str, Any]]:
    assert not bool(getattr(bpy.app, "background", True)), (
        "Use the isolated private interactive runner"
    )
    assert threading.current_thread() is threading.main_thread() and sys.byteorder == "little"
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    process = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(process) == 32 and all(value in "0123456789abcdef" for value in process)
    from blender_artist_sidebar_smoke import private_display_manifest

    display = private_display_manifest()  # Before any bpy.context/preferences access.
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    paths = {}
    for key in (
        "TEMP",
        "TMP",
        "TMPDIR",
        "BLENDER_USER_CONFIG",
        "BLENDER_USER_SCRIPTS",
        "BLENDER_USER_DATAFILES",
    ):
        requested = Path(os.environ[key])
        resolved = requested.resolve(strict=True)
        assert requested.is_absolute() and resolved.is_dir() and resolved.is_relative_to(folder)
        assert resolved == folder if key in {"TEMP", "TMP", "TMPDIR"} else resolved.parent == folder
        paths[key] = {"requested": str(requested), "resolved": str(resolved)}
    assert bpy.data.filepath == ""
    return (
        folder,
        process,
        {
            "display": display,
            "paths": paths,
            "factory_startup": True,
            "disable_autoexec": True,
            "interactive": True,
            "no_open_project": True,
        },
    )


class RemoteError(Exception):
    def __init__(self, response: dict[str, Any]):
        super().__init__(str(response))
        self.response = response


class Client:
    """Worker uses sockets/JSON only; no bpy/runtime references cross this path."""

    def __init__(self, port: int):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=310.0)
        self.stream = self.socket.makefile("rb")
        self.sequence = 0

    def call(self, method: str, **params: Any) -> Any:
        self.sequence += 1
        identifier = f"large_surface_{self.sequence}"
        self.socket.sendall(
            canonical(
                {
                    "id": identifier,
                    "method": method,
                    "params": params,
                    "protocol_version": "1.0",
                    "timeout_ms": 300_000,
                }
            )
            + b"\n"
        )
        raw = self.stream.readline(4 * 1024 * 1024 + 1)
        assert 0 < len(raw) <= 4 * 1024 * 1024
        result = json.loads(raw)
        assert result["id"] == identifier, result
        if not result["ok"]:
            raise RemoteError(result)
        return result["result"]

    def close(self) -> None:
        self.stream.close()
        self.socket.close()


class ProofSnapshots:
    """Coalesce periodic proof I/O without discarding any in-memory evidence."""

    interval_seconds = 1.0

    def __init__(self, path: Path, summary_path: Path):
        self.path, self.summary_path = path, summary_path
        assert not summary_path.exists()
        self.last_completed = time.perf_counter()
        self.metrics: dict[str, Any] = {
            "periodic_interval_seconds": self.interval_seconds,
            "periodic_requests": 0,
            "coalesced_periodic_requests": 0,
            "largest_periodic_request_age_seconds": 0.0,
            "snapshot_attempts": 0,
            "snapshot_count": 0,
            "periodic_snapshot_count": 0,
            "immediate_snapshot_count": 0,
            "serialization_seconds": 0.0,
            "write_seconds": 0.0,
            "bytes_serialized": 0,
            "bytes_written": 0,
            "scope": "Full proof snapshots only; excludes this small summary's own serialization/write. Native blocking may delay the unchanged timer beyond its requested cadence.",
        }

    def flush(self, data: dict[str, Any], *, periodic: bool = False) -> None:
        now = time.perf_counter()
        if periodic:
            self.metrics["periodic_requests"] += 1
            age = now - self.last_completed
            self.metrics["largest_periodic_request_age_seconds"] = max(
                self.metrics["largest_periodic_request_age_seconds"], age
            )
            if age < self.interval_seconds:
                self.metrics["coalesced_periodic_requests"] += 1
                return
        self.metrics["snapshot_attempts"] += 1
        started = time.perf_counter()
        try:
            raw = canonical(data) + b"\n"
        finally:
            self.metrics["serialization_seconds"] += time.perf_counter() - started
        self.metrics["bytes_serialized"] += len(raw)
        assert len(raw) < 4 * 1024 * 1024, "Bounded native proof exceeded 4 MiB"
        started = time.perf_counter()
        try:
            self.path.write_bytes(raw)
        finally:
            self.metrics["write_seconds"] += time.perf_counter() - started
        self.metrics["bytes_written"] += len(raw)
        self.metrics["snapshot_count"] += 1
        self.metrics["periodic_snapshot_count" if periodic else "immediate_snapshot_count"] += 1
        self.last_completed = time.perf_counter()

    def finish(self) -> None:
        # Separate counters include the last full write without changing the
        # main proof after its success-marker SHA256 has been printed.
        raw = canonical(self.metrics) + b"\n"
        assert len(raw) < 4096
        self.summary_path.write_bytes(raw)


class Fixture:
    def __init__(self, folder: Path, process: str, attestation: dict[str, Any]):
        self.path = folder / "large-surface-paint-evidence.json"
        assert not self.path.exists()
        self.proof_snapshots = ProofSnapshots(
            self.path, folder / "large-surface-paint-proof-io.json"
        )
        self.events: queue.Queue = queue.Queue()
        self.controls: queue.Queue = queue.Queue()
        self.done = threading.Event()
        self.worker_result: dict[str, Any] = {}
        self.originals: list[tuple[Any, str, Any]] = []
        self.runtime: Any = None
        self.phase = "setup"
        self.started = self.last_tick = self.last_memory = time.perf_counter()
        self.scene, self.layer = bpy.context.scene, bpy.context.scene.view_layers[0]
        self.data: dict[str, Any] = {
            "blender_version": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode(),
            "process_instance": process,
            "owned_profile_attestation": attestation,
            "completed": False,
            "calls": [],
            "jobs": [],
            "controls": [],
            "inclusive_native_helper_intervals": [],
            "fixture_native_intervals": [],
            "memory_samples": [],
            "timer_gaps": {"count": 0, "sum_seconds": 0.0, "largest": []},
            "deadline_seconds": 300.0,
            "proof_snapshot_io": {
                "summary_file": self.proof_snapshots.summary_path.name,
                "periodic_interval_seconds": self.proof_snapshots.interval_seconds,
                "scope": "All bounded raw RPC rows retained; periodic timer snapshots coalesced. Native-helper, control, final and failure snapshots remain immediate. Final I/O totals are retained separately to preserve the main proof hash.",
            },
            "limits": {
                "Windows_qualified": False,
                "release_acceptance": False,
                "visual_review": False,
                "project_saved": False,
                "native_undo_or_recovery_qualified": False,
                "full_artist_workflow_accepted": False,
                "constrained_memory_acceptance": False,
                "individual_product_RNA_write_update_intervals_measured": False,
            },
            "measurement_scope": "Helper intervals delegate once unchanged and include Python/guards plus native work; not individual RNA-call timing. RSS includes whole process/native/GPU/undo allocation; buffer estimates do not.",
            "termination": "Owned os._exit after evidence/stdio flush; no project serialization or native quit/save callbacks",
        }
        self.flush()

    def flush(self, *, periodic: bool = False) -> None:
        self.proof_snapshots.flush(self.data, periodic=periodic)

    def memory(self, label: str) -> None:
        from native_resources import linux_process_memory

        self.data["memory_samples"].append(
            {
                "label": label,
                "elapsed_seconds": time.perf_counter() - self.started,
                **linux_process_memory(),
            }
        )
        assert len(self.data["memory_samples"]) <= 1200

    def timed_fixture_native(self, label: str, callback: Any) -> Any:
        start = time.perf_counter()
        try:
            return callback()
        finally:
            self.data["fixture_native_intervals"].append(
                {"label": label, "seconds": time.perf_counter() - start}
            )
            self.flush()

    def pixels(self, image: Any) -> dict[str, Any]:
        assert (
            tuple(image.size) == (SIZE, SIZE)
            and image.channels == 4
            and len(image.pixels) == SIZE * SIZE * 4
        )
        values = array("f", [0.0]) * len(image.pixels)
        self.timed_fixture_native(
            "read_complete:" + image.name, lambda values=values: image.pixels.foreach_get(values)
        )
        result = {
            "identity": token(image),
            "size": list(image.size),
            "channels": image.channels,
            "pixels_sha256_float32_le": digest(values),
            "complete_pixel_count": SIZE * SIZE,
            "samples": [
                {"xy": [x, y], "rgba": list(values[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 4])}
                for x, y in SAMPLES
            ],
        }
        del values
        return result

    def image_metadata(self, image: Any) -> dict[str, Any]:
        return {
            "identity": token(image),
            "size": list(image.size),
            "source": image.source,
            "type": image.type,
            "is_float": image.is_float,
            "has_data": image.has_data,
            "channels": image.channels,
            "alpha_mode": image.alpha_mode,
            "colorspace": image.colorspace_settings.name,
            "users": image.users,
        }

    def object_state(self, obj: Any) -> dict[str, Any]:
        result = {
            "identity": token(obj),
            "data": token(obj.data),
            "parent": token(obj.parent),
            "mode": obj.mode,
            "transforms": {
                name: list(getattr(obj, name))
                for name in (
                    "location",
                    "rotation_euler",
                    "rotation_quaternion",
                    "rotation_axis_angle",
                    "scale",
                )
            },
            "rotation_mode": obj.rotation_mode,
        }
        if obj.type == "MESH":
            mesh = obj.data
            result["mesh"] = {
                "vertices": [list(vertex.co) for vertex in mesh.vertices],
                "edges": [list(edge.vertices) for edge in mesh.edges],
                "faces": [list(face.vertices) for face in mesh.polygons],
                "material_indices": [face.material_index for face in mesh.polygons],
                "attributes": [
                    [item.name, item.data_type, item.domain, len(item.data)]
                    for item in mesh.attributes
                ],
                "uv": {
                    layer.name: [list(value.vector) for value in mesh.attributes[layer.name].data]
                    for layer in mesh.uv_layers
                },
                "materials": [token(material) for material in mesh.materials],
            }
        return result

    def snapshot(self) -> dict[str, Any]:
        from blender_artist_target_verification_smoke import checkpoint_state

        flags = [[obj.name, obj.select_get(view_layer=self.layer)] for obj in self.layer.objects]
        active = self.layer.objects.active
        names = (
            "Cube",
            "4K Surface Quad",
            "4K Surface Protected",
            "4K Manual Empty",
            "4K Sculpt Seam",
        )
        return {
            "context": {
                "scene": token(self.scene),
                "view_layer": [self.layer.name, self.layer.as_pointer()],
                "active": token(active),
                "selection_flags": flags,
                "mode": None if active is None else active.mode,
                "frame": [self.scene.frame_current, self.scene.frame_subframe],
            },
            "objects": {name: self.object_state(bpy.data.objects[name]) for name in names},
            "images": {
                name: self.image_metadata(bpy.data.images[name])
                for name in (PARAMS["image_name"], PARAMS["stencil"]["image_name"])
            },
            "material_bindings": {
                material.name: {
                    node.name: token(node.image)
                    for node in material.node_tree.nodes
                    if node.bl_idname == "ShaderNodeTexImage"
                }
                for material in (self.material, self.protected_material)
            },
            "checkpoints": checkpoint_state(self.runtime),
            "scene_custom": {key: self.scene[key] for key in sorted(self.scene.keys())},
            "history": self.runtime.state.history(100),
        }

    def observe(self, owner: Any, name: str, label: str) -> None:
        original = getattr(owner, name)
        self.originals.append((owner, name, original))

        def delegated(*args: Any, **kwargs: Any) -> Any:
            start, completed = time.perf_counter(), False
            try:
                value = original(*args, **kwargs)
                completed = True
                return value
            finally:
                self.data["inclusive_native_helper_intervals"].append(
                    {
                        "helper": label,
                        "phase": self.phase,
                        "seconds": time.perf_counter() - start,
                        "completed": completed,
                        "delegate_calls": 1,
                    }
                )
                assert len(self.data["inclusive_native_helper_intervals"]) <= 1024
                self.flush()

        setattr(owner, name, delegated)

    def make_image(self, name: str, stencil: bool) -> Any:
        image = self.timed_fixture_native(
            "allocate:" + name,
            lambda: bpy.data.images.new(name, SIZE, SIZE, alpha=True, float_buffer=True),
        )
        image.colorspace_settings.name, image.alpha_mode = "Non-Color", "CHANNEL_PACKED"
        row = (
            array("f", (value for x in range(SIZE) for value in stencil_rgba(x)))
            if stencil
            else array("f", SOURCE) * SIZE
        )
        values = row * SIZE
        self.memory("setup_buffer:" + name)
        self.timed_fixture_native(
            "write_complete:" + name, lambda values=values: image.pixels.foreach_set(values)
        )
        self.timed_fixture_native("update:" + name, image.update)
        del values, row
        return image

    def make_mesh(self, name: str, vertices: list, faces: list, uvs: list) -> Any:
        mesh = bpy.data.meshes.new(name + " Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        layer = mesh.uv_layers.new(name="UV")
        attribute = mesh.attributes[layer.name]
        for item, uv in zip(attribute.data, uvs, strict=True):
            item.vector = uv
        obj = bpy.data.objects.new(name, mesh)
        self.scene.collection.objects.link(obj)
        return obj

    def setup(self) -> None:
        from blender_codex_bridge.permissions import Permission, PermissionManager
        from blender_codex_bridge.runtime import get_runtime
        from blender_codex_bridge.tools import image_paint
        from native_resources import linux_available_memory

        self.data["available_memory_before_allocations"] = linux_available_memory()
        assert self.data["available_memory_before_allocations"] >= 8 * 1024**3, (
            "4K fixture requires 8 GiB actual host/cgroup headroom"
        )
        self.data["hardware"] = {
            "platform": sys.platform,
            "machine": os.uname().machine,
            "cpu_count": os.cpu_count(),
            "cpu_model": next(
                (
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                "unavailable",
            ),
        }
        self.data["source_sha256"] = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                ROOT / "scripts/blender_artist_sidebar_smoke.py",
                ROOT / "scripts/native_resources.py",
                ROOT / "scripts/blender_artist_target_verification_smoke.py",
                ROOT / "addon/blender_codex_bridge/jobs.py",
                ROOT / "addon/blender_codex_bridge/tools/image_surface_paint.py",
                ROOT / "addon/blender_codex_bridge/tools/image_masks.py",
                ROOT / "addon/blender_codex_bridge/tools/image_paint.py",
                ROOT / "addon/blender_codex_bridge/tools/sculpt_masks.py",
            )
        }
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
        bpy.context.preferences.view.show_splash = False
        prefs = enable_fixture_addon()
        self.runtime = get_runtime()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = (
            prefs.allow_external_files
        ) = False
        prefs.paint_job_budget_ms = 8
        self.data["addon_preferences_setup"] = {
            "enable_operator_result": ["FINISHED"],
            "live_preferences_entry": True,
            "auto_start": prefs.auto_start,
            "paint_job_budget_ms": prefs.paint_job_budget_ms,
            "disabled_preferences": {
                name: getattr(prefs, name)
                for name in (
                    "allow_execute_python", "allow_save_project", "allow_delete_objects",
                    "allow_external_files",
                )
            },
        }
        grants = {
            permission.value: permission
            in {Permission.INSPECT_SCENE, Permission.EDIT_MATERIALS, Permission.EDIT_MESH}
            for permission in Permission
        }
        self.data["fixture_authoritative_grants"] = grants
        manager = PermissionManager(lambda: dict(grants))
        self.runtime.permissions = self.runtime.executor.permissions = manager
        for toolset in ("materials", "mesh"):
            self.runtime.registry.enable_toolset(toolset)
        self.data["oracles"] = independent_oracles()
        self.flush()
        source, stencil = (
            self.make_image(PARAMS["image_name"], False),
            self.make_image(PARAMS["stencil"]["image_name"], True),
        )
        for name, image in (("source", source), ("stencil", stencil)):
            value = self.pixels(image)
            self.data["initial_" + name] = value
            self.flush()
            assert (
                value["pixels_sha256_float32_le"] == self.data["oracles"]["sha256_float32_le"][name]
            )
        quad = self.make_mesh(
            PARAMS["object_name"],
            [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)],
            [(0, 1, 2, 3)],
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        )
        protected = bpy.data.objects.new("4K Surface Protected", quad.data.copy())
        protected.location.x = 4.0
        self.scene.collection.objects.link(protected)
        for name, obj in (("4K Source Consumer", quad), ("4K Protected Consumer", protected)):
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            material.node_tree.nodes.new("ShaderNodeTexImage").image = source
            material.node_tree.nodes.new("ShaderNodeTexImage").image = stencil
            obj.data.materials.append(material)
            if obj is quad:
                self.material = material
            else:
                self.protected_material = material
        empty = bpy.data.objects.new("4K Manual Empty", None)
        self.scene.collection.objects.link(empty)
        low, high = 0.5 / SIZE, 64.5 / SIZE
        self.make_mesh(
            "4K Sculpt Seam",
            [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)],
            [(0, 1, 2), (0, 2, 3)],
            [(low, low), (high, low), (low, low), (high, low), (low, low), (low, low)],
        )
        self.layer.update()
        self.data["baseline"] = self.snapshot()
        self.memory("baseline")
        self.observe(
            image_paint, "_read", "image_paint._read inclusive native read/guards/allocation"
        )
        self.observe(
            image_paint, "_new", "image_paint._new inclusive allocation/write/update/verification"
        )
        self.observe(
            self.runtime.jobs,
            "_native_commit",
            "PaintJobs._native_commit inclusive native publication",
        )
        for name in ("before_modification", "after_modification", "_snapshot"):
            self.observe(self.runtime.checkpoints, name, "CheckpointManager." + name)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.runtime.start_server("127.0.0.1", port, request_timeout=300.0)
        self.data["literal_loopback_port"] = port
        self.flush()
        self.worker_oracle = json.loads(canonical(self.data["oracles"]))
        threading.Thread(
            target=self.scenario, args=(port,), daemon=True, name="BridgeLargeSurfaceSocketFixture"
        ).start()

    def control(self, action: str, **params: Any) -> Any:
        started = time.perf_counter()
        event, result = threading.Event(), []
        self.controls.put((action, params, event, result))
        assert event.wait(310.0), "Main-thread fixture control did not complete: " + action
        assert len(result) == 1 and result[0]["ok"], result
        self.events.put(
            {"kind": "control_latency", "action": action, "seconds": time.perf_counter() - started}
        )
        return result[0]["value"]

    def apply_control(self, action: str, params: dict[str, Any]) -> Any:
        self.phase = action
        before = self.snapshot()
        result: Any = None
        if action == "pause":
            self.runtime.state.set_paused(True)
        elif action == "resume":
            self.runtime.state.set_paused(False)
        elif action == "manual_empty":
            bpy.data.objects["4K Manual Empty"].location.x = 0.25
            result = "Raw owned manual Empty edit; no bridge mutation or recovery claim"
        elif action == "snapshot":
            result = before
        elif action == "verify_output":
            result = self.pixels(bpy.data.images[params["name"]])
        elif action == "verify_inputs":
            result = {
                key: self.pixels(bpy.data.images[name])
                for key, name in (
                    ("source", PARAMS["image_name"]),
                    ("stencil", PARAMS["stencil"]["image_name"]),
                )
            }
        elif action == "verify_interrupt":
            assert bpy.data.images.get(params["name"]) is None
            assert canonical(before["checkpoints"]) == canonical(params["checkpoint_baseline"])
            assert canonical(before["scene_custom"]) == canonical(params["scene_custom_baseline"])
            result = before
        elif action == "sculpt":
            result = self.sculpt()
        else:
            raise AssertionError(action)
        after = self.snapshot()
        self.data["controls"].append(
            {"action": action, "params": params, "before": before, "after": after}
        )
        self.memory("control:" + action)
        self.flush()
        return result

    def sculpt(self) -> dict[str, Any]:
        rows, selected = [], None
        for channel, reduction, invert in [(name, "MEAN", False) for name in "RGBA"] + [
            ("R", "MIN", False),
            ("R", "MAX", False),
            ("R", "MEAN", True),
        ]:
            request = {
                "object_name": "4K Sculpt Seam",
                "uv_layer": "UV",
                "vertex_indices": [0, 1, 2, 3],
                "image_name": PARAMS["stencil"]["image_name"],
                "channel": channel,
                "corner_reduction": reduction,
                "invert": invert,
            }
            before, start = self.snapshot(), time.perf_counter()
            result = self.runtime.dispatch("mesh.sculpt_mask_sample", request)
            row = {
                "request": request,
                "result": result,
                "before": before,
                "after": self.snapshot(),
                "seconds": time.perf_counter() - start,
                "synchronous_native_copy_hash_and_readback_nonpreemptible": True,
            }
            rows.append(row)
            self.data["sculpt_rows"] = rows
            self.flush()
            split = [0.0, 1.0]
            if invert:
                split = [1.0 - value for value in split]
            first = (
                min(split)
                if reduction == "MIN"
                else max(split)
                if reduction == "MAX"
                else sum(split) / 2.0
            )
            expected = (
                [first, 0.0 if invert else 1.0, 1.0 if invert else 0.0, 1.0 if invert else 0.0]
                if channel == "R"
                else [{"G": 0.25, "B": 0.5, "A": 1.0}[channel]] * 4
            )
            assert result["mask_weights"] == expected and result["corner_counts"] == [2, 1, 2, 1]
            assert result["input_evidence"]["image_size"] == [SIZE, SIZE]
            assert (
                result["input_evidence"]["image_pixels_sha256_float32_le"]
                == self.data["oracles"]["sha256_float32_le"]["stencil"]
            )
            assert (
                result["input_evidence"]["channel_sha256_float32_le"]
                == self.data["oracles"]["stencil_channel_sha256_float32_le"][channel]
            )
            assert canonical(
                {key: value for key, value in before.items() if key != "history"}
            ) == canonical(
                {key: value for key, value in row["after"].items() if key != "history"}
            ), "Readonly sculpt sampling changed measured native/checkpoint state"
            history = row["after"]["history"]
            assert len(history) == len(before["history"]) + 1 and history[1:] == before["history"]
            assert (
                history[0]["tool"] == "mesh.sculpt_mask_sample"
                and history[0]["success"] is True
                # History records the named request scope for inspections too;
                # the independent before/after comparison proves no edit.
                and history[0]["affected_objects"] == [request["object_name"]]
            )
            if channel == "R" and reduction == "MAX" and not invert:
                selected = result
        assert selected is not None
        before = self.snapshot()
        request = {
            "object_name": "4K Sculpt Seam",
            "vertex_indices": [0, 1, 2, 3],
            "mask_weights": selected["mask_weights"],
            "strokes": [
                {
                    "center": [0.0, 0.0, 0.0],
                    "radius": 10.0,
                    "direction": [0.0, 0.0, 1.0],
                    "strength": 0.125,
                    "falloff": "CONSTANT",
                }
            ],
        }
        result = self.runtime.dispatch("mesh.sculpt_brush", request)
        after = self.snapshot()
        sculpt = {
            "request": request,
            "result": result,
            "before": before,
            "after": after,
            "expected_z": [0.125, 0.125, 0.0, 0.0],
            "zero_mask_vertices": [2, 3],
        }
        self.data["scoped_sculpt"] = sculpt
        self.flush()
        assert [
            vertex.co.z for vertex in bpy.data.objects["4K Sculpt Seam"].data.vertices
        ] == sculpt["expected_z"]
        assert canonical(before["objects"]["4K Surface Protected"]) == canonical(
            after["objects"]["4K Surface Protected"]
        )
        return {"sample_rows": len(rows), "scoped_sculpt": sculpt}

    def scenario(self, port: int) -> None:
        client: Client | None = None
        try:
            client = Client(port)

            def call(method: str, **params: Any) -> Any:
                started = time.perf_counter()
                result = client.call(method, **params)
                self.events.put(
                    {
                        "kind": "call",
                        "method": method,
                        "seconds": time.perf_counter() - started,
                        "job_id": result.get("job_id"),
                        "state": result.get("state"),
                        "revision": result.get("revision"),
                        "progress": result.get("progress"),
                    }
                )
                return result

            def start(name: str, limit: float = 300.0) -> dict[str, Any]:
                value = call(
                    "image.paint_surface_job_start",
                    **PARAMS,
                    new_name=name,
                    time_limit_seconds=limit,
                )
                assert (
                    value["accepted"]
                    and value["state"] == "QUEUED"
                    and not value["painting_completed"]
                    and not value["projection_work_started"]
                )
                assert not value["undo_boundary_created"] and value["workload"]["image_size"] == [
                    SIZE,
                    SIZE,
                ]
                assert value["workload"]["large_image_requires_job"] is True
                self.events.put(
                    {"kind": "job_start", "name": name, "result": value, "requested_limit": limit}
                )
                return value

            def wait(job: str, *, progress: bool = False) -> dict[str, Any]:
                deadline, revision = time.monotonic() + 320.0, 0
                while time.monotonic() < deadline:
                    value = call("jobs.inspect", job_id=job)
                    assert value["revision"] >= revision
                    revision = value["revision"]
                    if (
                        progress
                        and value["state"] == "RUNNING"
                        and value["progress"]["completed"] > 0
                    ):
                        return value
                    if value["terminal"]:
                        assert not progress, value
                        self.events.put({"kind": "job_terminal", "result": value})
                        return value
                    time.sleep(0.05)
                raise AssertionError("Job did not reach the requested finite state")

            stamp = time.perf_counter()
            normal = start("4K Surface Painted")
            wait(normal["job_id"], progress=True)
            self.control("pause")
            for _ in range(100):
                paused = call("jobs.inspect", job_id=normal["job_id"])
                if paused["state"] == "PAUSED":
                    break
                assert not paused["terminal"], paused
                time.sleep(0.01)
            assert paused["state"] == "PAUSED" and not paused["execution_started"]
            self.control("manual_empty")
            self.control("resume")
            completed = wait(normal["job_id"])
            elapsed = time.perf_counter() - stamp
            self.events.put(
                {
                    "kind": "normal_wall",
                    "seconds": elapsed,
                    "result_duration_ms": completed["duration_ms"],
                }
            )
            assert (
                completed["state"] == "SUCCEEDED"
                and completed["duration_ms"] <= 300_000.0
                and elapsed <= 300.0
            ), completed
            result = completed["result"]
            output = self.control("verify_output", name="4K Surface Painted")
            oracle = self.worker_oracle
            assert (
                output["pixels_sha256_float32_le"]
                == result["pixels_sha256_float32_le"]
                == oracle["sha256_float32_le"]["output"]
            )
            assert (
                output["samples"] == oracle["samples"]
                and result["painted_pixels"] == oracle["painted_pixels"]
            )
            assert (
                result["candidate_pixel_tests"] == 2 * SIZE * SIZE
                and result["stroke_segment_tests"] == SIZE * SIZE
            )
            assert (
                result["comparison_pixels"] == SIZE * SIZE
                and result["baseline_copy_bytes"] == 0
                and result["ownership_scratch_max_bytes"] <= 16384
            )
            self.events.put({"kind": "complete_native_output", "result": output})

            for kind, name in (
                ("cancel", "4K Surface Cancelled"),
                ("disconnect", "4K Surface Disconnected"),
                ("deadline", "4K Surface Deadline"),
            ):
                interruption_started = time.perf_counter()
                baseline = self.control("snapshot")
                try:
                    accepted = start(name, 1.0 if kind == "deadline" else 300.0)
                except RemoteError as error:
                    # A real 4K freeze can consume the one-second job budget
                    # before acceptance. Keep that measured endpoint distinct.
                    assert (
                        kind == "deadline"
                        and error.response["error"]["code"] == "TIMEOUT"
                        and error.response["error"]["context"]["job_deadline_expired"]
                    )
                    self.events.put(
                        {"kind": "deadline_before_acceptance", "response": error.response}
                    )
                    self.control(
                        "verify_interrupt",
                        name=name,
                        checkpoint_baseline=baseline["checkpoints"],
                        scene_custom_baseline=baseline["scene_custom"],
                    )
                    self.events.put(
                        {
                            "kind": "interruption_wall",
                            "interruption": kind,
                            "seconds": time.perf_counter() - interruption_started,
                            "endpoint": "refused_before_acceptance",
                        }
                    )
                    continue
                if kind == "cancel":
                    wait(accepted["job_id"], progress=True)
                    signal_started = time.perf_counter()
                    call("jobs.cancel", job_id=accepted["job_id"])
                elif kind == "disconnect":
                    signal_started = time.perf_counter()
                    client.close()
                    client = Client(port)
                else:
                    signal_started = time.perf_counter()
                    self.control("pause")
                terminal = wait(accepted["job_id"])
                self.events.put(
                    {
                        "kind": "interruption_wall",
                        "interruption": kind,
                        "seconds": time.perf_counter() - interruption_started,
                        "pause_control_to_terminal_seconds"
                        if kind == "deadline"
                        else "signal_to_terminal_seconds": time.perf_counter() - signal_started,
                        "endpoint": "accepted_then_cancelled",
                    }
                )
                assert (
                    terminal["state"] == "CANCELLED"
                    and not terminal["execution_started"]
                    and not terminal["undo_boundary_created"]
                )
                assert not terminal["error"]["context"].get("possible_mutation", False)
                if kind == "disconnect":
                    assert terminal["error"]["context"]["connection_disconnected"]
                if kind == "deadline":
                    assert terminal["error"]["context"]["job_deadline_expired"]
                    self.control("resume")
                self.control(
                    "verify_interrupt",
                    name=name,
                    checkpoint_baseline=baseline["checkpoints"],
                    scene_custom_baseline=baseline["scene_custom"],
                )
            self.control("sculpt")
            inputs = self.control("verify_inputs")
            assert all(
                inputs[name]["pixels_sha256_float32_le"] == oracle["sha256_float32_le"][name]
                for name in ("source", "stencil")
            )
            self.worker_result.update(inputs=inputs, success=True)
        except BaseException:
            self.worker_result["failure"] = traceback.format_exc()
        finally:
            try:
                if client is not None:
                    client.close()
            except BaseException:
                self.worker_result.setdefault("failure", traceback.format_exc())
            finally:
                self.done.set()

    def tick(self) -> float | None:
        try:
            now = time.perf_counter()
            gap = now - self.last_tick
            self.last_tick = now
            gaps = self.data["timer_gaps"]
            gaps["count"] += 1
            gaps["sum_seconds"] += gap
            gaps["largest"] = sorted(
                [*gaps["largest"], {"seconds": gap, "phase": self.phase}],
                key=lambda item: item["seconds"],
                reverse=True,
            )[:64]
            while not self.events.empty():
                row = self.events.get_nowait()
                if row["kind"] == "call":
                    self.data["calls"].append(row)
                else:
                    self.data["jobs"].append(row)
            assert len(self.data["calls"]) <= 8192 and len(self.data["jobs"]) <= 64
            while not self.controls.empty():
                action, params, event, result = self.controls.get_nowait()
                try:
                    result.append({"ok": True, "value": self.apply_control(action, params)})
                except BaseException:
                    result.append({"ok": False, "error": traceback.format_exc()})
                finally:
                    event.set()
            if now - self.last_memory >= 1.0:
                self.memory("timer")
                self.last_memory = now
            self.flush(periodic=True)
            if not self.done.is_set():
                assert now - self.started < 900.0, (
                    "Owned fixture exceeded its finite supervisor bound"
                )
                return 0.01
            self.data["worker"] = self.worker_result
            self.flush()
            assert (
                self.worker_result.get("success") is True and "failure" not in self.worker_result
            ), self.worker_result
            self.data["retired_job_buffer_observations"] = [
                {
                    "job_id": job.job_id,
                    "state": job.state,
                    "prepared_keys": sorted(job.prepared),
                    "work_is_none": job.work is None,
                    "driver_type": None if job.driver is None else type(job.driver).__name__,
                    "driver_prepared_keys": None
                    if job.driver is None
                    else sorted(job.driver.prepared),
                }
                for job in self.runtime.jobs.history
            ]
            self.flush()
            assert self.runtime.jobs.active is None and all(
                not row["prepared_keys"]
                and row["work_is_none"]
                and row["driver_prepared_keys"] in (None, [])
                for row in self.data["retired_job_buffer_observations"]
            )
            self.data["final"] = self.snapshot()
            self.memory("completed")
            base, final = self.data["baseline"], self.data["final"]
            assert canonical(base["context"]) == canonical(final["context"])
            assert canonical(base["material_bindings"]) == canonical(final["material_bindings"])
            for name in ("Cube", "4K Surface Quad", "4K Surface Protected"):
                assert canonical(base["objects"][name]) == canonical(final["objects"][name])
            assert bpy.data.objects["4K Manual Empty"].location.x == 0.25
            self.data["job_private_containers_cleared"] = True
            self.data["container_release_scope"] = (
                "Observed prepared containers empty and work cleared; allocator/native/GPU/undo memory retention remains in process RSS"
            )
            self.data["completed"] = True
            self.flush()
            print(
                "BLENDER_LARGE_SURFACE_PAINT_OK "
                + json.dumps(
                    {
                        "blender_version": bpy.app.version_string,
                        "evidence_file": str(self.path),
                        "evidence_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                        "image_size": [SIZE, SIZE],
                        "full_uv_quad": True,
                        "distinct_4K_stencil": True,
                        "normal_job_deadline_seconds": 300.0,
                        "complete_input_output_hashes_verified": True,
                        "finite_precommit_interruptions": 3,
                        "sculpt_mask_rows": len(self.data["sculpt_rows"]),
                        **self.data["limits"],
                    },
                    allow_nan=False,
                ),
                flush=True,
            )
            self.finish(0)
        except BaseException:
            self.data["failure"] = traceback.format_exc()
            self.finish(1)
        return None

    def finish(self, status: int) -> None:
        from blender_artist_sidebar_smoke import owned_process_exit

        try:
            for owner, name, original in reversed(self.originals):
                setattr(owner, name, original)
            self.flush()
        except BaseException:
            traceback.print_exc()
            status = 1
        finally:
            try:
                self.proof_snapshots.finish()
            except BaseException:
                traceback.print_exc()
                status = 1
            finally:
                owned_process_exit(status)


def main() -> None:
    folder, process, attestation = owned_entry()
    from blender_artist_sidebar_smoke import owned_process_exit

    proof: Fixture | None = None
    try:
        proof = Fixture(folder, process, attestation)
        proof.setup()
        proof.data["setup_seconds_before_active_timer"] = time.perf_counter() - proof.started
        proof.last_tick = time.perf_counter()
        bpy.app.timers.register(proof.tick, first_interval=0.01)
    except BaseException:
        traceback.print_exc()
        if proof is not None:
            proof.data["failure"] = traceback.format_exc()
            proof.finish(1)
        owned_process_exit(1)


if __name__ == "__main__":
    main()
