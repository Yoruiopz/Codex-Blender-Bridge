from __future__ import annotations

import copy
import importlib

import pytest


@pytest.fixture
def history(addon_package):
    state = importlib.import_module(f"{addon_package}.state")
    contract = importlib.import_module(f"{addon_package}.current_pixels_contract")
    errors = importlib.import_module(f"{addon_package}.errors")
    return state, contract, errors


def facts():
    return {"kind": "current_pixels_lifecycle", "schema_version": 1,
            "method": "image.pack_current_pixels_job_start", "mode": "CURRENT_PIXELS_PACK",
            "profile": "FILE_F32_EXR_DATA_CURRENT_PIXELS_V1", "stage": "FORWARD_COMPLETE",
            "identity_mode": "SAME_SESSION_NATIVE_IDS", "image_name": "Original",
            "snapshot_name": "Current Snapshot", "external_write_attempted": True,
            "helper_record_write_attempted": True, "image_write_attempted": True,
            "state_known": True, "possible_mutation": True, "verification_required": True,
            "recovery_authorized": False, "project_saved": False, "source_file_read": False,
            "automatic_inverse_attempted": False, "durable_backups_verified": True,
            "packed_bytes_verified": True, "complete_pixels_verified": True,
            "snapshot_retained": True, "owned_write_attempts": 4,
            "current_pixels_sha256_float32_le": "1" * 64,
            "previous_packed_sha256": "2" * 64, "current_packed_sha256": "3" * 64,
            "previous_decoded_pixels_sha256": "4" * 64,
            "record_uuid": "5" * 32, "runtime_nonce": "6" * 32,
            "expected_target_fingerprint": "7" * 64,
            "manifest_sha256": "8" * 64, "expected_prefix_sha256": "9" * 64,
            "observed_prefix_sha256": "9" * 64, "observed_prefix": "FORWARD_COMPLETE",
            "consumer_graph_sha256": "a" * 64, "same_session_original_pointer": "a123",
            "same_session_original_uid": "123456", "packed_bytes": 1024}


def record(state, evidence, *, success=False):
    return state.record_operation(tool=evidence["method"], description="Current pixel lifecycle",
                                  success=success, duration_ms=2., recovery_evidence=evidence)


def test_new_kind_retains_every_typed_fact_without_becoming_recovery_authority(history):
    module, _contract, _errors = history
    source = facts()
    result = module.bounded_recovery_evidence(source)
    assert result == source and result is not source
    state = module.BridgeState(history_limit=3)
    stored = record(state, source)
    assert stored.recovery_evidence == source
    assert not stored.success and stored.recovery_evidence["recovery_authorized"] is False
    source["image_name"] = "Caller modified dictionary"
    assert state.history(1)[0]["recovery_evidence"]["image_name"] == "Original"


def test_unknown_final_observation_keeps_attempts_last_hashes_and_uncertainty(history):
    module, contract, _errors = history
    measured = facts()
    unknown = contract.unknown_observation(measured)
    stored = record(module.BridgeState(), unknown).recovery_evidence
    assert stored["stage"] == "UNKNOWN" and stored["state_known"] is False
    assert stored["observed_prefix"] is None and stored["observed_prefix_sha256"] is None
    for name in ("external_write_attempted", "helper_record_write_attempted", "image_write_attempted",
                 "owned_write_attempts", "previous_packed_sha256", "current_packed_sha256",
                 "current_pixels_sha256_float32_le", "expected_prefix_sha256", "manifest_sha256"):
        assert stored[name] == measured[name]
    assert stored["verification_required"] and not stored["recovery_authorized"]


@pytest.mark.parametrize("field", ["schema_version", "method", "mode", "profile", "stage", "identity_mode",
    "external_write_attempted", "helper_record_write_attempted", "image_write_attempted", "state_known",
    "possible_mutation", "verification_required", "recovery_authorized", "project_saved", "source_file_read",
    "automatic_inverse_attempted"])
