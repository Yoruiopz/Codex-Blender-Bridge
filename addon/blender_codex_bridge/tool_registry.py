"""Declarative Blender tool registry with permission and toolset gates."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import BridgeError, ErrorCode
from .permissions import Permission, PermissionManager
from .state import BridgeState

ToolHandler = Callable[["ToolContext", Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    handler: ToolHandler
    permissions: frozenset[Permission]
    toolset: str
    modifies: bool
    description: str
    automatic_checkpoint: bool = True
    remote: bool = True

    def metadata(self, *, enabled: bool) -> dict[str, Any]:
        return {
            "name": self.name,
            "toolset": self.toolset,
            "description": self.description,
            "required_permissions": sorted(permission.value for permission in self.permissions),
            "modifies": self.modifies,
            "enabled": enabled,
            "remote": self.remote,
        }


@dataclass(slots=True)
class ToolContext:
    """Services supplied to a tool without exposing network internals."""

    state: BridgeState
    permissions: PermissionManager
    registry: ToolRegistry
    checkpoints: Any

    def require(self, *permissions: Permission) -> None:
        self.permissions.require(permissions)


class ToolRegistry:
    """Register, describe, enable, and dispatch structured tools."""

    CORE_TOOLSET = "core"
    RECOVERY_TOOLS = frozenset({"checkpoint.undo_last", "checkpoint.restore_last"})

    def __init__(self, *, enabled_toolsets: Iterable[str] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._toolsets: set[str] = {self.CORE_TOOLSET}
        self._enabled_toolsets: set[str] = {self.CORE_TOOLSET, *enabled_toolsets}

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        permissions: Iterable[Permission] = (),
        toolset: str = CORE_TOOLSET,
        modifies: bool = False,
        description: str = "",
        automatic_checkpoint: bool = True,
        remote: bool = True,
    ) -> ToolSpec:
        if not name or "." not in name:
            raise ValueError("Tool names must be non-empty dotted identifiers.")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        toolset = toolset.strip().lower()
        spec = ToolSpec(
            name=name,
            handler=handler,
            permissions=frozenset(permissions),
            toolset=toolset,
            modifies=modifies,
            description=description,
            automatic_checkpoint=automatic_checkpoint,
            remote=remote,
        )
        self._tools[name] = spec
        self._toolsets.add(toolset)
        return spec

    def tool(
        self,
        name: str,
        *,
        permissions: Iterable[Permission] = (),
        toolset: str = CORE_TOOLSET,
        modifies: bool = False,
        description: str = "",
        automatic_checkpoint: bool = True,
        remote: bool = True,
    ) -> Callable[[ToolHandler], ToolHandler]:
        def decorator(handler: ToolHandler) -> ToolHandler:
            self.register(
                name,
                handler,
                permissions=permissions,
                toolset=toolset,
                modifies=modifies,
                description=description,
                automatic_checkpoint=automatic_checkpoint,
                remote=remote,
            )
            return handler

        return decorator

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise BridgeError(
                ErrorCode.METHOD_NOT_FOUND,
                f"Unknown Blender bridge method '{name}'.",
                {"available_methods": sorted(self._tools)},
            ) from exc

    def prepare(
        self,
        name: str,
        context: ToolContext,
        *,
        allow_recovery: bool = False,
    ) -> ToolSpec:
        spec = self.get(name)
        if not spec.remote and not allow_recovery:
            raise BridgeError(
                ErrorCode.METHOD_NOT_FOUND,
                f"Tool '{name}' is available only from Blender's local recovery UI.",
            )
        if spec.toolset not in self._enabled_toolsets:
            raise BridgeError(
                ErrorCode.TOOLSET_DISABLED,
                f"Toolset '{spec.toolset}' is disabled in Blender.",
                {"tool": name, "toolset": spec.toolset},
            )
        context.permissions.require(spec.permissions)
        runtime_state = context.state.snapshot()
        recovery_override = allow_recovery and name in self.RECOVERY_TOOLS
        if spec.modifies and runtime_state["emergency_stopped"] and not recovery_override:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Agent modifications are emergency-stopped.")
        if spec.modifies and runtime_state["paused"] and not recovery_override:
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Agent modifications are paused in Blender.")
        return spec

    def dispatch(self, name: str, params: Mapping[str, Any], context: ToolContext) -> Any:
        spec = self.prepare(name, context)
        return spec.handler(context, params)

    def enable_toolset(self, name: str) -> None:
        normalized = name.strip().lower()
        if normalized not in self._toolsets:
            raise BridgeError(
                ErrorCode.INVALID_ARGUMENT,
                f"Unknown toolset '{name}'.",
                {"available_toolsets": sorted(self._toolsets)},
            )
        self._enabled_toolsets.add(normalized)

    def disable_toolset(self, name: str) -> None:
        normalized = name.strip().lower()
        if normalized == self.CORE_TOOLSET:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "The core toolset cannot be disabled.")
        if normalized not in self._toolsets:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, f"Unknown toolset '{name}'.")
        self._enabled_toolsets.discard(normalized)

    def list_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def describe(self) -> dict[str, Any]:
        return {
            "toolsets": [
                {
                    "name": name,
                    "enabled": name in self._enabled_toolsets,
                    "tool_count": sum(spec.toolset == name for spec in self._tools.values()),
                }
                for name in sorted(self._toolsets)
            ],
            "tools": [
                self._tools[name].metadata(enabled=self._tools[name].toolset in self._enabled_toolsets)
                for name in sorted(self._tools)
            ],
        }

    @property
    def enabled_toolsets(self) -> tuple[str, ...]:
        return tuple(sorted(self._enabled_toolsets))

    def reset_enabled_toolsets(self) -> None:
        """Return to the secure startup state without unloading definitions."""

        self._enabled_toolsets = {self.CORE_TOOLSET}
