"""Small Blender helpers shared by inspectors and structured tools."""

from __future__ import annotations

import difflib
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument

try:  # Import-safe for protocol/unit tests outside Blender.
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - exercised only outside Blender
    bpy = None  # type: ignore


def require_blender() -> Any:
    if bpy is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "This tool must run inside Blender.")
    return bpy


def similar_names(name: str, names: Iterable[str], *, limit: int = 5) -> list[str]:
    return difflib.get_close_matches(name, list(names), n=limit, cutoff=0.25)


def get_object(
    object_name: str | None = None,
    *,
    allow_active: bool = True,
) -> Any:
    blender = require_blender()
    if object_name is None or object_name == "":
        if not allow_active:
            raise invalid_argument(
                "A non-empty 'object_name' is required.",
                parameter="object_name",
            )
        active = blender.context.view_layer.objects.active
        if active is None:
            raise BridgeError(ErrorCode.OBJECT_NOT_FOUND, "There is no active object.")
        return active
    if not isinstance(object_name, str):
        raise invalid_argument("'object_name' must be a string.", parameter="object_name")
    if not object_name.strip() or len(object_name) > 256:
        raise invalid_argument(
            "'object_name' must be a non-empty string of at most 256 characters.",
            parameter="object_name",
        )
    obj = blender.data.objects.get(object_name)
    if obj is None:
        raise BridgeError(
            ErrorCode.OBJECT_NOT_FOUND,
            f"Object '{object_name}' does not exist.",
            {"available_similar_objects": similar_names(object_name, blender.data.objects.keys())},
        )
    return obj


def get_collection(collection_name: str | None = None) -> Any:
    blender = require_blender()
    if collection_name:
        collection = blender.data.collections.get(collection_name)
        if collection is None:
            raise invalid_argument(
                f"Collection '{collection_name}' does not exist.",
                available_similar_collections=similar_names(collection_name, blender.data.collections.keys()),
            )
        return collection
    context_collection = getattr(blender.context, "collection", None)
    return context_collection or blender.context.scene.collection


def object_identifier(obj: Any) -> str:
    """Return a unique identifier stable for the current Blender session."""

    session_uid = getattr(obj, "session_uid", None)
    if session_uid is not None:
        return f"obj_{int(session_uid):x}"
    try:
        return f"obj_{int(obj.as_pointer()):x}"
    except (AttributeError, TypeError, ValueError):
        return f"obj_{obj.name_full}"


def bool_param(params: Mapping[str, Any], name: str, default: bool) -> bool:
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise invalid_argument(f"'{name}' must be a boolean.", parameter=name)
    return value


def int_param(
    params: Mapping[str, Any],
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_argument(f"'{name}' must be an integer.", parameter=name)
    if minimum is not None and value < minimum:
        raise invalid_argument(f"'{name}' must be at least {minimum}.", parameter=name)
    if maximum is not None and value > maximum:
        raise invalid_argument(f"'{name}' must be at most {maximum}.", parameter=name)
    return value


def float_param(
    params: Mapping[str, Any],
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_argument(f"'{name}' must be a number.", parameter=name)
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(f"'{name}' must be a finite number.", parameter=name) from exc
    if not math.isfinite(result):
        raise invalid_argument(f"'{name}' must be finite.", parameter=name)
    if minimum is not None and result < minimum:
        raise invalid_argument(f"'{name}' must be at least {minimum}.", parameter=name)
    if maximum is not None and result > maximum:
        raise invalid_argument(f"'{name}' must be at most {maximum}.", parameter=name)
    return result


def vector3(value: Any, name: str, *, default: Sequence[float] | None = None) -> tuple[float, float, float]:
    if value is None and default is not None:
        value = default
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise invalid_argument(f"'{name}' must contain exactly three numbers.", parameter=name)
    if any(isinstance(component, bool) or not isinstance(component, (int, float)) for component in value):
        raise invalid_argument(f"'{name}' must contain exactly three numbers.", parameter=name)
    try:
        result = (float(value[0]), float(value[1]), float(value[2]))
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(
            f"'{name}' values must be finite numbers.",
            parameter=name,
        ) from exc
    if not all(math.isfinite(component) for component in result):
        raise invalid_argument(f"'{name}' values must be finite.", parameter=name)
    return result


def serialize_transform(obj: Any) -> dict[str, Any]:
    return {
        "object": obj.name,
        "location": [float(value) for value in obj.location],
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": [float(value) for value in obj.rotation_euler],
        "rotation_quaternion": [float(value) for value in obj.rotation_quaternion],
        "scale": [float(value) for value in obj.scale],
        "dimensions": [float(value) for value in obj.dimensions],
        "matrix_world": [[float(value) for value in row] for row in obj.matrix_world],
    }


@contextmanager
def preserved_object_context() -> Iterator[None]:
    """Restore mode, active object, and object selection after contextual operators."""

    blender = require_blender()
    view_layer = blender.context.view_layer
    active = view_layer.objects.active
    selected = list(blender.context.selected_objects)
    mode = getattr(active, "mode", "OBJECT") if active else "OBJECT"
    try:
        yield
    finally:
        try:
            current_active = view_layer.objects.active
            if current_active and current_active.mode != "OBJECT":
                blender.ops.object.mode_set(mode="OBJECT")
            for obj in view_layer.objects:
                obj.select_set(False)
            for obj in selected:
                if obj.name in view_layer.objects:
                    obj.select_set(True)
            if active and active.name in view_layer.objects:
                view_layer.objects.active = active
                if mode != "OBJECT" and active.mode == "OBJECT":
                    blender.ops.object.mode_set(mode=mode)
        except (RuntimeError, ReferenceError):
            # Restoration is best-effort if the operation removed the active object.
            pass


def affected_objects_from_result(result: Any) -> tuple[str, ...]:
    if not isinstance(result, Mapping):
        return ()
    candidates: list[str] = []
    for key in ("object", "object_name", "name"):
        value = result.get(key)
        if isinstance(value, str):
            candidates.append(value)
    affected = result.get("affected_objects")
    if isinstance(affected, Sequence) and not isinstance(affected, (str, bytes)):
        candidates.extend(str(name) for name in affected)
    return tuple(dict.fromkeys(candidates))
