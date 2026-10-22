"""Whole-world, memory-only rigid-body cache lifecycle with measured playback.

Native calls run synchronously on Blender's main thread. Their running C tails
cannot be canceled; authority is checked before every subsequent edit.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry, check_final_mutation
from ..utils import int_param, reject_unknown_params, require_blender
from . import _animation_scope as evidence
from . import _rigid_body_scope as scope
from . import _rigid_evaluation_scope as evaluation

LOGGER = logging.getLogger(__name__)
PERMISSIONS = (Permission.INSPECT_SCENE, Permission.EDIT_SCENE, Permission.EDIT_ANIMATION)
FIELDS = {"scene_name", "operation", "body_names", "constraint_names", "frame_start", "frame_end"}
STOP_CODES = frozenset({ErrorCode.PERMISSION_DENIED.value, ErrorCode.TOOLSET_DISABLED.value,
                        ErrorCode.TIMEOUT.value, ErrorCode.EMERGENCY_STOPPED.value, ErrorCode.AGENT_PAUSED.value})


def _proposal(params: Mapping[str, Any], cache: Any) -> dict[str, Any]:
    operation = params.get("operation")
    if not isinstance(operation, str) or operation not in {"BAKE", "FREE", "INVALIDATE"}:
        raise invalid_argument("operation must be BAKE, FREE or INVALIDATE.")
    if operation != "BAKE" and ("frame_start" in params or "frame_end" in params):
        raise invalid_argument("Only BAKE accepts a proposed frame range.")
    start = int_param(params, "frame_start", int(cache.frame_start), minimum=1, maximum=1048574)
    end = int_param(params, "frame_end", int(cache.frame_end), minimum=1, maximum=1048574)
    if not 1 <= end-start+1 <= scope.MAX_FRAMES:
        raise invalid_argument("Rigid-body lifecycle requires an ordered range of at most 32 integer frames.")
    if operation == "BAKE" and cache.is_baked:
        raise invalid_argument("FREE the baked cache explicitly and obtain a new preview before BAKE.")
    if operation == "INVALIDATE" and cache.is_baked:
        raise invalid_argument("FREE the baked cache explicitly before invalidation.")
    return {"operation": operation, "frame_start": start, "frame_end": end}


def _fingerprint(snapshot: Mapping[str, Any], proposal: Mapping[str, Any]) -> str:
    return evidence.digest({"scope": snapshot, "proposal": proposal})


def _preview(bpy: Any, params: Mapping[str, Any]) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    scene = scope.current_scene(bpy, params.get("scene_name"))
    if scene.rigidbody_world is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The current Scene has no rigid-body world.")
    proposal = _proposal(params, scene.rigidbody_world.point_cache)
    snapshot = scope.snapshot(bpy, scene, params)
    result = {"scene": scene.name, "cache_operation": proposal["operation"],
              "body_names": list(snapshot["body_names"]), "constraint_names": list(snapshot["constraint_names"]),
              "affected_objects": list(snapshot["body_names"]),
              "scope": "COMPLETE_INITIAL_WHOLE_WORLD_SUBSET", "base_vertices": snapshot["base_vertices"],
              "frame_start": proposal["frame_start"], "frame_end": proposal["frame_end"],
              "expected_fingerprint": _fingerprint(snapshot, proposal), "fingerprint_lifetime": "CURRENT_SESSION_AND_EXACT_CONTEXT",
              "cache": scope.cache_state(scene.rigidbody_world.point_cache),
              "resets_existing_unbaked_memory_cache": proposal["operation"] in {"BAKE", "INVALIDATE"},
              "native_calls_preemptible": False, "cancellation": "CHECKED_AT_EACH_NATIVE_CALL_AND_WRITE_BOUNDARY",
              "durable_backup_created": False, "project_saved": False,
              "evaluation_profile": "CONSERVATIVE_STATIC_MAIN_NATIVE_DEPENDENCIES_INCLUDING_UNUSED_IDS",
              "preflight_capture_seconds": time.monotonic()-started,
              "limits": {"bodies": scope.MAX_BODIES, "total_base_vertices": scope.MAX_VERTICES,
                         "integer_frames": scope.MAX_FRAMES, "substeps": 4, "solver_iterations": 8,
                         "main_ids": evaluation.MAX_MAIN_IDS, "graph_owners": evaluation.MAX_OWNERS,
                         "node_trees": evaluation.MAX_TREES, "aggregate_nodes": evaluation.MAX_TOTAL_NODES,
                         "aggregate_links": evaluation.MAX_TOTAL_LINKS,
                         "aggregate_interface_items": evaluation.MAX_TOTAL_INTERFACE,
                         "group_depth": evaluation.MAX_DEPTH},
              "verification": "BAKE compares every body matrix at every frame with a fresh unbaked sequential reference, starting baked playback with the last frame."}
    return scene, snapshot, proposal, result


def inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"scene_name"})
    context.require(Permission.INSPECT_SCENE)
    bpy = require_blender()
    scene = scope.current_scene(bpy, params.get("scene_name"))
    result = scope.inventory(bpy, scene)
    if not result["world_present"]:
        return result
    try:
        snapshot = scope.snapshot(bpy, scene, {"body_names": result["body_names"], "constraint_names": result["constraint_names"]})
    except BridgeError as error:
        result.update(scope_complete=False, unsupported_reasons=[{"code": error.code, "message": error.message}])
    else:
        result.update(scope_complete=True, supported_scope="INITIAL_WHOLE_WORLD_MEMORY_SUBSET",
                      base_vertices=snapshot["base_vertices"], unsupported_reasons=[])
    result.update(cache_freshness="NOT_INFERRED_FROM_NATIVE_FLAGS", numeric_motion_review="NOT_PERFORMED",
                  visual_review="NOT_PERFORMED", project_saved=False)
    return result


def cache_preview(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, FIELDS)
    context.require(Permission.INSPECT_SCENE)
    return _preview(require_blender(), params)[3]


class _Boundary:
    """Exact protected/owned comparison; native outputs never adopt authored edits."""

    def __init__(self, bpy: Any, context: ToolContext, scene: Any, params: Mapping[str, Any], snapshot: dict[str, Any]):
        if not all(hasattr(context, field) for field in ("require", "state", "check_cancelled")):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body mutation requires a live permission/state context.")
        self.bpy, self.context, self.scene, self.params = bpy, context, scene, params
        self.expected = snapshot
        self.original = dict(snapshot["owned"])
        self.stopped: BridgeError | None = None
        self.started = False
        self.native_started = False
        self.cache_verified = False
        self.timings: list[dict[str, Any]] = []

    def _authority(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            if self.context.check_cancelled is not None:
                self.context.check_cancelled()
            self.context.require(*PERMISSIONS)
            registry = self.context.registry
            registry.prepare("rigid_body.cache", self.context)
            self._final()
        except BridgeError as error:
            if error.code in STOP_CODES:
                self.stopped = error
            raise

    def _final(self) -> None:
        """Pure live state after providers AND after expensive native evidence."""
        if self.stopped is not None:
            raise self.stopped
        try:
            check_final_mutation(self.context, "rigid_body.cache")
        except BridgeError as error:
            if error.code in STOP_CODES:
                self.stopped = error
            raise

    def check(self) -> None:
        self._authority()
        scene = scope.current_scene(self.bpy, self.params["scene_name"])
        if scene != self.scene or self._timed("scope_comparison", lambda: scope.snapshot(self.bpy, scene, self.params)) != self.expected:
            raise invalid_argument("Rigid-body identity, authored inputs, cache, context or consumers changed; further writes and compensation are refused.", scope_complete=False)
        self._final()

    def _accept(self, owned: Mapping[str, Any]) -> None:
        actual = self._timed("scope_publication_readback", lambda: scope.snapshot(self.bpy, self.scene, self.params))
        protected = ("protected", "body_names", "constraint_names", "base_vertices")
        if any(actual[field] != self.expected[field] for field in protected) or actual["owned"] != owned:
            raise invalid_argument("Native rigid-body work changed protected or unexpected authored state; inspect partial effects before continuing.", scope_complete=False)
        self._final()
        # Only the declared owned delta and native read-only cache status are
        # published. Nothing from a protected snapshot is adopted here.
        self.expected = {**self.expected, "owned": dict(owned), "cache_status": actual["cache_status"]}

    def _timed(self, stage: str, callback: Any) -> Any:
        started = time.monotonic()
        try:
            return callback()
        finally:
            self.timings.append({"stage": stage, "seconds": time.monotonic()-started, "preemptible": False})

    def _failed_publication(self, owned: Mapping[str, Any]) -> None:
        # A native call may raise after publishing its declared delta. Only
        # exact authored/protected readback permits subsequent gated recovery.
        # A failed comparison retains the old CAS and the original exception.
        try:
            self._accept(owned)
        except Exception:
            LOGGER.exception("Failed native rigid-body call has an unowned or incomplete publication")

    def range_field(self, field: str, value: int) -> None:
        self.check()
        expected = dict(self.expected["owned"])
        old = expected["range"]
        expected["range"] = (value, old[1]) if field == "frame_start" else (old[0], value)
        self.started = True
        try:
            setattr(self.scene.rigidbody_world.point_cache, field, value)
        except Exception:
            self._failed_publication(expected)
            raise
        self._accept(expected)

    def reset(self) -> None:
        self.check()
        self.started = True
        world = self.scene.rigidbody_world
        try:
            self._timed("same_value_world_reset", lambda: setattr(world, "time_scale", self.expected["owned"]["time_scale"]))
        except Exception:
            self._failed_publication(self.expected["owned"])
            raise
        self._accept(self.expected["owned"])
        if world.point_cache.is_baked:
            raise RuntimeError("Native invalidation retained a baked cache")

    def frame(self, frame: int, subframe: float = 0.) -> Any:
        self.check()
        expected = {**self.expected["owned"], "frame": (frame, subframe)}
        self.started = True

        def evaluate() -> Any:
            self.scene.frame_set(frame, subframe=subframe)
            self.bpy.context.view_layer.update()
            return self.bpy.context.evaluated_depsgraph_get()

        try:
            graph = self._timed("frame_evaluation", evaluate)
        except Exception:
            self._failed_publication(expected)
            raise
        self._accept(expected)
        return graph

    def native(self, operation: str) -> None:
        self.check()
        body = self.bpy.data.objects[self.expected["body_names"][0]]
        cache = self.scene.rigidbody_world.point_cache
        with self.bpy.context.temp_override(scene=self.scene, view_layer=self.bpy.context.view_layer,
                                            object=body, active_object=body, point_cache=cache):
            operator = self.bpy.ops.ptcache.bake if operation == "BAKE" else self.bpy.ops.ptcache.free_bake
            if not operator.poll():
                raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Native rigid-body point-cache operator is unavailable in the exact cache context.")
            self.check()
            self.started = self.native_started = True
            try:
                status = self._timed(f"native_{operation.lower()}", lambda: operator("EXEC_DEFAULT", **({"bake": True} if operation == "BAKE" else {})))
            except Exception:
                self._failed_publication(self.expected["owned"])
                raise
        self._accept(self.expected["owned"])
        self.check()
        if status != {"FINISHED"} or bool(cache.is_baked) != (operation == "BAKE") or bool(cache.is_baking):
            raise RuntimeError("Native rigid-body cache state did not match the requested operation")

    def sample(self, frames: list[int]) -> list[dict[str, Any]]:
        rows = []
        for frame in frames:
            graph = self.frame(frame)
            matrices = {}
            for object_name in self.expected["body_names"]:
                obj = self.bpy.data.objects[object_name]
                values = tuple(float(value) for row in obj.evaluated_get(graph).matrix_world for value in row)
                if len(values) != 16 or not all(math.isfinite(value) for value in values):
                    raise RuntimeError("Rigid-body evaluation returned a nonfinite or incomplete matrix")
                matrices[object_name] = values
            self.check()
            rows.append({"frame": frame, "matrices": matrices})
        return rows


def _difference(reference: list[dict[str, Any]], playback: list[dict[str, Any]]) -> float:
    expected = {row["frame"]: row["matrices"] for row in reference}
    return max(abs(value-expected[row["frame"]][name][index])
               for row in playback for name, matrix in row["matrices"].items() for index, value in enumerate(matrix))


def _recover_frame(boundary: _Boundary) -> dict[str, Any]:
    result: dict[str, Any] = {"attempted": False, "verified": False}
    try:
        boundary.check()
        original = boundary.original["frame"]
        if boundary.expected["owned"]["frame"] != original:
            result["attempted"] = True
            boundary.frame(*original)
        boundary.check()
        result["verified"] = boundary.expected["owned"]["frame"] == original
    except Exception as error:
        LOGGER.exception("Rigid-body caller-time recovery refused or failed")
        result.update(error_type=type(error).__name__, error_code=getattr(error, "code", None))
    return result


def _recover_range(boundary: _Boundary) -> dict[str, Any]:
    result: dict[str, Any] = {"attempted": False, "verified": False}
    try:
        boundary.check()
        original = boundary.original["range"]
        if boundary.expected["owned"]["range"] != original:
            if boundary.scene.rigidbody_world.point_cache.is_baked:
                result["reason"] = "BAKED_CACHE_RETAINED_NO_IMPLICIT_FREE"
                return result
            for field, value in zip(("frame_start", "frame_end"), original, strict=True):
                result["attempted"] = True
                boundary.range_field(field, value)
        boundary.check()
        result["verified"] = boundary.expected["owned"]["range"] == original
    except Exception as error:
        LOGGER.exception("Rigid-body cache-range recovery refused or failed")
        result.update(error_type=type(error).__name__, error_code=getattr(error, "code", None))
    return result


def cache(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, FIELDS | {"expected_fingerprint"})
    context.require(*PERMISSIONS)
    bpy = require_blender()
    scene, before, proposal, preview = _preview(bpy, params)
    expected = params.get("expected_fingerprint")
    if not isinstance(expected, str) or expected != preview["expected_fingerprint"]:
        raise invalid_argument("The exact whole-world cache preview is stale or missing; obtain a new preview before mutation.")
    boundary = _Boundary(bpy, context, scene, params, before)
    primary: Exception | None = None
    motion: dict[str, Any] | None = None
    range_recovery: dict[str, Any] = {"attempted": False, "verified": True}
    try:
        boundary.check()
        operation = proposal["operation"]
        if operation == "BAKE":
            for field in ("frame_start", "frame_end"):
                boundary.range_field(field, proposal[field])
            frames = list(range(proposal["frame_start"], proposal["frame_end"]+1))
            boundary.reset()
            reference = boundary.sample(frames)
            boundary.reset()
            boundary.frame(proposal["frame_start"])
            boundary.native("BAKE")
            playback = boundary.sample([frames[-1], *frames[:-1]])
            maximum_error = _difference(reference, playback)
            motion = {"reference_sha256": evidence.digest(reference), "playback_sha256": evidence.digest(playback),
                      "maximum_absolute_matrix_error": maximum_error, "tolerance": 1.e-6,
                      "all_body_frames_compared": True, "last_frame_sampled_first": True,
                      "samples": playback, "physical_correctness": "NOT_ASSESSED", "visual_review": "NOT_PERFORMED"}
            if maximum_error > 1.e-6:
                raise RuntimeError("Baked last-frame-first playback differs from the fresh unbaked complete matrix reference")
        elif operation == "FREE":
            boundary.native("FREE")
        else:
            boundary.reset()
            boundary.frame(proposal["frame_start"])
        boundary.check()
        boundary.cache_verified = True
    except Exception as error:
        primary = error
        LOGGER.exception("Rigid-body cache operation failed")
        range_recovery = _recover_range(boundary)
    frame_recovery = _recover_frame(boundary)
    result: dict[str, Any] | None = None
    if primary is None and frame_recovery["verified"]:
        try:
            boundary.check()
            result = {**preview, "completed": True, "cache": scope.cache_state(scene.rigidbody_world.point_cache),
                      "cache_operation_verified": True, "frame_recovery": frame_recovery,
                      "authored_settings_preserved": True, "active_selection_mode_preserved": True,
                      "native_intervals": boundary.timings, "motion": motion,
                      "free_semantics": "NATIVE_BAKED_FLAG_CLEARED_ONLY_NO_DELETION_OR_FRESHNESS_CLAIM" if proposal["operation"] == "FREE" else None,
                      "cache_freshness": "MATCHED_FRESH_SEQUENTIAL_EVALUATION" if motion else "NOT_ASSESSED",
                      "durability": "NOT_ASSESSED", "cache_undo_guaranteed": False,
                      "final_authority_and_scope_verified": True}
            boundary.check()
        except Exception as error:
            primary = error
            LOGGER.exception("Rigid-body final validation failed after native work")
    if primary is not None or not frame_recovery["verified"]:
        code = primary.code if isinstance(primary, BridgeError) else ErrorCode.OPERATION_FAILED
        details = {"execution_started": boundary.started, "possible_mutation": boundary.started,
                   "cache_operation_started": boundary.native_started, "cache_operation_verified": boundary.cache_verified,
                   "primary_error_type": None if primary is None else type(primary).__name__,
                   "range_recovery": range_recovery, "frame_recovery": frame_recovery,
                   "reset_strategy": "SAME_VALUE_TIME_SCALE_SETTER", "cache_rollback": "NOT_ATTEMPTED",
                   "native_intervals": boundary.timings, "native_calls_preemptible": False,
                   "reinspection_required": True, "durable_backup_created": False,
                   "final_authority_and_scope_verified": False}
        if isinstance(primary, BridgeError):
            details["primary_error"] = {"code": primary.code, "message": primary.message}
            facts = {key: primary.context[key] for key in ("cancellation_requested", "deadline_expired", "connection_disconnected",
                     "start_delivery_failed", "start_handoff_expired", "scope_complete") if key in primary.context}
            if facts:
                details["primary_error"]["context"] = facts
            if "missing_permissions" in primary.context:
                details["missing_permissions"] = primary.context["missing_permissions"]
        raise BridgeError(code, "Rigid-body cache work or caller-context recovery failed; inspect retained partial effects and recovery evidence.", details) from primary
    assert result is not None
    return result


def register(registry: ToolRegistry) -> None:
    registry.register("rigid_body.inspect", inspect, permissions=(Permission.INSPECT_SCENE,), toolset="simulation",
                      description="Inspect the exact current Scene's bounded whole-world rigid bodies, constraints and cache ownership.")
    registry.register("rigid_body.cache_preview", cache_preview, permissions=(Permission.INSPECT_SCENE,), toolset="simulation",
                      description="Preview one bounded memory-only rigid-world cache operation, requiring static reviewed Main dependencies including unused IDs.")
    registry.register("rigid_body.cache", cache, permissions=PERMISSIONS, toolset="simulation", modifies=True, batchable=False,
                      description="Execute a fingerprinted whole-world memory cache operation with per-frame matrix verification and measured context recovery.")
