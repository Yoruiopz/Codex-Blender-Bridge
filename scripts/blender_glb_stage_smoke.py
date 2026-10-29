"""Opt-in real native GLB construction in an owned interactive factory process.

Import is cold. Direct private-controller calls and labeled synthetic boundary
actions are not queued/public requests, native C failures or durable recovery.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import stat
import struct
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

MARKER = "BLENDER_GLB_STAGE_CONSTRUCTOR_OK "
PROFILE = "GLB_PRIVATE_STAGE_V1"
SCHEMA = "glb_stage_constructor_v1"
MAX_EVIDENCE = 8 * 1024**2
SOURCES = (
    "scripts/blender_glb_stage_smoke.py", "scripts/run_blender_checks.py",
    "scripts/blender_artist_sidebar_smoke.py",
    "addon/blender_codex_bridge/glb_stage_driver.py",
    "addon/blender_codex_bridge/glb_stage_profile.py",
    "addon/blender_codex_bridge/glb_stage_source.py",
    "addon/blender_codex_bridge/glb_stage_state.py",
    "addon/blender_codex_bridge/asset_glb_import_plan.py",
    "addon/blender_codex_bridge/asset_glb_preflight.py",
)
CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
            "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")
POSITIONS = (((-0., 0., 0.), (1., 0., 0.), (0., 1., 0.)),
             ((0., 0., 2.), (2., 0., 2.), (0., 2., 2.)))
MATERIALS = (((.8, .2, .1, .5), .25, .75, True), ((.1, .4, .9, 1.), .6, .2, False))


def bits(value):
    assert type(value) in (int, float) and math.isfinite(value)
    return struct.pack("<f", value).hex()


def numeric(values):
    return [bits(value) for value in values]


def encode(value):
    chunks, length = [], 0
    for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(value):
        raw = part.encode()
        length += len(raw)
        assert length + 1 <= MAX_EVIDENCE, "GLB fixture evidence budget"
        chunks.append(raw)
    return b"".join(chunks) + b"\n"


def file_digest(path, maximum=1024**3):
    """Bounded ordinary descriptor read; refuse symlinks, FIFO and replacement."""
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum
    def identity(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    digest, count = hashlib.sha256(), 0
    try:
        assert identity(os.fstat(descriptor)) == identity(before)
        while True:
            raw = os.read(descriptor, min(65536, maximum + 1 - count))
            if not raw:
                break
            count += len(raw)
            assert count <= maximum
            digest.update(raw)
        assert count == before.st_size and identity(os.fstat(descriptor)) == identity(before)
        assert identity(path.lstat()) == identity(before)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def source_hashes(root):
    return {name: file_digest(root / name, 512 * 1024) for name in SOURCES}


def official_object_helper(obj, build):
    descriptor = inspect.getattr_static(type(obj), "users_collection")
    assert type(descriptor) is property and descriptor.fget is not None
    getter = descriptor.fget
    path = Path(getter.__code__.co_filename).resolve(strict=True)
    expected = {"62c1db4208e8": "0c9927d6907f9796ed3f3b6d96d2a140672c9637230ce1a3eff4229b5f3bf78e",
                "d13f752e3b9c": "f744effeb5ef2278e41902d927d1ff490613c31ead18838700cede64a00febdf"}
    digest = file_digest(path)
    assert getter.__name__ == "users_collection" and digest == expected[build]
    return {"path": str(path), "sha256": digest, "function": getter.__name__,
            "first_line": getter.__code__.co_firstlineno, "scope": "supported official Python property; no passivity claim"}


def source_glb():
    """Fixed independent source: two primitives, two Materials, shared Mesh, empty."""
    binary, views, accessors, primitives = bytearray(), [], [], []

    def accessor(rows, width, component, code):
        binary.extend(b"\0" * (-len(binary) % 4))
        start = len(binary)
        for row in rows:
            binary.extend(struct.pack("<" + code * len(row), *row))
        views.append({"buffer": 0, "byteOffset": start, "byteLength": len(binary) - start})
        accessors.append({"bufferView": len(views) - 1, "componentType": component,
                          "count": len(rows), "type": width})
        return len(accessors) - 1

    for index, positions in enumerate(POSITIONS):
        position = accessor(positions, "VEC3", 5126, "f")
        indices = accessor(((0,), (1,), (2,)), "SCALAR", 5123, "H")
        primitives.append({"attributes": {"POSITION": position}, "indices": indices,
                           "material": 1 - index})
    materials = [{"pbrMetallicRoughness": {"baseColorFactor": color, "metallicFactor": metal,
                  "roughnessFactor": rough}, "alphaMode": "OPAQUE", "doubleSided": double}
                 for color, metal, rough, double in MATERIALS]
    manifest = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1, 2]}],
                "nodes": [{"mesh": 0}, {"mesh": 0}, {}], "meshes": [{"primitives": primitives}],
                "materials": materials, "buffers": [{"byteLength": len(binary)}],
                "bufferViews": views, "accessors": accessors}
    text = json.dumps(manifest, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    binary.extend(b"\0" * (-len(binary) % 4))
    return (b"glTF" + struct.pack("<II", 2, 28 + len(text) + len(binary))
            + struct.pack("<II", len(text), 0x4E4F534A) + text
            + struct.pack("<II", len(binary), 0x004E4942) + bytes(binary))


def owned_entry():
    """Check runner ownership before context, product imports, timers or exit."""
    assert threading.current_thread() is threading.main_thread()
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv, "Use the isolated private interactive runner"
    assert sys.dont_write_bytecode is True
    process = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(process) == 32 and all(c in "0123456789abcdef" for c in process)
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    paths = {}
    for key in ("TEMP", "TMP", "TMPDIR", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        requested = Path(os.environ[key])
        resolved = requested.resolve(strict=True)
        assert requested.is_absolute() and not requested.is_symlink() and resolved.is_dir()
        assert resolved == folder if key in {"TEMP", "TMP", "TMPDIR"} else resolved.parent == folder
        paths[key] = str(resolved)
    assert Path.cwd().resolve() == folder / "working"
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "addon"))
    from scripts.blender_artist_sidebar_smoke import private_display_manifest

    display = private_display_manifest()
    import bpy

    assert bpy.app.background is False and bpy.data.filepath == ""
    assert (tuple(bpy.app.version), bpy.app.build_hash) in {
        ((4, 5, 14), b"62c1db4208e8"), ((5, 2, 2), b"d13f752e3b9c")}
    assert bpy.context.mode == "OBJECT"
    active = bpy.context.view_layer.objects.active
    assert active is not None and active.type != "VOLUME"
    return root, folder, bpy, {"display": display, "paths": paths, "process_instance": process,
                              "main_thread": True, "factory_startup": True, "disable_autoexec": True}


def header(value):
    assert value.library is None and value.override_library is None
    return {"name": value.name, "uid": value.session_uid, "pointer": value.as_pointer(),
            "users": value.users, "fake_user": value.use_fake_user, "class": value.bl_rna.identifier}


def mesh_row(mesh):
    assert len(mesh.vertices) <= 64 and len(mesh.polygons) <= 32 and len(mesh.loops) <= 96
    return {"identity": header(mesh), "coordinates": [numeric(v.co) for v in mesh.vertices],
            "corners": [[loop.vertex_index, loop.edge_index] for loop in mesh.loops],
            "faces": [[p.loop_start, p.loop_total, list(p.vertices), p.material_index, p.use_smooth]
                      for p in mesh.polygons],
            "edges": sorted(sorted(edge.vertices) for edge in mesh.edges),
            "materials": [header(material) for material in mesh.materials]}


def tree_row(tree):
    assert len(tree.nodes) == 2 and len(tree.links) == 1
    nodes = []
    for node in tree.nodes:
        assert node.bl_idname in {"ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"}
        assert len(node.inputs) <= 64
        inputs = []
        for socket in node.inputs:
            if socket.type == "SHADER":
                default = None
            elif socket.type == "BOOLEAN":
                assert type(socket.default_value) is bool
                default = [socket.default_value]
            elif socket.type == "VALUE":
                default = [bits(socket.default_value)]
            else:
                assert socket.type in {"RGBA", "VECTOR"}
                default = numeric(socket.default_value)
            inputs.append({"identifier": socket.identifier, "type": socket.type, "default": default})
        assert len({row["identifier"] for row in inputs}) == len(inputs)
        nodes.append({"type": node.bl_idname, "name": node.name, "location": numeric(node.location),
                      "width": bits(node.width), "mute": node.mute, "inputs": inputs,
                      "active_output": node.is_active_output if node.bl_idname == "ShaderNodeOutputMaterial" else None,
                      "target": node.target if node.bl_idname == "ShaderNodeOutputMaterial" else None})
    return {"identity": header(tree), "nodes": sorted(nodes, key=lambda n: n["type"]),
            "links": sorted([link.from_node.bl_idname, link.from_socket.identifier,
                             link.to_node.bl_idname, link.to_socket.identifier] for link in tree.links)}


def material_row(material):
    return {"identity": header(material), "color": numeric(material.diffuse_color),
            "backface": material.use_backface_culling, "use_nodes": material.use_nodes,
            "tree": None if material.node_tree is None else tree_row(material.node_tree)}


def object_row(obj):
    return {"identity": header(obj), "type": obj.type, "data_uid": None if obj.data is None else obj.data.session_uid,
            "parent_uid": None if obj.parent is None else obj.parent.session_uid,
            "matrix": [bits(v) for row in obj.matrix_local for v in row],
            "channels": {name: numeric(getattr(obj, name)) for name in CHANNELS},
            "collections": sorted(c.session_uid for c in obj.users_collection)}


class Fixture:
    def __init__(self, root, folder, bpy, attestation):
        self.root, self.folder, self.bpy = root, folder, bpy
        self.path = folder / "glb-stage-evidence.json"
        assert not self.path.exists()
        self.started = time.monotonic()
        self.controllers = []
        self.data = {"schema": SCHEMA, "profile": PROFILE, "completed": False,
                     "attestation": attestation, "blender_version": bpy.app.version_string,
                     "version": list(bpy.app.version), "build_hash": bpy.app.build_hash.decode("ascii"),
                     "process_instance": attestation["process_instance"], "process_id": os.getpid(),
                     "main": bpy.data.as_pointer(), "source_sha256": source_hashes(root),
                     "cases": [], "observations": [], "direct_private_controller": True,
                     "queued_or_public_request": False, "project_saved": False,
                     "destination_published": False, "native_failure_injected": False,
                     "unqualified": ["artist destinations", "hidden Main/UI state", "durable recovery",
                                     "Windows", "UV/normals/transforms/alpha/textures/skin/FBX", "full I02/1.0"]}
        binary = Path(bpy.app.binary_path).resolve(strict=True)
        self.data["binary"] = {"path": str(binary), "sha256": file_digest(binary)}

    def flush(self):
        self.path.write_bytes(encode(self.data))

    def sentinel(self):
        return {"mesh": mesh_row(self.sentinel_mesh), "material": material_row(self.sentinel_material),
                "object": object_row(self.sentinel_object)}

    def setup(self):
        # Explicit raw synthetic setup precedes the recorded Bridge boundary.
        # The sentinel is unlinked: no Scene/selection/frame/Area change occurs.
        bpy = self.bpy
        self.sentinel_mesh = bpy.data.meshes.new("GLB Sentinel Mesh")
        self.sentinel_mesh.from_pydata(((10., 0., 0.), (11., 0., 0.), (10., 1., 0.)), (), ((0, 1, 2),))
        self.sentinel_material = bpy.data.materials.new("GLB Sentinel Material")
        self.sentinel_material.use_nodes = True
        self.sentinel_mesh.materials.append(self.sentinel_material)
        self.sentinel_object = bpy.data.objects.new("GLB Sentinel", self.sentinel_mesh)
        self.data["official_object_helper"] = official_object_helper(self.sentinel_object, self.data["build_hash"])
        self.before_sentinel = self.sentinel()
        self.data["raw_setup"] = {"unlinked_sentinel": self.before_sentinel,
                                  "scene_publication": False, "outside_bridge_boundary": True}
        self.source = self.folder / "constructor-input.glb"
        assert not self.source.exists()
        self.source.write_bytes(source_glb())

    def owned(self, controller, stage_id):
        stage = controller._stages.get(stage_id)
        if stage is None:
            return {}
        values = {role: ref.value for role, ref in stage.references.items()}
        rows = {}
        for role, value in values.items():
            kind = role.split(":")[0]
            if kind == "mesh":
                rows[role] = mesh_row(value)
            elif kind == "material":
                rows[role] = material_row(value)
            elif kind == "node_tree":
                rows[role] = tree_row(value)
            elif kind == "object":
                rows[role] = object_row(value)
            else:
                assert kind == "collection"
                rows[role] = {"identity": header(value), "objects": sorted(o.session_uid for o in value.objects),
                              "children": sorted(c.session_uid for c in value.children)}
        return rows

    def run_case(self, name):
        result = {"name": name, "phase": "bootstrap"}
        self.data["cases"].append(result)
        self.flush()
        bridge_error = None
        try:
            from blender_codex_bridge.errors import BridgeError

            bridge_error = BridgeError
            self.construct_case(name, result)
        except BaseException as cause:
            result["status"] = "FAILED"
            result.setdefault("error", cause.to_dict() if bridge_error is not None and isinstance(cause, bridge_error)
                              else {"type": type(cause).__name__})
            result.setdefault("first_failure", traceback.format_exc())
            try:
                self.flush()
            except BaseException:
                result["case_proof_failure"] = traceback.format_exc()
            raise

    def construct_case(self, name, result):
        from blender_codex_bridge.errors import BridgeError, ErrorCode
        from blender_codex_bridge.glb_stage_driver import NativeOperations, PrivateGLBController
        from blender_codex_bridge.glb_stage_profile import digest
        from blender_codex_bridge.glb_stage_source import read_glb_source
        from blender_codex_bridge.glb_stage_state import GLBStageStore

        ops, store = NativeOperations(), GLBStageStore()
        result["native"] = ops.report()  # Pure diagnostic before the first environment getter.
        environment = ops.environment({})
        witness = environment if name != "invalid_context" else {**environment, "frame": environment["frame"] + 1}
        record = store.prepare(read_glb_source(str(self.source), str(self.folder)),
                               "GLB " + name, digest(witness), overwrite_policy="REFUSE")
        action = {"fired": False, "synthetic_validation_signal": True}

        def check():
            stage = controller._stages.get(record.intent.stage_id)
            if action["fired"] or stage is None or not stage.expected.get("mesh:0", {}).get("body", {}).get("vertices"):
                return
            if name not in {"cancel", "owned_change"}:
                return
            action.update(fired=True, native_entries=len(ops.report()["native_entries"]))
            if name == "cancel":
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Synthetic fixture boundary cancellation",
                                  {"fixture_action": "cancel", "real_request_cancel": False})
            mesh = stage.references["mesh:0"].value
            action["before"] = numeric(mesh.vertices[0].co)
            mesh.vertices[0].co[0] = .125
            action["after"] = numeric(mesh.vertices[0].co)

        controller = PrivateGLBController(store, ops, check)
        self.controllers.append((controller, ops, record.intent.stage_id))
        before_entries = len(ops.report()["native_entries"])
        result.update(phase="construct", source_proof=record.intent.source.proof(),
                      plan_sha256=record.intent.plan.normalized_sha256, environment_before=environment,
                      stage_id=record.intent.stage_id, action=action)
        self.flush()
        error = None
        try:
            retained = controller.construct(record.intent.preview_id, record.intent.fingerprint,
                                            list(record.intent.plan.required_accepted_losses))
        except BridgeError as cause:
            # Synthetic local evidence retains the original chained exception;
            # the structured client error above remains redacted.
            result["local_constructor_exception"] = traceback.format_exc()
            error = cause.to_dict()
            retained = controller.retained(record.intent.stage_id) if record.intent.stage_id in controller._stages else store.inspect(record.intent.stage_id)
        diagnostic = ops.report()
        result.update(error=error, retained=retained, native=diagnostic)
        if name == "success":
            assert error is None and retained["state"]["phase"] == "CONSTRUCTED"
            result["status"] = "CONSTRUCTED"
            rows = self.owned(controller, record.intent.stage_id)
            self.verify_rows(result, rows)
        elif name == "invalid_context":
            assert error is not None and len(diagnostic["native_entries"]) == before_entries
            assert record.intent.stage_id not in controller._stages and ops.environment({}) == environment
            assert store.inspect(record.intent.stage_id)["phase"] == "PREPARED"
            result.update(status="REFUSED_BEFORE_ALLOCATION", context_case="declared_destination_witness_mismatch",
                          invalid_mode_or_volume_native_qualified=False)
        else:
            assert error is not None and action["fired"]
            assert len(diagnostic["native_entries"]) == action["native_entries"]
            assert retained["state"]["phase"] == "UNKNOWN" and not retained["native_cleanup_performed"]
            result["status"] = "STOPPED"
            if name == "owned_change":
                assert numeric(controller._stages[record.intent.stage_id].references["mesh:0"].value.vertices[0].co) == action["after"]
        result["sentinel_after"] = self.sentinel()
        self.flush()
        assert result["sentinel_after"] == self.before_sentinel
        if "owned_rows" not in result:
            result["owned_rows"] = self.owned(controller, record.intent.stage_id)
        self.flush()

    def verify_rows(self, result, rows):
        # First conformance failures retain the complete actual arrays rather
        # than only the assertion that rejected them.
        result.update(phase="independent_verify", owned_rows=rows)
        self.flush()
        self.verify_success(rows)

    def verify_success(self, rows):
        assert set(rows) == {"collection", "mesh:0", "material:0", "material:1",
                             "node_tree:0", "node_tree:1", "object:0", "object:1", "object:2"}
        mesh = rows["mesh:0"]
        expected = [numeric((x, -z, y)) for positions in POSITIONS for x, y, z in positions]
        assert mesh["coordinates"] == expected and expected[0][0] == "00000080"
        assert [row[0] for row in mesh["corners"]] == [0, 1, 2, 3, 4, 5]
        assert mesh["faces"] == [[0, 3, [0, 1, 2], 0, False], [3, 3, [3, 4, 5], 1, False]]
        assert mesh["edges"] == [[0, 1], [0, 2], [1, 2], [3, 4], [3, 5], [4, 5]]
        assert [m["uid"] for m in mesh["materials"]] == [rows["material:1"]["identity"]["uid"], rows["material:0"]["identity"]["uid"]]
        assert mesh["identity"]["users"] == 2 and rows["collection"]["identity"]["users"] == 0
        for index, (color, metal, rough, double) in enumerate(MATERIALS):
            material = rows[f"material:{index}"]
            assert material["color"] == numeric(color) and material["backface"] is (not double)
            assert material["use_nodes"] is True
            assert material["tree"]["identity"]["uid"] == rows[f"node_tree:{index}"]["identity"]["uid"]
            assert material["tree"]["links"] == [["ShaderNodeBsdfPrincipled", "BSDF", "ShaderNodeOutputMaterial", "Surface"]]
            assert {n["type"] for n in material["tree"]["nodes"]} == {"ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"}
            output = next(n for n in material["tree"]["nodes"] if n["type"] == "ShaderNodeOutputMaterial")
            assert output["active_output"] is True and output["target"] == "ALL"
            principled = next(n for n in material["tree"]["nodes"] if n["type"] == "ShaderNodeBsdfPrincipled")
            inputs = {s["identifier"]: s["default"] for s in principled["inputs"]}
            assert {name: inputs[name] for name in ("Base Color", "Metallic", "Roughness", "Alpha")} == {
                "Base Color": numeric(color), "Metallic": [bits(metal)], "Roughness": [bits(rough)], "Alpha": [bits(1.)]}
            assert material["identity"]["users"] == 1
        assert [rows[f"object:{i}"]["data_uid"] for i in range(3)] == [mesh["identity"]["uid"], mesh["identity"]["uid"], None]
        collection = rows["collection"]
        assert collection["children"] == []
        assert collection["objects"] == sorted(rows[f"object:{i}"]["identity"]["uid"] for i in range(3))
        identity = [bits(float(row == col)) for row in range(4) for col in range(4)]
        for index in range(3):
            obj = rows[f"object:{index}"]
            assert obj["matrix"] == identity and obj["parent_uid"] is None
            assert obj["collections"] == [collection["identity"]["uid"]] and obj["identity"]["users"] == 1
            assert obj["type"] == ("EMPTY" if index == 2 else "MESH")

    def observation(self, phase, elapsed):
        value = {"sentinel": self.sentinel(), "environment": self.controllers[0][1].environment({}),
                 "owned": [self.owned(controller, stage_id) for controller, _ops, stage_id in self.controllers]}
        if phase == "immediate":
            self.frozen = value
        preserved = value["sentinel"] == self.before_sentinel and value == self.frozen
        self.data["observations"].append({"phase": phase, "elapsed_seconds": elapsed, "preserved": preserved,
                                           "snapshot": value})
        self.flush()
        assert preserved, "Declared data/context changed during actual event-loop delay"

    def run(self):
        try:
            self.setup()
            for name in ("success", "cancel", "owned_change", "invalid_context"):
                self.run_case(name)
            self.returned_at = time.monotonic()
            self.observation("immediate", 0.)
            self.bpy.app.timers.register(self.timer_short, first_interval=.1)
            self.bpy.app.timers.register(self.timer_long, first_interval=.5)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def timer_short(self):
        try:
            elapsed = time.monotonic() - self.returned_at
            assert elapsed >= .1
            self.observation("timer_0_1", elapsed)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def timer_long(self):
        try:
            elapsed = time.monotonic() - self.returned_at
            assert elapsed >= .5
            self.observation("timer_0_5", elapsed)
            assert [row["phase"] for row in self.data["observations"]] == ["immediate", "timer_0_1", "timer_0_5"]
            self.finish(0)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def finish(self, status, failure=None):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit

        exit_status = 1
        try:
            self.data.update(completed=status == 0, duration_seconds=time.monotonic() - self.started)
            if failure is not None:
                self.data["failure"] = failure
            assert source_hashes(self.root) == self.data["source_sha256"], "Source changed during fixture"
            try:
                import resource
                self.data["memory"] = {"peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                       "units": "KiB on qualified Linux fixture host"}
            except ImportError:
                self.data["memory"] = {"peak_rss": None, "supported": False}
            self.flush()
            if status == 0:
                keys = ("schema", "profile", "completed", "version", "blender_version", "build_hash",
                        "process_instance", "process_id", "source_sha256", "binary")
                payload = {key: self.data[key] for key in keys}
                payload["evidence_sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
                print(MARKER + json.dumps(payload, separators=(",", ":")), flush=True)
            exit_status = status
        except BaseException:
            # Keep the first experiment failure and retain proof/exit failures
            # separately. A failed success-marker write must never exit zero.
            detail = traceback.format_exc()
            self.data.setdefault("failure", detail)
            self.data.setdefault("finish_failure", detail)
            self.data["completed"] = False
            try:
                self.flush()
            except BaseException:
                traceback.print_exc()
        finally:
            owned_process_exit(exit_status)


# Separate private structural fixture. The original constructor experiment above
# keeps its schema, source asset, marker and cancellation labels.
STRUCTURE_SCHEMA = "glb_stage_structure_v1"
STRUCTURE_PROFILE = "GLB_PRIVATE_STRUCTURE_V1"
STRUCTURE_MARKER = "BLENDER_GLB_STAGE_STRUCTURE_OK "
STRUCTURE_CASES = ("success", "cancel_after_uv", "encoded_short_drift", "invalid_context")
STRUCTURE_OBSERVATIONS = (("immediate", 0.), ("timer_0_1", .1), ("timer_0_3", .3), ("timer_0_5", .5))
STRUCTURE_VERTICES = ((0., 0., 0.), (1., 0., 0.), (0., 0., 1.),
                      (0., -2., 0.), (1., -2., 0.), (0., -2., 1.))
STRUCTURE_UVS = ((0., 1.), (1., 1.), (0., 0.)) * 2
STRUCTURE_BASIS = (
    ((-1., 0., 0., 2.), (0., 1., 0., -4.), (0., 0., -2., 3.), (0., 0., 0., 1.)),
    ((-1., 0., 0., 1.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.)),
    ((0., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 1.), (0., 0., 0., 1.)),
)
STRUCTURE_WORLDS = (
    STRUCTURE_BASIS[0],
    ((1., 0., 0., 1.), (0., 1., 0., -4.), (0., 0., -2., 3.), (0., 0., 0., 1.)),
    ((0., 0., 0., 2.), (0., 1., 0., -4.), (0., 0., -2., 1.), (0., 0., 0., 1.)),
)
STRUCTURE_WORLD_VERTICES = (
    ((1., -4., 3.), (2., -4., 3.), (1., -4., 1.), (1., -6., 3.), (2., -6., 3.), (1., -6., 1.)),
    ((2., -4., 1.), (2., -4., 1.), (2., -4., -1.), (2., -6., 1.), (2., -6., 1.), (2., -6., -1.)),
)


def structure_source_glb():
    """Literal independent asset; never obtains inputs from the product plan."""
    binary, views, accessors = bytearray(), [], []

    def accessor(rows, width, component, code):
        binary.extend(b"\0" * (-len(binary) % 4))
        start = len(binary)
        for row in rows:
            binary.extend(struct.pack("<" + code * len(row), *row))
        views.append({"buffer": 0, "byteOffset": start, "byteLength": len(binary) - start})
        accessors.append({"bufferView": len(views) - 1, "componentType": component,
                          "count": len(rows), "type": width})
        return len(accessors) - 1

    primitives = []
    for index, z in enumerate((0., 2.)):
        position = accessor(((0., 0., z), (1., 0., z), (0., 1., z)), "VEC3", 5126, "f")
        uv = accessor(((0., 0.), (1., 0.), (0., 1.)), "VEC2", 5126, "f")
        indices = accessor(((0,), (1,), (2,)), "SCALAR", 5123, "H")
        attributes = {"POSITION": position, "TEXCOORD_0": uv}
        if index == 0:
            attributes["NORMAL"] = accessor(((.6, 0., .8),) * 3, "VEC3", 5126, "f")
        primitives.append({"attributes": attributes, "indices": indices, "material": 0})
    manifest = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"children": [1, 2], "translation": [2., 3., 4.],
                   "rotation": [0., 0., 1., 0.], "scale": [1., 2., 1.]},
                  {"mesh": 0, "translation": [1., 0., 0.], "scale": [-1., 1., 1.]},
                  {"mesh": 0, "translation": [0., 1., 0.], "scale": [0., 1., 1.]}],
        "meshes": [{"primitives": primitives}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [.25, .5, .75, 1.],
                        "metallicFactor": .25, "roughnessFactor": .75}, "alphaMode": "OPAQUE"}],
        "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": accessors}
    text = json.dumps(manifest, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    binary.extend(b"\0" * (-len(binary) % 4))
    return (b"glTF" + struct.pack("<II", 2, 28 + len(text) + len(binary))
            + struct.pack("<II", len(text), 0x4E4F534A) + text
            + struct.pack("<II", len(binary), 0x004E4942) + bytes(binary))


def structure_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def structure_numbers(values):
    assert type(values) is list and all(type(value) is str and len(value) == 8 for value in values)
    result = [struct.unpack("<f", bytes.fromhex(value))[0] for value in values]
    assert all(math.isfinite(value) for value in result)
    return result


def structure_close(values, expected, bound=2e-5):
    actual = structure_numbers(values)
    assert len(actual) == len(expected)
    assert all(abs(value - target) <= bound * max(1., abs(target))
               for value, target in zip(actual, expected, strict=True))


def structure_matrix(matrix):
    return [float(value) for row in matrix for value in row]


def structure_multiply(first, second):
    return [[sum(first[row][k] * second[k][column] for k in range(4))
             for column in range(4)] for row in range(4)]


def structure_mesh_row(mesh):
    """Inventory newly owned constructor storage, including selection and shorts.

    Attribute data getters may materialize 5.2 SINGLE storage. These declared
    owned effects do not qualify read-only inspection of an artist's data.
    """
    row = mesh_row(mesh)
    assert len(mesh.attributes) <= 12
    kinds = {"FLOAT_VECTOR": ("vector", 3, float), "FLOAT2": ("vector", 2, float),
             "INT": ("value", 0, int), "INT32_2D": ("value", 2, int),
             "INT16_2D": ("value", 2, int), "BOOLEAN": ("value", 0, bool)}
    attributes = {}
    for attribute in mesh.attributes:
        assert attribute.name not in attributes and attribute.data_type in kinds
        field, width, kind = kinds[attribute.data_type]
        assert len(attribute.data) <= 96
        values = []
        for element in attribute.data:
            value = getattr(element, field)
            if width:
                value = list(value)
                assert len(value) == width and all(type(v) is kind for v in value)
                values.append(numeric(value) if kind is float else value)
            else:
                assert type(value) is kind
                values.append(value)
        attributes[attribute.name] = {"domain": attribute.domain, "type": attribute.data_type, "values": values}
    assert len(mesh.uv_layers) <= 1
    uv = None
    if mesh.uv_layers:
        layer = mesh.uv_layers[0]
        clone, stencil = mesh.uv_layer_clone, mesh.uv_layer_stencil
        uv = {"name": layer.name, "vectors": [numeric(value.vector) for value in layer.uv],
              "active": mesh.uv_layers.active_index,
              "render": next((i for i, item in enumerate(mesh.uv_layers) if item.active_render), None),
              "clone": mesh.uv_layer_clone_index, "stencil": mesh.uv_layer_stencil_index,
              "clone_bound": clone is not None, "stencil_bound": stencil is not None,
              "clone_pointer": None if clone is None else clone.as_pointer(),
              "stencil_pointer": None if stencil is None else stencil.as_pointer(),
              "layer_pointer": layer.as_pointer(), "active_flag": layer.active,
              "render_flag": layer.active_render, "clone_flag": layer.active_clone}
    row.update(attributes=attributes, uv=uv, has_custom_normals=mesh.has_custom_normals,
               decoded_normals=None if not mesh.has_custom_normals else [numeric(n.vector) for n in mesh.corner_normals])
    return row


def structure_object_row(obj):
    row = object_row(obj)
    row.update(rotation_mode=obj.rotation_mode, parent_type=obj.parent_type,
               parent_inverse=numeric(value for values in obj.matrix_parent_inverse for value in values),
               basis=numeric(value for values in obj.matrix_basis for value in values),
               local=numeric(value for values in obj.matrix_local for value in values),
               world=numeric(value for values in obj.matrix_world for value in values),
               children=sorted(child.session_uid for child in obj.children))
    return row


def structure_body(row):
    uv = row["uv"]
    return {"vertices": row["coordinates"], "loops": [loop[0] for loop in row["corners"]],
            "face_ranges": [face[:2] for face in row["faces"]],
            "polygons": [[face[2], face[3], face[4]] for face in row["faces"]],
            "edges": row["edges"], "materials": [], "custom_data": row["attributes"],
            "uv": None if uv is None else {key: uv[key] for key in
                ("name", "vectors", "active", "render", "clone", "stencil", "clone_bound", "stencil_bound")},
            "normals": None if row["decoded_normals"] is None else {"decoded": row["decoded_normals"]}}


def verify_structure_mesh(mesh, *, normals=True, material=True):
    """Pure literal oracle shared with the runner, never product decoder output."""
    assert len(mesh["coordinates"]) == 6
    for actual, wanted in zip(mesh["coordinates"], STRUCTURE_VERTICES, strict=True):
        structure_close(actual, wanted, 0.)
    assert [value[0] for value in mesh["corners"]] == [0, 1, 2, 3, 4, 5]
    assert mesh["faces"] == [[0, 3, [0, 1, 2], 0, False], [3, 3, [3, 4, 5], 0, False]]
    assert mesh["edges"] == [[0, 1], [0, 2], [1, 2], [3, 4], [3, 5], [4, 5]]
    assert len(mesh["materials"]) == int(material)
    attributes = mesh["attributes"]
    required = {"position", ".edge_verts", ".corner_vert", ".corner_edge", "sharp_face", "UVMap",
                ".select_vert", ".select_edge", ".select_poly"}
    if material:
        required.add("material_index")
    if normals:
        required.update(("custom_normal", "sharp_edge"))
    assert required <= set(attributes) <= required | {"material_index"}
    schema = {"position": ("POINT", "FLOAT_VECTOR", 6), ".edge_verts": ("EDGE", "INT32_2D", 6),
              ".corner_vert": ("CORNER", "INT", 6), ".corner_edge": ("CORNER", "INT", 6),
              ".select_vert": ("POINT", "BOOLEAN", 6), ".select_edge": ("EDGE", "BOOLEAN", 6),
              ".select_poly": ("FACE", "BOOLEAN", 2),
              "sharp_face": ("FACE", "BOOLEAN", 2), "UVMap": ("CORNER", "FLOAT2", 6),
              "custom_normal": ("CORNER", "INT16_2D", 6), "sharp_edge": ("EDGE", "BOOLEAN", 6),
              "material_index": ("FACE", "INT", 2)}
    for name, value in attributes.items():
        assert set(value) == {"domain", "type", "values"}
        assert (value["domain"], value["type"], len(value["values"])) == schema[name]
    assert attributes["position"]["values"] == mesh["coordinates"]
    assert attributes[".corner_vert"]["values"] == [0, 1, 2, 3, 4, 5]
    edges = attributes[".edge_verts"]["values"]
    assert sorted(sorted(edge) for edge in edges) == mesh["edges"]
    for start in (0, 3):
        for offset in range(3):
            index = start + offset
            edge = attributes[".corner_edge"]["values"][index]
            assert type(edge) is int and 0 <= edge < 6
            assert sorted(edges[edge]) == sorted((index, start + (offset + 1) % 3))
    for name, count in ((".select_vert", 6), (".select_edge", 6), (".select_poly", 2)):
        values = attributes[name]["values"]
        assert type(values) is list and len(values) == count
        assert all(type(value) is bool and value is True for value in values)
    assert attributes["sharp_face"]["values"] == [True, True]
    if "material_index" in attributes:
        assert attributes["material_index"]["values"] == [0, 0]
    uv = mesh["uv"]
    assert uv["name"] == "UVMap" and uv["vectors"] == [numeric(v) for v in STRUCTURE_UVS]
    assert attributes["UVMap"]["values"] == uv["vectors"]
    assert all(uv[key] is True for key in ("clone_bound", "stencil_bound", "active_flag", "render_flag", "clone_flag"))
    assert [uv[key] for key in ("active", "render", "clone", "stencil")] == [0, 0, 0, 0]
    assert uv["clone_pointer"] == uv["stencil_pointer"] == uv["layer_pointer"] > 0
    if normals:
        assert mesh["has_custom_normals"] is True and len(mesh["decoded_normals"]) == 6
        for actual, expected in zip(mesh["decoded_normals"], ((.6, -.8, 0.),) * 3 + ((0., -1., 0.),) * 3, strict=True):
            structure_close(actual, expected, 5e-4)
        assert all(type(value) is bool for value in attributes["sharp_edge"]["values"])
        assert all(type(pair) is list and len(pair) == 2 and all(type(v) is int and -32767 <= v <= 32767 for v in pair)
                   for pair in attributes["custom_normal"]["values"])
        assert any(pair != [0, 0] for pair in attributes["custom_normal"]["values"][:3])
    else:
        assert mesh["has_custom_normals"] is False and mesh["decoded_normals"] is None


def verify_structure_rows(rows):
    assert set(rows) == {"collection", "mesh:0", "material:0", "node_tree:0", "object:0", "object:1", "object:2"}
    mesh, collection = rows["mesh:0"], rows["collection"]
    verify_structure_mesh(mesh)
    assert mesh["identity"]["users"] == 2 and collection["identity"]["users"] == 0
    assert [value["uid"] for value in mesh["materials"]] == [rows["material:0"]["identity"]["uid"]]
    material = rows["material:0"]
    assert material["color"] == numeric((.25, .5, .75, 1.)) and material["backface"] is True
    assert material["use_nodes"] is True and material["identity"]["users"] == 1
    assert material["tree"] == rows["node_tree:0"]
    assert material["tree"]["links"] == [["ShaderNodeBsdfPrincipled", "BSDF", "ShaderNodeOutputMaterial", "Surface"]]
    nodes = material["tree"]["nodes"]
    assert len(nodes) == 2 and {node["type"] for node in nodes} == {"ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"}
    output = next(node for node in nodes if node["type"] == "ShaderNodeOutputMaterial")
    assert output["active_output"] is True and output["target"] == "ALL"
    shader = next(node for node in nodes if node["type"] == "ShaderNodeBsdfPrincipled")
    inputs = {item["identifier"]: item["default"] for item in shader["inputs"]}
    assert {key: inputs[key] for key in ("Base Color", "Metallic", "Roughness", "Alpha")} == {
        "Base Color": numeric((.25, .5, .75, 1.)), "Metallic": [bits(.25)], "Roughness": [bits(.75)], "Alpha": [bits(1.)]}
    uids = [rows[f"object:{index}"]["identity"]["uid"] for index in range(3)]
    assert collection["children"] == [] and collection["objects"] == sorted(uids)
    composed = []
    for index in range(3):
        obj = rows[f"object:{index}"]
        assert set(obj["channels"]) == set(CHANNELS)
        assert obj["rotation_mode"] == "QUATERNION" and obj["parent_type"] == "OBJECT"
        assert obj["parent_uid"] == (None if index == 0 else uids[0])
        assert obj["children"] == (sorted(uids[1:]) if index == 0 else [])
        assert obj["data_uid"] == (None if index == 0 else mesh["identity"]["uid"])
        assert obj["type"] == ("EMPTY" if index == 0 else "MESH")
        assert obj["collections"] == [collection["identity"]["uid"]] and obj["identity"]["users"] == 1
        structure_close(obj["parent_inverse"], structure_matrix(((1., 0., 0., 0.), (0., 1., 0., 0.),
                        (0., 0., 1., 0.), (0., 0., 0., 1.))), 0.)
        structure_close(obj["basis"], structure_matrix(STRUCTURE_BASIS[index]))
        # Native matrix_local/world are retained, not silently replaced with a
        # planner or forced dependency-graph evaluation in an unlinked stage.
        for field in ("matrix", "local", "world"):
            assert len(structure_numbers(obj[field])) == 16
        structure_close(obj["channels"]["location"], ((2., -4., 3.), (1., 0., 0.), (0., 0., 1.))[index], 0.)
        structure_close(obj["channels"]["scale"], ((1., 1., 2.), (-1., 1., 1.), (0., 1., 1.))[index], 0.)
        structure_close(obj["channels"]["rotation_quaternion"], ((0., 0., 1., 0.), (1., 0., 0., 0.), (1., 0., 0., 0.))[index])
        basis_values = structure_numbers(obj["basis"])
        basis = [basis_values[start:start + 4] for start in range(0, 16, 4)]
        world = basis if index == 0 else structure_multiply(composed[0], basis)
        structure_close(numeric(structure_matrix(world)), structure_matrix(STRUCTURE_WORLDS[index]))
        composed.append(world)
        if index:
            for actual, expected in zip(STRUCTURE_VERTICES, STRUCTURE_WORLD_VERTICES[index - 1], strict=True):
                mapped = [sum(world[row][k] * (*actual, 1.)[k] for k in range(4)) for row in range(3)]
                assert all(abs(v - e) <= 2e-5 for v, e in zip(mapped, expected, strict=True))
    return {"literal_vertices": True, "literal_basis_and_composed_world": True,
            "all_12_instance_vertices": True, "hierarchy_shared_mesh": True,
            "complete_uv_roles_and_storage": True, "decoded_nonaxis_and_auto_normals": True,
            "complete_attribute_and_encoded_short_inventory": True, "material_and_channels": True,
            "raw_native_local_world_retained": True, "depsgraph_evaluated_world_qualified": False}


def verify_structure_entries(entries, case, version):
    """Require complete actual native entries, not a receipt-shaped success flag."""
    prefix = [("NEW_COLLECTION", "collection", "collections.new"),
              ("NEW_MESH", "mesh:0", "meshes.new")]
    prefix.extend(("BUILD_MESH", "mesh:0", entry) for entry in (
        "MeshVertices.add", "MeshLoops.add", "MeshPolygons.add", "vertices.foreach_set:co",
        "polygons.foreach_set:loop_start", "polygons.foreach_set:vertices", "polygons.foreach_set:use_smooth",
        "Mesh.update", "mesh_return.complete_read_attempt"))
    prefix.extend(("NEW_UV_LAYER", "mesh:0", entry) for entry in ("UVLoopLayers.new", "mesh_return.complete_read_attempt"))
    if version[:2] == [5, 2]:
        prefix.extend(("UV_ROLE", "mesh:0", "Mesh." + name) for name in ("uv_layer_clone", "uv_layer_stencil"))
    prefix.append(("WRITE_UV", "mesh:0", "uv.foreach_set:vector"))
    if case == "invalid_context":
        assert entries == []
        return
    if case != "cancel_after_uv":
        prefix.extend(("WRITE_NORMALS", "mesh:0", entry) for entry in (
            "Mesh.normals_split_custom_set", "mesh_return.complete_read_attempt"))
    actual = [(entry["operation"], entry["role"], entry["entry"]) for entry in entries]
    assert actual[:len(prefix)] == prefix
    if case != "success":
        assert actual == prefix
        return
    tail = actual[len(prefix):]
    assert tail[0] == ("NEW_MATERIAL", "material:0", "materials.new")
    if version[:2] == [4, 5]:
        assert tail[1] == ("INIT_MATERIAL", "material:0", "Material.use_nodes")
        tail = tail[2:]
    else:
        tail = tail[1:]
    assert len(tail) >= 14
    assert [entry[:2] for entry in tail[:6]] == [("WRITE_PBR", "material:0")] * 6
    assert [entry[2] for entry in tail[:2]] == ["Material.diffuse_color", "Material.use_backface_culling"]
    assert all(entry[2].endswith(".default_value") for entry in tail[2:6])
    assert tail[6:8] == [("BIND_MATERIALS", "mesh:0", "IDMaterials.append"),
                          ("BIND_MATERIALS", "mesh:0", "polygons.foreach_set:material_index")]
    assert tail[8:14] == [entry for index in range(3) for entry in (
        ("NEW_OBJECT", f"object:{index}", "objects.new"),
        ("LINK_OBJECT", "collection", "CollectionObjects.link"))]
    fields = tail[14:]
    allowed = {"Object.rotation_mode", "Object.location", "Object.rotation_quaternion", "Object.scale", "Object.matrix_parent_inverse", "Object.parent"}
    assert all(operation == "OBJECT_FIELD" and role in {"object:0", "object:1", "object:2"}
               and entry in allowed for operation, role, entry in fields)
    assert fields[-2:] == [("OBJECT_FIELD", "object:1", "Object.parent"),
                           ("OBJECT_FIELD", "object:2", "Object.parent")]
    for role in ("object:0", "object:1", "object:2"):
        assert ("OBJECT_FIELD", role, "Object.rotation_mode") in fields
        assert ("OBJECT_FIELD", role, "Object.location") in fields
        assert ("OBJECT_FIELD", role, "Object.scale") in fields
    assert ("OBJECT_FIELD", "object:0", "Object.rotation_quaternion") in fields


def validate_structure_transcript(proof):
    """Fail closed on partial status/boolean-only models as well as corruption."""
    assert proof["direct_private_controller"] is True and proof["queued_or_public_request"] is False
    assert proof["project_saved"] is False and proof["destination_published"] is False
    assert proof["native_failure_injected"] is False and proof["canonical_cancel_guaranteed"] is False
    cases = proof["cases"]
    assert [row["name"] for row in cases] == list(STRUCTURE_CASES)
    assert [row["status"] for row in cases] == ["CONSTRUCTED", "STOPPED", "STOPPED", "REFUSED_BEFORE_ALLOCATION"]
    success = cases[0]
    assert success["error"] is None and success["retained"]["state"]["phase"] == "CONSTRUCTED"
    assert success["oracles"] == {**verify_structure_rows(success["owned_rows"]), "preservation": True}
    source_bytes = structure_source_glb()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    for row in cases:
        source = row["source_proof"]
        assert source["file_bytes"] == len(source_bytes) and source["file_sha256"] == source_sha
        assert source["source_write_performed"] is False
        assert Path(source["filepath"]).name == "structure-input.glb"
        assert Path(source["filepath"]).parent == Path(source["approved_source_directory"])
        assert type(source["file_identity"]) is list and len(source["file_identity"]) == 4
        assert all(type(value) is int and value >= 0 for value in source["file_identity"])
        preservation = row["preservation_before"]
        assert set(preservation) == {"environment", "sentinel", "home", "filepath", "dirty", "scene_pointer", "layer_pointer", "factory_objects", "nonowned_ids", "window_pointers"}
        assert preservation["filepath"] == "" and type(preservation["dirty"]) is bool
        assert type(preservation["factory_objects"]) is list and len(preservation["factory_objects"]) == 3
        assert Path(preservation["home"]["path"]).is_absolute()
        assert type(preservation["nonowned_ids"]) is list and 3 <= len(preservation["nonowned_ids"]) <= 4096
        assert all(type(item) is list and len(item) == 2 and type(item[0]) is str and type(item[1]) is dict
                   and type(item[1]["uid"]) is int and item[1]["uid"] > 0 for item in preservation["nonowned_ids"])
        assert row["preservation_before"] == row["preservation_after"]
        assert row["oracles"]["preservation"] is True
        report = row["native"]
        assert report["native_storage_effects"] == {
            "scope": "NEW_OWNED_PRIVATE_CONSTRUCTOR_STORAGE",
            "implicit_selection_layers": [".select_vert", ".select_edge", ".select_poly"],
            "attribute_data_reads_may_materialize_storage": True,
            "blender_5_2_SINGLE_materialization_in_scope": proof["version"][:2] == [5, 2],
            "single_materialization_observed": False,
            "artist_read_only_inspection_qualified": False,
            "representation_level_passivity_qualified": False}
        assert report["build"] == {"version": proof["version"], "build_hash": proof["build_hash"]}
        entries = report["native_entries"]
        assert type(entries) is list and len(entries) <= 2048
        for entry in entries:
            assert entry["returned"] is True and entry["interruptible"] is False
            assert type(entry["seconds"]) in (float, int) and math.isfinite(entry["seconds"]) and entry["seconds"] >= 0.
            assert type(entry["entry"]) is str and entry["entry"] and type(entry["operation"]) is str
        verify_structure_entries(entries, row["name"], proof["version"])
        receipts = report["mesh_return_receipts"]
        expected_ops = [] if row["name"] == "invalid_context" else ["BUILD_MESH", "NEW_UV_LAYER"]
        if row["name"] in {"success", "encoded_short_drift"}:
            expected_ops.append("WRITE_NORMALS")
        assert [receipt["operation"] for receipt in receipts] == expected_ops
        for receipt in receipts:
            assert receipt["stage_id"] == row["stage_id"] and receipt["role"] == "mesh:0"
            assert receipt["capture_returned"] is True and receipt["captured_before_generic_callback"] is True
            assert receipt["queued_stop_during_capture_qualified"] is False
            assert any(entry["operation"] == receipt["operation"] and entry["entry"] == "mesh_return.complete_read_attempt" for entry in entries)
        if row["name"] == "invalid_context":
            assert entries == [] and row["error"] is not None and row["oracles"]["zero_native_allocation"] is True
            assert row["context_case"] == "declared_destination_witness_mismatch"
            assert row["invalid_mode_or_volume_native_qualified"] is False
            assert row["owned_rows"] == {}
        elif row["name"] != "success":
            action = row["action"]
            assert action["fired"] is True and action["private_validation_hook"] is True
            assert action["native_entries"] == len(entries) and row["error"] is not None
            assert row["retained"]["state"]["phase"] == "UNKNOWN" and row["retained"]["native_cleanup_performed"] is False
            assert row["owned_rows"]["mesh:0"] == action["after_mesh"]
            if row["name"] == "cancel_after_uv":
                verify_structure_mesh(action["after_mesh"], normals=False, material=False)
                assert action["before_mesh"] == action["after_mesh"]
                assert row["oracles"]["private_cancel_after_uv"] is True
            else:
                verify_structure_mesh(action["before_mesh"], material=False)
                before = action["before_mesh"]["attributes"]["custom_normal"]["values"]
                after = action["after_mesh"]["attributes"]["custom_normal"]["values"]
                assert before != after and before[1:] == after[1:] and before[0][1] == after[0][1]
                assert abs(before[0][0] - after[0][0]) == 1
                assert row["oracles"]["exact_encoded_short_cas_refusal"] is True
        if row["name"] in {"success", "encoded_short_drift"}:
            footprint = row["normal_return_footprint"]
            verify_structure_mesh(footprint["mesh"], material=False)
            body = structure_body(footprint["mesh"])
            assert footprint["body"] == body and footprint["body_sha256"] == structure_digest(body)
            assert footprint["body_sha256"] == receipts[-1]["body_sha256"]
            assert footprint["exact_future_cas"] is True
            if row["name"] == "success":
                for field in ("custom_normal", "sharp_edge", "UVMap", ".select_vert", ".select_edge", ".select_poly"):
                    assert row["owned_rows"]["mesh:0"]["attributes"][field] == footprint["mesh"]["attributes"][field]
            else:
                assert row["error"]["context"]["cause"]["context"]["reason"] == "PRIVATE_OWNED_PREFIX_CHANGED"
    observations = proof["observations"]
    assert [row["phase"] for row in observations] == [phase for phase, _floor in STRUCTURE_OBSERVATIONS]
    baseline, previous = observations[0]["snapshot"], 0.
    assert baseline["owned"] == [row["owned_rows"] for row in cases]
    assert baseline["preservation"] == cases[0]["preservation_before"]
    for row, (phase, floor) in zip(observations, STRUCTURE_OBSERVATIONS, strict=True):
        elapsed = row["elapsed_seconds"]
        assert type(elapsed) in (float, int) and math.isfinite(elapsed) and elapsed >= max(floor, previous)
        assert elapsed == 0. if phase == "immediate" else row["real_timer_callback"] is True
        assert row["preserved"] is True and row["snapshot"] == baseline
        previous = elapsed
    return True


class StructureFixture(Fixture):
    def __init__(self, root, folder, bpy, attestation):
        super().__init__(root, folder, bpy, attestation)
        self.path = folder / "glb-stage-structure-evidence.json"
        assert not self.path.exists()
        self.data.update(schema=STRUCTURE_SCHEMA, profile=STRUCTURE_PROFILE, canonical_cancel_guaranteed=False,
            unqualified=["public/queued requests", "Runtime authority", "guaranteed canonical cancellation",
                         "dependency-graph evaluated world", "images/skin/animation/FBX", "Windows", "full I02/1.0"])

    def flush(self):
        raw = encode(self.data)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            assert stat.S_ISREG(os.fstat(descriptor).st_mode)
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                assert written > 0
                view = view[written:]
        finally:
            os.close(descriptor)

    def setup(self):
        bpy = self.bpy
        self.sentinel_mesh = bpy.data.meshes.new("GLB Structure Sentinel Mesh")
        self.sentinel_mesh.from_pydata(((10., 0., 0.), (11., 0., 0.), (10., 1., 0.)), (), ((0, 1, 2),))
        self.sentinel_material = bpy.data.materials.new("GLB Structure Sentinel Material")
        self.sentinel_material.use_nodes = True
        self.sentinel_mesh.materials.append(self.sentinel_material)
        self.sentinel_object = bpy.data.objects.new("GLB Structure Sentinel", self.sentinel_mesh)
        self.data["official_object_helper"] = official_object_helper(self.sentinel_object, self.data["build_hash"])
        self.before_sentinel = self.sentinel()
        self.source = self.folder / "structure-input.glb"
        descriptor = os.open(self.source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            raw = structure_source_glb()
            assert os.write(descriptor, raw) == len(raw)
        finally:
            os.close(descriptor)
        self.data["raw_setup"] = {"unlinked_sentinel": self.before_sentinel, "outside_bridge_boundary": True,
                                  "source_sha256": file_digest(self.source), "scene_publication": False}

    def owned(self, controller, stage_id):
        rows = super().owned(controller, stage_id)
        stage = controller._stages.get(stage_id)
        if stage is not None:
            for role, ref in stage.references.items():
                if role.startswith("mesh:"):
                    rows[role] = structure_mesh_row(ref.value)
                elif role.startswith("object:"):
                    rows[role] = structure_object_row(ref.value)
        return rows

    def preservation(self, ops, owned):
        bpy = self.bpy
        home = Path(os.environ["HOME"]).resolve(strict=True)
        info = home.stat()
        omitted = {value.session_uid for value in owned.values()}
        nonowned = []
        properties = bpy.data.bl_rna.properties
        assert len(properties) <= 128
        for prop in properties:
            if prop.type != "COLLECTION":
                continue
            collection = getattr(bpy.data, prop.identifier)
            assert len(collection) <= 4096 and len(nonowned) + len(collection) <= 4096
            for value in collection:
                if value.session_uid not in omitted:
                    nonowned.append([prop.identifier, header(value)])
        window = bpy.context.window
        return {"environment": ops.environment(owned), "sentinel": self.sentinel(),
                "nonowned_ids": sorted(nonowned, key=lambda item: (item[0], item[1]["uid"])),
                "window_pointers": None if window is None else [window.as_pointer(), window.screen.as_pointer(), window.workspace.as_pointer()],
                "home": {"path": str(home), "device": info.st_dev, "inode": info.st_ino},
                "filepath": bpy.data.filepath, "dirty": bpy.data.is_dirty,
                "scene_pointer": bpy.context.scene.as_pointer(), "layer_pointer": bpy.context.view_layer.as_pointer(),
                "factory_objects": [structure_object_row(obj) for obj in bpy.context.scene.objects]}

    def construct_case(self, name, result):
        from blender_codex_bridge.errors import BridgeError, ErrorCode
        from blender_codex_bridge.glb_stage_driver import NativeOperations, PrivateGLBController
        from blender_codex_bridge.glb_stage_profile import digest
        from blender_codex_bridge.glb_stage_source import read_glb_source
        from blender_codex_bridge.glb_stage_state import GLBStageStore

        ops, store = NativeOperations(), GLBStageStore()
        environment = ops.environment({})
        witness = environment if name != "invalid_context" else {**environment, "frame": environment["frame"] + 1}
        record = store.prepare(read_glb_source(str(self.source), str(self.folder)), "GLB Structure " + name,
                               digest(witness), overwrite_policy="REFUSE")
        action = {"fired": False, "private_validation_hook": True, "canonical_cancel_guaranteed": False}
        result.update(stage_id=record.intent.stage_id, source_proof=record.intent.source.proof(),
                      plan_sha256=record.intent.plan.normalized_sha256, action=action,
                      preservation_before=self.preservation(ops, {}))

        def check():
            stage = controller._stages.get(record.intent.stage_id)
            if stage is None or not stage.timings:
                return
            operation = stage.timings[-1]["operation"]
            if operation == "WRITE_NORMALS" and "normal_return_footprint" not in result:
                mesh = structure_mesh_row(stage.references["mesh:0"].value)
                body = structure_body(mesh)
                receipts = ops.report()["mesh_return_receipts"]
                assert receipts[-1]["operation"] == "WRITE_NORMALS"
                assert structure_digest(body) == receipts[-1]["body_sha256"]
                verify_structure_mesh(mesh, material=False)
                result["normal_return_footprint"] = {"mesh": mesh, "body": body,
                    "body_sha256": structure_digest(body), "exact_future_cas": True}
            if action["fired"] or (name, operation) not in {("cancel_after_uv", "WRITE_UV"),
                                                              ("encoded_short_drift", "WRITE_NORMALS")}:
                return
            mesh = stage.references["mesh:0"].value
            action.update(fired=True, native_entries=len(ops.report()["native_entries"]),
                          before_mesh=structure_mesh_row(mesh))
            if name == "encoded_short_drift":
                value = mesh.attributes["custom_normal"].data[0]
                before = list(value.value)
                value.value = (before[0] + (1 if before[0] < 32767 else -1), before[1])
            action["after_mesh"] = structure_mesh_row(mesh)
            self.flush()
            if name == "cancel_after_uv":
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Private fixture hook stops after UV write",
                                  {"private_validation_hook": True, "real_request_cancel": False})

        controller = PrivateGLBController(store, ops, check)
        self.controllers.append((controller, ops, record.intent.stage_id))
        self.flush()
        error = None
        try:
            retained = controller.construct(record.intent.preview_id, record.intent.fingerprint,
                                            list(record.intent.plan.required_accepted_losses))
        except BridgeError as cause:
            result["local_constructor_exception"] = traceback.format_exc()
            error = cause.to_dict()
            retained = controller.retained(record.intent.stage_id) if record.intent.stage_id in controller._stages else store.inspect(record.intent.stage_id)
        rows = self.owned(controller, record.intent.stage_id)
        values = {} if record.intent.stage_id not in controller._stages else controller._values(controller._stages[record.intent.stage_id])
        result.update(error=error, retained=retained, native=ops.report(), owned_rows=rows,
                      preservation_after=self.preservation(ops, values), phase="independent_verify")
        self.flush()
        assert result["preservation_before"] == result["preservation_after"]
        if name == "success":
            assert error is None and retained["state"]["phase"] == "CONSTRUCTED"
            result["status"] = "CONSTRUCTED"
            result["oracles"] = verify_structure_rows(rows)
            result["normal_return_footprint"]["exact_future_cas"] = True
        elif name == "invalid_context":
            assert error is not None and not result["native"]["native_entries"] and rows == {}
            assert store.inspect(record.intent.stage_id)["phase"] == "PREPARED"
            result.update(status="REFUSED_BEFORE_ALLOCATION", context_case="declared_destination_witness_mismatch",
                          invalid_mode_or_volume_native_qualified=False, oracles={"zero_native_allocation": True})
        else:
            assert error is not None and action["fired"] and retained["state"]["phase"] == "UNKNOWN"
            assert not retained["native_cleanup_performed"]
            assert len(result["native"]["native_entries"]) == action["native_entries"]
            assert rows["mesh:0"] == action["after_mesh"]
            if name == "encoded_short_drift":
                assert error["context"]["cause"]["context"]["reason"] == "PRIVATE_OWNED_PREFIX_CHANGED"
            result.update(status="STOPPED", oracles={"private_cancel_after_uv" if name == "cancel_after_uv"
                                                    else "exact_encoded_short_cas_refusal": True})
        result["oracles"]["preservation"] = True
        self.flush()

    def observation(self, phase, elapsed):
        snapshot = {"preservation": self.preservation(self.controllers[0][1], {
            f"{stage_id}:{role}": ref.value for controller, _ops, stage_id in self.controllers if stage_id in controller._stages
            for role, ref in controller._stages[stage_id].references.items()}),
            "owned": [self.owned(controller, stage_id) for controller, _ops, stage_id in self.controllers]}
        if phase == "immediate":
            self.frozen = snapshot
        preserved = snapshot == self.frozen
        self.data["observations"].append({"phase": phase, "elapsed_seconds": elapsed,
            "preserved": preserved, "real_timer_callback": phase != "immediate", "snapshot": snapshot})
        self.flush()
        assert preserved, "Structural data/context changed during actual event-loop delay"

    def run(self):
        try:
            self.setup()
            for name in STRUCTURE_CASES:
                self.run_case(name)
            self.returned_at = time.monotonic()
            self.observation("immediate", 0.)
            self.bpy.app.timers.register(self.timer_short, first_interval=.1)
            self.bpy.app.timers.register(self.timer_middle, first_interval=.3)
            self.bpy.app.timers.register(self.timer_long, first_interval=.5)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def timer_middle(self):
        try:
            elapsed = time.monotonic() - self.returned_at
            assert elapsed >= .3
            self.observation("timer_0_3", elapsed)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def timer_long(self):
        try:
            elapsed = time.monotonic() - self.returned_at
            assert elapsed >= .5
            self.observation("timer_0_5", elapsed)
            validate_structure_transcript(self.data)
            self.finish(0)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def finish(self, status, failure=None):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit

        exit_status = 1
        try:
            self.data.update(completed=status == 0, duration_seconds=time.monotonic() - self.started)
            if failure is not None:
                self.data.setdefault("failure", failure)
            assert source_hashes(self.root) == self.data["source_sha256"], "Source changed during fixture"
            if status == 0:
                validate_structure_transcript(self.data)
            self.flush()
            if status == 0:
                keys = ("schema", "profile", "completed", "version", "blender_version", "build_hash",
                        "process_instance", "process_id", "source_sha256", "binary")
                payload = {key: self.data[key] for key in keys}
                payload["evidence_sha256"] = file_digest(self.path)
                print(STRUCTURE_MARKER + json.dumps(payload, separators=(",", ":")), flush=True)
            exit_status = status
        except BaseException:
            self.data.setdefault("failure", traceback.format_exc())
            self.data["finish_failure"] = traceback.format_exc()
            self.data["completed"] = False
            try:
                self.flush()
            except BaseException:
                traceback.print_exc()
        finally:
            owned_process_exit(exit_status)


def main():
    root, folder, bpy, attestation = owned_entry()
    fixture = None
    try:
        fixture_class = StructureFixture if "--bridge-glb-structure" in sys.argv else Fixture
        fixture = fixture_class(root, folder, bpy, attestation)
        fixture.flush()
        bpy.app.timers.register(fixture.run, first_interval=.2)
    except BaseException:
        if fixture is not None:
            fixture.finish(1, traceback.format_exc())
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        try:
            traceback.print_exc()
        finally:
            owned_process_exit(1)


if __name__ == "__main__":
    main()
