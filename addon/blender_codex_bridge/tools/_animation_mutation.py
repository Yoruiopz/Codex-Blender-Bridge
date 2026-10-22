"""Live boundaries for timeline changes and one native keyframe mutation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from . import _animation_scope as scope
from ._object_safety import require_local_editable_id, require_owned_action

FRAME_FIELDS = ("frame_current", "frame_subframe")
RANGE_FIELDS = ("frame_start", "frame_end", "use_preview_range", "frame_preview_start", "frame_preview_end")


class Timeline:
    def __init__(self, bpy: Any, context: Any, method: str):
        self.bpy, self.context, self.method, self.scene = bpy, context, method, bpy.context.scene
        require_local_editable_id(self.scene, operation=method)
        self.session = (scope.action_token(self.scene), scope.key(bpy.context.view_layer), bpy.context.mode, bpy.data.filepath)
        self.expected = self.observe()
        self.started = False

    def observe(self) -> dict[str, Any]:
        return {field: getattr(self.scene, field) for field in (*FRAME_FIELDS, *RANGE_FIELDS)}

    def measured_state(self) -> dict[str, Any]:
        try:
            return {"observed_timeline": self.observe(), "timeline_identity_observed": True}
        except (ReferenceError, AttributeError):
            return {"observed_timeline": None, "timeline_identity_observed": False}

    def gate(self) -> None:
        if self.context.check_cancelled:
            self.context.check_cancelled()
        self.context.require(Permission.EDIT_ANIMATION)
        if self.context.registry is not None:
            self.context.registry.prepare(self.method, self.context)
        flags = self.context.state.snapshot()
        if flags["emergency_stopped"]:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Timeline mutation emergency-stopped.")
        if flags["paused"]:
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Timeline mutation paused.")
        require_local_editable_id(self.scene, operation=self.method)
        current = (scope.action_token(self.bpy.context.scene), scope.key(self.bpy.context.view_layer), self.bpy.context.mode, self.bpy.data.filepath)
        if current != self.session or self.bpy.data.scenes.get(self.scene.name) != self.scene:
            raise invalid_argument("Timeline scene, view layer, mode, project or exact ID changed.")

    def check(self) -> None:
        self.gate()
        if self.observe() != self.expected:
            raise invalid_argument("Timeline changed outside this operation; stale writes or compensation refused.")

    def write(self, field: str, value: Any) -> None:
        self.check()
        if self.expected[field] == value:
            return
        self.started = True
        predicted = dict(self.expected)
        if field == "use_preview_range" and value and self.expected["frame_preview_start"] == self.expected["frame_preview_end"] == 0:
            # Reviewed official RNA: enabling an unset preview initializes it.
            predicted.update(frame_preview_start=self.expected["frame_start"], frame_preview_end=self.expected["frame_end"])
        elif field == "frame_preview_start" and not self.expected["use_preview_range"]:
            predicted["frame_preview_end"] = self.expected["frame_end"]
        elif field == "frame_preview_end" and not self.expected["use_preview_range"]:
            predicted["frame_preview_start"] = self.expected["frame_start"]
        predicted[field] = value
        if field == "frame_preview_start" and value > predicted["frame_preview_end"]:
            predicted["frame_preview_end"] = value
        elif field == "frame_preview_end" and value < predicted["frame_preview_start"]:
            predicted["frame_preview_start"] = value
        try:
            setattr(self.scene, field, value)
        finally:
            observed = self.observe()
            if observed == predicted:
                self.expected = observed
        if observed != predicted:
            raise invalid_argument("Native timeline setter changed fields outside its exact predicted write.", field=field, requested=value, predicted_timeline=predicted, observed_timeline=observed)

    def apply_range(self, desired: Mapping[str, Any]) -> None:
        fields = ("frame_end", "frame_start") if desired["frame_start"] > self.expected["frame_end"] else ("frame_start", "frame_end")
        for field in fields:
            self.write(field, desired[field])
        # A valid ordering avoids Blender's automatic min/max clamping.
        if "frame_preview_start" in desired:
            # Disabled preview setters reset the opposite bound to the main
            # range. Configure while enabled, then restore the desired flag.
            self.write("use_preview_range", True)
            fields = ("frame_preview_end", "frame_preview_start") if desired["frame_preview_start"] > self.expected["frame_preview_end"] else ("frame_preview_start", "frame_preview_end")
            for field in fields:
                self.write(field, desired[field])
        self.write("use_preview_range", desired["use_preview_range"])
        self.check()
        if any(self.expected[field] != value for field, value in desired.items() if field in RANGE_FIELDS):
            raise invalid_argument("Native playback/preview range did not retain every requested bound.")


def failed(error: Exception, message: str, *, started: bool, restored: bool = False, **evidence: Any) -> BridgeError:
    return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED, message,
                       {**(error.context if isinstance(error, BridgeError) else {}), "execution_started": started,
                        "rollback_verified": restored, "possible_mutation": started and not restored,
                        "verification_required": True, **evidence})


def retained_action(obj: Any) -> dict[str, Any]:
    try:
        action = getattr(obj.animation_data, "action", None)
        return {"observed_action": getattr(action, "name", None), "action_identity_observed": True}
    except (ReferenceError, AttributeError):
        return {"observed_action": None, "action_identity_observed": False}


class Keyframe:
    def __init__(self, bpy: Any, context: Any, params: Mapping[str, Any], obj: Any, path: str, index: int, frame: float, group: str, method: str):
        self.bpy, self.context, self.params, self.obj, self.path, self.index, self.frame, self.group = bpy, context, params, obj, path, index, frame, group
        self.guard = scope.Guard(bpy, context, method)
        self.guard.remember(obj, bpy.data.objects)
        self.affected = scope.affected_scope(bpy, obj, params.get("affected_objects", []))
        self.object_state = scope.rna_state(obj)
        self.timeline = Timeline(bpy, context, method)
        self.binding, self.animation = scope.binding(obj), scope.animation_context(obj)
        self.action = None if obj.animation_data is None else obj.animation_data.action
        self.content, self.users = None, None
        self.slot_handle = getattr(getattr(obj.animation_data, "action_slot", None), "handle", None)
        self.actions = {scope.action_token(action) for action in scope.bounded(bpy.data.actions, 65536, "Action inventory")}
        if self.action is not None:
            scope.editable_action(self.action)
            require_owned_action(obj, operation="Keyframe editing")
            self.guard.remember(self.action, bpy.data.actions)
            self.content, self.users = scope.action_content(self.action), scope.action_users(bpy, self.action)
            if hasattr(self.action, "is_action_legacy") and not self.action.is_action_legacy and not self.action.is_action_layered:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Empty unclassified native Actions need explicit layered allocation before keyframe editing.")
        self.channels = self.channel_scope()
        self.control_value = scope.value(obj.path_resolve(path))
        self.protected = None if self.action is None else self.protected_action(self.action)
        self.selected_meta = {} if self.action is None else {scope.key(curve): (scope.rna_state(curve, exclude=frozenset({"group"})), scope.curve_content(curve)[2])
            for handle, curve in scope.curve_inventory(self.action)
            if handle == self.slot_handle and curve.data_path == self.path and (self.index == -1 or curve.array_index == self.index)}
        self.groups = {} if self.action is None else self.group_content(self.action)
        self.group_curves: dict[str, set[Any]] = {}
        self.group_removal = set()
        if self.action is not None:
            for _handle, curve in scope.curve_inventory(self.action):
                group_name = getattr(getattr(curve, "group", None), "name", None)
                if group_name is not None:
                    self.group_curves.setdefault(group_name, set()).add(scope.key(curve))
            for group_name in self.group_curves:
                if all(handle == self.slot_handle and curve.data_path == self.path and (self.index == -1 or curve.array_index == self.index) and all(abs(float(point.co[0])-self.frame) <= 1e-6 for point in curve.keyframe_points)
                       for handle, curve in scope.curve_inventory(self.action) if getattr(getattr(curve, "group", None), "name", None) == group_name):
                    self.group_removal.add(group_name)
        self.options = {option.strip().upper() for option in params.get("options", ())}
        if "INSERTKEY_CYCLE_AWARE" in self.options and self.action is not None and any(modifier.type == "CYCLES" for _, curve in scope.curve_inventory(self.action) for modifier in curve.modifiers):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cycle-aware keys with cyclic modifiers need an explicit mapped-frame contract.")
        self.method = method
        if method == "animation.keyframe_insert" and obj.animation_data is not None and (len(obj.animation_data.nla_tracks)
                or getattr(obj.animation_data, "action_blend_type", "REPLACE") != "REPLACE"
                or getattr(obj.animation_data, "action_influence", 1.) != 1.):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Key insertion with NLA/influence conversion needs an independently verified keying contract.")
        existing = [] if self.action is None else [(handle, curve) for handle, curve in scope.curve_inventory(self.action)
            if handle == self.slot_handle and curve.data_path == self.path and (self.index == -1 or curve.array_index == self.index)]
        if len({curve.array_index for _, curve in existing}) != len(existing):
            raise invalid_argument("Keyframe request addresses duplicate layered channels.")
        self.eligible_indices = {record[2] for record in self.channels}
        if "INSERTKEY_AVAILABLE" in self.options:
            self.eligible_indices &= {curve.array_index for _, curve in existing}
        if "INSERTKEY_REPLACE" in self.options:
            self.eligible_indices &= {curve.array_index for _, curve in existing if any(abs(float(point.co[0])-frame) <= 1e-6 for point in curve.keyframe_points)}

    def channel_scope(self) -> tuple[Any, ...]:
        if self.index != -1:
            return (scope.validate_channel(self.obj, self.path, self.index),)
        value = self.obj.path_resolve(self.path)
        count = len(value) if not isinstance(value, (int, float)) else 1
        if not 1 <= count <= 4:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Whole-channel keyframe edits support one numeric control or up to four transform components.")
        return tuple(scope.validate_channel(self.obj, self.path, index) for index in range(count))

    def check(self) -> None:
        self.guard.gate()
        self.timeline.check()
        if self.bpy.context.scene.objects.get(self.params["object_name"]) != self.obj or scope.affected_scope(self.bpy, self.obj, self.params.get("affected_objects", [])) != self.affected:
            raise invalid_argument("Keyframe exact target or dependent-object scope changed.")
        if scope.rna_state(self.obj) != self.object_state or self.channel_scope() != self.channels or scope.value(self.obj.path_resolve(self.path)) != self.control_value:
            raise invalid_argument("Keyframe source object, bone or numeric value changed.")
        if scope.binding(self.obj) != self.binding or scope.animation_context(self.obj) != self.animation:
            raise invalid_argument("Keyframe Action/slot binding or NLA context changed.")
        if self.action is not None and (scope.action_content(self.action) != self.content or scope.action_users(self.bpy, self.action) != self.users):
            raise invalid_argument("Keyframe Action content or consumers changed before native mutation.")

    def protected_action(self, action: Any) -> tuple[Any, ...]:
        content = scope.action_content(action)
        curves = []
        owned_groups = set()
        other_groups = set()
        for (handle, curve), (_, curve_state) in zip(scope.curve_inventory(action), content[3], strict=True):
            selected = handle == self.slot_handle and curve.data_path == self.path and (self.index == -1 or curve.array_index == self.index)
            group_name = getattr(getattr(curve, "group", None), "name", None)
            (owned_groups if selected else other_groups).add(group_name)
            if not selected:
                curves.append((handle, curve_state))
                continue
            # Existing unrelated key coordinates and interpolation remain fixed;
            # automatic native neighbor-handle recalculation is allowed.
            points = []
            for point in curve.keyframe_points:
                if abs(float(point.co[0])-self.frame) > 1e-6:
                    points.append(tuple((name, value) for name, value in scope.rna_state(point) if name not in {"handle_left", "handle_right"}))
            curves.append((handle, curve.data_path, int(curve.array_index), tuple(points), tuple(scope.rna_state(modifier) for modifier in curve.modifiers)))
        # Selected channels may be created/deleted; omit empty selected records.
        curves = tuple(record for record in curves if len(record) != 5 or record[3])
        removable_groups = (owned_groups - other_groups) | ({self.group} if self.group and self.group not in other_groups else set())

        def groups(values):
            return tuple(record for record in values if dict(record).get("name") not in removable_groups)

        layers = tuple((layer, tuple((strip, tuple((handle, groups(items)) for handle, items in bags)) for strip, bags in strips)) for layer, strips in content[2])
        metadata = tuple((name, value) for name, value in content[0] if name not in {"frame_start", "frame_end", "frame_range"} or getattr(action, "use_frame_range", False))
        return metadata, content[1], layers, curves, content[4], groups(content[5])

    @staticmethod
    def group_content(action: Any) -> dict[Any, Any]:
        result = {}
        if not getattr(action, "is_action_layered", False):
            return {("LEGACY", group.name): scope.rna_state(group) for group in scope.bounded(getattr(action, "groups", ()), 256, "groups")}
        for layer_index, layer in enumerate(action.layers):
            for strip_index, strip in enumerate(layer.strips):
                for bag in strip.channelbags:
                    for group in bag.groups:
                        result[(layer_index, strip_index, bag.slot_handle, group.name)] = scope.rna_state(group)
        return result

    def after(self, native_result: bool = True) -> dict[str, Any]:
        # Adopt only the exact native binding/allocation just observed. This does
        # not authorize another write and is never a basis for blind rollback.
        action = None if self.obj.animation_data is None else self.obj.animation_data.action
        native_receipt = (scope.binding(self.obj), scope.animation_context(self.obj),
                          None if action is None else scope.action_content(action),
                          None if action is None else scope.action_users(self.bpy, action))
        self.guard.gate()
        self.timeline.check()
        action = None if self.obj.animation_data is None else self.obj.animation_data.action
        if native_receipt != (scope.binding(self.obj), scope.animation_context(self.obj),
                              None if action is None else scope.action_content(action),
                              None if action is None else scope.action_users(self.bpy, action)):
            raise invalid_argument("Observed native keyframe result changed during the live completion gate; no late edit or compensation is permitted.")
        if self.action is not None:
            if scope.action_token(action) != scope.action_token(self.action) or scope.action_users(self.bpy, action) != self.users or scope.binding(self.obj) != self.binding or self.protected_action(action) != self.protected:
                raise invalid_argument("Native keyframe mutation changed protected Action content, references or binding.")
            for _, curve in scope.curve_inventory(action):
                if scope.key(curve) in self.selected_meta and (scope.rna_state(curve, exclude=frozenset({"group"})), scope.curve_content(curve)[2]) != self.selected_meta[scope.key(curve)]:
                    raise invalid_argument("Native keyframe mutation changed existing curve settings or modifiers.")
            groups = self.group_content(action)
            for identity, state in self.groups.items():
                if identity in groups and groups[identity] != state:
                    raise invalid_argument("Native keyframe mutation changed protected group metadata.")
                if identity not in groups:
                    remaining = {scope.key(curve) for _, curve in scope.curve_inventory(action)}
                    if self.method != "animation.keyframe_delete" or identity[-1] not in self.group_removal or remaining & self.group_curves.get(identity[-1], set()):
                        raise invalid_argument("Native keyframe mutation removed a protected existing Action group.")
        elif action is not None:
            users = scope.action_users(self.bpy, action)
            if scope.action_token(action) in self.actions or users["users"] != 1 or users["fake_user"] or len(users["references"]) != 1 or users["references"][0][0] != scope.key(self.obj):
                raise invalid_argument("Native keyframe allocation reused or acquired a protected Action.")
            scope.editable_action(action)
            scope.action_content(action)
            if getattr(action, "is_action_layered", False):
                slot = getattr(self.obj.animation_data, "action_slot", None)
                if slot is None or slot.target_id_type != "OBJECT" or len(action.slots) != 1 or len(action.layers) != 1 or len(action.layers[0].strips) != 1:
                    raise invalid_argument("New native Action did not retain the reviewed single OBJECT-slot/layer schema.")
                strip = action.layers[0].strips[0]
                if strip.type != "KEYFRAME" or len(strip.channelbags) != 1 or strip.channelbags[0].slot_handle != slot.handle:
                    raise invalid_argument("New native Action acquired unrelated strips or channelbags.")
            if any(curve.data_path != self.path or (self.index != -1 and curve.array_index != self.index) or any(abs(float(point.co[0])-self.frame) > 1e-6 for point in curve.keyframe_points) for _, curve in scope.curve_inventory(action)):
                raise invalid_argument("New native Action contains channels outside the request.")
            actual_groups = self.group_content(action)
            used_groups = {getattr(getattr(curve, "group", None), "name", None) for _, curve in scope.curve_inventory(action)} - {None}
            if len(actual_groups) > 1 or any(identity[-1] not in used_groups or (self.group and identity[-1] != self.group) for identity in actual_groups):
                raise invalid_argument("New native Action acquired unrelated group metadata.")
            if self.animation is None and (len(self.obj.animation_data.nla_tracks) or len(self.obj.animation_data.drivers)):
                raise invalid_argument("New animation container acquired unrelated tracks or drivers.")
        current_actions = {scope.action_token(value) for value in scope.bounded(self.bpy.data.actions, 65536, "Action inventory")}
        expected_actions = self.actions | ({scope.action_token(action)} if self.action is None and action is not None else set())
        if current_actions != expected_actions:
            raise invalid_argument("Native keyframe mutation created/removed unrelated Action IDs.")
        if self.bpy.context.scene.objects.get(self.params["object_name"]) != self.obj or scope.affected_scope(self.bpy, self.obj, self.params.get("affected_objects", [])) != self.affected:
            raise invalid_argument("Keyframe target scope changed after native mutation.")
        if scope.rna_state(self.obj) != self.object_state or self.channel_scope() != self.channels or scope.value(self.obj.path_resolve(self.path)) != self.control_value:
            raise invalid_argument("Native keyframe mutation changed source values or owner metadata.")
        if self.animation is not None and scope.animation_context(self.obj) != self.animation:
            raise invalid_argument("Native keyframe mutation changed protected NLA context.")
        if not native_result and (scope.binding(self.obj) != self.binding or scope.animation_context(self.obj) != self.animation or (None if action is None else scope.action_content(action)) != self.content):
            raise RuntimeError("Native keyframe operation returned false after changing animation data")
        slot_handle = getattr(getattr(self.obj.animation_data, "action_slot", None), "handle", None)
        requested = []
        indices = {record[2] for record in self.channels}
        for handle, curve in (() if action is None else scope.curve_inventory(action)):
            if handle != slot_handle or curve.data_path != self.path or curve.array_index not in indices:
                continue
            points = [point for point in curve.keyframe_points if abs(float(point.co[0])-self.frame) <= 1e-6]
            if len(points) > 1:
                raise invalid_argument("Native keyframe mutation produced ambiguous duplicate frame keys.")
            if points:
                requested.append({"index": curve.array_index, "frame": float(points[0].co[0]), "value": float(points[0].co[1])})
        complete = len(requested) == len(indices) and {item["index"] for item in requested} == indices
        if native_result and self.method == "animation.keyframe_insert":
            present = {item["index"] for item in requested}
            if not self.eligible_indices <= present and "INSERTKEY_NEEDED" not in self.options:
                raise RuntimeError("Native keyframe success did not create every eligible requested frame/component")
            if not requested:
                raise RuntimeError("Native keyframe success produced no requested frame key")
            if "INSERTKEY_VISUAL" not in self.options:
                for item in requested:
                    value = self.control_value[item["index"]] if isinstance(self.control_value, tuple) else self.control_value
                    if abs(item["value"]-value) > max(1e-5, abs(value)*1e-6):
                        raise RuntimeError("Native keyframe value did not match the independently inspected source value")
        if native_result and self.method == "animation.keyframe_delete" and requested:
            raise RuntimeError("Native keyframe success did not remove every requested frame/component")
        return {"action": getattr(action, "name", None), "action_identity_known": action is not None,
                "requested_keyframes": requested, "requested_keyframes_complete": complete,
                "conditional_component_omissions": sorted(indices-{item["index"] for item in requested}),
                "requested_key_values_verified": self.method == "animation.keyframe_insert" and native_result and "INSERTKEY_VISUAL" not in self.options,
                "protected_channels_preserved": True, "affected_objects": [self.obj.name, *self.params.get("affected_objects", [])]}
