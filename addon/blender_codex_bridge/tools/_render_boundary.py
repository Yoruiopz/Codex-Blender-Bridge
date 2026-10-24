"""Per-owned-write render authority, exact state and measured compensation."""

from __future__ import annotations

import math
import struct
from typing import Any

from .. import render_scope_profile as profile
from ..errors import BridgeError, ErrorCode
from ..permissions import Permission
from ..tool_registry import check_final_mutation

STOP_CODES = frozenset(
    {
        ErrorCode.TIMEOUT.value,
        ErrorCode.PERMISSION_DENIED.value,
        ErrorCode.AGENT_PAUSED.value,
        ErrorCode.EMERGENCY_STOPPED.value,
        ErrorCode.TOOLSET_DISABLED.value,
    }
)


def _matches(actual: Any, desired: Any) -> bool:
    if isinstance(desired, float) and not isinstance(desired, bool):
        return (
            type(actual) in (int, float)
            and math.isfinite(float(actual))
            and float(actual) in {desired, struct.unpack("f", struct.pack("f", desired))[0]}
        )
    return type(actual) is type(desired) and actual == desired


class Boundary:
    def __init__(
        self,
        context: Any,
        bpy: Any,
        scene: Any,
        method: str,
        writes: list[tuple[Any, str, Any]],
        *,
        external: bool = False,
        checkpoint_prefix: str | None = None,
        initial_check: bool = True,
    ):
        self.context, self.bpy, self.scene, self.method = context, bpy, scene, method
        self.checkpoint_prefix = checkpoint_prefix
        self.required = (Permission.EDIT_RENDER,)
        if method == "render.execute":
            self.required += (Permission.CAPTURE_VIEWPORT,)
        if external:
            self.required += (Permission.ACCESS_EXTERNAL_FILES,)
        self.owned = frozenset((int(owner.as_pointer()), name) for owner, name, _ in writes)
        if len(self.owned) != len(writes):
            raise ValueError("Duplicate internal render field")
        self.fields = {(int(owner.as_pointer()), name): (owner, name) for owner, name, _ in writes}
        self.planned = list(writes)
        self.published: list[tuple[int, str]] = []
        self.stopped: BridgeError | None = None
        self.started = self.native_started = self.native_completed = False
        self.native_blocking_seconds = None
        self.failed_setter_observation: dict | None = None
        self.filesystem_checks: list[Any] = []
        # Freeze before callback-backed grant reads. A provider cannot turn a
        # stale prepared default or newer manual setting into our baseline.
        self.protected = self.snapshot()
        self.native_protected = (
            self.snapshot(predict_native_availability=True)
            if method == "render.execute"
            else self.protected
        )
        self.checkpoint_protected = (
            self.snapshot(predict_checkpoint_roles=True) if checkpoint_prefix is not None else self.protected
        )
        self.checkpoint_native_protected = (
            self.snapshot(predict_native_availability=True, predict_checkpoint_roles=True)
            if checkpoint_prefix is not None and method == "render.execute"
            else self.checkpoint_protected
        )
        self.native_sealed_protected = None
        self.original = {key: self.read(owner, name) for key, (owner, name) in self.fields.items()}
        self.expected = dict(self.original)
        if initial_check:
            self.check()

    def snapshot(self, *, predict_native_availability: bool = False, predict_checkpoint_roles: bool = False) -> tuple:
        return profile.snapshot(
            self.bpy,
            self.scene,
            self.owned,
            predict_native_availability=predict_native_availability,
            checkpoint_prefix=self.checkpoint_prefix,
            checkpoint_static=False,
            predict_checkpoint_roles=predict_checkpoint_roles,
        )

    def after_native_push(self) -> None:
        """Advance only to candidates frozen before any entry providers."""
        from ..checkpoint_completion import claim_native_push_delegate
        claim_native_push_delegate(self)
        if self.native_sealed_protected is not None:
            self.native_sealed_protected = (
                self.checkpoint_protected
                if self.native_sealed_protected == self.protected
                else self.checkpoint_native_protected
            )
        self.protected = self.checkpoint_protected
        self.native_protected = self.checkpoint_native_protected

    def read(self, owner: Any, name: str) -> Any:
        return profile.value(profile.Reader(self.bpy, self.scene).field(owner, name))

    def _authority(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            callback = getattr(self.context, "check_cancelled", None)
            if callback is not None:
                callback()
            registry = getattr(self.context, "registry", None)
            if registry is not None:
                registry.prepare(self.method, self.context)
            # This coherent complete set is the final callback-backed provider.
            self.context.require(*self.required)
        except BridgeError as error:
            if error.code in STOP_CODES:
                self.stopped = error
            raise

    def final(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            check_final_mutation(self.context, self.method)
        except BridgeError as error:
            if error.code in STOP_CODES:
                self.stopped = error
            raise

    def check(self) -> None:
        self._authority()
        self.check_after_read()

    def check_after_read(self) -> None:
        """Full authored ledger CAS after providers; never invokes providers."""
        for check in self.filesystem_checks:
            check()  # Trusted path/identity readers, never permission providers.
        current = self.snapshot()
        values = {key: self.read(owner, name) for key, (owner, name) in self.fields.items()}
        expected_protected = (
            self.native_sealed_protected if self.native_completed else self.protected
        )
        if current != expected_protected or values != self.expected:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Render context, dependencies or owned settings changed; further writes and compensation are refused.",
                {
                    "render_scope_complete": False,
                    "possible_mutation": self.started,
                    "verification_required": True,
                },
            )
        self.final()

    def seal_native_outcome(self) -> None:
        """Choose only a precomputed complete candidate, before any providers.

        Native socket updates may retain the original availability or apply the
        exact source-derived state. No unrelated values or per-field mixtures
        are adopted, and subsequent providers must preserve this sealed choice.
        """
        if not self.native_completed or self.native_sealed_protected is not None:
            raise ValueError("Only one successfully completed native outcome may be sealed")
        self.final()
        current = self.snapshot()
        values = {key: self.read(owner, name) for key, (owner, name) in self.fields.items()}
        if values != self.expected or current not in (self.protected, self.native_protected):
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Native render changed dependencies beyond its independently predicted complete outcomes.",
                {
                    "possible_mutation": True,
                    "verification_required": True,
                    "render_scope_complete": False,
                },
            )
        self.final()
        self.native_sealed_protected = (
            self.protected if current == self.protected else self.native_protected
        )

    def native_evidence(self) -> dict:
        return {
            "outcome_sealed": self.native_sealed_protected is not None,
            "derived_availability_transition_observed": self.native_sealed_protected is not None
            and self.native_sealed_protected != self.protected,
            "authored_socket_values_adopted": False,
        }

    def write(self, owner: Any, name: str, desired: Any) -> None:
        self.check()
        key = int(owner.as_pointer()), name
        if key not in self.fields:
            raise ValueError("Unplanned internal render field")
        old = self.expected[key]
        self.started = True
        try:
            setattr(owner, name, desired)
        except Exception as error:
            try:
                actual = self.read(owner, name)
            except Exception as observation_error:
                self.failed_setter_observation = {
                    "field": name,
                    "readback": "unavailable",
                    "exception_type": type(observation_error).__name__,
                }
                raise error from None
            # A failed setter can partially write. Only its exact independently
            # predicted value is admitted as owned, never an arbitrary readback.
            if _matches(actual, desired):
                self.expected[key] = actual
                if key not in self.published:
                    self.published.append(key)
            elif actual != old:
                self.failed_setter_observation = {
                    "field": name,
                    "readback": "unreviewed_value",
                    "compensation_admitted": False,
                }
            raise
        actual = self.read(owner, name)
        if not _matches(actual, desired):
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Render setter did not retain the predicted native value.",
                {"field": name, "possible_mutation": True, "verification_required": True},
            )
        self.expected[key] = actual
        if key not in self.published:
            self.published.append(key)
        self.check()

    def apply(self) -> None:
        for owner, name, desired in self.planned:
            if profile.value(desired) != self.expected[int(owner.as_pointer()), name]:
                self.write(owner, name, desired)
        self.check()

    def restore(self) -> dict:
        restored = []
        try:
            self.check()
            for key in reversed(self.published):
                owner, name = self.fields[key]
                if self.expected[key] != self.original[key]:
                    self.write(owner, name, self.original[key])
                    restored.append(name)
            self.check()
            return {
                "attempted": True,
                "restored": True,
                "restored_fields": restored,
                "verification_required": False,
            }
        except Exception as error:
            return {
                "attempted": True,
                "restored": False,
                "restored_fields": restored,
                "blocked_by": error.code
                if isinstance(error, BridgeError)
                else type(error).__name__,
                "verification_required": True,
            }

    def annotate(
        self, error: Exception, recovery: dict | None = None, effects: dict | None = None
    ) -> BridgeError:
        result = (
            error
            if isinstance(error, BridgeError)
            else BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Render operation failed.",
                {"exception_type": type(error).__name__},
            )
        )
        result.context.update(
            {
                "execution_started": self.started or self.native_started,
                "possible_mutation": self.started or self.native_started,
                "verification_required": True,
                "render_result_replacement_possible": self.native_started,
                "native_render_started": self.native_started,
                "native_render_completed": self.native_completed,
            }
        )
        if recovery is not None:
            result.context["render_settings_recovery"] = recovery
        if effects is not None:
            result.context["external_effects"] = effects
        result.context["native_dependency_evidence"] = self.native_evidence()
        if self.native_started:
            result.context["native_call_interruptible"] = False
            result.context["native_blocking_seconds"] = self.native_blocking_seconds
        if self.failed_setter_observation is not None:
            result.context["failed_setter_observation"] = self.failed_setter_observation
        return result
