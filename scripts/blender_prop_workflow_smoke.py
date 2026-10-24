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


def open_chain_state(name, limits=None):
    """Measure old geometry/attributes independently of bridge result metadata."""
    obj = bpy.data.objects[name]
    temporary = obj.mode != "EDIT"
    live = bmesh.new() if temporary else bmesh.from_edit_mesh(obj.data)
    if temporary:
        live.from_mesh(obj.data)
    try:
        for sequence in (live.verts, live.edges, live.faces):
            sequence.ensure_lookup_table()
            sequence.index_update()
        counts = {"vertices": len(live.verts), "edges": len(live.edges), "faces": len(live.faces)}
        limits = limits or counts
        deform = live.verts.layers.deform.active
        layers = list(live.loops.layers.uv.values())

        def uv_flags(loop, layer):
            if hasattr(loop, "uv_select_vert"):
                return bool(loop.uv_select_vert), bool(loop.uv_select_edge)
            return bool(loop[layer].select), bool(loop[layer].select_edge)

        return {
            "vertices": [(tuple(vertex.co), bool(vertex.select), bool(vertex.hide),
                sorted(vertex[deform].items()) if deform else [])
                for vertex in list(live.verts)[:limits["vertices"]]],
            "edges": [(tuple(vertex.index for vertex in edge.verts), bool(edge.select),
                bool(edge.hide), bool(edge.seam), bool(edge.smooth))
                for edge in list(live.edges)[:limits["edges"]]],
            "faces": [(tuple(vertex.index for vertex in face.verts), bool(face.select),
                bool(face.hide), bool(face.smooth), face.material_index,
                bool(face.uv_select) if hasattr(face, "uv_select") else None,
                [[(tuple(loop[layer].uv), bool(loop[layer].pin_uv), uv_flags(loop, layer)) for loop in face.loops]
                    for layer in layers]) for face in list(live.faces)[:limits["faces"]]],
            "uv_selection_valid": bool(live.uv_select_sync_valid) if hasattr(live, "uv_select_sync_valid") else None,
            "uv_names": [layer.name for layer in layers],
            "uv_roles": (obj.data.uv_layers.active_index,
                [(layer.name, bool(layer.active_render), bool(layer.active_clone)) for layer in obj.data.uv_layers]),
            "materials": [material.name if material else None for material in obj.data.materials],
            "groups": [(group.name, bool(group.lock_weight)) for group in obj.vertex_groups],
            "matrix": tuple(tuple(row) for row in obj.matrix_world),
        }, counts
    finally:
        if temporary:
            live.free()


