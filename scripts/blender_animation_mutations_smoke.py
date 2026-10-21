"""Disposable four legacy animation mutations: live gates and measured native state."""

from __future__ import annotations

import json
import math
import sys
import uuid
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _animation_mutation as mutation  # noqa: E402
from blender_codex_bridge.tools import _animation_scope as scope  # noqa: E402


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    permissions = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = permissions
    runtime.registry.enable_toolset("animation")
    scene = bpy.context.scene
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    original_frame = scene.frame_current_final
    original_range = {"start": scene.frame_start, "end": scene.frame_end, "use_preview": scene.use_preview_range,
                      "preview_start": scene.frame_preview_start, "preview_end": scene.frame_preview_end}
    preview_probe = []
    assert not scene.use_preview_range and (scene.frame_preview_start, scene.frame_preview_end) == (0, 0)
    scene.use_preview_range = True
    preview_probe.append({"operation": "ENABLE_FACTORY_UNSET_PREVIEW", "main": [scene.frame_start, scene.frame_end],
                          "preview": [scene.frame_preview_start, scene.frame_preview_end], "enabled": scene.use_preview_range})
    scene.use_preview_range = False
    scene.frame_preview_start, scene.frame_preview_end = 0, 0
    preview_probe.append({"operation": "RESTORE_DISABLED_ZERO_SENTINEL", "main": [scene.frame_start, scene.frame_end],
                          "preview": [scene.frame_preview_start, scene.frame_preview_end], "enabled": scene.use_preview_range})
    assert not scene.use_preview_range and (scene.frame_preview_start, scene.frame_preview_end) == (0, 0)
    scene.frame_start, scene.frame_end = 0, 10
    scene.use_preview_range = True
    preview_probe.append({"operation": "ENABLE_ZERO_BASED_MAIN_WITH_ZERO_SENTINEL", "main": [scene.frame_start, scene.frame_end],
                          "preview": [scene.frame_preview_start, scene.frame_preview_end], "enabled": scene.use_preview_range})
    scene.frame_preview_start, scene.frame_preview_end = 0, 0
    preview_probe.append({"operation": "CONFIGURE_ENABLED_ZERO_PREVIEW", "main": [scene.frame_start, scene.frame_end],
                          "preview": [scene.frame_preview_start, scene.frame_preview_end], "enabled": scene.use_preview_range})
    assert scene.use_preview_range and (scene.frame_preview_start, scene.frame_preview_end) == (0, 0)
    scene.use_preview_range = True
    preview_probe.append({"operation": "REDUNDANT_ENABLE_REINITIALIZES_ZERO_PREVIEW", "main": [scene.frame_start, scene.frame_end],
                          "preview": [scene.frame_preview_start, scene.frame_preview_end], "enabled": scene.use_preview_range})
    scene.use_preview_range = False
    scene.frame_start, scene.frame_end = original_range["start"], original_range["end"]
    scene.frame_preview_start, scene.frame_preview_end = 0, 0
    print("ANIMATION_NATIVE_PREVIEW_SENTINEL_PROBE " + json.dumps(preview_probe), flush=True)

    def empty(name):
        owner = bpy.data.objects.new(name, None)
        scene.collection.objects.link(owner)
        return owner

    actor, protected = empty("Typed Keyframe Actor"), empty("Protected Keyframe Owner")
    protected.location = (51., 52., 53.)
    protected_before = [list(row) for row in protected.matrix_basis]

    def call(method, **params):
        return runtime.dispatch("animation." + method, params)

    def execute(method, params, callback):
        response = runtime.executor.execute_request(Request(id="mutation_" + uuid.uuid4().hex, method="animation." + method, params=params),
                                                    check_cancelled=callback)
        assert not response.ok and response.error is not None, response
        return response.error

    def curve(obj, path="location", index=0):
        action = None if obj.animation_data is None else obj.animation_data.action
        if action is None:
            return None
        handle = getattr(getattr(obj.animation_data, "action_slot", None), "handle", None)
        matches = [item for bag_handle, item in scope.curve_inventory(action)
                   if bag_handle == handle and item.data_path == path and item.array_index == index]
        assert len(matches) <= 1
        return matches[0] if matches else None

    def point(obj, frame, path="location", index=0):
        channel = curve(obj, path, index)
        if channel is None:
            return None
        matches = [key for key in channel.keyframe_points if abs(key.co.x-frame) < 1e-6]
        assert len(matches) <= 1
        return matches[0] if matches else None

    def key(obj, frame, index=0, group="Motion"):
        return call("keyframe_insert", object_name=obj.name, data_path="location", index=index, frame=frame,
                    group=group, affected_objects=[])

    first = call("set_frame", frame=1.25)
    assert first["global_scene_evaluation"] and abs(scene.frame_current_final-1.25) < 1e-6
    zero_preview = call("set_range", start=0, end=10, use_preview=True, preview_start=0, preview_end=0)
    assert zero_preview["use_preview_range"] and (zero_preview["preview_start"], zero_preview["preview_end"]) == (0, 0)
    native_ranges = []
    original_write = mutation.Timeline.write

    def measured_range_write(boundary, field, value):
        before = boundary.observe()
        try:
            return original_write(boundary, field, value)
        finally:
            native_ranges.append({"field": field, "value": value, "before": before, "after": boundary.observe()})

    mutation.Timeline.write = measured_range_write
    try:
        assert call("set_range", start=1, end=40, use_preview=True, preview_start=2, preview_end=30)["preview_end"] == 30
    finally:
        mutation.Timeline.write = original_write
        print("ANIMATION_NATIVE_RANGE_TRANSITIONS " + json.dumps(native_ranges), flush=True)
    actor.location.x = 2.
    assert key(actor, 1.)["requested_key_values_verified"]
    actor.location.x = 10.
    assert key(actor, 11.)["requested_key_values_verified"]
    actor.location.y = 7.
    key(actor, 1., 1, "Protected")
    actor.location.y = 9.
    key(actor, 11., 1, "Protected")
    protected_curve = scope.curve_content(curve(actor, index=1))
    call("set_frame", frame=6.)
    assert math.isclose(actor.location.x, 6., abs_tol=1e-5)
    actor.location.x = 99.
    inserted = key(actor, 20.5)
    assert inserted["inserted"] and inserted["requested_key_values_verified"]
    assert math.isclose(point(actor, 20.5).co.y, 99., abs_tol=1e-6)
    assert scope.curve_content(curve(actor, index=1)) == protected_curve

    actor.location.z = 4.
    key(actor, 1., 2, "Only This Component")
    assert curve(actor, index=2).group.name == "Only This Component"
    last = call("keyframe_delete", object_name=actor.name, data_path="location", index=2, frame=1.,
                group="Only This Component", affected_objects=[])
    assert last["deleted"] and curve(actor, index=2) is None
    assert scope.curve_content(curve(actor, index=1)) == protected_curve
    deleted = call("keyframe_delete", object_name=actor.name, data_path="location", index=0, frame=20.5, group="Motion", affected_objects=[])
    assert deleted["deleted"] and point(actor, 20.5) is None
    assert scope.curve_content(curve(actor, index=1)) == protected_curve

    # Live revocation between the first and second range setter must not trigger
    # a late second write or compensation after authorization is gone.
    range_stops = []
    for stopped_by in ("PERMISSION", "PAUSE", "EMERGENCY_STOP", "CALLER_CANCEL"):
        call("set_range", start=1, end=40)

        def range_stop(*, stopped_by=stopped_by):
            if scene.frame_start != 10:
                return
            if stopped_by == "PERMISSION":
                grants[Permission.EDIT_ANIMATION.value] = False
            elif stopped_by == "PAUSE":
                runtime.state.set_paused(True)
            elif stopped_by == "EMERGENCY_STOP":
                runtime.state.set_emergency_stopped(True)
            else:
                from blender_codex_bridge.errors import BridgeError
                raise BridgeError("OPERATION_FAILED", "Injected caller cancellation")

        error = execute("set_range", {"start": 10, "end": 30}, range_stop)
        assert scene.frame_start == 10 and scene.frame_end == 40
        assert error["context"]["possible_mutation"] and not error["context"]["rollback_verified"]
        range_stops.append({"stopped_by": stopped_by, "retained_range": [scene.frame_start, scene.frame_end]})
        grants[Permission.EDIT_ANIMATION.value] = True
        runtime.state.set_paused(False)
        runtime.state.set_emergency_stopped(False)
    call("set_range", start=1, end=40)
    fired = []

    def fail_once():
        if scene.frame_start == 10 and not fired:
            fired.append(True)
            raise RuntimeError("One-shot native timeline failure")

    error = execute("set_range", {"start": 10, "end": 30}, fail_once)
    assert fired and error["context"]["rollback_verified"] and not error["context"]["possible_mutation"]
    assert (scene.frame_start, scene.frame_end) == (1, 40)

    # Keyframe operators are one native blocking call. A postwrite cancellation
    # retains its measured result; recovery uses a separate authorized request.
    actor.location.x = 123.

    def cancel_inserted():
        if point(actor, 22.25) is not None:
            from blender_codex_bridge.errors import BridgeError
            raise BridgeError("OPERATION_FAILED", "Injected caller cancellation")

    error = execute("keyframe_insert", {"object_name": actor.name, "data_path": "location", "index": 0,
                                       "frame": 22.25, "group": "Motion", "affected_objects": []}, cancel_inserted)
    assert error["context"]["possible_mutation"] and not error["context"]["rollback_verified"]
    assert math.isclose(point(actor, 22.25).co.y, 123., abs_tol=1e-6)
    assert scope.curve_content(curve(actor, index=1)) == protected_curve
    call("keyframe_delete", object_name=actor.name, data_path="location", index=0, frame=22.25, group="Motion", affected_objects=[])
    assert point(actor, 22.25) is None

    # Native success alone must not authorize foreign new-Action schema, fake
    # retention, missing requested keys or wrong requested values.
    anomalies = []
    for anomaly in ("FAKE_USER", "EXTRA_SLOT", "WRONG_VALUE", "MISSING_KEY"):
        owner = empty("Adversarial Keyframe " + anomaly)
        owner.location.x = 3.
        changed = []

        def alter_new_action(*, owner=owner, anomaly=anomaly, changed=changed):
            action = None if owner.animation_data is None else owner.animation_data.action
            if action is None or changed:
                return
            chosen = point(owner, 1.)
            if chosen is None:
                return
            changed.append(True)
            if anomaly == "FAKE_USER":
                action.use_fake_user = True
            elif anomaly == "EXTRA_SLOT":
                extra = action.slots.new("OBJECT", "Foreign")
                bag = action.layers[0].strips[0].channelbag(extra, ensure=True)
                foreign = bag.fcurves.new(data_path="location", index=0)
                foreign.keyframe_points.insert(1., 777.)
            elif anomaly == "WRONG_VALUE":
                chosen.co.y = 888.
            else:
                curve(owner).keyframe_points.remove(chosen)

        error = execute("keyframe_insert", {"object_name": owner.name, "data_path": "location", "index": 0,
                                           "frame": 1., "group": "Motion", "affected_objects": []}, alter_new_action)
        assert changed and error["context"]["possible_mutation"] and not error["context"]["rollback_verified"]
        action = owner.animation_data.action
        if anomaly == "FAKE_USER":
            assert action.use_fake_user
        elif anomaly == "EXTRA_SLOT":
            assert len(action.slots) == 2
        elif anomaly == "WRONG_VALUE":
            assert point(owner, 1.).co.y == 888.
        else:
            assert point(owner, 1.) is None
        anomalies.append({"anomaly": anomaly, "native_success_rejected": True, "foreign_state_retained": True})

    actor.location.x = 111.
    original_group = curve(actor).group
    old_color = original_group.color_set
    changed = []

    def alter_group():
        if point(actor, 25.) is not None and not changed:
            changed.append(True)
            original_group.color_set = "THEME02" if old_color != "THEME02" else "THEME03"

    error = execute("keyframe_insert", {"object_name": actor.name, "data_path": "location", "index": 0,
                                       "frame": 25., "group": "Motion", "affected_objects": []}, alter_group)
    assert changed and error["context"]["possible_mutation"] and not error["context"]["rollback_verified"]
    assert original_group.color_set != old_color and point(actor, 25.) is not None
    assert scope.curve_content(curve(actor, index=1)) == protected_curve
    original_group.color_set = "CUSTOM"
    old_custom = tuple(original_group.colors.normal)
    changed_custom = []

    def alter_custom_colors():
        if point(actor, 26.) is not None and not changed_custom:
            changed_custom.append(True)
            original_group.colors.normal = (.11, .23, .37) if old_custom != (.11, .23, .37) else (.9, .8, .7)

    error = execute("keyframe_insert", {"object_name": actor.name, "data_path": "location", "index": 0,
                                       "frame": 26., "group": "Motion", "affected_objects": []}, alter_custom_colors)
    assert changed_custom and error["context"]["possible_mutation"] and not error["context"]["rollback_verified"]
    assert tuple(original_group.colors.normal) != old_custom
    assert scope.curve_content(curve(actor, index=1)) == protected_curve

    conditional = empty("Conditional Component Actor")
    conditional.location = (2., 3., 4.)
    key(conditional, 1.)
    conditional.location.x = 5.
    available = call("keyframe_insert", object_name=conditional.name, data_path="location", frame=2., index=-1,
                     group="Motion", options=["INSERTKEY_AVAILABLE"], affected_objects=[])
    assert available["inserted"] and point(conditional, 2.).co.y == 5.
    assert curve(conditional, index=1) is None and curve(conditional, index=2) is None
    conditional.location.x = 6.
    replaced = call("keyframe_insert", object_name=conditional.name, data_path="location", frame=2., index=-1,
                    group="Motion", options=["INSERTKEY_REPLACE"], affected_objects=[])
    assert replaced["inserted"] and point(conditional, 2.).co.y == 6.
    needed = call("keyframe_insert", object_name=conditional.name, data_path="location", frame=3., index=-1,
                  group="Motion", options=["INSERTKEY_NEEDED"], affected_objects=[])
    assert needed["inserted"]
    assert point(conditional, 3., index=1).co.y == 3. and point(conditional, 3., index=2).co.y == 4.
    assert [list(row) for row in protected.matrix_basis] == protected_before
    restore = dict(original_range)
    if not restore["use_preview"]:
        restore.pop("preview_start")
        restore.pop("preview_end")
    call("set_range", **restore)
    # Owned fixture setup restores the factory's disabled sentinel, which the
    # public setter does not accept as a subrange of main frames1..250.
    if not original_range["use_preview"]:
        scene.frame_preview_start, scene.frame_preview_end = original_range["preview_start"], original_range["preview_end"]
    call("set_frame", frame=original_frame)
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    assert not grants[Permission.EXECUTE_PYTHON.value]
    print("BLENDER_ANIMATION_MUTATIONS_OK " + json.dumps({"blender": bpy.app.version_string,
        "four_legacy_mutators_verified": True, "sampled_motion": {"frame": 6., "location_x": 6.},
        "range_live_stops": range_stops, "range_measured_compensation": True,
        "initial_native_range_transitions": native_ranges,
        "preview_sentinel_probe": preview_probe,
        "requested_key_frame_value_and_deletion_verified": True, "postwrite_key_cancellation_retained_until_new_request": True,
        "new_action_anomalies": anomalies, "protected_group_metadata_change_rejected": True,
        "protected_nested_custom_group_colors_change_rejected": True, "last_component_curve_deletion_verified": True,
        "conditional_options": {"available": available["requested_keyframes"], "replace": replaced["requested_keyframes"],
                                "needed": needed["requested_keyframes"], "needed_omissions": needed.get("conditional_component_omissions")},
        "protected_curve_and_object_context_preserved": True, "arbitrary_python_enabled": False,
        "native_undo_verified": False, "project_saved": False, "full_character_acceptance_verified": False}), flush=True)


try:
    main()
finally:
    blender_codex_bridge.unregister()
