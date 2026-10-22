"""Disposable compatible object-driver API, live stops and measured recovery."""

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
    permissions = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = permissions
    runtime.registry.enable_toolset("animation_layers")
    scene = bpy.context.scene
    selection, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    scene_frame = (scene.frame_current, scene.frame_subframe)

    def empty(name):
        result = bpy.data.objects.new(name, None)
        scene.collection.objects.link(result)
        return result

    source, target, protected = (empty(name) for name in ("Object Driver Source", "Object Driver Target", "Protected Driver Object"))
    source.location.x, protected.location.x = 2.75, 91.
    protected_matrix = [list(row) for row in protected.matrix_basis]
    variable = {"object_name": source.name, "transform_type": "LOC_X", "transform_space": "WORLD_SPACE"}

    def add(obj=target, path="location", index=0):
        return runtime.dispatch("drivers.add", {"object_name": obj.name, "data_path": path, "index": index,
                                                "variables": [variable]})

    def remove(obj=target, path="location", index=0):
        return runtime.dispatch("drivers.remove", {"object_name": obj.name, "data_path": path, "index": index})

    grants[Permission.EDIT_ANIMATION.value] = False
    try:
        add()
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    else:
        raise AssertionError("Legacy driver bypassed permission denial")
    assert target.animation_data is None
    grants[Permission.EDIT_ANIMATION.value] = True
    result = add()
    assert result["added"] and not result["project_saved"]
    curve = rig_drivers._curve(target, "location", 0)
    assert curve.driver.type == "AVERAGE" and not curve.driver.use_self
    assert not len(curve.keyframe_points) and not len(curve.modifiers)
    assert math.isclose(target.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation.x, 2.75, abs_tol=1e-6)
    source.location.x = 4.
    bpy.context.view_layer.update()
    assert math.isclose(target.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation.x, 4., abs_tol=1e-6)
    original_curve = rig_drivers._driver_configuration(curve)
    original_data = target.animation_data.as_pointer()
    original_check = rig_drivers._check
    stops = []

    for stopped_by in ("PERMISSION", "PAUSE", "EMERGENCY_STOP", "CALLER_CANCEL"):
        retained = []

        def stop_after_native(context, *, stopped_by=stopped_by, retained=retained):
            original_check(context)
            current = rig_drivers._curve(target, "scale", 2)
            if current is None:
                return
            if not retained:
                retained.append(rig_drivers._driver_configuration(current))
            if stopped_by == "PERMISSION":
                grants[Permission.EDIT_ANIMATION.value] = False
            elif stopped_by == "PAUSE":
                runtime.state.set_paused(True)
            elif stopped_by == "EMERGENCY_STOP":
                runtime.state.set_emergency_stopped(True)
            else:
                raise BridgeError("OPERATION_FAILED", "Injected caller cancellation")

        rig_drivers._check = stop_after_native
        try:
            add(path="scale", index=2)
        except BridgeError as error:
            assert error.context["possible_mutation"] and not error.context["rollback_verified"]
            assert error.context["retained_driver_path"] == "scale" and error.context["retained_driver_index"] == 2
        else:
            raise AssertionError("Legacy driver ignored a live stop after native allocation")
        finally:
            rig_drivers._check = original_check
            grants[Permission.EDIT_ANIMATION.value] = True
            runtime.state.set_paused(False)
            runtime.state.set_emergency_stopped(False)
        current = rig_drivers._curve(target, "scale", 2)
        assert retained and rig_drivers._driver_configuration(current) == retained[0]
        stops.append({"stopped_by": stopped_by, "native_keys_retained": len(current.keyframe_points),
                      "native_modifiers_retained": len(current.modifiers), "no_late_setup_or_cleanup": True})
        assert rig_drivers._driver_configuration(curve) == original_curve
        assert target.animation_data.as_pointer() == original_data
        assert remove(path="scale", index=2)["removed"]

    # A foreign configuration edit after allocation is preserved rather than
    # absorbed as owned state or erased during automatic cleanup.
    manual = []

    def manual_after_native(context):
        original_check(context)
        current = rig_drivers._curve(target, "scale", 1)
        if current is not None and not manual:
            current.driver.type = "MAX"
            manual.append(rig_drivers._driver_configuration(current))

    rig_drivers._check = manual_after_native
    try:
        add(path="scale", index=1)
    except BridgeError as error:
        assert error.context["cleanup_skipped"] and not error.context["rollback_verified"]
    else:
        raise AssertionError("Legacy driver accepted an interleaved foreign edit")
    finally:
        rig_drivers._check = original_check
    assert manual and rig_drivers._driver_configuration(rig_drivers._curve(target, "scale", 1)) == manual[0]
    remove(path="scale", index=1)

    recovery = []
    new_owner = empty("New AnimData Retention Object")
    for owner in (target, new_owner):
        fired = []

        def fail_after_binding(context, *, owner=owner, fired=fired):
            original_check(context)
            current = rig_drivers._curve(owner, "scale", 0)
            if (current is not None and not fired and current.driver.variables
                    and current.driver.variables[0].targets[0].id == source):
                fired.append(True)
                raise RuntimeError("Injected one-shot postwrite failure")

        rig_drivers._check = fail_after_binding
        try:
            add(owner, "scale", 0)
        except BridgeError as error:
            assert fired and rig_drivers._curve(owner, "scale", 0) is None
            assert owner.animation_data is not None
            assert error.context["rollback_verified"] == (owner == target)
            assert error.context["possible_mutation"] == (owner == new_owner)
            assert error.context["retained_empty_anim_data"] == (owner == new_owner)
            recovery.append({"preexisting_animdata": owner == target, "curve_removed": True,
                             "rollback_verified": error.context["rollback_verified"],
                             "retained_empty_anim_data": error.context["retained_empty_anim_data"]})
        else:
            raise AssertionError("Injected legacy driver setup failure was hidden")
        finally:
            rig_drivers._check = original_check
    assert rig_drivers._driver_configuration(curve) == original_curve
    assert remove()["removed"] and not len(target.animation_data.drivers)
    assert [list(row) for row in protected.matrix_basis] == protected_matrix
    assert bpy.context.mode == "OBJECT" and list(bpy.context.selected_objects) == selection and bpy.context.view_layer.objects.active == active
    assert (scene.frame_current, scene.frame_subframe) == scene_frame
    print("BLENDER_CODEX_OBJECT_DRIVERS_OK " + json.dumps({"blender": bpy.app.version_string,
        "compatible_typed_api_and_sampled_transform_verified": True, "native_mapping_keys_removed": result["native_mapping_keyframes_removed"],
        "live_stop_evidence": stops, "interleaved_manual_configuration_preserved": True,
        "measured_recovery": recovery, "protected_driver_and_object_context_preserved": True,
        "native_undo_verified": False, "full_character_acceptance_verified": False, "project_saved": False}), flush=True)


try:
    main()
finally:
    blender_codex_bridge.unregister()
