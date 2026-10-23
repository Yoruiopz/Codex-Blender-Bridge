"""Bounded base-mesh sculpting and FLOAT_COLOR point/corner painting.

These are explicit component brushes, not viewport projection, multires or a
claim of full sculpt/paint editor coverage. No operator or mode switch is used.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import struct
from array import array
from collections.abc import Mapping
from contextlib import suppress
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import check_final_mutation
from ..utils import bool_param, float_param, int_param, reject_unknown_params, require_blender
from ._object_safety import require_unkeyed_object_data

LOGGER = logging.getLogger(__name__)
MAX_VERTICES, MAX_EDGES, MAX_LOOPS = 100_000, 200_000, 300_000
MAX_COMPONENTS, MAX_STROKES, MAX_TESTS = 10_000, 32, 500_000
MAX_ATTRIBUTE_ITEMS, MAX_ATTRIBUTES = 500_000, 16
MAX_ADJACENCY_TESTS = 2_000_000
_AUTHORITY_ERRORS = frozenset({ErrorCode.PERMISSION_DENIED.value, ErrorCode.TOOLSET_DISABLED.value,
                              ErrorCode.TIMEOUT.value, ErrorCode.AGENT_PAUSED.value, ErrorCode.EMERGENCY_STOPPED.value})


def _name(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip() or any(ord(char) < 32 for char in raw):
        raise invalid_argument(f"{label} must be a nonblank bounded name.")
    try:
        if len(raw.encode("utf-8")) > 63:
            raise invalid_argument(f"{label} must fit 63 UTF-8 bytes.")
    except UnicodeError as exc:
        raise invalid_argument(f"{label} must be valid UTF-8.") from exc
    return raw


def _vector(raw: Any, label: str, length: int, *, low=-1e9, high=1e9) -> tuple[float, ...]:
    if not isinstance(raw, (list, tuple)) or len(raw) != length:
        raise invalid_argument(f"{label} must contain exactly {length} finite numbers.")
    result = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid_argument(f"{label} must contain numeric values, not booleans.")
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise invalid_argument(f"{label} values must be finite.") from exc
        if not math.isfinite(number) or not low <= number <= high:
            raise invalid_argument(f"{label} exceeds its finite [{low},{high}] range.")
        result.append(number)
    return tuple(result)


def _gate(context: Any, method: str, *, modifying=True, deleting=False) -> None:
    required = [Permission.EDIT_MESH] if modifying else [Permission.INSPECT_SCENE]
    if deleting:
        required.append(Permission.DELETE_OBJECTS)
    context.require(*required)
    if context.check_cancelled:
        context.check_cancelled()
    context.require(*required)
    if modifying:
        check_final_mutation(context, method)


def _identity(value: Any) -> int:
    return value.as_pointer() if hasattr(value, "as_pointer") else id(value)


def _target(context: Any, raw: Any, method: str, *, modifying=True):
    name = _name(raw, "object_name")
    _gate(context, method, modifying=modifying)
    bpy = require_blender()
    return bpy, _target_read(bpy, name, modifying=modifying)


def _target_read(bpy: Any, name: str, *, modifying=True):
    """Revalidate the exact native target without live providers or callbacks."""
    matches = list(islice((obj for obj in bpy.data.objects if obj.name == name), 2))
    if len(matches) != 1:
        raise invalid_argument("Object name is missing or ambiguous; no surface edit attempted.", object_name=name)
    obj = matches[0]
    if obj.type != "MESH":
        raise invalid_argument("Surface brushes require an explicitly named mesh object.")
    if bpy.context.mode != "OBJECT" or obj.mode != "OBJECT" or getattr(obj.data, "is_editmode", False):
        raise BridgeError(ErrorCode.INVALID_MODE, "Surface brushes require Object Mode; no mode/selection changes are implicit.")
    mesh = obj.data
    if (len(mesh.vertices) > MAX_VERTICES or len(mesh.edges) > MAX_EDGES or len(mesh.loops) > MAX_LOOPS
            or len(mesh.color_attributes) > MAX_ATTRIBUTES
            or sum(len(layer.data) for layer in mesh.uv_layers) + sum(len(attr.data) for attr in mesh.color_attributes) > MAX_ATTRIBUTE_ITEMS):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Mesh/UV/color data exceeds the bounded surface evidence budget.")
    if modifying:
        require_unkeyed_object_data(obj, operation="Surface brush/attribute editing")
        if len(obj.modifiers):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Surface brushes do not guess evaluated/modifier correspondence; use an explicit unmodified base mesh.")
        if getattr(obj, "hide_viewport", False) or (hasattr(obj, "hide_get") and obj.hide_get()):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Reveal the explicit mesh before surface editing.")
    return obj


def _digest(values: Any) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _float_digest(values: Any) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(struct.pack("<f", value))
    return digest.hexdigest()


def _same_float_rows(left: list[tuple], right: list[tuple]) -> bool:
    """Compare native Float32 storage, including the sign of zero."""
    return len(left) == len(right) and _float_digest(value for row in left for value in row) == _float_digest(value for row in right for value in row)


def _positions(obj: Any) -> list[tuple[float, ...]]:
    return [_vector(tuple(vertex.co), "native vertex coordinate", 3) for vertex in obj.data.vertices]


def _colors(attribute: Any) -> list[tuple[float, ...]]:
    return [_vector(tuple(item.color), "native color", 4, low=-1e9, high=1e9) for item in attribute.data]


def _attribute(mesh: Any, raw: Any):
    name = _name(raw, "attribute_name")
    attribute = mesh.color_attributes.get(name)
    if attribute is None:
        raise invalid_argument("The named color attribute does not exist.", attribute_name=name)
    if attribute.data_type != "FLOAT_COLOR" or attribute.domain not in {"POINT", "CORNER"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Surface color tools support FLOAT_COLOR POINT/CORNER attributes only.")
    expected = len(mesh.vertices) if attribute.domain == "POINT" else len(mesh.loops)
    if len(attribute.data) != expected:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Color attribute domain does not match its complete mesh footprint.")
    return attribute


def _frozen_attribute(mesh: Any, name: str, identity: int, domain: str, data_type: str, colors: list[tuple]):
    current = _attribute(mesh, name)
    if (_identity(current) != identity or current.domain != domain or current.data_type != data_type
            or not _same_float_rows(_colors(current), colors)):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Target attribute identity/domain/complete values changed before publication; no edit attempted.")
    return current


def _preservation(bpy: Any, obj: Any, *, exclude_color: str | None = None, color_ui=True) -> dict:
    mesh = obj.data
    selected = list(islice(bpy.context.selected_objects, 257))
    if len(selected) > 256:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Selected-object context exceeds its bounded preservation window.")
    active = bpy.context.view_layer.objects.active
    return {"object_identity": _identity(obj), "mesh_identity": _identity(mesh),
            "ownership": (mesh.users, bool(getattr(obj, "library", None)), bool(getattr(mesh, "library", None)),
                          bool(getattr(obj, "override_library", None)), bool(getattr(mesh, "override_library", None)),
                          bool(getattr(obj, "is_editable", True)), bool(getattr(mesh, "is_editable", True)),
                          _identity(mesh.shape_keys) if mesh.shape_keys else None,
                          [_identity(modifier) for modifier in obj.modifiers]),
            "context": (bpy.context.mode, obj.mode, [_identity(item) for item in selected], _identity(active) if active else None),
            "matrix": [list(row) for row in obj.matrix_world],
            "topology": _digest({"edges": [list(edge.vertices) for edge in mesh.edges],
                                 "loops": [loop.vertex_index for loop in mesh.loops],
                                 "polygons": [(face.loop_start, face.loop_total, face.material_index, face.use_smooth) for face in mesh.polygons]}),
            "component_flags": _digest({"vertices": [(vertex.select, vertex.hide) for vertex in mesh.vertices],
                                        "edges": [(edge.select, edge.hide) for edge in mesh.edges],
                                        "faces": [(face.select, face.hide) for face in mesh.polygons]}),
            "materials": [(_identity(slot.material) if slot.material else None, slot.link) for slot in obj.material_slots],
            "uv": [(layer.name, layer.active_render, _float_digest(value for item in layer.data for value in item.uv),
                    _digest([bool(item.pin_uv) for item in layer.data])) for layer in mesh.uv_layers],
            "uv_active": mesh.uv_layers.active_index,
            "color_ui": (mesh.color_attributes.active_color_index, mesh.color_attributes.render_color_index) if color_ui else None,
            "other_colors": [(attr.name, attr.domain, attr.data_type, _float_digest(value for color in _colors(attr) for value in color))
                             for attr in mesh.color_attributes if attr.name != exclude_color]}


def _indices(raw: Any, total: int, *, maximum=MAX_COMPONENTS, label="vertex_indices") -> list[int]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= maximum:
        raise invalid_argument(f"{label} must contain 1-{maximum} explicit unique indices.")
    if any(type(value) is not int or not 0 <= value < total for value in raw) or len(set(raw)) != len(raw):
        raise invalid_argument(f"{label} must contain unique in-range integers.")
    return list(raw)


def _mask(params: Mapping[str, Any], obj: Any) -> tuple[list[int], list[float], str]:
    indices = _indices(params.get("vertex_indices"), len(obj.data.vertices))
    if any(obj.data.vertices[index].hide for index in indices):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "The explicit brush scope contains hidden vertices.")
    raw = params.get("mask_weights")
    weights = [1.] * len(indices) if raw is None else list(_vector(raw, "mask_weights", len(indices), low=0., high=1.))
    space = params.get("space", "LOCAL")
    if not isinstance(space, str) or space not in {"LOCAL", "WORLD"}:
        raise invalid_argument("space must be LOCAL or WORLD explicitly.")
    return indices, weights, space


def _strokes(raw: Any, *, color=False) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_STROKES:
        raise invalid_argument("Supply 1-32 explicit bounded strokes.")
    result = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise invalid_argument("Each surface stroke must be a typed object.")
        reject_unknown_params(item, {"center", "radius", "falloff", "color", "opacity"} if color else
                              {"center", "radius", "falloff", "operation", "direction", "strength"})
        center = _vector(item.get("center"), "center", 3)
        radius = float_param(item, "radius", 1., minimum=1e-8, maximum=1e6)
        falloff = item.get("falloff", "SMOOTH")
        if not isinstance(falloff, str) or falloff not in {"SMOOTH", "LINEAR", "CONSTANT"}:
            raise invalid_argument("falloff must be SMOOTH, LINEAR or CONSTANT.")
        stroke = {"center": center, "radius": radius, "falloff": falloff}
        if color:
            stroke.update(color=_vector(item.get("color"), "color", 4, low=0., high=1.),
                          opacity=float_param(item, "opacity", 1., minimum=0., maximum=1.))
        else:
            operation = item.get("operation", "PUSH")
            if not isinstance(operation, str) or operation not in {"PUSH", "SMOOTH"}:
                raise invalid_argument("Sculpt operation must be PUSH or SMOOTH.")
            stroke.update(operation=operation, strength=float_param(item, "strength", .1,
                          minimum=0. if operation == "SMOOTH" else -1e6, maximum=1. if operation == "SMOOTH" else 1e6))
            if operation == "PUSH":
                direction = _vector(item.get("direction"), "direction", 3, low=-1e6, high=1e6)
                length = math.sqrt(sum(value * value for value in direction))
                if length < 1e-12:
                    raise invalid_argument("PUSH needs a nonzero explicit direction.")
                stroke["direction"] = tuple(value / length for value in direction)
            elif "direction" in item:
                raise invalid_argument("SMOOTH has no direction; it uses frozen edge-neighbor positions.")
        result.append(stroke)
    return result


def _weight(position: tuple, stroke: dict, mask: float) -> float:
    distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(position, stroke["center"], strict=True)))
    if distance >= stroke["radius"] or not mask:
        return 0.
    value = 1. - distance / stroke["radius"]
    if stroke["falloff"] == "CONSTANT":
        value = 1.
    elif stroke["falloff"] == "SMOOTH":
        value = value * value * (3. - 2. * value)
    return value * mask


def sculpt_values(positions: list[tuple], edges: list[tuple], indices: list[int], masks: list[float], strokes: list[dict], check=lambda: None) -> list[tuple]:
    """Pure frozen-neighbor brush kernel; only explicit nonzero-mask indices change."""
    if len(indices) * len(strokes) > MAX_TESTS:
        raise invalid_argument("Sculpt candidate tests exceed 500,000; narrow the scope/strokes.")
    neighbors = None
    if any(stroke["operation"] == "SMOOTH" for stroke in strokes):
        neighbors = [[] for _ in positions]
        for a, b in edges:
            neighbors[a].append(b)
            neighbors[b].append(a)
        if sum(len(neighbors[index]) for index in indices) * len(strokes) > MAX_ADJACENCY_TESTS:
            raise invalid_argument("Smoothing neighbor tests exceed their bounded budget.")
    result = list(positions)
    for stroke in strokes:
        check()
        frozen = list(result)
        for offset, (index, mask) in enumerate(zip(indices, masks, strict=True)):
            if offset % 128 == 0:
                check()
            weight = _weight(frozen[index], stroke, mask) * stroke["strength"]
            if not weight:
                continue
            if stroke["operation"] == "PUSH":
                direction = stroke["direction"]
            else:
                adjacent = neighbors[index]
                if not adjacent:
                    continue
                direction = tuple(sum(frozen[other][axis] for other in adjacent) / len(adjacent) - frozen[index][axis] for axis in range(3))
            result[index] = _vector(tuple(value + weight * delta for value, delta in zip(frozen[index], direction, strict=True)), "sculpt result", 3)
    check()
    return result


def paint_values(colors: list[tuple], entry_vertices: list[int], positions: list[tuple], indices: list[int], masks: list[float], strokes: list[dict], check=lambda: None) -> list[tuple]:
    mask = dict(zip(indices, masks, strict=True))
    entries = [(entry, vertex) for entry, vertex in enumerate(entry_vertices) if vertex in mask]
    if len(entries) * len(strokes) > MAX_TESTS:
        raise invalid_argument("Color corner/stroke candidate tests exceed 500,000.")
    result = list(colors)
    for stroke in strokes:
        check()
        for offset, (entry, vertex) in enumerate(entries):
            if offset % 128 == 0:
                check()
            weight = _weight(positions[vertex], stroke, mask[vertex]) * stroke["opacity"]
            if weight:
                result[entry] = tuple(before * (1. - weight) + after * weight for before, after in zip(result[entry], stroke["color"], strict=True))
    check()
    return result


def _space(obj: Any, positions: list[tuple], space: str):
    if space == "LOCAL":
        return positions, lambda result: result
    from mathutils import Vector
    matrix = obj.matrix_world.copy()
    try:
        inverse = matrix.inverted()
    except ValueError as exc:
        raise invalid_argument("WORLD brushes require an invertible object matrix.") from exc
    return ([_vector(tuple(matrix @ Vector(position)), "world coordinate", 3) for position in positions],
            lambda result: [_vector(tuple(inverse @ Vector(position)), "local sculpt result", 3) for position in result])


def _publication(context: Any, bpy: Any, obj: Any, before: dict, before_positions: list[tuple], *, method: str, object_name: str, exclude_color=None, deleting=False, color_ui=True) -> None:
    _gate(context, method, deleting=deleting)
    # Retain the preliminary live target check, then resolve one coherent final
    # grant set. Every authoritative native comparison follows these callbacks.
    _target(context, object_name, method)
    context.require(Permission.EDIT_MESH, *([Permission.DELETE_OBJECTS] if deleting else []))
    check_final_mutation(context, method)
    try:
        current = _target_read(bpy, object_name)
        stale = current != obj or _preservation(bpy, obj, exclude_color=exclude_color, color_ui=color_ui) != before or not _same_float_rows(_positions(obj), before_positions)
    except ReferenceError as exc:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Native surface ID disappeared before publication; reinspect.") from exc
    if stale:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Surface/context/preservation scope changed before publication; reinspect.")
    check_final_mutation(context, method)


def _named_consumers(obj: Any, name: str, acknowledged: bool) -> dict:
    """Bounded direct material paths; name-based transitive consumers stay explicit."""
    visited, pending, consumers = set(), [], []
    for slot in obj.material_slots:
        material = slot.material
        if material is not None and getattr(material, "node_tree", None) is not None:
            pending.append((material.node_tree, material.name))
    nodes = 0
    while pending:
        tree, label = pending.pop()
        identity = _identity(tree)
        if identity in visited:
            continue
        visited.add(identity)
        nodes += len(tree.nodes)
        if len(visited) > 32 or nodes > 1024:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Named-consumer inspection exceeds 32 shader trees/1024 nodes; narrow material dependencies first.")
        for node in tree.nodes:
            if ((node.bl_idname == "ShaderNodeVertexColor" and node.layer_name == name)
                    or (node.bl_idname == "ShaderNodeAttribute" and node.attribute_name == name)):
                consumers.append({"material_path": label, "node": node.name, "node_type": node.bl_idname})
            elif node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None:
                pending.append((node.node_tree, label + "/" + node.name))
    evidence = {"direct_material_consumers": consumers, "transitive_geometry_nodes_or_dynamic_consumers_possible": True,
                "node_trees_deduplicated": True, "shared_tree_material_paths_may_be_omitted": True,
                "named_consumers_rewritten": False, "acknowledged": acknowledged}
    if not acknowledged:
        raise invalid_argument("Renaming/removing attributes can change named material/Geometry Nodes consumers; acknowledge_named_consumers=true is required.",
                               named_consumer_evidence=evidence)
    return evidence


def _failure(exc: Exception, object_name: str, started: bool, **extra):
    LOGGER.exception("Surface publication failed; retain truthful checkpoint recovery evidence")
    return BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                       "Surface edit did not complete; inspect affected mesh and checkpoint before retrying.",
                       {"execution_started": started, "affected_object": object_name, "possible_mutation": started,
                        "rollback_verified": False, "verification_required": True, **extra})


def sculpt_brush(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "vertex_indices", "mask_weights", "strokes", "space"})
    strokes = _strokes(params.get("strokes"))
    bpy, obj = _target(context, params.get("object_name"), "mesh.sculpt_brush")
    indices, masks, space = _mask(params, obj)
    before_positions, before = _positions(obj), _preservation(bpy, obj)
    positions, to_local = _space(obj, before_positions, space)
    brushed = sculpt_values(positions, [tuple(edge.vertices) for edge in obj.data.edges], indices, masks, strokes, lambda: _gate(context, "mesh.sculpt_brush"))
    result = to_local(brushed)
    # Round to the native storage before comparing any protected components.
    expected = array("f", [component for position in result for component in position])
    allowed = {index for index, weight in zip(indices, masks, strict=True) if weight and brushed[index] != positions[index]}
    for index, position in enumerate(before_positions):
        if index not in allowed:
            expected[index * 3:index * 3 + 3] = array("f", position)
    _publication(context, bpy, obj, before, before_positions, method="mesh.sculpt_brush", object_name=params["object_name"])
    started = False
    try:
        started = True
        obj.data.vertices.foreach_set("co", expected)
        check_final_mutation(context, "mesh.sculpt_brush")
        obj.data.update()
        _gate(context, "mesh.sculpt_brush")
        actual = array("f", [component for position in _positions(obj) for component in position])
        if actual.tobytes() != expected.tobytes() or _preservation(bpy, obj) != before:
            raise RuntimeError("Sculpt coordinates or protected topology/attributes/context differ from expected")
    except Exception as exc:
        raise _failure(exc, params["object_name"], started, intended_vertices=indices[:64]) from exc
    changed = [index for index in indices if tuple(expected[index * 3:index * 3 + 3]) != before_positions[index]]
    return {"object": obj.name, "space": space, "changed_vertices": len(changed), "vertices": changed[:64],
            "vertices_truncated": len(changed) > 64, "complete_coordinate_readback_verified": True,
            "protected_vertices_verified": True, "topology_uv_materials_context_preserved": True,
            "before_coordinates_sha256_float32_le": _float_digest(component for position in before_positions for component in position),
            "after_coordinates_sha256_float32_le": _float_digest(expected), "verification_required": True,
            "scope": "Explicit base-mesh PUSH/frozen-neighbor SMOOTH, not viewport projection/multires/full sculpt acceptance."}


def color_create(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "attribute_name", "domain", "initial_color"})
    name = _name(params.get("attribute_name"), "attribute_name")
    domain = params.get("domain", "POINT")
    if not isinstance(domain, str) or domain not in {"POINT", "CORNER"}:
        raise invalid_argument("Color attribute domain must be POINT or CORNER.")
    color = _vector(params.get("initial_color", [0., 0., 0., 1.]), "initial_color", 4, low=0., high=1.)
    bpy, obj = _target(context, params.get("object_name"), "color_attribute.create")
    attrs = obj.data.color_attributes
    if obj.data.attributes.get(name) is not None or len(attrs) >= MAX_ATTRIBUTES:
        raise invalid_argument("Attribute name exists or the 16-color-attribute limit is reached.")
    count = len(obj.data.vertices) if domain == "POINT" else len(obj.data.loops)
    if sum(len(layer.data) for layer in obj.data.uv_layers) + sum(len(attr.data) for attr in attrs) + count > MAX_ATTRIBUTE_ITEMS:
        raise invalid_argument("New color attribute would exceed preservation/attribute budgets.")
    before_positions, before = _positions(obj), _preservation(bpy, obj, color_ui=False)
    existing_count = len(attrs)
    old_active, old_render = attrs.active_color_index, attrs.render_color_index
    _publication(context, bpy, obj, before, before_positions, method="color_attribute.create", object_name=params["object_name"], color_ui=False)
    # Generic (non-color) attributes share this namespace too. They are not
    # represented by the color preservation projection.
    if obj.data.attributes.get(name) is not None or len(attrs) >= MAX_ATTRIBUTES:
        raise invalid_argument("Attribute destination changed before creation; no allocation attempted.")
    if (attrs.active_color_index, attrs.render_color_index) != (old_active, old_render):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Active/render color roles changed before creation; no allocation attempted.")
    check_final_mutation(context, "color_attribute.create")
    created, started, created_name = None, False, None
    created_identity, owned_colors = None, None
    # The first color may become active; otherwise the promised post-state is
    # the original roles. Cleanup never adopts a provider-selected newer role.
    owned_roles = (old_active, old_render) if existing_count else (0, 0)
    try:
        started = True
        created = attrs.new(name=name, type="FLOAT_COLOR", domain=domain)
        created_name = created.name
        created_identity = _identity(created)
        # Reviewed native POINT/CORNER FLOAT_COLOR allocation is opaque white.
        # Accept only that literal owned state; unknown initialization is retained.
        allocation_colors = [(1., 1., 1., 1.)] * count
        _frozen_attribute(obj.data, name, created_identity, domain, "FLOAT_COLOR", allocation_colors)
        owned_colors = allocation_colors
        check_final_mutation(context, "color_attribute.create")
        created.data.foreach_set("color", array("f", color) * count)
        initialized_colors = [tuple(array("f", color))] * count
        _frozen_attribute(obj.data, name, created_identity, domain, "FLOAT_COLOR", initialized_colors)
        owned_colors = initialized_colors
        if old_active >= 0:
            check_final_mutation(context, "color_attribute.create")
            attrs.active_color_index = old_active
        if old_render >= 0:
            check_final_mutation(context, "color_attribute.create")
            attrs.render_color_index = old_render
        check_final_mutation(context, "color_attribute.create")
        obj.data.update()
        _gate(context, "color_attribute.create")
        if created.name != name or not _same_float_rows(_colors(created), [tuple(array("f", color))] * count):
            raise RuntimeError("Created color attribute name/full color readback differs")
        if existing_count and (attrs.active_color_index, attrs.render_color_index) != (old_active, old_render):
            raise RuntimeError("Attribute creation changed existing active/render color roles")
        if not _same_float_rows(_positions(obj), before_positions) or _preservation(bpy, obj, exclude_color=created.name, color_ui=False) != before:
            raise RuntimeError("Attribute creation changed protected geometry/UV/material/context")
    except Exception as exc:
        cleanup_denied, cleanup_blocked, removed = False, None, False
        authority_lost = isinstance(exc, BridgeError) and exc.code in _AUTHORITY_ERRORS
        if created is not None:
            with suppress(ReferenceError):
                created_name = created.name
            try:
                if authority_lost:
                    raise exc
                if owned_colors is None or created_identity is None:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Owned allocation has no verified initialization state; retain it for inspection.")
                _publication(context, bpy, obj, before, before_positions, method="color_attribute.create", object_name=params["object_name"], exclude_color=created_name, deleting=True, color_ui=False)
                if attrs.get(created_name) != created:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Owned created attribute changed identity before cleanup.")
                _frozen_attribute(obj.data, name, created_identity, domain, "FLOAT_COLOR", owned_colors)
                if (attrs.active_color_index, attrs.render_color_index) != owned_roles:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Color roles changed before owned-allocation cleanup; retain the attribute.")
                check_final_mutation(context, "color_attribute.create")
                attrs.remove(created)
                removed = True
            except BridgeError as error:
                cleanup_denied = error.code == ErrorCode.PERMISSION_DENIED.value
                cleanup_blocked = error.code
            except Exception:
                LOGGER.exception("Owned color-attribute cleanup failed")
                cleanup_blocked = ErrorCode.OPERATION_FAILED.value
            if not removed:
                with suppress(ReferenceError):
                    created_name = created.name
        raise _failure(exc, params["object_name"], started, retained_attribute=created_name if created is not None and not removed else None,
                       retained_name_is_last_observed=created is not None and not removed,
                       cleanup_permission_denied=cleanup_denied, cleanup_blocked_code=cleanup_blocked,
                       cleanup_authority_loss_latched=authority_lost,
                       cleanup_last_verified_owned_state_available=owned_colors is not None) from exc
    return {"object": obj.name, "attribute_name": created.name, "domain": domain, "data_type": "FLOAT_COLOR",
            "entries": count, "complete_color_readback_verified": True, "protected_geometry_uv_materials_context_preserved": True,
            "first_attribute_may_become_active": not existing_count, "verification_required": True}


def color_inspect(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "attribute_name", "offset", "max_entries"})
    _bpy, obj = _target(context, params.get("object_name"), "color_attribute.inspect", modifying=False)
    attr = _attribute(obj.data, params.get("attribute_name"))
    identity, mesh_identity, object_identity = _identity(attr), _identity(obj.data), _identity(obj)
    frozen_name, frozen_domain, frozen_type, object_name = attr.name, attr.domain, attr.data_type, obj.name
    offset = int_param(params, "offset", 0, minimum=0, maximum=MAX_LOOPS)
    maximum = int_param(params, "max_entries", 32, minimum=1, maximum=64)
    values = _colors(attr)
    _gate(context, "color_attribute.inspect", modifying=False)
    try:
        _bpy, current = _target(context, object_name, "color_attribute.inspect", modifying=False)
        checked = _attribute(current.data, frozen_name)
        stale = (_identity(current) != object_identity or _identity(current.data) != mesh_identity
                 or _identity(checked) != identity or checked.domain != frozen_domain
                 or checked.data_type != frozen_type or not _same_float_rows(_colors(checked), values))
    except (BridgeError, ReferenceError) as exc:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Color inspection scope changed; request a fresh page/digest.", {"stale_evidence": True}) from exc
    if stale:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Color attribute changed during inspection; request a fresh page/digest.", {"stale_evidence": True})
    return {"object": object_name, "attribute_name": frozen_name, "domain": frozen_domain, "data_type": frozen_type,
            "entry_count": len(values), "offset": offset,
            "entries": [{"index": index, "color": list(values[index])} for index in range(offset, min(len(values), offset + maximum))],
            "truncated": offset + maximum < len(values), "next_offset": offset + maximum if offset + maximum < len(values) else None,
            "complete_colors_sha256_float32_le": _float_digest(component for color in values for component in color),
            "value_space": "Native scene-linear FLOAT_COLOR RGBA; no display/sRGB conversion or appearance certificate"}


def color_paint(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "attribute_name", "vertex_indices", "mask_weights", "strokes", "space"})
    strokes = _strokes(params.get("strokes"), color=True)
    bpy, obj = _target(context, params.get("object_name"), "color_attribute.paint")
    attr = _attribute(obj.data, params.get("attribute_name"))
    attribute_name = attr.name
    indices, masks, space = _mask(params, obj)
    before_positions, before = _positions(obj), _preservation(bpy, obj, exclude_color=attr.name)
    colors = _colors(attr)
    attribute_identity, domain, data_type = _identity(attr), attr.domain, attr.data_type
    positions, _to_local = _space(obj, before_positions, space)
    vertices = list(range(len(obj.data.vertices))) if attr.domain == "POINT" else [loop.vertex_index for loop in obj.data.loops]
    result = paint_values(colors, vertices, positions, indices, masks, strokes, lambda: _gate(context, "color_attribute.paint"))
    expected = array("f", [component for color in result for component in color])
    _publication(context, bpy, obj, before, before_positions, method="color_attribute.paint", object_name=params["object_name"], exclude_color=attribute_name)
    attr = _frozen_attribute(obj.data, params["attribute_name"], attribute_identity, domain, data_type, colors)
    check_final_mutation(context, "color_attribute.paint")
    started = False
    try:
        started = True
        attr.data.foreach_set("color", expected)
        check_final_mutation(context, "color_attribute.paint")
        obj.data.update()
        _gate(context, "color_attribute.paint")
        actual = array("f", [component for color in _colors(attr) for component in color])
        if actual.tobytes() != expected.tobytes() or not _same_float_rows(_positions(obj), before_positions) or _preservation(bpy, obj, exclude_color=attribute_name) != before:
            raise RuntimeError("Painted colors or protected geometry/attributes/context differ")
    except Exception as exc:
        raise _failure(exc, params["object_name"], started, attribute_name=attribute_name) from exc
    changed = sum(tuple(expected[index * 4:index * 4 + 4]) != color for index, color in enumerate(colors))
    return {"object": obj.name, "attribute_name": attr.name, "domain": attr.domain, "space": space,
            "changed_entries": changed, "complete_color_readback_verified": True,
            "protected_entries_verified": True, "geometry_uv_materials_context_preserved": True,
            "before_colors_sha256_float32_le": _float_digest(component for color in colors for component in color),
            "after_colors_sha256_float32_le": _float_digest(expected), "verification_required": True,
            "scope": "Linear FLOAT_COLOR RGBA MIX on explicit vertex-associated POINT/CORNER entries; no viewport projection or blend-mode expansion."}


def color_rename(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "attribute_name", "new_name", "acknowledge_named_consumers"})
    acknowledged = bool_param(params, "acknowledge_named_consumers", False)
    new_name = _name(params.get("new_name"), "new_name")
    bpy, obj = _target(context, params.get("object_name"), "color_attribute.rename")
    attr = _attribute(obj.data, params.get("attribute_name"))
    old_name = attr.name
    consumers = _named_consumers(obj, old_name, acknowledged)
    if obj.data.attributes.get(new_name) is not None:
        raise invalid_argument("New attribute name is occupied; no implicit rename/reuse.")
    before_positions, before = _positions(obj), _preservation(bpy, obj, exclude_color=old_name)
    colors = _colors(attr)
    attribute_identity, domain, data_type = _identity(attr), attr.domain, attr.data_type
    _publication(context, bpy, obj, before, before_positions, method="color_attribute.rename", object_name=params["object_name"], exclude_color=old_name)
    attr = _frozen_attribute(obj.data, old_name, attribute_identity, domain, data_type, colors)
    if obj.data.attributes.get(new_name) is not None:
        raise invalid_argument("Attribute destination changed before rename; no name changed.")
    check_final_mutation(context, "color_attribute.rename")
    try:
        attr.name = new_name
        _gate(context, "color_attribute.rename")
        if attr.name != new_name or not _same_float_rows(_colors(attr), colors) or not _same_float_rows(_positions(obj), before_positions) or _preservation(bpy, obj, exclude_color=new_name) != before:
            raise RuntimeError("Attribute rename/readback or protected fields differ")
    except Exception as exc:
        last_name = old_name
        with suppress(ReferenceError):
            last_name = attr.name
        raise _failure(exc, params["object_name"], True, last_observed_attribute_name=last_name) from exc
    return {"object": obj.name, "old_name": old_name, "attribute_name": new_name, "values_preserved": True,
            "named_consumer_evidence": consumers, "named_consumers_rewritten": False, "verification_required": True}


def color_remove(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "attribute_name", "confirm_remove", "acknowledge_named_consumers"})
    acknowledged = bool_param(params, "acknowledge_named_consumers", False)
    if not bool_param(params, "confirm_remove", False):
        raise invalid_argument("confirm_remove=true is required for explicit attribute data loss; named consumers are not rewritten.")
    _gate(context, "color_attribute.remove", deleting=True)
    bpy, obj = _target(context, params.get("object_name"), "color_attribute.remove")
    attr = _attribute(obj.data, params.get("attribute_name"))
    name = attr.name
    consumers = _named_consumers(obj, name, acknowledged)
    before_positions, before = _positions(obj), _preservation(bpy, obj, exclude_color=name, color_ui=False)
    colors = _colors(attr)
    attribute_identity, domain, data_type = _identity(attr), attr.domain, attr.data_type
    removed_digest = _float_digest(component for color in colors for component in color)
    _publication(context, bpy, obj, before, before_positions, method="color_attribute.remove", object_name=params["object_name"], exclude_color=name, deleting=True, color_ui=False)
    attr = _frozen_attribute(obj.data, name, attribute_identity, domain, data_type, colors)
    check_final_mutation(context, "color_attribute.remove")
    try:
        obj.data.color_attributes.remove(attr)
        _gate(context, "color_attribute.remove")
        if obj.data.attributes.get(name) is not None or not _same_float_rows(_positions(obj), before_positions) or _preservation(bpy, obj, color_ui=False) != before:
            raise RuntimeError("Color removal or protected fields differ")
    except Exception as exc:
        raise _failure(exc, params["object_name"], True, removed_attribute=name) from exc
    return {"object": obj.name, "removed_attribute": name, "removed_colors_sha256_float32_le": removed_digest,
            "named_consumers_rewritten": False, "named_consumer_evidence": consumers,
            "active_color_may_change": True, "verification_required": True}


TOOL_DATA = (
    ("mesh.sculpt_brush", sculpt_brush, (Permission.EDIT_MESH,), "Apply bounded explicit-mask PUSH/SMOOTH strokes to an unmodified local single-user base mesh."),
    ("color_attribute.create", color_create, (Permission.EDIT_MESH,), "Create a unique FLOAT_COLOR POINT/CORNER attribute with verified full initialization."),
    ("color_attribute.inspect", color_inspect, (Permission.INSPECT_SCENE,), "Inspect bounded color pages and complete raw FLOAT_COLOR digest."),
    ("color_attribute.paint", color_paint, (Permission.EDIT_MESH,), "Paint linear RGBA MIX strokes on explicit vertex-associated point/corner entries."),
    ("color_attribute.rename", color_rename, (Permission.EDIT_MESH,), "Rename an explicit color attribute without rewriting named consumers."),
    ("color_attribute.remove", color_remove, (Permission.EDIT_MESH, Permission.DELETE_OBJECTS), "Remove a color attribute only with explicit data-loss confirmation and deletion consent."),
)


def register_tools(registry: Any) -> None:
    for name, handler, permissions, description in TOOL_DATA:
        registry.register(name, handler, toolset="mesh", permissions=permissions,
                          modifies=name != "color_attribute.inspect", description=description)
