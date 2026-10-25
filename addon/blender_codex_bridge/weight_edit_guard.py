"""Retained direct-weight intent and measured field-only recovery.

The portable boundary is independent of Blender. Native admission requires its
separately reviewed ordinary-call window; models do not qualify a native reader.
"""

from __future__ import annotations

import dis
import hashlib
import json
import math
import struct
import sys
import threading
from dataclasses import dataclass, replace
from enum import Enum
from types import CodeType, FunctionType, MethodDescriptorType, ModuleType, WrapperDescriptorType
from typing import Any, ClassVar
from weakref import ref

from . import native_save_policy as _save_policy
from . import permissions as _permissions
from . import runtime as _runtime
from . import weight_edit_plan as intent
from .errors import BridgeError, ErrorCode
from .permissions import Permission
from .tool_registry import _checkpoint_parameters, check_final_mutation

# Loaded with the registration module, before any request provider. These are
# function/code identities, not a caller-set admission flag or function name.
_RUNTIME_CLASS = _runtime.BridgeRuntime
_PREFERENCES = _runtime._preferences
_PREFERENCES_CODE = _PREFERENCES.__code__
_PERMISSION_SNAPSHOT = _runtime.permission_snapshot
_PERMISSION_SNAPSHOT_CODE = _PERMISSION_SNAPSHOT.__code__
# Runtime must initialize before this source module: its jobs import depends on
# the canonical runtime definitions. Pin the actual loaded jobs module afterward.
_save_jobs = sys.modules[__package__ + ".native_save_jobs"]
_NATIVE_SAVE_JOBS = _save_jobs.NativeSaveJobs
_CONSTRUCTOR_CODE = _RUNTIME_CLASS.__init__.__code__
_PROVIDER_CODE, = (code for code in _CONSTRUCTOR_CODE.co_consts
                  if type(code) is CodeType and code.co_names == ("permission_snapshot", "_preferences")
                  and code.co_name == "<lambda>" and not code.co_freevars)
_MISSING = object()
_PURE_TYPE, _PURE_VARS, _PURE_LEN, _PURE_ANY, _PURE_ALL, _PURE_ZIP, _PURE_OBJECT = type, vars, len, any, all, zip, object
_PURE_TYPE_NAMESPACE = type.__dict__["__dict__"]
_PURE_NAMESPACE = globals()
_LOCAL_NAMESPACE_ORIGIN = _PURE_NAMESPACE
_PURE_BUILTINS = __builtins__ if type(__builtins__) is dict else vars(__builtins__)
_PURE_BUILTIN_FACTS = tuple((name, _PURE_BUILTINS[name]) for name in (
    "type", "vars", "len", "any", "all", "zip", "object", "__import__"))
_ORIGIN_ERROR = BridgeError
_PURE_ALIASES = tuple((name, _PURE_NAMESPACE[name]) for name in (
    "_PURE_TYPE", "_PURE_VARS", "_PURE_LEN", "_PURE_ANY", "_PURE_ALL", "_PURE_ZIP", "_PURE_OBJECT",
    "_PURE_TYPE_NAMESPACE", "_ORIGIN_ERROR"))


def _global_names(code):
    names = {instruction.argval for instruction in dis.get_instructions(code)
             if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}}
    for child in code.co_consts:
        if type(child) is CodeType:
            names.update(_global_names(child))
    return tuple(sorted(names))


def _function_fact(function):
    """Retain exact executable dependencies without running their callbacks."""
    namespace, builtins = function.__globals__, function.__builtins__
    bindings = tuple((name, name in namespace, namespace.get(name, builtins.get(name, _MISSING)))
                     for name in _global_names(function.__code__))
    return (function, function.__code__, namespace, builtins, function.__defaults__,
            function.__kwdefaults__, tuple((function.__kwdefaults__ or {}).items()),
            function.__closure__, tuple((cell, cell.cell_contents) for cell in function.__closure__ or ()), bindings,
            builtins.get("__import__", _MISSING), namespace.get("__builtins__", _MISSING))


def _function_intact(fact):
    function, code, namespace, builtins, defaults, kwdefaults, keywords, closure, cells, bindings, importer, alias = fact
    if (_PURE_TYPE(function) is not FunctionType or function.__code__ is not code
            or function.__globals__ is not namespace or function.__builtins__ is not builtins
            or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
            or function.__closure__ is not closure or builtins.get("__import__", _MISSING) is not importer
            or namespace.get("__builtins__", _MISSING) is not alias):
        return False
    if kwdefaults is not None and (_PURE_TYPE(kwdefaults) is not dict or _PURE_LEN(kwdefaults) != _PURE_LEN(keywords)
            or _PURE_ANY(key not in kwdefaults or kwdefaults[key] is not value for key, value in keywords)):
        return False
    if _PURE_ANY(cell.cell_contents is not value for cell, value in cells):
        return False
    return _PURE_ALL((name in namespace) is present
               and namespace.get(name, builtins.get(name, _MISSING)) is value
               for name, present, value in bindings)


_GRANT_CLASS = _save_policy.NativeSaveGrant
_STATEMENT_CLASS = _save_policy.GrantStatement
_GRANT_PROPERTY = _PURE_VARS(_GRANT_CLASS)["generation"]
_ENUM_VALUE_PROPERTY = _PURE_VARS(Enum)["value"]
_ENUM_VALUE_ITEMS = tuple(_PURE_VARS(_ENUM_VALUE_PROPERTY).items())
_GRAPH_CLASSES = (_RUNTIME_CLASS, _permissions.PermissionManager, _permissions.Permission,
                  Enum, _PURE_TYPE(_permissions.Permission), *_PURE_TYPE(_ENUM_VALUE_PROPERTY).__mro__[:-1],
                  _GRANT_CLASS, _STATEMENT_CLASS, *_NATIVE_SAVE_JOBS.__mro__[:-1])
_CLASS_FACTS = tuple((cls, tuple(_PURE_VARS(cls).items())) for cls in _GRAPH_CLASSES)
_GRAPH_FUNCTIONS = (
    _RUNTIME_CLASS.__init__, _PREFERENCES, _PERMISSION_SNAPSHOT,
    _runtime.native_save_permission_provider_intact, _permissions.permission_snapshot,
    _STATEMENT_CLASS.__init__, _GRANT_PROPERTY.fget,
    *(getattr(_GRANT_CLASS, name) for name in ("__init__", "__setattr__", "_main", "_now", "arm", "revoke",
                                             "active", "statement", "check", "status")),
    _save_policy.threading.current_thread, _save_policy.threading.main_thread,
    _ENUM_VALUE_PROPERTY.fget, _PURE_TYPE(_ENUM_VALUE_PROPERTY).__get__, _PURE_TYPE(_permissions.Permission).__iter__,
)
_FUNCTION_FACTS = tuple(_function_fact(function) for function in _GRAPH_FUNCTIONS)
_RUNTIME_PINS = tuple((name, _PURE_VARS(_runtime)[name]) for name in (
    "_BASE_PERMISSION_SNAPSHOT", "_BASE_PERMISSION_SNAPSHOT_CODE", "_NATIVE_SAVE_GRANT_CLASS",
    "_NATIVE_SAVE_STATEMENT_CLASS", "_GRANT_STATEMENT_INIT_CODE", "_NATIVE_SAVE_POLICY_VERSION", "_GRANT_HELPERS",
    "_GRANT_GENERATION_PROPERTY", "_GRANT_GENERATION_GETTER_CODE", "_CANONICAL_RUNTIME_CLASS",
    "_RUNTIME_CONSTRUCTOR_CODE", "_PERMISSION_PROVIDER_CODE", "_PREFERENCES_FUNCTION", "_PREFERENCES_CODE",
    "_PERMISSION_MANAGER_CLASS", "_PERMISSION_SNAPSHOT_FUNCTION", "_PERMISSION_SNAPSHOT_CODE",
    "_PERMISSION_PROVIDER_GUARD", "_PERMISSION_PROVIDER_GUARD_CODE", "NativeSaveJobs", "NativeSaveGrant",
    "GrantStatement", "POLICY_VERSION", "_native_save_policy_module", "_base_permission_snapshot", "Permission"))
