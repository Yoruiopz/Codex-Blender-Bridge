"""Main-thread image jobs; one shared owner, cooperative work and guarded commits."""

from __future__ import annotations

import inspect
import json
import logging
import math
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from threading import Event
from types import CodeType, FunctionType, GeneratorType, GetSetDescriptorType, ModuleType
from typing import Any

from . import glb_stage_runtime as _prepared_context_module
from .errors import BridgeError, ErrorCode, invalid_argument
from .job_controller import TERMINAL, CooperativeJobController
from .permissions import Permission, PermissionManager
from .protocol import utc_timestamp
from .request_lifecycle import RequestLifetime
from .state import BridgeState, bounded_external_effects, bounded_recovery_evidence
from .tool_registry import ToolContext, ToolRegistry
from .tools import image_masks, image_paint, images, pixel_brush
from .utils import require_blender

LOGGER = logging.getLogger(__name__)
START_METHOD = "image.paint_job_start"


def _prepared_refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, "Prepared image job callback ownership changed; inspect retained effects.",
                       {"reason": reason, "verification_required": True})


def _function_facts(function):
    if type(function) is not FunctionType:
        raise _prepared_refused("PREPARED_CALLBACK_UNSUPPORTED")
    try:
        closure = tuple((cell, cell.cell_contents) for cell in function.__closure__ or ())
    except ValueError as cause:
        raise _prepared_refused("PREPARED_CALLBACK_UNSUPPORTED") from cause
    return (function, function.__code__, function.__globals__, function.__defaults__, function.__kwdefaults__, closure)


def _function_matches(function, facts):
    try:
        actual = _function_facts(function)
        return (all(a is b for a, b in zip(actual[:5], facts[:5], strict=True))
                and len(actual[5]) == len(facts[5])
                and all(a is b and x is y for (a, x), (b, y) in zip(actual[5], facts[5], strict=True)))
    except Exception:
        return False


def _prepared_plain(value, *, maximum=65536):
    """Copy bounded owned literals before reducers; never traverse custom objects."""
    count = 0

    def copy(item, depth):
        nonlocal count
        count += 1
        if count > 4096 or depth > 8:
            raise _prepared_refused("PREPARED_EVIDENCE_BUDGET")
        if item is None or type(item) in {bool, str}:
            return item
        if type(item) is int and item.bit_length() <= 64:
            return item
        if type(item) is float and math.isfinite(item):
            return item
        if type(item) in {tuple, list}:
            return [copy(child, depth + 1) for child in item]
        if type(item) is dict and all(type(key) is str for key in item):
            return {key: copy(child, depth + 1) for key, child in item.items()}
        raise _prepared_refused("PREPARED_EVIDENCE_NOT_PLAIN")

    result = copy(value, 0)
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) > maximum:
        raise _prepared_refused("PREPARED_EVIDENCE_BUDGET")
    return result


_PREPARED_RECORDER = inspect.getattr_static(BridgeState, "record_operation")
_PREPARED_RECORDER_FACTS = _function_facts(_PREPARED_RECORDER)
_PREPARED_CONTEXT_INIT = inspect.getattr_static(ToolContext, "__init__")
_PREPARED_CONTEXT_INIT_FACTS = _function_facts(_PREPARED_CONTEXT_INIT)
_PREPARED_CONTEXT_HELPER = _prepared_context_module.checked_executor_context
_PREPARED_CONTEXT_EXECUTOR = _prepared_context_module._Executor
_PREPARED_EXECUTOR_MODULE = sys.modules[_PREPARED_CONTEXT_EXECUTOR.__module__]
_PREPARED_CONTEXT_SERVICE = _prepared_context_module.GLBStageService
_PREPARED_MISSING = object()


def _prepared_global_facts(function):
    """Pin names before calling the helper, including newly shadowed builtins."""
    names, pending = set(), [function.__code__]
    while pending:
        code = pending.pop()
        names.update(code.co_names)
        pending.extend(value for value in code.co_consts if type(value) is CodeType)
    return function, _function_facts(function), tuple(
        (name, function.__globals__.get(name, _PREPARED_MISSING)) for name in sorted(names))


_PREPARED_CONTEXT_FUNCTIONS = tuple(_prepared_global_facts(function) for function in (
    _PREPARED_CONTEXT_HELPER,
    vars(_PREPARED_CONTEXT_SERVICE)["check_context_factory"],
    _prepared_context_module._check_protected_dependencies,
    _prepared_context_module.refused,
))
_PREPARED_CONTEXT_CLASSES = tuple((cls, cls.__mro__, tuple(vars(cls).items()), tuple(
    _function_facts(function)
    for value in vars(cls).values()
    for function in ([value] if type(value) is FunctionType else
                     [value.__func__] if type(value) in {staticmethod, classmethod} else
                     [item for item in (value.fget, value.fset, value.fdel) if item is not None] if type(value) is property else [])))
    for cls in (_PREPARED_CONTEXT_EXECUTOR, _PREPARED_CONTEXT_SERVICE, *_prepared_context_module._AUTHORITY_CLASSES))


def _prepared_same_mro(actual, expected):
    return len(actual) == len(expected) and all(left is right for left, right in zip(actual, expected, strict=True))


