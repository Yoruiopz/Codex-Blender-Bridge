"""Geometry jobs share the existing Image/Scene owner without native checkpoints."""

from __future__ import annotations

import base64
import hashlib
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .geometry_preview_process import PreviewProcess
from .geometry_preview_source import REQUIRED, GeometryPreviewOrigin, refused, stop_gate
from .job_controller import TERMINAL
from .scene_jobs import SceneJobs


@dataclass(slots=True)
class GeometryPreviewJob:
    job_id: str
    origin: GeometryPreviewOrigin
    lifetime: Any
    deadline: float
    source_name: str = ""
    method: str = "preview.geometry_start"
    kind: str = "geometry.authored_preview"
    state: str = "QUEUED"
    revision: int = 1
    progress: dict = field(default_factory=lambda: {"phase": "awaiting_start_delivery"})
    result: dict | None = None
    error: dict | None = None
    work: Any = None
    process: Any = None
    cancel_reason: str = ""
    in_commit: bool = False
    in_tick: bool = False
    operation_id: str | None = None
    handoff_ready: bool = False
    external_effects: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    def summary(self):
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "source_object": self.source_name,
            "state": self.state,
            "terminal": self.state in TERMINAL,
            "revision": self.revision,
            "progress": dict(self.progress),
            "result": self.result,
            "error": self.error,
            "operation_id": self.operation_id,
            "external_effects": dict(self.external_effects),
            "scene_changed": False,
            "undo_boundary_created": False,
            "undo_boundary_finalized": False,
            "durable": False,
        }