_MODULE_PINS = tuple((module, name, _PURE_VARS(module)[name]) for module, names in (
    (_save_policy, ("NativeSaveGrant", "GrantStatement", "POLICY_VERSION", "math", "time", "threading")),
    (_permissions, ("Permission", "PermissionManager", "permission_snapshot", "PREFERENCE_PROPERTIES")),
    (_save_jobs, ("NativeSaveJobs",)),
    (_save_policy.math, ("ceil", "isfinite")),
    (_save_policy.time, ("monotonic",)),
    (_save_policy.threading, ("current_thread", "main_thread", "get_ident")),
) for name in names)
_PREFERENCE_MAP = _permissions.PREFERENCE_PROPERTIES
_PREFERENCE_ITEMS = tuple(_PREFERENCE_MAP.items())
_ENUM_NAMES = _permissions.Permission._member_names_
_ENUM_NAME_ITEMS = tuple(_ENUM_NAMES)
_ENUM_MAPS = tuple((mapping, tuple(mapping.items())) for mapping in (
    _permissions.Permission._member_map_, _permissions.Permission._value2member_map_))
_PERMISSION_MEMBERS = tuple((member, _PURE_VARS(member)["_name_"], _PURE_VARS(member)["_value_"])
                            for member in _permissions.Permission)
_H01_TOKEN = object()


def _mapping_intact(mapping, items):
    return _PURE_TYPE(mapping) is dict and _PURE_LEN(mapping) == _PURE_LEN(items) and _PURE_ALL(
        key is expected_key and value is expected_value
        for (key, value), (expected_key, expected_value) in _PURE_ZIP(mapping.items(), items, strict=True))


def _h01_origin(active):
    """Independent closed comparison, before any provider or native getter.

    The native save grant's volatile statement/epoch/expiry do not confer ordinary
    edit authority. This is a canonical-source fence, not a hostile Python sandbox.
    """
    if _PURE_TYPE(_runtime) is not ModuleType or _PURE_ANY(_PURE_TYPE(module) is not ModuleType for module, _name, _value in _MODULE_PINS):
        raise _error("Canonical weight permission modules changed.")
    for cls, attributes in _CLASS_FACTS:
        current = _PURE_TYPE_NAMESPACE.__get__(cls, _PURE_TYPE(cls))
        if _PURE_LEN(current) != _PURE_LEN(attributes) or _PURE_ANY(current.get(name, _MISSING) is not value
                                                 for name, value in attributes):
            raise _error("Canonical weight permission dependency class changed.")
    if (_PURE_ANY(not _function_intact(fact) for fact in _FUNCTION_FACTS)
            or _PURE_ANY(_PURE_VARS(_runtime).get(name, _MISSING) is not value for name, value in _RUNTIME_PINS)
            or _PURE_ANY(_PURE_VARS(module).get(name, _MISSING) is not value for module, name, value in _MODULE_PINS)
            or _RUNTIME_CLASS.__init__.__code__ is not _CONSTRUCTOR_CODE
            or not _mapping_intact(_PREFERENCE_MAP, _PREFERENCE_ITEMS)
            or _PURE_LEN(_ENUM_NAMES) != _PURE_LEN(_ENUM_NAME_ITEMS)
            or _PURE_ANY(name is not expected for name, expected in _PURE_ZIP(_ENUM_NAMES, _ENUM_NAME_ITEMS, strict=True))
            or _PURE_ANY(not _mapping_intact(mapping, items) for mapping, items in _ENUM_MAPS)
            or not _mapping_intact(_PURE_VARS(_ENUM_VALUE_PROPERTY), _ENUM_VALUE_ITEMS)
            or _PURE_ANY(_PURE_VARS(member).get("_name_") is not name or _PURE_VARS(member).get("_value_") is not value
                   for member, name, value in _PERMISSION_MEMBERS)):
        raise _error("Canonical weight permission dependency graph changed.")
    if _PURE_TYPE(active) is not _RUNTIME_CLASS or _PURE_TYPE(_PURE_VARS(active).get("_registered")) is not bool:
        raise _error("Canonical weight runtime ownership changed.", native_profile_qualified=False, origin_supported=False)
    grant = _PURE_VARS(active).get("native_save_policy")
    if (_PURE_TYPE(grant) is not _GRANT_CLASS or grant is not _PURE_VARS(active).get("_native_save_policy_origin")
            or _PURE_TYPE(_PURE_VARS(active).get("jobs")) is not _NATIVE_SAVE_JOBS
            or _PURE_VARS(active.jobs).get("native_save_policy") is not grant
            or _PURE_TYPE(_PURE_VARS(active).get("_native_save_local_authority")) is not object
            or _PURE_OBJECT.__getattribute__(grant, "_authority") is not _PURE_VARS(active)["_native_save_local_authority"]
            or _PURE_OBJECT.__getattribute__(grant, "_generation") is not _PURE_VARS(active).get("_native_save_generation")
            or _PURE_TYPE(_PURE_OBJECT.__getattribute__(grant, "_generation")) is not str
            or _PURE_TYPE(_PURE_OBJECT.__getattribute__(grant, "_thread")) is not int
            or _PURE_OBJECT.__getattribute__(grant, "_thread") != _save_policy.threading.get_ident()):
        raise _error("Canonical weight native-save grant ownership changed.")
    return (_H01_TOKEN, grant, _PURE_OBJECT.__getattribute__(grant, "_authority"),
            _PURE_OBJECT.__getattribute__(grant, "_generation"), _PURE_OBJECT.__getattribute__(grant, "_thread"))

METHODS = frozenset({"weights.assign", "weights.normalize"})
_CAPTURES: dict[int, list[Any]] = {}


def _error(message: str, **context: Any) -> BridgeError:
    # The refusal itself must not invoke a substituted Enum.value getter.
    return BridgeError("NOT_IMPLEMENTED", message, context)


# The entry authenticates these functions inline, before calling any comparator.
# Retaining function objects alone would miss an in-place __code__ substitution.
_LOCAL_FACTS = tuple((name, _function_fact(_PURE_NAMESPACE[name])) for name in (
    "_h01_origin", "_function_intact", "_mapping_intact", "_error"))


