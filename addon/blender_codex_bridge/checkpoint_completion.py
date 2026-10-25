"""Retained canonical native-push events; not a Python sandbox.

Consumers remain scheduler-local. Diagnostic bindings and copied event objects
cannot authorize a completion. No callback runs between event mint and consume.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar, cast

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
class MarkerWriteEvent:
    """Opaque receipt identity; never a marker value or write authority."""


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
    marker_callback: Any = None
    marker_binding_hook: Any = None
    marker_services: tuple[Any, ...] = ()


@dataclass(slots=True, eq=False)
class _Call:
    record: _ConsumerRecord
    guard: Any = None
    completed: int = 0
    marker_completed: int = 0
    marker_scope: Any = None


@dataclass(slots=True, eq=False)
class _Delivery:
    event: NativePushEvent
    record: _ConsumerRecord
    claimed: set[int] = field(default_factory=set)
    binding_claimed: bool = False


@dataclass(slots=True, eq=False)
class _MarkerDelivery:
    event: MarkerWriteEvent
    record: _ConsumerRecord
    evidence: tuple
    binding_claimed: bool = False
    owner_claimed: bool = False


_consumers: dict[int, _ConsumerRecord] = {}
_calls: dict[int, _Call] = {}
_deliveries: list[_Delivery] = []
_stopped: dict[int, BaseException] = {}
_marker_deliveries: list[_MarkerDelivery] = []


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
                             binding.native_push_callback, delegates, final_check, entry,
                             binding.marker_write_callback,
                             type(binding).after_marker_write if binding.marker_write_callback is not None else None,
                             tuple((name, getattr(entry.context, name, None)) for name in (
                                 "state", "request_lifecycle", "check_final_request", "check_final_job", "checkpoints"))
                             if binding.marker_write_callback is not None else ())
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
            if record is not None and record.marker_callback is not None:
                raise _marker_error(record)
            raise _refused()
        if record.consumer_id in _stopped:
            raise _stopped[record.consumer_id]
        if record.marker_callback is not None:
            if _marker_deliveries or _deliveries:
                raise _marker_error(record)
            _marker_identity(record)
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
            record = _consumers.get(id(consumer))
            if record is not None and record.marker_callback is not None:
                raise _marker_error(record)
            raise _refused()
        call.guard = guard
        guard.marker_completion = call.record.marker_callback is not None


def _marker_error(record: _ConsumerRecord | None = None, cause: Exception | None = None) -> BridgeError:
    if record is not None:
        previous = _stopped.get(record.consumer_id) or record.binding.stopped
        if isinstance(previous, BridgeError):
            return previous
    error = cause if isinstance(cause, BridgeError) else BridgeError(
        ErrorCode.OPERATION_FAILED, "Checkpoint marker completion has no canonical owned write.",
        {"marker_write_completion_valid": False, "verification_required": True})
    if record is not None:
        _stopped[record.consumer_id] = error
        record.binding.stopped = error
    return error


def _marker_identity(record: _ConsumerRecord) -> None:
    try:
        _identity(record)
        if (record.manager is not record.context.checkpoints
                or record.binding.marker_write_callback is not record.marker_callback
                or type(record.binding).after_marker_write is not record.marker_binding_hook
                or any(getattr(record.context, name, None) is not service for name, service in record.marker_services)):
            raise _marker_error()
        record.final_check()
    except Exception as cause:
        error = _marker_error(record, cause)
        if error is cause:
            raise
        raise error from cause


def check_marker_context(context: Any) -> None:
    """Pin optional marker callers before the generic pure gate reads services."""
    for record in tuple(_consumers.values()):
        if record.context is not context or record.marker_callback is None:
            continue
        try:
            if (record.manager is not context.checkpoints
                    or record.binding.marker_write_callback is not record.marker_callback
                    or type(record.binding).after_marker_write is not record.marker_binding_hook
                    or any(getattr(context, name, None) is not service for name, service in record.marker_services)):
                raise _marker_error()
            _identity(record)
        except Exception as cause:
            error = _marker_error(record, cause)
            if error is cause:
                raise
            raise error from cause


def _marker_record(manager: Any, guard: Any) -> _ConsumerRecord | None:
    consumer = guard.after_native_push
    if not isinstance(consumer, NativePushConsumer):
        return None
    record = _consumers.get(id(consumer))
    if record is None:
        raise _marker_error()
    if record.marker_callback is None:
        return None
    call = _calls.get(id(consumer))
    if call is None or call.record is not record or record.manager is not manager or call.guard is not guard:
        raise _marker_error(record)
    _marker_identity(record)
    return record


MarkerMethod = TypeVar("MarkerMethod", bound=Callable[..., Any])


def authenticated_marker(method: MarkerMethod) -> MarkerMethod:
    """Only the canonical stamp body may issue an optional marker receipt."""
    @wraps(method)
    def wrapped(manager: Any, *args: Any, **kwargs: Any) -> Any:
        guard = kwargs.get("guard")
        record = None if guard is None else _marker_record(manager, guard)
        if record is None:
            return method(manager, *args, **kwargs)
        call = _calls[record.consumer_id]
        if call.marker_scope is not None or _marker_deliveries or _deliveries:
            raise _marker_error(record)
        scope = object()
        retained_guard = call.guard
        call.marker_scope = scope
        try:
            return method(manager, *args, **kwargs)
        except Exception as cause:
            def failed(error: Exception = cause) -> None:
                raise error
            try:
                retained_guard._run("marker_completion", failed)
            except Exception as accounted:
                error = _marker_error(record, accounted)
                if error is accounted:
                    raise
                raise error from accounted
            raise _marker_error(record, cause) from cause
        finally:
            if call.marker_scope is scope:
                call.marker_scope = None
    return cast(MarkerMethod, wrapped)


def check_marker_write(manager: Any, guard: Any) -> None:
    """Optional provider-free provenance check immediately before a stamp write."""
    record = _marker_record(manager, guard)
    if record is not None and (_calls[record.consumer_id].marker_scope is None or _marker_deliveries or _deliveries):
        raise _marker_error(record)


def _freeze_marker_evidence(value: Any) -> tuple:
    def identity(raw: Any, *, optional: bool = False):
        if optional and raw is None:
            return None
        if (type(raw) is not tuple or len(raw) != 2
                or any(type(item) is not int or not 1 <= item <= 2**64 - 1 for item in raw)):
            raise _marker_error()
        return raw[0], raw[1]
    if type(value) is not tuple or len(value) != 2 or type(value[1]) is not tuple or not 1 <= len(value[1]) <= 200:
        raise _marker_error()
    active, records = identity(value[0]), []
    for row in value[1]:
        if (type(row) is not tuple or len(row) != 6 or type(row[3]) is not bool or type(row[4]) is not bool
                or (row[5] is not None and (type(row[5]) is not str or len(row[5]) > 4096))):
            raise _marker_error()
        records.append((identity(row[0]), identity(row[1], optional=True), identity(row[2], optional=True),
                        row[3], row[4], row[5]))
    if len({row[0] for row in records}) != len(records) or active not in {row[0] for row in records}:
        raise _marker_error()
    return active, tuple(records)


def issue_marker_write_completion(manager: Any, guard: Any, expected: Any) -> None:
    """Deliver the predicted full inventory immediately after an actual stamp write."""
    record = _marker_record(manager, guard)
    if record is None:
        return
    try:
        call = _calls[record.consumer_id]
        if (call.marker_scope is None or _marker_deliveries or _deliveries
                or type(guard.marker_writes) is not int or guard.marker_writes != call.marker_completed + 1):
            raise _marker_error()
        evidence = _freeze_marker_evidence(expected)
        call.marker_completed += 1  # Burn before any callback, including failures.
        delivery = _MarkerDelivery(MarkerWriteEvent(), record, evidence)
        _marker_deliveries.append(delivery)
        try:
            record.marker_binding_hook(record.binding, delivery.event)
            if not delivery.binding_claimed or not delivery.owner_claimed:
                raise _marker_error()
            _marker_identity(record)
        finally:
            if _marker_deliveries and _marker_deliveries[-1] is delivery:
                _marker_deliveries.pop()
    except Exception as cause:
        error = _marker_error(record, cause)
        if error is cause:
            raise
        raise error from cause


def claim_binding_marker_completion(binding: Any, event: Any) -> None:
    delivery = _marker_deliveries[-1] if _marker_deliveries else None
    record = delivery.record if delivery is not None else next(
        (item for item in _consumers.values() if item.binding is binding and item.marker_callback is not None), None)
    if (delivery is None or delivery.event is not event or delivery.record.binding is not binding
            or delivery.binding_claimed):
        raise _marker_error(record)
    _marker_identity(delivery.record)
    delivery.binding_claimed = True


def claim_marker_write_completion(context: Any, method: str, owner: Any, event: Any) -> tuple:
    """Consume a canonical marker observation; it grants no mutation authority."""
    delivery = _marker_deliveries[-1] if _marker_deliveries else None
    record = delivery.record if delivery is not None else next(
        (item for item in _consumers.values() if item.context is context and item.callback is owner
         and item.marker_callback is not None), None)
    if (delivery is None or delivery.event is not event or not delivery.binding_claimed or delivery.owner_claimed
            or delivery.record.context is not context or delivery.record.spec.name != method
            or delivery.record.callback is not owner):
        raise _marker_error(record)
    _marker_identity(delivery.record)
    delivery.owner_claimed = True
    return delivery.evidence


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
