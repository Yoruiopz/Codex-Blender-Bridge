"""Bounded native snapshot recovery with explicit, undoable scene markers."""

from __future__ import annotations

import logging
import re
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import islice
from typing import Any

from .checkpoint_completion import (
    authenticated_checkpoint,
    bind_native_push_guard,
    issue_native_push_completion,
)
from .errors import BridgeError, ErrorCode
from .selection import clear_selection_references
from .undo_window import UndoWindow
from .utils import require_blender

LOGGER = logging.getLogger(__name__)
MARKER_KEY = "_codex_bridge_undo_marker"
MAX_SCENES = 200
MAX_UNDO_HOPS = 256
TOKEN_PATTERN = re.compile(r"BCB1:[0-9a-f]{32}:[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class Checkpoint:
    checkpoint_id: str
    description: str
    timestamp: str
    snapshot_marker: str
    sequence: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UndoStep:
    label: str
    before_marker: str
    sequence: int
    kind: str = "operation"
    attempts: int = 1


@dataclass(slots=True)
class MeshEditSession:
    before: UndoStep
    group_id: str
    scene_uid: int
    object_uid: int
    object_name: str
    attempts: int = 1


@dataclass(slots=True)
class _CheckpointGuard:
    """Trusted pure safe point for new bookkeeping, never failed-writer cleanup."""

    before_write: Callable[[], None]
    after_read: Callable[[], None] | None = None
    after_native_push: Callable[[], None] | None = None
    marker_writes: int = 0
    native_snapshots: int = 0
    stopped: BridgeError | None = None

    def check(self, next_write: str) -> None:
        self._run(next_write, self.before_write)

    def complete(self, next_write: str, compare: Callable[[], None] | None = None) -> None:
        def prove() -> None:
            if compare is not None:
                compare()
            if self.after_read is not None:
                self.after_read()
        self._run(next_write, prove)

    def _run(self, next_write: str, callback: Callable[[], None]) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            callback()
        except Exception as cause:
            if isinstance(cause, BridgeError):
                error = cause
            else:
                LOGGER.exception("Checkpoint write guard failed")
                error = BridgeError(ErrorCode.OPERATION_FAILED, "Checkpoint write admission could not be verified.",
                                    {"verification_required": True})
            # Preserve the exact primary denial and measured partial state.
            # Owner loss never authorizes compensating marker writes.
            error.context["checkpoint_authority_rejected"] = True
            error.context.setdefault("checkpoint_bookkeeping", {
                "marker_writes_completed": self.marker_writes,
                "native_snapshots_completed": self.native_snapshots,
                "next_write_rejected": next_write,
                "compensation_performed": False,
            })
            if self.marker_writes or self.native_snapshots:
                error.context.update(execution_started=True, possible_mutation=True, verification_required=True)
            self.stopped = error
            if error is cause:
                raise
            raise error from cause


class CheckpointManager:
    """Navigate to measured native markers, never infer position from a label count."""

    def __init__(self, *, maximum: int = 50) -> None:
        self._checkpoints: deque[Checkpoint] = deque(maxlen=maximum)
        self._undo_steps: deque[UndoStep] = deque(maxlen=maximum * 4)
        self._pending: UndoStep | None = None
        self._editor_session: MeshEditSession | None = None
        self._sequence = 0
        self._prefix = f"BCB1:{uuid.uuid4().hex}:"
        self._window = UndoWindow()
        self._expired_operations = 0
        self.recovery_in_progress = False
        self._native_push_pending: dict[int, Any] = {}

    @staticmethod
    def _ensure_undo_enabled(*, require_object_mode: bool = True) -> Any:
        blender = require_blender()
        preferences = getattr(blender.context.preferences, "edit", None)
        if preferences is not None and not preferences.use_global_undo:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR, "Global Undo is disabled in Blender preferences."
            )
        if getattr(preferences, "undo_steps", None) == 0:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR, "Native undo steps are set to zero in Blender preferences."
            )
        # Scene markers belong to global memfile undo, not editor-specific undo stacks.
        if require_object_mode and blender.context.mode != "OBJECT":
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Verified native snapshot recovery currently requires Object Mode.",
            )
        if len(blender.data.scenes) > MAX_SCENES:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Recovery supports at most 200 scenes.")
        return blender

    def _stamp(self, blender: Any, *, guard: _CheckpointGuard | None = None) -> str:
        scene = blender.context.scene
        expected = self._marker_evidence(blender) if guard is not None else None
        if scene.library is not None or scene.override_library is not None or not scene.is_editable:
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED, "Recovery requires a local editable scene."
            )
        previous = scene.get(MARKER_KEY)
        if previous is not None and not (
            isinstance(previous, str) and TOKEN_PATTERN.fullmatch(previous)
        ):
            raise BridgeError(
                ErrorCode.INVALID_ARGUMENT, "Reserved recovery property contains unrelated data."
            )
        owned = []
        for item in blender.data.scenes:
            value = item.get(MARKER_KEY)
            if isinstance(value, str) and value.startswith(self._prefix):
                if (
                    item.library is not None
                    or item.override_library is not None
                    or not item.is_editable
                ):
                    raise BridgeError(
                        ErrorCode.NOT_IMPLEMENTED,
                        "A recovery marker belongs to nonlocal scene data.",
                    )
                owned.append(item)
        for item in owned:
            if guard is not None:
                guard.check("delete_marker")
                guard.complete("delete_marker", lambda expected=expected: self._compare_markers(blender, expected))
            del item[MARKER_KEY]
            if guard is not None:
                guard.marker_writes += 1
                expected = self._marker_delta(expected, item, None)
        token = self._prefix + uuid.uuid4().hex
        if guard is not None:
            guard.check("set_marker")
            guard.complete("set_marker", lambda: self._compare_markers(blender, expected))
        scene[MARKER_KEY] = token
        if guard is not None:
            guard.marker_writes += 1
            expected = self._marker_delta(expected, scene, token)
            guard.complete("verify_marker", lambda: self._compare_markers(blender, expected))
        return token

    @staticmethod
    def _identity(owner: Any) -> Any:
        if owner is None:
            return None
        pointer = getattr(owner, "as_pointer", None)
        return (int(pointer()), getattr(owner, "session_uid", None)) if callable(pointer) else (id(owner), None)

    def _marker_evidence(self, blender: Any) -> Any:
        scenes = tuple(islice(blender.data.scenes, MAX_SCENES + 1))
        if len(scenes) > MAX_SCENES:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint marker inventory exceeds its bounded Scene profile.")
        records = []
        for scene in scenes:
            value = scene.get(MARKER_KEY)
            if value is not None and (type(value) is not str or len(value) > 4096):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reserved checkpoint metadata requires a bounded literal value.")
            records.append((self._identity(scene), self._identity(scene.library), self._identity(scene.override_library),
                            bool(scene.is_editable), MARKER_KEY in scene, value))
        return self._identity(blender.context.scene), tuple(sorted(records))

    def _compare_markers(self, blender: Any, expected: Any) -> None:
        if self._marker_evidence(blender) != expected:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint Scene ownership or reserved metadata changed; newer values are preserved.",
                              {"checkpoint_marker_unchanged": False, "verification_required": True})

    def _marker_delta(self, expected: Any, scene: Any, value: str | None) -> Any:
        identity = self._identity(scene)
        return expected[0], tuple((*record[:4], value is not None, value) if record[0] == identity else record for record in expected[1])

    def _marker(self, blender: Any) -> str | None:
        values = {
            scene.get(MARKER_KEY)
            for scene in blender.data.scenes
            if isinstance(scene.get(MARKER_KEY), str)
            and scene.get(MARKER_KEY).startswith(self._prefix)
        }
        if len(values) > 1:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED, "Recovery marker is ambiguous; reinspect the scene."
            )
        return next(iter(values), None)

    def _snapshot(self, blender: Any, label: str, *, guard: _CheckpointGuard | None = None) -> str:
        token = self._stamp(blender, guard=guard) if guard is not None else self._stamp(blender)
        expected = self._marker_evidence(blender) if guard is not None else None
        # Resolve readers/operator wrappers before the final trusted safe point.
        undo_push, message = blender.ops.ed.undo_push, label[:120]
        step_limit = self._step_limit(blender)
        if guard is not None:
            guard.check("native_undo_push")
            # Providers can change preferences after the entry check. Read the
            # retained native settings, then finish with provider-free proof.
            edit = getattr(getattr(blender.context, "preferences", None), "edit", None)
            enabled = getattr(edit, "use_global_undo", True)
            step_limit = self._step_limit(blender)
            def compare() -> None:
                if not enabled or step_limit == 0:
                    raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR,
                                      "Native undo was disabled before the snapshot.")
                self._compare_markers(blender, expected)
            guard.complete("native_undo_push", compare)
        if "FINISHED" not in undo_push(message=message):
            raise BridgeError(
                ErrorCode.OPERATION_FAILED, "Blender did not create the native snapshot."
            )
        self._window.pushed(step_limit)
        if guard is not None:
            guard.native_snapshots += 1
            if guard.after_native_push is not None:
                guard._run("after_native_undo_push", lambda: issue_native_push_completion(self, guard))
        self._prune_expired_operations()
        return token

    @staticmethod
    def _step_limit(blender: Any) -> int | None:
        edit = getattr(getattr(blender.context, "preferences", None), "edit", None)
        value = getattr(edit, "undo_steps", None)
        return value if type(value) is int and 0 <= value <= 256 else None

    def _prune_expired_operations(self) -> None:
        retained = [step for step in self._undo_steps if not self._window.expired(step.before_marker)]
        self._expired_operations += len(self._undo_steps) - len(retained)
        self._undo_steps = deque(retained, maxlen=self._undo_steps.maxlen)

    def _retain_targets(self) -> None:
        targets = {checkpoint.snapshot_marker for checkpoint in self._checkpoints}
        targets.update(step.before_marker for step in self._undo_steps)
        if self._pending is not None:
            targets.add(self._pending.before_marker)
        if self._editor_session is not None:
            targets.add(self._editor_session.before.before_marker)
        self._window.retain(targets)

    def recovery_status(self, limit: int = 20) -> dict[str, Any]:
        """Read settings and report uncertainty without probing or changing native undo."""
        blender = require_blender()
        edit = getattr(blender.context.preferences, "edit", None)
        step_limit = self._step_limit(blender)
        enabled = bool(getattr(edit, "use_global_undo", False)) and step_limit != 0
        mode = blender.context.mode

        def describe(marker: str) -> dict[str, Any]:
            evidence = self._window.describe(marker, step_limit)
            return {
                **evidence,
                "can_attempt_restore": enabled and mode == "OBJECT"
                and evidence["availability"] == "unverified",
            }

        checkpoints = list(self._checkpoints)
        latest = self._undo_steps[0] if self._undo_steps else None
        return {
            "native_undo_steps": step_limit,
            "native_undo_memory_limit_mb": getattr(edit, "undo_memory_limit", None),
            "global_undo_enabled": enabled,
            "mode": mode,
            "tracked_operation_count": len(self._undo_steps),
            "expired_operations_pruned_since_clear": self._expired_operations,
            "tracked_checkpoint_count": len(checkpoints),
            "expired_checkpoint_count": sum(self._window.expired(cp.snapshot_marker) for cp in checkpoints),
            "latest_operation": None if latest is None else {
                "label": latest.label, **describe(latest.before_marker),
            },
            "checkpoints": [
                {"checkpoint_id": cp.checkpoint_id, **describe(cp.snapshot_marker)}
                for cp in checkpoints[:max(0, limit)]
            ],
            "checkpoints_truncated": len(checkpoints) > max(0, limit),
            "native_history_introspection": False,
            "availability_guaranteed": False,
            "verification_required": True,
            "warning": "Only bridge pushes are counted. Manual/operator snapshots, memory limits, preference changes and editor stacks can expire other targets. Global recovery can undo interleaved work; labels are not durable backups.",
        }

    @authenticated_checkpoint
    def create(self, description: str = "Agent checkpoint", *, before_write: Callable[[], None] | None = None,
               after_read: Callable[[], None] | None = None, after_native_push: Callable[[], None] | None = None) -> dict[str, Any]:
        guard = _CheckpointGuard(before_write, after_read, after_native_push) if before_write is not None else None
        if guard is not None:
            bind_native_push_guard(self, guard)
        blender = self._ensure_undo_enabled()
        description = (description or "Agent checkpoint").strip()[:120]
        token = self._snapshot(blender, f"Codex Checkpoint: {description}", guard=guard) if guard is not None else self._snapshot(blender, f"Codex Checkpoint: {description}")
        self._window.track(token)
        # A later native/manual snapshot must not masquerade as this named checkpoint.
        self._stamp(blender, guard=guard) if guard is not None else self._stamp(blender)
        self._sequence += 1
        checkpoint = Checkpoint(
            f"cp_{uuid.uuid4().hex[:10]}",
            description,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            token,
            self._sequence,
        )
        self._checkpoints.appendleft(checkpoint)
        self._retain_targets()
        return checkpoint.to_dict()

    @authenticated_checkpoint
    def before_modification(self, tool_name: str, *, before_write: Callable[[], None] | None = None,
                            after_read: Callable[[], None] | None = None, after_native_push: Callable[[], None] | None = None) -> bool:
        guard = _CheckpointGuard(before_write, after_read, after_native_push) if before_write is not None else None
        if guard is not None:
            bind_native_push_guard(self, guard)
        try:
            blender = self._ensure_undo_enabled(require_object_mode=False)
            invalid_editor = False
            if self._editor_session is not None:
                if blender.context.mode == "OBJECT":
                    self._finish_editor_session(guard)
                elif not self._editor_matches(blender):
                    invalid_editor = True
            if blender.context.mode != "OBJECT":
                # Keep earlier global checkpoints identifiable, but do not promise a
                # per-operation boundary on an editor-specific undo stack.
                self._stamp(blender, guard=guard) if guard is not None else self._stamp(blender)
                self._pending = None
                if invalid_editor:
                    self._editor_session = None
                    self._undo_steps.clear()
                if self._editor_session is not None:
                    self._editor_session.attempts += 1
                else:
                    self._undo_steps.clear()
                return False
            token = self._snapshot(blender, f"Codex Before: {tool_name}", guard=guard) if guard is not None else self._snapshot(blender, f"Codex Before: {tool_name}")
            self._sequence += 1
            self._pending = UndoStep(tool_name, token, self._sequence)
            self._window.track(token)
            self._retain_targets()
            # Child operators must not carry BEFORE into intermediate snapshots.
            self._stamp(blender, guard=guard) if guard is not None else self._stamp(blender)
            return True
        except BridgeError as error:
            if error.context.get("checkpoint_authority_rejected"):
                raise
            if guard is None:
                self.clear()
            return False
        except RuntimeError:
            if guard is None:
                self.clear()
            return False

    @authenticated_checkpoint
    def after_modification(self, tool_name: str, *, before_write: Callable[[], None] | None = None,
                           after_read: Callable[[], None] | None = None, after_native_push: Callable[[], None] | None = None) -> bool:
        guard = _CheckpointGuard(before_write, after_read, after_native_push) if before_write is not None else None
        if guard is not None:
            bind_native_push_guard(self, guard)
        pending = self._pending
        if pending is None:
            return False
        if guard is None:
            self._pending = None
        try:
            blender = self._ensure_undo_enabled(require_object_mode=False)
            if blender.context.mode != "OBJECT":
                active = getattr(blender.context, "active_object", None)
                scene_uid = getattr(blender.context.scene, "session_uid", None)
                object_uid = getattr(active, "session_uid", None)
                if (
                    blender.context.mode == "EDIT_MESH"
                    and object_uid is not None
                    and scene_uid is not None
                    and len(blender.context.objects_in_mode) == 1
                ):
                    if guard is not None:
                        guard.check("defer_editor_session")
                    self._editor_session = MeshEditSession(
                        pending,
                        f"edit_{uuid.uuid4().hex}",
                        scene_uid,
                        object_uid,
                        active.name,
                    )
                else:
                    if guard is not None:
                        guard.check("invalidate_editor_session")
                    self._editor_session = None
                    self._undo_steps.clear()
                self._pending = None
                return False
            if guard is not None:
                self._snapshot(blender, f"Codex After: {tool_name}", guard=guard)
            else:
                self._snapshot(blender, f"Codex After: {tool_name}")
        except BridgeError as error:
            if error.context.get("checkpoint_authority_rejected"):
                raise
            LOGGER.exception("Could not finalize the native recovery snapshot")
            if guard is None:
                self.clear()
            return False
        except RuntimeError:
            LOGGER.exception("Could not finalize the native recovery snapshot")
            if guard is None:
                self.clear()
            return False
        self._pending = None
        self._undo_steps.appendleft(UndoStep(tool_name, pending.before_marker, pending.sequence))
        self._prune_expired_operations()
        self._retain_targets()
        return True

    def _editor_matches(self, blender: Any) -> bool:
        session = self._editor_session
        return bool(
            session is not None
            and self._editor_matches_session(blender, session)
            and (
                blender.context.mode == "OBJECT"
                or (
                    blender.context.mode == "EDIT_MESH"
                    and len(blender.context.objects_in_mode) == 1
                )
            )
        )

    def editor_session_status(self) -> dict[str, Any] | None:
        session = self._editor_session
        if session is None:
            return None
        return {
            "kind": "mesh_edit_session",
            "group_id": session.group_id,
            "object": session.object_name,
            "entry_tool": session.before.label,
            "operation_attempts": session.attempts,
            "before_boundary_created": True,
            "state": "deferred",
        }

    @authenticated_checkpoint
    def finish_editor_session(self, *, before_write: Callable[[], None] | None = None,
                              after_read: Callable[[], None] | None = None, after_native_push: Callable[[], None] | None = None) -> dict[str, Any] | None:
        guard = _CheckpointGuard(before_write, after_read, after_native_push) if before_write is not None else None
        if guard is not None:
            bind_native_push_guard(self, guard)
        return self._finish_editor_session(guard)

    def _finish_editor_session(self, guard: _CheckpointGuard | None) -> dict[str, Any] | None:
        if self._editor_session is None:
            return None
        status = self.editor_session_status()
        try:
            blender = self._ensure_undo_enabled(require_object_mode=False)
        except (BridgeError, RuntimeError):
            LOGGER.exception("Native recovery is unavailable for the mesh edit session")
            if guard is None:
                self.clear()
            return {**status, "state": "unavailable"}
        if blender.context.mode != "OBJECT":
            return None
        session = self._editor_session
        if not self._editor_matches_session(blender, session):
            if guard is not None:
                guard.check("invalidate_editor_session")
            self._editor_session = None
            self._undo_steps.clear()
            return {**status, "state": "invalidated"}
        try:
            if guard is not None:
                self._snapshot(blender, f"Codex After Mesh Edit: {session.object_name}", guard=guard)
            else:
                self._snapshot(blender, f"Codex After Mesh Edit: {session.object_name}")
        except BridgeError as error:
            if error.context.get("checkpoint_authority_rejected"):
                raise
            LOGGER.exception("Could not finalize the mesh edit session")
            if guard is None:
                self.clear()
            return {**status, "state": "unavailable"}
        except RuntimeError:
            LOGGER.exception("Could not finalize the mesh edit session")
            if guard is None:
                self.clear()
            return {**status, "state": "unavailable"}
        self._editor_session = None
        self._undo_steps.appendleft(
            UndoStep(
                f"Mesh edit session: {session.object_name}",
                session.before.before_marker,
                session.before.sequence,
                "mesh_edit_session",
                session.attempts,
            )
        )
        self._prune_expired_operations()
        self._retain_targets()
        return {**status, "state": "finalized"}

    @staticmethod
    def _editor_matches_session(blender: Any, session: MeshEditSession) -> bool:
        return (
            getattr(blender.context.scene, "session_uid", None) == session.scene_uid
            and getattr(getattr(blender.context, "active_object", None), "session_uid", None)
            == session.object_uid
        )

    def _recover_to(
        self, target: str, check_cancelled: Callable[[], None] | None = None
    ) -> dict[str, Any]:
        if check_cancelled is not None:
            check_cancelled()
        blender = self._ensure_undo_enabled()
        availability = self._window.describe(target, self._step_limit(blender))
        if availability["availability"] != "unverified":
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Snapshot exceeded the observed native history window or its recovery guard budget; refusing global undo.",
                {"execution_started": False, "undo_steps_completed": 0,
                 "scene_undo_performed": False, "verification_required": True,
                 "recovery": availability},
            )
        if self._marker(blender) is None:
            self.clear()
            raise BridgeError(
                ErrorCode.OPERATION_FAILED, "Recovery marker is missing; refusing global undo."
            )
        # Capture unsnapshotted work so failed navigation can redo back to it.
        guard = self._snapshot(blender, "Codex Recovery Guard")
        hops = 0
        self.recovery_in_progress = True
        try:
            for _ in range(MAX_UNDO_HOPS):
                if check_cancelled is not None:
                    check_cancelled()
                if "FINISHED" not in blender.ops.ed.undo():
                    raise RuntimeError("Native undo did not finish")
                hops += 1
                marker = self._marker(blender)
                if marker == target:
                    self._stamp(blender)
                    if (
                        blender.context.mode != "OBJECT"
                        and "FINISHED" not in blender.ops.object.mode_set(mode="OBJECT")
                    ):
                        raise RuntimeError("Could not restore snapshot Object Mode")
                    self._window.rewind(target)
                    return {
                        "undo_steps": hops,
                        "snapshot_marker_verified": True,
                        "logical_restore_verified": False,
                        "verification_required": True,
                        "interleaving_warning": "Global recovery can affect interleaved user work. Reinspect all changed data.",
                    }
                if marker is None:
                    raise RuntimeError("Target snapshot is absent from retained native history")
            raise RuntimeError("Native recovery exceeded its bounded undo budget")
        except Exception as exc:
            LOGGER.exception("Native snapshot recovery failed; attempting return to guard")
            returned = False
            try:
                for _ in range(hops):
                    if "FINISHED" not in blender.ops.ed.redo():
                        raise RuntimeError("Native redo did not finish")
                returned = hops > 0 and self._marker(blender) == guard
                if returned and blender.context.mode != "OBJECT":
                    returned = "FINISHED" in blender.ops.object.mode_set(mode="OBJECT")
            except Exception:
                LOGGER.exception("Could not return to recovery guard")
            self.clear()
            raise BridgeError(
                exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                "Requested snapshot was not restored; reinspect before continuing.",
                {
                    "execution_started": True,
                    "undo_steps_completed": hops,
                    "return_to_guard_verified": returned,
                    "verification_required": True,
                },
            ) from exc
        finally:
            self.recovery_in_progress = False
            clear_selection_references()

    def restore_operation(
        self, *, check_cancelled: Callable[[], None] | None = None
    ) -> dict[str, Any]:
        if check_cancelled is not None:
            check_cancelled()
        group = self.finish_editor_session()
        if not self._undo_steps:
            context: dict[str, Any] = {
                "expired_operations_pruned_since_clear": self._expired_operations,
                "execution_started": False, "scene_undo_performed": False,
            }
            if group is not None:
                context["undo_group"] = group
                if group["state"] in {"finalized", "unavailable"}:
                    context.update({"execution_started": True, "verification_required": True})
                if group["state"] == "finalized":
                    context["undo_boundary_finalized"] = True
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "No tracked agent undo step is available; refusing to undo unrelated Blender work.",
                context,
            )
        step = self._undo_steps[0]
        try:
            evidence = self._recover_to(step.before_marker, check_cancelled)
        except BridgeError as error:
            if group is not None:
                error.context["undo_group"] = group
                if group["state"] == "finalized":
                    error.context.update({"execution_started": True, "verification_required": True,
                                          "undo_boundary_finalized": True})
            raise
        self._undo_steps.popleft()
        while self._checkpoints and self._checkpoints[0].sequence > step.sequence:
            self._checkpoints.popleft()
        self._retain_targets()
        return {
            "undone": True,
            "tracked_agent_label": step.label,
            "recovered_scope": step.kind,
            "group_operation_attempts": step.attempts,
            "scope": "blender_global_undo",
            **evidence,
        }

    def undo_last(self) -> dict[str, Any]:
        """Legacy public contract: exactly one native global undo, not marker navigation."""
        if not self._undo_steps:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "No tracked agent undo step is available; refusing to undo unrelated Blender work.",
            )
        label = self._undo_steps[0].label
        blender = self._ensure_undo_enabled()
        self.recovery_in_progress = True
        try:
            if "FINISHED" not in blender.ops.ed.undo():
                raise BridgeError(
                    ErrorCode.OPERATION_FAILED, "No native global undo step is available."
                )
        except RuntimeError as exc:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Blender could not undo; reinspect before continuing.",
            ) from exc
        finally:
            self.recovery_in_progress = False
            self.clear()
            clear_selection_references()
        return {
            "undone": True,
            "tracked_agent_label": label,
            "scope": "blender_global_undo",
            "undo_steps": 1,
            "snapshot_marker_verified": False,
            "logical_restore_verified": False,
            "verification_required": True,
            "interleaving_warning": "One native undo may affect interleaved work or stop inside an operation. Reinspect the scene.",
        }

    def restore_last(self, *, check_cancelled: Callable[[], None] | None = None) -> dict[str, Any]:
        if not self._checkpoints:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "No agent checkpoint is available.")
        checkpoint = self._checkpoints[0]
        evidence = self._recover_to(checkpoint.snapshot_marker, check_cancelled)
        self._editor_session = None
        while self._undo_steps and self._undo_steps[0].sequence > checkpoint.sequence:
            self._undo_steps.popleft()
        self._retain_targets()
        return {
            "restored": True,
            "checkpoint": checkpoint.to_dict(),
            "scope": "blender_global_undo_repeated",
            **evidence,
        }

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        return [checkpoint.to_dict() for checkpoint in list(self._checkpoints)[: max(0, limit)]]

    def clear(self) -> None:
        self._checkpoints.clear()
        self._undo_steps.clear()
        self._pending = None
        self._editor_session = None
        self._window.clear()
        self._expired_operations = 0

    def detach(self) -> None:
        """Remove only this session's metadata on normal shutdown."""
        try:
            blender = require_blender()
            for scene in blender.data.scenes:
                value = scene.get(MARKER_KEY)
                if isinstance(value, str) and value.startswith(self._prefix):
                    del scene[MARKER_KEY]
        except Exception:
            LOGGER.warning("Could not remove session recovery metadata", exc_info=True)
        finally:
            self.clear()
