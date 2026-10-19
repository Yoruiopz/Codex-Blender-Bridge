"""Read-only UV quality evidence using Blender's actual base-mesh tessellation."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, int_param, reject_unknown_params, require_blender
from ..uv_geometry import UV_EPSILON, WORLD_EPSILON, UVTriangle, overlap_analysis, triangle_metrics
from .mesh import _id_name
from .uv import _mesh_object, _uses_edit_data

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

MAX_ELEMENTS = 200_000
MAX_GLOBAL_CORNERS = 200_000
MAX_SCOPED_FACES = 10_000
MAX_SCOPED_CORNERS = 40_000


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _check_positions(context: ToolContext, vertices: Any) -> None:
    invalid = []
    count = 0
    for index, vertex in enumerate(vertices):
        if any(not math.isfinite(float(value)) or abs(float(value)) > 1e12 for value in vertex.co):
            count += 1
            if len(invalid) < 64:
                invalid.append(index)
        if index % 256 == 0:
            _check(context)
    if count:
        raise invalid_argument("Unsafe local positions prevent native tessellation; inspect/repair base geometry first.",
                               invalid_vertex_count=count, vertex_indices=invalid,
                               vertex_indices_truncated=count > len(invalid), maximum_coordinate_magnitude=1e12)


def _collect(context: ToolContext, params: Mapping[str, Any], maximum: int) -> tuple[dict[str, Any], list[UVTriangle]]:
    _id_name(params.get("object_name"), "object_name")
    layer_name = _id_name(params.get("uv_layer"), "uv_layer")
    selected_only = bool_param(params, "selected_only", False)
    reference_id = params.get("selection_id")
    if reference_id is not None and (not isinstance(reference_id, str) or not reference_id):
        raise invalid_argument("'selection_id' must be a non-empty string.")
    requested = params.get("face_indices")
    if requested is not None:
        if not isinstance(requested, list) or not 1 <= len(requested) <= MAX_SCOPED_FACES:
            raise invalid_argument("'face_indices' must contain 1-10,000 unique integer indices.")
        requested = [int_param({"face_index": item}, "face_index", -1, minimum=0, maximum=MAX_ELEMENTS) for item in requested]
        if len(requested) != len(set(requested)):
            raise invalid_argument("'face_indices' must be unique.")
    obj = _mesh_object(params)
    bpy = require_blender()
    if obj.name not in bpy.context.view_layer.objects or bpy.context.view_layer.objects[obj.name] != obj:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "World-unit UV analysis requires the mesh in the current view layer.")
    if obj.mode not in {"OBJECT", "EDIT"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV analysis supports Object/Edit Mode base meshes, not evaluated sculpt/paint states.")
    if reference_id is not None and obj.mode != "EDIT":
        raise BridgeError(ErrorCode.INVALID_MODE, "A face selection reference requires Edit Mode.")
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    owns = not _uses_edit_data(obj)
    if owns and (len(obj.data.vertices) + len(obj.data.edges) + len(obj.data.polygons) > MAX_ELEMENTS
                 or len(obj.data.loops) > MAX_GLOBAL_CORNERS):
        raise invalid_argument("Base mesh exceeds the global analysis budget.")
    if owns:
        _check_positions(context, obj.data.vertices)
    bm = bmesh.new() if owns else bmesh.from_edit_mesh(obj.data)
    try:
        if owns:
            bm.from_mesh(obj.data)
            if len(bm.faces) != len(obj.data.polygons):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Temporary mesh conversion did not preserve face indexing.")
        if len(bm.verts) + len(bm.edges) + len(bm.faces) > MAX_ELEMENTS:
            raise invalid_argument("Base mesh exceeds the global analysis budget.")
        _check_positions(context, bm.verts)
        # Refresh derived transforms only after validating native geometry inputs, in both modes.
        bpy.context.view_layer.update()
        _check_positions(context, bm.verts)
        corners = 0
        for index, face in enumerate(bm.faces):
            corners += len(face.loops)
            if corners > MAX_GLOBAL_CORNERS:
                raise invalid_argument("Base mesh exceeds the global corner budget.")
            if index % 64 == 0:
                _check(context)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        bm.verts.index_update()
        layer = bm.loops.layers.uv.get(layer_name)
        if layer is None:
            raise invalid_argument("The named UV layer does not exist.")
        reference = validate_selection_reference(reference_id, obj, bm) if reference_id else None
        faces = [bm.faces[i] for i in reference["faces"]] if reference else [face for face in bm.faces if not selected_only or face.select]
        if requested is not None:
            available = {face.index: face for face in faces}
            if any(index not in available for index in requested):
                raise BridgeError(ErrorCode.INVALID_SELECTION, "A requested face is absent or outside selected/referenced scope.")
            faces = [available[index] for index in requested]
        if not faces:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "No faces were found in the analysis scope.")
        if len(faces) > MAX_SCOPED_FACES or sum(len(face.loops) for face in faces) > MAX_SCOPED_CORNERS:
            raise invalid_argument("Narrow analysis to at most 10,000 faces / 40,000 corners.")
        indices = {face.index for face in faces}
        _check(context)
        loops = [triangle for triangle in bm.calc_loop_triangles() if triangle[0].face.index in indices]
        counts = Counter(triangle[0].face.index for triangle in loops)
        missing = [face.index for face in faces if counts[face.index] != len(face.loops) - 2]
        metadata = {"object": obj.name, "uv_layer": layer_name, "mode": obj.mode, "scoped_face_count": len(faces),
                    "mesh_data_state": "OBJECT_MESH_COPY" if owns else "LIVE_EDIT_BMESH",
                    "requested_triangle_count": len(loops), "tessellation_incomplete_faces": len(missing),
                    "tessellation_incomplete_examples": missing[:64], "tessellation_examples_truncated": len(missing) > 64,
                    "triangle_budget_exceeded": len(loops) > maximum}
        if len(loops) > maximum:
            return metadata, []
        matrix = [tuple(row) for row in obj.matrix_world]
        world = {}
        triangles = []
        for index, triangle in enumerate(loops):
            positions, uvs = [], []
            for loop in triangle:
                key = loop.vert.index
                if key not in world:
                    co = tuple(float(value) for value in loop.vert.co)
                    world[key] = tuple(sum(matrix[row][column] * co[column] for column in range(3)) + matrix[row][3] for row in range(3))
                positions.append(world[key])
                uvs.append(tuple(float(value) for value in loop[layer].uv))
            triangles.append(UVTriangle(index, triangle[0].face.index, tuple(uvs), tuple(positions)))
            if index % 64 == 0:
                _check(context)
        return metadata, triangles
    finally:
        if owns:
            bm.free()


def analyze(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "selected_only", "selection_id", "face_indices", "texture_resolution",
                                   "max_triangles", "max_pair_tests", "max_reports", "anisotropy_warning", "density_target", "density_tolerance"})
    resolution = params.get("texture_resolution", [1024, 1024])
    if not isinstance(resolution, list) or len(resolution) != 2:
        raise invalid_argument("'texture_resolution' must contain two integer pixel dimensions.")
    resolution = tuple(int_param({"size": value}, "size", 0, minimum=1, maximum=65_536) for value in resolution)
    maximum = int_param(params, "max_triangles", 8192, minimum=1, maximum=20_000)
    pairs = int_param(params, "max_pair_tests", 200_000, minimum=1, maximum=1_000_000)
    reports = int_param(params, "max_reports", 64, minimum=1, maximum=256)
    anisotropy_warning = float_param(params, "anisotropy_warning", 4., minimum=1., maximum=1e6)
    target = None if params.get("density_target") is None else float_param(params, "density_target", 1., minimum=1e-12, maximum=1e12)
    tolerance = float_param(params, "density_tolerance", .2, minimum=0., maximum=1.)
    metadata, triangles = _collect(context, params, maximum)
    result = {**metadata, "texture_resolution": list(resolution),
              "resolution_source": "CALLER_DECLARED" if "texture_resolution" in params else "DEFAULT_1024_ASSUMPTION",
              "geometry_source": "BASE_MESH_WITH_WORLD_TRANSFORM", "density_unit": "pixels_per_world_coordinate_unit_not_meters",
              "tessellation_source": "BMESH_CALC_LOOP_TRIANGLES",
              "scene_changed": False, "dependency_graph_refreshed": True,
              "uv_area_epsilon": UV_EPSILON, "world_area_epsilon": WORLD_EPSILON}
    if metadata["triangle_budget_exceeded"]:
        return {**result, "analysis_complete": False, "analysis_truncated": True, "metrics": None,
                "overlap": {"complete": False, "reason": "TRIANGLE_BUDGET"},
                "verification": {"status": "incomplete", "user_goal_verified": False,
                                 "warnings": ["Triangle budget exceeded; raise it within limits or narrow face scope."]}}
    faces = {}
    invalid = near_uv = near_world = mirrored = 0
    reasons: Counter[str] = Counter()
    for index, triangle in enumerate(triangles):
        face = faces.setdefault(triangle.face, {"face_index": triangle.face, "triangles": 0, "invalid_triangles": 0,
            "world_area": 0., "summed_triangle_uv_area": 0., "pixel_area": 0., "mirrored_triangles": 0,
            "positive_triangles": 0, "near_zero_uv_triangles": 0, "near_zero_world_triangles": 0, "max_anisotropy": None})
        face.setdefault("min_directional_density", None)
        face.setdefault("max_directional_density", None)
        face.setdefault("worst_triangle_index", None)
        face.setdefault("triangle_density_min", None)
        face.setdefault("triangle_density_max", None)
        face["triangles"] += 1
        metrics = triangle_metrics(triangle, resolution)
        if not metrics["valid"]:
            invalid += 1
            face["invalid_triangles"] += 1
            reasons[metrics["reason"]] += 1
            continue
        face["world_area"] += metrics["world_area"]
        face["summed_triangle_uv_area"] += metrics["uv_area"]
        face["pixel_area"] += metrics["pixel_area"]
        face["mirrored_triangles"] += int(metrics["mirrored"])
        face["positive_triangles"] += int(metrics["uv_signed_area"] > UV_EPSILON)
        face["near_zero_uv_triangles"] += int(metrics["near_zero_uv"])
        face["near_zero_world_triangles"] += int(metrics["near_zero_world"])
        near_uv += int(metrics["near_zero_uv"])
        near_world += int(metrics["near_zero_world"])
        mirrored += int(metrics["mirrored"])
        if metrics["anisotropy"] is not None:
            if face["max_anisotropy"] is None or metrics["anisotropy"] > face["max_anisotropy"]:
                face["max_anisotropy"] = metrics["anisotropy"]
                face["worst_triangle_index"] = triangle.index
            face["min_directional_density"] = min(face["min_directional_density"] or metrics["sigma_min"], metrics["sigma_min"])
            face["max_directional_density"] = max(face["max_directional_density"] or 0., metrics["sigma_max"])
        if metrics["density"] is not None:
            face["triangle_density_min"] = metrics["density"] if face["triangle_density_min"] is None else min(face["triangle_density_min"], metrics["density"])
            face["triangle_density_max"] = max(face["triangle_density_max"] or 0., metrics["density"])
        if index % 64 == 0:
            _check(context)
    overlap = overlap_analysis(triangles, max_pair_tests=pairs, max_reports=reports, check_cancelled=context.check_cancelled)
    overlap_counts = overlap.pop("_face_overlap_counts")
    for face in faces.values():
        face["folded"] = bool(face["mirrored_triangles"] and face["positive_triangles"])
        face["density"] = math.sqrt(face["pixel_area"] / face["world_area"]) if face["world_area"] > WORLD_EPSILON and not face["invalid_triangles"] else None
        face["overlap_triangle_pairs"] = overlap_counts.get(face["face_index"], 0)
        face["outside_density_target"] = bool(target is not None and face["triangle_density_min"] is not None and
            (abs(face["triangle_density_min"] - target) > target * tolerance or abs(face["triangle_density_max"] - target) > target * tolerance))
    rows = sorted(faces.values(), key=lambda face: (-int(bool(face["invalid_triangles"] or face["near_zero_world_triangles"] or face["near_zero_uv_triangles"])),
        -face["overlap_triangle_pairs"], -int(face["folded"]), -int(face["outside_density_target"]), -(face["max_anisotropy"] or 0), face["face_index"]))
    density_minima = [face["triangle_density_min"] for face in rows if face["triangle_density_min"] is not None]
    density_maxima = [face["triangle_density_max"] for face in rows if face["triangle_density_max"] is not None]
    anisotropies = [face["max_anisotropy"] for face in rows if face["max_anisotropy"] is not None]
    density_min, density_max = (min(density_minima), max(density_maxima)) if density_minima else (None, None)
    warnings = []
    for count, message in ((invalid, "Invalid/out-of-range triangle data prevents complete metrics."), (near_uv, "Near-zero UV-area triangles; tiny valid mappings can fall below the cutoff."),
                           (near_world, "Near-zero world-area triangles; directional metrics are undefined at this cutoff."),
                           (mirrored, "Mirrored UV triangles; mirroring may be intentional."),
                           (overlap["positive_triangle_pairs"], "Positive-area UV intersections found; stacking may be intentional."),
                           (sum(face["folded"] for face in rows), "Some faces contain mixed UV winding/folds."),
                           (sum((face["max_anisotropy"] or 0) > anisotropy_warning for face in rows), "Pixel-direction anisotropy exceeds the declared warning threshold."),
                           (sum(face["outside_density_target"] for face in rows), "Some triangle densities are outside the declared target tolerance.")):
        if count:
            warnings.append(message)
    complete = not invalid and not metadata["tessellation_incomplete_faces"] and overlap["complete"]
    if not complete:
        warnings.append("Analysis is incomplete; inspect reasons and narrow scope or increase budgets. Do not infer a clean layout.")
    result.update(analysis_complete=complete, analysis_truncated=overlap["pair_budget_exhausted"], overlap=overlap,
        metrics={"invalid_triangles": invalid, "invalid_reasons": dict(reasons), "near_zero_uv_triangles": near_uv,
                 "near_zero_world_triangles": near_world, "mirrored_triangles": mirrored, "folded_faces": sum(face["folded"] for face in rows),
                 "max_pixel_anisotropy": max(anisotropies) if anisotropies else None,
                 "density_min": density_min, "density_max": density_max,
                 "density_variation_ratio": density_max / density_min if density_min else None,
                 "density_target": target, "density_relative_tolerance": tolerance, "anisotropy_warning": anisotropy_warning},
        face_reports=rows[:reports], face_reports_truncated=len(rows) > reports,
        verification={"status": "incomplete" if not complete else ("needs_review" if warnings else "numeric_checks_passed"),
                      "user_goal_verified": False, "warnings": warnings},
        index_validity="Base face and tessellation indices are session/state-local; reinspect after topology, mode, scene or undo changes.",
        limitations="Scoped base-mesh numeric checks, not evaluated/modifier geometry, an artistic verdict or Blender-overlay equivalence. Density assumes the reported resolution and world units, not image assets/meters. Face density uses summed triangle areas, not unique texture coverage. Sub-threshold overlap may be ignored; excluded faces/objects are not checked.")
    return result


def register_tools(registry: ToolRegistry) -> None:
    registry.register("uv.analyze", analyze, permissions=(Permission.INSPECT_SCENE,), toolset="uv",
                      description="Measure bounded triangulated UV overlap, winding, pixel anisotropy and world-unit texel density; report incomplete coverage honestly.")
