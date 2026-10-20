"""Conservative bookkeeping of owned native snapshots, not native stack introspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class _Boundary:
    position: int
    expired: bool = False


class UndoWindow:
    """Count only observed bridge pushes on the current branch.

    Blender also pushes snapshots outside this ledger and can evict them by memory.
    Consequently a boundary can be known expired, but never guaranteed available.
    Owners retain only referenced targets, keeping this ledger bounded by their limits.
    """

    def __init__(self) -> None:
        self.position = 0
        self._targets: dict[str, _Boundary] = {}
        self._has_redo = False

    def pushed(self, step_limit: int | None) -> None:
        self.position += 1
        # Blender limits the existing tail before a push. Immediately after undo,
        # the first push instead truncates redo; do not assume it applies that limit.
        if not self._has_redo and step_limit is not None and step_limit > 0:
            for boundary in self._targets.values():
                if self.position - boundary.position > step_limit:
                    boundary.expired = True
        self._has_redo = False

    def track(self, marker: str) -> None:
        self._targets[marker] = _Boundary(self.position)

    def expired(self, marker: str) -> bool:
        boundary = self._targets.get(marker)
        return boundary is not None and boundary.expired

    def describe(self, marker: str, step_limit: int | None) -> dict[str, Any]:
        boundary = self._targets.get(marker)
        age = None if boundary is None else max(0, self.position - boundary.position)
        state = "unverified"
        if boundary is not None and boundary.expired:
            state = "expired"
        elif (
            age is not None
            and step_limit is not None
            and step_limit > 0
            and not self._has_redo
            and age + 1 > step_limit
        ):
            state = "guard_would_exceed_step_limit"
        return {
            "availability": state,
            "known_newer_bridge_snapshots": age,
            "guard_snapshots_required": 1,
            "snapshot_marker_verified": False,
        }

    def rewind(self, marker: str) -> None:
        boundary = self._targets.get(marker)
        if boundary is None:
            self.clear()
            return
        self.position = boundary.position
        self._targets = {
            token: item for token, item in self._targets.items()
            if item.position <= self.position
        }
        self._has_redo = True

    def retain(self, markers: set[str]) -> None:
        self._targets = {token: item for token, item in self._targets.items() if token in markers}

    def clear(self) -> None:
        self.position = 0
        self._targets.clear()
        self._has_redo = False
