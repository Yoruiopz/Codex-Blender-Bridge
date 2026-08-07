"""Lazily-enabled deterministic object transform wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class TransformTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def transform_set(
        self,
        object_name: str,
        location: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> Any:
        """Set any supplied absolute transform components; rotations are radians."""

        return await self.registry.call(
            "transform.set",
            params(
                object_name=object_name,
                location=location,
                rotation=rotation,
                scale=scale,
            ),
        )

    async def transform_translate(
        self,
        object_name: str,
        offset: list[float],
        space: str = "WORLD",
    ) -> Any:
        """Translate by a three-component offset in WORLD or LOCAL space."""

        return await self.registry.call(
            "transform.translate",
            {"object_name": object_name, "offset": offset, "space": space},
        )

    async def transform_rotate(
        self,
        object_name: str,
        rotation: list[float],
        space: str = "LOCAL",
    ) -> Any:
        """Rotate by a three-component XYZ Euler delta in radians."""

        return await self.registry.call(
            "transform.rotate",
            {"object_name": object_name, "rotation": rotation, "space": space},
        )

    async def transform_scale(
        self,
        object_name: str,
        factors: list[float],
    ) -> Any:
        """Multiply the object's local scale by three explicit axis factors."""

        return await self.registry.call(
            "transform.scale",
            {"object_name": object_name, "factors": factors},
        )

    async def transform_apply(
        self,
        object_name: str,
        location: bool = False,
        rotation: bool = False,
        scale: bool = True,
    ) -> Any:
        """Apply selected transform components to object data."""

        return await self.registry.call(
            "transform.apply",
            {
                "object_name": object_name,
                "location": location,
                "rotation": rotation,
                "scale": scale,
            },
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("transform.set", self.transform_set, self.transform_set.__doc__ or ""),
            MCPToolBinding("transform.translate", self.transform_translate, self.transform_translate.__doc__ or ""),
            MCPToolBinding("transform.rotate", self.transform_rotate, self.transform_rotate.__doc__ or ""),
            MCPToolBinding("transform.scale", self.transform_scale, self.transform_scale.__doc__ or ""),
            MCPToolBinding("transform.apply", self.transform_apply, self.transform_apply.__doc__ or ""),
        )
