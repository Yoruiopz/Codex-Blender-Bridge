"""Lazily-enabled object lifecycle and hierarchy wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class ObjectTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def object_create(
        self,
        object_type: str,
        name: str | None = None,
        collection: str | None = None,
        location: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> Any:
        """Create a named structured primitive and return its resulting state."""

        return await self.registry.call(
            "object.create",
            params(
                object_type=object_type,
                name=name,
                collection=collection,
                location=location,
                rotation=rotation,
                scale=scale,
            ),
        )

    async def object_delete(self, object_name: str) -> Any:
        """Delete an object only when Blender grants DELETE_OBJECTS."""

        return await self.registry.call(
            "object.delete", {"object_name": object_name}
        )

    async def object_duplicate(
        self,
        object_name: str,
        new_name: str | None = None,
        linked: bool = False,
    ) -> Any:
        """Duplicate an object and optionally share its underlying data."""

        return await self.registry.call(
            "object.duplicate",
            params(object_name=object_name, new_name=new_name, linked=linked),
        )

    async def object_rename(self, object_name: str, new_name: str) -> Any:
        """Rename one object and return its authoritative resulting identity."""

        return await self.registry.call(
            "object.rename", {"object_name": object_name, "new_name": new_name}
        )

    async def object_set_parent(
        self,
        object_name: str,
        parent_name: str | None = None,
        keep_transform: bool = True,
    ) -> Any:
        """Set or clear an object's parent while optionally retaining world transform."""

        return await self.registry.call(
            "object.set_parent",
            params(
                object_name=object_name,
                parent_name=parent_name,
                keep_transform=keep_transform,
            ),
        )

    async def object_move_to_collection(
        self,
        object_name: str,
        collection_name: str,
        link_only: bool = False,
    ) -> Any:
        """Move an object to a collection or additionally link it there."""

        return await self.registry.call(
            "object.move_to_collection",
            {
                "object_name": object_name,
                "collection_name": collection_name,
                "link_only": link_only,
            },
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("object.create", self.object_create, self.object_create.__doc__ or ""),
            MCPToolBinding("object.delete", self.object_delete, self.object_delete.__doc__ or ""),
            MCPToolBinding("object.duplicate", self.object_duplicate, self.object_duplicate.__doc__ or ""),
            MCPToolBinding("object.rename", self.object_rename, self.object_rename.__doc__ or ""),
            MCPToolBinding("object.set_parent", self.object_set_parent, self.object_set_parent.__doc__ or ""),
            MCPToolBinding("object.move_to_collection", self.object_move_to_collection, self.object_move_to_collection.__doc__ or ""),
        )
