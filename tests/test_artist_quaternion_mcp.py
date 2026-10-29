"""MCP compatibility and strict numeric schemas for authored WXYZ assignments."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import math
import struct
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.errors import BridgeError
from mcp_server.tools import catalog
from mcp_server.tools.task_plan import TaskPlanTools
from mcp_server.tools.transforms import TransformTools

SET = "transform.set"
PREVIEW = "task.plan.preview_transform"
HANDLERS = (TransformTools.transform_set, TaskPlanTools.task_plan_preview_transform)


def test_quaternion_argument_is_optional_and_appended_to_existing_signatures():
    for handler, previous in (
        (HANDLERS[0], ["self", "object_name", "location", "rotation", "scale"]),
        (HANDLERS[1], ["self", "reference_id", "expected_revision", "object_name", "location",
                       "rotation", "scale", "rotation_mode", "step_id"]),
    ):
        signature = inspect.signature(handler)
        assert list(signature.parameters) == [*previous, "rotation_quaternion"]
        assert signature.parameters["rotation_quaternion"].default is None


@pytest.mark.parametrize("handler", HANDLERS, ids=("set", "preview"))
@pytest.mark.parametrize("invalid", [
    [], [1], [1, 0, 0], [1, 0, 0, 0, 0], "1,0,0,0", True, 1,
    {"w": 1, "x": 0, "y": 0, "z": 0}, (1, 0, 0, 0),
    [True, 0, 0, 0], [False, 0, 0, 0], ["1", 0, 0, 0], [None, 0, 0, 0],
    [[1], 0, 0, 0], [float("nan"), 0, 0, 0], [float("inf"), 0, 0, 0],
    [-float("inf"), 0, 0, 0],
])
def test_quaternion_annotations_refuse_wrong_shape_nonfinite_and_coercion(handler, invalid):
    hint = get_type_hints(handler, include_extras=True)["rotation_quaternion"]
    with pytest.raises(ValidationError):
        TypeAdapter(hint).validate_python(invalid)


@pytest.mark.parametrize("handler", HANDLERS, ids=("set", "preview"))
def test_schema_preserves_finite_wxyz_signs_and_leaves_profile_validation_to_blender(handler):
    hint = get_type_hints(handler, include_extras=True)["rotation_quaternion"]
    adapter = TypeAdapter(hint)
    assert adapter.validate_python(None) is None
    assert adapter.validate_python([1, 0, 0, 0]) == [1., 0., 0., 0.]
    raw = [-1., -0., 0., 0.]
    converted = adapter.validate_python(raw)
    assert [struct.pack("!d", value) for value in converted] == [struct.pack("!d", value) for value in raw]
    # Numeric shape validation does not guess Blender's native/ownership profile.
    for values in ([0., 0., 0., 0.], [1., 1e-40, 0., 0.], [1.0000001, 0., 0., 0.]):
        assert adapter.validate_python(values) == values


def test_wrappers_preserve_old_positional_calls_omit_none_and_keep_new_values_raw():
    calls = []

    class Registry:
        async def call(self, method, values):
            calls.append((method, values))
            return values

    async def scenario():
        transforms, plans = TransformTools(Registry()), TaskPlanTools(Registry())
        await transforms.transform_set("Prop", [1., 2., 3.], [.1, .2, .3], [2., 1., 1.])
        await plans.task_plan_preview_transform("ref", 3, "Prop", [1., 2., 3.], [.1, .2, .3],
                                                [2., 1., 1.], "XYZ", "revise")
        await transforms.transform_set("Prop", location=[1., 2., 3.], rotation_quaternion=None)
        await plans.task_plan_preview_transform("ref", 3, location=[1., 2., 3.], rotation_quaternion=None)
        quaternion = [-1., -0., 0., 0.]
        await transforms.transform_set("Prop", rotation_quaternion=quaternion)
        await plans.task_plan_preview_transform("ref", 3, step_id="revise", rotation_quaternion=quaternion)

    asyncio.run(scenario())
    assert calls[:4] == [
        (SET, {"object_name": "Prop", "location": [1., 2., 3.], "rotation": [.1, .2, .3], "scale": [2., 1., 1.]}),
        (PREVIEW, {"reference_id": "ref", "expected_revision": 3, "object_name": "Prop",
                   "location": [1., 2., 3.], "rotation": [.1, .2, .3], "scale": [2., 1., 1.],
                   "rotation_mode": "XYZ", "step_id": "revise"}),
        (SET, {"object_name": "Prop", "location": [1., 2., 3.]}),
        (PREVIEW, {"reference_id": "ref", "expected_revision": 3, "location": [1., 2., 3.]}),
    ]
    assert calls[4] == (SET, {"object_name": "Prop", "rotation_quaternion": [-1., -0., 0., 0.]})
    assert calls[5] == (PREVIEW, {"reference_id": "ref", "expected_revision": 3, "step_id": "revise",
                                "rotation_quaternion": [-1., -0., 0., 0.]})
    assert all(math.copysign(1., values["rotation_quaternion"][1]) == -1. for _, values in calls[4:])


def test_existing_addon_and_mcp_permissions_toolsets_and_modifying_flags_match(addon_package):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry(enabled_toolsets=("core", "objects"))
    for module in ("transforms", "task_plan"):
        importlib.import_module(f"{addon_package}.tools.{module}").register_tools(registry)
    definitions = {definition.name: definition for definition in (*catalog.CORE_DEFINITIONS,
                                                                 *catalog.load_object_definitions())}
    for method, toolset, modifying, permissions in (
        (SET, "objects", True, ("TRANSFORM_OBJECTS",)),
        (PREVIEW, "core", False, ("INSPECT_SCENE",)),
    ):
        definition, spec = definitions[method], registry.get(method)
        assert definition.toolset == spec.toolset == toolset
        assert definition.modifying is modifying and spec.modifies is modifying
        assert definition.required_permissions == permissions
        assert {permission.value for permission in spec.permissions} == set(permissions)
        assert (method in catalog.MODIFYING_TOOL_NAMES) is modifying
        assert method not in catalog.DESTRUCTIVE_TOOL_NAMES


def test_official_sdk_advertises_bounded_optional_quaternion_and_rejects_raw_bool_before_forwarding():
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
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                assert len(tools) == 275
                assert {"preview.geometry_start", "preview.geometry_image"} <= tools.keys()
                assert {"project.native_save_preview", "project.native_save_start"} <= tools.keys()
                for method, required in ((SET, ["object_name"]), (PREVIEW, ["reference_id", "expected_revision"])):
                    tool = tools[method]
                    assert tool.annotations.read_only_hint is (method == PREVIEW)
                    assert tool.annotations.destructive_hint is False
                    schema = tool.input_schema
                    assert schema["required"] == required
                    optional = schema["properties"]["rotation_quaternion"]
                    assert optional["default"] is None
                    array, = [item for item in optional["anyOf"] if item.get("type") == "array"]
                    assert array["minItems"] == array["maxItems"] == 4
                    assert array["items"]["type"] == "number"
                    arguments = {"object_name": "Prop"} if method == SET else {"reference_id": "ref", "expected_revision": 3}
                    for invalid in ([True, 0, 0, 0], [False, 0, 0, 0], ["1", 0, 0, 0],
                                    [None, 0, 0, 0], [], [1, 0, 0], [1, 0, 0, 0, 0]):
                        assert (await client.call_tool(method, {**arguments, "rotation_quaternion": invalid})).is_error
                assert not calls
                quaternion = [-1., -0., 0., 0.]
                for method, arguments in ((SET, {"object_name": "Prop"}),
                                          (PREVIEW, {"reference_id": "ref", "expected_revision": 3, "step_id": "revise"})):
                    assert not (await client.call_tool(method, {**arguments, "rotation_quaternion": quaternion})).is_error
                    assert calls[-1] == (method, {**arguments, "rotation_quaternion": quaternion})
                    assert math.copysign(1., calls[-1][1]["rotation_quaternion"][1]) == -1.
                assert runtime.registry.enabled_toolsets == ("core",)
        finally:
            await runtime.client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["INVALID_ARGUMENT", "NOT_IMPLEMENTED", "PERMISSION_DENIED"])
def test_real_forwarding_keeps_objects_disabled_by_default_and_preserves_blender_errors(code):
    from mcp import Client

    from mcp_server.server import build_runtime

    class Blender:
        def __init__(self):
            self.calls = []

        async def request(self, method, values):
            self.calls.append((method, values))
            raise BridgeError(code, "Blender's authoritative refusal.", context={"authority": "Blender"})

        async def close(self):
            return None

    async def scenario():
        blender = Blender()
        runtime = build_runtime(client=blender)  # type: ignore[arg-type]
        quaternion = [.5, -.5, .5, -.5]
        async with Client(runtime.server) as client:
            arguments = {"object_name": "Prop", "rotation_quaternion": quaternion}
            denied = await client.call_tool(SET, arguments)
            assert denied.is_error and json.loads(denied.content[0].text)["code"] == "TOOLSET_DISABLED"
            assert not blender.calls and runtime.registry.enabled_toolsets == ("core",)
            preview = {"reference_id": "ref", "expected_revision": 3, "rotation_quaternion": quaternion}
            for method, values in ((PREVIEW, preview), (SET, arguments)):
                if method == SET:
                    runtime.registry.enable("objects")
                response = await client.call_tool(method, values)
                assert response.is_error
                assert json.loads(response.content[0].text) == {
                    "code": code, "message": "Blender's authoritative refusal.", "context": {"authority": "Blender"},
                    "retryable": False,
                }
            assert blender.calls == [(PREVIEW, preview), (SET, arguments)]

    asyncio.run(scenario())
