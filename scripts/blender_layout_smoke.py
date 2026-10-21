"""Isolated background smoke for evaluated scene queries and bulk layout.

Run with Blender --background --factory-startup --python this_file.py.
No project is saved and the open interactive Blender instance is never used.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import layout  # noqa: E402
from blender_codex_bridge.tools import objects as object_tools  # noqa: E402


def lifecycle_checks(runtime, created, permission_flags):
    """Typed operations and test-only fault injection inside this disposable scene."""
    runtime.registry.enable_toolset("objects")
    permission_flags["TRANSFORM_OBJECTS"] = permission_flags["DELETE_OBJECTS"] = True
    child = runtime.dispatch("object.create", {"name": "Lifecycle Child", "object_type": "EMPTY", "location": [2, 3, 4], "rotation": [.3, .4, -.2], "scale": [.7, 1.1, .9]})["object"]
    created.append(child)
    parent = runtime.dispatch("object.create", {"name": "Lifecycle Parent", "object_type": "EMPTY", "location": [10, -2, 7], "rotation": [.2, -.4, .5], "scale": [1.3, 1.3, 1.3]})["object"]
    created.append(parent)
    target = bpy.data.objects[child]
    bpy.context.view_layer.update()
    world = target.matrix_world.copy()
    result = runtime.dispatch("object.set_parent", {"object_name": child, "parent_name": parent})
    assert result["verified"] and result["context_preserved"]
    assert target.parent == bpy.data.objects[parent] and object_tools._matrix_close(target.matrix_world, world)
    try:
        runtime.dispatch("object.delete", {"object_name": parent})
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    else:
        raise AssertionError("Parent deletion implicitly detached its child")
    runtime.dispatch("object.set_parent", {"object_name": child, "parent_name": None})
    assert target.parent is None and object_tools._matrix_close(target.matrix_world, world)
    target.rotation_euler.x += 2 * math.pi
    bpy.context.view_layer.update()
    raw_rotation = tuple(target.rotation_euler)
    before = (target.parent, target.matrix_parent_inverse.copy(), target.matrix_basis.copy(), target.matrix_world.copy())
    original_serialize = object_tools.serialize_transform
    def fail_after_parenting(obj):
        if obj == target:
            raise RuntimeError("Injected native post-parenting evidence failure")
        return original_serialize(obj)
    object_tools.serialize_transform = fail_after_parenting
    try:
        try:
            runtime.dispatch("object.set_parent", {"object_name": child, "parent_name": parent})
        except BridgeError as error:
            assert error.code == "OPERATION_FAILED" and error.context["rollback_verified"] is True
        else:
            raise AssertionError("Injected parenting failure was swallowed")
    finally:
        object_tools.serialize_transform = original_serialize
    assert target.parent == before[0]
    assert tuple(target.rotation_euler) == raw_rotation
    assert all(object_tools._matrix_close(actual, expected) for actual, expected in zip((target.matrix_parent_inverse, target.matrix_basis, target.matrix_world), before[1:], strict=True))
    collection = bpy.data.collections.new("Lifecycle Owned Collection")
    bpy.context.scene.collection.children.link(collection)
    try:
        moved = runtime.dispatch("object.move_to_collection", {"object_name": child, "collection_name": collection.name})
        assert moved["verified"] and tuple(target.users_collection) == (collection,)
        copied = runtime.dispatch("object.duplicate", {"object_name": child, "new_name": "Lifecycle Copy", "linked": False})
        created.append(copied["object"])
        assert copied["dependency_policy"] == "REFERENCED_DATABLOCKS_RETAINED"
        renamed = runtime.dispatch("object.rename", {"object_name": copied["object"], "new_name": "Lifecycle Renamed Copy"})
        created[-1] = renamed["object"]
        runtime.dispatch("object.delete", {"object_name": renamed["object"]})
        created.pop()
        instance = bpy.data.objects[parent]
        instance.instance_type, instance.instance_collection = "COLLECTION", collection
        try:
            runtime.dispatch("object.move_to_collection", {"object_name": child, "collection_name": bpy.context.scene.collection.name})
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED"
        else:
            raise AssertionError("Shared collection membership was edited")
        instance.instance_collection, instance.instance_type = None, "NONE"
        constraint = instance.constraints.new("COPY_LOCATION")
        constraint.target = target
        try:
            runtime.dispatch("object.transform_batch", {"edits": [{"object_name": child, "location": [99, 0, 0]}]})
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED"
        else:
            raise AssertionError("Layout silently moved an incoming constraint consumer")
        instance.constraints.remove(constraint)
        assert object_tools._matrix_close(target.matrix_world, world)
    finally:
        # Fixture teardown, not product cleanup or an implicit permission bypass.
        instance = bpy.data.objects[parent]
        instance.instance_collection, instance.instance_type = None, "NONE"
        for obj in tuple(collection.objects):
            bpy.context.scene.collection.objects.link(obj)
        bpy.data.collections.remove(collection)
    return {"parenting_recovery_verified": True, "collection_scope_verified": True, "incoming_dependency_rejected": True}


def main() -> None:
    assert bpy.app.background and not bpy.data.filepath, "Use an isolated factory-startup process."
    original_objects = {obj.name: tuple(obj.matrix_world) for obj in bpy.context.scene.objects}
    initial_selection = {obj.name for obj in bpy.context.selected_objects}
    initial_active = bpy.context.view_layer.objects.active.name
    created: list[str] = []
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        centrally_wired = "scene.query" in runtime.registry.list_tools()
        if not centrally_wired:
            layout.register_tools(runtime.registry)
        permission_flags = {"INSPECT_SCENE": True, "TRANSFORM_OBJECTS": True}
        permissions = PermissionManager(lambda: permission_flags)
        runtime.permissions = runtime.executor.permissions = permissions
        runtime.registry.enable_toolset("layout")
        for name, position in (("LayoutSmokeA", (0, 1, 2)), ("LayoutSmokeB", (2, 3, 4)), ("LayoutSmokeC", (10, 5, 6))):
            obj = bpy.data.objects.new(name, None)
            bpy.context.scene.collection.objects.link(obj)
            obj.location = position
            created.append(obj.name)
        bpy.context.view_layer.update()
        print("LAYOUT_SCOPE_PROBE " + json.dumps({obj.name: {"scene_uses": bpy.context.scene.user_of_id(obj), "root_collection_uses": bpy.context.scene.collection.user_of_id(obj), "users": [{"name": user.name, "type": type(user).__name__} for user in bpy.data.user_map(subset={obj}).get(obj, ())]} for obj in (bpy.data.objects[name] for name in created)}, sort_keys=True))
        query = runtime.dispatch("scene.query", {"name_pattern": "LayoutSmoke*", "object_types": ["EMPTY"], "origin_min": [0, 0, 0], "origin_max": [10, 10, 10], "limit": 2})
        assert query["matched_count"] == 3 and query["next_offset"] == 2
        assert query["objects"][1]["world_origin"] == [2, 3, 4]
        checkpoint = runtime.checkpoints.create("Isolated layout smoke operation")
        assert checkpoint["checkpoint_id"]

        distributed = runtime.dispatch("object.distribute", {"object_names": list(reversed(created)), "axis": "X"})
        assert distributed["order"] == created
        assert distributed["spacing"] == 5
        assert distributed["operation"]["operation_id"]
        assert tuple(bpy.data.objects[created[1]].location) == (5, 3, 4)
        assert tuple(bpy.data.objects[created[0]].location) == (0, 1, 2)
        assert tuple(bpy.data.objects[created[2]].location) == (10, 5, 6)

        aligned = runtime.dispatch("object.align", {"object_names": created, "axis": "Y", "target": "REFERENCE", "reference_object": created[0]})
        assert aligned["coordinate"] == 1
        assert all(obj["world_origin"][1] == 1 for obj in aligned["objects"])
        transformed = runtime.dispatch("object.transform_batch", {"edits": [{"object_name": created[0], "location": [3, 4, 5], "rotation": [0.1, 0.2, 0.3], "scale": [2, 3, 4]}, {"object_name": created[1], "location": [6, 7, 8]}]})
        assert transformed["verified"]
        assert tuple(bpy.data.objects[created[0]].location) == (3, 4, 5)
        assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(bpy.data.objects[created[0]].rotation_euler, (0.1, 0.2, 0.3), strict=True))
        assert tuple(bpy.data.objects[created[0]].scale) == (2, 3, 4)
        verify = runtime.dispatch("scene.query", {"name_pattern": "LayoutSmoke*"})
        assert verify["objects"][0]["world_origin"] == [3, 4, 5]
        assert verify["objects"][1]["world_origin"] == [6, 7, 8]
        before_invalid = tuple(bpy.data.objects[created[0]].location)
        try:
            runtime.dispatch("object.transform_batch", {"edits": [{"object_name": created[0], "location": [99, 0, 0]}, {"object_name": created[1], "rotation": [0, 0]}]})
        except BridgeError as error:
            assert error.code == "INVALID_ARGUMENT"
        else:
            raise AssertionError("Invalid later edit was accepted")
        assert tuple(bpy.data.objects[created[0]].location) == before_invalid
        lifecycle_evidence = lifecycle_checks(runtime, created, permission_flags)

        bpy.data.objects[created[1]].parent = bpy.data.objects[created[2]]
        try:
            runtime.dispatch("object.align", {"object_names": created})
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED"
        else:
            raise AssertionError("Parented layout was accepted")
        assert tuple(bpy.data.objects[created[0]].location) == before_invalid
        bpy.data.objects[created[1]].parent = None
        permission_flags["TRANSFORM_OBJECTS"] = False
        try:
            runtime.dispatch("object.transform_batch", {"edits": [{"object_name": created[0], "location": [99, 0, 0]}]})
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Permission denial was bypassed")
        assert tuple(bpy.data.objects[created[0]].location) == before_invalid
        assert {obj.name for obj in bpy.context.selected_objects} == initial_selection
        assert bpy.context.view_layer.objects.active.name == initial_active
        assert bpy.context.mode == "OBJECT"
        for name, matrix in original_objects.items():
            assert tuple(bpy.data.objects[name].matrix_world) == matrix
        assert not bpy.data.filepath
        print("BLENDER_CODEX_LAYOUT_SMOKE_OK " + json.dumps({"blender_version": bpy.app.version_string, "centrally_wired": centrally_wired, "tools": 4, "objects": created, "selection_preserved": True, "saved": False, **lifecycle_evidence}, sort_keys=True))
    finally:
        for name in reversed(created):
            obj = bpy.data.objects.get(name)
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
