"""Opt-in loaded-image preview and paired backup preparation for native testing."""

from __future__ import annotations

import hashlib
import uuid

from .. import current_pixels_contract as contract
from .. import current_pixels_files as files
from .. import current_pixels_source as source
from ..errors import BridgeError, ErrorCode


def _origin(context, params, method):
    admission = context.checkpoint_admission
    origin = admission.callback if admission is not None else None
    if (type(origin) is not source.CurrentPixelsOrigin or origin.context is not context
            or origin.params is not params or origin.method != method):
        raise source.refused("CANONICAL_LOADED_IMAGE_ADMISSION_REQUIRED")
    return origin


def _enter_small_backup(context, params, method):
    origin = _origin(context, params, method).enter()
    _require_small_backup(origin.capture, origin.file_plan)
    return origin


def _require_small_backup(capture, plan):
    static = capture.original_metadata["static"]
    if (static["width"], static["height"]) != (2, 2) or plan.journal_enabled:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "The private paired-backup fixture admits 2x2 textures with retain_event_journal=false.",
        )


def _preview_details(capture):
    return {"profile": contract.PROFILE, "dimensions": [2, 2], "phase": "preview",
            "image_packed": False, "backup_files_written": False,
            "consumer_graph_sha256": capture.consumer_graph_sha256,
            "payload_facts": capture.payloads.facts()}


def pack_preview(context, params):
    origin = _enter_small_backup(context, params, contract.PACK_PREVIEW)
    return {**origin.cache_preview(origin.capture, origin.file_plan), **_preview_details(origin.capture)}


def pack_preview_start(context, params):
    origin = _origin(context, params, source.PREVIEW_START)
    return context.jobs.start_prepared_driver(
        context, params, source.PREVIEW_JOB_SECONDS, prepare=prepare_current_pixels_preview,
        required_permissions=source.REQUIRED, callback_control=origin.callbacks,
    )


def prepare_current_pixels_preview(context, params):
    origin = _origin(context, params, source.PREVIEW_START).enter()
    return {"source_name": origin.parameters["image_name"], "name": origin.parameters["snapshot_name"],
            "requires_external_files": True, "method": source.PREVIEW_START,
            "kind": "current_pixels_preview", "driver_type": CurrentPixelsPreviewDriver,
            "origin": origin, "workload": {"source_capture_pending": True}}


class CurrentPixelsPreviewDriver:
    def __init__(self, prepared):
        self.origin = prepared["origin"]

    def steps(self, context, _job, _commit):
        origin = self.origin
        origin.prepare_acquisition(context)
        yield {"phase": "capture_preflight", "completed": 1, "total": 3}
        try:
            capture = yield from origin.acquire_steps(context)
            _require_small_backup(capture, origin.file_plan)
            raw = origin._preview_candidate(capture, origin.file_plan)
            result = _preview_details(capture)
            del capture
        finally:
            origin.release_acquisition()
        yield {"phase": "capture_complete", "completed": 2, "total": 3}
        origin.authorize(context)
        return {**origin._retain_preview(raw), **result}

    def cleanup(self, _context, _job, *, success):
        return self.evidence()

    def evidence(self):
        return {"publication_attempted": False, "file_published": False}

    def recovery_evidence(self):
        return {"possible_mutation": False, "project_saved": False, "source_file_read": False}


def pack_start(context, params):
    origin = _origin(context, params, contract.PACK_START)
    return context.jobs.start_prepared_driver(
        context, params, origin.parameters["time_limit_seconds"], prepare=prepare_current_pixels,
        required_permissions=source.REQUIRED, callback_control=origin.callbacks,
    )


def recovery_preview(_context, _params):
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This private workflow prepares forward backup files.")


def restore_start(_context, _params):
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This private workflow prepares forward backup files.")


def prepare_current_pixels(context, params):
    origin = _origin(context, params, contract.PACK_START).enter()
    prepared = {"source_name": origin.parameters["image_name"],
            "name": origin.parameters["snapshot_name"], "requires_external_files": True,
            "method": contract.PACK_START, "kind": contract.KIND,
            "driver_type": CurrentPixelsDriver, "origin": origin,
            "workload": {"source_capture_pending": True}}
    if not origin.input_deferred:
        _require_small_backup(origin.capture, origin.file_plan)
        prepared.update(source=origin.capture.original, workload=origin.capture.workload)
    return prepared


