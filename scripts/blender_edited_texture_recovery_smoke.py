"""Save a retained edited-pixel helper, then restore the original ID after restart."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.blender_current_pixels_paired_recovery_smoke import (  # noqa: E402
    MIN_DISK,
    MIN_MEMORY,
    OLD_RGBA,
    PROFILES,
    edited_oracle,
    edited_values,
    raw_digest,
)
from scripts.blender_persistent_save_smoke import ADDON, Scenario  # noqa: E402

CASES = {"edited_texture_recovery": "SMALL2X2", "edited_texture_recovery_large": "LARGE4K"}
ORIGINAL = "Owned edited FILE original"
SNAPSHOT = "Owned edited-pixel recovery helper"
PROTECTED = "Owned unrelated FILE image"
BINDINGS = ("Edited surface", "Second edited surface", "Protected surface")
PROTECTED_DIMENSIONS = (2, 2)
MAX_FIXTURE_FILE_BYTES = 1024**3
PROTECTED_CHANNELS = (.5, .75, .875, 1.)


def pixels(image, dimensions):
    assert image.has_data and image.is_float and tuple(image.size) == dimensions and image.channels == 4
    values = array("f", [0.]) * (dimensions[0] * dimensions[1] * 4)
    assert len(image.pixels) == len(values)
    image.pixels.foreach_get(values)
    return values


def packed_hash(image):
    assert image.packed_file is not None
    return hashlib.sha256(bytes(image.packed_file.data)).hexdigest()


def roles(image):
    return image.source, image.colorspace_settings.name, image.alpha_mode


def make_file(bpy, name, folder, channels, dimensions):
    from blender_codex_bridge import pixel_codecs

    expected = array("f", channels) * (dimensions[0] * dimensions[1])
    payload = b"".join(step.data for step in pixel_codecs.encode_steps(
        expected, *dimensions, "EXR32_RAW", "DATA",
    ))
    assert 0 < len(payload) <= MAX_FIXTURE_FILE_BYTES
    path = folder / (name + ".exr")
    with path.open("xb") as stream:
        stream.write(payload)
    image = bpy.data.images.load(str(path), check_existing=False)
    image.name = name
    image.colorspace_settings.name, image.alpha_mode = "Non-Color", "CHANNEL_PACKED"
    image.pack(data=payload, data_len=len(payload))
    assert tuple(image.size) == dimensions  # Native buffer allocation at the owned input boundary.
    assert raw_digest(pixels(image, dimensions)) == raw_digest(expected)
    assert packed_hash(image) == file_proof(path)["sha256"]
    return image


def file_proof(path):
    size = path.stat().st_size
    assert 0 < size <= MAX_FIXTURE_FILE_BYTES
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = size
        while remaining:
            block = stream.read(min(remaining, 1024**2))
            assert block, "Owned fixture file was truncated"
            digest.update(block)
            remaining -= len(block)
        assert not stream.read(1), "Owned fixture file grew"
    return {"bytes": size, "sha256": digest.hexdigest()}


def make_surface(bpy, name, image, offset):
    material = bpy.data.materials.new(name + " Material")
    material.use_nodes = True
    tree = material.node_tree
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.name = "Fixture Texture"
    texture.image = image
    tree.links.new(texture.outputs["Color"], tree.nodes["Principled BSDF"].inputs["Base Color"])
    mesh = bpy.data.meshes.new(name + " Mesh")
    mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location.x = offset


def bindings(bpy, original, protected):
    observed = {}
    for offset, (name, target) in enumerate(zip(BINDINGS, (original, original, protected), strict=True)):
        obj = bpy.context.scene.objects[name]
        assert tuple(obj.location) == (float(offset * 2), 0., 0.)
        assert [tuple(vertex.co) for vertex in obj.data.vertices] == [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
        assert [tuple(face.vertices) for face in obj.data.polygons] == [(0, 1, 2)]
        assert len(obj.data.materials) == 1
        material = obj.data.materials[0]
        assert material.name == name + " Material"
        tree = material.node_tree
        texture = tree.nodes["Fixture Texture"]
        assert texture.image == target
        target_input = tree.nodes["Principled BSDF"].inputs["Base Color"]
        assert len(target_input.links) == 1
        link = target_input.links[0]
        assert link.from_node == texture and link.from_socket.name == "Color"
        observed[name] = [obj.as_pointer(), obj.data.as_pointer(), material.as_pointer(), texture.as_pointer()]
    return observed


def run_image_job(client_factory, port, method, params, preview_params, limit, outcome):
    """Keep the job owner connected through completion. This thread uses only socket data."""
    client = None
    try:
        client = client_factory(port)
        preview = None
        if preview_params is not None:
            preview = client.call("image.recovery_job_preview", **preview_params)
            assert preview["mutation_performed"] is False and preview["snapshot_pixels_verified"] is False
            assert preview["source_file_read"] is False and preview["file_written"] is False
            params = {**params, **preview_params,
                      "expected_target_fingerprint": preview["expected_target_fingerprint"],
                      "confirm_replace_packed_bytes": preview["requires_confirm_replace_packed_bytes"]}
        started = time.monotonic()
        accepted = client.call(method, **params, time_limit_seconds=limit)
        assert accepted["accepted"] is True and accepted["job_completed"] is False, accepted
        assert accepted["undo_boundary_created"] is False, accepted
        revision = 0
        phases = set()
        while time.monotonic() - started < limit + 10.:
            result = client.call("jobs.inspect", job_id=accepted["job_id"])
            assert result["revision"] >= revision, result
            revision = result["revision"]
            phases.add(result["progress"]["phase"])
            if result["terminal"]:
                assert result["state"] == "SUCCEEDED", result
                assert result["execution_started"] and result["undo_boundary_finalized"], result
                assert not result["external_effects"] and not result["evidence_observation_unknown"], result
                assert result["recovery_evidence"]["complete_pixels_verified"] is True, result
                outcome.update(result=result["result"], preview=preview, job_evidence={
                    "job_id": accepted["job_id"], "revision": revision, "observed_phases": sorted(phases),
                    "terminal": result["state"], "elapsed_seconds": round(time.monotonic() - started, 3),
                    "native_undo_finalized": result["undo_boundary_finalized"],
                })
                return
            time.sleep(.025)
        raise AssertionError("Image job did not reach a terminal state")
    except Exception as error:
        outcome["error"] = error
    finally:
        if client is not None:
            client.close()


class EditedTextureScenario(Scenario):
    def image_job(self, method, params, preview_params=None):
        outcome = {}
        worker = threading.Thread(
            target=run_image_job,
            args=(self.client_factory, self.port, method, params, preview_params, self.job_limit, outcome),
            daemon=True,
        )
        worker.start()
        while worker.is_alive():
            yield
        if "error" in outcome:
            raise outcome["error"]
        if preview_params is not None:
            self.evidence["methods"].append({"method": "image.recovery_job_preview", "ok": True})
        self.evidence["methods"].extend(({"method": method, "ok": True}, {"method": "jobs.inspect", "ok": True}))
        return outcome["result"], outcome["preview"], outcome["job_evidence"]

    def check_capacity(self):
        if self.dimensions == PROTECTED_DIMENSIONS:
            return
        from scripts.blender_large_paint_smoke import check_memory_headroom

        available = check_memory_headroom()
        free = shutil.disk_usage(self.bundle).free
        assert available is not None and available >= MIN_MEMORY, "4K needs measured 8 GiB memory headroom"
        assert free >= MIN_DISK, "4K needs measured 2 GiB bundle filesystem headroom"
        self.evidence["initial_resources"] = {"available_memory_bytes": available, "bundle_disk_free_bytes": free,
                                               "required_memory_bytes": MIN_MEMORY, "required_disk_bytes": MIN_DISK}

    def capture_peak_memory(self):
        if self.dimensions != PROTECTED_DIMENSIONS:
            from scripts.blender_large_paint_smoke import process_memory

            self.evidence["process_memory_at_completion"] = process_memory()

    def save_owned_project(self):
        result = yield from self.call("project.save", {"filepath": str(self.first), "overwrite": False})
        assert result["saved"] is True and result["project_saved"] is True, result
        assert Path(result["filepath"]) == Path(self.bpy.data.filepath) == self.first, result
        proof = file_proof(self.first)
        receipt = result["recovery_checkpoint"]
        assert receipt["state"] == "available", receipt
        assert Path(receipt["filepath"]) == self.first and receipt["verification"] == "saved_bytes", receipt
        assert receipt["file_sha256"] == proof["sha256"] and result["file_bytes"] == receipt["file_bytes"] == proof["bytes"], receipt
        return proof

    def check_missing_source(self, image):
        bpy = self.bpy
        # An expected EXR at the new owned location must not be available at the original stored path.
        original = self.approved / "temporary texture sources" / (ORIGINAL + ".exr")
        detached = self.bundle / "detached owned texture sources" / original.name
        assert Path(bpy.path.abspath(image.filepath)) == original and not original.exists()
        assert detached.is_file()
        return detached

    def writer(self):
        bpy, prefs = self.bpy, self.prefs
        self.stage = "preflight and individually authorize owned project and texture roots"
        self.check_capacity()
        self.approved.mkdir()
        source_folder = self.approved / "temporary texture sources"
        source_folder.mkdir()
        prefs.project_directory = str(self.approved)
        prefs.texture_directory = str(self.approved)
        prefs.allow_save_project = True
        prefs.allow_external_files = True
        prefs.allow_edit_scene = True
        prefs.allow_edit_materials = True
        assert prefs.allow_inspect_scene and not prefs.all_dangerous_permissions
        assert not prefs.allow_unrestricted_project_texture_paths
        bpy.context.preferences.filepaths.save_version = 0
        yield from self.call("toolsets.enable", {"name": "materials"})

        self.stage = "edit original Float32 FILE pixels separated from its saved previous payload"
        original = make_file(bpy, ORIGINAL, source_folder, OLD_RGBA, self.dimensions)
        protected = make_file(bpy, PROTECTED, source_folder, PROTECTED_CHANNELS, PROTECTED_DIMENSIONS)
        for offset, (name, image) in enumerate(zip(BINDINGS, (original, original, protected), strict=True)):
            make_surface(bpy, name, image, offset * 2)
        old_packed, protected_packed = packed_hash(original), packed_hash(protected)
        original.pixels.foreach_set(edited_values(*self.dimensions))
        original.update()
        expected = edited_oracle(*self.dimensions)
        assert original.is_dirty and raw_digest(pixels(original, self.dimensions)) == expected
        assert packed_hash(original) == old_packed
        source_folder.rename(self.bundle / "detached owned texture sources")
        assert file_proof(self.check_missing_source(original))["sha256"] == old_packed
        original_pointer = original.as_pointer()
        before = bindings(bpy, original, protected)

        self.stage = "queue a native owner-bound packed current-pixel helper and verify every channel"
        result, _, job = yield from self.image_job("image.snapshot_job_start", {
            "image_name": ORIGINAL, "new_name": SNAPSHOT,
        })
        assert result["created"] and result["current_pixels_verified"] and result["original_pixels_unchanged"], result
        assert not result["project_saved"] and not result["external_file_written"], result
        assert result["pixels_sha256_float32_le"] == expected, result
        from blender_codex_bridge.tools import image_portability as storage

        helper = bpy.data.images[SNAPSHOT]
        assert helper[storage.OWNER_KEY] == original and helper.use_fake_user
        helper_hash = packed_hash(helper)
        assert helper_hash == result["packed_sha256"] and helper_hash != old_packed
        assert raw_digest(pixels(helper, self.dimensions)) == expected
        assert original.as_pointer() == original_pointer and raw_digest(pixels(original, self.dimensions)) == expected
        assert packed_hash(original) == old_packed and bindings(bpy, original, protected) == before

        self.stage = "ordinary queued Save to approved project path with a persistent individual grant"
        proof = yield from self.save_owned_project()
        checkpoint = yield from self.checkpoint(self.first, proof)
        assert file_proof(self.check_missing_source(original))["sha256"] == old_packed
        assert protected_packed == packed_hash(protected)
        self.capture_peak_memory()
        self.evidence.update(checkpoint_id=checkpoint, checkpoint_file=proof, snapshot=job,
                             project_filepath=str(self.first), original_packed_sha256=old_packed,
                             protected_packed_sha256=protected_packed, snapshot_packed_sha256=helper_hash,
                             current_raw_sha256=expected, dimensions=self.dimensions,
                             original_and_snapshot_distinct=True, source_path_unavailable=True)

    def reader(self):
        bpy, prefs = self.bpy, self.prefs
        self.stage = "preflight and discover persisted permissions from a fresh factory process"
        self.check_capacity()
        with (self.bundle / "writer.json").open("rb") as stream:
            writer = json.loads(stream.read(64 * 1024))
        assert writer["process_instance"] != self.token and writer["process_id"] != os.getpid()
        assert not bpy.data.filepath and bpy.data.images.get(ORIGINAL) is None
        assert not prefs.all_dangerous_permissions and not prefs.allow_unrestricted_project_texture_paths
        assert prefs.allow_save_project and prefs.allow_external_files and prefs.allow_edit_scene and prefs.allow_edit_materials
        assert Path(prefs.project_directory) == Path(prefs.texture_directory) == self.approved
        proof = file_proof(self.first)
        checkpoint = yield from self.checkpoint(self.first, proof)
        assert checkpoint == writer["checkpoint_id"] and proof == writer["checkpoint_file"]

        self.stage = "explicit queued checkpoint reopen and prepare linked original recovery"
        opened = yield from self.call("project.checkpoint_reopen", {"checkpoint_id": checkpoint, "confirm_reopen": True})
        assert opened["reopened"] is True and opened["auto_replayed"] is False, opened
        assert Path(opened["filepath"]) == Path(bpy.data.filepath) == self.first
        assert bpy.app.timers.is_registered(self.runtime.executor._timer_callback)
        yield from self.call("toolsets.enable", {"name": "materials"})
        from blender_codex_bridge.tools import image_portability as storage

        original, helper, protected = (bpy.data.images[name] for name in (ORIGINAL, SNAPSHOT, PROTECTED))
        assert helper[storage.OWNER_KEY] == original and helper.use_fake_user
        original_id, helper_id, protected_id = (image.as_pointer() for image in (original, helper, protected))
        assert roles(original) == roles(helper) == roles(protected) == ("FILE", "Non-Color", "CHANNEL_PACKED")
        original_loaded = bool(original.has_data)
        original_before_digest = raw_digest(pixels(original, self.dimensions)) if original_loaded else None
        assert packed_hash(original) == writer["original_packed_sha256"]
        helper_hash = packed_hash(helper)
        assert helper_hash == writer["snapshot_packed_sha256"]
        expected = edited_oracle(*self.dimensions)
        assert writer["dimensions"] == list(self.dimensions) and expected == writer["current_raw_sha256"]
        if original_loaded:
            previous = array("f", OLD_RGBA) * (self.dimensions[0] * self.dimensions[1])
            assert original_before_digest == raw_digest(previous) and original_before_digest != expected
            del previous
        assert file_proof(self.check_missing_source(original))["sha256"] == writer["original_packed_sha256"]
        before = bindings(bpy, original, protected)
        protected_hash = writer["protected_packed_sha256"]
        assert packed_hash(protected) == protected_hash
        protected_loaded = bool(protected.has_data)
        if protected_loaded:
            assert raw_digest(pixels(protected, PROTECTED_DIMENSIONS)) == raw_digest(array("f", PROTECTED_CHANNELS) * 4)

        self.stage = "preview and explicitly restore complete current channels to the same original image"
        result, preview, job = yield from self.image_job("image.restore_snapshot_job_start", {}, {
            "image_name": ORIGINAL, "snapshot_name": SNAPSHOT, "allow_shared": True,
        })
        assert preview["previous_packed_sha256"] == writer["original_packed_sha256"] and preview["snapshot_packed_sha256"] == helper_hash
        assert preview["requires_confirm_replace_packed_bytes"] is (not original_loaded), preview
        assert preview["mode"] == result["mode"] == ("LOADED_BUFFER" if original_loaded else "PACKED_RECONSTRUCTION")
        assert result["restored"] and result["complete_pixels_verified"] and result["image_identity_preserved"], result
        assert result["pixels_sha256_float32_le"] == expected and result["snapshot_retained"], result
        assert not result["project_saved"] and not result["file_written"] and not result["source_file_read"], result

        self.stage = "check exact pixels, roles, shared bindings, protected consumer and unchanged checkpoint bytes"
        assert (bpy.data.images[ORIGINAL].as_pointer(), bpy.data.images[SNAPSHOT].as_pointer(),
                bpy.data.images[PROTECTED].as_pointer()) == (original_id, helper_id, protected_id)
        assert raw_digest(pixels(original, self.dimensions)) == expected
        assert roles(original) == roles(helper) == roles(protected) == ("FILE", "Non-Color", "CHANNEL_PACKED")
        restored_hash = packed_hash(original)
        assert restored_hash == result["packed_sha256"] and result["packed_payload_replaced"] is (not original_loaded)
        assert (restored_hash == writer["original_packed_sha256"]) is original_loaded
        assert helper[storage.OWNER_KEY] == original and packed_hash(helper) == helper_hash
        tuple(helper.size)  # Verify the exact freshly reopened packed helper as well as the restored original.
        assert raw_digest(pixels(helper, self.dimensions)) == expected
        assert packed_hash(protected) == protected_hash and bool(protected.has_data) is protected_loaded
        tuple(protected.size)
        assert raw_digest(pixels(protected, PROTECTED_DIMENSIONS)) == raw_digest(array("f", PROTECTED_CHANNELS) * 4)
        assert bindings(bpy, original, protected) == before
        assert file_proof(self.check_missing_source(original))["sha256"] == writer["original_packed_sha256"]
        assert file_proof(self.first) == proof
        self.capture_peak_memory()
        self.evidence.update(checkpoint_id=checkpoint, checkpoint_file=proof, reopened=True, restore=job,
                             original_loaded_before_restore=original_loaded, original_pre_restore_raw_sha256=original_before_digest,
                             restoration_mode=preview["mode"], explicit_packed_replacement=preview["requires_confirm_replace_packed_bytes"],
                             original_raw_sha256=expected, snapshot_raw_sha256=expected, dimensions=self.dimensions,
                             restored_packed_sha256=restored_hash, original_id_preserved=True,
                             roles_preserved=True, protected_consumer_preserved=True, shared_bindings_preserved=True,
                             scene_save_unchanged=True, source_path_unavailable=True)


def main():
    import addon_utils
    import bpy

    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    phase = args.bridge_phase
    token = os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    bundle = args.bridge_bundle.resolve(strict=True)
    assert re.fullmatch("[0-9a-f]{32}", token) and not bpy.app.background
    assert {"--factory-startup", "--disable-autoexec"} <= set(sys.argv) and not bpy.data.filepath
    case = bundle.name.removesuffix("-bundle")
    assert args.bridge_bundle == bundle and bundle.is_dir() and bundle.name == f"{case}-bundle" and case in CASES
    profile = CASES[case]
    assert not (bundle / (phase + ".json")).exists()
    config = Path(os.environ["BLENDER_USER_CONFIG"])
    assert config == bundle / "bridge-config" and config.is_dir() and not config.is_symlink()
    temporary = Path(os.environ["TEMP"])
    assert temporary == bundle.parent / f"{case}-{phase}-temp"
    for name in ("BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        path = Path(os.environ[name])
        assert path.parent == temporary and path.is_dir() and not path.is_symlink()
    sys.path.insert(0, str(ROOT / "addon"))
    assert addon_utils.enable(ADDON, default_set=True, persistent=True) is not None
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime

    from scripts.blender_image_delivery_smoke import Client

    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    prefs = get_preferences()
    assert prefs is not None
    scenario = EditedTextureScenario(bpy, prefs, get_runtime(), bundle, phase, False, token)
    scenario.client_factory = Client
    scenario.dimensions = PROFILES[profile]
    scenario.job_limit = 240. if profile == "LARGE4K" else 25.
    if profile == "LARGE4K":
        scenario.deadline = time.monotonic() + 285.
    bpy.app.timers.register(scenario.tick, first_interval=.05, persistent=True)


if __name__ == "__main__":
    main()
