"""Bounded native snapshot recovery with explicit, undoable scene markers."""

from __future__ import annotations

import logging
import re
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .errors import BridgeError, ErrorCode
from .selection import clear_selection_references
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


class CheckpointManager:
    """Navigate to measured native markers, never infer position from a label count."""

    def __init__(self, *, maximum: int = 50) -> None:
        self._checkpoints: deque[Checkpoint] = deque(maxlen=maximum)
        self._undo_steps: deque[UndoStep] = deque(maxlen=maximum * 4)
        self._pending: UndoStep | None = None
        self._sequence = 0
        self._prefix = f"BCB1:{uuid.uuid4().hex}:"
        self.recovery_in_progress = False

    @staticmethod
    def _ensure_undo_enabled(*, require_object_mode: bool = True) -> Any:
        blender = require_blender()
        preferences = getattr(blender.context.preferences, "edit", None)
        if preferences is not None and not preferences.use_global_undo:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR, "Global Undo is disabled in Blender preferences."
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

    def _stamp(self, blender: Any) -> str:
        scene = blender.context.scene
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
            del item[MARKER_KEY]
        token = self._prefix + uuid.uuid4().hex
        scene[MARKER_KEY] = token
        return token

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

    def _snapshot(self, blender: Any, label: str) -> str:
        token = self._stamp(blender)
        if "FINISHED" not in blender.ops.ed.undo_push(message=label[:120]):
            raise BridgeError(
                ErrorCode.OPERATION_FAILED, "Blender did not create the native snapshot."
            )
        return token

    def create(self, description: str = "Agent checkpoint") -> dict[str, Any]:
        blender = self._ensure_undo_enabled()
        description = (description or "Agent checkpoint").strip()[:120]
        token = self._snapshot(blender, f"Codex Checkpoint: {description}")
        # A later native/manual snapshot must not masquerade as this named checkpoint.
        self._stamp(blender)
        self._sequence += 1
        checkpoint = Checkpoint(
            f"cp_{uuid.uuid4().hex[:10]}",
            description,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            token,
            self._sequence,
        )
        self._checkpoints.appendleft(checkpoint)
        return checkpoint.to_dict()

    def before_modification(self, tool_name: str) -> bool:
        self._pending = None
        try:
            blender = self._ensure_undo_enabled(require_object_mode=False)
            if blender.context.mode != "OBJECT":
                # Keep earlier global checkpoints identifiable, but do not promise a
                # per-operation boundary on an editor-specific undo stack.
                self._stamp(blender)
                self._undo_steps.clear()
                return False
            token = self._snapshot(blender, f"Codex Before: {tool_name}")
            self._sequence += 1
            self._pending = UndoStep(tool_name, token, self._sequence)
            # Child operators must not carry BEFORE into intermediate snapshots.
            self._stamp(blender)
            return True
        except (BridgeError, RuntimeError):
            self.clear()
            return False

    def after_modification(self, tool_name: str) -> bool:
        pending = self._pending
        self._pending = None
        if pending is None:
            return False
        try:
            self._snapshot(self._ensure_undo_enabled(), f"Codex After: {tool_name}")
        except (BridgeError, RuntimeError):
            LOGGER.exception("Could not finalize the native recovery snapshot")
            self.clear()
            return False
        self._undo_steps.appendleft(UndoStep(tool_name, pending.before_marker, pending.sequence))
        return True

    def _recover_to(
        self, target: str, check_cancelled: Callable[[], None] | None = None
    ) -> dict[str, Any]:
        if check_cancelled is not None:
            check_cancelled()
        blender = self._ensure_undo_enabled()
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
        if not self._undo_steps:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "No tracked agent undo step is available; refusing to undo unrelated Blender work.",
            )
        step = self._undo_steps[0]
        evidence = self._recover_to(step.before_marker, check_cancelled)
        self._undo_steps.popleft()
        while self._checkpoints and self._checkpoints[0].sequence > step.sequence:
            self._checkpoints.popleft()
        return {
            "undone": True,
            "tracked_agent_label": step.label,
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
        while self._undo_steps and self._undo_steps[0].sequence > checkpoint.sequence:
            self._undo_steps.popleft()
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
