"""Immutable membership plans for the two bounded direct weight writers.

This module handles plain data only. Pointer values are retained facts supplied
by the reader; they do not qualify persistent native VertexGroup identity.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass
from typing import Any

MAX_VERTICES = 512
MAX_EDGES = 1024
MAX_POLYGONS = 512
MAX_CORNERS = 2048
MAX_GROUPS = 32
MAX_CHANGED_FIELDS = 256
MAX_REQUEST_INDICES = 1000
MAX_SNAPSHOT_VALUES = 65_536
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_COMPARE_VALUES = 8_388_608
MAX_MARKER_SCENES = 200


class WeightPlanError(ValueError):
    """Invalid or unsupported plain weight plan; no native effects occurred."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise WeightPlanError(message)


def _name(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} requires an exact nonempty name.")
    _require(not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value),
             f"{label} contains control characters.")
    try:
        _require(len(value.encode("utf-8")) <= 63, f"{label} exceeds its UTF-8 name budget.")
    except UnicodeError as exc:
        raise WeightPlanError(f"{label} requires valid UTF-8.") from exc
    return value


def f32_bits(value: Any) -> str:
    """Predict a stored finite [0,1] Float32, preserving signed zero."""
    _require(type(value) in {int, float}, "Weight must be an exact numeric value.")
    # Range first: arbitrarily large integers must not reach float conversion.
    _require(0 <= value <= 1 and math.isfinite(value), "Weight must be finite in [0,1].")
    try:
        return struct.pack("<f", value).hex()
    except (OverflowError, struct.error) as exc:
        raise WeightPlanError("Weight cannot be stored as Float32.") from exc


def f32_value(bits: Any) -> float:
    _require(type(bits) is str and re.fullmatch(r"[0-9a-f]{8}", bits) is not None,
             "Membership requires exact little-endian Float32 hex.")
    value = struct.unpack("<f", bytes.fromhex(bits))[0]
    _require(math.isfinite(value) and 0 <= value <= 1, "Stored weight must be finite in [0,1].")
    return value


@dataclass(frozen=True, slots=True)
class GroupState:
    index: int
    name: str
    pointer: int
    locked: bool


@dataclass(frozen=True, slots=True)
class MembershipSnapshot:
    groups: tuple[GroupState, ...]
    memberships: tuple[tuple[tuple[int, str], ...], ...]


@dataclass(frozen=True, slots=True)
class WeightWrite:
    vertex: int
    group: GroupState
    before: str | None
    after: str | None


@dataclass(frozen=True, slots=True)
class WeightPlan:
    method: str
    object_name: str
    vertex_indices: tuple[int, ...]
    group_indices: tuple[int, ...]
    before: MembershipSnapshot
    expected: MembershipSnapshot
    writes: tuple[WeightWrite, ...]
    requested_memberships: int


