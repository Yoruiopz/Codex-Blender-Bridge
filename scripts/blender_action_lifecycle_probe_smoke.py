"""Disposable direct-RNA Action/slot/retention probe; runner only, no public tools."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
from blender_codex_bridge.tools import _animation_scope  # noqa: E402


def main() -> None:
    scene = bpy.context.scene
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    actor, protected = (bpy.data.objects.new(label, None) for label in ("Action Probe Actor", "Action Probe Protected"))
    scene.collection.objects.link(actor)
    scene.collection.objects.link(protected)
    action = bpy.data.actions.new("Action Probe Source")
    slot = action.slots.new("OBJECT", "Actor")
    other_slot = action.slots.new("OBJECT", "Protected")
    layer = action.layers.new("Layer")
    keystrip = layer.strips.new(type="KEYFRAME")
    for chosen, values in ((slot, (0., 10.)), (other_slot, (50., 60.))):
        bag = keystrip.channelbag(chosen, ensure=True)
        curve = bag.fcurves.new(data_path="location", index=0)
        for frame, value in zip((1., 11.), values, strict=True):
            point = curve.keyframe_points.insert(frame, value)
            point.interpolation = "LINEAR"
        curve.update()

    def users(value):
        direct = bpy.data.user_map(subset={value}).get(value, ())
        return {"users": value.users, "fake_user": value.use_fake_user,
                "direct": [{"name": owner.name, "type": owner.bl_rna.identifier,
                            "references": owner.user_of_id(value)} for owner in direct]}

    def slots(value):
        return [{"identifier": item.identifier, "handle": item.handle, "target_id_type": item.target_id_type,
                 "users": [owner.name for owner in item.users()] if hasattr(item, "users") else None} for item in value.slots]

    unbound_users = users(action)
    actor.animation_data_create().action = action
    automatic_slot = getattr(actor.animation_data.action_slot, "identifier", None)
    actor.animation_data.action_slot = slot
    protected.animation_data_create().action = action
    protected.animation_data.action_slot = other_slot
    shared_users, original_slots = users(action), slots(action)
    values = []
    for frame in (1, 6, 11):
        scene.frame_set(frame)
        values.append([actor.location.x, protected.location.x])
    assert values == [[0., 50.], [5., 55.], [10., 60.]], values
    copied = action.copy()
    copied.name = "Action Probe Copy"
    copied_slot = next(item for item in copied.slots if item.identifier == slot.identifier)
    actor.animation_data.action = copied
    automatic_copy_slot = getattr(actor.animation_data.action_slot, "identifier", None)
    actor.animation_data.action_slot = copied_slot
    assert copied_slot.as_pointer() != slot.as_pointer()
    source_after_copy, copied_slots = users(action), slots(copied)
    assert _animation_scope.action_content(action) == _animation_scope.action_content(copied)
    assert _animation_scope.action_users(bpy, action)["real_users"] == 1
    for frame, expected in zip((1, 6, 11), values, strict=True):
        scene.frame_set(frame)
        assert [actor.location.x, protected.location.x] == expected
    track = actor.animation_data.nla_tracks.new()
    track.name = "Probe NLA"
    clip = track.strips.new("Probe Clip", 1, action)
    clip.action_slot = slot
    referenced_by_active_and_nla = users(action)
    actor.animation_data.nla_tracks.remove(track)
    actor.animation_data.action = None
    clear_slot = getattr(actor.animation_data.action_slot, "identifier", None)
    assert clear_slot is None
    assert users(copied)["users"] == 0
    blocked_in_use = False
    try:
        bpy.data.actions.remove(action, do_unlink=False)
    except RuntimeError:
        blocked_in_use = True
    assert blocked_in_use and protected.animation_data.action == action
    protected.animation_data.action = None
    assert action.users == 0
    bpy.data.actions.remove(action, do_unlink=False)
    assert bpy.data.actions.get("Action Probe Source") is None
    kept, lost = bpy.data.actions.new("Probe Retained"), bpy.data.actions.new("Probe Session Only")
    kept.use_fake_user = True
    retained_counts, session_counts = users(kept), users(lost)
    evidence = {"blender": bpy.app.version_string, "layered_action": copied.is_action_layered,
                "legacy_action": copied.is_action_legacy, "automatic_slot": automatic_slot,
                "automatic_copy_slot": automatic_copy_slot, "slot_after_clear": clear_slot,
                "original_slots": original_slots, "copied_slots": copied_slots,
                "unbound_users": unbound_users, "shared_users": shared_users,
                "source_after_copy": source_after_copy, "source_active_and_nla": referenced_by_active_and_nla,
                "retained_counts": retained_counts, "session_only_counts": session_counts,
                "sampled_motion": values, "copy_slot_identity_independent": True,
                "in_use_remove_without_unlink_refused": blocked_in_use}
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    path = Path(tempfile.gettempdir()) / "action-lifecycle-probe.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    assert bpy.data.actions.get("Probe Retained") is not None and bpy.data.actions.get("Probe Session Only") is None
    evidence.update(same_process_save_reopen_retention_verified=True, fresh_process_reopen_verified=False,
                    product_workflow_verified=False, full_character_acceptance_verified=False)
    print("BLENDER_CODEX_ACTION_LIFECYCLE_PROBE_OK " + json.dumps(evidence), flush=True)


main()
