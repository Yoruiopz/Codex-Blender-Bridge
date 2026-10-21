"""Non-scripted transform drivers and explicit action-backed NLA strips."""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import get_object, int_param, reject_unknown_params, require_blender
from . import _legacy_object_drivers
from ._animation_scope import (
    Guard,
    action_content,
    action_token,
    action_users,
    affected_scope,
    bounded,
    key,
    object_scope,
    rna_state,
    validate_slot,
)
from ._nla_controls import controls, new_clip, new_influence
from ._rna import bounded_name, prepare_assignments, settings_mapping
from .geometry_nodes import _editable

STRIP_PROPERTIES = frozenset(
    {
        "frame_start",
        "frame_end",
        "action_frame_start",
        "action_frame_end",
        "scale",
        "repeat",
        "influence",
        "blend_type",
        "extrapolation",
        "mute",
        "blend_in",
        "blend_out",
        "use_auto_blend",
        "use_animated_influence",
    }
)
CHANNELS = {"location", "rotation_euler", "scale"}
TRANSFORMS = {f"{kind}_{axis}" for kind in ("LOC", "ROT", "SCALE") for axis in "XYZ"}


def _nla_context(context: Any) -> None:
    if context is None or not all(hasattr(context, field) for field in ("require", "state", "check_cancelled")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "NLA mutation requires a live permission/state context.")


def _nla_authority(context: Any, method: str) -> None:
    context.require(Permission.EDIT_ANIMATION)
    flags = context.state.snapshot()
    if flags.get("emergency_stopped") or flags.get("paused"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags.get("emergency_stopped") else ErrorCode.AGENT_PAUSED,
                          "NLA mutation stopped before its next write.")
    registry = getattr(context, "registry", None)
    if registry is not None and registry.get(method).toolset not in registry.enabled_toolsets:
        raise BridgeError(ErrorCode.TOOLSET_DISABLED, "NLA toolset was disabled during live permission validation.")


def _nla_slot(slot: Any) -> Any:
    return None if slot is None else (key(slot), slot.identifier, int(slot.handle), slot.target_id_type)


