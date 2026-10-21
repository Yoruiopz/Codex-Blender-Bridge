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

    def __init__(self, name, values, module, *, users=0):
        super().__init__()
        self.name, self.source, self.type = name, "GENERATED", "UV_TEST"
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
                  library=None, override_library=None, is_editable=True)
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
