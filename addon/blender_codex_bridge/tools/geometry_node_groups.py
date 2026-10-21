"""Bounded nested GN instances and object-owned modifier inputs.

Only exact socket identifiers and the reviewed Geometry Nodes allowlist are used.
No RNA paths, file nodes, implicit deep copies or arbitrary scripts are exposed.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, reject_unknown_params, require_blender
from . import geometry_nodes as gn
from . import nodes
from ._object_safety import require_local_object
from .shader_scope import name

LOGGER = logging.getLogger(__name__)
MAX_TREES = 32
MAX_DEPTH = 8
MAX_NODES = 256
MAX_LINKS = 1024
MAX_USERS = 100
SCALAR_TYPES = frozenset({"NodeSocketFloat", "NodeSocketInt", "NodeSocketBool", "NodeSocketVector", "NodeSocketColor", "NodeSocketString"})


def _key(owner: Any) -> int:
    return int(owner.as_pointer()) if hasattr(owner, "as_pointer") else id(owner)


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _gate(context: ToolContext, *required: Permission) -> None:
    _check(context)
    flags = context.state.snapshot()
    if flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Geometry Nodes mutation emergency-stopped.")
    if flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Geometry Nodes mutation paused.")
    context.require(*required)


def _local(owner: Any) -> bool:
    return (getattr(owner, "library", None) is None and getattr(owner, "override_library", None) is None
            and bool(getattr(owner, "is_editable", True)))


def _object_mode(bpy: Any) -> None:
    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Nested GN mutations require Object Mode for verified recovery.")


def _group(bpy: Any, raw: Any) -> Any:
    exact = name(raw, "group_name")
    matches = list(islice((item for item in bpy.data.node_groups if item.name == exact), 2))
    if len(matches) != 1 or matches[0].bl_idname != "GeometryNodeTree":
        raise invalid_argument("Expected one exact GeometryNodeTree without library-name ambiguity.", group_name=exact)
    return matches[0]


def _review(tree: Any, context: ToolContext) -> list[str]:
    """Validate all reachable definitions before a new evaluation dependency is introduced."""
    visited: set[int] = set()
    names: list[str] = []

    def walk(current: Any, ancestors: tuple[int, ...]):
        _check(context)
        key = _key(current)
        if key in ancestors:
            raise invalid_argument("Recursive Geometry Nodes group dependencies are unsupported.")
        if len(ancestors) > MAX_DEPTH:
            raise invalid_argument("Geometry Nodes dependency depth exceeds eight.")
        if key in visited:
            return
        if len(visited) >= MAX_TREES:
            raise invalid_argument("Geometry Nodes dependency scope exceeds 32 groups.")
        visited.add(key)
        if current.bl_idname != "GeometryNodeTree" or not _local(current):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Nested GN requires local editable non-override group dependencies.")
        if len(current.nodes) > MAX_NODES or len(current.links) > MAX_LINKS or len(current.interface.items_tree) > 128:
            raise invalid_argument("Nested GN supports 256 nodes, 1024 links and 128 interface items per tree.")
        names.append(current.name)
        for node in current.nodes:
            _check(context)
            if len(node.inputs) > 128 or len(node.outputs) > 128:
                raise invalid_argument("GN node socket scope exceeds 128 per direction.")
            if node.bl_idname == "GeometryNodeGroup":
                child = node.node_tree
                if child is None:
                    raise invalid_argument("Nested Geometry Nodes instances must have an explicit group binding.")
                walk(child, (*ancestors, key))
            elif node.bl_idname not in gn._SAFE_NODE_TYPES:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "GN dependency contains an unreviewed node; file/import/script nodes remain unsupported.", {"node_type": node.bl_idname})
            elif node.bl_idname in {"GeometryNodeRepeatInput", "GeometryNodeSimulationInput"}:
                if node.paired_output is None:
                    raise invalid_argument("Zone input has no paired output.")
                if node.bl_idname == "GeometryNodeRepeatInput":
                    iterations = node.inputs.get("Iterations")
                    if iterations is None or iterations.is_linked or not 0 <= iterations.default_value <= 64:
                        raise invalid_argument("Repeat zones require an unlinked constant iteration count from 0 to 64.")

    walk(tree, ())
    return names


def _ownership(bpy: Any, tree: Any, context: ToolContext) -> dict[str, Any]:
    pending = deque([tree])
    visited: set[int] = set()
    owners: dict[int, Any] = {}
    parent_groups: list[str] = []
    other_owners: list[dict[str, str]] = []
    while pending:
        _check(context)
        current = pending.popleft()
        if _key(current) in visited:
            continue
        if len(visited) >= MAX_TREES:
            raise invalid_argument("Parent GN ownership exceeds 32 groups; isolate the graph first.")
        visited.add(_key(current))
        if not _local(current):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "GN changes cannot affect linked, override or read-only parent groups.")
        direct = bpy.data.user_map(subset={current}).get(current, set())
        if len(direct) > MAX_USERS:
            raise invalid_argument("GN ownership exceeds 100 direct consumers; narrow the scope.")
        for owner in direct:
            _check(context)
            if _key(owner) not in owners and len(owners) >= MAX_USERS:
                raise invalid_argument("GN ownership exceeds 100 consumers; narrow the scope.")
            owners[_key(owner)] = owner
            if not _local(owner):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "GN changes cannot affect linked, override or read-only consumers.", {"owner": owner.name})
            if getattr(owner, "bl_idname", None) == "GeometryNodeTree":
                parent_groups.append(owner.name)
                pending.append(owner)
            elif getattr(getattr(owner, "bl_rna", None), "identifier", None) != "Object":
                other_owners.append({"name": owner.name, "type": getattr(getattr(owner, "bl_rna", None), "identifier", "unknown")})
    objects = sorted(owner.name for owner in owners.values() if getattr(getattr(owner, "bl_rna", None), "identifier", None) == "Object")
    return {"affected_objects": objects, "parent_groups": sorted(set(parent_groups)), "other_owners": other_owners,
            "requires_shared_consent": (int(tree.users) - int(bool(getattr(tree, "use_fake_user", False))) > 1 or bool(parent_groups)
                                         or len(objects) > 1 or bool(other_owners)),
            "coverage_complete": True,
            "scope": "Parent GN groups and direct object consumers; collection/geometry instances and evaluated transitive effects require independent inspection."}


def _editable(bpy: Any, tree: Any, context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    _object_mode(bpy)
    _review(tree, context)
    scope = _ownership(bpy, tree, context)
    if scope["requires_shared_consent"] and not bool_param(params, "allow_shared", False):
        raise invalid_argument("Inspect users and set allow_shared only when every affected consumer is in scope.", **scope)
    # Validate even when unshared so malformed consent never succeeds accidentally.
    bool_param(params, "allow_shared", False)
    return scope


def _socket(collection: Any, identifier: Any) -> Any:
    text = name(identifier, "socket_identifier")
    if len(collection) > 128:
        raise invalid_argument("GN socket scope exceeds 128 entries.")
    matches = [socket for socket in collection if getattr(socket, "identifier", None) == text]
    if len(matches) != 1:
        raise invalid_argument("Socket identifier is missing or ambiguous; inspect the current interface first.", socket_identifier=text)
    return matches[0]


def _value(socket: Any, raw: Any) -> Any:
    kind = getattr(socket, "socket_type", getattr(socket, "bl_socket_idname", getattr(socket, "bl_idname", None)))
    if not hasattr(socket, "socket_type"):
        kind = {"VALUE": "NodeSocketFloat", "INT": "NodeSocketInt", "BOOLEAN": "NodeSocketBool",
                "VECTOR": "NodeSocketVector", "RGBA": "NodeSocketColor", "STRING": "NodeSocketString"}.get(getattr(socket, "type", None), kind)
    # Runtime socket subclasses include FloatFactor/FloatDistance etc; interface
    # socket_type is the authoritative reviewed base type for modifier values.
    if kind not in SCALAR_TYPES or not hasattr(socket, "default_value"):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Only explicit scalar/vector/color/string GN defaults are supported.", {"socket_type": kind})
    if kind == "NodeSocketBool":
        if type(raw) is not bool:
            raise invalid_argument("Boolean GN input requires a boolean.")
    elif kind == "NodeSocketInt":
        if type(raw) is not int or not -(2**31) <= raw < 2**31:
            raise invalid_argument("Integer GN input requires a signed 32-bit integer.")
    elif kind == "NodeSocketFloat":
        if isinstance(raw, bool) or not isinstance(raw, (float, int)) or abs(raw) > 1e20 or not math.isfinite(raw):
            raise invalid_argument("Float GN input requires a finite number with magnitude at most 1e20.")
        raw = float(raw)
    elif kind in {"NodeSocketVector", "NodeSocketColor"}:
        count = 3 if kind == "NodeSocketVector" else 4
        if (not isinstance(raw, list) or len(raw) != count or any(isinstance(item, bool) or not isinstance(item, (float, int)) or abs(item) > 1e20 or not math.isfinite(item) for item in raw)):
            raise invalid_argument(f"GN input requires {count} finite numeric components with magnitude at most 1e20.")
        raw = [float(item) for item in raw]
    elif not isinstance(raw, str) or len(raw) > 1024 or any(ord(char) < 32 for char in raw):
        raise invalid_argument("String GN input requires at most 1024 printable characters.")
    return raw


def _read(value: Any) -> Any:
    if isinstance(value, str) and len(value) > 1024:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Stored GN string exceeds its 1024-character evidence bound.")
    if isinstance(value, float) and not math.isfinite(value):
        raise invalid_argument("Stored GN value is not finite.")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "__len__") and len(value) <= 4:
        result = [float(item) for item in value]
        if not all(math.isfinite(item) for item in result):
            raise invalid_argument("Stored GN vector is not finite.")
        return result
    raise invalid_argument("GN value cannot be represented in the reviewed scalar/vector scope.")


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, (float, int)) and not isinstance(a, bool) and isinstance(b, (float, int)) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=2e-6, abs_tol=1e-7)
    return type(a) is type(b) and a == b


def _post(tree: Any, scope: dict[str, Any]) -> dict[str, Any]:
    return {"group_name": tree.name, "node_count": len(tree.nodes), "link_count": len(tree.links), "ownership": scope,
            "affected_objects": scope["affected_objects"], "verification_required": True,
            "evaluation_verified": False, "project_saved": False}


def _failed(error: Exception, message: str, *, restored: bool = False, **evidence: Any) -> BridgeError:
    return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED, message,
                       {"execution_started": True, "rollback_verified": restored, "possible_mutation": not restored,
                        "verification_required": True, **evidence})


def group_bind(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"parent_group_name", "child_group_name", "node_name", "allow_shared"})
    bpy = require_blender()
    parent, child = _group(bpy, params.get("parent_group_name")), _group(bpy, params.get("child_group_name"))
    scope = _editable(bpy, parent, context, params)
    dependencies = _review(child, context)
    if parent.name in dependencies:
        raise invalid_argument("Binding would introduce a recursive GN group dependency.")
    if len(set(_review(parent, context)) | set(dependencies)) > MAX_TREES:
        raise invalid_argument("Combined GN dependency scope exceeds 32 groups.")
    requested = name(params.get("node_name"), "node_name")
    if parent.nodes.get(requested) is not None or len(parent.nodes) >= MAX_NODES:
        raise invalid_argument("An unused exact node name and node capacity are required.")
    _gate(context, Permission.EDIT_MESH)
    node = None
    try:
        node = parent.nodes.new("GeometryNodeGroup")
        node.name, node.node_tree = requested, child
        _gate(context, Permission.EDIT_MESH)
        _review(parent, context)
        if node.name != requested or node.node_tree != child:
            raise RuntimeError("GN instance binding readback mismatch")
        return {"bound": True, "node_name": node.name, "child_group_name": child.name,
                "inputs": [{"identifier": item.identifier, "name": item.name} for item in node.inputs], **_post(parent, scope)}
    except Exception as error:
        LOGGER.exception("GN group binding failed")
        restored = False
        try:
            context.require(Permission.EDIT_MESH)
            if node is not None:
                parent.nodes.remove(node)
            restored = parent.nodes.get(requested) is None
        except Exception:
            LOGGER.exception("GN instance cleanup failed")
        raise _failed(error, "GN group binding failed; reinspect the parent graph.", restored=restored, retained_node=None if restored else requested) from error


def group_copy_for_node(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"parent_group_name", "node_name", "new_group_name", "allow_shared"})
    bpy = require_blender()
    parent = _group(bpy, params.get("parent_group_name"))
    scope = _editable(bpy, parent, context, params)
    node = parent.nodes.get(name(params.get("node_name"), "node_name"))
    if node is None or node.bl_idname != "GeometryNodeGroup" or node.node_tree is None:
        raise invalid_argument("Expected an exact bound GeometryNodeGroup instance.")
    original = node.node_tree
    requested = name(params.get("new_group_name"), "new_group_name")
    if any(tree.name == requested for tree in bpy.data.node_groups):
        raise invalid_argument("The new group name already exists; no implicit reuse occurs.")
    before = {item.identifier: _read(item.default_value) for item in node.inputs if hasattr(item, "default_value")}
    links = [(link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) for link in parent.links]
    clone = None
    _gate(context, Permission.EDIT_MESH)
    try:
        clone = original.copy()
        clone.name = requested
        node.node_tree = clone
        _gate(context, Permission.EDIT_MESH)
        after = {item.identifier: _read(item.default_value) for item in node.inputs if hasattr(item, "default_value")}
        now_links = [(link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) for link in parent.links]
        if clone.name != requested or node.node_tree != clone or before != after or links != now_links:
            raise RuntimeError("GN instance copy changed socket defaults, identifiers or graph links")
        _review(parent, context)
        return {"copied": True, "node_name": node.name, "previous_group": original.name, "new_group_name": clone.name,
                "deep_copy": False, "nested_dependencies_retained": _review(clone, context)[1:], **_post(parent, scope)}
    except Exception as error:
        LOGGER.exception("GN instance copy failed")
        rebound, removed, cleanup_denied = False, clone is None, False
        try:
            context.require(Permission.EDIT_MESH)
            node.node_tree = original
            rebound = (node.node_tree == original and before == {item.identifier: _read(item.default_value) for item in node.inputs if hasattr(item, "default_value")}
                       and links == [(link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) for link in parent.links])
            if clone is not None and clone.users == 0 and not clone.use_fake_user:
                try:
                    context.require(Permission.DELETE_OBJECTS)
                except BridgeError:
                    cleanup_denied = True
                else:
                    bpy.data.node_groups.remove(clone, do_unlink=False)
                    removed = True
        except Exception:
            LOGGER.exception("GN instance copy recovery failed")
        raise _failed(error, "GN instance copy failed; inspect binding and retained group evidence.", restored=rebound and removed,
                      binding_restored=rebound, cleanup_denied=cleanup_denied, retained_group=None if removed else requested) from error


def group_link(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "from_node", "from_socket_identifier", "to_node", "to_socket_identifier", "replace_existing", "allow_shared"})
    bpy = require_blender()
    tree = _group(bpy, params.get("group_name"))
    scope = _editable(bpy, tree, context, params)
    source_node = nodes._node_exact(tree, name(params.get("from_node"), "from_node"))
    target_node = nodes._node_exact(tree, name(params.get("to_node"), "to_node"))
    source = _socket(source_node.outputs, params.get("from_socket_identifier"))
    target = _socket(target_node.inputs, params.get("to_socket_identifier"))
    if target.is_multi_input:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Nested GN links to multi-input sockets require a separate verified ordering/recovery workflow.")
    if target_node.bl_idname == "GeometryNodeRepeatInput" and target.name == "Iterations":
        raise invalid_argument("Repeat iterations must remain an unlinked bounded constant.")
    replace = bool_param(params, "replace_existing", False)
    previous = [(link.from_socket, link.to_socket) for link in tree.links if link.to_socket == target]
    if any(old_source == source for old_source, _ in previous):
        return {"linked": False, "already_exists": True, **_post(tree, scope)}
    if len(tree.links) >= MAX_LINKS or (previous and not target.is_multi_input and not replace):
        raise invalid_argument("Link capacity or destination binding requires explicit review/replacement.")
    gn._check_link(tree, source_node, source, target_node, target)
    _gate(context, Permission.EDIT_MESH)
    link = None
    try:
        link = tree.links.new(source, target)
        _gate(context, Permission.EDIT_MESH)
        if not any(item.from_socket == source and item.to_socket == target for item in tree.links):
            raise RuntimeError("GN link readback mismatch")
        return {"linked": True, "replaced_link_count": len(previous) if not target.is_multi_input else 0, "link": nodes._link_summary(link), **_post(tree, scope)}
    except Exception as error:
        LOGGER.exception("GN link failed")
        restored = False
        try:
            context.require(Permission.EDIT_MESH)
            if link is not None:
                tree.links.remove(link)
            for old_source, old_target in previous:
                if not any(item.from_socket == old_source and item.to_socket == old_target for item in tree.links):
                    tree.links.new(old_source, old_target)
            restored = [(item.from_socket, item.to_socket) for item in tree.links if item.to_socket == target] == previous
        except Exception:
            LOGGER.exception("GN link recovery failed")
        raise _failed(error, "GN link failed; reinspect links and recover the checkpoint if needed.", restored=restored) from error


def group_set_input(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "node_name", "socket_identifier", "value", "allow_shared"})
    bpy = require_blender()
    tree = _group(bpy, params.get("group_name"))
    scope = _editable(bpy, tree, context, params)
    node = nodes._node_exact(tree, name(params.get("node_name"), "node_name"))
    socket = _socket(node.inputs, params.get("socket_identifier"))
    if getattr(socket, "is_linked", False) or not getattr(socket, "enabled", True):
        raise invalid_argument("GN default editing requires an enabled, unlinked input.")
    value = _value(socket, params.get("value"))
    if node.bl_idname == "GeometryNodeRepeatInput" and socket.name == "Iterations" and (type(value) is not int or not 0 <= value <= 64):
        raise invalid_argument("Repeat iterations must remain an integer from 0 to 64.")
    previous = _read(socket.default_value)
    _gate(context, Permission.EDIT_MESH)
    try:
        socket.default_value = value
        _gate(context, Permission.EDIT_MESH)
        observed = _read(socket.default_value)
        if not _same(observed, value):
            raise RuntimeError("GN input assignment was clamped or changed")
        return {"input_set": True, "node_name": node.name, "socket_identifier": socket.identifier,
                "previous_value": previous, "value": observed, **_post(tree, scope)}
    except Exception as error:
        LOGGER.exception("GN socket edit failed")
        restored = False
        try:
            context.require(Permission.EDIT_MESH)
            socket.default_value = previous
            restored = _same(_read(socket.default_value), previous)
        except Exception:
            LOGGER.exception("GN socket recovery failed")
        raise _failed(error, "GN input edit failed; inspect the node and recovery evidence.", restored=restored) from error


def group_remove(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "confirm_unused"})
    bpy = require_blender()
    _object_mode(bpy)
    tree = _group(bpy, params.get("group_name"))
    if not bool_param(params, "confirm_unused", False) or not _local(tree) or tree.users != 0 or tree.use_fake_user:
        raise invalid_argument("Removal requires confirm_unused=true and a local editable unused group without fake-user retention.")
    _gate(context, Permission.EDIT_MESH, Permission.DELETE_OBJECTS)
    requested = tree.name
    try:
        bpy.data.node_groups.remove(tree, do_unlink=False)
        if any(item.name == requested for item in bpy.data.node_groups):
            raise RuntimeError("GN group removal readback mismatch")
    except Exception as error:
        LOGGER.exception("GN group removal failed")
        raise _failed(error, "GN group removal failed; reinspect before recovery.") from error
    return {"removed": requested, "forced_unlink": False, "affected_objects": [], "verification_required": True}


def _modifier(bpy: Any, params: Mapping[str, Any], *, modify: bool) -> tuple[Any, Any, Any]:
    exact = name(params.get("object_name"), "object_name")
    matches = list(islice((obj for obj in bpy.context.scene.objects if obj.name == exact), 2))
    if len(matches) != 1:
        raise invalid_argument("Object must resolve exactly in the current scene.")
    obj = matches[0]
    if modify:
        _object_mode(bpy)
        require_local_object(obj, operation="GN modifier editing")
    modifier = obj.modifiers.get(name(params.get("modifier_name"), "modifier_name"))
    if modifier is None or modifier.type != "NODES" or modifier.node_group is None:
        raise invalid_argument("Expected an exact GN modifier with an explicit group binding.")
    tree = modifier.node_group
    if len(tree.interface.items_tree) > 128:
        raise invalid_argument("GN interface exceeds 128 items.")
    return obj, modifier, tree


def _input_summary(modifier: Any, socket: Any) -> dict[str, Any]:
    identifier = socket.identifier
    supported = socket.socket_type in SCALAR_TYPES
    return {"identifier": identifier, "name": socket.name, "socket_type": socket.socket_type,
            "supported_constant": supported,
            "value": _read(modifier.get(identifier, socket.default_value)) if supported else None,
            "use_attribute": bool(modifier.get(identifier + "_use_attribute", False)),
            "attribute_name": str(modifier.get(identifier + "_attribute_name", ""))[:1024],
            "attribute_name_truncated": len(str(modifier.get(identifier + "_attribute_name", ""))) > 1024}


def _modifier_properties(modifier: Any) -> dict[str, Any]:
    if len(modifier.keys()) > 512:
        raise invalid_argument("Modifier property evidence exceeds 512 keys.")
    keys = list(modifier.keys())
    return {key: _read(modifier[key]) for key in keys}


def modifier_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "modifier_name"})
    bpy = require_blender()
    obj, modifier, tree = _modifier(bpy, params, modify=False)
    _check(context)
    inputs = [_input_summary(modifier, item) for item in tree.interface.items_tree if item.item_type == "SOCKET" and item.in_out == "INPUT"]
    return {"object": obj.name, "modifier_name": modifier.name, "group_name": tree.name, "inputs": inputs,
            "scope": "Stored modifier/interface values, not evaluated geometry or complete nested ownership.", "truncated": False}


def modifier_set_input(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "modifier_name", "socket_identifier", "value"})
    bpy = require_blender()
    obj, modifier, tree = _modifier(bpy, params, modify=True)
    _review(tree, context)
    socket = _socket(tree.interface.items_tree, params.get("socket_identifier"))
    if socket.item_type != "SOCKET" or socket.in_out != "INPUT":
        raise invalid_argument("Modifier input must identify an input interface socket.")
    identifier = socket.identifier
    value = _value(socket, params.get("value"))
    if modifier.get(identifier + "_use_attribute", False):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Attribute-driven modifier inputs require a separate explicit workflow; constant editing will not disable them silently.")
    if getattr(obj, "animation_data", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "GN modifier constant editing currently requires an unanimated object for verified recovery.")
    existed = identifier in modifier
    previous = _read(modifier.get(identifier, socket.default_value))
    _gate(context, Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS)
    try:
        modifier[identifier] = value
        obj.update_tag()
        _gate(context, Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS)
        observed = _read(modifier[identifier])
        if not _same(observed, value) or modifier.node_group != tree:
            raise RuntimeError("GN modifier input readback mismatch")
        return {"object": obj.name, "modifier_name": modifier.name, "group_name": tree.name,
                "socket_identifier": identifier, "previous_value": previous, "value": observed,
                "affected_objects": [obj.name], "group_definition_changed": False, "verification_required": True,
                "evaluation_verified": False, "project_saved": False}
    except Exception as error:
        LOGGER.exception("GN modifier input edit failed")
        restored = False
        try:
            context.require(Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS)
            if existed:
                modifier[identifier] = previous
            elif identifier in modifier:
                del modifier[identifier]
            obj.update_tag()
            restored = _same(_read(modifier.get(identifier, socket.default_value)), previous)
        except Exception:
            LOGGER.exception("GN modifier input recovery failed")
        raise _failed(error, "GN modifier input edit failed; inspect the object and recovery evidence.", restored=restored) from error


def group_attach(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"group_name", "object_name", "modifier_name", "replace_existing_group"})
    bpy = require_blender()
    _object_mode(bpy)
    tree = _group(bpy, params.get("group_name"))
    dependencies = _review(tree, context)
    exact = name(params.get("object_name"), "object_name")
    objects = list(islice((obj for obj in bpy.context.scene.objects if obj.name == exact), 2))
    if len(objects) != 1 or objects[0].type != "MESH":
        raise invalid_argument("Nested GN attachment currently requires one exact mesh object.")
    obj = objects[0]
    require_local_object(obj, operation="Nested GN attachment")
    if not any(item.item_type == "SOCKET" and item.in_out == "OUTPUT" and item.socket_type == "NodeSocketGeometry" for item in tree.interface.items_tree):
        raise invalid_argument("An attached GN tree requires a geometry output.")
    requested = name(params.get("modifier_name"), "modifier_name")
    replace = bool_param(params, "replace_existing_group", False)
    modifier = obj.modifiers.get(requested)
    created = modifier is None
    previous = None if created else modifier.node_group if modifier.type == "NODES" else None
    if (not created and modifier.type != "NODES") or (previous is not None and previous != tree and not replace):
        raise invalid_argument("An existing modifier requires the correct type and explicit replacement consent.")
    if created and len(obj.modifiers) >= 100:
        raise invalid_argument("Object exceeds the 100-modifier budget.")
    old_properties = {}
    if not created:
        if getattr(obj, "animation_data", None) is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "GN attachment replacement requires an unanimated object for verified recovery.")
        old_properties = _modifier_properties(modifier)
    _gate(context, Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS)
    try:
        if created:
            modifier = obj.modifiers.new(requested, "NODES")
        modifier.node_group = tree
        _gate(context, Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS)
        if modifier.node_group != tree or modifier.name != requested:
            raise RuntimeError("GN modifier attachment readback mismatch")
        return {"object": obj.name, "modifier_name": modifier.name, "group_name": tree.name, "created_modifier": created,
                "previous_group": previous.name if previous else None, "dependencies": dependencies,
                "affected_objects": [obj.name], "verification_required": True, "evaluation_verified": False}
    except Exception as error:
        LOGGER.exception("GN attachment failed")
        restored = False
        try:
            context.require(Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS)
            if created and modifier is not None:
                obj.modifiers.remove(modifier)
                restored = obj.modifiers.get(requested) is None
            elif modifier is not None:
                modifier.node_group = previous
                for key in list(modifier.keys()):
                    if key not in old_properties:
                        del modifier[key]
                for key, value in old_properties.items():
                    modifier[key] = value
                restored = modifier.node_group == previous and old_properties == _modifier_properties(modifier)
        except Exception:
            LOGGER.exception("GN modifier attachment recovery failed")
        raise _failed(error, "GN attachment failed; inspect modifier recovery evidence.", restored=restored) from error


TOOL_DATA = (
    ("geometry_nodes.group_bind", group_bind, True, (Permission.EDIT_MESH,), "Bind a reviewed nested GN group through a uniquely named instance."),
    ("geometry_nodes.group_copy_for_node", group_copy_for_node, True, (Permission.EDIT_MESH,), "Copy one nested GN instance root while retaining referenced descendants."),
    ("geometry_nodes.group_link", group_link, True, (Permission.EDIT_MESH,), "Link exact socket identifiers in a reviewed nested GN graph."),
    ("geometry_nodes.group_set_input", group_set_input, True, (Permission.EDIT_MESH,), "Set an unlinked constant by exact socket identifier in a reviewed GN graph."),
    ("geometry_nodes.group_remove", group_remove, True, (Permission.EDIT_MESH, Permission.DELETE_OBJECTS), "Remove only an explicitly confirmed unused GN group."),
    ("geometry_nodes.group_attach", group_attach, True, (Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS), "Attach a recursively reviewed nested GN graph to one mesh object."),
    ("geometry_nodes.modifier_inspect", modifier_inspect, False, (Permission.INSPECT_SCENE,), "Inspect stored GN modifier inputs by stable interface identifiers."),
    ("geometry_nodes.modifier_set_input", modifier_set_input, True, (Permission.EDIT_MESH, Permission.TRANSFORM_OBJECTS), "Set an object-owned GN modifier constant without changing the shared graph."),
)


def register_tools(registry: ToolRegistry) -> None:
    for tool_name, handler, modifying, permissions, description in TOOL_DATA:
        registry.register(tool_name, handler, permissions=permissions, toolset="geometry_nodes", modifies=modifying, description=description)
