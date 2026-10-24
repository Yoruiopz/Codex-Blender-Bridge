"""Owned native UV Edit Mode storage research; no production tool acceptance.

Optional UV getter accesses are measured operations, never silently warmed away.
Live edit-BMesh and object-Mesh views remain separate, including explicit updates
and mode transitions. Python wrapper identity is process-local evidence only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import sys
import traceback
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MAPS = ("Research Primary", "Research Secondary")
MIN_NORMAL = float.fromhex("0x1p-126")


def token(owner: Any) -> dict[str, Any] | None:
    return None if owner is None else {"name": owner.name, "pointer": owner.as_pointer(), "session_uid": owner.session_uid}


def pair_bits(values: Any) -> list[str]:
    return [struct.pack("<f", float(value)).hex() for value in values]


def predicted_pair(values: Any) -> dict[str, Any]:
    assert len(values) == 2 and all(type(value) is float and math.isfinite(value) for value in values)
    assert all(value == 0. or MIN_NORMAL <= abs(value) <= 1_000_000. for value in values)
    rounded = [struct.unpack("<f", struct.pack("<f", value))[0] for value in values]
    assert all(value == 0. or MIN_NORMAL <= abs(value) <= 1_000_000. for value in rounded)
    return {"requested": list(values), "requested_float64_le": [struct.pack("<d", value).hex() for value in values],
            "expected": rounded, "expected_float32_le": pair_bits(rounded)}


def wrapper(handle: Any) -> dict[str, Any]:
    kind = type(handle)
    available = any("is_valid" in base.__dict__ for base in kind.__mro__)
    return {"python_id": id(handle), "type": kind.__module__ + "." + kind.__name__,
            "is_valid_property_present": available, "is_valid": bool(handle.is_valid) if available else None,
            "scope": "Retained process-local Python wrapper; absent is_valid never implies validity or native session identity"}


def has_static(handle: Any, name: str) -> bool:
    return any(name in base.__dict__ for base in type(handle).__mro__)


def rna_capabilities(owner: Any, names: tuple[str, ...]) -> dict[str, Any]:
    result = {}
    for name in names:
        prop = owner.bl_rna.properties.get(name)
        result[name] = None if prop is None else {"type": prop.type, "readonly": prop.is_readonly,
            "runtime": prop.is_runtime, "registered": getattr(prop, "is_registered", False),
            "array_length": getattr(prop, "array_length", None),
            "fixed_type": getattr(getattr(prop, "fixed_type", None), "identifier", None)}
    return result


def logical_map_roles(roles: dict[str, Any]) -> dict[str, Any]:
    """Compare roles, retaining native layer-pointer changes as separate observations."""
    return {"order": roles["order"], "active_index": roles["active_index"],
            "layers": [{key: value for key, value in layer.items() if key != "pointer"} for layer in roles["layers"]]}


def copy_object_uv_property(mesh: Any, name: str, field: str) -> list[Any]:
    """Finish one allocating RNA getter's primitive copy before another getter.

    UV-layer and collection handles are local to this one property read. Named
    layers are reacquired for every property because optional attribute creation
    can reallocate the Mesh CustomData and invalidate earlier RNA handles.
    """
    assert field in {"uv", "pin", "vertex_selection", "edge_selection"}
    layer = mesh.uv_layers.get(name)
    assert type(layer) is bpy.types.MeshUVLoopLayer
    prop = layer.bl_rna.properties.get(field)
    expected = "Float2AttributeValue" if field == "uv" else "BoolAttributeValue"
    assert prop is not None and prop.type == "COLLECTION" and not prop.is_runtime and not prop.is_registered
    assert prop.fixed_type.identifier == expected
    item_class = getattr(bpy.types, expected)
    value_field = "vector" if field == "uv" else "value"
    value_prop = item_class.bl_rna.properties.get(value_field)
    assert value_prop is not None and not value_prop.is_runtime and not value_prop.is_registered
    assert value_prop.type == ("FLOAT" if field == "uv" else "BOOLEAN")
    assert getattr(value_prop, "array_length", 0) == (2 if field == "uv" else 0)
    collection = getattr(layer, field)
    assert len(collection) <= 64
    values = []
    for item in collection:
        assert type(item) is item_class, "Unexpected native UV property element type"
        values.append([float(component) for component in item.vector] if field == "uv" else bool(item.value))
    return values


class Proof:
    def __init__(self, folder: Path, attestation: dict[str, Any], process_token: str):
        self.path = folder / "uv-edit-storage-evidence.json"
        assert not self.path.exists()
        self.bm: Any = None
        self.scene, self.layer = bpy.context.scene, bpy.context.scene.view_layers[0]
        self.work: Any = None
        self.protected = bpy.data.objects["Cube"]
        self.data: dict[str, Any] = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "process_instance": process_token, "owned_profile_attestation": attestation, "completed": False,
            "inventories": {}, "getter_accesses": [], "object_property_copies": [], "actions": [], "observations": [], "edits": [], "lifetime": [],
            "authority": {"edit_bmesh": "Live Edit Mode BMesh", "object_mesh_view": "Literal Mesh RNA; may lag while editing"},
            "limits": {"production_tools_invoked": False, "typed_uv_tools_qualified": False,
                "provider_faults": False, "undo_or_recovery": False, "durable_recovery": False,
                "project_saved": False, "visual_capture": False, "artist_goal_verified": False,
                "subnormal_extreme_nonfinite_storage_qualified": False, "uv_sync_true_authoring_qualified": False,
                "absent_optional_storage_pin_setter_qualified": False, "persistent_native_wrapper_identity_qualified": False,
                "Mesh_uv_select_sync_valid_getter_semantics_qualified": False,
                "Object_Mesh_empty_pin_semantics_qualified": False,
                "selection_history_persistence_across_explicit_modes_qualified": False,
                "Windows_qualified": False, "release_acceptance": False},
            "termination": "Owned fixture os._exit after proof/stdio flush; no native save/quit callbacks"}
        self.flush()

    def flush(self) -> None:
        raw = (json.dumps(self.data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        assert len(raw) < 4 * 1024 * 1024, "Bounded UV research exceeded 4 MiB"
        self.path.write_bytes(raw)

    def context(self) -> dict[str, Any]:
        # Stored flags always precede further context getters.
        flags = [[obj.name, bool(obj.select_get(view_layer=self.layer))] for obj in self.layer.objects]
        active = self.layer.objects.active
        settings = self.scene.tool_settings
        return {"selection_flags": flags, "active": token(active), "mode": None if active is None else active.mode,
                "scene": token(self.scene), "layer": {"name": self.layer.name, "pointer": self.layer.as_pointer()},
                "frame": [self.scene.frame_current, self.scene.frame_subframe],
                "mesh_select_mode": list(settings.mesh_select_mode), "use_uv_select_sync": bool(settings.use_uv_select_sync),
                "uv_select_mode": str(settings.uv_select_mode) if "uv_select_mode" in settings.bl_rna.properties else None}

    def consumers(self) -> list[dict[str, Any]]:
        if self.work is None:
            return []
        owners = {self.work, self.work.data, self.protected, self.protected.data}
        rows = bpy.data.user_map(subset=owners)
        assert len(rows) <= 4 and all(len(values) <= 16 for values in rows.values())
        return [{"owner": token(owner), "consumers": sorted(
            [{"identity": token(user), "references": user.user_of_id(owner)} for user in rows.get(owner, ())],
            key=lambda item: (item["identity"]["pointer"], item["identity"]["session_uid"]))}
            for owner in sorted(owners, key=lambda item: item.as_pointer())]

    def inventory(self) -> str:
        mesh = None if self.work is None else self.work.data
        raw = {"mesh_attributes": [] if mesh is None else [{"name": item.name, "type": item.data_type,
                   "domain": item.domain, "length": len(item.data)} for item in mesh.attributes],
               "mesh_uv_maps": [] if mesh is None else [layer.name for layer in mesh.uv_layers],
               "bmesh_layer_families": None}
        assert len(raw["mesh_attributes"]) <= 64 and len(raw["mesh_uv_maps"]) <= 8
        if self.bm is not None and self.bm.is_valid:
            access = self.bm.loops.layers
            names = sorted(name for name in ("uv", "bool", "int", "float", "float_vector", "color", "float_color", "string")
                           if any(name in base.__dict__ for base in type(access).__mro__))
            raw["bmesh_layer_families"] = {name: list(getattr(access, name).keys()) for name in names}
            assert all(len(values) <= 64 for values in raw["bmesh_layer_families"].values())
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.data["inventories"][digest] = raw
        return digest

    def access(self, label: str, callback: Any) -> Any:
        row = {"label": label, "inventory_before": self.inventory()}
        self.data["getter_accesses"].append(row)
        self.flush()
        try:
            value = callback()
            row["returned_type"] = type(value).__module__ + "." + type(value).__name__
            return value
        finally:
            row["inventory_after"] = self.inventory()
            row["inventory_changed"] = row["inventory_before"] != row["inventory_after"]
            self.flush()

    def action(self, label: str, callback: Any) -> Any:
        row = {"label": label, "inventory_before": self.inventory(), "context_before": self.context(),
               "consumers_before": self.consumers()}
        self.data["actions"].append(row)
        self.flush()
        try:
            result = callback()
            row["returned"] = sorted(result) if isinstance(result, set) else None
            return result
        finally:
            row["inventory_after"], row["context_after"] = self.inventory(), self.context()
            row["consumers_after"] = self.consumers()
            self.flush()

    def map_roles(self) -> dict[str, Any]:
        mesh = self.work.data
        maps = list(mesh.uv_layers)
        return {"order": [layer.name for layer in maps], "active_index": mesh.uv_layers.active_index,
                "layers": [{"name": layer.name, "pointer": layer.as_pointer(),
                            **{name: bool(getattr(layer, name)) for name in ("active", "active_render", "active_clone")
                               if name in layer.bl_rna.properties}} for layer in maps]}

    def edit_active_role(self, stage: str) -> dict[str, Any]:
        collection = self.bm.loops.layers.uv
        available = has_static(collection, "active")
        if not available:
            return {"active_property_present": False, "name": None, "layer_wrapper": None,
                    "scope": "Live BMesh active layer semantics unavailable; never inferred from Mesh RNA"}
        active = self.access(stage + ":BMesh.uv.active", lambda: collection.active)
        if active is not None:
            assert has_static(active, "name"), "An active native UV layer requires an exposed name"
        name = None if active is None else self.access(stage + ":BMesh.uv.active.name", lambda: active.name)
        return {"active_property_present": True, "name": name,
                "layer_wrapper": None if active is None else wrapper(active),
                "scope": "Literal live BMesh active role; wrapper identity remains process-local only"}

    def mesh_view(self, obj: Any) -> dict[str, Any]:
        mesh = obj.data
        attributes = []
        for item in mesh.attributes:
            assert len(item.data) <= 64
            row = {"name": item.name, "type": item.data_type, "domain": item.domain, "length": len(item.data)}
            if item.data_type == "FLOAT2" and item.domain == "CORNER":
                row["values"] = [{"uv": list(value.vector), "float32_le": pair_bits(value.vector)} for value in item.data]
            elif item.data_type == "BOOLEAN":
                row["values"] = [bool(value.value) for value in item.data]
            attributes.append(row)
        return {"object": token(obj), "mesh": token(mesh), "mesh_users": mesh.users,
                "is_editmode": mesh.is_editmode, "transforms": {name: list(getattr(obj, name)) for name in (
                    "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")},
                "rotation_mode": obj.rotation_mode, "parent": token(obj.parent),
                "vertices": [{"index": v.index, "co": list(v.co), "co_float32_le": pair_bits(v.co),
                              "select": v.select, "hide": v.hide} for v in mesh.vertices],
                "edges": [{"index": e.index, "vertices": list(e.vertices), "seam": e.use_seam,
                           "select": e.select, "hide": e.hide} for e in mesh.edges],
                "faces": [{"index": f.index, "vertices": list(f.vertices), "loops": list(f.loop_indices),
                           "material": f.material_index, "smooth": f.use_smooth, "select": f.select, "hide": f.hide} for f in mesh.polygons],
                "loops": [{"vertex": loop.vertex_index, "edge": loop.edge_index} for loop in mesh.loops],
                "material_bindings": [token(material) for material in mesh.materials],
                "attributes": attributes}

    def edit_rest(self) -> dict[str, Any]:
        bm = self.bm
        return {"vertices": [{"index": v.index, "co": list(v.co), "co_float32_le": pair_bits(v.co),
                              "select": v.select, "hide": v.hide} for v in bm.verts],
                "edges": [{"index": e.index, "vertices": [v.index for v in e.verts], "seam": e.seam,
                           "smooth": e.smooth, "select": e.select, "hide": e.hide} for e in bm.edges],
                "faces": [{"index": f.index, "vertices": [v.index for v in f.verts], "material": f.material_index,
                           "smooth": f.smooth, "select": f.select, "hide": f.hide,
                           "loops": [{"vertex": loop.vert.index, "edge": loop.edge.index} for loop in f.loops]} for f in bm.faces],
                "active_face": None if bm.faces.active is None else bm.faces.active.index,
                "selection_history": [{"type": type(item).__name__, "index": item.index} for item in bm.select_history]}

    def object_uv_property(self, stage: str, name: str, field: str) -> list[Any]:
        values = self.access(stage + ":copy_MeshUVLoopLayer." + field + ":" + name,
            lambda: copy_object_uv_property(self.work.data, name, field))
        self.data["object_property_copies"].append({"stage": stage, "map": name, "property": field,
            "value_field": "vector" if field == "uv" else "value", "plain_values": values,
            "raw_length": len(values), "mesh_loop_count": len(self.work.data.loops),
            "empty_collection": not values,
            "scope": "Fresh named layer and complete primitive copy before the next materializing getter; no retained RNA collection"})
        self.flush()  # Retain this completed read before requesting another property.
        return values

    def read_maps(self, stage: str, *, edit: bool) -> dict[str, Any]:
        result = {}
        mesh = self.work.data
        for name in MAPS:
            corners = []
            if edit:
                layer = self.access(stage + ":layer.get:" + name, lambda name=name: self.bm.loops.layers.uv.get(name))
                assert layer is not None
                sources = [(face.index, i, loop.vert.index, loop.edge.index, loop)
                           for face in self.bm.faces for i, loop in enumerate(face.loops)]
            else:
                data = self.object_uv_property(stage, name, "uv")
                pins = self.object_uv_property(stage, name, "pin")
                assert len(data) == len(mesh.loops) and len(pins) in (0, len(mesh.loops))
                legacy_selection = {}
                if not self.global_selection:
                    for field in ("vertex_selection", "edge_selection"):
                        legacy_selection[field] = self.object_uv_property(stage, name, field)
                        assert len(legacy_selection[field]) == len(mesh.loops), "Legacy Object UV selection collection is unavailable"
                sources = [(face.index, i, mesh.loops[index].vertex_index, mesh.loops[index].edge_index, index)
                           for face in mesh.polygons for i, index in enumerate(face.loop_indices)]
            for face, corner, vertex, edge, source in sources:
                prefix = f"{stage}:{name}:{face}:{corner}:"
                if edit:
                    uv = self.access(prefix + "loop[layer]", lambda source=source, layer=layer: source[layer])
                    kind = type(uv)
                    if "uv_corner_wrapper" not in self.data:
                        self.data["uv_corner_wrapper"] = {"type": kind.__module__ + "." + kind.__name__,
                            "static_attributes": sorted(key for key in dir(kind) if not key.startswith("_")),
                            "is_valid_property_present": any("is_valid" in base.__dict__ for base in kind.__mro__)}
                        self.flush()
                    coordinates = self.access(prefix + "uv", lambda uv=uv: [float(value) for value in uv.uv])
                else:
                    coordinates = list(data[source])
                row = {"face": face, "corner": corner, "vertex": vertex, "edge": edge,
                       "uv": coordinates, "float32_le": pair_bits(coordinates)}
                fields = ("pin_uv",) if self.global_selection else ("pin_uv", "select", "select_edge")
                for field in fields:
                    if edit:
                        assert has_static(uv, field), (kind.__name__, field)
                        row[field] = self.access(prefix + field, lambda uv=uv, field=field: bool(getattr(uv, field)))
                    else:
                        values = pins if field == "pin_uv" else legacy_selection["vertex_selection" if field == "select" else "edge_selection"]
                        row[field] = None if field == "pin_uv" and not values else values[source]
                corners.append(row)
            result[name] = corners
        return result

    def uv_selection(self, stage: str, *, edit: bool) -> dict[str, Any]:
        if not self.global_selection:
            return {"storage": "PER_LAYER", "source": "Selection flags retained separately within each map corner"}
        if edit:
            return {"storage": "MESH_GLOBAL", "source": "BMLoop/BMFace/BMesh; not per-map data",
                "sync_valid": self.access(stage + ":BMesh.uv_select_sync_valid", lambda: bool(self.bm.uv_select_sync_valid)),
                "faces": [{"face": face.index, "selected": self.access(stage + f":BMFace{face.index}.uv_select",
                    lambda face=face: bool(face.uv_select))} for face in self.bm.faces],
                "corners": [{"face": face.index, "corner": corner, "vertex": loop.vert.index, "edge": loop.edge.index,
                    "select": self.access(stage + f":global{face.index}:{corner}:uv_select_vert", lambda loop=loop: bool(loop.uv_select_vert)),
                    "select_edge": self.access(stage + f":global{face.index}:{corner}:uv_select_edge", lambda loop=loop: bool(loop.uv_select_edge))}
                    for face in self.bm.faces for corner, loop in enumerate(face.loops)]}
        attributes = {}
        for name in (".uv_select_vert", ".uv_select_edge", ".uv_select_face"):
            attribute = self.work.data.attributes.get(name)
            attributes[name] = None if attribute is None else {"domain": attribute.domain, "type": attribute.data_type,
                "values": [bool(item.value) for item in attribute.data]}
        return {"storage": "MESH_GLOBAL", "source": "Literal Object Mesh attributes, with absent storage retained as null",
                "sync_valid": None, "sync_valid_scope": "No qualified Object Mesh getter; live BMesh value is retained separately",
                "attributes": attributes}

    def observe(self, label: str, *, edit: bool) -> dict[str, Any]:
        row = {"label": label, "authority": "live edit-BMesh" if edit else "Object Mode Mesh RNA",
               "context_before": self.context(), "inventory_before": self.inventory(),
               "consumers_before": self.consumers(),
               "object_mesh_view_before_uv_getters": self.mesh_view(self.work),
               "protected_peer": self.mesh_view(self.protected)}
        self.data["observations"].append(row)
        self.flush()
        if edit:
            row["edit_rest_before"] = self.edit_rest()
        row["map_roles"] = self.access(label + ":map_roles", self.map_roles)
        row["edit_active_role"] = self.edit_active_role(label) if edit else None
        row["maps"] = self.read_maps(label, edit=edit)
        row["uv_selection"] = self.uv_selection(label, edit=edit)
        row["inventory_after"], row["context_after"] = self.inventory(), self.context()
        row["object_mesh_view_after_uv_getters"] = self.mesh_view(self.work)
        row["protected_peer_after_uv_getters"] = self.mesh_view(self.protected)
        row["consumers_after"] = self.consumers()
        if edit:
            row["edit_rest_after"] = self.edit_rest()
        self.flush()
        assert row["context_before"] == row["context_after"]
        assert row["protected_peer"] == row["protected_peer_after_uv_getters"]
        assert row["consumers_before"] == row["consumers_after"]
        assert row["context_after"]["use_uv_select_sync"] is False
        if edit:
            assert row["edit_rest_before"] == row["edit_rest_after"]
        return row

    def lifetime(self, label: str, bm: Any, faces: list[Any], loops: list[Any], layers: dict[str, Any],
                 uv_wrapper: Any, *, reacquired: Any = None) -> None:
        row = {"label": label, "bmesh": wrapper(bm), "faces": [wrapper(face) for face in faces],
               "loops": [wrapper(loop) for loop in loops], "layers": {name: wrapper(layer) for name, layer in layers.items()},
               "uv_wrapper": wrapper(uv_wrapper)}
        if reacquired is not None:
            fresh_faces = list(reacquired.faces)
            fresh_loops = [loop for face in fresh_faces for loop in face.loops]
            fresh_layers = {name: self.access(label + ":reacquired_layer.get:" + name,
                lambda name=name: reacquired.loops.layers.uv.get(name)) for name in layers}
            row["reacquired_bmesh"] = wrapper(reacquired)
            row["reacquired_faces"] = [wrapper(face) for face in fresh_faces]
            row["reacquired_loops"] = [wrapper(loop) for loop in fresh_loops]
            row["reacquired_layers"] = {name: wrapper(layer) for name, layer in fresh_layers.items()}
            row["same_bmesh_python_wrapper"] = reacquired is bm
            row["same_loop_python_wrappers"] = [old is new for old, new in zip(loops, fresh_loops, strict=True)]
            row["same_layer_python_wrappers"] = {name: fresh_layers[name] is layer for name, layer in layers.items()}
        self.data["lifetime"].append(row)
        self.flush()


def main() -> None:
    import bmesh
    from blender_artist_quaternion_storage_smoke import owned_profile

    folder, process_token, attestation = owned_profile()
    proof = Proof(folder, attestation, process_token)
    try:
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
        proof.data["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
            Path(__file__), ROOT / "scripts/blender_artist_quaternion_storage_smoke.py", ROOT / "scripts/blender_artist_sidebar_smoke.py",
            ROOT / "addon/blender_codex_bridge/tools/uv_edit.py", ROOT / "addon/blender_codex_bridge/tools/_uv_selection.py")}
        mesh = bpy.data.meshes.new("UV Storage Checker Geometry")
        mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (2., 0., 0.), (0., 1., 0.), (1., 1., 0.), (2., 1., 0.)],
                         [], [(0, 1, 4, 3), (1, 2, 5, 4)])
        mesh.update()
        proof.work = bpy.data.objects.new("UV Storage Checker", mesh)
        proof.scene.collection.objects.link(proof.work)
        proof.data["capabilities"] = {"Mesh": rna_capabilities(mesh, ("attributes", "uv_layers", "uv_select_sync_valid")),
            "ToolSettings": rna_capabilities(proof.scene.tool_settings, ("use_uv_select_sync", "uv_select_mode", "mesh_select_mode"))}
        proof.data["setup_inventory_before_uv_maps"] = proof.inventory()
        proof.flush()
        for index, name in enumerate(MAPS):
            proof.action("setup_create_uv_map:" + name, lambda name=name: mesh.uv_layers.new(name=name))
            attribute = mesh.attributes.get(name)
            assert attribute is not None and attribute.data_type == "FLOAT2" and attribute.domain == "CORNER" and len(attribute.data) == 8
            for corner, value in enumerate(attribute.data):
                value.vector = (.125 * (corner + index), .25 * ((corner + index) % 3))
        mesh.uv_layers.active_index = 0
        proof.data["capabilities"]["MeshUVLoopLayer"] = rna_capabilities(mesh.uv_layers[0], ("data", "uv", "pin", "vertex_selection", "edge_selection", "active", "active_render", "active_clone"))
        for index, shade in enumerate((.8, .2)):
            material = bpy.data.materials.new("UV Storage Checker " + str(index))
            material.diffuse_color = (shade, shade, shade, 1.)
            mesh.materials.append(material)
            mesh.polygons[index].material_index = index
        mesh.edges[0].use_seam = True
        proof.layer.update()
        for obj in proof.layer.objects:
            obj.select_set(False, view_layer=proof.layer)
        proof.work.select_set(True, view_layer=proof.layer)
        proof.layer.objects.active = proof.work
        proof.scene.tool_settings.use_uv_select_sync = False
        proof.scene.tool_settings.mesh_select_mode = (False, False, True)
        proof.layer.update()
        proof.data["setup_object_mesh_before_optional_uv_getters"] = proof.mesh_view(proof.work)
        protected = proof.mesh_view(proof.protected)
        proof.data["protected_peer_baseline"] = protected
        proof.action("setup_enter_edit_mode", lambda: bpy.ops.object.mode_set(mode="EDIT"))
        def acquire_bmesh() -> Any:
            acquired = bmesh.from_edit_mesh(mesh)
            proof.bm = acquired
            return acquired

        proof.bm = proof.action("first_bmesh.from_edit_mesh", acquire_bmesh)
        proof.data["bmesh_capabilities_before_uv_access"] = {
            "bmesh": wrapper(proof.bm), "loop_layer_access_static_attributes": sorted(key for key in dir(type(proof.bm.loops.layers)) if not key.startswith("_")),
            "indices_before_lookup_preparation": {name: [item.index for item in getattr(proof.bm, name)] for name in ("verts", "edges", "faces")}}
        proof.flush()
        for name in ("verts", "edges", "faces"):
            sequence = getattr(proof.bm, name)
            proof.action("setup_ensure_lookup_table:" + name, sequence.ensure_lookup_table)
            proof.action("setup_index_update:" + name, sequence.index_update)
        selection_capabilities = {"BMesh.uv_select_sync_valid": has_static(proof.bm, "uv_select_sync_valid"),
            "BMFace.uv_select": all(has_static(face, "uv_select") for face in proof.bm.faces),
            "BMLoop.uv_select_vert": all(has_static(loop, "uv_select_vert") for face in proof.bm.faces for loop in face.loops),
            "BMLoop.uv_select_edge": all(has_static(loop, "uv_select_edge") for face in proof.bm.faces for loop in face.loops)}
        proof.data["native_uv_selection_capabilities_before_getters"] = selection_capabilities
        proof.flush()
        assert all(selection_capabilities.values()) or not any(selection_capabilities.values()), "Incomplete mesh-global UV selection API"
        proof.global_selection = all(selection_capabilities.values())
        if proof.global_selection:
            proof.action("setup_control_BMesh_global_uv_selection_valid_false", lambda: setattr(proof.bm, "uv_select_sync_valid", False))
        for face in proof.bm.faces:
            face.select_set(True)
        proof.bm.faces.active = proof.bm.faces[0]
        proof.bm.select_history.clear()
        proof.bm.select_history.add(proof.bm.faces[0])
        proof.action("setup_update_before_optional_uv_getters", lambda: bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False))
        before = proof.observe("first_complete_edit_observation_with_getter_effects", edit=True)
        if proof.global_selection:
            assert before["uv_selection"]["sync_valid"] is False
        bm = proof.bm
        faces, loops = list(bm.faces), [loop for face in bm.faces for loop in face.loops]
        layers = {name: proof.access("retain:layer.get:" + name, lambda name=name: bm.loops.layers.uv.get(name)) for name in MAPS}
        uv_wrapper = proof.access("retain:loopUV_wrapper", lambda: loops[0][layers[MAPS[0]]])
        proof.lifetime("retained_before_edits", bm, faces, loops, layers, uv_wrapper)
        baseline_rest, baseline_roles = before["edit_rest_after"], before["map_roles"]
        baseline_active = {key: value for key, value in before["edit_active_role"].items() if key != "layer_wrapper"}
        edits = (("coordinates", [(0, 0, (-0., .1)), (1, 2, (1.125, -0.))]),
                 ("transform", [(0, 1, None), (1, 3, None)]), ("pin", [(1, 1, None)]))
        for label, targets in edits:
            before = proof.observe(label + ":before", edit=True)
            expected = copy.deepcopy(before["maps"])
            prediction = {"label": label, "before_observation": before["label"], "requested": [], "expected_maps": expected}
            proof.data["edits"].append(prediction)
            for face, corner, requested in targets:
                target = next(item for item in expected[MAPS[0]] if item["face"] == face and item["corner"] == corner)
                if label == "pin":
                    target["pin_uv"] = not target["pin_uv"]
                    prediction["requested"].append({"face": face, "corner": corner, "vertex": target["vertex"],
                                                    "edge": target["edge"], "pinned": target["pin_uv"]})
                else:
                    if label == "transform":
                        x, y = (target["uv"][0] - .25) * 1.5, (target["uv"][1] - .25) * .5
                        requested = (.25 + .125 + math.cos(math.pi / 6.) * x - math.sin(math.pi / 6.) * y,
                                     .25 - .25 + math.sin(math.pi / 6.) * x + math.cos(math.pi / 6.) * y)
                    oracle = predicted_pair(requested)
                    prediction["requested"].append({"face": face, "corner": corner, "vertex": target["vertex"],
                                                    "edge": target["edge"], **oracle})
                    target["uv"], target["float32_le"] = oracle["expected"], oracle["expected_float32_le"]
            proof.flush()  # Full independent two-map prediction precedes the raw setters.
            def raw_setters(prediction: dict[str, Any] = prediction, label: str = label) -> None:
                for target in prediction["requested"]:
                    uv = proof.access(label + ":setter_loopUV_access", lambda target=target: bm.faces[
                        target["face"]].loops[target["corner"]][layers[MAPS[0]]])
                    if label == "pin":
                        uv.pin_uv = target["pinned"]
                    else:
                        uv.uv = target["requested"]

            proof.action(label + ":raw_setters", raw_setters)
            immediate = proof.observe(label + ":immediate_after_raw_assignment", edit=True)
            proof.action(label + ":update_edit_mesh", lambda: bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False))
            after_update = proof.observe(label + ":after_explicit_update", edit=True)
            fresh = proof.action(label + ":bmesh.from_edit_mesh", acquire_bmesh)
            proof.lifetime(label + ":after_update_reacquisition", bm, faces, loops, layers, uv_wrapper, reacquired=fresh)
            proof.bm = fresh
            reacquired = proof.observe(label + ":reacquired_edit_bmesh", edit=True)
            prediction["observations"] = [immediate["label"], after_update["label"], reacquired["label"]]
            proof.flush()
            for actual in (immediate, after_update, reacquired):
                assert actual["maps"] == expected
                assert actual["edit_rest_after"] == baseline_rest and logical_map_roles(actual["map_roles"]) == logical_map_roles(baseline_roles)
                assert {key: value for key, value in actual["edit_active_role"].items() if key != "layer_wrapper"} == baseline_active
                assert actual["context_after"] == before["context_before"] and actual["protected_peer"] == protected
                assert actual["uv_selection"] == before["uv_selection"] and actual["consumers_after"] == before["consumers_before"]
            assert fresh.is_valid and bm.is_valid and all(loop.is_valid for loop in loops)
        final_edit = proof.observe("before_explicit_mode_flush", edit=True)
        proof.action("explicit_mode_flush_to_object", lambda: bpy.ops.object.mode_set(mode="OBJECT"))
        proof.bm = None
        proof.lifetime("held_wrappers_after_mode_exit_no_descendant_dereference", bm, faces, loops, layers, uv_wrapper)
        final_object = proof.observe("after_mode_flush_object_view", edit=False)
        proof.flush()
        unavailable_pins = []
        for name in MAPS:
            for observed, wanted in zip(final_object["maps"][name], final_edit["maps"][name], strict=True):
                if observed["pin_uv"] is None:
                    unavailable_pins.append({"map": name, "face": observed["face"], "corner": observed["corner"], "vertex": observed["vertex"]})
                assert {key: value for key, value in observed.items() if key != "pin_uv" or value is not None} == {
                    key: value for key, value in wanted.items() if key != "pin_uv" or observed["pin_uv"] is not None}
        proof.data["object_pin_observation_limit"] = {"unavailable_corners": unavailable_pins,
            "scope": "Empty native Object pin collections remain raw empty and per-corner null; only exposed pin values compare here. Full live BMesh maps/pins equality after reentry remains mandatory."}
        proof.flush()
        assert final_object["protected_peer"] == protected
        assert logical_map_roles(final_object["map_roles"]) == logical_map_roles(baseline_roles)
        proof.action("explicit_mode_reentry", lambda: bpy.ops.object.mode_set(mode="EDIT"))
        fresh = proof.action("reentered_bmesh.from_edit_mesh", acquire_bmesh)
        proof.bm = fresh
        proof.lifetime("old_and_new_wrappers_after_reentry", bm, faces, loops, layers, uv_wrapper, reacquired=fresh)
        final_reentry = proof.observe("after_reentry_edit_bmesh", edit=True)
        proof.data["explicit_mode_transition_findings"] = {"edit_uv_selection_equal_before_exit_after_reentry":
            final_reentry["uv_selection"] == final_edit["uv_selection"],
            "active_face_equal": final_reentry["edit_rest_after"]["active_face"] == baseline_rest["active_face"],
            "selection_history_equal": final_reentry["edit_rest_after"]["selection_history"] == baseline_rest["selection_history"]}
        proof.flush()
        assert final_reentry["maps"] == final_edit["maps"]
        assert {key: value for key, value in final_reentry["edit_rest_after"].items() if key not in {"active_face", "selection_history"}} == {
            key: value for key, value in baseline_rest.items() if key not in {"active_face", "selection_history"}}
        assert final_reentry["protected_peer"] == protected
        assert logical_map_roles(final_reentry["map_roles"]) == logical_map_roles(baseline_roles)
        assert {key: value for key, value in final_reentry["edit_active_role"].items() if key != "layer_wrapper"} == baseline_active
        proof.data["completed"] = True
        proof.flush()
        print("BLENDER_UV_EDIT_STORAGE_OK " + json.dumps({"blender_version": bpy.app.version_string,
            "evidence_file": str(proof.path), "evidence_sha256": hashlib.sha256(proof.path.read_bytes()).hexdigest(),
            "maps": 2, "corners_per_map": 8, "raw_edits": 3, "getter_effects_retained": True,
            "mode_flush_and_reentry_observed": True, **proof.data["limits"]}, allow_nan=False), flush=True)
    except BaseException as error:
        proof.data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        proof.flush()
        raise


if __name__ == "__main__":
    from blender_artist_quaternion_storage_smoke import owned_profile

    owned_profile()
    from blender_artist_sidebar_smoke import owned_process_exit

    exit_code = 1
    try:
        main()
        exit_code = 0
    except BaseException:
        traceback.print_exc()
    finally:
        owned_process_exit(exit_code)
