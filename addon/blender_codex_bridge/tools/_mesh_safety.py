"""Common ownership preconditions for structured mesh-data mutation."""

from __future__ import annotations

from typing import Any

from ..errors import BridgeError, ErrorCode


def require_local_single_user_mesh(obj: Any) -> None:
    """Do not silently edit linked duplicates or library/override assets."""
    if any(getattr(data, "library", None) or getattr(data, "override_library", None)
           for data in (obj, obj.data)):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Mesh-data editing requires local, non-override object and mesh data.",
            {"object": obj.name},
        )
    if obj.data.users != 1:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Mesh-data editing requires a single-user mesh; shared data is not changed implicitly.",
            {"object": obj.name, "mesh_users": obj.data.users},
        )
