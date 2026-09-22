"""Lazily-enabled mesh inspection and selection-scoped editing wrappers."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params


class MeshTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def mesh_create(
        self,
        object_name: str,
        mesh_name: str,
        vertices: list[list[float]],
        edges: list[list[int]] | None = None,
        faces: list[list[int]] | None = None,
        collection_name: str | None = None,
        location: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
        rotation_mode: str = "XYZ",
    ) -> Any:
        """Create an arbitrary mesh from fully prevalidated bounded topology arrays."""

        return await self.registry.call(
            "mesh.create",
            params(
                object_name=object_name,
                mesh_name=mesh_name,
                vertices=vertices,
                edges=edges,
                faces=faces,
                collection_name=collection_name,
                location=location,
                rotation=rotation,
                scale=scale,
                rotation_mode=rotation_mode,
            ),
        )

    async def mesh_inspect(self, object_name: str | None = None) -> Any:
        """Inspect compact mesh and topology statistics."""

        return await self.registry.call(
            "mesh.inspect", params(object_name=object_name)
        )

    async def mesh_recalculate_normals(
        self,
        object_name: str | None = None,
        inside: bool = False,
        selection_only: bool = True,
        selection_id: str | None = None,
    ) -> Any:
        """Recalculate mesh normals for the selection or whole mesh."""

        return await self.registry.call(
            "mesh.recalculate_normals",
            params(
                object_name=object_name,
                inside=inside,
                selection_only=selection_only,
                selection_id=selection_id,
            ),
        )

    async def mesh_delete_selected(
        self,
        object_name: str | None = None,
        element_type: str = "VERT",
        selection_id: str | None = None,
    ) -> Any:
        """Delete selected VERT, EDGE, or FACE elements."""

        return await self.registry.call(
            "mesh.delete_selected",
            params(
                object_name=object_name,
                element_type=element_type,
                selection_id=selection_id,
            ),
        )

    async def mesh_dissolve_selected(
        self,
        object_name: str | None = None,
        use_verts: bool = False,
        use_face_split: bool = False,
        selection_id: str | None = None,
    ) -> Any:
        """Dissolve selected elements while preserving surrounding surface where possible."""

        return await self.registry.call(
            "mesh.dissolve_selected",
            params(
                object_name=object_name,
                use_verts=use_verts,
                use_face_split=use_face_split,
                selection_id=selection_id,
            ),
        )

    async def mesh_extrude_selected(
        self,
        offset: list[float],
        object_name: str | None = None,
        selection_id: str | None = None,
    ) -> Any:
        """Extrude selected geometry by a three-component local-space offset."""

        return await self.registry.call(
            "mesh.extrude_selected",
            params(
                object_name=object_name,
                offset=offset,
                selection_id=selection_id,
            ),
        )

    async def mesh_inset_selected(
        self,
        thickness: float,
        depth: float = 0.0,
        object_name: str | None = None,
        selection_id: str | None = None,
    ) -> Any:
        """Inset selected faces by explicit thickness and depth."""

        return await self.registry.call(
            "mesh.inset_selected",
            params(
                object_name=object_name,
                thickness=thickness,
                depth=depth,
                selection_id=selection_id,
            ),
        )

    async def mesh_bevel_selected(
        self,
        width: float,
        segments: int = 1,
        affect: str = "EDGES",
        object_name: str | None = None,
        selection_id: str | None = None,
    ) -> Any:
        """Bevel selected edges or vertices with explicit width and segments."""

        return await self.registry.call(
            "mesh.bevel_selected",
            params(
                object_name=object_name,
                width=width,
                segments=segments,
                affect=affect,
                selection_id=selection_id,
            ),
        )

    async def mesh_mark_seams(
        self, object_name: str, seam: bool = True, selection_id: str | None = None,
    ) -> Any:
        """Mark/clear selected edge UV seams on a single-user active Edit Mode mesh; preserve geometry, UV coordinates and selection."""
        return await self.registry.call(
            "mesh.mark_seams", params(object_name=object_name, seam=seam, selection_id=selection_id),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("mesh.mark_seams", self.mesh_mark_seams, self.mesh_mark_seams.__doc__ or ""),
            MCPToolBinding("mesh.create", self.mesh_create, self.mesh_create.__doc__ or ""),
            MCPToolBinding("mesh.inspect", self.mesh_inspect, self.mesh_inspect.__doc__ or ""),
            MCPToolBinding("mesh.recalculate_normals", self.mesh_recalculate_normals, self.mesh_recalculate_normals.__doc__ or ""),
            MCPToolBinding("mesh.delete_selected", self.mesh_delete_selected, self.mesh_delete_selected.__doc__ or ""),
            MCPToolBinding("mesh.dissolve_selected", self.mesh_dissolve_selected, self.mesh_dissolve_selected.__doc__ or ""),
            MCPToolBinding("mesh.extrude_selected", self.mesh_extrude_selected, self.mesh_extrude_selected.__doc__ or ""),
            MCPToolBinding("mesh.inset_selected", self.mesh_inset_selected, self.mesh_inset_selected.__doc__ or ""),
            MCPToolBinding("mesh.bevel_selected", self.mesh_bevel_selected, self.mesh_bevel_selected.__doc__ or ""),
        )
