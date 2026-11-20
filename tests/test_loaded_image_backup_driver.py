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
        payloads=SimpleNamespace(original_packed_sha256="3" * 64,
                                 original_decoded_pixels_sha256="4" * 64,
                                 current_pixels_sha256_float32_le="5" * 64),
    )

    def compare_source(_context):
        calls.append("complete source comparison")
        return capture

    origin = SimpleNamespace(
        capture=capture, file_plan=object(), binding=SimpleNamespace(nonce="a" * 32),
        parameters={"expected_target_fingerprint": "6" * 64, "affected_materials": ["Material"]},
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
    assert fixture.driver.recovery_evidence()["stage"] == "BACKUPS_PARTIAL"
    with pytest.raises(StopIteration) as done:
        next(generator)
    assert done.value.value == {"phase": "backups_verified", "files": [{"kind": "manifest"}],
                                "manifest_sha256": "a" * 64, "image_packed": False, "project_saved": False}
    assert fixture.calls == ["grants", "complete source comparison", "file gate"] * 2
    receipt = fixture.driver.recovery_evidence()
    assert receipt["stage"] == "BACKUPS_DURABLE" and receipt["durable_backups_verified"] is True
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
