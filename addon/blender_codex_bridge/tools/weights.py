"""Bounded vertex-group weight authoring, with rollback and explicit scope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import get_object, int_param, reject_unknown_params
from ._mesh_safety import require_local_single_user_mesh
from ._rna import bounded_name


def _object(params: Mapping[str, Any], *, modify: bool = False) -> Any:
    obj = get_object(params.get("object_name"), allow_active=False)
    if obj.type != "MESH" or obj.mode != "OBJECT":
        raise invalid_argument("Weight tools require a mesh in Object Mode.")
    if len(obj.vertex_groups) > 128 or len(obj.data.vertices) > 200_000:
        raise invalid_argument("Weight inspection/editing budget exceeded.")
    if modify:
        require_local_single_user_mesh(obj)
    return obj


def _indices(obj: Any, value: Any) -> list[int]:
    if not isinstance(value, list) or not 1 <= len(value) <= 1000:
        raise invalid_argument("vertex_indices must contain 1-1000 indices.")
    if any(type(i) is not int or not 0 <= i < len(obj.data.vertices) for i in value) or len(
        set(value)
    ) != len(value):
        raise invalid_argument("Vertex indices must be unique, in-range integers.")
    return value


def _members(obj: Any, indices: list[int]) -> list[dict[str, Any]]:
    names = {group.index: group.name for group in obj.vertex_groups}
    return [
        {
            "vertex_index": i,
            "weights": {names[g.group]: g.weight for g in obj.data.vertices[i].groups},
        }
        for i in indices
    ]


def inspect(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "offset", "max_vertices"})
    obj = _object(params)
    offset = int_param(params, "offset", 0, minimum=0, maximum=200_000)
    maximum = int_param(params, "max_vertices", 50, minimum=1, maximum=128)
    indices = list(range(offset, min(offset + maximum, len(obj.data.vertices))))
    end = offset + len(indices)
    return {
        "object": obj.name,
        "groups": [{"name": g.name, "locked": g.lock_weight} for g in obj.vertex_groups],
        "vertices": _members(obj, indices),
        "vertex_count": len(obj.data.vertices),
        "truncated": end < len(obj.data.vertices),
        "next_offset": end if end < len(obj.data.vertices) else None,
    }


def group_create(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "group_name"})
    obj = _object(params, modify=True)
    name = bounded_name(params.get("group_name"), "group_name", maximum=63)
    if (
        len(name.encode("utf-8")) > 63
        or obj.vertex_groups.get(name)
        or len(obj.vertex_groups) >= 128
    ):
        raise invalid_argument("Group name is unavailable or group limit reached.")
    active = obj.vertex_groups.active_index
    group = obj.vertex_groups.new(name=name)
    obj.vertex_groups.active_index = active
    return {"object": obj.name, "affected_objects": [obj.name], "group_name": group.name}


def _apply(obj: Any, updates: list[tuple[Any, int, float | None]]) -> dict[str, Any]:
    before = []
    for group, index, _ in updates:
        old = next(
            (g.weight for g in obj.data.vertices[index].groups if g.group == group.index), None
        )
        before.append((group, index, old))
    try:
        for group, index, value in updates:
            if value is None:
                group.remove([index])
            else:
                group.add([index], value, "REPLACE")
    except Exception as exc:
        restored = True
        for group, index, value in before:
            try:
                group.remove([index]) if value is None else group.add([index], value, "REPLACE")
            except Exception:
                import logging

                logging.getLogger(__name__).exception("Weight rollback failed")
                restored = False
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Weight edit failed; reinspect the tracked operation.",
            {
                "object": obj.name,
                "execution_started": True,
                "verification_required": True,
                "rollback_performed": restored,
            },
        ) from exc
    indices = sorted({i for _, i, _ in updates})
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "updated_memberships": len(updates),
        "vertices": _members(obj, indices[:128]),
        "truncated": len(indices) > 128,
        "selection_changed": False,
    }


def assign(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "group_name", "vertex_indices", "weight"})
    obj = _object(params, modify=True)
    name = bounded_name(params.get("group_name"), "group_name")
    group = obj.vertex_groups.get(name)
    if group is None or group.lock_weight:
        raise invalid_argument("Named vertex group must exist and be unlocked.")
    indices = _indices(obj, params.get("vertex_indices"))
    value = params.get("weight")
    if value is not None and (type(value) not in (int, float) or not 0 <= value <= 1):
        raise invalid_argument(
            "weight must be a finite number in [0,1], or null to remove membership."
        )
    if "weight" not in params:
        raise invalid_argument("weight is required (null removes memberships).")
    return _apply(obj, [(group, i, value) for i in indices])


def normalize(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "group_names", "vertex_indices"})
    obj = _object(params, modify=True)
    indices = _indices(obj, params.get("vertex_indices"))
    names = params.get("group_names")
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 32
        or any(not isinstance(n, str) for n in names)
        or len(set(names)) != len(names)
    ):
        raise invalid_argument("group_names must contain 1-32 unique names.")
    groups = [obj.vertex_groups.get(name) for name in names]
    if any(group is None or group.lock_weight for group in groups):
        raise invalid_argument("Normalization groups must exist and be unlocked.")
    selected = {g.index for g in groups}
    updates = []
    for index in indices:
        weights = {g.group: g.weight for g in obj.data.vertices[index].groups}
        untouched = sum(w for g, w in weights.items() if g not in selected)
        total = sum(weights.get(g.index, 0) for g in groups)
        if untouched > 1 + 1e-6 or total <= 0:
            raise invalid_argument(
                "Cannot normalize zero target weights or preserve untouched weights exceeding one.",
                vertex_index=index,
            )
        for group in groups:
            if group.index in weights:
                updates.append((group, index, weights[group.index] / total * max(0, 1 - untouched)))
    return _apply(obj, updates)


def register_tools(registry: Any) -> None:
    for name, handler in (
        ("inspect", inspect),
        ("group_create", group_create),
        ("assign", assign),
        ("normalize", normalize),
    ):
        registry.register(
            f"weights.{name}",
            handler,
            toolset="weights",
            modifies=name != "inspect",
            permissions=(Permission.INSPECT_SCENE,)
            if name == "inspect"
            else (Permission.EDIT_MESH,),
            description=handler.__doc__ or f"Bounded vertex weights: {name}.",
        )