def test_recognized_missing_required_field_raises_instead_of_empty_success(history, field):
    module, _contract, errors = history
    receipt = facts()
    del receipt[field]
    with pytest.raises(errors.BridgeError) as error:
        module.bounded_recovery_evidence(receipt)
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("field,value", [
    ("unexpected", "silently dropped proof"), ("schema_version", True),
    ("mode", "PACKED_RECONSTRUCTION"), ("method", "image.snapshot_job_start"),
    ("stage", "RESTORED_COMPLETE"), ("identity_mode", "UNAVAILABLE"),
    ("possible_mutation", False), ("external_write_attempted", 1),
    ("helper_record_write_attempted", False), ("image_write_attempted", False),
    ("durable_backups_verified", False), ("packed_bytes_verified", False),
    ("complete_pixels_verified", False), ("verification_required", False),
    ("recovery_authorized", True), ("project_saved", True), ("source_file_read", True),
    ("automatic_inverse_attempted", True), ("image_name", "é" * 32),
    ("snapshot_name", "bad\nname"), ("current_packed_sha256", "A" * 64),
    ("owned_write_attempts", True), ("owned_write_attempts", 9),
    ("owned_write_attempts", 2), ("packed_bytes", 269484033),
    ("same_session_original_pointer", "f" * 17), ("same_session_original_uid", "1" * 21),
    ("observed_prefix_sha256", "0" * 64), ("state_known", False),
])
def test_recognized_malformed_receipt_is_rejected_before_history_append(history, field, value):
    module, _contract, errors = history
    state = module.BridgeState(history_limit=3)
    record(state, facts(), success=True)
    before = copy.deepcopy(state.history(3))
    receipt = {**facts(), field: value}
    with pytest.raises(errors.BridgeError):
        record(state, receipt)
    assert state.history(3) == before


def test_new_kind_does_not_change_legacy_image_reducer_output_or_drop_legacy_extras(history):
    module, _contract, _errors = history
    legacy = {"mode": "LOADED_BUFFER", "image_name": "Legacy", "snapshot_name": "Snapshot",
              "snapshot_retained": True, "project_saved": False, "source_file_read": False,
              "possible_mutation": True, "previous_packed_sha256": None,
              "pixels_sha256_float32_le": "a" * 64, "packed_bytes": 288 * 1024 * 1024}
    assert module.bounded_recovery_evidence({**legacy, "old_unknown": [0] * 10000}) == legacy
    assert module.bounded_recovery_evidence({"kind": "not-a-recognized-kind", **legacy}) == legacy
    assert module.bounded_recovery_evidence({"mode": "invalid", "packed_bytes": True}) is None
    assert module.bounded_recovery_evidence(None) is None


def test_four_artifact_and_existing_history_caps_are_unchanged(history):
    module, contract, _errors = history
    assert module.MAX_EXTERNAL_ARTIFACTS == contract.MAX_EXTERNAL_ARTIFACTS == 4
    artifacts = [{"filepath": f"/approved/{index}.bin", "file_bytes": 4, "file_sha256": "a" * 64}
                 for index in range(5)]
    state = module.BridgeState(history_limit=3)
    for _ in range(5):
        state.record_operation(tool="image.pack_current_pixels_job_start", description="Bounded event",
                               success=False, duration_ms=1., recovery_evidence=facts(),
                               external_effects={"artifacts": artifacts})
    assert len(state.history(100)) == 3
    effects = state.history(1)[0]["external_effects"]
    assert len(effects["artifacts"]) == 4 and effects["artifacts_truncated"]
    assert state.history(1)[0]["recovery_evidence"] == facts()


def test_recovery_noop_receipt_cannot_claim_image_restoration_or_helper_writes(history):
    module, _contract, errors = history
    noop = {**facts(), "method": "image.restore_current_pixels_job_start", "mode": "CURRENT_PIXELS_RESTORE",
            "stage": "ALREADY_AT_BACKED_UP_STATE", "observed_prefix": "ALREADY_AT_BACKED_UP_STATE",
            "external_write_attempted": False, "helper_record_write_attempted": False,
            "image_write_attempted": False, "possible_mutation": False, "owned_write_attempts": 0}
    assert module.bounded_recovery_evidence(noop) == noop
    for field in ("image_write_attempted", "helper_record_write_attempted"):
        with pytest.raises(errors.BridgeError):
            module.bounded_recovery_evidence({**noop, field: True, "possible_mutation": True})
