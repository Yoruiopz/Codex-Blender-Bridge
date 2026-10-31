"""Owned Scene phases composed with the existing image-job controller.

Only trusted in-process adapters can start these records. No public simulation
tool is registered here. All inspection uses cached evidence, never Blender.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from time import monotonic as _INSPECTION_CLOCK
from types import (
    BuiltinFunctionType,
    CodeType,
    FunctionType,
    GetSetDescriptorType,
    MemberDescriptorType,
    ModuleType,
)
from typing import Any

from .checkpoint_completion import claim_native_push_completion
from .errors import BridgeError, ErrorCode, invalid_argument
from .job_controller import TERMINAL, CooperativeJobController
from .jobs import PaintJobs
from .mesh_storage_effects import MeshStorageJournal, snapshot_storage_effects
from .operation_lease import MutationInterlock, _InvocationRecord
from .protocol import utc_timestamp
from .request_lifecycle import RequestLifetime
from .request_lifecycle import threading as _inspection_threading
from .scene_job_authority import SceneJobAuthority, bind_permissions
from .scene_job_effects import EffectsStatus, SceneNativeEffects, snapshot_native_effects
from .scene_job_evidence import phase as phase_report
from .scene_job_evidence import plain
from .scene_job_evidence import progress as progress_report
from .scene_job_reservations import (
    INSPECTION_TURN_METHOD,
    TURN_METHOD,
    _Reservation,
    _Turn,
    refused,
)
from .task_plans import get_task_plans
from .tool_registry import ToolSpec, check_final_mutation

# Recognize the stock, nonblocking lifetime body; code membership alone cannot
# establish that a replacement hook is callback-free.
_INSPECTION_LIFETIME_CHECK = RequestLifetime.__dict__["check"]
_INSPECTION_LIFETIME_CODE = _INSPECTION_LIFETIME_CHECK.__code__

_INSPECTION_EVENT_KIND = _inspection_threading.Event
_INSPECTION_EVENT_IS_SET = _INSPECTION_EVENT_KIND.__dict__["is_set"]
_INSPECTION_EVENT_CODE = _INSPECTION_EVENT_IS_SET.__code__
_INSPECTION_INTERLOCK_KIND = MutationInterlock
_INSPECTION_INTERLOCK_OWNER = MutationInterlock.__dict__["check_owner"]
_INSPECTION_INTERLOCK_OWNER_CODE = _INSPECTION_INTERLOCK_OWNER.__code__
_INSPECTION_INTERLOCK_DICT = MutationInterlock.__dict__["__dict__"]


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


def _inspection_source(seal):
    raw = tuple.__getitem__
    function, code, namespace, defaults, keywords, closure = raw(seal, 7)
    native = raw(seal, 4)
    if (type(function) is not FunctionType or function.__code__ is not code or function.__globals__ is not namespace
            or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
        raise raw(native, 8)
    function(seal)


def _inspection_function(fact):
    function, code, namespace, defaults, keywords, rows, cells = fact
    if (type(function) is not FunctionType or function.__code__ is not code or function.__globals__ is not namespace
            or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
            or (keywords is not None and (type(keywords) is not dict or len(keywords) != len(rows)
                or any(type(k) is not str for k in keywords)
                or any(k not in keywords or keywords[k] is not v for k, v in rows)))
            or len(function.__closure__ or ()) != len(cells)
            or any(actual is not cell or actual.cell_contents is not value
                   for actual, (cell, value) in zip(function.__closure__ or (), cells, strict=True))):
        raise refused("INSPECTION_CALLBACK_SOURCE_CHANGED")


def _inspection_error(error, _type=type, _object=object, _len=len, _all=all,
                      _bool=bool, _str=str, _int=int, _float=float, _list=list, _tuple=tuple, _dict=dict, _failure=ValueError,
                      _error_dict=BaseException.__dict__["__dict__"]):
    """Copy stopped-job diagnostics without dynamic exception serializers."""
    fields = _error_dict.__get__(error, _type(error))
    code, message, raw = fields.get("code"), fields.get("message"), fields.get("context")
    remaining = [256, 1536]

    def copy(value, depth=0):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 8:
            raise _failure
        if value is None or _type(value) is _bool:
            return value
        if _type(value) is _str and _len(value) <= 2048:
            remaining[1] -= _len(value)
            if remaining[1] < 0:
                raise _failure
            return value
        if _type(value) is _int and value.bit_length() <= 64:
            return value
        if _type(value) is _float and -1e300 <= value <= 1e300:
            return value
        if _type(value) is _list or _type(value) is _tuple:
            return [copy(item, depth+1) for item in value]
        if _type(value) is _dict and _all(_type(key) is _str and _len(key) <= 128 for key in value):
            return {copy(key, depth+1): copy(item, depth+1) for key, item in value.items()}
        raise _failure

    try:
        context = copy(raw)
    except _failure:
        context = {"original_error_context_invalid": True}
    if _type(context) is not _dict:
        context = {"original_error_context_invalid": True}
    reason = context.get("reason")
    stale = _type(reason) is _str and reason in (
        "SCENE_RUNTIME_RESET", "SCENE_START_SPEC_CHANGED", "SCENE_START_PERMISSION_SOURCE_CHANGED",
        "STORAGE_SOURCE_CHANGED", "INSPECTION_DRIVER_STATE_CHANGED", "INSPECTION_DRIVER_SOURCE_CHANGED",
        "INSPECTION_CONTEXT_FACTORY_CHANGED", "INSPECTION_PHASE_COMMIT_CHANGED", "INSPECTION_ADMISSION_CHANGED",
        "INSPECTION_TURN_SPEC_CHANGED", "INSPECTION_ENTRY_PROVENANCE_CHANGED")
    context.setdefault("inspection_status", "STALE" if stale else "INCOMPLETE")
    context.update(ready=False, logical_write_capability=False, undo_boundary_created=False, undo_boundary_finalized=False)
    return {"code": code[:64] if _type(code) is _str else "OPERATION_FAILED",
            "message": message[:512] if _type(message) is _str else "Inspection stopped.", "context": context}


def _inspection_event_data(row, _type=type, _len=len, _any=any, _str=str, _dict=dict, _bool=bool):
    event, kind, _namespace, _methods, descriptor, saved = row
    if _type(event) is not kind:
        return None
    data = descriptor.__get__(event, kind)
    if (_type(data) is not _dict or _len(data) != _len(saved)+1 or _any(_type(name) is not _str for name in data)
            or _type(data.get("_flag")) is not _bool or _any(data.get(name) is not item for name, item in saved)):
        return None
    return data


def _inspection_ready_check(proof):
    seal, factory, authority, authority_rows, state_origin, lifetime, lifetime_rows, connection_rows, events, permissions, deadline = proof
    raw = ().__class__.__getitem__
    function, code, namespace, defaults, keywords, closure = raw(seal, 7)
    native = raw(seal, 4)
    if (raw(native, 0)(function) is not raw(native, 4) or function.__code__ is not code
            or function.__globals__ is not namespace or function.__defaults__ is not defaults
            or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
        raise raw(native, 8)
    function(seal)
    _inspection_context_factory_check(factory)
    if any(getattr(authority, name) is not value for name, value in authority_rows):
        raise refused("INSPECTION_READY_AUTHORITY_CHANGED")
    authority.check()
    state, store, epoch = state_origin
    if getattr(state, "_artist_task_plans", None) is not store or store.evidence_epoch != epoch:
        raise refused("SCENE_RUNTIME_RESET")
    controls = state.snapshot()
    if controls["emergency_stopped"] or controls["paused"]:
        raise refused("INSPECTION_READY_CONTROL_STOP")
    if any(getattr(lifetime, name) is not value for name, value in lifetime_rows):
        raise refused("INSPECTION_READY_LIFETIME_CHANGED")
    connection = lifetime.connection
    if any(getattr(connection, name) is not value for name, value in connection_rows):
        raise refused("INSPECTION_READY_CONNECTION_CHANGED")
    flags = {}
    for row in events:
        data = _inspection_event_data(row)
        if data is None:
            raise refused("INSPECTION_READY_EVENT_CHANGED")
        flags[id(row[0])] = data["_flag"]
    if (flags.get(id(lifetime.rejected)) or (connection is not None and flags.get(id(connection.disconnected)))
            or not flags.get(id(lifetime.delivered)) or time.monotonic() >= deadline):
        raise BridgeError(ErrorCode.TIMEOUT, "Inspection owner or deadline no longer permits readiness.",
                          {"inspection_status": "INCOMPLETE"})
    from .mesh_storage_source import _check_callback
    for manager, kind, descriptor, rows, provider in permissions:
        if type(manager) is not kind:
            raise refused("INSPECTION_READY_PERMISSION_SOURCE_CHANGED")
        data = descriptor.__get__(manager, kind)
        if (type(data) is not dict or len(data) != len(rows) or any(type(name) is not str for name in data)
                or any(data.get(name) is not value for name, value in rows)):
            raise refused("INSPECTION_READY_PERMISSION_SOURCE_CHANGED")
        if provider is not None:
            _check_callback(data.get("_source"), provider)


def _inspection_driver(driver):
    import sys
    kind = type(driver)
    module = sys.modules.get(__package__ + ".tools._mesh_storage_inspection")
    if type(module) is not ModuleType or vars(module).get("MeshStorageInspectionDriver") is not kind:
        raise refused("INSPECTION_DRIVER_ORIGIN_CHANGED")
    classes = _storage_class_facts(kind)
    descriptor = next((value for _base, _mro, fields, _functions in classes for name, value in fields if name == "__dict__"), None)
    if type(descriptor) is not GetSetDescriptorType:
        raise refused("INSPECTION_DRIVER_ORIGIN_CHANGED")
    fields = descriptor.__get__(driver, kind)
    if type(fields) is not dict or any(type(key) is not str for key in fields):
        raise refused("INSPECTION_DRIVER_ORIGIN_CHANGED")
    seal = fields.get("source_seal")
    _inspection_source(seal)
    methods = {name: next(value for _base, _mro, rows, _functions in classes for key, value in rows if key == name)
               for name in ("check_after_read", "advance")}
    proof = (driver, kind, classes, descriptor, seal, tuple(fields.items()),
             tuple((name, _storage_function_fact(function)) for name, function in methods.items()))
    _inspection_driver_check(proof)
    return proof


def _inspection_driver_check(proof, *, instance=True):
    _inspection_source(proof[4])
    return _inspection_driver_fields(proof, instance=instance)


def _inspection_driver_fields(proof, *, instance=True):
    """Source-closed Python fields; no provider, native read or callback."""
    driver, kind, classes, descriptor, seal, owned, methods = proof
    for base, mro, saved, functions in classes:
        fields = type.__dict__["__dict__"].__get__(base)
        if (type.__dict__["__mro__"].__get__(base) is not mro or len(fields) != len(saved)
                or any(type(key) is not str for key in fields)
                or any(name not in fields or fields[name] is not value for name, value in saved)):
            raise refused("INSPECTION_DRIVER_SOURCE_CHANGED")
        for fact in functions:
            _inspection_function(fact)
    fields = descriptor.__get__(driver, kind)
    if (type(driver) is not kind or type(fields) is not dict or any(type(key) is not str for key in fields)
            or any(name in fields for name in ("check_after_read", "advance")) or fields.get("source_seal") is not seal
            or (instance and (len(fields) != len(owned) or any(name not in fields or fields[name] is not value for name, value in owned)))):
        raise refused("INSPECTION_DRIVER_STATE_CHANGED")
    for _name, fact in methods:
        _inspection_function(fact)
    return fields



def _inspection_driver_union_fields(proof, class_check, function_check, *, instance=True):
    """Source-closed Python fields; no provider, native read or callback."""
    driver, kind, classes, descriptor, seal, owned, methods = proof
    for row in classes:
        class_check(row)
    fields = descriptor.__get__(driver, kind)
    if (type(driver) is not kind or type(fields) is not dict or any(type(key) is not str for key in fields)
            or any(name in fields for name in ("check_after_read", "advance")) or fields.get("source_seal") is not seal
            or (instance and (len(fields) != len(owned) or any(name not in fields or fields[name] is not value for name, value in owned)))):
        raise refused("INSPECTION_DRIVER_STATE_CHANGED")
    for _name, fact in methods:
        function_check(fact)
    return fields


def _inspection_fields(value, kind):
    """Read owned fields through native descriptors, without access hooks."""
    classes = _storage_class_facts(kind)
    merged = {name: item for _base, _mro, rows, _functions in reversed(classes) for name, item in rows}
    if (type(value) is not kind or merged.get("__getattribute__") is not object.__getattribute__
            or merged.get("__setattr__") is not object.__setattr__ or "__getattr__" in merged):
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    descriptor = merged.get("__dict__")
    if type(descriptor) is not GetSetDescriptorType:
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    fields = descriptor.__get__(value, kind)
    if type(fields) is not dict or any(type(key) is not str for key in fields):
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    return fields, descriptor, classes


def _inspection_context_factory(context, seal):
    """Pin the actual Runtime constructor's queued-resumption factory."""
    import sys
    _inspection_source(seal)
    runtime_module = sys.modules.get(__package__ + ".runtime")
    helper_module = sys.modules.get(__package__ + ".glb_stage_runtime")
    if type(runtime_module) is not ModuleType or type(helper_module) is not ModuleType:
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    runtime = vars(runtime_module).get("_RUNTIME")
    kind = vars(runtime_module).get("_CANONICAL_RUNTIME_CLASS")
    fields, descriptor, classes = _inspection_fields(runtime, kind)
    constructor = type.__dict__["__dict__"].__get__(kind).get("__init__")
    if (type(constructor) is not FunctionType or constructor.__globals__ is not vars(runtime_module)
            or constructor.__code__ is not vars(runtime_module).get("_RUNTIME_CONSTRUCTOR_CODE")):
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    jobs, executor, service = fields.get("jobs"), fields.get("executor"), fields.get("glb_stage")
    job_fields, job_descriptor, job_classes = _inspection_fields(jobs, type(jobs))
    execution, executor_descriptor, executor_classes = _inspection_fields(executor, vars(runtime_module).get("MainThreadExecutor"))
    service_fields, service_descriptor, service_classes = _inspection_fields(service, vars(helper_module).get("GLBStageService"))
    registry_fields, registry_descriptor, registry_classes = _inspection_fields(fields.get("registry"), vars(runtime_module).get("ToolRegistry"))
    permission_fields, permission_descriptor, permission_classes = _inspection_fields(fields.get("permissions"), vars(runtime_module).get("PermissionManager"))
    state_fields, state_descriptor, state_classes = _inspection_fields(fields.get("state"), vars(runtime_module).get("BridgeState"))
    reservations = job_fields.get("reservations")
    reservation_fields, reservation_descriptor, reservation_classes = _inspection_fields(reservations, type(reservations))
    factory = job_fields.get("context_factory")
    if (type(factory) is not FunctionType or factory.__globals__ is not vars(runtime_module)
            or not any(factory.__code__ is code for code in constructor.__code__.co_consts if type(code) is CodeType)
            or factory.__code__.co_names != ("checked_executor_context", "executor")
            or factory.__code__.co_freevars != ("self",) or len(factory.__closure__ or ()) != 1
            or factory.__closure__[0].cell_contents is not runtime or factory.__defaults__ is not None
            or factory.__kwdefaults__ is not None or context.jobs is not jobs
            or context.registry is not fields.get("registry") or context.state is not fields.get("state")
            or context.permissions is not fields.get("permissions") or context.checkpoints is not fields.get("checkpoints")
            or context.glb_stage is not service or service_fields.get("runtime") is not runtime
            or job_fields.get("registry") is not fields.get("registry")
            or reservations is not registry_fields.get("_scene_reservations")
            or reservation_fields.get("registry") is not fields.get("registry")
            or service_fields.get("_executor_origin") is not executor
            or any(execution.get(name) is not fields.get(name) for name in ("jobs", "registry", "state", "permissions", "checkpoints", "glb_stage"))):
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    provider = permission_fields.get("_source")
    if (type(provider) is not FunctionType or provider.__globals__ is not vars(runtime_module)
            or not any(provider.__code__ is code for code in constructor.__code__.co_consts if type(code) is CodeType)
            or provider.__code__.co_names != ("permission_snapshot", "_preferences")
            or provider.__closure__ is not None or provider.__defaults__ is not None or provider.__kwdefaults__ is not None):
        raise refused("INSPECTION_PERMISSION_PROVIDER_ORIGIN_CHANGED")
    helper = vars(runtime_module).get("checked_executor_context")
    if helper is not vars(helper_module).get("checked_executor_context"):
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    objects = tuple((value, type(value), desc, class_rows, tuple((name, data.get(name)) for name in names))
        for value, data, desc, class_rows, names in (
            (runtime, fields, descriptor, classes, ("jobs", "executor", "glb_stage", "registry", "state", "permissions", "checkpoints")),
            (jobs, job_fields, job_descriptor, job_classes, ("context_factory", "registry", "reservations", "history", "_main_thread",
                "_inspection_spec", "_inspection_spec_origin", "_inspection_records", "_inspection_ready")),
            (executor, execution, executor_descriptor, executor_classes, ("jobs", "registry", "state", "permissions", "checkpoints", "glb_stage", "evidence")),
            (service, service_fields, service_descriptor, service_classes, ("runtime", "_executor_origin", "jobs", "registry", "state", "checkpoints")),
            (fields["registry"], registry_fields, registry_descriptor, registry_classes,
                ("_tools", "_mutation_interlock", "_scene_reservations", "_enabled_toolsets")),
            (fields["permissions"], permission_fields, permission_descriptor, permission_classes, ("_source",)),
            (fields["state"], state_fields, state_descriptor, state_classes, ("_lock",)),
            (reservations, reservation_fields, reservation_descriptor, reservation_classes,
                ("registry", "_retained", "_turns", "_inspection_turns", "_inspection_proofs"))))
    functions = tuple(_storage_function_fact(value) for value in vars(helper_module).values() if type(value) is FunctionType)
    proof = (seal, runtime_module, runtime, factory, _storage_function_fact(factory), helper_module,
             tuple(vars(helper_module).items()), (*functions, _storage_function_fact(provider)), objects)
    _inspection_context_factory_check(proof)
    return proof