def _prepared_helper_proof(runtime_module, executor_module):
    """Pure source facts first; never resolve a Runtime or executor property."""
    if (type(runtime_module) is not ModuleType or type(executor_module) is not ModuleType
            or sys.modules.get(__package__+".runtime") is not runtime_module
            or executor_module is not _PREPARED_EXECUTOR_MODULE
            or sys.modules.get(__package__+".executor") is not _PREPARED_EXECUTOR_MODULE
            or sys.modules.get(__package__+".glb_stage_runtime") is not _prepared_context_module
            or type(_prepared_context_module) is not ModuleType
            or vars(runtime_module).get("checked_executor_context") is not _PREPARED_CONTEXT_HELPER
            or vars(_prepared_context_module).get("checked_executor_context") is not _PREPARED_CONTEXT_HELPER
            or vars(executor_module).get("MainThreadExecutor") is not _PREPARED_CONTEXT_EXECUTOR):
        raise _prepared_refused("PREPARED_CONTEXT_HELPER_CHANGED")
    for function, facts, dependencies in _PREPARED_CONTEXT_FUNCTIONS:
        if (not _function_matches(function, facts)
                or any(function.__globals__.get(name, _PREPARED_MISSING) is not value for name, value in dependencies)):
            raise _prepared_refused("PREPARED_CONTEXT_HELPER_CHANGED")
    for cls, mro, namespace, functions in _PREPARED_CONTEXT_CLASSES:
        current = vars(cls)
        if (not _prepared_same_mro(cls.__mro__, mro) or len(current) != len(namespace)
                or any(current.get(name, _PREPARED_MISSING) is not value for name, value in namespace)
                or any(not _function_matches(facts[0], facts) for facts in functions)):
            raise _prepared_refused("PREPARED_CONTEXT_HELPER_CHANGED")


def _prepared_instance_namespace(value, cls, mro, fields):
    """Reject inherited access hooks and field descriptors before data access."""
    if (type(cls) is not type or type(value) is not cls or not _prepared_same_mro(cls.__mro__, mro)
            or inspect.getattr_static(cls, "__getattribute__") is not object.__getattribute__
            or inspect.getattr_static(cls, "__setattr__") is not object.__setattr__
            or inspect.getattr_static(cls, "__getattr__", _PREPARED_MISSING) is not _PREPARED_MISSING
            or any(inspect.getattr_static(cls, name, _PREPARED_MISSING) is not _PREPARED_MISSING for name in fields)):
        raise _prepared_refused("PREPARED_CONTEXT_ACCESS_CHANGED")
    descriptor = inspect.getattr_static(cls, "__dict__")
    if type(descriptor) is not GetSetDescriptorType or not any(descriptor.__objclass__ is base for base in mro):
        raise _prepared_refused("PREPARED_CONTEXT_ACCESS_CHANGED")
    namespace = object.__getattribute__(value, "__dict__")
    if type(namespace) is not dict or any(type(name) is not str for name in namespace):
        raise _prepared_refused("PREPARED_CONTEXT_ACCESS_CHANGED")
    return namespace


def _prepared_runtime_parts(runtime_module, executor_module):
    _prepared_helper_proof(runtime_module, executor_module)
    runtime_type = vars(runtime_module).get("BridgeRuntime")
    if type(runtime_type) is not type or runtime_type is not vars(runtime_module).get("_CANONICAL_RUNTIME_CLASS"):
        raise _prepared_refused("PREPARED_RUNTIME_CHANGED")
    constructor = inspect.getattr_static(runtime_type, "__init__")
    if (type(constructor) is not FunctionType or constructor.__globals__ is not vars(runtime_module)
            or constructor.__code__ is not vars(runtime_module).get("_RUNTIME_CONSTRUCTOR_CODE")):
        raise _prepared_refused("PREPARED_RUNTIME_CHANGED")
    runtime = vars(runtime_module).get("_RUNTIME")
    owned = _prepared_instance_namespace(runtime, runtime_type, (runtime_type, object),
        ("jobs", "executor", "state", "permissions", "registry", "checkpoints", "glb_stage"))
    executor = owned.get("executor")
    execution = _prepared_instance_namespace(executor, _PREPARED_CONTEXT_EXECUTOR, _PREPARED_CONTEXT_EXECUTOR.__mro__,
        ("jobs", "state", "permissions", "registry", "checkpoints", "glb_stage", "evidence"))
    manager = owned.get("jobs")
    manager_type = vars(runtime_module).get("NativeSaveJobs")
    geometry = sys.modules.get(__package__+".geometry_preview_jobs")
    scene = sys.modules.get(__package__+".scene_jobs")
    if type(geometry) is not ModuleType or type(scene) is not ModuleType or type(manager_type) is not type:
        raise _prepared_refused("PREPARED_RUNTIME_CHANGED")
    manager_mro = (manager_type, vars(geometry).get("GeometryPreviewJobs"), vars(scene).get("SceneJobs"), PaintJobs, CooperativeJobController, object)
    if any(type(base) is not type for base in manager_mro):
        raise _prepared_refused("PREPARED_RUNTIME_CHANGED")
    _prepared_instance_namespace(manager, manager_type, manager_mro, ("context_factory", "history"))
    service = owned.get("glb_stage")
    service_data = _prepared_instance_namespace(service, _PREPARED_CONTEXT_SERVICE, _PREPARED_CONTEXT_SERVICE.__mro__,
        ("runtime", "state", "registry", "checkpoints", "jobs", "_executor_origin"))
    if (execution.get("glb_stage") is not service or service_data.get("runtime") is not runtime
            or service_data.get("_executor_origin") is not executor
            or "check_context_factory" in service_data):
        raise _prepared_refused("PREPARED_CONTEXT_SERVICES_CHANGED")
    return runtime, manager, executor


