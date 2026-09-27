"""Bounded material ownership evidence and pre-mutation authorization of scope."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..utils import similar_names

LIMIT = 100


def material_exact(bpy: Any, name: str) -> Any:
    matches = list(islice((m for m in bpy.data.materials if m.name == name), 2))
    if not matches:
        raise BridgeError(
            ErrorCode.MATERIAL_NOT_FOUND,
            f"Material '{name}' does not exist.",
            {"available_similar_materials": similar_names(name, bpy.data.materials.keys())},
        )
    if len(matches) > 1:
        raise invalid_argument(
            "Material name is ambiguous across local/linked libraries; use a unique name.",
            material_name=name,
            matching_count_is_lower_bound=True,
            matching_count=2,
        )
    return matches[0]


def local_editable(owner: Any) -> bool:
    return owner.library is None and owner.override_library is None and owner.is_editable


def material_scope(
    bpy: Any,
    material: Any,
    *,
    user_map: Mapping | None = None,
    object_usage: Mapping | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    if user_map is None:
        user_map = bpy.data.user_map(subset={material})
    users = user_map.get(material, set())
    owners = list(islice(users, LIMIT))
    objects = []
    count = 0
    if object_usage is not None:
        objects = object_usage["objects"]
        count = object_usage["object_count"]
    else:
        for obj in bpy.data.objects:
            if any(slot.material == material for slot in obj.material_slots):
                count += 1
                if len(objects) < LIMIT:
                    objects.append(obj.name)
    indirect = any(
        owner.bl_rna.identifier
        not in {
            "Object",
            "Mesh",
            "Curve",
            "Curves",
            "MetaBall",
            "Volume",
            "PointCloud",
            "GreasePencil",
        }
        for owner in owners
    )
    return {
        "material_local_editable": bool(local_editable(material)),
        "material_library_linked": material.library is not None,
        "material_library_override": material.override_library is not None,
        "material_users": material.users,
        "affected_objects": sorted(objects),
        "affected_object_count": count,
        "affected_objects_truncated": count > LIMIT,
        "direct_users": sorted(
            [
                {
                    "name": owner.name,
                    "type": owner.bl_rna.identifier,
                    "local_editable": bool(local_editable(owner)),
                }
                for owner in owners
            ],
            key=lambda item: (item["type"], item["name"]),
        ),
        "direct_user_count": len(users),
        "direct_users_truncated": len(users) > LIMIT,
        "indirect_users_possible": indirect,
        "object_scope": "material_slots_only_not_transitive_dependencies",
        "requires_shared_consent": count > 1 or material.users > 1 or indirect,
    }, owners


def editable_material_scope(
    bpy: Any, material: Any, params: Mapping[str, Any], *, unlink: bool = False
) -> dict[str, Any]:
    allow = params.get("allow_shared", False)
    if not isinstance(allow, bool):
        raise invalid_argument("'allow_shared' must be a boolean.")
    if not local_editable(material) or (
        material.node_tree is not None and not local_editable(material.node_tree)
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED, "Material edits require local, editable, non-override data."
        )
    scope, owners = material_scope(bpy, material)
    if scope["affected_objects_truncated"] or scope["direct_users_truncated"]:
        raise invalid_argument("Material scope exceeds the 100-user evidence limit.", **scope)
    if scope["requires_shared_consent"] and not allow:
        raise invalid_argument(
            "Inspect material usage, then set 'allow_shared' to true only if all users are in scope.",
            **scope,
        )
    if unlink:
        if any(not local_editable(owner) for owner in owners):
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Forced unlink requires local, editable, non-override users.",
                scope,
            )
        for obj in bpy.data.objects:
            if not any(slot.material == material for slot in obj.material_slots):
                continue
            if not local_editable(obj) or obj.mode != "OBJECT":
                raise BridgeError(
                    ErrorCode.NOT_IMPLEMENTED,
                    "Forced unlink requires local object users in Object Mode.",
                    scope,
                )
    return scope
