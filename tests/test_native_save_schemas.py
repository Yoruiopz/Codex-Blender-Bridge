"""Strict public native-save schemas and thin forwarding; no Blender process."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.native_save import PERMISSIONS, NativeSaveTools, load_definitions


def adapter(method, field):
    return TypeAdapter(get_type_hints(getattr(NativeSaveTools, method), include_extras=True)[field])


@pytest.mark.parametrize("method", ["native_save_preview", "native_save_start"])
@pytest.mark.parametrize("field,value", [
    ("mode", "SAVE"), ("mode", True), ("mode", 1), ("mode", None),
    ("overwrite_policy", "REPLACE"), ("overwrite_policy", True),
    ("filepath", ""), ("filepath", True), ("filepath", 1), ("filepath", None),
    ("filepath", "x"*4097),
])
def test_native_save_modes_paths_and_overwrite_fields_are_explicit(method, field, value):
    with pytest.raises(ValidationError):
        adapter(method, field).validate_python(value)


@pytest.mark.parametrize("mode", ["COPY_NEW", "SAVE_CURRENT", "SAVE_AS"])
def test_all_three_modes_have_typed_public_schema(mode):
    for method in ("native_save_preview", "native_save_start"):
        assert adapter(method, "mode").validate_python(mode) == mode


@pytest.mark.parametrize("value", [None, True, "native_save_" + "z"*32, "native_save_" + "a"*31,
                                  "native_save_" + "a"*33, "selected"])
def test_native_save_handle_is_exact(value):
    with pytest.raises(ValidationError):
        adapter("native_save_start", "preview_id").validate_python(value)


@pytest.mark.parametrize("value", [None, True, "A"*64, "a"*63, "a"*65, "z"*64])
def test_native_save_source_fingerprint_is_exact(value):
    with pytest.raises(ValidationError):
        adapter("native_save_start", "expected_fingerprint").validate_python(value)


@pytest.mark.parametrize("value", [True, False, 0, 301, 1.5, "120", None])
def test_native_save_deadline_is_strict_bounded_integer(value):
    with pytest.raises(ValidationError):
        adapter("native_save_start", "time_limit_seconds").validate_python(value)


@pytest.mark.parametrize("value", [None, "loss", (), [True], [1], [None], ["x"*1025], ["x"]*130])
def test_native_save_loss_declarations_are_bounded_strict_array(value):
    with pytest.raises(ValidationError):
        adapter("native_save_start", "accepted_losses").validate_python(value)


def test_native_save_wrappers_forward_exact_values_without_local_paths_or_grant_changes(monkeypatch):
    from pathlib import Path

    calls = []

    async def forward(method, values):
        calls.append((method, values))
        return {"accepted": method.endswith("start")}

    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("MCP read a local file"))
    monkeypatch.setattr(Path, "resolve", lambda *_args, **_kwargs: pytest.fail("MCP resolved a local path"))
    tools = NativeSaveTools(NS(call=forward))
    path = "/approved/project with spaces.blend"
    losses = ["NATIVE_DESTINATION_RACE_NOT_EXCLUDED"]

    async def scenario():
        await tools.native_save_preview("SAVE_AS", path, "NATIVE_NEW_EXPECTED")
        await tools.native_save_start("native_save_" + "a"*32, "b"*64, "SAVE_AS", path,
                                     "NATIVE_NEW_EXPECTED", losses)

    asyncio.run(scenario())
    assert calls == [
        ("project.native_save_preview", {"mode": "SAVE_AS", "filepath": path,
                                         "overwrite_policy": "NATIVE_NEW_EXPECTED"}),
        ("project.native_save_start", {"preview_id": "native_save_"+"a"*32,
            "expected_fingerprint": "b"*64, "mode": "SAVE_AS", "filepath": path,
            "overwrite_policy": "NATIVE_NEW_EXPECTED", "accepted_losses": losses,
            "time_limit_seconds": 120}),
    ]


def test_native_save_metadata_declares_core_mutations_and_all_live_permissions():
    from mcp_server.tools import catalog

    definitions = load_definitions()
    assert {definition.name for definition in definitions} == {
        "project.native_save_preview", "project.native_save_start"}
    for definition in definitions:
        assert definition.toolset == "core" and definition.modifying is True
        assert definition.required_permissions == PERMISSIONS
        assert definition.name in catalog.MODIFYING_TOOL_NAMES
    assert PERMISSIONS == ("INSPECT_SCENE", "SAVE_PROJECT", "ACCESS_EXTERNAL_FILES", "NATIVE_SAVE_EFFECTS")
    assert "project.native_save_start" in catalog.DESTRUCTIVE_TOOL_NAMES
    assert "project.native_save_preview" not in catalog.DESTRUCTIVE_TOOL_NAMES


def test_official_sdk_publishes_exact_required_fields_and_rejects_untyped_arguments():
    from mcp import Client

    from mcp_server.server import build_runtime

    async def scenario():
        runtime = build_runtime()
        calls = []

        async def forward(method, values):
            calls.append((method, values))
            return {"accepted": True}

        runtime.registry.call = forward
        async with Client(runtime.server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            for name, required in (
                ("project.native_save_preview", ["mode", "filepath", "overwrite_policy"]),
                ("project.native_save_start", ["preview_id", "expected_fingerprint", "mode", "filepath",
                                               "overwrite_policy", "accepted_losses"]),
            ):
                tool = tools[name]
                assert tool.annotations.read_only_hint is False
                assert tool.input_schema["required"] == required
                assert "armed" not in tool.input_schema["properties"]
                assert "approval_token" not in tool.input_schema["properties"]
            common = {"mode": "COPY_NEW", "filepath": "/approved/a.blend", "overwrite_policy": "NO_CLOBBER"}
            start = {**common, "preview_id": "native_save_"+"a"*32,
                     "expected_fingerprint": "b"*64, "accepted_losses": []}
            assert (await client.call_tool("project.native_save_preview", {**common, "filepath": True})).is_error
            for invalid in (True, "120", 0, 301):
                assert (await client.call_tool("project.native_save_start", {**start, "time_limit_seconds": invalid})).is_error
            assert not calls
            assert not (await client.call_tool("project.native_save_preview", common)).is_error
            assert not (await client.call_tool("project.native_save_start", start)).is_error
            assert [method for method, _ in calls] == ["project.native_save_preview", "project.native_save_start"]

    asyncio.run(scenario())
