"""Disposable native typed NLA transitions, track ordering, permissions and recovery."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import animation_layers as legacy  # noqa: E402
from blender_codex_bridge.tools import nla_lifecycle as domain  # noqa: E402
from blender_codex_bridge.tools._animation_scope import action_content, digest, key  # noqa: E402


def main():
    try:
        assert not bpy.app.background
        bpy.context.preferences.use_preferences_save = False
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {permission.value: True for permission in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        runtime.registry.enable_toolset("animation_layers")
        scene = bpy.context.scene
        runtime.registry.enable_toolset("rigging")
        runtime.dispatch("rig.create", {"name": "NLA Typed Actor", "root_bone_name": "Root",
                         "root_head": [0., 0., 0.], "root_tail": [0., 1., 0.]})
        target = bpy.data.objects["NLA Typed Actor"]
        protected = bpy.data.objects.new("NLA Protected Actor", None)
        scene.collection.objects.link(protected)
        for obj in (target, protected):
            obj.animation_data_create()
        def action(name, value):
            target.location.x = value
            for frame in (1, 11):
                target.keyframe_insert("location", index=0, frame=frame)
            source = target.animation_data.action
            source.name = name
            slot = target.animation_data.action_slot
            target.animation_data.action = None
            return source, slot
        first, first_slot = action("NLA Typed Zero", 0.)
        second, second_slot = action("NLA Typed Ten", 10.)
        tracks = target.animation_data.nla_tracks
        for name in ("Motion", "Empty Middle", "Empty Top"):
            track = tracks.new(prev=tracks[-1]) if len(tracks) else tracks.new()
            track.name = name
        motion = tracks[0]
        for index, (source, slot) in enumerate(((first, first_slot), (second, second_slot))):
            track = protected.animation_data.nla_tracks.new()
            track.name = f"Protected {index}"
            strip = track.strips.new(f"Protected {index}", 1, source)
            strip.action_slot = slot
            track.select = True
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        target.select_set(True)
        protected.select_set(True)
        bpy.context.view_layer.objects.active = protected
        original_selected = sorted(obj.name for obj in bpy.context.selected_objects)
        original_active = bpy.context.view_layer.objects.active.name
        action_before = {source.name: digest(action_content(source)) for source in (first, second)}
        protected_before = [(key(track), track.name, [(key(strip), strip.name, key(strip.action)) for strip in track.strips])
                            for track in protected.animation_data.nla_tracks]
        def call(method, **params):
            return runtime.dispatch(method, {"object_name": target.name, "affected_objects": [], **params})
        grants[Permission.EDIT_ANIMATION.value] = False
        try:
            call("nla.clip_add", track_name=motion.name, strip_name="Denied", action_name=first.name,
                 frame_start=1, slot_identifier=first_slot.identifier)
            raise AssertionError("Edit permission denial bypassed")
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        assert len(motion.strips) == 0
        grants[Permission.EDIT_ANIMATION.value] = True
        for source, slot, name, start in ((first, first_slot, "Left", 1), (second, second_slot, "Right", 21)):
            result = call("nla.clip_add", track_name=motion.name, strip_name=name,
                          action_name=source.name, frame_start=start, slot_identifier=slot.identifier)
            assert result["added"] and result["action_channels_changed"] is False
            # Fixture explicitly sets non-overlapping clip extrapolation for the
            # evaluated transition benchmark; new clip API preserves native HOLD.
            motion.strips[name].extrapolation = "NOTHING"
        clip_ids = [key(strip) for strip in motion.strips]
        # Native operations fail closed without an existing NLA Editor.
        try:
            call("nla.transition_add", track_name=motion.name, left_strip="Left", right_strip="Right", new_name="Denied Editor")
            raise AssertionError("Transition created without an NLA Editor")
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED" and error.context["possible_mutation"] is False
        assert [key(strip) for strip in motion.strips] == clip_ids
        area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
        area.type = "NLA_EDITOR"  # Fixture setup; product never changes editor type.
        if hasattr(target, "show_nla_expanded"):
            target.show_nla_expanded = True
        result = call("nla.transition_add", track_name=motion.name, left_strip="Left", right_strip="Right", new_name="Blend")
        assert result["added"] and result["native_strip_type"] == "TRANSITION"
        assert [key(strip) for strip in motion.strips if strip.type == "CLIP"] == clip_ids
        assert sorted(obj.name for obj in bpy.context.selected_objects) == original_selected
        assert bpy.context.view_layer.objects.active.name == original_active
        sampled = []
        for frame in (6, 11, 16, 21, 26):
            scene.frame_set(frame)
            sampled.append([frame, target.evaluated_get(bpy.context.evaluated_depsgraph_get()).location.x])
        assert abs(sampled[0][1]) < 1e-5 and abs(sampled[2][1]-5.) < 1e-5 and abs(sampled[-1][1]-10.) < 1e-5
        track_ids = {track.name: key(track) for track in tracks}
        strip_ids = {track.name: [key(strip) for strip in track.strips] for track in tracks}
        desired = ["Empty Top", "Motion", "Empty Middle"]
        moved = call("nla.track_reorder", track_names=desired)
        assert moved["track_and_strip_identities_preserved"]
        assert [track.name for track in tracks] == desired
        assert {track.name: key(track) for track in tracks} == track_ids
        assert {track.name: [key(strip) for strip in track.strips] for track in tracks} == strip_ids
        assert sorted(obj.name for obj in bpy.context.selected_objects) == original_selected
        assert bpy.context.view_layer.objects.active.name == original_active
        # Legacy structured endpoints keep their reviewed isolated behavior and
        # now freeze scope at each real setter, including compensating writes.
        def old_call(method, **params):
            return runtime.dispatch(method, {"object_name": target.name, **params})
        old_call("nla.add_strip", track_name="Legacy Audit", strip_name="Legacy Walk",
                 action_name=first.name, frame_start=1, slot_identifier=first_slot.identifier)
        audit = tracks["Legacy Audit"]
        neighbor = tracks.new(prev=audit)
        neighbor.name = "Manual Neighbor"
        neighbor_clip = neighbor.strips.new("Manual Neighbor Clip", 7, second)
        neighbor_clip.action_slot = second_slot
        neighbor_clip.use_auto_blend = True
        neighbor_clip.blend_in = 0.  # Explicit manual tweak; global validation would rewrite it.
        before_blends = [(strip.name, strip.blend_in, strip.blend_out, strip.use_auto_blend)
                         for track in tracks for strip in track.strips]
        try:
            old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk", settings={"use_auto_blend": True})
            raise AssertionError("Automatic cross-strip rewrite was inferred")
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED"
        assert [(strip.name, strip.blend_in, strip.blend_out, strip.use_auto_blend)
                for track in tracks for strip in track.strips] == before_blends
        neighbor_clip.use_auto_blend = False  # Fixture explicit neighbor protection.
        old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk", settings={"use_auto_blend": True})
        assert audit.strips["Legacy Walk"].blend_out == 4.
        old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk",
                 settings={"scale": 2., "repeat": 2., "action_frame_end": 6.,
                           "influence": .25, "blend_in": 2., "blend_out": 3.})
        audit_strip = audit.strips["Legacy Walk"]
        assert audit_strip.frame_start == 1. and audit_strip.frame_end == 21.
        old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk",
                 settings={"frame_start": 2., "frame_end": 22.})
        assert audit_strip.frame_start == 2. and audit_strip.frame_end == 22.
        edit = bpy.context.preferences.edit
        preferences = (edit.fcurve_new_auto_smoothing, edit.keyframe_new_handle_type, edit.keyframe_new_interpolation_type)
        edit.fcurve_new_auto_smoothing, edit.keyframe_new_handle_type, edit.keyframe_new_interpolation_type = "NONE", "VECTOR", "LINEAR"
        old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk", settings={"use_animated_influence": True})
        influence = audit_strip.fcurves[0]
        assert tuple(influence.keyframe_points[0].co) == (2., .25)
        assert influence.keyframe_points[0].interpolation == "LINEAR" and influence.keyframe_points[0].handle_left_type == "VECTOR"
        control_id, control_hash = key(influence), digest(legacy.controls(audit_strip))
        old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk", settings={"use_animated_influence": False})
        assert len(audit_strip.fcurves) == 1 and key(audit_strip.fcurves[0]) == control_id
        old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk", settings={"use_animated_influence": True})
        assert key(audit_strip.fcurves[0]) == control_id and digest(legacy.controls(audit_strip)) == control_hash
        edit.fcurve_new_auto_smoothing, edit.keyframe_new_handle_type, edit.keyframe_new_interpolation_type = preferences
        control_track_order = [track.name for track in tracks]
        call("nla.track_reorder", track_names=list(reversed(control_track_order)))
        assert digest(legacy.controls(audit_strip)) == control_hash
        call("nla.track_reorder", track_names=control_track_order)
        assert digest(legacy.controls(audit_strip)) == control_hash
        old_call("nla.edit_strip", track_name=neighbor.name, strip_name=neighbor_clip.name, remove=True)
        old_call("nla.edit_track", track_name=neighbor.name, remove=True)
        old_call("nla.edit_track", track_name=audit.name, settings={"name": "Legacy Renamed", "mute": True})
        assert audit.name == "Legacy Renamed" and audit.mute
        old_call("nla.edit_track", track_name=audit.name, settings={"mute": False})
        old_call("nla.solo_track", track_name=audit.name, enabled=True)
        assert audit.is_solo
        old_call("nla.solo_track", track_name=audit.name, enabled=False)
        assert not audit.is_solo
        original_write = legacy._LegacyNlaGuard.write
        injected = False
        def revoke_after_first_field(self, expected, operation):
            nonlocal injected
            result = original_write(self, expected, operation)
            if not injected:
                injected = True
                grants[Permission.EDIT_ANIMATION.value] = False
            return result
        legacy._LegacyNlaGuard.write = revoke_after_first_field
        try:
            try:
                old_call("nla.edit_track", track_name=audit.name, settings={"mute": True, "lock": True})
                raise AssertionError("Late permission revocation hidden")
            except BridgeError as error:
                assert error.code == "PERMISSION_DENIED" and error.context["possible_mutation"]
                assert not error.context["rollback_verified"]
                assert audit.mute and not audit.lock
        finally:
            legacy._LegacyNlaGuard.write = original_write
            grants[Permission.EDIT_ANIMATION.value] = True
        old_call("nla.edit_track", track_name=audit.name, settings={"mute": False})
        old_call("nla.edit_strip", track_name=audit.name, strip_name="Legacy Walk", remove=True)
        assert len(audit.strips) == 0
        old_call("nla.edit_track", track_name=audit.name, remove=True)
        assert tracks.get("Legacy Renamed") is None
        # Push-down guards a pre-existing active binding, shared Action contents,
        # slot identity and Action user-count deltas without copying keyframes.
        push_actor = bpy.data.objects.new("NLA Pushdown Actor", None)
        scene.collection.objects.link(push_actor)
        push_actor.animation_data_create()
        push_actor.animation_data.action = first
        push_actor.animation_data.action_slot = first_slot
        pushed = runtime.dispatch("nla.push_down", {"object_name": push_actor.name,
                                   "track_name": "Pushdown", "strip_name": "Pushed"})
        assert pushed["pushed_action"] == first.name and push_actor.animation_data.action is None
        assert push_actor.animation_data.nla_tracks["Pushdown"].strips["Pushed"].action == first
        # One measured native reorder failure compensates while consent remains;
        # temporary editor selection is independently restored.
        original_operation = domain._Editor.operation
        did_fail = False
        def fail_after_move(self, operator, **kwargs):
            nonlocal did_fail
            result = original_operation(self, operator, **kwargs)
            if "direction" in kwargs and not did_fail:
                did_fail = True
                raise BridgeError("OPERATION_FAILED", "Fixture failure after native move")
            return result
        order_before_failure = [track.name for track in tracks]
        domain._Editor.operation = fail_after_move
        try:
            try:
                call("nla.track_reorder", track_names=list(reversed(order_before_failure)))
                raise AssertionError("Injected native reorder failure hidden")
            except BridgeError as error:
                assert error.context["original_order_restored"] and error.context["rollback_verified"]
                assert [track.name for track in tracks] == order_before_failure
        finally:
            domain._Editor.operation = original_operation
        assert sorted(obj.name for obj in bpy.context.selected_objects) == original_selected
        assert bpy.context.view_layer.objects.active.name == original_active
        # A last permission provider can invoke a native mode switch. No RNA
        # clip write may occur after that observed session change.
        bpy.context.view_layer.objects.active = target
        original_quiet, armed, mode_changed = domain._quiet_authority, False, False
        def mode_provider():
            nonlocal mode_changed
            if armed and not mode_changed:
                bpy.ops.object.mode_set(mode="POSE")
                mode_changed = True
            return grants
        def arm_last_provider(context, method):
            nonlocal armed
            armed = True
            return original_quiet(context, method)
        late_manager = PermissionManager(mode_provider)
        domain._quiet_authority = arm_last_provider
        runtime.permissions = runtime.executor.permissions = late_manager
        try:
            try:
                call("nla.clip_add", track_name=motion.name, strip_name="Mode Switch Denied",
                     action_name=first.name, frame_start=41, slot_identifier=first_slot.identifier)
                raise AssertionError("Mode switch after last provider permitted a clip write")
            except BridgeError as error:
                assert mode_changed and bpy.context.mode == "POSE"
                assert error.context["stale_nla_scope"] and not error.context["possible_mutation"]
                assert not error.context["context_restored"]
                assert motion.strips.get("Mode Switch Denied") is None
        finally:
            domain._quiet_authority = original_quiet
            runtime.permissions = runtime.executor.permissions = manager
            bpy.ops.object.mode_set(mode="OBJECT")  # Fixture explicitly restores its own injected change.
            bpy.context.view_layer.objects.active = protected
        # Removal is an explicit strip operation. Its finalized native checkpoint
        # is the identity-preserving recovery route; no strip recreation occurs.
        call("nla.transition_remove", track_name=motion.name, left_strip="Left", right_strip="Right",
             transition_name="Blend", confirm=True)
        assert [key(strip) for strip in motion.strips] == clip_ids
        restored = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert restored["snapshot_marker_verified"]
        # Native undo invalidates Python wrappers; reacquire exact saved names.
        target = bpy.data.objects["NLA Typed Actor"]
        protected = bpy.data.objects["NLA Protected Actor"]
        tracks = target.animation_data.nla_tracks
        motion = tracks["Motion"]
        assert motion.strips["Blend"].type == "TRANSITION"
        assert {source.name: digest(action_content(source)) for source in (bpy.data.actions["NLA Typed Zero"], bpy.data.actions["NLA Typed Ten"])} == action_before
        assert [(track.name, [(strip.name, strip.action.name) for strip in track.strips]) for track in protected.animation_data.nla_tracks] == [
            ("Protected 0", [("Protected 0", "NLA Typed Zero")]), ("Protected 1", [("Protected 1", "NLA Typed Ten")])]
        print("BLENDER_NLA_LIFECYCLE_OK "+json.dumps({
            "blender": bpy.app.version_string, "typed_tools": 4, "native_transition_motion": sampled,
            "complete_track_permutation_verified": True, "track_and_strip_ids_preserved_before_undo": True,
            "permission_denial_and_missing_editor_fail_closed": True,
            "other_selected_animated_owner_and_shared_action_contents_preserved": True,
            "native_checkpoint_transition_recovery_verified": True,
            "legacy_creation_timing_blending_track_solo_pushdown_verified": True,
            "automatic_own_blends_verified_cross_strip_rewrites_rejected_before_writes": True,
            "animated_influence_constructor_custom_preferences_reuse_retention_verified": True,
            "late_permission_revocation_retained_state_and_explicit_recovery_verified": True,
            "injected_native_reorder_failure_measured_compensation_verified": True,
            "last_permission_provider_native_pose_mode_switch_refused_before_clip_write": True,
            "project_saved": False, "visual_quality_verified": False,
            "full_animation_acceptance_verified": False,
            "protected_initial_native_ids": protected_before,
        }, sort_keys=True), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(main, first_interval=1.)
