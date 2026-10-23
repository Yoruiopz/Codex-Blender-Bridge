from __future__ import annotations

import asyncio
import inspect
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.scene_edit import SceneEditTools


@pytest.mark.parametrize("invalid", [True, False, "12", [], {}, -0.1, 1.0e9 + 1,
                                     float("nan"), float("inf"), -float("inf"), 10 ** 400])
def test_focus_distance_annotation_is_strict_bounded_and_finite(invalid):
    annotation = get_type_hints(SceneEditTools.camera_configure, include_extras=True)["focus_distance"]
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python(invalid)


@pytest.mark.parametrize("valid", [0, .1, 43.1, 1_000_000_000, None])
def test_focus_distance_annotation_accepts_only_optional_numeric_range(valid):
    annotation = get_type_hints(SceneEditTools.camera_configure, include_extras=True)["focus_distance"]
    assert TypeAdapter(annotation).validate_python(valid) == valid


def test_mcp_focus_distance_is_appended_and_default_calls_remain_compatible():
    parameters = list(inspect.signature(SceneEditTools.camera_configure).parameters)
    assert parameters[-3:] == ["scene_name", "set_active_for_scene", "focus_distance"]
    calls = []

    class Registry:
        async def call(self, name, values):
            calls.append((name, values))
            return values

    async def scenario():
        tools = SceneEditTools(Registry())
        await tools.camera_configure("Camera", lens=50)
        await tools.camera_configure("Camera", clear_focus_object=True, focus_distance=43.1)

    asyncio.run(scenario())
    assert calls == [("camera.configure", {"object_name": "Camera", "lens": 50, "clear_focus_object": False}),
                     ("camera.configure", {"object_name": "Camera", "clear_focus_object": True, "focus_distance": 43.1})]


def test_official_sdk_focus_distance_schema_and_pre_forward_validation():
    from mcp import Client

    from mcp_server.server import build_runtime

    async def scenario():
        runtime = build_runtime()
        calls = []

        async def forward(method, values):
            calls.append((method, values))
            return {"forwarded": method}

        runtime.registry.call = forward
        try:
            async with Client(runtime.server) as client:
                tool, = [tool for tool in (await client.list_tools()).tools if tool.name == "camera.configure"]
                assert tool.annotations.read_only_hint is False and tool.annotations.destructive_hint is False
                schema = tool.input_schema
                assert schema["required"] == ["object_name"]
                field = schema["properties"]["focus_distance"]
                number, = [branch for branch in field["anyOf"] if branch.get("type") == "number"]
                assert number["minimum"] == 0 and number["maximum"] == 1.0e9
                assert field["default"] is None
                for value in (True, False, "12", -0.1, 1.0e9 + 1, [], {}):
                    result = await client.call_tool("camera.configure", {"object_name": "Camera", "focus_distance": value})
                    assert result.is_error
                assert not calls
                for value in (0, 43.1, 1_000_000_000):
                    result = await client.call_tool("camera.configure", {"object_name": "Camera", "focus_distance": value,
                                                                         "clear_focus_object": True})
                    assert not result.is_error
                assert calls == [("camera.configure", {"object_name": "Camera", "clear_focus_object": True,
                                                       "focus_distance": value}) for value in (0, 43.1, 1_000_000_000)]
        finally:
            await runtime.client.close()

    asyncio.run(scenario())