class PreparedJobCallbacks:
    """Internal concrete current-pixels callback origin, never wire authority.

    Capture occurs in the domain's retained pre-provider admission. The source
    origin checks its finite dependencies without reading Blender or files.
    CPython/stdlib primitives and qualified owned-object lifetimes are trusted.
    """

    __slots__ = (
        "background_event",
        "cleanup_verified",
        "context",
        "context_getter",
        "control_map",
        "domain_module",
        "driver",
        "driver_type",
        "effects",
        "executor",
        "executor_type",
        "factory",
        "factory_facts",
        "getter_facts",
        "history",
        "history_attempted",
        "history_dependencies",
        "history_lock",
        "job",
        "job_deadline",
        "job_method",
        "lifetime",
        "manager",
        "methods",
        "origin",
        "owner_history",
        "prepare",
        "prepare_facts",
        "prepared",
        "provider",
        "provider_dependencies",
        "provider_facts",
        "recorder",
        "recorder_facts",
        "recovery",
        "required_permissions",
        "retired",
        "runtime",
        "runtime_facts",
        "runtime_module",
        "runtime_type",
        "service_methods",
        "services",
        "source_check",
        "source_facts",
        "source_module",
        "source_type",
        "state",
        "terminalizing",
        "token",
        "work",
    )

    @classmethod
    def capture(cls, context, *, origin):
        if cls is not PreparedJobCallbacks or type(context) is not ToolContext:
            raise _prepared_refused("PREPARED_ADMISSION_REQUIRED")
        source = sys.modules.get(__package__ + ".current_pixels_source")
        domain = sys.modules.get(__package__ + ".tools.image_current_pixels")
        runtime_module = sys.modules.get(__package__ + ".runtime")
        executor_module = sys.modules.get(__package__ + ".executor")
        if any(type(module) is not ModuleType for module in (source, domain, runtime_module, executor_module)):
            raise _prepared_refused("PREPARED_DOMAIN_UNAVAILABLE")
        source_type = vars(source).get("CurrentPixelsOrigin")
        driver_type = vars(domain).get("CurrentPixelsDriver")
        prepare = vars(domain).get("prepare_current_pixels")
        if type(source_type) is not type or type(origin) is not source_type or type(driver_type) is not type:
            raise _prepared_refused("PREPARED_CONCRETE_DOMAIN_REQUIRED")
        check = vars(source_type).get("check_job_callbacks")
        if (type(check) is not FunctionType or check.__globals__ is not vars(source)
                or type(prepare) is not FunctionType or prepare.__globals__ is not vars(domain)
                or driver_type.__module__ != domain.__name__):
            raise _prepared_refused("PREPARED_DOMAIN_CALLBACK_ORIGIN_REQUIRED")
        runtime, manager, executor = _prepared_runtime_parts(runtime_module, executor_module)
        if (type(runtime) is not runtime_module.BridgeRuntime or manager is not context.jobs
                or type(runtime.jobs) is not runtime_module.NativeSaveJobs
                or type(runtime.executor) is not executor_module.MainThreadExecutor
                or type(context.state) is not BridgeState or type(context.permissions) is not PermissionManager
                or type(context.registry) is not ToolRegistry
                or type(context.checkpoints) is not runtime_module.CheckpointManager
                or type(context.evidence) is not executor_module.SceneEvidenceStore
                or inspect.getattr_static(BridgeState, "record_operation") is not _PREPARED_RECORDER
                or not _function_matches(_PREPARED_RECORDER, _PREPARED_RECORDER_FACTS)):
            raise _prepared_refused("PREPARED_RUNTIME_CHANGED")
        self = cls()
        self.manager, self.context, self.origin = context.jobs, context, origin
        self.source_module, self.domain_module, self.source_type = source, domain, source_type
        self.source_check, self.source_facts = check, _function_facts(check)
        self.prepare, self.prepare_facts, self.driver_type = prepare, _function_facts(prepare), driver_type
        self.methods = {name: (vars(driver_type).get(name), _function_facts(vars(driver_type).get(name)))
                        for name in ("__init__", "steps", "cleanup", "evidence", "recovery_evidence")}
        if not self.methods["steps"][0].__code__.co_flags & inspect.CO_GENERATOR:
            raise _prepared_refused("PREPARED_GENERATOR_REQUIRED")
        self.runtime, self.executor = runtime, executor
        self.runtime_module, self.runtime_type = runtime_module, runtime_module.BridgeRuntime
        self.runtime_facts = _function_facts(inspect.getattr_static(self.runtime_type, "__init__"))
        self.executor_type = executor_module.MainThreadExecutor
        self.factory = self.manager.context_factory
        self.factory_facts = _function_facts(self.factory)
        codes = [item for item in self.runtime_facts[1].co_consts
                 if type(item) is CodeType and item.co_freevars == ("self",) and item.co_names == ("checked_executor_context", "executor")]
        if (len(codes) != 1 or self.factory.__code__ is not codes[0]
                or self.factory.__globals__ is not vars(runtime_module)
                or self.factory.__defaults__ is not None or self.factory.__kwdefaults__ is not None
                or len(self.factory.__closure__ or ()) != 1 or self.factory.__closure__[0].cell_contents is not runtime):
            raise _prepared_refused("PREPARED_FACTORY_ORIGIN_REQUIRED")
        context_property = inspect.getattr_static(self.executor_type, "context")
        if type(context_property) is not property:
            raise _prepared_refused("PREPARED_CONTEXT_GETTER_CHANGED")
        self.context_getter = context_property.fget
        self.getter_facts = _function_facts(self.context_getter)
        self.services = tuple((name, getattr(context, name)) for name in ("state", "permissions", "registry", "checkpoints", "jobs", "evidence"))
        self.service_methods = tuple((owner, name, inspect.getattr_static(owner, name),
                                     _function_facts(inspect.getattr_static(owner, name)))
            for owner, name in ((context, "require"), (context.permissions, "require"),
                                (context.registry, "get"), (context.registry, "prepare"),
                                (context.state, "snapshot"), (context.checkpoints, "before_modification"),
                                (context.checkpoints, "after_modification")))
        self.provider = context.permissions._source
        self.provider_facts = _function_facts(self.provider)
        provider_codes = [item for item in self.runtime_facts[1].co_consts
                          if type(item) is CodeType and item.co_names == ("permission_snapshot", "_preferences")]
        if (len(provider_codes) != 1 or self.provider.__code__ is not provider_codes[0]
                or self.provider.__globals__ is not vars(runtime_module) or self.provider.__closure__ is not None):
            raise _prepared_refused("PREPARED_PERMISSION_PROVIDER_ORIGIN_REQUIRED")
        self.provider_dependencies = tuple((name, vars(runtime_module).get(name), _function_facts(vars(runtime_module).get(name)))
                                           for name in ("_preferences", "permission_snapshot", "_base_permission_snapshot"))
        self.state, self.recorder = context.state, inspect.getattr_static(BridgeState, "record_operation")
        self.recorder_facts = _function_facts(self.recorder)
        self.history, self.history_lock = self.state._history, self.state._lock
        self.history_dependencies = tuple((name, self.recorder.__globals__[name],
            _function_facts(self.recorder.__globals__[name]) if type(self.recorder.__globals__[name]) is FunctionType else None)
            for name in ("OperationRecord", "bounded_recovery_evidence", "bounded_external_effects", "bounded_entry_effects", "_now"))
        self.job = self.token = self.driver = self.prepared = self.work = self.control_map = None
        self.job_deadline = self.job_method = self.required_permissions = None
        self.lifetime = self.background_event = None
        self.effects, self.recovery = {}, {}
        self.owner_history = self.manager.history
        if type(self.owner_history) is not deque or self.owner_history.maxlen != 32:
            raise _prepared_refused("PREPARED_HISTORY_STORAGE_CHANGED")
        self.terminalizing = self.retired = self.cleanup_verified = self.history_attempted = False
        self.verify(context=context)
        return self

    def verify(self, *, context=None, job=None, callbacks=True, work=True):
        executor_module = sys.modules.get(__package__+".executor")
        if type(executor_module) is not ModuleType:
            raise _prepared_refused("PREPARED_RUNTIME_CHANGED")
        _prepared_runtime_parts(self.runtime_module, executor_module)
        context_property = inspect.getattr_static(self.executor_type, "context")
        if (type(self) is not PreparedJobCallbacks or self.runtime.jobs is not self.manager
                or vars(self.runtime_module).get("_RUNTIME") is not self.runtime
                or vars(self.runtime_module).get("BridgeRuntime") is not self.runtime_type
                or type(self.runtime) is not self.runtime_type
                or not _function_matches(inspect.getattr_static(self.runtime_type, "__init__"), self.runtime_facts)
                or type(self.executor) is not self.executor_type
                or self.runtime.executor is not self.executor or self.manager.context_factory is not self.factory
                or not _function_matches(self.factory, self.factory_facts)
                or type(context_property) is not property or context_property.fget is not self.context_getter
                or not _function_matches(self.context_getter, self.getter_facts)
                or self.context_getter.__globals__.get("ToolContext") is not ToolContext
                or inspect.getattr_static(ToolContext, "__init__") is not _PREPARED_CONTEXT_INIT
                or not _function_matches(_PREPARED_CONTEXT_INIT, _PREPARED_CONTEXT_INIT_FACTS)
                or vars(self.source_module).get("CurrentPixelsOrigin") is not self.source_type
                or sys.modules.get(__package__ + ".current_pixels_source") is not self.source_module
                or sys.modules.get(__package__ + ".tools.image_current_pixels") is not self.domain_module
                or type(self.origin) is not self.source_type
                or vars(self.source_type).get("check_job_callbacks") is not self.source_check
                or inspect.getattr_static(self.origin, "check_job_callbacks") is not self.source_check
                or not _function_matches(self.source_check, self.source_facts)
                or vars(self.domain_module).get("prepare_current_pixels") is not self.prepare
                or not _function_matches(self.prepare, self.prepare_facts)
                or vars(self.domain_module).get("CurrentPixelsDriver") is not self.driver_type):
            raise _prepared_refused("PREPARED_CALLBACK_ORIGIN_CHANGED")
        for name, service in self.services:
            if (getattr(self.executor, name, None) is not service
                    or (name != "evidence" and getattr(self.runtime, name, None) is not service)
                    or (context is not None and getattr(context, name, None) is not service)):
                raise _prepared_refused("PREPARED_CONTEXT_SERVICES_CHANGED")
        if context is not None and type(context) is not ToolContext:
            raise _prepared_refused("PREPARED_CONTEXT_TYPE_CHANGED")
        for owner, name, function, facts in self.service_methods:
            if inspect.getattr_static(owner, name) is not function or not _function_matches(function, facts):
                raise _prepared_refused("PREPARED_SERVICE_CALLBACK_CHANGED")
        if context is not None and inspect.getattr_static(context, "require") is not self.service_methods[0][2]:
            raise _prepared_refused("PREPARED_CONTEXT_REQUIRE_CHANGED")
        if (self.runtime.permissions._source is not self.provider or not _function_matches(self.provider, self.provider_facts)
                or any(vars(self.runtime_module).get(name) is not function or not _function_matches(function, facts)
                       for name, function, facts in self.provider_dependencies)):
            raise _prepared_refused("PREPARED_PERMISSION_PROVIDER_CHANGED")
        if callbacks:
            for name, (function, facts) in self.methods.items():
                if vars(self.driver_type).get(name) is not function or not _function_matches(function, facts):
                    raise _prepared_refused("PREPARED_DRIVER_CALLBACK_CHANGED")
                if self.driver is not None and inspect.getattr_static(self.driver, name) is not function:
                    raise _prepared_refused("PREPARED_DRIVER_CALLBACK_CHANGED")
        if job is not None:
            item = dict.get(self.control_map, id(job)) if type(self.control_map) is dict else None
            active = self.manager._prepared_active
            if (self.job is not job or job._callback_token is not self.token or type(self.control_map) is not dict
                    or self.manager._prepared_controls is not self.control_map
                    or type(item) is not tuple or len(item) != 3
                    or any(actual is not expected for actual, expected in zip(item, (job, self, self.token), strict=True))
                    or type(active) is not tuple or len(active) != 3
                    or any(actual is not expected for actual, expected in zip(active, (job, self, self.token), strict=True))
                    or job.driver is not self.driver or type(self.driver) is not self.driver_type
                    or job.prepared is not self.prepared or type(job.prepared) is not dict
                    or job.lifetime is not self.lifetime or self.manager.history is not self.owner_history
                    or job.deadline is not self.job_deadline or type(job.method) is not str or job.method != self.job_method
                    or type(job.required_permissions) is not tuple or job.required_permissions != self.required_permissions
                    or job.requires_external_files is not True):
                raise _prepared_refused("PREPARED_CONTROL_CHANGED")
            if (_prepared_plain(job.external_effects) != self.effects
                    or _prepared_plain(job.recovery_evidence, maximum=8192) != self.recovery):
                raise _prepared_refused("PREPARED_CACHED_EVIDENCE_CHANGED")
            if work and (job.work is not self.work or (self.work is not None
                    and (type(self.work) is not GeneratorType or self.work.gi_code is not self.methods["steps"][0].__code__))):
                raise _prepared_refused("PREPARED_WORK_CHANGED")
        if self.source_check(self.origin) is not None:
            raise _prepared_refused("PREPARED_PURE_CHECK_INVALID")

    def history_valid(self):
        # Terminal observers may damage the binding. Recheck only owned plain
        # identities here; full verify would call the domain origin too late.
        if self.job is None or type(self.control_map) is not dict or self.manager._prepared_controls is not self.control_map:
            return False
        item = dict.get(self.control_map, id(self.job))
        active = self.manager._prepared_active
        expected = self.job, self, self.token
        if (type(item) is not tuple or len(item) != 3
                or any(actual is not original for actual, original in zip(item, expected, strict=True))
                or type(active) is not tuple or len(active) != 3
                or any(actual is not original for actual, original in zip(active, expected, strict=True))
                or self.job._callback_token is not self.token):
            return False
        if (type(self.state) is not BridgeState or inspect.getattr_static(BridgeState, "record_operation", None) is not self.recorder
                or not _function_matches(self.recorder, self.recorder_facts)
                or inspect.getattr_static(self.state, "record_operation", None) is not self.recorder
                or vars(self.state).get("_history") is not self.history or type(self.history) is not deque
                or vars(self.state).get("_lock") is not self.history_lock):
            return False
        return all(self.recorder.__globals__.get(name) is value and (facts is None or _function_matches(value, facts))
                   for name, value, facts in self.history_dependencies)


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


