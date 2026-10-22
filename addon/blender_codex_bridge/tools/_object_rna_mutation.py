"""Live boundaries for bounded object-owned RNA edits.

This is deliberately separate from object deletion scope. Incoming local Object
consumers are reported, while unexplained non-Object references fail closed.
An RNA snapshot is comparison evidence, never a durable recovery backup.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import check_final_mutation
from . import _animation_scope as scope
from ._object_safety import require_local_object
from ._object_scope import _ordinary_scene_membership, require_object_scope

LOGGER = logging.getLogger(__name__)
TRANSFORMS = frozenset({"location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale"})
DERIVED = frozenset({"matrix_world", "matrix_local", "matrix_basis", "dimensions"})


def _items(values: Any, maximum: int, label: str) -> list[Any]:
    return scope.bounded(values, maximum, label)


def _custom(owner: Any) -> Any:
    if not hasattr(owner, "keys"):
        return ()
    try:
        keys = _items(owner.keys(), 128, "custom properties")
    except TypeError as error:
        if "doesn't support IDProperties" in str(error):
            return ()
        raise
    remaining = [4096]
    def read(raw: Any, depth: int = 0) -> Any:
        remaining[0] -= 1
        if remaining[0] < 0:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Custom-property comparison exceeds 4096 total values.")
        if depth > 4:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Custom-property nesting exceeds four levels.")
        if hasattr(raw, "keys") and not hasattr(raw, "as_pointer"):
            return tuple((str(k), read(raw[k], depth+1)) for k in _items(raw.keys(), 128, "custom fields"))
        if raw is None or isinstance(raw, (str, bool, int, float)) or hasattr(raw, "as_pointer"):
            return scope.value(raw)
        return tuple(read(item, depth+1) for item in _items(raw, 256, "custom array"))
    return tuple((str(name), read(owner[name])) for name in keys)


def component_state(owner: Any) -> Any:
    fields = scope.rna_state(owner)
    if hasattr(owner, "persistent_uid"):
        fields = (*fields, ("__persistent_uid__", int(owner.persistent_uid)))
    return (scope.key(owner), getattr(owner, "type", None), fields, _custom(owner))


def _components(obj: Any, kind: str) -> Any:
    return tuple(component_state(item) for item in _items(getattr(obj, kind, ()), 100, kind))


def _channels(obj: Any) -> Any:
    fields = (*sorted(TRANSFORMS), "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale", "matrix_parent_inverse")
    return tuple((field, scope.value(getattr(obj, field))) for field in fields if hasattr(obj, field))


def _animation(obj: Any) -> Any:
    data = getattr(obj, "animation_data", None)
    if data is None:
        return None
    action = getattr(data, "action", None)
    actions = {}
    def content(bound: Any) -> Any:
        if bound is None:
            return None
        token = scope.action_token(bound)
        if token not in actions:
            if len(actions) >= 16:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object animation comparison exceeds 16 distinct Actions.")
            actions[token] = scope.action_content(bound)
        return actions[token]
    content(action)
    drivers = []
    total_controls, total_strips = 0, 0
    for curve in _items(getattr(data, "drivers", ()), 128, "object drivers"):
        total_controls += len(curve.keyframe_points)
        if total_controls > 16384:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object driver comparison exceeds 16384 keys.")
        driver = curve.driver
        variables = tuple((scope.rna_state(variable), tuple(scope.rna_state(target) for target in _items(variable.targets, 8, "driver targets")))
                          for variable in _items(driver.variables, 32, "driver variables"))
        drivers.append((scope.curve_content(curve), scope.rna_state(driver), variables))
    tracks = []
    for track in _items(getattr(data, "nla_tracks", ()), 32, "NLA tracks"):
        strips = []
        for strip in _items(track.strips, 64, "NLA strips"):
            total_strips += 1
            if total_strips > 64:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object animation comparison exceeds 64 total strips.")
            total_controls += sum(len(curve.keyframe_points) for curve in _items(getattr(strip, "fcurves", ()), 32, "NLA controls"))
            if total_controls > 16384:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object control comparison exceeds 16384 keys.")
            bound = getattr(strip, "action", None)
            strips.append((scope.rna_state(strip), scope.action_token(bound), content(bound),
                           tuple(scope.curve_content(curve) for curve in _items(getattr(strip, "fcurves", ()), 32, "NLA controls"))))
        tracks.append((scope.rna_state(track), tuple(strips)))
    return (scope.key(data), scope.rna_state(data), scope.action_token(action), content(action), tuple(drivers), tuple(tracks))


def _pose(obj: Any) -> Any:
    pose = getattr(obj, "pose", None)
    if pose is None:
        return None
    return tuple((bone.name, scope.rna_state(bone, exclude=DERIVED | frozenset({"matrix_channel", "matrix"})), _custom(bone), _components(bone, "constraints"))
                 for bone in _items(pose.bones, 256, "pose bones"))


def _data_state(obj: Any) -> Any:
    data = getattr(obj, "data", None)
    if data is None:
        return None
    base = (scope.action_token(data), getattr(data, "users", None), getattr(data, "library", None) is None,
            getattr(data, "override_library", None) is None, getattr(data, "is_editable", True),
            scope.rna_state(data, exclude=frozenset({"collections", "collections_all"}) if getattr(obj, "type", None) == "ARMATURE" else frozenset()), _custom(data), tuple(scope.action_token(mat) for mat in _items(getattr(data, "materials", ()), 128, "material bindings")))
    if getattr(obj, "type", None) == "MESH":
        if len(data.vertices)+len(data.edges)+len(data.loops)+len(data.polygons) > 131072:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Mesh comparison exceeds 131072 structural elements.")
        attributes = []
        total = 0
        for attribute in _items(getattr(data, "attributes", ()), 128, "mesh attributes"):
            total += len(attribute.data)
            if total > 262144:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Mesh attribute comparison exceeds 262144 values.")
            attributes.append((attribute.name, attribute.domain, attribute.data_type, tuple(scope.rna_state(item) for item in attribute.data)))
        keys = getattr(data, "shape_keys", None)
        shape = None
        if keys is not None:
            blocks = _items(keys.key_blocks, 64, "shape key blocks")
            if sum(len(block.data) for block in blocks) > 262144:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shape-key comparison exceeds 262144 points.")
            shape = (scope.action_token(keys), scope.rna_state(keys), tuple((scope.rna_state(block), tuple(tuple(point.co) for point in block.data)) for block in blocks))
        geometry = (tuple((scope.rna_state(v), tuple((g.group, g.weight) for g in v.groups)) for v in data.vertices),
                    tuple((tuple(edge.vertices), scope.rna_state(edge)) for edge in data.edges),
                    tuple((loop.vertex_index, loop.edge_index, scope.rna_state(loop)) for loop in data.loops),
                    tuple((tuple(poly.vertices), poly.loop_start, poly.loop_total, scope.rna_state(poly)) for poly in data.polygons),
                    tuple(attributes), shape)
        return base, geometry
    if getattr(obj, "type", None) == "ARMATURE":
        collections = _items(getattr(data, "collections_all", getattr(data, "collections", ())), 256, "bone collections")
        collection_state = tuple((scope.key(collection), scope.rna_state(collection, exclude=frozenset({"children"})),
                                  tuple(scope.key(child) for child in _items(getattr(collection, "children", ()), 256, "bone collection children")),
                                  tuple(bone.name for bone in _items(getattr(collection, "bones", ()), 256, "bone collection members")), _custom(collection)) for collection in collections)
        active = getattr(getattr(data, "collections", None), "active", None)
        bones = tuple((bone.name, tuple(bone.head_local), tuple(bone.tail_local), scope.rna_state(bone, exclude=frozenset({"collections"})),
                       tuple(scope.key(collection) for collection in _items(getattr(bone, "collections", ()), 256, "bone memberships")), _custom(bone))
                      for bone in _items(data.bones, 256, "rest bones"))
        return base, bones, (scope.key(active), collection_state)
    # Object-owned settings may refer to immutable external data, but direct
    # geometry application below only accepts the explicitly measured Mesh path.
    return base


def _object_state(obj: Any, *, transform: bool = False, omit: str | None = None, artist_profile: bool = False) -> Any:
    exclude = DERIVED | (TRANSFORMS if transform else frozenset())
    if artist_profile:
        from ._artist_scope_profile import IGNORED_OBJECT_RUNTIME
        exclude |= IGNORED_OBJECT_RUNTIME
    # The channels are included separately, including non-current rotation modes.
    return (scope.action_token(obj), str(obj.name), scope.action_token(getattr(obj, "data", None)),
            scope.rna_state(obj, exclude=exclude | TRANSFORMS), () if transform else _channels(obj),
            _custom(obj), () if omit == "modifiers" else _components(obj, "modifiers"),
            () if omit == "constraints" else _components(obj, "constraints"),
            tuple(scope.action_token(item) for item in _items(getattr(obj, "users_collection", ()), 32, "owning collections")),
            _animation(obj), _pose(obj), _data_state(obj),
            tuple(scope.rna_state(group) for group in _items(getattr(obj, "vertex_groups", ()), 256, "vertex groups")),
            tuple((slot.link, scope.action_token(slot.material)) for slot in _items(getattr(obj, "material_slots", ()), 128, "material slots")))


def object_state(obj: Any, *, omit: frozenset[str] = frozenset()) -> tuple[Any, ...]:
    """Named immutable projections for other domains' separate mutation proofs.

    Omissions are internal literal field names, never caller-supplied scope.
    A caller must independently measure every omitted field it modifies.
    """
    names = ("identity", "name", "data_identity", "rna", "channels", "custom", "modifiers", "constraints", "collections",
             "animation", "pose", "data", "vertex_groups", "material_slots")
    unknown = omit-set(names)
    if unknown:
        raise ValueError("Unknown internal object snapshot projection")
    return tuple((name, state) for name, state in zip(names, _object_state(obj), strict=True) if name not in omit)


def _native_mesh_metadata(base: Any, mesh: Any) -> Any:
    """Predict the automatic texture-space getters from native base vertices."""
    fields = dict(base[5])
    if fields.get("use_auto_texspace") is not True:
        return base
    vertices = mesh.vertices
    if len(vertices):
        low = tuple(min(float(vertex.co[axis]) for vertex in vertices) for axis in range(3))
        high = tuple(max(float(vertex.co[axis]) for vertex in vertices) for axis in range(3))
        location = tuple((a+b)*.5 for a, b in zip(low, high, strict=True))
        extent = tuple((b-a)*.5 for a, b in zip(low, high, strict=True))
        size = tuple(1. if value == 0. else max(value, .00001) for value in extent)
    else:
        location, size = (0., 0., 0.), (1., 1., 1.)
    aliases = {"texspace_location": location, "texspace_size": size}
    result = list(base)
    result[5] = tuple((field, aliases.get(field, old)) for field, old in base[5])
    return tuple(result)


def _rotation_mode_delta(obj: Any, requested: str) -> dict[str, Any]:
    if obj.rotation_mode == requested:
        return {}
    import mathutils
    if obj.rotation_mode == "QUATERNION":
        rotation = mathutils.Quaternion(obj.rotation_quaternion)
    elif obj.rotation_mode == "AXIS_ANGLE":
        angle, *axis = obj.rotation_axis_angle
        rotation = mathutils.Quaternion(axis, angle)
    else:
        rotation = mathutils.Euler(obj.rotation_euler, obj.rotation_mode).to_quaternion()
    if requested == "QUATERNION":
        return {"rotation_quaternion": tuple(rotation)}
    if requested == "AXIS_ANGLE":
        axis, angle = rotation.to_axis_angle()
        return {"rotation_axis_angle": (angle, *axis)}
    return {"rotation_euler": tuple(rotation.to_euler(requested))}


def _is_object(owner: Any) -> bool:
    return getattr(getattr(owner, "bl_rna", None), "identifier", None) == "Object"


def _scene_reference(bpy: Any, scene: Any, owner: Any, obj: Any) -> Any:
    if _ordinary_scene_membership(scene, owner, obj):
        return ("MEMBERSHIP",)
    if scope.key(owner) != scope.key(scene):
        return None
    # Camera binding is an explicitly measured extra Scene reference, not a
    # global relaxation of ordinary collection/base ownership.
    root = int(scene.collection.objects.get(obj.name) == obj)
    bases = sum(layer.objects.get(obj.name) == obj for layer in _items(scene.view_layers, 256, "view layers"))
    camera = int(getattr(scene, "camera", None) == obj)
    particle = getattr(getattr(scene, "tool_settings", None), "particle_edit", None)
    particle_ref = int(particle is not None and getattr(particle, "object", None) == obj)
    if (camera or particle_ref) and scene.collection.user_of_id(obj) == root and scene.user_of_id(obj) == root+bases+camera+particle_ref:
        return ("SCENE_REFERENCES", camera, particle_ref, None if not particle_ref else scope.rna_state(particle))
    return None


def _closure(bpy: Any, obj: Any) -> tuple[tuple[Any, ...], Any]:
    pending, found, references = [obj], {}, []
    while pending:
        current = pending.pop()
        if scope.key(current) in found:
            continue
        if len(found) >= 32:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object consumer closure exceeds 32 objects.")
        require_object_scope(bpy, current, operation="Object RNA editing")
        found[scope.key(current)] = current
        users = _items(bpy.data.user_map(subset={current}).get(current, ()), 100, "object consumers")
        for owner in users:
            count = int(owner.user_of_id(current))
            containers = tuple(getattr(current, "users_collection", ()))
            if any(scope.key(owner) == scope.key(item) and count == 1 for item in containers):
                role = ("COLLECTION",)
            else:
                role = _scene_reference(bpy, bpy.context.scene, owner, current)
                if role is None:
                    if not _is_object(owner) or not 0 < count <= 256:
                        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object has an unexplained non-Object dependency consumer.", {"object": current.name, "consumer": getattr(owner, "name", None), "scope_complete": False})
                    role = ("OBJECT",)
                    pending.append(owner)
            references.append((scope.action_token(current), scope.action_token(owner), count, role))
    return tuple(found[key] for key in sorted(found)), tuple(sorted(references))


def _close(a: Any, b: Any) -> bool:
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
    return a == b


def _predicted_delta(before: Any, predicted: Any, observed: Any) -> bool:
    """Float tolerance applies to changed requested values, never protected ones."""
    if before == predicted:
        return observed == before
    if isinstance(before, (tuple, list)) and isinstance(predicted, (tuple, list)) and isinstance(observed, (tuple, list)):
        return len(before) == len(predicted) == len(observed) and all(_predicted_delta(old, wanted, actual) for old, wanted, actual in zip(before, predicted, observed, strict=True))
    return _close(predicted, observed)


class Boundary:
    """Compare-and-swap proof with live authority before every owned write."""
    def __init__(self, bpy: Any, context: Any, method: str, obj: Any, *, kind: str | None = None, transform: bool = False, artist_profile: bool = False):
        require_local_object(obj, operation=method)
        if context is None or not all(hasattr(context, name) for name in ("require", "state", "check_cancelled")):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object mutation requires a live permission/state context.")
        self.bpy, self.context, self.method, self.obj = bpy, context, method, obj
        self.kind, self.transform = kind, transform
        from . import artist_loop
        self.artist_stamp = artist_loop.policy_stamp(context)
        self.artist_review = artist_profile or artist_loop.needs_review(context)
        if self.artist_review:
            artist_loop.require_reviewed_mutator(context, method, reviewed=transform and method in artist_loop.TRANSFORM_METHODS)
            artist_loop.pre_closure(bpy)
        self.session = self._session()
        self.objects, self.references = _closure(bpy, obj)
        if self.artist_review:
            artist_loop.require_profile(bpy, self.objects)
            artist_loop.check_affected(context, bpy, self.objects, stamp=self.artist_stamp)
        self.protected = self._protected()
        self.expected = self._owned()
        self.original = self.expected
        self.started = False
        self.allocated = None
        self.stopped: BridgeError | None = None
        self.native_seconds: float | None = None
        self.extra: list[tuple[Any, Any, Any]] = []
        if self.artist_review:
            artist_loop.check_preview_origin(self)

    def _session(self) -> Any:
        ctx = self.bpy.context
        return (scope.action_token(ctx.scene), scope.key(ctx.view_layer), self.bpy.data.filepath, ctx.mode,
                tuple(scope.action_token(item) for item in _items(getattr(ctx, "selected_objects", ()), 1024, "selection")),
                scope.action_token(ctx.view_layer.objects.active), getattr(ctx.scene, "frame_current", None), getattr(ctx.scene, "frame_subframe", None))

    def _protected(self) -> Any:
        return tuple(_object_state(item, transform=self.transform and item == self.obj, omit=self.kind if item == self.obj else None,
                                   artist_profile=self.artist_review) for item in self.objects)

    def _owned(self) -> Any:
        return _channels(self.obj) if self.transform else _components(self.obj, self.kind) if self.kind else ()

    def _authority(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            callback = self.context.check_cancelled
            if callback:
                callback()
            required = (Permission.TRANSFORM_OBJECTS, Permission.EDIT_MESH) if self.method in {"transform.apply", "modifier.apply"} else (Permission.TRANSFORM_OBJECTS,)
            # Native application writes the base Mesh as well as object-owned
            # settings. Keep both grants coherent even for direct contexts
            # without a registry; ordinary object settings do not write Mesh.
            self.context.require(*required)
            registry = getattr(self.context, "registry", None)
            if registry is not None:
                registry.prepare(self.method, self.context)
                if registry.get(self.method).toolset not in registry.enabled_toolsets:
                    raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Object toolset disabled during live permission validation.")
            # No further permission/cancellation providers run after this snapshot.
            flags = self.context.state.snapshot()
            if flags.get("emergency_stopped"):
                raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Object mutation emergency-stopped.")
            if flags.get("paused"):
                raise BridgeError(ErrorCode.AGENT_PAUSED, "Object mutation paused.")

        except BridgeError as error:
            if error.code in {ErrorCode.PERMISSION_DENIED.value, ErrorCode.TOOLSET_DISABLED.value, ErrorCode.TIMEOUT.value,
                              ErrorCode.EMERGENCY_STOPPED.value, ErrorCode.AGENT_PAUSED.value}:
                self.stopped = error
            raise

    def check(self) -> None:
        self._authority()
        from . import artist_loop
        review = self.artist_review or artist_loop.needs_review(self.context)
        try:
            if review:
                artist_loop.pre_closure(self.bpy)
            objects, references = _closure(self.bpy, self.obj)
            if review:
                artist_loop.require_profile(self.bpy, objects)
                artist_loop.check_affected(self.context, self.bpy, objects, stamp=self.artist_stamp)
            stable = (self._session() == self.session and tuple(scope.action_token(item) for item in objects) == tuple(scope.action_token(item) for item in self.objects)
                      and references == self.references and self._protected() == self.protected and self._owned() == self.expected
                      and self.bpy.data.objects.get(self.obj.name) == self.obj)
            for source, snapshot, references in self.extra:
                require_object_scope(self.bpy, source, operation=self.method)
                stable = stable and self.bpy.data.objects.get(source.name) == source and _object_state(source) == snapshot and self._source_users(source) == references
        except (AttributeError, ReferenceError, TypeError, RuntimeError):
            stable = False
        if not stable:
            raise invalid_argument("Object identity, content, context or consumers changed; further writes and compensation are refused.", scope_complete=False)
        self.final()

    def final(self) -> None:
        """Latch canonical lifetime loss without rerunning live providers."""
        if self.stopped is not None:
            raise self.stopped
        try:
            check_final_mutation(self.context, self.method)
        except BridgeError as error:
            if error.code in {ErrorCode.PERMISSION_DENIED.value, ErrorCode.TOOLSET_DISABLED.value, ErrorCode.TIMEOUT.value,
                              ErrorCode.EMERGENCY_STOPPED.value, ErrorCode.AGENT_PAUSED.value}:
                self.stopped = error
            raise

    def sources(self, assignments: Sequence[Any]) -> None:
        for assignment in assignments:
            source = assignment.value
            if _is_object(source):
                if any(scope.key(source) == scope.key(item) for item in self.objects):
                    raise invalid_argument("Object pointer would create a self-reference or dependency cycle.", property=assignment.name)
                require_object_scope(self.bpy, source, operation=self.method)
                if not any(scope.key(source) == scope.key(item[0]) for item in self.extra):
                    self.extra.append((source, _object_state(source), self._source_users(source)))

    def _source_users(self, source: Any) -> Any:
        records = []
        owned = getattr(self.obj, self.kind, ()) if self.kind else ()
        own_count = 0
        for component in owned:
            for prop in component.bl_rna.properties:
                if prop.type == "POINTER" and getattr(component, prop.identifier, None) == source:
                    own_count += 1
        for consumer in _items(self.bpy.data.user_map(subset={source}).get(source, ()), 100, "source consumers"):
            count = int(consumer.user_of_id(source))
            if scope.key(consumer) == scope.key(self.obj):
                count -= own_count
            if count:
                records.append((scope.action_token(consumer), count))
        return tuple(sorted(records))

    def _predict(self, owner: Any, name: str, requested: Any) -> Any:
        before = self._owned()
        expected_value = scope.value(requested)
        if self.transform:
            if name not in dict(before):
                raise invalid_argument("Unsupported guarded transform channel.", property=name)
            aliases = _rotation_mode_delta(owner, requested) if name == "rotation_mode" else {}
            aliases[name] = expected_value
            return tuple((field, aliases.get(field, old)) for field, old in before)
        found = False
        result = []
        for identity, kind, fields, custom in before:
            if identity == scope.key(owner):
                found = True
                aliases = {name: expected_value}
                if self.kind == "constraints" and name == "mute":
                    aliases["enabled"] = not expected_value
                if self.kind == "modifiers" and kind == "BEVEL" and name == "width":
                    aliases["width_pct"] = expected_value
                fields = tuple((field, aliases.get(field, old)) for field, old in fields)
                if name not in dict(fields):
                    raise invalid_argument("RNA property has no complete writable snapshot.", property=name)
            if self.kind in {"constraints", "modifiers"} and name == ("active" if self.kind == "constraints" else "is_active") and requested is True and identity != scope.key(owner):
                fields = tuple((field, False if field == name else old) for field, old in fields)
            result.append((identity, kind, fields, custom))
        if not found:
            raise invalid_argument("Owned component identity changed before its write.")
        return tuple(result)

    def write(self, owner: Any, name: str, requested: Any) -> None:
        self.check()
        predicted = self._predict(owner, name, requested)
        before = self.expected
        self.final()
        self.started = True
        try:
            setattr(owner, name, requested)
        finally:
            receipt = self._owned()
            # Only the predicted field delta may be adopted. A failed native
            # setter with any unexplained delta stays unowned and is retained.
            if _predicted_delta(before, predicted, receipt) or receipt == before:
                self.expected = receipt
        if not _predicted_delta(before, predicted, receipt) or receipt != self.expected:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Blender did not retain exactly the requested RNA field delta.")
        self.check()

    def apply(self, owner: Any, assignments: Sequence[Any]) -> None:
        self.sources(assignments)
        previous: list[tuple[str, Any]] = []
        try:
            for assignment in assignments:
                old = getattr(owner, assignment.name)
                if hasattr(old, "copy") and not hasattr(old, "as_pointer"):
                    old = old.copy()
                elif isinstance(old, (set, tuple, list)):
                    old = type(old)(old)
                elif hasattr(old, "__len__") and hasattr(old, "__iter__") and not isinstance(old, (str, bytes)) and not hasattr(old, "as_pointer"):
                    old = tuple(old)
                previous.append((assignment.name, old))
                self.write(owner, assignment.name, assignment.value)
            self.check()
        except Exception as error:
            restored = False
            try:
                if self.transform:
                    self.restore_transform()
                else:
                    for name, old in reversed(previous):
                        self.write(owner, name, old)
                self.check()
                restored = self.expected == self.original
            except Exception:
                LOGGER.exception("Guarded RNA compensation refused or incomplete")
            raise self.failure(error, restored=restored) from error

    def restore_transform(self) -> None:
        """Restore predicted native rotation-mode aliases as well as requests."""
        if not self.transform:
            raise ValueError("Transform compensation requires a transform boundary")
        original = dict(self.original)
        for field in ("rotation_mode", "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale"):
            if field in original and scope.value(getattr(self.obj, field)) != original[field]:
                self.write(self.obj, field, original[field])
        self.check()

    def allocate(self, operation: Any, kind: str) -> Any:
        self.check()
        before = self.expected
        self.final()
        self.started = True
        created = operation()
        receipt = self._owned()
        active_field = "active" if self.kind == "constraints" else "is_active"
        predicted_old = tuple((identity, previous_kind, tuple((field, False if field == active_field else value) for field, value in fields), custom)
                              for identity, previous_kind, fields, custom in before)
        if len(receipt) != len(before)+1 or receipt[:-1] != predicted_old or receipt[-1][0] != scope.key(created) or receipt[-1][1] != kind:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Native allocation did not produce one exact appended component.")
        self.expected = receipt
        self.allocated = created
        self.check()
        return created

    def removed_state(self, owner: Any) -> Any:
        current = self.expected
        index = next((index for index, item in enumerate(current) if item[0] == scope.key(owner)), None)
        if index is None:
            raise invalid_argument("Exact component is no longer owned by the target object.")
        expected = tuple(item for ordinal, item in enumerate(current) if ordinal != index)
        if self.kind == "modifiers" and dict(current[index][2]).get("is_active") is True and expected:
            active_index = min(index, len(expected)-1)
            expected = tuple((identity, kind, tuple((field, ordinal == active_index if field == "is_active" else value) for field, value in fields), custom)
                             for ordinal, (identity, kind, fields, custom) in enumerate(expected))
        return expected

    def remove(self, owner: Any) -> None:
        self.check()
        expected = self.removed_state(owner)
        self.final()
        self.started = True
        getattr(self.obj, self.kind).remove(owner)
        if self._owned() != expected:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Native removal changed data beyond the exact owned component.")
        self.expected = expected
        self.check()

    def restore_activation(self) -> None:
        """Restore only the original UI active flag after a private allocation."""
        if self.kind not in {"constraints", "modifiers"}:
            return
        field = "active" if self.kind == "constraints" else "is_active"
        for identity, _kind, fields, _custom_values in self.original:
            if dict(fields).get(field) is True:
                current = next((item for item in getattr(self.obj, self.kind) if scope.key(item) == identity), None)
                if current is None:
                    raise invalid_argument("Original active component identity is unavailable for recovery.")
                self.write(current, field, True)

    def native_apply(self, operation: Any, *, removed: Any = None, applied_channels: frozenset[str] = frozenset()) -> Any:
        """One native blocking call, measured receipts, no invented mesh rollback."""
        if self.obj.type != "MESH":
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native application currently requires the bounded Mesh comparison path.")
        self.check()
        protected_before, owned_before = self.protected, self.expected
        expected = self.removed_state(removed) if removed is not None else None
        self.final()
        self.started = True
        try:
            result = operation()
            receipt, owned = self._protected(), self._owned()
            if "FINISHED" not in result:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Native object application did not finish.")
            # Application may change Mesh contents, never its identity, bindings,
            # group metadata or another object's persistent state.
            target_index = next(index for index, item in enumerate(self.objects) if item == self.obj)
            predicted = list(protected_before)
            target = list(predicted[target_index])
            old_data, new_data = target[11], receipt[target_index][11]
            expected_metadata = _native_mesh_metadata(old_data[0], self.obj.data)
            if not _predicted_delta(old_data[0], expected_metadata, new_data[0]):
                raise invalid_argument("Native application changed protected Mesh metadata, ownership or bindings.")
            target[11] = (new_data[0], new_data[1])
            predicted[target_index] = tuple(target)
            if tuple(predicted) != receipt:
                raise invalid_argument("Native application changed protected object metadata or dependencies.")
            if removed is not None and owned != expected:
                raise invalid_argument("Native apply did not remove exactly the named component.")
            if self.transform:
                old = dict(owned_before)
                wanted = {"location": (0., 0., 0.), "rotation_euler": (0., 0., 0.),
                          "rotation_quaternion": (1., 0., 0., 0.), "rotation_axis_angle": (0., 0., 1., 0.), "scale": (1., 1., 1.)}
                for field, current in owned:
                    if field in applied_channels:
                        if not _close(current, wanted[field]):
                            raise invalid_argument("Applied transform channel was not reset to its expected identity.", property=field)
                    elif current != old[field]:
                        raise invalid_argument("Native application changed an unrequested transform channel.", property=field)
            self.protected, self.expected = receipt, owned
            # Captured native receipt precedes every provider callback. Manual
            # edits during the fresh gate cannot be adopted as native output.
            self.check()
            return result
        except Exception as error:
            raise self.failure(error) from error

    def failure(self, error: Exception, *, restored: bool = False) -> BridgeError:
        return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                           "Object edit could not be completed; inspect the measured state and finalized checkpoint.",
                           {"execution_started": self.started, "possible_mutation": self.started and not restored,
                            "rollback_verified": restored, "verification_required": True,
                            "affected_objects": self.affected, "exception_type": type(error).__name__,
                            "native_blocking_seconds": self.native_seconds})

    @property
    def affected(self) -> list[str]:
        return [item.name for item in self.objects]
