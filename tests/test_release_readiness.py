from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from mcp_server import __version__
from mcp_server.tool_registry import create_default_registry

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_inventory_matches_registry() -> None:
    module = load_script("readme_tools")
    current = (ROOT / "README.md").read_text(encoding="utf-8")
    assert module.updated_readme(current) == current
    inventory = module.render_inventory()
    registry = create_default_registry(None)
    names = registry.tool_names(include_disabled=True)
    documented = [line.split("`")[1] for line in inventory.splitlines() if line.startswith("| `")]
    assert sorted(documented) == sorted(names)


def test_inventory_rejects_missing_markers() -> None:
    with pytest.raises(ValueError, match="marker"):
        load_script("readme_tools").updated_readme("README without markers")


@pytest.mark.parametrize("root_already_present", [False, True])
def test_inventory_cli_uses_its_checkout_over_another_installed_package(tmp_path, root_already_present):
    package = tmp_path / "shadow" / "mcp_server"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('raise AssertionError("wrong MCP checkout")\n')
    python_path = str(package.parent) + (os.pathsep + str(ROOT) if root_already_present else "")
    environment = dict(os.environ, PYTHONPATH=python_path)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/readme_tools.py"), "--check"],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_release_components_match() -> None:
    assert load_script("build_release").release_version(ROOT) == __version__


@pytest.mark.parametrize("name,metadata_version,runtime_version,valid", [
    ("blender-codex-bridge", "0.3.0", "0.3.0", True),
    ("blender_codex_bridge", "0.3.0", "0.3.0", True),
    ("another-package", "0.3.0", "0.3.0", False),
    ("blender-codex-bridge", "0.2.0", "0.3.0", False),
    ("blender-codex-bridge", "0.3.0", "0.2.0", False),
])
def test_wheel_identity_is_verified(tmp_path: Path, name: str, metadata_version: str,
                                   runtime_version: str, valid: bool) -> None:
    wheel = tmp_path / "blender_codex_bridge-0.3.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("blender_codex_bridge-0.3.0.dist-info/METADATA",
                         f"Metadata-Version: 2.1\nName: {name}\nVersion: {metadata_version}\n")
        archive.writestr("mcp_server/__init__.py", f'__version__ = "{runtime_version}"\n')
    builder = load_script("build_release")
    if valid:
        builder.validate_wheel(wheel, "0.3.0")
    else:
        with pytest.raises(ValueError, match="version"):
            builder.validate_wheel(wheel, "0.3.0")


@pytest.mark.parametrize("metadata_count", [0, 2])
def test_wheel_requires_unambiguous_metadata(tmp_path: Path, metadata_count: int) -> None:
    wheel = tmp_path / "release.whl"
    with ZipFile(wheel, "w") as archive:
        for index in range(metadata_count):
            archive.writestr(f"package{index}.dist-info/METADATA", "Name: blender-codex-bridge\nVersion: 0.3.0\n")
    with pytest.raises(ValueError, match="exactly one"):
        load_script("build_release").validate_wheel(wheel, "0.3.0")


@pytest.mark.parametrize("component", [
    "addon/blender_codex_bridge/__init__.py",
    "addon/blender_codex_bridge/constants.py",
    "addon/blender_codex_bridge/blender_manifest.toml",
    "mcp_server/__init__.py",
    "plugins/blender-codex-bridge/.codex-plugin/plugin.json",
])
def test_mismatched_release_fails_before_build(tmp_path: Path, component: str) -> None:
    files = {
        "pyproject.toml": 'version = "0.3.0"',
        "addon/blender_codex_bridge/__init__.py": 'bl_info = {"version": (0, 3, 0)}',
        "addon/blender_codex_bridge/constants.py": "ADDON_VERSION = (0, 3, 0)",
        "addon/blender_codex_bridge/blender_manifest.toml": 'version = "0.3.0"',
        "mcp_server/__init__.py": '__version__ = "0.3.0"',
        "plugins/blender-codex-bridge/.codex-plugin/plugin.json": '{"name":"blender-codex-bridge","version":"0.3.0"}',
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name == component:
            content = content.replace("0.3.0", "0.2.0").replace("(0, 3, 0)", "(0, 2, 0)")
        path.write_text(content, encoding="utf-8")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="versions disagree"):
        load_script("build_release").build(tmp_path, output)
    assert not output.exists()


@pytest.fixture
def probe_package(tmp_path: Path) -> Path:
    package = tmp_path / "candidate.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr("blender_codex_bridge/__init__.py", "")
        archive.writestr("blender_codex_bridge/constants.py", "ADDON_VERSION = (0, 4, 0)\n")
    return package


