from __future__ import annotations

import importlib
from types import SimpleNamespace as NS


def test_cancellation_during_checkpoint_setup_prevents_handler_start(addon_package):
    executor_mod = importlib.import_module(f"{addon_package}.executor")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    state_mod = importlib.import_module(f"{addon_package}.state")
    permission_mod = importlib.import_module(f"{addon_package}.permissions")
    queue_mod = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    cancelled = False
    calls = []

    def before(_tool):
        nonlocal cancelled
        cancelled = True
        return True

    def check():
        if cancelled:
            raise errors.BridgeError(errors.ErrorCode.TIMEOUT, "Canceled during snapshot setup")

    registry = registry_mod.ToolRegistry()
    registry.register("fixture.edit", lambda *_: calls.append("edited"), modifies=True)
    executor = executor_mod.MainThreadExecutor(
        command_queue=queue_mod.CommandQueue(),
        registry=registry,
        state=state_mod.BridgeState(),
        permissions=permission_mod.PermissionManager(lambda: {}),
        checkpoints=NS(before_modification=before, after_modification=lambda _: True),
    )
    response = executor.execute_request(
        protocol.Request(id="cancel-after-checkpoint", method="fixture.edit", params={}),
        check_cancelled=check,
    )
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert calls == []
