from __future__ import annotations

import copy
import hashlib
import importlib
import json

import pytest


@pytest.fixture
def contract(addon_package):
    return importlib.import_module(f"{addon_package}.current_pixels_contract")


def pack_request():
    return {"image_name": "Original", "snapshot_name": "Edited Pixels", "affected_materials": ["Material"],
            "backup_directory": "/approved/backups", "backup_prefix": "asset_01"}


def receipt(*, restore=False):
    return {"kind": "current_pixels_lifecycle", "schema_version": 1,
            "method": "image.restore_current_pixels_job_start" if restore else "image.pack_current_pixels_job_start",
            "mode": "CURRENT_PIXELS_RESTORE" if restore else "CURRENT_PIXELS_PACK",
            "profile": "FILE_F32_EXR_DATA_CURRENT_PIXELS_V1", "stage": "PREPARED",
            "identity_mode": "SAME_SESSION_NATIVE_IDS", "external_write_attempted": False,
            "helper_record_write_attempted": False, "image_write_attempted": False,
            "state_known": True, "possible_mutation": False, "verification_required": True,
            "recovery_authorized": False, "project_saved": False, "source_file_read": False,
            "automatic_inverse_attempted": False}


def prefix_facts(stage, *, restore=False):
    """Independently valid facts for each measured boundary, including skips."""
    value = {**receipt(restore=restore), "stage": stage}
    if stage == "UNKNOWN":
        return {**value, "state_known": False}
    if restore:
        if stage == "ALREADY_AT_BACKED_UP_STATE":
            return {**value, "durable_backups_verified": True,
                    "packed_bytes_verified": True, "complete_pixels_verified": True}
        if stage != "PREPARED":
            value.update(image_write_attempted=True, possible_mutation=True,
                         durable_backups_verified=True, previous_decoded_pixels_sha256="a" * 64)
        if stage in {"RESTORE_PREVIOUS_PACK_VERIFIED", "RESTORE_EDITED_PIXELS_ATTEMPT", "RESTORED_COMPLETE"}:
            value["packed_bytes_verified"] = True
        if stage == "RESTORED_COMPLETE":
            value["complete_pixels_verified"] = True
    else:
        if stage != "PREPARED":
            value.update(external_write_attempted=True, possible_mutation=True)
        if stage not in {"PREPARED", "BACKUPS_PARTIAL"}:
            value["durable_backups_verified"] = True
        if stage not in {"PREPARED", "BACKUPS_PARTIAL", "BACKUPS_DURABLE"}:
            value["helper_record_write_attempted"] = True
        if stage in {"PACK_ATTEMPT", "PACKED_BYTES_VERIFIED", "BUFFER_DISCARD_ATTEMPT", "PACKED_BUFFER_DISCARDED", "FORWARD_COMPLETE"}:
            value["image_write_attempted"] = True
        if stage in {"PACKED_BYTES_VERIFIED", "BUFFER_DISCARD_ATTEMPT", "PACKED_BUFFER_DISCARDED", "FORWARD_COMPLETE"}:
            value["packed_bytes_verified"] = True
        if stage == "FORWARD_COMPLETE":
            value["complete_pixels_verified"] = True
    return value


def manifest():
    native = [
        {"kind": "Image", "name": "Original", "pointer": "abc", "session_uid": "41", "content_sha256": "a" * 64},
        {"kind": "Image", "name": "Edited Pixels", "pointer": "def", "session_uid": "42", "content_sha256": "b" * 64},
        {"kind": "Material", "name": "Material", "pointer": "123", "session_uid": "43", "content_sha256": "c" * 64},
    ]
    return {"kind": "current_pixels_manifest", "schema_version": 1,
            "profile": "FILE_F32_EXR_DATA_CURRENT_PIXELS_V1", "record_uuid": "1" * 32, "runtime_nonce": "2" * 32,
            "image_name": "Original", "snapshot_name": "Edited Pixels", "width": 2, "height": 2,
            "affected_materials": ["Material"], "backup_prefix": "asset_01",
            "current_pixels_sha256_float32_le": "d" * 64, "previous_packed_sha256": "e" * 64,
            "previous_decoded_pixels_sha256": "f" * 64, "native_graph_sha256": "3" * 64,
            "portable_graph_sha256": "4" * 64, "original_identity": {"pointer": "abc", "session_uid": "41"},
            "snapshot_identity": {"pointer": "def", "session_uid": "42"},
            "roles": {"source": "FILE", "file_format": "OPEN_EXR", "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED", "is_float": True},
            "native_identity_rows": native,
            "portable_identity_rows": [{key: value for key, value in row.items() if key not in {"pointer", "session_uid"}} for row in native],
            "backups": {"oldpacked": {"filename": "asset_01.oldpacked.bin", "bytes": 400, "sha256": "e" * 64},
                        "current": {"filename": "asset_01.current.exr", "bytes": 500, "sha256": "5" * 64}}}


