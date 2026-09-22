from __future__ import annotations

import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest

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


def test_release_components_match() -> None:
    assert load_script("build_release").release_version(ROOT) == "0.3.0"


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
    "addon/blender_codex_bridge/constants.py",
    "addon/blender_codex_bridge/blender_manifest.toml",
    "mcp_server/__init__.py",
    "plugins/blender-codex-bridge/.codex-plugin/plugin.json",
])
def test_mismatched_release_fails_before_build(tmp_path: Path, component: str) -> None:
    files = {
        "pyproject.toml": 'version = "0.3.0"',
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
