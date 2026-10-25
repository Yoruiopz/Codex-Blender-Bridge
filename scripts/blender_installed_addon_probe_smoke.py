"""Install exact ZIPs into a disposable profile, upgrade, reconnect and roll back.

Only the runner launches this fixture. Its explicit package configuration pins
both archives and all member bytes; no source-checkout imports are permitted.
This development probe is not the complete installed artist acceptance suite.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import re
import shutil
import socket
import stat
import struct
import sys
import threading
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath

import addon_utils  # type: ignore
import bpy  # type: ignore

MODULE = "blender_codex_bridge"
TOOL_NAME = r"[a-z][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+"
PREVIEW_TOOLS = {"preview.geometry_start", "preview.geometry_image"}
PROBE_MARKER = "BLENDER_INSTALLED_ADDON_PROBE_OK "
MAX_PROBE_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_PROBE_MARKER_BYTES = 32 * 1024


def _preview_expected(record: dict, surface: dict) -> bool:
    """Capability pins, never a version guess, select installed preview checks."""
    actual = PREVIEW_TOOLS.intersection(surface["public_tool_names"])
    assert not actual or actual == PREVIEW_TOOLS, "Incomplete installed preview surface"
    names = record.get("expected_tool_names")
    pinned = None if names is None else PREVIEW_TOOLS.intersection(names)
    assert pinned is None or not pinned or pinned == PREVIEW_TOOLS, "Incomplete pinned preview surface"
    explicit = record.get("expected_geometry_preview")
    if "expected_geometry_preview" in record:
        assert type(explicit) is bool, "Preview expectation must be an explicit bool"
        assert pinned is None or explicit == bool(pinned), "Preview capability pins disagree"
    else:
        assert pinned is not None or not actual, "New preview tools require explicit capability pins"
        explicit = bool(pinned)
    assert explicit == bool(actual), "Installed preview capability differs from pinned expectation"
    return explicit


def _cube_projection(name: str) -> dict:
    """Literal native geometry/channels, independent of packaged DTO helpers."""
    obj = bpy.data.objects[name]
    mesh = obj.data
    assert obj.type == "MESH" and len(mesh.vertices) == 8 and len(mesh.edges) == 12 and len(mesh.polygons) == 6
    vertices = [list(vertex.co) for vertex in mesh.vertices]
    corners = {(x, y, z) for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.)}
    assert {tuple(vertex) for vertex in vertices} == corners, "Installed Cube vertex geometry differs"
    edges = [list(edge.vertices) for edge in mesh.edges]
    actual_edges = {frozenset(tuple(vertices[index]) for index in edge) for edge in edges}
    expected_edges = {frozenset((a, b)) for a in corners for b in corners
                      if sum(x != y for x, y in zip(a, b, strict=True)) == 1}
    assert actual_edges == expected_edges, "Installed Cube edge geometry differs"
    polygons = [list(face.vertices) for face in mesh.polygons]
    expected_faces = {frozenset(point for point in corners if point[axis] == sign)
                      for axis in range(3) for sign in (-1., 1.)}
    assert all(len(face) == 4 for face in polygons)
    assert {frozenset(tuple(vertices[index]) for index in face) for face in polygons} == expected_faces
    assert all(frozenset((tuple(vertices[face[index - 1]]), tuple(vertices[face[index]]))) in actual_edges
               for face in polygons for index in range(4)), "Installed Cube face boundary differs"
    channels = {key: list(getattr(obj, key)) for key in (
        "location", "rotation_euler", "scale", "delta_location", "delta_rotation_euler",
        "delta_rotation_quaternion", "delta_scale")}
    assert obj.rotation_mode == "XYZ" and channels == {
        "location": [1., 2., 3.], "rotation_euler": [0., 0., 0.], "scale": [1., 1., 1.],
        "delta_location": [0., 0., 0.], "delta_rotation_euler": [0., 0., 0.],
        "delta_rotation_quaternion": [1., 0., 0., 0.], "delta_scale": [1., 1., 1.]}
    assert obj.parent is None and obj.animation_data is None and not obj.modifiers and not obj.constraints
    assert mesh.shape_keys is None and len(mesh.materials) == 0
    return {"object_pointer": int(obj.as_pointer()), "object_uid": int(obj.session_uid),
            "mesh_pointer": int(mesh.as_pointer()), "mesh_uid": int(mesh.session_uid),
            "vertices": vertices, "edges": edges, "polygons": polygons,
            "rotation_mode": obj.rotation_mode, "channels": channels,
            "float32_vertices": [[struct.pack("<f", value).hex() for value in vertex] for vertex in vertices],
            "float32_channels": {key: [struct.pack("<f", value).hex() for value in values] for key, values in channels.items()}}


def _cube_dto_sha256(name: str, projection: dict) -> str:
    def bits(values):
        return [struct.pack("<f", value).hex() for value in values]

    dto = {"schema": "stock_geometry_preview_v1", "object_name": name,
           "mesh": {"vertices": [bits(vertex) for vertex in projection["vertices"]],
                    "edges": projection["edges"], "polygons": projection["polygons"]},
           "transform": {"rotation_mode": "XYZ", **{key: bits(value) for key, value in projection["channels"].items()}},
           "render": {"width": 128, "height": 128, "samples": 8, "style": "opaque_flat_geometry"}}
    raw = json.dumps(dto, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _png_proof(encoded: str) -> tuple[bytes, dict]:
    """Independent bounded signature, CRC, dimensions and compressed-row proof."""
    assert type(encoded) is str and 0 < len(encoded) <= 3 * 1024 * 1024
    raw = base64.b64decode(encoded, validate=True)
    assert 8 < len(raw) <= 2 * 1024 * 1024 and raw[:8] == b"\x89PNG\r\n\x1a\n"
    offset, compressed, ended = 8, bytearray(), False
    while offset < len(raw):
        assert offset + 12 <= len(raw)
        size = struct.unpack_from(">I", raw, offset)[0]
        assert size <= 2 * 1024 * 1024 and offset + size + 12 <= len(raw)
        kind, value = raw[offset + 4:offset + 8], raw[offset + 8:offset + 8 + size]
        assert zlib.crc32(kind + value) & 0xffffffff == struct.unpack_from(">I", raw, offset + 8 + size)[0]
        if offset == 8:
            assert kind == b"IHDR" and size == 13 and struct.unpack(">IIBBBBB", value) == (128, 128, 8, 6, 0, 0, 0)
        elif kind == b"IDAT":
            compressed.extend(value)
        elif kind == b"IEND":
            assert size == 0 and offset + 12 == len(raw)
            ended = True
        else:
            assert kind[:1].islower(), "Unexpected critical PNG chunk"
        offset += size + 12
    assert ended and compressed
    decoder = zlib.decompressobj()
    rows = decoder.decompress(compressed, 128 * 513 + 1)
    assert len(rows) == 128 * 513 and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
    assert all(rows[index * 513] <= 4 for index in range(128))
    return raw, {"width": 128, "height": 128, "sha256": hashlib.sha256(raw).hexdigest(),
                 "bytes": len(raw), "compressed_rows_verified": True, "visual_review_performed": False}


def _installed_preview(runtime, label: str, name: str, installed: Path, members: dict, BridgeError) -> dict:
    """Call the installed public tools; only product code starts its worker."""
    assert threading.current_thread() is threading.main_thread()
    builds = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}
    assert sys.platform == "linux" and bpy.app.build_type == b"Release"
    assert bpy.app.build_hash.decode("ascii") == builds[tuple(bpy.app.version)]
    prefs = bpy.context.preferences.addons[MODULE].preferences
    consent_fields = ("allow_inspect_scene", "allow_viewport_capture", "allow_external_files")
    old_consent = {field: getattr(prefs, field) for field in consent_fields}
    assert old_consent["allow_external_files"] is False
    proof = {"completed": False, "label": label, "parent_pid": os.getpid(),
             "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode("ascii"),
             "before": _cube_projection(name), "default_permission_denied": False,
             "scope": "Installed authored Cube geometry preview only; no viewport/material/artist acceptance or Windows qualification."}
    evidence = installed.parent.parent.parent / "installed preview evidence with spaces"
    evidence.mkdir(mode=0o700, exist_ok=True)
    receipt = evidence / (label + ".json")
    job_id = None
    try:
        proof["stage"] = "default_permission_denial"
        try:
            runtime.dispatch("preview.geometry_start", {"object_name": name})
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED" and "ACCESS_EXTERNAL_FILES" in error.context["missing_permissions"]
            proof["default_permission_denied"] = True
        else:
            raise AssertionError("Installed preview bypassed default external-file denial")
        assert runtime.jobs.active is None and _cube_projection(name) == proof["before"]
        for field in consent_fields:
            setattr(prefs, field, True)
        proof["stage"] = "owned_preference_consent"
        proof["consented_permissions"] = runtime.permissions.snapshot()
        assert all(proof["consented_permissions"][key] for key in ("INSPECT_SCENE", "CAPTURE_VIEWPORT", "ACCESS_EXTERNAL_FILES"))
        started = runtime.dispatch("preview.geometry_start", {"object_name": name, "time_limit_seconds": 120})
        proof["accepted"] = started
        assert started["accepted"] is True and started["terminal"] is False
        job_id = started["job_id"]
        owned_job = runtime.jobs.active
        assert owned_job is not None and owned_job.job_id == job_id
        deadline, ticks = time.monotonic() + 125., 0
        proof["stage"] = "manual_main_thread_job_ticks"
        while True:
            row = runtime.dispatch("jobs.inspect", {"job_id": job_id})
            if row["terminal"]:
                break
            assert time.monotonic() < deadline and ticks < 20000, "Installed preview exceeded bounded fixture deadline"
            runtime.jobs.tick()  # Script-mode main thread; native app timers do not advance this loop.
            ticks += 1
            time.sleep(.01)
        proof.update(terminal=row, manual_main_thread_ticks=ticks)
        assert row["state"] == "SUCCEEDED" and row["error"] is None, row
        proof["stage"] = "installed_image_and_worker_verification"
        image = runtime.dispatch("preview.geometry_image", {"preview_id": row["result"]["preview_id"]})
        png, png_proof = _png_proof(image["png_base64"])
        assert {key: value for key, value in image.items() if key != "png_base64"} == row["result"]
        assert image["width"] == 128 and image["height"] == 128 and image["mime_type"] == "image/png"
        assert image["image_sha256"] == png_proof["sha256"]
        metadata, effects = image["worker_evidence"], row["external_effects"]
        worker = metadata["worker"]
        expected_dto = _cube_dto_sha256(name, proof["before"])
        assert image["source_fingerprint"] == started["source_fingerprint"] == expected_dto
        assert worker["dto_sha256"] == worker["input_sha256"] == expected_dto
        assert worker["geometry_reconstructed"] is True and worker["raw_channels_reconstructed"] is True
        assert worker["world_bounds"] == {"min": [0., 1., 2.], "max": [2., 3., 4.]}
        assert worker["build_hash"] == bpy.app.build_hash.decode("ascii") and worker["blender_version"] == bpy.app.version_string
        assert type(worker["process_id"]) is int and worker["process_id"] != os.getpid()
        assert worker["process_id"] == effects["worker_pid"]
        assert worker["png"]["sha256"] == metadata["parent_validated_png"]["sha256"] == png_proof["sha256"]
        assert effects["worker_reaped"] is True and effects["worker_exit_code"] == 0
        assert effects["staging_cleanup"] == "complete" and effects["retained_staging_path"] is None
        assert effects["worker_receipt"] == worker
        resource = owned_job.process
        assert resource.process.pid == worker["process_id"] and resource.process.returncode == 0
        assert resource.folder is not None and not resource.folder.exists() and not resource.folder.is_symlink()
        process_module = importlib.import_module(MODULE + ".geometry_preview_process")
        worker_path = Path(process_module.__file__).resolve().with_name("geometry_preview_worker.py")
        dto_path = worker_path.with_name("geometry_preview_dto.py")
        command = resource.process.args
        assert command[command.index("--python") + 1] == str(worker_path)
        assert command[command.index("--bundle") + 1] == str(resource.folder)
        assert Path(command[0]).resolve() == Path(bpy.app.binary_path).resolve()
        assert all(flag in command for flag in ("--background", "--factory-startup", "--disable-autoexec"))
        program = {}
        for path in (worker_path, dto_path):
            assert path.is_relative_to(installed.resolve()) and " " in str(path)
            member = MODULE + "/" + path.name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == members[member] == metadata["program_sha256"][path.name]
            program[path.name] = {"installed_path": str(path), "zip_member": member, "sha256": digest}
        assert set(metadata["program_sha256"]) == set(program)
        assert _cube_projection(name) == proof["before"] and runtime.jobs.active is None
        assert image["scene_changed"] is False and image["project_saved"] is False
        image_path = evidence / (label + ".png")
        with image_path.open("xb") as stream:
            stream.write(png)
        proof.update(completed=True, after=_cube_projection(name), png=png_proof, png_path=str(image_path),
                     worker_program=program, source_geometry_and_transforms_preserved=True,
                     actual_process_handle_reaped=True, actual_staging_directory_absent=True,
                     worker_and_parent_process_separate=True, stage="complete")
    except Exception as error:
        proof["failure"] = {"type": type(error).__name__[:128], "stage": proof["stage"]}
        raise
    finally:
        try:
            if not proof["completed"] and (job_id is not None or runtime.jobs.active is not None):
                runtime.jobs.cancel_all("installed preview probe failed")
        finally:
            for field, value in old_consent.items():
                setattr(prefs, field, value)
            proof["consent_restored"] = all(getattr(prefs, field) == value for field, value in old_consent.items())
            receipt.write_text(json.dumps(proof, indent=2) + "\n")
    assert proof["consent_restored"]
    return {**proof, "receipt_path": str(receipt)}


def _valid_tool_names(names: object, count: int) -> bool:
    return (type(names) is list and len(names) == count
            and all(type(name) is str and len(name) <= 128 and re.fullmatch(TOOL_NAME, name) is not None for name in names)
            and len(set(names)) == len(names))


def _expected_tool_names(record: dict) -> list[str] | None:
    count = record["expected_tools"]
    assert type(count) is int and 1 <= count <= 4096, "Invalid expected tool count"
    fields = {"expected_tool_names", "expected_tool_names_sha256", "expected_tool_names_source"}
    present = fields.intersection(record)
    if not present:
        return None
    assert present == fields, "Incomplete expected tool-name pins"
    names = record["expected_tool_names"]
    assert _valid_tool_names(names, count) and names == sorted(names), "Invalid expected tool names"
    source = record["expected_tool_names_source"]
    assert type(source) is str and Path(source).is_absolute(), "Invalid expected tool-name source"
    digest = record["expected_tool_names_sha256"]
    assert type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest), "Invalid expected tool-name hash"
    with Path(source).open("rb") as stream:
        payload = stream.read(512 * 1024 + 1)
    assert len(payload) <= 512 * 1024 and hashlib.sha256(payload).hexdigest() == digest, "Expected tool-name file changed"
    original = json.loads(payload)
    assert _valid_tool_names(original, count) and sorted(original) == names, "Pinned tool-name source disagrees with configuration"
    return names


def _public_tool_surface(registry, record: dict) -> dict:
    expected = _expected_tool_names(record)
    listed = registry.list_tools()
    assert type(listed) in (list, tuple) and 1 <= len(listed) <= 4096, "Invalid registry name inventory"
    assert _valid_tool_names(list(listed), len(listed)), "Invalid or duplicate registry names"
    description = registry.describe()
    assert type(description) is dict and type(description.get("tools")) is list, "Invalid registry descriptor inventory"
    descriptors = description["tools"]
    assert len(descriptors) == len(listed), "Registry descriptors omit or add methods"
    public, hidden, described = [], [], []
    for item in descriptors:
        assert type(item) is dict and type(item.get("remote")) is bool, "Registry remote metadata must be an explicit bool"
        name = item.get("name")
        assert _valid_tool_names([name], 1), "Invalid registry descriptor name"
        described.append(name)
        if item["remote"]:
            public.append(name)
        else:
            hidden.append({"name": name, "remote": False})
    assert len(set(described)) == len(described) and set(described) == set(listed), "Duplicate or inconsistent registry descriptors"
    public.sort()
    hidden.sort(key=lambda item: item["name"])
    assert len(public) == record["expected_tools"], {"actual_public_count": len(public), "expected": record["expected_tools"]}
    if expected is not None:
        assert public == expected, {"missing": sorted(set(expected) - set(public)), "extra": sorted(set(public) - set(expected))}
    return {"documented_tool_count": len(public), "public_tool_names": public,
            "public_tool_names_sha256": hashlib.sha256(json.dumps(public, separators=(",", ":")).encode()).hexdigest(),
            "hidden_tool_count": len(hidden), "hidden_tool_metadata": hidden,
            "exact_expected_tool_names_verified": expected is not None,
            "expected_tool_names_source_sha256": record.get("expected_tool_names_sha256")}


def _archive(record: dict, owned: Path, label: str) -> tuple[Path, dict[str, str]]:
    source = Path(record["path"])
    with source.open("rb") as stream:
        payload = stream.read(32 * 1024 * 1024 + 1)
    assert len(payload) <= 32 * 1024 * 1024
    assert hashlib.sha256(payload).hexdigest() == record["sha256"]
    frozen = owned / (label + " package with spaces.zip")
    frozen.write_bytes(payload)
    members: dict[str, str] = {}
    normalized_names: set[str] = set()
    total = 0
    with zipfile.ZipFile(frozen) as archive:
        assert archive.testzip() is None
        for item in archive.infolist():
            name = PurePosixPath(item.filename)
            raw_parts = item.filename.rstrip("/").split("/")
            assert (not name.is_absolute() and ".." not in name.parts
                    and "\\" not in item.filename and ":" not in item.filename
                    and name.parts[0] == MODULE and len(name.parts) > 1)
            assert all(part not in {"", ".", ".."} for part in raw_parts)
            normalized = str(name).casefold()
            assert normalized not in normalized_names
            normalized_names.add(normalized)
            assert stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR)
            if item.is_dir():
                continue
            assert item.filename not in members
            total += item.file_size
            assert total <= 64 * 1024 * 1024 and len(members) < 512
            members[item.filename] = hashlib.sha256(archive.read(item)).hexdigest()
    assert members == record["members_sha256"]
    assert MODULE + "/__init__.py" in members
    return frozen, members


def _unload() -> None:
    if MODULE in sys.modules:
        addon_utils.disable(MODULE, default_set=True)
    for name in tuple(sys.modules):
        if name == MODULE or name.startswith(MODULE + "."):
            del sys.modules[name]
    importlib.invalidate_caches()


def _installed_bytes(root: Path, expected: dict[str, str]) -> None:
    actual = {str(path.relative_to(root.parent)).replace("\\", "/"):
              hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    assert actual == expected, {"missing": sorted(expected.keys() - actual.keys()),
                                "extra": sorted(actual.keys() - expected.keys())}
    for name, module in tuple(sys.modules.items()):
        if name == MODULE or name.startswith(MODULE + "."):
            assert Path(module.__file__).resolve().is_relative_to(root.resolve()), (name, module.__file__)


def _network(runtime, label: str) -> dict:
    # The networking thread only sends bytes; Blender dispatch remains on this
    # fixture's main thread, as the normal timer would do outside a script.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    runtime.start_server("127.0.0.1", port, request_timeout=5.)
    result = {}

    def client() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.) as connection:
                request = {"id": label, "method": "bridge.status", "params": {},
                           "protocol_version": "1.0", "timeout_ms": 5000}
                connection.sendall(json.dumps(request).encode() + b"\n")
                with connection.makefile("rb") as stream:
                    result["response"] = json.loads(stream.readline())
        except Exception as error:
            result["error"] = str(error)

    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8.
    while thread.is_alive() and time.monotonic() < deadline:
        runtime.executor._drain_timer()
        time.sleep(.005)
    thread.join(timeout=.1)
    runtime.stop_server()
    assert not thread.is_alive() and "error" not in result, result
    response = result["response"]
    assert response["id"] == label and response["ok"] is True, response
    return {"id": response["id"], "ok": response["ok"]}


def _exercise(label: str, archive: Path, members: dict, record: dict, scripts: Path) -> dict:
    _unload()
    installed = scripts / "addons" / MODULE
    replaced = installed.exists()
    if replaced:
        # Blender's overwrite installer retains obsolete source files. A clean
        # replacement in this owned disposable profile is the reviewed path;
        # this does not claim preferences migration or UI-uninstall coverage.
        assert not installed.is_symlink() and installed.resolve().is_relative_to(scripts)
        shutil.rmtree(installed)
    assert bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=True) == {"FINISHED"}
    addon_utils.modules_refresh()
    discovered = [module for module in addon_utils.modules() if module.__name__ == MODULE]
    if record.get("require_discovery", True):
        assert len(discovered) == 1 and discovered[0].bl_info.get("version") == tuple(map(int, record["version"].split("."))), discovered
    module = addon_utils.enable(MODULE, default_set=True, persistent=True)
    assert module is not None and addon_utils.check(MODULE)[1]
    _installed_bytes(installed, members)
    runtime = importlib.import_module(MODULE + ".runtime").get_runtime()
    BridgeError = importlib.import_module(MODULE + ".errors").BridgeError
    permissions_module = importlib.import_module(MODULE + ".permissions")
    status = runtime.dispatch("bridge.status", {})
    assert status["addon_version"] == record["version"]
    default_permissions = runtime.permissions.snapshot()
    assert all(default_permissions[key] is False for key in ("DELETE_OBJECTS", "EXECUTE_PYTHON", "ACCESS_EXTERNAL_FILES"))
    assert bpy.context.preferences.addons[MODULE].preferences.auto_start is False
    runtime.dispatch("toolsets.enable", {"name": "objects"})
    try:
        runtime.dispatch("object.delete", {"object_names": ["Cube"]})
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED", error
    else:
        raise AssertionError("Installed default profile granted deletion")
    runtime.dispatch("toolsets.disable", {"name": "objects"})
    public_surface = _public_tool_surface(runtime.registry, record)
    preview_expected = _preview_expected(record, public_surface)
    first = _network(runtime, label + "-connect")
    second = _network(runtime, label + "-reconnect")
    allowed = {permission.value: True for permission in permissions_module.Permission}
    permissions = permissions_module.PermissionManager(lambda: allowed)
    original_permissions, original_executor_permissions = runtime.permissions, runtime.executor.permissions
    try:
        runtime.permissions = runtime.executor.permissions = permissions
        runtime.dispatch("toolsets.enable", {"name": "objects"})
        created = runtime.dispatch("object.create", {"object_type": "CUBE", "name": label + " installed cube"})
        name = created["object"]
        runtime.dispatch("transform.set", {"object_name": name, "location": [1., 2., 3.]})
        assert tuple(bpy.data.objects[name].location) == (1., 2., 3.)
    finally:
        runtime.permissions, runtime.executor.permissions = original_permissions, original_executor_permissions
    preview = (_installed_preview(runtime, label, name, installed, members, BridgeError)
               if preview_expected else {"completed": False, "expected": False,
                                         "reason": "Pinned package capability surface excludes geometry preview."})
    assert runtime.permissions is original_permissions and runtime.executor.permissions is original_executor_permissions
    assert runtime.permissions.snapshot() == default_permissions, "Installed preview left nondefault permission consent"
    _installed_bytes(installed, members)
    return {"label": label, "archive_sha256": record["sha256"], "version": status["addon_version"],
            **public_surface, "installed_members_verified": len(members),
            "module_path": str(Path(module.__file__).resolve()), "default_deletion_denied": True,
            "default_permissions": default_permissions, "discovered_in_addon_list": bool(discovered),
            "clean_directory_replacement": replaced,
            "loopback": [first, second], "created_object": name, "location": [1., 2., 3.],
            "geometry_preview_expected": preview_expected, "geometry_preview": preview,
            "original_permission_manager_identities_restored": True}


def _receipt_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _persist_probe_report(payload: dict, owned: Path, *, process_instance: str, process_id: int) -> str:
    """Retain complete proof; return a compact success line only after exact readback."""
    assert type(process_instance) is str and re.fullmatch(r"[0-9a-f]{32}", process_instance)
    assert type(process_id) is int and process_id > 0
    assert owned.is_dir() and not owned.is_symlink()
    assert not {"schema_version", "case", "process_instance", "process_id"}.intersection(payload)
    observations = payload["observations"]
    assert type(observations) is list and [row["label"] for row in observations] == [
        "fresh-candidate", "previous", "upgrade", "rollback"]
    full = {**payload, "schema_version": 1, "case": "installed_addon_probe",
            "process_instance": process_instance, "process_id": process_id}
    raw = _receipt_json(full) + b"\n"
    assert 0 < len(raw) <= MAX_PROBE_RECEIPT_BYTES, "Installed probe receipt exceeds its 4 MiB bound"
    digest = hashlib.sha256(raw).hexdigest()
    receipt = owned / "installed-probe-full-receipt.json"
    compact = []
    for row in observations:
        summary = {key: row[key] for key in (
            "label", "archive_sha256", "version", "documented_tool_count", "public_tool_names_sha256",
            "hidden_tool_count", "exact_expected_tool_names_verified", "installed_members_verified",
            "default_deletion_denied", "discovered_in_addon_list", "clean_directory_replacement",
            "original_permission_manager_identities_restored", "loopback", "created_object", "location",
            "geometry_preview_expected")}
        preview = row["geometry_preview"]
        expected = row["geometry_preview_expected"]
        assert type(expected) is bool and type(preview["completed"]) is bool
        assert preview["completed"] is expected
        summary["geometry_preview"] = {
            "expected": expected, "completed": preview["completed"],
            "full_preview_sha256": hashlib.sha256(_receipt_json(preview)).hexdigest(),
            "png_sha256": preview["png"]["sha256"] if expected else None,
            **{key: preview.get(key) for key in (
                "source_geometry_and_transforms_preserved", "actual_process_handle_reaped",
                "actual_staging_directory_absent", "worker_and_parent_process_separate", "consent_restored")}}
        summary["observation_sha256"] = hashlib.sha256(_receipt_json(row)).hexdigest()
        compact.append(summary)
    marker = {**{key: payload[key] for key in (
        "blender_version", "configuration_sha256", "unregistered_after_probe", "project_saved",
        "user_preferences_saved", "scope", "release_readiness")},
        "schema_version": 1, "case": "installed_addon_probe", "process_instance": process_instance,
        "process_id": process_id, "observations_compact": True, "observations": compact,
        "full_observations_sha256": hashlib.sha256(_receipt_json(observations)).hexdigest(),
        "full_receipt": {"path": str(receipt), "sha256": digest, "bytes": len(raw), "schema_version": 1}}
    line = PROBE_MARKER + _receipt_json(marker).decode("ascii")
    assert len((line + "\n").encode("ascii")) <= MAX_PROBE_MARKER_BYTES, "Installed probe marker exceeds 32 KiB"
    with receipt.open("xb") as stream:
        assert stream.write(raw) == len(raw)
    with receipt.open("rb") as stream:
        readback = stream.read(MAX_PROBE_RECEIPT_BYTES + 1)
    assert len(readback) <= MAX_PROBE_RECEIPT_BYTES and readback == raw, "Installed probe receipt readback differs"
    assert hashlib.sha256(readback).hexdigest() == digest, "Installed probe receipt hash differs"
    assert json.loads(readback) == full, "Installed probe JSON proof was not preserved"
    return line


def main() -> None:
    config_path = os.environ.get("BRIDGE_TEST_PACKAGE_PROBE_CONFIG")
    assert config_path, "Select explicit pinned ZIPs with --package-probe-config"
    with Path(config_path).open("rb") as stream:
        config_bytes = stream.read(512 * 1024 + 1)
    assert len(config_bytes) <= 512 * 1024
    config = json.loads(config_bytes)
    assert config["schema_version"] == 1 and set(config) == {"schema_version", "candidate", "previous"}
    for record in (config["candidate"], config["previous"]):
        _expected_tool_names(record)
    scripts = Path(os.environ["BLENDER_USER_SCRIPTS"]).resolve()
    assert scripts.is_dir() and scripts != Path.home()
    # Keep the caller's user-script folder untouched; the runner supplies this
    # process's unique disposable profile. All ZIP staging paths contain spaces.
    owned = scripts.parent / "package inputs with spaces"
    owned.mkdir(mode=0o700)
    candidate, candidate_members = _archive(config["candidate"], owned, "candidate")
    previous, previous_members = _archive(config["previous"], owned, "previous")
    # Remove every checkout path before the first bridge import. The Blender
    # installer adds the isolated profile's addons directory separately.
    repository = Path(__file__).resolve().parents[1]
    sys.path[:] = [entry for entry in sys.path if entry and not Path(entry).resolve().is_relative_to(repository)]
    assert MODULE not in sys.modules
    observations = []
    try:
        observations.append(_exercise("fresh-candidate", candidate, candidate_members, config["candidate"], scripts))
        observations.append(_exercise("previous", previous, previous_members, config["previous"], scripts))
        observations.append(_exercise("upgrade", candidate, candidate_members, config["candidate"], scripts))
        observations.append(_exercise("rollback", previous, previous_members, config["previous"], scripts))
    finally:
        _unload()
    assert not addon_utils.check(MODULE)[1]
    payload = {
        "blender_version": bpy.app.version_string, "configuration_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "package_configuration": config,
        "observations": observations, "unregistered_after_probe": True,
        "project_saved": False, "user_preferences_saved": False,
        "scope": "Actual isolated installed ZIP enable/disable, exact member/import proof, default denial, loopback reconnect, bounded creation/transform and clean-directory upgrade/rollback. Explicitly pinned preview-capable packages additionally exercise installed public geometry start/inspect/image with real preference denial/consent, worker identity, independent Cube/PNG evidence and cleanup. No preferences migration, UI-uninstall, reviewed appearance, complete installed artist scenarios or Windows qualification. Previous alpha may require known-name enablement because its nonliteral metadata is undiscoverable.",
        "release_readiness": "NOT_ASSESSED"}
    marker = _persist_probe_report(payload, owned,
                                   process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid())
    print(marker, flush=True)


if __name__ == "__main__":
    main()
