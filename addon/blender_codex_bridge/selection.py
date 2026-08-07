"""Current selection inspection and temporary selection references."""

from __future__ import annotations

import hashlib
import struct
import threading
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .errors import BridgeError, ErrorCode
from .utils import bool_param, object_identifier, require_blender

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

_SELECTIONS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_MAX_SELECTION_REFERENCES = 32
_MAX_SELECTION_REFERENCE_ELEMENTS = 50_000
_MAX_SELECTED_OBJECTS = 200
_SELECTION_LOCK = threading.RLock()


def topology_fingerprint(bm: Any) -> dict[str, Any]:
    """Hash mesh connectivity so count-preserving topology edits go stale too."""

    digest = hashlib.blake2b(digest_size=16)
    digest.update(struct.pack("<QQQ", len(bm.verts), len(bm.edges), len(bm.faces)))
    for edge in bm.edges:
        first, second = sorted((edge.verts[0].index, edge.verts[1].index))
        digest.update(struct.pack("<QQ", first, second))
    for face in bm.faces:
        digest.update(struct.pack("<Q", len(face.verts)))
        for vertex in face.verts:
            digest.update(struct.pack("<Q", vertex.index))
    return {
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "connectivity": digest.hexdigest(),
    }


def _bounds(
    minimum: list[float] | None,
    maximum: list[float] | None,
) -> tuple[dict[str, list[float]] | None, list[float] | None]:
    if minimum is None or maximum is None:
        return None, None
    center = [(minimum[index] + maximum[index]) * 0.5 for index in range(3)]
    return (
        {"min": [float(value) for value in minimum], "max": [float(value) for value in maximum]},
        [float(value) for value in center],
    )


def _store_selection(
    obj: Any,
    bm: Any,
    vertex_indices: list[int],
    edge_indices: list[int],
    face_indices: list[int],
) -> str:
    bpy = require_blender()
    selection_id = f"sel_{uuid.uuid4().hex[:10]}"
    reference = {
        "selection_id": selection_id,
        "object": obj.name,
        "object_id": object_identifier(obj),
        "mesh_id": object_identifier(obj.data),
        "scene_id": object_identifier(bpy.context.scene),
        "view_layer": bpy.context.view_layer.name,
        "vertices": vertex_indices,
        "edges": edge_indices,
        "faces": face_indices,
        "topology": topology_fingerprint(bm),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "valid_until_topology_changes": True,
    }
    with _SELECTION_LOCK:
        _SELECTIONS[selection_id] = reference
        while len(_SELECTIONS) > _MAX_SELECTION_REFERENCES:
            _SELECTIONS.popitem(last=False)
    return selection_id


def resolve_selection(selection_id: str) -> dict[str, Any]:
    with _SELECTION_LOCK:
        try:
            return dict(_SELECTIONS[selection_id])
        except KeyError as exc:
            raise BridgeError(
                ErrorCode.INVALID_SELECTION,
                f"Selection reference '{selection_id}' is unknown or expired.",
            ) from exc


def clear_selection_references(object_name: str | None = None) -> int:
    """Invalidate all session handles, or only handles for one object."""

    if object_name is None:
        with _SELECTION_LOCK:
            count = len(_SELECTIONS)
            _SELECTIONS.clear()
            return count
    with _SELECTION_LOCK:
        stale = [
            selection_id
            for selection_id, reference in _SELECTIONS.items()
            if reference.get("object") == object_name
        ]
        for selection_id in stale:
            _SELECTIONS.pop(selection_id, None)
        return len(stale)


def validate_selection_reference(selection_id: str, obj: Any, bm: Any) -> dict[str, Any]:
    """Resolve a handle only while object identity and topology still match."""

    reference = resolve_selection(selection_id)
    bpy = require_blender()
    identity_matches = (
        reference["object"] == obj.name
        and reference.get("object_id") == object_identifier(obj)
        and reference.get("mesh_id") == object_identifier(obj.data)
        and reference.get("scene_id") == object_identifier(bpy.context.scene)
        and reference.get("view_layer") == bpy.context.view_layer.name
    )
    if not identity_matches:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Selection reference belongs to another or replaced object.",
            {
                "selection_object": reference["object"],
                "target_object": obj.name,
            },
        )
    if reference.get("topology") != topology_fingerprint(bm):
        clear_selection_references(obj.name)
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Mesh topology changed after the selection reference was created.",
            {"selection_id": selection_id, "object": obj.name},
        )
    return reference


def inspect_selection(params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    bpy = require_blender()
    params = params or {}
    create_id = bool_param(params, "create_selection_id", True)
    active = bpy.context.view_layer.objects.active
    all_selected_objects = list(bpy.context.selected_objects)
    selected_objects = [
        {"name": obj.name, "id": object_identifier(obj), "type": obj.type}
        for obj in all_selected_objects[:_MAX_SELECTED_OBJECTS]
    ]
    result: dict[str, Any] = {
        "mode": bpy.context.mode,
        "active_object": active.name if active else None,
        "selected_objects": selected_objects,
        "selected_object_count": len(all_selected_objects),
        "selected_objects_truncated": len(all_selected_objects) > len(selected_objects),
    }
    if active is None or active.type != "MESH" or active.mode != "EDIT":
        result["mesh_selection"] = None
        return result
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    bm = bmesh.from_edit_mesh(active.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    vertex_indices: list[int] = []
    edge_indices: list[int] = []
    face_indices: list[int] = []
    selected_vertices = 0
    selected_edges = 0
    selected_faces = 0
    cached_elements = 0
    minimum: list[float] | None = None
    maximum: list[float] | None = None
    for vertex in bm.verts:
        if not vertex.select:
            continue
        selected_vertices += 1
        if cached_elements < _MAX_SELECTION_REFERENCE_ELEMENTS:
            vertex_indices.append(vertex.index)
            cached_elements += 1
        point = active.matrix_world @ vertex.co
        if minimum is None:
            minimum = [float(point[index]) for index in range(3)]
            maximum = list(minimum)
        else:
            assert maximum is not None
            for index in range(3):
                value = float(point[index])
                minimum[index] = min(minimum[index], value)
                maximum[index] = max(maximum[index], value)
    for edge in bm.edges:
        if edge.select:
            selected_edges += 1
            if cached_elements < _MAX_SELECTION_REFERENCE_ELEMENTS:
                edge_indices.append(edge.index)
                cached_elements += 1
    for face in bm.faces:
        if face.select:
            selected_faces += 1
            if cached_elements < _MAX_SELECTION_REFERENCE_ELEMENTS:
                face_indices.append(face.index)
                cached_elements += 1
    bounds, center = _bounds(minimum, maximum)
    selected_element_count = selected_vertices + selected_edges + selected_faces
    mesh_selection: dict[str, Any] = {
        "object": active.name,
        "object_id": object_identifier(active),
        "selected_vertices": selected_vertices,
        "selected_edges": selected_edges,
        "selected_faces": selected_faces,
        "selection_modes": sorted(bm.select_mode),
        "world_bounding_box": bounds,
        "world_center": center,
    }
    if create_id and selected_element_count <= _MAX_SELECTION_REFERENCE_ELEMENTS:
        mesh_selection["selection_id"] = _store_selection(
            active, bm, vertex_indices, edge_indices, face_indices
        )
    elif create_id:
        mesh_selection["selection_id"] = None
        mesh_selection["selection_reference_truncated"] = True
        mesh_selection["selection_reference_limit"] = _MAX_SELECTION_REFERENCE_ELEMENTS
    result["mesh_selection"] = mesh_selection
    return result
