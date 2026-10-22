"""Disposable typed control/driver fixture with evaluated pose and skin evidence."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import rig_drivers  # noqa: E402


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: True for permission in Permission}
    manager = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("rigging")
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active

    def call(tool_name, **params):
        return runtime.dispatch("rig." + tool_name, params)

    control_name, control_property = 'Control"A', 'move"X'
    rig_name = "Typed Driver Rig"
    call("create", name=rig_name, root_bone_name=control_name, root_head=[0, 0, 0], root_tail=[0, 1, 0])
    call("bone_update", object_name=rig_name, bone_name=control_name, use_deform=False)
    call("bone_add", object_name=rig_name, bone_name="Deform", head=[0, 1, 0], tail=[0, 2, 0], parent_name=control_name)
    for bone_name in (control_name, "Deform"):
        call("pose_transform", object_name=rig_name, bone_name=bone_name, rotation_euler=[0, 0, 0])
    rig = bpy.data.objects[rig_name]
    protected = rig.copy()
    protected.name = "Protected Shared Rig Data"
    bpy.context.scene.collection.objects.link(protected)
    data = bpy.data.meshes.new("Driver Skin")
    data.from_pydata([(0, 1.25, 0), (1, 1.25, 0), (0, 1.75, 0)], [], [(0, 1, 2)])
    mesh = bpy.data.objects.new("Driver Skin", data)
    bpy.context.scene.collection.objects.link(mesh)
    call("bind_mesh", mesh_object=mesh.name, armature_object=rig_name, method="EMPTY_GROUPS", parent=False)
    mesh.vertex_groups["Deform"].add([0, 1, 2], 1.0, "REPLACE")

    def evaluated():
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        evaluated_mesh = mesh.evaluated_get(graph)
        geometry = evaluated_mesh.to_mesh()
        try:
            points = [list(vertex.co) for vertex in geometry.vertices]
        finally:
            evaluated_mesh.to_mesh_clear()
        return points, rig.evaluated_get(graph).pose.bones["Deform"].matrix.translation.x

    original_points, original_x = evaluated()
    assert original_x == 0
    call("property_set", object_name=rig_name, bone_name=control_name, property_name=control_property, value=0.0, create=True)
    source = {"kind": "PROPERTY", "object_name": rig_name, "bone_name": control_name, "property_name": control_property}
    original_normalize = rig_drivers._normalize_new_driver_mapping
    native_mappings = []

    def record_native_mapping(curve):
        record = {"type": curve.driver.type, "use_self": curve.driver.use_self, "expression": curve.driver.expression,
                  "keyframes": [{"co": list(point.co), "interpolation": point.interpolation,
                                 "handle_left": list(point.handle_left), "handle_right": list(point.handle_right),
                                 "handle_left_type": point.handle_left_type, "handle_right_type": point.handle_right_type} for point in list(curve.keyframe_points)[:16]],
                  "sample_count": len(curve.sampled_points), "extrapolation": curve.extrapolation,
                  "modifiers": [modifier.type for modifier in curve.modifiers],
                  "variables": [{"name": variable.name, "type": variable.type, "target_count": len(variable.targets)} for variable in curve.driver.variables]}
        count = original_normalize(curve)
        assert len(curve.keyframe_points) == 0
        record["removed_mapping_keys"] = count
        native_mappings.append(record)
        return count

    rig_drivers._normalize_new_driver_mapping = record_native_mapping
    try:
        added = call("driver_add", object_name=rig_name, bone_name="Deform", channel="location", index=0, variables=[source])
    finally:
        rig_drivers._normalize_new_driver_mapping = original_normalize
    assert added["driver"]["driver_type"] == "AVERAGE" and mesh.name in added["affected_objects"]
    curve = rig_drivers._curve(rig, rig_drivers._bone_path("Deform") + ".location", 0)
    assert len(curve.keyframe_points) == len(curve.sampled_points) == len(curve.modifiers) == 0
    assert added["native_mapping_keyframes_removed"] == native_mappings[0]["removed_mapping_keys"]
    # Existing identity mappings remain unsupported and are never normalized by a
    # property edit. This raw setup belongs only to the disposable native fixture.
    curve.keyframe_points.insert(0., 0.)
    curve.keyframe_points.insert(1., 1.)
    mapped_keys = [list(point.co) for point in curve.keyframe_points]
    try:
        call("property_set", object_name=rig_name, bone_name=control_name, property_name=control_property, value=2.)
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    else:
        raise AssertionError("Existing mapped driver was silently normalized")
    assert [list(point.co) for point in curve.keyframe_points] == mapped_keys
    assert rig.pose.bones[control_name][control_property] == 0
    curve.keyframe_points.clear()
    call("property_set", object_name=rig_name, bone_name=control_name, property_name=control_property, value=2.0)
    moved_points, moved_x = evaluated()
    assert math.isclose(moved_x, 2.0, abs_tol=1e-6), moved_x
    assert all(math.isclose(after[0]-before[0], 2.0, abs_tol=1e-6) for before, after in zip(original_points, moved_points, strict=True)), moved_points
    bpy.context.view_layer.update()
    assert protected.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones["Deform"].matrix.translation.x == 0
    assert protected.data == rig.data and len(rig.data.bones) == 2

    controller = bpy.data.objects.new("Independent Driver Control", None)
    controller.location.x = 1.25
    bpy.context.scene.collection.objects.link(controller)
    transform = {"kind": "TRANSFORM", "object_name": controller.name, "transform_type": "LOC_X", "transform_space": "WORLD_SPACE"}
    call("driver_add", object_name=rig_name, bone_name="Deform", channel="location", index=2, driver_type="SUM", variables=[transform])
    bpy.context.view_layer.update()
    assert math.isclose(rig.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones["Deform"].matrix.translation.z, 1.25, abs_tol=1e-6)
    call("driver_remove", object_name=rig_name, bone_name="Deform", channel="location", index=2)
    call("pose_transform", object_name=rig_name, bone_name="Deform", location=[2.0, 0.0, 0.0])

    try:
        call("driver_add", object_name=rig_name, bone_name=control_name, channel="rotation_euler", index=0,
             variables=[{"kind": "TRANSFORM", "object_name": rig_name, "bone_name": "Deform", "transform_type": "LOC_X", "transform_space": "WORLD_SPACE"}])
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT" and "cycle" in error.message
    else:
        raise AssertionError("Driver accepted descendant transform cycle")

    grants[Permission.EDIT_ANIMATION.value] = False
    try:
        call("property_set", object_name=rig_name, bone_name=control_name, property_name=control_property, value=5.0)
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    else:
        raise AssertionError("Control edit bypassed permission")
    assert rig.pose.bones[control_name][control_property] == 2.0
    grants[Permission.EDIT_ANIMATION.value] = True

    failure_path = rig_drivers._bone_path("Deform") + ".scale"
    original_check = rig_drivers._check

    def revoke_after_driver(context):
        original_check(context)
        if any(curve.data_path == failure_path and curve.array_index == 2 for curve in rig_drivers._curves(rig)):
            grants[Permission.EDIT_ANIMATION.value] = False

    rig_drivers._check = revoke_after_driver
    try:
        call("driver_add", object_name=rig_name, bone_name="Deform", channel="scale", index=2, variables=[source])
    except BridgeError as error:
        assert error.context["possible_mutation"] and not error.context["rollback_verified"]
        assert error.context["retained_driver_path"] == failure_path
    else:
        raise AssertionError("Post-allocation permission revocation was hidden")
    finally:
        rig_drivers._check = original_check
        grants[Permission.EDIT_ANIMATION.value] = True
    inspected = call("driver_inspect", object_name=rig_name, bone_name="Deform", channel="scale", index=2)
    assert inspected["driver"] is not None
    call("driver_remove", object_name=rig_name, bone_name="Deform", channel="scale", index=2)
    call("pose_transform", object_name=rig_name, bone_name="Deform", scale=[1, 1, 1])
    assert len(rig.animation_data.drivers) == 1

    # Stop after the native allocation exists, before mapping/variable setup.
    # The retained native state must survive both setup and recovery unchanged;
    # later authorized cleanup is a separate typed operation.
    stop_evidence = []
    for stopped_by in ("PAUSE", "EMERGENCY_STOP", "CALLER_CANCEL"):
        retained = []

        def stop_new_curve(context, *, retained=retained, stopped_by=stopped_by):
            original_check(context)
            current = rig_drivers._curve(rig, failure_path, 1)
            if current is None:
                return
            if not retained:
                retained.append(rig_drivers._driver_configuration(current))
            if stopped_by == "PAUSE":
                runtime.state.set_paused(True)
            elif stopped_by == "EMERGENCY_STOP":
                runtime.state.set_emergency_stopped(True)
            else:
                raise BridgeError("OPERATION_FAILED", "Injected caller cancellation")

        rig_drivers._check = stop_new_curve
        try:
            call("driver_add", object_name=rig_name, bone_name="Deform", channel="scale", index=1, variables=[source])
        except BridgeError as error:
            assert error.context["possible_mutation"] and not error.context["rollback_verified"]
            assert error.context["retained_driver_path"] == failure_path
        else:
            raise AssertionError("Post-allocation live stop was ignored")
        finally:
            rig_drivers._check = original_check
            runtime.state.set_paused(False)
            runtime.state.set_emergency_stopped(False)
        current = rig_drivers._curve(rig, failure_path, 1)
        assert retained and rig_drivers._driver_configuration(current) == retained[0]
        stop_evidence.append({"stopped_by": stopped_by, "native_keys_retained": len(current.keyframe_points),
                              "native_modifiers_retained": len(current.modifiers), "unchanged_after_stop": True})
        call("driver_remove", object_name=rig_name, bone_name="Deform", channel="scale", index=1)
        call("pose_transform", object_name=rig_name, bone_name="Deform", scale=[1, 1, 1])

    def pause_after_property(context):
        original_check(context)
        if rig.pose.bones[control_name][control_property] == 3.:
            runtime.state.set_paused(True)

    rig_drivers._check = pause_after_property
    try:
        call("property_set", object_name=rig_name, bone_name=control_name, property_name=control_property, value=3.)
    except BridgeError as error:
        assert error.context["possible_mutation"] and not error.context["rollback_verified"]
        assert rig.pose.bones[control_name][control_property] == 3.
    else:
        raise AssertionError("Postwrite pause allowed property compensation")
    finally:
        rig_drivers._check = original_check
        runtime.state.set_paused(False)
    call("property_set", object_name=rig_name, bone_name=control_name, property_name=control_property, value=0.0)
    restored_points, restored_x = evaluated()
    assert restored_x == 0 and restored_points == original_points, (restored_x, restored_points)
    call("driver_remove", object_name=rig_name, bone_name="Deform", channel="location", index=0)
    assert not len(rig.animation_data.drivers)
    assert bpy.context.mode == "OBJECT" and list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    print("BLENDER_RIG_DRIVERS_OK " + json.dumps({
        "blender": bpy.app.version_string, "typed_control_and_non_scripted_bone_drivers_verified": True,
        "evaluated_pose_translation_x": moved_x, "evaluated_skin_vertex_count": len(moved_points),
        "full_skin_displacement_and_control_restoration_verified": True,
        "quoted_bone_and_property_paths_verified": True, "transform_source_and_cycle_rejection_verified": True,
        "permission_revocation_retained_driver_and_explicit_cleanup_verified": True,
        "shared_armature_data_protected_pose_and_context_preserved": True,
        "fresh_native_driver_configurations": native_mappings,
        "fresh_native_identity_mapping_removed_only": True, "existing_keyframed_driver_preserved_and_rejected": True,
        "live_stops_preserve_partial_native_allocation": stop_evidence,
        "postwrite_pause_refuses_property_compensation": True,
        "explicit_partial_and_self_reference_driver_cleanup_verified": True,
        "native_undo_verified": False, "project_saved": False, "visual_quality_verified": False,
    }))


try:
    main()
finally:
    blender_codex_bridge.unregister()
