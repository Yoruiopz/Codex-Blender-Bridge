from __future__ import annotations

import hashlib
import importlib
import os
import threading
from array import array
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def staging(addon_package, tmp_path):
    module = importlib.import_module(f"{addon_package}.texture_staging")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    grants = {permission.value: True for permission in permissions.Permission}
    manager = permissions.PermissionManager(lambda: grants)
    flags = {"paused": False, "emergency_stopped": False}
    context = NS(require=lambda *required: manager.require(required), check_cancelled=None,
                 state=NS(snapshot=lambda: dict(flags)))
    root, resources = [str(tmp_path)], []

    def factory(name="texture.png", format="PNG16", role="DATA"):
        item = module.TextureStaging(context, str(tmp_path / name), lambda: root[0], format, role)
        resources.append(item)
        return item

    yield NS(module=module, make=factory, context=context, grants=grants, flags=flags, root=root)
    for resource in resources:
        resource.cleanup()


def encode(item, values=None, width=2, height=1):
    return list(item.encode_steps(values if values is not None else array("f", [.25, .5, 1., 0., 1., .5, .25, .75]), width, height))


@pytest.mark.parametrize("format", ["PNG8", "PNG16", "EXR32", "EXR32_RAW"])
@pytest.mark.parametrize("role", ["COLOR", "DATA"])
def test_complete_stream_seals_hashes_publishes_without_overwrite(staging, format, role):
    item = staging.make("texture.png" if format.startswith("PNG") else "texture.exr", format, role)
    progress = encode(item)
    assert progress[-1]["phase"] == "verifying_staging"
    assert progress[-1]["completed"] == progress[-1]["total"] == item.bytes
    assert item.sealed and not item.path.exists() and item.stream is None
    assert not item.evidence()["publication_attempted"] and not item.evidence()["publication_outcome_unknown"]
    assert item.stage.read_bytes()[:4] == (b"\x89PNG" if format.startswith("PNG") else b"v/1\x01")
    evidence = item.publish()
    assert evidence["file_published"] and not evidence["published_file_hash_verified"]
    assert evidence["publication_attempted"] and not evidence["publication_outcome_unknown"]
    list(item.verify_published_steps())
    assert item.evidence()["published_file_hash_verified"]
    assert hashlib.sha256(item.path.read_bytes()).hexdigest() == evidence["file_sha256"]
    assert item.path.stat().st_ino == item.stage.stat().st_ino
    cleanup = item.cleanup()
    assert cleanup["staging_cleanup"] == "removed" and cleanup["retained_staging_path"] is None
    assert item.path.exists() and not item.stage.exists()
    assert cleanup["external_file_survives_native_undo"] and not cleanup["pixel_roundtrip_verified"]
    assert item.cleanup() == cleanup


@pytest.mark.parametrize("permission", ["EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT"])
def test_denial_precedes_root_and_filesystem_probes(staging, monkeypatch, permission, tmp_path):
    item = staging.make()
    staging.grants[permission] = False
    monkeypatch.setattr(staging.module, "approved_output", lambda *_a: pytest.fail("unauthorized path probe"))
    item.root = lambda: pytest.fail("unauthorized preferences/path probe")
    with pytest.raises(staging.module.BridgeError) as error:
        encode(item)
    assert error.value.code == "PERMISSION_DENIED"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw", ["relative.png", "//server/x.png", "\\\\server\\x.png", "x\ny.png", "https://host/a.png"])
def test_unsafe_output_syntax_fails(staging, tmp_path, raw):
    item = staging.make()
    item.raw = raw
    with pytest.raises(staging.module.BridgeError):
        encode(item)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["outside", "root_volume", "missing_parent", "traversal", "reserved", "trailing_dot", "extension", "missing_root"])
def test_output_scope_and_portable_names(staging, tmp_path, kind):
    item = staging.make()
    if kind == "outside":
        child = tmp_path / "approved"
        child.mkdir()
        staging.root[0] = str(child)
    elif kind == "root_volume":
        staging.root[0] = str(tmp_path.anchor)
    elif kind == "missing_parent":
        item.raw = str(tmp_path / "missing" / "texture.png")
    elif kind == "traversal":
        item.raw = str(tmp_path / "missing" / ".." / "texture.png")
    elif kind == "reserved":
        item.raw = str(tmp_path / "CON.png")
    elif kind == "trailing_dot":
        item.raw = str(tmp_path / "texture.png.")
    elif kind == "extension":
        item.raw = str(tmp_path / "texture.jpg")
    else:
        staging.root[0] = ""
    with pytest.raises(staging.module.BridgeError):
        encode(item)
    assert not list(tmp_path.glob(".blender-codex-*"))


