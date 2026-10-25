"""Read-only generated-image UV samples for explicit base-mesh sculpt masks."""

from __future__ import annotations

import hashlib
import logging
import math
import struct
from array import array
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry, check_final_mutation
from ..utils import bool_param, reject_unknown_params, require_blender
from . import image_masks, pixel_brush

LOGGER = logging.getLogger(__name__)
METHOD = "mesh.sculpt_mask_sample"
MAX_VERTICES = 100_000
MAX_EDGES = 200_000
MAX_LOOPS = 300_000
MAX_PIXELS = pixel_brush.MAX_PIXELS
CHANNELS = {"R": 0, "G": 1, "B": 2, "A": 3}


def _name(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 63
        or any(ord(char) < 32 for char in value)
    ):
        raise invalid_argument(f"'{field}' must be a non-empty name of at most 63 UTF-8 bytes.")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise invalid_argument(f"'{field}' must be valid UTF-8 text.") from exc
    if len(encoded) > 63:
        raise invalid_argument(f"'{field}' must fit 63 UTF-8 bytes.")
    return value


def _parameters(params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(
        params,
        {
            "object_name",
            "uv_layer",
            "vertex_indices",
            "image_name",
            "channel",
            "invert",
            "corner_reduction",
        },
    )
    result = {
        field: _name(params.get(field), field)
        for field in ("object_name", "uv_layer", "image_name")
    }
    indices = params.get("vertex_indices")
    if (
        not isinstance(indices, list)
        or not 1 <= len(indices) <= 1024
        or any(type(value) is not int or not 0 <= value < MAX_VERTICES for value in indices)
        or len(set(indices)) != len(indices)
    ):
        raise invalid_argument(
            "vertex_indices must contain 1-1024 distinct integers from 0 to 99,999."
        )
    channel = params.get("channel", "R")
    reduction = params.get("corner_reduction")
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise invalid_argument("channel must be R, G, B or A.")
    if not isinstance(reduction, str) or reduction not in {"MIN", "MAX", "MEAN"}:
        raise invalid_argument("corner_reduction must explicitly select MIN, MAX or MEAN.")
    result.update(
        vertex_indices=list(indices),
        channel=channel,
        invert=bool_param(params, "invert", False),
        corner_reduction=reduction,
    )
    return result


def _check_request(context: ToolContext) -> None:
    """Scheduler-owned pure hooks; no live providers during a frozen read."""
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    for name in ("check_final_request", "check_final_job"):
        hook = getattr(context, name, None)
        if hook is not None:
            hook()


def _pure(context: ToolContext, spec: Any) -> None:
    if spec is None:
        # Direct read-only helper calls have no registry binding. Normal dispatch
        # always retains the exact registered nonmodifying spec below.
        _check_request(context)
    else:
        check_final_mutation(context, METHOD, expected_spec=spec)


def _live(context: ToolContext, spec: Any) -> None:
    context.require(Permission.INSPECT_SCENE)
    callback = getattr(context, "check_cancelled", None)
    if callback is not None:
        callback()
    context.require(Permission.INSPECT_SCENE)
    _pure(context, spec)


def _identity(owner: Any) -> tuple | None:
    if owner is None:
        return None
    pointer = int(owner.as_pointer()) if hasattr(owner, "as_pointer") else id(owner)
    return pointer, getattr(owner, "session_uid", None), str(getattr(owner, "name", ""))


def _exact(items: Any, name: str, label: str) -> Any:
    if len(items) > 4096:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED, f"{label} lookup exceeds the 4096-data-block read budget."
        )
    matches = list(islice((item for item in items if item.name == name), 2))
    if len(matches) != 1:
        raise invalid_argument(f"The named {label} is missing or ambiguous.")
    return matches[0]


def _float32(value: Any, label: str) -> float:
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Nonfinite native input")
        return struct.unpack("<f", struct.pack("<f", number))[0]
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED, f"{label} must contain finite Float32 values."
        ) from exc


def _context(bpy: Any) -> tuple:
    native = bpy.context
    # Explicit object/UV/image names need neither selection nor active-object
    # lookup. Some native context getters can normalize stored selection; do
    # not read selected_objects or view_layer just to observe them here.
    scene = native.scene
    return _identity(scene), native.mode, int(scene.frame_current), float(scene.frame_subframe)


