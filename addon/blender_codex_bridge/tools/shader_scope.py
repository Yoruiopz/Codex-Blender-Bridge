"""Bounded shader-group paths and shared-user evidence, independent of Blender UI classes."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from .material_scope import local_editable, material_scope

MAX_DEPTH = 8
MAX_GROUPS = 32
MAX_OWNERS = 100
MAX_NODES = 256
MAX_LINKS = 1024


def _key(owner: Any) -> int:
    pointer = getattr(owner, "as_pointer", None)
    return int(pointer()) if pointer else id(owner)


def name(value: Any, parameter: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise invalid_argument(f"'{parameter}' must be non-empty text without control characters.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise invalid_argument(f"'{parameter}' must be valid UTF-8 text.") from exc
    if size > 63:
        raise invalid_argument(f"'{parameter}' must be at most 63 UTF-8 bytes.")
    return value


def path(params: Mapping[str, Any]) -> list[str]:
    value = params.get("group_path")
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_DEPTH:
        raise invalid_argument("'group_path' must be an array of at most eight exact group-node names.")
    return [name(item, "group_path item") for item in value]


def object_mode(bpy: Any) -> None:
    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader-group mutations require Object Mode for verified recovery.")


def bounded_tree(tree: Any) -> None:
    if len(tree.nodes) > MAX_NODES or len(tree.links) > MAX_LINKS:
        raise invalid_argument("Shader-group editing supports at most 256 nodes / 1,024 links per tree.")
    interface = getattr(tree, "interface", None)
    if interface is not None and len(interface.items_tree) > 128:
        raise invalid_argument("Shader-group interfaces support at most 128 items.")


def group_exact(bpy: Any, value: Any) -> Any:
    group_name = name(value, "group_name")
    matches = list(islice((g for g in bpy.data.node_groups if g.name == group_name), 2))
    if len(matches) != 1 or matches[0].bl_idname != "ShaderNodeTree":
        raise invalid_argument("'group_name' must identify exactly one ShaderNodeTree, without library-name ambiguity.")
    return matches[0]


def ownership(bpy: Any, tree: Any, check: Callable[[], None] | None = None) -> dict:
    """Trace parent shader groups to material/world/light owners; never infer full scene effects."""
    pending = deque([tree])
    visited: set[int] = set()
    seen_owners: set[int] = set()
    materials, material_owners, objects, roots, groups, direct, reasons = [], [], set(), [], [], [], []
    readonly, direct_count = False, 0
    while pending:
        if check:
            check()
        current = pending.popleft()
        if _key(current) in visited:
            continue
        if len(visited) >= MAX_GROUPS:
            reasons.append("parent_group_budget")
            break
        visited.add(_key(current))
        groups.append(current.name)
        users = bpy.data.user_map(subset={current}).get(current, set())
        if current == tree:
            direct_count = len(users)
        if len(users) > MAX_OWNERS:
            reasons.append("owner_budget")
        for owner in islice(users, MAX_OWNERS):
            kind = owner.bl_rna.identifier
            record = {"name": owner.name, "type": kind, "local_editable": bool(local_editable(owner))}
            if current == tree:
                direct.append(record)
            if _key(owner) in seen_owners:
                continue
            if len(seen_owners) >= MAX_OWNERS:
                reasons.append("owner_budget")
                break
            seen_owners.add(_key(owner))
            readonly |= not record["local_editable"]
            if getattr(owner, "bl_idname", None) == "ShaderNodeTree":
                pending.append(owner)
            elif kind == "Material":
                material_owners.append(owner)
            else:
                roots.append(record)
    if material_owners:
        from .materials import _material_usage

        # A shared group may reach many materials: inspect object slots once, not once per material.
        material_set = set(material_owners)
        usage = _material_usage(bpy, material_set)
        user_map = bpy.data.user_map(subset=material_set)
        for owner in material_owners:
            if check:
                check()
            scope, owners = material_scope(bpy, owner, user_map=user_map, object_usage=usage[owner])
            readonly |= any(not local_editable(user) for user in owners)
            materials.append({"name": owner.name, "material_users": scope["material_users"],
                              "affected_object_count": scope["affected_object_count"],
                              "indirect_users_possible": scope["indirect_users_possible"]})
            objects.update(scope["affected_objects"])
            if scope["affected_objects_truncated"] or scope["direct_users_truncated"] or len(objects) > MAX_OWNERS:
                reasons.append("material_user_budget")
    return {"group_name": tree.name, "group_users": int(tree.users),
            "group_local_editable": bool(local_editable(tree)), "direct_users": sorted(direct, key=lambda u: (u["type"], u["name"])),
            "direct_user_count": direct_count, "direct_users_truncated": direct_count > len(direct),
            "parent_groups": sorted(groups), "materials": sorted(materials, key=lambda m: m["name"]),
            "affected_objects": sorted(objects)[:MAX_OWNERS], "other_owners": sorted(roots, key=lambda u: (u["type"], u["name"])),
            "readonly_owner": readonly, "coverage_complete": not reasons, "incomplete_reasons": sorted(set(reasons)),
            "requires_shared_consent": (tree.users > 1 or len(materials) > 1 or len(objects) > 1 or bool(roots)
                                        or any(m["material_users"] > 1 or m["affected_object_count"] > 1
                                               or m["indirect_users_possible"] for m in materials)),
            "scope": "Transitive parent shader groups, material-slot object users and direct non-shader owners; not evaluated geometry, instances or complete scene appearance."}


def editable(bpy: Any, tree: Any, params: Mapping[str, Any], check: Callable[[], None] | None = None) -> dict:
    allow = params.get("allow_shared", False)
    if not isinstance(allow, bool):
        raise invalid_argument("'allow_shared' must be a boolean.")
    object_mode(bpy)
    if not local_editable(tree):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader edits require local editable, non-override groups.")
    bounded_tree(tree)
    scope = ownership(bpy, tree, check)
    if not scope["coverage_complete"]:
        raise invalid_argument("Shader ownership evidence exceeded its budget; narrow or isolate the group.", **scope)
    if scope["readonly_owner"]:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader-group changes cannot affect linked, override or read-only owners.", scope)
    if scope["requires_shared_consent"] and not allow:
        raise invalid_argument("Inspect group users and explicitly allow_shared only when every affected user is in scope.", **scope)
    return scope


def resolve(bpy: Any, material: Any, params: Mapping[str, Any], *, modify: bool = False,
            check: Callable[[], None] | None = None) -> Any:
    tree = material.node_tree
    seen = {_key(tree)}
    names = path(params)
    for node_name in names:
        if check:
            check()
        bounded_tree(tree)
        node = tree.nodes.get(node_name)
        if node is None or node.bl_idname != "ShaderNodeGroup" or node.node_tree is None:
            raise invalid_argument("'group_path' must follow exact bound ShaderNodeGroup nodes.", node_name=node_name)
        tree = node.node_tree
        if tree.bl_idname != "ShaderNodeTree" or _key(tree) in seen:
            raise invalid_argument("Shader path has an invalid tree type or recursive group reference.")
        seen.add(_key(tree))
        if modify and not local_editable(tree):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader path contains linked, override or read-only data.")
    if names and modify:
        editable(bpy, tree, params, check)
    return tree
