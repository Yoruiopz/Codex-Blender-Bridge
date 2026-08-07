"""Headless smoke for the centrally wired extended bridge domains."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def main() -> None:
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        permission_manager = PermissionManager(
            lambda: {permission.value: True for permission in Permission}
        )
        runtime.permissions = permission_manager
        runtime.executor.permissions = permission_manager
        for toolset in (
            "objects",
            "mesh",
            "scene_edit",
            "render",
            "python",
        ):
            runtime.registry.enable_toolset(toolset)

        scene_name = bpy.context.scene.name
        arbitrary_mesh = runtime.dispatch(
            "mesh.create",
            {
                "object_name": "Bridge Smoke Tetrahedron",
                "mesh_name": "Bridge Smoke Tetrahedron Mesh",
                "vertices": [
                    [0.0, 0.0, 1.0],
                    [-1.0, -1.0, 0.0],
                    [1.0, -1.0, 0.0],
                    [0.0, 1.0, 0.0],
                ],
                "faces": [
                    [0, 1, 2],
                    [0, 2, 3],
                    [0, 3, 1],
                    [1, 3, 2],
                ],
                "location": [0.0, 0.0, -0.5],
                "rotation": [0.0, 0.0, 0.25],
                "scale": [0.5, 0.5, 0.5],
            },
        )
        assert arbitrary_mesh["object"] == "Bridge Smoke Tetrahedron"
        assert arbitrary_mesh["mesh_data_name"] == "Bridge Smoke Tetrahedron Mesh"
        assert arbitrary_mesh["mesh_counts"] == {
            "vertices": 4,
            "edges": 6,
            "faces": 4,
            "face_corners": 12,
        }
        camera = runtime.dispatch(
            "object.create",
            {
                "object_type": "CAMERA",
                "name": "Bridge Smoke Camera",
                "location": [0.0, -8.0, 0.0],
                "rotation": [math.pi / 2.0, 0.0, 0.0],
            },
        )
        light = runtime.dispatch(
            "object.create",
            {
                "object_type": "LIGHT",
                "name": "Bridge Smoke Light",
                "location": [3.0, -4.0, 5.0],
                "light_type": "AREA",
            },
        )
        runtime.dispatch(
            "scene.configure",
            {"scene_name": scene_name, "camera_object": camera["object"]},
        )
        camera_state = runtime.dispatch(
            "camera.configure",
            {
                "object_name": camera["object"],
                "lens": 45.0,
                "clip_start": 0.01,
                "clip_end": 500.0,
            },
        )
        light_state = runtime.dispatch(
            "light.configure",
            {
                "object_name": light["object"],
                "energy": 750.0,
                "color": [1.0, 0.8, 0.6],
            },
        )
        world = runtime.dispatch(
            "world.configure",
            {
                "scene_name": scene_name,
                "create": bpy.context.scene.world is None,
                "use_nodes": True,
                "color": [0.03, 0.04, 0.06],
                "strength": 0.2,
            },
        )
        collection = runtime.dispatch(
            "collection.create",
            {"scene_name": scene_name, "name": "Bridge Smoke Collection"},
        )
        runtime.dispatch(
            "collection.rename",
            {
                "collection_name": collection["collection"],
                "new_name": "Bridge Smoke Collection Renamed",
            },
        )
        runtime.dispatch(
            "collection.delete",
            {
                "collection_name": "Bridge Smoke Collection Renamed",
                "confirm_delete": True,
            },
        )
        render_settings = runtime.dispatch(
            "render.configure",
            {
                "scene_name": scene_name,
                "width": 64,
                "height": 64,
                "resolution_percentage": 100,
                "samples": 1,
            },
        )
        rendered = runtime.dispatch(
            "render.execute",
            {
                "scene_name": scene_name,
                "file_format": "PNG",
                "width": 64,
                "height": 64,
                "resolution_percentage": 100,
            },
        )
        assert Path(rendered["filepath"]).is_file()
        assert (rendered["width"], rendered["height"]) == (64, 64)

        python_result = runtime.dispatch(
            "python.execute",
            {
                "code": "import math\nresult = {'root': math.sqrt(81), 'scene': bpy.context.scene.name}",
                "expected_effect": "Read the active scene and compute a smoke-test value",
                "confirm_dangerous": True,
                "time_limit_seconds": 2.0,
            },
        )
        assert python_result["result"]["root"] == 9.0
        runtime.dispatch("bridge.task.set", {"description": "Extended smoke"})
        assert runtime.state.snapshot()["current_task"] == "Extended smoke"
        runtime.dispatch("bridge.task.clear")
        assert runtime.state.snapshot()["current_task"] == ""

        methods = runtime.registry.list_tools()
        required = {
            "animation.inspect",
            "camera.configure",
            "constraint.add",
            "material.create",
            "mesh.create",
            "modifier.add",
            "nodes.add",
            "python.execute",
            "render.execute",
            "rig.create",
            "uv.unwrap",
            "world.configure",
        }
        assert required <= set(methods)
        print(
            "BRIDGE_EXTENDED_SMOKE "
            + json.dumps(
                {
                    "blender": bpy.app.version_string,
                    "method_count": len(methods),
                    "arbitrary_mesh": arbitrary_mesh["mesh_counts"],
                    "camera": camera_state["camera"],
                    "light": light_state["light"],
                    "world": world["world"],
                    "render_engine": render_settings["engine"],
                    "render": rendered["filepath"],
                },
                sort_keys=True,
            )
        )
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
