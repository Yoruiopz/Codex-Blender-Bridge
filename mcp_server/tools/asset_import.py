"""Strict approved-source static asset import wrappers; no Blender imports."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

READ = ("INSPECT_SCENE", "ACCESS_EXTERNAL_FILES")
REQUIRED = (
    *READ,
    "EDIT_SCENE",
    "TRANSFORM_OBJECTS",
    "EDIT_MESH",
    "EDIT_MATERIALS",
    "EDIT_ANIMATION",
    "DELETE_OBJECTS",
)
TOOL_DATA = (
    (
        "asset.import_preview",
        "Validate complete approved static GLB/FBX bytes and preview source/destination fingerprint.",
        False,
        READ,
    ),
    (
        "asset.import",
        "Import a current preview over frozen private source bytes into a new owned collection.",
        True,
        REQUIRED,
    ),
)
TOOL_NAMES = tuple(row[0] for row in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES = ("asset.import",)
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
CollectionName = Annotated[StrictStr, Field(min_length=1, max_length=63)]
ImportLoss = Literal[
    "VERTEX_SPLITS",
    "AXIS_UNIT_CONVERSION",
    "PBR_MATERIAL_RECONSTRUCTION",
    "FBX_MESH_RECONSTRUCTION",
]


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset="asset_delivery",
            description=description,
            modifying=modifying,
            required_permissions=permissions,
        )
        for name, description, modifying, permissions in TOOL_DATA
    )


class AssetImportTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def asset_import_preview(
        self,
        filepath: StrictStr,
        format: Literal["GLB", "FBX"],
        include_animation: StrictBool = False,
    ) -> Any:
        """Read complete bytes only from Blender's separate Approved Asset Source Folder with live inspect/external-file grants. Preview self-contained GLB2 triangle/empty assets with bounded core PBR constants/base-color PNG/JPEG or static material-free binary FBX7400/7500 mesh/empty assets. Reject all external/data URIs, extensions, rigs/skins/animation, unreviewed material channels and embedded/native import hooks. Complete bounded source validation and protected destination evidence are required; no writes or project save. Return exact fingerprint and required_accepted_losses. include_animation=true remains NOT_IMPLEMENTED."""
        return await self.registry.call(
            "asset.import_preview",
            {"filepath": filepath, "format": format, "include_animation": include_animation},
        )

    async def asset_import(
        self,
        filepath: StrictStr,
        format: Literal["GLB", "FBX"],
        collection_name: CollectionName,
        expected_fingerprint: Fingerprint,
        accepted_losses: list[ImportLoss],
        include_animation: StrictBool = False,
    ) -> Any:
        """Import precisely the current approved-source/destination preview, repeating its required_accepted_losses exactly, into an unused exact collection_name. Require live domain/READ/delete grants; no SAVE_PROJECT grant or source-folder writes. A private owned input freezes validated complete bytes; synchronous native import in a private scene is non-preemptible. Publish only a measured owned mesh/empty/material/packed-image closure. Recheck protected existing geometry/UV/weights/rig/animation/shader definitions, complete loaded pixels/packed bytes, FPS/frame/subframe/units/context. Stop/revocation or newer/unexpected consumers can retain resources and private input with explicit recovery evidence. Undo does not clean filesystem staging. Source animation/skin/general textured FBX and visual/durable reopen acceptance remain separate, unsupported work."""
        return await self.registry.call(
            "asset.import",
            {
                "filepath": filepath,
                "format": format,
                "collection_name": collection_name,
                "expected_fingerprint": expected_fingerprint,
                "accepted_losses": accepted_losses,
                "include_animation": include_animation,
            },
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(
            MCPToolBinding(name, method, method.__doc__ or "")
            for name, method in (
                ("asset.import_preview", self.asset_import_preview),
                ("asset.import", self.asset_import),
            )
        )
