"""Disposable sculpt/vertex-color fixture with measured protected state and renders."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import surface_brushes  # noqa: E402


def coordinates(obj):
    return [tuple(vertex.co) for vertex in obj.data.vertices]


def main():
    assert bpy.app.background, "Use the isolated native runner"
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: False for permission in Permission}
    grants[Permission.EDIT_MESH.value] = grants[Permission.INSPECT_SCENE.value] = True
    manager = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("mesh")
    mesh = bpy.data.meshes.new("Brush Grid Mesh")
    mesh.from_pydata([(x, y, 0.) for y in (-1., 0., 1.) for x in (-1., 0., 1.)], [],
                     [(y * 3 + x, y * 3 + x + 1, (y + 1) * 3 + x + 1, (y + 1) * 3 + x) for y in range(2) for x in range(2)])
    mesh.update()
    uv = mesh.uv_layers.new(name="Protected UV")
    for loop, item in zip(mesh.loops, uv.data, strict=True):
        co = mesh.vertices[loop.vertex_index].co
        item.uv = ((co.x + 1.) / 2., (co.y + 1.) / 2.)
    obj = bpy.data.objects.new("Brush Grid", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.scale = (2., 1., 1.)
    material = bpy.data.materials.new("Protected Brush Material")
    material.use_nodes = True
    material.node_tree.nodes.clear()
    color = material.node_tree.nodes.new("ShaderNodeVertexColor")
    color.layer_name = "Paint"
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(color.outputs["Color"], emission.inputs["Color"])
    material.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
    mesh.materials.append(material)
    protected = obj.copy()
    protected.data = mesh.copy()
    protected.name = "Protected Brush Duplicate"
    protected.location.x = 8.
    bpy.context.scene.collection.objects.link(protected)
    bpy.data.objects["Cube"].hide_render = True
    bpy.context.view_layer.update()
    original, protected_original = coordinates(obj), coordinates(protected)
    selected = [item.name for item in bpy.context.selected_objects]
    active = bpy.context.view_layer.objects.active
    call = runtime.dispatch
    create = call("color_attribute.create", {"object_name": obj.name, "attribute_name": "Paint", "initial_color": [.05, .1, .2, 1.]})
    assert create["complete_color_readback_verified"] and create["entries"] == 9
    call("color_attribute.create", {"object_name": obj.name, "attribute_name": "Corners", "domain": "CORNER", "initial_color": [.1, .2, .3, 1.]})
    before_colors = [tuple(value.color) for value in mesh.color_attributes["Paint"].data]
    corner_before = [tuple(value.color) for value in mesh.color_attributes["Corners"].data]
    folder = Path(os.environ["TMPDIR"]) / "surface-evidence"
    folder.mkdir()
    scene = bpy.context.scene
    camera = bpy.data.objects["Camera"]
    camera.location = (0., -4.5, 5.)
    camera.rotation_euler = (Vector((0., 0., .1)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type, camera.data.ortho_scale = "ORTHO", 5.2
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.device, scene.cycles.samples = "CPU", 4
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = 96
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    def capture(filename):
        scene.render.filepath = str(folder / filename)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        values = tuple(image.pixels)
        return {"path": scene.render.filepath, "sha256": hashlib.sha256(Path(scene.render.filepath).read_bytes()).hexdigest()}, values
    before_capture, before_pixels = capture("surface-before.png")
    sculpt = call("mesh.sculpt_brush", {"object_name": obj.name, "vertex_indices": [4, 0], "mask_weights": [1., 0.],
        "strokes": [{"center": [0., 0., 0.], "radius": .75, "direction": [0., 0., 1.], "strength": .5}]})
    assert sculpt["changed_vertices"] == 1 and abs(mesh.vertices[4].co.z - .5) < 1e-7
    assert all(tuple(vertex.co) == original[index] for index, vertex in enumerate(mesh.vertices) if index != 4)
    smooth = call("mesh.sculpt_brush", {"object_name": obj.name, "vertex_indices": [4],
        "strokes": [{"center": [0., 0., .5], "radius": .75, "operation": "SMOOTH", "strength": .5, "falloff": "CONSTANT"}]})
    assert smooth["changed_vertices"] == 1 and abs(mesh.vertices[4].co.z - .25) < 1e-7
    world_center = obj.matrix_world @ mesh.vertices[4].co
    call("mesh.sculpt_brush", {"object_name": obj.name, "vertex_indices": [4], "space": "WORLD",
        "strokes": [{"center": list(world_center), "radius": .5, "direction": [1., 0., 0.], "strength": .2, "falloff": "CONSTANT"}]})
    assert abs(mesh.vertices[4].co.x - .1) < 1e-7  # WORLD direction under nonuniform scale.
    paint = call("color_attribute.paint", {"object_name": obj.name, "attribute_name": "Paint", "vertex_indices": [4, 1], "mask_weights": [1., 0.],
        "strokes": [{"center": list(mesh.vertices[4].co), "radius": .75, "color": [1., .1, .05, 1.], "falloff": "CONSTANT"}]})
    assert paint["changed_entries"] == 1
    assert all(tuple(item.color) == before_colors[index] for index, item in enumerate(mesh.color_attributes["Paint"].data) if index != 4)
    corner = call("color_attribute.paint", {"object_name": obj.name, "attribute_name": "Corners", "vertex_indices": [4],
        "strokes": [{"center": list(mesh.vertices[4].co), "radius": .75, "color": [0., 1., 0., 1.], "opacity": .5, "falloff": "CONSTANT"}]})
    assert corner["changed_entries"] == 4
    for loop in mesh.loops:
        if loop.vertex_index != 4:
            assert tuple(mesh.color_attributes["Corners"].data[loop.index].color) == corner_before[loop.index]
    page = call("color_attribute.inspect", {"object_name": obj.name, "attribute_name": "Corners", "max_entries": 2})
    assert page["truncated"] and page["next_offset"] == 2 and len(page["complete_colors_sha256_float32_le"]) == 64
    def denied(code, name, params):
        try:
            call(name, params)
        except BridgeError as error:
            assert error.code == code, error.to_dict()
            return error.context
        raise AssertionError("Expected a structured surface denial")
    denied("INVALID_ARGUMENT", "color_attribute.rename", {"object_name": obj.name, "attribute_name": "Paint", "new_name": "Changed"})
    assert material.node_tree.nodes.get(color.name).layer_name == "Paint"
    call("color_attribute.rename", {"object_name": obj.name, "attribute_name": "Corners", "new_name": "Corner Review", "acknowledge_named_consumers": True})
    denied("PERMISSION_DENIED", "color_attribute.remove", {"object_name": obj.name, "attribute_name": "Corner Review", "confirm_remove": True, "acknowledge_named_consumers": True})
    grants[Permission.DELETE_OBJECTS.value] = True
    removed = call("color_attribute.remove", {"object_name": obj.name, "attribute_name": "Corner Review", "confirm_remove": True, "acknowledge_named_consumers": True})
    assert not removed["named_consumers_rewritten"] and mesh.color_attributes.get("Corner Review") is None
    grants[Permission.EDIT_MESH.value] = False
    denied("PERMISSION_DENIED", "mesh.sculpt_brush", {"object_name": obj.name, "vertex_indices": [4],
        "strokes": [{"center": [0., 0., 0.], "radius": 1., "direction": [0., 0., 1.]}]})
    grants[Permission.EDIT_MESH.value] = True
    # Actual shared mesh and shape-key denials preserve the protected copy.
    alias = obj.copy()
    alias.name = "Shared Brush Alias"
    bpy.context.scene.collection.objects.link(alias)
    denied("NOT_IMPLEMENTED", "mesh.sculpt_brush", {"object_name": obj.name, "vertex_indices": [4],
        "strokes": [{"center": [0., 0., 0.], "radius": 1., "direction": [0., 0., 1.]}]})
    alias.data = mesh.copy()
    alias.hide_render = True
    protected.shape_key_add(name="Basis")
    denied("NOT_IMPLEMENTED", "color_attribute.create", {"object_name": protected.name, "attribute_name": "Denied"})
    assert coordinates(protected) == protected_original and protected.data.color_attributes.get("Denied") is None
    after_capture, after_pixels = capture("surface-after.png")
    changed_pixels = sum(before_pixels[index:index + 4] != after_pixels[index:index + 4] for index in range(0, len(before_pixels), 4))
    assert changed_pixels > 100 and before_capture["sha256"] != after_capture["sha256"]
    assert [item.name for item in bpy.context.selected_objects] == selected and bpy.context.view_layer.objects.active == active
    assert coordinates(protected) == protected_original
    # Direct handler fault injection proves cancellation truthfulness after a
    # native publication; it is not a claim of native global-undo restoration.
    initial = coordinates(obj)
    context = SimpleNamespace(require=lambda *required: manager.require(required), state=None, check_cancelled=None)
    def late_cancel():
        if coordinates(obj) != initial:
            raise BridgeError("TIMEOUT", "Injected late surface cancellation")
    context.check_cancelled = late_cancel
    try:
        surface_brushes.sculpt_brush(context, {"object_name": obj.name, "vertex_indices": [4],
            "strokes": [{"center": list(mesh.vertices[4].co), "radius": .75, "direction": [0., 0., 1.], "strength": .1}]})
    except BridgeError as error:
        assert error.code == "TIMEOUT" and error.context["execution_started"] and error.context["possible_mutation"]
    else:
        raise AssertionError("Late sculpt cancellation should retain possible-mutation evidence")
    print("BLENDER_SURFACE_BRUSHES_OK " + json.dumps({"blender_version": bpy.app.version_string,
        "sculpt_push_smooth_world_verified": True, "point_corner_paint_verified": True,
        "protected_geometry_uv_materials_context_verified": True,
        "shared_shapekey_permission_denials_verified": True, "late_failure_possible_mutation_verified": True,
        "captures": {"before": before_capture, "after": after_capture, "changed_rgba_pixels": changed_pixels},
        "native_undo_verified": False, "artistic_quality_accepted": False, "release_readiness": "NOT_ASSESSED"}), flush=True)
    blender_codex_bridge.unregister()


main()
