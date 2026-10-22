"""Blender main-thread dispatcher driven by ``bpy.app.timers``."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from .checkpoints import CheckpointManager
from .command_queue import CommandQueue, QueuedRequest
from .errors import BridgeError, ErrorCode
from .permissions import PermissionManager
from .protocol import PROTOCOL_VERSION, Request, Response
from .scene_evidence import SceneEvidenceStore
from .state import BridgeState, bounded_external_effects, bounded_recovery_evidence
from .tool_registry import ToolContext, ToolRegistry
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
            return Response.success(request.id, self._invoke(request, check_cancelled=check_cancelled))
        except BridgeError as error:
            return Response.failure(request.id, error)

    def _editor_recovery_metadata(self) -> Mapping[str, Any] | None:
        finish = getattr(self.checkpoints, "finish_editor_session", None)
        result = finish() if callable(finish) else None
        if result is not None:
            return result
        status = getattr(self.checkpoints, "editor_session_status", None)
        return status() if callable(status) else None

    def _invoke(
        self, request: Request, *, allow_recovery: bool = False,
        check_cancelled: Callable[[], None] | None = None,
    ) -> Any:
        start = time.perf_counter()
        task = request.params.get("_task", request.params.get("task_description"))
        if task is not None and not isinstance(task, str):
            task = None
        self.state.begin_execution(request.method, task)
        spec = None
        undo_boundary = False
        undo_finalized = False
        undo_group = None
        context = self.context
        context.check_cancelled = check_cancelled
        context.request_lifecycle = request._lifecycle
        context.request_id = request.id
        try:
            if check_cancelled is not None:
                check_cancelled()
            spec = self.registry.prepare(
                request.method,
                context,
                allow_recovery=allow_recovery,
            )
            if spec.modifies and spec.automatic_checkpoint:
                undo_boundary = self.checkpoints.before_modification(request.method)
            if check_cancelled is not None:
                check_cancelled()
            result = spec.handler(context, request.params)
            if spec.modifies and undo_boundary:
                undo_finalized = bool(self.checkpoints.after_modification(request.method))
            if spec.modifies:
                undo_group = self._editor_recovery_metadata()
                if undo_group is not None and undo_group["state"] == "finalized":
                    undo_finalized = True
            duration_ms = (time.perf_counter() - start) * 1000.0
            record = self.state.record_operation(
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
            LOGGER.info("Completed %s in %.1f ms", request.method, duration_ms)
            self.state.end_execution()
            return result
        except BridgeError as error:
            duration_ms = (time.perf_counter() - start) * 1000.0
            execution_started = bool(error.context.get("execution_started"))
            effects = bounded_external_effects(error.context.get("external_effects"))
            recovery = bounded_recovery_evidence(error.context.get("recovery_evidence"))
            if recovery is not None and (recovery.get("possible_mutation") or recovery.get("packed_payload_replaced")):
                execution_started = True
                error.context.update(execution_started=True, possible_mutation=True, verification_required=True)
            if effects is not None and (effects.get("file_published")
                    or effects.get("publication_outcome_unknown") or effects.get("publication_attempted")
                    or effects.get("retained_staging_path") or effects.get("artifacts")
                    or effects.get("render_result_replaced")):
                # Scene preservation/native undo cannot reverse an external file
                # or establish that a publication attempt had no filesystem effect.
                execution_started = True
                error.context.update(execution_started=True, possible_mutation=True, verification_required=True)
            if spec is not None and spec.modifies and undo_boundary:
                # Handler errors may follow a partial edit, even if not explicitly annotated.
                execution_started = True
                error.context["execution_started"] = True
                error.context["verification_required"] = True
                error.context["undo_boundary_finalized"] = bool(
                    self.checkpoints.after_modification(f"{request.method} (failed; verify state)")
                )
            if spec is not None and spec.modifies:
                undo_group = self._editor_recovery_metadata()
                if undo_group is not None:
                    error.context["undo_group"] = dict(undo_group)
                    if undo_group["state"] == "finalized":
                        execution_started = True
                        error.context.update({"execution_started": True, "verification_required": True,
                                              "undo_boundary_finalized": True})
            self.state.record_operation(
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
            )
            self.state.end_execution(error.message)
            if error.code == ErrorCode.PERMISSION_DENIED.value:
                LOGGER.warning("Permission denied for %s: %s", request.method, error.context)
            else:
                LOGGER.warning("Bridge tool %s failed: %s", request.method, error.message)
            raise
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            LOGGER.exception("Unhandled Blender tool failure in %s", request.method)
            if spec is not None and spec.modifies and undo_boundary:
                undo_finalized = bool(self.checkpoints.after_modification(f"{request.method} (failed; verify state)"))
            if spec is not None and spec.modifies:
                undo_group = self._editor_recovery_metadata()
                undo_finalized = undo_finalized or (undo_group is not None and undo_group["state"] == "finalized")
            error = BridgeError(
                ErrorCode.OPERATION_FAILED,
                f"Blender operation '{request.method}' failed.",
                {"exception_type": type(exc).__name__, "detail": str(exc)[:400],
                 "execution_started": bool(spec is not None and spec.modifies),
                 "verification_required": True, "undo_boundary_finalized": undo_finalized},
            )
            if undo_group is not None:
                error.context["undo_group"] = dict(undo_group)
            self.state.record_operation(
                tool=request.method,
                description=error.message,
                success=False,
                duration_ms=duration_ms,
                error_code=error.code,
            )
            self.state.end_execution(error.message)
            raise error from exc

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
