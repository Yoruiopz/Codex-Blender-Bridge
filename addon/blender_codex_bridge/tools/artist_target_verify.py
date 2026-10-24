"""Explicit current-receipt observations of intended Object core channels.

This tool observes authored channels, not evaluated transforms or artistic
completion. It performs no context lookup, dependency-graph update, checkpoint
or native write. Successful calls add no operation-history entry; the executor
retains its usual failed-call audit. The runtime journal stores a historical fact.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry, ToolSpec, check_final_mutation
from ..utils import require_blender

METHOD = "task.plan.verify_transform"
SCOPE = "authored_core_transform_channels"
STEP_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
RECEIPT_ID = re.compile(r"step_receipt_[a-f0-9]{32}")


def _parameters(params: Mapping[str, Any]) -> dict[str, Any]:
    # Wire parameters are plain JSON. Avoid custom Mapping/equality callbacks
    # when these same bounded values are checked after the native observation.
    if type(params) is not dict or any(type(key) is not str for key in params):
        raise invalid_argument("Target verification requires plain structured parameters.")
    if set(params) != {"step_id", "receipt_id", "expected_revision"}:
        raise invalid_argument("Supply only step_id, receipt_id and expected_revision.")
    step, receipt, revision = params["step_id"], params["receipt_id"], params["expected_revision"]
    if type(step) is not str or STEP_ID.fullmatch(step) is None:
        raise invalid_argument("step_id requires 1-64 ASCII letters, digits, underscores or hyphens.")
    if type(receipt) is not str or RECEIPT_ID.fullmatch(receipt) is None:
        raise invalid_argument("receipt_id must be an exact retained step_receipt_ identifier.")
    if type(revision) is not int or not 1 <= revision <= 1_000_000_000:
        raise invalid_argument("expected_revision must be an integer from 1 to 1000000000.")
    return {"step_id": step, "receipt_id": receipt, "expected_revision": revision}


def _spec(context: ToolContext) -> ToolSpec:
    spec = context.registry.get(METHOD)
    if (spec.handler is not verify_transform or spec.modifies or spec.toolset != "core"
            or spec.permissions != frozenset({Permission.INSPECT_SCENE})
            or spec.automatic_checkpoint or spec.batchable or spec.record_history
            or not spec.remote or spec.exclusive_mutation or spec.protected_scope_resolver is not None
            or spec.checkpoint_admission_factory is not None or spec.checkpoint_parameter_scope is not None
            or spec.checkpoint_parameter_dependencies is not None or spec.checkpoint_owns_finalization
            or spec.checkpoint_batch_reviewed):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "Target verification requires its exact registered read-only contract.")
    return spec


def _live(context: ToolContext, spec: ToolSpec) -> None:
    context.require(Permission.INSPECT_SCENE)
    if context.check_cancelled is not None:
        context.check_cancelled()
    context.require(Permission.INSPECT_SCENE)
    check_final_mutation(context, METHOD, expected_spec=spec)


def verify_transform(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    # Lazy imports keep ordinary tool registration independent of per-request
    # journal state and keep Blender out of the standalone MCP process.
    from ..artist_step_evidence import (
        append_target_observation,
        check_target_verify_entry,
        require_target_verify_entry,
    )
    from ..artist_target_intent import compare_target, read_target

    request = _parameters(params)
    spec = _spec(context)
    entry = require_target_verify_entry(context, request)
    _live(context, spec)
    check_target_verify_entry(context, entry, request)
    intent = entry.target_intent
    if intent.availability != "available":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "This receipt has no qualified independent core-channel expectation.",
                          {"verification_available": False, "reason": intent.reason,
                           "profile": intent.profile, "scope": SCOPE,
                           "target_channels_read": False, "user_goal_verified": False})
    bpy = require_blender()
    check_target_verify_entry(context, entry, request)
    observed = read_target(bpy, intent)
    evidence = compare_target(intent, observed)

    # All live permission/cancellation providers precede the bounded static
    # reads. Only plain parameter/provenance and trusted lifecycle checks follow.
    if _parameters(params) != request:
        raise invalid_argument("Target verification parameters changed; no observation was attached.")
    check_target_verify_entry(context, entry, request)
    check_final_mutation(context, METHOD, expected_spec=spec)
    observation = append_target_observation(
        context, entry, evidence,
        before_attach=lambda: check_final_mutation(context, METHOD, expected_spec=spec),
    )
    return {"step_id": entry.association.step_id, "receipt_id": entry.receipt_id,
            "operation_id": entry.operation_id, "target_observation": observation,
            "scope": SCOPE, "user_goal_verified": False, "current_scene_verified": False}


def register_tools(registry: ToolRegistry) -> None:
    registry.register(METHOD, verify_transform, permissions=(Permission.INSPECT_SCENE,),
                      toolset="core", modifies=False, automatic_checkpoint=False,
                      batchable=False, record_history=False,
                      description="Compare one current successful artist-step receipt's independently predicted Object core channels with its exact named target; no evaluated, visual or completion claim.")
