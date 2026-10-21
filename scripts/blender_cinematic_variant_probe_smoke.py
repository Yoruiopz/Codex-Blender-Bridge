"""Native-only probe of cinematic controls, reference accounting and pinned renders."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_camera_evidence import compare_rgba8, rgba8

CAMERA_FIELDS = ("type", "lens", "lens_unit", "sensor_fit", "sensor_width", "sensor_height",
                 "shift_x", "shift_y", "clip_start", "clip_end", "ortho_scale")
DOF_FIELDS = ("use_dof", "focus_distance", "aperture_fstop", "aperture_blades", "aperture_rotation", "aperture_ratio")
LIGHT_FIELDS = ("type", "energy", "color", "use_shadow", "shadow_soft_size", "angle", "spot_size",
                "spot_blend", "shape", "size", "size_y", "use_square", "use_nodes", "normalize",
                "exposure", "diffuse_factor", "specular_factor", "volume_factor", "transmission_factor",
                "use_custom_distance", "cutoff_distance", "shadow_buffer_clip_start", "use_shadow_jitter",
                "shadow_filter_radius", "shadow_jitter_overblur", "spread", "shadow_maximum_resolution",
                "shadow_resolution_scale", "use_soft_falloff")


def value(item):
    if item is None or isinstance(item, (str, bool, int, float)):
        return item
    if hasattr(item, "name"):
        return item.name
    return [value(part) for part in item]


def properties(owner, names):
    return {name: value(getattr(owner, name)) for name in names if hasattr(owner, name)}


def numeric_state(camera, lights):
    def obj_state(obj):
        return {"name": obj.name, "data": obj.data.name, "rotation_mode": obj.rotation_mode,
                "location": list(obj.location), "rotation_quaternion": list(obj.rotation_quaternion),
                "rotation_euler": list(obj.rotation_euler), "rotation_axis_angle": list(obj.rotation_axis_angle),
                "scale": list(obj.scale), "delta_location": list(obj.delta_location),
                "delta_rotation_euler": list(obj.delta_rotation_euler),
                "delta_rotation_quaternion": list(obj.delta_rotation_quaternion), "delta_scale": list(obj.delta_scale),
                "matrix_world": [list(row) for row in obj.matrix_world]}
    return {"camera": {**obj_state(camera), "settings": properties(camera.data, CAMERA_FIELDS),
                       "dof": properties(camera.data.dof, DOF_FIELDS),
                       "focus_object": value(camera.data.dof.focus_object)},
            "lights": [{**obj_state(light), "settings": properties(light.data, LIGHT_FIELDS)} for light in lights]}


def membership(scene, obj):
    users = bpy.data.user_map(subset={obj}).get(obj, ())
    return {"scene_user_of_id": scene.user_of_id(obj),
            "root_user_of_id": scene.collection.user_of_id(obj),
            "root_link": scene.collection.objects.get(obj.name) == obj,
            "base_links": sum(layer.objects.get(obj.name) == obj for layer in scene.view_layers),
            "active_camera": scene.camera == obj,
            "users_scene": [item.name for item in obj.users_scene],
            "direct_users": sorted((item.bl_rna.identifier, item.name, item.user_of_id(obj)) for item in users),
            "collections": [(item.name, item.user_of_id(obj)) for item in obj.users_collection]}


def camera_point(obj, location, target=(0., 0., .3)):
    obj.location = location
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (Vector(target)-obj.location).to_track_quat("-Z", "Y")


def image_bytes(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = tuple(image.size)
        data = rgba8(tuple(image.pixels[:]))
        assert len(data) == width*height*4
        return width, height, data
    finally:
        bpy.data.images.remove(image)


def main():
    assert bpy.app.background and not bpy.data.filepath
    scene = bpy.context.scene
    original_camera = scene.camera
    camera_data = bpy.data.cameras.new("Probe Camera Data")
    camera = bpy.data.objects.new("Probe Camera", camera_data)
    scene.collection.objects.link(camera)
    bpy.context.view_layer.update()
    ordinary = membership(scene, camera)
    scene.camera = camera
    active = membership(scene, camera)
    assert active["scene_user_of_id"] == ordinary["scene_user_of_id"]+1
    assert ordinary["scene_user_of_id"] == ordinary["root_user_of_id"]+ordinary["base_links"]
    assert active["scene_user_of_id"] == active["root_user_of_id"]+active["base_links"]+1
    marker = scene.timeline_markers.new("Probe Unreviewed Marker")
    marker.camera = camera
    marker_state = membership(scene, camera)
    assert marker_state["scene_user_of_id"] == active["scene_user_of_id"]+1
    scene.timeline_markers.remove(marker)
    original_camera.data.dof.focus_object = camera
    focus_consumer = membership(scene, camera)
    assert any(kind == "Camera" for kind, _name, _count in focus_consumer["direct_users"])
    original_camera.data.dof.focus_object = None
    assert membership(scene, camera) == active
    scene.camera = original_camera

    camera_schema = properties(camera_data, CAMERA_FIELDS)
    dof_schema = properties(camera_data.dof, DOF_FIELDS)
    camera_enums = {name: [item.identifier for item in camera_data.bl_rna.properties[name].enum_items]
                    for name in ("type", "lens_unit", "sensor_fit")}
    light_schema = {}
    for kind in ("POINT", "SUN", "SPOT", "AREA"):
        data = bpy.data.lights.new("Probe "+kind+" Data", type=kind)
        light_schema[kind] = properties(data, LIGHT_FIELDS)
        if kind == "AREA":
            light_schema[kind]["shape_choices"] = [item.identifier for item in data.bl_rna.properties["shape"].enum_items]
        bpy.data.lights.remove(data)
    render_schema = {"engine": scene.render.engine,
                     "eevee": properties(scene.eevee, ("taa_samples", "taa_render_samples", "use_raytracing")),
                     "cycles": properties(scene.cycles, ("samples", "preview_samples", "seed", "use_animated_seed", "use_denoising")),
                     "view": properties(scene.view_settings, ("view_transform", "look", "exposure", "gamma", "use_curve_mapping")),
                     "render": properties(scene.render, ("pixel_aspect_x", "pixel_aspect_y", "film_transparent", "fps", "fps_base")),
                     "frame": [scene.frame_current, scene.frame_subframe]}
    print("CINEMATIC_VARIANT_NATIVE_SCHEMA "+json.dumps({"blender_version": bpy.app.version_string,
        "camera": camera_schema, "camera_enums": camera_enums, "dof": dof_schema, "lights": light_schema,
        "render": render_schema, "ordinary_camera": ordinary, "active_camera": active,
        "marker_camera": marker_state, "focus_incoming_consumer": focus_consumer}), flush=True)

    # Small matched scene with two independent lights and a deliberate unrelated
    # active camera. A camera render must pin the requested camera, then restore.
    cube = bpy.data.objects["Cube"]
    material = bpy.data.materials.new("Probe Blue Metal")
    material.diffuse_color = (.12, .35, .55, 1.)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (.12, .35, .55, 1.)
    shader.inputs["Metallic"].default_value = .15
    shader.inputs["Roughness"].default_value = .35
    cube.data.materials.clear()
    cube.data.materials.append(material)
    floor_mesh = bpy.data.meshes.new("Probe Floor Data")
    floor_mesh.from_pydata([(-5., -5., -1.01), (5., -5., -1.01), (5., 5., -1.01), (-5., 5., -1.01)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new("Probe Floor", floor_mesh)
    scene.collection.objects.link(floor)
    lights = []
    for name, location, energy, color in (("Probe Key", (4., -4., 6.), 750., (1., .72, .4)),
                                         ("Probe Fill", (-4., -1., 3.), 300., (.35, .6, 1.))):
        data = bpy.data.lights.new(name+" Data", type="AREA")
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        data.shape, data.size, data.size_y = "RECTANGLE", 4., 2.5
        data.energy, data.color = energy, color
        camera_point(obj, location)
        lights.append(obj)
    default_light = bpy.data.objects.get("Light")
    if default_light:
        default_light.hide_render = True
    world = scene.world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (.05, .05, .05, 1.)
    background.inputs["Strength"].default_value = .25
    camera_point(camera, (5., -6., 4.))
    camera_data.lens, camera_data.sensor_fit = 50., "HORIZONTAL"
    camera_data.sensor_width, camera_data.sensor_height = 36., 24.
    camera_data.clip_start, camera_data.clip_end = .1, 100.
    camera_data.dof.use_dof = False
    camera_data.dof.focus_distance = 8.
    camera_data.dof.aperture_fstop, camera_data.dof.aperture_blades = 4., 6
    camera_data.dof.aperture_rotation, camera_data.dof.aperture_ratio = .2, 1.2
    bpy.context.view_layer.update()
    a_numeric = numeric_state(camera, lights)
    protected = [tuple(vertex.co) for vertex in cube.data.vertices]
    selected = tuple(bpy.context.selected_objects)
    active_object = bpy.context.view_layer.objects.active
    saved_render = properties(scene.render, ("filepath", "resolution_x", "resolution_y", "resolution_percentage",
                                              "use_border", "use_crop_to_border", "film_transparent"))
    saved_image = properties(scene.render.image_settings, ("file_format", "color_mode", "color_depth"))
    saved_samples = properties(scene.eevee, ("taa_samples", "taa_render_samples", "use_raytracing"))
    output = Path(tempfile.gettempdir()).resolve()/"cinematic_variant_probe"
    output.mkdir()

    def render(label):
        path = output/(label+".png")
        assert not path.exists()
        try:
            scene.camera = camera
            scene.render.filepath = str(path)
            scene.render.resolution_x, scene.render.resolution_y = 384, 256
            scene.render.resolution_percentage = 100
            scene.render.use_border = scene.render.use_crop_to_border = False
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA"
            scene.render.image_settings.color_depth = "8"
            for name in ("taa_samples", "taa_render_samples"):
                if hasattr(scene.eevee, name):
                    setattr(scene.eevee, name, 16)
            if hasattr(scene.eevee, "use_raytracing"):
                scene.eevee.use_raytracing = False
            assert bpy.ops.render.render(write_still=True, use_viewport=False) == {"FINISHED"}
        finally:
            for name, setting in saved_render.items():
                setattr(scene.render, name, setting)
            for name, setting in saved_image.items():
                setattr(scene.render.image_settings, name, setting)
            for name, setting in saved_samples.items():
                setattr(scene.eevee, name, setting)
            scene.camera = original_camera
        assert properties(scene.render, saved_render) == saved_render
        assert properties(scene.render.image_settings, saved_image) == saved_image
        assert properties(scene.eevee, saved_samples) == saved_samples
        assert scene.camera == original_camera
        width, height, pixels = image_bytes(path)
        assert (width, height) == (384, 256)
        return path, pixels

    render("warmup")
    a_path, a_pixels = render("a")
    camera_point(camera, (4., -5., 3.))
    camera_data.lens, camera_data.shift_x = 62., .08
    lights[0].data.energy, lights[0].data.color = 1000., (.25, .55, 1.)
    lights[1].data.energy, lights[1].data.color = 175., (1., .4, .15)
    bpy.context.view_layer.update()
    b_numeric = numeric_state(camera, lights)
    b_path, b_pixels = render("b")
    camera.location = a_numeric["camera"]["location"]
    camera.rotation_quaternion = a_numeric["camera"]["rotation_quaternion"]
    camera_data.lens, camera_data.shift_x = a_numeric["camera"]["settings"]["lens"], a_numeric["camera"]["settings"]["shift_x"]
    for light, record in zip(lights, a_numeric["lights"], strict=True):
        light.data.energy, light.data.color = record["settings"]["energy"], record["settings"]["color"]
    bpy.context.view_layer.update()
    assert numeric_state(camera, lights) == a_numeric
    restored_path, restored_pixels = render("a_restored")
    changed = compare_rgba8(a_pixels, b_pixels, 384, 256)
    restored = compare_rgba8(a_pixels, restored_pixels, 384, 256)
    assert changed["changed_pixels"] > 384*256//10
    assert restored["changed_pixels"] == 0
    assert [tuple(vertex.co) for vertex in cube.data.vertices] == protected
    assert tuple(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active_object
    assert scene.camera == original_camera
    print("BLENDER_CINEMATIC_VARIANT_PROBE_OK "+json.dumps({"blender_version": bpy.app.version_string,
        "field_schema": {"camera": camera_schema, "dof": dof_schema, "lights": light_schema},
        "render_schema": render_schema, "ordinary_camera_membership": ordinary, "active_camera_membership": active,
        "extra_marker_reference_detected": True, "incoming_camera_dof_consumer_detected": True,
        "pinned_scene_camera_and_render_settings_restored": True, "full_rgba8_changes": changed,
        "full_rgba8_restoration": restored, "camera_b": b_numeric["camera"],
        "captures": {"a": str(a_path), "b": str(b_path), "a_restored": str(restored_path)},
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (a_path, b_path, restored_path)},
        "project_saved": False, "product_variant_domain_implemented": False}), flush=True)


if __name__ == "__main__":
    main()
