from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def driver_fixture(addon_package, monkeypatch):
    domain = importlib.import_module(f"{addon_package}.tools.image_current_pixels")
    calls = []
    capture = SimpleNamespace(
        full_native_prefix_sha256="1" * 64, consumer_graph_sha256="2" * 64,
        original_metadata={"static": {"width": 2, "height": 2}},
        payloads=SimpleNamespace(original_packed_sha256="3" * 64,
                                 original_decoded_pixels_sha256="4" * 64,
                                 current_pixels_sha256_float32_le="5" * 64),
    )

    def compare_source(_context):
        calls.append("complete source comparison")
        return capture

    origin = SimpleNamespace(
        capture=capture, file_plan=SimpleNamespace(journal_enabled=False),
        binding=SimpleNamespace(nonce="a" * 32), input_deferred=False,
        parameters={"expected_target_fingerprint": "6" * 64, "affected_materials": ["Material"],
                    "image_name": "Original", "snapshot_name": "Snapshot"},
        authorize=lambda _context: calls.append("grants"),
        refresh_capture=compare_source,
        _read_gate=lambda: calls.append("file gate"),
    )
    resource = SimpleNamespace(attempted=False, verified=False,
                               close=lambda: calls.append("close"))
    resource.evidence = lambda: {"durable_backups_verified": resource.verified}
    monkeypatch.setattr(domain.files, "BackupFiles", lambda _plan: resource)
    driver = domain.CurrentPixelsDriver({"origin": origin, "source_name": "Original", "name": "Snapshot"})
    return SimpleNamespace(domain=domain, resource=resource, driver=driver, calls=calls)


def test_backup_driver_compares_full_source_before_each_file_turn(driver_fixture):
    fixture = driver_fixture

    def prepare_pair_steps(_capture, *, check, **_kwargs):
        check()
        fixture.resource.attempted = True
        yield {"phase": "write", "completed": 1, "total": 1}
        check()
        fixture.resource.verified = True
        return {"files": [{"kind": "manifest"}], "manifest_sha256": "a" * 64}

    fixture.resource.prepare_pair_steps = prepare_pair_steps
    generator = fixture.driver.steps(object(), None, None)
    assert next(generator)["phase"] == "write"
    assert fixture.driver.receipt["stage"] == "BACKUPS_PARTIAL"
    intermediate = fixture.driver.recovery_evidence()
    assert intermediate["state_known"] is False and intermediate["external_write_attempted"] is True
    with pytest.raises(StopIteration) as done:
        next(generator)
    assert done.value.value == {"phase": "backups_verified", "files": [{"kind": "manifest"}],
                                "manifest_sha256": "a" * 64, "image_packed": False, "project_saved": False}
    assert fixture.calls == ["grants", "complete source comparison", "file gate"] * 2
    receipt = fixture.driver.recovery_evidence()
    assert fixture.driver.receipt["stage"] == "BACKUPS_DURABLE"
    assert receipt["stage"] == "UNKNOWN" and receipt["state_known"] is False
    assert receipt["observed_prefix"] is None and receipt["observed_prefix_sha256"] is None
    assert receipt["expected_prefix_sha256"] == "1" * 64 and receipt["durable_backups_verified"] is True
    assert receipt["image_write_attempted"] is False and receipt["helper_record_write_attempted"] is False
    assert receipt["recovery_authorized"] is False


@pytest.mark.parametrize("external_attempted", [False, True])
def test_backup_driver_marks_only_actual_partial_effects_after_failure(driver_fixture, external_attempted):
    fixture = driver_fixture

    def prepare_pair_steps(_capture, *, check, **_kwargs):
        check()
        fixture.resource.attempted = external_attempted
        yield from ()
        raise RuntimeError("fixture file failure")

    fixture.resource.prepare_pair_steps = prepare_pair_steps
    with pytest.raises(RuntimeError, match="fixture file failure"):
        next(fixture.driver.steps(object(), None, None))
    receipt = fixture.driver.recovery_evidence()
    assert receipt["stage"] == "UNKNOWN" and receipt["state_known"] is False
    assert receipt["external_write_attempted"] is external_attempted
    assert receipt["possible_mutation"] is external_attempted


def test_deferred_archive_keeps_verified_original_bytes_after_a_new_scene_edit(driver_fixture):
    fixture = driver_fixture
    origin = fixture.driver.origin
    original_capture = origin.capture
    origin.input_deferred = True
    origin.prepare_acquisition = lambda _context: fixture.calls.append("approved plan")
    origin.release_acquisition = lambda: setattr(origin, "capture", None)

    def acquire_steps(_context):
        yield {"phase": "source_read"}
        fixture.calls.append("complete source comparison")
        return original_capture

    def prepare_pair_steps(capture, *, check, **_kwargs):
        assert capture is original_capture
        frozen_digest = capture.payloads.original_packed_sha256
        check()
        fixture.resource.attempted = True
        yield {"phase": "write", "completed": 1, "total": 1}
        check()
        assert frozen_digest == "3" * 64
        fixture.resource.verified = True
        return {"files": [{"kind": "manifest"}], "manifest_sha256": "a" * 64}

    origin.acquire_steps = acquire_steps
    fixture.resource.prepare_pair_steps = prepare_pair_steps
    driver = fixture.domain.CurrentPixelsDriver({"origin": origin})
    assert driver.files is None and driver.recovery_evidence()["possible_mutation"] is False
    worker = driver.steps(object(), None, None)
    assert next(worker)["phase"] == "backup_preflight"
    assert next(worker)["phase"] == "source_read"
    assert next(worker)["phase"] == "write"
    assert origin.capture is None
    origin.capture = SimpleNamespace(full_native_prefix_sha256="e" * 64)
    with pytest.raises(StopIteration) as done:
        next(worker)
    assert done.value.value["phase"] == "backups_verified"
    assert done.value.value["historical_archive"] is True
    assert done.value.value["current_scene_match_verified"] is False
    assert fixture.calls == ["approved plan", "complete source comparison", "file gate", "grants", "file gate"]
    assert driver.recovery_evidence()["durable_backups_verified"] is True
