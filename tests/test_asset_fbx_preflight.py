from __future__ import annotations

import importlib
import json
import math
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

import pytest

MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"


@dataclass
class Element:
    name: bytes
    properties: list[bytes] = field(default_factory=list)
    children: list[Element] = field(default_factory=list)


def scalar(kind: str, value: Any) -> bytes:
    formats = {"L": "q", "I": "i", "D": "d", "F": "f", "Y": "h", "Z": "b", "B": "?", "C": "c"}
    return kind.encode() + struct.pack("<" + formats[kind], value)


def string(value: bytes, kind: bytes = b"S") -> bytes:
    return kind + struct.pack("<I", len(value)) + value


def array(kind: str, values: list[Any], *, compressed: bool = False, declared: int | None = None,
          encoding: int | None = None, encoded: bytes | None = None) -> bytes:
    formats = {"d": "d", "f": "f", "i": "i", "l": "q", "b": "B", "c": "B"}
    raw = struct.pack("<" + formats[kind] * len(values), *values)
    data = encoded if encoded is not None else zlib.compress(raw) if compressed else raw
    mode = encoding if encoding is not None else int(compressed)
    return kind.encode() + struct.pack("<III", len(values) if declared is None else declared, mode, len(data)) + data


def encode(element: Element, start: int, version: int) -> bytes:
    header = struct.Struct("<IIIB" if version == 7400 else "<QQQB")
    properties = b"".join(element.properties)
    position = start + header.size + len(element.name) + len(properties)
    children = []
    for child in element.children:
        child_bytes = encode(child, position, version)
        children.append(child_bytes)
        position += len(child_bytes)
    if element.children:
        children.append(bytes(header.size))
        position += header.size
    return header.pack(position, len(element.properties), len(properties), len(element.name)) + element.name + properties + b"".join(children)


def fbx(elements: list[Element], version: int = 7400, footer: bytes = b"") -> bytes:
    parts = [MAGIC + struct.pack("<I", version)]
    position = len(parts[0])
    for element in elements:
        part = encode(element, position, version)
        position += len(part)
        parts.append(part)
    parts.extend([bytes(13 if version == 7400 else 25), footer])
    return b"".join(parts)


def object_element(kind: bytes, identifier: int, name: bytes, subtype: bytes, children: list[Element] | None = None) -> Element:
    return Element(kind, [scalar("L", identifier), string(name + b"\0\1" + kind), string(subtype)], children or [])


def connect(source: int, target: int, relation: bytes = b"OO") -> Element:
    return Element(b"C", [string(relation), scalar("L", source), scalar("L", target)])


def mesh(*, compressed: bool = False, coordinates: list[float] | None = None,
         indices: list[int] | None = None) -> list[Element]:
    coordinates = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0] if coordinates is None else coordinates
    indices = [0, 1, -3] if indices is None else indices
    geometry = object_element(b"Geometry", 100, b"Triangle", b"Mesh", [
        Element(b"Vertices", [array("d", coordinates, compressed=compressed)]),
        Element(b"PolygonVertexIndex", [array("i", indices, compressed=compressed)]),
    ])
    model = object_element(b"Model", 200, b"TriangleObject", b"Mesh")
    return [Element(b"Objects", children=[geometry, model]), Element(b"Connections", children=[connect(100, 200), connect(200, 0)])]


@pytest.fixture
def api(addon_package):
    return importlib.import_module(f"{addon_package}.asset_fbx_preflight")


def reject(api, elements: list[Element], *, message: str | None = None, code: str = "INVALID_ARGUMENT", version: int = 7400):
    with pytest.raises(api.BridgeError, match=message) as caught:
        api.preflight_fbx(fbx(elements, version))
    assert caught.value.code == code


@pytest.mark.parametrize("version", [7400, 7500])
@pytest.mark.parametrize("compressed", [False, True])
def test_static_mesh_exact_summary(api, version, compressed):
    result = api.preflight_fbx(fbx(mesh(compressed=compressed), version))
    assert result["fbx_version"] == version
    assert result["source_objects"] == [{"name": "TriangleObject", "type": "MESH", "vertex_count": 3, "corner_count": 3, "polygon_count": 1}]
    assert result["object_count"] == result["mesh_count"] == result["mesh_object_count"] == 1
    assert result["vertex_count"] == result["corner_count"] == result["instanced_vertex_count"] == 3
    assert result["polygon_count"] == result["instanced_polygon_count"] == 1
    assert result["decoded_array_bytes"] == 9 * 8 + 3 * 4
    assert result["dependencies"] == [] and result["self_contained"] is True
    assert result["required_accepted_losses"] == ["AXIS_UNIT_CONVERSION", "FBX_MESH_RECONSTRUCTION"]
    assert json.loads(json.dumps(result)) == result


