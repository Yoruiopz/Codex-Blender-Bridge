"""Isolated seam authoring/inspection integration; never saves a blend file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))

import blender_codex_bridge
from blender_codex_bridge.errors import BridgeError
from blender_codex_bridge.permissions import Permission, PermissionManager
from blender_codex_bridge.runtime import get_runtime


def main() -> None:
    assert bpy.app.background and not bpy.data.filepath, "Use --background --factory-startup"
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        permissions = {permission.value: True for permission in Permission}
        runtime.executor.permissions = PermissionManager(lambda: permissions)
        for toolset in ("mesh", "interaction", "batch", "uv"):
            runtime.registry.enable_toolset(toolset)
        dispatch = runtime.dispatch
        cube = bpy.data.objects["Cube"]
        material = bpy.data.materials.new("SeamPreservationMaterial")
        cube.data.materials.append(material)
        before_materials = list(cube.data.materials)
        before_positions = [tuple(vertex.co) for vertex in cube.data.vertices]
        before_uvs = [tuple(loop.uv) for loop in cube.data.uv_layers.active.data]
        def coordinates():
            items = []
            offset = 0
            while True:
                result = dispatch("uv.inspect", {"object_name": "Cube", "include_coordinates": True,
                                                "coordinate_offset": offset, "max_coordinates": 7})
                page = result["coordinates"]
                assert not page["analysis_truncated"]
                items.extend(page["items"])
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            assert len(items) == len(before_uvs)
            assert [tuple(item["uv"]) for item in items] == before_uvs
            return items

        object_coordinates = coordinates()
        before_counts = (len(cube.data.vertices), len(cube.data.edges), len(cube.data.polygons))
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "EDIT"})
        selected = dispatch("mesh.select_components", {"object_name": "Cube", "element_type": "EDGE", "indices": [0, 1]})
        selection_id = selected["selection"]["mesh_selection"]["selection_id"]
        bm = bmesh.from_edit_mesh(cube.data)
        edit_coordinates = coordinates()
        assert [(item["face_index"], item["corner_index"], item["vertex_index"])
                for item in object_coordinates] == [
                    (item["face_index"], item["corner_index"], item["vertex_index"])
                    for item in edit_coordinates]
        before_selection = [[item.select for item in sequence] for sequence in (bm.verts, bm.edges, bm.faces)]

        def rejected(params, code):
            try:
                dispatch("mesh.mark_seams", params)
                raise AssertionError("Expected seam rejection")
            except BridgeError as error:
                assert error.code == code, error.code

        permissions["EDIT_MESH"] = False
        rejected({"object_name": "Cube"}, "PERMISSION_DENIED")
        assert not any(edge.seam for edge in bm.edges)
        permissions["EDIT_MESH"] = True
        rejected({"object_name": "Cube", "selection_id": "expired"}, "INVALID_SELECTION")
        result = dispatch("batch.execute", {"steps": [{"method": "mesh.mark_seams", "params": {
            "object_name": "Cube", "selection_id": selection_id,
        }}]})
        assert result["completed_steps"] == 1
        assert result["results"][0]["result"]["changed_edges"] == 2
        page = dispatch("mesh.components_inspect", {"object_name": "Cube", "element_type": "EDGE"})
        assert [edge["index"] for edge in page["items"] if edge["seam"]] == [0, 1]
        assert [edge.index for edge in bm.edges if edge.seam] == [0, 1]
        assert before_selection == [[item.select for item in sequence] for sequence in (bm.verts, bm.edges, bm.faces)]
        assert not dispatch("mesh.mark_seams", {"object_name": "Cube"})["changed"]
        cleared = dispatch("mesh.mark_seams", {"object_name": "Cube", "seam": False})
        assert cleared["changed_edges"] == 2 and not any(edge.seam for edge in bm.edges)
        bm.edges[0].hide = True
        rejected({"object_name": "Cube"}, "INVALID_SELECTION")
        bm.edges[0].hide = False
        scoped = dispatch("mesh.select_components", {"object_name": "Cube", "element_type": "FACE", "indices": [1]})
        scoped_id = scoped["selection"]["mesh_selection"]["selection_id"]
        uv_scope = dispatch("uv.inspect", {"object_name": "Cube", "selection_id": scoped_id,
                                           "include_coordinates": True})["coordinates"]
        assert uv_scope["scoped_loop_count"] == 4
        assert all(item["face_index"] == 1 for item in uv_scope["items"])
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "OBJECT"})
        assert before_positions == [tuple(vertex.co) for vertex in cube.data.vertices]
        assert before_uvs == [tuple(loop.uv) for loop in cube.data.uv_layers.active.data]
        coordinates()
        assert before_counts == (len(cube.data.vertices), len(cube.data.edges), len(cube.data.polygons))
        assert list(cube.data.materials) == before_materials
        rejected({"object_name": "Cube"}, "INVALID_MODE")
        sibling = bpy.data.objects.new("SharedSeamTarget", cube.data)
        bpy.context.scene.collection.objects.link(sibling)
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "EDIT"})
        rejected({"object_name": "Cube"}, "NOT_IMPLEMENTED")
        assert not any(edge.seam for edge in bmesh.from_edit_mesh(cube.data).edges)
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "OBJECT"})
        assert not any(edge.use_seam for edge in sibling.data.edges)
        print("BLENDER_CODEX_SEAMS_SMOKE_OK " + json.dumps({
            "version": bpy.app.version_string, "batch_verified": True,
            "topology_uvs_materials_selection_preserved": True,
            "shared_mesh_rejected": True, "saved": False,
            "uv_coordinate_pages_verified": True,
        }))
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
