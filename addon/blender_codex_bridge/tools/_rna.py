"""Safe, bounded RNA property assignment for structured Blender tools.

This module intentionally supports only direct properties selected by each domain
tool.  It never follows dotted paths, indexes collections, or invokes attributes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..serialization import to_jsonable

MAX_SETTINGS = 32
MAX_STRING_LENGTH = 1024


@dataclass(frozen=True, slots=True)
class RNAAssignment:
    name: str
    value: Any


def bounded_name(value: Any, parameter: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument(
            f"'{parameter}' must be a non-empty string.", parameter=parameter
        )
    if len(value) > maximum:
        raise invalid_argument(
            f"'{parameter}' must contain at most {maximum} characters.",
            parameter=parameter,
            maximum=maximum,
        )
    return value


def settings_mapping(params: Mapping[str, Any], *, required: bool = True) -> Mapping[str, Any]:
    value = params.get("settings")
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise invalid_argument("'settings' must be an object.", parameter="settings")
    if required and not value:
        raise invalid_argument("'settings' must contain at least one property.", parameter="settings")
    if len(value) > MAX_SETTINGS:
        raise invalid_argument(
            f"'settings' may contain at most {MAX_SETTINGS} properties.",
            parameter="settings",
            maximum=MAX_SETTINGS,
        )
    return value


def _rna_property(owner: Any, name: str) -> Any:
    properties = getattr(getattr(owner, "bl_rna", None), "properties", None)
    prop = properties.get(name) if properties is not None else None
    if prop is None:
        raise invalid_argument(
            f"RNA property '{name}' is unavailable on this Blender data block.",
            property=name,
        )
    if bool(getattr(prop, "is_readonly", False)):
        raise invalid_argument(f"RNA property '{name}' is read-only.", property=name)
    return prop


def _bounded_numeric(value: Any, prop: Any, *, integer: bool, name: str) -> int | float:
    expected = "an integer" if integer else "a finite number"
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise invalid_argument(f"Setting '{name}' must be {expected}.", property=name)
    try:
        result: int | float = int(value) if integer else float(value)
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(f"Setting '{name}' must be {expected}.", property=name) from exc
    if not integer and not math.isfinite(float(result)):
        raise invalid_argument(f"Setting '{name}' must be finite.", property=name)
    minimum = getattr(prop, "hard_min", None)
    maximum = getattr(prop, "hard_max", None)
    if isinstance(minimum, (int, float)) and result < minimum:
        raise invalid_argument(
            f"Setting '{name}' is below Blender's minimum of {minimum}.",
            property=name,
            minimum=minimum,
        )
    if isinstance(maximum, (int, float)) and result > maximum:
        raise invalid_argument(
            f"Setting '{name}' exceeds Blender's maximum of {maximum}.",
            property=name,
            maximum=maximum,
        )
    return result


def _enum_identifiers(prop: Any) -> set[str]:
    items = getattr(prop, "enum_items", ())
    try:
        return {str(item.identifier) for item in items}
    except (AttributeError, TypeError):
        return set()


def _coerce_scalar(
    value: Any,
    prop: Any,
    *,
    name: str,
    bpy: Any,
    object_pointer: bool,
) -> Any:
    kind = str(getattr(prop, "type", ""))
    if kind == "BOOLEAN":
        if not isinstance(value, bool):
            raise invalid_argument(f"Setting '{name}' must be a boolean.", property=name)
        return value
    if kind == "INT":
        return _bounded_numeric(value, prop, integer=True, name=name)
    if kind == "FLOAT":
        return _bounded_numeric(value, prop, integer=False, name=name)
    if kind == "STRING":
        if not isinstance(value, str) or len(value) > MAX_STRING_LENGTH:
            raise invalid_argument(
                f"Setting '{name}' must be a string of at most {MAX_STRING_LENGTH} characters.",
                property=name,
            )
        return value
    if kind == "ENUM":
        allowed = _enum_identifiers(prop)
        if bool(getattr(prop, "is_enum_flag", False)):
            if (
                isinstance(value, (str, bytes))
                or not isinstance(value, Sequence)
                or len(value) > 32
                or any(not isinstance(item, str) for item in value)
            ):
                raise invalid_argument(
                    f"Setting '{name}' must be a bounded list of enum identifiers.",
                    property=name,
                )
            unknown = sorted(set(value) - allowed)
            if unknown:
                raise invalid_argument(
                    f"Setting '{name}' contains unsupported enum identifiers.",
                    property=name,
                    unsupported=unknown,
                    allowed=sorted(allowed),
                )
            return set(value)
        if not isinstance(value, str) or value not in allowed:
            raise invalid_argument(
                f"Setting '{name}' must be one of Blender's enum identifiers.",
                property=name,
                allowed=sorted(allowed),
            )
        return value
    if kind == "POINTER" and object_pointer:
        if value is None:
            return None
        target_name = bounded_name(value, f"settings.{name}", maximum=256)
        target = bpy.data.objects.get(target_name)
        if target is None:
            raise BridgeError(
                ErrorCode.OBJECT_NOT_FOUND,
                f"Target object '{target_name}' does not exist.",
                {"property": name, "target_object": target_name},
            )
        return target
    raise invalid_argument(
        f"Setting '{name}' uses an unsupported RNA property type.",
        property=name,
        rna_type=kind or None,
    )


def _coerce_value(
    value: Any,
    prop: Any,
    *,
    name: str,
    bpy: Any,
    object_pointer: bool,
) -> Any:
    array_length = int(getattr(prop, "array_length", 0) or 0)
    if not array_length:
        return _coerce_scalar(
            value, prop, name=name, bpy=bpy, object_pointer=object_pointer
        )
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != array_length
    ):
        raise invalid_argument(
            f"Setting '{name}' must contain exactly {array_length} values.",
            property=name,
            length=array_length,
        )
    kind = str(getattr(prop, "type", ""))
    if kind not in {"FLOAT", "INT", "BOOLEAN"}:
        raise invalid_argument(
            f"Array setting '{name}' has an unsupported RNA type.",
            property=name,
            rna_type=kind,
        )
    return tuple(
        _coerce_scalar(
            item,
            prop,
            name=f"{name}[{index}]",
            bpy=bpy,
            object_pointer=False,
        )
        for index, item in enumerate(value)
    )


def prepare_assignments(
    owner: Any,
    settings: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    object_pointers: frozenset[str],
    bpy: Any,
) -> tuple[RNAAssignment, ...]:
    """Validate every assignment before mutating the owner."""

    prepared: list[RNAAssignment] = []
    for raw_name, value in settings.items():
        if not isinstance(raw_name, str) or not raw_name or "." in raw_name:
            raise invalid_argument(
                "Setting names must be direct, non-empty RNA property names.",
                property=raw_name,
            )
        if raw_name not in allowed:
            raise invalid_argument(
                f"Setting '{raw_name}' is not allowlisted for this data-block type.",
                property=raw_name,
                allowed=sorted(allowed),
            )
        prop = _rna_property(owner, raw_name)
        prepared.append(
            RNAAssignment(
                raw_name,
                _coerce_value(
                    value,
                    prop,
                    name=raw_name,
                    bpy=bpy,
                    object_pointer=raw_name in object_pointers,
                ),
            )
        )
    return tuple(prepared)


def apply_assignments(owner: Any, assignments: Sequence[RNAAssignment]) -> None:
    """Apply a prevalidated batch and best-effort roll it back on setter failure."""

    previous: list[tuple[str, Any]] = []
    failed_name: str | None = None
    try:
        for assignment in assignments:
            failed_name = assignment.name
            old_value = getattr(owner, assignment.name)
            if hasattr(old_value, "__len__") and not isinstance(old_value, (str, bytes)):
                with suppress(TypeError):
                    old_value = tuple(old_value)
            previous.append((assignment.name, old_value))
            setattr(owner, assignment.name, assignment.value)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        for name, old_value in reversed(previous):
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                setattr(owner, name, old_value)
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender rejected an otherwise valid RNA property assignment.",
            {"property": failed_name},
        ) from exc


def serialize_property(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "name"):
        return str(value.name)
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if hasattr(value, "__len__") and hasattr(value, "__getitem__"):
        try:
            return [serialize_property(value[index]) for index in range(len(value))]
        except (IndexError, TypeError, ValueError):
            pass
    return to_jsonable(value)


def serialize_properties(owner: Any, allowed: frozenset[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    properties = getattr(getattr(owner, "bl_rna", None), "properties", None)
    for name in sorted(allowed):
        if properties is None or properties.get(name) is None or not hasattr(owner, name):
            continue
        try:
            result[name] = serialize_property(getattr(owner, name))
        except (AttributeError, ReferenceError, TypeError, ValueError):
            continue
    return result
