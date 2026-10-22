"""Main-thread image jobs; one shared owner, cooperative work and guarded commits."""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .permissions import Permission
from .protocol import utc_timestamp
from .request_lifecycle import RequestLifetime
from .state import bounded_recovery_evidence
from .tools import image_masks, image_paint, images, pixel_brush
from .utils import require_blender

LOGGER = logging.getLogger(__name__)
START_METHOD = "image.paint_job_start"
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _identity(image: Any) -> tuple:
    pointer = image.as_pointer() if hasattr(image, "as_pointer") else id(image)
    return pointer, getattr(image, "session_uid", None)


def _metadata(image: Any) -> dict:
    result = images._summary(image)
    if result["filepath_truncated"]:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Job source path exceeds its complete metadata verification window.")
    return {key: value for key, value in result.items() if key != "users"}


@dataclass(slots=True)
class PaintJob:
    job_id: str
    request_id: str
    source_name: str
    new_name: str
    lifetime: RequestLifetime
    deadline: float
    prepared: dict
    source_identity: tuple
    source_metadata: dict
    requires_external_files: bool
    created_at: str = field(default_factory=utc_timestamp)
    state: str = "QUEUED"
    revision: int = 1
    progress: dict = field(default_factory=lambda: {"phase": "awaiting_start_delivery", "completed": 0, "total": 1})
    result: dict | None = None
    error: dict | None = None
    work: Any = None
    cancel_reason: str = ""
    boundary_created: bool = False
    boundary_finalized: bool = False
    execution_started: bool = False
    started: float = field(default_factory=time.monotonic)
    operation_id: str | None = None
    in_commit: bool = False
    in_tick: bool = False
    workload: dict = field(default_factory=dict)
    method: str = START_METHOD
    kind: str = "image.paint_version"
    required_permissions: tuple = (Permission.EDIT_MATERIALS,)
    driver: Any = None
    external_effects: dict = field(default_factory=dict)
    recovery_evidence: dict = field(default_factory=dict)
    evidence_observation_unknown: list[str] = field(default_factory=list)
    finished: float | None = None

    def observe_evidence(self) -> list[str]:
        """Retain last bounded observations if native IDs disappear or reads fail."""
        if self.driver is None:
            return list(self.evidence_observation_unknown)
        unknown = []
        for field_name, observe in (("external_effects", self.driver.evidence),
                ("recovery_evidence", getattr(self.driver, "recovery_evidence", None))):
            if observe is None:
                continue
            try:
                value = observe()
                setattr(self, field_name, (bounded_recovery_evidence(value) or {}) if field_name == "recovery_evidence" else dict(value))
            except Exception:
                LOGGER.exception("Image-job %s observation failed", field_name)
                unknown.append(field_name)
        self.evidence_observation_unknown = unknown
        return list(unknown)

    def summary(self) -> dict:
        self.observe_evidence()
        return {"job_id": self.job_id, "kind": self.kind, "request_id": self.request_id,
                "source_image": self.source_name, "new_image": self.new_name, "state": self.state,
                "terminal": self.state in TERMINAL, "revision": self.revision, "progress": dict(self.progress),
                "created_at": self.created_at, "result": self.result, "error": self.error,
                "execution_started": self.execution_started, "undo_boundary_created": self.boundary_created,
                "undo_boundary_finalized": self.boundary_finalized, "operation_id": self.operation_id,
                "verification_required": True, "durable": False, "workload": dict(self.workload),
                "external_effects": dict(self.external_effects), "recovery_evidence": dict(self.recovery_evidence),
                "evidence_observation_unknown": list(self.evidence_observation_unknown),
                "duration_ms": round(((self.finished or time.monotonic())-self.started)*1000, 3)}


