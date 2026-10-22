"""Disposable native Action-version and F-curve authoring acceptance fixture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy  # type: ignore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError, ErrorCode  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import animation, animation_curves  # noqa: E402


def main() -> None:
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {item.value: True for item in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    runtime.registry.enable_toolset("animation")
    runtime.registry.enable_toolset("animation_layers")
    obj = bpy.data.objects.new("CurveActor", None)
    protected = bpy.data.objects.new("ProtectedActor", None)
    playback = bpy.data.objects.new("NLAPlayback", None)
    for item in (obj, protected, playback):
        bpy.context.scene.collection.objects.link(item)
    try:
        for frame, value in ((1, 0), (11, 10)):
            obj.location.x = value
            runtime.dispatch("animation.keyframe_insert", {"object_name": obj.name, "data_path": "location", "index": 0, "frame": frame})
        runtime.dispatch("animation.keyframe_insert", {"object_name": obj.name, "data_path": "location", "index": 1, "frame": 1})
        source = obj.animation_data.action
        protected.animation_data_create().action = source
        if hasattr(obj.animation_data, "action_slot"):
            protected.animation_data.action_slot = obj.animation_data.action_slot
        source_state = animation.inspect_animation(None, {"object_name": protected.name})
        active = bpy.context.view_layer.objects.active
        selected = [item.name for item in bpy.context.selected_objects]
        frame_before = bpy.context.scene.frame_current_final
        try:
            runtime.dispatch("animation.curve_edit", {"object_name": obj.name, "data_path": "location", "index": 0, "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
        except BridgeError as error:
            assert error.code == ErrorCode.NOT_IMPLEMENTED
        else:
            raise AssertionError("Shared Action must remain protected")
        copied = runtime.dispatch("animation.action_copy", {"object_name": obj.name, "new_name": "IndependentMotion"})
        assert copied["independent_version"] and obj.animation_data.action != source
        assert protected.animation_data.action == source
        edited = runtime.dispatch("animation.curve_edit", {
            "object_name": obj.name, "data_path": "location", "index": 0, "extrapolation": "CONSTANT",
            "keyframes": [{"frame": 1, "interpolation": "LINEAR"}],
        })
        curves, _ = animation_curves._slot_curves(obj.animation_data, obj.animation_data.action, None)
        curve = next(item for item in curves if item.data_path == "location" and item.array_index == 0)
        assert abs(curve.evaluate(6) - 5) < 1e-5
        other_before = [(tuple(point.co), point.interpolation) for other in curves if other.array_index == 1 for point in other.keyframe_points]
        runtime.dispatch("animation.curve_edit", {
            "object_name": obj.name, "data_path": "location", "index": 0,
            "keyframes": [
                {"frame": 1, "interpolation": "BEZIER", "handle_left_type": "FREE", "handle_right_type": "FREE", "handle_left": [0, 0], "handle_right": [4, 0]},
                {"frame": 11, "handle_left_type": "FREE", "handle_right_type": "FREE", "handle_left": [8, 10], "handle_right": [12, 10]},
            ],
        })
        assert abs(curve.evaluate(6) - 5) < 1e-4
        runtime.dispatch("animation.curve_edit", {"object_name": obj.name, "data_path": "location", "index": 0, "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
        assert abs(curve.evaluate(6)) < 1e-5
        original_check = animation_curves._Boundary.check
        native_recovery = []
        for scenario in ("KNOWN_FAILURE", "PAUSE", "PERMISSION", "MANUAL_KEY"):
            fired = False
            prior = [animation_curves._point_state(point) for point in curve.keyframe_points]

            def after_write(boundary, scenario=scenario):
                nonlocal fired
                result = original_check(boundary)
                if not fired and boundary.curve == curve and curve.extrapolation == "LINEAR":
                    fired = True
                    if scenario == "KNOWN_FAILURE":
                        raise RuntimeError("Injected known native curve failure")
                    if scenario == "PAUSE":
                        runtime.state.set_paused(True)
                    elif scenario == "PERMISSION":
                        grants[Permission.EDIT_ANIMATION.value] = False
                    else:
                        curve.keyframe_points[0].interpolation = "BEZIER"
                    return original_check(boundary)
                return result

            animation_curves._Boundary.check = after_write
            try:
                runtime.dispatch("animation.curve_edit", {"object_name": obj.name, "data_path": "location", "extrapolation": "LINEAR",
                    "keyframes": [{"frame": 1, "interpolation": "LINEAR"}]})
            except BridgeError as error:
                assert fired
                if scenario == "KNOWN_FAILURE":
                    assert error.context["rollback_verified"] and not error.context["possible_mutation"], error.context
                    assert curve.extrapolation == "CONSTANT"
                    assert [animation_curves._point_state(point) for point in curve.keyframe_points] == prior
                else:
                    assert not error.context["rollback_verified"] and error.context["possible_mutation"], error.context
                    assert curve.extrapolation == "LINEAR"
                    assert curve.keyframe_points[0].interpolation == ("BEZIER" if scenario == "MANUAL_KEY" else "CONSTANT")
                native_recovery.append({"scenario": scenario, "rollback_verified": error.context["rollback_verified"],
                                        "possible_mutation": error.context["possible_mutation"]})
            else:
                raise AssertionError("Native curve fault was hidden: " + scenario)
            finally:
                animation_curves._Boundary.check = original_check
                runtime.state.set_paused(False)
                grants[Permission.EDIT_ANIMATION.value] = True
            runtime.dispatch("animation.curve_edit", {"object_name": obj.name, "data_path": "location", "extrapolation": "CONSTANT",
                "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
        assert [(tuple(point.co), point.interpolation) for other in curves if other.array_index == 1 for point in other.keyframe_points] == other_before
        assert animation.inspect_animation(None, {"object_name": protected.name}) == source_state
        assert bpy.context.view_layer.objects.active == active
        assert [item.name for item in bpy.context.selected_objects] == selected
        assert bpy.context.scene.frame_current_final == frame_before
        runtime.dispatch("nla.add_strip", {
            "object_name": playback.name, "track_name": "ReviewedMotion", "strip_name": "MotionClip",
            "action_name": obj.animation_data.action.name, "frame_start": 1,
        })
        bpy.context.scene.frame_set(6)
        bpy.context.view_layer.update()
        assert abs(playback.location.x) < 1e-5
        assert protected.animation_data.action == source
        print("BLENDER_CODEX_ANIMATION_CURVES_SMOKE_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "independent_action": copied["action"],
            "linear_midpoint": 5.0, "constant_midpoint": float(playback.location.x),
            "source_action_preserved": True, "nla_playback_verified": True,
            "native_recovery": native_recovery,
            "full_animation_acceptance_verified": False, "slot_identifier": edited["slot_identifier"],
        }, sort_keys=True))
    finally:
        for item in (playback, protected, obj):
            bpy.data.objects.remove(item, do_unlink=True)


if __name__ == "__main__":
    main()