def _inspection_context_factory_check(proof):
    _inspection_source(proof[0])
    _inspection_context_factory_fields(proof)


def _inspection_context_factory_fields(proof):
    """Source-closed Python fields; callers verify the whole source first."""
    _seal, runtime_module, runtime, _factory, fact, helper_module, namespace, functions, objects = proof
    if vars(runtime_module).get("_RUNTIME") is not runtime:
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    current = vars(helper_module)
    if (len(current) != len(namespace) or any(type(name) is not str for name in current)
            or any(name not in current or current[name] is not value for name, value in namespace)):
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    for function in (fact, *functions):
        _inspection_function(function)
    for value, kind, descriptor, classes, rows in objects:
        for base, mro, saved, methods in classes:
            current = type.__dict__["__dict__"].__get__(base)
            if (type.__dict__["__mro__"].__get__(base) is not mro or len(current) != len(saved)
                    or any(name not in current or current[name] is not item for name, item in saved)):
                raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
            for method in methods:
                _inspection_function(method)
        current = descriptor.__get__(value, kind)
        if (type(value) is not kind or type(current) is not dict or any(type(name) is not str for name in current)
                or any(name not in current or current[name] is not item for name, item in rows)
                or any(name in current for _base, _mro, _saved, methods in classes for method in methods
                       for name in (method[0].__name__,))):
            raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")



