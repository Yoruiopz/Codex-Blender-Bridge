"""Retained current-pixels request/source origins; no public registration here.

The first preview establishes its complete pixel baseline only AFTER canonical
grants and approved-path/resource checks. Its earlier bounded identity/context
witness cannot detect pixel-only changes in that first authorization window.
Starts bind the existing complete preview before providers and never rebase it.
This finite callback guard assumes the qualified runtime and normal owned Python
lifetimes, not an arbitrary interpreter or hidden-Main sandbox.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import math
import shutil
import sys
import threading
import time
import uuid
from _thread import LockType
from collections import OrderedDict
from dataclasses import dataclass
from types import CodeType, FunctionType, MappingProxyType, MethodType, ModuleType
from typing import Any

from . import command_queue, current_pixels_contract, current_pixels_files, executor, jobs, protocol
from .errors import BridgeError
from .permissions import Permission
from .preferences import get_preferences
from .request_lifecycle import ConnectionLifetime, RequestLifetime
from .state import BridgeState
from .task_plans import TaskPlanStore, get_task_plans
from .tool_registry import ToolContext, ToolRegistry, ToolSpec, _checkpoint_parameters
from .utils import require_blender

METHODS = (current_pixels_contract.PACK_PREVIEW, current_pixels_contract.PACK_START,
           current_pixels_contract.RECOVERY_PREVIEW, current_pixels_contract.RESTORE_START)
REQUIRED = (Permission.INSPECT_SCENE, Permission.EDIT_MATERIALS,
            Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT)
HANDLERS = dict(zip(METHODS, ("pack_preview", "pack_start", "recovery_preview", "restore_start"), strict=True))
MAX_PLANS, MAX_PLAN_BYTES, PLAN_SECONDS = 16, 65536, 60.
_MISSING = object()
_REGISTRATION = None
_PLANS: OrderedDict[str, Any] = OrderedDict()


def refused(reason):
    return BridgeError("OPERATION_FAILED", "Current-pixel source or request ownership changed; obtain a fresh preview.",
                       {"reason": reason, "verification_required": True, "recovery_authorized": False})


def _function_facts(function):
    if type(function) is not FunctionType:
        raise refused("SOURCE_FUNCTION_REQUIRED")
    return (function, function.__code__, function.__globals__, function.__defaults__, function.__kwdefaults__,
            tuple((cell, cell.cell_contents) for cell in function.__closure__ or ()))


def _function_matches(function, facts):
    try:
        if (type(function) is not FunctionType or function is not facts[0]
                or function.__code__ is not facts[1] or function.__globals__ is not facts[2]
                or function.__defaults__ is not facts[3] or function.__kwdefaults__ is not facts[4]):
            return False
        closure = function.__closure__ or ()
        captured = facts[5]
        if len(closure) != len(captured):
            return False
        for index, (cell, value) in enumerate(captured):
            current = closure[index]
            if current is not cell or current.cell_contents is not value:
                return False
        return True
    except Exception:
        return False


def _plain(value):
    """Finite immutable cache bytes, never native handles, arrays or callbacks."""
    _checkpoint_parameters(value)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_PLAN_BYTES:
        raise refused("PLAN_BYTE_BUDGET")
    return raw


def _static(owner, name):
    if type(owner) is ModuleType:
        return vars(owner).get(name, _MISSING)
    if type(owner) is type:
        # These canonical native getsets do not evaluate a class's own or its
        # metaclass's Python __dict__/__mro__ descriptors. No lookup is cached.
        mro = type.__dict__["__mro__"].__get__(owner)
        if all(type(base) is type for base in mro):
            for base in mro:
                namespace = type.__dict__["__dict__"].__get__(base)
                if name in namespace:
                    return namespace[name]
            # Match getattr_static's metaclass fallback for missing members.
            for base in type.__dict__["__mro__"].__get__(type(owner)):
                namespace = type.__dict__["__dict__"].__get__(base)
                if name in namespace:
                    return namespace[name]
            return _MISSING
    return inspect.getattr_static(owner, name, _MISSING)


def _literal_facts(value, depth=0, remaining=None):
    """Snapshot only finite schema constants, including exact build-byte keys."""
    remaining = [4096] if remaining is None else remaining
    remaining[0] -= 1
    if remaining[0] < 0:
        raise refused("SOURCE_CONSTANT_BUDGET")
    if depth > 8:
        raise refused("SOURCE_CONSTANT_BUDGET")
    if value is None or type(value) in {str, bool, int}:
        if (type(value) is str and len(value) > 4096) or (type(value) is int and value.bit_length() > 4096):
            raise refused("SOURCE_CONSTANT_BUDGET")
        return type(value).__name__, value
    if type(value) is float and math.isfinite(value):
        return "float", value.hex()
    if type(value) is bytes and len(value) <= 128:
        return "bytes", value.hex()
    if type(value) in {tuple, list, set, frozenset}:
        if len(value) > 4096:
            raise refused("SOURCE_CONSTANT_BUDGET")
        rows = tuple(_literal_facts(item, depth + 1, remaining) for item in value)
        return type(value).__name__, tuple(sorted(rows, key=repr)) if type(value) in {set, frozenset} else rows
    if type(value) is dict and len(value) <= 4096 and all(type(key) in {str, bytes} or (
            type(key) is tuple and len(key) == 2 and all(type(part) is str for part in key)) for key in value):
        return "dict", tuple(sorted(((_literal_facts(key, depth + 1, remaining), _literal_facts(item, depth + 1, remaining))
                                     for key, item in value.items()), key=repr))
    raise refused("NONLITERAL_SOURCE_CONSTANT")


def _deeply_immutable_literal(value):
    """Only exact builtin literals, already validated within capture budgets."""
    if value is None or type(value) in {str, bool, int, bytes}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return type(value) in {tuple, frozenset} and all(_deeply_immutable_literal(item) for item in value)


def _collect_immutable_literals(value, facts, captured):
    if _deeply_immutable_literal(value):
        captured[id(facts)] = (facts, value)  # Strong refs, not bare addresses.
        return
    kind, rows = facts
    if kind in {"list", "tuple"}:
        for item, fact in zip(value, rows, strict=True):
            _collect_immutable_literals(item, fact, captured)
    elif kind == "dict":
        for (key_kind, key_fact), item_fact in rows:
            key = (bytes.fromhex(key_fact) if key_kind == "bytes" else
                   tuple(part[1] for part in key_fact) if key_kind == "tuple" else key_fact)
            _collect_immutable_literals(value[key], item_fact, captured)
    # Mutable sets keep the existing complete content comparison. Their
    # iteration order need not be paired with sorted fact-node identities.


def _immutable_literal_refs(value, facts):
    if MappingProxyType is not type(type.__dict__):
        raise refused("IMMUTABLE_LITERAL_MAP_TYPE_CHANGED")
    captured = {}
    _collect_immutable_literals(value, facts, captured)
    return MappingProxyType(captured)  # No raw mutable alias leaves this call.


def _literal_matches(value, facts, immutable=None):
    """Compare only exact builtin literals to a bounded immutable fact tree.

    Traverse the captured shape, without rebuilding or sorting large tables at
    every native safe point. Foreign keys are refused before any dict lookup.
    """
    if immutable is not None:
        if type(immutable) is not MappingProxyType:
            raise refused("IMMUTABLE_LITERAL_MAP_TYPE_CHANGED")
        retained = immutable.get(id(facts))
        if retained is not None and retained[0] is facts and retained[1] is value:
            return True
    kind, expected = facts
    if kind == "NoneType":
        return value is None
    if kind in {"str", "bool", "int"}:
        return type(value) in {str, bool, int} and type(value).__name__ == kind and value == expected
    if kind == "float":
        return type(value) is float and value.hex() == expected
    if kind == "bytes":
        return type(value) is bytes and len(value) <= 128 and value.hex() == expected
    if kind in {"tuple", "list"}:
        return (type(value) in {tuple, list} and type(value).__name__ == kind and len(value) == len(expected)
                and all(_literal_matches(item, fact, immutable) for item, fact in zip(value, expected, strict=True)))
    if kind in {"set", "frozenset"}:
        return (type(value) in {set, frozenset} and type(value).__name__ == kind and len(value) == len(expected)
                and _literal_facts(value) == facts)
    if kind != "dict" or type(value) is not dict or len(value) != len(expected):
        return False
    if any(type(key) not in {str, bytes} and not (type(key) is tuple and len(key) == 2
            and all(type(part) is str for part in key)) for key in value):
        return False
    for (key_kind, key_fact), item_fact in expected:
        key = (bytes.fromhex(key_fact) if key_kind == "bytes" else
               tuple(part[1] for part in key_fact) if key_kind == "tuple" else key_fact)
        if key not in value or not _literal_matches(value[key], item_fact, immutable):
            return False
    return True


def _descriptor_facts(value):
    if type(value) is FunctionType:
        return (_function_facts(value),)
    if type(value) is property:
        return tuple(_function_facts(function) for function in (value.fget, value.fset, value.fdel) if function is not None)
    if type(value) in {classmethod, staticmethod}:
        return (_function_facts(value.__func__),)
    return ()


def _store_facts(state):
    store = vars(state).get("_artist_task_plans")
    if store is None:
        return None, None
    if type(store) is not TaskPlanStore:
        raise refused("PLAN_STORE_TYPE_CHANGED")
    values = vars(store)
    if values.get("protection") is not None:
        raise BridgeError("NOT_IMPLEMENTED", "Current-pixel lifecycle refuses enforced protected scope; it remains enforced.",
                          {"protected_scope_enforced": True, "scope_complete": False,
                           "initial_policy_classification": True, "execution_started": False})
    facts = (values.get("runtime_id"), values.get("protection_generation"), values.get("evidence_epoch"))
    if (type(facts[0]) is not str or len(facts[0]) != 32 or type(facts[1]) is not int or type(facts[2]) is not int):
        raise refused("PLAN_STORE_GENERATION_INVALID")
    return store, facts


def _scope(method, parameters):
    result = dict(parameters)
    for key in ("expected_target_fingerprint", "expected_recovery_fingerprint", "confirm_replace_packed_bytes",
                "confirm_discard_current_buffer", "confirm_restore_previous_packed_bytes",
                "confirm_restore_original_current_pixels", "time_limit_seconds"):
        result.pop(key, None)
    return _plain({"mode": "PACK" if method in METHODS[:2] else "RECOVERY", "parameters": result})


@dataclass(frozen=True, slots=True)
class _CachedPlan:
    registration: Any
    runtime: Any
    registry: Any
    owner: Any
    store: Any
    generation: Any
    scope: bytes
    raw: bytes
    expires: float


class _Registration:
    def __init__(self, registry):
        runtime_module = sys.modules.get(__package__ + ".runtime")
        domain = sys.modules.get(__package__ + ".tools.image_current_pixels")
        if type(runtime_module) is not ModuleType or type(domain) is not ModuleType:
            raise refused("CONCRETE_DOMAIN_NOT_LOADED")
        self.runtime_module, self.domain = runtime_module, domain
        self.runtime_type = vars(runtime_module).get("BridgeRuntime")
        self.runtime_constructor = _function_facts(_static(self.runtime_type, "__init__"))
        self.registry, self.nonce = registry, uuid.uuid4().hex
        self.graph = importlib.import_module(__package__ + ".current_pixels_graph")
        self.specs = tuple(vars(registry).get("_tools", {}).get(method) for method in METHODS)
        if any(type(spec) is not ToolSpec for spec in self.specs):
            raise refused("ALL_FOUR_SPECS_REQUIRED")
        self.functions, self.bindings, self.constants = [], [], []
        helpers = tuple(importlib.import_module(__package__ + "." + name) for name in (
            "tools.image_portability", "tools.image_recovery_jobs", "pixel_codecs", "uv_edit_guard", "tools._scene_mutation",
            "state", "permissions", "tool_registry", "task_plans", "request_lifecycle", "preferences", "utils"))
        modules = (sys.modules[__name__], self.graph, current_pixels_contract, current_pixels_files, jobs, self.domain, *helpers)
        required_graph_tables = {"_CATALOG_HASHES", "_STATIC_CATALOG_HASHES", "_FIXED_TARGETS", "_RUNTIME_MARKER_ROWS"}
        for module in modules:
            for name, value in tuple(vars(module).items()):
                if type(value) is FunctionType:
                    self.functions.append((module, name, value, _descriptor_facts(value)))
                elif type(value) is type and value.__module__ == module.__name__:
                    self.bindings.append((module, name, value))
                    for member, descriptor in tuple(vars(value).items()):
                        facts = _descriptor_facts(descriptor)
                        if facts:
                            self.functions.append((value, member, descriptor, facts))
                elif type(value) in {ModuleType, type}:
                    self.bindings.append((module, name, value))
                elif name.isupper() and type(value) in {str, bytes, int, float, bool, tuple, list, dict, set, frozenset}:
                    try:
                        facts = _literal_facts(value)
                        # Source fact wrappers have a different shape from an
                        # RPC request. Retain their own existing 64KiB budget.
                        if len(json.dumps(facts, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()) > MAX_PLAN_BYTES:
                            raise refused("SOURCE_CONSTANT_BYTE_BUDGET")
                        self.constants.append((module, name, facts, _immutable_literal_refs(value, facts)))
                    except (BridgeError, TypeError, ValueError):
                        if module is self.graph and name in required_graph_tables:
                            raise refused("MANDATORY_GRAPH_TABLE_NOT_CAPTURED") from None
                        continue  # Callable/type inventories are qualified separately.
        if not required_graph_tables <= {name for owner, name, _facts, _refs in self.constants if owner is self.graph}:
            raise refused("MANDATORY_GRAPH_TABLE_NOT_CAPTURED")
        self.constant_maps = tuple(row[3] for row in self.constants)
        self.runtime_callbacks = tuple((name, vars(runtime_module).get(name), _function_facts(vars(runtime_module).get(name)))
            for name in ("_preferences", "permission_snapshot", "_base_permission_snapshot", "native_save_permission_provider_intact"))
        self.queue_class, self.queue_check = command_queue.QueuedRequest, _static(command_queue.QueuedRequest, "check_active")
        self.queue_facts = _function_facts(self.queue_check)
        self.request_class = protocol.Request
        self.queue_bindings = tuple((module, name, vars(module).get(name)) for module, name in (
            (command_queue, "QueuedRequest"), (command_queue, "BridgeError"), (command_queue, "ErrorCode"),
            (command_queue, "time"), (executor, "MainThreadExecutor"), (executor, "QueuedRequest"),
            (executor, "RequestLifetime"), (protocol, "Request"), (protocol, "MAX_REQUEST_ID_LENGTH")))
        self.queue_clock = vars(command_queue.time).get("monotonic")
        self.executor_class, self.invoke = executor.MainThreadExecutor, _static(executor.MainThreadExecutor, "_invoke_owned")
        self.invoke_facts = _function_facts(self.invoke)
        self.final_codes = tuple(code for code in self.invoke.__code__.co_consts
                                 if type(code) is CodeType and code.co_freevars == ("queued_owner",))
        self.verify()

    def verify(self):
        if (type(self.registry) is not ToolRegistry or vars(self.runtime_module).get("BridgeRuntime") is not self.runtime_type
                or not _function_matches(_static(self.runtime_type, "__init__"), self.runtime_constructor)):
            raise refused("CANONICAL_RUNTIME_CLASS_CHANGED")
        for owner, name, value, facts in self.functions:
            current = vars(owner).get(name, _MISSING) if type(owner) is ModuleType else _static(owner, name)
            if current is not value:
                raise refused("DOMAIN_CALLBACK_SOURCE_CHANGED")
            # Keep every captured comparison at every safe point, without a
            # generator and helper dispatch for each descriptor function.
            for fact in facts:
                unchanged = False
                try:
                    function = fact[0]
                    if (type(function) is FunctionType and function is fact[0] and function.__code__ is fact[1]
                            and function.__globals__ is fact[2] and function.__defaults__ is fact[3]
                            and function.__kwdefaults__ is fact[4]):
                        closure, captured = function.__closure__ or (), fact[5]
                        unchanged = len(closure) == len(captured)
                        if unchanged:
                            for index, (cell, retained) in enumerate(captured):
                                actual = closure[index]
                                if actual is not cell or actual.cell_contents is not retained:
                                    unchanged = False
                                    break
                except Exception:
                    unchanged = False
                if not unchanged:
                    raise refused("DOMAIN_CALLBACK_SOURCE_CHANGED")
        for owner, name, value in self.bindings:
            current = vars(owner).get(name, _MISSING) if type(owner) is ModuleType else _static(owner, name)
            if current is not value:
                raise refused("DOMAIN_BINDING_CHANGED")
        if len(self.constants) != len(self.constant_maps):
            raise refused("IMMUTABLE_LITERAL_MAP_CHANGED")
        for index, (owner, name, facts, immutable) in enumerate(self.constants):
            if immutable is not self.constant_maps[index] or type(immutable) is not MappingProxyType:
                raise refused("IMMUTABLE_LITERAL_MAP_CHANGED")
            current = vars(owner).get(name, _MISSING) if type(owner) is ModuleType else _static(owner, name)
            if not _literal_matches(current, facts, immutable):
                raise refused("DOMAIN_CONSTANT_CHANGED")
        for name, function, facts in self.runtime_callbacks:
            if vars(self.runtime_module).get(name) is not function or not _function_matches(function, facts):
                raise refused("CANONICAL_PROVIDER_SOURCE_CHANGED")
        tools = vars(self.registry).get("_tools")
        if type(tools) is not dict:
            raise refused("REGISTRY_STORAGE_CHANGED")
        for method, spec in zip(METHODS, self.specs, strict=True):
            factory = spec.checkpoint_admission_factory
            code = admission_factory.__code__.co_consts
            expected_codes = tuple(value for value in code if type(value) is CodeType)
            if (tools.get(method) is not spec or spec.handler is not vars(self.domain).get(HANDLERS[method])
                    or type(spec.handler) is not FunctionType or spec.handler.__globals__ is not vars(self.domain)
                    or spec.toolset != "materials" or not spec.remote or spec.batchable or not spec.record_history
                    or spec.automatic_checkpoint or spec.modifies is not (method in current_pixels_contract.METHOD_MODES)
                    or spec.checkpoint_owns_finalization is not spec.modifies or spec.exclusive_mutation
                    or spec.permissions != frozenset(REQUIRED) or spec.checkpoint_parameter_dependencies is not initial_dependencies
                    or spec.protected_scope_resolver is not protected_scope
                    or type(factory) is not FunctionType or factory.__globals__ is not globals()
                    or factory.__code__ not in expected_codes or factory.__closure__ is None
                    or len(factory.__closure__) != 1 or factory.__closure__[0].cell_contents != method):
                raise refused("LIFECYCLE_SPEC_CHANGED")


def bind_registry(registry):
    """Called after all four canonical domain specs at registration, not remotely."""
    global _REGISTRATION
    if type(registry) is not ToolRegistry:
        raise refused("CANONICAL_REGISTRY_REQUIRED")
    binding = _Registration(registry)
    _PLANS.clear()
    _REGISTRATION = binding
    return binding


def _entry(registry):
    binding = _REGISTRATION
    if type(binding) is not _Registration or binding.registry is not registry:
        raise refused("REGISTERED_DOMAIN_REQUIRED")
    binding.verify()
    runtime = vars(binding.runtime_module).get("_RUNTIME")
    if (type(runtime) is not binding.runtime_type or vars(runtime).get("registry") is not registry
            or vars(runtime).get("_registered") is not True or type(vars(runtime).get("state")) is not BridgeState):
        raise refused("CANONICAL_RUNTIME_REQUIRED")
    _store_facts(vars(runtime)["state"])
    return binding, runtime


def initial_dependencies(registry, _params):
    """Pure ALL4 hook: no providers, runtime/store creation, bpy or path probes."""
    binding, _runtime = _entry(registry)
    return binding.specs


def protected_scope(_context, _params):
    raise BridgeError("NOT_IMPLEMENTED", "Current-pixel lifecycle has no admitted protected mutation scope.",
                      {"protected_scope_enforced": True, "scope_complete": False})


def admission_factory(method):
    if method not in METHODS:
        raise refused("UNKNOWN_LIFECYCLE_METHOD")
    def factory(context, params):
        return CurrentPixelsOrigin(context, params, method)
    return factory


def _queued_facts(binding, context, method, params):
    hook, final = context.check_cancelled, context.check_final_request
    if hook is None and final is None and context.check_final_job is None:
        return None
    if type(hook) is not MethodType or type(hook.__self__) is not binding.queue_class or hook.__func__ is not binding.queue_check:
        raise refused("CANONICAL_REQUEST_HOOK_REQUIRED")
    owner = hook.__self__
    if (not _function_matches(binding.queue_check, binding.queue_facts)
            or any(vars(module).get(name) is not value for module, name, value in binding.queue_bindings)
            or vars(command_queue.time).get("monotonic") is not binding.queue_clock
            or _static(binding.queue_class, "check_active") is not binding.queue_check
            or not _function_matches(binding.invoke, binding.invoke_facts)
            or _static(binding.executor_class, "_invoke_owned") is not binding.invoke
            or vars(executor).get("QueuedRequest") is not binding.queue_class
            or type(owner.request) is not binding.request_class or type(owner.request.method) is not str or owner.request.method != method
            or owner.request.params is not params or type(owner.request.id) is not str or type(context.request_id) is not str
            or len(owner.request.id) > protocol.MAX_REQUEST_ID_LENGTH or owner.request.id != context.request_id
            or owner.request._lifecycle is not context.request_lifecycle or type(owner._lock) is not LockType
            or type(owner.deadline) is not float or not math.isfinite(owner.deadline)
            or type(final) is not FunctionType or len(binding.final_codes) != 1 or final.__code__ is not binding.final_codes[0]
            or final.__globals__ is not vars(executor) or final.__defaults__ is not None or final.__kwdefaults__ is not None
            or final.__closure__ is None or len(final.__closure__) != 1 or final.__closure__[0].cell_contents is not owner
            or context.check_final_job is not None):
        raise refused("CANONICAL_REQUEST_OWNERSHIP_REQUIRED")
    return (hook, _function_facts(final), owner, owner.request, owner._lock, owner.deadline)


def _owner(context):
    lifetime = context.request_lifecycle
    if lifetime is None:
        return None, None
    if type(lifetime) is not RequestLifetime or (lifetime.connection is not None and type(lifetime.connection) is not ConnectionLifetime):
        raise refused("CANONICAL_LIFETIME_REQUIRED")
    events = (lifetime.delivered, lifetime.rejected) + (() if lifetime.connection is None else
             (lifetime.connection.disconnected, lifetime.connection.background_active))
    if any(type(event) is not threading.Event for event in events):
        raise refused("CANONICAL_LIFETIME_EVENTS_REQUIRED")
    return lifetime, lifetime.connection


def _context_witness(bpy):
    # Object-mode is the admitted native undo context. Selection is never read
    # or changed here; broader context preservation still needs native evidence.
    mode = bpy.context.mode
    if type(mode) is not str or mode != "OBJECT":
        raise BridgeError("NOT_IMPLEMENTED", "Current-pixel lifecycle requires Object Mode.")
    return {"mode": mode}


def _available_memory():
    # Fixed OS resource metadata, never an arbitrary user path or project file.
    if sys.platform != "linux":
        raise BridgeError("NOT_IMPLEMENTED", "Current-pixel resource preflight is qualified only on Linux.")
    try:
        with open("/proc/meminfo", "rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError
        rows = [line.split() for line in raw.splitlines() if line.startswith(b"MemAvailable:")]
        if len(rows) != 1 or len(rows[0]) != 3 or rows[0][2] != b"kB":
            raise ValueError
        value = int(rows[0][1]) * 1024
        if not 0 <= value <= 2**63 - 1:
            raise ValueError
        return value
    except (OSError, ValueError) as cause:
        raise refused("AVAILABLE_MEMORY_MEASUREMENT_UNAVAILABLE") from cause


class CurrentPixelsOrigin:
    """Pre-provider callback/witness and retained full-preview source intent."""

    __slots__ = ("_sealed", "authorized", "binding", "bound", "cached", "callback_verifier", "callbacks", "capture", "connection_events",
                 "context", "deadline", "file_plan", "file_root", "first_full_raw", "gate_context", "generation",
                 "hooks", "invocation", "lifetime", "lifetime_facts", "method", "normalized_facts", "owner",
                 "parameter_facts", "parameters", "params", "request_hooks", "runtime", "scope", "services",
                 "spec", "store", "used", "witness")

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise refused("RETAINED_ORIGIN_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise refused("RETAINED_ORIGIN_IMMUTABLE")

    def __init__(self, context, params, method):
        if threading.current_thread() is not threading.main_thread() or type(context) is not ToolContext:
            raise refused("MAIN_THREAD_CONTEXT_REQUIRED")
        self.binding, self.runtime = _entry(context.registry)
        self.context, self.params, self.method = context, params, method
        self.parameters = current_pixels_contract.validate_request(method, params)
        self.normalized_facts = _plain(self.parameters)
        self.parameter_facts, self.scope = _checkpoint_parameters(params), _scope(method, self.parameters)
        self.spec = self.binding.specs[METHODS.index(method)]
        entries = vars(context.registry._mutation_interlock).get("_entries")
        if (type(entries) is not list or not entries or entries[-1].context is not context
                or entries[-1].spec is not self.spec or entries[-1].params is not params):
            raise refused("CANONICAL_ENTRY_REQUIRED")
        self.invocation = entries[-1]
        self.services = tuple((name, getattr(context, name)) for name in ("state", "registry", "permissions", "checkpoints", "jobs", "evidence"))
        for owner, name in ((context, "require"), (context.permissions, "require"), (context.registry, "get"),
                            (context.registry, "prepare"), (context.state, "snapshot"),
                            (context.checkpoints, "before_modification"), (context.checkpoints, "after_modification")):
            if _static(owner, name) is not _static(type(owner), name):
                raise refused("INSTANCE_SERVICE_CALLBACK_UNQUALIFIED")
        self.request_hooks = _queued_facts(self.binding, context, method, params)
        self.hooks = context.check_cancelled, context.check_final_request, context.check_final_job
        self.lifetime, self.owner = _owner(context)
        self.lifetime_facts = None if self.lifetime is None else (self.lifetime.connection, self.lifetime.delivered,
                                                                self.lifetime.rejected, self.lifetime.deadline)
        self.connection_events = None if self.owner is None else (self.owner.disconnected, self.owner.background_active)
        self.store, self.generation = _store_facts(context.state)
        self.deadline = time.monotonic() + self.parameters.get("time_limit_seconds", 300.)
        self.cached = None
        self.file_root = None
        if method in current_pixels_contract.METHOD_MODES:
            key = self.parameters["expected_target_fingerprint" if method == METHODS[1] else "expected_recovery_fingerprint"]
            cached = _PLANS.get(key)
            if (type(cached) is not _CachedPlan or cached.registration is not self.binding or cached.runtime is not self.runtime
                    or cached.registry is not context.registry or cached.owner is not self.owner
                    or cached.store is not self.store or cached.generation != self.generation or cached.scope != self.scope
                    or time.monotonic() >= cached.expires):
                raise refused("PREVIEW_MISSING_STALE_OR_FOREIGN")
            self.cached = cached
            self.file_root = json.loads(cached.raw)["files"]["approved_root"]
        self.authorized, self.used, self.bound = False, False, None
        self.capture = self.file_plan = None
        self.first_full_raw = None
        self.gate_context = context
        verifier_type = jobs.PreparedJobCallbacks
        verifier = _static(verifier_type, "verify")
        self.callback_verifier = verifier_type, verifier, _function_facts(verifier), verifier.__kwdefaults__
        self.callbacks = None
        self.check_job_callbacks()
        self.callbacks = jobs.PreparedJobCallbacks.capture(context, origin=self)
        self._stop(context)
        self.witness = self._witness()
        if self.cached is not None and _plain(json.loads(self.cached.raw)["identity_witness"]) != self.witness:
            raise refused("CACHED_NATIVE_IDENTITY_WITNESS_CHANGED")
        # The registry's later modifying prepare may initialize this store.
        # Do it explicitly only after our own actual current grants succeed.
        self.authorize()
        if self.store is None:
            get_task_plans(context.state)
            self.store, self.generation = _store_facts(context.state)
        try:
            root = self.approved_root()
            if method in METHODS[:2]:
                self.file_plan = current_pixels_files.freeze_backup_plan(self.parameters["backup_directory"],
                    self.parameters["backup_prefix"], root, self.parameters["retain_event_journal"], self.authorize)
            else:
                self.file_plan = current_pixels_files.freeze_recovery_plan(self.parameters["backup_manifest_path"], root, self.authorize)
            self.refresh_capture(context)
        except BaseException:
            self.capture = None
            self.callbacks = None
            raise
        self._sealed = True

    def check_job_callbacks(self):
        """Pure source/service identities; never permissions, native or paths."""
        binding, runtime = _entry(self.context.registry)
        _owner_type, function, _facts, keywords = self.callback_verifier
        if (type(keywords) is not dict or function.__kwdefaults__ is not keywords
                or len(keywords) != 4 or any(type(key) is not str for key in keywords)
                or set(keywords) != {"context", "job", "callbacks", "work"}
                or keywords["context"] is not None or keywords["job"] is not None
                or keywords["callbacks"] is not True or keywords["work"] is not True):
            raise refused("SHARED_VERIFIER_KEYWORDS_CHANGED")
        if (binding is not self.binding or runtime is not self.runtime or _checkpoint_parameters(self.params) != self.parameter_facts
                or _plain(self.parameters) != self.normalized_facts):
            raise refused("ORIGIN_OR_PARAMETERS_CHANGED")
        for name, service in self.services:
            if getattr(self.context, name) is not service or (name != "evidence" and vars(runtime).get(name) is not service):
                raise refused("RUNTIME_SERVICE_CHANGED")
        if (self.context.check_cancelled is not self.hooks[0] or self.context.check_final_request is not self.hooks[1]
                or self.context.check_final_job is not self.hooks[2]):
            raise refused("REQUEST_HOOK_CHANGED")
        if self.request_hooks is not None:
            current = _queued_facts(binding, self.context, self.method, self.params)
            before = self.request_hooks
            if current[0] is not before[0] or current[2] is not before[2] or current[3] is not before[3] or current[4] is not before[4] or current[5] is not before[5]:
                raise refused("REQUEST_OWNER_CHANGED")
        if self.context.request_lifecycle is not self.lifetime:
            raise refused("REQUEST_LIFETIME_CHANGED")
        if self.lifetime is not None and any(actual is not expected for actual, expected in zip(
                (self.lifetime.connection, self.lifetime.delivered, self.lifetime.rejected, self.lifetime.deadline), self.lifetime_facts, strict=True)):
            raise refused("REQUEST_LIFETIME_FIELDS_CHANGED")
        if self.owner is not None and (self.owner.disconnected is not self.connection_events[0]
                                       or self.owner.background_active is not self.connection_events[1]):
            raise refused("CONNECTION_EVENTS_CHANGED")
        store, generation = _store_facts(self.context.state)
        if store is not self.store or generation != self.generation:
            raise refused("PLAN_GENERATION_CHANGED")

    def _witness(self):
        context = self.gate_context
        self._stop(context)
        bpy = require_blender()
        return _plain({"context": _context_witness(bpy), "data": self.binding.graph.identity_witness(
            bpy, self.parameters.get("image_name"), self.parameters["snapshot_name"], self.parameters["affected_materials"],
            check=lambda: self._stop(context))})

    def _stop(self, context):
        if self.callbacks is not None:
            # The canonical shared verifier invokes this same retained source
            # check after its service/callback checks; do not repeat it twice.
            owner, function, facts, keywords = self.callback_verifier
            if (vars(jobs).get("PreparedJobCallbacks") is not owner or type(self.callbacks) is not owner
                    or _static(owner, "verify") is not function or not _function_matches(function, facts)):
                raise refused("SHARED_VERIFIER_CHANGED")
            if (type(keywords) is not dict or function.__kwdefaults__ is not keywords
                    or len(keywords) != 4 or any(type(key) is not str for key in keywords)
                    or set(keywords) != {"context", "job", "callbacks", "work"}
                    or keywords["context"] is not None or keywords["job"] is not None
                    or keywords["callbacks"] is not True or keywords["work"] is not True):
                raise refused("SHARED_VERIFIER_KEYWORDS_CHANGED")
            function(self.callbacks, context=context, job=self.callbacks.job)
        else:
            self.check_job_callbacks()
        if context is not self.context:
            self.check_worker_context(context)
        elif self.bound is not None and not self.bound.active:
            raise refused("REQUEST_ADMISSION_NO_LONGER_ACTIVE")
        lifetime = context.request_lifecycle
        if lifetime is not None:
            RequestLifetime.check(lifetime)
        if time.monotonic() >= self.deadline:
            raise BridgeError("TIMEOUT", "Current-pixel request/job deadline expired.")
        flags = context.state.snapshot()
        if flags["paused"] or flags["emergency_stopped"]:
            raise BridgeError("EMERGENCY_STOPPED" if flags["emergency_stopped"] else "AGENT_PAUSED", "Current-pixel lifecycle is stopped.")
        if "materials" not in context.registry.enabled_toolsets:
            raise BridgeError("TOOLSET_DISABLED", "The materials toolset is disabled.")
        if context is self.context and context.check_final_request is not None:
            context.check_final_request()
        elif context is not self.context:
            context.check_final_job()

    def authorize(self, context=None):
        context = self.context if context is None else context
        if context is not self.context:
            self.check_worker_context(context)
        self._stop(context)
        object.__setattr__(self, "gate_context", context)
        context.require(*REQUIRED)
        # No live source-method lookup after a provider until the retained
        # shared verifier has checked the source-check slot and all origins.
        owner, function, facts, keywords = self.callback_verifier
        if (vars(jobs).get("PreparedJobCallbacks") is not owner or type(self.callbacks) is not owner
                or _static(owner, "verify") is not function or not _function_matches(function, facts)):
            raise refused("SHARED_VERIFIER_CHANGED")
        if (type(keywords) is not dict or function.__kwdefaults__ is not keywords
                or len(keywords) != 4 or any(type(key) is not str for key in keywords)
                or set(keywords) != {"context", "job", "callbacks", "work"}
                or keywords["context"] is not None or keywords["job"] is not None
                or keywords["callbacks"] is not True or keywords["work"] is not True):
            raise refused("SHARED_VERIFIER_KEYWORDS_CHANGED")
        function(self.callbacks, context=context, job=self.callbacks.job)
        if self._witness() != self.witness:
            raise refused("IDENTITY_OR_CONTEXT_WITNESS_CHANGED")
        self._stop(context)
        if self.file_root is not None and self._approved_root_value() != self.file_root:
            raise refused("APPROVED_TEXTURE_ROOT_CHANGED")
        object.__setattr__(self, "authorized", True)
        object.__setattr__(self, "gate_context", context)

    def _approved_root_value(self):
        prefs = get_preferences()
        raw = None if prefs is None else prefs.texture_directory
        if type(raw) is not str or not raw or len(raw.encode("utf-8")) > 4096 or any(ord(char) < 32 for char in raw):
            raise refused("APPROVED_TEXTURE_ROOT_REQUIRED")
        return raw

    def approved_root(self):
        """Bind the real locally approved folder only after current grants."""
        self.authorize()
        raw = self._approved_root_value()
        if self.file_root is not None and raw != self.file_root:
            raise refused("APPROVED_TEXTURE_ROOT_CHANGED")
        object.__setattr__(self, "file_root", raw)
        return raw

    def check_after_read(self):
        self.check_job_callbacks()
        if self._witness() != self.witness:
            raise refused("IDENTITY_OR_CONTEXT_WITNESS_CHANGED")
        self._stop(self.context)
        if self.first_full_raw is not None:
            self.refresh_capture(self.context)

    def __call__(self):
        self.authorize()

    def bind_checkpoint(self, binding):
        if self.bound is not None or binding.context is not self.context or binding.spec is not self.spec or binding.params is not self.params:
            raise refused("ADMISSION_BINDING_CHANGED")
        object.__setattr__(self, "bound", binding)

        def release():
            # No native, filesystem or provider cleanup after the final read.
            object.__setattr__(self, "capture", None)
            if self.spec.modifies and (sys.exc_info()[0] is not None or not self.used):
                control = self.callbacks
                lifetime = None if control is None else control.lifetime
                if type(lifetime) is RequestLifetime:
                    threading.Event.set(lifetime.rejected)
        return release

    def enter(self):
        if self.used or self.bound is None or not self.bound.active or self.context.checkpoint_admission is not self.bound:
            raise refused("ADMISSION_NOT_CURRENT")
        self.authorize()
        self.refresh_capture(self.context)
        object.__setattr__(self, "used", True)
        if self.spec.modifies:
            self.context.checkpoint_finalization_owner = self.context.checkpoint_call_id
        return self

    def check_worker_context(self, context):
        self.check_job_callbacks()
        control = self.callbacks
        job = None if control is None else control.job
        if (type(context) is not ToolContext or job is None or context.request_lifecycle is not job.lifetime
                or context.check_final_request is not None or type(job) is not jobs.GuardedPreparedPaintJob):
            raise refused("CANONICAL_WORKER_CONTEXT_REQUIRED")
        for name, service in self.services:
            if getattr(context, name) is not service:
                raise refused("WORKER_SERVICE_CHANGED")
        code = inspect.getattr_static(jobs.PaintJobs, "_context").__code__
        for name, called in (("check_cancelled", "_check"), ("check_final_job", "_lifetime_check")):
            function = getattr(context, name)
            allowed = tuple(value for value in code.co_consts if type(value) is CodeType and value.co_names == (called,))
            if (type(function) is not FunctionType or function.__code__ not in allowed or function.__globals__ is not vars(jobs)
                    or function.__defaults__ is not None or function.__kwdefaults__ is not None):
                raise refused("WORKER_HOOK_CHANGED")
            cells = dict(zip(function.__code__.co_freevars, (cell.cell_contents for cell in function.__closure__ or ()), strict=True))
            if cells.get("context") is not context or cells.get("job") is not job or cells.get("self") is not self.context.jobs:
                raise refused("WORKER_HOOK_OWNER_CHANGED")

    def _summary(self, capture, plan):
        self.check_job_callbacks()
        graph_type = vars(self.binding.graph).get("GraphCapture")
        if type(capture) is not graph_type or type(plan) is not current_pixels_files.BackupPlan:
            raise refused("CONCRETE_CAPTURE_AND_PLAN_REQUIRED")
        summary = inspect.getattr_static(graph_type, "summary")(capture)
        if type(summary) is not dict:
            raise refused("PLAIN_GRAPH_SUMMARY_REQUIRED")
        for name in ("native_graph_sha256", "portable_graph_sha256", "consumer_graph_sha256"):
            value = summary.get(name)
            if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise refused("COMPLETE_GRAPH_DIGEST_REQUIRED")
        for name in ("full_native_prefix_sha256", "full_portable_prefix_sha256"):
            value = summary.get(name)
            if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise refused("COMPLETE_PREFIX_DIGEST_REQUIRED")
        if self.file_root is None or plan.approved_root != self.file_root:
            raise refused("CAPTURE_PLAN_ROOT_CHANGED")
        # Resource measurements are diagnostics, never a changing source
        # baseline. Complete native/prefix digests still cover all authored data.
        summary.pop("resource_facts", None)
        return {"graph": summary, "files": current_pixels_files.BackupPlan.summary(plan)}

    def _read_gate(self):
        self._stop(self.gate_context)
        if self._approved_root_value() != self.file_root:
            raise refused("APPROVED_TEXTURE_ROOT_CHANGED")
        if self._witness() != self.witness:
            raise refused("IDENTITY_OR_CONTEXT_WITNESS_CHANGED")

    def refresh_capture(self, context=None, *, expected_prefix=None, lifecycle_record=_MISSING):
        """Provider-free complete comparison after the caller's current grants.

        Fresh OS measurements precede every potentially large native capture.
        The expected prefix is internal driver state, never request parameters.
        """
        context = self.context if context is None else context
        if context is not self.context:
            self.check_worker_context(context)
        object.__setattr__(self, "gate_context", context)
        if not self.authorized or self.file_plan is None:
            raise refused("AUTHORIZED_RESOURCE_PLAN_REQUIRED")
        self._read_gate()
        self.file_plan.check(self._read_gate)
        self._read_gate()
        available_memory = _available_memory()
        self._read_gate()
        available_disk = shutil.disk_usage(self.file_plan.parent).free
        self._read_gate()
        if lifecycle_record is _MISSING:
            if self.method in METHODS[:2]:
                lifecycle_record = None
            else:
                bpy = require_blender()
                helper = bpy.data.images.get(self.parameters["snapshot_name"])
                if helper is None or helper.has_data is not True:
                    raise refused("TARGET_BUFFER_UNLOADED")
                lifecycle_record = self.binding.graph.validate_lifecycle_record(helper.get(self.binding.graph.LIFECYCLE_KEY))
        current = self.binding.graph.capture_graph(require_blender(), self.parameters.get("image_name"),
            self.parameters["snapshot_name"], self.parameters["affected_materials"], check=self._read_gate,
            available_memory_bytes=available_memory, available_disk_bytes=available_disk, lifecycle_record=lifecycle_record)
        self._read_gate()
        if expected_prefix is None:
            self.compare_capture(current, self.file_plan)
        else:
            if (type(expected_prefix) is not str or len(expected_prefix) != 64
                    or any(char not in "0123456789abcdef" for char in expected_prefix)):
                raise refused("INTERNAL_EXPECTED_PREFIX_REQUIRED")
            initial = json.loads(self.first_full_raw)["graph"]
            observed = self._summary(current, self.file_plan)["graph"]
            if (observed["consumer_graph_sha256"] != initial["consumer_graph_sha256"]
                    or observed["native_identity_rows"] != initial["native_identity_rows"]
                    or observed["full_native_prefix_sha256"] != expected_prefix):
                raise refused("EXPECTED_NATIVE_PREFIX_CHANGED")
        object.__setattr__(self, "capture", current)
        return current

    def compare_capture(self, capture, plan):
        """Compare the original full start baseline after grants/preflight/read."""
        if not self.authorized:
            raise refused("CURRENT_GRANTS_REQUIRED")
        current = self._summary(capture, plan)
        raw = _plain(current)
        if self.cached is not None:
            expected = json.loads(self.cached.raw)
            if raw != _plain({"graph": expected["graph"], "files": expected["files"]}):
                raise refused("FULL_PREVIEW_BASELINE_CHANGED")
        if self.first_full_raw is not None and raw != self.first_full_raw:
            raise refused("FULL_SOURCE_REBASE_REFUSED")
        object.__setattr__(self, "first_full_raw", raw)
        return current

    def cache_preview(self, capture, plan, domain_facts=None):
        if self.method not in {METHODS[0], METHODS[2]} or not self.authorized:
            raise refused("AUTHORIZED_PREVIEW_REQUIRED")
        current = self.compare_capture(capture, plan)
        store, generation = _store_facts(self.context.state)
        if store is None or store is not self.store or generation != self.generation:
            raise refused("AUTHORIZED_PLAN_STORE_REQUIRED")
        data = {**current, "domain": {} if domain_facts is None else domain_facts,
                "identity_witness": json.loads(self.witness),
                "runtime_nonce": self.binding.nonce, "scope": json.loads(self.scope)}
        raw = _plain(data)
        key = hashlib.sha256(raw).hexdigest()
        now = time.monotonic()
        for identifier, old in tuple(_PLANS.items()):
            if now >= old.expires:
                _PLANS.pop(identifier)
        while len(_PLANS) >= MAX_PLANS:
            _PLANS.popitem(last=False)
        _PLANS[key] = _CachedPlan(self.binding, self.runtime, self.context.registry, self.owner,
                                  store, generation, self.scope, raw, now + PLAN_SECONDS)
        return {"fingerprint": key, "expires_in_seconds": PLAN_SECONDS, "baseline_established_after_authorization": True,
                "first_authorization_pixel_only_change_detection": False, "preview_mutation_performed": False}

    def preview_data(self):
        if self.cached is None:
            raise refused("CACHED_START_PREVIEW_REQUIRED")
        return json.loads(self.cached.raw)
