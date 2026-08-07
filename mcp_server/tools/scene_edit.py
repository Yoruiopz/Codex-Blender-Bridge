"""Structured scene, collection, camera, light, and world wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

SCENE_EDIT_TOOL_DATA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("scene.configure", "Configure an explicit scene's camera, units, and gravity.", True, ("EDIT_SCENE",)),
    ("collection.create", "Create and link a collection under an explicit scene or parent.", True, ("EDIT_SCENE",)),
    ("collection.rename", "Rename an explicit collection without collisions.", True, ("EDIT_SCENE",)),
    ("collection.delete", "Remove an explicitly confirmed collection and report unlinked contents.", True, ("EDIT_SCENE", "DELETE_OBJECTS")),
    ("camera.configure", "Configure camera optics, clipping, depth of field, and active-scene assignment.", True, ("EDIT_SCENE",)),
    ("light.configure", "Configure a named Blender light's type, energy, color, and shape settings.", True, ("EDIT_SCENE",)),
    ("world.configure", "Create, assign, and configure a scene world and Background node.", True, ("EDIT_SCENE",)),
)
SCENE_EDIT_TOOL_NAMES = tuple(item[0] for item in SCENE_EDIT_TOOL_DATA)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="scene_edit",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in SCENE_EDIT_TOOL_DATA
    )


class SceneEditTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def scene_configure(
        self,
        scene_name: str,
        camera_object: str | None = None,
        clear_camera: bool = False,
        unit_system: str | None = None,
        unit_scale_length: float | None = None,
        use_gravity: bool | None = None,
        gravity: list[float] | None = None,
    ) -> Any:
        """Configure camera assignment, units, and gravity for an explicit scene."""

        return await self.registry.call(
            "scene.configure",
            params(
                scene_name=scene_name,
                camera_object=camera_object,
                clear_camera=clear_camera,
                unit_system=unit_system,
                unit_scale_length=unit_scale_length,
                use_gravity=use_gravity,
                gravity=gravity,
            ),
        )

    async def collection_create(
        self,
        scene_name: str,
        name: str,
        parent_collection: str | None = None,
    ) -> Any:
        """Create and link a collection in an explicit scene."""

        return await self.registry.call(
            "collection.create",
            params(scene_name=scene_name, name=name, parent_collection=parent_collection),
        )

    async def collection_rename(self, collection_name: str, new_name: str) -> Any:
        """Rename an explicit collection without collisions."""

        return await self.registry.call(
            "collection.rename",
            {"collection_name": collection_name, "new_name": new_name},
        )

    async def collection_delete(
        self,
        collection_name: str,
        confirm_delete: bool = False,
    ) -> Any:
        """Remove a collection only after explicit acknowledgement."""

        return await self.registry.call(
            "collection.delete",
            {"collection_name": collection_name, "confirm_delete": confirm_delete},
        )

    async def camera_configure(
        self,
        object_name: str,
        camera_type: str | None = None,
        lens: float | None = None,
        sensor_width: float | None = None,
        clip_start: float | None = None,
        clip_end: float | None = None,
        ortho_scale: float | None = None,
        dof_enabled: bool | None = None,
        focus_object: str | None = None,
        clear_focus_object: bool = False,
        aperture_fstop: float | None = None,
        scene_name: str | None = None,
        set_active_for_scene: bool | None = None,
    ) -> Any:
        """Configure camera optics, clipping, depth of field, and scene assignment."""

        return await self.registry.call(
            "camera.configure",
            params(
                object_name=object_name,
                camera_type=camera_type,
                lens=lens,
                sensor_width=sensor_width,
                clip_start=clip_start,
                clip_end=clip_end,
                ortho_scale=ortho_scale,
                dof_enabled=dof_enabled,
                focus_object=focus_object,
                clear_focus_object=clear_focus_object,
                aperture_fstop=aperture_fstop,
                scene_name=scene_name,
                set_active_for_scene=set_active_for_scene,
            ),
        )

    async def light_configure(
        self,
        object_name: str,
        light_type: str | None = None,
        energy: float | None = None,
        color: list[float] | None = None,
        shadow_soft_size: float | None = None,
        spot_size: float | None = None,
        spot_blend: float | None = None,
    ) -> Any:
        """Configure a named light's type, energy, color, and shape."""

        return await self.registry.call(
            "light.configure",
            params(
                object_name=object_name,
                light_type=light_type,
                energy=energy,
                color=color,
                shadow_soft_size=shadow_soft_size,
                spot_size=spot_size,
                spot_blend=spot_blend,
            ),
        )

    async def world_configure(
        self,
        scene_name: str,
        world_name: str | None = None,
        create: bool = False,
        use_nodes: bool | None = None,
        color: list[float] | None = None,
        strength: float | None = None,
    ) -> Any:
        """Create, assign, and configure a scene world and Background node."""

        return await self.registry.call(
            "world.configure",
            params(
                scene_name=scene_name,
                world_name=world_name,
                create=create,
                use_nodes=use_nodes,
                color=color,
                strength=strength,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods = (
            ("scene.configure", self.scene_configure),
            ("collection.create", self.collection_create),
            ("collection.rename", self.collection_rename),
            ("collection.delete", self.collection_delete),
            ("camera.configure", self.camera_configure),
            ("light.configure", self.light_configure),
            ("world.configure", self.world_configure),
        )
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in methods)


__all__ = [
    "SCENE_EDIT_TOOL_DATA",
    "SCENE_EDIT_TOOL_NAMES",
    "SceneEditTools",
    "load_definitions",
]
