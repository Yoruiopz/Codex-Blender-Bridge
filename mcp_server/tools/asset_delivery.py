"""Strict wrappers for explicit previewed GLB/FBX delivery."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

TOOL_DATA = (
    ("asset.export_preview", "Preview exact static/skinned asset scope and GLB/FBX format limits.", False, ("INSPECT_SCENE",)),
    ("asset.export", "Export a current previewed asset to an approved unused GLB/FBX path.", True,
     ("INSPECT_SCENE", "EDIT_SCENE", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT")),
)
TOOL_NAMES = tuple(row[0] for row in TOOL_DATA)
ObjectNames = Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=256)]], Field(min_length=1, max_length=64)]
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
FormatLoss = Literal["VERTEX_SPLITS", "AXIS_CONVERSION", "BONE_AXIS_CONVERSION", "SAMPLED_INTEGER_FRAMES"]


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="asset_delivery", description=description,
        modifying=modifying, required_permissions=permissions)
        for name, description, modifying, permissions in TOOL_DATA)


class AssetDeliveryTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def asset_export_preview(self, object_names: ObjectNames, format: Literal["GLB", "FBX"],
                                   include_animation: StrictBool = False) -> Any:
        """Preview exact visible local material-free triangle mesh/rig/empty scope. Requires complete parent/armature dependencies, normalized <=4 skin influences, no constraints/drivers/NLA/shape keys/simulation/materials/textures, <=100000 vertices, <=256 bones and <=250 animation frames. Units must be one metre. Returns a fingerprint and explicit format limits; no file writes. Animated sources require include_animation=true."""
        return await self.registry.call("asset.export_preview", {"object_names": object_names,
            "format": format, "include_animation": include_animation})

    async def asset_export(self, object_names: ObjectNames, format: Literal["GLB", "FBX"],
                           filepath: StrictStr, expected_fingerprint: Fingerprint,
                           accepted_losses: list[FormatLoss], include_animation: StrictBool = False) -> Any:
        """Export exactly the current preview fingerprint, repeating its required_accepted_losses verbatim. Requires local Approved Asset Folder plus inspect/scene-edit/external-file/save grants. Exact absolute unused output, matching .glb/.fbx extension, existing ordinary local parents; no overwrite, auto rename, directories or unreviewed image reads. Native export is synchronous/non-preemptible. Owned staging is hashed then published atomically without replacement; cancellation after publication retains the file and truthful effects, which Blender undo never deletes. Source and context are independently checked. Fresh-process/downstream appearance acceptance is separate; no arbitrary import tool or .blend save."""
        return await self.registry.call("asset.export", {"object_names": object_names, "format": format,
            "filepath": filepath, "expected_fingerprint": expected_fingerprint,
            "accepted_losses": accepted_losses, "include_animation": include_animation})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in (
            ("asset.export_preview", self.asset_export_preview), ("asset.export", self.asset_export)))
