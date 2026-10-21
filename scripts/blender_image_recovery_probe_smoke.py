"""Native Image-buffer recovery research in distinct isolated processes.

This fixture intentionally observes native data APIs before extending any typed
tool. In-place packed-payload replacement is a separate behavior from a loaded
pixel write, and remains explicitly identified in its evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
from blender_codex_bridge import pixel_codecs  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.tools import image_portability, images  # noqa: E402

WIDTH, HEIGHT = 16, 16


def digest(values):
    return hashlib.sha256(values).hexdigest()


def pixels(image):
    result = array("f", [0.]) * len(image.pixels)
    image.pixels.foreach_get(result)
    return result


def encode(values, format, role, *, srgb=False):
    return b"".join(step.data for step in pixel_codecs.encode_steps(
        values, WIDTH, HEIGHT, format, role, srgb=srgb))


def metadata(image):
    return {"name": image.name, "source": image.source, "filepath": image.filepath,
            "colorspace": image.colorspace_settings.name, "alpha_mode": image.alpha_mode,
            "is_float": image.is_float, "size": list(image.size)}


def protect(image):
    material = bpy.data.materials.new("Recovery " + image.name)
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    reference = bpy.data.images.new("Reference " + image.name, 1, 1)
    reference["exact_original"] = image
    reference.use_fake_user = True
    material.use_fake_user = True
    return {"material": material.name, "node": texture.name, "reference": reference.name}


def _row(image, before, desired, owner, method, **extra):
    return {"name": image.name, "method": method, "metadata": metadata(image),
            "before_sha256": digest(before), "desired_sha256": digest(desired),
            "actual_sha256": digest(pixels(image)), "owner": owner, **extra}


def writer(bundle):
    assert bpy.app.background
    bpy.context.preferences.use_preferences_save = False
    folder = bundle / "external"
    folder.mkdir()
    grants = {permission.value: True for permission in Permission}
    permissions = PermissionManager(lambda: grants)
    context = SimpleNamespace(require=lambda *required: permissions.require(required), check_cancelled=None,
        state=SimpleNamespace(snapshot=lambda: {"paused": False, "emergency_stopped": False}))
    images.get_preferences = lambda: SimpleNamespace(texture_directory=str(folder))
    # Exercise every representable byte in each channel, including hidden RGB
    # and all alpha values; getters establish the actual byte-ImBuf contract.
    desired = array("f", (channel / 255 for index in range(256)
        for channel in (index, 255-index, (index*37) % 256, (index*73) % 256)))
    initial = array("f", [.1, .2, .3, 1.]) * (WIDTH*HEIGHT)
    rows = []
    for source in ("GENERATED", "FILE"):
        for space in ("sRGB", "Linear Rec.709", "Non-Color"):
            for alpha in ("STRAIGHT", "CHANNEL_PACKED"):
                name = "Byte-" + "-".join((source, space, alpha))
                if source == "GENERATED":
                    image = bpy.data.images.new(name, WIDTH, HEIGHT, alpha=True, float_buffer=False)
                else:
                    path = folder / (name + ".png")
                    path.write_bytes(encode(initial, "PNG8", "DATA"))
                    image = bpy.data.images.load(str(path), check_existing=False)
                    image.name = name
                image.colorspace_settings.name, image.alpha_mode = space, alpha
                assert not image.is_float
                image.pixels.foreach_set(desired)
                image.update()
                expected = pixels(image)
                assert max(abs(a-b) for a, b in zip(expected, desired, strict=True)) < 1e-6
                owner = protect(image)
                snapshot_name = "Typed Snapshot " + str(len(rows))
                packed_result = image_portability.pack_version(context, {"image_name": image.name,
                    "new_name": snapshot_name, "mode": "CURRENT_PIXELS"})
                assert packed_result["current_pixels_verified"]
                identity, before = image.as_pointer(), metadata(image)
                image.pixels.foreach_set(initial)
                image.update()
                image.pixels.foreach_set(expected)
                image.update()
                assert image.as_pointer() == identity and metadata(image) == before
                assert digest(pixels(image)) == digest(expected), name
                image.pixels.foreach_set(initial)
                image.update()
                restored = image_portability.restore_pixels(context, {"image_name": image.name,
                    "snapshot_name": snapshot_name, "allow_shared": True})
                assert restored["complete_pixels_verified"] and restored["image_identity_preserved"]
                assert digest(pixels(image)) == digest(expected)
                # Keep a packed original for the reader; this step does not
                # establish that a loaded-only write itself persists at save.
                packed = encode(expected, "PNG8", "COLOR" if space == "sRGB" else "DATA", srgb=space == "sRGB")
                image.pack(data=packed, data_len=len(packed))
                rows.append(_row(image, expected, expected, owner, "LOADED_BYTE_ROUNDTRIP",
                    packed_sha256=hashlib.sha256(packed).hexdigest(), metadata_preserved_during_pixel_write=True,
                    typed_snapshot=snapshot_name, typed_restore_verified=True))
    # Replacing packed payload supplies an unloaded FILE ImBuf without touching
    # the missing original file. This intentionally changes packed bytes and is
    # not the existing restore_pixels contract.
    for storage in ("BYTE", "FLOAT"):
        for space in (("sRGB", "Non-Color") if storage == "BYTE" else ("Linear Rec.709", "Non-Color")):
            for alpha in ("STRAIGHT", "CHANNEL_PACKED"):
                name = "Missing-" + "-".join((storage, space, alpha))
                path = folder / (name + (".png" if storage == "BYTE" else ".exr"))
                path.write_bytes(encode(initial, "PNG8" if storage == "BYTE" else "EXR32_RAW", "DATA"))
                image = bpy.data.images.load(str(path), check_existing=False)
                image.name = name
                image.colorspace_settings.name, image.alpha_mode = space, alpha
                image.pixels.foreach_set(desired)
                image.update()
                expected = pixels(image)
                owner = protect(image)
                identity, before = image.as_pointer(), metadata(image)
                image.buffers_free()
                path.rename(path.with_suffix(path.suffix + ".unavailable"))
                assert not image.has_data and image.packed_file is None
                # No pixel/size getter between buffer release and injection:
                # those can try to open the now-missing external file.
                payload = encode(expected, "PNG8" if storage == "BYTE" else "EXR32_RAW",
                    "COLOR" if storage == "BYTE" and space == "sRGB" else "DATA", srgb=storage == "BYTE" and space == "sRGB")
                image.pack(data=payload, data_len=len(payload))
                actual = pixels(image)  # A known valid packed payload is present.
                assert image.as_pointer() == identity
                current = metadata(image)
                assert current == before, (name, before, current)
                exact = digest(actual) == digest(expected)
                rows.append(_row(image, initial, expected, owner, "UNLOADED_PACKED_PAYLOAD_REPLACEMENT",
                    exact_pixels_restored=exact, complete_metadata_preserved=current == before,
                    packed_payload_changed=True, original_path_missing=not path.exists(),
                    packed_sha256=hashlib.sha256(payload).hexdigest()))
    project = bundle / "recovery-probe.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(project), check_existing=False, relative_remap=False)
    folder.rename(bundle / "unavailable-external")
    manifest = {"project": project.name, "rows": rows, "blender_version": bpy.app.version_string,
                "release_readiness": "NOT_ASSESSED", "scope": "Native byte/unloaded buffer research; not a typed recovery or undo acceptance result."}
    (bundle / "recovery-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"phase": "writer", "blender_version": bpy.app.version_string,
            "rows": len(rows), "project_saved": True, "external_sources_unavailable": True}


def reader(bundle):
    assert bpy.app.background
    bpy.context.preferences.use_preferences_save = False
    manifest = json.loads((bundle / "recovery-manifest.json").read_text())
    assert not (bundle / "external").exists()
    bpy.ops.wm.open_mainfile(filepath=str(bundle / manifest["project"]), load_ui=False, use_scripts=False)
    grants = {permission.value: True for permission in Permission}
    permissions = PermissionManager(lambda: grants)
    context = SimpleNamespace(require=lambda *required: permissions.require(required), check_cancelled=None,
        state=SimpleNamespace(snapshot=lambda: {"paused": False, "emergency_stopped": False}))
    rows = []
    for row in manifest["rows"]:
        image = bpy.data.images[row["name"]]
        owner = row["owner"]
        assert bpy.data.images[owner["reference"]]["exact_original"] == image
        assert bpy.data.materials[owner["material"]].node_tree.nodes[owner["node"]].image == image
        assert hashlib.sha256(bytes(image.packed_file.data)).hexdigest() == row["packed_sha256"]
        actual = digest(pixels(image))
        assert metadata(image) == row["metadata"], (row["name"], row["metadata"], metadata(image))
        if row["metadata"]["source"] == "FILE":
            assert actual == row["actual_sha256"], row["name"]
        typed_verified = False
        if row.get("typed_snapshot"):
            identity = image.as_pointer()
            assert bpy.data.images[row["typed_snapshot"]][image_portability.OWNER_KEY] == image
            image.pixels.foreach_set(array("f", [.5]) * (WIDTH*HEIGHT*4))
            image.update()
            result = image_portability.restore_pixels(context, {"image_name": image.name,
                "snapshot_name": row["typed_snapshot"], "allow_shared": True})
            assert result["complete_pixels_verified"] and result["image_identity_preserved"]
            assert image.as_pointer() == identity and digest(pixels(image)) == row["desired_sha256"]
            assert metadata(image) == row["metadata"]
            assert hashlib.sha256(bytes(image.packed_file.data)).hexdigest() == row["packed_sha256"]
            assert bpy.data.materials[owner["material"]].node_tree.nodes[owner["node"]].image == image
            typed_verified = True
        rows.append({"name": image.name, "method": row["method"],
                     "writer_buffer_preserved": actual == row["actual_sha256"],
                     "exact_pixels_restored": actual == row["desired_sha256"],
                     "typed_loaded_byte_restore_verified": typed_verified,
                     "image_id_reference_preserved": True, "binding_preserved": True})
    report = {"phase": "reader", "blender_version": bpy.app.version_string,
              "rows": rows, "fresh_process_reopen": True, "external_sources_unavailable": True,
              "native_undo_verified": False, "typed_loaded_byte_tool_verified": True,
              "release_readiness": "NOT_ASSESSED"}
    (bundle / "recovery-reader.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    result = (writer if args.bridge_phase == "writer" else reader)(args.bridge_bundle.resolve(strict=True))
    result.update({"process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": os.getpid()})
    print("BLENDER_IMAGE_RECOVERY_PROBE_" + args.bridge_phase.upper() + "_OK " + json.dumps(result), flush=True)


main()
