"""Typed whole-world memory-cache proposals; Blender remains authoritative."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

CacheOperation = Literal["BAKE", "FREE", "INVALIDATE"]
Name = Annotated[StrictStr, Field(min_length=1, max_length=63)]
BodyNames = Annotated[list[Name], Field(min_length=1, max_length=16)]
ConstraintNames = Annotated[list[Name], Field(max_length=16)]
Frame = Annotated[StrictInt, Field(ge=1, le=1048574)]
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("rigid_body.inspect", "Inspect the exact current Scene's bounded whole-world rigid bodies, constraints and cache ownership.", False, ("INSPECT_SCENE",)),
    ("rigid_body.cache_preview", "Preview a bounded memory-only world operation and session/context fingerprint; requires static reviewed Main dependencies including unused IDs.", False, ("INSPECT_SCENE",)),
    ("rigid_body.cache", "Execute an exact whole-world memory cache proposal; BAKE verifies every matrix/frame and all operations measure context recovery.", True, ("INSPECT_SCENE", "EDIT_SCENE", "EDIT_ANIMATION")),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"rigid_body.cache"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(tool_name, toolset="simulation", description=description, modifying=modifying,
                             required_permissions=permissions)
                 for tool_name, description, modifying, permissions in TOOL_DATA)


class RigidBodyTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def rigid_body_inspect(self, scene_name: Name) -> Any:
        """Inspect an exact actual current Scene; never infer complete freshness from native baked/outdated flags."""
        return await self.registry.call("rigid_body.inspect", {"scene_name": scene_name})

    async def rigid_body_cache_preview(self, scene_name: Name, operation: CacheOperation,
                                       body_names: BodyNames, constraint_names: ConstraintNames,
                                       frame_start: Frame | None = None, frame_end: Frame | None = None) -> Any:
        """Preview the complete world with static reviewed Main dependencies, including unused IDs. BAKE resets unbaked memory; native calls are nonpreemptible."""
        return await self.registry.call("rigid_body.cache_preview", params(scene_name=scene_name, operation=operation,
            body_names=body_names, constraint_names=constraint_names, frame_start=frame_start, frame_end=frame_end))

    async def rigid_body_cache(self, scene_name: Name, operation: CacheOperation,
                               body_names: BodyNames, constraint_names: ConstraintNames, expected_fingerprint: Fingerprint,
                               frame_start: Frame | None = None, frame_end: Frame | None = None) -> Any:
        """Execute an unchanged preview; memory-only, explicit whole-world scope, no save, disk access or cache undo guarantee."""
        return await self.registry.call("rigid_body.cache", params(scene_name=scene_name, operation=operation,
            body_names=body_names, constraint_names=constraint_names, expected_fingerprint=expected_fingerprint,
            frame_start=frame_start, frame_end=frame_end))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(tool_name, getattr(self, tool_name.replace(".", "_")), description)
                     for tool_name, description, _, _ in TOOL_DATA)
