"""Bounded material inspection and deterministic material-slot editing."""

from __future__ import annotations

import math
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
    "Emission",
    "Emission Color",
    "Emission Strength",
    "Clearcoat",
    "Coat Weight",
}
_PRINCIPLED_ALIASES: dict[str, tuple[str, ...]] = {
    "base_color": ("Base Color",),
    "metallic": ("Metallic",),
    "roughness": ("Roughness",),
    "ior": ("IOR",),
    "alpha": ("Alpha",),
    "emission_color": ("Emission Color", "Emission"),
    "emission_strength": ("Emission Strength",),
    "coat_weight": ("Coat Weight", "Clearcoat"),
}
_MAX_MATERIALS = 200
_MAX_MATERIAL_USERS = 100
_MAX_KEY_NODES = 200
_MAX_TEXTURES = 100
_MAX_LINKS = 500
_MAX_NAME_BYTES = 63


def _value(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            float(item) if isinstance(item, (int, float)) else to_jsonable(item)
            for item in value
        ]
    if (
        not isinstance(value, (str, bytes))
        and hasattr(value, "__len__")
        and hasattr(value, "__getitem__")
    ):
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


def _required_name(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument(
            f"'{key}' must be a non-empty string.",
            parameter=key,
        )
    if len(value.encode("utf-8")) > _MAX_NAME_BYTES:
        raise invalid_argument(
            f"'{key}' must be at most {_MAX_NAME_BYTES} UTF-8 bytes.",
            parameter=key,
        )
    return value


def _material_exact(name: str) -> Any:
    bpy = require_blender()
    material = bpy.data.materials.get(name)
    if material is None:
        raise BridgeError(
            ErrorCode.MATERIAL_NOT_FOUND,
            f"Material '{name}' does not exist.",
            {"available_similar_materials": similar_names(name, bpy.data.materials.keys())},
        )
    return material


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


def _object_materials(obj: Any) -> Any:
    data = getattr(obj, "data", None)
    materials = getattr(data, "materials", None)
    if materials is None:
        raise invalid_argument(
            f"Object '{obj.name}' does not support material slots.",
            object_name=obj.name,
            object_type=getattr(obj, "type", None),
        )
    return materials


def _slot_state(obj: Any) -> dict[str, Any]:
    materials = _object_materials(obj)
    slots = [
        {
            "index": index,
            "material": slot.material.name if slot.material is not None else None,
            "link": getattr(slot, "link", "DATA"),
        }
        for index, slot in islice(enumerate(obj.material_slots), len(materials))
    ]
    return {
        "object": obj.name,
        "active_slot_index": int(getattr(obj, "active_material_index", 0)),
        "slot_count": len(slots),
        "slots": slots,
    }


def _slot_index(params: Mapping[str, Any], *, maximum: int, required: bool = True) -> int | None:
    value = params.get("slot_index")
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_argument("'slot_index' must be an integer.", parameter="slot_index")
    if maximum < 0:
        raise invalid_argument(
            "The object has no material slots.",
            parameter="slot_index",
            slot_count=0,
        )
    if value < 0 or value > maximum:
        raise invalid_argument(
            "'slot_index' is outside the object's material-slot range.",
            parameter="slot_index",
            minimum=0,
            maximum=maximum,
            actual=value,
        )
    return value


def _finite_number(value: Any, name: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_argument(f"'{name}' must be a number.", parameter=name)
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(
            f"'{name}' must be a finite number.",
            parameter=name,
        ) from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise invalid_argument(
            f"'{name}' must be finite and between {minimum} and {maximum}.",
            parameter=name,
            minimum=minimum,
            maximum=maximum,
        )
    return result


def _color(value: Any, name: str) -> list[float]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) not in {3, 4}
    ):
        raise invalid_argument(
            f"'{name}' must contain three or four numbers from 0 to 1.",
            parameter=name,
        )
    result = [
        _finite_number(component, name, minimum=0.0, maximum=1.0)
        for component in value
    ]
    if len(result) == 3:
        result.append(1.0)
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
        material = _material_exact(material_name)
        materials = [material]
        material_count = 1
        materials_truncated = False
    elif object_name:
        obj = get_object(object_name, allow_active=False)
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


