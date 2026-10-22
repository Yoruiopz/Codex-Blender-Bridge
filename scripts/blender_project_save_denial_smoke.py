"""No-write legacy save refusal in an official disposable background process."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import core  # noqa: E402


def main():
    assert bpy.app.background and os.environ.get("BRIDGE_TEST_PROCESS_TOKEN")
    blender_codex_bridge.register()
    runtime = get_runtime()
    lookups, save_callbacks = [], []
    original_reader = core.require_blender

    def no_blender():
        lookups.append(True)
        raise AssertionError("Refused save reached a Blender reader")

    def save_callback(_unused):
        save_callbacks.append(True)

    native_before = (bpy.data.filepath, bpy.data.is_dirty, bpy.context.scene.as_pointer(), bpy.context.mode,
                     sorted(obj.name for obj in bpy.context.selected_objects))
    core.require_blender = no_blender
    bpy.app.handlers.save_pre.append(save_callback)
    tested = []
    try:
        for case in ("unsupported_current", "unsupported_new", "save_denied", "path_denied", "save_revoked", "queued", "disconnect", "deadline", "pause", "emergency"):
            grants = {"SAVE_PROJECT": case != "save_denied", "ACCESS_EXTERNAL_FILES": case != "path_denied"}
            lifetime = RequestLifetime(ConnectionLifetime())
            filepath = Path(os.environ["TEMP"])/"no-file-created.blend"
            params = {} if case == "unsupported_current" else {"filepath": str(filepath)}
            request = Request("native-save-" + case, "project.save", params, _lifecycle=lifetime)
            queued = QueuedRequest(request, deadline=float("inf"))
            assert queued.try_start()
            reads = []

            def provider(reads=reads, case=case, queued=queued, lifetime=lifetime, grants=grants):
                reads.append(True)
                if len(reads) == 2:
                    if case == "queued":
                        queued.cancel_pending(BridgeError("TIMEOUT", "Fixture caller canceled"))
                    elif case == "disconnect":
                        lifetime.connection.disconnected.set()
                    elif case == "deadline":
                        lifetime.deadline = 0.
                    elif case == "pause":
                        runtime.state.set_paused(True)
                    elif case == "emergency":
                        runtime.state.set_emergency_stopped(True)
                    elif case == "save_revoked":
                        grants["SAVE_PROJECT"] = False
                return dict(grants)

            runtime.permissions = runtime.executor.permissions = PermissionManager(provider)
            response = runtime.executor.execute_request(request, check_cancelled=queued.check_active)
            assert not response.ok, response.to_dict()
            expected = {"unsupported_current": "NOT_IMPLEMENTED", "unsupported_new": "NOT_IMPLEMENTED",
                        "save_denied": "PERMISSION_DENIED", "path_denied": "PERMISSION_DENIED",
                        "save_revoked": "PERMISSION_DENIED", "pause": "AGENT_PAUSED",
                        "emergency": "EMERGENCY_STOPPED"}.get(case, "TIMEOUT")
            assert response.error["code"] == expected, response.to_dict()
            if case != "save_denied":
                assert response.error["context"]["native_save_invoked"] is False
            assert not filepath.exists()
            runtime.state.set_paused(False)
            runtime.state.set_emergency_stopped(False)
            tested.append(case)
        assert native_before == (bpy.data.filepath, bpy.data.is_dirty, bpy.context.scene.as_pointer(), bpy.context.mode,
                                 sorted(obj.name for obj in bpy.context.selected_objects))
        assert not lookups and not save_callbacks
        print("BLENDER_PROJECT_SAVE_DENIAL_OK " + json.dumps({"blender": bpy.app.version_string,
            "no_write_denial_cases": tested, "native_save_invoked": False, "bridge_file_writes": False,
            "blender_handler_reader_invoked": False, "python_save_callback_invoked": False,
            "bridge_safe_project_save_verified": False, "fixture_native_save": False,
            "release_readiness": "NOT_ASSESSED"}), flush=True)
    finally:
        bpy.app.handlers.save_pre.remove(save_callback)
        core.require_blender = original_reader
        blender_codex_bridge.unregister()


main()