def test_all_four_request_shapes_have_explicit_confirmations_and_fresh_copies(contract):
    params = pack_request()
    validated = contract.validate_request(contract.PACK_PREVIEW, params)
    assert validated == {**params, "retain_event_journal": True}
    params["affected_materials"].append("Changed")
    assert validated["affected_materials"] == ["Material"]
    started = contract.validate_request(contract.PACK_START, {**pack_request(), "expected_target_fingerprint": "a" * 64,
        "confirm_replace_packed_bytes": True, "confirm_discard_current_buffer": True})
    assert started["time_limit_seconds"] == 300
    recovery = {"snapshot_name": "Edited Pixels", "backup_manifest_path": "/approved/asset.manifest.json", "affected_materials": ["Material"]}
    assert contract.validate_request(contract.RECOVERY_PREVIEW, recovery) == recovery
    restored = contract.validate_request(contract.RESTORE_START, {**recovery, "expected_recovery_fingerprint": "b" * 64,
        "confirm_restore_previous_packed_bytes": True, "confirm_restore_original_current_pixels": True, "time_limit_seconds": 1.5})
    assert restored["time_limit_seconds"] == 1.5


@pytest.mark.parametrize("key,value", [
    ("image_name", ""), ("image_name", "  "), ("image_name", "é" * 32), ("image_name", "\ud800"),
    ("snapshot_name", "line\nbreak"), ("affected_materials", []), ("affected_materials", ["A", "A"]),
    ("affected_materials", ["A", "B", "C"]), ("affected_materials", ("A",)),
    ("backup_prefix", "../escape"), ("backup_prefix", "é"), ("backup_prefix", "a" * 49),
    ("backup_directory", "\x00bad"), ("backup_directory", "é" * 2049),
    ("backup_directory", "relative/backups"), ("backup_directory", "//server/backups"),
    ("backup_directory", "/approved/../outside"),
    ("retain_event_journal", 1), ("unrecognized", True),
])
def test_pack_preview_refuses_unbounded_or_ambiguous_scope(contract, key, value):
    with pytest.raises(contract.BridgeError) as failure:
        contract.validate_request(contract.PACK_PREVIEW, {**pack_request(), key: value})
    assert failure.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_start_never_coerces_explicit_confirmation(contract, value):
    with pytest.raises(contract.BridgeError, match="confirmation"):
        contract.validate_request(contract.PACK_START, {**pack_request(), "expected_target_fingerprint": "a" * 64,
            "confirm_replace_packed_bytes": value, "confirm_discard_current_buffer": True})


@pytest.mark.parametrize("value", [True, 0, 301, pytest.param(10**5000, id="oversized-integer"), float("inf"), float("nan"), "10"])
def test_start_deadline_has_original_finite_bounds(contract, value):
    with pytest.raises(contract.BridgeError, match="time_limit_seconds"):
        contract.validate_request(contract.PACK_START, {**pack_request(), "expected_target_fingerprint": "a" * 64,
            "confirm_replace_packed_bytes": True, "confirm_discard_current_buffer": True, "time_limit_seconds": value})


def test_strict_receipt_preserves_plain_facts_without_granting_authority(contract):
    facts = {**receipt(), "image_name": "Original", "snapshot_name": "Edited Pixels", "record_uuid": "1" * 32,
             "runtime_nonce": "2" * 32, "owned_write_attempts": 0, "previous_packed_sha256": "a" * 64}
    saved = contract.validate_receipt(facts)
    assert saved == facts and saved is not facts and saved["recovery_authorized"] is False
    facts["image_name"] = "Changed"
    assert saved["image_name"] == "Original"


