"""Direct, face-corner UV authoring without operators or selection changes."""

from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import float_param, int_param
from ._mesh_safety import require_local_single_user_mesh
from .interaction import _active_edit_mesh
from .mesh import _id_name

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

MAX_CORNERS = 20_000
MAX_UV = 1_000_000.0


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


def coordinates_set(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from ..uv_edit_guard import current
    return current(context, "uv.coordinates_set", params).execute()


def transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from ..uv_edit_guard import current
    return current(context, "uv.transform", params).execute()


def pin(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from ..uv_edit_guard import current
    return current(context, "uv.pin", params).execute()


def register_tools(registry: ToolRegistry) -> None:
    from ..uv_edit_guard import factory
    for name, handler, description in (
        ("uv.coordinates_set", coordinates_set, "Set exact face-corner UVs within a validated face selection reference."),
        ("uv.transform", transform, "Transform selected-face UV corners by explicit pivot, scale, rotation and offset; respect pins by default."),
        ("uv.pin", pin, "Pin or unpin UV corners of selected faces without changing their coordinates."),
    ):
        registry.register(name, handler, permissions=(Permission.EDIT_MESH,), toolset="uv", modifies=True,
                          description=description, checkpoint_admission_factory=lambda context, params, method=name:
                          factory(method, context, params), exclusive_mutation=True)
