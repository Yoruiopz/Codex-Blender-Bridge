"""Measure denied public artist entries in an isolated, owned desktop scene.

This research probe never admits protected capture and never installs a raw
Base reader in production. Run only through run_blender_checks.py.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

SOURCE_REFS = {
    (4, 5, 14): "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
    (5, 2, 2): "d13f752e3b9c4f8c261cda552b1021f8bcc0382c",
}
MARKER = "BLENDER_ARTIST_PUBLIC_ENTRY_PROBE_OK "


def raw_selection(layer):
    # Exact Release research witness: the collection filters raw Base flags.
    # Its C accessor has a debug assertion, and it is not a full Base witness.
    return sorted(obj.name for obj in layer.objects.selected)


def object_state(obj):
    """Literal channels and tiny geometry; no active/selection/visibility getters."""
    return {
        "object_pointer": obj.as_pointer(),
        "data_pointer": obj.data.as_pointer(),
        "location": list(obj.location),
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": list(obj.rotation_euler),
        "rotation_quaternion": list(obj.rotation_quaternion),
        "rotation_axis_angle": list(obj.rotation_axis_angle),
        "scale": list(obj.scale),
        "delta_location": list(obj.delta_location),
        "delta_rotation_euler": list(obj.delta_rotation_euler),
        "delta_rotation_quaternion": list(obj.delta_rotation_quaternion),
        "delta_scale": list(obj.delta_scale),
        "hide_viewport": obj.hide_viewport,
        "hide_render": obj.hide_render,
        "hide_select": obj.hide_select,
        "vertices": [list(vertex.co) for vertex in obj.data.vertices],
        "edges": [list(edge.vertices) for edge in obj.data.edges],
        "polygons": [list(polygon.vertices) for polygon in obj.data.polygons],
        "materials": [None if item is None else item.as_pointer() for item in obj.data.materials],
    }


def main():
    import blender_codex_bridge
    from blender_codex_bridge.checkpoints import MARKER_KEY, CheckpointManager
    from blender_codex_bridge.errors import BridgeError
    from blender_codex_bridge.permissions import Permission, PermissionManager
    from blender_codex_bridge.runtime import get_runtime
    from blender_codex_bridge.task_plans import get_task_plans
    from blender_codex_bridge.tools import _artist_checkpoint_admission, artist_loop
    from blender_codex_bridge.tools._object_rna_mutation import Boundary
    from blender_codex_bridge.tools._scene_checkpoint_roles import Plan

    assert threading.current_thread() is threading.main_thread()
    assert not bpy.app.background and not bpy.data.filepath
    source_ref = SOURCE_REFS[tuple(bpy.app.version)]
    build_hash = bpy.app.build_hash.decode("ascii")
    build_type = bpy.app.build_type.decode("ascii")
    assert len(build_hash) >= 12 and source_ref.startswith(build_hash), build_hash
    assert build_type == "Release", build_type
    assert sys.getprofile() is None, "A pre-existing profiler is outside this owned fixture."
    assert {obj.name for obj in bpy.data.objects} == {"Cube", "Camera", "Light"}
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.edit.use_global_undo = True
    blender_codex_bridge.register()
    runtime = get_runtime()
    runtime.registry.enable_toolset("objects")
    grants = {
        permission.value: permission
        not in {
            Permission.EXECUTE_PYTHON,
            Permission.DELETE_OBJECTS,
            Permission.SAVE_PROJECT,
            Permission.ACCESS_EXTERNAL_FILES,
        }
        for permission in Permission
    }
    active_measurement = [None]
    scene, window, layer = bpy.context.scene, bpy.context.window, bpy.context.view_layer

    def event(label):
        measurement = active_measurement[0]
        if measurement is not None:
            assert len(measurement["events"]) < 64
            measurement["events"].append(
                {"event": label, "raw_selected": raw_selection(layer)}
            )

    def provider():
        measurement = active_measurement[0]
        if measurement is not None:
            # The first operation here is the reviewed raw observation; no
            # context getter or native update precedes the denied grant set.
            event("permission_provider")
            measurement["provider_calls"] += 1
            values = dict(grants)
            values[Permission.TRANSFORM_OBJECTS.value] = False
            return values
        return dict(grants)

    manager = PermissionManager(provider)
    runtime.permissions = runtime.executor.permissions = manager
    call = runtime.dispatch
    mesh = bpy.data.meshes.new("Public Entry Working Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh.update()
    work = bpy.data.objects.new("Public Entry Working Prop", mesh)
    scene.collection.objects.link(work)
    protected = bpy.data.objects["Cube"]

    def select_work():
        work.hide_set(False, view_layer=layer)
        layer.update()
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False, view_layer=layer)
        work.select_set(True, view_layer=layer)
        layer.objects.active = work
        layer.update()
        assert bpy.context.mode == "OBJECT" and layer.objects.active == work
        assert raw_selection(layer) == [work.name]

    select_work()
    plan = call(
        "task.plan.set",
        {
            "goal": "Research denied public entries while preserving Cube",
            "steps": [{"id": "place", "description": "Measure admission without applying a transform"}],
            "protected_objects": [protected.name],
        },
    )
    revision = plan["plan"]["revision"]
    captured = call(
        "task.plan.capture",
        {"fields": ["transforms", "hierarchy", "mesh_geometry", "material_slots"]},
    )
    assert captured["baseline"]["coverage_complete"]
    armed = call("task.plan.enforce", {"enabled": True, "expected_revision": revision})
    assert armed["protected_scope_enforced"]
    store = get_task_plans(runtime.state)
    original_protection = store.protection
    original_baseline_owner = store.baseline
    original_baseline = copy.deepcopy(store.baseline)
    original_generation = store.protection_generation
    protected_before = object_state(protected)
    work_before = object_state(work)
    code_events = {
        _artist_checkpoint_admission.factory.__code__: "admission_factory",
        artist_loop._context.__code__: "artist_context_reader",
        Boundary._session.__code__: "boundary_session_reader",
        Plan._read.__code__: "checkpoint_role_reader",
        CheckpointManager.before_modification.__code__: "checkpoint_before_modification",
        CheckpointManager._snapshot.__code__: "checkpoint_snapshot",
    }
    for method in ("transform.set", "transform.apply", "task.plan.apply_preview"):
        code_events[runtime.registry.get(method).handler.__code__] = "handler:" + method

    def profiler(frame, kind, _argument):
        if kind == "call" and active_measurement[0] is not None:
            label = code_events.get(frame.f_code)
            if label is not None:
                measurement = active_measurement[0]
                measurement["calls"][label] = measurement["calls"].get(label, 0) + 1
                event(label)

    def checkpoint_state():
        checkpoint = runtime.checkpoints
        return {
            "tracked_native_position": checkpoint._window.position,
            "sequence": checkpoint._sequence,
            "pending": checkpoint._pending is not None,
            "editor_session": checkpoint._editor_session is not None,
            "scene_marker": scene.get(MARKER_KEY),
        }

    def context_without_sync():
        return {
            "window": window.as_pointer(),
            "window_scene": window.scene.as_pointer(),
            "scene": scene.as_pointer(),
            "window_view_layer": window.view_layer.as_pointer(),
            "view_layer": layer.as_pointer(),
            "frame": scene.frame_current,
            "subframe": scene.frame_subframe,
            "bridge_flags": {
                name: runtime.state.snapshot()[name] for name in ("paused", "emergency_stopped")
            },
        }

    results = []

    def measure(label, method, params, *, pending_hidden):
        select_work()
        before_context = context_without_sync()
        before_checkpoint = checkpoint_state()
        before_history = {item["operation_id"] for item in runtime.state.history(50)}
        measurement = {
            "case": label,
            "method": method,
            "params": params,
            "pending_hidden_setup": pending_hidden,
            "setup_active_object": work.name,
            "setup_mode": "OBJECT",
            "events": [],
            "calls": {},
            "provider_calls": 0,
        }
        if pending_hidden:
            # Last setup writer; no synced reader may run before dispatch.
            work.hide_set(True, view_layer=layer)
        measurement["raw_selected_before_dispatch"] = raw_selection(layer)
        assert measurement["raw_selected_before_dispatch"] == [work.name]
        active_measurement[0] = measurement
        error = None
        try:
            sys.setprofile(profiler)
            try:
                call(method, params)
            except BridgeError as caught:
                error = caught.to_dict()
        finally:
            sys.setprofile(None)
            active_measurement[0] = None
        # This must precede any post-denial synchronizing inspection.
        measurement["raw_selected_after_denial"] = raw_selection(layer)
        measurement["error"] = error
        measurement["checkpoint_before"] = before_checkpoint
        measurement["checkpoint_after"] = checkpoint_state()
        measurement["context_before"] = before_context
        measurement["context_after_without_sync"] = context_without_sync()
        measurement["work_after"] = object_state(work)
        measurement["protected_after"] = object_state(protected)
        measurement["new_history"] = [
            item for item in runtime.state.history(50) if item["operation_id"] not in before_history
        ]
        factory = [item for item in measurement["events"] if item["event"] == "admission_factory"]
        providers = [item for item in measurement["events"] if item["event"] == "permission_provider"]
        measurement["raw_selected_at_first_factory"] = None if not factory else factory[0]["raw_selected"]
        measurement["raw_selected_at_first_provider"] = None if not providers else providers[0]["raw_selected"]
        measurement["selection_changed_before_first_provider"] = (
            None if not providers else providers[0]["raw_selected"] != measurement["raw_selected_before_dispatch"]
        )
        measurement["checkpoint_snapshot_entries"] = measurement["calls"].get("checkpoint_snapshot", 0)
        measurement["bridge_native_push_attempts"] = (
            0 if measurement["checkpoint_snapshot_entries"] == 0 else None
        )
        measurement["bridge_native_push_completions"] = (
            measurement["checkpoint_after"]["tracked_native_position"]
            - before_checkpoint["tracked_native_position"]
        )
        measurement["native_push_count_basis"] = (
            "sole bridge undo_push callsite is CheckpointManager._snapshot; "
            "zero snapshot entries plus unchanged tracked native position; "
            "not global native history introspection"
        )
        print("ARTIST_PUBLIC_ENTRY_OBSERVATION " + json.dumps(measurement), flush=True)
        results.append(measurement)
        assert error is not None, measurement
        assert measurement["provider_calls"] >= 1, measurement
        factory_count = measurement["calls"].get("admission_factory", 0)
        assert (factory_count == 0) if method == "transform.apply" else (factory_count >= 1)
        assert all(not key.startswith("handler:") for key in measurement["calls"]), measurement
        assert measurement["calls"].get("checkpoint_before_modification", 0) == 0, measurement
        assert measurement["bridge_native_push_attempts"] == measurement["bridge_native_push_completions"] == 0
        assert measurement["checkpoint_after"] == before_checkpoint
        assert measurement["context_after_without_sync"] == before_context
        assert measurement["work_after"] == work_before
        assert measurement["protected_after"] == protected_before
        assert store.protection is original_protection
        assert store.baseline is original_baseline_owner and store.baseline == original_baseline
        assert store.protection_generation == original_generation
        # Deliberate inspection outside the measured interval. In the control
        # this can itself clear pending selection; retain that distinction.
        layer.update()
        measurement["post_measurement_explicit_update_context"] = {
            "mode": bpy.context.mode,
            "active": layer.objects.active.name,
            "hidden": work.hide_get(view_layer=layer),
            "raw_selected": raw_selection(layer),
        }
        assert layer.objects.active == work and bpy.context.mode == "OBJECT"

    measure(
        "denied_without_admission_factory",
        "transform.apply",
        {"object_name": work.name, "scale": True},
        pending_hidden=True,
    )
    measure(
        "denied_guarded_transform_set",
        "transform.set",
        {"object_name": work.name, "location": [4.0, 5.0, 6.0]},
        pending_hidden=True,
    )
    select_work()
    reference = call("task.reference.resolve", {"source": "selection"})["reference_id"]
    preview = call(
        "task.plan.preview_transform",
        {
            "reference_id": reference,
            "expected_revision": revision,
            "location": [7.0, 8.0, 9.0],
            "step_id": "place",
        },
    )
    assert not preview["scene_edited"] and not preview["authority_granted"]
    apply_params = {"preview_id": preview["preview_id"], "expected_revision": revision}
    measure("denied_current_preview_synchronized_control", "task.plan.apply_preview", apply_params, pending_hidden=False)
    assert preview["preview_id"] in store.previews
    measure("denied_preview_after_pending_hide", "task.plan.apply_preview", apply_params, pending_hidden=True)
    select_work()
    assert object_state(protected) == protected_before and object_state(work) == work_before
    assert not bpy.data.filepath and not bpy.context.preferences.use_preferences_save
    evidence = Path(tempfile.gettempdir()) / "artist-public-entry-probe-evidence"
    evidence.mkdir(exist_ok=False)
    receipt = evidence / "public-entry-observations.json"
    payload = {
        "blender": bpy.app.version_string,
        "build_hash": build_hash,
        "build_type": build_type,
        "source_ref": source_ref,
        "main_thread_single_timer_turn_no_yield": True,
        "entry_route": "BridgeRuntime.dispatch -> MainThreadExecutor -> actual ToolRegistry",
        "registered_specs_handlers_factories_or_checkpoint_callbacks_replaced": False,
        "counter_method": "Python profile call events for retained exact code objects",
        "protected_object": protected.name,
        "working_object": work.name,
        "protected_before_all_cases": protected_before,
        "work_before_all_cases": work_before,
        "plan_id": store.plan["plan_id"],
        "plan_revision": revision,
        "protection_generation": original_generation,
        "baseline_before": original_baseline,
        "baseline_after": copy.deepcopy(store.baseline),
        "protected_baseline_changed_or_replaced": False,
        "all_requested_transforms_and_protected_geometry_unchanged": True,
        "all_handler_checkpoint_and_bridge_native_push_counts_zero": True,
        "selection_outcome_prescribed": False,
        "observations": results,
        "production_remediation_qualified": False,
        "project_saved": False,
        "user_preferences_saved": False,
    }
    receipt.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        MARKER
        + json.dumps(
            {
                **{key: value for key, value in payload.items() if key != "observations"},
                "case_count": len(results),
                "case_errors": {item["case"]: item["error"]["code"] for item in results},
                "selection_changed_before_first_provider": {
                    item["case"]: item["selection_changed_before_first_provider"] for item in results
                },
                "receipt": str(receipt),
                "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            }
        ),
        flush=True,
    )
    runtime.emergency_stop()


def run():
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        sys.setprofile(None)
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