class _LegacyNlaGuard:
    """Stage-specific compare-and-swap for legacy NLA writes and recovery.

    Capturing a newly returned native allocation requires unchanged old state and
    its reviewed constructor defaults. Ordinary writes never refresh expected
    state from arbitrary observations after a setter/cancellation callback.
    """

    def __init__(self, context: Any, obj: Any, method: str, extra_actions: tuple[Any, ...] = ()):
        self.bpy, self.obj, self.data = require_blender(), obj, obj.animation_data
        self.guard = Guard(self.bpy, context, method)
        self.guard.remember(obj, self.bpy.data.objects)
        self.name, self.object_token, self.data_token = obj.name, action_token(obj), key(self.data)
        self.actions: dict[Any, Any] = {}
        self.extra_actions = extra_actions
        self.created_tracks: list[Any] = []
        self.started = False
        for action in extra_actions:
            self._action(action)
        self.expected = self.read()
        self.original = deepcopy(self.expected)

    def _action(self, action: Any) -> None:
        if action is not None and action_token(action) not in self.actions:
            self.actions[action_token(action)] = action
            self.guard.remember(action, self.bpy.data.actions)

    def _strip(self, strip: Any) -> dict[str, Any]:
        if strip.type not in {"CLIP", "TRANSITION"}:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "NLA recovery snapshot supports CLIP/TRANSITION strips, not nested META data.")
        if len(getattr(strip, "modifiers", ())):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Strip modifiers need a broader native recovery snapshot.")
        action = getattr(strip, "action", None)
        self._action(action)
        return {"id": key(strip), "type": strip.type, "action": action_token(action), "controls": controls(strip),
                "slot": _nla_slot(getattr(strip, "action_slot", None)),
                "settings": dict(rna_state(strip, exclude=frozenset({"action", "action_slot", "action_slot_handle", "last_slot_identifier"})))}

    def _track(self, track: Any) -> dict[str, Any]:
        return {"id": key(track), "settings": dict(rna_state(track)),
                "strips": [self._strip(strip) for strip in bounded(track.strips, 64, "NLA strips")]}

    def read(self) -> dict[str, Any]:
        obj, data = self.obj, self.obj.animation_data
        if action_token(obj) != self.object_token or key(data) != self.data_token:
            raise invalid_argument("NLA owner/AnimData identity changed; writes and recovery refused.")
        object_scope(self.bpy, obj)
        if data.use_tweak_mode or len(data.drivers):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed NLA mutation excludes tweak mode and drivers.")
        closure = affected_scope(self.bpy, obj, [])
        tracks = bounded(data.nla_tracks, 16, "NLA tracks")
        if sum(len(track.strips) for track in tracks) > 64:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "NLA recovery scope exceeds 64 total strips.")
        self._action(getattr(data, "action", None))
        if data.action is not None:
            validate_slot(obj, data.action, getattr(data, "action_slot", None))
        for track in tracks:
            for strip in track.strips:
                if strip.action is not None:
                    validate_slot(obj, strip.action, getattr(strip, "action_slot", None))
        records = [self._track(track) for track in tracks]
        consumers = []
        for owner in bounded(self.bpy.data.user_map(subset={obj}).get(obj, ()), 100, "NLA object consumers"):
            _editable(owner)
            consumers.append((action_token(owner), owner.name, int(owner.user_of_id(obj))))
        for action in self.extra_actions:
            slots = bounded(getattr(action, "slots", ()), 64, "Action slots")
            suitable = [slot for slot in slots if slot.target_id_type == "OBJECT"]
            if slots and (len(slots) != 1 or len(suitable) != 1):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Created clips require one exact suitable Action slot.")
            validate_slot(obj, action, suitable[0] if suitable else None)
        if len(self.actions) > 16:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed NLA snapshot exceeds 16 Actions.")
        actions = {}
        for token, action in self.actions.items():
            actions[token] = {"name": action.name, "content": action_content(action),
                              "range": tuple(float(value) for value in action.frame_range),
                              "users": action_users(self.bpy, action)}
        edit = getattr(getattr(self.bpy.context, "preferences", None), "edit", None)
        preferences = None if edit is None else (edit.fcurve_new_auto_smoothing, edit.keyframe_new_handle_type, edit.keyframe_new_interpolation_type)
        return {"object": (action_token(obj), obj.name, key(getattr(obj, "data", None))), "data": key(data),
                "control_preferences": preferences,
                "session": (key(self.bpy.context.scene), key(self.bpy.context.view_layer), self.bpy.data.filepath, self.bpy.context.mode),
                "closure": closure, "frame": (self.bpy.context.scene.frame_current, self.bpy.context.scene.frame_subframe),
                "selection": tuple((key(item), bool(item.select_get())) for item in bounded(self.bpy.context.view_layer.objects, 256, "view-layer objects")),
                "active_object": key(self.bpy.context.view_layer.objects.active),
                "settings": dict(rna_state(data, exclude=frozenset({"action", "action_slot", "action_slot_handle", "last_slot_identifier"}))),
                "active_action": action_token(getattr(data, "action", None)),
                "slot": _nla_slot(getattr(data, "action_slot", None)), "tracks": records,
                "active_track": key(data.nla_tracks.active), "actions": actions,
                "consumers": tuple(sorted(consumers, key=lambda record: record[0][0]))}

    def gate(self) -> None:
        self.guard.gate()
        _nla_authority(self.guard.context, self.guard.method)
        if self.read() != self.expected:
            raise invalid_argument("NLA ownership, settings, Action/slot/content or consumer scope changed; writes and recovery refused.")

    def verify(self) -> None:
        if self.read() != self.expected:
            raise invalid_argument("NLA setter changed state outside its exact expected stage; reinspect retained data.")

    def write(self, expected: dict[str, Any], operation: Any) -> None:
        self.gate()
        previous = self.expected
        self.started = True
        try:
            operation()
        except Exception:
            try:
                observed = self.read()
                if observed == expected:
                    self.expected = expected
                elif observed != previous:
                    # Do not accept a partial setter or callback's unrelated change.
                    self.expected = previous
            except Exception:
                # Observation failure never authorizes compensation or replaces
                # the setter's primary failure.
                self.expected = previous
            raise
        self.expected = expected
        self.verify()

    def track(self, model: dict[str, Any], owner: Any) -> dict[str, Any]:
        return next(record for record in model["tracks"] if record["id"] == key(owner))

    def references(self, model: dict[str, Any], action: Any, delta: int) -> None:
        users = model["actions"][action_token(action)]["users"]
        refs = list(users["references"])
        matches = [index for index, record in enumerate(refs) if record[0] == key(self.obj)]
        if not matches and delta == 1:
            refs.append((key(self.obj), getattr(self.obj, "session_uid", None), self.obj.name,
                         getattr(getattr(self.obj, "bl_rna", None), "identifier", "unknown"), 0,
                         self.obj.library is None and self.obj.override_library is None and bool(self.obj.is_editable)))
            matches = [len(refs)-1]
        if len(matches) != 1 or refs[matches[0]][4]+delta < 0:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "NLA Action reference delta has no exact existing owner.")
        index = matches[0]
        record = refs[index]
        if record[4]+delta:
            refs[index] = (*record[:4], record[4]+delta, record[5])
        else:
            refs.pop(index)
        users.update(users=users["users"]+delta, real_users=users["real_users"]+delta,
                     references=tuple(sorted(refs, key=lambda record: record[0])))

    def add_track(self) -> Any:
        self.gate()
        self.started = True
        tracks = self.data.nla_tracks
        track = tracks.new(prev=tracks[-1]) if len(tracks) else tracks.new()
        self.created_tracks.append(track)
        record = self._track(track)
        settings = record["settings"]
        if (record["strips"] or settings.get("lock") or settings.get("mute") or settings.get("is_solo")
                or settings.get("select") is not True):
            raise invalid_argument("New NLA track does not retain its empty private constructor scope.")
        expected = deepcopy(self.expected)
        expected["tracks"].append(record)
        expected["active_track"] = key(track)
        self.expected = expected
        self.verify()
        return track

    def add_strip(self, track: Any, name: str, start: float, end: float, action: Any, slot: Any,
                  source_start: float | None = None, source_end: float | None = None) -> Any:
        self.gate()
        self.started = True
        strip = track.strips.new(name, int(start), action)
        record = self._strip(strip)
        if not new_clip(strip, name, start, end,
                        start if source_start is None else source_start,
                        end if source_end is None else source_end, action, slot):
            raise invalid_argument("New NLA strip does not match its complete reviewed native constructor scope.")
        expected = deepcopy(self.expected)
        self.track(expected, track)["strips"].append(record)
        self.references(expected, action, 1)
        self.expected = expected
        self.verify()
        return strip

    def influence(self, track: Any, strip: Any, expected: dict[str, Any]) -> None:
        """Adopt only the fully demonstrated private native one-key allocation."""
        self.gate()
        previous = deepcopy(self.expected)
        before = next(item for item in self.track(previous, track)["strips"] if item["id"] == key(strip))
        prefs = previous["control_preferences"]
        if prefs is None or (before["settings"].get("use_animated_time", False)
                and not any(curve.data_path == "strip_time" for curve in strip.fcurves)):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Influence allocation requires reviewed preferences and an already complete animated-time control scope.")
        edit = SimpleNamespace(fcurve_new_auto_smoothing=prefs[0], keyframe_new_handle_type=prefs[1], keyframe_new_interpolation_type=prefs[2])
        self.started = True
        setter_error = None
        try:
            strip.use_animated_influence = True
        except Exception as error:
            setter_error = error
        after = self.read()
        if after == previous:
            if setter_error is not None:
                raise setter_error
            raise invalid_argument("Native animated-influence setter made no expected allocation.")
        record = next(item for item in self.track(after, track)["strips"] if item["id"] == key(strip))
        old_ids = {item[0] for item in before["controls"]}
        new = [curve for curve in strip.fcurves if key(curve) not in old_ids]
        if (len(new) != 1 or not new_influence(new[0], before["settings"], edit)
                or record["controls"][:-1] != before["controls"] or record["controls"][-1][0] != key(new[0])):
            raise invalid_argument("New NLA influence control exceeds its exact reviewed native constructor; retained without further writes.")
        target = next(item for item in self.track(expected, track)["strips"] if item["id"] == key(strip))
        target["controls"] = record["controls"]
        if after != expected:
            raise invalid_argument("Influence allocation changed protected NLA/Action/context data; retained without further writes.")
        self.expected = expected
        if setter_error is not None:
            raise setter_error

    def retained_track(self, track: Any) -> Any:
        try:
            if track is None and self.created_tracks:
                track = self.created_tracks[-1]
            if track is not None and any(key(item) == key(track) for item in self.obj.animation_data.nla_tracks):
                return {"name": str(track.name)[:1024], "identity": key(track)}
        except Exception:
            pass
        return None


