"""Private candidate GLB Runtime wrappers; native/installed acceptance is pending."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, StrictInt, StrictStr

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

READ = ("INSPECT_SCENE", "ACCESS_EXTERNAL_FILES")
CREATE = (*READ, "EDIT_SCENE", "TRANSFORM_OBJECTS", "EDIT_MESH", "EDIT_MATERIALS")
INSPECT = ("INSPECT_SCENE",)
PUBLISH = (*INSPECT, "EDIT_SCENE", "TRANSFORM_OBJECTS", "EDIT_MESH", "EDIT_MATERIALS")
TOOL_DATA = (
    ("asset.glb_stage_preview", "Preview new-ID GLB intent with declared logical-preservation read effects; private unqualified candidate.", False, READ),
    ("asset.glb_stage_create_start", "Accept an exact GLB stage preview as a bounded Scene job; private candidate, not completed creation.", True, CREATE),
    ("asset.glb_stage_inspect", "Inspect retained GLB stage facts and explicit unknown effects without cleanup authority.", False, INSPECT),
    ("asset.glb_stage_publish_preview", "Preview exact new-owned stage collection publication into one existing Scene; private candidate.", False, INSPECT),
    ("asset.glb_stage_publish_start", "Accept exact GLB stage publication as a bounded Scene job; private candidate, not completed delivery.", True, PUBLISH),
)
TOOL_NAMES = tuple(row[0] for row in TOOL_DATA)
DESTRUCTIVE_TOOL_NAMES: tuple[str, ...] = ()
CORE_LOSSES = ["VERTEX_SPLITS", "AXIS_UNIT_CONVERSION", "PBR_MATERIAL_RECONSTRUCTION"]
NORMAL_LOSS = "NORMAL_STORAGE_QUANTIZATION"
AUTO_NORMAL_LOSS = "MISSING_NORMALS_USE_GEOMETRIC_AUTO"


def _text(value: str, maximum: int) -> str:
    if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Text must be nonblank and contain no control characters")
    if len(value.encode("utf8")) > maximum:
        raise ValueError("Text exceeds its UTF-8 byte budget")
    return value


def _name(value: str) -> str:
    return _text(value, 40)


def _path(value: str) -> str:
    return _text(value, 4096)


def _losses(values: list[str]) -> list[str]:
    # Wire shape cannot infer source attribute presence. Blender must still
    # require exact equality with its independently planned preview loss list.
    supported = [
        [*CORE_LOSSES, *uv, *normals]
        for uv in ((), ("UV_ORIGIN_CONVERSION",))
        for normals in ((), (NORMAL_LOSS,), (NORMAL_LOSS, AUTO_NORMAL_LOSS))
    ]
    if values not in supported:
        raise ValueError("Repeat the complete ordered preview loss list exactly")
    return values


Name = Annotated[StrictStr, Field(min_length=1, max_length=40), AfterValidator(_name)]
SourcePath = Annotated[StrictStr, Field(min_length=1, max_length=4096), AfterValidator(_path)]
PreviewID = Annotated[StrictStr, Field(pattern=r"^glb_preview_[a-f0-9]{32}$")]
StageID = Annotated[StrictStr, Field(pattern=r"^glb_stage_[a-f0-9]{32}$")]
PublishPreviewID = Annotated[StrictStr, Field(pattern=r"^glb_publish_[a-f0-9]{32}$")]
Fingerprint = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
TimeLimit = Annotated[StrictInt, Field(ge=1, le=300)]
Loss = Literal["VERTEX_SPLITS", "AXIS_UNIT_CONVERSION", "PBR_MATERIAL_RECONSTRUCTION", "UV_ORIGIN_CONVERSION",
               "NORMAL_STORAGE_QUANTIZATION", "MISSING_NORMALS_USE_GEOMETRIC_AUTO"]
Losses = Annotated[list[Loss], Field(min_length=3, max_length=6, strict=True), AfterValidator(_losses)]


def load_definitions() -> tuple[ToolDefinition, ...]:
    """Private candidate metadata; registration does not establish qualification."""
    return tuple(remote_tool(name, toolset="asset_delivery", description=description,
                             modifying=modifies, required_permissions=permissions)
                 for name, description, modifies, permissions in TOOL_DATA)


class GLBStageTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def glb_stage_preview(self, filepath: SourcePath, collection_name: Name,
                                overwrite_policy: Literal["REFUSE"]) -> Any:
        """UNQUALIFIED private candidate: plan complete approved GLB bytes <=8MiB and seal source, losses, new-ID names and intent before allocating Blender IDs. REFUSE only; existing data is never replaced. Logical inspection may perform source-qualified bit-preserving ARRAY COW/unsharing, cache tagging and empty deform-layer observation effects on both builds; hidden storage/cache passivity is not promised. Detached physical headers and fresh schema/storage checks must precede protected Mesh data reads; 5.2 SINGLE refuses until separate authorized preparation. Legacy UV.data optional-storage creation is forbidden. Unsupported source textures, skin, animation and mixed UV presence refuse. Blender owns path/grant/session checks; MCP opens no files or grants. Native/installed acceptance remains pending."""
        return await self.registry.call("asset.glb_stage_preview", {
            "filepath": filepath, "collection_name": collection_name,
            "overwrite_policy": overwrite_policy})

    async def glb_stage_create_start(self, preview_id: PreviewID, expected_fingerprint: Fingerprint,
                                     accepted_losses: Losses, time_limit_seconds: TimeLimit = 60) -> Any:
        """UNQUALIFIED private candidate: accept one exact current preview as a bounded Scene job. Repeat its ordered source-specific losses verbatim; normal quantization and missing-normal geometric AUTO require explicit preview consent. A returned job_id means accepted, not completed; poll jobs.inspect/list and keep the owner connection until terminal. Full current grants and protected/owned CAS precede each bounded synchronous phase and follow every provider or yield; provider-free pure stop/session/lease/source/descriptor checks precede each inner native entry and its first return, with genuine reference escrow first. Stop, revoke, disconnect or deadline blocks later native work but cannot interrupt an active native call or promise rollback. Inspect retained stage_id and partial/unknown effects; no automatic cleanup, deletion, save or durable backup."""
        return await self.registry.call("asset.glb_stage_create_start", {
            "preview_id": preview_id, "expected_fingerprint": expected_fingerprint,
            "accepted_losses": accepted_losses, "time_limit_seconds": time_limit_seconds})

    async def glb_stage_inspect(self, stage_id: StageID) -> Any:
        """UNQUALIFIED private candidate: inspect retained stage facts with current INSPECT_SCENE. Cached or unknown native effects are explicit; a record/token proves neither native ownership nor current authority. Inspection does not read source files, adopt same-name IDs, resume jobs, clean up, delete or save. Stored/authored mathematical world intent is not an evaluated-world guarantee."""
        return await self.registry.call("asset.glb_stage_inspect", {"stage_id": stage_id})

    async def glb_stage_publish_preview(self, stage_id: StageID, destination_scene_name: Name,
                                        overwrite_policy: Literal["REFUSE"]) -> Any:
        """UNQUALIFIED private candidate: preview one Scene-root link using cached completed-stage intent and prefix. Seal only admitted destination header/context, units and exact edge expectations; REFUSE only. No live owned Mesh read, fresh ownership/closure proof or manual-owned-drift check occurs here; publish_start must perform that exact current comparison before linking. Unknown/stale cached records and incompatible destinations refuse. Current profile requires Scene scale_length=1 and a plain active Empty. Protected Mesh reads require detached physical headers and declared bit-preserving ARRAY read effects; 5.2 SINGLE and legacy UV.data optional-storage creation refuse. Header/binding and native qualification remain pending. Preserve rich existing artist data; no clearing, save or export."""
        return await self.registry.call("asset.glb_stage_publish_preview", {
            "stage_id": stage_id, "destination_scene_name": destination_scene_name,
            "overwrite_policy": overwrite_policy})

    async def glb_stage_publish_start(self, stage_id: StageID, publish_preview_id: PublishPreviewID,
                                      expected_fingerprint: Fingerprint,
                                      overwrite_policy: Literal["REFUSE"],
                                      time_limit_seconds: TimeLimit = 60) -> Any:
        """UNQUALIFIED private candidate: consume one exact current publication preview as a bounded Scene job, with fresh authority and exact native comparisons before publication. REFUSE only; no overwrite, destructive cleanup, source write, export or project save. Acceptance is not completion: poll jobs.inspect/list. Stop/revoke/disconnect/deadline prevents later native entries, without inverse writes or restoring manual edits. Inspect retained stage/effect facts on every terminal result. Runtime/native/installed qualification and broader artist delivery remain pending."""
        return await self.registry.call("asset.glb_stage_publish_start", {
            "stage_id": stage_id, "publish_preview_id": publish_preview_id,
            "expected_fingerprint": expected_fingerprint, "overwrite_policy": overwrite_policy,
            "time_limit_seconds": time_limit_seconds})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, method, method.__doc__ or "") for name, method in (
            ("asset.glb_stage_preview", self.glb_stage_preview),
            ("asset.glb_stage_create_start", self.glb_stage_create_start),
            ("asset.glb_stage_inspect", self.glb_stage_inspect),
            ("asset.glb_stage_publish_preview", self.glb_stage_publish_preview),
            ("asset.glb_stage_publish_start", self.glb_stage_publish_start)))
