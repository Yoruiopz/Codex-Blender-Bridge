"""Lazily-enabled scene query and multi-object layout wrappers."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params


class _NamedEdit(TypedDict):
    object_name: str


class TransformEdit(_NamedEdit, total=False):
    location: list[float]
    rotation: list[float]
    scale: list[float]


LAYOUT_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("scene.query", "Query bounded current-view-layer objects by glob, type, collection, visibility, selection, and evaluated world origin.", False, ("INSPECT_SCENE",)),
    ("object.transform_batch", "Prevalidate and apply up to 128 explicit independent-object transforms in one logical operation.", True, ("TRANSFORM_OBJECTS",)),
    ("object.align", "Align explicit independent objects by evaluated world origins along one axis.", True, ("TRANSFORM_OBJECTS",)),
    ("object.distribute", "Space explicit independent object origins evenly on one world axis while preserving endpoints.", True, ("TRANSFORM_OBJECTS",)),
)
LAYOUT_TOOL_NAMES = tuple(item[0] for item in LAYOUT_TOOL_DATA)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="layout", description=description, modifying=modifying, required_permissions=permissions) for name, description, modifying, permissions in LAYOUT_TOOL_DATA)


class LayoutTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def scene_query(
        self,
        name_pattern: str = "*",
        object_types: list[str] | None = None,
        collection_name: str | None = None,
        selected: bool | None = None,
        visible: bool | None = None,
        origin_min: list[float] | None = None,
        origin_max: list[float] | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Any:
        """Query current view layer; glob is case-sensitive, collection includes descendants, bounds are evaluated world origins (not surfaces). Follow next_offset; scan capped at 100,000 objects."""

        return await self.registry.call("scene.query", params(name_pattern=name_pattern, object_types=object_types, collection_name=collection_name, selected=selected, visible=visible, origin_min=origin_min, origin_max=origin_max, offset=offset, limit=limit))

    async def object_transform_batch(self, edits: list[TransformEdit]) -> Any:
        """Set 1-128 named objects' absolute location/Euler-radian rotation/scale with complete prevalidation and rollback on failure. Object mode and independent, local, unlocked objects only; no parenting, constraints, animation, rigid bodies, or delta transforms. Does not change selection."""

        return await self.registry.call("object.transform_batch", {"edits": edits})

    async def object_align(self, object_names: list[str], axis: str = "X", target: str = "CENTER", reference_object: str | None = None) -> Any:
        """Align 2-128 independent object origins on X/Y/Z to MIN/MAX/CENTER (midpoint of extrema) or REFERENCE (explicit member). Preserves other coordinates, rotation, scale, and selection. Same dependency restrictions as transform_batch."""

        return await self.registry.call("object.align", params(object_names=object_names, axis=axis, target=target, reference_object=reference_object))

    async def object_distribute(self, object_names: list[str], axis: str = "X") -> Any:
        """Distribute 3-128 independent world origins evenly on X/Y/Z, sorted by coordinate then name. Preserves endpoint positions and off-axis coordinates. Same dependency restrictions as transform_batch."""

        return await self.registry.call("object.distribute", {"object_names": object_names, "axis": axis})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods = (("scene.query", self.scene_query), ("object.transform_batch", self.object_transform_batch), ("object.align", self.object_align), ("object.distribute", self.object_distribute))
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in methods)


__all__ = ["LAYOUT_TOOL_DATA", "LAYOUT_TOOL_NAMES", "LayoutTools", "load_definitions"]