def _object(params: Mapping[str, Any], modify: bool = False) -> Any:
    obj = get_object(params.get("object_name"), allow_active=False)
    if modify:
        _editable(obj)
    data = obj.animation_data
    if data:
        if data.use_tweak_mode:
            raise invalid_argument("Exit NLA tweak mode before structured editing/inspection.")
        if (
            len(data.drivers) > 128
            or len(data.nla_tracks) > 64
            or sum(len(t.strips) for t in data.nla_tracks) > 256
        ):
            raise invalid_argument("Animation layer budget exceeded.")
    return obj


def _channel(params: Mapping[str, Any]) -> tuple[str, int]:
    path = params.get("data_path")
    if not isinstance(path, str) or path not in CHANNELS:
        raise invalid_argument("data_path must be location, rotation_euler or scale.")
    return path, int_param(params, "index", 0, minimum=0, maximum=2)


def inspect(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name"})
    obj = _object(params)
    data = obj.animation_data
    return {
        "object": obj.name,
        "active_action": getattr(getattr(data, "action", None), "name", None),
        "nla_enabled": bool(data and data.use_nla),
        "drivers": []
        if not data
        else [
            {
                "data_path": curve.data_path,
                "index": curve.array_index,
                "driver_type": curve.driver.type,
                "valid": curve.driver.is_valid,
                "muted": curve.mute,
                "variables": [
                    {
                        "name": v.name,
                        "type": v.type,
                        "targets": [
                            {
                                "object": getattr(t.id, "name", None),
                                "transform_type": t.transform_type,
                                "transform_space": t.transform_space,
                            }
                            for t in v.targets
                        ],
                    }
                    for v in list(curve.driver.variables)[:16]
                ],
                "variables_truncated": len(curve.driver.variables) > 16,
            }
            for curve in data.drivers
        ],
        "tracks": []
        if not data
        else [
            {
                "name": track.name,
                "mute": track.mute,
                "solo": track.is_solo,
                "locked": track.lock,
                "strips": [
                    {
                        "name": strip.name,
                        "type": strip.type,
                        "action": getattr(strip.action, "name", None),
                        "frame_start": strip.frame_start,
                        "frame_end": strip.frame_end,
                        "influence": strip.influence,
                        "scale": strip.scale,
                        "repeat": strip.repeat,
                        "blend_type": strip.blend_type,
                        "mute": strip.mute,
                        "action_slot": getattr(
                            getattr(strip, "action_slot", None), "identifier", None
                        ),
                    }
                    for strip in track.strips
                ],
            }
            for track in data.nla_tracks
        ],
    }


def driver_add(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    result = _legacy_object_drivers.add(context, params)
    return {**result, **inspect(context, {"object_name": params["object_name"]})}


def driver_remove(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    result = _legacy_object_drivers.remove(context, params)
    return {**result, **inspect(context, {"object_name": params["object_name"]})}


def nla_add(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(
        params,
        {
            "object_name",
            "track_name",
            "strip_name",
            "action_name",
            "frame_start",
            "slot_identifier",
        },
    )
    _nla_context(context)
    obj = _object(params, True)
    track_name = bounded_name(params.get("track_name"), "track_name", maximum=63)
    strip_name = bounded_name(params.get("strip_name"), "strip_name", maximum=63)
    if any(len(name.encode("utf-8")) > 63 for name in (track_name, strip_name)):
        raise invalid_argument("Track and strip names must fit 63 UTF-8 bytes.")
    start = int_param(params, "frame_start", 1, minimum=-100_000, maximum=100_000)
    action_name = bounded_name(params.get("action_name"), "action_name")
    action = require_blender().data.actions.get(action_name)
    if action is None or (obj.animation_data and len(obj.animation_data.drivers)):
        raise invalid_argument("Action must exist; NLA target may not have drivers.")
    slots = list(getattr(action, "slots", ()))
    requested_slot = params.get("slot_identifier")
    choices = [
        s
        for s in slots
        if s.target_id_type == "OBJECT"
        and (requested_slot is None or s.identifier == requested_slot)
    ]
    if (slots and len(choices) != 1) or (requested_slot is not None and not choices):
        raise invalid_argument("Choose exactly one suitable action slot by slot_identifier.")
    if obj.animation_data and obj.animation_data.nla_tracks.get(track_name):
        raise invalid_argument(
            "nla.add_strip creates a new named track; existing tracks are not reused implicitly."
        )
    bpy = require_blender()
    source_start, source_end = map(float, action.frame_range)
    if not (math.isfinite(source_start) and math.isfinite(source_end)
            and source_start.is_integer() and source_end.is_integer()
            and -100_000 <= source_start < source_end <= 100_000
            and source_end-source_start <= 100_000 and start+source_end-source_start <= 100_000):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "New NLA clips require a positive bounded integral Action range.")
    if slots and len(slots) != 1:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "New NLA tracks currently require one exact suitable Action slot.")
    validate_slot(obj, action, choices[0] if choices else None)
    had_data = obj.animation_data is not None
    if not had_data:
        guard = Guard(bpy, context, "nla.add_strip")
        guard.remember(obj, bpy.data.objects)
        guard.remember(action, bpy.data.actions)
        source_signature = (action_token(action), action.name, action_content(action), action_users(bpy, action), tuple(action.frame_range))
        created_data = None
        try:
            guard.gate()
            _nla_authority(context, "nla.add_strip")
            object_scope(bpy, obj)
            affected_scope(bpy, obj, [])
            if obj.animation_data is not None or source_signature != (action_token(action), action.name, action_content(action), action_users(bpy, action), tuple(action.frame_range)):
                raise invalid_argument("Preflight Action or empty AnimData scope changed; allocation refused.")
            # Retain an owned empty AnimData on later failure instead of clearing
            # a container that might have acquired foreign dependencies.
            created_data = obj.animation_data_create()
            guard.gate()
            _nla_authority(context, "nla.add_strip")
            if (key(obj.animation_data) != key(created_data) or created_data.action is not None
                    or len(created_data.nla_tracks) or len(created_data.drivers) or created_data.use_tweak_mode
                    or source_signature != (action_token(action), action.name, action_content(action), action_users(bpy, action), tuple(action.frame_range))):
                raise invalid_argument("Created AnimData or source Action acquired foreign state; retained for recovery.")
        except Exception as error:
            raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                              "NLA AnimData allocation failed or scope changed; inspect the exact owner.",
                              {"possible_mutation": created_data is not None or obj.animation_data is not None,
                               "execution_started": created_data is not None, "verification_required": True,
                               "retained_anim_data": key(obj.animation_data)}) from error
    data = obj.animation_data
    if len(data.nla_tracks) >= 16:
        raise invalid_argument("Reviewed NLA mutation supports at most 16 tracks.")
    _nla_context(context)
    scope = _LegacyNlaGuard(context, obj, "nla.add_strip", (action,))
    previous_active, track = data.nla_tracks.active, None
    try:
        track = scope.add_track()
        if track.name != track_name:
            expected = deepcopy(scope.expected)
            scope.track(expected, track)["settings"]["name"] = track_name
            scope.write(expected, lambda: setattr(track, "name", track_name))
        scope.add_strip(track, strip_name, float(start), start+source_end-source_start, action,
                        choices[0] if choices else None, source_start, source_end)
        scope.gate()
    except Exception as error:
        restored = False
        try:
            scope.gate()
            owned = track if track is not None else scope.created_tracks[-1] if scope.created_tracks else None
            if owned is not None:
                expected = deepcopy(scope.expected)
                record = scope.track(expected, owned)
                for strip in record["strips"]:
                    if strip["action"] != action_token(action):
                        raise invalid_argument("Created track acquired foreign strips; cleanup refused.")
                    scope.references(expected, action, -1)
                if previous_active is not None and expected["active_track"] != key(previous_active):
                    active_state = deepcopy(scope.expected)
                    active_state["active_track"] = key(previous_active)
                    scope.write(active_state, lambda: setattr(data.nla_tracks, "active", previous_active))
                    expected["active_track"] = key(previous_active)
                expected["tracks"] = [item for item in expected["tracks"] if item["id"] != key(owned)]
                if expected["active_track"] == key(owned):
                    expected["active_track"] = None
                scope.write(expected, lambda: data.nla_tracks.remove(owned))
            scope.gate()
            restored = had_data and scope.expected == scope.original
        except Exception:
            import logging
            logging.getLogger(__name__).exception("New NLA track recovery refused or failed")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "NLA creation failed; inspect retained tracks and finalized checkpoint.",
                          {"object": scope.name, "execution_started": scope.started or not had_data,
                           "rollback_verified": restored, "possible_mutation": (scope.started or not had_data) and not restored,
                           "retained_track": scope.retained_track(track), "retained_empty_anim_data": not had_data,
                           "verification_required": True}) from error
    return {"affected_objects": [obj.name], **inspect(context, {"object_name": obj.name})}


