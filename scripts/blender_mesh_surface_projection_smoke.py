"""Curved reference/working-patch fitting with independent distance and recovery proof."""

from __future__ import annotations

import faulthandler
import json
import math
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils.geometry import closest_point_on_tri

faulthandler.enable()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def make_grid(name, side, step):
    half = (side-1)*step*.5
    points = [(x*step-half, y*step-half, -.3*((x*step-half)**2+(y*step-half)**2))
              for y in range(side) for x in range(side)]
    faces = [(y*side+x, y*side+x+1, (y+1)*side+x+1, (y+1)*side+x)
             for y in range(side-1) for x in range(side-1)]
    mesh = bpy.data.meshes.new(name+" Data")
    mesh.from_pydata(points, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def native_uv_selection(bm):
    """Independent raw native API readback, distinct from named custom data."""
    if hasattr(bm, "uv_select_sync_valid"):
        return {"storage": "MESH_GLOBAL", "sync_valid": bool(bm.uv_select_sync_valid),
            "faces": [bool(face.uv_select) for face in bm.faces],
            "corners": [[(bool(loop.uv_select_vert), bool(loop.uv_select_edge))
                         for loop in face.loops] for face in bm.faces]}
    return {"storage": "PER_LAYER", "layers": [(layer.name, [
        (bool(loop[layer].select), bool(loop[layer].select_edge))
        for face in bm.faces for loop in face.loops]) for layer in bm.loops.layers.uv.values()]}


def seed_native_uv_selection(bm, *, sync_valid=True):
    modern = hasattr(bm, "uv_select_sync_valid")
    if modern:
        for index, loop in enumerate(loop for face in bm.faces for loop in face.loops):
            loop.uv_select_vert = index % 3 == 1
            loop.uv_select_edge = index % 5 == 1
        for index, face in enumerate(bm.faces):
            face.uv_select = index % 3 == 0
        bm.uv_select_sync_valid = sync_valid
    else:
        for offset, layer in enumerate(bm.loops.layers.uv.values()):
            for index, loop in enumerate(loop for face in bm.faces for loop in face.loops):
                loop[layer].select = (index+offset) % 3 == 1
                loop[layer].select_edge = (index+offset) % 5 == 1


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
        for toolset in ("mesh", "interaction"):
            runtime.registry.enable_toolset(toolset)
        frame = bpy.data.objects["Cube"]
        frame.name = "Protected Frame"
        frame.location = (0., 0., -1.)
        frame.scale = (1.1, 1.1, .12)
        source = make_grid("Curved Reference", 9, .3)
        source.display_type = "WIRE"
        alias = bpy.data.objects.new("Protected Reference Consumer", source.data)
        bpy.context.scene.collection.objects.link(alias)
        alias.location = (5., 0., 0.)
        patch = make_grid("Working Patch", 5, .45)
        mesh = patch.data
        moving = [y*5+x for y in range(1, 4) for x in range(1, 4)]
        boundary = [index for index in range(25) if index not in moving]
        source.data.calc_loop_triangles()
        initial_triangles = [tuple(source.data.vertices[index].co.copy() for index in tri.vertices)
                             for tri in source.data.loop_triangles]
        for vertex in mesh.vertices:
            candidates = [closest_point_on_tri(vertex.co, *triangle) for triangle in initial_triangles]
            vertex.co = min(candidates, key=lambda point: (vertex.co-point).length_squared)
            if vertex.index in moving:
                vertex.co.z += .35
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        patch.select_set(True)
        bpy.context.view_layer.objects.active = patch
        patch.show_wire = patch.show_all_edges = True
        for name in ("UV", "Spare"):
            mesh.uv_layers.new(name=name)
        # UV pin setters lazily allocate hidden BOOLEAN CustomData on 4.5.
        # Materialize all storage before retaining RNA UV-layer handles: adding
        # a native attribute can relocate their CustomDataLayer array.
        for layer_name in ("UV", "Spare"):
            for prefix in ("pn", "vs", "es"):
                if mesh.attributes.get(f".{prefix}.{layer_name}") is None:
                    mesh.attributes.new(name=f".{prefix}.{layer_name}", type="BOOLEAN", domain="CORNER")
        for name in ("UV", "Spare"):
            layer = mesh.uv_layers[name]
            for polygon in mesh.polygons:
                for loop_index in polygon.loop_indices:
                    vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
                    layer.data[loop_index].uv = ((vertex.co.x+.9)/1.8, (vertex.co.y+.9)/1.8)
                    layer.data[loop_index].pin_uv = vertex.index in boundary
        mesh.uv_layers.active_index = 1
        for layer_name in ("UV", "Spare"):
            for prefix, period in (("vs", 3), ("es", 5)):
                attribute = mesh.attributes.get(f".{prefix}.{layer_name}")
                if attribute is None:
                    attribute = mesh.attributes.new(name=f".{prefix}.{layer_name}", type="BOOLEAN", domain="CORNER")
                for index, entry in enumerate(attribute.data):
                    entry.value = index % period == 1
        point = mesh.color_attributes.new(name="Protected Point Color", type="FLOAT_COLOR", domain="POINT")
        for index, entry in enumerate(point.data):
            entry.color = (.1+index*.01, .25, .6, 1.)
        corner = mesh.color_attributes.new(name="Protected Corner Color", type="BYTE_COLOR", domain="CORNER")
        for entry in corner.data:
            entry.color = (.7, .2, .1, 1.)
        scalar = mesh.attributes.new(name="Protected Density", type="FLOAT", domain="POINT")
        for index, entry in enumerate(scalar.data):
            entry.value = index*.125
        group = patch.vertex_groups.new(name="Protected Weights")
        for index in range(25):
            group.add([index], .2+index*.02, "REPLACE")
        group.lock_weight = True
        material = bpy.data.materials.new("Protected Patch Checker")
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.uv_map = "UV"
        checker = nodes.new("ShaderNodeTexChecker")
        checker.inputs["Scale"].default_value = 6.
        checker.inputs["Color1"].default_value = (.04, .12, .18, 1.)
        checker.inputs["Color2"].default_value = (.6, .8, .9, 1.)
        links.new(uv_node.outputs["UV"], checker.inputs["Vector"])
        links.new(checker.outputs["Color"], nodes.get("Principled BSDF").inputs["Base Color"])
        mesh.materials.append(material)
        # Seed actual native UV state through Blender's own mesh conversion.
        # On 5.2 these are global flags and Mesh's sync-valid flag, independently
        # of the deliberately retained .vs/.es custom BOOLEAN attributes above.
        seeded = bmesh.new()
        try:
            seeded.from_mesh(mesh)
            seed_native_uv_selection(seeded, sync_valid=True)
            seeded.to_mesh(mesh)
        finally:
            seeded.free()
        mesh.update()
        bpy.context.view_layer.update()
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_location = (0., 0., -.15)
                space.region_3d.view_distance = 4.5
                overlay = space.overlay
                overlay.show_axis_x = overlay.show_axis_y = overlay.show_floor = overlay.show_cursor = False

        def call(method, **params):
            return runtime.dispatch(method, {"object_name": patch.name, **params})

        def capture(shading):
            for _attempt in range(2):
                result = call("viewport.capture", view="current", shading=shading,
                    resolution=[640, 480], include_overlays=shading == "wireframe")
                assert result["source"] == "viewport_opengl"
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            return result["path"]

        def preserved_attributes():
            # Inspect native Object Mode data independently of product capture.
            return {"point": [tuple(item.color) for item in mesh.color_attributes["Protected Point Color"].data],
                "corner": [tuple(item.color) for item in mesh.color_attributes["Protected Corner Color"].data],
                "scalar": [item.value for item in mesh.attributes["Protected Density"].data],
                "weights": [[(entry.group, entry.weight) for entry in vertex.groups] for vertex in mesh.vertices],
                "uv": [(layer.name, [(tuple(item.uv), bool(item.pin_uv)) for item in layer.data]) for layer in mesh.uv_layers],
                "named_boolean_custom_data": [(name, [bool(item.value) for item in mesh.attributes[name].data])
                    for name in (".vs.UV", ".es.UV", ".vs.Spare", ".es.Spare")],
                "uv_active": mesh.uv_layers.active_index, "material": mesh.materials[0].name}

        def current_native_uv_selection():
            if patch.mode == "EDIT":
                return native_uv_selection(bmesh.from_edit_mesh(mesh))
            temporary = bmesh.new()
            try:
                temporary.from_mesh(mesh)
                return native_uv_selection(temporary)
            finally:
                temporary.free()

        original = [tuple(vertex.co) for vertex in mesh.vertices]
        attributes_before = preserved_attributes()
        native_baseline = current_native_uv_selection()
        protected = runtime.dispatch("scene.snapshot", {"object_names": [source.name, alias.name, frame.name]})
        baseline = runtime.dispatch("scene.snapshot", {"object_names": [patch.name]})
        captures = {"before_material": capture("material")}
        call("context.set_mode", mode="EDIT")
        call("mesh.select_components", element_type="FACE", indices=list(range(16)))
        captures["before_wire"] = capture("wireframe")
        selected = call("mesh.select_components", element_type="VERT", indices=moving)
        reference = selected["selection"]["mesh_selection"]["selection_id"]
        live = bmesh.from_edit_mesh(mesh)
        seed_native_uv_selection(live, sync_valid=True)
        native_fault_baseline = native_uv_selection(live)
        args = {"selection_id": reference, "source_object": source.name,
                "source_polygon_indices": list(range(64)), "max_distance": .5}
        preview = call("mesh.surface_projection_preview", **args)
        assert preview["target_count"] == 9 and preview["maximum_distance_before_world"] > .25
        grants[Permission.EDIT_MESH.value] = False
        try:
            call("mesh.project_to_surface", expected_fingerprint=preview["fingerprint"], **args)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Projection bypassed live consent")
        grants[Permission.EDIT_MESH.value] = True
        original_update, updates = bmesh.update_edit_mesh, 0
        def fail_once(*positional, **keywords):
            nonlocal updates
            updates += 1
            if updates == 1:
                raise RuntimeError("fixture projection publication failure")
            return original_update(*positional, **keywords)
        bmesh.update_edit_mesh = fail_once
        try:
            try:
                call("mesh.project_to_surface", expected_fingerprint=preview["fingerprint"], **args)
            except BridgeError as error:
                assert error.context["rollback_verified"] and not error.context["possible_mutation"]
            else:
                raise AssertionError("Injected publication failure did not fail")
        finally:
            bmesh.update_edit_mesh = original_update
        live = bmesh.from_edit_mesh(mesh)
        assert [tuple(vertex.co) for vertex in live.verts] == original
        assert native_uv_selection(live) == native_fault_baseline
        seed_native_uv_selection(live, sync_valid=False)
        native_apply_baseline = native_uv_selection(live)
        preview = call("mesh.surface_projection_preview", **args)
        result = call("mesh.project_to_surface", expected_fingerprint=preview["fingerprint"], **args)
        assert result["supported_custom_data_preserved"] and result["source_preserved"]
        live = bmesh.from_edit_mesh(mesh)
        assert all(tuple(live.verts[index].co) == original[index] for index in boundary)
        assert native_uv_selection(live) == native_apply_baseline
        call("mesh.select_components", element_type="FACE", indices=list(range(16)))
        captures["after_wire"] = capture("wireframe")
        call("context.set_mode", mode="OBJECT")
        assert preserved_attributes() == attributes_before
        assert current_native_uv_selection() == native_apply_baseline
        captures["after_material"] = capture("material")
        # Independent native geometry helper, independent of product barycentric
        # math and returned hit records. Source has an actual second consumer.
        source.data.calc_loop_triangles()
        triangles = [tuple(source.matrix_world @ source.data.vertices[index].co for index in tri.vertices)
                     for tri in source.data.loop_triangles]
        residuals = [min((patch.matrix_world @ mesh.vertices[index].co-closest_point_on_tri(
            patch.matrix_world @ mesh.vertices[index].co, *triangle)).length for triangle in triangles) for index in moving]
        assert max(residuals) < 1e-6 and source.data.users == 2
        assert all(tuple(mesh.vertices[index].co) == original[index] for index in boundary)
        assert math.dist(tuple(mesh.vertices[12].co), original[12]) > .3
        comparison = runtime.dispatch("scene.compare", {"snapshot_id": protected["snapshot_id"]})
        assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope"
        recovered = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert recovered["snapshot_marker_verified"] and recovered["recovered_scope"] == "mesh_edit_session"
        patch = bpy.data.objects["Working Patch"]
        mesh = patch.data
        assert [tuple(vertex.co) for vertex in mesh.vertices] == original
        comparison = runtime.dispatch("scene.compare", {"snapshot_id": baseline["snapshot_id"]})
        if not comparison["coverage_complete"] or comparison["status"] != "unchanged_within_scope":
            print("MESH_SURFACE_RECOVERY_COMPARISON "+json.dumps(comparison), flush=True)
        assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope"
        assert preserved_attributes() == attributes_before
        # Whole Edit-session native recovery must restore the actual original
        # per-layer/global flags. 5.2 serializes sync-valid in Mesh's own flag.
        assert current_native_uv_selection() == native_baseline
        blender_codex_bridge.unregister()
        print("BLENDER_MESH_SURFACE_PROJECTION_OK "+json.dumps({"blender_version": bpy.app.version_string,
            "projected_vertices": 9, "maximum_independent_residual_world": max(residuals),
            "curved_reference_and_shared_consumer_preserved": True, "protected_outer_silhouette_preserved": True,
            "uv_pins_spare_colors_scalar_weights_material_preserved": True,
            "named_boolean_custom_data_both_maps_preserved": True,
            "actual_native_uv_selection_storage": native_baseline["storage"],
            "actual_native_uv_selection_all_faces_preserved": True,
            "mesh_global_face_corner_flags_preserved": native_baseline["storage"] == "MESH_GLOBAL",
            "actual_uv_sync_valid_true_fault_false_apply_and_native_undo_verified": native_baseline["storage"] == "MESH_GLOBAL",
            "live_consent_verified": True, "local_fault_recovery_verified": True,
            "native_edit_session_recovery_verified": True, "captures": captures,
            "visual_review_required": True, "project_saved": False,
            "evaluated_projection_custom_normals_shape_keys_full_retopology_complete": False}), flush=True)
    except Exception as error:
        if isinstance(error, BridgeError):
            print("MESH_SURFACE_FAILURE_CONTEXT "+json.dumps(error.context), flush=True)
        traceback.print_exc()
    finally:
        # Release this callback's live Edit BMesh/RNA handles before native
        # shutdown and let the restored viewport flush its pending draw once.
        bpy.app.timers.register(quit_after_run, first_interval=.5)
    return None


def quit_after_run():
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.)
