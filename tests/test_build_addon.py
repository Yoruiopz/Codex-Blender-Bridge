from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from zipfile import ZipFile

import pytest


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


@pytest.mark.parametrize("replacement,message", [
    (b'"version": ADDON_VERSION', "literal bl_info"),
    (b'"version": (99, 0, 0)', "versions disagree"),
])
def test_archive_rejects_undiscoverable_or_mismatched_metadata(tmp_path, replacement, message):
    module = _build_module()
    original = module.build(tmp_path / "original.zip")
    changed = tmp_path / "changed.zip"
    with ZipFile(original) as source, ZipFile(changed, "w") as target:
        for item in source.infolist():
            payload = source.read(item)
            if item.filename == "blender_codex_bridge/__init__.py":
                version_literal = re.search(rb'"version": \([0-9]+, [0-9]+, [0-9]+\)', payload)
                assert version_literal is not None
                payload = payload.replace(version_literal[0], replacement, 1)
            target.writestr(item, payload)
    with pytest.raises(ValueError, match=message):
        module.validate_archive(changed)
