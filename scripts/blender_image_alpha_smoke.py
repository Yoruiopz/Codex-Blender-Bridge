"""Compare generated/file alpha through a real image-textured transparent material.

UI fixture: run via the private-desktop native runner, never launch directly.
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))


def run():
    try:
        assert not bpy.app.background
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge import pixel_codecs as codecs
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_external_files = prefs.allow_save_project = prefs.allow_delete_objects = False
        runtime.registry.enable_toolset("materials")
        runtime.dispatch("image.create", {"new_name": "Bridge Float", "width": 8, "height": 4,
            "color": [.25,.5,.75,.25]})
        source = array("f", [.25,.5,.75,.25])*32
        folder = tempfile.TemporaryDirectory(prefix="bridge-alpha-appearance-")
        paths, inputs = {}, [bpy.data.images["Bridge Float"]]
        for format in ("PNG8", "PNG16", "EXR32"):
            layout = codecs.interpretation(format, "COLOR")
            path = Path(folder.name) / (format+layout["extension"])
            with path.open("xb") as stream:
                for step in codecs.encode_steps(source, 8, 4, format, "COLOR"):
                    stream.write(step.data)
            image = bpy.data.images.load(str(path), check_existing=False)
            image.name, image.colorspace_settings.name = format, layout["colorspace"]
            image.alpha_mode = layout["alpha_mode"]
            inputs.append(image)
        # A reviewed float PNG FILE in declared linear space exposes associated
        # ImBuf values. Verify actual typed painting normalizes that native source
        # without changing the original buffer, then render the converted version.
        linear_file = Path(folder.name) / "linear-source.png"
        with linear_file.open("xb") as stream:
            for step in codecs.encode_steps(source, 8, 4, "PNG16", "DATA"):
                stream.write(step.data)
        prefs.texture_directory, prefs.allow_external_files = folder.name, True
        runtime.dispatch("image.load", {"filepath": str(linear_file), "new_name": "Linear Float FILE",
            "colorspace": "Linear Rec.709", "alpha_mode": "STRAIGHT"})
        original = runtime.dispatch("image.inspect_pixels", {"image_name": "Linear Float FILE"})
        painted = runtime.dispatch("image.paint_version", {"image_name": "Linear Float FILE", "new_name": "Normalized FILE",
            "strokes": [{"points": [[.5,.5]], "radius_pixels": 1., "color": [1.,0.,0.,1.], "opacity": 0.}]})
        assert painted["source_associated_converted_to_straight"] and painted["painted_pixels"] == 0
        assert original["pixels_sha256_float32_le"] == runtime.dispatch("image.inspect_pixels", {"image_name": "Linear Float FILE"})["pixels_sha256_float32_le"]
        inputs.append(bpy.data.images["Normalized FILE"])
        plane = bpy.data.objects["Cube"]
        plane.data.clear_geometry()
        plane.data.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)], [], [(0,1,2,3)])
        uv = plane.data.uv_layers.new(name="Alpha UV")
        for loop, point in zip(uv.data, [(0,0),(1,0),(1,1),(0,1)], strict=True):
            loop.uv = point
        material = plane.active_material
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        texture = nodes.new("ShaderNodeTexImage")
        texture.interpolation = "Closest"
        emission = nodes.new("ShaderNodeEmission")
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        links = material.node_tree.links
        links.new(texture.outputs["Color"], emission.inputs["Color"])
        links.new(texture.outputs["Alpha"], mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emission.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs["Surface"])
        # Cycles evaluates the transparent shader without material surface-mode
        # version differences; the matched UI capture is added by later delivery.
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device, scene.cycles.samples = "CPU", 1
        scene.cycles.use_denoising = False
        scene.world.use_nodes = True
        scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0,0,0,1)
        camera = scene.camera
        camera.location, camera.rotation_euler = (0,0,3), (0,0,0)
        camera.data.type, camera.data.ortho_scale = "ORTHO", 2.
        scene.render.resolution_x = scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = False
        scene.view_settings.view_transform, scene.view_settings.look = "Standard", "None"
        scene.view_settings.exposure, scene.view_settings.gamma = 0., 1.
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode, scene.render.image_settings.color_depth = "RGBA", "8"
        observed = {}
        capture_folder = Path(tempfile.gettempdir()) / "bridge_alpha_evidence"
        capture_folder.mkdir()
        for image in inputs:
            texture.image = image
            path = capture_folder / ("alpha-"+image.name+".png")
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            rendered = bpy.data.images.load(str(path), check_existing=False)
            pixels = array("f", [0.])*(32*32*4)
            rendered.pixels.foreach_get(pixels)
            observed[image.name] = list(pixels[(16*32+16)*4:(16*32+16)*4+4])
            paths[image.name] = str(path)
        print("ALPHA_APPEARANCE_OBSERVATIONS " + json.dumps(observed), flush=True)
        expected_linear = [.0625,.125,.1875]
        expected_display = [12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055 for v in expected_linear]
        assert all(abs(observed["Bridge Float"][i]-expected_display[i]) < .008 for i in range(3)), (observed, expected_display)
        assert all(max(abs(value[i]-observed["Bridge Float"][i]) for i in range(3)) < .008 for value in observed.values()), observed
        print("BLENDER_IMAGE_ALPHA_OK " + json.dumps({"blender": bpy.app.version_string,
            "observed": observed, "captures": paths, "expected_display": expected_display,
            "associated_linear_file_normalization_verified": True,
            "project_saved": False, "user_preferences_saved": False}), flush=True)
        folder.cleanup()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(run, first_interval=1.)
