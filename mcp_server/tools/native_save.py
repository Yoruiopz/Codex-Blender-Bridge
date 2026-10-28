"""Typed stock-Blender native save requests; no local grant or file access."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, StrictStr

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding, params

NativeSaveMode = Literal["COPY_NEW", "SAVE_CURRENT", "SAVE_AS"]
OverwritePolicy = Literal["NO_CLOBBER", "NATIVE_NEW_EXPECTED", "NATIVE_REPLACE_EXPECTED"]
PERMISSIONS = ("INSPECT_SCENE", "SAVE_PROJECT", "ACCESS_EXTERNAL_FILES", "NATIVE_SAVE_EFFECTS")
TOOL_DATA = (
    ("project.native_save_preview", "Preview an explicitly authorized stock native save with exact source/path/overwrite facts; not a passive read or completed save.", True),
    ("project.native_save_start", "Accept the identical preview as a bounded native-save/reopen job; native callbacks and saved files can persist after cancellation.", True),
)


def load_definitions():
    from ..tool_registry import remote_tool

    return tuple(remote_tool(name, description=description, modifying=modifying,
                             required_permissions=PERMISSIONS)
                 for name, description, modifying in TOOL_DATA)


class NativeSaveTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def native_save_preview(
        self,
        mode: NativeSaveMode,
        filepath: Annotated[StrictStr, Field(min_length=1, max_length=4096)],
        overwrite_policy: OverwritePolicy,
    ) -> Any:
        """Preview COPY_NEW/SAVE_CURRENT/SAVE_AS under locally armed Native Save Effects plus inspect/save/external-file grants. Exact absolute .blend path in Blender's Approved Project Folder, including SAVE_CURRENT. Preview performs bounded native inspection/retains intent and is modifying; it is not a passive capture or save. Finite profile: supported local Scene/Object/mesh/rig/layered Action/material forms, an empty native sequencer with ordered public channels, and at most four already-loaded packed clean RGBA FILE images, each dimension <=4096, <=16,777,216 aggregate pixels/80MiB packed bytes; saved files <=256MiB. Above 1,048,576 aggregate pixels, fresh Linux 8GiB available-memory/2GiB free-disk observations are required; these are admission checks, not reservations or process bounds. Strict protected scope, dirty/generated images, broader dependencies and unsupported schemas refuse. No source packing or reload. Native callbacks/catalog/history effects may affect paths beyond the project folder under the distinct local session permission; this call cannot arm it. Returns exact expiring source/path/overwrite/loss facts. Old project.save remains unavailable. Exact 0.9.0 candidate installed/native qualification remains pending; full artist delivery is open."""
        return await self.registry.call("project.native_save_preview", params(
            mode=mode, filepath=filepath, overwrite_policy=overwrite_policy))

    async def native_save_start(
        self,
        preview_id: Annotated[StrictStr, Field(pattern=r"^native_save_[a-f0-9]{32}$")],
        expected_fingerprint: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")],
        mode: NativeSaveMode,
        filepath: Annotated[StrictStr, Field(min_length=1, max_length=4096)],
        overwrite_policy: OverwritePolicy,
        accepted_losses: Annotated[list[Annotated[StrictStr, Field(max_length=1024)]],
                                   Field(max_length=129, strict=True)],
        time_limit_seconds: Annotated[StrictInt, Field(ge=1, le=300)] = 120,
    ) -> Any:
        """Consume one exact current preview, repeating all facts and accepted_losses verbatim; poll jobs.inspect/list and keep the owner connection until terminal. COPY_NEW uses NO_CLOBBER final publication. Native current-file/SaveAs modes require NATIVE_DESTINATION_RACE_NOT_EXCLUDED: their final native overwrite is not atomic compare-and-swap, even after path/hash checks. Native Save may flush/synchronize state, run callbacks/catalog writes and change the active filepath in SAVE_AS; it cannot be preempted. Stop/revoke/disconnect/deadline prevents later actions but never promises rollback or removal of written files. Source changes stop success/publication without restoring manual work. A fresh worker reads only owned hashed output with autoexec disabled; success verifies the declared projection, not arbitrary hidden/UI state, appearance, current edited-pixel packing, full portable delivery or 1.0. Inspect external_effects.native_save, known artifacts, backup/staging and unknown callback inventory on every terminal outcome. This tool cannot arm/renew local permission or alter the approved project folder."""
        return await self.registry.call("project.native_save_start", params(
            preview_id=preview_id, expected_fingerprint=expected_fingerprint, mode=mode,
            filepath=filepath, overwrite_policy=overwrite_policy, accepted_losses=accepted_losses,
            time_limit_seconds=time_limit_seconds))

    def bindings(self):
        return (
            MCPToolBinding("project.native_save_preview", self.native_save_preview,
                           self.native_save_preview.__doc__ or ""),
            MCPToolBinding("project.native_save_start", self.native_save_start,
                           self.native_save_start.__doc__ or ""),
        )
