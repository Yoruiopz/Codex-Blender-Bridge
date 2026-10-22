"""Lazy typed MCP entry points for bounded Action and curve authoring."""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import NotRequired, TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params


class KeyframeEdit(TypedDict):
    frame: float
    interpolation: NotRequired[Literal["CONSTANT", "LINEAR", "BEZIER"]]
    easing: NotRequired[Literal["AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"]]
    handle_left_type: NotRequired[Literal["FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"]]
    handle_right_type: NotRequired[Literal["FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"]]
    handle_left: NotRequired[list[float]]
    handle_right: NotRequired[list[float]]


TOOL_DATA = (
    ("animation.action_copy", "Copy and bind an explicit independent active Action; source remains in this session, unused source retention across saves is not guaranteed."),
    ("animation.curve_edit", "Edit interpolation/easing/handles on at most 256 existing keyframes of one local unshared active-Action curve; at most 1024 curve points, no insertion or arbitrary RNA."),
)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="animation", description=description, modifying=True,
                             required_permissions=("EDIT_ANIMATION",)) for name, description in TOOL_DATA)


class AnimationCurveTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def animation_action_copy(self, object_name: str, new_name: str, affected_objects: list[str] | None = None) -> Any:
        """Bind an independent Action version; an unused source is retained only in this session."""
        return await self.registry.call("animation.action_copy", params(object_name=object_name, new_name=new_name, affected_objects=affected_objects))

    async def animation_curve_edit(
        self, object_name: str, data_path: str, index: int = 0,
        keyframes: list[KeyframeEdit] | None = None,
        extrapolation: Literal["CONSTANT", "LINEAR"] | None = None,
        slot_identifier: str | None = None,
        affected_objects: list[str] | None = None,
    ) -> Any:
        """Edit one existing curve; explicit handle coordinates require corresponding FREE handle types."""
        return await self.registry.call("animation.curve_edit", params(
            object_name=object_name, data_path=data_path, index=index, keyframes=keyframes,
            extrapolation=extrapolation, slot_identifier=slot_identifier, affected_objects=affected_objects,
        ))

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("animation.action_copy", self.animation_action_copy, self.animation_action_copy.__doc__ or ""),
            MCPToolBinding("animation.curve_edit", self.animation_curve_edit, self.animation_curve_edit.__doc__ or ""),
        )
