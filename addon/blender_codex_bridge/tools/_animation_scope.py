"""Bounded callback-free animation content, reference and write-boundary guards."""

from __future__ import annotations

import hashlib
import json
import math
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ._object_safety import require_local_editable_id, require_local_object
from ._object_scope import _ordinary_scene_membership, require_collection_scope


def key(owner: Any) -> int | None:
    return None if owner is None else int(owner.as_pointer()) if hasattr(owner, "as_pointer") else id(owner)


def action_token(action: Any) -> tuple[int | None, Any]:
    return key(action), None if action is None else getattr(action, "session_uid", None)


def value(raw: Any) -> Any:
    if raw is None or isinstance(raw, (bool, int, str)):
        if isinstance(raw, str) and len(raw) > 1024:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation string evidence exceeds 1024 characters.")
        return raw
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation evidence contains a nonfinite value.")
        return raw
    if hasattr(raw, "as_pointer") or hasattr(raw, "name"):
        if hasattr(raw, "library") and hasattr(raw, "users"):
            return ("ID", *action_token(raw))
        return ("RNA", getattr(getattr(raw, "bl_rna", None), "identifier", type(raw).__name__), getattr(raw, "name", None))
    items = list(islice(iter(raw), 257))
    if len(items) > 256:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation property arrays exceed 256 entries.")
    return tuple(value(item) for item in items)


def rna_state(owner: Any, *, exclude: frozenset[str] = frozenset()) -> tuple[Any, ...]:
    """Read trusted RNA descriptors only; never resolve caller-supplied RNA paths."""
    rna = getattr(owner, "bl_rna", None)
    if rna is None:
        fields = ("name", "data_path", "array_index", "extrapolation", "mute", "lock", "select", "is_solo",
                  "influence", "blend_type", "frame_start", "frame_end", "action_frame_start", "action_frame_end",
                  "scale", "repeat", "use_auto_blend", "blend_in", "blend_out", "type", "socket_type",
                  "use_nla", "use_tweak_mode", "action_blend_type", "action_extrapolation", "action_influence",
                  "co", "interpolation", "easing", "handle_left", "handle_right", "handle_left_type", "handle_right_type")
        return tuple((field, value(getattr(owner, field))) for field in fields if field not in exclude and hasattr(owner, field))
    if len(rna.properties) > 256:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation RNA inventory exceeds 256 fields.")
    result: list[tuple[str, Any]] = []
    for prop in rna.properties:
        if prop.is_readonly or prop.identifier in exclude:
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation property kind needs an explicit bounded content reader.")
        result.append((prop.identifier, value(getattr(owner, prop.identifier))))
    if getattr(rna, "identifier", None) == "ActionGroup" and hasattr(owner, "colors"):
        result.append(("__colors__", rna_state(owner.colors)))
    return tuple(result)


def bounded(items: Any, maximum: int, label: str) -> list[Any]:
    result = list(islice(items, maximum+1))
    if len(result) > maximum:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, f"Animation {label} exceeds {maximum} entries.")
    return result


def curve_inventory(action: Any) -> list[tuple[int | None, Any]]:
    if not getattr(action, "is_action_layered", False):
        return [(None, curve) for curve in bounded(action.fcurves, 1024, "curves")]
    bounded(action.slots, 64, "slots")
    result: list[tuple[int | None, Any]] = []
    for layer in bounded(action.layers, 16, "layers"):
        for strip in bounded(layer.strips, 32, "layer strips"):
            bags = getattr(strip, "channelbags", None)
            if bags is None:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Layered Action has no reviewed channelbag API.")
            for bag in bounded(bags, 64, "channelbags"):
                result.extend((bag.slot_handle, curve) for curve in bounded(bag.fcurves, 1024, "curves"))
                if len(result) > 1024:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action exceeds 1024 total curves.")
    return result


def curve_content(curve: Any) -> tuple[Any, ...]:
    points = bounded(curve.keyframe_points, 1024, "curve keyframes")
    if len(getattr(curve, "sampled_points", ())):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Sampled curves require a separate lifecycle contract.")
    modifiers = []
    for modifier in bounded(getattr(curve, "modifiers", ()), 32, "curve modifiers"):
        controls: tuple[Any, ...] = ()
        if hasattr(modifier, "control_points"):
            controls = tuple(rna_state(point) for point in bounded(modifier.control_points, 256, "envelope controls"))
        modifiers.append((rna_state(modifier), controls))
    return (rna_state(curve), tuple(rna_state(point) for point in points), tuple(modifiers))


