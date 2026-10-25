from __future__ import annotations

import copy
import hashlib
import importlib
import json
import struct
import zlib
from dataclasses import FrozenInstanceError

import pytest


def glb(manifest, binary, *, raw_json=None):
    text = json.dumps(manifest, separators=(",", ":")).encode() if raw_json is None else raw_json
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (b"glTF" + struct.pack("<II", 2, 28 + len(text) + len(binary))
            + struct.pack("<II", len(text), 0x4E4F534A) + text
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def triangle(*, component=5123, normals=False, uv=False, interleaved=False):
    manifest = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
                "nodes": [{"mesh": 0}], "meshes": [], "buffers": [], "bufferViews": [],
                "accessors": []}
    binary = bytearray()

    def add(rows, kind, code, component_type):
        binary.extend(b"\0" * (-len(binary) % 4))
        start = len(binary)
        for row in rows:
            binary.extend(struct.pack("<" + code * len(row), *row))
        view = len(manifest["bufferViews"])
        manifest["bufferViews"].append({"buffer": 0, "byteOffset": start, "byteLength": len(binary) - start})
        index = len(manifest["accessors"])
        manifest["accessors"].append({"bufferView": view, "componentType": component_type,
                                      "count": len(rows), "type": kind})
        return index

    positions = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))
    normal_rows = ((0., 0., 1.),) * 3
    uv_rows = ((0., 0.), (1., .25), (0., 1.))
    if interleaved:
        for position, normal, coord in zip(positions, normal_rows, uv_rows, strict=True):
            binary.extend(struct.pack("<8f", *position, *normal, *coord))
        manifest["bufferViews"].append({"buffer": 0, "byteLength": 96, "byteStride": 32})
        attributes = {}
        for semantic, kind, offset in (("POSITION", "VEC3", 0), ("NORMAL", "VEC3", 12), ("TEXCOORD_0", "VEC2", 24)):
            attributes[semantic] = len(manifest["accessors"])
            manifest["accessors"].append({"bufferView": 0, "componentType": 5126,
                                          "count": 3, "type": kind, "byteOffset": offset})
    else:
        attributes = {"POSITION": add(positions, "VEC3", "f", 5126)}
        if normals:
            attributes["NORMAL"] = add(normal_rows, "VEC3", "f", 5126)
        if uv:
            attributes["TEXCOORD_0"] = add(uv_rows, "VEC2", "f", 5126)
    indices = add(((0,), (1,), (2,)), "SCALAR", {5121: "B", 5123: "H", 5125: "I"}[component], component)
    manifest["meshes"] = [{"primitives": [{"attributes": attributes, "indices": indices}]}]
    manifest["buffers"] = [{"byteLength": len(binary)}]
    return manifest, bytes(binary)


def append_accessor(manifest, binary, rows, kind):
    binary += b"\0" * (-len(binary) % 4)
    start = len(binary)
    for row in rows:
        binary += struct.pack("<" + "f" * len(row), *row)
    view = len(manifest["bufferViews"])
    manifest["bufferViews"].append({"buffer": 0, "byteOffset": start, "byteLength": len(binary) - start})
    index = len(manifest["accessors"])
    manifest["accessors"].append({"bufferView": view, "componentType": 5126, "count": len(rows), "type": kind})
    manifest["buffers"][0]["byteLength"] = len(binary)
    return index, binary


