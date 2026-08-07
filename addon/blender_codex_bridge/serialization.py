"""Bounded conversion of Blender and Python values to JSON-safe structures."""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


def to_jsonable(
    value: Any,
    *,
    max_depth: int = 10,
    max_items: int = 10_000,
    _depth: int = 0,
) -> Any:
    """Convert a value to a bounded JSON-compatible representation.

    Blender math types are intentionally handled by duck typing so this module is
    usable by ordinary Python tests without importing :mod:`bpy` or
    :mod:`mathutils`.
    """

    if _depth > max_depth:
        return "<max-depth>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return to_jsonable(value.value, max_depth=max_depth, max_items=max_items, _depth=_depth + 1)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(
            dataclasses.asdict(value),
            max_depth=max_depth,
            max_items=max_items,
            _depth=_depth + 1,
        )
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                result["__truncated__"] = True
                break
            result[str(key)] = to_jsonable(
                item,
                max_depth=max_depth,
                max_items=max_items,
                _depth=_depth + 1,
            )
        return result
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (set, frozenset)):
        value = sorted(value, key=repr)
    if isinstance(value, Sequence):
        result_list = [
            to_jsonable(item, max_depth=max_depth, max_items=max_items, _depth=_depth + 1)
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            result_list.append({"__truncated__": True, "total": len(value)})
        return result_list

    # mathutils Vector/Euler/Quaternion/Color/Matrix and similar bounded types.
    type_name = type(value).__name__
    if type_name == "Matrix":
        try:
            return [
                [float(component) for component in row]
                for row in value
            ]
        except (TypeError, ValueError):
            pass
    if type_name in {"Vector", "Euler", "Quaternion", "Color"}:
        try:
            return [float(component) for component in value]
        except (TypeError, ValueError):
            pass

    # Blender IDs and RNA values commonly expose a useful name.
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return repr(value)


def dumps(value: Any) -> str:
    """Serialize a value using compact, deterministic JSON."""

    return json.dumps(
        to_jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite JSON number {value!r} is not permitted")
    return parsed


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number {value!r} is not permitted")


def loads(payload: str | bytes) -> Any:
    """Deserialize UTF-8 JSON."""

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(
        payload,
        parse_float=_finite_json_float,
        parse_constant=_reject_json_constant,
    )
