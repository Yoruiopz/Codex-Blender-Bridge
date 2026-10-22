"""One-owner cooperative raw snapshots and exact original-image recovery.

Private encoding/validation yields; full native pixel capture, pack, decode and
publication do not. Full arrays remain in memory, never a substitute for saved
packed snapshots. The shared image-job scheduler owns lifetime and undo/history.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from array import array
from collections.abc import Mapping
from typing import Any

from .. import pixel_codecs
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import bool_param, reject_unknown_params, require_blender
from . import image_masks, image_paint, image_recovery, images
from . import image_portability as storage
from . import pixel_brush as brush

MAX_PIXELS = brush.MAX_PIXELS
MAX_BYTES = 288 * 1024 * 1024
QUANTUM = 4096
READ = (Permission.INSPECT_SCENE,)
WRITE = (*READ, Permission.EDIT_MATERIALS)
SNAPSHOT_METHOD = "image.snapshot_job_start"
RESTORE_METHOD = "image.restore_snapshot_job_start"


def _gate(context: Any, image: Any | None = None, *, modifying=True) -> None:
    image_recovery._gate(context, image, modifying=modifying)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _packed_hash(image: Any) -> str | None:
    return hashlib.sha256(storage._packed(image, maximum_bytes=MAX_BYTES)).hexdigest() if image.packed_file is not None else None


def _read_current(image: Any) -> tuple[array, int, int]:
    """Callback-free native capture; caller gates and verifies identity/scope."""
    storage._local(image)
    if not image.has_data:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Current pixels require an already-loaded ordinary buffer; no external reload is implied.")
    image_paint.source_role(image)
    width, height = brush.size(*(int(x) for x in image.size), maximum_pixels=MAX_PIXELS)
    if image.channels != 4 or len(image.pixels) != width*height*4:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recovery jobs require a complete ordinary four-channel RGBA buffer.")
    values = array("f", [0.]) * (width*height*4)
    image.pixels.foreach_get(values)
    return values, width, height


def _read_verified_packed(image: Any, payload: bytes) -> tuple[array, int, int]:
    """Explicitly decode only a complete already-verified native packed input."""
    if storage._packed(image, maximum_bytes=MAX_BYTES) != payload:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Packed image changed before its explicit native decode.")
    # Unlike arbitrary or unloaded external files, this exact payload was
    # encoded/validated privately. No cancellation/provider callback intervenes.
    tuple(image.size)
    return _read_current(image)


def _source_record(image: Any, values: array, width: int, height: int) -> dict:
    return {"identity": image_masks.identity(image), "metadata": storage._metadata(image),
        "width": width, "height": height, "pixels_sha256_float32_le": brush.digest(values),
        "packed_sha256": _packed_hash(image)}


def prepare_snapshot(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "new_name"})
    _gate(context)
    bpy = require_blender()
    source = images.image_exact(bpy, images._name(params, "image_name"))
    name = images._name(params, "new_name")
    _gate(context, source)
    if bpy.data.images.get(name) is not None:
        raise invalid_argument("Snapshot names never overwrite/reuse existing image IDs.")
    values, width, height = _read_current(source)
    record = _source_record(source, values, width, height)
    _gate(context, source)
    current, w, h = _read_current(source)
    if _source_record(source, current, w, h) != record:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Current source changed while freezing the snapshot job.")
    return {"source": source, "source_name": source.name, "name": name, "values": values,
        "width": width, "height": height, "source_record": record,
        "requires_external_files": source.source == "FILE", "method": SNAPSHOT_METHOD,
        "kind": "image.current_pixels_snapshot", "driver_type": SnapshotDriver,
        "workload": _workload(width, height, "CURRENT_PIXELS_SNAPSHOT")}


def _workload(width: int, height: int, mode: str) -> dict:
    pixel_bytes = width*height*16
    return {"image_size": [width, height], "mode": mode, "raw_pixel_bytes": pixel_bytes,
        "private_pixel_and_payload_peak_estimate_bytes": 4*pixel_bytes+MAX_BYTES+262144,
        "estimate_excludes": "Blender/native/GPU/undo buffers, graph/ID wrappers and allocator overhead; not a memory reservation or cap",
        "native_capture_and_publication_interruptible": False,
        "large_image_requires_job": width*height > storage.MAX_PIXELS}


def _proof(bpy: Any, target: Any, snapshot: Any, shared: bool) -> tuple[dict, dict, bytes]:
    images._object_mode(bpy)
    storage._local(target)
    storage._local(snapshot)
    if target == snapshot:
        raise invalid_argument("The original target and retained snapshot must be distinct exact image IDs.")
    metadata = storage._snapshot(snapshot, target, maximum_pixels=MAX_PIXELS, maximum_bytes=MAX_BYTES)
    payload = storage._packed(snapshot, maximum_bytes=MAX_BYTES)
    target_metadata = storage._metadata(target)
    if any(target_metadata[field] != metadata[key] for field, key in
           (("source", "source"), ("colorspace", "colorspace"), ("alpha_mode", "alpha_mode"))):
        raise invalid_argument("Original source/color/alpha roles no longer match the retained snapshot.")
    if target.has_data:
        values, width, height = _read_current(target)
        if (width, height) != (metadata["width"], metadata["height"]) or bool(target.is_float) != metadata["is_float"]:
            raise invalid_argument("Loaded original dimensions/storage no longer match the retained snapshot.")
        before_digest = brush.digest(values)
        mode, format, role, srgb = "LOADED_BUFFER", None, None, False
    else:
        if target.source != "FILE":
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Unloaded reconstruction requires an original FILE image; GENERATED must already have an explicitly allocated buffer.")
        before_digest = None
        mode = "PACKED_RECONSTRUCTION"
        space, alpha = target_metadata["colorspace"], target_metadata["alpha_mode"]
        if metadata["is_float"]:
            if not ((space == "Non-Color" and alpha in {"STRAIGHT", "CHANNEL_PACKED"})
                    or (space == "Linear Rec.709" and alpha == "CHANNEL_PACKED")):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Unloaded associated float color reconstruction remains unsupported; no alpha conversion is guessed.")
            format, role, srgb = "EXR32_RAW", "DATA", False
        else:
            if space not in {"sRGB", "Linear Rec.709", "Non-Color"} or alpha not in {"STRAIGHT", "CHANNEL_PACKED"}:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Unloaded byte reconstruction requires reviewed color/alpha roles.")
            format, role, srgb = "PNG8", "COLOR" if space == "sRGB" else "DATA", space == "sRGB"
    scope = storage._scope(bpy, target, snapshot, shared)
    owners = sorted(((*image_masks.identity(owner), owner.name, owner.bl_rna.identifier,
        int(owner.users), bool(owner.use_fake_user)) for owner in bpy.data.user_map(subset={target}).get(target, ())), key=repr)
    record = {"session": image_recovery.SESSION_NONCE, "target_identity": image_masks.identity(target),
        "snapshot_identity": image_masks.identity(snapshot), "target": target_metadata,
        "snapshot_metadata": metadata, "snapshot_native_metadata": storage._metadata(snapshot),
        "before_pixels_sha256_float32_le": before_digest, "previous_packed_sha256": _packed_hash(target),
        "scope": scope, "consumers": owners, "mode": mode, "format": format, "role": role, "srgb": srgb}
    return record, metadata, payload


def _restore_inputs(context: Any, params: Mapping[str, Any], *, modifying=False):
    _gate(context, modifying=modifying)
    bpy = require_blender()
    target = images.image_exact(bpy, images._name(params, "image_name"))
    snapshot = images.image_exact(bpy, images._name(params, "snapshot_name"))
    shared = bool_param(params, "allow_shared", False)
    _gate(context, target, modifying=modifying)
    record, metadata, payload = _proof(bpy, target, snapshot, shared)
    _gate(context, target, modifying=modifying)
    checked, _, _ = _proof(bpy, target, snapshot, shared)
    if checked != record:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Recovery preview changed while freezing complete original/snapshot evidence.")
    return bpy, target, snapshot, shared, record, metadata, payload


def recovery_job_preview(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "snapshot_name", "allow_shared"})
    _, target, snapshot, _, record, metadata, payload = _restore_inputs(context, params)
    return {"expected_target_fingerprint": _hash(record), "image_name": target.name, "snapshot_name": snapshot.name,
        "mode": record["mode"], "image_size": [metadata["width"], metadata["height"]],
        "scope": record["scope"], "previous_packed_sha256": record["previous_packed_sha256"],
        "snapshot_packed_sha256": metadata["packed_sha256"], "snapshot_packed_bytes": len(payload),
        "snapshot_pixels_verified": False, "complete_channel_validation_deferred_to_job": True,
        "requires_confirm_replace_packed_bytes": record["mode"] == "PACKED_RECONSTRUCTION",
        "native_capture_interruptible": False, "mutation_performed": False,
        "source_file_read": False, "file_written": False, "project_saved": False,
        "workload": _workload(metadata["width"], metadata["height"], record["mode"])}


def prepare_restore(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "snapshot_name", "allow_shared",
        "expected_target_fingerprint", "confirm_replace_packed_bytes"})
    _, target, snapshot, shared, record, metadata, payload = _restore_inputs(context, params, modifying=True)
    expected = params.get("expected_target_fingerprint")
    if not isinstance(expected, str) or len(expected) != 64 or _hash(record) != expected:
        raise invalid_argument("Use the complete current recovery_job_preview fingerprint; changed scope is never retargeted.")
    confirmed = bool_param(params, "confirm_replace_packed_bytes", False)
    if record["mode"] == "PACKED_RECONSTRUCTION" and not confirmed:
        raise invalid_argument("Unloaded recovery requires confirm_replace_packed_bytes=true from the explicit preview.")
    return {"source": snapshot, "source_name": snapshot.name, "name": target.name,
        "target": target, "snapshot": snapshot, "shared": shared, "record": record,
        "metadata": metadata, "payload": payload, "width": metadata["width"], "height": metadata["height"],
        "requires_external_files": target.source == "FILE", "method": RESTORE_METHOD,
        "kind": "image.restore_snapshot", "driver_type": RestoreDriver,
        "workload": _workload(metadata["width"], metadata["height"], record["mode"])}


def _validate_steps(values: array, *, is_float: bool, check):
    digest = hashlib.sha256()
    for start in range(0, len(values), QUANTUM):
        check()
        block = values[start:start+QUANTUM]
        if any(not math.isfinite(value) for value in block):
            raise invalid_argument("Every snapshot channel must be finite; no partial recovery is published.")
        if not is_float and any(struct.pack("<f", value) not in storage._BYTE_CHANNEL_BITS for value in block):
            raise invalid_argument("Snapshot channels are not exact native byte values; lossy recovery is refused.")
        if sys.byteorder != "little":
            block.byteswap()
        digest.update(block)
        yield {"phase": "validating_channels", "completed": min(start+QUANTUM, len(values)), "total": len(values)}
    return digest.hexdigest()


def _decode_steps(payload: bytes, metadata: dict, check):
    width, height = metadata["width"], metadata["height"]
    header = pixel_codecs.exr_header(width, height, "EXR32_RAW", "DATA")
    start, stride = len(header)+height*8, 8+width*16
    if payload[:len(header)] != header or len(payload) != start+height*stride:
        raise invalid_argument("Snapshot must contain the complete canonical raw EXR layout.")
    values = array("f", [0.]) * (width*height*4)
    for row in range(height):
        check()
        offset = start+row*stride
        if struct.unpack_from("<Q", payload, len(header)+row*8)[0] != offset or struct.unpack_from("<ii", payload, offset) != (row, width*16):
            raise invalid_argument("Snapshot row offsets/coordinates/length changed.")
        for plane, channel in enumerate((3, 2, 1, 0)):
            channels = array("f")
            begin = offset+8+plane*width*4
            channels.frombytes(payload[begin:begin+width*4])
            if sys.byteorder != "little":
                channels.byteswap()
            destination = (height-1-row)*width*4+channel
            values[destination:destination+width*4:4] = channels
        yield {"phase": "decoding_snapshot", "completed": row+1, "total": height}
    return values


class _Driver:
    def __init__(self, prepared: dict):
        self.prepared = prepared
        self.snapshot_name = prepared["source_name"] if prepared["method"] == RESTORE_METHOD else None
        self.snapshot_identity = image_masks.identity(prepared["source"]) if self.snapshot_name is not None else None
        self.recovery: dict[str, Any] = {"mode": prepared["workload"]["mode"], "snapshot_retained": self.snapshot_name is not None,
            "project_saved": False, "source_file_read": False, "packed_payload_replaced": False,
            "complete_pixels_verified": False}

    def evidence(self) -> dict:
        return {}  # Packed memory is never represented as a filesystem effect.

    def recovery_evidence(self) -> dict:
        result = dict(self.recovery)
        if self.snapshot_name is not None:
            current = require_blender().data.images.get(self.snapshot_name)
            result["snapshot_retained"] = current is not None and image_masks.identity(current) == self.snapshot_identity
            result["snapshot_name"] = self.snapshot_name
        return result

    def cleanup(self, context, job, *, success):
        return {}  # Private generators/arrays release through close()/prepared.clear().


class SnapshotDriver(_Driver):
    def __init__(self, prepared: dict):
        super().__init__(prepared)
        self.output = None
        self.output_identity = None
        self.owned_fake = False

    def _source(self, context):
        prepared = self.prepared
        _gate(context, prepared["source"])
        bpy = require_blender()
        source = images.image_exact(bpy, prepared["source_name"])
        values, width, height = _read_current(source)
        if _source_record(source, values, width, height) != prepared["source_record"]:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Frozen snapshot source changed; newer original work is preserved.")
        return source

    def _output_guard(self, context, source):
        _gate(context, source)
        bpy, image = require_blender(), self.output
        if (image is None or bpy.data.images.get(self.prepared["name"]) != image
                or image_masks.identity(image) != self.output_identity or not images.local_editable(image)
                or image.users != int(self.owned_fake) or bool(image.use_fake_user) != self.owned_fake
                or bpy.data.user_map(subset={image}).get(image, ())):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "New snapshot acquired changed identity/ownership/consumers; further writes are refused.")

    def _publish(self, context, job, payload, raw_digest):
        prepared, bpy = self.prepared, require_blender()
        source = self._source(context)  # Also after the manager's native checkpoint.
        if bpy.data.images.get(prepared["name"]) is not None:
            raise invalid_argument("The snapshot output name became occupied; no rename/overwrite is allowed.")
        job.execution_started = True
        self.output = bpy.data.images.new(prepared["name"], prepared["width"], prepared["height"], alpha=True, float_buffer=True)
        self.output_identity = image_masks.identity(self.output)
        self.recovery["retained_image_name"] = self.output.name
        self.recovery["possible_mutation"] = True
        for owner, attr, value in ((self.output, "source", "FILE"),
                (self.output, "filepath", ""),
                (self.output.colorspace_settings, "name", "Non-Color"), (self.output, "alpha_mode", "CHANNEL_PACKED")):
            self._output_guard(context, source)
            setattr(owner, attr, value)
        self._output_guard(context, source)
        self.output.pack(data=payload, data_len=len(payload))
        self.recovery.update(snapshot_name=self.output.name, packed_sha256=hashlib.sha256(payload).hexdigest(), packed_bytes=len(payload))
        for key, value in ((storage.METADATA_KEY, json.dumps({"schema_version": 1, "mode": "CURRENT_PIXELS",
                "width": prepared["width"], "height": prepared["height"], "source": prepared["source_record"]["metadata"]["source"],
                "colorspace": prepared["source_record"]["metadata"]["colorspace"], "alpha_mode": prepared["source_record"]["metadata"]["alpha_mode"],
                "is_float": prepared["source_record"]["metadata"]["is_float"], "pixels_sha256_float32_le": raw_digest,
                "packed_sha256": self.recovery["packed_sha256"]}, sort_keys=True, separators=(",", ":"))),
                (storage.OWNER_KEY, source)):
            self._output_guard(context, source)
            self.output[key] = value
        self._output_guard(context, source)
        self.output.use_fake_user = True
        self.owned_fake = True
        self._output_guard(context, source)
        if storage._packed(self.output, maximum_bytes=MAX_BYTES) != payload:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "New snapshot packed bytes changed before native readback.")
        actual, width, height = _read_verified_packed(self.output, payload)
        if (width, height, brush.digest(actual)) != (prepared["width"], prepared["height"], raw_digest):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Complete native snapshot channels did not verify.")
        self.snapshot_name, self.snapshot_identity = self.output.name, self.output_identity
        self.recovery["snapshot_retained"] = True
        self._output_guard(context, source)
        source_check, sw, sh = _read_current(source)
        if _source_record(source, source_check, sw, sh) != prepared["source_record"]:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Original changed at the final publication gate; retained snapshot contains earlier frozen pixels.")
        actual, _, _ = _read_verified_packed(self.output, payload)
        if brush.digest(actual) != raw_digest or storage._packed(self.output, maximum_bytes=MAX_BYTES) != payload:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Snapshot changed at the final permission boundary.")
        self.recovery.update(complete_pixels_verified=True, original_pixels_unchanged=True,
            pixels_sha256_float32_le=raw_digest)
        return {"created": True, "mode": "CURRENT_PIXELS", "image": images._summary(self.output),
            "original_image": source.name, "packed_bytes": len(payload), "packed_sha256": self.recovery["packed_sha256"],
            "pixels_sha256_float32_le": raw_digest, "current_pixels_verified": True,
            "original_pixels_unchanged": True, "retained_with_fake_user": True,
            "project_saved": False, "external_file_written": False, "source_file_at_read": None,
            "verification_required": True, "durability": "Packed memory becomes a durable backup only after separately authorized project.save."}

    def steps(self, context, job, native_commit):
        prepared = self.prepared
        def check():
            _gate(context, prepared["source"])
        raw_digest = yield from _validate_steps(prepared["values"], is_float=prepared["source_record"]["metadata"]["is_float"], check=check)
        if raw_digest != prepared["source_record"]["pixels_sha256_float32_le"]:
            raise invalid_argument("Private snapshot input changed before encoding.")
        parts, total = [], 0
        for step in pixel_codecs.encode_steps(prepared["values"], prepared["width"], prepared["height"], "EXR32_RAW", "DATA", check=check):
            total += len(step.data)
            if total > MAX_BYTES:
                raise invalid_argument("Raw snapshot exceeds its bounded job payload budget.")
            if step.data:
                parts.append(step.data)
            yield {"phase": "encoding_snapshot", "completed": step.pixels_completed, "total": step.pixels_total}
        payload = b"".join(parts)
        del parts
        yield {"phase": "awaiting_snapshot_publication", "completed": 1, "total": 1}
        return native_commit(lambda: self._publish(context, job, payload, raw_digest))


class RestoreDriver(_Driver):
    def _current(self, context):
        prepared = self.prepared
        _gate(context, prepared["target"])
        bpy = require_blender()
        target = images.image_exact(bpy, prepared["name"])
        snapshot = images.image_exact(bpy, prepared["source_name"])
        record, _, _ = _proof(bpy, target, snapshot, prepared["shared"])
        if record != prepared["record"]:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Recovery input/current original changed; newer work is preserved.")
        return target, snapshot

    def _publish(self, context, job, values, payload):
        prepared = self.prepared
        target, snapshot = self._current(context)
        metadata, record = prepared["metadata"], prepared["record"]
        job.execution_started = True
        self.recovery.update(image_name=target.name, snapshot_name=snapshot.name, possible_mutation=True)
        if record["mode"] == "LOADED_BUFFER":
            target.pixels.foreach_set(values)
            target.update()
        else:
            target.pack(data=payload, data_len=len(payload))
            self.recovery["packed_payload_replaced"] = True
        _gate(context, target)
        expected_packed = hashlib.sha256(payload).hexdigest() if record["mode"] == "PACKED_RECONSTRUCTION" else record["previous_packed_sha256"]
        if (image_masks.identity(target) != tuple(record["target_identity"])
                or storage._snapshot(snapshot, target, maximum_pixels=MAX_PIXELS, maximum_bytes=MAX_BYTES) != metadata
                or _packed_hash(target) != expected_packed
                or image_recovery._stable(storage._metadata(target)) != image_recovery._stable(record["target"])
                or storage._scope(require_blender(), target, snapshot, prepared["shared"]) != record["scope"]):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Restored original identity/roles/packed bytes/consumers changed.")
        if record["mode"] == "PACKED_RECONSTRUCTION":
            actual, width, height = _read_verified_packed(target, payload)
        else:
            actual, width, height = _read_current(target)
        _gate(context, target)
        if (_packed_hash(target) != expected_packed
                or image_masks.identity(target) != tuple(record["target_identity"])
                or image_recovery._stable(storage._metadata(target)) != image_recovery._stable(record["target"])
                or storage._scope(require_blender(), target, snapshot, prepared["shared"]) != record["scope"]
                or storage._snapshot(snapshot, target, maximum_pixels=MAX_PIXELS, maximum_bytes=MAX_BYTES) != metadata):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Original changed at the final recovery permission boundary.")
        actual, width, height = _read_current(target)
        if ((width, height, brush.digest(actual)) != (metadata["width"], metadata["height"], metadata["pixels_sha256_float32_le"])
                or bool(target.is_float) != metadata["is_float"]):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Complete restored native channels did not match their raw snapshot digest.")
        self.recovery.update(complete_pixels_verified=True, pixels_sha256_float32_le=brush.digest(actual),
            packed_sha256=expected_packed, previous_packed_sha256=record["previous_packed_sha256"])
        return {"restored": True, "image_name": target.name, "snapshot_name": snapshot.name,
            "mode": record["mode"], "image_identity_preserved": True, "complete_pixels_verified": True,
            "pixels_sha256_float32_le": brush.digest(actual), "snapshot_retained": True,
            "packed_payload_replaced": self.recovery["packed_payload_replaced"], "packed_sha256": expected_packed,
            "project_saved": False, "file_written": False, "source_file_read": False,
            "verification_required": True, "durability": "Native undo is not a pixel backup; separately save packed restoration/snapshot for durability."}

    def steps(self, context, job, native_commit):
        prepared = self.prepared
        def check():
            _gate(context, prepared["target"])
        values = yield from _decode_steps(prepared["payload"], prepared["metadata"], check)
        raw_digest = yield from _validate_steps(values, is_float=prepared["metadata"]["is_float"], check=check)
        if raw_digest != prepared["metadata"]["pixels_sha256_float32_le"]:
            raise invalid_argument("Complete decoded snapshot channels do not match the retained digest.")
        payload = None
        record = prepared["record"]
        if record["mode"] == "PACKED_RECONSTRUCTION":
            parts, total = [], 0
            for step in pixel_codecs.encode_steps(values, prepared["width"], prepared["height"], record["format"], record["role"], srgb=record["srgb"], check=check):
                total += len(step.data)
                if total > MAX_BYTES:
                    raise invalid_argument("Reconstructed packed payload exceeds the bounded job budget.")
                if step.data:
                    parts.append(step.data)
                yield {"phase": "encoding_reconstruction", "completed": step.pixels_completed, "total": step.pixels_total}
            payload = b"".join(parts)
            del parts
        yield {"phase": "awaiting_recovery_publication", "completed": 1, "total": 1}
        return native_commit(lambda: self._publish(context, job, values, payload))


def _manager(context):
    if context.jobs is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The shared image-job scheduler is unavailable.")
    return context.jobs


def snapshot_job_start(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "new_name", "time_limit_seconds"})
    return _manager(context).start_recovery_driver(context,
        {key: value for key, value in params.items() if key != "time_limit_seconds"},
        params.get("time_limit_seconds", 300.), snapshot=True)


def restore_snapshot_job_start(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "snapshot_name", "allow_shared", "expected_target_fingerprint",
        "confirm_replace_packed_bytes", "time_limit_seconds"})
    return _manager(context).start_recovery_driver(context,
        {key: value for key, value in params.items() if key != "time_limit_seconds"},
        params.get("time_limit_seconds", 300.), snapshot=False)


def register_tools(registry: Any) -> None:
    registry.register(SNAPSHOT_METHOD, snapshot_job_start, permissions=WRITE, toolset="materials", modifies=True,
        automatic_checkpoint=False, batchable=False,
        description="Accept an owner-bound cooperative CURRENT_PIXELS raw snapshot job, up to 4096 x 4096; poll terminal evidence and save explicitly for durability.")
    registry.register("image.recovery_job_preview", recovery_job_preview, permissions=READ, toolset="materials", modifies=False,
        description="Preview bounded4K original-ID snapshot recovery, exact current scope/hash and loaded-vs-packed mode; validation completes privately in the job.")
    registry.register(RESTORE_METHOD, restore_snapshot_job_start, permissions=WRITE, toolset="materials", modifies=True,
        automatic_checkpoint=False, batchable=False,
        description="Accept confirmed current-scope cooperative raw snapshot recovery, up to 4096 x 4096; native publication is non-preemptible, poll terminal evidence.")
