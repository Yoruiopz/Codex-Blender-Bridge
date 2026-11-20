from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def profile(addon_package, monkeypatch, tmp_path):
    settings = importlib.import_module(addon_package + ".permission_settings")
    preferences = importlib.import_module(addon_package + ".preferences")
    permissions = importlib.import_module(addon_package + ".permissions")
    native = SimpleNamespace(**settings.restrictive_values())
    path = tmp_path / "user config" / "blender_codex_bridge" / settings.PROFILE_FILE
    monkeypatch.setattr(preferences, "get_preferences", lambda *_: native)
    monkeypatch.setattr(preferences, "_permission_profile_path", lambda: path)
    monkeypatch.setattr(preferences, "_committed_settings", None)
    monkeypatch.setattr(preferences, "_restoring", False)
    monkeypatch.setattr(preferences, "_profile_error", "")
    return SimpleNamespace(settings=settings, preferences=preferences, permissions=permissions,
                           native=native, path=path)


def test_new_profile_does_not_write_or_restore_unproven_dangerous_opt_ins(profile):
    profile.native.allow_save_project = True
    profile.native.all_dangerous_permissions = True  # Stale Blender prefs without a Bridge profile.
    profile.native.allow_unrestricted_project_texture_paths = True
    profile.preferences.restore_permission_settings()

    assert not profile.path.parent.exists()
    assert profile.permissions.permission_snapshot(profile.native)["SAVE_PROJECT"] is True
    assert profile.permissions.permission_snapshot(profile.native)["EXECUTE_PYTHON"] is False
    assert profile.native.all_dangerous_permissions is False
    assert profile.native.allow_unrestricted_project_texture_paths is False
    assert not profile.permissions.unrestricted_project_texture_paths(profile.native)


def test_profile_restores_individual_grants_master_and_folders_then_records_immediate_revoke(profile):
    settings, prefs, native = profile.settings, profile.preferences, profile.native
    prefs.restore_permission_settings()
    native.allow_inspect_scene = True
    native.allow_external_files = True
    native.project_directory = r"C:\Artist Projects\Projects"
    native.texture_directory = r"C:\Artist Projects\Textures"
    prefs._permission_setting_changed(native, None)
    assert prefs._set_dangerous_permissions(native, True)
    native.allow_unrestricted_project_texture_paths = True
    prefs._permission_setting_changed(native, None)
    on_disk = settings.read_permission_settings(profile.path)
    assert on_disk == settings.preference_values(native)
    assert native.allow_execute_python is False
    assert profile.permissions.permission_snapshot(native)["EXECUTE_PYTHON"] is True

    for field, value in settings.restrictive_values().items():
        setattr(native, field, value)
    prefs.restore_permission_settings()
    assert settings.preference_values(native) == on_disk
    assert profile.permissions.unrestricted_project_texture_paths(native)

    assert prefs._set_dangerous_permissions(native, False)
    disk_after = settings.read_permission_settings(profile.path)
    assert disk_after == settings.preference_values(native)
    assert native.allow_external_files is True
    assert native.project_directory == r"C:\Artist Projects\Projects"
    assert native.allow_unrestricted_project_texture_paths is False
    assert profile.permissions.permission_snapshot(native)["EXECUTE_PYTHON"] is False
    assert profile.permissions.permission_snapshot(native)["SAVE_PROJECT"] is False
    assert not profile.permissions.unrestricted_project_texture_paths(native)


@pytest.mark.parametrize("payload", [b"{", b'{"version":1,"version":1,"settings":{}}',
                                        b'{"version":true,"settings":{}}', b"[]", b"x" * (64 * 1024 + 1)])
def test_malformed_profile_fails_closed_without_rewriting_it(profile, payload):
    profile.path.parent.mkdir(parents=True)
    profile.path.write_bytes(payload)
    profile.native.allow_execute_python = True
    profile.native.all_dangerous_permissions = True
    profile.native.allow_unrestricted_project_texture_paths = True

    profile.preferences.restore_permission_settings()

    assert not any(profile.permissions.permission_snapshot(profile.native).values())
    assert not profile.permissions.unrestricted_project_texture_paths(profile.native)
    assert profile.preferences._profile_error
    assert profile.path.read_bytes() == payload


def test_profile_cannot_use_unrestricted_option_without_master(profile):
    values = profile.settings.restrictive_values()
    values["allow_unrestricted_project_texture_paths"] = True
    profile.path.parent.mkdir(parents=True)
    profile.path.write_text(json.dumps({"version": 1, "settings": values}), encoding="utf-8")

    with pytest.raises(ValueError, match="master opt-in"):
        profile.settings.read_permission_settings(profile.path)
    assert not profile.permissions.unrestricted_project_texture_paths(SimpleNamespace(**values))


def test_preference_write_failure_refuses_new_grants_and_honors_session_revocation(profile, monkeypatch):
    prefs, native = profile.preferences, profile.native
    prefs.restore_permission_settings()
    native.allow_external_files = True
    prefs._permission_setting_changed(native, None)

    def failed_write(_path, _values):
        raise PermissionError("modeled failure")

    monkeypatch.setattr(prefs, "write_permission_settings", failed_write)
    assert not prefs._set_dangerous_permissions(native, True)
    assert not native.all_dangerous_permissions
    assert profile.permissions.permission_snapshot(native)["EXECUTE_PYTHON"] is False

    native.allow_external_files = False
    prefs._permission_setting_changed(native, None)
    assert not native.allow_external_files
    assert profile.settings.read_permission_settings(profile.path)["allow_external_files"] is True
    assert "could not be saved" in prefs._profile_error


def test_failed_replace_preserves_last_durable_settings_and_removes_temporary_file(profile, monkeypatch):
    settings = profile.settings
    previous = settings.restrictive_values()
    settings.write_permission_settings(profile.path, previous)

    def interrupt_replace(source, destination):
        assert destination == profile.path
        assert source.read_bytes() != destination.read_bytes()
        raise PermissionError("modeled failure")

    monkeypatch.setattr(settings.os, "replace", interrupt_replace)
    with pytest.raises(PermissionError):
        settings.write_permission_settings(profile.path, {**previous, "allow_save_project": True})
    assert settings.read_permission_settings(profile.path) == previous
    assert list(profile.path.parent.iterdir()) == [profile.path]