def test_null_models_and_optional_null_attributes(api):
    roots = [Element(b"Objects", children=[
        object_element(b"Model", 1, b"Empty", b"Null"),
        object_element(b"Model", 2, "子".encode(), b"Null"),
        object_element(b"NodeAttribute", 3, b"EmptyAttribute", b"Null"),
    ]), Element(b"Connections", children=[connect(1, 0), connect(2, 1), connect(3, 1)])]
    result = api.preflight_fbx(fbx(roots))
    assert result["object_names"] == ["Empty", "子"]
    assert result["object_count"] == result["empty_object_count"] == 2
    assert result["mesh_count"] == result["vertex_count"] == result["instanced_vertex_count"] == 0


def test_shared_geometry_keeps_unique_and_instanced_counts_separate(api):
    roots = mesh()
    roots[0].children.append(object_element(b"Model", 201, b"Instance", b"Mesh"))
    roots[1].children.extend([connect(100, 201), connect(201, 200)])
    result = api.preflight_fbx(fbx(roots))
    assert result["object_count"] == result["mesh_object_count"] == 2
    assert result["mesh_count"] == 1
    assert result["vertex_count"] == 3 and result["instanced_vertex_count"] == 6


def test_preflight_common_import_summary_matches_detailed_counts(api):
    result = api.preflight_fbx(fbx(mesh()))
    assert result['objects'] == result['object_count'] == 1
    assert result['meshes'] == result['mesh_count'] == 1
    assert result['vertices'] == result['vertex_count'] == 3
    assert result['materials'] == result['material_count'] == 0
    assert result['images'] == [] and result['image_pixels'] == 0
    assert not result['animation_present']


@pytest.mark.parametrize('limit', ['MAX_VERTICES', 'MAX_CORNERS'])
def test_shared_geometry_instances_obey_aggregate_import_budget(api, monkeypatch, limit):
    roots = mesh()
    roots[0].children.append(object_element(b'Model', 201, b'Instance', b'Mesh'))
    roots[1].children.extend([connect(100, 201), connect(201, 0)])
    monkeypatch.setattr(api, limit, 5)
    reject(api, roots, message='instances exceed')


def test_logical_model_hierarchy_has_independent_depth_budget(api):
    roots = mesh()
    previous = 200
    for identifier in range(201, 234):
        roots[0].children.append(object_element(b'Model', identifier, b'Empty', b'Null'))
        roots[1].children.append(connect(identifier, previous))
        previous = identifier
    reject(api, roots, message='32 levels')


@pytest.mark.parametrize("payload", [b"", b"not binary FBX", MAGIC, bytearray(MAGIC + bytes(100))])
def test_reject_nonbinary_or_wrong_python_type(api, payload):
    with pytest.raises(api.BridgeError, match="bounded binary"):
        api.preflight_fbx(payload)


def test_exact_version_admission(api):
    payload = bytearray(fbx(mesh()))
    struct.pack_into("<I", payload, 23, 7600)
    with pytest.raises(api.BridgeError) as error:
        api.preflight_fbx(bytes(payload))
    assert error.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("version", [7400, 7500])
def test_root_sentinel_truncation_footer_bounds_and_null_bytes(api, version):
    payload = fbx(mesh(), version)
    sentinel = 13 if version == 7400 else 25
    for truncated in [payload[:-sentinel], payload[:-1], payload[:30]]:
        with pytest.raises(api.BridgeError):
            api.preflight_fbx(truncated)
    assert api.preflight_fbx(payload + bytes(256))["ignored_footer_bytes"] == 256
    with pytest.raises(api.BridgeError, match="footer"):
        api.preflight_fbx(payload + bytes(257))
    broken = bytearray(payload)
    broken[-1] = 1
    with pytest.raises(api.BridgeError, match="sentinel"):
        api.preflight_fbx(bytes(broken))


@pytest.mark.parametrize("version", [7400, 7500])
@pytest.mark.parametrize("field_index,value", [(0, 1), (0, 1_000_000), (1, 100001), (2, 1_000_000)])
def test_malformed_top_element_bounds(api, version, field_index, value):
    payload = bytearray(fbx(mesh(), version))
    struct.pack_into("<I" if version == 7400 else "<Q", payload, 27 + field_index * (4 if version == 7400 else 8), value)
    with pytest.raises(api.BridgeError):
        api.preflight_fbx(bytes(payload))


