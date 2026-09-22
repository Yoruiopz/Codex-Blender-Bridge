from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest


def test_plugin_release_is_reproducible_and_excludes_marketplace(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("release_builder", root / "scripts" / "build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((root / "plugins/blender-codex-bridge/.codex-plugin/plugin.json").read_text())
    first = module.package_plugin(root, tmp_path / "a", manifest["version"])
    second = module.package_plugin(root, tmp_path / "b", manifest["version"])
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        names = archive.namelist()
        assert "blender-codex-bridge/.codex-plugin/plugin.json" in names
        assert "blender-codex-bridge/.mcp.json" in names
        assert not any(".agents/" in name or "__pycache__" in name for name in names)
        assert archive.testzip() is None
    with pytest.raises(ValueError, match="version"):
        module.package_plugin(root, tmp_path / "bad", "999.0.0")
