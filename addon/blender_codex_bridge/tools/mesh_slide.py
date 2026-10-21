"""Measured coordinate slides on explicit neighboring rails; no inferred topology."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import struct
from collections import Counter
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import float_param, int_param, reject_unknown_params
from ._mesh_safety import require_local_single_user_mesh
from ._object_safety import require_local_editable_id
from .interaction import _active_edit_mesh
from .mesh import _id_name
from .mesh_repair import _adjacent_faces

try:
    import bmesh
except ImportError:  # pragma: no cover
    bmesh = None

LOGGER = logging.getLogger(__name__)
MAX_TARGETS = 4096
MAX_UV_CORNERS = 500_000


def _gate(context: ToolContext, *, modifying=False, recovery=False) -> None:
    permission = Permission.EDIT_MESH if modifying else Permission.INSPECT_SCENE
    context.require(permission)
    if not recovery and context.check_cancelled:
        context.check_cancelled()
    flags = context.state.snapshot() if getattr(context, "state", None) else {}
    if modifying and not recovery:
        if flags.get("emergency_stopped"):
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Mesh slide emergency-stopped.")
        if flags.get("paused"):
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Mesh slide is paused.")
    context.require(permission)


def _point(values) -> tuple[float, float, float]:
    values = tuple(float(value) for value in values)
    if len(values) != 3 or not all(math.isfinite(value) and abs(value) <= 1e6 for value in values):
        raise invalid_argument("Mesh slide coordinates must be finite and within +/-1000000 local units.")
    return struct.unpack("<fff", struct.pack("<fff", *values))


def _identity(value):
    return int(value.as_pointer()) if hasattr(value, "as_pointer") else id(value)


def _ownership(obj, bm):
    return {"object": _identity(obj), "mesh": _identity(obj.data),
        "users": int(obj.data.users), "object_editable": bool(getattr(obj, "is_editable", True)),
        "mesh_editable": bool(getattr(obj.data, "is_editable", True)),
        "mode": getattr(obj, "mode", "EDIT"),
        "shape_keys": bool(getattr(obj.data, "shape_keys", None)),
        "bmesh_valid": bool(getattr(bm, "is_valid", True)),
        "libraries": [bool(getattr(owner, "library", None)) for owner in (obj, obj.data)],
        "overrides": [bool(getattr(owner, "override_library", None)) for owner in (obj, obj.data)]}


def _assert_session(obj, bm, ownership):
    _bpy, current, live, _sequences = _active_edit_mesh(obj.name)
    # from_edit_mesh can return a different Python BMesh wrapper for the same
    # native edit mesh. Wrapper id is neither a persistent preview identity nor
    # an edit-session proof. Retain original liveness and native element handles.
    same_elements = all(len(first) == len(second) and (not first or (
        first[0] == second[0] and first[-1] == second[-1]))
        for first, second in ((bm.verts, live.verts), (bm.edges, live.edges), (bm.faces, live.faces)))
    if _identity(current) != _identity(obj) or not same_elements or _ownership(obj, bm) != ownership:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Mesh ownership or Edit Mode session changed; reinspect before editing or recovery.")
    require_local_single_user_mesh(obj)
    require_local_editable_id(obj, operation="Mesh coordinate/UV refinement")
    require_local_editable_id(obj.data, operation="Mesh coordinate/UV refinement")


def _sub(first, second):
    return tuple(a - b for a, b in zip(first, second, strict=True))


def _dot(first, second):
    return sum(a * b for a, b in zip(first, second, strict=True))


def _cross(first, second):
    return (first[1]*second[2] - first[2]*second[1],
            first[2]*second[0] - first[0]*second[2], first[0]*second[1] - first[1]*second[0])


def _snapshot(obj, bm) -> dict:
    layers = list(bm.loops.layers.uv.values())
    if sum(len(face.loops) for face in bm.faces) * len(layers) > MAX_UV_CORNERS:
        raise invalid_argument("Slide preservation snapshot exceeds 500000 UV corners across layers.")
    active = bm.loops.layers.uv.active
    return {"ownership": _ownership(obj, bm),
        "vertices": [(_point(vertex.co), bool(vertex.select), bool(vertex.hide)) for vertex in bm.verts],
        "edges": [(tuple(vertex.index for vertex in edge.verts), bool(edge.select), bool(edge.hide),
                   bool(edge.seam), bool(edge.smooth)) for edge in bm.edges],
        "faces": [(tuple(vertex.index for vertex in face.verts), bool(face.select), bool(face.hide),
                   int(face.material_index), bool(face.smooth)) for face in bm.faces],
        "uv_active": active.name if active is not None else None,
        "uv": [(layer.name, [(tuple(loop[layer].uv), bool(loop[layer].pin_uv),
            getattr(loop[layer], "select", None), getattr(loop[layer], "select_edge", None))
            for face in bm.faces for loop in face.loops]) for layer in layers],
        "materials": [(material.name, _identity(material)) if material else None for material in obj.data.materials]}


def _face_checks(faces, proposed) -> int:
    checked = 0
    for face in faces:
        if len(face.verts) not in {3, 4}:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Slide safety currently checks triangle/quad fans only.")
        before = [_point(vertex.co) for vertex in face.verts]
        after = [proposed.get(vertex.index, before[index]) for index, vertex in enumerate(face.verts)]
        for index in range(1, len(before)-1):
            old = _cross(_sub(before[index], before[0]), _sub(before[index+1], before[0]))
            new = _cross(_sub(after[index], after[0]), _sub(after[index+1], after[0]))
            old_area, new_area = _dot(old, old), _dot(new, new)
            if old_area <= 1e-20 or new_area < old_area * 1e-8 or _dot(old, new) <= 0.:
                raise invalid_argument("Slide would degenerate or invert an affected face fan; choose a smaller factor or different rails.", face_index=face.index)
            checked += 1
    return checked


def _prepare(context: ToolContext, params: Mapping[str, Any], mode: str, *, modifying=False):
    _gate(context, modifying=modifying)
    if not isinstance(mode, str) or mode not in {"VERTEX", "EDGE"}:
        raise invalid_argument("Slide mode must be VERTEX or EDGE.")
    name = _id_name(params.get("object_name"), "object_name")
    reference_id = _id_name(params.get("selection_id"), "selection_id")
    factor = float_param(params, "factor", 0., minimum=0., maximum=.95)
    maximum = float_param(params, "max_distance", 0., minimum=1e-9, maximum=1e6)
    targets = params.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
        raise invalid_argument("targets must contain 1-4096 exact vertex/rail-neighbor records.")
    bpy, obj, bm, _sequences = _active_edit_mesh(name)
    require_local_single_user_mesh(obj)
    require_local_editable_id(obj, operation="Mesh slide")
    require_local_editable_id(obj.data, operation="Mesh slide")
    if obj.data.shape_keys is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shape-key meshes need a separate slide ownership contract.")
    reference = validate_selection_reference(reference_id, obj, bm)
    mappings = {}
    for record in targets:
        if not isinstance(record, Mapping) or set(record) != {"vertex_index", "target_vertex_index"}:
            raise invalid_argument("Each slide target needs exactly vertex_index and target_vertex_index.")
        vertex = int_param(record, "vertex_index", -1, minimum=0, maximum=len(bm.verts)-1)
        target = int_param(record, "target_vertex_index", -1, minimum=0, maximum=len(bm.verts)-1)
        if vertex in mappings or vertex == target:
            raise invalid_argument("Slide vertices must be distinct and cannot target themselves.")
        mappings[vertex] = target
    if set(mappings.values()) & set(mappings):
        raise invalid_argument("Rail targets must stay outside the moving vertex scope.")
    if mode == "VERTEX":
        if not set(mappings).issubset(reference["vertices"]):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "A moving vertex lies outside the referenced vertex selection.")
    else:
        edges = [bm.edges[index] for index in reference["edges"]]
        if not edges or len(edges) > MAX_TARGETS or any(edge.hide or len(edge.link_faces) > 2 for edge in edges):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Edge slides require one visible manifold selected chain/loop.")
        degrees = Counter(vertex.index for edge in edges for vertex in edge.verts)
        if set(degrees) != set(mappings) or any(value > 2 for value in degrees.values()) or sum(value == 1 for value in degrees.values()) not in {0, 2}:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Provide exactly one rail for every vertex of a non-branching selected edge chain/loop.")
        adjacency = {index: set() for index in degrees}
        for edge in edges:
            first, second = (vertex.index for vertex in edge.verts)
            adjacency[first].add(second)
            adjacency[second].add(first)
        pending, connected = [next(iter(degrees))], set()
        while pending:
            vertex = pending.pop()
            if vertex in connected:
                continue
            connected.add(vertex)
            pending.extend(adjacency[vertex] - connected)
        if connected != set(degrees):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Edge-slide scope must be one connected chain/loop.")
    moving = [bm.verts[index] for index in mappings]
    faces = _adjacent_faces(moving)
    proposed, items = {}, []
    for index, target_index in mappings.items():
        vertex, target = bm.verts[index], bm.verts[target_index]
        rails = [edge for edge in vertex.link_edges if target in edge.verts]
        if vertex.hide or target.hide or len(rails) != 1 or rails[0].hide or len(rails[0].link_faces) > 2:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Every explicit rail must be one visible neighboring edge with at most two incident faces.")
        _adjacent_faces([rails[0]])
        source, endpoint = _point(vertex.co), _point(target.co)
        output = _point(tuple(a + factor * (b-a) for a, b in zip(source, endpoint, strict=True)))
        distance = math.sqrt(_dot(_sub(output, source), _sub(output, source)))
        if distance > maximum + 1e-9 or _dot(_sub(endpoint, source), _sub(endpoint, source)) <= 1e-20:
            raise invalid_argument("Slide exceeds max_distance or uses a zero-length rail.", vertex_index=index, distance_local=distance)
        proposed[index] = output
        items.append({"vertex_index": index, "target_vertex_index": target_index, "rail_edge_index": rails[0].index,
            "before_local": list(source), "after_local": list(output), "distance_local": distance})
    checked = _face_checks(faces, proposed)
    snapshot = _snapshot(obj, bm)
    fingerprint = hashlib.sha256(json.dumps({"state": snapshot, "mode": mode, "targets": targets,
        "factor": factor, "max_distance": maximum}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return bpy, obj, bm, snapshot, proposed, {"object": obj.name, "mode": mode, "fingerprint": fingerprint,
        "factor": factor, "max_distance": maximum, "coordinate_space": "LOCAL", "target_count": len(items),
        "affected_face_count": len(faces), "checked_face_triangles": checked, "items": items[:64],
        "items_truncated": len(items) > 64, "maximum_distance_local": max(item["distance_local"] for item in items),
        "limitations": "Explicit existing-edge interpolation, not automatic edge-slide correspondence, surface projection, collision testing or full retopology."}


def slide_preview(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "selection_id", "mode", "targets", "factor", "max_distance"})
    return {**_prepare(context, params, params.get("mode"))[5], "changed": False}


def _slide(context: ToolContext, params: Mapping[str, Any], mode: str) -> dict:
    reject_unknown_params(params, {"object_name", "selection_id", "targets", "factor", "max_distance", "expected_fingerprint"})
    _bpy, obj, bm, before, proposed, preview = _prepare(context, params, mode, modifying=True)
    if params.get("expected_fingerprint") != preview["fingerprint"]:
        raise invalid_argument("Slide requires the exact current preview fingerprint; reinspect moved coordinates or rails.")
    expected = {**before, "vertices": [(proposed.get(index, point), selected, hidden)
        for index, (point, selected, hidden) in enumerate(before["vertices"])]}
    written = []
    try:
        _gate(context, modifying=True)
        _assert_session(obj, bm, before["ownership"])
        if _snapshot(obj, bm) != before:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Slide source changed after preview validation; reinspect before retrying.")
        for index, (vertex_index, point) in enumerate(proposed.items()):
            if index % 64 == 0:
                _gate(context, modifying=True)
                _assert_session(obj, bm, before["ownership"])
            written.append(vertex_index)
            bm.verts[vertex_index].co = point
        bm.normal_update()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        _gate(context, modifying=True)
        _assert_session(obj, bm, before["ownership"])
        if _snapshot(obj, bm) != expected:
            raise RuntimeError("Slide readback or protected mesh/UV state did not match")
    except Exception as error:
        restored = False
        try:
            _gate(context, modifying=True, recovery=True)
            _assert_session(obj, bm, before["ownership"])
            for vertex_index in written:
                current = _point(bm.verts[vertex_index].co)
                if current == before["vertices"][vertex_index][0]:
                    continue
                if current != proposed[vertex_index]:
                    raise RuntimeError("Slide output was replaced by an interleaved edit")
                bm.verts[vertex_index].co = before["vertices"][vertex_index][0]
            bm.normal_update()
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            restored = _snapshot(obj, bm) == before
        except Exception:
            LOGGER.exception("Mesh slide local restoration could not be verified")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Mesh slide did not complete; inspect source and native recovery evidence.",
            {"object": obj.name, "affected_objects": [obj.name], "execution_started": bool(written),
             "rollback_verified": restored, "possible_mutation": not restored, "verification_required": True}) from error
    return {**preview, "changed": before != expected, "affected_objects": [obj.name],
        "topology_changed": False, "selection_changed": False, "uv_layers_preserved": True,
        "protected_vertices_preserved": True, "verification_required": True}


def vertex_slide(context: ToolContext, params: Mapping[str, Any]) -> dict:
    return _slide(context, params, "VERTEX")


def edge_slide(context: ToolContext, params: Mapping[str, Any]) -> dict:
    return _slide(context, params, "EDGE")


def register_tools(registry: ToolRegistry) -> None:
    registry.register("mesh.slide_preview", slide_preview, toolset="mesh", permissions=(Permission.INSPECT_SCENE,),
        description="Preview measured selected vertex/edge slides along explicit neighboring rails and fingerprint protected geometry/UV state.")
    for name, handler in (("mesh.vertex_slide", vertex_slide), ("mesh.edge_slide", edge_slide)):
        registry.register(name, handler, toolset="mesh", modifies=True, permissions=(Permission.EDIT_MESH,),
            description="Slide an explicit selected vertex/edge scope along existing adjacent rails using a current preview, local distance bound and face-inversion checks; preserve topology/UV/context.")
