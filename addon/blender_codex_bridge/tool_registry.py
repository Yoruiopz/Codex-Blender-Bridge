"""Declarative Blender tool registry with permission and toolset gates."""

from __future__ import annotations

import logging
import math
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Protocol

from .checkpoint_completion import (
    check_marker_context,
    claim_binding_completion,
    claim_binding_marker_completion,
    native_push_consumer,
)
from .entry_effects import (
    annotate_entry_error,
    bind_entry_audit,
    current_entry_audit,
    mark_handler_entered,
)
from .errors import BridgeError, ErrorCode
from .operation_lease import ExclusiveMutationLease, InvocationPermit, MutationInterlock
from .permissions import Permission, PermissionManager
from .request_lifecycle import RequestLifetime
from .scene_job_reservations import INSPECTION_TURN_METHOD, TURN_METHOD, SceneJobReservations
from .state import BridgeState
from .task_plans import get_task_plans

ToolHandler = Callable[["ToolContext", Mapping[str, Any]], Any]
ProtectedScopeResolver = Callable[["ToolContext", Mapping[str, Any]], Mapping[str, Any]]
class CheckpointAdmissionGuard(Protocol):
    def __call__(self) -> None: ...
    def check_after_read(self) -> None:
        """Read only static native evidence, then pure final; no providers."""
        ...


CheckpointAdmissionFactory = Callable[["ToolContext", Mapping[str, Any]], CheckpointAdmissionGuard]
CheckpointParameterScope = Callable[["ToolRegistry", Mapping[str, Any]], bool]
CheckpointParameterDependencies = Callable[["ToolRegistry", Mapping[str, Any]], tuple["ToolSpec | None", ...]]
LOGGER = logging.getLogger(__name__)


def _checkpoint_parameters(raw: Any) -> Any:
    """Freeze bounded plain request data without custom Mapping/getter calls."""
    remaining = [4096, 65536]

    def visit(item: Any, depth: int = 0) -> Any:
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 8:
            raise ValueError
        kind = type(item)
        if item is None:
            return ("none",)
        if kind is bool:
            return ("bool", item)
        if kind is int:
            if item.bit_length() > 4096:
                raise ValueError
            return ("int", item)
        if kind is float:
            if not math.isfinite(item):
                raise BridgeError(ErrorCode.INVALID_ARGUMENT, "Numeric request parameters must be finite.",
                                  {"checkpoint_parameters_finite": False})
            return ("float", item.hex())
        if kind is str:
            remaining[1] -= len(item.encode("utf-8"))
            if len(item) > 4096 or remaining[1] < 0:
                raise ValueError
            return ("str", item)
        if kind is dict:
            if len(item) > remaining[0] or any(type(key) is not str for key in item):
                raise ValueError
            return ("dict", tuple((visit(key, depth + 1), visit(item[key], depth + 1)) for key in sorted(item)))
        if kind is list or kind is tuple:
            if len(item) > remaining[0]:
                raise ValueError
            return (kind.__name__, tuple(visit(child, depth + 1) for child in item))
        raise ValueError
    try:
        return visit(raw)
    except (ValueError, UnicodeError) as error:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission requires bounded plain request parameters.",
                          {"checkpoint_parameters_bounded": False}) from error


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    handler: ToolHandler
    permissions: frozenset[Permission]
    toolset: str
    modifies: bool
    description: str
    automatic_checkpoint: bool = True
    remote: bool = True
    batchable: bool = True
    record_history: bool = True
    protected_scope_resolver: ProtectedScopeResolver | None = None
    checkpoint_admission_factory: CheckpointAdmissionFactory | None = None
    checkpoint_parameter_scope: CheckpointParameterScope | None = None
    checkpoint_parameter_dependencies: CheckpointParameterDependencies | None = None
    checkpoint_owns_finalization: bool = False
    checkpoint_batch_reviewed: bool = False
    exclusive_mutation: bool = False

    def metadata(self, *, enabled: bool) -> dict[str, Any]:
        return {
            "name": self.name,
            "toolset": self.toolset,
            "description": self.description,
            "required_permissions": sorted(permission.value for permission in self.permissions),
            "modifies": self.modifies,
            "enabled": enabled,
            "remote": self.remote,
            "protected_scope_reviewed": self.protected_scope_resolver is not None,
        }


@dataclass(frozen=True, slots=True)
class _CheckpointEntryEvidence:
    parameters: Any
    dependencies: tuple[ToolSpec | None, ...]


@dataclass(slots=True)
class ToolContext:
    """Services supplied to a tool without exposing network internals."""

    state: BridgeState
    permissions: PermissionManager
    registry: ToolRegistry
    checkpoints: Any
    check_cancelled: Callable[[], None] | None = None
    evidence: Any = None
    jobs: Any = None
    glb_stage: Any = None
    glb_method: str = ""
    request_lifecycle: RequestLifetime | None = None
    request_id: str = ""
    # Set only by the scheduler: Events/deadline/toolset checks without calling
    # permission providers or Blender. Domains invoke this after live providers.
    check_final_job: Callable[[], None] | None = None
    # Set only for the canonical queued-request safe point by the executor.
    # Arbitrary check_cancelled callbacks may call providers and are not pure.
    check_final_request: Callable[[], None] | None = None
    # Per-context diagnostic receipt. Only actual handler entry increments it;
    # it is never a wire parameter or an authorization grant.
    handler_entries: int = 0
    checkpoint_admission: CheckpointAdmissionBinding | None = None
    checkpoint_call_id: object | None = None
    checkpoint_method: str | None = None
    checkpoint_params: Mapping[str, Any] | None = None
    checkpoint_finalization_owner: object | None = None
    # A final-gate binding, never authority for a new registry/executor entry.
    exclusive_mutation_lease: ExclusiveMutationLease | None = None
    artist_step_entry_captured: bool = False
    artist_step_entry: Any = None

    def require(self, *permissions: Permission) -> None:
        self.permissions.require(permissions)


