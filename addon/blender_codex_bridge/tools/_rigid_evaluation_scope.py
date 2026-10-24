"""Conservative native evaluation admission, without reading evaluated sockets.

All Main material/world/node families are inspected, including unused data.
This is a bounded unsupported-profile check, not a sandbox for the host process.
"""

from __future__ import annotations

from typing import Any

from ..errors import BridgeError, ErrorCode
from . import _animation_scope as evidence
from .geometry_nodes import _SAFE_NODE_TYPES
from .shader_state import SETTINGS

MAX_SCENES, MAX_MATERIALS, MAX_WORLDS = 16, 64, 16
MAX_OWNERS, MAX_TREES, MAX_DEPTH = 96, 64, 8
MAX_NODES, MAX_LINKS, MAX_INTERFACE = 256, 1024, 128
MAX_TOTAL_NODES, MAX_TOTAL_LINKS, MAX_TOTAL_INTERFACE = 1024, 4096, 512
MAX_MAIN_IDS = 512
TREE_TYPES = frozenset({"ShaderNodeTree", "CompositorNodeTree", "GeometryNodeTree"})
GROUP_TYPES = frozenset({"ShaderNodeGroup", "CompositorNodeGroup", "GeometryNodeGroup"})
# Native classes only. Image/clip/script/file nodes and object-coordinate inputs
# are outside this initial profile, even if they appear unused.
NODE_TYPES = frozenset(SETTINGS) | _SAFE_NODE_TYPES | GROUP_TYPES | frozenset({
    "ShaderNodeBackground", "ShaderNodeOutputWorld", "ShaderNodeOutputMaterial",
    "ShaderNodeOutputLight", "ShaderNodeBsdfDiffuse", "ShaderNodeBsdfGlass",
    "ShaderNodeBsdfTransparent", "ShaderNodeMixShader", "ShaderNodeAddShader",
    "ShaderNodeEmission", "ShaderNodeRGB", "ShaderNodeValue", "ShaderNodeValToRGB",
    "CompositorNodeValue", "CompositorNodeRGB", "CompositorNodeComposite",
})
SOCKET_TYPES = frozenset({"NodeSocketShader", "NodeSocketFloat", "NodeSocketInt", "NodeSocketBool",
                          "NodeSocketVector", "NodeSocketColor", "NodeSocketRotation"})
INTERFACE_TYPES = frozenset({"NodeTreeInterfacePanel", "NodeTreeInterfaceSocketShader", "NodeTreeInterfaceSocketFloat",
    "NodeTreeInterfaceSocketInt", "NodeTreeInterfaceSocketBool", "NodeTreeInterfaceSocketVector",
    "NodeTreeInterfaceSocketColor", "NodeTreeInterfaceSocketRotation"})
FAMILY_SUBTYPES = {
    "NodeTree": TREE_TYPES,
    "Light": frozenset({"PointLight", "AreaLight", "SpotLight", "SunLight"}),
    "Curve": frozenset({"TextCurve", "SurfaceCurve"}),
}


def _unsupported(message: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message, {"evaluation_scope_complete": False})


def _native(bpy: Any, owner: Any, allowed: frozenset[str]) -> Any:
    rna = owner.bl_rna
    identifier = rna.identifier
    if identifier not in allowed:
        raise _unsupported(f"Rigid-body evaluation contains unreviewed RNA class '{identifier}'; no properties are evaluated.")
    builtin = getattr(bpy.types, identifier, None)
    if builtin is None or builtin.bl_rna != rna:
        raise _unsupported("Rigid-body evaluation requires the exact canonical built-in RNA descriptor.")
    return rna


def _read(owner: Any, rna: Any, field: str, kind: str, *, optional: bool = False) -> Any:
    prop = rna.properties.get(field)
    if prop is None and optional:
        return None
    if prop is None or prop.type != kind or bool(prop.is_runtime):
        raise _unsupported("An evaluation input has a missing, runtime or unreviewed RNA property descriptor.")
    return getattr(owner, field)


def _id(bpy: Any, owner: Any, allowed: frozenset[str]) -> tuple[Any, Any]:
    rna = _native(bpy, owner, allowed)
    if (_read(owner, rna, "library", "POINTER") is not None
            or _read(owner, rna, "override_library", "POINTER") is not None
            or not _read(owner, rna, "is_editable", "BOOLEAN")):
        raise _unsupported("Rigid-body evaluation requires local editable, non-override dependency IDs.")
    if _read(owner, rna, "animation_data", "POINTER") is not None:
        raise _unsupported("Rigid-body evaluation rejects every Action, NLA or driver owner in the bounded Main dependency profile, including unused data.")
    return rna, (evidence.action_token(owner), _read(owner, rna, "name", "STRING"), rna.identifier)


