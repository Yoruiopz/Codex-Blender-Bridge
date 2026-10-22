"""Exercise the product whole-world scope against small, owned native data."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _rigid_body_scope as scope  # noqa: E402
from blender_codex_bridge.tools import rigid_body  # noqa: E402

from scripts.blender_rigid_lifecycle_probe_smoke import context_state, make_scene  # noqa: E402


def main():
    bpy.context.preferences.use_preferences_save = False
    scene, bodies, sentinel = make_scene("Owned Product Scope", (0., 0., -9.81))
    other = bpy.data.scenes.new("Owned Product Scope Consumer")
    params = {"body_names": [obj.name for obj in bodies], "constraint_names": []}
    scene.frame_set(7, subframe=.25)
    before = context_state()
    inventory = scope.inventory(bpy, scene)
    snapshot = scope.snapshot(bpy, scene, params)
    assert context_state() == before
    assert inventory["body_names"] == sorted(params["body_names"])
    assert inventory["constraint_names"] == [] and not inventory["truncated"]
    assert snapshot["body_names"] == tuple(sorted(params["body_names"]))
    assert snapshot["constraint_names"] == () and snapshot["base_vertices"] == 24
    assert snapshot["owned"] == {"frame": (7, .25), "time_scale": .75, "range": (1, 3)}
    assert snapshot == scope.snapshot(bpy, scene, params)

    rejections = []

    def reject(label, proposal=params):
        current = context_state()
        try:
            scope.snapshot(bpy, scene, proposal)
        except BridgeError as error:
            rejections.append({"case": label, "code": error.code, "message": error.message})
        else:
            raise AssertionError(f"Scope unexpectedly accepted {label}")
        assert current == context_state()

    reject("missing_passive_body", {"body_names": params["body_names"][:-1], "constraint_names": []})
    reject("duplicate_body", {"body_names": params["body_names"] + [bodies[0].name], "constraint_names": []})
    other.collection.children.link(scene.rigidbody_world.collection)
    reject("body_collection_shared_by_another_scene")
    other.collection.children.unlink(scene.rigidbody_world.collection)
    assert snapshot == scope.snapshot(bpy, scene, params)
    other.collection.children.link(scene.rigidbody_world.constraints)
    reject("constraint_collection_shared_by_another_scene")
    other.collection.children.unlink(scene.rigidbody_world.constraints)
    manager = bpy.context.window_manager
    reference_key = "_bridge_owned_rigid_scene_consumer"
    assert reference_key not in manager
    manager[reference_key] = scene
    reject("unexplained_window_manager_scene_reference")
    del manager[reference_key]
    assert snapshot == scope.snapshot(bpy, scene, params)

    def owned_frame_handler(unused_scene):
        pass

    bpy.app.handlers.frame_change_post.append(owned_frame_handler)
    reject("unbounded_frame_handler")
    bpy.app.handlers.frame_change_post.remove(owned_frame_handler)
    assert snapshot == scope.snapshot(bpy, scene, params)
    external_constraint = sentinel.constraints.new("COPY_LOCATION")
    external_constraint.target = bodies[0]
    reject("external_object_constraint_consumer")
    sentinel.constraints.remove(external_constraint)
    instance = bpy.data.objects.new("Owned World Collection Instance", None)
    scene.collection.objects.link(instance)
    instance.instance_type = "COLLECTION"
    instance.instance_collection = scene.rigidbody_world.collection
    reject("body_collection_instance_consumer")
    bpy.data.objects.remove(instance, do_unlink=True)
    assert snapshot == scope.snapshot(bpy, scene, params)
    bodies[0].parent = sentinel
    reject("body_parent_dependency")
    bodies[0].parent = None
    assert snapshot == scope.snapshot(bpy, scene, params)
    original = bodies[0].data.vertices[0].co.x
    bodies[0].data.vertices[0].co.x = original + .125
    changed = scope.snapshot(bpy, scene, params)
    assert changed["protected"] != snapshot["protected"]
    bodies[0].data.vertices[0].co.x = original
    assert snapshot == scope.snapshot(bpy, scene, params)
    assert context_state() == before
    blender_codex_bridge.register()
    runtime = get_runtime()
    registry = runtime.registry
    registry.enable_toolset("simulation")
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    tool_context = runtime.executor.context
    tool_context.check_cancelled = lambda: None

    def call(method, proposal):
        try:
            return runtime.dispatch("rigid_body." + method, proposal)
        except BridgeError:
            print("RIGID_RUNTIME_SCENE_OWNERSHIP " + json.dumps({"users": scene.users,
                "fake_user": scene.use_fake_user, "extra_user": scene.use_extra_user,
                "scene_identity": [int(scene.as_pointer()), scene.session_uid],
                "self_id_pointers": [prop.identifier for prop in scene.bl_rna.properties
                                     if prop.type == "POINTER" and getattr(scene, prop.identifier) == scene],
                "direct_users": [{"name": owner.name, "type": owner.bl_rna.identifier,
                                  "references": owner.user_of_id(scene), "same_identity": owner == scene,
                                  "identity": [int(owner.as_pointer()), owner.session_uid]}
                                 for owner in bpy.data.user_map(subset={scene}).get(scene, ())]}), flush=True)
            raise

    typed_inspection = call("inspect", {"scene_name": scene.name})
    assert typed_inspection["scope_complete"]

    def prepared(operation):
        proposal = {"scene_name": scene.name, **params, "operation": operation}
        if operation == "BAKE":
            proposal.update(frame_start=1, frame_end=3)
        preview = call("cache_preview", proposal)
        assert len(preview["expected_fingerprint"]) == 64
        return {**proposal, "expected_fingerprint": preview["expected_fingerprint"]}

    def execute(operation):
        result = call("cache", prepared(operation))
        assert result["completed"] and result["cache_operation_verified"]
        assert result["frame_recovery"]["verified"] and context_state() == before
        assert scene.rigidbody_world.time_scale == .75
        return result

    first_bake = execute("BAKE")
    motion = first_bake["motion"]
    assert motion["maximum_absolute_matrix_error"] <= motion["tolerance"]
    assert motion["all_body_frames_compared"] and motion["last_frame_sampled_first"]
    assert [row["frame"] for row in motion["samples"]] == [3, 1, 2]
    assert all(set(row["matrices"]) == set(params["body_names"]) and
               all(len(values) == 16 for values in row["matrices"].values()) for row in motion["samples"])
    assert motion["samples"][0]["matrices"][bodies[0].name][11] < motion["samples"][1]["matrices"][bodies[0].name][11]
    first_free = execute("FREE")
    assert not first_free["cache"]["is_baked"]
    scene.gravity = (0., 0., 0.)
    bpy.context.view_layer.update()
    zero_bake = execute("BAKE")
    rows = zero_bake["motion"]["samples"]
    assert rows[0]["matrices"] == rows[1]["matrices"] == rows[2]["matrices"]
    second_free = execute("FREE")
    invalidated = execute("INVALIDATE")
    assert not invalidated["cache"]["is_baked"]
    registered_runtime_history = runtime.state.history(50)
    assert sum(record["tool"] == "rigid_body.cache" for record in registered_runtime_history) == 5
    assert all(record["affected_objects"] == sorted(params["body_names"]) for record in registered_runtime_history
               if record["tool"] == "rigid_body.cache")
    native_checkpoint_reference = {"same_original_identity": scene.original == scene,
                                   "is_evaluated": scene.is_evaluated, "extra_user": scene.use_extra_user,
                                   "native_users": scene.users, "self_reference_count": scene.user_of_id(scene)}
    assert native_checkpoint_reference == {"same_original_identity": True, "is_evaluated": False,
                                           "extra_user": True, "native_users": 1, "self_reference_count": 1}
    self_reference_key = "_bridge_owned_unexplained_self_reference"
    scene[self_reference_key] = scene
    reject("scene_custom_self_reference_beyond_native_checkpoint")
    del scene[self_reference_key]

    queue_final_hook_available = hasattr(runtime.executor.context, "check_final_request")
    assert queue_final_hook_available, "Canonical pure request hook is required for this native fixture"
    queued_scope_stops = []
    if queue_final_hook_available:
        capture = scope.snapshot
        for signal in ("cancel", "expiry"):
            for capture_index in (2, 4):
                proposal = prepared("BAKE")
                request = Request(id=f"rigid-{signal}-{capture_index}", method="rigid_body.cache", params=proposal,
                                  _lifecycle=RequestLifetime.local())
                queued = QueuedRequest(request)
                assert queued.try_start()
                reads = [0]

                def poison_after_capture(*args, signal=signal, capture_index=capture_index, queued=queued, reads=reads):
                    result = capture(*args)
                    reads[0] += 1
                    if reads[0] == capture_index:
                        if signal == "cancel":
                            queued.cancel_pending(BridgeError("TIMEOUT", "Injected canonical queued cancellation after scope read"))
                        else:
                            queued.deadline = 0.
                    return result

                scope.snapshot = poison_after_capture
                try:
                    response = runtime.executor.execute_request(request, check_cancelled=queued.check_active)
                    assert not response.ok and response.error["code"] == "TIMEOUT", response
                    details = response.error["context"]
                    assert reads[0] >= capture_index and not details["cache_operation_started"]
                    assert details["possible_mutation"] == (capture_index == 4)
                    assert not details["frame_recovery"]["attempted"]
                    assert (scene.frame_current, scene.frame_subframe) == (7, .25)
                    queued_scope_stops.append({"signal": signal, "capture_index": capture_index,
                                               "canonical_queued_request": True, "error": response.error})
                finally:
                    scope.snapshot = capture

    # Each inner stage invokes a real native call. Cancellation is injected only
    # after that call returns (or just before its guarded invocation), without
    # replacing Blender's Scene/ViewLayer/dependency-graph implementations.
    native_stage_stops = []
    original_interval = rigid_body._Boundary._native_interval
    capture = scope.snapshot
    for signal in ("cancel", "expiry"):
        for target_stage in ("scene_frame_set", "view_layer_update"):
            for when in ("before", "after"):
                proposal = prepared("BAKE")
                protected_before = scope.snapshot(bpy, scene, params)["protected"]
                cache_before = scope.cache_state(scene.rigidbody_world.point_cache)
                request = Request(id=f"rigid-native-{signal}-{target_stage}-{when}",
                                  method="rigid_body.cache", params=proposal, _lifecycle=RequestLifetime.local())
                queued = QueuedRequest(request)
                assert queued.try_start()
                entries, stopped, reads = [], [], []
                cache_at_stop = []

                def counted_capture(*args, reads=reads):
                    reads.append(True)
                    return capture(*args)

                def revoke(*, signal=signal, queued=queued, stopped=stopped, reads=reads, cache_at_stop=cache_at_stop):
                    if signal == "cancel":
                        queued.cancel_pending(BridgeError("TIMEOUT", "Injected canonical cancellation between native evaluations"))
                    else:
                        queued.deadline = 0.
                    stopped.append(len(reads))
                    cache_at_stop.append(scope.cache_state(scene.rigidbody_world.point_cache))

                def guarded_interval(self, stage, callback, *, target_stage=target_stage, when=when,
                                     stopped=stopped, entries=entries, revoke=revoke):
                    if stage == target_stage and when == "before" and not stopped:
                        revoke()

                    def observed():
                        entries.append(stage)
                        result = callback()  # Actual bounded native setter/evaluation.
                        if stage == target_stage and when == "after" and not stopped:
                            revoke()
                        return result

                    return original_interval(self, stage, observed)

                scope.snapshot = counted_capture
                rigid_body._Boundary._native_interval = guarded_interval
                try:
                    response = runtime.executor.execute_request(request, check_cancelled=queued.check_active)
                    assert not response.ok and response.error["code"] == "TIMEOUT", response
                    details = response.error["context"]
                    assert stopped and len(reads) == stopped[0]
                    assert entries.count(target_stage) == (when == "after")
                    assert not details["cache_operation_started"] and details["possible_mutation"]
                    assert not details["frame_recovery"]["attempted"] and not details["frame_recovery"]["verified"]
                    assert "native_bake" not in entries and "evaluated_depsgraph_get" not in entries
                    if target_stage == "scene_frame_set":
                        assert "view_layer_update" not in entries
                    expected_frame = (7, .25) if target_stage == "scene_frame_set" and when == "before" else (1, 0.)
                    assert (scene.frame_current, scene.frame_subframe) == expected_frame
                    assert not scene.rigidbody_world.point_cache.is_baked
                    cache_after = scope.cache_state(scene.rigidbody_world.point_cache)
                    assert cache_after == cache_at_stop[0]
                    assert capture(bpy, scene, params)["protected"] == protected_before
                    native_stage_stops.append({"signal": signal, "stage": target_stage, "when": when,
                        "canonical_queued_request": True, "actual_native_stage_entries": entries,
                        "domain_scope_readbacks_after_stop": len(reads)-stopped[0],
                        "retained_frame": list(expected_frame), "cache_before": cache_before,
                        "cache_at_stop": cache_at_stop[0], "cache_after_response": cache_after,
                        "protected_authored_state_preserved": True, "error": response.error})
                finally:
                    scope.snapshot = capture
                    rigid_body._Boundary._native_interval = original_interval
                # This is an explicit fixture repair after the stopped request
                # ended, not an authorized production compensation.
                scene.frame_set(7, subframe=.25)
                assert context_state() == before

    # The real registered executor/history path above is separate from the
    # following domain fault harness, which injects a custom live context.
    def call(method, proposal):
        return registry.dispatch("rigid_body." + method, proposal, tool_context)
    proposal = prepared("BAKE")
    denied_before = scope.snapshot(bpy, scene, params)
    grants[Permission.EDIT_SCENE.value] = False
    try:
        call("cache", proposal)
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    else:
        raise AssertionError("Missing permission was ignored")
    finally:
        grants[Permission.EDIT_SCENE.value] = True
    assert scope.snapshot(bpy, scene, params) == denied_before

    cancellation = {"active": False}

    def check_cancelled():
        if cancellation["active"]:
            raise BridgeError("TIMEOUT", "Injected local request cancellation")

    tool_context.check_cancelled = check_cancelled
    original_timed = rigid_body._Boundary._timed
    stop_codes = {"permission": "PERMISSION_DENIED", "pause": "AGENT_PAUSED",
                  "emergency": "EMERGENCY_STOPPED", "cancel": "TIMEOUT", "toolset": "TOOLSET_DISABLED"}
    live_stops = []
    for stop, code in stop_codes.items():
        proposal = prepared("BAKE")
        fired = []

        def after_first_evaluation(self, stage, callback, *, stop=stop, fired=fired):
            result = original_timed(self, stage, callback)
            if stage == "frame_evaluation" and not fired:
                fired.append(True)
                if stop == "permission":
                    grants[Permission.EDIT_SCENE.value] = False
                elif stop == "pause":
                    tool_context.state.set_paused(True)
                elif stop == "emergency":
                    tool_context.state.set_emergency_stopped(True)
                elif stop == "cancel":
                    cancellation["active"] = True
                else:
                    registry.disable_toolset("simulation")
            return result

        rigid_body._Boundary._timed = after_first_evaluation
        try:
            call("cache", proposal)
        except BridgeError as error:
            assert fired and error.code == code, error.to_dict()
            assert error.context["possible_mutation"] and not error.context["frame_recovery"]["verified"]
            assert not error.context["cache_operation_started"]
            live_stops.append({"case": stop, "error": error.to_dict(), "retained_frame": [scene.frame_current, scene.frame_subframe]})
        else:
            raise AssertionError(f"Live {stop} was ignored")
        finally:
            rigid_body._Boundary._timed = original_timed
            grants[Permission.EDIT_SCENE.value] = True
            tool_context.state.set_paused(False)
            tool_context.state.set_emergency_stopped(False)
            cancellation["active"] = False
            registry.enable_toolset("simulation")
        assert (scene.frame_current, scene.frame_subframe) == (1, 0.)
        assert not scene.rigidbody_world.point_cache.is_baked
        scene.frame_set(7, subframe=.25)  # Explicit owned fixture repair after authority is restored.
        assert context_state() == before

    owner_failures = []
    for owner_stop in ("connection_disconnected", "expired_undelivered", "final_job_cancel", "final_job_deadline"):
        lifetime = RequestLifetime(connection=ConnectionLifetime())
        if owner_stop != "expired_undelivered":
            lifetime.delivered.set()
        armed, revoked, final_cancel = threading.Event(), threading.Event(), threading.Event()
        final_deadline = [float("inf")]

        def provider(*, armed=armed, revoked=revoked, owner_stop=owner_stop, lifetime=lifetime,
                     final_cancel=final_cancel, final_deadline=final_deadline):
            if armed.is_set() and not revoked.is_set():
                revoked.set()
                if owner_stop == "connection_disconnected":
                    lifetime.connection.disconnected.set()
                elif owner_stop == "expired_undelivered":
                    lifetime.deadline = time.monotonic()-1.
                elif owner_stop == "final_job_cancel":
                    final_cancel.set()
                else:
                    final_deadline[0] = time.monotonic()-1.
            return grants

        def final_job_check(*, final_cancel=final_cancel, final_deadline=final_deadline):
            if final_cancel.is_set() or time.monotonic() >= final_deadline[0]:
                raise BridgeError("TIMEOUT", "Injected pure scheduler cancellation/deadline flag")

        def arm_after_evaluation(self, stage, callback, *, armed=armed):
            result = original_timed(self, stage, callback)
            if stage == "frame_evaluation":
                armed.set()
            return result

        tool_context.permissions = PermissionManager(provider)
        tool_context.request_lifecycle = lifetime
        tool_context.check_final_job = final_job_check
        proposal = prepared("BAKE")
        rigid_body._Boundary._timed = arm_after_evaluation
        try:
            call("cache", proposal)
        except BridgeError as error:
            assert armed.is_set() and revoked.is_set() and error.code == "TIMEOUT"
            assert error.context["possible_mutation"] and not error.context["cache_operation_started"]
            assert not error.context["frame_recovery"]["verified"]
            owner_failures.append({"case": owner_stop, "error": error.to_dict(),
                                   "revoked_inside_permission_provider": True,
                                   "connection_disconnected": lifetime.connection.disconnected.is_set(),
                                   "request_delivered": lifetime.delivered.is_set(),
                                   "handoff_deadline_expired": time.monotonic() >= lifetime.deadline,
                                   "final_job_cancelled": final_cancel.is_set(),
                                   "final_job_deadline_expired": time.monotonic() >= final_deadline[0]})
        else:
            raise AssertionError(f"Owner {owner_stop} revoked inside the provider was ignored")
        finally:
            rigid_body._Boundary._timed = original_timed
            tool_context.permissions = PermissionManager(lambda: grants)
            tool_context.request_lifecycle = None
            tool_context.check_final_job = None
        assert (scene.frame_current, scene.frame_subframe) == (1, 0.)
        assert not scene.rigidbody_world.point_cache.is_baked
        scene.frame_set(7, subframe=.25)
        assert context_state() == before

    def after_native_bake(self, stage, callback):
        result = original_timed(self, stage, callback)
        if stage == "native_bake":
            raise RuntimeError("Injected fault after the synchronous native bake completed")
        return result

    proposal = prepared("BAKE")
    rigid_body._Boundary._timed = after_native_bake
    try:
        call("cache", proposal)
    except BridgeError as error:
        assert error.code == "OPERATION_FAILED" and error.context["primary_error_type"] == "RuntimeError"
        assert error.context["possible_mutation"] and error.context["cache_operation_started"]
        assert not error.context["cache_operation_verified"]
        assert error.context["frame_recovery"]["verified"], error.to_dict()
        post_native_failure = error.to_dict()
    else:
        raise AssertionError("Injected native-tail fault was ignored")
    finally:
        rigid_body._Boundary._timed = original_timed
    assert context_state() == before and scene.rigidbody_world.point_cache.is_baked
    execute("FREE")
    complete_evidence = {"blender_version": bpy.app.version_string,
          "inventory": inventory, "base_vertices": snapshot["base_vertices"],
          "whole_world_names_verified": True, "protected_mesh_change_detected": True,
          "scope_reads_preserved_context": True, "rejections": rejections,
          "registered_runtime_tools": len(registry.list_tools()), "registered_runtime_history": registered_runtime_history,
          "native_checkpoint_scene_reference": native_checkpoint_reference,
          "canonical_queue_final_hook_available": queue_final_hook_available,
          "canonical_queue_scope_stop_evidence": queued_scope_stops,
          "canonical_queue_native_stage_stops": native_stage_stops,
          "typed_cache_lifecycle": {"first_bake": first_bake, "first_free": first_free,
                                    "changed_gravity_bake": zero_bake, "second_free": second_free,
                                    "invalidation": invalidated},
          "permission_denied_before_writes": True, "live_stop_evidence": live_stops,
          "owner_revocation_inside_live_provider": owner_failures,
          "post_native_failure": post_native_failure,
          "release_readiness": "NOT_ASSESSED"}
    full_path = Path(tempfile.gettempdir()) / "rigid-body-scope-complete-evidence.json"
    full_bytes = (json.dumps(complete_evidence, indent=2)+"\n").encode()
    full_path.write_bytes(full_bytes)

    def compact(raw):
        if isinstance(raw, dict):
            result = {key: compact(value) for key, value in raw.items() if key != "native_intervals"}
            if "native_intervals" in raw:
                intervals = raw["native_intervals"]
                result["native_interval_summary"] = {"records": len(intervals),
                    "maximum_record_seconds": max((row["seconds"] for row in intervals), default=0.),
                    "complete_records_retained_in_evidence_file": True,
                    "nested_timing_records_are_not_additive": True}
            return result
        return [compact(value) for value in raw] if isinstance(raw, list) else raw

    evidence = {**compact(complete_evidence), "complete_evidence_file": str(full_path),
                "complete_evidence_file_sha256": hashlib.sha256(full_bytes).hexdigest()}
    payload = json.dumps(evidence, separators=(",", ":"))
    assert len(payload.encode()) < 60000, "Keep the runner's bounded marker extraction intact"
    print("BLENDER_RIGID_BODY_SCOPE_OK " + payload, flush=True)


if __name__ == "__main__":
    main()
