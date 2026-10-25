"""Typed geometry-preview jobs and image bytes, never arbitrary local paths."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
from typing import Annotated, Any

from pydantic import Field, StrictInt, StrictStr

from ..errors import BridgeError
from ._common import MCPToolBinding, params

TOOL_DATA = (
    (
        "preview.geometry_start",
        "Start one bounded isolated authored-geometry preview job; no source Main or original material appearance is changed.",
        True,
    ),
    (
        "preview.geometry_image",
        "Retrieve a successful fresh geometry-preview PNG from this session; stale/expired handles refuse.",
        False,
    ),
)
PERMISSIONS = ("INSPECT_SCENE", "CAPTURE_VIEWPORT", "ACCESS_EXTERNAL_FILES")


def load_definitions():
    from ..tool_registry import remote_tool

    return tuple(
        remote_tool(
            name, description=description, modifying=modifying, required_permissions=PERMISSIONS
        )
        for name, description, modifying in TOOL_DATA
    )


class GeometryPreviewTools:
    def __init__(self, registry):
        self.registry = registry

    async def preview_geometry_start(
        self,
        object_name: Annotated[StrictStr, Field(min_length=1, max_length=63)],
        time_limit_seconds: Annotated[StrictInt, Field(ge=1, le=120)] = 60,
    ) -> Any:
        """Start a fixed 128px opaque geometry snapshot; poll jobs.inspect then retrieve its preview_id."""
        return await self.registry.call(
            "preview.geometry_start",
            params(object_name=object_name, time_limit_seconds=time_limit_seconds),
        )

    async def preview_geometry_image(
        self, preview_id: Annotated[StrictStr, Field(pattern=r"^geometry_preview_[a-f0-9]{32}$")]
    ) -> Any:
        """Retrieve exact managed PNG bytes after Blender revalidates source and permissions; no local file path is read."""
        result = await self.registry.call("preview.geometry_image", params(preview_id=preview_id))
        if (
            type(result) is not dict
            or type(result.get("png_base64")) is not str
            or len(result["png_base64"]) > 2796204
        ):
            raise BridgeError(
                "OPERATION_FAILED", "Geometry image response exceeded its exact envelope."
            )
        try:
            raw = base64.b64decode(result["png_base64"], validate=True)
        except ValueError as cause:
            raise BridgeError("OPERATION_FAILED", "Geometry image encoding is invalid.") from cause
        if (
            not 8 < len(raw) <= 2 * 1024 * 1024
            or raw[:8] != b"\x89PNG\r\n\x1a\n"
            or hashlib.sha256(raw).hexdigest() != result.get("image_sha256")
        ):
            raise BridgeError("OPERATION_FAILED", "Geometry image identity is invalid.")
        types = importlib.import_module("mcp.types")
        metadata = {key: value for key, value in result.items() if key != "png_base64"}
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text=json.dumps(metadata, allow_nan=False)),
                types.ImageContent(type="image", mimeType="image/png", data=result["png_base64"]),
            ],
            structuredContent=metadata,
        )

    def bindings(self):
        return (
            MCPToolBinding(
                "preview.geometry_start",
                self.preview_geometry_start,
                self.preview_geometry_start.__doc__ or "",
            ),
            MCPToolBinding(
                "preview.geometry_image",
                self.preview_geometry_image,
                self.preview_geometry_image.__doc__ or "",
            ),
        )
