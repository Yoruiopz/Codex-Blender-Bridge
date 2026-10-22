"""Typed cooperative 4K snapshot/recovery jobs; no Blender imports."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictBool

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding
from .image_portability import Name
from .image_recovery import Fingerprint

TimeLimit = Annotated[float, Field(strict=True, ge=1., le=300., allow_inf_nan=False)]
TOOL_DATA = (
    ("image.snapshot_job_start", "Accept an owner-bound cooperative CURRENT_PIXELS raw snapshot, up to 4096 x 4096; native capture/commit block, poll completion.", True, ("INSPECT_SCENE", "EDIT_MATERIALS")),
    ("image.recovery_job_preview", "Preview exact 4K original-ID recovery fingerprint, loaded-vs-packed mode and consumer scope; private channel validation follows in the job.", False, ("INSPECT_SCENE",)),
    ("image.restore_snapshot_job_start", "Accept current-fingerprint cooperative 4K snapshot recovery; unloaded FILE reconstruction additionally confirms packed replacement.", True, ("INSPECT_SCENE", "EDIT_MATERIALS")),
)
DESTRUCTIVE_TOOL_NAMES = frozenset({"image.restore_snapshot_job_start"})


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="materials", description=description,
        modifying=modifying, required_permissions=permissions)
        for name, description, modifying, permissions in TOOL_DATA)


class ImageRecoveryJobTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def image_snapshot_job_start(self, image_name: Name, new_name: Name,
                                       time_limit_seconds: TimeLimit = 300.) -> Any:
        """Accept one shared owner-bound image job for a unique CURRENT_PIXELS raw EXR snapshot of an already-loaded local unanimated FILE/GENERATED image, up to 4096 x 4096 RGBA pixels and 288 MiB packed payload. Require INSPECT_SCENE+EDIT_MATERIALS, Object Mode and live ACCESS_EXTERNAL_FILES for a FILE source. Freeze complete actual channels without reading its backing file; a missing file does not discard an already-loaded buffer. Full native capture/hash at acceptance can block. Start-response acceptance is not snapshot completion; keep owner connection alive and poll jobs.inspect. Private finite/byte-channel validation and encoding run cooperatively only after start delivery. One native checkpointed pack/decode/readback publishes an exact original-ID-referencing, fake-user-retained Non-Color/CHANNEL_PACKED recovery Image. It is raw storage, not automatically equivalent shader binding. New incoming consumers stop further output writes. Original channels/roles/packed bytes/bindings must verify unchanged; staleness preserves newer manual work. Native tails and full arrays are not interruptible/out-of-core/memory reservations; cleanup releases private work, and late errors can retain a partial new Image with recovery_evidence. No external file write or automatic project save. A source buffer, private array, retained undo step or fake-user flag alone is not a backup: save packed snapshot explicitly for durability."""
        return await self.registry.call("image.snapshot_job_start", {"image_name": image_name,
            "new_name": new_name, "time_limit_seconds": time_limit_seconds})

    async def image_recovery_job_preview(self, image_name: Name, snapshot_name: Name,
                                         allow_shared: StrictBool = False) -> Any:
        """Read-only preview of a retained CURRENT_PIXELS snapshot and exact original Image ID for up to 4096 x 4096 recovery. Require INSPECT_SCENE and live FILE-target ACCESS_EXTERNAL_FILES; no edit grant. Validate complete bounded packed bytes/metadata/owner ID and freeze process/native identities, current target roles/storage/loaded pixels/old packed hash plus all bounded direct-consumer identities. Native full capture/hash can block; no external reload or Image mutation occurs. Return fresh expected_target_fingerprint and mode LOADED_BUFFER (pixel write preserving existing packed bytes) or PACKED_RECONSTRUCTION (unloaded FILE buffer reconstruction intentionally replaces packed bytes and requires confirm_replace_packed_bytes). Raw channel/canonical-layout validation completes cooperatively inside the job; snapshot_pixels_verified=false is intentional, and preview alone does not certify restoration. Reject resized/changed-role/same-name replacement targets, linked direct consumers, unsupported unloaded associated float color and incomplete scope. More than one consumer reference requires allow_shared=true. The direct list is not universal transitive preservation proof. Fingerprint expires on any measured change/restart. Nothing is saved."""
        return await self.registry.call("image.recovery_job_preview", {"image_name": image_name,
            "snapshot_name": snapshot_name, "allow_shared": allow_shared})

    async def image_restore_snapshot_job_start(self, image_name: Name, snapshot_name: Name,
                                               expected_target_fingerprint: Fingerprint,
                                               confirm_replace_packed_bytes: StrictBool = False,
                                               allow_shared: StrictBool = False,
                                               time_limit_seconds: TimeLimit = 300.) -> Any:
        """Accept owner-bound recovery using the complete current image.recovery_job_preview fingerprint and identical sharing scope. Require INSPECT_SCENE+EDIT_MATERIALS, Object Mode and live FILE-target ACCESS_EXTERNAL_FILES; one shared image job and a 1-300 second job deadline. Freeze actual packed snapshot bytes/target proof, then defer canonical raw decode, full finite/representable-byte validation and optional reconstruction encoding until start-response delivery. Poll jobs.inspect for terminal result; acceptance is not a restored image. LOADED_BUFFER restores all raw channels to the same loaded float/byte Image ID, preserving its packed bytes. PACKED_RECONSTRUCTION requires confirm_replace_packed_bytes=true and restores an unloaded FILE using new packed PNG8/raw EXR, preserving ID/path/color/alpha roles/bindings. Unsupported associated float conversion is refused. Recheck complete frozen snapshot, current target pixels/payload/scope after native checkpoint and immediately before publication; newer manual work/stale identities are never silently replaced. Native pack/decode/write/readback tails are non-preemptible, full arrays consume memory, and undo history is not a durable backup. Late cancel/revocation/native errors retain exact original/snapshot and truthful recovery_evidence; no blind compensating write, external reload/file output or automatic save. Explicitly save packed bytes for durable recovery. At most 4096 x 4096 pixels and 288 MiB; Windows, constrained-memory, crash and full artist acceptance remain open."""
        return await self.registry.call("image.restore_snapshot_job_start", {"image_name": image_name,
            "snapshot_name": snapshot_name, "expected_target_fingerprint": expected_target_fingerprint,
            "confirm_replace_packed_bytes": confirm_replace_packed_bytes, "allow_shared": allow_shared,
            "time_limit_seconds": time_limit_seconds})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in (
            ("image.snapshot_job_start", self.image_snapshot_job_start),
            ("image.recovery_job_preview", self.image_recovery_job_preview),
            ("image.restore_snapshot_job_start", self.image_restore_snapshot_job_start)))
