from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.geometry_preview import GeometryPreviewTools


@pytest.mark.parametrize("value", [True, 0, 121, 1.5, "60"])
def test_geometry_deadline_schema_refuses_coercion(value):
    hints = get_type_hints(GeometryPreviewTools.preview_geometry_start, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints["time_limit_seconds"]).validate_python(value)


@pytest.mark.parametrize("value", [None, "", "selected", 1, "geometry_preview_" + "z" * 32])
def test_geometry_handle_is_typed_and_exact(value):
    hints = get_type_hints(GeometryPreviewTools.preview_geometry_image, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints["preview_id"]).validate_python(value)


def test_geometry_name_schema_is_explicit_and_bounded():
    hints = get_type_hints(GeometryPreviewTools.preview_geometry_start, include_extras=True)
    adapter = TypeAdapter(hints["object_name"])
    assert adapter.validate_python("Named Object") == "Named Object"
    for value in (None, "", True, 7, "x" * 64):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


@pytest.mark.parametrize("bad", ["base64", "hash", "not_png", "shape", "oversize"])
def test_geometry_image_wrapper_refuses_malformed_transport_payload(bad):
    import asyncio
    import base64
    import hashlib
    from types import SimpleNamespace as NS

    from mcp_server.errors import BridgeError

    raw = b"\x89PNG\r\n\x1a\nmodel"
    value = {
        "png_base64": base64.b64encode(raw).decode(),
        "image_sha256": hashlib.sha256(raw).hexdigest(),
    }
    if bad == "base64":
        value["png_base64"] = "%%"
    elif bad == "hash":
        value["image_sha256"] = "0" * 64
    elif bad == "not_png":
        value["png_base64"] = base64.b64encode(b"other").decode()
    elif bad == "shape":
        value = []
    else:
        value["png_base64"] = "A" * 2796205

    async def call(*_args, **_kwargs):
        return value

    tool = GeometryPreviewTools(NS(call=call))
    with pytest.raises(BridgeError):
        asyncio.run(tool.preview_geometry_image("geometry_preview_" + "a" * 32))


def test_geometry_image_wrapper_emits_image_content_without_reading_paths(monkeypatch):
    import asyncio
    import base64
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace as NS

    import mcp.types
    from test_geometry_preview import png

    raw = png()
    value = {
        "png_base64": base64.b64encode(raw).decode(),
        "image_sha256": hashlib.sha256(raw).hexdigest(),
        "scene_changed": False,
        "width": 128,
        "height": 128,
    }

    async def call(*_args, **_kwargs):
        return value

    monkeypatch.setattr(
        Path, "read_bytes", lambda *_: pytest.fail("MCP image wrapper read a local path")
    )
    result = asyncio.run(
        GeometryPreviewTools(NS(call=call)).preview_geometry_image("geometry_preview_" + "a" * 32)
    )
    assert isinstance(result, mcp.types.CallToolResult)
    assert result.content[1].type == "image" and result.content[1].data == value["png_base64"]
    import json

    assert "png_base64" not in json.loads(result.content[0].text)
