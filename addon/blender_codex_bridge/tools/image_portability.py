"""Explicit packed versions and bounded, identity-preserving raw pixel recovery.

FILE_BYTES and CURRENT_PIXELS deliberately have different contracts. A packed
raw snapshot is durable only after a separately authorized project save. These
synchronous foundations do not claim 4K, unloaded-target or native-undo support.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import struct
import sys
from array import array
from collections.abc import Callable, Mapping
from contextlib import suppress
from itertools import islice
from typing import Any

from .. import pixel_codecs
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import bool_param, reject_unknown_params, require_blender
from . import image_masks, image_paint, images
from . import pixel_brush as brush

LOGGER = logging.getLogger(__name__)
METADATA_KEY = "_codex_bridge_packed_version_v1"
OWNER_KEY = "_codex_bridge_snapshot_original"
MAX_PIXELS = brush.MAX_SYNC_PIXELS
MAX_BYTES = 20 * 1024 * 1024
MAX_USERS = 100
REQUIRED = (Permission.EDIT_MATERIALS,)
_BYTE_SCALE = array("f", [1. / 255.])[0]
_BYTE_CHANNEL_BITS = frozenset(struct.pack("<f", index * _BYTE_SCALE) for index in range(256))


def _gate(context: Any, image: Any | None = None, *, extra_permissions: tuple = ()) -> None:
    base = (*REQUIRED, *extra_permissions)
    required = (*base, Permission.ACCESS_EXTERNAL_FILES) if image is not None and image.source == "FILE" else base
    context.require(*required)
    images._check(context)
    # Permission providers and cancellation callbacks may change Blender state.
    # The last provider must precede every callback-free state/scope check.
    file_source = image is not None and image.source == "FILE"
    required = (*base, Permission.ACCESS_EXTERNAL_FILES) if file_source else base
    context.require(*required)
    if image is not None and (image.source == "FILE") != file_source:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Image source changed while checking live recovery permissions.")
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    flags = context.state.snapshot()
    if flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Image recovery is emergency-stopped.")
    if flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Image recovery is paused.")
    images._object_mode(require_blender())


def _local(image: Any) -> None:
    if (not images.local_editable(image) or image.source not in {"FILE", "GENERATED"}
            or getattr(image, "is_multiview", False)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Packed versions/recovery support local editable single-view FILE/GENERATED images only.")
    image_masks.unanimated(image)


def _metadata(image: Any) -> dict:
    summary = images._summary(image)
    if summary["filepath_truncated"]:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recovery requires complete bounded image metadata.")
    return {key: value for key, value in summary.items() if key != "users"}


def _buffer(context: Any, image: Any) -> tuple[array, int, int]:
    _gate(context, image)
    _local(image)
    if not image.has_data:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recovery requires an already-loaded target/snapshot; no external reload or buffer allocation is implied.")
    width, height = brush.size(*(int(value) for value in image.size), maximum_pixels=MAX_PIXELS)
    if image.channels != 4 or len(image.pixels) != width * height * 4:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Packed versions/recovery require a complete four-channel RGBA buffer.")
    values = array("f", [0.]) * (width * height * 4)
    _gate(context, image)
    image.pixels.foreach_get(values)
    _gate(context, image)
    if any(not math.isfinite(value) for value in values):
        raise invalid_argument("Recovery requires finite raw channels; NaN/infinite input is refused.")
    return values, width, height


def _packed(image: Any) -> bytes:
    packed = image.packed_file
    if packed is None or not 1 <= packed.size <= MAX_BYTES:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "A complete packed payload within the synchronous byte budget is required.")
    payload = bytes(packed.data)
    if len(payload) != packed.size:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Packed payload length changed during inspection.")
    return payload


def _file_bytes(context: Any, image: Any) -> tuple[bytes, dict, str]:
    source = images.source_reference(context, image)
    path, proof = images._source_file(context, str(source.path), source=source)
    if proof["file_bytes"] > MAX_BYTES:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "File-byte packing exceeds its synchronous 20 MiB budget; no partial version is allocated.")
    data = bytearray()
    source.check(context)
    try:
        with path.open("rb") as stream:
            while True:
                _gate(context, image)
                source.check(context)
                block = stream.read(min(65536, MAX_BYTES + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > MAX_BYTES:
                    raise invalid_argument("Texture grew beyond the bounded packing byte budget.")
    except OSError as exc:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Approved FILE_BYTES source could not be read; no version allocated.") from exc
    source.check(context)
    checked_path, checked_proof = images._source_file(context, str(source.path), source=source)
    if (checked_path != path or checked_proof != proof or len(data) != proof["file_bytes"]
            or hashlib.sha256(data).hexdigest() != proof["file_sha256"]):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Source bytes changed while preparing FILE_BYTES; no packed version allocated.")
    return bytes(data), {key: value for key, value in proof.items() if not key.startswith("_")}, str(path)


def _cleanup(context: Any, bpy: Any, image: Any | None, *, owned_fake: bool = False) -> tuple[bool, bool]:
    if image is None:
        return True, False
    try:
        context.require(Permission.DELETE_OBJECTS)
        _gate(context, extra_permissions=(Permission.DELETE_OBJECTS,))
    except BridgeError as error:
        if error.code == ErrorCode.PERMISSION_DENIED.value:
            return False, True
        raise
    # The fake-user flag was created by this operation. Never unlink real users.
    if bool(image.use_fake_user) != owned_fake or image.users != int(owned_fake):
        return False, False
    image.use_fake_user = False
    bpy.data.images.remove(image, do_unlink=False)
    return True, False


def _owned_version(context: Any, bpy: Any, image: Any, source: Any, name: str, *, owned_fake=False) -> None:
    """Callbacks must not turn a new private version into a protected consumer."""
    _gate(context, source)
    images._object_mode(bpy)
    if (bpy.data.images.get(name) != image or not images.local_editable(image)
            or bool(image.use_fake_user) != owned_fake or image.users != int(owned_fake)
            or bpy.data.user_map(subset={image}).get(image, ())):
        raise BridgeError(ErrorCode.OPERATION_FAILED,
                          "New packed version acquired changed ownership/consumers; further writes are refused.")


def pack_version(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "new_name", "mode"})
    source_name, name = images._name(params, "image_name"), images._name(params, "new_name")
    mode = params.get("mode")
    if not isinstance(mode, str) or mode not in {"FILE_BYTES", "CURRENT_PIXELS"}:
        raise invalid_argument("Choose FILE_BYTES or CURRENT_PIXELS explicitly; they are not equivalent backups.")
    _gate(context)
    bpy = require_blender()
    images._object_mode(bpy)
    source = images.image_exact(bpy, source_name)
    _gate(context, source)
    _local(source)
    if bpy.data.images.get(name) is not None:
        raise invalid_argument("The packed-version name already exists; overwrite/reuse/automatic rename is forbidden.")
    if mode == "FILE_BYTES":
        values, width, height, source_file = image_paint._read(context, source, modifying=True, maximum_pixels=MAX_PIXELS)
    else:
        # CURRENT_PIXELS reads only the already-loaded buffer. A vanished or
        # changed external file must not prevent preserving these current bits.
        # Live FILE consent remains required; no external-source proof is claimed.
        values, width, height = _buffer(context, source)
        source_file = None
    image_paint.source_role(source)
    original_identity, original_metadata = image_masks.identity(source), _metadata(source)
    original_digest = brush.digest(values)
    if mode == "FILE_BYTES":
        if source.source != "FILE":
            raise invalid_argument("FILE_BYTES requires an explicit approved FILE source; generated/current pixels are a separate mode.")
        payload, source_file, filepath = _file_bytes(context, source)
        colorspace, alpha_mode = source.colorspace_settings.name, source.alpha_mode
    else:
        parts = []
        total = 0
        for step in pixel_codecs.encode_steps(values, width, height, "EXR32_RAW", "DATA", check=lambda: _gate(context, source)):
            total += len(step.data)
            if total > MAX_BYTES:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Raw snapshot exceeds its synchronous byte budget.")
            parts.append(step.data)
        payload = b"".join(parts)
        filepath = "//.codex-bridge-packed/" + hashlib.sha256(name.encode("utf-8")).hexdigest() + ".exr"
        colorspace, alpha_mode = "Non-Color", "CHANNEL_PACKED"
    _gate(context, source)
    if image_masks.identity(source) != original_identity or _metadata(source) != original_metadata:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Original image changed while preparing a packed version.")
    new = None
    created_image_name = None
    owned_fake = False
    try:
        _gate(context, source)
        images._object_mode(bpy)
        if bpy.data.images.get(name) is not None:
            raise invalid_argument("Packed-version name became occupied before allocation.")
        new = bpy.data.images.new(name, width, height, alpha=True, float_buffer=True)
        created_image_name = new.name
        _owned_version(context, bpy, new, source, name)
        new.source = "FILE"
        _owned_version(context, bpy, new, source, name)
        new.filepath = filepath
        _owned_version(context, bpy, new, source, name)
        new.colorspace_settings.name = colorspace
        _owned_version(context, bpy, new, source, name)
        new.alpha_mode = alpha_mode
        _owned_version(context, bpy, new, source, name)
        new.pack(data=payload, data_len=len(payload))
        _owned_version(context, bpy, new, source, name)
        if new.name != name or _packed(new) != payload:
            raise RuntimeError("New packed bytes/name did not match the explicit version")
        # These getters explicitly decode only this operation's packed memory.
        # No native filepath reload is requested, including synthetic // paths.
        actual = array("f", [0.]) * (width * height * 4)
        if tuple(new.size) != (width, height) or new.channels != 4 or len(new.pixels) != len(actual):
            raise RuntimeError("Packed version failed complete bounded native decode")
        new.pixels.foreach_get(actual)
        current_pixels_verified = mode == "CURRENT_PIXELS" and brush.digest(actual) == original_digest
        if mode == "CURRENT_PIXELS" and not current_pixels_verified:
            raise RuntimeError("Raw packed snapshot did not preserve every original float channel")
        if mode == "FILE_BYTES":
            retained, w, h, _ = image_paint._read(context, source, modifying=True, maximum_pixels=MAX_PIXELS)
        else:
            retained, w, h = _buffer(context, source)
        if (brush.digest(retained) != original_digest or (w, h) != (width, height)
                or image_masks.identity(source) != original_identity or _metadata(source) != original_metadata):
            raise RuntimeError("Original image changed during packed-version allocation")
        metadata = {"schema_version": 1, "mode": mode, "width": width, "height": height,
                    "source": source.source, "colorspace": source.colorspace_settings.name,
                    "alpha_mode": source.alpha_mode, "is_float": bool(source.is_float),
                    "pixels_sha256_float32_le": original_digest,
                    "packed_sha256": hashlib.sha256(payload).hexdigest()}
        _owned_version(context, bpy, new, source, name)
        new[METADATA_KEY] = json.dumps(metadata, separators=(",", ":"), sort_keys=True)
        _owned_version(context, bpy, new, source, name)
        new[OWNER_KEY] = source
        _owned_version(context, bpy, new, source, name)
        new.use_fake_user = True  # Explicit retention; packed bytes, not this flag, preserve pixels.
        owned_fake = True
        _owned_version(context, bpy, new, source, name, owned_fake=True)
        if new.name != name or not images.local_editable(new) or _packed(new) != payload:
            raise RuntimeError("Packed version identity/name/bytes changed before success")
        original_check = array("f", [0.]) * len(values)
        source.pixels.foreach_get(original_check)
        if (brush.digest(original_check) != original_digest or image_masks.identity(source) != original_identity
                or _metadata(source) != original_metadata):
            raise RuntimeError("Original image changed at the final packed-version permission boundary")
        return {"created": True, "mode": mode, "image": images._summary(new), "original_image": source.name,
                "packed_bytes": len(payload), "packed_sha256": metadata["packed_sha256"],
                "source_pixels_sha256_float32_le": original_digest,
                "packed_version_pixels_sha256_float32_le": brush.digest(actual),
                "current_pixels_verified": current_pixels_verified, "original_pixels_unchanged": True,
                "source_file_at_read": source_file, "retained_with_fake_user": True,
                "raw_snapshot_storage": mode == "CURRENT_PIXELS", "bound_to_nodes": False,
                "project_saved": False, "external_file_written": False, "verification_required": True,
                "durability": "Packed payload and original-ID reference persist only after an explicit approved project save; native undo/crash/Windows/4K acceptance is not established."}
    except Exception as exc:
        LOGGER.exception("Packed-version creation failed; attempting only owned, independently consented cleanup")
        removed, denied = False, False
        if new is not None:
            # Retain last observed owned handle name, never a guessed source name.
            with suppress(ReferenceError):
                created_image_name = new.name
        try:
            removed, denied = _cleanup(context, bpy, new, owned_fake=owned_fake)
        except Exception:
            LOGGER.exception("Owned packed-version cleanup failed")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Packed-version creation failed; inspect retained image and original state.",
                          {"execution_started": new is not None, "requested_image": name,
                           "retained_image_name": None if removed else created_image_name,
                           "retained_name_is_last_observed": not removed and created_image_name is not None,
                           "rollback_verified": removed, "possible_mutation": not removed,
                           "cleanup_permission_denied": denied, "verification_required": True}) from exc


def _snapshot(snapshot: Any, target: Any) -> dict:
    raw = snapshot.get(METADATA_KEY)
    if not isinstance(raw, str):
        raise invalid_argument("Snapshot metadata is missing or exceeds its bounded versioned contract.")
    try:
        raw_size = len(raw.encode("utf-8"))
    except UnicodeError as exc:
        raise invalid_argument("Snapshot metadata must be valid bounded UTF-8.") from exc
    if raw_size > 4096:
        raise invalid_argument("Snapshot metadata is missing or exceeds its bounded versioned contract.")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate snapshot metadata key")
            result[key] = value
        return result
    try:
        metadata = json.loads(raw, object_pairs_hook=unique_pairs)
    except (ValueError, TypeError, RecursionError) as exc:
        raise invalid_argument("Snapshot metadata is not valid JSON.") from exc
    fields = {"schema_version", "mode", "width", "height", "source", "colorspace", "alpha_mode", "is_float",
              "pixels_sha256_float32_le", "packed_sha256"}
    if (not isinstance(metadata, dict) or set(metadata) != fields or type(metadata["schema_version"]) is not int
            or metadata["schema_version"] != 1 or metadata["mode"] != "CURRENT_PIXELS"
            or snapshot.get(OWNER_KEY) != target):
        raise invalid_argument("Recovery requires a CURRENT_PIXELS snapshot referencing this exact original image ID.")
    for key in ("pixels_sha256_float32_le", "packed_sha256"):
        value = metadata[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise invalid_argument("Snapshot digest metadata is invalid.")
    if type(metadata["is_float"]) is not bool or any(type(metadata[key]) is not int for key in ("width", "height")):
        raise invalid_argument("Snapshot dimensions/storage metadata is invalid.")
    brush.size(metadata["width"], metadata["height"], maximum_pixels=MAX_PIXELS)
    if (snapshot.source != "FILE" or snapshot.colorspace_settings.name != "Non-Color"
            or snapshot.alpha_mode != "CHANNEL_PACKED"):
        raise invalid_argument("Snapshot raw float storage/interpretation changed; no restoration attempted.")
    if hashlib.sha256(_packed(snapshot)).hexdigest() != metadata["packed_sha256"]:
        raise invalid_argument("Snapshot packed bytes changed; no restoration attempted.")
    return metadata


def _snapshot_buffer(context: Any, snapshot: Any, metadata: dict, *, check: Callable[[], None] | None = None) -> array:
    """Decode only our exact canonical packed layout, with no native/file getter.

    A .blend's custom properties are untrusted. Passing arbitrary packed bytes
    to native Image getters could fall back to a filepath; canonical in-memory
    parsing avoids granting such a reload through recovery.
    """
    check = check or (lambda: _gate(context))
    payload = _packed(snapshot)
    width, height = metadata["width"], metadata["height"]
    header = pixel_codecs.exr_header(width, height, "EXR32_RAW", "DATA")
    start, stride = len(header) + height * 8, 8 + width * 16
    if payload[:len(header)] != header or len(payload) != start + height * stride:
        raise invalid_argument("Snapshot is not the complete canonical raw EXR layout.")
    offsets = struct.unpack_from("<" + "Q" * height, payload, len(header))
    if any(offset != start + index * stride for index, offset in enumerate(offsets)):
        raise invalid_argument("Snapshot scanline offsets changed.")
    values = array("f", [0.]) * (width * height * 4)
    for row, offset in enumerate(offsets):
        check()
        if struct.unpack_from("<ii", payload, offset) != (row, width * 16):
            raise invalid_argument("Snapshot scanline coordinates/length changed.")
        for plane, channel in enumerate((3, 2, 1, 0)):
            channels = array("f")
            begin = offset + 8 + plane * width * 4
            channels.frombytes(payload[begin:begin + width * 4])
            if sys.byteorder != "little":
                channels.byteswap()
            target = (height - 1 - row) * width * 4 + channel
            values[target:target + width * 4:4] = channels
    check()
    if any(not math.isfinite(value) for value in values) or brush.digest(values) != metadata["pixels_sha256_float32_le"]:
        raise invalid_argument("Snapshot complete decoded channels do not match their raw digest.")
    return values


def _storage_values(context: Any, values: array, *, is_float: bool, check: Callable[[], None] | None = None) -> None:
    """Refuse lossy byte writes before touching the original's ImBuf.

    Native byte getters use float32(byte * float32(1/255)), which differs by a
    bit from Python's mathematical byte/255 for some channels. Snapshot metadata
    is untrusted: a matching digest alone does not prove byte representability.
    """
    if is_float:
        return
    check = check or (lambda: _gate(context))
    for index, value in enumerate(values):
        if index % 4096 == 0:
            check()
        if struct.pack("<f", value) not in _BYTE_CHANNEL_BITS:
            raise invalid_argument("Snapshot channels are not exact native byte-buffer values; lossy recovery is refused before writing.")


def _scope(bpy: Any, target: Any, snapshot: Any, allow_shared: bool) -> dict:
    if target.users > MAX_USERS:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recovery target exceeds the bounded direct-consumer window.")
    owners = list(islice(bpy.data.user_map(subset={target}).get(target, ()), MAX_USERS + 1))
    if len(owners) > MAX_USERS:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recovery cannot act on truncated direct-consumer evidence.")
    consumers = [owner for owner in owners if owner != snapshot]
    if any(not images.local_editable(owner) for owner in consumers):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recovery would affect linked/override/read-only consumers.")
    # The known snapshot ID-property reference is an intentional extra user.
    other_references = max(0, target.users - 1 - int(bool(target.use_fake_user)))
    if other_references > 1 and not allow_shared:
        raise invalid_argument("Image recovery affects all its consumers; inspect and explicitly acknowledge allow_shared=true.",
                               reference_count=other_references)
    direct = sorted(({"name": owner.name, "type": owner.bl_rna.identifier} for owner in consumers),
                    key=lambda value: (value["type"], value["name"]))
    return {"direct_consumers": direct, "reference_count_excluding_snapshot": other_references,
            "allow_shared": allow_shared, "indirect_users_possible": True,
            "scope": "All consumers of this exact image ID; direct list is not a complete transitive scene graph."}


def restore_pixels(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "snapshot_name", "allow_shared"})
    name, snapshot_name = images._name(params, "image_name"), images._name(params, "snapshot_name")
    allow_shared = bool_param(params, "allow_shared", False)
    _gate(context)
    bpy = require_blender()
    images._object_mode(bpy)
    target, snapshot = images.image_exact(bpy, name), images.image_exact(bpy, snapshot_name)
    if target == snapshot:
        raise invalid_argument("The snapshot and original target must be distinct image IDs.")
    _gate(context, target)
    _local(target)
    _local(snapshot)
    if not target.has_data:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Durable restore currently requires an already-loaded original; missing/unloaded identity recovery remains open.")
    image_paint.source_role(target)
    metadata = _snapshot(snapshot, target)
    before, width, height = _buffer(context, target)
    values = _snapshot_buffer(context, snapshot, metadata)
    _storage_values(context, values, is_float=bool(target.is_float))
    if ((width, height) != (metadata["width"], metadata["height"])
            or target.source != metadata["source"] or target.colorspace_settings.name != metadata["colorspace"]
            or target.alpha_mode != metadata["alpha_mode"] or bool(target.is_float) != metadata["is_float"]
            or brush.digest(values) != metadata["pixels_sha256_float32_le"]):
        raise invalid_argument("Target dimensions/storage/role or complete snapshot pixels changed; no restoration attempted.")
    identity, before_metadata = image_masks.identity(target), _metadata(target)
    packed_before = hashlib.sha256(_packed(target)).hexdigest() if target.packed_file is not None else None
    snapshot_identity = image_masks.identity(snapshot)
    ownership = _scope(bpy, target, snapshot, allow_shared)
    started = False
    try:
        _gate(context, target)
        images._object_mode(bpy)
        if (_metadata(target) != before_metadata or image_masks.identity(target) != identity
                or image_masks.identity(snapshot) != snapshot_identity or _snapshot(snapshot, target) != metadata
                or _scope(bpy, target, snapshot, allow_shared) != ownership):
            raise RuntimeError("Target/snapshot/context changed before the pixel publication boundary")
        # Cancellation callbacks can mutate the frozen input; compare complete
        # snapshots again before touching the original. No user buffer is deleted.
        checked = _snapshot_buffer(context, snapshot, metadata)
        if brush.digest(checked) != metadata["pixels_sha256_float32_le"]:
            raise RuntimeError("Snapshot pixels changed before restoration")
        _gate(context, target)
        # This is the final gate callback before mutation. Recheck immutable
        # snapshot bytes/owner and target scope afterwards, so revocation or
        # context changes observed by that callback cannot use stale evidence.
        if (_metadata(target) != before_metadata or image_masks.identity(target) != identity
                or _snapshot(snapshot, target) != metadata
                or _scope(bpy, target, snapshot, allow_shared) != ownership):
            raise RuntimeError("Restoration inputs changed at the final permission boundary")
        # Callbacks above can interleave manual edits without changing an
        # already-dirty flag. Compare every current target channel after the
        # last callback; this native read and the following write do not yield.
        publication_before = array("f", [0.]) * len(before)
        target.pixels.foreach_get(publication_before)
        if brush.digest(publication_before) != brush.digest(before):
            raise RuntimeError("Original pixels changed before restoration; newer work is preserved")
        started = True
        target.pixels.foreach_set(values)
        target.update()
        _gate(context, target)
        actual, aw, ah = _buffer(context, target)
        # Dirty state is expected after pixel publication; all other native
        # metadata, packed payload, ID and consumers must remain unchanged.
        after_metadata = _metadata(target)
        before_metadata.pop("is_dirty", None)
        after_metadata.pop("is_dirty", None)
        packed_after = hashlib.sha256(_packed(target)).hexdigest() if target.packed_file is not None else None
        if ((aw, ah) != (width, height) or brush.digest(actual) != metadata["pixels_sha256_float32_le"]
                or image_masks.identity(target) != identity or before_metadata != after_metadata
                or _scope(bpy, target, snapshot, allow_shared) != ownership or packed_before != packed_after):
            raise RuntimeError("Restored pixels/identity/consumer/metadata verification failed")
        return {"restored": True, "image_name": name, "snapshot_name": snapshot_name,
                "before_pixels_sha256_float32_le": brush.digest(before),
                "restored_pixels_sha256_float32_le": brush.digest(actual),
                "image_identity_preserved": True, "complete_pixels_verified": True,
                "ownership": ownership, "project_saved": False, "snapshot_retained": True,
                "file_written": False, "verification_required": True,
                "scope": "Loaded float or exact byte target, matching original ID/dimensions/roles; save explicitly for durability. Native undo, unloaded/4K/Windows recovery remain unaccepted."}
    except Exception as exc:
        LOGGER.exception("Pixel restoration failed; original/snapshot retained for inspection and confirmed recovery")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Pixel restoration did not complete; inspect the original and retained packed snapshot before retrying.",
                          {"execution_started": started, "possible_mutation": started,
                           "image_name": name, "snapshot_name": snapshot_name,
                           "snapshot_retained": True, "rollback_verified": False,
                           "verification_required": True}) from exc


def register_tools(registry: Any) -> None:
    registry.register("image.pack_version", pack_version, permissions=REQUIRED, toolset="materials", modifies=True,
                      description="Create an explicit packed FILE_BYTES version or exact raw CURRENT_PIXELS snapshot; <=1M pixels, no save or binding.")
    registry.register("image.restore_pixels", restore_pixels, permissions=REQUIRED, toolset="materials", modifies=True,
                      description="Restore a retained CURRENT_PIXELS snapshot into its exact loaded float/byte original image ID, preserving consumers; <=1M pixels.")
