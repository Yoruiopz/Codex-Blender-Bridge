"""Typed native NLA clips, transitions and identity-preserving track ordering."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("nla.clip_add", "Add one explicit Action/slot clip into an existing unlocked track without overlap or channel mapping.", True, ("EDIT_ANIMATION",)),
    ("nla.transition_add", "Create one real native transition between explicitly named adjacent gapped clips; requires an existing NLA Editor.", True, ("EDIT_ANIMATION",)),
    ("nla.transition_remove", "Confirm removal of exactly one native transition while preserving its neighboring clips and Action contents.", True, ("EDIT_ANIMATION",)),
    ("nla.track_reorder", "Reorder the complete explicit track permutation with native identities preserved; requires an existing NLA Editor.", True, ("EDIT_ANIMATION",)),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"nla.transition_remove"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="animation_layers", description=description,
                             modifying=modifying, required_permissions=permissions)
                 for name, description, modifying, permissions in TOOL_DATA)


class NlaLifecycleTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def nla_clip_add(self, object_name: str, affected_objects: list[str], track_name: str,
                           strip_name: str, action_name: str, frame_start: int,
                           slot_identifier: str | None = None) -> Any:
        """Add an exact existing Action/slot into one existing track; no overlap, trimming, copying or automatic slot mapping."""
        return await self.registry.call("nla.clip_add", params(object_name=object_name,
            affected_objects=affected_objects, track_name=track_name, strip_name=strip_name,
            action_name=action_name, frame_start=frame_start, slot_identifier=slot_identifier))

    async def nla_transition_add(self, object_name: str, affected_objects: list[str], track_name: str,
                                 left_strip: str, right_strip: str, new_name: str) -> Any:
        """Create a native transition over the exact positive gap between adjacent clips in an existing NLA Editor."""
        return await self.registry.call("nla.transition_add", {"object_name": object_name,
            "affected_objects": affected_objects, "track_name": track_name,
            "left_strip": left_strip, "right_strip": right_strip, "new_name": new_name})

    async def nla_transition_remove(self, object_name: str, affected_objects: list[str], track_name: str,
                                    left_strip: str, right_strip: str, transition_name: str,
                                    confirm: bool = False) -> Any:
        """Remove only the confirmed exact TRANSITION; neighbors/Actions remain. Use finalized checkpoint recovery for deletion."""
        return await self.registry.call("nla.transition_remove", {"object_name": object_name,
            "affected_objects": affected_objects, "track_name": track_name,
            "left_strip": left_strip, "right_strip": right_strip,
            "transition_name": transition_name, "confirm": confirm})

    async def nla_track_reorder(self, object_name: str, affected_objects: list[str],
                                track_names: list[str]) -> Any:
        """Apply the exact complete bottom-to-top track permutation using an existing NLA Editor, preserving track/strip IDs."""
        return await self.registry.call("nla.track_reorder", {"object_name": object_name,
            "affected_objects": affected_objects, "track_names": track_names})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, getattr(self, name.replace(".", "_")), description)
                     for name, description, _, _ in TOOL_DATA)
