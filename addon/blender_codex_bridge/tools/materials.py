"""Bounded material/node graph structural inspection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..serialization import to_jsonable
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, require_blender, similar_names

_KEY_NODE_TYPES = {
    "BSDF_PRINCIPLED",
    "OUTPUT_MATERIAL",
    "TEX_IMAGE",
    "NORMAL_MAP",
    "BUMP",
    "MAPPING",
    "TEX_COORD",
    "MIX_SHADER",
    "ADD_SHADER",
    "GROUP",
}
_PRINCIPLED_INPUTS = {
    "Base Color",
    "Metallic",
    "Roughness",
    "IOR",
    "Alpha",
    "Normal",
    "Emission Color",
    "Emission Strength",
    "Coat Weight",
}
_MAX_MATERIALS = 200
_MAX_MATERIAL_USERS = 100
_MAX_KEY_NODES = 200
_MAX_TEXTURES = 100
_MAX_LINKS = 500


def _value(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [float(item) if isinstance(item, (int, float)) else to_jsonable(item) for item in value]
    if not isinstance(value, (str, bytes)) and hasattr(value, "__len__") and hasattr(value, "__getitem__"):
        try:
            return [
                float(value[index])
                if isinstance(value[index], (int, float))
                else to_jsonable(value[index])
                for index in range(len(value))
            ]
        except (IndexError, TypeError, ValueError):
            pass
    try:
        return to_jsonable(value)
    except (TypeError, ValueError):
        return repr(value)


def _node(node: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": node.name,
        "label": node.label,
        "type": node.type,
        "bl_idname": node.bl_idname,
        "muted": bool(node.mute),
        "inputs": {},
    }
    if node.type == "BSDF_PRINCIPLED":
        result["inputs"] = {
            socket.name: _value(socket.default_value)
            for socket in node.inputs
            if socket.name in _PRINCIPLED_INPUTS and hasattr(socket, "default_value")
        }
    if node.type == "TEX_IMAGE":
        image = node.image
        result["image"] = (
            {
                "name": image.name,
                "filepath": image.filepath,
                "source": image.source,
                "colorspace": image.colorspace_settings.name,
                "packed": image.packed_file is not None,
            }
            if image
            else None
        )
        result["interpolation"] = node.interpolation
        result["projection"] = node.projection
    if node.type == "GROUP" and node.node_tree:
        result["node_tree"] = node.node_tree.name
    return result


def _material_usage(bpy: Any, material_names: set[str]) -> dict[str, dict[str, Any]]:
    """Build all requested material users in one object/slot traversal."""

    usage = {
        name: {"objects": [], "object_count": 0, "objects_truncated": False}
        for name in material_names
    }
    for obj in bpy.data.objects:
        matched: set[str] = set()
        for slot in obj.material_slots:
            material = slot.material
            if material is not None and material.name in material_names:
                matched.add(material.name)
        for name in matched:
            entry = usage[name]
            entry["object_count"] += 1
            if len(entry["objects"]) < _MAX_MATERIAL_USERS:
                entry["objects"].append(obj.name)
            else:
                entry["objects_truncated"] = True
    for entry in usage.values():
        entry["objects"].sort()
    return usage


def _inspect_material(material: Any, usage: Mapping[str, Any]) -> dict[str, Any]:
    users = usage[material.name]
    result: dict[str, Any] = {
        "name": material.name,
        "use_nodes": bool(material.use_nodes),
        **users,
        "diffuse_color": [float(value) for value in material.diffuse_color],
        "blend_method": getattr(material, "surface_render_method", None),
    }
    tree = material.node_tree if material.use_nodes else None
    if tree is None:
        result.update({"node_tree": None, "key_nodes": [], "textures": [], "links": []})
        return result
    key_nodes: list[dict[str, Any]] = []
    textures: list[dict[str, Any]] = []
    key_node_count = 0
    texture_count = 0
    for node in tree.nodes:
        if node.type in _KEY_NODE_TYPES:
            key_node_count += 1
            if len(key_nodes) < _MAX_KEY_NODES:
                key_nodes.append(_node(node))
        if node.type == "TEX_IMAGE" and node.image is not None:
            texture_count += 1
            if len(textures) < _MAX_TEXTURES:
                textures.append(_node(node)["image"])
    links = [
        {
            "from_node": link.from_node.name,
            "from_socket": link.from_socket.name,
            "to_node": link.to_node.name,
            "to_socket": link.to_socket.name,
        }
        for link in islice(tree.links, _MAX_LINKS)
    ]
    result.update(
        {
            "node_tree": tree.name,
            "node_count": len(tree.nodes),
            "key_nodes": key_nodes,
            "key_node_count": key_node_count,
            "textures": textures,
            "texture_count": texture_count,
            "links": links,
            "link_count": len(tree.links),
            "truncated_fields": {
                "key_nodes": key_node_count > len(key_nodes),
                "textures": texture_count > len(textures),
                "links": len(tree.links) > len(links),
            },
        }
    )
    return result


def inspect_material(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    material_name = params.get("material_name")
    object_name = params.get("object_name")
    if material_name is not None and not isinstance(material_name, str):
        raise invalid_argument("'material_name' must be a string.")
    if object_name is not None and not isinstance(object_name, str):
        raise invalid_argument("'object_name' must be a string.")
    if material_name:
        material = bpy.data.materials.get(material_name)
        if material is None:
            raise BridgeError(
                ErrorCode.MATERIAL_NOT_FOUND,
                f"Material '{material_name}' does not exist.",
                {"available_similar_materials": similar_names(material_name, bpy.data.materials.keys())},
            )
        materials = [material]
        material_count = 1
        materials_truncated = False
    elif object_name:
        obj = get_object(object_name)
        materials = []
        seen: set[str] = set()
        materials_truncated = False
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.name in seen:
                continue
            seen.add(material.name)
            if len(materials) >= _MAX_MATERIALS:
                materials_truncated = True
                break
            materials.append(material)
        material_count = len(materials) + int(materials_truncated)
    else:
        material_count = len(bpy.data.materials)
        materials = list(islice(bpy.data.materials, _MAX_MATERIALS))
        materials_truncated = material_count > len(materials)
    usage = _material_usage(bpy, {material.name for material in materials})
    return {
        "materials": [_inspect_material(material, usage) for material in materials],
        "material_count": material_count,
        "material_count_is_lower_bound": bool(object_name and materials_truncated),
        "truncated": materials_truncated,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "material.inspect",
        inspect_material,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="materials",
        description="Inspect materials, important shader nodes, texture images, and usage.",
    )
