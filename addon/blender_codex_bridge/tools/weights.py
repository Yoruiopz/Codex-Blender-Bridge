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
        ("smooth", smooth),
        ("transfer", transfer),
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


def _group(obj: Any, name: Any, *, writable: bool) -> Any:
    group = obj.vertex_groups.get(bounded_name(name, "group_name"))
    if group is None or (writable and group.lock_weight):
        raise invalid_argument("Named group must exist; target groups must be unlocked.")
    return group


def _weight(obj: Any, group: Any, index: int) -> float | None:
    return next((g.weight for g in obj.data.vertices[index].groups if g.group == group.index), None)


def smooth(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Smooth one group across mesh edges; only explicit target vertices are changed."""
    reject_unknown_params(
        params, {"object_name", "group_name", "vertex_indices", "iterations", "factor"}
    )
    obj = _object(params, modify=True)
    group = _group(obj, params.get("group_name"), writable=True)
    indices = _indices(obj, params.get("vertex_indices"))
    iterations = int_param(params, "iterations", 1, minimum=1, maximum=20)
    factor = params.get("factor", 0.5)
    if type(factor) not in (int, float) or not 0 <= factor <= 1:
        raise invalid_argument("factor must be finite and between 0 and 1.")
    if len(obj.data.edges) > 400_000:
        raise invalid_argument("Smoothing requires at most 400000 mesh edges.")
    neighbors: dict[int, set[int]] = {index: set() for index in indices}
    for edge in obj.data.edges:
        a, b = edge.vertices
        if a in neighbors:
            neighbors[a].add(b)
        if b in neighbors:
            neighbors[b].add(a)
    if sum(len(items) for items in neighbors.values()) > 20_000:
        raise invalid_argument("Selected one-ring neighborhood exceeds 20000 adjacency entries.")
    support = set(indices).union(*(neighbors[i] for i in indices))
    original = {i: _weight(obj, group, i) for i in support}
    values = {i: value if value is not None else 0.0 for i, value in original.items()}
    for _ in range(iterations):
        if getattr(context, "check_cancelled", None):
            context.check_cancelled()
        # Simultaneous iterations: outside targets provide fixed boundary values.
        updates = {
            i: (1 - factor) * values[i]
            + factor * sum(values[n] for n in sorted(neighbors[i])) / len(neighbors[i])
            for i in indices
            if neighbors[i]
        }
        values.update(updates)
    changes = [(group, i, values[i]) for i in indices if values[i] != (original[i] or 0.0)]
    return {
        "operation": "smooth",
        "iterations": iterations,
        "factor": factor,
        "target_vertex_count": len(indices),
        "boundary_vertex_count": len(support) - len(indices),
        "normalization_performed": False,
        **_apply(obj, changes),
    }


def transfer(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Copy one group through explicit vertex pairs; missing source membership removes target membership."""
    reject_unknown_params(
        params,
        {
            "source_object",
            "source_group",
            "object_name",
            "group_name",
            "source_indices",
            "vertex_indices",
        },
    )
    target = _object(params, modify=True)
    source = _object({"object_name": params.get("source_object")})
    source_group = _group(source, params.get("source_group"), writable=False)
    target_group = _group(target, params.get("group_name"), writable=True)
    source_indices = _indices(source, params.get("source_indices"))
    target_indices = _indices(target, params.get("vertex_indices"))
    if len(source_indices) != len(target_indices):
        raise invalid_argument(
            "Source and target lists must have equal lengths; pairs are positional."
        )
    # Snapshot all source values before writes, including overlapping same-object mappings.
    changes = [
        (target_group, dest, _weight(source, source_group, src))
        for src, dest in zip(source_indices, target_indices, strict=True)
    ]
    if getattr(context, "check_cancelled", None):
        context.check_cancelled()
    return {
        "operation": "transfer",
        "source_object": source.name,
        "source_group": source_group.name,
        "mapped_vertex_count": len(changes),
        "normalization_performed": False,
        **_apply(target, changes),
    }
