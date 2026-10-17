"""Inspected quad-ring cuts and native closed-loop bridging."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import int_param, reject_unknown_params
from ._mesh_safety import require_local_single_user_mesh
from .interaction import MAX_MESH_ELEMENTS, _active_edit_mesh
from .mesh import _id_name, _mesh_counts
from .mesh_repair import _adjacent_faces, _check_cancelled, _result, _scope

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

MAX_RING_EDGES = 4_096
MAX_LOOP_EDGES = 1_024


@dataclass
class Ring:
    edges: list[Any]
    faces: list[Any]
    closed: bool


def _ring(bm: Any, seed: Any, context: ToolContext) -> Ring:
    if not seed.link_faces:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "A quad ring cannot start on a wire edge.")
    pending = [seed]
    edges = {seed}
    faces = set()
    boundary = set()
    while pending:
        edge = pending.pop()
        if edge.hide or any(vertex.hide for vertex in edge.verts):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "The ring reaches hidden geometry; reveal it explicitly first.")
        if len(edge.link_faces) > 2:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Quad-ring cuts do not cross non-manifold edges.")
        if len(edge.link_faces) == 1:
            boundary.add(edge)
        for face in edge.link_faces:
            if len(face.verts) != 4:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The ring touches a non-quad face; this cut requires a complete quad strip.", {"face_index": face.index})
            faces.add(face)
            opposite = face.edges[(list(face.edges).index(edge) + 2) % 4]
            if opposite not in edges:
                edges.add(opposite)
                if len(edges) > MAX_RING_EDGES:
                    raise invalid_argument("Ring traversal exceeds its edge budget.", maximum_edges=MAX_RING_EDGES)
                pending.append(opposite)
        if len(edges) % 64 == 0:
            _check_cancelled(context)
    if len(boundary) not in {0, 2} or any(sum(edge in edges for edge in face.edges) != 2 for face in faces):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The ring is self-crossing or does not form a simple open/closed quad strip.")
    _adjacent_faces(list(edges))  # Includes hidden corners/edges and bounded face-corner checks.
    return Ring(sorted(edges, key=lambda item: item.index), sorted(faces, key=lambda item: item.index), not boundary)


def _ring_target(params: Mapping[str, Any], *, modifying: bool) -> tuple[Any, Any, Any]:
    name = _id_name(params.get("object_name"), "object_name")
    seed_index = int_param(params, "seed_edge_index", -1, minimum=0, maximum=200_000)
    reference_id = params.get("selection_id")
    if reference_id is not None and (not isinstance(reference_id, str) or not reference_id):
        raise invalid_argument("'selection_id' must be a non-empty string.")
    if modifying and reference_id is None:
        raise invalid_argument("A quad-ring cut requires a fresh edge selection_id containing its seed.")
    _bpy, obj, bm, _sequences = _active_edit_mesh(name)
    if modifying:
        require_local_single_user_mesh(obj)
        if obj.data.shape_keys is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Loop cuts do not yet support shape-key meshes.")
    if seed_index >= len(bm.edges):
        raise invalid_argument("The seed edge index is out of range.")
    if reference_id is not None:
        reference = validate_selection_reference(reference_id, obj, bm)
        if seed_index not in reference["edges"]:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "The seed is not in the referenced edge selection.")
    return obj, bm, bm.edges[seed_index]


def _cut_counts(before: Mapping[str, int], ring: Ring, cuts: int) -> dict[str, int]:
    return {"vertices": before["vertices"] + len(ring.edges) * cuts,
            "edges": before["edges"] + (len(ring.edges) + len(ring.faces)) * cuts,
            "faces": before["faces"] + len(ring.faces) * cuts}


def edge_ring_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "seed_edge_index", "selection_id", "cuts", "offset", "max_items"})
    cuts = int_param(params, "cuts", 1, minimum=1, maximum=32)
    offset = int_param(params, "offset", 0, minimum=0, maximum=MAX_RING_EDGES)
    maximum = int_param(params, "max_items", 100, minimum=1, maximum=256)
    obj, bm, seed = _ring_target(params, modifying=False)
    ring = _ring(bm, seed, context)
    expected = _cut_counts(_mesh_counts(bm), ring, cuts)
    items = []
    for edge in ring.edges[offset:offset + maximum]:
        center = (edge.verts[0].co + edge.verts[1].co) * .5
        items.append({"edge_index": edge.index, "vertex_indices": [v.index for v in edge.verts],
                      "center_local": list(center), "center_world": list(obj.matrix_world @ center)})
    more = offset + len(items) < len(ring.edges)
    return {"object": obj.name, "closed": ring.closed, "ring_edge_count": len(ring.edges),
            "crossed_quad_count": len(ring.faces), "items": items, "offset": offset,
            "truncated": more, "next_offset": offset + len(items) if more else None,
            "expected_counts_after": expected, "within_output_budget": sum(expected.values()) <= MAX_MESH_ELEMENTS,
            "mesh_users": obj.data.users, "shape_keys_present": obj.data.shape_keys is not None,
            "scope": "Entire connected quad ring, including unselected edges/faces; not a selection-limited cut.",
            "index_validity": "Reinspect after topology, mode, undo or scene changes. Preview does not reserve the mesh."}


def loop_cut(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "seed_edge_index", "selection_id", "cuts"})
    cuts = int_param(params, "cuts", 1, minimum=1, maximum=32)
    obj, bm, seed = _ring_target(params, modifying=True)
    ring = _ring(bm, seed, context)
    before = _mesh_counts(bm)
    expected = _cut_counts(before, ring, cuts)
    if sum(expected.values()) > MAX_MESH_ELEMENTS:
        raise invalid_argument("The ring cut would exceed the 200,000-element inspection budget.", expected_counts_after=expected)
    _check_cancelled(context)
    bmesh.ops.subdivide_edges(bm, edges=ring.edges, cuts=cuts, smooth=0.0, fractal=0.0,
                              use_grid_fill=False, use_only_quads=True)
    bm.normal_update()
    result = _result(obj, bm, before, changed=True)
    if result["mesh_counts_after"] != expected:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "The native ring cut produced unexpected topology; inspect or recover the edit session.",
                          {"object": obj.name, "execution_started": True, "verification_required": True,
                           "expected_counts_after": expected, "observed_counts_after": result["mesh_counts_after"]})
    result.update({"source_ring_edges": len(ring.edges), "crossed_quad_count": len(ring.faces),
                   "closed": ring.closed, "cuts": cuts, "spacing": "EVEN_NO_SLIDE", "expected_counts_after": expected})
    return result


def _closed_loops(edges: list[Any]) -> list[list[Any]]:
    adjacency = defaultdict(list)
    for edge in edges:
        if not (edge.is_boundary or edge.is_wire):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Bridge input must be boundary or wire edges, not interior edges.")
        for vertex in edge.verts:
            adjacency[vertex].append(edge)
    if any(len(incident) != 2 for incident in adjacency.values()):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Select two complete disjoint closed loops without branches.")
    remaining = set(edges)
    loops = []
    for seed in edges:
        if seed not in remaining:
            continue
        loop, pending = [], [seed]
        while pending:
            edge = pending.pop()
            if edge not in remaining:
                continue
            remaining.remove(edge)
            loop.append(edge)
            if len(loop) > MAX_LOOP_EDGES:
                raise invalid_argument("A bridge loop exceeds 1,024 edges.")
            for vertex in edge.verts:
                pending.extend(adjacency[vertex])
        loops.append(loop)
        if len(loops) > 2:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Bridge exactly two closed loops per operation.")
    if len(loops) != 2 or any(len(loop) < 3 for loop in loops):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Bridge exactly two closed loops of at least three edges.")
    return loops


def bridge_loops(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "selection_id", "twist_offset", "material_index"})
    if not isinstance(params.get("selection_id"), str) or not params["selection_id"]:
        raise invalid_argument("Bridging requires a fresh edge selection_id for both loops.")
    twist = int_param(params, "twist_offset", 0, minimum=-MAX_LOOP_EDGES, maximum=MAX_LOOP_EDGES)
    material_index = int_param(params, "material_index", 0, minimum=0, maximum=255)
    obj, bm, edges = _scope(params, "EDGE")
    if material_index >= max(1, len(obj.data.materials)):
        raise invalid_argument("The material index must address an existing slot (or zero for no slots).")
    loops = _closed_loops(edges)
    _adjacent_faces(edges)
    if abs(twist) >= min(len(loop) for loop in loops):
        raise invalid_argument("The twist offset magnitude must be smaller than both loop sizes.")
    before = _mesh_counts(bm)
    sizes = [len(loop) for loop in loops]
    if sizes[0] != sizes[1] and twist:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Explicit twist correspondence for unequal loops is not implemented; native Blender ignores that option.")
    expected_faces = sizes[0] if sizes[0] == sizes[1] else sum(sizes)
    if sum(before.values()) + expected_faces * 2 > MAX_MESH_ELEMENTS:
        raise invalid_argument("The bridge exceeds the output-element budget.")
    _check_cancelled(context)
    output = bmesh.ops.bridge_loops(bm, edges=edges, use_pairs=False, use_cyclic=False,
                                   use_merge=False, twist_offset=twist)
    faces = list(output["faces"])
    if (len(faces) != expected_faces or len(bm.verts) != before["vertices"]
            or len(bm.edges) != before["edges"] + expected_faces):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Native bridging produced unexpected topology; inspect or recover the edit session.",
                          {"object": obj.name, "execution_started": True, "verification_required": True,
                           "expected_faces": expected_faces, "created_faces": len(faces)})
    invalid_faces = sum(not math.isfinite(face.calc_area()) or face.calc_area() <= 0 for face in faces)
    if invalid_faces:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "The bridge created zero/non-finite-area faces; inspect or recover this edit session.",
                          {"object": obj.name, "invalid_created_faces": invalid_faces,
                           "execution_started": True, "verification_required": True})
    for face in faces:
        face.material_index = material_index
        for loop in face.loops:
            for layer in bm.loops.layers.uv.values():
                loop[layer].uv = (0, 0)
                loop[layer].pin_uv = False
    bm.normal_update()
    result = _result(obj, bm, before, changed=True)
    result.update({"loop_sizes": sizes, "created_faces": len(faces), "twist_offset": twist,
                   "invalid_created_faces": invalid_faces,
                   "face_policy": "QUADS" if sizes[0] == sizes[1] else "NATIVE_TRIANGULATED_STRIP",
                   "material_index": material_index, "new_face_uv_policy": "ZERO_INITIALIZED_UNPINNED",
                   "warnings": ["Inspect correspondence, normals, crossings and triangulation visually; new faces need UV authoring. No vertex merge or automatic twist optimization."]})
    return result


def register_tools(registry: ToolRegistry) -> None:
    registry.register("mesh.edge_ring_inspect", edge_ring_inspect, permissions=(Permission.INSPECT_SCENE,),
                      toolset="mesh", description="Preview paginated measured edges and expected topology of one connected quad ring.")
    for name, handler, description in (
        ("mesh.loop_cut", loop_cut, "Insert evenly spaced cuts across the entire inspected connected quad ring, including unselected faces."),
        ("mesh.bridge_loops", bridge_loops, "Bridge two referenced closed boundary/wire loops without merging vertices; unequal loops produce triangles."),
    ):
        registry.register(name, handler, permissions=(Permission.EDIT_MESH,), toolset="mesh", modifies=True, description=description)
