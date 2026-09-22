"""Bounded serial composition of registered structured tools, never scripts.

Preflight checks shape, registration, enablement, and static permissions only.
Handler arguments and scene dependencies are checked at each step. This is not
an atomic transaction: failed or interrupted batches retain audited partial work.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..tool_registry import ToolContext, ToolRegistry, ToolSpec
from ..utils import affected_objects_from_result, float_param

LOGGER = logging.getLogger(__name__)
MAX_STEPS = 32
MAX_RESULT_BYTES = 16 * 1024
SAFE_TOOLSETS = frozenset({
    "objects", "mesh", "materials", "nodes", "uv", "modifiers", "constraints",
    "animation", "rigging", "scene_edit", "interaction", "layout", "geometry_nodes",
})
SAFE_CORE = frozenset({"project.info", "scene.inspect", "scene.summary", "selection.inspect", "object.inspect"})


def is_batch_supported(spec: ToolSpec) -> bool:
    return spec.remote and (spec.toolset in SAFE_TOOLSETS or spec.name in SAFE_CORE)


def _preflight(context: ToolContext, params: Mapping[str, Any]) -> list[tuple[str, ToolSpec, dict[str, Any]]]:
    unknown = set(params) - {"steps", "label", "time_limit_seconds"}
    if unknown:
        raise invalid_argument("Unknown batch parameters.", parameters=sorted(unknown))
    label = params.get("label", "Structured edit")
    if not isinstance(label, str) or not label.strip() or len(label) > 120:
        raise invalid_argument("'label' must contain 1-120 characters.")
    float_param(params, "time_limit_seconds", 10.0, minimum=0.1, maximum=30.0)
    steps = params.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise invalid_argument(f"'steps' must contain 1-{MAX_STEPS} objects.")
    prepared = []
    ids: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) - {"id", "method", "params"}:
            raise invalid_argument("Each step accepts only id, method, and params.", step_index=index)
        identifier = step.get("id", str(index + 1))
        method = step.get("method")
        arguments = step.get("params", {})
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 64 or identifier in ids:
            raise invalid_argument("Step IDs must be unique non-empty strings of at most 64 characters.", step_index=index)
        if not isinstance(method, str) or not 1 <= len(method) <= 128 or not isinstance(arguments, dict):
            raise invalid_argument("Each step requires a method string and object params.", step_index=index)
        spec = context.registry.get(method)
        if not is_batch_supported(spec):
            raise invalid_argument(
                "This method is not batch-supported. Python, render/capture, save, recovery, and lifecycle tools must be separate calls.",
                step_index=index, method=method,
            )
        # Preflight *every* gate before creating the first undo marker.
        context.registry.prepare(method, context)
        ids.add(identifier)
        prepared.append((identifier, spec, arguments))
    return prepared


def batch_plan(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    prepared = _preflight(context, params)
    return {
        "ready": True,
        "preflight_scope": "shape, registration, toolsets, static permissions; NOT handler arguments or scene dependencies",
        "atomic": False,
        "steps": [
            {"id": identifier, "method": spec.name, "modifies": spec.modifies,
             "toolset": spec.toolset, "required_permissions": sorted(p.value for p in spec.permissions)}
            for identifier, spec, _arguments in prepared
        ],
        "required_permissions": sorted({p.value for _, spec, _ in prepared for p in spec.permissions}),
        "verification_required": any(spec.modifies for _, spec, _ in prepared),
    }


def _bounded_result(result: Any) -> Any:
    """Keep each step's evidence bounded without discarding its audit envelope."""

    size = 0
    try:
        for chunk in json.JSONEncoder(allow_nan=False, ensure_ascii=True).iterencode(result):
            size += len(chunk)
            if size > MAX_RESULT_BYTES:
                break
        else:
            return result
    except (TypeError, ValueError, OverflowError, RecursionError):
        pass
    return {
        "result_truncated": True, "result_limit_bytes": MAX_RESULT_BYTES,
        "affected_objects": list(affected_objects_from_result(result))[:128],
        "verification_required": True,
    }