class PaintJobs:
    """Shared paint/delivery scheduler (legacy class name); no concurrent mutators.

    Domain drivers own their typed workflow, not networking or a second scheduler.
    Network threads touch only the existing lifetime Events.
    """

    def __init__(self, context_factory, budget_ms=lambda: 4.):
        self.context_factory, self.budget_ms = context_factory, budget_ms
        self._main_thread = threading.get_ident()
        self.active: PaintJob | None = None
        self.history: deque[PaintJob] = deque(maxlen=32)

    def _main(self):
        if threading.get_ident() != self._main_thread:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Job control and execution require Blender's main thread.")

    def _lifetime_check(self, job: PaintJob, context: Any):
        """Pure safe point after providers: Events, clock, job and registry only."""
        job.lifetime.check()
        if job.cancel_reason or time.monotonic() >= job.deadline:
            raise BridgeError(ErrorCode.TIMEOUT, "Image job stopped before its next safe action.",
                              {"job_cancel_requested": bool(job.cancel_reason), "reason": job.cancel_reason,
                               "job_deadline_expired": time.monotonic() >= job.deadline})
        spec = context.registry.get(job.method)
        if spec.toolset not in context.registry.enabled_toolsets:
            raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Image job toolset was disabled before its next safe action.",
                              {"tool": job.method, "toolset": spec.toolset})
        if job.in_commit:
            flags = context.state.snapshot()
            if flags["emergency_stopped"] or flags["paused"]:
                raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags["emergency_stopped"] else ErrorCode.AGENT_PAUSED,
                                  "Image publication stopped at its final safe action.")

    def _check(self, job: PaintJob, context: Any):
        self._lifetime_check(job, context)
        required = list(job.required_permissions)
        if job.requires_external_files and Permission.ACCESS_EXTERNAL_FILES not in required:
            required.append(Permission.ACCESS_EXTERNAL_FILES)
        context.require(*required)
        if job.in_commit:
            # A pause during an already-started native call cannot hold half a
            # publication. Stop at the next safe point and retain recovery evidence.
            context.registry.prepare(job.method, context)
        self._lifetime_check(job, context)

    def start(self, context: Any, params: dict, time_limit: float) -> dict:
        self._main()
        if self.active is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "One painting job is already active; inspect/cancel it before starting another.",
                              {"active_job_id": self.active.job_id})
        time_limit = pixel_brush.number(time_limit, "time_limit_seconds", 1., 300.)
        started = time.monotonic()
        prepared = image_paint.prepare_paint(context, params, allow_large=True)
        lifetime = getattr(context, "request_lifecycle", None) or RequestLifetime.local()
        job = PaintJob("job_" + uuid.uuid4().hex, getattr(context, "request_id", ""), prepared["source_name"], prepared["name"],
                       lifetime, started + time_limit, prepared, _identity(prepared["source"]), _metadata(prepared["source"]),
                       prepared["source"].source == "FILE" or bool(prepared["mask"] and prepared["mask"]["requires_external_files"]), started=started)
        pixel_bytes = prepared["width"] * prepared["height"] * 16
        job.workload = {"image_size": [prepared["width"], prepared["height"]],
                        "frozen_source_pixel_bytes": pixel_bytes, "candidate_pixel_tests": prepared["tests"],
                        "coverage_tile_size": pixel_brush.TILE_SIZE,
                        "private_pixel_buffers_peak_estimate_bytes": 2 * pixel_bytes + pixel_brush.TILE_SIZE**2 * 8,
                        "estimate_excludes": "Plan metadata, Blender/native/GPU/undo/file buffers and allocator overhead",
                        "large_image_requires_job": prepared["width"] * prepared["height"] > pixel_brush.MAX_SYNC_PIXELS}
        if prepared["mask"] is not None:
            mask = prepared["mask"]
            job.workload.update(image_paint.masked_memory_estimate(prepared))
            job.workload["mask"] = {"size": [mask["kernel"]["width"], mask["kernel"]["height"]],
                "channel": mask["channel"], "invert": mask["kernel"]["invert"],
                "frozen_channel_bytes": len(mask["kernel"]["values"]) * mask["kernel"]["values"].itemsize}
            job.workload["large_image_requires_job"] |= mask["kernel"]["width"] * mask["kernel"]["height"] > pixel_brush.MAX_SYNC_PIXELS
        self._accept(job, context)
        return {"accepted": True, **job.summary(), "native_commit_interruptible": False,
                "source_frozen_at_acceptance": True, "painting_completed": False}

    def _accept(self, job: PaintJob, context: Any):
        self._check(job, context)
        images._check(context)
        self.active = job
        if job.lifetime.connection is not None:
            job.lifetime.connection.background_active.set()
        try:
            images._check(context)
        except Exception:
            self.cancel_all("start request cancelled")
            raise

    def start_prepared_driver(self, context: Any, params: dict, time_limit: float, *, prepare, required_permissions) -> dict:
        """Trusted domain preparation; preserve the one shared owner/lifecycle.

        Preparation may perform a bounded non-preemptible native input capture.
        Driver CPU work waits for start-response delivery and shares normal tick,
        consent, cancel, pause, undo, terminal history and buffer-release paths.
        """
        self._main()
        if self.active is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "One image job is already active; inspect/cancel it before starting another.",
                              {"active_job_id": self.active.job_id})
        time_limit = pixel_brush.number(time_limit, "time_limit_seconds", 1., 300.)
        started = time.monotonic()
        prepared = prepare(context, params)
        job = PaintJob("job_"+uuid.uuid4().hex, getattr(context, "request_id", ""),
            prepared["source_name"], prepared["name"],
            getattr(context, "request_lifecycle", None) or RequestLifetime.local(), started+time_limit,
            prepared, _identity(prepared["source"]), _metadata(prepared["source"]),
            prepared["requires_external_files"], started=started,
            method=prepared["method"], kind=prepared["kind"], required_permissions=tuple(required_permissions),
            driver=prepared["driver_type"](prepared))
        job.workload = dict(prepared["workload"])
        self._accept(job, context)
        return {"accepted": True, **job.summary(), "job_completed": False,
                "input_frozen_at_acceptance": True, "native_commit_interruptible": False}

    def start_recovery_driver(self, context: Any, params: dict, time_limit: float, *, snapshot: bool) -> dict:
        from .tools.image_recovery_jobs import WRITE, prepare_restore, prepare_snapshot

        return self.start_prepared_driver(context, params, time_limit,
            prepare=prepare_snapshot if snapshot else prepare_restore, required_permissions=WRITE)

    def start_export(self, context: Any, params: dict, time_limit: float) -> dict:
        self._main()
        if self.active is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "One image job is already active; inspect/cancel it before starting another.",
                              {"active_job_id": self.active.job_id})
        time_limit = pixel_brush.number(time_limit, "time_limit_seconds", 1., 300.)
        from .texture_staging import REQUIRED
        from .tools.image_delivery import ExportDriver, prepare_export

        started = time.monotonic()
        prepared = prepare_export(context, params)
        job = PaintJob("job_" + uuid.uuid4().hex, getattr(context, "request_id", ""), prepared["source_name"], prepared["name"],
                       getattr(context, "request_lifecycle", None) or RequestLifetime.local(), started+time_limit,
                       prepared, _identity(prepared["source"]), _metadata(prepared["source"]), True, started=started,
                       method="image.export_job_start", kind="image.export_reimport", required_permissions=REQUIRED,
                       driver=ExportDriver(prepared))
        pixel_bytes = prepared["width"] * prepared["height"] * 16
        job.workload = {"image_size": [prepared["width"], prepared["height"]],
                        "frozen_source_pixel_bytes": pixel_bytes,
                        "private_pixel_buffers_peak_estimate_bytes": 2*pixel_bytes+262144,
                        "estimate_excludes": "Blender/native/GPU/undo buffers, source revalidation copies and allocator overhead",
                        "format": prepared["format"]}
        self._accept(job, context)
        return {"accepted": True, **job.summary(), "export_completed": False,
                "source_frozen_at_acceptance": True, "native_commit_interruptible": False}

    def start_surface_paint(self, context: Any, params: dict, time_limit: float) -> dict:
        """Freeze bounded inputs; defer overlap/raster/visibility/paint work until delivery."""
        self._main()
        if self.active is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "One image job is already active; inspect/cancel it first.",
                              {"active_job_id": self.active.job_id})
        time_limit = pixel_brush.number(time_limit, "time_limit_seconds", 1., 300.)
        from .tools.image_surface_paint import REQUIRED, SurfacePaintDriver, prepare_surface

        started = time.monotonic()
        prepared = prepare_surface(context, params)
        mask = prepared["mask"]
        job = PaintJob("job_" + uuid.uuid4().hex, getattr(context, "request_id", ""), prepared["source_name"], prepared["name"],
                       getattr(context, "request_lifecycle", None) or RequestLifetime.local(), started+time_limit,
                       prepared, _identity(prepared["source"]), _metadata(prepared["source"]),
                       prepared["source"].source == "FILE" or bool(mask and mask["requires_external_files"]), started=started,
                       method="image.paint_surface_job_start", kind="image.paint_surface_version", required_permissions=REQUIRED,
                       driver=SurfacePaintDriver(prepared))
        pixels = prepared["width"]*prepared["height"]
        job.workload = {"image_size": [prepared["width"], prepared["height"]],
                        "frozen_source_pixel_bytes": pixels*16,
                        "private_pixel_buffers_peak_estimate_bytes": pixels*52 + (len(mask["kernel"]["values"])*4 if mask else 0),
                        "estimate_excludes": "Geometry/plan Python objects, input readbacks, Blender/native/GPU/undo/file buffers and allocator overhead",
                        "frozen_geometry_objects": len(prepared["records"]), "frozen_triangles": len(prepared["triangles"]),
                        "projection_work_started": False, "maximum_visibility_triangle_tests": 2_000_000}
        self._accept(job, context)
        return {"accepted": True, **job.summary(), "painting_completed": False,
                "source_and_geometry_frozen_at_acceptance": True, "projection_work_started": False,
                "native_commit_interruptible": False}

    def _native_commit(self, job: PaintJob, context: Any, callback):
        """A driver's one synchronous native publication, never across timer yields."""
        label = f"Image job {job.job_id}: {job.new_name}"
        job.in_commit = True
        job.state = "COMMITTING"
        job.revision += 1
        try:
            job.boundary_created = bool(context.checkpoints.before_modification(label))
            try:
                if not job.boundary_created:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "A recoverable native undo boundary is required before image publication.")
                self._check(job, context)
                context.registry.prepare(job.method, context)
                result = callback()
                self._check(job, context)
            finally:
                if job.boundary_created:
                    job.boundary_finalized = bool(context.checkpoints.after_modification(label))
            if not job.boundary_finalized:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Image job native undo finalization failed; inspect retained effects.", {"possible_mutation": job.execution_started})
            return result
        finally:
            job.in_commit = False

    def _context(self, job: PaintJob):
        context = self.context_factory()
        context.check_cancelled = lambda: self._check(job, context)
        context.request_lifecycle = job.lifetime
        context.check_final_job = lambda: self._lifetime_check(job, context)
        return context

    def _validate_source(self, job: PaintJob, context: Any):
        self._check(job, context)
        bpy = require_blender()
        images._object_mode(bpy)
        source = images.image_exact(bpy, job.source_name)
        if _identity(source) != job.source_identity or _metadata(source) != job.source_metadata:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Painting job source identity/metadata changed; no output was committed.", {"stale_source": True})
        image_paint.source_role(source)  # Animation can be added without changing basic image metadata.
        values, width, height, file = image_paint._read(context, source, modifying=True)
        if ((width, height) != (job.prepared["width"], job.prepared["height"])
                or pixel_brush.digest(values) != job.prepared["source_digest"] or file != job.prepared["source_file"]):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Painting job source pixels or approved file changed; reinspect before restarting.", {"stale_source": True})
        if bpy.data.images.get(job.new_name) is not None:
            raise invalid_argument("The painting job's output name is now in use; no overwrite or implicit rename is allowed.")
        job.prepared["source"] = source
        image_masks.validate(context, bpy, job.prepared.get("mask"), read=image_paint._read)

    def _commit(self, job: PaintJob, context: Any, output):
        self._validate_source(job, context)
        job.state, job.progress = "COMMITTING", {"phase": "committing", "completed": 0, "total": 1}
        job.revision += 1
        label = f"Paint job {job.job_id}: {job.new_name}"
        job.in_commit = True
        job.boundary_created = bool(context.checkpoints.before_modification(label))
        try:
            if not job.boundary_created:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "A recoverable native undo boundary is required before publishing a painting job.")
            self._check(job, context)
            context.registry.prepare(START_METHOD, context)
            self._validate_source(job, context)
            job.execution_started = True
            result = image_paint.finish_paint(context, job.prepared, *output)
            self._check(job, context)
        finally:
            if job.boundary_created:
                job.boundary_finalized = bool(context.checkpoints.after_modification(label))
        if not job.boundary_finalized:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Paint image exists but native undo finalization failed; reinspect before further edits.", {"possible_mutation": True})
        job.result = result
        self._finish(job, "SUCCEEDED")

    def _finish(self, job: PaintJob, state: str, error: BridgeError | None = None):
        if job.state in TERMINAL:
            return
        if job.work is not None:
            work = job.work
            job.work = None
            try:
                work.close()
            except Exception as failure:
                LOGGER.exception("Image-job generator close failed")
                state, error = "FAILED", BridgeError(ErrorCode.OPERATION_FAILED, "Image-job private work did not close cleanly; inspect retained effects.",
                                                     {"exception_type": type(failure).__name__, "cleanup_outcome_unknown": True})
        if job.driver is not None:
            try:
                job.external_effects = job.driver.cleanup(self._context(job), job, success=state == "SUCCEEDED")
                if state == "SUCCEEDED":
                    context = self._context(job)
                    self._check(job, context)
                    context.registry.prepare(job.method, context)
            except BridgeError as failure:
                error = failure
                state = "CANCELLED" if failure.code in {ErrorCode.TIMEOUT.value, ErrorCode.EMERGENCY_STOPPED.value} else "FAILED"
            except Exception as failure:
                LOGGER.exception("Image-job terminal cleanup failed")
                state, error = "FAILED", BridgeError(ErrorCode.OPERATION_FAILED, "Image-job cleanup could not be fully verified.",
                                                     {"exception_type": type(failure).__name__, "cleanup_outcome_unknown": True})
            finally:
                # Cleanup failures cannot erase already observed file effects.
                unknown = job.observe_evidence()
                if unknown:
                    if error is None:
                        state, error = "FAILED", BridgeError(ErrorCode.OPERATION_FAILED,
                            "Image-job final effects could not be observed; last observations may be stale.")
                    error.context["evidence_observation_unknown"] = unknown
                if job.recovery_evidence:
                    job.recovery_evidence.setdefault("possible_mutation", bool(job.execution_started))
                job.driver = None
            if job.result is not None:
                job.result["external_effects"] = dict(job.external_effects)
                if job.recovery_evidence:
                    job.result["recovery_evidence"] = dict(job.recovery_evidence)
            if state != "SUCCEEDED":
                job.result = None
        job.state = state
        job.finished = time.monotonic()
        job.revision += 1
        if error is not None:
            error.context.update({"job_id": job.job_id, "requested_image": job.new_name,
                                  "execution_started": job.execution_started,
                                  "undo_boundary_created": job.boundary_created,
                                  "undo_boundary_finalized": job.boundary_finalized,
                                  "verification_required": True})
            if job.external_effects:
                error.context["external_effects"] = dict(job.external_effects)
            if job.recovery_evidence:
                error.context["recovery_evidence"] = dict(job.recovery_evidence)
            external_possible = bool(job.external_effects.get("file_published") or job.external_effects.get("publication_outcome_unknown")
                                     or job.external_effects.get("retained_staging_path"))
            if external_possible:
                error.context["native_image_rollback_verified"] = error.context.get("rollback_verified", False)
                error.context["rollback_verified"] = False
                error.context["possible_mutation"] = True
            elif not job.execution_started:
                error.context["possible_mutation"] = False
            elif "possible_mutation" not in error.context:
                error.context["possible_mutation"] = True
            job.error = error.to_dict()
        job.progress = {**job.progress, "phase": state.lower()}
        if state == "SUCCEEDED":
            job.progress = {"phase": "succeeded", "completed": 1, "total": 1}
        job.prepared.clear()  # Release all source/output buffers and bpy handles.
        if job.lifetime.connection is not None:
            job.lifetime.connection.background_active.clear()
        try:
            record = self.context_factory().state.record_operation(tool=job.method,
                description=f"Image job {job.job_id} {state.lower()}: {job.new_name}; verify state",
                success=state == "SUCCEEDED", duration_ms=(job.finished - job.started) * 1000,
                error_code=error.code if error else None,
                recovery_evidence=job.recovery_evidence or None,
                **({"job_evidence": {"job_id": job.job_id, "state": state, "external_effects": dict(job.external_effects),
                                     "execution_started": job.execution_started, "undo_boundary_finalized": job.boundary_finalized,
                                     "evidence_observation_unknown": list(job.evidence_observation_unknown)}}
                   if job.external_effects or job.recovery_evidence or job.evidence_observation_unknown else {}))
            job.operation_id = record.operation_id
        except Exception:
            LOGGER.exception("Image-job operation history recording failed")
            job.error = BridgeError(ErrorCode.OPERATION_FAILED, "Image-job history could not be recorded; inspect terminal evidence.",
                                    {"operation_history_unknown": True, "possible_mutation": job.execution_started}).to_dict()
            job.state, job.result = "FAILED", None
            job.progress = {**job.progress, "phase": "failed"}
        finally:
            self.history.appendleft(job)
            if self.active is job:
                self.active = None

    def tick(self) -> bool:
        self._main()
        job = self.active
        if job is None:
            return False
        context = self._context(job)
        job.in_tick = True
        try:
            self._check(job, context)
            snapshot = context.state.snapshot()
            if snapshot["emergency_stopped"]:
                raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Painting job emergency-stopped.")
            if snapshot["paused"]:
                if job.state != "PAUSED":
                    job.state = "PAUSED"
                    job.revision += 1
                return True
            if not job.lifetime.delivered.is_set():
                return True
            context.registry.prepare(job.method, context)
            job.state = "RUNNING"
            if job.work is None:
                prepared = job.prepared
                job.work = job.driver.steps(context, job, lambda callback: self._native_commit(job, context, callback)) if job.driver is not None else pixel_brush.paint_steps(prepared.pop("values"), prepared["width"], prepared["height"], prepared["strokes"],
                    prepared["role"], srgb=prepared["srgb"], mask=prepared["mask"]["kernel"] if prepared["mask"] else None,
                    associated=prepared["associated"],
                    check=lambda: self._check(job, context))
            budget = self.budget_ms()
            budget = min(8., max(1., float(budget))) if isinstance(budget, (int, float)) and math.isfinite(budget) else 4.
            deadline = time.perf_counter() + budget / 1000
            while time.perf_counter() < deadline:
                self._check(job, context)
                flags = context.state.snapshot()
                if flags["paused"] and not flags["emergency_stopped"]:
                    job.state = "PAUSED"
                    job.revision += 1
                    return True
                context.registry.prepare(job.method, context)
                try:
                    job.progress = next(job.work)
                    job.revision += 1
                except StopIteration as completed:
                    if job.driver is None:
                        self._commit(job, context, completed.value)
                    else:
                        job.result = completed.value
                        self._finish(job, "SUCCEEDED")
                    return False
        except BridgeError as error:
            cancelled = error.code in {ErrorCode.TIMEOUT.value, ErrorCode.EMERGENCY_STOPPED.value}
            self._finish(job, "CANCELLED" if cancelled else "FAILED", error)
        except Exception as error:
            LOGGER.exception("Image job failed outside its typed error path")
            self._finish(job, "FAILED", BridgeError(ErrorCode.OPERATION_FAILED, "Image job failed; inspect its recovery/file evidence.",
                                                    {"exception_type": type(error).__name__}))
        finally:
            job.in_tick = False
        return self.active is not None

    def inspect(self, job_id: str) -> dict:
        self._main()
        for job in ([self.active] if self.active else []) + list(self.history):
            if job.job_id == job_id:
                return job.summary()
        raise invalid_argument("Job ID is missing or no longer retained in this bridge session.")

    def list(self, limit=10) -> dict:
        self._main()
        jobs = ([self.active] if self.active else []) + list(self.history)
        return {"jobs": [job.summary() for job in jobs[:limit]], "total": len(jobs), "truncated": len(jobs) > limit,
                "max_active": 1, "terminal_history_limit": 32, "durable": False}

    def status(self) -> dict:
        """Minimal control/status evidence, not an INSPECT_SCENE bypass."""
        self._main()
        def compact(job):
            return {key: value for key, value in job.summary().items()
                    if key in {"job_id", "kind", "state", "terminal", "revision", "progress"}}
        return {"active": compact(self.active) if self.active else None,
                "last_terminal": compact(self.history[0]) if self.history else None,
                "max_active": 1, "terminal_history_limit": 32, "durable": False}

    def cancel(self, job_id: str) -> dict:
        self._main()
        summary = self.inspect(job_id)
        if self.active is not None and self.active.job_id == job_id:
            self.active.cancel_reason = "explicit cancellation"
            self.active.state = "CANCELLING"
            self.active.revision += 1
            summary = self.active.summary()
        return {"cancel_requested": not summary["terminal"], "job_id": job_id,
                "state": summary["state"], "terminal": summary["terminal"],
                "verification_required": True}

    def cancel_all(self, reason: str):
        self._main()
        if self.active is not None:
            job = self.active
            job.cancel_reason = reason
            if job.in_tick or job.in_commit:
                # Native callbacks can re-enter stop/undo handlers. Do not release
                # buffers underneath publication; unwind at the next safe point.
                job.revision += 1
                return
            self._finish(job, "CANCELLED", BridgeError(ErrorCode.TIMEOUT, "Image job cancelled by bridge lifecycle.", {"reason": reason}))
