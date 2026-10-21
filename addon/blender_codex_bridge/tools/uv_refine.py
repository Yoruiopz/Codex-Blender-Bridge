"""Pinned, explicit-corner UV refinement without editor operators or hidden scope."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Mapping

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import float_param, int_param, reject_unknown_params
from . import uv_edit
from .mesh_slide import _assert_session, _snapshot

try:
    import bmesh
except ImportError:  # pragma: no cover
    bmesh = None

LOGGER = logging.getLogger(__name__)
BASE = {"object_name", "uv_layer", "selection_id"}
MAX_RELAX_CORNERS = 4096


def _gate(context: ToolContext, *, recovery=False):
    context.require(Permission.EDIT_MESH)
    if not recovery and context.check_cancelled:
        context.check_cancelled()
    flags = context.state.snapshot() if getattr(context, "state", None) else {}
    if not recovery and flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "UV refinement emergency-stopped.")
    if not recovery and flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "UV refinement is paused.")
    context.require(Permission.EDIT_MESH)


def _scope(context, params):
    _gate(context)
    obj, bm, layer, faces = uv_edit._scope(params, require_reference=True)
    for owner in (obj, obj.data):
        if not getattr(owner, "is_editable", True):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV refinement requires editable local object and mesh data.")
    return obj, bm, layer, faces, _snapshot(obj, bm)


def _uv(loop, layer):
    return uv_edit._pair(tuple(loop[layer].uv), "existing_uv")


def _face_safety(faces, layer, proposed):
    for face in faces:
        if len(face.loops) not in {3, 4}:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV refinement currently checks triangle/quad fan orientation.")
        old = [_uv(loop, layer) for loop in face.loops]
        new = [proposed.get((face.index, index), old[index]) for index in range(len(old))]
        for index in range(1, len(old)-1):
            def cross(points, index=index):
                return ((points[index][0]-points[0][0])*(points[index+1][1]-points[0][1])
                        - (points[index][1]-points[0][1])*(points[index+1][0]-points[0][0]))
            before, after = cross(old), cross(new)
            if abs(before) <= 1e-12 or before*after <= 0. or abs(after) < abs(before)*1e-4:
                raise invalid_argument("UV refinement would degenerate or invert an affected face fan.", face_index=face.index)


def _commit(context, obj, bm, layer, faces, before, proposed):
    lookup = {(face.index, index): loop for face in faces for index, loop in enumerate(face.loops)}
    for key, uv in proposed.items():
        if lookup[key][layer].pin_uv and _uv(lookup[key], layer) != uv:
            raise invalid_argument("A targeted pinned UV corner would move; revise the explicit scope or target.", face_index=key[0], corner_index=key[1])
    affected = [face for face in faces if any((face.index, index) in proposed for index in range(len(face.loops)))]
    _face_safety(affected, layer, proposed)
    ordinal = {(face.index, index): number for number, (face, index) in enumerate(
        (face, index) for face in bm.faces for index in range(len(face.loops)))}
    expected_uv = []
    for name, rows in before["uv"]:
        rows = list(rows)
        if name == layer.name:
            for key, value in proposed.items():
                _uv_before, pin, selected, edge_selected = rows[ordinal[key]]
                rows[ordinal[key]] = (value, pin, selected, edge_selected)
        expected_uv.append((name, rows))
    expected = {**before, "uv": expected_uv}
    originals = {key: _uv(lookup[key], layer) for key in proposed}
    written = []
    try:
        _gate(context)
        _assert_session(obj, bm, before["ownership"])
        if _snapshot(obj, bm) != before:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "UV source changed during planning; reinspect before retrying.")
        for index, (key, value) in enumerate(proposed.items()):
            if index % 64 == 0:
                _gate(context)
                _assert_session(obj, bm, before["ownership"])
            if lookup[key][layer].pin_uv and _uv(lookup[key], layer) != value:
                raise invalid_argument("A UV pin changed before application; reinspect before retrying.")
            written.append(key)
            lookup[key][layer].uv = value
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        _gate(context)
        _assert_session(obj, bm, before["ownership"])
        if _snapshot(obj, bm) != expected:
            raise RuntimeError("UV refinement or protected-state readback mismatch")
    except Exception as error:
        restored = False
        try:
            _gate(context, recovery=True)
            _assert_session(obj, bm, before["ownership"])
            for key in written:
                # Never overwrite an interleaved edit that replaced our output.
                current = _uv(lookup[key], layer)
                if current == originals[key]:
                    continue
                if current != proposed[key]:
                    raise RuntimeError("UV output was changed after application")
                lookup[key][layer].uv = originals[key]
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            restored = _snapshot(obj, bm) == before
        except Exception:
            LOGGER.exception("UV refinement restoration could not be verified")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
            "UV refinement did not complete; inspect local and native recovery evidence.",
            {"object": obj.name, "affected_objects": [obj.name], "uv_layer": layer.name,
             "execution_started": bool(written), "rollback_verified": restored,
             "possible_mutation": not restored, "verification_required": True}) from error
    return {"object": obj.name, "affected_objects": [obj.name], "uv_layer": layer.name,
        "target_corners": len(proposed), "changed_corners": sum(originals[key] != value for key, value in proposed.items()),
        "maximum_displacement_uv": max((math.dist(originals[key], value) for key, value in proposed.items()), default=0.),
        "pins_preserved": True, "other_layers_preserved": True, "geometry_preserved": True,
        "selection_changed": False, "active_layer_changed": False, "topology_changed": False,
        "verification_required": True, "appearance_verified": False}


def align(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, {*BASE, "corners", "axis", "value"})
    axis = params.get("axis")
    if not isinstance(axis, str) or axis not in {"U", "V"}:
        raise invalid_argument("UV alignment axis must be U or V.")
    value = float_param(params, "value", 0., minimum=-uv_edit.MAX_UV, maximum=uv_edit.MAX_UV)
    if params.get("corners") is None:
        raise invalid_argument("UV alignment requires explicit face/corner records.")
    obj, bm, layer, faces, before = _scope(context, params)
    proposed = {}
    for face, corner, loop in uv_edit._corners(params, faces):
        point = list(_uv(loop, layer))
        point[0 if axis == "U" else 1] = value
        proposed[(face.index, corner)] = uv_edit._pair(point, "aligned_uv")
    return {**_commit(context, obj, bm, layer, faces, before, proposed), "axis": axis, "value": value,
        "scope": "Explicit corners; pinned corners must already lie on the requested line. No UV-editor selection is inferred."}


def stitch(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, {*BASE, "pairs", "max_distance"})
    records = params.get("pairs")
    if not isinstance(records, list) or not 1 <= len(records) <= 2048:
        raise invalid_argument("UV stitch pairs must contain 1-2048 explicit source/target corner correspondences.")
    maximum = float_param(params, "max_distance", .25, minimum=1e-9, maximum=uv_edit.MAX_UV)
    obj, bm, layer, faces, before = _scope(context, params)
    proposed, sources, targets, distances = {}, set(), set(), []
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {"source", "target"}:
            raise invalid_argument("Each stitch pair requires exactly source and target corner records.")
        first = uv_edit._corners({"corners": [record["source"]]}, faces)[0]
        second = uv_edit._corners({"corners": [record["target"]]}, faces)[0]
        source_key, target_key = (first[0].index, first[1]), (second[0].index, second[1])
        if source_key == target_key or target_key in targets or first[2].vert != second[2].vert:
            raise invalid_argument("Stitch targets must be unique, distinct corners of the same mesh vertex.")
        source, target = _uv(first[2], layer), _uv(second[2], layer)
        distance = math.dist(source, target)
        if distance > maximum:
            raise invalid_argument("UV stitch correspondence exceeds max_distance.", distance_uv=distance)
        sources.add(source_key)
        targets.add(target_key)
        distances.append(distance)
        proposed[target_key] = source
    if sources & targets:
        raise invalid_argument("Stitch anchor corners must remain outside the moving target scope.")
    return {**_commit(context, obj, bm, layer, faces, before, proposed), "stitched_pairs": len(records),
        "maximum_gap_before_uv": max(distances), "maximum_gap_after_uv": 0.,
        "scope": "Copy explicit same-vertex corner coordinates to targets; anchors/pins/mesh topology stay fixed. Complete island merging is not inferred."}


def _island_nodes(faces, layer):
    chosen = {face.index: face for face in faces}
    corners = {(face.index, index): loop for face in faces for index, loop in enumerate(face.loops)}
    parent = {key: key for key in corners}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    def union(first, second):
        parent[find(second)] = find(first)
    boundary, adjacency = set(), defaultdict(set)
    for face in faces:
        for index, loop in enumerate(face.loops):
            following = (index+1) % len(face.loops)
            endpoints = {loop.vert.index: (index, loop), face.loops[following].vert.index: (following, face.loops[following])}
            edge = loop.edge
            if len(edge.link_faces) > 2:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV relaxation does not infer connectivity across nonmanifold edges.")
            neighbor = next((other for other in edge.link_faces if other != face), None)
            matched = None
            if neighbor is not None:
                matched = {corner.vert.index: (corner_index, corner) for corner_index, corner in enumerate(neighbor.loops)
                           if corner.vert.index in endpoints}
                if len(matched) != 2 or any(_uv(endpoints[vertex][1], layer) != _uv(matched[vertex][1], layer) for vertex in endpoints):
                    matched = None
            if matched is None:
                boundary.update(((face.index, index), (face.index, following)))
            else:
                if neighbor.index not in chosen:
                    raise invalid_argument("Relaxation requires the complete current UV island; a continuous neighboring face is outside face_indices.", face_index=neighbor.index)
                adjacency[face.index].add(neighbor.index)
                for vertex, (corner_index, _corner) in endpoints.items():
                    union((face.index, corner_index), (neighbor.index, matched[vertex][0]))
    pending, visited = [faces[0].index], set()
    while pending:
        face_index = pending.pop()
        if face_index not in visited:
            visited.add(face_index)
            pending.extend(adjacency[face_index] - visited)
    if visited != set(chosen):
        raise invalid_argument("Relax exactly one complete connected UV island per call.")
    nodes, fixed, edges = {}, set(), defaultdict(set)
    for key, loop in corners.items():
        root = find(key)
        nodes[root] = _uv(loop, layer)
        if loop[layer].pin_uv or key in boundary:
            fixed.add(root)
    for face in faces:
        for index in range(len(face.loops)):
            first, second = find((face.index, index)), find((face.index, (index+1) % len(face.loops)))
            if first != second:
                edges[first].add(second)
                edges[second].add(first)
    return corners, {key: find(key) for key in corners}, nodes, fixed, edges


def relax(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, {*BASE, "face_indices", "iterations", "strength", "max_displacement"})
    indices = params.get("face_indices")
    if not isinstance(indices, list) or not 1 <= len(indices) <= MAX_RELAX_CORNERS or any(
            isinstance(index, bool) or not isinstance(index, int) or index < 0 for index in indices) or len(set(indices)) != len(indices):
        raise invalid_argument("face_indices must be distinct nonnegative indices for one complete UV island.")
    iterations = int_param(params, "iterations", 10, minimum=1, maximum=50)
    strength = float_param(params, "strength", .5, minimum=1e-6, maximum=.5)
    maximum = float_param(params, "max_displacement", .25, minimum=1e-9, maximum=1000.)
    obj, bm, layer, reference_faces, before = _scope(context, params)
    lookup = {face.index: face for face in reference_faces}
    if not set(indices).issubset(lookup):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Relaxation faces lie outside the fresh face-selection reference.")
    faces = [lookup[index] for index in indices]
    if sum(len(face.loops) for face in faces) > MAX_RELAX_CORNERS:
        raise invalid_argument("UV relaxation is bounded to 4096 island corners.")
    _corners, roots, original, fixed, edges = _island_nodes(faces, layer)
    if len(original) * iterations > 200_000:
        raise invalid_argument("UV relaxation exceeds its 200000 node-iteration budget.")
    values = dict(original)
    def energy(points):
        return sum(math.dist(points[key], points[other])**2 for key, neighbors in edges.items() for other in neighbors) * .5
    for _iteration in range(iterations):
        _gate(context)
        result = dict(values)
        for key, neighbors in edges.items():
            if key in fixed or not neighbors:
                continue
            average = [sum(values[other][axis] for other in neighbors)/len(neighbors) for axis in range(2)]
            result[key] = uv_edit._pair([values[key][axis] + strength*(average[axis]-values[key][axis]) for axis in range(2)], "relaxed_uv")
            if math.dist(result[key], original[key]) > maximum:
                raise invalid_argument("UV relaxation exceeds max_displacement; reduce iterations/strength or revise the bound.")
        _face_safety(faces, layer, {key: result[root] for key, root in roots.items()})
        values = result
    proposed = {key: values[root] for key, root in roots.items() if root not in fixed}
    committed = _commit(context, obj, bm, layer, reference_faces, before, proposed)
    return {**committed, "iterations": iterations, "strength": strength, "island_faces": indices,
        "fixed_uv_nodes": len(fixed), "movable_uv_nodes": len(original)-len(fixed),
        "edge_energy_before": energy(original), "edge_energy_after": energy(values),
        "scope": "One complete exactly continuous base-mesh UV island; boundaries and pinned UV nodes fixed. Uniform Laplacian smoothing, not conformal unwrap, texel-density or artistic-quality acceptance."}


def register_tools(registry: ToolRegistry) -> None:
    for name, handler, description in (
        ("uv.align", align, "Align explicit UV corners to an exact U/V line, preserving pins, other layers and face orientation."),
        ("uv.stitch", stitch, "Stitch explicit same-mesh-vertex corner pairs to fixed anchors within a UV distance bound; no topology welding."),
        ("uv.relax", relax, "Relax one explicitly enumerated complete UV island with fixed boundaries/pins, bounded iterations and displacement, preserving other layers/context."),
    ):
        registry.register(name, handler, toolset="uv", modifies=True,
            permissions=(Permission.EDIT_MESH,), description=description)
