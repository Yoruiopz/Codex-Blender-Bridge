"""Selection-scoped mesh editing implemented with :mod:`bmesh`."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..mesh_inspector import inspect_mesh_object
from ..permissions import Permission
from ..selection import clear_selection_references, validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import (
    bool_param,
    float_param,
    get_collection,
    get_object,
    int_param,
    reject_unknown_params,
    require_blender,
    serialize_transform,
    vector3,
)
from .interaction import _active_edit_mesh

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

_MAX_OPERATION_ELEMENTS = 100_000
_MAX_BEVEL_COMPLEXITY = 500_000
_MAX_CREATE_VERTICES = 100_000
_MAX_CREATE_EDGES = 200_000
_MAX_CREATE_FACES = 100_000
_MAX_CREATE_FACE_CORNERS = 500_000
_MAX_FACE_VERTICES = 1_024
_MAX_ID_NAME_BYTES = 63


@dataclass(frozen=True, slots=True)
class _PreparedMesh:
    object_name: str
    mesh_name: str
    collection_name: str | None
    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    faces: tuple[tuple[int, ...], ...]
    location: tuple[float, float, float]
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    rotation_mode: str


def _id_name(value: Any, parameter: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument(
            f"'{parameter}' must be a non-empty string.", parameter=parameter
        )
    if "\x00" in value or len(value.encode("utf-8")) > _MAX_ID_NAME_BYTES:
        raise invalid_argument(
            f"'{parameter}' must be a Blender ID name of at most {_MAX_ID_NAME_BYTES} UTF-8 bytes.",
            parameter=parameter,
            maximum_bytes=_MAX_ID_NAME_BYTES,
        )
    return value


def _bounded_array(value: Any, name: str, maximum: int) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise invalid_argument(f"'{name}' must be an array.", parameter=name)
    if len(value) > maximum:
        raise invalid_argument(
            f"'{name}' exceeds the bounded mesh-creation limit.",
            parameter=name,
            count=len(value),
            maximum=maximum,
        )
    return value


def _index(value: Any, *, parameter: str, vertex_count: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_argument(
            f"'{parameter}' values must be integer vertex indices.", parameter=parameter
        )
    if value < 0 or value >= vertex_count:
        raise invalid_argument(
            f"'{parameter}' contains an out-of-range vertex index.",
            parameter=parameter,
            index=value,
            vertex_count=vertex_count,
        )
    return value


def _prepare_mesh_create(params: Mapping[str, Any]) -> _PreparedMesh:
    """Validate and copy the complete request before touching Blender data."""

    object_name = _id_name(params.get("object_name"), "object_name")
    mesh_name = _id_name(params.get("mesh_name"), "mesh_name")
    collection_name = params.get("collection_name")
    if collection_name is not None:
        collection_name = _id_name(collection_name, "collection_name")

    raw_vertices = _bounded_array(
        params.get("vertices"), "vertices", _MAX_CREATE_VERTICES
    )
    if not raw_vertices:
        raise invalid_argument(
            "'vertices' must contain at least one coordinate.", parameter="vertices"
        )
    vertices = tuple(
        vector3(value, f"vertices[{index}]")
        for index, value in enumerate(raw_vertices)
    )
    vertex_count = len(vertices)

    raw_edges = _bounded_array(params.get("edges", ()), "edges", _MAX_CREATE_EDGES)
    edges: list[tuple[int, int]] = []
    unique_edges: set[tuple[int, int]] = set()
    for edge_index, value in enumerate(raw_edges):
        edge = _bounded_array(value, f"edges[{edge_index}]", 2)
        if len(edge) != 2:
            raise invalid_argument(
                f"'edges[{edge_index}]' must contain exactly two vertex indices.",
                parameter=f"edges[{edge_index}]",
            )
        first = _index(
            edge[0], parameter=f"edges[{edge_index}][0]", vertex_count=vertex_count
        )
        second = _index(
            edge[1], parameter=f"edges[{edge_index}][1]", vertex_count=vertex_count
        )
        if first == second:
            raise invalid_argument(
                "Mesh edges may not connect a vertex to itself.", edge_index=edge_index
            )
        canonical = tuple(sorted((first, second)))
        if canonical in unique_edges:
            raise invalid_argument(
                "'edges' contains a duplicate undirected edge.",
                edge_index=edge_index,
                edge=list(canonical),
            )
        unique_edges.add(canonical)
        edges.append((first, second))

    raw_faces = _bounded_array(params.get("faces", ()), "faces", _MAX_CREATE_FACES)
    faces: list[tuple[int, ...]] = []
    unique_faces: set[tuple[int, ...]] = set()
    total_corners = 0
    for face_index, value in enumerate(raw_faces):
        face = _bounded_array(value, f"faces[{face_index}]", _MAX_FACE_VERTICES)
        if len(face) < 3:
            raise invalid_argument(
                f"'faces[{face_index}]' must contain at least three vertex indices.",
                parameter=f"faces[{face_index}]",
            )
        total_corners += len(face)
        if total_corners > _MAX_CREATE_FACE_CORNERS:
            raise invalid_argument(
                "'faces' exceeds the bounded total-corner limit.",
                parameter="faces",
                maximum_corners=_MAX_CREATE_FACE_CORNERS,
            )
        indices = tuple(
            _index(
                item,
                parameter=f"faces[{face_index}][{corner_index}]",
                vertex_count=vertex_count,
            )
            for corner_index, item in enumerate(face)
        )
        if len(set(indices)) != len(indices):
            raise invalid_argument(
                "A mesh face may not repeat a vertex index.", face_index=face_index
            )
        canonical_face = tuple(sorted(indices))
        if canonical_face in unique_faces:
            raise invalid_argument(
                "'faces' contains a duplicate face vertex set.", face_index=face_index
            )
        unique_faces.add(canonical_face)
        faces.append(indices)

    location = vector3(params.get("location"), "location", default=(0.0, 0.0, 0.0))
    rotation = vector3(params.get("rotation"), "rotation", default=(0.0, 0.0, 0.0))
    scale = vector3(params.get("scale"), "scale", default=(1.0, 1.0, 1.0))
    rotation_mode = params.get("rotation_mode", "XYZ")
    if not isinstance(rotation_mode, str):
        raise invalid_argument("'rotation_mode' must be a string.", parameter="rotation_mode")
    rotation_mode = rotation_mode.upper()
    if rotation_mode not in {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}:
        raise invalid_argument(
            "'rotation_mode' must be an Euler rotation mode.",
            parameter="rotation_mode",
            supported=["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"],
        )
    return _PreparedMesh(
        object_name=object_name,
        mesh_name=mesh_name,
        collection_name=collection_name,
        vertices=vertices,
        edges=tuple(edges),
        faces=tuple(faces),
        location=location,
        rotation=rotation,
        scale=scale,
        rotation_mode=rotation_mode,
    )


def _local_bounds(
    vertices: Sequence[Sequence[float]],
) -> dict[str, list[float]]:
    return {
        "min": [min(vertex[index] for vertex in vertices) for index in range(3)],
        "max": [max(vertex[index] for vertex in vertices) for index in range(3)],
    }


def create_mesh(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    prepared = _prepare_mesh_create(params)
    bpy = require_blender()
    if bpy.data.objects.get(prepared.object_name) is not None:
        raise invalid_argument(
            f"An object named '{prepared.object_name}' already exists.",
            parameter="object_name",
        )
    if bpy.data.meshes.get(prepared.mesh_name) is not None:
        raise invalid_argument(
            f"A mesh data-block named '{prepared.mesh_name}' already exists.",
            parameter="mesh_name",
        )
    collection = get_collection(prepared.collection_name)

    mesh = None
    obj = None
    try:
        mesh = bpy.data.meshes.new(prepared.mesh_name)
        if mesh.name != prepared.mesh_name:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Blender could not reserve the exact requested mesh data-block name.",
                {"requested_mesh_name": prepared.mesh_name},
            )
        mesh.from_pydata(prepared.vertices, prepared.edges, prepared.faces)
        if mesh.validate(verbose=False, clean_customdata=False):
            raise BridgeError(
                ErrorCode.INVALID_ARGUMENT,
                "Blender found invalid topology after structured prevalidation.",
            )
        mesh.update(calc_edges=True, calc_edges_loose=True)
        obj = bpy.data.objects.new(prepared.object_name, mesh)
        if obj.name != prepared.object_name:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Blender could not reserve the exact requested object name.",
                {"requested_object_name": prepared.object_name},
            )
        collection.objects.link(obj)
        obj.rotation_mode = prepared.rotation_mode
        obj.location = prepared.location
        obj.rotation_euler = prepared.rotation
        obj.scale = prepared.scale
    except Exception as exc:
        if obj is not None:
            with suppress(ReferenceError, RuntimeError):
                bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            with suppress(ReferenceError, RuntimeError):
                bpy.data.meshes.remove(mesh)
        if isinstance(exc, BridgeError):
            raise
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not create the validated mesh object.",
            {
                "object_name": prepared.object_name,
                "mesh_name": prepared.mesh_name,
            },
        ) from exc

    return {
        "created": True,
        "object": obj.name,
        "mesh_data_name": mesh.name,
        "affected_objects": [obj.name],
        "collections": [item.name for item in obj.users_collection],
        "mesh_counts": {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "faces": len(mesh.polygons),
            "face_corners": sum(len(polygon.vertices) for polygon in mesh.polygons),
        },
        "local_bounds": _local_bounds(prepared.vertices),
        "transform": serialize_transform(obj),
        "selection_changed": False,
        "post_state": inspect_mesh_object(obj, include_topology=True),
    }


def _selected_elements(sequence: Any, label: str) -> list[Any]:
    selected: list[Any] = []
    for element in sequence:
        if not element.select:
            continue
        if len(selected) >= _MAX_OPERATION_ELEMENTS:
            raise BridgeError(
                ErrorCode.INVALID_SELECTION,
                f"Selected {label} exceed the safe V1 operation limit.",
                {"maximum_elements": _MAX_OPERATION_ELEMENTS, "element_type": label},
            )
        selected.append(element)
    return selected


def _edit_bmesh(params: Mapping[str, Any]) -> tuple[Any, Any, Mapping[str, Any] | None]:
    obj = get_object(params.get("object_name"))
    if obj.type != "MESH":
        raise BridgeError(
            ErrorCode.INVALID_ARGUMENT,
            f"Object '{obj.name}' is not a mesh.",
            {"object_type": obj.type},
        )
    if obj.mode != "EDIT":
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "Selection-scoped mesh editing requires the target object to be in Edit Mode.",
            {"object": obj.name, "current_mode": obj.mode, "required_mode": "EDIT"},
        )
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    selection_id = params.get("selection_id")
    if selection_id is None:
        return obj, bm, None
    if not isinstance(selection_id, str):
        raise invalid_argument("'selection_id' must be a string.")
    return obj, bm, validate_selection_reference(selection_id, obj, bm)


def _operation_elements(
    sequence: Any,
    label: str,
    reference: Mapping[str, Any] | None,
) -> list[Any]:
    """Resolve scoped geometry without changing the user's live selection."""

    if reference is None:
        return _selected_elements(sequence, label)
    indices = reference[label]
    if len(indices) > _MAX_OPERATION_ELEMENTS:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            f"Selected {label} exceed the safe V1 operation limit.",
            {"maximum_elements": _MAX_OPERATION_ELEMENTS, "element_type": label},
        )
    try:
        return [sequence[index] for index in indices]
    except IndexError as exc:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Mesh topology changed after the selection reference was created.",
            {"selection_id": reference["selection_id"]},
        ) from exc


