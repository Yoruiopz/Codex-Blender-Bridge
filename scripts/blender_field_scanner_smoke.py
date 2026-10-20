"""Reference-constrained scanner workflow: structured authoring, measured state and visual review."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "addon"))
from scripts.field_scanner_spec import (  # noqa: E402
    asset_hashes,
    create_steps,
    geometry_recipe,
    glass_uv_updates,
    load_brief,
    surface_steps,
    write_fixture_textures,
)


def run():
    try:
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime

        brief, parts = load_brief(), geometry_recipe()
        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = prefs.allow_external_files = False
        for toolset in ("objects", "mesh", "uv", "materials", "nodes", "interaction", "modifiers", "batch"):
            runtime.registry.enable_toolset(toolset)
        # Only the negative-control fixture is prebuilt through native data APIs.
        # Every scanner component/edit/material is authored through typed bridge tools.
        protected = bpy.data.objects["Cube"]
        protected.name, protected.location = brief["protected_object"], (.38, .0, .04)
        protected.scale = (.015, .010, .020)
        protected.vertex_groups.new(name="Protected Weight").add(list(range(8)), .4, "REPLACE")
        source_material = protected.active_material
        source_material.name = "Calibration Source"
        source_material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = [.08, .16, .28, 1]
        assert bpy.context.scene.unit_settings.scale_length == 1
        request_count, stages = [0], []

        def call(method, **params):
            request_count[0] += 1
            return runtime.dispatch(method, params)

        def batch(label, steps):
            plan = call("batch.plan", label=label, steps=steps)
            assert plan["ready"] and not plan["atomic"]
            result = call("batch.execute", label=label, steps=steps)
            stages.append({"label": label, "steps": len(steps)})
            return result

        def page(kind, name="Scanner Shell"):
            result = call("mesh.components_inspect", object_name=name, element_type=kind, max_items=256)
            assert not result["truncated"], result
            return result["items"]

        def select(kind, indices, name="Scanner Shell"):
            result = call("mesh.select_components", object_name=name, element_type=kind, indices=indices)
            return result["selection"]["mesh_selection"]["selection_id"]

        def mode(value, name="Scanner Shell"):
            return call("context.set_mode", object_name=name, mode=value)

        def protected_unchanged():
            result = call("scene.compare", snapshot_id=protected_baseline["snapshot_id"])
            assert result["coverage_complete"] and result["status"] == "unchanged_within_scope", result

        def measured(name, *, closed=True):
            obj = bpy.data.objects[name]
            mesh = bmesh.new()
            mesh.from_mesh(obj.data)
            try:
                values = {"vertices": len(mesh.verts), "faces": len(mesh.faces),
                          "nonmanifold_edges": sum(not edge.is_manifold for edge in mesh.edges),
                          "signed_volume": mesh.calc_volume(signed=True)}
                if closed:
                    assert values["nonmanifold_edges"] == 0 and values["signed_volume"] > 0, (name, values)
                return values
            finally:
                mesh.free()

        def capture(view="current", shading="material", target=None):
            regions = [area.spaces.active.region_3d for area in bpy.context.screen.areas if area.type == "VIEW_3D"]
            before = [(r.view_location.copy(), r.view_rotation.copy(), r.view_distance) for r in regions]
            try:
                for region in regions:
                    region.view_location = Vector((0, 0, .13)) if target is None else bpy.data.objects[target].matrix_world.translation
                    region.view_distance = .31 if target is None else .16
                    region.view_rotation = Vector((4, -6, 3)).to_track_quat("Z", "Y")
                return call("viewport.capture", view=view, shading=shading,
                            **({"object_name": target} if target else {}),
                            include_overlays=False, resolution=[768, 1024])["path"]
            finally:
                for region, (location, rotation, distance) in zip(regions, before, strict=True):
                    region.view_location, region.view_rotation, region.view_distance = location, rotation, distance

        status = call("bridge.status")
        call("selection.inspect")
        initial_selection = sorted(obj.name for obj in bpy.context.selected_objects)
        initial_active = bpy.context.view_layer.objects.active.name
        protected_baseline = call("scene.snapshot", object_names=[brief["protected_object"], "Camera", "Light"])
        captures = {"protected_before": capture(target=brief["protected_object"])}
        def datablock_names():
            return {kind: sorted(item.name for item in getattr(bpy.data, kind))
                    for kind in ("objects", "meshes", "materials", "node_groups", "images")}
        datablocks_before = datablock_names()
        checkpoint = call("checkpoint.create", description="Start original field-scanner geometry")
        batch("Create scanner components and temporary slot cutters", create_steps())
        for item in parts:
            obj = bpy.data.objects[item["name"]]
            expected = item["geometry"].get("face_smooth")
            if expected is not None:
                assert [poly.use_smooth for poly in obj.data.polygons] == expected
            if item["name"] != "Scanner Shell":
                measured(item["name"])
        mode("EDIT")
        ref = select("EDGE", [edge["index"] for edge in page("EDGE")])
        bridge = call("mesh.bridge_loops", object_name="Scanner Shell", selection_id=ref)
        assert bridge["created_faces"] == 8
        faces = page("FACE")
        boundary = [edge["index"] for edge in page("EDGE")
                    if sum(set(edge["vertex_indices"]).issubset(face["vertex_indices"]) for face in faces) == 1]
        fill = call("mesh.fill_holes", object_name="Scanner Shell", selection_id=select("EDGE", boundary))
        assert fill["created_faces"] == 2
        call("mesh.recalculate_normals", object_name="Scanner Shell", selection_only=False)
        front = next(face for face in page("FACE") if face["vertex_count"] == 8 and face["normal_local"][1] < -.9)
        call("mesh.inset_selected", object_name="Scanner Shell", selection_id=select("FACE", [front["index"]]),
             thickness=brief["shell"]["fascia_inset"])
        front = next(face for face in page("FACE") if face["vertex_count"] == 8 and face["normal_local"][1] < -.9)
        call("mesh.extrude_selected", object_name="Scanner Shell", selection_id=select("FACE", [front["index"]]),
             offset=[0, brief["shell"]["fascia_recess"], 0])
        call("mesh.recalculate_normals", object_name="Scanner Shell", selection_only=False)
        mode("OBJECT")
        shell_before_slots = measured("Scanner Shell")
        protected_unchanged()

        material_steps = []
        roles = brief["material_roles"]
        for key, role in roles.items():
            if key != "shell":
                material_steps += [{"method": "material.create", "params": {"name": role["name"]}},
                                   {"method": "material.set_principled", "params": {"material_name": role["name"],
                                    "base_color": role["color"], "roughness": role["roughness"], "metallic": role["metallic"]}}]
        for item in parts:
            material_steps.append({"method": "material.assign", "params": {"object_name": item["name"],
                "material_name": "Calibration Source" if item["role"] == "shell" else roles[item["role"]]["name"]}})
        material_steps += [{"method": "material.copy_for_object", "params": {"object_name": "Scanner Shell", "slot_index": 0, "new_name": roles["shell"]["name"]}},
                           {"method": "material.set_principled", "params": {"material_name": roles["shell"]["name"],
                            "base_color": roles["shell"]["color"], "roughness": roles["shell"]["roughness"], "metallic": roles["shell"]["metallic"]}}]
        batch("Isolate shell finish and assign component roles", material_steps)
        cutters = [item["name"] for item in parts if item.get("temporary")]
        slot_steps = []
        for index, cutter in enumerate(cutters):
            name = f"Vent Pocket {index + 1}"
            slot_steps += [{"method": "modifier.add", "params": {"object_name": "Scanner Shell", "modifier_name": name,
                            "modifier_type": "BOOLEAN", "settings": {"operation": "DIFFERENCE", "solver": "EXACT", "object": cutter}}},
                           {"method": "modifier.apply", "params": {"object_name": "Scanner Shell", "modifier_name": name}},
                           {"method": "object.delete", "params": {"object_name": cutter}}]
        try:
            call("batch.plan", label="Carve grille pockets and remove only owned cutters", steps=slot_steps)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Cutter deletion was not permission gated")
        # Explicit fixture consent for these exact, newly created cutter objects only.
        prefs.allow_delete_objects = True
        batch("Carve grille pockets and remove only owned cutters", slot_steps)
        prefs.allow_delete_objects = False
        assert not any(bpy.data.objects.get(name) for name in cutters)
        shell_after_slots = measured("Scanner Shell")
        assert shell_after_slots["signed_volume"] < shell_before_slots["signed_volume"]
        slot = call("material.slot_add", object_name="Scanner Shell", material_name=roles["bezel"]["name"])
        grille_material_index = slot["slot_index"]
        assert bpy.data.objects["Scanner Shell"].material_slots[grille_material_index].material.name == roles["bezel"]["name"]
        call("uv.layer_create", object_name="Scanner Shell", new_name="Scanner UV")
        mode("EDIT")
        floor_y = brief["grille"]["cutter_back_y"]
        floors = [face["index"] for face in page("FACE") if face["normal_local"][1] < -.9
                  and abs(face["center_local"][1] - floor_y) < .000001]
        assert len(floors) == 4, floors
        # Native negative controls: dynamic material consent and a failure after
        # Blender has already updated the live edit mesh must not be called success.
        face_reference = select("FACE", floors)
        prefs.allow_edit_materials = False
        try:
            call("mesh.set_face_attributes", object_name="Scanner Shell", selection_id=face_reference, material_index=grille_material_index)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Face slot edit bypassed material permission")
        finally:
            prefs.allow_edit_materials = True
        from blender_codex_bridge.tools import face_attributes
        native_update = face_attributes.mesh.bmesh.update_edit_mesh
        native_mesh = bmesh.from_edit_mesh(bpy.data.objects["Scanner Shell"].data)
        native_mesh.faces.ensure_lookup_table()
        floor_attributes_before = [(bool(native_mesh.faces[i].smooth), native_mesh.faces[i].material_index) for i in floors]
        updates = [0]
        def fail_after_update(*args, **kwargs):
            native_update(*args, **kwargs)
            updates[0] += 1
            if updates[0] == 1:
                raise RuntimeError("Injected native post-update face-attribute failure")
        face_reference = select("FACE", floors)
        face_attributes.mesh.bmesh.update_edit_mesh = fail_after_update
        try:
            call("mesh.set_face_attributes", object_name="Scanner Shell", selection_id=face_reference,
                 smooth=not floor_attributes_before[0][0], material_index=grille_material_index)
        except BridgeError as error:
            assert error.context["rollback_verified"] and not error.context["possible_mutation"]
        else:
            raise AssertionError("Injected face update was not reported as failure")
        finally:
            face_attributes.mesh.bmesh.update_edit_mesh = native_update
        native_mesh = bmesh.from_edit_mesh(bpy.data.objects["Scanner Shell"].data)
        native_mesh.faces.ensure_lookup_table()
        assert [(bool(native_mesh.faces[i].smooth), native_mesh.faces[i].material_index) for i in floors] == floor_attributes_before
        # The 3-mm pockets self-occlude their 1.5-mm floors in an elevated view.
        # Darken the actual inner walls too, not just the unseen floor or fake bars.
        fascia_y = -brief["shell"]["thickness"] / 2 + brief["shell"]["fascia_recess"]
        pocket_faces = [face["index"] for face in page("FACE")
                        if fascia_y + 1e-6 < face["center_local"][1] <= floor_y + 1e-6
                        and abs(face["center_local"][0]) <= brief["grille"]["width"] / 2 + 1e-6
                        and any(abs(face["center_local"][2] - z) <= brief["grille"]["height"] / 2 + 1e-6 for z in brief["grille"]["z"])]
        assert len(pocket_faces) == 20 and set(floors).issubset(pocket_faces), pocket_faces
        call("mesh.set_face_attributes", object_name="Scanner Shell", selection_id=select("FACE", pocket_faces), material_index=grille_material_index)
        assert all(face["material_index"] == grille_material_index for face in page("FACE") if face["index"] in pocket_faces)
        vertices = {vertex["index"]: vertex["center_local"] for vertex in page("VERT")}
        seams = []
        shell = brief["shell"]
        for edge in page("EDGE"):
            a, b = (vertices[index] for index in edge["vertex_indices"])
            front = max(a[1], b[1]) <= -shell["thickness"] / 2 + shell["fascia_recess"] + 1e-6
            rear = all(abs(v[1] - shell["thickness"] / 2) < 1e-6 for v in (a, b))
            opening = any(all(abs(v[0]) <= brief["grille"]["width"] / 2 + 1e-6
                and abs(v[2] - z) <= brief["grille"]["height"] / 2 + 1e-6 for v in (a, b)) for z in brief["grille"]["z"])
            strip_cut = all(abs(v[0] - (shell["width"] / 2 - shell["corner"])) < 1e-6 and abs(v[2]) < 1e-6 for v in (a, b))
            if front or rear or opening or strip_cut:
                seams.append(edge["index"])
        call("mesh.mark_seams", object_name="Scanner Shell", selection_id=select("EDGE", seams))
        select("FACE", [face["index"] for face in page("FACE")])
        call("uv.unwrap", object_name="Scanner Shell", uv_layer="Scanner UV", create_if_missing=False, margin=.01)
        call("uv.pack_islands", object_name="Scanner Shell", uv_layer="Scanner UV", margin=.008)
        shell_uv = call("uv.analyze", object_name="Scanner Shell", uv_layer="Scanner UV",
                        texture_resolution=[1024, 1024], anisotropy_warning=1.1, max_reports=256)
        assert shell_uv["analysis_complete"] and shell_uv["verification"]["status"] == "numeric_checks_passed", shell_uv
        captures["shell_uv"] = call("uv.capture_layout", object_name="Scanner Shell", uv_layer="Scanner UV", size=768)["path"]
        mode("OBJECT")
        call("uv.layer_create", object_name="Scanner Glass", new_name="Display UV")
        mode("EDIT", "Scanner Glass")
        glass_faces = page("FACE", "Scanner Glass")
        glass_vertices = {v["index"]: v["center_local"] for v in page("VERT", "Scanner Glass")}
        call("uv.coordinates_set", object_name="Scanner Glass", uv_layer="Display UV",
             selection_id=select("FACE", [f["index"] for f in glass_faces], "Scanner Glass"),
             updates=glass_uv_updates(glass_vertices, glass_faces, brief))
        glass_uv = call("uv.analyze", object_name="Scanner Glass", uv_layer="Display UV",
                        texture_resolution=[500, 350], anisotropy_warning=1.1, max_reports=256)
        assert glass_uv["analysis_complete"] and glass_uv["verification"]["status"] == "numeric_checks_passed", glass_uv
        captures["glass_uv"] = call("uv.capture_layout", object_name="Scanner Glass", uv_layer="Display UV", size=768)["path"]
        mode("OBJECT", "Scanner Glass")
        textures = write_fixture_textures(Path(tempfile.gettempdir()) / "scanner-textures")
        prefs.texture_directory, prefs.allow_external_files = str(textures["shell_color"].parent), True
        shell_material, display_material = roles["shell"]["name"], roles["glass"]["name"]
        batch("Nested shell color and data-texture finish", surface_steps(
            shell_material, "Scanner Shell Surface", "Scanner UV", textures["shell_color"], "Scanner Shell Color",
            roughness_path=textures["shell_roughness"]))
        batch("Nested calibration display material", surface_steps(
            display_material, "Scanner LCD Surface", "Display UV", textures["lcd_calibration"], "Scanner LCD Calibration", emission=True))
        def surface(material):
            return bpy.data.materials[material].node_tree.nodes["Surface"].node_tree
        def image_hash(name):
            from array import array
            image = bpy.data.images[name]
            assert image.has_data
            values = array("f", [0]) * len(image.pixels)
            image.pixels.foreach_get(values)
            return hashlib.sha256(values.tobytes()).hexdigest()
        for material, uv_name in ((shell_material, "Scanner UV"), (display_material, "Display UV")):
            inspection = call("nodes.inspect", material_name=material, group_path=["Surface"], max_nodes=32, max_sockets_per_direction=64)
            assert not inspection["truncated"]
            assert surface(material).nodes["UV Coordinates"].uv_map == uv_name
            assert surface(material).nodes["Albedo"].image.colorspace_settings.name == "sRGB"
            assert surface(material).nodes["Finish"].inputs["Base Color"].is_linked
        assert surface(shell_material).nodes["Roughness"].image.colorspace_settings.name == "Non-Color"
        assert surface(shell_material).nodes["Finish"].inputs["Roughness"].is_linked
        calibration_pixels = image_hash("Scanner LCD Calibration")
        bevels = []
        for item in parts:
            if not item.get("temporary"):
                bevels.append({"method": "modifier.add", "params": {"object_name": item["name"],
                    "modifier_name": "Manufactured Edge", "modifier_type": "BEVEL",
                    "settings": {"width": .0005 if item["role"] in {"metal", "status", "glass"} else .0007,
                                 "segments": 3, "limit_method": "ANGLE", "angle_limit": .5, "use_clamp_overlap": True}}})
        batch("Non-destructive manufactured edge finish", bevels)
        captures["calibration_variant"] = capture("front")
        revision_batch = batch("Blue telemetry texture and painted readiness accents", [
            {"method": "nodes.refresh_image", "params": {"material_name": display_material, "group_path": ["Surface"],
             "node_name": "Albedo", "new_image_name": "Scanner LCD Scan", "filepath": str(textures["lcd_scan"])}},
            {"method": "image.paint_version", "params": {"image_name": "Scanner LCD Scan", "new_name": "Scanner LCD Painted",
             "strokes": [{"points": [[.055, .784], [.209, .784]], "radius_pixels": 1.5, "hardness": .8,
                          "color": [.1, .8, 1., 1.], "opacity": .9},
                         {"points": [[.677, .35]], "radius_pixels": 3., "hardness": 1., "color": [.02, .8, .1, 1.]}]}},
            {"method": "nodes.set_image", "params": {"material_name": display_material, "group_path": ["Surface"],
             "node_name": "Albedo", "image_name": "Scanner LCD Painted"}},
        ])
        revision = revision_batch["results"][0]["result"]
        assert revision["revision_mode"] == "new_image_for_node" and not revision["previous_buffer_reloaded"]
        paint = revision_batch["results"][1]["result"]
        assert paint["source_pixels_unchanged"] and paint["painted_pixels"] > 0
        assert surface(display_material).nodes["Albedo"].image.name == "Scanner LCD Painted"
        assert surface(display_material).nodes["Albedo"].image.colorspace_settings.name == "Linear Rec.709"
        painted_inspection = call("image.inspect_pixels", image_name="Scanner LCD Painted")
        assert painted_inspection["pixels_sha256_float32_le"] == paint["pixels_sha256_float32_le"]
        assert image_hash("Scanner LCD Calibration") == calibration_pixels and image_hash("Scanner LCD Scan") != calibration_pixels
        bpy.context.view_layer.update()
        all_points = [obj.matrix_world @ vertex.co for obj in (bpy.data.objects[p["name"]] for p in parts if not p.get("temporary")) for vertex in obj.data.vertices]
        dimensions = [max(point[i] for point in all_points) - min(point[i] for point in all_points) for i in range(3)]
        assert all(abs(actual - wanted) < brief["dimension_tolerance"] for actual, wanted in zip(dimensions, brief["overall_dimensions"], strict=True)), dimensions
        evaluated = bpy.data.objects["Scanner Handle"].evaluated_get(bpy.context.evaluated_depsgraph_get())
        evaluated_mesh = evaluated.to_mesh()
        try:
            tree = BVHTree.FromPolygons([tuple(v.co) for v in evaluated_mesh.vertices], [tuple(p.vertices) for p in evaluated_mesh.polygons])
            origin = Vector((0, 0, brief["handle"]["center_z"]))
            assert tree.ray_cast(origin, Vector((0, 1, 0)), .2)[0] is None
            assert tree.ray_cast(origin, Vector((0, -1, 0)), .2)[0] is None
            clearance = [sum(tree.ray_cast(origin, Vector(direction), .2)[3] for direction in directions)
                         for directions in (((1, 0, 0), (-1, 0, 0)), ((0, 0, 1), (0, 0, -1)))]
            assert all(abs(a - b) < brief["dimension_tolerance"] for a, b in zip(clearance, brief["handle"]["inner"], strict=True)), clearance
        finally:
            evaluated.to_mesh_clear()
        protected_unchanged()
        captures["geometry_front"] = capture("front")
        captures["geometry_isometric"] = capture()
        captures["geometry_wire"] = capture(shading="wireframe")
        # A real non-atomic batch fails only after a valid material edit. Recovery
        # must use the finalized native boundary, then independently compare the
        # nested graphs, UVs, image buffers and geometry (scene.compare alone does
        # not claim nested shader coverage).
        def asset_state():
            meshes = {}
            for part in parts:
                if part.get("temporary"):
                    continue
                obj = bpy.data.objects[part["name"]]
                meshes[obj.name] = {"vertices": [list(v.co) for v in obj.data.vertices],
                    "faces": [(list(p.vertices), p.material_index, p.use_smooth) for p in obj.data.polygons],
                    "uv": {layer.name: [list(loop.uv) for loop in layer.data] for layer in obj.data.uv_layers}}
            graphs = {material: call("nodes.inspect", material_name=material, group_path=["Surface"], max_nodes=32, max_sockets_per_direction=64)
                      for material in (shell_material, display_material)}
            return {"meshes": meshes, "graphs": graphs,
                    "pixels": {name: image_hash(name) for name in ("Scanner Shell Color", "Scanner Roughness", "Scanner LCD Calibration", "Scanner LCD Scan", "Scanner LCD Painted")}}
        asset_before_failure = asset_state()
        try:
            batch("Failed material refinement with measured recovery", [
                {"method": "nodes.set_input", "params": {"material_name": display_material, "group_path": ["Surface"], "node_name": "Finish", "socket_name": "Roughness", "value": .85}},
                {"method": "nodes.set_input", "params": {"material_name": display_material, "group_path": ["Surface"], "node_name": "Finish", "socket_name": "Missing Fixture Socket", "value": 1.}},
            ])
        except BridgeError as error:
            assert error.context["completed_steps"] == 1 and error.context["undo_boundary_finalized"], error.to_dict()
        else:
            raise AssertionError("Invalid refinement was reported as successful")
        assert abs(surface(display_material).nodes["Finish"].inputs["Roughness"].default_value - .85) < 1e-6
        recovery = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
        assert recovery["snapshot_marker_verified"] and asset_state() == asset_before_failure
        protected_unchanged()
        captures["recovered_front"] = capture("front")
        captures["protected_after"] = capture(target=brief["protected_object"])
        call("selection.set", object_names=initial_selection, active_object=initial_active)
        assert bpy.context.mode == "OBJECT"
        assert bpy.context.preferences.edit.undo_steps == 32
        capacity_before_recovery = runtime.checkpoints.recovery_status()
        recovered_stages = []
        for _ in range(capacity_before_recovery["tracked_operation_count"]):
            step = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert step["snapshot_marker_verified"], step
            recovered_stages.append(step["tracked_agent_label"])
            protected_unchanged()
        assert datablock_names() == datablocks_before, (datablock_names(), datablocks_before)
        assert sorted(obj.name for obj in bpy.context.selected_objects) == initial_selection
        assert bpy.context.view_layer.objects.active.name == initial_active and bpy.context.mode == "OBJECT"
        captures["whole_build_recovered_protected"] = capture(target=brief["protected_object"])
        print("BLENDER_FIELD_SCANNER_OK " + json.dumps({"blender": bpy.app.version_string,
              "stage": "integrated_reference_workflow", "reference_asset_sha256": asset_hashes(), "dimensions": dimensions,
              "handle_clearance": clearance, "components": 12, "shell_topology": shell_after_slots,
              "shell_uv_metrics": shell_uv["metrics"], "shell_uv_overlap": shell_uv["overlap"],
              "glass_uv_metrics": glass_uv["metrics"], "glass_uv_overlap": glass_uv["overlap"],
              "display_density_policy": "Front-priority atlas; side/back density deliberately lower, not a uniform whole-asset atlas",
              "texture_file_sha256": {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in textures.items()},
              "logical_stages": stages, "structured_requests": request_count[0], "captures": captures,
              "visual_review_required": True, "uv_and_texture_workflow_verified": True,
              "partial_failure_recovery_verified": True, "face_attribute_failure_restoration_verified": True,
              "painted_readiness_accents_verified": True, "painted_display_pixels": paint["painted_pixels"],
              "grille_material_index": grille_material_index,
              "whole_build_checkpoint_id": checkpoint["checkpoint_id"],
              "recovery_capacity_before_staged_restore": capacity_before_recovery,
              "recovered_stage_labels": recovered_stages,
              "whole_build_recovery_verified": True,
              "full_artist_acceptance_verified": False, "project_saved": False,
              "user_preferences_saved": False, "status_checked": bool(status)}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1)
