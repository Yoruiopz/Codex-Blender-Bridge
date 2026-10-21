from __future__ import annotations

import hashlib
import importlib.util
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
