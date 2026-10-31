"""Persistent Scene-job ownership and one-use local turn origins.

No Blender APIs or permission providers run here. Handles are identities in
private records, never context-held or wire-supplied authorization.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .errors import BridgeError, ErrorCode
from .scene_job_authority import bind_permissions

TURN_METHOD = "jobs._scene_turn"
INSPECTION_TURN_METHOD = "jobs._inspection_turn"
SAFE_METHODS = ("bridge.status", "jobs.inspect", "jobs.list", "jobs.cancel", "toolsets.list",
                "toolsets.enable", "toolsets.disable")


def refused(reason: str, message: str = "Scene-job ownership does not authorize this action.") -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, message, {"reason": reason, "execution_started": False})


@dataclass(frozen=True, slots=True, eq=False)
class SceneJobReservation:
    pass


@dataclass(frozen=True, slots=True, eq=False)
class SceneTurn:
    pass


@dataclass(frozen=True, slots=True, eq=False)
class InspectionTurn:
    """One read-only scheduler entry; never accepted by Scene write turns."""
    pass


@dataclass(frozen=True, slots=True, eq=False)
class _SchedulerOrigin:
    pass


@dataclass(slots=True)
class _Reservation:
    handle: SceneJobReservation
    job: Any
    origin_id: int | None
    allowlist: tuple[Any, ...]
    epoch: int
    authority: Any = None
    stopped: str = ""
    turn: SceneTurn | None = None
    accepted: bool = False


@dataclass(slots=True)
class _Turn:
    token: SceneTurn
    owner: _Reservation
    phase: str
    revision: int
    used: bool = False
    context: Any = None
    spec: Any = None
    params: Any = None
    invocation: Any = None
    binding: Any = None
    consumer_id: int | None = None
    scheduler_id: int | None = None
    check_only: bool = False
    permission_denial: BridgeError | None = None
    inspection_entry_proof: Any = None
    inspection_spec: tuple = ()
    inspection_deadline: float = float("inf")


_services: dict[int, tuple[SceneJobReservation, Any]] = {}
_inspection_origins: dict[int, tuple] = {}


def reservation_service(handle: SceneJobReservation):
    item = _services.get(id(handle))
    if item is None or item[0] is not handle:
        raise refused("SCENE_RESERVATION_LOST")
    return item[1]


class SceneJobReservations:
    def __init__(self, registry: Any):
        self.registry = registry
        self.epoch = 0
        self.owner: _Reservation | None = None
        self._retained: dict[int, _Reservation] = {}
        self._turns: dict[int, _Turn] = {}
        self._inspection_turns: dict[int, _Turn] = {}
        self._inspection_proofs: dict[int, tuple] = {}
        self._scheduler: tuple[int, Any] | None = None
        self._scheduler_busy = False

    @contextmanager
    def scheduler_scope(self, handle: SceneJobReservation):
        # Before context factories/providers. Structured callbacks cannot turn a
        # reservation receipt into scheduler authority, even from readonly RPCs.
        if self._scheduler_busy or self._scheduler is not None or self.registry._mutation_interlock._entries:
            raise refused("SCENE_SCHEDULER_REENTRY")
        self._scheduler_busy = True  # Before allocations that can invoke finalizers.
        receipt = None
        try:
            owner = self._owner(handle)
            if not owner.accepted:
                raise refused("SCENE_START_NOT_ACCEPTED")
            origin = _SchedulerOrigin()
            receipt = (id(origin), owner)
            self._scheduler = receipt  # ID only; the capability remains caller-local.
            yield origin
        finally:
            if self._scheduler is receipt:
                self._scheduler = None
                self._scheduler_busy = False

    def _check_scheduler(self, origin: Any, owner: Any):
        receipt = self._scheduler
        if (type(origin) is not _SchedulerOrigin or receipt is None or receipt[0] != id(origin)
                or receipt[1] is not owner or self.registry._mutation_interlock._entries):
            raise refused("INVALID_SCENE_SCHEDULER_ORIGIN")

    def capture_allowlist(self) -> tuple[Any, ...]:
        return tuple(self.registry._tools[name] for name in SAFE_METHODS if name in self.registry._tools)

    def check_allowlist(self, allowlist: tuple[Any, ...]) -> None:
        if any(spec.modifies or self.registry._tools.get(spec.name) is not spec for spec in allowlist):
            raise refused("SCENE_STATUS_SPEC_CHANGED")

    def reserve(self, job: Any, origin: Any, *, allowlist: tuple[Any, ...] | None = None,
                authority: Any = None) -> SceneJobReservation:
        if self.owner is not None or self._retained:
            raise refused("SCENE_RESERVATION_BUSY")
        frozen = self.capture_allowlist() if allowlist is None else allowlist
        self.check_allowlist(frozen)
        if authority is not None:
            authority.check()
            if authority.registry is not self.registry:
                raise refused("SCENE_START_ENTRY_LOST")
        handle = SceneJobReservation()
        record = _Reservation(handle, job, id(origin), frozen, self.epoch, authority=authority)
        self.owner = record
        self._retained[id(handle)] = record
        _services[id(handle)] = handle, self
        return handle

    def check_unaccepted(self, handle: SceneJobReservation, origin: Any):
        record = self._owner(handle)
        if record.accepted or record.turn is not None or record.origin_id != id(origin):
            raise refused("INVALID_SCENE_START_ORIGIN")
        return record

    def activate(self, handle: SceneJobReservation, origin: Any) -> None:
        record = self.check_unaccepted(handle, origin)
        self._live(record)
        record.accepted, record.origin_id = True, None

    def discard_unaccepted(self, handle: SceneJobReservation, origin: Any) -> None:
        self.check_unaccepted(handle, origin)
        self._remove(handle)

    def _owner(self, handle: SceneJobReservation) -> _Reservation:
        record = self._retained.get(id(handle))
        if record is None or record.handle is not handle or self.owner is not record:
            raise refused("SCENE_RESERVATION_LOST")
        return record

    def _live(self, record: _Reservation) -> None:
        self._owner(record.handle)
        job = record.job
        if record.authority is not None:
            record.authority.check()
            if job.authority is not record.authority:
                raise refused("SCENE_START_AUTHORITY_LOST")
        origin = getattr(job, "state_origin", None)
        if origin is not None:
            state, store, epoch = origin
            if getattr(state, "_artist_task_plans", None) is not store or store.evidence_epoch != epoch:
                raise refused("SCENE_RUNTIME_RESET")
        if getattr(job, "pending", None) is not None:
            job.checkpoint_manager.check_pending_owner(job.pending, record.handle)
        job.lifetime.check()
        if record.stopped or job.cancel_reason or time.monotonic() >= job.deadline or record.epoch != self.epoch:
            raise BridgeError(ErrorCode.TIMEOUT, "Scene job stopped before its next safe action.",
                              {"reason": record.stopped or job.cancel_reason, "job_deadline_expired": time.monotonic() >= job.deadline,
                               "job_cancel_requested": bool(record.stopped or job.cancel_reason), "execution_started": False})
        turn = self._turns.get(id(record.turn)) or self._inspection_turns.get(id(record.turn))
        entries = self.registry._mutation_interlock._entries
        if turn is not None and turn.permission_denial is not None and entries and entries[-1] is turn.invocation:
            raise turn.permission_denial
        self.check_allowlist(record.allowlist)

    def check_job(self, handle: SceneJobReservation) -> None:
        self._live(self._owner(handle))

    def issue_turn(self, handle: SceneJobReservation, phase: str, revision: int, *, origin: Any = None,
                   check_only: bool = False) -> SceneTurn:
        record = self._owner(handle)
        self._check_scheduler(origin, record)
        self._live(record)
        if record.turn is not None or record.job.revision != revision or record.job.phase != phase:
            raise refused("SCENE_TURN_SEQUENCE_CHANGED")
        token = SceneTurn()
        record.turn = token
        self._turns[id(token)] = _Turn(token, record, phase, revision, scheduler_id=id(origin), check_only=check_only)
        return token

    def _turn(self, token: SceneTurn) -> _Turn:
        record = self._turns.get(id(token))
        if record is None or record.token is not token or record.owner.turn is not token:
            raise refused("SCENE_TURN_LOST")
        self._live(record.owner)
        if (self._scheduler is None or self._scheduler[0] != record.scheduler_id
                or self._scheduler[1] is not record.owner):
            raise refused("INVALID_SCENE_SCHEDULER_ORIGIN")
        if not record.check_only and not record.owner.job.lifetime.delivered.is_set():
            raise refused("SCENE_START_NOT_DELIVERED")
        return record

    def issue_inspection_turn(self, handle, phase, revision, *, origin=None, check_only=False):
        owner = self._owner(handle)
        self._check_scheduler(origin, owner)
        self._live(owner)
        if (owner.job.method != INSPECTION_TURN_METHOD or owner.job.pending is not None
                or owner.turn is not None or owner.job.phase != phase or owner.job.revision != revision
                or (not check_only and not owner.job.lifetime.delivered.is_set())):
            raise refused("INSPECTION_TURN_SEQUENCE_CHANGED")
        token = InspectionTurn()
        owner.turn = token
        row = _Turn(token, owner, phase, revision, scheduler_id=id(origin), check_only=check_only,
                    inspection_deadline=min(owner.job.deadline, time.monotonic()+60.))
        self._inspection_turns[id(token)] = row
        _inspection_origins[id(token)] = (token, self, row, owner, self._inspection_turns,
                                          self._inspection_proofs, self._scheduler, None)
        return token

    def _inspection_turn(self, token, _get=dict.get):
        origin = _get(_inspection_origins, id(token))
        if (type(token) is not InspectionTurn or type(origin) is not tuple or len(origin) != 8
                or origin[0] is not token or origin[1] is not self):
            raise refused("INSPECTION_TURN_LOST")
        _token, _service, row, owner, turns, proofs, scheduler, entry_proof = origin
        if (type(row) is not _Turn or type(owner) is not _Reservation or self._inspection_turns is not turns
                or self._inspection_proofs is not proofs or self._scheduler is not scheduler
                or _get(turns, id(token)) is not row or row.token is not token or row.owner is not owner
                or owner.turn is not token):
            raise refused("INSPECTION_TURN_ORIGIN_CHANGED")
        if entry_proof is not None:
            if _get(proofs, id(token)) is not entry_proof or row.inspection_entry_proof is not entry_proof:
                raise refused("INSPECTION_ENTRY_PROVENANCE_CHANGED")
            function, code, namespace, defaults, keywords, cells, contents = entry_proof
            if (type(function) is not type(lambda: None) or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not keywords or function.__closure__ is not cells
                    or len(cells or ()) != len(contents)
                    or any(actual is not cell or actual.cell_contents is not value
                           for actual, (cell, value) in zip(cells or (), contents, strict=True))):
                raise refused("INSPECTION_ENTRY_SOURCE_CHANGED")
            function()
        self._live(row.owner)
        if time.monotonic() >= row.inspection_deadline:
            raise BridgeError(ErrorCode.TIMEOUT, "Inspection turn exceeded its unchanged 60-second bound.",
                              {"reason": "INSPECTION_TURN_DEADLINE", "inspection_status": "INCOMPLETE", "ready": False})
        if not row.check_only and not row.owner.job.lifetime.delivered.is_set():
            raise refused("SCENE_START_NOT_DELIVERED")
        return row

    def current_inspection(self, context, _values=dict.values):
        rows = []
        for origin in _values(_inspection_origins):
            if type(origin) is not tuple or len(origin) != 8 or origin[1] is not self:
                continue
            row = origin[2]
            if type(row) is not _Turn:
                raise refused("INSPECTION_TURN_ORIGIN_CHANGED")
            if row.context is context:
                rows.append(row)
        if len(rows) != 1:
            raise refused("INSPECTION_TURN_LOST")
        self.check_inspection_turn(rows[0].token)
        return rows[0]

    def check_inspection_turn(self, token):
        row = self._inspection_turn(token)
        entries = self.registry._mutation_interlock._entries
        if (not row.used or row.invocation is None or not entries or entries[-1] is not row.invocation
                or row.owner.job.phase != row.phase or row.owner.job.revision != row.revision
                or row.spec.modifies or row.spec.name != INSPECTION_TURN_METHOD
                or any(getattr(row.spec, name) is not value for name, value in row.inspection_spec)):
            raise refused("INSPECTION_TURN_LOST")
        self.registry._mutation_interlock.check_owner(self.registry, row.spec, row.context)

    def _inspection_turn_fields(self, token, entry_check, _get=dict.get):
        """Live replay; caller holds a source-verified local static-field union."""
        origin = _get(_inspection_origins, id(token))
        if (type(token) is not InspectionTurn or type(origin) is not tuple or len(origin) != 8
                or origin[0] is not token or origin[1] is not self):
            raise refused("INSPECTION_TURN_LOST")
        _token, _service, row, owner, turns, proofs, scheduler, entry_proof = origin
        if (type(row) is not _Turn or type(owner) is not _Reservation or self._inspection_turns is not turns
                or self._inspection_proofs is not proofs or self._scheduler is not scheduler
                or _get(turns, id(token)) is not row or row.token is not token or row.owner is not owner
                or owner.turn is not token):
            raise refused("INSPECTION_TURN_ORIGIN_CHANGED")
        if entry_proof is not None:
            if _get(proofs, id(token)) is not entry_proof or row.inspection_entry_proof is not entry_proof:
                raise refused("INSPECTION_ENTRY_PROVENANCE_CHANGED")
            entry_check(entry_proof)
        self._live(row.owner)
        if time.monotonic() >= row.inspection_deadline:
            raise BridgeError(ErrorCode.TIMEOUT, "Inspection turn exceeded its unchanged 60-second bound.",
                              {"reason": "INSPECTION_TURN_DEADLINE", "inspection_status": "INCOMPLETE", "ready": False})
        if not row.check_only and not row.owner.job.lifetime.delivered.is_set():
            raise refused("SCENE_START_NOT_DELIVERED")
        return row

    def _inspection_current_fields(self, context, entry_check, interlock_check, _values=dict.values):
        rows = []
        for origin in _values(_inspection_origins):
            if type(origin) is not tuple or len(origin) != 8 or origin[1] is not self:
                continue
            row = origin[2]
            if type(row) is not _Turn:
                raise refused("INSPECTION_TURN_ORIGIN_CHANGED")
            if row.context is context:
                rows.append(row)
        if len(rows) != 1:
            raise refused("INSPECTION_TURN_LOST")
        self._inspection_check_turn_fields(rows[0].token, entry_check, interlock_check)
        return rows[0]

    def _inspection_check_turn_fields(self, token, entry_check, interlock_check):
        row = self._inspection_turn_fields(token, entry_check)
        entries = self.registry._mutation_interlock._entries
        if (not row.used or row.invocation is None or not entries or entries[-1] is not row.invocation
                or row.owner.job.phase != row.phase or row.owner.job.revision != row.revision
                or row.spec.modifies or row.spec.name != INSPECTION_TURN_METHOD
                or any(getattr(row.spec, name) is not value for name, value in row.inspection_spec)):
            raise refused("INSPECTION_TURN_LOST")
        interlock_check()
        self.registry._mutation_interlock.check_owner(self.registry, row.spec, row.context)

    def close_inspection_turn(self, token, _pop=dict.pop):
        origin = _pop(_inspection_origins, id(token), None)
        if type(origin) is not tuple or len(origin) != 8 or origin[0] is not token or origin[1] is not self:
            return
        _token, _service, row, owner, turns, proofs, _scheduler, _entry = origin
        _pop(proofs, id(token), None)
        _pop(turns, id(token), None)
        if type(row) is _Turn and type(owner) is _Reservation and owner.turn is token:
            owner.turn = None

    def bind_inspection_proof(self, token, binding, proof, _get=dict.get):
        origin = _get(_inspection_origins, id(token))
        if (type(origin) is not tuple or len(origin) != 8 or origin[0] is not token or origin[1] is not self
                or self._inspection_turns is not origin[4] or self._inspection_proofs is not origin[5]):
            raise refused("INSPECTION_ENTRY_PROVENANCE_CHANGED")
        row = _get(origin[4], id(token))
        if (type(row) is not _Turn or row is not origin[2] or row.token is not token or not row.used or row.binding is not binding
                or row.context is not binding.context or binding.callback.entry_proof is not proof):
            raise refused("INSPECTION_ENTRY_PROVENANCE_CHANGED")
        self._inspection_proofs[id(token)] = proof
        row.inspection_entry_proof = proof
        _inspection_origins[id(token)] = (*origin[:7], proof)

    def check_entry(self, spec: Any, context: Any, turn: SceneTurn | None = None) -> None:
        if type(turn) is InspectionTurn:
            row = self._inspection_turn(turn)
            if (row.used or spec.name != INSPECTION_TURN_METHOD or spec.modifies or spec.remote
                    or self.registry._tools.get(INSPECTION_TURN_METHOD) is not spec
                    or row.owner.job.phase != row.phase or row.owner.job.revision != row.revision):
                raise refused("INVALID_INSPECTION_TURN_ORIGIN")
            row.used, row.context, row.spec = True, context, spec
            row.inspection_spec = tuple((name, getattr(spec, name)) for name in type(spec).__slots__)
            return
        if turn is not None:
            record = self._turn(turn)
            if (record.used or spec.name != TURN_METHOD or self.registry.get(TURN_METHOD) is not spec
                    or record.owner.job.revision != record.revision or record.owner.job.phase != record.phase):
                raise refused("INVALID_SCENE_TURN_ORIGIN")
            record.used = True
            record.context, record.spec = context, spec
            return
        if spec.name in {TURN_METHOD, INSPECTION_TURN_METHOD}:
            raise refused("INVALID_SCENE_TURN_ORIGIN")
        if not self._retained and self.owner is None:
            return
        owner = self.owner
        if owner is not None and any(spec is item for item in owner.allowlist) and not spec.modifies:
            self.check_allowlist(owner.allowlist)
            if owner.turn is not None:
                bind_permissions(context, self)
            return
        raise refused("SCENE_JOB_RESERVATION_BLOCKED", "A Scene job owns the current evaluation context; inspect or cancel it first.")

    def bind_invocation(self, token: SceneTurn, permit: Any, params: Any) -> None:
        record = self._inspection_turn(token) if type(token) is InspectionTurn else self._turn(token)
        entries = self.registry._mutation_interlock._entries
        invocation = entries[-1] if entries else None
        if (not record.used or record.invocation is not None or invocation is None
                or invocation.continuation_id != id(permit) or invocation.context is not record.context
                or invocation.spec is not record.spec or invocation.params is not params):
            raise refused("INVALID_SCENE_TURN_ORIGIN")
        record.params, record.invocation = params, invocation

    def scheduled(self, spec: Any, context: Any) -> bool:
        if spec.name == INSPECTION_TURN_METHOD:
            return any(type(origin) is tuple and len(origin) == 8 and origin[1] is self
                       and type(origin[2]) is _Turn and origin[2].used and origin[2].spec is spec
                       and origin[2].context is context and origin[2].invocation is not None
                       and any(item is origin[2].invocation for item in self.registry._mutation_interlock._entries)
                       for origin in dict.values(_inspection_origins))
        return any(record.used and record.spec is spec and record.context is context
                   and record.invocation is not None and any(item is record.invocation for item in self.registry._mutation_interlock._entries)
                   for record in self._turns.values())

    def current(self, context: Any) -> _Turn:
        records = [record for record in self._turns.values() if record.context is context]
        if len(records) != 1:
            raise refused("SCENE_TURN_LOST")
        record = records[0]
        self.check_turn(record.token)
        return record

    def permission_turn(self):
        """Require retained Scene proof only for the exact top TURN entry."""
        entries = self.registry._mutation_interlock._entries
        entry = entries[-1] if entries else None
        if entry is None or entry.spec.name not in {TURN_METHOD, INSPECTION_TURN_METHOD}:
            return None
        record = self.current_inspection(entry.context) if entry.spec.name == INSPECTION_TURN_METHOD else self.current(entry.context)
        if record.invocation is not entry or record.owner.authority is None:
            raise refused("SCENE_START_AUTHORITY_LOST")
        return record

    def permission_parent(self):
        """Observe nested readonly grants without imposing the parent's grants."""
        owner = self.owner
        if owner is None or owner.turn is None:
            return None
        record = self._inspection_turn(owner.turn) if type(owner.turn) is InspectionTurn else self._turns.get(id(owner.turn))
        if (record is None or record.owner is not owner or record.owner.authority is None
                or not any(item is record.invocation for item in self.registry._mutation_interlock._entries)):
            return None
        return record

    @staticmethod
    def note_permission_denial(turn, error):
        if turn.permission_denial is None:
            turn.permission_denial = error

    def note_permission_snapshot(self, turn, values):
        required = [item.value for item in turn.owner.authority.required_permissions]
        denied = [item for item in required if not values.get(item, False)]
        if denied:
            self.note_permission_denial(turn, BridgeError(ErrorCode.PERMISSION_DENIED, "Blender-side permission denied.",
                                                         {"required": required, "missing_permissions": denied}))

    def check_permission_turn(self, token):
        if type(token) is InspectionTurn:
            self.check_inspection_turn(token)
        else:
            self.check_turn(token)

    def check_turn(self, token: SceneTurn) -> None:
        record = self._turn(token)
        if (not record.used or record.invocation is None
                or not any(item is record.invocation for item in self.registry._mutation_interlock._entries)
                or record.owner.job.revision != record.revision or record.owner.job.phase != record.phase):
            raise refused("SCENE_TURN_LOST")
        self.registry._mutation_interlock.check_owner(self.registry, record.spec, record.context)

    def checkpoint_access(self, token: SceneTurn, handle: SceneJobReservation, manager: Any, consumer: Any) -> None:
        record = self._turn(token)
        self.check_turn(token)
        if (record.owner.handle is not handle or record.owner.job.checkpoint_manager is not manager
                or record.binding is None or not record.binding.active or record.consumer_id != id(consumer)
                or consumer is None or record.phase not in {"checkpoint_before", "checkpoint_after"}
                or record.invocation.continuation_id not in self.registry._mutation_interlock._consumed):
            raise refused("OWNED_PENDING_ACCESS_REFUSED")
        record.binding.check_identity(TURN_METHOD)

    def check_pending_access(self, token: SceneTurn, handle: SceneJobReservation, manager: Any) -> None:
        self.check_turn(token)
        record = self._turn(token)
        if record.owner.handle is not handle or record.owner.job.checkpoint_manager is not manager:
            raise refused("OWNED_PENDING_ACCESS_REFUSED")

    def close_turn(self, token: SceneTurn) -> None:
        record = self._turns.get(id(token))
        if record is None or record.token is not token:
            return
        del self._turns[id(token)]
        if record.owner.turn is token:
            record.owner.turn = None

    def request_stop(self, handle: SceneJobReservation, reason: str) -> None:
        self._owner(handle).stopped = reason

    def invalidate(self, reason: str) -> None:
        self.epoch += 1
        for record in self._retained.values():
            record.stopped = reason

    def check_retirement(self, handle: SceneJobReservation, origin: Any) -> None:
        record = self._owner(handle)
        self._check_scheduler(origin, record)
        if record.turn is not None:
            raise refused("SCENE_TURN_STILL_ACTIVE")

    def release(self, handle: SceneJobReservation, *, origin: Any = None) -> None:
        self.check_retirement(handle, origin)
        self._remove(handle)

    def _remove(self, handle: SceneJobReservation) -> None:
        record = self._owner(handle)
        self._retained.pop(id(handle))
        if self.owner is record:
            self.owner = None
        item = _services.get(id(handle))
        if item is not None and item[0] is handle:
            _services.pop(id(handle))
