"""Lazily-enabled material and shader graph inspection wrapper."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class MaterialTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def material_inspect(
        self,
        material_name: str | None = None,
        object_name: str | None = None,
    ) -> Any:
        """Inspect materials, users, node trees, textures, and Principled values."""

        return await self.registry.call(
            "material.inspect",
            params(material_name=material_name, object_name=object_name),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("material.inspect", self.material_inspect, self.material_inspect.__doc__ or ""),
        )
