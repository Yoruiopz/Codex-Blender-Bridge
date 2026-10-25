# SPDX-License-Identifier: GPL-3.0-or-later
"""Native saves share the existing single job slot and own external effects."""
from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field

from .errors import BridgeError, ErrorCode, invalid_argument
from .geometry_preview_jobs import GeometryPreviewJobs
from .job_controller import TERMINAL
from .native_save_files import NativeSaveFiles, freeze_plan
from .native_save_process import SaveReaderProcess
from .native_save_source import START, SaveOrigin, hook_facts, hooks_match, refused
from .utils import require_blender


@dataclass(frozen=True, slots=True)
class SavePreview:
    origin: SaveOrigin
    plan: object
    fingerprint: str
    losses: tuple
    expires: float


@dataclass(slots=True)
class NativeSaveJob:
    job_id: str
    origin: SaveOrigin
    lifetime: object
    deadline: float
    kind: str = "project.native_save"
    method: str = START
    state: str = "QUEUED"
    revision: int = 1
    progress: dict = field(default_factory=lambda: {"phase": "awaiting_start_delivery"})
    result: dict | None = None
    error: dict | None = None
    work: object = None
    cancel_reason: str = ""
    in_commit: bool = False
    in_tick: bool = False
    handoff_ready: bool = False
    external_effects: dict = field(default_factory=dict)
    operation_id: str | None = None
    started: float = field(default_factory=time.monotonic)

    def summary(self):
        return {"job_id": self.job_id, "kind": self.kind, "state": self.state,
                "terminal": self.state in TERMINAL, "revision": self.revision,
                "progress": dict(self.progress), "result": self.result, "error": self.error,
                "external_effects": dict(self.external_effects), "operation_id": self.operation_id,
                "undo_boundary_created": False, "undo_boundary_finalized": False,
                "durable": False, "scene_changed": None}


@dataclass(slots=True)
class SaveRecord:
    job: NativeSaveJob
    origin: SaveOrigin
    preview: SavePreview
    files: object = None
    reader: object = None
    work: object = None
    native_started: bool = False
    native_returned: bool = False
    native_completed: bool = False
    source_filepath_after: str | None = None
    source_verified: bool = False
    reader_verified: bool = False
    native_interval_ms: float | None = None


