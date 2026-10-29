from __future__ import annotations

import importlib
import os
from dataclasses import FrozenInstanceError, replace

import pytest


@pytest.fixture
def source(addon_package, tmp_path):
    module = importlib.import_module(addon_package + ".glb_stage_source")
    root = tmp_path / "approved GLB sources"
    root.mkdir()
    path = root / "complete.glb"
    path.write_bytes(b"independently parsed later" + b"-" * 20)
    return module, root, path


def test_snapshot_read_verify_and_proof_never_write_source(source):
    module, root, path = source
    original = path.read_bytes()
    snapshot = module.read_glb_source(str(path), str(root))
    snapshot.verify(str(root))
    assert snapshot.payload == original == path.read_bytes()
    assert snapshot.proof()["source_write_performed"] is False
    assert snapshot.file_identity[2] == len(original)
    assert all(type(row) is tuple for row in snapshot.ancestry)
    with pytest.raises(FrozenInstanceError):
        snapshot.payload = b"changed"


@pytest.mark.parametrize("size", [27, 8 * 1024**2 + 1, 64 * 1024**2])
def test_size_refusal_precedes_any_payload_read(source, monkeypatch, size):
    module, root, path = source
    with path.open("wb") as stream:
        stream.truncate(size)
    monkeypatch.setattr(module.os, "read", lambda *_: pytest.fail("oversized source read"))
    with pytest.raises(module.BridgeError):
        module.read_glb_source(str(path), str(root))


@pytest.mark.parametrize("size", [28, 65536, 65537, 8 * 1024**2])
def test_complete_reads_never_exceed_64k_or_fixed_eight_mebibytes(source, monkeypatch, size):
    module, root, path = source
    path.write_bytes(b"x" * size)
    reads, checks = [], []
    original = module.os.read

    def observe(fd, count):
        assert 1 <= count <= 65536
        reads.append((count, len(checks)))
        return original(fd, count)

    monkeypatch.setattr(module.os, "read", observe)
    snapshot = module.read_glb_source(str(path), str(root), lambda: checks.append(True))
    assert snapshot.payload == b"x" * size
    assert sum(n for n, _ in reads) == size <= module.MAX_BYTES
    assert len({stamp for _, stamp in reads}) == len(reads)


@pytest.mark.parametrize("kind", ["outside", "relative", "empty_root", "volume_root", "extension",
                                  "source_link", "ancestor_link", "directory", "fifo", "unreadable"])
def test_unapproved_or_nonordinary_sources_refuse(source, kind):
    module, root, path = source
    approval, raw = str(root), str(path)
    if kind == "outside":
        approval = str(root / "other")
    elif kind == "relative":
        raw = "complete.glb"
    elif kind == "empty_root":
        approval = ""
    elif kind == "volume_root":
        approval = path.anchor
    elif kind == "extension":
        raw = str(root / "complete.fbx")
    elif kind == "source_link":
        alias = root / "alias.glb"
        alias.symlink_to(path)
        raw = str(alias)
    elif kind == "ancestor_link":
        alias = root.parent / "alias"
        alias.symlink_to(root, target_is_directory=True)
        raw = str(alias / path.name)
    elif kind == "directory":
        raw = str(root / "folder.glb")
        (root / "folder.glb").mkdir()
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    else:
        raw = str(root / "absent.glb")
    with pytest.raises(module.BridgeError):
        module.read_glb_source(raw, approval)


def test_cancel_precedes_every_filesystem_probe(source, monkeypatch):
    module, root, path = source
    monkeypatch.setattr(module, "_absolute", lambda *_: pytest.fail("path API invoked"))

    def denied():
        raise RuntimeError("cancelled before path")

    with pytest.raises(RuntimeError, match="cancelled before path"):
        module.read_glb_source(str(path), str(root), denied)


@pytest.mark.parametrize("kind", ["grow", "shrink", "replace", "root_replace", "parent_symlink"])
def test_mutation_after_first_chunk_stops_before_next_read(source, monkeypatch, kind):
    module, root, path = source
    path.write_bytes(b"a" * (3 * 65536))
    read, count = module.os.read, []

    def change(fd, maximum):
        result = read(fd, maximum)
        count.append(True)
        if len(count) == 1:
            if kind == "grow":
                with path.open("ab") as stream:
                    stream.write(b"b")
            elif kind == "shrink":
                path.write_bytes(b"x" * 28)
            elif kind == "replace":
                path.rename(root / "old.glb")
                path.write_bytes(b"b" * (3 * 65536))
            else:
                old = root.with_name("original-root")
                root.rename(old)
                if kind == "root_replace":
                    root.mkdir()
                else:
                    outside = root.with_name("outside")
                    outside.mkdir()
                    (outside / path.name).write_bytes(b"unapproved" * 10000)
                    root.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(module.os, "read", change)
    with pytest.raises(module.BridgeError):
        module.read_glb_source(str(path), str(root))
    assert len(count) == 1


