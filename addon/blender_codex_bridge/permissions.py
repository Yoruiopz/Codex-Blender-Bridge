"""Blender-owned permission enforcement."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from typing import Any

from .errors import BridgeError, ErrorCode


class Permission(str, Enum):
    INSPECT_SCENE = "INSPECT_SCENE"
    CAPTURE_VIEWPORT = "CAPTURE_VIEWPORT"
    TRANSFORM_OBJECTS = "TRANSFORM_OBJECTS"
    EDIT_MESH = "EDIT_MESH"
    EDIT_MATERIALS = "EDIT_MATERIALS"
    EDIT_ANIMATION = "EDIT_ANIMATION"
    DELETE_OBJECTS = "DELETE_OBJECTS"
    EXECUTE_PYTHON = "EXECUTE_PYTHON"
    ACCESS_EXTERNAL_FILES = "ACCESS_EXTERNAL_FILES"
    SAVE_PROJECT = "SAVE_PROJECT"


PREFERENCE_PROPERTIES: dict[Permission, str] = {
    Permission.INSPECT_SCENE: "allow_inspect_scene",
    Permission.CAPTURE_VIEWPORT: "allow_viewport_capture",
    Permission.TRANSFORM_OBJECTS: "allow_transform_objects",
    Permission.EDIT_MESH: "allow_edit_mesh",
    Permission.EDIT_MATERIALS: "allow_edit_materials",
    Permission.EDIT_ANIMATION: "allow_edit_animation",
    Permission.DELETE_OBJECTS: "allow_delete_objects",
    Permission.EXECUTE_PYTHON: "allow_execute_python",
    Permission.ACCESS_EXTERNAL_FILES: "allow_external_files",
    Permission.SAVE_PROJECT: "allow_save_project",
}


def permission_snapshot(preferences: Any | None) -> dict[str, bool]:
    """Read permission flags from Blender add-on preferences."""

    if preferences is None:
        return {permission.value: False for permission in Permission}
    return {
        permission.value: bool(getattr(preferences, property_name, False))
        for permission, property_name in PREFERENCE_PROPERTIES.items()
    }


class PermissionManager:
    """Resolve and enforce live Blender preference flags."""

    def __init__(self, source: Callable[[], Mapping[str, bool]]) -> None:
        self._source = source

    def snapshot(self) -> dict[str, bool]:
        values = self._source()
        return {permission.value: bool(values.get(permission.value, False)) for permission in Permission}

    def is_allowed(self, permission: Permission | str) -> bool:
        key = permission.value if isinstance(permission, Permission) else str(permission)
        return bool(self._source().get(key, False))

    def require(self, permissions: Iterable[Permission | str]) -> None:
        required = [p.value if isinstance(p, Permission) else str(p) for p in permissions]
        denied = [permission for permission in required if not self.is_allowed(permission)]
        if denied:
            raise BridgeError(
                ErrorCode.PERMISSION_DENIED,
                "Blender-side permission denied.",
                {
                    "required": required,
                    "missing_permissions": denied,
                },
            )
