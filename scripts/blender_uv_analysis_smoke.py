"""Diagnose and refine deliberate UV defects with native tessellation and recovery."""

from __future__ import annotations

import json
import math
import sys
import time
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


def fixture(name, vertices, faces, uv_values):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    for layer_name in ("Work", "Other"):
        layer = bm.loops.layers.uv.new(layer_name)
        for index, face in enumerate(bm.faces):
            for loop, uv in zip(face.loops, uv_values[index], strict=True):
                loop[layer].uv = uv
    bm.to_mesh(mesh)
    bm.free()
    mesh.uv_layers.active_index = 1
    return mesh


def run():
    try:
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {p.value: True for p in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        for toolset in ("uv", "interaction", "objects"):
            runtime.registry.enable_toolset(toolset)
        positions = [(x + face * 2, y, 0) for face in range(4) for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
        faces = [tuple(range(face * 4, face * 4 + 4)) for face in range(4)]
        square = [(0, 0), (1, 0), (1, 1), (0, 1)]
        values = [square, square, [(4 + x * 4, y) for x, y in square], [(12 - x, y) for x, y in square]]
        obj = bpy.data.objects["Cube"]
        obj.name = "UV Quality Prop"
        obj.data = fixture("UV Defects", positions, faces, values)
        protected = obj.copy()
        protected.data = obj.data.copy()
        protected.name = "Protected Quality Prop"
        protected.location.y = 3
        bpy.context.scene.collection.objects.link(protected)
        protected.select_set(True)
        selected_before = sorted(item.name for item in bpy.context.selected_objects)
        # Concave triangulation must follow geometry, not a fan from UV corner zero.
        concave_points = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)]
        concave = bpy.data.objects.new("Concave Quality", fixture("Concave", concave_points, [tuple(range(6))],
            [[(x / 2, y / 2) for x, y, _z in concave_points]]))
        bpy.context.scene.collection.objects.link(concave)
        folded = bpy.data.objects.new("Folded Quality", fixture("Folded", positions[:4], [(0, 1, 2, 3)],
            [[(0, 0), (1, 1), (0, 1), (1, 0)]]))
        bpy.context.scene.collection.objects.link(folded)
        invalid = bpy.data.objects.new("Invalid Quality", fixture("Invalid", positions[:4], [(0, 1, 2, 3)],
            [[(float("nan"), 0), (1, 0), (1, 1), (0, 1)]]))
        bpy.context.scene.collection.objects.link(invalid)
        shared_owner = bpy.data.objects.new("Shared Quality Owner", fixture("Shared Quality", positions[:4], [(0, 1, 2, 3)], [square]))
        bpy.context.scene.collection.objects.link(shared_owner)
        shared_alias = shared_owner.copy()
        shared_alias.name = "Shared Quality Alias"
        shared_alias.scale.x = 2
        bpy.context.scene.collection.objects.link(shared_alias)
        side = 64
        grid_positions = [(x / side, y / side, 0) for y in range(side + 1) for x in range(side + 1)]
        grid_faces = [(y * (side + 1) + x, y * (side + 1) + x + 1,
                       (y + 1) * (side + 1) + x + 1, (y + 1) * (side + 1) + x)
                      for y in range(side) for x in range(side)]
        grid_uvs = [[grid_positions[index][:2] for index in face] for face in grid_faces]
        grid = bpy.data.objects.new("Grid Quality", fixture("Grid Quality", grid_positions, grid_faces, grid_uvs))
        bpy.context.scene.collection.objects.link(grid)

        def analyze(name="UV Quality Prop", **params):
            return runtime.dispatch("uv.analyze", {"object_name": name, "uv_layer": "Work", **params})

        def compare(snapshot):
            result = runtime.dispatch("scene.compare", {"snapshot_id": snapshot["snapshot_id"]})
            assert result["coverage_complete"] and result["status"] == "unchanged_within_scope"

        def layout():
            return runtime.dispatch("uv.capture_layout", {"object_name": "UV Quality Prop", "uv_layer": "Work", "view": "FIT"})["path"]

        def other_coordinates():
            rows = runtime.dispatch("uv.inspect", {"object_name": "UV Quality Prop", "uv_layer": "Other",
                "include_coordinates": True, "max_coordinates": 256})["coordinates"]
            assert not rows["truncated"]
            return [(item["face_index"], item["corner_index"], item["uv"], item["pinned"]) for item in rows["items"]]

        baseline = runtime.dispatch("scene.snapshot", {"object_names": ["UV Quality Prop", "Protected Quality Prop"]})
        original_other = other_coordinates()
        guard = runtime.dispatch("scene.snapshot", {"object_names": ["Protected Quality Prop"]})
        grants[Permission.EDIT_MESH.value] = False
        for permission in (Permission.EXECUTE_PYTHON, Permission.DELETE_OBJECTS, Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT):
            grants[permission.value] = False
        grants[Permission.INSPECT_SCENE.value] = False
        try:
            analyze()
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Analysis bypassed inspection permission")
        grants[Permission.INSPECT_SCENE.value] = True
        before = analyze(texture_resolution=[1024, 1024], anisotropy_warning=2.)
        assert before["analysis_complete"] and before["overlap"]["face_pairs"] == 1
        assert before["overlap"]["summed_pairwise_uv_area"] == 1
        assert before["metrics"]["mirrored_triangles"] == 2
        assert abs(before["metrics"]["max_pixel_anisotropy"] - 4) < 1e-6
        assert before["verification"]["status"] == "needs_review"
        partial = analyze(max_pair_tests=1)
        assert not partial["analysis_complete"] and partial["verification"]["status"] == "incomplete"
        assert not partial["overlap"]["complete"]
        truncated = analyze(max_triangles=1)
        assert not truncated["analysis_complete"] and truncated["metrics"] is None
        details = analyze(max_reports=1)
        assert details["analysis_complete"] and details["face_reports_truncated"] and len(details["face_reports"]) == 1
        region = analyze(face_indices=[2], anisotropy_warning=2.)
        assert region["scoped_face_count"] == 1 and region["overlap"]["positive_triangle_pairs"] == 0
        assert abs(region["metrics"]["density_min"] - 2048) < 1e-6
        for stopped in ("paused", "emergency_stopped"):
            getattr(runtime.state, f"set_{stopped}")(True)
            assert analyze()["analysis_complete"]
            getattr(runtime.state, f"set_{stopped}")(False)
            runtime.state.set_paused(False)
        concave_result = analyze("Concave Quality", texture_resolution=[1024, 1024])
        assert concave_result["requested_triangle_count"] == 4 and concave_result["analysis_complete"]
        assert not concave_result["overlap"]["positive_triangle_pairs"]
        assert abs(concave_result["face_reports"][0]["world_area"] - 3) < 1e-6
        assert abs(concave_result["metrics"]["density_min"] - 512) < 1e-6
        rectangle = analyze("Concave Quality", texture_resolution=[2048, 1024])
        assert abs(rectangle["metrics"]["max_pixel_anisotropy"] - 2) < 1e-6
        assert abs(rectangle["metrics"]["density_min"] - 512 * math.sqrt(2)) < 1e-6
        folds = analyze("Folded Quality")
        assert folds["metrics"]["folded_faces"] == 1 and folds["overlap"]["examples"][0]["same_face"]
        invalid_result = analyze("Invalid Quality")
        assert not invalid_result["analysis_complete"] and invalid_result["metrics"]["invalid_triangles"]
        json.dumps(invalid_result, allow_nan=False)
        started = time.perf_counter()
        grid_result = analyze("Grid Quality", texture_resolution=[1024, 1024])
        grid_seconds = time.perf_counter() - started
        assert grid_result["analysis_complete"] and grid_result["requested_triangle_count"] == 8192
        assert grid_result["verification"]["status"] == "numeric_checks_passed"
        assert not grid_result["overlap"]["positive_triangle_pairs"] and grid_result["face_reports_truncated"]
        compare(baseline)
        assert bpy.data.objects["UV Quality Prop"].data.uv_layers.active.name == "Other"
        images = {"before_layout": layout()}
        runtime.dispatch("checkpoint.create", {"description": "Refine measured UV defects"})
        grants[Permission.EDIT_MESH.value] = True
        runtime.dispatch("context.set_mode", {"object_name": "UV Quality Prop", "mode": "EDIT"})
        for face, scale, offset in ((0, [.46, .46], [.02, .02]), (1, [.46, .46], [.52, .02]),
                                    (2, [.115, .46], [-.44, .52]), (3, [-.46, .46], [6.04, .52])):
            selection = runtime.dispatch("mesh.select_components", {"object_name": "UV Quality Prop", "element_type": "FACE", "indices": [face]})
            reference = selection["selection"]["mesh_selection"]["selection_id"]
            scoped = analyze(selection_id=reference, face_indices=[face])
            assert scoped["scoped_face_count"] == 1
            runtime.dispatch("uv.transform", {"object_name": "UV Quality Prop", "uv_layer": "Work", "selection_id": reference,
                "scale": scale, "offset": offset})
        after = analyze(texture_resolution=[1024, 1024], density_target=471.04, density_tolerance=1e-5, anisotropy_warning=1.01)
        assert after["analysis_complete"] and after["verification"]["status"] == "numeric_checks_passed"
        assert not after["overlap"]["positive_triangle_pairs"] and not after["metrics"]["mirrored_triangles"]
        assert after["metrics"]["max_pixel_anisotropy"] < 1.00001
        assert abs(after["metrics"]["density_min"] - 471.04) < .001
        assert abs(after["metrics"]["density_max"] - 471.04) < .001
        images["after_layout"] = layout()
        runtime.dispatch("context.set_mode", {"object_name": "UV Quality Prop", "mode": "OBJECT"})
        object_result = analyze(texture_resolution=[1024, 1024], density_target=471.04, density_tolerance=1e-5)
        assert object_result["verification"]["status"] == "numeric_checks_passed"
        assert bpy.data.objects["UV Quality Prop"].data.uv_layers.active.name == "Other"
        assert other_coordinates() == original_other
        compare(guard)
        refined = runtime.dispatch("scene.snapshot", {"object_names": ["UV Quality Prop", "Protected Quality Prop"]})
        # A transform assigned in this same timer must be reflected in density, not stale matrix_world.
        runtime.dispatch("transform.set", {"object_name": "UV Quality Prop", "scale": [2, 1, 1]})
        scaled = analyze(face_indices=[0], texture_resolution=[1024, 1024])
        assert abs(scaled["metrics"]["density_min"] - 471.04 / math.sqrt(2)) < .001
        assert abs(scaled["metrics"]["max_pixel_anisotropy"] - 2) < .00001
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert abs(analyze()["metrics"]["density_min"] - 471.04) < .001
        compare(refined)
        recovered = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert recovered["recovered_scope"] == "mesh_edit_session" and recovered["snapshot_marker_verified"]
        compare(baseline)
        assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active.name == "UV Quality Prop"
        assert sorted(item.name for item in bpy.context.selected_objects) == selected_before
        images["recovered_layout"] = layout()
        # Emulate a human's unflushed edit on a shared mesh; this is fixture setup, not a mutation API.
        runtime.dispatch("context.set_mode", {"object_name": "Shared Quality Owner", "mode": "EDIT"})
        shared_mesh = bpy.data.objects["Shared Quality Owner"].data
        live = bmesh.from_edit_mesh(shared_mesh)
        live.loops.layers.uv.new("Live Only")
        work, live_only = live.loops.layers.uv["Work"], live.loops.layers.uv["Live Only"]
        for face in live.faces:
            for loop in face.loops:
                uv = tuple(float(value) * .5 for value in loop[work].uv)
                loop[work].uv = uv
                loop[live_only].uv = uv
        active_map = live.loops.layers.uv.active.name
        assert bpy.data.objects["Shared Quality Alias"].mode == "OBJECT" and shared_mesh.is_editmode
        alias_result = analyze("Shared Quality Alias", texture_resolution=[1024, 1024])
        assert alias_result["mesh_data_state"] == "LIVE_EDIT_BMESH" and alias_result["analysis_complete"]
        assert abs(alias_result["metrics"]["density_min"] - 512 / math.sqrt(2)) < .001
        owner_result = analyze("Shared Quality Owner", texture_resolution=[1024, 1024])
        assert abs(owner_result["metrics"]["density_min"] - 512) < .001
        alias_uv = runtime.dispatch("uv.inspect", {"object_name": "Shared Quality Alias", "uv_layer": "Live Only",
            "include_coordinates": True, "max_coordinates": 256})
        assert alias_uv["mesh_data_state"] == "LIVE_EDIT_BMESH" and alias_uv["uv_layer_count"] == 3
        assert max(value for item in alias_uv["coordinates"]["items"] for value in item["uv"]) == .5
        alias_image = runtime.dispatch("uv.capture_layout", {"object_name": "Shared Quality Alias", "uv_layer": "Live Only"})
        assert alias_image["mesh_data_state"] == "LIVE_EDIT_BMESH"
        images["live_alias_layout"] = alias_image["path"]
        assert len(live.faces) == 1 and live.loops.layers.uv.active.name == active_map
        runtime.dispatch("context.set_mode", {"object_name": "Shared Quality Owner", "mode": "OBJECT"})
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert "Live Only" not in bpy.data.objects["Shared Quality Owner"].data.uv_layers
        assert abs(analyze("Shared Quality Owner")["metrics"]["density_min"] - 1024) < .001
        compare(baseline)
        assert sorted(item.name for item in bpy.context.selected_objects) == selected_before
        blender_codex_bridge.unregister()
        print("BLENDER_UV_ANALYSIS_OK " + json.dumps({
            "blender": bpy.app.version_string, "known_overlap_stretch_mirror_detected": True,
            "native_concave_and_folded_tessellation_verified": True, "budgets_are_incomplete": True,
            "declared_resolution_and_fresh_world_scale_verified": True, "refinement_and_recovery_verified": True,
            "protected_state_and_active_layer_preserved": True, "captures": images,
            "clean_grid_triangles": 8192, "clean_grid_seconds": grid_seconds,
            "clean_grid_pair_tests": grid_result["overlap"]["pair_tests"],
            "object_mode_shared_alias_live_uv_reads_verified": True,
            "visual_review_required": True, "project_saved": False,
        }), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