@dataclass(frozen=True, slots=True)
class NativeState:
    """Complete admitted authored projection; native purity is not implied."""

    preservation: tuple[Any, ...]
    memberships: intent.MembershipSnapshot
    checkpoint_markers: tuple[Any, ...] | None = None


def _plain(value: Any, remaining: list[int]) -> Any:
    remaining[0] -= 1
    if remaining[0] < 0:
        raise _error("Weight evidence exceeds its retained scalar budget.")
    if value is None or type(value) in {str, bool, int}:
        if type(value) is str and len(value.encode("utf-8")) > 4096:
            raise _error("Weight evidence contains an over-budget string.")
        if type(value) is int and value.bit_length() > 4096:
            raise _error("Weight evidence contains an over-budget integer.")
        return value
    if type(value) is float and math.isfinite(value):
        return ("float64", struct.pack("<d", value).hex())
    if type(value) is tuple:
        return tuple(_plain(item, remaining) for item in value)
    raise _error("Weight evidence must contain immutable plain values.")


def _projection(state: NativeState, *, markers: bool = True) -> tuple[Any, ...]:
    if type(state) is not NativeState or type(state.preservation) is not tuple:
        raise _error("Weight reader returned an unsupported authored projection.")
    intent.validate_snapshot(state.memberships)
    groups = tuple((g.index, g.name, g.pointer, g.locked) for g in state.memberships.groups)
    return (state.preservation, groups, state.memberships.memberships,
            state.checkpoint_markers if markers else None)


def _state_data(state: NativeState, *, markers: bool = True) -> tuple[Any, int]:
    remaining = [intent.MAX_SNAPSHOT_VALUES]
    value = _plain(_projection(state, markers=markers), remaining)
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if len(raw) > intent.MAX_SNAPSHOT_BYTES:
        raise _error("Weight evidence exceeds its retained byte budget.")
    return value, intent.MAX_SNAPSHOT_VALUES - remaining[0]


def _digest(state: NativeState) -> str:
    # Canonically observed core marker writes are bookkeeping, not weight fields.
    value, _ = _state_data(state, markers=False)
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode("ascii")).hexdigest()


def _hooks(reader: Any) -> tuple[Any, ...]:
    return tuple(vars(type(reader)).get(name) for name in ("snapshot", "resolve"))


