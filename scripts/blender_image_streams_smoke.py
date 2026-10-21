"""Registered large PNG/EXR loading, numeric reuse, denial and native recovery.

Run only with run_blender_checks.py on its private Windows desktop.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import struct
import sys
import tempfile
import traceback
import zlib
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


def chunk(kind, data):
    return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)


def large_png(path):
    # Independent fixture: deterministic high-entropy PNG16 exceeds the old
    # 32 MiB envelope, without relying on the production pixel encoder.
    size, rng = 2048, random.Random(1701)
    expected = array("f", [0.])*(size*size*4)
    compressor = zlib.compressobj(6)
    with path.open("xb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 16, 6, 0, 0, 0)))
        for y in range(size):
            row = rng.randbytes(size*8)
            values = array("H")
            values.frombytes(row)
            if sys.byteorder == "little":
                values.byteswap()
            start = (size-1-y)*size*4
            expected[start:start+size*4] = array("f", (value/65535 for value in values))
            packed = compressor.compress(b"\0"+row)
            for offset in range(0, len(packed), 65536):
                stream.write(chunk(b"IDAT", packed[offset:offset+65536]))
        packed = compressor.flush()
        for offset in range(0, len(packed), 65536):
            stream.write(chunk(b"IDAT", packed[offset:offset+65536]))
        stream.write(chunk(b"IEND", b""))
    assert path.stat().st_size > 32*1024*1024
    return expected


def large_exr(path):
    from blender_codex_bridge.pixel_codecs import exr_header

    size = 4096
    expected = array("f", [.25, -.125, 65536., -2.])*(size*size)
    markers = {(0, 0): [-0., 1., 2., 3.], (size-1, 0): [4., 5., 6., 7.],
               (0, size-1): [-1., -2., -3., -4.], (size-1, size-1): [8., 9., 10., 11.]}
    for (x, y), rgba in markers.items():
        offset = (y*size+x)*4
        expected[offset:offset+4] = array("f", rgba)
    # Independent planar scanline writer, not encode_steps or TextureStaging.
    header = exr_header(size, size, "EXR32_RAW", "DATA")
    start, stride = len(header)+size*8, size*16+8
    with path.open("xb") as stream:
        stream.write(header)
        stream.write(b"".join(struct.pack("<Q", start+y*stride) for y in range(size)))
        for row in range(size):
            stream.write(struct.pack("<ii", row, size*16))
            for channel in (3, 2, 1, 0):
                values = array("f", [[.25, -.125, 65536., -2.][channel]])*size
                source_y = size-1-row
                for x in (0, size-1):
                    if (x, source_y) in markers:
                        values[x] = markers[(x, source_y)][channel]
                if sys.byteorder != "little":
                    values.byteswap()
                stream.write(values.tobytes())
    return expected


def run():
    try:
        assert not bpy.app.background, "Native undo requires the private-desktop runner"
        from blender_large_paint_smoke import check_memory_headroom
        available = check_memory_headroom()
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.pixel_codecs import encode_steps
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        runtime, prefs = get_runtime(), get_preferences()
        for toolset in ("materials", "nodes"):
            runtime.registry.enable_toolset(toolset)
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = False
        prefs.allow_external_files = False
        folder = Path(tempfile.gettempdir()) / "reviewed-image-streams"
        folder.mkdir()
        prefs.texture_directory = str(folder)
        surface = bpy.data.materials.new("Stream Verification Surface")
        surface.use_nodes, surface.use_fake_user = True, True
        texture = surface.node_tree.nodes.new("ShaderNodeTexImage")
        texture.name = "Stream Image"
        def call(method, **params):
            return runtime.dispatch(method, params)
        scene = call("scene.inspect")
        selection = call("selection.inspect")
        selected_names = sorted(obj.name for obj in bpy.context.selected_objects)
        active_name = bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None
        before = call("scene.snapshot", object_names=["Cube"])
        baseline_images = sorted(image.name for image in bpy.data.images)

        def unchanged():
            compared = call("scene.compare", snapshot_id=before["snapshot_id"])
            assert compared["coverage_complete"] and compared["status"] == "unchanged_within_scope", compared

        def deny(code, **params):
            names = sorted(image.name for image in bpy.data.images)
            try:
                call("image.load", **params)
            except BridgeError as error:
                assert error.code == code, error.to_dict()
            else:
                raise AssertionError("Expected an authoritative image-load denial")
            assert sorted(image.name for image in bpy.data.images) == names

        small = folder / "small.exr"
        with small.open("xb") as stream:
            for step in encode_steps(array("f", [.25, .5, .75, .25])*12, 4, 3, "EXR32", "COLOR"):
                stream.write(step.data)
        request = {"filepath": str(small), "new_name": "Ordinary Float", "colorspace": "Linear Rec.709", "alpha_mode": "PREMUL"}
        deny("PERMISSION_DENIED", **request)
        prefs.allow_external_files = True
        deny("INVALID_ARGUMENT", filepath=str(small), new_name="No Guessed Role")
        for flag, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            getattr(runtime.state, "set_"+flag)(True)
            deny(code, **request)
            getattr(runtime.state, "set_"+flag)(False)
        runtime.state.set_paused(False)  # Clearing emergency stop deliberately does not resume the agent.
        compressed = folder / "unreviewed.exr"
        data = bytearray(small.read_bytes())
        key = b"compression\0compression\0\1\0\0\0"
        data[data.index(key)+len(key)] = 3
        compressed.write_bytes(data)
        deny("NOT_IMPLEMENTED", **{**request, "filepath": str(compressed)})
        loaded = call("image.load", **request)
        assert loaded["source_file"]["streaming_preflight"] and loaded["source_file"]["format"] == "EXR"
        assert loaded["operation"]["undo_boundary_finalized"]
        actual = array("f", [0.])*48
        bpy.data.images["Ordinary Float"].pixels.foreach_get(actual)
        assert actual == array("f", [.0625, .125, .1875, .25])*12
        call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
        assert bpy.data.images.get("Ordinary Float") is None and small.is_file()
        observations = []
        for name, filename, factory, side in (("Large PNG Data", "large.png", large_png, 2048),
                                               ("Large Raw EXR", "large.exr", large_exr, 4096)):
            path = folder / filename
            expected = factory(path)
            digest, disk_digest = hashlib.sha256(expected).hexdigest(), file_hash(path)
            loaded = call("image.load", filepath=str(path), new_name=name, colorspace="Non-Color", alpha_mode="CHANNEL_PACKED")
            assert loaded["operation"]["undo_boundary_finalized"] and not loaded["file_written"]
            assert loaded["source_file"]["file_sha256"] == disk_digest
            pixels = call("image.inspect_pixels", image_name=name, include_statistics=False,
                          samples=[[0, 0], [side-1, 0], [0, side-1], [side-1, side-1]])
            max_error = 0.
            if filename.endswith(".exr"):
                assert pixels["pixels_sha256_float32_le"] == digest
                tolerance = 0.
            else:
                # U16 -> native float normalization can use a rounded reciprocal.
                # Check EVERY channel against independent double/U16 reference,
                # allowing one float32 ULP at 1, not a lost U16 quantization step.
                tolerance = 2**-23
                native = array("f", [0.])*len(expected)
                bpy.data.images[name].pixels.foreach_get(native)
                for actual_value, expected_value in zip(native, expected, strict=True):
                    assert math.isfinite(actual_value)
                    max_error = max(max_error, abs(actual_value-expected_value))
                del native
                assert max_error <= tolerance, max_error
            assert loaded["image"]["loaded_size"] == [side, side]
            bound = call("nodes.set_image", material_name="Stream Verification Surface", node_name="Stream Image", image_name=name)
            assert bound["source_file_at_binding"]["file_sha256"] == disk_digest
            assert bpy.data.materials["Stream Verification Surface"].node_tree.nodes["Stream Image"].image.name == name
            call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert bpy.data.materials["Stream Verification Surface"].node_tree.nodes["Stream Image"].image is None
            image = bpy.data.images[name]
            retained_loaded = bool(image.has_data)
            retained_digest = None
            if retained_loaded:
                native = array("f", [0.])*len(expected)
                image.pixels.foreach_get(native)
                retained_digest = hashlib.sha256(native).hexdigest()
                del native
                assert retained_digest == pixels["pixels_sha256_float32_le"]
            call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert bpy.data.images.get(name) is None and file_hash(path) == disk_digest
            unchanged()
            observations.append({"name": name, "size": [side, side], "file_bytes": path.stat().st_size,
                "filepath": str(path),
                "file_sha256": disk_digest, "source_pixels_sha256_float32_le": digest,
                "native_pixels_sha256_float32_le": pixels["pixels_sha256_float32_le"],
                "maximum_expected_channel_error": max_error, "native_normalization_tolerance": tolerance,
                "loaded_buffer_retained_after_binding_undo": retained_loaded,
                "retained_buffer_digest": retained_digest, "new_image_removed_by_native_undo": True,
                "external_file_unchanged_after_undo": True, "source_file": loaded["source_file"]})
            del expected
        assert sorted(image.name for image in bpy.data.images) == baseline_images
        unchanged()
        assert sorted(obj.name for obj in bpy.context.selected_objects) == selected_names
        assert (bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None) == active_name
        assert bpy.context.mode == selection["mode"] == "OBJECT"
        assert not prefs.allow_execute_python and not prefs.allow_save_project and not prefs.allow_delete_objects
        print("BLENDER_IMAGE_STREAMS_OK " + json.dumps({"blender": bpy.app.version_string,
            "initial_scene": scene["scene"],
            "initial_mode": selection.get("mode"), "observations": observations,
            "registered_tools_used": ["image.load", "image.inspect_pixels", "nodes.set_image", "checkpoint.undo_last"],
            "role_permission_pause_stop_and_compression_denials_verified": True,
            "protected_cube_scope_unchanged": True, "host_available_bytes_at_start": available,
            "project_saved": False, "user_preferences_saved": False,
            "scope": "Reviewed streaming imports/reuse/native recovery; not export jobs, durable input-pixel restoration or full artist acceptance"}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(run, first_interval=1.)
