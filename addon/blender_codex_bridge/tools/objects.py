"""Deterministic object lifecycle, hierarchy, and collection tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import clear_selection_references
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_collection, get_object, require_blender, serialize_transform, vector3

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore


_MESH_TYPES = {"MESH", "CUBE", "PLANE", "UV_SPHERE", "ICOSPHERE", "CYLINDER", "CONE"}


def _create_mesh_data(bpy: Any, object_type: str, name: str) -> Any:
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    if object_type == "MESH":
        return mesh
    if bmesh is None:
        bpy.data.meshes.remove(mesh)
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    bm = bmesh.new()
    try:
        if object_type == "CUBE":
            bmesh.ops.create_cube(bm, size=2.0)
        elif object_type == "PLANE":
            bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
        elif object_type == "UV_SPHERE":
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
        elif object_type == "ICOSPHERE":
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        elif object_type == "CYLINDER":
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=32, radius1=1.0, radius2=1.0, depth=2.0
            )
        elif object_type == "CONE":
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=32, radius1=1.0, radius2=0.0, depth=2.0
            )
        bm.to_mesh(mesh)
        mesh.update()
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise
    finally:
        bm.free()
    return mesh


def create_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    raw_type = params.get("object_type", "EMPTY")
    if not isinstance(raw_type, str):
        raise invalid_argument("'object_type' must be a string.")
    object_type = raw_type.strip().upper().replace(" ", "_")
    supported = sorted({*_MESH_TYPES, "EMPTY", "CAMERA", "LIGHT"})
    if object_type not in supported:
        raise invalid_argument("Unsupported object type.", object_type=object_type, supported=supported)
    name = params.get("name", f"Codex {object_type.title()}")
    if not isinstance(name, str) or not name.strip():
        raise invalid_argument("'name' must be a non-empty string.")
    name = name.strip()[:63]
    collection_name = params.get("collection")
    if collection_name is not None and not isinstance(collection_name, str):
        raise invalid_argument("'collection' must be a string.")
    collection = get_collection(collection_name)
    location = vector3(params.get("location"), "location", default=(0.0, 0.0, 0.0))
    rotation = vector3(params.get("rotation"), "rotation", default=(0.0, 0.0, 0.0))
    scale = vector3(params.get("scale"), "scale", default=(1.0, 1.0, 1.0))
    light_type = str(params.get("light_type", "POINT")).upper()
    if object_type == "LIGHT" and light_type not in {"POINT", "SUN", "SPOT", "AREA"}:
        raise invalid_argument("Unsupported light type.", supported=["POINT", "SUN", "SPOT", "AREA"])
    data = None
    try:
        if object_type in _MESH_TYPES:
            data = _create_mesh_data(bpy, object_type, name)
            obj = bpy.data.objects.new(name, data)
        elif object_type == "CAMERA":
            data = bpy.data.cameras.new(f"{name}Camera")
            obj = bpy.data.objects.new(name, data)
        elif object_type == "LIGHT":
            data = bpy.data.lights.new(f"{name}Light", light_type)
            obj = bpy.data.objects.new(name, data)
        else:
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_type = "PLAIN_AXES"
    except Exception:
        if data is not None and data.users == 0:
            bpy.data.batch_remove(ids=(data,))
        raise
    try:
        collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = rotation
        obj.scale = scale
    except Exception:
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if object_type in _MESH_TYPES:
                bpy.data.meshes.remove(data)
            elif object_type == "CAMERA":
                bpy.data.cameras.remove(data)
            elif object_type == "LIGHT":
                bpy.data.lights.remove(data)
        raise
    return {
        "created": True,
        "object": obj.name,
        "type": obj.type,
        "source_primitive": object_type,
        "collections": [item.name for item in obj.users_collection],
        "transform": serialize_transform(obj),
    }


def delete_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    name = obj.name
    data = obj.data
    clear_selection_references(name)
    bpy.data.objects.remove(obj, do_unlink=True)
    # Do not delete shared data; unused datablocks remain recoverable via undo.
    return {"deleted": True, "object": name, "data_name": data.name if data else None}


def duplicate_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    linked = params.get("linked", False)
    if not isinstance(linked, bool):
        raise invalid_argument("'linked' must be a boolean.")
    new_name = params.get("new_name")
    if new_name is not None:
        if not isinstance(new_name, str) or not new_name.strip():
            raise invalid_argument("'new_name' must be a non-empty string.")
        new_name = new_name.strip()[:63]
        existing = require_blender().data.objects.get(new_name)
        if existing is not None:
            raise invalid_argument(f"An object named '{new_name}' already exists.")
    collections = list(obj.users_collection) or [get_collection()]
    duplicate = obj.copy()
    copied_data = None
    try:
        if obj.data is not None and not linked:
            copied_data = obj.data.copy()
            duplicate.data = copied_data
        if new_name is not None:
            duplicate.name = new_name
        for collection in collections:
            collection.objects.link(duplicate)
    except Exception:
        require_blender().data.objects.remove(duplicate, do_unlink=True)
        if copied_data is not None and copied_data.users == 0:
            require_blender().data.batch_remove(ids=(copied_data,))
        raise
    return {
        "duplicated": True,
        "source_object": obj.name,
        "object": duplicate.name,
        "linked_data": linked,
        "collections": [item.name for item in duplicate.users_collection],
        "transform": serialize_transform(duplicate),
    }


def rename_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    obj = get_object(params.get("object_name"), allow_active=False)
    new_name = params.get("new_name")
    if not isinstance(new_name, str) or not new_name.strip():
        raise invalid_argument("'new_name' must be a non-empty string.")
    new_name = new_name.strip()[:63]
    collision = bpy.data.objects.get(new_name)
    if collision is not None and collision != obj:
        raise invalid_argument(f"An object named '{new_name}' already exists.")
    old_name = obj.name
    clear_selection_references(old_name)
    obj.name = new_name
    return {"renamed": True, "old_name": old_name, "object": obj.name}


def set_parent(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    parent_name = params.get("parent_name")
    if parent_name is not None and (
        not isinstance(parent_name, str) or not parent_name.strip()
    ):
        raise invalid_argument("'parent_name' must be a non-empty string or null.")
    parent = get_object(parent_name, allow_active=False) if parent_name is not None else None
    if parent == obj or (parent is not None and parent in obj.children_recursive):
        raise invalid_argument("Parenting would create an object hierarchy cycle.")
    keep_transform = params.get("keep_transform", True)
    if not isinstance(keep_transform, bool):
        raise invalid_argument("'keep_transform' must be a boolean.")
    world_matrix = obj.matrix_world.copy()
    obj.parent = parent
    if keep_transform:
        obj.matrix_world = world_matrix
    return {
        "object": obj.name,
        "parent": parent.name if parent else None,
        "kept_world_transform": keep_transform,
        "transform": serialize_transform(obj),
    }


def move_to_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(params.get("object_name"), allow_active=False)
    collection_name = params.get("collection_name")
    if not isinstance(collection_name, str) or not collection_name.strip():
        raise invalid_argument("'collection_name' must be a non-empty string.")
    target = get_collection(collection_name)
    link_only = params.get("link_only", False)
    if not isinstance(link_only, bool):
        raise invalid_argument("'link_only' must be a boolean.")
    if target not in obj.users_collection:
        target.objects.link(obj)
    if not link_only:
        for collection in list(obj.users_collection):
            if collection != target:
                collection.objects.unlink(obj)
    return {
        "object": obj.name,
        "collections": [item.name for item in obj.users_collection],
        "linked_only": link_only,
    }


def register_tools(registry: ToolRegistry) -> None:
    common = {
        "permissions": (Permission.TRANSFORM_OBJECTS,),
        "toolset": "objects",
        "modifies": True,
    }
    registry.register("object.create", create_object, description="Create a supported Blender object or mesh primitive.", **common)
    registry.register(
        "object.delete",
        delete_object,
        permissions=(Permission.DELETE_OBJECTS,),
        toolset="objects",
        modifies=True,
        description="Delete one named object after Blender-side permission approval.",
    )
    registry.register("object.duplicate", duplicate_object, description="Duplicate one object, linked or with copied data.", **common)
    registry.register("object.rename", rename_object, description="Rename one object without name collisions.", **common)
    registry.register("object.set_parent", set_parent, description="Set or clear an object's parent while optionally preserving its world transform.", **common)
    registry.register("object.move_to_collection", move_to_collection, description="Link or move an object to an existing collection.", **common)
