from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest


@pytest.fixture
def probe(monkeypatch):
    import sys
    for name in ("bpy", "addon_utils"):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace())
    path = Path(__file__).resolve().parents[1] / "scripts/blender_installed_addon_probe_smoke.py"
    spec = importlib.util.spec_from_file_location("installed_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(tmp_path, names):
    path = tmp_path / "input.zip"
    members = {}
    with ZipFile(path, "w") as archive:
        for name in names:
            info = ZipInfo(name)
            info.external_attr = 0o100644 << 16
            archive.writestr(info, b"test")
            members[name] = hashlib.sha256(b"test").hexdigest()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "members_sha256": members}


@pytest.mark.parametrize("bad", [
    "blender_codex_bridge/../escaped.py", "/blender_codex_bridge/a.py",
    "blender_codex_bridge/a\\b.py", "blender_codex_bridge/C:a.py",
    "blender_codex_bridge//a.py", "blender_codex_bridge/./a.py",
    "other/__init__.py", "blender_codex_bridge/__INIT__.PY",
])
def test_unsafe_or_case_alias_archive_never_reaches_installer(probe, tmp_path, bad):
    configured = record(tmp_path, ["blender_codex_bridge/__init__.py", bad])
    owned = tmp_path / "owned"
    owned.mkdir()
    with pytest.raises(AssertionError):
        probe._archive(configured, owned, "bad")


