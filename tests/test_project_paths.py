from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_save_as_path_requires_safe_absolute_blend_path(
    addon_package: str, tmp_path: Path
) -> None:
    core = importlib.import_module(f"{addon_package}.tools.core")
    errors = importlib.import_module(f"{addon_package}.errors")

    target = tmp_path / "approved.blend"
    assert core._resolve_save_as_path(str(target)) == target.resolve()

    for unsafe in (
        "relative.blend",
        "~/implicit.blend",
        "//server/share/project.blend",
        "\\\\server\\share\\project.blend",
        str(tmp_path / "folder" / ".." / "traversal.blend"),
        str(tmp_path / "wrong.txt"),
        str(tmp_path / "bad\x00name.blend"),
    ):
        with pytest.raises(errors.BridgeError):
            core._resolve_save_as_path(unsafe)
