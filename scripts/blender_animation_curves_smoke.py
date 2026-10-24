"""Disposable native Action authoring and read-only curve-page fixture."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import bpy  # type: ignore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError, ErrorCode  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _animation_scope as animation_scope  # noqa: E402
from blender_codex_bridge.tools import animation, animation_curves  # noqa: E402


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(owner):
    return None if owner is None else [int(owner.as_pointer()), owner.session_uid, owner.name]


def native_curve(obj, data_path="location", index=0):
    """Read the assigned native channel directly for an independent comparison."""
    data, action = obj.animation_data, obj.animation_data.action
    layered = bool(getattr(action, "is_action_layered", False))
    slot = data.action_slot if layered else None
    if layered:
        assert slot is not None
        curves = [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags
                  if bag.slot_handle == slot.handle for curve in bag.fcurves]
    else:
        curves = list(action.fcurves)
    matches = [curve for curve in curves if curve.data_path == data_path and curve.array_index == index]
    assert len(matches) == 1
    return matches[0], str(slot.identifier) if slot is not None else None


def native_point(point):
    return {"frame": float(point.co[0]), "value": float(point.co[1]),
        "interpolation": str(point.interpolation), "easing": str(point.easing),
        "handle_left_type": str(point.handle_left_type), "handle_right_type": str(point.handle_right_type),
        "handle_left": [float(point.handle_left[0]), float(point.handle_left[1])],
        "handle_right": [float(point.handle_right[0]), float(point.handle_right[1])]}


class CurveInspectionProof:
    def __init__(self, runtime, grants, actors):
        self.runtime, self.grants, self.actors = runtime, grants, actors
        self.reads = []
        self.legacy_available = False
        self.legacy_probe = {}
        spec = runtime.registry.get("animation.curve_inspect")
        assert spec.modifies is False and spec.permissions == frozenset({Permission.INSPECT_SCENE})

    def snapshot(self):
        context, scene = bpy.context, bpy.context.scene
        bindings = []
        for obj in self.actors:
            data = obj.animation_data
            action = data.action if data is not None else None
            slot = getattr(data, "action_slot", None) if data is not None else None
            bindings.append({"object": identity(obj), "action": identity(action),
                "slot_identifier": str(slot.identifier) if slot is not None else None,
                "use_nla": bool(data.use_nla) if data is not None else None,
                "use_tweak_mode": bool(data.use_tweak_mode) if data is not None else None,
                "location": list(obj.location), "rotation_euler": list(obj.rotation_euler), "scale": list(obj.scale)})
        return {"actions": [{"identity": identity(action), "users": int(action.users),
                    "fake_user": bool(action.use_fake_user), "extra_user": bool(action.use_extra_user),
                    "content": animation_scope.action_content(action)}
                   for action in sorted(bpy.data.actions, key=lambda action: action.name)],
            "bindings": bindings, "context": {"scene": identity(scene),
                "view_layer": [int(context.view_layer.as_pointer()), context.view_layer.name],
                "window": int(context.window.as_pointer()) if context.window is not None else None,
                "active": identity(context.view_layer.objects.active), "mode": context.mode,
                "selected": sorted((identity(obj) for obj in context.selected_objects), key=lambda value: value[0]),
                "frame": [scene.frame_current, float(scene.frame_subframe)],
                "checkpoint_marker": scene.get("_codex_bridge_undo_marker")}}

    def inspect(self, label, obj, *, offset=0, limit=64, explicit_slot=False):
        curve, slot = native_curve(obj)
        points = [native_point(point) for point in curve.keyframe_points]
        before = self.snapshot()
        request = {"object_name": obj.name, "data_path": "location", "index": 0}
        if offset:
            request["point_offset"] = offset
        if limit != 64:
            request["point_limit"] = limit
        if explicit_slot:
            assert slot is not None
            request["slot_identifier"] = slot
        previous = dict(self.grants)
        # Ordinary fixture configuration between requests; no race or callbacks.
        self.grants.update({permission.value: permission == Permission.INSPECT_SCENE for permission in Permission})
        assert [name for name, granted in self.grants.items() if granted] == [Permission.INSPECT_SCENE.value]
        try:
            result = self.runtime.dispatch("animation.curve_inspect", request)
        finally:
            self.grants.clear()
            self.grants.update(previous)
        after = self.snapshot()
        assert canonical(before) == canonical(after), "Read-only curve inspection changed the measured Action/context state"
        end = min(len(points), offset+limit)
        expected = {"object": obj.name, "action": obj.animation_data.action.name, "slot_identifier": slot,
            "data_path": "location", "index": 0, "group": curve.group.name if curve.group is not None else None,
            "mute": bool(curve.mute), "lock": bool(curve.lock), "extrapolation": str(curve.extrapolation),
            "point_count": len(points), "point_offset": offset, "point_limit": limit,
            "returned_points": end-offset, "keyframes": points[offset:end],
            "truncated": end < len(points), "next_offset": end if end < len(points) else None}
        assert canonical(result) == canonical(expected), (label, result, expected)
        self.reads.append({"label": label, "request": request, "result": result, "native_expected": expected,
            "only_granted_permission": Permission.INSPECT_SCENE.value,
            "action_layout": "LAYERED" if slot is not None else "LEGACY",
            "before": before, "after": after,
            "before_sha256": hashlib.sha256(canonical(before).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(canonical(after).encode()).hexdigest()})
        return result

    def retain(self):
        path = Path(tempfile.gettempdir()) / "animation-curves-inspection-evidence.json"
        raw = (json.dumps({"blender_version": bpy.app.version_string,
            "source_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "method": "animation.curve_inspect", "modifies": False,
            "legacy_api_available": self.legacy_available, "legacy_probe": self.legacy_probe, "reads": self.reads,
            "ordinary_fixture_grant_configuration": True, "project_saved": False,
            "native_mcp_end_to_end": False, "release_readiness": "NOT_ASSESSED"}, indent=2)+"\n").encode()
        path.write_bytes(raw)
        return {"evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "read_count": len(self.reads), "only_inspect_scene_granted": True,
            "whole_action_and_context_preserved": True, "shared_action_read": True,
            "legacy_api_available": self.legacy_available,
            "legacy_probe": self.legacy_probe,
            "observed_layouts": sorted({row["action_layout"] for row in self.reads})}


def make_legacy_fixture():
    """Report the actual Action layout created through the optional older API."""
    probe = {"fcurves_api_exposed": False, "api_route": None, "created_action_layout": None,
             "legacy_action_created": False, "unused_fixture_action_removed_before_binding": False}
    if bpy.types.Action.bl_rna.properties.get("fcurves") is None:
        return None, None, probe
    probe.update(fcurves_api_exposed=True, api_route="Action.fcurves.new")
    action = bpy.data.actions.new("OwnedLegacyCurveRead")
    curve = action.fcurves.new(data_path="location", index=0)
    if action.is_action_layered:
        # An exposed older API can create a layered Action. This unused owned
        # fixture allocation is removed before any object/Action binding.
        probe["created_action_layout"] = "LAYERED"
        name = action.name
        assert action.users == 0
        bpy.data.actions.remove(action)
        assert bpy.data.actions.get(name) is None
        probe["unused_fixture_action_removed_before_binding"] = True
        return None, None, probe
    assert action.is_action_legacy
    probe.update(created_action_layout="LEGACY", legacy_action_created=True)
    curve.extrapolation = "LINEAR"
    for frame, value in ((1., 2.), (11., 4.)):
        curve.keyframe_points.insert(frame, value)
    for point, left, right in zip(curve.keyframe_points, ((0., 2.), (8., 4.)), ((4., 2.), (12., 4.)), strict=True):
        point.interpolation = "BEZIER"
        point.handle_left_type = point.handle_right_type = "FREE"
        point.handle_left, point.handle_right = left, right
    obj = bpy.data.objects.new("OwnedLegacyCurveActor", None)
    bpy.context.scene.collection.objects.link(obj)
    obj.animation_data_create().action = action
    return obj, action, probe


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
    legacy_actor, legacy_action = None, None
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
        legacy_actor, legacy_action, legacy_probe = make_legacy_fixture()
        proof = CurveInspectionProof(runtime, grants, [obj, protected, playback, *([legacy_actor] if legacy_actor is not None else [])])
        proof.legacy_available = legacy_actor is not None
        proof.legacy_probe = legacy_probe
        shared = proof.inspect("shared_source_before_authoring", obj)
        peer = proof.inspect("shared_peer_before_authoring", protected)
        assert shared["action"] == peer["action"] and shared["keyframes"] == peer["keyframes"]
        first_page = proof.inspect("first_point_page", obj, limit=1)
        tail_page = proof.inspect("tail_point_page", obj, offset=1, limit=1)
        terminal_page = proof.inspect("empty_terminal_page", obj, offset=2, limit=1)
        assert first_page["truncated"] and first_page["next_offset"] == 1
        assert tail_page["returned_points"] == 1 and tail_page["next_offset"] is None
        assert terminal_page["returned_points"] == 0 and terminal_page["keyframes"] == []
        if shared["slot_identifier"] is not None:
            proof.inspect("explicit_assigned_slot", obj, explicit_slot=True)
        if legacy_actor is not None:
            legacy = proof.inspect("native_legacy_action", legacy_actor)
            assert legacy["slot_identifier"] is None and legacy["extrapolation"] == "LINEAR"
        try:
            runtime.dispatch("animation.curve_edit", {"object_name": obj.name, "data_path": "location", "index": 0, "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
        except BridgeError as error:
            assert error.code == ErrorCode.NOT_IMPLEMENTED
        else:
            raise AssertionError("Shared Action must remain protected")
        copied = runtime.dispatch("animation.action_copy", {"object_name": obj.name, "new_name": "IndependentMotion"})
        assert copied["independent_version"] and obj.animation_data.action != source
        assert protected.animation_data.action == source
        proof.inspect("independent_before_authoring", obj)
        edited = runtime.dispatch("animation.curve_edit", {
            "object_name": obj.name, "data_path": "location", "index": 0, "extrapolation": "CONSTANT",
            "keyframes": [{"frame": 1, "interpolation": "LINEAR"}],
        })
        linear_read = proof.inspect("after_linear_authoring", obj)
        assert linear_read["keyframes"][0]["interpolation"] == "LINEAR"
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
        bezier_read = proof.inspect("after_free_handle_authoring", obj)
        assert bezier_read["keyframes"][0]["handle_left"] == [0., 0.]
        assert bezier_read["keyframes"][0]["handle_right"] == [4., 0.]
        assert bezier_read["keyframes"][1]["handle_left"] == [8., 10.]
        assert bezier_read["keyframes"][1]["handle_right"] == [12., 10.]
        assert all(point["handle_left_type"] == point["handle_right_type"] == "FREE" for point in bezier_read["keyframes"])
        assert abs(curve.evaluate(6) - 5) < 1e-4
        runtime.dispatch("animation.curve_edit", {"object_name": obj.name, "data_path": "location", "index": 0, "keyframes": [{"frame": 1, "interpolation": "CONSTANT"}]})
        constant_read = proof.inspect("after_constant_authoring", obj)
        assert constant_read["keyframes"][0]["interpolation"] == "CONSTANT"
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
            "curve_inspection": proof.retain(),
            "full_animation_acceptance_verified": False, "slot_identifier": edited["slot_identifier"],
        }, sort_keys=True))
    finally:
        if legacy_actor is not None:
            bpy.data.objects.remove(legacy_actor, do_unlink=True)
        if legacy_action is not None and legacy_action.users == 0:
            bpy.data.actions.remove(legacy_action)
        for item in (playback, protected, obj):
            bpy.data.objects.remove(item, do_unlink=True)


if __name__ == "__main__":
    main()
