from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

from mcp_server.tool_registry import create_default_registry
from mcp_server.tools import iter_bindings


class NoopClient:
    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> Any:
        return {"method": method, "params": dict(params or {})}


def test_every_remote_addon_method_has_one_static_mcp_wrapper(addon_package: str) -> None:
    addon_registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    addon_tools = importlib.import_module(f"{addon_package}.tools")
    addon_registry = addon_registry_module.ToolRegistry()
    addon_tools.register_all(addon_registry)
    remote_methods = {
        item["name"]
        for item in addon_registry.describe()["tools"]
        if item["remote"]
    }

    mcp_registry = create_default_registry(NoopClient())
    binding_names = [binding.name for binding in iter_bindings(mcp_registry)]

    assert len(binding_names) == len(set(binding_names))
    assert set(binding_names) == remote_methods
    assert "checkpoint.restore_last" not in remote_methods
    assert "python.execute" in remote_methods
    assert len(remote_methods) >= 80


def test_default_registry_declares_every_wrapper_even_when_disabled() -> None:
    registry = create_default_registry(NoopClient())
    wrapper_names = {binding.name for binding in iter_bindings(registry)}

    assert set(registry.tool_names(include_disabled=True)) == wrapper_names
    assert registry.enabled_toolsets == ("core",)


def test_remote_permission_and_mutation_metadata_matches_blender(addon_package: str) -> None:
    """Composed specialist loaders must not weaken Blender's public permission metadata."""
    addon_registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools").register_all(addon_registry)
    mcp_registry = create_default_registry(NoopClient())
    for toolset in mcp_registry.inspect()["toolsets"]:
        if toolset["name"] != "core":
            mcp_registry.enable(toolset["name"])
    for name in addon_registry.list_tools():
        spec = addon_registry.get(name)
        # MCP enable/disable also mutate local enablement; Blender classifies
        # these controls outside scene mutation and its checkpoint lifecycle.
        if not spec.remote or name in {"toolsets.enable", "toolsets.disable"}:
            continue
        definition = mcp_registry._tools[name]
        assert set(definition.required_permissions) == {p.value for p in spec.permissions}, name
        assert definition.modifying == spec.modifies, name
        assert definition.toolset == spec.toolset, name
