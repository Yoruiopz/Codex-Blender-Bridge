from __future__ import annotations

import importlib

import pytest


def test_permissions_default_to_denied_without_preferences(addon_package: str) -> None:
    permissions = importlib.import_module(f"{addon_package}.permissions")

    snapshot = permissions.permission_snapshot(None)

    assert set(snapshot) == {permission.value for permission in permissions.Permission}
    assert not any(snapshot.values())


def test_permission_manager_enforces_live_values(addon_package: str) -> None:
    permissions = importlib.import_module(f"{addon_package}.permissions")
    errors = importlib.import_module(f"{addon_package}.errors")
    values = {permission.value: False for permission in permissions.Permission}
    manager = permissions.PermissionManager(lambda: values)

    with pytest.raises(errors.BridgeError) as caught:
        manager.require([permissions.Permission.DELETE_OBJECTS])

    assert caught.value.code == errors.ErrorCode.PERMISSION_DENIED.value
    assert caught.value.context == {
        "required": ["DELETE_OBJECTS"],
        "missing_permissions": ["DELETE_OBJECTS"],
    }

    values["DELETE_OBJECTS"] = True
    manager.require([permissions.Permission.DELETE_OBJECTS])


def test_permission_snapshot_reads_expected_preference_names(addon_package: str) -> None:
    permissions = importlib.import_module(f"{addon_package}.permissions")

    class Preferences:
        allow_inspect_scene = True
        allow_delete_objects = False

    snapshot = permissions.permission_snapshot(Preferences())

    assert snapshot["INSPECT_SCENE"] is True
    assert snapshot["DELETE_OBJECTS"] is False
    assert snapshot["EXECUTE_PYTHON"] is False
