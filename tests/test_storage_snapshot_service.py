"""Private service ownership models; no shipping or native qualification."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_storage_snapshot as snapshot_models


@pytest.fixture
def service_env(addon_package, tmp_path, monkeypatch):
    observation = snapshot_models.observation.__wrapped__(addon_package, tmp_path, monkeypatch)
    module = importlib.import_module(addon_package + ".storage_snapshot_service")
    owner = object()
    service = module.StorageSnapshotService(owner)
    root = tmp_path / "approved"
    root.mkdir()
    scratch = root / "scratch"
    scratch.mkdir()
    calls, hook = [], [None]
    def check():
        # Trusted PURE control gate model. Actual preference/source admission
        # and proof of a caller-supplied gate remain integration prerequisites.
        calls.append("gate")
        observation.module._cleanup_control(observation.context)
        if hook[0] is not None:
            hook[0]()
        observation.module._cleanup_control(observation.context)
    return SimpleNamespace(module=module, owner=owner, service=service, root=root, scratch=scratch,
                           check=check, calls=calls, hook=hook, observation=observation)


def reserve(env, capacity=1):
    # Authorization is outside the service's PURE per-filesystem gate.
    env.observation.context.require(*env.observation.module.REQUIRED)
    return env.service.reserve(env.owner, str(env.root), "scratch", capacity, check=env.check)


def operation(env, identifier):
    native = env.observation
    return env.service.operation(env.owner, identifier, native.context, native.bpy, native.scenes,
                                 approved_root=str(env.root), check=env.check)


def fresh_context(env, addon_package):
    registry = importlib.import_module(addon_package + ".tool_registry")
    old = env.observation.context
    context = registry.ToolContext(old.state, old.permissions, old.registry, old.checkpoints)
    context.checkpoint_method = old.checkpoint_method
    return context


def test_constructor_is_filesystem_free_and_owner_identity_is_not_authority(addon_package, monkeypatch):
    module = importlib.import_module(addon_package + ".storage_snapshot_service")
    def forbidden(*_args, **_kwargs):
        pytest.fail("Constructor touched the filesystem")
    monkeypatch.setattr(module.os, "open", forbidden)
    monkeypatch.setattr(module.os, "mkdir", forbidden)
    monkeypatch.setattr(module.os, "lstat", forbidden)
    owner = object()
    service = module.StorageSnapshotService(owner)
    assert service.receipts(owner) == ()
    with pytest.raises(module.BridgeError):
        service.receipts(object())


def test_reservation_creates_only_private_namespace_and_immutable_journal_budget(service_env):
    env = service_env
    identifier = reserve(env, 3)
    value = env.service.receipt(env.owner, identifier)
    assert len(identifier) == 32 and value["capacity"] == 3 and value["attempts"] == 0
    assert value["namespace_ready"] and value["namespace_created"]
    assert value["journal"]["capacity"] == 3 and value["journal"]["snapshots"] == []
    assert Path(value["namespace"]).parent == env.scratch
    assert Path(value["namespace"]).stat().st_mode & 0o777 == 0o700
    assert list(env.scratch.iterdir()) == [Path(value["namespace"])]
    assert not value["shipping_caller_qualified"] and not value["durable_backup_qualified"]


@pytest.mark.parametrize("capacity", (True, False, 0, -1, 257, 1.0, "1", None))
def test_capacity_refuses_before_gate_or_filesystem(service_env, capacity):
    env = service_env
    with pytest.raises(env.module.BridgeError):
        reserve(env, capacity)
    assert env.calls == [] and list(env.scratch.iterdir()) == []


def test_service_total_is_qualified_256_cells_and_never_refunded(service_env):
    env = service_env
    first, second = reserve(env, 128), reserve(env, 128)
    assert first != second and env.module.MAX_SERVICE_SNAPSHOTS == env.observation.effects.MAX_SNAPSHOTS == 256
    before = len(env.calls)
    with pytest.raises(env.module.BridgeError):
        reserve(env)
    assert len(env.calls) == before
    assert [row["capacity"] for row in env.service.receipts(env.owner)] == [128, 128]
    assert env.service._receipts[first].journal is not env.service._receipts[second].journal


@pytest.mark.parametrize("root,subdirectory", (("/", "scratch"), ("//tmp", "scratch"), ("relative", "scratch"),
    ("ROOT", "../scratch"), ("ROOT", "./scratch"), ("ROOT", "/scratch"), ("ROOT", "scratch/"),
    ("ROOT", "scratch//nested"), ("ROOT", ""), ("ROOT", "scratch\\nested")))
def test_exact_path_policy_refuses_before_gate(service_env, root, subdirectory):
    env = service_env
    root = str(env.root) if root == "ROOT" else root
    with pytest.raises(env.module.BridgeError):
        env.service.reserve(env.owner, root, subdirectory, 1, check=env.check)
    assert env.calls == [] and list(env.scratch.iterdir()) == []


def test_existing_scratch_symlink_is_not_traversed(service_env, tmp_path):
    env = service_env
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (env.root / "alias").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(env.module.BridgeError):
        env.service.reserve(env.owner, str(env.root), "alias", 1, check=env.check)
    assert list(foreign.iterdir()) == [] and env.service.receipts(env.owner) == ()


def test_preexisting_namespace_is_never_adopted_or_removed(service_env):
    env = service_env
    namespace = env.scratch / env.service._leaf
    namespace.mkdir(mode=0o700)
    sentinel = namespace / "foreign"
    sentinel.write_bytes(b"retain")
    with pytest.raises(FileExistsError):
        reserve(env)
    row, = env.service.receipts(env.owner)
    assert not row["namespace_created"] and not row["namespace_ready"]
    assert row["capacity"] == 1 and sentinel.read_bytes() == b"retain"
    with pytest.raises(env.module.BridgeError):
        reserve(env)
    assert sentinel.read_bytes() == b"retain"


def test_postmkdir_gate_failure_retains_discoverable_unknown_namespace(service_env):
    env = service_env
    primary = RuntimeError("postmkdir original denial")
    def stop_after_create():
        if env.service._created:
            raise primary
    env.hook[0] = stop_after_create
    with pytest.raises(RuntimeError) as caught:
        reserve(env, 2)
    assert caught.value is primary
    env.hook[0] = None
    row, = env.service.receipts(env.owner)
    assert row["namespace_created"] and not row["namespace_ready"]
    assert Path(row["namespace"]).is_dir() and row["capacity"] == 2
    assert env.service._binding is None
    with pytest.raises(env.module.BridgeError):
        operation(env, row["receipt_id"])


def test_close_failure_does_not_mask_primary_postmkdir_gate(service_env, monkeypatch):
    env = service_env
    primary = RuntimeError("primary postmkdir")
    env.hook[0] = lambda: (_ for _ in ()).throw(primary) if env.service._created else None
    original = env.module.os.close
    def close(descriptor):
        original(descriptor)
        raise OSError("secondary close")
    monkeypatch.setattr(env.module.os, "close", close)
    with pytest.raises(RuntimeError) as caught:
        reserve(env)
    assert caught.value is primary
    row, = env.service.receipts(env.owner)
    assert row["descriptor_close_failed"] and not row["namespace_ready"]


@pytest.mark.parametrize("identifier", ("a" * 32, "../foreign", True, None))
def test_foreign_or_restarted_receipt_refuses_before_gate(service_env, identifier):
    env = service_env
    with pytest.raises(env.module.BridgeError):
        env.service.cleanup(env.owner, identifier, env.observation.context,
                            approved_root=str(env.root), check=env.check)
    assert env.calls == []


def test_restart_and_wrong_owner_do_not_adopt_receipts(service_env):
    env = service_env
    identifier = reserve(env)
    replacement = env.module.StorageSnapshotService(env.owner)
    before = len(env.calls)
    with pytest.raises(env.module.BridgeError):
        replacement.cleanup(env.owner, identifier, env.observation.context, approved_root=str(env.root), check=env.check)
    with pytest.raises(env.module.BridgeError):
        env.service.cleanup(object(), identifier, env.observation.context, approved_root=str(env.root), check=env.check)
    assert len(env.calls) == before


def test_constructor_failure_consumes_attempt_without_losing_journal(service_env, monkeypatch):
    env = service_env
    identifier = reserve(env)
    journal = env.service._receipts[identifier].journal
    primary = RuntimeError("original source capture refusal")
    def failed(*_args):
        raise primary
    monkeypatch.setattr(env.module, "SnapshotOperation", failed)
    with pytest.raises(RuntimeError) as caught:
        operation(env, identifier)
    assert caught.value is primary
    assert env.service._receipts[identifier].journal is journal
    assert env.service.receipt(env.owner, identifier)["attempts"] == 1
    with pytest.raises(env.module.BridgeError):
        operation(env, identifier)


def test_known_file_fresh_request_cleanup_uses_latest_original_journal_owner(service_env, addon_package):
    env = service_env
    identifier = reserve(env)
    value = operation(env, identifier)
    witness = value.run()
    assert len(witness.consume(env.observation.context, env.observation.bpy, env.observation.scenes)) == 2
    before = env.service.receipt(env.owner, identifier)
    row, = before["original_owners"]
    assert row["original_file_identity_known"] and not row["complete"]
    native = Path(before["journal"]["snapshots"][0]["filepath"])
    context = fresh_context(env, addon_package)
    assert context is not value.context
    result = env.service.cleanup(env.owner, identifier, context, approved_root=str(env.root), check=env.check)
    assert result["original_owners"][0]["complete"] and not native.exists()
    assert Path(result["namespace"]).is_dir() and result["attempts"] == 1
    with pytest.raises(env.module.BridgeError):
        operation(env, identifier)


def test_unknown_postwriter_file_is_retained_without_adoption(service_env, addon_package):
    env = service_env
    identifier = reserve(env)
    value = operation(env, identifier)
    primary = RuntimeError("writer failed after partial file")
    def partial():
        raise primary
    env.observation.writer_hook[0] = partial
    with pytest.raises(RuntimeError) as caught:
        value.run()
    assert caught.value is primary
    result = env.service.cleanup(env.owner, identifier, fresh_context(env, addon_package),
                                 approved_root=str(env.root), check=env.check)
    row, = result["original_owners"]
    assert row["retained_unknown"] and not row["original_file_identity_known"] and not row["complete"]
    assert Path(result["journal"]["snapshots"][0]["filepath"]).read_bytes() == b"owned native gateway model bytes"


def test_denial_before_namespace_has_no_receipt_or_filesystem_effect(service_env):
    env = service_env
    env.observation.grants["SAVE_PROJECT"] = False
    with pytest.raises(env.module.BridgeError) as denied:
        reserve(env)
    assert denied.value.code == "PERMISSION_DENIED"
    assert env.service.receipts(env.owner) == () and list(env.scratch.iterdir()) == []


def test_approval_or_namespace_replacement_never_rebinds_cleanup(service_env, tmp_path):
    env = service_env
    identifier = reserve(env)
    root = Path(env.service.receipt(env.owner, identifier)["namespace"])
    moved = tmp_path / "original"
    root.rename(moved)
    root.mkdir(mode=0o700)
    before = env.service._binding
    with pytest.raises(env.module.BridgeError):
        env.service.cleanup(env.owner, identifier, env.observation.context, approved_root=str(env.root), check=env.check)
    assert env.service._binding is before and moved.is_dir() and root.is_dir()


def test_cached_receipt_never_inspects_filesystem_or_provider(service_env, monkeypatch):
    env = service_env
    identifier = reserve(env)
    before = len(env.calls)
    def forbidden(*_args, **_kwargs):
        pytest.fail("Cached receipt inspected a live dependency")
    monkeypatch.setattr(env.module.os, "lstat", forbidden)
    monkeypatch.setattr(env.module.os, "stat", forbidden)
    env.observation.provider_hook[0] = forbidden
    row = env.service.receipt(env.owner, identifier)
    assert len(env.calls) == before and row["receipt_id"] == identifier
    row["journal"]["capacity"] = 999
    assert env.service.receipt(env.owner, identifier)["journal"]["capacity"] == 1


def test_gate_failure_after_filesystem_return_prevents_followup_read(service_env, monkeypatch):
    env = service_env
    original = Path.lstat
    calls = []
    primary = RuntimeError("source invalidated after lstat")
    def observed(path):
        result = original(path)
        calls.append(str(path))
        env.hook[0] = lambda: (_ for _ in ()).throw(primary)
        return result
    monkeypatch.setattr(Path, "lstat", observed)
    with pytest.raises(RuntimeError) as caught:
        reserve(env)
    assert caught.value is primary and calls == [os.path.sep]


def test_gate_drift_cannot_create_through_stale_parent_fd(service_env, monkeypatch):
    """A drifting callback is outside the PURE contract; final CAS still refuses."""
    env = service_env
    original, armed = env.module.os.fstat, [False]
    moved = env.root.parent / "moved-outside-approval"
    def drift():
        env.hook[0] = None
        env.scratch.rename(moved)
        env.scratch.mkdir()
    def observed(descriptor):
        result = original(descriptor)
        if not armed[0]:
            armed[0] = True
            env.hook[0] = drift
        return result
    monkeypatch.setattr(env.module.os, "fstat", observed)
    with pytest.raises(env.module.BridgeError):
        reserve(env)
    assert list(moved.iterdir()) == list(env.scratch.iterdir()) == []
    row, = env.service.receipts(env.owner)
    assert not row["namespace_created"] and not row["namespace_ready"]
