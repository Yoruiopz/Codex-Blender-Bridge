"""Bounded binary-FBX admission for static material-free mesh/empty imports.

This standard-library parser performs no IO or native allocations. It does not
replace Blender's importer and never treats names or strings as executable paths.
"""

from __future__ import annotations

import math
import struct
import unicodedata
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument

MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024
MAX_ELEMENTS, MAX_PROPERTIES, MAX_DEPTH = 20_000, 100_000, 32
MAX_VERTICES, MAX_CORNERS, MAX_OBJECTS = 100_000, 200_000, 64
_SCALARS = {b"Z": "b", b"Y": "h", b"B": "?", b"C": "c", b"I": "i", b"F": "f", b"D": "d", b"L": "q"}
_ARRAYS = {b"b": ("B", 1), b"c": ("B", 1), b"i": ("i", 4), b"l": ("q", 8), b"f": ("f", 4), b"d": ("d", 8)}
_FORBIDDEN = {
    b"Material", b"Texture", b"Video", b"Deformer", b"Pose", b"Constraint", b"Camera", b"Light",
    b"Filename", b"FileName", b"RelativeFilename", b"Content", b"LayerElementMaterial",
}


def _unsupported(message: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message)


@dataclass(slots=True)
class _Array:
    kind: str
    count: int
    data: bytes

    def values(self) -> Iterator[Any]:
        return (item[0] for item in struct.iter_unpack("<" + self.kind, self.data))


@dataclass(slots=True)
class _Node:
    name: bytes
    properties: list[Any]
    property_types: bytes
    children: list[_Node]


class _Reader:
    def __init__(self, payload: bytes, check: Callable[[], None]):
        self.payload, self.check, self.position = payload, check, 27
        self.version = struct.unpack_from("<I", payload, 23)[0]
        if self.version not in {7400, 7500}:
            raise _unsupported("Only reviewed binary FBX 7400/7500 is supported.")
        self.header = struct.Struct("<IIIB" if self.version == 7400 else "<QQQB")
        self.elements = self.properties = self.decoded_bytes = 0

    def read(self, count: int, limit: int) -> bytes:
        if not 0 <= count <= limit - self.position or limit > len(self.payload):
            raise invalid_argument("FBX property or element exceeds its enclosing byte range.")
        start = self.position
        self.position += count
        return self.payload[start:self.position]

    def unpack(self, format: str, limit: int) -> tuple:
        return struct.unpack(format, self.read(struct.calcsize(format), limit))

    def property(self, limit: int) -> Any:
        self.check()
        self.properties += 1
        if self.properties > MAX_PROPERTIES:
            raise invalid_argument("FBX exceeds 100000 properties.")
        kind = self.read(1, limit)
        if kind in _SCALARS:
            value = self.unpack("<" + _SCALARS[kind], limit)[0]
            if isinstance(value, float) and (not math.isfinite(value) or abs(value) > 1e12):
                raise invalid_argument("FBX contains a nonfinite or unbounded scalar.")
            return value
        if kind in {b"R", b"S"}:
            length = self.unpack("<I", limit)[0]
            if length > (4096 if kind == b"S" else 65536):
                raise invalid_argument("FBX string or opaque property exceeds its byte bound.")
            return self.read(length, limit)
        if kind not in _ARRAYS:
            raise _unsupported("FBX contains an unreviewed property encoding.")
        count, encoding, size = self.unpack("<III", limit)
        format, stride = _ARRAYS[kind]
        expected = count * stride
        if expected > MAX_DECODED_BYTES - self.decoded_bytes or size > MAX_FILE_BYTES:
            raise invalid_argument("FBX decoded arrays exceed the aggregate 64 MiB budget.")
        self.decoded_bytes += expected
        encoded = self.read(size, limit)
        if encoding == 0:
            if size != expected:
                raise invalid_argument("FBX uncompressed array length differs from its declaration.")
            data = encoded
        elif encoding == 1:
            inflater = zlib.decompressobj()
            parts, received = [], 0
            try:
                for offset in range(0, len(encoded), 65536):
                    self.check()
                    part = inflater.decompress(encoded[offset:offset+65536], expected-received+1)
                    received += len(part)
                    if received > expected or inflater.unconsumed_tail:
                        raise invalid_argument("FBX compressed array exceeds its declared decoded length.")
                    parts.append(part)
                if not inflater.eof or inflater.unused_data or received != expected:
                    raise invalid_argument("FBX compressed array is truncated, concatenated or incorrectly sized.")
            except zlib.error as error:
                raise invalid_argument("FBX compressed array is invalid.") from error
            data = b"".join(parts)
        else:
            raise _unsupported("FBX array encoding must be plain or zlib.")
        array = _Array(format, count, data)
        if format in {"f", "d"}:
            for index, value in enumerate(array.values()):
                if not index % 1024:
                    self.check()
                if not math.isfinite(value) or abs(value) > 1e12:
                    raise invalid_argument("FBX array contains nonfinite or unbounded values.")
        return array

    def node(self, limit: int, depth: int = 0) -> _Node | None:
        self.check()
        if depth > MAX_DEPTH:
            raise invalid_argument("FBX hierarchy exceeds 32 levels.")
        raw = self.read(self.header.size, limit)
        end, count, length, name_length = self.header.unpack(raw)
        if not end:
            if any(raw):
                raise invalid_argument("FBX null element sentinel must contain only zero bytes.")
            return None
        self.elements += 1
        if self.elements > MAX_ELEMENTS or count > MAX_PROPERTIES - self.properties:
            raise invalid_argument("FBX exceeds its element/property inventory budget.")
        if end > limit or end < self.position + name_length or not name_length:
            raise invalid_argument("FBX element end offset/name is invalid.")
        name = self.read(name_length, end)
        if any(value < 32 or value > 126 for value in name):
            raise invalid_argument("FBX element identifiers must be printable ASCII.")
        if name in _FORBIDDEN or name.startswith(b"Animation"):
            raise _unsupported("FBX materials, media, animation, rigs and constraints need a broader import contract.")
        property_end = self.position + length
        if property_end > end:
            raise invalid_argument("FBX declared property list exceeds its element.")
        properties = []
        property_types = bytearray()
        for _ in range(count):
            if self.position >= property_end:
                raise invalid_argument("FBX property count exceeds its declared byte range.")
            property_types.append(self.payload[self.position])
            properties.append(self.property(property_end))
        if self.position != property_end:
            raise invalid_argument("FBX property count and property byte length disagree.")
        children = []
        if self.position < end:
            while self.position < end:
                child = self.node(end, depth + 1)
                if child is None:
                    if self.position != end:
                        raise invalid_argument("FBX child sentinel does not end its element exactly.")
                    break
                children.append(child)
            else:
                raise invalid_argument("FBX child scopes require a final null sentinel.")
        if self.position != end:
            raise invalid_argument("FBX element length does not match its parsed contents.")
        return _Node(name, properties, bytes(property_types), children)


