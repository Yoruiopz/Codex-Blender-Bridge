"""Strict persistent cinematic-variant wrappers; no Blender imports."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StrictInt, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

TOOL_DATA = (
    ("scene.variant.inspect", "Inspect bounded inert Scene cinematic records and exact library CAS.", False, ("INSPECT_SCENE",)),
    ("scene.variant.capture", "Store exact current camera/light controls and protected static scene proof as Scene JSON without saving.", True, ("INSPECT_SCENE", "EDIT_SCENE")),
    ("scene.variant.preview", "Render matched current/candidate images and restore owned settings; issue a fresh session-bound apply token.", True, ("INSPECT_SCENE", "EDIT_SCENE", "TRANSFORM_OBJECTS", "CAPTURE_VIEWPORT")),
    ("scene.variant.apply", "Apply an exact fresh preview with live consent, ownership and protected-state CAS checks.", True, ("INSPECT_SCENE", "EDIT_SCENE", "TRANSFORM_OBJECTS")),
)
TOOL_NAMES = tuple(row[0] for row in TOOL_DATA)
Name = Annotated[StrictStr, Field(min_length=1, max_length=256)]
Label = Annotated[StrictStr, Field(min_length=1, max_length=80)]
Revision = Annotated[StrictInt, Field(ge=0, le=1_000_000_000)]
Fingerprint = Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
VariantID = Annotated[StrictStr, Field(pattern="^v_[0-9a-f]{32}$")]
Lights = Annotated[list[Name], Field(min_length=1, max_length=8)]
Protected = Annotated[list[Name], Field(min_length=1, max_length=32)]


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="scene_edit", description=description, modifying=modifying,
        required_permissions=permissions) for name, description, modifying, permissions in TOOL_DATA)


class SceneVariantTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def scene_variant_inspect(self) -> Any:
        """Inspect at most eight inert Scene JSON variants. Data contains no permission authority or durable native identity; fresh preview is required after reopening."""
        return await self.registry.call("scene.variant.inspect")

    async def scene_variant_capture(self, label: Label, camera_object: Name, light_objects: Lights,
        protected_objects: Protected, expected_library_revision: Revision,
        expected_library_fingerprint: Fingerprint, variant_id: VariantID | None = None) -> Any:
        """Capture actual current controls for one independent camera and 1-8 lights. Explicitly list every scene mesh (1-32), including shared-data consumers. Only bounded unanimated unmodified base meshes and reviewed procedural shaders in a static EEVEE scene are supported. Replacement needs the existing variant_id and exact current library revision/raw-JSON fingerprint. Persists Scene metadata only; separate authorized project saving is required for disk durability."""
        values = {"label": label, "camera_object": camera_object, "light_objects": light_objects,
            "protected_objects": protected_objects, "expected_library_revision": expected_library_revision,
            "expected_library_fingerprint": expected_library_fingerprint}
        if variant_id is not None:
            values["variant_id"] = variant_id
        return await self.registry.call("scene.variant.capture", values)

    async def scene_variant_preview(self, variant_id: VariantID, expected_library_revision: Revision,
        expected_library_fingerprint: Fingerprint) -> Any:
        """MODIFYING: temporarily apply the exact named camera/light state, render current/candidate at matched 384x256 PNG/16-sample settings, and restore owned controls, active camera and overwritten render settings. Protected asset/world/render/time/session/selection/JSON and live permissions are checked around writes and native calls. Returns two temporary artifact proofs and a single-use fresh apply token. Render Result is replaced; native undo does not delete PNGs. Native rendering is uninterruptible until return. A changed context, replaced output or revoked consent can refuse compensation and require explicit native recovery. Review both images before applying."""
        return await self.registry.call("scene.variant.preview", {"variant_id": variant_id,
            "expected_library_revision": expected_library_revision,
            "expected_library_fingerprint": expected_library_fingerprint})

    async def scene_variant_apply(self, variant_id: VariantID, expected_library_revision: Revision,
        expected_library_fingerprint: Fingerprint, expected_fingerprint: Fingerprint) -> Any:
        """Apply the current fresh preview exactly once, with one logical checkpoint and guarded compensation. Exact name/data/type/rotation-mode rebinding is mandatory; changed protected data or render/world/time profile requires a newly reviewed variant. Scene-stored JSON never grants permissions. Reinspect numeric camera/light state and review visual evidence; no project save occurs."""
        return await self.registry.call("scene.variant.apply", {"variant_id": variant_id,
            "expected_library_revision": expected_library_revision,
            "expected_library_fingerprint": expected_library_fingerprint,
            "expected_fingerprint": expected_fingerprint})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, getattr(self, "scene_variant_"+name.rsplit(".", 1)[1]),
            getattr(self, "scene_variant_"+name.rsplit(".", 1)[1]).__doc__ or "") for name in TOOL_NAMES)
