"""Typed MCP contract for explicit artist target-channel observations."""

from __future__ import annotations

import asyncio
import importlib
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools import catalog
from mcp_server.tools.task_plan import TaskPlanTools, load_definitions

METHOD = "task.plan.verify_transform"
RECEIPT = "step_receipt_" + "a1" * 16
VALID = {"step_id": "revise", "receipt_id": RECEIPT, "expected_revision": 3}


def test_binding_and_core_read_only_metadata_agree():
    definition, = [item for item in load_definitions() if item.name == METHOD]
    binding, = [item for item in TaskPlanTools(None).bindings() if item.name == METHOD]
    catalog_definition, = [item for item in catalog.CORE_DEFINITIONS if item.name == METHOD]
    assert binding.handler.__name__ == "task_plan_verify_transform"
    for candidate in (definition, catalog_definition):
        assert candidate.toolset == "core" and candidate.modifying is False
        assert candidate.required_permissions == ("INSPECT_SCENE",)
    assert METHOD not in catalog.DESTRUCTIVE_TOOL_NAMES
    assert METHOD not in catalog.MODIFYING_TOOL_NAMES


def test_addon_registration_matches_mcp_and_has_no_history_or_checkpoint(addon_package):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    plans = importlib.import_module(f"{addon_package}.tools.task_plan")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    registry = registry_module.ToolRegistry(enabled_toolsets=("core",))
    plans.register_tools(registry)
    spec = registry.get(METHOD)
    assert spec.toolset == "core" and not spec.modifies and spec.remote
    assert spec.permissions == frozenset({permissions.Permission.INSPECT_SCENE})
    assert not spec.automatic_checkpoint and not spec.batchable and not spec.record_history
    context = registry_module.ToolContext(state, permissions.PermissionManager(lambda: {}), registry, None)
    with pytest.raises(Exception) as caught:
        registry.dispatch(METHOD, VALID, context)
    assert caught.value.code == "PERMISSION_DENIED"
    assert getattr(state, "_artist_task_plans", None) is None


def test_wrapper_forwards_only_the_exact_required_provenance():
    calls = []

    class Registry:
        async def call(self, method, values):
            calls.append((method, values))
            return {"observation_id": "observation", "user_goal_verified": False}

    result = asyncio.run(TaskPlanTools(Registry()).task_plan_verify_transform(**VALID))
    assert calls == [(METHOD, VALID)]
    assert result == {"observation_id": "observation", "user_goal_verified": False}


@pytest.mark.parametrize("field,invalid", [
    ("step_id", ""), ("step_id", "x" * 65), ("step_id", "revise\n"),
    ("step_id", "bad name"), ("step_id", "révise"), ("step_id", True),
    ("step_id", 1), ("step_id", ["revise"]), ("step_id", None),
    ("receipt_id", ""), ("receipt_id", "a" * 32),
    ("receipt_id", "step_receipt_" + "a" * 31), ("receipt_id", "step_receipt_" + "a" * 33),
    ("receipt_id", "step_receipt_" + "A" * 32), ("receipt_id", RECEIPT + "\n"),
    ("receipt_id", 1), ("receipt_id", False), ("receipt_id", None),
    ("expected_revision", 0), ("expected_revision", -1), ("expected_revision", 1_000_000_001),
    ("expected_revision", True), ("expected_revision", False), ("expected_revision", 3.),
    ("expected_revision", "3"), ("expected_revision", None),
])
def test_annotations_reject_coercion_and_invalid_receipt_provenance(field, invalid):
    hints = get_type_hints(TaskPlanTools.task_plan_verify_transform, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints[field]).validate_python(invalid)


def test_native_identifier_and_revision_boundaries_are_representable():
    hints = get_type_hints(TaskPlanTools.task_plan_verify_transform, include_extras=True)
    assert TypeAdapter(hints["step_id"]).validate_python("A_0-" * 16) == "A_0-" * 16
    assert TypeAdapter(hints["receipt_id"]).validate_python(RECEIPT) == RECEIPT
    for revision in (1, 1_000_000_000):
        assert TypeAdapter(hints["expected_revision"]).validate_python(revision) == revision


def test_official_sdk_schema_and_validation_run_before_forwarding():
    from mcp import Client

    from mcp_server.server import build_runtime

    async def scenario():
        runtime = build_runtime()
        calls = []

        async def forward(method, values):
            calls.append((method, values))
            return {"target_observation": {"status": "channels_match", "user_goal_verified": False}}

        runtime.registry.call = forward
        try:
            async with Client(runtime.server) as client:
                tool, = [tool for tool in (await client.list_tools()).tools if tool.name == METHOD]
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                schema = tool.input_schema
                assert schema["required"] == ["step_id", "receipt_id", "expected_revision"]
                fields = schema["properties"]
                assert fields["step_id"]["type"] == fields["receipt_id"]["type"] == "string"
                assert fields["step_id"]["minLength"] == 1 and fields["step_id"]["maxLength"] == 64
                assert fields["receipt_id"]["minLength"] == fields["receipt_id"]["maxLength"] == 45
                assert fields["receipt_id"]["pattern"] == "^step_receipt_[a-f0-9]{32}$"
                assert fields["expected_revision"]["type"] == "integer"
                assert fields["expected_revision"]["minimum"] == 1
                assert fields["expected_revision"]["maximum"] == 1_000_000_000
                for missing in VALID:
                    assert (await client.call_tool(METHOD, {k: v for k, v in VALID.items() if k != missing})).is_error
                for invalid in ({"step_id": ""}, {"step_id": "revise\n"}, {"step_id": 1},
                                {"step_id": "x" * 65}, {"receipt_id": "other"},
                                {"receipt_id": "step_receipt_" + "A" * 32}, {"receipt_id": None},
                                {"expected_revision": True}, {"expected_revision": 3.},
                                {"expected_revision": "3"}, {"expected_revision": 0},
                                {"expected_revision": 1_000_000_001}):
                    result = await client.call_tool(METHOD, {**VALID, **invalid})
                    assert result.is_error, invalid
                assert not calls
                assert not (await client.call_tool(METHOD, VALID)).is_error
                assert calls == [(METHOD, VALID)]
                assert runtime.registry.enabled_toolsets == ("core",)
        finally:
            await runtime.client.close()

    asyncio.run(scenario())


def test_valid_core_call_keeps_blender_authoritative_without_extra_toolsets():
    from mcp import Client

    from mcp_server.server import build_runtime

    class StubBlender:
        def __init__(self):
            self.calls = []

        async def request(self, method, values):
            self.calls.append((method, values))
            return {"target_observation": {"status": "channels_differ", "user_goal_verified": False}}

        async def close(self):
            return None

    async def scenario():
        blender = StubBlender()
        runtime = build_runtime(client=blender)  # type: ignore[arg-type]
        async with Client(runtime.server) as client:
            result = await client.call_tool(METHOD, VALID)
            assert not result.is_error
        assert runtime.registry.enabled_toolsets == ("core",)
        assert blender.calls == [(METHOD, VALID)]

    asyncio.run(scenario())
