"""Synchronous structured-call ownership, never a Blender/Python sandbox.

Only explicitly registered exclusive mutators acquire a lease. A lease spans
admission, native work and finalization, and is never held across job ticks.
The context binding is evidence for final gates, not permission to reenter.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any

from .errors import BridgeError, ErrorCode


@dataclass(frozen=True, slots=True, eq=False)
class ExclusiveMutationLease:
    registry: Any
    spec: Any
    context: Any
    params: Mapping[str, Any]
    call_id: object


@dataclass(frozen=True, slots=True, eq=False)
class _InvocationRecord:
    registry: Any
    spec: Any
    context: Any
    params: Mapping[str, Any]
    call_id: object
    lease: ExclusiveMutationLease | None
    continuation_id: int


@dataclass(frozen=True, slots=True, eq=False)
class InvocationPermit:
    """Local, single-use continuation; never obtained from a ToolContext.

    Registry records retain only its identity number, not this capability. Its
    immutable identity prevents relabeling a readonly entry as a mutator.
    """

    registry: Any
    spec: Any
    context: Any
    params: Mapping[str, Any]
    call_id: object


def _lost() -> BridgeError:
    return BridgeError(
        ErrorCode.OPERATION_FAILED,
        "Exclusive mutation ownership changed; no further structured writes are authorized.",
        {"reason": "EXCLUSIVE_MUTATION_LEASE_LOST", "execution_started": False,
         "exclusive_mutation_lease_valid": False},
    )


class MutationInterlock:
    def __init__(self) -> None:
        self.owner: ExclusiveMutationLease | None = None
        self.invocation: _InvocationRecord | None = None
        self._entries: list[_InvocationRecord] = []
        self._consumed: set[int] = set()

    def _reject_entry(self, spec: Any) -> None:
        if not spec.modifies:
            return
        if self.owner is not None or self.invocation is not None or (
            spec.exclusive_mutation and any(entry.spec.modifies for entry in self._entries)
        ):
            details = {"reason": "REENTRANT_MUTATION_BLOCKED", "execution_started": False,
                       "blocked_tool": spec.name}
            if isinstance(self.owner, ExclusiveMutationLease):
                details["exclusive_tool"] = self.owner.spec.name
            raise BridgeError(ErrorCode.OPERATION_FAILED,
                              "An exclusive structured mutation is active; finish it before starting another mutation.",
                              details)

    def check_owner(self, registry: Any, spec: Any, context: Any) -> None:
        if not spec.modifies:
            return
        permit = self.invocation
        if self.owner is None and permit is None and not spec.exclusive_mutation:
            return
        if (not isinstance(permit, _InvocationRecord) or not any(entry is permit for entry in self._entries)
                or permit.registry is not registry or permit.spec is not spec or permit.context is not context
                or registry.get(spec.name) is not spec or context.registry is not registry
                or permit.lease is None or self.owner is not permit.lease
                or getattr(context, "exclusive_mutation_lease", None) is not permit.lease
                or permit.lease.registry is not registry or permit.lease.spec is not spec
                or permit.lease.context is not context or permit.lease.params is not permit.params
                or permit.lease.call_id is not permit.call_id):
            raise _lost()

    def consume(self, registry: Any, spec: Any, params: Mapping[str, Any], context: Any,
                permit: InvocationPermit) -> None:
        record = self._entries[-1] if self._entries else None
        if (not isinstance(permit, InvocationPermit) or record is None
                or id(permit) in self._consumed or record.continuation_id != id(permit)
                or record.registry is not registry or record.spec is not spec
                or record.params is not params or record.context is not context
                or permit.registry is not registry or permit.spec is not spec
                or permit.params is not params or permit.context is not context
                or permit.call_id is not record.call_id
                or (spec.exclusive_mutation and self.invocation is not record)):
            raise BridgeError(ErrorCode.OPERATION_FAILED,
                              "The structured-call continuation is absent, reused or belongs to another call.",
                              {"reason": "INVALID_INVOCATION_CONTINUATION", "execution_started": False})
        self.check_owner(registry, spec, context)
        self._consumed.add(id(permit))

    @contextmanager
    def entry(self, registry: Any, spec: Any, params: Mapping[str, Any], context: Any) -> Iterator[InvocationPermit]:
        self._reject_entry(spec)  # Before factories, providers, checkpoints or handler callbacks.
        call_id = object()
        permit = InvocationPermit(registry, spec, context, params, call_id)
        lease = ExclusiveMutationLease(registry, spec, context, params, call_id) if spec.exclusive_mutation else None
        record = _InvocationRecord(registry, spec, context, params, call_id, lease, id(permit))
        previous = getattr(context, "exclusive_mutation_lease", None)
        if lease is not None:
            self.owner, self.invocation = lease, record
            context.exclusive_mutation_lease = lease
        self._entries.append(record)
        primary: BaseException | None = None
        try:
            yield permit
        except BaseException as error:
            primary = error
            raise
        finally:
            drift = None
            if lease is not None:
                try:
                    self.check_owner(registry, spec, context)
                except BridgeError as error:
                    drift = error
                # Never unlock or overwrite a newer/foreign owner. Lifecycle
                # reset does not touch this service, including during native C.
                if self.owner is lease:
                    self.owner = None
                if self.invocation is record:
                    self.invocation = None
                if getattr(context, "exclusive_mutation_lease", None) is lease:
                    context.exclusive_mutation_lease = previous
            self._consumed.discard(id(permit))
            if self._entries and self._entries[-1] is record:
                self._entries.pop()
            if drift is not None:
                if isinstance(primary, BridgeError):
                    primary.context["exclusive_mutation_lease_drift"] = dict(drift.context)
                elif primary is not None:
                    # Preserve even an unexpected exception's identity. The
                    # executor normally converts it before this scope unwinds.
                    with suppress(AttributeError, TypeError):
                        primary.exclusive_mutation_lease_drift = dict(drift.context)
                else:
                    raise drift
