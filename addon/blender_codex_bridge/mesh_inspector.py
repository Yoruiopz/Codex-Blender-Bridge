"""Compact mesh diagnostics that avoid returning raw vertex arrays."""

from __future__ import annotations

from typing import Any

from .errors import BridgeError, ErrorCode

try:  # Import safe outside Blender.
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore


def basic_mesh_statistics(mesh: Any) -> dict[str, int]:
    polygons = len(mesh.polygons)
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "polygons": polygons,
        "triangles_estimate": sum(max(0, len(polygon.vertices) - 2) for polygon in mesh.polygons),
        "ngons": sum(len(polygon.vertices) > 4 for polygon in mesh.polygons),
    }


def _topology_statistics(obj: Any) -> dict[str, Any]:
    if bmesh is None:
        return {"available": False, "reason": "bmesh is unavailable"}
    mesh = obj.data
    owns_bmesh = obj.mode != "EDIT"
    bm = bmesh.new() if owns_bmesh else bmesh.from_edit_mesh(mesh)
    try:
        if owns_bmesh:
            bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return {
            "available": True,
            "loose_vertices": sum(not vertex.link_edges for vertex in bm.verts),
            "boundary_edges": sum(edge.is_boundary for edge in bm.edges),
            "non_manifold_edges": sum(not edge.is_manifold for edge in bm.edges),
            "wire_edges": sum(edge.is_wire for edge in bm.edges),
            "degenerate_faces": sum(face.calc_area() <= 1.0e-12 for face in bm.faces),
        }
    finally:
        if owns_bmesh:
            bm.free()


def inspect_mesh_object(obj: Any, *, include_topology: bool = True) -> dict[str, Any]:
    """Return useful bounded diagnostics for one mesh object."""

    if getattr(obj, "type", None) != "MESH":
        raise BridgeError(
            ErrorCode.INVALID_ARGUMENT,
            f"Object '{getattr(obj, 'name', '<unknown>')}' is not a mesh.",
            {"object_type": getattr(obj, "type", None)},
        )
    mesh = obj.data
    scale = tuple(float(value) for value in obj.scale)
    result: dict[str, Any] = {
        **basic_mesh_statistics(mesh),
        "mesh_data_name": mesh.name,
        "users": int(mesh.users),
        "material_slots": [slot.material.name if slot.material else None for slot in obj.material_slots],
        "uv_layers": [
            {
                "name": layer.name,
                "active": mesh.uv_layers.active == layer,
                "active_render": bool(getattr(layer, "active_render", False)),
            }
            for layer in mesh.uv_layers
        ],
        "shape_keys": (
            [block.name for block in mesh.shape_keys.key_blocks]
            if getattr(mesh, "shape_keys", None)
            else []
        ),
        "modifiers": [
            {"name": modifier.name, "type": modifier.type, "show_viewport": modifier.show_viewport}
            for modifier in obj.modifiers
        ],
        "dimensions": [float(value) for value in obj.dimensions],
        "scale": list(scale),
        "unapplied_scale": any(abs(value - 1.0) > 1.0e-5 for value in scale),
        "negative_scale": obj.matrix_world.to_3x3().determinant() < 0.0,
        "has_custom_normals": bool(getattr(mesh, "has_custom_normals", False)),
    }
    if include_topology:
        result["topology"] = _topology_statistics(obj)
    return result
