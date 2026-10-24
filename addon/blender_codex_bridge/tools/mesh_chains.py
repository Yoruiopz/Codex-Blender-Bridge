"""Previewed open-chain bridges with explicit correspondence and retained evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import uuid
from collections import defaultdict
from collections.abc import Mapping
from itertools import pairwise
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import clear_selection_references, validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry, check_final_mutation
from ..utils import int_param, reject_unknown_params
from .interaction import _active_edit_mesh
from .mesh import _id_name, _mesh_counts
from .mesh_repair import _adjacent_faces
from .mesh_slide import _cross, _dot, _point, _sub
from .mesh_surface import _capture, _check_object, _context, _proof_size, _target_scope

try:
    import bmesh
except ImportError:  # pragma: no cover
    bmesh = None

LOGGER = logging.getLogger(__name__)
METHOD = "mesh.bridge_chains"
MAX_VERTICES = 64
MAX_PROOF_VALUES = 2_000_000
SESSION_NONCE = uuid.uuid4().hex
PARAMS = {"object_name", "selection_id", "rail_a_start", "rail_a_end", "rail_b_start", "rail_b_end", "material_index"}


def _token(owner: Any) -> tuple[int, int | None]:
    return (int(owner.as_pointer()) if hasattr(owner, "as_pointer") else id(owner),
            getattr(owner, "session_uid", None))


def _same(first: Any, second: Any) -> bool:
    # Python equality merges bool/int and +0/-0. Protected authored values do not.
    return json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(second, sort_keys=True, allow_nan=False)


def _state(obj: Any, bm: Any) -> dict:
    state = _capture(obj, bm)
    state["selection_history"] = [(type(item).__name__, item.index) for item in bm.select_history]
    state["active_face"] = bm.faces.active.index if bm.faces.active is not None else None
    state["select_mode"] = sorted(bm.select_mode)
    state["uv_clone_roles"] = [(layer.name, bool(getattr(layer, "active_clone", False))) for layer in obj.data.uv_layers]
    return state


def _old_projection(state: dict, before: dict) -> dict:
    """Discard only appended native topology/custom values; keep every old value."""
    result = copy.deepcopy(state)
    base, original = result["base"], before["base"]
    for label in ("vertices", "edges", "faces"):
        base[label] = base[label][:len(original[label])]
    corners = sum(len(face[0]) for face in original["faces"])
    base["uv"] = [(name, values[:corners]) for name, values in base["uv"]]
    if base["uv_global_selection"] is not None:
        base["uv_global_selection"]["faces"] = base["uv_global_selection"]["faces"][:len(original["faces"])]
        base["uv_global_selection"]["corners"] = base["uv_global_selection"]["corners"][:len(original["faces"])]
    if len(result["custom_data"]) != len(before["custom_data"]):
        return result
    result["custom_data"] = [(domain, family, name, active, values[:len(old[4])])
        for (domain, family, name, active, values), old in zip(result["custom_data"], before["custom_data"], strict=True)]
    return result


def _rails(edges: list[Any], endpoints: tuple[int, int, int, int]) -> list[list[Any]]:
    if not 2 <= len(edges) <= 2 * (MAX_VERTICES - 1):
        raise invalid_argument("Bridge exactly two open chains of 2-64 vertices each.")
    adjacency: dict[Any, list[Any]] = defaultdict(list)
    for edge in edges:
        if edge.hide or any(vertex.hide for vertex in edge.verts) or len(edge.link_faces) > 1:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Chain edges must be visible boundary or wire edges.")
        for vertex in edge.verts:
            adjacency[vertex].append(edge)
    if any(len(incident) not in {1, 2} for incident in adjacency.values()):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Open bridge chains cannot branch.")
    by_index = {vertex.index: vertex for vertex in adjacency}
    if (len(set(endpoints)) != 4 or any(index not in by_index or len(adjacency[by_index[index]]) != 1 for index in endpoints)):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Supply the four distinct endpoints of the two referenced open chains.")
    remaining, rails = set(edges), []
    for start, end in (endpoints[:2], endpoints[2:]):
        vertex, rail, previous = by_index[start], [], None
        while True:
            rail.append(vertex)
            if len(rail) > MAX_VERTICES:
                raise invalid_argument("Each bridge chain is limited to 64 vertices.")
            onward = [edge for edge in adjacency[vertex] if edge is not previous]
            if not onward:
                break
            edge = onward[0]
            if edge not in remaining:
                raise BridgeError(ErrorCode.INVALID_SELECTION, "The endpoints do not describe disjoint simple open chains.")
            remaining.remove(edge)
            previous, vertex = edge, next(item for item in edge.verts if item != vertex)
        if rail[-1].index != end:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Each explicit end must terminate its corresponding start chain.")
        rails.append(rail)
    if remaining or len(rails[0]) != len(rails[1]) or set(rails[0]) & set(rails[1]):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Reference exactly two disjoint open chains with equal vertex counts.")
    return rails


def _candidate(bm: Any, rails: list[list[Any]]) -> list[list[int]]:
    first, second = rails
    connections = {frozenset((a.index, b.index)) for a, b in zip(first, second, strict=True)}
    if any(frozenset(vertex.index for vertex in edge.verts) in connections for edge in bm.edges):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "A proposed connecting edge already exists; this bridge never merges or reuses connections.")
    existing = {frozenset(vertex.index for vertex in face.verts) for face in bm.faces}
    faces = []
    for index in range(len(first)-1):
        vertices = (first[index], first[index+1], second[index+1], second[index])
        indices = [vertex.index for vertex in vertices]
        if frozenset(indices) in existing:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "A proposed bridge face already exists.")
        points = [_point(vertex.co) for vertex in vertices]
        normals = [_cross(_sub(points[1], points[0]), _sub(points[2], points[0])),
                   _cross(_sub(points[2], points[0]), _sub(points[3], points[0]))]
        if any(_dot(normal, normal) <= 1e-20 for normal in normals) or _dot(*normals) <= 0:
            raise invalid_argument("Explicit chain correspondence creates a degenerate or folded quad fan; choose different endpoints.")
        for a, b in ((vertices[0], vertices[1]), (vertices[2], vertices[3])):
            edge = next(edge for edge in a.link_edges if b in edge.verts)
            for face in edge.link_faces:
                old = list(face.verts)
                if any(old[i] == a and old[(i+1) % len(old)] == b for i in range(len(old))):
                    raise invalid_argument("Explicit endpoints give inconsistent boundary winding; reverse both rail directions explicitly.")
        faces.append(indices)
    return faces


def _vertex_stars(rails: list[list[Any]]) -> None:
    """Admit ordinary boundary face fans or unbranched wire vertices only."""
    vertices = [vertex for rail in rails for vertex in rail]
    selected_pairs = {frozenset((first.index, second.index)) for rail in rails for first, second in pairwise(rail)}
    _adjacent_faces(vertices)
    for vertex in vertices:
        edges, faces = list(vertex.link_edges), set(vertex.link_faces)
        if any(edge.hide or any(endpoint.hide for endpoint in edge.verts) for edge in edges):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Reveal the complete affected chain-vertex star before bridging.")
        if not faces:
            if (len(edges) > 2 or any(edge.link_faces for edge in edges)
                    or any(frozenset(endpoint.index for endpoint in edge.verts) not in selected_pairs for edge in edges)):
                raise BridgeError(ErrorCode.INVALID_SELECTION, "Wire chains must be complete, without branches, unselected extensions or incident surface fans.")
            continue
        if any(len(edge.link_faces) not in {1, 2} for edge in edges) or sum(len(edge.link_faces) == 1 for edge in edges) != 2:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Affected surface vertices require an ordinary manifold boundary fan without wire attachments.")
        adjacent = {face: set() for face in faces}
        for edge in edges:
            for face in edge.link_faces:
                adjacent[face].update(other for other in edge.link_faces if other != face)
        reached, pending = set(), [next(iter(faces))]
        while pending:
            face = pending.pop()
            if face not in reached:
                reached.add(face)
                pending.extend(adjacent[face] - reached)
        if reached != faces:
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Affected boundary vertices cannot contain disconnected or bow-tie face fans.")


def _prepare(params: Mapping) -> dict:
    name = _id_name(params.get("object_name"), "object_name")
    selection = _id_name(params.get("selection_id"), "selection_id")
    endpoints = tuple(int_param(params, label, -1, minimum=0, maximum=19_999)
        for label in ("rail_a_start", "rail_a_end", "rail_b_start", "rail_b_end"))
    material = int_param(params, "material_index", 0, minimum=0, maximum=255)
    bpy, obj, bm, _sequences = _active_edit_mesh(name)
    _check_object(obj, target=True)
    _target_scope(bpy, obj)
    reference = validate_selection_reference(selection, obj, bm)
    indices = list(reference["edges"])
    if len(set(indices)) != len(indices) or any(type(index) is not int or not 0 <= index < len(bm.edges) for index in indices):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "The referenced edge scope is invalid.")
    edges = [bm.edges[index] for index in indices]
    rails = _rails(edges, endpoints)
    _vertex_stars(rails)
    if material >= max(1, len(obj.data.materials)):
        raise invalid_argument("material_index must address an existing slot, or zero with no slots.")
    faces = _candidate(bm, rails)
    before = _state(obj, bm)
    # Conservative domain-work estimate includes seven complete captures per
    # material-bearing face, appended custom-data values, projection copies and
    # constant entry/final checks. Checkpoint guards add independently bounded
    # captures; this is not a runtime, memory or native-stall guarantee.
    growth = len(rails[0]) + len(faces)
    for domain, _family, _name, _active, _values in before["custom_data"]:
        growth += {"VERT": 0, "EDGE": len(rails[0]), "FACE": len(faces), "CORNER": 4*len(faces)}[domain]
    if 8 * (_proof_size(before) + growth) * (10*len(faces)+24) > MAX_PROOF_VALUES:
        raise invalid_argument("Repeated chain preservation proof exceeds 2000000 values; narrow the mesh or chain scope.")
    before_context = _context(bpy)
    counts = _mesh_counts(bm)
    expected = {"vertices": counts["vertices"], "edges": counts["edges"]+len(rails[0]), "faces": counts["faces"]+len(faces)}
    if sum(expected.values()) > 20_000:
        raise invalid_argument("The bridge requires at most 20000 output mesh elements.")
    identity = (_token(obj), _token(obj.data), _token(bpy.context.scene))
    fingerprint = hashlib.sha256(json.dumps({"session": SESSION_NONCE, "identity": identity,
        "state": before, "context": before_context, "selection_id": selection, "edge_indices": indices,
        "endpoints": endpoints, "material_index": material, "faces": faces}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {"bpy": bpy, "obj": obj, "bm": bm, "before": before, "context": before_context,
        "identity": identity, "handles": tuple(tuple(sequence) for sequence in (bm.verts, bm.edges, bm.faces)),
        "material": material, "faces": faces, "rails": [[vertex.index for vertex in rail] for rail in rails],
        "preview": {"object": obj.name, "fingerprint": fingerprint, "rail_vertex_indices": [[v.index for v in rail] for rail in rails],
            "planned_faces": faces, "mesh_counts_before": counts, "expected_counts_after": expected,
            "topology_delta": {"vertices": 0, "edges": len(rails[0]), "faces": len(faces)},
            "material_index": material, "new_face_uv_policy": "ZERO_INITIALIZED_UNPINNED",
            "limitations": "Explicit equal open chains only; no merge, unequal/multi-chain pairing, automatic winding/correspondence, evaluated mesh, collision or whole-project preservation claim."}}


class _Guard:
    def __init__(self, context: ToolContext, plan: dict):
        self.context, self.plan, self.expected = context, plan, plan["before"]
        self.handles = plan["handles"]
        self.created: list[Any] = []
        self.attempted = False
        self.normal_calls_started = self.normal_calls_returned = 0
        self.mesh_updates_started = self.mesh_updates_returned = 0
        self.verified_syncs = self.synced_face_count = 0

    def __call__(self) -> None:
        callback = getattr(self.context, "check_cancelled", None)
        if callback is not None:
            callback()
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.prepare(METHOD, self.context)
        self.context.require(Permission.EDIT_MESH)
        self.check_after_read()

    def check_after_read(self) -> None:
        plan, bm, obj = self.plan, self.plan["bm"], self.plan["obj"]
        bpy, current, live, _sequences = _active_edit_mesh(obj.name)
        if (not bm.is_valid or current != obj or (_token(obj), _token(obj.data), _token(bpy.context.scene)) != plan["identity"]
                or _context(bpy) != plan["context"]
                or any(tuple(sequence) != saved for sequence, saved in zip((live.verts, live.edges, live.faces), self.handles, strict=True))):
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The retained chain Edit session, identities or context changed.")
        _check_object(obj, target=True)
        _target_scope(bpy, obj)
        if not _same(_state(obj, bm), self.expected):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Protected or published chain state changed; reinspect before another write.")
        check_final_mutation(self.context, METHOD)

    def publish_face(self, face: Any) -> None:
        plan, bm = self.plan, self.plan["bm"]
        for sequence in (bm.verts, bm.edges, bm.faces):
            sequence.ensure_lookup_table()
            sequence.index_update()
        created = [*self.created, face]
        old_counts = plan["preview"]["mesh_counts_before"]
        fresh_edges = list(bm.edges)[len(self.handles[1]):]
        pairs = {frozenset((plan["rails"][0][i], plan["rails"][1][i])) for i in range(len(created)+1)}
        if (len(bm.verts) != old_counts["vertices"] or len(bm.edges) != old_counts["edges"]+len(created)+1
                or len(bm.faces) != old_counts["faces"]+len(created)
                or tuple(bm.faces)[old_counts["faces"]:] != tuple(created)
                or any(tuple(sequence)[:len(saved)] != saved for sequence, saved in zip((bm.verts, bm.edges, bm.faces), self.handles, strict=True))
                or {frozenset(vertex.index for vertex in edge.verts) for edge in list(bm.edges)[old_counts["edges"]:]} != pairs
                or [vertex.index for vertex in face.verts] != plan["faces"][len(self.created)]
                or any(edge.select or edge.hide or edge.seam or not edge.smooth for edge in fresh_edges)
                or face.select or face.hide or face.smooth or face.material_index != 0
                or not math.isfinite(face.calc_area()) or face.calc_area() <= 0
                or any(tuple(loop[layer].uv) != (0., 0.) or loop[layer].pin_uv for loop in face.loops for layer in bm.loops.layers.uv.values())):
            raise RuntimeError("Native chain allocation differs from the predicted append-only topology/face defaults")
        state = _state(plan["obj"], bm)
        global_uv = state["base"]["uv_global_selection"]
        if global_uv is not None:
            if global_uv["faces"][-1] or any(a or b for a, b in global_uv["corners"][-1]):
                raise RuntimeError("New native global UV selection flags are not deselected")
        elif any(bool(getattr(loop[layer], "select", False)) or bool(getattr(loop[layer], "select_edge", False))
                for loop in face.loops for layer in bm.loops.layers.uv.values()):
            raise RuntimeError("New native UV-layer selection flags are not deselected")
        if not _same(_old_projection(state, self.expected), self.expected):
            raise RuntimeError("Native chain allocation changed original or previously published mesh data")
        # Only freshly allocated native custom-data defaults enter this receipt.
        # All pre-existing data is independently equal to the frozen pre-state.
        self.expected, self.created = state, created
        self.handles = tuple(tuple(sequence) for sequence in (bm.verts, bm.edges, bm.faces))
        check_final_mutation(self.context, METHOD)

    def sync_verified_face(self) -> None:
        """Publish derived tessellation before a later allocation can fail.

        There is no failure-path repair. Every native interval has its own live
        authority/CAS proof and pure final gate; loss of authority stops here.
        """
        normal_update = self.plan["bm"].normal_update
        mesh, update_edit_mesh = self.plan["obj"].data, bmesh.update_edit_mesh
        self()
        check_final_mutation(self.context, METHOD)
        self.normal_calls_started += 1
        normal_update()
        self.normal_calls_returned += 1
        self()
        check_final_mutation(self.context, METHOD)
        self.mesh_updates_started += 1
        update_edit_mesh(mesh, loop_triangles=True, destructive=True)
        self.mesh_updates_returned += 1
        self()
        self.verified_syncs += 1
        self.synced_face_count = len(self.created)

    def sync_receipt(self, *, current_topology_verified: bool) -> dict:
        # Plain retained counters only: safe even after native RNA invalidation.
        return {"normal_update_calls_started": self.normal_calls_started,
            "normal_update_calls_returned": self.normal_calls_returned,
            "edit_mesh_update_calls_started": self.mesh_updates_started,
            "edit_mesh_update_calls_returned": self.mesh_updates_returned,
            "verified_syncs": self.verified_syncs, "last_verified_face_count": self.synced_face_count,
            "current_topology_sync_verified": current_topology_verified}


def _factory(context: ToolContext, params: Mapping) -> _Guard:
    reject_unknown_params(params, PARAMS | {"expected_fingerprint"})
    plan = _prepare(params)  # Static capture only: providers run in the returned guard.
    if params.get("expected_fingerprint") != plan["preview"]["fingerprint"]:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "An exact current chain preview fingerprint is required.")
    return _Guard(context, plan)


def bridge_chains_preview(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, PARAMS)
    context.require(Permission.INSPECT_SCENE)
    if context.check_cancelled:
        context.check_cancelled()
    plan = _prepare(params)
    context.require(Permission.INSPECT_SCENE)
    # Providers cannot change the scene and have that change adopted as preview truth.
    if not _same(_state(plan["obj"], plan["bm"]), plan["before"]) or _context(plan["bpy"]) != plan["context"]:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Chain scope changed during preview; reinspect.")
    return {**plan["preview"], "changed": False, "verification_required": True}


def _new_face(bm: Any, vertices: list[Any]) -> Any:
    return bm.faces.new(vertices)


def _material_state(state: dict, face_index: int, material: int) -> dict:
    result = copy.deepcopy(state)
    row = list(result["base"]["faces"][face_index])
    row[3] = material
    result["base"]["faces"][face_index] = tuple(row)
    for domain, family, name, _active, values in result["custom_data"]:
        if domain == "FACE" and family == "int" and name == "material_index":
            values[face_index] = material
    return result


def bridge_chains(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, PARAMS | {"expected_fingerprint"})
    binding = getattr(context, "checkpoint_admission", None)
    guard = getattr(binding, "callback", None)
    if not isinstance(guard, _Guard) or guard.context is not context:
        guard = _factory(context, params)
    plan, bm, obj = guard.plan, guard.plan["bm"], guard.plan["obj"]
    try:
        for indices in plan["faces"]:
            guard()
            vertices = [bm.verts[index] for index in indices]
            check_final_mutation(context, METHOD)
            guard.attempted = True
            face = _new_face(bm, vertices)
            guard.publish_face(face)
            if plan["material"] != 0:
                guard()
                expected = _material_state(guard.expected, face.index, plan["material"])
                check_final_mutation(context, METHOD)
                face.material_index = plan["material"]
                if not _same(_state(obj, bm), expected):
                    raise RuntimeError("New chain face material assignment changed other protected values")
                guard.expected = expected
            guard.sync_verified_face()
        guard()
        clear_selection_references(plan["preview"]["object"])
    except Exception as error:
        LOGGER.exception("Open-chain bridge failed; retaining partial topology for explicit recovery")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Open-chain bridge did not complete; inspect partial effects and the Edit-session checkpoint.",
            {"object": plan["preview"]["object"], "affected_objects": [plan["preview"]["object"]], "execution_started": guard.attempted,
             "possible_mutation": guard.attempted, "rollback_verified": False,
             "created_faces_verified": len(guard.created), "created_faces_count_complete": not guard.attempted,
             "derived_cache_sync": guard.sync_receipt(current_topology_verified=False),
             "verification_required": True,
             "recovery": "Explicit confirmed native Edit-session checkpoint recovery; no implicit topology deletion.",
             "selection_reference_invalidated": guard.attempted}) from error
    return {**plan["preview"], "changed": True, "affected_objects": [plan["preview"]["object"]],
        "created_faces": len(guard.created), "mesh_counts_after": _mesh_counts(bm),
        "derived_cache_sync": guard.sync_receipt(current_topology_verified=True),
        "topology_changed": True, "selection_changed": False, "selection_reference_invalidated": True,
        "preservation": {"original_mesh_custom_data": True, "original_uvs_pins_materials_weights": True, "context": True},
        "verification": {"planned_topology": True, "original_data_preserved": True, "new_face_uvs_zero_unpinned": True},
        "verification_required": True, "user_goal_verified": False,
        "warnings": ["New faces need UV authoring. Compare wireframe/checker appearance; global crossings and artistic quality are not certified."]}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("mesh.bridge_chains_preview", bridge_chains_preview, toolset="mesh",
        permissions=(Permission.INSPECT_SCENE,), description="Preview two equal open chains with explicit endpoint correspondence and a complete bounded preservation fingerprint.")
    registry.register(METHOD, bridge_chains, toolset="mesh", modifies=True, batchable=False,
        permissions=(Permission.EDIT_MESH,), checkpoint_admission_factory=_factory,
        description="Bridge an exact current equal open-chain preview with quads, no vertex merge and verified original custom-data preservation.")
