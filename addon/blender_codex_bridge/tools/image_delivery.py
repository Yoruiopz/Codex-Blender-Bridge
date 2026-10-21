"""Typed frozen-source texture export, no-clobber publication and verified reimport."""

from __future__ import annotations

from array import array
from collections.abc import Mapping
from typing import Any

from .. import pixel_codecs, texture_verification
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..image_files import preflight_steps
from ..texture_staging import REQUIRED, TextureStaging, approved_output
from ..utils import reject_unknown_params, require_blender
from . import image_masks, image_paint, images
from . import pixel_brush as brush


def _metadata(image: Any) -> dict:
    result = images._summary(image)
    if result["filepath_truncated"]:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Export needs complete bounded source metadata.")
    return {key: value for key, value in result.items() if key != "users"}


def prepare_export(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "new_name", "filepath", "format"})
    source_name, name = images._name(params, "image_name"), images._name(params, "new_name")
    format = params.get("format")
    if not isinstance(format, str) or format not in pixel_codecs.FORMATS:
        raise invalid_argument("Choose PNG8, PNG16, EXR32 or EXR32_RAW explicitly.")
    context.require(*REQUIRED)
    images._check(context)
    bpy = require_blender()
    images._object_mode(bpy)
    source = images.image_exact(bpy, source_name)
    images.binding_source(context, source)
    role, srgb = image_paint.source_role(source)
    layout = pixel_codecs.interpretation(format, role)
    root = images._root()
    context.require(*REQUIRED)
    _folder, path = approved_output(params.get("filepath"), root, layout["extension"])
    try:
        path.lstat()
    except FileNotFoundError:
        pass
    else:
        raise invalid_argument("Texture output already exists; overwrite and automatic rename are forbidden.")
    if bpy.data.images.get(name) is not None:
        raise invalid_argument("Reimport image name already exists; overwrite and automatic rename are forbidden.")
    spaces = {item.identifier for item in bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"].enum_items}
    if layout["colorspace"] not in spaces:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The export's reviewed reimport color space is unavailable.")
    values, width, height, file = image_paint._read(context, source, modifying=True)
    return {"source": source, "source_name": source_name, "name": name, "width": width, "height": height,
            "values": values, "source_digest": brush.digest(values), "source_file": file,
            "role": role, "srgb": srgb, "associated": image_paint.source_associated(source),
            "format": format, "layout": layout, "filepath": str(path), "approved_root": root,
            "source_identity": image_masks.identity(source), "source_metadata": _metadata(source)}


class ExportDriver:
    """Domain state only; the shared scheduler owns lifetime/ticks/history/checkpoints."""

    def __init__(self, prepared: dict):
        self.prepared = prepared
        self.staging: TextureStaging | None = None
        self.last_image_name: str | None = None
        self.image_identity: tuple | None = None
        self.image_metadata: dict | None = None
        self.native_digest: str | None = None
        self.native_verified = False
        self.pixels_verified = False
        self.cleanup_evidence: dict = {}

    def _check(self, context):
        context.require(*REQUIRED)
        images._check(context)
        if images._root() != self.prepared["approved_root"]:
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Approved texture folder changed during export; reinspect retained effects.")
        context.require(*REQUIRED)

    def _source(self, context):
        self._check(context)
        bpy = require_blender()
        images._object_mode(bpy)
        prepared = self.prepared
        source = images.image_exact(bpy, prepared["source_name"])
        if image_masks.identity(source) != prepared["source_identity"] or _metadata(source) != prepared["source_metadata"]:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Export source identity or metadata changed.", {"stale_source": True})
        image_paint.source_role(source)
        values, width, height, file = image_paint._read(context, source, modifying=True)
        if (width, height, file, brush.digest(values)) != (prepared["width"], prepared["height"], prepared["source_file"], prepared["source_digest"]):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Export source pixels or approved file changed.", {"stale_source": True})
        self._check(context)

    def _name_available(self):
        if require_blender().data.images.get(self.prepared["name"]) is not None:
            raise invalid_argument("The reimport image name is now occupied; no implicit rename is allowed.")

    def _read_native(self, context):
        self._check(context)
        image = images.image_exact(require_blender(), self.last_image_name)
        prepared = self.prepared
        if ((self.image_identity is not None and image_masks.identity(image) != self.image_identity)
                or (self.image_metadata is not None and _metadata(image) != self.image_metadata)):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Reimported image identity/metadata changed; retained for explicit recovery.")
        if (not image.has_data or image.source != "FILE" or image.channels != 4
                or tuple(image.size) != (prepared["width"], prepared["height"])
                or len(image.pixels) != prepared["width"]*prepared["height"]*4):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Reimported image lacks its complete reviewed native buffer.")
        values = array("f", [0])*len(image.pixels)
        self._check(context)
        image.pixels.foreach_get(values)
        self._check(context)
        return values

    def _reimport(self, context, job):
        self._source(context)  # Again AFTER the manager created the native checkpoint.
        self._name_available()
        self._check(context)
        prepared, layout = self.prepared, self.prepared["layout"]
        job.execution_started = True
        try:
            loaded = images.load_image(context, {"filepath": prepared["filepath"], "new_name": prepared["name"],
                "colorspace": layout["colorspace"], "alpha_mode": layout["reopen_alpha_mode"]})
        except BridgeError as error:
            self.last_image_name = error.context.get("retained_image_name")
            raise
        self.last_image_name = loaded["image"]["name"]
        image = images.image_exact(require_blender(), self.last_image_name)
        self.image_identity, self.image_metadata = image_masks.identity(image), _metadata(image)
        values = self._read_native(context)
        self.native_digest = brush.digest(values)
        self.native_verified = True
        return values, loaded["image"]

    def _file_steps(self, context):
        self._check(context)
        path, proof = yield from preflight_steps(self.prepared["filepath"], self.prepared["approved_root"], check=lambda: self._check(context))
        evidence = self.staging.evidence()
        if (str(path) != self.prepared["filepath"] or proof["file_sha256"] != evidence["file_sha256"]
                or proof["file_bytes"] != evidence["file_bytes"] or proof["_identity"] != self.staging.stage_id):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Published texture no longer matches this job's sealed source stream.")
        return {key: value for key, value in proof.items() if not key.startswith("_")}

    def steps(self, context, job, native_commit):
        prepared = self.prepared
        self._check(context)
        yield from texture_verification.normalize_steps(prepared["values"], associated=prepared["associated"], check=lambda: self._check(context))
        self.staging = TextureStaging(context, prepared["filepath"], images._root, prepared["format"], prepared["role"])
        yield from self.staging.encode_steps(prepared["values"], prepared["width"], prepared["height"], srgb=prepared["srgb"])
        self._source(context)
        self._name_available()
        self._check(context)
        self.staging.publish()
        yield {"phase": "file_published", "completed": 1, "total": 1}
        yield from self.staging.verify_published_steps()
        proof = yield from self._file_steps(context)
        self._source(context)
        self._name_available()
        native, image_summary = native_commit(lambda: self._reimport(context, job))
        verification = yield from texture_verification.compare_steps(prepared["values"], native, prepared["format"], prepared["role"],
                                                                     srgb=prepared["srgb"], check=lambda: self._check(context))
        del native
        self.pixels_verified = True
        yield from self.staging.verify_published_steps()
        after = yield from self._file_steps(context)
        if proof != after:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Texture changed after native reimport; retain output evidence.")
        self._source(context)
        if brush.digest(self._read_native(context)) != self.native_digest:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Reimported image pixels changed during verification; retained for explicit recovery.")
        self._check(context)
        return {"exported": True, "reimported": True, "image": image_summary, "source_file": proof,
                "source_image": prepared["source_name"], "source_pixels_sha256_float32_le": prepared["source_digest"],
                "encoded_source_pixels_sha256_float32_le": brush.digest(prepared["values"]),
                "raw_input_float32_recovery_verified": (not prepared["associated"] and not prepared["srgb"] and
                    prepared["format"].startswith("EXR") and (prepared["role"] == "DATA" or prepared["format"] == "EXR32_RAW")),
                "source_pixels_unchanged": True, "source_associated_converted_to_straight": prepared["associated"],
                "pixel_verification": verification, "file_written": True, "bound_to_nodes": False,
                "project_saved": False, "verification_required": True,
                "native_decode_interruptible": False, "native_source_validation_interruptible": False}

    def evidence(self):
        file = self.staging.evidence() if self.staging is not None else {"file_published": False, "publication_attempted": False,
            "publication_outcome_unknown": False, "retained_staging_path": None, "staging_cleanup": "not_created"}
        return {**file, "requested_output_path": self.prepared.get("filepath"),
                "native_decode_verified": self.native_verified, "pixel_roundtrip_verified": self.pixels_verified,
                "last_observed_reimport_image_name": self.last_image_name,
                **self.cleanup_evidence}

    def cleanup(self, context, job, *, success):
        if self.staging is not None:
            try:
                self.staging.cleanup()
            finally:
                self.staging.release_handles()
        # After the guarded native call, verification yields to user/bridge work.
        # Never delete a possibly subsequently edited output outside that finalized
        # checkpoint. Reuse its confirmed recovery marker or explicit image.remove.
        self.cleanup_evidence = {"post_commit_image_cleanup": "not_needed" if success or not self.last_image_name else "explicit_recovery_required",
                                 "external_file_removed": False, "native_undo_removes_external_file": False}
        return self.evidence()


def start_export(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "new_name", "filepath", "format", "time_limit_seconds"})
    if context.jobs is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Image delivery jobs are unavailable in this runtime.")
    return context.jobs.start_export(context, {key: value for key, value in params.items() if key != "time_limit_seconds"},
                                     params.get("time_limit_seconds", 120.))


def register_tools(registry: Any) -> None:
    registry.register("image.export_job_start", start_export, toolset="materials", modifies=True,
                      automatic_checkpoint=False, batchable=False, permissions=REQUIRED,
                      description="Accept a frozen-source PNG/EXR no-overwrite export and verified reimport job; poll exact terminal file/image effects, never assume undo removes files.")