def test_cancellation_after_a_chunk_closes_all_owned_descriptors(source, monkeypatch):
    module, root, path = source
    path.write_bytes(b"a" * 131072)
    original, descriptors = module.os.read, []

    def read(fd, count):
        descriptors.append(fd)
        return original(fd, count)

    def check():
        if descriptors:
            raise RuntimeError("expired after first read")

    monkeypatch.setattr(module.os, "read", read)
    with pytest.raises(RuntimeError, match="expired after first read"):
        module.read_glb_source(str(path), str(root), check)
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_revalidation_checks_complete_bytes_even_same_metadata(source):
    module, root, path = source
    snapshot = module.read_glb_source(str(path), str(root))
    before = path.stat()
    path.write_bytes(b"z" * before.st_size)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(module.BridgeError):
        snapshot.verify(str(root))


def test_revalidation_cannot_adopt_a_different_approved_root(source):
    module, root, path = source
    snapshot = module.read_glb_source(str(path), str(root))
    with pytest.raises(module.BridgeError):
        snapshot.verify(str(root.parent))


@pytest.mark.parametrize("field,value", [("payload", bytearray(b"x" * 28)), ("sha256", "a" * 64),
                                        ("file_identity", (0, 1, 28, True)), ("ancestry", [])])
def test_snapshot_integrity_is_not_a_caller_container_or_stale_digest(source, field, value):
    module, root, path = source
    snapshot = module.read_glb_source(str(path), str(root))
    with pytest.raises(module.BridgeError):
        replace(snapshot, **{field: value}).validate()


def test_missing_descriptor_relative_platform_support_fails_closed(source, monkeypatch):
    module, root, path = source
    monkeypatch.setattr(module.os, "supports_dir_fd", set())
    with pytest.raises(module.BridgeError) as error:
        module.read_glb_source(str(path), str(root))
    assert error.value.code == "NOT_IMPLEMENTED"


def test_foreign_parent_descriptor_refuses_before_payload_read(source, monkeypatch):
    module, root, path = source
    outside = root.parent / "unapproved"
    outside.mkdir()
    (outside / path.name).write_bytes(b"unapproved sentinel" * 10)
    original = module._open_directory
    monkeypatch.setattr(module, "_open_directory", lambda _path, check: original(outside, check))
    monkeypatch.setattr(module.os, "read", lambda *_: pytest.fail("foreign descriptor read"))
    with pytest.raises(module.BridgeError):
        module.read_glb_source(str(path), str(root))


def test_race_to_fifo_is_nonblocking_and_rejected_before_read(source, monkeypatch):
    module, root, path = source
    original = module.os.open

    def race(name, flags, **kwargs):
        if name == path.name:
            assert flags & os.O_NONBLOCK
            path.unlink()
            os.mkfifo(path)
        return original(name, flags, **kwargs)

    monkeypatch.setattr(module.os, "supports_dir_fd", {*module.os.supports_dir_fd, race})
    monkeypatch.setattr(module.os, "open", race)
    monkeypatch.setattr(module.os, "read", lambda *_: pytest.fail("FIFO read"))
    with pytest.raises(module.BridgeError):
        module.read_glb_source(str(path), str(root))


@pytest.mark.parametrize("kind", ["path", "root", "ancestry_text", "ancestry_integer",
                                  "identity_integer", "identity_time", "negative_inode"])
def test_manually_constructed_snapshot_cannot_retain_unbounded_metadata(source, monkeypatch, kind):
    module, root, path = source
    snapshot = module.read_glb_source(str(path), str(root))
    monkeypatch.setattr(type(path), "open", lambda *_a, **_k: pytest.fail("pure validation opened a path"))
    if kind == "path":
        snapshot = replace(snapshot, path="/" + "x" * 4096)
    elif kind == "root":
        snapshot = replace(snapshot, approved_root="/" + "x" * 4096)
    elif kind == "ancestry_text":
        snapshot = replace(snapshot, ancestry=(("x" * 1_000_000, 1, 2),))
    elif kind == "ancestry_integer":
        row = snapshot.ancestry[0]
        snapshot = replace(snapshot, ancestry=((row[0], 2**4096, row[2]), *snapshot.ancestry[1:]))
    elif kind == "identity_integer":
        snapshot = replace(snapshot, file_identity=(2**4096, *snapshot.file_identity[1:]))
    elif kind == "identity_time":
        snapshot = replace(snapshot, file_identity=(*snapshot.file_identity[:3], 2**80))
    else:
        snapshot = replace(snapshot, file_identity=(snapshot.file_identity[0], -1, *snapshot.file_identity[2:]))
    with pytest.raises(module.BridgeError):
        snapshot.validate()


def test_source_metadata_is_bounded_and_part_of_retained_payload_accounting(source, monkeypatch):
    module, root, path = source
    snapshot = module.read_glb_source(str(path), str(root))
    metadata = snapshot.metadata_bytes()
    assert snapshot.accounted_bytes == len(snapshot.payload) + len(metadata)
    assert len(metadata) < module.MAX_METADATA_BYTES
    monkeypatch.setattr(module, "MAX_METADATA_BYTES", 1)
    with pytest.raises(module.BridgeError):
        snapshot.metadata_bytes()
