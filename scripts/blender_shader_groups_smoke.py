"""Nested shader authoring/isolation with protected data, matched views and actual native recovery."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import traceback
import zlib
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

        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = prefs.allow_external_files = False
        for toolset in ("nodes", "materials", "objects", "batch"):
            runtime.registry.enable_toolset(toolset)
        assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active.name == "Cube"
        cube = bpy.data.objects["Cube"]
        cube.name = "Nested Prop"
        protected = cube.copy()
        protected.name, protected.location.x = "Protected Prop", 4
        bpy.context.scene.collection.objects.link(protected)
        base = cube.data.materials[0]
        base.name = "Protected Surface"
        base.node_tree.nodes.clear()
        inner = bpy.data.node_groups.new("Shared Finish", "ShaderNodeTree")
        inner.interface.new_socket(name="Color", in_out="INPUT", socket_type="NodeSocketColor")
        inner.interface.new_socket(name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
        source = inner.nodes.new("NodeGroupInput")
        source.name = "Group Input"
        finish = inner.nodes.new("ShaderNodeBsdfPrincipled")
        finish.name = "Finish"
        output = inner.nodes.new("NodeGroupOutput")
        output.name, output.is_active_output = "Group Output", True
        inner.links.new(source.outputs["Color"], finish.inputs["Base Color"])
        inner.links.new(finish.outputs["BSDF"], output.inputs["Shader"])
        outer = bpy.data.node_groups.new("Shared Outer", "ShaderNodeTree")
        outer.interface.new_socket(name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
        inner_node = outer.nodes.new("ShaderNodeGroup")
        inner_node.name, inner_node.node_tree = "Finish", inner
        inner_node.inputs["Color"].default_value = (.8, .14, .025, 1)
        outer_output = outer.nodes.new("NodeGroupOutput")
        outer_output.name, outer_output.is_active_output = "Group Output", True
        outer.links.new(inner_node.outputs["Shader"], outer_output.inputs["Shader"])
        cycle = outer.nodes.new("ShaderNodeGroup")
        cycle.name = "Cycle Probe"
        instance = base.node_tree.nodes.new("ShaderNodeGroup")
        instance.name, instance.node_tree = "Surface", outer
        material_output = base.node_tree.nodes.new("ShaderNodeOutputMaterial")
        base.node_tree.links.new(instance.outputs["Shader"], material_output.inputs["Surface"])
        target = base.copy()
        target.name = "Target Surface"
        cube.material_slots[0].link, cube.material_slots[0].material = "OBJECT", target
        assert cube.data == protected.data and inner.users == 1 and outer.users == 2

        directory = Path(tempfile.gettempdir()) / "shader-textures"
        directory.mkdir()
        texture_path = directory / "green.png"
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
        pixels = b"".join(b"\0" + b"".join(bytes((35, 165, 48, 255) if (x // 4 + y // 4) % 2 else (150, 230, 35, 255))
                         for x in range(16)) for y in range(16))
        texture_path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0))
                                 + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))
        image = bpy.data.images.load(str(texture_path), check_existing=False)
        image.name = "Approved Green"
        assert tuple(image.size) == (16, 16)  # Explicit fixture decode, never a bridge inspection side effect.
        assert image.has_data
        file_probe = inner.nodes.new("ShaderNodeTexImage")
        file_probe.name = "File Probe"
        file_group = bpy.data.node_groups.new("File Dependency", "ShaderNodeTree")
        file_group.nodes.new("ShaderNodeTexImage").image = image
        source_hash = hashlib.sha256(texture_path.read_bytes()).hexdigest()
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                region = area.spaces.active.region_3d
                region.view_rotation = Vector((5, -6, 4)).to_track_quat("Z", "Y")
                region.view_distance = 5.5
        tracked, tracking = [], False

        def call(method, **params):
            result = runtime.dispatch(method, params)
            spec = runtime.registry.get(method)
            if tracking and spec.modifies and (spec.automatic_checkpoint or method == "batch.execute"):
                assert result["operation"]["undo_boundary_finalized"]
                tracked.append("Batch: " + result["batch_label"] if method == "batch.execute" else method)
            return result

        def denied(method, code, **params):
            group_names = sorted(g.name for g in bpy.data.node_groups)
            try:
                call(method, **params)
            except BridgeError as error:
                assert error.code == code, error.to_dict()
            else:
                raise AssertionError("Expected denial: " + method)
            assert sorted(g.name for g in bpy.data.node_groups) == group_names

        def undo(expected):
            result = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert result["tracked_agent_label"] == expected, result

        def content(group_name):
            result = call("shader_group.inspect", group_name=group_name, max_nodes=256, max_links=1024, max_sockets_per_direction=64)
            assert not result["truncated"], result
            return {"nodes": [{key: value for key, value in node.items() if key not in {"location", "dimensions"}}
                              for node in result["nodes"]], "links": result["links"], "interface": result["interface"]}

        def compare(snapshot):
            result = call("scene.compare", snapshot_id=snapshot["snapshot_id"])
            assert result["coverage_complete"] and result["status"] == "unchanged_within_scope", result

        def capture(object_name="Nested Prop"):
            regions = [a.spaces.active.region_3d for a in bpy.context.screen.areas if a.type == "VIEW_3D"]
            locations = [r.view_location.copy() for r in regions]
            try:
                for region in regions:
                    region.view_location = bpy.data.objects[object_name].matrix_world.translation
                return call("viewport.capture", object_name=object_name, view="current", shading="material", resolution=[640, 480], include_overlays=False)["path"]
            finally:
                for region, location in zip(regions, locations, strict=True):
                    region.view_location = location

        initial_contents = {g.name: content(g.name) for g in (inner, outer)}
        scope = call("shader_group.inspect", group_name="Shared Finish")["ownership"]
        assert scope["group_users"] == 1 and scope["requires_shared_consent"]
        assert scope["affected_objects"] == ["Nested Prop", "Protected Prop"]
        denied("nodes.set_input", "INVALID_ARGUMENT", material_name="Target Surface", group_path=["Surface", "Finish"], node_name="Finish", socket_name="Roughness", value=.1)
        denied("shader_group.interface_add", "INVALID_ARGUMENT", group_name="Shared Finish", name="Unsafe")
        denied("shader_group.bind", "INVALID_ARGUMENT", material_name="Target Surface", group_path=["Surface"], node_name="Cycle Probe", group_name="Shared Outer", allow_shared=True)
        denied("nodes.set_image", "PERMISSION_DENIED", material_name="Target Surface", group_path=["Surface", "Finish"], node_name="File Probe", image_name="Approved Green", allow_shared=True)
        denied("shader_group.bind", "PERMISSION_DENIED", material_name="Target Surface", group_path=["Surface"], node_name="Cycle Probe", group_name="File Dependency", allow_shared=True)
        prefs.allow_edit_materials = False
        denied("shader_group.create", "PERMISSION_DENIED", group_name="Denied")
        prefs.allow_edit_materials = True
        for attribute, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            getattr(runtime.state, "set_" + attribute)(True)
            denied("shader_group.create", code, group_name="Blocked")
            assert call("nodes.inspect", material_name="Target Surface", group_path=["Surface", "Finish"])["node_tree"] == "Shared Finish"
            getattr(runtime.state, "set_" + attribute)(False)
        runtime.state.set_paused(False)
        call("shader_group.create", group_name="Unused")
        call("shader_group.interface_add", group_name="Unused", name="Value", default_value=.5)
        denied("shader_group.remove", "PERMISSION_DENIED", group_name="Unused", confirm_unused=True)
        prefs.allow_delete_objects = True
        call("shader_group.remove", group_name="Unused", confirm_unused=True)
        undo("shader_group.remove")
        assert bpy.data.node_groups["Unused"].interface.items_tree[0].default_value == .5
        undo("shader_group.interface_add")
        undo("shader_group.create")
        prefs.allow_delete_objects = False
        try:
            call("batch.execute", label="Partial group failure", steps=[
                {"method": "shader_group.create", "params": {"group_name": "Partial"}},
                {"method": "shader_group.interface_add", "params": {"group_name": "Partial", "name": "Bad", "default_value": "not a float"}},
            ])
        except BridgeError as error:
            assert error.code == "INVALID_ARGUMENT" and error.context["completed_steps"] == 1
            assert error.context["undo_boundary_finalized"] and not error.context["rollback_performed"]
        else:
            raise AssertionError("Expected a partial batch failure")
        assert bpy.data.node_groups.get("Partial") is not None
        undo("Batch: Partial group failure")
        assert bpy.data.node_groups.get("Partial") is None

        baseline = call("scene.snapshot", object_names=["Nested Prop", "Protected Prop"])
        guard = call("scene.snapshot", object_names=["Protected Prop"])
        group_names = sorted(g.name for g in bpy.data.node_groups)
        material_names = sorted(m.name for m in bpy.data.materials)
        selection = sorted(o.name for o in bpy.context.selected_objects)
        captures = {"before": capture(), "protected_before": capture("Protected Prop")}
        call("checkpoint.create", description="Isolate and revise a nested material without touching its protected user")
        tracking = True
        call("material.copy_for_object", object_name="Nested Prop", slot_index=0, new_name="Working Surface")
        call("shader_group.copy_for_node", material_name="Working Surface", node_name="Surface", new_name="Isolated Outer")
        call("shader_group.copy_for_node", material_name="Working Surface", group_path=["Surface"], node_name="Finish", new_name="Isolated Finish")
        assert list(bpy.data.node_groups["Isolated Outer"].nodes["Finish"].inputs["Color"].default_value) == list(bpy.data.node_groups["Shared Outer"].nodes["Finish"].inputs["Color"].default_value)
        call("nodes.set_input", material_name="Working Surface", group_path=["Surface"], node_name="Finish", socket_name="Color", value=[.025, .24, .8, 1])
        call("nodes.set_input", material_name="Working Surface", group_path=["Surface", "Finish"], node_name="Finish", socket_name="Roughness", value=.18)
        first_count = len(tracked)
        first_contents = {g: content(g) for g in ("Isolated Outer", "Isolated Finish")}
        first_snapshot = call("scene.snapshot", object_names=["Nested Prop", "Protected Prop"])
        compare(guard)
        captures["blue_variant"] = capture()

        steps = []
        def step(method, **params):
            steps.append({"id": str(len(steps) + 1), "method": method, "params": params})
        step("shader_group.create", group_name="Variant Finish")
        step("shader_group.interface_add", group_name="Variant Finish", name="Color", socket_type="NodeSocketColor", default_value=[.2, .8, .07, 1])
        step("shader_group.interface_add", group_name="Variant Finish", name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
        step("nodes.add", material_name="Working Surface", group_path=["Surface"], node_type="ShaderNodeGroup", name="Variant")
        step("shader_group.bind", material_name="Working Surface", group_path=["Surface"], node_name="Variant", group_name="Variant Finish")
        variant = {"material_name": "Working Surface", "group_path": ["Surface", "Variant"]}
        step("nodes.add", **variant, node_type="ShaderNodeBsdfPrincipled", name="Finish")
        step("nodes.link", **variant, from_node="Group Input", from_socket="Color", to_node="Finish", to_socket="Base Color")
        step("nodes.link", **variant, from_node="Finish", from_socket="BSDF", to_node="Group Output", to_socket="Shader")
        step("nodes.add", **variant, node_type="ShaderNodeTexImage", name="Paint")
        # File permission is tested before the positive recipe so failed checkpoints do not interleave this undo stack.
        prefs.allow_external_files, prefs.texture_directory = True, str(directory)
        step("nodes.set_image", **variant, node_name="Paint", image_name="Approved Green", interpolation="Closest")
        step("nodes.link", **variant, from_node="Paint", from_socket="Color", to_node="Finish", to_socket="Base Color", replace_existing=True)
        step("nodes.link", material_name="Working Surface", group_path=["Surface"], from_node="Variant", from_socket="Shader", to_node="Group Output", to_socket="Shader", replace_existing=True)
        plan = call("batch.plan", steps=steps, label="Nested green finish")
        assert plan["ready"] and not plan["atomic"] and len(plan["steps"]) == 12
        batch = call("batch.execute", steps=steps, label="Nested green finish")
        assert batch["completed_steps"] == 12 and batch["operation"]["scope"] == "logical_batch"
        compare(guard)
        assert all(content(g) == expected for g, expected in initial_contents.items())
        captures["green_texture_variant"] = capture()
        captures["protected_midway"] = capture("Protected Prop")
        while len(tracked) > first_count:
            undo(tracked.pop())
        compare(first_snapshot)
        assert all(content(g) == expected for g, expected in first_contents.items())
        assert bpy.data.node_groups.get("Variant Finish") is None
        captures["recovered_blue"] = capture()
        while tracked:
            undo(tracked.pop())
        tracking = False
        compare(baseline)
        assert all(content(g) == expected for g, expected in initial_contents.items())
        assert sorted(g.name for g in bpy.data.node_groups) == group_names
        assert sorted(m.name for m in bpy.data.materials) == material_names
        assert sorted(o.name for o in bpy.context.selected_objects) == selection
        assert hashlib.sha256(texture_path.read_bytes()).hexdigest() == source_hash
        captures["recovered_original"] = capture()
        captures["protected_after"] = capture("Protected Prop")
        bpy.ops.preferences.addon_disable(module="blender_codex_bridge")
        print("BLENDER_SHADER_GROUPS_OK " + json.dumps({"blender": bpy.app.version_string,
            "transitive_shared_scope_verified": True, "nested_authoring_and_image_binding_verified": True,
            "instance_inputs_and_links_preserved": True, "protected_group_content_unchanged": True,
            "staged_native_recovery_verified": True, "partial_failure_recovery_verified": True,
            "logical_revision_batch_verified": True, "undo_steps_preference": bpy.context.preferences.edit.undo_steps,
            "source_file_unchanged": True, "captures": captures,
            "visual_review_required": True, "project_saved": False, "user_preferences_saved": False}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.)
