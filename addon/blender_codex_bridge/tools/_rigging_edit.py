"""Bounded live ownership and context boundaries for legacy rig editing.

Snapshots are comparison receipts, not durable backups. Rest edits deliberately
retain a partial operation when authorization or exact state changes; they never
recreate a rig from bone names or remove newly allocated Blender IDs on failure.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from . import _animation_scope as scope
from . import _object_rna_mutation as measured
from ._object_safety import require_local_object, require_single_user_object_data
from ._object_scope import require_collection_scope

POSE_FIELDS = frozenset({"location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale"})
REST_DERIVED = frozenset({"matrix", "length", "head", "tail"})
POSE_DERIVED = measured.DERIVED | frozenset({"matrix", "matrix_channel"})


def _session(bpy: Any) -> Any:
    ctx = bpy.context
    return (scope.action_token(ctx.scene), scope.key(ctx.view_layer), bpy.data.filepath,
            ctx.mode, scope.action_token(ctx.view_layer.objects.active),
            tuple(sorted(scope.action_token(obj) for obj in scope.bounded(ctx.selected_objects, 1024, "selected objects"))),
            ctx.scene.frame_current, ctx.scene.frame_subframe)


def _authority(context: Any, method: str, permissions: tuple[Permission, ...]) -> None:
    if context is None or not all(hasattr(context, key) for key in ("require", "state", "check_cancelled")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rig mutation requires a live authorization and cancellation context.")
    if context.check_cancelled:
        context.check_cancelled()
    context.require(Permission.EDIT_ANIMATION, *permissions)
    registry = getattr(context, "registry", None)
    if registry is not None:
        registry.prepare(method, context)
        if registry.get(method).toolset not in registry.enabled_toolsets:
            raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Rig toolset was disabled during live authorization.")
    flags = context.state.snapshot()
    if flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Rig mutation emergency-stopped.")
    if flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Rig mutation paused.")


def _rest(bpy: Any, rig: Any) -> Any:
    edit = rig.mode == "EDIT"
    collection = rig.data.edit_bones if edit else rig.data.bones
    records = []
    for bone in scope.bounded(collection, 256, "rest bones"):
        geometry = (tuple(bone.head if edit else bone.head_local), tuple(bone.tail if edit else bone.tail_local),
                    tuple(tuple(row) for row in (bone.matrix if edit else bone.matrix_local)))
        # The full RNA descriptor set remains protected during each phase;
        # EditBone and Bone have different native descriptors at mode changes.
        color = getattr(bone, "color", None)
        custom_color = getattr(color, "custom", None)
        nested = (measured._custom(bone),
                  tuple(scope.key(item) for item in scope.bounded(getattr(bone, "collections", ()), 64, "bone collection memberships")),
                  scope.rna_state(custom_color) if custom_color is not None else ())
        records.append((bone.name, bone.parent.name if bone.parent else None, geometry,
                        scope.rna_state(bone, exclude=REST_DERIVED), nested,
                        scope.rna_state(color) if color is not None else ()))
    return tuple(records)


def _pose(rig: Any, *, omit_transform: str | None = None, omit_constraints: str | None = None) -> Any:
    return tuple((bone.name, scope.rna_state(bone, exclude=POSE_DERIVED | (POSE_FIELDS if bone.name == omit_transform else frozenset())),
                  (measured._custom(bone), _color(bone)), () if bone.name == omit_constraints else measured._components(bone, "constraints"))
                 for bone in scope.bounded(getattr(rig.pose, "bones", ()), 256, "pose bones"))


def _color(owner: Any) -> Any:
    color = getattr(owner, "color", None)
    custom = getattr(color, "custom", None)
    return (scope.rna_state(color) if color is not None else (), scope.rna_state(custom) if custom is not None else ())


def _collections(data: Any) -> Any:
    return tuple((scope.key(item), scope.rna_state(item), measured._custom(item), scope.key(getattr(item, "parent", None)))
                 for item in scope.bounded(getattr(data, "collections_all", ()), 64, "bone collections"))


def rig_source_state(rig: Any) -> Any:
    """Bounded stored rig state; no evaluated deformation/visual verdict."""
    return (_rest(None, rig), _pose(rig), _collections(rig.data), measured._animation(rig), measured._animation(rig.data))


def _common_geometry(rig: Any) -> Any:
    return tuple((record[0], record[1], record[2]) for record in _rest(None, rig))


def _close(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_close(value, right[key]) for key, value in left.items())
    return measured._close(left, right)


def _rest_transition(before: Any, after: Any) -> bool:
    if len(before) != len(after):
        return False
    for first, second in zip(before, after, strict=True):
        if not _close(first[:3], second[:3]) or first[4:] != second[4:]:
            return False
        left, right = dict(first[3]), dict(second[3])
        if any(not _close(left[key], right[key]) for key in left.keys() & right.keys()):
            return False
    return True


class Boundary:
    """A frozen consumer/content receipt checked after the final live provider."""
    def __init__(self, bpy: Any, context: Any, method: str, rig: Any, names: Any, *, kind: str, bone_name: str | None = None):
        require_local_object(rig, operation=method)
        if kind == "rest":
            require_single_user_object_data(rig, operation=method)
        if bpy.context.mode not in {"OBJECT", "POSE"} or rig.mode == "EDIT":
            raise BridgeError(ErrorCode.INVALID_MODE, "Rig edits require Object or Pose Mode before execution.")
        if kind == "rest" and bpy.context.mode != "OBJECT":
            raise BridgeError(ErrorCode.INVALID_MODE, "Rest bone editing requires Object Mode before execution.")
        self.bpy, self.context, self.method, self.rig = bpy, context, method, rig
        self.kind, self.bone_name, self.names = kind, bone_name, names
        self.permissions = (Permission.DELETE_OBJECTS,) if method == "rig.bone_remove" else (Permission.TRANSFORM_OBJECTS,) if kind == "pose" or method == "rig.create" else ()
        self.session = _session(bpy)
        self.original_session = self.session
        self.references = scope.affected_scope(bpy, rig, names)
        self.objects = (rig, *(bpy.data.objects[name] for name in names))
        self.identities = tuple((obj, scope.action_token(obj), scope.action_token(obj.data), obj.name) for obj in self.objects)
        self.protected = self._protected()
        self.expected = self._owned()
        self.steps = 0
        self.attempted = False
        self.new_bones: set[str] = set()
        self.removed_bones: set[str] = set()
        self.renamed_bones: dict[str, str] = {}
        self.bone_selection = {bone.name: tuple((field, bool(getattr(bone, field))) for field in ("select", "select_head", "select_tail") if hasattr(bone, field))
                               for bone in scope.bounded(rig.data.bones, 256, "rest bones")}
        self.bone_radii = {bone.name: (("head_radius", float(bone.head_radius)), ("tail_radius", float(bone.tail_radius)))
                           for bone in scope.bounded(rig.data.bones, 256, "rest bones")}
        self.sources: list[tuple[Any, Any, Any]] = []
        self.check()

    def _protected(self) -> Any:
        records = []
        for obj in self.objects:
            if obj != self.rig:
                records.append(measured._object_state(obj))
                continue
            # Named fields rather than relying on the private tuple layout.
            records.append((scope.action_token(obj), obj.name, scope.action_token(obj.data),
                            scope.rna_state(obj, exclude=measured.DERIVED | measured.TRANSFORMS), measured._channels(obj), measured._custom(obj),
                            measured._components(obj, "modifiers"), measured._components(obj, "constraints"), measured._animation(obj),
                            scope.rna_state(obj.data, exclude=frozenset({"collections"})), measured._custom(obj.data), _collections(obj.data), measured._animation(obj.data),
                            () if self.kind == "rest" else _rest(self.bpy, obj),
                            () if self.kind == "rest" else _pose(obj, omit_transform=self.bone_name if self.kind == "pose" else None,
                                                                omit_constraints=self.bone_name if self.kind == "constraints" else None)))
        return tuple(records)

    def _owned(self) -> Any:
        if self.kind == "rest":
            return _rest(self.bpy, self.rig), _pose(self.rig)
        bone = self.rig.pose.bones.get(self.bone_name)
        if bone is None:
            raise invalid_argument("Exact pose bone disappeared before a rig write.")
        if self.kind == "pose":
            return tuple((field, scope.value(getattr(bone, field))) for field in sorted(POSE_FIELDS))
        return measured._components(bone, "constraints")

    def _source_references(self, obj: Any) -> Any:
        owned_count = 0
        if self.kind == "constraints":
            bone = self.rig.pose.bones[self.bone_name]
            for constraint in bone.constraints:
                for prop in constraint.bl_rna.properties:
                    if prop.type == "POINTER" and getattr(constraint, prop.identifier, None) == obj:
                        owned_count += 1
        records = []
        for consumer in scope.bounded(self.bpy.data.user_map(subset={obj}).get(obj, ()), 100, "constraint source consumers"):
            count = int(consumer.user_of_id(obj)) - (owned_count if consumer == self.rig else 0)
            if count:
                records.append((scope.action_token(consumer), count))
        return tuple(sorted(records))

    def source(self, obj: Any) -> None:
        if obj in self.objects:
            raise invalid_argument("Constraint target would create a self-reference or a dependency cycle.")
        scope.object_scope(self.bpy, obj)
        self.sources.append((obj, measured._object_state(obj), self._source_references(obj)))
        self.check()

    def check(self) -> None:
        try:
            _authority(self.context, self.method, self.permissions)
        except Exception as error:
            raise self.failed(error) from error
        try:
            stable = self.session == _session(self.bpy) and self.references == scope.affected_scope(self.bpy, self.rig, self.names)
            stable = stable and self._protected() == self.protected and self._owned() == self.expected
            for obj, token, data, name in self.identities:
                stable = stable and scope.action_token(obj) == token and scope.action_token(obj.data) == data and obj.name == name and self.bpy.data.objects.get(name) == obj
            for obj, state, references in self.sources:
                stable = stable and self.bpy.data.objects.get(obj.name) == obj and measured._object_state(obj) == state and self._source_references(obj) == references
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            stable = False
        except BridgeError as error:
            raise self.failed(error) from error
        if not stable:
            raise self.failed(invalid_argument("Rig identity, exact consumer closure, content or context changed; further writes and compensation refused.", completed_writes=self.steps, scope_complete=False))
        final_job = getattr(self.context, "check_final_job", None)
        if final_job is not None:
            try:
                final_job()
            except Exception as error:
                raise self.failed(error) from error

    def failed(self, error: Exception) -> BridgeError:
        details = dict(error.context) if isinstance(error, BridgeError) else {}
        possible = self.steps > 0 or getattr(self, "attempted", False)
        details.update({"possible_mutation": possible, "rollback_verified": False, "completed_writes": self.steps,
                        "partial_operation_retained": possible,
                        "recovery": "Reinspect exact current data and restore the operation checkpoint; no compensation was attempted."})
        return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.BLENDER_CONTEXT_ERROR, str(error), details)

    def _adopt(self) -> None:
        self.expected = self._owned()

    def write(self, owner: Any, field: str, value: Any) -> None:
        self.check()
        if _close(scope.value(getattr(owner, field)), scope.value(value)):
            return
        old = self._owned()
        owner_name = getattr(owner, "name", None)
        before_protected = self._protected()
        self.attempted = True
        try:
            setattr(owner, field, value)
        except Exception as error:
            raise self.failed(error) from error
        self.steps += 1
        # Setter receipts are adopted only after the requested field readback
        # and every unrelated protected domain have been measured.
        if not _close(scope.value(getattr(owner, field)), scope.value(value)) or self._protected() != before_protected:
            raise invalid_argument("Rig setter changed unreviewed protected data; partial operation retained.", completed_writes=self.steps, recovery="Reinspect and restore the operation checkpoint; no compensation attempted.")
        after = self._owned()
        predicted: Any
        if self.kind == "pose":
            predicted = tuple((key, scope.value(value) if key == field else item) for key, item in old)
            if not _close(after, predicted):
                raise invalid_argument("Pose setter changed another channel; partial operation retained.", completed_writes=self.steps)
        elif self.kind == "constraints":
            predicted = []
            found = False
            for identity, kind, fields, custom in old:
                if identity == scope.key(owner):
                    found = True
                    if field not in dict(fields):
                        raise invalid_argument("Constraint setter has no complete field receipt.")
                    fields = tuple((key, scope.value(value) if key == field else item) for key, item in fields)
                predicted.append((identity, kind, fields, custom))
            if not found or not _close(after, tuple(predicted)):
                raise invalid_argument("Constraint setter changed an unreviewed field; partial operation retained.", completed_writes=self.steps)
        elif self.kind == "rest":
            predicted = []
            if field == "name":
                assert isinstance(owner_name, str)
                self.renamed_bones[owner_name] = value
            previous_parent = next((record[1] for record in old[0] if record[0] == owner_name), None)
            for name, parent, geometry, fields, custom, color in old[0]:
                if name == owner_name:
                    fields = tuple((key, scope.value(value) if key == field else item) for key, item in fields)
                    if field in {"head", "tail", "roll"}:
                        head, tail, _matrix = geometry
                        geometry = (scope.value(value) if field == "head" else head, scope.value(value) if field == "tail" else tail, None)
                    if field == "parent":
                        parent = None if value is None else value.name
                    if field == "name":
                        name = value
                if field == "name" and parent == owner_name:
                    parent = value
                    fields = tuple((key, ("RNA", "EditBone", value) if key == "parent" else item) for key, item in fields)
                if field == "parent" and (name == previous_parent or (value is not None and name == value.name)):
                    fields = tuple((key, False if key == "select_tail" else item) for key, item in fields)
                if self.rig.mode == "EDIT" and field in {"head", "tail", "roll"} and owner.use_connect and name == previous_parent:
                    fields = tuple((key, float(owner.head_radius) if key == "tail_radius" else item) for key, item in fields)
                predicted.append((name, parent, geometry, fields, custom, color))
            # Matrix is a computed result of the explicitly requested geometry
            # field. Every other bone and all other writable fields must match.
            normalized = []
            for record, before in zip(after[0], predicted, strict=True):
                if before[2][2] is None:
                    record = (*record[:2], (*record[2][:2], None), *record[3:])
                normalized.append(record)
            if not _close(tuple(normalized), tuple(predicted)) or not self._pose_transition(old[1], after[1]):
                raise invalid_argument("Rest setter changed another bone or pose field; partial operation retained.", completed_writes=self.steps)
            if field == "name" and owner_name in self.bone_selection:
                self.bone_selection[value] = self.bone_selection.pop(owner_name)
                self.bone_radii[value] = self.bone_radii.pop(owner_name)
        self.expected = after

    def allocate_constraint(self, bone: Any, kind: str) -> Any:
        self.check()
        before = self.expected
        self.attempted = True
        try:
            constraint = bone.constraints.new(type=kind)
        except Exception as error:
            raise self.failed(error) from error
        self.steps += 1
        after = self._owned()
        if after[:-1] != before or after[-1][0] != scope.key(constraint) or constraint.type != kind or self._protected() != self.protected:
            raise invalid_argument("Constraint allocation changed unreviewed data; allocated constraint retained.", completed_writes=self.steps)
        self.expected = after
        return constraint

    def remove_constraint(self, bone: Any, constraint: Any) -> None:
        self.check()
        predicted = tuple(item for item in self.expected if item[0] != scope.key(constraint))
        self.attempted = True
        try:
            bone.constraints.remove(constraint)
        except Exception as error:
            raise self.failed(error) from error
        self.steps += 1
        if self._owned() != predicted or self._protected() != self.protected:
            raise invalid_argument("Constraint removal changed unreviewed data; reinspection required.", completed_writes=self.steps)
        self.expected = predicted

    def allocate_bone(self, bones: Any, name: str) -> Any:
        self.check()
        before = self.expected
        self.attempted = True
        result = bones.new(name)
        self.steps += 1
        self.new_bones.add(name)
        after = self._owned()
        if tuple(item for item in after[0] if item[0] != name) != before[0] or len(after[0]) != len(before[0])+1 or after[1] != before[1] or self._protected() != self.protected:
            raise invalid_argument("Bone allocation changed protected data; partial operation retained.", completed_writes=self.steps)
        self.expected = after
        return result

    def remove_bone(self, bones: Any, bone: Any) -> None:
        self.check()
        before, name = self.expected, bone.name
        self.attempted = True
        bones.remove(bone)
        self.steps += 1
        self.removed_bones.add(name)
        after = self._owned()
        if after[0] != tuple(item for item in before[0] if item[0] != name) or after[1] != before[1] or self._protected() != self.protected:
            raise invalid_argument("Bone removal changed unreviewed data; partial operation retained.", completed_writes=self.steps)
        self.expected = after

    def contextual(self, callback: Any, *, change: tuple[int, Any], mode: bool = False) -> None:
        self.check()
        geometry = _common_geometry(self.rig)
        rest = _rest(self.bpy, self.rig)
        pose = _pose(self.rig)
        expected_session = list(self.session)
        expected_session[change[0]] = change[1]
        self.attempted = True
        callback()
        self.steps += 1
        # Context writes cannot adopt geometry or unrelated object edits.
        if _session(self.bpy) != tuple(expected_session) or not _close(geometry, _common_geometry(self.rig)) or not _rest_transition(rest, _rest(self.bpy, self.rig)) or self._protected() != self.protected or not self._pose_transition(pose, _pose(self.rig)):
            raise invalid_argument("Context transition changed protected rig data; context retained for inspection.", completed_writes=self.steps)
        self.session = _session(self.bpy)
        if mode:
            self._adopt()

    def _pose_transition(self, before: Any, after: Any) -> bool:
        """Keep existing channel/configuration content across native pose rebuild."""
        remaining = list(before)
        rest_names = {record[0] for record in _rest(self.bpy, self.rig)}
        for record in after:
            exact = next((item for item in remaining if item[0] == record[0]), None)
            if exact is not None:
                if not _close(exact, record):
                    return False
                remaining.remove(exact)
                continue
            renamed = next((item for item in remaining if self.renamed_bones.get(item[0]) == record[0]), None)
            if renamed is not None:
                renamed_fields = tuple((name, record[0] if name == "name" else value) for name, value in renamed[1])
                if not _close((renamed_fields, *renamed[2:]), record[1:]):
                    return False
                remaining.remove(renamed)
                continue
            fields = dict(record[1])
            defaults = {"location": (0., 0., 0.), "rotation_euler": (0., 0., 0.),
                        "rotation_quaternion": (1., 0., 0., 0.), "scale": (1., 1., 1.)}
            if record[0] not in self.new_bones or record[0] not in rest_names or record[2][0] or record[3] or any(not _close(fields.get(name), value) for name, value in defaults.items()):
                return False
        return all(record[0] in self.removed_bones or record[0] in self.renamed_bones for record in remaining)

    @contextmanager
    def edit(self) -> Iterator[Any]:
        bpy, rig = self.bpy, self.rig
        selected = list(bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active
        if rig.hide_get() or rig.hide_viewport or rig.hide_select:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Rest editing requires a visible, selectable armature.")
        try:
            for obj in selected:
                self.select(obj, False)
            self.select(rig, True)
            self.contextual(lambda: setattr(bpy.context.view_layer.objects, "active", rig), change=(4, scope.action_token(rig)))
            self.contextual(lambda: self._mode("EDIT"), change=(3, "EDIT_ARMATURE"), mode=True)
            yield rig.data.edit_bones
            for name, fields in self.bone_selection.items():
                bone = rig.data.edit_bones.get(name)
                if bone is not None:
                    for field, value in fields:
                        if bool(getattr(bone, field)) != value:
                            self.write(bone, field, value)
            self.contextual(lambda: self._mode("OBJECT"), change=(3, "OBJECT"), mode=True)
            # EditBone transforms synchronize connected envelope radii. Native
            # Bone RNA in Object Mode can restore distinct original radii
            # without propagating the restoration to connected neighbours.
            for name, radius_fields in self.bone_radii.items():
                bone = rig.data.bones.get(name)
                if bone is not None:
                    for field, radius in radius_fields:
                        if float(getattr(bone, field)) != radius:
                            self.write(bone, field, radius)
            self.select(rig, False)
            for obj in selected:
                self.select(obj, True)
            self.contextual(lambda: setattr(bpy.context.view_layer.objects, "active", active), change=(4, scope.action_token(active)))
            self.check()
        except Exception as error:
            # No unconditional finally writes: revocation/manual interleaving
            # must not cause a mode change or overwrite the user's selection.
            details = dict(error.context or {}) if isinstance(error, BridgeError) else {}
            details.update({"completed_writes": self.steps, "partial_operation_retained": self.steps > 0,
                            "current_mode": rig.mode, "context_restored": _session(bpy) == self.original_session,
                            "possible_mutation": self.steps > 0, "rollback_verified": False,
                            "recovery": "Reinspect exact current state and use the operation checkpoint; retained comparison buffers are not backups."})
            code = error.code if isinstance(error, BridgeError) else ErrorCode.BLENDER_CONTEXT_ERROR
            raise BridgeError(code, str(error), details) from error

    def _mode(self, mode: str) -> None:
        if self.bpy.ops.object.mode_set(mode=mode) != {"FINISHED"} or self.rig.mode != mode:
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Blender did not reach the requested Armature mode.")

    def select(self, obj: Any, selected: bool) -> None:
        identities = set(self.session[5])
        if selected:
            identities.add(scope.action_token(obj))
        else:
            identities.discard(scope.action_token(obj))
        self.contextual(lambda: obj.select_set(selected), change=(5, tuple(sorted(identities))))


def require_independent_rest(rig: Any, affected: Any, operation: str) -> None:
    if affected or getattr(rig, "animation_data", None) is not None or getattr(rig.data, "animation_data", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, f"{operation} of a consumer-bound or animated rig requires a reviewed propagation transaction; no context or data was changed.")
    if any(len(bone.constraints) for bone in scope.bounded(getattr(rig.pose, "bones", ()), 256, "pose bones")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, f"{operation} with pose constraints needs a reviewed propagation transaction.")
    if any(getattr(bone, "custom_shape_transform", None) is not None for bone in scope.bounded(getattr(rig.pose, "bones", ()), 256, "pose bones")) or any(
        getattr(bone, field, None) is not None for bone in scope.bounded(rig.data.bones, 256, "rest bones") for field in ("bbone_custom_handle_start", "bbone_custom_handle_end")
    ):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, f"{operation} with custom bone references needs a reviewed propagation transaction.")


class Creation:
    """Retain exact new IDs on failure; never infer authority to delete them."""
    def __init__(self, bpy: Any, context: Any, collection: Any):
        self.bpy, self.context, self.collection = bpy, context, collection
        require_collection_scope(bpy, collection, operation="Rig creation")
        self.session = _session(bpy)
        self.ids = self._ids()
        self.original_ids = self.ids
        self.created: list[Any] = []
        self.retained_records: list[Any] = []
        self.allocation_attempted = False
        self.content: Any = {}
        self.check()

    def _ids(self) -> Any:
        return (tuple(scope.action_token(item) for item in scope.bounded(self.bpy.data.objects, 2048, "project objects")),
                tuple(scope.action_token(item) for item in scope.bounded(self.bpy.data.armatures, 256, "project armatures")))

    def check(self) -> None:
        _authority(self.context, "rig.create", (Permission.TRANSFORM_OBJECTS,))
        require_collection_scope(self.bpy, self.collection, operation="Rig creation")
        if _session(self.bpy) != self.session or self._ids() != self.ids or self._content() != self.content:
            raise invalid_argument("Rig creation session or ID inventory changed; further writes refused.")
        final_job = getattr(self.context, "check_final_job", None)
        if final_job is not None:
            final_job()

    def _content(self) -> Any:
        records = {}
        for item in self.created:
            is_object = item.bl_rna.identifier == "Object"
            records[scope.action_token(item)] = {
                "rna": scope.rna_state(item, exclude=measured.DERIVED | measured.TRANSFORMS if is_object else frozenset({"collections"})),
                "channels": measured._channels(item) if is_object else (),
                "custom": measured._custom(item),
                "animation": measured._animation(item),
                "pose": _pose(item) if is_object else (),
                "modifiers": measured._components(item, "modifiers") if is_object else (),
                "constraints": measured._components(item, "constraints") if is_object else (),
                "collections": tuple(scope.action_token(value) for value in item.users_collection) if is_object else _collections(item),
                "bones": () if is_object else tuple((bone.name, scope.rna_state(bone)) for bone in scope.bounded(item.bones, 256, "new rest bones")),
            }
        return records

    def allocate(self, callback: Any) -> Any:
        self.check()
        self.allocation_attempted = True
        item = callback()
        before = self._content()
        self.created.append(item)
        self.retained_records.append({"name": item.name, "identity": scope.action_token(item), "type": item.bl_rna.identifier})
        current = self._ids()
        expected = (set(self.ids[0]), set(self.ids[1]))
        index = 0 if getattr(item.bl_rna, "identifier", None) == "Object" else 1
        expected[index].add(scope.action_token(item))
        if any(set(actual) != wanted for actual, wanted in zip(current, expected, strict=True)):
            raise invalid_argument("Rig allocation changed another ID; newly allocated IDs retained.")
        if before != self.content:
            raise invalid_argument("Rig allocation changed a prior ID; newly allocated IDs retained.")
        self.ids = current
        self.content = self._content()
        return item

    def assign(self, owner: Any, field: str, value: Any) -> None:
        self.check()
        predicted = deepcopy(self.content)
        record = predicted[scope.action_token(owner)]
        category = "channels" if field in dict(record["channels"]) else "rna"
        if field not in dict(record[category]):
            raise invalid_argument("New rig property lacks a complete writable receipt.", property=field)
        record[category] = tuple((name, scope.value(value) if name == field else old) for name, old in record[category])
        setattr(owner, field, value)
        current = self._content()
        if not _close(current, predicted):
            raise invalid_argument("New rig setter changed an unreviewed field; IDs retained.")
        self.content = current

    def link(self, owner: Any) -> None:
        self.check()
        predicted = deepcopy(self.content)
        predicted[scope.action_token(owner)]["collections"] = (scope.action_token(self.collection),)
        self.collection.objects.link(owner)
        current = self._content()
        if current != predicted:
            raise invalid_argument("Linking the new rig changed another owned property; IDs retained.")
        self.content = current

    def failure(self, error: Exception) -> BridgeError:
        details = dict(error.context or {}) if isinstance(error, BridgeError) else {}
        records = getattr(self, "retained_records", None)
        if records is None:
            records = [{"name": item.name, "identity": scope.action_token(item), "type": item.bl_rna.identifier} for item in self.created]
        unattributed: list[dict[str, Any]] = []
        if hasattr(self, "bpy"):
            try:
                known = {record["identity"] for record in records}
                for collection, original in zip((self.bpy.data.objects, self.bpy.data.armatures), self.original_ids, strict=True):
                    unattributed.extend({"name": item.name, "identity": scope.action_token(item), "ownership_inferred": False}
                                        for item in scope.bounded(collection, 2048, "failure ID inventory") if scope.action_token(item) not in set(original) | known)
            except (AttributeError, ReferenceError, RuntimeError, BridgeError):
                details["failure_id_inventory_complete"] = False
        details.update({"retained_ids": records,
                        "unattributed_new_ids": unattributed, "possible_mutation": bool(self.created) or getattr(self, "allocation_attempted", False),
                        "rollback_verified": False, "partial_operation_retained": bool(self.created) or getattr(self, "allocation_attempted", False), "automatic_id_deletion": False,
                        "recovery": "Reinspect retained exact IDs and use the operation checkpoint; explicit deletion requires DELETE_OBJECTS."})
        return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.BLENDER_CONTEXT_ERROR, str(error), details)
