"""Typed, bounded editing for material shader node graphs."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..serialization import to_jsonable
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import int_param, require_blender, similar_names

_MAX_NAME_BYTES = 63
_MAX_SOCKET_NAME_BYTES = 256
_MAX_NODE_TYPE_LENGTH = 128
_MAX_LABEL_BYTES = 63
_MAX_NODES_LIMIT = 256
_MAX_LINKS_LIMIT = 1024
_MAX_SOCKETS_LIMIT = 64
_DEFAULT_MAX_NODES = 100
_DEFAULT_MAX_LINKS = 300
_DEFAULT_MAX_SOCKETS = 32
_MAX_TOTAL_INSPECTED_SOCKETS = 2048
_MAX_DEFAULT_VALUE_ITEMS = 64
_MAX_DEFAULT_STRING_LENGTH = 512
_NODE_TYPE_PATTERN = re.compile(r"^ShaderNode[A-Za-z0-9_]+$")


def _required_string(
    params: Mapping[str, Any],
    key: str,
    *,
    maximum: int = _MAX_NAME_BYTES,
) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument(f"'{key}' must be a non-empty string.", parameter=key)
    if len(value.encode("utf-8")) > maximum:
        raise invalid_argument(
            f"'{key}' must be at most {maximum} UTF-8 bytes.",
            parameter=key,
        )
    return value


def _optional_string(
    params: Mapping[str, Any], key: str, *, maximum: int = _MAX_NAME_BYTES
) -> str | None:
    if key not in params or params[key] is None:
        return None
    return _required_string(params, key, maximum=maximum)


def _material_graph(material_name: str) -> tuple[Any, Any]:
    bpy = require_blender()
    material = bpy.data.materials.get(material_name)
    if material is None:
        raise BridgeError(
            ErrorCode.MATERIAL_NOT_FOUND,
            f"Material '{material_name}' does not exist.",
            {
                "available_similar_materials": similar_names(
                    material_name, bpy.data.materials.keys()
                )
            },
        )
    if not material.use_nodes or material.node_tree is None:
        raise invalid_argument(
            f"Material '{material.name}' does not use nodes.",
            material_name=material.name,
        )
    return material, material.node_tree


def _node_exact(tree: Any, node_name: str) -> Any:
    node = tree.nodes.get(node_name)
    if node is None:
        raise invalid_argument(
            f"Node '{node_name}' does not exist in graph '{tree.name}'.",
            node_name=node_name,
            available_similar_nodes=similar_names(node_name, (item.name for item in tree.nodes)),
        )
    return node


def _finite_pair(value: Any, name: str) -> tuple[float, float]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 2
        or any(
            isinstance(component, bool) or not isinstance(component, (int, float))
            for component in value
        )
    ):
        raise invalid_argument(f"'{name}' must contain exactly two numbers.", parameter=name)
    try:
        result = (float(value[0]), float(value[1]))
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(
            f"'{name}' values must be finite and bounded.",
            parameter=name,
        ) from exc
    if not all(math.isfinite(component) and abs(component) <= 1_000_000 for component in result):
        raise invalid_argument(
            f"'{name}' values must be finite and no larger than 1000000 in magnitude.",
            parameter=name,
        )
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _json_value(bytes(value).decode("utf-8", errors="replace"))
    if isinstance(value, str):
        if len(value) <= _MAX_DEFAULT_STRING_LENGTH:
            return value
        return {
            "text": value[:_MAX_DEFAULT_STRING_LENGTH],
            "truncated": True,
            "original_length": len(value),
        }
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result = [
            _json_value(item)
            for item in value[:_MAX_DEFAULT_VALUE_ITEMS]
        ]
        if len(value) > _MAX_DEFAULT_VALUE_ITEMS:
            result.append({"truncated": True, "original_length": len(value)})
        return result
    if (
        not isinstance(value, (str, bytes))
        and hasattr(value, "__len__")
        and hasattr(value, "__getitem__")
    ):
        try:
            length = len(value)
            result = [
                _json_value(value[index])
                for index in range(min(length, _MAX_DEFAULT_VALUE_ITEMS))
            ]
            if length > _MAX_DEFAULT_VALUE_ITEMS:
                result.append({"truncated": True, "original_length": length})
            return result
        except (IndexError, TypeError, ValueError):
            pass
    converted = to_jsonable(value, max_depth=4, max_items=256)
    if isinstance(converted, str) and len(converted) > _MAX_DEFAULT_STRING_LENGTH:
        return {
            "text": converted[:_MAX_DEFAULT_STRING_LENGTH],
            "truncated": True,
            "original_length": len(converted),
        }
    return converted


def _socket_summary(socket: Any, index: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "index": index,
        "name": socket.name,
        "identifier": getattr(socket, "identifier", ""),
        "type": getattr(socket, "type", None),
        "bl_idname": getattr(socket, "bl_idname", None),
        "enabled": bool(getattr(socket, "enabled", True)),
        "linked": bool(getattr(socket, "is_linked", False)),
        "multi_input": bool(getattr(socket, "is_multi_input", False)),
    }
    if hasattr(socket, "default_value"):
        result["default_value"] = _json_value(socket.default_value)
    return result


def _node_summary(
    node: Any,
    *,
    max_sockets: int,
    socket_budget: int | None = None,
) -> dict[str, Any]:
    input_limit = max_sockets
    if socket_budget is not None:
        input_limit = min(input_limit, max(0, socket_budget))
    inputs = [
        _socket_summary(socket, index)
        for index, socket in enumerate(islice(node.inputs, input_limit))
    ]
    output_limit = max_sockets
    if socket_budget is not None:
        output_limit = min(output_limit, max(0, socket_budget - len(inputs)))
    outputs = [
        _socket_summary(socket, index)
        for index, socket in enumerate(islice(node.outputs, output_limit))
    ]
    return {
        "name": node.name,
        "label": node.label,
        "type": node.type,
        "bl_idname": node.bl_idname,
        "location": [float(component) for component in node.location],
        "dimensions": [float(component) for component in node.dimensions],
        "muted": bool(node.mute),
        "hidden": bool(node.hide),
        "input_count": len(node.inputs),
        "output_count": len(node.outputs),
        "inputs": inputs,
        "outputs": outputs,
        "truncated_fields": {
            "inputs": len(node.inputs) > len(inputs),
            "outputs": len(node.outputs) > len(outputs),
        },
    }


def _link_summary(link: Any) -> dict[str, Any]:
    return {
        "from_node": link.from_node.name,
        "from_socket": link.from_socket.name,
        "from_socket_identifier": getattr(link.from_socket, "identifier", ""),
        "to_node": link.to_node.name,
        "to_socket": link.to_socket.name,
        "to_socket_identifier": getattr(link.to_socket, "identifier", ""),
        "muted": bool(getattr(link, "is_muted", False)),
        "valid": bool(getattr(link, "is_valid", True)),
    }


def _graph_inspection(
    material: Any,
    tree: Any,
    *,
    max_nodes: int,
    max_links: int,
    max_sockets: int,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    remaining_socket_budget = _MAX_TOTAL_INSPECTED_SOCKETS
    for node in islice(tree.nodes, max_nodes):
        summary = _node_summary(
            node,
            max_sockets=max_sockets,
            socket_budget=remaining_socket_budget,
        )
        remaining_socket_budget -= len(summary["inputs"]) + len(summary["outputs"])
        nodes.append(summary)
    links = [_link_summary(link) for link in islice(tree.links, max_links)]
    truncated_socket_lists = sum(
        int(item["truncated_fields"]["inputs"])
        + int(item["truncated_fields"]["outputs"])
        for item in nodes
    )
    nodes_with_truncated_sockets = sum(
        bool(item["truncated_fields"]["inputs"])
        or bool(item["truncated_fields"]["outputs"])
        for item in nodes
    )
    return {
        "graph_type": "MATERIAL_SHADER",
        "material": material.name,
        "node_tree": tree.name,
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "nodes": nodes,
        "links": links,
        "limits": {
            "max_nodes": max_nodes,
            "max_links": max_links,
            "max_sockets_per_direction": max_sockets,
            "max_total_sockets": _MAX_TOTAL_INSPECTED_SOCKETS,
        },
        "truncated": len(nodes) < len(tree.nodes)
        or len(links) < len(tree.links)
        or bool(truncated_socket_lists),
        "truncated_fields": {
            "nodes": len(nodes) < len(tree.nodes),
            "links": len(links) < len(tree.links),
            "socket_lists": truncated_socket_lists > 0,
            "nodes_with_truncated_sockets": nodes_with_truncated_sockets,
        },
    }


def inspect_nodes(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material_name = _required_string(params, "material_name")
    material, tree = _material_graph(material_name)
    max_nodes = int_param(
        params,
        "max_nodes",
        _DEFAULT_MAX_NODES,
        minimum=1,
        maximum=_MAX_NODES_LIMIT,
    )
    max_links = int_param(
        params,
        "max_links",
        _DEFAULT_MAX_LINKS,
        minimum=1,
        maximum=_MAX_LINKS_LIMIT,
    )
    max_sockets = int_param(
        params,
        "max_sockets_per_direction",
        _DEFAULT_MAX_SOCKETS,
        minimum=1,
        maximum=_MAX_SOCKETS_LIMIT,
    )
    return _graph_inspection(
        material,
        tree,
        max_nodes=max_nodes,
        max_links=max_links,
        max_sockets=max_sockets,
    )


def _post_state(material: Any, tree: Any, node: Any | None = None) -> dict[str, Any]:
    result = {
        "graph_type": "MATERIAL_SHADER",
        "material": material.name,
        "node_tree": tree.name,
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
    }
    if node is not None:
        result["node"] = _node_summary(node, max_sockets=_DEFAULT_MAX_SOCKETS)
    return result


def add_node(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material, tree = _material_graph(_required_string(params, "material_name"))
    node_type = _required_string(
        params,
        "node_type",
        maximum=_MAX_NODE_TYPE_LENGTH,
    )
    if _NODE_TYPE_PATTERN.fullmatch(node_type) is None:
        raise invalid_argument(
            "'node_type' must be a registered shader node id beginning with 'ShaderNode'.",
            parameter="node_type",
        )
    requested_name = _optional_string(params, "name")
    if requested_name is not None and tree.nodes.get(requested_name) is not None:
        raise invalid_argument(
            f"A node named '{requested_name}' already exists.",
            node_name=requested_name,
        )
    label = _optional_string(params, "label", maximum=_MAX_LABEL_BYTES)
    location = params.get("location", (0.0, 0.0))
    location_value = _finite_pair(location, "location")
    try:
        node = tree.nodes.new(node_type)
    except RuntimeError as exc:
        raise invalid_argument(
            f"Blender does not support shader node type '{node_type}'.",
            node_type=node_type,
        ) from exc
    try:
        if requested_name is not None:
            node.name = requested_name
        if label is not None:
            node.label = label
        node.location = location_value
    except Exception:
        tree.nodes.remove(node)
        raise
    return {"added": True, **_post_state(material, tree, node)}


def remove_node(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material, tree = _material_graph(_required_string(params, "material_name"))
    node = _node_exact(tree, _required_string(params, "node_name"))
    name = node.name
    removed_links = sum(
        link.from_node == node or link.to_node == node for link in tree.links
    )
    tree.nodes.remove(node)
    return {
        "removed": True,
        "node": name,
        "removed_link_count": removed_links,
        **_post_state(material, tree),
    }


def rename_node(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material, tree = _material_graph(_required_string(params, "material_name"))
    node = _node_exact(tree, _required_string(params, "node_name"))
    new_name = _required_string(params, "new_name")
    collision = tree.nodes.get(new_name)
    if collision is not None and collision != node:
        raise invalid_argument(
            f"A node named '{new_name}' already exists.",
            node_name=new_name,
        )
    old_name = node.name
    node.name = new_name
    return {
        "renamed": True,
        "old_name": old_name,
        **_post_state(material, tree, node),
    }


def _socket_candidates(sockets: Any, socket_name: str) -> list[tuple[int, Any]]:
    return [
        (index, socket)
        for index, socket in enumerate(sockets)
        if socket.name == socket_name or getattr(socket, "identifier", None) == socket_name
    ]


def _socket_exact(
    node: Any,
    direction: str,
    socket_name: str,
    socket_index: Any,
    *,
    index_parameter: str = "socket_index",
) -> Any:
    sockets = node.inputs if direction == "input" else node.outputs
    candidates = _socket_candidates(sockets, socket_name)
    if socket_index is not None:
        if isinstance(socket_index, bool) or not isinstance(socket_index, int):
            raise invalid_argument(
                f"'{index_parameter}' must be an integer.",
                parameter=index_parameter,
            )
        if socket_index < 0 or socket_index >= len(sockets):
            raise invalid_argument(
                f"'{index_parameter}' is outside the socket range.",
                parameter=index_parameter,
                minimum=0,
                maximum=max(0, len(sockets) - 1),
            )
        socket = sockets[socket_index]
        if socket.name != socket_name and getattr(socket, "identifier", None) != socket_name:
            raise invalid_argument(
                f"Socket index {socket_index} does not match '{socket_name}'.",
                node_name=node.name,
                socket=_socket_summary(socket, socket_index),
            )
        return socket
    if len(candidates) == 1:
        return candidates[0][1]
    available = [
        {
            "index": index,
            "name": socket.name,
            "identifier": getattr(socket, "identifier", ""),
        }
        for index, socket in islice(enumerate(sockets), 64)
    ]
    if not candidates:
        raise invalid_argument(
            f"{direction.title()} socket '{socket_name}' does not exist on node '{node.name}'.",
            node_name=node.name,
            socket_name=socket_name,
            available_sockets=available,
            available_sockets_truncated=len(sockets) > len(available),
        )
    raise invalid_argument(
        f"Socket name '{socket_name}' is ambiguous; provide its exact index.",
        node_name=node.name,
        socket_name=socket_name,
        matching_indices=[index for index, _ in candidates],
    )


def _coerce_default_value(socket: Any, raw_value: Any) -> Any:
    if not hasattr(socket, "default_value"):
        raise invalid_argument(
            f"Socket '{socket.name}' has no editable default value.",
            socket_name=socket.name,
        )
    current = socket.default_value
    if isinstance(raw_value, bool):
        if not isinstance(current, bool):
            raise invalid_argument("A boolean value is not valid for this socket.")
        return raw_value
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        try:
            value = float(raw_value)
        except (OverflowError, ValueError) as exc:
            raise invalid_argument("Numeric socket values must be finite and bounded.") from exc
        if not math.isfinite(value) or abs(value) > 1e12:
            raise invalid_argument("Numeric socket values must be finite and bounded.")
        if isinstance(current, bool):
            raise invalid_argument("A numeric value is not valid for this boolean socket.")
        if isinstance(current, int):
            if not value.is_integer():
                raise invalid_argument("This integer socket requires a whole number.")
            return int(value)
        if isinstance(current, float):
            return value
        raise invalid_argument("This socket requires a vector, color, string, or data block value.")
    if isinstance(raw_value, str):
        if len(raw_value) > 4096:
            raise invalid_argument("String socket values must be at most 4096 characters.")
        if not isinstance(current, str):
            raise invalid_argument("A string value is not valid for this socket.")
        return raw_value
    if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes)):
        if not hasattr(current, "__len__"):
            raise invalid_argument("A sequence value is not valid for this socket.")
        if len(raw_value) != len(current):
            raise invalid_argument(
                "Socket vector length does not match its Blender value.",
                expected_length=len(current),
                actual_length=len(raw_value),
            )
        converted: list[float] = []
        for component in raw_value:
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise invalid_argument("Socket vector components must be numbers.")
            try:
                converted_component = float(component)
            except (OverflowError, ValueError) as exc:
                raise invalid_argument(
                    "Socket vector components must be finite and bounded."
                ) from exc
            if not math.isfinite(converted_component) or abs(converted_component) > 1e12:
                raise invalid_argument("Socket vector components must be finite and bounded.")
            converted.append(converted_component)
        return converted
    raise invalid_argument(
        "Unsupported socket value type; use a boolean, finite number, string, or numeric sequence."
    )


def set_node_input(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material, tree = _material_graph(_required_string(params, "material_name"))
    node = _node_exact(tree, _required_string(params, "node_name"))
    socket_name = _required_string(
        params,
        "socket_name",
        maximum=_MAX_SOCKET_NAME_BYTES,
    )
    socket = _socket_exact(node, "input", socket_name, params.get("socket_index"))
    if "value" not in params:
        raise invalid_argument("'value' is required.", parameter="value")
    value = _coerce_default_value(socket, params["value"])
    try:
        socket.default_value = value
    except (TypeError, ValueError, OverflowError) as exc:
        raise invalid_argument(
            f"Blender rejected the value for socket '{socket.name}'.",
            node_name=node.name,
            socket_name=socket.name,
        ) from exc
    socket_index = next(index for index, item in enumerate(node.inputs) if item == socket)
    return {
        "input_set": True,
        "material": material.name,
        "node_tree": tree.name,
        "node": node.name,
        "socket": _socket_summary(socket, socket_index),
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
    }


def _endpoint(
    tree: Any,
    params: Mapping[str, Any],
    prefix: str,
    direction: str,
) -> tuple[Any, Any]:
    node = _node_exact(tree, _required_string(params, f"{prefix}_node"))
    socket_name = _required_string(
        params,
        f"{prefix}_socket",
        maximum=_MAX_SOCKET_NAME_BYTES,
    )
    socket = _socket_exact(
        node,
        direction,
        socket_name,
        params.get(f"{prefix}_socket_index"),
        index_parameter=f"{prefix}_socket_index",
    )
    return node, socket


def link_nodes(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material, tree = _material_graph(_required_string(params, "material_name"))
    _, from_socket = _endpoint(tree, params, "from", "output")
    _, to_socket = _endpoint(tree, params, "to", "input")
    replace = params.get("replace_existing", False)
    if not isinstance(replace, bool):
        raise invalid_argument("'replace_existing' must be a boolean.")
    duplicate = next(
        (
            link
            for link in tree.links
            if link.from_socket == from_socket and link.to_socket == to_socket
        ),
        None,
    )
    if duplicate is not None:
        return {
            "linked": False,
            "already_exists": True,
            "link": _link_summary(duplicate),
            **_post_state(material, tree),
        }
    existing = [link for link in tree.links if link.to_socket == to_socket]
    if existing and not bool(getattr(to_socket, "is_multi_input", False)) and not replace:
        raise invalid_argument(
            "The destination socket is already linked; set 'replace_existing' to true to replace it.",
            existing_links=[_link_summary(link) for link in existing[:16]],
            existing_links_truncated=len(existing) > 16,
        )
    removed = (
        len(existing)
        if replace and not bool(getattr(to_socket, "is_multi_input", False))
        else 0
    )
    link = tree.links.new(from_socket, to_socket)
    return {
        "linked": True,
        "replaced_link_count": removed,
        "link": _link_summary(link),
        **_post_state(material, tree),
    }


def unlink_nodes(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    material, tree = _material_graph(_required_string(params, "material_name"))
    from_node, from_socket = _endpoint(tree, params, "from", "output")
    to_node, to_socket = _endpoint(tree, params, "to", "input")
    matches = [
        link
        for link in tree.links
        if link.from_socket == from_socket and link.to_socket == to_socket
    ]
    for link in matches:
        tree.links.remove(link)
    return {
        "unlinked": bool(matches),
        "removed_link_count": len(matches),
        "endpoint": {
            "from_node": from_node.name,
            "from_socket": from_socket.name,
            "to_node": to_node.name,
            "to_socket": to_socket.name,
        },
        **_post_state(material, tree),
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "nodes.inspect",
        inspect_nodes,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="nodes",
        description="Inspect a complete material shader graph with explicit bounds and truncation metadata.",
    )
    common = {
        "permissions": (Permission.EDIT_MATERIALS,),
        "toolset": "nodes",
        "modifies": True,
    }
    registry.register(
        "nodes.add",
        add_node,
        description="Add a validated shader node to one material graph.",
        **common,
    )
    registry.register(
        "nodes.remove",
        remove_node,
        description="Remove one exact node and its incident links.",
        **common,
    )
    registry.register(
        "nodes.rename",
        rename_node,
        description="Rename one exact shader node without collisions.",
        **common,
    )
    registry.register(
        "nodes.set_input",
        set_node_input,
        description="Set one exact unlinked or linked node input default value.",
        **common,
    )
    registry.register(
        "nodes.link",
        link_nodes,
        description="Link exact output and input sockets with explicit replacement behavior.",
        **common,
    )
    registry.register(
        "nodes.unlink",
        unlink_nodes,
        description="Remove links between exact output and input sockets.",
        **common,
    )
