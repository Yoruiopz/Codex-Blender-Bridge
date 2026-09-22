"""Lazy MCP definitions for precise object and component context controls."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    (
        "mesh.components_inspect",
        "Inspect paginated component indices and measured centers on the active single Edit Mode mesh.",
        False,
        ("INSPECT_SCENE",),
    ),
    (
        "selection.set",
        "Set exact Object Mode selection and active object; do not change visibility or mode.",
        True,
        ("TRANSFORM_OBJECTS",),
    ),
    (
        "context.set_mode",
        "Set a named object's mode; non-Object modes isolate selection and require EDIT_MESH or EDIT_ANIMATION.",
        True,
        ("TRANSFORM_OBJECTS",),
    ),
    (
        "mesh.select_components",
        "Select bounded explicit indices on the active single Edit Mode mesh; return refreshed selection ID.",
        True,
        ("EDIT_MESH",),
    ),
)
TOOL_NAMES = tuple(item[0] for item in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES: frozenset[str] = frozenset()


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="interaction",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in TOOL_DATA
    )


class InteractionTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def mesh_components_inspect(
        self,
        object_name: str,
        element_type: str,
        offset: int = 0,
        max_items: int = 100,
        selected_only: bool = False,
    ) -> Any:
        """Inspect VERT/EDGE/FACE indices, local/world centers, normals and bounded connectivity in active single-object Edit Mode. Pagination uses offset/max_items (max 256); indices must be reinspected after topology/context changes."""
        return await self.registry.call(
            "mesh.components_inspect",
            {
                "object_name": object_name,
                "element_type": element_type,
                "offset": offset,
                "max_items": max_items,
                "selected_only": selected_only,
            },
        )

    async def selection_set(
        self, object_names: list[str], operation: str = "REPLACE", active_object: str | None = None
    ) -> Any:
        """REPLACE/ADD/REMOVE up to 200 exact names in Object Mode; active must be in the result."""
        return await self.registry.call(
            "selection.set",
            params(object_names=object_names, operation=operation, active_object=active_object),
        )

    async def context_set_mode(self, object_name: str, mode: str) -> Any:
        """OBJECT; mesh EDIT/SCULPT/VERTEX_PAINT/WEIGHT_PAINT/TEXTURE_PAINT; armature EDIT/POSE. Editing isolates the named object. Exit another active object's mode explicitly first."""
        return await self.registry.call(
            "context.set_mode", {"object_name": object_name, "mode": mode}
        )

    async def mesh_select_components(
        self,
        object_name: str,
        element_type: str,
        indices: list[int],
        operation: str = "REPLACE",
        selection_id: str | None = None,
    ) -> Any:
        """REPLACE/ADD/REMOVE at most 20,000 VERT/EDGE/FACE indices; requires active single-object Edit Mode. Optional selection_id rejects stale topology/context. Dependent components flush consistently."""
        return await self.registry.call(
            "mesh.select_components",
            params(
                object_name=object_name,
                element_type=element_type,
                indices=indices,
                operation=operation,
                selection_id=selection_id,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(
            MCPToolBinding(name, handler, handler.__doc__ or "")
            for name, handler in (
                ("mesh.components_inspect", self.mesh_components_inspect),
                ("selection.set", self.selection_set),
                ("context.set_mode", self.context_set_mode),
                ("mesh.select_components", self.mesh_select_components),
            )
        )


__all__ = [
    "DESTRUCTIVE_TOOL_NAMES",
    "TOOL_DATA",
    "TOOL_NAMES",
    "InteractionTools",
    "load_definitions",
]
