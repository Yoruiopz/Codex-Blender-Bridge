from __future__ import annotations

import asyncio

from mcp import Client

from mcp_server.server import build_runtime


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def request(self, method, params=None, **kwargs):
        self.calls.append((method, params))
        return {"forwarded": method}

    async def close(self):
        pass


def test_viewport_framing_schema_is_additive_and_disabled_by_default():
    async def scenario():
        recording = RecordingClient()
        runtime = build_runtime(client=recording)  # type: ignore[arg-type]
        try:
            async with Client(runtime.server) as client:
                listing = await client.list_tools()
                tools = [tool for tool in listing.tools if tool.name == "viewport.capture"]
                assert len(tools) == 1
                schema = tools[0].input_schema
                assert schema["properties"]["frame_object"]["type"] == "boolean"
                assert schema["properties"]["frame_object"]["default"] is False
                assert "frame_object" not in schema.get("required", [])
                assert tools[0].annotations.read_only_hint is False
                assert tools[0].annotations.destructive_hint is True
                result = await client.call_tool("viewport.capture", {})
                assert not result.is_error
                assert recording.calls == [
                    ("viewport.capture", {
                        "view": "current", "shading": "solid", "include_overlays": True,
                        "frame_object": False,
                    })
                ]
        finally:
            await runtime.client.close()

    asyncio.run(scenario())


def test_viewport_framing_sdk_rejects_boolean_coercion_before_forwarding():
    async def scenario():
        recording = RecordingClient()
        runtime = build_runtime(client=recording)  # type: ignore[arg-type]
        try:
            async with Client(runtime.server) as client:
                for invalid in (0, 1, "true", "false", None, [], {}):
                    result = await client.call_tool(
                        "viewport.capture", {"object_name": "Exact Target", "frame_object": invalid}
                    )
                    assert result.is_error, repr(invalid)
                assert not recording.calls
                for frame_object in (True, False):
                    result = await client.call_tool("viewport.capture", {
                        "view": "top", "shading": "wireframe", "object_name": "Exact Target",
                        "resolution": [640, 480], "include_overlays": False,
                        "frame_object": frame_object,
                    })
                    assert not result.is_error
                    assert recording.calls[-1] == ("viewport.capture", {
                        "view": "top", "shading": "wireframe", "include_overlays": False,
                        "object_name": "Exact Target", "resolution": [640, 480],
                        "frame_object": frame_object,
                    })
        finally:
            await runtime.client.close()

    asyncio.run(scenario())
