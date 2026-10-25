from __future__ import annotations

import pytest
from test_external_effects_history import history_env  # noqa: F401


@pytest.fixture
def domain_env(request):
    return request.getfixturevalue("history_env")


def evidence():
    return {"kind": "weight_mutation", "object_name": "Character", "method": "weights.brush_stroke",
            "stage": "FAILED", "execution_started": True, "possible_mutation": True,
            "rollback_verified": False, "verification_required": True, "state_known": False,
            "retained_partial": True, "owned_membership_attempts": 2, "owned_membership_verified": 1,
            "restoration_attempts": 0, "restored_memberships": 0,
            "native_update_attempts": 0, "native_update_verified": 0,
            "restoration_refused": "AUTHORITY_LOST", "before_sha256": "a" * 64,
            "expected_sha256": "b" * 64, "observed_sha256": None}


def invoke(env, handler, method="weights.brush_stroke"):
    env.registry.register(method, handler, modifies=True, automatic_checkpoint=False)
    return env.executor.execute_request(env.protocol.Request(id="weight-history", method=method, params={}))


def test_failed_weight_write_retains_unknown_partial_state_and_redacts_on_inspection_denial(domain_env):
    env = domain_env
    facts = evidence()

    def interrupted(*_):
        raise env.errors.BridgeError("TIMEOUT", "Weight edit interrupted", {
            "affected_objects": ["Character"], "possible_mutation": False, "recovery_evidence": facts})

    response = invoke(env, interrupted)
    assert not response.ok and response.error["context"]["possible_mutation"] is True
    assert response.error["context"]["verification_required"] is True
    record = env.state.history(1)[0]
    assert record["recovery_evidence"] == facts and record["external_effects"] is None
    facts["object_name"] = "Changed caller buffer"
    facts["owned_membership_attempts"] = 4000
    assert env.state.history(1)[0]["recovery_evidence"]["object_name"] == "Character"
    assert env.state.history(1)[0]["recovery_evidence"]["owned_membership_attempts"] == 2
    env.grants["INSPECT_SCENE"] = False
    hidden = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"]
    assert hidden["description_redacted"]
    assert "object_name" not in str(hidden) and "a" * 64 not in str(hidden)


def test_successful_verified_weight_write_remains_separate_from_undo_and_saved_backup_claims(domain_env):
    env = domain_env
    facts = {**evidence(), "stage": "COMPLETE", "state_known": True, "retained_partial": False,
             "owned_membership_verified": 2, "observed_sha256": "b" * 64, "restoration_refused": None}
    response = invoke(env, lambda *_: {"changed": True, "affected_objects": ["Character"],
                                      "recovery_evidence": facts})
    assert response.ok and not response.result["operation"]["undo_boundary_created"]
    assert env.state.history(1)[0]["recovery_evidence"] == facts
    assert "project_saved" not in facts and "snapshot_retained" not in facts


def test_verified_local_weight_restoration_needs_original_digest_and_known_state(domain_env):
    env = domain_env
    facts = {**evidence(), "state_known": True, "retained_partial": False, "rollback_verified": True,
             "restoration_attempts": 1, "restored_memberships": 1,
             "observed_sha256": "a" * 64, "restoration_refused": None}
    assert env.state_mod.bounded_recovery_evidence(facts) == facts
    assert env.state_mod.bounded_recovery_evidence({**facts, "observed_sha256": "b" * 64}) is None
    assert env.state_mod.bounded_recovery_evidence({**facts, "retained_partial": True}) is None


def test_weight_history_ignores_unbounded_cyclic_payload_and_restoration_handles(domain_env):
    facts = evidence()
    supplied = {**facts, "weights": [0.] * 10000, "restore": object(), "project_saved": True}
    supplied["cycle"] = supplied
    assert domain_env.state_mod.bounded_recovery_evidence(supplied) == facts


@pytest.mark.parametrize("key,value", [
    ("method", "weights.delete_everything"), ("stage", "RESTORED"),
    ("object_name", ""), ("object_name", "bad\nname"), ("object_name", "é" * 32),
    ("object_name", "\ud800"), ("owned_membership_attempts", True),
    ("owned_membership_attempts", 4097), ("restored_memberships", -1),
    ("native_update_attempts", 7), ("native_update_verified", 1),
    ("owned_membership_verified", 3), ("restored_memberships", 1),
    ("possible_mutation", 1), ("rollback_verified", "false"),
    ("restoration_refused", "OVERRIDE_STOP"), ("before_sha256", "A" * 64),
    ("expected_sha256", None), ("observed_sha256", "b" * 64), ("state_known", True),
])
def test_invalid_or_contradictory_weight_facts_never_become_history_proof(domain_env, key, value):
    assert domain_env.state_mod.bounded_recovery_evidence({**evidence(), key: value}) is None


