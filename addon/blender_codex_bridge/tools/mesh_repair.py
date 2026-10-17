"""Bounded repair primitives for one explicitly named Edit Mode mesh."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import float_param, int_param, reject_unknown_params
from ._mesh_safety import require_local_single_user_mesh
from .interaction import MAX_MESH_ELEMENTS, _active_edit_mesh
from .mesh import _finish, _id_name, _mesh_counts, _operation_elements, _selection_counts

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

MAX_SELECTED = 20_000
MAX_FACE_CORNERS = 100_000
MAX_HOLE_SIDES = 1_024


def _scope(params: Mapping[str, Any], label: str) -> tuple[Any, Any, list[Any]]:
    name = _id_name(params.get("object_name"), "object_name")
    selection_id = params.get("selection_id")
    if selection_id is not None and (not isinstance(selection_id, str) or not selection_id):
        raise invalid_argument("'selection_id' must be a non-empty string.")
    _bpy, obj, bm, sequences = _active_edit_mesh(name)
    require_local_single_user_mesh(obj)
    if getattr(obj.data, "shape_keys", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Repair primitives do not yet support shape-key meshes.")
    reference = validate_selection_reference(selection_id, obj, bm) if selection_id else None
    elements = _operation_elements(sequences[label], {"VERT": "vertices", "EDGE": "edges"}[label], reference)
    if (not elements or len(elements) > MAX_SELECTED or any(element.hide for element in elements)
            or (label == "EDGE" and any(vertex.hide for edge in elements for vertex in edge.verts))):
        raise BridgeError(
            ErrorCode.INVALID_SELECTION, "Select 1-20,000 non-hidden components for mesh repair.",
            {"object": name, "element_type": label, "maximum_elements": MAX_SELECTED},
        )
    return obj, bm, elements


def _adjacent_faces(elements: list[Any]) -> set[Any]:
    faces: set[Any] = set()
    corners = 0
    for element in elements:
        for face in element.link_faces:
            if face in faces:
                continue
            faces.add(face)
            corners += len(face.verts)
            if corners > MAX_FACE_CORNERS:
                raise invalid_argument("Affected face corners exceed the repair budget.", maximum_corners=MAX_FACE_CORNERS)
            if (face.hide or any(vertex.hide for vertex in face.verts)
                    or any(edge.hide for edge in face.edges)):
                raise BridgeError(ErrorCode.INVALID_SELECTION, "Repair would affect hidden geometry; reveal it explicitly first.")
    return faces


def _check_cancelled(context: ToolContext) -> None:
    if context.check_cancelled is not None:
        context.check_cancelled()


def _result(obj: Any, bm: Any, before: Mapping[str, int], *, changed: bool) -> dict[str, Any]:
    result = _finish(obj, bm, destructive=True, before=before) if changed else {
        "object": obj.name, "mesh_counts_before": dict(before),
        "mesh_counts_after": _mesh_counts(bm), "selection_after": _selection_counts(bm),
    }
    result.update({
        "affected_objects": [obj.name], "changed": changed, "coordinate_space": "LOCAL",
        "selection_reference_invalidated": changed,
        "verification_required": True,
    })
    return result


def subdivide_selected(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "selection_id", "cuts"})
    cuts = int_param(params, "cuts", 1, minimum=1, maximum=32)
    obj, bm, edges = _scope(params, "EDGE")
    faces = _adjacent_faces(edges)
    before = _mesh_counts(bm)
    # Deliberately conservative: account for grids AND adjacent n-gon replacement.
    projected = sum(before.values()) + 4 * len(edges) * cuts + sum(
        len(face.verts) * (cuts + 1) ** 2 for face in faces
    )
    if projected > MAX_MESH_ELEMENTS:
        raise invalid_argument(
            "Subdivision exceeds the conservative output-element budget; narrow the selection or cuts.",
            projected_element_bound=projected, maximum_elements=MAX_MESH_ELEMENTS,
        )
    _check_cancelled(context)
    bmesh.ops.subdivide_edges(
        bm, edges=edges, cuts=cuts, smooth=0.0, fractal=0.0,
        use_grid_fill=True, use_only_quads=False, quad_corner_type="STRAIGHT_CUT",
    )
    result = _result(obj, bm, before, changed=True)
    result.update({"source_edges": len(edges), "cuts": cuts, "smoothing": 0.0,
                   "projected_element_bound": projected})
    return result


def merge_by_distance(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "selection_id", "distance"})
    distance = float_param(params, "distance", 0.0001, minimum=1e-12, maximum=1e6)
    obj, bm, vertices = _scope(params, "VERT")
    _adjacent_faces(vertices)
    if any(edge.hide or any(vertex.hide for vertex in edge.verts)
           for vertex in vertices for edge in vertex.link_edges):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Merge would affect hidden incident geometry.")
    before = _mesh_counts(bm)
    _check_cancelled(context)
    targets = bmesh.ops.find_doubles(bm, verts=vertices, dist=distance)["targetmap"]
    selected = set(vertices)
    if any(source not in selected or target not in selected for source, target in targets.items()):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Merge target escaped the selected vertex scope.")
    _check_cancelled(context)
    if targets:
        bmesh.ops.weld_verts(bm, targetmap=targets)
    result = _result(obj, bm, before, changed=bool(targets))
    result.update({
        "source_vertices": len(vertices), "merged_vertices": before["vertices"] - len(bm.verts),
        "distance": distance,
        "warnings": ["Welding may collapse incident faces/edges and reconcile corner UVs or vertex attributes; reinspect affected data."]
        if targets else [],
    })
    return result


def _hole_loops(edges: list[Any]) -> list[list[Any]]:
    adjacency: dict[Any, list[Any]] = defaultdict(list)
    for edge in edges:
        if not edge.is_boundary:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Hole filling accepts boundary edges with exactly one incident face, not wire/interior edges.")
        for vertex in edge.verts:
            if vertex.hide:
                raise BridgeError(ErrorCode.INVALID_SELECTION, "Hole boundary contains hidden vertices.")
            adjacency[vertex].append(edge)
    if any(len(incident) != 2 for incident in adjacency.values()):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Select complete, disjoint closed boundary loops without branches.")
    remaining = set(edges)
    loops = []
    for seed in edges:
        if seed not in remaining:
            continue
        pending = [seed]
        loop = []
        while pending:
            edge = pending.pop()
            if edge not in remaining:
                continue
            remaining.remove(edge)
            loop.append(edge)
            if len(loop) > MAX_HOLE_SIDES:
                raise invalid_argument("A hole exceeds the bounded n-gon size.", maximum_sides=MAX_HOLE_SIDES)
            for vertex in edge.verts:
                pending.extend(adjacency[vertex])
        if len(loop) < 3:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "A hole requires at least three boundary edges.")
        loops.append(loop)
    return loops


def fill_holes(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "selection_id", "material_index"})
    material_index = int_param(params, "material_index", 0, minimum=0, maximum=255)
    obj, bm, edges = _scope(params, "EDGE")
    if material_index >= max(1, len(obj.data.materials)):
        raise invalid_argument("'material_index' must address an existing material slot (or zero for no slots).")
    _adjacent_faces(edges)
    loops = _hole_loops(edges)
    before = _mesh_counts(bm)
    if sum(before.values()) + len(loops) > MAX_MESH_ELEMENTS:
        raise invalid_argument("Filled mesh would exceed the inspection element budget.")
    _check_cancelled(context)
    created = list(bmesh.ops.holes_fill(bm, edges=edges, sides=MAX_HOLE_SIDES)["faces"])
    if len(created) != len(loops):
        raise BridgeError(
            ErrorCode.OPERATION_FAILED, "Not every selected loop produced a cap; inspect or recover this edit session.",
            {"execution_started": True, "verification_required": True,
             "expected_faces": len(loops), "created_faces": len(created)},
        )
    for face in created:
        face.material_index = material_index
        for loop in face.loops:
            for layer in bm.loops.layers.uv.values():
                loop[layer].uv = (0.0, 0.0)
                loop[layer].pin_uv = False
    result = _result(obj, bm, before, changed=True)
    result.update({
        "boundary_loops": len(loops), "created_faces": len(created),
        "material_index": material_index, "new_face_uv_policy": "ZERO_INITIALIZED_UNPINNED",
        "warnings": ["Caps are independent n-gons, not a grid/bridge. Unwrap new faces; inspect planarity and triangulation visually."],
    })
    return result


def register_tools(registry: ToolRegistry) -> None:
    for name, handler, description in (
        ("mesh.subdivide_selected", subdivide_selected, "Subdivide selected edges without smoothing, with a conservative growth budget."),
        ("mesh.merge_by_distance", merge_by_distance, "Weld only selected vertices within a local-space distance."),
        ("mesh.fill_holes", fill_holes, "Cap complete disjoint boundary loops with bounded n-gons and zero-initialized new UVs."),
    ):
        registry.register(name, handler, permissions=(Permission.EDIT_MESH,), toolset="mesh",
                          modifies=True, description=description)
