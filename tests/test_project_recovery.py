from __future__ import annotations

import gzip
import hashlib
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def recovery_env(addon_package, tmp_path, monkeypatch):
    store = importlib.import_module(f"{addon_package}.project_recovery")
    tools = importlib.import_module(f"{addon_package}.tools.project_recovery")
    error = importlib.import_module(f"{addon_package}.errors")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    config = tmp_path / "blender user config"
    config.mkdir()
    projects = tmp_path / "approved project folder"
    projects.mkdir()
    project = projects / "Test asset.blend"
    data = b"BLENDER-v409test checkpoint data"
    project.write_bytes(data)
    config_access = []
    native_calls = []
    flags = {permission.value: True for permission in permissions.Permission}

    def user_resource(resource, *, create):
        assert resource == "CONFIG"
        config_access.append(create)
        return str(config)

    def open_mainfile(**kwargs):
        native_calls.append(kwargs)
        bpy.data.filepath = kwargs["filepath"]
        return {"FINISHED"}

    bpy = SimpleNamespace(utils=SimpleNamespace(user_resource=user_resource),
                          data=SimpleNamespace(filepath="", is_dirty=False, images=[]),
                          context=SimpleNamespace(mode="OBJECT"),
                          ops=SimpleNamespace(wm=SimpleNamespace(open_mainfile=open_mainfile)))

    def approve(filepath):
        path = Path(filepath)
        if path.parent != projects:
            raise store.EvidenceError("RECOVERY_PATH_NOT_APPROVED")
        return path

    monkeypatch.setattr(store, "require_blender", lambda: bpy)
    monkeypatch.setattr(tools, "require_blender", lambda: bpy)
    monkeypatch.setattr(tools, "_approve", approve)
    registry = registry_module.ToolRegistry()
    tools.register_tools(registry)
    checkpoints = SimpleNamespace(editor_session_status=lambda: None)
    context = registry_module.ToolContext(state, permissions.PermissionManager(lambda: flags),
                                         registry, checkpoints, jobs=SimpleNamespace(active=None))
    context.request_lifecycle = lifecycle.RequestLifetime.local()
    context.check_final_request = lambda: None
    runtime = SimpleNamespace(state=state, registry=registry, permissions=context.permissions,
                              checkpoints=context.checkpoints, jobs=context.jobs,
                              run_checkpoint_open=lambda opener: opener())
    runtime_module = importlib.import_module(f"{addon_package}.runtime")
    monkeypatch.setattr(runtime_module, "get_runtime", lambda: runtime)
    return SimpleNamespace(store=store, tools=tools, error=error, config=config, project=project,
                           data=data, config_access=config_access, context=context, bpy=bpy,
                           calls=native_calls, registry=registry, runtime=runtime, flags=flags,
                           package=addon_package, lifecycle=lifecycle,
                           status=lambda: registry.dispatch(tools.STATUS, {}, context),
                           reopen=lambda p: registry.dispatch(tools.REOPEN, p, context))


def _record(env):
    return env.store.save_recovery_checkpoint(env.project, lambda: None)


def _reopen_args(record, *, confirm=True):
    return {"checkpoint_id": record["checkpoint_id"], "confirm_reopen": confirm}


def test_reconnect_reads_saved_bytes_receipt_and_distinguishes_fresh_read(recovery_env):
    env = recovery_env
    assert env.status() == {"state": "unavailable", "reason": "NO_VERIFIED_CHECKPOINT"}
    assert not any(env.config.iterdir())
    result = _record(env)
    assert result["verification"] == "saved_bytes"
    assert result["fresh_process_reopen_verified"] is False
    assert result["file_sha256"] == hashlib.sha256(env.data).hexdigest()
    assert env.status() == result
    assert env.tools.recovery_hint(env.context) == {**result, "state": "verification_required"}

    fresh = env.store.record_verified_save(filepath=str(env.project), file_sha256=result["file_sha256"],
                                           file_bytes=len(env.data), fresh_process_reopen_verified=True)
    assert fresh["checkpoint_id"] != result["checkpoint_id"]
    assert fresh["verification"] == "fresh_process_reopen"
    assert env.status() == fresh


@pytest.mark.parametrize("saved_bytes", [
    b"BLENDER17-01v0501extended native header",
    gzip.compress(b"BLENDER-v409legacy compressed payload"),
    bytes.fromhex("28 B5 2F FD") + b"stock Zstandard frame prefix fixture",
])
def test_writer_byte_checkpoint_accepts_stock_container_prefixes(recovery_env, saved_bytes):
    env = recovery_env
    env.project.write_bytes(saved_bytes)
    result = _record(env)
    assert result["file_sha256"] == hashlib.sha256(saved_bytes).hexdigest()
    assert result["file_bytes"] == len(saved_bytes)
    assert result["verification"] == "saved_bytes"
    assert result["fresh_process_reopen_verified"] is False
    assert env.status() == result


