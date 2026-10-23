"""Typed, unbaked rigid-body evaluation through the owned Scene scheduler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..entry_effects import mark_view_layer_sync_possible
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..scene_jobs import start_admission
from ..utils import int_param, reject_unknown_params, require_blender
from . import _animation_scope as evidence
from . import _rigid_body_scope as scope
from . import _scene_checkpoint_roles as checkpoint_roles

PREVIEW = "rigid_body.evaluate_preview"
START = "rigid_body.evaluate_job_start"
PERMISSIONS = (Permission.INSPECT_SCENE, Permission.EDIT_SCENE, Permission.EDIT_ANIMATION)
FIELDS = frozenset({"scene_name", "body_names", "constraint_names", "frame_start", "frame_end", "time_limit_seconds"})
POLICY = "STATIC_WHOLE_WORLD_UNBAKED_EVALUATION_V1"


def prepare(bpy: Any, params: Mapping[str, Any], *, starting: bool = False):
    reject_unknown_params(params, FIELDS | ({"expected_fingerprint"} if starting else set()))
    scene = scope.current_scene(bpy, params.get("scene_name"))
    start = int_param(params, "frame_start", 0, minimum=1, maximum=1048574)
    end = int_param(params, "frame_end", 0, minimum=1, maximum=1048574)
    limit = int_param(params, "time_limit_seconds", 60, minimum=1, maximum=300)
    if not 1 <= end-start+1 <= scope.MAX_FRAMES:
        raise invalid_argument("Rigid evaluation requires an ordered range of at most 32 integer frames.")
    bodies = scope.explicit_names(params.get("body_names"), "body_names", maximum=scope.MAX_BODIES)
    constraints = scope.explicit_names(params.get("constraint_names"), "constraint_names", maximum=0)
    frozen_params = {"scene_name": scene.name, "body_names": list(bodies), "constraint_names": list(constraints)}
    mark_view_layer_sync_possible()
    snapshot = scope.snapshot(bpy, scene, frozen_params)
    mark_view_layer_sync_possible()
    active = bpy.context.view_layer.objects.active
    if active is None or active.type != "EMPTY":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "Rigid evaluation jobs currently require a plain active Empty; no selection is changed.",
                          {"active_context_supported": False, "execution_started": False})
    roles = checkpoint_roles.Plan(bpy, scene)
    authored_roles = roles.authored()
    if scene.rigidbody_world.point_cache.is_baked:
        raise invalid_argument("Explicitly FREE the baked cache and obtain a new evaluation preview first.")
    proposal = {"policy": POLICY, "frame_start": start, "frame_end": end, "time_limit_seconds": limit}
    fingerprint = evidence.digest({"scope": snapshot, "checkpoint_roles": authored_roles, "proposal": proposal})
    if starting and params.get("expected_fingerprint") != fingerprint:
        raise invalid_argument("The exact rigid evaluation preview is stale or missing; preview again before starting.")
    return scene, frozen_params, snapshot, roles, authored_roles, proposal, fingerprint


def evaluate_preview(context, params):
    context.require(Permission.INSPECT_SCENE)
    scene, frozen, snapshot, _roles, _authored, proposal, fingerprint = prepare(require_blender(), params)
    return {"scene": scene.name, "body_names": frozen["body_names"], "constraint_names": [],
            "affected_objects": frozen["body_names"], **proposal, "expected_fingerprint": fingerprint,
            "fingerprint_lifetime": "CURRENT_SESSION_AND_EXACT_CONTEXT", "base_vertices": snapshot["base_vertices"],
            "resets_existing_unbaked_memory_cache": True, "proposed_cache_range_retained": True,
            "active_context_profile": "PLAIN_EMPTY_WITH_EXACT_SELECTION_PRESERVED",
            "bake_requested": False, "cache_coverage": "NOT_ASSESSED", "project_saved": False,
            "durable_backup_created": False, "native_calls_preemptible": False,
            "protected_plan_support": False, "maximum_active_jobs": 1}


def driver_factory(context, params):
    from ._rigid_evaluation_job import RigidEvaluationDriver
    bpy = require_blender()
    return RigidEvaluationDriver(bpy, prepare(bpy, params, starting=True))


def evaluate_job_start(context, params):
    return context.jobs.start_scene(context, params, time_limit=params.get("time_limit_seconds", 60))


def register(registry):
    registry.register(PREVIEW, evaluate_preview, toolset="simulation", permissions=(Permission.INSPECT_SCENE,),
                      description="Preview an exact bounded whole-world unbaked evaluation job with a plain active Empty.")
    registry.register(START, evaluate_job_start, toolset="simulation", permissions=PERMISSIONS,
                      modifies=True, batchable=False, automatic_checkpoint=False, exclusive_mutation=True,
                      checkpoint_owns_finalization=True, checkpoint_admission_factory=start_admission(driver_factory),
                      description="Start an owned timer-separated rigid evaluation; inspect/cancel through jobs tools. No bake or cache-coverage claim.")
