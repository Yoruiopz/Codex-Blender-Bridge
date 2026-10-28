# SPDX-License-Identifier: GPL-3.0-or-later
"""Retained canonical save intent; no later source/protection rebase."""
from __future__ import annotations

import hashlib
import importlib
import math
import re
import sys
import time
from _thread import LockType
from types import CodeType, FunctionType, MethodType

from . import command_queue as _queue_module
from . import executor as _executor_module
from . import protocol as _protocol_module
from .errors import BridgeError, ErrorCode, invalid_argument
from .geometry_preview_source import semantic
from .native_save_policy import NativeSaveGrant
from .native_save_profile import (
    ProfileRefused,
    Projection,
    bind_resource_directory,
    canonical,
    capture,
)
from .permissions import Permission
from .preferences import get_preferences
from .request_lifecycle import RequestLifetime
from .state import BridgeState
from .task_plans import TaskPlanStore, get_task_plans
from .tool_registry import ToolRegistry, _checkpoint_parameters, check_final_mutation
from .utils import require_blender

PREVIEW, START = "project.native_save_preview", "project.native_save_start"
REQUIRED = (Permission.INSPECT_SCENE, Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES,
            Permission.NATIVE_SAVE_EFFECTS)
BUILDS = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}
SERVICES = ("state", "registry", "permissions", "checkpoints", "jobs")
HOOKS = ("check_final_request", "check_final_job", "check_cancelled")
_QUEUED_REQUEST = _queue_module.QueuedRequest
_QUEUED_CHECK = _QUEUED_REQUEST.check_active
_QUEUED_CHECK_CODE = _QUEUED_CHECK.__code__
_QUEUE_ERROR, _QUEUE_ERROR_CODE = _queue_module.BridgeError, _queue_module.ErrorCode
_QUEUE_TIME, _QUEUE_MONOTONIC = _queue_module.time, _queue_module.time.monotonic
_REQUEST = _protocol_module.Request
_EXECUTOR = _executor_module.MainThreadExecutor
_EXECUTOR_INVOKE = _EXECUTOR._invoke_owned
_EXECUTOR_INVOKE_CODE = _EXECUTOR_INVOKE.__code__
_FINAL_REQUEST_CODES = tuple(code for code in _EXECUTOR_INVOKE_CODE.co_consts
                             if type(code) is CodeType and code.co_freevars == ("queued_owner",))


def initial_dependencies(registry, _params):
    """Pure canonical-runtime policy classification before admission/providers.

    This existing registry hook deliberately does not create a runtime/store,
    invoke the permission provider, or access Blender or the filesystem.
    """
    runtime = _runtime._RUNTIME
    runtime_class = _runtime._CANONICAL_RUNTIME_CLASS
    if (initial_dependencies is not _initial_dependencies
            or initial_dependencies.__code__ is not _initial_dependencies_code
            or runtime_class is None or _runtime.BridgeRuntime is not runtime_class
            or type(runtime) is not runtime_class
            or runtime_class.__init__.__code__ is not _runtime._RUNTIME_CONSTRUCTOR_CODE
            or type(registry) is not ToolRegistry
            or vars(runtime).get("registry") is not registry
            or vars(runtime).get("_registered") is not True):
        raise refused("CANONICAL_SAVE_CLASSIFICATION_REQUIRED")
    state = vars(runtime).get("state")
    if type(state) is not BridgeState:
        raise refused("CANONICAL_SAVE_STATE_REQUIRED")
    store = vars(state).get("_artist_task_plans")
    if store is not None and type(store) is not TaskPlanStore:
        raise refused("CANONICAL_SAVE_PLAN_STORE_REQUIRED")
    if store is not None and vars(store).get("protection") is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                          "Native save does not admit enforced protected scope; it remains enforced.",
                          {"scope_complete": False, "protected_scope_enforced": True,
                           "execution_started": False, "native_save_invoked": False,
                           "bridge_file_writes": False, "initial_policy_classification": True})
    return ()


_initial_dependencies = initial_dependencies
_initial_dependencies_code = initial_dependencies.__code__


