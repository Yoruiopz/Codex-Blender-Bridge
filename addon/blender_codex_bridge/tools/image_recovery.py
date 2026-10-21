"""Explicit packed-payload reconstruction of an unloaded original FILE image.

The target Image ID survives. Its old packed payload is intentionally replaced;
this is separate from restore_pixels' loaded-buffer/unchanged-payload contract.
No native getter may acquire an ImBuf until the new verified payload is present.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from array import array
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import bool_param, reject_unknown_params, require_blender
from . import image_masks, images
from . import image_portability as storage
from . import pixel_brush as brush

LOGGER = logging.getLogger(__name__)
READ = (Permission.INSPECT_SCENE,)
WRITE = (*READ, Permission.EDIT_MATERIALS)
SESSION_NONCE = secrets.token_hex(16)


def _gate(context: Any, target: Any | None = None, *, modifying=False) -> None:
    required = WRITE if modifying else READ
    context.require(*required)
    if target is not None and target.source == "FILE":
        context.require(Permission.ACCESS_EXTERNAL_FILES)
    if context.check_cancelled:
        context.check_cancelled()
    # Final providers run before callback-free lifetime/state/mode checks and
    # the caller's identity/metadata/consumer proof at the write boundary.
    file_source = target is not None and target.source == "FILE"
    context.require(*required, *((Permission.ACCESS_EXTERNAL_FILES,) if file_source else ()))
    if target is not None and (target.source == "FILE") != file_source:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Image source changed while checking live reconstruction permissions.")
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    if modifying:
        flags = context.state.snapshot()
        if flags.get("emergency_stopped"):
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Image recovery is emergency-stopped.")
        if flags.get("paused"):
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Image recovery is paused.")
    images._object_mode(require_blender())


def _unsupported(message: str) -> None:
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, message)


def _stable(metadata: dict) -> dict:
    return {key: value for key, value in metadata.items()
            if key not in {"has_data", "loaded_size", "is_dirty", "is_float", "packed"}}


def _proof(bpy: Any, target: Any, snapshot: Any, allow_shared: bool) -> tuple[dict, dict]:
    images._object_mode(bpy)
    storage._local(target)
    storage._local(snapshot)
    if target == snapshot or target.source != "FILE" or target.has_data:
        _unsupported("Packed reconstruction requires an unloaded exact original FILE image; loaded-buffer restoration is a separate tool.")
    metadata = storage._snapshot(snapshot, target)
    before = storage._metadata(target)  # has_data=false guards size/is_float getters.
    if (metadata["source"] != "FILE" or metadata["colorspace"] != before["colorspace"]
            or metadata["alpha_mode"] != before["alpha_mode"]):
        raise invalid_argument("Original source/color/alpha roles no longer match the retained snapshot.")
    if metadata["is_float"]:
        if not ((before["colorspace"] == "Non-Color" and before["alpha_mode"] in {"STRAIGHT", "CHANNEL_PACKED"})
                or (before["colorspace"] == "Linear Rec.709" and before["alpha_mode"] == "CHANNEL_PACKED")):
            _unsupported("Unloaded float reconstruction currently supports Non-Color or explicitly CHANNEL_PACKED linear roles; associated color conversion is not guessed.")
        format, role, srgb = "EXR32_RAW", "DATA", False
    else:
        if before["colorspace"] not in {"sRGB", "Linear Rec.709", "Non-Color"} or before["alpha_mode"] not in {"STRAIGHT", "CHANNEL_PACKED"}:
            _unsupported("Unloaded byte reconstruction supports reviewed sRGB/linear/Non-Color and straight/channel-packed roles only.")
        format, role, srgb = "PNG8", "COLOR" if before["colorspace"] == "sRGB" else "DATA", before["colorspace"] == "sRGB"
    owners = storage._scope(bpy, target, snapshot, allow_shared)
    # Include native identities and individual reference counts, not only names.
    consumers = sorted(((*image_masks.identity(owner), owner.name, owner.bl_rna.identifier,
                         int(owner.users), bool(owner.use_fake_user))
                        for owner in bpy.data.user_map(subset={target}).get(target, ())), key=repr)
    previous = storage._packed(target) if target.packed_file is not None else None
    record = {"session": SESSION_NONCE, "target_identity": image_masks.identity(target),
        "snapshot_identity": image_masks.identity(snapshot), "target": before,
        "snapshot_metadata": metadata, "consumers": consumers, "scope": owners,
        "previous_packed_sha256": hashlib.sha256(previous).hexdigest() if previous is not None else None,
        "previous_packed_bytes": len(previous) if previous is not None else 0,
        "replacement_format": format, "replacement_role": role, "replacement_srgb": srgb}
    return record, metadata


def _fingerprint(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _prepare(context: Any, params: Mapping[str, Any], *, modifying=False):
    _gate(context, modifying=modifying)
    bpy = require_blender()
    target = images.image_exact(bpy, images._name(params, "image_name"))
    snapshot = images.image_exact(bpy, images._name(params, "snapshot_name"))
    shared = bool_param(params, "allow_shared", False)
    _gate(context, target, modifying=modifying)
    record, metadata = _proof(bpy, target, snapshot, shared)
    def check() -> None:
        _gate(context, target, modifying=modifying)
    values = storage._snapshot_buffer(context, snapshot, metadata, check=check)
    storage._storage_values(context, values, is_float=metadata["is_float"], check=check)
    parts, total = [], 0
    for step in storage.pixel_codecs.encode_steps(values, metadata["width"], metadata["height"],
            record["replacement_format"], record["replacement_role"], srgb=record["replacement_srgb"], check=check):
        total += len(step.data)
        if total > storage.MAX_BYTES:
            _unsupported("Packed reconstruction exceeds the synchronous 20 MiB payload budget.")
        parts.append(step.data)
    check()
    current, _ = _proof(bpy, target, snapshot, shared)
    if current != record:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Recovery preview inputs changed while validating complete snapshot bytes.")
    payload = b"".join(parts)
    return bpy, target, snapshot, shared, record, metadata, values, payload


def recovery_preview(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "snapshot_name", "allow_shared"})
    _, target, snapshot, _, record, metadata, _, payload = _prepare(context, params)
    return {"expected_target_fingerprint": _fingerprint(record), "image_name": target.name,
        "snapshot_name": snapshot.name, "target_has_data": False, "scope": record["scope"],
        "previous_packed_sha256": record["previous_packed_sha256"],
        "previous_packed_bytes": record["previous_packed_bytes"],
        "replacement_packed_sha256": hashlib.sha256(payload).hexdigest(), "replacement_packed_bytes": len(payload),
        "replacement_format": record["replacement_format"], "reconstructed_size": [metadata["width"], metadata["height"]],
        "reconstructed_is_float": metadata["is_float"], "source_file_read": False,
        "file_written": False, "project_saved": False, "mutation_performed": False,
        "requires_confirm_replace_packed_bytes": True,
        "scope_note": "Reconstruct the unloaded original buffer from its retained snapshot, intentionally replacing packed bytes; no before-buffer/storage observation or external reload is implied."}


def restore_packed_snapshot(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "snapshot_name", "allow_shared",
        "expected_target_fingerprint", "confirm_replace_packed_bytes"})
    if not bool_param(params, "confirm_replace_packed_bytes", False):
        raise invalid_argument("Explicit confirm_replace_packed_bytes=true is required for packed reconstruction.")
    expected = params.get("expected_target_fingerprint")
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise invalid_argument("Use the complete current recovery_preview fingerprint.")
    bpy, target, snapshot, shared, record, metadata, values, payload = _prepare(context, params, modifying=True)
    if _fingerprint(record) != expected:
        raise invalid_argument("Recovery preview is stale; current image identity, payload, role or consumer scope changed.")
    started = False
    try:
        _gate(context, target, modifying=True)
        current, _ = _proof(bpy, target, snapshot, shared)
        if current != record:
            raise RuntimeError("Recovery inputs changed at the final publication boundary")
        started = True
        target.pack(data=payload, data_len=len(payload))
        _gate(context, target, modifying=True)
        # Check packed bytes before any getter that can acquire/decode an ImBuf.
        if (image_masks.identity(target) != tuple(record["target_identity"])
                or storage._packed(target) != payload
                or storage._snapshot(snapshot, target) != metadata
                or _stable(storage._metadata(target)) != _stable(record["target"])
                or storage._scope(bpy, target, snapshot, shared) != record["scope"]):
            raise RuntimeError("Packed reconstruction changed identity, roles, payload or consumers")
        actual = array("f", [0.]) * len(values)
        if tuple(target.size) != (metadata["width"], metadata["height"]) or target.channels != 4 or len(target.pixels) != len(actual):
            raise RuntimeError("Reconstructed native buffer has an unexpected shape")
        target.pixels.foreach_get(actual)
        _gate(context, target, modifying=True)
        if (image_masks.identity(target) != tuple(record["target_identity"])
                or storage._packed(target) != payload
                or _stable(storage._metadata(target)) != _stable(record["target"])
                or storage._scope(bpy, target, snapshot, shared) != record["scope"]
                or storage._snapshot(snapshot, target) != metadata):
            raise RuntimeError("Reconstructed image changed at the final verification permission boundary")
        # Final callback may have changed pixels on an already-loaded target.
        # Reacquire the complete current channels without another callback.
        target.pixels.foreach_get(actual)
        if (brush.digest(actual) != metadata["pixels_sha256_float32_le"]
                or bool(target.is_float) != metadata["is_float"]
                or storage._packed(target) != payload
                or _stable(storage._metadata(target)) != _stable(record["target"])
                or storage._scope(bpy, target, snapshot, shared) != record["scope"]
                or storage._snapshot(snapshot, target) != metadata):
            raise RuntimeError("Complete reconstructed pixels/storage/roles/consumers did not verify")
        return {"restored": True, "image_name": target.name, "snapshot_name": snapshot.name,
            "image_identity_preserved": True, "complete_pixels_verified": True,
            "pixels_sha256_float32_le": brush.digest(actual), "packed_payload_replaced": True,
            "previous_packed_sha256": record["previous_packed_sha256"],
            "packed_sha256": hashlib.sha256(payload).hexdigest(), "packed_bytes": len(payload),
            "reconstructed_size": [metadata["width"], metadata["height"]], "is_float": bool(target.is_float),
            "scope": record["scope"], "snapshot_retained": True,
            "source_file_read": False, "file_written": False, "project_saved": False,
            "native_operation_interruptible": False, "verification_required": True,
            "durability": "The replacement is in memory; save explicitly to persist it. Native undo, crash, 4K, Windows and production recovery remain unaccepted."}
    except Exception as exc:
        LOGGER.exception("Packed reconstruction failed; exact original and snapshot retained")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Packed reconstruction did not complete; inspect retained image and snapshot before retrying.",
            {"execution_started": started, "possible_mutation": started,
             "image_name": params["image_name"], "snapshot_name": params["snapshot_name"],
             "snapshot_retained": True, "packed_payload_may_have_changed": started,
             "rollback_verified": False, "verification_required": True}) from exc


def register_tools(registry: Any) -> None:
    registry.register("image.recovery_preview", recovery_preview, permissions=READ, toolset="materials", modifies=False,
        description="Preview exact unloaded FILE recovery identity, packed-payload replacement and consumers; <=1M pixels, no external reload.")
    registry.register("image.restore_packed_snapshot", restore_packed_snapshot, permissions=WRITE, toolset="materials", modifies=True,
        description="Confirm current preview and reconstruct the unloaded original FILE Image ID by replacing its packed payload; <=1M pixels.")
