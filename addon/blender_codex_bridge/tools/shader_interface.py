"""Scoped shader interface plans and exact owned-state compensation.

Only rename, flat reordering and definition defaults are supported. Native probes
show type conversion loses defaults and 4.5 reordering aliases animated inputs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import struct
from collections.abc import Mapping

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import reject_unknown_params, require_blender
from . import nodes, shader_scope, shader_state
from ._object_scope import datablock_identity
from .material_scope import local_editable

LOGGER = logging.getLogger(__name__)
READ = (Permission.INSPECT_SCENE,)
EDIT = (*READ, Permission.EDIT_MATERIALS)
MAX_TREES, MAX_OWNERS, MAX_VALUES, MAX_BYTES = 32, 100, 100_000, 1_048_576
MAX_OBJECTS = 4096
BASE = {"group_name", "socket_identifier", "operation"}
EXTRA = {"RENAME": {"new_name"}, "MOVE": {"to_index"}, "SET_DEFAULT": {"value"}}
SOCKET_TYPES = {"NodeSocketFloat", "NodeSocketInt", "NodeSocketBool", "NodeSocketVector", "NodeSocketColor", "NodeSocketShader"}
NODE_TYPES = set(shader_state.SETTINGS) | {"ShaderNodeGroup", "NodeGroupInput", "NodeGroupOutput",
    "ShaderNodeOutputMaterial", "ShaderNodeOutputWorld", "ShaderNodeOutputLight", "ShaderNodeBsdfDiffuse",
    "ShaderNodeBsdfGlass", "ShaderNodeBsdfTransparent", "ShaderNodeMixShader", "ShaderNodeAddShader",
    "ShaderNodeEmission", "ShaderNodeBackground", "ShaderNodeTexChecker", "ShaderNodeTexCoord",
    "ShaderNodeRGB", "ShaderNodeValue", "ShaderNodeValToRGB", "ShaderNodeTexImage", "ShaderNodeMapping", "NodeFrame"}


def _gate(context, *, modify=False):
    # No provider callbacks follow cancellation/stop checks. Callers compare the
    # full captured scope after this boundary, before any native assignment.
    context.require(*(EDIT if modify else READ))
    if context.check_cancelled:
        context.check_cancelled()
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    registry = getattr(context, "registry", None)
    if registry is not None and "nodes" not in registry.enabled_toolsets:
        raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Shader nodes toolset was disabled during live authorization.")
    flags = context.state.snapshot()
    if modify and flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Shader interface mutation emergency-stopped.")
    if modify and flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Shader interface mutation paused.")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _identity(owner):
    return [datablock_identity(owner), getattr(owner, "session_uid", None)]


class _Proof:
    def __init__(self):
        self.count = 0

    def value(self, value, depth=0):
        self.count += 1
        if self.count > MAX_VALUES or depth > 8:
            raise invalid_argument("Shader interface proof exceeds 100000 values or depth eight.")
        if value is None or type(value) in (bool, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise invalid_argument("Shader interface proof requires finite native values.")
            return value
        if isinstance(value, str):
            if len(value) > 4096:
                raise invalid_argument("Shader interface proof strings exceed 4096 characters.")
            return value
        if hasattr(value, "as_pointer"):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Custom native references need an explicit shader dependency contract.")
        if hasattr(value, "keys"):
            keys = list(value.keys())
            if len(keys) > 128:
                raise invalid_argument("Shader custom-property mappings exceed 128 fields.")
            return {key: self.value(value[key], depth+1) for key in sorted(keys)}
        if isinstance(value, set):
            value = sorted(value)
        if hasattr(value, "__len__") and len(value) <= 64:
            return [self.value(item, depth+1) for item in value]
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "A native shader value lacks bounded preservation proof.")

    def properties(self, owner, exclude=()):
        result = {}
        for prop in owner.bl_rna.properties:
            if prop.identifier in exclude or prop.is_readonly or prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
                continue
            result[prop.identifier] = self.value(getattr(owner, prop.identifier))
        try:
            keys = tuple(owner.keys())
        except (AttributeError, TypeError):
            keys = ()  # Native structs such as sockets do not have IDProperties.
        if keys:
            result["custom_properties"] = {key: self.value(owner[key]) for key in sorted(keys)
                if key != "_codex_bridge_undo_marker"}
        return result

    def graph(self, tree):
        shader_scope.bounded_tree(tree)
        if any(item.item_type != "SOCKET" for item in tree.interface.items_tree):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface plans currently require flat socket-only interfaces.")
        records = []
        for node in tree.nodes:
            if node.bl_idname not in NODE_TYPES:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface preservation requires reviewed builtin node types.", {"node_type": node.bl_idname})
            if len(node.inputs) > 128 or len(node.outputs) > 128:
                raise invalid_argument("Shader interface proof exceeds 128 sockets per node direction.")
            record = {"identity": datablock_identity(node), "name": node.name, "type": node.bl_idname,
                "group": None if getattr(node, "node_tree", None) is None else datablock_identity(node.node_tree),
                "parent": None if node.parent is None else datablock_identity(node.parent),
                "properties": self.properties(node), "inputs": [], "outputs": []}
            for direction in ("inputs", "outputs"):
                for socket in getattr(node, direction):
                    record[direction].append({"identifier": socket.identifier, "type": socket.bl_idname,
                        "properties": self.properties(socket), "linked": bool(socket.is_linked)})
            for name in ("texture_mapping", "color_mapping", "image_user"):
                owner = getattr(node, name, None)
                if owner is not None:
                    record[name] = self.properties(owner)
                    scene = getattr(owner, "scene", None)
                    if scene is not None:
                        record[name]["scene_reference"] = _identity(scene)
                    ramp = getattr(owner, "color_ramp", None)
                    if ramp is not None:
                        if len(ramp.elements) > shader_state.MAX_STOPS:
                            raise invalid_argument("Shader ramp preservation exceeds 32 stops.")
                        record[name]["color_ramp"] = shader_state.ramp_state(ramp)
            if hasattr(node, "color_ramp"):
                if len(node.color_ramp.elements) > shader_state.MAX_STOPS:
                    raise invalid_argument("Shader ramp preservation exceeds 32 stops.")
                record["color_ramp"] = shader_state.ramp_state(node.color_ramp)
            obj = getattr(node, "object", None)
            if obj is not None:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object-referenced shader nodes require a separately reviewed dependency scope.")
            image = getattr(node, "image", None)
            if image is not None:
                if (image.source not in {"FILE", "GENERATED"} or image.type != "IMAGE"
                        or not image.has_data or image.is_multiview):
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface proof requires already-loaded simple images; it never triggers implicit file decoding.")
                record["image"] = {"identity": _identity(image), "name": image.name,
                    "source": image.source, "size": list(image.size), "alpha_mode": image.alpha_mode,
                    "color_space": image.colorspace_settings.name, "has_data": bool(image.has_data),
                    "is_dirty": bool(image.is_dirty), "filepath": image.filepath}
            records.append(record)
        interface = []
        for item in tree.interface.items_tree:
            if item.socket_type not in SOCKET_TYPES:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface proof supports reviewed scalar/vector/color/shader sockets only.")
            interface.append({"identifier": item.identifier, "in_out": item.in_out, "type": item.socket_type,
                "properties": self.properties(item)})
        return {"identity": _identity(tree), "name": tree.name, "properties": self.properties(tree),
            "interface_properties": self.properties(tree.interface), "interface": interface,
            "active_interface_identifier": getattr(tree.interface.active, "identifier", None),
            "active_node": None if tree.nodes.active is None else datablock_identity(tree.nodes.active),
            "nodes": sorted(records, key=lambda item: item["identity"]),
            "links": sorted([datablock_identity(link.from_node), link.from_socket.identifier,
                datablock_identity(link.to_node), link.to_socket.identifier, bool(link.is_valid), bool(link.is_muted)] for link in tree.links)}


def _unanimated(owner):
    if getattr(owner, "animation_data", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface maintenance requires unanimated affected definitions and root owners; actions, NLA and drivers need separate path-preservation proof.")


def _root_tree(bpy, owner):
    for kind, owners in (("Material", bpy.data.materials), ("World", bpy.data.worlds), ("Light", bpy.data.lights)):
        if owners.get(owner.name) == owner and getattr(owner, "node_tree", None) is not None:
            return kind, owner.node_tree
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface has an unreviewed incoming consumer.", {"owner": owner.name, "type": owner.bl_rna.identifier})


def _local(owner):
    if not local_editable(owner):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface scope must contain local editable non-override owners.")
    _unanimated(owner)


def _context(bpy):
    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.INVALID_MODE, "Shader interface changes require Object Mode without changing selection.")
    if not local_editable(bpy.context.scene):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface changes require a local editable context scene.")
    layer = bpy.context.view_layer
    if len(layer.objects) > MAX_OBJECTS:
        raise invalid_argument("Shader interface context exceeds 4096 view-layer objects.")
    return {"scene": _identity(bpy.context.scene), "view_layer": datablock_identity(layer),
        "mode": bpy.context.mode, "filepath": bpy.data.filepath,
        "frame": [bpy.context.scene.frame_current, bpy.context.scene.frame_subframe],
        "selected": sorted(datablock_identity(obj) for obj in layer.objects if obj.select_get(view_layer=layer)),
        "active": None if layer.objects.active is None else datablock_identity(layer.objects.active)}


def _capture(bpy, target):
    """Complete bounded shader definitions/bindings, without reading image pixels."""
    context = _context(bpy)
    if len(bpy.data.objects) > MAX_OBJECTS:
        raise invalid_argument("Shader interface material-binding proof exceeds 4096 project objects.")
    pending, ancestors, root_owners, reference_counts = [target], {}, {}, []
    while pending:
        current = pending.pop()
        key = datablock_identity(current)
        if key in ancestors:
            continue
        if len(ancestors) >= MAX_TREES:
            raise invalid_argument("Shader interface incoming scope exceeds 32 definitions.")
        _local(current)
        shader_scope.bounded_tree(current)
        ancestors[key] = current
        users = list(bpy.data.user_map(subset={current}).get(current, ()))
        if len(users) > MAX_OWNERS:
            raise invalid_argument("Shader interface ownership exceeds 100 direct users.")
        for owner in users:
            _local(owner)
            if getattr(owner, "bl_idname", None) == "ShaderNodeTree" and not owner.is_embedded_data:
                tree, kind = owner, "GROUP"
                pending.append(tree)
            else:
                kind, tree = _root_tree(bpy, owner)
                root_owners[datablock_identity(owner)] = (kind, owner, tree)
                if len(root_owners) > MAX_OWNERS:
                    raise invalid_argument("Shader interface ownership exceeds 100 root owners.")
            refs = sum(getattr(node, "node_tree", None) == current for node in tree.nodes)
            if refs < 1 or owner.user_of_id(current) != refs:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader group has native references beyond the reviewed group-node bindings.", {"owner": owner.name})
            reference_counts.append([key, datablock_identity(owner), refs])
    # Protect all nested children of the changed definition, incoming parents
    # and owner roots. They are not recursively declared changed consumers.
    pending = [(tree, ()) for tree in (*ancestors.values(), *(tree for _kind, _owner, tree in root_owners.values()))]
    trees = {}
    while pending:
        tree, chain = pending.pop()
        key = datablock_identity(tree)
        if key in chain:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recursive shader definitions cannot be safely updated.")
        if key in trees:
            continue
        if len(trees) >= MAX_TREES:
            raise invalid_argument("Shader interface nested preservation exceeds 32 trees.")
        _local(tree)
        shader_scope.bounded_tree(tree)
        trees[key] = tree
        pending.extend((node.node_tree, (*chain, key)) for node in tree.nodes if getattr(node, "node_tree", None) is not None)
    proof = _Proof()
    owners, affected, worlds = {}, set(), set()
    for key, (kind, owner, tree) in root_owners.items():
        direct = list(bpy.data.user_map(subset={owner}).get(owner, ()))
        if len(direct) > MAX_OWNERS:
            raise invalid_argument("Shader root owner references exceed 100 IDs.")
        for user in direct:
            _local(user)
        owners[key] = {"kind": kind, "name": owner.name, "identity": _identity(owner),
            "tree": datablock_identity(tree), "properties": proof.properties(owner),
            "users": sorted([datablock_identity(user), user.bl_rna.identifier, user.name,
                user.user_of_id(owner)] for user in direct)}
        if kind == "Material":
            for user in direct:
                if user.bl_rna.identifier == "Object":
                    refs = sum(slot.link == "OBJECT" and slot.material == owner for slot in user.material_slots)
                elif hasattr(user, "materials"):
                    refs = sum(material == owner for material in user.materials)
                else:
                    refs = 0
                if refs < 1 or user.user_of_id(owner) != refs:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Material has native users beyond its reviewed material-slot bindings.")
            usage = []
            for obj in bpy.data.objects:
                bindings = [index for index, slot in enumerate(obj.material_slots) if slot.material == owner]
                if bindings:
                    _local(obj)
                    if len(affected) >= MAX_OWNERS:
                        raise invalid_argument("Shader material effect scope exceeds 100 objects.")
                    affected.add(obj.name)
                    usage.append([_identity(obj), obj.name, _identity(obj.data), bindings,
                        [[slot.link, None if slot.material is None else datablock_identity(slot.material)] for slot in obj.material_slots]])
            owners[key]["object_bindings"] = sorted(usage, key=lambda item: item[1])
        elif kind == "Light":
            for user in direct:
                if getattr(user, "data", None) != owner or user.user_of_id(owner) != 1:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Light ownership includes an unreviewed native reference.")
                affected.add(user.name)
        else:
            for user in direct:
                if getattr(user, "world", None) != owner or user.user_of_id(owner) != 1:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "World ownership includes an unreviewed native reference.")
                worlds.add(user.name)
    if len(affected) > MAX_OWNERS or len(worlds) > MAX_OWNERS:
        raise invalid_argument("Shader interface affected object/scene list exceeds 100 entries.")
    state = {"context": context, "target": _identity(target), "graphs": {key: proof.graph(tree) for key, tree in trees.items()},
        "owners": owners, "references": sorted(reference_counts)}
    if len(json.dumps(state, allow_nan=False).encode()) > MAX_BYTES:
        raise invalid_argument("Shader interface preservation state exceeds one MiB.")
    summary = {"group_name": target.name, "definition_count": len(trees),
        "affected_objects": sorted(affected), "affected_world_scenes": sorted(worlds),
        "root_owners": sorted([kind, owner.name] for kind, owner, _tree in root_owners.values()),
        "requires_shared_consent": bool(root_owners) or target.users > 1,
        "coverage": "Bounded shader definitions, root ownership, links, defaults and existing image bindings; image pixels and evaluated geometry are not compared."}
    return state, summary


def _item(tree, identifier):
    matches = [item for item in tree.interface.items_tree if getattr(item, "identifier", None) == identifier]
    if len(matches) != 1 or matches[0].item_type != "SOCKET":
        raise invalid_argument("socket_identifier must name one current interface socket.")
    return matches[0]


def _float32(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1_000_000 or not math.isfinite(value):
        raise invalid_argument("Shader defaults require finite numbers with magnitude at most one million.")
    return struct.unpack("f", struct.pack("f", value))[0]


def _plan(tree, params):
    operation = params.get("operation")
    if not isinstance(operation, str) or operation not in EXTRA:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface operation must be RENAME, MOVE or SET_DEFAULT; conversion/removal are not implemented.")
    identifier = shader_scope.name(params.get("socket_identifier"), "socket_identifier")
    item = _item(tree, identifier)
    result = {"operation": operation, "socket_identifier": identifier, "in_out": item.in_out}
    if operation == "RENAME":
        result["value"] = shader_scope.name(params.get("new_name"), "new_name")
        if any(peer.identifier != identifier and peer.in_out == item.in_out and peer.name == result["value"] for peer in tree.interface.items_tree):
            raise invalid_argument("An interface socket already has the requested name and direction.")
        result["before"] = item.name
    elif operation == "MOVE":
        peers = [peer.identifier for peer in tree.interface.items_tree if peer.in_out == item.in_out]
        index = params.get("to_index")
        if type(index) is not int or not 0 <= index < len(peers):
            raise invalid_argument("to_index must name a final index within the same socket direction.")
        result["before"], result["value"] = peers.index(identifier), index
    else:
        kind, value = item.socket_type, params.get("value")
        if kind == "NodeSocketBool":
            if type(value) is not bool:
                raise invalid_argument("Boolean interface defaults require a Boolean.")
        elif kind == "NodeSocketInt":
            if type(value) is not int or not -(2**31) <= value < 2**31:
                raise invalid_argument("Integer interface defaults require a signed 32-bit integer.")
        elif kind == "NodeSocketFloat":
            value = _float32(value)
        elif kind in {"NodeSocketVector", "NodeSocketColor"}:
            count = 3 if kind == "NodeSocketVector" else 4
            if not isinstance(value, list) or len(value) != count:
                raise invalid_argument("Vector/color interface defaults require exactly three/four numeric components.")
            value = [_float32(part) for part in value]
        else:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader socket interfaces have no editable scalar default.")
        prop = item.bl_rna.properties.get("default_value")
        if prop is None:
            raise invalid_argument("Interface default lacks native range metadata.")
        for component in value if isinstance(value, list) else (value,):
            if (getattr(prop, "hard_min", -float("inf")) > component
                    or getattr(prop, "hard_max", float("inf")) < component):
                raise invalid_argument("Interface default exceeds its native component range.")
        result["before"] = _Proof().value(item.default_value)
        result["value"] = value
    return result


def _project(before, key, plan):
    result = copy.deepcopy(before)
    graph = result["graphs"][key]
    identifier, operation, value = plan["socket_identifier"], plan["operation"], plan["value"]
    matching = [item for item in graph["interface"] if item["identifier"] == identifier]
    assert len(matching) == 1
    item = matching[0]
    if operation == "RENAME":
        item["properties"]["name"] = value
    elif operation == "SET_DEFAULT":
        item["properties"]["default_value"] = value
    else:
        peers = [entry["identifier"] for entry in graph["interface"] if entry["in_out"] == item["in_out"]]
        peers.remove(identifier)
        peers.insert(value, identifier)
        original = {entry["identifier"]: entry for entry in graph["interface"]}
        iterator = iter(peers)
        graph["interface"] = [original[next(iterator)] if entry["in_out"] == item["in_out"] else entry for entry in graph["interface"]]
        active = graph.get("active_interface_identifier")
        if active is not None:
            graph["interface_properties"]["active_index"] = next(index for index, entry in enumerate(graph["interface"])
                if entry["identifier"] == active)
    if operation == "SET_DEFAULT":
        # Demonstrated shader behaviour: even Group Input output defaults stay
        # unchanged. This deliberately does not reuse Geometry Nodes masking.
        return result
    order = [entry["identifier"] for entry in graph["interface"]]
    for tree in result["graphs"].values():
        for node in tree["nodes"]:
            if node["group"] != key and not (tree["identity"][0] == key and node["type"] in {"NodeGroupInput", "NodeGroupOutput"}):
                continue
            for direction in ("inputs", "outputs"):
                if operation == "RENAME":
                    for socket in node[direction]:
                        if socket["identifier"] == identifier:
                            socket["properties"]["name"] = value
                else:
                    table = {socket["identifier"]: socket for socket in node[direction] if socket["identifier"] in order}
                    iterator = iter(table[ident] for ident in order if ident in table)
                    node[direction] = [next(iterator) if socket["identifier"] in table else socket for socket in node[direction]]
    return result


def _write(tree, plan, *, inverse=False):
    item = _item(tree, plan["socket_identifier"])
    value = plan["before"] if inverse else plan["value"]
    if plan["operation"] == "RENAME":
        item.name = value
    elif plan["operation"] == "SET_DEFAULT":
        item.default_value = value
    else:
        active = getattr(tree.interface.active, "identifier", None)
        items = list(tree.interface.items_tree)
        selected = {entry.identifier: entry.select for entry in items if hasattr(entry, "select")}
        peers = [entry for entry in items if entry.in_out == item.in_out]
        old, target = items.index(item), items.index(peers[value])
        tree.interface.move(item, target+int(old < target))
        # Native MOVE preserves the numeric index, selecting another socket.
        # Retain the actual UI selection by stable identifier on both versions.
        if active is not None:
            active_index = next(index for index, entry in enumerate(tree.interface.items_tree)
                if entry.identifier == active)
            if tree.interface.active_index != active_index:
                tree.interface.active_index = active_index
                # 5.2's index setter also selects the active socket. Preserve
                # its independent selection flags, including a nonselected active.
                for entry in tree.interface.items_tree:
                    if entry.identifier in selected and entry.select != selected[entry.identifier]:
                        entry.select = selected[entry.identifier]


def _prepare(context, params, *, modify=False):
    operation = params.get("operation")
    if not isinstance(operation, str) or operation not in EXTRA:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader interface operation must be RENAME, MOVE or SET_DEFAULT.")
    reject_unknown_params(params, BASE | EXTRA[operation] | ({"expected_fingerprint", "allow_shared"} if modify else set()))
    _gate(context, modify=modify)
    bpy = require_blender()
    tree = shader_scope.group_exact(bpy, params.get("group_name"))
    state, scope = _capture(bpy, tree)
    plan = _plan(tree, params)
    if modify:
        allow = params.get("allow_shared", False)
        if type(allow) is not bool or (scope["requires_shared_consent"] and not allow):
            raise invalid_argument("Shared shader interface changes require explicit allow_shared covering all reported owners.", **scope)
    fingerprint = _digest({"state": state, "plan": plan})
    return bpy, tree, state, scope, plan, fingerprint


def preview(context: ToolContext, params: Mapping) -> dict:
    _bpy, tree, _state, scope, plan, fingerprint = _prepare(context, params)
    return {**scope, "socket_identifier": plan["socket_identifier"], "operation": plan["operation"],
        "before": plan["before"], "after": plan["value"], "fingerprint": fingerprint,
        "changed": False, "native_writes": False, "project_saved": False,
        "existing_instance_defaults_preserved": True, "stable_interface_identifiers": True,
        "visual_comparison_required": False, "interface": nodes._json_value([item.identifier for item in tree.interface.items_tree])}


def edit(context: ToolContext, params: Mapping) -> dict:
    bpy, tree, before, scope, plan, fingerprint = _prepare(context, params, modify=True)
    if params.get("expected_fingerprint") != fingerprint:
        raise invalid_argument("Shader interface edit needs its exact current scope/operation preview fingerprint.")
    expected = _project(before, datablock_identity(tree), plan)
    attempted = False

    def current():
        _gate(context, modify=True)
        resolved = shader_scope.group_exact(bpy, params["group_name"])
        if _identity(resolved) != before["target"]:
            raise invalid_argument("Shader interface target identity changed; no further writes.")
        observed, summary = _capture(bpy, resolved)
        if summary != scope:
            raise invalid_argument("Shader interface owner scope changed; no further writes.")
        return resolved, observed

    try:
        tree, observed = current()
        if observed != before:
            raise invalid_argument("Shader interface state changed after preview; no write allowed.")
        if plan["before"] != plan["value"]:
            attempted = True
            _write(tree, plan)
        _tree, observed = current()
        if observed != expected:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Shader interface propagation changed protected state or did not match the exact planned output.")
    except Exception as error:
        restored = not attempted
        if attempted:
            try:
                tree, observed = current()
                if observed == before:
                    restored = True
                elif observed == expected:
                    _write(tree, plan, inverse=True)
                    _tree, observed = current()
                    restored = observed == before
                else:
                    raise invalid_argument("Shader output no longer equals the owned planned state; compensation refused.")
            except Exception:
                LOGGER.exception("Shader interface compensation was refused or failed")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Shader interface edit did not complete; inspect the current definition and measured recovery state.",
            {"execution_started": attempted, "rollback_verified": restored, "possible_mutation": attempted and not restored,
                "verification_required": True, **scope}) from error
    return {**scope, "changed": attempted, "socket_identifier": plan["socket_identifier"],
        "operation": plan["operation"], "value": plan["value"], "protected_graph_state_preserved": True,
        "existing_instance_defaults_preserved": True, "stable_interface_identifiers": True,
        "project_saved": False, "verification_required": True}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("shader_group.interface_preview", preview, toolset="nodes", permissions=READ,
        description="Preview one bounded shader interface rename/reorder/default plan with exact full-scope fingerprint.")
    registry.register("shader_group.interface_edit", edit, toolset="nodes", permissions=EDIT, modifies=True,
        batchable=False, description="Apply one exact shader interface preview with complete bounded graph/owner CAS and guarded compensation.")