@pytest.mark.parametrize("key,value", [
    ("kind", "legacy"), ("schema_version", True), ("method", "unknown"), ("mode", "PACKED_RECONSTRUCTION"),
    ("stage", "RESTORED_COMPLETE"), ("identity_mode", "UUID_ONLY"), ("state_known", 1),
    ("verification_required", False), ("recovery_authorized", True), ("project_saved", True),
    ("source_file_read", True), ("automatic_inverse_attempted", True), ("unexpected", {"nested": True}),
    ("image_name", "é" * 32), ("record_uuid", "A" * 32), ("same_session_original_pointer", "f" * 17),
    ("same_session_original_uid", "1" * 21), ("owned_write_attempts", True), ("owned_write_attempts", 9),
    ("packed_bytes", 269_484_033), ("expected_target_fingerprint", "A" * 64),
])
def test_recognized_malformed_receipt_raises_never_becomes_empty_success(contract, key, value):
    with pytest.raises(contract.BridgeError) as failure:
        contract.validate_receipt({**receipt(), key: value})
    assert failure.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("key", ["kind", "schema_version", "method", "mode", "profile", "stage", "identity_mode",
    "external_write_attempted", "helper_record_write_attempted", "image_write_attempted", "state_known",
    "possible_mutation", "verification_required", "recovery_authorized", "project_saved", "source_file_read", "automatic_inverse_attempted"])
def test_each_required_receipt_field_is_required(contract, key):
    facts = receipt()
    del facts[key]
    with pytest.raises(contract.BridgeError):
        contract.validate_receipt(facts)


def test_unknown_observation_retains_attempts_but_never_a_current_hash(contract):
    facts = {**receipt(), "stage": "UNKNOWN", "state_known": False, "external_write_attempted": True,
             "possible_mutation": True, "expected_prefix_sha256": "a" * 64,
             "observed_prefix": None, "observed_prefix_sha256": None}
    assert contract.validate_receipt(facts) == facts
    for change in ({"state_known": True}, {"observed_prefix_sha256": "a" * 64}, {"observed_prefix": "PREPARED"}):
        with pytest.raises(contract.BridgeError):
            contract.validate_receipt({**facts, **change})


@pytest.mark.parametrize("change", [{"observed_prefix": "PREPARED"}, {"expected_prefix_sha256": "a" * 64},
    {"observed_prefix": "PREPARED", "expected_prefix_sha256": "a" * 64, "observed_prefix_sha256": "b" * 64}])
def test_optional_known_observation_is_all_or_matching_not_partial(contract, change):
    with pytest.raises(contract.BridgeError):
        contract.validate_receipt({**receipt(), **change})
    known = {**receipt(), "observed_prefix": "PREPARED", "expected_prefix_sha256": "a" * 64, "observed_prefix_sha256": "a" * 64}
    assert contract.validate_receipt(known) == known


def test_prefix_progress_requires_durable_backups_before_native_writes(contract):
    current = receipt()
    current = contract.prefix_receipt(current, "BACKUPS_PARTIAL", external_write_attempted=True, possible_mutation=True, owned_write_attempts=1)
    current = contract.prefix_receipt(current, "BACKUPS_DURABLE", durable_backups_verified=True)
    current = contract.prefix_receipt(current, "HELPER_RECORD_ATTEMPT", helper_record_write_attempted=True, owned_write_attempts=2)
    current = contract.prefix_receipt(current, "HELPER_RECORD_VERIFIED")
    current = contract.prefix_receipt(current, "PACK_ATTEMPT", image_write_attempted=True, owned_write_attempts=3)
    current = contract.prefix_receipt(current, "PACKED_BYTES_VERIFIED", packed_bytes_verified=True)
    current = contract.prefix_receipt(current, "BUFFER_DISCARD_ATTEMPT", owned_write_attempts=4)
    current = contract.prefix_receipt(current, "PACKED_BUFFER_DISCARDED")
    current = contract.prefix_receipt(current, "FORWARD_COMPLETE", complete_pixels_verified=True)
    assert current["owned_write_attempts"] == 4 and all(current[key] for key in contract.ATTEMPT_FLAGS)
    with pytest.raises(contract.BridgeError):
        contract.prefix_receipt(current, "PREPARED")
    with pytest.raises(contract.BridgeError):
        contract.prefix_receipt(current, "FORWARD_COMPLETE", owned_write_attempts=3)


