"""Repair an isolated prop through typed tools, verify attributes, capture and recover."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def run():
    try:
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {permission.value: True for permission in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        for toolset in ("interaction", "mesh"):
            runtime.registry.enable_toolset(toolset)
        cube = bpy.data.objects["Cube"]
        cube.name = "Repair Prop"
        mesh = bpy.data.meshes.new("Repair Fixture")
        mesh.from_pydata([
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
            (-.99999, -1, -1), (-1, -1, -1),
        ], [(0, 8)], [(3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
        cube.data = mesh
        for name in ("Fixture Side", "Fixture Cap"):
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            mesh.materials.append(material)
        fixture = bmesh.new()
        fixture.from_mesh(mesh)
        uv = fixture.loops.layers.uv.new("Existing UV")
        for face in fixture.faces:
            for loop in face.loops:
                co = loop.vert.co
                loop[uv].uv = (co.x * .25 + .5, co.y * .25 + .5)
                loop[uv].pin_uv = True
        fixture.to_mesh(mesh)
        fixture.free()
        cube.vertex_groups.new(name="Keep Weight").add(list(range(10)), .25, "REPLACE")
        protected = cube.copy()
        protected.data = mesh.copy()
        protected.name = "Protected Prop"
        protected.location.x = 4
        bpy.context.scene.collection.objects.link(protected)
        protected.select_set(True)
        names = [cube.name, protected.name]
        selected = sorted(obj.name for obj in bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active.name
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                region = area.spaces.active.region_3d
                region.view_location = (0, 0, 0)
                region.view_rotation = Vector((5, -6, 4)).to_track_quat("Z", "Y")
                region.view_distance = 7
        baseline = runtime.dispatch("scene.snapshot", {"object_names": names})
        guard = runtime.dispatch("scene.snapshot", {"object_names": [protected.name]})

        def capture(shading):
            selection_before = sorted(obj.name for obj in bpy.context.selected_objects)
            active_before = bpy.context.view_layer.objects.active
            visibility_before = [(obj.name, obj.hide_get(), obj.hide_render) for obj in bpy.context.scene.objects]
            path = runtime.dispatch("viewport.capture", {
                "view": "current", "shading": shading, "object_name": "Repair Prop",
                "resolution": [640, 480], "include_overlays": False,
            })["path"]
            assert selection_before == sorted(obj.name for obj in bpy.context.selected_objects)
            assert active_before == bpy.context.view_layer.objects.active
            assert visibility_before == [(obj.name, obj.hide_get(), obj.hide_render) for obj in bpy.context.scene.objects]
            return path

        before_image = capture("wireframe")
        runtime.dispatch("checkpoint.create", {"description": "Prop repair workflow"})
        runtime.dispatch("context.set_mode", {"object_name": cube.name, "mode": "EDIT"})

        def page(kind):
            result = runtime.dispatch("mesh.components_inspect", {
                "object_name": "Repair Prop", "element_type": kind, "max_items": 256,
            })
            assert not result["truncated"]
            return result

        def select(kind, indices):
            result = runtime.dispatch("mesh.select_components", {
                "object_name": "Repair Prop", "element_type": kind, "indices": indices,
            })
            return result["selection"]["mesh_selection"]["selection_id"]

        def denied(method, params, code):
            try:
                runtime.dispatch(method, {"object_name": "Repair Prop", **params})
            except BridgeError as error:
                assert error.code == code, (method, error.code, code)
            else:
                raise AssertionError(f"{method} accepted a forbidden operation")

        for method in ("mesh.subdivide_selected", "mesh.merge_by_distance", "mesh.fill_holes"):
            grants[Permission.EDIT_MESH.value] = False
            denied(method, {}, "PERMISSION_DENIED")
            grants[Permission.EDIT_MESH.value] = True
        # EDIT_MESH governs topology. No object deletion, arbitrary Python, save or external-file grant is needed.
        for permission in (Permission.EXECUTE_PYTHON, Permission.DELETE_OBJECTS,
                           Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT):
            grants[permission.value] = False
        merge_selection = select("VERT", [0, 8])
        merged = runtime.dispatch("mesh.merge_by_distance", {
            "object_name": "Repair Prop", "selection_id": merge_selection, "distance": .001,
        })
        assert merged["merged_vertices"] == 1 and merged["mesh_counts_after"]["vertices"] == 9
        denied("mesh.merge_by_distance", {"selection_id": merge_selection}, "INVALID_SELECTION")
        # The unselected coincident vertex remains: only the selected pair was welded.
        vertices = page("VERT")["items"]
        assert sum((Vector(item["center_local"]) - Vector((-1, -1, -1))).length < 1e-6
                   for item in vertices) == 2
        edges = page("EDGE")["items"]
        top_edges = [item["index"] for item in edges if abs(item["center_local"][2] - 1) < 1e-6]
        assert len(top_edges) == 4
        select("EDGE", top_edges[:3])
        denied("mesh.fill_holes", {}, "INVALID_SELECTION")
        cap_selection = select("EDGE", top_edges)
        filled = runtime.dispatch("mesh.fill_holes", {
            "object_name": "Repair Prop", "selection_id": cap_selection, "material_index": 1,
        })
        assert filled["created_faces"] == filled["boundary_loops"] == 1
        assert filled["mesh_counts_after"]["faces"] == 6
        # Filling must leave every pre-existing corner UV and material assignment intact.
        edit = bmesh.from_edit_mesh(bpy.data.objects["Repair Prop"].data)
        layer = edit.loops.layers.uv["Existing UV"]
        for face in edit.faces:
            if face.material_index == 0:
                for loop in face.loops:
                    expected = Vector((loop.vert.co.x * .25 + .5, loop.vert.co.y * .25 + .5))
                    assert (loop[layer].uv - expected).length < 1e-5
                    assert loop[layer].pin_uv
            else:
                assert all(loop[layer].uv.length < 1e-6 and not loop[layer].pin_uv for loop in face.loops)
        edges = page("EDGE")["items"]
        top_edges = [item["index"] for item in edges if abs(item["center_local"][2] - 1) < 1e-6]
        split_selection = select("EDGE", top_edges)
        subdivided = runtime.dispatch("mesh.subdivide_selected", {
            "object_name": "Repair Prop", "selection_id": split_selection, "cuts": 1,
        })
        assert subdivided["mesh_counts_after"]["vertices"] == 14
        faces = page("FACE")["items"]
        cap_faces = [face for face in faces if face["normal_local"][2] > .9]
        assert len(cap_faces) == 4 and all(face["vertex_count"] == 4 for face in cap_faces)
        assert all(face["material_index"] == 1 for face in cap_faces)
        for face in edit.faces:
            for loop in face.loops:
                if face.material_index == 0:
                    expected = Vector((loop.vert.co.x * .25 + .5, loop.vert.co.y * .25 + .5))
                    assert (loop[layer].uv - expected).length < 1e-5
                else:
                    assert loop[layer].uv.length < 1e-6
        runtime.dispatch("context.set_mode", {"object_name": "Repair Prop", "mode": "OBJECT"})
        repaired = bpy.data.objects["Repair Prop"]
        assert [m.name for m in repaired.data.materials] == ["Fixture Side", "Fixture Cap"]
        assert list(repaired.data.uv_layers.keys()) == ["Existing UV"]
        assert all(abs(repaired.vertex_groups[0].weight(vertex.index) - .25) < 1e-6
                   for vertex in repaired.data.vertices)
        assert all(abs(value - expected) < 1e-6 for value, expected in zip(repaired.dimensions, (2, 2, 2), strict=True))
        observed = runtime.dispatch("scene.compare", {"snapshot_id": baseline["snapshot_id"]})
        assert observed["coverage_complete"] and observed["status"] == "changed"
        assert {change["object"] for change in observed["changes"]} == {"Repair Prop"}
        untouched = runtime.dispatch("scene.compare", {"snapshot_id": guard["snapshot_id"]})
        assert untouched["status"] == "unchanged_within_scope" and untouched["coverage_complete"]
        after_wire = capture("wireframe")
        after_solid = capture("solid")
        restored = runtime.dispatch("checkpoint.undo_last", {
            "confirm_global_undo": True, "restore_snapshot": True,
        })
        assert restored["snapshot_marker_verified"] and restored["recovered_scope"] == "mesh_edit_session"
        comparison = runtime.dispatch("scene.compare", {"snapshot_id": baseline["snapshot_id"]})
        assert comparison["status"] == "unchanged_within_scope" and comparison["coverage_complete"]
        assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active.name == active
        assert sorted(obj.name for obj in bpy.context.selected_objects) == selected
        blender_codex_bridge.unregister()
        print("BLENDER_MESH_REPAIR_OK " + json.dumps({
            "blender": bpy.app.version_string, "selected_only_weld": True,
            "cap_and_quad_subdivision_verified": True, "material_uv_weight_checks": True,
            "protected_prop_unchanged": True, "edit_session_recovery_verified": True,
            "captures": {"before_wire": before_image, "after_wire": after_wire, "after_solid": after_solid},
            "visual_review_required": True, "project_saved": False,
        }), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
