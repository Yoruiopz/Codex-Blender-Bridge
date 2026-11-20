"""The queued stock save obeys local path policy and reports actual effects."""
from __future__ import annotations

import importlib
import inspect
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def save_env(addon_package, monkeypatch, tmp_path):
    def module(name):
        return importlib.import_module(f"{addon_package}.{name}")

    runtime_module = module("runtime")
    monkeypatch.setattr(runtime_module, "get_state", module("state").BridgeState)
    runtime = runtime_module.BridgeRuntime()
    runtime._registered = True
    monkeypatch.setattr(runtime_module, "_RUNTIME", runtime)
    native = module("native_save_standard")
    recovery = module("project_recovery")
    plan = module("task_plans").get_task_plans(runtime.state)
    approved = tmp_path / "Approved Project Path"
    approved.mkdir()
    prefs = NS(allow_save_project=True, allow_external_files=True, project_directory=str(approved),
               allow_unrestricted_project_texture_paths=False, all_dangerous_permissions=False)
    bpy = NS(data=NS(filepath=""), context=NS(preferences=NS(
        addons={addon_package: NS(preferences=prefs)}, filepaths=NS(save_version=1))))
    markers, calls, measured = [], [], []
    action = NS(poll=lambda: True, native=lambda: None, check_recovery=lambda: None)

    def writer(*, filepath=None, **options):
        action.native()
        calls.append((filepath, options))
        path = Path(bpy.data.filepath if filepath is None else filepath)
        path.write_bytes(b"BLENDER-test-file")
        bpy.data.filepath = str(path)
        return {"FINISHED"}

    writer.poll = lambda: action.poll()
    bpy.ops = NS(wm=NS(save_mainfile=writer, save_as_mainfile=writer))

    def checkpoint(path, check):
        action.check_recovery()
        check()
        measured.append(path)
        return {"state": "available", "verification": "saved_bytes"}

    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setattr(native, "get_preferences", lambda: prefs)
    monkeypatch.setattr(native, "require_blender", lambda: bpy)
    monkeypatch.setattr(recovery, "save_recovery_checkpoint", checkpoint)
    monkeypatch.setattr(runtime.checkpoints, "finish_editor_session", lambda: markers.append("finish"))
    monkeypatch.setattr(runtime.checkpoints, "editor_session_status", lambda: {"state": "deferred"})

    def call(params, *, queue=True, before=None):
        lifetime_module = module("request_lifecycle")
        lifetime = lifetime_module.RequestLifetime(lifetime_module.ConnectionLifetime())
        request = module("protocol").Request("save-test", "project.save", params, _lifecycle=lifetime)
        queued = module("command_queue").QueuedRequest(request, deadline=time.monotonic() + 30.0)
        assert queued.try_start()
        if before is not None:
            before(queued, lifetime)
        return runtime.executor.execute_request(request, check_cancelled=queued.check_active if queue else None)

    return NS(module=module, runtime=runtime, native=native, prefs=prefs, bpy=bpy, approved=approved,
              plan=plan, calls=calls, measured=measured, markers=markers, action=action, call=call)


def test_first_save_save_as_and_current_return_actual_filepath_with_no_arming(save_env):
    e = save_env
    first, second = e.approved / "First Save.blend", e.approved / "Save As.blend"
    unsaved = e.call({})
    assert unsaved.error["code"] == "INVALID_ARGUMENT" and unsaved.error["context"]["requires_filepath"]
    for params, expected, mode in (({"filepath": str(first)}, first, "SAVE_AS"),
                                   ({"filepath": str(second)}, second, "SAVE_AS"),
                                   ({}, second, "SAVE_CURRENT")):
        reply = e.call(params)
        assert reply.ok, reply.to_dict()
        assert reply.result["filepath"] == reply.result["actual_saved_path"] == str(expected)
        assert reply.result["mode"] == mode and reply.result["saved"]
        assert reply.result["file_bytes"] == expected.stat().st_size
        assert reply.result["fresh_process_reopen_verified"] is False
        assert reply.result["recovery_checkpoint"]["verification"] == "saved_bytes"
    assert e.calls == [(str(first), {"check_existing": False}), (str(second), {"check_existing": False}), (None, {})]
    assert e.measured == [first, second, second] and e.markers == []


