"""Lazy MCP wrappers and definitions for structured animation operations."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

ANIMATION_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    (
        "animation.inspect",
        "Inspect one object's bounded action, F-curves, keyframes, slots, and drivers.",
        False,
        ("INSPECT_SCENE",),
    ),
    (
        "animation.set_frame",
        "Set the current scene frame and subframe explicitly.",
        True,
        ("EDIT_ANIMATION",),
    ),
    (
        "animation.set_range",
        "Set the scene playback and optional preview frame ranges.",
        True,
        ("EDIT_ANIMATION",),
    ),
    (
        "animation.keyframe_insert",
        "Insert a keyframe on an explicit object RNA data path.",
        True,
        ("EDIT_ANIMATION",),
    ),
    (
        "animation.keyframe_delete",
        "Delete a keyframe from an explicit object RNA data path.",
        True,
        ("EDIT_ANIMATION",),
    ),
)
ANIMATION_TOOL_NAMES = tuple(item[0] for item in ANIMATION_TOOL_DATA)


def load_animation_definitions() -> tuple[ToolDefinition, ...]:
    """Return lazy-registry definitions without importing Blender or MCP SDK classes."""

    return tuple(
        remote_tool(
            name,
            toolset="animation",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in ANIMATION_TOOL_DATA
    )


class AnimationTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def animation_inspect(
        self,
        object_name: str,
        max_curves: int = 128,
        max_keyframes: int = 1_000,
    ) -> Any:
        """Inspect bounded animation data for one explicit object."""

        return await self.registry.call(
            "animation.inspect",
            {
                "object_name": object_name,
                "max_curves": max_curves,
                "max_keyframes": max_keyframes,
            },
        )

    async def animation_set_frame(self, frame: float) -> Any:
        """Set the scene's current frame, including a fractional subframe."""

        return await self.registry.call("animation.set_frame", {"frame": frame})

    async def animation_set_range(
        self,
        start: int,
        end: int,
        use_preview: bool = False,
        preview_start: int | None = None,
        preview_end: int | None = None,
    ) -> Any:
        """Set the scene playback range and optional bounded preview range."""

        return await self.registry.call(
            "animation.set_range",
            params(
                start=start,
                end=end,
                use_preview=use_preview,
                preview_start=preview_start,
                preview_end=preview_end,
            ),
        )

    async def animation_keyframe_insert(
        self,
        object_name: str,
        data_path: str,
        frame: float | None = None,
        index: int = -1,
        group: str | None = None,
        options: list[str] | None = None,
    ) -> Any:
        """Insert a keyframe on one explicit object RNA path and array index."""

        return await self.registry.call(
            "animation.keyframe_insert",
            params(
                object_name=object_name,
                data_path=data_path,
                frame=frame,
                index=index,
                group=group,
                options=options,
            ),
        )

    async def animation_keyframe_delete(
        self,
        object_name: str,
        data_path: str,
        frame: float | None = None,
        index: int = -1,
        group: str | None = None,
    ) -> Any:
        """Delete a keyframe on one explicit object RNA path and array index."""

        return await self.registry.call(
            "animation.keyframe_delete",
            params(
                object_name=object_name,
                data_path=data_path,
                frame=frame,
                index=index,
                group=group,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("animation.inspect", self.animation_inspect, self.animation_inspect.__doc__ or ""),
            MCPToolBinding("animation.set_frame", self.animation_set_frame, self.animation_set_frame.__doc__ or ""),
            MCPToolBinding("animation.set_range", self.animation_set_range, self.animation_set_range.__doc__ or ""),
            MCPToolBinding(
                "animation.keyframe_insert",
                self.animation_keyframe_insert,
                self.animation_keyframe_insert.__doc__ or "",
            ),
            MCPToolBinding(
                "animation.keyframe_delete",
                self.animation_keyframe_delete,
                self.animation_keyframe_delete.__doc__ or "",
            ),
        )


__all__ = [
    "ANIMATION_TOOL_DATA",
    "ANIMATION_TOOL_NAMES",
    "AnimationTools",
    "load_animation_definitions",
]
