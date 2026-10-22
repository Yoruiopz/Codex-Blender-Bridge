"""4K raw snapshot/recovery prototype; not an integrated public job acceptance.

Only the native runner's disposable writer/reader bundles cross processes. This
research records actual allocation/blocking and private generator safe points;
it does not imply UI responsiveness, native undo, resource caps or crash safety.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import sys
import time
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from blender_codex_bridge import pixel_codecs  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from native_resources import linux_available_memory, linux_process_memory  # noqa: E402

WIDTH = HEIGHT = 4096
CHANNELS = WIDTH*HEIGHT*4
REFERENCE_KEY = "_large_recovery_probe_original"


def memory():
    if sys.platform != "linux":
        raise RuntimeError("This research fixture requires measurable Linux cgroup-v2 headroom; other platforms are not silently qualified.")
    available = linux_available_memory()
    assert available >= 8*1024**3, "4K recovery research requires8GiB headroom; this is not constrained-memory acceptance"
    return available


def digest(values):
    return hashlib.sha256(values).hexdigest()


def pixels(image):
    result = array("f", [0.]) * len(image.pixels)
    started = time.perf_counter()
    image.pixels.foreach_get(result)
    return result, time.perf_counter()-started


def native_metadata(image):
    return (image.name, image.source, image.filepath, image.colorspace_settings.name,
            image.alpha_mode, bool(image.is_float), list(image.size), int(image.users))


def writer(bundle):
    headroom = memory()
    bpy.context.preferences.use_preferences_save = False
    pattern = array("f", [-0., -.125, 65536., -2., .1234567, 2., 4., 2., .5, .25, .75, 0., 1., 2., 3., 1.])
    values = pattern * (CHANNELS // len(pattern))
    wanted = digest(values)
    original = bpy.data.images.new("4K Original", WIDTH, HEIGHT, alpha=True, float_buffer=True)
    original.colorspace_settings.name, original.alpha_mode = "Non-Color", "CHANNEL_PACKED"
    original.pixels.foreach_set(values)
    original.update()
    material = bpy.data.materials.new("4K Protected Material")
    material.use_nodes = True
    material.use_fake_user = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = original
    native_before = native_metadata(original)
    # Model an actual disconnected owner event in the private encoder. The
    # product scheduler/transport integration remains a separate required test.
    owner = ConnectionLifetime()
    lifetime = RequestLifetime(connection=owner)
    lifetime.delivered.set()
    partial = pixel_codecs.encode_steps(values, WIDTH, HEIGHT, "EXR32_RAW", "DATA", check=lifetime.check)
    names_before = sorted(image.name for image in bpy.data.images)
    next(partial)
    owner.disconnected.set()
    interrupted = time.perf_counter()
    try:
        next(partial)
    except BridgeError as error:
        assert error.code == "TIMEOUT" and error.context["connection_disconnected"]
    else:
        raise AssertionError("Disconnected private encoder did not stop")
    finally:
        partial.close()
    cancellation_seconds = time.perf_counter()-interrupted
    assert sorted(image.name for image in bpy.data.images) == names_before
    chunks, intervals, safe_points = [], [], 0
    started = last = time.perf_counter()
    for step in pixel_codecs.encode_steps(values, WIDTH, HEIGHT, "EXR32_RAW", "DATA"):
        now = time.perf_counter()
        intervals.append(now-last)
        last = now
        safe_points += 1
        if step.data:
            chunks.append(step.data)
    encoding_seconds = time.perf_counter()-started
    joined = time.perf_counter()
    payload = b"".join(chunks)
    payload_join_seconds = time.perf_counter()-joined
    del chunks
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    snapshot = bpy.data.images.new("4K Raw Snapshot", WIDTH, HEIGHT, alpha=True, float_buffer=True)
    snapshot.source, snapshot.filepath = "FILE", "//.probe-owned/4k-raw.exr"
    snapshot.colorspace_settings.name, snapshot.alpha_mode = "Non-Color", "CHANNEL_PACKED"
    packed = time.perf_counter()
    snapshot.pack(data=payload, data_len=len(payload))
    pack_seconds = time.perf_counter()-packed
    assert hashlib.sha256(snapshot.packed_file.data).hexdigest() == payload_sha256
    snapshot[REFERENCE_KEY] = original
    snapshot.use_fake_user = True
    decoded = time.perf_counter()
    actual, get_seconds = pixels(snapshot)
    native_decode_and_get_seconds = time.perf_counter()-decoded
    assert len(actual) == CHANNELS and digest(actual) == wanted
    del actual, payload
    original_now, original_get_seconds = pixels(original)
    assert digest(original_now) == wanted
    # The only added original reference is the recorded exact snapshot pointer.
    expected_native = list(native_before)
    expected_native[-1] += 1
    assert list(native_metadata(original)) == expected_native
    del original_now, values
    gc.collect()
    project = bundle / "4k-raw-recovery.blend"
    saved = time.perf_counter()
    bpy.ops.wm.save_as_mainfile(filepath=str(project), check_existing=False, relative_remap=False)
    save_seconds = time.perf_counter()-saved
    result = {"phase": "writer", "blender_version": bpy.app.version_string,
        "image_size": [WIDTH, HEIGHT], "channels": CHANNELS, "raw_digest": wanted,
        "packed_sha256": payload_sha256, "packed_bytes": snapshot.packed_file.size,
        "available_bytes_before_allocation": headroom, "memory": linux_process_memory(),
        "processor": platform.processor(), "machine": platform.machine(),
        "encoding_seconds": encoding_seconds, "encoder_yields": safe_points,
        "maximum_encoder_yield_interval_seconds": max(intervals),
        "payload_join_seconds": payload_join_seconds, "native_pack_seconds": pack_seconds,
        "native_decode_and_get_seconds": native_decode_and_get_seconds,
        "native_foreach_get_seconds": get_seconds, "original_foreach_get_seconds": original_get_seconds,
        "project_save_seconds": save_seconds, "private_generator_disconnect_seconds": cancellation_seconds,
        "disconnect_before_allocation_preserved_inventory": True,
        "protected_material": material.name, "protected_texture": texture.name, "project": project.name,
        "native_operation_interruptible": False, "scheduler_integrated": False,
        "typed_tools_verified": False, "native_undo_verified": False,
        "constrained_memory_acceptance": False, "release_readiness": "NOT_ASSESSED"}
    (bundle / "large-recovery-manifest.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def reader(bundle):
    headroom = memory()
    bpy.context.preferences.use_preferences_save = False
    manifest = json.loads((bundle / "large-recovery-manifest.json").read_text())
    bpy.ops.wm.open_mainfile(filepath=str(bundle / manifest["project"]), load_ui=False, use_scripts=False)
    original, snapshot = bpy.data.images["4K Original"], bpy.data.images["4K Raw Snapshot"]
    assert snapshot[REFERENCE_KEY] == original
    material = bpy.data.materials[manifest["protected_material"]]
    assert material.node_tree.nodes[manifest["protected_texture"]].image == original
    assert hashlib.sha256(snapshot.packed_file.data).hexdigest() == manifest["packed_sha256"]
    decoded = time.perf_counter()
    values, get_seconds = pixels(snapshot)
    decode_seconds = time.perf_counter()-decoded
    assert len(values) == CHANNELS and digest(values) == manifest["raw_digest"]
    # Generated getters recreate a native buffer without opening any FILE path.
    old, old_get_seconds = pixels(original)
    assert digest(old) != manifest["raw_digest"]
    del old
    identity, metadata = original.as_pointer(), native_metadata(original)
    writing = time.perf_counter()
    original.pixels.foreach_set(values)
    original.update()
    write_seconds = time.perf_counter()-writing
    actual, restored_get_seconds = pixels(original)
    assert digest(actual) == manifest["raw_digest"] and original.as_pointer() == identity
    assert native_metadata(original) == metadata and snapshot[REFERENCE_KEY] == original
    assert material.node_tree.nodes[manifest["protected_texture"]].image == original
    result = {"phase": "reader", "blender_version": bpy.app.version_string,
        "image_size": [WIDTH, HEIGHT], "complete_raw_pixels_restored": True,
        "native_original_id_reference_and_binding_preserved": True, "fresh_process_reader": True,
        "external_file_reload": False, "available_bytes_before_allocation": headroom,
        "native_decode_and_get_seconds": decode_seconds, "native_foreach_get_seconds": get_seconds,
        "original_foreach_get_seconds": old_get_seconds, "native_write_update_seconds": write_seconds,
        "restored_foreach_get_seconds": restored_get_seconds, "memory": linux_process_memory(),
        "typed_tools_verified": False, "scheduler_integrated": False,
        "native_undo_verified": False, "constrained_memory_acceptance": False,
        "release_readiness": "NOT_ASSESSED"}
    (bundle / "large-recovery-reader.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    result = (writer if args.bridge_phase == "writer" else reader)(args.bridge_bundle.resolve(strict=True))
    result.update(process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid())
    print("BLENDER_IMAGE_LARGE_RECOVERY_PROBE_"+args.bridge_phase.upper()+"_OK "+json.dumps(result), flush=True)


main()