def uv_evidence(method="uv.coordinates_set"):
    return {"kind": "uv_mutation", "method": method, "object_name": "Work Mesh", "uv_layer": "UVMap",
            "object_session_uid": 101, "mesh_session_uid": 102, "object_pointer": 1001, "mesh_pointer": 1002,
            "stage": "FAILED", "execution_started": True, "possible_mutation": True,
            "rollback_verified": False, "verification_required": True, "state_known": False,
            "retained_partial": True, "owned_field_attempts": 2, "owned_field_verified": 1,
            "restoration_attempts": 0, "restored_fields": 0,
            "native_update_attempts": 0, "native_update_verified": 0,
            "restoration_refused": "SESSION_INVALIDATED", "before_sha256": "a" * 64,
            "expected_sha256": "b" * 64, "observed_sha256": None}


@pytest.mark.parametrize("method", ["uv.coordinates_set", "uv.transform", "uv.pin"])
def test_uv_interruption_history_retains_detached_flat_facts_and_inspection_redacts(domain_env, method):
    env, facts = domain_env, uv_evidence(method)

    def interrupted(*_):
        raise env.errors.BridgeError("TIMEOUT", "UV edit interrupted", {
            "affected_objects": [facts["object_name"]], "recovery_evidence": facts,
            "possible_mutation": False})

    response = invoke(env, interrupted, method)
    assert not response.ok and response.error["context"]["possible_mutation"] is True
    assert response.error["context"]["verification_required"] is True
    retained = env.state.history(1)[0]
    assert retained["recovery_evidence"] == facts and retained["external_effects"] is None
    facts["object_name"], facts["owned_field_attempts"] = "Later caller edit", 4096
    assert env.state.history(1)[0]["recovery_evidence"] == retained["recovery_evidence"]
    env.grants["INSPECT_SCENE"] = False
    hidden = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"]
    assert hidden["description_redacted"] and "object_name" not in str(hidden) and "a" * 64 not in str(hidden)
    assert "uv_layer" not in str(hidden) and hidden["affected_objects"] == ["Work Mesh"]


@pytest.mark.parametrize("method", ["uv.coordinates_set", "uv.transform", "uv.pin"])
def test_complete_uv_evidence_is_history_only_without_undo_or_backup_authority(domain_env, method):
    env = domain_env
    facts = {**uv_evidence(method), "stage": "COMPLETE", "state_known": True, "retained_partial": False,
             "owned_field_verified": 2, "native_update_attempts": 1, "native_update_verified": 1,
             "observed_sha256": "b" * 64, "restoration_refused": None}
    response = invoke(env, lambda *_: {"changed": True, "affected_objects": [facts["object_name"]],
                                     "recovery_evidence": facts}, method)
    assert response.ok and not response.result["operation"]["undo_boundary_created"]
    assert env.state.history(1)[0]["recovery_evidence"] == facts
    assert "project_saved" not in facts and "snapshot_retained" not in facts and len(facts) == 25


def test_uv_rollback_requires_known_original_digest_and_no_retained_partial_or_refusal(domain_env):
    facts = {**uv_evidence(), "rollback_verified": True, "state_known": True, "retained_partial": False,
             "restoration_attempts": 1, "restored_fields": 1, "native_update_attempts": 2,
             "native_update_verified": 2, "observed_sha256": "a" * 64, "restoration_refused": None}
    reduce = domain_env.state_mod.bounded_recovery_evidence
    assert reduce(facts) == facts
    for changed in ({"observed_sha256": "b" * 64}, {"retained_partial": True},
                    {"restoration_refused": "STATE_CHANGED"}, {"observed_sha256": None, "state_known": False}):
        assert reduce({**facts, **changed}) is None


def test_uv_history_ignores_unknown_arrays_cycles_and_native_handles(domain_env):
    facts = uv_evidence()
    supplied = {**facts, "UVs": [0.] * 10000, "native_mesh": object(), "restore": object(), "project_saved": True}
    supplied["cycle"] = supplied
    assert domain_env.state_mod.bounded_recovery_evidence(supplied) == facts


