"""Prove UV diagnostics and seam-to-unwrap results in a disposable Blender scene."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))

import blender_codex_bridge
from blender_codex_bridge.permissions import Permission, PermissionManager
from blender_codex_bridge.runtime import get_runtime


def main() -> None:
    assert bpy.app.background and not bpy.data.filepath
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        runtime.executor.permissions = PermissionManager(lambda: {p.value: True for p in Permission})
        for toolset in ("mesh", "interaction", "uv"):
            runtime.registry.enable_toolset(toolset)
        dispatch = runtime.dispatch
        cube = bpy.data.objects["Cube"]
        positions = [tuple(vertex.co) for vertex in cube.data.vertices]
        materials = list(cube.data.materials)
        for uv in cube.data.uv_layers.active.data:
            uv.uv = (0, 0)
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "EDIT"})
        dispatch("mesh.select_components", {"object_name": "Cube", "element_type": "FACE", "indices": list(range(6))})
        failed = dispatch("uv.unwrap", {"object_name": "Cube", "method": "ANGLE_BASED"})
        assert failed["verification"]["status"] == "needs_review"
        assert failed["post_state"]["quality"]["degenerate_face_count"] == 6
        assert failed["verification"]["user_goal_verified"] is False
        dispatch("mesh.select_components", {"object_name": "Cube", "element_type": "EDGE", "indices": list(range(12))})
        dispatch("mesh.mark_seams", {"object_name": "Cube"})
        dispatch("mesh.select_components", {"object_name": "Cube", "element_type": "FACE", "indices": list(range(6))})
        bm = bmesh.from_edit_mesh(cube.data)
        selection = [[element.select for element in seq] for seq in (bm.verts, bm.edges, bm.faces)]
        result = dispatch("uv.unwrap", {"object_name": "Cube", "method": "ANGLE_BASED"})
        assert result["verification"]["status"] == "basic_checks_passed"
        assert result["verification"]["user_goal_verified"] is False
        analysis = dispatch("uv.inspect", {"object_name": "Cube"})["analysis"]
        assert analysis["quality"]["degenerate_face_count"] == 0
        assert analysis["quality"]["invalid_face_count"] == 0
        assert analysis["quality"]["total_absolute_signed_area"] > 0.1
        assert analysis["island_count"] == 6
        assert selection == [[element.select for element in seq] for seq in (bm.verts, bm.edges, bm.faces)]
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "OBJECT"})
        assert positions == [tuple(vertex.co) for vertex in cube.data.vertices]
        assert materials == list(cube.data.materials)
        assert len(cube.data.polygons) == 6
        cube.data.uv_layers.active.data[0].uv.x = float("nan")
        invalid = dispatch("uv.inspect", {"object_name": "Cube", "include_coordinates": True})
        assert invalid["analysis"]["analysis_truncated"]
        assert invalid["analysis"]["quality"]["invalid_face_count"] == 1
        assert invalid["coordinates"]["items"][0]["uv"] is None
        json.dumps(invalid, allow_nan=False)
        print("BLENDER_CODEX_UV_WORKFLOW_SMOKE_OK " + json.dumps({
            "version": bpy.app.version_string, "collapsed_unwrap_flagged": True,
            "seamed_unwrap_measured": True, "islands": 6, "saved": False,
        }))
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
