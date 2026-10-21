"""Reviewed native NLA child constructors and complete bounded control snapshots."""

from __future__ import annotations

from typing import Any

from ..errors import BridgeError, ErrorCode
from ._animation_scope import bounded, curve_content, key, rna_state


def controls(strip: Any) -> tuple[Any, ...]:
    result, seen = [], set()
    for curve in bounded(strip.fcurves, 8, "NLA control curves"):
        channel = (curve.data_path, int(curve.array_index))
        if (channel not in {("influence", 0), ("strip_time", 0)} or channel in seen
                or getattr(curve, "driver", None) is not None or len(curve.keyframe_points) > 256):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "NLA controls require unique influence/strip_time channels, at most 256 keys each and no drivers.")
        seen.add(channel)
        result.append((key(curve), curve_content(curve)))
    return tuple(result)


def new_clip(strip: Any, name: str, start: float, end: float, source_start: float,
             source_end: float, action: Any, slot: Any) -> bool:
    """Validate the complete reviewed 4.5/5.2 native constructor, never adopt callbacks."""
    expected = {"name": name, "type": "CLIP", "extrapolation": "HOLD", "blend_type": "REPLACE",
                "frame_start": start, "frame_end": end, "frame_start_raw": start, "frame_end_raw": end,
                "frame_start_ui": start, "frame_end_ui": end, "blend_in": 0., "blend_out": 0.,
                "use_auto_blend": False, "action_frame_start": source_start, "action_frame_end": source_end,
                "repeat": 1., "scale": 1., "influence": 0., "strip_time": 0.,
                "use_animated_influence": False, "use_animated_time": False,
                "use_animated_time_cyclic": bool(getattr(action, "use_cyclic", False)),
                "select": True, "mute": False, "use_reverse": False,
                "use_sync_length": not bool(getattr(action, "use_frame_range", False))}
    actual = dict(rna_state(strip, exclude=frozenset({"action", "action_slot", "action_slot_handle", "last_slot_identifier"})))
    return (strip.type == "CLIP" and not strip.active and strip.action == action
            and getattr(strip, "action_slot", None) == slot and not controls(strip)
            and not len(strip.modifiers) and not len(strip.strips)
            and all(name in expected and value == expected[name] for name, value in actual.items())
            and all(not hasattr(strip, name) or getattr(strip, name) == value for name, value in expected.items()))


def new_influence(curve: Any, strip_settings: dict[str, Any], preferences: Any) -> bool:
    """Native allocation is one retained key using the user's existing preferences."""
    expected_curve = {"array_index": 0, "auto_smoothing": preferences.fcurve_new_auto_smoothing,
        "color": (0., 0., 0.), "color_mode": "AUTO_RAINBOW", "data_path": "influence",
        "extrapolation": "CONSTANT", "group": None, "hide": False, "is_valid": True,
        "lock": False, "mute": False, "select": True}
    point = (strip_settings["frame_start"], strip_settings["influence"])
    expected_key = {"amplitude": 0., "back": 0., "co": point, "co_ui": point,
        "easing": "AUTO", "handle_left": (0., 0.), "handle_left_type": preferences.keyframe_new_handle_type,
        "handle_right": (0., 0.), "handle_right_type": preferences.keyframe_new_handle_type,
        "interpolation": preferences.keyframe_new_interpolation_type, "period": 0.,
        "select_control_point": False, "select_left_handle": False, "select_right_handle": False,
        "type": "KEYFRAME"}
    return (getattr(curve, "driver", None) is None and not len(curve.modifiers) and not len(curve.sampled_points)
            and len(curve.keyframe_points) == 1 and dict(rna_state(curve)) == expected_curve
            and dict(rna_state(curve.keyframe_points[0])) == expected_key)


def new_transition(strip: Any, name: str, start: float, end: float) -> bool:
    """Complete native transition constructor demonstrated on 4.5/5.2."""
    expected = {"name": name, "type": "TRANSITION", "action": None, "action_slot": None,
                "action_slot_handle": 0, "last_slot_identifier": "", "extrapolation": "HOLD",
                "blend_type": "REPLACE", "frame_start": start, "frame_end": end,
                "frame_start_raw": start, "frame_end_raw": end, "frame_start_ui": start,
                "frame_end_ui": end, "blend_in": 0., "blend_out": 0., "use_auto_blend": True,
                "action_frame_start": 0., "action_frame_end": 0., "repeat": 1., "scale": 1.,
                "influence": 0., "strip_time": 0., "use_animated_influence": False,
                "use_animated_time": False, "use_animated_time_cyclic": False,
                "select": True, "mute": False, "use_reverse": False, "use_sync_length": False}
    actual = dict(rna_state(strip))
    return (strip.type == "TRANSITION" and not strip.active and not controls(strip)
            and not len(strip.modifiers) and not len(strip.strips)
            and all(name in expected and value == expected[name] for name, value in actual.items())
            and all(not hasattr(strip, name) or getattr(strip, name) == value for name, value in expected.items()))
