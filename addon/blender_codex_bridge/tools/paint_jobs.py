"""Typed controls for the shared session-local job scheduler."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import int_param, reject_unknown_params


def _manager(context: Any):
    if context.jobs is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cooperative jobs are unavailable in this runtime.")
    return context.jobs


def _id(params: Mapping[str, Any]) -> str:
    value = params.get("job_id")
    if not isinstance(value, str) or re.fullmatch(r"job_[0-9a-f]{32}", value) is None:
        raise invalid_argument("'job_id' must be an exact ID returned by this bridge session.")
    return value


def start(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "new_name", "strokes", "time_limit_seconds", "mask"})
    return _manager(context).start(context, {k: v for k, v in params.items() if k != "time_limit_seconds"},
                                   params.get("time_limit_seconds", 60.))


def inspect(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"job_id"})
    return _manager(context).inspect(_id(params))


def list_jobs(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"limit"})
    return _manager(context).list(int_param(params, "limit", 10, minimum=1, maximum=32))


def cancel(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"job_id"})
    return _manager(context).cancel(_id(params))


def register_tools(registry: Any) -> None:
    registry.register("image.paint_job_start", start, toolset="materials", modifies=True,
                      automatic_checkpoint=False, batchable=False, permissions=(Permission.EDIT_MATERIALS,),
                      description="Accept one source-frozen bounded paint job; poll for final result, keep owner connection alive, verify pixels/recovery afterward.")
    registry.register("jobs.inspect", inspect, permissions=(Permission.INSPECT_SCENE,), batchable=False,
                      record_history=False, description="Inspect session-local image, geometry-preview, native-save or rigid-evaluation job progress, result and retained effects.")
    registry.register("jobs.list", list_jobs, permissions=(Permission.INSPECT_SCENE,), batchable=False,
                      record_history=False, description="List bounded image, geometry-preview, native-save and rigid-evaluation jobs and retained receipts; one active job, no durable queue.")
    registry.register("jobs.cancel", cancel, batchable=False,
                      description="Request cancellation of one exact job, including while paused; inspect terminal evidence, never assume rollback.")
