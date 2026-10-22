"""Explicit local Action allocation, binding, metadata retention and unused removal."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import suppress
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, reject_unknown_params, require_blender
from . import _animation_scope as scope
from .shader_scope import name

LOGGER = logging.getLogger(__name__)


def _name(raw: Any, label: str, maximum: int = 63) -> str:
    exact = name(raw, label)
    if len(exact.encode("utf-8")) > maximum:
        raise invalid_argument(f"{label} exceeds {maximum} UTF-8 bytes.")
    return exact


def _action(bpy: Any, raw: Any) -> Any:
    exact = _name(raw, "action_name")
    if len(bpy.data.actions) > 65536:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action lookup exceeds 65536 datablocks.")
    matches = list(islice((action for action in bpy.data.actions if action.name == exact), 2))
    if len(matches) != 1:
        raise invalid_argument("Action must resolve exactly without local/library name ambiguity.", action_name=exact)
    return matches[0]


def _object(bpy: Any, raw: Any) -> Any:
    exact = name(raw, "object_name")
    if len(bpy.context.scene.objects) > 65536:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Animation object lookup exceeds 65536 objects.")
    matches = list(islice((obj for obj in bpy.context.scene.objects if obj.name == exact), 2))
    if len(matches) != 1:
        raise invalid_argument("Animation object must resolve exactly in the current scene.")
    scope.object_scope(bpy, matches[0])
    return matches[0]


def _summary(bpy: Any, action: Any) -> dict[str, Any]:
    content, users = scope.action_content(action), scope.action_users(bpy, action)
    curves = scope.curve_inventory(action)
    return {"action": action.name, "content_sha256": scope.digest(content), "users": users["users"], "real_users": users["real_users"],
            "keep_on_save": users["fake_user"], "retention": "REFERENCED" if users["real_users"] else "FAKE_USER" if users["fake_user"] else "SESSION_ONLY",
            "direct_users": [{"object": record[2], "type": record[3], "references": record[4], "local_editable": record[5]} for record in users["references"]],
            "slots": [{"identifier": slot.identifier, "handle": int(slot.handle), "target_id_type": slot.target_id_type} for slot in getattr(action, "slots", ())],
            "curve_count": len(curves), "keyframe_count": sum(len(curve.keyframe_points) for _, curve in curves),
            "content_complete_within_limits": True, "project_saved": False}


def action_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"action_name"})
    bpy = require_blender()
    action = _action(bpy, params.get("action_name"))
    token = scope.action_token(action)
    if context.check_cancelled:
        context.check_cancelled()
    context.require(Permission.INSPECT_SCENE)
    if scope.action_token(_action(bpy, params.get("action_name"))) != token:
        raise invalid_argument("Action identity changed during inspection.")
    return _summary(bpy, action)


def _failed(error: Exception, message: str, *, started: bool, restored: bool = False, **evidence: Any) -> BridgeError:
    return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED, message,
                       {**(error.context if isinstance(error, BridgeError) else {}),
                        "execution_started": started, "rollback_verified": restored, "possible_mutation": started and not restored,
                        "verification_required": True, **evidence})


def action_create(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"action_name", "slot_name", "keep_on_save"})
    exact, slot_name = _name(params.get("action_name"), "action_name"), _name(params.get("slot_name"), "slot_name", 61)
    if "keep_on_save" not in params:
        raise invalid_argument("keep_on_save must be chosen explicitly; retention does not save a project.")
    keep = bool_param(params, "keep_on_save", False)
    bpy, created, allocated = require_blender(), None, False
    guard = scope.Guard(bpy, context, "animation.action_create")
    guard.gate()
    if bpy.data.actions.get(exact) is not None:
        raise invalid_argument("action_name must be unused.")
    expected = None

    def fresh() -> None:
        guard.gate()
        assert created is not None
        scope.editable_action(created)
        users = scope.action_users(bpy, created)
        if created.name != exact or scope.action_content(created) != expected or users["real_users"] or created.use_fake_user:
            raise invalid_argument("New Action allocation changed or acquired a consumer; further setup refused.")

    try:
        allocated = True
        created = bpy.data.actions.new(exact)
        guard.remember(created, bpy.data.actions)
        if created.name != exact or not hasattr(created, "slots") or not hasattr(created, "layers"):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action creation requires the reviewed layered Action API and an exact retained name.")
        expected = scope.action_content(created)
        fresh()
        slot = created.slots.new("OBJECT", slot_name)
        slot_identifier = slot.identifier
        expected = scope.action_content(created)
        fresh()
        layer = created.layers.new("Layer")
        expected = scope.action_content(created)
        fresh()
        strip = layer.strips.new(type="KEYFRAME")
        expected = scope.action_content(created)
        fresh()
        strip.channelbag(slot, ensure=True)
        expected = scope.action_content(created)
        fresh()
        if keep:
            created.use_fake_user = True
        guard.gate()
        if created.name != exact or scope.action_content(created) != expected or scope.action_users(bpy, created)["real_users"] or created.use_fake_user != keep:
            raise RuntimeError("New Action content/retention readback mismatch")
        return {"created": True, "bound": False, "slot_identifier": slot_identifier, **_summary(bpy, created)}
    except Exception as error:
        LOGGER.exception("Action allocation/setup failed; retaining exact known allocations")
        retained = None
        with suppress(ReferenceError):
            retained = created.name if created is not None else None
        raise _failed(error, "Action creation failed; inspect any retained allocation before explicit cleanup.", started=allocated,
                      retained_action=retained, allocation_identity_known=created is not None) from error


def _external_action_refs(bpy: Any, action: Any, obj: Any) -> Any:
    users = scope.action_users(bpy, action)
    records = []
    for record in users["references"]:
        values = list(record)
        if record[0] == scope.key(obj) and obj.animation_data is not None and obj.animation_data.action == action:
            values[4] -= 1
        if values[4]:
            records.append(tuple(values))
    return action.name, users["fake_user"], tuple(records)


class _Binding:
    def __init__(self, bpy: Any, context: ToolContext, params: Mapping[str, Any], obj: Any, action: Any, slot: Any):
        self.bpy, self.context, self.params, self.obj = bpy, context, params, obj
        self.guard = scope.Guard(bpy, context, "animation.action_bind")
        self.guard.remember(obj, bpy.data.objects)
        self.object_key, self.data_key = scope.key(obj), scope.key(obj.data)
        self.affected = scope.affected_scope(bpy, obj, params.get("affected_objects"))
        self.expected_context, self.expected_binding = scope.animation_context(obj), scope.binding(obj)
        self.actions = list({scope.key(value): value for value in (action, None if obj.animation_data is None else obj.animation_data.action) if value is not None}.values())
        self.frozen = {}
        for value in self.actions:
            scope.editable_action(value)
            self.guard.remember(value, bpy.data.actions)
            self.frozen[scope.key(value)] = (scope.action_content(value), _external_action_refs(bpy, value, obj))
        self.channels = None if action is None else scope.validate_slot(obj, action, slot)

    def check(self) -> None:
        self.guard.gate()
        if scope.key(_object(self.bpy, self.params["object_name"])) != self.object_key or scope.key(self.obj.data) != self.data_key:
            raise invalid_argument("Animation binding object/data identity changed.")
        if scope.affected_scope(self.bpy, self.obj, self.params["affected_objects"]) != self.affected:
            raise invalid_argument("Animation binding affected-object closure changed.")
        if scope.animation_context(self.obj) != self.expected_context or scope.binding(self.obj) != self.expected_binding:
            raise invalid_argument("Animation/NLA context or binding changed outside this operation.")
        for action in self.actions:
            scope.editable_action(action)
            if (scope.action_content(action), _external_action_refs(self.bpy, action, self.obj)) != self.frozen[scope.key(action)]:
                raise invalid_argument("Action content, retention or protected references changed during binding.")


def action_bind(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "action_name", "slot_identifier", "expected_action_name", "affected_objects", "allow_session_only_previous"})
    if "action_name" not in params or "expected_action_name" not in params:
        raise invalid_argument("Choose action_name (or null to clear) and expected_action_name explicitly.")
    bpy = require_blender()
    obj = _object(bpy, params.get("object_name"))
    data = obj.animation_data
    previous = None if data is None else data.action
    old_slot = None if data is None else getattr(data, "action_slot", None)
    expected_name = None if params["expected_action_name"] is None else _name(params["expected_action_name"], "expected_action_name")
    if getattr(previous, "name", None) != expected_name:
        raise invalid_argument("Current active Action does not match expected_action_name.")
    action = None if params["action_name"] is None else _action(bpy, params["action_name"])
    slot = None if action is None else scope.slot_for(action, params.get("slot_identifier"))
    if action is None and params.get("slot_identifier") is not None:
        raise invalid_argument("Clearing an Action cannot include a slot identifier.")
    allow_session = bool_param(params, "allow_session_only_previous", False)
    session_only = previous is not None and previous != action and not previous.use_fake_user and scope.action_users(bpy, previous)["real_users"] == 1
    if session_only and not allow_session:
        raise invalid_argument("Previous Action would become session-only; retain it explicitly first or acknowledge allow_session_only_previous=true.")
    boundary = _Binding(bpy, context, params, obj, action, slot)
    original_context, original_binding = boundary.expected_context, boundary.expected_binding
    created_data, started = False, False

    def assign(field: str, value: Any) -> None:
        nonlocal started
        boundary.check()
        started = True
        data = obj.animation_data
        try:
            setattr(data, field, value)
        finally:
            # A native Action assignment may select a suitable cached slot. Adopt
            # only the exact requested Action and a slot owned by that Action.
            observed_action, observed_slot = data.action, getattr(data, "action_slot", None)
            matching_action = field == "action" and observed_action == value and (observed_slot is None or any(scope.key(item) == scope.key(observed_slot) for item in getattr(observed_action, "slots", ())))
            matching_slot = field == "action_slot" and scope.slot_identity(observed_slot) == scope.slot_identity(value)
            if matching_action or matching_slot:
                boundary.expected_binding = scope.binding(obj)
        if (field == "action" and data.action != value) or (field == "action_slot" and scope.slot_identity(data.action_slot) != scope.slot_identity(value)):
            raise RuntimeError("Blender did not retain the requested Action/slot binding")

    try:
        boundary.check()
        if data is None and action is not None:
            started = created_data = True
            obj.animation_data_create()
            boundary.expected_context, boundary.expected_binding = scope.animation_context(obj), scope.binding(obj)
        if obj.animation_data is not None:
            assign("action", action)
            if slot is not None:
                assign("action_slot", slot)
        boundary.check()
        if action is not None and scope.validate_slot(obj, action, slot) != boundary.channels:
            raise invalid_argument("Action channel owners changed after assignment.")
        return {"object": obj.name, "affected_objects": [obj.name, *params["affected_objects"]], "previous_action": expected_name,
                "action": getattr(action, "name", None), "slot_identifier": getattr(slot, "identifier", None), "previous_session_only": session_only,
                "source_channels_preserved": True, "evaluation_verified": False, "verification_required": True, "project_saved": False}
    except Exception as error:
        LOGGER.exception("Action binding failed")
        restored = False
        try:
            if obj.animation_data is not None:
                assign("action", previous)
                if old_slot is not None:
                    assign("action_slot", old_slot)
            if created_data:
                boundary.check()
                obj.animation_data_clear()
                boundary.expected_context, boundary.expected_binding = None, None
            boundary.check()
            restored = scope.binding(obj) == original_binding and scope.animation_context(obj) == original_context
        except Exception:
            LOGGER.exception("Action binding compensation refused or failed")
        raise _failed(error, "Action binding failed; inspect the exact current Action, slot and retained data.", started=started, restored=restored,
                      object_name=params["object_name"], previous_action=expected_name) from error


def action_update(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"action_name", "new_name", "keep_on_save", "allow_shared"})
    if params.get("new_name") is None and "keep_on_save" not in params:
        raise invalid_argument("Provide new_name or keep_on_save.")
    bpy = require_blender()
    action = _action(bpy, params.get("action_name"))
    scope.editable_action(action)
    content, users = scope.action_content(action), scope.action_users(bpy, action)
    allow_shared = bool_param(params, "allow_shared", False)
    if users["real_users"] > 1 and not allow_shared:
        raise invalid_argument("Shared Action metadata requires allow_shared=true after inspecting every reference.")
    if any(record[3] != "Object" or not record[5] for record in users["references"]):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Action metadata requires local editable object users.")
    original = {"name": action.name, "use_fake_user": bool(action.use_fake_user)}
    expected, attempted = dict(original), []
    desired = {}
    if params.get("new_name") is not None:
        desired["name"] = _name(params["new_name"], "new_name")
    if "keep_on_save" in params:
        desired["use_fake_user"] = bool_param(params, "keep_on_save", False)
    guard = scope.Guard(bpy, context, "animation.action_update")
    guard.remember(action, bpy.data.actions)

    def check(field: str | None = None, value: Any = None) -> None:
        deleting_retention = field == "use_fake_user" and action.use_fake_user and value is False
        guard.gate(*((Permission.DELETE_OBJECTS,) if deleting_retention else ()))
        scope.editable_action(action)
        current_users = scope.action_users(bpy, action)
        if action.name != expected["name"] or action.use_fake_user != expected["use_fake_user"] or scope.action_content(action) != content or current_users["references"] != users["references"]:
            raise invalid_argument("Action content, metadata or direct references changed; stale writes/recovery refused.")
        if field == "name":
            candidate = bpy.data.actions.get(value)
            if candidate is not None and candidate != action:
                raise invalid_argument("Requested Action name is occupied.")

    try:
        for field, value in desired.items():
            check(field, value)
            if getattr(action, field) == value:
                continue
            attempted.append(field)
            try:
                setattr(action, field, value)
            finally:
                if getattr(action, field) == value:
                    expected[field] = value
            if getattr(action, field) != value:
                raise RuntimeError("Native Action metadata readback mismatch")
        check()
        return {"previous_name": original["name"], "changed": bool(attempted), **_summary(bpy, action)}
    except Exception as error:
        LOGGER.exception("Action metadata update failed")
        restored = False
        try:
            for field in reversed(attempted):
                check(field, original[field])
                setattr(action, field, original[field])
                if getattr(action, field) != original[field]:
                    raise RuntimeError("Action metadata compensation readback mismatch")
                expected[field] = original[field]
            check()
            restored = expected == original
        except Exception:
            LOGGER.exception("Action metadata compensation refused or failed")
        raise _failed(error, "Action metadata update failed; inspect current retention/name before continuing.", started=bool(attempted), restored=restored) from error


def action_remove(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"action_name", "confirm"})
    if not bool_param(params, "confirm", False):
        raise invalid_argument("Action removal requires confirm=true.")
    bpy = require_blender()
    action = _action(bpy, params.get("action_name"))
    exact, content, users = action.name, scope.action_content(action), scope.action_users(bpy, action)
    scope.editable_action(action)
    if users["users"] or users["references"]:
        raise invalid_argument("Action removal requires no references and keep_on_save=false; nothing is unlinked or unpinned implicitly.")
    guard = scope.Guard(bpy, context, "animation.action_remove")
    guard.remember(action, bpy.data.actions)
    guard.gate(Permission.DELETE_OBJECTS)
    scope.editable_action(action)
    if action.name != exact or scope.action_content(action) != content or scope.action_users(bpy, action) != users:
        raise invalid_argument("Action content or reference ownership changed before removal.")
    removed = False
    try:
        bpy.data.actions.remove(action, do_unlink=False)
        removed = True
        guard.ids.clear()
        guard.gate(Permission.DELETE_OBJECTS)
        return {"removed": True, "removed_action": exact, "replacement_present": bpy.data.actions.get(exact) is not None,
                "automatic_recreation_attempted": False, "verification_required": True, "project_saved": False}
    except Exception as error:
        raise _failed(error, "Action removal could not be verified; inspect before retrying.", started=True,
                      removal_returned_successfully=removed, removed_action=exact) from error


TOOL_DATA = (
    ("animation.action_inspect", action_inspect, False, (Permission.INSPECT_SCENE,), "Inspect one exact Action's bounded content, slots, direct references and save retention."),
    ("animation.action_create", action_create, True, (Permission.EDIT_ANIMATION,), "Create an unbound OBJECT-slot Action with explicit fake-user retention; never saves."),
    ("animation.action_bind", action_bind, True, (Permission.EDIT_ANIMATION,), "Assign/clear an exact object Action/slot with expected old binding and explicit affected-object scope."),
    ("animation.action_update", action_update, True, (Permission.EDIT_ANIMATION,), "Rename/set fake-user retention on one Action; clearing retention additionally needs DELETE_OBJECTS."),
    ("animation.action_remove", action_remove, True, (Permission.EDIT_ANIMATION, Permission.DELETE_OBJECTS), "Confirm removal of one unused unretained Action ID without unlinking or automatic recreation."),
)


def register_tools(registry: ToolRegistry) -> None:
    for tool_name, handler, modifies, permissions, description in TOOL_DATA:
        registry.register(tool_name, handler, toolset="animation", modifies=modifies, permissions=permissions, description=description)
