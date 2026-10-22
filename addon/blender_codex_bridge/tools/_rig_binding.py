"""Measured, bounded armature binding with exact preexisting weight recovery.

The native heat solver is one synchronous Blender call. Its immediate output is
retained before any completion callback, and never treated as a durable backup.
"""

from __future__ import annotations

import copy
import math
import time
from collections.abc import Callable
from functools import partial
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from . import _animation_scope as scope
from ._object_safety import require_local_editable_id, require_unkeyed_object_data

MAX_VERTICES, MAX_GROUPS, MAX_MEMBERSHIPS, MAX_BONES = 4096, 128, 32768, 128
CHANNELS = ("rotation_mode", "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
            "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")
MUTABLE_OBJECT = frozenset((*CHANNELS, "parent", "parent_type", "parent_bone", "matrix_basis",
                            "matrix_parent_inverse", "matrix_world", "matrix_local", "dimensions"))


def _matrix(raw: Any) -> tuple[tuple[float, ...], ...]:
    result = tuple(tuple(float(item) for item in row) for row in raw)
    if len(result) != 4 or any(len(row) != 4 for row in result) or any(
        not math.isfinite(item) or abs(item) > 1e6 for row in result for item in row
    ):
        raise invalid_argument("Binding requires finite matrices bounded to +/-1000000.")
    return result


def _custom(owner: Any) -> Any:
    from ._object_rna_mutation import _custom as read_custom

    return read_custom(owner)


def _animation(bpy: Any, obj: Any) -> Any:
    data = obj.animation_data
    if data is None:
        return None
    result = scope.animation_context(obj), scope.binding(obj)
    actions = [data.action] if data.action else []
    for track in scope.bounded(data.nla_tracks, 64, "binding tracks"):
        actions.extend(strip.action for strip in scope.bounded(track.strips, 256, "binding strips") if strip.action)
    unique = {scope.key(action): action for action in actions}
    return result, tuple((scope.action_token(action), scope.action_content(action), scope.action_users(bpy, action))
                         for action in unique.values())


def _geometry(obj: Any) -> dict[str, Any]:
    # A private BMesh is a read-only representation. Never flush it into Mesh.
    from . import mesh_surface

    if getattr(obj.data, "has_custom_normals", False):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding custom split-normal preservation requires a reviewed complete reader.")
    if mesh_surface.bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Native BMesh evidence is unavailable.")
    bm = mesh_surface.bmesh.new()
    try:
        bm.from_mesh(obj.data)
        for sequence in (bm.verts, bm.edges, bm.faces):
            sequence.ensure_lookup_table()
            sequence.index_update()
        result: dict[str, Any] = mesh_surface._capture(obj, bm)
    finally:
        bm.free()
    result["custom_data"] = [item for item in result["custom_data"] if item[1] != "deform"]
    for name in ("matrix", "groups", "group_active"):
        result["metadata"].pop(name)
    return result


def binding_state(mesh: Any) -> dict[str, Any]:
    from ._object_rna_mutation import component_state

    if len(mesh.data.vertices) > MAX_VERTICES or len(mesh.vertex_groups) > MAX_GROUPS or len(mesh.modifiers) > 16:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding is bounded to 4096 vertices, 128 groups and 16 modifiers.")
    weights = tuple(tuple(sorted((int(member.group), float(member.weight)) for member in vertex.groups)) for vertex in mesh.data.vertices)
    if sum(map(len, weights)) > MAX_MEMBERSHIPS or any(
        not 0 <= index < len(mesh.vertex_groups) or not math.isfinite(weight) or not 0 <= weight <= 1
        for memberships in weights for index, weight in memberships
    ):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding requires at most 32768 finite, valid vertex memberships.")
    return {"groups": tuple((scope.key(group), group.name, int(group.index), bool(group.lock_weight)) for group in mesh.vertex_groups),
            "weights": weights, "active": int(mesh.vertex_groups.active_index),
            "modifiers": tuple(component_state(item) for item in mesh.modifiers),
            "parent": scope.key(mesh.parent), "parent_type": mesh.parent_type, "parent_bone": mesh.parent_bone,
            "inverse": _matrix(mesh.matrix_parent_inverse), "basis": _matrix(mesh.matrix_basis), "world": _matrix(mesh.matrix_world),
            "channels": tuple((name, scope.value(getattr(mesh, name))) for name in CHANNELS)}


