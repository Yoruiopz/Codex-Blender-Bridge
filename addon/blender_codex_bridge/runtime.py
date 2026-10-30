"""Single Blender add-on runtime coordinating registry, executor, and listener."""

from __future__ import annotations

from collections.abc import Mapping
from types import CodeType, FunctionType
from typing import Any
from uuid import uuid4

from . import native_save_policy as _native_save_policy_module
from .checkpoints import CheckpointManager
from .command_queue import CommandQueue
from .constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_REQUEST_TIMEOUT_SECONDS
from .errors import BridgeError, ErrorCode
from .executor import MainThreadExecutor
from .glb_stage_runtime import GLBStageService, checked_executor_context
from .native_save_policy import POLICY_VERSION, GrantStatement, NativeSaveGrant
from .permissions import Permission, PermissionManager
from .permissions import permission_snapshot as _base_permission_snapshot
from .selection import clear_selection_references
from .server import LocalBridgeServer
from .state import BridgeState, get_state
from .storage_snapshot_service import StorageSnapshotService
from .task_plans import get_task_plans
from .tool_registry import ToolRegistry

_BASE_PERMISSION_SNAPSHOT = _base_permission_snapshot
_BASE_PERMISSION_SNAPSHOT_CODE = _base_permission_snapshot.__code__
_NATIVE_SAVE_GRANT_CLASS = NativeSaveGrant
_NATIVE_SAVE_STATEMENT_CLASS = GrantStatement
_GRANT_STATEMENT_INIT_CODE = GrantStatement.__init__.__code__
_NATIVE_SAVE_POLICY_VERSION = POLICY_VERSION
_GRANT_HELPERS = tuple((name, getattr(NativeSaveGrant, name), getattr(NativeSaveGrant, name).__code__)
                      for name in ("__init__", "__setattr__", "_main", "_now", "arm", "revoke",
                                   "active", "statement", "check", "status"))
_GRANT_GENERATION_PROPERTY = NativeSaveGrant.generation
_GRANT_GENERATION_GETTER_CODE = NativeSaveGrant.generation.fget.__code__
_CANONICAL_RUNTIME_CLASS = None
_RUNTIME_CONSTRUCTOR_CODE = None
_PERMISSION_PROVIDER_CODE = None
_PREFERENCES_FUNCTION = None
_PREFERENCES_CODE = None
_PERMISSION_MANAGER_CLASS = PermissionManager


def native_save_permission_provider_intact() -> bool:
    """Pure code identities; callers must also pin this guard before invoking it."""
    runtime = globals().get("_RUNTIME")
    runtime_class = globals().get("BridgeRuntime")
    preferences = globals().get("_preferences")
    if (_CANONICAL_RUNTIME_CLASS is None or runtime_class is not _CANONICAL_RUNTIME_CLASS
            or type(runtime) is not runtime_class or not runtime._registered
            or type(runtime_class.__init__) is not FunctionType
            or runtime_class.__init__.__code__ is not _RUNTIME_CONSTRUCTOR_CODE
            or preferences is not _PREFERENCES_FUNCTION or type(preferences) is not FunctionType
            or preferences.__code__ is not _PREFERENCES_CODE
            or type(runtime.permissions) is not _PERMISSION_MANAGER_CLASS):
        return False
    provider = runtime.permissions._source
    if (type(provider) is not FunctionType or provider.__closure__ is not None
            or provider.__globals__ is not globals() or provider.__code__ is not _PERMISSION_PROVIDER_CODE
            or provider.__defaults__ is not None or provider.__kwdefaults__ is not None):
        return False
    if not (
        permission_snapshot is _PERMISSION_SNAPSHOT_FUNCTION
        and type(permission_snapshot) is FunctionType
        and permission_snapshot.__code__ is _PERMISSION_SNAPSHOT_CODE
        and _base_permission_snapshot is _BASE_PERMISSION_SNAPSHOT
        and type(_base_permission_snapshot) is FunctionType
        and _base_permission_snapshot.__code__ is _BASE_PERMISSION_SNAPSHOT_CODE
        and NativeSaveGrant is _NATIVE_SAVE_GRANT_CLASS
        and _native_save_policy_module.NativeSaveGrant is _NATIVE_SAVE_GRANT_CLASS
        and GrantStatement is _NATIVE_SAVE_STATEMENT_CLASS
        and _native_save_policy_module.GrantStatement is _NATIVE_SAVE_STATEMENT_CLASS
        and GrantStatement.__init__.__code__ is _GRANT_STATEMENT_INIT_CODE
        and _native_save_policy_module.POLICY_VERSION == _NATIVE_SAVE_POLICY_VERSION
        and NativeSaveGrant.generation is _GRANT_GENERATION_PROPERTY
        and NativeSaveGrant.generation.fget.__code__ is _GRANT_GENERATION_GETTER_CODE
        and _CANONICAL_RUNTIME_CLASS is globals().get("BridgeRuntime")
        and all(type(getattr(NativeSaveGrant, name)) is FunctionType
                and getattr(NativeSaveGrant, name) is function
                and function.__code__ is code for name, function, code in _GRANT_HELPERS)
    ):
        return False
    grant = runtime.native_save_policy
    return (type(grant) is _NATIVE_SAVE_GRANT_CLASS
            and grant is runtime._native_save_policy_origin
            and grant._authority is runtime._native_save_local_authority
            and grant.generation == runtime._native_save_generation)