@pytest.mark.parametrize("field,value", [
    ("method", "uv.delete_all"), ("method", True), ("stage", "RESTORED"), ("stage", 1),
    ("object_name", ""), ("object_name", "bad\nname"), ("object_name", "é" * 32),
    ("uv_layer", "\ud800"), ("uv_layer", "x" * 64), ("uv_layer", False),
    ("object_session_uid", True), ("object_session_uid", 0), ("mesh_session_uid", -1),
    ("object_pointer", 2**64), ("mesh_pointer", 1.0),
    ("execution_started", 1), ("possible_mutation", "true"), ("rollback_verified", 0),
    ("verification_required", None), ("state_known", 1), ("retained_partial", []),
    ("owned_field_attempts", True), ("owned_field_attempts", 4097), ("owned_field_verified", 3),
    ("restoration_attempts", -1), ("restored_fields", 1), ("native_update_attempts", 3),
    ("native_update_verified", 1), ("before_sha256", "A" * 64), ("expected_sha256", None),
    ("observed_sha256", "b" * 64), ("state_known", True), ("restoration_refused", "AUTO_RESTORE"),
])
def test_invalid_or_contradictory_uv_facts_never_become_history_proof(domain_env, field, value):
    assert domain_env.state_mod.bounded_recovery_evidence({**uv_evidence(), field: value}) is None


@pytest.mark.parametrize("field", list(uv_evidence()))
def test_incomplete_uv_receipt_is_not_partial_history_proof(domain_env, field):
    supplied = uv_evidence()
    del supplied[field]
    assert domain_env.state_mod._bounded_uv_recovery(supplied) is None


def test_uv_reducer_accepts_exact_identity_and_counter_boundaries(domain_env):
    facts = {**uv_evidence(), "object_session_uid": 2**64 - 1, "mesh_session_uid": 1,
             "object_pointer": 2**64 - 1, "mesh_pointer": 1,
             "owned_field_attempts": 4096, "owned_field_verified": 4096,
             "restoration_attempts": 4096, "restored_fields": 4096,
             "native_update_attempts": 2, "native_update_verified": 2}
    assert domain_env.state_mod.bounded_recovery_evidence(facts) == facts


def test_uv_reducer_refuses_adapters_custom_keys_and_oversized_objects_before_reads(domain_env):
    from collections.abc import Mapping

    class Adapter(Mapping):
        def __getitem__(self, _key):
            pytest.fail("UV reducer must not read an arbitrary adapter")
        def __iter__(self):
            pytest.fail("UV reducer must not iterate an arbitrary adapter")
        def __len__(self):
            pytest.fail("UV reducer must not measure an arbitrary adapter")

    class Key:
        def __hash__(self):
            return hash("kind")
        def __eq__(self, _other):
            pytest.fail("UV reducer must not compare a custom key")

    reduce = domain_env.state_mod._bounded_uv_recovery
    assert reduce(Adapter()) is None
    supplied = {key: value for key, value in uv_evidence().items() if key != "kind"}
    supplied[Key()] = "unknown"
    assert reduce(supplied) is None
    assert reduce({**uv_evidence(), **{f"unknown_{i}": None for i in range(39)}}) == uv_evidence()
    assert reduce({**uv_evidence(), **{f"unknown_{i}": None for i in range(40)}}) is None


def curve_evidence():
    return {"kind": "curve_mutation", "method": "animation.curve_edit", "object_name": "Actor",
            "action_name": "Walk", "data_path": "location", "array_index": 0,
            "object_pointer": 1001, "object_session_uid": 101, "action_pointer": 1002,
            "action_session_uid": 102, "curve_pointer": 1003, "stage": "FAILED",
            "execution_started": True, "possible_mutation": True, "rollback_verified": False,
            "verification_required": True, "state_known": False, "retained_partial": True,
            "owned_field_attempts": 2, "owned_field_verified": 1,
            "restoration_attempts": 0, "restored_fields": 0, "native_update_attempts": 0,
            "native_update_verified": 0, "before_sha256": "a" * 64, "expected_sha256": "b" * 64,
            "observed_sha256": None, "restoration_refused": "AUTHORITY_LOST"}