def _rig(bpy: Any, rig: Any) -> Any:
    from ._rigging_edit import rig_source_state

    require_local_editable_id(rig.data, operation="Armature binding source")
    bones = scope.bounded(rig.data.bones, MAX_BONES, "binding source bones")
    pose = scope.bounded(rig.pose.bones, MAX_BONES, "binding source pose")
    return (scope.rna_state(rig), _custom(rig), scope.rna_state(rig.data, exclude=frozenset({"collections"})), _custom(rig.data), _animation(bpy, rig),
            rig_source_state(rig),
            tuple((scope.key(bone), scope.rna_state(bone), _custom(bone), tuple(bone.head_local), tuple(bone.tail_local),
                   _matrix(bone.matrix_local), scope.key(bone.parent)) for bone in bones),
            tuple((scope.key(bone), scope.rna_state(bone), _custom(bone),
                   tuple((scope.key(item), scope.rna_state(item), _custom(item)) for item in scope.bounded(bone.constraints, 32, "pose constraints"))) for bone in pose),
            tuple((scope.key(item), scope.rna_state(item), _custom(item)) for item in scope.bounded(rig.constraints, 32, "rig constraints")))


def _consumer(bpy: Any, obj: Any) -> Any:
    if obj.type not in {"MESH", "ARMATURE", "EMPTY"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding dependent preservation supports bounded Mesh, Armature and Empty objects.")
    if obj.type == "ARMATURE":
        data = _rig(bpy, obj)
    elif obj.type == "MESH":
        if obj.data.shape_keys is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding dependent shape-key preservation needs a separate reviewed reader.")
        data = _geometry(obj), binding_state(obj), scope.rna_state(obj.data), _custom(obj.data)
    else:
        data = None
    return (scope.action_token(obj), scope.action_token(getattr(obj, "data", None)), scope.rna_state(obj), _custom(obj), _animation(bpy, obj), data,
            tuple((scope.key(item), scope.rna_state(item), _custom(item)) for item in scope.bounded(obj.constraints, 32, "dependent constraints")))


def _context(bpy: Any) -> Any:
    return (scope.action_token(bpy.context.scene), scope.key(bpy.context.view_layer), bpy.data.filepath, bpy.context.mode,
            bpy.context.scene.frame_current, bpy.context.scene.frame_subframe,
            scope.action_token(bpy.context.view_layer.objects.active), tuple(sorted(scope.action_token(obj) for obj in scope.bounded(bpy.context.selected_objects, 256, "selection"))))


def _no_cycle(closure: Any, mesh_key: int | None, rig_key: int | None) -> None:
    if mesh_key is None or rig_key is None:
        raise invalid_argument("Binding roots require exact native identities.")
    pending, seen = [mesh_key], set()
    while pending:
        current = pending.pop()
        if current == rig_key:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding would close an unreviewed rig-to-mesh dependency cycle.")
        if current in seen:
            continue
        seen.add(current)
        pending.extend(record[1] for record in closure[1] if len(record) == 3 and record[0] == current)


def _allocation_shape(before: dict[str, Any], after: dict[str, Any], deform: tuple[str, ...], rig_key: int | None,
                      *, parent: bool) -> None:
    """Prove exact preexisting identities and bounded native allocation shape."""
    if rig_key is None:
        raise invalid_argument("Binding source requires an exact native identity.")
    old, new = before["groups"], after["groups"]
    if new[:len(old)] != old or tuple(item[1] for item in new[len(old):]) != tuple(name for name in deform if name not in {item[1] for item in old}):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding changed preexisting group identity or allocated unexpected groups.")
    old_mods, new_mods = before["modifiers"], after["modifiers"]
    if new_mods[:len(old_mods)] != old_mods or len(new_mods) not in {len(old_mods), len(old_mods)+1}:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding changed a protected modifier or allocated unexpected modifiers.")
    if after["parent"] != (rig_key if parent else before["parent"]):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding returned an unexpected parent.")
    # keep_transform is verified numerically, never inferred from FINISHED.
    if any(abs(a-b) > 2e-5 for row_a, row_b in zip(before["world"], after["world"], strict=True) for a, b in zip(row_a, row_b, strict=True)):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding did not preserve the mesh world transform.")


def _weight_shape(before: dict[str, Any], after: dict[str, Any], deform: tuple[str, ...], *, automatic: bool) -> dict[str, Any]:
    old, new = before["groups"], after["groups"]
    indices = {item[2] for item in new if item[1] in deform}
    protected = {item[2] for item in old if item[1] not in deform}
    totals = []
    for old_weights, new_weights in zip(before["weights"], after["weights"], strict=True):
        if tuple(item for item in old_weights if item[0] in protected) != tuple(item for item in new_weights if item[0] in protected):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding changed protected unrelated group memberships.")
        if not automatic and old_weights != new_weights:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Empty-group binding changed existing memberships.")
        if automatic:
            total = sum(weight for index, weight in new_weights if index in indices)
            if total <= 1e-8:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Native automatic weights have incomplete deform coverage.", {"deform_total": total})
            totals.append(total)
    # Heat weights are not guaranteed to sum to one (observed natively). The
    # Armature evaluator normalizes their contribution; never certify authored
    # normalization or artistic deformation merely from positive coverage.
    return {"positive_deform_coverage": automatic, "normalization_certified": False,
            "deform_weight_total_min": min(totals) if totals else None,
            "deform_weight_total_max": max(totals) if totals else None}


class Binding:
    def __init__(self, bpy: Any, context: Any, mesh: Any, rig: Any, names: Any, *, automatic: bool):
        self.bpy, self.context, self.mesh, self.rig = bpy, context, mesh, rig
        self.names, self.automatic = names, automatic
        if isinstance(names, list) and len(names) > 30:
            raise invalid_argument("Binding affected_objects is bounded to 30 dependents plus the two explicit roots.")
        self.guard = scope.Guard(bpy, context, "rig.bind_mesh")
        for owner, storage in ((mesh, bpy.data.objects), (rig, bpy.data.objects), (mesh.data, bpy.data.meshes), (rig.data, bpy.data.armatures)):
            self.guard.remember(owner, storage)
        require_unkeyed_object_data(mesh, operation="Armature binding")
        if bpy.context.mode != "OBJECT" or mesh.mode != "OBJECT" or rig.mode != "OBJECT":
            raise BridgeError(ErrorCode.INVALID_MODE, "Armature binding requires Object Mode; no temporary physical context change is attempted.")
        if mesh.parent not in (None, rig) or mesh.parent_type != "OBJECT" or mesh.parent_bone:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding requires an unparented mesh or an existing object parent to this rig.")
        if len(mesh.constraints) or mesh.animation_data is not None or mesh.data.animation_data is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding requires a mesh without constraints or animation.")
        self.deform = tuple(bone.name for bone in scope.bounded(rig.data.bones, MAX_BONES, "binding bones") if bone.use_deform)
        if not self.deform:
            raise invalid_argument("Binding requires at least one deform bone.")
        if len(mesh.vertex_groups)+sum(mesh.vertex_groups.get(name) is None for name in self.deform) > MAX_GROUPS:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding output would exceed 128 vertex groups.")
        if any(item.type != "ARMATURE" or item.object != rig for item in mesh.modifiers) or len(mesh.modifiers) > 1:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding requires no modifier or one existing Armature modifier targeting this exact rig.")
        if automatic:
            if rig.animation_data is not None or rig.data.animation_data is not None or rig.parent or len(rig.constraints) or len(rig.modifiers):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Automatic weights require a static, independent rest rig.")
            for bone in rig.pose.bones:
                if len(bone.constraints) or any(abs(value) > 1e-7 for value in bone.location) or any(abs(value-1) > 1e-7 for value in bone.scale) or any(
                    abs(value-expected) > 1e-7 for row, expected_row in zip(bone.matrix_basis, ((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)), strict=True) for value, expected in zip(row, expected_row, strict=True)
                ):
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Automatic weights require rest pose channels without constraints.")
            if any(group.lock_weight and group.name in self.deform for group in mesh.vertex_groups):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Automatic weights refuse locked existing deform groups.")
        # Native evaluation can run arbitrary add-on handlers. This bounded
        # transaction has no reviewable prediction for those user mutations.
        for name in ("depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post"):
            if getattr(bpy.app.handlers, name, ()):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding requires no installed dependency/frame mutation handlers.", {"handler_list": name})
        self.changed = False
        self.blocked: str | None = None
        self.owned_output = not automatic
        self.expected = self.read()
        _no_cycle(self.expected["scope"], scope.key(mesh), scope.key(rig))
        self.original = copy.deepcopy(self.expected)
        buckets = sum(len({weight for memberships in self.original["binding"]["weights"] for group_index, weight in memberships
                           if group_index == group[2]}) for group in self.original["binding"]["groups"])
        if buckets > 128:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding recovery is bounded to 128 original per-group weight buckets.")
        self.guard.gate(Permission.TRANSFORM_OBJECTS, Permission.EDIT_MESH)
        self.match()

    def read(self) -> dict[str, Any]:
        closure = scope.affected_scope(self.bpy, self.rig, self.names, additional_roots=(self.mesh,))
        consumers = [self.bpy.context.scene.objects[name] for name in self.names]
        return {"context": _context(self.bpy), "scope": closure,
                "binding": binding_state(self.mesh),
                "protected": (_geometry(self.mesh), scope.rna_state(self.mesh, exclude=MUTABLE_OBJECT), _custom(self.mesh),
                              scope.rna_state(self.mesh.data), _custom(self.mesh.data), _rig(self.bpy, self.rig),
                              tuple((scope.action_token(slot.material), slot.link) for slot in self.mesh.material_slots),
                              tuple(scope.action_token(material) for material in self.mesh.data.materials),
                              tuple((scope.key(obj), _consumer(self.bpy, obj)) for obj in consumers))}

    def match(self) -> None:
        if self.read() != self.expected:
            raise invalid_argument("Binding scope, exact identities, context or content changed; writes and recovery refused.")

    def gate(self) -> None:
        if self.blocked is not None:
            raise BridgeError(self.blocked, "Binding authorization or exact-state failure is latched; further writes require reinspection.")
        try:
            self.guard.gate(Permission.TRANSFORM_OBJECTS, Permission.EDIT_MESH)
            self.match()
            final_job = getattr(self.context, "check_final_job", None)
            if final_job is not None:
                final_job()
        except BridgeError as error:
            self.blocked = error.code
            raise

    def observe(self) -> dict[str, Any]:
        observed = self.read()
        if observed["protected"] != self.original["protected"] or observed["context"] != self.original["context"]:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding changed protected content or physical context; output retained for reinspection.")
        return observed

    def write(self, operation: Callable[[], Any], allowed: set[str]) -> Any:
        self.gate()
        before = self.expected
        self.changed = True
        result = operation()
        after = self.observe()
        differences = {name for name in before["binding"] if before["binding"][name] != after["binding"][name]}
        if differences-allowed:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding RNA write changed fields outside its reviewed effect.", {"fields": sorted(differences-allowed)})
        # Exact owned operations may add one rig reference (modifier/parent).
        self.expected = after
        return result

    def recover(self) -> bool:
        """Restore original memberships only while exact observed output survives."""
        self.gate()
        if not self.owned_output:
            return False
        before = self.original["binding"]
        current = self.expected["binding"]
        old_groups = before["groups"]
        if current["groups"][:len(old_groups)] != old_groups:
            return False
        # Revoke/cancel/manual edits are checked before every individual write.
        for token, name, _index, _lock in reversed(current["groups"][len(old_groups):]):
            group = self.mesh.vertex_groups.get(name)
            if scope.key(group) != token or name not in self.deform:
                return False
            self.write(partial(self.mesh.vertex_groups.remove, group), {"groups", "weights", "active"})
        indices = list(range(len(self.mesh.data.vertices)))
        for token, name, index, _lock in old_groups:
            group = self.mesh.vertex_groups.get(name)
            if scope.key(group) != token or group.index != index:
                return False
            wanted = tuple((vertex, weight) for vertex, memberships in enumerate(before["weights"]) for group_index, weight in memberships if group_index == index)
            actual = tuple((vertex, weight) for vertex, memberships in enumerate(self.expected["binding"]["weights"]) for group_index, weight in memberships if group_index == index)
            if wanted == actual:
                continue
            self.write(partial(group.remove, indices), {"weights"})
            buckets: dict[float, list[int]] = {}
            for vertex, weight in wanted:
                buckets.setdefault(weight, []).append(vertex)
            for weight, vertices in buckets.items():
                self.write(partial(group.add, vertices, weight, "REPLACE"), {"weights"})
        for modifier in reversed(list(self.mesh.modifiers)):
            if scope.key(modifier) not in {item[0] for item in before["modifiers"]}:
                if modifier.type != "ARMATURE" or modifier.object not in (None, self.rig):
                    return False
                self.write(partial(self.mesh.modifiers.remove, modifier), {"modifiers"})
        old_parent = None if before["parent"] is None else self.bpy.data.objects.get(self.rig.name)
        if scope.key(old_parent) != before["parent"]:
            return False
        for field, value in (("parent", old_parent), ("parent_type", before["parent_type"]), ("parent_bone", before["parent_bone"]),
                             ("matrix_parent_inverse", before["inverse"]), *before["channels"]):
            current_value = getattr(self.mesh, field)
            equal = (scope.key(current_value) == scope.key(value)) if field == "parent" else (
                _matrix(current_value) == value if field == "matrix_parent_inverse" else scope.value(current_value) == value)
            if equal:
                continue
            self.write(partial(setattr, self.mesh, field, value),
                       {"parent", "parent_type", "parent_bone", "inverse", "basis", "world", "channels"})
        if self.mesh.vertex_groups.active_index != before["active"]:
            self.write(lambda: setattr(self.mesh.vertex_groups, "active_index", before["active"]), {"active"})
        self.gate()
        # Scope may retain Blender's read-only particle-edit context reference.
        # Report it separately; it is never silently counted as full rollback.
        return self.expected == self.original


def bind(bpy: Any, context: Any, mesh: Any, rig: Any, names: Any, *, automatic: bool, parent: bool) -> dict[str, Any]:
    transaction = Binding(bpy, context, mesh, rig, names, automatic=automatic)
    before = transaction.original["binding"]
    started = time.monotonic()
    native_seconds = 0.
    try:
        if automatic:
            transaction.gate()
            with bpy.context.temp_override(object=rig, active_object=rig, selected_objects=[mesh, rig], selected_editable_objects=[mesh, rig]):
                if not bpy.ops.object.parent_set.poll():
                    raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Automatic weights are unavailable in the isolated context override.")
                native_started = time.monotonic()
                try:
                    transaction.changed = True
                    result = bpy.ops.object.parent_set(type="ARMATURE_AUTO", keep_transform=True)
                finally:
                    native_seconds = time.monotonic()-native_started
            # Capture before any live provider/completion callback runs.
            transaction.expected = transaction.observe()
            if "FINISHED" not in result:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Automatic weights did not finish.")
        else:
            for name in transaction.deform:
                if mesh.vertex_groups.get(name) is None:
                    transaction.write(partial(mesh.vertex_groups.new, name=name), {"groups", "active"})
            if not len(mesh.modifiers):
                modifier = transaction.write(lambda: mesh.modifiers.new(name=f"{rig.name} Deform", type="ARMATURE"), {"modifiers"})
                transaction.write(lambda: setattr(modifier, "object", rig), {"modifiers"})
            if parent:
                world = mesh.matrix_world.copy()
                transaction.write(lambda: setattr(mesh, "parent", rig), {"parent", "basis", "world", "channels"})
                transaction.write(lambda: setattr(mesh, "matrix_world", world), {"basis", "world", "channels"})
        _allocation_shape(before, transaction.expected["binding"], transaction.deform, scope.key(rig), parent=parent)
        modifier = next((item for item in mesh.modifiers if item.type == "ARMATURE" and item.object == rig), None)
        if modifier is None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Binding returned no exact Armature modifier.")
        transaction.owned_output = True
        coverage = _weight_shape(before, transaction.expected["binding"], transaction.deform, automatic=automatic)
        transaction.gate()
        return {"created_vertex_groups": [item[1] for item in transaction.expected["binding"]["groups"][len(before["groups"]):]],
                "modifier": modifier.name, "verified": True, "before_fingerprint": scope.digest(transaction.original),
                "after_fingerprint": scope.digest(transaction.expected), "native_blocking_seconds": native_seconds,
                "operation_seconds": time.monotonic()-started,
                "weight_coverage": coverage,
                "preservation": {"original_group_identities": True, "unrelated_memberships": True,
                                 "base_geometry_custom_data_material_bindings": True, "rig_source_and_explicit_consumers": True,
                                 "physical_context": True}, "durable_backup": False}
    except Exception as error:
        restored = False
        if transaction.changed:
            try:
                # A raised native call may have partial effects, but unknown
                # allocations cannot become owned merely because names match.
                restored = transaction.recover()
            except Exception:
                restored = False
        context_values = {"possible_mutation": transaction.changed and not restored, "rollback_verified": restored,
                          "requires_reinspection": transaction.changed and not restored,
                          "before_fingerprint": scope.digest(transaction.original), "durable_backup": False}
        if isinstance(error, BridgeError):
            raise BridgeError(error.code, error.message, {**error.context, **context_values}) from error
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Armature binding failed; measured recovery status is attached.", context_values) from error