def test_child_scope_requires_exact_final_sentinel(api):
    payload = bytearray(fbx(mesh()))
    parent_end = struct.unpack_from("<I", payload, 27)[0]
    payload[parent_end-1] = 1
    with pytest.raises(api.BridgeError, match="sentinel"):
        api.preflight_fbx(bytes(payload))


def test_property_byte_length_count_and_unknown_encoding(api):
    for data in [b"I", b"X", string(b"a")[:-1], b"I" + struct.pack("<i", 4) + b"extra"]:
        roots = mesh()
        roots.append(Element(b"Ignored", [data]))
        with pytest.raises(api.BridgeError):
            api.preflight_fbx(fbx(roots))


@pytest.mark.parametrize("name", [b"Material", b"Texture", b"Video", b"Deformer", b"AnimationCurve", b"AnimationStack", b"Pose", b"Constraint", b"Camera", b"Light", b"Content", b"FileName", b"Filename", b"RelativeFilename", b"LayerElementMaterial"])
def test_actual_forbidden_nodes_rejected_at_any_depth(api, name):
    roots = mesh()
    roots[0].children[0].children.append(Element(b"Nested", children=[Element(name)]))
    reject(api, roots, code="NOT_IMPLEMENTED")


def test_material_template_name_is_not_actual_material_node(api):
    roots = [*mesh(), Element(b"Definitions", children=[Element(b"ObjectType", [string(b"Material")])])]
    assert api.preflight_fbx(fbx(roots))["material_count"] == 0


@pytest.mark.parametrize("kind,subtype", [(b"Geometry", b"NurbsSurface"), (b"Model", b"Camera"), (b"Model", b"Light"), (b"Model", b"LimbNode"), (b"NodeAttribute", b"Camera"), (b"Collection", b"Scene")])
def test_unsupported_object_classes(api, kind, subtype):
    roots = mesh()
    roots[0].children.append(object_element(kind, 999, b"Unsupported", subtype))
    reject(api, roots, code="NOT_IMPLEMENTED")


@pytest.mark.parametrize("name", [b"", b"\xff", b"has\x7fcontrol", b"has\ncontrol", "bidi\u202e".encode(), b"x" * 257])
def test_object_name_controls_unicode_and_character_bounds(api, name):
    roots = mesh()
    roots[0].children[1].properties[1] = string(name + b"\0\1Model")
    reject(api, roots)


@pytest.mark.parametrize("raw", [b"withoutclass", b"Triangle\0\1Geometry", b"Triangle\0\1Model\0\1Model"])
def test_exact_name_suffix(api, raw):
    roots = mesh()
    roots[0].children[1].properties[1] = string(raw)
    reject(api, roots, message="class suffix")


@pytest.mark.parametrize("metadata", [
    [scalar("I", 200), string(b"Object\0\1Model"), string(b"Mesh")],
    [scalar("L", 200), string(b"Object\0\1Model", b"R"), string(b"Mesh")],
    [scalar("L", 200), string(b"Object\0\1Model"), string(b"Mesh", b"R")],
    [scalar("L", 200), string(b"Object\0\1Model")],
])
def test_native_object_metadata_types_are_exact(api, metadata):
    roots = mesh()
    roots[0].children[1].properties = metadata
    reject(api, roots, message="distinct nonzero")


@pytest.mark.parametrize("identifier", [0, 100])
def test_zero_and_duplicate_object_ids(api, identifier):
    roots = mesh()
    roots[0].children[1].properties[0] = scalar("L", identifier)
    reject(api, roots, message="distinct nonzero")


@pytest.mark.parametrize("change", ["source_missing", "target_missing", "bad_kind", "bad_id_type", "extra_property", "child", "geometry_to_root", "model_to_geometry"])
def test_connections_exact_native_types_and_references(api, change):
    roots = mesh()
    connection = roots[1].children[0]
    if change == "source_missing":
        connection.properties[1] = scalar("L", 999)
    elif change == "target_missing":
        connection.properties[2] = scalar("L", 999)
    elif change == "bad_kind":
        connection.properties[0] = string(b"OP")
    elif change == "bad_id_type":
        connection.properties[1] = scalar("I", 100)
    elif change == "extra_property":
        connection.properties.append(string(b"path"))
    elif change == "child":
        connection.children.append(Element(b"Unexpected"))
    elif change == "geometry_to_root":
        connection.properties[2] = scalar("L", 0)
    elif change == "model_to_geometry":
        connection.properties = connect(200, 100).properties
    with pytest.raises(api.BridgeError):
        api.preflight_fbx(fbx(roots))


