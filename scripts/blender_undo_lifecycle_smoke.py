"""Native undo/redo invalidation in an isolated interactive (not background) Blender."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def run():
    try:
        assert not bpy.app.background
        blender_codex_bridge.register()
        manager = get_runtime().checkpoints
        manager.create("Disposable lifecycle fixture")
        assert manager.before_modification("fixture.data_edit")
        bpy.data.objects["Cube"].location.x = 2.0
        manager.after_modification("fixture.data_edit")
        bpy.ops.ed.undo_push(message="Manual fixture snapshot")
        assert manager.list()
        assert bpy.ops.ed.undo() == {"FINISHED"}
        assert manager.list() == []
        before = bpy.data.objects["Cube"].location.x
        try:
            manager.undo_last()
        except BridgeError as error:
            assert error.code == "OPERATION_FAILED" and "No tracked" in error.message
        else:
            raise AssertionError("Stale bridge history survived native undo")
        assert bpy.data.objects["Cube"].location.x == before
        assert bpy.ops.ed.redo() == {"FINISHED"}
        assert manager.list() == []
        # Re-registration must not leak duplicate native handlers.
        blender_codex_bridge.unregister()
        blender_codex_bridge.register()
        from blender_codex_bridge.runtime import _before_external_undo_redo

        assert bpy.app.handlers.undo_pre.count(_before_external_undo_redo) == 1
        assert bpy.app.handlers.redo_pre.count(_before_external_undo_redo) == 1
        blender_codex_bridge.unregister()
        assert _before_external_undo_redo not in bpy.app.handlers.undo_pre
        assert _before_external_undo_redo not in bpy.app.handlers.redo_pre
        print(
            "BLENDER_UNDO_LIFECYCLE_OK "
            + json.dumps(
                {
                    "blender": bpy.app.version_string,
                    "native_undo_redo_invalidation": True,
                    "stale_bridge_undo_refused_without_mutation": True,
                    "handler_lifecycle_verified": True,
                    "logical_undo_restoration_verified": False,
                    "project_saved": False,
                }
            ),
            flush=True,
        )
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
