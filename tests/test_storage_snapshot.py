"""Owned file/control countermodels; the substituted native gateway is a model.

These tests do not qualify Blender's C writer or the native RNA declarations.
The exact native adapter and its future cache pairing still require the isolated
runner. No production flag, provider or callback exemption is introduced here.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def observation(addon_package, tmp_path, monkeypatch):
    module = importlib.import_module(addon_package + ".storage_snapshot")
    effects = importlib.import_module(addon_package + ".storage_snapshot_effects")
    registry = importlib.import_module(addon_package + ".tool_registry")
    state = importlib.import_module(addon_package + ".state")
    permissions = importlib.import_module(addon_package + ".permissions")
    calls, provider_hook, writer_hook, parser_hook = [], [None], [None], [None]
    grants = {item.value: True for item in permissions.Permission}

    def provider():
        calls.append("provider")
        if provider_hook[0] is not None:
            provider_hook[0]()
        return grants

    context = registry.ToolContext(state.BridgeState(), permissions.PermissionManager(provider), registry.ToolRegistry(), None)
    method = "simulation.cache_preview"
    context.registry.register(method, lambda *_: None, modifies=True, permissions=module.REQUIRED)
    context.checkpoint_method = method
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    scenes, bpy, changed = (object(), object()), object(), [False]
    targets = (((11, 21, "Home"), (31, "Home Layer"), 1, 0..hex()),
               ((12, 22, "Target"), (32, "Target Layer"), 1, 0..hex()))

    class NativeModel:
        __slots__ = ("baseline", "bpy", "build", "libraries", "main", "scenes", "writer")

        def __init__(self, current_bpy, current_scenes):
            assert current_bpy is bpy and current_scenes is scenes
            calls.append("native_bind")
            self.bpy, self.scenes = current_bpy, current_scenes
            self.build = ("62c1db4208e8", (4, 5, 14), "USER")
            self.libraries, self.main = object(), object()
            self.baseline = (self.build, 10, "", True, (), targets)

            def writer(path, blocks, *, path_remap, fake_user, compress):
                assert blocks == set(scenes) and (path_remap, fake_user, compress) == ("NONE", False, False)
                calls.append("native_write")
                Path(path).write_bytes(b"owned native gateway model bytes")
                if writer_hook[0] is not None:
                    writer_hook[0]()
            self.writer = writer

        def check(self):
            calls.append("native_identity")
            if changed[0]:
                raise module.refused("SNAPSHOT_SOURCE_IDENTITY_CHANGED")

    def parser(path, scene, layer, *, allowed_names):
        calls.append("parser")
        assert (scene, layer) in {(target[0][2], target[1][1]) for target in targets}
        info, raw = os.stat(path), Path(path).read_bytes()
        children = [{"name": name, "type": 10, "subtype": 0, "flag": 2, "len": 1, "totallen": 0,
                     "value": index % 2, "value2": 0} for index, name in enumerate(allowed_names)]
        header = {"name": "cycles", "type": 6, "subtype": 0, "flag": 2, "len": len(children), "totallen": 0}
        value = {"schema": "blend_view_layer_raw_storage_v1", "file_identity": list(module._file_identity(info)),
                 "file_sha256": hashlib.sha256(raw).hexdigest(), "storage_fingerprint": "a" * 64,
                 "storage": {"scene_name": scene, "view_layer_name": layer, "property_name": "cycles",
                             "storage": "USER", "state": "GROUP", "root_present": True,
                             "root_header": {**header, "name": "root", "len": 1}, "property": header,
                             "children": children}}
        if parser_hook[0] is not None:
            parser_hook[0](value)
        return value

    # Substitute at the trusted model setup boundary, before capturing source;
    # lifecycle tests exercise real permission/source/journal/filesystem code.
    monkeypatch.setattr(module, "_NativeSource", NativeModel)
    monkeypatch.setattr(module, "inspect_view_layer_storage", parser)
    monkeypatch.setattr(module, "available_memory_facts", lambda: {"available_memory_bytes": 12 * 1024**3})
    return SimpleNamespace(module=module, effects=effects, context=context, root=root, scenes=scenes, bpy=bpy,
                           calls=calls, grants=grants, provider_hook=provider_hook, writer_hook=writer_hook,
                           parser_hook=parser_hook, changed=changed)


def operation(observation):
    env = observation
    journal = env.effects.SnapshotJournal(2)
    value = env.module.SnapshotOperation(env.context, env.bpy, env.scenes, str(env.root), journal)
    return value, journal


def test_success_keeps_complete_typed_raw_values_and_owned_files(observation):
    env = observation
    value, journal = operation(env)
    witness = value.run()
    rows = witness.consume(env.context, env.bpy, env.scenes)
    assert len(rows) == 2
    assert rows[0].scene == (11, 21, "Home") and rows[1].layer == (32, "Target Layer")
    assert [row[0] for row in rows[0].children] == list(env.module.CYCLES_NAMES)
    assert [row[-2] for row in rows[0].children] == [0, 1, 0, 1, 0, 1]
    assert env.calls.count("provider") == 2 and env.calls.count("native_write") == 1 and env.calls.count("parser") == 2
    receipt = journal.snapshot()["snapshots"][0]
    assert receipt["native_returned"] and receipt["identity_verified"] and receipt["consumed"]
    assert receipt["retained_file_possible"] and Path(receipt["filepath"]).read_bytes() == b"owned native gateway model bytes"
    assert Path(receipt["directory"]).stat().st_mode & 0o777 == 0o700
    assert receipt["cleanup_entered"] is False
    assert journal.snapshot()["runtime_retention_qualified"] is False


def cleanup_ready(env):
    value, journal = operation(env)
    witness = value.run()
    return value, journal, witness, value.cleanup_owner


@contextmanager
def cleanup_fs_events(env, actor=None):
    """Observe original real OS calls; never substitute the filesystem API."""
    previous = sys.getprofile()
    assert previous is None
    known = {id(function): name for name, function in env.module._CLEANUP_OS_ORIGINS}
    calls = []
    def profile(frame, event, function):
        name = known.get(id(function))
        if event in {"c_call", "c_return", "c_exception"} and name is not None and frame.f_code.co_filename == env.module.__file__:
            calls.append((event, name))
            if actor is not None:
                actor(event, name)
    sys.setprofile(profile)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


def test_cleanup_removes_only_original_file_and_child_preserving_receipts_and_root(observation):
    env = observation
    value, journal = operation(env)
    witness = value.run()
    owner = value.cleanup_owner
    witness.consume(env.context, env.bpy, env.scenes)
    before = journal.snapshot()["snapshots"][0]
    env.calls.clear()
    result = env.module.cleanup_step(env.context, journal, owner)
    assert result["complete"] and result["unlink_returned"] and result["rmdir_returned"]
    assert env.root.is_dir() and list(env.root.iterdir()) == []
    assert env.calls and set(env.calls) == {"provider"}
    after = journal.snapshot()["snapshots"][0]
    assert after["cleanup_entered"] and after["cleanup_returned"] and not after["retained_file_possible"]
    for name in ("root", "directory", "filepath", "file_identity", "file_sha256", "file_bytes"):
        assert after[name] == before[name]
    assert not result["durable_backup_qualified"] and not result["runtime_retention_qualified"]
    env.calls.clear()
    assert env.module.cleanup_step(env.context, journal, owner) == result
    assert env.calls == []


def test_cleanup_retires_an_unused_witness_before_its_native_check(observation):
    env = observation
    value, journal = operation(env)
    witness = value.run()
    owner = value.cleanup_owner
    assert env.module.cleanup_step(env.context, journal, owner)["complete"]
    env.calls.clear()
    with pytest.raises(env.module.BridgeError) as failure:
        witness.consume(env.context, env.bpy, env.scenes)
    assert failure.value.context["reason"] == "SNAPSHOT_WITNESS_RETIRED"
    assert env.calls == []


@pytest.mark.parametrize("permission", ["INSPECT_SCENE", "SAVE_PROJECT", "ACCESS_EXTERNAL_FILES"])
def test_cleanup_initial_denial_does_no_filesystem_work_or_retirement(observation, monkeypatch, permission):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    env.grants[permission] = False
    env.calls.clear()
    with cleanup_fs_events(env) as fs, pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert fs == [] and env.calls == ["provider"]
    assert not journal.snapshot()["snapshots"][0]["cleanup_entered"]


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_cleanup_stopped_context_does_not_call_provider_or_filesystem(observation, monkeypatch, flag):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    setattr(env.context.state, flag, True)
    env.calls.clear()
    with cleanup_fs_events(env) as fs, pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert fs == env.calls == []


@pytest.mark.parametrize("target", ["root", "child", "file", "symlink", "hardlink", "mode", "bytes", "extra"])
def test_cleanup_refuses_changed_filesystem_binding_preserving_foreign_sentinels(observation, target):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    row = journal.snapshot()["snapshots"][0]
    directory, native = Path(row["directory"]), Path(row["filepath"])
    sentinel = env.root.parent / "foreign.blend"
    sentinel.write_bytes(b"FOREIGN SENTINEL")
    if target == "root":
        env.root.rename(env.root.with_name("original-root"))
        env.root.mkdir(mode=0o700)
    elif target == "child":
        directory.rename(directory.with_name("original-child"))
        directory.mkdir(mode=0o700)
    elif target == "file":
        native.rename(native.with_name("original.blend"))
        native.write_bytes(b"FOREIGN REPLACEMENT")
    elif target == "symlink":
        native.unlink()
        native.symlink_to(sentinel)
    elif target == "hardlink":
        os.link(native, env.root.parent / "another-link")
    elif target == "mode":
        native.chmod(0o600 if native.stat().st_mode & 0o777 != 0o600 else 0o644)
    elif target == "bytes":
        native.write_bytes(b"CHANGED")
    else:
        (directory / "foreign-entry").write_bytes(b"EXTRA")
    with pytest.raises((env.module.BridgeError, OSError)):
        env.module.cleanup_step(env.context, journal, owner)
    assert sentinel.read_bytes() == b"FOREIGN SENTINEL"
    assert not env.effects.cleanup_receipt(journal, owner)["complete"]
    if target in {"symlink", "hardlink", "file", "mode", "bytes", "extra"}:
        assert os.path.lexists(native)


def test_cleanup_provider_cannot_redirect_mutable_receipt_or_private_owner(observation):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    original = Path(journal.snapshot()["snapshots"][0]["filepath"])
    def redirect():
        env.provider_hook[0] = None
        journal.rows[0].filepath = str(env.root.parent / "foreign.blend")
    env.provider_hook[0] = redirect
    with pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert original.is_file()
    assert not journal.rows[0].cleanup_entered


@pytest.mark.parametrize("tamper", ["forged_owner", "wrong_journal", "owner_cell", "source", "foreign_receipt"])
def test_cleanup_authority_cannot_be_forged_or_switched_by_provider(observation, monkeypatch, tamper):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    native = Path(journal.snapshot()["snapshots"][0]["filepath"])
    callbacks = []
    class Foreign:
        def __eq__(self, other):
            callbacks.append("equality")
            raise AssertionError("Foreign equality")
    if tamper == "forged_owner":
        owner = tuple.__new__(env.effects.SnapshotOwner, tuple(owner))
    elif tamper == "wrong_journal":
        journal = env.effects.SnapshotJournal(2)
    else:
        def change():
            env.provider_hook[0] = None
            if tamper == "owner_cell":
                _owners, state, slots = env.effects.cleanup_state(journal, journal.rows[0])
                dict(slots)["owner"].__set__(state, tuple(owner))
            elif tamper == "foreign_receipt":
                journal.rows[0].root_identity = (Foreign(), 1)
            else:
                monkeypatch.setattr(env.module, "_directory_cleanup_binding", lambda *_: callbacks.append("foreign"))
        env.provider_hook[0] = change
    with pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert callbacks == [] and native.is_file()


def test_cleanup_uses_full_ctime_fact_when_size_and_mtime_are_restored(observation):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    native = Path(journal.snapshot()["snapshots"][0]["filepath"])
    before = native.stat()
    native.write_bytes(native.read_bytes())
    os.utime(native, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert native.stat().st_mtime_ns == before.st_mtime_ns
    assert native.stat().st_ctime_ns != before.st_ctime_ns
    with pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert native.is_file()


def test_cleanup_refuses_foreign_uid_metadata_without_deletion(observation):
    env = observation
    _value, journal, _witness, _owner = cleanup_ready(env)
    native = Path(journal.snapshot()["snapshots"][0]["filepath"])
    info = native.stat()
    with pytest.raises(env.module.BridgeError):
        env.module._file_cleanup_binding(SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid + 1, st_nlink=1))
    assert native.is_file()


def test_cleanup_rejects_replaced_filesystem_api_before_provider_or_foreign_dispatch(observation, monkeypatch):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    calls = []
    env.calls.clear()
    monkeypatch.setattr(os, "scandir", lambda *_: calls.append("foreign"))
    with pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert calls == env.calls == []


def test_cleanup_close_failure_does_not_claim_complete_or_skip_other_held_closes(observation):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    previous, leaked, callbacks = sys.getprofile(), [], []
    assert previous is None
    class CloseError(OSError):
        def __bool__(self):
            callbacks.append("foreign bool")
            raise AssertionError("Do not test exception truthiness")
    def profile(frame, event, function):
        if event == "c_call" and function is os.close and frame.f_code is env.module.cleanup_step.__code__ and not leaked:
            leaked.append(frame.f_locals["descriptor"])
            raise CloseError("injected held descriptor close failure")
    sys.setprofile(profile)
    try:
        with pytest.raises(OSError):
            env.module.cleanup_step(env.context, journal, owner)
    finally:
        sys.setprofile(previous)
        for descriptor in leaked:
            os.close(descriptor)
    receipt = env.effects.cleanup_receipt(journal, owner)
    assert receipt["rmdir_returned"] and receipt["close_failed"] and not receipt["complete"]
    assert list(env.root.iterdir()) == [] and callbacks == []


def test_cleanup_memory_failure_after_open_keeps_fd_in_preallocated_close_slots(observation, monkeypatch):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    original_control, opened, closed = env.module._cleanup_control, [], []
    def control(context):
        original_control(context)
        if opened:
            env.calls.clear()
            raise MemoryError("owned post-open control model")
    monkeypatch.setattr(env.module, "_cleanup_control", control)
    previous = sys.getprofile()
    assert previous is None
    def profile(frame, event, function):
        if event == "c_return" and function is os.open and frame.f_code.co_filename == env.module.__file__:
            opened.append(True)
        if event == "c_return" and function is os.close and frame.f_code is env.module.cleanup_step.__code__:
            closed.append(frame.f_locals["descriptor"])
    sys.setprofile(profile)
    try:
        with pytest.raises(MemoryError):
            env.module.cleanup_step(env.context, journal, owner)
    finally:
        sys.setprofile(previous)
    assert opened == [True] and len(closed) == 1 and env.calls == []
    with pytest.raises(OSError):
        os.fstat(closed[0])
    assert not env.effects.cleanup_receipt(journal, owner)["unlink_entered"]


def test_cleanup_private_root_with_spaces_uses_original_sealed_names(observation):
    env = observation
    env.root = env.root.with_name("private snapshots with spaces")
    env.root.mkdir(mode=0o700)
    _value, journal, _witness, owner = cleanup_ready(env)
    assert env.module.cleanup_step(env.context, journal, owner)["complete"]
    assert env.root.is_dir() and list(env.root.iterdir()) == []


@pytest.mark.parametrize("same_inode", [True, False])
def test_cleanup_ancestor_alias_cannot_redirect_original_physical_root_authority(observation, same_inode):
    env = observation
    parent = env.root.parent / "anchored-parent"
    parent.mkdir(mode=0o700)
    env.root = parent / "private"
    env.root.mkdir(mode=0o700)
    _value, journal, _witness, owner = cleanup_ready(env)
    leaf = tuple.__getitem__(owner, 3)
    physical = parent.with_name("original-physical-parent")
    parent.rename(physical)
    sentinel = physical / "foreign.blend"
    sentinel.write_bytes(b"ORIGINAL PARENT SENTINEL")
    foreign = parent.with_name("foreign-parent")
    foreign.mkdir(mode=0o700)
    (foreign / "private").mkdir(mode=0o700)
    other = foreign / "private" / "foreign.blend"
    other.write_bytes(b"FOREIGN ROOT SENTINEL")
    parent.symlink_to(physical if same_inode else foreign, target_is_directory=True)
    if same_inode:
        assert env.module.cleanup_step(env.context, journal, owner)["complete"]
        assert not (physical / "private" / leaf).exists()
    else:
        with pytest.raises(env.module.BridgeError):
            env.module.cleanup_step(env.context, journal, owner)
        assert (physical / "private" / leaf / "snapshot.blend").is_file()
    assert parent.is_symlink() and (physical / "private").is_dir()
    assert sentinel.read_bytes() == b"ORIGINAL PARENT SENTINEL"
    assert other.read_bytes() == b"FOREIGN ROOT SENTINEL"


@pytest.mark.parametrize("boundary", ["open", "lstat", "fstat", "scandir", "stat"])
def test_cleanup_stop_after_first_filesystem_return_prevents_later_inspection_or_provider(observation, boundary):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    stopped = []
    def stop(event, name):
        if event == "c_return" and name == boundary and not stopped:
            env.context.state.paused = True
            env.calls.clear()
            stopped.append(True)
    with cleanup_fs_events(env, stop) as calls, pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert stopped == [True] and env.calls == []
    boundary_index = calls.index(("c_return", boundary))
    assert all(name == "close" for _event, name in calls[boundary_index + 1:])
    assert not env.effects.cleanup_receipt(journal, owner)["unlink_entered"]


def test_cleanup_opaque_tuple_methods_are_never_virtual_dispatch(observation, monkeypatch):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    calls = []
    monkeypatch.setattr(env.effects.SnapshotOwner, "__len__", lambda *_: calls.append("foreign len"), raising=False)
    assert env.effects.cleanup_receipt(journal, owner)["complete"] is False
    assert env.module.cleanup_step(env.context, journal, owner)["complete"]
    assert calls == []


def test_cleanup_rechecks_file_after_its_final_permission_provider(observation):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    native = Path(journal.snapshot()["snapshots"][0]["filepath"])
    moved, swapped = native.with_name("original-owned.blend"), []
    # Learn the final-provider boundary from the real function's own frame,
    # rather than hardcoding a count that changes when inspections are added.
    import inspect
    def swap_on_final_provider():
        frame = inspect.currentframe()
        authorize_frame = None
        while frame is not None:
            if frame.f_code.co_name == "authorize" and frame.f_code.co_filename == env.module.__file__:
                authorize_frame = frame
                break
            frame = frame.f_back
        caller = authorize_frame.f_back if authorize_frame is not None else None
        if (caller is not None and caller.f_code is env.module.cleanup_step.__code__
                and caller.f_locals.get("file_binding") is not None and "info" in caller.f_locals and not swapped):
            swapped.append(True)
            native.rename(moved)
            native.write_bytes(b"FOREIGN REPLACEMENT AT PROVIDER")
    env.provider_hook[0] = swap_on_final_provider
    with pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    assert swapped == [True]
    assert native.read_bytes() == b"FOREIGN REPLACEMENT AT PROVIDER" and moved.is_file()
    assert not env.effects.cleanup_receipt(journal, owner)["unlink_entered"]


def test_cleanup_stop_after_unlink_records_return_and_defers_all_later_work(observation):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    native = Path(journal.snapshot()["snapshots"][0]["filepath"])
    stopped = []
    def stop(event, name):
        if (event, name) == ("c_return", "unlink"):
            env.context.state.paused = True
            env.calls.clear()
            stopped.append(True)
    with cleanup_fs_events(env, stop) as calls, pytest.raises(env.module.BridgeError):
        env.module.cleanup_step(env.context, journal, owner)
    result = env.effects.cleanup_receipt(journal, owner)
    assert stopped == [True] and result["unlink_returned"] and not result["rmdir_entered"]
    boundary = calls.index(("c_return", "unlink"))
    assert all(name == "close" for _event, name in calls[boundary + 1:])
    assert env.calls == [] and not native.exists() and native.parent.is_dir()
    env.context.state.paused = False
    result = env.module.cleanup_step(env.context, journal, owner)
    assert result["complete"]


@pytest.mark.parametrize("failure", ["unlink", "rmdir"])
def test_cleanup_partial_oserror_keeps_original_owner_for_fresh_retry(observation, failure):
    env = observation
    _value, journal, _witness, owner = cleanup_ready(env)
    fired = []
    def fail(event, name):
        if event == "c_call" and name == failure and not fired:
            fired.append(True)
            raise OSError("injected owned cleanup failure")
    with cleanup_fs_events(env, fail), pytest.raises(OSError):
        env.module.cleanup_step(env.context, journal, owner)
    partial = env.effects.cleanup_receipt(journal, owner)
    assert partial["failed"] and not partial["complete"]
    assert partial["unlink_returned"] is (failure == "rmdir")
    assert env.module.cleanup_step(env.context, journal, owner)["complete"]


def test_cleanup_never_adopts_an_unknown_file_after_writer_stop(observation):
    env = observation
    value, journal = operation(env)
    env.writer_hook[0] = lambda: setattr(env.context.state, "paused", True)
    with pytest.raises(env.module.BridgeError):
        value.run()
    owner = value.cleanup_owner
    native = Path(journal.snapshot()["snapshots"][0]["filepath"])
    assert native.is_file() and tuple.__getitem__(owner, 6) is None
    env.context.state.paused = False
    result = env.module.cleanup_step(env.context, journal, owner)
    assert result["retained_unknown"] and not result["complete"] and not result["unlink_entered"]
    assert native.is_file()


def test_cleanup_removes_verified_empty_directory_without_adopting_a_file(observation):
    env = observation
    value, journal = operation(env)
    env.writer_hook[0] = None
    # The second provider can deny before the writer; the issued empty-directory
    # owner remains available for a later fresh authorization.
    def deny_second():
        if env.calls.count("provider") == 2:
            env.grants["SAVE_PROJECT"] = False
    env.provider_hook[0] = deny_second
    with pytest.raises(env.module.BridgeError):
        value.run()
    env.provider_hook[0] = None
    env.grants["SAVE_PROJECT"] = True
    result = env.module.cleanup_step(env.context, journal, value.cleanup_owner)
    assert result["complete"] and not result["unlink_entered"] and env.root.is_dir()


# Sixteen real captures and cleanups share this aggregate test budget. The
# production request/job/native limits are unchanged.
@pytest.mark.timeout(30)
def test_cleanup_sixteen_captures_keep_files_bounded_and_do_not_recycle_receipts(observation):
    env = observation
    journal = env.effects.SnapshotJournal(16)
    owners = []
    for _ in range(16):
        value = env.module.SnapshotOperation(env.context, env.bpy, env.scenes, str(env.root), journal)
        witness = value.run()
        witness.consume(env.context, env.bpy, env.scenes)
        owners.append(value.cleanup_owner)
        assert env.module.cleanup_step(env.context, journal, owners[-1])["complete"]
        assert list(env.root.iterdir()) == []
    assert len(journal.snapshot()["snapshots"]) == 16 and len({id(owner) for owner in owners}) == 16
    value = env.module.SnapshotOperation(env.context, env.bpy, env.scenes, str(env.root), journal)
    with pytest.raises(env.module.BridgeError):
        value.run()
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("permission", ["SAVE_PROJECT", "ACCESS_EXTERNAL_FILES", "INSPECT_SCENE"])
def test_initial_denial_prevents_native_inspection_and_all_file_creation(observation, permission):
    env = observation
    env.grants[permission] = False
    value, journal = operation(env)
    with pytest.raises(env.module.BridgeError) as error:
        value.run()
    assert error.value.code == "PERMISSION_DENIED"
    assert env.calls == ["provider"] and list(env.root.iterdir()) == []
    assert journal.snapshot()["snapshots"] == []


def test_second_authoritative_denial_retains_owned_directory_without_entering_c(observation):
    env = observation
    value, journal = operation(env)

    def revoke():
        if env.calls.count("provider") == 2:
            env.grants["SAVE_PROJECT"] = False
    env.provider_hook[0] = revoke
    with pytest.raises(env.module.BridgeError) as error:
        value.run()
    assert error.value.code == "PERMISSION_DENIED"
    receipt = journal.snapshot()["snapshots"][0]
    assert receipt["directory_returned"] and receipt["stopped"]
    assert receipt["native_entered"] is False and receipt["parser_entered"] is False
    assert Path(receipt["directory"]).is_dir() and list(Path(receipt["directory"]).iterdir()) == []


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_paused_or_stopped_owner_cannot_create_files_or_query_native(observation, flag):
    env = observation
    value, journal = operation(env)
    setattr(env.context.state, flag, True)
    with pytest.raises(env.module.BridgeError):
        value.run()
    assert env.calls == [] and list(env.root.iterdir()) == [] and journal.snapshot()["snapshots"] == []


@pytest.mark.parametrize("target", ["control", "verifier_binding", "verifier_code"])
def test_provider_substitution_is_refused_before_foreign_dispatch(observation, monkeypatch, target):
    env = observation
    value, _journal = operation(env)
    foreign = []
    source_kind = type(value.source)
    with monkeypatch.context() as patch:
        def replace():
            if target == "control":
                patch.setattr(env.module.SnapshotOperation, "_control", lambda *_: foreign.append("control"))
            elif target == "verifier_binding":
                patch.setattr(source_kind, "verify", lambda *_: foreign.append("verify"))
            else:
                def altered(*_):
                    raise AssertionError("Foreign verifier code must never run")
                patch.setattr(source_kind.verify, "__code__", altered.__code__)
        env.provider_hook[0] = replace
        with pytest.raises(env.module.BridgeError):
            value.run()
    assert foreign == [] and "native_write" not in env.calls and "native_bind" not in env.calls


def test_stop_during_native_write_retains_return_facts_without_later_reader_or_cleanup(observation):
    env = observation
    value, journal = operation(env)
    env.writer_hook[0] = lambda: setattr(env.context.state, "paused", True)
    with pytest.raises(env.module.BridgeError) as error:
        value.run()
    assert error.value.code == "AGENT_PAUSED"
    receipt = journal.snapshot()["snapshots"][0]
    assert receipt["native_entered"] and receipt["native_returned"] and receipt["stopped"]
    assert receipt["parser_entered"] is False and receipt["file_identity"] == []
    assert receipt["file_bytes"] is None and receipt["cleanup_entered"] is False
    assert env.calls[-1] == "native_write" and Path(receipt["filepath"]).is_file()


@pytest.mark.parametrize("field", ["context", "native_writer", "filepath", "journal_rows"])
def test_second_provider_cannot_replace_bound_owner_or_writer_fields(observation, field):
    env = observation
    value, journal = operation(env)
    foreign = []

    def replace():
        if env.calls.count("provider") != 2:
            return
        if field == "context":
            value.context = object()
        elif field == "native_writer":
            value.native.writer = lambda *_args, **_kwargs: foreign.append("writer")
        elif field == "filepath":
            value.cell.filepath = "/unrelated/source.blend"
        else:
            object.__setattr__(journal, "rows", ())
    env.provider_hook[0] = replace
    with pytest.raises(env.module.BridgeError):
        value.run()
    assert foreign == [] and "native_write" not in env.calls and "parser" not in env.calls


@pytest.mark.parametrize("mode", ["cancel", "disconnect"])
def test_actual_queued_stop_or_connection_loss_after_c_prevents_later_reads(observation, mode):
    from types import FunctionType

    env = observation
    prefix = env.module.__package__
    lifetime_module = importlib.import_module(prefix + ".request_lifecycle")
    queue = importlib.import_module(prefix + ".command_queue")
    protocol = importlib.import_module(prefix + ".protocol")
    executor = importlib.import_module(prefix + ".executor")
    connection = lifetime_module.ConnectionLifetime()
    lifetime = lifetime_module.RequestLifetime(connection)
    request = protocol.Request(id="stored-settings-stop", method=env.context.checkpoint_method, params={}, _lifecycle=lifetime)
    owner = queue.QueuedRequest(request, deadline=float("inf"))
    # A finite real queued deadline and its original executor-generated hook.
    import time
    owner.deadline = time.monotonic() + 60
    code, = [item for item in executor.MainThreadExecutor._invoke_owned.__code__.co_consts
             if getattr(item, "co_freevars", None) == ("queued_owner",)]
    cell = (lambda: owner).__closure__[0]
    env.context.request_lifecycle, env.context.request_id = lifetime, request.id
    env.context.check_cancelled = owner.check_active
    env.context.check_final_request = FunctionType(code, vars(executor), closure=(cell,))
    value, journal = operation(env)

    def stop():
        if mode == "cancel":
            owner._stop_requested = True
        else:
            connection.disconnected.set()
    env.writer_hook[0] = stop
    with pytest.raises(env.module.BridgeError) as error:
        value.run()
    assert error.value.code == "TIMEOUT" and env.calls[-1] == "native_write"
    receipt = journal.snapshot()["snapshots"][0]
    assert receipt["native_returned"] and receipt["stopped"] and not receipt["parser_entered"]


def test_memory_pressure_after_permission_provider_refuses_before_native_entry(observation, monkeypatch):
    env = observation
    available = [12 * 1024**3]
    monkeypatch.setattr(env.module, "available_memory_facts", lambda: {"available_memory_bytes": available[0]})
    value, journal = operation(env)

    def pressure():
        if env.calls.count("provider") == 2:
            available[0] = 1024**3
    env.provider_hook[0] = pressure
    with pytest.raises(env.module.BridgeError):
        value.run()
    receipt = journal.snapshot()["snapshots"][0]
    assert receipt["available_memory_bytes"] == 1024**3 and not receipt["native_entered"]
    assert "native_write" not in env.calls and "parser" not in env.calls


def test_partial_writer_failure_keeps_unknown_completion_and_partial_artifact(observation):
    env = observation
    value, journal = operation(env)

    def fail():
        raise OSError("owned injected partial write")
    env.writer_hook[0] = fail
    with pytest.raises(OSError, match="partial write"):
        value.run()
    receipt = journal.snapshot()["snapshots"][0]
    assert receipt["native_entered"] and not receipt["native_returned"] and receipt["retained_file_possible"]
    assert receipt["parser_entered"] is False and "parser" not in env.calls


@pytest.mark.parametrize("stop_after", [1, 2])
def test_stop_after_detached_parse_prevents_every_later_reader_and_live_reinspection(observation, stop_after):
    env = observation
    value, journal = operation(env)
    def stop(_proof):
        if env.calls.count("parser") == stop_after:
            env.context.state.paused = True
    env.parser_hook[0] = stop
    with pytest.raises(env.module.BridgeError):
        value.run()
    assert env.calls.count("parser") == stop_after and env.calls[-1] == "parser"
    receipt = journal.snapshot()["snapshots"][0]
    assert receipt["parser_entered"] and not receipt["parser_returned"] and not receipt["cleanup_entered"]


def test_parser_return_source_change_refuses_before_foreign_projection_helper(observation, monkeypatch):
    env = observation
    value, journal = operation(env)
    foreign = []
    with monkeypatch.context() as patch:
        def replace(_proof):
            patch.setattr(env.module, "_projection", lambda *_: foreign.append("projection"))
        env.parser_hook[0] = replace
        with pytest.raises(env.module.BridgeError):
            value.run()
    assert foreign == [] and env.calls[-1] == "parser"
    assert journal.snapshot()["snapshots"][0]["identity_verified"] is False


@pytest.mark.parametrize("target", ["_mark", "__getattribute__"])
def test_native_return_facts_survive_changed_operation_dispatch(observation, monkeypatch, target):
    env = observation
    value, journal = operation(env)
    foreign = []
    with monkeypatch.context() as patch:
        def replace():
            patch.setattr(env.module.SnapshotOperation, target, lambda *_: foreign.append("operation"))
        env.writer_hook[0] = replace
        with pytest.raises(env.module.BridgeError):
            value.run()
    row = journal.snapshot()["snapshots"][0]
    assert foreign == [] and row["native_returned"] and row["stopped"] and row["failed"]
    assert not row["parser_entered"] and Path(row["filepath"]).is_file()


@pytest.mark.parametrize("fault", ["value_type", "duplicate", "file_identity", "digest"])
def test_incomplete_or_foreign_raw_projection_is_not_certified(observation, fault):
    env = observation
    value, journal = operation(env)

    def damage(proof):
        if fault == "value_type":
            proof["storage"]["children"][0]["value"] = True
        elif fault == "duplicate":
            proof["storage"]["children"][1]["name"] = proof["storage"]["children"][0]["name"]
        elif fault == "file_identity":
            proof["file_identity"][0] += 1
        else:
            proof["file_sha256"] = "invalid"
    env.parser_hook[0] = damage
    with pytest.raises(env.module.BridgeError):
        value.run()
    assert journal.snapshot()["snapshots"][0]["identity_verified"] is False


def test_operation_and_witness_are_one_use(observation):
    env = observation
    value, _journal = operation(env)
    witness = value.run()
    witness.consume(env.context, env.bpy, env.scenes)
    before = list(env.calls)
    with pytest.raises(env.module.BridgeError):
        value.run()
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)
    assert env.calls == before


def test_witness_cannot_cross_a_returned_call_activation(observation):
    env = observation
    value, _journal = operation(env)

    def earlier_turn():
        return value.run()
    witness = earlier_turn()
    before = list(env.calls)
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)
    assert env.calls == before


def test_generator_turn_refuses_before_provider_and_files(observation):
    env = observation
    value, journal = operation(env)

    def yielding_turn():
        yield value.run()
    with pytest.raises(env.module.BridgeError):
        next(yielding_turn())
    assert env.calls == [] and journal.snapshot()["snapshots"] == []


def test_foreign_or_changed_identity_cannot_consume_a_prior_proof(observation):
    env = observation
    value, _journal = operation(env)
    witness = value.run()
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, (env.scenes[1], env.scenes[0]))
    env.changed[0] = True
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)
    env.changed[0] = False
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)


def test_identity_drift_on_first_consumption_burns_the_proof_without_rebaselining(observation):
    env = observation
    value, journal = operation(env)
    witness = value.run()
    env.changed[0] = True
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)
    assert env.calls[-1] == "native_identity" and journal.snapshot()["snapshots"][0]["consumed"] is False
    before = list(env.calls)
    env.changed[0] = False
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)
    assert env.calls == before


@pytest.mark.parametrize("mode", [0o755, 0o777])
def test_nonprivate_existing_root_is_never_used(observation, mode):
    env = observation
    env.root.chmod(mode)
    value, journal = operation(env)
    with pytest.raises(env.module.BridgeError):
        value.run()
    assert "native_write" not in env.calls and list(env.root.iterdir()) == [] and journal.snapshot()["snapshots"] == []


def test_cgroup_namespace_measurement_counts_every_visible_ancestor(addon_package):
    module = importlib.import_module(addon_package + ".storage_snapshot")
    mount = "42 1 0:5 /.. /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
    assert module._visible_cgroup_paths("0::/\n", mount) == (Path("/sys/fs/cgroup"),)
    assert module._visible_cgroup_paths("0::/one/two\n", mount) == (
        Path("/sys/fs/cgroup/one/two"), Path("/sys/fs/cgroup/one"), Path("/sys/fs/cgroup"))
    with pytest.raises(module.BridgeError):
        module._visible_cgroup_paths("0::/../escape\n", mount)


def test_id_rejects_foreign_owner_before_its_rna_getter(addon_package):
    module = importlib.import_module(addon_package + ".storage_snapshot")
    calls = []

    class Foreign:
        @property
        def bl_rna(self):
            calls.append("foreign")
            raise AssertionError("unqualified RNA")

    fake = SimpleNamespace(types=SimpleNamespace(Foreign=Foreign, bpy_struct=object))
    with pytest.raises(module.BridgeError):
        module._id(fake, Foreign())
    assert calls == []


def test_field_rejects_python_metadata_shadow_before_getting_it(addon_package):
    module = importlib.import_module(addon_package + ".storage_snapshot")
    calls = []

    class Owner:
        @property
        def bl_rna(self):
            calls.append("foreign")
            raise AssertionError("foreign metadata")

    class Struct:
        pass

    fake = SimpleNamespace(types=SimpleNamespace(Owner=Owner, Struct=Struct, bpy_struct=object))
    with pytest.raises(module.BridgeError):
        module._field(fake, Owner(), "Owner", "name", "STRING", readonly=False)
    assert calls == []


@pytest.fixture
def metadata_model(addon_package, monkeypatch):
    """Native-class substitution at model setup, never a product exception."""
    module = importlib.import_module(addon_package + ".storage_snapshot")
    calls = []
    class Struct:
        __slots__ = ("identifier", "properties")
        def __init__(self, identifier):
            self.identifier, self.properties = identifier, ()
    metadata = Struct("Owner")
    class Owner:
        bl_rna = metadata
        name = "owned value"
    fake = SimpleNamespace(types=SimpleNamespace(Owner=Owner, Struct=Struct))
    def native_class(bpy, name):
        assert bpy is fake
        calls.append(("class", name))
        return {"Owner": Owner, "Struct": Struct}[name]
    def native_field(bpy, owner, kind, name, category, *, target, readonly):
        calls.append(("field", kind, name, category, target, readonly))
    monkeypatch.setattr(module.roles, "_particle_class", native_class)
    monkeypatch.setattr(module.roles, "_particle_field", native_field)
    return SimpleNamespace(module=module, fake=fake, Owner=Owner, Struct=Struct,
                           metadata=metadata, calls=calls)


def test_field_derives_actual_wrapper_and_qualifies_canonical_struct_without_structrna_export(metadata_model):
    env = metadata_model
    assert not hasattr(env.fake.types, "StructRNA")
    assert env.module._field(env.fake, env.Owner(), "Owner", "name", "STRING", readonly=False) == "owned value"
    assert env.calls == [("class", "Owner"), ("class", "Struct"), ("field", "Owner", "name", "STRING", None, False)]


@pytest.mark.parametrize("tamper", ["wrong_wrapper", "wrong_origin", "owner_binding", "identifier_shadow", "properties_shadow", "identifier"])
def test_field_metadata_origin_and_shadow_refusals_do_not_call_foreign_getters(metadata_model, monkeypatch, tamper):
    env = metadata_model
    foreign = []
    class Foreign:
        @property
        def identifier(self):
            foreign.append("identifier")
            raise AssertionError("foreign metadata")
        @property
        def properties(self):
            foreign.append("properties")
            raise AssertionError("foreign metadata")
    if tamper == "wrong_wrapper":
        monkeypatch.setattr(env.Owner, "bl_rna", Foreign())
    elif tamper == "wrong_origin":
        other = type("Struct", (), {})
        original = env.module.roles._particle_class
        monkeypatch.setattr(env.module.roles, "_particle_class", lambda bpy, name: other if name == "Struct" else original(bpy, name))
    elif tamper == "owner_binding":
        owner = env.Owner()
        owner.bl_rna = env.Struct("Owner")
    elif tamper in {"identifier_shadow", "properties_shadow"}:
        label = tamper.removesuffix("_shadow")
        def getter(self):
            foreign.append(label)
            raise AssertionError("foreign metadata")
        monkeypatch.setattr(env.Struct, label, property(getter))
    else:
        env.metadata.identifier = "DifferentOwner"
    owner = owner if tamper == "owner_binding" else env.Owner()
    with pytest.raises(env.module.BridgeError):
        env.module._field(env.fake, owner, "Owner", "name", "STRING", readonly=False)
    assert foreign == [] and not any(row[0] == "field" for row in env.calls)


def test_actual_native_source_rejects_foreign_blender_before_any_attribute(addon_package):
    module = importlib.import_module(addon_package + ".storage_snapshot")
    calls = []

    class Foreign:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("Foreign Blender wrapper")

    with pytest.raises(module.BridgeError):
        module._NativeSource(Foreign(), (object(), object()))
    assert calls == []


def test_consumption_rejects_changed_operation_owner_before_foreign_control(observation):
    env = observation
    value, _journal = operation(env)
    witness = value.run()
    calls = []

    class Foreign:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("Foreign control")

    value.context = Foreign()
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)
    assert calls == []


@pytest.mark.parametrize("field", ["cell", "slots"])
def test_consumption_cannot_redirect_its_retained_effect_cell_or_slot_writer(observation, field):
    env = observation
    value, journal = operation(env)
    witness = value.run()
    calls = []

    class Foreign:
        def __iter__(self):
            calls.append("foreign iterate")
            raise AssertionError("Foreign slots")

        def __setattr__(self, name, value):
            calls.append("foreign write")
            raise AssertionError("Foreign cell")

    setattr(value, field, Foreign())
    before = list(env.calls)
    with pytest.raises(env.module.BridgeError):
        witness.consume(env.context, env.bpy, env.scenes)
    assert calls == [] and env.calls == before
    row = journal.snapshot()["snapshots"][0]
    assert not row["consumed"] and row["retained_file_possible"] and Path(row["filepath"]).is_file()
