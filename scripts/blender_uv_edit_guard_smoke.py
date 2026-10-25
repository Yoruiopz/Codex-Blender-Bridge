"""Owned provided-storage UV guard qualification, with no native undo.

Only the isolated background runner may enter this disposable experiment. All
native work stays on its main thread. Faults are bounded Python seam injections;
no BMesh free, schema replacement, cached UV payload, capture or project save.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from weakref import ref

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
MAPS = ("Guard Primary", "Guard Protected")
MARKER = "_codex_bridge_undo_marker"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pair(value: Any) -> tuple[float, float]:
    return struct.unpack("<ff", struct.pack("<ff", *value))


def bits(value: Any) -> list[str]:
    return [struct.pack("<f", float(component)).hex() for component in value]


def token(owner: Any) -> Any:
    return None if owner is None else (int(owner.as_pointer()), int(owner.session_uid))


def enable_addon() -> tuple[Any, Any]:
    """Use Blender's normal enable path so registered preferences actually exist."""
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime
    assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
    assert bpy.context.preferences.addons.get("blender_codex_bridge") is not None, "Enabled add-on entry is missing"
    prefs = get_preferences()
    assert prefs is not None and prefs.auto_start is False, "Factory enabled preferences are unavailable or auto-started"
    return get_runtime(), prefs


def link_fixture_meshes(scene: Any, work: Any, peer: Any) -> Any:
    """Use the existing direct local leaf; retain the factory collection tree."""
    master = scene.collection
    assert len(master.children) == 1, "Factory fixture requires one existing direct leaf Collection"
    leaf = master.children[0]
    assert leaf is not master and not len(leaf.children), "Fixture owning Collection must be a direct leaf"
    assert leaf.library is None and leaf.override_library is None and leaf.is_editable
    assert len(leaf.objects) <= 254, "Fixture Collection must retain room for both provided meshes"
    leaf.objects.link(work)
    leaf.objects.link(peer)
    return leaf


def expected_maps(before: dict, operation: str, params: dict) -> dict:
    """Independent request oracle; never read the guard's plan or expected UVs."""
    result = copy.deepcopy(before)
    rows = result[params["uv_layer"]]
    explicit = params.get("corners")
    chosen = None if explicit is None else {(row["face_index"], row["corner_index"]) for row in explicit}
    if operation == "coordinates_set":
        replacements = {(row["face_index"], row["corner_index"]): pair(row["uv"]) for row in params["updates"]}
        for row in rows:
            if (row["face"], row["corner"]) in replacements:
                row["uv"] = list(replacements[row["face"], row["corner"]])
                row["float32_le"] = bits(row["uv"])
    elif operation == "pin":
        for row in rows:
            if chosen is None or (row["face"], row["corner"]) in chosen:
                row["pin_uv"] = params.get("pinned", True)
    else:
        assert operation == "transform"
        offset, scale, pivot = (pair(params.get(name, default)) for name, default in (
            ("offset", (0., 0.)), ("scale", (1., 1.)), ("pivot", (0., 0.))))
        angle = float(params.get("rotation", 0.))
        c, s = math.cos(angle), math.sin(angle)
        for row in rows:
            if (chosen is not None and (row["face"], row["corner"]) not in chosen) or (
                    params.get("respect_pins", True) and row["pin_uv"]):
                continue
            x = (row["uv"][0]-pivot[0])*scale[0]
            y = (row["uv"][1]-pivot[1])*scale[1]
            row["uv"] = list(pair((pivot[0]+offset[0]+c*x-s*y, pivot[1]+offset[1]+s*x+c*y)))
            row["float32_le"] = bits(row["uv"])
    return result


def marker_inventory() -> tuple:
    """Literal independent projection of the complete core marker inventory."""
    rows = []
    for scene in bpy.data.scenes:
        value = scene.get(MARKER)
        assert value is None or type(value) is str
        rows.append((token(scene), token(scene.library), token(scene.override_library),
                     bool(scene.is_editable), MARKER in scene, value))
    return token(bpy.context.scene), tuple(sorted(rows))


