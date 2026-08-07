from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from mcp_server.errors import BridgeError, ToolsetDisabledError
from mcp_server.schemas import JsonValue
from mcp_server.tool_registry import ToolDefinition, ToolRegistry, remote_tool


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(
        self, method: str, params: Mapping[str, Any] | None = None, **_: Any
    ) -> JsonValue:
        copied = dict(params or {})
        self.calls.append((method, copied))
        return {"method": method, "params": copied}


def test_core_tool_forwards_structured_request() -> None:
    client = RecordingClient()
    registry = ToolRegistry(client)
    registry.register_core([remote_tool("scene.inspect")])

    result = asyncio.run(registry.call("scene.inspect", include_hidden=False))

    assert result == {
        "method": "scene.inspect",
        "params": {"include_hidden": False},
    }
    assert client.calls == [("scene.inspect", {"include_hidden": False})]


def test_domain_toolset_is_lazy_and_disabled_by_default() -> None:
    client = RecordingClient()
    registry = ToolRegistry(client)
    load_count = 0

    def load_mesh() -> tuple[ToolDefinition, ...]:
        nonlocal load_count
        load_count += 1
        return (remote_tool("mesh.inspect", toolset="mesh"),)

    registry.register_toolset("mesh", load_mesh, tools=("mesh.inspect",))

    assert load_count == 0
    with pytest.raises(ToolsetDisabledError):
        asyncio.run(registry.call("mesh.inspect", object_name="Cube"))
    assert load_count == 0

    enabled = registry.enable("mesh")
    assert enabled["changed"] is True
    assert load_count == 1
    assert asyncio.run(registry.call("mesh.inspect"))["method"] == "mesh.inspect"

    registry.disable("mesh")
    with pytest.raises(ToolsetDisabledError):
        asyncio.run(registry.call("mesh.inspect"))

    registry.enable("mesh")
    assert load_count == 1


def test_toolset_control_synchronizes_blender_and_local_state() -> None:
    client = RecordingClient()
    registry = ToolRegistry(client)
    registry.register_toolset(
        "mesh",
        lambda: (remote_tool("mesh.inspect", toolset="mesh"),),
        tools=("mesh.inspect",),
    )

    enabled = asyncio.run(registry.call("toolsets.enable", name="mesh"))

    assert enabled["scope"] == "mcp_and_blender"
    assert registry.enabled_toolsets == ("core", "mesh")
    assert client.calls == [("toolsets.enable", {"name": "mesh"})]

    disabled = asyncio.run(registry.call("toolsets.disable", name="mesh"))
    assert disabled["changed"] is True
    assert registry.enabled_toolsets == ("core",)
    assert client.calls[-1] == ("toolsets.disable", {"name": "mesh"})


def test_loader_must_match_declared_tools() -> None:
    registry = ToolRegistry(RecordingClient())
    registry.register_toolset(
        "mesh",
        lambda: (remote_tool("mesh.other", toolset="mesh"),),
        tools=("mesh.inspect",),
    )

    with pytest.raises(ValueError, match="disagrees"):
        registry.enable("mesh")


def test_core_cannot_be_disabled() -> None:
    registry = ToolRegistry(RecordingClient())

    with pytest.raises(BridgeError) as caught:
        registry.disable("core")

    assert caught.value.code == "INVALID_ARGUMENT"


def test_non_json_tool_result_is_rejected() -> None:
    async def invalid_handler(_: RecordingClient, __: Mapping[str, JsonValue]) -> Any:
        return object()

    registry = ToolRegistry(RecordingClient())
    registry.register_core(
        [
            ToolDefinition(
                name="scene.invalid",
                description="test",
                handler=invalid_handler,
            )
        ]
    )

    with pytest.raises(BridgeError) as caught:
        asyncio.run(registry.call("scene.invalid"))

    assert caught.value.code == "PROTOCOL_ERROR"
