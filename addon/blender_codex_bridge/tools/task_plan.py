"""Typed artist-plan controls and explicit advisory preservation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..artist_step_evidence import associate, latest, observe
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..task_plans import (
    MAX_SAVED_BYTES,
    SCENE_PROPERTY,
    STEP_STATUSES,
    contents,
    decode_saved,
    encode_saved,
    get_task_plans,
    text,
)
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, reject_unknown_params, require_blender
from ._object_safety import require_local_editable_id


def _identity(value: Any) -> Any:
    uid = getattr(value, "session_uid", None)
    return (uid if uid is not None else value.as_pointer() if hasattr(value, "as_pointer") else id(value))


def _scope(bpy: Any, names: list[str], check=None) -> tuple[Any, tuple[tuple[str, Any], ...]]:
    matches: dict[str, list[Any]] = {name: [] for name in names}
    for index, obj in enumerate(bpy.context.scene.objects):
        if check is not None and index % 256 == 0:
            check()
        if obj.name in matches and len(matches[obj.name]) < 2:
            matches[obj.name].append(obj)
    unresolved = [name for name in names if len(matches[name]) != 1]
    if unresolved:
        raise invalid_argument("Protected objects must resolve to unique exact names in the current scene.", unresolved=unresolved)
    return _identity(bpy.context.scene), tuple((name, _identity(matches[name][0])) for name in names)


def _checked_scope(context: ToolContext, store: Any, bpy: Any) -> None:
    if _scope(bpy, store.require_plan()["protected_objects"], context.check_cancelled) != store.scope:
        raise invalid_argument("Task-plan scene or protected-object identity changed; explicitly correct or reload the plan before new evidence.")


def set_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"goal", "steps", "protected_objects", "expected_revision"})
    parsed = contents(params.get("goal"), params.get("steps"), params.get("protected_objects", []))
    bpy = require_blender()
    scope = _scope(bpy, parsed["protected_objects"], context.check_cancelled)
    store = get_task_plans(context.state)
    store.replace(parsed, scope, params.get("expected_revision"))
    context.state.set_task(parsed["goal"])
    return store.inspect(context.evidence)


def inspect_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, set())
    return get_task_plans(context.state).inspect(context.evidence)


def update_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"step_id", "status", "note", "expected_revision"})
    store = get_task_plans(context.state)
    store.check_revision(params.get("expected_revision"))
    parsed = deepcopy(store.require_plan())
    identifier = params.get("step_id")
    if not isinstance(identifier, str):
        raise invalid_argument("'step_id' must identify an existing plan step.")
    step = next((item for item in parsed["steps"] if item["id"] == identifier), None)
    if step is None:
        raise invalid_argument("The task plan has no step with this exact ID.")
    if not any(key in params for key in ("status", "note")):
        raise invalid_argument("Supply a step status or note correction.")
    if "status" in params:
        status = params["status"]
        if not isinstance(status, str) or status not in STEP_STATUSES:
            raise invalid_argument("Unsupported step status.", supported=list(STEP_STATUSES))
        step["status"] = status
    if "note" in params:
        step["note"] = text(params["note"], "note", 500, empty=True)
    parsed["revision"] += 1
    encode_saved(parsed)
    store.plan = parsed
    return store.inspect(context.evidence)


def capture_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"fields", "max_elements"})
    store = get_task_plans(context.state)
    plan = store.require_plan()
    if not plan["protected_objects"]:
        raise invalid_argument("The task plan has no named protected objects to capture.")
    bpy = require_blender()
    _checked_scope(context, store, bpy)
    result = context.evidence.capture(bpy, {"object_names": plan["protected_objects"], **params}, context.check_cancelled)
    _checked_scope(context, store, bpy)
    store.baseline = {"snapshot_id": result["snapshot_id"], "captured_revision": plan["revision"], "coverage_complete": result["coverage_complete"], "fields": result["fields"]}
    return {**store.inspect(context.evidence), "evidence": result}


def compare_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"max_elements", "step_id", "expected_revision"})
    store = get_task_plans(context.state)
    store.require_plan()
    if store.baseline is None:
        raise invalid_argument("Capture the plan's protected objects before comparison; saved plans contain no live baseline.")
    association = None
    if "step_id" in params:
        store.check_revision(params.get("expected_revision"))
        association = associate(store, params["step_id"])
        receipt_id = latest(store, association.step_id)["receipt_id"]
        baseline = deepcopy(store.baseline)
        mutation_revision = store.evidence_revision
    elif "expected_revision" in params:
        raise invalid_argument("expected_revision requires step_id for a step-linked comparison.")
    # Compare must report missing/replaced protected objects as changed, not hide them
    # behind the stricter preconditions needed to create a new baseline.
    arguments = {"snapshot_id": store.baseline["snapshot_id"]}
    if "max_elements" in params:
        arguments["max_elements"] = params["max_elements"]
    result = context.evidence.compare(require_blender(), arguments, context.check_cancelled)
    if association is not None:
        from .artist_loop import final_lifetime_gate
        context.require(Permission.INSPECT_SCENE)
        final_lifetime_gate(context)
        if get_task_plans(context.state) is not store:
            raise invalid_argument("Runtime plan store changed during comparison; no step evidence was attached.")
        observe(store, association, receipt_id, baseline, mutation_revision, result)
    return {**store.inspect(context.evidence), "evidence": result}


def persist_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"confirm", "expected_revision"})
    if not bool_param(params, "confirm", False):
        raise invalid_argument("Set 'confirm' to true to store this plan in the active scene; this does not save the project.")
    store = get_task_plans(context.state)
    store.check_revision(params.get("expected_revision"))
    bpy = require_blender()
    _checked_scope(context, store, bpy)
    scene = bpy.context.scene
    require_local_editable_id(scene, operation="Task-plan persistence")
    raw = encode_saved(store.require_plan())
    previous = scene.get(SCENE_PROPERTY)
    present = SCENE_PROPERTY in scene
    if present:
        # This bridge property is bounded text, never a container/ID to traverse
        # or replace implicitly. Malformed bounded text can still be repaired.
        try:
            valid_previous = isinstance(previous, str) and len(previous.encode("utf-8")) <= MAX_SAVED_BYTES
        except UnicodeError:
            valid_previous = False
        if not valid_previous:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing task-plan storage is not bounded UTF-8 text; repair it explicitly.")
    session = (_identity(scene), _identity(bpy.context.view_layer),
               getattr(getattr(bpy, "data", None), "filepath", ""), getattr(bpy.context, "mode", "OBJECT"))

    def stored() -> tuple[bool, Any]:
        return SCENE_PROPERTY in scene, scene.get(SCENE_PROPERTY)

    def check(expected: tuple[bool, Any]) -> None:
        # Permission providers and cancellation hooks can execute callbacks.
        # Run every callback before the terminal, callback-free scope/CAS check.
        if context.check_cancelled:
            context.check_cancelled()
        context.require(Permission.INSPECT_SCENE, Permission.EDIT_SCENE)
        if context.check_cancelled:
            context.check_cancelled()
        flags = context.state.snapshot()
        if flags["emergency_stopped"]:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Task-plan persistence stopped before another write.")
        if flags["paused"]:
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Task-plan persistence paused before another write.")
        current_session = (_identity(bpy.context.scene), _identity(bpy.context.view_layer),
                           getattr(getattr(bpy, "data", None), "filepath", ""), getattr(bpy.context, "mode", "OBJECT"))
        if current_session != session or bpy.context.scene is not scene:
            raise invalid_argument("Task-plan persistence scene or editing context changed.")
        require_local_editable_id(scene, operation="Task-plan persistence")
        if encode_saved(store.require_plan()) != raw or _scope(bpy, store.require_plan()["protected_objects"]) != store.scope:
            raise invalid_argument("Task plan or protected-object scope changed before persistence.")
        if stored() != expected:
            raise invalid_argument("Task-plan scene property changed; newer storage is retained.")

    before = (present, previous)
    check(before)
    try:
        scene[SCENE_PROPERTY] = raw
        check((True, raw))
    except Exception as exc:
        try:
            rollback_verified = stored() == before
        except Exception:
            rollback_verified = False
        recovery = "unchanged" if rollback_verified else "explicit_recovery_required"
        try:
            if not rollback_verified:
                # Never overwrite an interleaved edit or compensate after lost
                # consent, context, identity, plan revision or live stop state.
                check((True, raw))
                if present:
                    scene[SCENE_PROPERTY] = previous
                else:
                    del scene[SCENE_PROPERTY]
                rollback_verified = stored() == before
                recovery = "restored" if rollback_verified else "explicit_recovery_required"
        except Exception:
            pass
        error = exc if isinstance(exc, BridgeError) else BridgeError(ErrorCode.OPERATION_FAILED, "Task-plan persistence failed; inspect the scene property before retrying.")
        error.context.update(execution_started=True, rollback_verified=rollback_verified,
                             possible_mutation=not rollback_verified, verification_required=True,
                             recovery=recovery, project_saved=False)
        raise error from (exc if error is not exc else None)
    return {**store.inspect(context.evidence), "stored_in_scene": scene.name, "scene_property": SCENE_PROPERTY, "project_saved": False}


def load_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"expected_revision"})
    store = get_task_plans(context.state)
    store.require_advisory("loading a plan")
    bpy = require_blender()
    parsed = decode_saved(bpy.context.scene.get(SCENE_PROPERTY))
    scope = _scope(bpy, parsed["protected_objects"], context.check_cancelled)
    if store.plan is not None:
        store.check_revision(params.get("expected_revision"))
        parsed["revision"] = store.plan["revision"] + 1
    elif params.get("expected_revision") is not None:
        raise invalid_argument("There is no existing plan for 'expected_revision'.")
    encode_saved(parsed)
    # A loaded document begins a fresh runtime baseline. Saved snapshot IDs and
    # operational authority are never imported from project data.
    store.plan = parsed
    store.scope, store.baseline = scope, None
    store.reset_step_evidence()
    store.invalidate_handles()
    context.state.set_task(parsed["goal"])
    return {**store.inspect(context.evidence), "loaded_from_scene": bpy.context.scene.name}


def clear_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"expected_revision"})
    store = get_task_plans(context.state)
    store.require_advisory("clearing a plan")
    store.check_revision(params.get("expected_revision"))
    store.clear()
    context.state.set_task("")
    return {**store.inspect(context.evidence), "stored_scene_property_removed": False}


def register_tools(registry: ToolRegistry) -> None:
    from . import artist_loop, artist_target_verify
    for name, handler, description in (
        ("set", set_plan, "Create or revision-check replacement of a bounded artist task plan; protected objects are advisory."),
        ("inspect", inspect_plan, "Inspect the current artist plan, steps and advisory protected scope."),
        ("update", update_plan, "Revision-check and correct one plan step's status or note."),
        ("capture", capture_plan, "Capture bounded structural evidence for exact advisory protected objects."),
        ("compare", compare_plan, "Compare protected-object evidence explicitly; incomplete evidence never proves preservation."),
        ("load", load_plan, "Explicitly validate/load scene-stored JSON as plan data; no executable instructions or baseline restoration."),
        ("clear", clear_plan, "Clear only the runtime artist plan; leave stored scene data unchanged."),
    ):
        registry.register(f"task.plan.{name}", handler, permissions=(Permission.INSPECT_SCENE,), description=description, batchable=False, record_history=False)
    registry.register("task.plan.persist", persist_plan, permissions=(Permission.INSPECT_SCENE, Permission.EDIT_SCENE), modifies=True, description="Explicitly store validated plan JSON in the active scene without saving the project.", batchable=False)
    artist_loop.register_tools(registry)
    artist_target_verify.register_tools(registry)