@dataclass(slots=True)
class CheckpointAdmissionBinding:
    """Internal call identity; never a permission or wire-supplied profile."""

    context: ToolContext
    method: str
    params: Mapping[str, Any]
    call_id: object
    callback: Callable[[], None]
    frozen_params: Any = None
    readonly_callback: Callable[[], None] | None = None
    native_push_callback: Callable[[], None] | None = None
    registry: ToolRegistry | None = None
    spec: ToolSpec | None = None
    enclosing: tuple[Any, ...] | None = None
    active: bool = True
    stopped: BridgeError | None = None
    marker_write_callback: Callable[[Any], None] | None = None

    def matches(self, spec: ToolSpec, params: Mapping[str, Any], context: ToolContext) -> bool:
        return (self.active and self.context is context and self.registry is context.registry and self.spec is spec
                and self.method == spec.name and self.params is params
                and context.checkpoint_admission is self and context.checkpoint_call_id is self.call_id
                and context.checkpoint_method == self.method and context.checkpoint_params is self.params)

    def __call__(self) -> None:
        self._check(self.callback)

    def check_after_read(self) -> None:
        if self.readonly_callback is None:
            error = BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission has no reviewed read-only proof.",
                                {"checkpoint_admission_valid": False})
            self.stopped = error
            raise error
        self._check(self.readonly_callback)

    def after_native_push(self, event: Any = None) -> None:
        """Consume exact canonical completion before any domain hook."""
        if self.stopped is not None:
            raise self.stopped
        claim_binding_completion(self, event)
        def completed() -> None:
            if self.native_push_callback is not None:
                self.native_push_callback()
            if self.readonly_callback is not None:
                self.readonly_callback()
        self._check(completed)

    def after_marker_write(self, event: Any = None) -> None:
        """Receive only the opaque observation earned by a canonical stamp write."""
        if self.stopped is not None:
            raise self.stopped
        claim_binding_marker_completion(self, event)
        callback = self.marker_write_callback
        if callback is None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint marker consumer is unavailable.")
        self._check(lambda: callback(event))

    def _enclosing_after_read(self) -> None:
        if self.enclosing is None or self.enclosing[0] is None:
            return
        context = self.context
        current = (context.checkpoint_admission, context.checkpoint_call_id, context.checkpoint_method,
                   context.checkpoint_params, context.checkpoint_finalization_owner)
        try:
            (context.checkpoint_admission, context.checkpoint_call_id, context.checkpoint_method,
             context.checkpoint_params, context.checkpoint_finalization_owner) = self.enclosing
            self.enclosing[0].check_after_read()
        finally:
            (context.checkpoint_admission, context.checkpoint_call_id, context.checkpoint_method,
             context.checkpoint_params, context.checkpoint_finalization_owner) = current

    def _check(self, callback: Callable[[], None]) -> None:
        try:
            self.check_identity(self.method)
            callback()
            self.check_identity(self.method)
            self._enclosing_after_read()
            self.check_identity(self.method)
        except BridgeError as error:
            self._retain_enclosing_stop()
            self.stopped = error
            raise
        except Exception as cause:
            LOGGER.exception("Checkpoint admission callback failed")
            error = BridgeError(ErrorCode.OPERATION_FAILED, "Checkpoint admission could not be verified.",
                                {"checkpoint_admission_valid": False, "verification_required": True})
            self._retain_enclosing_stop()
            self.stopped = error
            raise error from cause

    def _retain_enclosing_stop(self) -> None:
        # A child provider can change the parent's closure and then deny the
        # child before its normal enclosing proof. Latch that parent drift
        # without replacing the child's exact primary authorization failure.
        try:
            self._enclosing_after_read()
        except BridgeError:
            return

    def check_identity(self, method: str) -> None:
        """Pure check, also used after domain providers/content comparisons."""
        if self.stopped is not None:
            raise self.stopped
        try:
            if method != self.method or not self.matches(self.context.registry.get(self.method), self.params, self.context):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission belongs to a different or completed call.",
                                  {"checkpoint_admission_valid": False})
            if _checkpoint_parameters(self.params) != self.frozen_params:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission parameters changed during the call.",
                                  {"checkpoint_parameters_unchanged": False})
        except BridgeError as error:
            self.stopped = error
            raise
        except Exception as cause:
            LOGGER.exception("Checkpoint admission identity could not be verified")
            error = BridgeError(ErrorCode.OPERATION_FAILED, "Checkpoint admission could not be verified.",
                                {"checkpoint_admission_valid": False, "verification_required": True})
            self.stopped = error
            raise error from cause


