from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest


def test_empty_checkpoint_history_refuses_global_undo(addon_package: str) -> None:
    checkpoints = importlib.import_module(f"{addon_package}.checkpoints")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError) as caught:
        checkpoints.CheckpointManager().undo_last()

    assert caught.value.code == errors.ErrorCode.OPERATION_FAILED.value
    assert "refusing" in caught.value.message


def test_recovery_tools_obey_remote_pause_and_ui_only_gates(
    addon_package: str,
) -> None:
    errors = importlib.import_module(f"{addon_package}.errors")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    state_module = importlib.import_module(f"{addon_package}.state")

    registry = registry_module.ToolRegistry()

    def recover(_context: Any, _params: Any) -> dict[str, bool]:
        return {"recovered": True}

    registry.register("checkpoint.undo_last", recover, modifies=True)
    registry.register(
        "checkpoint.restore_last",
        recover,
        modifies=True,
        remote=False,
    )
    state = state_module.BridgeState()
    context = registry_module.ToolContext(
        state=state,
        permissions=permissions.PermissionManager(lambda: {}),
        registry=registry,
        checkpoints=object(),
    )
    state.set_paused(True)

    with pytest.raises(errors.BridgeError) as paused:
        registry.prepare("checkpoint.undo_last", context)
    assert paused.value.code == errors.ErrorCode.AGENT_PAUSED.value
    assert registry.prepare(
        "checkpoint.undo_last",
        context,
        allow_recovery=True,
    ).name == "checkpoint.undo_last"

    state.set_paused(False)
    with pytest.raises(errors.BridgeError) as remote:
        registry.prepare("checkpoint.restore_last", context)
    assert remote.value.code == errors.ErrorCode.METHOD_NOT_FOUND.value
    assert registry.prepare(
        "checkpoint.restore_last",
        context,
        allow_recovery=True,
    ).remote is False


def test_checkpoint_undo_requires_explicit_global_undo_confirmation(
    addon_package: str,
) -> None:
    core = importlib.import_module(f"{addon_package}.tools.core")
    errors = importlib.import_module(f"{addon_package}.errors")

    class Checkpoints:
        called = False

        def undo_last(self) -> dict[str, bool]:
            self.called = True
            return {"undone": True}

    checkpoints = Checkpoints()
    context = SimpleNamespace(checkpoints=checkpoints)

    with pytest.raises(errors.BridgeError) as caught:
        core.checkpoint_undo_last(context, {})

    assert caught.value.code == errors.ErrorCode.INVALID_ARGUMENT.value
    assert checkpoints.called is False
    assert core.checkpoint_undo_last(
        context,
        {"confirm_global_undo": True},
    ) == {"undone": True}
