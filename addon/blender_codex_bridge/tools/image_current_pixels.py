"""Opt-in loaded-image preview and paired backup preparation for native testing."""

from __future__ import annotations

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
    static = origin.capture.original_metadata["static"]
    if (static["width"], static["height"]) != (2, 2) or origin.file_plan.journal_enabled:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "The private paired-backup fixture admits 2x2 textures with retain_event_journal=false.",
        )
    return origin


def pack_preview(context, params):
    origin = _enter_small_backup(context, params, contract.PACK_PREVIEW)
    capture = origin.capture
    cached = origin.cache_preview(capture, origin.file_plan)
    return {**cached, "profile": contract.PROFILE, "dimensions": [2, 2], "phase": "preview",
            "image_packed": False, "backup_files_written": False,
            "consumer_graph_sha256": capture.consumer_graph_sha256,
            "payload_facts": capture.payloads.facts()}


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
    origin = _enter_small_backup(context, params, contract.PACK_START)
    return {"source": origin.capture.original, "source_name": origin.parameters["image_name"],
            "name": origin.parameters["snapshot_name"], "requires_external_files": True,
            "method": contract.PACK_START, "kind": contract.KIND,
            "driver_type": CurrentPixelsDriver, "origin": origin,
            "workload": origin.capture.workload}


class CurrentPixelsDriver:
    def __init__(self, prepared):
        self.origin = origin = prepared["origin"]
        self.files = files.BackupFiles(origin.file_plan)
        self.record_uuid = uuid.uuid4().hex
        capture = origin.capture
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
            "image_name": prepared["source_name"], "snapshot_name": prepared["name"],
            "expected_target_fingerprint": origin.parameters["expected_target_fingerprint"],
            "expected_prefix_sha256": prefix, "observed_prefix_sha256": prefix, "observed_prefix": "PREPARED",
            "previous_packed_sha256": capture.payloads.original_packed_sha256,
            "previous_decoded_pixels_sha256": capture.payloads.original_decoded_pixels_sha256,
            "current_pixels_sha256_float32_le": capture.payloads.current_pixels_sha256_float32_le,
            "consumer_graph_sha256": capture.consumer_graph_sha256, "snapshot_retained": True,
        })

    def steps(self, context, _job, _commit):
        origin = self.origin
        origin.authorize(context)
        capture = origin.refresh_capture(context)
        work = self.files.prepare_pair_steps(
            capture, record_uuid=self.record_uuid, runtime_nonce=origin.binding.nonce,
            affected_materials=origin.parameters["affected_materials"], check=origin._read_gate,
        )
        # The file iterator closes each OS descriptor before yielding. Renew
        # grants and compare the complete baseline at every subsequent turn;
        # within that turn file gates check the retained origin without providers.
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
        return {"phase": "backups_verified", "files": pair["files"],
                "manifest_sha256": pair["manifest_sha256"], "image_packed": False, "project_saved": False}

    def _record_attempt(self):
        if self.files.attempted and self.receipt["stage"] == "PREPARED":
            self.receipt = contract.prefix_receipt(
                self.receipt, "BACKUPS_PARTIAL", external_write_attempted=True,
                possible_mutation=True, observed_prefix="BACKUPS_PARTIAL",
            )

    def cleanup(self, _context, _job, *, success):
        self.files.close()
        return self.evidence()

    def evidence(self):
        return self.files.evidence()

    def recovery_evidence(self):
        return dict(self.receipt)


def register_tools(registry):
    """Explicit native-fixture entry. The shipped registry never calls this."""
    for method, handler in zip(source.METHODS, (pack_preview, pack_start, recovery_preview, restore_start), strict=True):
        modifies = method in contract.METHOD_MODES
        registry.register(
            method, handler, toolset="materials", permissions=source.REQUIRED, modifies=modifies,
            batchable=False, automatic_checkpoint=False, record_history=True,
            checkpoint_owns_finalization=modifies, protected_scope_resolver=source.protected_scope,
            checkpoint_admission_factory=source.admission_factory(method),
            checkpoint_parameter_dependencies=source.initial_dependencies,
        )
    source.bind_registry(registry)