def permission_snapshot(preferences: Any | None) -> dict[str, bool]:
    """Compose one ordinary preference snapshot with only canonical local consent."""
    if (_base_permission_snapshot is not _BASE_PERMISSION_SNAPSHOT
            or type(_base_permission_snapshot) is not FunctionType
            or _base_permission_snapshot.__code__ is not _BASE_PERMISSION_SNAPSHOT_CODE):
        return {permission.value: False for permission in Permission}
    result = _base_permission_snapshot(preferences)
    result["NATIVE_SAVE_EFFECTS"] = False
    if (native_save_permission_provider_intact is not _PERMISSION_PROVIDER_GUARD
            or native_save_permission_provider_intact.__code__ is not _PERMISSION_PROVIDER_GUARD_CODE
            or not native_save_permission_provider_intact()):
        return result
    runtime = globals().get("_RUNTIME")
    if (_CANONICAL_RUNTIME_CLASS is None or type(runtime) is not _CANONICAL_RUNTIME_CLASS
            or not runtime._registered):
        return result
    grant = runtime.native_save_policy
    if (type(grant) is not _NATIVE_SAVE_GRANT_CLASS
            or grant is not runtime._native_save_policy_origin
            or grant._authority is not runtime._native_save_local_authority
            or grant.generation != runtime._native_save_generation):
        return result
    result["NATIVE_SAVE_EFFECTS"] = grant.active()
    return result


_PERMISSION_SNAPSHOT_FUNCTION = permission_snapshot
_PERMISSION_SNAPSHOT_CODE = permission_snapshot.__code__
_PERMISSION_PROVIDER_GUARD = native_save_permission_provider_intact
_PERMISSION_PROVIDER_GUARD_CODE = native_save_permission_provider_intact.__code__

# Define the canonical provider before imports that can inspect this module.
from .native_save_jobs import NativeSaveJobs  # noqa: E402
from .tools import register_all  # noqa: E402

try:
    import bpy  # type: ignore
    from bpy.app.handlers import persistent  # type: ignore
except ImportError:  # pragma: no cover - pure Python tests
    bpy = None  # type: ignore

    def persistent(function):
        return function


@persistent
def _before_file_load(_unused: Any) -> None:
    """Fail closed before Blender replaces every project datablock."""

    if _RUNTIME is not None:
        _RUNTIME.prepare_for_file_load()


