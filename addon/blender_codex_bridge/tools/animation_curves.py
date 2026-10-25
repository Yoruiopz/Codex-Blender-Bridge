"""Explicit Action versions and bounded existing F-curve authoring."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry, _checkpoint_parameters, check_final_mutation
from ..utils import get_object, int_param, reject_unknown_params, require_blender
from . import _animation_scope as scope
from . import animation_lifecycle
from ._object_safety import require_local_object, require_owned_action
from ._rna import bounded_name

LOGGER = logging.getLogger(__name__)


class _Boundary:
    """Live authority and exact CAS around each native authoring write."""

    def __init__(self, bpy: Any, context: ToolContext, params: Mapping[str, Any], obj: Any, action: Any, method: str, curve: Any = None):
        self.bpy, self.context, self.params, self.obj, self.action, self.curve = bpy, context, params, obj, action, curve
        self.guard = scope.Guard(bpy, context, method)
        self.guard.remember(obj, bpy.data.objects)
        self.guard.remember(action, bpy.data.actions)
        scope.editable_action(action)
        self.scope = scope.affected_scope(bpy, obj, params.get("affected_objects", []))
        self.binding, self.animation = scope.binding(obj), scope.animation_context(obj)
        self.data_key = scope.key(getattr(obj, "data", None))
        self.users = scope.action_users(bpy, action)
        self.expected = scope.action_content(action)
        self.protected = self._protected(self.expected)

    def _protected(self, content: tuple[Any, ...]) -> tuple[Any, ...]:
        if self.curve is None:
            return content
        inventory = scope.curve_inventory(self.action)
        selected = [ordinal for ordinal, (_, curve) in enumerate(inventory) if scope.key(curve) == scope.key(self.curve)]
        if len(selected) != 1:
            raise invalid_argument("Exact F-curve identity changed.")
        curves = list(content[3])
        curves[selected[0]] = (curves[selected[0]][0], "OWNED_CURVE")
        return (*content[:3], tuple(curves), *content[4:])

    def check(self) -> None:
        self.guard.gate()
        obj, _data, action = _active(self.params, edit=self.curve is not None)
        if scope.key(obj) != scope.key(self.obj) or scope.key(action) != scope.key(self.action) or scope.key(getattr(obj, "data", None)) != self.data_key:
            raise invalid_argument("Exact animation object, data or Action changed.")
        if scope.binding(obj) != self.binding or scope.animation_context(obj) != self.animation:
            raise invalid_argument("Action/slot binding or NLA context changed outside this operation.")
        if scope.affected_scope(self.bpy, obj, self.params.get("affected_objects", [])) != self.scope:
            raise invalid_argument("Animation affected-object scope changed.")
        if scope.action_users(self.bpy, action) != self.users or scope.action_content(action) != self.expected:
            raise invalid_argument("Animation content or consumers changed; stale writes and compensation refused.")

_MAX_POINTS = 1024
_POINT_FIELDS = (
    "interpolation", "easing", "handle_left_type", "handle_right_type", "co", "handle_left", "handle_right",
)
_ENUMS = {
    "interpolation": {"CONSTANT", "LINEAR", "BEZIER"},
    "easing": {"AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"},
    "handle_left_type": {"FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"},
    "handle_right_type": {"FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"},
}


def _active(params: Mapping[str, Any], *, edit: bool) -> tuple[Any, Any, Any]:
    obj = get_object(params.get("object_name"), allow_active=False)
    require_local_object(obj, operation="Action authoring")
    data = obj.animation_data
    if data is None or data.action is None:
        raise invalid_argument("The named object must have an active Action.")
    if getattr(data, "use_tweak_mode", False):
        raise invalid_argument("Exit NLA tweak mode before Action authoring.")
    if edit:
        require_owned_action(obj, operation="F-curve authoring")
    return obj, data, data.action


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_argument(f"{name} must be a finite bounded number.")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise invalid_argument(f"{name} must be a finite bounded number.") from exc
    if not math.isfinite(result) or abs(result) > 1_000_000:
        raise invalid_argument(f"{name} must be finite and within +/-1,000,000.")
    return result


def _point_state(point: Any) -> dict[str, Any]:
    return {
        "frame": float(point.co[0]), "value": float(point.co[1]),
        "interpolation": str(point.interpolation), "easing": str(point.easing),
        "handle_left_type": str(point.handle_left_type), "handle_right_type": str(point.handle_right_type),
        "handle_left": [float(v) for v in point.handle_left],
        "handle_right": [float(v) for v in point.handle_right],
    }


def _bounded_items(items: Any, limit: int, label: str) -> list[Any]:
    values = list(islice(items, limit + 1))
    if len(values) > limit:
        raise invalid_argument(f"Action exceeds the {limit}-{label} authoring budget.")
    return values


def _curve_inventory(action: Any) -> list[tuple[int | None, Any]]:
    if not getattr(action, "is_action_layered", False):
        return [(None, curve) for curve in _bounded_items(action.fcurves, 1024, "curve")]
    _bounded_items(getattr(action, "slots", ()), 64, "slot")
    found = []
    for layer in _bounded_items(action.layers, 16, "layer"):
        for strip in _bounded_items(layer.strips, 32, "strip"):
            bags = getattr(strip, "channelbags", None)
            if bags is None:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This layered Action strip has no reviewed channelbag API.")
            for bag in _bounded_items(bags, 64, "channelbag"):
                for curve in _bounded_items(bag.fcurves, 1024, "curve"):
                    found.append((bag.slot_handle, curve))
                    if len(found) > 1024:
                        raise invalid_argument("Action exceeds the 1024-curve authoring budget.")
    return found


def _slot_curves(data: Any, action: Any, requested_slot: Any) -> tuple[list[Any], str | None]:
    if not getattr(action, "is_action_layered", False):
        if requested_slot is not None:
            raise invalid_argument("Legacy Actions do not have slots.")
        return [curve for _, curve in _curve_inventory(action)], None
    slot = getattr(data, "action_slot", None)
    if slot is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Layered Action authoring requires an assigned active slot.")
    identifier = str(slot.identifier)
    if requested_slot is not None and requested_slot != identifier:
        raise invalid_argument("slot_identifier must identify this object's active Action slot.", active_slot=identifier)
    return [curve for handle, curve in _curve_inventory(action) if handle == slot.handle], identifier


def action_copy(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Create and bind one explicitly named independent active Action version."""
    reject_unknown_params(params, {"object_name", "new_name", "affected_objects"})
    obj, data, source = _active(params, edit=False)
    name = bounded_name(params.get("new_name"), "new_name", maximum=63)
    if len(name.encode("utf-8")) > 63:
        raise invalid_argument("new_name must fit 63 UTF-8 bytes.")
    bpy = require_blender()
    if bpy.data.actions.get(name) is not None:
        raise invalid_argument("An Action with new_name already exists.", action=name)
    old_slot = getattr(data, "action_slot", None)
    old_identifier = getattr(old_slot, "identifier", None)
    if getattr(source, "is_action_layered", False) and old_slot is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Assign an active slot before copying a layered Action.")
    points = 0
    for _, curve in _curve_inventory(source):
        if len(curve.keyframe_points) > 1024 or len(getattr(curve, "sampled_points", ())):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action copies support unsampled curves with at most 1024 keyframes each.")
        points += len(curve.keyframe_points)
        if points > 16384 or len(getattr(curve, "modifiers", ())) > 32:
            raise invalid_argument("Action copy exceeds the 16384-keyframe or 32-modifier-per-curve budget.")
    boundary = _Boundary(bpy, context, params, obj, source, "animation.action_copy")
    object_name, source_name = obj.name, source.name
    boundary.check()
    created = None
    created_state = None

    def fresh_copy() -> None:
        boundary.check()
        assert created is not None
        scope.editable_action(created)
        if bpy.data.actions.get(created.name) != created or scope.action_content(created) != boundary.expected or scope.action_users(bpy, created)["real_users"]:
            raise invalid_argument("New Action copy changed or acquired a consumer; no further setup/binding is permitted.")
        if (created.name, bool(created.use_fake_user)) != created_state:
            raise invalid_argument("New Action copy metadata changed outside this operation.")

    try:
        created = source.copy()
        boundary.guard.remember(created, bpy.data.actions)
        created_state = (created.name, bool(created.use_fake_user))
        fresh_copy()
        created.name = name
        created_state = (name, bool(created.use_fake_user))
        fresh_copy()
        created.use_fake_user = False
        created_state = (name, False)
        fresh_copy()
        if created.name != name:
            raise RuntimeError("Blender could not preserve the explicit Action name.")
        target_slot = None
        if old_identifier is not None:
            choices = [slot for slot in created.slots if slot.identifier == old_identifier]
            if len(choices) != 1:
                raise RuntimeError("Copied Action did not preserve its active slot identity.")
            target_slot = choices[0]
        animation_lifecycle.action_bind(context, {"object_name": obj.name, "action_name": name,
            "expected_action_name": source.name, "slot_identifier": getattr(target_slot, "identifier", None),
            "affected_objects": params.get("affected_objects", []), "allow_session_only_previous": True})
        if data.action != created or (target_slot is not None and data.action_slot != target_slot):
            raise RuntimeError("Independent Action binding did not verify.")
    except Exception as exc:
        LOGGER.exception("Action copy or guarded binding failed; allocations remain for explicit inspection")
        # Binding has its own live/CAS compensation. Never replay a stale binding
        # here or remove an allocation after cancellation/ownership changes.
        restored, retained_name = False, None
        with suppress(ReferenceError, AttributeError):
            restored = scope.binding(obj) == boundary.binding
        with suppress(ReferenceError, AttributeError):
            retained_name = getattr(created, "name", None)
        raise BridgeError(
            exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Action version creation failed; inspect retained data before retrying.",
            {**(exc.context if isinstance(exc, BridgeError) else {}), "object": object_name, "source_action": source_name,
             "retained_action": retained_name, "rollback_verified": restored,
             "possible_mutation": created is not None or not restored},
        ) from exc
    return {
        "object": obj.name, "affected_objects": [obj.name, *params.get("affected_objects", [])], "source_action": source.name,
        "action": created.name, "slot_identifier": old_identifier, "independent_version": True,
        "source_retained_in_session": True, "source_users_after": int(source.users),
        "source_fake_user": bool(source.use_fake_user),
        "source_save_retention": "REFERENCED" if source.users-int(source.use_fake_user) else "FAKE_USER" if source.use_fake_user else "SESSION_ONLY",
    }


