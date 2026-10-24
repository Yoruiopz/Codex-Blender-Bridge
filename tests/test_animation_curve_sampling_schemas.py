from __future__ import annotations

import asyncio
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools import catalog
from mcp_server.tools.animation_curve_sampling import AnimationCurveSamplingTools, load_definitions

METHOD = "animation.curve_sample"


def test_native_catalog_bindings_and_read_only_definition_agree():
    definition, = load_definitions()
    binding, = AnimationCurveSamplingTools(None).bindings()
    assert definition.name == binding.name == METHOD
    assert definition.toolset == "animation" and definition.modifying is False
    assert definition.required_permissions == ("INSPECT_SCENE",)
    assert METHOD in catalog.ANIMATION_TOOL_NAMES
    catalog_definition = next(item for item in catalog.load_animation_definitions() if item.name == METHOD)
    assert (catalog_definition.toolset, catalog_definition.modifying, catalog_definition.required_permissions) == (
        "animation", False, ("INSPECT_SCENE",))
    assert next(item for item in catalog.ANIMATION_TOOL_DATA if item[0] == METHOD)[2:] == (False, ("INSPECT_SCENE",))


def test_wrapper_forwards_explicit_frames_order_duplicates_selector_and_defaults():
    calls = []

    class Registry:
        async def call(self, name, values):
            calls.append((name, values))
            return values

    async def scenario():
        tools = AnimationCurveSamplingTools(Registry())
        await tools.animation_curve_sample("Actor", "location", [11, 1.1, 11])
        await tools.animation_curve_sample("Actor", 'pose.bones["Hand.L"].rotation_euler', [-1, 0, 100], index=2, slot_identifier="OBActor")

    asyncio.run(scenario())
    assert calls == [(METHOD, {"object_name": "Actor", "data_path": "location", "frames": [11, 1.1, 11], "index": 0}),
                     (METHOD, {"object_name": "Actor", "data_path": 'pose.bones["Hand.L"].rotation_euler',
                               "frames": [-1, 0, 100], "index": 2, "slot_identifier": "OBActor"})]


@pytest.mark.parametrize("field,invalid", [
    ("object_name", ""), ("object_name", 7), ("object_name", "x" * 257),
    ("data_path", ""), ("data_path", 7), ("data_path", "x" * 513),
    ("slot_identifier", 7), ("slot_identifier", ""), ("slot_identifier", "x" * 257),
    ("index", True), ("index", 0.0), ("index", "0"), ("index", -1), ("index", 16385),
    ("frames", None), ("frames", []), ("frames", [1] * 129), ("frames", (1,)), ("frames", "1"),
    ("frames", [True]), ("frames", ["1"]), ("frames", [None]), ("frames", [1_000_001]), ("frames", [-1_000_001]),
    ("frames", [float("nan")]), ("frames", [float("inf")]), ("frames", [-float("inf")]),
])
def test_annotations_reject_coercion_nonfinite_values_and_bounds(field, invalid):
    annotations = get_type_hints(AnimationCurveSamplingTools.animation_curve_sample, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(annotations[field]).validate_python(invalid)


def test_official_sdk_schema_and_validation_precede_any_forwarding():
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
                assert tool.annotations.read_only_hint is True and tool.annotations.destructive_hint is False
                schema = tool.input_schema
                assert schema["required"] == ["object_name", "data_path", "frames"]
                fields = schema["properties"]
                assert fields["index"]["default"] == 0 and fields["index"]["maximum"] == 16384
                assert fields["frames"]["minItems"] == 1 and fields["frames"]["maxItems"] == 128
                assert fields["frames"]["items"]["type"] == "number"
                assert (fields["frames"]["items"]["minimum"], fields["frames"]["items"]["maximum"]) == (-1_000_000, 1_000_000)
                values = {"object_name": "Actor", "data_path": "location", "frames": [11, 1.1, 11]}
                for invalid in ({"frames": []}, {"frames": [1] * 129}, {"frames": [True]}, {"frames": ["1"]},
                                {"frames": [1_000_001]}, {"frames": None}, {"index": True}, {"index": -1},
                                {"slot_identifier": 7}, {"object_name": 7}):
                    result = await client.call_tool(METHOD, {**values, **invalid})
                    assert result.is_error
                assert not calls
                result = await client.call_tool(METHOD, values)
                assert not result.is_error
                result = await client.call_tool(METHOD, {**values, "index": 2, "slot_identifier": "OBActor"})
                assert not result.is_error
                assert calls == [(METHOD, {**values, "index": 0}),
                                 (METHOD, {**values, "index": 2, "slot_identifier": "OBActor"})]
        finally:
            await runtime.client.close()

    asyncio.run(scenario())
