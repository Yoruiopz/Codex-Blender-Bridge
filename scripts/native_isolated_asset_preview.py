"""Private stock-Blender geometry DTO research; no registered tool or child launcher.

Source capture reads literal authored fields. Evaluation, camera creation, rendering
and PNG output happen only in the separate runner-owned worker process.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zlib
from pathlib import Path
from typing import Any

SCHEMA = "stock_geometry_preview_v1"
MAX_VERTICES, MAX_EDGES, MAX_POLYGONS, MAX_CORNERS = 512, 1024, 512, 2048
MAX_BYTES = 2 * 1024 * 1024
SIZE, SAMPLES = 128, 8
LOCAL_LIMIT, LOCATION_LIMIT, WORLD_LIMIT = 1024.0, 8192.0, 65536.0
ROTATION_LIMIT = 16 * math.pi
MIN_SCALE, MAX_SCALE = 1e-4, 64.0
DEFAULT_DELTAS = {"delta_location": (0., 0., 0.), "delta_rotation_euler": (0., 0., 0.),
                  "delta_rotation_quaternion": (1., 0., 0., 0.), "delta_scale": (1., 1., 1.)}


class PreviewRefused(ValueError):
    """Unsupported research input; never a claim of rollback or public permission."""


def _require(value: Any, message: str) -> None:
    if not value:
        raise PreviewRefused(message)


def _keys(value: Any, expected: set[str]) -> None:
    _require(type(value) is dict and set(value) == expected, "Unexpected DTO keys or container")


def _name(value: Any) -> str:
    _require(type(value) is str and value and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value), "Exact name required")
    try:
        _require(len(value.encode("utf-8")) <= 63, "Name exceeds native UTF-8 bound")
    except UnicodeError as exc:
        raise PreviewRefused("Invalid UTF-8 name") from exc
    return value


def _bits(value: Any, limit: float) -> str:
    _require(type(value) in {int, float}, "Finite numeric channel required")
    _require(abs(value) <= limit and math.isfinite(value), "Numeric magnitude outside profile")
    try:
        raw = struct.pack("<f", value)
    except (OverflowError, struct.error) as exc:
        raise PreviewRefused("Channel is not native Float32 safe") from exc
    _require(math.isfinite(struct.unpack("<f", raw)[0]), "Nonfinite native Float32")
    return raw.hex()


def _float(value: Any, limit: float) -> float:
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{8}", value), "Exact Float32 hex required")
    result = struct.unpack("<f", bytes.fromhex(value))[0]
    _require(math.isfinite(result) and abs(result) <= limit, "Unsafe Float32 value")
    return result


def _vector(values: Any, count: int, limit: float) -> list[float]:
    _require(type(values) is list and len(values) == count, "Unexpected vector shape")
    return [_float(x, limit) for x in values]


def canonical(value: dict[str, Any]) -> bytes:
    """Call after typed validation; no arbitrary objects or executable payloads."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def make_dto(name: str, vertices: Any, edges: Any, polygons: Any, *,
             location=(0., 0., 0.), rotation=(0., 0., 0.), scale=(1., 1., 1.)) -> dict[str, Any]:
    for rows, minimum, maximum in ((vertices, 3, MAX_VERTICES), (edges, 3, MAX_EDGES),
                                    (polygons, 1, MAX_POLYGONS)):
        _require(type(rows) in {list, tuple} and minimum <= len(rows) <= maximum,
                 "Geometry count outside profile")
    for row in vertices:
        _require(type(row) in {list, tuple} and len(row) == 3, "Unexpected source vertex shape")
    for row in edges:
        _require(type(row) in {list, tuple} and len(row) == 2, "Unexpected source edge shape")
    _require(all(type(row) in {list, tuple} and 3 <= len(row) <= 64 for row in polygons) and
             sum(len(row) for row in polygons) <= MAX_CORNERS, "Corner budget exceeded")
    for channels in (location, rotation, scale):
        _require(type(channels) in {list, tuple} and len(channels) == 3, "Unexpected source transform shape")
    value = {"schema": SCHEMA, "object_name": _name(name),
             "mesh": {"vertices": [[_bits(x, LOCAL_LIMIT) for x in v] for v in vertices],
                      "edges": [list(e) for e in edges], "polygons": [list(p) for p in polygons]},
             "transform": {"rotation_mode": "XYZ", "location": [_bits(x, LOCATION_LIMIT) for x in location],
                           "rotation_euler": [_bits(x, ROTATION_LIMIT) for x in rotation],
                           "scale": [_bits(x, MAX_SCALE) for x in scale],
                           **{k: [_bits(x, MAX_SCALE) for x in v] for k, v in DEFAULT_DELTAS.items()}},
             "render": {"width": SIZE, "height": SIZE, "samples": SAMPLES,
                        "style": "opaque_flat_geometry"}}
    return validate_dto(value)


