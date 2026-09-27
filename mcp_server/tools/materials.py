"""Static MCP wrappers and lazy definitions for material operations."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

MATERIAL_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    (
        "material.inspect",
        "Inspect material users, important nodes, textures, and Principled values.",
        False,
        ("INSPECT_SCENE",),
    ),
    (
        "material.create",
        "Create a named material with optional nodes and viewport color.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "material.delete",
        "Delete one exact material, refusing active users unless forced.",
        True,
        ("EDIT_MATERIALS", "DELETE_OBJECTS"),
    ),
    (
        "material.assign",
        "Assign a material to an exact object slot or append it.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "material.unassign",
        "Clear one exact object material slot without deleting it.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "material.slot_add",
        "Append a material slot to one exact object.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "material.slot_remove",
        "Remove one exact object material slot.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "material.set_principled",
        "Set validated common Principled BSDF inputs.",
        True,
        ("EDIT_MATERIALS",),
    ),
    (
        "material.copy_for_object",
        "Copy a material for one object slot without changing shared mesh data.",
        True,
        ("EDIT_MATERIALS",),
    ),
)
MATERIAL_TOOL_NAMES = tuple(item[0] for item in MATERIAL_TOOL_DATA)


def load_definitions() -> tuple[ToolDefinition, ...]:
    """Return lazy-registry definitions without importing the MCP SDK."""

    return tuple(
        remote_tool(
            name,
            toolset="materials",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in MATERIAL_TOOL_DATA
    )


load_material_definitions = load_definitions


class MaterialTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def material_inspect(
        self,
        material_name: str | None = None,
        object_name: str | None = None,
    ) -> Any:
        """Inspect materials, users, node trees, textures, and Principled values."""

        return await self.registry.call(
            "material.inspect",
            params(material_name=material_name, object_name=object_name),
        )

    async def material_create(
        self,
        name: str,
        use_nodes: bool = True,
        diffuse_color: list[float] | None = None,
    ) -> Any:
        """Create a unique named material and return its resulting state."""

        return await self.registry.call(
            "material.create",
            params(name=name, use_nodes=use_nodes, diffuse_color=diffuse_color),
        )

    async def material_delete(
        self,
        material_name: str,
        only_if_unused: bool = True,
        allow_shared: bool = False,
    ) -> Any:
        """Delete a material; forced unlink needs editable users; shared usage needs allow_shared."""

        return await self.registry.call(
            "material.delete",
            {
                "material_name": material_name,
                "only_if_unused": only_if_unused,
                "allow_shared": allow_shared,
            },
        )

    async def material_assign(
        self,
        object_name: str,
        material_name: str,
        slot_index: int | None = None,
    ) -> Any:
        """Assign a material by exact names, appending when no slot is supplied."""

        return await self.registry.call(
            "material.assign",
            params(
                object_name=object_name,
                material_name=material_name,
                slot_index=slot_index,
            ),
        )

    async def material_unassign(self, object_name: str, slot_index: int) -> Any:
        """Clear one exact material slot while preserving the slot itself."""

        return await self.registry.call(
            "material.unassign",
            {"object_name": object_name, "slot_index": slot_index},
        )

    async def material_slot_add(self, object_name: str, material_name: str) -> Any:
        """Append a new material slot containing an existing named material."""

        return await self.registry.call(
            "material.slot_add",
            {"object_name": object_name, "material_name": material_name},
        )

    async def material_slot_remove(self, object_name: str, slot_index: int) -> Any:
        """Remove one exact material slot and return the remapped slot state."""

        return await self.registry.call(
            "material.slot_remove",
            {"object_name": object_name, "slot_index": slot_index},
        )

    async def material_set_principled(
        self,
        material_name: str,
        node_name: str | None = None,
        base_color: list[float] | None = None,
        metallic: float | None = None,
        roughness: float | None = None,
        ior: float | None = None,
        alpha: float | None = None,
        emission_color: list[float] | None = None,
        emission_strength: float | None = None,
        coat_weight: float | None = None,
        allow_shared: bool = False,
    ) -> Any:
        """Set Principled inputs; inspect usage before consenting to shared edits with allow_shared."""

        return await self.registry.call(
            "material.set_principled",
            params(
                material_name=material_name,
                node_name=node_name,
                base_color=base_color,
                metallic=metallic,
                roughness=roughness,
                ior=ior,
                alpha=alpha,
                emission_color=emission_color,
                emission_strength=emission_strength,
                coat_weight=coat_weight,
                allow_shared=allow_shared,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("material.inspect", self.material_inspect, self.material_inspect.__doc__ or ""),
            MCPToolBinding("material.create", self.material_create, self.material_create.__doc__ or ""),
            MCPToolBinding("material.delete", self.material_delete, self.material_delete.__doc__ or ""),
            MCPToolBinding("material.assign", self.material_assign, self.material_assign.__doc__ or ""),
            MCPToolBinding("material.unassign", self.material_unassign, self.material_unassign.__doc__ or ""),
            MCPToolBinding("material.slot_add", self.material_slot_add, self.material_slot_add.__doc__ or ""),
            MCPToolBinding("material.slot_remove", self.material_slot_remove, self.material_slot_remove.__doc__ or ""),
            MCPToolBinding(
                "material.set_principled",
                self.material_set_principled,
                self.material_set_principled.__doc__ or "",
            ),
            MCPToolBinding("material.copy_for_object", self.material_copy_for_object,
                           self.material_copy_for_object.__doc__ or ""),
        )

    async def material_copy_for_object(self, object_name: str, slot_index: int, new_name: str) -> Any:
        """Copy and bind one slot at OBJECT level; mesh, nested groups and images stay shared."""
        return await self.registry.call(
            "material.copy_for_object",
            {"object_name": object_name, "slot_index": slot_index, "new_name": new_name},
        )


__all__ = [
    "MATERIAL_TOOL_DATA",
    "MATERIAL_TOOL_NAMES",
    "MaterialTools",
    "load_definitions",
    "load_material_definitions",
]
