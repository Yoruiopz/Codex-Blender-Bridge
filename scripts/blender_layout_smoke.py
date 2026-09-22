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
        print("BLENDER_CODEX_LAYOUT_SMOKE_OK " + json.dumps({"blender_version": bpy.app.version_string, "centrally_wired": centrally_wired, "tools": 4, "objects": created, "selection_preserved": True, "saved": False}, sort_keys=True))
    finally:
        for name in reversed(created):
            obj = bpy.data.objects.get(name)
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
