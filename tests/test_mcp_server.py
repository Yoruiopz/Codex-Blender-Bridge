from __future__ import annotations

import asyncio
import json

import pytest
from mcp import Client

from mcp_server.errors import BridgeError
from mcp_server.server import build_runtime


@pytest.mark.parametrize("expected", [True, False])
def test_sdk_preserves_safe_errors_and_redacts_unexpected_exceptions(expected: bool) -> None:
    class FailingClient:
        async def request(self, *_args, **_kwargs):
            if expected:
                raise BridgeError("PERMISSION_DENIED", "Enable the required permission.", context={"missing_permissions": ["EDIT_MESH"]})
            raise RuntimeError("secret diagnostic must stay local")

    async def scenario() -> None:
        runtime = build_runtime(client=FailingClient())  # type: ignore[arg-type]
        async with Client(runtime.server) as client:
            result = await client.call_tool("bridge.status", {})
            assert result.is_error
            error = json.loads(result.content[0].text)
            assert error["code"] == ("PERMISSION_DENIED" if expected else "OPERATION_FAILED")
            assert "secret diagnostic" not in result.content[0].text
            if expected:
                assert error["context"]["missing_permissions"] == ["EDIT_MESH"]
            listing = await client.list_tools()
            bulk = next(tool for tool in listing.tools if tool.name == "object.transform_batch")
            assert "edits" in bulk.input_schema["properties"]
            assert bulk.output_schema is None

    asyncio.run(scenario())


def test_official_mcp_sdk_discovers_structured_tools() -> None:
    async def scenario() -> None:
        runtime = build_runtime()
        try:
            async with Client(runtime.server) as client:
                listing = await client.list_tools()
                tools = {tool.name: tool for tool in listing.tools}

                assert "bridge.status" in tools
                assert "scene.inspect" in tools
                assert "object.create" in tools
                assert "mesh.bevel_selected" in tools
                assert "viewport.capture" in tools
                assert "material.set_principled" in tools
                assert "nodes.link" in tools
                assert "uv.unwrap" in tools
                assert "modifier.apply" in tools
                assert "rig.bind_mesh" in tools
                assert "animation.keyframe_insert" in tools
                assert "camera.configure" in tools
                assert "render.execute" in tools
                assert "python.execute" in tools
                assert "bridge.task.set" in tools
                for name in ("jobs.inspect", "jobs.list", "jobs.cancel", "image.paint_job_start"):
                    assert name in tools
                start_schema = tools["image.paint_job_start"].input_schema
                assert start_schema["required"] == ["image_name", "new_name", "strokes"]
                assert start_schema["properties"]["time_limit_seconds"]["maximum"] == 300
                assert tools["jobs.list"].input_schema["properties"]["limit"]["maximum"] == 32
                assert len(tools) >= 80
                assert tools["object.create"].input_schema["required"] == ["object_type"]
                assert "selection_id" in tools["mesh.bevel_selected"].input_schema["properties"]
                assert "max_collection_depth" in tools["scene.inspect"].input_schema["properties"]
                assert "confirm_global_undo" in tools["checkpoint.undo_last"].input_schema[
                    "properties"
                ]
                assert tools["scene.inspect"].annotations.read_only_hint is True
                assert tools["transform.translate"].annotations.read_only_hint is False
                assert tools["object.delete"].annotations.destructive_hint is True
                assert tools["project.save"].annotations.destructive_hint is True
                assert tools["viewport.capture"].annotations.read_only_hint is False
                assert tools["viewport.capture"].annotations.destructive_hint is True
                assert tools["python.execute"].annotations.destructive_hint is True
                assert tools["render.execute"].annotations.destructive_hint is True
                assert tools["nodes.inspect"].annotations.read_only_hint is True
                assert tools["material.inspect"].annotations.open_world_hint is False

                toolsets = await client.call_tool("toolsets.list", {})
                assert toolsets.is_error is False
                assert toolsets.structured_content is not None
                assert toolsets.structured_content["enabled"] == ["core"]

                disabled = await client.call_tool("mesh.inspect", {})
                assert disabled.is_error is True
                assert "TOOLSET_DISABLED" in disabled.content[0].text
        finally:
            await runtime.client.close()

    asyncio.run(scenario())


def test_mcp_server_advertises_agent_workflow_instructions() -> None:
    runtime = build_runtime()
    try:
        instructions = getattr(runtime.server, "instructions", "")
        assert "inspect" in instructions.lower()
        assert "checkpoint" in instructions.lower()
        assert "verify" in instructions.lower()
        assert "permission" in instructions.lower()
        assert "python.execute" in instructions
        assert "bridge.task.set" in instructions
    finally:
        asyncio.run(runtime.client.close())


def test_sdk_enforces_annotated_bounds_and_strict_types_before_forwarding():
    calls = []
    class RecordingClient:
        async def request(self, method, params=None, **kwargs):
            calls.append((method, params))
            return {"forwarded": method}
        async def close(self):
            pass
    async def scenario():
        runtime = build_runtime(client=RecordingClient())  # type: ignore[arg-type]
        runtime.registry.enable("materials")
        brush = {"points": [[.5, .5]], "radius_pixels": 2., "color": [1., 0., 0., 1.]}
        async with Client(runtime.server) as client:
            for name, params in (
                ("jobs.list", {"limit": True}),
                ("jobs.list", {"limit": 33}),
                ("jobs.inspect", {"job_id": "not-a-job"}),
                ("image.create", {"new_name": "Canvas", "width": True, "height": 4}),
                ("image.paint_job_start", {"image_name": "Canvas", "new_name": "Painted", "strokes": [brush], "time_limit_seconds": 301}),
                ("image.paint_job_start", {"image_name": "Canvas", "new_name": "Painted", "strokes": [{**brush, "radius_pixels": 257.}]}),
            ):
                assert (await client.call_tool(name, params)).is_error
            assert calls == []
            result = await client.call_tool("image.paint_job_start", {"image_name": "Canvas", "new_name": "Painted", "strokes": [brush]})
            assert not result.is_error and calls[0][0] == "image.paint_job_start"
            assert calls[0][1]["strokes"][0]["radius_pixels"] == 2.
            assert calls[0][1]["time_limit_seconds"] == 60.
    asyncio.run(scenario())
