from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def history_env(addon_package):
    def load(name):
        return importlib.import_module(f"{addon_package}.{name}")
    state_mod, registry_mod, executor_mod = load("state"), load("tool_registry"), load("executor")
    permissions_mod = load("permissions")
    state = state_mod.BridgeState(history_limit=3)
    registry = registry_mod.ToolRegistry()
    grants = {"INSPECT_SCENE": True}
    checkpoints = NS(list=lambda _limit: [], recovery_status=lambda **_: {})
    executor = executor_mod.MainThreadExecutor(command_queue=load("command_queue").CommandQueue(),
        registry=registry, state=state,
        permissions=permissions_mod.PermissionManager(lambda: grants), checkpoints=checkpoints)
    effects = {"filepath": "/approved/asset.glb", "file_published": True,
        "publication_attempted": True, "publication_outcome_unknown": False,
        "file_sha256": "a" * 64, "file_bytes": 1024, "published_bytes_verified": True,
        "staging_cleanup": "removed", "retained_staging_path": None,
        "native_undo_removes_external_file": False, "crash_durability_verified": False,
        "windows_directory_pin_acceptance": "NOT_ASSESSED"}
    return NS(state_mod=state_mod, state=state, registry=registry, executor=executor,
        protocol=load("protocol"), errors=load("errors"), core=load("tools.core"),
        grants=grants, effects=effects)


def invoke(env, handler):
    env.registry.register("asset.export", handler, modifies=True, automatic_checkpoint=False, batchable=False)
    return env.executor.execute_request(env.protocol.Request(id="export", method="asset.export", params={}))


def test_completed_export_retains_file_effects_without_native_undo_claim(history_env):
    env = history_env
    response = invoke(env, lambda *_: {"exported": True, "external_effects": env.effects,
                                      "source_and_context_preserved": True})
    assert response.ok
    assert not response.result["operation"]["undo_boundary_created"]
    record = env.state.history(1)[0]
    assert record["success"] and record["external_effects"] == env.effects
    assert record["external_effects"]["native_undo_removes_external_file"] is False
    env.effects["filepath"] = "mutated caller dictionary"
    assert env.state.history(1)[0]["external_effects"]["filepath"] == "/approved/asset.glb"


@pytest.mark.parametrize("code", ["OPERATION_FAILED", "TIMEOUT", "PERMISSION_DENIED"])
def test_failed_or_cancelled_export_retains_effects_and_requires_reinspection(history_env, code):
    env = history_env
    def fail(*_):
        raise env.errors.BridgeError(code, "Export interrupted", {"external_effects": env.effects,
            "source_and_context_preserved": True, "possible_mutation": False})
    response = invoke(env, fail)
    assert not response.ok and response.error["code"] == code
    assert response.error["context"]["possible_mutation"] is True
    assert response.error["context"]["verification_required"] is True
    assert response.error["context"]["source_and_context_preserved"] is True
    record = env.state.history(1)[0]
    assert not record["success"] and record["external_effects"] == env.effects


@pytest.mark.parametrize("field,value", [("file_published", True),
    ("publication_outcome_unknown", True), ("publication_attempted", True),
    ("render_result_replacement_possible", True),
    ("retained_staging_path", "/approved/.staging")])
def test_known_or_uncertain_external_effect_is_possible_mutation(history_env, field, value):
    env = history_env
    effects = {field: value}
    def fail(*_):
        raise env.errors.BridgeError("TIMEOUT", "interrupted", {"external_effects": effects,
            "source_and_context_preserved": True, "possible_mutation": False})
    response = invoke(env, fail)
    assert response.error["context"]["possible_mutation"] is True
    assert env.state.history(1)[0]["external_effects"] == effects


@pytest.mark.parametrize("value", [True, False, 1, "true", None])
def test_uncertain_render_result_is_strict_boolean_history_evidence(history_env, value):
    env = history_env
    supplied = {"render_result_replacement_possible": value, "render_result_replaced": None}
    facts = env.state_mod.bounded_external_effects(supplied)
    assert facts == ({"render_result_replacement_possible": value} if type(value) is bool else None)


def test_rejected_export_without_effects_does_not_acquire_mutation_claim(history_env):
    env = history_env
    def fail(*_):
        raise env.errors.BridgeError("PERMISSION_DENIED", "rejected", {"external_effects": {
            "file_published": False, "publication_attempted": False, "retained_staging_path": None},
            "possible_mutation": False})
    response = invoke(env, fail)
    assert response.error["context"]["possible_mutation"] is False
    assert env.state.history(1)[0]["external_effects"]["file_published"] is False