def check_final_mutation(context: ToolContext, method: str, *, allow_recovery: bool = False,
                         expected_spec: ToolSpec | None = None) -> None:
    """Pure final safe point after all providers and Blender content reads.

    The hooks are internal executor/scheduler services, never wire parameters.
    This function must not run permission providers, Blender APIs or arbitrary
    cancellation callbacks after a domain's compare-and-swap proof.
    Lifetime, identity and toolset checks also protect readonly handler entry;
    only an exact retained nonmodifying spec omits mutation pause/stop gates.
    """
    check_marker_context(context)
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    for name in ("check_final_request", "check_final_job"):
        hook = getattr(context, name, None)
        if hook is not None:
            hook()
    admission = getattr(context, "checkpoint_admission", None)
    if admission is not None:
        admission.check_identity(method)
        if expected_spec is None:
            expected_spec = admission.spec
    registry = getattr(context, "registry", None)
    modifies = True  # Raw mutation helpers retain conservative stop behavior.
    if registry is not None:
        spec = registry.get(method)
        if expected_spec is not None:
            if spec is not expected_spec:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Registered tool identity changed before handler entry.",
                                  {"checkpoint_parameters_unchanged": False})
            modifies = expected_spec.modifies
        if spec.toolset not in registry.enabled_toolsets:
            raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Mutation toolset was disabled before its next write.",
                              {"tool": method, "toolset": spec.toolset})
        check_owner = getattr(registry, "check_mutation_owner", None)
        if check_owner is not None:
            check_owner(spec, context)
    if not modifies:
        return
    flags = context.state.snapshot()
    recovery_override = allow_recovery and method in ToolRegistry.RECOVERY_TOOLS
    if flags.get("emergency_stopped") and not recovery_override:
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Mutation emergency-stopped before its next write.")
    if flags.get("paused") and not recovery_override:
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Mutation paused before its next write.")


