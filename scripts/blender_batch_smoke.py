"""Real dispatcher batch integration; isolated factory startup, never saves a blend."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def main() -> None:
    assert bpy.app.background and not bpy.data.filepath, "Use --background --factory-startup"
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        runtime.executor.permissions = PermissionManager(lambda: {p.value: True for p in Permission})
        for toolset in ("batch", "objects", "layout", "geometry_nodes"):
            runtime.registry.enable_toolset(toolset)
        steps = [
            {"method": "object.create", "params": {"name": f"Batch{i}", "object_type": "CUBE", "location": [x, 0, 1]}}
            for i, x in enumerate((-3, 0, 3))
        ]
        steps += [
            {"method": "geometry_nodes.create", "params": {"group_name": "BatchGraph"}},
            {"method": "geometry_nodes.attach", "params": {"group_name": "BatchGraph", "object_name": "Batch1", "modifier_name": "Procedural"}},
            {"method": "scene.query", "params": {"name_pattern": "Batch*"}},
        ]
        plan = runtime.dispatch("batch.plan", {"steps": steps})
        assert plan["ready"] and not bpy.data.objects.get("Batch0")
        result = runtime.dispatch("batch.execute", {"steps": steps, "label": "Create three inspected props"})
        assert result["completed_steps"] == 6
        assert result["operation"]["operation_id"]
        assert result["operation"]["scope"] == "logical_batch"
        assert result["results"][-1]["result"]["matched_count"] == 3
        assert len(runtime.state.history(50)) == 8  # plan, six children, parent
        bpy.context.view_layer.update()
        for i, x in enumerate((-3, 0, 3)):
            obj = bpy.data.objects[f"Batch{i}"]
            assert tuple(obj.location) == (x, 0, 1)
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            try:
                assert len(mesh.vertices) == 8 and len(mesh.polygons) == 6
            finally:
                evaluated.to_mesh_clear()
        try:
            runtime.dispatch("batch.execute", {"steps": [
                {"method": "transform.set", "params": {"object_name": "Batch0", "location": [-3, 0, 2]}},
                {"method": "transform.set", "params": {"object_name": "Missing", "location": [0, 0, 0]}},
                {"method": "transform.set", "params": {"object_name": "Batch2", "location": [999, 0, 0]}},
            ]})
        except BridgeError as exc:
            assert exc.context["completed_steps"] == 1
            assert exc.context["verification_required"] and not exc.context["rollback_performed"]
        else:
            raise AssertionError("Partial failure accepted as success")
        assert tuple(bpy.data.objects["Batch0"].location) == (-3, 0, 2)
        assert tuple(bpy.data.objects["Batch2"].location) == (3, 0, 1)
        assert not runtime.state.history(1)[0]["success"]
        if "--render" in sys.argv:
            bpy.data.objects["Cube"].hide_render = True
            camera = bpy.data.objects["Camera"]
            camera.location = (9, -14, 10)
            camera.rotation_euler = (Vector((0, 0, 1)) - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.data.type = "ORTHO"
            camera.data.ortho_scale = 12
            scene = bpy.context.scene
            scene.camera = camera
            scene.render.engine = "BLENDER_WORKBENCH"
            scene.display.shading.color_type = "OBJECT"
            scene.display.shading.light = "STUDIO"
            for i, color in enumerate(((0.1, 0.5, 0.9, 1), (0.9, 0.3, 0.1, 1), (0.15, 0.8, 0.4, 1))):
                bpy.data.objects[f"Batch{i}"].color = color
            scene.render.resolution_x, scene.render.resolution_y = 640, 480
            scene.render.resolution_percentage = 100
            output = ROOT / "build" / "batch-smoke.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            scene.render.filepath = str(output)
            bpy.ops.render.render(write_still=True)
            assert output.is_file()
        assert not bpy.data.filepath
        print("BLENDER_CODEX_BATCH_SMOKE_OK " + json.dumps({"version": bpy.app.version_string, "steps": 6, "partial_failure_verified": True, "saved": False}))
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
