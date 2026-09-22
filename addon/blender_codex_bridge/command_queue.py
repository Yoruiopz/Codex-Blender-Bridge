"""Thread-safe handoff from socket workers to Blender's main thread."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

from .errors import BridgeError, ErrorCode
from .protocol import Request, Response


@dataclass(slots=True)
class QueuedRequest:
    request: Request
    deadline: float = field(default_factory=lambda: time.monotonic() + 30.0)
    completed: threading.Event = field(default_factory=threading.Event)
    response: Response | None = None
    _state: str = "pending"
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop_requested: bool = False

    def resolve(self, response: Response) -> None:
        with self._lock:
            if self._state in {"completed", "cancelled"}:
                return
            self.response = response
            self._state = "completed"
            self.completed.set()

    def try_start(self) -> bool:
        """Atomically claim a pending request unless its deadline passed."""

        with self._lock:
            if self._state != "pending":
                return False
            if time.monotonic() >= self.deadline:
                error = BridgeError(
                    ErrorCode.TIMEOUT,
                    "Request expired before Blender began executing it.",
                    {"method": self.request.method, "executed": False},
                )
                self.response = Response.failure(self.request.id, error)
                self._state = "cancelled"
                self.completed.set()
                return False
            self._state = "running"
            return True

    def cancel_pending(self, error: BridgeError) -> bool:
        """Cancel only if Blender has not begun execution."""

        with self._lock:
            # A running tool cannot be interrupted, but cooperative tools must
            # not begin another action after their caller has gone away.
            self._stop_requested = True
            if self._state != "pending":
                return False
            self.response = Response.failure(self.request.id, error)
            self._state = "cancelled"
            self.completed.set()
            return True

    def check_active(self) -> None:
        """Safe-point check; never attempt to interrupt a Blender C operation."""

        with self._lock:
            cancelled = self._stop_requested
            expired = time.monotonic() >= self.deadline
        if cancelled or expired:
            raise BridgeError(
                ErrorCode.TIMEOUT,
                "Request stopped at a cooperative execution boundary; reinspect prior changes.",
                {"cancellation_requested": cancelled, "deadline_expired": expired},
            )

    def wait(self, timeout: float, *, running_grace: float = 300.0) -> Response:
        if not self.completed.wait(timeout):
            timeout_error = BridgeError(
                ErrorCode.TIMEOUT,
                "Request timed out before Blender began executing it.",
                {"timeout_seconds": timeout, "method": self.request.method, "executed": False},
            )
            if self.cancel_pending(timeout_error):
                raise timeout_error
            # It crossed the atomic running boundary before the timeout. Waiting
            # for the actual response avoids reporting a timeout followed by an
            # apparently mysterious late mutation.
            if not self.completed.wait(running_grace):
                raise BridgeError(
                    ErrorCode.TIMEOUT,
                    "A Blender operation is still running; its final outcome is unknown.",
                    {
                        "method": self.request.method,
                        "execution_started": True,
                        "outcome_unknown": True,
                    },
                )
        if self.response is None:  # defensive: Event should only be set by resolve().
            raise BridgeError(ErrorCode.SERVER_ERROR, "Request completed without a response.")
        return self.response

    @property
    def state(self) -> str:
        with self._lock:
            return self._state


class CommandQueue:
    """A small FIFO with explicit completion futures."""

    def __init__(self, *, maximum_size: int = 256) -> None:
        self._queue: queue.Queue[QueuedRequest] = queue.Queue(maxsize=maximum_size)

    def submit(self, request: Request, *, timeout: float) -> QueuedRequest:
        queued = QueuedRequest(request, deadline=time.monotonic() + timeout)
        try:
            self._queue.put_nowait(queued)
        except queue.Full as exc:
            raise BridgeError(
                ErrorCode.SERVER_ERROR,
                "Blender command queue is full.",
                {"maximum_size": self._queue.maxsize},
            ) from exc
        return queued

    def pop_nowait(self) -> QueuedRequest | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def task_done(self) -> None:
        self._queue.task_done()

    def cancel_all(self, error: BridgeError) -> int:
        count = 0
        while True:
            queued = self.pop_nowait()
            if queued is None:
                return count
            queued.cancel_pending(error)
            self.task_done()
            count += 1

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()