def _prepare_curve_edit(params: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve/validate the request without providers or native writes."""
    reject_unknown_params(params, {"object_name", "data_path", "index", "keyframes", "extrapolation", "slot_identifier", "affected_objects"})
    obj, data, action = _active(params, edit=True)
    path = bounded_name(params.get("data_path"), "data_path", maximum=512)
    index = int_param(params, "index", 0, minimum=0, maximum=16384)
    curves, slot = _slot_curves(data, action, params.get("slot_identifier"))
    if getattr(action, "is_action_layered", False) and getattr(data.action_slot, "target_id_type", None) != "OBJECT":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve authoring requires an assigned native OBJECT slot.")
    matches = [curve for curve in curves if curve.data_path == path and curve.array_index == index]
    if len(matches) != 1:
        raise invalid_argument("Choose exactly one existing F-curve by data_path, index and active slot.", matches=len(matches))
    curve = matches[0]
    points = list(islice(curve.keyframe_points, _MAX_POINTS + 1))
    if len(points) > _MAX_POINTS or len(getattr(curve, "sampled_points", ())):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Authoring supports at most 1024 existing unsampled keyframes.")
    edits = params.get("keyframes", [])
    if not isinstance(edits, list) or len(edits) > 256:
        raise invalid_argument("keyframes must contain at most 256 existing-frame edits.")
    extrapolation = params.get("extrapolation")
    if extrapolation is not None and (not isinstance(extrapolation, str) or extrapolation not in {"CONSTANT", "LINEAR"}):
        raise invalid_argument("extrapolation must be CONSTANT or LINEAR.")
    if not edits and extrapolation is None:
        raise invalid_argument("At least one keyframe edit or extrapolation is required.")
    prepared = []
    seen = set()
    for edit in edits:
        if not isinstance(edit, Mapping):
            raise invalid_argument("Each keyframe edit must be an object.")
        reject_unknown_params(edit, {"frame", *_POINT_FIELDS})
        frame = _number(edit.get("frame"), "frame")
        candidates = [point for point in points if abs(float(point.co[0]) - frame) <= 1e-6]
        if len(candidates) != 1 or id(candidates[0]) in seen:
            raise invalid_argument("Each edit must identify one distinct existing frame.", frame=frame)
        point = candidates[0]
        seen.add(id(point))
        values = {}
        for field in _POINT_FIELDS:
            if field not in edit:
                continue
            value = edit[field]
            if field in _ENUMS:
                if not isinstance(value, str) or value not in _ENUMS[field]:
                    raise invalid_argument(f"Unsupported {field}.", supported=sorted(_ENUMS[field]))
            else:
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise invalid_argument(f"{field} requires [frame, value].")
                value = tuple(_number(item, field) for item in value)
                kind = "FREE" if field == "co" else edit.get(f"{field}_type", getattr(point, f"{field}_type"))
                if kind != "FREE":
                    raise invalid_argument("Explicit handle coordinates require the corresponding FREE handle type.")
            values[field] = value
        if not values:
            raise invalid_argument("Each frame requires an interpolation/easing/handle change.")
        prepared.append((float(point.co[0]), values))
    inventory = _curve_inventory(action)
    ordinal = [i for i, (_handle, item) in enumerate(inventory) if scope.key(item) == scope.key(curve)]
    if len(ordinal) != 1:
        raise invalid_argument("The selected native curve is not unique in its Action.")
    return {"object": obj, "action": action, "curve": curve, "slot": slot, "path": path,
            "index": index, "ordinal": ordinal[0], "prepared": tuple(prepared), "extrapolation": extrapolation}


def _curve_id(owner: Any) -> tuple[int, int] | None:
    if owner is None:
        return None
    pointer, uid = owner.as_pointer(), owner.session_uid
    if any(type(value) is not int or not 1 <= value <= 2**64 - 1 for value in (pointer, uid)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve authoring requires native ID pointers and session UIDs.")
    return pointer, uid


def _curve_pointer(owner: Any) -> int:
    pointer = owner.as_pointer()
    if type(pointer) is not int or not 1 <= pointer <= 2**64 - 1:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve authoring requires an exact native curve pointer.")
    return pointer


def _curve_native_screen(bpy: Any, params: Mapping[str, Any]) -> None:
    """Descriptor-first qualification before inherited authored-data getters."""
    from . import _scene_mutation as native

    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The initial retained-intent curve profile requires Object Mode.")
    classes = set()
    def screen(owner):
        if owner is not None and type(owner) not in classes:
            native.descriptors(bpy, owner)
            classes.add(type(owner))
    def items(values, limit, label):
        result = _bounded_items(values, limit, label)
        for owner in result:
            screen(owner)
        return result
    def curves(values):
        for curve in values:
            screen(curve)
            items(curve.keyframe_points, 1024, "keyframe")
            for modifier in items(getattr(curve, "modifiers", ()), 32, "modifier"):
                items(getattr(modifier, "control_points", ()), 256, "modifier-control")
    actions = {}
    target = get_object(params.get("object_name"), allow_active=False)
    objects = [target]
    for name in params.get("affected_objects", []):
        matches = [owner for owner in bpy.context.scene.objects if owner.name == name]
        if len(matches) != 1:
            raise invalid_argument("Affected Object is missing or ambiguous.")
        objects.append(matches[0])
    for obj in objects:
        screen(obj)
        data = obj.animation_data
        screen(data)
        if obj == target and (data is None or data.action is None):
            raise invalid_argument("The named object requires an active Action.")
        if data is not None:
            if data.action is not None:
                actions[_curve_id(data.action)] = data.action
            items(data.drivers, 0, "owner-driver")
            for track in items(data.nla_tracks, 64, "NLA-track"):
                for strip in items(track.strips, 64, "NLA-strip"):
                    if strip.action is not None:
                        actions[_curve_id(strip.action)] = strip.action
                    curves(items(strip.fcurves, 32, "NLA-curve"))
                    for modifier in items(strip.modifiers, 32, "NLA-modifier"):
                        items(getattr(modifier, "control_points", ()), 256, "NLA-modifier-control")
        items(getattr(obj, "modifiers", ()), 100, "Object-modifier")
        items(getattr(obj, "constraints", ()), 100, "Object-constraint")
        items(getattr(obj, "vertex_groups", ()), 256, "vertex-group")
        items(getattr(obj, "material_slots", ()), 128, "material-slot")
        pose = getattr(obj, "pose", None)
        screen(pose)
        if pose is not None:
            for bone in items(pose.bones, 256, "pose-bone"):
                items(bone.constraints, 100, "bone-constraint")
        geometry = obj.data
        screen(geometry)
        if geometry is not None:
            if obj.type == "MESH":
                for field in ("vertices", "edges", "loops", "polygons"):
                    items(getattr(geometry, field), 131072, field)
                for attribute in items(geometry.attributes, 128, "Mesh-attribute"):
                    items(attribute.data, 262144, "attribute-value")
                keys = geometry.shape_keys
                screen(keys)
                if keys is not None:
                    for block in items(keys.key_blocks, 64, "shape-key"):
                        items(block.data, 262144, "shape-key-point")
            elif obj.type == "ARMATURE":
                items(geometry.bones, 256, "rest-bone")
                items(getattr(geometry, "collections_all", ()), 256, "bone-collection")
    if len(actions) > 16:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve preservation exceeds sixteen bound Actions.")
    for action in actions.values():
        screen(action)
        curves([curve for _slot, curve in _curve_inventory(action)])
        fields = ("slots", "pose_markers") + (() if getattr(action, "is_action_layered", False) else ("groups",))
        for field in fields:
            for owner in items(getattr(action, field, ()), 256, field):
                if field == "groups":
                    screen(getattr(owner, "colors", None))
        for layer in items(getattr(action, "layers", ()), 16, "layer"):
            for strip in items(layer.strips, 32, "strip"):
                for bag in items(strip.channelbags, 64, "channelbag"):
                    for group in items(bag.groups, 256, "group"):
                        screen(getattr(group, "colors", None))
    native.runtime(bpy)  # No evaluated/frame/dependency-graph handler assumptions.


def _curve_write_schema(bpy: Any, owner: Any, field: str, value: Any) -> None:
    """Admit only literal writable native enum/Float32-pair setters."""
    from . import _scene_mutation as native

    properties = native.descriptors(bpy, owner)
    matches = [prop for prop in properties if prop.identifier == field]
    if len(matches) != 1:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve field lacks its exact native descriptor.")
    prop = matches[0]
    coordinates = field in {"co", "handle_left", "handle_right"}
    if (prop.is_readonly or prop.is_runtime or getattr(prop, "is_registered", False)
            or prop.type != ("FLOAT" if coordinates else "ENUM")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve setter has an unsupported native descriptor.")
    if coordinates:
        try:
            length = prop.array_length
        except AttributeError as error:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve Float2 setter lacks numeric array metadata.") from error
        if type(length) is not int or length != 2:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve coordinates require an exact native Float2 descriptor.")
        if any(not prop.hard_min <= item <= prop.hard_max for item in value):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve setter would clamp its independently predicted coordinates.")
    else:
        # Source-defined EnumProperty is NON_ARRAY: it has no numeric array API.
        # Never default a missing length to zero or ask this descriptor for one.
        identifiers = tuple(item.identifier for item in scope.bounded(prop.enum_items, 256, "curve-enum"))
        if (type(value) is not str or any(type(item) is not str for item in identifiers)
                or value not in identifiers):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve setter lacks the requested native enum value.")


def _curve_roles(bpy: Any, obj: Any) -> Any:
    from ._artist_role_witness import capture
    from ._scene_checkpoint_roles import Plan

    plan = Plan(bpy, bpy.context.scene, include_brush=True, previous_owner_factory=capture)
    active = bpy.context.view_layer.objects.active
    if active is None or active == obj:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "Initial curve authoring requires a separate frozen unanimated active Object.")
    witness = capture(bpy, active, plan)
    return plan, witness


def _curve_context(bpy: Any) -> tuple:
    context, scene = bpy.context, bpy.context.scene
    layer = context.view_layer
    objects = _bounded_items(layer.objects, 256, "view-layer-object")
    return (_curve_id(scene), _curve_pointer(layer), bpy.data.filepath, context.mode,
            int(scene.frame_current), float(scene.frame_subframe), _curve_id(layer.objects.active),
            tuple((_curve_id(obj), bool(obj.select_get(view_layer=layer))) for obj in objects))


def _curve_object_state(obj: Any, *, target: bool) -> Any:
    from ._artist_scope_profile import IGNORED_OBJECT_RUNTIME
    from ._object_rna_mutation import object_state

    result = object_state(obj, exclude_object_rna=IGNORED_OBJECT_RUNTIME)
    if not target:
        return result
    # Only this bound active Action content is owned. Preserve the complete
    # AnimData/NLA/other-Action records instead of dropping all animation.
    return tuple((name, (*value[:3], "OWNED_ACTIVE_ACTION", *value[4:]))
                 if name == "animation" and value is not None else (name, value) for name, value in result)


def _curve_structure(action: Any) -> Any:
    """Retain native descendant identity and writable metadata omitted by content."""
    rows = []
    def record(label, owner):
        rows.append((label, _curve_pointer(owner), scope.rna_state(owner)))
    fields = ("slots", "pose_markers") + (() if getattr(action, "is_action_layered", False) else ("groups",))
    for field in fields:
        for owner in _bounded_items(getattr(action, field, ()), 256, field):
            record(field, owner)
    for layer in _bounded_items(getattr(action, "layers", ()), 16, "layer"):
        record("layer", layer)
        for strip in _bounded_items(layer.strips, 32, "strip"):
            record("strip", strip)
            for bag in _bounded_items(strip.channelbags, 64, "channelbag"):
                record("channelbag", bag)
                for group in _bounded_items(bag.groups, 256, "group"):
                    record("channelgroup", group)
    curves = tuple((handle, _curve_pointer(curve), curve.data_path, curve.array_index,
                    tuple(_curve_pointer(point) for point in _bounded_items(curve.keyframe_points, 1024, "keyframe")),
                    tuple(_curve_pointer(modifier) for modifier in _bounded_items(getattr(curve, "modifiers", ()), 32, "modifier")))
                   for handle, curve in _curve_inventory(action))
    return bool(getattr(action, "use_extra_user", False)), tuple(rows), curves


def _make_curve_reader(context: ToolContext, params: dict):
    from ._curve_point_native import Reader
    return Reader(context, params)


def _point_request(params: Mapping[str, Any]) -> None:
    """Reject unknown shapes before native acquisition or provider calls."""
    if type(params) is not dict:
        raise invalid_argument("Curve point requests require an exact plain parameter object.")
    if any(type(key) is not str for key in params):
        raise invalid_argument("Curve point parameter names must be literal strings.")
    reject_unknown_params(params, {"object_name", "data_path", "index", "keyframes", "extrapolation", "slot_identifier", "affected_objects"})
    for name, maximum in (("object_name", 63), ("data_path", 512)):
        value = params.get(name)
        try:
            valid = (type(value) is str and bool(value) and len(value.encode("utf8")) <= maximum
                     and not any(ord(c) < 32 for c in value))
        except UnicodeError:
            valid = False
        if not valid:
            raise invalid_argument("Point names/paths require bounded literal strings.", parameter=name)
    if params["data_path"] not in {"location", "rotation_euler", "scale"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The first point profile addresses explicit XYZ Object channels.")
    index = params.get("index", 0)
    if type(index) is not int or not 0 <= index < 3:
        raise invalid_argument("Point array index must be an integer from zero through two.")
    slot = params.get("slot_identifier")
    if slot is not None:
        try:
            valid_slot = (type(slot) is str and bool(slot) and len(slot.encode("utf8")) <= 63
                          and not any(ord(c) < 32 for c in slot))
        except UnicodeError:
            valid_slot = False
        if not valid_slot:
            raise invalid_argument("slot_identifier must be a bounded literal string.")
    if type(params.get("affected_objects", [])) is not list or params.get("affected_objects", []):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The first point profile refuses external affected consumers.")
    edits = params.get("keyframes", [])
    if type(edits) is not list or len(edits) > 256 or any(type(edit) is not dict for edit in edits):
        raise invalid_argument("Point keyframes require at most 256 plain edit objects.")
    for edit in edits:
        if any(type(key) is not str for key in edit):
            raise invalid_argument("Point edit field names must be literal strings.")
        reject_unknown_params(edit, {"frame", *_POINT_FIELDS})
        if type(edit.get("frame")) not in (int, float):
            raise invalid_argument("Point frames require a literal finite number.")
        _number(edit["frame"], "frame")
        for field in _ENUMS:
            if field in edit:
                value = edit[field]
                if type(value) is not str or value not in _ENUMS[field]:
                    raise invalid_argument(f"Unsupported {field}.")
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                                  "Interpolation/easing/handle-type transitions need a separate curve profile.")
        for field in ("co", "handle_left", "handle_right"):
            if field in edit:
                value = edit[field]
                if type(value) is not list or len(value) != 2:
                    raise invalid_argument("Point fields require an exact two-number array.", property=field)
                for component in value:
                    if type(component) not in (int, float):
                        raise invalid_argument("Point coordinates require literal finite numbers.")
                    _number(component, field)
    if params.get("extrapolation") is not None:
        value = params["extrapolation"]
        if type(value) is not str or value not in {"CONSTANT", "LINEAR"}:
            raise invalid_argument("extrapolation must be CONSTANT or LINEAR.")
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "Extrapolation/full-update transitions need a separate curve profile.")
    if not edits and params.get("extrapolation") is None:
        raise invalid_argument("Supply at least one point field.")


class _CurveWriter:
    """Retained FREE-channel intent; observed native content is never authority."""

    METHOD = "animation.curve_edit"

    def __init__(self, context: ToolContext, params: Mapping[str, Any]):
        from . import _curve_edit_intent as kernel

        _point_request(params)
        self.kernel, self.context, self.original_params = kernel, context, params
        self.parameter_facts = _checkpoint_parameters(params)
        self.params = deepcopy(dict(params))
        self.registry, self.spec = context.registry, context.registry.get(self.METHOD)
        if (self.spec.handler is not curve_edit or not self.spec.modifies or self.spec.toolset != "animation"
                or self.spec.permissions != frozenset({Permission.EDIT_ANIMATION}) or not self.spec.automatic_checkpoint
                or self.spec.checkpoint_admission_factory is not _curve_edit_admission or self.spec.batchable
                or not self.spec.exclusive_mutation):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve editing requires its exact modifying registered contract.",
                              {"execution_started": False})
        self.services = tuple((name, getattr(context, name, None)) for name in (
            "state", "request_lifecycle", "check_final_request", "check_final_job", "checkpoints", "permissions"))
        self._services, self._context, self._params_origin = self.services, context, params
        self._registry, self._spec = self.registry, self.spec
        self.registry.check_mutation_owner(self.spec, context)
        entries = self.registry._mutation_interlock._entries
        self._invocation = entries[-1] if entries else None
        if (self._invocation is None or self._invocation.params is not params
                or self._invocation.context is not context or self._invocation.spec is not self.spec):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve intent requires its original structured invocation.")
        self.binding = None
        self.stopped: BridgeError | None = None
        self.refused: str | None = None
        self.stage, self.cursor = "PREPARED", 0
        self.attempts = self.verified = self.restore_attempts = self.restored = 0
        self.update_attempts = self.update_verified = 0
        self.known = False
        self.observed: str | None = None
        self.complete = self.rollback = False
        self.in_gate = self.used = False
        self.reader_factory = _make_curve_reader
        self.reader = self.reader_factory(context, self.params)
        self._reader = self.reader
        self.bpy = self.reader.bpy
        selected = self.reader.prepare()
        self.name, self.action_name = selected["object"].name, selected["action"].name
        self.ids = (_curve_id(selected["object"]), _curve_id(selected["action"]),
                    _curve_id(selected["object"].data), _curve_pointer(selected["curve"]))
        self.path, self.index, self.slot, self.ordinal = (selected[key] for key in ("path", "index", "slot", "ordinal"))
        self.frames = tuple(frame for frame, _values in selected["prepared"])
        self._evidence_origin = (self.name, self.action_name, self.path, self.index, self.ids,
                                 tuple(self.params.get("affected_objects", [])))
        before = self.reader.action_content(selected["action"])
        self.plan = kernel.plan_edit(before, self.ordinal, selected["prepared"], selected["extrapolation"])
        self._plan = self.plan
        self.roles, self.active_witness = self.reader.roles()
        for step in self.plan.steps:
            owner = self._target(selected["curve"], step.field, step.frame)
            try:
                _curve_write_schema(self.bpy, owner, step.field, step.value)
            finally:
                owner = None
        self.expected = self.plan.before
        self._expected = self.expected
        self.preservation = self._preservation(selected["object"], selected["action"])
        self._preservation_origin = self.preservation
        self._roles, self._active_witness = self.roles, self.active_witness
        self._origin = _checkpoint_parameters((self.name, self.action_name, self.ids, self.path, self.index,
                                              self.slot, self.ordinal, self.frames))
        self.before_digest, self.expected_digest = kernel.digest(self.plan.before), kernel.digest(self.plan.expected)
        self.check_after_read()

    def _stop(self, error: Exception, reason: str = "STATE_CHANGED") -> BridgeError:
        if self.stopped is None:
            self.stopped = error if isinstance(error, BridgeError) else BridgeError(
                ErrorCode.OPERATION_FAILED, "Curve scope could not be revalidated.")
            self.refused = reason
            if reason == "AUTHORITY_LOST":
                self.known, self.observed = False, None
            if hasattr(self, "before_digest"):
                self.complete, self.stage = False, "FAILED"
                facts = self.evidence()
                name, action, _path, _index, _ids, affected = self._evidence_origin
                self.stopped.context.update(object=name, action=action, affected_objects=[name, *affected],
                                            recovery_evidence=facts, verification_required=True,
                                            rollback_verified=self.rollback,
                                            execution_started=self.stopped.context.get("execution_started") is True or facts["execution_started"],
                                            possible_mutation=self.stopped.context.get("possible_mutation") is True or facts["possible_mutation"])
        return self.stopped

    def _identity(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        if (self.context is not self._context or self.original_params is not self._params_origin
                or self.registry is not self._registry or self.spec is not self._spec or self.services is not self._services
                or self.roles is not self._roles or self.active_witness is not self._active_witness
                or self.reader is not self._reader or _make_curve_reader is not self.reader_factory
                or self.expected is not self._expected or self.preservation is not self._preservation_origin
                or self.context.registry is not self.registry or self.registry.get(self.METHOD) is not self.spec
                or any(getattr(self.context, name, None) is not value for name, value in self.services)
                or _checkpoint_parameters(self.original_params) != self.parameter_facts
                or _checkpoint_parameters(self.params) != self.parameter_facts or self.plan is not self._plan
                or _checkpoint_parameters((self.name, self.action_name, self.ids, self.path, self.index,
                                            self.slot, self.ordinal, self.frames)) != self._origin):
            raise self._stop(invalid_argument("Original curve caller, registered tool or request intent changed."), "AUTHORITY_LOST")
        if self.binding is not None and (self.context.checkpoint_admission is not self.binding
                                         or self.binding.callback is not self):
            raise self._stop(invalid_argument("Original curve admission binding changed."), "AUTHORITY_LOST")
        self.reader.check_origin()
        self.registry.check_mutation_owner(self.spec, self.context)
        if not any(entry is self._invocation for entry in self.registry._mutation_interlock._entries):
            raise self._stop(invalid_argument("Original curve invocation was retired."), "AUTHORITY_LOST")
        if (type(self.cursor) is not int or not 0 <= self.cursor <= len(self.plan.steps)
                or self.expected is not (self.plan.before if self.cursor == 0 else self.plan.steps[self.cursor - 1].expected)):
            raise self._stop(invalid_argument("Curve prefix position does not match its retained intent."), "AUTHORITY_LOST")

    def final(self) -> None:
        try:
            self._identity()
            check_final_mutation(self.context, self.METHOD, expected_spec=self.spec)
            self._identity()
        except Exception as error:
            self.known, self.observed = False, None
            refused = self._stop(error, "AUTHORITY_LOST")
            if refused is error:
                raise
            raise refused from error

    def __call__(self) -> None:
        if self.in_gate:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Curve admission cannot recursively authorize another writer.")
        self.in_gate = True
        try:
            self._identity()
            if self.context.check_cancelled is not None:
                self.context.check_cancelled()
            self._identity()
            self.context.require(Permission.EDIT_ANIMATION)
            self._identity()
            self.check_after_read()
        except Exception as error:
            refused = self._stop(error, "AUTHORITY_LOST")
            if self.refused == "AUTHORITY_LOST":
                self.known, self.observed = False, None
            if refused is error:
                raise
            raise refused from error
        finally:
            self.in_gate = False

    def enter_handler(self) -> None:
        if (self.used or self.in_gate or self._invocation is None
                or self._invocation.continuation_id not in self.registry._mutation_interlock._consumed):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Curve writer has no fresh canonical handler continuation.",
                              {"reason": "REENTRANT_MUTATION_BLOCKED", "execution_started": False})
        self._identity()
        self.used = True

    def bind_checkpoint(self, binding: Any) -> None:
        if (self.binding is not None or binding.context is not self.context or binding.callback is not self
                or binding.params is not self.original_params):
            raise invalid_argument("Curve checkpoint binding does not belong to its retained factory.")
        self.binding = binding

    def native_push_delegates(self) -> tuple:
        return (self.roles,)

    def after_native_push(self) -> None:
        from ..checkpoint_completion import claim_native_push_completion

        claim_native_push_completion(self.context, self.METHOD, self)
        self.roles.after_native_push()

    def _resolve(self) -> tuple[Any, Any, Any]:
        obj, action, curve = self.reader.resolve()
        if ((_curve_id(obj), _curve_id(action), _curve_id(obj.data), _curve_pointer(curve)) != self.ids
                or (obj.name, action.name) != (self.name, self.action_name)):
            raise invalid_argument("Original point Object/Action/curve identity changed.")
        return obj, action, curve

    def _preservation(self, _obj: Any, _action: Any) -> Any:
        self.active_witness.check(self.roles)
        return self.reader.preservation(self.roles)

    def _read(self) -> tuple[Any, Any]:
        self.known, self.observed = False, None
        try:
            self.final()
            obj, action, curve = self._resolve()
            if not self.kernel.same(self._preservation(obj, action), self.preservation):
                raise invalid_argument("Curve consumers, binding, context or protected authored data changed.")
            content = self.reader.action_content(action)
            self.final()
            return curve, content
        except Exception as error:
            refused = self._stop(error)
            if refused is error:
                raise
            raise refused from error

    def check_after_read(self) -> None:
        try:
            _curve, content = self._read()
            self.observed, self.known = self.kernel.digest(content), True
            if not self.kernel.same(content, self.expected):
                raise invalid_argument("Action content differs from the independently predicted curve prefix.")
            self.final()
        except Exception as error:
            refused = self._stop(error)
            if refused is error:
                raise
            raise refused from error

    def _target(self, curve: Any, field: str, frame: float | None):
        if frame is None:
            return curve
        points = [point for point in curve.keyframe_points if float(point.co[0]) == frame]
        if len(points) != 1:
            raise invalid_argument("Original existing keyframe is missing or ambiguous.")
        return points[0]

    def _measure(self, before: Any, expected: Any) -> bool:
        try:
            _curve, content = self._read()
            self.observed, self.known = self.kernel.digest(content), True
            if self.kernel.same(content, expected):
                self.expected = self._expected = expected
                return True
            if self.kernel.same(content, before):
                self.expected = self._expected = before
                return False
            raise invalid_argument("Native curve write produced unpredicted authored content; no replay is safe.")
        except Exception as error:
            refused = self._stop(error)
            if refused is error:
                raise
            raise refused from error

    def _write(self, field: str, frame: float | None, value: Any, before: Any, expected: Any, *, restore: bool = False) -> None:
        if not self.kernel.same(self.expected, before):
            raise self._stop(invalid_argument("Curve write does not follow its retained independent prefix."))
        self()
        curve, _content = self._read()
        # Prebuild the literal Float2 before the final complete source CAS.
        value = tuple(value)
        self.check_after_read()
        try:
            leaf = self.reader.leaf(curve, field, frame, value, expected=self.expected,
                                    preservation=self.preservation, roles=self.roles)
        except Exception as error:
            refused = self._stop(error, "INVALID_NATIVE_SCOPE")
            if refused is error:
                raise
            raise refused from error
        curve = _content = None
        failed = None
        try:
            self.final()  # Provider-free canonical gate only; no broad native read.
            if restore:
                self.restore_attempts += 1
            else:
                self.attempts += 1
            leaf()
        except BaseException as error:
            if not isinstance(error, Exception):
                self.known, self.observed = False, None
                raise self._stop(BridgeError(ErrorCode.OPERATION_FAILED,
                    "Point assignment was interrupted; native effects require reinspection."), "NATIVE_INTERRUPTED") from error
            failed = error
        finally:
            leaf.clear()  # No point/vector/method wrapper crosses into providers/readback.
            leaf = None
        try:
            verified = self._measure(before, expected)
        except Exception as secondary:
            if failed is not None:
                raise failed from secondary
            raise
        if verified:
            if restore:
                self.restored += 1
                self.cursor -= 1
            else:
                self.verified += 1
                self.cursor += 1
        if failed is not None:
            raise failed
        if not verified:
            raise RuntimeError("Native curve setter did not produce its retained requested value.")

    def _original_value(self, step: Any) -> Any:
        curve = step.before[3][self.ordinal][1]
        if step.frame is None:
            return dict(curve[0])[step.field]
        return next(dict(point)[step.field] for point in curve[1] if dict(point)["co"][0] == step.frame)

    def execute(self) -> None:
        try:
            self()
            for step in self.plan.steps:
                self.stage = "FIELD_WRITE"
                self._write(step.field, step.frame, step.value, step.before, step.expected)
            self.check_after_read()
            self.complete, self.stage = True, "COMPLETE"
        except Exception as primary:
            if self.stopped is None and self.known:
                try:
                    self.stage = "RESTORE"
                    while self.cursor:
                        step = self.plan.steps[self.cursor - 1]
                        self._write(step.field, step.frame, self._original_value(step), step.expected, step.before, restore=True)
                    self.check_after_read()
                    self.rollback = self.kernel.same(self.expected, self.plan.before)
                except Exception:
                    LOGGER.exception("Curve restoration refused or incomplete; retained prefix requires inspection")
            self.stage = "FAILED"
            raise self.failure(primary) from primary

    def failure(self, primary: Exception) -> BridgeError:
        self.complete, self.stage = False, "FAILED"
        facts = self.evidence()
        name, action, _path, _index, _ids, affected = self._evidence_origin
        return BridgeError(primary.code if isinstance(primary, BridgeError) else ErrorCode.OPERATION_FAILED,
                           "F-curve edit failed; inspect retained authored state before a new request.",
                           {**(primary.context if isinstance(primary, BridgeError) else {}),
                            "object": name, "action": action, "affected_objects": [name, *affected],
                            "execution_started": (isinstance(primary, BridgeError) and primary.context.get("execution_started") is True) or facts["execution_started"],
                            "possible_mutation": (isinstance(primary, BridgeError) and primary.context.get("possible_mutation") is True) or facts["possible_mutation"],
                            "rollback_verified": self.rollback, "verification_required": True, "recovery_evidence": facts})

    def evidence(self) -> dict:
        name, action, path, index, ids, _affected = self._evidence_origin
        assert ids[0] is not None and ids[1] is not None
        touched = bool(self.attempts or self.update_attempts)
        return {"kind": "curve_mutation", "method": self.METHOD, "object_name": name,
                "action_name": action, "data_path": path, "array_index": index,
                "object_pointer": ids[0][0], "object_session_uid": ids[0][1],
                "action_pointer": ids[1][0], "action_session_uid": ids[1][1], "curve_pointer": ids[3],
                "stage": self.stage, "execution_started": touched, "possible_mutation": touched and not self.rollback,
                "rollback_verified": self.rollback, "verification_required": not self.complete,
                "state_known": self.known, "retained_partial": touched and not self.complete and not self.rollback,
                "owned_field_attempts": self.attempts, "owned_field_verified": self.verified,
                "restoration_attempts": self.restore_attempts, "restored_fields": self.restored,
                "native_update_attempts": self.update_attempts, "native_update_verified": self.update_verified,
                "before_sha256": self.before_digest, "expected_sha256": self.expected_digest,
                "observed_sha256": self.observed if self.known else None, "restoration_refused": self.refused}


def _curve_edit_admission(context: ToolContext, params: Mapping[str, Any]) -> _CurveWriter:
    return _CurveWriter(context, params)


def _curve_result(writer: _CurveWriter) -> dict[str, Any]:
    """Format only independently predicted, fully compared primitive records."""
    content = writer.expected[3][writer.ordinal][1]
    return {"object": writer.name, "action": writer.action_name,
            "affected_objects": [writer.name, *writer.params.get("affected_objects", [])],
            "data_path": writer.path, "index": writer.index, "slot_identifier": writer.slot,
            "extrapolation": dict(content[0])["extrapolation"], "edited_frames": list(writer.frames),
            "keyframes": [{"frame": dict(point)["co"][0], "value": dict(point)["co"][1],
                           **{field: list(dict(point)[field]) if field in {"co", "handle_left", "handle_right"} else dict(point)[field]
                              for field in _POINT_FIELDS}} for point in content[1]], "truncated": False,
            "authored_profile": "RAW_FREE_POINT_V1", "context_sync_possible": True,
            "current_pose_revision_qualified": False, "persistent_non_ID_identity_qualified": False,
            "complete_hidden_state_qualified": False, "recovery_evidence": writer.evidence()}


def curve_edit(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Write only independently predicted existing FREE-handle channel intent."""
    binding = getattr(context, "checkpoint_admission", None)
    if binding is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Curve editing requires its original pre-provider admission.",
                          {"execution_started": False})
    binding.check_identity(_CurveWriter.METHOD)
    writer = binding.callback
    if type(writer) is not _CurveWriter or writer.binding is not binding or writer.original_params is not params:
        raise invalid_argument("Curve editing requires its original pre-provider intent guard.")
    writer.enter_handler()
    writer.execute()
    try:
        result = _curve_result(writer)
        writer.final()
    except Exception as primary:
        raise writer.failure(primary) from primary
    return result


def register_tools(registry: ToolRegistry) -> None:
    common: dict[str, Any] = {"permissions": (Permission.EDIT_ANIMATION,), "toolset": "animation", "modifies": True}
    registry.register("animation.action_copy", action_copy, description="Copy and bind an independent named active Action; unreferenced source retention is session-only.", **common)
    registry.register("animation.curve_edit", curve_edit, description="Edit bounded raw co/value and FREE handle fields of existing ordinary Object keys; sorting/interpolation profiles remain unqualified.",
                      checkpoint_admission_factory=_curve_edit_admission, batchable=False, exclusive_mutation=True, **common)
