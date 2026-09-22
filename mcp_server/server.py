"""Official MCP SDK integration and command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import logging
import os
import sys
from collections.abc import Awaitable
from dataclasses import dataclass
from functools import wraps
from typing import Any, cast, get_type_hints

from .blender_client import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HOST,
    DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    BlenderClient,
    validate_loopback_host,
)
from .errors import BridgeError, MCPDependencyError
from .tool_registry import ToolRegistry, create_default_registry
from .tools import iter_bindings
from .tools.catalog import DESTRUCTIVE_TOOL_NAMES, MODIFYING_TOOL_NAMES

LOGGER = logging.getLogger(__name__)
SERVER_NAME = "Blender Codex Bridge"
SERVER_INSTRUCTIONS = (
    "Begin live Blender work with bridge.status, show the high-level task with "
    "bridge.task.set, and enable only the structured toolsets the task needs. "
    "Inspect explicit objects, selections, and datablocks before acting. Create one "
    "checkpoint before each meaningful edit, prefer structured tools, and use "
    "python.execute only as an explicitly acknowledged last resort. Verify every "
    "change structurally and capture the viewport when appearance, pose, UVs, "
    "lighting, or composition matters. Blender-side permissions are authoritative. "
    "Delete, write external files, render, execute Python, or save only when requested "
    "and permitted. Never infer measurements from images when Blender can report them. "
    "Clear the task when finished and report changed datablocks, verification, and save state."
    " Use scene.query and paginated mesh.components_inspect to resolve targets. "
    "Prefer object.transform_batch for independent bulk placement; use batch.execute "
    "for short sequences with known explicit names. Enable every child toolset first. "
    "Batch preflight checks gates, not scene dependencies; partial failures are not rolled back. "
    "Reinspect partial work, truncated results, and topology changes before continuing. "
    "Use geometry_nodes tools for procedural graphs and acknowledge shared users explicitly."
)


@dataclass(slots=True)
class MCPRuntime:
    """References useful to embedders and unit tests."""

    server: Any
    client: BlenderClient
    registry: ToolRegistry


def _load_server_class() -> type[Any]:
    """Prefer the official v2 API, with a narrow v1 compatibility fallback."""

    errors: list[str] = []
    try:
        module = importlib.import_module("mcp.server")
        server_class = module.MCPServer
        return cast(type[Any], server_class)
    except (ImportError, AttributeError) as exc:
        errors.append(str(exc))
    try:
        module = importlib.import_module("mcp.server.fastmcp")
        server_class = module.FastMCP
        LOGGER.warning(
            "Using legacy MCP SDK FastMCP compatibility; upgrade to mcp>=2,<3."
        )
        return cast(type[Any], server_class)
    except (ImportError, AttributeError) as exc:
        errors.append(str(exc))
    raise MCPDependencyError(
        "The optional official MCP Python SDK is required to start the server. "
        "Install it with: pip install 'mcp>=2,<3'. "
        f"Import details: {'; '.join(errors)}"
    )


def _accepted_kwargs(callable_object: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Filter optional compatibility kwargs without hiding runtime errors."""

    try:
        signature = inspect.signature(callable_object)
    except (TypeError, ValueError):
        return values
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return values
    return {key: value for key, value in values.items() if key in signature.parameters}


def _tool_annotations(*, modifying: bool, destructive: bool) -> Any | None:
    """Build official MCP safety hints without importing the SDK at package import."""

    try:
        module = importlib.import_module("mcp.types")
        annotations_class = module.ToolAnnotations
    except (ImportError, AttributeError):
        return None
    return annotations_class(
        read_only_hint=not modifying,
        destructive_hint=destructive,
        idempotent_hint=None,
        open_world_hint=False,
    )


def _register_tool(server: Any, *, name: str, handler: Any, description: str) -> None:
    registrar = getattr(server, "tool", None)
    if not callable(registrar):
        raise MCPDependencyError(
            "Installed MCP SDK does not provide the expected @server.tool API. "
            "Install a supported mcp>=2,<3 release."
        )
    annotations = _tool_annotations(
        modifying=name in MODIFYING_TOOL_NAMES,
        destructive=name in DESTRUCTIVE_TOOL_NAMES,
    )
    decorator_kwargs = _accepted_kwargs(
        registrar,
        {"name": name, "description": description, "annotations": annotations},
    )
    decorator = registrar(**decorator_kwargs)

    @wraps(handler)
    async def safe_handler(*args: Any, **kwargs: Any) -> Any:
        try:
            return await handler(*args, **kwargs)
        except BridgeError as exc:
            error_text = str(exc)
        except Exception:
            LOGGER.exception("Unexpected MCP tool failure in %s", name)
            error_text = str(BridgeError("OPERATION_FAILED", "Unexpected tool failure; inspect local diagnostics."))
        # SDK 2.2 intentionally redacts unexpected exception text. Explicit MCP
        # error results preserve our safe machine-readable envelope on all 2.x.
        types = importlib.import_module("mcp.types")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=error_text)], isError=True
        )

    # Resolve postponed annotations in the ORIGINAL function's namespace (some
    # wrappers use domain TypedDicts), retaining precise tool input schemas.
    hints = get_type_hints(handler)
    signature = inspect.signature(handler)
    safe_handler.__annotations__ = hints
    cast(Any, safe_handler).__signature__ = signature.replace(
        parameters=[parameter.replace(annotation=hints.get(key, parameter.annotation))
                    for key, parameter in signature.parameters.items()],
        return_annotation=hints.get("return", signature.return_annotation),
    )
    decorator(safe_handler)


