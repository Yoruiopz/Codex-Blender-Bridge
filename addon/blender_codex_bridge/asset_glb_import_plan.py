"""Immutable numeric plans for a separately qualified structured GLB backend.

This module accepts complete bytes, never paths or Blender objects. It strengthens
rather than replaces the existing GLB preflight. It does not authorize, allocate,
import, save, restore or register anything in Blender.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import TypeAlias

from .asset_glb_preflight import LOSSES, _node_matrix, _object, preflight_glb
from .errors import BridgeError, ErrorCode, invalid_argument

PROFILE = "STATIC_INDEXED_GLB_PLAN_1"
MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 32
MAX_MESHES = 16
MAX_MATERIALS = 16  # Includes an implicit glTF default material when needed.
MAX_PRIMITIVES = 64
MAX_VERTICES = 8192
MAX_TRIANGLES = 8192
MAX_SCALARS = 131_072
MAX_LABEL_BYTES = 8192
MAX_CANONICAL_BYTES = 4 * 1024 * 1024
UV_LOSS = "UV_ORIGIN_CONVERSION"
NORMAL_LOSS = "NORMAL_STORAGE_QUANTIZATION"
AUTO_NORMAL_LOSS = "MISSING_NORMALS_USE_GEOMETRIC_AUTO"
CORE_LOSSES = tuple(LOSSES)

Vec2: TypeAlias = tuple[float, float]
Vec3: TypeAlias = tuple[float, float, float]
Vec4: TypeAlias = tuple[float, float, float, float]
Triangle: TypeAlias = tuple[int, int, int]
Matrix: TypeAlias = tuple[Vec4, Vec4, Vec4, Vec4]


@dataclass(frozen=True, slots=True)
class MaterialPlan:
    source_index: int | None
    name: str | None
    base_color: Vec4
    metallic: float
    roughness: float
    alpha_mode: str
    alpha_cutoff: float
    double_sided: bool


@dataclass(frozen=True, slots=True)
class PrimitivePlan:
    source_index: int
    material_index: int  # Index in the plan, including its explicit default.
    source_accessors: tuple[tuple[str, int], ...]
    positions: tuple[Vec3, ...]
    triangles: tuple[Triangle, ...]
    normals: tuple[Vec3, ...] | None
    texcoords: tuple[Vec2, ...] | None


@dataclass(frozen=True, slots=True)
class MeshPlan:
    source_index: int
    name: str | None
    primitives: tuple[PrimitivePlan, ...]


@dataclass(frozen=True, slots=True)
class NodePlan:
    source_index: int
    name: str | None
    parent_index: int | None
    children: tuple[int, ...]
    mesh_index: int | None
    local_matrix: Matrix
    world_matrix: Matrix


@dataclass(frozen=True, slots=True)
class ConversionRequirements:
    """Definition/corner-write counts, never native or permission evidence."""
    custom_normal_meshes: int
    authored_normal_primitives: int
    authored_normal_corners: int
    geometric_auto_primitives: int
    geometric_auto_corners: int
    missing_uv_zero_fill_corners: int


@dataclass(frozen=True, slots=True)
class GLBImportPlan:
    profile: str
    coordinate_unit: str
    source_sha256: str
    source_bytes: int
    nodes: tuple[NodePlan, ...]
    roots: tuple[int, ...]
    meshes: tuple[MeshPlan, ...]
    materials: tuple[MaterialPlan, ...]
    source_labels: tuple[tuple[str, str], ...]
    vertex_count: int
    triangle_count: int
    instance_vertex_count: int
    instance_triangle_count: int
    dependencies: tuple[str, ...]
    conversion_requirements: ConversionRequirements
    required_accepted_losses: tuple[str, ...]
    normalized_sha256: str

    def canonical_bytes(self) -> bytes:
        """Bounded JSON of numeric intent, excluding the hash of that JSON."""
        value = asdict(self)
        del value["normalized_sha256"]
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf8")
        if len(encoded) > MAX_CANONICAL_BYTES:
            raise invalid_argument("Structured GLB plan exceeds its canonical byte budget.")
        return encoded

    def summary(self) -> dict:
        """Compact evidence only; not a public tool result or mutation authority."""
        validate_conversion_requirements(self)
        conversion = self.conversion_requirements
        return {
            "profile": self.profile,
            "coordinate_unit": self.coordinate_unit,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "normalized_sha256": self.normalized_sha256,
            "nodes": len(self.nodes),
            "meshes": len(self.meshes),
            "materials": len(self.materials),
            "vertices": self.vertex_count,
            "triangles": self.triangle_count,
            "instance_vertices": self.instance_vertex_count,
            "instance_triangles": self.instance_triangle_count,
            "dependencies": list(self.dependencies),
            "required_accepted_losses": list(self.required_accepted_losses),
            "axis_basis": "GLTF_Y_UP_TO_BLENDER_Z_UP: (x, y, z) -> (x, -z, y)",
            "axis_basis_determinant": 1,
            "uv_convention": "(u, v) -> Float32(u, 1-v)",
            "normal_conversion": {
                "count_scope": "MESH_DEFINITION_CORNER_WRITES_NOT_INSTANCES",
                "custom_normal_meshes": conversion.custom_normal_meshes,
                "authored_normal_primitives": conversion.authored_normal_primitives,
                "authored_normal_corners": conversion.authored_normal_corners,
                "geometric_auto_primitives": conversion.geometric_auto_primitives,
                "geometric_auto_corners": conversion.geometric_auto_corners,
                "native_decoded_component_error_bound": 5e-4,
                "decoded_bound_policy": "OBSERVED_NATIVE_POSTCONDITION_NOT_CAS_TOLERANCE",
                "input_normal_bits_preserved": False,
                "future_encoded_short_selection_sharp_edge_CAS": "EXACT",
            },
            "missing_uv_zero_fill_corners": conversion.missing_uv_zero_fill_corners,
            "mixed_uv_zero_fill_public_registration_gate": "OPEN" if conversion.missing_uv_zero_fill_corners else "NOT_APPLICABLE",
            "matrix_policy": "Float64 local/world similarity transforms; no native decomposition",
            "native_backend_qualified": False,
            "native_permission_or_checkpoint_verified": False,
        }


def conversion_requirements(meshes: tuple[MeshPlan, ...]) -> tuple[ConversionRequirements, tuple[str, ...]]:
    """Derive exact structured-only conversions from immutable decoded streams.

    Missing normal corners count only when their mesh invokes the custom-normal
    setter. A wholly absent NORMAL mesh uses no setter and adds no storage loss.
    Mixed UV zero fill is measured but remains a separate public-registration
    gate; the UV token is not a new authorization for that missing-input policy.
    """
    if type(meshes) is not tuple or not 1 <= len(meshes) <= MAX_MESHES:
        raise invalid_argument("Conversion requirements need exact bounded mesh plans.")
    custom_meshes = authored_primitives = authored_corners = auto_primitives = auto_corners = missing_uv = 0
    has_uv = False
    primitive_total = corner_total = vertex_total = 0
    for mesh in meshes:
        if type(mesh) is not MeshPlan or type(mesh.primitives) is not tuple or not 1 <= len(mesh.primitives) <= MAX_PRIMITIVES:
            raise invalid_argument("Conversion requirements need exact bounded primitive plans.")
        primitive_total += len(mesh.primitives)
        for primitive in mesh.primitives:
            if (type(primitive) is not PrimitivePlan or type(primitive.positions) is not tuple
                    or not 1 <= len(primitive.positions) <= MAX_VERTICES
                    or type(primitive.triangles) is not tuple or not 1 <= len(primitive.triangles) <= MAX_TRIANGLES
                    or (primitive.normals is not None and (type(primitive.normals) is not tuple
                        or len(primitive.normals) != len(primitive.positions)))
                    or (primitive.texcoords is not None and (type(primitive.texcoords) is not tuple
                        or len(primitive.texcoords) != len(primitive.positions)))):
                raise invalid_argument("Conversion requirements need exact decoded stream shapes.")
            vertex_total += len(primitive.positions)
            corner_total += 3 * len(primitive.triangles)
        normal_mesh = any(primitive.normals is not None for primitive in mesh.primitives)
        uv_mesh = any(primitive.texcoords is not None for primitive in mesh.primitives)
        custom_meshes += int(normal_mesh)
        has_uv |= uv_mesh
        for primitive in mesh.primitives:
            corners = 3 * len(primitive.triangles)
            if primitive.normals is not None:
                authored_primitives += 1
                authored_corners += corners
            elif normal_mesh:
                auto_primitives += 1
                auto_corners += corners
            if uv_mesh and primitive.texcoords is None:
                missing_uv += corners
    if (primitive_total > MAX_PRIMITIVES or vertex_total > MAX_VERTICES or corner_total > 3 * MAX_TRIANGLES
            or authored_primitives + auto_primitives > MAX_PRIMITIVES
            or authored_corners + auto_corners > 3 * MAX_TRIANGLES or missing_uv > 3 * MAX_TRIANGLES):
        raise invalid_argument("Conversion requirements exceed the complete plan budget.")
    conversion = ConversionRequirements(custom_meshes, authored_primitives, authored_corners,
                                        auto_primitives, auto_corners, missing_uv)
    losses = (*CORE_LOSSES, *((UV_LOSS,) if has_uv else ()),
              *((NORMAL_LOSS,) if custom_meshes else ()), *((AUTO_NORMAL_LOSS,) if auto_corners else ()))
    return conversion, losses


def validate_conversion_requirements(plan: GLBImportPlan) -> None:
    """A matching hash cannot bless forged counters or a weaker consent list."""
    if type(plan) is not GLBImportPlan:
        raise invalid_argument("Conversion requirements need an exact structured GLB plan.")
    expected, losses = conversion_requirements(plan.meshes)
    actual = plan.conversion_requirements
    if (type(actual) is not ConversionRequirements
            or any(type(value) is not int or value < 0 for value in (
                actual.custom_normal_meshes, actual.authored_normal_primitives, actual.authored_normal_corners,
                actual.geometric_auto_primitives, actual.geometric_auto_corners, actual.missing_uv_zero_fill_corners))
            or actual != expected or type(plan.required_accepted_losses) is not tuple
            or any(type(value) is not str for value in plan.required_accepted_losses)
            or plan.required_accepted_losses != losses):
        raise invalid_argument("Structured GLB conversion counts or exact ordered loss policy changed.")


def _unsupported(message: str) -> None:
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, message)


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _basis(vector: tuple[float, ...]) -> Vec3:
    # Signed permutation, not arithmetic matrix multiplication: source Float32
    # bits (including zero sign) survive apart from the explicit sign reversal.
    return vector[0], -vector[2], vector[1]


def _matrix_basis(matrix: list[list[float]]) -> Matrix:
    rows = ((0, 1), (2, -1), (1, 1), (3, 1))
    return tuple(  # type: ignore[return-value]
        tuple(sign * other_sign * float(matrix[row][column]) for column, other_sign in rows)
        for row, sign in rows
    )


def _multiply(first: list[list[float]], second: list[list[float]]) -> list[list[float]]:
    # Explicit left fold avoids Python 3.12's changed compensated float sum.
    result = [[0.0] * 4 for _ in range(4)]
    for row in range(4):
        for column in range(4):
            total = 0.0
            for inner in range(4):
                total = total + first[row][inner] * second[inner][column]
            if not math.isfinite(total) or abs(total) > 1e9:
                raise invalid_argument("Structured GLB world transform exceeds its numeric budget.")
            result[row][column] = total
    return result


def _text_bytes(value: str) -> int:
    if type(value) is not str:
        raise invalid_argument("GLB source labels must be explicit strings.")
    try:
        return len(value.encode("utf8"))
    except UnicodeError as error:
        raise invalid_argument("GLB source labels must contain valid Unicode scalar values.") from error


def _name(record: dict) -> str | None:
    if "name" not in record:
        return None
    value = record["name"]
    if _text_bytes(value) > 59:
        _unsupported("Structured GLB ID names require strings within 59 UTF-8 bytes.")
    return value


def _labels(manifest: dict) -> tuple[tuple[str, str], ...]:
    result = []
    for key in ("generator", "copyright"):
        if key in manifest["asset"]:
            result.append(("asset." + key, manifest["asset"][key]))
    for family in ("scenes", "nodes", "meshes", "materials", "buffers", "bufferViews", "accessors"):
        for index, record in enumerate(manifest.get(family, [])):
            if "name" in record:
                result.append((f"{family}[{index}].name", record["name"]))
    if sum(_text_bytes(value) for _, value in result) > MAX_LABEL_BYTES:
        raise invalid_argument("Structured GLB source labels exceed their byte budget.")
    return tuple(result)


def _profile(manifest: dict, summary: dict) -> tuple[int | None, bool]:
    for family in ("images", "textures", "samplers"):
        if manifest.get(family):
            _unsupported("Structured GLB image/texture/sampler reconstruction is not implemented.")
    nodes, meshes, materials = (manifest.get(key, []) for key in ("nodes", "meshes", "materials"))
    if not meshes:
        _unsupported("This structured GLB profile requires a referenced triangle mesh.")
    for values, maximum in ((nodes, MAX_NODES), (meshes, MAX_MESHES), (materials, MAX_MATERIALS)):
        if len(values) > maximum:
            raise invalid_argument("Structured GLB resource inventory exceeds its plan budget.")
    if (summary["instance_vertices"] > MAX_VERTICES or summary["vertices"] > MAX_VERTICES
            or summary["instance_triangles"] > MAX_TRIANGLES or summary["triangles"] > MAX_TRIANGLES):
        raise invalid_argument("Structured GLB geometry/instance inventory exceeds its plan budget.")
    used_meshes = {node["mesh"] for node in nodes if "mesh" in node}
    if used_meshes != set(range(len(meshes))):
        _unsupported("Unused GLB meshes need an explicit resource-selection contract.")
    used_materials, primitive_count, default, uv = set(), 0, False, False
    for node in nodes:
        _name(node)
        if "matrix" in node and tuple(node["matrix"][index] for index in (3, 7, 11, 15)) != (0, 0, 0, 1):
            _unsupported("Structured GLB matrices must be exactly affine.")
    for mesh in meshes:
        _name(mesh)
        for primitive in mesh["primitives"]:
            primitive_count += 1
            if primitive_count > MAX_PRIMITIVES:
                raise invalid_argument("Structured GLB primitive budget exceeded.")
            if "indices" not in primitive:
                _unsupported("Structured GLB currently requires explicit triangle indices.")
            if set(primitive["attributes"]) - {"POSITION", "NORMAL", "TEXCOORD_0"}:
                _unsupported("Structured GLB tangents/additional vertex attributes are not implemented.")
            uv |= "TEXCOORD_0" in primitive["attributes"]
            if "material" in primitive:
                used_materials.add(primitive["material"])
            else:
                default = True
    if used_materials != set(range(len(materials))):
        _unsupported("Unused GLB materials need an explicit resource-selection contract.")
    if len(materials) + int(default) > MAX_MATERIALS:
        raise invalid_argument("Structured GLB material budget includes the implicit default.")
    scalars = 32 * len(nodes) + 8 * (len(materials) + int(default))
    for mesh in meshes:
        for primitive in mesh["primitives"]:
            attributes = primitive["attributes"]
            count = manifest["accessors"][attributes["POSITION"]]["count"]
            index_count = manifest["accessors"][primitive["indices"]]["count"]
            scalars += count * (3 + (3 if "NORMAL" in attributes else 0) + (2 if "TEXCOORD_0" in attributes else 0)) + index_count
    if scalars > MAX_SCALARS:
        raise invalid_argument("Structured GLB numeric scalar budget exceeded.")
    for material in materials:
        _name(material)
    return len(materials) if default else None, uv


def _accessor(manifest: dict, binary: bytes, index: int, check: Callable[[], None]):
    """Decode only the layout already accepted by the unchanged core preflight."""
    item = manifest["accessors"][index]
    view = manifest["bufferViews"][item["bufferView"]]
    size, code = {5121: (1, "B"), 5123: (2, "H"), 5125: (4, "I"), 5126: (4, "f")}[item["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[item["type"]]
    stride = view.get("byteStride", size * width)
    start = view.get("byteOffset", 0) + item.get("byteOffset", 0)
    layout = "<" + code * width
    for number in range(item["count"]):
        if number % 256 == 0:
            check()
        yield struct.unpack_from(layout, binary, start + number * stride)


def _materials(records: list[dict], default: int | None) -> tuple[MaterialPlan, ...]:
    result = []
    for index, record in enumerate(records + ([{}] if default is not None else [])):
        pbr = record.get("pbrMetallicRoughness", {})
        result.append(MaterialPlan(
            index if index < len(records) else None, _name(record),
            tuple(float(value) for value in pbr.get("baseColorFactor", (1, 1, 1, 1))),
            float(pbr.get("metallicFactor", 1)), float(pbr.get("roughnessFactor", 1)),
            record.get("alphaMode", "OPAQUE"), float(record.get("alphaCutoff", .5)),
            record.get("doubleSided", False),
        ))
    return tuple(result)


def _nodes(records: list[dict], roots: tuple[int, ...], check: Callable[[], None]) -> tuple[NodePlan, ...]:
    result: list[NodePlan | None] = [None] * len(records)

    def visit(index: int, parent: int | None, parent_matrix: list[list[float]] | None):
        check()
        record = records[index]
        local = _node_matrix(record)
        world = local if parent_matrix is None else _multiply(parent_matrix, local)
        children = tuple(record.get("children", ()))
        result[index] = NodePlan(index, _name(record), parent, children, record.get("mesh"),
                                 _matrix_basis(local), _matrix_basis(world))
        for child in children:
            visit(child, index, world)

    for root in roots:
        visit(root, None, None)
    # Preflight proves every node is reached once, including non-mesh parents.
    assert all(node is not None for node in result)
    return tuple(result)  # type: ignore[return-value]


def plan_glb(payload: bytes, check: Callable[[], None] = lambda: None) -> GLBImportPlan:
    """Freeze a bounded numeric plan; the callback signals lifecycle, not consent."""
    if type(payload) is not bytes or not 28 <= len(payload) <= MAX_BYTES:
        raise invalid_argument("Structured GLB requires exact immutable bytes within 8 MiB.")
    check()
    summary = preflight_glb(payload, check)
    json_length = struct.unpack_from("<I", payload, 12)[0]
    manifest = json.loads(payload[20:20 + json_length], object_pairs_hook=_object)
    binary = payload[28 + json_length:]
    default, _has_uv = _profile(manifest, summary)
    labels = _labels(manifest)
    meshes = []
    for mesh_index, record in enumerate(manifest["meshes"]):
        primitives = []
        for primitive_index, primitive in enumerate(record["primitives"]):
            attributes = primitive["attributes"]
            positions = tuple(_basis(value) for value in _accessor(manifest, binary, attributes["POSITION"], check))
            indices = tuple(value[0] for value in _accessor(manifest, binary, primitive["indices"], check))
            triangles = tuple(tuple(indices[offset:offset + 3]) for offset in range(0, len(indices), 3))
            for triangle_index, (first, second, third) in enumerate(triangles):
                if triangle_index % 256 == 0:
                    check()
                if len({first, second, third}) != 3:
                    _unsupported("Degenerate GLB triangle indices need an explicit repair contract.")
                a, b, c = positions[first], positions[second], positions[third]
                u, v = tuple(b[i] - a[i] for i in range(3)), tuple(c[i] - a[i] for i in range(3))
                if all(value == 0 for value in (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])):
                    _unsupported("Zero-area GLB triangles need an explicit repair contract.")
            normals = None
            if "NORMAL" in attributes:
                rows = tuple(_accessor(manifest, binary, attributes["NORMAL"], check))
                if any(abs(row[0] * row[0] + row[1] * row[1] + row[2] * row[2] - 1) > 2e-5 for row in rows):
                    raise invalid_argument("GLB normals must already be unit vectors; no renormalization is implicit.")
                normals = tuple(_basis(row) for row in rows)
            texcoords = None
            if "TEXCOORD_0" in attributes:
                texcoords = tuple((row[0], _f32(1.0 - row[1])) for row in _accessor(manifest, binary, attributes["TEXCOORD_0"], check))
            primitives.append(PrimitivePlan(
                primitive_index, primitive.get("material", default),
                tuple(sorted((*attributes.items(), ("indices", primitive["indices"])))),
                positions, triangles, normals, texcoords,
            ))
        meshes.append(MeshPlan(mesh_index, _name(record), tuple(primitives)))
    roots = tuple(manifest["scenes"][0]["nodes"])
    conversion, losses = conversion_requirements(tuple(meshes))
    plan = GLBImportPlan(
        PROFILE, "METERS", hashlib.sha256(payload).hexdigest(), len(payload),
        _nodes(manifest["nodes"], roots, check), roots, tuple(meshes),
        _materials(manifest.get("materials", []), default), labels,
        summary["vertices"], summary["triangles"], summary["instance_vertices"], summary["instance_triangles"],
        (), conversion, losses, "",
    )
    canonical = plan.canonical_bytes()
    check()
    return replace(plan, normalized_sha256=hashlib.sha256(canonical).hexdigest())


def require_loss_acceptance(plan: GLBImportPlan, accepted_losses: list[str]) -> None:
    """Validate the exact preview list; this grants no Blender permissions."""
    validate_conversion_requirements(plan)
    if (type(accepted_losses) is not list or any(type(value) is not str for value in accepted_losses)
            or accepted_losses != list(plan.required_accepted_losses)):
        raise invalid_argument("accepted_losses must repeat the structured GLB plan list exactly.")