def test_installed_probe_pins_exact_inventory_bytes_and_sorted_names(probe_package, tmp_path):
    module = load_script("package_probe_config")
    tools = tmp_path / "accepted tools.json"
    payload = b'[\n  "transform.set",\n  "toolsets.list",\n  "bridge.status"\n]\n'
    tools.write_bytes(payload)
    record = module.package_record(probe_package, 3, tools_file=tools)
    assert record["expected_tool_names"] == ["bridge.status", "toolsets.list", "transform.set"]
    assert record["expected_tool_names_sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["expected_tool_names_source"] == str(tools.resolve())
    assert record["expected_tools"] == 3
    assert record["require_discovery"] is True


def test_installed_probe_count_only_configuration_remains_available(probe_package):
    record = load_script("package_probe_config").package_record(probe_package, 108, require_discovery=False)
    assert record["expected_tools"] == 108
    assert record["require_discovery"] is False
    assert not any(name.startswith("expected_tool_names") for name in record)


@pytest.mark.parametrize("count", [True, False, 1.0, "1", None, 0, -1, 4097])
def test_installed_probe_rejects_noninteger_and_unbounded_tool_counts(probe_package, count):
    with pytest.raises(ValueError):
        load_script("package_probe_config").package_record(probe_package, count)


@pytest.mark.parametrize("payload,count", [
    (b'{}', 1),
    (b'"toolsets.list"', 1),
    (b'null', 1),
    (b'[]', 1),
    (b'["toolsets.list", "toolsets.list"]', 2),
    (b'["toolsets.list"]', 2),
    (b'["toolsets.list", 1]', 2),
    (b'["toolsets.list", true]', 2),
    (b'["toolsets.list", null]', 2),
    (b'["toolsets.list", ["transform.set"]]', 2),
    (b'[NaN]', 1),
    (b'[Infinity]', 1),
    (b'[-Infinity]', 1),
    (b'\xff', 1),
    (b'not JSON', 1),
])
def test_installed_probe_rejects_invalid_inventory_documents(probe_package, tmp_path, payload, count):
    tools = tmp_path / "tools.json"
    tools.write_bytes(payload)
    with pytest.raises(ValueError):
        load_script("package_probe_config").package_record(probe_package, count, tools_file=tools)


@pytest.mark.parametrize("name", [
    "", "toolsets", "Toolsets.list", "toolsets.List", "toolsets.list\n", " toolsets.list",
    "toolsets.list ", ".toolsets.list", "toolsets..list", "toolsets/list", "toolsets.list-name",
    "toolsets.1list", "toolsets.líst", "toolsets.\u0000list", "a." + "v" * 127,
])
def test_installed_probe_rejects_invalid_public_method_names(probe_package, tmp_path, name):
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps([name]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_script("package_probe_config").package_record(probe_package, 1, tools_file=tools)


def test_installed_probe_inventory_byte_limit_is_inclusive(probe_package, tmp_path):
    module = load_script("package_probe_config")
    tools = tmp_path / "tools.json"
    payload = b'["toolsets.list"]'
    boundary = payload + b' ' * (512 * 1024 - len(payload))
    tools.write_bytes(boundary)
    assert module.package_record(probe_package, 1, tools_file=tools)["expected_tool_names_sha256"] == hashlib.sha256(boundary).hexdigest()
    tools.write_bytes(boundary + b' ')
    with pytest.raises(ValueError):
        module.package_record(probe_package, 1, tools_file=tools)


def test_installed_probe_accepts_maximum_method_name_length(probe_package, tmp_path):
    tools = tmp_path / "tools.json"
    name = "a." + "v" * 126
    tools.write_text(json.dumps([name]), encoding="utf-8")
    record = load_script("package_probe_config").package_record(probe_package, 1, tools_file=tools)
    assert record["expected_tool_names"] == [name]


def test_installed_probe_cli_pins_candidate_inventory_only(probe_package, tmp_path, monkeypatch):
    tools = tmp_path / "tools.json"
    tools.write_bytes(b'["toolsets.list"]\n')
    output = tmp_path / "probe.json"
    monkeypatch.setattr(sys, "argv", [
        "package_probe_config.py", "--candidate", str(probe_package), "--candidate-tools", "1",
        "--candidate-tools-file", str(tools), "--previous", str(probe_package), "--previous-tools", "108",
        "--allow-previous-undiscoverable", "--output", str(output),
    ])
    load_script("package_probe_config").main()
    config = json.loads(output.read_text(encoding="utf-8"))
    assert config["candidate"]["expected_tool_names"] == ["toolsets.list"]
    assert config["candidate"]["expected_tool_names_sha256"] == hashlib.sha256(tools.read_bytes()).hexdigest()
    assert config["previous"]["expected_tools"] == 108
    assert config["previous"]["require_discovery"] is False
    assert not any(name.startswith("expected_tool_names") for name in config["previous"])