def validate_dto(value: Any) -> dict[str, Any]:
    _keys(value, {"schema", "object_name", "mesh", "transform", "render"})
    _require(value["schema"] == SCHEMA, "Unsupported geometry schema")
    _name(value["object_name"])
    mesh, transform = value["mesh"], value["transform"]
    _keys(mesh, {"vertices", "edges", "polygons"})
    _keys(transform, {"rotation_mode", "location", "rotation_euler", "scale", *DEFAULT_DELTAS})
    _require(transform["rotation_mode"] == "XYZ", "Only authored XYZ transforms are supported")
    for name, limit in (("location", LOCATION_LIMIT), ("rotation_euler", ROTATION_LIMIT)):
        _vector(transform[name], 3, limit)
    scales = _vector(transform["scale"], 3, MAX_SCALE)
    _require(all(abs(x) >= MIN_SCALE for x in scales), "Degenerate source scale")
    for key, expected in DEFAULT_DELTAS.items():
        _vector(transform[key], len(expected), MAX_SCALE)
        _require(transform[key] == [_bits(x, MAX_SCALE) for x in expected], "Nondefault delta transform")
    _keys(value["render"], {"width", "height", "samples", "style"})
    _require(value["render"] == {"width": SIZE, "height": SIZE, "samples": SAMPLES,
                                  "style": "opaque_flat_geometry"}, "Fixed render profile required")
    for name in ("width", "height", "samples"):
        _require(type(value["render"][name]) is int, "Exact render integer required")
    for name, minimum, maximum in (("vertices", 3, MAX_VERTICES), ("edges", 3, MAX_EDGES),
                                    ("polygons", 1, MAX_POLYGONS)):
        _require(type(mesh[name]) is list and minimum <= len(mesh[name]) <= maximum,
                 "Geometry count outside profile")
    for vertex in mesh["vertices"]:
        _vector(vertex, 3, LOCAL_LIMIT)
    count = len(mesh["vertices"])
    seen = set()
    for edge in mesh["edges"]:
        _require(type(edge) is list and len(edge) == 2 and all(type(i) is int and 0 <= i < count for i in edge)
                 and edge[0] != edge[1], "Invalid edge")
        pair = tuple(sorted(edge))
        _require(pair not in seen, "Duplicate edge")
        seen.add(pair)
    corners = 0
    for polygon in mesh["polygons"]:
        _require(type(polygon) is list and 3 <= len(polygon) <= 64 and
                 all(type(i) is int and 0 <= i < count for i in polygon) and
                 len(set(polygon)) == len(polygon), "Invalid polygon")
        corners += len(polygon)
        _require(corners <= MAX_CORNERS, "Corner budget exceeded")
        _require(all(tuple(sorted((polygon[i - 1], polygon[i]))) in seen for i in range(len(polygon))),
                 "Polygon boundary missing from edges")
    points = _world_points(value)
    bounds = _bounds(points)
    extent = max(b - a for a, b in zip(bounds["min"], bounds["max"], strict=True))
    magnitude = max(abs(x) for p in points for x in p)
    _require(extent >= max(1e-4, magnitude * 2**-16), "Geometry below preview precision floor")
    raw = canonical(value)
    _require(len(raw) <= MAX_BYTES, "DTO byte budget exceeded")
    return json.loads(raw)


