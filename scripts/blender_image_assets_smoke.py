"""Approved image imports, isolated textured-prop revision and independently verified recovery."""

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


def png(path, size=128, *, blue=False, roughness=False, width=None):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            if roughness:
                shade = 45 if (x // 16 + y // 16) % 2 else 200
                color = (shade, shade, shade)
            elif min(x, y, size - 1 - x, size - 1 - y) < 7:
                color = (22, 28, 36)
            elif 22 < x < size - 22 and (25 < y < 31 or 37 < y < 41):
                color = (238, 238, 224)
            elif (x // 20 + y // 20) % 2:
                color = (18, 82, 155) if blue else (221, 100, 22)
            else:
                color = (42, 125, 193) if blue else (249, 165, 40)
            row.extend((*color, 255))
        rows.append(bytes(row))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width or size, size, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def run():
    try:
        # The runner provides separate config/scripts/datafiles folders before enabling the add-on.
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime

        runtime, prefs = get_runtime(), get_preferences()
        assert prefs.texture_directory == ""
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = False
        for name in ("materials", "nodes", "objects"):
            runtime.registry.enable_toolset(name)
        directory = Path(tempfile.gettempdir()) / "texture-sources"
        directory.mkdir()
        outside = Path(tempfile.gettempdir()) / "outside.png"
        png(outside, size=16)
        paths = {name: directory / f"{name}.png" for name in ("orange", "blue", "roughness")}
        png(paths["orange"])
        png(paths["blue"], blue=True)
        png(paths["roughness"], roughness=True)
        oversized = directory / "oversized.png"
        png(oversized, size=8, width=8193)
        damaged = directory / "damaged.png"
        damaged.write_bytes(b"not an image")
        jpeg = directory / "small.jpg"
        generated = bpy.data.images.new("JPEG Fixture Source", 8, 8)
        generated.file_format, generated.filepath_raw = "JPEG", str(jpeg)
        generated.save()
        bpy.data.images.remove(generated)
        source_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [*paths.values(), jpeg, outside]}

        cube = bpy.data.objects["Cube"]
        cube.name = "Textured Prop"
        base = cube.data.materials[0]
        base.name = "Shared Surface"
        protected_pattern = bpy.data.images.new("Protected Pattern", 32, 32)
        protected_pattern.pixels.foreach_set([value for y in range(32) for x in range(32)
            for value in ((.05, .15, .3, 1.) if (x // 8 + y // 8) % 2 else (.5, .6, .7, 1.))])
        texture = base.node_tree.nodes.new("ShaderNodeTexImage")
        texture.name, texture.image = "Surface Texture", protected_pattern
        base.node_tree.links.new(texture.outputs["Color"], base.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
        protected = cube.copy()
        protected.name = "Protected Prop"
        protected.location.x = 4
        bpy.context.scene.collection.objects.link(protected)
        assert protected.data == cube.data
        unloaded = bpy.data.images.new("Unloaded Outside", 1, 1)
        unloaded.filepath, unloaded.source = str(outside), "FILE"
        unloaded.buffers_free()
        assert not unloaded.has_data
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                region = area.spaces.active.region_3d
                region.view_rotation = Vector((5, -6, 4)).to_track_quat("Z", "Y")
                region.view_distance = 5.5

        tracked = []
        tracking = False

        def call(method, **params):
            result = runtime.dispatch(method, params)
            spec = runtime.registry.get(method)
            if tracking and spec.modifies and spec.automatic_checkpoint:
                assert result["operation"]["undo_boundary_finalized"]
                tracked.append(method)
            return result

        def denied(method, code, **params):
            names = sorted(i.name for i in bpy.data.images)
            try:
                call(method, **params)
            except BridgeError as error:
                assert error.code == code, error.to_dict()
            else:
                raise AssertionError(f"Expected {method} denial")
            assert sorted(i.name for i in bpy.data.images) == names

        def compare(snapshot):
            result = call("scene.compare", snapshot_id=snapshot["snapshot_id"])
            assert result["coverage_complete"] and result["status"] == "unchanged_within_scope", result

        def undo(expected=None):
            result = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            if expected is not None:
                assert result["tracked_agent_label"] == expected

        def capture(name="Textured Prop"):
            regions = [a.spaces.active.region_3d for a in bpy.context.screen.areas if a.type == "VIEW_3D"]
            before = [r.view_location.copy() for r in regions]
            try:
                for region in regions:
                    region.view_location = bpy.data.objects[name].matrix_world.translation
                return call("viewport.capture", object_name=name, view="current", shading="material",
                            include_overlays=False, resolution=[640, 480])["path"]
            finally:
                for region, location in zip(regions, before, strict=True):
                    region.view_location = location

        denied("image.load", "PERMISSION_DENIED", filepath=str(paths["orange"]), new_name="Denied")
        prefs.allow_external_files = True
        denied("image.load", "PERMISSION_DENIED", filepath=str(paths["orange"]), new_name="Denied")
        prefs.texture_directory = str(directory)
        denied("image.load", "PERMISSION_DENIED", filepath=str(outside), new_name="Denied")
        denied("image.load", "INVALID_ARGUMENT", filepath=str(damaged), new_name="Denied")
        denied("image.load", "INVALID_ARGUMENT", filepath=str(oversized), new_name="Denied")
        denied("nodes.set_image", "INVALID_ARGUMENT", material_name="Shared Surface", node_name="Surface Texture", image_name="Protected Pattern")
        for stopped, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            getattr(runtime.state, f"set_{stopped}")(True)
            denied("image.load", code, filepath=str(paths["orange"]), new_name="Denied")
            assert call("image.inspect", image_name="Unloaded Outside")["images"][0]["loaded_size"] is None
            getattr(runtime.state, f"set_{stopped}")(False)
        runtime.state.set_paused(False)
        assert not bpy.data.images["Unloaded Outside"].has_data
        prefs.allow_delete_objects = True
        denied("image.remove", "INVALID_ARGUMENT", image_name="Unused JPEG")
        prefs.allow_delete_objects = False
        call("image.load", filepath=str(jpeg), new_name="Unused JPEG", colorspace="Non-Color")
        call("image.load", filepath=str(jpeg), new_name="Unused Color JPEG", colorspace="sRGB")
        assert bpy.data.images["Unused JPEG"] != bpy.data.images["Unused Color JPEG"]
        assert bpy.data.images["Unused JPEG"].colorspace_settings.name == "Non-Color"
        undo("image.load")
        assert bpy.data.images.get("Unused Color JPEG") is None
        denied("image.remove", "PERMISSION_DENIED", image_name="Unused JPEG", confirm_unused=True)
        prefs.allow_delete_objects = True
        removed = call("image.remove", image_name="Unused JPEG", confirm_unused=True)
        assert not removed["file_deleted"] and bpy.data.images.get("Unused JPEG") is None and jpeg.is_file()
        undo("image.remove")
        assert bpy.data.images.get("Unused JPEG") is not None
        undo("image.load")
        assert bpy.data.images.get("Unused JPEG") is None
        prefs.allow_delete_objects = False

        baseline_images = sorted(i.name for i in bpy.data.images)
        baseline = call("scene.snapshot", object_names=["Textured Prop", "Protected Prop"])
        guard = call("scene.snapshot", object_names=["Protected Prop"])
        protected_pixels = tuple(bpy.data.images["Protected Pattern"].pixels[:])
        selected = sorted(o.name for o in bpy.context.selected_objects)
        images = {"before_material": capture(), "protected_before": capture("Protected Prop")}
        call("checkpoint.create", description="Texture and revise an isolated shared-mesh prop")
        tracking = True
        call("image.load", filepath=str(paths["orange"]), new_name="Panel Orange", colorspace="sRGB")
        call("image.load", filepath=str(paths["roughness"]), new_name="Panel Roughness", colorspace="Non-Color")
        call("material.copy_for_object", object_name="Textured Prop", slot_index=0, new_name="Isolated Surface")
        call("nodes.set_image", material_name="Isolated Surface", node_name="Surface Texture", image_name="Panel Orange", interpolation="Closest", extension="CLIP")
        call("nodes.add", material_name="Isolated Surface", node_type="ShaderNodeTexImage", name="Roughness Texture")
        call("nodes.set_image", material_name="Isolated Surface", node_name="Roughness Texture", image_name="Panel Roughness", interpolation="Linear")
        call("nodes.link", material_name="Isolated Surface", from_node="Roughness Texture", from_socket="Color", to_node="Principled BSDF", to_socket="Roughness")
        call("material.set_principled", material_name="Isolated Surface", metallic=.35)
        first_variant = call("scene.snapshot", object_names=["Textured Prop", "Protected Prop"])
        assert bpy.data.objects["Textured Prop"].data == bpy.data.objects["Protected Prop"].data
        assert bpy.data.objects["Protected Prop"].material_slots[0].material.name == "Shared Surface"
        compare(guard)
        images["orange_material"] = capture()
        images["protected_midway"] = capture("Protected Prop")
        call("image.load", filepath=str(paths["blue"]), new_name="Panel Blue", colorspace="sRGB")
        call("nodes.set_image", material_name="Isolated Surface", node_name="Surface Texture", image_name="Panel Blue", interpolation="Linear")
        current = call("image.inspect", image_name="Panel Blue")["images"][0]
        assert current["loaded_size"] == [128, 128] and current["colorspace"] == "sRGB"
        assert call("image.inspect", image_name="Panel Roughness")["images"][0]["colorspace"] == "Non-Color"
        compare(guard)
        images["blue_revision"] = capture()
        undo(tracked.pop())
        compare(first_variant)
        undo(tracked.pop())
        assert bpy.data.images.get("Panel Blue") is None
        compare(first_variant)
        images["recovered_orange"] = capture()
        while tracked:
            undo(tracked.pop())
        tracking = False
        compare(baseline)
        assert sorted(i.name for i in bpy.data.images) == baseline_images
        assert tuple(bpy.data.images["Protected Pattern"].pixels[:]) == protected_pixels
        assert sorted(o.name for o in bpy.context.selected_objects) == selected
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in source_hashes.items())
        images["recovered_original"] = capture()
        images["protected_after"] = capture("Protected Prop")
        bpy.ops.preferences.addon_disable(module="blender_codex_bridge")
        print("BLENDER_IMAGE_ASSETS_OK " + json.dumps({"blender": bpy.app.version_string,
            "approved_folder_and_live_permissions_verified": True, "png_and_jpeg_verified": True,
            "shared_mesh_material_image_isolation_verified": True, "revision_and_exact_recovery_verified": True,
            "unloaded_inspection_does_not_load_files": True, "source_files_unchanged": True,
            "captures": images, "visual_review_required": True, "project_saved": False,
            "user_preferences_saved": False}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.)