@pytest.mark.parametrize("change", ["missing_geometry", "orphan_geometry", "missing_parent", "duplicate_parent", "duplicate_geometry", "self_parent", "cycle", "orphan_attribute", "duplicate_attribute"])
def test_dependency_closure_and_hierarchy(api, change):
    roots = mesh()
    if change == "missing_geometry":
        roots[1].children.pop(0)
    elif change == "orphan_geometry":
        geometry = object_element(b"Geometry", 101, b"Orphan", b"Mesh", roots[0].children[0].children)
        roots[0].children.append(geometry)
    elif change == "missing_parent":
        roots[1].children.pop()
    elif change == "duplicate_parent":
        roots[1].children.append(connect(200, 0))
    elif change == "duplicate_geometry":
        roots[1].children.append(connect(100, 200))
    elif change == "self_parent":
        roots[1].children[1] = connect(200, 200)
    elif change == "cycle":
        roots[0].children.append(object_element(b"Model", 201, b"Empty", b"Null"))
        roots[1].children[1] = connect(200, 201)
        roots[1].children.append(connect(201, 200))
    else:
        roots[0].children.extend([object_element(b"Model", 201, b"Empty", b"Null"), object_element(b"NodeAttribute", 202, b"Attribute", b"Null")])
        roots[1].children.append(connect(201, 0))
        if change == "duplicate_attribute":
            roots[1].children.extend([connect(202, 201), connect(202, 201)])
    reject(api, roots)


@pytest.mark.parametrize("references", [Element(b"References", [string(b"external")]), Element(b"References", children=[Element(b"Reference")])])
def test_external_reference_sections_rejected(api, references):
    reject(api, [*mesh(), references], code="NOT_IMPLEMENTED")


@pytest.mark.parametrize("section", [b"Objects", b"Connections", b"References"])
def test_duplicate_critical_roots(api, section):
    roots = mesh()
    if section == b"References":
        roots.append(Element(section))
    roots.append(Element(section))
    reject(api, roots, message="duplicated")


@pytest.mark.parametrize("section_index", [0, 1])
def test_sections_must_exist_without_properties(api, section_index):
    roots = mesh()
    roots[section_index].properties = [scalar("I", 1)]
    reject(api, roots, message="plain child")
    roots = mesh()
    roots.pop(section_index)
    reject(api, roots, message="missing")


@pytest.mark.parametrize("values", [[], [0.0], [0.0] * 8, [math.inf] * 9, [math.nan] * 9, [1e13] * 9, [1e10] * 9])
def test_geometry_coordinate_validation(api, values):
    reject(api, mesh(coordinates=values))


@pytest.mark.parametrize("values", [[], [0, 1], [0, 1, 2], [0, 1, -4], [0, 1, -1], [0, -2, -3], [-2147483648, 1, -3]])
def test_geometry_index_validation(api, values):
    reject(api, mesh(indices=values))


def test_geometry_polygons_bounded_and_arrays_typed(api):
    coords = [float(value) for index in range(33) for value in (index, index % 2, 0)]
    reject(api, mesh(coordinates=coords, indices=[*range(32), -33]), code="NOT_IMPLEMENTED")
    roots = mesh()
    roots[0].children[0].children[1].properties = [array("l", [0, 1, -3])]
    reject(api, roots, message="signed 32-bit")
    roots = mesh()
    roots[0].children[0].children[0].properties = [array("i", [0] * 9)]
    reject(api, roots, message="numeric array")
    roots = mesh()
    roots[0].children[0].children.append(roots[0].children[0].children[0])
    reject(api, roots, message="duplicated")


@pytest.mark.parametrize("kind", ["d", "f"])
def test_all_float_arrays_and_scalars_must_be_finite(api, kind):
    roots = [*mesh(), Element(b"Ignored", [array(kind, [math.inf])])]
    reject(api, roots, message="nonfinite")
    roots[-1].properties = [scalar(kind.upper(), math.nan)]
    reject(api, roots, message="nonfinite")


