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


def native_save_envelope():
    return {"mode": "SAVE_AS", "policy_version": "stock_native_save_effects_v1",
            "native_save_invoked": True, "native_save_completed": True,
            "possible_native_effects": True, "native_external_effects_authorized": True,
            "native_effect_inventory_complete": False, "source_filepath_before": None,
            "source_filepath_after": "/approved/project.blend", "declared_source_verified": True,
            "fresh_process_reopen_verified": False, "worker_reaped": True,
            "reader_cleanup": "complete", "retained_reader_path": None, "cleanup_outcome_unknown": False}


def test_native_save_envelope_is_bounded_copied_and_separate_from_known_artifacts(history_env):
    native = native_save_envelope()
    artifacts = [{"filepath": f"/approved/project.blend{index}", "file_sha256": "a"*64,
                  "file_bytes": 100} for index in range(8)]
    effects = {"native_save": native, "artifacts": artifacts, "publication_attempted": True}
    response = invoke(history_env, lambda *_: {"external_effects": effects})
    assert response.ok
    retained = history_env.state.history(1)[0]["external_effects"]
    assert retained["native_save"] == {**native, "evidence_incomplete": False}
    assert len(retained["artifacts"]) == 4 and retained["artifacts_truncated"] is True
    assert retained["native_save"]["native_effect_inventory_complete"] is False
    native["source_filepath_after"] = "caller changed"
    assert retained["native_save"]["source_filepath_after"] == "/approved/project.blend"
    history_env.grants["INSPECT_SCENE"] = False
    redacted = history_env.core.checkpoint_list(history_env.executor.context, {"limit": 1})["operation_history"][0]
    assert redacted["external_effects"] is None and "/approved/project.blend" not in str(redacted)


@pytest.mark.parametrize("field,value", [("mode", "NATIVE_PYTHON"), ("policy_version", "unknown"),
    ("native_save_invoked", 1), ("possible_native_effects", "true"),
    ("native_effect_inventory_complete", True), ("source_filepath_before", "x"*4097),
    ("source_filepath_after", "line\nbreak"), ("source_filepath_after", "\ud800"),
    ("fresh_process_reopen_verified", {}), ("worker_reaped", 1),
    ("cleanup_outcome_unknown", "true"), ("reader_cleanup", None), ("reader_cleanup", ""),
    ("reader_cleanup", "x"*65), ("reader_cleanup", "\u00e9"*33),
    ("reader_cleanup", "line\nbreak"), ("reader_cleanup", "\ud800"),
    ("retained_reader_path", False), ("retained_reader_path", "x"*4097),
    ("retained_reader_path", "\u00e9"*2049), ("retained_reader_path", "line\nbreak"),
    ("retained_reader_path", "\ud800")])
def test_invalid_native_save_evidence_never_becomes_complete_proof(history_env, field, value):
    native = {**native_save_envelope(), field: value}
    result = history_env.state_mod.bounded_external_effects({"native_save": native})["native_save"]
    assert result["evidence_incomplete"] is True and field not in result


def test_native_save_evidence_does_not_traverse_unknown_or_cyclic_callback_values(history_env):
    native = native_save_envelope()
    native["unlisted_catalog_paths"] = native
    native["unknown_payload"] = ["x"]*10000
    result = history_env.state_mod.bounded_external_effects({"native_save": native})
    assert result == {"native_save": {**native_save_envelope(), "evidence_incomplete": False}}
    assert "catalog_paths" not in str(result)


def test_failed_native_save_retains_possible_effects_even_without_a_known_file(history_env):
    native = {**native_save_envelope(), "native_save_completed": False,
              "declared_source_verified": False}

    def fail(*_):
        raise history_env.errors.BridgeError("PERMISSION_DENIED", "Revoked after native entry",
            {"external_effects": {"publication_attempted": True, "native_save": native}})

    response = invoke(history_env, fail)
    assert not response.ok and response.error["context"]["possible_mutation"] is True
    retained = history_env.state.history(1)[0]["external_effects"]
    assert retained["native_save"]["possible_native_effects"] and "artifacts" not in retained


def test_native_save_reader_retention_survives_failure_and_repeated_bounding(history_env):
    native = {**native_save_envelope(), "worker_reaped": False,
              "reader_cleanup": "retained_process_unknown", "retained_reader_path": "/owned/reader",
              "cleanup_outcome_unknown": True}
    effects = {"native_save": native, "publication_attempted": True,
               "retained_staging_path": "/approved/.native-save-stage.blend",
               "artifacts": [{"filepath": f"/approved/output{index}.blend", "file_sha256": "a"*64,
                              "file_bytes": 100} for index in range(6)]}
    first = history_env.state_mod.bounded_external_effects(effects)
    assert history_env.state_mod.bounded_external_effects(first) == first
    assert first["native_save"] == {**native, "evidence_incomplete": False}
    assert len(first["artifacts"]) == 4 and first["artifacts_truncated"] is True

    def fail(*_):
        raise history_env.errors.BridgeError("PERMISSION_DENIED", "Reader cleanup authority lost",
            {"possible_mutation": False, "external_effects": first})

    response = invoke(history_env, fail)
    assert not response.ok and response.error["context"]["possible_mutation"] is True
    retained = history_env.state.history(1)[0]["external_effects"]
    assert retained == first
    native["retained_reader_path"] = "caller changed"
    assert retained["native_save"]["retained_reader_path"] == "/owned/reader"
    history_env.grants["INSPECT_SCENE"] = False
    redacted = history_env.core.checkpoint_list(history_env.executor.context, {"limit": 1})["operation_history"][0]
    assert redacted["external_effects"] is None and "/owned/reader" not in str(redacted)


