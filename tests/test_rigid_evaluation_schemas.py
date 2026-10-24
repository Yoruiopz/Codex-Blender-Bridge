from __future__ import annotations

import asyncio
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.rigid_body import (
    DESTRUCTIVE_TOOL_NAMES,
    TOOL_NAMES,
    RigidBodyTools,
    load_definitions,
)

PREVIEW = "rigid_body.evaluate_preview"
START = "rigid_body.evaluate_job_start"
FINGERPRINT = "a" * 64


def test_evaluation_definitions_and_bindings_keep_simulation_authority():
    definitions = {definition.name: definition for definition in load_definitions()}
    bindings = {binding.name: binding for binding in RigidBodyTools(None).bindings()}
    assert set(definitions) == set(bindings) == set(TOOL_NAMES)
    assert definitions[PREVIEW].toolset == definitions[START].toolset == "simulation"
    assert definitions[PREVIEW].required_permissions == ("INSPECT_SCENE",)
    assert not definitions[PREVIEW].modifying
    assert definitions[START].modifying
    assert definitions[START].required_permissions == ("INSPECT_SCENE", "EDIT_SCENE", "EDIT_ANIMATION")
    assert START in DESTRUCTIVE_TOOL_NAMES and PREVIEW not in DESTRUCTIVE_TOOL_NAMES


def test_evaluation_wrappers_forward_identical_proposal_and_default_limit():
    calls = []

    class Registry:
        async def call(self, method, values):
            calls.append((method, values))
            return {"forwarded": method}

    async def scenario():
        tools = RigidBodyTools(Registry())
        preview = await tools.rigid_body_evaluate_preview("World", ["Body", "Floor"], [], 1, 3)
        started = await tools.rigid_body_evaluate_job_start("World", ["Body", "Floor"], [], 1, 3,
                                                          FINGERPRINT)
        assert preview == {"forwarded": PREVIEW} and started == {"forwarded": START}
        # Range ordering/span remain Blender-authoritative; the wrapper must not
        # silently clamp or transform a proposal into a different fingerprint.
        await tools.rigid_body_evaluate_preview("World", ["Body"], [], 7, 2, 12)

    asyncio.run(scenario())
    proposal = {"scene_name": "World", "body_names": ["Body", "Floor"], "constraint_names": [],
                "frame_start": 1, "frame_end": 3, "time_limit_seconds": 60}
    assert calls[:2] == [(PREVIEW, proposal), (START, {**proposal, "expected_fingerprint": FINGERPRINT})]
    assert calls[2] == (PREVIEW, {**proposal, "body_names": ["Body"], "frame_start": 7,
                                "frame_end": 2, "time_limit_seconds": 12})


@pytest.mark.parametrize("method", ["rigid_body_evaluate_preview", "rigid_body_evaluate_job_start"])
@pytest.mark.parametrize(("field", "invalid"), [
    ("scene_name", ""), ("scene_name", "x" * 64), ("scene_name", 7),
    ("body_names", []), ("body_names", ["Body"] * 17), ("body_names", [7]),
    ("constraint_names", ["Constraint"]), ("constraint_names", ""),
    ("frame_start", True), ("frame_start", 0), ("frame_end", "3"),
    ("frame_end", 3.0), ("frame_end", 1048575),
    ("time_limit_seconds", True), ("time_limit_seconds", "60"),
    ("time_limit_seconds", 1.0), ("time_limit_seconds", 0), ("time_limit_seconds", 301),
])
def test_evaluation_annotations_refuse_coercion_and_out_of_profile_values(method, field, invalid):
    annotations = get_type_hints(getattr(RigidBodyTools, method), include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(annotations[field]).validate_python(invalid)


@pytest.mark.parametrize("invalid", ["", "a" * 63, "a" * 65, "A" * 64, "z" * 64, 7])
def test_evaluation_start_requires_exact_fingerprint_shape(invalid):
    annotation = get_type_hints(RigidBodyTools.rigid_body_evaluate_job_start,
                                include_extras=True)["expected_fingerprint"]
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python(invalid)


def test_official_sdk_evaluation_schema_and_pre_forward_validation():
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
                preview, start = tools[PREVIEW], tools[START]
                assert preview.annotations.read_only_hint and not start.annotations.read_only_hint
                assert start.annotations.destructive_hint
                for tool in (preview, start):
                    fields = tool.input_schema["properties"]
                    assert fields["body_names"]["minItems"] == 1 and fields["body_names"]["maxItems"] == 16
                    assert fields["constraint_names"]["maxItems"] == 0
                    assert fields["frame_start"]["minimum"] == 1
                    assert fields["frame_end"]["maximum"] == 1048574
                    assert fields["time_limit_seconds"] == {
                        "default": 60, "maximum": 300, "minimum": 1,
                        "title": "Time Limit Seconds", "type": "integer"}
                    assert tool.input_schema["required"][:5] == [
                        "scene_name", "body_names", "constraint_names", "frame_start", "frame_end"]
                assert start.input_schema["required"][-1] == "expected_fingerprint"
                assert start.input_schema["properties"]["expected_fingerprint"]["pattern"] == "^[0-9a-f]{64}$"
                proposal = {"scene_name": "World", "body_names": ["Body"], "constraint_names": [],
                            "frame_start": 1, "frame_end": 3}
                for method in (PREVIEW, START):
                    values = proposal if method == PREVIEW else {**proposal, "expected_fingerprint": FINGERPRINT}
                    for changed in ({"constraint_names": ["Constraint"]}, {"time_limit_seconds": True},
                                    {"frame_end": "3"}):
                        result = await client.call_tool(method, {**values, **changed})
                        assert result.is_error
                    result = await client.call_tool(method, values)
                    assert not result.is_error
                assert calls == [(PREVIEW, {**proposal, "time_limit_seconds": 60}),
                                 (START, {**proposal, "expected_fingerprint": FINGERPRINT,
                                          "time_limit_seconds": 60})]
        finally:
            await runtime.client.close()

    asyncio.run(scenario())