def _one(nodes: list[_Node], name: bytes, *, required: bool = False) -> _Node | None:
    matches = [node for node in nodes if node.name == name]
    if len(matches) > 1 or (required and not matches):
        raise invalid_argument("FBX critical element is missing or duplicated.", element=name.decode("ascii"))
    return matches[0] if matches else None


def _object_name(raw: Any, expected_class: bytes) -> str:
    if not isinstance(raw, bytes) or not raw or len(raw) > 1024:
        raise invalid_argument("FBX object name must be a bounded UTF-8 string.")
    parts = raw.split(b"\0\1")
    if len(parts) != 2 or parts[1] != expected_class:
        raise invalid_argument("FBX object names require the exact native class suffix.")
    value = parts[0]
    try:
        result = value.decode("utf-8")
    except UnicodeError as error:
        raise invalid_argument("FBX object name is not UTF-8.") from error
    if not result.strip() or len(result) > 256 or any(unicodedata.category(char).startswith("C") for char in result):
        raise invalid_argument("FBX object name is empty or contains unsupported controls.")
    return result


def _geometry(node: _Node, check: Callable[[], None]) -> tuple[int, int, int]:
    vertices = _one(node.children, b"Vertices", required=True)
    indices = _one(node.children, b"PolygonVertexIndex", required=True)
    assert vertices is not None and indices is not None
    if len(vertices.properties) != 1 or not isinstance(vertices.properties[0], _Array) or vertices.properties[0].kind not in {"f", "d"}:
        raise invalid_argument("FBX mesh vertices require one numeric array.")
    coordinates = vertices.properties[0]
    if not coordinates.count or coordinates.count % 3 or coordinates.count // 3 > MAX_VERTICES:
        raise invalid_argument("FBX geometry vertex count is empty, malformed or exceeds 100000.")
    for index, value in enumerate(coordinates.values()):
        if not index % 1024:
            check()
        if abs(value) > 1e9:
            raise invalid_argument("FBX mesh coordinates exceed the reviewed magnitude bound.")
    if len(indices.properties) != 1 or not isinstance(indices.properties[0], _Array) or indices.properties[0].kind != "i":
        raise invalid_argument("FBX polygons require one signed 32-bit integer array.")
    corners = indices.properties[0]
    if not 3 <= corners.count <= MAX_CORNERS:
        raise invalid_argument("FBX geometry corners exceed the 200000-corner budget.")
    count = polygons = 0
    unique: set[int] = set()
    for index, value in enumerate(corners.values()):
        if not index % 1024:
            check()
        vertex = -value-1 if value < 0 else value
        if not 0 <= vertex < coordinates.count // 3:
            raise invalid_argument("FBX polygon references an absent vertex.")
        count += 1
        unique.add(vertex)
        if count > 32:
            raise _unsupported("FBX polygons with more than 32 corners need separate acceptance.")
        if value < 0:
            if count < 3 or len(unique) != count:
                raise invalid_argument("FBX polygon is degenerate or repeats a vertex.")
            polygons += 1
            count = 0
            unique.clear()
    if count or not polygons:
        raise invalid_argument("FBX polygon array lacks a valid final polygon terminator.")
    return coordinates.count // 3, corners.count, polygons