class ToolRegistry:
    """Register, describe, enable, and dispatch structured tools."""

    CORE_TOOLSET = "core"
    RECOVERY_TOOLS = frozenset({"checkpoint.undo_last", "checkpoint.restore_last"})

    def __init__(self, *, enabled_toolsets: Iterable[str] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._toolsets: set[str] = {self.CORE_TOOLSET}
        self._enabled_toolsets: set[str] = {self.CORE_TOOLSET, *enabled_toolsets}
        # Registry lifetime spans project/state replacement. A new plan store
        # must not hide a handler that is still unwinding on Blender's thread.
        self._executing_mutators = 0
        self._mutation_interlock = MutationInterlock()
        self._scene_reservations = SceneJobReservations(self)

    @property
    def _exclusive_mutation_lease(self) -> ExclusiveMutationLease | None:
        return self._mutation_interlock.owner

    @_exclusive_mutation_lease.setter
    def _exclusive_mutation_lease(self, value: ExclusiveMutationLease | None) -> None:
        self._mutation_interlock.owner = value

    @property
    def active_exclusive_mutation(self) -> bool:
        return (self._mutation_interlock.owner is not None or self._mutation_interlock.invocation is not None
                or self._mutation_interlock.has_retained_exclusive_entry)

    @contextmanager
    def mutation_entry(self, spec: ToolSpec, params: Mapping[str, Any], context: ToolContext, *, _scene_turn: Any = None):
        self._scene_reservations.check_entry(spec, context, _scene_turn)
        with self._mutation_interlock.entry(self, spec, params, context) as permit:
            if _scene_turn is not None:
                self._scene_reservations.bind_invocation(_scene_turn, permit, params)
            yield permit

    def check_mutation_owner(self, spec: ToolSpec, context: ToolContext) -> None:
        self._mutation_interlock.check_owner(self, spec, context)
        if spec.name == TURN_METHOD:
            self._scene_reservations.check_turn(self._scene_reservations.current(context).token)
        elif spec.name == INSPECTION_TURN_METHOD:
            turn = self._scene_reservations.current_inspection(context)
            job = turn.owner.job
            context.jobs._inspection_record(job)
            binding = context.checkpoint_admission
            if binding is not None:
                # The retained entry guard checks only source/context/top-level
                # identities. Domain readback caches can change during a phase.
                if turn.binding is not binding or turn.inspection_entry_proof is None:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Inspection admission ownership changed.")
                function, code, namespace, defaults, keywords, cells, contents = turn.inspection_entry_proof
                if (type(function) is not type(lambda: None) or function.__code__ is not code
                        or function.__globals__ is not namespace or function.__defaults__ is not defaults
                        or function.__kwdefaults__ is not keywords or function.__closure__ is not cells
                        or len(cells or ()) != len(contents)
                        or any(actual is not cell or actual.cell_contents is not value
                               for actual, (cell, value) in zip(cells or (), contents, strict=True))):
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Inspection entry source changed.")
                function()
            flags = context.state.snapshot()
            if flags["emergency_stopped"]:
                raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Inspection emergency-stopped before its next read.")
            if flags["paused"] and not turn.check_only:
                raise BridgeError(ErrorCode.AGENT_PAUSED, "Inspection paused before its next read.")

    @property
    def executing_mutators(self) -> int:
        return self._executing_mutators

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        permissions: Iterable[Permission] = (),
        toolset: str = CORE_TOOLSET,
        modifies: bool = False,
        description: str = "",
        automatic_checkpoint: bool = True,
        remote: bool = True,
        batchable: bool = True,
        record_history: bool = True,
        protected_scope_resolver: ProtectedScopeResolver | None = None,
        checkpoint_admission_factory: CheckpointAdmissionFactory | None = None,
        checkpoint_parameter_scope: CheckpointParameterScope | None = None,
        checkpoint_parameter_dependencies: CheckpointParameterDependencies | None = None,
        checkpoint_owns_finalization: bool = False,
        checkpoint_batch_reviewed: bool = False,
        exclusive_mutation: bool = False,
    ) -> ToolSpec:
        if not name or "." not in name:
            raise ValueError("Tool names must be non-empty dotted identifiers.")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        if exclusive_mutation and not modifies:
            raise ValueError("Only modifying tools can request exclusive mutation ownership.")
        toolset = toolset.strip().lower()
        spec = ToolSpec(
            name=name,
            handler=handler,
            permissions=frozenset(permissions),
            toolset=toolset,
            modifies=modifies,
            description=description,
            automatic_checkpoint=automatic_checkpoint,
            remote=remote,
            batchable=batchable,
            record_history=record_history,
            protected_scope_resolver=protected_scope_resolver,
            checkpoint_admission_factory=checkpoint_admission_factory,
            checkpoint_parameter_scope=checkpoint_parameter_scope,
            checkpoint_parameter_dependencies=checkpoint_parameter_dependencies,
            checkpoint_owns_finalization=checkpoint_owns_finalization,
            checkpoint_batch_reviewed=checkpoint_batch_reviewed,
            exclusive_mutation=exclusive_mutation,
        )
        self._tools[name] = spec
        self._toolsets.add(toolset)
        return spec

    def tool(
        self,
        name: str,
        *,
        permissions: Iterable[Permission] = (),
        toolset: str = CORE_TOOLSET,
        modifies: bool = False,
        description: str = "",
        automatic_checkpoint: bool = True,
        remote: bool = True,
        batchable: bool = True,
        record_history: bool = True,
        protected_scope_resolver: ProtectedScopeResolver | None = None,
        checkpoint_admission_factory: CheckpointAdmissionFactory | None = None,
        checkpoint_parameter_scope: CheckpointParameterScope | None = None,
        checkpoint_parameter_dependencies: CheckpointParameterDependencies | None = None,
        checkpoint_owns_finalization: bool = False,
        checkpoint_batch_reviewed: bool = False,
        exclusive_mutation: bool = False,
    ) -> Callable[[ToolHandler], ToolHandler]:
        def decorator(handler: ToolHandler) -> ToolHandler:
            self.register(
                name,
                handler,
                permissions=permissions,
                toolset=toolset,
                modifies=modifies,
                description=description,
                automatic_checkpoint=automatic_checkpoint,
                remote=remote,
                batchable=batchable,
                record_history=record_history,
                protected_scope_resolver=protected_scope_resolver,
                checkpoint_admission_factory=checkpoint_admission_factory,
                checkpoint_parameter_scope=checkpoint_parameter_scope,
                checkpoint_parameter_dependencies=checkpoint_parameter_dependencies,
                checkpoint_owns_finalization=checkpoint_owns_finalization,
                checkpoint_batch_reviewed=checkpoint_batch_reviewed,
                exclusive_mutation=exclusive_mutation,
            )
            return handler

        return decorator

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise BridgeError(
                ErrorCode.METHOD_NOT_FOUND,
                f"Unknown Blender bridge method '{name}'.",
                {"available_methods": sorted(self._tools)},
            ) from exc

    def prepare(
        self,
        name: str,
        context: ToolContext,
        *,
        allow_recovery: bool = False,
    ) -> ToolSpec:
        spec = self.get(name)
        if not spec.remote and not allow_recovery and not self._scene_reservations.scheduled(spec, context):
            raise BridgeError(
                ErrorCode.METHOD_NOT_FOUND,
                f"Tool '{name}' is available only from Blender's local recovery UI.",
            )
        if spec.toolset not in self._enabled_toolsets:
            raise BridgeError(
                ErrorCode.TOOLSET_DISABLED,
                f"Toolset '{spec.toolset}' is disabled in Blender.",
                {"tool": name, "toolset": spec.toolset},
            )
        storage_entry = None
        if name == "mesh.attribute_storage_prepare_preview" and context.checkpoint_admission is not None:
            # Only the concrete fixture-local domain supplies this proof. Keep
            # it before the first provider: a new Gate in the handler would
            # otherwise adopt altered final hooks after generic code used them.
            from .tools.mesh_storage import _PreviewAdmission
            callback = context.checkpoint_admission.callback
            if type(callback) is _PreviewAdmission:
                storage_entry = callback.entry_proof
                storage_type, storage_len, storage_any, storage_zip = type, len, any, zip
                storage_function_type = type(lambda: None)
                storage_value_error = ValueError
                storage_failure = BridgeError(ErrorCode.NOT_IMPLEMENTED, "Storage preview entry source changed.",
                                              {"reason": "STORAGE_CONTEXT_CHANGED"})
        if context.checkpoint_admission is not None and name in {
                "mesh.attribute_storage_prepare_inspection_start", INSPECTION_TURN_METHOD}:
            from .scene_jobs import _InspectionAdmission, _InspectionTurnAdmission
            callback = context.checkpoint_admission.callback
            if type(callback) is _InspectionAdmission or type(callback) is _InspectionTurnAdmission:
                storage_entry = callback.entry_proof
                storage_type, storage_len, storage_any, storage_zip = type, len, any, zip
                storage_function_type = type(lambda: None)
                storage_value_error = ValueError
                storage_failure = BridgeError(ErrorCode.NOT_IMPLEMENTED, "Inspection entry source changed.",
                                              {"reason": "INSPECTION_CONTEXT_CHANGED"})
        if storage_entry is not None:
            def checked_storage_entry():
                function, code, namespace, defaults, keywords, cells, contents = storage_entry
                try:
                    if (storage_type(function) is not storage_function_type or function.__code__ is not code
                            or function.__globals__ is not namespace or function.__defaults__ is not defaults
                            or function.__kwdefaults__ is not keywords or function.__closure__ is not cells
                            or storage_len(cells or ()) != storage_len(contents)
                            or storage_any(actual is not cell or actual.cell_contents is not value
                                           for actual, (cell, value) in storage_zip(cells or (), contents, strict=True))):
                        raise storage_failure
                except storage_value_error:
                    raise storage_failure from None
                function()

            checked_storage_entry()
            if name != "mesh.attribute_storage_prepare_preview":
                context.checkpoint_admission.check_after_read()
        context.permissions.require(spec.permissions)
        if storage_entry is not None:
            checked_storage_entry()
        if self.get(name) is not spec:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Registered tool identity changed during permission validation.",
                              {"checkpoint_parameters_unchanged": False})
        if spec.toolset not in self._enabled_toolsets:
            raise BridgeError(
                ErrorCode.TOOLSET_DISABLED,
                f"Toolset '{spec.toolset}' was disabled during Blender permission validation.",
                {"tool": name, "toolset": spec.toolset},
            )
        runtime_state = context.state.snapshot()
        recovery_override = allow_recovery and name in self.RECOVERY_TOOLS
        if spec.modifies and runtime_state["emergency_stopped"] and not recovery_override:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Agent modifications are emergency-stopped.")
        if spec.modifies and runtime_state["paused"] and not recovery_override:
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Agent modifications are paused in Blender.")
        if spec.modifies and get_task_plans(context.state).protection is not None and spec.protected_scope_resolver is None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                              "This modifying tool has no reviewed protected-scope resolver; enforcement remains active.",
                              {"tool": name, "protected_scope_enforced": True, "scope_complete": False})
        return spec

    def prepare_call(self, name: str, params: Mapping[str, Any], context: ToolContext, *, allow_recovery: bool = False) -> ToolSpec:
        """Resolve reviewed live effects before checkpoints/handler entry."""
        spec = self.prepare(name, context, allow_recovery=allow_recovery)
        if spec.modifies and get_task_plans(context.state).protection is not None:
            assert spec.protected_scope_resolver is not None  # prepare fails closed
            resolved = spec.protected_scope_resolver(context, params)
            if resolved.get("scope_complete") is not True:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Protected mutation scope is incomplete; no handler is entered.",
                                  {"tool": name, "scope_complete": False, "protected_scope_enforced": True})
        return spec

    def checkpoint_parameter_entry(self, spec: ToolSpec, params: Mapping[str, Any]) -> tuple[ToolSpec, bool, _CheckpointEntryEvidence]:
        """Trusted pure classification before any entry callback or provider."""
        guarded = spec.checkpoint_admission_factory is not None or (
            spec.checkpoint_parameter_scope is not None and spec.checkpoint_parameter_scope(self, params))
        if type(guarded) is not bool:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint request scope did not provide a literal classification.")
        dependencies = () if spec.checkpoint_parameter_dependencies is None else spec.checkpoint_parameter_dependencies(self, params)
        if (type(dependencies) is not tuple or len(dependencies) > 4096
                or any(item is not None and not isinstance(item, ToolSpec) for item in dependencies)):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint request dependencies did not provide bounded registered tool identities.")
        return spec, guarded, _CheckpointEntryEvidence(_checkpoint_parameters(params) if guarded else None, dependencies)

    def check_checkpoint_parameter_entry(self, entry: tuple[ToolSpec, bool, _CheckpointEntryEvidence], params: Mapping[str, Any]) -> None:
        initial, guarded, frozen = entry
        current = self.get(initial.name)
        if current is not initial:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission parameters or guarded request scope changed during entry validation.",
                              {"checkpoint_parameters_unchanged": False})
        latest = self.checkpoint_parameter_entry(current, params)
        dependencies = latest[2].dependencies
        if (latest[1] != guarded or (guarded and latest[2].parameters != frozen.parameters)
                or len(dependencies) != len(frozen.dependencies)
                or any(before is not after for before, after in zip(frozen.dependencies, dependencies, strict=False))):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission parameters or guarded request scope changed during entry validation.",
                              {"checkpoint_parameters_unchanged": False})

    def dispatch(self, name: str, params: Mapping[str, Any], context: ToolContext) -> Any:
        with self.mutation_entry(self.get(name), params, context) as permit:
            return self._dispatch_owned(name, params, context, permit)

    def _dispatch_owned(self, name: str, params: Mapping[str, Any], context: ToolContext,
                        permit: InvocationPermit) -> Any:
        entry = self.checkpoint_parameter_entry(self.get(name), params)
        enclosing = context.checkpoint_admission
        if enclosing is not None:
            enclosing.check_after_read()
        self.check_admission_entry(entry[0], context)
        scope, captured, deferred = self._capture_admission(entry[0], params, context)
        try:
            if deferred is not None and name == "mesh.attribute_storage_prepare_inspection_start":
                # A failed private source/context proof cannot safely dispatch
                # the provider whose original identity it failed to establish.
                raise deferred
            spec = self.prepare_call(name, params, context)
            self.check_checkpoint_parameter_entry(entry, params)
            if deferred is not None:
                if enclosing is not None:
                    enclosing.check_after_read()
                raise deferred
            return self.invoke(spec, params, context, _permit=permit)
        except BridgeError as error:
            annotate_entry_error(error, current_entry_audit())
            raise
        finally:
            if captured:
                scope.__exit__(None, None, None)

    def check_admission_entry(self, spec: ToolSpec, context: ToolContext, *, allow_recovery: bool = False) -> None:
        """Pure spec/lifetime/pause gate before readonly factory capture."""
        if not spec.remote and not allow_recovery and not self._scene_reservations.scheduled(spec, context):
            raise BridgeError(ErrorCode.METHOD_NOT_FOUND, "This tool is available only from Blender's local recovery UI.")
        if spec.toolset not in self.enabled_toolsets:
            raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Toolset is disabled before admission capture.")
        if context.checkpoint_admission is None:
            check_final_mutation(context, spec.name, allow_recovery=allow_recovery, expected_spec=spec)

    def _capture_admission(self, spec: ToolSpec, params: Mapping[str, Any], context: ToolContext) -> tuple[Any, bool, BridgeError | None]:
        scope = self.checkpoint_admission(spec, params, context)
        try:
            scope.__enter__()
        except BridgeError as error:
            if spec.name in {"mesh.attribute_storage_prepare_inspection_start", INSPECTION_TURN_METHOD}:
                # The private read workflow has no safe provider to call after
                # its canonical source/context capture has failed.
                raise
            # Readonly factory diagnostics must not bypass coherent live
            # permission/cancellation denial precedence or expose private data.
            return scope, False, error
        return scope, True, None

    @contextmanager
    def checkpoint_admission(self, spec: ToolSpec, params: Mapping[str, Any], context: ToolContext) -> Iterator[CheckpointAdmissionBinding | None]:
        """Capture before entry providers; restore the enclosing call in all exits.

        A factory must only capture reviewed native static evidence. It must not
        call providers between a batch transition proof and its new baseline.
        The returned callback resolves providers and compares that frozen state.
        """
        previous = (context.checkpoint_admission, context.checkpoint_call_id, context.checkpoint_method,
                    context.checkpoint_params, context.checkpoint_finalization_owner)
        try:
            frozen_params = _checkpoint_parameters(params) if spec.checkpoint_admission_factory is not None else None
        except BridgeError as error:
            error.context["execution_started"] = False  # Factory/handler not entered.
            raise
        try:
            callback = spec.checkpoint_admission_factory(context, params) if spec.checkpoint_admission_factory is not None else None
        except BridgeError:
            raise
        except Exception as cause:
            LOGGER.exception("Checkpoint admission factory failed")
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Checkpoint admission could not be prepared.",
                              {"execution_started": False, "checkpoint_admission_valid": False,
                               "verification_required": True}) from cause
        if spec.checkpoint_admission_factory is not None and not callable(callback):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission factory did not provide a reviewed guard.",
                              {"checkpoint_admission_valid": False, "execution_started": False})
        try:
            readonly = None if callback is None else getattr(callback, "check_after_read", None)
            native_push = None if callback is None else getattr(callback, "after_native_push", None)
            marker_write = None if callback is None else getattr(callback, "after_marker_write", None)
        except Exception as cause:
            LOGGER.exception("Checkpoint read-only admission descriptor failed")
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Checkpoint read-only admission could not be prepared.",
                              {"execution_started": False, "checkpoint_admission_valid": False,
                               "verification_required": True}) from cause
        if callback is not None and not callable(readonly):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission factory did not provide a reviewed read-only proof.",
                              {"checkpoint_admission_valid": False, "execution_started": False})
        if native_push is not None and not callable(native_push):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint native completion hook is not callable.",
                              {"checkpoint_admission_valid": False, "execution_started": False})
        if marker_write is not None and not callable(marker_write):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint marker completion hook is not callable.",
                              {"checkpoint_admission_valid": False, "execution_started": False})
        call_id = object()
        predecessor = previous[0]
        enclosing = previous if (isinstance(predecessor, CheckpointAdmissionBinding)
                                 and predecessor.active and predecessor.context is context) else None
        binding = None if callback is None else CheckpointAdmissionBinding(
            context, spec.name, params, call_id, callback, frozen_params, readonly,
            native_push, self, spec, enclosing, marker_write_callback=marker_write)
        context.checkpoint_admission, context.checkpoint_call_id = binding, call_id
        context.checkpoint_method, context.checkpoint_params = spec.name, params
        cleanup = None
        try:
            bind = None if callback is None else getattr(callback, "bind_checkpoint", None)
            if bind is not None:
                if not callable(bind):
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission binder is not callable.")
                cleanup = bind(binding)
                if cleanup is not None and not callable(cleanup):
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint admission cleanup is not callable.")
            yield binding
        finally:
            primary = sys.exc_info()[1]
            if binding is not None:
                binding.active = False
            try:
                if cleanup is not None and callable(cleanup):
                    try:
                        cleanup()
                    except Exception:
                        if primary is None:
                            raise
                        LOGGER.exception("Checkpoint admission cleanup failed; preserving primary error")
            finally:
                (context.checkpoint_admission, context.checkpoint_call_id, context.checkpoint_method,
                 context.checkpoint_params, context.checkpoint_finalization_owner) = previous

    def native_push_completion(self, permit: InvocationPermit, binding: CheckpointAdmissionBinding,
                               manager: Any, *, final_check: Callable[[], None]):
        if binding is not None and binding.spec.name in {"mesh.attribute_storage_prepare_inspection_start", INSPECTION_TURN_METHOD}:
            from .scene_jobs import _InspectionAdmission, _InspectionTurnAdmission
            if (binding.spec.modifies or (type(binding.callback) is not _InspectionAdmission
                                         and type(binding.callback) is not _InspectionTurnAdmission)):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Inspection cannot acquire a native checkpoint consumer.")
            return nullcontext(None)
        return native_push_consumer(self, permit, binding, manager, final_check)

    def invoke_inspection_turn(self, turn: Any, params: Mapping[str, Any], context: ToolContext,
                               *, check_only: bool = False) -> Any:
        """Consume a local read turn without a checkpoint or push capability."""
        spec = self.get(INSPECTION_TURN_METHOD)
        with self.mutation_entry(spec, params, context, _scene_turn=turn) as permit:
            record = self._scene_reservations.current_inspection(context)
            if (record.check_only is not check_only or spec.modifies or spec.automatic_checkpoint
                    or spec.checkpoint_owns_finalization or spec.remote):
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Inspection turn has no canonical readonly origin.")
            entry = self.checkpoint_parameter_entry(spec, params)
            self.check_admission_entry(spec, context)
            scope, captured, deferred = self._capture_admission(spec, params, context)
            try:
                if deferred is not None:
                    raise deferred
                if captured:
                    record.binding = context.checkpoint_admission
                    record.inspection_entry_proof = record.binding.callback.entry_proof
                prepared = self.prepare_call(spec.name, params, context)
                self.check_checkpoint_parameter_entry(entry, params)
                context.checkpoint_admission.check_after_read()
                if check_only:
                    self._scene_reservations.check_inspection_turn(turn)
                    return None
                result = self.invoke(prepared, params, context, _permit=permit)
                context.checkpoint_admission.check_after_read()
                check_final_mutation(context, INSPECTION_TURN_METHOD, expected_spec=spec)
                return result
            finally:
                if captured:
                    scope.__exit__(None, None, None)

    def invoke_scene_turn(self, turn: Any, params: Mapping[str, Any], context: ToolContext, manager: Any,
                          *, checkpoint_phase: Any = None, check_only: bool = False) -> Any:
        """Local scheduler entry; its one-use origin never comes from a context or wire."""
        spec = self.get(TURN_METHOD)
        with self.mutation_entry(spec, params, context, _scene_turn=turn) as permit:
            if self._scene_reservations.current(context).check_only is not check_only:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Scene turn purpose differs from its scheduler origin.")
            if check_only:
                # A paused/undelivered owner's consent can still be revoked.
                # This branch cannot enter a handler or create a push consumer;
                # its local origin buys only a leased, provider-ordered read.
                record = self._scene_reservations.current(context)
                storage_proof = record.owner.job.storage_driver_proof
                storage_guard = None
                storage_context_proof = None
                if storage_proof is not None:
                    # Capture the concrete source checker BEFORE the provider.
                    # A permission callback cannot substitute the driver or its
                    # read callback during a paused/undelivered turn.
                    from .scene_jobs import _check_storage_driver
                    storage_guard = (_check_storage_driver, _check_storage_driver.__code__,
                                     _check_storage_driver.__defaults__, _check_storage_driver.__kwdefaults__)
                    _check_storage_driver(storage_proof)
                    from .mesh_storage_source import capture_context
                    storage_context_proof = capture_context(context, storage_proof[4])
                context.require(*record.owner.authority.required_permissions)
                if storage_guard is not None:
                    guard, code, defaults, keywords = storage_guard
                    if (guard.__code__ is not code or guard.__defaults__ is not defaults or guard.__kwdefaults__ is not keywords
                            or record.owner.job.storage_driver_proof is not storage_proof
                            or record.owner.job.driver is not storage_proof[0]):
                        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Storage job source changed before its next read.",
                                          {"reason": "MESH_STORAGE_DRIVER_SOURCE_CHANGED"})
                    guard(storage_proof)
                    from .mesh_storage_source import verify_context
                    verify_context(context, storage_context_proof)
                record.owner.job.checkpoint_manager.check_pending_markers(record.owner.job.pending, turn)
                record.owner.job.driver.check_after_read(context)
                self._scene_reservations.check_turn(turn)
                if self.get(TURN_METHOD) is not spec or spec.toolset not in self.enabled_toolsets:
                    raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Scene job entry changed before its next phase.")
                return None
            entry = self.checkpoint_parameter_entry(spec, params)
            self.check_admission_entry(spec, context)
            scope, captured, deferred = self._capture_admission(spec, params, context)
            try:
                binding = context.checkpoint_admission
                if not captured:
                    self.prepare_call(spec.name, params, context)
                    raise deferred
                with self.native_push_completion(permit, binding, manager,
                        final_check=lambda: check_final_mutation(context, TURN_METHOD)) as consumer:
                    record = self._scene_reservations.current(context)
                    record.binding, record.consumer_id = binding, id(consumer)
                    prepared = self.prepare_call(spec.name, params, context)
                    self.check_checkpoint_parameter_entry(entry, params)
                    result = self.invoke(prepared, params, context, _permit=permit)
                    if record.phase in {"checkpoint_before", "checkpoint_after"}:
                        if checkpoint_phase is None:
                            raise BridgeError(ErrorCode.OPERATION_FAILED, "Scene checkpoint phase has no scheduler owner.")
                        result = checkpoint_phase(turn, context, consumer)
                    check_final_mutation(context, TURN_METHOD)
                    return result
            finally:
                if captured:
                    scope.__exit__(None, None, None)

    def invoke(self, spec: ToolSpec, params: Mapping[str, Any], context: ToolContext, *, allow_recovery: bool = False,
               _permit: InvocationPermit | None = None) -> Any:
        if _permit is None:
            with self.mutation_entry(spec, params, context) as permit:
                return self.invoke(spec, params, context, allow_recovery=allow_recovery, _permit=permit)
        self._mutation_interlock.consume(self, spec, params, context, _permit)
        audit = self._mutation_interlock.audit_for(_permit)
        with bind_entry_audit(audit):
            try:
                return self._invoke_owned(spec, params, context, allow_recovery=allow_recovery)
            except BridgeError as error:
                annotate_entry_error(error, audit)
                raise

    def _invoke_owned(self, spec: ToolSpec, params: Mapping[str, Any], context: ToolContext, *, allow_recovery: bool = False) -> Any:
        """Enter a prepared handler without arming over an in-flight writer."""
        binding = context.checkpoint_admission
        entry = self.checkpoint_parameter_entry(spec, params)
        exact_call = context.checkpoint_call_id is not None and context.checkpoint_method == spec.name and context.checkpoint_params is params
        if exact_call and ((spec.checkpoint_admission_factory is None and binding is None)
                           or (spec.checkpoint_admission_factory is not None and binding is not None and binding.matches(spec, params, context))):
            return self._invoke_admitted(spec, params, context, allow_recovery=allow_recovery)
        if binding is not None and binding.active:
            # Verify the enclosing live call before a nested factory can bind
            # another baseline. Drift is a stopped call, not a new request.
            binding.check_after_read()
            self.check_checkpoint_parameter_entry(entry, params)
            if binding.method == spec.name and binding.params is params:
                binding.check_identity(spec.name)
        elif spec.checkpoint_admission_factory is not None and context.checkpoint_method == spec.name and context.checkpoint_params is params:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "An active checkpoint admission call lost its binding.",
                              {"checkpoint_admission_valid": False})
        with self.checkpoint_admission(spec, params, context):
            return self._invoke_admitted(spec, params, context, allow_recovery=allow_recovery)

    def _invoke_admitted(self, spec: ToolSpec, params: Mapping[str, Any], context: ToolContext, *, allow_recovery: bool) -> Any:
        store = get_task_plans(context.state)
        if spec.modifies:
            # Direct, nested and failed writer entries invalidate prior scoped
            # observations even when no outer executor history record exists.
            store.evidence_revision += 1
            self._executing_mutators += 1
            store.executing_mutators += 1
        try:
            if spec.modifies and context.checkpoint_admission is not None:
                context.checkpoint_admission()
            # All remote/direct/batch handler entries retain owner, identity and
            # toolset authority after providers. Pause/stop gates apply to writes.
            check_final_mutation(context, spec.name, allow_recovery=allow_recovery, expected_spec=spec)
            context.handler_entries += 1
            mark_handler_entered()
            return spec.handler(context, params)
        finally:
            if spec.modifies:
                store.executing_mutators -= 1
                self._executing_mutators -= 1

    def enable_toolset(self, name: str) -> None:
        normalized = name.strip().lower()
        if normalized not in self._toolsets:
            raise BridgeError(
                ErrorCode.INVALID_ARGUMENT,
                f"Unknown toolset '{name}'.",
                {"available_toolsets": sorted(self._toolsets)},
            )
        self._enabled_toolsets.add(normalized)

    def disable_toolset(self, name: str) -> None:
        normalized = name.strip().lower()
        if normalized == self.CORE_TOOLSET:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "The core toolset cannot be disabled.")
        if normalized not in self._toolsets:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, f"Unknown toolset '{name}'.")
        self._enabled_toolsets.discard(normalized)

    def list_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def describe(self) -> dict[str, Any]:
        return {
            "toolsets": [
                {
                    "name": name,
                    "enabled": name in self._enabled_toolsets,
                    "tool_count": sum(spec.toolset == name for spec in self._tools.values()),
                }
                for name in sorted(self._toolsets)
            ],
            "tools": [
                self._tools[name].metadata(enabled=self._tools[name].toolset in self._enabled_toolsets)
                for name in sorted(self._tools)
            ],
        }

    @property
    def enabled_toolsets(self) -> tuple[str, ...]:
        return tuple(sorted(self._enabled_toolsets))

    def reset_enabled_toolsets(self) -> None:
        """Return to the secure startup state without unloading definitions."""

        self._enabled_toolsets = {self.CORE_TOOLSET}
