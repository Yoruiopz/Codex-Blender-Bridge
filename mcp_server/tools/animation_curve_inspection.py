"""Typed read-only MCP entry point for exact active-Action curve pages."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictInt, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

ObjectName = Annotated[StrictStr, Field(min_length=1, max_length=256)]
DataPath = Annotated[StrictStr, Field(min_length=1, max_length=512)]
CurveIndex = Annotated[StrictInt, Field(ge=0, le=16384)]
PointOffset = Annotated[StrictInt, Field(ge=0, le=1_000_000)]
PointLimit = Annotated[StrictInt, Field(ge=1, le=256)]
TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("animation.curve_inspect", "Inspect an exact active-Action curve's extrapolation and paged keyframes with full Bezier handles; never update or evaluate animation.", False, ("INSPECT_SCENE",)),
)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="animation", description=description, modifying=modifying,
                             required_permissions=permissions)
                 for name, description, modifying, permissions in TOOL_DATA)


class AnimationCurveInspectionTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def animation_curve_inspect(
        self, object_name: ObjectName, data_path: DataPath, index: CurveIndex = 0,
        slot_identifier: ObjectName | None = None, point_offset: PointOffset = 0, point_limit: PointLimit = 64,
    ) -> Any:
        """Inspect one exact active-Action/assigned-slot curve, including handle types/coordinates and extrapolation. Curves contain at most 1,000,000 points; pages return at most 256. Use next_offset until truncated is false. Shared/linked data may be read. Sampled curves and unsupported layered APIs fail explicitly; no animation is updated or evaluated."""
        return await self.registry.call("animation.curve_inspect", params(
            object_name=object_name, data_path=data_path, index=index, slot_identifier=slot_identifier,
            point_offset=point_offset, point_limit=point_limit,
        ))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (MCPToolBinding("animation.curve_inspect", self.animation_curve_inspect, self.animation_curve_inspect.__doc__ or ""),)
