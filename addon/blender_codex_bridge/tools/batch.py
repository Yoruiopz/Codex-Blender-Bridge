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
from contextlib import ExitStack
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..tool_registry import (
    ToolContext,
    ToolRegistry,
    ToolSpec,
    _checkpoint_parameters,
    check_final_mutation,
)
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
    return spec.remote and spec.batchable and (spec.toolset in SAFE_TOOLSETS or spec.name in SAFE_CORE)


def _checkpoint_parameter_dependencies(registry: ToolRegistry, params: Mapping[str, Any]) -> tuple[ToolSpec | None, ...]:
    """Retain exact child identities by position before outer callbacks.

    Invalid shapes retain their ordinary handler validation. No child provider,
    custom mapping or Blender descriptor is invoked by this classifier.
    """
    if type(params) is not dict:
        return ()
    steps = params.get("steps")
    if type(steps) is not list or not 1 <= len(steps) <= MAX_STEPS:
        return ()
    dependencies = []
    for step in tuple(steps):
        if type(step) is not dict or type(step.get("method")) is not str:
            dependencies.append(None)
            continue
        method = step["method"]
        if not 1 <= len(method) <= 128:
            dependencies.append(None)
            continue
        try:
            spec = registry.get(method)
        except BridgeError:
            spec = None
        dependencies.append(spec)
    return tuple(dependencies)


def _checkpoint_parameter_scope(registry: ToolRegistry, params: Mapping[str, Any]) -> bool:
    return any(spec is not None and spec.checkpoint_admission_factory is not None
               for spec in _checkpoint_parameter_dependencies(registry, params))


def _shape(context: ToolContext, params: Mapping[str, Any]) -> list[tuple[str, ToolSpec, dict[str, Any]]]:
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
    for index, step in enumerate(tuple(steps)):
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
        if spec.checkpoint_admission_factory is not None and not spec.checkpoint_batch_reviewed:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This guarded tool has no reviewed batch authored-state composition; use separate registered calls.",
                              {"execution_started": False, "checkpoint_batch_composition_reviewed": False, "step_index": index})
        ids.add(identifier)
        prepared.append((identifier, spec, arguments))
    return prepared