def _scope(context: ToolContext, bpy: Any, request: dict) -> tuple[dict, dict[int, list[tuple]]]:
    obj = _exact(bpy.data.objects, request["object_name"], "mesh object")
    if obj.type != "MESH" or obj.data is None:
        raise invalid_argument("The explicit object must be a mesh.")
    mesh = obj.data
    if bpy.context.mode != "OBJECT" or obj.mode != "OBJECT" or getattr(mesh, "is_editmode", False):
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "Sculpt-mask sampling reads Object Mode base-mesh UVs without changing modes.",
        )
    vertices, edges, loops, faces = mesh.vertices, mesh.edges, mesh.loops, mesh.polygons
    if (
        len(vertices) > MAX_VERTICES
        or len(edges) > MAX_EDGES
        or len(loops) > MAX_LOOPS
        or len(faces) > MAX_LOOPS
        or len(mesh.uv_layers) > 16
        or len(obj.material_slots) > 64
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED, "Base mesh exceeds the bounded sculpt-mask read budget."
        )
    if any(index >= len(vertices) for index in request["vertex_indices"]):
        raise invalid_argument("A requested vertex is outside the named base mesh.")
    layer = _exact(mesh.uv_layers, request["uv_layer"], "UV layer")
    if len(layer.data) != len(loops):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED, "UV data must cover every base-mesh corner exactly."
        )
    geometry, topology, uv_digest = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    topology.update(struct.pack("<IIII", len(vertices), len(edges), len(loops), len(faces)))
    for ordinal, vertex in enumerate(vertices):
        if ordinal % 1024 == 0:
            _check_request(context)
        values = tuple(_float32(value, "Base-mesh coordinates") for value in vertex.co)
        if len(values) != 3:
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED, "Base-mesh coordinates must be three-dimensional."
            )
        geometry.update(struct.pack("<fff", *values))
    for ordinal, edge in enumerate(edges):
        if ordinal % 1024 == 0:
            _check_request(context)
        pair = tuple(edge.vertices)
        if len(pair) != 2 or any(
            type(index) is not int or not 0 <= index < len(vertices) for index in pair
        ):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Base-mesh edge indices are inconsistent.")
        topology.update(struct.pack("<II", *pair))
    corners: dict[int, list[tuple]] = {index: [] for index in request["vertex_indices"]}
    for ordinal, loop in enumerate(loops):
        if ordinal % 1024 == 0:
            _check_request(context)
        index = loop.vertex_index
        if type(index) is not int or not 0 <= index < len(vertices):
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED, "Base-mesh corner indices are inconsistent."
            )
        topology.update(struct.pack("<I", index))
        uv = tuple(_float32(value, "UV coordinates") for value in layer.data[ordinal].uv)
        if len(uv) != 2:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV data must contain coordinate pairs.")
        uv_digest.update(struct.pack("<ff", *uv))
        if index in corners:
            if any(value < 0.0 or value > 1.0 for value in uv):
                raise BridgeError(
                    ErrorCode.NOT_IMPLEMENTED,
                    "Requested UV corners must be within [0,1]; wrapping and UDIM mapping are not inferred.",
                )
            corners[index].append(uv)
    offset = 0
    for ordinal, face in enumerate(faces):
        if ordinal % 1024 == 0:
            _check_request(context)
        start, count = face.loop_start, face.loop_total
        if (
            type(start) is not int
            or type(count) is not int
            or start != offset
            or count < 3
            or start + count > len(loops)
        ):
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED, "Base-mesh face/corner ranges are inconsistent."
            )
        topology.update(struct.pack("<II", start, count))
        offset += count
    if offset != len(loops) or any(not values for values in corners.values()):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Every requested vertex must have at least one valid UV face corner.",
        )
    frozen = {
        "object": _identity(obj),
        "mesh": _identity(mesh),
        "uv_layer": _identity(layer),
        "object_mode": obj.mode,
        "mesh_users": int(mesh.users),
        "library": (
            _identity(getattr(obj, "library", None)),
            _identity(getattr(mesh, "library", None)),
        ),
        "override": (
            _identity(getattr(obj, "override_library", None)),
            _identity(getattr(mesh, "override_library", None)),
        ),
        "geometry_sha256_float32_le": geometry.hexdigest(),
        "topology_sha256": topology.hexdigest(),
        "uv_sha256_float32_le": uv_digest.hexdigest(),
        "counts": [len(vertices), len(edges), len(loops), len(faces)],
        "material_slots": tuple(
            (_identity(slot.material), slot.link) for slot in obj.material_slots
        ),
        "context": _context(bpy),
    }
    return frozen, corners


