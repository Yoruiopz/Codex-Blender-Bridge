from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from collections.abc import Mapping
from typing import Any

import pytest

from mcp_server.errors import BridgeError, ToolsetDisabledError
from mcp_server.schemas import JsonValue
from mcp_server.tool_registry import ToolDefinition, ToolRegistry, remote_tool


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(
        self, method: str, params: Mapping[str, Any] | None = None, **_: Any
    ) -> JsonValue:
        copied = dict(params or {})
        self.calls.append((method, copied))
        return {"method": method, "params": copied}


def test_core_tool_forwards_structured_request() -> None:
    client = RecordingClient()
    registry = ToolRegistry(client)
    registry.register_core([remote_tool("scene.inspect")])

    result = asyncio.run(registry.call("scene.inspect", include_hidden=False))

    assert result == {
        "method": "scene.inspect",
        "params": {"include_hidden": False},
    }
    assert client.calls == [("scene.inspect", {"include_hidden": False})]


def test_domain_toolset_is_lazy_and_disabled_by_default() -> None:
    client = RecordingClient()
    registry = ToolRegistry(client)
    load_count = 0

    def load_mesh() -> tuple[ToolDefinition, ...]:
        nonlocal load_count
        load_count += 1
        return (remote_tool("mesh.inspect", toolset="mesh"),)

    registry.register_toolset("mesh", load_mesh, tools=("mesh.inspect",))

    assert load_count == 0
    with pytest.raises(ToolsetDisabledError):
        asyncio.run(registry.call("mesh.inspect", object_name="Cube"))
    assert load_count == 0

    enabled = registry.enable("mesh")
    assert enabled["changed"] is True
    assert load_count == 1
    assert asyncio.run(registry.call("mesh.inspect"))["method"] == "mesh.inspect"

    registry.disable("mesh")
    with pytest.raises(ToolsetDisabledError):
        asyncio.run(registry.call("mesh.inspect"))

    registry.enable("mesh")
    assert load_count == 1


def test_toolset_control_synchronizes_blender_and_local_state() -> None:
    client = RecordingClient()
    registry = ToolRegistry(client)
    registry.register_toolset(
        "mesh",
        lambda: (remote_tool("mesh.inspect", toolset="mesh"),),
        tools=("mesh.inspect",),
    )

    enabled = asyncio.run(registry.call("toolsets.enable", name="mesh"))

    assert enabled["scope"] == "mcp_and_blender"
    assert registry.enabled_toolsets == ("core", "mesh")
    assert client.calls == [("toolsets.enable", {"name": "mesh"})]

    disabled = asyncio.run(registry.call("toolsets.disable", name="mesh"))
    assert disabled["changed"] is True
    assert registry.enabled_toolsets == ("core",)
    assert client.calls[-1] == ("toolsets.disable", {"name": "mesh"})


def test_loader_must_match_declared_tools() -> None:
    registry = ToolRegistry(RecordingClient())
    registry.register_toolset(
        "mesh",
        lambda: (remote_tool("mesh.other", toolset="mesh"),),
        tools=("mesh.inspect",),
    )

    with pytest.raises(ValueError, match="disagrees"):
        registry.enable("mesh")


def test_core_cannot_be_disabled() -> None:
    registry = ToolRegistry(RecordingClient())

    with pytest.raises(BridgeError) as caught:
        registry.disable("core")

    assert caught.value.code == "INVALID_ARGUMENT"


def test_non_json_tool_result_is_rejected() -> None:
    async def invalid_handler(_: RecordingClient, __: Mapping[str, JsonValue]) -> Any:
        return object()

    registry = ToolRegistry(RecordingClient())
    registry.register_core(
        [
            ToolDefinition(
                name="scene.invalid",
                description="test",
                handler=invalid_handler,
            )
        ]
    )

    with pytest.raises(BridgeError) as caught:
        asyncio.run(registry.call("scene.invalid"))

    assert caught.value.code == "PROTOCOL_ERROR"