class NativeSaveJobs(GeometryPreviewJobs):
    def __init__(self, *args, native_save_policy, **kwargs):
        super().__init__(*args, **kwargs)
        self.native_save_policy = native_save_policy
        self.native_save_previews = OrderedDict()
        self._save_records = {}
        self._save_phases = {}
        self._save_contexts = {}
        self._save_resources = {}
        self._save_retained = OrderedDict()

    def _record(self, job):
        value = self._save_records.get(id(job))
        if (type(value) is not SaveRecord or value.job is not job or value.origin is not job.origin
                or job.lifetime is not value.origin.lifetime or job.deadline != value.origin.deadline
                or job.work is not value.work):
            raise refused("SAVE_RECORD_CHANGED")
        return value

    def preview_save(self, context, origin):
        self._main()
        origin.enter()
        if self.active is not None:
            raise refused("JOB_BUSY")
        origin.check(context)
        plan = freeze_plan(origin.preferences[0], origin.params["filepath"], origin.params["mode"],
                           origin.params["overwrite_policy"], origin.filepath, origin.preferences[1],
                           check=lambda: origin.check(context, source=False))
        origin.check(context)
        losses = origin.projection.losses + (() if origin.params["mode"] == "COPY_NEW" else
                                            ("NATIVE_DESTINATION_RACE_NOT_EXCLUDED",))
        value = SavePreview(origin, plan, origin.fingerprint(plan), losses, time.monotonic() + 60)
        for key, old in list(self.native_save_previews.items()):
            if time.monotonic() >= old.expires:
                self.native_save_previews.pop(key)
        while len(self.native_save_previews) >= 4:
            self.native_save_previews.popitem(last=False)
        key = "native_save_" + uuid.uuid4().hex
        self.native_save_previews[key] = value
        return {"preview_id": key, "fingerprint": value.fingerprint, "profile": "stock_native_project_v1",
                "mode": origin.params["mode"], "filepath": origin.params["filepath"],
                "overwrite_policy": origin.params["overwrite_policy"], "required_accepted_losses": list(losses),
                "destination": plan.summary(), "expires_in_seconds": 60,
                "native_save_invoked": False, "project_saved": False,
                "raw_whole_Main_preservation_qualified": False, "native_effect_inventory_complete": False}

    def start_native_save(self, context, origin):
        self._main()
        origin.enter()
        if self.active is not None:
            raise refused("JOB_BUSY")
        preview = self.native_save_previews.get(origin.params["preview_id"])
        if type(preview) is not SavePreview or time.monotonic() >= preview.expires:
            raise invalid_argument("Native-save preview expired or is missing; create a new preview.")
        previous = preview.origin
        if (previous.semantic != origin.semantic or previous.baseline is not origin.baseline
                or previous.protection is not origin.protection
                or any(a is not b for a, b in zip(previous.services, origin.services, strict=True))
                or previous.provider is not origin.provider):
            raise refused("PREVIEW_AUTHORITY_CHANGED")
        previous.lifetime.check()
        previous.source()
        if (previous.statement is not origin.statement
                or previous.lifetime.connection is not origin.lifetime.connection
                or origin.params["expected_fingerprint"] != preview.fingerprint
                or origin.params["accepted_losses"] != list(preview.losses)
                or any(origin.params[key] != previous.params[key] for key in ("mode", "filepath", "overwrite_policy"))):
            raise refused("PREVIEW_OR_ACCEPTED_LOSSES_CHANGED")
        preview.plan.check(lambda: origin.check(context, source=False))
        origin.check(context)
        # Reap exact retained workers before admitting another job. A renewed
        # grant never authorizes deleting native-save recovery bytes/receipts.
        self._reap_retained(context, origin)
        if len(self._save_retained) >= 4:
            raise refused("RETAINED_RESOURCE_LIMIT")
        if self.native_save_previews.get(origin.params["preview_id"]) is not preview:
            raise refused("PREVIEW_REMOVED")
        self.native_save_previews.pop(origin.params["preview_id"])
        job = NativeSaveJob("job_" + uuid.uuid4().hex, origin, origin.lifetime, origin.deadline)
        self._save_records[id(job)] = SaveRecord(job, origin, preview)
        self.active = job
        if origin.events is not None:
            origin.events[1].set()
        self._effects(self._record(job))
        return {"accepted": True, **job.summary(), "job_completed": False,
                "source_fingerprint": preview.fingerprint, "source_capture_wall_ms": origin.capture_ms,
                "native_effect_inventory_complete": False, "protected_baseline_rebased": False}

    def _reap_retained(self, context, origin):
        def gate():
            origin.check(context, source=False)

        for retained in tuple(self._save_retained.values()):
            gate()
            if retained.reader is not None:
                try:
                    evidence = retained.reader.close(remove_files=False)
                finally:
                    self._effects(retained)
                gate()
                if not evidence["worker_reaped"]:
                    raise refused("READER_REAP_PENDING")

    def complete_save_handoff(self, origin, accepted):
        job = self.active
        if type(job) is NativeSaveJob and self._save_records.get(id(job)) is not None and job.origin is origin:
            if accepted:
                job.handoff_ready = True
            else:
                self._finish(job, "FAILED", refused("START_HANDOFF_FAILED"))

    def phase_valid(self, context, origin):
        if not self.context_valid(context, origin):
            return False
        item = self._save_phases.get(id(context))
        if item is None or item[0] is not context or item[1] is not origin:
            return False
        permit, lease, job = item[2:]
        entries = self.registry._mutation_interlock._entries
        return self.active is job and bool(entries) and (
            entries[-1].continuation_id == id(permit) and entries[-1].context is context
            and entries[-1].spec is origin.spec and entries[-1].params is origin.params
            and entries[-1].lease is lease and context.exclusive_mutation_lease is lease
            and self.registry._exclusive_mutation_lease is lease)

    @contextmanager
    def _phase(self, job, context):
        record = self._record(job)
        with self.registry.mutation_entry(record.origin.spec, record.origin.params, context) as permit:
            self._save_phases[id(context)] = context, record.origin, permit, context.exclusive_mutation_lease, job
            try:
                self._gate(job, source=False)
                yield
            finally:
                self._save_phases.pop(id(context), None)
                self._save_contexts.pop(id(context), None)

    def context_valid(self, context, origin):
        value = self._save_contexts.get(id(context))
        return (value is not None and value[0] is context and value[1] is origin
                and context.request_lifecycle is origin.lifetime and context.check_final_request is None
                and hooks_match(context, value[2]))

    def _phase_context(self, job):
        for item in self._save_phases.values():
            if item[1] is self._record(job).origin:
                return item[0]
        raise refused("SAVE_PHASE_MISSING")

    def _gate(self, job, *, source=True):
        record = self._record(job)
        context = self._phase_context(job)
        self._save_pure(job, context)
        try:
            record.origin.check(context, source=source, after_native=record.native_returned)
        except BridgeError:
            if source:
                record.source_verified = False
            raise
        self._save_pure(job, context)

    def _save_pure(self, job, context):
        record = self._record(job)
        if self.active is not job or job.cancel_reason:
            raise BridgeError(ErrorCode.TIMEOUT, "Native save job cancelled; inspect retained file effects.")
        record.origin.static(context)

    def _guard_context_creation(self, job):
        return True if type(job) is NativeSaveJob else super()._guard_context_creation(job)

    def _context(self, job):
        if type(job) is not NativeSaveJob:
            return super()._context(job)
        record = self._record(job)
        context = self.context_factory()
        context.request_lifecycle, context.request_id = record.origin.lifetime, job.job_id
        context.check_final_request = None
        context.check_final_job = lambda: self._save_pure(job, context)
        context.check_cancelled = lambda: self._save_pure(job, context)
        self._save_contexts[id(context)] = context, record.origin, hook_facts(context)
        return context

    def _tick_owned(self, job, control):
        if type(job) is NativeSaveJob:
            if job.in_tick:
                raise refused("SAVE_SCHEDULER_REENTRY")
            if not job.handoff_ready:
                return True
        if type(job) is not NativeSaveJob:
            return super()._tick_owned(job, control)
        try:
            return super()._tick_owned(job, control)
        finally:
            for key, value in list(self._save_contexts.items()):
                if value[1] is job.origin:
                    self._save_contexts.pop(key)

    def _check(self, job, context):
        return self._save_pure(job, context) if type(job) is NativeSaveJob else super()._check(job, context)

    def _prepare_step(self, job, context):
        if type(job) is not NativeSaveJob:
            return super()._prepare_step(job, context)
        self._save_pure(job, context)

    def _work_step_limit(self, job):
        return 1 if type(job) is NativeSaveJob else super()._work_step_limit(job)

    def _make_work(self, job, context):
        if type(job) is not NativeSaveJob:
            return super()._make_work(job, context)
        record = self._record(job)
        record.work = self._save_steps(job)
        return record.work

    def _advance_work(self, job, context, control):
        if type(job) is not NativeSaveJob:
            return super()._advance_work(job, context, control)
        with self._phase(job, context):
            return next(self._record(job).work)

    def _effects(self, record):
        value = {} if record.files is None else record.files.effects()
        if record.native_started:
            value["publication_attempted"] = True
        value["native_save"] = {
            "mode": record.origin.mode, "policy_version": record.origin.statement.policy,
            "native_save_invoked": record.native_started, "native_save_completed": record.native_completed,
            "possible_native_effects": record.native_started, "native_external_effects_authorized": True,
            "native_effect_inventory_complete": False, "source_filepath_before": record.origin.filepath or None,
            "source_filepath_after": record.source_filepath_after,
            "declared_source_verified": record.source_verified, "fresh_process_reopen_verified": record.reader_verified,
        }
        if record.reader is not None:
            reader = record.reader.evidence()
            value["native_save"].update(worker_reaped=reader["worker_reaped"],
                                        reader_cleanup=reader["staging_cleanup"],
                                        retained_reader_path=reader.get("retained_staging_path"))
        value["native_undo_removes_external_file"] = False
        value["crash_durability_verified"] = False
        record.job.external_effects = value
        return value

    def _save_steps(self, job):
        record = self._record(job)
        origin = record.origin
        self._gate(job)
        record.preview.plan.check(lambda: self._gate(job, source=False))
        self._gate(job)
        record.files = NativeSaveFiles(record.preview.plan)
        native_path = record.files.prepare(lambda: self._gate(job, source=False))
        yield {"phase": "native_save_pending"}
        self._gate(job)
        record.native_started = job.in_commit = True
        origin.store.evidence_revision += 1
        record.files.native_started()
        self._effects(record)
        started = time.perf_counter()
        success = False
        try:
            bpy = require_blender()
            result = bpy.ops.wm.save_mainfile() if origin.mode == "SAVE_CURRENT" else bpy.ops.wm.save_as_mainfile(
                filepath=str(native_path), copy=origin.mode == "COPY_NEW",
                check_existing=False, relative_remap=False, compress=False)
            success = result == {"FINISHED"}
        finally:
            record.native_interval_ms = (time.perf_counter() - started) * 1000
            record.native_returned, record.native_completed, job.in_commit = True, success, False
            record.files.native_returned(success)
            try:
                record.source_filepath_after = origin.observe_native_path(self._phase_context(job))
            except BridgeError:
                record.source_filepath_after = None
            self._effects(record)
        if not success:
            raise refused("NATIVE_SAVE_FAILED", started=True)
        self._gate(job)
        saved = yield from record.files.observe_steps(lambda: self._gate(job, source=False))
        self._gate(job)
        record.source_verified = True
        self._effects(record)
        record.files.check_saved(lambda: self._gate(job, source=False))
        record.reader = SaveReaderProcess(origin.binary, native_path, origin.projection.raw,
                                         origin.build, origin.version, saved.sha256)
        yield from record.reader.fingerprint_steps(lambda: self._gate(job, source=False))
        self._gate(job)
        record.reader.launch(lambda: self._gate(job))
        while record.reader.poll() is None:
            self._gate(job, source=False)
            yield {"phase": "fresh_process_reopen", "fraction": None}
        self._gate(job)
        receipt = record.reader.result(lambda: self._gate(job, source=False))
        record.reader_verified = True
        self._gate(job)
        record.files.check_saved(lambda: self._gate(job, source=False))
        if origin.mode == "COPY_NEW":
            record.files.publish(lambda: self._gate(job, source=False))
        self._effects(record)
        self._gate(job)
        reader_cleanup = record.reader.close(remove_files=True)
        file_cleanup = record.files.close(remove_files=True)
        if (not reader_cleanup["worker_reaped"] or reader_cleanup["staging_cleanup"] not in {"complete", "not_created"}
                or file_cleanup["staging_cleanup"] not in {"complete", "not_created"}):
            raise refused("CLEANUP_UNKNOWN", started=True)
        self._gate(job)
        self._effects(record)
        return {"mode": origin.mode, "filepath": origin.target,
                "profile": "stock_native_project_v1", "fresh_process_reopen_verified": True,
                "declared_source_verified": True, "native_save_interval_ms": record.native_interval_ms,
                "source_capture_wall_ms": origin.capture_ms, "reader_evidence": receipt,
                "source_comparison_count": len(origin.capture_observations),
                "source_comparison_wall_ms_total": sum(origin.capture_observations),
                "reader_cleanup": reader_cleanup, "staging_cleanup": file_cleanup,
                "protected_baseline_rebased": False, "full_project_delivery_qualified": False,
                "raw_whole_Main_preservation_qualified": False, "native_C_catalog_effects_qualified": False}

    def _complete_work(self, job, context, value):
        if type(job) is not NativeSaveJob:
            return super()._complete_work(job, context, value)
        job.result = value
        self._finish(job, "SUCCEEDED")

    def _finish(self, job, state, error=None, **kwargs):
        if type(job) is not NativeSaveJob:
            return super()._finish(job, state, error, **kwargs)
        record = self._save_records.get(id(job))
        if type(record) is not SaveRecord or record.job is not job:
            return
        if error is not None and error.code in {ErrorCode.PERMISSION_DENIED.value, ErrorCode.AGENT_PAUSED.value,
                                                ErrorCode.EMERGENCY_STOPPED.value, ErrorCode.TIMEOUT.value}:
            state = "CANCELLED"
        unknown = False
        if record.work is not None:
            try:
                record.work.close()
            except Exception:
                unknown = True
        for resource in (record.reader, record.files):
            if resource is not None:
                try:
                    cleanup = resource.close(remove_files=False)
                    if resource is record.reader and not cleanup["worker_reaped"]:
                        unknown = True
                except Exception:
                    unknown = True
        self._effects(record)
        if unknown:
            state = "FAILED"
            error = error or refused("CLEANUP_UNKNOWN", started=record.native_started)
            error.context["cleanup_outcome_unknown"] = True
            job.external_effects["native_save"]["cleanup_outcome_unknown"] = True
        if state != "SUCCEEDED":
            job.result = None
            if record.files is not None or record.reader is not None:
                self._save_retained[job.job_id] = record
        if record.origin.events is not None:
            try:
                record.origin.events[1].clear()
            except Exception:
                state, job.result = "FAILED", None
                error = error or refused("LIFETIME_CLEANUP_UNKNOWN", started=record.native_started)
                error.context["lifetime_cleanup_unknown"] = True
        job.state, job.error, job.progress = state, error.to_dict() if error else None, {"phase": state.lower()}
        if error is not None:
            error.context.update(execution_started=record.native_started or record.files is not None,
                                 native_save_invoked=record.native_started, native_save_completed=record.native_completed)
            job.error = error.to_dict()
        job.revision += 1
        try:
            operation = record.origin.services[0].record_operation(
                tool=START, description="Native save " + state.lower(), success=state == "SUCCEEDED",
                duration_ms=(time.monotonic() - job.started) * 1000, error_code=error.code if error else None,
                external_effects=job.external_effects)
            job.operation_id = operation.operation_id
        except Exception:
            job.state, job.result = "FAILED", None
            job.progress = {"phase": "failed"}
            primary = error or refused("HISTORY_UNKNOWN", started=record.native_started)
            primary.context.update(history_outcome_unknown=True,
                                   execution_started=record.native_started or record.files is not None,
                                   native_save_invoked=record.native_started, native_save_completed=record.native_completed)
            job.error = primary.to_dict()
        if job.state != "SUCCEEDED" and (record.files is not None or record.reader is not None):
            self._save_retained[job.job_id] = record
        self._save_records.pop(id(job), None)
        for key, value in list(self._save_contexts.items()):
            if value[1] is record.origin:
                self._save_contexts.pop(key)
        job.work = None
        record.origin.release_buffer()
        record.preview.origin.release_buffer()
        self._retire(job)

    def inspect(self, job_id):
        self._main()
        value = self._save_retained.get(job_id)
        return value.job.summary() if value is not None else super().inspect(job_id)

    def list(self, limit=10):
        result = super().list(limit)
        result["retained_native_saves"] = [value.job.summary() for value in self._save_retained.values()]
        result["retained_native_save_limit"] = 4
        return result

    def cancel_all(self, reason):
        self.native_save_previews.clear()
        return super().cancel_all(reason)
