from __future__ import annotations

import pytest
from test_external_effects_history import history_env  # noqa: F401


@pytest.fixture
def recovery_env(request):
    return request.getfixturevalue("history_env")


def evidence():
    return {"mode": "PACKED_RECONSTRUCTION", "image_name": "Edited Texture",
            "snapshot_name": "Retained Pixels", "snapshot_retained": True,
            "project_saved": False, "source_file_read": False,
            "packed_payload_replaced": True, "complete_pixels_verified": True,
            "pixels_sha256_float32_le": "a" * 64, "packed_sha256": "b" * 64,
            "previous_packed_sha256": None, "packed_bytes": 288 * 1024 * 1024}


def invoke(env, handler):
    method = "image.restore_snapshot_job_start"
    env.registry.register(method, handler, modifies=True, automatic_checkpoint=False, batchable=False)
    return env.executor.execute_request(env.protocol.Request(id="recovery", method=method, params={}))


def test_recovery_facts_remain_separate_copied_and_redacted(recovery_env):
    env = recovery_env
    facts = evidence()
    response = invoke(env, lambda *_: {"job_id": "job_" + "a" * 32,
                                      "accepted": True, "recovery_evidence": facts})
    assert response.ok
    record = env.state.history(1)[0]
    assert record["recovery_evidence"] == facts and record["external_effects"] is None
    assert "not yet completed" in record["description"]
    assert not response.result["operation"]["undo_boundary_created"]
    facts["snapshot_name"] = "changed caller dictionary"
    assert env.state.history(1)[0]["recovery_evidence"]["snapshot_name"] == "Retained Pixels"
    env.grants["INSPECT_SCENE"] = False
    hidden = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"]
    assert "Retained Pixels" not in str(hidden) and "a" * 64 not in str(hidden)
    env.grants["INSPECT_SCENE"] = True
    shown = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert shown["recovery_evidence"]["snapshot_retained"]
    assert shown["recovery_evidence"]["project_saved"] is False


@pytest.mark.parametrize("field", ["possible_mutation", "packed_payload_replaced"])
def test_interrupted_recovery_retains_measured_facts_and_requires_verification(recovery_env, field):
    env = recovery_env
    facts = {"mode": "LOADED_BUFFER", field: True, "snapshot_retained": True, "project_saved": False}

    def fail(*_):
        raise env.errors.BridgeError("TIMEOUT", "recovery interrupted",
                                     {"possible_mutation": False, "recovery_evidence": facts})

    response = invoke(env, fail)
    assert not response.ok
    assert response.error["context"]["possible_mutation"] and response.error["context"]["verification_required"]
    record = env.state.history(1)[0]
    assert not record["success"] and record["recovery_evidence"] == facts
    assert record["external_effects"] is None


def test_unknown_nested_recovery_data_never_enters_history(recovery_env):
    env = recovery_env
    facts = evidence()
    unbounded = {**facts, "pixels": [0] * 1000, "filepath": "/not-a-file-effect"}
    unbounded["nested"] = unbounded
    assert env.state_mod.bounded_recovery_evidence(unbounded) == facts


def test_unknown_terminal_observation_does_not_leak_name_through_description(recovery_env):
    env = recovery_env
    env.state.record_operation(tool="image.snapshot_job_start", description="Image job failed: Private Snapshot",
                               success=False, duration_ms=1., error_code="OPERATION_FAILED")
    env.grants["INSPECT_SCENE"] = False
    denied = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert "Private Snapshot" not in str(denied) and denied["description_redacted"]
    assert "Private Snapshot" in env.state.history(1)[0]["description"]


@pytest.mark.parametrize("field,value", [("mode", "invented"), ("image_name", "\ud800"),
    ("snapshot_name", "line\nbreak"), ("image_name", "é" * 32), ("retained_image_name", ""),
    ("pixels_sha256_float32_le", "A" * 64), ("packed_sha256", "bad"),
    ("packed_bytes", True), ("packed_bytes", -1), ("packed_bytes", 288 * 1024 * 1024 + 1),
    ("snapshot_retained", 1), ("project_saved", "false")])
def test_invalid_recovery_fields_do_not_become_evidence(recovery_env, field, value):
    assert recovery_env.state_mod.bounded_recovery_evidence({field: value}) is None