def _bounded(items: Any, maximum: int, label: str) -> list[Any]:
    result = evidence.bounded(items, maximum, "rigid evaluation " + label)
    return result


def _main_animation(bpy: Any, rna: Any) -> tuple[Any, ...]:
    """Reject native animation owners anywhere in Main, not only reachable slots."""
    properties = _bounded(rna.properties, 128, "BlendData RNA properties")
    records = []
    alias = None
    for prop in properties:
        if prop.type != "COLLECTION":
            continue
        fixed = prop.fixed_type
        if fixed.identifier == "ID":
            if prop.identifier != "all_ids" or alias is not None:
                raise _unsupported("Unknown aggregate Main ID-family alias.")
            alias = prop.identifier
            continue
        base = fixed
        for _ in range(16):
            if base is None or base.identifier == "ID":
                break
            base = base.base
        else:
            raise _unsupported("Unknown native ID-family inheritance depth.")
        if base is None:
            continue
        allowed = frozenset({fixed.identifier}) | FAMILY_SUBTYPES.get(fixed.identifier, frozenset())
        for owner in _bounded(_read(bpy.data, rna, prop.identifier, "COLLECTION"), MAX_MAIN_IDS-len(records), "aggregate Main IDs"):
            owner_rna = _native(bpy, owner, allowed)
            if (_read(owner, owner_rna, "library", "POINTER") is not None
                    or _read(owner, owner_rna, "override_library", "POINTER") is not None
                    or not _read(owner, owner_rna, "is_editable", "BOOLEAN")):
                raise _unsupported("Rigid-body evaluation requires every bounded Main ID to be local, editable and non-override, including unused dependencies.")
            if _read(owner, owner_rna, "animation_data", "POINTER", optional=True) is not None:
                raise _unsupported("Rigid-body evaluation rejects animation_data anywhere in the bounded Main ID inventory, including unused dependencies.")
            records.append((evidence.action_token(owner), owner_rna.identifier, _read(owner, owner_rna, "name", "STRING")))
    if alias is not None:
        all_ids = _bounded(_read(bpy.data, rna, alias, "COLLECTION"), MAX_MAIN_IDS, "aggregate Main ID alias")
        if {evidence.key(owner) for owner in all_ids} != {record[0][0] for record in records}:
            raise _unsupported("Native all_ids does not match the complete reviewed concrete Main families.")
    return tuple(sorted(records))


