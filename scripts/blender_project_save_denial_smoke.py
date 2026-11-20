"""No-write save denials through the canonical add-on in an owned Blender process."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.preferences import get_preferences  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def main():
    assert bpy.app.background and os.environ.get("BRIDGE_TEST_PROCESS_TOKEN")
    assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
    runtime, prefs = get_runtime(), get_preferences()
    bpy.context.preferences.use_preferences_save = False
    assert not prefs.all_dangerous_permissions
    target = Path(os.environ["TEMP"]).resolve() / "denied project path.blend"
    assert not target.exists()
    cases = {"unsaved": "INVALID_ARGUMENT", "unapproved": "PERMISSION_DENIED", "direct": "NOT_IMPLEMENTED",
             "save_denied": "PERMISSION_DENIED", "path_denied": "PERMISSION_DENIED", "queued": "TIMEOUT",
             "disconnect": "TIMEOUT", "deadline": "TIMEOUT", "pause": "AGENT_PAUSED", "emergency": "EMERGENCY_STOPPED"}
    save_callbacks = []

    def save_callback(_unused):
        save_callbacks.append(True)

    def native_state():
        return (bpy.data.filepath, bpy.data.is_dirty, bpy.context.scene.as_pointer(), bpy.context.mode,
                sorted(obj.name for obj in bpy.context.selected_objects))

    native_before = native_state()
    bpy.app.handlers.save_pre.append(save_callback)
    tested = []
    try:
        for case, code in cases.items():
            prefs.allow_save_project = case != "save_denied"
            prefs.allow_external_files = case != "path_denied"
            prefs.project_directory = "" if case == "unapproved" else str(target.parent)
            lifetime = RequestLifetime(ConnectionLifetime(), time.monotonic() + 30.)
            params = {} if case == "unsaved" else {"filepath": str(target)}
            request = Request("native-save-" + case, "project.save", params, _lifecycle=lifetime)
            queued = QueuedRequest(request, deadline=time.monotonic() + 30.)
            assert queued.try_start()
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
            response = runtime.executor.execute_request(request, check_cancelled=None if case == "direct" else queued.check_active)
            assert not response.ok and response.error["code"] == code, response.to_dict()
            assert not response.error.get("context", {}).get("native_save_invoked", False)
            assert not target.exists() and not save_callbacks
            runtime.state.set_emergency_stopped(False)
            runtime.state.set_paused(False)
            tested.append(case)
        assert native_before == native_state()
        print("BLENDER_PROJECT_SAVE_DENIAL_OK " + json.dumps({"blender": bpy.app.version_string,
            "no_write_denial_cases": tested, "native_save_invoked": False, "bridge_file_writes": False,
            "python_save_callback_invoked": False, "fixture_native_save": False,
            "release_readiness": "NOT_ASSESSED"}), flush=True)
    finally:
        bpy.app.handlers.save_pre.remove(save_callback)
        bpy.ops.preferences.addon_disable(module="blender_codex_bridge")


main()
