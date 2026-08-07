"""Single Blender add-on runtime coordinating registry, executor, and listener."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .checkpoints import CheckpointManager
from .command_queue import CommandQueue
from .constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_REQUEST_TIMEOUT_SECONDS
from .errors import BridgeError, ErrorCode
from .executor import MainThreadExecutor
from .permissions import PermissionManager, permission_snapshot
from .selection import clear_selection_references
from .server import LocalBridgeServer
from .state import BridgeState, get_state
from .tool_registry import ToolRegistry
from .tools import register_all

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
        self.permissions = PermissionManager(lambda: permission_snapshot(_preferences()))
        self.checkpoints = CheckpointManager()
        self.registry = ToolRegistry(enabled_toolsets=())
        register_all(self.registry)
        self.executor = MainThreadExecutor(
            command_queue=self.command_queue,
            registry=self.registry,
            state=self.state,
            permissions=self.permissions,
            checkpoints=self.checkpoints,
        )
        self.server = LocalBridgeServer(submit=self.executor.submit, state=self.state)
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        self.state.reset()
        clear_selection_references()
        self.registry.reset_enabled_toolsets()
        self.executor.start()
        if bpy is not None and _before_file_load not in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.append(_before_file_load)
        self._registered = True

    def unregister(self) -> None:
        if bpy is not None and _before_file_load in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.remove(_before_file_load)
        self.server.stop()
        self.executor.stop()
        self.checkpoints.clear()
        clear_selection_references()
        self.registry.reset_enabled_toolsets()
        self.state.reset()
        self._registered = False

    def prepare_for_file_load(self) -> None:
        """Disconnect clients and discard all project-scoped transient state."""

        self.server.stop()
        self.command_queue.cancel_all(
            BridgeError(ErrorCode.SERVER_ERROR, "Project file is being replaced in Blender.")
        )
        self.checkpoints.clear()
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
        self.state.set_emergency_stopped(False)
        self.state.set_paused(False)
        clear_selection_references()
        return self.server.start(host, port, request_timeout=request_timeout)

    def stop_server(self) -> None:
        self.server.stop()
        clear_selection_references()
        self.command_queue.cancel_all(
            BridgeError(ErrorCode.SERVER_ERROR, "Bridge stopped before request execution.")
        )

    def emergency_stop(self) -> None:
        self.state.set_emergency_stopped(True)
        self.command_queue.cancel_all(
            BridgeError(ErrorCode.EMERGENCY_STOPPED, "Request canceled by Blender emergency stop.")
        )
        self.server.stop()

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


_RUNTIME: BridgeRuntime | None = None


def get_runtime() -> BridgeRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = BridgeRuntime()
    return _RUNTIME
