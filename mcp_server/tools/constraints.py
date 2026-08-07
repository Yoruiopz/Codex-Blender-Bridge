"""Lazy MCP wrappers and definitions for structured object constraints."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
    ("constraint.inspect", "Inspect bounded object constraints and allowlisted settings.", False),
    ("constraint.add", "Add an allowlisted object constraint with an explicit target where required.", True),
    ("constraint.set", "Set direct allowlisted RNA properties on one object constraint.", True),
    ("constraint.remove", "Remove one explicitly named object constraint.", True),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"constraint.remove"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="constraints",
            description=description,
            modifying=modifying,
            required_permissions=("TRANSFORM_OBJECTS",) if modifying else ("INSPECT_SCENE",),
        )
        for name, description, modifying in TOOL_DATA
    )


class ConstraintTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def constraint_inspect(
        self, object_name: str, constraint_name: str | None = None
    ) -> Any:
        """Inspect all object constraints or one explicitly named constraint."""

        return await self.registry.call(
            "constraint.inspect",
            params(object_name=object_name, constraint_name=constraint_name),
        )

    async def constraint_add(
        self,
        object_name: str,
        constraint_type: str,
        constraint_name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Any:
        """Add an allowlisted object constraint with bounded settings."""

        return await self.registry.call(
            "constraint.add",
            params(
                object_name=object_name,
                constraint_type=constraint_type,
                constraint_name=constraint_name,
                settings=settings,
            ),
        )

    async def constraint_set(
        self,
        object_name: str,
        constraint_name: str,
        settings: dict[str, Any],
    ) -> Any:
        """Update direct allowlisted RNA properties on one object constraint."""

        return await self.registry.call(
            "constraint.set",
            {
                "object_name": object_name,
                "constraint_name": constraint_name,
                "settings": settings,
            },
        )

    async def constraint_remove(self, object_name: str, constraint_name: str) -> Any:
        """Remove one explicitly named object constraint after a checkpoint."""

        return await self.registry.call(
            "constraint.remove",
            {"object_name": object_name, "constraint_name": constraint_name},
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("constraint.inspect", self.constraint_inspect, self.constraint_inspect.__doc__ or ""),
            MCPToolBinding("constraint.add", self.constraint_add, self.constraint_add.__doc__ or ""),
            MCPToolBinding("constraint.set", self.constraint_set, self.constraint_set.__doc__ or ""),
            MCPToolBinding("constraint.remove", self.constraint_remove, self.constraint_remove.__doc__ or ""),
        )


__all__ = [
    "DESTRUCTIVE_TOOL_NAMES",
    "TOOL_DATA",
    "TOOL_NAMES",
    "ConstraintTools",
    "load_definitions",
]