def _native_float(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def _strip_stage(settings: dict[str, Any], name: str, value: Any) -> dict[str, Any]:
    """Predict reviewed isolated-CLIP RNA setters, including native float storage.

    Mirrors reviewed native RNA semantics, not arbitrary post-setter observation:
    scale/repeat/source-range recalculate end; transform updates clamp blends;
    frame_start/end aliases share storage. Native fixtures prove these on each
    supported development runtime. Global auto-blend validation is predicted
    separately; influence child allocation uses its reviewed native constructor.
    """
    result = dict(settings)
    value = _native_float(float(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    result[name] = value
    if name in {"action_frame_start", "action_frame_end", "scale", "repeat"}:
        length = _native_float(result["action_frame_end"]-result["action_frame_start"])
        if length < 1.:
            raise invalid_argument("Reviewed source Action range must stay at least one frame long.")
        mapping = _native_float(result["scale"]*result["repeat"])
        result["frame_end"] = _native_float(_native_float(length*mapping)+result["frame_start"])
    if not -100_000 <= result["frame_start"] < result["frame_end"] <= 100_000 or result["frame_end"]-result["frame_start"] < 1.:
        raise invalid_argument("Reviewed NLA extents must remain ordered, bounded and at least one frame long.")
    length = _native_float(result["frame_end"]-result["frame_start"])
    if name in {"blend_in", "blend_out"}:
        other = "blend_out" if name == "blend_in" else "blend_in"
        if value < 0 or value > length-result[other]:
            raise invalid_argument("Explicit blend duration must fit the strip without native clamping.")
    if name == "use_auto_blend" and not value:
        result["blend_in"] = result["blend_out"] = 0.

    if name in {"frame_start", "frame_end", "action_frame_start", "action_frame_end", "scale", "repeat"}:
        # The native transform-update uses double intermediates for blend limits.
        total = result["frame_end"]-result["frame_start"]
        result["blend_in"] = _native_float(max(0., min(result["blend_in"], max(0., total-result["blend_out"]))))
        result["blend_out"] = _native_float(max(0., min(result["blend_out"], total-result["blend_in"])))
    for field in ("frame_start", "frame_end"):
        for suffix in ("_raw", "_ui"):
            if field+suffix in result:
                result[field+suffix] = result[field]
    return result


def _native_autoblend(model: dict[str, Any]) -> None:
    """Predict native 4.5/5.2 global validation without mutating any RNA.

    Only reviewed plain strip extents enter the model. Invalid or displaced
    transitions fail before the setter instead of letting native validation
    remove/rewrite them. The caller rejects predicted writes outside its strip.
    """
    tracks = model["tracks"]
    def equal(a: float, b: float) -> bool:
        return abs(a-b) <= 1.1920928955078125e-7
    def overlaps(target: dict[str, Any], neighbors: list[dict[str, Any]]) -> tuple[Any, Any]:
        begin = end = None
        for index, record in enumerate(neighbors):
            other = record["settings"]
            if other["frame_start"] <= target["frame_start"] and other["frame_end"] >= target["frame_end"]:
                return None, None
            if other["frame_end"] < target["frame_start"]:
                continue
            if other["frame_start"] > target["frame_end"]:
                return begin, end
            if (index+1 == len(neighbors) or not equal(neighbors[index+1]["settings"]["frame_start"], other["frame_end"])) and target["frame_start"] < other["frame_end"] < target["frame_end"]:
                begin = other["frame_end"]
            if (index == 0 or not equal(neighbors[index-1]["settings"]["frame_end"], other["frame_start"])) and target["frame_start"] < other["frame_start"] < target["frame_end"]:
                end = other["frame_start"]
        return begin, end
    for index, track in enumerate(tracks):
        strips = track["strips"]
        for at, record in enumerate(strips):
            setting = record["settings"]
            if record["type"] == "TRANSITION" and (at == 0 or at+1 == len(strips)
                    or setting["frame_start"] != strips[at-1]["settings"]["frame_end"]
                    or setting["frame_end"] != strips[at+1]["settings"]["frame_start"]
                    or setting["frame_start"] >= setting["frame_end"]):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native auto-blend validation would rewrite/remove a transition; repair its exact neighbors first.")
            if len(tracks) > 1 and setting.get("use_auto_blend", False):
                ps, pe = overlaps(setting, tracks[index-1]["strips"]) if index else (None, None)
                ns, ne = overlaps(setting, tracks[index+1]["strips"]) if index+1 < len(tracks) else (None, None)
                # The reviewed native condition gives the previous-track endpoint
                # precedence whenever it exists; preserve that exact behavior.
                begin = ps if ps is not None else ns
                end = pe if pe is not None else ne
                setting["blend_in"] = _native_float(begin-setting["frame_start"]) if begin is not None and (at == 0 or not equal(strips[at-1]["settings"]["frame_end"], setting["frame_start"])) else 0.
                setting["blend_out"] = _native_float(setting["frame_end"]-end) if end is not None and (at+1 == len(strips) or not equal(strips[at+1]["settings"]["frame_start"], setting["frame_end"])) else 0.
            length = setting["frame_end"]-setting["frame_start"]
            setting["blend_in"] = _native_float(max(0., min(setting["blend_in"], max(0., length-setting["blend_out"]))))
            setting["blend_out"] = _native_float(max(0., min(setting["blend_out"], length-setting["blend_in"])))


def _strip_expected(scope: _LegacyNlaGuard, model: dict[str, Any], track: Any, strip_id: int, field: str, value: Any) -> dict[str, Any]:
    expected = deepcopy(model)
    record = next(item for item in scope.track(expected, track)["strips"] if item["id"] == strip_id)
    record["settings"] = _strip_stage(record["settings"], field, value)
    if (field == "use_auto_blend" and value) or (field in {"frame_start", "frame_end", "action_frame_start", "action_frame_end", "scale", "repeat"} and record["settings"].get("use_auto_blend", False)):
        _native_autoblend(expected)
        for old_track, new_track in zip(model["tracks"], expected["tracks"], strict=True):
            for before, after in zip(old_track["strips"], new_track["strips"], strict=True):
                if before["id"] != strip_id and before != after:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native automatic blending would change another strip; no cross-strip edits are inferred.",
                                      {"protected_strip_native_id": before["id"]})
    return expected


def _retained_controls(strip: Any) -> Any:
    try:
        return [key(curve) for curve in bounded(strip.fcurves, 8, "retained NLA controls")]
    except Exception:
        return None


def _legacy_failure(error: Exception, scope: _LegacyNlaGuard, *, restored: bool = False, **evidence: Any) -> BridgeError:
    return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                       "NLA edit failed; reinspect retained state and finalized recovery checkpoint.",
                       {**(error.context if isinstance(error, BridgeError) else {}), "object": scope.name,
                        "execution_started": scope.started, "rollback_verified": restored,
                        "possible_mutation": scope.started and not restored,
                        "verification_required": True, **evidence})


def nla_edit(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "track_name", "strip_name", "settings", "remove"})
    _nla_context(context)
    obj = _object(params, True)
    track_name = bounded_name(params.get("track_name"), "track_name")
    strip_name = bounded_name(params.get("strip_name"), "strip_name")
    track = obj.animation_data.nla_tracks.get(track_name) if obj.animation_data else None
    strip = track.strips.get(strip_name) if track else None
    if strip is None or strip.type != "CLIP":
        raise invalid_argument("An exact CLIP strip is required.")
    if track.lock:
        raise invalid_argument("Unlock the NLA track explicitly before editing its strips.")
    remove = params.get("remove", False)
    if type(remove) is not bool:
        raise invalid_argument("remove must be boolean.")
    if remove and params.get("settings"):
        raise invalid_argument("Removal cannot include settings.")
    assignments = []
    if not remove:
        if len(track.strips) != 1:
            raise invalid_argument("Strip timing edits require a single-strip track to avoid overlap side effects.")
        settings = settings_mapping(params)
        for name in ("scale", "repeat"):
            value = settings.get(name)
            if value is not None and (type(value) not in {int, float} or not 0.01 <= value <= 100):
                raise invalid_argument(f"{name} must be between 0.01 and 100.")
        assignments = prepare_assignments(strip, settings, allowed=STRIP_PROPERTIES,
                                         object_pointers=frozenset(), bpy=require_blender())
    scope = _LegacyNlaGuard(context, obj, "nla.edit_strip")
    strip_id = key(strip)
    original = dict(next(item for item in scope.track(scope.expected, track)["strips"] if item["id"] == strip_id)["settings"])
    # Preflight every requested intermediate stage before the first write.
    allocates_influence = any(item.name == "use_animated_influence" and item.value for item in assignments) and not any(curve.data_path == "influence" for curve in strip.fcurves)
    incomplete_controls = scope.expected["control_preferences"] is None or (getattr(strip, "use_animated_time", False) and not any(curve.data_path == "strip_time" for curve in strip.fcurves))
    if allocates_influence and incomplete_controls:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Influence allocation requires reviewed preferences and complete animated-time control scope.")
    prediction = deepcopy(scope.expected)
    for assignment in assignments:
        prediction = _strip_expected(scope, prediction, track, strip_id, assignment.name, assignment.value)
    completed = []
    try:
        if remove:
            expected = deepcopy(scope.expected)
            record = scope.track(expected, track)
            record["strips"] = [item for item in record["strips"] if item["id"] != strip_id]
            scope.references(expected, strip.action, -1)
            scope.write(expected, lambda: track.strips.remove(strip))
        else:
            for assignment in assignments:
                expected = _strip_expected(scope, scope.expected, track, strip_id, assignment.name, assignment.value)
                if assignment.name == "use_animated_influence" and assignment.value and not any(curve.data_path == "influence" for curve in strip.fcurves):
                    scope.influence(track, strip, expected)
                else:
                    scope.write(expected, lambda assignment=assignment: setattr(strip, assignment.name, assignment.value))
                completed.append(assignment.name)
        scope.gate()
    except Exception as error:
        restored = False
        if not remove:
            try:
                scope.gate()
                for name in reversed(completed):
                    expected = _strip_expected(scope, scope.expected, track, strip_id, name, original[name])
                    scope.write(expected, lambda name=name: setattr(strip, name, original[name]))
                scope.gate()
                restored = scope.expected == scope.original
            except Exception:
                import logging
                logging.getLogger(__name__).exception("NLA strip compensation refused or incomplete")
        raise _legacy_failure(error, scope, restored=restored, strip_name=strip_name,
                              removed_strip_requires_checkpoint_recovery=remove and scope.started,
                              retained_control_curve_ids=[] if remove else _retained_controls(strip)) from error
    return {"affected_objects": [obj.name], **inspect(context, {"object_name": obj.name})}