def _queued_hook_signature(context, value):
    """Authenticate the executor's current bound queue hook without invoking it.

    These facts belong to one entry request. They are not a source fingerprint
    or authority shared between preview A, start B and subsequent worker turns.
    """
    owner, function = value.__self__, value.__func__
    queue_globals, executor_globals = vars(_queue_module), vars(_executor_module)
    if (type(owner) is not _QUEUED_REQUEST or function is not _QUEUED_CHECK
            or queue_globals.get("QueuedRequest") is not _QUEUED_REQUEST
            or vars(_QUEUED_REQUEST).get("check_active") is not _QUEUED_CHECK
            or _QUEUED_CHECK.__code__ is not _QUEUED_CHECK_CODE
            or _QUEUED_CHECK.__globals__ is not queue_globals
            or _QUEUED_CHECK.__defaults__ is not None or _QUEUED_CHECK.__kwdefaults__ is not None
            or _QUEUED_CHECK.__closure__ is not None
            or queue_globals.get("time") is not _QUEUE_TIME
            or vars(_QUEUE_TIME).get("monotonic") is not _QUEUE_MONOTONIC
            or queue_globals.get("BridgeError") is not _QUEUE_ERROR
            or queue_globals.get("ErrorCode") is not _QUEUE_ERROR_CODE
            or executor_globals.get("MainThreadExecutor") is not _EXECUTOR
            or executor_globals.get("QueuedRequest") is not _QUEUED_REQUEST
            or vars(_EXECUTOR).get("_invoke_owned") is not _EXECUTOR_INVOKE
            or _EXECUTOR_INVOKE.__code__ is not _EXECUTOR_INVOKE_CODE
            or _EXECUTOR_INVOKE.__globals__ is not executor_globals
            or _protocol_module.Request is not _REQUEST
            or type(owner.request) is not _REQUEST
            or owner.request._lifecycle is not context.request_lifecycle
            or type(owner.request._lifecycle) is not RequestLifetime
            or type(owner.request.id) is not str or type(context.request_id) is not str
            or owner.request.id != context.request_id
            or type(owner._lock) is not LockType
            or type(owner.deadline) is not float or not math.isfinite(owner.deadline)):
        raise refused("CANONICAL_QUEUED_HOOK_REQUIRED")
    final = context.check_final_request
    if (type(final) is not FunctionType or len(_FINAL_REQUEST_CODES) != 1
            or final.__code__ is not _FINAL_REQUEST_CODES[0]
            or final.__globals__ is not executor_globals
            or final.__defaults__ is not None or final.__kwdefaults__ is not None
            or final.__closure__ is None or len(final.__closure__) != 1):
        raise refused("CANONICAL_QUEUED_FINAL_HOOK_REQUIRED")
    try:
        final_owner = final.__closure__[0].cell_contents
    except ValueError as cause:
        raise refused("CANONICAL_QUEUED_FINAL_HOOK_REQUIRED") from cause
    if final_owner is not owner:
        raise refused("CANONICAL_QUEUED_FINAL_HOOK_REQUIRED")
    return (owner, function, _QUEUED_CHECK_CODE, owner.request, owner.request._lifecycle,
            owner._lock, owner.deadline, final, final.__code__, final.__closure__[0])


def _hook_signature(context, name, value):
    if value is None:
        return None
    if type(value) is FunctionType:
        return value.__code__
    if name == "check_cancelled" and type(value) is MethodType:
        return _queued_hook_signature(context, value)
    raise refused("CALLER_HOOK_UNSUPPORTED")


def hook_facts(context):
    return tuple((name, value, _hook_signature(context, name, value))
                 for name in HOOKS for value in (getattr(context, name),))


def hooks_match(context, original):
    for name, value, signature in original:
        if getattr(context, name) is not value:
            return False
        current = _hook_signature(context, name, value)
        if type(signature) is tuple:
            if type(current) is not tuple or len(current) != len(signature) or any(
                    actual is not expected for actual, expected in zip(current, signature, strict=True)):
                return False
        elif current is not signature:
            return False
    return True


def refused(reason, *, started=False):
    return BridgeError(ErrorCode.OPERATION_FAILED, "Native save intent is unavailable or stale.",
                       {"reason": reason, "execution_started": started, "verification_required": True})


def stop_gate(context, lifetime, deadline):
    RequestLifetime.check(lifetime)
    if time.monotonic() >= deadline:
        raise BridgeError(ErrorCode.TIMEOUT, "Native save deadline expired; inspect retained file effects.")
    flags = context.state.snapshot()
    if flags["emergency_stopped"] or flags["paused"]:
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags["emergency_stopped"] else ErrorCode.AGENT_PAUSED,
                          "Native save stopped; status and cancellation remain available.")
    if context.check_final_request is not None:
        context.check_final_request()