@pytest.mark.parametrize("all_enabled", [False, True])
def test_public_addon_surface_matches_published_090_and_rejects_private_glb_rpc(
    addon_package, monkeypatch, all_enabled
):
    runtime_module = importlib.import_module(addon_package + ".runtime")
    states = importlib.import_module(addon_package + ".state")
    protocol = importlib.import_module(addon_package + ".protocol")
    monkeypatch.setattr(runtime_module, "get_state", states.BridgeState)
    runtime = runtime_module.BridgeRuntime()
    names = runtime.registry.list_tools()
    public_names = tuple(name for name in names if runtime.registry.get(name).remote)
    # Published v0.9.0 source d756b68: exact public names, independent of enablement.
    assert len(public_names) == 270
    assert hashlib.sha256(("\n".join(public_names) + "\n").encode()).hexdigest() == (
        "1cb16ea5e7320962bc0be5d886bf76724e59ed548e9bc2808b5bff7e3d3b9c1e"
    )
    assert set(names) - set(public_names) == {"checkpoint.restore_last", "jobs._scene_turn"}
    if all_enabled:
        for toolset in runtime.registry.describe()["toolsets"]:
            runtime.registry.enable_toolset(toolset["name"])
    else:
        assert runtime.registry.enabled_toolsets == ("core",)
    calls = []

    def forbidden(label):
        def invoke(*_args, **_kwargs):
            calls.append(label)
            pytest.fail("unknown private GLB RPC entered " + label)
        return invoke

    monkeypatch.setattr(runtime.permissions, "_source", forbidden("permission provider"))
    for method in ("before_modification", "after_modification", "capture_job_markers"):
        monkeypatch.setattr(runtime.checkpoints, method, forbidden("checkpoint " + method))
    monkeypatch.setattr(runtime.jobs, "start_scene", forbidden("scene job"))
    for method in ("preview", "by_preview", "inspect", "publish_preview", "attach_job"):
        monkeypatch.setattr(runtime.glb_stage, method, forbidden("GLB service " + method))

    for index, method in enumerate((
        "asset.glb_stage_preview", "asset.glb_stage_create_start", "asset.glb_stage_inspect",
        "asset.glb_stage_publish_preview", "asset.glb_stage_publish_start",
    )):
        assert method not in names
        request = protocol.decode_request(json.dumps({
            "id": f"private_glb_{index}", "method": method, "params": {}, "protocol_version": "1.0",
        }) + "\n")
        response = runtime.executor.execute_request(request)
        wire = json.loads(protocol.encode_response(response))
        assert wire["id"] == request.id and wire["ok"] is False
        assert wire["error"]["code"] == "METHOD_NOT_FOUND"
    assert calls == []
    assert runtime.registry.list_tools() == names
    assert runtime.jobs.active is None
    assert runtime.glb_stage._records == {} and runtime.glb_stage.store._records == {}


def test_private_glb_candidates_require_explicit_registration_and_exact_permissions(addon_package):
    runtime = importlib.import_module(addon_package + ".runtime").BridgeRuntime()
    importlib.import_module(addon_package + ".tools.glb_stage").register(runtime.registry)
    required = {
        "asset.glb_stage_preview": {"INSPECT_SCENE", "ACCESS_EXTERNAL_FILES"},
        "asset.glb_stage_create_start": {"INSPECT_SCENE", "ACCESS_EXTERNAL_FILES", "EDIT_SCENE", "TRANSFORM_OBJECTS", "EDIT_MESH", "EDIT_MATERIALS"},
        "asset.glb_stage_inspect": {"INSPECT_SCENE"},
        "asset.glb_stage_publish_preview": {"INSPECT_SCENE"},
        "asset.glb_stage_publish_start": {"INSPECT_SCENE", "EDIT_SCENE", "TRANSFORM_OBJECTS", "EDIT_MESH", "EDIT_MATERIALS"},
    }
    assert "asset_delivery" not in runtime.registry.enabled_toolsets
    for name, permissions in required.items():
        spec = runtime.registry.get(name)
        assert spec.toolset == "asset_delivery" and {p.value for p in spec.permissions} == permissions
        assert "UNQUALIFIED" in spec.description
        if name.endswith("_start"):
            assert spec.modifies and spec.exclusive_mutation and spec.checkpoint_owns_finalization
            assert not spec.batchable and not spec.automatic_checkpoint
            assert spec.checkpoint_admission_factory is not None
        else:
            assert not spec.modifies
