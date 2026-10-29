"""Private GLB recipe/conformance scope; no Blender or destination authority.

This temporary constructor prerequisite does not admit artist destinations.
Native source/default/catalog/bootstrap qualification remains a separate gate.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, fields, replace
from types import MappingProxyType, MemberDescriptorType
from typing import Any

from .asset_glb_import_plan import (
    PROFILE as PLAN_PROFILE,
)
from .asset_glb_import_plan import (
    ConversionRequirements,
    GLBImportPlan,
    MaterialPlan,
    MeshPlan,
    NodePlan,
    PrimitivePlan,
    validate_conversion_requirements,
)
from .errors import BridgeError, ErrorCode, invalid_argument

PROFILE = "GLB_PRIVATE_STAGE_V1"
MAX_PROJECTION_BYTES = 8 * 1024**2
PLAN_TYPES = (GLBImportPlan, MaterialPlan, MeshPlan, NodePlan, PrimitivePlan, ConversionRequirements)


def refused(reason: str, *, allocation_started: bool | None = None) -> BridgeError:
    context = {"reason": reason, "profile": PROFILE, "public_import_qualified": False}
    if allocation_started is not None:
        context["native_allocation_started"] = allocation_started
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "Outside the private GLB constructor profile.",
                      context)


def plain(value: Any, depth: int = 0, *, _budget: list[int] | None = None) -> Any:
    """Copy only bounded ordinary values; never invoke a foreign serializer."""
    budget = [1_000_000, MAX_PROJECTION_BYTES] if _budget is None else _budget
    budget[0] -= 1
    if depth > 16 or budget[0] < 0:
        raise invalid_argument("Private GLB projection exceeds its structural budget.")
    cls = type(value)
    if cls in PLAN_TYPES:
        result = {}
        for field in fields(cls):
            # Frozen slots are ordinary data, not a caller-supplied property.
            if type(vars(cls).get(field.name)) is not MemberDescriptorType:
                raise refused("PLAN_SLOT_CHANGED")
            result[field.name] = plain(object.__getattribute__(value, field.name), depth + 1,
                                       _budget=budget)
        return result
    if value is None or cls is bool:
        return value
    if cls is int and -(2**63) <= value < 2**64:
        return value
    if cls is float and math.isfinite(value) and abs(value) <= 1e12:
        return value
    if cls is str:
        try:
            size = len(value.encode("utf8")) if len(value) <= 8192 else 8193
            if size <= 8192 and size <= budget[1]:
                budget[1] -= size
                return value
        except UnicodeError:
            pass
    if cls in (list, tuple):
        return [plain(v, depth + 1, _budget=budget) for v in value]
    if cls is dict and len(value) <= 4096:
        if any(type(k) is not str or len(k) > 8192 for k in value):
            raise invalid_argument("Private GLB projection needs ordinary string keys.")
        return {plain(k, depth + 1, _budget=budget): plain(v, depth + 1, _budget=budget)
                for k, v in value.items()}
    raise invalid_argument("Private GLB projection contains an unsupported value.")


def _encode_plain(value: Any) -> bytes:
    chunks, count = [], 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    for part in encoder.iterencode(value):
        raw = part.encode()
        count += len(raw)
        if count > MAX_PROJECTION_BYTES:
            raise invalid_argument("Private GLB projection exceeds its byte budget.")
        chunks.append(raw)
    return b"".join(chunks)


def canonical(value: Any) -> bytes:
    return _encode_plain(plain(value))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def f32(value: float) -> str:
    if type(value) not in (float, int):
        raise invalid_argument("A finite ordinary scalar is required.")
    try:
        if not math.isfinite(value):
            raise invalid_argument("A finite ordinary scalar is required.")
        return struct.pack("<f", value).hex()
    except (OverflowError, struct.error) as cause:
        raise invalid_argument("Private GLB scalar does not fit Float32 storage.") from cause


IDENTITY = tuple(tuple(float(r == c) for c in range(4)) for r in range(4))
IDENTITY_BITS = tuple(f32(v) for row in IDENTITY for v in row)


@dataclass(frozen=True, slots=True)
class MeshRecipe:
    source_index: int
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    material_indices: tuple[int, ...]
    polygon_slots: tuple[int, ...]
    corner_uvs: tuple[tuple[float, float], ...] | None = None
    corner_normals: tuple[tuple[float, float, float], ...] | None = None
    corner_uv_present: tuple[bool, ...] = ()
    corner_normal_present: tuple[bool, ...] = ()


@dataclass(frozen=True, slots=True)
class MaterialRecipe:
    index: int
    color: tuple[str, ...]
    metallic: str
    roughness: str
    backface_culling: bool


@dataclass(frozen=True, slots=True)
class ObjectRecipe:
    source_index: int
    mesh_index: int | None
    parent_index: int | None = None
    location: tuple[str, ...] = (f32(0.),) * 3
    rotation_quaternion: tuple[str, ...] = (f32(1.), f32(0.), f32(0.), f32(0.))
    scale: tuple[str, ...] = (f32(1.),) * 3
    local_matrix: tuple[tuple[float, ...], ...] = IDENTITY
    world_matrix: tuple[tuple[float, ...], ...] = IDENTITY
    parent_inverse: tuple[str, ...] = IDENTITY_BITS


@dataclass(frozen=True, slots=True)
class PrivateRecipe:
    profile: str
    source_sha256: str
    plan_sha256: str
    meshes: tuple[MeshRecipe, ...]
    materials: tuple[MaterialRecipe, ...]
    objects: tuple[ObjectRecipe, ...]
    recipe_sha256: str


def recipe_data(recipe: PrivateRecipe) -> dict:
    if type(recipe) is not PrivateRecipe:
        raise invalid_argument("An exact private GLB recipe is required.")
    return {"profile": recipe.profile, "source_sha256": recipe.source_sha256,
            "plan_sha256": recipe.plan_sha256,
            "meshes": [{"source_index": m.source_index, "vertices": m.vertices,
                        "triangles": m.triangles, "materials": m.material_indices,
                        "polygon_slots": m.polygon_slots, "corner_uvs": m.corner_uvs,
                        "corner_normals": m.corner_normals,
                        "corner_uv_present": m.corner_uv_present,
                        "corner_normal_present": m.corner_normal_present} for m in recipe.meshes],
            "materials": [{"index": m.index, "color": m.color, "metallic": m.metallic,
                           "roughness": m.roughness, "backface": m.backface_culling}
                          for m in recipe.materials],
            "objects": [{"source_index": o.source_index, "mesh_index": o.mesh_index,
                         "parent_index": o.parent_index, "authored": object_authored(o),
                         "local_matrix": o.local_matrix, "world_matrix": o.world_matrix}
                        for o in recipe.objects]}


def _dot(first, second):
    return sum(a * b for a, b in zip(first, second, strict=True))


def _cross(first, second):
    a, b, c = first
    x, y, z = second
    return (b * z - c * y, c * x - a * z, a * y - b * x)


def _unit(vector):
    length = math.hypot(*vector)
    if not math.isfinite(length) or length == 0.:
        raise refused("TRANSFORM_AXES_DEGENERATE", allocation_started=False)
    return tuple(value / length for value in vector)


def _orthogonal(vector, axis):
    projected = _dot(vector, axis)
    return _unit(tuple(value - projected * other for value, other in zip(vector, axis, strict=True)))


def _quaternion(columns):
    """Canonical WXYZ unit quaternion from a proper orthonormal rotation."""
    m = tuple(tuple(columns[column][row] for column in range(3)) for row in range(3))
    trace = sum(m[i][i] for i in range(3))
    if trace > 0.:
        factor = 2. * math.sqrt(max(0., trace + 1.))
        values = (factor / 4., (m[2][1] - m[1][2]) / factor,
                  (m[0][2] - m[2][0]) / factor, (m[1][0] - m[0][1]) / factor)
    else:
        index = max(range(3), key=lambda i: m[i][i])
        other, last = (index + 1) % 3, (index + 2) % 3
        factor = 2. * math.sqrt(max(0., 1. + m[index][index] - m[other][other] - m[last][last]))
        vector = [0., 0., 0.]
        vector[index] = factor / 4.
        vector[other] = (m[index][other] + m[other][index]) / factor
        vector[last] = (m[index][last] + m[last][index]) / factor
        values = ((m[last][other] - m[other][last]) / factor, *vector)
    values = _unit(values)
    # Equivalent q/-q have one deterministic authored representation. This
    # convention derives from the frozen plan, never an observed native row.
    sign = next((value for value in values if value != 0.), 1.)
    return tuple(-value if sign < 0. else value for value in values)


def object_authored(recipe: ObjectRecipe) -> dict:
    """Exact assigned Float32 fields; numerical matrix tolerances confer no CAS."""
    if type(recipe) is not ObjectRecipe:
        raise invalid_argument("An exact private object recipe is required.")
    return {"rotation_mode": "QUATERNION", "location": list(recipe.location),
            "rotation_quaternion": list(recipe.rotation_quaternion), "scale": list(recipe.scale),
            "matrix_parent_inverse": list(recipe.parent_inverse)}


def compose_channels(location, rotation_quaternion, scale):
    """Independent Float64 matrix of the frozen assigned Float32 channels.

    This mathematical projection does not predict Blender's exact Float32
    evaluation or decomposition. Native conformance must retain measured bounds.
    """
    def decode(values):
        return tuple(struct.unpack("<f", bytes.fromhex(value))[0] for value in values)
    translation, quaternion, scales = decode(location), decode(rotation_quaternion), decode(scale)
    if len(translation) != 3 or len(quaternion) != 4 or len(scales) != 3:
        raise invalid_argument("Private transform channels have invalid arity.")
    w, x, y, z = _unit(quaternion)
    rotation = ((1. - 2. * (y * y + z * z), 2. * (x * y - z * w), 2. * (x * z + y * w)),
                (2. * (x * y + z * w), 1. - 2. * (x * x + z * z), 2. * (y * z - x * w)),
                (2. * (x * z - y * w), 2. * (y * z + x * w), 1. - 2. * (x * x + y * y)))
    rows = [(*(rotation[row][column] * scales[column] for column in range(3)), translation[row])
            for row in range(3)]
    rows.append((0., 0., 0., 1.))
    return tuple(rows)


def transform_recipe(node: NodePlan) -> ObjectRecipe:
    """Plan-only TRS decomposition, including reflected and zero-scale axes.

    The planner already rejects sheared input. Its small matrix-orthogonality
    allowance is tightened here: any residual beyond Float32 representation
    error refuses before allocation, rather than silently discarding shear.
    """
    if type(node) is not NodePlan:
        raise invalid_argument("An exact independently decoded node plan is required.")
    matrix = node.local_matrix
    columns = [tuple(matrix[row][column] for row in range(3)) for column in range(3)]
    scales = [math.hypot(*column) for column in columns]
    known = [index for index, value in enumerate(scales) if value != 0.]
    axes = [None, None, None]
    for index in known:
        axes[index] = _unit(columns[index])
    if len(known) == 3:
        if _dot(_cross(axes[0], axes[1]), axes[2]) < 0.:
            scales[0] = -scales[0]
            axes[0] = tuple(-value for value in axes[0])
        axes[1] = _orthogonal(axes[1], axes[0])
        axes[2] = _cross(axes[0], axes[1])
    elif len(known) == 2:
        first, second = known
        axes[second] = _orthogonal(axes[second], axes[first])
        missing = next(index for index in range(3) if index not in known)
        axes[missing] = _cross(axes[(missing + 1) % 3], axes[(missing + 2) % 3])
    elif len(known) == 1:
        index = known[0]
        helper = min(range(3), key=lambda i: abs(axes[index][i]))
        reference = tuple(float(i == helper) for i in range(3))
        axes[(index + 1) % 3] = _orthogonal(reference, axes[index])
        axes[(index + 2) % 3] = _cross(axes[index], axes[(index + 1) % 3])
    else:
        axes = [(1., 0., 0.), (0., 1., 0.), (0., 0., 1.)]
    location = tuple(f32(matrix[index][3]) for index in range(3))
    rotation = tuple(f32(value) for value in _quaternion(axes))
    scale = tuple(f32(value) for value in scales)
    composed = compose_channels(location, rotation, scale)
    # Per-column scale avoids admitting shear in a tiny axis merely because an
    # unrelated translation or scale is very large. This is a pure admission
    # bound, not a native-evaluation guarantee or tolerance-based state adoption.
    for column in range(4):
        magnitude = max(abs(matrix[row][column]) for row in range(4))
        budget = 8. * 2. ** -23 * magnitude + 2. ** -148
        if any(abs(composed[row][column] - matrix[row][column]) > budget for row in range(4)):
            raise refused("TRANSFORM_NOT_REPRESENTABLE_BY_FLOAT32_TRS", allocation_started=False)
    return ObjectRecipe(node.source_index, node.mesh_index, node.parent_index,
                        location, rotation, scale, node.local_matrix, node.world_matrix)


def expected_worlds(recipe: PrivateRecipe) -> dict[int, tuple[tuple[float, ...], ...]]:
    """Independent world projection of authored channels through owned parents."""
    if type(recipe) is not PrivateRecipe:
        raise invalid_argument("An exact private GLB recipe is required.")
    objects = {obj.source_index: obj for obj in recipe.objects}
    if len(objects) != len(recipe.objects):
        raise invalid_argument("Private object hierarchy has duplicate source indices.")
    result, active = {}, set()
    def visit(index):
        if index in active or index not in objects:
            raise invalid_argument("Private object hierarchy is incomplete or cyclic.")
        if index in result:
            return result[index]
        active.add(index)
        obj = objects[index]
        matrix = compose_channels(obj.location, obj.rotation_quaternion, obj.scale)
        if obj.parent_index is not None:
            parent = visit(obj.parent_index)
            matrix = tuple(tuple(sum(parent[row][k] * matrix[k][column] for k in range(4))
                                 for column in range(4)) for row in range(4))
        active.remove(index)
        result[index] = matrix
        return matrix
    for index in objects:
        visit(index)
    return result


def compile_profile(plan: GLBImportPlan) -> PrivateRecipe:
    if type(plan) is not GLBImportPlan:
        raise invalid_argument("Use an exact independently decoded GLB plan.")
    projected = plain(plan)
    del projected["normalized_sha256"]
    if hashlib.sha256(_encode_plain(projected)).hexdigest() != plan.normalized_sha256:
        raise invalid_argument("GLB numeric plan changed after independent validation.")
    validate_conversion_requirements(plan)
    if (plan.profile != PLAN_PROFILE or plan.dependencies or plan.coordinate_unit != "METERS"):
        raise refused("UNQUALIFIED_LOSS_OR_DEPENDENCY", allocation_started=False)
    if any(m.alpha_mode != "OPAQUE" for m in plan.materials):
        raise refused("ALPHA_MODE_NOT_YET_QUALIFIED", allocation_started=False)
    meshes = []
    for mesh in plan.meshes:
        vertices, triangles, slots, materials = [], [], [], []
        uvs, normals, uv_present, normal_present = [], [], [], []
        any_uv = any(primitive.texcoords is not None for primitive in mesh.primitives)
        any_normal = any(primitive.normals is not None for primitive in mesh.primitives)
        for primitive in mesh.primitives:
            offset = len(vertices)
            vertices.extend(primitive.positions)
            if primitive.material_index not in materials:
                materials.append(primitive.material_index)
            slot = materials.index(primitive.material_index)
            for triangle in primitive.triangles:
                triangles.append(tuple(i + offset for i in triangle))
                slots.append(slot)
                for index in triangle:
                    if any_uv:
                        uvs.append((0., 0.) if primitive.texcoords is None else primitive.texcoords[index])
                        uv_present.append(primitive.texcoords is not None)
                    if any_normal:
                        normals.append((0., 0., 0.) if primitive.normals is None else primitive.normals[index])
                        normal_present.append(primitive.normals is not None)
        meshes.append(MeshRecipe(mesh.source_index, tuple(vertices), tuple(triangles),
                                 tuple(materials), tuple(slots), tuple(uvs) if any_uv else None,
                                 tuple(normals) if any_normal else None, tuple(uv_present), tuple(normal_present)))
    materials = tuple(MaterialRecipe(i, tuple(f32(v) for v in m.base_color), f32(m.metallic),
                                    f32(m.roughness), not m.double_sided)
                      for i, m in enumerate(plan.materials))
    objects = tuple(transform_recipe(node) for node in plan.nodes)
    recipe = PrivateRecipe(PROFILE, plan.source_sha256, plan.normalized_sha256,
                           tuple(meshes), materials, objects, "")
    return replace(recipe, recipe_sha256=digest(recipe_data(recipe)))


def mesh_body(mesh: MeshRecipe) -> dict:
    edges = sorted({tuple(sorted((face[i], face[(i + 1) % 3])))
                    for face in mesh.triangles for i in range(3)})
    return {"vertices": [[f32(v) for v in row] for row in mesh.vertices],
            "loops": [v for face in mesh.triangles for v in face],
            "face_ranges": [[3 * i, 3] for i in range(len(mesh.triangles))],
            "polygons": [[list(face), slot, False]
                         for face, slot in zip(mesh.triangles, mesh.polygon_slots, strict=True)],
            "edges": [list(edge) for edge in edges], "materials": [], "uv": None, "normals": None,
            "custom_data": {}}


def mesh_uv_body(mesh: MeshRecipe) -> dict | None:
    """Authored UV input after the planner's declared V-origin conversion."""
    if mesh.corner_uvs is None:
        return None
    return {"name": "UVMap", "vectors": [[f32(value) for value in uv] for uv in mesh.corner_uvs],
            "active": 0, "render": 0, "clone": 0, "stencil": 0, "clone_bound": True, "stencil_bound": True}


