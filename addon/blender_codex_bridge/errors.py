"""Structured errors shared by the Blender transport and tool layer."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable machine-readable bridge error codes."""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_PROTOCOL_VERSION = "UNSUPPORTED_PROTOCOL_VERSION"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    MALFORMED_JSON = "MALFORMED_JSON"
    MESSAGE_TOO_LARGE = "MESSAGE_TOO_LARGE"
    METHOD_NOT_FOUND = "METHOD_NOT_FOUND"
    TOOLSET_DISABLED = "TOOLSET_DISABLED"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    MATERIAL_NOT_FOUND = "MATERIAL_NOT_FOUND"
    INVALID_MODE = "INVALID_MODE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_SELECTION = "INVALID_SELECTION"
    BLENDER_CONTEXT_ERROR = "BLENDER_CONTEXT_ERROR"
    OPERATION_FAILED = "OPERATION_FAILED"
    TIMEOUT = "TIMEOUT"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    AGENT_PAUSED = "AGENT_PAUSED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"
    SERVER_ERROR = "SERVER_ERROR"


class BridgeError(Exception):
    """An expected bridge failure safe to serialize to a client."""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code.value if isinstance(code, ErrorCode) else str(code)
        self.message = message
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.context:
            error["context"] = self.context
        return error


def invalid_argument(message: str, **context: Any) -> BridgeError:
    """Create a concise invalid-argument exception."""

    return BridgeError(ErrorCode.INVALID_ARGUMENT, message, context)