def _canonical(snapshot: MembershipSnapshot) -> bytes:
    plain = {
        "groups": [(g.index, g.name, g.pointer, g.locked) for g in snapshot.groups],
        "memberships": snapshot.memberships,
    }
    return json.dumps(plain, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def membership_values(snapshot: MembershipSnapshot) -> int:
    """Membership-only scalar cost; guard must also count its preservation state."""
    return 4 * len(snapshot.groups) + len(snapshot.memberships) + sum(
        2 * len(members) for members in snapshot.memberships
    )


def validate_snapshot(snapshot: Any) -> MembershipSnapshot:
    _require(type(snapshot) is MembershipSnapshot, "Expected an immutable membership snapshot.")
    _require(type(snapshot.groups) is tuple and 1 <= len(snapshot.groups) <= MAX_GROUPS,
             "Group inventory exceeds the initial profile.")
    names, pointers = set(), set()
    for expected_index, group in enumerate(snapshot.groups):
        _require(type(group) is GroupState, "Expected an exact immutable group record.")
        _require(type(group.index) is int and group.index == expected_index,
                 "Group inventory must retain consecutive native indices.")
        _name(group.name, "Group")
        _require(type(group.pointer) is int and 0 < group.pointer <= 2**64 - 1,
                 "Group pointer fact must fit the qualified 64-bit profile.")
        _require(type(group.locked) is bool, "Group lock state must be exact.")
        _require(group.name not in names and group.pointer not in pointers,
                 "Group names and pointer facts must be unique.")
        names.add(group.name)
        pointers.add(group.pointer)
    _require(type(snapshot.memberships) is tuple and
             1 <= len(snapshot.memberships) <= MAX_VERTICES,
             "Vertex inventory exceeds the initial profile.")
    for members in snapshot.memberships:
        _require(type(members) is tuple and len(members) <= len(snapshot.groups),
                 "Membership inventory must be a bounded tuple.")
        previous = -1
        for member in members:
            _require(type(member) is tuple and len(member) == 2,
                     "Membership record has an unexpected shape.")
            index, bits = member
            _require(type(index) is int and previous < index < len(snapshot.groups),
                     "Membership indices must be unique, ordered and present in the inventory.")
            f32_value(bits)
            previous = index
    _require(membership_values(snapshot) <= MAX_SNAPSHOT_VALUES,
             "Membership snapshot exceeds its scalar budget.")
    _require(len(_canonical(snapshot)) <= MAX_SNAPSHOT_BYTES,
             "Membership snapshot exceeds its serialized budget.")
    return snapshot


def _field(snapshot: MembershipSnapshot, vertex: Any, group_index: Any) -> None:
    _require(type(vertex) is int and 0 <= vertex < len(snapshot.memberships),
             "Vertex index is outside the retained snapshot.")
    _require(type(group_index) is int and 0 <= group_index < len(snapshot.groups),
             "Group index is outside the retained snapshot.")


def membership(snapshot: MembershipSnapshot, vertex: int, group_index: int) -> str | None:
    validate_snapshot(snapshot)
    _field(snapshot, vertex, group_index)
    return dict(snapshot.memberships[vertex]).get(group_index)


def _replace(snapshot: MembershipSnapshot, vertex: int, group_index: int,
             bits: str | None) -> MembershipSnapshot:
    members = dict(snapshot.memberships[vertex])
    if bits is None:
        members.pop(group_index, None)
    else:
        members[group_index] = bits
    vertices = list(snapshot.memberships)
    vertices[vertex] = tuple(sorted(members.items()))
    return MembershipSnapshot(snapshot.groups, tuple(vertices))


def replace_member(snapshot: MembershipSnapshot, vertex: int, group_index: int,
                   bits: str | None) -> MembershipSnapshot:
    validate_snapshot(snapshot)
    _field(snapshot, vertex, group_index)
    if bits is not None:
        f32_value(bits)
    return validate_snapshot(_replace(snapshot, vertex, group_index, bits))


def digest(snapshot: MembershipSnapshot) -> str:
    return hashlib.sha256(_canonical(validate_snapshot(snapshot))).hexdigest()


def comparison_budget(snapshot_values: int, changed_fields: int, marker_scenes: int) -> int:
    _require(type(snapshot_values) is int and 1 <= snapshot_values <= MAX_SNAPSHOT_VALUES,
             "Complete retained state exceeds its scalar budget.")
    _require(type(changed_fields) is int and 0 <= changed_fields <= MAX_CHANGED_FIELDS,
             "Changed membership count exceeds its profile.")
    _require(type(marker_scenes) is int and 0 <= marker_scenes <= MAX_MARKER_SCENES,
             "Checkpoint marker inventory exceeds its profile.")
    cost = snapshot_values * (6 * changed_fields + 24 + 2 * marker_scenes) + MAX_SNAPSHOT_VALUES
    _require(cost <= MAX_COMPARE_VALUES, "Joint forward/compensation comparison budget exceeded.")
    return cost


def _indices(snapshot: MembershipSnapshot, value: Any) -> tuple[int, ...]:
    _require(type(value) is list and 1 <= len(value) <= MAX_REQUEST_INDICES,
             "vertex_indices must contain 1-1,000 indices.")
    _require(all(type(i) is int and 0 <= i < len(snapshot.memberships) for i in value),
             "Vertex indices must be exact in-range integers.")
    _require(len(set(value)) == len(value), "Vertex indices must be unique.")
    return tuple(value)


def validate_request(method: str, params: Any) -> None:
    """Validate plain arguments before any native reader or payload acquisition.

    Native index upper bounds, existing groups and locks require the snapshot
    and are checked later. Validation grants no write or identity authority.
    """
    _require(type(method) is str and method in {"weights.assign", "weights.normalize"},
             "Unsupported direct weight method.")
    _require(type(params) is dict, "Weight requests must be plain dictionaries.")
    fields = {"object_name", "vertex_indices", "group_name", "weight"} if method == "weights.assign" else {
        "object_name", "vertex_indices", "group_names"
    }
    _require(set(params) == fields, "Weight request contains missing or unknown fields.")
    _name(params["object_name"], "Object")
    indices = params["vertex_indices"]
    _require(type(indices) is list and 1 <= len(indices) <= MAX_REQUEST_INDICES,
             "vertex_indices must contain 1-1,000 indices.")
    _require(all(type(i) is int and i >= 0 for i in indices),
             "Vertex indices must be exact nonnegative integers.")
    _require(len(set(indices)) == len(indices), "Vertex indices must be unique.")
    names = [params["group_name"]] if method == "weights.assign" else params["group_names"]
    _require(type(names) is list and 1 <= len(names) <= MAX_GROUPS,
             "group_names must contain 1-32 names.")
    for name in names:
        _name(name, "Target group")
    _require(len(set(names)) == len(names), "Target group names must be unique.")
    if method == "weights.assign" and params["weight"] is not None:
        f32_bits(params["weight"])


def plan_edit(snapshot: MembershipSnapshot, method: str, params: Any) -> WeightPlan:
    validate_request(method, params)
    snapshot = validate_snapshot(snapshot)
    object_name = params["object_name"]
    indices = _indices(snapshot, params["vertex_indices"])
    names = [params["group_name"]] if method == "weights.assign" else params["group_names"]
    lookup = {group.name: group for group in snapshot.groups}
    _require(all(name in lookup for name in names), "Target group must already exist.")
    groups = tuple(lookup[name] for name in names)
    _require(not any(group.locked for group in groups), "Target groups must be unlocked.")
    target_bits = None
    if method == "weights.assign" and params["weight"] is not None:
        target_bits = f32_bits(params["weight"])
    expected, writes, requested = snapshot, [], 0
    selected = {g.index for g in groups}
    for vertex in indices:
        original = dict(snapshot.memberships[vertex])
        if method == "weights.normalize":
            values = {index: f32_value(bits) for index, bits in original.items()}
            untouched = sum(value for index, value in values.items() if index not in selected)
            total = sum(values.get(group.index, 0.0) for group in groups)
            _require(untouched <= 1 + 1e-6 and total > 0,
                     "Cannot normalize zero targets or preserve untouched weights exceeding one.")
        for group in groups:
            before = original.get(group.index)
            if method == "weights.normalize":
                if before is None:
                    continue
                after = f32_bits(values[group.index] / total * max(0.0, 1 - untouched))
            else:
                after = target_bits
            requested += 1
            if before == after:
                continue
            writes.append(WeightWrite(vertex, group, before, after))
            _require(len(writes) <= MAX_CHANGED_FIELDS, "Changed membership count exceeds its profile.")
            expected = _replace(expected, vertex, group.index, after)
    validate_snapshot(expected)
    comparison_budget(membership_values(snapshot), len(writes), 0)
    return WeightPlan(method, object_name, indices, tuple(g.index for g in groups),
                      snapshot, expected, tuple(writes), requested)
