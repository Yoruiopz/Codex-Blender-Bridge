"""Cached target evidence stays historical and separate from artist completion."""

from __future__ import annotations

import ast
import importlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SCOPE = "authored_core_transform_channels"
OUTCOMES = [
    ("channels_match", "Matched at verification"),
    ("channels_differ", "Differences at verification"),
    ("target_missing", "Target missing at verification"),
    ("target_replaced", "Target replaced at verification"),
]


@pytest.fixture
def ui(addon_package):
    return importlib.import_module(f"{addon_package}.ui")


def receipt(status="channels_match", *, validity="recorded", step_id="step"):
    return {"step_id": step_id, "outcome": "completed", "history_state": "current_runtime_generation",
            "target_expectation": {"availability": "available"}, "protected_observation": None,
            "target_observation": {"status": status, "validity": validity, "scope": SCOPE,
                                   "comparison_complete": status in {"channels_match", "channels_differ"},
                                   "current_scene_verified": False, "user_goal_verified": False}}


@pytest.mark.parametrize("status,expected", OUTCOMES)
def test_recorded_target_labels_are_distinct_historical_facts(ui, status, expected):
    record = receipt(status)
    before = deepcopy(record)
    assert ui._target_channels_label(record) == expected
    assert record == before
    assert "verification" in expected and "goal" not in expected


@pytest.mark.parametrize("status", [*(status for status, _label in OUTCOMES), "unknown_future_status"])
@pytest.mark.parametrize("historical_receipt", [False, True])
def test_stale_observation_or_historical_receipt_overrides_previous_result(ui, status, historical_receipt):
    record = receipt(status, validity="recorded" if historical_receipt else "stale")
    if historical_receipt:
        record["history_state"] = "historical_after_generation_change"
    before = deepcopy(record)
    assert ui._target_channels_label(record) == "Stale; verify again"
    assert record == before


@pytest.mark.parametrize("record,expected", [
    ({}, "No retained expectation"),
    ({"target_observation": None, "target_expectation": None}, "No retained expectation"),
    ({"target_expectation": {"availability": "available"}}, "Not verified"),
    ({"target_expectation": {"availability": "unavailable", "reason": "rotation_mode_conversion"}},
     "Expectation unavailable"),
    ({"target_expectation": {"availability": "future_profile"}}, "Observation unavailable"),
    ({"target_expectation": {}}, "Observation unavailable"),
    ({"target_observation": {}}, "Observation unavailable"),
    ({"target_observation": {"status": "channels_match", "validity": "unknown", "scope": SCOPE}},
     "Observation unavailable"),
    ({"target_observation": {"status": "channels_match", "validity": "recorded"}},
     "Observation unavailable"),
    ({"target_observation": {"status": "channels_match", "validity": "recorded", "scope": "world_transform"}},
     "Observation unavailable"),
    ({"target_observation": {"status": "future_outcome", "validity": "recorded", "scope": SCOPE}},
     "Observation unavailable"),
    ({"target_expectation": False}, "Observation unavailable"),
    ({"target_observation": False}, "Observation unavailable"),
    ({"history_state": "unknown", "target_expectation": {"availability": "available"}},
     "Observation unavailable"),
])
def test_legacy_unavailable_or_unknown_data_cannot_appear_matched(ui, record, expected):
    before = deepcopy(record)
    assert ui._target_channels_label(record) == expected
    assert record == before
    assert len(expected) <= 40 and "Matched" not in expected


@pytest.mark.parametrize("status,_label", OUTCOMES)
@pytest.mark.parametrize("field,value", [
    ("current_scene_verified", True), ("current_scene_verified", 0), ("current_scene_verified", None),
    ("user_goal_verified", True), ("user_goal_verified", 0), ("user_goal_verified", None),
    ("comparison_complete", 0), ("comparison_complete", 1), ("comparison_complete", None),
])
def test_recorded_labels_require_literal_false_claims_and_complete_flags(ui, status, _label, field, value):
    record = receipt(status)
    record["target_observation"][field] = value
    assert ui._target_channels_label(record) == "Observation unavailable"


@pytest.mark.parametrize("status,_label", OUTCOMES)
def test_recorded_labels_require_outcome_appropriate_comparison_completeness(ui, status, _label):
    record = receipt(status)
    record["target_observation"]["comparison_complete"] = status not in {"channels_match", "channels_differ"}
    assert ui._target_channels_label(record) == "Observation unavailable"
    record["target_observation"].pop("current_scene_verified")
    assert ui._target_channels_label(record) == "Observation unavailable"


