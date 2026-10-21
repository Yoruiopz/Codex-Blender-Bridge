"""Typed packed-image versions and explicit raw input recovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, StrictBool, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding


def _name(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 for char in value) or len(value.encode("utf-8")) > 63:
        raise ValueError("Image names must be nonblank, control-free and at most 63 UTF-8 bytes")
    return value


Name = Annotated[StrictStr, Field(min_length=1, max_length=63), AfterValidator(_name)]
TOOL_DATA = (
    ("image.pack_version", "Create a distinct packed FILE_BYTES version or exact raw CURRENT_PIXELS snapshot, <=1M pixels; no save/binding.", True, ("EDIT_MATERIALS",)),
    ("image.restore_pixels", "Restore a retained raw snapshot to its exact loaded float/byte original image ID, preserving consumers; <=1M pixels.", True, ("EDIT_MATERIALS",)),
)


class ImagePortabilityTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def image_pack_version(self, image_name: Name, new_name: Name,
                                 mode: Literal["FILE_BYTES", "CURRENT_PIXELS"]) -> Any:
        """Object Mode: create a unique retained packed image, <=1,048,576 pixels and 20 MiB. Explicit FILE_BYTES embeds complete approved original FILE bytes; dirty source pixels are NOT preserved by that mode. CURRENT_PIXELS encodes every actual raw float32 RGBA channel as a separate Non-Color/CHANNEL_PACKED raw EXR snapshot, retaining the original Image ID reference and interpretation for recovery. It is recovery storage, not an automatically equivalent shader binding. Original buffers/metadata/bindings remain unchanged; reference counts increase by the new original-ID pointer. EDIT_MATERIALS required; FILE reads also require live ACCESS_EXTERNAL_FILES and approved stored-source checks. No path output, source overwrite, node binding, .blend save or implicit save grant. Packed bytes become persistent only after separately authorized project.save. Owned allocation cleanup requires DELETE_OBJECTS; denied cleanup reports retained image/possible mutation. Native copies/packing/decode are synchronous; 4K, UI undo, missing-target, Windows and production acceptance remain open."""
        return await self.registry.call("image.pack_version", {"image_name": image_name, "new_name": new_name, "mode": mode})

    async def image_restore_pixels(self, image_name: Name, snapshot_name: Name, allow_shared: StrictBool = False) -> Any:
        """Object Mode: restore a CURRENT_PIXELS snapshot into its exact original Image ID, never a same-name replacement. <=1,048,576 pixels, local unanimated already-loaded FLOAT or BYTE target with unchanged dimensions/source/color/alpha role. Snapshot's persistent original-ID pointer, complete packed bytes/layout, raw channel digest and bounded consumers are validated before the pixel write. Raw packed bytes are parsed in memory without implicit filepath reload; byte values must exactly match native normalized channels; lossy byte writes and unloaded/resized targets are refused. All image consumers receive the restored pixels; multiple references require explicit allow_shared=true and linked/override/read-only direct consumers block mutation. EDIT_MATERIALS required; FILE targets also need live ACCESS_EXTERNAL_FILES, but restoration never reads an external path. Full readback verifies bits/identity/metadata/consumer scope. Failure may follow a pixel write: both target and snapshot are retained, with possible_mutation and verification_required. Snapshot remains retained; no binding, file write or project save. Native undo/crash/4K/Windows recovery remains unaccepted; save explicitly for durable restored pixels."""
        return await self.registry.call("image.restore_pixels", {"image_name": image_name, "snapshot_name": snapshot_name,
                                                               "allow_shared": allow_shared})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods: tuple[Callable[..., Any], ...] = (self.image_pack_version, self.image_restore_pixels)
        return tuple(MCPToolBinding(data[0], method, method.__doc__ or "") for data, method in zip(TOOL_DATA, methods, strict=True))


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="materials", description=description, modifying=modifies,
                             required_permissions=permissions) for name, description, modifies, permissions in TOOL_DATA)
