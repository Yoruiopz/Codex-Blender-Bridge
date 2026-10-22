from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("modifying", [False, True])
def test_grant_provider_cannot_disable_toolset_and_still_start_handler(addon_package, modifying):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    registry = registry_module.ToolRegistry(enabled_toolsets=("mesh",))
    writes = []
    registry.register("mesh.fixture", lambda *_: writes.append("started"), toolset="mesh",
                      modifies=modifying, permissions=(permissions.Permission.EDIT_MESH,))

    def provider():
        registry.disable_toolset("mesh")
        return {"EDIT_MESH": True}

    context = registry_module.ToolContext(state_module.BridgeState(), permissions.PermissionManager(provider), registry, None)
    with pytest.raises(errors.BridgeError) as caught:
        registry.dispatch("mesh.fixture", {}, context)
    assert caught.value.code == "TOOLSET_DISABLED"
    assert caught.value.context == {"tool": "mesh.fixture", "toolset": "mesh"}
    assert writes == []