def nla_edit_track(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Rename/mute/lock an exact NLA track, or remove an explicitly empty track."""
    reject_unknown_params(params, {"object_name", "track_name", "settings", "remove"})
    _nla_context(context)
    obj = _object(params, True)
    name = bounded_name(params.get("track_name"), "track_name")
    track = obj.animation_data.nla_tracks.get(name) if obj.animation_data else None
    if track is None:
        raise invalid_argument("Named NLA track does not exist.")
    remove = params.get("remove", False)
    if type(remove) is not bool:
        raise invalid_argument("remove must be boolean.")
    assignments = []
    if remove:
        if params.get("settings") is not None:
            raise invalid_argument("Removal cannot include settings.")
        if track.lock or len(track.strips):
            raise invalid_argument("Track removal requires an unlocked, empty track; strips/actions are never deleted implicitly.")
    else:
        settings = settings_mapping(params)
        if track.lock and (set(settings) != {"lock"} or settings["lock"] is not False):
            raise invalid_argument("A locked track must first be explicitly unlocked with lock=false.")
        if "name" in settings:
            new_name = bounded_name(settings["name"], "name", maximum=63)
            existing = obj.animation_data.nla_tracks.get(new_name)
            if len(new_name.encode("utf-8")) > 63 or (existing is not None and existing != track):
                raise invalid_argument("Track name is unavailable or exceeds 63 UTF-8 bytes.")
        assignments = prepare_assignments(track, settings, allowed=frozenset({"name", "mute", "lock"}),
                                         object_pointers=frozenset(), bpy=require_blender())
    scope = _LegacyNlaGuard(context, obj, "nla.edit_track")
    original, completed = dict(scope.track(scope.expected, track)["settings"]), []
    try:
        if remove:
            expected = deepcopy(scope.expected)
            expected["tracks"] = [item for item in expected["tracks"] if item["id"] != key(track)]
            if expected["active_track"] == key(track):
                expected["active_track"] = None
            scope.write(expected, lambda: obj.animation_data.nla_tracks.remove(track))
        else:
            for assignment in assignments:
                expected = deepcopy(scope.expected)
                scope.track(expected, track)["settings"][assignment.name] = assignment.value
                scope.write(expected, lambda assignment=assignment: setattr(track, assignment.name, assignment.value))
                completed.append(assignment.name)
        scope.gate()
    except Exception as error:
        restored = False
        if not remove:
            try:
                scope.gate()
                for field in reversed(completed):
                    expected = deepcopy(scope.expected)
                    scope.track(expected, track)["settings"][field] = original[field]
                    scope.write(expected, lambda field=field: setattr(track, field, original[field]))
                scope.gate()
                restored = scope.expected == scope.original
            except Exception:
                import logging
                logging.getLogger(__name__).exception("NLA track compensation refused or incomplete")
        raise _legacy_failure(error, scope, restored=restored, previous_track_name=name,
                              removed_track_requires_checkpoint_recovery=remove and scope.started) from error
    return {"affected_objects": [obj.name], "previous_track_name": name,
            "removed": remove, **inspect(context, {"object_name": obj.name})}


def nla_push_down(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Move a standard active action into a new top NLA track without copying its keys."""
    reject_unknown_params(params, {"object_name", "track_name", "strip_name"})
    _nla_context(context)
    obj = _object(params, True)
    names = [bounded_name(params.get(key), key, maximum=63) for key in ("track_name", "strip_name")]
    if any(len(name.encode("utf-8")) > 63 for name in names):
        raise invalid_argument("Track and strip names must fit 63 UTF-8 bytes.")
    data = obj.animation_data
    if not data or not data.action:
        raise invalid_argument("An active action is required for push-down.")
    if (
        not data.use_nla
        or len(data.drivers)
        or any(t.is_solo for t in data.nla_tracks)
        or len(data.nla_tracks) >= 64
        or sum(len(t.strips) for t in data.nla_tracks) >= 256
    ):
        raise invalid_argument(
            "Push-down requires enabled NLA, no drivers/solo tracks, and available track/strip capacity."
        )
    if data.nla_tracks.get(names[0]):
        raise invalid_argument("Push-down requires a new unused track name.")
    if (
        data.action_blend_type != "REPLACE"
        or data.action_influence != 1.0
        or data.action_extrapolation != "HOLD"
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Push-down currently supports REPLACE, influence 1, HOLD active actions only.",
        )
    action, slot = data.action, getattr(data, "action_slot", None)
    if len(getattr(action, "slots", ())) and slot is None:
        raise invalid_argument("The active action needs an explicitly assigned slot.")
    start, end = map(float, action.frame_range)
    if (
        not all(
            math.isfinite(v) and v.is_integer() and -100_000 <= v <= 100_000 for v in (start, end)
        )
        or not 0 < end - start <= 100_000
    ):
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Push-down requires a nonzero integral action range of at most 100000 frames.",
        )
    previous_active = data.nla_tracks.active
    scope = _LegacyNlaGuard(context, obj, "nla.push_down")
    track = strip = None
    try:
        track = scope.add_track()
        if track.name != names[0]:
            expected = deepcopy(scope.expected)
            scope.track(expected, track)["settings"]["name"] = names[0]
            scope.write(expected, lambda: setattr(track, "name", names[0]))
        strip = scope.add_strip(track, names[1], start, end, action, slot)
        # Reviewed native constructor supplies exact timing, REPLACE/HOLD and the
        # matching slot on 4.5/5.2. Influence alone defaults to zero.
        expected = deepcopy(scope.expected)
        scope.track(expected, track)["strips"][0]["settings"]["influence"] = 1.
        scope.write(expected, lambda: setattr(strip, "influence", 1.))
        expected = deepcopy(scope.expected)
        expected["active_action"], expected["slot"] = action_token(None), None
        scope.references(expected, action, -1)
        scope.write(expected, lambda: setattr(data, "action", None))
        if previous_active is not None:
            expected = deepcopy(scope.expected)
            expected["active_track"] = key(previous_active)
            scope.write(expected, lambda: setattr(data.nla_tracks, "active", previous_active))
        scope.gate()
    except Exception as exc:
        restored = False
        try:
            if scope.started:
                scope.gate()
                if scope.expected["active_action"] != action_token(action):
                    expected = deepcopy(scope.expected)
                    expected["active_action"], expected["slot"] = action_token(action), None
                    scope.references(expected, action, 1)
                    scope.write(expected, lambda: setattr(data, "action", action))
                    if slot is not None:
                        expected = deepcopy(scope.expected)
                        expected["slot"] = _nla_slot(slot)
                        scope.write(expected, lambda: setattr(data, "action_slot", slot))
                if previous_active is not None and scope.expected["active_track"] != key(previous_active):
                    expected = deepcopy(scope.expected)
                    expected["active_track"] = key(previous_active)
                    scope.write(expected, lambda: setattr(data.nla_tracks, "active", previous_active))
                if track is not None:
                    expected = deepcopy(scope.expected)
                    owned = scope.track(expected, track)
                    if strip is not None:
                        if [record["id"] for record in owned["strips"]] != [key(strip)]:
                            raise invalid_argument("Created NLA track acquired foreign strips; cleanup refused.")
                        scope.references(expected, action, -1)
                    elif owned["strips"]:
                        raise invalid_argument("Created NLA track acquired foreign strips; cleanup refused.")
                    expected["tracks"] = [record for record in expected["tracks"] if record["id"] != key(track)]
                    if expected["active_track"] == key(track):
                        expected["active_track"] = key(previous_active)
                    scope.write(expected, lambda: data.nla_tracks.remove(track))
                scope.gate()
                restored = scope.expected == scope.original
        except Exception:
            import logging

            logging.getLogger(__name__).exception("NLA push-down recovery refused or failed")
        raise BridgeError(
            exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Action push-down failed; reinspect before retrying.",
            {
                "object": scope.name,
                "execution_started": scope.started,
                "verification_required": True,
                "rollback_performed": restored,
                "rollback_verified": restored,
                "possible_mutation": scope.started and not restored,
                "recovery_skipped_or_incomplete": scope.started and not restored,
                "retained_track": scope.retained_track(track),
            },
        ) from exc
    return {
        "affected_objects": [obj.name],
        "pushed_action": action.name,
        "preserved_slot": getattr(slot, "identifier", None),
        "action_range": [start, end],
        "created_track": track.name,
        "created_strip": strip.name,
        **inspect(context, {"object_name": obj.name}),
    }


