"""Explicit unloaded FILE image reconstruction; no Blender imports."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictBool, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding
from .image_portability import Name

Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
TOOL_DATA = (
    ("image.recovery_preview", "Preview exact unloaded FILE image identity, packed replacement and complete bounded consumers; <=1M pixels.", False, ("INSPECT_SCENE",)),
    ("image.restore_packed_snapshot", "Confirm current preview and reconstruct an unloaded original FILE Image ID by replacing packed bytes; <=1M pixels.", True, ("INSPECT_SCENE", "EDIT_MATERIALS")),
)
DESTRUCTIVE_TOOL_NAMES = frozenset({"image.restore_packed_snapshot"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="materials", description=description,
        modifying=modifying, required_permissions=permissions)
        for name, description, modifying, permissions in TOOL_DATA)


class ImageRecoveryTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def image_recovery_preview(self, image_name: Name, snapshot_name: Name,
                                      allow_shared: StrictBool = False) -> Any:
        """Inspect an unloaded local unanimated original FILE image and its exact CURRENT_PIXELS snapshot without reading an external path or acquiring an unloaded ImBuf. Require INSPECT_SCENE and live FILE ACCESS_EXTERNAL_FILES; no edit permission is needed for preview. Validate <=1,048,576 pixels/20MiB canonical packed snapshot bytes and every raw channel, native original-ID relationship, exact session identities/roles/packed payload and bounded local consumers. Review complete replacement PNG8/raw EXR size/hash and fresh expected_target_fingerprint. sRGB/linear/Non-Color BYTE straight/channel-packed or FLOAT Non-Color / linear CHANNEL_PACKED only; associated float color is refused. Preview explicitly proposes replacing any old packed bytes and reconstructing storage from snapshot metadata; it cannot observe a missing before-buffer. No source read, file output, implicit reload, datablock allocation, pixel write or project save. Multiple consumer references require allow_shared=true. Fingerprints expire on restart or any measured input change."""
        return await self.registry.call("image.recovery_preview", {"image_name": image_name,
            "snapshot_name": snapshot_name, "allow_shared": allow_shared})

    async def image_restore_packed_snapshot(self, image_name: Name, snapshot_name: Name,
                                            expected_target_fingerprint: Fingerprint,
                                            confirm_replace_packed_bytes: StrictBool = False,
                                            allow_shared: StrictBool = False) -> Any:
        """Confirm the current image.recovery_preview using its exact fingerprint, identical sharing scope and confirm_replace_packed_bytes=true. Require INSPECT_SCENE+EDIT_MATERIALS, live FILE ACCESS_EXTERNAL_FILES, Object Mode and unpaused/non-stopped state. Reconstruct the already-existing unloaded original FILE Image ID from its retained raw snapshot, intentionally replacing packed bytes; native ID/path/color/alpha roles and consumers stay preserved. This is separate from image.restore_pixels, which changes only an already-loaded buffer and preserves its packed bytes. Complete native pixel readback verifies reconstruction before success. Native pack/decode is synchronous and non-preemptible; late cancellation/permission/native errors may leave a changed target and always retain target/snapshot with truthful possible_mutation, no automatic compensation. No external source reload/file write/new Image ID/project save; explicitly save to persist the new packed bytes. <=1M pixels/20MiB; 4K/UI undo/Windows/crash/production acceptance remain open."""
        return await self.registry.call("image.restore_packed_snapshot", {"image_name": image_name,
            "snapshot_name": snapshot_name, "expected_target_fingerprint": expected_target_fingerprint,
            "confirm_replace_packed_bytes": confirm_replace_packed_bytes, "allow_shared": allow_shared})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding("image.recovery_preview", self.image_recovery_preview, self.image_recovery_preview.__doc__ or ""),
            MCPToolBinding("image.restore_packed_snapshot", self.image_restore_packed_snapshot, self.image_restore_packed_snapshot.__doc__ or ""),
        )