def exercise_open_chains(runtime, grants, images):
    """Repair an explicit open seam, including failed publication and native undo."""
    from blender_codex_bridge.tools import mesh_chains

    name, protected_name = "Open Chain Repair", "Protected Open Chain"
    mesh = bpy.data.meshes.new("Open Chain Repair Data")
    positions = [(float(x), float(y), 0.) for y in (-1, 0, 1, 2) for x in (-1, 0, 1)]
    positions.extend([(1.5, -.5, 0.), (2., -.5, 0.), (1.75, 0., 0.)])
    old_faces = [(0, 1, 4, 3), (1, 2, 5, 4), (6, 7, 10, 9), (7, 8, 11, 10), (12, 13, 14)]
    mesh.from_pydata(positions, [], old_faces)
    fixture = bmesh.new()
    fixture.from_mesh(mesh)
    fixture.faces.index_update()
    for layer_name in ("Chain UV", "Chain Spare"):
        layer = fixture.loops.layers.uv.new(layer_name)
        for face in fixture.faces:
            face.material_index = face.index % 2
            face.smooth = face.index % 2 == 1
            if hasattr(face, "uv_select"):
                face.uv_select = face.index % 2 == 1
            for corner, loop in enumerate(face.loops):
                loop[layer].uv = ((loop.vert.co.x + 1.) / 3., (loop.vert.co.y + 1.) / 3.)
                loop[layer].pin_uv = corner == 0
                if hasattr(loop, "uv_select_vert"):
                    loop.uv_select_vert, loop.uv_select_edge = corner % 2 == 0, corner == 0
                else:
                    loop[layer].select, loop[layer].select_edge = corner % 2 == 0, corner == 0
    if hasattr(fixture, "uv_select_sync_valid"):
        fixture.uv_select_sync_valid = False
    fixture.to_mesh(mesh)
    fixture.free()
    mesh.uv_layers.active_index = 1
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.show_wire = obj.show_all_edges = True
    obj.vertex_groups.new(name="Keep Chain Weight").add(list(range(len(positions))), .25, "REPLACE")
    obj.vertex_groups.new(name="Keep Other Weight").add([1, 4, 7, 10, 13], .75, "REPLACE")
    material = bpy.data.materials.new("Shared Open Chain Checker")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    uv_map = nodes.new("ShaderNodeUVMap")
    uv_map.uv_map = "Chain UV"
    checker = nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = 6.
    checker.inputs["Color1"].default_value = (.04, .12, .2, 1.)
    checker.inputs["Color2"].default_value = (.6, .8, .9, 1.)
    links.new(uv_map.outputs["UV"], checker.inputs["Vector"])
    links.new(checker.outputs["Color"], nodes.get("Principled BSDF").inputs["Base Color"])
    mesh.materials.append(material)
    mesh.materials.append(material)
    protected = obj.copy()
    protected.data = mesh.copy()
    protected.name = protected_name
    protected.location.x = 5.
    bpy.context.scene.collection.objects.link(protected)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    protected.select_set(True)
    bpy.context.view_layer.objects.active = obj
    mesh.update()
    bpy.context.view_layer.update()

    def call(method, **params):
        return runtime.dispatch(method, {"object_name": name, **params})

    def stage(label, **evidence):
        print("OPEN_CHAIN_STAGE " + json.dumps({"stage": label, **evidence}, sort_keys=True), flush=True)

    def deny(method, expected, **params):
        try:
            call(method, **params)
        except BridgeError as error:
            assert error.code == expected, (method, expected, error.to_dict())
            # Keep only plain evidence across native Edit-session restoration.
            # A retained exception traceback can own stale BM/guard/RNA handles.
            evidence = json.loads(json.dumps(error.to_dict()))
            pending, seen = [error], set()
            while pending:
                current = pending.pop()
                if id(current) in seen:
                    continue
                seen.add(id(current))
                pending.extend(linked for linked in (current.__context__, current.__cause__) if linked is not None)
                current.__traceback__ = current.__context__ = current.__cause__ = None
            return evidence
        raise AssertionError("Expected open-chain rejection: " + method)

    def capture(shading, target=name):
        regions = [area.spaces.active.region_3d for area in bpy.context.screen.areas if area.type == "VIEW_3D"]
        previous = [(region.view_location.copy(), region.view_distance) for region in regions]
        try:
            for region in regions:
                region.view_location = bpy.data.objects[target].matrix_world @ Vector((.5, .5, 0.))
                region.view_distance = 5.
            for _attempt in range(2):
                result = runtime.dispatch("viewport.capture", {"object_name": target, "view": "top",
                    "shading": shading, "include_overlays": shading == "wireframe", "resolution": [640, 480]})
                assert result["source"] == "viewport_opengl"
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            return result["path"]
        finally:
            for region, (location, distance) in zip(regions, previous, strict=True):
                region.view_location, region.view_distance = location, distance

    def select_rails():
        call("selection.inspect")
        inspected = call("mesh.components_inspect", element_type="EDGE", max_items=256)
        assert not inspected["truncated"]
        pairs = [{3, 4}, {4, 5}, {6, 7}, {7, 8}]
        edge_indices = [edge["index"] for edge in inspected["items"] if set(edge["vertex_indices"]) in pairs]
        assert len(edge_indices) == 4
        selected = call("mesh.select_components", element_type="EDGE", indices=edge_indices)
        return {"selection_id": selected["selection"]["mesh_selection"]["selection_id"],
            "rail_a_start": 3, "rail_a_end": 5, "rail_b_start": 6, "rail_b_end": 8, "material_index": 0}

    def assert_protected(label):
        stage(label + ":protected_compare_begin")
        compared = runtime.dispatch("scene.compare", {"snapshot_id": protected_snapshot["snapshot_id"]})
        assert compared["coverage_complete"] and compared["status"] == "unchanged_within_scope"
        stage(label + ":protected_compare_complete")
        assert open_chain_state(protected_name)[0] == protected_state
        stage(label + ":protected_readback_complete")

    def recover_session(label):
        stage(label + ":mode_exit_begin", mode=bpy.context.mode)
        if bpy.context.mode != "OBJECT":
            call("context.set_mode", mode="OBJECT")
        stage(label + ":mode_exit_complete", mode=bpy.context.mode)
        stage(label + ":undo_begin")
        recovered = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert recovered["snapshot_marker_verified"] and recovered["recovered_scope"] == "mesh_edit_session"
        stage(label + ":undo_complete")
        stage(label + ":baseline_compare_begin")
        compared = runtime.dispatch("scene.compare", {"snapshot_id": baseline["snapshot_id"]})
        assert compared["coverage_complete"] and compared["status"] == "unchanged_within_scope"
        stage(label + ":baseline_compare_complete")
        assert open_chain_state(name) == (baseline_state, before_counts)
        assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active.name == name
        assert sorted(selected.name for selected in bpy.context.selected_objects) == [name, protected_name]
        assert_protected(label + ":recovered")

    baseline_state, before_counts = open_chain_state(name)
    protected_state = open_chain_state(protected_name)[0]
    baseline = runtime.dispatch("scene.snapshot", {"object_names": [name, protected_name]})
    protected_snapshot = runtime.dispatch("scene.snapshot", {"object_names": [protected_name]})
    images["open_chain_before_material"] = capture("material")
    images["open_chain_protected_before"] = capture("material", protected_name)
    call("context.set_mode", mode="EDIT")
    args = select_rails()
    selected_state, _ = open_chain_state(name)
    preview = call("mesh.bridge_chains_preview", **args)
    assert preview["rail_vertex_indices"] == [[3, 4, 5], [6, 7, 8]]
    assert preview["planned_faces"] == [[3, 4, 7, 6], [4, 5, 8, 7]]
    expected_counts = {"vertices": before_counts["vertices"], "edges": before_counts["edges"] + 3,
        "faces": before_counts["faces"] + 2}
    assert preview["expected_counts_after"] == expected_counts
    assert open_chain_state(name) == (selected_state, before_counts)
    images["open_chain_before_wire"] = capture("wireframe")
    apply = {**args, "expected_fingerprint": preview["fingerprint"]}
    grants[Permission.EDIT_MESH.value] = False
    try:
        assert call("mesh.bridge_chains_preview", **args)["fingerprint"] == preview["fingerprint"]
        deny("mesh.bridge_chains", "PERMISSION_DENIED", **apply)
    finally:
        grants[Permission.EDIT_MESH.value] = True
    runtime.state.set_emergency_stopped(True)
    try:
        deny("mesh.bridge_chains", "EMERGENCY_STOPPED", **apply)
    finally:
        runtime.state.set_emergency_stopped(False)
        runtime.state.set_paused(False)
    assert open_chain_state(name) == (selected_state, before_counts)
    live = bmesh.from_edit_mesh(bpy.data.objects[name].data)
    live.verts.ensure_lookup_table()
    original = live.verts[0].co.copy()
    live.verts[0].co.z = .125
    bmesh.update_edit_mesh(bpy.data.objects[name].data, loop_triangles=False, destructive=False)
    stale_state = open_chain_state(name)
    try:
        deny("mesh.bridge_chains", "INVALID_SELECTION", **apply)
        assert open_chain_state(name) == stale_state
    finally:
        live.verts[0].co = original
        bmesh.update_edit_mesh(bpy.data.objects[name].data, loop_triangles=False, destructive=False)
    assert open_chain_state(name) == (selected_state, before_counts)

    original_new_face = mesh_chains._new_face
    attempted = []

    def fail_second_face(bm, vertices):
        attempted.append(tuple(vertex.index for vertex in vertices))
        if len(attempted) == 2:
            raise RuntimeError("fixture open-chain second-face publication failure")
        return original_new_face(bm, vertices)

    mesh_chains._new_face = fail_second_face
    try:
        stage("fault:bridge_begin")
        error = deny("mesh.bridge_chains", "OPERATION_FAILED", **apply)
        assert len(attempted) == 2
        assert error["context"].get("possible_mutation") and error["context"].get("verification_required")
        assert error["context"].get("rollback_verified") is False
        sync = error["context"]["derived_cache_sync"]
        assert sync["verified_syncs"] == sync["last_verified_face_count"] == 1
        assert sync["normal_update_calls_started"] == sync["normal_update_calls_returned"] == 1
        assert sync["edit_mesh_update_calls_started"] == sync["edit_mesh_update_calls_returned"] == 1
        assert sync["current_topology_sync_verified"] is False
        stage("fault:bridge_returned", derived_cache_sync=sync)
        partial_state, partial_counts = open_chain_state(name, before_counts)
        assert partial_state == selected_state
        assert partial_counts == {"vertices": before_counts["vertices"], "edges": before_counts["edges"] + 2,
            "faces": before_counts["faces"] + 1}
    finally:
        mesh_chains._new_face = original_new_face
    stage("fault:partial_readback_complete")
    assert_protected("fault")
    recover_session("fault")

    call("context.set_mode", mode="EDIT")
    args = select_rails()
    selected_state, _ = open_chain_state(name)
    preview = call("mesh.bridge_chains_preview", **args)
    stage("success:bridge_begin")
    result = call("mesh.bridge_chains", expected_fingerprint=preview["fingerprint"], **args)
    assert result["created_faces"] == 2 and result["verification"] and result["preservation"]
    assert result["derived_cache_sync"]["verified_syncs"] == 2
    assert result["derived_cache_sync"]["last_verified_face_count"] == 2
    assert result["derived_cache_sync"]["current_topology_sync_verified"] is True
    stage("success:bridge_returned", derived_cache_sync=result["derived_cache_sync"])
    preserved, observed_counts = open_chain_state(name, before_counts)
    assert observed_counts == expected_counts and preserved == selected_state
    live = bmesh.from_edit_mesh(bpy.data.objects[name].data)
    live.faces.ensure_lookup_table()
    live.faces.index_update()
    assert [tuple(vertex.index for vertex in face.verts) for face in list(live.faces)[before_counts["faces"]:]] == [
        (3, 4, 7, 6), (4, 5, 8, 7)]
    for face in list(live.faces)[before_counts["faces"]:]:
        assert face.material_index == 0 and face.calc_area() > 0.
        for loop in face.loops:
            for layer in live.loops.layers.uv.values():
                assert tuple(loop[layer].uv) == (0., 0.) and not loop[layer].pin_uv
    assert_protected("success")
    stage("success:after_wire_capture_begin")
    images["open_chain_after_wire"] = capture("wireframe")
    stage("success:after_wire_capture_complete")
    stage("success:mode_exit_for_material_begin")
    call("context.set_mode", mode="OBJECT")
    stage("success:mode_exit_for_material_complete")
    images["open_chain_after_material"] = capture("material")
    images["open_chain_protected_after"] = capture("material", protected_name)
    stage("success:after_material_captures_complete")
    assert_protected("success:after_captures")
    recover_session("success")
    images["open_chain_recovered_wire"] = capture("wireframe")
    stage("success:recovered_capture_complete")


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
        mesh_quality = call("mesh.analyze")
        assert mesh_quality["analysis_complete"] and not sum(mesh_quality["intersections"]["triangle_pairs"].values())
        assert not mesh_quality["topology"]["counts"].get("inconsistent_orientation_edges", 0)
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
        initial_quality = call("uv.analyze", uv_layer="Repair UV", texture_resolution=[1024, 1024])
        assert initial_quality["analysis_complete"] and initial_quality["metrics"]["near_zero_uv_triangles"] > 0
        unwrapped = call("uv.unwrap", uv_layer="Repair UV", create_if_missing=False, margin=.02)
        assert unwrapped["verification"]["status"] == "basic_checks_passed"
        call("uv.pack_islands", uv_layer="Repair UV", margin=.02)
        uv = call("uv.inspect", uv_layer="Repair UV", include_coordinates=True, max_coordinates=256)
        assert uv["analysis"]["island_count"] == 6 and not uv["analysis"]["quality"]["degenerate_face_count"]
        assert not uv["coordinates"]["truncated"]
        assert all(-1e-5 <= value <= 1.00001 for item in uv["coordinates"]["items"] for value in item["uv"])
        images["uv_after"] = call("uv.capture_layout", uv_layer="Repair UV")["path"]
        final_quality = call("uv.analyze", uv_layer="Repair UV", texture_resolution=[1024, 1024], anisotropy_warning=1.01)
        assert final_quality["analysis_complete"] and final_quality["overlap"]["positive_triangle_pairs"] == 0
        assert final_quality["verification"]["status"] == "numeric_checks_passed"
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
        exercise_open_chains(runtime, grants, images)
        blender_codex_bridge.unregister()
        print("BLENDER_PROP_WORKFLOW_OK " + json.dumps({
            "blender": bpy.app.version_string, "connected_prop_bridge_cut_unwrap_finish": True,
            "protected_data_and_source_uv_verified": True, "six_non_degenerate_islands": True,
            "five_step_recipe_recovery_verified": True, "wire_unequal_and_open_strip_cases_verified": True,
            "explicit_open_chain_preview_bridge_and_preservation_verified": True,
            "open_chain_stale_permission_stop_and_mid_face_failure_verified": True,
            "open_chain_actual_native_edit_session_recovery_verified": True,
            "captures": images, "visual_review_required": True, "project_saved": False,
        }), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
