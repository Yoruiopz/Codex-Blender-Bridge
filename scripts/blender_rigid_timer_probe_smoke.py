"""Opt-in timer-gap memory-cache research; use the isolated native runner.

No typed job, save, disk cache, global cancellation or automatic recovery is
implemented. Every fixture object and evidence file belongs to this process.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "addon")]

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _rigid_body_scope as scope  # noqa: E402
from blender_codex_bridge.tools import rigid_body  # noqa: E402

from scripts.blender_rigid_lifecycle_probe_smoke import context_state, make_scene  # noqa: E402

SOURCE_COMMITS = {
    (4, 5, 14): "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
    (5, 2, 2): "d13f752e3b9c4f8c261cda552b1021f8bcc0382c",
}
FRAMES, PLAYBACK, TOLERANCE = (1, 2, 3), (3, 1, 2), 1.e-6
STATE = {"done": False, "heartbeat": 0, "tick": 0, "rows": [], "polls": [], "injection": None,
         "phase_evidence": {}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def detached(error):
    result = json.loads(json.dumps(error.to_dict()))
    error.__traceback__ = error.__context__ = error.__cause__ = None
    return result


def stable_context(value):
    return {key: item for key, item in value.items() if key not in {"frame", "subframe"}}


def motion_evidence(rows, active_names):
    matrices = {row["frame"]: row["matrices"] for row in rows}
    assert set(matrices) == set(FRAMES)
    return {"active_body_z_displacement": {
        name: matrices[FRAMES[-1]][name][11]-matrices[FRAMES[0]][name][11] for name in active_names},
        "maximum_accepted_static_displacement": TOLERANCE,
        "requires_each_active_body_to_fall": True}


def require_falling_motion(evidence):
    assert all(delta < -TOLERANCE for delta in evidence["active_body_z_displacement"].values()), (
        "Known falling benchmark did not establish active-body motion", evidence)


def remap_reference(rows, source_names, target_names):
    assert len(source_names) == len(target_names) == 3
    return [{"frame": row["frame"], "matrices": {
        target: list(row["matrices"][source])
        for source, target in zip(source_names, target_names, strict=True)}} for row in rows]


def phase_state(boundary):
    """Fingerprint accepted state; no hidden cache-content coverage is inferred."""
    return {"accepted_scope_sha256": digest(boundary.expected),
            "accepted_owned": boundary.expected["owned"],
            "accepted_volatile_cache_status": dict(boundary.expected["cache_status"])}


def write_phase_checkpoint(label):
    """Retain measured phases before later assertions can terminate the run."""
    STATE["last_observation"] = label
    result = {"last_observation": label, "phase_evidence": STATE["phase_evidence"],
              "driver_turns": STATE["rows"], "readonly_poll_turns": STATE["polls"],
              "process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
              "source_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "terminal_success": False, "research_result": "IN_PROGRESS"}
    path = Path(tempfile.gettempdir()) / "rigid-timer-probe-progress.json"
    temporary = path.with_suffix(".json.next")
    temporary.write_text(json.dumps(result, indent=2)+"\n")
    temporary.replace(path)


def checkpointed_cache(runtime, params, operation):
    proposal = {key: value for key, value in params.items()
                if operation == "BAKE" or key not in {"frame_start", "frame_end"}}
    proposal["operation"] = operation
    preview = runtime.dispatch("rigid_body.cache_preview", proposal)
    result = runtime.dispatch("rigid_body.cache", {**proposal, "expected_fingerprint": preview["expected_fingerprint"]})
    assert result["completed"] and result["cache_operation_verified"]
    assert result["frame_recovery"]["verified"] and not result["durable_backup_created"]
    if operation == "BAKE":
        assert result["motion"]["all_body_frames_compared"] and result["motion"]["last_frame_sampled_first"]
        assert result["motion"]["maximum_absolute_matrix_error"] <= TOLERANCE
    return result


def boundary_for(runtime, params, label):
    context = runtime.executor.context
    request = Request("rigid-timer-" + label, "rigid_body.cache", dict(params), _lifecycle=RequestLifetime.local())
    owner = QueuedRequest(request, deadline=float("inf"))
    assert owner.try_start()
    context.request_id, context.request_lifecycle = request.id, request._lifecycle
    context.check_cancelled = owner.check_active
    context.check_final_request = lambda: QueuedRequest.check_active(owner)
    scene = scope.current_scene(bpy, params["scene_name"])
    frozen = scope.snapshot(bpy, scene, params)
    return rigid_body._Boundary(bpy, context, scene, params, frozen), owner


def sample_steps(boundary, frame, output, label):
    """One native stage per timer turn; accept only its declared frame delta.

    This uses the existing domain's private research interfaces. A production
    job API and its checkpoint/interlock ownership remain separate work.
    """
    scene = boundary.scene
    frame_set, update = scene.frame_set, bpy.context.view_layer.update
    get_graph = bpy.context.evaluated_depsgraph_get
    boundary.check()
    expected = {**boundary.expected["owned"], "frame": (frame, 0.)}

    # Resolve native targets before final proof; use the retained bound setter.
    def set_retained_frame():
        boundary.started = True
        frame_set(frame, subframe=0.)

    for stage, callback in (("scene_frame_set", set_retained_frame), ("view_layer_update", update)):
        boundary.check()
        try:
            boundary._native_interval(stage, callback)
        except Exception:
            boundary._failed_publication(expected)
            raise
        boundary._accept(expected)
        yield {"phase": label, "frame": frame, "native_stage": stage, **phase_state(boundary)}
    boundary.check()
    graph = boundary._native_interval("evaluated_depsgraph_get", get_graph)
    matrices = {}
    for name in boundary.expected["body_names"]:
        obj = bpy.data.objects[name]
        boundary._final()
        values = [float(value) for row in obj.evaluated_get(graph).matrix_world for value in row]
        boundary._final()
        assert len(values) == 16 and all(math.isfinite(value) for value in values)
        matrices[name] = values
    boundary._accept(expected)
    boundary.check()
    output.append({"frame": frame, "matrices": matrices})
    yield {"phase": label, "frame": frame, "native_stage": "evaluated_depsgraph_get_and_matrices",
           **phase_state(boundary)}


def convert(boundary):
    """Reviewed flag-only conversion, never a proof of populated cache frames."""
    scene = boundary.scene
    cache = scene.rigidbody_world.point_cache
    body = bpy.data.objects[boundary.expected["body_names"][0]]
    before_context = context_state()
    with bpy.context.temp_override(scene=scene, view_layer=bpy.context.view_layer,
                                  object=body, active_object=body, point_cache=cache):
        operator = bpy.ops.ptcache.bake_from_cache
        assert operator.poll(), "Exact-cache conversion context is unavailable"
        boundary.check()

        def invoke():
            boundary.started = boundary.native_started = True
            return operator("EXEC_DEFAULT")

        result = boundary._native_interval("native_bake_from_cache", invoke)
    boundary._accept(boundary.expected["owned"])
    boundary.check()
    assert result == {"FINISHED"} and cache.is_baked and not cache.is_baking
    assert context_state() == before_context
    return {"operator": "ptcache.bake_from_cache", "status": sorted(result),
            "semantics": "SETS_BAKED_FLAG_ONLY_NO_FRAME_COVERAGE_TEST", "cache": scope.cache_state(cache)}


def complete_steps(runtime, params, control, initial_context):
    boundary, _owner = boundary_for(runtime, params, "complete")
    initial_scope = boundary.expected
    reference, populated, playback = [], [], []
    retained = {"state": "IN_PROGRESS", "reference": reference, "candidate_population": populated,
                "playback": playback, "native_intervals": boundary.timings,
                "scope_sha256_before": digest(initial_scope)}
    STATE["phase_evidence"]["complete"] = retained
    boundary.reset()
    yield {"phase": "reference_reset"}
    for frame in FRAMES:
        yield from sample_steps(boundary, frame, reference, "fresh_reference")
    retained["fresh_reference_motion"] = motion_evidence(reference, boundary.expected["body_names"][:2])
    write_phase_checkpoint("fresh_reference_motion_measured")
    require_falling_motion(retained["fresh_reference_motion"])
    boundary.reset()
    yield {"phase": "candidate_reset"}
    for frame in FRAMES:
        yield from sample_steps(boundary, frame, populated, "candidate_population")
    conversion = convert(boundary)
    retained["conversion"] = conversion
    yield {"phase": "complete_cache_converted"}
    for frame in PLAYBACK:
        yield from sample_steps(boundary, frame, playback, "converted_playback")
    errors = {
        "fresh_reference": rigid_body._difference(reference, playback),
        "separate_population_pass": rigid_body._difference(reference, populated),
        "existing_typed_native_bake": rigid_body._difference(control["motion"]["samples"], playback),
    }
    retained["maximum_matrix_errors"] = errors
    write_phase_checkpoint("complete_playback_errors_measured")
    assert max(errors.values()) <= TOLERANCE, errors
    recovery = rigid_body._recover_frame(boundary)
    retained["caller_frame_recovery"] = recovery
    assert recovery["verified"] and context_state() == initial_context
    assert boundary.expected["protected"] == initial_scope["protected"]
    assert boundary.expected["owned"] == initial_scope["owned"]
    yield {"phase": "complete_caller_time_restored"}
    retained.update(state="VERIFIED", reference_sha256=digest(reference), population_sha256=digest(populated),
                    playback_sha256=digest(playback), scope_sha256_after=digest(boundary.expected))
    return retained


def incomplete_steps(runtime, params, reference):
    boundary, _owner = boundary_for(runtime, params, "incomplete")
    first_only, playback = [], []
    retained = {"state": "IN_PROGRESS", "only_evaluated_frames_before_conversion": [1],
                "memory_frame_coverage_before_conversion": "NOT_INFERRED_FROM_VISITED_FRAMES",
                "first_frame_samples": first_only,
                "reference": reference, "playback": playback, "native_intervals": boundary.timings,
                "reference_motion": motion_evidence(reference, boundary.expected["body_names"][:2]),
                "independent_new_world": True, "complete_playback_rejected": False}
    STATE["phase_evidence"]["incomplete"] = retained
    require_falling_motion(retained["reference_motion"])
    boundary.reset()
    yield {"phase": "incomplete_reset"}
    yield from sample_steps(boundary, 1, first_only, "incomplete_first_frame_only")
    retained["initial_frame_matrix_error"] = rigid_body._difference(reference, first_only)
    write_phase_checkpoint("independent_incomplete_initial_frame_compared")
    assert retained["initial_frame_matrix_error"] <= TOLERANCE
    conversion = convert(boundary)
    retained.update(conversion=conversion, native_baked_flag=True)
    yield {"phase": "incomplete_cache_converted"}
    for frame in PLAYBACK:
        yield from sample_steps(boundary, frame, playback, "incomplete_baked_playback")
    difference = rigid_body._difference(reference, playback)
    retained["maximum_matrix_error"] = difference
    retained["complete_playback_rejected"] = difference > TOLERANCE
    retained["playback_motion"] = motion_evidence(playback, boundary.expected["body_names"][:2])
    write_phase_checkpoint("independent_incomplete_playback_compared")
    assert difference > TOLERANCE, "Incomplete conversion did not establish the expected negative control"
    recovery = rigid_body._recover_frame(boundary)
    retained["caller_frame_recovery"] = recovery
    assert recovery["verified"]
    yield {"phase": "incomplete_caller_time_restored"}
    retained.update(state="VERIFIED", reference_sha256=digest(reference), playback_sha256=digest(playback))
    return retained


def native_stages(boundary):
    """Exclude guarded read-only captures from attempted native work receipts."""
    return [row for row in boundary.timings if row["stage"] not in {
        "scope_comparison", "scope_publication_readback",
    }]


def stopped_steps(runtime, params, grants, kind, body):
    boundary, owner = boundary_for(runtime, params, kind)
    before_context = context_state()
    boundary.reset()
    yield {"phase": kind + "_reset"}
    rows = []
    result = {"case": kind, "state": "IN_PROGRESS", "first_frame_samples": rows,
              "native_intervals": boundary.timings}
    STATE["phase_evidence"].setdefault("stopped", {})[kind] = result
    yield from sample_steps(boundary, 1, rows, kind + "_first_frame")
    before_native_stages = list(native_stages(boundary))
    before_scope_comparisons = sum(row["stage"] == "scope_comparison" for row in boundary.timings)
    original_location = tuple(body.location)
    action_observed = []

    def inject():
        if kind == "external_edit":
            body.location.x += .125
        elif kind == "cancel":
            owner.cancel_pending(BridgeError("TIMEOUT", "Owned timer-gap cancellation"))
        else:
            grants[Permission.EDIT_ANIMATION.value] = False
        action_observed.append({"heartbeat": STATE["heartbeat"], "driver_tick": STATE["tick"]})

    STATE["injection"] = inject
    yield {"phase": kind + "_await_independent_heartbeat_injection"}
    assert action_observed and STATE["injection"] is None
    try:
        yield from sample_steps(boundary, 2, rows, kind + "_forbidden_next_frame")
    except BridgeError as error:
        failure = detached(error)
        result["failure"] = failure
    else:
        raise AssertionError("A changed or stopped owner entered another frame phase: " + kind)
    expected_code = {"external_edit": "INVALID_ARGUMENT", "cancel": "TIMEOUT", "permission": "PERMISSION_DENIED"}[kind]
    assert failure["code"] == expected_code, failure
    assert native_stages(boundary) == before_native_stages, "A native stage started after stopped admission"
    assert (boundary.scene.frame_current, boundary.scene.frame_subframe) == (1, 0.)
    assert stable_context(context_state()) == stable_context(before_context)
    if kind == "external_edit":
        assert tuple(body.location) == (original_location[0]+.125, *original_location[1:])
    else:
        assert tuple(body.location) == original_location
    # No restore/reset/free/cleanup is attempted with this stopped or stale
    # boundary. Read-only evidence is retained before a NEW explicit operation.
    retained = {"frame": [boundary.scene.frame_current, boundary.scene.frame_subframe],
                "body_location": list(body.location), "cache": scope.cache_state(boundary.scene.rigidbody_world.point_cache)}
    result.update(state="STOP_BOUNDARY_VERIFIED", injection=action_observed, retained_partial=retained,
                  post_stop_native_work_stages=0, read_only_scope_comparisons_after_stop=sum(
                      row["stage"] == "scope_comparison" for row in boundary.timings)-before_scope_comparisons,
                  automatic_context_restore_attempted=False, automatic_cache_cleanup_attempted=False,
                  rollback_verified=False, caller_context_restored=False)
    yield {"phase": kind + "_partial_retained_without_recovery", "error_code": failure["code"]}
    if kind == "permission":
        grants[Permission.EDIT_ANIMATION.value] = True
    # The original owner remains canceled/stale. These are fresh, authorized
    # existing typed requests, not compensation on behalf of the stopped owner.
    free = checkpointed_cache(runtime, params, "FREE")
    result["explicit_followup"] = {"free": free, "new_requests": True, "stopped_boundary_reused": False}
    yield {"phase": kind + "_fresh_authorized_typed_free"}
    rebake = checkpointed_cache(runtime, params, "BAKE")
    result["explicit_followup"]["rebake"] = rebake
    yield {"phase": kind + "_fresh_authorized_typed_rebake"}
    assert native_stages(boundary) == before_native_stages
    result["state"] = "VERIFIED"
    return result


def experiment(runtime, grants):
    scene, bodies, _sentinel = make_scene("Owned Timer Cache World", (0., 0., -9.81))
    scene.frame_set(7, subframe=.25)
    initial_context = context_state()
    params = {"scene_name": scene.name, "body_names": [body.name for body in bodies],
              "constraint_names": [], "frame_start": 1, "frame_end": 3}
    # Complete native admission is performed before the first research write.
    before = scope.snapshot(bpy, scene, params)
    assert before["base_vertices"] == 24 and len(before["body_names"]) == 3
    yield {"phase": "frozen_world_admitted", "scope_sha256": digest(before)}
    control = checkpointed_cache(runtime, params, "BAKE")
    STATE["phase_evidence"]["typed_control"] = control
    STATE["phase_evidence"]["typed_control_motion"] = motion_evidence(control["motion"]["samples"], params["body_names"][:2])
    write_phase_checkpoint("existing_typed_control_motion_measured")
    require_falling_motion(STATE["phase_evidence"]["typed_control_motion"])
    assert context_state() == initial_context
    yield {"phase": "existing_synchronous_typed_bake_control"}
    checkpointed_cache(runtime, params, "FREE")
    yield {"phase": "typed_control_freed"}
    complete = yield from complete_steps(runtime, params, control, initial_context)
    checkpointed_cache(runtime, params, "FREE")
    yield {"phase": "complete_conversion_explicitly_freed"}
    # This cache is allocated independently and never visits frame 2 or 3
    # before conversion. Reusing the completed world's flagged memory cache
    # cannot prove an incomplete-cache negative control.
    source_cache_pointer = scene.rigidbody_world.point_cache.as_pointer()
    negative_scene, negative_bodies, _negative_sentinel = make_scene("Independent Incomplete Timer World", (0., 0., -9.81))
    assert (negative_scene.frame_current, negative_scene.frame_subframe) == (1, 0.)
    negative_params = {**params, "scene_name": negative_scene.name,
                       "body_names": [body.name for body in negative_bodies]}
    negative_cache = negative_scene.rigidbody_world.point_cache
    assert negative_cache.as_pointer() != source_cache_pointer
    mapped_reference = remap_reference(complete["reference"], params["body_names"], negative_params["body_names"])
    STATE["phase_evidence"]["independent_negative_world"] = {
        "scene": negative_scene.name, "scene_identity": [int(negative_scene.as_pointer()), negative_scene.session_uid],
        "cache_pointer": int(negative_cache.as_pointer()), "source_cache_pointer": int(source_cache_pointer),
        "created_frame": [negative_scene.frame_current, negative_scene.frame_subframe],
        "initial_native_cache_state": scope.cache_state(negative_cache),
        "role_mapping": list(zip(params["body_names"], negative_params["body_names"], strict=True)),
        "reference_sha256": digest(mapped_reference), "native_world_or_cache_copied": False,
    }
    scope.snapshot(bpy, negative_scene, negative_params)
    yield {"phase": "independent_incomplete_world_admitted_at_start_frame"}
    incomplete = yield from incomplete_steps(runtime, negative_params, mapped_reference)
    checkpointed_cache(runtime, negative_params, "FREE")
    yield {"phase": "negative_control_explicitly_freed"}
    # All old boundaries are finished; context switching is a new explicit
    # fixture action, never recovery by a canceled or invalidated owner.
    bpy.context.window.scene = scene
    assert context_state() == initial_context
    yield {"phase": "complete_world_context_explicitly_reselected"}
    stopped = []
    for kind in ("external_edit", "cancel", "permission"):
        if scene.rigidbody_world.point_cache.is_baked:
            checkpointed_cache(runtime, params, "FREE")
            yield {"phase": kind + "_prior_bake_explicitly_freed"}
        stopped.append((yield from stopped_steps(runtime, params, grants, kind, bodies[0])))
    final_boundary, _owner = boundary_for(runtime, params, "final_explicit_time_restore")
    final_boundary.frame(initial_context["frame"], initial_context["subframe"])
    assert context_state() == initial_context
    assert all(not getattr(scene.rigidbody_world.point_cache, flag) for flag in ("use_disk_cache", "use_external"))
    assert grants[Permission.EXECUTE_PYTHON.value] is False
    return {"body_names": params["body_names"], "base_vertices": 24, "frames": list(FRAMES),
            "complete": complete, "incomplete_control": incomplete, "stopped_cases": stopped,
            "phase_evidence": STATE["phase_evidence"],
            "typed_control": control, "initial_context": initial_context, "final_context": context_state(),
            "final_explicit_time_restore_intervals": final_boundary.timings,
            "world_identity": [int(scene.as_pointer()), scene.session_uid],
            "mode_selection_active_preserved": True, "project_saved": False,
            "cache_durability_verified": False, "typed_jobs_implemented": False,
            "global_cancel_invoked": False, "disk_cache_enabled": False,
            "full_recovery_acceptance": False, "release_readiness": "NOT_ASSESSED"}


def fail(stage):
    """Retain the primary failure and stop this owned process without recovery."""
    STATE["done"] = True
    primary_traceback = traceback.format_exc()
    print(primary_traceback, file=sys.stderr, flush=True)
    try:
        result = {"failed_callback": stage, "traceback": primary_traceback,
                  "driver_turns": STATE["rows"], "readonly_poll_turns": STATE["polls"],
                  "phase_evidence": STATE["phase_evidence"],
                  "last_observation": STATE.get("last_observation"),
                  "process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
                  "failure_path_context_restore_attempted": False, "failure_path_cache_cleanup_attempted": False,
                  "project_saved": False, "research_result": "FAILED"}
        path = Path(tempfile.gettempdir()) / "rigid-timer-probe-failure.json"
        raw = (json.dumps(result, indent=2)+"\n").encode()
        path.write_bytes(raw)
        print("RIGID_TIMER_PROBE_FAILURE " + json.dumps({
            "failed_callback": stage, "evidence_file": str(path),
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        }), flush=True)
    except Exception:
        traceback.print_exc()
    # Only process exit is requested; stopped/native cache state is retained.
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        traceback.print_exc()
    return None


def heartbeat():
    if STATE["done"]:
        return None
    try:
        STATE["heartbeat"] += 1
        runtime = STATE.get("runtime")
        if runtime is not None:
            status = runtime.dispatch("bridge.status", {})
            STATE["polls"].append({"heartbeat": STATE["heartbeat"], "driver_tick": STATE["tick"],
                                   "scene": status["scene"], "mode": status["mode"]})
        injection = STATE["injection"]
        if injection is not None:
            STATE["injection"] = None
            injection()
        return .005
    except Exception:
        return fail("heartbeat")


def tick():
    if STATE["done"]:
        return None
    try:
        if "work" not in STATE:
            version, build = tuple(bpy.app.version), bpy.app.build_hash
            build = build.decode("ascii") if isinstance(build, bytes) else build
            assert version in SOURCE_COMMITS and build in {SOURCE_COMMITS[version], SOURCE_COMMITS[version][:12]}
            assert not bpy.app.background, "Use the opt-in isolated interactive runner"
            bpy.context.preferences.use_preferences_save = False
            blender_codex_bridge.register()
            runtime = get_runtime()
            runtime.registry.enable_toolset("simulation")
            grants = {permission.value: permission not in {
                Permission.EXECUTE_PYTHON, Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT,
            } for permission in Permission}
            runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: dict(grants))
            STATE.update(runtime=runtime, grants=grants, work=experiment(runtime, grants), last_heartbeat=-1,
                         version=version, build=build)
        if STATE["heartbeat"] <= STATE["last_heartbeat"]:
            return .01
        STATE["tick"] += 1
        started = time.perf_counter()
        try:
            phase = next(STATE["work"])
        except StopIteration as completed:
            result = completed.value
            assert len(STATE["rows"]) > 30 and len(STATE["polls"]) >= len(STATE["rows"])-1
            assert all(a["heartbeat"] < b["heartbeat"]
                       for a, b in zip(STATE["rows"], STATE["rows"][1:], strict=False))
            result.update(native_build_hash=STATE["build"], native_source_commit=SOURCE_COMMITS[STATE["version"]],
                          driver_turns=STATE["rows"], readonly_poll_turns=STATE["polls"],
                          source_fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          process_id=os.getpid(), process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"])
            path = Path(tempfile.gettempdir()) / "rigid-timer-probe-evidence.json"
            raw = (json.dumps(result, indent=2)+"\n").encode()
            path.write_bytes(raw)
            print("BLENDER_RIGID_TIMER_PROBE_OK " + json.dumps({
                "blender_version": bpy.app.version_string, "native_source_commit": result["native_source_commit"],
                "complete_evidence_file": str(path), "complete_evidence_sha256": hashlib.sha256(raw).hexdigest(),
                "timer_turns": len(STATE["rows"]), "readonly_polls": len(STATE["polls"]),
                "complete_matrix_comparison_verified": True, "incomplete_cache_conversion_rejected": True,
                "external_edit_and_stopped_owner_boundaries_verified": True,
                "explicit_typed_free_rebake_verified": True, "typed_jobs_implemented": False,
                "full_recovery_acceptance": False, "release_readiness": "NOT_ASSESSED",
            }), flush=True)
            STATE["done"] = True
            bpy.ops.wm.quit_blender()
            return None
        STATE["rows"].append({"tick": STATE["tick"], "heartbeat": STATE["heartbeat"],
                              "seconds": time.perf_counter()-started, **phase})
        write_phase_checkpoint(phase["phase"])
        STATE["last_heartbeat"] = STATE["heartbeat"]
        print("RIGID_TIMER_STAGE " + json.dumps(STATE["rows"][-1]), flush=True)
        return .02
    except Exception:
        return fail("tick")


bpy.app.timers.register(heartbeat, first_interval=.01)
bpy.app.timers.register(tick, first_interval=1.)
