"""Previewed, explicitly scoped base-surface fitting without inferred correspondence."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..mesh_geometry import MeshTriangle, intersection_analysis, normal
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..surface_geometry import closest_point, dot, inverse, sub, transform
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import float_param, reject_unknown_params
from ._mesh_safety import require_local_single_user_mesh, uses_edit_data
from ._object_safety import require_local_editable_id
from ._object_scope import MAX_DIRECT_USERS, MAX_VIEW_LAYERS, require_collection_scope
from .interaction import _active_edit_mesh
from .mesh import _id_name
from .mesh_repair import _adjacent_faces
from .mesh_slide import _face_checks, _gate, _identity, _point, _snapshot

try:
    import bmesh
except ImportError:  # pragma: no cover
    bmesh = None

LOGGER = logging.getLogger(__name__)
MAX_ELEMENTS, MAX_TRIANGLES, MAX_PAIRS = 20_000, 2048, 262_144
MAX_ATTRIBUTE_VALUES = 300_000
MAX_REVALIDATION_VALUES = 2_000_000
PARAMS = {"object_name", "selection_id", "source_object", "source_polygon_indices", "max_distance"}
LAYER_FAMILIES = {"bool", "float", "int", "string", "float_vector", "color", "float_color", "uv", "deform", "skin", "shape"}
BUILTIN_DATA = {"position": ("POINT", "FLOAT_VECTOR"), ".edge_verts": ("EDGE", "INT32_2D"),
    ".corner_vert": ("CORNER", "INT"), ".corner_edge": ("CORNER", "INT"),
    ".select_vert": ("POINT", "BOOLEAN"), ".select_edge": ("EDGE", "BOOLEAN"), ".select_poly": ("FACE", "BOOLEAN"),
    ".hide_vert": ("POINT", "BOOLEAN"), ".hide_edge": ("EDGE", "BOOLEAN"), ".hide_poly": ("FACE", "BOOLEAN"),
    ".edge_seam": ("EDGE", "BOOLEAN"), "uv_seam": ("EDGE", "BOOLEAN"), "sharp_edge": ("EDGE", "BOOLEAN"),
    "sharp_face": ("FACE", "BOOLEAN"), "material_index": ("FACE", "INT")}
BUILTIN_FLAGS = set(BUILTIN_DATA)
GLOBAL_UV_ATTRIBUTES = {".uv_select_vert": ("CORNER", "BOOLEAN"), ".uv_select_edge": ("CORNER", "BOOLEAN"),
                        ".uv_select_face": ("FACE", "BOOLEAN")}


def _indices(raw, total, label, maximum=256):
    if (not isinstance(raw, list) or not 1 <= len(raw) <= maximum
            or any(type(value) is not int or not 0 <= value < total for value in raw)
            or len(set(raw)) != len(raw)):
        raise invalid_argument(f"{label} needs 1-{maximum} distinct existing indices.")
    return sorted(raw)


def _value(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise invalid_argument("Protected mesh attributes must be finite.")
        return value
    return tuple(_value(item) for item in value)


def _layers(bm):
    result, count = [], 0
    domains: tuple[tuple[str, Any], ...] = (("VERT", bm.verts), ("EDGE", bm.edges), ("FACE", bm.faces),
                              ("CORNER", [loop for face in bm.faces for loop in face.loops]))
    for domain, sequence in domains:
        access = bm.loops.layers if domain == "CORNER" else sequence.layers
        for family in dir(access):
            if family.startswith("_"):
                continue
            collection = getattr(access, family)
            if not hasattr(collection, "values"):
                continue
            layers = list(collection.values())
            if layers and family not in LAYER_FAMILIES:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, f"Protected {domain} {family} layers are unsupported.")
            active = getattr(collection, "active", None)
            for layer in layers:
                count += len(sequence)
                if count > MAX_ATTRIBUTE_VALUES:
                    raise invalid_argument("Protected custom-data evidence exceeds 300000 values.")
                values = []
                for element in sequence:
                    item = element[layer]
                    if family == "uv":
                        item = (tuple(item.uv), bool(item.pin_uv), getattr(item, "select", None), getattr(item, "select_edge", None))
                    elif family == "deform":
                        item = sorted(item.items())
                        count += len(item)
                        if count > MAX_ATTRIBUTE_VALUES:
                            raise invalid_argument("Protected deform evidence exceeds 300000 custom values.")
                    elif family == "skin":
                        item = (tuple(item.radius), bool(item.use_root), bool(item.use_loose))
                    values.append(_value(item))
                result.append((domain, family, layer.name, layer == active, values))
    return result


def _matrix(obj):
    result = tuple(tuple(float(value) for value in row) for row in obj.matrix_world)
    if (len(result) != 4 or any(len(row) != 4 for row in result)
            or any(not math.isfinite(value) or abs(value) > 1e6 for row in result for value in row)
            or result[3] != (0., 0., 0., 1.)):
        raise invalid_argument("Surface fitting requires bounded finite affine object matrices.")
    try:
        inverse(result)
    except ValueError as error:
        raise invalid_argument("Surface fitting requires invertible object matrices.") from error
    return result


def _metadata(obj):
    mesh = obj.data
    if len(mesh.attributes) > 64 or len(obj.vertex_groups) > 256 or len(obj.material_slots) > 256 or len(mesh.uv_layers) > 16:
        raise invalid_argument("Surface fitting metadata exceeds 64 attributes, 256 groups/slots or 16 UV layers.")
    attributes = [(attr.name, attr.domain, attr.data_type) for attr in mesh.attributes]
    uv_flags = {f".{prefix}.{layer.name}" for prefix in ("vs", "es", "pn") for layer in mesh.uv_layers}
    for name, domain, kind in attributes:
        if name in GLOBAL_UV_ATTRIBUTES:
            if (domain, kind) != GLOBAL_UV_ATTRIBUTES[name]:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Global UV selection attribute domain/type is unsupported.")
            continue
        if name in BUILTIN_DATA and (domain, kind) != BUILTIN_DATA[name]:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Builtin mesh attribute domain/type differs from its protected native semantics.")
        if name in uv_flags:
            if domain == "CORNER" and kind == "BOOLEAN":
                continue
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV flag names require native CORNER BOOLEAN data.")
        if name not in BUILTIN_FLAGS and (domain not in {"POINT", "EDGE", "FACE", "CORNER"}
                or kind not in {"FLOAT", "INT", "FLOAT_VECTOR", "FLOAT_COLOR", "BYTE_COLOR", "FLOAT2", "STRING"}):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Protected attribute type/domain is unsupported.",
                              {"attribute": name, "domain": domain, "data_type": kind})
    return {"name": obj.name, "matrix": _matrix(obj), "attributes": attributes,
        "scenes": [_identity(scene) for scene in obj.users_scene],
        "collections": [(_identity(collection), collection.name) for collection in obj.users_collection],
        "groups": [(group.name, group.index, bool(group.lock_weight)) for group in obj.vertex_groups],
        "group_active": getattr(obj.vertex_groups, "active_index", None),
        "slots": [(_identity(slot.material) if slot.material else None, slot.link) for slot in obj.material_slots],
        "uv_roles": [(layer.name, bool(layer.active_render)) for layer in mesh.uv_layers],
        "uv_active": mesh.uv_layers.active_index,
        "color_roles": (mesh.color_attributes.active_color_index, mesh.color_attributes.render_color_index)}


def _capture(obj, bm):
    if sum(len(sequence) for sequence in (bm.verts, bm.edges, bm.faces)) > MAX_ELEMENTS:
        raise invalid_argument("Surface fitting requires at most 20000 mesh elements per object.")
    result = {"base": _snapshot(obj, bm), "metadata": _metadata(obj), "custom_data": _layers(bm)}
    inventory = {(domain, name) for domain, _family, name, _active, _values in result["custom_data"]}
    uv_values = {name: values for domain, family, name, _active, values in result["custom_data"] if domain == "CORNER" and family == "uv"}
    flag_proofs = {f".{prefix}.{uv}": all(value[offset] is not None for value in values)
                   for prefix, offset in (("pn", 1), ("vs", 2), ("es", 3)) for uv, values in uv_values.items()}
    domains = {"POINT": "VERT", "EDGE": "EDGE", "FACE": "FACE", "CORNER": "CORNER"}
    for name, domain, _kind in result["metadata"]["attributes"]:
        if name in GLOBAL_UV_ATTRIBUTES:
            if result["base"]["uv_global_selection"] is None:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Global UV selection attributes lack actual native BMesh flag proof.")
            continue
        if name in BUILTIN_FLAGS:
            continue
        if name in flag_proofs and (flag_proofs[name] or ("CORNER", name) in inventory):
            continue
        if (domains[domain], name) not in inventory:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "A protected mesh attribute has no bounded native custom-layer proof.", {"attribute": name})
    return result


def _context(bpy):
    selected = list(bpy.context.selected_objects)
    if len(selected) > 256:
        raise invalid_argument("Surface fitting context exceeds 256 selected objects.")
    return (_identity(bpy.context.scene), _identity(bpy.context.view_layer), bpy.data.filepath,
            bpy.context.mode, _identity(bpy.context.view_layer.objects.active), sorted(_identity(obj) for obj in selected))


def _check_object(obj, *, target):
    require_local_editable_id(obj, operation="Reference surface fitting")
    require_local_editable_id(obj.data, operation="Reference surface fitting")
    if target:
        require_local_single_user_mesh(obj)
    if obj.data.shape_keys or obj.data.has_custom_normals or len(obj.modifiers):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Surface fitting requires unmodified meshes without shape keys or custom normals; these need explicit preservation contracts.")
    if obj.hide_viewport or obj.hide_get():
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Reveal the explicit source and target before fitting.")


def _source(bpy, name):
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH" or bpy.context.view_layer.objects.get(name) != obj:
        raise invalid_argument("source_object must name a mesh in the current view layer.")
    if obj.mode != "OBJECT" or uses_edit_data(obj):
        raise BridgeError(ErrorCode.INVALID_MODE, "The reference source requires its own Object Mode base mesh.")
    _check_object(obj, target=False)
    return obj


def _target_scope(bpy, obj):
    if (bpy.context.view_layer.objects.get(obj.name) != obj
            or len(obj.users_scene) != 1 or obj.users_scene[0] != bpy.context.scene):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Working mesh must belong only to the current scene/view layer.")
    for collection in obj.users_collection:
        require_collection_scope(bpy, collection, operation="Surface projection")
    # The Object Mode helper deliberately excludes the native Scene Edit-object
    # reference. Prove this one extra reference explicitly rather than allowing
    # arbitrary scene users or suppressing the incoming-consumer check.
    try:
        users = list(islice(bpy.data.user_map(subset={obj}).get(obj, ()), MAX_DIRECT_USERS+1))
        layers = list(islice(bpy.context.scene.view_layers, MAX_VIEW_LAYERS+1))
        if len(users) > MAX_DIRECT_USERS or len(layers) > MAX_VIEW_LAYERS or len(obj.users_collection) > 256:
            raise ValueError("Incoming scope budget")
        containers = {_identity(collection) for collection in obj.users_collection}
        if any(collection.user_of_id(obj) != 1 for collection in obj.users_collection):
            raise ValueError("Collection has non-membership references")
        scene = bpy.context.scene
        root_links = int(scene.collection.objects.get(obj.name) == obj)
        base_links = sum(layer.objects.get(obj.name) == obj for layer in layers)
        edit_links = int(bpy.context.mode == "EDIT_MESH" and obj.mode == "EDIT" and bpy.context.edit_object == obj)
        expected = root_links+base_links+edit_links
        if edit_links != 1 or scene not in users:
            raise ValueError("Current native Edit-object membership cannot be proved")
        for user in users:
            if _identity(user) in containers:
                continue
            if (user == scene and edit_links == 1 and base_links > 0
                    and scene.collection.user_of_id(obj) == root_links and scene.user_of_id(obj) == expected):
                continue
            raise ValueError("Unreviewed incoming consumer")
    except Exception as error:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Surface projection incoming consumers/collection references exceed ordinary current Edit-scene membership.") from error


def _source_snapshot(obj, polygons):
    temporary = bmesh.new()
    try:
        temporary.from_mesh(obj.data)
        for sequence in (temporary.verts, temporary.edges, temporary.faces):
            sequence.ensure_lookup_table()
            sequence.index_update()
        snapshot = _capture(obj, temporary)
        selected = set(polygons)
        if any(temporary.faces[index].hide or any(vertex.hide for vertex in temporary.faces[index].verts)
               or any(edge.hide for edge in temporary.faces[index].edges) for index in polygons):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "Explicit reference polygons must be visible.")
        triangles = []
        for loops in temporary.calc_loop_triangles():
            if loops[0].face.index in selected:
                points = tuple(transform(snapshot["metadata"]["matrix"], _point(loop.vert.co)) for loop in loops)
                area = normal(points)[1]
                longest_squared = max(dot(sub(points[a], points[b]), sub(points[a], points[b]))
                                      for a, b in ((0, 1), (1, 2), (2, 0)))
                if area <= 1e-12 or (2*area)**2 <= 1e-20*longest_squared**2:
                    raise invalid_argument("Reference triangles must have finite nonzero world area.")
                triangles.append((loops[0].face.index, tuple(loop.vert.index for loop in loops), points))
        if not triangles or len(triangles) > MAX_TRIANGLES:
            raise invalid_argument("Reference scope needs 1-2048 native base triangles.")
        return snapshot, triangles
    finally:
        temporary.free()


def _session(bpy, obj, bm, handles, before_context):
    _native, current, live, _sequences = _active_edit_mesh(obj.name)
    if (current != obj or _context(bpy) != before_context or not bm.is_valid
            or any(len(sequence) != len(saved) or any(a != b for a, b in zip(sequence, saved, strict=True))
                   for sequence, saved in zip((live.verts, live.edges, live.faces), handles, strict=True))):
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The original surface fitting Edit session changed.")
    _check_object(obj, target=True)
    _target_scope(bpy, obj)


def _nearest(point, triangles):
    candidates = []
    for polygon, vertices, points in triangles:
        closest, bary = closest_point(point, *points)
        candidates.append((math.dist(point, closest), polygon, vertices, closest, bary))
    best = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    for other in candidates:
        if math.isclose(other[0], best[0], rel_tol=1e-9, abs_tol=1e-9) and math.dist(other[3], best[3]) > 1e-7:
            raise invalid_argument("Nearest surface is ambiguous; narrow the explicit source polygons.")
    return best


def _candidate_checks(bm, proposed, matrix, context, *, modifying=False):
    _face_checks(bm.faces, proposed)
    triangles: list[MeshTriangle] = []
    for face in bm.faces:
        indices = [vertex.index for vertex in face.verts]
        for index in range(1, len(indices)-1):
            vertices = (indices[0], indices[index], indices[index+1])
            points = tuple(transform(matrix, proposed.get(i, _point(bm.verts[i].co))) for i in vertices)
            triangles.append(MeshTriangle(len(triangles), face.index, vertices, points))
    if len(triangles) > MAX_TRIANGLES:
        raise invalid_argument("Target fan evidence exceeds 2048 triangles.")
    checked = intersection_analysis(triangles, epsilon=1e-6, max_pair_tests=MAX_PAIRS, max_reports=8,
                                     check_cancelled=lambda: _gate(context, modifying=modifying))
    if not checked["complete"] or any(checked["triangle_pairs"].values()):
        raise invalid_argument("Candidate target fan contact checks are incomplete or contain contacts; repair/narrow the working mesh first.",
                               contacts=checked)
    return checked


def _moving_scope(bm, indices):
    if any(bm.verts[index].hide for index in indices):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Moving vertices must be visible.")
    moving = [bm.verts[index] for index in indices]
    _adjacent_faces(moving)
    if any(not vertex.link_faces or any(edge.hide or any(other.hide for other in edge.verts)
           for edge in vertex.link_edges) for vertex in moving):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Moving surface vertices must have visible incident faces, edges and endpoints.")


def _proof_size(snapshot):
    custom = sum(len(row[4]) + (sum(len(item) for item in row[4]) if row[1] == "deform" else 0)
                 for row in snapshot["custom_data"])
    return sum(len(snapshot["base"][key]) for key in ("vertices", "edges", "faces")) + custom + len(snapshot["metadata"]["groups"])


def _prepare(context, params, *, modifying=False):
    _gate(context, modifying=modifying)
    name = _id_name(params.get("object_name"), "object_name")
    source_name = _id_name(params.get("source_object"), "source_object")
    selection = _id_name(params.get("selection_id"), "selection_id")
    maximum = float_param(params, "max_distance", 0., minimum=1e-9, maximum=1e6)
    bpy, obj, bm, _sequences = _active_edit_mesh(name)
    _check_object(obj, target=True)
    _target_scope(bpy, obj)
    source = _source(bpy, source_name)
    if source.data == obj.data:
        raise invalid_argument("Reference and working mesh must have distinct mesh data.")
    reference = validate_selection_reference(selection, obj, bm)
    indices = _indices(list(reference["vertices"]), len(bm.verts), "Referenced vertices")
    _moving_scope(bm, indices)
    polygons = _indices(params.get("source_polygon_indices"), len(source.data.polygons), "source_polygon_indices")
    # Refresh before freezing proof: dependency handlers are native user code and
    # can change scene state. Every later callback has a fresh guarded readback.
    bpy.context.view_layer.update()
    _current_bpy, current, live, _live_sequences = _active_edit_mesh(name)
    # Python wrappers can differ while native elements remain identical.
    if current != obj or any(len(a) != len(b) or any(x != y for x, y in zip(a, b, strict=True))
            for a, b in ((live.verts, bm.verts), (live.edges, bm.edges), (live.faces, bm.faces))):
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Native graph refresh changed the target Edit session.")
    _check_object(obj, target=True)
    _target_scope(bpy, obj)
    source = _source(bpy, source_name)
    reference = validate_selection_reference(selection, obj, bm)
    if _indices(list(reference["vertices"]), len(bm.verts), "Referenced vertices") != indices:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Native graph refresh changed referenced vertices.")
    _moving_scope(bm, indices)
    polygons = _indices(params.get("source_polygon_indices"), len(source.data.polygons), "source_polygon_indices")
    before_context = _context(bpy)
    handles = tuple(tuple(sequence) for sequence in (bm.verts, bm.edges, bm.faces))
    before = _capture(obj, bm)
    source_before, triangles = _source_snapshot(source, polygons)
    if (len(indices)+4)*(_proof_size(before)+_proof_size(source_before)) > MAX_REVALIDATION_VALUES:
        raise invalid_argument("Repeated live preservation proof exceeds 2000000 items; narrow the working/source mesh or target scope.")
    if len(indices)*len(triangles) > MAX_PAIRS:
        raise invalid_argument("Projection exceeds 262144 vertex/triangle tests.")
    matrix = before["metadata"]["matrix"]
    backwards = inverse(matrix)
    proposed, items = {}, []
    for index in indices:
        _gate(context, modifying=modifying)
        point = transform(matrix, _point(bm.verts[index].co))
        distance, polygon, vertices, hit, bary = _nearest(point, triangles)
        output = _point(transform(backwards, hit))
        actual = transform(matrix, output)
        displacement, residual = math.dist(point, actual), _nearest(actual, triangles)[0]
        if displacement > maximum+1e-9 or residual > 1e-6:
            raise invalid_argument("Projection exceeds max_distance or native float32 surface tolerance.", vertex_index=index)
        proposed[index] = output
        items.append({"vertex_index": index, "before_local": list(_point(bm.verts[index].co)),
            "after_local": list(output), "source_polygon_index": polygon, "source_vertices": list(vertices),
            "barycentric": list(bary), "distance_before_world": distance,
            "distance_after_world": residual, "displacement_world": displacement})
    checked = _candidate_checks(bm, proposed, matrix, context, modifying=modifying)
    _session(bpy, obj, bm, handles, before_context)
    if _capture(obj, bm) != before or _source(bpy, source_name) != source or _source_snapshot(source, polygons)[0] != source_before:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Surface source/target changed during preview; reinspect.")
    fingerprint = hashlib.sha256(json.dumps({"target": before, "source": source_before, "context": before_context,
        "polygons": polygons, "selection": indices, "max_distance": maximum, "proposed": proposed},
        sort_keys=True, allow_nan=False).encode()).hexdigest()
    preview = {"object": obj.name, "source_object": source.name, "source_geometry": "BASE_MESH",
        "method": "NEAREST_SURFACE", "coordinate_space": "WORLD", "normal_offset": 0., "fingerprint": fingerprint,
        "target_count": len(indices), "source_triangle_count": len(triangles), "items": items[:64],
        "items_truncated": len(items) > 64, "maximum_displacement_world": max(item["displacement_world"] for item in items),
        "maximum_distance_before_world": max(item["distance_before_world"] for item in items),
        "maximum_distance_after_world": max(item["distance_after_world"] for item in items),
        "candidate_fan_contacts": checked, "surface_tolerance_world": 1e-6,
        "limitations": "Explicit base nearest-point fitting only. Whole working triangle/quad fans checked at declared tolerance; no evaluated mapping, offsets, clearance/solid containment, other-object collision, automatic topology, custom normals or shape-key editing."}
    return bpy, obj, bm, source, handles, before_context, before, source_before, polygons, proposed, preview


def surface_projection_preview(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, PARAMS)
    return {**_prepare(context, params)[-1], "changed": False}


def project_to_surface(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, PARAMS | {"expected_fingerprint"})
    bpy, obj, bm, source, handles, before_context, before, source_before, polygons, proposed, preview = _prepare(context, params, modifying=True)
    if params.get("expected_fingerprint") != preview["fingerprint"]:
        raise invalid_argument("Surface projection requires the exact current preview fingerprint.")
    expected = {**before, "base": {**before["base"], "vertices": [
        (proposed.get(index, point), selected, hidden) for index, (point, selected, hidden) in enumerate(before["base"]["vertices"])]}}
    attempted = []

    def validate(target_state):
        _session(bpy, obj, bm, handles, before_context)
        if (_capture(obj, bm) != target_state or _source(bpy, source.name) != source
                or _source_snapshot(source, polygons)[0] != source_before):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Surface source, ownership or protected data changed; reinspect.")

    try:
        current = before
        for vertex, point in proposed.items():
            _gate(context, modifying=True)
            validate(current)
            context.require(Permission.EDIT_MESH)
            attempted.append(vertex)
            bm.verts[vertex].co = point
            current = {**current, "base": {**current["base"], "vertices": list(current["base"]["vertices"])}}
            _old, selected, hidden = current["base"]["vertices"][vertex]
            current["base"]["vertices"][vertex] = (point, selected, hidden)
        bm.normal_update()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        _gate(context, modifying=True)
        validate(expected)
    except Exception as error:
        restored = False
        try:
            _gate(context, modifying=True, recovery=True)
            _session(bpy, obj, bm, handles, before_context)
            # Restore only owned outputs. Changed source/protected data refuses
            # recovery rather than concealing another operation's mutation.
            partial = _capture(obj, bm)
            allowed = {**before, "base": {**before["base"], "vertices": list(partial["base"]["vertices"])}}
            if partial != allowed or _source(bpy, source.name) != source or _source_snapshot(source, polygons)[0] != source_before:
                raise RuntimeError("Protected state changed during surface projection")
            for index, (point, selected, hidden) in enumerate(partial["base"]["vertices"]):
                original = before["base"]["vertices"][index]
                if index not in attempted and (point, selected, hidden) != original:
                    raise RuntimeError("Unowned vertex changed")
                if index in attempted and (point not in (original[0], proposed[index]) or (selected, hidden) != original[1:]):
                    raise RuntimeError("Projection output replaced")
            context.require(Permission.EDIT_MESH)
            for vertex in reversed(attempted):
                bm.verts[vertex].co = before["base"]["vertices"][vertex][0]
            bm.normal_update()
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            _gate(context, modifying=True, recovery=True)
            _session(bpy, obj, bm, handles, before_context)
            restored = (_capture(obj, bm) == before and _source(bpy, params["source_object"]) == source
                        and _source_snapshot(source, polygons)[0] == source_before)
        except Exception:
            LOGGER.exception("Surface projection local recovery could not be verified")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Surface projection did not complete; inspect recovery and current mesh state.",
            {"object": obj.name, "affected_objects": [obj.name], "execution_started": bool(attempted),
             "rollback_verified": restored, "possible_mutation": bool(attempted) and not restored,
             "verification_required": True}) from error
    return {**preview, "changed": before != expected, "affected_objects": [obj.name],
        "topology_changed": False, "selection_changed": False, "source_preserved": True,
        "protected_vertices_preserved": True, "supported_custom_data_preserved": True,
        "material_bindings_preserved": True, "verification_required": True}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("mesh.surface_projection_preview", surface_projection_preview, toolset="mesh",
        permissions=(Permission.INSPECT_SCENE,), description="Preview fresh selected vertices fitted to explicit base reference polygons, with bounded measured correspondence and protected-data proof.")
    registry.register("mesh.project_to_surface", project_to_surface, toolset="mesh", modifies=True,
        permissions=(Permission.EDIT_MESH,), description="Apply an exact current nearest-base-surface preview, preserving supported mesh custom data and source geometry.")