def snapshot(bpy: Any) -> tuple[Any, ...]:
    """Read only proven native metadata, bindings and topology before frame_set."""
    main_rna = _native(bpy, bpy.data, frozenset({"BlendData"}))
    main_ids = _main_animation(bpy, main_rna)
    groups = _bounded(_read(bpy.data, main_rna, "node_groups", "COLLECTION"), MAX_TREES, "standalone groups")
    standalone = {evidence.action_token(tree) for tree in groups}
    roots, owners = list(groups), []
    for family, kinds, maximum in (("scenes", frozenset({"Scene"}), MAX_SCENES),
        ("materials", frozenset({"Material"}), MAX_MATERIALS), ("worlds", frozenset({"World"}), MAX_WORLDS),
        ("lights", frozenset({"PointLight", "AreaLight", "SpotLight", "SunLight"}), 32),
        ("linestyles", frozenset({"FreestyleLineStyle"}), 16)):
        for owner in _bounded(_read(bpy.data, main_rna, family, "COLLECTION"), maximum, family):
            if len(owners) >= MAX_OWNERS:
                raise _unsupported("Rigid-body Main evaluation owner inventory exceeds 96 IDs.")
            rna, identity = _id(bpy, owner, kinds)
            kind = rna.identifier
            bindings = []
            for field in ("node_tree", "compositing_node_group") if kind == "Scene" else ("node_tree",):
                tree = _read(owner, rna, field, "POINTER", optional=True)
                bindings.append((field, evidence.action_token(tree)))
                if tree is not None:
                    roots.append(tree)
            if kind == "Scene":
                editor = _read(owner, rna, "sequence_editor", "POINTER")
                if editor is not None:
                    editor_rna = _native(bpy, editor, frozenset({"SequenceEditor"}))
                    fields = [field for field in ("sequences", "sequences_all", "strips", "strips_all") if editor_rna.properties.get(field) is not None]
                    if not fields:
                        raise _unsupported("Native sequencer has no reviewed strip-inventory API.")
                    if any(len(_read(editor, editor_rna, field, "COLLECTION")) for field in fields):
                        raise _unsupported("Nonempty sequencer evaluation is outside the initial rigid-body cache profile.")
                bindings.append(("world", evidence.action_token(_read(owner, rna, "world", "POINTER"))))
            owners.append((identity, tuple(bindings)))
    trees, adjacency = {}, {}
    totals = [0, 0, 0]
    while roots:
        tree = roots.pop()
        key = evidence.action_token(tree)
        if key in trees:
            continue
        if len(trees) >= MAX_TREES:
            raise _unsupported("Rigid-body evaluation exceeds 64 total standalone/embedded NodeTrees.")
        rna, identity = _id(bpy, tree, TREE_TYPES)
        nodes = _bounded(_read(tree, rna, "nodes", "COLLECTION"), MAX_NODES, "tree nodes")
        links = _bounded(_read(tree, rna, "links", "COLLECTION"), MAX_LINKS, "tree links")
        interface = _read(tree, rna, "interface", "POINTER")
        interface_rna = _native(bpy, interface, frozenset({"NodeTreeInterface"}))
        items = _bounded(_read(interface, interface_rna, "items_tree", "COLLECTION"), MAX_INTERFACE, "interface items")
        totals = [total+len(items_) for total, items_ in zip(totals, (nodes, links, items), strict=True)]
        if any(total > limit for total, limit in zip(totals, (MAX_TOTAL_NODES, MAX_TOTAL_LINKS, MAX_TOTAL_INTERFACE), strict=True)):
            raise _unsupported("Rigid-body evaluation exceeds aggregate 1024 nodes, 4096 links or 512 interface items.")
        node_records, children, interface_records = [], [], []
        for node in nodes:
            node_rna = _native(bpy, node, NODE_TYPES)
            child = None
            if node_rna.identifier in GROUP_TYPES:
                child = _read(node, node_rna, "node_tree", "POINTER")
                if child is not None:
                    child_rna = _native(bpy, child, TREE_TYPES)
                    if evidence.action_token(child) not in standalone or child_rna.identifier != rna.identifier:
                        raise _unsupported("Group evaluation requires an explicit standalone tree of the same reviewed native kind.")
                    roots.append(child)
                    children.append(evidence.action_token(child))
            node_records.append((evidence.key(node), node_rna.identifier, _read(node, node_rna, "name", "STRING"), evidence.action_token(child)))
        for item in items:
            # Check the registered class against bpy.types before reading any
            # dynamic item/socket properties; never read default_value.
            item_rna = _native(bpy, item, INTERFACE_TYPES)
            item_type = _read(item, item_rna, "item_type", "ENUM")
            socket_type = None
            if item_type == "SOCKET":
                socket_type = _read(item, item_rna, "socket_type", "ENUM")
                if socket_type not in SOCKET_TYPES:
                    raise _unsupported("Group interfaces with image/object/collection/custom sockets require a broader evaluation closure.")
            elif item_type != "PANEL":
                raise _unsupported("Unknown native group interface item kind.")
            interface_records.append((evidence.key(item), item_type, socket_type))
        link_records = []
        for link in links:
            link_rna = _native(bpy, link, frozenset({"NodeLink"}))
            link_records.append((evidence.key(link), *(evidence.key(_read(link, link_rna, field, "POINTER"))
                for field in ("from_node", "to_node", "from_socket", "to_socket"))))
        trees[key] = (identity, tuple(node_records), tuple(link_records), tuple(interface_records))
        adjacency[key] = tuple(children)
    depth = {}

    def visit(key: Any, trail: tuple[Any, ...]) -> int:
        if key in trail:
            raise _unsupported("Recursive node groups cannot establish a closed rigid-body evaluation scope.")
        if key not in depth:
            depth[key] = max((visit(child, (*trail, key))+1 for child in adjacency[key]), default=0)
            if depth[key] > MAX_DEPTH:
                raise _unsupported("Nested rigid-body evaluation groups exceed depth 8.")
        return depth[key]

    for key in trees:
        visit(key, ())
    return main_ids, tuple(sorted(owners)), tuple(trees[key] for key in sorted(trees)), tuple(totals)