def test_inspection_denial_redacts_file_facts_without_erasing_local_audit(history_env):
    env = history_env
    invoke(env, lambda *_: {"external_effects": env.effects})
    env.grants["INSPECT_SCENE"] = False
    denied = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert denied["external_effects"] is None and denied["external_effects_redacted"] is True
    assert "/approved/asset.glb" not in str(denied) and "a" * 64 not in str(denied)
    assert env.state.history(1)[0]["external_effects"] == env.effects
    env.grants["INSPECT_SCENE"] = True
    allowed = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert allowed["external_effects"] == env.effects and "external_effects_redacted" not in allowed


def test_external_effects_allowlist_never_retains_nested_or_unknown_results(history_env):
    env = history_env
    effect = {**env.effects, "result": {"large": [1] * 1000}, "script": "secret", "nested": env.effects}
    record = env.state.record_operation(tool="fixture", description="proof", success=True,
        duration_ms=1., external_effects=effect)
    assert record.external_effects == env.effects


@pytest.mark.parametrize("value", [[], "proof", False, None])
def test_non_mapping_effects_do_not_enter_audit(history_env, value):
    assert history_env.state_mod.bounded_external_effects(value) is None


@pytest.mark.parametrize("field,value", [("filepath", "x" * 4097),
    ("retained_staging_path", "\ud800"), ("filepath", "line\nbreak"),
    ("filepath", "\u00e9" * 3000), ("file_sha256", "A" * 64), ("file_sha256", "x" * 10),
    ("file_bytes", True), ("file_bytes", -1), ("file_bytes", 2**53),
    ("file_published", 1), ("publication_attempted", "true"), ("staging_cleanup", "x" * 65)])
def test_invalid_or_unbounded_effect_fields_are_omitted(history_env, field, value):
    assert history_env.state_mod.bounded_external_effects({field: value}) is None


def test_external_effect_history_obeys_existing_retention_bound(history_env):
    env = history_env
    for index in range(10):
        env.state.record_operation(tool="fixture", description=str(index), success=True,
            duration_ms=0., external_effects=env.effects)
    assert len(env.state.history(100)) == 3


def test_managed_preview_pair_is_bounded_copied_and_inspection_redacted(history_env):
    env = history_env
    artifacts = [{"filepath": f"/managed/{name}.png", "file_sha256": name*64, "file_bytes": 512}
                 for name in ("a", "b")]
    effects = {"artifacts": artifacts, "native_undo_removes_external_file": False,
               "render_result_replaced": True}
    response = invoke(env, lambda *_: {"external_effects": effects})
    assert response.ok
    retained = env.state.history(1)[0]["external_effects"]
    assert retained["artifacts"] == artifacts
    assert retained["artifacts_truncated"] is False and retained["artifacts_incomplete"] is False
    artifacts[0]["filepath"] = "caller changed"
    assert retained["artifacts"][0]["filepath"] == "/managed/a.png"
    env.grants["INSPECT_SCENE"] = False
    denied = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert denied["external_effects"] is None and denied["external_effects_redacted"]
    assert "/managed/" not in str(denied) and "b"*64 not in str(denied)


@pytest.mark.parametrize("effects", [{"render_result_replaced": True},
    {"artifacts": [{"filepath": "/managed/preview.png", "file_sha256": None, "file_bytes": None}]}])
def test_preview_effects_survive_failure_and_force_possible_mutation(history_env, effects):
    env = history_env
    def fail(*_):
        raise env.errors.BridgeError("TIMEOUT", "preview interrupted",
                                     {"possible_mutation": False, "external_effects": effects})
    response = invoke(env, fail)
    assert not response.ok and response.error["context"]["possible_mutation"]
    assert response.error["context"]["verification_required"]
    assert env.state.history(1)[0]["external_effects"]


def test_artifact_list_does_not_traverse_nested_cyclic_or_unbounded_data(history_env):
    env = history_env
    item = {"filepath": "/managed/a.png", "file_sha256": "a"*64, "file_bytes": 1}
    item["nested"] = item
    parsed = env.state_mod.bounded_external_effects({"artifacts": [item]*10})
    assert len(parsed["artifacts"]) == env.state_mod.MAX_EXTERNAL_ARTIFACTS == 4
    assert parsed["artifacts_truncated"] is True
    assert parsed["artifacts_incomplete"] is False
    assert all(set(record) == {"filepath", "file_sha256", "file_bytes"} for record in parsed["artifacts"])


def test_invalid_artifacts_remain_incomplete_without_fabricated_hashes(history_env):
    env = history_env
    parsed = env.state_mod.bounded_external_effects({"artifacts": [None,
        {"filepath": "x"*4097, "file_sha256": "a"*64, "file_bytes": 1},
        {"filepath": "/managed/retained.png", "file_sha256": "bad", "file_bytes": True}]})
    assert parsed["artifacts_incomplete"] is True and parsed["artifacts_truncated"] is False
    assert parsed["artifacts"] == [{"filepath": "/managed/retained.png"}]