def _preflight(context: ToolContext, params: Mapping[str, Any]) -> list[tuple[str, ToolSpec, dict[str, Any]]]:
    prepared = _shape(context, params)
    for _identifier, spec, arguments in prepared:
        context.registry.prepare_call(spec.name, arguments, context)
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
    prepared = _shape(context, params)
    parameter_entry = context.registry.checkpoint_parameter_entry(context.registry.get("batch.execute"), params)
    guarded = any(spec.modifies and spec.checkpoint_admission_factory is not None for _identifier, spec, _arguments in prepared)
    if guarded and any(spec.modifies and spec.checkpoint_admission_factory is None for _identifier, spec, _arguments in prepared):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "A batch with static checkpoint admission requires a reviewed admission factory for every modifying step.",
                          {"execution_started": False, "checkpoint_admission_complete": False})
    if guarded:
        # Internal call token, never a result/wire flag. The outer executor
        # must not add an unguarded editor push after this batch owns it.
        context.checkpoint_finalization_owner = context.checkpoint_call_id
    finalization_owner = context.checkpoint_call_id if guarded else None
    original_plan = _checkpoint_parameters(params) if guarded else None

    def plan_unchanged() -> None:
        if guarded and getattr(context, "checkpoint_finalization_owner", None) is not finalization_owner:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Guarded batch finalization ownership changed; no legacy fallback is authorized.",
                              {"checkpoint_finalization_owner_valid": False})
        context.registry.check_checkpoint_parameter_entry(parameter_entry, params)
        if guarded and _checkpoint_parameters(params) != original_plan:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Guarded batch request changed during preflight or execution; later values are not adopted.",
                              {"checkpoint_parameters_unchanged": False})

    # Shape/spec lookup and bounded plan capture precede every child provider.
    for _identifier, spec, arguments in prepared:
        context.registry.prepare_call(spec.name, arguments, context)
        try:
            plan_unchanged()
        except BridgeError as error:
            error.context["execution_started"] = False
            raise
    deadline = time.monotonic() + float_param(params, "time_limit_seconds", 10.0, minimum=0.1, maximum=30.0)
    label = params.get("label", "Structured edit")
    results: list[dict[str, Any]] = []
    affected: set[str] = set()
    mutation_started = False
    undo_boundary = False
    undo_finalized = False
    finalization_attempted = False
    current_started = False
    current_spec = prepared[0][1]
    admission_stack = ExitStack()
    invocation_stack = ExitStack()
    current_admission = None
    finalization_gate = None
    finalization_after_read = None
    finalization_native_push = None
    index = 0
    try:
        for index, (identifier, spec, arguments) in enumerate(prepared):
            current_spec = spec
            current_started = False
            child_permit = invocation_stack.enter_context(context.registry.mutation_entry(spec, arguments, context))
            if context.check_cancelled is not None:
                context.check_cancelled()
            if time.monotonic() >= deadline:
                raise BridgeError(ErrorCode.TIMEOUT, "Batch time budget expired before the next step.")
            # Authoritative gates are repeated immediately before every step.
            context.registry.prepare_call(spec.name, arguments, context)
            plan_unchanged()

            # New-step providers run first. The previous frozen closure must
            # still match before a next factory can capture a new baseline.
            if current_admission is not None:
                current_admission()
            plan_unchanged()
            if spec.modifies and spec.checkpoint_admission_factory is not None:
                # The proved previous step is a transition predecessor, not a
                # live enclosing writer. Retire it before the next readonly
                # capture; its authored expectations must never be rebased to
                # include this later step's owned effects.
                admission_stack.close()
                current_admission = admission_stack.enter_context(context.registry.checkpoint_admission(spec, arguments, context))

            def step_write_gate(method=spec.name, admission=current_admission):
                if admission is not None:
                    admission()
                plan_unchanged()
                if time.monotonic() >= deadline:
                    raise BridgeError(ErrorCode.TIMEOUT, "Batch time budget expired before its next write.")
                check_final_mutation(context, method)

            def step_after_read(method=spec.name, admission=current_admission):
                if admission is not None:
                    admission.check_after_read()
                plan_unchanged()
                if time.monotonic() >= deadline:
                    raise BridgeError(ErrorCode.TIMEOUT, "Batch time budget expired before its next write.")
                check_final_mutation(context, method)

            def native_push_final(method=spec.name):
                plan_unchanged()
                check_final_mutation(context, method)

            step_native_push = (admission_stack.enter_context(context.registry.native_push_completion(
                child_permit, current_admission, context.checkpoints, final_check=native_push_final))
                if spec.modifies and current_admission is not None else None)

            if spec.modifies:
                finalization_gate = step_write_gate
                finalization_after_read = step_after_read
                finalization_native_push = step_native_push

            if time.monotonic() >= deadline:
                raise BridgeError(ErrorCode.TIMEOUT, "Batch time budget expired during step preflight.")
            if spec.modifies and not mutation_started:
                step_write_gate()
                undo_boundary = context.checkpoints.before_modification(
                    f"Batch: {label}", before_write=step_write_gate, after_read=step_after_read,
                    after_native_push=step_native_push if current_admission is not None else None)
            if spec.modifies:
                step_write_gate()
            elif time.monotonic() >= deadline:
                raise BridgeError(ErrorCode.TIMEOUT, "Batch time budget expired before handler entry.")
            start = time.perf_counter()
            entries_before = context.handler_entries
            try:
                try:
                    result = context.registry.invoke(spec, arguments, context, _permit=child_permit)
                finally:
                    current_started = context.handler_entries > entries_before
                    mutation_started = mutation_started or (current_started and spec.modifies)
            except Exception as exc:
                error_code = exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED.value
                context.state.record_operation(
                    tool=spec.name, description=f"Batch {label} [{index + 1}/{len(prepared)}] failed; reinspect",
                    success=False, duration_ms=(time.perf_counter() - start) * 1000, error_code=error_code,
                )
                raise
            if current_admission is not None:
                current_admission()
            plan_unchanged()
            names = affected_objects_from_result(result)
            affected.update(names)
            record = context.state.record_operation(
                tool=spec.name, description=f"Batch {label} [{index + 1}/{len(prepared)}]",
                success=True, duration_ms=(time.perf_counter() - start) * 1000, affected_objects=names,
            )
            results.append({"id": identifier, "method": spec.name, "ok": True,
                            "operation_id": record.operation_id, "result": _bounded_result(result)})
        if mutation_started and undo_boundary:
            finalization_attempted = True
            undo_finalized = bool(context.checkpoints.after_modification(f"Batch: {label}", before_write=finalization_gate, after_read=finalization_after_read, after_native_push=finalization_native_push)
                if current_admission is not None else context.checkpoints.after_modification(f"Batch: {label}"))
    except Exception as exc:
        finalization_denial = None
        if mutation_started and undo_boundary and not finalization_attempted:
            finalization_attempted = True
            try:
                undo_finalized = bool(context.checkpoints.after_modification(f"Batch: {label}", before_write=finalization_gate, after_read=finalization_after_read, after_native_push=finalization_native_push)
                    if current_admission is not None else context.checkpoints.after_modification(f"Batch: {label}"))
            except BridgeError as secondary:
                finalization_denial = secondary
        if isinstance(exc, BridgeError):
            error = exc
        else:
            LOGGER.exception("Batch step %s failed", current_spec.name)
            error = BridgeError(ErrorCode.OPERATION_FAILED, "A structured batch step failed.",
                                {"exception_type": type(exc).__name__})
        affected.update(affected_objects_from_result(error.context))
        bookkeeping_started = undo_boundary or bool(error.context.get("checkpoint_authority_rejected") and error.context.get("execution_started"))
        context_data = {
            "batch_label": label, "atomic": False, "completed_steps": len(results),
            "failed_step_index": index, "failed_method": current_spec.name,
            "failed_step_started": current_started, "total_steps": len(prepared),
            "results": results, "cause": _bounded_result(error.context),
            "execution_started": mutation_started or bookkeeping_started, "mutation_outcome_unknown": mutation_started,
            "affected_objects": sorted(affected)[:128], "affected_objects_truncated": len(affected) > 128,
            "verification_required": mutation_started or bookkeeping_started, "undo_boundary_created": undo_boundary,
            "undo_boundary_finalized": undo_finalized,
            "rollback_performed": False,
        }
        if error.context.get("checkpoint_bookkeeping") is not None:
            context_data["checkpoint_bookkeeping"] = error.context["checkpoint_bookkeeping"]
        if finalization_denial is not None:
            context_data["checkpoint_finalization_refused"] = {"code": finalization_denial.code,
                "bookkeeping": finalization_denial.context.get("checkpoint_bookkeeping"), "primary_error_preserved": True}
        raise BridgeError(error.code, f"Batch stopped at step {index + 1}: {error.message}", context_data) from exc
    finally:
        try:
            admission_stack.close()
        finally:
            invocation_stack.close()
    return {
        "batch_label": label, "atomic": False, "completed_steps": len(results),
        "total_steps": len(prepared), "results": results,
        "affected_objects": sorted(affected)[:128], "affected_objects_truncated": len(affected) > 128,
        "verification_required": mutation_started, "rollback_performed": False,
        "operation": {"undo_boundary_created": undo_boundary, "undo_boundary_finalized": undo_finalized, "scope": "logical_batch"},
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register("batch.plan", batch_plan, toolset="batch",
                      checkpoint_parameter_scope=_checkpoint_parameter_scope,
                      checkpoint_parameter_dependencies=_checkpoint_parameter_dependencies,
                      description="Preflight batch shape and permissions, not scene state or handler arguments.")
    registry.register("batch.execute", batch_execute, toolset="batch", modifies=True, automatic_checkpoint=False,
                      checkpoint_parameter_scope=_checkpoint_parameter_scope,
                      checkpoint_parameter_dependencies=_checkpoint_parameter_dependencies,
                      checkpoint_owns_finalization=True,
                      description="Run up to 32 structured steps serially with one logical undo marker; stop on first error.")