def _image(bpy: Any, name: str) -> tuple[Any, dict]:
    image = _exact(bpy.data.images, name, "image")
    if (
        getattr(image, "library", None) is not None
        or getattr(image, "override_library", None) is not None
        or image.source != "GENERATED"
        or image.type != "UV_TEST"
        or image.channels != 4
        or not image.has_data
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Sculpt masks support loaded local GENERATED four-channel RGBA images only.",
        )
    animation = getattr(image, "animation_data", None)
    if animation is not None and (
        getattr(animation, "action", None) is not None
        or len(getattr(animation, "drivers", ()))
        or len(getattr(animation, "nla_tracks", ()))
    ):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Sculpt-mask images must be unanimated.")
    size = tuple(image.size)
    if (
        len(size) != 2
        or any(type(value) is not int or not 1 <= value <= 4096 for value in size)
        or size[0] * size[1] > MAX_PIXELS
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Sculpt masks support at most 16,777,216 pixels with dimensions 1-4096.",
        )
    if len(image.pixels) != size[0] * size[1] * 4:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED, "The complete loaded RGBA buffer must match its dimensions."
        )
    metadata = {
        "identity": _identity(image),
        "size": size,
        "source": image.source,
        "type": image.type,
        "channels": int(image.channels),
        "colorspace": str(image.colorspace_settings.name),
        "alpha_mode": str(image.alpha_mode),
        "is_float": bool(image.is_float),
        "is_dirty": bool(image.is_dirty),
        "has_data": bool(image.has_data),
    }
    return image, metadata


def _pixels(context: ToolContext, image: Any, width: int, height: int) -> array:
    _check_request(context)
    values = array("f", [0.0]) * (width * height * 4)
    try:
        image.pixels.foreach_get(values)
    except Exception as exc:
        LOGGER.exception("Generated sculpt-mask pixel read failed")
        raise BridgeError(
            ErrorCode.OPERATION_FAILED, "The complete generated mask buffer could not be read."
        ) from exc
    _check_request(context)
    return values


def sample_uv(values: array, width: int, height: int, uv: tuple, invert: bool) -> float:
    """Normalized UV pixel centres, bilinear interpolation and clamped edges."""
    x = max(0.0, min(width - 1.0, uv[0] * width - 0.5))
    y = max(0.0, min(height - 1.0, uv[1] * height - 0.5))
    x0, y0 = math.floor(x), math.floor(y)
    x1, y1 = min(x0 + 1, width - 1), min(y0 + 1, height - 1)
    a, b = x - x0, y - y0
    bottom = values[y0 * width + x0] * (1 - a) + values[y0 * width + x1] * a
    top = values[y1 * width + x0] * (1 - a) + values[y1 * width + x1] * a
    value = max(0.0, min(1.0, bottom * (1 - b) + top * b))
    return 1.0 - value if invert else value


