"""Bounded artist plans; saved text is data, never executable instructions."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .errors import invalid_argument

SCHEMA_VERSION = 1
SCENE_PROPERTY = "_blender_codex_bridge_task_plan_v1"
MAX_SAVED_BYTES = 65536
STEP_STATUSES = ("pending", "in_progress", "completed", "blocked")


def text(value: Any, name: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise invalid_argument(f"'{name}' must be a {'possibly empty' if empty else 'non-empty'} string.")
    if len(value) > maximum or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise invalid_argument(f"'{name}' exceeds its text limit or contains control characters.", maximum=maximum)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise invalid_argument(f"'{name}' must contain valid UTF-8 text.") from exc
    return value


def revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1_000_000_000:
        raise invalid_argument("'expected_revision' must be an integer from 1 to 1000000000.")
    return value


def contents(goal: Any, steps: Any, protected_objects: Any) -> dict[str, Any]:
    goal = text(goal, "goal", 2000)
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        raise invalid_argument("'steps' requires 1-32 structured plan steps.")
    parsed = []
    identifiers: set[str] = set()
    for item in steps:
        if not isinstance(item, Mapping) or set(item) - {"id", "description", "status", "note"}:
            raise invalid_argument("Each step supports only id, description, status and note.")
        identifier = item.get("id")
        if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) is None:
            raise invalid_argument("Step IDs require 1-64 ASCII letters, digits, underscores or hyphens.")
        if identifier in identifiers:
            raise invalid_argument("Step IDs must be unique.")
        identifiers.add(identifier)
        status = item.get("status", "pending")
        if not isinstance(status, str) or status not in STEP_STATUSES:
            raise invalid_argument("Unsupported plan-step status.", supported=list(STEP_STATUSES))
        parsed.append({
            "id": identifier,
            "description": text(item.get("description"), "description", 500),
            "status": status,
            "note": text(item.get("note", ""), "note", 500, empty=True),
        })
    if not isinstance(protected_objects, list) or len(protected_objects) > 32:
        raise invalid_argument("'protected_objects' requires at most 32 exact object names.")
    names: list[str] = []
    for name in protected_objects:
        name = text(name, "protected object name", 63)
        if len(name.encode("utf-8")) > 63 or name in names:
            raise invalid_argument("Protected object names must be unique and at most 63 UTF-8 bytes.")
        names.append(name)
    return {"goal": goal, "steps": parsed, "protected_objects": names}


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def decode_saved(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise invalid_argument("The scene has no saved task-plan JSON string.")
    try:
        if len(raw.encode("utf-8")) > MAX_SAVED_BYTES:
            raise invalid_argument("Saved task-plan JSON exceeds 64 KiB.")
        value = json.loads(raw, object_pairs_hook=_reject_pairs)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise invalid_argument("Saved task-plan JSON is malformed.") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "plan_id", "revision", "goal", "steps", "protected_objects",
    }:
        raise invalid_argument("Saved task-plan fields do not match schema version 1.")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise invalid_argument("Saved task-plan schema version is unsupported.")
    if not isinstance(value["plan_id"], str) or re.fullmatch(r"plan_[a-f0-9]{32}", value["plan_id"]) is None:
        raise invalid_argument("Saved task-plan identifier is invalid.")
    revision(value["revision"])
    parsed = contents(value["goal"], value["steps"], value["protected_objects"])
    return {"schema_version": SCHEMA_VERSION, "plan_id": value["plan_id"], "revision": value["revision"], **parsed}


def encode_saved(plan: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(plan), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_SAVED_BYTES:
        raise invalid_argument("Task-plan JSON exceeds 64 KiB; shorten plan text.")
    # Roundtrip the public schema before writing any Blender custom property.
    decode_saved(raw)
    return raw


class TaskPlanStore:
    """One runtime plan and one transient protected-scope baseline."""

    def __init__(self) -> None:
        self.plan: dict[str, Any] | None = None
        self.scope: Any = None
        self.baseline: dict[str, Any] | None = None

    def require_plan(self) -> dict[str, Any]:
        if self.plan is None:
            raise invalid_argument("No current task plan; create or explicitly load one first.")
        return self.plan

    def check_revision(self, expected: Any) -> None:
        if revision(expected) != self.require_plan()["revision"]:
            raise invalid_argument("Task plan changed; inspect it and supply the current revision.", current_revision=self.plan["revision"])

    def replace(self, parsed: dict[str, Any], scope: Any, expected: Any = None) -> None:
        if self.plan is not None:
            self.check_revision(expected)
            plan_id = self.plan["plan_id"]
            next_revision = self.plan["revision"] + 1
        else:
            if expected is not None:
                raise invalid_argument("There is no existing plan for 'expected_revision'.")
            plan_id, next_revision = f"plan_{uuid.uuid4().hex}", 1
        candidate = {"schema_version": SCHEMA_VERSION, "plan_id": plan_id, "revision": next_revision, **deepcopy(parsed)}
        encode_saved(candidate)
        self.plan = candidate
        self.scope, self.baseline = scope, None

    def inspect(self) -> dict[str, Any]:
        return {
            "active": self.plan is not None,
            "plan": deepcopy(self.plan),
            "protected_scope_enforced": False,
            "scope_policy": "advisory; compare measured protected data explicitly",
            "baseline": deepcopy(self.baseline),
            "project_saved": False,
        }

    def clear(self) -> None:
        self.plan = self.scope = self.baseline = None


def get_task_plans(state: Any) -> TaskPlanStore:
    store = getattr(state, "_artist_task_plans", None)
    if not isinstance(store, TaskPlanStore):
        store = TaskPlanStore()
        state._artist_task_plans = store
    return store


def clear_task_plans(state: Any) -> None:
    """Call on project replacement/runtime reset; MCP reconnect does not clear it."""
    get_task_plans(state).clear()
