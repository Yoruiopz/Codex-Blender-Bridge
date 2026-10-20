"""Measured procedural-palette revisions, protected groups and fault recovery in native Blender."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))


def run():
    try:
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        from blender_codex_bridge.tools import shader_settings
        from blender_codex_bridge.tools.shader_state import SETTINGS

        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_delete_objects = prefs.allow_save_project = prefs.allow_external_files = False
        for toolset in ("objects", "materials", "nodes", "batch", "interaction"):
            runtime.registry.enable_toolset(toolset)
        cube = bpy.data.objects["Cube"]
        cube.name = "Palette Prop"
        protected = cube.copy()
        protected.name, protected.location.x = "Protected Prop", 4
        bpy.context.scene.collection.objects.link(protected)
        source = cube.material_slots[0].material
        source.name = "Source Finish"
        group = bpy.data.node_groups.new("Palette Source", "ShaderNodeTree")
        group.interface.new_socket(name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
        output = group.nodes.new("NodeGroupOutput")
        bsdf = group.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Roughness"].default_value = .5
        noise = group.nodes.new("ShaderNodeTexNoise")
        noise.name = "Noise"
        noise.inputs["Scale"].default_value = 5
        ramp = group.nodes.new("ShaderNodeValToRGB")
        ramp.name = "Ramp"
        ramp.color_ramp.elements[0].color = [.05, .008, .002, 1]
        ramp.color_ramp.elements[1].color = [.9, .35, .02, 1]
        group.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        group.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        group.links.new(bsdf.outputs["BSDF"], output.inputs["Shader"])
        for kind in SETTINGS:
            group.nodes.new(kind).name = "Probe " + kind
        source.node_tree.nodes.clear()
        instance = source.node_tree.nodes.new("ShaderNodeGroup")
        instance.name, instance.node_tree = "Surface", group
        material_output = source.node_tree.nodes.new("ShaderNodeOutputMaterial")
        source.node_tree.links.new(instance.outputs["Shader"], material_output.inputs["Surface"])
        source.node_tree.nodes.new("ShaderNodeMath").name = "Root Math"
        source.node_tree.nodes.new("ShaderNodeValToRGB").name = "Root Ramp"
        source.node_tree.nodes.new("ShaderNodeTexImage").name = "Root Image"
        target = source.copy()
        target.name = "Target Finish"
        cube.material_slots[0].link, cube.material_slots[0].material = "OBJECT", target
        assert group.users == 2 and cube.data == protected.data
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((5, -6, 4)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 5.5

        def call(method, **params):
            return runtime.dispatch(method, params)

        def inspect(node="Ramp", material="Target Finish", nested=True, **params):
            return call("nodes.inspect_properties", material_name=material, node_name=node,
                        **({"group_path": ["Surface"]} if nested else {}), **params)

        def revise(stops, **params):
            return call("nodes.set_color_ramp", material_name="Target Finish", node_name="Ramp",
                        group_path=["Surface"], stops=stops, **params)

        def undo():
            result = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert result["snapshot_marker_verified"], result

        def capture(object_name="Palette Prop"):
            regions = [area.spaces.active.region_3d for area in bpy.context.screen.areas if area.type == "VIEW_3D"]
            locations = [region.view_location.copy() for region in regions]
            try:
                for region in regions:
                    region.view_location = bpy.data.objects[object_name].matrix_world.translation
                return call("viewport.capture", object_name=object_name, shading="material", view="current",
                            resolution=[640, 480], include_overlays=False)["path"]
            finally:
                for region, location in zip(regions, locations, strict=True):
                    region.view_location = location

        def content(material="Source Finish"):
            graph = call("nodes.inspect", material_name=material, group_path=["Surface"], max_nodes=100, max_sockets_per_direction=64)
            assert not graph["truncated"], graph
            return {"nodes": [{key: value for key, value in node.items() if key not in {"location", "dimensions"}}
                              for node in graph["nodes"]], "links": graph["links"]}

        def compare(snapshot, expected="unchanged_within_scope"):
            result = call("scene.compare", snapshot_id=snapshot["snapshot_id"])
            assert result["coverage_complete"] and result["status"] == expected, result

        def denied(method, code, **params):
            before = content()
            try:
                call(method, **params)
            except BridgeError as error:
                assert error.code == code, error.to_dict()
            else:
                raise AssertionError("Expected rejection: " + method)
            assert content() == before

        call("selection.inspect")
        initial_selection = sorted(obj.name for obj in bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active.name
        protected_content = content()
        baseline = call("scene.snapshot", object_names=["Palette Prop", "Protected Prop"])
        captures = {"before": capture(), "protected_before": capture("Protected Prop")}
        cool = [{"position": 0, "color": [.005, .015, .06, 1]},
                {"position": .5, "color": [.015, .32, .3, 1]},
                {"position": 1, "color": [.8, .95, .9, 1]}]
        denied("nodes.set_color_ramp", "INVALID_ARGUMENT", material_name="Target Finish", node_name="Ramp", group_path=["Surface"], stops=cool)
        denied("nodes.set_properties", "INVALID_ARGUMENT", material_name="Target Finish", node_name="Noise", group_path=["Surface"], settings={"noise_dimensions": "4D"})
        denied("nodes.set_properties", "NOT_IMPLEMENTED", material_name="Target Finish", node_name="Root Image", settings={"interpolation": "Closest"})
        denied("nodes.set_properties", "INVALID_ARGUMENT", material_name="Target Finish", node_name="Root Math", settings={"operation": "INVALID_NATIVE_ENUM"})
        target.node_tree.animation_data_create().action = bpy.data.actions.new("Animation Guard Fixture")
        denied("nodes.set_properties", "NOT_IMPLEMENTED", material_name="Target Finish", node_name="Root Math", settings={"operation": "MULTIPLY"})
        action = target.node_tree.animation_data.action
        target.node_tree.animation_data.action = None
        bpy.data.actions.remove(action)
        prefs.allow_edit_materials = False
        denied("nodes.set_properties", "PERMISSION_DENIED", material_name="Target Finish", node_name="Root Math", settings={"operation": "MULTIPLY"})
        prefs.allow_edit_materials = True
        for flag, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            getattr(runtime.state, f"set_{flag}")(True)
            denied("nodes.set_properties", code, material_name="Target Finish", node_name="Root Math", settings={"operation": "MULTIPLY"})
            getattr(runtime.state, f"set_{flag}")(False)
            runtime.state.set_paused(False)
        runtime.checkpoints.clear()
        call("shader_group.copy_for_node", material_name="Target Finish", node_name="Surface", new_name="Palette Working")
        root_snapshot = call("scene.snapshot", object_names=["Palette Prop"], fields=["shader_inputs"])
        call("nodes.set_properties", material_name="Target Finish", node_name="Root Math", settings={"operation": "MULTIPLY"})
        compare(root_snapshot, "changed")
        undo()
        compare(root_snapshot)
        call("nodes.set_color_ramp", material_name="Target Finish", node_name="Root Ramp", stops=[cool[0], cool[-1]])
        compare(root_snapshot, "changed")
        undo()
        compare(root_snapshot)
        for stops in ([{"position": 0, "color": [2, .25, 0, 1]}],
                      [{"position": i / 31, "color": [i / 31, 0, 1 - i / 31, 1]} for i in range(32)]):
            result = call("nodes.set_color_ramp", material_name="Target Finish", node_name="Root Ramp", stops=stops)
            assert result["node"]["color_ramp"]["element_count"] == len(stops)
            undo()
            compare(root_snapshot)

        hsv_stops = [{"position": 0, "color": [1, 0, 0, 1]}, {"position": 1, "color": [0, 0, 1, 1]}]
        call("nodes.set_color_ramp", material_name="Target Finish", node_name="Root Ramp", stops=hsv_stops,
             interpolation="CONSTANT", color_mode="HSV", hue_interpolation="NEAR")
        hsv = inspect("Root Ramp", nested=False, sample_positions=[.5])
        assert hsv["node"]["color_ramp"]["effective_interpolation"] == "LINEAR"
        assert not hsv["node"]["color_ramp"]["interpolation_active"]
        assert all(abs(actual - expected) < .00001 for actual, expected in zip(hsv["samples"][0]["color"], [1, 0, 1, 1], strict=True))
        undo()
        compare(root_snapshot)

        steps, requested = [], {}
        for kind in SETTINGS:
            node_name = "Probe " + kind
            state = inspect(node_name)
            settings = {}
            for key, descriptor in state["editable_settings"].items():
                if not descriptor["available"] or descriptor["readonly"]:
                    continue
                current = state["node"]["settings"][key]
                if descriptor["type"] == "ENUM":
                    settings[key] = next(item for item in descriptor["identifiers"] if item and item != current)
                elif descriptor["type"] == "BOOLEAN":
                    settings[key] = not current
                elif descriptor["type"] == "STRING":
                    settings[key] = "UVMap"
            requested[node_name] = settings
            steps.append({"method": "nodes.set_properties", "params": {"material_name": "Target Finish",
                          "node_name": node_name, "group_path": ["Surface"], "settings": settings}})
        call("batch.execute", label="Reviewed shader settings", steps=steps)
        for node_name, settings in requested.items():
            actual = inspect(node_name)["node"]["settings"]
            assert all(actual[key] == value for key, value in settings.items()), (node_name, actual, settings)
        call("batch.execute", label="Cool procedural palette", steps=[
            {"method": "nodes.set_properties", "params": {"material_name": "Target Finish", "node_name": "Noise", "group_path": ["Surface"], "settings": {"noise_dimensions": "4D"}}},
            {"method": "nodes.set_input", "params": {"material_name": "Target Finish", "node_name": "Noise", "group_path": ["Surface"], "socket_name": "W", "value": .6}},
            {"method": "nodes.set_color_ramp", "params": {"material_name": "Target Finish", "node_name": "Ramp", "group_path": ["Surface"], "stops": cool, "interpolation": "EASE"}},
        ])
        cool_state = inspect()["node"]["color_ramp"]
        assert cool_state["element_count"] == 3 and inspect("Noise")["node"]["settings"]["noise_dimensions"] == "4D"
        captures["cool_variant"] = capture()
        tied = [{"position": 0, "color": [.04, .008, .002, 1]},
                {"position": .5, "color": [.8, .08, .01, 1]},
                {"position": .5, "color": [.95, .55, .05, 1]},
                {"position": 1, "color": [.95, .8, .5, 1]}]
        revise(tied, interpolation="CONSTANT", color_mode="RGB", hue_interpolation="CCW")
        assert inspect()["node"]["color_ramp"]["effective_interpolation"] == "CONSTANT"
        assert [stop["position"] for stop in inspect()["node"]["color_ramp"]["elements"]] == [0., .5, .5, 1.]
        captures["hard_step_variant"] = capture()
        undo()
        assert inspect()["node"]["color_ramp"] == cool_state

        original_replace = shader_settings._replace
        for persistent in (False, True):
            attempts = [0]
            def fail(ramp, state, attempts=attempts, persistent=persistent):
                attempts[0] += 1
                if persistent or attempts[0] == 1:
                    ramp.elements[0].color = [.3, .1, .4, 1]
                    if len(ramp.elements) > 1:
                        ramp.elements.remove(ramp.elements[-1])
                    raise RuntimeError("Injected native ramp revision failure")
                return original_replace(ramp, state)
            shader_settings._replace = fail
            try:
                revise(tied)
            except BridgeError as error:
                assert error.context["rollback_verified"] is not persistent
                assert error.context["possible_mutation"] is persistent
                assert error.context["undo_boundary_finalized"]
            else:
                raise AssertionError("Injected failure unexpectedly succeeded")
            finally:
                shader_settings._replace = original_replace
            if not persistent:
                assert inspect()["node"]["color_ramp"] == cool_state
            undo()
            assert inspect()["node"]["color_ramp"] == cool_state
        captures["recovered_cool"] = capture()
        assert content() == protected_content
        captures["protected_midway"] = capture("Protected Prop")
        undo()  # Cool palette batch.
        undo()  # Reviewed settings batch.
        undo()  # Explicit group isolation.
        compare(baseline)
        assert content() == protected_content and bpy.data.node_groups.get("Palette Working") is None
        assert sorted(obj.name for obj in bpy.context.selected_objects) == initial_selection
        assert bpy.context.view_layer.objects.active.name == active and bpy.context.mode == "OBJECT"
        assert bpy.context.preferences.edit.undo_steps == 32
        captures["recovered_original"] = capture()
        captures["protected_after"] = capture("Protected Prop")
        print("BLENDER_SHADER_SETTINGS_OK " + json.dumps({"blender": bpy.app.version_string,
            "reviewed_node_types_verified": len(SETTINGS), "same_count_root_evidence_detected": True,
            "nested_palette_revisions_and_native_samples": True, "one_and_32_stop_and_tied_hdr_cases": True,
            "stored_vs_effective_interpolation_verified": True,
            "partial_failure_local_and_native_recovery_verified": True,
            "protected_shared_source_unchanged": True, "native_staged_recovery_verified": True,
            "permission_pause_emergency_and_animation_gates": True, "captures": captures,
            "project_saved": False, "user_preferences_saved": False, "visual_review_required": True,
            "full_artist_acceptance_verified": False}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
