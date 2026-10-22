"""Bounded, read-only admission of self-contained static GLB 2 assets.

This deliberately admits reviewed core triangle/PBR/base-color image assets.
It never invokes Blender, follows URIs, imports extensions or allocates scene data.
"""

from __future__ import annotations

import io
import json
import math
import struct
from collections.abc import Callable
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .image_streams import preflight_stream

MAX_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 16_777_216
MAX_VERTICES = 100_000
MAX_TRIANGLES = 100_000
LOSSES = ["VERTEX_SPLITS", "AXIS_UNIT_CONVERSION", "PBR_MATERIAL_RECONSTRUCTION"]


def _unsupported(message: str) -> None:
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, message)


def _integer(value: Any, minimum: int = 0, maximum: int = 100_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise invalid_argument("GLB integer count/index exceeds its reviewed bounds.")
    return value


def _vector(value: Any, count: int, maximum: float = 1e9) -> None:
    if not isinstance(value, list) or len(value) != count or any(type(item) not in (int, float) or not math.isfinite(item) or abs(item) > maximum for item in value):
        raise invalid_argument("GLB vector/transform must have finite bounded components and exact arity.")


def _node_matrix(node: dict) -> list[list[float]]:
    """Reviewed glTF column-major affine matrix, or equivalent T*R*S."""
    if 'matrix' in node:
        raw = node['matrix']
        matrix = [[float(raw[column*4+row]) for column in range(4)] for row in range(4)]
        if any(abs(matrix[3][column] - (1. if column == 3 else 0.)) > 1e-8 for column in range(4)):
            raise invalid_argument('GLB node matrices must be affine.')
        columns = [[matrix[row][column] for row in range(3)] for column in range(3)]
        for first in range(3):
            for second in range(first+1, 3):
                dot = sum(a*b for a, b in zip(columns[first], columns[second], strict=True))
                lengths = math.sqrt(sum(a*a for a in columns[first])*sum(b*b for b in columns[second]))
                if abs(dot) > 1e-7 + lengths*1e-5:
                    _unsupported('GLB sheared local matrices need a separately reviewed native decomposition contract.')
        return matrix
    x, y, z, w = node.get('rotation', [0., 0., 0., 1.])
    scale = node.get('scale', [1., 1., 1.])
    translation = node.get('translation', [0., 0., 0.])
    rotation = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
                (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
                (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    return [[rotation[row][column]*scale[column] for column in range(3)]+[translation[row]]
            for row in range(3)]+[[0., 0., 0., 1.]]


def _keys(value: Any, allowed: set[str]) -> None:
    if not isinstance(value, dict) or set(value) - allowed:
        _unsupported("GLB fields are outside the explicitly reviewed core subset.")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise invalid_argument("Duplicate GLB JSON keys are unsupported.")
        result[key] = value
    return result


def _json_budget(value: Any, check: Callable[[], None], depth=0, budget=None) -> None:
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 16 or budget[0] > 50_000:
        raise invalid_argument("GLB JSON exceeds its depth/element budget.")
    if budget[0] % 256 == 0:
        check()
    if isinstance(value, str) and (len(value) > 4096 or any(ord(char) < 32 for char in value)):
        raise invalid_argument("GLB text exceeds its reviewed printable bound.")
    if type(value) is float and not math.isfinite(value):
        raise invalid_argument("Non-finite GLB JSON values are unsupported.")
    if type(value) is int and abs(value) > 2**63-1:
        raise invalid_argument("GLB integers exceed their bounded representation.")
    if isinstance(value, dict):
        if {"extensions", "extras", "uri"}.intersection(value):
            _unsupported("GLB external/data URIs, extensions and extras are unsupported; use embedded core buffers/images.")
        for key, child in value.items():
            _json_budget(key, check, depth+1, budget)
            _json_budget(child, check, depth+1, budget)
    elif isinstance(value, list):
        for child in value:
            _json_budget(child, check, depth+1, budget)


def preflight_glb(payload: bytes, check: Callable[[], None] = lambda: None) -> dict:
    try:
        return _preflight_glb(payload, check)
    except (ValueError, TypeError, KeyError, AttributeError, struct.error, OverflowError) as error:
        raise invalid_argument("GLB contains malformed typed core data.") from error


def _preflight_glb(payload: bytes, check: Callable[[], None]) -> dict:
    if not isinstance(payload, bytes) or not 28 <= len(payload) <= MAX_BYTES:
        raise invalid_argument("GLB source must be complete and within 64 MiB.")
    if struct.unpack_from("<4sII", payload) != (b"glTF", 2, len(payload)):
        raise invalid_argument("Expected a complete GLB 2 binary envelope.")
    offset, chunks = 12, []
    while offset < len(payload):
        if offset + 8 > len(payload) or len(chunks) >= 2:
            raise invalid_argument("GLB must contain exactly JSON then BIN chunks.")
        length, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        if length % 4 or offset + length > len(payload):
            raise invalid_argument("GLB chunk alignment or length is invalid.")
        chunks.append((kind, payload[offset:offset+length]))
        offset += length
    if len(chunks) != 2 or chunks[0][0] != 0x4E4F534A or chunks[1][0] != 0x004E4942 or len(chunks[0][1]) > 2*1024*1024:
        raise invalid_argument("GLB requires one bounded JSON chunk and one embedded BIN chunk.")
    try:
        manifest = json.loads(chunks[0][1], object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise invalid_argument("GLB JSON manifest is malformed.") from error
    _json_budget(manifest, check)
    _keys(manifest, {"asset", "buffers", "bufferViews", "accessors", "nodes", "meshes", "materials", "textures", "images", "samplers", "scenes", "scene"})
    _keys(manifest.get("asset"), {"version", "minVersion", "generator", "copyright"})
    if manifest["asset"].get("version") != "2.0" or manifest["asset"].get("minVersion", "2.0") != "2.0":
        _unsupported("Only core GLB 2.0 is reviewed.")
    limits = {"buffers": 1, "bufferViews": 512, "accessors": 512, "nodes": 64, "meshes": 64,
              "materials": 16, "textures": 32, "images": 16, "samplers": 32, "scenes": 1}
    arrays = {}
    for key, maximum in limits.items():
        current = manifest.get(key, [])
        if not isinstance(current, list) or len(current) > maximum or any(not isinstance(item, dict) for item in current):
            raise invalid_argument("GLB inventory exceeds its bounded collection limits.")
        arrays[key] = current
    binary = chunks[1][1]
    if len(arrays["buffers"]) != 1:
        raise invalid_argument("One embedded GLB buffer is required.")
    _keys(arrays["buffers"][0], {"byteLength", "name"})
    buffer_size = _integer(arrays["buffers"][0].get("byteLength"), 1, MAX_BYTES)
    if not buffer_size <= len(binary) <= buffer_size+3:
        raise invalid_argument("GLB BIN chunk disagrees with its declared complete buffer size.")
    views = []
    for view in arrays["bufferViews"]:
        _keys(view, {"buffer", "byteOffset", "byteLength", "byteStride", "target", "name"})
        if type(view.get("buffer")) is not int or view["buffer"] != 0:
            raise invalid_argument("GLB views must reference the one embedded buffer.")
        start = _integer(view.get("byteOffset", 0), 0, buffer_size)
        length = _integer(view.get("byteLength"), 1, buffer_size)
        if start + length > buffer_size:
            raise invalid_argument("GLB view extends beyond its embedded buffer.")
        if "target" in view and view["target"] not in (34962, 34963):
            raise invalid_argument("GLB buffer target must be vertex or index data.")
        stride = view.get("byteStride")
        if stride is not None:
            _integer(stride, 4, 252)
            if stride % 4:
                raise invalid_argument("GLB byte stride must be four-byte aligned.")
        views.append((start, length, stride))
    types = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    components = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
    accessors = []
    total_values = 0
    for accessor in arrays["accessors"]:
        check()
        _keys(accessor, {"bufferView", "byteOffset", "componentType", "count", "type", "min", "max", "name"})
        index = _integer(accessor.get("bufferView"), 0, len(views)-1)
        kind, component = accessor.get("type"), accessor.get("componentType")
        if kind not in types or component not in components:
            _unsupported("GLB accessors support float vectors and unsigned triangle indices only.")
        count = _integer(accessor.get("count"), 1, 300_000)
        total_values += count * types[kind]
        if total_values > 2_000_000:
            raise invalid_argument("GLB decoded accessor component budget exceeded.")
        code, size = components[component]
        start, length, stride = views[index]
        byte_offset = _integer(accessor.get("byteOffset", 0), 0, length)
        width = size * types[kind]
        stride = stride or width
        if stride < width or byte_offset % size or start % size or byte_offset + (count-1)*stride + width > length:
            raise invalid_argument("GLB accessor alignment/stride/count exceeds its view.")
        for key in ("min", "max"):
            if key in accessor:
                _vector(accessor[key], types[kind])
        accessors.append((kind, component, count, start+byte_offset, stride, "<"+code*types[kind]))

    def values(index):
        _kind, component, count, start, stride, layout = accessors[index]
        for number in range(count):
            if number % 256 == 0:
                check()
            value = struct.unpack_from(layout, binary, start+number*stride)
            if component == 5126 and any(not math.isfinite(item) or abs(item) > 1e9 for item in value):
                raise invalid_argument("GLB binary accessor contains non-finite or unbounded values.")
            yield value

    # Validate even unreferenced accessors; malformed bytes do not become admitted
    # merely because the current native importer happens to skip a resource.
    for accessor_index in range(len(accessors)):
        for _ in values(accessor_index):
            pass
    vertices, triangles = 0, 0
    mesh_counts = []
    for mesh in arrays["meshes"]:
        before_vertices, before_triangles = vertices, triangles
        _keys(mesh, {"name", "primitives"})
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not 1 <= len(primitives) <= 16:
            raise invalid_argument("GLB mesh requires 1-16 reviewed triangle primitives.")
        for primitive in primitives:
            _keys(primitive, {"attributes", "indices", "material", "mode"})
            if primitive.get("mode", 4) != 4:
                _unsupported("Only GLB triangle primitives are reviewed.")
            attributes = primitive.get("attributes")
            _keys(attributes, {"POSITION", "NORMAL", "TEXCOORD_0", "TANGENT"})
            position = _integer(attributes.get("POSITION"), 0, len(accessors)-1)
            if accessors[position][:2] != ("VEC3", 5126):
                raise invalid_argument("GLB POSITION must contain FLOAT VEC3 values.")
            count = accessors[position][2]
            vertices += count
            # Enforce aggregate work before walking possibly reused accessors.
            # A small file can reference the same large array in many primitives.
            if vertices > MAX_VERTICES:
                raise invalid_argument("GLB imported mesh vertex budget exceeded.")
            for key, index in attributes.items():
                index = _integer(index, 0, len(accessors)-1)
                expected = {"POSITION": "VEC3", "NORMAL": "VEC3", "TEXCOORD_0": "VEC2", "TANGENT": "VEC4"}[key]
                if accessors[index][:3] != (expected, 5126, count):
                    raise invalid_argument("GLB primitive attributes must match POSITION count and reviewed types.")
                for _ in values(index):
                    pass
            indices = primitive.get("indices")
            index_count = count
            if indices is not None:
                index = _integer(indices, 0, len(accessors)-1)
                kind, component, index_count, *_ = accessors[index]
                if kind != "SCALAR" or component not in {5121, 5123, 5125} or any(item[0] >= count for item in values(index)):
                    raise invalid_argument("GLB triangle indices exceed their primitive vertex inventory.")
            if index_count % 3:
                raise invalid_argument("GLB triangle indices require complete triples.")
            triangles += index_count//3
            if triangles > MAX_TRIANGLES:
                raise invalid_argument("GLB imported triangle budget exceeded.")
            if "material" in primitive:
                material_index = _integer(primitive["material"], 0, len(arrays["materials"])-1)
                if ("baseColorTexture" in arrays["materials"][material_index].get("pbrMetallicRoughness", {})
                        and "TEXCOORD_0" not in attributes):
                    raise invalid_argument("Textured GLB primitives require an explicit first UV map.")
        mesh_counts.append((vertices-before_vertices, triangles-before_triangles))
    for sampler in arrays["samplers"]:
        _keys(sampler, {"magFilter", "minFilter", "wrapS", "wrapT", "name"})
        if sampler.get("magFilter", 9729) not in {9728, 9729} or sampler.get("minFilter", 9987) not in {9728, 9729, 9984, 9985, 9986, 9987} or any(sampler.get(key, 10497) not in {33071, 33648, 10497} for key in ("wrapS", "wrapT")):
            raise invalid_argument("GLB sampler modes are invalid.")
    for texture in arrays["textures"]:
        _keys(texture, {"source", "sampler", "name"})
        _integer(texture.get("source"), 0, len(arrays["images"])-1)
        if "sampler" in texture:
            _integer(texture["sampler"], 0, len(arrays["samplers"])-1)
    pixels, image_records = 0, []
    for image in arrays["images"]:
        _keys(image, {"bufferView", "mimeType", "name"})
        mime = image.get("mimeType")
        if mime not in {"image/png", "image/jpeg"}:
            _unsupported("GLB embedded images must be reviewed PNG/JPEG.")
        view = _integer(image.get("bufferView"), 0, len(views)-1)
        start, length, stride = views[view]
        if stride is not None:
            raise invalid_argument("Embedded image views cannot be interleaved.")
        work = preflight_stream(io.BytesIO(binary[start:start+length]), ".png" if mime == "image/png" else ".jpg", length, check=check)
        while True:
            try:
                next(work)
            except StopIteration as complete:
                record = complete.value
                break
        pixels += record["width"]*record["height"]
        if pixels > MAX_PIXELS:
            raise invalid_argument("GLB aggregate image pixel budget exceeds 4K square.")
        image_records.append(record)
    for material in arrays["materials"]:
        _keys(material, {"name", "pbrMetallicRoughness", "alphaMode", "alphaCutoff", "doubleSided"})
        pbr = material.get("pbrMetallicRoughness", {})
        _keys(pbr, {"baseColorFactor", "baseColorTexture", "metallicFactor", "roughnessFactor"})
        color = pbr.get("baseColorFactor", [1., 1., 1., 1.])
        _vector(color, 4, 1.)
        if any(value < 0 for value in color):
            raise invalid_argument("GLB base color factors must be normalized.")
        for key in ("metallicFactor", "roughnessFactor"):
            value = pbr.get(key, 1.)
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise invalid_argument("GLB PBR constants must be normalized finite values.")
        cutoff = material.get("alphaCutoff", .5)
        if type(cutoff) not in (int, float) or not math.isfinite(cutoff) or not 0 <= cutoff <= 1:
            raise invalid_argument("GLB alpha cutoff must be a normalized finite value.")
        if material.get("alphaMode", "OPAQUE") not in {"OPAQUE", "MASK", "BLEND"} or type(material.get("doubleSided", False)) is not bool:
            raise invalid_argument("GLB material alpha/double-sided mode is invalid.")
        if "baseColorTexture" in pbr:
            _keys(pbr["baseColorTexture"], {"index", "texCoord"})
            _integer(pbr["baseColorTexture"].get("index"), 0, len(arrays["textures"])-1)
            if type(pbr["baseColorTexture"].get("texCoord", 0)) is not int or pbr["baseColorTexture"].get("texCoord", 0) != 0:
                _unsupported("Only the first explicit UV map is reviewed.")
    for node in arrays["nodes"]:
        _keys(node, {"name", "mesh", "children", "matrix", "translation", "rotation", "scale"})
        if "mesh" in node:
            _integer(node["mesh"], 0, len(arrays["meshes"])-1)
        if "matrix" in node and {"translation", "rotation", "scale"}.intersection(node):
            raise invalid_argument("GLB node cannot combine matrix and TRS transforms.")
        for key, count in (("matrix", 16), ("translation", 3), ("rotation", 4), ("scale", 3)):
            if key in node:
                _vector(node[key], count)
        if "rotation" in node and abs(sum(value*value for value in node["rotation"])-1.) > 1e-5:
            raise invalid_argument("GLB node quaternions must have unit length.")
        children = node.get("children", [])
        if not isinstance(children, list) or len(children) > 64:
            raise invalid_argument("GLB node children require a bounded unique list.")
        for child in children:
            _integer(child, 0, len(arrays["nodes"])-1)
        if len(set(children)) != len(children):
            raise invalid_argument("GLB children must be unique.")
    if len(arrays["scenes"]) != 1 or type(manifest.get("scene", 0)) is not int or manifest.get("scene", 0) != 0:
        _unsupported("GLB import requires one explicit source scene.")
    _keys(arrays["scenes"][0], {"name", "nodes"})
    roots = arrays["scenes"][0].get("nodes", [])
    if not isinstance(roots, list) or not roots:
        raise invalid_argument("GLB source scene needs explicit root nodes.")
    seen = set()

    def walk(index, depth, parent=None):
        _integer(index, 0, len(arrays["nodes"])-1)
        if index in seen or depth > 32:
            raise invalid_argument("GLB node graph is cyclic, multiply parented or too deep.")
        seen.add(index)
        matrix = _node_matrix(arrays['nodes'][index])
        if parent is not None:
            matrix = [[sum(parent[row][inner]*matrix[inner][column] for inner in range(4))
                       for column in range(4)] for row in range(4)]
        if any(not math.isfinite(value) or abs(value) > 1e9 for row in matrix for value in row):
            raise invalid_argument('GLB accumulated hierarchy transform exceeds its finite magnitude budget.')
        for child in arrays["nodes"][index].get("children", []):
            walk(child, depth+1, matrix)

    for root in roots:
        walk(root, 0)
    if len(seen) != len(arrays["nodes"]):
        _unsupported("Unused GLB node graphs require a separate import-selection contract.")
    if not seen:
        raise invalid_argument("GLB source scene must contain at least one object.")
    instanced_vertices = sum(mesh_counts[node["mesh"]][0] for node in arrays["nodes"] if "mesh" in node)
    instanced_triangles = sum(mesh_counts[node["mesh"]][1] for node in arrays["nodes"] if "mesh" in node)
    if instanced_vertices > MAX_VERTICES or instanced_triangles > MAX_TRIANGLES:
        raise invalid_argument("GLB mesh instances exceed the aggregate imported geometry budget.")
    return {"format": "GLB", "objects": len(seen), "meshes": len(arrays["meshes"]), "vertices": vertices,
            "triangles": triangles, "instance_vertices": instanced_vertices, "instance_triangles": instanced_triangles,
            "materials": len(arrays["materials"]), "images": image_records,
            "image_pixels": pixels, "animation_present": False, "dependencies": [], "self_contained": True,
            "required_accepted_losses": list(LOSSES)}
