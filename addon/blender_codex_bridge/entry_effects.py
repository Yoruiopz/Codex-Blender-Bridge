"""Bounded diagnostic evidence for known native context readers, never authority.

The physical thread stack follows synchronous structured entries even when host
callbacks copy or replace their Python Context. No Blender getters run here.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .errors import BridgeError

_local = threading.local()
_FIELDS = frozenset({"view_layer_sync_possible", "context_change_measured", "handler_entered", "reinspection_required"})


@dataclass(slots=True, eq=False)
class EntryAudit:
    view_layer_sync_possible: bool = False
    handler_entered: bool = False
    live: bool = True


def current_entry_audit() -> EntryAudit | None:
    stack = getattr(_local, "stack", ())
    return stack[-1] if stack and stack[-1].live is True else None


def mark_view_layer_sync_possible() -> None:
    audit = current_entry_audit()
    if audit is not None:
        audit.view_layer_sync_possible = True


def mark_handler_entered() -> None:
    audit = current_entry_audit()
    if audit is not None:
        audit.handler_entered = True


def snapshot_entry_effects(audit: EntryAudit | None) -> dict[str, bool] | None:
    if (type(audit) is not EntryAudit or audit.live is not True
            or audit.view_layer_sync_possible is not True):
        return None
    return {"view_layer_sync_possible": True, "context_change_measured": False,
            "handler_entered": audit.handler_entered is True, "reinspection_required": True}


def bounded_entry_effects(value: Any) -> dict[str, bool] | None:
    """Accept only this exact plain four-boolean diagnostic; fail best effort."""
    try:
        if (type(value) is not dict or len(value) != 4
                or any(type(key) is not str or key not in _FIELDS for key in value)
                or any(type(value[key]) is not bool for key in _FIELDS)
                or value["view_layer_sync_possible"] is not True
                or value["context_change_measured"] is not False
                or value["reinspection_required"] is not True):
            return None
        return {"view_layer_sync_possible": True, "context_change_measured": False,
                "handler_entered": value["handler_entered"], "reinspection_required": True}
    except Exception:
        return None


def annotate_entry_error(error: BridgeError, audit: EntryAudit | None) -> dict[str, bool] | None:
    """Preserve the primary error even if optional diagnostic allocation fails.

    Recompute the reserved field from this entry, never from an earlier error's
    context. Existing execution/mutation/recovery facts keep their meanings.
    """
    try:
        effects = snapshot_entry_effects(audit)
        if effects is None:
            error.context.pop("entry_effects", None)
        else:
            error.context["entry_effects"] = effects
            error.context["verification_required"] = True
        return effects
    except Exception:
        return None


@contextmanager
def bind_entry_audit(audit: EntryAudit | None) -> Iterator[None]:
    """Route a retained continuation to its own audit without changing authority.

    Another registry may be physically current when an already-retained permit
    is invoked. This binding neither creates a canonical entry nor closes its
    carrier; it attributes reads/handler entry to the original retained call.
    """
    if audit is None or audit.live is not True or current_entry_audit() is audit:
        yield
        return
    stack = getattr(_local, "stack", None)
    if stack is None:
        stack = _local.stack = []
    stack.append(audit)
    try:
        yield
    finally:
        stack.pop()
        if stack:
            stack[-1].view_layer_sync_possible = (
                stack[-1].view_layer_sync_possible is True or audit.view_layer_sync_possible is True
            )


@contextmanager
def entry_audit() -> Iterator[EntryAudit]:
    """Bind only inside a retained canonical interlock entry, after its fence."""
    stack = getattr(_local, "stack", None)
    if stack is None:
        stack = _local.stack = []
    audit = EntryAudit()
    stack.append(audit)
    try:
        yield audit
    except BridgeError as error:
        annotate_entry_error(error, audit)
        raise
    finally:
        stack.pop()
        audit.live = False
        if stack:
            # Child context effects survive a caught error or copied Context.
            # A child's handler is never the enclosing request's handler.
            stack[-1].view_layer_sync_possible = (
                stack[-1].view_layer_sync_possible is True or audit.view_layer_sync_possible is True
            )
