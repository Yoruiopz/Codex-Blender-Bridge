from __future__ import annotations

import asyncio
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools import catalog
from mcp_server.tools.animation_curve_inspection import (
    AnimationCurveInspectionTools,
    load_definitions,
)

METHOD = "animation.curve_inspect"


def test_read_only_definitions_catalog_and_bindings_agree():
    definition, = load_definitions()
    binding, = AnimationCurveInspectionTools(None).bindings()
    assert definition.name == binding.name == METHOD
    assert definition.toolset == "animation" and definition.modifying is False
    assert definition.required_permissions == ("INSPECT_SCENE",)
    assert METHOD in catalog.ANIMATION_TOOL_NAMES
    catalog_definition = next(item for item in catalog.load_animation_definitions() if item.name == METHOD)
    assert (catalog_definition.toolset, catalog_definition.modifying, catalog_definition.required_permissions) == (
        "animation", False, ("INSPECT_SCENE",))
    assert next(item for item in catalog.ANIMATION_TOOL_DATA if item[0] == METHOD)[2:] == (False, ("INSPECT_SCENE",))


def test_typed_wrapper_forwards_exact_selector_and_pagination_defaults():
    calls = []

    class Registry:
        async def call(self, name, values):
            calls.append((name, values))
            return values

    async def scenario():
        tools = AnimationCurveInspectionTools(Registry())
        await tools.animation_curve_inspect("Actor", "location")
        await tools.animation_curve_inspect("Actor", 'pose.bones["Hand.L"].rotation_euler', index=2,
                                           slot_identifier="OBActor", point_offset=256, point_limit=128)

    asyncio.run(scenario())
    assert calls == [(METHOD, {"object_name": "Actor", "data_path": "location", "index": 0,
                               "point_offset": 0, "point_limit": 64}),
                     (METHOD, {"object_name": "Actor", "data_path": 'pose.bones["Hand.L"].rotation_euler',
                               "index": 2, "slot_identifier": "OBActor", "point_offset": 256, "point_limit": 128})]


@pytest.mark.parametrize("field,invalid", [
    ("object_name", ""), ("object_name", 7), ("object_name", "x" * 257),
    ("data_path", ""), ("data_path", 7), ("data_path", "x" * 513),
    ("slot_identifier", 7), ("slot_identifier", ""), ("slot_identifier", "x" * 257),
    ("index", True), ("index", 0.0), ("index", "0"), ("index", -1), ("index", 16385),
    ("point_offset", True), ("point_offset", 0.0), ("point_offset", "0"),
    ("point_offset", -1), ("point_offset", 1_000_001), ("point_offset", None),
    ("point_limit", True), ("point_limit", 1.0), ("point_limit", "1"),
    ("point_limit", 0), ("point_limit", 257), ("point_limit", None),
])
def test_annotations_reject_coercion_and_out_of_bounds_values(field, invalid):
    annotations = get_type_hints(AnimationCurveInspectionTools.animation_curve_inspect, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(annotations[field]).validate_python(invalid)


def test_official_sdk_publishes_read_only_schema_and_validates_before_forwarding():
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
                tool, = [tool for tool in (await client.list_tools()).tools if tool.name == METHOD]
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                schema = tool.input_schema
                assert schema["required"] == ["object_name", "data_path"]
                fields = schema["properties"]
                assert (fields["point_offset"]["default"], fields["point_offset"]["minimum"], fields["point_offset"]["maximum"]) == (0, 0, 1_000_000)
                assert (fields["point_limit"]["default"], fields["point_limit"]["minimum"], fields["point_limit"]["maximum"]) == (64, 1, 256)
                assert fields["index"]["default"] == 0 and fields["index"]["maximum"] == 16384
                values = {"object_name": "Actor", "data_path": "location"}
                for invalid in ({"point_offset": True}, {"point_offset": "0"}, {"point_offset": 1_000_001},
                                {"point_limit": 0}, {"point_limit": 257}, {"point_limit": 1.0},
                                {"index": -1}, {"slot_identifier": 7}, {"object_name": 7}):
                    result = await client.call_tool(METHOD, {**values, **invalid})
                    assert result.is_error
                assert not calls
                result = await client.call_tool(METHOD, values)
                assert not result.is_error
                result = await client.call_tool(METHOD, {**values, "index": 2, "slot_identifier": "OBActor",
                                                         "point_offset": 64, "point_limit": 256})
                assert not result.is_error
                assert calls == [(METHOD, {**values, "index": 0, "point_offset": 0, "point_limit": 64}),
                                 (METHOD, {**values, "index": 2, "slot_identifier": "OBActor",
                                           "point_offset": 64, "point_limit": 256})]
        finally:
            await runtime.client.close()

    asyncio.run(scenario())
