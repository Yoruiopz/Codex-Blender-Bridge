"""Guarded zone socket conversion and nested-group interface maintenance.

Native 4.3 probes establish identifier stability and default-reset behavior.
No cache operators, disk paths, generic RNA traversal or asynchronous jobs.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import int_param, reject_unknown_params, require_blender
from . import geometry_node_groups as groups
from .shader_scope import name

LOGGER = logging.getLogger(__name__)
TYPES = {"FLOAT": "NodeSocketFloat", "INT": "NodeSocketInt", "BOOLEAN": "NodeSocketBool",
         "VECTOR": "NodeSocketVector", "RGBA": "NodeSocketColor"}


def _zone(tree: Any, output_name: Any) -> tuple[Any, Any, Any]:
    output = tree.nodes.get(name(output_name, "output_name"))
    if output is None or output.bl_idname not in {"GeometryNodeRepeatOutput", "GeometryNodeSimulationOutput"}:
        raise invalid_argument("Expected an exact repeat or simulation output boundary.")
    items = output.repeat_items if output.bl_idname == "GeometryNodeRepeatOutput" else output.state_items
    if not 1 <= len(items) <= 32:
        raise invalid_argument("Zone item scope requires 1-32 items.")
    paired = [node for node in tree.nodes if getattr(node, "paired_output", None) == output]
    if len(paired) != 1:
        raise invalid_argument("Zone conversion requires exactly one paired input boundary.")
    return paired[0], output, items


def _item(tree: Any, output_name: Any, identifier: Any) -> tuple[Any, Any, Any]:
    source, output, items = _zone(tree, output_name)
    target = groups._socket(output.inputs, identifier)
    matches = [item for item in items if item.name == target.name and item.socket_type in TYPES
               and getattr(target, "type", None) == {"FLOAT": "VALUE"}.get(item.socket_type, item.socket_type)]
    if len(matches) != 1:
        raise invalid_argument("Identifier must resolve one reviewed numeric/bool/vector/color zone item.")
    for node in (source, output):
        for direction in (node.inputs, node.outputs):
            current = groups._socket(direction, identifier)
            if (current.name != matches[0].name or current.is_linked
                    or current.type != {"FLOAT": "VALUE"}.get(matches[0].socket_type, matches[0].socket_type)):
                raise invalid_argument("All four paired item sockets must be present and unlinked; unlink explicitly before conversion.")
    return source, output, matches[0]


def _state(bpy: Any, tree: Any, scope: dict, context: ToolContext) -> dict:
    """Bounded complete reviewed definitions and direct modifier properties, no callbacks."""
    quiet = groups._validation_context(context)
    names = {tree.name, *scope["parent_groups"]}
    for current_name in tuple(names):
        names.update(groups._review(groups._group(bpy, current_name), quiet))
    if len(names) > groups.MAX_TREES:
        raise invalid_argument("GN lifecycle scope exceeds 32 definitions.")
    definitions = {}
    for current_name in sorted(names):
        current = groups._group(bpy, current_name)
        if getattr(current, "animation_data", None) is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "GN lifecycle edits require unanimated definitions for verified preservation.")
        definitions[current_name] = groups._graph_guard(current)
    modifiers: list[Any] = []
    for object_name in scope["affected_objects"]:
        matches = [obj for obj in bpy.data.objects if obj.name == object_name]
        if len(matches) != 1:
            raise invalid_argument("GN lifecycle consumer identity is missing or ambiguous.")
        obj = matches[0]
        if len(obj.modifiers) > 100 or getattr(obj, "animation_data", None) is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "GN lifecycle consumers require bounded unanimated modifier owners.")
        for modifier in obj.modifiers:
            if modifier.type != "NODES" or modifier.node_group is None or modifier.node_group.name not in names:
                continue
            # 4.3 exposes bake settings but no authoritative baked/packed status.
            if len(getattr(modifier, "bakes", ())):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Attached simulation/bake caches need a separately verified cache lifecycle before schema/interface edits.")
            if len(modifiers) >= 100:
                raise invalid_argument("GN lifecycle scope exceeds 100 modifier consumers.")
            modifiers.append([obj.name, groups._object_token(obj), modifier.name, groups._key(modifier),
                              groups._key(modifier.node_group), groups._modifier_properties(modifier)])
    return {"graphs": definitions, "modifiers": modifiers}


def _without_edit(state: dict, tree_key: int, identifier: str, operation: str, boundaries: tuple[str, ...] = ()) -> dict:
    """Remove only the declared delta; every other captured field must match."""
    result = copy.deepcopy(state)
    for graph in result["graphs"].values():
        root = graph["identity"] == tree_key
        if root and operation in {"RENAME", "MOVE", "SET_DEFAULT"}:
            interface = []
            for record in graph["interface"]:
                values = list(record)
                if values[1] == identifier:
                    if operation == "RENAME":
                        values[0] = None
                    elif operation == "SET_DEFAULT":
                        values[5] = None
                interface.append(values)
            graph["interface"] = sorted(interface, key=lambda item: str(item[1])) if operation == "MOVE" else interface
        for node in graph["nodes"]:
            interface_consumer = node[3] == tree_key or (root and node[2] in {"NodeGroupInput", "NodeGroupOutput"})
            zone_boundary = root and node[1] in boundaries
            for direction in (5, 6):
                for socket in node[direction]:
                    if socket[0] != identifier:
                        continue
                    if zone_boundary and operation == "CONVERT":
                        socket[2], socket[3] = None, None
                    elif interface_consumer and operation == "RENAME":
                        socket[1] = None
                    elif root and node[2] == "NodeGroupInput" and operation == "SET_DEFAULT":
                        socket[3] = None
                if interface_consumer and operation == "MOVE":
                    node[direction].sort(key=lambda item: item[0])
            if zone_boundary and operation == "CONVERT" and node[7][1] is not None:
                item_name = next(socket[1] for socket in node[5] if socket[0] == identifier)
                node[7][1] = [(entry[0], None if entry[0] == item_name else entry[1], entry[2]) for entry in node[7][1]]
    return result


def _begin(context: ToolContext, params: Mapping[str, Any]) -> tuple[Any, Any, dict, dict]:
    bpy = require_blender()
    tree = groups._group(bpy, params.get("group_name"))
    scope = groups._editable(bpy, tree, context, params)
    before = _state(bpy, tree, scope, context)
    return bpy, tree, scope, before


def _current(context: ToolContext, bpy: Any, params: Mapping[str, Any], key: int, scope: dict, expected: dict) -> Any:
    tree = groups._compensation_group(context, bpy, params["group_name"], key, params, scope)
    if _state(bpy, tree, scope, context) != expected:
        raise invalid_argument("GN lifecycle scope changed; stale writes and compensation are refused.")
    return tree


def zone_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"group_name", "output_name"})
    bpy = require_blender()
    tree = groups._group(bpy, params.get("group_name"))
    groups._review(tree, context)
    source, output, items = _zone(tree, params.get("output_name"))
    records = []
    for item in items:
        matches = [socket for socket in output.inputs if socket.name == item.name]
        records.append({"name": item.name, "socket_type": item.socket_type,
                        "socket_identifier": matches[0].identifier if len(matches) == 1 else None,
                        "attribute_domain": getattr(item, "attribute_domain", None)})
    return {"group_name": tree.name, "input_name": source.name, "output_name": output.name,
            "items": records, "truncated": False, "maximum_items": 32,
            "supported_conversion_types": sorted(TYPES), "cache_status_verified": False}


def zone_item_convert(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"group_name", "output_name", "socket_identifier", "socket_type", "input_value", "output_value", "allow_shared"})
    bpy, tree, scope, before = _begin(context, params)
    identifier = name(params.get("socket_identifier"), "socket_identifier")
    source, output, item = _item(tree, params.get("output_name"), identifier)
    kind = params.get("socket_type")
    if not isinstance(kind, str) or kind not in TYPES:
        raise invalid_argument("Conversion requires FLOAT, INT, BOOLEAN, VECTOR or RGBA.")
    input_value = groups._value(SimpleNamespace(socket_type=TYPES[kind], default_value=None), params.get("input_value"))
    output_value = groups._value(SimpleNamespace(socket_type=TYPES[kind], default_value=None), params.get("output_value"))
    previous = {"socket_type": item.socket_type, "input_value": groups._read(groups._socket(source.inputs, identifier).default_value),
                "output_value": groups._read(groups._socket(output.inputs, identifier).default_value),
                "boundary_output_defaults": [groups._read(groups._socket(node.outputs, identifier).default_value) for node in (source, output)]}
    key, boundaries = groups._key(tree), (source.name, output.name)
    groups._gate(context, Permission.EDIT_MESH)
    tree = _current(context, bpy, params, key, scope, before)
    source, output, item = _item(tree, params["output_name"], identifier)
    published = None
    try:
        item.socket_type = kind
        published = _state(bpy, tree, scope, context)
        groups._socket(source.inputs, identifier).default_value = input_value
        published = _state(bpy, tree, scope, context)
        groups._socket(output.inputs, identifier).default_value = output_value
        published = _state(bpy, tree, scope, context)
        if _without_edit(before, key, identifier, "CONVERT", boundaries) != _without_edit(published, key, identifier, "CONVERT", boundaries):
            raise RuntimeError("Zone conversion changed protected definition/consumer state")
        groups._gate(context, Permission.EDIT_MESH)
        tree = _current(context, bpy, params, key, scope, published)
        source, output, item = _item(tree, params["output_name"], identifier)
        if (item.socket_type != kind or not groups._same(groups._read(groups._socket(source.inputs, identifier).default_value), input_value)
                or not groups._same(groups._read(groups._socket(output.inputs, identifier).default_value), output_value)):
            raise RuntimeError("Zone type/default readback mismatch")
        return {"converted": True, "socket_identifier": identifier, "socket_type": kind,
                "input_value": groups._read(groups._socket(source.inputs, identifier).default_value),
                "output_value": groups._read(groups._socket(output.inputs, identifier).default_value),
                "previous": previous, "paired_identifiers_preserved": True, **groups._post(tree, scope)}
    except Exception as error:
        LOGGER.exception("GN zone conversion failed")
        restored = False
        try:
            if published is None:
                raise invalid_argument("No owned publication fingerprint; inspect partial native effects.")
            groups._gate(context, Permission.EDIT_MESH)
            tree = _current(context, bpy, params, key, scope, published)
            source, output, item = _item(tree, params["output_name"], identifier)
            item.socket_type = previous["socket_type"]
            recovery_state = _state(bpy, tree, scope, context)
            groups._gate(context, Permission.EDIT_MESH)
            tree = _current(context, bpy, params, key, scope, recovery_state)
            source, output, item = _item(tree, params["output_name"], identifier)
            groups._socket(source.inputs, identifier).default_value = previous["input_value"]
            recovery_state = _state(bpy, tree, scope, context)
            groups._gate(context, Permission.EDIT_MESH)
            tree = _current(context, bpy, params, key, scope, recovery_state)
            source, output, item = _item(tree, params["output_name"], identifier)
            groups._socket(output.inputs, identifier).default_value = previous["output_value"]
            for node_name, default in zip(boundaries, previous["boundary_output_defaults"], strict=True):
                recovery_state = _state(bpy, tree, scope, context)
                groups._gate(context, Permission.EDIT_MESH)
                tree = _current(context, bpy, params, key, scope, recovery_state)
                node = tree.nodes.get(node_name)
                groups._socket(node.outputs, identifier).default_value = default
            restored = _state(bpy, tree, scope, context) == before
        except Exception:
            LOGGER.exception("GN zone conversion compensation skipped or failed")
        raise groups._failed(error, "Zone conversion failed; inspect paired sockets and recovery evidence.", restored=restored) from error


def _interface(tree: Any, identifier: str) -> Any:
    socket = groups._socket(tree.interface.items_tree, identifier)
    if socket.item_type != "SOCKET":
        raise invalid_argument("Expected an interface socket identifier.")
    return socket


def _move(tree: Any, socket: Any, position: int) -> None:
    items = list(tree.interface.items_tree)
    if any(item.item_type != "SOCKET" for item in items):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Interface reordering currently requires a flat socket-only interface.")
    peers = [item for item in items if item.in_out == socket.in_out]
    if position >= len(peers):
        raise invalid_argument("to_index must identify a final position within the socket direction.")
    current_index, target_index = items.index(socket), items.index(peers[position])
    tree.interface.move(socket, target_index + int(current_index < target_index))
    if [item.identifier for item in tree.interface.items_tree if item.in_out == socket.in_out][position] != socket.identifier:
        raise RuntimeError("Native interface move did not reach its requested final index")


def _move_order_verified(before: dict, after: dict, key: int, expected: list[str]) -> bool:
    for graph_name, original in before["graphs"].items():
        observed = after["graphs"][graph_name]
        root = original["identity"] == key
        if root and [item[1] for item in observed["interface"]] != expected:
            return False
        current_nodes = {item[0]: item for item in observed["nodes"]}
        for node in original["nodes"]:
            if node[3] != key and not (root and node[2] in {"NodeGroupInput", "NodeGroupOutput"}):
                continue
            for direction in (5, 6):
                old_ids = [item[0] for item in node[direction]]
                reordered = iter(item for item in expected if item in old_ids)
                desired = [next(reordered) if item in expected else item for item in old_ids]
                if [item[0] for item in current_nodes[node[0]][direction]] != desired:
                    return False
    return True


def interface_edit(context: ToolContext, params: Mapping[str, Any]) -> dict:
    operation = params.get("operation")
    extra = {"RENAME": {"new_name"}, "MOVE": {"to_index"}, "SET_DEFAULT": {"value"}}
    if not isinstance(operation, str) or operation not in extra:
        raise invalid_argument("operation must be RENAME, MOVE or SET_DEFAULT.")
    reject_unknown_params(params, {"group_name", "socket_identifier", "operation", "allow_shared"} | extra[operation])
    bpy, tree, scope, before = _begin(context, params)
    identifier = name(params.get("socket_identifier"), "socket_identifier")
    socket = _interface(tree, identifier)
    key = groups._key(tree)
    previous_name = socket.name
    peers = [item for item in tree.interface.items_tree if item.item_type == "SOCKET" and item.in_out == socket.in_out]
    previous_index = peers.index(socket)
    previous_value = groups._read(socket.default_value) if hasattr(socket, "default_value") else None
    value: Any = None
    expected_order = [item.identifier for item in tree.interface.items_tree if item.item_type == "SOCKET"]
    if operation == "RENAME":
        value = name(params.get("new_name"), "new_name")
        if any(item.name == value and item.identifier != identifier for item in peers):
            raise invalid_argument("New interface name collides within the socket direction.")
    elif operation == "MOVE":
        value = int_param(params, "to_index", -1, minimum=0, maximum=len(peers)-1)
        if any(item.item_type != "SOCKET" for item in tree.interface.items_tree):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Interface reordering requires a flat socket-only interface.")
        reordered = [item.identifier for item in peers]
        reordered.remove(identifier)
        reordered.insert(value, identifier)
        next_peer = iter(reordered)
        expected_order = [next(next_peer) if item.in_out == socket.in_out else item.identifier for item in tree.interface.items_tree]
    else:
        if socket.in_out != "INPUT":
            raise invalid_argument("Only input interface defaults are supported.")
        value = groups._value(socket, params.get("value"))
    groups._gate(context, Permission.EDIT_MESH)
    tree = _current(context, bpy, params, key, scope, before)
    socket = _interface(tree, identifier)
    published = None
    try:
        if operation == "RENAME":
            socket.name = value
        elif operation == "MOVE":
            _move(tree, socket, value)
        else:
            socket.default_value = value
        published = _state(bpy, tree, scope, context)
        if _without_edit(before, key, identifier, operation) != _without_edit(published, key, identifier, operation):
            raise RuntimeError("Interface edit changed protected definition/consumer state")
        if operation == "MOVE" and not _move_order_verified(before, published, key, expected_order):
            raise RuntimeError("Interface move changed another peer's relative order")
        groups._gate(context, Permission.EDIT_MESH)
        tree = _current(context, bpy, params, key, scope, published)
        socket = _interface(tree, identifier)
        peers = [item for item in tree.interface.items_tree if item.item_type == "SOCKET" and item.in_out == socket.in_out]
        observed = socket.name if operation == "RENAME" else peers.index(socket) if operation == "MOVE" else groups._read(socket.default_value)
        if not groups._same(observed, value):
            raise RuntimeError("Interface edit readback mismatch")
        return {"operation": operation, "socket_identifier": identifier, "value": observed,
                "existing_consumer_values_preserved": True, "previous_name": previous_name,
                "previous_index": previous_index, "previous_default": previous_value, **groups._post(tree, scope)}
    except Exception as error:
        LOGGER.exception("GN interface edit failed")
        restored = False
        try:
            if published is None:
                raise invalid_argument("No owned publication fingerprint; inspect partial native effects.")
            groups._gate(context, Permission.EDIT_MESH)
            tree = _current(context, bpy, params, key, scope, published)
            socket = _interface(tree, identifier)
            if operation == "RENAME":
                socket.name = previous_name
            elif operation == "MOVE":
                _move(tree, socket, previous_index)
            else:
                socket.default_value = previous_value
            restored = _state(bpy, tree, scope, context) == before
        except Exception:
            LOGGER.exception("GN interface compensation skipped or failed")
        raise groups._failed(error, "GN interface edit failed; inspect current consumers and recovery evidence.", restored=restored) from error


def register_tools(registry: ToolRegistry) -> None:
    for tool_name, handler in (("zone_inspect", zone_inspect), ("zone_item_convert", zone_item_convert), ("interface_edit", interface_edit)):
        modifying = tool_name != "zone_inspect"
        registry.register("geometry_nodes." + tool_name, handler, toolset="geometry_nodes", modifies=modifying,
                          permissions=(Permission.EDIT_MESH,) if modifying else (Permission.INSPECT_SCENE,),
                          description="Bounded paired-zone inspection/conversion or nested interface maintenance; no bake/cache lifecycle.")
