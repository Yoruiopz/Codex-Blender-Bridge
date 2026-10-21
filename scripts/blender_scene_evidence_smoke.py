"""Disposable structural comparison fixture; never opens a user project."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools.animation import _action_fcurves  # noqa: E402


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: True for permission in Permission}
    manager = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("materials")
    cube = bpy.data.objects["Cube"]
    group = cube.vertex_groups.new(name="Fixture Weight")
    group.add([0], 0.25, "REPLACE")
    source = bpy.data.materials.new("Shared Surface")
    source.use_nodes = True
    cube.data.materials.clear()
    cube.data.materials.append(source)
    protected = cube.copy()
    protected.name = "Protected Object"
    protected.location.x = 3.0
    bpy.context.scene.collection.objects.link(protected)
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    geometry = [tuple(vertex.co) for vertex in cube.data.vertices]

    def snapshot(names, **params):
        return runtime.dispatch("scene.snapshot", {"object_names": names, **params})

    def compare(baseline):
        return runtime.dispatch("scene.compare", {"snapshot_id": baseline["snapshot_id"]})

    all_before = snapshot([cube.name, protected.name])
    protected_before = snapshot([protected.name])
    assert all_before["coverage_complete"] and protected_before["coverage_complete"]
    assert compare(all_before)["status"] == "unchanged_within_scope"
    runtime.dispatch("checkpoint.create", {"description": "Isolate fixture material"})
    runtime.dispatch(
        "material.copy_for_object",
        {
            "object_name": cube.name,
            "slot_index": 0,
            "new_name": "Local Surface",
        },
    )
    runtime.dispatch(
        "material.set_principled", {"material_name": "Local Surface", "roughness": 0.1}
    )
    changed = compare(all_before)
    assert changed["status"] == "changed" and changed["coverage_complete"]
    assert {item["object"] for item in changed["changes"]} == {cube.name}
    assert {item["field"] for item in changed["changes"]} == {"material_slots", "shader_inputs"}
    assert compare(protected_before)["status"] == "unchanged_within_scope"
    assert protected.material_slots[0].material == source
    assert [tuple(vertex.co) for vertex in cube.data.vertices] == geometry

    # Same slot name cannot hide a shared shader edit.
    roughness = source.node_tree.nodes.get("Principled BSDF").inputs["Roughness"]
    old_roughness = roughness.default_value
    runtime.dispatch(
        "material.set_principled",
        {"material_name": source.name, "roughness": 0.9, "allow_shared": True},
    )
    assert {item["field"] for item in compare(protected_before)["changes"]} == {"shader_inputs"}
    runtime.dispatch(
        "material.set_principled",
        {"material_name": source.name, "roughness": old_roughness, "allow_shared": True},
    )
    assert compare(protected_before)["status"] == "unchanged_within_scope"

    cube.data.vertices[0].co.x -= 0.125
    assert {item["field"] for item in compare(protected_before)["changes"]} == {"mesh_geometry"}
    cube.data.vertices[0].co = geometry[0]
    uv = cube.data.uv_layers.active.data[0]
    old_uv = tuple(uv.uv)
    uv.uv.x += 0.125
    assert {item["field"] for item in compare(protected_before)["changes"]} == {"uv"}
    cube.data.uv_layers.active.data[0].uv = old_uv
    assert tuple(cube.data.uv_layers.active.data[0].uv) == old_uv
    group.add([0], 0.5, "REPLACE")
    weight_comparison = compare(protected_before)
    assert {item["field"] for item in weight_comparison["changes"]} == {"weights"}, {
        "changes": weight_comparison["changes"],
        "shared_mesh": cube.data == protected.data,
        "cube_weights": [(item.group, item.weight) for item in cube.data.vertices[0].groups],
        "protected_weights": [
            (item.group, item.weight) for item in protected.data.vertices[0].groups
        ],
    }
    group.add([0], 0.25, "REPLACE")
    assert compare(protected_before)["status"] == "unchanged_within_scope"

    # Root-only evidence deliberately remains shallow; opt-in dependency evidence
    # catches same-count nested changes without decoding an image or loading files.
    nested = bpy.data.node_groups.new("Evidence Nested Shader", "ShaderNodeTree")
    nested.interface.new_socket(name="Strength", in_out="INPUT", socket_type="NodeSocketFloat")
    value = nested.nodes.new("ShaderNodeValue")
    instance = source.node_tree.nodes.new("ShaderNodeGroup")
    instance.node_tree = nested
    nested_before = snapshot([protected.name], fields=["shader_inputs", "shader_dependencies"])
    assert nested_before["coverage_complete"], nested_before
    old_value = value.outputs[0].default_value
    value.outputs[0].default_value = 0.375
    result = compare(nested_before)
    assert result["coverage_complete"] and {item["field"] for item in result["changes"]} == {"shader_dependencies"}, result
    value.outputs[0].default_value = old_value
    assert compare(nested_before)["status"] == "unchanged_within_scope"

    # Fixture-only edits construct independent legacy/layered Action definitions;
    # the product inspector reads definitions without evaluating arbitrary paths.
    cube.keyframe_insert("location", index=0, frame=1)
    cube.keyframe_insert("location", index=0, frame=10)
    action = cube.animation_data.action
    curves = list(_action_fcurves(action))
    channel = curves[0][0]
    animation_before = snapshot([cube.name], fields=["animation"])
    assert animation_before["coverage_complete"], animation_before
    old_point = tuple(channel.keyframe_points[0].co)
    channel.keyframe_points[0].co.y += 0.125
    result = compare(animation_before)
    assert result["coverage_complete"] and {item["field"] for item in result["changes"]} == {"animation"}, result
    channel.keyframe_points[0].co = old_point
    assert compare(animation_before)["status"] == "unchanged_within_scope"
    track = cube.animation_data.nla_tracks.new()
    track.name = "Evidence Track"
    strip = track.strips.new("Evidence Clip", 1, action)
    nla_before = snapshot([cube.name], fields=["animation"])
    assert nla_before["coverage_complete"], nla_before
    strip.scale = 1.25
    result = compare(nla_before)
    assert result["coverage_complete"] and result["status"] == "changed", result

    driver_curve = protected.driver_add("location", 1)
    driver = driver_curve.driver
    driver.type = "AVERAGE"
    variable = driver.variables.new()
    variable.type = "TRANSFORMS"
    variable.targets[0].id = cube
    variable.targets[0].transform_type = "LOC_X"
    # Blender creates a generator modifier for some native driver configurations;
    # its RNA is outside this evidence contract and must be removed explicitly in
    # the fixture rather than silently ignored by the product reader.
    for modifier in list(driver_curve.modifiers):
        driver_curve.modifiers.remove(modifier)
    driver_before = snapshot([protected.name], fields=["animation"])
    assert driver_before["coverage_complete"], driver_before
    variable.targets[0].transform_type = "LOC_Z"
    result = compare(driver_before)
    assert result["coverage_complete"] and result["status"] == "changed", result

    # Armature construction needs Edit Mode, then the inspector preserves context.
    bpy.ops.object.select_all(action="DESELECT")
    armature = bpy.data.armatures.new("Evidence Rig Data")
    rig = bpy.data.objects.new("Evidence Rig", armature)
    bpy.context.scene.collection.objects.link(rig)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("Evidence Bone")
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    rig_before = snapshot([rig.name], fields=["rig"])
    assert rig_before["coverage_complete"], rig_before
    rig.pose.bones[0].rotation_mode = "XYZ"
    rig.pose.bones[0].rotation_euler.x = 0.25
    result = compare(rig_before)
    assert result["coverage_complete"] and {item["field"] for item in result["changes"]} == {"rig"}, result
    assert bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active == rig and rig.select_get()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in selected:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active

    limited = snapshot([cube.name], max_elements=1)
    assert not limited["coverage_complete"] and compare(limited)["status"] == "unknown"
    lights = snapshot(["Camera", "Light"], fields=["mesh_geometry", "uv", "weights"])
    assert all(
        not field["applicable"]
        for obj in lights["state"]["objects"].values()
        for field in obj["fields"].values()
    )
    grants[Permission.INSPECT_SCENE.value] = False
    for method, params in (
        ("scene.snapshot", {"object_names": [cube.name]}),
        ("scene.compare", {"snapshot_id": all_before["snapshot_id"]}),
    ):
        try:
            runtime.dispatch(method, params)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Evidence bypassed Blender inspection permission")
    grants[Permission.INSPECT_SCENE.value] = True
    assert bpy.context.mode == "OBJECT"
    assert (
        list(bpy.context.selected_objects) == selected
        and bpy.context.view_layer.objects.active == active
    )
    runtime.prepare_for_file_load()
    try:
        compare(all_before)
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    else:
        raise AssertionError("Project lifecycle retained an old snapshot")
    print(
        "BLENDER_SCENE_EVIDENCE_OK "
        + json.dumps(
            {
                "blender": bpy.app.version_string,
                "protected_material_isolation_verified": True,
                "same_count_geometry_uv_weights_and_shader_changes_detected": True,
                "nested_shader_animation_driver_nla_and_rig_changes_detected": True,
                "incomplete_evidence_unknown": True,
                "permissions_and_lifecycle_verified": True,
                "selection_mode_preserved": True,
                "project_saved": False,
                "visual_quality_verified": False,
            }
        )
    )


try:
    main()
finally:
    blender_codex_bridge.unregister()
