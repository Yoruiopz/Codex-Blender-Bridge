from __future__ import annotations

import importlib
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest


class Scene(dict):
    library = None
    override_library = None
    is_editable = True


class NativeStack:
    def __init__(self):
        self.scene = Scene(value=0)
        self.frames = [dict(self.scene)]
        self.cursor = 0
        self.fail_redo = False
        self.bpy = NS(
            data=NS(scenes=[self.scene]),
            context=NS(
                scene=self.scene, mode="OBJECT", preferences=NS(edit=NS(use_global_undo=True))
            ),
            ops=NS(ed=NS(undo_push=self.push, undo=self.undo, redo=self.redo)),
        )

    def push(self, **kwargs):
        self.frames = [*self.frames[: self.cursor + 1], deepcopy(dict(self.scene))]
        self.cursor += 1
        return {"FINISHED"}

    def move(self, delta):
        if not 0 <= self.cursor + delta < len(self.frames):
            return {"CANCELLED"}
        self.cursor += delta
        self.scene.clear()
        self.scene.update(deepcopy(self.frames[self.cursor]))
        return {"FINISHED"}

    def undo(self):
        return self.move(-1)

    def redo(self):
        return {"CANCELLED"} if self.fail_redo else self.move(1)


@pytest.fixture
def recovery(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.checkpoints")
    stack = NativeStack()
    monkeypatch.setattr(module, "require_blender", lambda: stack.bpy)
    return module, stack, module.CheckpointManager()


def edit(stack, manager, value):
    assert manager.before_modification("edit")
    stack.scene["value"] = value
    assert manager.after_modification("edit")


def test_recovers_multiple_edits_and_internal_snapshots_by_marker(recovery):
    _, stack, manager = recovery
    checkpoint = manager.create()
    edit(stack, manager, 1)
    assert manager.before_modification("multiple")
    stack.scene["value"] = 2
    stack.push()
    stack.scene["value"] = 3
    assert manager.after_modification("multiple")
    assert manager.restore_operation()["undo_steps"] == 3
    assert stack.scene["value"] == 1
    manager.restore_operation()
    assert stack.scene["value"] == 0
    result = manager.restore_last()
    assert result["checkpoint"] == checkpoint and result["snapshot_marker_verified"]


@pytest.mark.parametrize("fail_redo", [False, True])
def test_missing_target_attempts_measured_return_without_false_success(recovery, fail_redo):
    module, stack, manager = recovery
    edit(stack, manager, 1)
    stack.scene["value"] = 42  # Unsnapshotted manual work must be captured by the guard.
    stack.fail_redo = fail_redo
    with pytest.raises(module.BridgeError) as caught:
        manager._recover_to("missing")
    assert caught.value.context["return_to_guard_verified"] is not fail_redo
    assert caught.value.context["verification_required"]
    assert manager.recovery_in_progress is False
    if not fail_redo:
        assert stack.scene["value"] == 42
    assert not manager._undo_steps


def test_traversal_budget_does_not_leave_partial_recovery(recovery, monkeypatch):
    module, stack, manager = recovery
    edit(stack, manager, 5)
    monkeypatch.setattr(module, "MAX_UNDO_HOPS", 1)
    with pytest.raises(module.BridgeError) as caught:
        manager.restore_operation()
    assert caught.value.context["return_to_guard_verified"]
    assert stack.scene["value"] == 5


def test_unrelated_reserved_property_is_never_overwritten(recovery):
    module, stack, manager = recovery
    stack.scene[module.MARKER_KEY] = "BCB1:User note, not a token"
    assert manager.before_modification("edit") is False
    assert stack.scene[module.MARKER_KEY] == "BCB1:User note, not a token"


def test_editor_specific_undo_does_not_claim_global_boundary(recovery):
    _, stack, manager = recovery
    stack.bpy.context.mode = "EDIT_MESH"
    assert manager.before_modification("mesh_edit") is False
    assert len(stack.frames) == 1


def test_detach_removes_only_owned_metadata(recovery):
    module, stack, manager = recovery
    manager.create()
    stack.scene["user_property"] = 17
    manager.detach()
    assert module.MARKER_KEY not in stack.scene and stack.scene["user_property"] == 17
    stack.scene[module.MARKER_KEY] = "foreign value"
    manager.detach()
    assert stack.scene[module.MARKER_KEY] == "foreign value"


def test_legacy_undo_keeps_one_native_step_contract(recovery):
    _, stack, manager = recovery
    assert manager.before_modification("internal")
    stack.scene["value"] = 1
    stack.push()
    stack.scene["value"] = 2
    manager.after_modification("internal")
    result = manager.undo_last()
    assert result["undo_steps"] == 1 and not result["snapshot_marker_verified"]
    assert stack.scene["value"] == 1
    assert not manager._undo_steps


def test_named_marker_is_not_reused_by_later_manual_snapshots(recovery):
    _, stack, manager = recovery
    manager.create()
    stack.scene["value"] = 10
    stack.push()
    manager.restore_last()
    assert stack.scene["value"] == 0


def test_cancellation_during_navigation_returns_to_guard(recovery):
    module, stack, manager = recovery
    edit(stack, manager, 5)
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise module.BridgeError(module.ErrorCode.TIMEOUT, "fixture cancellation")

    with pytest.raises(module.BridgeError) as caught:
        manager.restore_operation(check_cancelled=cancelled)
    assert caught.value.code == "TIMEOUT"
    assert caught.value.context["return_to_guard_verified"]
    assert stack.scene["value"] == 5
