from __future__ import annotations

import asyncio
import math

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools import catalog
from mcp_server.tools.animation_curves import AnimationCurveTools, KeyframeEdit, load_definitions

METHOD = "animation.curve_edit"


def test_definitions_and_catalog_keep_the_modifying_animation_permission_contract():
    definition = next(item for item in load_definitions() if item.name == METHOD)
    binding = next(item for item in AnimationCurveTools(None).bindings() if item.name == METHOD)
    assert definition.name == binding.name
    assert (definition.toolset, definition.modifying, definition.required_permissions) == (
        "animation", True, ("EDIT_ANIMATION",))
    assert METHOD in catalog.ANIMATION_TOOL_NAMES
    catalog_definition = next(item for item in catalog.load_animation_definitions() if item.name == METHOD)
    assert (catalog_definition.name, catalog_definition.description, catalog_definition.toolset,
            catalog_definition.modifying, catalog_definition.required_permissions) == (
        definition.name, definition.description, "animation", True, ("EDIT_ANIMATION",))


@pytest.mark.parametrize("invalid", [
    None, True, 1, 1.0, "1,2", {}, (), (1.0, 2.0), [], [1], [1, 2, 3],
    [True, 2], [1, False], ["1", 2], [1, "2"], [None, 2], [[1], 2], [1, {}],
    [float("nan"), 2], [1, float("nan")], [float("inf"), 2], [1, -float("inf")],
    [1_000_001, 2], [-1_000_001, 2], [1, 1_000_001], [1, -1_000_001],
])
def test_optional_co_rejects_coercion_nonfinite_components_shapes_and_bounds(invalid):
    with pytest.raises(ValidationError):
        TypeAdapter(KeyframeEdit).validate_python({"frame": 1, "co": invalid})


@pytest.mark.parametrize("co", [[1, 2], [-1_000_000, 1_000_000], [-0.0, -0.0], [1.25, 2.5]])
def test_optional_co_accepts_finite_json_numbers_and_retains_negative_zero(co):
    result = TypeAdapter(KeyframeEdit).validate_python({"frame": co[0], "co": co})
    assert result["co"] == co
    assert all(type(value) is float for value in result["co"])
    for actual, supplied in zip(result["co"], co, strict=True):
        if supplied == 0:
            assert math.copysign(1, actual) == math.copysign(1, supplied)


def test_co_is_additive_and_state_dependent_admission_stays_in_blender():
    adapter = TypeAdapter(KeyframeEdit)
    legacy = {"frame": 1, "interpolation": "BEZIER", "easing": "EASE_IN",
              "handle_left_type": "FREE", "handle_right_type": "FREE",
              "handle_left": [0, 0], "handle_right": [2, 2]}
    assert adapter.validate_python(legacy) == legacy
    assert adapter.validate_python({"frame": 1}) == {"frame": 1}
    # The schema cannot know native frame bits or the original source profile.
    assert adapter.validate_python({"frame": 1, "co": [2, 3]})["co"] == [2, 3]
    with pytest.raises(ValidationError):
        adapter.validate_python({"co": [1, 2]})


def test_wrapper_preserves_existing_envelope_and_forwards_co_without_state_guesses():
    calls = []

    class Registry:
        async def call(self, method, values):
            calls.append((method, values))
            return values

    async def scenario():
        tools = AnimationCurveTools(Registry())
        await tools.animation_curve_edit("Actor", "location", keyframes=[{"frame": 11, "co": [11, 4]}])
        await tools.animation_curve_edit("Actor", "scale", index=2,
            keyframes=[{"frame": 1, "interpolation": "LINEAR", "handle_left_type": "FREE"}],
            extrapolation="LINEAR", slot_identifier="OBActor", affected_objects=["Protected"])

    asyncio.run(scenario())
    assert calls == [(METHOD, {"object_name": "Actor", "data_path": "location", "index": 0,
                               "keyframes": [{"frame": 11, "co": [11, 4]}]}),
                     (METHOD, {"object_name": "Actor", "data_path": "scale", "index": 2,
                               "keyframes": [{"frame": 1, "interpolation": "LINEAR", "handle_left_type": "FREE"}],
                               "extrapolation": "LINEAR", "slot_identifier": "OBActor",
                               "affected_objects": ["Protected"]})]


def test_official_sdk_schema_publishes_optional_float2_and_validates_before_forwarding():
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
                assert tool.annotations.read_only_hint is False
                schema = tool.input_schema
                assert schema["required"] == ["object_name", "data_path"]
                keyframe = schema["$defs"]["KeyframeEdit"]
                assert keyframe["required"] == ["frame"]
                assert set(keyframe["properties"]) == {"frame", "co", "interpolation", "easing",
                    "handle_left_type", "handle_right_type", "handle_left", "handle_right"}
                co = keyframe["properties"]["co"]
                assert co["type"] == "array" and co["minItems"] == co["maxItems"] == 2
                assert co["items"]["type"] == "number"
                assert (co["items"]["minimum"], co["items"]["maximum"]) == (-1_000_000, 1_000_000)
                values = {"object_name": "Actor", "data_path": "location"}
                for invalid in (None, [], [1], [1, 2, 3], [True, 2], [1, False],
                                ["1", 2], [1, None], [1, 1_000_001]):
                    result = await client.call_tool(METHOD, {**values, "keyframes": [{"frame": 11, "co": invalid}]})
                    assert result.is_error
                assert not calls
                edit = {"frame": 11, "co": [11, 4], "handle_right": [12, 5]}
                result = await client.call_tool(METHOD, {**values, "keyframes": [edit]})
                assert not result.is_error
                legacy = {"frame": 11, "interpolation": "LINEAR", "handle_left_type": "FREE"}
                result = await client.call_tool(METHOD, {**values, "keyframes": [legacy], "extrapolation": "CONSTANT"})
                assert not result.is_error
                assert calls == [(METHOD, {**values, "index": 0, "keyframes": [edit]}),
                                 (METHOD, {**values, "index": 0, "keyframes": [legacy], "extrapolation": "CONSTANT"})]
        finally:
            await runtime.client.close()

    asyncio.run(scenario())
