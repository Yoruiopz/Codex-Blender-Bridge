"""Typed Scene recovery facts survive history without arbitrary payloads."""

from __future__ import annotations

import pytest
from test_external_effects_history import history_env  # noqa: F401


@pytest.fixture
def scene_history_env(request):
    return request.getfixturevalue("history_env")


def facts():
    return {"kind": "scene_mutation", "owned_write_attempts": 4, "restoration_verified": False,
            "retained_effects": [{"kind": "world_allocation", "name": "Retained World", "identity": (123, 456)},
                                 {"kind": "embedded_world_graph_allocation", "world": "Retained World",
                                  "automatic_identity_restoration_available": False}]}


def test_scene_recovery_is_copied_bounded_and_permission_redacted(scene_history_env):
    env = scene_history_env
    supplied = facts()
    supplied.update(filepath="/private/path", exception="raw private exception", nested={"secret": [object()]})
    expected = env.state_mod.bounded_recovery_evidence(supplied)
    assert expected["kind"] == "scene_mutation" and expected["owned_write_attempts"] == 4
    assert expected["restoration_verified"] is False
    assert expected["retained_effects"] == [
        {"kind": "world_allocation", "name": "Retained World"},
        {"kind": "embedded_world_graph_allocation", "world": "Retained World", "automatic_identity_restoration_available": False}]
    method = "world.configure"
    def fail(*_):
        raise env.errors.BridgeError("TIMEOUT", "stopped", {"possible_mutation": True, "recovery_evidence": supplied})
    env.registry.register(method, fail, modifies=True, automatic_checkpoint=False)
    result = env.executor.execute_request(env.protocol.Request(id="scene-history", method=method, params={}))
    assert not result.ok and result.error["code"] == "TIMEOUT"
    assert env.state.history(1)[0]["recovery_evidence"] == expected
    supplied["retained_effects"][0]["name"] = "new caller name"
    assert env.state.history(1)[0]["recovery_evidence"] == expected
    env.grants["INSPECT_SCENE"] = False
    hidden = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"]
    assert "Retained World" not in str(hidden) and "/private/path" not in str(hidden)
    env.grants["INSPECT_SCENE"] = True
    shown = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert shown["recovery_evidence"] == expected


@pytest.mark.parametrize("field,bad", [("owned_write_attempts", True), ("owned_write_attempts", -1),
    ("owned_write_attempts", 65), ("owned_write_attempts", 1.0), ("restoration_verified", 0),
    ("restoration_verified", "false"), ("retained_effects", {}), ("retained_effects", None)])
def test_invalid_core_scene_evidence_never_becomes_proof(scene_history_env, field, bad):
    supplied = facts()
    supplied[field] = bad
    assert scene_history_env.state_mod.bounded_recovery_evidence(supplied) is None


@pytest.mark.parametrize("name", ["", "x" * 64, "é" * 32, "line\nbreak", "\ud800"])
def test_invalid_native_names_are_omitted_and_mark_incomplete(scene_history_env, name):
    supplied = facts()
    supplied["retained_effects"] = [{"kind": "world_allocation", "name": name}]
    result = scene_history_env.state_mod.bounded_recovery_evidence(supplied)
    assert result["retained_effects"] == [{"kind": "world_allocation"}]
    assert result["retained_effects_incomplete"] and not result["retained_effects_truncated"]


@pytest.mark.parametrize("bad", [[], {}, None, True, "unknown_kind"])
def test_unknown_effect_kinds_are_dropped_without_traversal(scene_history_env, bad):
    supplied = facts()
    supplied["retained_effects"] = [{"kind": bad, "filepath": "/private"}]
    result = scene_history_env.state_mod.bounded_recovery_evidence(supplied)
    assert result["retained_effects"] == [] and result["retained_effects_incomplete"]


def test_truncation_and_incomplete_flags_survive_repeated_sanitization(scene_history_env):
    supplied = facts()
    supplied["retained_effects"] = [None] + [{"kind": "world_allocation", "name": f"World {index}"} for index in range(100)]
    result = scene_history_env.state_mod.bounded_recovery_evidence(supplied)
    assert len(result["retained_effects"]) == 15
    assert result["retained_effects_truncated"] and result["retained_effects_incomplete"]
    assert scene_history_env.state_mod.bounded_recovery_evidence(result) == result


def test_role_specific_flags_never_invent_identity_restoration(scene_history_env):
    supplied = facts()
    supplied["retained_effects"] = [{"kind": "world_allocation", "name": "A", "linked": True,
                                    "automatic_identity_restoration_available": True},
                                   {"kind": "embedded_world_graph_allocation", "world": "B",
                                    "automatic_identity_restoration_available": True},
                                   {"kind": "collection_allocation", "name": "C", "linked": 1}]
    result = scene_history_env.state_mod.bounded_recovery_evidence(supplied)
    assert result["retained_effects"] == [{"kind": "world_allocation", "name": "A"},
        {"kind": "embedded_world_graph_allocation", "world": "B"}, {"kind": "collection_allocation", "name": "C"}]
    assert result["retained_effects_incomplete"]


def test_scene_kind_does_not_admit_packed_image_or_file_payloads(scene_history_env):
    supplied = facts()
    supplied.update(mode="PACKED_RECONSTRUCTION", packed_bytes=42, snapshot_retained=True, file_published=True)
    result = scene_history_env.state_mod.bounded_recovery_evidence(supplied)
    assert not ({"mode", "packed_bytes", "snapshot_retained", "file_published"} & result.keys())
