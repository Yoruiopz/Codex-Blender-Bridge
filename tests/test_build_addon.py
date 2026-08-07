from __future__ import annotations

import importlib.util
from pathlib import Path
from zipfile import ZipFile


def _build_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_addon.py"
    spec = importlib.util.spec_from_file_location("build_addon_for_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_addon_build_is_reproducible_and_validated(tmp_path: Path) -> None:
    module = _build_module()
    first = module.build(tmp_path / "first.zip")
    second = module.build(tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    module.validate_archive(first)
    with ZipFile(first) as archive:
        names = archive.namelist()
    assert "blender_codex_bridge/__init__.py" in names
    assert "blender_codex_bridge/blender_manifest.toml" in names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
