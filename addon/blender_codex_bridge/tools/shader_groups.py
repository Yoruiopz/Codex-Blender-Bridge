"""Shader-group lifecycle and explicit instance isolation; no arbitrary scripts or file writes."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, int_param, reject_unknown_params, require_blender
from . import nodes
from .material_scope import local_editable
from .shader_scope import (
    MAX_GROUPS,
    MAX_LINKS,
    MAX_NODES,
    bounded_tree,
    editable,
    group_exact,
    name,
    object_mode,
    ownership,
)

LOGGER = logging.getLogger(__name__)
MAX_INTERFACE = 128
SOCKET_TYPES = frozenset({"NodeSocketFloat", "NodeSocketInt", "NodeSocketBool", "NodeSocketVector", "NodeSocketColor", "NodeSocketShader"})


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _interface(tree: Any) -> list[dict]:
    return [{"name": item.name, "identifier": getattr(item, "identifier", None), "item_type": item.item_type,
             "in_out": getattr(item, "in_out", None), "socket_type": getattr(item, "socket_type", None),
             "default_value": nodes._json_value(item.default_value) if hasattr(item, "default_value") else None}
            for item in islice(tree.interface.items_tree, MAX_INTERFACE)]


def _post(bpy: Any, tree: Any) -> dict:
    return {"group_name": tree.name, "node_count": len(tree.nodes), "link_count": len(tree.links),
            "interface_item_count": len(tree.interface.items_tree), "ownership": ownership(bpy, tree)}


def inspect(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"group_name", "max_nodes", "max_links", "max_sockets_per_direction"})
    bpy = require_blender()
    tree = group_exact(bpy, params.get("group_name"))
    graph = nodes._graph_inspection(tree, tree,
        max_nodes=int_param(params, "max_nodes", 100, minimum=1, maximum=MAX_NODES),
        max_links=int_param(params, "max_links", 300, minimum=1, maximum=MAX_LINKS),
        max_sockets=int_param(params, "max_sockets_per_direction", 32, minimum=1, maximum=64))
    graph.update({"graph_type": "SHADER_GROUP", "material": None, **_post(bpy, tree),
                  "interface": _interface(tree), "supported_interface_socket_types": sorted(SOCKET_TYPES)})
    graph["truncated_fields"]["interface"] = len(tree.interface.items_tree) > MAX_INTERFACE
    graph["truncated"] |= graph["truncated_fields"]["interface"] or not graph["ownership"]["coverage_complete"]
    _check(context)
    return graph


def _failed(exc: Exception, message: str, *, restored: bool, **scope: Any) -> BridgeError:
    return BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED, message,
                       {"execution_started": True, "rollback_verified": restored, "possible_mutation": not restored, **scope})


def create(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"group_name"})
    bpy = require_blender()
    object_mode(bpy)
    requested = name(params.get("group_name"), "group_name")
    if bpy.data.node_groups.get(requested) is not None:
        raise invalid_argument("A node group already has this name; no implicit reuse occurs.")
    _check(context)
    context.require(Permission.EDIT_MATERIALS)
    tree = None
    try:
        tree = bpy.data.node_groups.new(requested, "ShaderNodeTree")
        source = tree.nodes.new("NodeGroupInput")
        source.name, source.location = "Group Input", (-240, 0)
        output = tree.nodes.new("NodeGroupOutput")
        output.name, output.location, output.is_active_output = "Group Output", (240, 0), True
        _check(context)
        if tree.name != requested or len(tree.nodes) != 2 or tree.users != 0:
            raise RuntimeError("Shader-group creation readback mismatch")
        return {"created": True, **_post(bpy, tree)}
    except Exception as exc:
        LOGGER.exception("Shader-group creation failed")
        restored = False
        try:
            if tree is not None and tree.users == 0:
                bpy.data.node_groups.remove(tree, do_unlink=False)
                tree = None
            restored = tree is None and bpy.data.node_groups.get(requested) is None
        except Exception:
            LOGGER.exception("Shader-group creation cleanup failed")
        raise _failed(exc, "Shader-group creation failed; inspect group state.", restored=restored, group_name=requested) from exc


def interface_add(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"group_name", "name", "in_out", "socket_type", "default_value", "allow_shared"})
    bpy = require_blender()
    tree = group_exact(bpy, params.get("group_name"))
    editable(bpy, tree, params, context.check_cancelled)
    requested = name(params.get("name"), "name")
    direction, socket_type = params.get("in_out", "INPUT"), params.get("socket_type", "NodeSocketFloat")
    if not isinstance(direction, str) or direction not in {"INPUT", "OUTPUT"}:
        raise invalid_argument("'in_out' must be INPUT or OUTPUT.")
    if not isinstance(socket_type, str) or socket_type not in SOCKET_TYPES:
        raise invalid_argument("Unsupported shader interface socket type.", supported=sorted(SOCKET_TYPES))
    if len(tree.interface.items_tree) >= MAX_INTERFACE:
        raise invalid_argument("Shader interfaces support at most 128 items.")
    if any(i.item_type == "SOCKET" and i.name == requested and i.in_out == direction for i in tree.interface.items_tree):
        raise invalid_argument("An interface socket already has this name and direction.")
    _check(context)
    context.require(Permission.EDIT_MATERIALS)
    item = None
    try:
        item = tree.interface.new_socket(name=requested, in_out=direction, socket_type=socket_type)
        if "default_value" in params:
            item.default_value = nodes._coerce_default_value(item, params["default_value"])
        _check(context)
        if item.name != requested or item.in_out != direction or item.socket_type != socket_type:
            raise RuntimeError("Interface socket creation readback mismatch")
        return {"added_identifier": item.identifier, "interface": _interface(tree), **_post(bpy, tree)}
    except Exception as exc:
        LOGGER.exception("Shader interface addition failed")
        try:
            if item is not None:
                tree.interface.remove(item)
        except Exception:
            LOGGER.exception("Shader interface cleanup failed")
        # Updating an interface may also rebuild external instances; local cleanup is not a global rollback proof.
        raise _failed(exc, "Shader interface addition failed; reinspect group and instances or recover the checkpoint.",
                      restored=False, group_name=tree.name) from exc


def _dependencies(context: ToolContext, tree: Any, target: Any) -> list[dict]:
    from .images import binding_source
    from .shader_scope import _key

    pending, seen, images, sources = [(tree, ())], set(), set(), []
    while pending:
        _check(context)
        current, ancestors = pending.pop()
        if current == target:
            raise invalid_argument("Binding would create a recursive shader-group dependency.")
        key = _key(current)
        if key in ancestors:
            raise invalid_argument("Shader dependencies contain a recursive group reference.")
        if key in seen:
            continue
        if len(seen) >= MAX_GROUPS:
            raise invalid_argument("Shader dependency review exceeds 32 groups.")
        seen.add(key)
        if current.bl_idname != "ShaderNodeTree" or not local_editable(current):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding requires local editable shader-group dependencies.")
        bounded_tree(current)
        for node in current.nodes:
            if node.bl_idname in {"ShaderNodeScript", "ShaderNodeTexIES"}:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Script/IES group dependencies are not reviewed for structured binding.")
            child = getattr(node, "node_tree", None)
            if child is not None:
                pending.append((child, (*ancestors, key)))
            image = getattr(node, "image", None)
            if image is not None and _key(image) not in images:
                if len(images) >= 16:
                    raise invalid_argument("Shader-group binding supports at most 16 distinct loaded images.")
                images.add(_key(image))
                source = binding_source(context, image)
                if source is not None:
                    sources.append({"image_name": image.name, **source})
    return sources


def _links(tree: Any) -> list[tuple]:
    return sorted((link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
                  for link in tree.links)


def _inputs(node: Any) -> list[tuple]:
    if len(node.inputs) > MAX_INTERFACE:
        raise invalid_argument("Group instance inputs exceed 128 sockets.")
    result = []
    for socket in node.inputs:
        value = None
        if hasattr(socket, "default_value"):
            value = nodes._coerce_default_value(socket, nodes._json_value(socket.default_value))
        result.append((socket.identifier, value))
    return result


def bind(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"material_name", "node_name", "group_name", "group_path", "allow_shared"})
    if "group_name" not in params:
        raise invalid_argument("'group_name' is required; explicit null clears an unlinked binding.")
    bpy = require_blender()
    object_mode(bpy)
    material, tree = nodes._target_graph(context, params, modify=True)
    bounded_tree(tree)
    node = nodes._node_exact(tree, name(params.get("node_name"), "node_name"))
    if node.bl_idname != "ShaderNodeGroup":
        raise invalid_argument("Target must be an exact ShaderNodeGroup instance.")
    if any(link.from_node == node or link.to_node == node for link in tree.links):
        raise invalid_argument("Binding replacement requires an unlinked group node; no incident links are discarded implicitly.")
    group = group_exact(bpy, params["group_name"]) if params["group_name"] is not None else None
    previous = node.node_tree
    if group is not None and previous is not None and group != previous:
        raise invalid_argument("Explicitly clear the unlinked previous binding before assigning a different group.")
    sources = _dependencies(context, group, tree) if group is not None else []
    links, previous_inputs = _links(tree), _inputs(node)
    _check(context)
    context.require(Permission.EDIT_MATERIALS, *((Permission.ACCESS_EXTERNAL_FILES,) if sources else ()))
    try:
        node.node_tree = group
        _check(context)
        if node.node_tree != group or _links(tree) != links:
            raise RuntimeError("Group binding readback mismatch")
        return {"bound_group": group.name if group else None, "source_files_at_binding": sources,
                "file_written": False, **nodes._post_state(material, tree, node)}
    except Exception as exc:
        LOGGER.exception("Shader-group binding failed")
        restored = False
        try:
            node.node_tree = previous
            restored = node.node_tree == previous and _links(tree) == links and _inputs(node) == previous_inputs
        except Exception:
            LOGGER.exception("Shader-group binding restoration failed")
        raise _failed(exc, "Shader-group binding failed; reinspect the instance.", restored=restored,
                      material_name=material.name, node_name=node.name) from exc


def copy_for_node(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"material_name", "node_name", "new_name", "group_path", "allow_shared"})
    bpy = require_blender()
    object_mode(bpy)
    material, tree = nodes._target_graph(context, params, modify=True)
    bounded_tree(tree)
    node = nodes._node_exact(tree, name(params.get("node_name"), "node_name"))
    if node.bl_idname != "ShaderNodeGroup" or node.node_tree is None:
        raise invalid_argument("Target must be an exact bound ShaderNodeGroup instance.")
    requested = name(params.get("new_name"), "new_name")
    if bpy.data.node_groups.get(requested) is not None:
        raise invalid_argument("The requested group name already exists.")
    original = node.node_tree
    sources = _dependencies(context, original, tree)
    links, inputs = _links(tree), _inputs(node)
    original_users = original.users
    copy = None
    _check(context)
    context.require(Permission.EDIT_MATERIALS, *((Permission.ACCESS_EXTERNAL_FILES,) if sources else ()))
    try:
        copy = original.copy()
        copy.name, copy.use_fake_user = requested, False
        node.node_tree = copy
        _check(context)
        if (node.node_tree != copy or copy.name != requested or copy.users != 1 or not local_editable(copy)
                or original.users != original_users - 1 or _links(tree) != links or _inputs(node) != inputs):
            raise RuntimeError("Shader group isolation did not preserve binding, instance values and links")
        return {"copied_from": original.name, "copied_group": copy.name, "nested_data_copied": False,
                "group": _post(bpy, copy), "source_files_at_binding": sources, **nodes._post_state(material, tree, node)}
    except Exception as exc:
        LOGGER.exception("Shader group isolation failed")
        restored = False
        try:
            node.node_tree = original
            if copy is not None and copy.users == 0:
                bpy.data.node_groups.remove(copy, do_unlink=False)
                copy = None
            restored = (copy is None and node.node_tree == original and original.users == original_users
                        and _links(tree) == links and _inputs(node) == inputs)
        except Exception:
            LOGGER.exception("Shader group isolation restoration failed")
        raise _failed(exc, "Shader group isolation failed; reinspect material and group users.", restored=restored,
                      material_name=material.name, requested_group=requested) from exc


def remove(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"group_name", "confirm_unused"})
    bpy = require_blender()
    object_mode(bpy)
    tree = group_exact(bpy, params.get("group_name"))
    if not bool_param(params, "confirm_unused", False):
        raise invalid_argument("Set confirm_unused=true to remove this exact unused shader-group datablock.")
    if not local_editable(tree) or tree.users or tree.use_fake_user:
        raise invalid_argument("Only unused local editable groups without a fake user may be removed; no forced unlink.")
    _check(context)
    context.require(Permission.EDIT_MATERIALS, Permission.DELETE_OBJECTS)
    group_name = tree.name
    bpy.data.node_groups.remove(tree, do_unlink=False)
    return {"removed_group": group_name, "remaining_same_name": sum(g.name == group_name for g in bpy.data.node_groups),
            "nested_data_removed": False, "file_deleted": False}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("shader_group.inspect", inspect, toolset="nodes", permissions=(Permission.INSPECT_SCENE,),
                      description="Inspect a bounded shader-group graph, interface and parent/material/world/light ownership evidence.")
    for method, handler, description in (
        ("create", create, "Create a new empty local shader group with input/output nodes."),
        ("interface_add", interface_add, "Add one typed interface socket to an explicitly scoped shader group."),
        ("bind", bind, "Bind/clear an exact unlinked shader-group instance after dependency/file-policy checks."),
        ("copy_for_node", copy_for_node, "Isolate one shader-group instance, preserving input defaults and graph links; nested data remains shared."),
        ("remove", remove, "Remove an explicitly confirmed unused shader-group datablock without unlinking users or deleting nested data."),
    ):
        permissions = (Permission.EDIT_MATERIALS, Permission.DELETE_OBJECTS) if method == "remove" else (Permission.EDIT_MATERIALS,)
        registry.register(f"shader_group.{method}", handler, toolset="nodes", modifies=True,
                          permissions=permissions, description=description)
