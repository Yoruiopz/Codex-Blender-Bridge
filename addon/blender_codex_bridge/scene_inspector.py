"""Authoritative, bounded project/scene/object structural inspection."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import islice
from typing import Any

from .errors import BridgeError, ErrorCode
from .mesh_inspector import basic_mesh_statistics, inspect_mesh_object
from .utils import bool_param, get_object, int_param, object_identifier, require_blender

_MAX_OBJECT_CHILDREN = 100
_MAX_OBJECT_COLLECTIONS = 50
_MAX_MATERIAL_SLOTS = 100
_MAX_MODIFIERS = 100
_MAX_CONSTRAINTS = 100


def _world_bounding_box(obj: Any) -> dict[str, Any] | None:
    corners = getattr(obj, "bound_box", None)
    if not corners or len(corners) != 8:
        return None
    try:
        world_corners = [obj.matrix_world @ __import__("mathutils").Vector(corner) for corner in corners]
    except (AttributeError, TypeError, ValueError):
        return None
    minimum = [min(corner[index] for corner in world_corners) for index in range(3)]
    maximum = [max(corner[index] for corner in world_corners) for index in range(3)]
    return {
        "min": [float(value) for value in minimum],
        "max": [float(value) for value in maximum],
        "center": [float((minimum[index] + maximum[index]) * 0.5) for index in range(3)],
        "corners": [[float(value) for value in corner] for corner in world_corners],
    }


def _object_compact(obj: Any, active: Any) -> dict[str, Any]:
    try:
        visible_viewport = bool(obj.visible_get())
    except (RuntimeError, TypeError):
        visible_viewport = not bool(obj.hide_viewport)
    children = [child.name for child in islice(obj.children, _MAX_OBJECT_CHILDREN)]
    collections = [
        collection.name for collection in islice(obj.users_collection, _MAX_OBJECT_COLLECTIONS)
    ]
    material_slots = [
        slot.material.name if slot.material else None
        for slot in islice(obj.material_slots, _MAX_MATERIAL_SLOTS)
    ]
    modifiers = [
        {"name": modifier.name, "type": modifier.type}
        for modifier in islice(obj.modifiers, _MAX_MODIFIERS)
    ]
    constraints = [
        {"name": constraint.name, "type": constraint.type}
        for constraint in islice(obj.constraints, _MAX_CONSTRAINTS)
    ]
    rotation_euler = [float(component) for component in obj.rotation_euler]
    rotation_quaternion = [float(component) for component in obj.rotation_quaternion]
    rotation_axis_angle = [float(component) for component in obj.rotation_axis_angle]
    if obj.rotation_mode == "QUATERNION":
        active_rotation = {"representation": "quaternion", "value": rotation_quaternion}
    elif obj.rotation_mode == "AXIS_ANGLE":
        active_rotation = {"representation": "axis_angle", "value": rotation_axis_angle}
    else:
        active_rotation = {"representation": "euler", "value": rotation_euler}
    value: dict[str, Any] = {
        "name": obj.name,
        "id": object_identifier(obj),
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "children": children,
        "collections": collections,
        "location": [float(component) for component in obj.location],
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": rotation_euler,
        "rotation_quaternion": rotation_quaternion,
        "rotation_axis_angle": rotation_axis_angle,
        "active_rotation": active_rotation,
        "scale": [float(component) for component in obj.scale],
        "dimensions": [float(component) for component in obj.dimensions],
        "world_bounding_box": _world_bounding_box(obj),
        "matrix_world": [[float(component) for component in row] for row in obj.matrix_world],
        "visible_viewport": visible_viewport,
        "hidden_viewport": bool(obj.hide_viewport),
        "visible_render": not bool(obj.hide_render),
        "selected": bool(obj.select_get()),
        "active": obj == active,
        "material_slots": material_slots,
        "modifiers": modifiers,
        "constraints": constraints,
        "truncated_fields": {
            "children": len(obj.children) > len(children),
            "collections": len(obj.users_collection) > len(collections),
            "material_slots": len(obj.material_slots) > len(material_slots),
            "modifiers": len(obj.modifiers) > len(modifiers),
            "constraints": len(obj.constraints) > len(constraints),
        },
    }
    if obj.type == "MESH":
        value["mesh"] = basic_mesh_statistics(obj.data)
    return value


def _collection_tree(
    collection: Any,
    *,
    budget: dict[str, Any],
    maximum_object_names: int,
    depth: int,
    maximum_depth: int,
) -> dict[str, Any]:
    """Return a collection node without allowing hierarchy fan-out to explode."""

    budget["remaining"] -= 1
    budget["visited"] += 1
    object_count = len(collection.objects)
    objects = [obj.name for obj in islice(collection.objects, maximum_object_names)]
    children: list[dict[str, Any]] = []
    child_count = len(collection.children)
    children_truncated = False
    if depth >= maximum_depth - 1:
        children_truncated = child_count > 0
    else:
        for child in collection.children:
            if budget["remaining"] <= 0:
                children_truncated = True
                break
            children.append(
                _collection_tree(
                    child,
                    budget=budget,
                    maximum_object_names=maximum_object_names,
                    depth=depth + 1,
                    maximum_depth=maximum_depth,
                )
            )
    if children_truncated:
        budget["truncated"] = True
    return {
        "name": collection.name,
        "objects": objects,
        "object_count": object_count,
        "objects_truncated": object_count > len(objects),
        "children": children,
        "child_collection_count": child_count,
        "children_truncated": children_truncated or child_count > len(children),
    }


def project_info(params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del params
    bpy = require_blender()
    scene = bpy.context.scene
    render = scene.render
    return {
        "filepath": bpy.data.filepath,
        "is_saved": bool(bpy.data.filepath),
        "is_dirty": bool(bpy.data.is_dirty),
        "scenes": [item.name for item in bpy.data.scenes],
        "current_scene": scene.name,
        "frame_range": {"start": scene.frame_start, "end": scene.frame_end, "current": scene.frame_current},
        "render_engine": scene.render.engine,
        "resolution": {
            "x": render.resolution_x,
            "y": render.resolution_y,
            "percentage": render.resolution_percentage,
        },
        "fps": float(render.fps) / float(render.fps_base),
        "blender_version": bpy.app.version_string,
    }


def inspect_scene(params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    bpy = require_blender()
    params = params or {}
    include_hidden = bool_param(params, "include_hidden", False)
    max_objects = int_param(params, "max_objects", 500, minimum=1, maximum=5_000)
    max_collections = int_param(params, "max_collections", 500, minimum=1, maximum=5_000)
    max_collection_objects = int_param(
        params, "max_collection_objects", 100, minimum=1, maximum=1_000
    )
    max_collection_depth = int_param(
        params, "max_collection_depth", 12, minimum=1, maximum=32
    )
    scene = bpy.context.scene
    active = bpy.context.view_layer.objects.active
    objects: list[dict[str, Any]] = []
    eligible_count = 0
    for obj in scene.objects:
        if not include_hidden:
            try:
                hidden = bool(obj.hide_viewport or obj.hide_get())
            except (RuntimeError, TypeError):
                hidden = bool(obj.hide_viewport)
            if hidden:
                continue
        eligible_count += 1
        if len(objects) < max_objects:
            objects.append(_object_compact(obj, active))
    selected = [obj.name for obj in bpy.context.selected_objects]
    collection_budget: dict[str, Any] = {
        "remaining": max_collections,
        "visited": 0,
        "truncated": False,
    }
    collections: list[dict[str, Any]] = []
    for collection in scene.collection.children:
        if collection_budget["remaining"] <= 0:
            collection_budget["truncated"] = True
            break
        collections.append(
            _collection_tree(
                collection,
                budget=collection_budget,
                maximum_object_names=max_collection_objects,
                depth=0,
                maximum_depth=max_collection_depth,
            )
        )
    root_object_count = len(scene.collection.objects)
    root_objects = [
        obj.name for obj in islice(scene.collection.objects, max_collection_objects)
    ]
    return {
        "scene": scene.name,
        "mode": bpy.context.mode,
        "frame": scene.frame_current,
        "active_object": active.name if active else None,
        "active_camera": scene.camera.name if scene.camera else None,
        "selected_objects": selected,
        "world": scene.world.name if scene.world else None,
        "collections": collections,
        "collection_count_returned": collection_budget["visited"],
        "collections_truncated": bool(collection_budget["truncated"]),
        "maximum_collections": max_collections,
        "maximum_collection_depth": max_collection_depth,
        "root_collection_objects": root_objects,
        "root_collection_object_count": root_object_count,
        "root_collection_objects_truncated": root_object_count > len(root_objects),
        "objects": objects,
        "object_count": eligible_count,
        "truncated": eligible_count > len(objects),
        "maximum_objects": max_objects,
    }


def scene_summary(params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    bpy = require_blender()
    params = params or {}
    include_hidden = bool_param(params, "include_hidden", False)
    max_collections = int_param(params, "max_collections", 100, minimum=1, maximum=500)
    max_objects_per_collection = int_param(
        params, "max_objects_per_collection", 100, minimum=1, maximum=500
    )
    scene = bpy.context.scene
    active = bpy.context.view_layer.objects.active
    collections: list[dict[str, Any]] = []
    lines = [f"Scene: {scene.name}", "", "Collections:"]
    top_level_count = len(scene.collection.children)
    for collection in islice(scene.collection.children, max_collections):
        names: list[str] = []
        names_truncated = False
        for obj in collection.all_objects:
            if not include_hidden and (obj.hide_viewport or obj.hide_get()):
                continue
            if len(names) >= max_objects_per_collection:
                names_truncated = True
                break
            names.append(obj.name)
        collections.append(
            {
                "name": collection.name,
                "objects": names,
                "objects_truncated": names_truncated,
            }
        )
        lines.append(f"- {collection.name}")
        lines.extend(f"  - {name}" for name in names)
        if names_truncated:
            lines.append("  - ... additional objects omitted")
    collections_truncated = top_level_count > len(collections)
    if collections_truncated:
        lines.append("- ... additional collections omitted")
    selected = [obj.name for obj in bpy.context.selected_objects]
    lines.extend(
        [
            "",
            f"Active object: {active.name if active else 'None'}",
            f"Mode: {bpy.context.mode}",
            f"Selected: {', '.join(selected) if selected else 'None'}",
        ]
    )
    by_type: dict[str, int] = {}
    for obj in scene.objects:
        by_type[obj.type] = by_type.get(obj.type, 0) + 1
    return {
        "text": "\n".join(lines),
        "scene": scene.name,
        "collections": collections,
        "collection_count": top_level_count,
        "collections_truncated": collections_truncated,
        "active_object": active.name if active else None,
        "mode": bpy.context.mode,
        "selected_objects": selected,
        "object_counts_by_type": dict(sorted(by_type.items())),
    }


def inspect_object(params: Mapping[str, Any] | str | None = None) -> dict[str, Any]:
    if isinstance(params, str):
        object_name = params
        include_topology = True
    else:
        values = params or {}
        object_name = values.get("object_name")
        if object_name is not None and not isinstance(object_name, str):
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "'object_name' must be a string.")
        include_topology = bool_param(values, "include_topology", True)
    obj = get_object(object_name)
    bpy = require_blender()
    active = bpy.context.view_layer.objects.active
    result = _object_compact(obj, active)
    result.update(
        {
            "data_name": obj.data.name if obj.data else None,
            "library": obj.library.filepath if obj.library else None,
            "instance_type": obj.instance_type,
            "display_type": obj.display_type,
        }
    )
    if obj.type == "MESH":
        result["mesh"] = inspect_mesh_object(obj, include_topology=include_topology)
    return result
