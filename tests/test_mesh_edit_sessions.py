from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_snapshots import NativeStack


@pytest.fixture
def edit_session(addon_package, monkeypatch):

    module = importlib.import_module(f"{addon_package}.checkpoints")
    stack = NativeStack()
    stack.scene.session_uid = 11
    obj = NS(name="Mesh", session_uid=22)
    stack.bpy.context.active_object = obj
    stack.bpy.context.objects_in_mode = [obj]
    monkeypatch.setattr(module, "require_blender", lambda: stack.bpy)
    manager = module.CheckpointManager()
    checkpoint = manager.create("Before edit")
    assert manager.before_modification("context.set_mode")
    stack.bpy.context.mode = "EDIT_MESH"
    assert manager.after_modification("context.set_mode") is False
    return module, stack, manager, checkpoint


def test_session_retains_named_checkpoint_and_finalizes_as_one_operation(edit_session):
    _, stack, manager, checkpoint = edit_session
    initial = manager.editor_session_status()
    assert initial["state"] == "deferred" and manager.list() == [checkpoint]
    assert not manager.before_modification("mesh.edit")
    stack.scene["value"] = 3
    assert manager.editor_session_status()["operation_attempts"] == 2
    assert manager.finish_editor_session() is None
    assert not manager.before_modification("context.set_mode")
    stack.bpy.context.mode = "OBJECT"
    finalized = manager.finish_editor_session()
    assert finalized["group_id"] == initial["group_id"] and finalized["state"] == "finalized"
    result = manager.restore_operation()
    assert (
        result["recovered_scope"] == "mesh_edit_session" and result["group_operation_attempts"] == 3
    )
    assert stack.scene["value"] == 0 and manager.editor_session_status() is None
    assert manager.list() == [checkpoint]


def test_changed_target_invalidates_group_but_keeps_named_checkpoint(edit_session):
    _, stack, manager, checkpoint = edit_session
    stack.bpy.context.active_object = NS(name="Other", session_uid=33)
    stack.bpy.context.mode = "OBJECT"
    assert manager.finish_editor_session()["state"] == "invalidated"
    assert manager.editor_session_status() is None and manager.list() == [checkpoint]
    assert not manager._undo_steps


def test_editor_finalization_failure_cannot_report_ready(edit_session, monkeypatch):
    _, stack, manager, _ = edit_session
    stack.bpy.context.mode = "OBJECT"

    def fail(**kwargs):
        raise RuntimeError("fixture snapshot failure")

    monkeypatch.setattr(stack.bpy.ops.ed, "undo_push", fail)
    assert manager.finish_editor_session()["state"] == "unavailable"
    assert manager.editor_session_status() is None and not manager._undo_steps


def test_named_restore_clears_pending_editor_session(edit_session):
    _, stack, manager, checkpoint = edit_session
    stack.scene["value"] = 5
    stack.bpy.context.mode = "OBJECT"
    assert manager.restore_last()["checkpoint"] == checkpoint
    assert stack.scene["value"] == 0 and manager.editor_session_status() is None


def test_history_invalidation_drops_pending_editor_session(edit_session):
    module, _, manager, _ = edit_session
    manager.clear()
    assert manager.editor_session_status() is None
    with pytest.raises(module.BridgeError, match="No tracked"):
        manager.restore_operation()


def test_other_editor_mode_does_not_claim_mesh_session_support(edit_session):
    _, stack, manager, checkpoint = edit_session
    stack.bpy.context.mode = "SCULPT"
    assert not manager.before_modification("unsupported_editor")
    assert manager.editor_session_status() is None and manager.list() == [checkpoint]


def test_precanceled_recovery_does_not_finalize_editor_session(edit_session):
    module, stack, manager, _ = edit_session
    stack.bpy.context.mode = "OBJECT"
    before_frames = len(stack.frames)

    def cancelled():
        raise module.BridgeError(module.ErrorCode.TIMEOUT, "fixture cancellation")

    with pytest.raises(module.BridgeError) as caught:
        manager.restore_operation(check_cancelled=cancelled)
    assert caught.value.code == "TIMEOUT"
    assert (
        len(stack.frames) == before_frames
        and manager.editor_session_status()["state"] == "deferred"
    )


def test_cancellation_after_session_finalization_retains_evidence(edit_session):
    module, stack, manager, _ = edit_session
    stack.bpy.context.mode = "OBJECT"
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise module.BridgeError(module.ErrorCode.TIMEOUT, "fixture cancellation")

    with pytest.raises(module.BridgeError) as caught:
        manager.restore_operation(check_cancelled=cancelled)
    assert caught.value.code == "TIMEOUT"
    assert caught.value.context["undo_group"]["state"] == "finalized"
    assert (
        caught.value.context["undo_boundary_finalized"]
        and caught.value.context["execution_started"]
    )
    assert manager._undo_steps[0].kind == "mesh_edit_session"
