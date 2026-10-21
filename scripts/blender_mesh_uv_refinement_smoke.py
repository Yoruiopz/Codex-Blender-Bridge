"""Independent prop-panel slide/UV revision and whole-session native recovery."""

from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bmesh
import bpy

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
        for permission in (Permission.EXECUTE_PYTHON, Permission.DELETE_OBJECTS,
                           Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT):
            grants[permission.value] = False
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        for toolset in ("interaction", "mesh", "uv"):
            runtime.registry.enable_toolset(toolset)
        frame = bpy.data.objects["Cube"]
        frame.name = "Protected Prop Frame"
        frame.location = (0., 0., -.15)
        frame.scale = (1.2, 1.2, .12)
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        frame.select_set(True)
        mesh = bpy.data.meshes.new("Refinement Panel Data")
        mesh.from_pydata([(float(index % 3)-1., float(index // 3)-1., 0.) for index in range(9)],
            [], [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7)])
        panel = bpy.data.objects.new("Prop Face Panel", mesh)
        bpy.context.scene.collection.objects.link(panel)
        panel.select_set(True)
        panel.show_wire = panel.show_all_edges = True
        bpy.context.view_layer.objects.active = panel
        temporary = bmesh.new()
        temporary.from_mesh(mesh)
        temporary.faces.index_update()
        for name in ("UV", "Spare"):
            layer = temporary.loops.layers.uv.new(name)
            for face in temporary.faces:
                for loop in face.loops:
                    uv = ((loop.vert.co.x+1.)*.5, (loop.vert.co.y+1.)*.5)
                    if name == "UV" and loop.vert.index == 4:
                        uv = (.5625, .53125)
                    if name == "UV" and loop.vert.index == 1:
                        uv = (.515625, 0.)
                    if name == "UV" and face.index == 1 and loop.vert.index == 4:
                        uv = (.59375, .53125)
                    loop[layer].uv = uv
                    loop[layer].pin_uv = loop.vert.index == 0
        temporary.to_mesh(mesh)
        temporary.free()
        mesh.uv_layers.active_index = 1
        material = bpy.data.materials.new("Protected Checker Material")
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        mapping = nodes.new("ShaderNodeUVMap")
        mapping.uv_map = "UV"
        checker = nodes.new("ShaderNodeTexChecker")
        checker.inputs["Scale"].default_value = 5.
        checker.inputs["Color1"].default_value = (.04, .12, .2, 1.)
        checker.inputs["Color2"].default_value = (.5, .7, .8, 1.)
        links.new(mapping.outputs["UV"], checker.inputs["Vector"])
        links.new(checker.outputs["Color"], nodes.get("Principled BSDF").inputs["Base Color"])
        mesh.materials.append(material)
        mesh.update()
        bpy.context.view_layer.update()
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_location = (0., 0., 0.)
                area.spaces.active.region_3d.view_distance = 4.
                # World axes coincide with the original centre edges. Hide them
                # so both baseline and revised topology remain independently visible.
                overlay = area.spaces.active.overlay
                overlay.show_axis_x = overlay.show_axis_y = overlay.show_floor = overlay.show_cursor = False

        def call(method, **params):
            return runtime.dispatch(method, {"object_name": panel.name, **params})

        def deny(method, expected, **params):
            try:
                return call(method, **params)
            except BridgeError as error:
                assert error.code == expected, (method, error.code, error.message)
                return error
            raise AssertionError("Expected rejection: " + method)

        def capture(shading):
            # Native material/GPU draw caches can be cold after fixture setup or
            # an Edit Mode flush. Warm the same typed capture and redraw before
            # retaining its matched evidence; keep topology overlays for wire.
            for _attempt in range(2):
                result = call("viewport.capture", view="top", shading=shading,
                    resolution=[512, 384], include_overlays=shading == "wireframe")
                assert result["source"] == "viewport_opengl"
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            return result["path"]

        def coords(layer):
            if panel.mode == "EDIT":
                live = bmesh.from_edit_mesh(panel.data)
                handle = live.loops.layers.uv.get(layer)
                return [(face.index, index, tuple(loop[handle].uv), bool(loop[handle].pin_uv))
                    for face in live.faces for index, loop in enumerate(face.loops)]
            return [(face.index, index, tuple(panel.data.uv_layers[layer].data[face.loop_start+index].uv),
                     bool(panel.data.uv_layers[layer].data[face.loop_start+index].pin_uv))
                    for face in panel.data.polygons for index in range(face.loop_total)]

        original_uv, original_spare = coords("UV"), coords("Spare")
        original_vertices = [tuple(vertex.co) for vertex in mesh.vertices]
        baseline = runtime.dispatch("scene.snapshot", {"object_names": [panel.name, frame.name]})
        protected = runtime.dispatch("scene.snapshot", {"object_names": [frame.name]})
        non_geometry = runtime.dispatch("scene.snapshot", {"object_names": [panel.name],
            "fields": ["transforms", "hierarchy", "visibility", "weights", "material_slots", "shader_inputs"]})
        captures = {"before_material": capture("material"),
            "before_uv": call("uv.capture_layout", uv_layer="UV", size=512, view="FIT")["path"]}
        call("context.set_mode", mode="EDIT")
        call("mesh.select_components", element_type="FACE", indices=[0, 1, 2, 3])
        captures["before_wire"] = capture("wireframe")
        selected = call("mesh.select_components", element_type="VERT", indices=[4])
        reference = selected["selection"]["mesh_selection"]["selection_id"]
        args = {"selection_id": reference, "targets": [{"vertex_index": 4, "target_vertex_index": 5}],
            "factor": .15, "max_distance": .2}
        preview = call("mesh.slide_preview", mode="VERTEX", **args)
        grants[Permission.EDIT_MESH.value] = False
        deny("mesh.vertex_slide", "PERMISSION_DENIED", expected_fingerprint=preview["fingerprint"], **args)
        grants[Permission.EDIT_MESH.value] = True
        vertex = call("mesh.vertex_slide", expected_fingerprint=preview["fingerprint"], **args)
        assert vertex["target_count"] == 1 and vertex["uv_layers_preserved"]
        live = bmesh.from_edit_mesh(panel.data)
        live.edges.ensure_lookup_table()
        live.edges.index_update()
        chain = [edge.index for edge in live.edges if {v.index for v in edge.verts} in ({1, 4}, {4, 7})]
        assert len(chain) == 2
        selected = call("mesh.select_components", element_type="EDGE", indices=chain)
        reference = selected["selection"]["mesh_selection"]["selection_id"]
        args = {"selection_id": reference, "targets": [{"vertex_index": index, "target_vertex_index": index+1}
            for index in (1, 4, 7)], "factor": .2, "max_distance": .21}
        preview = call("mesh.slide_preview", mode="EDGE", **args)
        edge = call("mesh.edge_slide", expected_fingerprint=preview["fingerprint"], **args)
        assert edge["target_count"] == 3
        live = bmesh.from_edit_mesh(panel.data)
        for index, expected in ((1, .2), (4, .32), (7, .2)):
            assert abs(live.verts[index].co.x-expected) < 1e-6
        for index, point in enumerate(original_vertices):
            if index not in {1, 4, 7}:
                assert tuple(live.verts[index].co) == point
        assert coords("UV") == original_uv and coords("Spare") == original_spare
        selection = call("mesh.select_components", element_type="FACE", indices=[0, 1, 2, 3])
        reference = selection["selection"]["mesh_selection"]["selection_id"]
        common = {"uv_layer": "UV", "selection_id": reference}
        deny("uv.align", "INVALID_ARGUMENT", corners=[{"face_index": 0, "corner_index": 0}], axis="U", value=.1, **common)
        aligned = call("uv.align", corners=[{"face_index": 0, "corner_index": 1},
            {"face_index": 1, "corner_index": 0}], axis="U", value=.5, **common)
        assert aligned["changed_corners"] == 2
        stitched = call("uv.stitch", pairs=[{"source": {"face_index": 0, "corner_index": 2},
            "target": {"face_index": 1, "corner_index": 3}}], max_distance=.1, **common)
        assert stitched["maximum_gap_after_uv"] == 0.
        before_fault = coords("UV")
        original_update = bmesh.update_edit_mesh
        count = 0
        def fail_once(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("fixture UV publication failure")
            return original_update(*args, **kwargs)
        bmesh.update_edit_mesh = fail_once
        try:
            error = deny("uv.align", "OPERATION_FAILED", corners=[{"face_index": 0, "corner_index": 1}], axis="U", value=.48, **common)
            assert error.context["rollback_verified"]
        finally:
            bmesh.update_edit_mesh = original_update
        assert coords("UV") == before_fault
        relaxed = call("uv.relax", face_indices=[0, 1, 2, 3], iterations=12,
            strength=.5, max_displacement=.1, **common)
        assert relaxed["movable_uv_nodes"] == 1 and relaxed["fixed_uv_nodes"] == 8
        assert relaxed["edge_energy_after"] < relaxed["edge_energy_before"]
        live = bmesh.from_edit_mesh(panel.data)
        handle = live.loops.layers.uv.get("UV")
        for face in live.faces:
            for loop in face.loops:
                if loop.vert.index == 4:
                    assert math.dist(tuple(loop[handle].uv), (.5, .5)) < .0001
                if loop.vert.index == 0:
                    assert loop[handle].pin_uv and tuple(loop[handle].uv) == (0., 0.)
        assert coords("Spare") == original_spare
        captures["after_wire"] = capture("wireframe")
        call("context.set_mode", mode="OBJECT")
        panel = bpy.data.objects["Prop Face Panel"]
        captures.update(after_material=capture("material"),
            after_uv=call("uv.capture_layout", uv_layer="UV", size=512, view="FIT")["path"])
        assert mesh.uv_layers.active.name == "Spare"
        for snapshot in (protected, non_geometry):
            compared = runtime.dispatch("scene.compare", {"snapshot_id": snapshot["snapshot_id"]})
            assert compared["coverage_complete"] and compared["status"] == "unchanged_within_scope"
        recovered = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert recovered["snapshot_marker_verified"] and recovered["recovered_scope"] == "mesh_edit_session"
        comparison = runtime.dispatch("scene.compare", {"snapshot_id": baseline["snapshot_id"]})
        assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope"
        assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active.name == "Prop Face Panel"
        blender_codex_bridge.unregister()
        print("BLENDER_MESH_UV_REFINEMENT_OK " + json.dumps({"blender_version": bpy.app.version_string,
            "vertex_and_chain_slide_verified": True, "explicit_uv_align_stitch_relax_verified": True,
            "protected_frame_material_pins_spare_layer_verified": True, "local_fault_rollback_verified": True,
            "actual_native_edit_session_recovery_verified": True, "captures": captures,
            "visual_review_required": True, "project_saved": False, "full_retopology_complete": False}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.)
