from __future__ import annotations

import asyncio
import importlib
import json
import struct
from array import array
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.image_portability import ImagePortabilityTools


class Pixels:
    def __init__(self, values):
        self.values = array("f", values)
        self.writes = 0
        self.fail_write = False

    def __len__(self):
        return len(self.values)

    def foreach_get(self, output):
        output[:] = self.values

    def foreach_set(self, values):
        self.writes += 1
        if self.fail_write:
            self.values[0] = values[0]
            raise RuntimeError("Injected partial pixel publication")
        self.values[:] = values


class Image(dict):
    __hash__ = object.__hash__
    __eq__ = object.__eq__
    __ne__ = object.__ne__

    def __init__(self, name, values, module, *, users=0):
        super().__init__()
        self.name, self.source, self.type = name, "GENERATED", "UV_TEST"
        self.bl_rna = NS(identifier="Image")
        self.filepath = ""
        self.library, self.override_library, self.is_editable = None, None, True
        self.has_data, self.is_multiview, self.is_float, self.is_dirty = True, False, True, False
        self.channels, self.size = 4, (2, 1)
        self.colorspace_settings, self.alpha_mode = NS(name="Non-Color"), "CHANNEL_PACKED"
        self.animation_data, self.packed_file = None, None
        self.pixels, self.users, self._fake = Pixels(values), users, False
        self.module, self.fail_pack = module, False

    @property
    def use_fake_user(self):
        return self._fake

    @use_fake_user.setter
    def use_fake_user(self, enabled):
        self.users += int(enabled) - int(self._fake)
        self._fake = enabled

    def __setitem__(self, key, value):
        if key == self.module.OWNER_KEY:
            value.users += 1
        super().__setitem__(key, value)

    def pack(self, *, data, data_len):
        if self.fail_pack:
            raise RuntimeError("Injected native packing failure")
        assert data_len == len(data)
        self.packed_file = NS(size=len(data), data=data)
        width, height = self.size
        header_size = len(self.module.pixel_codecs.exr_header(width, height, "EXR32_RAW", "DATA"))
        start = header_size + height * 8 + 8
        planes = struct.unpack_from("<" + "f" * (width * 4), data, start)
        self.pixels.values[:] = array("f", [planes[channel * width + column] for column in range(width) for channel in (3, 2, 1, 0)])

    def update(self):
        self.is_dirty = True


class Images(list):
    fail_pack = False

    def get(self, name):
        return next((image for image in self if image.name == name), None)

    def new(self, name, width, height, *, alpha, float_buffer):
        image = Image(name, [0.] * (width * height * 4), self[0].module)
        image.size = width, height
        image.fail_pack = self.fail_pack
        self.append(image)
        return image

    def remove(self, image, *, do_unlink):
        assert do_unlink is False
        owner = image.get(image.module.OWNER_KEY)
        if owner is not None:
            owner.users -= 1
        super().remove(image)


