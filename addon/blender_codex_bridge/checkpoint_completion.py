"""Retained canonical native-push events; not a Python sandbox.

Consumers remain scheduler-local. Diagnostic bindings and copied event objects
cannot authorize a completion. No callback runs between event mint and consume.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from .errors import BridgeError, ErrorCode
from .operation_lease import InvocationPermit


def _refused() -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED,
                       "Native checkpoint completion has no canonical completed push.",
                       {"native_push_completion_valid": False, "execution_started": False})


@dataclass(frozen=True, slots=True, eq=False)
class NativePushEvent:
    """Identity only; construction or copying does not grant authority."""


@dataclass(frozen=True, slots=True, eq=False)
class NativePushConsumer:
    """Local capability, never stored on the context or an admission binding."""

    def __call__(self) -> None:
        raise _refused()


@dataclass(frozen=True, slots=True, eq=False)
class _ConsumerRecord:
    consumer_id: int
    manager: Any
    binding: Any
    registry: Any
    spec: Any
    context: Any
    params: Any
    call_id: Any
    callback: Any
    readonly_callback: Any
    native_callback: Any
    delegates: tuple[Any, ...]
    final_check: Callable[[], None]
    invocation: Any


@dataclass(slots=True, eq=False)
class _Call:
    record: _ConsumerRecord
    guard: Any = None
    completed: int = 0


@dataclass(slots=True, eq=False)
class _Delivery:
    event: NativePushEvent
    record: _ConsumerRecord
    claimed: set[int] = field(default_factory=set)
    binding_claimed: bool = False


_consumers: dict[int, _ConsumerRecord] = {}
_calls: dict[int, _Call] = {}
_deliveries: list[_Delivery] = []
_stopped: dict[int, BaseException] = {}


def _identity(record: _ConsumerRecord) -> None:
    if record.consumer_id in _stopped:
        raise _stopped[record.consumer_id]
    binding = record.binding
    binding.check_identity(record.spec.name)
    if (not binding.matches(record.spec, record.params, record.context)
            or binding.call_id is not record.call_id or binding.callback is not record.callback
            or binding.readonly_callback is not record.readonly_callback
            or binding.native_push_callback is not record.native_callback
            or not any(entry is record.invocation for entry in record.registry._mutation_interlock._entries)):
        raise _refused()


@contextmanager
def native_push_consumer(registry: Any, permit: InvocationPermit, binding: Any,
                         manager: Any, final_check: Callable[[], None]) -> Iterator[NativePushConsumer]:
    entries = registry._mutation_interlock._entries
    entry = entries[-1] if entries else None
    if (type(permit) is not InvocationPermit or entry is None or entry.continuation_id != id(permit)
            or id(permit) in registry._mutation_interlock._consumed
            or entry.registry is not registry or entry.spec is not binding.spec
            or entry.context is not binding.context or entry.params is not binding.params
            or entry.call_id is not permit.call_id or permit.registry is not registry
            or permit.spec is not entry.spec or permit.context is not entry.context or permit.params is not entry.params):
        raise _refused()
    owner = binding.callback
    declare = getattr(owner, "native_push_delegates", None)
    delegates = () if declare is None else declare()
    if type(delegates) is not tuple or len(delegates) > 16 or len({id(item) for item in delegates}) != len(delegates):
        raise _refused()
    consumer = NativePushConsumer()
    record = _ConsumerRecord(id(consumer), manager, binding, registry, entry.spec, entry.context,
                             entry.params, binding.call_id, binding.callback, binding.readonly_callback,
                             binding.native_push_callback, delegates, final_check, entry)
    _identity(record)
    _consumers[id(consumer)] = record
    try:
        yield consumer
    finally:
        _consumers.pop(id(consumer), None)
        _calls.pop(id(consumer), None)
        _stopped.pop(id(consumer), None)


def authenticated_checkpoint(method: Callable[..., Any]) -> Callable[..., Any]:
    """Arm a specific manager call before its first provider or native read."""
    @wraps(method)
    def wrapped(manager: Any, *args: Any, **kwargs: Any) -> Any:
        consumer = kwargs.get("after_native_push")
        if not isinstance(consumer, NativePushConsumer):
            return method(manager, *args, **kwargs)
        record = _consumers.get(id(consumer))
        if record is None or record.manager is not manager or id(consumer) in _calls:
            raise _refused()
        if record.consumer_id in _stopped:
            raise _stopped[record.consumer_id]
        call = _Call(record)
        _calls[id(consumer)] = call
        try:
            return method(manager, *args, **kwargs)
        finally:
            if _calls.get(id(consumer)) is call:
                del _calls[id(consumer)]
    return wrapped


def bind_native_push_guard(manager: Any, guard: Any) -> None:
    consumer = guard.after_native_push
    if isinstance(consumer, NativePushConsumer):
        call = _calls.get(id(consumer))
        if call is None or call.record.manager is not manager or call.guard is not None:
            raise _refused()
        call.guard = guard


def issue_native_push_completion(manager: Any, guard: Any) -> None:
    """Called only after this guard's retained native operator returned FINISHED."""
    consumer = guard.after_native_push
    if not isinstance(consumer, NativePushConsumer):
        consumer()  # Legacy observation, with no canonical event authority.
        return
    call = _calls.get(id(consumer))
    if (call is None or call.record is not _consumers.get(id(consumer))
            or call.record.manager is not manager or call.guard is not guard
            or guard.native_snapshots != call.completed + 1):
        raise _refused()
    call.completed += 1  # Burn before callbacks, including a failing callback.
    record = call.record
    _identity(record)
    event = NativePushEvent()
    # Mint and consume before any extensible hook; no context-held event grant.
    pending = manager._native_push_pending
    pending[id(event)] = (event, call, record)
    stored = pending.pop(id(event), None)
    if stored is None or stored[0] is not event or stored[1] is not call or stored[2] is not record:
        raise _refused()
    delivery = _Delivery(event, record)
    _deliveries.append(delivery)
    try:
        record.binding.after_native_push(event)
        record.final_check()
    except BaseException as error:
        _stopped[id(consumer)] = error
        raise
    finally:
        if _deliveries and _deliveries[-1] is delivery:
            _deliveries.pop()


def claim_binding_completion(binding: Any, event: Any) -> None:
    delivery = _deliveries[-1] if _deliveries else None
    if (delivery is None or delivery.event is not event or delivery.record.binding is not binding
            or delivery.binding_claimed):
        raise _refused()
    _identity(delivery.record)
    delivery.binding_claimed = True


def claim_native_push_completion(context: Any, method: str, owner: Any) -> None:
    delivery = _deliveries[-1] if _deliveries else None
    if (delivery is None or not delivery.binding_claimed or delivery.record.context is not context
            or delivery.record.spec.name != method or delivery.record.callback is not owner
            or id(owner) in delivery.claimed):
        raise _refused()
    _identity(delivery.record)
    delivery.claimed.add(id(owner))


def claim_native_push_delegate(owner: Any) -> None:
    delivery = _deliveries[-1] if _deliveries else None
    if (delivery is None or not delivery.binding_claimed
            or id(delivery.record.callback) not in delivery.claimed
            or not any(item is owner for item in delivery.record.delegates) or id(owner) in delivery.claimed):
        raise _refused()
    _identity(delivery.record)
    delivery.claimed.add(id(owner))