class CurrentPixelsDriver:
    def __init__(self, prepared):
        self.origin = origin = prepared["origin"]
        self.files = self.receipt = None
        self.record_uuid = uuid.uuid4().hex
        if not origin.input_deferred:
            self._freeze_receipt(origin.capture)

    def _freeze_receipt(self, capture):
        origin = self.origin
        self.files = files.BackupFiles(origin.file_plan)
        prefix = capture.full_native_prefix_sha256
        self.receipt = contract.validate_receipt({
            "kind": contract.KIND, "schema_version": 1, "method": contract.PACK_START,
            "mode": contract.METHOD_MODES[contract.PACK_START], "profile": contract.PROFILE,
            "stage": "PREPARED", "identity_mode": "SAME_SESSION_NATIVE_IDS",
            "external_write_attempted": False, "helper_record_write_attempted": False,
            "image_write_attempted": False, "possible_mutation": False, "state_known": True,
            "verification_required": True, "recovery_authorized": False,
            "project_saved": False, "source_file_read": False, "automatic_inverse_attempted": False,
            "record_uuid": self.record_uuid, "runtime_nonce": origin.binding.nonce,
            "image_name": origin.parameters["image_name"], "snapshot_name": origin.parameters["snapshot_name"],
            "expected_target_fingerprint": origin.parameters["expected_target_fingerprint"],
            "expected_prefix_sha256": prefix, "observed_prefix_sha256": prefix, "observed_prefix": "PREPARED",
            "previous_packed_sha256": capture.payloads.original_packed_sha256,
            "previous_decoded_pixels_sha256": capture.payloads.original_decoded_pixels_sha256,
            "current_pixels_sha256_float32_le": capture.payloads.current_pixels_sha256_float32_le,
            "consumer_graph_sha256": capture.consumer_graph_sha256, "snapshot_retained": True,
        })

    def steps(self, context, job, commit):
        origin = self.origin
        if origin.input_deferred:
            origin.prepare_acquisition(context)
            yield {"phase": "backup_preflight", "completed": 0, "total": 1}
            capture = yield from origin.acquire_steps(context)
        else:
            origin.authorize(context)
            capture = origin.refresh_capture(context)
        try:
            if origin.input_deferred:
                _require_small_backup(capture, origin.file_plan)
                self._freeze_receipt(capture)
            work = self.files.prepare_pair_steps(
                capture, record_uuid=self.record_uuid, runtime_nonce=origin.binding.nonce,
                affected_materials=origin.parameters["affected_materials"], check=origin._read_gate,
            )
        finally:
            if origin.input_deferred:
                origin.release_acquisition()
            del capture
        # A deferred backup archives the bytes matched to the original preview
        # before any output. Renew live grants, path and ownership on every
        # turn. No fresh scene content is used to replace those frozen bytes.
        try:
            while True:
                try:
                    progress = next(work)
                except StopIteration as completed:
                    pair = completed.value
                    break
                self._record_attempt()
                yield progress
                origin.authorize(context)
                if not origin.input_deferred:
                    origin.refresh_capture(context)
        except BaseException:
            self._record_attempt()
            self.receipt = contract.unknown_observation(self.receipt)
            raise
        finally:
            work.close()
        self._record_attempt()
        if self.receipt["stage"] != "BACKUPS_PARTIAL" or not self.files.evidence()["durable_backups_verified"]:
            raise source.refused("COMPLETE_BACKUP_READBACK_REQUIRED")
        self.receipt = contract.prefix_receipt(
            self.receipt, "BACKUPS_DURABLE", durable_backups_verified=True,
            manifest_sha256=pair["manifest_sha256"], observed_prefix="BACKUPS_DURABLE",
        )
        result = {"phase": "backups_verified", "files": pair["files"],
                  "manifest_sha256": pair["manifest_sha256"], "image_packed": False, "project_saved": False,
                  **({"historical_archive": True, "current_scene_match_verified": False} if origin.input_deferred else {})}
        if origin.helper_record_requested:
            if commit is None:
                raise source.refused("NATIVE_HELPER_RECORD_BOUNDARY_REQUIRED")
            yield {"phase": "archive_verified", "completed": 1, "total": 1}
            origin.authorize(context)
            result.update(commit(lambda checkpoint_gate: self._write_helper_record(context, job, pair, checkpoint_gate)))
        return result

    def _write_helper_record(self, context, job, pair, checkpoint_gate):
        origin = self.origin
        graph = origin.binding.graph
        record = graph.canonical_lifecycle_record(self.record_uuid, origin.binding.nonce, pair["manifest_sha256"])
        record_sha256 = hashlib.sha256(record.encode("utf-8")).hexdigest()
        try:
            transition = graph.prepare_helper_record_transition(origin.refresh_capture(context), record)
            origin.release_acquisition()
            self.files.verify_record_archive(pair, origin._read_gate)
            checkpoint_gate()

            def mark_attempt():
                self.receipt = contract.prefix_receipt(
                    self.receipt, "HELPER_RECORD_ATTEMPT", helper_record_write_attempted=True,
                    expected_prefix_sha256=transition.expected_native_prefix_sha256, state_known=False,
                    observed_prefix=None, observed_prefix_sha256=None,
                )
                job.execution_started = True

            graph.write_helper_record(source.require_blender(), transition, check=origin._read_gate,
                                      on_attempt=mark_attempt)
            capture = origin.refresh_capture(context, expected_prefix=transition.expected_native_prefix_sha256,
                                             lifecycle_record=transition.record)
            if capture.full_portable_prefix_sha256 != transition.expected_portable_prefix_sha256:
                raise source.refused("EXPECTED_PORTABLE_HELPER_PREFIX_CHANGED")
            self.receipt = contract.prefix_receipt(
                self.receipt, "HELPER_RECORD_VERIFIED", helper_record_verified=True,
                lifecycle_record_sha256=record_sha256, state_known=True,
                observed_prefix="HELPER_RECORD_VERIFIED", observed_prefix_sha256=capture.full_native_prefix_sha256,
            )
            return {"phase": "helper_record_verified", "helper_record_verified": True,
                    "lifecycle_record_sha256": record_sha256}
        finally:
            origin.release_acquisition()

    def _record_attempt(self):
        if self.files.attempted and self.receipt["stage"] == "PREPARED":
            self.receipt = contract.prefix_receipt(
                self.receipt, "BACKUPS_PARTIAL", external_write_attempted=True,
                possible_mutation=True, observed_prefix="BACKUPS_PARTIAL",
            )

    def cleanup(self, _context, _job, *, success):
        if self.files is not None:
            self.files.close()
        return self.evidence()

    def evidence(self):
        if self.files is None:
            return {"publication_attempted": False, "file_published": False}
        return self.files.evidence()

    def recovery_evidence(self):
        # The job controller renews live permissions after each driver step.
        # Keep the verified backup facts, but a later provider can change Main
        # before the cached receipt is published to the caller.
        if self.receipt is None:
            return {"possible_mutation": False, "project_saved": False, "source_file_read": False}
        return contract.unknown_observation(self.receipt)


def register_tools(registry):
    """Explicit native-fixture entry. The shipped registry never calls this."""
    handlers = (pack_preview, pack_start, recovery_preview, restore_start, pack_preview_start)
    for method, handler in zip(source.FIXTURE_METHODS, handlers, strict=True):
        modifies = method in contract.METHOD_MODES
        registry.register(
            method, handler, toolset="materials", permissions=source.REQUIRED, modifies=modifies,
            batchable=False, automatic_checkpoint=False, record_history=True,
            checkpoint_owns_finalization=modifies, protected_scope_resolver=source.protected_scope,
            checkpoint_admission_factory=source.admission_factory(method),
            checkpoint_parameter_dependencies=source.initial_dependencies,
        )
    source.bind_registry(registry)