class Setter:
    """One ephemeral native field setter; no native UV handle survives it."""

    def __init__(self, fixture: Any, target: Any, key: tuple, field: str):
        object.__setattr__(self, "fixture", fixture)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "resolved_at", fixture.snapshot_reads)

    def __setattr__(self, name: str, value: Any) -> None:
        fixture, target = self.fixture, self.target
        assert name == self.field and name in {"uv", "pin_uv"} and target is not None
        assert fixture.snapshot_reads == self.resolved_at, "Native snapshot crossed the final UV leaf"
        object.__setattr__(self, "target", None)
        unknown = fixture.mode == "unknown_setter" and fixture.armed and not fixture.restoring
        actual = (0.9375, -0.3125) if unknown and name == "uv" else value
        if unknown:
            fixture.armed = False
        complete = False
        try:
            setattr(target, name, actual)
            complete = True
        finally:
            target = None  # Before any logging, fault callback or new native read.
            fixture.trace.append({"kind": "native_field", "key": list(self.key), "field": name,
                "restoring": fixture.restoring, "delegate_calls": 1, "completed": complete,
                "snapshots_since_resolve": fixture.snapshot_reads-self.resolved_at,
                "requested": bits(value) if name == "uv" else value,
                "written": bits(actual) if name == "uv" else actual})
        if unknown:
            raise RuntimeError("Owned fixture: same-field unknown setter result")


