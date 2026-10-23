"""Typed read-only MCP entry point for bounded stored F-curve values."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictFloat

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params
from .animation_curve_inspection import CurveIndex, DataPath, ObjectName

Frame = Annotated[StrictFloat, Field(ge=-1_000_000, le=1_000_000, allow_inf_nan=False)]
Frames = Annotated[list[Frame], Field(strict=True, min_length=1, max_length=128)]
TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("animation.curve_sample", "Sample bounded direct values of one exact active-Action curve; no scene, NLA, driver, constraint or deformation evaluation.", False, ("INSPECT_SCENE",)),
)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="animation", description=description, modifying=modifying,
                             required_permissions=permissions)
                 for name, description, modifying, permissions in TOOL_DATA)


class AnimationCurveSamplingTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def animation_curve_sample(
        self, object_name: ObjectName, data_path: DataPath, frames: Frames,
        index: CurveIndex = 0, slot_identifier: ObjectName | None = None,
    ) -> Any:
        """Sample one exact active-Action/assigned-slot stored curve at 1 to 128 explicit finite frames within +/-1,000,000. Order and duplicates are preserved; receipts report requested and Float32-effective times. Supports 1 to 1024 ordered finite keyframes, CONSTANT/LINEAR/BEZIER interpolation and CONSTANT/LINEAR extrapolation. Modifiers, drivers and sampled curves fail explicitly. Shared/linked data may be read. No scene time changes, scene/NLA/driver/constraint/deformation evaluation, key or handle updates, checkpoints or saves."""
        return await self.registry.call("animation.curve_sample", params(
            object_name=object_name, data_path=data_path, frames=frames,
            index=index, slot_identifier=slot_identifier,
        ))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (MCPToolBinding("animation.curve_sample", self.animation_curve_sample, self.animation_curve_sample.__doc__ or ""),)
