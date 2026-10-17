"""Structured mode/mesh/recovery workflow in a disposable interactive Blender."""

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
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def run():
    try:
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {p.value: True for p in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        runtime.registry.enable_toolset("interaction")
        runtime.registry.enable_toolset("mesh")
        runtime.registry.enable_toolset("objects")
        cube = bpy.data.objects["Cube"]
        protected = cube.copy()
        protected.data = cube.data.copy()
        protected.name = "Protected Mesh"
        protected.location.x = 3.0
        bpy.context.scene.collection.objects.link(protected)
        protected.select_set(True)
        selected_before = sorted(obj.name for obj in bpy.context.selected_objects)
        active_before = bpy.context.view_layer.objects.active.name
        original = runtime.dispatch("scene.snapshot", {"object_names": [cube.name, protected.name]})
        runtime.dispatch("transform.set", {"object_name": cube.name, "location": [0.25, 0, 0]})
        before = runtime.dispatch("scene.snapshot", {"object_names": [cube.name, protected.name]})
        checkpoint = runtime.dispatch("checkpoint.create", {"description": "Structured modeling"})
        entry = runtime.dispatch("context.set_mode", {"object_name": cube.name, "mode": "EDIT"})
        assert runtime.checkpoints.list()[0]["checkpoint_id"] == checkpoint["checkpoint_id"]
        assert entry["operation"]["undo_group"]["state"] == "deferred"
        group_id = entry["operation"]["undo_group"]["group_id"]
        assert runtime.dispatch("bridge.status")["agent"]["undo_group"]["group_id"] == group_id
        grants[Permission.EDIT_MESH.value] = False
        try:
            runtime.dispatch(
                "mesh.extrude_selected", {"object_name": cube.name, "offset": [0, 0, 1]}
            )
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Edit session bypassed permission revocation")
        grants[Permission.EDIT_MESH.value] = True
        for stopped in ("paused", "emergency_stopped"):
            getattr(runtime.state, f"set_{stopped}")(True)
            try:
                runtime.dispatch("context.set_mode", {"object_name": cube.name, "mode": "OBJECT"})
            except BridgeError as error:
                assert error.code == (
                    "AGENT_PAUSED" if stopped == "paused" else "EMERGENCY_STOPPED"
                )
            else:
                raise AssertionError("Stopped bridge accepted a mode change")
            finally:
                getattr(runtime.state, f"set_{stopped}")(False)
                runtime.state.set_paused(False)
            assert runtime.checkpoints.editor_session_status()["group_id"] == group_id
        page = runtime.dispatch(
            "mesh.components_inspect",
            {
                "object_name": cube.name,
                "element_type": "FACE",
                "max_items": 6,
            },
        )
        top = next(item["index"] for item in page["items"] if item["normal_local"][2] > 0.9)
        selection = runtime.dispatch(
            "mesh.select_components",
            {
                "object_name": cube.name,
                "element_type": "FACE",
                "indices": [top],
                "selection_id": page["selection"]["mesh_selection"]["selection_id"],
            },
        )
        edit = runtime.dispatch(
            "mesh.extrude_selected",
            {
                "object_name": cube.name,
                "offset": [0.0, 0.0, 0.25],
                "selection_id": selection["selection"]["mesh_selection"]["selection_id"],
            },
        )
        assert edit["mesh_counts_after"]["vertices"] > edit["mesh_counts_before"]["vertices"]
        assert edit["operation"]["undo_group"]["state"] == "deferred"
        exit_result = runtime.dispatch(
            "context.set_mode", {"object_name": cube.name, "mode": "OBJECT"}
        )
        assert exit_result["operation"]["undo_boundary_finalized"]
        assert exit_result["operation"]["undo_group"]["state"] == "finalized"
        changed = runtime.dispatch("scene.compare", {"snapshot_id": before["snapshot_id"]})
        assert changed["status"] == "changed" and changed["coverage_complete"]
        assert {item["object"] for item in changed["changes"]} == {cube.name}
        restored = runtime.dispatch(
            "checkpoint.undo_last",
            {
                "confirm_global_undo": True,
                "restore_snapshot": True,
            },
        )
        assert (
            restored["snapshot_marker_verified"]
            and restored["recovered_scope"] == "mesh_edit_session"
        )
        after = runtime.dispatch("scene.compare", {"snapshot_id": before["snapshot_id"]})
        assert after["status"] == "unchanged_within_scope" and after["coverage_complete"]
        assert bpy.context.mode == "OBJECT"
        assert sorted(obj.name for obj in bpy.context.selected_objects) == selected_before
        assert bpy.context.view_layer.objects.active.name == active_before
        assert runtime.checkpoints.list()[0]["checkpoint_id"] == checkpoint["checkpoint_id"]
        # A failed tool inside the editor keeps its pre-session point available.
        import bmesh

        runtime.dispatch("context.set_mode", {"object_name": "Cube", "mode": "EDIT"})

        def partial_failure(_context, _params):
            mesh = bmesh.from_edit_mesh(bpy.data.objects["Cube"].data)
            mesh.verts.ensure_lookup_table()
            mesh.verts[0].co.x += 0.125
            bmesh.update_edit_mesh(bpy.data.objects["Cube"].data)
            raise RuntimeError("injected editor mutation failure")

        runtime.registry.register(
            "fixture.editor_failure",
            partial_failure,
            modifies=True,
            permissions=(Permission.EDIT_MESH,),
        )
        try:
            runtime.dispatch("fixture.editor_failure")
        except BridgeError as error:
            assert (
                error.context["execution_started"]
                and error.context["undo_group"]["state"] == "deferred"
            )
        else:
            raise AssertionError("Injected editor failure succeeded")
        runtime.dispatch("context.set_mode", {"object_name": "Cube", "mode": "OBJECT"})
        assert runtime.dispatch(
            "checkpoint.undo_last",
            {
                "confirm_global_undo": True,
                "restore_snapshot": True,
            },
        )["snapshot_marker_verified"]
        assert (
            runtime.dispatch("scene.compare", {"snapshot_id": before["snapshot_id"]})["status"]
            == "unchanged_within_scope"
        )
        prior = runtime.dispatch(
            "checkpoint.undo_last",
            {
                "confirm_global_undo": True,
                "restore_snapshot": True,
            },
        )
        assert prior["recovered_scope"] == "operation"
        assert (
            runtime.dispatch("scene.compare", {"snapshot_id": original["snapshot_id"]})["status"]
            == "unchanged_within_scope"
        )
        blender_codex_bridge.unregister()
        print(
            "BLENDER_MESH_EDIT_RECOVERY_OK "
            + json.dumps(
                {
                    "blender": bpy.app.version_string,
                    "structured_mode_edit_recovery_verified": True,
                    "protected_mesh_and_materials_unchanged": True,
                    "selection_active_mode_restored": True,
                    "named_checkpoint_retained": True,
                    "permission_pause_and_emergency_gates_verified": True,
                    "partial_editor_failure_recovered": True,
                    "earlier_object_operation_recovers_separately": True,
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
