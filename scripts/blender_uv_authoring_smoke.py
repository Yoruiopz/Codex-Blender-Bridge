"""Layer lifecycle, corner authoring, pins, checker captures and native recovery."""

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
        grants = {p.value: True for p in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        for toolset in ("interaction", "uv"):
            runtime.registry.enable_toolset(toolset)
        obj = bpy.data.objects["Cube"]
        obj.name = "UV Prop"
        mesh = bpy.data.meshes.new("UV Fixture")
        mesh.from_pydata([(-2, -1, 0), (0, -1, 0), (0, 1, 0), (-2, 1, 0), (2, -1, 0), (2, 1, 0)],
                         [], [(0, 1, 2, 3), (1, 4, 5, 2)])
        fixture = bmesh.new()
        fixture.from_mesh(mesh)
        fixture.faces.index_update()
        for name in ("Source", "Spare"):
            layer = fixture.loops.layers.uv.new(name)
            for face in fixture.faces:
                for loop in face.loops:
                    loop[layer].uv = (.5 + loop.vert.co.x * .25, .5 + loop.vert.co.y * .5)
                    loop[layer].pin_uv = face.index == 1
        fixture.to_mesh(mesh)
        fixture.free()
        obj.data = mesh
        per_layer_selection = hasattr(mesh.uv_layers["Source"], "vertex_selection")
        if per_layer_selection:
            mesh.uv_layers["Source"].vertex_selection.foreach_set("value", [True, False] * 4)
            mesh.uv_layers["Source"].edge_selection.foreach_set("value", [False, True] * 4)
        else:
            for name in (".uv_select_vert", ".uv_select_edge"):
                attribute = mesh.attributes.get(name) or mesh.attributes.new(name=name, type="BOOLEAN", domain="CORNER")
                attribute.data.foreach_set("value", [True, False] * 4)
        mesh.attributes.new(name=".pn.Blocked", type="BOOLEAN", domain="CORNER")
        material = bpy.data.materials.new("Fixture Checker")
        material.use_nodes = True
        nodes = material.node_tree.nodes
        mapping = nodes.new("ShaderNodeUVMap")
        mapping.uv_map = "Authored"
        checker = nodes.new("ShaderNodeTexChecker")
        checker.inputs["Scale"].default_value = 8
        material.node_tree.links.new(mapping.outputs["UV"], checker.inputs["Vector"])
        material.node_tree.links.new(checker.outputs["Color"], nodes.get("Principled BSDF").inputs["Base Color"])
        mesh.materials.append(material)
        protected = obj.copy()
        protected.data = mesh.copy()
        protected.name = "Protected UV Prop"
        protected.location.x = 5
        bpy.context.scene.collection.objects.link(protected)
        protected.select_set(True)
        empty_mesh = bpy.data.meshes.new("Initially No UV")
        empty_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        empty = bpy.data.objects.new("Initially No UV", empty_mesh)
        empty.location.x = 9
        bpy.context.scene.collection.objects.link(empty)
        selected_before = sorted(o.name for o in bpy.context.selected_objects)
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_distance = 7
                area.spaces.active.region_3d.view_location = (0, 0, 0)

        def call(method, **params):
            return runtime.dispatch(method, {"object_name": "UV Prop", **params})

        def denied(method, code, **params):
            try:
                call(method, **params)
            except BridgeError as error:
                assert error.code == code, (method, code, error.code)
                return error
            raise AssertionError(f"{method} unexpectedly succeeded")

        def coordinates(layer):
            result = call("uv.inspect", uv_layer=layer, include_coordinates=True, max_coordinates=256)
            assert not result["coordinates"]["truncated"]
            return result["coordinates"]["items"]

        def capture():
            return call("viewport.capture", view="top", shading="material", include_overlays=False,
                        resolution=[640, 480])["path"]

        first = runtime.dispatch("uv.layer_create", {"object_name": "Initially No UV", "new_name": "First"})
        assert first["after"]["active"] == "First" and first["after"]["render"] == "First"
        assert first["uv_selection_policy"] == ("ZERO_PER_LAYER" if per_layer_selection else "PRESERVE_MESH_GLOBAL")
        runtime.dispatch("uv.layer_remove", {"object_name": "Initially No UV", "uv_layer": "First", "confirm_remove": True})
        assert not bpy.data.objects["Initially No UV"].data.uv_layers
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert bpy.data.objects["Initially No UV"].data.uv_layers.active.name == "First"

        def selection_state(layer_name):
            mesh = bpy.data.objects["UV Prop"].data
            buffers = []
            for name in ("vertex_selection", "edge_selection") if per_layer_selection else (".uv_select_vert", ".uv_select_edge"):
                data = getattr(mesh.uv_layers[layer_name], name) if per_layer_selection else mesh.attributes[name].data
                values = [False] * len(data)
                data.foreach_get("value", values)
                buffers.append(values)
            return buffers

        original_source = coordinates("Source")
        original_spare = coordinates("Spare")
        original_uv_selection = selection_state("Source")
        guard = runtime.dispatch("scene.snapshot", {"object_names": ["Protected UV Prop"]})
        non_uv = runtime.dispatch("scene.snapshot", {"object_names": ["UV Prop", "Protected UV Prop"],
            "fields": ["transforms", "hierarchy", "visibility", "mesh_geometry", "weights", "material_slots", "shader_inputs"]})
        for method, params in (
            ("uv.layer_create", {"new_name": "Denied"}),
            ("uv.layer_rename", {"uv_layer": "Source", "new_name": "Denied"}),
            ("uv.layer_activate", {"uv_layer": "Source"}),
            ("uv.layer_remove", {"uv_layer": "Source", "confirm_remove": True}),
        ):
            grants[Permission.EDIT_MESH.value] = False
            denied(method, "PERMISSION_DENIED", **params)
            grants[Permission.EDIT_MESH.value] = True
        for permission in (Permission.EXECUTE_PYTHON, Permission.DELETE_OBJECTS,
                           Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT):
            grants[permission.value] = False
        created = call("uv.layer_create", new_name="Authored", copy_from="Source")
        assert created["uv_selection_policy"] == ("COPY_PER_LAYER" if per_layer_selection else "PRESERVE_MESH_GLOBAL")
        assert selection_state("Authored") == original_uv_selection
        assert coordinates("Authored") == original_source
        assert bpy.data.objects["UV Prop"].data.uv_layers.active.name == "Source"
        call("uv.layer_rename", uv_layer="Authored", new_name="Renamed Authored")
        assert coordinates("Renamed Authored") == original_source
        assert selection_state("Renamed Authored") == original_uv_selection
        consumers = bpy.data.materials["Fixture Checker"].node_tree.nodes
        assert next(node for node in consumers if node.bl_idname == "ShaderNodeUVMap").uv_map == "Authored"
        call("uv.layer_rename", uv_layer="Renamed Authored", new_name="Authored")
        call("uv.layer_create", new_name="Remove Pinned", copy_from="Source")
        call("uv.layer_remove", uv_layer="Remove Pinned", confirm_remove=True)
        assert bpy.data.objects["UV Prop"].data.attributes.get(".pn.Remove Pinned") is None
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert coordinates("Remove Pinned") == original_source
        call("uv.layer_remove", uv_layer="Remove Pinned", confirm_remove=True)
        call("uv.layer_create", new_name="Zero")
        assert all(item["uv"] == [0, 0] and not item["pinned"] for item in coordinates("Zero"))
        denied("uv.layer_create", "INVALID_ARGUMENT", new_name="Source")
        denied("uv.layer_create", "INVALID_ARGUMENT", new_name="Blocked")
        call("uv.layer_rename", uv_layer="Zero", new_name="Scratch")
        denied("uv.layer_rename", "INVALID_ARGUMENT", uv_layer="Scratch", new_name="Blocked")
        activated = call("uv.layer_activate", uv_layer="Authored", for_render=True, for_clone=True)
        assert all(activated["after"][key] == "Authored" for key in ("active", "render", "clone"))
        denied("uv.layer_remove", "INVALID_ARGUMENT", uv_layer="Scratch")
        removal_baseline = runtime.dispatch("scene.snapshot", {"object_names": ["UV Prop"]})
        call("uv.layer_remove", uv_layer="Scratch", confirm_remove=True)
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert runtime.dispatch("scene.compare", {"snapshot_id": removal_baseline["snapshot_id"]})["status"] == "unchanged_within_scope"
        assert "Scratch" in bpy.data.objects["UV Prop"].data.uv_layers
        call("uv.layer_remove", uv_layer="Scratch", confirm_remove=True)
        session_baseline = runtime.dispatch("scene.snapshot", {"object_names": ["UV Prop"]})
        assert selection_state("Source") == original_uv_selection
        before_image = capture()
        runtime.dispatch("checkpoint.create", {"description": "Scoped UV authoring"})
        call("context.set_mode", mode="EDIT")
        selection = call("mesh.select_components", element_type="FACE", indices=[0])
        reference = selection["selection"]["mesh_selection"]["selection_id"]
        for method, params in (
            ("uv.coordinates_set", {"updates": [{"face_index": 0, "corner_index": 0, "uv": [0, 0]}]}),
            ("uv.transform", {"offset": [1, 1]}), ("uv.pin", {"pinned": True}),
        ):
            grants[Permission.EDIT_MESH.value] = False
            denied(method, "PERMISSION_DENIED", uv_layer="Authored", selection_id=reference, **params)
            grants[Permission.EDIT_MESH.value] = True
        denied("uv.layer_create", "INVALID_MODE", new_name="NoImplicitModeSwitch")
        denied("uv.coordinates_set", "INVALID_SELECTION", uv_layer="Authored", selection_id=reference,
               updates=[{"face_index": 0, "corner_index": 0, "uv": [7, 7]},
                        {"face_index": 1, "corner_index": 0, "uv": [7, 7]}])
        assert [item["uv"] for item in coordinates("Authored")] == [item["uv"] for item in original_source]
        call("uv.coordinates_set", uv_layer="Authored", selection_id=reference,
             updates=[{"face_index": 0, "corner_index": 0, "uv": [-.125, -.25]}])
        anchored = call("uv.pin", uv_layer="Authored", selection_id=reference, pinned=True,
                        corners=[{"face_index": 0, "corner_index": 0}])
        assert anchored["pin_changes"] == 1
        one_skipped = call("uv.transform", uv_layer="Authored", selection_id=reference, offset=[5, 5],
                           corners=[{"face_index": 0, "corner_index": 0}])
        assert one_skipped["skipped_pinned_corners"] == 1 and not one_skipped["changed"]
        call("uv.pin", uv_layer="Authored", selection_id=reference, pinned=True)
        skipped = call("uv.transform", uv_layer="Authored", selection_id=reference, offset=[5, 5])
        assert not skipped["changed"] and skipped["skipped_pinned_corners"] == 4
        call("uv.pin", uv_layer="Authored", selection_id=reference, pinned=False)
        one_moved = call("uv.transform", uv_layer="Authored", selection_id=reference, offset=[.125, 0],
                         corners=[{"face_index": 0, "corner_index": 1}])
        assert one_moved["coordinate_changes"] == 1 and one_moved["target_corners"] == 1
        # Inject an update failure into the real BMesh tool; verify local rollback independently.
        before_fault = coordinates("Authored")
        original_update = bmesh.update_edit_mesh
        updates = []

        def fail_once(*args, **kwargs):
            updates.append(True)
            if len(updates) == 1:
                raise RuntimeError("fixture update failure")
            return original_update(*args, **kwargs)

        bmesh.update_edit_mesh = fail_once
        try:
            failure = denied("uv.transform", "OPERATION_FAILED", uv_layer="Authored", selection_id=reference, offset=[1, 1])
            assert failure.context["rollback_verified"]
        finally:
            bmesh.update_edit_mesh = original_update
        assert coordinates("Authored") == before_fault
        transformed = call("uv.transform", uv_layer="Authored", selection_id=reference,
                           offset=[.125, .25], scale=[.5, .75], pivot=[.25, .5], rotation=math.pi / 2)
        assert transformed["coordinate_changes"] == 4 and not transformed["selection_changed"]
        after = coordinates("Authored")
        for old, new in zip(before_fault, after, strict=True):
            if old["face_index"] == 0:
                x, y = (old["uv"][0] - .25) * .5, (old["uv"][1] - .5) * .75
                expected = (.375 - y, .75 + x)
                assert all(abs(a - b) < 1e-6 for a, b in zip(new["uv"], expected, strict=True))
            else:
                assert new["uv"] == old["uv"] and new["pinned"] == old["pinned"]
        assert all(not item["pinned"] for item in after if item["face_index"] == 0)
        for name, original in (("Source", original_source), ("Spare", original_spare)):
            assert [(item["uv"], item["pinned"]) for item in coordinates(name)] == [(item["uv"], item["pinned"]) for item in original]
        call("context.set_mode", mode="OBJECT")
        after_image = capture()
        for snapshot in (guard, non_uv):
            compared = runtime.dispatch("scene.compare", {"snapshot_id": snapshot["snapshot_id"]})
            assert compared["coverage_complete"] and compared["status"] == "unchanged_within_scope"
        restored = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert restored["snapshot_marker_verified"] and restored["recovered_scope"] == "mesh_edit_session"
        compared = runtime.dispatch("scene.compare", {"snapshot_id": session_baseline["snapshot_id"]})
        assert compared["coverage_complete"] and compared["status"] == "unchanged_within_scope"
        assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active.name == "UV Prop"
        assert sorted(o.name for o in bpy.context.selected_objects) == selected_before
        roles = bpy.data.objects["UV Prop"].data.uv_layers
        assert roles.active.name == "Authored" and roles["Authored"].active_render and roles["Authored"].active_clone
        blender_codex_bridge.unregister()
        print("BLENDER_UV_AUTHORING_OK " + json.dumps({
            "blender": bpy.app.version_string, "layer_lifecycle_and_copy_verified": True,
            "scoped_coordinate_transform_and_pins_verified": True, "local_fault_rollback_verified": True,
            "protected_mesh_and_other_layers_verified": True, "grouped_recovery_verified": True,
            "captures": {"before": before_image, "after": after_image}, "visual_review_required": True,
            "project_saved": False,
        }), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
