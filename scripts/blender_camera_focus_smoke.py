"""Tiny matched DOF pictures from registered setters; rendering is fixture-only."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def material(name, color):
    value = bpy.data.materials.new(name)
    value.use_nodes = True
    tree = value.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.)
    emission.inputs["Strength"].default_value = 1.
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return value


def card(scene, name, distance, center_x, size, colors):
    vertices, faces = [], []
    for row in range(9):
        for column in range(9):
            vertices.append((center_x + size * (column / 8 - .5), size * (row / 8 - .5), -distance))
    for row in range(8):
        for column in range(8):
            corner = row * 9 + column
            faces.append((corner, corner + 1, corner + 10, corner + 9))
    mesh = bpy.data.meshes.new(name + " Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for value in colors:
        mesh.materials.append(value)
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = (index // 8 + index % 8) % 2
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    return obj


def matched_snapshot(scene, camera, cards):
    """Declared numeric projection; excludes distance, outputs and Render Result."""
    data, dof = camera.data, camera.data.dof
    selected = sorted(obj.name for obj in bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    window = bpy.context.window
    world_tree = scene.world.node_tree
    materials = sorted({material for obj in cards for material in obj.data.materials}, key=lambda value: value.name)
    return {
        "scene": scene.name, "frame": [scene.frame_current, scene.frame_subframe],
        "units": [scene.unit_settings.system, scene.unit_settings.scale_length],
        "context": {"scene": bpy.context.scene.name, "view_layer": bpy.context.view_layer.name,
                    "window_scene": None if window is None else window.scene.name, "mode": bpy.context.mode,
                    "selected": selected, "active": None if active is None else active.name},
        "active_camera": scene.camera.name,
        "camera": {"object": camera.name, "data": data.name, "matrix": [list(row) for row in camera.matrix_world],
                   "type": data.type, "lens": data.lens, "sensor_width": data.sensor_width,
                   "sensor_height": data.sensor_height, "sensor_fit": data.sensor_fit,
                   "shift": [data.shift_x, data.shift_y], "clip": [data.clip_start, data.clip_end],
                   "dof_enabled": dof.use_dof, "focus_object": None if dof.focus_object is None else dof.focus_object.name,
                   "aperture": [dof.aperture_fstop, dof.aperture_blades, dof.aperture_rotation, dof.aperture_ratio]},
        "cards": [{"object": obj.name, "matrix": [list(row) for row in obj.matrix_world],
                   "hide_viewport": obj.hide_viewport, "hide_render": obj.hide_render,
                   "vertices": [list(vertex.co) for vertex in obj.data.vertices],
                   "faces": [list(face.vertices) for face in obj.data.polygons],
                   "material_indices": [face.material_index for face in obj.data.polygons],
                   "materials": [value.name for value in obj.data.materials]} for obj in cards],
        "materials": [{"name": value.name, "nodes": sorted((node.bl_idname, node.name) for node in value.node_tree.nodes),
                       "emission": [{"color": list(node.inputs["Color"].default_value),
                                     "strength": node.inputs["Strength"].default_value}
                                    for node in value.node_tree.nodes if node.bl_idname == "ShaderNodeEmission"],
                       "links": sorted((link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
                                       for link in value.node_tree.links)} for value in materials],
        "world": {"name": scene.world.name, "use_nodes": scene.world.use_nodes, "color": list(scene.world.color),
                  "graph": None if world_tree is None else {
                      "nodes": sorted((node.bl_idname, node.name) for node in world_tree.nodes),
                      "backgrounds": [{"color": list(node.inputs["Color"].default_value),
                                       "strength": node.inputs["Strength"].default_value}
                                      for node in world_tree.nodes if node.bl_idname == "ShaderNodeBackground"],
                      "links": sorted((link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
                                      for link in world_tree.links)}},
        "lighting": "Fixed emissive checker cards and untouched factory World graph; no Light objects",
        "render": {"engine": scene.render.engine, "device": scene.cycles.device,
                   "width": scene.render.resolution_x, "height": scene.render.resolution_y,
                   "percentage": scene.render.resolution_percentage, "pixel_aspect": [scene.render.pixel_aspect_x, scene.render.pixel_aspect_y],
                   "samples": scene.cycles.samples, "seed": scene.cycles.seed,
                   "adaptive": scene.cycles.use_adaptive_sampling, "denoising": scene.cycles.use_denoising,
                   "border": scene.render.use_border, "crop": scene.render.use_crop_to_border,
                   "film_transparent": scene.render.film_transparent,
                   "format": scene.render.image_settings.file_format,
                   "color_mode": scene.render.image_settings.color_mode, "color_depth": scene.render.image_settings.color_depth,
                   "view_transform": scene.view_settings.view_transform, "look": scene.view_settings.look,
                   "exposure": scene.view_settings.exposure, "gamma": scene.view_settings.gamma},
    }


def main():
    # Raw setup owns this disposable factory scene. It is not a public tool call.
    bpy.context.preferences.use_preferences_save = False
    scene = bpy.context.scene
    camera = scene.camera
    for obj in tuple(scene.objects):
        if obj != camera:
            bpy.data.objects.remove(obj, do_unlink=True)
    camera.location = (0., 0., 0.)
    camera.rotation_euler = (0., 0., 0.)
    camera.scale = (1., 1., 1.)
    camera.data.lens = 50.
    camera.data.sensor_width = 36.
    camera.data.sensor_fit = "HORIZONTAL"
    camera.data.clip_start, camera.data.clip_end = .1, 100.
    camera.data.shift_x = camera.data.shift_y = 0.
    scene.unit_settings.system = "NONE"
    scene.unit_settings.scale_length = 1.
    pale = material("Owned Pale Checker", (.9, .9, .9))
    near = material("Owned Near Blue Checker", (.01, .04, .3))
    far = material("Owned Far Red Checker", (.3, .015, .01))
    cards = [card(scene, "Owned Near Card", 2., -.36, .64, (pale, near)),
             card(scene, "Owned Far Card", 6., 1.08, 1.92, (pale, far))]
    for obj in scene.objects:
        obj.select_set(False)
    camera.select_set(True)
    bpy.context.view_layer.objects.active = camera
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples, scene.cycles.seed = 8, 0
    scene.cycles.use_adaptive_sampling = scene.cycles.use_denoising = False
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    scene.render.resolution_x, scene.render.resolution_y = 192, 128
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.
    scene.render.use_border = scene.render.use_crop_to_border = scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure, scene.view_settings.gamma = 0., 1.
    bpy.context.view_layer.update()
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        grants = {permission.value: True for permission in Permission}
        manager = PermissionManager(lambda: dict(grants))
        runtime.permissions = runtime.executor.permissions = manager
        runtime.registry.enable_toolset("scene_edit")
        configured = runtime.dispatch("camera.configure", {"object_name": camera.name,
                                      "dof_enabled": True, "clear_focus_object": True, "aperture_fstop": .7})
        assert configured["dof"]["enabled"] and camera.data.dof.focus_object is None
        descriptor = camera.data.dof.bl_rna.properties["focus_distance"]
        metadata = {"type": descriptor.type, "hard_min": descriptor.hard_min, "hard_max": descriptor.hard_max,
                    "subtype": descriptor.subtype, "unit": descriptor.unit, "readonly": descriptor.is_readonly}
        assert descriptor.type == "FLOAT" and not descriptor.is_readonly
        assert descriptor.hard_min <= 2. < 6. <= descriptor.hard_max
        expected = matched_snapshot(scene, camera, cards)
        captures = []
        for distance in (2., 6.):
            receipt = runtime.dispatch("camera.configure", {"object_name": camera.name, "focus_distance": distance})
            stored = struct.unpack("f", struct.pack("f", distance))[0]
            inspection = runtime.dispatch("object.inspect", {"object_name": camera.name})
            assert camera.data.dof.focus_distance == receipt["dof"]["focus_distance"] == stored
            assert inspection["camera"]["dof"]["focus_distance"] == stored
            before = matched_snapshot(scene, camera, cards)
            assert before == expected
            path = Path(tempfile.gettempdir()) / f"camera-focus-{int(distance)}.png"
            scene.render.filepath = str(path)
            assert bpy.ops.render.render(write_still=True) == {"FINISHED"}
            raw = path.read_bytes()
            assert raw[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", raw[16:24]) == (192, 128)
            assert matched_snapshot(scene, camera, cards) == before
            assert camera.data.dof.focus_distance == stored
            captures.append({"requested_focus_distance": distance, "stored_float32": stored,
                             "receipt": receipt, "inspection_dof": inspection["camera"]["dof"],
                             "png_path": str(path), "png_sha256": hashlib.sha256(raw).hexdigest(),
                             "png_bytes": len(raw), "width": 192, "height": 128,
                             "matched_projection_sha256": digest(before), "render_projection_preserved": True})
        assert captures[0]["png_sha256"] != captures[1]["png_sha256"]
        evidence = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
                    "source_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "descriptor": metadata, "matched_numeric_projection": expected, "captures": captures,
                    "fixture_only_setup_and_renders": True, "render_call_count": 2,
                    "excluded_from_matching": ["focus_distance", "owned render.filepath", "checkpoint marker/bookkeeping", "Render Result and render caches"],
                    "visual_review": "REQUIRED; root reviews the matched PNGs",
                    "public_render_acceptance": False, "native_mcp_end_to_end": False,
                    "project_saved": False, "release_readiness": "NOT_ASSESSED"}
        raw = (json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        path = Path(tempfile.gettempdir()) / "camera-focus-evidence.json"
        path.write_bytes(raw)
        print("BLENDER_CAMERA_FOCUS_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "captures": captures, "matched_projection_sha256": digest(expected), "descriptor": metadata,
            "fixture_only_renders": True, "project_saved": False, "visual_review": "REQUIRED",
            "public_render_acceptance": False, "release_readiness": "NOT_ASSESSED"}, sort_keys=True))
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
