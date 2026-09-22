from __future__ import annotations

import importlib.util
from pathlib import Path

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
