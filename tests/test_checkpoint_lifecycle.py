from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


def test_external_history_navigation_invalidates_markers(addon_package, monkeypatch):
    runtime = importlib.import_module(f"{addon_package}.runtime")
    checkpoints = importlib.import_module(f"{addon_package}.checkpoints")
    manager = checkpoints.CheckpointManager()
    manager._undo_steps.append(checkpoints.UndoStep("tracked", "target", 1))
    cancellations = []
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    monkeypatch.setattr(runtime, "_RUNTIME", NS(checkpoints=manager, jobs=NS(cancel_all=cancellations.append), state=state))
    references = []
    monkeypatch.setattr(runtime, "clear_selection_references", lambda: references.append("cleared"))
    runtime._before_external_undo_redo(None)
    assert cancellations == ["native undo/redo"]
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
    cancellations = []
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    plans = importlib.import_module(f"{addon_package}.task_plans").get_task_plans(state)
    plans.references["ref_before_recovery"] = {}
    plans.previews["preview_before_recovery"] = {}
    generation = plans.protection_generation
    monkeypatch.setattr(runtime, "_RUNTIME", NS(checkpoints=manager, jobs=NS(cancel_all=cancellations.append), state=state))

    def undo():
        assert manager.recovery_in_progress
        runtime._before_external_undo_redo(None)
        assert cancellations == ["native undo/redo"]
        assert [step.label for step in manager._undo_steps] == ["tracked"]
        assert plans.protection_generation > generation
        assert not plans.references and not plans.previews
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


@pytest.mark.parametrize("recovery_in_progress", [False, True])
def test_every_native_history_callback_retains_policy_baseline_and_mutator_counter(addon_package, monkeypatch, recovery_in_progress):
    runtime = importlib.import_module(f"{addon_package}.runtime")
    data = importlib.import_module(f"{addon_package}.task_plans")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    store = data.get_task_plans(state)
    store.replace(data.contents("Preserve the character", [{"id": "edit", "description": "Revise prop"}], ["Protected"]), (1, (("Protected", 2),)))
    store.protection = {"plan_id": store.plan["plan_id"], "scope": store.scope}
    store.baseline = {"snapshot_id": "protected-baseline"}
    store.executing_mutators = 2
    plan, protection, baseline = store.plan, store.protection, store.baseline
    receipt = {"policy_stamp": (store.runtime_id, store.protection_generation)}
    store.applying_preview = receipt
    cleared = []
    monkeypatch.setattr(runtime, "_RUNTIME", NS(state=state, jobs=NS(cancel_all=lambda _reason: None),
        checkpoints=NS(recovery_in_progress=recovery_in_progress, clear=lambda: cleared.append("markers"))))
    monkeypatch.setattr(runtime, "clear_selection_references", lambda: cleared.append("selection"))
    generation = store.protection_generation
    for _navigation in ("undo", "redo"):
        store.references["ref_same_ids_and_context"] = {}
        store.previews["preview_same_authored_state"] = {}
        runtime._before_external_undo_redo(None)
        generation += 1
        assert store.protection_generation == generation
        assert data.get_task_plans(state) is store
        assert store.plan is plan and store.protection is protection and store.baseline is baseline
        assert store.executing_mutators == 2 and store.applying_preview is receipt
        assert not store.references and not store.previews
        assert receipt["policy_stamp"] != (store.runtime_id, store.protection_generation)
    assert cleared == ([] if recovery_in_progress else ["markers", "selection", "markers", "selection"])


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