def action_content(action: Any) -> tuple[Any, ...]:
    """Semantic content excludes identity/name/users/fake flags and runtime slot users."""
    if getattr(action, "asset_data", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Asset-marked Actions require a separate asset lifecycle contract.")
    if hasattr(action, "keys") and len(action.keys()):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Actions with custom properties require a broader lifecycle snapshot.")
    curves = curve_inventory(action)
    if sum(len(curve.keyframe_points) for _, curve in curves) > 16384 or sum(len(getattr(curve, "modifiers", ())) for _, curve in curves) > 256:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action exceeds 16384 total keys or 256 total modifiers.")
    slots = tuple((slot.identifier, int(slot.handle), slot.target_id_type) for slot in bounded(getattr(action, "slots", ()), 64, "slots"))
    layers, total_bags, total_strips, total_groups = [], 0, 0, 0
    for layer in bounded(getattr(action, "layers", ()), 16, "layers"):
        strips = []
        for strip in bounded(layer.strips, 32, "layer strips"):
            total_strips += 1
            bags = []
            for bag in bounded(getattr(strip, "channelbags", ()), 64, "channelbags"):
                total_bags += 1
                groups = bounded(getattr(bag, "groups", ()), 256, "channel groups")
                total_groups += len(groups)
                if total_strips > 64 or total_bags > 64 or total_groups > 256:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action schema exceeds 64 total layer strips/channelbags or 256 groups.")
                bags.append((bag.slot_handle, tuple(rna_state(group) for group in groups)))
            strips.append((rna_state(strip), tuple(bags)))
        layers.append((rna_state(layer), tuple(strips)))
    metadata = rna_state(action, exclude=frozenset({"name", "use_fake_user", "use_extra_user"}))
    markers = tuple(rna_state(marker) for marker in bounded(getattr(action, "pose_markers", ()), 256, "pose markers"))
    legacy_groups = tuple(rna_state(group) for group in bounded(getattr(action, "groups", ()), 256, "legacy groups")) if not getattr(action, "is_action_layered", False) else ()
    return metadata, slots, tuple(layers), tuple((handle, curve_content(curve)) for handle, curve in curves), markers, legacy_groups


def action_users(bpy: Any, action: Any) -> dict[str, Any]:
    direct = bounded(bpy.data.user_map(subset={action}).get(action, ()), 100, "Action direct users")
    records = []
    for owner in direct:
        count = int(owner.user_of_id(action))
        if not 0 < count <= 256:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action reference count is outside the reviewed range.")
        records.append((key(owner), getattr(owner, "session_uid", None), owner.name,
                        getattr(getattr(owner, "bl_rna", None), "identifier", "unknown"), count,
                        owner.library is None and owner.override_library is None and bool(owner.is_editable)))
    fake, users = bool(action.use_fake_user), int(action.users)
    if sum(record[4] for record in records) != users-int(fake):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native Action users include unaccounted references; no lifecycle mutation is inferred.")
    return {"users": users, "fake_user": fake, "references": tuple(sorted(records, key=lambda record: record[0])),
            "real_users": users-int(fake), "direct_users_complete": True}


def digest(content: Any) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def object_scope(bpy: Any, obj: Any) -> None:
    require_local_object(obj, operation="Animation lifecycle")
    if bpy.context.view_layer.objects.get(obj.name) != obj or len(obj.users_scene) != 1 or obj.users_scene[0] != bpy.context.scene:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation targets require one current-scene/view-layer owner.")
    for collection in obj.users_collection:
        require_collection_scope(bpy, collection, operation="Animation lifecycle")


def affected_scope(bpy: Any, obj: Any, names: Any, *, additional_roots: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    if not isinstance(names, list) or len(names) > 31 or any(not isinstance(item, str) for item in names) or len(set(names)) != len(names):
        raise invalid_argument("affected_objects must explicitly list at most 31 distinct dependent object names.")
    roots = (obj, *additional_roots)
    if len(roots) > 32 or len({key(item) for item in roots}) != len(roots):
        raise invalid_argument("Animation scope requires at most 32 distinct root objects.")
    expected = []
    for exact in names:
        matches = list(islice((item for item in bpy.context.scene.objects if item.name == exact), 2))
        if len(matches) != 1 or matches[0] in roots:
            raise invalid_argument("Each affected object must resolve exactly and exclude the animation target.")
        expected.append(matches[0])
    pending = list(roots)
    seen: set[int | None] = set()
    records: list[tuple[Any, ...]] = []
    while pending:
        current = pending.pop()
        if key(current) in seen:
            continue
        if len(seen) >= 32:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation affected-object closure exceeds 32 objects.")
        seen.add(key(current))
        object_scope(bpy, current)
        for owner in bounded(bpy.data.user_map(subset={current}).get(current, ()), 100, "object consumers"):
            if any(key(owner) == key(collection) and collection.user_of_id(current) == 1 for collection in current.users_collection) or _ordinary_scene_membership(bpy.context.scene, owner, current):
                continue
            scene = bpy.context.scene
            particle = getattr(getattr(scene, "tool_settings", None), "particle_edit", None)
            if key(owner) == key(scene) and particle is not None and getattr(particle, "object", None) == current:
                layers = bounded(scene.view_layers, 256, "view layers")
                root_links = int(scene.collection.objects.get(current.name) == current)
                bases = sum(layer.objects.get(current.name) == current for layer in layers)
                # Native parenting can retain a read-only particle-edit context
                # object. Account for this exact additional reference, preserve
                # its settings, and reject every unexplained Scene reference.
                if scene.collection.user_of_id(current) == root_links and scene.user_of_id(current) == root_links+bases+1:
                    brush = getattr(particle, "brush", None)
                    records.append((key(current), key(scene), root_links+bases+1, "PARTICLE_EDIT_CONTEXT", key(particle),
                                    rna_state(particle), None if brush is None else rna_state(brush)))
                    continue
            explicit_root = bool(additional_roots) and owner in roots and owner != current
            if (owner not in expected and not explicit_root) or getattr(getattr(owner, "bl_rna", None), "identifier", None) != "Object":
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation has consumers outside its explicit object scope.", {"object": current.name, "consumer": getattr(owner, "name", None)})
            count = int(owner.user_of_id(current))
            if not 0 < count <= 256:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation consumer reference count exceeds the reviewed range.")
            records.append((key(current), key(owner), count))
            pending.append(owner)
    if seen != {key(item) for item in (*roots, *expected)}:
        raise invalid_argument("affected_objects must match the complete reviewed direct-object closure.")
    return tuple(sorted((key(item), getattr(item, "session_uid", None), item.name, key(getattr(item, "data", None))) for item in (*roots, *expected))), tuple(sorted(records))


class Guard:
    def __init__(self, bpy: Any, context: Any, method: str):
        self.bpy, self.context, self.method = bpy, context, method
        self.session = (key(bpy.context.scene), key(bpy.context.view_layer), bpy.data.filepath, bpy.context.mode)
        self.ids: list[tuple[Any, Any, Any]] = []

    def remember(self, owner: Any, storage: Any = None) -> None:
        self.ids.append((owner, action_token(owner), storage))

    def gate(self, *permissions: Permission) -> None:
        if self.context.check_cancelled:
            self.context.check_cancelled()
        self.context.require(Permission.EDIT_ANIMATION, *permissions)
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.prepare(self.method, self.context)
        if self.context.check_cancelled:
            self.context.check_cancelled()
        if registry is not None and registry.get(self.method).toolset not in registry.enabled_toolsets:
            raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Animation toolset was disabled during live authorization.")
        flags = self.context.state.snapshot()
        if flags.get("emergency_stopped"):
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Animation mutation emergency-stopped.")
        if flags.get("paused"):
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Animation mutation paused.")
        try:
            stable = self.session == (key(self.bpy.context.scene), key(self.bpy.context.view_layer), self.bpy.data.filepath, self.bpy.context.mode)
            stable = stable and self.bpy.context.mode in {"OBJECT", "POSE"}
            stable = stable and all(action_token(owner) == token and (storage is None or storage.get(owner.name) == owner) for owner, token, storage in self.ids)
        except (ReferenceError, AttributeError):
            stable = False
        if not stable:
            raise invalid_argument("Animation session or exact ID identity changed; writes and compensation refused.")


def editable_action(action: Any) -> None:
    require_local_editable_id(action, operation="Action lifecycle")


def slot_for(action: Any, identifier: Any) -> Any:
    if not getattr(action, "is_action_layered", False):
        if identifier is not None:
            raise invalid_argument("Legacy Actions do not have slots.")
        return None
    if not isinstance(identifier, str) or not identifier:
        raise invalid_argument("Layered Action binding requires an explicit slot_identifier.")
    matches = [slot for slot in bounded(action.slots, 64, "slots") if slot.identifier == identifier and slot.target_id_type == "OBJECT"]
    if len(matches) != 1:
        raise invalid_argument("slot_identifier must resolve exactly one OBJECT slot.")
    return matches[0]


def slot_identity(slot: Any) -> Any:
    return None if slot is None else (key(slot), slot.identifier, int(slot.handle), slot.target_id_type)


def validate_channel(obj: Any, path: str, index: int) -> tuple[Any, ...]:
    """Resolve one reviewed own-object/pose transform or numeric-control channel."""
    owner = obj
    if len(path) > 512:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action channel path exceeds 512 characters.")
    suffix = path
    if path.startswith("pose.bones["):
        try:
            bone_name, end = json.JSONDecoder().raw_decode(path, len("pose.bones["))
        except (ValueError, TypeError) as error:
            raise invalid_argument("Action has an unsupported pose-bone path.") from error
        if not isinstance(bone_name, str) or end >= len(path) or path[end] != "]" or obj.type != "ARMATURE" or len(obj.pose.bones) > 256:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action pose channel needs a reviewed exact armature bone.")
        owner = obj.pose.bones.get(bone_name)
        if owner is None:
            raise invalid_argument("Action channel addresses a missing pose bone.", bone_name=bone_name)
        require_local_editable_id(obj.data, operation="Pose Action binding")
        prefix = "pose.bones[" + json.dumps(bone_name, ensure_ascii=False) + "]"
        if not path.startswith(prefix):
            raise invalid_argument("Action bone path must use the exact canonical escaped name.")
        suffix = path[len(prefix):]
        if suffix.startswith("."):
            suffix = suffix[1:]
        elif not suffix.startswith("["):
            raise invalid_argument("Action bone transform path is missing its property separator.")
    transforms = {"location": 3, "scale": 3, "rotation_euler": 3, "rotation_quaternion": 4, "rotation_axis_angle": 4}
    if suffix in transforms:
        if not 0 <= index < transforms[suffix]:
            raise invalid_argument("Action transform component is out of range.")
        mode = getattr(owner, "rotation_mode", "XYZ")
        if (suffix == "rotation_euler" and mode in {"QUATERNION", "AXIS_ANGLE"}) or (suffix == "rotation_quaternion" and mode != "QUATERNION") or (suffix == "rotation_axis_angle" and mode != "AXIS_ANGLE"):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action rotation channels must match the existing object/bone rotation mode.")
    elif suffix.startswith("[") and suffix.endswith("]"):
        try:
            control = json.loads(suffix[1:-1])
        except (ValueError, TypeError) as error:
            raise invalid_argument("Action numeric-control path is unsupported.") from error
        if not isinstance(control, str) or control.startswith("_") or suffix != "["+json.dumps(control, ensure_ascii=False)+"]" or control not in owner or index not in {0, -1}:
            raise invalid_argument("Action control must name one existing numeric object/pose property.")
        number = owner[control]
        if isinstance(number, bool) or not isinstance(number, (float, int)) or abs(number) > 1e6 or not math.isfinite(number):
            raise invalid_argument("Animated control must be finite numeric data within +/-1000000.")
    else:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action binding supports own transform channels and exact numeric controls, not arbitrary RNA or shared data paths.")
    return key(owner), path, index


def validate_slot(obj: Any, action: Any, slot: Any) -> tuple[Any, ...]:
    """Resolve only reviewed own-object/pose transform and numeric-control paths."""
    result, seen = [], set()
    for handle, curve in curve_inventory(action):
        if slot is not None and handle != slot.handle:
            continue
        path, index = curve.data_path, int(curve.array_index)
        identity = validate_channel(obj, path, index)
        if (path, index) in seen:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Multiple layered curves address the same bound channel.")
        seen.add((path, index))
        result.append(identity)
    return tuple(result)


def binding(obj: Any) -> Any:
    data = obj.animation_data
    return None if data is None else (action_token(data.action), slot_identity(getattr(data, "action_slot", None)))


def animation_context(obj: Any) -> Any:
    data = obj.animation_data
    if data is None:
        return None
    if data.use_tweak_mode or len(data.drivers):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action lifecycle currently requires no tweak mode or drivers on its binding owner.")
    tracks, strip_count = [], 0
    for track in bounded(data.nla_tracks, 64, "NLA tracks"):
        strips = []
        for strip in bounded(track.strips, 256, "NLA strips"):
            strip_count += 1
            if strip_count > 256 or strip.type not in {"CLIP", "TRANSITION"}:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding context supports at most 256 CLIP/TRANSITION strips.")
            strips.append((key(strip), rna_state(strip, exclude=frozenset({"action", "action_slot", "action_slot_handle"})),
                           action_token(strip.action), slot_identity(getattr(strip, "action_slot", None)),
                           tuple(curve_content(curve) for curve in bounded(strip.fcurves, 16, "strip curves")),
                           tuple(rna_state(modifier) for modifier in bounded(strip.modifiers, 32, "strip modifiers"))))
        tracks.append((key(track), rna_state(track), tuple(strips)))
    return (key(data), rna_state(data, exclude=frozenset({"action", "action_slot", "action_slot_handle", "last_slot_identifier"})),
            key(data.nla_tracks.active), tuple(tracks))