def mesh_normal_body(mesh: MeshRecipe) -> dict | None:
    """Frozen normal setter inputs, not an encoded native-normal prediction.

    Missing primitive normals carry a zero AUTO sentinel and an explicit
    presence mask. Native use of that sentinel is gated by the pinned setter
    contract and actual complete corner-normal conformance evidence.
    """
    if mesh.corner_normals is None:
        return None
    return {"source": [[f32(value) for value in normal] for normal in mesh.corner_normals],
            "present": list(mesh.corner_normal_present)}


def validate_new_row(role: str, name: str, row: dict, *, material_tree: str | None = None,
                     data_role: str | None = None) -> dict:
    """Validate a fresh canonical-constructor result, before any caller callback.

    Only fresh returned IDs can supply these initial receipts. This function
    alone does not prove freshness, provenance, native getter safety or grants.
    """
    row = plain(row)
    if set(row) != {"name", "kind", "uid", "pointer", "users", "fake_user", "body"}:
        raise refused("CONSTRUCTOR_ROW_SHAPE")
    kind = role.split(":")[0]
    if (row["kind"] != kind or row["name"] != name or type(row["uid"]) is not int
            or not 0 < row["uid"] < 2**64 or type(row["pointer"]) is not int
            or not 0 < row["pointer"] < 2**64 or row["fake_user"] is not False
            or type(row["users"]) is not int or not 0 <= row["users"] <= 2):
        raise refused("CONSTRUCTOR_ID_SHAPE")
    body = row["body"]
    if type(body) is not dict:
        raise refused("CONSTRUCTOR_BODY_SHAPE")
    if kind == "collection" and (body != {"objects": [], "children": []} or row["users"] != 0):
        raise refused("COLLECTION_CONSTRUCTOR_SHAPE")
    if kind == "mesh" and (body != {
            **{k: [] for k in ("vertices", "loops", "face_ranges", "polygons", "edges", "materials")},
            "uv": None, "normals": None, "custom_data": {}}
                           or row["users"] != 0):
        raise refused("MESH_CONSTRUCTOR_SHAPE")
    if kind == "material" and (set(body) != {"diffuse", "use_nodes", "tree", "backface"}
                or body["tree"] != material_tree or type(body["use_nodes"]) is not bool
                or body["use_nodes"] is not (material_tree is not None)
                or type(body["backface"]) is not bool or row["users"] != 0
                or type(body["diffuse"]) is not list or len(body["diffuse"]) != 4):
        raise refused("MATERIAL_CONSTRUCTOR_SHAPE")
    if kind == "node_tree" and (set(body) != {"layout", "other_inputs", "pbr", "links", "active_output", "output_target"}
                or type(body["layout"]) is not list or len(body["layout"]) != 2
                or any(type(n) is not list or len(n) != 5 or type(n[0]) is not str for n in body["layout"])
                or sorted(n[0] for n in body["layout"]) != ["ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"]
                or body["active_output"] is not True or body["output_target"] != "ALL"
                or body["links"] != [["ShaderNodeBsdfPrincipled", "BSDF", "ShaderNodeOutputMaterial", "Surface"]]
                or type(body["pbr"]) is not dict
                or set(body["pbr"]) != {"Base Color", "Metallic", "Roughness", "Alpha"}):
        raise refused("SURFACE_DEFAULT_GRAPH_REQUIRED")
    if kind == "object" and (set(body) != {"data", "parent", "matrix", "channels", "collections",
                                             "rotation_mode", "parent_inverse", "parent_type", "children"}
                or body["data"] != data_role or body["parent"] is not None
                or body["matrix"] != list(IDENTITY_BITS) or body["collections"] != []
                or body["rotation_mode"] != "XYZ" or body["parent_type"] != "OBJECT"
                or body["parent_inverse"] != list(IDENTITY_BITS) or body["children"] != []
                or type(body["channels"]) is not dict
                or body["channels"].get("rotation_euler") != [f32(0.)] * 3
                or body["channels"].get("rotation_quaternion") != [f32(1.), *([f32(0.)] * 3)]
                or row["users"] != 0):
        raise refused("OBJECT_CONSTRUCTOR_SHAPE")
    return row