def test_changed_archive_and_changed_member_fail_independent_proofs(probe, tmp_path):
    configured = record(tmp_path, ["blender_codex_bridge/__init__.py"])
    owned = tmp_path / "owned"
    owned.mkdir()
    configured["sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        probe._archive(configured, owned, "hash")
    configured["sha256"] = hashlib.sha256(Path(configured["path"]).read_bytes()).hexdigest()
    configured["members_sha256"]["blender_codex_bridge/__init__.py"] = "0" * 64
    with pytest.raises(AssertionError):
        probe._archive(configured, owned, "members")


def registry(descriptors, listed=None):
    names = [row["name"] for row in descriptors] if listed is None else listed
    return SimpleNamespace(list_tools=lambda: tuple(names), describe=lambda: {"tools": descriptors})


def expected_names(tmp_path, names):
    path = tmp_path / "expected-tools.json"
    payload = (json.dumps(names, indent=2) + "\n").encode()
    path.write_bytes(payload)
    return {"expected_tools": len(names), "expected_tool_names": sorted(names),
            "expected_tool_names_sha256": hashlib.sha256(payload).hexdigest(),
            "expected_tool_names_source": str(path)}


def test_public_projection_includes_toolsets_list_and_excludes_multiple_internal_tools(probe):
    descriptors = [{"name": "toolsets.list", "remote": True}, {"name": "scene.inspect", "remote": True},
                   {"name": "checkpoint.restore_last", "remote": False},
                   {"name": "jobs._scene_turn", "remote": False}, {"name": "jobs._other", "remote": False}]
    observed = probe._public_tool_surface(registry(descriptors), {"expected_tools": 2})
    assert observed["public_tool_names"] == ["scene.inspect", "toolsets.list"]
    assert observed["documented_tool_count"] == 2
    assert observed["hidden_tool_count"] == 3
    assert observed["hidden_tool_metadata"] == [
        {"name": "checkpoint.restore_last", "remote": False},
        {"name": "jobs._other", "remote": False}, {"name": "jobs._scene_turn", "remote": False}]
    assert observed["exact_expected_tool_names_verified"] is False


def test_public_projection_matches_actual_addon_and_mcp_surface(probe, addon_package, tmp_path):
    from mcp_server.tool_registry import create_default_registry

    actual = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools").register_all(actual)
    names = sorted(create_default_registry(None).tool_names(include_disabled=True))
    configured = expected_names(tmp_path, names)
    observed = probe._public_tool_surface(actual, configured)
    assert observed["public_tool_names"] == names
    assert "toolsets.list" in observed["public_tool_names"]
    # The runtime registers jobs._scene_turn separately from static register_all.
    assert "checkpoint.restore_last" in {item["name"] for item in observed["hidden_tool_metadata"]}
    assert "jobs._scene_turn" not in observed["public_tool_names"]
    assert observed["exact_expected_tool_names_verified"] is True
    assert observed["expected_tool_names_source_sha256"] == configured["expected_tool_names_sha256"]


@pytest.mark.parametrize("remote", [None, 0, 1, "true", [], {}])
def test_public_projection_refuses_nonboolean_remote_metadata(probe, remote):
    with pytest.raises(AssertionError, match="explicit bool"):
        probe._public_tool_surface(registry([{"name": "toolsets.list", "remote": remote}]), {"expected_tools": 1})


@pytest.mark.parametrize("descriptors,listed", [
    ([{"name": "toolsets.list"}], ["toolsets.list"]),
    ([{"name": "toolsets.list", "remote": True}] * 2, ["toolsets.list", "scene.inspect"]),
    ([{"name": "toolsets.list", "remote": True}], ["toolsets.list", "scene.inspect"]),
    ([{"name": "toolsets.list", "remote": True}, {"name": "scene.inspect", "remote": True}], ["toolsets.list"]),
    ([{"name": "toolsets.list", "remote": True}], ["scene.inspect"]),
    ([{"name": "toolsets.list", "remote": True}], ["toolsets.list", "toolsets.list"]),
    ([{"name": "bad\nname", "remote": True}], ["bad\nname"]),
    ([{"name": 1, "remote": True}], [1]),
])
def test_public_projection_refuses_incomplete_duplicate_or_invalid_descriptors(probe, descriptors, listed):
    with pytest.raises(AssertionError):
        probe._public_tool_surface(registry(descriptors, listed), {"expected_tools": 1})


@pytest.mark.parametrize("description", [None, [], {}, {"tools": None}, {"tools": ()}, {"tools": [None]}])
def test_public_projection_refuses_malformed_descriptor_inventory(probe, description):
    actual = SimpleNamespace(list_tools=lambda: ("toolsets.list",), describe=lambda: description)
    with pytest.raises(AssertionError):
        probe._public_tool_surface(actual, {"expected_tools": 1})


@pytest.mark.parametrize("names", [["toolsets.list", "scene.missing"], ["toolsets.list", "jobs._scene_turn"]])
def test_public_projection_checks_exact_names_even_when_counts_match(probe, tmp_path, names):
    actual = registry([{"name": "toolsets.list", "remote": True}, {"name": "scene.inspect", "remote": True},
                       {"name": "jobs._scene_turn", "remote": False}])
    with pytest.raises(AssertionError, match=r"missing.*extra"):
        probe._public_tool_surface(actual, expected_names(tmp_path, names))


@pytest.mark.parametrize("field", ["expected_tool_names", "expected_tool_names_sha256", "expected_tool_names_source"])
def test_exact_name_pin_requires_all_three_fields(probe, tmp_path, field):
    configured = expected_names(tmp_path, ["toolsets.list"])
    del configured[field]
    with pytest.raises(AssertionError, match="Incomplete"):
        probe._expected_tool_names(configured)


@pytest.mark.parametrize("names", [[], ["toolsets.list", "toolsets.list"], ["bad name"], [True], "toolsets.list"])
def test_expected_name_configuration_refuses_bad_names_duplicates_and_types(probe, tmp_path, names):
    configured = expected_names(tmp_path, ["toolsets.list"])
    configured["expected_tool_names"] = names
    with pytest.raises(AssertionError, match="Invalid expected tool names"):
        probe._expected_tool_names(configured)


@pytest.mark.parametrize("count", [True, False, 1.0, "1", 0, 4097, None])
def test_expected_name_configuration_refuses_noninteger_or_unbounded_counts(probe, count):
    with pytest.raises(AssertionError, match="count"):
        probe._expected_tool_names({"expected_tools": count})


def test_expected_name_source_hash_and_payload_are_both_verified(probe, tmp_path):
    configured = expected_names(tmp_path, ["toolsets.list"])
    path = Path(configured["expected_tool_names_source"])
    path.write_text('["scene.inspect"]\n')
    with pytest.raises(AssertionError, match="file changed"):
        probe._expected_tool_names(configured)
    configured["expected_tool_names_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(AssertionError, match="disagrees"):
        probe._expected_tool_names(configured)
