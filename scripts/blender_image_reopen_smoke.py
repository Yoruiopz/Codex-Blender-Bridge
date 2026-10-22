"""Save/reopen texture delivery in independent owned processes; use the native runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from native_camera_evidence import compare_rgba8, rgba8  # noqa: E402
from native_fixture_save import serialize_owned_fixture  # noqa: E402


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def setup(bundle):
    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime
    runtime, prefs = get_runtime(), get_preferences()
    prefs.allow_execute_python = prefs.allow_delete_objects = False
    prefs.allow_edit_materials = True
    assert not prefs.allow_external_files and prefs.texture_directory == "", "A fresh profile must not inherit file consent"
    for toolset in ("materials", "nodes"):
        runtime.registry.enable_toolset(toolset)
    return runtime, prefs


def deny(runtime, code, method, **params):
    from blender_codex_bridge.errors import BridgeError
    names = sorted(image.name for image in bpy.data.images)
    try:
        runtime.dispatch(method, params)
    except BridgeError as error:
        assert error.code == code, error.to_dict()
    else:
        raise AssertionError(f"Expected {method} to fail with {code}")
    assert sorted(image.name for image in bpy.data.images) == names


def camera_setup():
    plane = bpy.data.objects["Cube"]
    plane.data.clear_geometry()
    plane.data.from_pydata([(-1,-.5,0),(1,-.5,0),(1,.5,0),(-1,.5,0)], [], [(0,1,2,3)])
    uv = plane.data.uv_layers.new(name="ReopenUV")
    for loop, point in zip(uv.data, [(0,0),(1,0),(1,1),(0,1)], strict=True):
        loop.uv = point
    material = plane.active_material
    material.name, material.use_nodes = "Reopen Material", True
    nodes = material.node_tree.nodes
    nodes.clear()
    texture, output = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeOutputMaterial")
    texture.name, texture.interpolation = "Camera Texture", "Closest"
    emission, transparent, mix = nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeBsdfTransparent"), nodes.new("ShaderNodeMixShader")
    links = material.node_tree.links
    for source, destination in ((texture.outputs["Color"], emission.inputs["Color"]), (texture.outputs["Alpha"], mix.inputs[0]),
                                (transparent.outputs[0], mix.inputs[1]), (emission.outputs[0], mix.inputs[2]), (mix.outputs[0], output.inputs[0])):
        links.new(source, destination)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device, scene.cycles.samples, scene.cycles.use_denoising = "CPU", 1, False
    scene.camera.location, scene.camera.rotation_euler = (0,0,3), (0,0,0)
    scene.camera.data.type, scene.camera.data.ortho_scale = "ORTHO", 2.5
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0,0,0,1)
    scene.render.resolution_x = scene.render.resolution_y = 32
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform, scene.view_settings.look = "Standard", "None"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode, scene.render.image_settings.color_depth = "RGBA", "8"


def capture(bundle, phase, name, image):
    node = bpy.data.materials["Reopen Material"].node_tree.nodes["Camera Texture"]
    previous = node.image
    path = bundle / f"{phase}-{name}.png"
    scene, old_path = bpy.context.scene, bpy.context.scene.render.filepath
    try:
        node.image = image
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        loaded = bpy.data.images.load(str(path), check_existing=False)
        try:
            values = array("f", [0.]) * (32 * 32 * 4)
            loaded.pixels.foreach_get(values)
            return rgba8(values).hex()
        finally:
            bpy.data.images.remove(loaded)
    finally:
        node.image, scene.render.filepath = previous, old_path


def export(runtime, source, name, path, format):
    started = runtime.dispatch("image.export_job_start", {"image_name": source, "new_name": name,
        "filepath": str(path), "format": format, "time_limit_seconds": 300.})
    deadline = time.monotonic() + 360
    while runtime.jobs.active is not None and time.monotonic() < deadline:
        runtime.jobs.tick()
    result = runtime.dispatch("jobs.inspect", {"job_id": started["job_id"]})
    assert result["state"] == "SUCCEEDED", result
    assert result["external_effects"]["file_published"] and result["result"]["pixel_verification"]["all_channels_compared"] > 0
    return result


def writer(bundle):
    runtime, prefs = setup(bundle)
    prefs.allow_external_files, prefs.texture_directory = True, str(bundle)
    textures, projects = bundle / "textures", bundle / "projects"
    textures.mkdir()
    projects.mkdir()
    camera_setup()
    call = runtime.dispatch
    records = []
    for role in ("COLOR", "DATA"):
        source_name = f"Protected {role} Source"
        call("image.create", {"new_name": source_name, "role": role, "width": 8, "height": 4, "color": [.25,.5,.75,.25]})
        values = array("f", [v for y in range(4) for x in range(8) for v in
                             (.125 + x / 16, .125 + y / 8, .75, (x % 4) / 3)])
        source = bpy.data.images[source_name]
        source.pixels.foreach_set(values)
        source.update()
        keep = bpy.data.materials["Reopen Material"].node_tree.nodes.new("ShaderNodeTexImage")
        keep.image = source  # Real consumers, not cache lifetime or fake-user assumptions.
        for format in ("PNG8", "PNG16", "EXR32", "EXR32_RAW"):
            name = f"{role}_{format}"
            path = textures / (name + (".png" if format.startswith("PNG") else ".exr"))
            exported = export(runtime, source_name, name, path, format)
            node = bpy.data.materials["Reopen Material"].node_tree.nodes.new("ShaderNodeTexImage")
            node.name = f"Stored {name}"
            call("nodes.set_image", {"material_name": "Reopen Material", "node_name": node.name, "image_name": name})
            protected = bpy.data.materials["Reopen Material"].node_tree.nodes.new("ShaderNodeTexImage")
            protected.name, protected.image = f"Protected {name}", bpy.data.images[name]
            pixels = call("image.inspect_pixels", {"image_name": name})
            records.append({"name": name, "node": node.name, "file": str(path.relative_to(bundle)),
                "file_sha256": exported["external_effects"]["file_sha256"],
                "pixel_digest": pixels["pixels_sha256_float32_le"], "channels": 8 * 4 * 4,
                "camera_rgba8": capture(bundle, "writer", name, bpy.data.images[name])})
    # Complete 4K raw DATA evidence, including signed/HDR and zero-alpha channels.
    from blender_large_paint_smoke import check_memory_headroom
    check_memory_headroom()
    large = bpy.data.images.new("Protected 4K Source", 4096, 4096, alpha=True, float_buffer=True)
    large.colorspace_settings.name, large.alpha_mode = "Non-Color", "CHANNEL_PACKED"
    values = array("f", [.25, -.125, 65536., -2.]) * (4096 * 4096)
    for (x, y), color in {(0,0): [-0.,1.,2.,3.], (4095,0): [4.,5.,6.,7.],
                          (0,4095): [-1.,-2.,-3.,-4.], (4095,4095): [8.,9.,10.,11.]}.items():
        offset = (y * 4096 + x) * 4
        values[offset:offset+4] = array("f", color)
    large.pixels.foreach_set(values)
    large.update()
    digest = hashlib.sha256(values).hexdigest()
    del values
    keep = bpy.data.materials["Reopen Material"].node_tree.nodes.new("ShaderNodeTexImage")
    keep.image = large
    exported = export(runtime, large.name, "Full4K", textures / "Full4K.exr", "EXR32_RAW")
    node = bpy.data.materials["Reopen Material"].node_tree.nodes.new("ShaderNodeTexImage")
    node.name = "Stored Full4K"
    call("nodes.set_image", {"material_name": "Reopen Material", "node_name": node.name, "image_name": "Full4K"})
    records.append({"name": "Full4K", "node": node.name, "file": "textures/Full4K.exr",
        "file_sha256": exported["external_effects"]["file_sha256"], "pixel_digest": digest, "channels": 4096 * 4096 * 4})
    project = projects / "asset.blend"
    prefs.allow_save_project = False
    deny(runtime, "PERMISSION_DENIED", "project.save", filepath=str(project))
    assert not project.exists()
    prefs.allow_save_project = True
    fixture_save = serialize_owned_fixture(runtime, project)
    for record in records:
        record["stored_path"] = bpy.data.images[record["name"]].filepath
        assert record["stored_path"].startswith("//../textures/"), record
        assert file_hash(bundle / record["file"]) == record["file_sha256"]
    manifest = {"project": "projects/asset.blend", "project_sha256": file_hash(project), "images": records,
                "generated_input_pixels_after_reopen_certified": False}
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finish("writer", {**fixture_save, "project_sha256": manifest["project_sha256"], "images": len(records), "saved": True})


def reader(bundle, manifest):
    runtime, prefs = setup(bundle)
    first = manifest["images"][0]
    request = {"material_name": "Reopen Material", "node_name": first["node"], "new_image_name": "Denied"}
    deny(runtime, "PERMISSION_DENIED", "nodes.refresh_image", **request)
    prefs.allow_external_files, prefs.texture_directory = True, str(bundle)
    call = runtime.dispatch
    comparisons = []
    for record in manifest["images"]:
        assert file_hash(bundle / record["file"]) == record["file_sha256"]
        source = bpy.data.images[record["name"]]
        assert source.filepath == record["stored_path"]
        started = time.monotonic()
        revised = call("nodes.refresh_image", {"material_name": "Reopen Material", "node_name": record["node"],
            "new_image_name": f"Reopened {record['name']}"})
        assert not revised["previous_buffer_reloaded"] and not revised["image_identity_preserved"]
        elapsed = time.monotonic() - started
        name = revised["image"]["name"]
        observed = call("image.inspect_pixels", {"image_name": name, "include_statistics": record["name"] != "Full4K"})
        assert observed["pixels_sha256_float32_le"] == record["pixel_digest"], (record, observed)
        if "camera_rgba8" in record:
            captured = capture(bundle, "reader", record["name"], bpy.data.images[name])
            compared = compare_rgba8(bytes.fromhex(record["camera_rgba8"]), bytes.fromhex(captured), 32, 32)
            assert compared["changed_pixels"] == 0, compared
        else:
            compared = None
        comparisons.append({"image": record["name"], "channels": record["channels"],
            "full_pixel_digest_verified": True, "refresh_seconds": elapsed, "camera_comparison": compared})
        if record["name"] != "Full4K":
            protected = bpy.data.materials["Reopen Material"].node_tree.nodes[f"Protected {record['name']}"]
            assert protected.image == bpy.data.images[record["name"]]
    # Missing stored sources must fail; explicit absolute relocation remains repairable.
    path, hidden = bundle / first["file"], bundle / (first["file"] + ".unavailable")
    path.rename(hidden)
    try:
        deny(runtime, "INVALID_ARGUMENT", "nodes.refresh_image", **{**request, "new_image_name": "Missing"})
        replacement = bundle / manifest["images"][1]["file"]
        repaired = call("nodes.refresh_image", {**request, "new_image_name": "Relocated", "filepath": str(replacement)})
        assert repaired["image"]["name"] == "Relocated" and not repaired["previous_buffer_reloaded"]
    finally:
        hidden.rename(path)
    prefs.allow_external_files = False
    deny(runtime, "PERMISSION_DENIED", "image.inspect_pixels", image_name="Reopened DATA_PNG8")
    prefs.allow_external_files, prefs.allow_save_project = True, False
    denied_path = bundle / "projects" / "reader-denied.blend"
    deny(runtime, "PERMISSION_DENIED", "project.save", filepath=str(denied_path))
    assert not denied_path.exists()
    evidence = {"images": comparisons, "fresh_profile_consent_verified": True, "missing_source_repair_verified": True,
        "save_denial_verified": True, "project_unchanged": file_hash(bundle / manifest["project"]) == manifest["project_sha256"],
        "native_undo_verified": False, "artistic_quality_accepted": False, "release_readiness": "NOT_ASSESSED"}
    (bundle / "reader-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    finish("reader", evidence)


def finish(phase, evidence):
    print(f"BLENDER_IMAGE_REOPEN_{phase.upper()}_OK " + json.dumps({**evidence, "phase": phase,
        "process_id": os.getpid(), "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
        "blender_version": bpy.app.version_string}), flush=True)
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bundle = args.bridge_bundle.resolve(strict=True)
    if args.bridge_phase == "writer":
        writer(bundle)
    else:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        assert file_hash(bundle / manifest["project"]) == manifest["project_sha256"]
        bpy.ops.wm.open_mainfile(filepath=str(bundle / manifest["project"]))
        if bpy.app.background:
            reader(bundle, manifest)
        else:
            # File loading temporarily invalidates UI context; inspect on the next tick.
            bpy.app.timers.register(lambda: guarded(lambda: reader(bundle, manifest)), first_interval=.1)


def guarded(callback):
    try:
        callback()
    except Exception:
        traceback.print_exc()
        if bpy.app.background:
            raise
        # Exit-code and missing success marker retain a truthful failure.
        os._exit(1)


if __name__ == "__main__":
    if bpy.app.background:
        main()
    else:
        bpy.app.timers.register(lambda: guarded(main), first_interval=.1)
