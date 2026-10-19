"""Bounded read-only base-mesh topology, winding and geometric-contact evidence."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..mesh_geometry import MeshTriangle, intersection_analysis
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import float_param, get_object, int_param, reject_unknown_params, require_blender
from ._mesh_safety import uses_edit_data
from .mesh import _id_name

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

MAX_ELEMENTS = 200_000
MAX_CORNERS = 200_000


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _positions(context: ToolContext, vertices: Any) -> None:
    invalid, count = [], 0
    for index, vertex in enumerate(vertices):
        if any(not math.isfinite(float(v)) or abs(float(v)) > 1e12 for v in vertex.co):
            count += 1
            if len(invalid) < 64:
                invalid.append(index)
        if index % 256 == 0:
            _check(context)
    if count:
        raise invalid_argument("Unsafe local coordinates prevent native mesh analysis.", invalid_vertex_count=count,
                               vertex_indices=invalid, vertex_indices_truncated=count > len(invalid))


def _collect(context: ToolContext, name: str, epsilon: float, maximum: int, reports: int) -> tuple[dict, list[MeshTriangle]]:
    obj = get_object(name, allow_active=False)
    if obj.type != "MESH":
        raise invalid_argument("Mesh analysis requires an explicitly named mesh object.", object_type=obj.type)
    bpy = require_blender()
    if obj.name not in bpy.context.view_layer.objects or bpy.context.view_layer.objects[obj.name] != obj:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "World-space mesh analysis requires the current view layer.")
    if obj.mode not in {"OBJECT", "EDIT"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Mesh analysis covers Object/Edit Mode base geometry only.")
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    owns = not uses_edit_data(obj)
    if owns:
        if len(obj.data.vertices) + len(obj.data.edges) + len(obj.data.polygons) > MAX_ELEMENTS or len(obj.data.loops) > MAX_CORNERS:
            raise invalid_argument("Mesh exceeds the global analysis budget.")
        _positions(context, obj.data.vertices)
    bm = bmesh.new() if owns else bmesh.from_edit_mesh(obj.data)
    try:
        if owns:
            bm.from_mesh(obj.data)
            if len(bm.faces) != len(obj.data.polygons):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Temporary mesh conversion did not preserve face indexing.")
        if len(bm.verts) + len(bm.edges) + len(bm.faces) > MAX_ELEMENTS:
            raise invalid_argument("Mesh exceeds the global analysis budget.")
        _positions(context, bm.verts)
        bpy.context.view_layer.update()
        _positions(context, bm.verts)
        for sequence in (bm.verts, bm.edges, bm.faces):
            sequence.ensure_lookup_table()
            sequence.index_update()
        matrix = [tuple(float(v) for v in row) for row in obj.matrix_world]
        world = []
        for index, vertex in enumerate(bm.verts):
            p = tuple(sum(matrix[r][c] * float(vertex.co[c]) for c in range(3)) + matrix[r][3] for r in range(3))
            if any(not math.isfinite(v) or abs(v) > 1e12 for v in p):
                raise invalid_argument("Unsafe world coordinates prevent mesh analysis.", vertex_index=index)
            world.append(p)
            if index % 256 == 0:
                _check(context)
        counts: Counter[str] = Counter({key: 0 for key in (
            "loose_vertices", "non_manifold_vertices", "non_manifold_edges", "wire_edges", "boundary_edges",
            "over_connected_edges", "inconsistent_orientation_edges", "near_zero_edges", "ngons")})
        examples: dict[str, list[int]] = {}

        def issue(key: str, index: int) -> None:
            counts[key] += 1
            rows = examples.setdefault(key, [])
            if len(rows) < reports:
                rows.append(index)

        for vertex in bm.verts:
            if not vertex.link_edges:
                issue("loose_vertices", vertex.index)
            elif not vertex.is_manifold:
                issue("non_manifold_vertices", vertex.index)
            if vertex.index % 256 == 0:
                _check(context)
        for edge in bm.edges:
            n = len(edge.link_faces)
            if n != 2:
                issue("non_manifold_edges", edge.index)
            if n == 0:
                issue("wire_edges", edge.index)
            elif n == 1:
                issue("boundary_edges", edge.index)
            elif n > 2:
                issue("over_connected_edges", edge.index)
            if n == 2 and not edge.is_contiguous:
                issue("inconsistent_orientation_edges", edge.index)
            if math.dist(world[edge.verts[0].index], world[edge.verts[1].index]) <= epsilon:
                issue("near_zero_edges", edge.index)
            if edge.index % 256 == 0:
                _check(context)
        corners = 0
        for face in bm.faces:
            corners += len(face.loops)
            if corners > MAX_CORNERS:
                raise invalid_argument("Mesh exceeds the global corner budget.")
            if len(face.loops) > 4:
                counts["ngons"] += 1
            if face.index % 64 == 0:
                _check(context)
        loops = bm.calc_loop_triangles()
        face_counts = Counter(t[0].face.index for t in loops)
        missing = [f.index for f in bm.faces if face_counts[f.index] != len(f.loops) - 2]
        result = {"object": obj.name, "mode": obj.mode, "geometry_source": "WHOLE_BASE_MESH_WITH_WORLD_TRANSFORM",
                  "mesh_data_state": "OBJECT_MESH_COPY" if owns else "LIVE_EDIT_BMESH", "scene_changed": False,
                  "dependency_graph_refreshed": True,
                  "counts": {"vertices": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces), "corners": corners},
                  "topology": {"counts": dict(counts), "examples": examples,
                               "examples_truncated": any(counts[k] > len(v) for k, v in examples.items())},
                  "tessellation": {"source": "BMESH_CALC_LOOP_TRIANGLES", "triangles": len(loops),
                                   "incomplete_face_count": len(missing), "incomplete_face_examples": missing[:reports],
                                   "examples_truncated": len(missing) > reports, "triangle_budget_exceeded": len(loops) > maximum}}
        _check(context)
        if len(loops) > maximum:
            return result, []
        triangles = []
        for index, t in enumerate(loops):
            ids = tuple(loop.vert.index for loop in t)
            triangles.append(MeshTriangle(index, t[0].face.index, ids, tuple(world[i] for i in ids)))
            if index % 64 == 0:
                _check(context)
        return result, triangles
    finally:
        if owns:
            bm.free()


def analyze(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "distance_tolerance", "max_triangles", "max_pair_tests", "max_reports"})
    name = _id_name(params.get("object_name"), "object_name")
    epsilon = float_param(params, "distance_tolerance", 1e-6, minimum=1e-12, maximum=1e-2)
    maximum = int_param(params, "max_triangles", 8192, minimum=1, maximum=20_000)
    pairs = int_param(params, "max_pair_tests", 250_000, minimum=1, maximum=1_000_000)
    reports = int_param(params, "max_reports", 64, minimum=1, maximum=256)
    result, triangles = _collect(context, name, epsilon, maximum, reports)
    if result["tessellation"]["triangle_budget_exceeded"]:
        contacts = {"complete": False, "reason": "TRIANGLE_BUDGET", "triangle_pairs": {}}
    else:
        contacts = intersection_analysis(triangles, epsilon=epsilon, max_pair_tests=pairs, max_reports=reports,
                                         check_cancelled=lambda: _check(context))
    complete = contacts["complete"] and not result["tessellation"]["incomplete_face_count"]
    warnings = []
    if not result["counts"]["faces"]:
        complete = False
        warnings.append("No surface faces exist in this mesh.")
    if any(v for k, v in result["topology"]["counts"].items() if k != "ngons"):
        warnings.append("Topology/orientation findings require review; open boundaries and wire geometry may be intentional.")
    if sum(contacts["triangle_pairs"].values()):
        warnings.append("Geometric contact candidates require review; boundary contacts are not necessarily crossings.")
    if not complete:
        warnings.append("Analysis is incomplete; inspect skipped/precision/budget/tessellation reasons. Do not infer a clean mesh.")
    result.update(intersections=contacts, analysis_complete=complete,
                  analysis_truncated=bool(result["tessellation"]["triangle_budget_exceeded"] or contacts.get("pair_budget_exhausted")),
                  distance_tolerance=epsilon, tolerance_unit="world_coordinate_units_not_meters",
                  verification={"status": "incomplete" if not complete else ("needs_review" if warnings else "numeric_checks_passed"),
                                "warnings": warnings, "user_goal_verified": False},
                  limitations="Whole named base mesh only; other objects, evaluated modifiers, custom/split shading normals, outward orientation, solid containment and point-only contacts are not checked. Winding checks adjacent manifold face consistency only. Indices are state-local. Native graph refresh may run user handlers. No artistic, printability or whole-scene certificate.")
    return result


def register_tools(registry: ToolRegistry) -> None:
    registry.register("mesh.analyze", analyze, toolset="mesh", permissions=(Permission.INSPECT_SCENE,),
                      description="Inspect bounded base-mesh topology, adjacent winding and triangle crossing/contact candidates; report incomplete coverage.")
