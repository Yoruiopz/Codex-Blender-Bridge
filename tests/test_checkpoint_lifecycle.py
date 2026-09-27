from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


def test_external_history_navigation_invalidates_markers(addon_package, monkeypatch):
    runtime = importlib.import_module(f"{addon_package}.runtime")
    checkpoints = importlib.import_module(f"{addon_package}.checkpoints")
    manager = checkpoints.CheckpointManager()
    manager._undo_steps.append(checkpoints.UndoStep("tracked", "target", 1))
    monkeypatch.setattr(runtime, "_RUNTIME", NS(checkpoints=manager))
    references = []
    monkeypatch.setattr(runtime, "clear_selection_references", lambda: references.append("cleared"))
    runtime._before_external_undo_redo(None)
    assert references == ["cleared"]
    with pytest.raises(checkpoints.BridgeError, match="No tracked"):
        manager.restore_operation()


@pytest.mark.parametrize("failure", [False, True])
def test_own_undo_handler_guard_is_scoped_even_when_operator_fails(
    addon_package, monkeypatch, failure
):
    runtime = importlib.import_module(f"{addon_package}.runtime")
    checkpoints = importlib.import_module(f"{addon_package}.checkpoints")
    manager = checkpoints.CheckpointManager()
    manager._undo_steps.append(checkpoints.UndoStep("tracked", "target", 1))
    monkeypatch.setattr(runtime, "_RUNTIME", NS(checkpoints=manager))

    def undo():
        assert manager.recovery_in_progress
        runtime._before_external_undo_redo(None)
        assert [step.label for step in manager._undo_steps] == ["tracked"]
        if failure:
            raise RuntimeError("fixture failure")
        return {"FINISHED"}

    monkeypatch.setattr(
        manager,
        "_ensure_undo_enabled",
        lambda: NS(context=NS(mode="OBJECT"), ops=NS(ed=NS(undo=undo))),
    )
    monkeypatch.setattr(manager, "_snapshot", lambda *args: "guard")
    monkeypatch.setattr(manager, "_stamp", lambda *args: "fresh")
    markers = iter(["present", "guard" if failure else "target"])
    monkeypatch.setattr(manager, "_marker", lambda *args: next(markers))
    if failure:
        with pytest.raises(checkpoints.BridgeError):
            manager.restore_operation()
    else:
        assert manager.restore_operation()["tracked_agent_label"] == "tracked"
    assert manager.recovery_in_progress is False


def test_runtime_hooks_register_once_and_unregister(addon_package, monkeypatch):
    runtime = importlib.import_module(f"{addon_package}.runtime")
    handlers = NS(load_pre=[], undo_pre=[], redo_pre=[])
    monkeypatch.setattr(runtime, "bpy", NS(app=NS(handlers=handlers)))
    instance = runtime.BridgeRuntime()
    monkeypatch.setattr(instance.executor, "start", lambda: None)
    monkeypatch.setattr(instance.executor, "stop", lambda: None)
    monkeypatch.setattr(instance.server, "stop", lambda: None)
    instance.register()
    instance.register()
    assert handlers.undo_pre == [runtime._before_external_undo_redo]
    assert handlers.redo_pre == [runtime._before_external_undo_redo]
    instance.unregister()
    assert handlers.load_pre == handlers.undo_pre == handlers.redo_pre == []