def _inspection_context_factory_union_fields(proof, class_check, function_check):
    """Source-closed Python fields; callers verify the whole source first."""
    _seal, runtime_module, runtime, _factory, fact, helper_module, namespace, functions, objects = proof
    if vars(runtime_module).get("_RUNTIME") is not runtime:
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    current = vars(helper_module)
    if (len(current) != len(namespace) or any(type(name) is not str for name in current)
            or any(name not in current or current[name] is not value for name, value in namespace)):
        raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
    for function in (fact, *functions):
        function_check(function)
    for value, kind, descriptor, classes, rows in objects:
        for row in classes:
            class_check(row)
        current = descriptor.__get__(value, kind)
        if (type(value) is not kind or type(current) is not dict or any(type(name) is not str for name in current)
                or any(name not in current or current[name] is not item for name, item in rows)
                or any(name in current for _base, _mro, saved, _methods in classes
                       for name, value in saved if type(value) is FunctionType)):
            raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")


def _inspection_slot(owner, kind, name):
    if type(owner) is not kind:
        raise refused("INSPECTION_ADMISSION_CHANGED")
    descriptor = type.__dict__["__dict__"].__get__(kind).get(name)
    if (type(descriptor) is not MemberDescriptorType or descriptor.__objclass__ is not kind
            or descriptor.__name__ != name):
        raise refused("INSPECTION_ADMISSION_CHANGED")
    return descriptor.__get__(owner, kind)


