"""Isolated native packing observations; no product packing/undo acceptance claim.

The managed runner launches a writer and a fresh reader with separate profiles.
Only the owned bundle crosses that process boundary. Native setup/readback Python
here is fixture code, never an agent escape hatch around structured permissions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from array import array
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
from blender_codex_bridge import pixel_codecs  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.tools import image_portability, images  # noqa: E402

WIDTH, HEIGHT = 4, 3


def tool_context(folder):
    grants = {permission.value: True for permission in Permission}
    manager = PermissionManager(lambda: grants)
    context = SimpleNamespace(require=lambda *required: manager.require(required), check_cancelled=None,
                              state=SimpleNamespace(snapshot=lambda: {"paused": False, "emergency_stopped": False}))
    images.get_preferences = lambda: SimpleNamespace(texture_directory=str(folder))
    return context, grants


def digest(values):
    return hashlib.sha256(values).hexdigest()


def pixels(image):
    values = array("f", [0.]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return values


def encode(values, format, role):
    return b"".join(step.data for step in pixel_codecs.encode_steps(values, WIDTH, HEIGHT, format, role))


def protect(image, index):
    material = bpy.data.materials.new("Probe Material " + image.name)
    material.use_nodes = True
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.name, node.image = "Protected Texture", image
    mesh = bpy.data.meshes.new("Probe Mesh " + image.name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Probe Object " + image.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location.x = index * 2
    return {"object": obj.name, "material": material.name, "node": node.name}


def make_file(path, values, format, role):
    data = encode(values, format, role)
    with path.open("xb") as stream:
        stream.write(data)
    image = bpy.data.images.load(str(path), check_existing=False)
    layout = pixel_codecs.interpretation(format, role)
    image.colorspace_settings.name = layout["colorspace"]
    image.alpha_mode = layout["reopen_alpha_mode"]
    assert len(image.pixels) == WIDTH * HEIGHT * 4
    return image, data


def record(image, name, before, edited, payload, ownership, seconds):
    packed = bytes(image.packed_file.data)
    return {"name": name, "source": image.source, "colorspace": image.colorspace_settings.name,
            "alpha_mode": image.alpha_mode, "size": list(image.size), "channels": image.channels,
            "source_pixels_sha256": digest(before), "edited_pixels_sha256": digest(edited),
            "writer_pixels_sha256_after_pack": digest(pixels(image)),
            "packed_bytes_sha256": hashlib.sha256(packed).hexdigest(), "packed_bytes": len(packed),
            "supplied_bytes_sha256": hashlib.sha256(payload).hexdigest() if payload is not None else None,
            "native_pack_seconds": seconds, "ownership": ownership}


def writer(bundle):
    assert bpy.app.background, "Run through the isolated background runner"
    bpy.context.preferences.use_preferences_save = False
    folder = bundle / "external-textures"
    folder.mkdir()
    rows = []
    base = array("f", [.25, .5, .75, .25, .125, .25, .5, 0., .75, .5, .25, 1., .5, .25, .125, .5]) * 3
    for format in ("PNG8", "PNG16", "EXR32", "EXR32_RAW"):
        for role in ("COLOR", "DATA"):
            for method in ("CLEAN_NATIVE", "DIRTY_NATIVE", "FILE_BYTES", "CURRENT_PIXELS"):
                name = "-".join((format, role, method))
                extension = ".png" if format.startswith("PNG") else ".exr"
                image, original_bytes = make_file(folder / (name + extension), base, format, role)
                image.name = name
                before = pixels(image)
                edited = array("f", before)
                if method != "CLEAN_NATIVE":
                    # Unequal, nontrivial edits distinguish edited buffers from
                    # source bytes. Preserve the existing role/alpha contract.
                    edited[0:4] = array("f", [.625, .375, .875, .5])
                    image.pixels.foreach_set(edited)
                    image.update()
                    # A byte ImBuf quantizes RNA writes. The packing question
                    # concerns its actual complete edited buffer, not a falsely
                    # assumed float buffer or unrepresentable requested value.
                    observed = pixels(image)
                    error = max(abs(a - b) for a, b in zip(observed, edited, strict=True))
                    assert error <= (1 / 255 + 1e-7 if not image.is_float else 0.)
                    edited = observed
                payload = None
                if method == "FILE_BYTES":
                    payload = original_bytes
                elif method == "CURRENT_PIXELS":
                    # This is an explicitly raw snapshot with recorded original
                    # interpretation, never an implicit in-place file reload.
                    payload = encode(edited, "EXR32_RAW", "DATA")
                    image.filepath = "//embedded/" + name + ".exr"
                    image.colorspace_settings.name = "Non-Color"
                    image.alpha_mode = "CHANNEL_PACKED"
                ownership = protect(image, len(rows))
                started = time.perf_counter()
                if payload is None:
                    image.pack()
                else:
                    image.pack(data=payload, data_len=len(payload))
                elapsed = time.perf_counter() - started
                assert image.packed_file is not None
                if method in {"FILE_BYTES", "CURRENT_PIXELS"}:
                    assert bytes(image.packed_file.data) == payload
                row = record(image, name, before, edited, payload, ownership, elapsed)
                row.update({"method": method, "format": format, "role": role})
                if method == "CLEAN_NATIVE":
                    # A plain native clean FILE pack must retain original bytes.
                    assert row["packed_bytes_sha256"] == hashlib.sha256(original_bytes).hexdigest()
                rows.append(row)
    # Generated float native packing is observed independently; native PNG
    # encoding must not be mistaken for exact signed/HDR float recovery.
    raw = array("f", [-0., -.125, 65536., -2., .1234567, 2., 4., 2., .5, .25, .75, 0., 1., 2., 3., 1.]) * 3
    for method in ("GENERATED_NATIVE", "GENERATED_CURRENT_PIXELS", "ALREADY_PACKED"):
        image = bpy.data.images.new(method, WIDTH, HEIGHT, alpha=True, float_buffer=True)
        image.colorspace_settings.name, image.alpha_mode = "Non-Color", "CHANNEL_PACKED"
        image.pixels.foreach_set(raw)
        image.update()
        before = pixels(image)
        payload = encode(raw, "EXR32_RAW", "DATA") if method != "GENERATED_NATIVE" else None
        ownership = protect(image, len(rows))
        started = time.perf_counter()
        if payload is None:
            image.pack()
        else:
            # Explicit source assignment is part of this isolated probe: it is
            # not assumed equivalent to preserving a generated image identity.
            image.source = "FILE"
            image.filepath = "//embedded/" + method + ".exr"
            image.pack(data=payload, data_len=len(payload))
            if method == "ALREADY_PACKED":
                image.pack(data=payload, data_len=len(payload))
        elapsed = time.perf_counter() - started
        row = record(image, method, before, raw, payload, ownership, elapsed)
        row.update({"method": method, "format": "EXR32_RAW", "role": "DATA"})
        rows.append(row)
    # A packed FILE target is loaded again from its ORIGINAL bytes in the fresh
    # process, while the separately packed raw snapshot retains edited pixels.
    # A native ID-property reference must still resolve the same target ID after
    # save/reopen; names or stale process pointers are insufficient identity.
    target, target_bytes = make_file(folder / "durable-target.exr", base, "EXR32_RAW", "DATA")
    target.name = "Durable Target"
    source_before = pixels(target)
    target.pixels.foreach_set(raw)
    target.update()
    target.pack(data=target_bytes, data_len=len(target_bytes))
    owner = protect(target, len(rows))
    row = record(target, target.name, source_before, raw, target_bytes, owner, 0.)
    row.update({"method": "FILE_BYTES", "format": "EXR32_RAW", "role": "DATA"})
    rows.append(row)
    snapshot = bpy.data.images.new("Durable Snapshot", WIDTH, HEIGHT, alpha=True, float_buffer=True)
    snapshot.source = "FILE"
    snapshot.filepath = "//embedded/durable-snapshot.exr"
    snapshot.colorspace_settings.name, snapshot.alpha_mode = "Non-Color", "CHANNEL_PACKED"
    snapshot_bytes = encode(raw, "EXR32_RAW", "DATA")
    snapshot.pack(data=snapshot_bytes, data_len=len(snapshot_bytes))
    snapshot["bridge_original_image"] = target
    snapshot["bridge_original_pixels_sha256"] = digest(raw)
    owner = protect(snapshot, len(rows))
    row = record(snapshot, snapshot.name, raw, raw, snapshot_bytes, owner, 0.)
    row.update({"method": "CURRENT_PIXELS", "format": "EXR32_RAW", "role": "DATA"})
    rows.append(row)
    # Exercise the actual typed handlers, not only native calls. Every source
    # has measured pixels and a real protected consumer before publication.
    context, grants = tool_context(folder)
    api_source, _ = make_file(folder / "api-input.exr", base, "EXR32_RAW", "DATA")
    api_source.name = "API Input"
    protect(api_source, len(rows))
    packed = image_portability.pack_version(context, {"image_name": "API Input", "new_name": "API Target", "mode": "FILE_BYTES"})
    assert not packed["current_pixels_verified"] and not packed["project_saved"]
    api_target = bpy.data.images["API Target"]
    protect(api_target, len(rows) + 1)
    api_target.pixels.foreach_set(raw)
    api_target.update()
    current = image_portability.pack_version(context, {"image_name": "API Target", "new_name": "API Snapshot", "mode": "CURRENT_PIXELS"})
    assert current["current_pixels_verified"] and current["original_pixels_unchanged"]
    assert digest(pixels(api_target)) == digest(raw)
    # Permission denial happens before allocation and cannot silently pack or save.
    grants[Permission.EDIT_MATERIALS.value] = False
    try:
        image_portability.pack_version(context, {"image_name": "API Target", "new_name": "Denied Snapshot", "mode": "CURRENT_PIXELS"})
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED" and bpy.data.images.get("Denied Snapshot") is None
    else:
        raise AssertionError("Denied packing unexpectedly succeeded")
    grants[Permission.EDIT_MATERIALS.value] = True
    grants[Permission.DELETE_OBJECTS.value] = False
    def fail_after_allocation():
        if bpy.data.images.get("Retained Snapshot") is not None:
            raise BridgeError("AGENT_PAUSED", "Injected post-allocation cancellation")
    context.check_cancelled = fail_after_allocation
    try:
        image_portability.pack_version(context, {"image_name": "API Target", "new_name": "Retained Snapshot", "mode": "CURRENT_PIXELS"})
    except BridgeError as error:
        assert error.context["possible_mutation"] and error.context["cleanup_permission_denied"]
        assert error.context["retained_image_name"] == "Retained Snapshot"
        assert bpy.data.images.get("Retained Snapshot") is not None
        assert digest(pixels(api_target)) == digest(raw)
    else:
        raise AssertionError("Injected post-allocation failure unexpectedly succeeded")
    context.check_cancelled = None
    grants[Permission.DELETE_OBJECTS.value] = True
    project = bundle / "packed-probe.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(project), check_existing=False)
    assert project.is_file()
    # The fresh reader cannot use the input paths, even accidentally. Preserve
    # owned bytes for audit without deleting unrelated or published outputs.
    folder.rename(bundle / "unavailable-external-textures")
    manifest = {"schema_version": 1, "writer_blender": bpy.app.version_string,
                "project": project.name, "images": rows, "external_sources_unavailable": True,
                "scope": "Native packing/raw snapshot probe; no structured tool, native undo, Windows or release acceptance"}
    (bundle / "packing-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"blender_version": bpy.app.version_string, "phase": "writer", "images": len(rows),
            "project_saved": True, "external_sources_unavailable": True, "native_undo_verified": False}


def reader(bundle):
    assert bpy.app.background, "Run through the isolated background runner"
    bpy.context.preferences.use_preferences_save = False
    manifest = json.loads((bundle / "packing-manifest.json").read_text(encoding="utf-8"))
    assert not (bundle / "external-textures").exists()
    bpy.ops.wm.open_mainfile(filepath=str(bundle / manifest["project"]), load_ui=False, use_scripts=False)
    rows = []
    for original in manifest["images"]:
        image = bpy.data.images[original["name"]]
        assert image.packed_file is not None
        assert hashlib.sha256(bytes(image.packed_file.data)).hexdigest() == original["packed_bytes_sha256"]
        assert image.colorspace_settings.name == original["colorspace"] and image.alpha_mode == original["alpha_mode"]
        owner = original["ownership"]
        obj, material = bpy.data.objects[owner["object"]], bpy.data.materials[owner["material"]]
        assert obj.data.materials[0] == material and material.node_tree.nodes[owner["node"]].image == image
        actual = pixels(image)
        assert tuple(image.size) == (WIDTH, HEIGHT) and image.channels == 4
        actual_digest = digest(actual)
        if original["method"] in {"CURRENT_PIXELS", "GENERATED_CURRENT_PIXELS", "ALREADY_PACKED"}:
            assert actual_digest == original["edited_pixels_sha256"], (original["name"], list(actual[:8]))
        elif original["method"] in {"FILE_BYTES", "CLEAN_NATIVE"}:
            assert actual_digest == original["source_pixels_sha256"], original["name"]
        rows.append({"name": image.name, "method": original["method"], "format": original["format"],
                     "role": original["role"], "reader_pixels_sha256": actual_digest,
                     "source_pixels_preserved": actual_digest == original["source_pixels_sha256"],
                     "edited_pixels_preserved": actual_digest == original["edited_pixels_sha256"],
                     "packed_bytes_preserved": True, "protected_binding_preserved": True})
    target, snapshot = bpy.data.images["Durable Target"], bpy.data.images["Durable Snapshot"]
    assert snapshot["bridge_original_image"] == target
    identity = target.as_pointer()
    target_before = (target.name, target.source, target.filepath, target.colorspace_settings.name,
                     target.alpha_mode, target.is_float, bytes(target.packed_file.data), target.users)
    assert digest(pixels(target)) != snapshot["bridge_original_pixels_sha256"]
    target.pixels.foreach_set(pixels(snapshot))
    target.update()
    assert digest(pixels(target)) == snapshot["bridge_original_pixels_sha256"]
    assert target.as_pointer() == identity
    assert target_before == (target.name, target.source, target.filepath, target.colorspace_settings.name,
                             target.alpha_mode, target.is_float, bytes(target.packed_file.data), target.users)
    for row in manifest["images"]:
        owner = row["ownership"]
        assert bpy.data.materials[owner["material"]].node_tree.nodes[owner["node"]].image == bpy.data.images[row["name"]]
    context, grants = tool_context(bundle / "external-textures")
    api_target = bpy.data.images["API Target"]
    original_identity = api_target.as_pointer()
    old = pixels(api_target)  # Explicit fixture read from known packed bytes, no external fallback.
    snapshot = bpy.data.images["API Snapshot"]
    assert snapshot[image_portability.OWNER_KEY] == api_target
    saved_digest = json.loads(snapshot[image_portability.METADATA_KEY])["pixels_sha256_float32_le"]
    assert digest(old) != saved_digest
    grants[Permission.EDIT_MATERIALS.value] = False
    try:
        image_portability.restore_pixels(context, {"image_name": "API Target", "snapshot_name": "API Snapshot"})
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED" and digest(pixels(api_target)) == digest(old)
    else:
        raise AssertionError("Denied restoration unexpectedly succeeded")
    grants[Permission.EDIT_MATERIALS.value] = True
    def stop_after_write():
        if api_target.is_dirty:
            raise BridgeError("AGENT_PAUSED", "Injected late cancellation after native write")
    context.check_cancelled = stop_after_write
    try:
        image_portability.restore_pixels(context, {"image_name": "API Target", "snapshot_name": "API Snapshot"})
    except BridgeError as error:
        assert error.context["execution_started"] and error.context["possible_mutation"]
        assert error.context["snapshot_retained"] and not error.context["rollback_verified"]
        assert digest(pixels(api_target)) == saved_digest
    else:
        raise AssertionError("Injected post-write cancellation unexpectedly succeeded")
    context.check_cancelled = None
    restored = image_portability.restore_pixels(context, {"image_name": "API Target", "snapshot_name": "API Snapshot"})
    assert restored["complete_pixels_verified"] and restored["image_identity_preserved"]
    assert digest(pixels(api_target)) == saved_digest and api_target.as_pointer() == original_identity
    assert bpy.data.materials["Probe Material API Target"].node_tree.nodes["Protected Texture"].image == api_target
    report = {"blender_version": bpy.app.version_string, "phase": "reader", "images": rows,
              "external_sources_unavailable": True, "fresh_process_reader": True,
              "native_undo_verified": False, "structured_tool_verified": True,
              "durable_original_id_reference_verified": True,
              "loaded_float_target_pixels_restored_with_identity_and_consumers": True,
              "cleanup_denial_retains_allocated_version": True,
              "late_cancel_reports_possible_mutation_and_retains_snapshot": True,
              "release_readiness": "NOT_ASSESSED"}
    (bundle / "packing-reader.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bundle = args.bridge_bundle.resolve(strict=True)
    assert bundle.is_dir()
    result = writer(bundle) if args.bridge_phase == "writer" else reader(bundle)
    result.update({"process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": os.getpid()})
    print("BLENDER_IMAGE_PORTABILITY_PROBE_" + args.bridge_phase.upper() + "_OK " + json.dumps(result), flush=True)


main()
