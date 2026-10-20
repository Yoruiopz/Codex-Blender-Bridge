"""Finite-history recovery in a disposable, profile-isolated interactive Blender."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))


def run():
    try:
        assert not bpy.app.background
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.checkpoints import MARKER_KEY
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime

        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = False
        prefs.allow_delete_objects = prefs.allow_external_files = False
        runtime.registry.enable_toolset("objects")
        runtime.registry.enable_toolset("interaction")
        manager = runtime.checkpoints
        factory_limit = bpy.context.preferences.edit.undo_steps
        assert factory_limit == 32
        protected = bpy.data.objects["Cube"].copy()
        protected.name, protected.location.x = "Protected Cube", 4
        bpy.context.scene.collection.objects.link(protected)
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((5, -6, 4)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 6

        def call(method, **params):
            return runtime.dispatch(method, params)

        def inspected_x():
            result = call("object.inspect", object_name="Cube")
            # Independently observe the native object, not only a transport success.
            value = float(bpy.data.objects["Cube"].location.x)
            assert result["location"][0] == value, result
            return value

        def set_x(value):
            result = call("transform.set", object_name="Cube", location=[value, 0, 0])
            assert result["operation"]["undo_boundary_finalized"]
            assert inspected_x() == value

        def undo():
            return call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)

        def unchanged(snapshot):
            diff = call("scene.compare", snapshot_id=snapshot["snapshot_id"])
            assert diff["coverage_complete"] and diff["status"] == "unchanged_within_scope", diff

        def capture():
            return call("viewport.capture", object_name="Cube", view="current", shading="solid",
                        resolution=[640, 480], include_overlays=False)["path"]

        call("selection.inspect")
        initial_selection = sorted(obj.name for obj in bpy.context.selected_objects)
        initial_active = bpy.context.view_layer.objects.active.name
        baseline = call("scene.snapshot", object_names=["Cube", "Protected Cube"])
        protected_snapshot = call("scene.snapshot", object_names=["Protected Cube"])
        before_image = capture()
        summaries = []
        for limit, expected_recovered in ((32, 16), (128, 17)):
            manager.clear()
            bpy.context.preferences.edit.undo_steps = limit  # Only this test process/profile.
            bpy.data.objects["Cube"].location.x = 0
            for value in range(1, 18):
                set_x(value)
            status = call("checkpoint.list")["recovery"]
            assert status["tracked_operation_count"] == expected_recovered, status
            assert status["expired_operations_pruned_since_clear"] == 17 - expected_recovered
            assert status["latest_operation"]["availability"] == "unverified"
            assert not status["native_history_introspection"] and not status["availability_guaranteed"]
            for expected in range(16, 16 - expected_recovered, -1):
                assert undo()["snapshot_marker_verified"]
                assert inspected_x() == expected
            final_x = inspected_x()
            try:
                undo()
            except BridgeError as error:
                assert error.code == "OPERATION_FAILED"
                assert not error.context["execution_started"]
                assert not error.context["scene_undo_performed"]
            else:
                raise AssertionError("Recovery navigated beyond retained tracked operations")
            assert inspected_x() == final_x
            unchanged(protected_snapshot)
            # A new branch after repeated recovery must not inherit discarded push ages.
            set_x(99)
            undo()
            assert inspected_x() == final_x
            summaries.append({"undo_steps": limit, "operations": 17,
                              "recovered": expected_recovered, "remaining_x": final_x})

        manager.clear()
        bpy.context.preferences.edit.undo_steps = 2
        bpy.data.objects["Cube"].location.x = 0
        named = call("checkpoint.create", description="Guard budget fixture")
        set_x(1)
        status = call("checkpoint.list")["recovery"]
        assert status["checkpoints"][0]["availability"] == "guard_would_exceed_step_limit", status
        marker = bpy.context.scene.get(MARKER_KEY)
        position = manager._window.position
        try:
            runtime.dispatch_recovery("checkpoint.restore_last", {"confirm_global_undo": True})
        except BridgeError as error:
            assert not error.context["execution_started"] and error.context["undo_steps_completed"] == 0
        else:
            raise AssertionError("Guard budget was ignored")
        assert inspected_x() == 1 and bpy.context.scene.get(MARKER_KEY) == marker
        assert manager._window.position == position
        undo()
        assert inspected_x() == 0
        bpy.context.preferences.edit.undo_steps = 128
        status = call("checkpoint.list")["recovery"]
        assert status["checkpoints"][0]["checkpoint_id"] == named["checkpoint_id"]
        assert status["checkpoints"][0]["availability"] == "expired", status

        # Finalizing a pending edit interval can itself consume the last retained
        # target. Refusal must retain that prior mutation evidence, not claim no work.
        manager.clear()
        bpy.context.preferences.edit.undo_steps = 2
        entered = call("context.set_mode", object_name="Cube", mode="EDIT")
        assert entered["operation"]["undo_group"]["state"] == "deferred"
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="OBJECT")
        # Internal setup intentionally defers the dispatcher's usual eager finalization.
        manager.create("After manual mode exit")
        manager.create("Before delayed finalization")
        try:
            undo()
        except BridgeError as error:
            assert error.context["undo_group"]["state"] == "finalized", error.to_dict()
            assert error.context["execution_started"] and error.context["undo_boundary_finalized"]
            assert not error.context["scene_undo_performed"]
            assert error.context["expired_operations_pruned_since_clear"] == 1
        else:
            raise AssertionError("Expired group target was reported recovered")
        assert inspected_x() == 0 and bpy.context.mode == "OBJECT"
        unchanged(protected_snapshot)
        # Mode entry intentionally selects its explicit target. Restore that
        # fixture-only context before the remaining independent recovery cases.
        call("selection.set", object_names=initial_selection, active_object=initial_active)

        manager.clear()
        bpy.context.preferences.edit.undo_steps = 2
        set_x(1)
        for value in range(10, 18):
            bpy.data.objects["Cube"].location.x = value
            bpy.ops.ed.undo_push(message="Manual interleaving fixture")
        bpy.data.objects["Cube"].location.x = 42  # Unsnapshotted manual work.
        status = call("bridge.status")["agent"]["recovery"]
        assert status["latest_operation"]["availability"] == "unverified"
        try:
            undo()
        except BridgeError as error:
            assert error.context["return_to_guard_verified"], error.to_dict()
        else:
            raise AssertionError("Unobserved manual eviction was reported restored")
        assert inspected_x() == 42

        manager.clear()
        bpy.context.preferences.edit.undo_steps = 32
        bpy.data.objects["Cube"].location.x = 0
        set_x(1)
        position = manager._window.position
        prefs.allow_transform_objects = False
        try:
            set_x(2)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Live permissions were bypassed")
        finally:
            prefs.allow_transform_objects = True
        for field, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            getattr(runtime.state, f"set_{field}")(True)
            try:
                undo()
            except BridgeError as error:
                assert error.code == code
            else:
                raise AssertionError("Remote recovery bypassed stop state")
            finally:
                getattr(runtime.state, f"set_{field}")(False)
                runtime.state.set_paused(False)
        assert manager._window.position == position and inspected_x() == 1
        undo()
        assert inspected_x() == 0
        unchanged(baseline)
        assert sorted(obj.name for obj in bpy.context.selected_objects) == initial_selection
        assert bpy.context.view_layer.objects.active.name == initial_active
        assert bpy.context.mode == "OBJECT"
        after_image = capture()
        assert bpy.context.preferences.edit.undo_steps == factory_limit
        print("BLENDER_UNDO_CAPACITY_OK " + json.dumps({
            "blender": bpy.app.version_string, "capacity_cases": summaries,
            "known_expiry_pruned": True, "guard_budget_refused_without_navigation": True,
            "expired_target_not_resurrected_by_preference_increase": True,
            "editor_finalization_evidence_survives_expiry": True,
            "manual_eviction_unverified_then_returned_to_guard": True,
            "live_permission_and_remote_stop_gates": True,
            "protected_scope_and_selection_verified": True,
            "captures": [before_image, after_image],
            "project_saved": False, "user_preferences_saved": False,
            "full_recovery_acceptance_verified": False,
        }), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