class Fixture:
    def __init__(self, folder: Path, process: str, attestation: dict):
        self.path = folder / "uv-edit-guard-evidence.json"
        assert not self.path.exists()
        self.scene, self.layer = bpy.context.scene, bpy.context.scene.view_layers[0]
        self.runtime: Any = None
        self.work: Any = None
        self.peer: Any = None
        self.trace: list[dict] = []
        self.receipts: list[dict] = []
        self.mode, self.armed, self.restoring = "normal", False, False
        self.queued: Any = None
        self.snapshot_calls = 0
        self.snapshot_reads = 0
        self.leaves: list[Any] = []
        self.data = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "process_instance": process, "owned_profile_attestation": attestation, "completed": False,
            "cases": [], "selection_references": [], "setup": [], "limits": {"real_transport_verified": False,
                "local_main_thread_dispatch_only": True, "native_undo_verified": False,
                "durable_recovery_verified": False, "schema_ABA_or_free_probed": False,
                "internal_PYPTR_allocation_purity_verified": False,
                "persistent_non_ID_identity_verified": False, "project_saved": False,
                "visual_capture": False, "F02_complete": False, "REC_complete": False,
                "full_artist_acceptance": False, "Windows_qualified": False,
                "release_acceptance": False},
            "fault_scope": "Provided-storage static material-free native profile; wrappers installed before factory and removed after unwind; no destructive lifetime/schema probes",
            "termination": "Owned os._exit; no native quit/save callbacks"}
        self.flush()

    def flush(self) -> None:
        raw = canonical(self.data)+b"\n"
        assert len(raw) <= 4*1024*1024
        self.path.write_bytes(raw)

    def leaf_alive(self) -> bool:
        return any(item() is not None and item().target is not None for item in self.leaves)

    def queued_facts(self) -> dict | None:
        if self.queued is None:
            return None
        lifetime = self.queued.request._lifecycle
        return {"queue_state": self.queued._state, "cancel_requested": self.queued._stop_requested,
            "completed": self.queued.completed.is_set(),
            "lifetime_delivered": lifetime.delivered.is_set(), "lifetime_rejected": lifetime.rejected.is_set(),
            "connection_disconnected": None if lifetime.connection is None else lifetime.connection.disconnected.is_set()}

    def fresh_corner(self, name: str, face_index: int, corner_index: int) -> dict:
        import bmesh
        current = bmesh.from_edit_mesh(self.work.data)
        assert current.is_valid
        face = next(face for face in current.faces if face.index == face_index)
        loop = next(loop for index, loop in enumerate(face.loops) if index == corner_index)
        assert face.is_valid and loop.is_valid
        layer = current.loops.layers.uv.get(name)
        assert layer is not None
        payload = loop[layer]
        uv = [float(component) for component in payload.uv]
        row = {"face": face_index, "corner": corner_index, "vertex": loop.vert.index,
               "edge": loop.edge.index, "uv": uv, "float32_le": bits(uv), "pin_uv": bool(payload.pin_uv)}
        if self.modern:
            row.update(select=bool(loop.uv_select_vert), select_edge=bool(loop.uv_select_edge))
        else:
            row.update(select=bool(payload.select), select_edge=bool(payload.select_edge))
        return row

    def maps(self) -> dict:
        import bmesh
        current = bmesh.from_edit_mesh(self.work.data)
        names = tuple(current.loops.layers.uv.keys())
        keys = tuple((face.index, corner) for face in current.faces for corner, _loop in enumerate(face.loops))
        assert names == MAPS and len(keys) == 8
        # Each helper returns plain values before the next helper/flush callback.
        return {name: [self.fresh_corner(name, face, corner) for face, corner in keys] for name in names}

    def edit_rest(self) -> dict:
        import bmesh
        current = bmesh.from_edit_mesh(self.work.data)
        return {"vertices": [[v.index, bits(v.co), bits(v.normal), v.select, v.hide, v.tag] for v in current.verts],
            "edges": [[e.index, [v.index for v in e.verts], e.select, e.hide, e.tag, e.seam, e.smooth] for e in current.edges],
            "faces": [[f.index, [[loop.vert.index, loop.edge.index] for loop in f.loops], f.select, f.hide, f.tag,
                       f.smooth, f.material_index, bits(f.normal), bool(f.uv_select) if self.modern else None] for f in current.faces],
            "select_history": [[type(item).__name__, item.index] for item in current.select_history],
            "active_face": None if current.faces.active is None else current.faces.active.index,
            "uv_sync_valid": bool(current.uv_select_sync_valid) if self.modern else None,
            "layers": {name: list(getattr(current.loops.layers, name).keys()) for name in ("uv", "bool")},
            "roles": {"order": [layer.name for layer in self.work.data.uv_layers],
                "active_index": self.work.data.uv_layers.active_index,
                "render_clone": [[layer.name, bool(layer.active_render), bool(layer.active_clone)] for layer in self.work.data.uv_layers],
                "edit_active": None if current.loops.layers.uv.active is None else current.loops.layers.uv.active.name}}

    @staticmethod
    def object_view(obj: Any) -> dict:
        mesh = obj.data
        result = {"identity": token(obj), "mesh_identity": token(mesh), "name": obj.name,
            "mesh_name": mesh.name, "mesh_users": mesh.users, "mode": obj.mode,
            "transforms": {name: bits(getattr(obj, name)) for name in ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")},
            "rotation_mode": obj.rotation_mode, "parent": token(obj.parent),
            "materials": [token(item) for item in mesh.materials],
            "uv_roles": {"active_index": mesh.uv_layers.active_index,
                "layers": [[layer.name, layer.active_render, layer.active_clone] for layer in mesh.uv_layers]}}
        if obj.mode == "OBJECT":
            result.update(vertices=[[bits(v.co), v.select, v.hide] for v in mesh.vertices],
                edges=[[list(e.vertices), e.select, e.hide, e.use_seam] for e in mesh.edges],
                faces=[[list(f.vertices), f.select, f.hide, f.material_index] for f in mesh.polygons],
                attributes=[[a.name, a.data_type, a.domain, len(a.data)] for a in mesh.attributes],
                uv_flags={a.name: [bool(value.value) for value in a.data]
                          for a in mesh.attributes if a.data_type == "BOOLEAN" and a.domain == "CORNER"},
                uv={name: [bits(value.vector) for value in mesh.attributes[name].data] for name in MAPS if mesh.attributes.get(name) is not None})
        return result

    def snapshot(self) -> dict:
        from blender_artist_target_verification_smoke import checkpoint_state
        assert not self.leaf_alive(), "Fixture observation refused while a UV leaf was retained"
        flags = [[obj.name, obj.select_get(view_layer=self.layer)] for obj in self.layer.objects]
        active = self.layer.objects.active
        settings = self.scene.tool_settings
        flags_bridge = self.runtime.state.snapshot()
        owners = (self.work, self.work.data, self.peer, self.peer.data)
        users = bpy.data.user_map(subset=set(owners))
        consumers = [[token(owner), sorted([[token(user), user.name, user.user_of_id(owner)]
                      for user in users.get(owner, ())])] for owner in owners]
        return {"maps": self.maps(), "edit_rest": self.edit_rest(),
            "objects": {obj.name: self.object_view(obj) for obj in (self.work, self.peer)},
            "consumers": consumers,
            "context": {"scene": token(self.scene), "layer": self.layer.as_pointer(),
                "mode": bpy.context.mode, "active": token(active),
                "selected": flags,
                "frame": [self.scene.frame_current, self.scene.frame_subframe],
                "mesh_select_mode": list(settings.mesh_select_mode), "uv_select_sync": settings.use_uv_select_sync,
                "uv_select_mode": settings.uv_select_mode,
                "undo_preferences": [bpy.context.preferences.edit.use_global_undo, bpy.context.preferences.edit.undo_steps]},
            "scene_properties": {key: self.scene[key] for key in sorted(self.scene.keys())},
            "markers": marker_inventory(), "checkpoints": checkpoint_state(self.runtime),
            "authority": {"grants": dict(self.grants), "paused": flags_bridge["paused"],
                          "emergency_stopped": flags_bridge["emergency_stopped"], "queued_owner": self.queued_facts()},
            "history": self.runtime.state.history(50)}

    def setup(self) -> None:
        import bmesh
        from blender_codex_bridge.permissions import Permission, PermissionManager
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
        assert bpy.context.preferences.edit.use_global_undo and bpy.context.preferences.edit.undo_steps > 0
        self.runtime, prefs = enable_addon()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = prefs.allow_external_files = False
        self.grants = {permission.value: permission in {Permission.EDIT_MESH, Permission.INSPECT_SCENE} for permission in Permission}
        permissions = PermissionManager(lambda: dict(self.grants))
        self.runtime.permissions = self.runtime.executor.permissions = permissions
        self.runtime.registry.enable_toolset("uv")
        mesh = bpy.data.meshes.new("UV Guard Provided Mesh")
        mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (2., 0., 0.), (0., 1., 0.), (1., 1., 0.), (2., 1., 0.)],
                         [], [(0, 1, 4, 3), (1, 2, 5, 4)])
        mesh.update()
        self.modern = hasattr(bmesh.types.BMesh, "uv_select_sync_valid")
        predictions = {}
        for ordinal, name in enumerate(MAPS):
            mesh.uv_layers.new(name=name)
            source = [(0., -0.), (.25, .5), (-.5, .75), (1., -1.), (.125, .25), (.375, .5), (.625, .75), (.875, 1.)]
            predictions[name] = [pair((u+ordinal*.125, v+ordinal*.25)) if ordinal else pair((u, v)) for u, v in source]
            for item, uv in zip(mesh.attributes[name].data, predictions[name], strict=True):
                item.vector = uv
            for prefix in ((".pn.",) if self.modern else (".pn.", ".vs.", ".es.")):
                attribute = mesh.attributes.new(name=prefix+name, type="BOOLEAN", domain="CORNER")
                for index, item in enumerate(attribute.data):
                    item.value = index == 1 if prefix == ".pn." and not ordinal else bool(index % 2)
        mesh.uv_layers.active_index = 0
        mesh.uv_layers[1].active_render = True
        for sequence in (mesh.vertices, mesh.edges, mesh.polygons):
            for item in sequence:
                item.select = True
        mesh.edges[0].use_seam = True
        self.work = bpy.data.objects.new("UV Guard Working", mesh)
        self.peer = bpy.data.objects.new("UV Guard Protected Peer", mesh.copy())
        self.peer.location.x = 5.
        collection = link_fixture_meshes(self.scene, self.work, self.peer)
        self.data["setup"].append({"kind": "existing_factory_leaf_collection",
            "master": token(self.scene.collection), "direct_children": [token(child) for child in self.scene.collection.children],
            "owner": token(collection), "owner_children": [token(child) for child in collection.children],
            "owner_local": collection.library is None, "owner_override": token(collection.override_library),
            "owner_editable": bool(collection.is_editable), "owner_members": [token(obj) for obj in collection.objects],
            "working_owners": [token(owner) for owner in self.work.users_collection],
            "protected_owners": [token(owner) for owner in self.peer.users_collection]})
        self.scene["uv_guard_protected_note"] = "Keep literal Scene fields"
        self.scene["uv_guard_protected_number"] = 17
        for obj in self.layer.objects:
            obj.select_set(False, view_layer=self.layer)
        self.work.select_set(True, view_layer=self.layer)
        self.layer.objects.active = self.work
        self.scene.tool_settings.mesh_select_mode = (False, False, True)
        self.scene.tool_settings.use_uv_select_sync = False
        self.layer.update()
        attribute = item = sequence = None  # No Object-Mesh payload crosses mode entry.
        assert "FINISHED" in bpy.ops.object.mode_set(mode="EDIT")
        current = bmesh.from_edit_mesh(mesh)
        for name in ("verts", "edges", "faces"):
            getattr(current, name).ensure_lookup_table()
            getattr(current, name).index_update()
        for face in current.faces:
            face.select_set(True)
        current.faces.active = current.faces[0]
        current.select_history.clear()
        current.select_history.add(current.faces[0])
        if self.modern:
            current.uv_select_sync_valid = False
            for face in current.faces:
                face.uv_select = bool(face.index % 2)
                for ordinal, loop in enumerate(face.loops):
                    loop.uv_select_vert = bool(ordinal % 2)
                    loop.uv_select_edge = not bool(ordinal % 2)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        current = face = loop = None
        def inventory():
            current = bmesh.from_edit_mesh(mesh)
            return {"maps": list(current.loops.layers.uv.keys()),
                    "bool": list(current.loops.layers.bool.keys()),
                    "attributes": [[a.name, a.data_type, a.domain, len(a.data)] for a in mesh.attributes]}
        provided = inventory()
        expected_flags = {prefix+name for name in MAPS
                          for prefix in ((".pn.",) if self.modern else (".pn.", ".vs.", ".es."))}
        assert set(provided["bool"]) == expected_flags
        self.data["setup_first_payload_inventory_before"] = provided
        self.flush()
        actual = self.maps()
        self.data["setup_first_payload_inventory_after"] = inventory()
        assert self.data["setup_first_payload_inventory_after"] == provided
        for name in MAPS:
            assert [row["float32_le"] for row in actual[name]] == [bits(uv) for uv in predictions[name]]
            assert [row["pin_uv"] for row in actual[name]] == [bool(index % 2) if name == MAPS[1] else index == 1 for index in range(8)]
            assert [row["select"] for row in actual[name]] == [bool(index % 2) for index in range(8)]
            assert [row["select_edge"] for row in actual[name]] == [not bool(index % 2) if self.modern else bool(index % 2) for index in range(8)]
        self.expected = copy.deepcopy(actual)
        self.data["provided_storage"] = {"modern_global_selection": self.modern,
            "initial_predictions": {name: [bits(uv) for uv in values] for name, values in predictions.items()},
            "initial_snapshot": self.snapshot()}
        self.data["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), ROOT/"addon/blender_codex_bridge/uv_edit_guard.py",
                         ROOT/"addon/blender_codex_bridge/tools/uv_edit.py", ROOT/"addon/blender_codex_bridge/uv_edit_intent.py",
                         ROOT/"addon/blender_codex_bridge/checkpoint_completion.py", ROOT/"addon/blender_codex_bridge/checkpoints.py",
                         ROOT/"addon/blender_codex_bridge/executor.py", ROOT/"addon/blender_codex_bridge/tool_registry.py")}
        self.flush()

    @contextmanager
    def instrument(self, mode: str):
        from blender_codex_bridge import uv_edit_guard as guard
        self.mode, self.armed = mode, mode != "normal"
        self.trace, self.receipts, self.restoring = [], [], False
        self.leaves, self.snapshot_reads = [], 0
        original_write = guard.UVEditGuard._write
        original_read = guard._NativeReader.snapshot
        original_resolve = guard._NativeReader.resolve
        original_update = guard._NativeReader.update
        original_marker = guard.UVEditGuard.after_marker_write
        original_snapshot = self.runtime.checkpoints._snapshot

        def read(reader):
            assert not self.leaf_alive(), "Guard snapshot refused while a UV leaf was retained"
            self.snapshot_reads += 1
            return original_read(reader)

        def resolve(reader, key, field, expected):
            setter = Setter(self, original_resolve(reader, key, field, expected), key, field)
            self.leaves.append(ref(setter))
            self.trace.append({"kind": "leaf_resolve", "key": list(key), "field": field,
                               "snapshot_reads": self.snapshot_reads})
            return setter

        def write(owner, key, field, value, *, restoring=False):
            self.restoring = restoring
            try:
                result = original_write(owner, key, field, value, restoring=restoring)
            finally:
                self.restoring = False
            if self.armed and not restoring and mode not in {"unknown_setter", "unknown_update", "normal"}:
                self.armed = False
                if mode == "post_field":
                    raise RuntimeError("Owned fixture: failure after one measured field")
                if mode == "permission":
                    self.grants["EDIT_MESH"] = False
                elif mode == "pause":
                    owner.context.state.set_paused(True)
                elif mode == "stop":
                    owner.context.state.set_emergency_stopped(True)
                elif mode == "spec":
                    owner.context.registry._tools[owner.method] = replace(owner.spec, description="Owned replacement spec")
                elif mode == "cancel":
                    assert self.queued is not None
                    from blender_codex_bridge.errors import BridgeError
                    assert self.queued.cancel_pending(BridgeError("TIMEOUT", "Owned running cancellation")) is False
                elif mode == "lifetime":
                    assert owner.context.request_lifecycle is not None
                    owner.context.request_lifecycle.rejected.set()
                else:
                    raise AssertionError(mode)
            return result

        def update(reader):
            result = original_update(reader)
            self.trace.append({"kind": "native_update", "delegate_calls": 1})
            if mode == "unknown_update" and self.armed:
                self.armed = False
                raise RuntimeError("Owned fixture: update result deliberately unknown")
            return result

        def marker(owner, event):
            original_marker(owner, event)  # Actual canonical consumption FIRST.
            assert not self.leaf_alive(), "Marker observation refused while a UV leaf was retained"
            predicted = owner._expected.checkpoint_markers
            actual = marker_inventory()
            assert predicted == actual
            self.receipts.append({"event_type": type(event).__name__, "event_python_id": id(event),
                                  "canonical_consumption_returned": True, "predicted": predicted, "actual": actual})

        def no_snapshot(*_args, **_kwargs):
            self.snapshot_calls += 1
            raise AssertionError("Edit Mode UV fixture must never invoke native undo snapshot")

        guard._NativeReader.snapshot = read
        guard._NativeReader.resolve = resolve
        guard._NativeReader.update = update
        guard.UVEditGuard._write = write
        guard.UVEditGuard.after_marker_write = marker
        self.runtime.checkpoints._snapshot = no_snapshot
        try:
            yield
        finally:
            guard._NativeReader.snapshot = original_read
            guard._NativeReader.resolve = original_resolve
            guard._NativeReader.update = original_update
            guard.UVEditGuard._write = original_write
            guard.UVEditGuard.after_marker_write = original_marker
            self.runtime.checkpoints._snapshot = original_snapshot
            self.mode, self.restoring = "normal", False

    def reference(self) -> str:
        before = self.snapshot()
        result = self.runtime.dispatch("selection.inspect", {})
        after = self.snapshot()
        self.data["selection_references"].append({"before": before, "after": after,
                                                  "selection_id": result["mesh_selection"]["selection_id"]})
        self.flush()
        for name in ("maps", "edit_rest", "objects", "consumers", "context", "scene_properties", "markers", "checkpoints", "authority"):
            assert canonical(before[name]) == canonical(after[name]), "Readonly reference changed "+name
        return result["mesh_selection"]["selection_id"]

    def assert_preserved(self, before: dict, after: dict) -> None:
        for name in ("edit_rest", "objects", "consumers", "context"):
            assert canonical(before[name]) == canonical(after[name]), name
        original_props = {key: value for key, value in before["scene_properties"].items() if key != MARKER}
        current_props = {key: value for key, value in after["scene_properties"].items() if key != MARKER}
        assert canonical(original_props) == canonical(current_props)
        prior = before["markers"]
        for row in self.receipts:
            actual = row["actual"]
            assert actual[0] == prior[0] and len(actual[1]) == len(prior[1])
            changes = [(a, b) for a, b in zip(prior[1], actual[1], strict=True) if a != b]
            assert len(changes) == 1 and changes[0][0][:4] == changes[0][1][:4]
            prior = actual
        assert canonical(prior) == canonical(after["markers"])
        assert self.snapshot_calls == 0

    def run_case(self, label: str, method: str, params: dict, *, mode="normal", success=True,
                 expected: dict | None = None, queued=False) -> dict:
        from blender_codex_bridge.errors import BridgeError
        before = self.snapshot()
        started = time.perf_counter()
        local_owner_before = None
        with self.instrument(mode):
            try:
                if queued:
                    from blender_codex_bridge.command_queue import QueuedRequest
                    from blender_codex_bridge.protocol import Request
                    from blender_codex_bridge.request_lifecycle import RequestLifetime
                    request = Request(id="owned_uv_"+label, method=method, params=copy.deepcopy(params),
                                      _lifecycle=RequestLifetime.local())
                    self.queued = QueuedRequest(request)
                    assert self.queued.try_start()
                    local_owner_before = self.queued_facts()
                    response = self.runtime.executor.execute_request(request, check_cancelled=self.queued.check_active)
                    self.queued.resolve(response)
                    outcome = response.to_dict()
                else:
                    outcome = {"ok": True, "result": self.runtime.dispatch(method, params)}
            except BridgeError as error:
                outcome = {"ok": False, "error": error.to_dict()}
            after = self.snapshot()
            row = {"label": label, "method": method, "params": params, "mode": mode,
                   "queued_local_model": queued, "before": before, "after": after,
                   "queued_owner_before": local_owner_before,
                   "outcome": outcome, "seconds": time.perf_counter()-started,
                   "native_trace": copy.deepcopy(self.trace), "canonical_marker_receipts": copy.deepcopy(self.receipts)}
            self.data["cases"].append(row)
            self.flush()
            assert outcome["ok"] is success, outcome
            if expected is not None:
                assert canonical(after["maps"]) == canonical(expected), label
            self.assert_preserved(before, after)
            history = after["history"]
            assert history and history[0]["tool"] == method and history[0]["success"] is success
            assert len(history) == len(before["history"])+1 and history[1:] == before["history"]
            if success:
                result = outcome["result"]
                assert result["native_undo_boundary_verified"] is False
                evidence = result["recovery_evidence"]
            else:
                evidence = outcome["error"].get("context", {}).get("recovery_evidence")
            if evidence is not None:
                assert history[0]["recovery_evidence"] == evidence
            assert all(entry["snapshots_since_resolve"] == 0
                       for entry in self.trace if entry["kind"] == "native_field")
            self.expected = copy.deepcopy(after["maps"])
            return row

    def cases(self) -> None:
        common = {"object_name": self.work.name, "uv_layer": MAPS[0]}
        params = {**common, "selection_id": self.reference(), "updates": [
            {"face_index": 0, "corner_index": 0, "uv": [-0., 0.]},
            {"face_index": 0, "corner_index": 2, "uv": [.1, .2]}]}
        self.run_case("coordinates", "uv.coordinates_set", params,
                      expected=expected_maps(self.expected, "coordinates_set", params))
        params = {**common, "offset": [.1, -.2], "scale": [-1.25, .75], "pivot": [.25, -.5], "rotation": .125}
        self.run_case("transform", "uv.transform", params, expected=expected_maps(self.expected, "transform", params))
        params = {**common, "selection_id": self.reference(), "corners": [{"face_index": 1, "corner_index": 1}], "pinned": True}
        self.run_case("pin", "uv.pin", params, expected=expected_maps(self.expected, "pin", params))
        params = {**common, "selection_id": self.reference(), "corners": [{"face_index": 1, "corner_index": 2}], "pinned": True}
        row = self.run_case("post_pin_field", "uv.pin", params, mode="post_field", success=False, expected=self.expected)
        pin_fields = [entry for entry in row["native_trace"] if entry["kind"] == "native_field"]
        assert len(pin_fields) == 2 and all(entry["field"] == "pin_uv" for entry in pin_fields)
        assert pin_fields[1]["restoring"] and row["outcome"]["error"]["context"]["recovery_evidence"]["rollback_verified"]
        self.grants["EDIT_MESH"] = False
        try:
            row = self.run_case("permission_denied", "uv.transform", {**common, "offset": [.1, .2]},
                                success=False, expected=self.expected)
            assert row["outcome"]["error"]["code"] == "PERMISSION_DENIED" and not row["native_trace"]
        finally:
            self.grants["EDIT_MESH"] = True
        row = self.run_case("context_refused", "uv.transform", {**common, "object_name": self.peer.name},
                            success=False, expected=self.expected)
        assert row["outcome"]["error"]["code"] in {"NOT_IMPLEMENTED", "INVALID_MODE"}
        assert not row["native_trace"]
        for index, mode in enumerate(("post_field", "unknown_setter", "unknown_update", "permission", "pause", "stop", "spec", "cancel", "lifetime")):
            params = {**common, "selection_id": self.reference(), "updates": [
                {"face_index": 0, "corner_index": 0, "uv": [.625+index*.015625, -.375]},
                {"face_index": 1, "corner_index": 3, "uv": [-.125, .875+index*.015625]}]}
            expected = copy.deepcopy(self.expected)
            if mode == "unknown_update":
                expected = expected_maps(expected, "coordinates_set", params)
            elif mode != "post_field":
                one = copy.deepcopy(params)
                one["updates"] = one["updates"][:1]
                if mode == "unknown_setter":
                    one["updates"][0]["uv"] = [.9375, -.3125]
                expected = expected_maps(expected, "coordinates_set", one)
            old_spec = self.runtime.registry.get("uv.coordinates_set")
            try:
                row = self.run_case(mode, "uv.coordinates_set", params, mode=mode, success=False,
                                    expected=expected, queued=mode in {"cancel", "lifetime"})
                fields = [entry for entry in row["native_trace"] if entry["kind"] == "native_field"]
                evidence = row["outcome"]["error"]["context"]["recovery_evidence"]
                assert fields and all(entry["field"] == "uv" for entry in fields)
                if mode == "post_field":
                    assert evidence["rollback_verified"] is True and evidence["restored_fields"] == 1
                    assert len(fields) == 2 and fields[1]["restoring"] is True
                else:
                    assert not evidence["rollback_verified"] and evidence["retained_partial"]
                    assert evidence["restoration_attempts"] == 0 and not any(entry["restoring"] for entry in fields)
                    assert len(fields) == (2 if mode == "unknown_update" else 1)
                    if mode in {"unknown_update", "unknown_setter"}:
                        assert evidence["restoration_refused"] == "UNKNOWN_WRITE_RESULT"
                    else:
                        assert evidence["restoration_refused"] == "AUTHORITY_LOST"
                        assert row["outcome"]["error"]["code"] == {"permission": "PERMISSION_DENIED",
                            "pause": "AGENT_PAUSED", "stop": "EMERGENCY_STOPPED", "spec": "NOT_IMPLEMENTED",
                            "cancel": "TIMEOUT", "lifetime": "TIMEOUT"}[mode]
                        authority = row["after"]["authority"]
                        if mode == "permission":
                            assert authority["grants"]["EDIT_MESH"] is False
                        elif mode in {"pause", "stop"}:
                            assert authority["paused" if mode == "pause" else "emergency_stopped"] is True
                        elif mode in {"cancel", "lifetime"}:
                            owner = authority["queued_owner"]
                            assert row["queued_owner_before"]["queue_state"] == "running"
                            assert owner["completed"] and owner["queue_state"] == "completed"
                            assert owner["cancel_requested" if mode == "cancel" else "lifetime_rejected"] is True
            finally:
                self.grants["EDIT_MESH"] = True
                self.runtime.state.set_paused(False)
                self.runtime.state.set_emergency_stopped(False)
                self.runtime.registry._tools["uv.coordinates_set"] = old_spec
                self.queued = None


