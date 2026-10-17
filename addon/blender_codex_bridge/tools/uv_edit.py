"""Direct, face-corner UV authoring without operators or selection changes."""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, int_param, reject_unknown_params
from ._mesh_safety import require_local_single_user_mesh
from .interaction import _active_edit_mesh
from .mesh import _id_name

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

MAX_CORNERS = 20_000
MAX_UV = 1_000_000.0


@dataclass(frozen=True)
class CornerEdit:
    face_index: int
    corner_index: int
    loop: Any
    uv: tuple[float, float] | None = None
    pinned: bool | None = None


def _pair(value: Any, parameter: str) -> tuple[float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
        raise invalid_argument(f"'{parameter}' must contain two finite numbers.")
    result = tuple(float_param({parameter: item}, parameter, 0, minimum=-MAX_UV, maximum=MAX_UV) for item in value)
    # Match Blender's storage exactly, so postcondition checks are not tolerance guesses.
    return struct.unpack("<ff", struct.pack("<ff", *result))


def _scope(params: Mapping[str, Any], *, require_reference: bool = False) -> tuple[Any, Any, Any, list[Any]]:
    name = _id_name(params.get("object_name"), "object_name")
    layer_name = _id_name(params.get("uv_layer"), "uv_layer")
    selection_id = params.get("selection_id")
    if selection_id is not None and (not isinstance(selection_id, str) or not selection_id):
        raise invalid_argument("'selection_id' must be a non-empty string.")
    if require_reference and not selection_id:
        raise invalid_argument("Coordinate indices require a fresh face selection_id from inspection/selection.")
    _bpy, obj, bm, _sequences = _active_edit_mesh(name)
    require_local_single_user_mesh(obj)
    layer = bm.loops.layers.uv.get(layer_name)
    if layer is None:
        raise invalid_argument("The named UV layer does not exist.", uv_layer=layer_name)
    reference = validate_selection_reference(selection_id, obj, bm) if selection_id else None
    faces = [bm.faces[i] for i in reference["faces"]] if reference else [face for face in bm.faces if face.select]
    if not faces or sum(len(face.loops) for face in faces) > MAX_CORNERS:
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Select faces totaling 1-20,000 UV corners.")
    if any(face.hide or any(loop.vert.hide or loop.edge.hide for loop in face.loops) for face in faces):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "UV editing does not affect hidden scoped geometry.")
    return obj, bm, layer, faces


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _corners(params: Mapping[str, Any], faces: list[Any]) -> list[tuple[Any, int, Any]]:
    requested = params.get("corners")
    if requested is None:
        return [(face, index, loop) for face in faces for index, loop in enumerate(face.loops)]
    if not isinstance(requested, list) or not 1 <= len(requested) <= MAX_CORNERS:
        raise invalid_argument("'corners' must contain 1-20,000 unique face/corner records.")
    scoped = {face.index: face for face in faces}
    seen = set()
    resolved = []
    for record in requested:
        if not isinstance(record, Mapping) or set(record) != {"face_index", "corner_index"}:
            raise invalid_argument("Each corner requires exactly face_index and corner_index.")
        face_index = int_param(record, "face_index", 0, minimum=0, maximum=200_000)
        corner_index = int_param(record, "corner_index", 0, minimum=0, maximum=200_000)
        key = (face_index, corner_index)
        if key in seen:
            raise invalid_argument("A face corner may appear only once.")
        seen.add(key)
        face = scoped.get(face_index)
        if face is None or corner_index >= len(face.loops):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "A corner is outside the referenced face scope.")
        resolved.append((face, corner_index, face.loops[corner_index]))
    return resolved


def _same_uv(first: Sequence[float], second: Sequence[float]) -> bool:
    return all(a == b or (math.isnan(a) and math.isnan(b)) for a, b in zip(first, second, strict=True))


