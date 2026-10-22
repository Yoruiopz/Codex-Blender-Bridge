"""Typed explicit Action ownership, binding and retention controls."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("animation.action_inspect", "Inspect one exact Action's bounded content, slots, direct references and save retention.", False, ("INSPECT_SCENE",)),
    ("animation.action_create", "Create an unbound OBJECT-slot Action with explicit fake-user retention; never saves.", True, ("EDIT_ANIMATION",)),
    ("animation.action_bind", "Assign/clear an exact object Action/slot with expected old binding and explicit affected-object scope.", True, ("EDIT_ANIMATION",)),
    ("animation.action_update", "Rename/set fake-user retention on one Action; clearing retention additionally needs DELETE_OBJECTS.", True, ("EDIT_ANIMATION",)),
    ("animation.action_remove", "Confirm removal of one unused unretained Action ID without unlinking or automatic recreation.", True, ("EDIT_ANIMATION", "DELETE_OBJECTS")),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = frozenset({"animation.action_update", "animation.action_remove"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(tool_name, toolset="animation", description=description, modifying=modifying, required_permissions=permissions)
                 for tool_name, description, modifying, permissions in TOOL_DATA)


class ActionLifecycleTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def animation_action_inspect(self, action_name: str) -> Any:
        """Inspect bounded content/slots/direct users and session-only versus fake-user retention; no saving."""
        return await self.registry.call("animation.action_inspect", {"action_name": action_name})

    async def animation_action_create(self, action_name: str, slot_name: str, keep_on_save: bool) -> Any:
        """Create an unbound OBJECT-slot Action with explicitly chosen retention; keep_on_save does not write a project."""
        return await self.registry.call("animation.action_create", params(action_name=action_name, slot_name=slot_name, keep_on_save=keep_on_save))

    async def animation_action_bind(self, object_name: str, action_name: str | None, expected_action_name: str | None,
                                    affected_objects: list[str], slot_identifier: str | None = None,
                                    allow_session_only_previous: bool = False) -> Any:
        """Assign or explicitly clear using action_name=null; require the exact previous Action and enumerated dependent object closure."""
        # Null action/expected-action fields are intentional choices, never omitted.
        payload = params(object_name=object_name, affected_objects=affected_objects, slot_identifier=slot_identifier,
                         allow_session_only_previous=allow_session_only_previous)
        payload.update(action_name=action_name, expected_action_name=expected_action_name)
        return await self.registry.call("animation.action_bind", payload)

    async def animation_action_update(self, action_name: str, new_name: str | None = None,
                                      keep_on_save: bool | None = None, allow_shared: bool = False) -> Any:
        """Rename/change retention with shared-user acknowledgement; clearing a fake retention flag additionally requires live DELETE_OBJECTS."""
        return await self.registry.call("animation.action_update", params(action_name=action_name, new_name=new_name,
                                        keep_on_save=keep_on_save, allow_shared=allow_shared))

    async def animation_action_remove(self, action_name: str, confirm: bool = False) -> Any:
        """Delete only an explicitly confirmed unreferenced unretained local Action ID; never unlink users or recreate it automatically."""
        return await self.registry.call("animation.action_remove", {"action_name": action_name, "confirm": confirm})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(tool_name, getattr(self, tool_name.replace(".", "_")), description)
                     for tool_name, description, _, _ in TOOL_DATA)
