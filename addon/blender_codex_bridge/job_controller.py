"""Main-thread cooperative scheduling and controls, independent of job domains.

Domain adapters own authority checks, work creation, publication, cleanup and
terminal evidence. The controller has no Blender API or checkpoint dependency;
adapter hooks can enter native work that the slice budget cannot preempt.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument

LOGGER = logging.getLogger(__name__)
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


class CooperativeJobController:
    """One active owner with delivered-start gating and cooperative progress.

    Records supply lifecycle/control fields and summary(). Domain hooks retain
    their own permission, commit and terminal policies. _finish must retire the
    exact record only after its cleanup and terminal evidence are complete.
    """

    _logger = LOGGER
    _emergency_message = "Job emergency-stopped."
    _unexpected_failure_log = "Job failed outside its typed error path"
    _unexpected_failure_message = "Job failed; inspect its retained evidence."
    _lifecycle_cancel_message = "Job cancelled by bridge lifecycle."

    def __init__(self, context_factory, budget_ms=lambda: 4.):
        self.context_factory, self.budget_ms = context_factory, budget_ms
        self._main_thread = threading.get_ident()
        self.active: Any | None = None
        self.history: deque[Any] = deque(maxlen=32)

    def _main(self):
        if threading.get_ident() != self._main_thread:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Job control and execution require Blender's main thread.")

    def tick(self) -> bool:
        self._main()
        job = self.active
        if job is None:
            return False
        context = self._context(job)
        job.in_tick = True
        try:
            self._check(job, context)
            snapshot = context.state.snapshot()
            if snapshot["emergency_stopped"]:
                raise BridgeError(ErrorCode.EMERGENCY_STOPPED, self._emergency_message)
            if snapshot["paused"]:
                if job.state != "PAUSED":
                    job.state = "PAUSED"
                    job.revision += 1
                return True
            if not job.lifetime.delivered.is_set():
                return True
            context.registry.prepare(job.method, context)
            job.state = "RUNNING"
            if job.work is None:
                job.work = self._make_work(job, context)
            budget = self.budget_ms()
            budget = min(8., max(1., float(budget))) if isinstance(budget, (int, float)) and math.isfinite(budget) else 4.
            deadline = time.perf_counter() + budget / 1000
            while time.perf_counter() < deadline:
                self._check(job, context)
                flags = context.state.snapshot()
                if flags["paused"] and not flags["emergency_stopped"]:
                    job.state = "PAUSED"
                    job.revision += 1
                    return True
                context.registry.prepare(job.method, context)
                try:
                    job.progress = next(job.work)
                    job.revision += 1
                except StopIteration as completed:
                    self._complete_work(job, context, completed.value)
                    return False
        except BridgeError as error:
            cancelled = error.code in {ErrorCode.TIMEOUT.value, ErrorCode.EMERGENCY_STOPPED.value}
            self._finish(job, "CANCELLED" if cancelled else "FAILED", error)
        except Exception as error:
            self._logger.exception(self._unexpected_failure_log)
            self._finish(job, "FAILED", BridgeError(ErrorCode.OPERATION_FAILED, self._unexpected_failure_message,
                                                    {"exception_type": type(error).__name__}))
        finally:
            job.in_tick = False
        return self.active is not None

    def inspect(self, job_id: str) -> dict:
        self._main()
        for job in ([self.active] if self.active else []) + list(self.history):
            if job.job_id == job_id:
                return job.summary()
        raise invalid_argument("Job ID is missing or no longer retained in this bridge session.")

    def list(self, limit=10) -> dict:
        self._main()
        jobs = ([self.active] if self.active else []) + list(self.history)
        return {"jobs": [job.summary() for job in jobs[:limit]], "total": len(jobs), "truncated": len(jobs) > limit,
                "max_active": 1, "terminal_history_limit": 32, "durable": False}

    def status(self) -> dict:
        """Minimal control/status evidence, not an INSPECT_SCENE bypass."""
        self._main()
        def compact(job):
            return {key: value for key, value in job.summary().items()
                    if key in {"job_id", "kind", "state", "terminal", "revision", "progress"}}
        return {"active": compact(self.active) if self.active else None,
                "last_terminal": compact(self.history[0]) if self.history else None,
                "max_active": 1, "terminal_history_limit": 32, "durable": False}

    def cancel(self, job_id: str) -> dict:
        self._main()
        summary = self.inspect(job_id)
        if self.active is not None and self.active.job_id == job_id:
            self.active.cancel_reason = "explicit cancellation"
            self.active.state = "CANCELLING"
            self.active.revision += 1
            summary = self.active.summary()
        return {"cancel_requested": not summary["terminal"], "job_id": job_id,
                "state": summary["state"], "terminal": summary["terminal"],
                "verification_required": True}

    def cancel_all(self, reason: str):
        self._main()
        if self.active is not None:
            job = self.active
            job.cancel_reason = reason
            if job.in_tick or job.in_commit:
                # Native callbacks can re-enter stop/undo handlers. Do not release
                # buffers underneath publication; unwind at the next safe point.
                job.revision += 1
                return
            self._finish(job, "CANCELLED", BridgeError(ErrorCode.TIMEOUT, self._lifecycle_cancel_message, {"reason": reason}))

    def _retire(self, job: Any) -> None:
        self.history.appendleft(job)
        if self.active is job:
            self.active = None

    def _context(self, job: Any) -> Any:
        raise NotImplementedError

    def _check(self, job: Any, context: Any) -> None:
        raise NotImplementedError

    def _make_work(self, job: Any, context: Any) -> Any:
        raise NotImplementedError

    def _complete_work(self, job: Any, context: Any, value: Any) -> None:
        raise NotImplementedError

    def _finish(self, job: Any, state: str, error: BridgeError | None = None) -> None:
        raise NotImplementedError
