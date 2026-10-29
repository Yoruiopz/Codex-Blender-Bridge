"""Owned Scene phases composed with the existing image-job controller.

Only trusted in-process adapters can start these records. No public simulation
tool is registered here. All inspection uses cached evidence, never Blender.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from types import FunctionType, GetSetDescriptorType, ModuleType
from typing import Any

from .checkpoint_completion import claim_native_push_completion
from .errors import BridgeError, ErrorCode, invalid_argument
from .job_controller import TERMINAL
from .jobs import PaintJobs
from .mesh_storage_effects import MeshStorageJournal, snapshot_storage_effects
from .protocol import utc_timestamp
from .request_lifecycle import RequestLifetime
from .scene_job_authority import SceneJobAuthority, bind_permissions
from .scene_job_effects import EffectsStatus, SceneNativeEffects, snapshot_native_effects
from .scene_job_evidence import phase as phase_report
from .scene_job_evidence import plain
from .scene_job_evidence import progress as progress_report
from .scene_job_reservations import TURN_METHOD, refused
from .task_plans import get_task_plans
from .tool_registry import check_final_mutation


def _storage_function_fact(function):
    if type(function) is not FunctionType:
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    keywords = function.__kwdefaults__
    if keywords is not None and (type(keywords) is not dict or any(type(key) is not str for key in keywords)):
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    return (function, function.__code__, function.__globals__, function.__defaults__, keywords,
            () if keywords is None else tuple(keywords.items()),
            tuple((cell, cell.cell_contents) for cell in function.__closure__ or ()))


def _storage_class_facts(kind):
    if type(kind) is not type:
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    result = []
    for base in type.__dict__["__mro__"].__get__(kind):
        if type(base) is not type:
            raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
        fields = type.__dict__["__dict__"].__get__(base)
        if len(fields) > 512 or any(type(key) is not str for key in fields):
            raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
        functions = tuple(_storage_function_fact(value) for value in fields.values() if type(value) is FunctionType)
        result.append((base, type.__dict__["__mro__"].__get__(base), tuple(fields.items()), functions))
    return tuple(result)


def _capture_storage_driver(driver):
    """Recognize one concrete private domain, without probing other drivers."""
    kind = type(driver)
    if type(kind) is not type:
        return None
    native_fields = type.__dict__["__dict__"].__get__(kind)
    module_name = native_fields.get("__module__")
    if type(module_name) is not str or module_name != __package__ + ".tools._mesh_storage_job":
        return None
    import sys
    module = sys.modules.get(__package__ + ".tools._mesh_storage_job")
    if type(module) is not ModuleType or vars(module).get("MeshStorageDriver") is not kind:
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    facts = _storage_class_facts(kind)
    descriptor = next((value for _base, _mro, fields, _functions in facts
                       for name, value in fields if name == "__dict__"), None)
    if type(descriptor) is not GetSetDescriptorType:
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    fields = descriptor.__get__(driver, kind)
    if type(fields) is not dict or any(type(key) is not str for key in fields):
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    source, journal = fields.get("source_seal"), fields.get("storage_effects")
    source_module = sys.modules.get(__package__ + ".mesh_storage_source")
    if type(source_module) is not ModuleType or type(source) is not vars(source_module).get("SourceSeal"):
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    source_facts = _storage_class_facts(type(source))
    verify = next((value for _base, _mro, rows, _functions in source_facts for name, value in rows if name == "verify"), None)
    if type(journal) is not MeshStorageJournal:
        raise refused("MESH_STORAGE_EFFECTS_INVALID")
    native = (type, len, any, zip, type.__dict__["__dict__"], type.__dict__["__mro__"], dict, str, bool)
    failure = refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    owned = tuple((name, fields[name]) for name in ("gate", "origin", "bpy", "initial", "bindings", "parameters",
                  "excluded", "protected", "protected_digest", "fingerprint", "completed", "value_hashes",
                  "checkpoint_roles", "checkpoint_origin") if name in fields)
    proof = (driver, kind, facts, descriptor, source, source_facts, verify, _storage_function_fact(verify), journal,
             native, failure, owned)
    _check_storage_driver(proof)
    return proof


def _check_storage_driver(proof):
    """Pure held-source check before the source verifier or a driver callback."""
    driver, kind, class_facts, descriptor, source, source_facts, verify, verify_facts, journal, native, failure, owned = proof
    type_of, length, any_of, zip_pairs, class_dict, class_mro, dict_type, str_type, bool_type = native
    if type_of(driver) is not kind:
        raise failure
    for base, mro, saved, functions in (*class_facts, *source_facts):
        fields = class_dict.__get__(base)
        if (class_mro.__get__(base) is not mro or length(fields) != length(saved)
                or any_of(type_of(key) is not str_type for key in fields)
                or any_of(name not in fields or fields[name] is not value for name, value in saved)):
            raise failure
        for function, code, namespace, defaults, keywords, keyword_rows, cells in functions:
            closure = function.__closure__ or ()
            if (function.__code__ is not code or function.__globals__ is not namespace
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
                    or (keywords is not None and (type_of(keywords) is not dict_type or length(keywords) != length(keyword_rows)
                        or any_of(type_of(key) is not str_type for key in keywords)
                        or any_of(name not in keywords or keywords[name] is not value for name, value in keyword_rows)))
                    or length(closure) != length(cells)
                    or any_of(actual is not cell or actual.cell_contents is not value
                              for actual, (cell, value) in zip_pairs(closure, cells, strict=True))):
                raise failure
    fields = descriptor.__get__(driver, kind)
    if (type_of(fields) is not dict_type or any_of(type_of(key) is not str_type for key in fields)
            or any_of(name in fields for name in ("check_after_read", "advance", "native_push_delegates", "after_native_push"))
            or fields.get("source_seal") is not source or fields.get("storage_effects") is not journal
            or any_of(fields.get(name) is not value for name, value in owned)
            or type_of(fields.get("done")) is not bool_type or type_of(fields.get("phase")) is not str_type):
        raise failure
    # verify's complete class/function facts were just checked without calling
    # it. The exact held function cannot be swapped by an instance attribute.
    if verify is not verify_facts[0]:
        raise failure
    verify(source)


def _guard_storage_job(job):
    proof = job.storage_driver_proof
    if proof is not None:
        if job.driver is not proof[0] or job.storage_effects is not proof[8]:
            raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
        _check_storage_driver(proof)


def _storage_turn_scope(context, _params):
    job = context.registry._scene_reservations.current(context).owner.job
    _guard_storage_job(job)
    if job.storage_driver_proof is None or job.storage_scope is None:
        raise refused("MESH_STORAGE_TURN_SCOPE_UNAVAILABLE")
    spec, resolver, params = job.storage_scope
    if context.registry.get(spec.name) is not spec or spec.protected_scope_resolver is not resolver:
        raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
    return resolver(context, params)


def _storage_reader_fact():
    module = snapshot_storage_effects.__globals__
    functions = tuple(_storage_function_fact(value) for value in module.values() if type(value) is FunctionType)
    classes = tuple(_storage_class_facts(value) for value in module.values()
                    if type(value) is type and value.__module__ == __package__ + ".mesh_storage_effects")
    tables = []
    for function, *_facts in (*functions, *(fact for rows in classes for row in rows for fact in row[3])):
        table = function.__builtins__
        if not any(table is held for held, _saved in tables):
            if type(table) is not dict or any(type(name) is not str for name in table):
                raise refused("MESH_STORAGE_EFFECTS_SOURCE_CHANGED")
            tables.append((table, tuple(table.items())))
    native = (type, len, any, zip, dict, str, type.__dict__["__dict__"].__get__,
              type.__dict__["__mro__"].__get__, refused("MESH_STORAGE_EFFECTS_SOURCE_CHANGED"))
    return (snapshot_storage_effects, tuple(module.items()), functions, classes, native, tuple(tables))


def _storage_snapshot(job, *, seal=False):
    function, saved, functions, classes, native, tables = job.storage_reader_proof
    type_of, length, any_of, zip_pairs, dict_type, str_type, class_dict, class_mro, failure = native
    # Finalization intentionally skips the stopped driver/source verifier. Its
    # reader must therefore prove itself using bindings retained before stop,
    # including an already-created error rather than a mutable error factory.
    for table, entries in tables:
        if (type_of(table) is not dict_type or length(table) != length(entries)
                or any_of(type_of(name) is not str_type for name in table)
                or any_of(name not in table or table[name] is not value for name, value in entries)):
            raise failure
    namespace = function.__globals__
    if (length(namespace) != length(saved) or any_of(type_of(name) is not str_type for name in namespace)
            or any_of(name not in namespace or namespace[name] is not value for name, value in saved)):
        raise failure
    for owner, mro, fields, methods in (row for rows in classes for row in rows):
        current = class_dict(owner)
        if (class_mro(owner) is not mro or length(current) != length(fields)
                or any_of(type_of(name) is not str_type for name in current)
                or any_of(name not in current or current[name] is not value for name, value in fields)):
            raise failure
        for fact in methods:
            functions = (*functions, fact)
    for callback, code, globals_, defaults, keywords, keyword_rows, cells in functions:
        closure = callback.__closure__ or ()
        if (callback.__code__ is not code or callback.__globals__ is not globals_ or callback.__defaults__ is not defaults
                or callback.__kwdefaults__ is not keywords or length(closure) != length(cells)
                or (keywords is not None and (type_of(keywords) is not dict_type or length(keywords) != length(keyword_rows)
                    or any_of(type_of(key) is not str_type for key in keywords)
                    or any_of(name not in keywords or keywords[name] is not value for name, value in keyword_rows)))
                or any_of(actual is not cell or actual.cell_contents is not value
                          for actual, (cell, value) in zip_pairs(closure, cells, strict=True))):
            raise failure
    if seal:
        namespace["seal_storage_effects"](job.storage_effects)
    return function(job.storage_effects)


@dataclass(frozen=True, slots=True, eq=False)
class _StartAdmission:
    context: Any
    params: Any
    authority: SceneJobAuthority
    allowlist: tuple
    state_origin: tuple
    markers: Any
    driver: Any
    required_permissions: tuple
    kind: str
    label: str
    native_effects: Any
    storage_effects: Any
    storage_driver_proof: Any
    storage_reader_proof: Any
    storage_scope: Any
    storage_context_proof: Any

    def __init__(self, context, params, factory):
        authority = SceneJobAuthority.capture(context, params)
        allowlist = context.registry._scene_reservations.capture_allowlist()
        state_origin = (context.state, get_task_plans(context.state), get_task_plans(context.state).evidence_epoch)
        markers = context.checkpoints.capture_job_markers()
        driver = factory(context, params)  # Freeze authored inputs before providers.
        storage_driver_proof = _capture_storage_driver(driver)
        storage_effects = None if storage_driver_proof is None else storage_driver_proof[8]
        storage_reader_proof = None if storage_driver_proof is None else _storage_reader_fact()
        storage_scope = None
        if storage_driver_proof is not None:
            spec = context.registry.get(authority.method)
            resolver = spec.protected_scope_resolver
            if type(resolver) is not FunctionType:
                raise refused("MESH_STORAGE_TURN_SCOPE_UNAVAILABLE")
            storage_scope = (spec, resolver, plain(params, field="mesh_storage_start_params"))
        authority = authority.include_driver_permissions(tuple(driver.required_permissions))
        kind, label = plain(driver.kind), plain(driver.label)
        native_effects = getattr(driver, "native_effects", None)
        if native_effects is not None and type(native_effects) is not SceneNativeEffects:
            raise refused("SCENE_NATIVE_EFFECTS_INVALID")
        if type(kind) is not str or type(label) is not str or not kind or not label:
            raise refused("SCENE_JOB_EVIDENCE_INVALID")
        for name, value in (("context", context), ("params", params), ("authority", authority), ("allowlist", allowlist),
                            ("state_origin", state_origin), ("markers", markers), ("driver", driver),
                            ("required_permissions", authority.required_permissions), ("kind", kind), ("label", label),
                            ("native_effects", native_effects), ("storage_effects", storage_effects),
                            ("storage_driver_proof", storage_driver_proof), ("storage_reader_proof", storage_reader_proof),
                            ("storage_scope", storage_scope), ("storage_context_proof", None)):
            object.__setattr__(self, name, value)

    def bind_checkpoint(self, _binding):
        if self.storage_driver_proof is not None:
            _check_storage_driver(self.storage_driver_proof)
            from .mesh_storage_source import capture_context
            object.__setattr__(self, "storage_context_proof", capture_context(self.context, self.storage_driver_proof[4]))

    def __call__(self):
        if self.storage_driver_proof is not None:
            _check_storage_driver(self.storage_driver_proof)
            from .mesh_storage_source import verify_context
            verify_context(self.context, self.storage_context_proof)
        self.context.require(*self.required_permissions)
        self.check_after_read()

    def check_after_read(self):
        if self.storage_driver_proof is not None:
            if self.driver is not self.storage_driver_proof[0]:
                raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
            _check_storage_driver(self.storage_driver_proof)
            from .mesh_storage_source import verify_context
            verify_context(self.context, self.storage_context_proof)
        check_final_mutation(self.context, self.context.checkpoint_method)
        self.authority.check()
        state, store, epoch = self.state_origin
        if self.context.state is not state or getattr(state, "_artist_task_plans", None) is not store or store.evidence_epoch != epoch:
            raise refused("SCENE_RUNTIME_RESET")
        self.context.registry._scene_reservations.check_allowlist(self.allowlist)
        self.context.checkpoints.check_job_markers(self.markers)
        if self.storage_driver_proof is not None:
            if self.driver is not self.storage_driver_proof[0]:
                raise refused("MESH_STORAGE_DRIVER_SOURCE_CHANGED")
            _check_storage_driver(self.storage_driver_proof)
        self.driver.check_after_read(self.context)
        check_final_mutation(self.context, self.context.checkpoint_method)


def start_admission(driver_factory):
    """Trusted adapter factory; not an authorization supplied by request data."""
    return lambda context, params: _StartAdmission(context, params, driver_factory)


class _TurnAdmission:
    def __init__(self, context):
        self.context = context
        self.service = context.registry._scene_reservations
        self.turn = self.service.current(context)
        self.job = self.turn.owner.job
        self.storage_context_proof = None

    def bind_checkpoint(self, _binding):
        if self.job.storage_driver_proof is not None:
            _guard_storage_job(self.job)
            from .mesh_storage_source import capture_context
            self.storage_context_proof = capture_context(self.context, self.job.storage_driver_proof[4])

    def __call__(self):
        if self.storage_context_proof is not None:
            _guard_storage_job(self.job)
            from .mesh_storage_source import verify_context
            verify_context(self.context, self.storage_context_proof)
        self.context.require(*self.turn.owner.authority.required_permissions)
        self.check_after_read()

    def check_after_read(self):
        if self.storage_context_proof is not None:
            _guard_storage_job(self.job)
            from .mesh_storage_source import verify_context
            verify_context(self.context, self.storage_context_proof)
        self.service.check_turn(self.turn.token)
        self.job.checkpoint_manager.check_pending_markers(self.job.pending, self.turn.token)
        _guard_storage_job(self.job)
        self.job.driver.check_after_read(self.context)
        check_final_mutation(self.context, TURN_METHOD)

    def native_push_delegates(self):
        _guard_storage_job(self.job)
        return self.job.driver.native_push_delegates()

    def after_native_push(self):
        claim_native_push_completion(self.context, TURN_METHOD, self)
        self.service.check_turn(self.turn.token)
        _guard_storage_job(self.job)
        self.job.driver.after_native_push()


@dataclass(slots=True)
class SceneJob:
    job_id: str
    request_id: str
    lifetime: RequestLifetime
    deadline: float
    driver: Any
    checkpoint_manager: Any
    kind: str
    label: str
    required_permissions: tuple
    state_origin: tuple
    authority: SceneJobAuthority
    method: str = TURN_METHOD
    phase: str = "checkpoint_before"
    state: str = "QUEUED"
    revision: int = 1
    created_at: str = field(default_factory=utc_timestamp)
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    progress: dict = field(default_factory=lambda: {"phase": "awaiting_start_delivery", "completed": 0, "total": 1})
    checkpoint: dict = field(default_factory=dict)
    effects: dict = field(default_factory=lambda: {"domain_phases_completed": 0, "native_cleanup_attempted": False})
    reservation: Any = None
    pending: Any = None
    work: Any = None
    cancel_reason: str = ""
    in_tick: bool = False
    in_commit: bool = False
    execution_started: bool = False
    boundary_created: bool = False
    boundary_finalized: bool = False
    result: Any = None
    error: dict | None = None
    operation_id: str | None = None
    terminal_state: str | None = None
    terminal_abandoned: bool = False
    terminal_history_attempted: bool = False
    terminal_ledger_written: bool = False
    terminal_retired: bool = False
    terminal_pending_released: bool = False
    terminal_primary: BridgeError | None = None
    terminal_error_captured: bool = False
    native_effects: SceneNativeEffects | None = None
    native_effects_snapshot: dict | None = None
    storage_effects: MeshStorageJournal | None = None
    storage_effects_snapshot: dict | None = None
    storage_driver_proof: Any = None
    storage_reader_proof: Any = None
    storage_scope: Any = None

    def summary(self):
        return plain({"job_id": self.job_id, "kind": self.kind, "label": self.label, "request_id": self.request_id,
                "start_method": self.authority.method, "start_toolset": self.authority.toolset,
                "required_permissions": [permission.value for permission in self.authority.required_permissions],
                "state": self.state, "terminal": self.state in TERMINAL, "revision": self.revision,
                "phase": self.phase, "progress": dict(self.progress), "checkpoint": dict(self.checkpoint),
                "effects": dict(self.effects), "result": self.result, "error": self.error,
                **({"storage_effects": (self.storage_effects_snapshot if self.storage_effects_snapshot is not None
                                       else _storage_snapshot(self))} if self.storage_effects is not None else {}),
                **({"native_effects": (self.native_effects_snapshot if self.native_effects_snapshot is not None
                                      else snapshot_native_effects(self.native_effects))} if self.native_effects is not None else {}),
                "execution_started": self.execution_started, "undo_boundary_created": self.boundary_created,
                "undo_boundary_finalized": self.boundary_finalized, "operation_id": self.operation_id,
                "created_at": self.created_at, "verification_required": True, "durable": False,
                "duration_ms": round(((self.finished or time.monotonic())-self.started)*1000, 3)},
                field="summary", byte_limit=262144, item_limit=16384, depth_limit=16)


class SceneJobs(PaintJobs):
    """One shared active record; exact-type routing preserves image policies."""

    def __init__(self, context_factory, budget_ms=lambda: 4., *, registry, recovery_limit=8):
        super().__init__(context_factory, budget_ms)
        self.registry = registry
        self.reservations = registry._scene_reservations
        self.recovery_limit = recovery_limit
        self.recovery_ledger: dict[str, dict] = {}
        self._scene_records: dict[int, SceneJob] = {}
        self._turn_spec = registry.register(TURN_METHOD, self._advance, modifies=True, remote=False,
            batchable=False, record_history=False, automatic_checkpoint=False, exclusive_mutation=True,
            protected_scope_resolver=_storage_turn_scope,
            checkpoint_owns_finalization=True, checkpoint_admission_factory=lambda context, params: _TurnAdmission(context))

    def _scene(self, job):
        if type(job) is not SceneJob:
            return False
        if job.state in TERMINAL:
            return True
        if self._scene_records.get(id(job)) is not job:
            raise refused("SCENE_RECORD_LOST")
        return True

    def start_scene(self, context, params, *, time_limit=60.):
        self._main()
        if self.active is not None:
            raise refused("SCENE_JOB_BUSY")
        if len(self.recovery_ledger) >= self.recovery_limit:
            raise refused("SCENE_RECOVERY_LEDGER_FULL")
        if type(time_limit) not in {int, float} or not 1. <= time_limit <= 300.:
            raise invalid_argument("Scene job time limit must be between 1 and 300 seconds.")
        binding = context.checkpoint_admission
        admission = None if binding is None else binding.callback
        if (type(admission) is not _StartAdmission or admission.context is not context
                or admission.params is not params or not binding.active):
            raise refused("SCENE_START_ADMISSION_REQUIRED")
        binding.check_after_read()
        driver = admission.driver
        job = SceneJob("job_"+uuid.uuid4().hex, context.request_id,
            context.request_lifecycle or RequestLifetime.local(), time.monotonic()+time_limit,
            driver, context.checkpoints, admission.kind, admission.label, admission.required_permissions, admission.state_origin,
            admission.authority)
        job.native_effects = admission.native_effects
        job.storage_effects, job.storage_driver_proof = admission.storage_effects, admission.storage_driver_proof
        job.storage_reader_proof, job.storage_scope = admission.storage_reader_proof, admission.storage_scope
        start_origin = object()  # Caller-local; the reservation stores only its ID.
        job.reservation = self.reservations.reserve(job, start_origin, allowlist=admission.allowlist, authority=admission.authority)
        try:
            job.pending = context.checkpoints.claim_pending(job.reservation, job.label, markers=admission.markers)
            job.checkpoint = context.checkpoints.pending_status(job.pending)
            self._scene_records[id(job)] = job
            self.active = job
            self.reservations.activate(job.reservation, start_origin)
        except BaseException as primary:
            try:
                context.checkpoints.discard_unstarted_pending(job.reservation, start_origin)
                self.reservations.discard_unaccepted(job.reservation, start_origin)
                if self._scene_records.get(id(job)) is job:
                    self._scene_records.pop(id(job))
                if self.active is job:
                    self.active = None
            except Exception as secondary:
                if isinstance(primary, BridgeError):
                    primary.context["scene_start_abort_unknown"] = type(secondary).__name__
                else:
                    # Exception notes are available from Python 3.11. Optional
                    # diagnostics must never replace the original start error.
                    try:
                        add_note = getattr(primary, "add_note", None)
                        if callable(add_note):
                            add_note("Scene start metadata abort could not be verified: "+type(secondary).__name__)
                        else:
                            primary.scene_start_abort_unknown = type(secondary).__name__
                    except Exception:
                        pass
            raise
        context.checkpoint_finalization_owner = context.checkpoint_call_id
        if job.lifetime.connection is not None:
            job.lifetime.connection.background_active.set()
        return {"accepted": True, **job.summary(), "job_completed": False,
                "native_commit_interruptible": False, "input_frozen_at_acceptance": True}

    def _context(self, job):
        if not self._scene(job):
            return super()._context(job)
        context = self.context_factory()
        bind_permissions(context, self.reservations)
        context.request_lifecycle, context.request_id = job.lifetime, job.request_id
        context.check_final_request = None  # A delivered start is no longer a queued RPC.
        context.check_cancelled = lambda: self._check(job, context)
        context.check_final_job = lambda: self.reservations.check_job(job.reservation)
        return context

    def _check(self, job, context):
        if not self._scene(job):
            return super()._check(job, context)
        self.reservations.check_job(job.reservation)
        if self.registry.get(TURN_METHOD) is not self._turn_spec:
            raise refused("SCENE_TURN_SPEC_CHANGED")

    def _tick_scope(self, job):
        return self.reservations.scheduler_scope(job.reservation) if self._scene(job) else super()._tick_scope(job)

    def _guard_context_creation(self, job):
        return True if self._scene(job) else super()._guard_context_creation(job)

    def _tick_owned(self, job, control):
        if not self._scene(job) or job.terminal_state is None:
            return super()._tick_owned(job, control)
        job.in_tick = True
        try:
            self._finish(job, job.terminal_state, _origin=control)
        finally:
            job.in_tick = False
        return self.active is not None

    def _tick_check(self, job, context, control):
        if not self._scene(job):
            return super()._tick_check(job, context, control)
        self._check(job, context)
        token = self.reservations.issue_turn(job.reservation, job.phase, job.revision, origin=control, check_only=True)
        previous = context.check_final_job
        context.check_final_job = lambda: self.reservations.check_turn(token)
        try:
            self.registry.invoke_scene_turn(token, {}, context, job.checkpoint_manager, check_only=True)
        finally:
            self.reservations.close_turn(token)
            context.check_final_job = previous

    def _prepare_step(self, job, context):
        if not self._scene(job):
            return super()._prepare_step(job, context)
        self.reservations.check_job(job.reservation)

    def _budget_for(self, job):
        return 4. if self._scene(job) else super()._budget_for(job)

    def _work_step_limit(self, job):
        return 1 if self._scene(job) else super()._work_step_limit(job)

    def _make_work(self, job, context):
        if not self._scene(job):
            return super()._make_work(job, context)
        return object()  # No generator can retain a turn capability across yields.

    def _advance_work(self, job, context, control):
        if not self._scene(job):
            return super()._advance_work(job, context, control)
        context = self._context(job)
        token = self.reservations.issue_turn(job.reservation, job.phase, job.revision, origin=control)
        context.check_final_job = lambda: self.reservations.check_turn(token)
        try:
            progress = self.registry.invoke_scene_turn(token, {}, context, job.checkpoint_manager,
                                                       checkpoint_phase=self._checkpoint_phase)
        finally:
            self.reservations.close_turn(token)
            job.checkpoint = job.checkpoint_manager.pending_status(job.pending)
        completed = job.phase == "checkpoint_after"
        _guard_storage_job(job)
        if job.phase == "checkpoint_before":
            job.phase = phase_report(job.driver.phase)
        elif not completed:
            job.phase = "checkpoint_after" if job.driver.done else phase_report(job.driver.phase)
        if completed:
            raise StopIteration(job.result)
        return progress

    def _advance(self, context, params):
        turn = self.reservations.current(context)
        job = turn.owner.job
        if not self._scene(job) or self.active is not job:
            raise refused("SCENE_RECORD_LOST")
        _guard_storage_job(job)
        facts = job.checkpoint_manager.pending_status(job.pending)
        if turn.phase == "checkpoint_after" and (not job.driver.done or not facts["before_verified"]):
            raise refused("SCENE_PHASE_SEQUENCE_CHANGED")
        if turn.phase in {"checkpoint_before", "checkpoint_after"}:
            return {"phase": turn.phase, "completed": 0, "total": 1}
        if not facts["before_verified"] or job.driver.done or turn.phase != job.driver.phase:
            raise refused("SCENE_PHASE_SEQUENCE_CHANGED")
        job.execution_started = True
        progress = job.driver.advance(context)
        job.effects["domain_phases_completed"] += 1
        # The driver has advanced its own phase; the frozen scheduler revision
        # changes only after this invocation has fully unwound.
        context.checkpoint_admission.check_after_read()
        progress = progress_report(progress)
        phase_report(job.driver.phase)
        if type(job.driver.done) is not bool:
            raise refused("SCENE_JOB_EVIDENCE_INVALID")
        if job.driver.done:
            job.result = plain(job.driver.result, field="result")
        return progress

    def _checkpoint_phase(self, token, context, consumer):
        turn = self.reservations.current(context)
        job, binding = turn.owner.job, context.checkpoint_admission

        def before():
            binding()
            check_final_mutation(context, TURN_METHOD)

        def after():
            binding.check_after_read()
            check_final_mutation(context, TURN_METHOD)

        method = (job.checkpoint_manager.before_modification if turn.phase == "checkpoint_before"
                  else job.checkpoint_manager.after_modification)
        verified = method(job.label, pending=job.pending, turn=token, before_write=before,
                          after_read=after, after_native_push=consumer)
        if not verified:
            raise refused("SCENE_CHECKPOINT_UNVERIFIED")
        job.boundary_created = True
        job.boundary_finalized = turn.phase == "checkpoint_after"
        return {"phase": turn.phase, "completed": 1, "total": 1}

    def _complete_tick(self, job, context, value, control):
        if not self._scene(job):
            return super()._complete_tick(job, context, value, control)
        self._finish(job, "SUCCEEDED", _origin=control)

    def _finish_tick(self, job, state, error, control):
        if not self._scene(job):
            return super()._finish_tick(job, state, error, control)
        self._finish(job, state, error, _origin=control)

    def _finish(self, job, state, error=None, *, _origin=None):
        if not self._scene(job):
            return super()._finish(job, state, error)
        if job.state in TERMINAL:
            return
        if _origin is None:
            with self.reservations.scheduler_scope(job.reservation) as origin:
                return self._finish(job, state, error, _origin=origin)
        self.reservations.check_retirement(job.reservation, _origin)
        # Latch once: retrying receipt/retirement failure never resumes work,
        # recaptures consent/context or records another operation history entry.
        if job.terminal_state is None:
            job.terminal_primary = error
            job.terminal_state = state
        if job.finished is None:
            job.finished = time.monotonic()
        if job.storage_effects is not None and job.storage_effects_snapshot is None:
            try:
                # Only preattached literal cells survive a stop. Do not resolve
                # stopped driver methods, context factories, providers or RNA.
                job.storage_effects_snapshot = _storage_snapshot(job, seal=True)
            except BaseException:
                job.state = "FINALIZING"
                raise
        if job.native_effects is not None and job.native_effects_snapshot is None:
            # Directly retained fixed cells only. No stopped-driver property,
            # context factory, provider or Blender read is consulted here.
            if type(job.native_effects) is not SceneNativeEffects or type(job.native_effects.status) is not EffectsStatus:
                raise refused("SCENE_NATIVE_EFFECTS_INVALID")
            job.native_effects.status.sealed = True
            job.native_effects_snapshot = snapshot_native_effects(job.native_effects)
        if not job.terminal_error_captured:
            primary = job.terminal_primary
            if primary is not None:
                try:
                    job.error = plain(primary.to_dict(), field="error", byte_limit=16384)
                except BridgeError:
                    job.error = {"code": primary.code[:64], "message": "Scene job failed; original error evidence was invalid.",
                                 "context": {"original_error_context_invalid": True}}
            job.terminal_error_captured = True
            job.terminal_primary = None
        if not job.terminal_abandoned:
            job.checkpoint = job.checkpoint_manager.abandon_pending(
                job.pending, job.reservation, job.terminal_state.lower(), origin=_origin)
            job.terminal_abandoned = True
        job.boundary_created = job.checkpoint["before_verified"]
        job.boundary_finalized = job.checkpoint["after_verified"]
        possible_mutation = job.execution_started or bool(job.checkpoint["marker_writes_completed"]
                                                        or job.checkpoint["native_snapshots_completed"])
        if job.error is not None:
            job.error.setdefault("context", {}).update(job_id=job.job_id, execution_started=job.execution_started,
                possible_mutation=possible_mutation, undo_boundary_created=job.boundary_created,
                undo_boundary_finalized=job.boundary_finalized, verification_required=True)
        if not job.terminal_history_attempted:
            job.terminal_history_attempted = True
            try:
                record = job.state_origin[0].record_operation(tool=TURN_METHOD,
                    description=f"Scene job {job.job_id} {job.terminal_state.lower()}: {job.label}; verify state",
                    success=job.terminal_state == "SUCCEEDED", duration_ms=(job.finished-job.started)*1000,
                    error_code=job.error["code"] if job.error else None,
                    **({"job_evidence": {"job_id": job.job_id, "state": job.terminal_state,
                        **({"native_effects": job.native_effects_snapshot} if job.native_effects_snapshot is not None else {}),
                        **({"storage_effects": job.storage_effects_snapshot} if job.storage_effects_snapshot is not None else {})}}
                       if job.native_effects_snapshot is not None or job.storage_effects_snapshot is not None else {}))
                job.operation_id = record.operation_id
            except Exception:
                job.terminal_state = "FAILED"
                if job.error is not None:
                    job.error["context"]["operation_history_unknown"] = True
                else:
                    job.error = BridgeError(ErrorCode.OPERATION_FAILED, "Scene-job operation history could not be recorded.",
                        {"operation_history_unknown": True, "possible_mutation": possible_mutation}).to_dict()
        state = job.terminal_state
        if state != "SUCCEEDED":
            job.result = None
            if not job.terminal_ledger_written:
                receipt = {"checkpoint": dict(job.checkpoint), "phase": job.phase,
                    "effects": dict(job.effects), "error": job.error, "execution_started": job.execution_started,
                    "summary": {**job.summary(), "state": state, "terminal": True, "revision": job.revision+1,
                                "progress": {**job.progress, "phase": state.lower()}}}
                self.recovery_ledger[job.job_id] = plain(receipt, field="recovery_receipt",
                    byte_limit=262144, item_limit=16384, depth_limit=16)
                job.terminal_ledger_written = True
        # Retire before releasing the fence. A failed append can be retried
        # without duplicate history and keeps the exact active record available.
        try:
            job.state, job.progress = state, {**job.progress, "phase": state.lower()}
            if not job.terminal_retired:
                if not any(item is job for item in self.history):
                    self._retire(job)
                job.terminal_retired = True
            if self.active is None:
                self.active = job
            if state == "SUCCEEDED" and not job.terminal_pending_released:
                job.checkpoint_manager.release_pending(job.pending, job.reservation, origin=_origin)
                job.terminal_pending_released = True
            self.reservations.release(job.reservation, origin=_origin)
        except BaseException:
            job.state = "FINALIZING"
            if self.active is None:
                self.active = job
            raise
        job.revision += 1
        job.work = None
        if job.lifetime.connection is not None:
            job.lifetime.connection.background_active.clear()
        if self.active is job:
            self.active = None
        self._scene_records.pop(id(job), None)
        job.driver = None  # Only detached, bounded cached evidence survives.
        job.storage_driver_proof = job.storage_reader_proof = job.storage_scope = None

    def inspect(self, job_id):
        try:
            return super().inspect(job_id)
        except BridgeError as error:
            if error.code != ErrorCode.INVALID_ARGUMENT.value or job_id not in self.recovery_ledger:
                raise
            return plain({**self.recovery_ledger[job_id]["summary"], "terminal_history_evicted": True,
                    "recovery_receipt_retained": True}, field="summary", byte_limit=262144,
                    item_limit=16384, depth_limit=16)

    def list(self, limit=10):
        if not self.recovery_ledger:
            return super().list(limit)
        self._main()
        records = ([self.active] if self.active else [])+list(self.history)
        ids = {job.job_id for job in records}
        summaries = [job.summary() for job in records]
        summaries.extend(self.inspect(identifier) for identifier in self.recovery_ledger if identifier not in ids)
        return {"jobs": summaries[:limit], "total": len(summaries), "truncated": len(summaries) > limit,
                "max_active": 1, "terminal_history_limit": 32, "durable": False,
                "unresolved_scene_receipts": len(self.recovery_ledger), "scene_recovery_limit": self.recovery_limit}

    def status(self):
        status = super().status()
        if self.recovery_ledger:
            status.update(unresolved_scene_receipts=len(self.recovery_ledger), scene_recovery_limit=self.recovery_limit)
        return status

    def cancel_all(self, reason):
        self.reservations.invalidate(reason)
        super().cancel_all(reason)
