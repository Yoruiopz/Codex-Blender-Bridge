from __future__ import annotations

import asyncio
import json
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools import catalog
from mcp_server.tools.surface_brushes import SurfaceBrushTools, load_definitions

METHOD = "mesh.sculpt_mask_sample"


def test_binding_catalog_and_read_only_permission_metadata_agree():
    definition, = [item for item in load_definitions() if item.name == METHOD]
    binding, = [item for item in SurfaceBrushTools(None).bindings() if item.name == METHOD]
    assert binding.handler.__name__ == "mesh_sculpt_mask_sample"
    assert definition.toolset == "mesh" and definition.modifying is False
    assert definition.required_permissions == ("INSPECT_SCENE",)
    assert METHOD in catalog.MESH_TOOL_NAMES and METHOD not in catalog.DESTRUCTIVE_TOOL_NAMES
    catalog_definition, = [item for item in catalog.load_mesh_definitions() if item.name == METHOD]
    assert (
        catalog_definition.toolset, catalog_definition.modifying, catalog_definition.required_permissions
    ) == ("mesh", False, ("INSPECT_SCENE",))


def test_wrapper_preserves_explicit_vertex_order_seam_policy_and_defaults():
    calls = []

    class Registry:
        async def call(self, method, values):
            calls.append((method, values))
            return values

    async def scenario():
        tools = SurfaceBrushTools(Registry())
        await tools.mesh_sculpt_mask_sample("Sculpt", "UVMap", [8, 0, 3], "PaintedMask", "MIN")
        await tools.mesh_sculpt_mask_sample("Sculpt", "Mask UV", [1], "PaintedMask", "MEAN", channel="A", invert=True)

    asyncio.run(scenario())
    assert calls == [
        (METHOD, {"object_name": "Sculpt", "uv_layer": "UVMap", "vertex_indices": [8, 0, 3],
                  "image_name": "PaintedMask", "corner_reduction": "MIN", "channel": "R", "invert": False}),
        (METHOD, {"object_name": "Sculpt", "uv_layer": "Mask UV", "vertex_indices": [1],
                  "image_name": "PaintedMask", "corner_reduction": "MEAN", "channel": "A", "invert": True}),
    ]


@pytest.mark.parametrize("field,invalid", [
    ("object_name", ""), ("object_name", " "), ("object_name", 3), ("object_name", "x"*64),
    ("uv_layer", ""), ("uv_layer", "bad\nname"), ("uv_layer", "é"*32), ("uv_layer", False),
    ("image_name", ""), ("image_name", "x"*64), ("image_name", 1), ("image_name", "\x00mask"),
    ("vertex_indices", []), ("vertex_indices", [0]*1025), ("vertex_indices", [0,0]),
    ("vertex_indices", [True]), ("vertex_indices", [1.0]), ("vertex_indices", ["1"]),
    ("vertex_indices", [-1]), ("vertex_indices", [100_000]), ("vertex_indices", [None]),
    ("vertex_indices", None), ("vertex_indices", "1"), ("vertex_indices", (1,)),
    ("channel", "r"), ("channel", "RGB"), ("channel", None), ("channel", 1),
    ("invert", 1), ("invert", "false"), ("invert", None),
    ("corner_reduction", "min"), ("corner_reduction", None), ("corner_reduction", 1),
])
def test_strict_annotations_reject_coercion_duplicate_scope_and_bounds(field, invalid):
    hints = get_type_hints(SurfaceBrushTools.mesh_sculpt_mask_sample, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints[field]).validate_python(invalid)


def test_maximum_scope_is_valid_and_ordered():
    hints = get_type_hints(SurfaceBrushTools.mesh_sculpt_mask_sample, include_extras=True)
    values = list(range(1024))[::-1]
    assert TypeAdapter(hints["vertex_indices"]).validate_python(values) == values


def test_valid_sampler_call_stays_disabled_until_mesh_toolset_is_enabled():
    from mcp import Client

    from mcp_server.server import build_runtime

    class ForbiddenClient:
        async def request(self, *_args, **_kwargs):
            raise AssertionError("Disabled tools must not contact Blender")

    async def scenario():
        runtime = build_runtime(client=ForbiddenClient())  # type: ignore[arg-type]
        async with Client(runtime.server) as client:
            result = await client.call_tool(METHOD, {"object_name":"Sculpt", "uv_layer":"UVMap",
                "vertex_indices":[0], "image_name":"PaintedMask", "corner_reduction":"MIN"})
            assert result.is_error
            assert json.loads(result.content[0].text)["code"] == "TOOLSET_DISABLED"
            assert runtime.registry.enabled_toolsets == ("core",)

    asyncio.run(scenario())


def test_official_sdk_requires_explicit_seam_policy_and_validates_before_forwarding():
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
                assert schema["required"] == ["object_name", "uv_layer", "vertex_indices", "image_name", "corner_reduction"]
                fields = schema["properties"]
                assert fields["channel"]["default"] == "R" and fields["invert"]["default"] is False
                assert fields["vertex_indices"]["minItems"] == 1 and fields["vertex_indices"]["maxItems"] == 1024
                assert fields["vertex_indices"]["uniqueItems"] is True
                assert fields["vertex_indices"]["items"]["type"] == "integer"
                assert fields["vertex_indices"]["items"]["exclusiveMaximum"] == 100_000
                assert fields["corner_reduction"]["enum"] == ["MIN", "MAX", "MEAN"]
                values = {"object_name": "Sculpt", "uv_layer": "UVMap", "vertex_indices": [2,0],
                          "image_name": "PaintedMask", "corner_reduction": "MAX"}
                missing = {k:v for k,v in values.items() if k != "corner_reduction"}
                assert (await client.call_tool(METHOD, missing)).is_error
                for invalid in ({"vertex_indices": []}, {"vertex_indices": [0]*1025}, {"vertex_indices": [0,0]},
                                {"vertex_indices": [True]}, {"vertex_indices": [1.0]}, {"vertex_indices": ["1"]},
                                {"vertex_indices": [-1]}, {"vertex_indices": [100_000]},
                                {"image_name": ""}, {"uv_layer": "bad\nname"}, {"object_name": 1},
                                {"channel": "r"}, {"invert": 1}, {"corner_reduction": "min"}):
                    assert (await client.call_tool(METHOD, {**values, **invalid})).is_error
                assert not calls
                assert not (await client.call_tool(METHOD, values)).is_error
                assert not (await client.call_tool(METHOD, {**values, "channel":"A", "invert":True, "corner_reduction":"MEAN"})).is_error
                assert calls == [(METHOD, {**values, "channel":"R", "invert":False}),
                                 (METHOD, {**values, "channel":"A", "invert":True, "corner_reduction":"MEAN"})]
        finally:
            await runtime.client.close()

    asyncio.run(scenario())
