from __future__ import annotations

import asyncio

from mcp import Client

from mcp_server.server import build_runtime


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
