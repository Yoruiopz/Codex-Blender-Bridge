"""Prove actual per-layer/global UV selection scope and native restoration."""

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
from blender_codex_bridge.tools._uv_selection import scoped_uv_selection


def main():
    assert bpy.app.background and not bpy.data.filepath
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        runtime.executor.permissions = PermissionManager(lambda: {p.value: True for p in Permission})
        for toolset in ("uv", "interaction", "mesh"):
            runtime.registry.enable_toolset(toolset)
        obj = bpy.data.objects["Cube"]
        obj.data.uv_layers.new(name="ProtectedUV")
        obj.data.uv_layers.active_index = 0
        geometry = [tuple(v.co) for v in obj.data.vertices]
        runtime.dispatch("context.set_mode", {"object_name": obj.name, "mode": "EDIT"})
        runtime.dispatch("mesh.select_components", {"object_name": obj.name, "element_type": "FACE", "indices": [0]})
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        layer = bm.loops.layers.uv.active
        modern = hasattr(bm, "uv_select_sync_valid")
        for uv in bm.loops.layers.uv.values():
            for index, loop in enumerate(loop for face in bm.faces for loop in face.loops):
                if modern:
                    loop.uv_select_vert = index % 3 == 1
                    loop.uv_select_edge = index % 5 == 1
                else:
                    loop[uv].select = index % 3 == 1
                    loop[uv].select_edge = index % 5 == 1
        if modern:
            for face in bm.faces:
                face.uv_select = face.index % 2 == 0
            bm.uv_select_sync_valid = False
        def snapshot():
            flags = [(uv.name, [(getattr(loop, "uv_select_vert", None), getattr(loop, "uv_select_edge", None),
                                getattr(loop[uv], "select", None), getattr(loop[uv], "select_edge", None))
                               for face in bm.faces for loop in face.loops]) for uv in bm.loops.layers.uv.values()]
            return {"flags": flags, "selection": [[item.select for item in seq] for seq in (bm.verts, bm.edges, bm.faces)],
                    "face_uv": [getattr(face, "uv_select", None) for face in bm.faces],
                    "sync_valid": getattr(bm, "uv_select_sync_valid", None),
                    "protected_uv": [tuple(loop[bm.loops.layers.uv.get("ProtectedUV")].uv) for face in bm.faces for loop in face.loops]}
        before = snapshot()
        inspected = runtime.dispatch("uv.inspect", {"object_name": obj.name, "include_coordinates": True})
        analysis = inspected["analysis"]
        assert analysis["uv_selection_storage"] == ("MESH_GLOBAL" if modern else "PER_LAYER")
        if modern:
            assert analysis["uv_selection_valid"] is False
            assert analysis["selected_uv_loop_count"] is None
            assert all(item["selected"] is None for item in inspected["coordinates"]["items"])
        with scoped_uv_selection(bm, layer, [bm.faces[1]]):
            for face in bm.faces:
                for loop in face.loops:
                    if hasattr(loop[layer], "select"):
                        assert bool(loop[layer].select) == (face.index == 1)
                        assert bool(loop[layer].select_edge) == (face.index == 1)
                    else:
                        assert loop.uv_select_vert == (face.index == 1)
                        assert loop.uv_select_edge == (face.index == 1)
                        assert face.uv_select == (face.index == 1)
                        assert bm.uv_select_sync_valid
        assert snapshot() == before
        try:
            with scoped_uv_selection(bm, layer, [bm.faces[2]]):
                raise RuntimeError("owned injected operator failure")
        except RuntimeError as error:
            assert str(error) == "owned injected operator failure"
        assert snapshot() == before
        runtime.dispatch("uv.unwrap", {"object_name": obj.name, "method": "ANGLE_BASED"})
        assert snapshot() == before
        # Independently prove that the native pack operator consumes these
        # fields, rather than merely preserving synthetic custom attributes.
        # All mesh faces are selected, but exactly one UV island is selected.
        for face in bm.faces:
            face.select_set(True)
            if modern:
                face.uv_select = face.index == 0
            for corner, loop in enumerate(face.loops):
                loop[layer].uv = (2.+face.index*2.+(corner in (1, 2))*.5,
                                  2.+(corner in (2, 3))*.5)
                if modern:
                    loop.uv_select_vert = loop.uv_select_edge = face.index == 0
                else:
                    loop[layer].select = loop[layer].select_edge = face.index == 0
        if modern:
            bm.uv_select_sync_valid = True
        settings = bpy.context.scene.tool_settings
        settings.use_uv_select_sync = False
        settings.uv_select_mode = "VERTEX"
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        coordinates = [[tuple(loop[layer].uv) for loop in face.loops] for face in bm.faces]
        assert "FINISHED" in bpy.ops.uv.pack_islands(rotate=False, margin=.01)
        packed = [[tuple(loop[layer].uv) for loop in face.loops] for face in bm.faces]
        assert packed[0] != coordinates[0]
        assert packed[1:] == coordinates[1:], "Native UV scope changed an unselected island"
        assert [tuple(loop[bm.loops.layers.uv.get("ProtectedUV")].uv) for face in bm.faces for loop in face.loops] == before["protected_uv"]
        runtime.dispatch("context.set_mode", {"object_name": obj.name, "mode": "OBJECT"})
        assert geometry == [tuple(v.co) for v in obj.data.vertices]
        print("BLENDER_UV_SELECTION_STORAGE_OK "+json.dumps({"blender_version": bpy.app.version_string,
            "both_uv_maps_actual_native_flags_preserved": True, "selection_storage": "MESH_GLOBAL" if modern else "PER_LAYER", "operator_and_fault_restored": True,
            "native_sync_state_preserved": True, "native_pack_consumes_uv_scope": True,
            "unselected_islands_preserved": True, "project_saved": False}))
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
