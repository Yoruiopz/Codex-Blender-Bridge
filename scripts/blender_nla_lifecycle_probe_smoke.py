"""Private UI probe for real native NLA transitions and identity-preserving reorder.

Disposable factory data only. Run through run_blender_checks.py, never directly.
"""
from __future__ import annotations

import json
import traceback

import bpy


def key(owner):
    return int(owner.as_pointer())


def strip_state(strip):
    result = {}
    for prop in strip.bl_rna.properties:
        if prop.is_readonly:
            continue
        value = getattr(strip, prop.identifier)
        result[prop.identifier] = key(value) if prop.type == "POINTER" and value is not None else list(value) if getattr(prop, "is_array", False) else value
    return result


def main():
    try:
        assert not bpy.app.background
        bpy.context.preferences.use_preferences_save = False
        scene = bpy.context.scene
        target = bpy.data.objects.new("NLA Probe Target", None)
        protected = bpy.data.objects.new("NLA Probe Protected", None)
        for obj in (target, protected):
            scene.collection.objects.link(obj)
            obj.animation_data_create()
        def action(name, value):
            target.location.x = value
            for frame in (1, 11):
                target.keyframe_insert("location", index=0, frame=frame)
            result = target.animation_data.action
            result.name = name
            slot = getattr(target.animation_data, "action_slot", None)
            target.animation_data.action = None
            return result, slot
        first, first_slot = action("NLA Probe A", 0.)
        second, second_slot = action("NLA Probe B", 10.)
        tracks = target.animation_data.nla_tracks
        allocation_facts = []
        def new_track(previous=None):
            before = [(key(track), track.select) for track in tracks]
            active_before = key(tracks.active) if tracks.active is not None else None
            result = tracks.new(prev=previous) if previous is not None else tracks.new()
            allocation_facts.append({"kind": "track", "selected_before": before, "active_before": active_before,
                                     "selected_after": [(key(track), track.select) for track in tracks],
                                     "active_after": key(tracks.active) if tracks.active is not None else None,
                                     "created": key(result), "mute": result.mute, "solo": result.is_solo, "lock": result.lock})
            return result
        a = new_track()
        a.name = "A Motion"
        b = new_track(a)
        b.name = "B Empty"
        c = new_track(b)
        c.name = "C Empty"
        def clip(track, name, start, source, slot):
            result = track.strips.new(name, start, source)
            allocation_facts.append({"kind": "clip", "created": key(result), "select": result.select,
                                     "active": result.active, "name": result.name, "frame_start": result.frame_start,
                                     "frame_end": result.frame_end, "action_frame_start": result.action_frame_start,
                                     "action_frame_end": result.action_frame_end, "scale": result.scale, "repeat": result.repeat,
                                     "blend_type": result.blend_type, "extrapolation": result.extrapolation,
                                     "influence": result.influence, "mute": result.mute,
                                     "action_slot": key(result.action_slot) if result.action_slot is not None else None,
                                     "fcurves": len(result.fcurves), "modifiers": len(result.modifiers)})
            if slot is not None:
                result.action_slot = slot
            result.extrapolation = "NOTHING"
            return result
        left = clip(a, "Left", 1, first, first_slot)
        right = clip(a, "Right", 21, second, second_slot)
        for index, source, slot in ((0, first, first_slot), (1, second, second_slot)):
            track = protected.animation_data.nla_tracks.new()
            track.name = f"Protected {index}"
            clip(track, f"Protected Clip {index}", 1, source, slot)
            track.select = True
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        target.select_set(True)
        protected.select_set(True)
        bpy.context.view_layer.objects.active = protected
        original_selected = {key(obj) for obj in bpy.context.selected_objects}
        protected_before = [(key(track), track.name, [(key(strip), strip.name, key(strip.action)) for strip in track.strips])
                            for track in protected.animation_data.nla_tracks]
        area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
        area.type = "NLA_EDITOR"  # Fixture setup only; product will require an existing editor.
        region = next(region for region in area.regions if region.type == "WINDOW")
        space = area.spaces.active
        print("NLA_NATIVE_API " + json.dumps({
            "allocation_facts": allocation_facts,
            "strips_functions": list(a.strips.bl_rna.functions.keys()),
            "tracks_functions": list(tracks.bl_rna.functions.keys()),
            "nla_operators": [name for name in dir(bpy.ops.nla) if any(part in name for part in ("transition", "track", "move"))],
            "channel_move_directions": [item.identifier for item in bpy.ops.anim.channels_move.get_rna_type().properties["direction"].enum_items],
            "object_expansion_properties": [prop.identifier for prop in target.bl_rna.properties if "expanded" in prop.identifier],
            "strip_properties": [{"name": prop.identifier, "type": prop.type, "readonly": prop.is_readonly} for prop in left.bl_rna.properties],
        }, sort_keys=True), flush=True)
        protected.select_set(False)
        bpy.context.view_layer.objects.active = target
        space.dopesheet.show_only_selected = True
        if hasattr(target, "show_nla_expanded"):
            target.show_nla_expanded = True
        for track in tracks:
            track.select = track == a
            for strip in track.strips:
                strip.select = strip in (left, right)
        tracks.active = a
        original_clip_ids = [key(left), key(right)]
        with bpy.context.temp_override(window=bpy.context.window, area=area, region=region,
                                       object=target, active_object=target,
                                       selected_objects=[target], selected_editable_objects=[target]):
            assert bpy.ops.nla.transition_add.poll(), "transition_add poll failed"
            original_strip_settings = {key(strip): strip_state(strip) for strip in a.strips}
            status = bpy.ops.nla.transition_add()
            print("NLA_TRANSITION_RESULT " + json.dumps({"status": sorted(status), "strips": [
                {"id": key(strip), "name": strip.name, "type": strip.type,
                 "frame_start": strip.frame_start, "frame_end": strip.frame_end,
                 "selected": strip.select, "active": strip.active, "action": strip.action.name if strip.action else None} for strip in a.strips]}, sort_keys=True), flush=True)
            assert status == {"FINISHED"}
            transitions = [strip for strip in a.strips if strip.type == "TRANSITION"]
            assert len(transitions) == 1 and [key(strip) for strip in a.strips if strip.type == "CLIP"] == original_clip_ids
            transition = transitions[0]
            print("NLA_TRANSITION_CONSTRUCTOR " + json.dumps(strip_state(transition), sort_keys=True), flush=True)
            print("NLA_TRANSITION_EXISTING_FIELD_CHANGES " + json.dumps({str(key(strip)): {name: [old, strip_state(strip)[name]] for name, old in original_strip_settings[key(strip)].items() if old != strip_state(strip)[name]}
                 for strip in (left, right)}, sort_keys=True), flush=True)
            assert transition.frame_start == 11. and transition.frame_end == 21.
            measured = []
            for frame in (6, 11, 16, 21, 26):
                scene.frame_set(frame)
                measured.append([frame, target.evaluated_get(bpy.context.evaluated_depsgraph_get()).location.x])
            print("NLA_TRANSITION_MOTION " + json.dumps(measured), flush=True)
            assert abs(measured[0][1]) < 1e-5 and abs(measured[2][1]-5.) < 1e-5 and abs(measured[4][1]-10.) < 1e-5
            before = [key(track) for track in tracks]
            strip_ids = {key(track): [key(strip) for strip in track.strips] for track in tracks}
            for track in tracks:
                track.select = track == b
                for strip in track.strips:
                    strip.select = False
            tracks.active = b
            before_move_settings = {key(strip): strip_state(strip) for strip in a.strips}
            assert bpy.ops.anim.channels_move.poll(), "channels_move poll failed"
            result = bpy.ops.anim.channels_move(direction="UP")
            after = [key(track) for track in tracks]
            print("NLA_REORDER_EXISTING_FIELD_CHANGES " + json.dumps({str(key(strip)): {name: [old, strip_state(strip)[name]] for name, old in before_move_settings[key(strip)].items() if old != strip_state(strip)[name]}
                 for strip in a.strips}, sort_keys=True), flush=True)
            print("NLA_REORDER_RESULT " + json.dumps({"status": sorted(result), "before": before, "after": after,
                                                       "names_after": [track.name for track in tracks]}, sort_keys=True), flush=True)
            assert result == {"FINISHED"} and before != after and set(before) == set(after)
            assert {key(track): [key(strip) for strip in track.strips] for track in tracks} == strip_ids
            result2 = bpy.ops.anim.channels_move(direction="DOWN")
            assert result2 == {"FINISHED"} and [key(track) for track in tracks] == before
            a.strips.remove(transition)
            assert [key(strip) for strip in a.strips] == original_clip_ids
            assert not left.use_animated_influence and len(left.fcurves) == 0
            left.influence = .75
            left.use_animated_influence = True
            assert len(left.fcurves) == 1
            influence_curve = left.fcurves[0]
            assert influence_curve.data_path == "influence" and influence_curve.array_index == 0
            assert len(influence_curve.keyframe_points) == 1 and len(influence_curve.modifiers) == len(influence_curve.sampled_points) == 0
            assert tuple(influence_curve.keyframe_points[0].co) == (1., .75)
            influence_state = {"curve": strip_state(influence_curve),
                               "key": strip_state(influence_curve.keyframe_points[0])}
            print("NLA_INFLUENCE_NATIVE_ALLOCATION " + json.dumps({
                "new_control": influence_state,
                "preferences": {prop.identifier: getattr(bpy.context.preferences.edit, prop.identifier)
                                for prop in bpy.context.preferences.edit.bl_rna.properties
                                if any(text in prop.identifier for text in ("keyframe_new", "fcurve_new"))},
            }, sort_keys=True), flush=True)
            influence_id = key(influence_curve)
            left.use_animated_influence = False
            assert len(left.fcurves) == 1 and key(left.fcurves[0]) == influence_id
            left.use_animated_influence = True
            assert len(left.fcurves) == 1 and key(left.fcurves[0]) == influence_id
            assert {"curve": strip_state(influence_curve), "key": strip_state(influence_curve.keyframe_points[0])} == influence_state

        protected_after = [(key(track), track.name, [(key(strip), strip.name, key(strip.action)) for strip in track.strips])
                           for track in protected.animation_data.nla_tracks]
        assert protected_after == protected_before
        protected.select_set(True)
        bpy.context.view_layer.objects.active = protected
        assert {key(obj) for obj in bpy.context.selected_objects} == original_selected
        print("BLENDER_NLA_LIFECYCLE_PROBE_OK " + json.dumps({
            "blender": bpy.app.version_string, "native_transition_type_verified": True,
            "transition_evaluated_motion": measured, "transition_removed_by_data_api": True,
            "track_reorder_native_operator": "anim.channels_move", "native_track_strip_identities_preserved": True,
            "other_selected_animated_owner_unchanged": True, "shared_actions_read_only": True,
            "native_influence_curve_allocation_reuse_retention_verified": True,
            "headless_support_verified": False, "full_animation_acceptance_verified": False,
        }, sort_keys=True), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(main, first_interval=1.)