def test_existing_save_as_requires_explicit_replace(save_env):
    e = save_env
    existing = e.approved / "Existing.blend"
    existing.write_bytes(b"original")
    refused = e.call({"filepath": str(existing)})
    assert refused.error["context"]["reason"] == "PROJECT_DESTINATION_EXISTS"
    assert existing.read_bytes() == b"original" and e.calls == []
    assert e.call({"filepath": str(existing), "overwrite": True}).ok


@pytest.mark.parametrize("missing", ["allow_save_project", "allow_external_files"])
def test_denial_precedes_native_and_destination_access(save_env, monkeypatch, missing):
    setattr(save_env.prefs, missing, False)
    monkeypatch.setattr(save_env.native, "approve_project_path", lambda *_: pytest.fail("Denied path inspected"))
    result = save_env.call({"filepath": str(save_env.approved / "never.blend")})
    assert result.error["code"] == "PERMISSION_DENIED" and save_env.calls == []


@pytest.mark.parametrize("stop", ["queued", "disconnect", "deadline", "pause", "emergency"])
def test_cooperative_stop_after_poll_prevents_native_write(save_env, stop):
    e = save_env

    def before(queued, lifetime):
        def poll():
            if stop == "queued":
                queued.cancel_pending(e.module("errors").BridgeError("TIMEOUT", "Caller canceled"))
            elif stop == "disconnect":
                lifetime.connection.disconnected.set()
            elif stop == "deadline":
                lifetime.deadline = 0.
            elif stop == "pause":
                e.runtime.state.set_paused(True)
            else:
                e.runtime.state.set_emergency_stopped(True)
            return True
        e.action.poll = poll

    result = e.call({"filepath": str(e.approved / "never.blend")}, before=before)
    assert result.error["code"] == {"pause": "AGENT_PAUSED", "emergency": "EMERGENCY_STOPPED"}.get(stop, "TIMEOUT")
    assert result.error["context"]["native_save_invoked"] is False and e.calls == e.markers == []


def test_stop_after_native_separates_a_finished_save_from_checkpoint_success(save_env):
    e = save_env
    path = e.approved / "Partially Verified.blend"
    e.action.native = lambda: e.runtime.state.set_paused(True)
    result = e.call({"filepath": str(path)})
    assert result.error["code"] == "AGENT_PAUSED"
    assert result.error["context"]["active_filepath"] == str(path)
    assert result.error["context"]["native_save_finished"] is True and path.is_file()
    assert result.error["context"]["possible_file_writes"] is True and e.measured == e.markers == []


def test_checkpoint_interruption_preserves_the_successful_save_receipt(save_env):
    e = save_env
    path = e.approved / "Checkpoint Interrupted.blend"
    e.action.check_recovery = lambda: e.runtime.state.set_paused(True)
    result = e.call({"filepath": str(path)})
    assert result.ok and result.result["saved"] and result.result["filepath"] == str(path)
    assert result.result["recovery_checkpoint"] == {"state": "unavailable", "reason": "RECOVERY_VERIFICATION_INTERRUPTED",
                                                    "error_code": "AGENT_PAUSED"}
    assert path.is_file() and e.measured == e.markers == []


