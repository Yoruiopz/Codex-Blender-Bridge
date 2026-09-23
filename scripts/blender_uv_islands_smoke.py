"""Verify measured UV connectivity in a factory-startup Blender process only."""

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
        mesh = bpy.data.meshes.new("UVContinuityMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0),
                          (0, 1, 0), (1, 1, 0), (2, 1, 0)], [],
                         [(0, 1, 4, 3), (1, 2, 5, 4)])
        obj = bpy.data.objects.new("UVContinuity", mesh)
        bpy.context.scene.collection.objects.link(obj)
        layer = mesh.uv_layers.new(name="UVMap")
        for loop in mesh.loops:
            layer.data[loop.index].uv = mesh.vertices[loop.vertex_index].co[:2]
        dispatch = runtime.dispatch

        def island_count():
            return dispatch("uv.inspect", {"object_name": obj.name})["analysis"]["island_count"]

        assert island_count() == 1
        original_uvs = [tuple(item.uv) for item in layer.data]
        original_positions = [tuple(vertex.co) for vertex in mesh.vertices]
        dispatch("context.set_mode", {"object_name": obj.name, "mode": "EDIT"})
        bm = bmesh.from_edit_mesh(mesh)
        bm.edges.ensure_lookup_table()
        shared = next(edge.index for edge in bm.edges if len(edge.link_faces) == 2)
        dispatch("mesh.select_components", {"object_name": obj.name, "element_type": "EDGE", "indices": [shared]})
        dispatch("mesh.mark_seams", {"object_name": obj.name})
        assert island_count() == 1
        dispatch("context.set_mode", {"object_name": obj.name, "mode": "OBJECT"})
        assert island_count() == 1
        assert original_uvs == [tuple(item.uv) for item in mesh.uv_layers.active.data]
        dispatch("context.set_mode", {"object_name": obj.name, "mode": "EDIT"})
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        for loop in bm.faces[1].loops:
            loop[uv_layer].uv.x += 3
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        assert island_count() == 2
        dispatch("mesh.mark_seams", {"object_name": obj.name, "seam": False})
        assert island_count() == 2
        dispatch("context.set_mode", {"object_name": obj.name, "mode": "OBJECT"})
        assert island_count() == 2
        assert original_positions == [tuple(vertex.co) for vertex in mesh.vertices]
        print("BLENDER_CODEX_UV_ISLANDS_SMOKE_OK " + json.dumps({
            "version": bpy.app.version_string, "edit_and_object_modes_verified": True,
            "seams_preserve_uv_connectivity": True, "uv_split_detected": True, "saved": False,
        }))
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