# This is an internal stock-runtime binding, not a Runtime grant or a serialized
# certificate. Constructor-dependent owners are admitted only after real returns.
NATIVE_BUILDS = {(4, 5, 14): b"62c1db4208e8", (5, 2, 2): b"d13f752e3b9c"}
NATIVE_FIELDS = {
    "ID": "name:STRING session_uid:INT users:INT use_fake_user:BOOLEAN library:POINTER override_library:POINTER",
    "BlendData": "filepath:STRING collections:COLLECTION meshes:COLLECTION materials:COLLECTION objects:COLLECTION node_groups:COLLECTION scenes:COLLECTION worlds:COLLECTION",
    "Context": "scene:POINTER view_layer:POINTER mode:ENUM",
    "Scene": "collection:POINTER frame_current:INT frame_subframe:FLOAT",
    "ViewLayer": "objects:COLLECTION",
    "LayerObjects": "active:POINTER",
    "Collection": "objects:COLLECTION children:COLLECTION",
    "Mesh": "vertices:COLLECTION loops:COLLECTION polygons:COLLECTION edges:COLLECTION materials:COLLECTION "
        "uv_layers:COLLECTION attributes:COLLECTION corner_normals:COLLECTION has_custom_normals:BOOLEAN "
        "uv_layer_clone_index:INT uv_layer_stencil_index:INT uv_layer_clone:POINTER uv_layer_stencil:POINTER",
    "MeshVertex": "co:FLOAT/3",
    "MeshLoop": "vertex_index:INT",
    "MeshPolygon": "loop_start:INT loop_total:INT vertices:INT/* material_index:INT use_smooth:BOOLEAN",
    "MeshEdge": "vertices:INT/2",
    "Material": "use_nodes:BOOLEAN node_tree:POINTER diffuse_color:FLOAT/4 use_backface_culling:BOOLEAN",
    "Object": "type:ENUM data:POINTER parent:POINTER matrix_local:FLOAT/16 "
        "rotation_mode:ENUM parent_type:ENUM matrix_basis:FLOAT/16 matrix_parent_inverse:FLOAT/16 "
        "location:FLOAT/3 rotation_euler:FLOAT/3 rotation_quaternion:FLOAT/4 rotation_axis_angle:FLOAT/4 "
        "scale:FLOAT/3 delta_location:FLOAT/3 delta_rotation_euler:FLOAT/3 "
        "delta_rotation_quaternion:FLOAT/4 delta_scale:FLOAT/3",
    "ShaderNodeTree": "type:ENUM nodes:COLLECTION links:COLLECTION",
    "Node": "name:STRING location:FLOAT/2 width:FLOAT mute:BOOLEAN inputs:COLLECTION",
    "NodeSocket": "identifier:STRING type:ENUM",
    "ShaderNodeOutputMaterial": "is_active_output:BOOLEAN target:ENUM",
    "NodeLink": "from_node:POINTER from_socket:POINTER to_node:POINTER to_socket:POINTER",
    "UVLoopLayers": "active_index:INT",
    "MeshUVLoopLayer": "name:STRING active:BOOLEAN active_render:BOOLEAN active_clone:BOOLEAN uv:COLLECTION",
    "Attribute": "name:STRING domain:ENUM data_type:ENUM",
    "Float2Attribute": "data:COLLECTION",
    "Float2AttributeValue": "vector:FLOAT/2",
    "FloatVectorAttribute": "data:COLLECTION",
    "FloatVectorAttributeValue": "vector:FLOAT/3",
    "IntAttribute": "data:COLLECTION",
    "IntAttributeValue": "value:INT/0",
    "Int2Attribute": "data:COLLECTION",
    "Int2AttributeValue": "value:INT/2",
    "Short2Attribute": "data:COLLECTION",
    "Short2AttributeValue": "value:INT/2",
    "BoolAttribute": "data:COLLECTION",
    "BoolAttributeValue": "value:BOOLEAN/0",
    "MeshNormalValue": "vector:FLOAT/3",
}
NATIVE_FUNCTIONS = {
    "ID": {"user_of_id": (("id", "POINTER", False), ("count", "INT", True))},
    "BlendDataCollections": {"new": (("name", "STRING", False), ("collection", "POINTER", True))},
    "BlendDataMeshes": {"new": (("name", "STRING", False), ("mesh", "POINTER", True))},
    "BlendDataMaterials": {"new": (("name", "STRING", False), ("material", "POINTER", True))},
    "BlendDataObjects": {"new": (("name", "STRING", False), ("object_data", "POINTER", False),
                                  ("object", "POINTER", True))},
    "MeshVertices": {"add": (("count", "INT", False),)},
    "MeshLoops": {"add": (("count", "INT", False),)},
    "MeshPolygons": {"add": (("count", "INT", False),)},
    "Mesh": {"update": (("calc_edges", "BOOLEAN", False), ("calc_edges_loose", "BOOLEAN", False)),
             "normals_split_custom_set": (("normals", "FLOAT", False),)},
    "UVLoopLayers": {"new": (("name", "STRING", False), ("do_init", "BOOLEAN", False),
                             ("layer", "POINTER", True))},
    "IDMaterials": {"append": (("material", "POINTER", False),)},
    "CollectionObjects": {"link": (("object", "POINTER", False),)},
    "CollectionChildren": {"link": (("child", "POINTER", False),)},
}