@pytest.mark.parametrize(("signature_call", "phase", "field"), [
    (2, "open_signature", "file_id"),
    (3, "stream_signature", "modified_time"),
    (4, "final_path_signature", "creation_or_change_time"),
])
def test_signature_drift_reports_phase_and_field_without_accepting_it(
        recovery_env, monkeypatch, signature_call, phase, field):
    env = recovery_env
    prior = _record(env)
    real_signature = env.store._signature
    calls = []

    def changed_once(info):
        signature = list(real_signature(info))
        calls.append(None)
        if len(calls) == signature_call:
            signature[env.store._SIGNATURE_FIELDS.index(field)] += 1
        return tuple(signature)

    monkeypatch.setattr(env.store, "_signature", changed_once)
    assert _record(env) == {"state": "unavailable", "reason": "RECOVERY_FILE_CHANGED",
                            "verification_phase": phase, "changed_fields": [field]}
    assert env.status() == prior


def test_windows_path_and_descriptor_compare_birth_time_without_changing_old_semantics(recovery_env):
    signature = recovery_env.store._signature
    file_info = dict(st_dev=80, st_ino=449, st_size=7, st_mtime_ns=31)
    by_name = SimpleNamespace(**file_info, st_birthtime_ns=17, st_ctime_ns=17)
    descriptor = SimpleNamespace(**file_info, st_birthtime_ns=17, st_ctime_ns=23)
    assert signature(by_name, windows=True) == signature(descriptor, windows=True) == (80, 449, 7, 31, 17)
    assert signature(descriptor, windows=False)[-1] == 23
    descriptor.st_birthtime_ns = 18
    assert signature(by_name, windows=True) != signature(descriptor, windows=True)
    older = SimpleNamespace(**file_info, st_ctime_ns=17)
    assert signature(older, windows=True) == signature(by_name, windows=True)


@pytest.mark.parametrize("descriptor_change", [False, True])
def test_windows_descriptor_change_time_checked_independently_of_birth_time(
        recovery_env, monkeypatch, descriptor_change):
    env = recovery_env
    filename_stat = env.project.lstat()
    signature = env.store._signature
    fstat = env.store.os.fstat
    calls = []

    def simulated_windows_fstat(fd):
        value = fstat(fd)
        calls.append(None)
        birth = filename_stat.st_ctime_ns
        write = birth + (2 if descriptor_change and len(calls) == 2 else 1)
        return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino, st_size=value.st_size,
                               st_mode=value.st_mode, st_mtime_ns=value.st_mtime_ns,
                               st_ctime_ns=write, st_birthtime_ns=birth)

    monkeypatch.setattr(env.store, "_signature", lambda info: signature(info, windows=True))
    monkeypatch.setattr(env.store.os, "fstat", simulated_windows_fstat)
    if descriptor_change:
        with pytest.raises(env.store.EvidenceError) as drift:
            env.store.hash_project_bytes(env.project, lambda: None)
        assert drift.value.reason == "RECOVERY_FILE_CHANGED"
        assert drift.value.facts == {"verification_phase": "stream_signature",
                                     "changed_fields": ["descriptor_change_time"]}
    else:
        measured = env.store.hash_project_bytes(env.project, lambda: None)
        assert measured.sha256 == hashlib.sha256(env.data).hexdigest()
    assert len(calls) == 2


def test_failed_index_replacement_preserves_prior_receipt(recovery_env, monkeypatch):
    env = recovery_env
    prior = _record(env)

    def fail(*args):
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr(env.store.os, "replace", fail)
    assert _record(env) == {"state": "unavailable", "reason": "RECOVERY_INDEX_WRITE_FAILED"}
    assert env.status() == prior
    assert [item.name for item in env.config.iterdir()] == [env.store.INDEX_NAME]


def test_corrupt_index_does_not_reveal_a_path(recovery_env):
    env = recovery_env
    index = env.config / env.store.INDEX_NAME
    index.write_text('{"schema":1,"schema":1}', encoding="utf-8")
    assert env.status() == {"state": "unavailable", "reason": "RECOVERY_INDEX_INVALID"}


def test_live_permission_denial_never_reads_receipt(recovery_env):
    env = recovery_env
    _record(env)
    env.config_access.clear()
    env.flags["ACCESS_EXTERNAL_FILES"] = False
    assert env.tools.recovery_hint(env.context) is None
    with pytest.raises(env.error.BridgeError) as denied:
        env.status()
    assert denied.value.code == "PERMISSION_DENIED"
    assert env.config_access == []


def test_same_size_save_replacement_fails_digest_and_can_never_open(recovery_env):
    env = recovery_env
    prior = _record(env)
    env.project.write_bytes(env.data[:-1] + b"!")
    assert env.status() == {"state": "unavailable", "reason": "RECOVERY_FILE_CHANGED"}
    with pytest.raises(env.error.BridgeError, match="could not be verified") as denied:
        env.reopen(_reopen_args(prior))
    assert denied.value.context["reason"] == "RECOVERY_FILE_CHANGED"
    assert env.calls == []


