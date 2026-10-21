"""Bounded geometry-aware skin weights with explicit scope and measured recovery."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, NamedTuple

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import reject_unknown_params, require_blender
from . import weights
from ._object_safety import require_single_user_object_data
from ._rna import bounded_name

MAX_VERTICES = 4096
MAX_PAIRS = 262144
EPS = 1e-6


def _gate(context: Any) -> None:
    context.require(Permission.EDIT_MESH)
    if getattr(context, "check_cancelled", None):
        context.check_cancelled()
    context.require(Permission.EDIT_MESH)
    state = getattr(context, "state", None)
    if state is not None:
        flags = state.snapshot()
        if flags["emergency_stopped"] or flags["paused"]:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags["emergency_stopped"] else ErrorCode.AGENT_PAUSED,
                              "Weight editing stopped before its next safe action.")


def _object(name: Any, *, modify: bool) -> Any:
    obj = weights._object({"object_name": name}, modify=modify)
    if (len(obj.data.vertices) > MAX_VERTICES or len(getattr(obj.data, "polygons", ())) > 4096
            or len(getattr(obj.data, "edges", ())) > 16384):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Geometry-aware weights support at most 4096 base vertices/polygons per object.")
    if modify:
        require_single_user_object_data(obj, operation="Geometry-aware weight editing")
    return obj


def _number(value: Any, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float):
        raise invalid_argument(f"{name} must be a finite number within [{low}, {high}].")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(f"{name} must be finite.") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise invalid_argument(f"{name} must be a finite number within [{low}, {high}].")
    return result


def _vector(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise invalid_argument(f"{name} must contain exactly three numbers.")
    return tuple(_number(item, name, -1e9, 1e9) for item in value)


def _indices(obj: Any, value: Any, maximum: int) -> list[int]:
    if (not isinstance(value, list) or not 1 <= len(value) <= maximum
            or any(type(i) is not int or not 0 <= i < len(obj.data.vertices) for i in value)
            or len(set(value)) != len(value)):
        raise invalid_argument(f"Choose 1-{maximum} unique existing vertex indices.")
    return value


def _groups(obj: Any, names: Any, *, protected: Any = None) -> list[Any]:
    if not isinstance(names, list) or not 1 <= len(names) <= 16 or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise invalid_argument("Choose 1-16 distinct target groups.")
    if protected is None:
        protected = []
    if (not isinstance(protected, list) or len(protected) > 128
            or any(not isinstance(name, str) for name in protected) or len(set(protected)) != len(protected)):
        raise invalid_argument("protected_groups must contain at most 128 unique existing names.")
    for name in protected:
        weights._group(obj, name, writable=False)
    groups = [weights._group(obj, name, writable=True) for name in names]
    if any(group.name in protected for group in groups):
        raise invalid_argument("A protected group cannot also be a target.")
    return groups


def _mapping(source: Any, target: Any, value: Any, protected: Any) -> list[tuple[Any, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise invalid_argument("group_mapping must contain 1-16 explicit source/target pairs.")
    pairs = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"source_group", "target_group"}:
            raise invalid_argument("Each mapping requires source_group and target_group.")
        source_group = weights._group(source, item["source_group"], writable=False)
        target_name = bounded_name(item["target_group"], "target_group")
        pairs.append((source_group, target_name))
    targets = _groups(target, [name for _, name in pairs], protected=protected)
    return [(pair[0], group) for pair, group in zip(pairs, targets, strict=True)]


def _matrix(obj: Any) -> tuple[tuple[float, ...], ...]:
    matrix = tuple(tuple(_number(v, "matrix", -1e9, 1e9) for v in row) for row in obj.matrix_world)
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise invalid_argument("Object has an unsupported transform matrix.")
    return matrix


def _inverse(matrix: tuple[tuple[float, ...], ...]) -> list[list[float]]:
    rows = [list(row) + [float(i == j) for j in range(4)] for i, row in enumerate(matrix)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-15:
            raise invalid_argument("LOCAL surface transfer requires an invertible target transform.")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        denominator = rows[column][column]
        rows[column] = [value / denominator for value in rows[column]]
        for row in range(4):
            if row != column:
                factor = rows[row][column]
                rows[row] = [a - factor * b for a, b in zip(rows[row], rows[column], strict=True)]
    return [row[4:] for row in rows]


def _transform(matrix: Any, point: Any) -> tuple[float, float, float]:
    values = (*point, 1.0)
    result = tuple(sum(row[i] * values[i] for i in range(4)) for row in matrix[:3])
    if any(not math.isfinite(value) or abs(value) > 1e12 for value in result):
        raise invalid_argument("Transformed coordinates exceed the bounded geometry contract.")
    return result


def _coordinates(obj: Any, space: str, target: Any) -> list[tuple[float, float, float]]:
    if not isinstance(space, str) or space not in {"LOCAL", "WORLD"}:
        raise invalid_argument("coordinate_space must be LOCAL or WORLD.")
    points = [_vector(tuple(vertex.co), "vertex coordinates") for vertex in obj.data.vertices]
    if space == "WORLD":
        matrix = _matrix(obj)
        return [_transform(matrix, point) for point in points]
    if obj == target:
        return points
    inverse, matrix = _inverse(_matrix(target)), _matrix(obj)
    return [_transform(inverse, _transform(matrix, point)) for point in points]


def _weight(obj: Any, group: Any, index: int) -> float:
    value = weights._weight(obj, group, index)
    return 0.0 if value is None else _number(value, "source weight", 0.0, 1.0)


def _snapshot(obj: Any) -> dict[str, Any]:
    indices = {group.index for group in obj.vertex_groups}
    for vertex in obj.data.vertices:
        for member in vertex.groups:
            if member.group not in indices:
                raise invalid_argument("Mesh contains a membership without a matching vertex group.")
            _number(member.weight, "existing weight", 0., 1.)
    return {
        "matrix": _matrix(obj), "mode": obj.mode, "data_identity": id(obj.data) if not hasattr(obj.data, "as_pointer") else int(obj.data.as_pointer()),
        "data_users": int(obj.data.users), "object_name": obj.name, "data_name": obj.data.name,
        "polygons": [tuple(poly.vertices) for poly in getattr(obj.data, "polygons", ())],
        "edges": [tuple(edge.vertices) for edge in getattr(obj.data, "edges", ())],
        "groups": [(g.name, g.index, bool(g.lock_weight)) for g in obj.vertex_groups],
        "active_group": obj.vertex_groups.active_index,
        "vertices": [(tuple(vertex.co), tuple((g.group, g.weight) for g in vertex.groups)) for vertex in obj.data.vertices],
    }


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _matches(before: dict, after: dict, allowed: dict[tuple[int, int], float | None]) -> bool:
    if any(before[key] != after[key] for key in ("matrix", "mode", "groups", "active_group", "data_identity", "data_users", "object_name", "data_name", "polygons", "edges")):
        return False
    if len(before["vertices"]) != len(after["vertices"]):
        return False
    by_vertex: dict[int, dict[int, float | None]] = {}
    for (vertex, group), value in allowed.items():
        by_vertex.setdefault(vertex, {})[group] = value
    for index, ((co, old), (new_co, observed)) in enumerate(zip(before["vertices"], after["vertices"], strict=True)):
        if co != new_co:
            return False
        expected = dict(old)
        for group, value in by_vertex.get(index, {}).items():
            if value is None:
                expected.pop(group, None)
            else:
                expected[group] = value
        actual = dict(observed)
        if set(actual) != set(expected) or any(
            not math.isfinite(actual[g]) or (
                abs(actual[g] - value) > EPS if (index, g) in allowed else actual[g] != value
            ) for g, value in expected.items()
        ):
            return False
    return True


def _write_guard(context: Any, target: Any, frozen: dict, index: int) -> None:
    _gate(context)
    require_single_user_object_data(target, operation="Geometry-aware weight editing")
    pointer = target.data.as_pointer() if hasattr(target.data, "as_pointer") else id(target.data)
    if pointer != frozen["data_identity"]:
        raise invalid_argument("The target mesh identity changed before a weight write.")
    if [(g.name, g.index, bool(g.lock_weight)) for g in target.vertex_groups] != frozen["groups"]:
        raise invalid_argument("Vertex-group ownership changed before a weight write.")
    if (target.mode != "OBJECT" or len(target.data.vertices) != len(frozen["vertices"])
            or [tuple(vertex.co) for vertex in target.data.vertices] != [vertex[0] for vertex in frozen["vertices"]]
            or [tuple(poly.vertices) for poly in getattr(target.data, "polygons", ())] != frozen["polygons"]
            or [tuple(edge.vertices) for edge in getattr(target.data, "edges", ())] != frozen["edges"]):
        raise invalid_argument("Target geometry/context changed before a weight write.")


def _apply(context: Any, target: Any, updates: list[tuple[Any, int, float]], source: Any | None,
           frozen_target: dict, frozen_source: dict | None) -> dict:
    allowed = {(index, group.index): value for group, index, value in updates}
    if len(allowed) != len(updates):
        raise invalid_argument("Duplicate target membership writes are not supported.")
    attempted = []
    old = {i: dict(frozen_target["vertices"][i][1]) for i in {i for _, i, _ in updates}}
    try:
        _gate(context)
        require_single_user_object_data(target, operation="Geometry-aware weight editing")
        if _snapshot(target) != frozen_target or (source is not None and source != target and _snapshot(source) != frozen_source):
            raise invalid_argument("Source or target changed while preparing the frozen weight operation.")
        for group, index, value in updates:
            _write_guard(context, target, frozen_target, index)
            attempted.append((group, index))
            group.add([index], value, "REPLACE")
        target.data.update()
        target.update_tag(refresh={"DATA"})
        require_blender().context.view_layer.update()
        _gate(context)
        post = _snapshot(target)
        if not _matches(frozen_target, post, allowed) or (source is not None and source != target and _snapshot(source) != frozen_source):
            raise RuntimeError("Weight readback or preservation verification failed")
    except Exception as exc:
        restored = not attempted
        try:
            for group, index in reversed(attempted):
                _write_guard(context, target, frozen_target, index)
                original = old[index].get(group.index)
                group.remove([index]) if original is None else group.add([index], original, "REPLACE")
            if attempted:
                target.data.update()
                target.update_tag(refresh={"DATA"})
                require_blender().context.view_layer.update()
            restored = _matches(frozen_target, _snapshot(target), {})
        except Exception:
            restored = False
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Weight operation did not complete; reinspect before continuing.",
                          {"object": target.name, "execution_started": bool(attempted),
                           "attempted_memberships": len(attempted), "rollback_verified": restored,
                           "possible_mutation": bool(attempted) and not restored,
                           "verification_required": True}) from exc
    indices = sorted({i for _, i, _ in updates})
    return {"object": target.name, "affected_objects": [target.name], "changed": bool(updates),
            "updated_memberships": len(updates), "vertices": weights._members(target, indices[:128]),
            "truncated": len(indices) > 128, "maximum_returned": 128,
            "preservation_verified": True, "complete_membership_readback_verified": True,
            "before_sha256": _digest(frozen_target), "after_sha256": _digest(post),
            "normalization_performed": False, "selection_changed": False}


def brush_stroke(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "group_name", "vertex_indices", "strokes", "coordinate_space", "blend_mode", "falloff", "protected_groups"})
    _gate(context)
    obj = _object(params.get("object_name"), modify=True)
    group = _groups(obj, [params.get("group_name")], protected=params.get("protected_groups"))[0]
    indices = _indices(obj, params.get("vertex_indices"), 1000)
    space, blend, falloff = params.get("coordinate_space"), params.get("blend_mode"), params.get("falloff")
    if not isinstance(space, str) or not isinstance(blend, str) or not isinstance(falloff, str) or blend not in {"MIX", "ADD", "SUBTRACT"} or falloff not in {"CONSTANT", "LINEAR", "SMOOTH"}:
        raise invalid_argument("Choose explicit LOCAL/WORLD, MIX/ADD/SUBTRACT and CONSTANT/LINEAR/SMOOTH brush settings.")
    points = _coordinates(obj, space, obj)
    strokes = params.get("strokes")
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 32:
        raise invalid_argument("strokes must contain 1-32 explicit dabs.")
    parsed = []
    for stroke in strokes:
        if not isinstance(stroke, Mapping) or set(stroke) != {"center", "radius", "strength", "weight"}:
            raise invalid_argument("Each dab requires center, radius, strength and weight.")
        parsed.append((_vector(stroke["center"], "center"), _number(stroke["radius"], "radius", 1e-9, 1e6),
                       _number(stroke["strength"], "strength", 0, 1), _number(stroke["weight"], "weight", 0, 1)))
    frozen = _snapshot(obj)
    values = {i: _weight(obj, group, i) for i in indices}
    originals = dict(values)
    for center, radius, strength, weight in parsed:
        _gate(context)
        for index in indices:
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(points[index], center, strict=True)))
            if distance > radius:
                continue
            factor = 1.0 if falloff == "CONSTANT" else max(0, 1 - distance / radius)
            if falloff == "SMOOTH":
                factor = factor * factor * (3 - 2 * factor)
            influence = factor * strength
            delta = (weight - values[index]) if blend == "MIX" else weight * (1 if blend == "ADD" else -1)
            values[index] = min(1.0, max(0.0, values[index] + influence * delta))
    updates = [(group, i, value) for i, value in values.items() if value != originals[i]]
    return {"operation": "brush_stroke", "coordinate_space": space, "dab_count": len(parsed),
            "blend_mode": blend, "falloff": falloff, **_apply(context, obj, updates, None, frozen, None)}


def mirror_geometric(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "source_vertex_indices", "vertex_indices", "group_mapping", "axis", "plane_offset", "coordinate_space", "max_distance", "protected_groups"})
    _gate(context)
    obj = _object(params.get("object_name"), modify=True)
    sources = _indices(obj, params.get("source_vertex_indices"), 1024)
    targets = _indices(obj, params.get("vertex_indices"), 256)
    if len(sources) * len(targets) > MAX_PAIRS:
        raise invalid_argument("Mirror correspondence exceeds 262144 vertex pairs.")
    mapping = _mapping(obj, obj, params.get("group_mapping"), params.get("protected_groups"))
    axis = params.get("axis")
    if not isinstance(axis, str) or axis not in {"X", "Y", "Z"}:
        raise invalid_argument("axis must be X, Y or Z.")
    plane = _number(params.get("plane_offset"), "plane_offset", -1e6, 1e6)
    maximum = _number(params.get("max_distance"), "max_distance", 0, 1e6)
    points = _coordinates(obj, params.get("coordinate_space"), obj)
    component = "XYZ".index(axis)
    mirrored = {}
    for index in sources:
        point = list(points[index])
        point[component] = 2 * plane - point[component]
        mirrored[index] = point
    frozen = _snapshot(obj)
    samples = {(i, group.index): _weight(obj, group, i) for group, _ in mapping for i in sources}
    matched, used = [], set()
    updates = []
    for index in targets:
        _gate(context)
        distances = [(sum((a - b) ** 2 for a, b in zip(points[index], mirrored[source], strict=True)), source) for source in sources]
        distance, source = min(distances)
        if distance > maximum * maximum or sum(math.isclose(d, distance, rel_tol=1e-9, abs_tol=1e-18) for d, _ in distances) != 1 or source in used:
            raise invalid_argument("Mirror targets require unique unambiguous one-to-one matches within max_distance.", vertex_index=index)
        used.add(source)
        matched.append({"vertex_index": index, "source_vertex_index": source, "distance": math.sqrt(distance)})
        updates.extend((target_group, index, samples[source, source_group.index]) for source_group, target_group in mapping)
    return {"operation": "mirror_geometric", "coordinate_space": params["coordinate_space"],
            "mapped_vertex_count": len(matched), "correspondence": matched[:128],
            "correspondence_truncated": len(matched) > 128, **_apply(context, obj, updates, None, frozen, None)}


def _dot(a: Any, b: Any) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _sub(a: Any, b: Any) -> tuple[float, ...]:
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _closest(point: Any, a: Any, b: Any, c: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(point, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        bary = (1.0, 0.0, 0.0)
    else:
        bp = _sub(point, b)
        d3, d4 = _dot(ab, bp), _dot(ac, bp)
        if d3 >= 0 and d4 <= d3:
            bary = (0.0, 1.0, 0.0)
        else:
            vc = d1 * d4 - d3 * d2
            if vc <= 0 and d1 >= 0 and d3 <= 0:
                v = d1 / (d1 - d3)
                bary = (1 - v, v, 0.0)
            else:
                cp = _sub(point, c)
                d5, d6 = _dot(ab, cp), _dot(ac, cp)
                if d6 >= 0 and d5 <= d6:
                    bary = (0.0, 0.0, 1.0)
                else:
                    vb = d5 * d2 - d1 * d6
                    if vb <= 0 and d2 >= 0 and d6 <= 0:
                        w = d2 / (d2 - d6)
                        bary = (1 - w, 0.0, w)
                    else:
                        va = d3 * d6 - d5 * d4
                        if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
                            w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
                            bary = (0.0, 1 - w, w)
                        else:
                            denominator = va + vb + vc
                            bary = (1 - vb / denominator - vc / denominator, vb / denominator, vc / denominator)
    closest = tuple(sum(bary[i] * triangle[i] for i in range(3)) for triangle in zip(a, b, c, strict=True))
    return closest, bary


class _Triangle(NamedTuple):
    polygon_index: int
    vertices: tuple[int, int, int]


def transfer_surface(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"source_object", "object_name", "source_polygon_indices", "vertex_indices", "group_mapping", "coordinate_space", "max_distance", "protected_groups"})
    _gate(context)
    target = _object(params.get("object_name"), modify=True)
    source = _object(params.get("source_object"), modify=False)
    targets = _indices(target, params.get("vertex_indices"), 256)
    polygons = params.get("source_polygon_indices")
    if (not isinstance(polygons, list) or not 1 <= len(polygons) <= 256
            or any(type(i) is not int or not 0 <= i < len(source.data.polygons) for i in polygons)
            or len(set(polygons)) != len(polygons)):
        raise invalid_argument("source_polygon_indices must contain 1-256 unique existing base polygons.")
    mapping = _mapping(source, target, params.get("group_mapping"), params.get("protected_groups"))
    maximum = _number(params.get("max_distance"), "max_distance", 0, 1e6)
    space = params.get("coordinate_space")
    if not isinstance(space, str):
        raise invalid_argument("coordinate_space must be LOCAL or WORLD.")
    source_points, target_points = _coordinates(source, space, target), _coordinates(target, space, target)
    source.data.calc_loop_triangles()
    if len(source.data.loop_triangles) > 8192:
        raise invalid_argument("Source mesh exceeds the 8192-triangle inspection budget.")
    triangles = [_Triangle(int(triangle.polygon_index), tuple(int(i) for i in triangle.vertices))
                 for triangle in source.data.loop_triangles if triangle.polygon_index in set(polygons)]
    if not triangles or len(triangles) > 2048 or len(triangles) * len(targets) > MAX_PAIRS:
        raise invalid_argument("Surface projection requires 1-2048 triangles and at most 262144 triangle/vertex pairs.")
    for triangle in triangles:
        a, b, c = (source_points[i] for i in triangle.vertices)
        ab, ac = _sub(b, a), _sub(c, a)
        area2 = _dot(ab, ab) * _dot(ac, ac) - _dot(ab, ac) ** 2
        if area2 <= 1e-20 * max(_dot(ab, ab), _dot(ac, ac)) ** 2:
            raise invalid_argument("Degenerate source triangles are not accepted for barycentric transfer.")
    frozen_target, frozen_source = _snapshot(target), _snapshot(source)
    samples = {(i, group.index): _weight(source, group, i) for group, _ in mapping for triangle in triangles for i in triangle.vertices}
    updates, correspondence = [], []
    for index in targets:
        _gate(context)
        candidates = []
        for triangle in triangles:
            closest, bary = _closest(target_points[index], *(source_points[i] for i in triangle.vertices))
            distance = _dot(_sub(target_points[index], closest), _sub(target_points[index], closest))
            values = [sum(bary[j] * samples[vertex, source_group.index] for j, vertex in enumerate(triangle.vertices)) for source_group, _ in mapping]
            candidates.append((distance, triangle, closest, bary, values))
        best = min(candidates, key=lambda item: item[0])
        distance, triangle, closest, bary, values = best
        if distance > maximum * maximum:
            raise invalid_argument("A target is farther than max_distance from the explicit source surface.", vertex_index=index)
        for other in candidates:
            if math.isclose(other[0], distance, rel_tol=1e-9, abs_tol=1e-18) and (
                any(abs(a - b) > EPS for a, b in zip(other[2], closest, strict=True))
                or any(abs(a - b) > EPS for a, b in zip(other[4], values, strict=True))
            ):
                raise invalid_argument("Closest-surface correspondence is ambiguous; narrow the explicit source polygons.", vertex_index=index)
        updates.extend((group, index, min(1.0, max(0.0, value))) for (_, group), value in zip(mapping, values, strict=True))
        correspondence.append({"vertex_index": index, "source_polygon_index": triangle.polygon_index,
                               "source_vertex_indices": list(triangle.vertices), "barycentric": list(bary), "distance": math.sqrt(distance)})
    return {"operation": "transfer_surface", "source_object": source.name, "coordinate_space": space,
            "source_geometry": "BASE_MESH", "mapped_vertex_count": len(targets),
            "correspondence": correspondence[:128], "correspondence_truncated": len(correspondence) > 128,
            **_apply(context, target, updates, source, frozen_target, frozen_source)}


def register_tools(registry: Any) -> None:
    for name, handler in (("brush_stroke", brush_stroke), ("mirror_geometric", mirror_geometric), ("transfer_surface", transfer_surface)):
        registry.register(f"weights.{name}", handler, toolset="weights", modifies=True,
                          permissions=(Permission.EDIT_MESH,), description=handler.__doc__ or f"Bounded geometry-aware weights: {name}.")
