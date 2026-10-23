"""Owned raw-curve numerical evidence; no scene playback, saving or rendering."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402

METHOD = "animation.curve_sample"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identity(owner):
    return None if owner is None else [int(owner.as_pointer()), getattr(owner, "name", getattr(owner, "identifier", ""))]


def scalar_rna(owner):
    """Independent stored scalar/array projection, never native curve evaluation."""
    result = {}
    for prop in owner.bl_rna.properties:
        if prop.identifier == "rna_type" or prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            continue
        value = getattr(owner, prop.identifier)
        if getattr(prop, "is_array", False):
            value = list(value)
        elif isinstance(value, set):
            value = sorted(value)
        result[prop.identifier] = value
    return result


def stored_curve(curve):
    return {"rna": scalar_rna(curve), "group": identity(curve.group),
            "keys": [scalar_rna(point) for point in curve.keyframe_points],
            "sampled_points": [scalar_rna(point) for point in curve.sampled_points],
            "modifiers": [scalar_rna(modifier) for modifier in curve.modifiers],
            "driver": None if curve.driver is None else scalar_rna(curve.driver)}


def action_rows(action):
    if not getattr(action, "is_action_layered", False):
        return {"legacy_curves": [stored_curve(curve) for curve in action.fcurves]}
    return {"slots": [scalar_rna(slot) for slot in action.slots],
            "layers": [{"rna": scalar_rna(layer), "strips": [
                {"rna": scalar_rna(strip), "channelbags": [
                    {"slot_handle": int(bag.slot_handle), "groups": [scalar_rna(group) for group in bag.groups],
                     "curves": [stored_curve(curve) for curve in bag.fcurves]} for bag in strip.channelbags]}
                for strip in layer.strips]} for layer in action.layers]}


def native_curve(obj, index=0):
    data, action = obj.animation_data, obj.animation_data.action
    if not getattr(action, "is_action_layered", False):
        curves, slot = list(action.fcurves), None
    else:
        slot = data.action_slot
        assert slot is not None
        curves = [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags
                  if bag.slot_handle == slot.handle for curve in bag.fcurves]
    found = [curve for curve in curves if curve.data_path == "location" and curve.array_index == index]
    assert len(found) == 1
    return found[0], str(slot.identifier) if slot is not None else None


def snapshot(runtime):
    context, scene = bpy.context, bpy.context.scene
    return {
        "actions": [{"identity": identity(action), "rna": scalar_rna(action), "content": action_rows(action)}
                    for action in sorted(bpy.data.actions, key=lambda owner: owner.name)],
        "objects": [{"identity": identity(obj), "data": identity(obj.data), "parent": identity(obj.parent),
                     "location": list(obj.location), "rotation": list(obj.rotation_euler), "scale": list(obj.scale),
                     "matrix_world": [list(row) for row in obj.matrix_world],
                     "hide_viewport": obj.hide_viewport, "hide_render": obj.hide_render,
                     "animation": None if obj.animation_data is None else {
                         "rna": scalar_rna(obj.animation_data), "action": identity(obj.animation_data.action),
                         "slot": identity(getattr(obj.animation_data, "action_slot", None)),
                         "drivers": [stored_curve(curve) for curve in obj.animation_data.drivers],
                         "nla": [{"rna": scalar_rna(track), "strips": [
                             {"rna": scalar_rna(strip), "action": identity(strip.action)} for strip in track.strips]}
                             for track in obj.animation_data.nla_tracks]}}
                    for obj in sorted(bpy.data.objects, key=lambda owner: owner.name)],
        "context": {"scene": identity(scene), "view_layer": [int(context.view_layer.as_pointer()), context.view_layer.name],
                    "window": None if context.window is None else int(context.window.as_pointer()),
                    "active": identity(context.view_layer.objects.active), "mode": context.mode,
                    "selected": sorted((identity(obj) for obj in context.selected_objects), key=lambda value: value[0]),
                    "frame": [scene.frame_current, float(scene.frame_subframe)],
                    "marker": scene.get("_codex_bridge_undo_marker")},
        "checkpoints": runtime.checkpoints.list(200),
    }


def float32(value):
    return struct.unpack("f", struct.pack("f", float(value)))[0]


class Proof:
    def __init__(self, runtime, grants):
        self.runtime, self.grants, self.rows = runtime, grants, []

    def call(self, label, obj, frames, oracle=None, *, error=None, index=0, slot=None):
        request = {"object_name": obj.name, "data_path": "location", "index": index, "frames": frames}
        if slot is not None:
            request["slot_identifier"] = slot
        before = snapshot(self.runtime)
        history_before = self.runtime.state.history(50)
        result = failure = None
        try:
            result = self.runtime.dispatch(METHOD, request)
        except BridgeError as caught:
            failure = {"code": str(caught.code), "context": caught.context}
            assert error is not None and caught.code == error, (label, caught.code, error)
        else:
            assert error is None, (label, "Expected refusal", result)
        after = snapshot(self.runtime)
        assert canonical(before) == canonical(after), (label, "Stored native state or checkpoints changed")
        history_after = self.runtime.state.history(50)
        assert len(history_before) < 49 and len(history_after) == len(history_before) + 1
        assert history_after[1:] == history_before
        receipt = history_after[0]
        assert receipt["tool"] == METHOD and receipt["success"] == (error is None)
        assert receipt.get("error_code") == error
        if result is not None:
            curve, native_slot = native_curve(obj, index)
            assert (result["object"], result["action"], result["slot_identifier"]) == (
                obj.name, obj.animation_data.action.name, native_slot)
            assert result["point_count"] == len(curve.keyframe_points)
            assert result["sample_count"] == len(frames) and len(result["samples"]) == len(frames)
            assert result["mute"] == curve.mute and result["lock"] == curve.lock
            assert result["extrapolation"] == curve.extrapolation
            assert result["evaluation_scope"] == "ACTIVE_ACTION_FCURVE"
            assert all(result[key] is False for key in ("scene_evaluated", "includes_nla", "includes_drivers",
                                                       "includes_constraints", "includes_deformation"))
            assert "operation" not in result
            for sample, requested in zip(result["samples"], frames, strict=True):
                assert sample["requested_frame"] == float(requested)
                assert sample["evaluated_frame"] == float32(requested)
                expected = oracle(float32(requested))
                assert math.isfinite(sample["value"]) and abs(sample["value"] - expected) <= 2e-5, (label, sample, expected)
        self.rows.append({"label": label, "request": request, "result": result, "error": failure,
                          "before": before, "after": after, "before_sha256": digest(before), "after_sha256": digest(after),
                          "history_before": history_before, "history_receipt": receipt,
                          "only_inspect_scene_granted": [key for key, value in self.grants.items() if value] == [Permission.INSPECT_SCENE.value]})
        return result


def make_actor(name):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    for frame, value in ((1., 0.), (13., 10.)):
        obj.location.x = value
        obj.keyframe_insert(data_path="location", index=0, frame=frame)
    obj.location.y = 3.
    obj.keyframe_insert(data_path="location", index=1, frame=1.)
    return obj


def configure(curve, interpolation, extrapolation="CONSTANT"):
    """Ordinary owned fixture setup, outside each measured read-only request."""
    curve.extrapolation = extrapolation
    for point in curve.keyframe_points:
        point.interpolation = interpolation
        point.handle_left_type = point.handle_right_type = "FREE"
    curve.keyframe_points[0].handle_left, curve.keyframe_points[0].handle_right = (-3., 0.), (5., 0.)
    curve.keyframe_points[1].handle_left, curve.keyframe_points[1].handle_right = (9., 10.), (17., 10.)
    curve.update()


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission == Permission.INSPECT_SCENE for permission in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    runtime.registry.enable_toolset("animation")
    spec = runtime.registry.get(METHOD)
    assert spec.modifies is False and spec.permissions == frozenset({Permission.INSPECT_SCENE})
    actor = make_actor("OwnedSamplingActor")
    peer = bpy.data.objects.new("ProtectedSharedSamplingActor", None)
    bpy.context.scene.collection.objects.link(peer)
    peer.animation_data_create().action = actor.animation_data.action
    if hasattr(actor.animation_data, "action_slot"):
        peer.animation_data.action_slot = actor.animation_data.action_slot
    peer.location.z = 4.
    curve, slot = native_curve(actor)
    # Fixed non-sampled caller time and deliberate context are part of every comparison.
    bpy.context.scene.frame_set(37, subframe=.25)
    bpy.context.view_layer.objects.active = peer
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    peer.select_set(True)
    proof = Proof(runtime, grants)
    configure(curve, "LINEAR")
    def linear(frame):
        return 10. * min(1., max(0., (frame - 1.) / 12.))

    proof.call("linear_order_duplicates_float32", actor, [10., 4., 7., 4., 1.123456789, -2., 16.], linear)
    proof.call("shared_action_peer", peer, [1., 4., 13.], linear)
    if slot is not None:
        proof.call("explicit_assigned_slot", actor, [2., 8.], linear, slot=slot)
        proof.call("wrong_slot_refusal", actor, [4.], error="INVALID_ARGUMENT", slot="OBUnassignedSamplingSlot")
    proof.call("maximum_sample_count", actor, [1. + index * 12. / 127. for index in range(128)], linear)
    configure(curve, "LINEAR", "LINEAR")
    proof.call("linear_extrapolation", actor, [-5., 1., 7., 13., 19.], lambda frame: (frame - 1.) * 10. / 12.)
    configure(curve, "CONSTANT")
    proof.call("constant_interpolation", actor, [-2., 1., 4., 12.5, 13., 16.], lambda frame: 0. if frame < 13. else 10.)
    configure(curve, "BEZIER")

    def bezier(frame):
        t = min(1., max(0., (frame - 1.) / 12.))
        return 10. * (3. * t * t - 2. * t * t * t)

    proof.call("bezier_independent_easing_oracle", actor, [1., 4., 7., 10., 13., 1.123456789], bezier)
    curve.mute = curve.lock = True
    proof.call("muted_locked_direct_curve", actor, [4., 7., 10.], bezier)
    curve.mute = curve.lock = False
    grants[Permission.INSPECT_SCENE.value] = False
    proof.call("permission_denial", actor, [4.], error="PERMISSION_DENIED")
    grants[Permission.INSPECT_SCENE.value] = True
    proof.call("missing_exact_curve", actor, [4.], error="INVALID_ARGUMENT", index=2)
    modifier = curve.modifiers.new("NOISE")
    proof.call("modifier_refusal", actor, [4.], error="NOT_IMPLEMENTED")
    curve.modifiers.remove(modifier)
    curve.keyframe_points[0].interpolation = "SINE"
    proof.call("unreviewed_interpolation_refusal", actor, [4.], error="NOT_IMPLEMENTED")
    configure(curve, "BEZIER")
    curve.convert_to_samples(1, 13)
    assert len(curve.sampled_points) > 0 and len(curve.keyframe_points) == 0
    proof.call("sampled_points_refusal", actor, [4.], error="NOT_IMPLEMENTED")
    empty = make_actor("OwnedEmptySamplingActor")
    empty_curve, _ = native_curve(empty)
    empty_curve.keyframe_points.clear()
    proof.call("empty_curve_refusal", empty, [4.], error="NOT_IMPLEMENTED")
    large = make_actor("OwnedBoundedSamplingActor")
    large_curve, _ = native_curve(large)
    large_curve.keyframe_points.clear()
    large_curve.keyframe_points.add(1024)
    for index, point in enumerate(large_curve.keyframe_points):
        point.co = (float(index + 1), float(index))
        point.interpolation = "LINEAR"
    large_curve.update()
    proof.call("maximum_keyframe_count", large, [1., 512.5, 1024.], lambda frame: frame - 1.)
    large_curve.keyframe_points.add(1)
    large_curve.keyframe_points[-1].co = (1025., 1024.)
    large_curve.keyframe_points[-1].interpolation = "LINEAR"
    large_curve.update()
    proof.call("over_keyframe_budget_refusal", large, [4.], error="NOT_IMPLEMENTED")
    duplicate = make_actor("OwnedDuplicateTimeSamplingActor")
    duplicate_curve, _ = native_curve(duplicate)
    duplicate_curve.keyframe_points[1].co = (1., 10.)
    # Do not normalize the malformed stored timeline before or during the refusal.
    proof.call("duplicate_key_time_refusal", duplicate, [4.], error="NOT_IMPLEMENTED")
    evidence = {"blender_version": bpy.app.version_string,
                "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "method": METHOD, "rows": proof.rows, "fixture_setup_raw_native": True,
                "project_saved": False, "rendered": False, "scene_motion_or_deformation_verified": False,
                "native_mcp_end_to_end": False, "windows_qualification": False,
                "unsupported_pre_evaluation_source_unit_proof_separate": True,
                "observed_action_layouts": sorted({"LAYERED" if row["result"]["slot_identifier"] is not None else "LEGACY"
                                                   for row in proof.rows if row["result"] is not None}),
                "visual_acceptance": "NOT_APPLICABLE_TO_STORED_NUMERIC_CURVE_SAMPLING"}
    path = Path(tempfile.gettempdir()) / "animation-curve-sampling-evidence.json"
    raw = (json.dumps(evidence, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    print("BLENDER_ANIMATION_CURVE_SAMPLING_OK " + canonical({
        "blender_version": bpy.app.version_string, "evidence_file": str(path),
        "evidence_sha256": hashlib.sha256(raw).hexdigest(), "case_count": len(proof.rows),
        "successful_reads": sum(row["error"] is None for row in proof.rows),
        "refusals": sum(row["error"] is not None for row in proof.rows),
        "stored_native_state_and_checkpoints_preserved": True,
        "read_only_history_receipts_verified": True, "independent_numeric_oracle": True,
        "shared_action_read": True, "scene_evaluated": False, "project_saved": False}))


if __name__ == "__main__":
    main()
