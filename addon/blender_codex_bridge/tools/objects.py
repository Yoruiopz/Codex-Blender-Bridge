"""Deterministic object lifecycle, hierarchy, and collection tools."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import clear_selection_references
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import get_collection, get_object, require_blender, serialize_transform, vector3
from ._object_scope import (
    MutationGuard,
    datablock_identity,
    require_collection_scope,
    require_no_external_consumers,
    require_object_scope,
)

LOGGER = logging.getLogger(__name__)

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore


_MESH_TYPES = {"MESH", "CUBE", "PLANE", "UV_SPHERE", "ICOSPHERE", "CYLINDER", "CONE"}


def _populate_mesh_data(mesh: Any, object_type: str) -> None:
    if object_type == "MESH":
        return
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    bm = bmesh.new()
    try:
        if object_type == "CUBE":
            bmesh.ops.create_cube(bm, size=2.0)
        elif object_type == "PLANE":
            bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
        elif object_type == "UV_SPHERE":
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
        elif object_type == "ICOSPHERE":
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        elif object_type == "CYLINDER":
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=32, radius1=1.0, radius2=1.0, depth=2.0
            )
        elif object_type == "CONE":
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=32, radius1=1.0, radius2=0.0, depth=2.0
            )
        bm.to_mesh(mesh)
        mesh.update()
    finally:
        bm.free()


def _allocation_failure(exc: Exception, obj: Any, data: Any, operation: str) -> BridgeError:
    retained = []
    for kind, value in (("OBJECT", obj), ("DATA", data)):
        if value is not None:
            try:
                retained.append({"kind": kind, "name": value.name})
            except ReferenceError:
                retained.append({"kind": kind, "name": None, "identity_invalidated": True})
    labels = ", ".join(f"{item['kind']}:{item.get('name') or '<invalidated>'}" for item in retained) or "allocations not fully identified"
    affected = [item["name"] for item in retained if item["kind"] == "OBJECT" and isinstance(item.get("name"), str)]
    return BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED, f"{operation} failed; retained {labels}; inspect before explicit cleanup.", {"execution_started": True, "possible_mutation": True, "verification_required": True, "rollback_verified": False, "retained_allocations": retained, "affected_objects": affected, "allocation_outcome_unknown": True, "cleanup_policy": "RETAIN_FOR_EXPLICIT_PERMISSION_CHECKED_RECOVERY", "primary_error": exc.to_dict() if isinstance(exc, BridgeError) else {"exception_type": type(exc).__name__}})


def create_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    guard = MutationGuard(bpy, context, "object.create")
    raw_type = params.get("object_type", "EMPTY")
    if not isinstance(raw_type, str):
        raise invalid_argument("'object_type' must be a string.")
    object_type = raw_type.strip().upper().replace(" ", "_")
    supported = sorted({*_MESH_TYPES, "EMPTY", "CAMERA", "LIGHT"})
    if object_type not in supported:
        raise invalid_argument("Unsupported object type.", object_type=object_type, supported=supported)
    name = params.get("name", f"Codex {object_type.title()}")
    if not isinstance(name, str) or not name.strip():
        raise invalid_argument("'name' must be a non-empty string.")
    name = name.strip()[:63]
    collection_name = params.get("collection")
    if collection_name is not None and not isinstance(collection_name, str):
        raise invalid_argument("'collection' must be a string.")
    collection = get_collection(collection_name)
    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.INVALID_MODE, "Object creation requires Object Mode without changing the current mode.")
    require_collection_scope(bpy, collection, operation="Object creation")
    location = vector3(params.get("location"), "location", default=(0.0, 0.0, 0.0))
    rotation = vector3(params.get("rotation"), "rotation", default=(0.0, 0.0, 0.0))
    scale = vector3(params.get("scale"), "scale", default=(1.0, 1.0, 1.0))
    light_type = str(params.get("light_type", "POINT")).upper()
    if object_type == "LIGHT" and light_type not in {"POINT", "SUN", "SPOT", "AREA"}:
        raise invalid_argument("Unsupported light type.", supported=["POINT", "SUN", "SPOT", "AREA"])
    guard.check(collections=(collection,))
    data = obj = None
    try:
        if object_type in _MESH_TYPES:
            data = bpy.data.meshes.new(f"{name}Mesh")
            guard.remember(data, bpy.data.meshes)
            guard.check(collections=(collection,))
            _populate_mesh_data(data, object_type)
            guard.check(collections=(collection,))
            obj = bpy.data.objects.new(name, data)
        elif object_type == "CAMERA":
            data = bpy.data.cameras.new(f"{name}Camera")
            guard.remember(data, bpy.data.cameras)
            guard.check(collections=(collection,))
            obj = bpy.data.objects.new(name, data)
        elif object_type == "LIGHT":
            data = bpy.data.lights.new(f"{name}Light", light_type)
            guard.remember(data, bpy.data.lights)
            guard.check(collections=(collection,))
            obj = bpy.data.objects.new(name, data)
        else:
            obj = bpy.data.objects.new(name, None)
            guard.remember(obj, bpy.data.objects)
            guard.check(collections=(collection,))
            obj.empty_display_type = "PLAIN_AXES"
        guard.remember(obj, bpy.data.objects)
        guard.check(collections=(collection,))
        collection.objects.link(obj)
        guard.check(collections=(collection,))
        obj.location = location
        guard.check(collections=(collection,))
        obj.rotation_euler = rotation
        guard.check(collections=(collection,))
        obj.scale = scale
        bpy.context.view_layer.update()
        guard.check((obj,), (collection,))
        if any(any(not math.isclose(float(actual), float(wanted), rel_tol=1e-6, abs_tol=1e-5) for actual, wanted in zip(getattr(obj, field), value, strict=True)) for field, value in (("location", location), ("rotation_euler", rotation), ("scale", scale))):
            raise RuntimeError("Created object transform changed outside the operation.")
        transform = serialize_transform(obj)
    except Exception as exc:
        LOGGER.exception("Object creation failed; retaining exact allocations for explicit recovery")
        raise _allocation_failure(exc, obj, data, "Object creation") from exc
    return {
        "created": True,
        "object": obj.name,
        "type": obj.type,
        "source_primitive": object_type,
        "collections": [item.name for item in obj.users_collection],
        "transform": transform,
    }


def delete_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    guard = MutationGuard(bpy, context, "object.delete")
    obj = get_object(params.get("object_name"), allow_active=False)
    guard.remember(obj, bpy.data.objects)
    require_object_scope(bpy, obj, operation="Object deletion")
    if obj.children:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Deleting an object with children requires an explicit hierarchy workflow; children are not unparented implicitly.", {"object": obj.name})
    require_no_external_consumers(bpy, [obj], operation="Object deletion")
    name = obj.name
    data = obj.data
    data_name = data.name if data else None
    guard.check((obj,))
    clear_selection_references(name)
    try:
        guard.check((obj,))
        if obj.children:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Deletion scope changed before execution.")
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception as exc:
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED, "Object deletion failed; verify the exact target before retrying.", {"object": name, "execution_started": True, "possible_mutation": True, "verification_required": True}) from exc
    # Do not delete shared data; unused datablocks remain recoverable via undo.
    return {"deleted": True, "object": name, "data_name": data_name}


def duplicate_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    obj = get_object(params.get("object_name"), allow_active=False)
    bpy = require_blender()
    guard = MutationGuard(bpy, context, "object.duplicate")
    guard.remember(obj, bpy.data.objects)
    require_object_scope(bpy, obj, operation="Object duplication")
    linked = params.get("linked", False)
    if not isinstance(linked, bool):
        raise invalid_argument("'linked' must be a boolean.")
    new_name = params.get("new_name")
    if new_name is not None:
        if not isinstance(new_name, str) or not new_name.strip():
            raise invalid_argument("'new_name' must be a non-empty string.")
        new_name = new_name.strip()[:63]
        existing = require_blender().data.objects.get(new_name)
        if existing is not None:
            raise invalid_argument(f"An object named '{new_name}' already exists.")
    collections = list(obj.users_collection) or [get_collection()]
    guard.check((obj,), collections, dependencies=False)
    duplicate = copied_data = None
    try:
        duplicate = obj.copy()
        guard.remember(duplicate, bpy.data.objects)
        if obj.data is not None and not linked:
            guard.check((obj,), collections, dependencies=False)
            copied_data = obj.data.copy()
            guard.remember(copied_data)
            guard.check((obj,), collections, dependencies=False)
            duplicate.data = copied_data
        if new_name is not None:
            guard.check((obj,), collections, dependencies=False)
            duplicate.name = new_name
        for collection in collections:
            guard.check((obj,), collections, dependencies=False)
            collection.objects.link(duplicate)
        bpy.context.view_layer.update()
        guard.check((obj, duplicate), collections, dependencies=False)
        transform = serialize_transform(duplicate)
    except Exception as exc:
        LOGGER.exception("Object duplication failed; retaining exact allocations for explicit recovery")
        raise _allocation_failure(exc, duplicate, copied_data, "Object duplication") from exc
    return {
        "duplicated": True,
        "source_object": obj.name,
        "object": duplicate.name,
        "linked_data": linked,
        "dependency_policy": "REFERENCED_DATABLOCKS_RETAINED",
        "collections": [item.name for item in duplicate.users_collection],
        "transform": transform,
    }


def rename_object(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    guard = MutationGuard(bpy, context, "object.rename")
    obj = get_object(params.get("object_name"), allow_active=False)
    guard.remember(obj, bpy.data.objects)
    require_object_scope(bpy, obj, operation="Object rename")
    require_no_external_consumers(bpy, [obj], operation="Object rename")
    new_name = params.get("new_name")
    if not isinstance(new_name, str) or not new_name.strip():
        raise invalid_argument("'new_name' must be a non-empty string.")
    new_name = new_name.strip()[:63]
    collision = bpy.data.objects.get(new_name)
    if collision is not None and collision != obj:
        raise invalid_argument(f"An object named '{new_name}' already exists.")
    old_name = obj.name
    guard.check((obj,))
    clear_selection_references(old_name)
    guard.check((obj,))
    if obj.name != old_name or (bpy.data.objects.get(new_name) is not None and bpy.data.objects.get(new_name) != obj):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object naming scope changed before the rename; reinspect before retrying.")
    obj.name = new_name
    if obj.name != new_name:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Blender did not retain the requested name; inspect the retained object.", {"execution_started": True, "possible_mutation": True, "verification_required": True, "old_name": old_name, "object": obj.name})
    return {"renamed": True, "old_name": old_name, "object": obj.name}


def _matrix_close(actual: Any, expected: Any) -> bool:
    return all(math.isclose(float(left), float(right), rel_tol=1.0e-6, abs_tol=1.0e-5) for row, original in zip(actual, expected, strict=True) for left, right in zip(row, original, strict=True))


def _context_snapshot(bpy: Any) -> tuple[Any, tuple[Any, ...], str]:
    return bpy.context.view_layer.objects.active, tuple(bpy.context.selected_objects), bpy.context.mode


def _context_matches(bpy: Any, snapshot: tuple[Any, tuple[Any, ...], str]) -> bool:
    active, selected, mode = snapshot
    current = bpy.context.view_layer.objects.active
    return bpy.context.mode == mode and (None if active is None else datablock_identity(active)) == (None if current is None else datablock_identity(current)) and {datablock_identity(obj) for obj in selected} == {datablock_identity(obj) for obj in bpy.context.selected_objects}


def _parent_snapshot(obj: Any) -> dict[str, Any]:
    return {"parent": obj.parent, "parent_type": obj.parent_type, "matrix_parent_inverse": obj.matrix_parent_inverse.copy(), "matrix_basis": obj.matrix_basis.copy(), "channels": {field: tuple(getattr(obj, field)) for field in ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale") if hasattr(obj, field)}}


def _parent_matches(obj: Any, snapshot: dict[str, Any]) -> bool:
    return obj.parent == snapshot["parent"] and obj.parent_type == snapshot["parent_type"] and all(tuple(tuple(row) for row in getattr(obj, field)) == tuple(tuple(row) for row in snapshot[field]) for field in ("matrix_parent_inverse", "matrix_basis")) and all(tuple(getattr(obj, field)) == values for field, values in snapshot["channels"].items())


def _parenting_compatible(obj: Any) -> None:
    if obj.parent_type != "OBJECT" or obj.children or obj.constraints or obj.animation_data is not None or obj.rigid_body is not None or getattr(obj, "instance_collection", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Parenting supports independent object-parented targets without children, animation, constraints, rigid bodies, or collection instances.", {"object": obj.name})
    defaults = {"delta_location": (0, 0, 0), "delta_rotation_euler": (0, 0, 0), "delta_rotation_quaternion": (1, 0, 0, 0), "delta_scale": (1, 1, 1)}
    if any(tuple(getattr(obj, field, value)) != value for field, value in defaults.items()):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Parenting with non-default delta transforms is not supported with verified recovery.", {"object": obj.name})
    if any(any(getattr(obj, field, (False, False, False))) for field in ("lock_location", "lock_rotation", "lock_scale")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Parenting does not bypass locked transform channels.", {"object": obj.name})


def set_parent(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    guard = MutationGuard(bpy, context, "object.set_parent")
    obj = get_object(params.get("object_name"), allow_active=False)
    guard.remember(obj, bpy.data.objects)
    require_object_scope(bpy, obj, operation="Object parenting")
    parent_name = params.get("parent_name")
    if parent_name is not None and (
        not isinstance(parent_name, str) or not parent_name.strip()
    ):
        raise invalid_argument("'parent_name' must be a non-empty string or null.")
    parent = get_object(parent_name, allow_active=False) if parent_name is not None else None
    if parent is not None:
        require_object_scope(bpy, parent, operation="Object parenting")
        guard.remember(parent, bpy.data.objects)
    if parent == obj or (parent is not None and parent in obj.children_recursive):
        raise invalid_argument("Parenting would create an object hierarchy cycle.")
    keep_transform = params.get("keep_transform", True)
    if not isinstance(keep_transform, bool):
        raise invalid_argument("'keep_transform' must be a boolean.")
    _parenting_compatible(obj)
    require_no_external_consumers(bpy, [obj], operation="Object parenting")
    related = [obj, *([parent] if parent is not None else [])]
    if obj.parent is not None:
        require_object_scope(bpy, obj.parent, operation="Object parenting")
        related.append(obj.parent)
        guard.remember(obj.parent, bpy.data.objects)
    original = _parent_snapshot(obj)
    bpy.context.view_layer.update()
    guard.check(related, dependencies=False)
    require_no_external_consumers(bpy, [obj], operation="Object parenting")
    _parenting_compatible(obj)
    if not _parent_matches(obj, original):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Parenting target changed during preflight; reinspect before retrying.")
    world_matrix = obj.matrix_world.copy()
    new_inverse = original["matrix_parent_inverse"].copy()
    new_inverse.identity()
    if parent is not None and keep_transform:
        try:
            new_inverse = parent.matrix_world.inverted()
        except (ValueError, ZeroDivisionError) as exc:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "A singular parent transform cannot preserve a verified world transform.", {"parent": parent.name}) from exc
    saved_context = _context_snapshot(bpy)
    owned = original
    attempted = False
    try:
        for field, value in (("parent", parent), ("parent_type", "OBJECT"), ("matrix_parent_inverse", new_inverse), ("matrix_world" if keep_transform else "matrix_basis", world_matrix if keep_transform else original["matrix_basis"])):
            guard.check(related, dependencies=False)
            require_no_external_consumers(bpy, [obj], operation="Object parenting")
            _parenting_compatible(obj)
            if not _parent_matches(obj, owned):
                raise RuntimeError("Parenting state changed outside the operation before a write.")
            attempted = True
            setattr(obj, field, value)
            owned = _parent_snapshot(obj)
        bpy.context.view_layer.update()
        guard.check(related, dependencies=False)
        require_no_external_consumers(bpy, [obj], operation="Object parenting")
        if not _parent_matches(obj, owned) or obj.parent != parent or not _matrix_close(obj.matrix_parent_inverse, new_inverse) or not _matrix_close(obj.matrix_world if keep_transform else obj.matrix_basis, world_matrix if keep_transform else original["matrix_basis"]) or not _context_matches(bpy, saved_context):
            raise RuntimeError("Blender did not retain the requested parent, transform, or context.")
        transform = serialize_transform(obj)
    except Exception as exc:
        LOGGER.exception("Object parenting failed; restoring hierarchy and transform snapshots")
        restored = not attempted
        try:
            if attempted:
                guard.check(related, dependencies=False)
                require_no_external_consumers(bpy, [obj], operation="Parenting recovery")
                if not _parent_matches(obj, owned):
                    raise RuntimeError("A newer hierarchy/transform state replaced the operation output; retaining it.")
                for field in ("parent", "parent_type", "matrix_parent_inverse", "matrix_basis"):
                    guard.check(related, dependencies=False)
                    _parenting_compatible(obj)
                    require_no_external_consumers(bpy, [obj], operation="Parenting recovery")
                    if not _parent_matches(obj, owned):
                        raise RuntimeError("Parenting output changed before a compensation write.")
                    setattr(obj, field, original[field])
                    owned = _parent_snapshot(obj)
                for field, value in original["channels"].items():
                    guard.check(related, dependencies=False)
                    _parenting_compatible(obj)
                    require_no_external_consumers(bpy, [obj], operation="Parenting recovery")
                    if not _parent_matches(obj, owned):
                        raise RuntimeError("Parenting output changed before a compensation write.")
                    setattr(obj, field, value)
                    owned = _parent_snapshot(obj)
                bpy.context.view_layer.update()
            restored = _parent_matches(obj, original) and _matrix_close(obj.matrix_world, world_matrix) and _context_matches(bpy, saved_context)
        except Exception:
            LOGGER.exception("Failed to verify parenting restoration")
            restored = False
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED, "Parenting failed; inspect the verified recovery state before retrying.", {"object": obj.name, "affected_objects": [obj.name], "execution_started": attempted, "rollback_verified": restored, "possible_mutation": attempted and not restored, "verification_required": True, "external_state_retained": not restored}) from exc
    return {
        "object": obj.name,
        "parent": parent.name if parent else None,
        "kept_world_transform": keep_transform,
        "transform": transform,
        "affected_objects": [obj.name],
        "verified": True,
        "context_preserved": True,
    }


def move_to_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    guard = MutationGuard(bpy, context, "object.move_to_collection")
    obj = get_object(params.get("object_name"), allow_active=False)
    guard.remember(obj, bpy.data.objects)
    require_object_scope(bpy, obj, operation="Collection membership editing")
    collection_name = params.get("collection_name")
    if not isinstance(collection_name, str) or not collection_name.strip():
        raise invalid_argument("'collection_name' must be a non-empty string.")
    target = get_collection(collection_name)
    require_collection_scope(bpy, target, operation="Collection membership editing")
    link_only = params.get("link_only", False)
    if not isinstance(link_only, bool):
        raise invalid_argument("'link_only' must be a boolean.")
    require_no_external_consumers(bpy, [obj], operation="Collection membership editing")
    before = tuple(obj.users_collection)
    for collection in (*before, target):
        guard.remember(collection)
    expected = (*before, target) if link_only and target not in before else before if link_only else (target,)
    saved_context = _context_snapshot(bpy)
    world_matrix = obj.matrix_world.copy()
    attempted_links = False
    attempted_unlinks = []
    expected_current = {datablock_identity(item) for item in before}
    try:
        if target not in obj.users_collection:
            guard.check((obj,), (*before, target))
            attempted_links = True
            target.objects.link(obj)
            expected_current.add(datablock_identity(target))
        if not link_only:
            for collection in before:
                if collection != target:
                    guard.check((obj,), (*before, target))
                    if {datablock_identity(item) for item in obj.users_collection} != expected_current:
                        raise RuntimeError("Collection scope changed outside the operation before unlinking.")
                    attempted_unlinks.append(collection)
                    collection.objects.unlink(obj)
                    expected_current.discard(datablock_identity(collection))
        bpy.context.view_layer.update()
        guard.check((obj,), (*before, target))
        if {datablock_identity(item) for item in obj.users_collection} != {datablock_identity(item) for item in expected} or not _matrix_close(obj.matrix_world, world_matrix) or not _context_matches(bpy, saved_context):
            raise RuntimeError("Collection membership, world transform, or context did not match the request.")
    except Exception as exc:
        LOGGER.exception("Collection membership edit failed; restoring owned memberships")
        restored = True
        for collection in attempted_unlinks:
            try:
                if collection not in obj.users_collection:
                    guard.check((obj,), (*before, target))
                    collection.objects.link(obj)
            except Exception:
                LOGGER.exception("Failed to restore collection link")
                restored = False
        if attempted_links and target not in before and target in obj.users_collection:
            try:
                guard.check((obj,), (*before, target))
                target.objects.unlink(obj)
            except Exception:
                LOGGER.exception("Failed to remove the operation's target collection link")
                restored = False
        try:
            bpy.context.view_layer.update()
            restored = restored and {datablock_identity(item) for item in obj.users_collection} == {datablock_identity(item) for item in before} and _matrix_close(obj.matrix_world, world_matrix)
            restored = _context_matches(bpy, saved_context) and restored
        except Exception:
            LOGGER.exception("Failed to verify collection membership restoration")
            restored = False
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED, "Collection membership edit failed; inspect recovery before retrying.", {"object": obj.name, "affected_objects": [obj.name], "execution_started": attempted_links or bool(attempted_unlinks), "rollback_verified": restored, "possible_mutation": not restored, "verification_required": True, "external_state_retained": not restored}) from exc
    return {
        "object": obj.name,
        "collections": [item.name for item in obj.users_collection],
        "linked_only": link_only,
        "affected_objects": [obj.name],
        "verified": True,
        "context_preserved": True,
    }


def register_tools(registry: ToolRegistry) -> None:
    common = {
        "permissions": (Permission.TRANSFORM_OBJECTS,),
        "toolset": "objects",
        "modifies": True,
    }
    registry.register("object.create", create_object, description="Create a supported Blender object or mesh primitive.", **common)
    registry.register(
        "object.delete",
        delete_object,
        permissions=(Permission.DELETE_OBJECTS,),
        toolset="objects",
        modifies=True,
        description="Delete one named object after Blender-side permission approval.",
    )
    registry.register("object.duplicate", duplicate_object, description="Duplicate one object, linked or with copied data.", **common)
    registry.register("object.rename", rename_object, description="Rename one object without name collisions.", **common)
    registry.register("object.set_parent", set_parent, description="Set or clear an object's parent while optionally preserving its world transform.", **common)
    registry.register("object.move_to_collection", move_to_collection, description="Link or move an object to an existing collection.", **common)