def _inspection_bind(admission):
    from .mesh_storage_source import _verify_context_fields, capture_context
    admission_type = type(admission)
    if admission_type is not _InspectionAdmission and admission_type is not _InspectionTurnAdmission:
        raise refused("INSPECTION_ADMISSION_CHANGED")
    context, proof = admission.context, admission.driver_proof
    _inspection_driver_check(proof)
    factory_proof = admission.factory_proof
    _inspection_context_factory_check(factory_proof)
    captured = capture_context(context, proof[4])
    object.__setattr__(admission, "inspection_context_proof", captured)
    owned = tuple((name, _inspection_slot(admission, admission_type, name)) for name in admission_type.__slots__
                  if name not in {"entry_guard", "entry_proof"})
    turn = _inspection_slot(admission, admission_type, "turn") if admission_type is _InspectionTurnAdmission else None
    if turn is not None and type(turn) is not _Turn:
        raise refused("INSPECTION_ADMISSION_CHANGED")
    turn_rows = () if turn is None else tuple((name, _inspection_slot(turn, _Turn, name)) for name in _Turn.__slots__
                                             if name not in {"inspection_entry_proof", "permission_denial"})
    owner = None if turn is None else _inspection_slot(turn, _Turn, "owner")
    if owner is not None and type(owner) is not _Reservation:
        raise refused("INSPECTION_ADMISSION_CHANGED")
    owner_rows = () if owner is None else tuple((name, _inspection_slot(owner, _Reservation, name)) for name in _Reservation.__slots__
                                               if name != "stopped")
    driver_fields, factory_fields, context_fields = (_inspection_driver_fields,
        _inspection_context_factory_fields, _verify_context_fields)
    record_fields = SceneJobs.__dict__["_inspection_record_fields"]
    leaf_facts = tuple(_storage_function_fact(function)
                       for function in (driver_fields, factory_fields, context_fields, record_fields))
    record = None
    if turn is not None:
        service = context.jobs
        row = next(item for item in factory_proof[8] if item[0] is service)
        service_fields = row[2].__get__(service, row[1])
        records = dict.get(service_fields, "_inspection_records")
        if type(records) is not dict or any(type(key) is not int for key in records):
            raise refused("INSPECTION_RECORD_LOST")
        record = dict.get(records, id(admission.job))

    for row in proof[2]:
        for fact in row[3]:
            _inspection_function(fact)
    for obj in factory_proof[8]:
        for row in obj[3]:
            for fact in row[3]:
                _inspection_function(fact)

    # Immutable auxiliary facts are not authority: the local Gate union must
    # first prove this canonical admission and its owned closure.
    interlock = context.registry._mutation_interlock
    interlock_kind = type(interlock)
    auxiliary = (frozenset(id(row[0]) for row in proof[4][1]),
                 frozenset(id(row[0]) for row in proof[4][2]),
                 interlock, interlock_kind, _storage_class_facts(interlock_kind))

    def entry_fields(driver_check, factory_check, context_check, record_check):
        """Held local leaf; only a freshly source-verified caller may dispatch."""
        if type(auxiliary) is not tuple or len(auxiliary) != 5:
            raise refused("INSPECTION_ADMISSION_CHANGED")
        for leaf_fact in leaf_facts:
            _inspection_function(leaf_fact)
        if (type(admission) is not admission_type
                or any(_inspection_slot(admission, admission_type, name) is not value for name, value in owned)
                or any(_inspection_slot(turn, _Turn, name) is not value for name, value in turn_rows)
                or any(_inspection_slot(owner, _Reservation, name) is not value for name, value in owner_rows)
                or admission.entry_guard is not checked or type(admission.entry_proof) is not tuple
                or len(admission.entry_proof) != 7 or admission.entry_proof[0] is not checked
                or admission.driver_proof is not proof or admission.factory_proof is not factory_proof
                or admission.inspection_context_proof is not captured):
            raise refused("INSPECTION_ADMISSION_CHANGED")
        driver_check()
        factory_check()
        context_check()
        for manager, kind, descriptor, rows, _provider in captured[11]:
            data = descriptor.__get__(manager, kind)
            if (type(data) is not dict or len(data) != len(rows) or any(type(name) is not str for name in data)
                    or any(data.get(name) is not value for name, value in rows)):
                raise refused("INSPECTION_PERMISSION_INSTANCE_CHANGED")
        if admission_type is _InspectionTurnAdmission:
            record_check()

    def checked():
        # One held full verification covers only this callback-free field chain.
        raw = tuple.__getitem__
        seal = raw(proof, 4)
        function, code, namespace, defaults, keywords, closure = raw(seal, 7)
        native = raw(seal, 4)
        if (type(function) is not FunctionType or function.__code__ is not code or function.__globals__ is not namespace
                or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
            raise raw(native, 8)
        function(seal)
        _inspection_function(entry_fields_fact)
        entry_fields(lambda: driver_fields(proof), lambda: factory_fields(factory_proof),
                     lambda: context_fields(context, captured),
                     lambda: record_fields(context.jobs, admission.job, record))

    entry_fields_fact = _storage_function_fact(entry_fields)

    object.__setattr__(admission, "entry_guard", checked)
    object.__setattr__(admission, "entry_proof", (checked, checked.__code__, checked.__globals__, checked.__defaults__,
        checked.__kwdefaults__, checked.__closure__, tuple((cell, cell.cell_contents) for cell in checked.__closure__ or ())))


def _inspection_gate_pure(gate, seal, cell):
    """Run one exact canonical read Gate with a synchronous local fact union.

    Gate has just dispatched its held source verifier. Unknown contexts/hooks
    keep the ordinary path. No union state escapes this call, crosses I/O or a
    snapshot lock, or grants a writer/native capability.
    """
    # Resolve only namespaces already owned and verified by the incoming seal;
    # do not follow a fresh import through mutable process/package aliases.
    pairs = [(ModuleType.__getattribute__(module, "__dict__").get("__name__"), module)
             for module, _saved in tuple.__getitem__(seal, 0)]
    if type(__package__) is not str or any(type(name) is not str for name, _module in pairs):
        return False
    modules = dict(pairs)
    if __package__ + ".scene_job_reservations" not in modules:
        return False  # Ordinary storage Gate seals never admit this branch.
    source_fields = ModuleType.__getattribute__(modules[__package__ + ".mesh_storage_source"], "__dict__")
    CheckpointAdmissionBinding = source_fields["CheckpointAdmissionBinding"]
    ToolContext = source_fields["ToolContext"]
    _context_slot = source_fields["_context_slot"]
    _verify_context_fields = source_fields["_verify_context_fields"]
    available_memory_facts = source_fields["available_memory_facts"]
    contract = source_fields["contract"]
    checkpoint_completion = modules[__package__ + ".checkpoint_completion"]
    request_lifecycle = modules[__package__ + ".request_lifecycle"]
    scene_job_reservations = modules[__package__ + ".scene_job_reservations"]
    registry_fields = ModuleType.__getattribute__(modules[__package__ + ".tool_registry"], "__dict__")
    _inspection_final_fields = registry_fields["_inspection_final_fields"]
    task_fields = ModuleType.__getattribute__(modules[__package__ + ".task_plans"], "__dict__")
    TaskPlanStore = task_fields["TaskPlanStore"]
    ConnectionLifetime = ModuleType.__getattribute__(request_lifecycle, "__dict__")["ConnectionLifetime"]
    Permission = ModuleType.__getattribute__(modules[__package__ + ".permissions"], "__dict__")["Permission"]

    context = cell["context"]
    if type(context) is not ToolContext:
        return False
    binding = _context_slot(context, ToolContext, "checkpoint_admission")
    if type(binding) is not CheckpointAdmissionBinding:
        return False
    admission = _context_slot(binding, CheckpointAdmissionBinding, "callback")
    if type(admission) is not _InspectionTurnAdmission:
        return False
    _verify_context_fields(context, cell["context_proof"])
    proof = _inspection_slot(admission, _InspectionTurnAdmission, "driver_proof")
    factory = _inspection_slot(admission, _InspectionTurnAdmission, "factory_proof")
    captured = _inspection_slot(admission, _InspectionTurnAdmission, "inspection_context_proof")
    entry = _inspection_slot(admission, _InspectionTurnAdmission, "entry_proof")
    if (type(proof) is not tuple or len(proof) != 7 or proof[4] is not seal
            or type(factory) is not tuple or len(factory) != 9 or factory[0] is not seal
            or type(entry) is not tuple or len(entry) != 7):
        return False
    function, code, namespace, defaults, keywords, cells, contents = entry
    if (type(function) is not FunctionType or function.__code__ is not code
            or function.__globals__ is not namespace or function.__defaults__ is not defaults
            or function.__kwdefaults__ is not keywords or function.__closure__ is not cells
            or len(cells or ()) != len(contents)
            or any(actual is not old or actual.cell_contents is not value
                   for actual, (old, value) in zip(cells or (), contents, strict=True))
            or admission.entry_guard is not function):
        return False
    closed = dict(zip(code.co_freevars, (item.cell_contents for item in cells or ()), strict=True))
    entry_fields_fact = closed.get("entry_fields_fact")
    if type(entry_fields_fact) is not tuple or len(entry_fields_fact) != 7:
        return False
    try:
        _inspection_function(entry_fields_fact)
    except BridgeError:
        return False
    entry_fields = entry_fields_fact[0]
    field_closed = dict(zip(entry_fields.__code__.co_freevars,
        (item.cell_contents for item in entry_fields.__closure__ or ()), strict=True))
    auxiliary = field_closed.get("auxiliary")
    record = closed.get("record")
    if (type(auxiliary) is not tuple or len(auxiliary) != 5
            or type(record) is not tuple or len(record) != 7):
        return False
    source_classes, source_functions, interlock, interlock_kind, interlock_classes = auxiliary
    turn = _inspection_slot(admission, _InspectionTurnAdmission, "turn")
    job = _inspection_slot(admission, _InspectionTurnAdmission, "job")
    if type(turn) is not _Turn or type(job) is not InspectionJob or type(turn.owner) is not _Reservation:
        return False
    owner = turn.owner

    def eligible():
        # Eligibility reads only native slots/dictionaries. In particular no
        # foreign clock, Event getter, __hash__ or __eq__ is called to decide.
        if (type(_INSPECTION_CLOCK) is not BuiltinFunctionType
                or type(request_lifecycle.time) is not ModuleType
                or type(scene_job_reservations.time) is not ModuleType
                or vars(request_lifecycle.time).get("monotonic") is not _INSPECTION_CLOCK
                or vars(scene_job_reservations.time).get("monotonic") is not _INSPECTION_CLOCK
                or RequestLifetime.__dict__.get("check") is not _INSPECTION_LIFETIME_CHECK
                or _INSPECTION_LIFETIME_CHECK.__code__ is not _INSPECTION_LIFETIME_CODE
                or _INSPECTION_EVENT_KIND.__dict__.get("is_set") is not _INSPECTION_EVENT_IS_SET
                or _INSPECTION_EVENT_IS_SET.__code__ is not _INSPECTION_EVENT_CODE
                or any(type(row[0]) is not _INSPECTION_EVENT_KIND for row in captured[10])
                or type(context.request_lifecycle) is not RequestLifetime
                or type(_context_slot(context.request_lifecycle, RequestLifetime, "deadline")) not in (int, float)
                or type(turn.used) is not bool or type(turn.check_only) is not bool
                or type(binding.active) is not bool or type(binding.method) is not str
                or (context.checkpoint_method is not None and type(context.checkpoint_method) is not str)
                or context.check_final_request is not None
                or type(checkpoint_completion._consumers) is not dict
                or checkpoint_completion._consumers):
            return False
        for kind in (RequestLifetime, ConnectionLifetime, _INSPECTION_EVENT_KIND):
            fields = type.__dict__["__dict__"].__get__(kind)
            if (fields.get("__getattribute__", object.__getattribute__) is not object.__getattribute__
                    or fields.get("__setattr__", object.__setattr__) is not object.__setattr__
                    or "__getattr__" in fields):
                return False
        if "_flag" in type.__dict__["__dict__"].__get__(_INSPECTION_EVENT_KIND):
            return False
        owned_data = {}
        for value, kind, descriptor, _classes, _rows in factory[8]:
            if type(value) is not kind or type(descriptor) is not GetSetDescriptorType:
                return False
            data = descriptor.__get__(value, kind)
            if type(data) is not dict or any(type(key) is not str for key in data):
                return False
            owned_data[id(value)] = data
        registry_data = owned_data.get(id(context.registry))
        jobs_data = owned_data.get(id(context.jobs))
        if registry_data is None or jobs_data is None:
            return False
        hook = context.check_final_job
        if (type(hook) is not FunctionType or hook.__globals__ is not globals()
                or hook.__defaults__ is not None or hook.__kwdefaults__ is not None
                or hook.__code__.co_freevars != ("record", "self", "token")
                or hook.__code__.co_names != ("_inspection_context_factory_check", "reservations", "check_inspection_turn")
                or not any(hook.__code__ is value for origin in (SceneJobs._advance_work, SceneJobs._tick_check)
                           for value in origin.__code__.co_consts if type(value) is CodeType)
                or len(hook.__closure__ or ()) != 3
                or any(item.cell_contents is not expected for item, expected in
                       zip(hook.__closure__ or (), (record, context.jobs, turn.token), strict=True))):
            return False
        # No custom rich comparison may enter the closed live replay.
        tools = registry_data.get("_tools")
        enabled = registry_data.get("_enabled_toolsets")
        records = jobs_data.get("_inspection_records")
        if (type(tools) is not dict or any(type(key) is not str for key in tools)
                or type(enabled) is not set or any(type(key) is not str for key in enabled)
                or type(records) is not dict or any(type(key) is not int for key in records)
                or type(owner.allowlist) is not tuple or type(owner.authority) is not SceneJobAuthority
                or type(job.deadline) not in (float, int) or type(turn.inspection_deadline) not in (float, int)
                or type(job.cancel_reason) is not str or type(owner.stopped) is not str
                or type(owner.epoch) is not int
                or type(job.phase) is not str or type(turn.phase) is not str
                or type(job.revision) is not int or type(turn.revision) is not int
                or job.pending is not None or job.lifetime is not context.request_lifecycle
                or interlock_kind is not _INSPECTION_INTERLOCK_KIND
                or type(interlock) is not _INSPECTION_INTERLOCK_KIND):
            return False
        interlock_class = type.__dict__["__dict__"].__get__(_INSPECTION_INTERLOCK_KIND)
        if (interlock_class.get("check_owner") is not _INSPECTION_INTERLOCK_OWNER
                or _INSPECTION_INTERLOCK_OWNER.__code__ is not _INSPECTION_INTERLOCK_OWNER_CODE
                or interlock_class.get("__dict__") is not _INSPECTION_INTERLOCK_DICT
                or interlock_class.get("__getattribute__", object.__getattribute__) is not object.__getattribute__
                or interlock_class.get("__setattr__", object.__setattr__) is not object.__setattr__
                or "__getattr__" in interlock_class
                or type.__dict__["__mro__"].__get__(_INSPECTION_INTERLOCK_KIND) != (_INSPECTION_INTERLOCK_KIND, object)):
            return False
        interlock_data = _INSPECTION_INTERLOCK_DICT.__get__(interlock, _INSPECTION_INTERLOCK_KIND)
        if (type(interlock_data) is not dict or any(type(key) is not str for key in interlock_data)
                or "check_owner" in interlock_data or type(interlock_data.get("_entries")) is not list
                or any(type(item) is not _InvocationRecord for item in interlock_data["_entries"])):
            return False
        # Native frozenset comparison is pure only with the stock string Enum
        # equality/hash slots; read raw class dictionaries, never descriptors.
        enum_slots = {}
        for base in type.__dict__["__mro__"].__get__(Permission):
            fields = type.__dict__["__dict__"].__get__(base)
            for name in ("__eq__", "__hash__"):
                if name not in enum_slots and name in fields:
                    enum_slots[name] = fields[name]
        if enum_slots.get("__eq__") is not str.__eq__ or enum_slots.get("__hash__") is not str.__hash__:
            return False
        declared = owner.authority.declared_permissions
        if type(declared) is not frozenset or any(type(item) is not Permission for item in declared):
            return False
        for spec in (*owner.allowlist, turn.spec, owner.authority.spec):
            if (type(spec) is not ToolSpec or type(spec.name) is not str
                    or type(spec.toolset) is not str or type(spec.modifies) is not bool
                    or type(spec.permissions) is not frozenset
                    or any(type(item) is not Permission for item in spec.permissions)):
                return False
        reservation_data = owned_data.get(id(jobs_data.get("reservations")))
        if reservation_data is None:
            return False
        tables = [scene_job_reservations._inspection_origins,
                  *(reservation_data.get(name) for name in
                    ("_retained", "_turns", "_inspection_turns", "_inspection_proofs"))]
        if any(type(table) is not dict or any(type(key) is not int for key in table) for table in tables):
            return False
        origin = job.state_origin
        if (type(origin) is not tuple or len(origin) != 3 or origin[0] is not context.state
                or type(origin[1]) is not TaskPlanStore or type(origin[2]) is not int
                or type(owner.authority.method) is not str or type(owner.authority.toolset) is not str
                or type(reservation_data.get("epoch")) is not int):
            return False
        state_data = owned_data.get(id(context.state))
        store_class = type.__dict__["__dict__"].__get__(TaskPlanStore)
        if (state_data is None or state_data.get("_artist_task_plans") is not origin[1]
                or store_class.get("__getattribute__", object.__getattribute__) is not object.__getattribute__
                or store_class.get("__setattr__", object.__setattr__) is not object.__setattr__
                or "__getattr__" in store_class or "evidence_epoch" in store_class):
            return False
        store_descriptor = store_class.get("__dict__")
        if type(store_descriptor) is not GetSetDescriptorType:
            return False
        store_data = store_descriptor.__get__(origin[1], TaskPlanStore)
        if (type(store_data) is not dict or any(type(key) is not str for key in store_data)
                or type(store_data.get("evidence_epoch")) is not int):
            return False
        for rows in (turn.inspection_spec, owner.authority.inspection_spec):
            if (type(rows) is not tuple or any(type(row) is not tuple or len(row) != 2
                    or type(row[0]) is not str for row in rows)):
                return False
        return True

    if not eligible():
        return False
    def same_facts(left, right):
        if left is right:
            return True
        return (type(left) is tuple and type(right) is tuple and len(left) == len(right)
                and all(same_facts(a, b) for a, b in zip(left, right, strict=True)))
    shared_context_facts = same_facts(cell["context_proof"], captured)
    seen_classes, seen_functions = set(), set()
    seen_families = {"context"} if shared_context_facts else set()
    active = True

    def class_check(row):
        base, mro, saved, functions = row
        key = id(base)
        if key in source_classes or key in seen_classes:
            return
        fields = type.__dict__["__dict__"].__get__(base)
        if (type.__dict__["__mro__"].__get__(base) is not mro or len(fields) != len(saved)
                or any(type(name) is not str for name in fields)
                or any(name not in fields or fields[name] is not value for name, value in saved)):
            raise refused("INSPECTION_DRIVER_SOURCE_CHANGED")
        seen_classes.add(key)
        for fact in functions:
            function_check(fact)

    def function_check(fact):
        key = id(fact[0])
        if key not in source_functions and key not in seen_functions:
            _inspection_function(fact)
            seen_functions.add(key)

    def family(name, callback):
        if name not in seen_families:
            callback()
            seen_families.add(name)

    def driver_check():
        family("driver", lambda: _inspection_driver_union_fields(proof, class_check, function_check))

    def factory_check():
        family("factory", lambda: _inspection_context_factory_union_fields(factory, class_check, function_check))

    def context_check():
        family("context", lambda: _verify_context_fields(context, captured))

    def record_check():
        family("record", lambda: _inspection_record_union_fields(context.jobs, job, record, factory_check, driver_check))

    def entry_check(actual):
        if actual is not entry:
            raise refused("INSPECTION_ENTRY_PROVENANCE_CHANGED")
        def verify_entry():
            # Dynamic functions are absent from the module SourceSeal rows.
            # Re-prove their original closure cells at each segment's first use.
            function, code, namespace, defaults, keywords, cells, contents = entry
            if (function.__code__ is not code or function.__globals__ is not namespace
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
                    or function.__closure__ is not cells or len(cells or ()) != len(contents)
                    or any(actual is not old or actual.cell_contents is not value
                           for actual, (old, value) in zip(cells or (), contents, strict=True))):
                raise refused("INSPECTION_ENTRY_SOURCE_CHANGED")
            _inspection_function(entry_fields_fact)
            entry_fields(driver_check, factory_check, context_check, record_check)
        family("entry", verify_entry)

    def renew():
        nonlocal active
        # Called only after a successful boundary and its original returned
        # resource/control validation. Failure is never hidden by a post-check.
        verifier, code, namespace, defaults, keywords, closure = tuple.__getitem__(seal, 7)
        native = tuple.__getitem__(seal, 4)
        if (type(verifier) is not FunctionType or verifier.__code__ is not code
                or verifier.__globals__ is not namespace or verifier.__defaults__ is not defaults
                or verifier.__kwdefaults__ is not keywords or verifier.__closure__ is not closure):
            raise tuple.__getitem__(native, 8)
        verifier(seal)
        seen_classes.clear()
        seen_functions.clear()
        seen_families.clear()
        if not shared_context_facts:
            _verify_context_fields(context, cell["context_proof"])
        context_check()
        factory_check()
        driver_check()
        record_check()
        entry_check(entry)
        active = active and eligible()

    def interlock_check():
        def verify_interlock():
            for row in interlock_classes:
                class_check(row)
        family("interlock", verify_interlock)

    def job_check():
        factory_check()
        context.jobs.reservations._inspection_check_turn_fields(turn.token, entry_check, interlock_check)

    def owner_check(spec, actual_context):
        interlock_check()
        interlock.check_owner(actual_context.registry, spec, actual_context)
        row = context.jobs.reservations._inspection_current_fields(context, entry_check, interlock_check)
        record_check()
        binding_now = context.checkpoint_admission
        if binding_now is not None:
            if row.binding is not binding_now or row.inspection_entry_proof is None:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Inspection admission ownership changed.")
            entry_check(row.inspection_entry_proof)
        flags = context.state.snapshot()  # Hard RLock boundary, including release.
        if flags["emergency_stopped"]:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Inspection emergency-stopped before its next read.")
        if flags["paused"] and not row.check_only:
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Inspection paused before its next read.")
        renew()

    method = context.checkpoint_method or (TURN_METHOD if context.check_final_job is not None else cell["method"])
    if context.registry is not cell["registry"] or context.state is not cell["state"]:
        raise refused("STORAGE_RUNTIME_CONTEXT_CHANGED")
    _inspection_final_fields(context, method, job_check, owner_check)
    if get_task_plans(cell["state"]).evidence_epoch != cell["epoch"]:
        raise contract.refused("STORAGE_TASK_PLAN_CHANGED")
    facts = available_memory_facts()  # Hard external-I/O boundary.
    available = facts["available_memory_bytes"]
    if type(available) is not int or available < cell["floor"]:
        raise contract.refused("STORAGE_LIVE_MEMORY_REFUSED")
    cell["last_available"] = available
    renew()
    if active:
        _inspection_final_fields(context, method, job_check, owner_check)
    else:
        check_final_mutation(context, method)
    return True


@dataclass(frozen=True, slots=True, eq=False)
class _InspectionAdmission:
    context: Any
    params: Any
    authority: Any
    allowlist: tuple
    state_origin: tuple
    driver: Any
    driver_proof: tuple
    inspection_context_proof: Any = None
    entry_guard: Any = None
    entry_proof: Any = None
    factory_proof: Any = None

    def __init__(self, context, params, factory):
        authority = SceneJobAuthority.capture_inspection(context, params)
        allowlist = context.registry._scene_reservations.capture_allowlist()
        store = get_task_plans(context.state)
        driver = factory(context, params)  # Cheap Python capture only; no native reads.
        proof = _inspection_driver(driver)
        context.jobs._ensure_inspection_spec()
        factory_proof = _inspection_context_factory(context, proof[4])
        authority = authority.include_driver_permissions(tuple(driver.required_permissions))
        for name, value in (("context", context), ("params", params), ("authority", authority), ("allowlist", allowlist),
                ("state_origin", (context.state, store, store.evidence_epoch)), ("driver", driver), ("driver_proof", proof),
                ("inspection_context_proof", None), ("entry_guard", None), ("entry_proof", None), ("factory_proof", factory_proof)):
            object.__setattr__(self, name, value)

    def bind_checkpoint(self, _binding):
        _inspection_bind(self)

    def __call__(self):
        self.check_after_read()

    def check_after_read(self):
        self.entry_guard()
        self.driver_proof[6][0][1][0](self.driver, self.context)
        self.authority.check()
        state, store, epoch = self.state_origin
        if self.context.state is not state or getattr(state, "_artist_task_plans", None) is not store or store.evidence_epoch != epoch:
            raise refused("SCENE_RUNTIME_RESET")
        self.context.registry._scene_reservations.check_allowlist(self.allowlist)
        check_final_mutation(self.context, self.authority.method)


def inspection_admission(factory):
    """A held registered factory, never a client-selected callback or token."""
    fact = _storage_function_fact(factory)
    function_check, admission_type = _inspection_function, _InspectionAdmission
    def make(context, params):
        function_check(fact)
        return admission_type(context, params, factory)
    return make


@dataclass(frozen=True, slots=True, eq=False)
class _InspectionTurnAdmission:
    context: Any
    turn: Any
    job: Any
    driver_proof: tuple
    inspection_context_proof: Any = None
    entry_guard: Any = None
    entry_proof: Any = None
    factory_proof: Any = None

    def __init__(self, context):
        turn = context.registry._scene_reservations.current_inspection(context)
        job = turn.owner.job
        record = context.jobs._inspection_record(job)
        proof, factory_proof = record[1], record[2]
        for name, value in (("context", context), ("turn", turn), ("job", job), ("driver_proof", proof),
                            ("inspection_context_proof", None), ("entry_guard", None), ("entry_proof", None), ("factory_proof", factory_proof)):
            object.__setattr__(self, name, value)

    def bind_checkpoint(self, _binding):
        self.turn.binding = _binding
        _inspection_bind(self)
        self.context.registry._scene_reservations.bind_inspection_proof(self.turn.token, _binding, self.entry_proof)

    def __call__(self):
        self.entry_guard()
        self.context.require(*self.turn.owner.authority.required_permissions)
        self.check_after_read()

    def check_after_read(self):
        self.entry_guard()
        self.driver_proof[6][0][1][0](self.job.driver, self.context)
        self.context.registry._scene_reservations.check_inspection_turn(self.turn.token)
        check_final_mutation(self.context, INSPECTION_TURN_METHOD)


@dataclass(slots=True, eq=False)
class InspectionJob:
    job_id: str
    request_id: str
    lifetime: Any
    deadline: float
    driver: Any
    authority: Any
    state_origin: tuple
    phase: str
    kind: str
    label: str
    method: str = INSPECTION_TURN_METHOD
    pending: Any = None
    reservation: Any = None
    revision: int = 1
    state: str = "QUEUED"
    cancel_reason: str = ""
    in_tick: bool = False
    in_commit: bool = False
    work: Any = None
    result: Any = None
    error: Any = None
    ready_valid: bool = False
    invalidated_reason: str = ""
    native_reads_started: bool = False
    progress: dict = field(default_factory=lambda: {"phase": "awaiting_start_delivery", "completed": 0, "total": 3})
    created_at: str = field(default_factory=utc_timestamp)

    def summary(self):
        return plain({"job_id": self.job_id, "kind": self.kind, "label": self.label, "request_id": self.request_id,
                      "state": self.state, "terminal": self.state in TERMINAL, "phase": self.phase,
                      "revision": self.revision, "progress": self.progress, "result": self.result, "error": self.error,
                      "inspection_only": True, "ready": self.state == "SUCCEEDED" and self.ready_valid,
                      "invalidated_reason": self.invalidated_reason, "logical_write_capability": False,
                      "native_reads_started": self.native_reads_started,
                      "physical_read_effects": {"ARRAY_COW_or_tagging_possible": self.native_reads_started,
                                                "image_buffer_cache_changes_possible": self.native_reads_started},
                      "undo_boundary_created": False, "undo_boundary_finalized": False, "checkpoint": {},
                      "created_at": self.created_at, "verification_required": True, "durable": False},
                     field="inspection_summary", byte_limit=262144, item_limit=16384, depth_limit=16)


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
        self._inspection_records: dict[int, tuple] = {}
        self._inspection_ready: dict[int, tuple] = {}
        self._turn_spec = registry.register(TURN_METHOD, self._advance, modifies=True, remote=False,
            batchable=False, record_history=False, automatic_checkpoint=False, exclusive_mutation=True,
            protected_scope_resolver=_storage_turn_scope,
            checkpoint_owns_finalization=True, checkpoint_admission_factory=lambda context, params: _TurnAdmission(context))
        self._inspection_spec = None
        self._inspection_spec_origin = ()

    def _ensure_inspection_spec(self):
        # Ordinary Runtime metadata stays unchanged. Only the sealed private
        # starter enables this local read entry, before its first provider.
        if self._inspection_spec is not None:
            if (self.registry.get(INSPECTION_TURN_METHOD) is not self._inspection_spec
                    or not self._inspection_spec_origin
                    or any(getattr(self._inspection_spec, name) is not value for name, value in self._inspection_spec_origin)):
                raise refused("INSPECTION_TURN_SPEC_CHANGED")
            return
        if INSPECTION_TURN_METHOD in self.registry._tools:
            raise refused("INSPECTION_TURN_SPEC_CHANGED")
        self._inspection_spec = self.registry.register(INSPECTION_TURN_METHOD, self._advance_inspection,
            modifies=False, remote=False, batchable=False, record_history=False, automatic_checkpoint=False,
            checkpoint_admission_factory=lambda context, params: _InspectionTurnAdmission(context))
        self._inspection_spec_origin = tuple((name, getattr(self._inspection_spec, name))
                                             for name in type(self._inspection_spec).__slots__)

    def _inspection(self, job, _type=type, _job_type=InspectionJob):
        return _type(job) is _job_type

    def _inspection_record(self, job, _type=type, _job_type=InspectionJob, _id=id, _get=dict.get, _tuple=tuple,
                           _dictionary=CooperativeJobController.__dict__["__dict__"].__get__):
        # The original native dictionary descriptor cannot invoke a substituted
        # service's Python attribute hook while locating its retained proof.
        data = _dictionary(self, _type(self))
        if _type(data) is not dict or any(_type(key) is not str for key in data):
            raise refused("INSPECTION_RECORD_LOST")
        records = _get(data, "_inspection_records")
        if _type(records) is not dict or any(_type(key) is not int for key in records):
            raise refused("INSPECTION_RECORD_LOST")
        record = _get(records, _id(job))
        if (_type(job) is not _job_type or _type(record) is not _tuple or len(record) != 7
                or record[0] is not job or _get(data, "active") is not job):
            raise refused("INSPECTION_RECORD_LOST")
        raw = ().__class__.__getitem__
        seal = raw(raw(record, 1), 4)
        function, code, namespace, defaults, keywords, closure = raw(seal, 7)
        native = raw(seal, 4)
        if (raw(native, 0)(function) is not raw(native, 4) or function.__code__ is not code
                or function.__globals__ is not namespace or function.__defaults__ is not defaults
                or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
            raise raw(native, 8)
        function(seal)
        return SceneJobs.__dict__["_inspection_record_fields"](self, job, record)

    def _inspection_record_fields(self, job, record, _type=type, _job_type=InspectionJob,
                                  _id=id, _get=dict.get, _tuple=tuple):
        """One callback-free record chain under a freshly verified source seal."""
        if (_type(job) is not _job_type or _type(record) is not _tuple or len(record) != 7 or record[0] is not job):
            raise refused("INSPECTION_RECORD_LOST")
        # Prove service/registry exact classes and method-shadow absence before
        # reading service fields or dispatching the original registry get().
        _inspection_context_factory_fields(record[2])
        service_row = next(row for row in record[2][8] if row[0] is self)
        data = service_row[2].__get__(self, service_row[1])
        records = _get(data, "_inspection_records")
        if (_type(records) is not dict or any(_type(key) is not int for key in records)
                or _get(data, "active") is not job or _get(records, _id(job)) is not record):
            raise refused("INSPECTION_RECORD_LOST")
        if (job.driver is not record[1][0]
                or any(getattr(job, name) is not value for name, value in record[3])):
            raise refused("INSPECTION_RECORD_LOST")
        registry = _get(data, "registry")
        registry_row = next(row for row in record[2][8] if row[0] is registry)
        registry_fields = registry_row[2].__get__(registry, registry_row[1])
        tools = _get(registry_fields, "_tools")
        if _type(tools) is not dict or any(_type(key) is not str for key in tools):
            raise refused("INSPECTION_TURN_SPEC_CHANGED")
        spec = _get(data, "_inspection_spec")
        if (_type(spec) is not ToolSpec or registry.get(INSPECTION_TURN_METHOD) is not spec
                or any(_inspection_slot(spec, ToolSpec, name) is not value
                       for name, value in _get(data, "_inspection_spec_origin"))):
            raise refused("INSPECTION_TURN_SPEC_CHANGED")
        _inspection_driver_fields(record[1])
        return record

    def start_inspection(self, context, params, *, time_limit=60.):
        self._main()
        if self.active is not None:
            raise refused("SCENE_JOB_BUSY")
        if type(time_limit) not in {int, float} or not 1. <= time_limit <= 300.:
            raise invalid_argument("Inspection time limit must be between 1 and 300 seconds.")
        binding = context.checkpoint_admission
        admission = None if binding is None else binding.callback
        if (type(admission) is not _InspectionAdmission or admission.context is not context
                or admission.params is not params or not binding.active):
            raise refused("INSPECTION_START_ADMISSION_REQUIRED")
        binding.check_after_read()
        driver = admission.driver
        job = InspectionJob("job_"+uuid.uuid4().hex, context.request_id,
            context.request_lifecycle or RequestLifetime.local(), time.monotonic()+time_limit,
            driver, admission.authority, admission.state_origin, phase_report(driver.phase),
            plain(driver.kind), plain(driver.label))
        origin = object()
        job.reservation = self.reservations.reserve(job, origin, allowlist=admission.allowlist, authority=admission.authority)
        try:
            anchors = tuple((name, getattr(job, name)) for name in ("job_id", "request_id", "lifetime", "deadline",
                "driver", "authority", "state_origin", "kind", "label", "method", "pending", "reservation"))
            import sys
            from threading import Event
            service_fields, _descriptor, _classes = _inspection_fields(self.reservations, type(self.reservations))
            connection = job.lifetime.connection
            event = None if connection is None else connection.background_active
            context_proof = admission.inspection_context_proof
            event_row = next((row for row in context_proof[10] if row[0] is event), None)
            retirement = (self.reservations, service_fields, self.reservations.owner, self.reservations._retained,
                vars(sys.modules[__package__ + ".scene_job_reservations"])["_services"], self.history,
                event, _storage_function_fact(Event.clear), _storage_function_fact(_inspection_error),
                refused("INSPECTION_RETIREMENT_ORIGIN_CHANGED"), event_row, _storage_function_fact(_inspection_event_data),
                deque.appendleft, _storage_function_fact(_inspection_ready_check))
            authority_rows = tuple((name, getattr(admission.authority, name)) for name in type(admission.authority).__slots__)
            ready_proof = (admission.driver_proof[4], admission.factory_proof, admission.authority, authority_rows,
                admission.state_origin, job.lifetime, context_proof[8], context_proof[9], context_proof[10], context_proof[11], job.deadline)
            if type(self.history) is not deque:
                raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
            self._inspection_records[id(job)] = (job, admission.driver_proof, admission.factory_proof, anchors,
                                                 retirement, ready_proof, job.deadline)
            self.active = job
            self.reservations.activate(job.reservation, origin)
        except BaseException:
            self.reservations.discard_unaccepted(job.reservation, origin)
            self._inspection_records.pop(id(job), None)
            if self.active is job:
                self.active = None
            raise
        if job.lifetime.connection is not None:
            job.lifetime.connection.background_active.set()
        return {"accepted": True, **job.summary(), "job_completed": False, "input_frozen_at_acceptance": True,
                "native_commit_interruptible": False}

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
        if self._inspection(job):
            record = self._inspection_record(job)
            factory = record[2][3]
            context = factory()
            self._inspection_record(job)
            runtime_fields = record[2][8][0][2].__get__(record[2][2], type(record[2][2]))
            if (context.jobs is not self or any(getattr(context, name) is not runtime_fields.get(name)
                    for name in ("registry", "state", "permissions", "checkpoints", "glb_stage"))):
                raise refused("INSPECTION_CONTEXT_FACTORY_CHANGED")
            bind_permissions(context, self.reservations)
            context.request_lifecycle, context.request_id = job.lifetime, job.request_id
            context.check_final_request = None
            context.check_cancelled = lambda: self._check(job, context)
            context.check_final_job = lambda: (_inspection_context_factory_check(record[2]),
                                                self.reservations.check_job(job.reservation))
            return context
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
        if self._inspection(job):
            self._inspection_record(job)
            self.reservations.check_job(job.reservation)
            if self.registry.get(INSPECTION_TURN_METHOD) is not self._inspection_spec:
                raise refused("INSPECTION_TURN_SPEC_CHANGED")
            return
        if not self._scene(job):
            return super()._check(job, context)
        self.reservations.check_job(job.reservation)
        if self.registry.get(TURN_METHOD) is not self._turn_spec:
            raise refused("SCENE_TURN_SPEC_CHANGED")

    def _tick_scope(self, job):
        return self.reservations.scheduler_scope(job.reservation) if self._inspection(job) or self._scene(job) else super()._tick_scope(job)

    def _guard_context_creation(self, job):
        return True if self._inspection(job) or self._scene(job) else super()._guard_context_creation(job)

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
        if self._inspection(job):
            self._check(job, context)
            record = self._inspection_record(job)
            token = self.reservations.issue_inspection_turn(job.reservation, job.phase, job.revision,
                                                           origin=control, check_only=True)
            previous = context.check_final_job
            context.check_final_job = lambda: (_inspection_context_factory_check(record[2]),
                                                self.reservations.check_inspection_turn(token))
            try:
                self.registry.invoke_inspection_turn(token, {}, context, check_only=True)
            finally:
                self.reservations.close_inspection_turn(token)
                context.check_final_job = previous
            return
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
        if self._inspection(job):
            self._check(job, context)
            return
        if not self._scene(job):
            return super()._prepare_step(job, context)
        self.reservations.check_job(job.reservation)

    def _budget_for(self, job):
        return 4. if self._inspection(job) or self._scene(job) else super()._budget_for(job)

    def _work_step_limit(self, job):
        return 1 if self._inspection(job) or self._scene(job) else super()._work_step_limit(job)

    def _make_work(self, job, context):
        if self._inspection(job):
            self._check(job, context)
            return object()
        if not self._scene(job):
            return super()._make_work(job, context)
        return object()  # No generator can retain a turn capability across yields.

    def _advance_work(self, job, context, control):
        if self._inspection(job):
            context = self._context(job)
            record = self._inspection_record(job)
            token = self.reservations.issue_inspection_turn(job.reservation, job.phase, job.revision, origin=control)
            context.check_final_job = lambda: (_inspection_context_factory_check(record[2]),
                                                self.reservations.check_inspection_turn(token))
            try:
                progress = self.registry.invoke_inspection_turn(token, {}, context)
            finally:
                self.reservations.close_inspection_turn(token)
            record = self._inspection_record(job)
            job.phase = phase_report(job.driver.phase)
            if job.driver.done:
                job.result = plain(job.driver.result, field="inspection_result")
                from .mesh_storage_contract import digest
                job.result["inspection_fingerprint"] = digest({"domain": job.result["inspection_fingerprint"],
                    "registry": id(self.registry), "state": id(job.state_origin[0]),
                    "connection": id(job.lifetime.connection), "protection_epoch": job.state_origin[2],
                    "source": record[1][4].fingerprint()})
                job.result.update(cached_at_completion=True, native_state_revalidated=False,
                                  permission_values_revalidated=False, write_authorized=False, writer_handoff_supported=False)
                raise StopIteration(job.result)
            return progress
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

    def _advance_inspection(self, context, params):
        turn = self.reservations.current_inspection(context)
        job = turn.owner.job
        record = self._inspection_record(job)
        if turn.check_only or turn.phase != job.driver.phase or job.driver.done:
            raise refused("INSPECTION_PHASE_SEQUENCE_CHANGED")
        admission = context.checkpoint_admission.callback
        if type(admission) is not _InspectionTurnAdmission:
            raise refused("INSPECTION_TURN_ADMISSION_REQUIRED")
        admission.check_after_read()
        admission_rows = tuple((name, getattr(admission, name)) for name in type(admission).__slots__)
        original_context = admission.inspection_context_proof
        advance = record[1][6][1][1][0]
        job.native_reads_started = True
        progress = advance(job.driver, context)
        # The exact held callback has returned after its last native guard.
        # Only this point can adopt the domain's committed cached state.
        _inspection_driver_check(record[1], instance=False)
        if (self._inspection_records.get(id(job)) is not record or self.active is not job
                or any(getattr(job, name) is not value for name, value in record[3])
                or any(getattr(admission, name) is not value for name, value in admission_rows)):
            raise refused("INSPECTION_ADMISSION_CHANGED")
        from .mesh_storage_source import verify_context
        verify_context(context, original_context)
        old_fields = dict(record[1][5])
        fields = record[1][3].__get__(job.driver, record[1][1])
        transitions = {
            "inspection_plan": ("inspection_capture", {"gate", "origin", "initial", "bindings", "excluded", "checkpoint_roles",
                "role_stamp", "metadata_stamp", "plan_stamp", "minimum_floor", "context_stamp", "phase"}),
            "inspection_capture": ("inspection_seal", {"protected_bytes", "role_stamp", "phase"}),
            "inspection_seal": ("inspection_complete", {"role_stamp", "result", "done", "phase"}),
        }
        expected, changed = transitions[turn.phase]
        if (len(fields) != len(old_fields) or fields.get("phase") != expected
                or any(name not in fields or (name not in changed and fields[name] is not value)
                       for name, value in old_fields.items())):
            raise refused("INSPECTION_PHASE_COMMIT_CHANGED")
        proof = _inspection_driver(job.driver)
        deadline = min(job.deadline, turn.inspection_deadline) if job.driver.done else record[6]
        self._inspection_records[id(job)] = (job, proof, record[2], record[3], record[4], record[5], deadline)
        object.__setattr__(admission, "driver_proof", proof)
        _inspection_bind(admission)
        self.reservations.bind_inspection_proof(turn.token, context.checkpoint_admission, admission.entry_proof)
        admission.check_after_read()
        if type(job.driver.done) is not bool:
            raise refused("INSPECTION_PHASE_SEQUENCE_CHANGED")
        phase_report(job.driver.phase)
        return progress_report(progress)

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

    def _complete_tick(self, job, context, value, control, _type=type, _inspection_kind=InspectionJob):
        if _type(job) is _inspection_kind:
            return self._finish(job, "SUCCEEDED", _origin=control)
        if not self._scene(job):
            return super()._complete_tick(job, context, value, control)
        self._finish(job, "SUCCEEDED", _origin=control)

    def _finish_tick(self, job, state, error, control, _type=type, _inspection_kind=InspectionJob):
        if _type(job) is _inspection_kind:
            return self._finish(job, state, error, _origin=control)
        if not self._scene(job):
            return super()._finish_tick(job, state, error, control)
        self._finish(job, state, error, _origin=control)

    def _finish(self, job, state, error=None, *, _origin=None, _type=type, _id=id, _object=object, _len=len,
                _tuple=tuple, _str=str, _bridge_error=BridgeError, _error_dict=BaseException.__dict__["__dict__"],
                _inspection_kind=InspectionJob, _get=dict.get):
        if _type(job) is _inspection_kind:
            if _type(job.state) is _str and job.state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                return
            if _origin is None:
                with self.reservations.scheduler_scope(job.reservation) as origin:
                    return self._finish(job, state, error, _origin=origin)
            record = _get(self._inspection_records, _id(job))
            if record is None or record[0] is not job:
                raise refused("INSPECTION_RECORD_LOST")
            (_service, service_fields, owner, retained, services, history, event, _clear_fact,
             error_fact, failure, event_row, event_reader_fact, append_history, ready_fact) = record[4]
            scheduler = service_fields.get("_scheduler")
            if (_type(scheduler) is not _tuple or scheduler[0] != _id(_origin) or scheduler[1] is not owner
                    or service_fields.get("owner") is not owner or owner.turn is not None):
                raise failure
            if state == "SUCCEEDED":
                try:
                    ready_check, code, namespace, defaults, keywords, _rows, cells = ready_fact
                    if (ready_check.__code__ is not code or ready_check.__globals__ is not namespace
                            or ready_check.__defaults__ is not defaults or ready_check.__kwdefaults__ is not keywords
                            or _len(ready_check.__closure__ or ()) != _len(cells)):
                        raise failure
                    ready_check((*record[5][:-1], record[6]))
                except _bridge_error as stopped:
                    state, error = "FAILED", stopped
            job.result = job.result if state == "SUCCEEDED" else None
            if error is not None:
                reader, code, namespace, defaults, keywords, _rows, cells = error_fact
                if (reader.__code__ is code and reader.__globals__ is namespace and reader.__defaults__ is defaults
                        and reader.__kwdefaults__ is keywords and _len(reader.__closure__ or ()) == _len(cells)):
                    job.error = reader(error)
                else:
                    job.error = {"code": _error_dict.__get__(error, _type(error)).get("code"), "message": "Inspection stopped.",
                                 "context": {"inspection_status": "INCOMPLETE", "error_context_unknown": True}}
                job.error["context"].update(native_reads_started=job.native_reads_started,
                    physical_read_effects={"ARRAY_COW_or_tagging_possible": job.native_reads_started,
                                           "image_buffer_cache_changes_possible": job.native_reads_started})
            job.state, job.progress = state, {"phase": state.lower(), "completed": 3 if state == "SUCCEEDED" else 0, "total": 3}
            job.ready_valid = state == "SUCCEEDED"
            if job.ready_valid:
                self._inspection_ready[_id(job)] = record[5]
            retained.pop(_id(job.reservation), None)
            services.pop(_id(job.reservation), None)
            service_fields["owner"] = None
            job.revision += 1
            job.work = job.driver = None
            self._inspection_records.pop(_id(job), None)
            event_reader, reader_code, _namespace, reader_defaults, _keywords, _rows, _cells = event_reader_fact
            event_data = None
            if event is not None and event_reader.__code__ is reader_code and event_reader.__defaults__ is reader_defaults:
                event_data = event_reader(event_row)
            if event_data is not None:
                # background_active is a cached tracking bit. A literal native
                # dict write avoids stopped Event/Condition callbacks entirely.
                event_data["_flag"] = False
            elif event is not None and job.error is not None:
                job.error["context"]["lifetime_cleanup_unknown"] = True
            self.history = history
            append_history(history, job)
            retained_ids = {_id(item) for item in history}
            for identifier in _tuple(self._inspection_ready):
                if identifier not in retained_ids:
                    self._inspection_ready.pop(identifier, None)
            if self.active is job:
                self.active = None
            return
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
        for job in self.history:
            if type(job) is InspectionJob and job.job_id == job_id:
                self._refresh_inspection_ready(job)
        try:
            return super().inspect(job_id)
        except BridgeError as error:
            if error.code != ErrorCode.INVALID_ARGUMENT.value or job_id not in self.recovery_ledger:
                raise
            return plain({**self.recovery_ledger[job_id]["summary"], "terminal_history_evicted": True,
                    "recovery_receipt_retained": True}, field="summary", byte_limit=262144,
                    item_limit=16384, depth_limit=16)

    def list(self, limit=10):
        for job in self.history:
            if type(job) is InspectionJob:
                self._refresh_inspection_ready(job)
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

    def _refresh_inspection_ready(self, job):
        if not job.ready_valid:
            return
        proof = self._inspection_ready.get(id(job))
        try:
            if proof is None:
                raise refused("INSPECTION_READY_RECORD_LOST")
            # Bootstrap the held seal before any replaceable pure helper.
            raw = ().__class__.__getitem__
            seal = raw(proof, 0)
            function, code, namespace, defaults, keywords, closure = raw(seal, 7)
            native = raw(seal, 4)
            if (raw(native, 0)(function) is not raw(native, 4) or function.__code__ is not code or function.__globals__ is not namespace
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
                raise raw(native, 8)
            function(seal)
            _inspection_ready_check(proof)
        except Exception:
            job.ready_valid = False
            job.invalidated_reason = "cached inspection ownership/source proof changed"
            job.result = None
            self._inspection_ready.pop(id(job), None)

    def cancel_all(self, reason):
        for job in self.history:
            if type(job) is InspectionJob:
                job.ready_valid = False
                job.invalidated_reason = reason
                job.result = None
        self._inspection_ready.clear()
        self.reservations.invalidate(reason)
        super().cancel_all(reason)


def _inspection_record_union_fields(self, job, record, factory_check, driver_check, _type=type, _job_type=InspectionJob,
                              _id=id, _get=dict.get, _tuple=tuple):
    """One callback-free record chain under a freshly verified source seal."""
    if (_type(job) is not _job_type or _type(record) is not _tuple or len(record) != 7 or record[0] is not job):
        raise refused("INSPECTION_RECORD_LOST")
    # Prove service/registry exact classes and method-shadow absence before
    # reading service fields or dispatching the original registry get().
    factory_check()
    service_row = next(row for row in record[2][8] if row[0] is self)
    data = service_row[2].__get__(self, service_row[1])
    records = _get(data, "_inspection_records")
    if (_type(records) is not dict or any(_type(key) is not int for key in records)
            or _get(data, "active") is not job or _get(records, _id(job)) is not record):
        raise refused("INSPECTION_RECORD_LOST")
    if (job.driver is not record[1][0]
            or any(getattr(job, name) is not value for name, value in record[3])):
        raise refused("INSPECTION_RECORD_LOST")
    registry = _get(data, "registry")
    registry_row = next(row for row in record[2][8] if row[0] is registry)
    registry_fields = registry_row[2].__get__(registry, registry_row[1])
    tools = _get(registry_fields, "_tools")
    if _type(tools) is not dict or any(_type(key) is not str for key in tools):
        raise refused("INSPECTION_TURN_SPEC_CHANGED")
    spec = _get(data, "_inspection_spec")
    if (_type(spec) is not ToolSpec or registry.get(INSPECTION_TURN_METHOD) is not spec
            or any(_inspection_slot(spec, ToolSpec, name) is not value
                   for name, value in _get(data, "_inspection_spec_origin"))):
        raise refused("INSPECTION_TURN_SPEC_CHANGED")
    driver_check()
    return record
