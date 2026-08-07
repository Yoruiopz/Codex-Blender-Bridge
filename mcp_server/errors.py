"""Structured exceptions shared by the MCP server and Blender transport client."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class BridgeError(Exception):
    """An error returned by Blender, preserving its machine-readable details."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = str(code or "OPERATION_FAILED")
        self.message = str(message or "Blender bridge operation failed")
        self.context = dict(context or {})
        self.request_id = request_id
        self.retryable = bool(retryable)
        super().__init__(self.message)

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], *, request_id: str | None = None
    ) -> BridgeError:
        """Build an exception from a protocol ``error`` object."""

        code = payload.get("code", "OPERATION_FAILED")
        message = payload.get("message", "Blender bridge operation failed")
        context = payload.get("context")
        if context is None:
            context = {}
        elif not isinstance(context, Mapping):
            context = {"details": context}
        retryable = payload.get("retryable", False)
        return cls(
            str(code),
            str(message),
            context=context,
            request_id=request_id,
            retryable=retryable if isinstance(retryable, bool) else False,
        )

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "context": self.context,
            "retryable": self.retryable,
        }
        if self.request_id is not None:
            error["request_id"] = self.request_id
        return error

    def __str__(self) -> str:
        # MCP SDKs normally surface exception text to the client. JSON keeps the
        # structured Blender error useful even through that compatibility path.
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class BridgeConnectionError(BridgeError):
    """The local Blender listener could not be reached or disconnected."""

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            "CONNECTION_ERROR",
            message,
            context=context,
            request_id=request_id,
            retryable=retryable,
        )


class BridgeTimeoutError(BridgeError):
    """A connection or operation exceeded its configured deadline."""

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            "TIMEOUT",
            message,
            context=context,
            request_id=request_id,
            retryable=retryable,
        )


class BridgeProtocolError(BridgeError):
    """The peer sent data that does not satisfy protocol version 1.0."""

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            "PROTOCOL_ERROR",
            message,
            context=context,
            request_id=request_id,
            retryable=False,
        )


class ToolsetDisabledError(BridgeError):
    """A statically advertised domain tool was called while locally disabled."""

    def __init__(self, tool: str, toolset: str) -> None:
        super().__init__(
            "TOOLSET_DISABLED",
            f"Tool '{tool}' requires the local MCP toolset '{toolset}' to be enabled.",
            context={
                "tool": tool,
                "toolset": toolset,
                "hint": f"Call toolsets.enable with name='{toolset}'.",
            },
        )


class MCPDependencyError(RuntimeError):
    """Raised at server startup when the optional official MCP SDK is absent."""
