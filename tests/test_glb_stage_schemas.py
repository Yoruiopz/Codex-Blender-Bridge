"""Private candidate GLB wrappers: strict wire shapes, no Blender or file actions."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.glb_stage import (
    CREATE,
    INSPECT,
    PUBLISH,
    READ,
    TOOL_NAMES,
    GLBStageTools,
    load_definitions,
)

LOSSES = ["VERTEX_SPLITS", "AXIS_UNIT_CONVERSION", "PBR_MATERIAL_RECONSTRUCTION"]
NORMAL = "NORMAL_STORAGE_QUANTIZATION"
AUTO = "MISSING_NORMALS_USE_GEOMETRIC_AUTO"
VALID_LOSSES = [
    LOSSES,
    [*LOSSES, "UV_ORIGIN_CONVERSION"],
    [*LOSSES, NORMAL],
    [*LOSSES, "UV_ORIGIN_CONVERSION", NORMAL],
    [*LOSSES, NORMAL, AUTO],
    [*LOSSES, "UV_ORIGIN_CONVERSION", NORMAL, AUTO],
]


def adapter(method, field):
    return TypeAdapter(get_type_hints(getattr(GLBStageTools, method), include_extras=True)[field])


@pytest.mark.parametrize("field,value", [
    ("filepath", None), ("filepath", True), ("filepath", 1), ("filepath", ""),
    ("filepath", " "), ("filepath", "x" * 4097), ("filepath", "x\0.glb"),
    ("filepath", "\ud800"), ("collection_name", True), ("collection_name", ""),
    ("collection_name", " "), ("collection_name", "x" * 41),
    ("collection_name", "é" * 21), ("collection_name", "x\x7f"),
    ("overwrite_policy", True), ("overwrite_policy", "REPLACE"),
    ("overwrite_policy", "refuse"), ("overwrite_policy", None),
])
def test_preview_paths_names_and_explicit_no_overwrite_are_strict(field, value):
    with pytest.raises(ValidationError):
        adapter("glb_stage_preview", field).validate_python(value)


@pytest.mark.parametrize("value", [None, True, [], "", "native_save_" + "a" * 32,
                                  "glb_preview_" + "a" * 31, "glb_preview_" + "A" * 32])
def test_exact_preview_id(value):
    with pytest.raises(ValidationError):
        adapter("glb_stage_create_start", "preview_id").validate_python(value)


@pytest.mark.parametrize("value", [None, True, "glb_preview_" + "a" * 32,
                                  "glb_stage_" + "a" * 31, "glb_stage_" + "a" * 33])
def test_exact_retained_stage_id(value):
    with pytest.raises(ValidationError):
        adapter("glb_stage_inspect", "stage_id").validate_python(value)


@pytest.mark.parametrize("value", [None, True, 1, "A" * 64, "a" * 63, "a" * 65, "z" * 64])
def test_fingerprint_is_not_a_boolean_or_loose_string(value):
    with pytest.raises(ValidationError):
        adapter("glb_stage_create_start", "expected_fingerprint").validate_python(value)


@pytest.mark.parametrize("value", [None, True, (), tuple(LOSSES), "losses", [],
                                  [True], [1], LOSSES[:-1], list(reversed(LOSSES)),
                                  [*LOSSES, "UNKNOWN"], [*LOSSES, "UV_ORIGIN_CONVERSION", "UNKNOWN"],
                                  [*LOSSES, LOSSES[0]], [*LOSSES, AUTO],
                                  [*LOSSES, "UV_ORIGIN_CONVERSION", AUTO],
                                  [*LOSSES, NORMAL, "UV_ORIGIN_CONVERSION"],
                                  [*LOSSES, NORMAL, NORMAL], [*LOSSES, NORMAL, AUTO, AUTO],
                                  [*LOSSES, NORMAL, AUTO, "UV_ORIGIN_CONVERSION"],
                                  [*LOSSES, "UV_ORIGIN_CONVERSION", NORMAL, AUTO, NORMAL],
                                  [*LOSSES, NORMAL, True], [*LOSSES, NORMAL, 1],
                                  [*LOSSES, "UV_ORIGIN_CONVERSION", NORMAL, b"AUTO"],
                                  tuple([*LOSSES, NORMAL]), {"losses": [*LOSSES, NORMAL]}])
def test_only_complete_reviewed_loss_lists_are_admitted(value):
    with pytest.raises(ValidationError):
        adapter("glb_stage_create_start", "accepted_losses").validate_python(value)


@pytest.mark.parametrize("value", VALID_LOSSES)
def test_uv_and_normal_notices_have_only_the_six_supported_ordered_shapes(value):
    assert adapter("glb_stage_create_start", "accepted_losses").validate_python(value) == value


@pytest.mark.parametrize("value", VALID_LOSSES)
def test_every_supported_loss_token_is_required_once_in_its_declared_position(value):
    losses = adapter("glb_stage_create_start", "accepted_losses")
    # Complete wire forms remain source-agnostic. Removal of an optional suffix
    # may produce another valid shape, but cannot authorize a source requiring
    # that suffix; Blender must compare the complete actual preview list.
    for index in range(len(value)):
        duplicated = [*value[:index], value[index], *value[index:]]
        with pytest.raises(ValidationError):
            losses.validate_python(duplicated)
    for index in range(len(value) - 1):
        reordered = list(value)
        reordered[index:index + 2] = reversed(reordered[index:index + 2])
        with pytest.raises(ValidationError):
            losses.validate_python(reordered)


def test_wrappers_forward_only_typed_intent_without_path_or_grant_actions(monkeypatch):
    calls = []

    async def forward(method, values):
        calls.append((method, values))
        return {"candidate_wrapper_only": True}

    monkeypatch.setattr(Path, "open", lambda *_a, **_k: pytest.fail("MCP opened a local path"))
    monkeypatch.setattr(Path, "resolve", lambda *_a, **_k: pytest.fail("MCP resolved a local path"))
    tools = GLBStageTools(SimpleNamespace(call=forward))

    async def scenario():
        await tools.glb_stage_preview("/approved/source with spaces.glb", "Imported Asset", "REFUSE")
        await tools.glb_stage_create_start("glb_preview_" + "a" * 32, "b" * 64, LOSSES)
        await tools.glb_stage_inspect("glb_stage_" + "c" * 32)
        await tools.glb_stage_publish_preview("glb_stage_" + "c" * 32, "Destination", "REFUSE")
        await tools.glb_stage_publish_start("glb_stage_" + "c" * 32, "glb_publish_" + "d" * 32,
                                            "e" * 64, "REFUSE", 17)

    asyncio.run(scenario())
    assert calls == [
        ("asset.glb_stage_preview", {"filepath": "/approved/source with spaces.glb",
          "collection_name": "Imported Asset", "overwrite_policy": "REFUSE"}),
        ("asset.glb_stage_create_start", {"preview_id": "glb_preview_" + "a" * 32,
          "expected_fingerprint": "b" * 64, "accepted_losses": LOSSES, "time_limit_seconds": 60}),
        ("asset.glb_stage_inspect", {"stage_id": "glb_stage_" + "c" * 32}),
        ("asset.glb_stage_publish_preview", {"stage_id": "glb_stage_" + "c" * 32,
          "destination_scene_name": "Destination", "overwrite_policy": "REFUSE"}),
        ("asset.glb_stage_publish_start", {"stage_id": "glb_stage_" + "c" * 32,
          "publish_preview_id": "glb_publish_" + "d" * 32, "expected_fingerprint": "e" * 64,
          "overwrite_policy": "REFUSE", "time_limit_seconds": 17}),
    ]


def test_private_candidate_metadata_bindings_and_permissions_are_registered_exactly():
    from mcp_server.server import build_runtime
    from mcp_server.tools import catalog, iter_bindings

    definitions = load_definitions()
    assert tuple(row.name for row in definitions) == TOOL_NAMES
    assert all(row.toolset == "asset_delivery" for row in definitions)
    assert [row.modifying for row in definitions] == [False, True, False, False, True]
    assert [row.required_permissions for row in definitions] == [READ, CREATE, INSPECT, INSPECT, PUBLISH]
    assert "SAVE_PROJECT" not in CREATE and "DELETE_OBJECTS" not in CREATE
    assert set(TOOL_NAMES) & set(catalog.MODIFYING_TOOL_NAMES) == {
        "asset.glb_stage_create_start", "asset.glb_stage_publish_start"}
    assert all("SAVE_PROJECT" not in row.required_permissions and
               "DELETE_OBJECTS" not in row.required_permissions for row in definitions)
    assert {row.name for row in catalog.load_asset_delivery_definitions()} >= set(TOOL_NAMES)
    runtime = build_runtime()
    bindings = {binding.name: binding for binding in iter_bindings(runtime.registry)}
    assert set(TOOL_NAMES) <= set(bindings)
    assert "asset.glb_stage_create" not in bindings
    assert all("UNQUALIFIED" in bindings[name].description for name in TOOL_NAMES)


def test_official_sdk_validates_candidate_wrappers_in_an_isolated_test_server():
    from mcp import Client

    from mcp_server.server import _load_server_class

    calls = []

    async def forward(method, values):
        calls.append((method, values))
        return {"wrapper_validated": True}

    server = _load_server_class()("private candidate GLB schema model")
    for binding in GLBStageTools(SimpleNamespace(call=forward)).bindings():
        server.tool(name=binding.name, description=binding.description)(binding.handler)

    async def scenario():
        async with Client(server) as client:
            listed = {row.name: row for row in (await client.list_tools()).tools}
            assert set(listed) == set(TOOL_NAMES)
            for name, required in (
                ("asset.glb_stage_preview", ["filepath", "collection_name", "overwrite_policy"]),
                ("asset.glb_stage_create_start", ["preview_id", "expected_fingerprint", "accepted_losses"]),
                ("asset.glb_stage_inspect", ["stage_id"]),
                ("asset.glb_stage_publish_preview", ["stage_id", "destination_scene_name", "overwrite_policy"]),
                ("asset.glb_stage_publish_start", ["stage_id", "publish_preview_id", "expected_fingerprint", "overwrite_policy"]),
            ):
                assert listed[name].input_schema["required"] == required
            for name in ("asset.glb_stage_create_start", "asset.glb_stage_publish_start"):
                deadline = listed[name].input_schema["properties"]["time_limit_seconds"]
                assert (deadline["type"], deadline["minimum"], deadline["maximum"], deadline["default"]) == ("integer", 1, 300, 60)
            preview = {"filepath": "/approved/asset.glb", "collection_name": "Asset",
                       "overwrite_policy": "REFUSE"}
            create = {"preview_id": "glb_preview_" + "a" * 32,
                      "expected_fingerprint": "b" * 64, "accepted_losses": LOSSES}
            publish = {"stage_id": "glb_stage_" + "c" * 32,
                       "publish_preview_id": "glb_publish_" + "d" * 32,
                       "expected_fingerprint": "e" * 64, "overwrite_policy": "REFUSE"}
            invalid = [
                ("asset.glb_stage_preview", {**preview, "filepath": True}),
                ("asset.glb_stage_preview", {**preview, "overwrite_policy": "REPLACE"}),
                ("asset.glb_stage_create_start", {**create, "accepted_losses": [*LOSSES, "UNKNOWN"]}),
                ("asset.glb_stage_create_start", {**create, "expected_fingerprint": True}),
                ("asset.glb_stage_create_start", {**create, "accepted_losses": [*LOSSES, AUTO]}),
                ("asset.glb_stage_create_start", {**create, "accepted_losses": [*LOSSES, NORMAL, "UV_ORIGIN_CONVERSION"]}),
                ("asset.glb_stage_create_start", {**create, "accepted_losses": [*LOSSES, NORMAL, AUTO, AUTO]}),
                ("asset.glb_stage_inspect", {"stage_id": "Cube"}),
            ]
            invalid.extend((name, {**values, "time_limit_seconds": deadline})
                           for name, values in (("asset.glb_stage_create_start", create),
                                                ("asset.glb_stage_publish_start", publish))
                           for deadline in (True, False, 0, 301, 1.0, "60", None))
            invalid.extend([
                ("asset.glb_stage_publish_start", {**publish, "publish_preview_id": "glb_preview_" + "d" * 32}),
                ("asset.glb_stage_publish_start", {**publish, "overwrite_policy": "REPLACE"}),
                ("asset.glb_stage_publish_preview", {"stage_id": "glb_stage_" + "c" * 32,
                  "destination_scene_name": True, "overwrite_policy": "REFUSE"}),
            ])
            for name, values in invalid:
                assert (await client.call_tool(name, values)).is_error
            assert not calls
            assert not (await client.call_tool("asset.glb_stage_preview", preview)).is_error
            for losses in VALID_LOSSES:
                assert not (await client.call_tool("asset.glb_stage_create_start", {**create, "accepted_losses": losses})).is_error
            assert not (await client.call_tool("asset.glb_stage_inspect", {"stage_id": "glb_stage_" + "c" * 32})).is_error
            assert not (await client.call_tool("asset.glb_stage_publish_preview", {
                "stage_id": "glb_stage_" + "c" * 32, "destination_scene_name": "Destination",
                "overwrite_policy": "REFUSE"})).is_error
            assert not (await client.call_tool("asset.glb_stage_publish_start", publish)).is_error
            assert len(calls) == 10
            assert calls[-1][1]["time_limit_seconds"] == 60
            assert [params["accepted_losses"] for name, params in calls if name == "asset.glb_stage_create_start"] == VALID_LOSSES

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["glb_stage_create_start", "glb_stage_publish_start"])
@pytest.mark.parametrize("value", [None, True, False, 0, -1, 301, 1.0, "60"])
def test_job_time_limits_are_strict_bounded_integers(method, value):
    with pytest.raises(ValidationError):
        adapter(method, "time_limit_seconds").validate_python(value)


@pytest.mark.parametrize("value", [1, 60, 300])
@pytest.mark.parametrize("method", ["glb_stage_create_start", "glb_stage_publish_start"])
def test_job_time_limit_boundaries(method, value):
    assert adapter(method, "time_limit_seconds").validate_python(value) == value


@pytest.mark.parametrize("value", [None, True, "glb_preview_" + "a" * 32,
                                  "glb_publish_" + "A" * 32, "glb_publish_" + "a" * 31,
                                  "glb_publish_" + "a" * 33])
def test_publish_preview_id_has_its_own_exact_namespace(value):
    with pytest.raises(ValidationError):
        adapter("glb_stage_publish_start", "publish_preview_id").validate_python(value)


@pytest.mark.parametrize("method", ["glb_stage_publish_preview", "glb_stage_publish_start"])
@pytest.mark.parametrize("value", [None, True, "REPLACE", "refuse"])
def test_publication_requires_explicit_refuse_policy(method, value):
    with pytest.raises(ValidationError):
        adapter(method, "overwrite_policy").validate_python(value)


@pytest.mark.parametrize("value", [None, True, "", " ", "x" * 41, "é" * 21, "x\0"])
def test_publication_destination_names_are_strict_and_byte_bounded(value):
    with pytest.raises(ValidationError):
        adapter("glb_stage_publish_preview", "destination_scene_name").validate_python(value)