@pytest.mark.parametrize("change", [
    {"helper_record_write_attempted": True, "possible_mutation": True},
    {"image_write_attempted": True, "possible_mutation": True},
    {"external_write_attempted": True},
    {"stage": "BACKUPS_DURABLE", "external_write_attempted": True, "possible_mutation": True},
    {"stage": "FORWARD_COMPLETE"}, {"identity_mode": "UNAVAILABLE"},
])
def test_impossible_write_and_verified_prefix_combinations_refuse(contract, change):
    with pytest.raises(contract.BridgeError):
        contract.validate_receipt({**receipt(), **change})


def test_restore_noop_is_distinct_from_a_previous_completed_restoration(contract):
    noop = {**receipt(restore=True), "stage": "ALREADY_AT_BACKED_UP_STATE", "complete_pixels_verified": True,
            "durable_backups_verified": True, "packed_bytes_verified": True}
    assert contract.validate_receipt(noop) == noop
    with pytest.raises(contract.BridgeError):
        contract.validate_receipt({**noop, "image_write_attempted": True, "possible_mutation": True})
    restore = contract.prefix_receipt(receipt(restore=True), "RESTORE_PREVIOUS_PACK_ATTEMPT", image_write_attempted=True,
        possible_mutation=True, durable_backups_verified=True, previous_decoded_pixels_sha256="a" * 64, owned_write_attempts=1)
    restore = contract.prefix_receipt(restore, "RESTORE_PREVIOUS_PACK_VERIFIED", packed_bytes_verified=True)
    restore = contract.prefix_receipt(restore, "RESTORE_EDITED_PIXELS_ATTEMPT", owned_write_attempts=2)
    restore = contract.prefix_receipt(restore, "RESTORED_COMPLETE", complete_pixels_verified=True)
    assert restore["stage"] == "RESTORED_COMPLETE" and not restore["helper_record_write_attempted"]


def test_unknown_prefix_cannot_resume_or_clear_attempt_facts(contract):
    unknown = {**receipt(), "stage": "UNKNOWN", "state_known": False, "external_write_attempted": True, "possible_mutation": True}
    with pytest.raises(contract.BridgeError):
        contract.prefix_receipt(unknown, "PREPARED", external_write_attempted=False)
    with pytest.raises(contract.BridgeError):
        contract.prefix_receipt(unknown, "UNKNOWN", external_write_attempted=False)


@pytest.mark.parametrize("field,original,replacement", [("expected_target_fingerprint", "a" * 64, "b" * 64),
    ("previous_packed_sha256", "a" * 64, "b" * 64), ("current_pixels_sha256_float32_le", "a" * 64, "b" * 64),
    ("previous_decoded_pixels_sha256", "a" * 64, "b" * 64), ("same_session_original_pointer", "abc", "def"),
    ("same_session_original_uid", "1", "2"), ("manifest_sha256", "a" * 64, "b" * 64),
    ("consumer_graph_sha256", "a" * 64, "b" * 64)])
def test_prefix_never_rebases_the_original_target_or_backup_content(contract, field, original, replacement):
    with pytest.raises(contract.BridgeError, match="original scope identity"):
        contract.prefix_receipt({**receipt(), field: original}, "PREPARED", **{field: replacement})


@pytest.mark.parametrize("field", ["manifest_sha256", "consumer_graph_sha256"])
def test_prefix_advance_cannot_replace_present_manifest_or_protected_consumer_digest(contract, field):
    before = {**receipt(), field: "a" * 64}
    advanced = {**prefix_facts("BACKUPS_PARTIAL"), field: "b" * 64}
    assert contract.validate_receipt(advanced) == advanced  # The payload itself is otherwise valid.
    with pytest.raises(contract.BridgeError, match="original scope identity"):
        contract.prefix_receipt(before, "BACKUPS_PARTIAL", **{key: value for key, value in advanced.items() if key != "stage"})
    assert before[field] == "a" * 64
    same = contract.prefix_receipt(before, "PREPARED", **{field: "a" * 64})
    assert same == before and same is not before