NATIVE_FIXED = {
    "BlendData": dict(collections="Collection", meshes="Mesh", materials="Material", objects="Object",
                      node_groups="NodeTree", scenes="Scene", worlds="World"),
    "Context": dict(scene="Scene", view_layer="ViewLayer"),
    "Scene": dict(collection="Collection"),
    "ViewLayer": dict(objects="Object"), "LayerObjects": dict(active="Object"),
    "Collection": dict(objects="Object", children="Collection"),
    "Mesh": dict(vertices="MeshVertex", loops="MeshLoop", polygons="MeshPolygon", edges="MeshEdge", materials="Material",
                 uv_layers="MeshUVLoopLayer", attributes="Attribute", corner_normals="MeshNormalValue",
                 uv_layer_clone="MeshUVLoopLayer", uv_layer_stencil="MeshUVLoopLayer"),
    "Material": dict(node_tree="NodeTree"),
    "Object": dict(data="ID", parent="Object"),
    "ShaderNodeTree": dict(nodes="Node", links="NodeLink"),
    "Node": dict(inputs="NodeSocket"),
    "NodeLink": dict(from_node="Node", to_node="Node", from_socket="NodeSocket", to_socket="NodeSocket"),
    "MeshUVLoopLayer": dict(uv="Float2AttributeValue"),
    "Float2Attribute": dict(data="Float2AttributeValue"),
    "FloatVectorAttribute": dict(data="FloatVectorAttributeValue"),
    "IntAttribute": dict(data="IntAttributeValue"),
    "Int2Attribute": dict(data="Int2AttributeValue"),
    "Short2Attribute": dict(data="Short2AttributeValue"),
    "BoolAttribute": dict(data="BoolAttributeValue"),
}


def native_property_signature(prop, *, read=getattr, pointer=lambda value: value.as_pointer()):
    """Literal used RNA metadata; array_length exists only for numeric kinds."""
    kind = read(prop, "type")
    width = read(prop, "array_length") if kind in {"BOOLEAN", "INT", "FLOAT"} else None
    if width is not None and (type(width) is not int or not 0 <= width <= 65536):
        raise refused("NATIVE_PROPERTY_ARRAY_BUDGET")
    fixed = read(prop, "fixed_type") if kind in {"POINTER", "COLLECTION"} else None
    pointer = pointer(prop)
    flags = (read(prop, "is_runtime"), read(prop, "is_registered"), read(prop, "is_readonly"))
    if (any(type(value) is not bool for value in flags) or type(pointer) is not int
            or not 0 < pointer < 2**64):
        raise refused("NATIVE_PROPERTY_METADATA_SHAPE")
    return (read(prop, "identifier"), kind, width, *flags, None if fixed is None else read(fixed, "identifier"), pointer)


