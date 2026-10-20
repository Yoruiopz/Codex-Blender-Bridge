"""Strict MCP schemas for reviewed shader settings and complete color-ramp revisions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params
from .shader_groups import GroupPath

Position = Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)]
Component = Annotated[StrictFloat, Field(ge=0, le=1_000_000, allow_inf_nan=False)]
ShaderScalar = StrictBool | StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)] | StrictStr


class RampStop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: Position
    color: Annotated[list[Component], Field(min_length=4, max_length=4)]


SHADER_SETTINGS_TOOL_DATA = (
    ("nodes.inspect_properties", "Inspect one shader node's reviewed settings, native enum choices and color ramp with bounded native samples.", False, ("INSPECT_SCENE",)),
    ("nodes.set_properties", "Set reviewed native shader-node scalar/enum properties, preserving links/socket defaults with measured failure recovery.", True, ("EDIT_MATERIALS",)),
    ("nodes.set_color_ramp", "Replace a shader color ramp with 1-32 ordered scene-linear RGBA stops and reviewed interpolation settings.", True, ("EDIT_MATERIALS",)),
)


class ShaderSettingsTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def nodes_inspect_properties(self, material_name: StrictStr, node_name: StrictStr,
                                       group_path: GroupPath | None = None,
                                       sample_positions: Annotated[list[Position], Field(max_length=32)] | None = None) -> Any:
        """Inspect one exact shader node at the root or group_path: native enum identifiers, reviewed settings and up to 32 ramp stops/samples. Reports stored versus effective interpolation: HSV/HSL use linear interpolation and hue wrapping; RGB uses the stored interpolation and ignores hue wrapping. No edits/file loads, recursive group inspection or rendered-appearance certification."""
        return await self.registry.call("nodes.inspect_properties", params(material_name=material_name, node_name=node_name,
            group_path=group_path, sample_positions=sample_positions))

    async def nodes_set_properties(self, material_name: StrictStr, node_name: StrictStr,
                                  settings: Annotated[dict[str, ShaderScalar], Field(min_length=1, max_length=32)],
                                  group_path: GroupPath | None = None, allow_shared: StrictBool = False) -> Any:
        """Object Mode: revise only inspected, per-node reviewed native settings. No arbitrary attributes, pointers, scripts or Image Texture properties (use nodes.set_image for its file-policy checks). Local unanimated material/target tree; nested/shared ownership needs explicit consent. Native changes must preserve links and socket structure/defaults; failures return measured rollback evidence, not a blanket transaction guarantee. Reinspect and capture the result."""
        return await self.registry.call("nodes.set_properties", params(material_name=material_name, node_name=node_name,
            settings=settings, group_path=group_path, allow_shared=allow_shared))

    async def nodes_set_color_ramp(self, material_name: StrictStr, node_name: StrictStr,
                                  stops: Annotated[list[RampStop], Field(min_length=1, max_length=32)],
                                  interpolation: StrictStr | None = None, color_mode: StrictStr | None = None,
                                  hue_interpolation: StrictStr | None = None,
                                  group_path: GroupPath | None = None, allow_shared: StrictBool = False) -> Any:
        """Object Mode: replace all stops of an exact ShaderNodeValToRGB at root/group_path. Supply the complete nondecreasing list; equal positions preserve requested color-index order. Positions 0-1, scene-linear RGBA components 0-1e6, native float32 rounding. Interpolation/color/hue modes use inspected native identifiers. No topology/links/input-default changes; direct material/target animation is unsupported. Inspect ownership, isolate shared groups or explicitly allow_shared. Failed local restoration is possible: inspect rollback_verified and recover the logical checkpoint if needed. Verify native samples and a matched material capture."""
        return await self.registry.call("nodes.set_color_ramp", params(material_name=material_name, node_name=node_name,
            stops=[stop.model_dump() for stop in stops], interpolation=interpolation, color_mode=color_mode,
            hue_interpolation=hue_interpolation, group_path=group_path, allow_shared=allow_shared))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods: tuple[Callable[..., Any], ...] = (self.nodes_inspect_properties, self.nodes_set_properties, self.nodes_set_color_ramp)
        return tuple(MCPToolBinding(data[0], method, method.__doc__ or "")
                     for data, method in zip(SHADER_SETTINGS_TOOL_DATA, methods, strict=True))
