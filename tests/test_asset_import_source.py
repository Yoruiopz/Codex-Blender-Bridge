from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def source(addon_package, tmp_path):
    module = importlib.import_module(addon_package + ".asset_import_source")
    root = tmp_path / "Approved Source With Spaces"
    root.mkdir()
    path = root / "asset.glb"
    path.write_bytes(b"validated complete bytes")
    return module, root, path


def test_source_read_snapshot_and_owned_private_copy(source):
    module, root, path = source
    snapshot = module.read_source(str(path), "GLB", str(root))
    assert snapshot.payload == path.read_bytes()
    snapshot.verify(str(root))
    staging = module.OwnedInput(snapshot)
    staging.create(lambda: None)
    try:
        assert staging.path.read_bytes() == snapshot.payload
        assert staging.directory.parent != root
        if os.name != "nt":
            assert staging.directory.stat().st_mode & 0o777 == 0o700
            assert staging.path.stat().st_mode & 0o777 == 0o600
        staging.verify()
    finally:
        staging.cleanup(lambda: None)
    assert staging.evidence()["staging_cleanup"] == "removed"
    assert path.read_bytes() == snapshot.payload


@pytest.mark.parametrize(
    "kind", ["empty_root", "outside", "source_link", "ancestor_link", "extension", "relative"]
)
def test_source_admission_denies_unapproved_paths(source, kind):
    module, root, path = source
    approved, raw = str(root), str(path)
    if kind == "empty_root":
        approved = ""
    elif kind == "outside":
        approved = str(root / "inner")
        Path(approved).mkdir()
    elif kind == "source_link":
        alias = root / "alias.glb"
        alias.symlink_to(path)
        raw = str(alias)
    elif kind == "ancestor_link":
        alias = root.parent / "alias"
        alias.symlink_to(root, target_is_directory=True)
        raw = str(alias / path.name)
    elif kind == "extension":
        raw = str(root / "asset.fbx")
    else:
        raw = "asset.glb"
    with pytest.raises(module.BridgeError):
        module.read_source(raw, "GLB", approved)


def test_denial_callback_precedes_any_filesystem_probe(source, monkeypatch):
    module, root, path = source
    monkeypatch.setattr(module, "_absolute", lambda *_: pytest.fail("path probed"))

    def deny():
        raise RuntimeError("denied")

    with pytest.raises(RuntimeError, match="denied"):
        module.read_source(str(path), "GLB", str(root), deny)


@pytest.mark.parametrize("kind", ["rewrite", "replace", "root_replace"])
def test_revalidation_rejects_stale_complete_source_identity(source, kind):
    module, root, path = source
    snapshot = module.read_source(str(path), "GLB", str(root))
    if kind == "rewrite":
        path.write_bytes(b"changed complete bytes")
    elif kind == "replace":
        path.rename(root / "old.glb")
        path.write_bytes(snapshot.payload)
    else:
        root.rename(root.parent / "old-root")
        root.mkdir()
        path.write_bytes(snapshot.payload)
    with pytest.raises(module.BridgeError):
        snapshot.verify(str(root))


@pytest.mark.parametrize("kind", ["replace", "extra", "permission"])
def test_cleanup_never_deletes_unowned_entries_or_ignores_revocation(source, kind):
    module, root, path = source
    staging = module.OwnedInput(module.read_source(str(path), "GLB", str(root)))
    staging.create(lambda: None)
    directory, temporary = staging.directory, staging.path
    assert directory and temporary
    backup = None
    if kind == "replace":
        backup = directory / "old.glb"
        temporary.rename(backup)
        temporary.write_bytes(b"newer unrelated bytes")
    elif kind == "extra":
        (directory / "unexpected").write_bytes(b"keep")

    def gate():
        if kind == "permission":
            raise RuntimeError("consent revoked")

    staging.cleanup(gate)
    assert temporary.exists() and staging.evidence()["retained_staging_path"] == str(directory)
    # Test process owns its own cleanup after asserting the product refusal.
    for item in directory.iterdir():
        item.unlink()
    directory.rmdir()


def test_native_input_verification_rejects_same_length_changed_bytes(source):
    module, root, path = source
    staging = module.OwnedInput(module.read_source(str(path), "GLB", str(root)))
    staging.create(lambda: None)
    original = staging.path.stat()
    staging.path.write_bytes(b"x" * len(staging.source.payload))
    os.utime(staging.path, ns=(original.st_atime_ns, original.st_mtime_ns))
    with pytest.raises(module.BridgeError):
        staging.verify()
    staging.cleanup(lambda: None)
    if staging.directory.exists():
        staging.path.unlink()
        staging.directory.rmdir()


def test_callback_ancestor_replacement_never_reads_outside_approved_folder(source, monkeypatch):
    module, root, path = source
    outside = root.parent / "outside"
    outside.mkdir()
    sentinel = b"UNAPPROVED SOURCE"
    (outside / path.name).write_bytes(sentinel)
    calls, reads = [], []
    original_read = module.os.read

    def check():
        calls.append(True)
        if len(calls) == 2:
            root.rename(root.parent / "original-root")
            root.symlink_to(outside, target_is_directory=True)

    def spy(*args):
        result = original_read(*args)
        reads.append(result)
        return result

    monkeypatch.setattr(module.os, "read", spy)
    with pytest.raises(module.BridgeError):
        module.read_source(str(path), "GLB", str(root), check)
    assert sentinel not in reads


def test_private_staging_never_allocates_inside_approved_read_folder(source, monkeypatch):
    module, root, path = source
    staging = module.OwnedInput(module.read_source(str(path), "GLB", str(root)))
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(root))
    with pytest.raises(module.BridgeError):
        staging.create(lambda: None)
    assert list(root.iterdir()) == [path] and staging.directory is None