def test_network_drive_denied(staging, monkeypatch):
    monkeypatch.setattr(staging.module, "_local_drive", lambda _p: False)
    with pytest.raises(staging.module.BridgeError, match="local drive"):
        encode(staging.make())


@pytest.mark.parametrize("target_kind", ["file", "directory"])
def test_existing_output_refused_before_staging(staging, tmp_path, target_kind):
    target = tmp_path / "texture.png"
    target.write_bytes(b"protected") if target_kind == "file" else target.mkdir()
    with pytest.raises(staging.module.BridgeError, match="already exists"):
        encode(staging.make())
    assert not list(tmp_path.glob(".blender-codex-*"))
    if target_kind == "file":
        assert target.read_bytes() == b"protected"


def test_atomic_competitor_creation_cannot_clobber(staging, monkeypatch):
    item = staging.make()
    encode(item)
    link = os.link

    def competing(source, destination, **kwargs):
        Path(destination).write_bytes(b"other actor's output")
        return link(source, destination, **kwargs)

    monkeypatch.setattr(staging.module.os, "link", competing)
    with pytest.raises(staging.module.BridgeError, match="No-clobber"):
        item.publish()
    assert not item.published and item.path.read_bytes() == b"other actor's output"
    assert item.cleanup()["staging_cleanup"] == "removed"
    assert item.path.read_bytes() == b"other actor's output"


def test_unsupported_link_has_no_rename_or_copy_fallback(staging, monkeypatch):
    item = staging.make()
    encode(item)
    monkeypatch.setattr(staging.module.os, "link", lambda *_a, **_k: (_ for _ in ()).throw(OSError("unsupported")))
    monkeypatch.setattr(staging.module.os, "replace", lambda *_a, **_k: pytest.fail("overwrite fallback"))
    monkeypatch.setattr(staging.module.os, "rename", lambda *_a, **_k: pytest.fail("rename fallback"))
    with pytest.raises(staging.module.BridgeError, match="No-clobber"):
        item.publish()
    assert not item.path.exists() and not item.published


def test_late_revocation_retains_truthful_published_and_staging_evidence(staging, monkeypatch):
    item = staging.make()
    encode(item)
    link = os.link

    def revoke(source, destination, **kwargs):
        link(source, destination, **kwargs)
        staging.grants["SAVE_PROJECT"] = False

    monkeypatch.setattr(staging.module.os, "link", revoke)
    with pytest.raises(staging.module.BridgeError) as error:
        item.publish()
    assert error.value.code == "PERMISSION_DENIED"
    proof = item.cleanup()
    assert proof["file_published"] and proof["file_sha256"]
    assert proof["staging_cleanup"] == "retained_permission_denied"
    assert item.path.exists() and item.stage.exists()
    assert not proof["published_file_hash_verified"]


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_publication_syscall_can_have_effect_before_raising(staging, monkeypatch, failure):
    item = staging.make()
    encode(item)
    link = os.link

    def interrupted(source, destination, **kwargs):
        link(source, destination, **kwargs)
        raise failure("signal/IO error after filesystem effect")

    monkeypatch.setattr(staging.module.os, "link", interrupted)
    with pytest.raises(staging.module.BridgeError if failure is OSError else failure):
        item.publish()
    evidence = item.cleanup()
    assert evidence["publication_attempted"] and evidence["publication_outcome_unknown"]
    assert not evidence["file_published"]  # Not confirmed, NOT a negative existence proof.
    assert item.path.exists() and evidence["filepath"] == str(item.path)
    assert evidence["staging_cleanup"] == "removed" and evidence["file_sha256"]


@pytest.mark.parametrize("permission", ["EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT"])
def test_revocation_during_encoding_retains_only_owned_staging(staging, monkeypatch, permission):
    item = staging.make()
    work = item.encode_steps(array("f", [.2, .4, .6, 1.]), 1, 1)
    next(work)
    assert item.bytes > 0 and not item.path.exists()
    staging.grants[permission] = False
    monkeypatch.setattr(staging.module, "approved_output", lambda *_a: pytest.fail("revoked IO probe"))
    with pytest.raises(staging.module.BridgeError) as error:
        next(work)
    assert error.value.code == "PERMISSION_DENIED"
    proof = item.cleanup()
    assert proof["retained_staging_path"] == str(item.stage)
    assert proof["staging_cleanup"] == "retained_permission_denied"
    assert not proof["file_published"] and not item.path.exists()