@dataclass(slots=True)
class GuardedPreparedPaintJob(PaintJob):
    """Exact routing identity survives damaged driver/prepared/control fields."""

    _callback_token: object = None
    _cached_external_effects: dict = field(default_factory=dict)
    _cached_recovery_evidence: dict = field(default_factory=dict)

    def observe_evidence(self) -> list[str]:
        # Polling is deliberately cached-only, including after source drift.
        value = self.evidence_observation_unknown
        return list(value) if type(value) is list and len(value) <= 8 and all(type(name) is str for name in value) else ["cached_observation_invalid"]

    def summary(self) -> dict:
        def cached(value, fallback):
            try:
                return _prepared_plain(value)
            except Exception:
                return fallback

        return {"job_id": self.job_id, "kind": self.kind, "request_id": self.request_id,
                "source_image": self.source_name, "new_image": self.new_name, "state": self.state,
                "terminal": self.state in TERMINAL, "revision": self.revision,
                "progress": cached(self.progress, {"phase": "unknown"}), "created_at": self.created_at,
                "result": cached(self.result, None), "error": cached(self.error, None),
                "execution_started": self.execution_started, "undo_boundary_created": self.boundary_created,
                "undo_boundary_finalized": self.boundary_finalized, "operation_id": self.operation_id,
                "verification_required": True, "durable": False, "workload": cached(self.workload, {}),
                "external_effects": cached(self._cached_external_effects, {}),
                "recovery_evidence": cached(self._cached_recovery_evidence, {}),
                "evidence_observation_unknown": self.observe_evidence(),
                "duration_ms": round(((self.finished or time.monotonic()) - self.started) * 1000, 3)}