def main() -> None:
    from blender_artist_quaternion_storage_smoke import owned_profile
    folder, process, attestation = owned_profile()
    from blender_artist_sidebar_smoke import owned_process_exit
    proof = None
    status = 1
    try:
        proof = Fixture(folder, process, attestation)
        proof.setup()
        proof.cases()
        proof.data["final"] = proof.snapshot()
        proof.data["native_snapshot_invocations"] = proof.snapshot_calls
        proof.data["completed"] = True
        proof.flush()
        print("BLENDER_UV_EDIT_GUARD_OK "+json.dumps({"blender_version": bpy.app.version_string,
            "evidence_file": str(proof.path), "evidence_sha256": hashlib.sha256(proof.path.read_bytes()).hexdigest(),
            "cases": len(proof.data["cases"]), "actual_registered_tools": ["uv.coordinates_set", "uv.transform", "uv.pin"],
            "full_maps_verified": True, "canonical_marker_receipts_observed": True, **proof.data["limits"]}), flush=True)
        status = 0
    except BaseException:
        traceback.print_exc()
        if proof is not None:
            proof.data["failure"] = traceback.format_exc()
            try:
                proof.flush()
            except BaseException:
                traceback.print_exc()
    finally:
        owned_process_exit(status)


if __name__ == "__main__":
    main()
