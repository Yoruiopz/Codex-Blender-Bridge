"""Readonly request-owned render admission for every native checkpoint write.

Wiring uses the optional registry checkpoint-admission contract. Authored render
field comparisons remain the separate full Boundary's responsibility.
"""

from __future__ import annotations

from typing import Any

from .. import render_scope_profile as profile
from ..errors import BridgeError, ErrorCode
from ..permissions import Permission
from ..tool_registry import check_final_mutation


class Admission:
    def __init__(
        self,
        context: Any,
        bpy: Any,
        scene: Any,
        method: str,
        *,
        external: bool,
        boundary: Any = None,
    ):
        self.context, self.bpy, self.scene, self.method = context, bpy, scene, method
        self.boundary = boundary
        self.manager = context.checkpoints
        self.prefix = getattr(self.manager, "_prefix", None)
        if not isinstance(self.prefix, str):
            profile.refuse("Native render checkpoints require a manager-owned marker namespace.")
        self.required = (Permission.EDIT_RENDER,)
        if method == "render.execute":
            self.required += (Permission.CAPTURE_VIEWPORT,)
        if external:
            self.required += (Permission.ACCESS_EXTERNAL_FILES,)
        self.stopped = None
        # No providers run before this readonly descriptor/dependency baseline.
        self.baseline = profile.snapshot(bpy, scene, checkpoint_prefix=self.prefix)
        self.after_push_baseline = profile.snapshot(
            bpy, scene, checkpoint_prefix=self.prefix, predict_checkpoint_roles=True
        )

    def after_native_push(self) -> None:
        """Provider-free successful-push notification; never adopt readback."""
        from ..checkpoint_completion import claim_native_push_completion
        claim_native_push_completion(self.context, self.method, self)
        if self.stopped is not None:
            raise self.stopped
        self.baseline = self.after_push_baseline
        if self.boundary is not None:
            self.boundary.after_native_push()
        self.check_after_read()

    def native_push_delegates(self) -> tuple[Any, ...]:
        return () if self.boundary is None else (self.boundary,)

    def __call__(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            callback = getattr(self.context, "check_cancelled", None)
            if callback is not None:
                callback()
            registry = getattr(self.context, "registry", None)
            if registry is not None:
                registry.prepare(self.method, self.context)
            self.context.require(*self.required)
            self.check_after_read()
        except Exception as error:
            self.stopped = (
                error
                if isinstance(error, BridgeError)
                else BridgeError(
                    ErrorCode.OPERATION_FAILED,
                    "Render checkpoint admission failed.",
                    {"exception_type": type(error).__name__},
                )
            )
            if self.stopped is error:
                raise
            raise self.stopped from error

    def check_after_read(self) -> None:
        """Readonly static CAS and pure final guard, with no providers.

        Checkpoint code calls this only after its own exact marker/value CAS.
        It must never fall back to the callback-backed __call__ here.
        """
        if self.stopped is not None:
            raise self.stopped
        try:
            if (
                self.context.checkpoints is not self.manager
                or getattr(self.manager, "_prefix", None) != self.prefix
            ):
                raise BridgeError(
                    ErrorCode.OPERATION_FAILED,
                    "Render checkpoint ownership changed before its next write.",
                )
            if (
                profile.snapshot(self.bpy, self.scene, checkpoint_prefix=self.prefix)
                != self.baseline
            ):
                raise BridgeError(
                    ErrorCode.OPERATION_FAILED,
                    "Render checkpoint dependency descriptors, bindings, topology or context changed before its next write.",
                )
            if self.boundary is not None:
                if self.boundary.checkpoint_prefix != self.prefix:
                    raise BridgeError(
                        ErrorCode.OPERATION_FAILED,
                        "Render authored ledger has a different checkpoint owner.",
                    )
                self.boundary.check_after_read()
            check_final_mutation(self.context, self.method)
        except Exception as error:
            self.stopped = (
                error
                if isinstance(error, BridgeError)
                else BridgeError(
                    ErrorCode.OPERATION_FAILED,
                    "Render checkpoint readonly verification failed.",
                    {"exception_type": type(error).__name__},
                )
            )
            if self.stopped is error:
                raise
            raise self.stopped from error
