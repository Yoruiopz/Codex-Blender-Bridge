"""Selection-scoped mesh editing implemented with :mod:`bmesh`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..mesh_inspector import inspect_mesh_object
from ..permissions import Permission
from ..selection import clear_selection_references, validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, get_object, int_param, vector3

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

_MAX_OPERATION_ELEMENTS = 100_000
_MAX_BEVEL_COMPLEXITY = 500_000


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


def register_tools(registry: ToolRegistry) -> None:
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
