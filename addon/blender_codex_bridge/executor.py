"""Blender main-thread dispatcher driven by ``bpy.app.timers``."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from .artist_step_evidence import capture_call, record_terminal
from .checkpoints import CheckpointManager
from .command_queue import CommandQueue, QueuedRequest
from .entry_effects import annotate_entry_error
from .errors import BridgeError, ErrorCode
from .operation_lease import InvocationPermit
from .permissions import PermissionManager
from .protocol import PROTOCOL_VERSION, Request, Response
from .scene_evidence import SceneEvidenceStore
from .state import BridgeState, bounded_external_effects, bounded_recovery_evidence
from .task_plans import get_task_plans
from .tool_registry import ToolContext, ToolRegistry, check_final_mutation
from .utils import affected_objects_from_result, require_blender

LOGGER = logging.getLogger(__name__)


def _history_description(
    request: Request,
    *,
    outcome: str,
    metadata: Mapping[str, Any] | None = None,
    fallback: str,
) -> str:
    if request.method in {"image.paint_job_start", "image.paint_surface_job_start"} and outcome == "completed" and metadata:
        return f"Accepted paint job {metadata.get('job_id', '')}; image not yet committed"
    if request.method == "image.export_job_start" and outcome == "completed" and metadata:
        return f"Accepted texture delivery job {metadata.get('job_id', '')}; export/reimport not yet completed"
    if request.method in {"image.snapshot_job_start", "image.restore_snapshot_job_start"} and outcome == "completed" and metadata:
        return f"Accepted image recovery job {metadata.get('job_id', '')}; recovery not yet completed"
    if request.method != "python.execute":
        return fallback
    effect = request.params.get("expected_effect")
    effect_text = effect.strip() if isinstance(effect, str) and effect.strip() else "unspecified effect"
    digest = metadata.get("script_digest") if metadata is not None else None
    digest_text = digest if isinstance(digest, str) and digest else "unvalidated"
    return f"Python {outcome} [{digest_text}]: {effect_text}"


def _affected_objects_from_error(error: BridgeError) -> tuple[str, ...]:
    names = list(affected_objects_from_result(error.context))
    for key in ("objects_added", "objects_removed"):
        value = error.context.get(key)
        if not isinstance(value, Mapping):
            continue
        items = value.get("items")
        if isinstance(items, list):
            names.extend(item for item in items if isinstance(item, str) and item)
    return tuple(dict.fromkeys(names))


class MainThreadExecutor:
    """Execute queued tools exclusively from Blender's main UI thread."""

    def __init__(
        self,
        *,
        command_queue: CommandQueue,
        registry: ToolRegistry,
        state: BridgeState,
        permissions: PermissionManager,
        checkpoints: CheckpointManager,
        interval: float = 0.05,
        maximum_per_tick: int = 4,
        jobs: Any = None,
    ) -> None:
        self.command_queue = command_queue
        self.registry = registry
        self.state = state
        self.permissions = permissions
        self.checkpoints = checkpoints
        self.evidence = SceneEvidenceStore()
        self.jobs = jobs
        self.interval = interval
        self.maximum_per_tick = maximum_per_tick
        self._running = False
        self._main_thread_id: int | None = None
        # A bound-method lookup creates a new object; keep a stable timer identity.
        self._timer_callback = self._drain_timer

    @property
    def context(self) -> ToolContext:
        return ToolContext(
            state=self.state,
            permissions=self.permissions,
            registry=self.registry,
            checkpoints=self.checkpoints,
            evidence=self.evidence,
            jobs=self.jobs,
        )

    def start(self) -> None:
        bpy = require_blender()
        self._main_thread_id = threading.get_ident()
        self._running = True
        if not bpy.app.timers.is_registered(self._timer_callback):
            bpy.app.timers.register(self._timer_callback, first_interval=self.interval, persistent=True)

    def stop(self) -> None:
        if self.jobs is not None:
            self.jobs.cancel_all("executor stopped")
        self._running = False
        try:
            bpy = require_blender()
            if bpy.app.timers.is_registered(self._timer_callback):
                bpy.app.timers.unregister(self._timer_callback)
        except (BridgeError, ValueError, RuntimeError):
            pass
        self.command_queue.cancel_all(
            BridgeError(ErrorCode.SERVER_ERROR, "Blender bridge executor stopped before execution.")
        )

    def submit(self, request: Request, *, timeout: float) -> QueuedRequest:
        """Enqueue from a networking thread; never call Blender here."""

        return self.command_queue.submit(request, timeout=timeout)

    def dispatch(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        allow_recovery: bool = False,
    ) -> Any:
        """Synchronous entry point for Blender-main-thread tests and operators."""

        if self._main_thread_id is not None and threading.get_ident() != self._main_thread_id:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Direct dispatch is restricted to Blender's main thread.",
            )
        request = Request(
            id=f"direct_{uuid.uuid4().hex[:10]}",
            method=method,
            params=dict(params or {}),
            protocol_version=PROTOCOL_VERSION,
        )
        return self._invoke(request, allow_recovery=allow_recovery)

    def execute_request(
        self, request: Request, *, check_cancelled: Callable[[], None] | None = None
    ) -> Response:
        """Execute one validated request and contain all failures."""

        try:
            try:
                result = self._invoke(request, check_cancelled=check_cancelled)
            except BridgeError as error:
                return Response.failure(request.id, error)
            return Response.success(request.id, result)
        except Exception:
            # Reporting/finalization itself can fail after the invocation has
            # unwound. Do not invoke providers, history or native work again.
            LOGGER.exception("Blender request outcome reporting failed for %s", request.method)
            # Fixed plain data avoids invoking the failing context/result
            # normalizer again. Normal wire encoding still uses the V1 envelope.
            return Response(id=request.id, ok=False, error={
                "code": ErrorCode.SERVER_ERROR.value,
                "message": "Blender request reporting failed; reinspect affected state.",
                "context": {"error_reporting_failed": True, "execution_outcome_unknown": True,
                            "possible_mutation": True, "verification_required": True}})

    def _editor_recovery_metadata(self, *, finalize: bool = True, before_write: Callable[[], None] | None = None,
                                  after_read: Callable[[], None] | None = None,
                                  after_native_push: Callable[[], None] | None = None) -> Mapping[str, Any] | None:
        finish = getattr(self.checkpoints, "finish_editor_session", None)
        result = (finish(before_write=before_write, after_read=after_read, after_native_push=after_native_push) if before_write is not None else finish()) if finalize and callable(finish) else None
        if result is not None:
            return result
        status = getattr(self.checkpoints, "editor_session_status", None)
        return status() if callable(status) else None

    def _invoke(
        self, request: Request, *, allow_recovery: bool = False,
        check_cancelled: Callable[[], None] | None = None,
    ) -> Any:
        context = self.context
        try:
            spec = self.registry.get(request.method)
        except BridgeError:
            # Preserve the existing unknown-method error/history path. A
            # callback cannot erase an exclusive parent's execution display.
            return self._invoke_owned(request, allow_recovery=allow_recovery, check_cancelled=check_cancelled,
                                      _context=context, _permit=None,
                                      preserve_execution=self.registry.active_exclusive_mutation)
        preserve_execution = self.registry.active_exclusive_mutation and not spec.modifies
        # Reject new reentrant writers before begin_execution, admission
        # factories, permission providers or checkpoint bookkeeping.
        with self.registry.mutation_entry(spec, request.params, context) as permit:
            return self._invoke_owned(request, allow_recovery=allow_recovery, check_cancelled=check_cancelled,
                                      _context=context, _permit=permit, preserve_execution=preserve_execution)

    def _invoke_owned(
        self, request: Request, *, allow_recovery: bool,
        check_cancelled: Callable[[], None] | None,
        _context: ToolContext, _permit: InvocationPermit | None,
        preserve_execution: bool = False,
    ) -> Any:
        start = time.perf_counter()
        task = request.params.get("_task", request.params.get("task_description"))
        if task is not None and not isinstance(task, str):
            task = None
        if not preserve_execution:
            self.state.begin_execution(request.method, task)
        spec = None
        undo_boundary = False
        undo_finalized = False
        undo_group = None
        handler_entered = False
        handler_completed = False
        admission_scope = None
        completion_scope = None
        checkpoint_native_push = None
        admission = None
        checkpoint_finalization_attempted = False
        editor_finalization_attempted = False
        owns_finalization = False
        finalization_token = None
        context = _context
        audit = self.registry._mutation_interlock.audit_for(_permit)
        context.check_cancelled = check_cancelled
        context.request_lifecycle = request._lifecycle
        context.request_id = request.id
        step_entry = None
        queued_owner = getattr(check_cancelled, "__self__", None)
        history_attempted = False
        history_failed = False
        history_record = None

        def record_history(*, failure: BridgeError | None = None, **details: Any) -> Any:
            nonlocal history_attempted, history_failed, history_record
            if not history_attempted:
                # A writer may append before raising. Retrying could duplicate
                # that unknown outcome, including from the exception path.
                history_attempted = True
                try:
                    history_record = self.state.record_operation(**details)
                except Exception:
                    history_failed = True
                    if failure is None:
                        raise
                    LOGGER.exception("Operation history recording failed for %s", request.method)
            if failure is not None and history_failed:
                failure.context.update(history_recording_failed=True, history_record_verified=False,
                                       history_outcome_unknown=True, history_retry_attempted=False)
            return history_record

        if isinstance(queued_owner, QueuedRequest) and getattr(check_cancelled, "__func__", None) is QueuedRequest.check_active:
            # Bind the known class implementation, not an arbitrary callback or
            # an overridden method that could invoke permission providers.
            context.check_final_request = lambda: QueuedRequest.check_active(queued_owner)

        def checkpoint_write_gate() -> None:
            if admission is not None:
                admission()
            check_final_mutation(context, request.method, allow_recovery=allow_recovery)

        def checkpoint_after_read() -> None:
            if admission is not None:
                admission.check_after_read()
            check_final_mutation(context, request.method, allow_recovery=allow_recovery)

        def finalization_owned() -> bool:
            # Retained trusted ToolSpec/request classification, never a mutable
            # context slot deciding whether legacy native writes are allowed.
            return owns_finalization

        def check_finalization_owner() -> None:
            if owns_finalization and (finalization_token is None or getattr(context, "checkpoint_finalization_owner", None) is not finalization_token
                                      or getattr(context, "checkpoint_call_id", None) is not finalization_token):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The guarded workflow lost its checkpoint finalization owner; legacy finalization remains disabled.",
                                  {"checkpoint_finalization_owner_valid": False, "verification_required": True})

        def retain_finalization_denial(primary: BridgeError, secondary: BridgeError) -> None:
            primary.context["checkpoint_finalization_refused"] = {"code": secondary.code,
                "bookkeeping": secondary.context.get("checkpoint_bookkeeping"), "primary_error_preserved": True}
            if secondary.context.get("execution_started"):
                primary.context.update(checkpoint_bookkeeping_changed=True, execution_started=True,
                                       possible_mutation=True, verification_required=True)

        try:
            step_entry = capture_call(context, request)
            entry = self.registry.checkpoint_parameter_entry(self.registry.get(request.method), request.params)
            owns_finalization = entry[0].checkpoint_owns_finalization and entry[1]
            self.registry.check_admission_entry(entry[0], context, allow_recovery=allow_recovery)
            scope, captured, deferred = self.registry._capture_admission(entry[0], request.params, context)
            if captured:
                admission_scope = scope
                admission = context.checkpoint_admission
                finalization_token = context.checkpoint_call_id
                if admission is not None:
                    completion_scope = self.registry.native_push_completion(
                        _permit, admission, self.checkpoints,
                        final_check=lambda: check_final_mutation(context, request.method, allow_recovery=allow_recovery))
                    checkpoint_native_push = completion_scope.__enter__()
            if check_cancelled is not None:
                check_cancelled()
            spec = self.registry.prepare_call(
                request.method,
                request.params,
                context,
                allow_recovery=allow_recovery,
            )
            self.registry.check_checkpoint_parameter_entry(entry, request.params)
            if deferred is not None:
                raise deferred
            if spec.modifies and spec.automatic_checkpoint:
                # Providers/scope resolution can outlive the caller. Check the
                # canonical lifetime before writing even an undo marker.
                checkpoint_write_gate()
                undo_boundary = self.checkpoints.before_modification(
                    request.method, before_write=checkpoint_write_gate, after_read=checkpoint_after_read,
                    after_native_push=checkpoint_native_push if admission is not None else None)
            if check_cancelled is not None:
                check_cancelled()
            if get_task_plans(context.state).protection is not None:
                # A checkpoint/cancellation callback can change policy, context
                # or consumers. Re-resolve after it, before handler entry.
                spec = self.registry.prepare_call(request.method, request.params, context, allow_recovery=allow_recovery)
            if admission is not None:
                # A callback after BEFORE must never turn this same call into
                # a fresh factory baseline in registry.invoke.
                admission.check_identity(request.method)
            self.registry.check_checkpoint_parameter_entry(entry, request.params)
            entries_before = context.handler_entries
            try:
                result = self.registry.invoke(spec, request.params, context, allow_recovery=allow_recovery, _permit=_permit)
                handler_completed = True
            finally:
                handler_entered = context.handler_entries > entries_before
            check_finalization_owner()
            if spec.modifies and undo_boundary:
                checkpoint_finalization_attempted = True
                undo_finalized = bool(self.checkpoints.after_modification(request.method, before_write=checkpoint_write_gate, after_read=checkpoint_after_read, after_native_push=checkpoint_native_push)
                                      if admission is not None else self.checkpoints.after_modification(request.method))
            if spec.modifies:
                editor_finalization_attempted = not finalization_owned()
                undo_group = self._editor_recovery_metadata(finalize=not finalization_owned(),
                    before_write=checkpoint_write_gate if admission is not None else None,
                    after_read=checkpoint_after_read if admission is not None else None,
                    after_native_push=checkpoint_native_push if admission is not None else None)
                if undo_group is not None and undo_group["state"] == "finalized":
                    undo_finalized = True
            self.registry.check_mutation_owner(spec, context)
            duration_ms = (time.perf_counter() - start) * 1000.0
            record = record_history(
                tool=request.method,
                description=_history_description(
                    request,
                    outcome="completed",
                    metadata=result if isinstance(result, Mapping) else None,
                    fallback=f"Completed {request.method}",
                ),
                success=True,
                duration_ms=duration_ms,
                affected_objects=affected_objects_from_result(result),
                external_effects=bounded_external_effects(result.get("external_effects")) if isinstance(result, Mapping) else None,
                recovery_evidence=bounded_recovery_evidence(result.get("recovery_evidence")) if isinstance(result, Mapping) else None,
            ) if spec.record_history else None
            if spec.modifies and isinstance(result, Mapping):
                result = dict(result)
                operation = {"undo_boundary_created": undo_boundary, "undo_boundary_finalized": undo_finalized}
                if isinstance(result.get("operation"), Mapping):
                    operation.update(result["operation"])
                if undo_group is not None:
                    operation["undo_group"] = dict(undo_group)
                    if undo_group["state"] == "finalized":
                        operation["undo_boundary_finalized"] = True
                operation["operation_id"] = record.operation_id if record else None
                result["operation"] = operation
            receipt_id = record_terminal(context, request, record, result, entry=step_entry, modifying=spec.modifies,
                handler_entered=handler_entered, undo_created=undo_boundary, undo_finalized=undo_finalized)
            if receipt_id is not None and isinstance(result, Mapping):
                result = {**result, "step_receipt_id": receipt_id}
            LOGGER.info("Completed %s in %.1f ms", request.method, duration_ms)
            if not preserve_execution:
                self.state.end_execution()
            return result
        except BridgeError as error:
            duration_ms = (time.perf_counter() - start) * 1000.0
            # The batch wrapper can enter while every child is rejected. Its
            # measured no-execution result does not authorize finishing an old
            # editor session. The known blocked-save handler similarly reports
            # no native entry; unknown legacy writers remain conservative.
            finalize_writer = handler_entered and not (
                (request.method == "batch.execute" and error.context.get("execution_started") is False)
                or (request.method == "project.save" and error.context.get("execution_started") is False
                    and error.context.get("native_save_invoked") is False)
                or (spec is not None and spec.checkpoint_admission_factory is not None and error.context.get("execution_started") is False))
            finalize_writer = finalize_writer and not finalization_owned() and not editor_finalization_attempted
            execution_started = bool(error.context.get("execution_started"))
            if handler_entered and spec is not None and spec.modifies and spec.checkpoint_admission_factory is not None and error.context.get("execution_started") is not False:
                execution_started = True
                error.context.update(execution_started=True, possible_mutation=True, verification_required=True)
            if handler_completed and spec is not None and spec.modifies:
                execution_started = True
                error.context.update(execution_started=True, requested_edit_started=True, possible_mutation=True,
                                     verification_required=True, undo_boundary_created=undo_boundary,
                                     undo_boundary_finalized=undo_finalized)
            effects = bounded_external_effects(error.context.get("external_effects"))
            recovery = bounded_recovery_evidence(error.context.get("recovery_evidence"))
            if recovery is not None and (recovery.get("possible_mutation") or recovery.get("packed_payload_replaced")):
                execution_started = True
                error.context.update(execution_started=True, possible_mutation=True, verification_required=True)
            if effects is not None and (effects.get("file_published")
                    or effects.get("publication_outcome_unknown") or effects.get("publication_attempted")
                    or effects.get("retained_staging_path") or effects.get("artifacts")
                    or effects.get("render_result_replaced") or effects.get("render_result_replacement_possible")):
                # Scene preservation/native undo cannot reverse an external file
                # or establish that a publication attempt had no filesystem effect.
                execution_started = True
                error.context.update(execution_started=True, possible_mutation=True, verification_required=True)
            if spec is not None and spec.modifies and undo_boundary and handler_entered and finalize_writer and not checkpoint_finalization_attempted:
                # Handler errors may follow a partial edit, even if not explicitly annotated.
                execution_started = True
                error.context["execution_started"] = True
                error.context["verification_required"] = True
                checkpoint_finalization_attempted = True
                try:
                    label = f"{request.method} (failed; verify state)"
                    undo_finalized = bool(self.checkpoints.after_modification(label, before_write=checkpoint_write_gate, after_read=checkpoint_after_read, after_native_push=checkpoint_native_push)
                        if admission is not None else self.checkpoints.after_modification(label))
                    error.context["undo_boundary_finalized"] = undo_finalized
                except BridgeError as secondary:
                    retain_finalization_denial(error, secondary)
                    finalize_writer = False
            elif spec is not None and spec.modifies and undo_boundary and not handler_entered:
                # The requested writer never entered; an existing BEFORE
                # snapshot is evidence, not permission for a new AFTER write.
                error.context.update(undo_boundary_created=True, undo_boundary_finalized=False,
                                     requested_edit_started=False, checkpoint_bookkeeping_changed=True,
                                     execution_started=True, possible_mutation=True, verification_required=True)
                execution_started = True
            if spec is not None and spec.modifies:
                try:
                    editor_finalization_attempted = editor_finalization_attempted or finalize_writer
                    undo_group = self._editor_recovery_metadata(finalize=finalize_writer,
                        before_write=checkpoint_write_gate if admission is not None else None,
                        after_read=checkpoint_after_read if admission is not None else None,
                    after_native_push=checkpoint_native_push if admission is not None else None)
                except BridgeError as secondary:
                    retain_finalization_denial(error, secondary)
                    undo_group = self._editor_recovery_metadata(finalize=False)
                if undo_group is not None:
                    error.context["undo_group"] = dict(undo_group)
                    if undo_group["state"] == "finalized":
                        undo_finalized = True
                        execution_started = True
                        error.context.update({"execution_started": True, "verification_required": True,
                                              "undo_boundary_finalized": True})
            entry_effects = annotate_entry_error(error, audit)
            record = record_history(
                failure=error,
                tool=request.method,
                description=_history_description(
                    request,
                    outcome="failed; verify state" if execution_started else "rejected",
                    metadata=error.context,
                    fallback=error.message,
                ),
                success=False,
                duration_ms=duration_ms,
                affected_objects=_affected_objects_from_error(error),
                error_code=error.code,
                external_effects=effects,
                recovery_evidence=recovery,
                entry_effects=entry_effects,
            )
            receipt_id = record_terminal(context, request, record, error.context, entry=step_entry, modifying=bool(spec is not None and spec.modifies),
                handler_entered=handler_entered, undo_created=undo_boundary, undo_finalized=undo_finalized)
            if receipt_id is not None:
                error.context.update(step_receipt_id=receipt_id, operation_id=record.operation_id)
            if not preserve_execution:
                self.state.end_execution(error.message)
            if error.code == ErrorCode.PERMISSION_DENIED.value:
                LOGGER.warning("Permission denied for %s: %s", request.method, error.context)
            else:
                LOGGER.warning("Bridge tool %s failed: %s", request.method, error.message)
            raise
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            LOGGER.exception("Unhandled Blender tool failure in %s", request.method)
            finalization_denial = None
            if spec is not None and spec.modifies and undo_boundary and handler_entered and not checkpoint_finalization_attempted:
                checkpoint_finalization_attempted = True
                try:
                    label = f"{request.method} (failed; verify state)"
                    undo_finalized = bool(self.checkpoints.after_modification(label, before_write=checkpoint_write_gate, after_read=checkpoint_after_read, after_native_push=checkpoint_native_push)
                        if admission is not None else self.checkpoints.after_modification(label))
                except BridgeError as secondary:
                    finalization_denial = secondary
            if spec is not None and spec.modifies:
                try:
                    finalize_editor = handler_entered and finalization_denial is None and not finalization_owned() and not editor_finalization_attempted
                    editor_finalization_attempted = editor_finalization_attempted or finalize_editor
                    undo_group = self._editor_recovery_metadata(finalize=finalize_editor,
                        before_write=checkpoint_write_gate if admission is not None else None,
                        after_read=checkpoint_after_read if admission is not None else None,
                    after_native_push=checkpoint_native_push if admission is not None else None)
                except BridgeError as secondary:
                    finalization_denial = secondary
                    undo_group = self._editor_recovery_metadata(finalize=False)
                undo_finalized = undo_finalized or (undo_group is not None and undo_group["state"] == "finalized")
            error = BridgeError(
                ErrorCode.OPERATION_FAILED,
                f"Blender operation '{request.method}' failed.",
                {"exception_type": type(exc).__name__,
                 "detail": "Operation history recording failed." if history_failed else str(exc)[:400],
                 "execution_started": bool(spec is not None and spec.modifies and handler_entered),
                 "verification_required": True, "undo_boundary_finalized": undo_finalized},
            )
            if undo_group is not None:
                error.context["undo_group"] = dict(undo_group)
            if finalization_denial is not None:
                retain_finalization_denial(error, finalization_denial)
            entry_effects = annotate_entry_error(error, audit)
            record = record_history(
                failure=error,
                tool=request.method,
                description=error.message,
                success=False,
                duration_ms=duration_ms,
                error_code=error.code,
                entry_effects=entry_effects,
            )
            receipt_id = record_terminal(context, request, record, error.context, entry=step_entry, modifying=bool(spec is not None and spec.modifies),
                handler_entered=handler_entered, undo_created=undo_boundary, undo_finalized=undo_finalized)
            if receipt_id is not None:
                error.context.update(step_receipt_id=receipt_id, operation_id=record.operation_id)
            if not preserve_execution:
                self.state.end_execution(error.message)
            raise error from exc
        finally:
            try:
                if completion_scope is not None:
                    completion_scope.__exit__(None, None, None)
            finally:
                if admission_scope is not None:
                    admission_scope.__exit__(None, None, None)

    def _drain_timer(self) -> float | None:
        if not self._running:
            return None
        for _index in range(self.maximum_per_tick):
            queued = self.command_queue.pop_nowait()
            if queued is None:
                break
            try:
                if queued.try_start():
                    queued.resolve(self.execute_request(queued.request, check_cancelled=queued.check_active))
            finally:
                self.command_queue.task_done()
        if self.jobs is not None and self.jobs.active is not None:
            active = self.jobs.tick()
            # Refresh sidebar progress without forcing expensive 3D redraws or
            # reaching UI classes from the standalone MCP process/job manager.
            screen = getattr(require_blender().context, "screen", None)
            for area in getattr(screen, "areas", ()):
                if area.type == "VIEW_3D":
                    for region in area.regions:
                        if region.type == "UI":
                            region.tag_redraw()
            if active:
                return min(self.interval, 0.01)
        return self.interval
