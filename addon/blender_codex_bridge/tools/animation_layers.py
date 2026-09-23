"""Non-scripted transform drivers and explicit action-backed NLA strips."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import invalid_argument
from ..permissions import Permission
from ..utils import get_object, int_param, reject_unknown_params, require_blender
from ._rna import apply_assignments, bounded_name, prepare_assignments, settings_mapping
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
    reject_unknown_params(params, {"object_name", "data_path", "index", "driver_type", "variables"})
    obj = _object(params, True)
    path, index = _channel(params)
    kind = params.get("driver_type", "AVERAGE")
    if obj.animation_data and len(obj.animation_data.drivers) >= 128:
        raise invalid_argument("Driver limit reached.")
    if not isinstance(kind, str) or kind not in {"AVERAGE", "SUM", "MIN", "MAX"}:
        raise invalid_argument("Only non-scripted AVERAGE, SUM, MIN and MAX drivers are supported.")
    if path == "rotation_euler" and obj.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
        raise invalid_argument("Euler rotation drivers require an Euler rotation mode.")
    data = obj.animation_data
    if data and (
        any(c.data_path == path and c.array_index == index for c in data.drivers)
        or data.action
        or len(data.nla_tracks)
    ):
        raise invalid_argument(
            "Driver target must have no existing driver on the channel, active action or NLA tracks."
        )
    variables = params.get("variables")
    if not isinstance(variables, list) or not 1 <= len(variables) <= 8:
        raise invalid_argument("variables must contain 1-8 transform sources.")
    prepared = []
    for variable in variables:
        if not isinstance(variable, Mapping) or set(variable) != {
            "object_name",
            "transform_type",
            "transform_space",
        }:
            raise invalid_argument(
                "Each variable requires object_name, transform_type and transform_space."
            )
        target = get_object(variable["object_name"], allow_active=False)
        if (
            target == obj
            or target.parent is not None
            or len(target.constraints)
            or target.animation_data is not None
        ):
            raise invalid_argument(
                "Driver sources must be distinct, independent objects without animation/drivers/constraints; cyclic or indirect dependencies are not inferred."
            )
        if (
            not all(isinstance(v, str) for v in variable.values())
            or variable["transform_type"] not in TRANSFORMS
            or variable["transform_space"] not in {"WORLD_SPACE", "LOCAL_SPACE", "TRANSFORM_SPACE"}
        ):
            raise invalid_argument("Unsupported transform channel or space.")
        prepared.append((target, variable["transform_type"], variable["transform_space"]))
    had_data = data is not None
    curve = obj.driver_add(path, index)
    try:
        curve.driver.type = kind
        for variable in list(curve.driver.variables):
            curve.driver.variables.remove(variable)
        for i, (target, transform, space) in enumerate(prepared):
            variable = curve.driver.variables.new()
            variable.name = f"source_{i}"
            variable.type = "TRANSFORMS"
            variable.targets[0].id = target
            variable.targets[0].transform_type = transform
            variable.targets[0].transform_space = space
    except Exception:
        obj.driver_remove(path, index)
        if not had_data:
            obj.animation_data_clear()
        raise
    obj.update_tag()
    require_blender().context.view_layer.update()
    return {"affected_objects": [obj.name], **inspect(context, {"object_name": obj.name})}


def driver_remove(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "data_path", "index"})
    obj = _object(params, True)
    path, index = _channel(params)
    if not obj.animation_data or not any(
        c.data_path == path and c.array_index == index for c in obj.animation_data.drivers
    ):
        raise invalid_argument("Driver does not exist on the named channel.")
    obj.driver_remove(path, index)
    return {"affected_objects": [obj.name], **inspect(context, {"object_name": obj.name})}


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
    had_data = obj.animation_data is not None
    data = obj.animation_data_create()
    if len(data.nla_tracks) >= 64:
        raise invalid_argument("NLA track limit reached.")
    track = data.nla_tracks.new()
    try:
        track.name = track_name
        strip = track.strips.new(strip_name, start, action)
        strip.name = strip_name
        if choices:
            strip.action_slot = choices[0]
    except Exception:
        data.nla_tracks.remove(track)
        if not had_data:
            obj.animation_data_clear()
        raise
    return {"affected_objects": [obj.name], **inspect(context, {"object_name": obj.name})}


def nla_edit(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "track_name", "strip_name", "settings", "remove"})
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
    if remove:
        if params.get("settings"):
            raise invalid_argument("Removal cannot include settings.")
        track.strips.remove(strip)
    else:
        if len(track.strips) != 1:
            raise invalid_argument(
                "Strip timing edits require a single-strip track to avoid overlap side effects."
            )
        settings = settings_mapping(params)
        for name in ("scale", "repeat"):
            value = settings.get(name)
            if value is not None and (type(value) not in {int, float} or not 0.01 <= value <= 100):
                raise invalid_argument(f"{name} must be between 0.01 and 100.")
        apply_assignments(
            strip,
            prepare_assignments(
                strip,
                settings,
                allowed=STRIP_PROPERTIES,
                object_pointers=frozenset(),
                bpy=require_blender(),
            ),
        )
    return {"affected_objects": [obj.name], **inspect(context, {"object_name": obj.name})}


def nla_edit_track(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Rename/mute/lock an exact NLA track, or remove an explicitly empty track."""
    reject_unknown_params(params, {"object_name", "track_name", "settings", "remove"})
    obj = _object(params, True)
    name = bounded_name(params.get("track_name"), "track_name")
    track = obj.animation_data.nla_tracks.get(name) if obj.animation_data else None
    if track is None:
        raise invalid_argument("Named NLA track does not exist.")
    remove = params.get("remove", False)
    if type(remove) is not bool:
        raise invalid_argument("remove must be boolean.")
    if remove:
        if params.get("settings") is not None:
            raise invalid_argument("Removal cannot include settings.")
        if track.lock or len(track.strips):
            raise invalid_argument(
                "Track removal requires an unlocked, empty track; strips/actions are never deleted implicitly."
            )
        obj.animation_data.nla_tracks.remove(track)
    else:
        settings = settings_mapping(params)
        if track.lock and (set(settings) != {"lock"} or settings["lock"] is not False):
            raise invalid_argument(
                "A locked track must first be explicitly unlocked with lock=false."
            )
        if "name" in settings:
            new_name = bounded_name(settings["name"], "name", maximum=63)
            existing = obj.animation_data.nla_tracks.get(new_name)
            if len(new_name.encode("utf-8")) > 63 or (existing is not None and existing != track):
                raise invalid_argument("Track name is unavailable or exceeds 63 UTF-8 bytes.")
        apply_assignments(
            track,
            prepare_assignments(
                track,
                settings,
                allowed=frozenset({"name", "mute", "lock"}),
                object_pointers=frozenset(),
                bpy=require_blender(),
            ),
        )
    return {
        "affected_objects": [obj.name],
        "previous_track_name": name,
        "removed": remove,
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