def test_curve_partial_failure_history_is_detached_typed_and_redacted(domain_env):
    env, facts = domain_env, curve_evidence()
    def failed(*_):
        raise env.errors.BridgeError("TIMEOUT", "Curve edit interrupted", {
            "affected_objects": ["Actor"], "possible_mutation": False, "recovery_evidence": facts})
    response = invoke(env, failed, "animation.curve_edit")
    assert not response.ok and response.error["context"]["possible_mutation"] is True
    assert response.error["context"]["verification_required"] is True
    assert env.state.history(1)[0]["recovery_evidence"] == facts
    facts["action_name"] = "Later caller mutation"
    assert env.state.history(1)[0]["recovery_evidence"]["action_name"] == "Walk"
    env.grants["INSPECT_SCENE"] = False
    hidden = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"]
    assert hidden["description_redacted"] and hidden["affected_objects"] == ["Actor"]
    assert "action_name" not in str(hidden) and "a" * 64 not in str(hidden)


def test_curve_native_interruption_keeps_attempted_unknown_receipt_without_restore_authority(domain_env):
    env = domain_env
    facts = {**curve_evidence(), "owned_field_attempts": 1, "owned_field_verified": 0,
             "restoration_refused": "NATIVE_INTERRUPTED"}
    def interrupted(*_):
        raise env.errors.BridgeError("OPERATION_FAILED", "Native point call interrupted", {
            "affected_objects": ["Actor"], "recovery_evidence": facts, "verification_required": True})
    response = invoke(env, interrupted, "animation.curve_edit")
    assert not response.ok and response.error["context"]["possible_mutation"]
    retained = env.state.history(1)[0]["recovery_evidence"]
    assert retained == facts
    assert not retained["state_known"] and retained["observed_sha256"] is None
    assert not retained["rollback_verified"] and retained["restoration_attempts"] == 0


def test_curve_success_history_does_not_grant_undo_or_saved_backup(domain_env):
    env = domain_env
    facts = {**curve_evidence(), "stage": "COMPLETE", "state_known": True, "observed_sha256": "b" * 64,
             "retained_partial": False, "verification_required": False, "owned_field_verified": 2,
             "restoration_refused": None, "native_update_attempts": 1, "native_update_verified": 1}
    response = invoke(env, lambda *_: {"affected_objects": ["Actor"], "recovery_evidence": facts}, "animation.curve_edit")
    assert response.ok and not response.result["operation"]["undo_boundary_created"]
    assert env.state.history(1)[0]["recovery_evidence"] == facts
    assert "project_saved" not in facts and "snapshot_retained" not in facts


def test_curve_rollback_facts_require_known_original_and_no_retained_refusal(domain_env):
    facts = {**curve_evidence(), "state_known": True, "observed_sha256": "a" * 64,
             "rollback_verified": True, "retained_partial": False, "restoration_refused": None,
             "restoration_attempts": 1, "restored_fields": 1}
    reduce = domain_env.state_mod.bounded_recovery_evidence
    assert reduce(facts) == facts
    for changed in ({"observed_sha256": "b" * 64}, {"retained_partial": True},
                    {"restoration_refused": "STATE_CHANGED"}, {"state_known": False, "observed_sha256": None}):
        assert reduce({**facts, **changed}) is None


def test_curve_history_never_copies_intent_prefixes_arrays_or_native_handles(domain_env):
    facts = curve_evidence()
    supplied = {**facts, "prefixes": [0.] * 10000, "native_curve": object(), "restore": object(), "project_saved": True}
    supplied["cycle"] = supplied
    assert domain_env.state_mod.bounded_recovery_evidence(supplied) == facts


@pytest.mark.parametrize("field,value", [
    ("method", "animation.keyframe_insert"), ("stage", "RESTORED"), ("object_name", ""),
    ("action_name", "é" * 32), ("action_name", "bad\nname"), ("data_path", "\ud800"),
    ("data_path", "a" * 513), ("array_index", True), ("array_index", 16385),
    ("object_pointer", 0), ("action_session_uid", 2**64), ("curve_pointer", 1.0),
    ("execution_started", 1), ("possible_mutation", "false"), ("rollback_verified", None),
    ("owned_field_attempts", True), ("owned_field_attempts", 1538), ("owned_field_verified", 3),
    ("restoration_attempts", -1), ("restored_fields", 1), ("native_update_attempts", 3),
    ("native_update_verified", 1), ("before_sha256", "A" * 64), ("expected_sha256", None),
    ("observed_sha256", "b" * 64), ("state_known", True), ("restoration_refused", "FORCE"),
])
def test_invalid_curve_facts_never_become_recovery_history(domain_env, field, value):
    assert domain_env.state_mod.bounded_recovery_evidence({**curve_evidence(), field: value}) is None
