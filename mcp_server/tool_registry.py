"""Layered, lazily-loaded MCP tool registry."""

from __future__ import annotations

import builtins
import inspect
import threading
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import BridgeError, ToolsetDisabledError
from .schemas import JsonValue, ToolsetState, validate_json_value


class AsyncRequestClient(Protocol):
    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
    ) -> JsonValue: ...


ToolHandler = Callable[
    [AsyncRequestClient, Mapping[str, JsonValue]],
    Awaitable[JsonValue] | JsonValue,
]
ToolsetLoader = Callable[[], Iterable["ToolDefinition"]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Runtime metadata and handler for one structured tool."""

    name: str
    description: str
    handler: ToolHandler
    toolset: str = "core"
    modifying: bool = False
    required_permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("tool name must be a non-empty string")
        if not self.toolset or not isinstance(self.toolset, str):
            raise ValueError("toolset must be a non-empty string")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")


@dataclass(slots=True)
class _ToolsetDefinition:
    name: str
    description: str
    loader: ToolsetLoader
    declared_tools: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    enabled: bool = False
    loaded: bool = False


async def _forward_request(
    client: AsyncRequestClient, method: str, params: Mapping[str, JsonValue]
) -> JsonValue:
    return await client.request(method, params)


def remote_tool(
    name: str,
    *,
    toolset: str = "core",
    description: str = "",
    modifying: bool = False,
    required_permissions: Iterable[str] = (),
) -> ToolDefinition:
    """Create a definition that forwards unchanged to the Blender add-on."""

    async def handler(
        client: AsyncRequestClient, params: Mapping[str, JsonValue]
    ) -> JsonValue:
        return await _forward_request(client, name, params)

    return ToolDefinition(
        name=name,
        description=description,
        handler=handler,
        toolset=toolset,
        modifying=modifying,
        required_permissions=tuple(required_permissions),
    )


class ToolRegistry:
    """Own tool enablement without changing the MCP server's static schema.

    MCP discovery remains deterministic: every wrapper is registered at startup.
    Definitions for domain groups are loaded only when enabled. Calls to a visible
    but disabled wrapper fail locally with ``TOOLSET_DISABLED`` and never reach
    Blender. Blender still performs its own authoritative permission checks.
    """

    def __init__(self, client: AsyncRequestClient) -> None:
        self.client = client
        self._tools: dict[str, ToolDefinition] = {}
        self._toolsets: dict[str, _ToolsetDefinition] = {}
        self._aliases: dict[str, str] = {}
        self._tool_to_toolset: dict[str, str] = {}
        self._lock = threading.RLock()

    def register_core(self, definitions: Iterable[ToolDefinition]) -> None:
        with self._lock:
            for definition in definitions:
                if definition.toolset != "core":
                    raise ValueError(
                        f"Core tool {definition.name!r} must declare toolset='core'"
                    )
                self._register_definition(definition)

    def register_toolset(
        self,
        name: str,
        loader: ToolsetLoader,
        *,
        tools: Iterable[str],
        description: str = "",
        aliases: Iterable[str] = (),
        enabled: bool = False,
    ) -> None:
        """Declare a lazy toolset without running its loader."""

        if not isinstance(name, str) or not name.strip() or name == "core":
            raise ValueError("toolset name must be non-empty and may not be 'core'")
        declared = tuple(dict.fromkeys(tools))
        if not declared:
            raise ValueError("a domain toolset must declare at least one tool")
        alias_tuple = tuple(dict.fromkeys(aliases))
        with self._lock:
            if name in self._toolsets or name in self._aliases:
                raise ValueError(f"toolset {name!r} is already registered")
            for alias in alias_tuple:
                if (
                    not alias
                    or alias == "core"
                    or alias in self._toolsets
                    or alias in self._aliases
                ):
                    raise ValueError(f"toolset alias {alias!r} is invalid or duplicated")
            for tool_name in declared:
                existing = self._tool_to_toolset.get(tool_name)
                if existing is not None:
                    raise ValueError(
                        f"tool {tool_name!r} is already declared by {existing!r}"
                    )
                if tool_name in self._tools:
                    raise ValueError(f"tool {tool_name!r} is already registered")
            definition = _ToolsetDefinition(
                name=name,
                description=description,
                loader=loader,
                declared_tools=declared,
                aliases=alias_tuple,
                enabled=False,
            )
            self._toolsets[name] = definition
            for alias in alias_tuple:
                self._aliases[alias] = name
            for tool_name in declared:
                self._tool_to_toolset[tool_name] = name
            if enabled:
                self._load_toolset(definition)
                definition.enabled = True

    def inspect(self, name: str | None = None) -> dict[str, JsonValue]:
        """Return deterministic local state for one or all toolsets."""

        with self._lock:
            states = self._states()
            if name is None:
                return {
                    "toolsets": [state.to_dict() for state in states],
                    "enabled": [
                        state.name for state in states if state.enabled
                    ],
                }
            canonical = self._canonical_toolset(name)
            if canonical == "core":
                return self._core_state().to_dict()
            definition = self._toolsets.get(canonical)
            if definition is None:
                raise BridgeError(
                    "TOOLSET_NOT_FOUND",
                    f"Unknown toolset '{name}'.",
                    context={"available": ["core", *sorted(self._toolsets)]},
                )
            return self._state(definition).to_dict()

    def list(self) -> dict[str, JsonValue]:
        """Alias matching the ``toolsets.list`` MCP operation."""

        return self.inspect()

    def enable(self, name: str) -> dict[str, JsonValue]:
        with self._lock:
            canonical = self._canonical_toolset(name)
            if canonical == "core":
                return {
                    "changed": False,
                    "toolset": self._core_state().to_dict(),
                }
            definition = self._toolsets.get(canonical)
            if definition is None:
                raise BridgeError(
                    "TOOLSET_NOT_FOUND",
                    f"Unknown toolset '{name}'.",
                    context={"available": sorted(self._toolsets)},
                )
            changed = not definition.enabled
            self._load_toolset(definition)
            definition.enabled = True
            return {"changed": changed, "toolset": self._state(definition).to_dict()}

    def disable(self, name: str) -> dict[str, JsonValue]:
        with self._lock:
            canonical = self._canonical_toolset(name)
            if canonical == "core":
                raise BridgeError(
                    "INVALID_ARGUMENT", "The core toolset is always enabled."
                )
            definition = self._toolsets.get(canonical)
            if definition is None:
                raise BridgeError(
                    "TOOLSET_NOT_FOUND",
                    f"Unknown toolset '{name}'.",
                    context={"available": sorted(self._toolsets)},
                )
            changed = definition.enabled
            definition.enabled = False
            # Keep definitions cached so re-enabling is inexpensive.
            return {"changed": changed, "toolset": self._state(definition).to_dict()}

    async def call(
        self,
        tool_name: str,
        params: Mapping[str, Any] | None = None,
        **keyword_params: Any,
    ) -> JsonValue:
        """Validate enablement, then invoke one handler."""

        if params is not None and keyword_params:
            raise BridgeError(
                "INVALID_ARGUMENT",
                "Pass tool parameters either as a mapping or keyword arguments, not both.",
            )
        raw_params: Mapping[str, Any] = keyword_params if params is None else params
        if not isinstance(raw_params, Mapping):
            raise BridgeError("INVALID_ARGUMENT", "Tool parameters must be an object.")
        try:
            clean_params = validate_json_value(raw_params, path="$.params")
        except ValueError as exc:
            raise BridgeError("INVALID_ARGUMENT", str(exc)) from exc
        assert isinstance(clean_params, dict)
        if tool_name == "toolsets.list":
            # Listing local capability state must work even before Blender starts.
            return self.list()
        if tool_name in {"toolsets.enable", "toolsets.disable"}:
            requested = clean_params.get("name")
            if not isinstance(requested, str) or not requested.strip():
                raise BridgeError(
                    "INVALID_ARGUMENT",
                    "Toolset control requires a non-empty string parameter 'name'.",
                )
            return await self._synchronize_toolset(
                requested, enable=tool_name == "toolsets.enable"
            )
        with self._lock:
            definition = self._tools.get(tool_name)
            toolset = self._tool_to_toolset.get(tool_name)
            if toolset is not None:
                group = self._toolsets[toolset]
                if not group.enabled:
                    raise ToolsetDisabledError(tool_name, toolset)
                if definition is None:
                    # Defensive: enable() normally performs this load.
                    self._load_toolset(group)
                    definition = self._tools.get(tool_name)
            if definition is None:
                raise BridgeError(
                    "TOOL_NOT_FOUND",
                    f"Unknown tool '{tool_name}'.",
                    context={"available": self.tool_names(include_disabled=True)},
                )
        result = definition.handler(self.client, clean_params)
        if inspect.isawaitable(result):
            result = await result
        try:
            return validate_json_value(result, path="$.result")
        except ValueError as exc:
            raise BridgeError(
                "PROTOCOL_ERROR",
                f"Tool '{tool_name}' returned a non-JSON result: {exc}",
            ) from exc

    def tool_names(self, *, include_disabled: bool = False) -> builtins.list[str]:
        with self._lock:
            names = set(self._tools)
            if include_disabled:
                names.update(self._tool_to_toolset)
            else:
                for tool_name, toolset in self._tool_to_toolset.items():
                    if self._toolsets[toolset].enabled:
                        names.add(tool_name)
            return sorted(names)

    async def _synchronize_toolset(
        self, requested_name: str, *, enable: bool
    ) -> JsonValue:
        """Change Blender first, then mirror it locally, rolling back on failure."""

        canonical = self._canonical_toolset(requested_name)
        # Validate without changing local state before touching Blender.
        self.inspect(canonical)
        if canonical == "core":
            if enable:
                return {
                    "changed": False,
                    "toolset": self._core_state().to_dict(),
                    "blender": None,
                }
            raise BridgeError(
                "INVALID_ARGUMENT", "The core toolset is always enabled."
            )
        operation = "toolsets.enable" if enable else "toolsets.disable"
        inverse = "toolsets.disable" if enable else "toolsets.enable"
        remote_result = await self.client.request(operation, {"name": canonical})
        try:
            local_result = self.enable(canonical) if enable else self.disable(canonical)
        except Exception:
            # A loader/configuration bug must not leave Blender and MCP with
            # opposite capability state. Preserve the original local state.
            with suppress(Exception):
                await self.client.request(inverse, {"name": canonical})
            raise
        return {
            **local_result,
            "blender": remote_result,
            "scope": "mcp_and_blender",
        }

    @property
    def enabled_toolsets(self) -> tuple[str, ...]:
        with self._lock:
            return (
                "core",
                *tuple(
                    sorted(
                        name
                        for name, definition in self._toolsets.items()
                        if definition.enabled
                    )
                ),
            )

    def _canonical_toolset(self, name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise BridgeError(
                "INVALID_ARGUMENT", "Toolset name must be a non-empty string."
            )
        normalized = name.strip().lower()
        return self._aliases.get(normalized, normalized)

    def _load_toolset(self, definition: _ToolsetDefinition) -> None:
        if definition.loaded:
            return
        loaded = tuple(definition.loader())
        names = tuple(item.name for item in loaded)
        if len(names) != len(set(names)):
            raise ValueError(f"loader for {definition.name!r} returned duplicate tools")
        undeclared = sorted(set(names) - set(definition.declared_tools))
        missing = sorted(set(definition.declared_tools) - set(names))
        if undeclared or missing:
            raise ValueError(
                f"loader for {definition.name!r} disagrees with declared tools "
                f"(missing={missing}, undeclared={undeclared})"
            )
        for item in loaded:
            if item.toolset != definition.name:
                raise ValueError(
                    f"tool {item.name!r} must declare toolset={definition.name!r}"
                )
            self._register_definition(item)
        definition.loaded = True

    def _register_definition(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool {definition.name!r} is already registered")
        self._tools[definition.name] = definition

    def _core_state(self) -> ToolsetState:
        tools = tuple(
            sorted(name for name, item in self._tools.items() if item.toolset == "core")
        )
        return ToolsetState(
            name="core",
            enabled=True,
            loaded=True,
            tools=tools,
            description="Always-available inspection, capture, checkpoint, save, and registry tools.",
        )

    def _state(self, definition: _ToolsetDefinition) -> ToolsetState:
        return ToolsetState(
            name=definition.name,
            enabled=definition.enabled,
            loaded=definition.loaded,
            tools=tuple(sorted(definition.declared_tools)),
            description=definition.description,
            aliases=tuple(sorted(definition.aliases)),
        )

    def _states(self) -> builtins.list[ToolsetState]:
        return [
            self._core_state(),
            *(self._state(self._toolsets[name]) for name in sorted(self._toolsets)),
        ]


def create_default_registry(client: AsyncRequestClient) -> ToolRegistry:
    """Create the V1 registry while preserving lazy domain imports."""

    from .tools.catalog import (
        CORE_DEFINITIONS,
        MATERIAL_TOOL_NAMES,
        MESH_TOOL_NAMES,
        OBJECT_TOOL_NAMES,
        load_material_definitions,
        load_mesh_definitions,
        load_object_definitions,
    )

    registry = ToolRegistry(client)
    registry.register_core(CORE_DEFINITIONS)
    registry.register_toolset(
        "objects",
        load_object_definitions,
        tools=OBJECT_TOOL_NAMES,
        aliases=("transforms",),
        description="Object lifecycle, hierarchy, collection, and transform operations.",
    )
    registry.register_toolset(
        "mesh",
        load_mesh_definitions,
        tools=MESH_TOOL_NAMES,
        description="Selection-scoped mesh inspection and editing operations.",
    )
    registry.register_toolset(
        "materials",
        load_material_definitions,
        tools=MATERIAL_TOOL_NAMES,
        description="Material and shader-node inspection operations.",
    )
    return registry


__all__ = [
    "AsyncRequestClient",
    "ToolDefinition",
    "ToolRegistry",
    "create_default_registry",
    "remote_tool",
]