def require_native_property(prop, name, kind, width=None, *, writing=False, read=getattr, pointer=lambda value: value.as_pointer()):
    if prop is None:
        raise refused("NATIVE_PROPERTY_MISSING")
    signature = native_property_signature(prop, read=read, pointer=pointer)
    if (signature[0] != name or signature[1] != kind or signature[3] is not False
            or (width != "*" and width is not None and signature[2] != width)
            or (writing and signature[5] is not False)):
        raise refused("NATIVE_PROPERTY_CONTRACT_CHANGED")
    # Registration flags are retained individually. Some source-defined node
    # registration fields differ from ordinary numeric properties; never infer
    # getter purity from a blanket flag rule.
    return signature


def native_function_signature(function, schema, method, *, class_name=None, read=getattr, pointer=lambda value: value.as_pointer(), items=tuple):
    """Used metadata contract only; these plain observations grant no calls."""
    if function is None or read(function, "is_registered") is not False or read(function, "is_registered_optional") is not False:
        raise refused("NATIVE_FUNCTION_REQUIRED")
    parameters = items(read(function, "parameters"))
    if len(parameters) != len(schema):
        raise refused("NATIVE_FUNCTION_PARAMETERS_CHANGED")
    rows = []
    for prop, (name, kind, output) in zip(parameters, schema, strict=True):
        dynamic_normals = class_name == "Mesh" and method == "normals_split_custom_set" and name == "normals"
        width = "*" if dynamic_normals else 0 if kind in {"BOOLEAN", "INT", "FLOAT"} else None
        signature = require_native_property(prop, name, kind, width, read=read, pointer=pointer)
        fixed = {"collection": "Collection", "child": "Collection", "mesh": "Mesh", "material": "Material",
                 "object": "Object", "object_data": "ID", "id": "ID", "layer": "MeshUVLoopLayer"}.get(name)
        optional_uv = class_name == "UVLoopLayers" and method == "new"
        required = not output and method != "update" and not optional_uv
        if (read(prop, "is_output") is not output or type(read(prop, "is_required")) is not bool
                or (not output and read(prop, "is_required") is not required)
                or (fixed is not None and signature[6] != fixed)):
            raise refused("NATIVE_FUNCTION_DIRECTION_CHANGED")
        rows.append((signature, read(prop, "is_required"), read(prop, "is_output")))
    pointer = pointer(function)
    if type(pointer) is not int or not 0 < pointer < 2**64:
        raise refused("NATIVE_FUNCTION_IDENTITY_REQUIRED")
    return pointer, tuple(rows)


_STOCK_TREE_NAMES = ("CompositorNodeTree", "ShaderNodeTree", "TextureNodeTree", "GeometryNodeTree")
_TREE_CALLBACK_FIELDS = frozenset({"bl_idname", "bl_label", "bl_description", "bl_icon", "poll", "update",
    "get_from_context", "valid_socket_type", "interface_update", "draw_buttons", "draw_buttons_ext",
    "__getattribute__", "__setattr__", "__getattr__"})
_TYPE_FIELDS = MappingProxyType({name: vars(type)[name] for name in ("__name__", "__bases__", "__dict__")})
_TYPE_SUBCLASSES = vars(type)["__subclasses__"]


def stock_tree_family(node_tree, classes, *, id_base, base_module):
    """Bounded supported-namespace proof, not a hostile-interpreter sandbox.

    C fallback RNA classes have their identifier/name, bpy.types module, one
    NodeTree base and empty slots. Python registration retains supplied class
    namespaces; a MyTree with bl_idname=ShaderNodeTree remains a descendant even
    when the RNA type resolver still exposes the original ShaderNodeTree head.
    Inspect the complete family without invoking class/metaclass descriptors.
    """
    if (type(classes) is not dict or len(classes) != 4 or any(type(name) is not str for name in classes)
            or set(classes) != set(_STOCK_TREE_NAMES) or not isinstance(node_tree, type)
            or not isinstance(id_base, type) or type(base_module) is not str
            or base_module not in {"bpy_types", "_bpy_types"}
            or any(not isinstance(cls, type) for cls in classes.values())):
        raise refused("NATIVE_STOCK_TREE_FAMILY_INCOMPLETE", allocation_started=False)
    root_namespace = _TYPE_FIELDS["__dict__"].__get__(node_tree)
    root_slots = root_namespace.get("__slots__")
    root_bases = _TYPE_FIELDS["__bases__"].__get__(node_tree)
    root_module = root_namespace.get("__module__")
    if (type(root_slots) is not tuple or len(root_slots) != 0
            or _TYPE_FIELDS["__name__"].__get__(node_tree) != "NodeTree"
            or type(root_module) is not str or root_module != base_module
            or type(root_bases) is not tuple or len(root_bases) != 1 or root_bases[0] is not id_base
            or any(name in root_namespace for name in _TREE_CALLBACK_FIELDS)):
        raise refused("NATIVE_STOCK_NODE_TREE_BASE_CHANGED", allocation_started=False)
    expected = tuple(classes[name] for name in _STOCK_TREE_NAMES)
    if len({id(cls) for cls in expected}) != 4:
        raise refused("NATIVE_STOCK_TREE_FAMILY_ALIASED", allocation_started=False)
    for name, cls in zip(_STOCK_TREE_NAMES, expected, strict=True):
        namespace = _TYPE_FIELDS["__dict__"].__get__(cls)
        bases = _TYPE_FIELDS["__bases__"].__get__(cls)
        slots, module = namespace.get("__slots__"), namespace.get("__module__")
        if (type(module) is not str or module != "bpy.types"
                or _TYPE_FIELDS["__name__"].__get__(cls) != name
                or type(bases) is not tuple or len(bases) != 1 or bases[0] is not node_tree
                or type(slots) is not tuple or len(slots) != 0
                or any(field in namespace for field in _TREE_CALLBACK_FIELDS)):
            raise refused("NATIVE_EXTENSION_TREE_NAMESPACE_UNQUALIFIED", allocation_started=False)
    pending, seen = list(_TYPE_SUBCLASSES(node_tree)), set()
    while pending:
        if len(pending) + len(seen) > 64:
            raise refused("NATIVE_NODE_TREE_FAMILY_BUDGET", allocation_started=False)
        cls = pending.pop()
        identity = id(cls)
        if identity in seen:
            continue
        seen.add(identity)
        if not any(cls is stock for stock in expected):
            raise refused("NATIVE_UNPROVEN_NODE_TREE_SUBCLASS", allocation_started=False)
        pending.extend(_TYPE_SUBCLASSES(cls))
    if seen != {id(cls) for cls in expected}:
        raise refused("NATIVE_STOCK_TREE_FAMILY_MISSING", allocation_started=False)
    return tuple((name, id(classes[name])) for name in _STOCK_TREE_NAMES)


_STOCK_TREE_GUARD_ORIGIN = stock_tree_family
_STOCK_TREE_GUARD_CODE = stock_tree_family.__code__


