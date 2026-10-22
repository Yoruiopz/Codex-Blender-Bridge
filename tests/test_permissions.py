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


def test_each_permission_requirement_uses_one_coherent_live_grant_set(addon_package: str) -> None:
    permissions = importlib.import_module(f"{addon_package}.permissions")
    errors = importlib.import_module(f"{addon_package}.errors")
    calls = []

    def provider():
        calls.append(None)
        return ({"EDIT_MATERIALS": True, "ACCESS_EXTERNAL_FILES": False} if len(calls) == 1
                else {"EDIT_MATERIALS": False, "ACCESS_EXTERNAL_FILES": True})

    manager = permissions.PermissionManager(provider)
    for missing in ("ACCESS_EXTERNAL_FILES", "EDIT_MATERIALS"):
        with pytest.raises(errors.BridgeError) as caught:
            manager.require([permissions.Permission.EDIT_MATERIALS, permissions.Permission.ACCESS_EXTERNAL_FILES])
        assert caught.value.context == {"required": ["EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES"],
                                        "missing_permissions": [missing]}
    assert len(calls) == 2


def test_empty_permission_requirement_does_not_invoke_provider(addon_package: str) -> None:
    permissions = importlib.import_module(f"{addon_package}.permissions")

    def provider():
        pytest.fail("No permission was requested")

    permissions.PermissionManager(provider).require([])