class GeometryPreviewJobs(SceneJobs):
    """Exact-type routing only; legacy Scene/Image records use their old paths."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.geometry_previews: OrderedDict[str, dict] = OrderedDict()
        self._geometry_records = {}
        self._geometry_resources = {}
        self._geometry_work = {}
        self._geometry_retained = OrderedDict()

    def _geometry_origin(self, job):
        item = self._geometry_records.get(id(job))
        if (
            item is None
            or item[0] is not job
            or item[1] is not job.origin
            or job.lifetime is not item[1].lifetime
            or job.deadline != item[1].deadline
        ):
            raise refused("GEOMETRY_RECORD_CHANGED")
        return item[1]

    def _guard_context_creation(self, job):
        return True if type(job) is GeometryPreviewJob else super()._guard_context_creation(job)

    def start_geometry(self, context, origin):
        self._main()
        if self.active is not None:
            raise refused("JOB_BUSY")
        if type(origin) is not GeometryPreviewOrigin:
            raise refused("ADMISSION_REQUIRED")
        origin.enter()
        for key, resource in list(self._geometry_retained.items()):
            try:
                effects = resource.close()
            except Exception:
                continue
            if effects["staging_cleanup"] == "complete" and effects["worker_reaped"]:
                self._geometry_retained.pop(key)
        if any(
            not resource.evidence()["worker_reaped"]
            for resource in self._geometry_retained.values()
        ):
            raise refused("WORKER_REAP_PENDING")
        if len(self._geometry_retained) >= 4:
            raise refused("STAGING_RETENTION_LIMIT")
        job = GeometryPreviewJob(
            "job_" + uuid.uuid4().hex,
            origin,
            origin.lifetime,
            origin.deadline,
            source_name=origin.name,
        )
        self._geometry_records[id(job)] = job, origin
        self.active = job
        if origin.connection_events is not None:
            origin.connection_events[1].set()
        return {
            "accepted": True,
            **job.summary(),
            "job_completed": False,
            "source_fingerprint": origin.digest,
            "source_capture_wall_ms": origin.capture_ms,
            "source_snapshot_profile": "stock_geometry_preview_v1",
            "original_Main_write_set": [],
            "framework_evidence_revision_before": origin.revision,
            "framework_evidence_revision_at_admission": origin.revision + 1,
            "framework_executing_mutators_at_admission": 1,
            "protected_baseline_rebased": False,
            "permission_provider_purity_qualified": False,
            "current_viewport_qualified": False,
            "complete_H02_or_F01_qualified": False,
        }

    def _tick_owned(self, job, control):
        if type(job) is GeometryPreviewJob and job.in_tick:
            raise refused("GEOMETRY_SCHEDULER_REENTRY")
        if type(job) is GeometryPreviewJob and job.state in TERMINAL:
            self._finish(job, "FAILED", refused("JOB_STATE_CHANGED"))
            return False
        if type(job) is GeometryPreviewJob and not job.handoff_ready:
            return True  # No process/file work before the canonical start scope completes.
        return super()._tick_owned(job, control)

    def _context(self, job):
        if type(job) is not GeometryPreviewJob:
            return super()._context(job)
        origin = self._geometry_origin(job)
        context = self.context_factory()
        context.request_lifecycle = origin.lifetime
        context.request_id = job.job_id
        context.check_final_request = None
        context.check_final_job = lambda: self._pure(job, context)
        context.check_cancelled = lambda: self._check(job, context)
        return context

    def _pure(self, job, context):
        origin = self._geometry_origin(job)
        if self.active is not job or job.cancel_reason:
            raise BridgeError(ErrorCode.TIMEOUT, "Geometry preview cancelled.")
        resource = self._geometry_resources.get(id(job))
        if job.process is not resource or job.work is not self._geometry_work.get(id(job)):
            raise refused("WORKER_OWNER_CHANGED")
        if context.check_final_request is not None:
            raise refused("JOB_SAFE_POINT_CHANGED")
        try:
            stop_gate(context, job.lifetime, job.deadline)
        except BridgeError as error:
            if error.code == ErrorCode.AGENT_PAUSED.value:
                raise BridgeError(
                    ErrorCode.TIMEOUT, "Geometry preview cancelled because the bridge was paused."
                ) from error
            raise
        origin._static(context)

    def _check(self, job, context):
        if type(job) is not GeometryPreviewJob:
            return super()._check(job, context)
        self._pure(job, context)
        self._geometry_origin(job).check_job(context)
        self._pure(job, context)

    def _source_action(self, job, context):
        # Live consent first, then literal source CAS and pure final stop gate.
        self._pure(job, context)
        self._geometry_origin(job).check_job(context, source=True)
        self._pure(job, context)

    def _make_work(self, job, context):
        if type(job) is not GeometryPreviewJob:
            return super()._make_work(job, context)
        work = self._geometry_steps(job, context)
        self._geometry_work[id(job)] = work
        return work

    def _work_step_limit(self, job):
        return 1 if type(job) is GeometryPreviewJob else super()._work_step_limit(job)

    def _geometry_steps(self, job, context):
        origin = self._geometry_origin(job)
        origin.check_job(context, source=True)
        process = PreviewProcess(origin.binary, origin.raw, origin.build, origin.version)
        self._geometry_resources[id(job)] = process
        job.process = process
        yield from process.fingerprint_steps(lambda: self._check(job, context))
        origin.check_job(context, source=True)
        process.launch(lambda: self._source_action(job, context))
        while process.poll() is None:
            yield {"phase": "worker_running", "fraction": None}
        self._check(job, context)
        png, metadata = process.result(lambda: self._source_action(job, context))
        yield {"phase": "validating_output", "completed": 1, "total": 1}
        origin.check_job(context, source=True)
        effects = process.close()
        job.external_effects = effects
        if effects["staging_cleanup"] != "complete" or not effects["worker_reaped"]:
            raise refused("CLEANUP_UNKNOWN")
        origin.check_job(context, source=True)
        self._pure(job, context)
        preview_id = "geometry_preview_" + uuid.uuid4().hex
        result = {
            "preview_id": preview_id,
            "source_object": origin.name,
            "source_fingerprint": origin.digest,
            "width": 128,
            "height": 128,
            "mime_type": "image/png",
            "image_sha256": metadata["parent_validated_png"]["sha256"],
            "source_capture_wall_ms": origin.capture_ms,
            "worker_evidence": metadata,
            "scene_changed": False,
            "source_geometry_evaluated": False,
            "render_result_replaced": False,
            "project_saved": False,
            "original_material_appearance_copied": False,
            "temporary": True,
            "visual_review_performed": False,
            "full_hidden_state_preservation_qualified": False,
            "permission_provider_purity_qualified": False,
            "current_viewport_qualified": False,
            "protected_baseline_rebased": False,
            "complete_H02_or_F01_qualified": False,
            "scene_changed_scope": "No tool-owned source writes; unrelated manual/evaluation changes are not a whole-Main snapshot guarantee.",
            "coverage": "Named authored base-Mesh geometry and represented XYZ channels only; children/instances and original appearance excluded.",
        }
        self._expire()
        while len(self.geometry_previews) >= 4:
            self.geometry_previews.popitem(last=False)
        self.geometry_previews[preview_id] = {
            "png": png,
            "result": result,
            "origin": job.origin,
            "expires": time.monotonic() + 300,
            "job_id": job.job_id,
        }
        return result

    def _complete_work(self, job, context, value):
        if type(job) is not GeometryPreviewJob:
            return super()._complete_work(job, context, value)
        self._pure(job, context)
        job.result = value
        self._finish(job, "SUCCEEDED")

    def _finish(self, job, state, error=None, **kwargs):
        if type(job) is not GeometryPreviewJob:
            return super()._finish(job, state, error, **kwargs)
        if id(job) not in self._geometry_records and self.active is not job:
            return
        if error is not None and error.code in {
            ErrorCode.AGENT_PAUSED.value,
            ErrorCode.PERMISSION_DENIED.value,
            ErrorCode.TOOLSET_DISABLED.value,
        }:
            state = "CANCELLED"
        record = self._geometry_records.get(id(job))
        origin = record[1] if record is not None and record[0] is job else None
        resource = self._geometry_resources.pop(id(job), None)
        # Latch no publication before killing/reaping; cleanup never needs a new grant.
        if state != "SUCCEEDED":
            for key, value in list(self.geometry_previews.items()):
                if value["job_id"] == job.job_id:
                    self.geometry_previews.pop(key)
        cleanup_unknown = False
        work = self._geometry_work.pop(id(job), None)
        job.work = None
        if work is not None:
            try:
                work.close()
            except Exception:
                cleanup_unknown = True
                job.external_effects["work_close_unknown"] = True
        # Always attempt the real owned process even if generator close failed.
        if resource is not None:
            try:
                job.external_effects.update(resource.close())
                if (
                    job.external_effects["staging_cleanup"] != "complete"
                    or not job.external_effects["worker_reaped"]
                ):
                    cleanup_unknown = True
            except Exception:
                cleanup_unknown = True
            if cleanup_unknown:
                self._geometry_retained[id(resource)] = resource
        if cleanup_unknown:
            state = "FAILED"
            if error is None:
                error = refused("CLEANUP_UNKNOWN")
            error.context["cleanup_outcome_unknown"] = True
            job.external_effects["cleanup_outcome_unknown"] = True
        if resource is not None:
            job.process = resource  # Retain the real owned handle, never a substituted record.
        if state != "SUCCEEDED":
            job.result = None
            for key, value in list(self.geometry_previews.items()):
                if value["job_id"] == job.job_id:
                    self.geometry_previews.pop(key)
        job.state, job.progress = state, {"phase": state.lower()}
        job.revision += 1
        job.error = error.to_dict() if error is not None else None
        if origin is not None and origin.connection_events is not None:
            try:
                origin.connection_events[1].clear()
            except Exception:
                state = job.state = "FAILED"
                job.progress, job.result = {"phase": "failed"}, None
                for key, value in list(self.geometry_previews.items()):
                    if value["job_id"] == job.job_id:
                        self.geometry_previews.pop(key)
                if error is None:
                    error = refused("LIFETIME_CLEANUP_UNKNOWN")
                error.context["lifetime_cleanup_unknown"] = True
                job.external_effects["lifetime_cleanup_unknown"] = True
                job.error = error.to_dict()
        try:
            if origin is None:
                raise refused("GEOMETRY_RECORD_CHANGED")
            record = origin.services[0].record_operation(
                tool=job.method,
                description="Geometry preview " + state.lower(),
                success=state == "SUCCEEDED",
                duration_ms=(time.monotonic() - job.started) * 1000,
                error_code=error.code if error else None,
                job_evidence={
                    "job_id": job.job_id,
                    "state": state,
                    "external_effects": dict(job.external_effects),
                    "scene_changed": False,
                },
            )
            job.operation_id = record.operation_id
        except Exception:
            for key, value in list(self.geometry_previews.items()):
                if value["job_id"] == job.job_id:
                    self.geometry_previews.pop(key)
            job.state, job.result, job.error = "FAILED", None, refused("HISTORY_UNKNOWN").to_dict()
        if origin is not None:
            origin.release_buffer()  # Retain digests, not full DTO buffers.
        self._geometry_records.pop(id(job), None)
        self._retire(job)

    def _expire(self):
        for key, value in list(self.geometry_previews.items()):
            if time.monotonic() >= value["expires"]:
                self.geometry_previews.pop(key)

    def geometry_image(self, context, preview_id):
        self._main()
        self._expire()
        value = self.geometry_previews.get(preview_id)
        if value is None:
            raise invalid_argument(
                "Geometry preview is missing, expired or evicted; start a new preview."
            )
        origin = value["origin"]
        if type(origin) is not GeometryPreviewOrigin:
            raise refused("PREVIEW_CACHE_CHANGED")
        # Completed previews use this new fetch's lifetime/deadline, not the old job deadline.
        self._fetch_check(context, origin)
        if (
            self.geometry_previews.get(preview_id) is not value
            or time.monotonic() >= value["expires"]
        ):
            raise refused("PREVIEW_EXPIRED_OR_EVICTED")
        if (
            type(value["png"]) is not bytes
            or not 8 < len(value["png"]) <= 2 * 1024 * 1024
            or hashlib.sha256(value["png"]).hexdigest() != value["result"]["image_sha256"]
            or value["result"]["source_fingerprint"] != origin.digest
        ):
            raise refused("PREVIEW_CACHE_CHANGED")
        return {**value["result"], "png_base64": base64.b64encode(value["png"]).decode("ascii")}

    def _fetch_check(self, context, origin):
        from .tools.geometry_preview import ImageAdmission

        binding = context.checkpoint_admission
        guard = None if binding is None else binding.callback
        if type(guard) is not ImageAdmission:
            raise refused("FETCH_ADMISSION_REQUIRED")
        ImageAdmission.check_after_read(guard)
        if (
            context.registry.active_exclusive_mutation
            or context.registry.executing_mutators
            or origin.store.executing_mutators
        ):
            raise refused("NESTED_MUTATOR")
        context.require(*REQUIRED)
        ImageAdmission.check_after_read(guard)
        if (
            context.registry.active_exclusive_mutation
            or context.registry.executing_mutators
            or origin.store.executing_mutators
        ):
            raise refused("NESTED_MUTATOR")
        services = tuple(
            getattr(context, key)
            for key in ("state", "registry", "permissions", "checkpoints", "jobs")
        )
        if any(a is not b for a, b in zip(services, origin.services, strict=True)):
            raise refused("AUTHORITY_CHANGED")
        from .geometry_preview_source import frozen_source, semantic

        if (
            context.permissions._source is not origin.provider
            or context.jobs.context_factory is not origin.context_factory
            or getattr(context.state, "_artist_task_plans", None) is not origin.store
            or origin.store.baseline is not origin.baseline
            or origin.store.protection is not origin.protection
            or semantic(origin.store) != origin.semantic_origin
            or context.registry.get(origin.spec.name) is not origin.spec
        ):
            raise refused("AUTHORITY_CHANGED")
        ImageAdmission.check_after_read(guard)
        stop_gate(context, context.request_lifecycle)
        if (
            context.registry.active_exclusive_mutation
            or context.registry.executing_mutators
            or origin.store.executing_mutators
        ):
            raise refused("NESTED_MUTATOR")
        try:
            raw, ids, _elapsed = frozen_source(origin.name)
        except BridgeError as cause:
            raise refused("STALE_SOURCE") from cause
        if (
            context.registry.active_exclusive_mutation
            or context.registry.executing_mutators
            or origin.store.executing_mutators
        ):
            raise refused("NESTED_MUTATOR")
        if hashlib.sha256(raw).hexdigest() != origin.digest or ids != origin.identities:
            raise refused("STALE_SOURCE")
        ImageAdmission.check_after_read(guard)
        stop_gate(context, context.request_lifecycle)

    def cancel_all(self, reason):
        self.geometry_previews.clear()
        return super().cancel_all(reason)
