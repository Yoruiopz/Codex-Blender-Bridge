"""Opt-in private-UI evidence for registered RAW_FREE_POINT_V1 edits.

Raw owned setup and independent stored-state predictions only. Never invokes
Timeline/Keyframe tools, scene evaluation, save, capture, native undo, full curve
update or an Area switch. Broader cancellation and recovery remain unqualified.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "addon"))
MAX_EVIDENCE = 4 * 1024 * 1024
METHOD = "animation.curve_edit"
MARKER = "BLENDER_ANIMATION_INTENT_OK "


def f32(value: float) -> float:
    assert type(value) in (int, float) and math.isfinite(value)
    return struct.unpack("<f", struct.pack("<f", value))[0]


def typed(value: Any) -> Any:
    """Independent plain evidence encoding preserves every float bit and type."""
    if type(value) is float:
        assert math.isfinite(value)
        return ["float64", struct.pack("<d", value).hex()]
    if type(value) is dict:
        assert len(value) <= 512 and all(type(key) is str for key in value)
        return ["dict", [[key, typed(item)] for key, item in sorted(value.items())]]
    if type(value) in (tuple, list):
        assert len(value) <= 4096
        return [type(value).__name__, [typed(item) for item in value]]
    assert value is None or type(value) in (str, int, bool)
    return [type(value).__name__, value]


def same(first: Any, second: Any) -> bool:
    return typed(first) == typed(second)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(typed(value), separators=(",", ":")).encode()).hexdigest()


def identity(owner: Any) -> Any:
    if owner is None:
        return None
    result = {"pointer": int(owner.as_pointer()), "type": owner.bl_rna.identifier}
    if hasattr(owner, "session_uid"):
        result.update(session_uid=int(owner.session_uid), name=str(owner.name))
    return result


def primitive(value: Any) -> Any:
    if value is None or type(value) in (bool, int, float, str):
        return value
    if hasattr(value, "as_pointer"):
        return identity(value)
    if type(value) is set:
        return sorted(value)
    values = list(value)
    assert len(values) <= 256
    return [primitive(item) for item in values]


def rna(owner: Any) -> dict[str, Any]:
    """Independent complete writable native scalar/array/pointer projection."""
    properties = list(owner.bl_rna.properties)
    assert len(properties) <= 256
    result = {}
    for prop in properties:
        if prop.is_readonly:
            continue
        assert not prop.is_runtime and not prop.is_registered
        assert prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}
        result[prop.identifier] = primitive(getattr(owner, prop.identifier))
    return result


def curve_row(curve: Any) -> dict[str, Any]:
    assert len(curve.keyframe_points) <= 8 and not curve.sampled_points and not curve.modifiers
    result = {"identity": identity(curve), "rna": rna(curve),
              "points": [{"identity": identity(point), "rna": rna(point),
                          "float32_bits": {field: [struct.pack("<f", value).hex() for value in getattr(point, field)]
                                           for field in ("co", "co_ui", "handle_left", "handle_right")}}
                         for point in curve.keyframe_points]}
    for point in result["points"]:
        assert same(point["rna"]["co"], point["rna"]["co_ui"]), "Native co_ui read alias differs before freezing"
        assert point["float32_bits"]["co"] == point["float32_bits"]["co_ui"]
    return result


def action_row(action: Any) -> dict[str, Any]:
    assert action.is_action_layered and len(action.slots) <= 4 and len(action.layers) <= 2
    return {"identity": identity(action), "rna": rna(action), "users": int(action.users),
            "slots": [{"identity": identity(slot), "rna": rna(slot)} for slot in action.slots],
            "layers": [{"identity": identity(layer), "rna": rna(layer), "strips": [
                {"identity": identity(strip), "rna": rna(strip), "bags": [
                    {"identity": identity(bag), "rna": rna(bag),
                     "groups": [{"identity": identity(group), "rna": rna(group), "colors": rna(group.colors)}
                                for group in bag.groups],
                     "curves": [curve_row(curve) for curve in bag.fcurves]}
                    for bag in strip.channelbags]}
                for strip in layer.strips]} for layer in action.layers],
            "pose_markers": [{"identity": identity(marker), "rna": rna(marker)} for marker in action.pose_markers]}


def chosen_curve(state: dict[str, Any], action_pointer: int, index: int = 0) -> dict[str, Any]:
    actions = [row for row in state["actions"] if row["identity"]["pointer"] == action_pointer]
    assert len(actions) == 1
    curves = [curve for layer in actions[0]["layers"] for strip in layer["strips"] for bag in strip["bags"]
              for curve in bag["curves"] if curve["rna"]["data_path"] == "location" and curve["rna"]["array_index"] == index]
    assert len(curves) == 1
    return curves[0]


def predict(before: dict[str, Any], action_pointer: int, request: dict[str, Any]) -> dict[str, Any]:
    """Predict raw fields and read aliases before registered entry, never from readback."""
    assert request.get("extrapolation") is None, "The raw oracle never predicts full-curve setters"
    expected = copy.deepcopy(before)
    curve = chosen_curve(expected, action_pointer)
    for edit in request.get("keyframes", []):
        assert set(edit) <= {"frame", "co", "handle_left", "handle_right"}
        matches = [row for row in curve["points"] if same(row["rna"]["co"][0], float(edit["frame"]))]
        assert len(matches) == 1
        point = matches[0]
        assert same(point["rna"]["co"], point["rna"]["co_ui"])
        for field in ("co", "handle_left", "handle_right"):
            if field not in edit:
                continue
            assert type(edit[field]) is list and len(edit[field]) == 2
            value = [f32(component) for component in edit[field]]
            if field == "co":
                assert struct.pack("<f", value[0]) == struct.pack("<f", point["rna"]["co"][0])
            fields = ("co", "co_ui") if field == "co" else (field,)
            for changed in fields:
                point["rna"][changed] = list(value)
                point["float32_bits"][changed] = [struct.pack("<f", component).hex() for component in value]
    return expected


def owned_entry() -> tuple[Path, dict[str, Any]]:
    assert not bool(getattr(bpy.app, "background", True)), "Use the isolated private interactive runner"
    assert threading.current_thread() is threading.main_thread()
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert sys.dont_write_bytecode is True
    from scripts.blender_artist_sidebar_smoke import private_display_manifest

    display = private_display_manifest()  # Before any context/preferences access.
    process = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(process) == 32 and all(char in "0123456789abcdef" for char in process)
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    paths = {}
    for key in ("TEMP", "TMP", "TMPDIR", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        requested = Path(os.environ[key])
        resolved = requested.resolve(strict=True)
        assert requested.is_absolute() and resolved.is_dir() and resolved.is_relative_to(folder)
        assert resolved == folder if key in {"TEMP", "TMP", "TMPDIR"} else resolved.parent == folder
        paths[key] = {"requested": str(requested), "resolved": str(resolved)}
    assert bpy.data.filepath == ""
    return folder, {"display": display, "paths": paths, "process_instance": process,
                    "main_thread": True, "factory_startup": True, "disable_autoexec": True}


class Fixture:
    def __init__(self, folder: Path, attestation: dict[str, Any]):
        self.folder, self.path = folder, folder / "animation-intent-evidence.json"
        assert not self.path.exists()
        self.started = time.monotonic()
        self.label = "setup"
        self.data = {"attestation": attestation, "calls": [], "native_snapshot_receipts": [],
                     "controls": [], "samples": [], "completed": False,
                     "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
                     "authored_profile": "RAW_FREE_POINT_V1",
                     "scope": "Registered raw future-key co/left/right fields; complete declared stored Actions, point pointers, protected unanimated Object and context. No scene evaluation.",
                     "fault_scope": "No modified providers, production writer hooks or injected native exceptions; broader fault/recovery evidence remains portable and unqualified here.",
                     "unqualified": ["current-pose revision", "interpolation/easing/handle-type/extrapolation/full-update workflows",
                         "native failure compensation", "manual interleaving", "cancellation/disconnect",
                         "persistent non-ID/ABA identity", "complete hidden state", "Windows", "full H05/C03 and 1.0"],
                     "production_acceptance": False, "project_saved": False, "native_undo_invoked": False}

    def flush(self):
        raw = (json.dumps(self.data, indent=2, allow_nan=False) + "\n").encode()
        assert len(raw) <= MAX_EVIDENCE
        self.path.write_bytes(raw)

    def snapshot(self) -> dict[str, Any]:
        scene, layer = bpy.context.scene, bpy.context.view_layer
        objects = []
        for obj in (self.work, self.protected, self.active):
            data = obj.animation_data
            fields = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
                      "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale", "matrix_parent_inverse",
                      "hide_viewport", "hide_render", "hide_select", "lock_location", "lock_rotation", "lock_rotation_w",
                      "lock_rotations_4d", "lock_scale", "parent", "instance_type")
            objects.append({"identity": identity(obj), "data": identity(obj.data),
                            "literal_object_fields": {field: primitive(getattr(obj, field)) for field in fields},
                            "location": list(obj.location), "rotation_euler": list(obj.rotation_euler), "scale": list(obj.scale),
                            "action": identity(data.action) if data else None,
                            "slot": identity(data.action_slot) if data else None,
                            "anim_data": None if data is None else rna(data),
                            "nla": [] if data is None else [{"identity": identity(track), "rna": rna(track), "strips": [
                                {"identity": identity(strip), "rna": rna(strip)} for strip in track.strips]} for track in data.nla_tracks]})
        actions = sorted((self.action, self.protected_action), key=lambda item: item.as_pointer())
        users = bpy.data.user_map(subset=set(actions))
        authored = {"actions": [action_row(action) for action in actions], "objects": objects,
                    "consumers": [{"owner": identity(action), "references": sorted([
                        {"owner": identity(owner), "count": int(owner.user_of_id(action))} for owner in users.get(action, ())],
                        key=lambda item: item["owner"]["pointer"])} for action in actions],
                    "context": {"scene": identity(scene), "layer": identity(layer), "active": identity(layer.objects.active),
                                "selection": [identity(obj) for obj in layer.objects if obj.select_get(view_layer=layer)],
                                "frame": [scene.frame_current, scene.frame_subframe], "mode": bpy.context.mode,
                                "filepath": bpy.data.filepath}}
        manager = self.runtime.checkpoints
        return {"authored": authored, "history": self.runtime.state.history(limit=50),
                "checkpoint_bookkeeping": {"sequence": manager._sequence, "pending": None if manager._pending is None else vars_step(manager._pending),
                    "undo_steps": [vars_step(step) for step in manager._undo_steps],
                    "markers": [{"scene": identity(owner), "present": "_codex_bridge_undo_marker" in owner,
                                 "value": owner.get("_codex_bridge_undo_marker")} for owner in bpy.data.scenes]}}

    def setup(self):
        from blender_codex_bridge.permissions import PREFERENCE_PROPERTIES, Permission
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime

        preferences = bpy.context.preferences
        before = {"preferences_save": preferences.use_preferences_save,
                  "temporary_autosave": preferences.filepaths.use_auto_save_temporary_files}
        preferences.use_preferences_save = False
        preferences.filepaths.use_auto_save_temporary_files = False
        assert preferences.use_preferences_save is False and preferences.filepaths.use_auto_save_temporary_files is False
        self.data["serialization_controls"] = {"before": before, "after": {"preferences_save": False, "temporary_autosave": False},
            "termination": "Owned os._exit in finally after proof/stdio; no implicit quit/save or production cleanup claim"}
        assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
        self.prefs = get_preferences()
        assert self.prefs is not None and self.prefs.auto_start is False
        for permission, property_name in PREFERENCE_PROPERTIES.items():
            setattr(self.prefs, property_name, permission in {Permission.INSPECT_SCENE, Permission.EDIT_ANIMATION})
        self.runtime = get_runtime()
        assert self.runtime.permissions is self.runtime.executor.permissions
        self.data["grants"] = self.runtime.permissions.snapshot()
        self.data["permission_source"] = "Unchanged canonical Runtime PermissionManager; real add-on preference flags"
        self.runtime.registry.enable_toolset("animation")
        self.action, self.work = make_actor("IntentActor", "IntentMotion", ((1., 0.), (11., 10.)))
        self.protected = bpy.data.objects.new("Protected Unanimated", None)
        self.protected.location = (20., 40., 0.)
        bpy.context.scene.collection.objects.link(self.protected)
        self.protected_action, _slot = make_action("ProtectedMotion", self.protected.name, ((1., 20.), (11., 30.)))
        self.protected_action.use_fake_user = True
        assert self.protected.animation_data is None and self.protected_action.users == 1
        assert not self.work.animation_data.nla_tracks
        self.active = bpy.data.objects.new("Frozen Unanimated Active", None)
        bpy.context.scene.collection.objects.link(self.active)
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        self.active.select_set(True)
        bpy.context.view_layer.objects.active = self.active
        self.data["raw_setup"] = {"active": identity(self.active), "target": identity(self.work),
                                  "protected": identity(self.protected), "unbound_fake_user_action": identity(self.protected_action),
                                  "factory_time": [bpy.context.scene.frame_current, bpy.context.scene.frame_subframe],
                                  "seeded_locations": {self.work.name: list(self.work.location),
                                                       self.protected.name: list(self.protected.location)},
                                  "transform_setup": "Raw first-key values assigned before Action binding; no full curve update, evaluation or frame change"}
        self.observe_checkpoints()
        # A genuine setup checkpoint precedes every frozen request/oracle. It can
        # synchronize the disposable context; no later baseline adoption is allowed.
        self.label = "genuine_setup_checkpoint"
        self.data["setup_checkpoint"] = self.runtime.dispatch("checkpoint.create", {"description": "Raw point fixture setup"})
        receipts = self.data["native_snapshot_receipts"]
        assert len(receipts) == 1 and receipts[0]["completed"]
        assert receipts[0]["returned"] == self.data["setup_checkpoint"]["snapshot_marker"]
        assert bpy.context.scene.frame_current == 1 and bpy.context.scene.frame_subframe == 0.
        assert tuple(self.work.location) == (0., 20., 0.)
        self.data["setup_after_genuine_checkpoint"] = self.snapshot()

    def observe_checkpoints(self):
        """Passive completion observations, not a replacement checkpoint capability."""
        original_snapshot = self.runtime.checkpoints._snapshot

        def native_snapshot(blender, label, **kwargs):
            row = {"call": self.label, "label": label, "completed": False}
            self.data["native_snapshot_receipts"].append(row)
            returned = original_snapshot(blender, label, **kwargs)  # Exactly once; genuine native push and callbacks.
            row.update(completed=True, returned=returned)
            return returned

        self.runtime.checkpoints._snapshot = native_snapshot
        self.data["observer_scope"] = "Only _snapshot call-through observations; original called once with unchanged arguments/return. No provider, writer, Plan, native setter or checkpoint guard is replaced."

    def curve(self, index=0):
        slot = self.work.animation_data.action_slot
        matches = [curve for layer in self.action.layers for strip in layer.strips for bag in strip.channelbags
                   if bag.slot_handle == slot.handle for curve in bag.fcurves if curve.array_index == index]
        assert len(matches) == 1
        return matches[0]

    def call(self, label, request, *, expected_error=None):
        from blender_codex_bridge.errors import BridgeError

        self.label = label
        before = self.snapshot()
        expected = (copy.deepcopy(before["authored"]) if expected_error is not None else
                    predict(before["authored"], self.action.as_pointer(), request))
        row = {"label": label, "request": copy.deepcopy(request), "before": before, "expected_authored": expected,
               "expected_sha256": digest(expected), "entry": "runtime.dispatch with unchanged ordinary services",
               "snapshot_receipts_before": len(self.data["native_snapshot_receipts"])}
        self.data["calls"].append(row)
        self.flush()  # BEFORE registered providers, checkpoints or native authoring.
        try:
            row["result"] = self.runtime.dispatch(METHOD, request)
        except BridgeError as error:
            row["error"] = error.to_dict()
        finally:
            row["after"] = self.snapshot()
            row["snapshot_receipts_after"] = len(self.data["native_snapshot_receipts"])
            self.flush()
        if expected_error is None:
            assert "error" not in row, row.get("error")
            result = row["result"]
            assert result["authored_profile"] == "RAW_FREE_POINT_V1"
            assert result["current_pose_revision_qualified"] is False
            assert result["persistent_non_ID_identity_qualified"] is False
            assert result["complete_hidden_state_qualified"] is False
            facts = result["recovery_evidence"]
            assert facts["native_update_attempts"] == facts["native_update_verified"] == 0
            assert facts["state_known"] and facts["verification_required"] is False
        else:
            assert "error" in row and row["error"]["code"] == expected_error, row.get("error")
            assert row["snapshot_receipts_before"] == row["snapshot_receipts_after"]
        observed = row["after"]["authored"]
        assert same(observed, expected), (label, "Complete authored Action/context differs from independent expectation")
        row["observed_sha256"] = digest(observed)
        row["authored_comparison_passed"] = True
        self.flush()
        return row

    def samples(self, label, expected):
        before = self.snapshot()
        rows = [{"frame": frame, "expected": value, "observed": float(self.curve().evaluate(frame))}
                for frame, value in expected]
        after = self.snapshot()
        assert same(before, after)
        assert all(abs(row["observed"]-row["expected"]) <= 3e-6 for row in rows)
        self.data["samples"].append({"label": label, "rows": rows, "before": before, "after": after,
                                     "scope": "Stored FCurve.evaluate only; no scene/frame/deformation evaluation"})

    def run(self):
        try:
            self.setup()
            base = {"object_name": self.work.name, "data_path": "location", "index": 0}
            changed = {**base, "keyframes": [{"frame": 11, "co": [11., 12.],
                       "handle_left": [10., 11.], "handle_right": [14., 13.]}]}
            first = self.call("future_key_raw_co_left_right", changed)
            facts = first["result"]["recovery_evidence"]
            assert facts["owned_field_attempts"] == facts["owned_field_verified"] == 3
            receipts = self.data["native_snapshot_receipts"][first["snapshot_receipts_before"]:first["snapshot_receipts_after"]]
            assert len(receipts) == 2 and all(row["completed"] for row in receipts)
            assert [row["label"] for row in receipts] == ["Codex Before: " + METHOD, "Codex After: " + METHOD]
            self.samples("unchanged_current_and_revised_future_endpoints", ((1., 0.), (11., 12.)))
            noop = self.call("exact_noop", changed)
            facts = noop["result"]["recovery_evidence"]
            assert facts["owned_field_attempts"] == facts["owned_field_verified"] == 0
            revised = {**base, "keyframes": [{"frame": 11, "co": [11., 13.]}]}
            self.prefs.allow_edit_animation = False
            try:
                self.call("permission_denial", revised, expected_error="PERMISSION_DENIED")
            finally:
                self.prefs.allow_edit_animation = True
            self.call("invalid_typed_frame", {**base, "keyframes": [{"frame": True, "co": [11., 13.]}]},
                      expected_error="INVALID_ARGUMENT")
            self.call("invalid_existing_frame", {**base, "keyframes": [{"frame": 100, "co": [100., 13.]}]},
                      expected_error="INVALID_ARGUMENT")
            for field, value in (("interpolation", "LINEAR"), ("easing", "EASE_IN"),
                                 ("handle_left_type", "FREE"), ("handle_right_type", "FREE")):
                self.call("unsupported_" + field, {**base, "keyframes": [{"frame": 11, field: value}]},
                          expected_error="NOT_IMPLEMENTED")
            self.call("unsupported_extrapolation", {**base, "extrapolation": "CONSTANT"}, expected_error="NOT_IMPLEMENTED")
            self.call("unsupported_key_time_revision", {**base, "keyframes": [{"frame": 11, "co": [12., 13.]}]},
                      expected_error="NOT_IMPLEMENTED")
            self.call("current_pose_value_refusal", {**base, "keyframes": [{"frame": 1, "co": [1., 2.]}]},
                      expected_error="NOT_IMPLEMENTED")
            bpy.context.view_layer.objects.active = self.work  # Explicit outside-call invalid-context setup.
            try:
                self.call("animated_active_context_refusal", revised, expected_error="NOT_IMPLEMENTED")
            finally:
                bpy.context.view_layer.objects.active = self.active
                self.data["controls"].append({"label": "invalid_context_restored_outside_call", "active": identity(self.active)})
            self.samples("refusals_preserve_endpoints", ((1., 0.), (11., 12.)))
            self.data["completed"] = True
            self.finish(0)
        except BaseException:
            self.finish(1, traceback.format_exc())
        return None

    def finish(self, status, failure=None):
        from scripts.blender_artist_sidebar_smoke import owned_process_exit

        exit_status = 1
        try:
            if failure:
                self.data["failure"] = failure
                print(failure, file=sys.stderr, flush=True)
            self.data["elapsed_seconds"] = time.monotonic()-self.started
            self.flush()
            if status == 0:
                print(MARKER + json.dumps({"evidence_file": str(self.path), "evidence_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                    "calls": len(self.data["calls"]), "blender_version": bpy.app.version_string, "source_sha256": self.data["source_sha256"]}), flush=True)
            sys.stdout.flush()
            sys.stderr.flush()
            exit_status = status
        finally:
            owned_process_exit(exit_status)


def vars_step(step):
    return {"label": step.label, "before_marker": step.before_marker, "sequence": step.sequence,
            "kind": step.kind, "attempts": step.attempts}


def make_actor(name, action_name, values):
    """Seed a consistent factory-frame actor before binding its raw Action."""
    scene = bpy.context.scene
    assert scene.frame_current == 1 and scene.frame_subframe == 0., "Use untouched factory frame one"
    assert values and values[0][0] == 1., "The raw first key must match factory frame one"
    initial_location = (f32(values[0][1]), f32(values[0][1] + 20.), 0.)
    obj = bpy.data.objects.new(name, None)
    # Checkpoint creation can evaluate bound Actions. Do not seed inconsistent
    # zero channels and then adopt those later native changes as a baseline.
    obj.location = initial_location
    assert tuple(obj.location) == initial_location
    scene.collection.objects.link(obj)
    action, slot = make_action(action_name, name, values)
    obj.animation_data_create().action = action
    obj.animation_data.action_slot = slot
    return action, obj


def make_action(action_name, owner_name, values):
    """Build already ordered FREE points with raw setters; never issue full update."""
    action = bpy.data.actions.new(action_name)
    slot = action.slots.new("OBJECT", owner_name)
    layer = action.layers.new("Raw Owned Layer")
    strip = layer.strips.new(type="KEYFRAME")
    bag = strip.channelbag(slot, ensure=True)
    for index in (0, 1):
        curve = bag.fcurves.new(data_path="location", index=index)
        curve.keyframe_points.add(len(values))
        for point, (frame, value) in zip(curve.keyframe_points, values, strict=True):
            value += index*20.
            point.co = frame, value
            point.handle_left_type = point.handle_right_type = "FREE"
            point.handle_left, point.handle_right = (frame-1., value), (frame+3., value)
            point.interpolation, point.easing = "BEZIER", "AUTO"
    return action, slot


def main():
    # An imported direct main() call has the same fail-closed entry as __main__.
    folder, attestation = owned_entry()
    fixture = None
    try:
        fixture = Fixture(folder, attestation)
        paths = (Path(__file__), ROOT/"scripts/blender_artist_sidebar_smoke.py",
                 ROOT/"addon/blender_codex_bridge/tools/animation_curves.py",
                 ROOT/"addon/blender_codex_bridge/tools/_curve_edit_intent.py",
                 ROOT/"addon/blender_codex_bridge/tools/_curve_point_native.py",
                 ROOT/"addon/blender_codex_bridge/tools/_scene_checkpoint_roles.py",
                 ROOT/"addon/blender_codex_bridge/tools/_artist_role_witness.py",
                 ROOT/"addon/blender_codex_bridge/checkpoint_completion.py", ROOT/"addon/blender_codex_bridge/checkpoints.py")
        fixture.data["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        fixture.flush()
        bpy.app.timers.register(fixture.run, first_interval=.5)
    except BaseException:
        if fixture is not None:
            fixture.finish(1, traceback.format_exc())
        from scripts.blender_artist_sidebar_smoke import owned_process_exit
        try:
            traceback.print_exc()
        finally:
            owned_process_exit(1)


if __name__ == "__main__":
    # Unowned invocations never acquire the process-exit utility or schedule UI work.
    main()
