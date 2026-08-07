"""Always-available structural scene and selection wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class SceneTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def scene_inspect(
        self,
        include_hidden: bool = False,
        max_objects: int = 200,
        max_collections: int = 500,
        max_collection_objects: int = 100,
        max_collection_depth: int = 12,
    ) -> Any:
        """Return a compact authoritative structural representation of the scene."""

        return await self.registry.call(
            "scene.inspect",
            {
                "include_hidden": include_hidden,
                "max_objects": max_objects,
                "max_collections": max_collections,
                "max_collection_objects": max_collection_objects,
                "max_collection_depth": max_collection_depth,
            },
        )

    async def scene_summary(
        self,
        include_hidden: bool = False,
        max_collections: int = 100,
        max_objects_per_collection: int = 100,
    ) -> Any:
        """Return a concise textual and JSON scene hierarchy summary."""

        return await self.registry.call(
            "scene.summary",
            {
                "include_hidden": include_hidden,
                "max_collections": max_collections,
                "max_objects_per_collection": max_objects_per_collection,
            },
        )

    async def selection_inspect(self, create_selection_id: bool = True) -> Any:
        """Inspect active/selected objects or selected Edit Mode mesh elements."""

        return await self.registry.call(
            "selection.inspect", {"create_selection_id": create_selection_id}
        )

    async def object_inspect(self, object_name: str) -> Any:
        """Inspect one object in detail without returning every vertex coordinate."""

        return await self.registry.call(
            "object.inspect", params(object_name=object_name)
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("scene.inspect", self.scene_inspect, self.scene_inspect.__doc__ or ""),
            MCPToolBinding("scene.summary", self.scene_summary, self.scene_summary.__doc__ or ""),
            MCPToolBinding("selection.inspect", self.selection_inspect, self.selection_inspect.__doc__ or ""),
            MCPToolBinding("object.inspect", self.object_inspect, self.object_inspect.__doc__ or ""),
        )