def embedded_image(manifest, binary):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\0\x10\x20\x30\xff")) + chunk(b"IEND", b""))
    binary += b"\0" * (-len(binary) % 4)
    view = len(manifest["bufferViews"])
    manifest["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(png)})
    binary += png
    manifest["buffers"][0]["byteLength"] = len(binary)
    manifest["images"] = [{"bufferView": view, "mimeType": "image/png"}]
    return binary


@pytest.fixture
def module(addon_package):
    return importlib.import_module(addon_package + ".asset_glb_import_plan")


def test_complete_numeric_plan_has_explicit_default_material_and_source_binding(module):
    manifest, binary = triangle()
    source = glb(manifest, binary)
    plan = module.plan_glb(source)
    primitive = plan.meshes[0].primitives[0]
    assert primitive.positions == ((0., -0., 0.), (1., -0., 0.), (0., -0., 1.))
    assert primitive.triangles == ((0, 1, 2),) and primitive.material_index == 0
    assert primitive.normals is None and primitive.texcoords is None
    assert plan.materials[0].source_index is None
    assert plan.materials[0].base_color == (1., 1., 1., 1.)
    assert plan.materials[0].metallic == plan.materials[0].roughness == 1.
    assert plan.source_sha256 == hashlib.sha256(source).hexdigest()
    assert plan.normalized_sha256 == hashlib.sha256(plan.canonical_bytes()).hexdigest()
    assert plan.vertex_count == plan.instance_vertex_count == 3
    assert plan.triangle_count == plan.instance_triangle_count == 1
    assert plan.dependencies == () and plan.roots == (0,)
    assert plan.coordinate_unit == plan.summary()["coordinate_unit"] == "METERS"
    assert plan.summary()["native_backend_qualified"] is False
    assert plan.summary()["native_permission_or_checkpoint_verified"] is False


@pytest.mark.parametrize("component", [5121, 5123, 5125])
@pytest.mark.parametrize("interleaved", [False, True])
def test_admitted_unsigned_indices_and_interleaved_attributes_are_decoded(module, component, interleaved):
    manifest, binary = triangle(component=component, normals=True, uv=True, interleaved=interleaved)
    plan = module.plan_glb(glb(manifest, binary))
    primitive = plan.meshes[0].primitives[0]
    assert primitive.triangles == ((0, 1, 2),)
    assert primitive.normals == ((0., -1., 0.),) * 3
    assert primitive.texcoords == ((0., 1.), (1., .75), (0., 0.))
    assert plan.required_accepted_losses[-1] == module.UV_LOSS
    # X cross Z is -Y: the basis has determinant +1 and preserves triangle winding.
    first, second, third = primitive.positions
    u, v = [second[i] - first[i] for i in range(3)], [third[i] - first[i] for i in range(3)]
    assert (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]) == primitive.normals[0]


def test_signed_zero_geometry_and_normal_bits_survive_signed_permutation(module):
    manifest, binary = triangle(normals=True)
    binary = struct.pack("<f", -0.) + binary[4:]
    plan = module.plan_glb(glb(manifest, binary))
    point = plan.meshes[0].primitives[0].positions[0]
    assert struct.pack("<3f", *point).hex() == "000000800000008000000000"


def test_uv_origin_rounding_is_f32_and_declared_as_a_required_loss(module):
    manifest, binary = triangle(uv=True)
    accessor = manifest["accessors"][1]
    offset = manifest["bufferViews"][accessor["bufferView"]]["byteOffset"]
    data = bytearray(binary)
    struct.pack_into("<2f", data, offset, .2, .1)
    plan = module.plan_glb(glb(manifest, bytes(data)))
    uv = plan.meshes[0].primitives[0].texcoords[0]
    assert struct.pack("<2f", *uv).hex() == "cdcc4c3e6666663f"
    assert module.UV_LOSS in plan.required_accepted_losses


def test_pbr_alpha_double_sided_and_source_labels_are_retained_without_substitution(module):
    manifest, binary = triangle()
    manifest["materials"] = [{"name": "Source Material", "pbrMetallicRoughness": {
        "baseColorFactor": [.2, .3, .4, .8], "metallicFactor": .125, "roughnessFactor": .75},
        "alphaMode": "BLEND", "alphaCutoff": .35, "doubleSided": True}]
    manifest["meshes"][0]["primitives"][0]["material"] = 0
    manifest["asset"].update(generator="Source exporter", copyright="Source author")
    manifest["nodes"][0]["name"] = "Source Object"
    manifest["meshes"][0]["name"] = "Source Mesh"
    manifest["accessors"][0]["name"] = "Position stream"
    plan = module.plan_glb(glb(manifest, binary))
    material = plan.materials[0]
    assert material.source_index == 0 and material.base_color == (.2, .3, .4, .8)
    assert (material.metallic, material.roughness, material.alpha_mode, material.alpha_cutoff,
            material.double_sided) == (.125, .75, "BLEND", .35, True)
    assert ("asset.copyright", "Source author") in plan.source_labels
    assert ("accessors[0].name", "Position stream") in plan.source_labels