@persistent
def _before_external_undo_redo(_unused: Any) -> None:
    """Invalidate live handles on every native history move, including recovery."""
    if _RUNTIME is not None:
        _RUNTIME.native_save_policy.revoke()
        was_paused = _RUNTIME.state.paused
        # A failed cache invalidation must leave mutations paused. Restore the
        # previous intent only after the entire history callback succeeds.
        _RUNTIME.state.set_paused(True)
        _RUNTIME.jobs.cancel_all("native undo/redo")
        service = getattr(_RUNTIME, "glb_stage", None)
        if service is not None:
            service.invalidate()
        get_task_plans(_RUNTIME.state).invalidate_handles()
        if not _RUNTIME.checkpoints.recovery_in_progress:
            _RUNTIME.checkpoints.clear()
            clear_selection_references()
        _RUNTIME.state.set_paused(was_paused)


def _preferences() -> Any | None:
    try:
        import bpy  # type: ignore

        addon = bpy.context.preferences.addons.get(__package__)
        return addon.preferences if addon else None
    except (ImportError, AttributeError, RuntimeError):
        return None


class BridgeRuntime:
    """Own all mutable add-on services and a stable direct-dispatch API."""

    def __init__(self) -> None:
        self.state: BridgeState = get_state()
        self.command_queue = CommandQueue(maximum_size=256)
        self._native_save_generation = uuid4().hex
        self._native_save_local_authority = object()
        self.native_save_policy = NativeSaveGrant(self._native_save_generation,
                                                 self._native_save_local_authority)
        self._native_save_policy_origin = self.native_save_policy
        self._registered = False
        self.permissions = PermissionManager(lambda: permission_snapshot(_preferences()))
        self.checkpoints = CheckpointManager()
        self.registry = ToolRegistry(enabled_toolsets=())
        register_all(self.registry)
        self.jobs = NativeSaveJobs(lambda: checked_executor_context(self.executor),
                              lambda: getattr(_preferences(), "paint_job_budget_ms", 4),
                              native_save_policy=self.native_save_policy, registry=self.registry)
        self.storage_snapshots = StorageSnapshotService(self)
        self._storage_snapshot_origin = self.storage_snapshots
        self.glb_stage = GLBStageService(self)
        self._glb_stage_origin = self.glb_stage
        self.executor = MainThreadExecutor(
            command_queue=self.command_queue,
            registry=self.registry,
            state=self.state,
            permissions=self.permissions,
            checkpoints=self.checkpoints,
            jobs=self.jobs,
            glb_stage=self.glb_stage,
            storage_snapshots=self.storage_snapshots,
        )
        self.glb_stage._executor_origin = self.executor
        self.server = LocalBridgeServer(submit=self.executor.submit, state=self.state)
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        # Invalidation can allocate. Revoke and stop existing/new writes first.
        self.native_save_policy.revoke()
        self.state.set_paused(True)
        self.jobs.cancel_all("runtime registered")
        self.glb_stage.invalidate()
        self.state.reset()
        clear_selection_references()
        self.registry.reset_enabled_toolsets()
        self.executor.start()
        if bpy is not None and _before_file_load not in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.append(_before_file_load)
        if bpy is not None:
            for handlers in (bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
                if _before_external_undo_redo not in handlers:
                    handlers.append(_before_external_undo_redo)
        self._registered = True

    def unregister(self) -> None:
        self.native_save_policy.revoke()
        self.state.set_paused(True)
        self.jobs.cancel_all("runtime unregistered")
        self.glb_stage.invalidate()
        if bpy is not None:
            for handlers in (bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
                if _before_external_undo_redo in handlers:
                    handlers.remove(_before_external_undo_redo)
        if bpy is not None and _before_file_load in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.remove(_before_file_load)
        self.server.stop()
        self.executor.stop()
        self.checkpoints.detach()
        self.executor.evidence.clear()
        clear_selection_references()
        self.registry.reset_enabled_toolsets()
        self.state.reset()
        self._registered = False

    def prepare_for_file_load(self) -> None:
        """Disconnect clients and discard all project-scoped transient state."""

        self.native_save_policy.revoke()
        self.state.set_paused(True)
        self.jobs.cancel_all("project file replacement")
        self.glb_stage.invalidate()
        self.server.stop()
        self.command_queue.cancel_all(
            BridgeError(ErrorCode.SERVER_ERROR, "Project file is being replaced in Blender.")
        )
        self.checkpoints.clear()
        self.executor.evidence.clear()
        clear_selection_references()
        self.registry.reset_enabled_toolsets()
        self.state.reset()

    def start_server(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> tuple[str, int]:
        if not self._registered:
            raise BridgeError(ErrorCode.SERVER_ERROR, "The Blender add-on is not registered.")
        self.native_save_policy.revoke()
        self.state.set_emergency_stopped(False)
        self.state.set_paused(False)
        clear_selection_references()
        return self.server.start(host, port, request_timeout=request_timeout)

    def stop_server(self) -> None:
        self.native_save_policy.revoke()
        self.state.set_paused(True)
        self.jobs.cancel_all("bridge stopped")
        self.glb_stage.invalidate()
        self.server.stop()
        clear_selection_references()
        self.command_queue.cancel_all(
            BridgeError(ErrorCode.SERVER_ERROR, "Bridge stopped before request execution.")
        )

    def emergency_stop(self) -> None:
        self.native_save_policy.revoke()
        self.state.set_emergency_stopped(True)
        self.jobs.cancel_all("emergency stop")
        self.glb_stage.invalidate()
        self.command_queue.cancel_all(
            BridgeError(ErrorCode.EMERGENCY_STOPPED, "Request canceled by Blender emergency stop.")
        )
        self.server.stop()

    def arm_native_save_effects(self, seconds: int = 900) -> dict[str, Any]:
        """Local UI entry only; no ToolRegistry/MCP method grants this authority."""
        if not self._registered:
            raise BridgeError(ErrorCode.SERVER_ERROR, "The Blender add-on is not registered.")
        active = self.jobs.active
        if active is not None and (getattr(active, "kind", None) == "project.native_save"
                                   or getattr(active, "method", None) == "project.native_save_start"):
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "Finish or cancel the active native save before renewing permission.")
        self.native_save_policy.arm(self._native_save_local_authority, seconds)
        return self.native_save_policy.status()

    def revoke_native_save_effects(self) -> None:
        """Local revocation remains possible while a save or bridge is stopped."""
        self.native_save_policy.revoke()

    def dispatch(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Dispatch synchronously on Blender's main thread (tests/internal use)."""

        if not self._registered:
            raise BridgeError(ErrorCode.SERVER_ERROR, "The Blender add-on is not registered.")
        return self.executor.dispatch(method, params)

    def dispatch_recovery(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Allow only Blender-UI recovery controls through pause/emergency gates."""

        if method not in self.registry.RECOVERY_TOOLS:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "Method is not a recovery control.")
        if not self._registered:
            raise BridgeError(ErrorCode.SERVER_ERROR, "The Blender add-on is not registered.")
        return self.executor.dispatch(method, params, allow_recovery=True)


_CANONICAL_RUNTIME_CLASS = BridgeRuntime
_RUNTIME_CONSTRUCTOR_CODE = BridgeRuntime.__init__.__code__
_PERMISSION_PROVIDER_CODE, = (
    code for code in _RUNTIME_CONSTRUCTOR_CODE.co_consts if type(code) is CodeType
    and code.co_name == "<lambda>" and code.co_argcount == 0 and code.co_kwonlyargcount == 0
    and code.co_names == ("permission_snapshot", "_preferences") and not code.co_freevars
)
_PREFERENCES_FUNCTION = _preferences
_PREFERENCES_CODE = _preferences.__code__
_RUNTIME: BridgeRuntime | None = None


def get_runtime() -> BridgeRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = BridgeRuntime()
    return _RUNTIME