def create_material(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    name = _required_name(params, "name")
    if bpy.data.materials.get(name) is not None:
        raise invalid_argument(f"A material named '{name}' already exists.", material_name=name)
    use_nodes = params.get("use_nodes", True)
    if not isinstance(use_nodes, bool):
        raise invalid_argument("'use_nodes' must be a boolean.", parameter="use_nodes")
    diffuse = params.get("diffuse_color")
    material = bpy.data.materials.new(name=name)
    try:
        material.use_nodes = use_nodes
        if diffuse is not None:
            material.diffuse_color = _color(diffuse, "diffuse_color")
    except Exception:
        bpy.data.materials.remove(material)
        raise
    usage = {material.name: {"objects": [], "object_count": 0, "objects_truncated": False}}
    return {"created": True, "material": _inspect_material(material, usage)}


def delete_material(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    material = _material_exact(_required_name(params, "material_name"))
    only_if_unused = params.get("only_if_unused", True)
    if not isinstance(only_if_unused, bool):
        raise invalid_argument("'only_if_unused' must be a boolean.", parameter="only_if_unused")
    usage = _material_usage(bpy, {material.name})[material.name]
    if only_if_unused and int(material.users) > 0:
        raise invalid_argument(
            f"Material '{material.name}' still has users.",
            material_name=material.name,
            users=int(material.users),
            object_users=usage["objects"],
            object_users_truncated=usage["objects_truncated"],
        )
    name = material.name
    affected_objects = list(usage["objects"])
    bpy.data.materials.remove(material, do_unlink=not only_if_unused)
    return {
        "deleted": True,
        "material": name,
        "forced_unlink": not only_if_unused,
        "affected_objects": affected_objects,
        "affected_objects_truncated": usage["objects_truncated"],
    }


def assign_material(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(_required_name(params, "object_name"), allow_active=False)
    material = _material_exact(_required_name(params, "material_name"))
    materials = _object_materials(obj)
    index = _slot_index(params, maximum=len(materials), required=False)
    if index is None:
        existing = next(
            (
                slot_index
                for slot_index, slot in enumerate(obj.material_slots)
                if slot.material == material
            ),
            None,
        )
        if existing is None:
            materials.append(material)
            index = len(materials) - 1
        else:
            index = existing
    elif index == len(materials):
        materials.append(material)
    else:
        obj.material_slots[index].material = material
    obj.active_material_index = index
    return {
        "assigned": True,
        "material": material.name,
        "slot_index": index,
        **_slot_state(obj),
    }


def unassign_material(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(_required_name(params, "object_name"), allow_active=False)
    materials = _object_materials(obj)
    index = _slot_index(params, maximum=len(materials) - 1)
    assert index is not None
    slot = obj.material_slots[index]
    previous = slot.material
    slot.material = None
    return {
        "unassigned": True,
        "previous_material": previous.name if previous is not None else None,
        "slot_index": index,
        **_slot_state(obj),
    }


def add_material_slot(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(_required_name(params, "object_name"), allow_active=False)
    material = _material_exact(_required_name(params, "material_name"))
    materials = _object_materials(obj)
    materials.append(material)
    index = len(materials) - 1
    obj.active_material_index = index
    return {
        "slot_added": True,
        "material": material.name,
        "slot_index": index,
        **_slot_state(obj),
    }


def remove_material_slot(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    obj = get_object(_required_name(params, "object_name"), allow_active=False)
    materials = _object_materials(obj)
    index = _slot_index(params, maximum=len(materials) - 1)
    assert index is not None
    previous = obj.material_slots[index].material
    materials.pop(index=index)
    return {
        "slot_removed": True,
        "removed_material": previous.name if previous is not None else None,
        "slot_index": index,
        **_slot_state(obj),
    }


def _principled_node(material: Any, node_name: str | None) -> Any:
    if not material.use_nodes or material.node_tree is None:
        raise invalid_argument(
            f"Material '{material.name}' does not use nodes.",
            material_name=material.name,
        )
    if node_name is not None:
        node = material.node_tree.nodes.get(node_name)
        if node is None or node.type != "BSDF_PRINCIPLED":
            raise invalid_argument(
                f"Principled BSDF node '{node_name}' does not exist in material '{material.name}'.",
                material_name=material.name,
                node_name=node_name,
            )
        return node
    matches = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
    if len(matches) != 1:
        raise invalid_argument(
            "'node_name' is required unless the material has exactly one Principled BSDF node.",
            material_name=material.name,
            principled_nodes=[node.name for node in matches[:20]],
            principled_nodes_truncated=len(matches) > 20,
        )
    return matches[0]


def _principled_socket(node: Any, names: tuple[str, ...]) -> Any:
    for socket_name in names:
        socket = node.inputs.get(socket_name)
        if socket is not None:
            return socket
    raise invalid_argument(
        f"Node '{node.name}' does not expose a compatible input.",
        node_name=node.name,
        expected_socket_names=list(names),
    )


def set_principled(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material = _material_exact(_required_name(params, "material_name"))
    raw_node_name = params.get("node_name")
    if raw_node_name is not None:
        raw_node_name = _required_name(params, "node_name")
    node = _principled_node(material, raw_node_name)
    changes: dict[str, Any] = {}
    color_fields = {"base_color", "emission_color"}
    scalar_ranges = {
        "metallic": (0.0, 1.0),
        "roughness": (0.0, 1.0),
        "ior": (1.0, 1000.0),
        "alpha": (0.0, 1.0),
        "emission_strength": (0.0, 1_000_000.0),
        "coat_weight": (0.0, 1.0),
    }
    pending: list[tuple[str, Any, Any]] = []
    for key, aliases in _PRINCIPLED_ALIASES.items():
        if key not in params or params[key] is None:
            continue
        raw_value = params[key]
        value = (
            _color(raw_value, key)
            if key in color_fields
            else _finite_number(
                raw_value,
                key,
                minimum=scalar_ranges[key][0],
                maximum=scalar_ranges[key][1],
            )
        )
        pending.append((key, _principled_socket(node, aliases), value))
    if not pending:
        raise invalid_argument(
            "At least one Principled setting must be provided.",
            supported=sorted(_PRINCIPLED_ALIASES),
        )
    for key, socket, value in pending:
        socket.default_value = value
        changes[key] = {"socket": socket.name, "value": _value(value)}
    return {
        "material": material.name,
        "node": node.name,
        "changed": changes,
        "principled": _node(node),
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "material.inspect",
        inspect_material,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="materials",
        description="Inspect materials, important shader nodes, texture images, and usage.",
    )
    common = {
        "permissions": (Permission.EDIT_MATERIALS,),
        "toolset": "materials",
        "modifies": True,
    }
    registry.register(
        "material.create",
        create_material,
        description="Create a named material with optional nodes and viewport color.",
        **common,
    )
    registry.register(
        "material.delete",
        delete_material,
        permissions=(Permission.EDIT_MATERIALS, Permission.DELETE_OBJECTS),
        toolset="materials",
        modifies=True,
        description="Delete one exact material, refusing active users unless forced.",
    )
    registry.register(
        "material.assign",
        assign_material,
        description="Assign a material to an exact object slot or append it.",
        **common,
    )
    registry.register(
        "material.unassign",
        unassign_material,
        description="Clear one exact object material slot without deleting it.",
        **common,
    )
    registry.register(
        "material.slot_add",
        add_material_slot,
        description="Append a material slot to one exact object.",
        **common,
    )
    registry.register(
        "material.slot_remove",
        remove_material_slot,
        description="Remove one exact object material slot.",
        **common,
    )
    registry.register(
        "material.set_principled",
        set_principled,
        description="Set validated common Principled BSDF inputs.",
        **common,
    )