def test_hierarchy_similarity_transform_has_independent_numeric_expectations(module):
    manifest, binary = triangle()
    manifest["nodes"] = [
        {"children": [1], "translation": [1., 2., 3.], "rotation": [0., 0., 1., 0.], "scale": [2., 3., 4.]},
        {"mesh": 0, "translation": [1., -2., 3.], "scale": [-1., 2., .5]},
    ]
    plan = module.plan_glb(glb(manifest, binary))
    root, child = plan.nodes
    assert root.local_matrix == ((-2., 0., 0., 1.), (0., 4., 0., -3.), (0., 0., -3., 2.), (0., 0., 0., 1.))
    assert child.local_matrix == ((-1., 0., 0., 1.), (0., .5, 0., -3.), (0., 0., 2., -2.), (0., 0., 0., 1.))
    assert child.world_matrix == ((2., 0., 0., -1.), (0., 2., 0., -15.), (0., 0., -6., 8.), (0., 0., 0., 1.))
    assert child.parent_index == 0 and root.children == (1,) and child.children == ()


def test_column_major_matrix_and_referenced_mesh_instances_are_retained(module):
    manifest, binary = triangle()
    manifest["nodes"] = [{"mesh": 0, "matrix": [0., 3., 0., 0., -2., 0., 0., 0., 0., 0., 4., 0., 4., 5., 6., 1.]},
                         {"mesh": 0, "translation": [1., 2., 3.]}]
    manifest["scenes"][0]["nodes"] = [0, 1]
    plan = module.plan_glb(glb(manifest, binary))
    assert len(plan.meshes) == 1 and plan.instance_vertex_count == 6 and plan.instance_triangle_count == 2
    assert plan.nodes[0].local_matrix == ((0., 0., -2., 4.), (0., 4., 0., -6.), (3., 0., 0., 5.), (0., 0., 0., 1.))
    assert plan.nodes[0].mesh_index == plan.nodes[1].mesh_index == 0


@pytest.mark.parametrize("kind", ["bytearray", "memoryview", "path", "subclass"])
def test_only_exact_immutable_bytes_enter_the_validator(module, monkeypatch, kind):
    manifest, binary = triangle()
    source = glb(manifest, binary)
    class BytesSubclass(bytes):
        pass
    value = {"bytearray": bytearray(source), "memoryview": memoryview(source),
             "path": "/tmp/example.glb", "subclass": BytesSubclass(source)}[kind]
    monkeypatch.setattr(module, "preflight_glb", lambda *_args: pytest.fail("Invalid intake reached decoder"))
    with pytest.raises(module.BridgeError):
        module.plan_glb(value)


def test_plan_is_deeply_immutable_and_does_not_retain_caller_manifest(module):
    manifest, binary = triangle()
    source = glb(manifest, binary)
    plan = module.plan_glb(source, check=lambda: manifest["nodes"][0].update(name="Caller mutation"))
    assert plan.nodes[0].name is None
    with pytest.raises(FrozenInstanceError):
        plan.nodes[0].parent_index = 12
    with pytest.raises(TypeError):
        plan.meshes[0].primitives[0].positions[0][0] = 12.
    assert plan.normalized_sha256 == hashlib.sha256(plan.canonical_bytes()).hexdigest()


@pytest.mark.parametrize("kind", ["external_uri", "data_uri", "extensions", "extras", "animations", "skins",
                                  "colors", "sparse", "normalized", "tangents", "nonindexed",
                                  "unused_mesh", "unused_material", "sampler", "image", "texture"])
def test_unsupported_content_is_refused_instead_of_silently_discarded(module, kind):
    manifest, binary = triangle()
    primitive = manifest["meshes"][0]["primitives"][0]
    if kind in ("external_uri", "data_uri"):
        manifest["buffers"][0]["uri"] = "../outside.bin" if kind == "external_uri" else "data:application/octet-stream;base64,AAAA"
    elif kind in ("extensions", "extras", "animations", "skins"):
        manifest[kind] = [] if kind in ("animations", "skins") else {}
    elif kind == "colors":
        primitive["attributes"]["COLOR_0"] = 0
    elif kind in ("sparse", "normalized"):
        manifest["accessors"][0][kind] = {} if kind == "sparse" else False
    elif kind == "tangents":
        index, binary = append_accessor(manifest, binary, ((1., 0., 0., 1.),) * 3, "VEC4")
        primitive["attributes"]["TANGENT"] = index
    elif kind == "nonindexed":
        del primitive["indices"]
    elif kind == "unused_mesh":
        manifest["meshes"].append(copy.deepcopy(manifest["meshes"][0]))
    elif kind == "unused_material":
        manifest["materials"] = [{}]
    elif kind == "sampler":
        manifest["samplers"] = [{}]
    else:
        binary = embedded_image(manifest, binary)
        if kind == "texture":
            manifest["textures"] = [{"source": 0}]
    with pytest.raises(module.BridgeError) as raised:
        module.plan_glb(glb(manifest, binary))
    assert raised.value.code == module.ErrorCode.NOT_IMPLEMENTED