def register_tools(registry: Any) -> None:
    for name, handler in (
        ("animation_layers.inspect", inspect),
        ("drivers.add", driver_add),
        ("drivers.remove", driver_remove),
        ("nla.add_strip", nla_add),
        ("nla.edit_strip", nla_edit),
        ("nla.edit_track", nla_edit_track),
        ("nla.solo_track", nla_solo_track),
        ("nla.push_down", nla_push_down),
    ):
        registry.register(
            name,
            handler,
            toolset="animation_layers",
            modifies=handler != inspect,
            permissions=(Permission.INSPECT_SCENE,)
            if handler == inspect
            else (Permission.EDIT_ANIMATION,),
            description=f"Structured animation layer operation: {name}.",
        )


def nla_solo_track(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Set one track's solo state with explicit consent to replace an existing solo."""
    reject_unknown_params(params, {"object_name", "track_name", "enabled", "replace_existing"})
    _nla_context(context)
    obj = _object(params, True)
    name = bounded_name(params.get("track_name"), "track_name")
    enabled = params.get("enabled")
    replace = params.get("replace_existing", False)
    if type(enabled) is not bool or type(replace) is not bool:
        raise invalid_argument(
            "enabled and replace_existing must be booleans; enabled is required."
        )
    data = obj.animation_data
    track = data.nla_tracks.get(name) if data else None
    if track is None or track.lock:
        raise invalid_argument("An exact unlocked NLA track is required.")
    if enabled and (track.mute or not data.use_nla):
        raise invalid_argument(
            "Unmute the target and enable NLA before soloing; neither is changed implicitly."
        )
    others = [t for t in data.nla_tracks if t != track and t.is_solo]
    if enabled and others and not replace:
        raise invalid_argument(
            "Another track is soloed; replace_existing=true is required.",
            solo_tracks=[t.name for t in others],
        )
    if enabled and any(t.lock for t in others):
        raise invalid_argument(
            "An existing solo track is locked; unlock it explicitly before replacement."
        )
    before = [(t, t.is_solo) for t in data.nla_tracks]
    expected = [(t, enabled if t == track else False if enabled else value) for t, value in before]
    scope = _LegacyNlaGuard(context, obj, "nla.solo_track")
    try:
        if enabled:
            for other in others:
                next_state = deepcopy(scope.expected)
                scope.track(next_state, other)["settings"]["is_solo"] = False
                scope.write(next_state, lambda other=other: setattr(other, "is_solo", False))
        if track.is_solo != enabled:
            next_state = deepcopy(scope.expected)
            scope.track(next_state, track)["settings"]["is_solo"] = enabled
            scope.write(next_state, lambda: setattr(track, "is_solo", enabled))
        scope.gate()
        if any(t.is_solo != value for t, value in expected):
            raise RuntimeError("Blender did not retain the requested solo state")
    except Exception as exc:
        restored = False
        try:
            if scope.started:
                scope.gate()
                # Restore false flags before true flags, and only settings that
                # still exactly match this operation's known partial state.
                for desired in (False, True):
                    for item, value in before:
                        if value == desired and scope.track(scope.expected, item)["settings"]["is_solo"] != value:
                            next_state = deepcopy(scope.expected)
                            scope.track(next_state, item)["settings"]["is_solo"] = value
                            scope.write(next_state, lambda item=item, value=value: setattr(item, "is_solo", value))
                scope.gate()
                restored = scope.expected == scope.original
        except Exception:
            import logging

            logging.getLogger(__name__).exception("NLA solo recovery refused or failed")
        raise BridgeError(
            exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Solo edit failed; reinspect animation layers.",
            {
                "object": scope.name,
                "execution_started": scope.started,
                "verification_required": True,
                "rollback_performed": restored,
                "rollback_verified": restored,
                "possible_mutation": scope.started and not restored,
                "recovery_skipped_or_incomplete": scope.started and not restored,
            },
        ) from exc
    return {
        "affected_objects": [obj.name],
        "changed_tracks": [t.name for t, value in before if t.is_solo != value],
        "solo_before": [t.name for t, value in before if value],
        "solo_after": [t.name for t in data.nla_tracks if t.is_solo],
        "playback_scope": "Solo excludes other NLA tracks and the active action from evaluation; their data is preserved.",
        **inspect(context, {"object_name": obj.name}),
    }