@pytest.fixture
def fixture(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.image_portability")
    values = array("f", [-0., -.125, 65536., -2., .1234567, 2., 4., 2.])
    target = Image("Original", values, module, users=1)
    collection = Images([target])
    consumer = NS(name="Protected Material", bl_rna=NS(identifier="Material"),
                  library=None, override_library=None, is_editable=True, users=1, use_fake_user=False)
    owners = [consumer]
    bpy = NS(context=NS(mode="OBJECT"), data=NS(images=collection,
             user_map=lambda **_: {target: [*owners, *(image for image in collection if image.get(module.OWNER_KEY) is target)]}))
    grants = {"EDIT_MATERIALS": True, "ACCESS_EXTERNAL_FILES": True, "DELETE_OBJECTS": True}
    flags = {"paused": False, "emergency_stopped": False}
    def require(*permissions):
        if any(not grants.get(permission.value, False) for permission in permissions):
            raise module.BridgeError("PERMISSION_DENIED", "Denied")
    context = NS(require=require, state=NS(snapshot=lambda: dict(flags)), check_cancelled=None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module.image_paint, "_read", lambda ctx, image, **_: (*module._buffer(ctx, image), None))
    return NS(module=module, values=values, target=target, images=collection, bpy=bpy,
              context=context, grants=grants, flags=flags, owners=owners)


@pytest.fixture
def unloaded_recovery(fixture, addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.image_recovery")
    fixture.grants["INSPECT_SCENE"] = True
    target = fixture.target
    target.source, target.type, target.filepath = "FILE", "IMAGE", "/unavailable/original.exr"
    packed(fixture)
    target.has_data = False
    original_pack = target.pack
    writes = []
    def publish(*args, **kwargs):
        writes.append(kwargs["data"])
        original_pack(*args, **kwargs)
        target.has_data = True
    monkeypatch.setattr(target, "pack", publish)
    monkeypatch.setattr(module, "require_blender", lambda: fixture.bpy)
    return NS(module=module, fixture=fixture, target=target, writes=writes,
              context=fixture.context, grants=fixture.grants)


def reconstruction_preview(fixture, **kwargs):
    return fixture.module.recovery_preview(fixture.context, {"image_name": "Original", "snapshot_name": "Snapshot", **kwargs})


def reconstruct(fixture, preview, **kwargs):
    return fixture.module.restore_packed_snapshot(fixture.context, {"image_name": "Original", "snapshot_name": "Snapshot",
        "expected_target_fingerprint": preview["expected_target_fingerprint"], "confirm_replace_packed_bytes": True, **kwargs})


def test_unloaded_preview_does_not_require_edit_or_access_native_target_pixels(unloaded_recovery, monkeypatch):
    f = unloaded_recovery
    f.grants["EDIT_MATERIALS"] = False
    monkeypatch.setattr(f.target.pixels, "foreach_get", lambda _: pytest.fail("Unloaded target pixel read"))
    result = reconstruction_preview(f)
    assert len(result["expected_target_fingerprint"]) == 64
    assert not result["mutation_performed"] and not result["source_file_read"]
    assert result["requires_confirm_replace_packed_bytes"] and not f.writes and not f.target.has_data


def test_confirmed_unloaded_reconstruction_preserves_id_and_snapshot_without_save(unloaded_recovery):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    result = reconstruct(f, preview)
    assert result["restored"] and result["image_identity_preserved"] and result["complete_pixels_verified"]
    assert result["packed_payload_replaced"] and result["snapshot_retained"]
    assert not result["file_written"] and not result["project_saved"]
    assert f.fixture.images.get("Original") is f.target and len(f.writes) == 1
    assert f.fixture.images.get("Snapshot") is not None


@pytest.mark.parametrize("field,value", [("filepath", "/new/manual/source.exr"), ("alpha_mode", "STRAIGHT"), ("name", "Other")])
def test_reconstruction_rejects_stale_preview_before_pack(unloaded_recovery, field, value):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    setattr(f.target, field, value)
    with pytest.raises(f.module.BridgeError):
        reconstruct(f, preview)
    assert not f.writes


@pytest.mark.parametrize("permission", ["INSPECT_SCENE", "EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES"])
def test_reconstruction_live_permissions_block_before_pack(unloaded_recovery, permission):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    f.grants[permission] = False
    with pytest.raises(f.module.BridgeError) as caught:
        reconstruct(f, preview)
    assert caught.value.code == "PERMISSION_DENIED" and not f.writes


def test_reconstruction_requires_explicit_confirmation(unloaded_recovery):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    with pytest.raises(f.module.BridgeError, match="confirm_replace_packed_bytes"):
        reconstruct(f, preview, confirm_replace_packed_bytes=False)
    assert not f.writes


def test_reconstruction_old_payload_hash_is_part_of_preview(unloaded_recovery):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    f.target.packed_file = NS(size=5, data=b"older")
    with pytest.raises(f.module.BridgeError, match="stale"):
        reconstruct(f, preview)
    assert not f.writes


def test_reconstruction_final_callback_scope_change_is_preserved(unloaded_recovery, monkeypatch):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    proof, calls = f.module._proof, []
    def interleaved(*args, **kwargs):
        calls.append(True)
        if len(calls) == 3:
            f.target.filepath = "/manual/newer.exr"
        return proof(*args, **kwargs)
    monkeypatch.setattr(f.module, "_proof", interleaved)
    with pytest.raises(f.module.BridgeError) as caught:
        reconstruct(f, preview)
    assert not caught.value.context["execution_started"] and not f.writes
    assert f.target.filepath == "/manual/newer.exr"


def test_late_reconstruction_revocation_retains_changed_target_and_snapshot(unloaded_recovery):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    def revoke_after_pack():
        if f.writes:
            f.grants["EDIT_MATERIALS"] = False
    f.context.check_cancelled = revoke_after_pack
    with pytest.raises(f.module.BridgeError) as caught:
        reconstruct(f, preview)
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["possible_mutation"] and caught.value.context["packed_payload_may_have_changed"]
    assert caught.value.context["snapshot_retained"] and not caught.value.context["rollback_verified"]
    assert f.target.packed_file is not None and f.fixture.images.get("Snapshot") is not None


def test_packed_reconstruction_does_not_guess_associated_float_color(unloaded_recovery):
    f = unloaded_recovery
    snapshot = f.fixture.images.get("Snapshot")
    metadata = json.loads(snapshot[f.fixture.module.METADATA_KEY])
    metadata["colorspace"], metadata["alpha_mode"] = "Linear Rec.709", "STRAIGHT"
    snapshot[f.fixture.module.METADATA_KEY] = json.dumps(metadata)
    f.target.colorspace_settings.name, f.target.alpha_mode = "Linear Rec.709", "STRAIGHT"
    with pytest.raises(f.module.BridgeError, match="associated color"):
        reconstruction_preview(f)
    assert not f.writes


def test_reconstruction_rejects_same_name_replacement_instead_of_retargeting_snapshot(unloaded_recovery):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    f.target.name = "Original Retained Under Another Name"
    replacement = Image("Original", f.fixture.values, f.fixture.module, users=1)
    replacement.source, replacement.type = "FILE", "IMAGE"
    replacement.filepath, replacement.has_data = "/unavailable/original.exr", False
    f.fixture.images.append(replacement)
    with pytest.raises(f.module.BridgeError, match="exact original image ID"):
        reconstruct(f, preview)
    assert not f.writes and replacement.packed_file is None


def test_reconstruction_fingerprint_expires_across_sessions(unloaded_recovery, monkeypatch):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    monkeypatch.setattr(f.module, "SESSION_NONCE", "different-process")
    with pytest.raises(f.module.BridgeError, match="stale"):
        reconstruct(f, preview)
    assert not f.writes


def test_reconstruction_new_buffer_acquisition_invalidates_preview_before_write(unloaded_recovery):
    f = unloaded_recovery
    preview = reconstruction_preview(f)
    f.target.has_data = True
    with pytest.raises(f.module.BridgeError, match="unloaded"):
        reconstruct(f, preview)
    assert not f.writes


def test_recovery_mcp_preserves_confirmation_and_rejects_weak_schema_values():
    from mcp_server.tools.image_recovery import ImageRecoveryTools
    calls = []
    class Registry:
        async def call(self, method, params):
            calls.append((method, params))
            return {"forwarded": True}
    tools = ImageRecoveryTools(Registry())
    result = asyncio.run(tools.image_restore_packed_snapshot("Original", "Snapshot", "a"*64, True, False))
    assert result == {"forwarded": True}
    assert calls == [("image.restore_packed_snapshot", {"image_name": "Original", "snapshot_name": "Snapshot",
        "expected_target_fingerprint": "a"*64, "confirm_replace_packed_bytes": True, "allow_shared": False})]
    hints = get_type_hints(tools.image_restore_packed_snapshot, include_extras=True)
    for bad in ("A"*64, "a"*63, "a"*65, "not-a-fingerprint", 42):
        with pytest.raises(ValidationError):
            TypeAdapter(hints["expected_target_fingerprint"]).validate_python(bad)
    for bad in (1, 0, "true", None):
        with pytest.raises(ValidationError):
            TypeAdapter(hints["confirm_replace_packed_bytes"]).validate_python(bad)


def _last_provider_fault(context, gate, arm, mutate):
    """Inject at the last grant provider regardless of permission batching.

    A harmless gate first measures provider calls. The real operation then arms
    only its final write boundary; assertions concern actual protected writes.
    """
    original, measured = context.require, []
    def measure(*required):
        measured.append(required)
        return original(*required)
    context.require = measure
    try:
        gate()
    finally:
        context.require = original
    assert measured
    calls, injected = [], []
    def provider(*required):
        result = original(*required)
        if arm():
            calls.append(required)
            if len(calls) == len(measured):
                mutate()
                injected.append(True)
        return result
    context.require = provider
    return injected


def _fault_state(fixture, change):
    if change == "mode":
        fixture.bpy.context.mode = "EDIT_MESH"
    else:
        fixture.flags[change] = True


@pytest.mark.parametrize("change", ["paused", "emergency_stopped", "mode"])
def test_final_grant_provider_cannot_allow_new_version_metadata_after_state_change(fixture, change):
    module, context = fixture.module, fixture.context
    injected = _last_provider_fault(context, lambda: module._gate(context, fixture.target),
        lambda: fixture.images.get("Snapshot") is not None,
        lambda: _fault_state(fixture, change))
    with pytest.raises(module.BridgeError):
        packed(fixture)
    snapshot = fixture.images.get("Snapshot")
    assert injected and snapshot is not None
    assert snapshot.source == "GENERATED" and snapshot.filepath == ""
    assert snapshot.packed_file is None and module.METADATA_KEY not in snapshot
    assert module.OWNER_KEY not in snapshot and not snapshot.use_fake_user
    assert fixture.target.pixels.writes == 0


@pytest.mark.parametrize("change", ["paused", "emergency_stopped", "mode"])
def test_final_grant_provider_blocks_loaded_pixel_write_after_state_change(fixture, monkeypatch, change):
    packed(fixture)
    module, context, armed = fixture.module, fixture.context, []
    decode, calls = module._snapshot_buffer, []
    def arm_at_publication(*args, **kwargs):
        result = decode(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            armed.append(True)
        return result
    monkeypatch.setattr(module, "_snapshot_buffer", arm_at_publication)
    injected = _last_provider_fault(context, lambda: module._gate(context, fixture.target),
        lambda: bool(armed), lambda: _fault_state(fixture, change))
    before = fixture.target.pixels.values.tobytes()
    with pytest.raises(module.BridgeError) as caught:
        restore(fixture)
    assert injected and not caught.value.context["execution_started"]
    assert fixture.target.pixels.writes == 0 and fixture.target.pixels.values.tobytes() == before


@pytest.mark.parametrize("change", ["paused", "emergency_stopped", "mode"])
def test_final_grant_provider_blocks_unloaded_pack_after_state_change(unloaded_recovery, monkeypatch, change):
    f = unloaded_recovery
    inspected, armed = reconstruction_preview(f), []
    prepare = f.module._prepare
    def arm_at_publication(*args, **kwargs):
        result = prepare(*args, **kwargs)
        armed.append(True)
        return result
    monkeypatch.setattr(f.module, "_prepare", arm_at_publication)
    injected = _last_provider_fault(f.context, lambda: f.module._gate(f.context, f.target, modifying=True),
        lambda: bool(armed), lambda: _fault_state(f.fixture, change))
    with pytest.raises(f.module.BridgeError) as caught:
        reconstruct(f, inspected)
    assert injected and not caught.value.context["execution_started"]
    assert not f.writes and not f.target.has_data and f.target.packed_file is None


def packed(fixture):
    return fixture.module.pack_version(fixture.context, {"image_name": "Original", "new_name": "Snapshot", "mode": "CURRENT_PIXELS"})


def restore(fixture, **kwargs):
    return fixture.module.restore_pixels(fixture.context, {"image_name": "Original", "snapshot_name": "Snapshot", **kwargs})


def test_current_pixels_snapshot_packs_all_bits_without_source_mutation_or_save(fixture):
    before = fixture.module._metadata(fixture.target)
    result = packed(fixture)
    snapshot = fixture.images.get("Snapshot")
    assert result["current_pixels_verified"] and result["original_pixels_unchanged"]
    assert not result["project_saved"] and not result["external_file_written"] and not result["bound_to_nodes"]
    assert snapshot[fixture.module.OWNER_KEY] is fixture.target and snapshot.use_fake_user
    assert fixture.module._metadata(fixture.target) == before
    assert fixture.target.pixels.values.tobytes() == fixture.values.tobytes()
    # SAVE_PROJECT is not needed for in-memory packing; save is separately authorized.
    assert "SAVE_PROJECT" not in fixture.grants


def test_restore_changes_pixels_preserving_exact_id_and_consumers(fixture):
    packed(fixture)
    target = fixture.target
    target.pixels.values[:] = array("f", [1.]) * len(fixture.values)
    result = restore(fixture)
    assert result["complete_pixels_verified"] and result["image_identity_preserved"]
    assert target is fixture.images.get("Original") and target.pixels.values.tobytes() == fixture.values.tobytes()
    assert result["ownership"]["direct_consumers"] == [{"name": "Protected Material", "type": "Material"}]
    assert result["snapshot_retained"] and not result["project_saved"]


@pytest.mark.parametrize("space", ["sRGB", "Linear Rec.709", "Non-Color"])
@pytest.mark.parametrize("alpha", ["STRAIGHT", "CHANNEL_PACKED"])
def test_loaded_byte_restore_accepts_exact_native_channel_values(fixture, space, alpha):
    module, target = fixture.module, fixture.target
    values = array("f", [index * module._BYTE_SCALE for index in (0, 1, 2, 127, 128, 253, 254, 255)])
    target.is_float = False
    target.colorspace_settings.name, target.alpha_mode = space, alpha
    target.pixels.values[:] = values
    packed(fixture)
    target.pixels.values[:] = array("f", [0.]) * 8
    result = restore(fixture)
    assert result["complete_pixels_verified"] and target.pixels.values.tobytes() == values.tobytes()


@pytest.mark.parametrize("bad", [-0., .1, -1., 1.0001])
def test_byte_snapshot_with_unrepresentable_channels_is_refused_before_write(fixture, bad):
    target, module = fixture.target, fixture.module
    target.is_float = False
    target.pixels.values[:] = array("f", [0., 1., 0., 1., 0., 1., 0., 1.])
    packed(fixture)
    snapshot = fixture.images.get("Snapshot")
    values = array("f", target.pixels.values)
    values[0] = bad
    payload = b"".join(step.data for step in module.pixel_codecs.encode_steps(values, 2, 1, "EXR32_RAW", "DATA"))
    snapshot.packed_file = NS(size=len(payload), data=payload)
    metadata = json.loads(snapshot[module.METADATA_KEY])
    metadata["packed_sha256"] = module.hashlib.sha256(payload).hexdigest()
    metadata["pixels_sha256_float32_le"] = module.brush.digest(values)
    snapshot[module.METADATA_KEY] = json.dumps(metadata)
    with pytest.raises(module.BridgeError, match="lossy recovery"):
        restore(fixture)
    assert target.pixels.writes == 0


def test_recovery_preserves_newer_manual_pixels_when_callback_interleaves(fixture, monkeypatch):
    packed(fixture)
    module, target = fixture.module, fixture.target
    target.is_dirty = True
    before = array("f", [1.]) * 8
    target.pixels.values[:] = before
    original = module._snapshot_buffer
    newer = array("f", [.75]) * 8
    def interleaved(*args):
        result = original(*args)
        target.pixels.values[:] = newer
        return result
    monkeypatch.setattr(module, "_snapshot_buffer", interleaved)
    with pytest.raises(module.BridgeError) as caught:
        restore(fixture)
    assert not caught.value.context["execution_started"]
    assert target.pixels.writes == 0 and target.pixels.values.tobytes() == newer.tobytes()


@pytest.mark.parametrize("operation", ["pack", "restore"])
def test_permission_denial_precedes_any_pixel_read_or_allocation(fixture, monkeypatch, operation):
    if operation == "restore":
        packed(fixture)
    fixture.grants["EDIT_MATERIALS"] = False
    monkeypatch.setattr(fixture.target.pixels, "foreach_get", lambda _: pytest.fail("Denied pixel read"))
    count = len(fixture.images)
    with pytest.raises(fixture.module.BridgeError, match="Denied"):
        packed(fixture) if operation == "pack" else restore(fixture)
    assert len(fixture.images) == count and fixture.target.pixels.writes == 0


@pytest.mark.parametrize("flag,error", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")])
def test_pause_stop_prevent_new_packed_versions(fixture, flag, error):
    fixture.flags[flag] = True
    with pytest.raises(fixture.module.BridgeError) as caught:
        packed(fixture)
    assert caught.value.code == error and len(fixture.images) == 1


@pytest.mark.parametrize("invalid", ["AUTO", "file_bytes", None, True])
def test_pack_mode_must_be_explicit(fixture, invalid):
    with pytest.raises(fixture.module.BridgeError, match="FILE_BYTES or CURRENT_PIXELS"):
        fixture.module.pack_version(fixture.context, {"image_name": "Original", "new_name": "Snapshot", "mode": invalid})
    assert len(fixture.images) == 1


def test_file_bytes_never_claims_dirty_input_pixels_preserved(fixture, monkeypatch):
    module, source = fixture.module, fixture.target
    source.source, source.type = "FILE", "IMAGE"
    old_values = array("f", [.25, .5, .75, 1.]) * 2
    payload = b"".join(step.data for step in module.pixel_codecs.encode_steps(old_values, 2, 1, "EXR32_RAW", "DATA"))
    monkeypatch.setattr(module, "_file_bytes", lambda *_: (payload, {"file_sha256": "observed"}, "/approved/source.exr"))
    result = module.pack_version(fixture.context, {"image_name": "Original", "new_name": "File Version", "mode": "FILE_BYTES"})
    assert not result["current_pixels_verified"] and result["original_pixels_unchanged"]
    assert fixture.images.get("File Version").pixels.values.tobytes() == old_values.tobytes()
    assert source.pixels.values.tobytes() == fixture.values.tobytes()
    with pytest.raises(module.BridgeError, match="CURRENT_PIXELS"):
        module.restore_pixels(fixture.context, {"image_name": "Original", "snapshot_name": "File Version"})


def test_failed_allocation_cleanup_requires_independent_deletion_permission(fixture):
    fixture.images.fail_pack = True
    fixture.grants["DELETE_OBJECTS"] = False
    with pytest.raises(fixture.module.BridgeError) as caught:
        packed(fixture)
    assert caught.value.context["possible_mutation"] and caught.value.context["cleanup_permission_denied"]
    assert caught.value.context["retained_image_name"] == "Snapshot" and len(fixture.images) == 2
    assert fixture.target.pixels.writes == 0


def test_failed_owned_allocation_removes_only_zero_user_created_image(fixture):
    fixture.images.fail_pack = True
    with pytest.raises(fixture.module.BridgeError) as caught:
        packed(fixture)
    assert caught.value.context["rollback_verified"] and not caught.value.context["possible_mutation"]
    assert list(fixture.images) == [fixture.target]


def test_failed_name_verification_reports_actual_retained_handle_name(fixture, monkeypatch):
    original_new = fixture.images.new
    def renamed(*args, **kwargs):
        image = original_new(*args, **kwargs)
        image.name = "Snapshot.001"
        return image
    monkeypatch.setattr(fixture.images, "new", renamed)
    fixture.grants["DELETE_OBJECTS"] = False
    with pytest.raises(fixture.module.BridgeError) as caught:
        packed(fixture)
    assert caught.value.context["requested_image"] == "Snapshot"
    assert caught.value.context["retained_image_name"] == "Snapshot.001"
    assert caught.value.context["retained_name_is_last_observed"]
    assert fixture.images.get("Snapshot.001") is not None


@pytest.mark.parametrize("incoming", ["consumer", "retention"])
def test_acquired_new_version_receives_no_later_metadata_or_payload_writes(fixture, incoming):
    acquired = []
    def acquire():
        image = fixture.images.get("Snapshot")
        if image is not None and not acquired:
            if incoming == "consumer":
                image.users += 1
            else:
                image.use_fake_user = True
            acquired.append(image)
    fixture.context.check_cancelled = acquire
    with pytest.raises(fixture.module.BridgeError) as caught:
        packed(fixture)
    snapshot = acquired[0]
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]
    assert fixture.images.get("Snapshot") is snapshot
    assert snapshot.source == "GENERATED" and snapshot.filepath == "" and snapshot.packed_file is None
    assert fixture.module.METADATA_KEY not in snapshot and fixture.module.OWNER_KEY not in snapshot
    assert fixture.target.pixels.values.tobytes() == fixture.values.tobytes()


def test_current_pixels_missing_external_file_does_not_read_source_path(fixture, monkeypatch):
    fixture.target.source, fixture.target.type = "FILE", "IMAGE"
    fixture.target.filepath = "/missing/source.exr"
    monkeypatch.setattr(fixture.module.image_paint, "_read", lambda *a, **k: pytest.fail("External source path read"))
    result = packed(fixture)
    assert result["current_pixels_verified"] and result["source_file_at_read"] is None


def test_owned_cleanup_rechecks_delete_after_its_final_callback(fixture):
    fixture.images.fail_pack = True
    require, cleaning = fixture.context.require, []
    def track_cleanup(*permissions):
        result = require(*permissions)
        if any(permission.value == "DELETE_OBJECTS" for permission in permissions):
            cleaning.append(True)
        return result
    fixture.context.require = track_cleanup
    def revoke_in_cleanup():
        if cleaning:
            fixture.grants["DELETE_OBJECTS"] = False
    fixture.context.check_cancelled = revoke_in_cleanup
    with pytest.raises(fixture.module.BridgeError) as caught:
        packed(fixture)
    assert cleaning and caught.value.context["cleanup_permission_denied"]
    assert caught.value.context["possible_mutation"] and fixture.images.get("Snapshot") is not None


@pytest.mark.parametrize("change", ["unloaded", "byte", "resized", "colorspace", "alpha", "linked", "animated"])
def test_unsupported_restore_target_refused_before_write(fixture, change):
    packed(fixture)
    target = fixture.target
    if change == "unloaded":
        target.has_data = False
    elif change == "byte":
        target.is_float = False
    elif change == "resized":
        target.size = 1, 2
    elif change == "colorspace":
        target.colorspace_settings.name = "Linear Rec.709"
    elif change == "alpha":
        target.alpha_mode = "PREMUL"
    elif change == "linked":
        target.library = object()
    else:
        target.animation_data = NS(action=object())
    with pytest.raises(fixture.module.BridgeError):
        restore(fixture)
    assert target.pixels.writes == 0


@pytest.mark.parametrize("change", ["missing_metadata", "bad_json", "deep_json", "duplicate_key", "bad_utf8", "too_large", "wrong_owner", "packed_hash", "layout", "digest"])
def test_snapshot_is_untrusted_bounded_input(fixture, change):
    packed(fixture)
    module, snapshot = fixture.module, fixture.images.get("Snapshot")
    metadata = json.loads(snapshot[module.METADATA_KEY])
    if change == "missing_metadata":
        del snapshot[module.METADATA_KEY]
    elif change == "bad_json":
        snapshot[module.METADATA_KEY] = "not JSON"
    elif change == "deep_json":
        snapshot[module.METADATA_KEY] = "[" * 1500 + "0" + "]" * 1500
    elif change == "duplicate_key":
        snapshot[module.METADATA_KEY] = snapshot[module.METADATA_KEY][:-1] + ',"mode":"CURRENT_PIXELS"}'
    elif change == "bad_utf8":
        snapshot[module.METADATA_KEY] = "\ud800"
    elif change == "too_large":
        snapshot[module.METADATA_KEY] = "x" * 4097
    elif change == "wrong_owner":
        snapshot[module.OWNER_KEY] = NS(users=0)
    elif change == "packed_hash":
        snapshot.packed_file.data = snapshot.packed_file.data[:-1] + b"x"
    elif change == "layout":
        payload = b"x" + snapshot.packed_file.data[1:]
        snapshot.packed_file.data = payload
        metadata["packed_sha256"] = module.hashlib.sha256(payload).hexdigest()
        snapshot[module.METADATA_KEY] = json.dumps(metadata)
    else:
        metadata["pixels_sha256_float32_le"] = "0" * 64
        snapshot[module.METADATA_KEY] = json.dumps(metadata)
    with pytest.raises(module.BridgeError):
        restore(fixture)
    assert fixture.target.pixels.writes == 0


def test_more_than_one_consumer_requires_shared_acknowledgment(fixture):
    packed(fixture)
    fixture.target.users += 1
    with pytest.raises(fixture.module.BridgeError, match="allow_shared=true"):
        restore(fixture)
    result = restore(fixture, allow_shared=True)
    assert result["ownership"]["allow_shared"]


def test_linked_consumer_cannot_be_bypassed_with_shared_acknowledgment(fixture):
    packed(fixture)
    fixture.owners[0].library = object()
    with pytest.raises(fixture.module.BridgeError, match="consumers"):
        restore(fixture, allow_shared=True)
    assert fixture.target.pixels.writes == 0


def test_restoration_partial_write_is_truthful_and_retains_snapshot(fixture):
    packed(fixture)
    fixture.target.pixels.values[:] = array("f", [1.]) * len(fixture.values)
    fixture.target.pixels.fail_write = True
    with pytest.raises(fixture.module.BridgeError) as caught:
        restore(fixture)
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"] and caught.value.context["snapshot_retained"]
    assert fixture.images.get("Snapshot") is not None


def test_snapshot_pixels_are_read_from_canonical_memory_not_native_path(fixture, monkeypatch):
    packed(fixture)
    snapshot = fixture.images.get("Snapshot")
    snapshot.filepath = "/unapproved/missing/source.exr"
    snapshot.has_data = False
    monkeypatch.setattr(snapshot.pixels, "foreach_get", lambda _: pytest.fail("Native snapshot buffer/file read"))
    assert restore(fixture)["complete_pixels_verified"]


def test_oversized_payload_refused_before_data_getter(fixture):
    class Oversized:
        size = fixture.module.MAX_BYTES + 1
        @property
        def data(self):
            pytest.fail("Oversized packed bytes read")
    fixture.target.packed_file = Oversized()
    with pytest.raises(fixture.module.BridgeError, match="budget"):
        fixture.module._packed(fixture.target)


def test_mcp_wrapper_forwards_explicit_modes_and_strict_shared_argument():
    calls = []
    class Registry:
        async def call(self, name, values):
            calls.append((name, values))
            return {}
    tools = ImagePortabilityTools(Registry())
    asyncio.run(tools.image_pack_version("Original", "Snapshot", "CURRENT_PIXELS"))
    asyncio.run(tools.image_restore_pixels("Original", "Snapshot", True))
    assert calls == [("image.pack_version", {"image_name": "Original", "new_name": "Snapshot", "mode": "CURRENT_PIXELS"}),
                     ("image.restore_pixels", {"image_name": "Original", "snapshot_name": "Snapshot", "allow_shared": True})]
    hints = get_type_hints(ImagePortabilityTools.image_pack_version, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints["mode"]).validate_python("AUTO")
    with pytest.raises(ValidationError):
        TypeAdapter(hints["new_name"]).validate_python("é" * 40)
