"""Bounded image painting, color semantics, protected consumers and native pixel recovery."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import time
import traceback
import zlib
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))


def png(path):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"".join(b"\0" + bytes((128, 64, 32, 128)) * 128 for _ in range(64))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 64, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def run():
    try:
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        from blender_codex_bridge.tools import image_paint

        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_delete_objects = prefs.allow_save_project = prefs.allow_external_files = False
        for toolset in ("materials", "nodes", "objects", "interaction"):
            runtime.registry.enable_toolset(toolset)

        def call(method, **params):
            return runtime.dispatch(method, params)

        def undo():
            result = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert result["snapshot_marker_verified"], result

        def pixels(name, samples=None):
            return call("image.inspect_pixels", image_name=name, samples=samples or [])

        brush = {"points": [[.05, .2], [.95, .8]], "radius_pixels": 6., "hardness": .8,
                 "opacity": .8, "color": [1., .35, .02, .7]}
        # Generated color/data tools require material-edit consent, not external
        # files, arbitrary Python, deletion, saving or a hidden inspection grant.
        for role, color in (("COLOR", [.05, .1, .3, .5]), ("DATA", [.2, .2, .2, 1.])):
            prefs.allow_inspect_scene = False
            created = call("image.create", new_name="Generated Canvas", width=16, height=16, role=role, color=color)
            version = call("image.paint_version", image_name="Generated Canvas", new_name="Generated Paint",
                           strokes=[{**brush, "color": [.9, .7, .1, 1.]}])
            assert version["source_pixels_unchanged"] and version["role"] == role
            prefs.allow_inspect_scene = True
            assert pixels("Generated Canvas")["pixels_sha256_float32_le"] == created["pixels_sha256_float32_le"]
            assert pixels("Generated Paint")["pixels_sha256_float32_le"] == version["pixels_sha256_float32_le"]
            undo()
            assert bpy.data.images.get("Generated Paint") is None
            assert pixels("Generated Canvas")["pixels_sha256_float32_le"] == created["pixels_sha256_float32_le"]
            undo()
            assert bpy.data.images.get("Generated Canvas") is None

        started = time.perf_counter()
        large = call("image.create", new_name="Bounded Canvas", width=1024, height=1024,
                     role="COLOR", color=[.05, .1, .3, 1.])
        created_seconds = time.perf_counter() - started
        started = time.perf_counter()
        large_paint = call("image.paint_version", image_name="Bounded Canvas", new_name="Bounded Paint",
                           strokes=[{**brush, "radius_pixels": 80.}])
        painted_seconds = time.perf_counter() - started
        started = time.perf_counter()
        assert pixels("Bounded Paint")["pixels_sha256_float32_le"] == large_paint["pixels_sha256_float32_le"]
        inspected_seconds = time.perf_counter() - started
        assert pixels("Bounded Canvas")["pixels_sha256_float32_le"] == large["pixels_sha256_float32_le"]
        assert large_paint["painted_pixels"] > 100_000
        undo()
        assert pixels("Bounded Canvas")["pixels_sha256_float32_le"] == large["pixels_sha256_float32_le"]
        undo()

        directory = Path(tempfile.gettempdir()) / "paint-sources"
        directory.mkdir()
        path = directory / "source.png"
        png(path)
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        prefs.texture_directory, prefs.allow_external_files = str(directory), True
        call("image.load", filepath=str(path), new_name="Original Pixels", colorspace="sRGB", alpha_mode="STRAIGHT")
        original = pixels("Original Pixels", [[64, 32]])
        assert all(abs(a - b) < 1e-7 for a, b in zip(original["samples"][0]["rgba"], [128/255, 64/255, 32/255, 128/255], strict=True))
        # Native preparation only defines the negative-control material consumers.
        # All pixel creation/painting and final node rebinding use typed bridge tools.
        panel = bpy.data.objects["Cube"]
        panel.name = "Paint Panel"
        panel.data.clear_geometry()
        panel.data.from_pydata([(-1, -.5, 0), (1, -.5, 0), (1, .5, 0), (-1, .5, 0)], [], [(0, 1, 2, 3)])
        uv = panel.data.uv_layers.new(name="Canvas UV")
        for loop, coordinate in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
            loop.uv = coordinate
        material = panel.active_material
        material.name = "Protected Canvas"
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name, node.image = "Albedo", bpy.data.images["Original Pixels"]
        shader = material.node_tree.nodes["Principled BSDF"]
        material.node_tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
        material.node_tree.links.new(node.outputs["Alpha"], shader.inputs["Alpha"])
        uv_node = material.node_tree.nodes.new("ShaderNodeUVMap")
        uv_node.name, uv_node.uv_map = "Canvas Coordinates", "Canvas UV"
        material.node_tree.links.new(uv_node.outputs["UV"], node.inputs["Vector"])
        protected = panel.copy()
        protected.name, protected.location.x = "Protected Panel", 3.5
        bpy.context.scene.collection.objects.link(protected)
        call("material.copy_for_object", object_name="Paint Panel", slot_index=0, new_name="Working Canvas")
        initial_selection = sorted(obj.name for obj in bpy.context.selected_objects)
        initial_active = bpy.context.view_layer.objects.active.name
        baseline = call("scene.snapshot", object_names=["Protected Panel", "Camera", "Light"])
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((0, 0, 1)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 2.5

        def capture(name="Paint Panel"):
            return call("viewport.capture", object_name=name, shading="material", view="current",
                        include_overlays=False, resolution=[768, 512])["path"]

        def unchanged():
            result = call("scene.compare", snapshot_id=baseline["snapshot_id"])
            assert result["coverage_complete"] and result["status"] == "unchanged_within_scope", result
            assert pixels("Original Pixels")["pixels_sha256_float32_le"] == original["pixels_sha256_float32_le"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == file_hash

        def denied(code):
            count = len(bpy.data.images)
            try:
                call("image.paint_version", image_name="Original Pixels", new_name="Denied Paint", strokes=[brush])
            except BridgeError as error:
                assert error.code == code, error.to_dict()
            else:
                raise AssertionError("Expected image paint denial")
            assert len(bpy.data.images) == count and bpy.data.images.get("Denied Paint") is None

        captures = {"before": capture(), "protected_before": capture("Protected Panel")}
        for preference in ("allow_edit_materials", "allow_external_files"):
            setattr(prefs, preference, False)
            denied("PERMISSION_DENIED")
            setattr(prefs, preference, True)
        for flag, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            getattr(runtime.state, "set_" + flag)(True)
            denied(code)
            getattr(runtime.state, "set_" + flag)(False)
            runtime.state.set_paused(False)
        call("context.set_mode", object_name="Paint Panel", mode="EDIT")
        denied("NOT_IMPLEMENTED")
        call("context.set_mode", object_name="Paint Panel", mode="OBJECT")
        call("selection.set", object_names=initial_selection, active_object=initial_active)
        runtime.checkpoints.clear()
        call("checkpoint.create", description="Scoped canvas texture painting")
        conversion = call("image.paint_version", image_name="Original Pixels", new_name="Color Conversion Probe", strokes=[{**brush, "opacity": 0.}])
        assert conversion["painted_pixels"] == 0 and conversion["source_srgb_converted_to_linear"]
        call("nodes.set_image", material_name="Working Canvas", node_name="Albedo", image_name="Color Conversion Probe")
        captures["conversion_only"] = capture()
        undo()
        undo()
        unchanged()
        painted = call("image.paint_version", image_name="Original Pixels", new_name="Painted Pixels", strokes=[brush])
        measured = pixels("Painted Pixels", [[64, 32], [0, 0]])
        alpha = .56 + (128/255) * .44
        # Independent standard-sRGB values for the exact fixture byte triplet,
        # not a call back into the conversion implementation being tested.
        rgb = [.21586050011389926, .05126945837404324, .014443843596092545]
        expected = [(color * .56 + old * (128/255) * .44) / alpha for color, old in zip(brush["color"][:3], rgb, strict=True)] + [alpha]
        assert all(abs(a - b) < 2e-6 for a, b in zip(measured["samples"][0]["rgba"], expected, strict=True)), measured
        assert all(abs(a - b) < 2e-6 for a, b in zip(measured["samples"][1]["rgba"], [*rgb, 128/255], strict=True))
        assert measured["pixels_sha256_float32_le"] == painted["pixels_sha256_float32_le"]
        call("nodes.set_image", material_name="Working Canvas", node_name="Albedo", image_name="Painted Pixels")
        captures["painted"] = capture()
        erased = call("image.paint_version", image_name="Painted Pixels", new_name="Erased Pixels",
                      strokes=[{"points": [[.5, .5]], "radius_pixels": 8., "hardness": 1., "opacity": .5,
                                "blend": "ERASE_ALPHA", "color": [1, 1, 1, 1]}])
        erased_sample = pixels("Erased Pixels", [[64, 32]])["samples"][0]["rgba"]
        assert erased_sample[:3] == measured["samples"][0]["rgba"][:3] and abs(erased_sample[3] - alpha / 2) < 2e-6
        assert pixels("Painted Pixels")["pixels_sha256_float32_le"] == painted["pixels_sha256_float32_le"]
        call("nodes.set_image", material_name="Working Canvas", node_name="Albedo", image_name="Erased Pixels")
        captures["erased"] = capture()
        unchanged()
        for _ in range(4):
            undo()
            unchanged()
        assert bpy.data.images.get("Painted Pixels") is None and bpy.data.images.get("Erased Pixels") is None
        captures["recovered"] = capture()

        # Real post-write faults: do not force-unlink an unexpected new consumer.
        for kind in ("transient", "delete_denied", "unexpected_user", "cancelled"):
            # Explicit fixture consent only for scoped removal of Failed Paint;
            # the denied case must retain the image until confirmed native undo.
            prefs.allow_delete_objects = kind in {"transient", "cancelled"}
            original_read = image_paint._read
            fired = [False]
            def fault(context, image, *, modifying=False, kind=kind, original_read=original_read, fired=fired):
                result = original_read(context, image, modifying=modifying)
                if image.name == "Failed Paint" and not fired[0]:
                    fired[0] = True
                    if kind == "unexpected_user":
                        bpy.data.materials["Working Canvas"].node_tree.nodes.new("ShaderNodeTexImage").image = image
                    if kind == "cancelled":
                        raise BridgeError("TIMEOUT", "Injected cancellation after native pixel write")
                    raise RuntimeError("Injected post-write pixel readback failure")
                return result
            image_paint._read = fault
            try:
                call("image.paint_version", image_name="Original Pixels", new_name="Failed Paint", strokes=[brush])
            except BridgeError as error:
                assert error.context["rollback_verified"] is (kind in {"transient", "cancelled"})
                assert error.context["possible_mutation"] is (kind in {"unexpected_user", "delete_denied"})
                assert error.context["cleanup_permission_denied"] is (kind == "delete_denied")
                assert error.context["undo_boundary_finalized"]
                if kind == "cancelled":
                    assert error.code == "TIMEOUT"
            else:
                raise AssertionError("Post-write fault was reported as success")
            finally:
                image_paint._read = original_read
                prefs.allow_delete_objects = False
            if kind == "delete_denied":
                assert bpy.data.images["Failed Paint"].users == 0
            undo()
            assert bpy.data.images.get("Failed Paint") is None
            unchanged()
        captures["protected_after"] = capture("Protected Panel")
        captures["final_recovered"] = capture()
        assert sorted(obj.name for obj in bpy.context.selected_objects) == initial_selection
        assert bpy.context.view_layer.objects.active.name == initial_active and bpy.context.mode == "OBJECT"
        assert bpy.context.preferences.edit.undo_steps == 32
        print("BLENDER_TEXTURE_PAINT_OK " + json.dumps({"blender": bpy.app.version_string,
              "generated_color_and_data_verified": True, "source_over_and_alpha_eraser_verified": True,
              "byte_srgb_storage_and_explicit_linear_conversion_verified": True,
              "protected_consumers_and_pixels_unchanged": True, "post_write_failure_and_cancellation_recovered": True,
              "native_pixel_versions_recovered": True, "painted_pixels": painted["painted_pixels"],
              "bounded_1024_square_workload": {"create_seconds": created_seconds, "paint_seconds": painted_seconds,
                  "inspect_seconds": inspected_seconds, "painted_pixels": large_paint["painted_pixels"],
                  "candidate_pixel_tests": large_paint["candidate_pixel_tests"], "responsive_job_verified": False},
              "erased_pixels": erased["painted_pixels"], "captures": captures,
              "full_texture_paint_workflow_verified": False, "project_saved": False,
              "user_preferences_saved": False}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1)