def _apply(context: ToolContext, obj: Any, layer: Any, edits: list[CornerEdit]) -> dict[str, Any]:
    before = [(edit, tuple(edit.loop[layer].uv), bool(edit.loop[layer].pin_uv)) for edit in edits]
    changed_uv = sum(edit.uv is not None and not _same_uv(edit.uv, uv) for edit, uv, _ in before)
    changed_pin = sum(edit.pinned is not None and edit.pinned != pin for edit, _, pin in before)
    _check(context)
    if changed_uv or changed_pin:
        try:
            for index, (edit, _uv, _pin) in enumerate(before):
                if index % 256 == 0:
                    _check(context)
                if edit.uv is not None:
                    edit.loop[layer].uv = edit.uv
                if edit.pinned is not None:
                    edit.loop[layer].pin_uv = edit.pinned
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            _check(context)
            if any((edit.uv is not None and not _same_uv(edit.loop[layer].uv, edit.uv))
                   or (edit.pinned is not None and bool(edit.loop[layer].pin_uv) != edit.pinned)
                   for edit in edits):
                raise RuntimeError("UV postcondition mismatch")
        except Exception as error:
            logging.getLogger(__name__).exception("UV authoring failed on %s", obj.name)
            restored = False
            try:
                for edit, uv, pin in before:
                    edit.loop[layer].uv = uv
                    edit.loop[layer].pin_uv = pin
                bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
                restored = all(_same_uv(edit.loop[layer].uv, uv) and bool(edit.loop[layer].pin_uv) == pin
                               for edit, uv, pin in before)
            except Exception:
                logging.getLogger(__name__).exception("UV local rollback failed on %s", obj.name)
            raise BridgeError(
                error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                "UV authoring failed; inspect the operation and its recovery evidence.",
                {"object": obj.name, "affected_objects": [obj.name], "uv_layer": layer.name,
                 "execution_started": True, "verification_required": True, "rollback_verified": restored},
            ) from error
    coordinates = [tuple(edit.loop[layer].uv) for edit in edits]
    finite = all(math.isfinite(value) for uv in coordinates for value in uv)
    return {
        "object": obj.name, "affected_objects": [obj.name], "uv_layer": layer.name,
        "changed": bool(changed_uv or changed_pin), "coordinate_changes": changed_uv, "pin_changes": changed_pin,
        "target_corners": len(edits), "pinned_corners_after": sum(bool(edit.loop[layer].pin_uv) for edit in edits),
        "bounds_scope": "target_corners", "bounds_after": {
            "min": [min(uv[i] for uv in coordinates) for i in range(2)],
            "max": [max(uv[i] for uv in coordinates) for i in range(2)],
        } if coordinates and finite else None,
        "corners": [{"face_index": edit.face_index, "corner_index": edit.corner_index} for edit in edits[:64]],
        "corners_truncated": len(edits) > 64, "selection_changed": False, "topology_changed": False,
        "active_layer_changed": False, "verification_required": True,
        "warnings": [] if finite else ["Some targeted UV coordinates are non-finite; use coordinates_set to repair them."],
    }


def coordinates_set(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "selection_id", "updates"})
    updates = params.get("updates")
    if not isinstance(updates, list) or not 1 <= len(updates) <= MAX_CORNERS:
        raise invalid_argument("'updates' must contain 1-20,000 face/corner/UV records.")
    prepared = []
    seen = set()
    for update in updates:
        if not isinstance(update, Mapping) or set(update) != {"face_index", "corner_index", "uv"}:
            raise invalid_argument("Each update requires exactly face_index, corner_index and uv.")
        face = int_param(update, "face_index", 0, minimum=0, maximum=200_000)
        corner = int_param(update, "corner_index", 0, minimum=0, maximum=200_000)
        key = (face, corner)
        if key in seen:
            raise invalid_argument("A face corner may appear only once per coordinate edit.")
        seen.add(key)
        prepared.append((face, corner, _pair(update["uv"], "uv")))
    obj, _bm, layer, faces = _scope(params, require_reference=True)
    scoped = {face.index: face for face in faces}
    edits = []
    for face_index, corner_index, uv in prepared:
        face = scoped.get(face_index)
        if face is None or corner_index >= len(face.loops):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "A coordinate update is outside the referenced face/corner scope.")
        edits.append(CornerEdit(face_index, corner_index, face.loops[corner_index], uv=uv))
    return _apply(context, obj, layer, edits)


def transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "selection_id", "corners", "offset", "scale", "pivot", "rotation", "respect_pins"})
    offset = _pair(params.get("offset", [0, 0]), "offset")
    scale = _pair(params.get("scale", [1, 1]), "scale")
    pivot = _pair(params.get("pivot", [0, 0]), "pivot")
    rotation = float_param(params, "rotation", 0, minimum=-math.tau * 1_000, maximum=math.tau * 1_000)
    respect_pins = bool_param(params, "respect_pins", True)
    obj, _bm, layer, faces = _scope(params, require_reference=params.get("corners") is not None)
    edits = []
    skipped = 0
    cosine, sine = math.cos(rotation), math.sin(rotation)
    for face, index, loop in _corners(params, faces):
        if respect_pins and loop[layer].pin_uv:
            skipped += 1
            continue
        uv = _pair(tuple(loop[layer].uv), "existing_uv")
        x, y = (uv[0] - pivot[0]) * scale[0], (uv[1] - pivot[1]) * scale[1]
        target = _pair([pivot[0] + offset[0] + cosine * x - sine * y,
                        pivot[1] + offset[1] + sine * x + cosine * y], "transformed_uv")
        edits.append(CornerEdit(face.index, index, loop, uv=target))
    result = _apply(context, obj, layer, edits)
    result["skipped_pinned_corners"] = skipped
    result["transform_order"] = "pivot-relative scale, counterclockwise rotation (radians), then offset"
    return result


def pin(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "selection_id", "corners", "pinned"})
    pinned = bool_param(params, "pinned", True)
    obj, _bm, layer, faces = _scope(params, require_reference=params.get("corners") is not None)
    return _apply(context, obj, layer, [CornerEdit(face.index, index, loop, pinned=pinned)
        for face, index, loop in _corners(params, faces)])


def register_tools(registry: ToolRegistry) -> None:
    for name, handler, description in (
        ("uv.coordinates_set", coordinates_set, "Set exact face-corner UVs within a validated face selection reference."),
        ("uv.transform", transform, "Transform selected-face UV corners by explicit pivot, scale, rotation and offset; respect pins by default."),
        ("uv.pin", pin, "Pin or unpin UV corners of selected faces without changing their coordinates."),
    ):
        registry.register(name, handler, permissions=(Permission.EDIT_MESH,), toolset="uv", modifies=True, description=description)
