"""Repair a disconnected prop, add loops, unwrap, isolate its finish, and recover."""

from __future__ import annotations

import json
import math
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
        grants = {p.value: True for p in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        for toolset in ("interaction", "mesh", "uv", "materials", "nodes"):
            runtime.registry.enable_toolset(toolset)
        obj = bpy.data.objects["Cube"]
        obj.name = "Repair Prop"
        mesh = bpy.data.meshes.new("Disconnected Prop")
        vertices = [(x, y, z) for z in (-1., -.25, .25, 1.) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        faces = [(base + i, base + (i + 1) % 4, base + (i + 1) % 4 + 4, base + i + 4)
                 for base in (0, 8) for i in range(4)] + [(3, 2, 1, 0), (12, 13, 14, 15)]
        mesh.from_pydata(vertices, [], faces)
        fixture = bmesh.new()
        fixture.from_mesh(mesh)
        layer = fixture.loops.layers.uv.new("Source UV")
        for face in fixture.faces:
            for loop in face.loops:
                co = loop.vert.co
                loop[layer].uv = (.5 + co.x * .1 + co.z * .2, .5 + co.y * .1 + co.z * .2)
        fixture.to_mesh(mesh)
        fixture.free()
        obj.data = mesh
        obj.vertex_groups.new(name="Keep Weight").add(list(range(16)), .25, "REPLACE")
        material = bpy.data.materials.new("Shared Prop")
        material.use_nodes = True
        tree = material.node_tree
        mapping = tree.nodes.new("ShaderNodeUVMap")
        mapping.uv_map = "Repair UV"
        checker = tree.nodes.new("ShaderNodeTexChecker")
        checker.name = "Prop Checker"
        checker.inputs["Scale"].default_value = 6
        tree.links.new(mapping.outputs["UV"], checker.inputs["Vector"])
        tree.links.new(checker.outputs["Color"], tree.nodes.get("Principled BSDF").inputs["Base Color"])
        mesh.materials.append(material)
        protected = obj.copy()
        protected.data = mesh.copy()
        protected.name = "Protected Prop"
        protected.location.x = 4
        bpy.context.scene.collection.objects.link(protected)
        protected.select_set(True)
        selected_before = sorted(o.name for o in bpy.context.selected_objects)
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                region = area.spaces.active.region_3d
                region.view_location = (0, 0, 0)
                region.view_rotation = Vector((5, -6, 4)).to_track_quat("Z", "Y")
                region.view_distance = 7

        def call(method, **params):
            return runtime.dispatch(method, {"object_name": "Repair Prop", **params})

        def denied(method, code, **params):
            try:
                call(method, **params)
            except BridgeError as error:
                assert error.code == code, (method, code, error.code)
                return
            raise AssertionError(f"{method} unexpectedly succeeded")

        def page(kind):
            result = call("mesh.components_inspect", element_type=kind, max_items=256)
            assert not result["truncated"]
            return result["items"]

        def select(kind, indices):
            result = call("mesh.select_components", element_type=kind, indices=indices)
            return result["selection"]["mesh_selection"]["selection_id"]

        def capture(shading, name="Repair Prop"):
            regions = [area.spaces.active.region_3d for area in bpy.context.screen.areas if area.type == "VIEW_3D"]
            previous = [region.view_location.copy() for region in regions]
            try:
                for region in regions:
                    region.view_location = bpy.data.objects[name].matrix_world.translation
                return runtime.dispatch("viewport.capture", {"object_name": name, "view": "current",
                    "shading": shading, "include_overlays": False, "resolution": [640, 480]})["path"]
            finally:
                for region, location in zip(regions, previous, strict=True):
                    region.view_location = location

        baseline = runtime.dispatch("scene.snapshot", {"object_names": ["Repair Prop", "Protected Prop"]})
        guard = runtime.dispatch("scene.snapshot", {"object_names": ["Protected Prop"]})
        images = {"before_wire": capture("wireframe"), "protected_before": capture("material", "Protected Prop")}
        runtime.dispatch("checkpoint.create", {"description": "Repair / unwrap / finish prop"})
        for permission in (Permission.EXECUTE_PYTHON, Permission.DELETE_OBJECTS,
                           Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT):
            grants[permission.value] = False
        call("uv.layer_create", new_name="Repair UV", copy_from="Source UV")
        call("context.set_mode", mode="EDIT")
        edge_items = page("EDGE")
        gap_edges = [edge["index"] for edge in edge_items if abs(abs(edge["center_local"][2]) - .25) < 1e-6]
        assert len(gap_edges) == 8
        reference = select("EDGE", gap_edges)
        grants[Permission.EDIT_MESH.value] = False
        denied("mesh.bridge_loops", "PERMISSION_DENIED", selection_id=reference)
        grants[Permission.EDIT_MESH.value] = True
        bridged = call("mesh.bridge_loops", selection_id=reference)
        assert bridged["created_faces"] == 4 and bridged["face_policy"] == "QUADS"
        denied("mesh.bridge_loops", "INVALID_SELECTION", selection_id=reference)
        edge_items = page("EDGE")
        seed = next(edge["index"] for edge in edge_items if abs(edge["center_local"][2]) < 1e-6)
        reference = select("EDGE", [seed])
        preview = call("mesh.edge_ring_inspect", seed_edge_index=seed, selection_id=reference, max_items=2)
        assert preview["closed"] and preview["ring_edge_count"] == preview["crossed_quad_count"] == 4
        assert preview["truncated"] and preview["next_offset"] == 2
        remainder = call("mesh.edge_ring_inspect", seed_edge_index=seed, selection_id=reference, offset=2)
        assert len(remainder["items"]) == 2 and not remainder["truncated"]
        grants[Permission.EDIT_MESH.value] = False
        call("mesh.edge_ring_inspect", seed_edge_index=seed, selection_id=reference)
        denied("mesh.loop_cut", "PERMISSION_DENIED", seed_edge_index=seed, selection_id=reference)
        grants[Permission.EDIT_MESH.value] = True
        cut = call("mesh.loop_cut", seed_edge_index=seed, selection_id=reference)
        assert cut["mesh_counts_after"] == {"vertices": 20, "edges": 36, "faces": 18}
        denied("mesh.loop_cut", "INVALID_SELECTION", seed_edge_index=seed, selection_id=reference)
        vertices_after, edges_after, faces_after = page("VERT"), page("EDGE"), page("FACE")
        assert sum(abs(v["center_local"][2]) < 1e-6 for v in vertices_after) == 4
        seam_edges = []
        for edge in edges_after:
            owners = [face for face in faces_after if set(edge["vertex_indices"]).issubset(face["vertex_indices"])]
            assert len(owners) == 2
            if Vector(owners[0]["normal_local"]).dot(Vector(owners[1]["normal_local"])) < .99:
                seam_edges.append(edge["index"])
        call("mesh.mark_seams", selection_id=select("EDGE", seam_edges))
        select("FACE", [face["index"] for face in faces_after])
        grants[Permission.CAPTURE_VIEWPORT.value] = False
        denied("uv.capture_layout", "PERMISSION_DENIED", uv_layer="Repair UV")
        grants[Permission.CAPTURE_VIEWPORT.value] = True
        images["uv_before"] = call("uv.capture_layout", uv_layer="Repair UV")["path"]
        unwrapped = call("uv.unwrap", uv_layer="Repair UV", create_if_missing=False, margin=.02)
        assert unwrapped["verification"]["status"] == "basic_checks_passed"
        call("uv.pack_islands", uv_layer="Repair UV", margin=.02)
        uv = call("uv.inspect", uv_layer="Repair UV", include_coordinates=True, max_coordinates=256)
        assert uv["analysis"]["island_count"] == 6 and not uv["analysis"]["quality"]["degenerate_face_count"]
        assert not uv["coordinates"]["truncated"]
        assert all(-1e-5 <= value <= 1.00001 for item in uv["coordinates"]["items"] for value in item["uv"])
        images["uv_after"] = call("uv.capture_layout", uv_layer="Repair UV")["path"]
        # The original map must retain old/interpolated corner values; new bridge faces start at zero.
        edit = bmesh.from_edit_mesh(bpy.data.objects["Repair Prop"].data)
        source = edit.loops.layers.uv["Source UV"]
        for face in edit.faces:
            middle = abs(face.calc_center_median().z) < .25 - 1e-6
            for loop in face.loops:
                co = loop.vert.co
                expected = Vector((0, 0) if middle else (.5 + co.x * .1 + co.z * .2, .5 + co.y * .1 + co.z * .2))
                assert (loop[source].uv - expected).length < 1e-6
        call("context.set_mode", mode="OBJECT")
        repaired = bpy.data.objects["Repair Prop"]
        assert all(abs(repaired.vertex_groups[0].weight(v.index) - .25) < 1e-6 for v in repaired.data.vertices)
        assert all(abs(value - 2) < 1e-6 for value in repaired.dimensions)
        call("material.copy_for_object", slot_index=0, new_name="Repaired Finish")
        runtime.dispatch("material.set_principled", {"material_name": "Repaired Finish", "roughness": .28, "metallic": .35})
        runtime.dispatch("nodes.set_input", {"material_name": "Repaired Finish", "node_name": "Prop Checker",
            "socket_name": "Color2", "value": [.03, .3, .65, 1]})
        assert bpy.data.objects["Repair Prop"].material_slots[0].material.name == "Repaired Finish"
        assert bpy.data.objects["Protected Prop"].material_slots[0].material.name == "Shared Prop"
        protected_result = runtime.dispatch("scene.compare", {"snapshot_id": guard["snapshot_id"]})
        assert protected_result["coverage_complete"] and protected_result["status"] == "unchanged_within_scope"
        images["after_wire"] = capture("wireframe")
        images["after_material"] = capture("material")
        images["protected_after"] = capture("material", "Protected Prop")
        scopes = []
        for _ in range(5):
            recovered = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
            assert recovered["snapshot_marker_verified"]
            scopes.append(recovered["recovered_scope"])
        assert scopes == ["operation", "operation", "operation", "mesh_edit_session", "operation"]
        comparison = runtime.dispatch("scene.compare", {"snapshot_id": baseline["snapshot_id"]})
        assert comparison["coverage_complete"] and comparison["status"] == "unchanged_within_scope"
        assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active.name == "Repair Prop"
        assert sorted(o.name for o in bpy.context.selected_objects) == selected_before
        images["recovered_wire"] = capture("wireframe")
        # Also exercise wire-loop and unequal-loop bridging, and a two-cut open quad strip.
        for name, sizes in (("Unequal Wire", (3, 5)), ("Equal Wire", (4, 4))):
            fixture_mesh = bpy.data.meshes.new(name)
            positions, fixture_edges = [], []
            for z, count in enumerate(sizes):
                offset = len(positions)
                positions.extend((math.cos(i * math.tau / count), math.sin(i * math.tau / count), z) for i in range(count))
                fixture_edges.extend((offset + i, offset + (i + 1) % count) for i in range(count))
            fixture_mesh.from_pydata(positions, fixture_edges, [])
            fixture_object = bpy.data.objects.new(name, fixture_mesh)
            bpy.context.scene.collection.objects.link(fixture_object)
            runtime.dispatch("context.set_mode", {"object_name": name, "mode": "EDIT"})
            selection = runtime.dispatch("mesh.select_components", {"object_name": name, "element_type": "EDGE", "indices": list(range(sum(sizes)))})
            if sizes[0] != sizes[1]:
                try:
                    runtime.dispatch("mesh.bridge_loops", {"object_name": name, "selection_id": selection["selection"]["mesh_selection"]["selection_id"], "twist_offset": 1})
                except BridgeError as error:
                    assert error.code == "NOT_IMPLEMENTED"
                else:
                    raise AssertionError("Ignored unequal-loop twist was reported as supported")
            result = runtime.dispatch("mesh.bridge_loops", {"object_name": name, "selection_id": selection["selection"]["mesh_selection"]["selection_id"]})
            assert result["created_faces"] == (sizes[0] if sizes[0] == sizes[1] else sum(sizes))
            runtime.dispatch("context.set_mode", {"object_name": name, "mode": "OBJECT"})
            if sizes[0] != sizes[1]:
                assert all(len(face.vertices) == 3 for face in fixture_object.data.polygons)
                images["unequal_wire_bridge"] = capture("wireframe", name)
            else:
                signature = sorted(tuple(sorted(face.vertices)) for face in bpy.data.objects[name].data.polygons)
                runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
                runtime.dispatch("context.set_mode", {"object_name": name, "mode": "EDIT"})
                selection = runtime.dispatch("mesh.select_components", {"object_name": name, "element_type": "EDGE", "indices": list(range(8))})
                runtime.dispatch("mesh.bridge_loops", {"object_name": name, "selection_id": selection["selection"]["mesh_selection"]["selection_id"], "twist_offset": 1})
                runtime.dispatch("context.set_mode", {"object_name": name, "mode": "OBJECT"})
                assert sorted(tuple(sorted(face.vertices)) for face in bpy.data.objects[name].data.polygons) != signature
                images["equal_wire_twist"] = capture("wireframe", name)
        strip_mesh = bpy.data.meshes.new("Open Strip")
        strip_mesh.from_pydata([(x, y, 0) for y in (0, 1) for x in (0, 1, 2)], [], [(0, 1, 4, 3), (1, 2, 5, 4)])
        strip = bpy.data.objects.new("Open Strip", strip_mesh)
        bpy.context.scene.collection.objects.link(strip)
        runtime.dispatch("context.set_mode", {"object_name": strip.name, "mode": "EDIT"})
        edge = next(edge.index for edge in bmesh.from_edit_mesh(strip_mesh).edges if len(edge.link_faces) == 2)
        selection = runtime.dispatch("mesh.select_components", {"object_name": strip.name, "element_type": "EDGE", "indices": [edge]})
        reference = selection["selection"]["mesh_selection"]["selection_id"]
        preview = runtime.dispatch("mesh.edge_ring_inspect", {"object_name": strip.name, "seed_edge_index": edge, "selection_id": reference, "cuts": 2})
        assert not preview["closed"] and preview["crossed_quad_count"] == 2
        result = runtime.dispatch("mesh.loop_cut", {"object_name": strip.name, "seed_edge_index": edge, "selection_id": reference, "cuts": 2})
        assert result["mesh_counts_after"] == {"vertices": 12, "edges": 17, "faces": 6}
        runtime.dispatch("context.set_mode", {"object_name": strip.name, "mode": "OBJECT"})
        added = [v.co for v in strip_mesh.vertices if 1e-6 < v.co.y < 1 - 1e-6]
        assert len(added) == 6 and all(abs(v.y - 1 / 3) < 1e-6 or abs(v.y - 2 / 3) < 1e-6 for v in added)
        blender_codex_bridge.unregister()
        print("BLENDER_PROP_WORKFLOW_OK " + json.dumps({
            "blender": bpy.app.version_string, "connected_prop_bridge_cut_unwrap_finish": True,
            "protected_data_and_source_uv_verified": True, "six_non_degenerate_islands": True,
            "five_step_recipe_recovery_verified": True, "wire_unequal_and_open_strip_cases_verified": True,
            "captures": images, "visual_review_required": True, "project_saved": False,
        }), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
