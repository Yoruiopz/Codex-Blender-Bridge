"""Explicit, bounded Geometry Nodes authoring through Blender's data API.

Graph edits require EDIT_MESH; attaching a graph additionally requires
TRANSFORM_OBJECTS. No operators, arbitrary attributes, files, or Python are
exposed. Shared graphs require an explicit acknowledgement on every edit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_object, int_param, reject_unknown_params, require_blender
from . import nodes as shader_nodes
from ._rna import apply_assignments, prepare_assignments, serialize_properties, settings_mapping

MAX_NODES = 2048
MAX_LINKS = 8192
MAX_INTERFACE = 128
MAX_USERS = 128
_NODE_TYPE = re.compile(r"^(?:GeometryNode|ShaderNode)[A-Za-z0-9_]+$")
_UTILITY_TYPES = frozenset({"NodeGroupInput", "NodeGroupOutput", "NodeReroute", "NodeFrame"})
# Exact reviewed types: a prefix match would also admit file-import/script nodes
# whose string inputs could bypass ACCESS_EXTERNAL_FILES on evaluation.
_SAFE_NODE_TYPES = _UTILITY_TYPES | frozenset({
    "GeometryNodeRepeatInput", "GeometryNodeRepeatOutput",
    "GeometryNodeSimulationInput", "GeometryNodeSimulationOutput",
    "GeometryNodeMeshGrid", "GeometryNodeMeshCube", "GeometryNodeMeshCircle",
    "GeometryNodeMeshLine", "GeometryNodeMeshUVSphere", "GeometryNodeMeshIcoSphere",
    "GeometryNodeMeshCylinder", "GeometryNodeMeshCone", "GeometryNodeTransform",
    "GeometryNodeJoinGeometry", "GeometryNodeSetPosition", "GeometryNodeInputPosition",
    "GeometryNodeInputNormal", "GeometryNodeInputIndex", "GeometryNodeInputID",
    "GeometryNodeInputSceneTime", "GeometryNodeSetShadeSmooth", "GeometryNodeSubdivisionSurface",
    "GeometryNodeSubdivideMesh", "GeometryNodeExtrudeMesh", "GeometryNodeMeshToPoints",
    "GeometryNodePointsToVertices", "GeometryNodeInstanceOnPoints", "GeometryNodeRealizeInstances",
    "GeometryNodeTranslateInstances", "GeometryNodeRotateInstances", "GeometryNodeScaleInstances",
    "GeometryNodeDeleteGeometry", "GeometryNodeDuplicateElements", "GeometryNodeMergeByDistance",
    "GeometryNodeCurvePrimitiveCircle", "GeometryNodeCurvePrimitiveLine", "GeometryNodeCurveToMesh",
    "GeometryNodeCurveToPoints", "GeometryNodeResampleCurve", "GeometryNodeSetCurveRadius",
    "GeometryNodeSwitch", "GeometryNodeGeometryToInstance", "GeometryNodeStoreNamedAttribute",
    "GeometryNodeInputNamedAttribute", "GeometryNodeRemoveAttribute",
    "ShaderNodeMath", "ShaderNodeVectorMath", "ShaderNodeMapRange", "ShaderNodeClamp",
    "ShaderNodeCombineXYZ", "ShaderNodeSeparateXYZ", "ShaderNodeValue", "ShaderNodeRGB",
})
_SOCKET_TYPES = frozenset(
    {
        "NodeSocketGeometry",
        "NodeSocketFloat",
        "NodeSocketInt",
        "NodeSocketBool",
        "NodeSocketVector",
        "NodeSocketColor",
        "NodeSocketString",
    }
)
# Direct scalar/enum RNA only. Pointers, collections, script paths, images,
# group assignment, and dynamically sized zone items are deliberately absent.
_NODE_PROPERTIES = frozenset(
    {
        "operation",
        "data_type",
        "domain",
        "mode",
        "input_type",
        "clamp",
        "use_clamp",
        "interpolation_type",
        "interpolation",
        "transform_space",
        "rotation_type",
        "distribution",
        "distribute_method",
        "component",
        "axis",
        "pivot_axis",
        "invert",
        "boolean",
        "use_whole_collection",
        "label",
        "location",
        "width",
        "mute",
        "hide",
        "is_active_output",
    }
)


def _name(params: Mapping[str, Any], key: str) -> str:
    return shader_nodes._required_string(params, key)


def _boolean(params: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise invalid_argument(f"'{key}' must be a boolean.", parameter=key)
    return value


def _editable(data: Any) -> None:
    if (
        getattr(data, "library", None) is not None
        or getattr(data, "override_library", None) is not None
        or not bool(getattr(data, "is_editable", True))
    ):
        raise invalid_argument(
            "Structured Geometry Nodes editing requires a local, editable data block without a library override.",
            data_block=data.name,
        )


def _users(tree: Any) -> list[Any]:
    return list(require_blender().data.user_map(subset={tree}).get(tree, ()))


def _safe_graph(tree: Any) -> None:
    unsupported = sorted({node.bl_idname for node in tree.nodes if node.bl_idname not in _SAFE_NODE_TYPES})
    if unsupported:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "This graph contains nodes outside the reviewed structured subset; inspect it separately. File/script and nested group nodes are not supported.",
            {"unsupported_node_types": unsupported[:32], "truncated": len(unsupported) > 32},
        )
    for node in tree.nodes:
        if node.bl_idname in {"GeometryNodeRepeatInput", "GeometryNodeSimulationInput"} and node.paired_output is None:
            raise invalid_argument("Zone input has no paired output.", node_name=node.name)
        if node.bl_idname == "GeometryNodeRepeatInput":
            iterations = node.inputs.get("Iterations")
            if iterations is None or iterations.is_linked or not 0 <= iterations.default_value <= 64:
                raise invalid_argument("Repeat zones require a constant iteration count between 0 and 64.")


def _group(params: Mapping[str, Any], *, modify: bool = False) -> Any:
    name = _name(params, "group_name")
    tree = require_blender().data.node_groups.get(name)
    if tree is None or tree.bl_idname != "GeometryNodeTree":
        raise invalid_argument(
            "'group_name' must identify an existing GeometryNodeTree exactly.",
            group_name=name,
        )
    if modify:
        _editable(tree)
        _safe_graph(tree)
        allow_shared = _boolean(params, "allow_shared")
        indirect = any(
            getattr(user, "bl_idname", None) == "GeometryNodeTree" for user in _users(tree)
        )
        if (tree.users > 1 or indirect) and not allow_shared:
            raise invalid_argument(
                "This graph is shared or nested; inspect its users and set 'allow_shared' to acknowledge editing every user.",
                group_name=tree.name,
                user_count=tree.users,
                nested=indirect,
                required_acknowledgement="allow_shared",
            )
        if len(tree.nodes) > MAX_NODES or len(tree.links) > MAX_LINKS:
            raise invalid_argument(
                "This graph exceeds the structured editing budget.",
                maximum_nodes=MAX_NODES,
                maximum_links=MAX_LINKS,
            )
    return tree


def _post_state(tree: Any, node: Any | None = None) -> dict[str, Any]:
    users = _users(tree)
    returned = sorted(islice(users, MAX_USERS), key=lambda item: item.name)
    result: dict[str, Any] = {
        "graph_type": "GEOMETRY_NODES",
        "group_name": tree.name,
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "interface_item_count": len(tree.interface.items_tree),
        "user_count": tree.users,
        "direct_users": [{"name": user.name, "type": user.bl_rna.identifier} for user in returned],
        "direct_users_truncated": len(users) > MAX_USERS,
        "affected_objects": [user.name for user in returned if user.bl_rna.identifier == "Object"],
        "affected_objects_scope": "direct users only; nested graph users may affect additional objects",
    }
    if node is not None:
        result["node"] = shader_nodes._node_summary(node, max_sockets=32)
        result["node"]["settings"] = serialize_properties(node, _NODE_PROPERTIES)
        result["node"]["zone"] = _zone_summary(node)
    return result


def _zone_summary(node: Any) -> dict[str, Any] | None:
    paired = getattr(node, "paired_output", None)
    items = getattr(node, "repeat_items", getattr(node, "state_items", None))
    if paired is None and items is None:
        return None
    return {"paired_output": getattr(paired, "name", None),
            "items": [] if items is None else [{"name": item.name, "socket_type": item.socket_type,
                      "identifier": getattr(item, "identifier", None)} for item in list(items)[:32]],
            "items_truncated": items is not None and len(items) > 32}


def _interface_summary(item: Any) -> dict[str, Any]:
    result = {
        "name": item.name,
        "identifier": getattr(item, "identifier", None),
        "item_type": item.item_type,
    }
    if item.item_type == "SOCKET":
        result.update(in_out=item.in_out, socket_type=item.socket_type)
        if hasattr(item, "default_value"):
            result["default_value"] = shader_nodes._json_value(item.default_value)
    return result


def inspect_graph(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    tree = _group(params)
    max_nodes = int_param(params, "max_nodes", 100, minimum=1, maximum=256)
    max_links = int_param(params, "max_links", 300, minimum=1, maximum=1024)
    max_sockets = int_param(params, "max_sockets_per_direction", 32, minimum=1, maximum=64)
    max_interface = int_param(params, "max_interface_items", 64, minimum=1, maximum=MAX_INTERFACE)
    graph = shader_nodes._graph_inspection(
        tree, tree, max_nodes=max_nodes, max_links=max_links, max_sockets=max_sockets
    )
    graph.pop("material")
    graph.pop("node_tree")
    for node in graph["nodes"]:
        node["settings"] = serialize_properties(tree.nodes.get(node["name"]), _NODE_PROPERTIES)
        node["zone"] = _zone_summary(tree.nodes.get(node["name"]))
    graph.update(_post_state(tree))
    graph["supported_node_types"] = sorted(_SAFE_NODE_TYPES)
    graph["interface"] = [
        _interface_summary(item) for item in islice(tree.interface.items_tree, max_interface)
    ]
    graph["truncated_fields"]["interface"] = len(graph["interface"]) < len(
        tree.interface.items_tree
    )
    graph["truncated"] |= graph["truncated_fields"]["interface"] or graph["direct_users_truncated"]
    graph["limits"]["max_interface_items"] = max_interface
    graph["editable_node_properties"] = sorted(_NODE_PROPERTIES)
    graph["supported_interface_socket_types"] = sorted(_SOCKET_TYPES)
    return graph


def create_graph(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "passthrough"})
    del context
    bpy = require_blender()
    name = _name(params, "group_name")
    passthrough = _boolean(params, "passthrough", True)
    if bpy.data.node_groups.get(name) is not None:
        raise invalid_argument("A node group already has this name.", group_name=name)
    tree = bpy.data.node_groups.new(name=name, type="GeometryNodeTree")
    try:
        tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        tree.interface.new_socket(
            name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )
        source = tree.nodes.new("NodeGroupInput")
        source.name = "Group Input"
        source.location = (-240, 0)
        destination = tree.nodes.new("NodeGroupOutput")
        destination.name = "Group Output"
        destination.location = (240, 0)
        destination.is_active_output = True
        if passthrough:
            tree.links.new(source.outputs["Geometry"], destination.inputs["Geometry"])
    except Exception:
        bpy.data.node_groups.remove(tree)
        raise
    return {"created": True, "passthrough": passthrough, **_post_state(tree)}


def add_interface(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "name", "in_out", "socket_type", "default_value", "allow_shared"})
    del context
    tree = _group(params, modify=True)
    name = _name(params, "name")
    direction = params.get("in_out", "INPUT")
    socket_type = params.get("socket_type", "NodeSocketFloat")
    if not isinstance(direction, str) or direction not in {"INPUT", "OUTPUT"}:
        raise invalid_argument("'in_out' must be INPUT or OUTPUT.")
    if not isinstance(socket_type, str) or socket_type not in _SOCKET_TYPES:
        raise invalid_argument(
            "Unsupported interface socket type.", supported=sorted(_SOCKET_TYPES)
        )
    if len(tree.interface.items_tree) >= MAX_INTERFACE:
        raise invalid_argument(
            "The graph has reached the interface item limit.", maximum=MAX_INTERFACE
        )
    if any(
        item.item_type == "SOCKET" and item.name == name and item.in_out == direction
        for item in tree.interface.items_tree
    ):
        raise invalid_argument("An interface socket already has this name and direction.")
    socket = tree.interface.new_socket(name=name, in_out=direction, socket_type=socket_type)
    try:
        if "default_value" in params:
            socket.default_value = shader_nodes._coerce_default_value(
                socket, params["default_value"]
            )
    except Exception:
        tree.interface.remove(socket)
        raise
    return {"added": _interface_summary(socket), **_post_state(tree)}


def add_node(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "node_type", "name", "location", "settings", "allow_shared"})
    del context
    bpy = require_blender()
    tree = _group(params, modify=True)
    node_type = shader_nodes._required_string(params, "node_type", maximum=128)
    if node_type == "GeometryNodeGroup" or node_type.startswith(
        ("GeometryNodeSimulation", "GeometryNodeRepeat", "GeometryNodeForeach")
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Nested groups are unsupported; create paired zone boundaries with geometry_nodes.zone_create.",
            {"node_type": node_type},
        )
    if node_type not in _UTILITY_TYPES and _NODE_TYPE.fullmatch(node_type) is None:
        raise invalid_argument(
            "'node_type' must identify a GeometryNode, compatible ShaderNode, or built-in utility node."
        )
    if node_type not in _SAFE_NODE_TYPES:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "This node_type is outside the reviewed structured subset; file/import/script nodes are not exposed.",
            {"node_type": node_type, "supported_node_types": sorted(_SAFE_NODE_TYPES)},
        )
    node_class = getattr(bpy.types, node_type, None)
    if node_class is None or not issubclass(node_class, bpy.types.Node):
        raise invalid_argument(
            "This node type is unavailable in a GeometryNodeTree.", node_type=node_type
        )
    if len(tree.nodes) >= MAX_NODES:
        raise invalid_argument("The graph has reached the node limit.", maximum=MAX_NODES)
    name = _name(params, "name") if params.get("name") is not None else None
    if name is not None and tree.nodes.get(name) is not None:
        raise invalid_argument("A node already has this exact name.", node_name=name)
    location = shader_nodes._finite_pair(params.get("location", (0.0, 0.0)), "location")
    settings = settings_mapping(params, required=False)
    # ShaderNode.poll rejects geometry trees even for the Math/Vector Math
    # nodes that Blender supports there. nodes.new is the authoritative check.
    try:
        node = tree.nodes.new(node_type)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise invalid_argument(
            "This node type is unavailable in a GeometryNodeTree.", node_type=node_type
        ) from exc
    try:
        if name is not None:
            node.name = name
        node.location = location
        assignments = prepare_assignments(
            node, settings, allowed=_NODE_PROPERTIES, object_pointers=frozenset(), bpy=bpy
        )
        apply_assignments(node, assignments)
    except Exception:
        tree.nodes.remove(node)
        raise
    return {"added": True, **_post_state(tree, node)}


def set_node_properties(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "node_name", "settings", "allow_shared"})
    del context
    tree = _group(params, modify=True)
    node = shader_nodes._node_exact(tree, _name(params, "node_name"))
    assignments = prepare_assignments(
        node,
        settings_mapping(params),
        allowed=_NODE_PROPERTIES,
        object_pointers=frozenset(),
        bpy=require_blender(),
    )
    apply_assignments(node, assignments)
    return {"updated_properties": [item.name for item in assignments], **_post_state(tree, node)}


def set_node_input(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "node_name", "socket_name", "socket_index", "value", "allow_shared"})
    del context
    tree = _group(params, modify=True)
    node = shader_nodes._node_exact(tree, _name(params, "node_name"))
    socket_name = shader_nodes._required_string(params, "socket_name", maximum=256)
    socket = shader_nodes._socket_exact(node, "input", socket_name, params.get("socket_index"))
    if "value" not in params:
        raise invalid_argument("'value' is required.")
    value = shader_nodes._coerce_default_value(socket, params["value"])
    if (node.bl_idname == "GeometryNodeRepeatInput" and socket.name == "Iterations"
            and (type(value) is not int or not 0 <= value <= 64)):
        raise invalid_argument("Structured repeat zones allow 0-64 iterations.")
    assignments = prepare_assignments(
        socket,
        {"default_value": value},
        allowed=frozenset({"default_value"}),
        object_pointers=frozenset(),
        bpy=require_blender(),
    )
    apply_assignments(socket, assignments)
    index = next(index for index, item in enumerate(node.inputs) if item == socket)
    return {
        "input_set": True,
        "socket": shader_nodes._socket_summary(socket, index),
        **_post_state(tree, node),
    }


def remove_node(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "node_name", "allow_shared"})
    del context
    tree = _group(params, modify=True)
    node = shader_nodes._node_exact(tree, _name(params, "node_name"))
    name = node.name
    links_before = len(tree.links)
    if node.bl_idname in {"GeometryNodeRepeatInput", "GeometryNodeRepeatOutput", "GeometryNodeSimulationInput", "GeometryNodeSimulationOutput"}:
        raise invalid_argument("Remove paired zone boundaries with geometry_nodes.zone_remove.")
    tree.nodes.remove(node)
    return {
        "removed": name,
        "removed_link_count": links_before - len(tree.links),
        **_post_state(tree),
    }


def _check_link(tree: Any, source_node: Any, source: Any, target_node: Any, target: Any) -> None:
    numeric = {"VALUE", "INT", "BOOLEAN"}
    if source.type != target.type and not {source.type, target.type} <= numeric:
        raise invalid_argument(
            "Socket types are incompatible for this structured link.",
            from_type=source.type,
            to_type=target.type,
        )
    if not source.enabled or not target.enabled:
        raise invalid_argument("Cannot link a disabled socket; configure the node mode first.")
    # Reject graph cycles before Blender can create an invalid evaluation graph.
    edges: dict[str, set[str]] = {}
    for link in tree.links:
        edges.setdefault(link.from_node.name, set()).add(link.to_node.name)
    pending, seen = [target_node.name], set()
    while pending:
        name = pending.pop()
        if name == source_node.name:
            raise invalid_argument("This link would introduce a node-graph cycle.")
        if name not in seen:
            seen.add(name)
            pending.extend(edges.get(name, ()))


def link_nodes(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "from_node", "from_socket", "to_node", "to_socket", "replace_existing", "from_socket_index", "to_socket_index", "allow_shared"})
    del context
    tree = _group(params, modify=True)
    source_node, source = shader_nodes._endpoint(tree, params, "from", "output")
    target_node, target = shader_nodes._endpoint(tree, params, "to", "input")
    if target_node.bl_idname == "GeometryNodeRepeatInput" and target.name == "Iterations":
        raise invalid_argument("Repeat iterations must be a bounded constant, not a linked field.")
    replace = _boolean(params, "replace_existing")
    existing = [link for link in tree.links if link.to_socket == target]
    duplicate = next((link for link in existing if link.from_socket == source), None)
    if duplicate is not None:
        return {
            "linked": False,
            "already_exists": True,
            "link": shader_nodes._link_summary(duplicate),
            **_post_state(tree),
        }
    if len(tree.links) >= MAX_LINKS:
        raise invalid_argument("The graph has reached the link limit.", maximum=MAX_LINKS)
    if existing and not target.is_multi_input and not replace:
        raise invalid_argument(
            "The destination is already linked; explicitly set 'replace_existing'."
        )
    _check_link(tree, source_node, source, target_node, target)
    link = tree.links.new(source, target)
    return {
        "linked": True,
        "replaced_link_count": len(existing) if not target.is_multi_input else 0,
        "link": shader_nodes._link_summary(link),
        **_post_state(tree),
    }


def unlink_nodes(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "from_node", "from_socket", "to_node", "to_socket", "from_socket_index", "to_socket_index", "allow_shared"})
    del context
    tree = _group(params, modify=True)
    _, source = shader_nodes._endpoint(tree, params, "from", "output")
    _, target = shader_nodes._endpoint(tree, params, "to", "input")
    matches = [
        link for link in tree.links if link.from_socket == source and link.to_socket == target
    ]
    for link in matches:
        tree.links.remove(link)
    return {"removed_link_count": len(matches), **_post_state(tree)}


def attach_graph(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "object_name", "modifier_name", "replace_existing_group"})
    del context
    tree = _group(params)
    _safe_graph(tree)
    obj = get_object(_name(params, "object_name"), allow_active=False)
    _editable(obj)
    if obj.type not in {
        "MESH",
        "CURVE",
        "CURVES",
        "FONT",
        "SURFACE",
        "POINTCLOUD",
        "VOLUME",
        "GREASEPENCIL",
    }:
        raise invalid_argument(
            "This object type does not support a Geometry Nodes modifier.", object_type=obj.type
        )
    name = _name(params, "modifier_name")
    replace = _boolean(params, "replace_existing_group")
    if not any(
        item.item_type == "SOCKET"
        and item.in_out == "OUTPUT"
        and item.socket_type == "NodeSocketGeometry"
        for item in tree.interface.items_tree
    ):
        raise invalid_argument("An attached graph must expose a geometry output socket.")
    modifier = obj.modifiers.get(name)
    created = modifier is None
    previous = None
    if modifier is not None:
        if modifier.type != "NODES":
            raise invalid_argument(
                "An existing modifier with this name is not a Geometry Nodes modifier."
            )
        previous = modifier.node_group
        if previous is not None and previous != tree and not replace:
            raise invalid_argument(
                "The modifier already uses a different group; explicitly set 'replace_existing_group'."
            )
    elif len(obj.modifiers) >= 100:
        raise invalid_argument(
            "The object has reached the structured modifier limit.", maximum_modifiers=100
        )
    if created:
        modifier = obj.modifiers.new(name=name, type="NODES")
    try:
        modifier.node_group = tree
    except Exception:
        if created:
            obj.modifiers.remove(modifier)
        else:
            modifier.node_group = previous
        raise
    return {
        **_post_state(tree),
        "object": obj.name,
        "affected_objects": [obj.name],
        "modifier": {
            "name": modifier.name,
            "type": modifier.type,
            "node_group": modifier.node_group.name,
        },
        "created_modifier": created,
        "previous_group": previous.name if previous else None,
    }


def zone_create(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "zone_type", "input_name", "output_name", "iterations", "allow_shared"})
    tree = _group(params, modify=True)
    kind = params.get("zone_type")
    if not isinstance(kind, str) or kind not in {"REPEAT", "SIMULATION"}:
        raise invalid_argument("zone_type must be REPEAT or SIMULATION.")
    input_name, output_name = _name(params, "input_name"), _name(params, "output_name")
    if any(len(name.encode("utf-8")) > 63 for name in (input_name, output_name)):
        raise invalid_argument("Zone boundary names must fit 63 UTF-8 bytes.")
    iterations = int_param(params, "iterations", 1, minimum=0, maximum=64)
    if input_name == output_name or tree.nodes.get(input_name) or tree.nodes.get(output_name) or len(tree.nodes) > MAX_NODES - 2 or len(tree.links) >= MAX_LINKS:
        raise invalid_argument("Two distinct unused node names and graph capacity are required.")
    prefix = "GeometryNodeRepeat" if kind == "REPEAT" else "GeometryNodeSimulation"
    created = []
    try:
        output = tree.nodes.new(prefix + "Output")
        created.append(output)
        source = tree.nodes.new(prefix + "Input")
        created.append(source)
        source.name, output.name = input_name, output_name
        if not source.pair_with_output(output):
            raise invalid_argument("Blender refused the zone pairing.")
        if kind == "REPEAT":
            source.inputs["Iterations"].default_value = iterations
        tree.links.new(source.outputs["Geometry"], output.inputs["Geometry"])
        source.location, output.location = (-200, 0), (200, 0)
    except Exception:
        for node in reversed(created):
            tree.nodes.remove(node)
        raise
    return {"zone_type": kind, "input_name": source.name, "output_name": output.name, **_post_state(tree, output)}


def zone_item_add(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "output_name", "socket_type", "name", "allow_shared"})
    tree = _group(params, modify=True)
    output = shader_nodes._node_exact(tree, _name(params, "output_name"))
    items = getattr(output, "repeat_items", getattr(output, "state_items", None))
    kind, name = params.get("socket_type"), _name(params, "name")
    if items is None or not isinstance(kind, str) or kind not in {"GEOMETRY", "FLOAT", "INT", "BOOLEAN", "VECTOR", "RGBA"}:
        raise invalid_argument("Expected a zone output and a supported zone socket type.")
    if len(name.encode("utf-8")) > 63 or len(items) >= 32 or any(item.name == name for item in items):
        raise invalid_argument("Zone item name already exists or 32-item budget reached.")
    items.new(kind, name)
    return _post_state(tree, output)


def zone_remove(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "output_name", "allow_shared"})
    tree = _group(params, modify=True)
    output = shader_nodes._node_exact(tree, _name(params, "output_name"))
    if output.bl_idname not in {"GeometryNodeRepeatOutput", "GeometryNodeSimulationOutput"}:
        raise invalid_argument("Expected a repeat or simulation output node.")
    inputs = [node for node in tree.nodes if getattr(node, "paired_output", None) == output]
    names = [node.name for node in inputs] + [output.name]
    for node in inputs:
        tree.nodes.remove(node)
    tree.nodes.remove(output)
    return {"removed_nodes": names, **_post_state(tree)}


def zone_item_edit(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Rename/reorder zone items, or remove an unlinked non-geometry item."""
    operation = params.get("operation")
    options = {"RENAME": {"new_name"}, "MOVE": {"to_index"}, "REMOVE": set()}
    if not isinstance(operation, str) or operation not in options:
        raise invalid_argument("operation must be RENAME, MOVE or REMOVE.")
    reject_unknown_params(params, {"group_name", "output_name", "name", "operation", "allow_shared"} | options[operation])
    tree = _group(params, modify=True)
    output = shader_nodes._node_exact(tree, _name(params, "output_name"))
    items = getattr(output, "repeat_items", getattr(output, "state_items", None))
    name = _name(params, "name")
    if items is None or not 1 <= len(items) <= 32:
        raise invalid_argument("Expected a zone output with 1-32 items.")
    matches = [(index, item) for index, item in enumerate(items) if item.name == name]
    if len(matches) != 1:
        raise invalid_argument("Zone item name is missing or ambiguous.")
    old_index, item = matches[0]
    boundaries = [output, *[node for node in tree.nodes if getattr(node, "paired_output", None) == output]]
    if operation == "RENAME":
        new_name = _name(params, "new_name")
        reserved = {socket.name for node in boundaries for socket in (*node.inputs, *node.outputs) if socket.name != name}
        if len(new_name.encode("utf-8")) > 63 or new_name in reserved or any(i.name == new_name and i != item for i in items):
            raise invalid_argument("New item name collides with a socket/item or exceeds 63 UTF-8 bytes.")
        item.name = new_name
    elif operation == "MOVE":
        to_index = int_param(params, "to_index", -1, minimum=0, maximum=len(items) - 1)
        items.move(old_index, to_index)
    else:
        if item.socket_type == "GEOMETRY":
            raise invalid_argument("Geometry items cannot be removed by this scoped workflow.")
        if any(socket.is_linked for node in boundaries for socket in (*node.inputs, *node.outputs) if socket.name == name):
            raise invalid_argument("Unlink the item's sockets explicitly before removing it.")
        items.remove(item)
    return {"operation": operation, "previous_name": name, "previous_index": old_index,
            **_post_state(tree, output)}


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "geometry_nodes.inspect",
        inspect_graph,
        toolset="geometry_nodes",
        permissions=(Permission.INSPECT_SCENE,),
        description="Inspect a bounded Geometry Nodes graph, interface, and direct users.",
    )
    common = {"toolset": "geometry_nodes", "permissions": (Permission.EDIT_MESH,), "modifies": True}
    handlers = (
        (
            "create",
            create_graph,
            "Create an explicit geometry node group with geometry IO and optional passthrough.",
        ),
        (
            "interface_add",
            add_interface,
            "Add a typed input or output socket to an explicit geometry node group.",
        ),
        (
            "node_add",
            add_node,
            "Add a compatible built-in Geometry Nodes node with validated settings.",
        ),
        (
            "node_set_properties",
            set_node_properties,
            "Configure direct allowlisted scalar/enum properties of one geometry node.",
        ),
        (
            "node_set_input",
            set_node_input,
            "Set an exact geometry node input's scalar or vector default.",
        ),
        ("node_remove", remove_node, "Remove an exact geometry node and its incident links."),
        (
            "link",
            link_nodes,
            "Link exact compatible geometry-node sockets without introducing cycles.",
        ),
        ("unlink", unlink_nodes, "Remove links between exact geometry-node sockets."),
    )
    for name, handler, description in handlers:
        registry.register(f"geometry_nodes.{name}", handler, description=description, **common)
    for name, handler in (("zone_create", zone_create), ("zone_item_add", zone_item_add), ("zone_item_edit", zone_item_edit), ("zone_remove", zone_remove)):
        registry.register(f"geometry_nodes.{name}", handler, description=f"Structured paired Geometry Nodes {name}.", **common)
    registry.register(
        "geometry_nodes.attach",
        attach_graph,
        toolset="geometry_nodes",
        modifies=True,
        permissions=(Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS),
        description="Attach an explicit geometry node group to an exact named object modifier.",
    )


__all__ = ["register_tools"]
