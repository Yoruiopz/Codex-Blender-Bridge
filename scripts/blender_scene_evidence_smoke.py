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
