"""Candidate structured stage/publish RPCs; Runtime/native acceptance is pending."""
from __future__ import annotations

from ..errors import invalid_argument
from ..glb_stage_jobs import create_driver, publish_driver
from ..glb_stage_runtime import PUBLISH, READ, WRITE
from ..permissions import Permission
from ..scene_jobs import start_admission
from ..utils import int_param, reject_unknown_params


def _service(context):
    from ..glb_stage_runtime import GLBStageService
    from ..tool_registry import ToolContext
    if type(context) is not ToolContext:
        raise invalid_argument("Canonical Runtime GLB stage context is unavailable.")
    if type(context.glb_stage) is not GLBStageService:
        raise invalid_argument("Canonical Runtime GLB stage service is unavailable.")
    return context.glb_stage


def preview(context, params):
    reject_unknown_params(params, {"filepath", "collection_name", "overwrite_policy"})
    return _service(context).preview(context, params)


def create_start(context, params):
    reject_unknown_params(params, {"preview_id", "expected_fingerprint", "accepted_losses", "time_limit_seconds"})
    limit = int_param(params, "time_limit_seconds", 60, minimum=1, maximum=300)
    service = _service(context)
    stage_id, _row = service.by_preview(params.get("preview_id"))
    result = context.jobs.start_scene(context, params, time_limit=limit)
    return service.attach_job(stage_id, result)


def inspect_stage(context, params):
    reject_unknown_params(params, {"stage_id"})
    return _service(context).inspect(context, params.get("stage_id"))


def publish_preview(context, params):
    reject_unknown_params(params, {"stage_id", "destination_scene_name", "overwrite_policy"})
    return _service(context).publish_preview(context, params)


def publish_start(context, params):
    reject_unknown_params(params, {"stage_id", "publish_preview_id", "expected_fingerprint", "overwrite_policy", "time_limit_seconds"})
    limit = int_param(params, "time_limit_seconds", 60, minimum=1, maximum=300)
    service = _service(context)
    result = context.jobs.start_scene(context, params, time_limit=limit)
    return service.attach_job(params.get("stage_id"), result)


def _early_start_admission(method, permissions, factory):
    admission = start_admission(factory)

    def capture(context, params):
        # Shared SceneJobs captures native checkpoint markers before its driver
        # factory. This domain must finish canonical grants BEFORE that read.
        _service(context)._entry(context, method, permissions)
        return admission(context, params)

    return capture


def register(registry):
    registry.register("asset.glb_stage_preview", preview, toolset="asset_delivery", permissions=READ,
        description="UNQUALIFIED candidate: preview a finite approved-source new-owned GLB stage; no native allocation.")
    registry.register("asset.glb_stage_inspect", inspect_stage, toolset="asset_delivery", permissions=(Permission.INSPECT_SCENE,),
        description="UNQUALIFIED candidate: cached primitive stage/effects evidence; no live native reads or cleanup.")
    registry.register("asset.glb_stage_publish_preview", publish_preview, toolset="asset_delivery", permissions=(Permission.INSPECT_SCENE,),
        description="UNQUALIFIED candidate: explicit one-edge Scene destination intent; no Mesh attribute inspection.")
    for name, handler, permissions, factory in (("asset.glb_stage_create_start", create_start, WRITE, create_driver),
                                               ("asset.glb_stage_publish_start", publish_start, PUBLISH, publish_driver)):
        registry.register(name, handler, toolset="asset_delivery", permissions=permissions,
            modifies=True, batchable=False, automatic_checkpoint=False, exclusive_mutation=True,
            checkpoint_owns_finalization=True, checkpoint_admission_factory=_early_start_admission(name, permissions, factory),
            description="UNQUALIFIED candidate: accept a canonical Scene job; jobs.inspect/cancel report later completion. No save or cleanup.")