class WeightEditGuard:
    """One pre-provider factory, immutable plan and exact known write prefix."""

    def __init__(self, method: str, context: Any, params: Any):
        self.context, self.method, self.params = context, method, params
        self.parameters = _checkpoint_parameters(params)
        if method not in METHODS or type(params) is not dict:
            raise _error("Direct weight editing requires its exact supported request.")
        try:
            intent.validate_request(method, params)
        except intent.WeightPlanError as cause:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, str(cause)) from cause
        self.registry, self.spec = context.registry, context.registry.get(method)
        self.services = tuple((name, getattr(context, name, None)) for name in (
            "state", "permissions", "checkpoints", "request_lifecycle", "check_final_request",
            "check_final_job", "check_cancelled"))
        self.reader = _NativeReader(context, params)
        self._reader, self._reader_type = self.reader, type(self.reader)
        self._hooks = _hooks(self.reader)
        self.before = self.reader.snapshot()
        _, self._snapshot_cost = _state_data(self.before)
        try:
            self.plan = intent.plan_edit(self.before.memberships, method, params)
            _, expected_cost = _state_data(replace(self.before, memberships=self.plan.expected))
            self._snapshot_cost = max(self._snapshot_cost, expected_cost)
            markers = self.before.checkpoint_markers
            marker_count = 0 if markers is None else len(markers[1])
            intent.comparison_budget(self._snapshot_cost, len(self.plan.writes), marker_count)
        except (intent.WeightPlanError, IndexError, TypeError) as cause:
            raise _error(str(cause)) from cause
        self._before, self._plan = self.before, self.plan
        self.expected = self.before
        self._expected_identity = self.expected
        self._comparison_work = self._snapshot_cost
        self.binding = self._binding = None
        self._journal: tuple[intent.WeightWrite, ...] = ()
        self._journal_identity = self._journal
        self.stopped: BridgeError | None = None
        self.refusal: str | None = None
        self.consumed = False
        self.stage = "PREPARED"
        self.known, self.observed = True, self.before
        self.attempts = self.verified = self.restore_attempts = self.restored = 0

    def bind_checkpoint(self, binding: Any) -> Any:
        if (self.binding is not None or binding.context is not self.context
                or binding.callback is not self or binding.method != self.method
                or binding.params is not self.params):
            raise _error("Weight proof cannot bind a different registered call.")
        self.binding = self._binding = binding

        def release() -> None:
            captures = _CAPTURES.get(id(self.context), [])
            captures[:] = [item for item in captures if item() is not None and item() is not self]
            if not captures:
                _CAPTURES.pop(id(self.context), None)
        return release

    def _stop(self, error: Exception, reason: str) -> BridgeError:
        if self.stopped is None:
            self.stopped = error if isinstance(error, BridgeError) else _error(
                "Weight native state or authority could not be verified.")
            self.refusal = reason
        self.known, self.observed = False, None
        return self.stopped

    def _identity(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        if (self.context.registry is not self.registry or self.registry.get(self.method) is not self.spec
                or _checkpoint_parameters(self.params) != self.parameters
                or any(getattr(self.context, key, None) is not value for key, value in self.services)
                or self.before is not self._before or self.plan is not self._plan
                or self.expected is not self._expected_identity or self.reader is not self._reader
                or type(self.reader) is not self._reader_type or _hooks(self.reader) != self._hooks
                or self.binding is not self._binding or self._journal is not self._journal_identity):
            raise self._stop(_error("Weight original call, plan, reader or services changed."), "AUTHORITY_LOST")
        if self.binding is None:
            raise self._stop(_error("Weight writer has no original factory binding."), "AUTHORITY_LOST")
        self.binding.check_identity(self.method)

    def _final(self) -> None:
        try:
            self._identity()
            check_final_mutation(self.context, self.method, expected_spec=self.spec)
        except Exception as cause:
            raise self._stop(cause, "AUTHORITY_LOST") from cause

    def _live(self) -> None:
        try:
            self._identity()
            self.context.require(Permission.EDIT_MESH)
            if self.context.check_cancelled is not None:
                self.context.check_cancelled()
            self.context.require(Permission.EDIT_MESH)
            self._final()
        except Exception as cause:
            raise self._stop(cause, "AUTHORITY_LOST") from cause

    def _read(self) -> NativeState:
        self._final()
        try:
            if self._comparison_work + intent.MAX_SNAPSHOT_VALUES > intent.MAX_COMPARE_VALUES:
                raise _error("Weight comparison and recovery reserve is exhausted.")
            state = self.reader.snapshot()
            _, cost = _state_data(state)
            self._comparison_work += cost
        except Exception as cause:
            raise self._stop(cause, "INVALID_NATIVE_SCOPE") from cause
        self._final()
        return state

    def _compare(self) -> None:
        state = self._read()
        if _state_data(state)[0] != _state_data(self.expected)[0]:
            raise self._stop(_error("Weight supported authored state changed outside its owned prefix."), "STATE_CHANGED")
        self.known, self.observed = True, state
        self._final()

    def __call__(self) -> None:
        self._live()
        self._compare()

    def check_after_read(self) -> None:
        self._identity()
        self._compare()

    def after_marker_write(self, event: Any) -> None:
        from .checkpoint_completion import claim_marker_write_completion
        markers = claim_marker_write_completion(self.context, self.method, self, event)
        self._identity()
        if self.expected.checkpoint_markers is None or type(markers) is not tuple:
            raise self._stop(_error("Weight checkpoint has no original marker witness."), "AUTHORITY_LOST")
        self.expected = replace(self.expected, checkpoint_markers=markers)
        self._expected_identity = self.expected

    def after_native_push(self) -> None:
        from .checkpoint_completion import claim_native_push_completion
        claim_native_push_completion(self.context, self.method, self)
        self._compare()

    def _member(self, write: intent.WeightWrite, *, restoring: bool = False) -> None:
        self._identity()
        if write not in self._plan.writes or (restoring and write not in self._journal):
            raise self._stop(_error("Weight field lost its original planned ownership."), "AUTHORITY_LOST")
        if not restoring:
            remaining = len(self.plan.writes) - self.attempts
            required = 3 * remaining + 3 * (len(self._journal) + remaining) + 12
            if (self._comparison_work + self._snapshot_cost * required
                    + intent.MAX_SNAPSHOT_VALUES > intent.MAX_COMPARE_VALUES):
                # Earlier known writes may still use their reserved compensation.
                raise _error("Weight forward work would consume its retained recovery reserve.")
        self()
        before = self.expected
        value = write.before if restoring else write.after
        after = replace(before, memberships=intent.replace_member(
            before.memberships, write.vertex, write.group.index, value))
        leaf = None
        failure = None
        try:
            self._comparison_work += self._snapshot_cost
            if self._comparison_work + intent.MAX_SNAPSHOT_VALUES > intent.MAX_COMPARE_VALUES:
                raise _error("Weight closed-leaf comparison budget is exhausted.")
            # Reader finishes complete CAS before acquiring its genuine native method.
            leaf = self.reader.resolve(write.vertex, write.group, before, value)
            self._final()
            self.stage = "RESTORE" if restoring else "FIELD_WRITE"
            if restoring:
                self.restore_attempts += 1
            else:
                self.attempts += 1
            try:
                leaf()
            except Exception as cause:
                failure = cause
        except Exception as cause:
            raise self._stop(cause, "INVALID_NATIVE_SCOPE") from cause
        finally:
            leaf = None
        state = self._read()
        actual = _state_data(state)[0]
        if actual == _state_data(after)[0]:
            self.expected = after
            self._expected_identity = self.expected
            if restoring:
                self.restored += 1
            else:
                self.verified += 1
                self._journal = (*self._journal, write)
                self._journal_identity = self._journal
        elif actual != _state_data(before)[0]:
            raise self._stop(_error("Weight setter left an unknown or unowned state."), "UNKNOWN_WRITE_RESULT")
        self.known, self.observed = True, state
        if failure is not None:
            raise failure
        if actual != _state_data(after)[0]:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Weight setter did not store its predicted result.")

    def _recover(self) -> bool:
        if self.stopped is not None or not self.known:
            return False
        try:
            for write in reversed(self._journal):
                self._member(write, restoring=True)
            self()
            return self.expected == replace(self.before, checkpoint_markers=self.expected.checkpoint_markers)
        except Exception:
            return False

    def evidence(self, *, success: bool, rollback: bool) -> dict[str, Any]:
        return {"kind": "weight_mutation", "method": self.method, "object_name": self.plan.object_name,
                "stage": "COMPLETE" if success else "FAILED", "execution_started": bool(self.attempts),
                "possible_mutation": not success and bool(self.attempts) and not rollback,
                "rollback_verified": rollback, "verification_required": not success,
                "state_known": self.known, "retained_partial": not success and bool(self.attempts) and not rollback,
                "owned_membership_attempts": self.attempts, "owned_membership_verified": self.verified,
                "restoration_attempts": self.restore_attempts, "restored_memberships": self.restored,
                "native_update_attempts": 0, "native_update_verified": 0,
                "restoration_refused": self.refusal, "before_sha256": _digest(self.before),
                "expected_sha256": _digest(self.expected),
                "observed_sha256": _digest(self.observed) if self.known and self.observed is not None else None}

    def execute(self) -> dict[str, Any]:
        self._identity()
        if self.consumed:
            raise _error("The original weight intent has already been consumed.")
        self.consumed = True
        try:
            self()
            for write in self.plan.writes:
                self._member(write)
            self()
        except Exception as cause:
            rollback = self._recover()
            evidence = self.evidence(success=False, rollback=rollback)
            raise BridgeError(cause.code if isinstance(cause, BridgeError) else ErrorCode.OPERATION_FAILED,
                              "Direct weight edit failed; reinspect before continuing.",
                              {"object": self.plan.object_name, "affected_objects": [self.plan.object_name],
                               "execution_started": bool(self.attempts), "verification_required": True,
                               "possible_mutation": evidence["possible_mutation"], "rollback_verified": rollback,
                               "recovery_evidence": evidence}) from cause
        vertices = []
        groups = {group.index: group.name for group in self.expected.memberships.groups}
        for index in sorted(self.plan.vertex_indices)[:128]:
            vertices.append({"vertex_index": index, "weights": {
                groups[group]: intent.f32_value(bits)
                for group, bits in self.expected.memberships.memberships[index]}})
        return {"object": self.plan.object_name, "affected_objects": [self.plan.object_name],
                "updated_memberships": self.plan.requested_memberships, "vertices": vertices,
                "truncated": len(self.plan.vertex_indices) > 128, "changed": bool(self.plan.writes),
                "complete_membership_readback_verified": True, "explicit_update_calls": 0,
                "recovery_evidence": self.evidence(success=True, rollback=False)}


def factory(method: str, context: Any, params: Any) -> WeightEditGuard:
    guard = WeightEditGuard(method, context, params)
    _CAPTURES.setdefault(id(context), []).append(ref(guard))
    return guard


def current(context: Any, method: str, params: Any) -> WeightEditGuard:
    binding = getattr(context, "checkpoint_admission", None)
    guard = getattr(binding, "callback", None)
    captures = [item() for item in _CAPTURES.get(id(context), ()) if item() is not None]
    if (type(guard) is not WeightEditGuard or not any(guard is item for item in captures)
            or guard.context is not context or guard.method != method or guard.params is not params
            or guard.binding is not binding):
        raise _error("Direct weights require their original registered factory; recapture is forbidden.")
    guard._identity()
    return guard


class _NativeLeaf:
    """Preallocated builtin argument tuple; clear native method on every exit."""

    __slots__ = ("arguments", "method")

    def __init__(self, arguments):
        self.arguments, self.method = arguments, None

    def __call__(self):
        method = self.method
        try:
            return method(*self.arguments)
        finally:
            self.method = method = None


class _NativeReader:
    """Bounded ordinary stock call window; not a hostile-Python identity proof."""

    BUILDS: ClassVar = {(4, 5, 14): b"62c1db4208e8", (5, 2, 2): b"d13f752e3b9c"}
    OBJECT_FIELDS: ClassVar = {
        "name": ("STRING", None), "type": ("ENUM", None), "mode": ("ENUM", None),
        "data": ("POINTER", None), "library": ("POINTER", None), "override_library": ("POINTER", None),
        "is_editable": ("BOOLEAN", 0), "animation_data": ("POINTER", None),
        "parent": ("POINTER", None),
        "modifiers": ("COLLECTION", None), "constraints": ("COLLECTION", None),
        "instance_type": ("ENUM", None), "vertex_groups": ("COLLECTION", None),
        "location": ("FLOAT", 3), "rotation_mode": ("ENUM", None),
        "rotation_euler": ("FLOAT", 3), "rotation_quaternion": ("FLOAT", 4),
        "rotation_axis_angle": ("FLOAT", 4), "scale": ("FLOAT", 3),
        "delta_location": ("FLOAT", 3), "delta_rotation_euler": ("FLOAT", 3),
        "delta_rotation_quaternion": ("FLOAT", 4), "delta_scale": ("FLOAT", 3),
        "hide_viewport": ("BOOLEAN", 0), "hide_render": ("BOOLEAN", 0), "hide_select": ("BOOLEAN", 0),
    }
    MESH_FIELDS: ClassVar = {
        "name": ("STRING", None), "library": ("POINTER", None), "override_library": ("POINTER", None),
        "is_editable": ("BOOLEAN", 0), "users": ("INT", 0), "is_editmode": ("BOOLEAN", 0),
        "animation_data": ("POINTER", None), "shape_keys": ("POINTER", None),
        "materials": ("COLLECTION", None), "uv_layers": ("COLLECTION", None),
        "color_attributes": ("COLLECTION", None), "attributes": ("COLLECTION", None),
        "vertices": ("COLLECTION", None), "edges": ("COLLECTION", None),
        "polygons": ("COLLECTION", None), "loops": ("COLLECTION", None),
        "use_auto_texspace": ("BOOLEAN", 0),
    }
    ATTRIBUTES = frozenset({"position", ".edge_verts", ".corner_vert", ".corner_edge",
        ".select_vert", ".hide_vert", ".select_edge", ".hide_edge", ".select_poly", ".hide_poly",
        "material_index", "sharp_face", "sharp_edge", ".uv_seam"})

    def __init__(self, context: Any, params: Any):
        self.context, self.params = context, params
        self._origin = self._ordinary_origin()
        from .utils import require_blender
        self.bpy = require_blender()
        if (sys.platform != "linux" or tuple(self.bpy.app.version) not in self.BUILDS
                or self.bpy.app.build_hash != self.BUILDS[tuple(self.bpy.app.version)]):
            raise _error("Direct weight native admission supports only the two source-reviewed Linux builds.",
                         native_profile_qualified=False)
        self.name = params["object_name"]
        self._ids = None
        self._method_type = None
        first = self.snapshot()
        if not any(first.memberships.memberships):
            raise _error("Initial direct weights require already populated deform storage.")
        self._ids = self._identity(self._object()), self._identity(self._object().data)

    def _ordinary_origin(self):
        # A literal's immutable native class supplies the bootstrap type anchor;
        # no caller-replaceable comparator or container is touched first.
        native_type, native_tuple, native_dict = ().__class__.__class__, ().__class__, {}.__class__
        native_str, native_function, native_bool = "".__class__, (lambda: None).__class__, True.__class__
        tuple_length = native_tuple.__len__
        if (native_type(_PURE_NAMESPACE) is not native_dict
                or native_type(_LOCAL_NAMESPACE_ORIGIN) is not native_dict
                or _PURE_NAMESPACE is not _LOCAL_NAMESPACE_ORIGIN
                or native_type(_PURE_BUILTINS) is not native_dict
                or native_type(_PURE_ALIASES) is not native_tuple or tuple_length(_PURE_ALIASES) != 9
                or native_type(_PURE_BUILTIN_FACTS) is not native_tuple or tuple_length(_PURE_BUILTIN_FACTS) != 8
                or native_type(_LOCAL_FACTS) is not native_tuple or tuple_length(_LOCAL_FACTS) != 4):
            raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin root shape changed.")
        for rows in (_PURE_ALIASES, _PURE_BUILTIN_FACTS):
            for row in rows:
                if (native_type(row) is not native_tuple or tuple_length(row) != 2
                        or native_type(row[0]) is not native_str):
                    raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin primitive pin shape changed.")
        for row in _LOCAL_FACTS:
            if (native_type(row) is not native_tuple or tuple_length(row) != 2
                    or native_type(row[0]) is not native_str or native_type(row[1]) is not native_tuple
                    or tuple_length(row[1]) != 12):
                raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin comparator pin shape changed.")
            fact = row[1]
            if (native_type(fact[0]) is not native_function or fact[2] is not _PURE_NAMESPACE
                    or fact[3] is not _PURE_BUILTINS or fact[4] is not None or fact[5] is not None
                    or native_type(fact[6]) is not native_tuple or tuple_length(fact[6]) != 0
                    or fact[7] is not None or native_type(fact[8]) is not native_tuple or tuple_length(fact[8]) != 0
                    or native_type(fact[9]) is not native_tuple or tuple_length(fact[9]) > 128):
                raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin comparator pin contents changed.")
            for binding in fact[9]:
                if (native_type(binding) is not native_tuple or tuple_length(binding) != 3
                        or native_type(binding[0]) is not native_str or native_type(binding[1]) is not native_bool):
                    raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin binding pin shape changed.")
        # No local comparator is called until its complete executable shape and
        # direct bindings pass this independent inline fence. Native primitive
        # aliases also make a rejected builtin substitution callback-free.
        for name, expected in _PURE_ALIASES:
            if _PURE_NAMESPACE.get(name, _MISSING) is not expected:
                raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin primitive changed.")
        for name, expected in _PURE_BUILTIN_FACTS:
            if _PURE_BUILTINS.get(name, _MISSING) is not expected:
                raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin builtin changed.")
        for name, fact in _LOCAL_FACTS:
            function, code, namespace, builtins, defaults, kwdefaults, keywords, closure, cells, bindings, importer, alias = fact
            if (_PURE_NAMESPACE.get(name, _MISSING) is not function
                    or _PURE_TYPE(function) is not FunctionType or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__builtins__ is not builtins
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                    or function.__closure__ is not closure
                    or builtins.get("__import__", _MISSING) is not importer
                    or namespace.get("__builtins__", _MISSING) is not alias):
                raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin comparator changed.")
            if kwdefaults is not None:
                if _PURE_TYPE(kwdefaults) is not dict or _PURE_LEN(kwdefaults) != _PURE_LEN(keywords):
                    raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin comparator defaults changed.")
                for key, value in keywords:
                    if key not in kwdefaults or kwdefaults[key] is not value:
                        raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin comparator defaults changed.")
            for cell, value in cells:
                if cell.cell_contents is not value:
                    raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin comparator closure changed.")
            for key, present, value in bindings:
                if ((key in namespace) is not present
                        or namespace.get(key, builtins.get(key, _MISSING)) is not value):
                    raise _ORIGIN_ERROR("NOT_IMPLEMENTED", "Weight origin comparator binding changed.")
        runtime = _runtime
        if _PURE_TYPE(runtime) is not ModuleType:
            raise _error("Canonical weight runtime module changed.")
        active = _PURE_VARS(runtime).get("_RUNTIME")
        grant_origin = _h01_origin(active)
        from .command_queue import QueuedRequest
        from .executor import MainThreadExecutor
        from .permissions import PermissionManager
        from .tool_registry import ToolContext
        c = self.context
        if (threading.current_thread() is not threading.main_thread()
                or type(c) is not ToolContext or type(active) is not _RUNTIME_CLASS
                or runtime.BridgeRuntime is not _RUNTIME_CLASS
                or c.state is not active.state or c.registry is not active.registry
                or c.permissions is not active.permissions or c.checkpoints is not active.checkpoints
                or type(active.executor) is not MainThreadExecutor
                or active.executor.state is not c.state or active.executor.registry is not c.registry
                or active.executor.permissions is not c.permissions or active.executor.checkpoints is not c.checkpoints
                or active.executor.jobs is not c.jobs
                or c.jobs is not active.jobs or type(active.jobs) is not _NATIVE_SAVE_JOBS or active.jobs.active is not None
                or type(c.permissions) is not PermissionManager or c.check_final_job is not None):
            raise _error("Direct weight native calls require canonical runtime services and main-thread origin.",
                         native_profile_qualified=False, origin_supported=False)
        source = c.permissions._source
        codes = tuple(item for item in runtime.BridgeRuntime.__init__.__code__.co_consts
                      if type(item) is CodeType and set(item.co_names) == {"permission_snapshot", "_preferences"})
        if (type(source) is not FunctionType or len(codes) != 1 or source.__code__ is not codes[0]
                or source.__globals__ is not vars(runtime) or source.__closure__ is not None
                or source.__builtins__ is not _PERMISSION_SNAPSHOT.__builtins__
                or source.__defaults__ is not None or source.__kwdefaults__ is not None
                or source.__code__ is not _PROVIDER_CODE
                or runtime._preferences is not _PREFERENCES or _PREFERENCES.__code__ is not _PREFERENCES_CODE
                or _PREFERENCES.__globals__ is not vars(runtime)
                or runtime.permission_snapshot is not _PERMISSION_SNAPSHOT
                or _PERMISSION_SNAPSHOT.__code__ is not _PERMISSION_SNAPSHOT_CODE):
            raise _error("Unknown weight permission-provider origins are refused before native reads.",
                         native_profile_qualified=False, origin_supported=False)
        cancel, final = c.check_cancelled, c.check_final_request
        if cancel is None:
            if final is not None:
                raise _error("A direct weight call has an unknown final-request origin.")
            request = None
        else:
            request = getattr(cancel, "__self__", None)
            final_codes = tuple(item for item in MainThreadExecutor._invoke_owned.__code__.co_consts
                                if type(item) is CodeType and item.co_freevars == ("queued_owner",))
            if (type(request) is not QueuedRequest or getattr(cancel, "__func__", None) is not QueuedRequest.check_active
                    or type(final) is not FunctionType or len(final_codes) != 1 or final.__code__ is not final_codes[0]
                    or final.__closure__ is None or len(final.__closure__) != 1
                    or final.__closure__[0].cell_contents is not request
                    or c.request_lifecycle is not request.request._lifecycle):
                raise _error("Unknown weight cancellation/provider hooks are refused before native reads.")
        return (active, source, source.__code__, source.__globals__, runtime._preferences,
                runtime._preferences.__code__, runtime._preferences.__globals__, runtime.permission_snapshot,
                runtime.permission_snapshot.__code__, runtime.permission_snapshot.__globals__,
                cancel, final, None if final is None else final.__code__,
                c.request_lifecycle, request, c.state, c.registry, c.checkpoints,
                active.executor, active.jobs, *grant_origin)

    def _check_origin(self):
        current = self._ordinary_origin()
        if len(current) != len(self._origin) or any(a is not b for a, b in zip(current, self._origin, strict=True)):
            raise _error("The ordinary weight call origin changed.")

    @staticmethod
    def _identity(owner):
        pointer, uid = owner.as_pointer(), owner.session_uid
        if type(pointer) is not int or type(uid) is not int or pointer <= 0 or uid <= 0:
            raise _error("Weight ID ownership requires genuine positive native pointer/session UID.")
        return pointer, uid

    @staticmethod
    def _base(owner_type):
        candidates = [base for base in owner_type.__mro__ if base.__name__ == "bpy_struct"]
        if len(candidates) != 1 or type(candidates[0]) is not type:
            raise _error("Weight ownership requires the genuine native RNA base.")
        return candidates[0]

    def _schema(self, owner, family, fields):
        cls = getattr(self.bpy.types, family)
        if type(owner) is not cls or owner.bl_rna.as_pointer() != cls.bl_rna.as_pointer():
            raise _error("Weight reads require exact canonical native classes.")
        props = tuple(cls.bl_rna.properties)
        if len(props) > 512:
            raise _error("Native weight schema exceeds its bounded inventory.")
        if family not in {"Object", "Mesh"} and any(prop.is_runtime for prop in props):
            raise _error("Weight element/group runtime descriptors require a broader profile.")
        for name, (kind, size) in fields.items():
            prop = cls.bl_rna.properties.get(name)
            if (prop is None or prop.identifier != name or prop.is_runtime or prop.is_registered
                    or prop.type != kind or (size is not None and prop.array_length != size)):
                raise _error("A required native weight descriptor changed.", property=name)
        return props

    def _stored_runtime(self, owner, props):
        # Noncreating native presence, never a bundled runtime pointer getter.
        owner_type = owner.bl_rna.identifier
        base = self._base(type(owner))
        presence = vars(base).get("is_property_set")
        keys = vars(base).get("keys")
        if (type(presence) is not MethodDescriptorType or presence.__objclass__ is not base
                or type(keys) is not MethodDescriptorType or keys.__objclass__ is not base):
            raise _error("Native weight storage-presence methods changed.", owner_type=owner_type)
        if tuple(keys(owner)):
            raise _error("Initial direct weights refuse custom USER properties.", owner_type=owner_type)
        allowed = {"Object": {"cycles": ("POINTER", "CyclesObjectSettings"),
                              "selection_sets": ("COLLECTION", "SelectionSet"),
                              "active_selection_set": ("INT", None)},
                   "Mesh": {"cycles": ("POINTER", "CyclesMeshSettings")}}
        signatures = []
        identifiers = tuple(prop.identifier for prop in props)
        if len(set(identifiers)) != len(identifiers):
            raise _error("Native weight property identifiers are not unique.", owner_type=owner_type)
        for prop in props:
            if prop.is_runtime:
                expected = allowed.get(owner_type, {}).get(prop.identifier)
                if (expected is None or prop.type != expected[0] or prop.is_registered
                        or bool(prop.is_readonly) != (prop.identifier != "active_selection_set")
                        or (expected[1] is not None and prop.fixed_type.identifier != expected[1])
                        or (prop.identifier == "active_selection_set" and (prop.array_length or prop.default != 0))):
                    raise _error("Unknown runtime weight metadata is unsupported.",
                                 owner_type=owner_type, property=prop.identifier)
                metadata = self._mesh_cycles_metadata(prop) if owner_type == "Mesh" else None
                present = presence(owner, prop.identifier, ghost=False)
                if type(present) is not bool or present:
                    raise _error("Stored runtime weight settings require a broader preservation profile.",
                                 owner_type=owner_type, property=prop.identifier,
                                 native_presence_boolean=type(present) is bool,
                                 runtime_getter_fallback_used=False)
                signatures.append((prop.identifier, prop.type, int(prop.as_pointer()), metadata))
        if owner_type == "Mesh" and "cycles" not in {item[0] for item in signatures}:
            raise _error("Mesh weights require the reviewed bundled cycles declaration.",
                         owner_type=owner_type, property="cycles")
        return tuple(signatures)

    def _mesh_cycles_metadata(self, prop):
        """Exact empty bundled group schema; no instance/runtime pointer read.

        Both pinned builds require native absence, including ghost storage.
        This does not adopt 4.5 USER storage or infer a raw 5.2 SYSTEM reader.
        """
        build = self.bpy.app.build_hash
        if type(build) is not bytes or build not in self.BUILDS.values():
            raise _error("Mesh runtime metadata requires an exact reviewed build.",
                         owner_type="Mesh", property="cycles")
        fixed, base = prop.fixed_type, self.bpy.types.PropertyGroup.bl_rna
        if (fixed.base is None or fixed.base.as_pointer() != base.as_pointer()
                or len(fixed.properties) != 2 or len(base.properties) != 2):
            raise _error("Mesh cycles settings require the reviewed empty native group schema.",
                         owner_type="Mesh", property="cycles")
        group_props, base_props = tuple(fixed.properties), tuple(base.properties)
        if ({p.identifier for p in group_props} != {"rna_type", "name"}
                or {p.identifier for p in base_props} != {"rna_type", "name"}):
            raise _error("Mesh cycles settings contain unknown inherited fields.",
                         owner_type="Mesh", property="cycles")

        def signature(value):
            fixed_type = value.fixed_type.identifier if value.type in {"POINTER", "COLLECTION"} else None
            return (value.identifier, value.type, value.is_readonly, value.is_runtime,
                    value.is_registered, fixed_type, int(value.as_pointer()))

        inherited = {p.identifier: signature(p) for p in base_props}
        schema = tuple(signature(p) for p in group_props)
        expected = {"rna_type": ("POINTER", True), "name": ("STRING", False)}
        for row in schema:
            if (row[:-1] != inherited[row[0]][:-1] or row[1:3] != expected[row[0]]
                    or row[3] is not False or row[4] is not False):
                raise _error("Mesh cycles settings contain an unreviewed field declaration.",
                             owner_type="Mesh", property="cycles", group_property=row[0])
        return (build.decode("ascii"), "NATIVE_ABSENCE_ONLY", int(fixed.as_pointer()), schema,
                int(base.as_pointer()), tuple(inherited[name] for name in sorted(inherited)))

    def _object(self):
        obj = self.bpy.data.objects.get(self.name)
        if obj is None:
            raise _error("The original weight Object is no longer in current Main.")
        props = self._schema(obj, "Object", self.OBJECT_FIELDS)
        mesh = obj.data
        self._schema(mesh, "Mesh", self.MESH_FIELDS)
        if self._ids is not None and (self._identity(obj), self._identity(mesh)) != self._ids:
            raise _error("The original weight Object or Mesh identity changed.")
        if (obj.name != self.name or obj.type != "MESH" or obj.mode != "OBJECT" or mesh.is_editmode
                or obj.library is not None or obj.override_library is not None or not obj.is_editable
                or mesh.library is not None or mesh.override_library is not None or not mesh.is_editable
                or mesh.users != 1 or obj.parent is not None
                or len(obj.modifiers) or len(obj.constraints) or obj.instance_type != "NONE"
                or obj.animation_data is not None or mesh.animation_data is not None or mesh.shape_keys is not None
                or len(mesh.materials) or len(mesh.uv_layers) or len(mesh.color_attributes)):
            raise _error("Direct weights require the bounded static local unshared Mesh profile.")
        self._stored_runtime(obj, props)
        self._stored_runtime(mesh, tuple(mesh.bl_rna.properties))
        if not (1 <= len(mesh.vertices) <= intent.MAX_VERTICES and len(mesh.edges) <= intent.MAX_EDGES
                and len(mesh.polygons) <= intent.MAX_POLYGONS and len(mesh.loops) <= intent.MAX_CORNERS
                and 1 <= len(obj.vertex_groups) <= intent.MAX_GROUPS):
            raise _error("Weight native topology/group counts exceed the profile.")
        attributes = tuple(mesh.attributes)
        if len(attributes) > 32 or any(a.name not in self.ATTRIBUTES for a in attributes):
            raise _error("Unreviewed Mesh attribute storage requires a broader weight profile.")
        return obj

    def _global(self, obj):
        from .tools import _scene_mutation as scene
        scene.runtime(self.bpy)
        main = self.bpy.data
        if len(main.actions) or len(main.libraries) or len(main.texts):
            raise _error("Initial direct weights refuse global Actions, libraries and Text scripts.")
        rows, count = [], 0
        for descriptor in tuple(main.bl_rna.properties):
            if descriptor.type != "COLLECTION" or descriptor.is_runtime:
                continue
            collection = getattr(main, descriptor.identifier)
            for owner in collection:
                count += 1
                if count > 256:
                    raise _error("Weight global static-ID screening exceeds its bounded profile.")
                canonical = getattr(self.bpy.types, owner.bl_rna.identifier, None)
                if canonical is None or type(owner) is not canonical:
                    raise _error("Global weight animation screening requires exact native ID types.")
                prop = canonical.bl_rna.properties.get("animation_data")
                if prop is not None and (
                        prop.is_runtime or prop.type != "POINTER" or owner.animation_data is not None):
                    raise _error("Unrelated animation/drivers must be absent before weight checkpoints.")
                rows.append((descriptor.identifier, self._identity(owner), owner.name))
        current = self.bpy.context.scene
        if current is None or main.scenes.get(current.name) != current:
            raise _error("Direct weights require the current native Scene.")
        scenes = tuple(item for item in main.scenes if item.objects.get(obj.name) == obj)
        collections = tuple(item for item in main.collections if item.objects.get(obj.name) == obj)
        if any(other.parent == obj for other in main.objects):
            raise _error("Weight target children require a wider dependency profile.")
        if len(scenes) != 1 or scenes[0] != current or not 1 <= len(collections) <= 8:
            raise _error("Weight target scene/collection ownership is not local and bounded.")
        user_map = main.user_map(subset={obj, obj.data})
        mesh_users, object_users = tuple(user_map.get(obj.data, ())), tuple(user_map.get(obj, ()))
        allowed = {int(current.as_pointer()), *(int(c.as_pointer()) for c in collections)}
        if (mesh_users != (obj,) or len(object_users) > 16
                or any(int(user.as_pointer()) not in allowed for user in object_users)):
            raise _error("Weight consumers include unreviewed direct or transitive roles.")
        for collection in collections:
            if (collection.library is not None or collection.override_library is not None
                    or not collection.is_editable or len(collection.children)
                    or current.collection.children.get(collection.name) != collection
                    or int(collection.users) - int(bool(collection.use_fake_user)) != 1
                    or int(collection.user_of_id(obj)) != 1):
                raise _error("Weight owning Collections must be direct local unshared leaves.")
        return (tuple(sorted(rows)), self._identity(current), int(self.bpy.context.view_layer.as_pointer()),
                main.filepath, int(current.frame_current), float(current.frame_subframe),
                tuple(sorted(self._identity(c) for c in collections)))

    def _groups(self, obj):
        result = []
        for group in obj.vertex_groups:
            try:
                self._schema(group, "VertexGroup", {"name": ("STRING", None), "index": ("INT", 0),
                                                     "lock_weight": ("BOOLEAN", 0)})
                if group.id_data.as_pointer() != obj.as_pointer():
                    raise _error("A weight group has a different native owner.")
                result.append(intent.GroupState(group.index, group.name, int(group.as_pointer()), bool(group.lock_weight)))
            finally:
                group = None
        return tuple(result)

    def snapshot(self):
        self._check_origin()
        obj = self._object()
        mesh = obj.data
        global_state = self._global(obj)
        runtime_metadata = (self._stored_runtime(obj, tuple(obj.bl_rna.properties)),
                            self._stored_runtime(mesh, tuple(mesh.bl_rna.properties)))
        groups = self._groups(obj)
        memberships, geometry = [], []
        for vertex in mesh.vertices:
            self._schema(vertex, "MeshVertex", {"index": ("INT", 0), "co": ("FLOAT", 3),
                "groups": ("COLLECTION", None), "select": ("BOOLEAN", 0), "hide": ("BOOLEAN", 0)})
            members = []
            for member in vertex.groups:
                try:
                    self._schema(member, "VertexGroupElement", {"group": ("INT", 0), "weight": ("FLOAT", 0)})
                    members.append((member.group, intent.f32_bits(member.weight)))
                finally:
                    member = None
            memberships.append(tuple(sorted(members)))
            geometry.append((vertex.index, tuple(vertex.co), vertex.select, vertex.hide))
            vertex = None
        edges = []
        for edge in mesh.edges:
            self._schema(edge, "MeshEdge", {"vertices": ("INT", 2), "select": ("BOOLEAN", 0),
                "hide": ("BOOLEAN", 0), "use_seam": ("BOOLEAN", 0), "use_edge_sharp": ("BOOLEAN", 0)})
            edges.append((tuple(edge.vertices), edge.select, edge.hide, edge.use_seam, edge.use_edge_sharp))
            edge = None
        polygons = []
        for polygon in mesh.polygons:
            self._schema(polygon, "MeshPolygon", {"vertices": ("INT", 3), "select": ("BOOLEAN", 0),
                "hide": ("BOOLEAN", 0), "material_index": ("INT", 0), "use_smooth": ("BOOLEAN", 0),
                "loop_start": ("INT", 0), "loop_total": ("INT", 0)})
            polygons.append((tuple(polygon.vertices), polygon.select, polygon.hide,
                             polygon.material_index, polygon.use_smooth, polygon.loop_start, polygon.loop_total))
            polygon = None
        loops = []
        for loop in mesh.loops:
            self._schema(loop, "MeshLoop", {"vertex_index": ("INT", 0), "edge_index": ("INT", 0)})
            if not (0 <= loop.vertex_index < len(mesh.vertices) and 0 <= loop.edge_index < len(mesh.edges)):
                raise _error("Weight topology has an invalid native corner index.")
            loops.append((loop.vertex_index, loop.edge_index))
            loop = None
        channels = tuple((name, tuple(getattr(obj, name)) if kind == "FLOAT" and size else getattr(obj, name))
                         for name, (kind, size) in self.OBJECT_FIELDS.items()
                         if kind in {"FLOAT", "BOOLEAN", "ENUM", "STRING"})
        markers = self.context.checkpoints._marker_evidence(self.bpy)
        attrs = tuple((a.name, a.data_type, a.domain, len(a.data)) for a in mesh.attributes)
        state = NativeState((self._identity(obj), self._identity(mesh), global_state, runtime_metadata, channels,
            tuple(geometry), tuple(edges), tuple(polygons), tuple(loops), attrs, obj.vertex_groups.active_index,
            mesh.use_auto_texspace), intent.MembershipSnapshot(groups, tuple(memberships)), markers)
        _state_data(state)
        self._check_origin()
        return state

    def resolve(self, vertex, group, expected, value):
        self._check_origin()
        # Prebuild every Python argument before full CAS and native method acquisition.
        leaf = _NativeLeaf(((vertex,),) if value is None else
                           ((vertex,), intent.f32_value(value), "REPLACE"))
        method_name = "remove" if value is None else "add"
        fields = (("index", "INT", 1),) if value is None else (
            ("index", "INT", 1), ("weight", "FLOAT", 0), ("type", "ENUM", None))
        function = self.bpy.types.VertexGroup.bl_rna.functions.get(method_name)
        if function is None or function.is_registered or function.is_registered_optional:
            raise _error("A genuine native weight method descriptor was replaced.")
        parameters = tuple(function.parameters)
        if tuple(p.identifier for p in parameters) != tuple(f[0] for f in fields):
            raise _error("Native weight method argument schema changed.")
        for prop, (identifier, kind, size) in zip(parameters, fields, strict=True):
            if prop.type != kind or prop.is_runtime or (size is not None and prop.array_length != size):
                raise _error("Native weight argument metadata changed.", property=identifier)
        if self.snapshot() != expected:
            raise _error("Fresh weight native leaf lost the complete expected prefix.")
        obj = self._object()
        target = obj.vertex_groups.get(group.name)
        if (target is None or type(target) is not self.bpy.types.VertexGroup or target.index != group.index
                or int(target.as_pointer()) != group.pointer or target.lock_weight
                or target.id_data.as_pointer() != obj.as_pointer()
                or not 0 <= vertex < len(obj.data.vertices)):
            raise _error("Fresh native weight group/vertex ownership changed.")
        base = self._base(self.bpy.types.VertexGroup)
        getattribute = vars(base).get("__getattribute__")
        if type(getattribute) is not WrapperDescriptorType or getattribute.__objclass__ is not base:
            raise _error("The genuine native RNA attribute resolver is unavailable.")
        try:
            method = getattribute(target, method_name)
            cls = type(method)
            call = vars(cls).get("__call__")
            if (cls.__name__ != "bpy_func" or type(call) is not WrapperDescriptorType
                    or call.__objclass__ is not cls):
                raise _error("Weight field leaf requires a genuine C RNA function.")
            if self._method_type is not None and cls is not self._method_type:
                raise _error("Native weight method type identity changed.")
            self._method_type = cls
            leaf.method = method
        finally:
            target = obj = method = None
        return leaf
