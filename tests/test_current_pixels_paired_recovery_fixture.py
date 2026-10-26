"""Models for private fixture durability/oracles, without running Blender."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture():
    spec = importlib.util.spec_from_file_location(
        "paired_recovery_fixture", ROOT / "scripts/blender_current_pixels_paired_recovery_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_small_oracle_is_independent_and_signed_zero_sensitive(fixture):
    values = fixture.edited_values(2, 2)
    assert len(values) == 16 and fixture.raw_digest(values) == fixture.edited_oracle(2, 2)
    assert values[1] == .25 and values[2] == 0. and values[6] == 2. ** -24
    changed = array("f", values)
    changed[4] = 0.
    assert changed[4] == values[4] and fixture.raw_digest(changed) != fixture.raw_digest(values)


def test_image_animation_witness_measures_only_declared_rna_absence(fixture):
    rna = SimpleNamespace(identifier="Image", properties=[SimpleNamespace(identifier=name)
                          for name in ["rna_type", "name", "pixels"]])
    result = fixture.image_animation_schema_absence(rna)
    assert result["profile"] == "IMAGE_ANIMATION_DATA_RNA_ABSENT_V1"
    assert result["property"] == "animation_data" and result["declared"] is False
    assert result["catalog_count"] == 3 and len(result["ordered_catalog_sha256"]) == 64


def test_unexpected_image_animation_declaration_refuses_before_later_schema_reads(fixture):
    calls = []

    class LaterProperty:
        @property
        def identifier(self):
            calls.append("unexpected later metadata access")
            raise AssertionError("Must refuse before this read")

    rna = SimpleNamespace(identifier="Image", properties=[SimpleNamespace(identifier="animation_data"), LaterProperty()])
    with pytest.raises(AssertionError, match=r"Unexpected Image\.animation_data declaration"):
        fixture.image_animation_schema_absence(rna)
    assert not calls


def test_image_schema_witness_retains_ordered_occurrences_without_value_getters(fixture):
    rna = SimpleNamespace(identifier="Image", properties=[SimpleNamespace(identifier="name"),
                                                         SimpleNamespace(identifier="name")])
    result = fixture.image_animation_schema_absence(rna)
    assert result["catalog_count"] == 2
    assert result["ordered_catalog_sha256"] == fixture.record_hash(["name", "name"])


@pytest.mark.parametrize("identifier,names", [("Object", ["name"]), ("Image", []),
                                              ("Image", ["name"] * 257)])
def test_missing_foreign_or_unbounded_image_schema_refuses(fixture, identifier, names):
    rna = SimpleNamespace(identifier=identifier, properties=[SimpleNamespace(identifier=name) for name in names])
    with pytest.raises(AssertionError):
        fixture.image_animation_schema_absence(rna)


def test_socket_projection_preserves_registered_class_identifiers_defaults_and_flags(fixture):
    class VectorSocket:
        name, identifier = "Vector", "Vector_input_0"
        bl_idname, type = "NodeSocketVector", "VECTOR"
        default_value = (.25, -.5, .75)
        hide, enabled, is_linked = False, True, True

        @property
        def bl_socket_idname(self):
            raise AssertionError("Unsupported socket attribute must not be read")

    value = VectorSocket()
    result = fixture.socket_projection([value], native=lambda item: {"rna_type": item.bl_idname, "pointer": 17},
                                       scalar=lambda values: list(values))
    assert result == [{"name": "Vector", "identifier": "Vector_input_0", "type": "NodeSocketVector",
                       "_native": {"rna_type": "NodeSocketVector", "pointer": 17}, "default": [.25, -.5, .75],
                       "hide": False, "enabled": True, "is_linked": True}]
    assert result[0]["type"] != value.type


def test_missing_registered_socket_type_propagates_without_type_or_rna_fallback(fixture):
    socket = SimpleNamespace(name="Unknown", identifier="Unknown_0", type="VECTOR",
                             bl_rna=SimpleNamespace(identifier="NodeSocketVector"))
    with pytest.raises(AttributeError, match="bl_idname"):
        fixture.socket_projection([socket], native=lambda _value: pytest.fail("Type must resolve first"), scalar=lambda value: value)


def test_defaultless_shader_socket_model_keeps_its_explicit_absence(fixture):
    socket = SimpleNamespace(name="BSDF", identifier="BSDF", bl_idname="NodeSocketShader",
                             hide=False, enabled=True, is_linked=True)
    result = fixture.socket_projection([socket], native=lambda _value: {"pointer": 18}, scalar=lambda _value: pytest.fail("No default getter"))
    assert result[0]["type"] == "NodeSocketShader" and result[0]["default"] is None
    assert result[0]["identifier"] == "BSDF" and result[0]["is_linked"] is True


def test_socket_projection_bound_refuses_before_any_socket_getter(fixture):
    class Poison:
        @property
        def name(self):
            pytest.fail("Oversized socket collection must not be traversed")

    with pytest.raises(AssertionError):
        fixture.socket_projection([Poison()] * 65, native=lambda _value: None, scalar=lambda value: value)


@pytest.mark.parametrize("dimensions", [(0, 2), (1, 1), (4097, 4096), (2, 3)])
def test_unqualified_dimensions_refuse_before_allocating(fixture, dimensions):
    with pytest.raises(AssertionError):
        fixture.edited_values(*dimensions)
    with pytest.raises(AssertionError):
        fixture.edited_oracle(*dimensions)


@pytest.mark.parametrize("memory,disk", [(8 * 1024**3 - 1, 2 * 1024**3),
                                       (8 * 1024**3, 2 * 1024**3 - 1), (0, 0)])
def test_large_preflight_preserves_eight_and_two_gib_requirements(fixture, memory, disk):
    with pytest.raises(AssertionError):
        fixture.resource_check(memory, disk, large=True)
    fixture.resource_check(8 * 1024**3, 2 * 1024**3, large=True)


def test_manifest_duplicate_nonfinite_and_size_refusals(fixture, tmp_path):
    path = tmp_path / "manifest.json"
    for data in [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}']:
        path.write_bytes(data)
        with pytest.raises(ValueError):
            fixture.read_json(path)
    path.write_bytes(b' ' * (fixture.MAX_MANIFEST + 1))
    with pytest.raises(AssertionError):
        fixture.read_json(path)


def test_create_only_backup_has_file_and_parent_fsync_and_fresh_readback(fixture, tmp_path, monkeypatch):
    events, real_fsync = [], os.fsync

    def sync(fd):
        events.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(fixture.os, "fsync", sync)
    payload = b"closed durable artifact bytes"
    result = fixture.durable_new(tmp_path, "previous-packed.bin", payload)
    assert len(events) == 2
    assert result["file_fsync"] and result["parent_directory_fsync"]
    assert result["independent_reopen_verified"] and result["create_only"]
    assert result["bytes"] == len(payload) and result["sha256"] == hashlib.sha256(payload).hexdigest()
    with pytest.raises(FileExistsError):
        fixture.durable_new(tmp_path, "previous-packed.bin", b"replacement")
    assert (tmp_path / "previous-packed.bin").read_bytes() == payload


@pytest.mark.parametrize("sync_number", [1, 2])
def test_fsync_failure_retains_the_published_backup_and_does_not_claim_durability(fixture, tmp_path, monkeypatch, sync_number):
    calls = 0
    original = os.fsync

    def fail(fd):
        nonlocal calls
        calls += 1
        if calls == sync_number:
            raise OSError(errno.EIO, "injected fsync failure")
        original(fd)

    monkeypatch.setattr(fixture.os, "fsync", fail)
    with pytest.raises(OSError, match="injected"):
        fixture.durable_new(tmp_path, "current-pixels.exr", b"retained partial publication")
    assert (tmp_path / "current-pixels.exr").read_bytes() == b"retained partial publication"


@pytest.mark.parametrize("name", ["../escape", "elsewhere.bin", "/absolute", "manifest.json/child"])
def test_only_three_fixed_backup_names_are_accepted(fixture, tmp_path, name):
    with pytest.raises(AssertionError):
        fixture.durable_new(tmp_path, name, b"data")
    assert not list(tmp_path.iterdir())


def test_manifest_cap_is_not_widened_by_large_image_payload_budget(fixture, tmp_path):
    with pytest.raises(AssertionError):
        fixture.durable_new(tmp_path, "manifest.json", b"x" * (fixture.MAX_MANIFEST + 1))
    assert not list(tmp_path.iterdir())


def test_reopen_detects_complete_corruption_and_wrong_length(fixture, tmp_path):
    path = tmp_path / "current-pixels.exr"
    data = bytes(range(256)) * 4
    path.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    fixture.verify_file(path, expected_bytes=len(data), expected_sha256=expected)
    assert fixture.reopened_payload(path, expected_bytes=len(data), expected_sha256=expected) == data
    changed = bytearray(data)
    changed[-1] ^= 1
    path.write_bytes(changed)
    with pytest.raises(AssertionError):
        fixture.verify_file(path, expected_bytes=len(data), expected_sha256=expected)
    with pytest.raises(AssertionError):
        fixture.reopened_payload(path, expected_bytes=len(data), expected_sha256=expected)
    path.write_bytes(data[:-1])
    with pytest.raises(AssertionError):
        fixture.verify_file(path, expected_bytes=len(data), expected_sha256=expected)


def test_backup_symlinks_and_shared_hardlinks_refuse(fixture, tmp_path):
    path, other = tmp_path / "previous-packed.bin", tmp_path / "other"
    other.write_bytes(b"bytes")
    path.symlink_to(other)
    with pytest.raises(FileExistsError):
        fixture.durable_new(tmp_path, path.name, b"replacement")
    with pytest.raises(AssertionError):
        fixture.verify_file(path, expected_bytes=5, expected_sha256=hashlib.sha256(b"bytes").hexdigest())
    path.unlink()
    os.link(other, path)
    with pytest.raises(AssertionError):
        fixture.verify_file(path, expected_bytes=5, expected_sha256=hashlib.sha256(b"bytes").hexdigest())


def test_saved_comparison_strips_only_process_native_tokens(fixture):
    one = {"owner": {"name": "same", "rna_type": "Image", "_native": {"pointer": 123}}, "dirty": True}
    two = {"owner": {"name": "same", "rna_type": "Image", "_native": {"pointer": 456}}, "dirty": True}
    assert fixture.differences(one, two)
    assert fixture.scrub_native(one) == fixture.scrub_native(two)
    two["dirty"] = False
    assert fixture.differences(fixture.scrub_native(one), fixture.scrub_native(two)) == ["/dirty"]
    assert json.loads(fixture.canonical_json(one))["owner"]["_native"]["pointer"] == 123
