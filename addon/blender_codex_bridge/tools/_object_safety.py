"""Ownership preconditions for object and owned-data mutations.

An object's transform, modifiers and constraints are object-owned. Shared mesh data
alone must not prohibit those edits; operations that write that data opt in to the
stronger single-user check instead.
"""

from __future__ import annotations

from typing import Any

from ..errors import BridgeError, ErrorCode


def require_local_editable_id(data: Any, *, operation: str) -> None:
    if (
        getattr(data, "library", None) is not None
        or getattr(data, "override_library", None) is not None
        or not getattr(data, "is_editable", True)
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            f"{operation} requires local, editable, non-override data.",
            {"data": getattr(data, "name", None)},
        )


def require_local_object(obj: Any, *, operation: str) -> None:
    require_local_editable_id(obj, operation=operation)


def require_single_user_object_data(obj: Any, *, operation: str) -> None:
    """Reject implicit changes to another object's shared data before any edits."""
    require_local_object(obj, operation=operation)
    data = getattr(obj, "data", None)
    if data is None:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            f"{operation} requires an owned object datablock.",
            {"object": obj.name},
        )
    require_local_editable_id(data, operation=operation)
    users = int(getattr(data, "users", 1))
    if users != 1:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            f"{operation} requires single-user object data; shared data is not changed implicitly.",
            {"object": obj.name, "data": data.name, "data_users": users},
        )


def require_unkeyed_object_data(obj: Any, *, operation: str) -> None:
    require_single_user_object_data(obj, operation=operation)
    if getattr(obj.data, "shape_keys", None) is not None:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            f"{operation} does not support shape-key data with verified recovery.",
            {"object": obj.name, "data": obj.data.name},
        )


def require_owned_action(obj: Any, *, operation: str) -> None:
    """A keyframe edit must not silently edit a shared/linked Action."""
    require_local_object(obj, operation=operation)
    animation_data = getattr(obj, "animation_data", None)
    action = getattr(animation_data, "action", None)
    if action is None:
        return
    require_local_editable_id(action, operation=operation)
    users = int(getattr(action, "users", 1))
    effective_users = users - int(bool(getattr(action, "use_fake_user", False)))
    if effective_users > 1:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            f"{operation} requires an unshared Action; create an explicit independent version first.",
            {"object": obj.name, "action": action.name, "action_users": users},
        )
