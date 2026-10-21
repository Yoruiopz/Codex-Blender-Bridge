"""Frozen orthographic surface projection into a new image version.

Geometry is read-only. Private UV raster/visibility/stencil work yields; the
existing image scheduler owns transport, deadlines, checkpoints and publication.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from array import array
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import islice

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import reject_unknown_params, require_blender
from ..uv_geometry import intersection_area
from . import image_masks, image_paint, images
from . import pixel_brush as brush
from .material_scope import local_editable

REQUIRED = (Permission.EDIT_MATERIALS, Permission.INSPECT_SCENE)
MAX_PIXELS = 1_048_576
MAX_VERTICES, MAX_FACES, MAX_LOOPS = 4096, 2048, 12288
MAX_TARGET_TRIANGLES, MAX_TOTAL_TRIANGLES = 512, 1024
MAX_CANDIDATES, MAX_RAY_TESTS, MAX_STROKE_TESTS = 2_000_000, 2_000_000, 2_000_000
UV_EPSILON = 1e-12


@dataclass(frozen=True)
class Triangle:
    object_id: int
    face: int
    world: tuple
    uv: tuple | None


def _id(value):
    return int(value.as_pointer()) if hasattr(value, "as_pointer") else id(value)


def _number(raw, name, low, high):
    return brush.number(raw, name, low, high)


def _vector(raw, name, length, low=-1e9, high=1e9):
    if not isinstance(raw, (list, tuple)) or len(raw) != length:
        raise invalid_argument(f"{name} must contain {length} finite numbers.")
    return tuple(_number(value, name, low, high) for value in raw)


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _unit(value, name):
    length = math.sqrt(_dot(value, value))
    if length < 1e-12:
        raise invalid_argument(f"{name} must be nonzero and independent.")
    return tuple(item/length for item in value)


def projector_spec(raw):
    if not isinstance(raw, Mapping):
        raise invalid_argument("projector must be an explicit orthographic world frame.")
    fields = {"origin", "direction", "up", "width", "height", "near", "far"}
    reject_unknown_params(raw, fields)
    if set(raw) != fields:
        raise invalid_argument("projector requires origin/direction/up/width/height/near/far.")
    direction = _unit(_vector(raw["direction"], "direction", 3), "direction")
    right = _unit(_cross(direction, _unit(_vector(raw["up"], "up", 3), "up")), "projector axes")
    up = _cross(right, direction)
    near = _number(raw["near"], "near", 0., 1e6)
    far = _number(raw["far"], "far", 1e-8, 1e6)
    if far <= near:
        raise invalid_argument("Projector far must exceed near.")
    width = _number(raw["width"], "width", 1e-8, 1e6)
    height = _number(raw["height"], "height", 1e-8, 1e6)
    return {"origin": _vector(raw["origin"], "origin", 3), "direction": direction,
            "right": right, "up": up, "width": width, "height": height, "near": near, "far": far,
            "depth_epsilon": max(1e-6, max(width, height, far-near)*1e-7)}


def _authority(context, job=None):
    context.require(*REQUIRED)
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    if job is not None:
        job.lifetime.check()
        if job.cancel_reason or time.monotonic() >= job.deadline:
            raise BridgeError(ErrorCode.TIMEOUT, "Surface image job stopped before publication.")
    state = getattr(context, "state", None)
    if state is not None:
        flags = state.snapshot()
        if flags["emergency_stopped"] or flags["paused"]:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags["emergency_stopped"] else ErrorCode.AGENT_PAUSED,
                              "Surface image painting stopped before its next safe action.")


def _gate(context):
    _authority(context)
    if getattr(context, "check_cancelled", None):
        context.check_cancelled()
    _authority(context)


class _ContextView:
    def __init__(self, base, check):
        self.base, self.check_cancelled = base, check

    def __getattr__(self, key):
        return getattr(self.base, key)


def _mesh_record(bpy, name, uv_name=None):
    matches = list(islice((obj for obj in bpy.data.objects if obj.name == name), 2))
    if len(matches) != 1:
        raise invalid_argument("Projection object is missing or ambiguous.", object_name=name)
    obj = matches[0]
    if obj.type != "MESH" or obj.mode != "OBJECT" or getattr(obj.data, "is_editmode", False):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Projection requires Object Mode base meshes.")
    if obj.parent is not None or len(obj.constraints) or obj.animation_data is not None or getattr(obj.data, "animation_data", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Initial projection requires independent unanimated objects/mesh data; parent/constraint/driver evaluation is not inferred.")
    if len(obj.modifiers) or obj.data.shape_keys is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Projection does not infer evaluated modifier/shape-key correspondence.")
    if (obj.hide_viewport or obj.hide_get() or bpy.context.view_layer.objects.get(name) != obj):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Projection meshes must be visible in the current view layer.")
    mesh = obj.data
    if (len(mesh.vertices) > MAX_VERTICES or len(mesh.polygons) > MAX_FACES or len(mesh.loops) > MAX_LOOPS
            or len(mesh.edges) > 8192 or len(obj.material_slots) > 128):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Projection base mesh exceeds its bounded geometry window.")
    positions = [_vector(tuple(vertex.co), "vertex coordinate", 3) for vertex in mesh.vertices]
    matrix = tuple(_vector(tuple(row), "world matrix", 4) for row in obj.matrix_world)
    if len(matrix) != 4 or matrix[3] != (0., 0., 0., 1.):
        raise invalid_argument("An affine world matrix is required.")
    determinant = _dot(matrix[0][:3], _cross(matrix[1][:3], matrix[2][:3]))
    if determinant <= 1e-12:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Projection currently requires a nonsingular positive-determinant world transform.")
    world = [tuple(sum(matrix[row][column]*point[column] for column in range(3))+matrix[row][3] for row in range(3)) for point in positions]
    if any(not math.isfinite(value) or abs(value) > 1e12 for point in world for value in point):
        raise invalid_argument("Transformed projection coordinates exceed the finite world bound.")
    layer = mesh.uv_layers.get(uv_name) if uv_name is not None else None
    if uv_name is not None and layer is None:
        raise invalid_argument("The explicit projection UV layer does not exist.")
    uv = [_vector(tuple(item.uv), "UV coordinate", 2, 0., 1.) for item in layer.data] if layer is not None else None
    if uv is not None and len(uv) != len(mesh.loops):
        raise invalid_argument("Projection UV loops are incomplete.")
    snapshot = {"object_id": _id(obj), "mesh_id": _id(mesh), "object_name": obj.name, "mesh_name": mesh.name,
                "mesh_users": int(mesh.users), "matrix": matrix, "positions": positions,
                "transform_channels": (tuple(obj.location), obj.rotation_mode, tuple(obj.rotation_euler),
                                       tuple(obj.rotation_quaternion), tuple(obj.rotation_axis_angle), tuple(obj.scale),
                                       tuple(obj.delta_location), tuple(obj.delta_rotation_euler), tuple(obj.delta_rotation_quaternion), tuple(obj.delta_scale)),
                "loops": [loop.vertex_index for loop in mesh.loops],
                "edges": [tuple(edge.vertices) for edge in mesh.edges],
                "faces": [(tuple(face.vertices), bool(face.hide), face.material_index) for face in mesh.polygons],
                "materials": [(_id(slot.material) if slot.material else None, slot.link) for slot in obj.material_slots],
                "uv_name": uv_name, "uv": uv, "object_visible": True}
    mesh.calc_loop_triangles()
    if len(mesh.loop_triangles) > MAX_TOTAL_TRIANGLES:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Projection tessellation exceeds 1024 triangles.")
    triangles = [Triangle(_id(obj), item.polygon_index,
                          tuple(world[mesh.loops[loop].vertex_index] for loop in item.loops),
                          tuple(uv[loop] for loop in item.loops) if uv is not None else None)
                 for item in mesh.loop_triangles]
    counts = Counter(triangle.face for triangle in triangles)
    if any(counts[index] != len(face.vertices)-2 for index, face in enumerate(mesh.polygons)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Projection requires complete native base-face tessellation.")
    return snapshot, triangles


def _strokes(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 32:
        raise invalid_argument("strokes must contain 1-32 bounded projected strokes.")
    parsed, segments = [], 0
    for item in raw:
        if not isinstance(item, Mapping):
            raise invalid_argument("Every projected stroke must be an object.")
        reject_unknown_params(item, {"points", "radius_world", "hardness", "color", "opacity", "blend"})
        points = item.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= 128:
            raise invalid_argument("Projected strokes require 1-128 normalized projector points.")
        points = [_vector(point, "projector point", 2, 0., 1.) for point in points]
        segments += max(1, len(points)-1)
        if segments > 256:
            raise invalid_argument("Projected painting supports at most 256 stroke segments.")
        blend = item.get("blend", "MIX")
        if not isinstance(blend, str) or blend not in {"MIX", "ERASE_ALPHA"}:
            raise invalid_argument("Projected blend must be MIX or ERASE_ALPHA.")
        color = _vector(item.get("color"), "stroke color", 4, 0., 16.)
        if color[3] > 1:
            raise invalid_argument("Stroke alpha must be within [0,1].")
        parsed.append({"points": points, "radius": _number(item.get("radius_world"), "radius_world", 1e-8, 1e6),
                       "hardness": _number(item.get("hardness", .8), "hardness", 0., 1.), "color": color,
                       "opacity": _number(item.get("opacity", 1.), "opacity", 0., 1.), "blend": blend})
    return parsed


def prepare_surface(context, params):
    fields = {"image_name", "new_name", "object_name", "uv_layer", "face_indices", "projector", "strokes", "stencil", "occluder_objects"}
    reject_unknown_params(params, fields)
    source_name, new_name = images._name(params, "image_name"), images._name(params, "new_name")
    object_name, uv_name = images._name(params, "object_name"), images._name(params, "uv_layer")
    projector, strokes = projector_spec(params.get("projector")), _strokes(params.get("strokes"))
    stencil_spec = image_masks.specification(params.get("stencil"))
    faces = params.get("face_indices")
    if (not isinstance(faces, list) or not 1 <= len(faces) <= 256
            or any(type(index) is not int or index < 0 for index in faces) or len(set(faces)) != len(faces)):
        raise invalid_argument("face_indices must contain 1-256 unique explicit base-face indices.")
    occluders = params.get("occluder_objects", [])
    if (not isinstance(occluders, list) or len(occluders) > 8 or any(not isinstance(name, str) for name in occluders)
            or len(set(occluders)) != len(occluders) or object_name in occluders):
        raise invalid_argument("occluder_objects must contain at most 8 distinct additional mesh names.")
    occluders = [images._name({"name": name}, "name") for name in occluders]
    _gate(context)
    bpy = require_blender()
    images._object_mode(bpy)
    source = images.image_exact(bpy, source_name)
    if bpy.data.images.get(new_name) is not None:
        raise invalid_argument("The new image name is occupied; no overwrite or automatic rename.")
    images.binding_source(context, source)
    role, srgb = image_paint.source_role(source)
    if role == "DATA" and any(stroke["blend"] != "MIX" or any(value > 1 for value in stroke["color"]) for stroke in strokes):
        raise invalid_argument("DATA projection supports MIX RGBA [0,1] only.")
    values, width, height, file = image_paint._read(context, source, modifying=True, maximum_pixels=MAX_PIXELS)
    stencil = image_masks.freeze(context, bpy, stencil_spec, read=image_paint._read, maximum_pixels=MAX_PIXELS,
                                source=source, source_values=values, source_file=file)
    records, target_triangles = [], []
    for name, layer in [(object_name, uv_name), *((name, None) for name in occluders)]:
        _gate(context)
        record, triangles = _mesh_record(bpy, name, layer)
        records.append(record)
        if name == object_name:
            target_triangles = triangles
        else:
            target_triangles.extend(triangles)
    target_count = sum(triangle.object_id == records[0]["object_id"] for triangle in target_triangles)
    if target_count > MAX_TARGET_TRIANGLES or len(target_triangles) > MAX_TOTAL_TRIANGLES:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Projection supports at most 512 target / 1024 total opaque triangles.")
    if any(index >= len(records[0]["faces"]) or records[0]["faces"][index][1] for index in faces):
        raise invalid_argument("Projection face scope is absent or hidden.")
    prepared = {"source": source, "source_name": source_name, "name": new_name, "width": width, "height": height,
                "values": values, "source_digest": brush.digest(values), "source_file": file,
                "source_identity": image_masks.identity(source), "source_metadata": image_masks.metadata(source),
                "role": role, "srgb": srgb, "associated": image_paint.source_associated(source), "mask": stencil,
                "projector": projector, "strokes": strokes, "records": records, "triangles": target_triangles,
                "target_id": records[0]["object_id"], "faces": frozenset(faces), "tests": 0}
    _gate(context)
    # Refresh derived world transforms only after bounded finite geometry validation.
    # Recollect after update, because dependency-graph callbacks may change inputs.
    bpy.context.view_layer.update()
    refreshed = [_mesh_record(bpy, frozen["object_name"], frozen["uv_name"]) for frozen in records]
    prepared["records"] = [record for record, _ in refreshed]
    prepared["triangles"] = [triangle for _, triangles in refreshed for triangle in triangles]
    prepared["target_id"] = prepared["records"][0]["object_id"]
    if (sum(triangle.object_id == prepared["target_id"] for triangle in prepared["triangles"]) > MAX_TARGET_TRIANGLES
            or len(prepared["triangles"]) > MAX_TOTAL_TRIANGLES):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Refreshed projection exceeds 512 target / 1024 total triangles.")
    if any(index >= len(prepared["records"][0]["faces"]) or prepared["records"][0]["faces"][index][1] for index in faces):
        raise invalid_argument("Refreshed projection face scope is absent or hidden.")
    _gate(context)
    validate_inputs(_ContextView(context, None), prepared)
    return prepared


def validate_inputs(context, prepared):
    _authority(context)
    bpy = require_blender()
    images._object_mode(bpy)
    for frozen in prepared["records"]:
        record, _triangles = _mesh_record(bpy, frozen["object_name"], frozen["uv_name"])
        if record != frozen:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Projection geometry/UV/transform/consumer scope changed.", {"stale_geometry": True})
    source = images.image_exact(bpy, prepared["source_name"])
    if image_masks.identity(source) != prepared["source_identity"] or image_masks.metadata(source) != prepared["source_metadata"]:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Projection image identity/metadata changed.", {"stale_source": True})
    image_paint.source_role(source)
    values, w, h, file = image_paint._read(context, source, modifying=True, maximum_pixels=MAX_PIXELS)
    if (w, h, file, brush.digest(values)) != (prepared["width"], prepared["height"], prepared["source_file"], prepared["source_digest"]):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Projection image pixels or approved FILE proof changed.", {"stale_source": True})
    image_masks.validate(context, bpy, prepared.get("mask"), read=image_paint._read)


def _bary(point, uv):
    a, b, c = uv
    denominator = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(denominator) <= UV_EPSILON:
        raise invalid_argument("Degenerate UV triangles are not supported.")
    first = ((b[1]-c[1])*(point[0]-c[0])+(c[0]-b[0])*(point[1]-c[1]))/denominator
    second = ((c[1]-a[1])*(point[0]-c[0])+(a[0]-c[0])*(point[1]-c[1]))/denominator
    return first, second, 1-first-second


def sample_stencil(mask, u, v):
    if u < 0 or u > 1 or v < 0 or v > 1:
        return 0.
    width, height = mask["width"], mask["height"]
    x, y = max(0., min(width-1., u*width-.5)), max(0., min(height-1., v*height-.5))
    x0, y0 = math.floor(x), math.floor(y)
    x1, y1 = min(x0+1, width-1), min(y0+1, height-1)
    a, b, values = x-x0, y-y0, mask["values"]
    value = (values[y0*width+x0]*(1-a)+values[y0*width+x1]*a)*(1-b)+(values[y1*width+x0]*(1-a)+values[y1*width+x1]*a)*b
    return 1-value if mask["invert"] else value


def ray_triangle(origin, direction, triangle):
    a, b, c = triangle.world
    edge1, edge2 = _sub(b, a), _sub(c, a)
    h = _cross(direction, edge2)
    determinant = _dot(edge1, h)
    if abs(determinant) < 1e-12:
        return None
    inverse = 1/determinant
    s = _sub(origin, a)
    u = inverse*_dot(s, h)
    if u < -1e-10 or u > 1+1e-10:
        return None
    q = _cross(s, edge1)
    v = inverse*_dot(direction, q)
    if v < -1e-10 or u+v > 1+1e-10:
        return None
    distance = inverse*_dot(edge2, q)
    return distance if distance >= 0 else None


def _world_bary(point, triangle):
    a, b, c = triangle.world
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(point, a)
    aa, bb, cc = _dot(ab, ab), _dot(ab, ac), _dot(ac, ac)
    denominator = aa*cc-bb*bb
    if denominator <= 0:
        raise invalid_argument("Numerically unresolved world triangle correspondence.")
    second = (cc*_dot(ap, ab)-bb*_dot(ap, ac))/denominator
    third = (aa*_dot(ap, ac)-bb*_dot(ap, ab))/denominator
    return 1-second-third, second, third


def _coverage(u, v, stroke, projector):
    point = (u*projector["width"], v*projector["height"])
    points = [(a*projector["width"], b*projector["height"]) for a, b in stroke["points"]]
    distance = float("inf")
    for a, b in zip(points, points[1:] or points, strict=len(points) == 1):
        delta, relative = _sub(b, a), _sub(point, a)
        length = _dot(delta, delta)
        t = max(0., min(1., _dot(relative, delta)/length)) if length else 0.
        distance = min(distance, math.hypot(*(relative[i]-t*delta[i] for i in range(2))))
    if distance >= stroke["radius"]:
        return 0.
    fraction = 1. if distance <= stroke["radius"]*stroke["hardness"] else (stroke["radius"]-distance)/(stroke["radius"]*(1-stroke["hardness"]))
    return fraction*fraction*(3-2*fraction)*stroke["opacity"]


def projection_steps(prepared, check=lambda: None):
    """CPU-only frozen geometry, overlap, raster, visibility and image calculations."""
    triangles, target_id = prepared["triangles"], prepared["target_id"]
    targets = [(index, triangle) for index, triangle in enumerate(triangles) if triangle.object_id == target_id]
    selected = [(index, triangle) for index, triangle in targets if triangle.face in prepared["faces"]]
    for count, triangle in enumerate(triangles):
        check()
        normal = _cross(_sub(triangle.world[1], triangle.world[0]), _sub(triangle.world[2], triangle.world[0]))
        if _dot(normal, normal) <= 1e-24:
            raise invalid_argument("Degenerate world triangles are not supported for projection/occlusion.")
        if triangle.uv is not None:
            _bary(triangle.uv[0], triangle.uv)
        yield {"phase": "validating_geometry", "completed": count+1, "total": len(triangles)}
    pairs = 0
    for offset, (_index, first) in enumerate(targets):
        for _other_index, second in targets[offset+1:]:
            if first.face not in prepared["faces"] and second.face not in prepared["faces"]:
                continue
            pairs += 1
            if pairs % 64 == 0:
                check()
                yield {"phase": "checking_uv_overlap", "completed": pairs, "total": len(targets)*(len(targets)-1)//2}
            area, epsilon = intersection_area(first.uv, second.uv)
            if area > epsilon:
                raise invalid_argument("Scoped UV faces overlap another target face; no projected version allocated.")
    width, height = prepared["width"], prepared["height"]
    stencil = prepared["mask"]["kernel"] if prepared.get("mask") else None
    if stencil is not None:
        for index, value in enumerate(stencil["values"]):
            if index % 256 == 0:
                check()
                yield {"phase": "validating_stencil", "completed": index, "total": len(stencil["values"])}
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise invalid_argument("Complete selected stencil channel must be finite within [0,1].")
    result, _ = yield from brush.paint_steps(prepared["values"], width, height, [], prepared["role"],
                                            srgb=prepared["srgb"], associated=prepared["associated"], check=check)
    baseline = array("f", result)
    owners = array("i", [-1])*(width*height)
    projector, strokes = prepared["projector"], prepared["strokes"]
    candidates = ray_tests = stroke_tests = visible = occluded = backfacing = 0
    for triangle_index, triangle in selected:
        minimum = [max(0, math.ceil(min(uv[axis] for uv in triangle.uv)*(width, height)[axis]-.5)) for axis in range(2)]
        maximum = [min((width, height)[axis]-1, math.floor(max(uv[axis] for uv in triangle.uv)*(width, height)[axis]-.5)) for axis in range(2)]
        normal = _cross(_sub(triangle.world[1], triangle.world[0]), _sub(triangle.world[2], triangle.world[0]))
        front = _dot(normal, projector["direction"]) < -1e-12
        for y in range(minimum[1], maximum[1]+1):
            for x in range(minimum[0], maximum[0]+1):
                candidates += 1
                if candidates > MAX_CANDIDATES:
                    raise invalid_argument("Projection exceeds 2M UV candidate tests; narrow resolution/face scope.")
                if candidates % 128 == 0:
                    check()
                    yield {"phase": "projecting", "completed": candidates, "total": MAX_CANDIDATES}
                uv = ((x+.5)/width, (y+.5)/height)
                bary = _bary(uv, triangle.uv)
                if min(bary) < -1e-10:
                    continue
                world = tuple(sum(bary[i]*triangle.world[i][axis] for i in range(3)) for axis in range(3))
                pixel = y*width+x
                if owners[pixel] >= 0:
                    prior = triangles[owners[pixel]]
                    old_bary = _bary(uv, prior.uv)
                    old_world = tuple(sum(old_bary[i]*prior.world[i][axis] for i in range(3)) for axis in range(3))
                    if math.dist(world, old_world) > projector["depth_epsilon"]:
                        raise invalid_argument("A texel centre maps to distinct surface points on a UV boundary.")
                    old_normal = _cross(_sub(prior.world[1], prior.world[0]), _sub(prior.world[2], prior.world[0]))
                    if front != (_dot(old_normal, projector["direction"]) < -1e-12):
                        raise invalid_argument("UV-boundary samples have ambiguous front-facing classification.")
                    continue
                owners[pixel] = triangle_index
                if not front:
                    backfacing += 1
                    continue
                relative = _sub(world, projector["origin"])
                u = .5+_dot(relative, projector["right"])/projector["width"]
                v = .5+_dot(relative, projector["up"])/projector["height"]
                depth = _dot(relative, projector["direction"])
                if not (0 <= u <= 1 and 0 <= v <= 1 and projector["near"] <= depth <= projector["far"]):
                    continue
                coverages = []
                for stroke in strokes:
                    old_stroke_tests = stroke_tests
                    stroke_tests += max(1, len(stroke["points"])-1)
                    if stroke_tests > MAX_STROKE_TESTS:
                        raise invalid_argument("Projection exceeds 2M stroke-segment tests.")
                    value = _coverage(u, v, stroke, projector)
                    if stroke_tests//128 != old_stroke_tests//128:
                        check()
                        yield {"phase": "stroke_coverage", "completed": stroke_tests, "total": MAX_STROKE_TESTS}
                    if stencil is not None:
                        value *= sample_stencil(stencil, u, v)
                    coverages.append(value)
                if not any(coverages):
                    continue
                origin = tuple(world[axis]-projector["direction"][axis]*(depth-projector["near"]) for axis in range(3))
                hits = []
                for other in triangles:
                    ray_tests += 1
                    if ray_tests > MAX_RAY_TESTS:
                        raise invalid_argument("Projection exceeds 2M visibility triangle tests; narrow footprint/occluders.")
                    if ray_tests % 128 == 0:
                        check()
                        yield {"phase": "checking_visibility", "completed": ray_tests, "total": MAX_RAY_TESTS}
                    distance = ray_triangle(origin, projector["direction"], other)
                    if distance is not None and distance <= depth-projector["near"]+projector["depth_epsilon"]:
                        hits.append((distance, other))
                if not hits:
                    raise invalid_argument("The projected point has no independently verified surface ray hit.")
                nearest = min(distance for distance, _ in hits)
                if nearest < depth-projector["near"]-projector["depth_epsilon"]:
                    occluded += 1
                    continue
                if any(other.object_id != target_id for distance, other in hits if abs(distance-nearest) <= projector["depth_epsilon"]):
                    raise invalid_argument("Coincident target/occluder visibility is ambiguous.")
                if any(other is not triangle and (min(bary) > 1e-10 or min(_world_bary(world, other)) > 1e-10)
                       for distance, other in hits if abs(distance-nearest) <= projector["depth_epsilon"]):
                    raise invalid_argument("Coincident target triangle interiors have ambiguous visibility.")
                visible += 1
                offset = pixel*4
                for stroke, value in zip(strokes, coverages, strict=True):
                    color = stroke["color"]
                    if prepared["role"] == "DATA":
                        for channel in range(4):
                            result[offset+channel] = result[offset+channel]*(1-value)+color[channel]*value
                    elif value:
                        value *= color[3]
                        if stroke["blend"] == "ERASE_ALPHA":
                            result[offset+3] *= 1-value
                        else:
                            alpha = value+result[offset+3]*(1-value)
                            if alpha:
                                for channel in range(3):
                                    result[offset+channel] = (color[channel]*value+result[offset+channel]*result[offset+3]*(1-value))/alpha
                            result[offset+3] = alpha
    changed, examples = 0, []
    for pixel in range(width*height):
        if pixel % 256 == 0:
            check()
            yield {"phase": "comparing", "completed": pixel, "total": width*height}
        if any(result[pixel*4+channel] != baseline[pixel*4+channel] for channel in range(4)):
            changed += 1
            if len(examples) < 64:
                examples.append([pixel % width, pixel//width])
    prepared["tests"] = candidates
    return result, {"painted_pixels": changed, "changed_pixel_examples": examples, "examples_truncated": changed > len(examples),
                    "candidate_pixel_tests": candidates, "visibility_triangle_tests": ray_tests, "stroke_segment_tests": stroke_tests,
                    "visible_painted_candidates": visible, "occluded_candidates": occluded, "backfacing_candidates": backfacing,
                    "uv_overlap_pairs_checked": pairs, "shared_uv_boundary_samples_deduplicated": True,
                    "source_srgb_converted_to_linear": prepared["srgb"], "source_associated_converted_to_straight": prepared["associated"],
                    "private_pixel_buffers_peak_estimate_bytes": 3*len(result)*result.itemsize+len(owners)*owners.itemsize+(len(stencil["values"])*4 if stencil else 0),
                    "estimate_excludes": "Geometry/plan Python objects, input readbacks, Blender/native/GPU/undo/file buffers and allocator overhead"}


def _commit_context(context, prepared, job=None):
    quiet = _ContextView(context, None)
    def check():
        _gate(context)
        validate_inputs(quiet, prepared)
        _authority(quiet, job)
    return _ContextView(context, check)


def _owned_output_guard(context, prepared, job=None):
    """Keep the actual allocation private across native callbacks and setters."""
    quiet = _ContextView(context, None)
    frozen_identity = None
    def guard(image):
        nonlocal frozen_identity
        _authority(quiet, job)
        bpy = require_blender()
        actual = image_masks.identity(image)
        if frozen_identity is None:
            frozen_identity = actual
        if (actual != frozen_identity or image.name != prepared["name"] or not local_editable(image)
                or image.source != "GENERATED" or not image.is_float or image.channels != 4
                or tuple(image.size) != (prepared["width"], prepared["height"])
                or image.users != 0 or image.use_fake_user or getattr(image, "animation_data", None) is not None):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "New projected output lost its exact private allocation scope.", {"stale_output": True})
        current = images.image_exact(bpy, prepared["name"])
        if image_masks.identity(current) != frozen_identity:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "New projected output name resolves to another image.", {"stale_output": True})
        user_map = getattr(bpy.data, "user_map", None)
        if user_map is None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Complete native incoming-ID consumer evidence is unavailable.")
        if next(iter(user_map(subset={image}).get(image, ())), None) is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "New projected output acquired an incoming ID consumer.", {"stale_output": True})
        _authority(quiet, job)
    return guard


def publish(context, prepared, output, job=None):
    result, evidence = output
    _gate(context)
    validate_inputs(_ContextView(context, None), prepared)
    if require_blender().data.images.get(prepared["name"]) is not None:
        raise invalid_argument("Projected image name became occupied before publication.")
    guarded = _commit_context(context, prepared, job)
    if job is not None:
        job.execution_started = True
    output_guard = _owned_output_guard(context, prepared, job)
    new = image_paint._new(guarded, require_blender(), prepared["name"], prepared["width"], prepared["height"], prepared["role"], result,
                           owned_output_guard=output_guard)
    try:
        _gate(guarded)
        validate_inputs(_ContextView(context, None), prepared)
        output_guard(new)
    except Exception as exc:
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Projected version exists but frozen input preservation failed; inspect retained output and inputs.",
                          {"execution_started": True, "possible_mutation": True, "retained_image_name": new.name,
                           "verification_required": True}) from exc
    stencil = image_masks.evidence(prepared.get("mask"))
    if stencil is not None:
        stencil["sampling"] = "Projector-normalized pixel-centre bilinear, edge-clamped inside projector; outside zero even when inverted"
    return {"painted_image": images._summary(new), "source_image": prepared["source_name"], "role": prepared["role"],
            "source_pixels_sha256_float32_le": prepared["source_digest"], "pixels_sha256_float32_le": brush.digest(result),
            "source_pixels_unchanged": True, "geometry_and_uv_inputs_unchanged": True, "stencil": stencil,
            "projection": "ORTHOGRAPHIC_WORLD_FRAME_TO_BASE_UV_TEXEL_CENTRES", "projector": prepared["projector"],
            "opaque_occlusion_objects": [item["object_name"] for item in prepared["records"]],
            "occlusion_scope": "Complete target base mesh plus explicit opaque occluders; other scene objects and material transparency are not inferred",
            "geometry_fingerprints": [{"object": item["object_name"], "mesh_id": item["mesh_id"], "vertices": len(item["positions"]), "uv_layer": item["uv_name"],
                                        "geometry_uv_sha256": hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()} for item in prepared["records"]],
            "source_file_at_read": prepared["source_file"], **evidence, "file_written": False, "bound_to_nodes": False,
            "project_saved": False, "verification_required": True, "full_texture_paint_workflow_verified": False}


class SurfacePaintDriver:
    def __init__(self, prepared):
        self.prepared = prepared
        self.last_image_name = None

    def steps(self, context, job, native_commit):
        output = yield from projection_steps(self.prepared, lambda: _gate(context))
        _gate(context)
        validate_inputs(_ContextView(context, None), self.prepared)
        def commit():
            try:
                result = publish(context, self.prepared, output, job)
            except BridgeError as error:
                self.last_image_name = error.context.get("retained_image_name")
                raise
            self.last_image_name = result["painted_image"]["name"]
            return result
        return native_commit(commit)

    def evidence(self):
        return {"file_published": False, "external_file_written": False,
                "last_observed_projected_image_name": self.last_image_name,
                "post_commit_image_cleanup": "explicit_recovery_required" if self.last_image_name else "no_completed_publication_observed"}

    def cleanup(self, context, job, *, success):
        return self.evidence()


def paint_surface_version(context, params):
    prepared = prepare_surface(context, params)
    work = projection_steps(prepared, lambda: _gate(context))
    try:
        while True:
            try:
                next(work)
            except StopIteration as completed:
                return publish(context, prepared, completed.value)
    finally:
        work.close()


def paint_surface_job_start(context, params):
    values = dict(params)
    time_limit = values.pop("time_limit_seconds", 60.)
    if getattr(context, "jobs", None) is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cooperative image jobs are unavailable.")
    return context.jobs.start_surface_paint(context, values, time_limit)


def register_tools(registry):
    registry.register("image.paint_surface_version", paint_surface_version, toolset="materials", modifies=True, permissions=REQUIRED,
                      description="Project bounded orthographic world strokes/raw stencils through explicit opaque geometry into a NEW UV image, preserving source/geometry; verify pixels and appearance.")
    registry.register("image.paint_surface_job_start", paint_surface_job_start, toolset="materials", modifies=True, permissions=REQUIRED,
                      automatic_checkpoint=False, batchable=False,
                      description="Freeze bounded surface-paint inputs, then yield private overlap/projection/visibility/stencil work in the existing image job lifecycle; poll final pixel/recovery evidence.")