def test_native_error_returns_an_observed_path_without_claiming_a_verified_write(save_env):
    e = save_env
    path = e.approved / "Native Failure.blend"

    def fail_after_partial_write():
        path.write_bytes(b"partial")
        e.bpy.data.filepath = str(path)
        raise RuntimeError("Native save handler failed")

    e.action.native = fail_after_partial_write
    response = e.call({"filepath": str(path)})
    assert response.error["code"] == "OPERATION_FAILED"
    facts = response.error["context"]
    assert facts["reason"] == "NATIVE_SAVE_ERROR" and facts["active_filepath"] == str(path)
    assert facts["native_error"] == "Native save handler failed"
    assert facts["native_save_invoked"] and facts["possible_file_writes"] and facts["verification_required"]
    assert not facts["native_save_finished"] and not facts["project_saved"]
    assert path.read_bytes() == b"partial" and e.measured == e.markers == []


def test_canonical_queue_and_protected_scope_required(save_env, monkeypatch):
    e = save_env
    monkeypatch.setattr(e.native, "approve_project_path", lambda *_: pytest.fail("Refused path inspected"))
    assert e.call({}, queue=False).error["context"]["reason"] == "NATIVE_SAVE_REQUIRES_QUEUED_REQUEST"
    e.plan.protection = object()
    assert e.call({}).error["context"]["protected_scope_enforced"] is True
    assert e.calls == e.markers == []


@pytest.mark.parametrize("master,bypass,allowed", [(False, False, False), (False, True, False),
                                                   (True, False, False), (True, True, True)])
def test_blank_folder_requires_both_persistent_opt_ins(save_env, master, bypass, allowed):
    e = save_env
    e.prefs.project_directory = ""
    e.prefs.all_dangerous_permissions = master
    e.prefs.allow_unrestricted_project_texture_paths = bypass
    result = e.call({"filepath": str(e.approved.parent / "outside.blend")})
    assert result.ok is allowed
    if not allowed:
        assert result.error["code"] == "PERMISSION_DENIED" and e.calls == []


def test_selected_folder_is_scoped_and_current_save_needs_no_extra_path_grant(save_env):
    e = save_env
    outside = e.approved.parent / "Scoping.blend"
    assert e.call({"filepath": str(outside)}).error["code"] == "PERMISSION_DENIED"
    current = e.approved / "Current.blend"
    current.write_bytes(b"original")
    e.bpy.data.filepath = str(current)
    e.prefs.allow_external_files = False
    assert e.call({}).ok


def test_path_symlink_and_windows_device_forms_are_refused(save_env):
    e = save_env
    if sys.platform != "win32":
        outside = e.approved.parent / "unaltered.blend"
        outside.write_bytes(b"original")
        link = e.approved / "Linked.blend"
        link.symlink_to(outside)
        assert e.call({"filepath": str(link), "overwrite": True}).error["code"] == "INVALID_ARGUMENT"
        assert outside.read_bytes() == b"original"
    for raw in (r"C:relative.blend", r"\\server\share\scene.blend", r"\\?\C:\scene.blend", r"C:\NUL.blend",
                r"C:\scene.blend:stream", r"C:\folder.\scene.blend", r"C:\folder\..\scene.blend"):
        with pytest.raises(e.module("errors").BridgeError):
            e.native._ordinary_text(raw, windows=True)
    assert e.native._ordinary_text(r"C:\Project with spaces\scene.blend", windows=True).startswith("C:")


def test_save_registration_and_mcp_schema_remain_compatible(save_env):
    from mcp_server.tools.catalog import CORE_DEFINITIONS
    from mcp_server.tools.project import ProjectTools

    spec = save_env.runtime.registry.get("project.save")
    assert spec.modifies and not spec.automatic_checkpoint and spec.toolset == "core"
    assert spec.exclusive_mutation and spec.checkpoint_owns_finalization and not spec.batchable
    assert spec.remote and {item.value for item in spec.permissions} == {"SAVE_PROJECT"}
    tool = next(item for item in CORE_DEFINITIONS if item.name == "project.save")
    assert set(tool.required_permissions) == {"SAVE_PROJECT"}
    signature = inspect.signature(ProjectTools.project_save)
    assert list(signature.parameters) == ["self", "filepath", "overwrite"]
    assert signature.parameters["filepath"].default is None
    assert signature.parameters["overwrite"].default is False
