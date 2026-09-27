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
        baseline = bpy.data.objects["Cube"].location.x
        manager.create("Measured snapshot baseline")
        assert manager.before_modification("first")
        bpy.data.objects["Cube"].location.x = 1.0
        assert manager.after_modification("first")
        assert manager.before_modification("second_with_native_steps")
        bpy.data.objects["Cube"].location.x = 2.0
        bpy.ops.ed.undo_push(message="Fixture internal native step")
        bpy.ops.transform.translate("EXEC_DEFAULT", True, value=(1.0, 0.0, 0.0))
        assert manager.after_modification("second_with_native_steps")
        assert bpy.data.objects["Cube"].location.x == 3.0
        result = get_runtime().dispatch(
            "checkpoint.undo_last",
            {
                "confirm_global_undo": True,
                "restore_snapshot": True,
            },
        )
        assert result["snapshot_marker_verified"] and result["undo_steps"] >= 3
        assert bpy.data.objects["Cube"].location.x == 1.0
        assert manager.restore_operation()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        assert manager.restore_last()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        # A global named checkpoint remains usable after an Edit Mode round trip.
        import bmesh

        vertices_before = [tuple(v.co) for v in bpy.data.objects["Cube"].data.vertices]
        manager.create("Before editor-specific changes")
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="EDIT")
        assert not manager.before_modification("editor_mesh_change")
        mesh = bmesh.from_edit_mesh(bpy.data.objects["Cube"].data)
        mesh.verts.ensure_lookup_table()
        mesh.verts[0].co.x += 0.7
        bmesh.update_edit_mesh(bpy.data.objects["Cube"].data)
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="OBJECT")
        assert manager.restore_last()["snapshot_marker_verified"]
        assert bpy.context.mode == "OBJECT"
        assert [tuple(v.co) for v in bpy.data.objects["Cube"].data.vertices] == vertices_before

        def fail_after_mutating(_context, _params):
            bpy.data.objects["Cube"].location.x = 6.0
            raise RuntimeError("injected unexpected handler failure")

        get_runtime().registry.register("fixture.fail", fail_after_mutating, modifies=True)
        try:
            get_runtime().dispatch("fixture.fail")
        except BridgeError as error:
            assert error.context["undo_boundary_finalized"] and error.context["execution_started"]
        else:
            raise AssertionError("Injected handler failure succeeded")
        assert bpy.data.objects["Cube"].location.x == 6.0
        assert manager.restore_operation()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        # Restore a named checkpoint directly over multiple logical operations.
        manager.create("Multi operation baseline")
        for coordinate in (4.0, 5.0):
            assert manager.before_modification("data_edit")
            bpy.data.objects["Cube"].location.x = coordinate
            assert manager.after_modification("data_edit")
        assert manager.restore_last()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        # An evicted target must fail and return to the measured guard, not claim success.
        previous_limit = bpy.context.preferences.edit.undo_steps
        bpy.context.preferences.edit.undo_steps = 2
        try:
            assert manager.before_modification("evicted")
            bpy.data.objects["Cube"].location.x = 9.0
            assert manager.after_modification("evicted")
            for index in range(8):
                bpy.data.objects["Cube"].location.x = 10.0 + index
                bpy.ops.ed.undo_push(message="Eviction fixture")
            try:
                manager.restore_operation()
            except BridgeError as error:
                assert error.context["return_to_guard_verified"], error
            else:
                raise AssertionError("Evicted snapshot was reported restored")
            assert bpy.data.objects["Cube"].location.x == 17.0
        finally:
            bpy.context.preferences.edit.undo_steps = previous_limit
        manager.clear()
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
            manager.restore_operation()
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
                    "object_mode_transform_snapshot_restoration_verified": True,
                    "internal_native_steps_and_checkpoint_restore_verified": True,
                    "evicted_target_returns_to_guard": True,
                    "global_checkpoint_after_edit_mode_round_trip": True,
                    "unexpected_partial_failure_has_recoverable_snapshot": True,
                    "full_recovery_acceptance_verified": False,
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