@pytest.mark.parametrize("restore,before_stage,after_stage", [
    (False, "PREPARED", "BACKUPS_DURABLE"),
    (False, "BACKUPS_PARTIAL", "HELPER_RECORD_ATTEMPT"),
    (False, "BACKUPS_DURABLE", "HELPER_RECORD_VERIFIED"),
    (False, "HELPER_RECORD_ATTEMPT", "PACK_ATTEMPT"),
    (False, "HELPER_RECORD_VERIFIED", "PACKED_BYTES_VERIFIED"),
    (False, "PACK_ATTEMPT", "BUFFER_DISCARD_ATTEMPT"),
    (False, "PACKED_BYTES_VERIFIED", "PACKED_BUFFER_DISCARDED"),
    (False, "BUFFER_DISCARD_ATTEMPT", "FORWARD_COMPLETE"),
    (False, "PREPARED", "FORWARD_COMPLETE"),
    (True, "PREPARED", "RESTORE_PREVIOUS_PACK_VERIFIED"),
    (True, "RESTORE_PREVIOUS_PACK_ATTEMPT", "RESTORE_EDITED_PIXELS_ATTEMPT"),
    (True, "RESTORE_PREVIOUS_PACK_VERIFIED", "RESTORED_COMPLETE"),
    (True, "PREPARED", "RESTORED_COMPLETE"),
    (True, "RESTORED_COMPLETE", "ALREADY_AT_BACKED_UP_STATE"),
    (True, "ALREADY_AT_BACKED_UP_STATE", "RESTORE_PREVIOUS_PACK_ATTEMPT"),
    (False, "UNKNOWN", "PREPARED"),
    (True, "UNKNOWN", "PREPARED"),
])
def test_valid_later_receipt_cannot_skip_attempt_or_verification_boundaries(contract, restore, before_stage, after_stage):
    before = prefix_facts(before_stage, restore=restore)
    after = prefix_facts(after_stage, restore=restore)
    # Refusal must be the ordering gate, not malformed receipt or false flags.
    assert contract.validate_receipt(before) == before
    assert contract.validate_receipt(after) == after
    with pytest.raises(contract.BridgeError, match="prefix transitions"):
        contract.prefix_receipt(before, after_stage, **{key: value for key, value in after.items() if key != "stage"})


@pytest.mark.parametrize("restore,stage", [
    *[(False, stage) for stage in ("PREPARED", "BACKUPS_PARTIAL", "BACKUPS_DURABLE", "HELPER_RECORD_ATTEMPT",
                                  "HELPER_RECORD_VERIFIED", "PACK_ATTEMPT", "PACKED_BYTES_VERIFIED",
                                  "BUFFER_DISCARD_ATTEMPT", "PACKED_BUFFER_DISCARDED", "FORWARD_COMPLETE", "UNKNOWN")],
    *[(True, stage) for stage in ("PREPARED", "RESTORE_PREVIOUS_PACK_ATTEMPT", "RESTORE_PREVIOUS_PACK_VERIFIED",
                                 "RESTORE_EDITED_PIXELS_ATTEMPT", "RESTORED_COMPLETE", "ALREADY_AT_BACKED_UP_STATE", "UNKNOWN")],
])
def test_every_prefix_can_remain_or_become_unknown_without_clearing_attempts(contract, restore, stage):
    before = prefix_facts(stage, restore=restore)
    assert contract.prefix_receipt(before, stage) == before
    unknown = contract.unknown_observation(before)
    assert contract.prefix_receipt(before, "UNKNOWN", **{key: value for key, value in unknown.items() if key != "stage"}) == unknown


def test_prepared_recovery_explicit_noop_is_the_only_shortcut(contract):
    before = receipt(restore=True)
    noop = prefix_facts("ALREADY_AT_BACKED_UP_STATE", restore=True)
    result = contract.prefix_receipt(before, "ALREADY_AT_BACKED_UP_STATE",
                                    **{key: value for key, value in noop.items() if key != "stage"})
    assert result == noop and not result["image_write_attempted"] and not result["helper_record_write_attempted"]


def test_unknown_observation_keeps_last_measured_facts_and_never_relabels_them_current(contract):
    complete = {**receipt(), "stage": "FORWARD_COMPLETE", "external_write_attempted": True,
                "helper_record_write_attempted": True, "image_write_attempted": True,
                "possible_mutation": True, "durable_backups_verified": True, "packed_bytes_verified": True,
                "complete_pixels_verified": True, "owned_write_attempts": 4, "manifest_sha256": "b" * 64,
                "expected_prefix_sha256": "a" * 64, "observed_prefix_sha256": "a" * 64,
                "observed_prefix": "FORWARD_COMPLETE", "previous_packed_sha256": "c" * 64}
    unknown = contract.unknown_observation(complete)
    assert unknown is not complete and complete["stage"] == "FORWARD_COMPLETE"
    assert unknown == {**complete, "stage": "UNKNOWN", "state_known": False,
                       "observed_prefix": None, "observed_prefix_sha256": None}
    assert unknown["expected_prefix_sha256"] == "a" * 64
    assert unknown["previous_packed_sha256"] == "c" * 64
    assert unknown["recovery_authorized"] is False
    assert contract.unknown_observation(receipt()) == {**receipt(), "stage": "UNKNOWN", "state_known": False,
                                                       "observed_prefix": None, "observed_prefix_sha256": None}