@pytest.mark.parametrize("encoding,declared,encoded", [
    (0, 2, b"\0" * 4),
    (1, 1, zlib.compress(b"\0" * 8)),
    (1, 2, zlib.compress(b"\0" * 4)),
    (1, 1, zlib.compress(b"\0" * 4)[:-1]),
    (1, 1, zlib.compress(b"\0" * 4) + b"tail"),
    (1, 1, zlib.compress(b"\0" * 4) + zlib.compress(b"")),
    (1, 1, b"notzlib"),
    (1, 1, zlib.compress(b"\0" * 1_000_000)),
    (1, 0, zlib.compress(b"\0")),
    (2, 1, b"\0" * 4),
])
def test_array_length_encoding_truncation_tails_and_bombs(api, encoding, declared, encoded):
    roots = [*mesh(), Element(b"Ignored", [array("i", [], declared=declared, encoding=encoding, encoded=encoded)])]
    with pytest.raises(api.BridgeError):
        api.preflight_fbx(fbx(roots))


def test_exact_empty_compressed_array_is_safe(api):
    roots = [*mesh(), Element(b"Ignored", [array("i", [], compressed=True)])]
    assert api.preflight_fbx(fbx(roots))["vertex_count"] == 3


def test_all_array_types_and_small_scalars_have_explicit_encodings(api):
    props = [array(kind, [0, 1], compressed=True) for kind in ["b", "c", "i", "l", "f", "d"]]
    props += [scalar("Z", -1), scalar("Y", -2), scalar("B", True), scalar("C", b"x"), string(b"opaque", b"R")]
    assert api.preflight_fbx(fbx([*mesh(), Element(b"Ignored", props)]))["parsed_properties"] > 10


@pytest.mark.parametrize("kind,size", [(b"S", 4097), (b"R", 65537)])
def test_string_and_opaque_lengths(api, kind, size):
    reject(api, [*mesh(), Element(b"Ignored", [string(b"x" * size, kind)])], message="byte bound")


def test_declared_bomb_rejected_before_inflation(api, monkeypatch):
    roots = [*mesh(), Element(b"Ignored", [array("d", [], declared=2 ** 32 - 1, encoding=1, encoded=b"x")])]
    def unexpected_inflate():
        raise AssertionError("inflation must not run for an oversized declaration")
    monkeypatch.setattr(api.zlib, "decompressobj", unexpected_inflate)
    reject(api, roots, message="64 MiB")


@pytest.mark.parametrize("budget,value", [("MAX_FILE_BYTES", 64), ("MAX_ELEMENTS", 4), ("MAX_PROPERTIES", 2), ("MAX_DECODED_BYTES", 80), ("MAX_VERTICES", 2), ("MAX_CORNERS", 2), ("MAX_OBJECTS", 0)])
def test_inventory_budgets_fail_closed(api, monkeypatch, budget, value):
    monkeypatch.setattr(api, budget, value)
    with pytest.raises(api.BridgeError):
        api.preflight_fbx(fbx(mesh()))


def test_aggregate_geometry_limits_not_only_per_mesh(api, monkeypatch):
    roots = mesh()
    roots[0].children.extend([
        object_element(b"Geometry", 101, b"OtherGeometry", b"Mesh", roots[0].children[0].children),
        object_element(b"Model", 201, b"OtherModel", b"Mesh"),
    ])
    roots[1].children.extend([connect(101, 201), connect(201, 0)])
    monkeypatch.setattr(api, "MAX_VERTICES", 5)
    reject(api, roots)


def test_hierarchy_depth_and_element_identifiers(api):
    nested = Element(b"Leaf")
    for _ in range(35):
        nested = Element(b"Nested", children=[nested])
    reject(api, [*mesh(), nested], message="32 levels")
    for name in [b"", b"\n", b"\xff"]:
        reject(api, [*mesh(), Element(name)])


def test_cancellation_callback_propagates_during_decode_and_inventory(api):
    class Cancelled(Exception):
        pass
    calls = 0
    def check():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise Cancelled("stop")
    with pytest.raises(Cancelled, match="stop"):
        api.preflight_fbx(fbx(mesh(compressed=True)), check)
    assert calls == 12


def test_compressed_stream_checks_cancellation_between_chunks(api):
    # An incompressible array forces multiple bounded inflater feed calls.
    import random
    generator = random.Random(0)
    values = [generator.randrange(2**31) for _ in range(40_000)]
    roots = [*mesh(), Element(b"Ignored", [array("i", values, compressed=True)])]
    calls = 0
    def check():
        nonlocal calls
        calls += 1
    result = api.preflight_fbx(fbx(roots), check)
    assert result["decoded_array_bytes"] == 84 + len(values)*4
    assert calls > result["parsed_elements"] + result["parsed_properties"]