@pytest.mark.parametrize("flag,code", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")])
def test_pause_stop_blocks_next_write_but_allows_private_cleanup(staging, flag, code):
    item = staging.make()
    work = item.encode_steps(array("f", [.2, .4, .6, 1.]), 1, 1)
    next(work)
    count = item.bytes
    staging.flags[flag] = True
    with pytest.raises(staging.module.BridgeError) as error:
        next(work)
    assert error.value.code == code and item.bytes == count
    assert item.cleanup()["staging_cleanup"] == "removed"
    assert not item.path.exists()


def test_cancellation_and_generator_close_do_not_publish(staging):
    item = staging.make()
    work = item.encode_steps(array("f", [.2, .4, .6, 1.]), 1, 1)
    next(work)

    def cancelled():
        raise staging.module.BridgeError(staging.module.ErrorCode.TIMEOUT, "canceled")

    staging.context.check_cancelled = cancelled
    with pytest.raises(staging.module.BridgeError, match="canceled"):
        next(work)
    assert item.cleanup()["staging_cleanup"] == "removed"
    other = staging.make("closed.png")
    staging.context.check_cancelled = None
    work = other.encode_steps(array("f", [.2, .4, .6, 1.]), 1, 1)
    next(work)
    work.close()
    with pytest.raises(staging.module.BridgeError, match="sealed"):
        other.publish()
    assert other.cleanup()["staging_cleanup"] == "removed"
    assert not other.path.exists()


def test_invalid_late_pixel_remains_private_and_cleans(staging):
    item = staging.make()
    with pytest.raises(staging.module.BridgeError, match="finite"):
        encode(item, array("f", [0., 0., 0., 1., float("nan"), 0., 0., 1.]))
    assert item.bytes > 0 and not item.sealed and not item.path.exists()
    assert item.cleanup()["staging_cleanup"] == "removed"


def test_file_and_block_budgets_precede_write(staging, monkeypatch):
    item = staging.make()
    monkeypatch.setattr(staging.module.pixel_codecs, "MAX_ENCODED_BYTES", 8)
    with pytest.raises(staging.module.BridgeError, match="budget"):
        encode(item)
    assert item.bytes == item.stage.stat().st_size == 0
    assert item.cleanup()["staging_cleanup"] == "removed"


def test_replaced_staging_is_neither_deleted_nor_published(staging):
    item = staging.make()
    encode(item)
    original = item.stage.with_suffix(".owned")
    item.stage.rename(original)
    item.stage.write_bytes(b"not ours")
    with pytest.raises(staging.module.BridgeError, match="identity"):
        item.publish()
    proof = item.cleanup()
    assert proof["staging_cleanup"] == "retained_identity_or_location_changed"
    assert item.stage.read_bytes() == b"not ours" and original.exists() and not item.path.exists()


def test_corrupt_stream_rejected_by_complete_hash_even_with_restored_stat(staging):
    item = staging.make()
    # Complete encode but intervene before its streaming seal proof.
    work = item.encode_steps(array("f", [.2, .4, .6, 1.]), 1, 1)
    for progress in work:
        if progress["phase"] == "encoding" and item.stage.read_bytes().endswith(b"IEND\xaeB`\x82"):
            break
    previous = item.stage.stat()
    with item.stage.open("r+b") as stream:
        stream.write(b"x")
    os.utime(item.stage, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    with pytest.raises(staging.module.BridgeError, match="hash"):
        list(work)
    assert not item.sealed and not item.path.exists()


def test_complete_published_hash_verification_is_bounded_and_detects_late_corruption(staging, monkeypatch):
    item = staging.make()
    encode(item)
    item.publish()
    monkeypatch.setattr(staging.module, "READ_BYTES", 8)
    progress = list(item.verify_published_steps())
    assert len(progress) > 1 and all(0 < row["completed"] <= item.bytes for row in progress)
    assert all(b["completed"]-a["completed"] <= 8 for a, b in pairwise(progress))
    # Mutating either hard-link changes the same inode; no independent backup is claimed.
    with item.path.open("r+b") as stream:
        stream.write(b"x")
    with pytest.raises(staging.module.BridgeError, match="identity"):
        list(item.verify_published_steps())
    assert not item.published_verified


def test_changed_approved_root_prevents_publication_and_unlink(staging, tmp_path):
    item = staging.make()
    encode(item)
    other = tmp_path / "other"
    other.mkdir()
    staging.root[0] = str(other)
    with pytest.raises(staging.module.BridgeError):
        item.publish()
    assert item.cleanup()["staging_cleanup"] == "retained_permission_denied"
    assert item.stage.exists() and not item.path.exists()


def test_changed_approved_root_stops_before_next_streaming_read(staging, monkeypatch):
    item = staging.make()
    encode(item)
    item.publish()
    monkeypatch.setattr(staging.module, "READ_BYTES", 8)
    work = item.verify_published_steps()
    assert next(work)["completed"] == 8
    staging.root[0] = ""
    # Without a per-slice location check this would yield another unauthorized
    # block, and notice the changed folder only at the end of the whole proof.
    with pytest.raises(staging.module.BridgeError) as error:
        next(work)
    assert error.value.code == "PERMISSION_DENIED" and not item.published_verified
    assert item.cleanup()["staging_cleanup"] == "retained_permission_denied"
    assert item.path.exists() and item.stage.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory pin semantics")
def test_windows_pins_parent_against_rename_then_releases_handles(staging, tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    item = staging.make("child/texture.png")
    encode(item)
    with pytest.raises(OSError):
        child.rename(tmp_path / "renamed")
    item.cleanup()
    renamed = child.rename(tmp_path / "renamed")
    assert renamed.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="Unprivileged POSIX symlink fixture")
def test_symlink_output_and_ancestry_fail_closed(staging, tmp_path):
    target = tmp_path / "texture.png"
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(staging.module.BridgeError, match="already exists"):
        encode(staging.make())
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(staging.module.BridgeError, match="links"):
        encode(staging.make("linked/child.png"))


def test_resource_cannot_encode_publish_or_clean_from_another_thread(staging):
    item = staging.make()
    errors = []

    def worker():
        for call in (lambda: encode(item), item.publish, item.cleanup):
            try:
                call()
            except staging.module.BridgeError as exc:
                errors.append(exc.code)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)
    assert not thread.is_alive() and errors == ["BLENDER_CONTEXT_ERROR"]*3
    assert item.stage is None


@pytest.mark.parametrize("failure", ["create", "open", "sync", "write", "short_write", "partial_write"])
def test_io_failures_cannot_publish_and_release_only_owned_resources(staging, monkeypatch, failure):
    item = staging.make()

    def fail(*_args, **_kwargs):
        raise OSError("injected disk failure")

    if failure == "create":
        monkeypatch.setattr(staging.module.tempfile, "mkstemp", fail)
    elif failure == "open":
        monkeypatch.setattr(staging.module.os, "fdopen", fail)
    elif failure == "sync":
        monkeypatch.setattr(staging.module.os, "fsync", fail)
    else:
        fdopen = staging.module.os.fdopen

        def wrapped(*args, **kwargs):
            stream = fdopen(*args, **kwargs)
            def partial(data):
                stream.write(data[:1])
                raise OSError("write failed after partial external IO")
            return NS(fileno=stream.fileno, close=stream.close,
                      write=fail if failure == "write" else partial if failure == "partial_write" else lambda data: stream.write(data[:1]))

        monkeypatch.setattr(staging.module.os, "fdopen", wrapped)
    with pytest.raises((OSError, staging.module.BridgeError)):
        encode(item)
    assert not item.published and not item.path.exists()
    if failure in {"short_write", "partial_write"}:
        assert item.evidence()["file_bytes"] == 1
        assert item.evidence()["encoded_bytes_hashed"] == 0
        assert item.evidence()["file_sha256"] is None
    proof = item.cleanup()
    assert proof["staging_cleanup"] == ("not_created" if failure == "create" else "removed")
    assert item.pins is None or item.pins.handles == []


def test_failed_encode_cannot_reuse_or_leak_its_directory_pins(staging, monkeypatch):
    item = staging.make()
    monkeypatch.setattr(staging.module.tempfile, "mkstemp", lambda **_k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        encode(item)
    pins = item.pins
    with pytest.raises(staging.module.BridgeError, match="once"):
        encode(item)
    assert item.pins is pins
    item.cleanup()
    assert pins.handles == []


def test_publication_and_encoding_are_one_shot(staging):
    item = staging.make()
    encode(item)
    with pytest.raises(staging.module.BridgeError, match="once"):
        encode(item)
    item.publish()
    with pytest.raises(staging.module.BridgeError, match="unpublished"):
        item.publish()
    assert item.path.exists()


def test_cleanup_permission_does_not_imply_arbitrary_scene_deletion(staging):
    staging.grants["DELETE_OBJECTS"] = False
    item = staging.make()
    encode(item)
    assert item.cleanup()["staging_cleanup"] == "removed"
    assert not item.path.exists()


@pytest.mark.parametrize("phase", ["create", "publish"])
def test_lifecycle_callback_cannot_revoke_grant_then_allow_external_io(staging, phase):
    item = staging.make()
    if phase == "publish":
        encode(item)
    staging.context.check_cancelled = lambda: staging.grants.update(SAVE_PROJECT=False)
    with pytest.raises(staging.module.BridgeError) as error:
        item.publish() if phase == "publish" else encode(item)
    assert error.value.code == "PERMISSION_DENIED" and not item.published
    assert not item.publication_attempted
    assert item.stage is None if phase == "create" else not item.path.exists()
