"""Native per-layer and mesh-global UV selection preservation."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from ..errors import BridgeError, ErrorCode

MAX_LOOPS = 200_000
MAX_SELECTION_ELEMENTS = 200_000


def corner_selection(loop: Any, layer: Any) -> bool | None:
    if hasattr(loop, "uv_select_vert"):
        return bool(loop.uv_select_vert)
    data = loop[layer]
    return bool(data.select) if hasattr(data, "select") else None


def _flags(loop: Any, layer: Any, global_selection: bool) -> tuple[bool, bool]:
    if global_selection:
        return bool(loop.uv_select_vert), bool(loop.uv_select_edge)
    data = loop[layer]
    return bool(data.select), bool(data.select_edge)


def _set(loop: Any, layer: Any, global_selection: bool, values: tuple[bool, bool]) -> None:
    if global_selection:
        loop.uv_select_vert, loop.uv_select_edge = values
    else:
        data = loop[layer]
        data.select, data.select_edge = values


@contextmanager
def scoped_uv_selection(bm: Any, layer: Any, faces: Sequence[Any]) -> Iterator[None]:
    """Scope actual native selection; preserve mesh-global flags on Blender 5.2.

    BMLoop.uv_select_vert/uv_select_edge, BMFace.uv_select and
    BMesh.uv_select_sync_valid replace legacy BMLoopUV selection properties.
    Legacy-named .vs/.es BOOLEAN attributes are unrelated custom data here.
    This context allocates no custom-data layers and changes no coordinates.
    """
    if sum(len(seq) for seq in (bm.verts, bm.edges, bm.faces)) > MAX_SELECTION_ELEMENTS:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV selection preservation exceeds 200000 mesh elements.")
    selections = [(item, bool(item.select)) for seq in (bm.verts, bm.edges, bm.faces) for item in seq]

    def scope():
        if not getattr(bm, "is_valid", True) or any(not getattr(item, "is_valid", True) for item, _ in selections):
            raise RuntimeError("BMesh or original selection elements were invalidated.")
        loops, topology = [], []
        for face in bm.faces:
            current = list(face.loops)
            if len(loops)+len(current) > MAX_LOOPS:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV selection preservation exceeds 200000 corners.")
            loops.extend(current)
            topology.append(tuple((getattr(loop.vert, "index", None), getattr(loop.edge, "index", None)) for loop in current)
                            if current and hasattr(current[0], "vert") else len(current))
        return loops, (tuple(len(seq) for seq in (bm.verts, bm.edges, bm.faces)), topology)

    loops, original_topology = scope()
    global_selection = (hasattr(bm, "uv_select_sync_valid")
                        and all(hasattr(face, "uv_select") for face in bm.faces)
                        and all(hasattr(loop, "uv_select_vert") and hasattr(loop, "uv_select_edge") for loop in loops))
    if not global_selection and not all(hasattr(loop[layer], "select") and hasattr(loop[layer], "select_edge") for loop in loops):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native UV selection storage is unsupported.")
    original = [_flags(loop, layer, global_selection) for loop in loops]
    face_flags = [bool(face.uv_select) for face in bm.faces] if global_selection else []
    sync_valid = bool(bm.uv_select_sync_valid) if global_selection else None
    failure: Exception | None = None
    try:
        for item, _selected in selections:
            item.select = False
        for loop in loops:
            _set(loop, layer, global_selection, (False, False))
        if global_selection:
            for face in bm.faces:
                face.uv_select = False
        for face in faces:
            face.select_set(True)
            if global_selection:
                face.uv_select = True
            for loop in face.loops:
                _set(loop, layer, global_selection, (True, True))
        if global_selection:
            bm.uv_select_sync_valid = True
        yield
    except Exception as exc:
        failure = exc
        raise
    finally:
        try:
            # Operators can refresh custom data, invalidating old loop wrappers.
            # Resolve every loop again and reject a changed mesh topology.
            loops, topology = scope()
            if topology != original_topology:
                raise RuntimeError("UV operator changed topology; context restoration is unsafe.")
            for item, selected in selections:
                item.select = selected
            for loop, selected in zip(loops, original, strict=True):
                _set(loop, layer, global_selection, selected)
            if global_selection:
                for face, selected in zip(bm.faces, face_flags, strict=True):
                    face.uv_select = selected
                bm.uv_select_sync_valid = sync_valid
            if (any(bool(item.select) != selected for item, selected in selections)
                    or [_flags(loop, layer, global_selection) for loop in loops] != original
                    or (global_selection and ([bool(face.uv_select) for face in bm.faces] != face_flags
                                               or bool(bm.uv_select_sync_valid) != sync_valid))):
                raise RuntimeError("UV selection restoration readback differed.")
        except Exception as recovery:
            details = {"possible_mutation": True, "verification_required": True,
                       "selection_restored": False, "recovery_error_type": type(recovery).__name__}
            if isinstance(failure, BridgeError):
                failure.context.update(details)
            else:
                raise BridgeError(ErrorCode.OPERATION_FAILED,
                                  "UV selection restoration failed; reinspect mesh and UV flags.",
                                  {**details, "primary_error_type": type(failure).__name__ if failure else None}) from (failure or recovery)