def test_manifest_is_canonical_reopens_complete_and_copies_nested_data(contract):
    original = manifest()
    encoded = contract.canonical_manifest(original)
    assert encoded == json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert contract.manifest_sha256(original) == hashlib.sha256(encoded).hexdigest()
    reopened = contract.parse_manifest(encoded)
    assert reopened == original and reopened is not original
    original["backups"]["current"]["bytes"] = 1
    original["native_identity_rows"][0]["name"] = "Changed"
    assert reopened["backups"]["current"]["bytes"] == 500
    assert reopened["native_identity_rows"][0]["name"] == "Original"


@pytest.mark.parametrize("kind", ["unknown_topkey", "bad_schema", "oversized_payload", "wrong_old_hash", "traversal_filename",
    "roles", "bool_dimension", "extra_id", "missing_original", "foreign_pointer", "material_omitted", "portable_token", "portable_mismatch"])
def test_manifest_refuses_misbinding_and_profile_widening(contract, kind):
    value = manifest()
    if kind == "unknown_topkey":
        value["arbitrary"] = []
    elif kind == "bad_schema":
        value["schema_version"] = True
    elif kind == "oversized_payload":
        value["backups"]["current"]["bytes"] = 269_484_033
    elif kind == "wrong_old_hash":
        value["backups"]["oldpacked"]["sha256"] = "0" * 64
    elif kind == "traversal_filename":
        value["backups"]["current"]["filename"] = "../asset_01.current.exr"
    elif kind == "roles":
        value["roles"]["colorspace"] = "sRGB"
    elif kind == "bool_dimension":
        value["width"] = True
    elif kind == "extra_id":
        value["native_identity_rows"] *= 6
    elif kind == "missing_original":
        value["native_identity_rows"].pop(0)
        value["portable_identity_rows"].pop(0)
    elif kind == "foreign_pointer":
        value["original_identity"]["pointer"] = "999"
    elif kind == "material_omitted":
        value["affected_materials"] = ["Foreign Material"]
    elif kind == "portable_token":
        value["portable_identity_rows"][0]["pointer"] = "abc"
    else:
        value["portable_identity_rows"][0]["content_sha256"] = "0" * 64
    with pytest.raises(contract.BridgeError):
        contract.validate_manifest(value)


@pytest.mark.parametrize("metadata", [{"arbitrary": {"nested": True}}, {"pixels": [0] * 100}, {"is_dirty": 1},
    {"channels": True}, {"channels": 3}, {"snapshot_schema_version": 2}, {"record_sha256": "bad"},
    {"filepath": "é" * 2049}, {"filepath_raw": "line\nbreak"}, {"colorspace": "sRGB"}])
def test_manifest_metadata_is_a_literal_whitelist_not_arbitrary_json(contract, metadata):
    with pytest.raises(contract.BridgeError):
        contract.canonical_manifest({**manifest(), "image_metadata": metadata})


def test_manifest_metadata_missing_fields_are_not_invented(contract):
    value = {**manifest(), "image_metadata": {"filepath": "//stored.exr", "is_dirty": True, "channels": 4},
             "snapshot_metadata": {"use_fake_user": True, "record_present": False, "snapshot_schema_version": 1}}
    assert contract.parse_manifest(contract.canonical_manifest(value)) == value
    assert "has_data" not in contract.validate_manifest(value)["image_metadata"]


@pytest.mark.parametrize("payload", [b"{}", b"[]", b"\xff", b'{"kind":1,"kind":2}', b'{"kind":NaN}', b"{" * 65536,
    b" " * 65537])
def test_manifest_parser_refuses_malformed_duplicate_nonfinite_and_over_budget_bytes(contract, payload):
    with pytest.raises(contract.BridgeError):
        contract.parse_manifest(payload)


