"""Blender main-thread dispatcher driven by ``bpy.app.timers``."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Any

from .checkpoints import CheckpointManager
from .command_queue import CommandQueue, QueuedRequest
from .errors import BridgeError, ErrorCode
from .permissions import PermissionManager
from .protocol import PROTOCOL_VERSION, Request, Response
from .state import BridgeState
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
    if request.method != "python.execute":
        return fallback
    effect = request.params.get("expected_effect")
    effect_text = effect.strip() if isinstance(effect, str) and effect.strip() else "unspecified effect"
    digest = metadata.get("script_digest") if metadata is not None else None
    digest_text = digest if isinstance(digest, str) and digest else "unvalidated"
    return f"Python {outcome} [{digest_text}]: {effect_text}"


def _affected_objects_from_error(error: BridgeError) -> tuple[str, ...]:
    names: list[str] = []
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
    ) -> None:
        self.command_queue = command_queue
        self.registry = registry
        self.state = state
        self.permissions = permissions
        self.checkpoints = checkpoints
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
        )

    def start(self) -> None:
        bpy = require_blender()
        self._main_thread_id = threading.get_ident()
        self._running = True
        if not bpy.app.timers.is_registered(self._timer_callback):
            bpy.app.timers.register(self._timer_callback, first_interval=self.interval, persistent=True)

    def stop(self) -> None:
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

    def execute_request(self, request: Request) -> Response:
        """Execute one validated request and contain all failures."""

        try:
            return Response.success(request.id, self._invoke(request))
        except BridgeError as error:
            return Response.failure(request.id, error)

    def _invoke(self, request: Request, *, allow_recovery: bool = False) -> Any:
        start = time.perf_counter()
        task = request.params.get("_task", request.params.get("task_description"))
        if task is not None and not isinstance(task, str):
            task = None
        self.state.begin_execution(request.method, task)
        spec = None
        undo_boundary = False
        try:
            spec = self.registry.prepare(
                request.method,
                self.context,
                allow_recovery=allow_recovery,
            )
            if spec.modifies and spec.automatic_checkpoint:
                undo_boundary = self.checkpoints.before_modification(request.method)
            result = spec.handler(self.context, request.params)
            if spec.modifies and undo_boundary:
                self.checkpoints.after_modification(request.method)
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
            )
            if spec.modifies and isinstance(result, Mapping):
                result = dict(result)
                result["operation"] = {
                    "operation_id": record.operation_id,
                    "undo_boundary_created": undo_boundary,
                }
            LOGGER.info("Completed %s in %.1f ms", request.method, duration_ms)
            self.state.end_execution()
            return result
        except BridgeError as error:
            duration_ms = (time.perf_counter() - start) * 1000.0
            execution_started = bool(error.context.get("execution_started"))
            if spec is not None and spec.modifies and undo_boundary and execution_started:
                self.checkpoints.after_modification(f"{request.method} (failed; verify state)")
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
            error = BridgeError(
                ErrorCode.OPERATION_FAILED,
                f"Blender operation '{request.method}' failed.",
                {"exception_type": type(exc).__name__, "detail": str(exc)[:400]},
            )
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
                    queued.resolve(self.execute_request(queued.request))
            finally:
                self.command_queue.task_done()
        return self.interval