def test_reopen_checks_confirmation_dirty_state_and_actual_native_path(recovery_env):
    env = recovery_env
    prior = _record(env)
    with pytest.raises(env.error.BridgeError) as denied:
        env.reopen(_reopen_args(prior, confirm=False))
    assert denied.value.code == "INVALID_ARGUMENT"
    env.bpy.data.is_dirty = True
    with pytest.raises(env.error.BridgeError) as denied:
        env.reopen(_reopen_args(prior))
    assert denied.value.context["reason"] == "RECOVERY_LIVE_PROJECT_NOT_CLEAN"
    assert env.calls == []

    env.bpy.data.is_dirty = False
    result = env.reopen(_reopen_args(prior))
    assert result["reopened"] is True
    assert result["filepath"] == str(env.project)
    assert result["file_sha256"] == prior["file_sha256"]
    assert env.calls == [{"filepath": str(env.project), "load_ui": False, "use_scripts": False}]
    assert env.status() == prior


def test_scope_loss_after_hash_refuses_open_and_cannot_rebase(recovery_env, monkeypatch):
    env = recovery_env
    prior = _record(env)

    def switch_scope_then_open(opener):
        def deny(path):
            raise env.store.EvidenceError("RECOVERY_PATH_NOT_APPROVED")
        monkeypatch.setattr(env.tools, "_approve", deny)
        return opener()

    env.runtime.run_checkpoint_open = switch_scope_then_open
    with pytest.raises(env.error.BridgeError) as denied:
        env.reopen(_reopen_args(prior))
    assert denied.value.context["reason"] == "RECOVERY_FILE_OR_CONTEXT_CHANGED"
    assert env.calls == []


def test_clean_project_flag_does_not_override_dirty_image_pixels(recovery_env):
    env = recovery_env
    prior = _record(env)
    assert env.bpy.data.is_dirty is False
    env.bpy.data.images.append(SimpleNamespace(is_dirty=True))
    with pytest.raises(env.error.BridgeError) as denied:
        env.reopen(_reopen_args(prior))
    assert denied.value.context["reason"] == "RECOVERY_DIRTY_IMAGES"
    assert env.calls == []


def test_native_finished_with_wrong_path_fails_owned_load_verification(recovery_env):
    env = recovery_env
    prior = _record(env)
    env.bpy.ops.wm.open_mainfile = lambda **kwargs: {"FINISHED"}
    load_callback_completed = []

    def run_owned(open_verified):
        result = open_verified()
        load_callback_completed.append(result)
        return result

    env.runtime.run_checkpoint_open = run_owned
    with pytest.raises(env.error.BridgeError) as failed:
        env.reopen(_reopen_args(prior))
    assert failed.value.context == {"reason": "RECOVERY_NATIVE_OPEN_UNVERIFIED", "execution_started": True,
                                    "verification_required": True}
    assert load_callback_completed == []


def test_queued_reopen_does_not_finalize_an_active_editor_session(recovery_env):
    env = recovery_env
    prior = _record(env)
    env.context.checkpoints.editor_session_status = lambda: {"state": "deferred"}

    def unexpected_finalize(*args, **kwargs):
        pytest.fail("A refused checkpoint reopen must not finalize an older editor session")

    env.context.checkpoints.finish_editor_session = unexpected_finalize
    executor_module = importlib.import_module(f"{env.package}.executor")
    queue_module = importlib.import_module(f"{env.package}.command_queue")
    protocol = importlib.import_module(f"{env.package}.protocol")
    queue = queue_module.CommandQueue()
    executor = executor_module.MainThreadExecutor(command_queue=queue, registry=env.registry,
                                                 state=env.context.state, permissions=env.context.permissions,
                                                 checkpoints=env.context.checkpoints, jobs=env.context.jobs)
    request = protocol.Request("reopen", env.tools.REOPEN, _reopen_args(prior), protocol.PROTOCOL_VERSION,
                               _lifecycle=env.lifecycle.RequestLifetime.local())
    queued = queue.submit(request, timeout=30)
    assert queued.try_start()
    response = executor.execute_request(request, check_cancelled=queued.check_active)
    assert response.ok is False
    assert response.error["context"]["reason"] == "RECOVERY_EDIT_SESSION_ACTIVE"
    assert env.calls == []


def test_cancellation_between_chunks_preserves_old_index(recovery_env, monkeypatch):
    env = recovery_env
    prior = _record(env)
    monkeypatch.setattr(env.store, "HASH_CHUNK_BYTES", 8)
    checks = []

    def cancel():
        checks.append(True)
        if len(checks) == 3:
            raise env.error.BridgeError(env.error.ErrorCode.TIMEOUT, "Stopped during digest")

    with pytest.raises(env.error.BridgeError, match="Stopped during digest"):
        env.store.save_recovery_checkpoint(env.project, cancel)
    assert env.status() == prior