def test_formatter_uses_no_runtime_native_getter_or_mapping_adapter(ui, monkeypatch):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("runtime")
        raise AssertionError("Cached formatting must not inspect or refresh native state")

    class MappingAdapter(dict):
        def get(self, *_args, **_kwargs):
            calls.append("mapping")
            raise AssertionError("Mapping adapters must not run")

    class ValueAdapter:
        def __eq__(self, _other):
            calls.append("comparison")
            raise AssertionError("Unknown values must not run comparison callbacks")

        def __str__(self):
            calls.append("string")
            raise AssertionError("Unknown values must not be formatted")

    monkeypatch.setattr(ui, "bpy", NS(context=NS(inspect=forbidden)))
    monkeypatch.setattr(ui, "get_runtime", forbidden)
    monkeypatch.setattr(ui, "get_preferences", forbidden)
    assert ui._target_channels_label(receipt()) == "Matched at verification"
    assert ui._target_channels_label(MappingAdapter()) == "Observation unavailable"
    for field in ("validity", "scope", "status", "comparison_complete", "current_scene_verified", "user_goal_verified"):
        record = receipt()
        record["target_observation"][field] = ValueAdapter()
        assert ui._target_channels_label(record) == "Observation unavailable"
    assert ui._target_channels_label({"target_expectation": MappingAdapter()}) == "Observation unavailable"
    assert calls == []


class Layout:
    """Collect labels from the actual panel draw method without importing bpy."""

    def __init__(self):
        self.labels = []

    def box(self):
        return self

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def label(self, *, text, icon=None):
        self.labels.append((text, icon))

    def operator(self, *_args, **_kwargs):
        return NS()


def test_actual_panel_draw_uses_one_snapshot_latest_receipt_and_eight_step_limit(ui):
    # Only the real draw method is compiled: Blender's registration classes are
    # unavailable in portable Python. Its ordinary panel/runtime code still runs.
    tree = ast.parse(Path(ui.__file__).read_text())
    panel = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
                 and node.name == "BCB_PT_bridge_panel")
    draw = next(node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == "draw")
    records = [receipt("channels_match", step_id="s0"), receipt("channels_differ", step_id="s0"),
               receipt("channels_match", step_id="s1"), receipt("target_missing", step_id="s2"),
               receipt("target_replaced", step_id="s3"), receipt(validity="stale", step_id="s4")]
    for index, expectation in ((5, {"availability": "available"}), (6, {"availability": "unavailable"}), (7, None)):
        record = receipt(step_id=f"s{index}")
        record.update(target_observation=None, target_expectation=expectation)
        records.append(record)
    records.extend([receipt(step_id="s8"), receipt(step_id="s9")])
    plan_info = {"plan": {"steps": [{"id": f"s{index}", "description": f"Step {index}", "status": "pending"}
                                    for index in range(10)], "protected_objects": ["Protected peer"]},
                 "step_evidence": {"receipts": records, "incomplete": False}, "protected_scope_enforced": False}
    before = deepcopy(plan_info)
    evidence = object()
    snapshots = []

    def inspect(actual_evidence):
        assert actual_evidence is evidence
        snapshots.append(True)
        return plan_info

    state = {"is_executing": False, "emergency_stopped": False, "connected_clients": 0,
             "server_running": False, "current_method": "", "current_task": "Artist task", "last_error": "", "paused": False}
    recovery = {"native_undo_steps": 32, "global_undo_enabled": True, "native_undo_memory_limit_mb": 0,
                "tracked_operation_count": 0, "expired_operations_pruned_since_clear": 0,
                "latest_operation": None, "checkpoints": []}
    runtime = NS(state=NS(snapshot=lambda: state, history=lambda _limit: [], _artist_task_plans=NS(inspect=inspect)),
                 executor=NS(evidence=evidence), command_queue=NS(pending_count=0),
                 registry=NS(describe=lambda: {"toolsets": []}), jobs=NS(list=lambda **_kwargs: {"jobs": []}),
                 checkpoints=NS(recovery_status=lambda **_kwargs: recovery, editor_session_status=lambda: None))
    namespace = {**vars(ui), "get_runtime": lambda: runtime, "get_preferences": lambda _context: None}
    exec(compile(ast.Module(body=[draw], type_ignores=[]), ui.__file__, "exec"), namespace)
    layout = Layout()
    namespace["draw"](NS(layout=layout), object())
    labels = [text for text, _icon in layout.labels]
    assert snapshots == [True] and plan_info == before
    target_headings = [index for index, text in enumerate(labels) if text == "Target core channels:"]
    assert len(target_headings) == 8
    assert [labels[index + 1] for index in target_headings] == [
        "Differences at verification", "Matched at verification", "Target missing at verification",
        "Target replaced at verification", "Stale; verify again", "Not verified", "Expectation unavailable",
        "No retained expectation"]
    assert all(labels[index + 2] == "Protected objects only: Not compared" for index in target_headings)
    assert labels.count("Protected objects only: Not compared") == 8
    assert "Plan: 0/10 marked complete" in labels and "2 more steps; inspect the plan" in labels
    disclaimer = labels.index("Step marks are claims;")
    assert layout.labels[disclaimer:disclaimer + 4] == [
        ("Step marks are claims;", "INFO"), ("receipts do not verify the goal", None),
        ("Target records are historical;", "INFO"), ("verify after manual edits", None)]