def qualify_provider(context):
    from .native_save_jobs import NativeSaveJobs

    if (_runtime.native_save_permission_provider_intact is not _provider_guard
            or _provider_guard.__code__ is not _provider_guard_code
            or not _provider_guard()
            or _runtime._RUNTIME is None or _runtime._RUNTIME.permissions is not context.permissions
            or _runtime._RUNTIME.registry is not context.registry
            or _runtime._RUNTIME.state is not context.state
            or _runtime._RUNTIME.checkpoints is not context.checkpoints
            or _runtime._RUNTIME.jobs is not context.jobs
            or type(context.jobs) is not NativeSaveJobs
            or context.jobs.native_save_policy is not _runtime._RUNTIME.native_save_policy):
        raise refused("CANONICAL_PERMISSION_PROVIDER_REQUIRED")


def options():
    bpy, prefs = require_blender(), get_preferences()
    if prefs is None:
        raise refused("PREFERENCES_UNAVAILABLE")
    paths = bpy.context.preferences.filepaths
    values = (prefs.project_directory, paths.save_version, paths.file_preview_type, bpy.data.use_autopack)
    if type(values[0]) is not str or type(values[1]) is not int or not 0 <= values[1] <= 3:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native save requires a local Approved Project Folder and backup count 0..3.")
    if values[2] != "NONE" or values[3] is not False:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Set native file thumbnails to NONE and disable automatic packing locally for this initial save profile.")
    return values


def snapshot(resource_directory=None):
    try:
        return capture(require_blender().data, resource_directory=resource_directory)
    except (ProfileRefused, AttributeError, TypeError, ValueError, RuntimeError) as cause:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The current project is outside the declared native save profile.",
                          {"reason": str(cause)[:160], "profile": "stock_native_project_v1"}) from cause


def parameters(params, method):
    if type(params) is not dict:
        raise invalid_argument("Native save requires plain typed parameters.")
    keys = {"mode", "filepath", "overwrite_policy"}
    if method == START:
        keys |= {"preview_id", "expected_fingerprint", "accepted_losses", "time_limit_seconds"}
    if set(params) - keys or not {"mode", "filepath", "overwrite_policy"} <= set(params):
        raise invalid_argument("Native save arguments are missing or unknown.")
    if type(params["mode"]) is not str or params["mode"] not in {"COPY_NEW", "SAVE_CURRENT", "SAVE_AS"}:
        raise invalid_argument("Select COPY_NEW, SAVE_CURRENT or SAVE_AS.")
    if type(params["overwrite_policy"]) is not str or params["overwrite_policy"] not in {
        "NO_CLOBBER", "NATIVE_NEW_EXPECTED", "NATIVE_REPLACE_EXPECTED"
    }:
        raise invalid_argument("Select an explicit native overwrite policy.")
    path = params["filepath"]
    if type(path) is not str or not 0 < len(path.encode()) <= 4096 or any(ord(c) < 32 for c in path):
        raise invalid_argument("Native save requires an exact absolute .blend path.")
    if method == START:
        if type(params.get("preview_id")) is not str or not re.fullmatch(r"native_save_[0-9a-f]{32}", params["preview_id"]):
            raise invalid_argument("Use an exact session native-save preview ID.")
        if type(params.get("expected_fingerprint")) is not str or not re.fullmatch(r"[0-9a-f]{64}", params["expected_fingerprint"]):
            raise invalid_argument("Repeat the exact preview fingerprint.")
        losses = params.get("accepted_losses")
        if type(losses) is not list or len(losses) > 129 or any(type(v) is not str or len(v.encode()) > 1024 for v in losses):
            raise invalid_argument("Repeat the bounded required accepted_losses list exactly.")
        limit = params.get("time_limit_seconds", 120)
        if type(limit) is not int or not 1 <= limit <= 300:
            raise invalid_argument("time_limit_seconds must be an integer from 1 through 300.")


