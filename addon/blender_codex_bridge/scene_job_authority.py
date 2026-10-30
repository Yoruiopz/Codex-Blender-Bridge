"""Frozen starter authority, retained independently of mutable job diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .errors import BridgeError, ErrorCode
from .permissions import Permission


def _permissions(values):
    try:
        if any(type(value) not in {Permission, str} for value in values):
            raise ValueError
        return tuple(sorted({Permission(value) for value in values}, key=lambda item: item.value))
    except ValueError as cause:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Scene-job permissions have no reviewed literal declaration.",
                          {"reason": "SCENE_START_PERMISSIONS_INVALID", "execution_started": False}) from cause


@dataclass(frozen=True, slots=True, eq=False)
class SceneJobAuthority:
    registry: Any
    spec: Any
    method: str
    toolset: str
    declared_permissions: frozenset
    required_permissions: tuple[Permission, ...]
    permission_manager: Any
    permission_source: Any
    inspection_spec: tuple = ()

    @classmethod
    def capture(cls, context, params):
        """Capture the canonical pending starter before factory/provider calls."""
        registry = context.registry
        entries = registry._mutation_interlock._entries
        entry = entries[-1] if entries else None
        if (entry is None or entry.registry is not registry or entry.context is not context or entry.params is not params
                or entry.continuation_id in registry._mutation_interlock._consumed):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Scene job has no canonical pending starter.",
                              {"reason": "SCENE_START_ENTRY_LOST", "execution_started": False})
        spec = entry.spec
        manager = context.permissions
        while type(manager) is SceneJobPermissions:
            manager = manager.base
        authority = cls(registry, spec, spec.name, spec.toolset, spec.permissions, _permissions(spec.permissions),
                        manager, getattr(manager, "_source", None))
        authority.check()
        return authority

    def include_driver_permissions(self, values):
        return replace(self, required_permissions=_permissions((*self.required_permissions, *values)))

    @classmethod
    def capture_inspection(cls, context, params):
        """The private read starter cannot inherit a modifying tool's authority."""
        authority = cls.capture(context, params)
        from .mesh_storage_contract import INSPECTION_START, PERMISSIONS
        spec = authority.spec
        if (authority.method != INSPECTION_START or spec.modifies or spec.automatic_checkpoint
                or spec.permissions != frozenset(PERMISSIONS) or spec.checkpoint_owns_finalization):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Inspection has no canonical readonly starter.",
                              {"reason": "INSPECTION_START_SPEC_INVALID", "execution_started": False})
        return replace(authority, inspection_spec=tuple((name, getattr(spec, name)) for name in type(spec).__slots__))

    def check(self):
        """Provider-free proof; no native reads or re-registration adoption."""
        if (self.registry._tools.get(self.method) is not self.spec or self.spec.name != self.method
                or self.spec.toolset != self.toolset or self.spec.permissions != self.declared_permissions
                or any(getattr(self.spec, name) is not value for name, value in self.inspection_spec)):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The accepted Scene-job starter was replaced or removed.",
                              {"reason": "SCENE_START_SPEC_CHANGED", "tool": self.method, "execution_started": False})
        if self.toolset not in self.registry.enabled_toolsets:
            raise BridgeError(ErrorCode.TOOLSET_DISABLED, "The accepted Scene-job toolset is disabled.",
                              {"tool": self.method, "toolset": self.toolset, "execution_started": False})
        self.check_permission_source(self.permission_manager)

    def check_permission_source(self, manager):
        if manager is not self.permission_manager or getattr(manager, "_source", None) is not self.permission_source:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The accepted Scene-job permission source changed.",
                              {"reason": "SCENE_START_PERMISSION_SOURCE_CHANGED", "execution_started": False})


class SceneJobPermissions:
    """An enforcement view, never a grant; nested control entries stay ordinary.

    Driver helpers and registry.prepare both reach this view through the supplied
    Scene context. Authority comes only from the exact live top TURN invocation.
    """

    def __init__(self, base, service):
        while type(base) is SceneJobPermissions:
            base = base.base
        self.base, self.service = base, service

    def _scope(self):
        turn = self.service.permission_turn()
        return (turn, True) if turn is not None else (self.service.permission_parent(), False)

    def _values(self, turn, enforce):
        if enforce:
            turn.owner.authority.check_permission_source(self.base)
        try:
            values = self.base.snapshot()  # One original coherent provider read.
        except Exception as cause:
            error = cause if isinstance(cause, BridgeError) else BridgeError(
                ErrorCode.OPERATION_FAILED, "Scene-job permission evidence could not be read.",
                {"reason": "SCENE_PERMISSION_READ_FAILED", "exception_type": type(cause).__name__})
            self.service.note_permission_denial(turn, error)
            raise
        try:
            turn.owner.authority.check_permission_source(self.base)
        except BridgeError as error:
            self.service.note_permission_denial(turn, error)
        self.service.note_permission_snapshot(turn, values)
        return values

    @staticmethod
    def _require_snapshot(required, values):
        names = [item.value if isinstance(item, Permission) else str(item) for item in required]
        denied = [item for item in names if not values.get(item, False)]
        if denied:
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Blender-side permission denied.",
                              {"required": names, "missing_permissions": denied})

    def require(self, permissions):
        turn, enforce = self._scope()
        required = tuple(permissions)
        if turn is None or (not enforce and not required):
            return self.base.require(required)
        if enforce:
            required = tuple(dict.fromkeys((*turn.owner.authority.required_permissions, *required)))
        values = self._values(turn, enforce)
        self._require_snapshot(required, values)
        if enforce:
            self.service.check_permission_turn(turn.token)

    def snapshot(self):
        turn, enforce = self._scope()
        if turn is None:
            return self.base.snapshot()
        values = self._values(turn, enforce)
        if enforce:
            self.service.check_permission_turn(turn.token)
        return values

    def is_allowed(self, permission):
        turn, enforce = self._scope()
        if turn is None:
            return self.base.is_allowed(permission)
        values = self._values(turn, enforce)
        if enforce:
            self.service.check_permission_turn(turn.token)
        key = permission.value if isinstance(permission, Permission) else str(permission)
        return bool(values.get(key, False))


def bind_permissions(context, service):
    if type(context.permissions) is not SceneJobPermissions or context.permissions.service is not service:
        context.permissions = SceneJobPermissions(context.permissions, service)