def _world_points(dto: dict[str, Any]) -> list[list[float]]:
    t = dto["transform"]
    location = _vector(t["location"], 3, LOCATION_LIMIT)
    angles = _vector(t["rotation_euler"], 3, ROTATION_LIMIT)
    scale = _vector(t["scale"], 3, MAX_SCALE)
    cx, cy, cz = (math.cos(x) for x in angles)
    sx, sy, sz = (math.sin(x) for x in angles)
    result = []
    for raw in dto["mesh"]["vertices"]:
        x, y, z = (v * s for v, s in zip(_vector(raw, 3, LOCAL_LIMIT), scale, strict=True))
        y, z = cx * y - sx * z, sx * y + cx * z
        x, z = cy * x + sy * z, -sy * x + cy * z
        x, y = cz * x - sz * y, sz * x + cz * y
        p = [a + b for a, b in zip((x, y, z), location, strict=True)]
        _require(all(math.isfinite(v) and abs(v) <= WORLD_LIMIT for v in p), "Unsafe world-space bounds")
        result.append(p)
    return result


def _bounds(points: list[list[float]]) -> dict[str, list[float]]:
    return {"min": [min(p[i] for p in points) for i in range(3)],
            "max": [max(p[i] for p in points) for i in range(3)]}


def world_bounds(dto: dict[str, Any]) -> dict[str, list[float]]:
    return _bounds(_world_points(dto))


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _normal(v) -> list[float]:
    length = math.sqrt(_dot(v, v))
    return [x / length for x in v]


def camera_fit(dto: dict[str, Any]) -> dict[str, Any]:
    bounds = world_bounds(dto)
    center = [(a + b) * .5 for a, b in zip(bounds["min"], bounds["max"], strict=True)]
    back = _normal((1.5, -2.5, 1.8))
    right = _normal((-back[1], back[0], 0.))
    up = [back[1] * right[2] - back[2] * right[1],
          back[2] * right[0] - back[0] * right[2],
          back[0] * right[1] - back[1] * right[0]]
    points = _world_points(dto)
    relative = [[a - b for a, b in zip(p, center, strict=True)] for p in points]
    radius = max(math.sqrt(_dot(p, p)) for p in relative)
    half = max(max(abs(_dot(p, axis)) for p in relative) for axis in (right, up))
    distance = radius * 4 + 1.
    return {"center": center, "right": right, "up": up, "back": back,
            "location": [a + distance * b for a, b in zip(center, back, strict=True)],
            "ortho_scale": max(half * 2 * 1.3, .001),
            "clip_start": max(.0001, distance - radius * 2), "clip_end": distance + radius * 4 + 1.}


def projected_bounds(dto: dict[str, Any], fit: dict[str, Any]) -> dict[str, list[float]]:
    points = []
    for p in _world_points(dto):
        relative = [a - b for a, b in zip(p, fit["center"], strict=True)]
        points.append([2 * _dot(relative, axis) / fit["ortho_scale"] for axis in (fit["right"], fit["up"])])
    return {"min": [min(p[i] for p in points) for i in range(2)],
            "max": [max(p[i] for p in points) for i in range(2)]}


def _schema(bpy: Any, owner: Any, family: str, fields: dict[str, tuple[str, int | None]]) -> None:
    _require(type(owner) is getattr(bpy.types, family), "Exact native RNA class required")
    rna = type(owner).bl_rna
    _require(rna.identifier == family, "Native RNA class identity changed")
    for name, (kind, length) in fields.items():
        p = rna.properties.get(name)
        _require(p is not None and p.identifier == name and p.is_runtime is False and p.type == kind,
                 "Unsupported or runtime RNA descriptor")
        if kind in {"FLOAT", "INT", "BOOLEAN"}:
            _require(type(p.array_length) is int and p.array_length == length, "Native numeric shape changed")


