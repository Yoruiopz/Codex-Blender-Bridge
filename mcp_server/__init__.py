"""Blender Codex Bridge MCP package.

Importing this package does not require the optional MCP SDK. The SDK is loaded
only by :func:`create_server`, :func:`build_runtime`, or the CLI startup path.
"""

from __future__ import annotations

from .blender_client import AsyncBlenderClient, BlenderClient, SyncBlenderClient
from .errors import (
    BridgeConnectionError,
    BridgeError,
    BridgeProtocolError,
    BridgeTimeoutError,
    MCPDependencyError,
    ToolsetDisabledError,
)
from .schemas import PROTOCOL_VERSION, BridgeRequest, BridgeResponse, ErrorPayload
from .server import build_runtime, create_mcp_server, create_server
from .tool_registry import ToolDefinition, ToolRegistry, create_default_registry

__version__ = "0.2.0"

__all__ = [
    "PROTOCOL_VERSION",
    "AsyncBlenderClient",
    "BlenderClient",
    "BridgeConnectionError",
    "BridgeError",
    "BridgeProtocolError",
    "BridgeRequest",
    "BridgeResponse",
    "BridgeTimeoutError",
    "ErrorPayload",
    "MCPDependencyError",
    "SyncBlenderClient",
    "ToolDefinition",
    "ToolRegistry",
    "ToolsetDisabledError",
    "build_runtime",
    "create_default_registry",
    "create_mcp_server",
    "create_server",
]