def _selection_counts(bm: Any) -> dict[str, int]:
    return {
        "vertices": sum(vertex.select for vertex in bm.verts),
        "edges": sum(edge.select for edge in bm.edges),
        "faces": sum(face.select for face in bm.faces),
    }


def _mesh_counts(bm: Any) -> dict[str, int]:
    return {"vertices": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces)}


def _finish(obj: Any, bm: Any, *, destructive: bool, before: Mapping[str, int]) -> dict[str, Any]:
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=destructive)
    if destructive:
        clear_selection_references(obj.name)
    return {
        "object": obj.name,
        "mesh_counts_before": dict(before),
        "mesh_counts_after": _mesh_counts(bm),
        "selection_after": _selection_counts(bm),
    }


def inspect_mesh(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"))
    return {"object": obj.name, "mesh": inspect_mesh_object(obj, include_topology=True)}


def recalculate_normals(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    selected_only = bool_param(params, "selection_only", True)
    inside = bool_param(params, "inside", False)
    obj, bm, reference = _edit_bmesh(params)
    if not selected_only and len(bm.faces) > _MAX_OPERATION_ELEMENTS:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Mesh faces exceed the safe V1 operation limit.",
            {"maximum_elements": _MAX_OPERATION_ELEMENTS, "element_type": "faces"},
        )
    faces = (
        _operation_elements(bm.faces, "faces", reference)
        if selected_only
        else list(bm.faces)
    )
    if not faces:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "No faces are selected for normal recalculation.")
    before = _mesh_counts(bm)
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    if inside:
        bmesh.ops.reverse_faces(bm, faces=faces, flip_multires=True)
    result = _finish(obj, bm, destructive=False, before=before)
    result.update({"faces_affected": len(faces), "inside": inside})
    return result