@pytest.mark.parametrize("kind", ["indices", "repeated_index", "zero_area", "normal_length", "nonnumeric_name",
                                  "unicode_name", "long_name", "partial_affine", "duplicate_json", "nan"])
def test_malformed_or_unreviewed_values_fail_before_native_work(module, kind):
    manifest, binary = triangle(normals=kind == "normal_length")
    raw_json = None
    if kind == "indices":
        binary = binary[:-2] + struct.pack("<H", 3)
    elif kind == "repeated_index":
        binary = binary[:-2] + struct.pack("<H", 1)
    elif kind == "zero_area":
        binary = b"\0" * 36 + binary[36:]
    elif kind == "normal_length":
        binary = binary[:36] + struct.pack("<3f", 0., 0., .5) + binary[48:]
    elif kind in ("nonnumeric_name", "unicode_name", "long_name"):
        manifest["nodes"][0]["name"] = {"nonnumeric_name": 12, "unicode_name": "\ud800", "long_name": "x" * 60}[kind]
    elif kind == "partial_affine":
        manifest["nodes"][0]["matrix"] = [1., 0., 0., 1e-9, 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
    elif kind == "duplicate_json":
        raw_json = b'{"asset":{"version":"2.0"},"asset":{"version":"2.0"}}'
    elif kind == "nan":
        binary = struct.pack("<f", float("nan")) + binary[4:]
    with pytest.raises(module.BridgeError):
        module.plan_glb(glb(manifest, binary, raw_json=raw_json))


@pytest.mark.parametrize("limit", ["MAX_NODES", "MAX_MESHES", "MAX_MATERIALS", "MAX_PRIMITIVES", "MAX_VERTICES", "MAX_TRIANGLES", "MAX_SCALARS"])
def test_tighter_profile_budgets_refuse_before_numeric_plan_decoding(module, monkeypatch, limit):
    manifest, binary = triangle()
    monkeypatch.setattr(module, limit, 0)
    monkeypatch.setattr(module, "_accessor", lambda *_args: pytest.fail("Over-budget profile decoded numeric output"))
    with pytest.raises(module.BridgeError, match="budget"):
        module.plan_glb(glb(manifest, binary))


def test_mesh_instance_budget_applies_even_when_unique_geometry_fits(module, monkeypatch):
    manifest, binary = triangle()
    manifest["nodes"] = [{"mesh": 0}, {"mesh": 0}]
    manifest["scenes"][0]["nodes"] = [0, 1]
    monkeypatch.setattr(module, "MAX_VERTICES", 5)
    with pytest.raises(module.BridgeError, match="instance"):
        module.plan_glb(glb(manifest, binary))


def test_source_labels_and_canonical_bytes_have_independent_output_budgets(module, monkeypatch):
    manifest, binary = triangle()
    manifest["asset"]["copyright"] = "Source license text"
    monkeypatch.setattr(module, "MAX_LABEL_BYTES", 4)
    with pytest.raises(module.BridgeError, match="labels"):
        module.plan_glb(glb(manifest, binary))
    monkeypatch.setattr(module, "MAX_LABEL_BYTES", 8192)
    monkeypatch.setattr(module, "MAX_CANONICAL_BYTES", 64)
    with pytest.raises(module.BridgeError, match="canonical"):
        module.plan_glb(glb(manifest, binary))


@pytest.mark.parametrize("when", [1, 8, 16])
def test_cancellation_propagates_without_a_plan_or_blender_access(module, when):
    manifest, binary = triangle(normals=True, uv=True)
    error = module.BridgeError(module.ErrorCode.TIMEOUT, "Modeled lifetime stopped")
    count = 0
    def check():
        nonlocal count
        count += 1
        if count == when:
            raise error
    with pytest.raises(module.BridgeError) as raised:
        module.plan_glb(glb(manifest, binary), check)
    assert raised.value is error and count == when


def test_exact_loss_acceptance_is_separate_from_permissions(module):
    manifest, binary = triangle(uv=True)
    plan = module.plan_glb(glb(manifest, binary))
    expected = list(plan.required_accepted_losses)
    assert module.require_loss_acceptance(plan, expected) is None
    for value in ([], tuple(expected), [*expected, "UNKNOWN"], list(reversed(expected)), [*expected[:-1], True]):
        with pytest.raises(module.BridgeError, match="repeat"):
            module.require_loss_acceptance(plan, value)
    assert plan.summary()["native_permission_or_checkpoint_verified"] is False


def test_complete_source_binding_and_normalized_hash_are_deterministic(module):
    manifest, binary = triangle(normals=True, uv=True)
    payload = glb(manifest, binary)
    first, second = module.plan_glb(payload), module.plan_glb(payload)
    assert first == second and first.normalized_sha256 == second.normalized_sha256
    altered = copy.deepcopy(manifest)
    altered["asset"]["generator"] = "Different complete source bytes"
    third = module.plan_glb(glb(altered, binary))
    assert first.meshes == third.meshes and first.source_sha256 != third.source_sha256
    assert first.normalized_sha256 != third.normalized_sha256


def test_mixed_explicit_and_default_materials_have_separate_stable_bindings(module):
    manifest, binary = triangle()
    manifest["materials"] = [{"pbrMetallicRoughness": {"metallicFactor": .25}}]
    original = manifest["meshes"][0]["primitives"][0]
    explicit = copy.deepcopy(original)
    explicit["material"] = 0
    manifest["meshes"][0]["primitives"] = [explicit, original]
    plan = module.plan_glb(glb(manifest, binary))
    assert [p.material_index for p in plan.meshes[0].primitives] == [0, 1]
    assert [m.source_index for m in plan.materials] == [0, None]
    assert [m.metallic for m in plan.materials] == [.25, 1.]
    assert plan.vertex_count == 6 and plan.triangle_count == 2


def test_implicit_material_counts_toward_the_same_resource_budget(module, monkeypatch):
    manifest, binary = triangle()
    manifest["materials"] = [{}]
    original = manifest["meshes"][0]["primitives"][0]
    explicit = copy.deepcopy(original)
    explicit["material"] = 0
    manifest["meshes"][0]["primitives"] = [explicit, original]
    monkeypatch.setattr(module, "MAX_MATERIALS", 1)
    with pytest.raises(module.BridgeError, match="implicit"):
        module.plan_glb(glb(manifest, binary))


def test_aggregate_scalar_budget_is_checked_before_any_primitive_is_copied(module, monkeypatch):
    manifest, binary = triangle()
    primitive = manifest["meshes"][0]["primitives"][0]
    manifest["meshes"][0]["primitives"] = [primitive, copy.deepcopy(primitive)]
    # One primitive plus its matrices/default fits; both exceed this bound.
    monkeypatch.setattr(module, "MAX_SCALARS", 55)
    monkeypatch.setattr(module, "_accessor", lambda *_args: pytest.fail("Scalar-overbudget plan copied arrays"))
    with pytest.raises(module.BridgeError, match="scalar"):
        module.plan_glb(glb(manifest, binary))


def test_final_lifecycle_check_can_stop_a_completed_numeric_plan(module):
    manifest, binary = triangle()
    source = glb(manifest, binary)
    observations = []
    module.plan_glb(source, check=lambda: observations.append(None))
    count = 0
    error = module.BridgeError(module.ErrorCode.TIMEOUT, "Stopped at final plan boundary")
    def stop_last():
        nonlocal count
        count += 1
        if count == len(observations):
            raise error
    with pytest.raises(module.BridgeError) as raised:
        module.plan_glb(source, stop_last)
    assert raised.value is error


def test_authoritative_preflight_denial_cannot_be_bypassed_by_the_plan_decoder(module, monkeypatch):
    manifest, binary = triangle()
    error = module.BridgeError(module.ErrorCode.NOT_IMPLEMENTED, "Denied by reviewed core parser")
    def deny(*_args):
        raise error
    monkeypatch.setattr(module, "preflight_glb", deny)
    monkeypatch.setattr(module, "_accessor", lambda *_args: pytest.fail("Denied source reached decoding"))
    with pytest.raises(module.BridgeError) as raised:
        module.plan_glb(glb(manifest, binary))
    assert raised.value is error
