"""Bounded UV inspection and selection-safe unwrap operations."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, get_object, int_param, require_blender
from ._mesh_safety import require_local_single_user_mesh
from ._rna import bounded_name

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

_MAX_UV_LAYERS = 32
_MAX_FACES = 50_000
_MAX_LOOPS = 200_000
_UV_EPSILON = 1e-6


def _mesh_object(params: Mapping[str, Any]) -> Any:
    obj = get_object(params.get("object_name"), allow_active=False)
    if obj.type != "MESH":
        raise BridgeError(
            ErrorCode.INVALID_ARGUMENT,
            f"Object '{obj.name}' is not a mesh.",
            {"object": obj.name, "object_type": obj.type},
        )
    return obj


def _optional_layer_name(params: Mapping[str, Any]) -> str | None:
    value = params.get("uv_layer")
    return None if value is None else bounded_name(value, "uv_layer", maximum=64)


def _layer_summaries(obj: Any) -> tuple[list[dict[str, Any]], bool]:
    layers = list(obj.data.uv_layers)
    active = obj.data.uv_layers.active
    summaries = [
        {
            "name": layer.name,
            "active": layer == active,
            "active_render": bool(getattr(layer, "active_render", False)),
            "active_clone": bool(getattr(layer, "active_clone", False)),
        }
        for layer in layers[:_MAX_UV_LAYERS]
    ]
    return summaries, len(layers) > len(summaries)


def _uv_close(first: Sequence[float], second: Sequence[float]) -> bool:
    return abs(float(first[0]) - float(second[0])) <= _UV_EPSILON and abs(
        float(first[1]) - float(second[1])
    ) <= _UV_EPSILON


def _islands(
    faces: Mapping[int, list[tuple[int, bool, dict[int, tuple[float, float]]]]],
) -> list[list[int]]:
    adjacency: dict[int, set[int]] = {index: set() for index in faces}
    edges: dict[int, list[tuple[int, bool, dict[int, tuple[float, float]]]]] = defaultdict(list)
    for face_index, records in faces.items():
        for edge_index, seam, endpoint_uvs in records:
            edges[edge_index].append((face_index, seam, endpoint_uvs))
    for records in edges.values():
        if len(records) != 2:
            continue
        (first_index, _first_seam, first_uvs), (second_index, _second_seam, second_uvs) = records
        # Seams guide future unwrapping; only current coordinates define UV continuity.
        if first_uvs.keys() != second_uvs.keys():
            continue
        if all(_uv_close(first_uvs[key], second_uvs[key]) for key in first_uvs):
            adjacency[first_index].add(second_index)
            adjacency[second_index].add(first_index)
    remaining = set(faces)
    islands: list[list[int]] = []
    for seed in sorted(faces):
        if seed not in remaining:
            continue
        queue = deque([seed])
        remaining.remove(seed)
        island: list[int] = []
        while queue:
            current = queue.popleft()
            island.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        islands.append(sorted(island))
    islands.sort(key=lambda item: item[0] if item else -1)
    return islands


def _uv_quality(coordinates: Mapping[int, Sequence[tuple[float, float]]]) -> dict[str, Any]:
    """Cheap numeric diagnostics, not an overlap/distortion or artistic quality verdict."""
    degenerate = 0
    invalid = 0
    total_area = 0.0
    for points in coordinates.values():
        if not all(math.isfinite(value) for point in points for value in point):
            invalid += 1
            continue
        if len(points) < 3:
            degenerate += 1
            continue
        origin = points[0]
        area = abs(sum(
            (points[i][0] - origin[0]) * (points[i + 1][1] - origin[1])
            - (points[i + 1][0] - origin[0]) * (points[i][1] - origin[1])
            for i in range(1, len(points) - 1)
        )) * 0.5
        if not math.isfinite(area):
            invalid += 1
            continue
        degenerate += int(area <= 1e-12)
        total_area += area
    return {
        "face_count": len(coordinates), "degenerate_face_count": degenerate,
        "invalid_face_count": invalid,
        "total_absolute_signed_area": total_area if math.isfinite(total_area) else None,
        "area_epsilon": 1e-12,
        "limitations": "Per-face signed polygon area only; does not prove absence of overlaps, self-intersections, distortion, or acceptable texel density. Tiny valid faces can fall below the threshold.",
    }


def _verification(analysis: Mapping[str, Any]) -> dict[str, Any]:
    quality = analysis.get("quality")
    warnings = []
    if analysis.get("analysis_truncated") or not quality:
        warnings.append("UV analysis is incomplete; narrow the scope and reinspect.")
    else:
        if quality["invalid_face_count"]:
            warnings.append("Some UV faces contain non-finite coordinates or area calculations.")
        if quality["degenerate_face_count"]:
            warnings.append("Some UV faces have near-zero signed area; inspect collapsed, tiny or folded UVs.")
        if not quality["face_count"]:
            warnings.append("No UV faces were measured.")
    return {"status": "needs_review" if warnings else "basic_checks_passed",
            "user_goal_verified": False, "warnings": warnings}


def _invalid_uv_analysis(layer_name: str, quality: Mapping[str, Any], loop_count: int) -> dict[str, Any]:
    return {"layer": layer_name, "quality": dict(quality), "scoped_face_count": quality["face_count"],
            "scoped_loop_count": loop_count, "bounds": None, "island_count": None, "islands": [],
            "analysis_truncated": True, "analysis_reason": "Non-finite UV coordinates or area; bounds and islands are unavailable."}


def _island_summaries(
    islands: Sequence[Sequence[int]],
    coordinates: Mapping[int, Sequence[tuple[float, float]]],
    maximum: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for island in islands[:maximum]:
        uvs = [uv for face_index in island for uv in coordinates[face_index]]
        minimum = [min(uv[index] for uv in uvs) for index in range(2)]
        maximum_uv = [max(uv[index] for uv in uvs) for index in range(2)]
        result.append(
            {
                "face_count": len(island),
                "loop_count": len(uvs),
                "face_indices": list(island[:100]),
                "face_indices_truncated": len(island) > 100,
                "bounds": {"min": minimum, "max": maximum_uv},
            }
        )
    return result


def _edit_data(
    obj: Any,
    layer_name: str | None,
    selection_id: str | None,
    selected_only: bool,
) -> tuple[Any, Any, list[Any]]:
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    layer = (
        bm.loops.layers.uv.get(layer_name)
        if layer_name is not None
        else bm.loops.layers.uv.active
    )
    if layer is None:
        available = [item.name for item in obj.data.uv_layers]
        raise invalid_argument(
            "The requested mesh has no matching UV layer.",
            uv_layer=layer_name,
            available_uv_layers=available,
        )
    reference = None
    if selection_id is not None:
        if not isinstance(selection_id, str):
            raise invalid_argument("'selection_id' must be a string.", parameter="selection_id")
        reference = validate_selection_reference(selection_id, obj, bm)
    if reference is not None:
        try:
            faces = [bm.faces[index] for index in reference["faces"]]
        except IndexError as exc:
            raise BridgeError(
                ErrorCode.INVALID_SELECTION,
                "Mesh topology changed after the selection reference was created.",
                {"selection_id": selection_id, "object": obj.name},
            ) from exc
    elif selected_only:
        faces = [face for face in bm.faces if face.select]
    else:
        faces = list(bm.faces)
    return bm, layer, faces


def _inspect_edit_uv(
    obj: Any,
    *,
    layer_name: str | None,
    selection_id: str | None,
    selected_only: bool,
    max_islands: int,
) -> dict[str, Any]:
    _bm, layer, faces = _edit_data(obj, layer_name, selection_id, selected_only)
    if len(faces) > _MAX_FACES:
        return {
            "layer": layer.name,
            "scoped_face_count": len(faces),
            "analysis_truncated": True,
            "analysis_limit": _MAX_FACES,
        }
    coordinates: dict[int, list[tuple[float, float]]] = {}
    records: dict[int, list[tuple[int, bool, dict[int, tuple[float, float]]]]] = {}
    selected_uv_loops = 0
    uv_selection_available = True
    pinned_uv_loops = 0
    loop_count = 0
    for face in faces:
        face_uvs: list[tuple[float, float]] = []
        face_edges: list[tuple[int, bool, dict[int, tuple[float, float]]]] = []
        for loop in face.loops:
            loop_count += 1
            if loop_count > _MAX_LOOPS:
                return {
                    "layer": layer.name,
                    "scoped_face_count": len(faces),
                    "analysis_truncated": True,
                    "analysis_limit": _MAX_LOOPS,
                    "truncated_field": "loops",
                }
            uv_data = loop[layer]
            uv = (float(uv_data.uv[0]), float(uv_data.uv[1]))
            next_uv_data = loop.link_loop_next[layer]
            next_uv = (float(next_uv_data.uv[0]), float(next_uv_data.uv[1]))
            face_uvs.append(uv)
            if hasattr(uv_data, "select"):
                selected_uv_loops += int(bool(uv_data.select))
            else:
                uv_selection_available = False
            pinned_uv_loops += int(bool(uv_data.pin_uv))
            face_edges.append(
                (
                    loop.edge.index,
                    bool(loop.edge.seam),
                    {loop.vert.index: uv, loop.link_loop_next.vert.index: next_uv},
                )
            )
        coordinates[face.index] = face_uvs
        records[face.index] = face_edges
    quality = _uv_quality(coordinates)
    if quality["invalid_face_count"]:
        return _invalid_uv_analysis(layer.name, quality, loop_count)
    islands = _islands(records)
    summaries = _island_summaries(islands, coordinates, max_islands)
    all_uvs = [uv for values in coordinates.values() for uv in values]
    bounds = (
        {
            "min": [min(uv[index] for uv in all_uvs) for index in range(2)],
            "max": [max(uv[index] for uv in all_uvs) for index in range(2)],
        }
        if all_uvs
        else None
    )
    return {
        "layer": layer.name,
        "scoped_face_count": len(faces),
        "scoped_loop_count": loop_count,
        "selected_uv_loop_count": selected_uv_loops if uv_selection_available else None,
        "uv_selection_available": uv_selection_available,
        "pinned_uv_loop_count": pinned_uv_loops,
        "quality": quality,
        "bounds": bounds,
        "island_count": len(islands),
        "islands": summaries,
        "islands_truncated": len(islands) > len(summaries),
        "analysis_truncated": False,
    }


def _inspect_object_uv(
    obj: Any,
    *,
    layer_name: str | None,
    selected_only: bool,
    max_islands: int,
) -> dict[str, Any]:
    layers = obj.data.uv_layers
    layer = layers.get(layer_name) if layer_name is not None else layers.active
    if layer is None:
        raise invalid_argument(
            "The requested mesh has no matching UV layer.",
            uv_layer=layer_name,
            available_uv_layers=[item.name for item in layers],
        )
    polygons = [polygon for polygon in obj.data.polygons if polygon.select or not selected_only]
    if len(polygons) > _MAX_FACES:
        return {
            "layer": layer.name,
            "scoped_face_count": len(polygons),
            "analysis_truncated": True,
            "analysis_limit": _MAX_FACES,
        }
    records: dict[int, list[tuple[int, bool, dict[int, tuple[float, float]]]]] = {}
    coordinates: dict[int, list[tuple[float, float]]] = {}
    loop_count = 0
    for polygon in polygons:
        face_uvs: list[tuple[float, float]] = []
        face_edges: list[tuple[int, bool, dict[int, tuple[float, float]]]] = []
        loop_indices = list(polygon.loop_indices)
        for position, loop_index in enumerate(loop_indices):
            loop_count += 1
            if loop_count > _MAX_LOOPS:
                return {
                    "layer": layer.name,
                    "scoped_face_count": len(polygons),
                    "analysis_truncated": True,
                    "analysis_limit": _MAX_LOOPS,
                    "truncated_field": "loops",
                }
            next_loop_index = loop_indices[(position + 1) % len(loop_indices)]
            loop = obj.data.loops[loop_index]
            next_loop = obj.data.loops[next_loop_index]
            uv = tuple(float(value) for value in layer.data[loop_index].uv)
            next_uv = tuple(float(value) for value in layer.data[next_loop_index].uv)
            face_uvs.append(uv)
            edge = obj.data.edges[loop.edge_index]
            face_edges.append(
                (
                    loop.edge_index,
                    bool(edge.use_seam),
                    {loop.vertex_index: uv, next_loop.vertex_index: next_uv},
                )
            )
        coordinates[polygon.index] = face_uvs
        records[polygon.index] = face_edges
    quality = _uv_quality(coordinates)
    if quality["invalid_face_count"]:
        return _invalid_uv_analysis(layer.name, quality, loop_count)
    islands = _islands(records)
    summaries = _island_summaries(islands, coordinates, max_islands)
    all_uvs = [uv for values in coordinates.values() for uv in values]
    return {
        "layer": layer.name,
        "scoped_face_count": len(polygons),
        "scoped_loop_count": loop_count,
        "selected_uv_loop_count": None,
        "quality": quality,
        "pinned_uv_loop_count": sum(
            int(bool(getattr(item, "pin_uv", False))) for item in layer.data
        ),
        "bounds": (
            {
                "min": [min(uv[index] for uv in all_uvs) for index in range(2)],
                "max": [max(uv[index] for uv in all_uvs) for index in range(2)],
            }
            if all_uvs
            else None
        ),
        "island_count": len(islands),
        "islands": summaries,
        "islands_truncated": len(islands) > len(summaries),
        "analysis_truncated": False,
    }


def _coordinate_page(
    obj: Any, *, layer_name: str | None, selection_id: str | None,
    selected_only: bool, offset: int, maximum: int,
) -> dict[str, Any]:
    """Bounded face-corner evidence; offsets are scoped positions, not durable IDs."""
    edit_mode = obj.mode == "EDIT"
    if edit_mode:
        bm, layer, faces = _edit_data(obj, layer_name, selection_id, selected_only)
        bm.faces.index_update()
        bm.verts.index_update()
    else:
        layers = obj.data.uv_layers
        layer = layers.get(layer_name) if layer_name is not None else layers.active
        if layer is None:
            raise invalid_argument("The requested mesh has no matching UV layer.")
        faces = [face for face in obj.data.polygons if not selected_only or face.select]
    if len(faces) > _MAX_FACES:
        return {"items": [], "analysis_truncated": True, "analysis_limit": _MAX_FACES, "next_offset": None}
    total = sum(len(face.loops) if edit_mode else face.loop_total for face in faces)
    if total > _MAX_LOOPS:
        return {"items": [], "analysis_truncated": True, "analysis_limit": _MAX_LOOPS, "next_offset": None}
    items = []
    position = 0
    for face in faces:
        count = len(face.loops) if edit_mode else face.loop_total
        if position + count <= offset:
            position += count
            continue
        for corner in range(count):
            if position >= offset and len(items) < maximum:
                if edit_mode:
                    loop = face.loops[corner]
                    uv_data = loop[layer]
                    vertex_index = loop.vert.index
                else:
                    loop_index = face.loop_start + corner
                    uv_data = layer.data[loop_index]
                    vertex_index = obj.data.loops[loop_index].vertex_index
                uv = [float(value) for value in uv_data.uv]
                finite = all(math.isfinite(value) for value in uv)
                items.append({
                    "face_index": face.index, "corner_index": corner,
                    "vertex_index": vertex_index, "uv": uv if finite else None, "finite": finite,
                    "pinned": bool(uv_data.pin_uv),
                    "selected": bool(uv_data.select) if edit_mode and hasattr(uv_data, "select") else None,
                })
            position += 1
            if len(items) >= maximum:
                break
        if len(items) >= maximum:
            break
    next_offset = offset + len(items)
    return {
        "layer": layer.name, "items": items, "offset": offset, "scoped_loop_count": total,
        "truncated": next_offset < total, "next_offset": next_offset if next_offset < total else None,
        "analysis_truncated": False,
        "index_validity": "Scope-relative pagination; reinspect after UV, topology, selection, mode, layer or scene changes. Face/corner indices are not persistent IDs.",
    }


def inspect_uv(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = _mesh_object(params)
    selected_only = bool_param(params, "selected_only", False)
    include_coordinates = bool_param(params, "include_coordinates", False)
    coordinate_offset = int_param(params, "coordinate_offset", 0, minimum=0, maximum=_MAX_LOOPS)
    max_coordinates = int_param(params, "max_coordinates", 100, minimum=1, maximum=256)
    max_islands = int_param(params, "max_islands", 100, minimum=1, maximum=1_000)
    layer_name = _optional_layer_name(params)
    selection_id = params.get("selection_id")
    if selection_id is not None and obj.mode != "EDIT":
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "A UV selection reference can only be validated while its mesh is in Edit Mode.",
            {"object": obj.name, "current_mode": obj.mode, "required_mode": "EDIT"},
        )
    layers, layers_truncated = _layer_summaries(obj)
    if not obj.data.uv_layers:
        empty = {
            "object": obj.name,
            "mode": obj.mode,
            "uv_layer_count": 0,
            "uv_layers": [],
            "layers_truncated": False,
            "analysis": None,
        }
        if include_coordinates:
            empty["coordinates"] = None
        return empty
    analysis = (
        _inspect_edit_uv(
            obj,
            layer_name=layer_name,
            selection_id=selection_id,
            selected_only=selected_only or selection_id is not None,
            max_islands=max_islands,
        )
        if obj.mode == "EDIT"
        else _inspect_object_uv(
            obj,
            layer_name=layer_name,
            selected_only=selected_only,
            max_islands=max_islands,
        )
    )
    result = {
        "object": obj.name,
        "mode": obj.mode,
        "uv_layer_count": len(obj.data.uv_layers),
        "uv_layers": layers,
        "layers_truncated": layers_truncated,
        "analysis": analysis,
    }
    if include_coordinates:
        result["coordinates"] = _coordinate_page(
            obj, layer_name=layer_name, selection_id=selection_id,
            selected_only=selected_only or selection_id is not None,
            offset=coordinate_offset, maximum=max_coordinates,
        )
    return result


def _operation_context(
    obj: Any,
    params: Mapping[str, Any],
    *,
    operator: Any,
    create_default: bool = True,
) -> tuple[Any, Any, list[Any], str | None, bool]:
    bpy = require_blender()
    if obj.mode != "EDIT" or bpy.context.view_layer.objects.active != obj:
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "UV operations require the explicit target to be the active mesh in Edit Mode.",
            {
                "object": obj.name,
                "current_mode": obj.mode,
                "active_object": getattr(bpy.context.view_layer.objects.active, "name", None),
                "required_mode": "EDIT",
            },
        )
    edit_objects = [
        item
        for item in getattr(bpy.context, "objects_in_mode_unique_data", (obj,))
        if item.type == "MESH"
    ]
    if len(edit_objects) != 1 or edit_objects[0] != obj:
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            "UV operations require single-object Edit Mode to avoid modifying another mesh.",
            {"edit_objects": [item.name for item in edit_objects]},
        )
    require_local_single_user_mesh(obj)
    if not operator.poll():
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            "The requested Blender UV operator is unavailable in the current context.",
            {"object": obj.name},
        )
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    selection_id = params.get("selection_id")
    reference = None
    if selection_id is not None:
        if not isinstance(selection_id, str):
            raise invalid_argument("'selection_id' must be a string.", parameter="selection_id")
        reference = validate_selection_reference(selection_id, obj, bm)
    try:
        faces = (
            [bm.faces[index] for index in reference["faces"]]
            if reference is not None
            else [face for face in bm.faces if face.select]
        )
    except IndexError as exc:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Mesh topology changed after the selection reference was created.",
            {"selection_id": selection_id, "object": obj.name},
        ) from exc
    if not faces:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "No faces are selected for the UV operation.")
    if len(faces) > _MAX_FACES or sum(len(face.loops) for face in faces) > _MAX_LOOPS:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "The selected UV operation exceeds the bounded face or loop limit.",
            {"maximum_faces": _MAX_FACES, "maximum_loops": _MAX_LOOPS},
        )
    requested_layer = _optional_layer_name(params)
    create_if_missing = bool_param(params, "create_if_missing", create_default)
    layer = (
        bm.loops.layers.uv.get(requested_layer)
        if requested_layer is not None
        else bm.loops.layers.uv.active
    )
    created = False
    if layer is None:
        if not create_if_missing:
            raise invalid_argument(
                "The requested mesh has no matching UV layer and creation is disabled.",
                uv_layer=requested_layer,
                available_uv_layers=[item.name for item in obj.data.uv_layers],
            )
        layer = bm.loops.layers.uv.new(requested_layer or "UVMap")
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        created = True
    return bm, layer, faces, selection_id if isinstance(selection_id, str) else None, created


@contextmanager
def _scoped_uv_selection(bm: Any, layer: Any, faces: Sequence[Any]) -> Iterator[None]:
    vertex_state = [(item, bool(item.select)) for item in bm.verts]
    edge_state = [(item, bool(item.select)) for item in bm.edges]
    face_state = [(item, bool(item.select)) for item in bm.faces]
    uv_state = [
        (
            loop,
            bool(loop[layer].select) if hasattr(loop[layer], "select") else None,
            (
                bool(loop[layer].select_edge)
                if hasattr(loop[layer], "select_edge")
                else None
            ),
        )
        for face in bm.faces
        for loop in face.loops
    ]
    try:
        for item, _ in vertex_state:
            item.select = False
        for item, _ in edge_state:
            item.select = False
        for item, _ in face_state:
            item.select = False
        for loop, _, _ in uv_state:
            if hasattr(loop[layer], "select"):
                loop[layer].select = False
            if hasattr(loop[layer], "select_edge"):
                loop[layer].select_edge = False
        for face in faces:
            face.select_set(True)
            for loop in face.loops:
                if hasattr(loop[layer], "select"):
                    loop[layer].select = True
                if hasattr(loop[layer], "select_edge"):
                    loop[layer].select_edge = True
        yield
    finally:
        for item, selected in vertex_state:
            item.select = selected
        for item, selected in edge_state:
            item.select = selected
        for item, selected in face_state:
            item.select = selected
        for loop, selected, edge_selected in uv_state:
            if selected is not None and hasattr(loop[layer], "select"):
                loop[layer].select = selected
            if edge_selected is not None and hasattr(loop[layer], "select_edge"):
                loop[layer].select_edge = edge_selected


def _run_uv_operator(
    obj: Any,
    bm: Any,
    layer: Any,
    faces: Sequence[Any],
    operator: Any,
    keyword_arguments: Mapping[str, Any],
    *,
    created_layer: bool,
) -> None:
    try:
        with _scoped_uv_selection(bm, layer, faces):
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            result = operator(**keyword_arguments)
            if "FINISHED" not in result:
                raise BridgeError(
                    ErrorCode.OPERATION_FAILED,
                    "Blender canceled the requested UV operation.",
                    {"object": obj.name, "uv_layer": layer.name},
                )
    except (BridgeError, RuntimeError) as exc:
        if created_layer:
            with suppress(ReferenceError, RuntimeError, TypeError, ValueError):
                bm.loops.layers.uv.remove(layer)
        if isinstance(exc, BridgeError):
            raise
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not complete the requested UV operation.",
            {"object": obj.name, "uv_layer": layer.name},
        ) from exc
    finally:
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)


def _activate_layer(obj: Any, layer_name: str) -> None:
    for index, layer in enumerate(obj.data.uv_layers):
        if layer.name == layer_name:
            obj.data.uv_layers.active_index = index
            return


def _post_operation(
    obj: Any,
    *,
    operation: str,
    layer_name: str,
    selection_id: str | None,
    face_count: int,
    created_layer: bool,
) -> dict[str, Any]:
    analysis = _inspect_edit_uv(
        obj,
        layer_name=layer_name,
        selection_id=selection_id,
        selected_only=True,
        max_islands=100,
    )
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "operation": operation,
        "uv_layer": layer_name,
        "created_uv_layer": created_layer,
        "faces_affected": face_count,
        "overwrites_uv_coordinates": True,
        "verification": _verification(analysis),
        "post_state": analysis,
    }


def unwrap(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _mesh_object(params)
    method = str(params.get("method", "ANGLE_BASED")).upper()
    if method not in {"ANGLE_BASED", "CONFORMAL", "MINIMUM_STRETCH"}:
        raise invalid_argument("'method' must be ANGLE_BASED, CONFORMAL, or MINIMUM_STRETCH.")
    fill_holes = bool_param(params, "fill_holes", True)
    correct_aspect = bool_param(params, "correct_aspect", True)
    use_subsurf_data = bool_param(params, "use_subsurf_data", False)
    margin = float_param(params, "margin", 0.001, minimum=0.0, maximum=1.0)
    bm, layer, faces, selection_id, created = _operation_context(
        obj, params, operator=bpy.ops.uv.unwrap
    )
    _activate_layer(obj, layer.name)
    _run_uv_operator(
        obj,
        bm,
        layer,
        faces,
        bpy.ops.uv.unwrap,
        {
            "method": method,
            "fill_holes": fill_holes,
            "correct_aspect": correct_aspect,
            "use_subsurf_data": use_subsurf_data,
            "margin": margin,
        },
        created_layer=created,
    )
    return _post_operation(
        obj,
        operation="UNWRAP",
        layer_name=layer.name,
        selection_id=selection_id,
        face_count=len(faces),
        created_layer=created,
    )


def smart_project(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _mesh_object(params)
    angle_limit = float_param(params, "angle_limit", math.radians(66.0), minimum=0.0, maximum=math.pi)
    island_margin = float_param(params, "island_margin", 0.0, minimum=0.0, maximum=1.0)
    area_weight = float_param(params, "area_weight", 0.0, minimum=0.0, maximum=1.0)
    correct_aspect = bool_param(params, "correct_aspect", True)
    scale_to_bounds = bool_param(params, "scale_to_bounds", False)
    bm, layer, faces, selection_id, created = _operation_context(
        obj, params, operator=bpy.ops.uv.smart_project
    )
    _activate_layer(obj, layer.name)
    _run_uv_operator(
        obj,
        bm,
        layer,
        faces,
        bpy.ops.uv.smart_project,
        {
            "angle_limit": angle_limit,
            "island_margin": island_margin,
            "area_weight": area_weight,
            "correct_aspect": correct_aspect,
            "scale_to_bounds": scale_to_bounds,
        },
        created_layer=created,
    )
    return _post_operation(
        obj,
        operation="SMART_PROJECT",
        layer_name=layer.name,
        selection_id=selection_id,
        face_count=len(faces),
        created_layer=created,
    )


def pack_islands(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = _mesh_object(params)
    rotate = bool_param(params, "rotate", True)
    scale = bool_param(params, "scale", True)
    margin = float_param(params, "margin", 0.001, minimum=0.0, maximum=1.0)
    bm, layer, faces, selection_id, created = _operation_context(
        obj, params, operator=bpy.ops.uv.pack_islands, create_default=False
    )
    _activate_layer(obj, layer.name)
    _run_uv_operator(
        obj,
        bm,
        layer,
        faces,
        bpy.ops.uv.pack_islands,
        {"rotate": rotate, "scale": scale, "margin": margin},
        created_layer=created,
    )
    return _post_operation(
        obj,
        operation="PACK_ISLANDS",
        layer_name=layer.name,
        selection_id=selection_id,
        face_count=len(faces),
        created_layer=created,
    )


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "uv.inspect",
        inspect_uv,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="uv",
        description="Inspect bounded UV layers, selection, bounds, and island connectivity.",
    )
    modifying = {
        "permissions": (Permission.EDIT_MESH,),
        "toolset": "uv",
        "modifies": True,
    }
    registry.register("uv.unwrap", unwrap, description="Unwrap selected faces with explicit method and margin.", **modifying)
    registry.register("uv.smart_project", smart_project, description="Smart-project selected faces using bounded projection settings.", **modifying)
    registry.register("uv.pack_islands", pack_islands, description="Pack selected UV islands with bounded margin settings.", **modifying)


__all__ = ["inspect_uv", "pack_islands", "register_tools", "smart_project", "unwrap"]
