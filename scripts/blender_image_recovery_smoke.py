"""Typed unloaded Image reconstruction with separately saved, fresh-process proof."""

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
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.tools import image_portability, image_recovery, images  # noqa: E402

WIDTH, HEIGHT = 16, 16


def context():
    grants = {permission.value: True for permission in Permission}
    manager = PermissionManager(lambda: grants)
    flags = {"paused": False, "emergency_stopped": False}
    result = SimpleNamespace(require=lambda *required: manager.require(required), check_cancelled=None,
        state=SimpleNamespace(snapshot=lambda: dict(flags)), fixture_flags=flags)
    return result, grants


def pixels(image):
    values = array("f", [0.]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return values


def digest(values):
    return hashlib.sha256(values).hexdigest()


def encode(values, format):
    return b"".join(step.data for step in pixel_codecs.encode_steps(values, WIDTH, HEIGHT, format, "DATA"))


def protect(image):
    material = bpy.data.materials.new("Protected " + image.name)
    material.use_nodes = True
    material.use_fake_user = True
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    return {"material": material.name, "node": node.name}


def restore(ctx, name, snapshot, preview):
    return image_recovery.restore_packed_snapshot(ctx, {"image_name": name, "snapshot_name": snapshot,
        "allow_shared": True, "expected_target_fingerprint": preview["expected_target_fingerprint"],
        "confirm_replace_packed_bytes": True})


def preview(ctx, name, snapshot):
    return image_recovery.recovery_preview(ctx, {"image_name": name, "snapshot_name": snapshot, "allow_shared": True})


def _one_final_provider_fault(ctx, row, operation, change):
    """Actual native data must receive no write after a provider changes state."""
    target = bpy.data.images[row["name"]]
    original_require = ctx.require
    if operation == "unloaded_pack":
        target.buffers_free()
        inspected = preview(ctx, target.name, row["snapshot"])
    else:
        if not target.has_data:
            restore(ctx, target.name, row["snapshot"], preview(ctx, target.name, row["snapshot"]))
        before_digest = digest(pixels(target))
    packed_before = hashlib.sha256(bytes(target.packed_file.data)).hexdigest()
    measured = []
    def measure(*required):
        measured.append(required)
        return original_require(*required)
    ctx.require = measure
    gate = (lambda: image_recovery._gate(ctx, target, modifying=True)) if operation == "unloaded_pack" else (lambda: image_portability._gate(ctx, target))
    gate()
    ctx.require = original_require
    armed, calls, injected = [], [], []
    output_name = "Provider Fault " + operation + " " + change
    decode, prepare, decodes = image_portability._snapshot_buffer, image_recovery._prepare, []
    def armed_decode(*args, **kwargs):
        result = decode(*args, **kwargs)
        decodes.append(True)
        if len(decodes) == 2:
            armed.append(True)
        return result
    def armed_prepare(*args, **kwargs):
        result = prepare(*args, **kwargs)
        armed.append(True)
        return result
    def provider(*required):
        result = original_require(*required)
        active = bpy.data.images.get(output_name) is not None if operation == "snapshot" else bool(armed)
        if active:
            calls.append(required)
            if len(calls) == len(measured):
                if change == "mode":
                    bpy.ops.object.mode_set(mode="EDIT")
                else:
                    ctx.fixture_flags[change] = True
                injected.append(True)
        return result
    ctx.require = provider
    if operation == "loaded_pixels":
        image_portability._snapshot_buffer = armed_decode
    elif operation == "unloaded_pack":
        image_recovery._prepare = armed_prepare
    try:
        if operation == "snapshot":
            image_portability.pack_version(ctx, {"image_name": target.name,
                "new_name": output_name, "mode": "CURRENT_PIXELS"})
        elif operation == "loaded_pixels":
            image_portability.restore_pixels(ctx, {"image_name": target.name,
                "snapshot_name": row["snapshot"], "allow_shared": True})
        else:
            restore(ctx, target.name, row["snapshot"], inspected)
    except BridgeError as error:
        assert injected
        if operation == "snapshot":
            output = bpy.data.images[output_name]
            assert output.source == "GENERATED" and output.filepath == "" and output.packed_file is None
            assert image_portability.METADATA_KEY not in output and image_portability.OWNER_KEY not in output
        else:
            assert not error.context["execution_started"]
        assert hashlib.sha256(bytes(target.packed_file.data)).hexdigest() == packed_before
        if operation == "unloaded_pack":
            assert not target.has_data
        else:
            assert digest(pixels(target)) == before_digest
    else:
        raise AssertionError("Final permission provider state change allowed a native write")
    finally:
        ctx.require = original_require
        image_portability._snapshot_buffer, image_recovery._prepare = decode, prepare
        ctx.fixture_flags.update(paused=False, emergency_stopped=False)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    return {"operation": operation, "change": change, "further_native_writes_blocked": True}


def final_provider_faults(ctx, row):
    return [_one_final_provider_fault(ctx, row, operation, change)
        for operation in ("snapshot", "loaded_pixels", "unloaded_pack")
        for change in ("paused", "emergency_stopped", "mode")]


def writer(bundle):
    bpy.context.preferences.use_preferences_save = False
    folder = bundle / "external"
    folder.mkdir()
    ctx, grants = context()
    images.get_preferences = lambda: SimpleNamespace(texture_directory=str(folder))
    initial = array("f", [.1, .2, .3, 1.]) * (WIDTH*HEIGHT)
    byte = array("f", (channel / 255 for index in range(256)
        for channel in (index, 255-index, index*37 % 256, index*73 % 256)))
    raw = array("f", [-0., -.125, 65536., -2., .1234567, 2., 4., 2., .5, .25, .75, 0., 1., 2., 3., 1.]) * 64
    cases = [(False, space, alpha) for space in ("sRGB", "Linear Rec.709", "Non-Color")
        for alpha in ("STRAIGHT", "CHANNEL_PACKED")]
    cases += [(True, "Non-Color", "STRAIGHT"), (True, "Non-Color", "CHANNEL_PACKED"),
              (True, "Linear Rec.709", "CHANNEL_PACKED")]
    rows = []
    for index, (is_float, space, alpha) in enumerate(cases):
        name, snapshot_name = "Unloaded Original " + str(index), "Retained Snapshot " + str(index)
        path = folder / (name + (".exr" if is_float else ".png"))
        path.write_bytes(encode(initial, "EXR32_RAW" if is_float else "PNG8"))
        image = bpy.data.images.load(str(path), check_existing=False)
        image.name = name
        image.colorspace_settings.name, image.alpha_mode = space, alpha
        image.pixels.foreach_set(raw if is_float else byte)
        image.update()
        desired = digest(pixels(image))
        owner = protect(image)
        # CURRENT_PIXELS requires only the loaded buffer, even after the backing
        # file has disappeared; FILE_BYTES retains its separate path contract.
        path.rename(path.with_suffix(path.suffix + ".unavailable"))
        packed = image_portability.pack_version(ctx, {"image_name": name,
            "new_name": snapshot_name, "mode": "CURRENT_PIXELS"})
        assert packed["current_pixels_verified"] and packed["source_file_at_read"] is None
        assert image_portability.OWNER_KEY in bpy.data.images[snapshot_name]
        identity = image.as_pointer()
        image.buffers_free()
        assert not image.has_data and image.packed_file is None
        grants[Permission.EDIT_MATERIALS.value] = False
        inspected = preview(ctx, name, snapshot_name)
        assert not inspected["mutation_performed"] and not image.has_data
        try:
            restore(ctx, name, snapshot_name, inspected)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED" and not image.has_data and image.packed_file is None
        else:
            raise AssertionError("Denied reconstruction unexpectedly succeeded")
        grants[Permission.EDIT_MATERIALS.value] = True
        # Preview CAS must preserve a newer metadata edit rather than overwriting.
        previous_path = image.filepath
        image.filepath = previous_path + ".manual"
        try:
            restore(ctx, name, snapshot_name, inspected)
        except BridgeError:
            assert not image.has_data and image.packed_file is None
        else:
            raise AssertionError("Stale reconstruction preview unexpectedly succeeded")
        image.filepath = previous_path
        inspected = preview(ctx, name, snapshot_name)
        result = restore(ctx, name, snapshot_name, inspected)
        assert result["image_identity_preserved"] and result["complete_pixels_verified"]
        assert result["packed_payload_replaced"] and not result["source_file_read"]
        assert image.as_pointer() == identity and digest(pixels(image)) == desired
        assert bpy.data.materials[owner["material"]].node_tree.nodes[owner["node"]].image == image
        rows.append({"name": name, "snapshot": snapshot_name, "owner": owner, "digest": desired,
            "metadata": image_portability._metadata(image), "packed_sha256": result["packed_sha256"],
            "float": is_float, "colorspace": space, "alpha_mode": alpha})
    # Revoke at an observed actual packed-byte change, rather than guessing a
    # callback count or pretending cancellation can preempt native pack().
    target = bpy.data.images[rows[0]["name"]]
    old_payload = encode(initial, "PNG8")
    target.pack(data=old_payload, data_len=len(old_payload))
    target.buffers_free()
    inspected = preview(ctx, target.name, rows[0]["snapshot"])
    original_gate = image_recovery._gate
    def late_gate(context, image=None, *, modifying=False):
        if modifying and image is target and image.packed_file is not None and bytes(image.packed_file.data) != old_payload:
            grants[Permission.EDIT_MATERIALS.value] = False
        return original_gate(context, image, modifying=modifying)
    image_recovery._gate = late_gate
    try:
        restore(ctx, target.name, rows[0]["snapshot"], inspected)
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED" and error.context["possible_mutation"]
        assert error.context["snapshot_retained"] and not error.context["rollback_verified"]
        assert hashlib.sha256(bytes(target.packed_file.data)).hexdigest() == rows[0]["packed_sha256"]
        assert not target.has_data
    else:
        raise AssertionError("Post-native permission revocation was not reported")
    finally:
        image_recovery._gate = original_gate
        grants[Permission.EDIT_MATERIALS.value] = True
    restore(ctx, target.name, rows[0]["snapshot"], preview(ctx, target.name, rows[0]["snapshot"]))
    # If a consumer acquires a newly allocated snapshot from a permission
    # callback, no subsequent metadata/payload/ID-property writes are permitted.
    acquired = []
    acquired_name = "Acquired Snapshot"
    def acquire_new_output():
        output = bpy.data.images.get(acquired_name)
        if output is not None and not acquired:
            material = bpy.data.materials.new("Acquiring Material")
            material.use_nodes = True
            node = material.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = output
            acquired.append((material, node, output.source, output.filepath))
    ctx.check_cancelled = acquire_new_output
    try:
        image_portability.pack_version(ctx, {"image_name": target.name, "new_name": acquired_name, "mode": "CURRENT_PIXELS"})
    except BridgeError as error:
        output = bpy.data.images[acquired_name]
        assert error.context["possible_mutation"] and not error.context["rollback_verified"]
        assert acquired[0][1].image == output
        assert (output.source, output.filepath) == acquired[0][2:] and output.packed_file is None
        assert image_portability.METADATA_KEY not in output and image_portability.OWNER_KEY not in output
        assert not output.use_fake_user
    else:
        raise AssertionError("Acquired snapshot publication was not stopped")
    finally:
        ctx.check_cancelled = None
    provider_faults = final_provider_faults(ctx, rows[0])
    project = bundle / "recovered.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(project), check_existing=False, relative_remap=False)
    folder.rename(bundle / "unavailable-external")
    (bundle / "recovery-manifest.json").write_text(json.dumps({"project": project.name, "rows": rows}, indent=2)+"\n")
    return {"phase": "writer", "blender_version": bpy.app.version_string, "cases": len(rows),
        "permission_denial_verified": True, "stale_preview_preserves_manual_metadata": True,
        "late_native_revocation_retains_changed_payload": True,
        "acquired_new_snapshot_stops_all_further_writes": True,
        "final_grant_provider_faults": provider_faults,
        "external_sources_unavailable": True, "project_saved": True}


def reader(bundle):
    bpy.context.preferences.use_preferences_save = False
    manifest = json.loads((bundle / "recovery-manifest.json").read_text())
    bpy.ops.wm.open_mainfile(filepath=str(bundle / manifest["project"]), load_ui=False, use_scripts=False)
    ctx, _ = context()
    rows = []
    for row in manifest["rows"]:
        image = bpy.data.images[row["name"]]
        snapshot = bpy.data.images[row["snapshot"]]
        assert snapshot[image_portability.OWNER_KEY] == image
        assert not image.has_data
        identity = image.as_pointer()
        inspected = preview(ctx, image.name, snapshot.name)
        assert inspected["previous_packed_sha256"] == row["packed_sha256"] and not image.has_data
        result = restore(ctx, image.name, snapshot.name, inspected)
        assert result["complete_pixels_verified"] and image.as_pointer() == identity
        assert digest(pixels(image)) == row["digest"]
        assert image.colorspace_settings.name == row["colorspace"] and image.alpha_mode == row["alpha_mode"]
        assert bool(image.is_float) == row["float"]
        owner = row["owner"]
        assert bpy.data.materials[owner["material"]].node_tree.nodes[owner["node"]].image == image
        rows.append({"name": image.name, "complete_pixels_verified": True,
            "identity_and_binding_preserved": True, "packed_payload_verified": True})
    result = {"phase": "reader", "blender_version": bpy.app.version_string,
        "cases": rows, "fresh_process_reopen": True, "external_sources_unavailable": True,
        "typed_tools_verified": True, "native_undo_verified": False, "release_readiness": "NOT_ASSESSED"}
    (bundle / "recovery-reader.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    result = (writer if args.bridge_phase == "writer" else reader)(args.bridge_bundle.resolve(strict=True))
    result.update(process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid())
    print("BLENDER_IMAGE_RECOVERY_"+args.bridge_phase.upper()+"_OK "+json.dumps(result), flush=True)


main()
