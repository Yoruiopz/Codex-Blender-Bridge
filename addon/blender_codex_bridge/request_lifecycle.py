"""Thread-safe transport ownership flags; never access Blender or execute job work."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .errors import BridgeError, ErrorCode


@dataclass(slots=True)
class ConnectionLifetime:
    disconnected: threading.Event = field(default_factory=threading.Event)
    background_active: threading.Event = field(default_factory=threading.Event)


@dataclass(slots=True)
class RequestLifetime:
    connection: ConnectionLifetime | None = None
    deadline: float = float("inf")
    delivered: threading.Event = field(default_factory=threading.Event)
    rejected: threading.Event = field(default_factory=threading.Event)

    @classmethod
    def local(cls) -> RequestLifetime:
        result = cls()
        result.delivered.set()
        return result

    def acknowledge(self, success: bool) -> None:
        (self.delivered if success else self.rejected).set()

    def check(self) -> None:
        disconnected = self.connection is not None and self.connection.disconnected.is_set()
        expired = not self.delivered.is_set() and time.monotonic() >= self.deadline
        if disconnected or self.rejected.is_set() or expired:
            raise BridgeError(ErrorCode.TIMEOUT, "Job owner disconnected or its start handoff failed/expired.",
                              {"connection_disconnected": disconnected, "start_delivery_failed": self.rejected.is_set(),
                               "start_handoff_expired": expired})
