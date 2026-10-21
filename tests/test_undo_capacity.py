from __future__ import annotations

import importlib
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_snapshots import NativeStack, edit


class BoundedStack(NativeStack):
    """Model Object Mode's step limit, including the first push after branching."""

    def __init__(self, limit=32):
        super().__init__()
        self.bpy.context.preferences.edit.undo_steps = limit
        self.bpy.context.preferences.edit.undo_memory_limit = 0

    def push(self, **kwargs):
        if self.cursor == len(self.frames) - 1:
            retained = max(1, self.bpy.context.preferences.edit.undo_steps)
            self.frames = self.frames[-retained:]
            self.cursor = len(self.frames) - 1
        return super().push(**kwargs)


@pytest.fixture
def capacity(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.checkpoints")
    stack = BoundedStack()
    monkeypatch.setattr(module, "require_blender", lambda: stack.bpy)
    return module, stack, module.CheckpointManager()


@pytest.mark.parametrize("limit,recovered", [(32, 16), (128, 17)])
def test_long_recovery_prunes_only_observed_expiry_and_stops_without_another_undo(
    capacity, limit, recovered
):
    module, stack, manager = capacity
    stack.bpy.context.preferences.edit.undo_steps = limit
    for value in range(1, 18):
        edit(stack, manager, value)
    status = manager.recovery_status()
    assert status["tracked_operation_count"] == recovered
    assert status["expired_operations_pruned_since_clear"] == 17 - recovered
    assert status["latest_operation"]["availability"] == "unverified"
    assert status["latest_operation"]["can_attempt_restore"]
    for value in range(16, 16 - recovered, -1):
        assert manager.restore_operation()["snapshot_marker_verified"]
        assert stack.scene["value"] == value
    before = deepcopy(stack.frames), stack.cursor, dict(stack.scene)
    with pytest.raises(module.BridgeError, match="No tracked") as caught:
        manager.restore_operation()
    assert caught.value.context["execution_started"] is False
    assert caught.value.context["scene_undo_performed"] is False
    assert (stack.frames, stack.cursor, dict(stack.scene)) == before
    assert manager.recovery_status()["expired_operations_pruned_since_clear"] == 17 - recovered


def test_guard_budget_refusal_is_read_only_and_cannot_resurrect_after_eviction(capacity):
    module, stack, manager = capacity
    stack.bpy.context.preferences.edit.undo_steps = 2
    checkpoint = manager.create()
    edit(stack, manager, 1)
    state = manager.recovery_status()["checkpoints"][0]
    assert state["availability"] == "guard_would_exceed_step_limit"
    assert state["can_attempt_restore"] is False
    before = deepcopy(stack.frames), stack.cursor, dict(stack.scene), manager._window.position
    with pytest.raises(module.BridgeError) as caught:
        manager.restore_last()
    assert caught.value.context["execution_started"] is False
    assert caught.value.context["undo_steps_completed"] == 0
    assert (stack.frames, stack.cursor, dict(stack.scene), manager._window.position) == before
    assert manager.restore_operation()["snapshot_marker_verified"]
    assert stack.scene["value"] == 0
    stack.bpy.context.preferences.edit.undo_steps = 128
    state = manager.recovery_status()["checkpoints"][0]
    assert state["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert state["availability"] == "expired"
    with pytest.raises(module.BridgeError) as expired:
        manager.restore_last()
    assert expired.value.context["recovery"]["availability"] == "expired"


def test_lowering_preferences_does_not_fabricate_completed_eviction(capacity):
    _, stack, manager = capacity
    manager.create()
    edit(stack, manager, 1)
    stack.bpy.context.preferences.edit.undo_steps = 1
    assert manager.recovery_status()["expired_checkpoint_count"] == 0
    assert manager.recovery_status()["checkpoints"][0]["availability"] == "guard_would_exceed_step_limit"
    stack.bpy.context.preferences.edit.undo_steps = 32
    assert manager.recovery_status()["checkpoints"][0]["availability"] == "unverified"
    assert manager.restore_last()["snapshot_marker_verified"]


def test_unobserved_manual_eviction_remains_unverified_and_failure_returns_to_guard(capacity):
    module, stack, manager = capacity
    stack.bpy.context.preferences.edit.undo_steps = 2
    edit(stack, manager, 1)
    for value in range(10, 18):
        stack.scene["value"] = value
        stack.push()
    stack.scene["value"] = 42
    stack.bpy.context.preferences.edit.undo_memory_limit = 1
    status = manager.recovery_status()
    assert status["native_undo_memory_limit_mb"] == 1
    assert status["latest_operation"]["availability"] == "unverified"
    assert status["availability_guaranteed"] is False
    with pytest.raises(module.BridgeError) as caught:
        manager.restore_operation()
    assert caught.value.context["return_to_guard_verified"]
    assert stack.scene["value"] == 42
    assert manager.recovery_status()["tracked_operation_count"] == 0


def test_recovery_branch_does_not_age_older_boundaries_by_discarded_future(capacity):
    _, stack, manager = capacity
    stack.bpy.context.preferences.edit.undo_steps = 8
    manager.create()
    for value in range(1, 4):
        edit(stack, manager, value)
    manager.restore_operation()
    manager.restore_operation()
    for value in (11, 12):
        edit(stack, manager, value)
        manager.restore_operation()
        assert stack.scene["value"] == 1
    assert manager.recovery_status()["expired_checkpoint_count"] == 0
    manager.restore_last()
    assert stack.scene["value"] == 0


def test_zero_undo_steps_cannot_claim_a_native_snapshot(capacity):
    module, stack, manager = capacity
    stack.bpy.context.preferences.edit.undo_steps = 0
    before = deepcopy(stack.frames), dict(stack.scene)
    with pytest.raises(module.BridgeError, match="zero"):
        manager.create()
    assert manager.before_modification("edit") is False
    assert (stack.frames, dict(stack.scene)) == before
    assert manager.recovery_status()["global_undo_enabled"] is False


def test_reports_are_bounded_read_only_and_do_not_enable_recovery_in_edit_mode(capacity):
    _, stack, manager = capacity
    for _ in range(3):
        manager.create()
    edit(stack, manager, 1)
    stack.bpy.context.mode = "EDIT_MESH"
    before = deepcopy(stack.frames), dict(stack.scene)
    report = manager.recovery_status(limit=1)
    assert len(report["checkpoints"]) == 1 and report["checkpoints_truncated"]
    assert report["latest_operation"]["availability"] == "unverified"
    assert not report["latest_operation"]["can_attempt_restore"]
    assert report["native_history_introspection"] is False
    assert (stack.frames, dict(stack.scene)) == before


def test_window_tracks_only_live_references_and_expiry_survives_preference_increases(addon_package):
    module = importlib.import_module(f"{addon_package}.undo_window")
    window = module.UndoWindow()
    window.pushed(2)
    window.track("old")
    for _ in range(3):
        window.pushed(2)
    assert window.expired("old")
    window.pushed(256)
    assert window.describe("old", 256)["availability"] == "expired"
    window.track("new")
    window.retain({"new"})
    assert set(window._targets) == {"new"}
    window.clear()
    assert window.position == 0 and not window._targets


def test_first_push_after_rewind_does_not_assume_a_tail_limit_was_applied(addon_package):
    module = importlib.import_module(f"{addon_package}.undo_window")
    window = module.UndoWindow()
    window.pushed(32)
    window.track("old")
    window.pushed(32)
    window.track("target")
    window.pushed(32)
    window.rewind("target")
    window.pushed(1)
    assert not window.expired("old")
    window.pushed(1)
    assert window.expired("old") and window.expired("target")


def test_public_list_includes_separate_availability_without_changing_label_contract(
    capacity, addon_package
):
    _, _, manager = capacity
    checkpoint = manager.create()
    core = importlib.import_module(f"{addon_package}.tools.core")
    result = core.checkpoint_list(NS(checkpoints=manager, state=NS(history=lambda limit: []),
                                     permissions=NS(snapshot=lambda: {})), {})
    assert result["checkpoints"] == [checkpoint]
    assert result["recovery"]["checkpoints"][0]["availability"] == "unverified"
    assert result["recovery"]["checkpoints"][0]["checkpoint_id"] == checkpoint["checkpoint_id"]


def test_ledger_remains_bounded_by_live_label_limits(capacity):
    module, stack, _ = capacity
    manager = module.CheckpointManager(maximum=3)
    for value in range(150):
        manager.create()
        edit(stack, manager, value)
        assert len(manager._window._targets) <= 15
    assert manager.recovery_status()["tracked_checkpoint_count"] == 3