def capture(bpy: Any, object_name: str) -> dict[str, Any]:
    """Literal named data only; intentionally contains no context/evaluated getter."""
    _name(object_name)
    obj = bpy.data.objects.get(object_name)
    _require(obj is not None, "Named Object missing")
    object_fields = {"name": ("STRING", None), "type": ("ENUM", None), "mode": ("ENUM", None),
                     "data": ("POINTER", None), "library": ("POINTER", None), "override_library": ("POINTER", None),
                     "parent": ("POINTER", None), "modifiers": ("COLLECTION", None),
                     "constraints": ("COLLECTION", None), "animation_data": ("POINTER", None),
                     "rotation_mode": ("ENUM", None), "location": ("FLOAT", 3),
                     "rotation_euler": ("FLOAT", 3), "scale": ("FLOAT", 3),
                     **{k: ("FLOAT", len(v)) for k, v in DEFAULT_DELTAS.items()}}
    _schema(bpy, obj, "Object", object_fields)
    _require(obj.name == object_name and obj.type == "MESH" and obj.mode == "OBJECT" and
             obj.library is None and obj.override_library is None and obj.parent is None and
             len(obj.modifiers) == len(obj.constraints) == 0 and obj.animation_data is None and
             obj.rotation_mode == "XYZ", "Unsupported source Object profile")
    for key, expected in DEFAULT_DELTAS.items():
        actual = tuple(getattr(obj, key))
        _require([_bits(v, MAX_SCALE) for v in actual] == [_bits(v, MAX_SCALE) for v in expected],
                 "Nondefault delta transform")
    mesh = obj.data
    _schema(bpy, mesh, "Mesh", {"library": ("POINTER", None), "override_library": ("POINTER", None),
             "animation_data": ("POINTER", None), "shape_keys": ("POINTER", None),
             "is_editmode": ("BOOLEAN", 0), "users": ("INT", 0), "vertices": ("COLLECTION", None),
             "edges": ("COLLECTION", None), "polygons": ("COLLECTION", None)})
    _require(mesh.library is None and mesh.override_library is None and mesh.animation_data is None and
             mesh.shape_keys is None and mesh.is_editmode is False and mesh.users == 1,
             "Edit/shared/animated Mesh buffers are unsupported")
    _require(3 <= len(mesh.vertices) <= MAX_VERTICES and 3 <= len(mesh.edges) <= MAX_EDGES and
             1 <= len(mesh.polygons) <= MAX_POLYGONS, "Geometry outside capture budget")
    # Screen every bounded element descriptor before any geometry payload getter.
    # Dynamic face vertices have static RNA reflection length 3 in both pinned
    # sources; each actual polygon's dynamic length is independently bounded below.
    for collection, family, fields in ((mesh.vertices, "MeshVertex", {"co": ("FLOAT", 3)}),
                                       (mesh.edges, "MeshEdge", {"vertices": ("INT", 2)}),
                                       (mesh.polygons, "MeshPolygon", {"vertices": ("INT", 3)})):
        for owner in collection:
            _schema(bpy, owner, family, fields)
    vertices, edges, polygons = [], [], []
    for v in mesh.vertices:
        vertices.append(tuple(v.co))
    for e in mesh.edges:
        edges.append(tuple(e.vertices))
    corners = 0
    for p in mesh.polygons:
        corners += len(p.vertices)
        _require(corners <= MAX_CORNERS and len(p.vertices) <= 64, "Corner budget exceeded")
        polygons.append(tuple(p.vertices))
    return make_dto(object_name, vertices, edges, polygons, location=tuple(obj.location),
                    rotation=tuple(obj.rotation_euler), scale=tuple(obj.scale))