class SaveOrigin:
    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise refused("ORIGIN_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise refused("ORIGIN_IMMUTABLE")

    def __init__(self, context, params, method, handler):
        parameters(params, method)
        self.context, self.params, self.method = context, params, method
        self.mode, self.target, self.overwrite = params["mode"], params["filepath"], params["overwrite_policy"]
        self.facts = _checkpoint_parameters(params)
        self.registry, self.spec = context.registry, context.registry.get(method)
        from .tools.native_save import preview_admission, scope, start_admission

        if (self.spec.handler is not handler or not self.spec.modifies or self.spec.automatic_checkpoint
                or not self.spec.checkpoint_owns_finalization or not self.spec.exclusive_mutation
                or self.spec.batchable or self.spec.permissions != frozenset(REQUIRED)
                or self.spec.toolset != "core" or not self.spec.remote
                or self.spec.checkpoint_admission_factory is not (preview_admission if method == PREVIEW else start_admission)
                or self.spec.protected_scope_resolver is not scope
                or self.spec.checkpoint_parameter_dependencies is not _initial_dependencies):
            raise refused("SAVE_SPEC_CHANGED")
        self.services = tuple(getattr(context, name) for name in SERVICES)
        self.provider = context.permissions._source
        self.hooks = hook_facts(context)
        if type(context.check_cancelled) is MethodType:
            queued_request = context.check_cancelled.__self__.request
            if queued_request.method != method or queued_request.params is not params:
                raise refused("QUEUED_REQUEST_INTENT_CHANGED")
        self.manager = context.jobs
        qualify_provider(context)
        self.policy = self.manager.native_save_policy
        if type(self.policy) is not NativeSaveGrant:
            raise refused("NATIVE_GRANT_REQUIRED")
        try:
            self.statement = self.policy.statement()
        except ValueError as cause:
            raise BridgeError(ErrorCode.PERMISSION_DENIED, str(cause)) from cause
        self.store = get_task_plans(context.state)
        self.semantic, self.baseline, self.protection = semantic(self.store), self.store.baseline, self.store.protection
        if self.protection is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native save does not admit enforced protected scope; it remains enforced.")
        self.lifetime = context.request_lifecycle or RequestLifetime.local()
        if type(self.lifetime) is not RequestLifetime:
            raise refused("CANONICAL_REQUEST_LIFETIME_REQUIRED")
        self.request_slot = context.request_lifecycle
        self.lifetime_facts = (self.lifetime.connection, self.lifetime.delivered, self.lifetime.rejected, self.lifetime.deadline)
        self.events = None if self.lifetime.connection is None else (
            self.lifetime.connection.disconnected, self.lifetime.connection.background_active)
        self.deadline = time.monotonic() + params.get("time_limit_seconds", 120)
        entries = self.registry._mutation_interlock._entries
        if (len(entries) != 1 or entries[0].context is not context or entries[0].spec is not self.spec
                or entries[0].params is not params or self.registry.executing_mutators or self.store.executing_mutators):
            raise refused("CANONICAL_SAVE_ENTRY_REQUIRED")
        self.invocation = entries[0]
        self.revision = self.store.evidence_revision
        self.binding, self.used = None, False
        self.stopped = False
        stop_gate(context, self.lifetime, self.deadline)
        qualify_provider(context)
        # Admission factories run before registry.prepare_call. Authenticate
        # every live permission here before any Blender/source/options read,
        # then recheck identities/policy after that canonical provider returns.
        context.require(*REQUIRED)
        self.static(context)
        bpy = require_blender()
        if sys.platform != "linux" or BUILDS.get(tuple(bpy.app.version)) != bpy.app.build_hash.decode():
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native save is qualified only on the recorded official Linux builds.")
        self.build, self.version, self.binary = bpy.app.build_hash.decode(), bpy.app.version_string, bpy.app.binary_path
        self.preferences, self.filepath = options(), bpy.data.filepath
        if method == START:
            from .native_save_jobs import SavePreview

            preview = self.manager.native_save_previews.get(params["preview_id"])
            if type(preview) is not SavePreview or time.monotonic() >= preview.expires:
                raise invalid_argument("Native-save preview expired or is missing; create a new preview.")
            if type(preview.origin) is not SaveOrigin or preview.origin.registry is not self.registry:
                raise refused("PREVIEW_AUTHORITY_CHANGED")
            self.resource_directory = preview.origin.resource_directory
            if self.preferences != preview.origin.preferences:
                raise refused("APPROVED_RESOURCE_DIRECTORY_CHANGED")
        else:
            try:
                self.resource_directory = bind_resource_directory(self.preferences[0])
            except ProfileRefused as cause:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native save cannot verify the Approved Project Folder.",
                    {"reason": str(cause)[:160], "profile": "stock_native_project_v1"}) from cause
        started = time.perf_counter()
        self.projection = snapshot(self.resource_directory)
        self.projection_digest = self.projection.digest
        self.capture_ms = (time.perf_counter() - started) * 1000
        self.resource_checks = self.projection.resource_checks
        self.capture_observations = []
        self._sealed = True

    def static(self, context):
        if self.stopped:
            raise refused("SAVE_ORIGIN_TERMINATED")
        if context is self.context:
            if not hooks_match(context, self.hooks):
                raise refused("CALLER_HOOK_CHANGED")
        elif not self.manager.context_valid(context, self):
            raise refused("JOB_CALLER_HOOK_CHANGED")
        if context is self.context and context.request_lifecycle is not self.request_slot:
            raise refused("CALLER_LIFETIME_CHANGED")
        if (any(getattr(context, name) is not value for name, value in zip(SERVICES, self.services, strict=True))
                or context.permissions._source is not self.provider):
            raise refused("SERVICES_CHANGED")
        qualify_provider(context)
        if self.manager.native_save_policy is not self.policy:
            raise refused("NATIVE_GRANT_CHANGED")
        try:
            self.policy.check(self.statement)
        except ValueError as cause:
            raise BridgeError(ErrorCode.PERMISSION_DENIED, str(cause)) from cause
        if (get_task_plans(context.state) is not self.store or semantic(self.store) != self.semantic
                or self.store.baseline is not self.baseline or self.store.protection is not self.protection
                or self.protection is not None or self.registry.get(self.method) is not self.spec
                or _checkpoint_parameters(self.params) != self.facts):
            raise refused("SEMANTIC_OR_INTENT_CHANGED")
        if (any(actual is not expected for actual, expected in zip(
                (self.lifetime.connection, self.lifetime.delivered, self.lifetime.rejected), self.lifetime_facts[:3], strict=True))
                or self.lifetime.deadline != self.lifetime_facts[3]):
            raise refused("LIFETIME_CHANGED")
        if self.events is not None and (self.lifetime.connection.disconnected is not self.events[0]
                                       or self.lifetime.connection.background_active is not self.events[1]):
            raise refused("CONNECTION_EVENTS_CHANGED")
        stop_gate(context, self.lifetime, self.deadline)

    def source(self, *, after_native=False):
        if options() != self.preferences:
            raise refused("SAVE_OPTIONS_CHANGED")
        expected_path = self.target if after_native and self.mode == "SAVE_AS" else self.filepath
        if require_blender().data.filepath != expected_path:
            raise refused("CURRENT_FILEPATH_CHANGED")
        if len(self.capture_observations) >= 256:
            raise refused("SOURCE_COMPARISON_BUDGET")
        started = time.perf_counter()
        current = snapshot(self.resource_directory)
        self.capture_observations.append((time.perf_counter() - started) * 1000)
        if (current.raw != self.projection.raw or current.identities != self.projection.identities
                or (not after_native and current.driven_raw != self.projection.driven_raw)):
            raise refused("SOURCE_CHANGED")

    def observe_native_path(self, context):
        # Audit the completed operation's literal filepath before a revoked grant
        # blocks new actions. No provider, retained RNA dereference or source CAS.
        if (any(getattr(context, name) is not value for name, value in zip(SERVICES, self.services, strict=True))
                or get_task_plans(context.state) is not self.store or semantic(self.store) != self.semantic
                or self.registry.get(self.method) is not self.spec
                or not self.manager.context_valid(context, self)):
            raise refused("POST_NATIVE_PATH_UNOBSERVED")
        qualify_provider(context)
        return require_blender().data.filepath or None

    def check(self, context, *, source=True, after_native=False):
        self.static(context)
        if context is self.context and self.binding is not None and self.binding.active:
            if (self.registry._mutation_interlock._entries[-1] is not self.invocation
                    or context.checkpoint_admission is not self.binding):
                raise refused("SAVE_ENTRY_CHANGED")
        elif not self.manager.phase_valid(context, self):
            raise refused("CANONICAL_SAVE_PHASE_REQUIRED")
        context.require(*REQUIRED)
        self.static(context)
        if source:
            self.source(after_native=after_native)
        self.static(context)
        check_final_mutation(context, self.method, expected_spec=self.spec)

    def __call__(self):
        self.check(self.context)

    def check_after_read(self):
        self.static(self.context)
        self.source()
        self.static(self.context)
        check_final_mutation(self.context, self.method, expected_spec=self.spec)

    def bind_checkpoint(self, binding):
        object.__setattr__(self, "binding", binding)

        def cleanup():
            self.manager.complete_save_handoff(self, sys.exc_info()[0] is None and self.used)
        return cleanup

    def enter(self):
        if self.used or self.binding is None or not self.binding.active:
            raise refused("SAVE_ADMISSION_CONSUMED")
        self.check(self.context)
        object.__setattr__(self, "used", True)
        self.context.checkpoint_finalization_owner = self.context.checkpoint_call_id

    def fingerprint(self, file_plan):
        return hashlib.sha256(canonical([self.projection.digest, file_plan.fingerprint,
                                         list(self.preferences), self.statement.policy])).hexdigest()

    def release_buffer(self):
        object.__setattr__(self, "stopped", True)
        object.__setattr__(self, "projection", Projection(b"", (), (), self.projection.losses))


# Class definitions precede this import so both normal runtime-first and isolated
# source-module imports have the same canonical code pins without an import cycle.
_runtime = importlib.import_module(__package__ + ".runtime")
_provider_guard = _runtime.native_save_permission_provider_intact
_provider_guard_code = _provider_guard.__code__
