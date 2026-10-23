"""Bounded runtime references, transform previews and opt-in plan protection.

Saved plans contain none of this operational state. Scope follows reviewed
incoming native ID consumers, not arbitrary Python callbacks or visual intent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..artist_step_evidence import associate, check_apply, matches
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..request_lifecycle import RequestLifetime
from ..task_plans import get_task_plans, text
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import reject_unknown_params, require_blender, vector3
from . import _animation_scope as scope
from ._artist_scope_profile import pre_closure, require_profile
from ._object_rna_mutation import Boundary, _closure, _rotation_mode_delta

MAX_SCENE_OBJECTS = 4096
MAX_REFERENCES = 16
MAX_PREVIEWS = 8
MAX_PROFILE_BYTES = 8 * 1024 * 1024
TRANSFORM_METHODS = frozenset({"transform.set", "transform.translate", "transform.rotate", "transform.scale"})
EULER_MODES = frozenset({"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"})


def _objects(bpy: Any, names: list[str]) -> tuple[Any, ...]:
    objects = scope.bounded(bpy.context.scene.objects, MAX_SCENE_OBJECTS, "artist scene objects")
    resolved = []
    for name in names:
        matches = [obj for obj in objects if obj.name == name]
        if len(matches) != 1 or bpy.context.view_layer.objects.get(name) != matches[0]:
            raise invalid_argument("Reference names must resolve uniquely in the current scene and view layer.", object=name)
        resolved.append(matches[0])
    return tuple(resolved)


def _scene_scope(bpy: Any, names: list[str]) -> Any:
    objects = _objects(bpy, names)
    # Match the existing advisory-plan identity representation, but use a
    # bounded scan before resolving it for operational enforcement.
    def identity(owner: Any) -> Any:
        return getattr(owner, "session_uid", None) or scope.key(owner)
    return identity(bpy.context.scene), tuple((obj.name, identity(obj)) for obj in objects)


def policy_stamp(context: Any) -> tuple[str, int]:
    store = get_task_plans(context.state)
    return store.runtime_id, store.protection_generation


def needs_review(context: Any) -> bool:
    store = get_task_plans(context.state)
    return store.protection is not None or store.applying_preview is not None


def final_lifetime_gate(context: Any) -> None:
    """Only trusted lifecycle flags, without invoking arbitrary providers."""
    if getattr(context, "request_lifecycle", None) is not None:
        RequestLifetime.check(context.request_lifecycle)
    for name in ("check_final_request", "check_final_job"):
        callback = getattr(context, name, None)
        if callback is not None:
            callback()


def final_write_gate(context: Any) -> None:
    """Only trusted lifecycle flags after all native/profile/content readers."""
    final_lifetime_gate(context)
    flags = context.state.snapshot()
    if flags["emergency_stopped"] or flags["paused"]:
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags["emergency_stopped"] else ErrorCode.AGENT_PAUSED,
                          "Protected transform stopped before its next owned write.")


def check_affected(context: Any, bpy: Any, objects: tuple[Any, ...], *, stamp: Any = None) -> None:
    """Callback-free terminal check; callers run live providers before this."""
    store = get_task_plans(context.state)
    if stamp is not None and policy_stamp(context) != stamp:
        raise invalid_argument("Task-plan protection changed; further writes and compensation are refused.", scope_complete=False)
    if store.protection is None:
        return
    plan = store.require_plan()
    current = _scene_scope(bpy, plan["protected_objects"])
    if (current != store.scope or current != store.protection["scope"]
            or plan["plan_id"] != store.protection["plan_id"]):
        raise invalid_argument("Protected scene or object identities changed; constraints are retained.", scope_complete=False)
    protected = {identity: name for name, identity in current[1]}
    conflicts = sorted({protected[token] for obj in objects
                        if (token := (getattr(obj, "session_uid", None) or scope.key(obj))) in protected})
    if conflicts:
        raise invalid_argument("The reviewed affected-consumer scope intersects protected objects; no write is allowed.",
                               protected_scope_violation=True, affected_protected_objects=conflicts,
                               scope_complete=True, protected_scope_enforced=True)


def require_reviewed_mutator(context: Any, method: str, *, reviewed: bool) -> None:
    if get_task_plans(context.state).protection is not None and not reviewed:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "This modifying tool has no reviewed protected-scope resolver; enforcement remains active.",
                          {"tool": method, "protected_scope_enforced": True, "scope_complete": False})


def _inspect_gate(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()
    context.require(Permission.INSPECT_SCENE)
    final_lifetime_gate(context)


def enforce_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"enabled", "expected_revision"})
    enabled = params.get("enabled")
    if type(enabled) is not bool:
        raise invalid_argument("'enabled' must explicitly be true or false.")
    store = get_task_plans(context.state)
    store.check_revision(params.get("expected_revision"))
    _inspect_gate(context)
    store.check_revision(params.get("expected_revision"))
    if enabled:
        flags = context.state.snapshot()
        if (context.registry.executing_mutators or store.executing_mutators
                or (flags.get("is_executing") and flags.get("current_method") != "task.plan.enforce")):
            raise invalid_argument("Enforcement cannot be enabled inside another executing request; finish it first.")
        if context.jobs is not None and context.jobs.active is not None:
            raise invalid_argument("Finish or cancel the active job before enabling plan enforcement.")
        plan = store.require_plan()
        if not plan["protected_objects"]:
            raise invalid_argument("Enforcement requires at least one exact protected object.")
        current = _scene_scope(require_blender(), plan["protected_objects"])
        if current != store.scope:
            raise invalid_argument("Protected identities changed; explicitly correct the advisory plan before enforcement.")
        final_lifetime_gate(context)
        store.protection = {"plan_id": plan["plan_id"], "scope": deepcopy(current)}
    else:
        final_lifetime_gate(context)
        store.protection = None
    store.invalidate_handles()
    record = context.state.record_operation(tool="task.plan.enforce",
        description=("Enabled" if enabled else "Explicitly disabled") + " runtime protected task-plan scope",
        success=True, duration_ms=0.)
    return {**store.inspect(context.evidence), "enforcement_changed_explicitly": True,
            "protection_audit_operation_id": record.operation_id,
            "reviewed_transform_methods": sorted(TRANSFORM_METHODS),
            "host_python_sandbox": False}


def _context(bpy: Any) -> Any:
    selected = scope.bounded(getattr(bpy.context, "selected_objects", ()), 32, "artist selected objects")
    return (scope.action_token(bpy.context.scene), scope.key(bpy.context.view_layer), bpy.context.mode,
            getattr(bpy.data, "filepath", ""), tuple(scope.action_token(obj) for obj in selected),
            scope.action_token(bpy.context.view_layer.objects.active),
            getattr(bpy.context.scene, "frame_current", None), getattr(bpy.context.scene, "frame_subframe", None))


def _keep(values: Any, prefix: str, value: dict[str, Any], maximum: int) -> str:
    identifier = prefix + uuid.uuid4().hex
    values[identifier] = value
    while len(values) > maximum:
        values.popitem(last=False)
    return identifier


def resolve_reference(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"source", "object_names"})
    source = params.get("source")
    bpy = require_blender()
    _inspect_gate(context)
    if source == "selection":
        if "object_names" in params:
            raise invalid_argument("Selection references cannot also supply object_names.")
        names = [obj.name for obj in scope.bounded(bpy.context.selected_objects, 32, "artist selected objects")]
    elif source == "objects":
        names = params.get("object_names")
        if not isinstance(names, list) or not 1 <= len(names) <= 32:
            raise invalid_argument("Exact object references require 1-32 object_names.")
        names = [text(name, "object name", 63) for name in names]
    else:
        raise invalid_argument("'source' must be selection or objects; visual and pronoun guesses are unsupported.")
    if not names or len(set(names)) != len(names):
        raise invalid_argument("References require a nonempty unique exact scope.")
    objects = _objects(bpy, names)
    reference = {"source": source, "names": names, "objects": tuple(scope.action_token(obj) for obj in objects),
                 "context": _context(bpy), "policy_stamp": policy_stamp(context)}
    final_lifetime_gate(context)
    identifier = _keep(get_task_plans(context.state).references, "ref_", reference, MAX_REFERENCES)
    return {"reference_id": identifier, "source": source, "objects": [{"name": obj.name, "type": obj.type} for obj in objects],
            "mode": bpy.context.mode, "authority_granted": False, "visual_reference_resolved": False,
            "runtime_only": True, "reference_limit": MAX_REFERENCES}


def _reference(context: ToolContext, bpy: Any, identifier: Any) -> tuple[Any, ...]:
    store = get_task_plans(context.state)
    if not isinstance(identifier, str) or identifier not in store.references:
        raise invalid_argument("Reference is missing or evicted; resolve it again.")
    reference = store.references[identifier]
    objects = _objects(bpy, reference["names"])
    if (reference["context"] != _context(bpy) or reference["policy_stamp"] != policy_stamp(context)
            or reference["objects"] != tuple(scope.action_token(obj) for obj in objects)):
        raise invalid_argument("Reference context or identities changed; resolve it again.")
    return objects


def _profile(boundary: Boundary) -> str:
    digest, size = hashlib.sha256(), 0
    for chunk in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(
            (boundary.session, boundary.references, boundary.protected, boundary.expected)):
        encoded = chunk.encode("utf-8")
        size += len(encoded)
        if size > MAX_PROFILE_BYTES:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Artist preview profile exceeds 8 MiB; no preview is retained.")
        digest.update(encoded)
    return digest.hexdigest()


def check_preview_origin(boundary: Boundary) -> None:
    """Bind an apply's new write boundary to its reviewed authored pre-state.

    A dispatch permission callback can run after apply's initial preview CAS.
    Rebuilding a boundary must never adopt that callback's newer manual state.
    """
    store = get_task_plans(boundary.context.state)
    preview = store.applying_preview
    if preview is None:
        return
    from ._artist_checkpoint_admission import current
    admission = current(boundary.context)
    roles = admission.roles if admission is not None and admission.roles is not None else preview["checkpoint_roles"].fork()
    roles.check_after_read()
    association = preview.get("step_association")
    if association is not None and not matches(store, association):
        raise invalid_argument("The preview's retained plan step changed before its write boundary.")
    if (boundary.method != "transform.set" or boundary.obj.name != preview["params"]["object_name"]
            or policy_stamp(boundary.context) != preview["policy_stamp"] or _profile(boundary) != preview["profile"]):
        raise invalid_argument("The preview's authored pre-state changed before its write boundary; no edit is allowed.")


def _preview_params(params: Mapping[str, Any], obj: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = {"object_name": obj.name}
    for field in ("location", "rotation", "scale"):
        if field in params:
            parsed[field] = list(vector3(params[field], field))
    mode = params.get("rotation_mode")
    if mode is not None:
        if not isinstance(mode, str) or mode.upper() not in EULER_MODES | {"QUATERNION", "AXIS_ANGLE"}:
            raise invalid_argument("Unsupported rotation_mode.")
        parsed["rotation_mode"] = mode.upper()
    if not any(field in parsed for field in ("location", "rotation", "scale")):
        raise invalid_argument("Preview requires location, rotation or scale.")
    if "rotation" in parsed and mode is not None and parsed["rotation_mode"] not in EULER_MODES:
        raise invalid_argument("Three-component rotation values require an Euler rotation mode.")
    if "rotation" in parsed and mode is None and obj.rotation_mode not in EULER_MODES:
        parsed["rotation_mode"] = "XYZ"
    return parsed


def preview_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"reference_id", "expected_revision", "object_name", "location", "rotation", "scale", "rotation_mode", "step_id"})
    store = get_task_plans(context.state)
    store.check_revision(params.get("expected_revision"))
    association = associate(store, params["step_id"]) if "step_id" in params else None
    bpy = require_blender()
    _inspect_gate(context)
    store.check_revision(params.get("expected_revision"))
    objects = _reference(context, bpy, params.get("reference_id"))
    requested = params.get("object_name")
    targets = [obj for obj in objects if requested is None or obj.name == requested]
    if len(targets) != 1:
        raise invalid_argument("Preview requires one exact referenced object; specify object_name for a multi-object reference.")
    obj = targets[0]
    pre_closure(bpy)
    affected, _references = _closure(bpy, obj)
    require_profile(bpy, affected)
    parsed = _preview_params(params, obj)
    boundary = Boundary(bpy, context, "transform.set", obj, transform=True, artist_profile=True)
    require_profile(bpy, boundary.objects)
    check_affected(context, bpy, boundary.objects)
    before = dict(boundary.expected)
    desired = dict(before)
    if "rotation_mode" in parsed:
        desired.update(_rotation_mode_delta(obj, parsed["rotation_mode"]))
        desired["rotation_mode"] = parsed["rotation_mode"]
    for field in ("location", "rotation", "scale"):
        if field in parsed:
            desired["rotation_euler" if field == "rotation" else field] = tuple(parsed[field])
    # Locked components use the same contract as the actual transform handler.
    for field in ("location", "rotation_euler", "scale"):
        locks = getattr(obj, "lock_rotation" if field == "rotation_euler" else f"lock_{field}", ())
        if any(locked and old != new for locked, old, new in zip(locks, before[field], desired[field], strict=False)):
            raise invalid_argument("Preview does not bypass locked transform components.", property=field)
    changes = [{"field": field, "before": before[field], "requested": desired[field]} for field in before if before[field] != desired[field]]
    preview = {"reference_id": params["reference_id"], "params": parsed, "profile": _profile(boundary),
               "policy_stamp": policy_stamp(context), "plan_id": store.require_plan()["plan_id"], "step_association": association,
               "checkpoint_roles": boundary.checkpoint_roles.origin()}
    if association is not None and not matches(store, association):
        raise invalid_argument("The plan step changed during preview; resolve it again.")
    final_lifetime_gate(context)
    identifier = _keep(store.previews, "preview_", preview, MAX_PREVIEWS)
    return {"preview_id": identifier, "step_id": association.step_id if association is not None else None,
            "method": "transform.set", "object": obj.name, "changes": changes,
            "affected_objects": boundary.affected, "scope_complete": True,
            "protected_scope_enforced": store.protection is not None,
            "authority_granted": False, "scene_edited": False, "project_saved": False,
            "scope_basis": "reviewed native incoming ID consumers; arbitrary host Python is outside this proof",
            "preview_limit": MAX_PREVIEWS, "runtime_only": True}


def prepare_transform_scope(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    name = params.get("object_name")
    if not isinstance(name, str):
        raise invalid_argument("A reviewed transform requires an exact object_name.")
    pre_closure(bpy)
    objects, _references = _closure(bpy, _objects(bpy, [name])[0])
    require_profile(bpy, objects)
    check_affected(context, bpy, objects)
    return {"scope_complete": True, "affected_objects": [obj.name for obj in objects]}


def preview_boundary(context: ToolContext, params: Mapping[str, Any], *, checkpoint_roles: Any = None) -> Boundary:
    store = get_task_plans(context.state)
    store.check_revision(params.get("expected_revision"))
    identifier = params.get("preview_id")
    if not isinstance(identifier, str) or identifier not in store.previews:
        raise invalid_argument("Preview is missing, consumed or evicted; preview again.")
    transform_spec = context.registry.get("transform.set")
    if transform_spec.toolset not in context.registry.enabled_toolsets:
        raise BridgeError(ErrorCode.TOOLSET_DISABLED, "The preview's transform toolset is disabled.",
                          {"tool": "transform.set", "toolset": transform_spec.toolset})
    preview = store.previews[identifier]
    check_apply(context, identifier, preview, params)
    bpy = require_blender()
    if preview["policy_stamp"] != policy_stamp(context) or preview["plan_id"] != store.require_plan()["plan_id"]:
        raise invalid_argument("Preview protection or plan changed; preview again.")
    objects = _reference(context, bpy, preview["reference_id"])
    obj = next((obj for obj in objects if obj.name == preview["params"]["object_name"]), None)
    if obj is None:
        raise invalid_argument("Preview target identity changed.")
    # Preserve the stale-reference contract before consulting a native role
    # origin. These reads validate existing identities; they adopt no baseline.
    if checkpoint_roles is None:
        from ._artist_checkpoint_admission import current
        admission = current(context)
        checkpoint_roles = admission.roles if admission is not None and admission.preview is preview else preview["checkpoint_roles"].fork()
    checkpoint_roles.check_after_read()
    pre_closure(bpy)
    affected, _references = _closure(bpy, obj)
    require_profile(bpy, affected)
    boundary = Boundary(bpy, context, "transform.set", obj, transform=True, artist_profile=True,
                        checkpoint_roles=checkpoint_roles)
    require_profile(bpy, boundary.objects)
    check_affected(context, bpy, boundary.objects, stamp=preview["policy_stamp"])
    if _profile(boundary) != preview["profile"]:
        raise invalid_argument("Authored channels, context or consumers changed after preview; preview again.")
    check_apply(context, identifier, preview, params)
    return boundary


def prepare_preview_scope(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    boundary = preview_boundary(context, params)
    return {"scope_complete": True, "affected_objects": boundary.affected}


def apply_preview(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"preview_id", "expected_revision"})
    # Resolve live transform permission before the terminal preview CAS. A
    # preview itself never requires or grants edit permission.
    if context.check_cancelled:
        context.check_cancelled()
    context.require(Permission.INSPECT_SCENE, Permission.TRANSFORM_OBJECTS)
    final_lifetime_gate(context)
    prepare_preview_scope(context, params)
    final_lifetime_gate(context)
    store = get_task_plans(context.state)
    preview = store.previews.pop(params["preview_id"])
    check_apply(context, params["preview_id"], preview, params)
    if store.applying_preview is not None:
        raise invalid_argument("A preview is already being applied; nested application is unsupported.")
    store.applying_preview = preview
    try:
        from ._artist_checkpoint_admission import consumed
        consumed(context, preview)
        result = context.registry.dispatch("transform.set", deepcopy(preview["params"]), context)
    finally:
        if store.applying_preview is preview:
            store.applying_preview = None
    return {**result, "preview_id": params["preview_id"], "preview_consumed": True, "project_saved": False}


def register_tools(registry: ToolRegistry) -> None:
    from ._artist_checkpoint_admission import factory
    for name, handler, description in (
        ("task.plan.enforce", enforce_plan, "Explicitly enable/disable runtime plan protection; unknown modifying tools fail closed."),
        ("task.reference.resolve", resolve_reference, "Resolve bounded exact object names/current selection to runtime-only references; never infers visual intent."),
        ("task.plan.preview_transform", preview_transform, "Preview exact transform channels and reviewed consumer scope without acquiring edit authority."),
    ):
        registry.register(name, handler, permissions=(Permission.INSPECT_SCENE,), description=description,
                          batchable=False, record_history=False)
    registry.register("task.plan.apply_preview", apply_preview,
                      permissions=(Permission.INSPECT_SCENE, Permission.TRANSFORM_OBJECTS), modifies=True,
                      description="Apply one exact live transform preview once after renewed permission and context checks.", batchable=False,
                      protected_scope_resolver=prepare_preview_scope,
                      checkpoint_admission_factory=lambda context, params: factory("task.plan.apply_preview", context, params),
                      checkpoint_parameter_dependencies=lambda registry, _params: (registry.get("transform.set"),))
