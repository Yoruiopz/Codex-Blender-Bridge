"""Independent bounded fixture evidence without native pointers or session authority.

This is fixture support, not a public Blender inspector or a backup format.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Nonfinite native fixture evidence")
        return value
    if hasattr(value, "identifier") and hasattr(value, "handle"):
        return {"slot_identifier": value.identifier, "slot_handle": int(value.handle), "target": value.target_id_type}
    if hasattr(value, "name"):
        return {"type": value.bl_rna.identifier, "name": value.name}
    return [plain(item) for item in value]


def rna(owner: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    result = {}
    for prop in owner.bl_rna.properties:
        if prop.is_readonly or prop.identifier in (exclude or set()):
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}:
            raise ValueError("Unreviewed fixture RNA property kind")
        value = getattr(owner, prop.identifier)
        result[prop.identifier] = sorted(value) if prop.type == "ENUM" and prop.is_enum_flag else plain(value)
    return result


def curve(curve: Any) -> dict[str, Any]:
    assert len(curve.keyframe_points) <= 256 and len(curve.modifiers) <= 32 and not len(curve.sampled_points)
    return {"settings": rna(curve), "keys": [rna(point) for point in curve.keyframe_points],
            "modifiers": [rna(modifier) for modifier in curve.modifiers]}


def action(action: Any) -> dict[str, Any]:
    assert len(action.slots) <= 64 and len(action.layers) <= 16
    return {"metadata": rna(action, {"use_extra_user"}),
            "slots": [{"identifier": slot.identifier, "handle": int(slot.handle), "target": slot.target_id_type} for slot in action.slots],
            "layers": [{"settings": rna(layer), "strips": [{"settings": rna(strip), "bags": [
                {"slot_handle": bag.slot_handle, "curves": [curve(item) for item in bag.fcurves],
                 "groups": [{"settings": rna(group), "colors": rna(group.colors)} for group in bag.groups]}
                for bag in strip.channelbags]} for strip in layer.strips]} for layer in action.layers],
            "markers": [rna(marker) for marker in action.pose_markers]}


def animation(obj: Any) -> dict[str, Any] | None:
    data = obj.animation_data
    if data is None:
        return None
    assert len(data.nla_tracks) <= 16 and sum(len(track.strips) for track in data.nla_tracks) <= 64
    return {"settings": rna(data), "active_track": None if data.nla_tracks.active is None else data.nla_tracks.active.name,
            "tracks": [{"settings": rna(track), "strips": [{"settings": rna(strip), "type": strip.type,
                "controls": [curve(item) for item in strip.fcurves], "modifiers": [rna(item) for item in strip.modifiers]}
                for strip in track.strips]} for track in data.nla_tracks],
            "drivers": [curve(item) for item in data.drivers]}


def material(material: Any) -> Any:
    if material is None:
        return None
    assert material.use_nodes and len(material.node_tree.nodes) < 32 and len(material.node_tree.links) < 64
    return {"name": material.name, "settings": rna(material, {"use_extra_user"}), "nodes": [
        {"settings": rna(node), "inputs": [{"identifier": socket.identifier, "value": plain(socket.default_value)}
            for socket in node.inputs if hasattr(socket, "default_value")]}
        for node in material.node_tree.nodes], "links": [
            [link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier]
            for link in material.node_tree.links]}


def rest(obj: Any) -> dict[str, Any]:
    mesh = obj.data
    assert len(mesh.vertices) <= 4096 and len(mesh.loops) <= 16384
    attributes = []
    for attribute in mesh.attributes:
        records = []
        for item in attribute.data:
            fields = [field for field in ("value", "vector", "color", "uv") if hasattr(item, field)]
            assert fields
            records.append(plain(getattr(item, fields[0])))
        attributes.append({"name": attribute.name, "domain": attribute.domain, "type": attribute.data_type, "values": records})
    return {"object": obj.name, "data": mesh.name, "parent": plain(obj.parent),
            "matrix_parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
            "groups": [{"name": group.name, "index": group.index, "locked": group.lock_weight} for group in obj.vertex_groups],
            "vertices": [{"co": list(vertex.co), "weights": sorted([member.group, member.weight] for member in vertex.groups)} for vertex in mesh.vertices],
            "edges": [{"vertices": list(edge.vertices), "seam": edge.use_seam, "sharp": edge.use_edge_sharp} for edge in mesh.edges],
            "polygons": [{"vertices": list(face.vertices), "material": face.material_index, "smooth": face.use_smooth} for face in mesh.polygons],
            "uv_layers": [{"name": layer.name, "render": layer.active_render, "uv": [list(loop.uv) for loop in layer.data]} for layer in mesh.uv_layers],
            "attributes": attributes, "materials": [material(item) for item in mesh.materials],
            "modifiers": [{"type": modifier.type, "settings": rna(modifier)} for modifier in obj.modifiers]}


def rig_rest(obj: Any) -> dict[str, Any]:
    assert len(obj.data.bones) <= 32
    return {"object": obj.name, "data": obj.data.name, "bones": [
        {"settings": rna(bone), "head": list(bone.head_local), "tail": list(bone.tail_local),
         "matrix": [list(row) for row in bone.matrix_local], "collections": sorted(collection.name for collection in bone.collections)}
        for bone in obj.data.bones]}


def evaluated(scene: Any, graph: Any, rig: Any, skin: Any) -> dict[str, Any]:
    posed = rig.evaluated_get(graph)
    transformed = skin.evaluated_get(graph)
    mesh = transformed.to_mesh()
    try:
        vertices = [list(transformed.matrix_world @ vertex.co) for vertex in mesh.vertices]
    finally:
        transformed.to_mesh_clear()
    return {"frame": scene.frame_current, "bones": {bone.name: [list(row) for row in posed.matrix_world @ bone.matrix] for bone in posed.pose.bones},
            "vertices": vertices}


def max_difference(before: Any, after: Any) -> float:
    if isinstance(before, dict):
        assert isinstance(after, dict) and set(before) == set(after)
        return max((max_difference(value, after[key]) for key, value in before.items()), default=0.)
    if isinstance(before, list):
        assert isinstance(after, list) and len(before) == len(after)
        return max((max_difference(a, b) for a, b in zip(before, after, strict=True)), default=0.)
    if isinstance(before, (int, float)) and not isinstance(before, bool):
        assert isinstance(after, (int, float)) and not isinstance(after, bool)
        assert math.isfinite(before) and math.isfinite(after)
        return abs(before-after)
    assert type(before) is type(after) and before == after
    return 0.