def validate_png(data: bytes) -> dict[str, Any]:
    """Independent bounded PNG decoding/CRC/alpha evidence; not artistic approval."""
    _require(type(data) is bytes and 8 < len(data) <= MAX_BYTES and data[:8] == b"\x89PNG\r\n\x1a\n",
             "Invalid PNG envelope")
    offset, compressed, header, ended = 8, bytearray(), None, False
    while offset < len(data):
        _require(offset + 12 <= len(data), "Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        _require(length <= MAX_BYTES and offset + length + 12 <= len(data), "PNG chunk outside bounds")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        _require(zlib.crc32(kind + payload) & 0xffffffff == crc, "PNG CRC differs")
        if header is None:
            _require(kind == b"IHDR" and length == 13, "PNG must start with IHDR")
            header = struct.unpack(">IIBBBBB", payload)
            _require(header == (SIZE, SIZE, 8, 6, 0, 0, 0), "Expected fixed noninterlaced RGBA8 PNG")
        elif kind == b"IHDR":
            raise PreviewRefused("Duplicate PNG header")
        elif kind == b"IDAT":
            _require(not ended and len(compressed) + length <= MAX_BYTES, "PNG data budget exceeded")
            compressed.extend(payload)
        elif kind == b"IEND":
            _require(length == 0 and offset + 12 == len(data), "Invalid PNG end")
            ended = True
        else:
            _require(kind[:1].islower(), "Unsupported critical PNG chunk")
        offset += length + 12
    _require(ended and compressed, "Incomplete PNG")
    expected = SIZE * (1 + SIZE * 4)
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(compressed, expected + 1)
    except zlib.error as exc:
        raise PreviewRefused("Invalid PNG compressed stream") from exc
    _require(len(raw) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
             "PNG decompression size/trailing stream mismatch")
    previous, points = bytearray(SIZE * 4), []
    for y in range(SIZE):
        start = y * (1 + SIZE * 4)
        mode, row = raw[start], bytearray(raw[start + 1:start + 1 + SIZE * 4])
        _require(mode <= 4, "Unknown PNG filter")
        for i in range(len(row)):
            a, b, c = (row[i - 4] if i >= 4 else 0), previous[i], (previous[i - 4] if i >= 4 else 0)
            if mode == 1:
                row[i] = (row[i] + a) & 255
            elif mode == 2:
                row[i] = (row[i] + b) & 255
            elif mode == 3:
                row[i] = (row[i] + (a + b) // 2) & 255
            elif mode == 4:
                p = a + b - c
                distances = (abs(p - a), abs(p - b), abs(p - c))
                predictor = (a, b, c)[distances.index(min(distances))]
                row[i] = (row[i] + predictor) & 255
        points.extend((x, y) for x in range(SIZE) if row[x * 4 + 3] >= 128)
        previous = row
    _require(points, "PNG contains no opaque geometry")
    bounds = [min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points)]
    _require(bounds[0] >= 2 and bounds[1] >= 2 and bounds[2] < SIZE - 2 and bounds[3] < SIZE - 2,
             "Geometry clipped at PNG boundary")
    return {"width": SIZE, "height": SIZE, "foreground_pixels": len(points), "alpha_bbox": bounds,
            "sha256": hashlib.sha256(data).hexdigest(), "visual_review_performed": False}


def render_worker(bpy: Any, value: Any, output: Path) -> dict[str, Any]:
    """Fixed trusted worker code only. The source process must never call this."""
    _require(bpy.app.background is True, "Render only in the runner-owned background worker")
    _require(isinstance(output, Path), "Owned output Path required")
    _require(output.is_absolute() and not output.is_symlink() and output.parent.resolve(strict=True) == output.parent,
             "Canonical owned worker output required")
    dto = validate_dto(value)
    _require(not output.exists(), "Worker output exists")
    from mathutils import Matrix

    mesh = bpy.data.meshes.new("Isolated Preview Worker Mesh")
    vertices = [_vector(v, 3, LOCAL_LIMIT) for v in dto["mesh"]["vertices"]]
    mesh.from_pydata(vertices, dto["mesh"]["edges"], dto["mesh"]["polygons"])
    obj = bpy.data.objects.new("Isolated Preview Worker Object", mesh)
    scene = bpy.data.scenes.new("Isolated Preview Worker Scene")
    scene.collection.objects.link(obj)
    t = dto["transform"]
    obj.rotation_mode = "XYZ"
    for name in ("location", "rotation_euler", "scale", *DEFAULT_DELTAS):
        setattr(obj, name, _vector(t[name], 4 if name == "delta_rotation_quaternion" else 3,
                                  LOCATION_LIMIT if name == "location" else
                                  ROTATION_LIMIT if name == "rotation_euler" else MAX_SCALE))
    actual_vertices = [[_bits(x, LOCAL_LIMIT) for x in v.co] for v in mesh.vertices]
    _require(actual_vertices == dto["mesh"]["vertices"], "Reconstructed vertex bits differ")
    _require(sorted(tuple(sorted(e.vertices)) for e in mesh.edges) ==
             sorted(tuple(sorted(e)) for e in dto["mesh"]["edges"]), "Reconstructed complete edge set differs")
    _require([list(p.vertices) for p in mesh.polygons] == dto["mesh"]["polygons"], "Reconstructed faces differ")
    for name in ("location", "rotation_euler", "scale", *DEFAULT_DELTAS):
        _require([struct.pack("<f", x).hex() for x in getattr(obj, name)] == t[name], "Worker raw channels differ")
    # A single new opaque geometry material; original material appearance is not copied.
    material = bpy.data.materials.new("Isolated Preview Worker Opaque")
    material.diffuse_color = (.55, .7, .9, 1.)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (.55, .7, .9, 1.)
    bsdf.inputs["Roughness"].default_value = .65
    mesh.materials.append(material)
    for p in mesh.polygons:
        p.use_smooth = False
    camera_data = bpy.data.cameras.new("Isolated Preview Worker Camera")
    camera = bpy.data.objects.new("Isolated Preview Worker Camera", camera_data)
    scene.collection.objects.link(camera)
    fit = camera_fit(dto)
    camera_rows = [[*(fit[axis][i] for axis in ("right", "up", "back")), fit["location"][i]] for i in range(3)]
    camera_rows.append([0., 0., 0., 1.])
    camera.matrix_world = Matrix(camera_rows)
    camera_data.type = "ORTHO"
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.ortho_scale = fit["ortho_scale"]
    camera_data.clip_start, camera_data.clip_end = fit["clip_start"], fit["clip_end"]
    scene.camera = camera
    light_data = bpy.data.lights.new("Isolated Preview Worker Area", "AREA")
    light = bpy.data.objects.new("Isolated Preview Worker Area", light_data)
    scene.collection.objects.link(light)
    light.matrix_world = camera.matrix_world.copy()
    light_data.energy, light_data.size = 1000., max(fit["ortho_scale"], 1.)
    world = bpy.data.worlds.new("Isolated Preview Worker World")
    world.use_nodes = True
    world.node_tree.nodes.get("Background").inputs["Color"].default_value = (.1, .1, .1, 1.)
    scene.world = world
    scene.render.engine = "CYCLES"
    scene.cycles.device, scene.cycles.samples = "CPU", SAMPLES
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.seed = 0
    scene.render.threads_mode, scene.render.threads = "FIXED", 1
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode, scene.render.image_settings.color_depth = "RGBA", "8"
    scene.render.filepath = str(output)
    scene.render.use_file_extension = False
    scene.render.use_stamp = False
    # Explicit worker-only evaluation; never used for the source capture.
    scene.view_layers[0].update()
    observed = [list(obj.matrix_world @ v.co) for v in mesh.vertices]
    expected = _world_points(dto)
    _require(all(abs(a - b) <= max(1e-5, abs(b) * 2**-19)
                 for p, q in zip(observed, expected, strict=True) for a, b in zip(p, q, strict=True)),
             "Worker world bounds differ from independently composed input")
    _require(bpy.ops.render.render(write_still=True, scene=scene.name) == {"FINISHED"}, "Worker render failed")
    png = validate_png(output.read_bytes())
    return {"input_sha256": hashlib.sha256(canonical(dto)).hexdigest(), "geometry_reconstructed": True,
            "raw_channels_reconstructed": True,
            "raw_channel_scope": ["location", "rotation_mode", "rotation_euler", "scale", *DEFAULT_DELTAS],
            "inactive_rotation_channels_copied": False, "edge_identity_scope": "Complete undirected edge set, not native edge allocation/order",
            "world_bounds": _bounds(observed), "camera_fit": fit, "projected_bounds": projected_bounds(dto, fit),
            "png": png, "render_engine": "CYCLES", "device": "CPU", "samples": SAMPLES,
            "source_process_contacted": False, "source_restore_writes": 0,
            "original_material_appearance_copied": False, "project_saved": False}
