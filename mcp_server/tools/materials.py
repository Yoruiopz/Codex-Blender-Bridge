"""Static MCP wrappers and lazy definitions for material operations."""

from __future__ import annotations

from typing import Any

from pydantic import StrictBool, StrictInt, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

MATERIAL_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("image.inspect", "Inspect bounded image metadata/direct users without loading unloaded buffers.", False, ("INSPECT_SCENE",)),
    ("image.load", "Load a new bounded PNG/JPEG image from Blender's user-approved texture folder; no implicit reuse or file writes.", True, ("EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES")),
    ("image.remove", "Remove one explicitly confirmed unused image datablock, never its source file.", True, ("EDIT_MATERIALS", "DELETE_OBJECTS")),
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

    async def image_inspect(self, image_name: StrictStr | None = None, offset: StrictInt = 0, max_images: StrictInt = 32) -> Any:
        """Read existing image metadata and direct users, not file contents/pixels. Unloaded dimensions are not probed. Max 64 images, 100 direct users each / 256 total. Reports the Blender-controlled texture-folder policy without changing it."""
        return await self.registry.call("image.inspect", params(image_name=image_name, offset=offset, max_images=max_images))

    async def image_load(self, filepath: StrictStr, new_name: StrictStr, colorspace: StrictStr = "sRGB") -> Any:
        """Object Mode only. Load a NEW image from an absolute local path inside the folder chosen in Blender's bridge settings. Requires material-edit and external-file permissions. PNG (no animation or iCCP/zTXt/iTXt chunks) or 8-bit baseline/progressive JPEG; 32 MiB, 8192 per dimension, 16,777,216 pixels. No implicit reuse/reload, filename expansion, remote path, packing or file writes. Native decode is not interruptible; failure attempts scoped cleanup and requires reinspection. sRGB defaults to color textures; explicitly use an available Non-Color space for data maps. Verify appearance and save only if asked."""
        return await self.registry.call("image.load", {"filepath": filepath, "new_name": new_name, "colorspace": colorspace})

    async def image_remove(self, image_name: StrictStr, confirm_unused: StrictBool = False) -> Any:
        """Remove one confirmed zero-user local image datablock in Object Mode; fake users or active users block it. Requires material-edit and deletion permission. Never deletes a source file; checkpoint and verify recovery."""
        return await self.registry.call("image.remove", {"image_name": image_name, "confirm_unused": confirm_unused})

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
            MCPToolBinding("image.inspect", self.image_inspect, self.image_inspect.__doc__ or ""),
            MCPToolBinding("image.load", self.image_load, self.image_load.__doc__ or ""),
            MCPToolBinding("image.remove", self.image_remove, self.image_remove.__doc__ or ""),
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