def sculpt_mask_sample(context: ToolContext, params: Mapping[str, Any]) -> dict:
    request = _parameters(params)
    registry = getattr(context, "registry", None)
    spec = registry.get(METHOD) if registry is not None else None
    if spec is not None and (spec.modifies or spec.handler is not sculpt_mask_sample):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "The exact registered read-only sculpt-mask handler is required.",
        )
    _live(context, spec)
    bpy = require_blender()
    frozen, corners = _scope(context, bpy, request)
    image, metadata = _image(bpy, request["image_name"])
    width, height = metadata["size"]
    _pure(context, spec)
    values = _pixels(context, image, width, height)
    _pure(context, spec)
    pixels_digest = pixel_brush.digest(values)
    _pure(context, spec)
    channel = image_masks.channel_copy(
        values, CHANNELS[request["channel"]], check=lambda: _pure(context, spec)
    )
    del values
    for ordinal, value in enumerate(channel):
        if ordinal % 1024 == 0:
            _pure(context, spec)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "The complete selected raw mask channel must be finite and within [0,1].",
            )
    channel_digest = pixel_brush.digest(channel)
    _pure(context, spec)
    weights, corner_counts, seams = [], [], []
    for index in request["vertex_indices"]:
        _check_request(context)
        uvs = corners[index]

        def samples(rows=uvs):
            for ordinal, uv in enumerate(rows):
                if ordinal % 1024 == 0:
                    _check_request(context)
                yield sample_uv(channel, width, height, uv, request["invert"])

        reduction = request["corner_reduction"]
        weight = (
            min(samples())
            if reduction == "MIN"
            else max(samples())
            if reduction == "MAX"
            else math.fsum(samples()) / len(uvs)
        )
        weights.append(weight)
        corner_counts.append(len(uvs))
        if any(uv != uvs[0] for uv in uvs[1:]):
            seams.append(index)
    _live(context, spec)
    # No providers or arbitrary cancellation callbacks may follow these complete
    # input reads. The final check is the canonical pure lifecycle/identity gate.
    try:
        current_request = _parameters(params)
        current_image, current_metadata = _image(bpy, request["image_name"])
        current_values = _pixels(context, current_image, *current_metadata["size"])
        _same_image, metadata_after_read = _image(bpy, request["image_name"])
        current, _corners = _scope(context, bpy, request)
    except BridgeError as exc:
        if exc.code not in {
            ErrorCode.INVALID_ARGUMENT.value,
            ErrorCode.INVALID_MODE.value,
            ErrorCode.NOT_IMPLEMENTED.value,
        }:
            raise
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Sculpt-mask inputs changed during the read; resample.",
            {"stale_mask_inputs": True},
        ) from exc
    _pure(context, spec)
    if (
        current_request != request
        or current != frozen
        or current_metadata != metadata
        or metadata_after_read != metadata
        or pixel_brush.digest(current_values) != pixels_digest
    ):
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Sculpt-mask image, UV, topology or context changed during the read; resample.",
            {"stale_mask_inputs": True},
        )
    _pure(context, spec)
    return {
        "object": request["object_name"],
        "uv_layer": request["uv_layer"],
        "image_name": request["image_name"],
        "channel": request["channel"],
        "invert": request["invert"],
        "corner_reduction": request["corner_reduction"],
        "vertex_indices": request["vertex_indices"],
        "mask_weights": weights,
        "corner_counts": corner_counts,
        "seam_vertices": seams,
        "input_evidence": {
            "image_pixels_sha256_float32_le": pixels_digest,
            "channel_sha256_float32_le": channel_digest,
            "uv_sha256_float32_le": frozen["uv_sha256_float32_le"],
            "topology_sha256": frozen["topology_sha256"],
            "geometry_sha256_float32_le": frozen["geometry_sha256_float32_le"],
            "image_size": list(metadata["size"]),
            "colorspace": metadata["colorspace"],
            "alpha_mode": metadata["alpha_mode"],
            "complete_pixels_and_inputs_unchanged": True,
            "image_identity_session_only": True,
        },
        "sampling": {
            "coordinate_space": "NORMALIZED_UV",
            "filter": "BILINEAR_PIXEL_CENTRE",
            "edge_mode": "CLAMP",
            "value_space": "RAW_STORED_CHANNEL",
            "color_alpha_transform": False,
            "invert_before_corner_reduction": True,
        },
        "snapshot_only": True,
        "live_image_binding": False,
        "resample_after": "Image pixels/metadata, UV, geometry or topology changes",
        "geometry_modified": False,
        "image_modified": False,
        "scene_evaluated": False,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        METHOD,
        sculpt_mask_sample,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="mesh",
        modifies=False,
        description="Sample a loaded generated image through explicit base-mesh UV corners into snapshot sculpt-mask weights; no edits or live binding.",
    )