def batch_execute(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    prepared = _preflight(context, params)
    deadline = time.monotonic() + float_param(params, "time_limit_seconds", 10.0, minimum=0.1, maximum=30.0)
    label = params.get("label", "Structured edit")
    results: list[dict[str, Any]] = []
    affected: set[str] = set()
    mutation_started = False
    undo_boundary = False
    current_started = False
    current_spec = prepared[0][1]
    index = 0
    try:
        for index, (identifier, spec, arguments) in enumerate(prepared):
            current_spec = spec
            current_started = False
            if context.check_cancelled is not None:
                context.check_cancelled()
            if time.monotonic() >= deadline:
                raise BridgeError(ErrorCode.TIMEOUT, "Batch time budget expired before the next step.")
            # Authoritative gates are repeated immediately before every step.
            context.registry.prepare(spec.name, context)
            if spec.modifies and not mutation_started:
                undo_boundary = context.checkpoints.before_modification(f"Batch: {label}")
            mutation_started = mutation_started or spec.modifies
            current_started = True
            start = time.perf_counter()
            try:
                result = spec.handler(context, arguments)
            except Exception as exc:
                error_code = exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED.value
                context.state.record_operation(
                    tool=spec.name, description=f"Batch {label} [{index + 1}/{len(prepared)}] failed; reinspect",
                    success=False, duration_ms=(time.perf_counter() - start) * 1000, error_code=error_code,
                )
                raise
            names = affected_objects_from_result(result)
            affected.update(names)
            record = context.state.record_operation(
                tool=spec.name, description=f"Batch {label} [{index + 1}/{len(prepared)}]",
                success=True, duration_ms=(time.perf_counter() - start) * 1000, affected_objects=names,
            )
            results.append({"id": identifier, "method": spec.name, "ok": True,
                            "operation_id": record.operation_id, "result": _bounded_result(result)})
    except Exception as exc:
        if isinstance(exc, BridgeError):
            error = exc
        else:
            LOGGER.exception("Batch step %s failed", current_spec.name)
            error = BridgeError(ErrorCode.OPERATION_FAILED, "A structured batch step failed.",
                                {"exception_type": type(exc).__name__})
        affected.update(affected_objects_from_result(error.context))
        context_data = {
            "batch_label": label, "atomic": False, "completed_steps": len(results),
            "failed_step_index": index, "failed_method": current_spec.name,
            "failed_step_started": current_started, "total_steps": len(prepared),
            "results": results, "cause": _bounded_result(error.context),
            "execution_started": mutation_started, "mutation_outcome_unknown": mutation_started,
            "affected_objects": sorted(affected)[:128], "affected_objects_truncated": len(affected) > 128,
            "verification_required": mutation_started, "undo_boundary_created": undo_boundary,
            "rollback_performed": False,
        }
        raise BridgeError(error.code, f"Batch stopped at step {index + 1}: {error.message}", context_data) from exc
    finally:
        if mutation_started and undo_boundary:
            context.checkpoints.after_modification(f"Batch: {label}")
    return {
        "batch_label": label, "atomic": False, "completed_steps": len(results),
        "total_steps": len(prepared), "results": results,
        "affected_objects": sorted(affected)[:128], "affected_objects_truncated": len(affected) > 128,
        "verification_required": mutation_started, "rollback_performed": False,
        "operation": {"undo_boundary_created": undo_boundary, "scope": "logical_batch"},
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register("batch.plan", batch_plan, toolset="batch",
                      description="Preflight batch shape and permissions, not scene state or handler arguments.")
    registry.register("batch.execute", batch_execute, toolset="batch", modifies=True, automatic_checkpoint=False,
                      description="Run up to 32 structured steps serially with one logical undo marker; stop on first error.")