class NativeBinding:
    """No-argument actual bpy binding for the private owned-process constructor.

    Supported runtime provenance, not a hostile-interpreter sandbox. The fixed
    isolated runner establishes process disposal; no blank-file/Boolean grants it.
    """

    def __init__(self, *, runtime_gate=None):
        self._runtime_gate = runtime_gate
        if runtime_gate is not None:
            runtime_gate.check()
        import importlib
        import sys
        import threading
        from types import (
            BuiltinFunctionType,
            MethodDescriptorType,
            ModuleType,
            WrapperDescriptorType,
        )

        try:
            bpy = importlib.import_module("bpy")
        except ImportError as error:
            raise refused("NATIVE_BLENDER_REQUIRED", allocation_started=False) from error
        if type(bpy) is not ModuleType or sys.modules.get("bpy") is not bpy:
            raise refused("NATIVE_MODULE_REQUIRED", allocation_started=False)
        namespace = vars(bpy)
        app, types = namespace.get("app"), namespace.get("types")
        if (app is None or types is None or threading.current_thread() is not threading.main_thread()
                or tuple(self._access("app:version", getattr, app, "version")) not in NATIVE_BUILDS
                or self._access("app:build_hash", getattr, app, "build_hash") != NATIVE_BUILDS[tuple(self._access("app:version", getattr, app, "version"))] or self._access("app:build_type", getattr, app, "build_type") != b"Release"):
            raise refused("NATIVE_BUILD_OR_THREAD_UNQUALIFIED", allocation_started=False)
        resolver = vars(types).get("__getattr__")
        if (type(resolver) is not BuiltinFunctionType or resolver.__self__ is not types
                or resolver.__name__ != "__getattr__"):
            raise refused("NATIVE_TYPE_REGISTRY_REQUIRED", allocation_started=False)
        self.bpy, self.app, self.types, self.resolver = bpy, app, types, resolver
        self.version_tuple, self.build_hash = tuple(self._access("app:version", getattr, app, "version")), self._access("app:build_hash", getattr, app, "build_hash")
        self.thread, self.thread_object = threading.get_ident(), threading.main_thread()
        self.base = vars(types).get("bpy_struct")
        self.collection_type = vars(types).get("bpy_prop_collection")
        self.function_type = vars(types).get("bpy_func")
        self.array_type = vars(types).get("bpy_prop_array")
        if any(not isinstance(cls, type) for cls in (self.base, self.collection_type, self.function_type, self.array_type)):
            raise refused("NATIVE_WRAPPER_TYPES_REQUIRED", allocation_started=False)
        self.getter = vars(self.base).get("__getattribute__")
        self.setter = vars(self.base).get("__setattr__")
        self.pointer = vars(self.base).get("as_pointer")
        if (any(type(fn) is not WrapperDescriptorType or fn.__objclass__ is not self.base
                for fn in (self.getter, self.setter)) or type(self.pointer) is not MethodDescriptorType
                or self.pointer.__objclass__ is not self.base):
            raise refused("NATIVE_ACCESS_SLOTS_REQUIRED", allocation_started=False)
        self.foreach = vars(self.collection_type).get("foreach_set")
        if type(self.foreach) is not MethodDescriptorType or self.foreach.__objclass__ is not self.collection_type:
            raise refused("NATIVE_FOREACH_REQUIRED", allocation_started=False)
        self.foreach_read = vars(self.collection_type).get("foreach_get")
        if type(self.foreach_read) is not MethodDescriptorType or self.foreach_read.__objclass__ is not self.collection_type:
            raise refused("NATIVE_FOREACH_GET_REQUIRED", allocation_started=False)
        self.classes, self.properties, self.functions, self.class_namespaces, self.rnas = {}, {}, {}, {}, {}
        self._tree_family = None
        for name in (*NATIVE_FIELDS, *NATIVE_FUNCTIONS, "ShaderNodeBsdfPrincipled", "NodeSocketShader"):
            self.resolve(name)
        self._qualify_tree_family()
        for name, layout in NATIVE_FIELDS.items():
            for definition in layout.split():
                field, shape = definition.split(":")
                kind, _, width = shape.partition("/")
                self.field(self.classes[name], field, kind, "*" if width == "*" else int(width or 0)
                           if kind in {"BOOLEAN", "INT", "FLOAT"} else None)
        for name, functions in NATIVE_FUNCTIONS.items():
            for method, schema in functions.items():
                self.function(name, method, schema)
        self.main, self.context = namespace.get("data"), namespace.get("context")
        if self.main is None or self.context is None:
            raise refused("NATIVE_MAIN_REQUIRED", allocation_started=False)
        self.main_pointer = self._pointer(self.main)
        self.initial_scene = self.get(self.context, "scene")
        self.initial_layer = self.get(self.context, "view_layer")
        self.scene_pointer, self.layer_pointer = self._pointer(self.initial_scene), self._pointer(self.initial_layer)
        self.scene_uid = self.get(self.initial_scene, "session_uid")
        self.constructors = {}
        for family, name in (("collections", "Collections"), ("meshes", "Meshes"),
                             ("materials", "Materials"), ("objects", "Objects")):
            owner = self.get(self.main, family)
            self.constructors[family] = (owner, self.callable(owner, "BlendData" + name, "new"))
        mathutils = importlib.import_module("mathutils")
        self.vector_types = (self.array_type, mathutils.Vector, mathutils.Euler, mathutils.Quaternion)
        self.matrix_type, self.mathutils = mathutils.Matrix, mathutils
        self._origin = (bpy, app, types, resolver, self.base, self.getter, self.setter, self.pointer,
                        self.collection_type, self.function_type, self.array_type, self.foreach, self.foreach_read,
                        self.vector_types, self.matrix_type, self.mathutils)
        self.check()

    def _qualify_tree_family(self):
        if stock_tree_family is not _STOCK_TREE_GUARD_ORIGIN or stock_tree_family.__code__ is not _STOCK_TREE_GUARD_CODE:
            raise refused("NATIVE_STOCK_TREE_GUARD_SOURCE_CHANGED", allocation_started=False)
        root = self.resolve("NodeTree")
        classes = {name: self.resolve(name) for name in _STOCK_TREE_NAMES}
        current = stock_tree_family(root, classes, id_base=self.classes["ID"],
            base_module="bpy_types" if self.version_tuple[:2] == (4, 5) else "_bpy_types")
        if self._tree_family is not None and current != self._tree_family:
            raise refused("NATIVE_STOCK_TREE_REGISTRY_CHANGED", allocation_started=False)
        self._tree_family = current

    def _access(self, label, function, *args, escrow=None, capture_role=None):
        gate = self._runtime_gate
        if gate is not None and (type(self) is not NativeBinding or any(
                vars(NativeBinding).get(name) is not fn or fn.__code__ is not code
                for name, fn, code in _BINDING_METHOD_ORIGINS)):
            raise refused("GLB_NATIVE_BINDING_CODE_ORIGIN_CHANGED")
        if gate is not None:
            gate.check()
            cell = gate.enter(label)
        else:
            cell = None
        result = function(*args)
        if escrow is not None:
            escrow.remember(capture_role, result)
        if gate is not None:
            gate.returned(cell)
            gate.check()
        return result

    def _raw(self, owner, name):
        return self._access("get:" + name, self.getter, owner, name)

    def _pointer(self, owner):
        return self._access("as_pointer", self.pointer, owner)

    def _resolve(self, name):
        return self._access("resolve:" + name, self.resolver, name)

    def length(self, value):
        return self._access("collection_len", len, value)

    def copy(self, value):
        # A native collection iterator can enter C for each component.
        iterator = self._access("iter", iter, value)
        result = []
        while True:
            try:
                item = self._access("next", next, iterator)
            except StopIteration:
                return tuple(result)
            result.append(item)

    def items(self, value):
        return self.copy(value)

    def _rna(self, cls):
        import inspect
        raw = inspect.getattr_static(cls, "bl_rna", None)
        if raw is None or self.base not in type(raw).__mro__:
            raise refused("NATIVE_CLASS_RNA_REQUIRED")
        for field in ("identifier", "properties", "functions"):
            self._screen(type(raw), field)
        pointer = self._pointer(raw)
        if cls in self.rnas and self.rnas[cls][1] != pointer:
            raise refused("NATIVE_CLASS_RNA_CHANGED")
        self.rnas[cls] = (raw, pointer)
        return raw

    def resolve(self, name):
        cls = self._resolve(name)
        if not isinstance(cls, type) or self.base not in cls.__mro__:
            raise refused("NATIVE_CLASS_REQUIRED")
        if name in self.classes and self.classes[name] is not cls:
            raise refused("NATIVE_CLASS_CHANGED")
        if self._raw(self._rna(cls), "identifier") != name:
            raise refused("NATIVE_CLASS_RNA_CHANGED")
        self.classes[name] = cls
        return cls

    def _screen(self, cls, name):
        import inspect
        from types import GetSetDescriptorType, MemberDescriptorType
        descriptor = inspect.getattr_static(cls, name, None)
        if descriptor is not None and (type(descriptor) not in {GetSetDescriptorType, MemberDescriptorType}
                                       or descriptor.__objclass__ not in cls.__mro__):
            raise refused("NATIVE_FIELD_PYTHON_SHADOW")
        if (inspect.getattr_static(cls, "__getattribute__", None) is not self.getter
                or inspect.getattr_static(cls, "__setattr__", None) is not self.setter):
            raise refused("NATIVE_OWNER_ACCESS_SLOT_CHANGED")
        # Raw namespace observation is never an invocation of the field.
        key = (cls, name)
        before = self.class_namespaces.get(key, descriptor)
        if before is not descriptor:
            raise refused("NATIVE_FIELD_BINDING_CHANGED")
        self.class_namespaces[key] = descriptor

    def _metadata(self, owner, names):
        import inspect
        cls = type(owner)
        if self.base not in cls.__mro__ or self._resolve(self._raw(self._rna(cls), "identifier")) is not cls:
            raise refused("NATIVE_METADATA_CLASS_REQUIRED")
        if inspect.getattr_static(cls, "as_pointer", None) is not self.pointer:
            raise refused("NATIVE_METADATA_POINTER_ORIGIN")
        for name in names:
            self._screen(cls, name)
        if "type" in names:
            if self._raw(owner, "type") in {"BOOLEAN", "INT", "FLOAT"}:
                self._screen(cls, "array_length")
            elif self._raw(owner, "type") in {"POINTER", "COLLECTION"}:
                self._screen(cls, "fixed_type")

    def field(self, cls, name, kind, width=None, *, writing=False):
        self._screen(cls, name)
        prop = self._access("metadata_property_get", self._raw(self._rna(cls), "properties").get, name)
        if prop is not None:
            self._metadata(prop, ("identifier", "type", "is_readonly", "is_runtime", "is_registered"))
        signature = require_native_property(prop, name, kind, width, writing=writing, read=self._raw, pointer=self._pointer)
        key = (cls, name)
        class_name = next((identifier for identifier, native in self.classes.items() if native is cls), None)
        expected_fixed = NATIVE_FIXED.get(class_name, {}).get(name)
        if expected_fixed is not None and signature[6] != expected_fixed:
            raise refused("NATIVE_FIELD_FIXED_TYPE_CHANGED")
        if cls is self.classes.get("MeshPolygon") and name == "loop_total" and signature[5] is not True:
            raise refused("NATIVE_FACE_TOTAL_READONLY_REQUIRED")
        if key in self.properties and self.properties[key][1] != signature:
            raise refused("NATIVE_FIELD_METADATA_CHANGED")
        self.properties[key] = (prop, signature)
        return prop

    def function(self, class_name, method, schema):
        cls = self.classes[class_name]
        self._screen(cls, method)
        function = self._access("metadata_function_get", self._raw(self._rna(cls), "functions").get, method)
        if function is None:
            raise refused("NATIVE_FUNCTION_REQUIRED")
        self._metadata(function, ("parameters", "is_registered", "is_registered_optional"))
        for prop in self.items(self._raw(function, "parameters")):
            self._metadata(prop, ("identifier", "type", "is_runtime", "is_registered", "is_readonly",
                                  "is_required", "is_output"))
        signature = native_function_signature(function, schema, method, class_name=class_name, read=self._raw, pointer=self._pointer, items=self.items)
        key = (class_name, method)
        if key in self.functions and self.functions[key][1] != signature:
            raise refused("NATIVE_FUNCTION_METADATA_CHANGED")
        self.functions[key] = (function, signature)
        return function

    def get(self, owner, name, *, escrow=None, capture_role=None):
        if type(owner) is self.collection_type:
            if name != "active":
                raise refused("NATIVE_COLLECTION_FIELD_UNQUALIFIED")
            self.field(self.classes["LayerObjects"], "active", "POINTER")
            return self._access("collection_get:" + name, self.collection_type.__getattribute__, owner, name)
        cls = type(owner)
        if self.base not in cls.__mro__ or self._resolve(self._raw(self._rna(cls), "identifier")) is not cls:
            raise refused("NATIVE_OWNER_CLASS_REQUIRED")
        self._screen(cls, name)
        prop = self._access("metadata_property_get", self._raw(self._rna(cls), "properties").get, name)
        if prop is None:
            raise refused("NATIVE_OWNER_FIELD_REQUIRED")
        self._metadata(prop, ("identifier", "type", "is_runtime", "is_registered", "is_readonly"))
        if self._raw(prop, "is_runtime"):
            raise refused("NATIVE_OWNER_FIELD_REQUIRED")
        if escrow is not None:
            from .glb_stage_driver import _ReturnEscrow
            if type(escrow) is not _ReturnEscrow or name != "node_tree":
                raise refused("NATIVE_EMBEDDED_RETURN_ESCROW_REQUIRED")
        return self._access("get:" + name, self.getter, owner, name,
                            escrow=escrow, capture_role=capture_role)

    def prepare_set(self, owner, name):
        prop = self._access("metadata_property_get", self._raw(self._rna(type(owner)), "properties").get, name)
        if prop is None:
            raise refused("NATIVE_SETTER_REQUIRED")
        self._metadata(prop, ("identifier", "type", "is_runtime", "is_registered", "is_readonly"))
        self.field(type(owner), name, self._raw(prop, "type"),
                   self._raw(prop, "array_length") if self._raw(prop, "type") in {"BOOLEAN", "INT", "FLOAT"} else None, writing=True)

    def set(self, owner, name, value):
        self.prepare_set(owner, name)
        self._access("set:" + name, self.setter, owner, name, value)

    def callable(self, owner, class_name, method):
        self.function(class_name, method, NATIVE_FUNCTIONS[class_name][method])
        if type(owner) is self.collection_type:
            fn = self._access("collection_get:" + method, self.collection_type.__getattribute__, owner, method)
        elif self.base in type(owner).__mro__:
            fn = self._raw(owner, method)
        else:
            raise refused("NATIVE_CALL_OWNER_REQUIRED")
        if type(fn) is not self.function_type:
            raise refused("NATIVE_FUNCTION_WRAPPER_REQUIRED")
        return fn

    def selected(self):
        self._screen(self.classes["Context"], "selected_objects")
        # Source-reviewed CTX_data_get fallback, not a guessed RNA descriptor.
        values = self._raw(self.context, "selected_objects")
        if type(values) is not list or len(values) > 4096:
            raise refused("NATIVE_SELECTION_BUDGET")
        return tuple(values)

    def vector(self, owner, name, size):
        self.field(type(owner), name, "FLOAT", size)
        value = self.get(owner, name)
        if type(value) not in self.vector_types or self.length(value) != size:
            raise refused("NATIVE_VECTOR_REQUIRED")
        result = self.copy(value)
        if any(type(v) is not float or not math.isfinite(v) for v in result):
            raise refused("NATIVE_VECTOR_VALUES_REQUIRED")
        return result

    def bulk_read(self, collection, element_class_name, field, kind, width, count):
        """Bounded complete native collection copy, never a public read grant.

        The driver proves the held mesh/attribute owner and element class before
        entry. This helper qualifies the native collection/field/bulk descriptor
        and exact shape; its returned ordinary values cannot authorize writes.
        """
        from array import array
        from types import MethodDescriptorType

        if (type(collection) is not self.collection_type or type(count) is not int
                or count < 0 or type(width) is not int or not 0 <= width <= 65536
                or type(kind) is not str or kind not in {"FLOAT", "INT", "BOOLEAN"}
                or type(element_class_name) is not str or type(field) is not str):
            raise refused("NATIVE_BULK_READ_INPUT")
        if type(self) is not NativeBinding:
            raise refused("NATIVE_BULK_BINDING_REQUIRED")
        values_count = count * (width or 1)
        if values_count > 131072 or self.length(collection) != count:
            raise refused("NATIVE_BULK_READ_BUDGET_OR_SHAPE")
        if (type(self.foreach_read) is not MethodDescriptorType
                or self.foreach_read.__objclass__ is not self.collection_type
                or vars(self.collection_type).get("foreach_get") is not self.foreach_read):
            raise refused("NATIVE_FOREACH_GET_REQUIRED")
        if element_class_name not in self.classes:
            raise refused("NATIVE_BULK_READ_ELEMENT_CLASS")
        self.field(self.classes[element_class_name], field, kind, width)
        code = {"FLOAT": "f", "INT": "i", "BOOLEAN": "b"}[kind]
        values = array(code, [0]) * values_count
        if values.itemsize != {"FLOAT": 4, "INT": 4, "BOOLEAN": 1}[kind]:
            raise refused("NATIVE_BULK_READ_BUFFER_WIDTH")
        self._access("foreach_get:" + field, self.foreach_read, collection, field, values)
        if self.length(collection) != count:
            raise refused("NATIVE_BULK_READ_SHAPE_CHANGED")
        if kind == "FLOAT" and any(not math.isfinite(value) for value in values):
            raise refused("NATIVE_BULK_READ_NONFINITE")
        if kind == "BOOLEAN":
            if any(value not in (0, 1) for value in values):
                raise refused("NATIVE_BULK_READ_BOOLEAN_VALUE")
            return tuple(bool(value) for value in values)
        return tuple(values)

    def check(self):
        import inspect
        import sys
        import threading
        if (sys.modules.get("bpy") is not self.bpy or vars(self.bpy).get("types") is not self.types
                or vars(self.bpy).get("app") is not self.app or vars(self.bpy).get("data") is not self.main
                or vars(self.bpy).get("context") is not self.context
                or threading.get_ident() != self.thread or threading.current_thread() is not self.thread_object
                or tuple(self._access("app:version", getattr, self.app, "version")) != self.version_tuple or self._access("app:build_hash", getattr, self.app, "build_hash") != self.build_hash
                or self._access("app:build_type", getattr, self.app, "build_type") != b"Release" or self._pointer(self.main) != self.main_pointer
                or vars(self.types).get("__getattr__") is not self.resolver
                or vars(self.base).get("__getattribute__") is not self.getter
                or vars(self.base).get("__setattr__") is not self.setter
                or vars(self.base).get("as_pointer") is not self.pointer
                or vars(self.collection_type).get("foreach_set") is not self.foreach
                or vars(self.collection_type).get("foreach_get") is not self.foreach_read
                or any(left is not right for left, right in zip(self._origin,
                    (self.bpy, self.app, self.types, self.resolver, self.base, self.getter, self.setter,
                     self.pointer, self.collection_type, self.function_type, self.array_type, self.foreach, self.foreach_read,
                     self.vector_types, self.matrix_type, self.mathutils), strict=True))):
            raise refused("NATIVE_BINDING_LIFETIME_CHANGED")
        self._qualify_tree_family()
        for name, cls in tuple(self.classes.items()):
            if self._resolve(name) is not cls:
                raise refused("NATIVE_CLASS_CHANGED")
        for (cls, name), descriptor in tuple(self.class_namespaces.items()):
            if inspect.getattr_static(cls, name, None) is not descriptor:
                raise refused("NATIVE_FIELD_BINDING_CHANGED")
        for (cls, name), (_prop, signature) in tuple(self.properties.items()):
            current = self._access("metadata_property_get", self._raw(self._rna(cls), "properties").get, name)
            if current is None or native_property_signature(current, read=self._raw, pointer=self._pointer) != signature:
                raise refused("NATIVE_FIELD_METADATA_CHANGED")
        for (class_name, method), (_fn, _signature) in tuple(self.functions.items()):
            self.function(class_name, method, NATIVE_FUNCTIONS[class_name][method])
        if (self.get(self.get(self.context, "scene"), "session_uid") != self.scene_uid
                or self._pointer(self.get(self.context, "scene")) != self.scene_pointer
                or self._pointer(self.get(self.context, "view_layer")) != self.layer_pointer):
            raise refused("NATIVE_CONTEXT_OWNER_CHANGED")

    def report(self):
        # Pure cached observations only: no new RNA getters in a failure report.
        return {"version": list(self.version_tuple), "build_hash": self.build_hash.decode("ascii"),
                "main_pointer": self.main_pointer,
                "classes": sorted(self.classes),
                "properties": [[cls.__name__, name, list(signature)]
                               for (cls, name), (_prop, signature) in self.properties.items()],
                "functions": [[name, method, plain(signature)]
                              for (name, method), (_fn, signature) in self.functions.items()],
                "stock_node_tree_family": [list(row) for row in self._tree_family],
                "node_tree_namespace_profile": "EXACT_SHIPPED_FOUR_FAMILY_NO_EXTENSION_SUBCLASSES",
                "hostile_interpreter_or_custom_C_extensions_qualified": False,
                "authority": "internal binding only; no artist Runtime grant"}


# These plain Python identities are checked without touching Blender before
# every Runtime native access. They complement the immutable stock C slots.
from types import FunctionType as _FunctionType  # noqa: E402

_BINDING_METHOD_ORIGINS = tuple((name, fn, fn.__code__) for name, fn in vars(NativeBinding).items()
                                if type(fn) is _FunctionType)
