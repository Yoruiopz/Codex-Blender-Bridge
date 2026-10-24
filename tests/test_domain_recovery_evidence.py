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


def invoke(env, handler):
    method = "weights.brush_stroke"
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