class PaintJobs(CooperativeJobController):
    """Image preparation/publication adapter using the shared job controller.

    The existing runtime-facing identity, image summaries and terminal cleanup
    policy stay here. Network threads touch only the existing lifetime Events.
    """

    _logger = LOGGER
    _emergency_message = "Painting job emergency-stopped."
    _unexpected_failure_log = "Image job failed outside its typed error path"
    _unexpected_failure_message = "Image job failed; inspect its recovery/file evidence."
    _lifecycle_cancel_message = "Image job cancelled by bridge lifecycle."

    def __init__(self, context_factory, budget_ms=lambda: 4.):
        super().__init__(context_factory, budget_ms)
        self._prepared_controls = {}
        self._prepared_active = None
        self._prepared_unresolved = None

    def _prepared_control(self, job):
        mapping = self._prepared_controls
        value = dict.get(mapping, id(job)) if type(mapping) is dict else None
        if (type(value) is not tuple or len(value) != 3 or value[0] is not job
                or type(value[1]) is not PreparedJobCallbacks or value[2] is not job._callback_token):
            raise _prepared_refused("PREPARED_CONTROL_LOST")
        control = value[1]
        control.verify(job=job)
        return control

    def _guard_context_creation(self, job):
        # This hook runs outside the controller's try. Never validate here.
        return type(job) is GuardedPreparedPaintJob

    def _prepare_step(self, job, context):
        if type(job) is GuardedPreparedPaintJob:
            control = self._prepared_control(job)
            control.verify(context=context, job=job)
            context.registry.prepare(job.method, context)
            control.verify(context=context, job=job)
            return
        return super()._prepare_step(job, context)

    def _budget_for(self, job):
        return 4. if type(job) is GuardedPreparedPaintJob else super()._budget_for(job)

    def _work_step_limit(self, job):
        return 1 if type(job) is GuardedPreparedPaintJob else super()._work_step_limit(job)

    def _advance_work(self, job, context, control):
        if type(job) is not GuardedPreparedPaintJob:
            return super()._advance_work(job, context, control)
        owned = self._prepared_control(job)
        owned.verify(context=context, job=job)
        try:
            value = next(owned.work)
        except StopIteration:
            owned.verify(context=context, job=job)
            raise
        owned.verify(context=context, job=job)
        self._observe_prepared(job, owned, current=False)
        self._check(job, context)
        self._observe_prepared(job, owned, current=True)
        return _prepared_plain(value)

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
        control = self._prepared_control(job) if type(job) is GuardedPreparedPaintJob else None
        if control is not None:
            control.verify(context=context, job=job)
        self._lifetime_check(job, context)
        required = list(job.required_permissions)
        if job.requires_external_files and Permission.ACCESS_EXTERNAL_FILES not in required:
            required.append(Permission.ACCESS_EXTERNAL_FILES)
        context.require(*required)
        if control is not None:
            control.verify(context=context, job=job)
        if job.in_commit:
            # A pause during an already-started native call cannot hold half a
            # publication. Stop at the next safe point and retain recovery evidence.
            context.registry.prepare(job.method, context)
            if control is not None:
                control.verify(context=context, job=job)
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
        if type(job) is GuardedPreparedPaintJob:
            self._prepared_control(job).verify(context=context, job=job)
        self.active = job
        if job.lifetime.connection is not None:
            job.lifetime.connection.background_active.set()
        try:
            images._check(context)
            if type(job) is GuardedPreparedPaintJob:
                self._prepared_control(job).verify(context=context, job=job)
        except Exception:
            self.cancel_all("start request cancelled")
            raise

    def start_prepared_driver(self, context: Any, params: dict, time_limit: float, *, prepare, required_permissions, callback_control=None) -> dict:
        """Trusted domain preparation; preserve the one shared owner/lifecycle.

        Preparation may perform a bounded non-preemptible native input capture.
        Driver CPU work waits for start-response delivery and shares normal tick,
        consent, cancel, pause, undo, terminal history and buffer-release paths.
        """
        self._main()
        if self.active is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "One image job is already active; inspect/cancel it before starting another.",
                              {"active_job_id": self.active.job_id})
        if callback_control is not None:
            return self._start_guarded_prepared(context, params, time_limit, prepare, required_permissions, callback_control)
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

    def _start_guarded_prepared(self, context, params, time_limit, prepare, required_permissions, control):
        if self._prepared_unresolved is not None or self._prepared_active is not None:
            raise _prepared_refused("PREPARED_CLEANUP_UNRESOLVED")
        if (type(control) is not PreparedJobCallbacks or control.manager is not self
                or control.context is not context or control.job is not None or prepare is not control.prepare):
            raise _prepared_refused("PREPARED_ADMISSION_REQUIRED")
        if tuple(required_permissions) != (Permission.INSPECT_SCENE, Permission.EDIT_MATERIALS,
                                           Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT):
            raise _prepared_refused("PREPARED_PERMISSION_CONTRACT_CHANGED")
        time_limit = pixel_brush.number(time_limit, "time_limit_seconds", 1., 300.)
        control.verify(context=context)
        started = time.monotonic()
        prepared = control.prepare(context, params)
        control.verify(context=context)
        if type(prepared) is not dict or prepared.get("driver_type") is not control.driver_type:
            raise _prepared_refused("PREPARED_DRIVER_TYPE_CHANGED")
        control.prepared = prepared
        # The constructor is captured and checked before any instance call.
        if vars(control.driver_type).get("__new__", object.__new__) is not object.__new__:
            raise _prepared_refused("PREPARED_DRIVER_ALLOCATOR_CHANGED")
        driver = object.__new__(control.driver_type)
        if type(driver) is not control.driver_type:
            raise _prepared_refused("PREPARED_DRIVER_TYPE_CHANGED")
        control.driver = driver
        control.methods["__init__"][0](driver, prepared)
        control.verify(context=context)
        token = object()
        job = GuardedPreparedPaintJob("job_" + uuid.uuid4().hex, context.request_id,
            prepared["source_name"], prepared["name"], context.request_lifecycle or RequestLifetime.local(),
            started + time_limit, prepared, _identity(prepared["source"]), _metadata(prepared["source"]),
            prepared["requires_external_files"], started=started, method=prepared["method"], kind=prepared["kind"],
            required_permissions=tuple(required_permissions), driver=driver, _callback_token=token)
        job.workload = _prepared_plain(prepared["workload"])
        control.job, control.token, control.control_map = job, token, self._prepared_controls
        control.job_deadline, control.job_method, control.required_permissions = job.deadline, job.method, job.required_permissions
        control.lifetime = job.lifetime
        control.background_event = job.lifetime.connection.background_active if job.lifetime.connection is not None else None
        if control.background_event is not None and type(control.background_event) is not Event:
            raise _prepared_refused("PREPARED_LIFETIME_CHANGED")
        self._prepared_controls[id(job)] = (job, control, token)
        self._prepared_active = job, control, token
        try:
            control.verify(context=context, job=job)
            self._accept(job, context)
            control.verify(context=context, job=job)
        except Exception as failure:
            if not control.retired:
                self._finish(job, "FAILED", failure if isinstance(failure, BridgeError) else _prepared_refused("PREPARED_ACCEPT_FAILED"))
            raise
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
        from .tools.image_surface_paint import (
            REQUIRED,
            SurfacePaintDriver,
            prepare_surface,
            workload,
        )

        started = time.monotonic()
        prepared = prepare_surface(context, params, allow_large=True)
        mask = prepared["mask"]
        job = PaintJob("job_" + uuid.uuid4().hex, getattr(context, "request_id", ""), prepared["source_name"], prepared["name"],
                       getattr(context, "request_lifecycle", None) or RequestLifetime.local(), started+time_limit,
                       prepared, _identity(prepared["source"]), _metadata(prepared["source"]),
                       prepared["source"].source == "FILE" or bool(mask and mask["requires_external_files"]), started=started,
                       method="image.paint_surface_job_start", kind="image.paint_surface_version", required_permissions=REQUIRED,
                       driver=SurfacePaintDriver(prepared))
        job.workload = {**workload(prepared), "frozen_geometry_objects": len(prepared["records"]),
                        "frozen_triangles": len(prepared["triangles"]), "projection_work_started": False}
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
        control = self._prepared_control(job) if type(job) is GuardedPreparedPaintJob else None
        guarded_callbacks = {}
        if control is not None:
            guarded_callbacks = {"before_write": lambda: self._check(job, context),
                                 "after_read": lambda: control.verify(context=context, job=job)}
        try:
            if control is not None:
                control.verify(context=context, job=job)
            job.boundary_created = bool(context.checkpoints.before_modification(label, **guarded_callbacks))
            try:
                if control is not None:
                    control.verify(context=context, job=job)
                if not job.boundary_created:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "A recoverable native undo boundary is required before image publication.")
                self._check(job, context)
                context.registry.prepare(job.method, context)
                if control is not None:
                    control.verify(context=context, job=job)
                result = callback()
                self._check(job, context)
            finally:
                if job.boundary_created:
                    if control is not None:
                        control.verify(context=context, job=job)
                    job.boundary_finalized = bool(context.checkpoints.after_modification(label, **guarded_callbacks))
                    if control is not None:
                        control.verify(context=context, job=job)
            if not job.boundary_finalized:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Image job native undo finalization failed; inspect retained effects.", {"possible_mutation": job.execution_started})
            return result
        finally:
            job.in_commit = False

    def _context(self, job: PaintJob):
        if type(job) is GuardedPreparedPaintJob:
            control = self._prepared_control(job)
            control.verify(job=job)
            context = control.factory()
            control.verify(context=context, job=job)
            context.check_cancelled = lambda: self._check(job, context)
            context.request_lifecycle = job.lifetime
            context.check_final_request = None
            context.check_final_job = lambda: self._lifetime_check(job, context)
            return context
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
        if type(job) is GuardedPreparedPaintJob:
            return self._finish_prepared(job, state, error)
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
            self._retire(job)

    def _observe_prepared(self, job, control, *, current):
        field = "recovery_evidence" if current else "external_effects"
        job.evidence_observation_unknown = job.observe_evidence()
        try:
            control.verify(job=job)
            value = control.methods["recovery_evidence" if current else "evidence"][0](control.driver)
            control.verify(job=job)
            value = _prepared_plain(value, maximum=8192 if current else 65536)
            if type(value) is not dict:
                raise _prepared_refused("PREPARED_OBSERVATION_INVALID")
            reduced = bounded_recovery_evidence(value) if current else bounded_external_effects(value)
            if reduced is None or (current and reduced != value):
                raise _prepared_refused("PREPARED_OBSERVATION_INVALID")
            previous = getattr(job, field)
            for name in ("publication_attempted", "file_published", "publication_outcome_unknown",
                         "external_write_attempted", "helper_record_write_attempted", "image_write_attempted"):
                if previous.get(name) is True and reduced.get(name) is not True:
                    raise _prepared_refused("PREPARED_ATTEMPT_FACT_LOST")
            setattr(job, field, reduced)
            if current:
                control.recovery = _prepared_plain(reduced, maximum=8192)
                job._cached_recovery_evidence = _prepared_plain(reduced, maximum=8192)
            else:
                control.effects = _prepared_plain(reduced)
                job._cached_external_effects = _prepared_plain(reduced)
            job.evidence_observation_unknown = [name for name in job.evidence_observation_unknown if name != field]
        except Exception:
            if field not in job.evidence_observation_unknown:
                job.evidence_observation_unknown.append(field)
            raise

    def _finish_prepared(self, job, state, error):
        """Finite release-only tail; never construct a context after observation."""
        if job.state in TERMINAL:
            return
        item = self._prepared_active
        if (type(item) is not tuple or len(item) != 3 or item[0] is not job) and type(self._prepared_controls) is dict:
            item = dict.get(self._prepared_controls, id(job))
        control = item[1] if (type(item) is tuple and len(item) == 3 and item[0] is job
                             and type(item[1]) is PreparedJobCallbacks) else None
        if control is not None and control.terminalizing:
            return
        if control is not None:
            control.terminalizing = True
        job.evidence_observation_unknown = job.observe_evidence()
        unknown = {}

        def failed(reason, failure=None):
            nonlocal state, error
            if error is None:
                error = failure if isinstance(failure, BridgeError) else _prepared_refused(reason)
            elif isinstance(failure, BridgeError) and failure is not error:
                error.context.setdefault("prepared_secondary_failure", failure.code)
            state = "CANCELLED" if error.code in {ErrorCode.TIMEOUT.value, ErrorCode.EMERGENCY_STOPPED.value} else "FAILED"

        qualified = False
        try:
            qualified = self._prepared_control(job) is control
        except Exception as failure:
            failed("PREPARED_CONTROL_UNKNOWN", failure)
            unknown.update(cleanup_outcome_unknown=True, operation_history_unknown=True)
            # A damaged public field cannot erase the last controller observation
            # or invoke a replacement container during failure construction.
            job.external_effects = _prepared_plain(control.effects) if control is not None else _prepared_plain(job._cached_external_effects)
            job.recovery_evidence = _prepared_plain(control.recovery, maximum=8192) if control is not None else _prepared_plain(job._cached_recovery_evidence, maximum=8192)
        if qualified:
            try:
                if control.work is not None:
                    GeneratorType.close(control.work)
                    control.work = job.work = None
                    control.verify(job=job)
                cleanup = control.methods["cleanup"][0](control.driver, None, job, success=state == "SUCCEEDED")
                control.verify(job=job)
                if type(cleanup) is not dict:
                    raise _prepared_refused("PREPARED_CLEANUP_RECEIPT_INVALID")
                _prepared_plain(cleanup)
                control.cleanup_verified = True
            except Exception as failure:
                failed("PREPARED_RELEASE_FAILED", failure)
                unknown["cleanup_outcome_unknown"] = True
            if state == "SUCCEEDED":
                try:
                    context = self._context(job)
                    self._check(job, context)
                    self._prepare_step(job, context)
                except Exception as failure:
                    failed("PREPARED_FINAL_AUTHORITY_FAILED", failure)
            try:
                self._observe_prepared(job, control, current=False)
                if state == "SUCCEEDED":
                    self._observe_prepared(job, control, current=True)
                elif "recovery_evidence" not in job.evidence_observation_unknown:
                    job.evidence_observation_unknown.append("recovery_evidence")
            except Exception as failure:
                failed("PREPARED_FINAL_OBSERVATION_FAILED", failure)
                if "recovery_evidence" not in job.evidence_observation_unknown:
                    job.evidence_observation_unknown.append("recovery_evidence")
        else:
            for field in ("external_effects", "recovery_evidence"):
                if field not in job.evidence_observation_unknown:
                    job.evidence_observation_unknown.append(field)

        # No context, domain/driver, permission/provider or native calls below.
        if job.evidence_observation_unknown:
            failed("PREPARED_EVIDENCE_UNKNOWN")
            unknown["evidence_observation_unknown"] = list(job.evidence_observation_unknown)
            if "state_known" in job.recovery_evidence:
                job.recovery_evidence = {**job.recovery_evidence, "state_known": False}
                if job.recovery_evidence.get("kind") == "current_pixels_lifecycle":
                    job.recovery_evidence.update(stage="UNKNOWN", observed_prefix=None, observed_prefix_sha256=None)
        job._cached_external_effects = _prepared_plain(job.external_effects)
        job._cached_recovery_evidence = _prepared_plain(job.recovery_evidence, maximum=8192)
        job.driver, job.work, job.prepared = None, None, {}
        job.finished, job.state = time.monotonic(), state
        job.revision += 1
        job.progress = {"phase": state.lower(), "completed": 1 if state == "SUCCEEDED" else 0, "total": 1}
        try:
            if control is not None and control.background_event is not None:
                Event.clear(control.background_event)
        except Exception:
            unknown["lifetime_cleanup_unknown"] = True
            failed("PREPARED_LIFETIME_CLEANUP_FAILED")
        if control is not None and qualified and control.history_valid():
            try:
                control.history_attempted = True
                record = control.recorder(control.state, tool=job.method,
                    description=f"Image job {job.job_id} {state.lower()}: {job.new_name}; verify state",
                    success=state == "SUCCEEDED", duration_ms=(job.finished - job.started) * 1000,
                    error_code=error.code if error else None, recovery_evidence=job.recovery_evidence or None,
                    job_evidence={"job_id": job.job_id, "state": state, "external_effects": dict(job.external_effects),
                                  "execution_started": job.execution_started, "undo_boundary_finalized": job.boundary_finalized,
                                  "evidence_observation_unknown": list(job.evidence_observation_unknown)})
                job.operation_id = record.operation_id
            except Exception:
                unknown["operation_history_unknown"] = True
                failed("PREPARED_HISTORY_FAILED")
        else:
            unknown["operation_history_unknown"] = True
            failed("PREPARED_HISTORY_ORIGIN_CHANGED")
        if state != "SUCCEEDED":
            job.result = None
        elif job.result is not None:
            job.result = {**job.result, "external_effects": dict(job.external_effects),
                          "recovery_evidence": dict(job.recovery_evidence)}
        if error is not None:
            error.context.update({"job_id": job.job_id, "verification_required": True,
                "execution_started": job.execution_started, "possible_mutation": bool(job.execution_started
                    or error.context.get("possible_mutation") is True or job.external_effects.get("file_published")
                    or job.external_effects.get("publication_outcome_unknown") or job.external_effects.get("retained_staging_path")),
                "undo_boundary_created": job.boundary_created, "undo_boundary_finalized": job.boundary_finalized,
                "external_effects": dict(job.external_effects), "recovery_evidence": dict(job.recovery_evidence), **unknown})
            job.error = error.to_dict()
        job.state = state
        job.progress["phase"] = state.lower()
        if control is not None:
            control.retired = True
            if not control.cleanup_verified:
                self._prepared_unresolved = control
            else:
                control.driver = control.prepared = control.work = None
        else:
            self._prepared_unresolved = True
        if type(self._prepared_controls) is dict:
            self._prepared_controls.pop(id(job), None)
        self._prepared_active = None
        if control is not None:
            # Retain the original owned deque, never call a replacement container.
            self.history = control.owner_history
        if type(self.history) is deque:
            deque.appendleft(self.history, job)
        if self.active is job:
            self.active = None

    def _make_work(self, job: PaintJob, context: Any):
        if type(job) is GuardedPreparedPaintJob:
            control = self._prepared_control(job)
            control.verify(context=context, job=job)
            work = control.methods["steps"][0](control.driver, context, job,
                                              lambda callback: self._native_commit(job, context, callback))
            if type(work) is not GeneratorType or work.gi_code is not control.methods["steps"][0].__code__:
                raise _prepared_refused("PREPARED_WORK_ORIGIN_CHANGED")
            control.work = work
            control.verify(context=context, job=job, work=False)
            return work
        prepared = job.prepared
        return job.driver.steps(context, job, lambda callback: self._native_commit(job, context, callback)) if job.driver is not None else pixel_brush.paint_steps(prepared.pop("values"), prepared["width"], prepared["height"], prepared["strokes"],
            prepared["role"], srgb=prepared["srgb"], mask=prepared["mask"]["kernel"] if prepared["mask"] else None,
            associated=prepared["associated"],
            check=lambda: self._check(job, context))

    def _complete_work(self, job: PaintJob, context: Any, value: Any):
        if type(job) is GuardedPreparedPaintJob:
            self._prepared_control(job).verify(context=context, job=job)
            job.result = _prepared_plain(value)
            return self._finish(job, "SUCCEEDED")
        if job.driver is None:
            self._commit(job, context, value)
        else:
            job.result = value
            self._finish(job, "SUCCEEDED")