def build_runtime(
    *,
    client: BlenderClient | None = None,
    registry: ToolRegistry | None = None,
    server_name: str = SERVER_NAME,
    mcp_host: str = DEFAULT_HOST,
    mcp_port: int = 8000,
    server_class: type[Any] | None = None,
) -> MCPRuntime:
    """Build and register an MCP server without connecting to Blender yet."""

    safe_mcp_host = validate_loopback_host(mcp_host)
    if isinstance(mcp_port, bool) or not isinstance(mcp_port, int) or not 1 <= mcp_port <= 65535:
        raise ValueError("mcp_port must be an integer from 1 to 65535")
    if registry is not None and client is not None and registry.client is not client:
        raise ValueError("registry and client refer to different Blender clients")
    if registry is None:
        active_client = client or BlenderClient()
        active_registry = create_default_registry(active_client)
    else:
        active_registry = registry
        active_client = client or registry.client  # type: ignore[assignment]
    sdk_class = server_class or _load_server_class()
    constructor_kwargs = _accepted_kwargs(
        sdk_class,
        {
            "host": safe_mcp_host,
            "port": mcp_port,
            "instructions": SERVER_INSTRUCTIONS,
        },
    )
    mcp_server = sdk_class(server_name, **constructor_kwargs)
    seen: set[str] = set()
    for binding in iter_bindings(active_registry):
        if binding.name in seen:
            raise RuntimeError(f"Duplicate MCP wrapper name {binding.name!r}")
        seen.add(binding.name)
        _register_tool(
            mcp_server,
            name=binding.name,
            handler=binding.handler,
            description=binding.description,
        )
    return MCPRuntime(
        server=mcp_server,
        client=active_client,
        registry=active_registry,
    )


def create_server(**kwargs: Any) -> Any:
    """Return the configured official MCP server instance."""

    return build_runtime(**kwargs).server


create_mcp_server = create_server


def _env(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    return fallback if value is None or not value.strip() else value.strip()


def _env_int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc


def _env_float(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blender-codex-mcp",
        description="Run the local MCP server for the Blender Codex Bridge add-on.",
    )
    parser.add_argument(
        "--blender-host",
        default=_env("BLENDER_CODEX_BRIDGE_HOST", DEFAULT_HOST),
        help="Blender listener host (loopback only; default: 127.0.0.1).",
    )
    parser.add_argument(
        "--blender-port",
        type=int,
        default=_env_int("BLENDER_CODEX_BRIDGE_PORT", DEFAULT_PORT),
        help="Blender listener TCP port (default: 9876).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_env_float("BLENDER_CODEX_BRIDGE_TIMEOUT", DEFAULT_TIMEOUT),
        help="Per-operation timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=_env_float(
            "BLENDER_CODEX_BRIDGE_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT
        ),
        help="TCP connection timeout in seconds (default: 5).",
    )
    parser.add_argument(
        "--max-message-bytes",
        type=int,
        default=_env_int(
            "BLENDER_CODEX_BRIDGE_MAX_MESSAGE_BYTES", DEFAULT_MAX_MESSAGE_BYTES
        ),
        help="Maximum newline-delimited JSON frame size (default: 4194304).",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default=_env("BLENDER_CODEX_MCP_TRANSPORT", "stdio"),
        help="MCP client transport (default: stdio).",
    )
    parser.add_argument(
        "--mcp-host",
        default=_env("BLENDER_CODEX_MCP_HOST", DEFAULT_HOST),
        help="MCP HTTP/SSE bind host (loopback only; default: 127.0.0.1).",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=_env_int("BLENDER_CODEX_MCP_PORT", 8000),
        help="MCP HTTP/SSE bind port (default: 8000).",
    )
    parser.add_argument(
        "--no-timestamps",
        action="store_true",
        help="Omit optional timestamps from Blender protocol requests.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=_env("BLENDER_CODEX_LOG_LEVEL", "WARNING").upper(),
    )
    return parser


def _run_sdk_server(server: Any, transport: str) -> None:
    run = getattr(server, "run", None)
    if callable(run):
        kwargs = _accepted_kwargs(run, {"transport": transport})
        result = run(**kwargs)
    else:
        method_name = {
            "stdio": "run_stdio",
            "streamable-http": "run_streamable_http",
            "sse": "run_sse",
        }[transport]
        runner = getattr(server, method_name, None)
        if not callable(runner):
            raise MCPDependencyError(
                f"Installed MCP SDK cannot run the requested {transport!r} transport."
            )
        result = runner()
    if inspect.isawaitable(result):
        asyncio.run(_await_sdk_result(result))


async def _await_sdk_result(result: Awaitable[Any]) -> Any:
    """Turn any SDK awaitable into a concrete coroutine for ``asyncio.run``."""

    return await result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by ``python -m mcp_server`` and console scripts."""

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        client = BlenderClient(
            host=args.blender_host,
            port=args.blender_port,
            timeout=args.timeout,
            connect_timeout=args.connect_timeout,
            max_message_bytes=args.max_message_bytes,
            include_timestamps=not args.no_timestamps,
        )
        runtime = build_runtime(
            client=client,
            mcp_host=args.mcp_host,
            mcp_port=args.mcp_port,
        )
    except (ValueError, MCPDependencyError) as exc:
        parser.exit(2, f"error: {exc}\n")
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.info(
        "Starting %s via %s; Blender endpoint %s:%s",
        SERVER_NAME,
        args.transport,
        client.host,
        client.port,
    )
    try:
        _run_sdk_server(runtime.server, args.transport)
    except KeyboardInterrupt:
        LOGGER.info("MCP server stopped")
    return 0


__all__ = [
    "SERVER_INSTRUCTIONS",
    "SERVER_NAME",
    "MCPRuntime",
    "build_parser",
    "build_runtime",
    "create_mcp_server",
    "create_server",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