def test_noncanonical_manifest_bytes_do_not_match_a_canonical_backup(contract):
    encoded = contract.canonical_manifest(manifest())
    with pytest.raises(contract.BridgeError, match="canonical"):
        contract.parse_manifest(encoded + b"\n")


def test_plain_contract_does_not_invoke_custom_container_or_scalar_hooks(contract):
    calls = []

    class Foreign(dict):
        def __iter__(self):
            calls.append("iteration")
            raise AssertionError

    class Scalar:
        def __eq__(self, _other):
            calls.append("equality")
            raise AssertionError

    for value in (Foreign(receipt()), {**receipt(), "kind": Scalar()}):
        with pytest.raises(contract.BridgeError):
            contract.validate_receipt(value)
    assert calls == []


@pytest.mark.parametrize("width,height,memory,disk", [(1, 1, 512 * 1024**2, 64 * 1024**2),
    (1024, 1024, 512 * 1024**2, 64 * 1024**2), (1025, 1024, 8 * 1024**3, 2 * 1024**3),
    (4096, 4096, 8 * 1024**3, 2 * 1024**3)])
def test_resource_thresholds_are_measured_point_in_time_facts(contract, width, height, memory, disk):
    facts = contract.validate_resource_facts(width, height, memory, disk)
    assert facts["admitted"] is True and facts["resources_reserved"] is False
    assert facts["required_available_memory_bytes"] == memory
    assert facts["required_available_disk_bytes"] == disk
    for m, d in ((memory - 1, disk), (memory, disk - 1)):
        with pytest.raises(contract.BridgeError) as failure:
            contract.validate_resource_facts(width, height, m, d)
        refused = failure.value.context["resource_facts"]
        assert refused["available_memory_bytes"] == m and refused["available_disk_bytes"] == d
        assert refused["admitted"] is False and refused["resources_reserved"] is False


@pytest.mark.parametrize("width,height,memory,disk", [(True, 2, 1, 1), (0, 2, 1, 1), (4097, 1, 1, 1),
    (2, 2, True, 1), (2, 2, -1, 1), (2, 2, 1, float("inf"))])
def test_resource_facts_do_not_coerce_invalid_measurements(contract, width, height, memory, disk):
    with pytest.raises(contract.BridgeError) as failure:
        contract.validate_resource_facts(width, height, memory, disk)
    assert failure.value.code == "INVALID_ARGUMENT"


def test_recovery_complete_state_classification_is_not_a_grant(contract):
    base = {"target_loaded": True, "snapshot_loaded": True, "owner_verified": True,
            "state_matches_forward": True, "state_matches_backup": False}
    assert contract.recovery_classification(**base) == "FORWARD_COMPLETE"
    assert contract.recovery_classification(**{**base, "state_matches_forward": False, "state_matches_backup": True}) == "ALREADY_AT_BACKED_UP_STATE"
    for change, reason in (({"target_loaded": False}, "TARGET_BUFFER_UNLOADED"),
            ({"snapshot_loaded": False}, "TARGET_BUFFER_UNLOADED"), ({"owner_verified": False}, "NATIVE_OWNER_UNVERIFIED"),
            ({"state_matches_backup": True}, "AMBIGUOUS_COMPLETE_STATE"), ({"state_matches_forward": False}, "PARTIAL_OR_UNKNOWN_STATE")):
        with pytest.raises(contract.BridgeError) as failure:
            contract.recovery_classification(**{**base, **change})
        assert failure.value.context == {"reason": reason, "inspection_only": True, "recovery_authorized": False}
    with pytest.raises(contract.BridgeError) as failure:
        contract.recovery_classification(**{**base, "owner_verified": 1})
    assert failure.value.code == "INVALID_ARGUMENT"


def test_manifest_identity_modes_do_not_assert_historical_pointer_equality(contract):
    value = manifest()
    changed = copy.deepcopy(value)
    changed["original_identity"]["pointer"] = "789"
    changed["original_identity"]["session_uid"] = "99"
    changed["native_identity_rows"][0].update(pointer="789", session_uid="99")
    changed["native_graph_sha256"] = "6" * 64
    assert contract.canonical_manifest(changed) != contract.canonical_manifest(value)
    assert changed["portable_identity_rows"] == value["portable_identity_rows"]
    assert changed["portable_graph_sha256"] == value["portable_graph_sha256"]
