"""Thread-safe runtime state and concise agent operation history."""

from __future__ import annotations

import threading
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    tool: str
    timestamp: str
    description: str
    success: bool
    duration_ms: float
    affected_objects: tuple[str, ...] = ()
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["affected_objects"] = list(self.affected_objects)
        return value


class BridgeState:
    """Mutable runtime state protected for network/UI access."""

    def __init__(self, *, history_limit: int = 50) -> None:
        self._lock = threading.RLock()
        self._history: deque[OperationRecord] = deque(maxlen=history_limit)
        self.server_running = False
        self.host = "127.0.0.1"
        self.port = 9876
        self.connected_clients = 0
        self.paused = False
        self.emergency_stopped = False
        self.current_task = ""
        self.current_method = ""
        self.is_executing = False
        self.last_error = ""

    def set_server(self, running: bool, host: str | None = None, port: int | None = None) -> None:
        with self._lock:
            self.server_running = running
            if host is not None:
                self.host = host
            if port is not None:
                self.port = port
            if not running:
                self.connected_clients = 0

    def client_connected(self) -> None:
        with self._lock:
            self.connected_clients += 1

    def client_disconnected(self) -> None:
        with self._lock:
            self.connected_clients = max(0, self.connected_clients - 1)

    def begin_execution(self, method: str, task: str | None = None) -> None:
        with self._lock:
            self.current_method = method
            self.is_executing = True
            if task is not None:
                self.current_task = task[:500]

    def end_execution(self, error: str = "") -> None:
        with self._lock:
            self.current_method = ""
            self.is_executing = False
            self.last_error = error[:500]

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self.paused = bool(paused)

    def set_emergency_stopped(self, stopped: bool) -> None:
        with self._lock:
            self.emergency_stopped = bool(stopped)
            if stopped:
                self.paused = True
                self.current_method = ""
                self.is_executing = False

    def set_task(self, description: str) -> None:
        with self._lock:
            self.current_task = description[:500]

    def record_operation(
        self,
        *,
        tool: str,
        description: str,
        success: bool,
        duration_ms: float,
        affected_objects: Iterable[str] = (),
        error_code: str | None = None,
    ) -> OperationRecord:
        record = OperationRecord(
            operation_id=f"op_{uuid.uuid4().hex[:10]}",
            tool=tool,
            timestamp=_now(),
            description=description[:240],
            success=success,
            duration_ms=round(duration_ms, 3),
            affected_objects=tuple(dict.fromkeys(str(name) for name in affected_objects if name)),
            error_code=error_code,
        )
        with self._lock:
            self._history.appendleft(record)
        return record

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [record.to_dict() for record in list(self._history)[: max(0, limit)]]

    def clear_history(self) -> int:
        """Clear the local audit display and return the removed record count."""

        with self._lock:
            count = len(self._history)
            self._history.clear()
            return count

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self.connected_clients:
                connection_status = "connected"
            elif self.server_running:
                connection_status = "listening"
            else:
                connection_status = "disconnected"
            return {
                "server_running": self.server_running,
                "connection_status": connection_status,
                "host": self.host,
                "port": self.port,
                "connected_clients": self.connected_clients,
                "paused": self.paused,
                "emergency_stopped": self.emergency_stopped,
                "current_task": self.current_task,
                "current_method": self.current_method,
                "is_executing": self.is_executing,
                "last_error": self.last_error,
            }

    def reset(self) -> None:
        with self._lock:
            self.server_running = False
            self.connected_clients = 0
            self.paused = False
            self.emergency_stopped = False
            self.current_task = ""
            self.current_method = ""
            self.is_executing = False
            self.last_error = ""
            self._history.clear()


_STATE = BridgeState()


def get_state() -> BridgeState:
    return _STATE
