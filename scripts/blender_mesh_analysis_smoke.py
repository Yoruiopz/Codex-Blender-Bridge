"""Native mesh-quality diagnosis, winding repair, preservation and snapshot recovery."""

from __future__ import annotations

import json
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


def fixture(name, vertices, faces, edges=()):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, edges, faces)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def run():
    try:
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {p.value: True for p in Permission}
        runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
        for toolset in ("mesh", "interaction", "objects"):
            runtime.registry.enable_toolset(toolset)
        protected = bpy.data.objects["Cube"].copy()
        protected.name = "Protected Mesh"
        protected.data = protected.data.copy()
        bpy.context.scene.collection.objects.link(protected)
        protected.location.y = 4
        bm = bmesh.new()
        bm.from_mesh(bpy.data.objects["Cube"].data)
        bm.faces.ensure_lookup_table()
        bm.faces[0].normal_flip()
        bm.to_mesh(bpy.data.objects["Cube"].data)
        bm.free()
        crossing = fixture("Crossing", [(0, 0, 0), (1, 0, 0), (0, 1, 0),
            (.5, -.5, -1), (.5, 1.5, -1), (.5, .5, 1)], [(0, 1, 2), (3, 4, 5)])
        alias = crossing.copy()
        alias.name = "Linked Crossing"
        alias.scale.x = 2
        alias.scale.y = 2
        bpy.context.scene.collection.objects.link(alias)
        fixture("Stacked", [(0, 0, 0), (1, 0, 0), (0, 1, 0)] * 2, [(0, 1, 2), (3, 4, 5)])
        fixture("Tiny Stacked", [(0, 0, 0), (1e-8, 0, 0), (0, 1e-8, 0)] * 2, [(0, 1, 2), (3, 4, 5)])
        fixture("Nonmanifold", [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)],
                [(0, 1, 2), (1, 0, 3), (0, 1, 4)])
        fixture("Degenerate", [(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)])
        fixture("Loose Wire", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1)])
        fixture("Empty", [], [])
        fixture("Zero Edge", [(0, 0, 0), (0, 0, 0)], [], [(0, 1)])
        precision = fixture("Precision Limited", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        precision.location.x = 1e10
        fixture("Concave", [(0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)],
                [(0, 1, 2, 3, 4, 5)])
        unsafe = fixture("Unsafe", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        unsafe.data.vertices[0].co.x = float("nan")
        side = 64
        vertices = [(x / side, y / side, 0) for y in range(side + 1) for x in range(side + 1)]
        faces = [(y * (side + 1) + x, y * (side + 1) + x + 1,
                  (y + 1) * (side + 1) + x + 1, (y + 1) * (side + 1) + x)
                 for y in range(side) for x in range(side)]
        fixture("Clean Grid", vertices, faces)

        def analyze(name="Cube", **params):
            result = runtime.dispatch("mesh.analyze", {"object_name": name, **params})
            json.dumps(result, allow_nan=False)
            return result

        def compare(snapshot):
            result = runtime.dispatch("scene.compare", {"snapshot_id": snapshot["snapshot_id"]})
            assert result["coverage_complete"] and result["status"] == "unchanged_within_scope", result

        def preserved_cube_data():
            obj = bpy.data.objects["Cube"]
            owns = not obj.data.is_editmode
            mesh = bmesh.new() if owns else bmesh.from_edit_mesh(obj.data)
            try:
                if owns:
                    mesh.from_mesh(obj.data)
                mesh.verts.index_update()
                return {"positions": [tuple(v.co) for v in mesh.verts],
                        "edges": sorted(tuple(sorted(v.index for v in e.verts)) for e in mesh.edges),
                        "faces": [sorted(v.index for v in f.verts) for f in mesh.faces],
                        "uv_by_vertex": {layer.name: [sorted((loop.vert.index, tuple(loop[layer].uv), bool(loop[layer].pin_uv))
                            for loop in face.loops) for face in mesh.faces] for layer in mesh.loops.layers.uv.values()},
                        "face_materials": [f.material_index for f in mesh.faces],
                        "material_slots": [m.name if m else None for m in obj.data.materials],
                        "transform": [tuple(row) for row in obj.matrix_world]}
            finally:
                if owns:
                    mesh.free()

        def denied(name, code):
            try:
                analyze(name)
            except BridgeError as error:
                assert error.code == code, error.to_dict()
            else:
                raise AssertionError("Expected mesh-analysis denial")

        def capture(name="Cube"):
            regions = [s.region_3d for screen in bpy.data.screens for area in screen.areas if area.type == "VIEW_3D"
                       for s in area.spaces if s.type == "VIEW_3D"]
            previous = [(r.view_location.copy(), r.view_distance) for r in regions]
            try:
                for region in regions:
                    region.view_location = bpy.data.objects[name].matrix_world.translation
                    region.view_distance = 4.5
                return runtime.dispatch("viewport.capture", {"object_name": name, "view": "current", "shading": "wireframe",
                    "include_overlays": False, "resolution": [640, 480]})["path"]
            finally:
                for region, (location, distance) in zip(regions, previous, strict=True):
                    region.view_location = location
                    region.view_distance = distance

        baseline = runtime.dispatch("scene.snapshot", {"object_names": ["Cube", "Protected Mesh"]})
        preserved_before = preserved_cube_data()
        guard = runtime.dispatch("scene.snapshot", {"object_names": ["Protected Mesh"]})
        crossing_baseline = runtime.dispatch("scene.snapshot", {"object_names": ["Crossing", "Linked Crossing"]})
        selected = sorted(o.name for o in bpy.context.selected_objects)
        images = {"before_wire": capture(), "crossing_wire": capture("Crossing"), "protected_before": capture("Protected Mesh")}
        for permission in (Permission.EDIT_MESH, Permission.EXECUTE_PYTHON, Permission.DELETE_OBJECTS,
                           Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT):
            grants[permission.value] = False
        initial = analyze()
        assert initial["analysis_complete"] and initial["topology"]["counts"]["inconsistent_orientation_edges"] == 4
        assert not sum(initial["intersections"]["triangle_pairs"].values())
        assert analyze("Protected Mesh")["verification"]["status"] == "numeric_checks_passed"
        assert analyze("Crossing")["intersections"]["triangle_pairs"]["crossing"] == 1
        assert abs(analyze("Linked Crossing")["intersections"]["examples"][0]["segment_length_world"] - 1.) < 1e-6
        assert analyze("Stacked")["intersections"]["triangle_pairs"]["coplanar_overlap"] == 1
        tiny = analyze("Tiny Stacked", distance_tolerance=1e-12)
        assert tiny["analysis_complete"] and tiny["intersections"]["triangle_pairs"]["coplanar_overlap"] == 1
        assert analyze("Nonmanifold")["topology"]["counts"]["over_connected_edges"] == 1
        assert not analyze("Degenerate")["analysis_complete"] and not analyze("Empty")["analysis_complete"]
        assert analyze("Zero Edge")["topology"]["counts"]["near_zero_edges"] == 1
        precision_result = analyze("Precision Limited")
        assert not precision_result["analysis_complete"] and precision_result["intersections"]["precision_limited_triangles"] == 1
        wire = analyze("Loose Wire")
        assert wire["topology"]["counts"]["wire_edges"] == wire["topology"]["counts"]["loose_vertices"] == 1
        concave = analyze("Concave")
        assert concave["analysis_complete"] and concave["tessellation"]["triangles"] == 4
        assert not sum(concave["intersections"]["triangle_pairs"].values())
        denied("Unsafe", "INVALID_ARGUMENT")
        assert not analyze(max_triangles=1)["analysis_complete"]
        assert not analyze(max_pair_tests=1)["analysis_complete"]
        detail = analyze(max_reports=1)
        assert detail["analysis_complete"] and detail["topology"]["examples_truncated"]
        started = time.perf_counter()
        grid = analyze("Clean Grid")
        seconds = time.perf_counter() - started
        assert grid["analysis_complete"] and not sum(grid["intersections"]["triangle_pairs"].values())
        for state in ("paused", "emergency_stopped"):
            getattr(runtime.state, f"set_{state}")(True)
            assert analyze()["analysis_complete"]
            getattr(runtime.state, f"set_{state}")(False)
        runtime.state.set_paused(False)
        grants[Permission.INSPECT_SCENE.value] = False
        denied("Cube", "PERMISSION_DENIED")
        grants[Permission.INSPECT_SCENE.value] = True
        compare(baseline)

        runtime.dispatch("checkpoint.create", {"description": "Repair inconsistent face orientation"})
        grants[Permission.EDIT_MESH.value] = True
        runtime.dispatch("context.set_mode", {"object_name": "Cube", "mode": "EDIT"})
        selection = runtime.dispatch("mesh.select_components", {"object_name": "Cube", "element_type": "FACE", "indices": list(range(6))})
        reference = selection["selection"]["mesh_selection"]["selection_id"]
        runtime.dispatch("mesh.recalculate_normals", {"object_name": "Cube", "selection_id": reference})
        repaired = analyze()
        assert repaired["analysis_complete"] and repaired["verification"]["status"] == "numeric_checks_passed", repaired
        assert repaired["counts"] == initial["counts"]
        assert preserved_cube_data() == preserved_before
        compare(guard)
        runtime.dispatch("context.set_mode", {"object_name": "Cube", "mode": "OBJECT"})
        images["after_wire"] = capture()
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        compare(baseline)
        assert analyze()["topology"]["counts"]["inconsistent_orientation_edges"] == 4
        assert sorted(o.name for o in bpy.context.selected_objects) == selected
        images["recovered_wire"] = capture()
        images["protected_after"] = capture("Protected Mesh")

        runtime.dispatch("checkpoint.create", {"description": "Verify freshly assigned world-space measurements"})
        runtime.dispatch("transform.set", {"object_name": "Crossing", "scale": [1, 3, 1]})
        assert abs(analyze("Crossing")["intersections"]["examples"][0]["segment_length_world"] - 1.5) < 1e-6
        assert abs(analyze("Linked Crossing")["intersections"]["examples"][0]["segment_length_world"] - 1.) < 1e-6
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        compare(crossing_baseline)

        # Unflushed human edits on shared data must not read the alias's stale Object shadow.
        runtime.dispatch("checkpoint.create", {"description": "Shared live analysis fixture"})
        runtime.dispatch("context.set_mode", {"object_name": "Crossing", "mode": "EDIT"})
        live = bmesh.from_edit_mesh(bpy.data.objects["Crossing"].data)
        live.verts.new((0, 0, 3))
        alias_result = analyze("Linked Crossing")
        assert alias_result["counts"]["vertices"] == 7 and alias_result["mesh_data_state"] == "LIVE_EDIT_BMESH"
        assert alias_result["topology"]["counts"]["loose_vertices"] == 1 and len(live.verts) == 7
        runtime.dispatch("context.set_mode", {"object_name": "Crossing", "mode": "OBJECT"})
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert analyze("Linked Crossing")["counts"]["vertices"] == 6
        compare(baseline)
        blender_codex_bridge.unregister()
        print("BLENDER_MESH_ANALYSIS_OK " + json.dumps({"blender": bpy.app.version_string,
            "topology_winding_crossing_coplanar_verified": True, "concave_native_tessellation_verified": True,
            "repair_preservation_and_recovery_verified": True, "shared_live_data_verified": True,
            "fresh_world_scale_and_precision_limits_verified": True,
            "small_asset_tolerance_verified": True,
            "budgets_and_permissions_verified": True, "grid_triangles": 8192, "grid_seconds": seconds,
            "grid_pair_tests": grid["intersections"]["pair_tests"], "captures": images,
            "visual_review_required": True, "project_saved": False}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.)
