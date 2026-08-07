"""Logical agent checkpoints backed by Blender's global undo stack."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .errors import BridgeError, ErrorCode
from .selection import clear_selection_references
from .utils import require_blender


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class Checkpoint:
    checkpoint_id: str
    description: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CheckpointManager:
    """Track named undo markers without writing hidden project copies."""

    def __init__(self, *, maximum: int = 50) -> None:
        self._checkpoints: deque[Checkpoint] = deque(maxlen=maximum)
        self._undo_labels: deque[str] = deque(maxlen=maximum * 4)
        self._steps_since_checkpoint = 0

    @staticmethod
    def _ensure_undo_enabled() -> Any:
        blender = require_blender()
        edit_preferences = getattr(blender.context.preferences, "edit", None)
        if edit_preferences is not None and not edit_preferences.use_global_undo:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Global Undo is disabled in Blender preferences.",
            )
        return blender

    def create(self, description: str = "Agent checkpoint") -> dict[str, Any]:
        blender = self._ensure_undo_enabled()
        description = (description or "Agent checkpoint").strip()[:120]
        try:
            result = blender.ops.ed.undo_push(message=f"Codex Checkpoint: {description}")
        except RuntimeError as exc:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Blender could not create an undo checkpoint in the current context.",
                {"detail": str(exc)},
            ) from exc
        if "FINISHED" not in result:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Blender did not create the undo checkpoint.")
        checkpoint = Checkpoint(
            checkpoint_id=f"cp_{uuid.uuid4().hex[:10]}",
            description=description,
            timestamp=_timestamp(),
        )
        self._checkpoints.appendleft(checkpoint)
        self._steps_since_checkpoint = 0
        return checkpoint.to_dict()

    def before_modification(self, tool_name: str) -> bool:
        """Best-effort undo boundary for a modifying structured tool."""

        try:
            blender = self._ensure_undo_enabled()
            result = blender.ops.ed.undo_push(message=f"Codex: {tool_name}")
            if "FINISHED" in result:
                return True
        except (BridgeError, RuntimeError):
            # Some background or transient UI contexts cannot push undo. The
            # modification can still proceed and reports this in its history.
            return False
        return False

    def after_modification(self, tool_name: str) -> None:
        """Record a successful agent step only after its handler completes."""

        self._undo_labels.appendleft(tool_name)
        if self._checkpoints:
            self._steps_since_checkpoint += 1

    def undo_last(self) -> dict[str, Any]:
        if not self._undo_labels:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "No tracked agent undo step is available; refusing to undo unrelated Blender work.",
            )
        blender = self._ensure_undo_enabled()
        try:
            result = blender.ops.ed.undo()
        except RuntimeError as exc:
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Blender could not undo in the current context.",
                {"detail": str(exc)},
            ) from exc
        if "FINISHED" not in result:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "There is no available Blender undo step.")
        label = self._undo_labels.popleft() if self._undo_labels else "latest Blender step"
        clear_selection_references()
        if self._steps_since_checkpoint > 0:
            self._steps_since_checkpoint -= 1
        return {
            "undone": True,
            "tracked_agent_label": label,
            "scope": "blender_global_undo",
            "interleaving_warning": (
                "Blender does not expose undo-entry ownership; this may also undo interleaved "
                "user work. Inspect the scene immediately."
            ),
        }

    def restore_last(self) -> dict[str, Any]:
        """Undo tracked agent steps back to the latest logical checkpoint.

        Blender does not expose random access to named undo entries. This method
        therefore restores only the agent steps tracked after our latest marker;
        the caller is explicitly told how many undo operations were used.
        """

        if not self._checkpoints:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "No agent checkpoint is available.")
        checkpoint = self._checkpoints[0]
        steps = self._steps_since_checkpoint
        for _index in range(steps):
            self.undo_last()
        self._steps_since_checkpoint = 0
        return {
            "restored": True,
            "checkpoint": checkpoint.to_dict(),
            "undo_steps": steps,
            "scope": "blender_global_undo_repeated",
            "interleaving_warning": (
                "Blender does not expose undo-entry ownership; repeated undo may also affect "
                "interleaved user work."
            ),
        }

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        return [checkpoint.to_dict() for checkpoint in list(self._checkpoints)[: max(0, limit)]]

    def clear(self) -> None:
        self._checkpoints.clear()
        self._undo_labels.clear()
        self._steps_since_checkpoint = 0