def delete_selected(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    element_type = str(params.get("element_type", "VERT")).upper()
    aliases = {"VERTEX": "VERT", "VERTICES": "VERT", "EDGES": "EDGE", "FACES": "FACE"}
    element_type = aliases.get(element_type, element_type)
    if element_type not in {"VERT", "EDGE", "FACE"}:
        raise invalid_argument("'element_type' must be VERT, EDGE, or FACE.")
    obj, bm, reference = _edit_bmesh(params)
    sequence = {"VERT": bm.verts, "EDGE": bm.edges, "FACE": bm.faces}[element_type]
    label = {"VERT": "vertices", "EDGE": "edges", "FACE": "faces"}[element_type]
    geometry = _operation_elements(sequence, label, reference)
    if not geometry:
        raise BridgeError(ErrorCode.INVALID_SELECTION, f"No selected {element_type.lower()} elements.")
    before = _mesh_counts(bm)
    bmesh.ops.delete(bm, geom=geometry, context={"VERT": "VERTS", "EDGE": "EDGES", "FACE": "FACES"}[element_type])
    result = _finish(obj, bm, destructive=True, before=before)
    result.update({"deleted_elements": len(geometry), "element_type": element_type})
    return result


def dissolve_selected(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    use_verts = bool_param(params, "use_verts", False)
    use_face_split = bool_param(params, "use_face_split", False)
    obj, bm, reference = _edit_bmesh(params)
    before = _mesh_counts(bm)
    faces = _operation_elements(bm.faces, "faces", reference)
    if faces:
        bmesh.ops.dissolve_faces(bm, faces=faces, use_verts=use_verts)
        dissolved_type, dissolved_count = "FACE", len(faces)
    else:
        edges = _operation_elements(bm.edges, "edges", reference)
    if not faces and edges:
        bmesh.ops.dissolve_edges(
            bm,
            edges=edges,
            use_verts=use_verts,
            use_face_split=use_face_split,
        )
        dissolved_type, dissolved_count = "EDGE", len(edges)
    elif not faces:
        vertices = _operation_elements(bm.verts, "vertices", reference)
        if not vertices:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "No mesh elements are selected to dissolve.")
        bmesh.ops.dissolve_verts(
            bm,
            verts=vertices,
            use_face_split=use_face_split,
            use_boundary_tear=False,
        )
        dissolved_type, dissolved_count = "VERT", len(vertices)
    result = _finish(obj, bm, destructive=True, before=before)
    result.update({"dissolved_elements": dissolved_count, "element_type": dissolved_type})
    return result


def extrude_selected(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    if "offset" not in params:
        raise invalid_argument("An extrusion 'offset' is required.")
    offset = vector3(params.get("offset"), "offset")
    obj, bm, reference = _edit_bmesh(params)
    faces = _operation_elements(bm.faces, "faces", reference)
    if not faces:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Face-region extrusion requires one or more selected faces.",
        )
    before = _mesh_counts(bm)
    output = bmesh.ops.extrude_face_region(bm, geom=faces, use_keep_orig=False)
    extruded = list(output["geom"])
    new_vertices = [element for element in extruded if isinstance(element, bmesh.types.BMVert)]
    if any(offset):
        bmesh.ops.translate(bm, verts=new_vertices, vec=__import__("mathutils").Vector(offset))
    for element in (*bm.verts, *bm.edges, *bm.faces):
        element.select = False
    for element in extruded:
        element.select = True
    result = _finish(obj, bm, destructive=True, before=before)
    result.update({"source_faces": len(faces), "new_vertices": len(new_vertices), "offset": list(offset)})
    return result


def inset_selected(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    if "thickness" not in params:
        raise invalid_argument("Inset 'thickness' is required.")
    thickness = float_param(params, "thickness", 0.0, minimum=0.0)
    depth = float_param(params, "depth", 0.0)
    obj, bm, reference = _edit_bmesh(params)
    faces = _operation_elements(bm.faces, "faces", reference)
    if not faces:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "No faces are selected to inset.")
    before = _mesh_counts(bm)
    output = bmesh.ops.inset_region(
        bm,
        faces=faces,
        use_boundary=True,
        use_even_offset=True,
        use_relative_offset=False,
        use_interpolate=True,
        thickness=thickness,
        depth=depth,
    )
    result = _finish(obj, bm, destructive=True, before=before)
    result.update(
        {
            "source_faces": len(faces),
            "new_faces": len(output.get("faces", ())),
            "thickness": thickness,
            "depth": depth,
        }
    )
    return result


def bevel_selected(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    if "width" not in params:
        raise invalid_argument("Bevel 'width' is required.")
    width = float_param(params, "width", 0.0, minimum=0.0)
    segments = int_param(params, "segments", 1, minimum=1, maximum=16)
    affect = str(params.get("affect", "EDGES")).upper()
    if affect not in {"EDGES", "VERTICES"}:
        raise invalid_argument("'affect' must be EDGES or VERTICES.")
    obj, bm, reference = _edit_bmesh(params)
    geometry = (
        _operation_elements(bm.edges, "edges", reference)
        if affect == "EDGES"
        else _operation_elements(bm.verts, "vertices", reference)
    )
    if not geometry:
        raise BridgeError(ErrorCode.INVALID_SELECTION, f"No selected {affect.lower()} to bevel.")
    if len(geometry) * segments > _MAX_BEVEL_COMPLEXITY:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Requested bevel exceeds the safe V1 complexity limit.",
            {
                "selected_elements": len(geometry),
                "segments": segments,
                "maximum_complexity": _MAX_BEVEL_COMPLEXITY,
            },
        )
    before = _mesh_counts(bm)
    output = bmesh.ops.bevel(
        bm,
        geom=geometry,
        offset=width,
        offset_type="OFFSET",
        segments=segments,
        affect=affect,
        clamp_overlap=True,
        loop_slide=True,
    )
    result = _finish(obj, bm, destructive=True, before=before)
    result.update(
        {
            "source_elements": len(geometry),
            "created_faces": len(output.get("faces", ())),
            "width": width,
            "segments": segments,
            "affect": affect,
        }
    )
    return result


def mark_seams(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Set edge seam flags only; never unwrap or change geometry/selection."""
    del context
    reject_unknown_params(params, {"object_name", "seam", "selection_id"})
    name = _id_name(params.get("object_name"), "object_name")
    seam = bool_param(params, "seam", True)
    selection_id = params.get("selection_id")
    if selection_id is not None and (not isinstance(selection_id, str) or not selection_id):
        raise invalid_argument("'selection_id' must be a non-empty string.")
    _bpy, obj, bm, _sequences = _active_edit_mesh(name)
    if any(getattr(data, "library", None) or getattr(data, "override_library", None)
           for data in (obj, obj.data)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Seam editing requires local, non-override data.", {"object": name})
    if obj.data.users != 1:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Seam editing requires a single-user mesh; shared data is not changed implicitly.", {"object": name, "mesh_users": obj.data.users})
    reference = validate_selection_reference(selection_id, obj, bm) if selection_id else None
    edges = _operation_elements(bm.edges, "edges", reference)
    if not edges or any(edge.hide for edge in edges):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Seam editing requires non-hidden selected edges.", {"object": name})
    before = [(edge, bool(edge.seam)) for edge in edges]
    changed_count = sum(previous != seam for _, previous in before)
    seam_count_before = sum(bool(edge.seam) for edge in bm.edges)
    try:
        for edge, _ in before:
            edge.seam = seam
        if changed_count:
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        if any(bool(edge.seam) != seam for edge, _ in before):
            raise RuntimeError("Seam post-state verification failed")
    except Exception as exc:
        restored = False
        try:
            for edge, previous in before:
                edge.seam = previous
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            restored = all(bool(edge.seam) == previous for edge, previous in before)
        except Exception:
            logging.getLogger(__name__).exception("Failed to restore seam flags on %s", name)
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Seam editing failed; reinspect the tracked operation.", {
            "object": name, "affected_objects": [name], "execution_started": True,
            "verification_required": True, "rollback_performed": restored,
        }) from exc
    return {
        "object": name, "affected_objects": [name], "seam": seam,
        "changed": bool(changed_count), "changed_edges": changed_count,
        "target_edge_count": len(edges), "edge_indices": [edge.index for edge in edges[:256]],
        "edge_indices_truncated": len(edges) > 256,
        "seam_count_before": seam_count_before,
        "seam_count_after": sum(bool(edge.seam) for edge in bm.edges),
        "mesh_counts_after": _mesh_counts(bm), "selection_changed": False,
        "topology_changed": False, "uv_coordinates_changed": False,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "mesh.create",
        create_mesh,
        permissions=(Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS),
        toolset="mesh",
        modifies=True,
        description="Create a fully prevalidated arbitrary mesh object from bounded topology arrays.",
    )
    registry.register(
        "mesh.inspect",
        inspect_mesh,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="mesh",
        description="Inspect compact mesh topology and diagnostics.",
    )
    common = {
        "permissions": (Permission.EDIT_MESH,),
        "toolset": "mesh",
        "modifies": True,
    }
    registry.register("mesh.recalculate_normals", recalculate_normals, description="Recalculate selected or all mesh face normals.", **common)
    registry.register("mesh.delete_selected", delete_selected, description="Delete selected vertices, edges, or faces.", **common)
    registry.register("mesh.dissolve_selected", dissolve_selected, description="Dissolve selected faces, edges, or vertices.", **common)
    registry.register("mesh.extrude_selected", extrude_selected, description="Extrude the selected face region by an explicit offset.", **common)
    registry.register("mesh.inset_selected", inset_selected, description="Inset selected faces using a deterministic thickness and depth.", **common)
    registry.register("mesh.bevel_selected", bevel_selected, description="Bevel selected edges or vertices.", **common)
    registry.register("mesh.mark_seams", mark_seams, description="Mark or clear UV seams on selected edges of one local single-user Edit Mode mesh.", **common)
