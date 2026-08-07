"""Lazy MCP wrappers and definitions for structured Blender modifiers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool], ...] = (
    ("modifier.inspect", "Inspect bounded allowlisted modifier state for an explicit object.", False),
    ("modifier.add", "Add and configure an allowlisted object modifier.", True),
    ("modifier.set", "Set direct allowlisted RNA properties on one modifier.", True),
    ("modifier.remove", "Remove one explicitly named modifier.", True),
    ("modifier.apply", "Apply one modifier in a validated Object Mode context.", True),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"modifier.remove", "modifier.apply"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="modifiers",
            description=description,
            modifying=modifying,
            required_permissions=("TRANSFORM_OBJECTS",) if modifying else ("INSPECT_SCENE",),
        )
        for name, description, modifying in TOOL_DATA
    )


class ModifierTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def modifier_inspect(
        self, object_name: str, modifier_name: str | None = None
    ) -> Any:
        """Inspect all modifiers or one explicitly named modifier."""

        return await self.registry.call(
            "modifier.inspect",
            params(object_name=object_name, modifier_name=modifier_name),
        )

    async def modifier_add(
        self,
        object_name: str,
        modifier_type: str,
        modifier_name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Any:
        """Add an allowlisted modifier with an optional validated settings object."""

        return await self.registry.call(
            "modifier.add",
            params(
                object_name=object_name,
                modifier_type=modifier_type,
                modifier_name=modifier_name,
                settings=settings,
            ),
        )

    async def modifier_set(
        self,
        object_name: str,
        modifier_name: str,
        settings: dict[str, Any],
    ) -> Any:
        """Update direct allowlisted RNA properties on one modifier."""

        return await self.registry.call(
            "modifier.set",
            {
                "object_name": object_name,
                "modifier_name": modifier_name,
                "settings": settings,
            },
        )

    async def modifier_remove(self, object_name: str, modifier_name: str) -> Any:
        """Remove one explicitly named modifier after an automatic checkpoint."""

        return await self.registry.call(
            "modifier.remove",
            {"object_name": object_name, "modifier_name": modifier_name},
        )

    async def modifier_apply(self, object_name: str, modifier_name: str) -> Any:
        """Apply one explicitly named modifier, changing evaluated object data."""

        return await self.registry.call(
            "modifier.apply",
            {"object_name": object_name, "modifier_name": modifier_name},
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("modifier.inspect", self.modifier_inspect, self.modifier_inspect.__doc__ or ""),
            MCPToolBinding("modifier.add", self.modifier_add, self.modifier_add.__doc__ or ""),
            MCPToolBinding("modifier.set", self.modifier_set, self.modifier_set.__doc__ or ""),
            MCPToolBinding("modifier.remove", self.modifier_remove, self.modifier_remove.__doc__ or ""),
            MCPToolBinding("modifier.apply", self.modifier_apply, self.modifier_apply.__doc__ or ""),
        )


__all__ = [
    "DESTRUCTIVE_TOOL_NAMES",
    "TOOL_DATA",
    "TOOL_NAMES",
    "ModifierTools",
    "load_definitions",
]