def preflight_fbx(payload: bytes, check: Callable[[], None] | None = None) -> dict[str, Any]:
    """Admit bounded static mesh/empty binary FBX without material/media dependencies.

    This is a source-admission check, not a promise that native import will succeed
    or preserve every optional mesh layer. Footer bytes ignored by Blender remain
    bounded but do not carry an integrity claim.
    """
    if not isinstance(payload, bytes) or not 27 <= len(payload) <= MAX_FILE_BYTES or not payload.startswith(MAGIC):
        raise invalid_argument("Asset must be a bounded binary FBX file within 64 MiB.")
    check = check or (lambda: None)
    reader = _Reader(payload, check)
    roots = []
    while reader.position < len(payload):
        node = reader.node(len(payload))
        if node is None:
            break
        roots.append(node)
    else:
        raise invalid_argument("FBX file lacks its top-level null sentinel.")
    # Native FBX ignores its footer. Keep it bounded without claiming CRC identity.
    if len(payload) - reader.position > 256:
        raise invalid_argument("FBX footer exceeds its reviewed ignored-byte window.")
    objects = _one(roots, b"Objects", required=True)
    connections = _one(roots, b"Connections", required=True)
    references = _one(roots, b"References")
    if references is not None and (references.properties or references.children):
        raise _unsupported("External FBX reference sections are not admitted.")
    assert objects is not None and connections is not None
    if objects.properties or connections.properties:
        raise invalid_argument("FBX object/connection sections must be plain child scopes.")
    if len(objects.children) > MAX_OBJECTS * 3:
        raise invalid_argument("FBX object dependency inventory exceeds 192 entries.")
    table: dict[int, _Node] = {}
    geometry_counts: dict[int, tuple[int, int, int]] = {}
    names, models, geometries, vertex_count, corner_count, polygon_count = [], {}, {}, 0, 0, 0
    for node in objects.children:
        check()
        if node.property_types != b"LSS" or node.properties[0] == 0 or node.properties[0] in table:
            raise invalid_argument("FBX Objects require distinct nonzero integer IDs and exact class/name metadata.")
        identifier = node.properties[0]
        table[identifier] = node
        name = _object_name(node.properties[1], node.name)
        if node.name == b"Model" and node.properties[2] in {b"Mesh", b"Null"}:
            models[identifier] = node.properties[2]
            names.append(name)
        elif node.name == b"Geometry" and node.properties[2] == b"Mesh":
            counts = _geometry(node, check)
            vertex_count += counts[0]
            corner_count += counts[1]
            polygon_count += counts[2]
            geometries[identifier] = node
            geometry_counts[identifier] = counts
        elif node.name == b"NodeAttribute" and node.properties[2] == b"Null":
            pass
        else:
            raise _unsupported("Static FBX import admits only mesh/empty Models, Mesh Geometry and Null NodeAttribute objects.")
    if not models or len(models) > MAX_OBJECTS or vertex_count > MAX_VERTICES or corner_count > MAX_CORNERS:
        raise invalid_argument("FBX static import requires 1-64 models, <=100000 vertices and <=200000 corners.")
    parents: dict[int, int] = {}
    geometry_users: dict[int, list[int]] = {identifier: [] for identifier in geometries}
    model_geometry: dict[int, int] = {}
    attribute_users: dict[int, int] = {}
    model_attribute: set[int] = set()
    for connection in connections.children:
        check()
        values = connection.properties
        if connection.name != b"C" or connection.property_types != b"SLL" or values[0] != b"OO" or connection.children:
            raise _unsupported("Only exact object-to-object FBX connections are reviewed.")
        source, target = values[1:]
        if source not in table or (target not in table and target != 0):
            raise invalid_argument("FBX connection references an absent object ID.")
        if source in geometries and target in models and models[target] == b"Mesh":
            if target in model_geometry:
                raise invalid_argument("FBX mesh Model has multiple geometry bindings.")
            geometry_users[source].append(target)
            model_geometry[target] = source
        elif source in models and (target in models or target == 0):
            if source in parents:
                raise invalid_argument("FBX Model has multiple parent bindings.")
            parents[source] = target
        elif table[source].name == b"NodeAttribute" and target in models and models[target] == b"Null":
            if source in attribute_users or target in model_attribute:
                raise invalid_argument("FBX Null attributes require one explicit Model binding each.")
            attribute_users[source] = target
            model_attribute.add(target)
        else:
            raise _unsupported("FBX connection introduces an unreviewed dependency relationship.")
    if any(not users for users in geometry_users.values()) or any(kind == b"Mesh" and identifier not in model_geometry for identifier, kind in models.items()):
        raise invalid_argument("FBX geometry/mesh Models require explicit complete bindings.")
    if len(parents) != len(models) or any(node.name == b"NodeAttribute" and identifier not in attribute_users for identifier, node in table.items()):
        raise invalid_argument("FBX Models/Null attributes require complete explicit hierarchy bindings.")
    for identifier in models:
        visited = set()
        current = identifier
        while current:
            if current in visited:
                raise invalid_argument("FBX Model hierarchy contains a cycle.")
            visited.add(current)
            if len(visited) > MAX_DEPTH:
                raise invalid_argument('FBX Model hierarchy exceeds 32 levels.')
            current = parents.get(current, 0)
    source_objects = []
    for identifier, kind in models.items():
        counts = geometry_counts[model_geometry[identifier]] if kind == b"Mesh" else (0, 0, 0)
        source_objects.append({
            "name": _object_name(table[identifier].properties[1], b"Model"),
            "type": "MESH" if kind == b"Mesh" else "EMPTY",
            "vertex_count": counts[0], "corner_count": counts[1], "polygon_count": counts[2],
        })
    instanced_vertices = sum(item["vertex_count"] for item in source_objects)
    instanced_corners = sum(item["corner_count"] for item in source_objects)
    instanced_polygons = sum(item["polygon_count"] for item in source_objects)
    if instanced_vertices > MAX_VERTICES or instanced_corners > MAX_CORNERS:
        raise invalid_argument("FBX mesh instances exceed the aggregate imported geometry budget.")
    return {"format": "FBX", "fbx_version": reader.version, "objects": len(models),
            "meshes": len(geometries), "vertices": vertex_count, "materials": 0, "images": [],
            "image_pixels": 0, "animation_present": False, "object_count": len(models),
            "mesh_count": len(geometries), "vertex_count": vertex_count, "corner_count": corner_count,
            "polygon_count": polygon_count, "material_count": 0, "image_count": 0,
            "animation_count": 0, "skin_count": 0, "object_names": names,
            "mesh_object_count": len(model_geometry), "empty_object_count": len(models)-len(model_geometry),
            "instanced_vertex_count": instanced_vertices,
            "instanced_corner_count": instanced_corners,
            "instanced_polygon_count": instanced_polygons,
            "source_objects": source_objects,
            "dependencies": [], "self_contained": True, "decoded_array_bytes": reader.decoded_bytes,
            "parsed_elements": reader.elements, "parsed_properties": reader.properties,
            "ignored_footer_bytes": len(payload)-reader.position, "pixel_contents_verified": False,
            "required_accepted_losses": ["AXIS_UNIT_CONVERSION", "FBX_MESH_RECONSTRUCTION"],
            "limits": {"file_bytes": MAX_FILE_BYTES, "decoded_array_bytes": MAX_DECODED_BYTES,
                       "objects": MAX_OBJECTS, "vertices": MAX_VERTICES, "corners": MAX_CORNERS}}