def test_native_save_reader_fields_do_not_coerce_poison_or_traverse_receipts(history_env):
    class Poison:
        def __bool__(self):
            raise AssertionError("No coercion")

        def __str__(self):
            raise AssertionError("No stringification")

        def __iter__(self):
            raise AssertionError("No traversal")

    native = native_save_envelope()
    for key in ("worker_reaped", "reader_cleanup", "retained_reader_path", "cleanup_outcome_unknown"):
        native[key] = Poison()
    native["worker_receipt"] = {"recursive": native, "large": [Poison()]*10000}
    first = history_env.state_mod.bounded_external_effects({"native_save": native})
    result = first["native_save"]
    assert result["evidence_incomplete"] is True
    assert not {"worker_reaped", "reader_cleanup", "retained_reader_path", "cleanup_outcome_unknown",
                "worker_receipt"}.intersection(result)
    assert history_env.state_mod.bounded_external_effects(first) == first


def test_native_save_reader_cleanup_warnings_use_only_bounded_cached_facts(addon_package):
    ui = importlib.import_module(f"{addon_package}.ui")

    class Layout:
        def __init__(self):
            self.labels = []

        def label(self, *, text, icon=None):
            self.labels.append((text, icon))

    layout = Layout()
    ui._draw_native_save_effects(layout, {"native_save": {**native_save_envelope(),
        "worker_reaped": False, "retained_reader_path": "/owned/reader", "cleanup_outcome_unknown": True}})
    assert ("Owned reader files retained; inspect job details", "ERROR") in layout.labels
    assert ("Reader process exit not verified", "ERROR") in layout.labels
    assert ("Reader cleanup outcome unknown; reinspection required", "ERROR") in layout.labels
    assert all("/owned/reader" not in text for text, _ in layout.labels)


@pytest.mark.parametrize("method", ["weights.assign", "weights.normalize"])
def test_both_direct_methods_accept_exact_all_membership_caps(history_env, method):
    from test_domain_recovery_evidence import evidence

    facts = {
        **evidence(),
        "method": method,
        "owned_membership_attempts": 256,
        "owned_membership_verified": 256,
        "restoration_attempts": 256,
        "restored_memberships": 256,
    }
    assert history_env.state_mod.bounded_recovery_evidence(facts) == facts


@pytest.mark.parametrize("method", ["weights.assign", "weights.normalize"])
@pytest.mark.parametrize(
    "field,bad",
    [
        ("owned_membership_attempts", 257),
        ("owned_membership_verified", 257),
        ("restoration_attempts", 257),
        ("restored_memberships", 257),
        ("native_update_attempts", 1),
        ("native_update_verified", 1),
        ("stage", "UPDATE"),
    ],
)
def test_both_direct_methods_keep_all_strict_bounds(history_env, method, field, bad):
    from test_domain_recovery_evidence import evidence

    facts = {
        **evidence(),
        "method": method,
        "owned_membership_attempts": 256,
        "owned_membership_verified": 256,
        "restoration_attempts": 256,
        "restored_memberships": 256,
    }
    assert history_env.state_mod.bounded_recovery_evidence({**facts, field: bad}) is None


@pytest.mark.parametrize("method", ["weights.assign", "weights.normalize", "animation.curve_edit"])
@pytest.mark.parametrize("failed", [False, True])
def test_one_history_record_keeps_both_detached_receipts_and_redacts(history_env, method, failed):
    from copy import deepcopy

    from test_domain_recovery_evidence import curve_evidence, evidence

    env = history_env
    recovery = curve_evidence() if method == "animation.curve_edit" else {**evidence(), "method": method}
    native = native_save_envelope()
    effects = {
        "native_save": native,
        "publication_attempted": True,
        "artifacts": [
            {"filepath": f"/approved/project{index}.blend", "file_sha256": "a" * 64, "file_bytes": 1}
            for index in range(5)
        ],
        "artifacts_incomplete": True,
    }

    def handler(*_args):
        payload = {"external_effects": effects, "recovery_evidence": recovery}
        if failed:
            raise env.errors.BridgeError("OPERATION_FAILED", "Injected combined-record failure", payload)
        return payload

    env.registry.register(method, handler, modifies=True, automatic_checkpoint=False, batchable=False)
    response = env.executor.execute_request(env.protocol.Request(id="combined-state", method=method, params={}))
    assert response.ok is not failed
    retained = env.state.history(1)[0]
    assert retained["tool"] == method and retained["success"] is not failed
    assert retained["recovery_evidence"] == recovery
    assert retained["external_effects"]["native_save"] == {**native, "evidence_incomplete": False}
    assert len(retained["external_effects"]["artifacts"]) == 4
    assert retained["external_effects"]["artifacts_incomplete"] is True
    assert retained["external_effects"]["artifacts_truncated"] is True
    assert env.state_mod.bounded_external_effects(retained["external_effects"]) == retained["external_effects"]
    expected = deepcopy(retained)
    native["source_filepath_after"] = "caller changed"
    recovery["expected_sha256"] = "c" * 64
    effects["artifacts"][0]["filepath"] = "caller changed"
    assert env.state.history(1)[0] == expected
    env.grants["INSPECT_SCENE"] = False
    hidden = env.core.checkpoint_list(env.executor.context, {"limit": 1})["operation_history"][0]
    assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"] is True
    assert hidden["external_effects"] is None and hidden["external_effects_redacted"] is True
    assert "/approved/" not in str(hidden)
    assert env.state.history(1)[0] == expected
