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


def native_exact_comparisons(runtime, scene, bodies, params, grants):
    """Real Object IDProperty drift around the registered public cache handler.

    Checkpoints retain their existing executor behavior. These observations count
    the selected domain native intervals, not every Blender/checkpoint side effect.
    """
    target, key = bodies[0], "_bridge_owned_rigid_exact_value"
    assert key not in target
    original_check = rigid_body._Boundary.check
    original_interval = rigid_body._Boundary._native_interval
    previous_permissions = (runtime.permissions, runtime.executor.permissions)
    initial_context = context_state()
    transitions = (("bool_to_int", False, 0), ("int_to_float", 0, 0.),
                   ("signed_zero", 0., -0.), ("nested_bool_to_int", {"value": False}, {"value": 0}))
    scenarios = [(name, old, new, stage, False) for name, old, new in transitions
                 for stage in ("provider_before_native", "after_reset_return")]
    scenarios.append(("nested_bool_to_int", {"value": False}, {"value": 0}, "after_reset_return", True))
    records = []

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def fingerprint(value):
        return hashlib.sha256(canonical(value).encode()).hexdigest()

    def projected(snapshot):
        # This is the actual Object.custom projection captured by scope.snapshot.
        # The Mesh custom reader already type-tags values and is not this repro.
        objects = snapshot["protected"][8]
        states = [dict(state) for state, _body in objects if dict(state)["name"] == target.name]
        assert len(states) == 1
        return dict(states[0]["custom"])[key]

    def describe(raw, expected, *, captured=False):
        if isinstance(expected, dict):
            if captured:
                assert isinstance(raw, tuple) and [name for name, _value in raw] == ["value"]
                leaf = dict(raw)["value"]
            else:
                assert hasattr(raw, "keys") and list(raw.keys()) == ["value"], type(raw).__name__
                leaf = raw["value"]
            expected = expected["value"]
        else:
            leaf = raw
        assert type(leaf) is type(expected), ("Native IDProperty scalar type was not preserved", type(leaf).__name__, type(expected).__name__)
        assert leaf == expected
        if type(expected) is float:
            assert leaf.hex() == expected.hex(), (leaf.hex(), expected.hex())
        return {"container_type": type(raw).__name__, "leaf_type": type(leaf).__name__,
                "leaf_value": leaf, "leaf_float_hex": leaf.hex() if type(leaf) is float else None}

    for name, old, new, injection_stage, native_failure in scenarios:
        assert key not in target and not scene.rigidbody_world.point_cache.is_baked
        target[key] = old
        raw_before = describe(target[key], old)
        captured_before = describe(projected(scope.snapshot(bpy, scene, params)), old, captured=True)
        proposal = {"scene_name": scene.name, **params, "operation": "BAKE", "frame_start": 2, "frame_end": 3}
        preview = runtime.dispatch("rigid_body.cache_preview", proposal)
        proposal["expected_fingerprint"] = preview["expected_fingerprint"]
        observed = {"armed": False, "fired": False, "entries": [], "returns": [], "boundary": None}
        native_fault = RuntimeError("Owned native exact-comparison fault after reset return")

        def inject(boundary, *, observed=observed, old=old, new=new):
            assert not observed["fired"]
            expected = boundary.expected
            expected_value = projected(expected)
            expected_description = describe(expected_value, old, captured=True)
            # Recreating the actual native property avoids existing-slot coercion.
            del target[key]
            target[key] = new
            raw_after = describe(target[key], new)
            actual = scope.snapshot(bpy, scene, params)
            actual_value = projected(actual)
            captured_after = describe(actual_value, new, captured=True)
            assert expected["protected"] == actual["protected"], "This case must expose Python's conflated equality"
            assert canonical(expected["protected"]) != canonical(actual["protected"])
            assert canonical(expected_value) != canonical(actual_value)
            observed.update(fired=True, raw_after=raw_after, captured_after=captured_after,
                captured_expected=expected_description, captured_old_value=expected_value, captured_new_value=actual_value,
                protected_python_equal=True, protected_canonical_different=True,
                protected_before_sha256=fingerprint(expected["protected"]), protected_after_sha256=fingerprint(actual["protected"]),
                native_entries_at_injection=list(observed["entries"]), native_returns_at_injection=list(observed["returns"]))

        def check(boundary, *, observed=observed, old=old):
            if observed["boundary"] is None:
                observed["boundary"] = boundary
                observed["armed"] = True  # cache() has retained its real baseline.
                describe(projected(boundary.expected), old, captured=True)
            return original_check(boundary)

        def provider(*, observed=observed, injection_stage=injection_stage, inject=inject):
            if observed["armed"] and not observed["fired"] and injection_stage == "provider_before_native":
                inject(observed["boundary"])
            return dict(grants)

        def interval(boundary, stage, callback, *, observed=observed, injection_stage=injection_stage,
                     native_failure=native_failure, native_fault=native_fault, inject=inject):
            def actual_native():
                observed["entries"].append(stage)
                result = callback()  # Real native implementation, including its writes.
                observed["returns"].append(stage)
                return result

            result = original_interval(boundary, stage, actual_native)
            if stage == "same_value_world_reset" and not observed["fired"] and injection_stage == "after_reset_return":
                inject(boundary)
                if native_failure:
                    raise native_fault
            return result

        live_permissions = PermissionManager(provider)
        runtime.permissions = runtime.executor.permissions = live_permissions
        rigid_body._Boundary.check, rigid_body._Boundary._native_interval = check, interval
        try:
            try:
                runtime.dispatch("rigid_body.cache", proposal)
            except BridgeError as error:
                assert observed["fired"] and observed["boundary"] is not None
                details = error.context
                assert error.code == ("OPERATION_FAILED" if native_failure else "INVALID_ARGUMENT"), error.to_dict()
                assert details["primary_error_type"] == ("RuntimeError" if native_failure else "BridgeError")
                if native_failure:
                    assert error.__cause__ is native_fault
                expected_entries = [] if injection_stage == "provider_before_native" else [
                    "cache_range_setter", "cache_range_setter", "same_value_world_reset"]
                assert observed["entries"] == observed["returns"] == expected_entries
                assert observed["entries"] == observed["native_entries_at_injection"]
                assert observed["returns"] == observed["native_returns_at_injection"]
                assert observed["boundary"].started is (injection_stage == "after_reset_return")
                assert details["possible_mutation"] is (injection_stage == "after_reset_return")
                assert details["cache_operation_started"] is False and details["cache_operation_verified"] is False
                assert details["final_authority_and_scope_verified"] is False
                for field in ("range_recovery", "frame_recovery"):
                    assert details[field]["attempted"] is False and details[field]["verified"] is False
                    assert details[field]["error_code"] == "INVALID_ARGUMENT", details[field]
                assert context_state() == initial_context
                expected_range = (1, 3) if injection_stage == "provider_before_native" else (2, 3)
                assert (scene.rigidbody_world.point_cache.frame_start, scene.rigidbody_world.point_cache.frame_end) == expected_range
                assert not scene.rigidbody_world.point_cache.is_baked
                final_raw = describe(target[key], new)
                final_scope = scope.snapshot(bpy, scene, params)
                describe(projected(final_scope), new, captured=True)
                # The old protected CAS remains retained; drift was not adopted.
                describe(projected(observed["boundary"].expected), old, captured=True)
                record = {"case": name, "injection_stage": injection_stage, "native_failure": native_failure,
                    "entry": "ACTUAL_REGISTERED_RUNTIME_DISPATCH", "raw_before": raw_before,
                    "captured_before": captured_before, "raw_after": observed["raw_after"],
                    "captured_after": observed["captured_after"], "captured_old_value": observed["captured_old_value"],
                    "captured_new_value": observed["captured_new_value"], "final_raw": final_raw,
                    "protected_python_equal": True, "protected_canonical_different": True,
                    "protected_before_sha256": observed["protected_before_sha256"],
                    "protected_after_sha256": observed["protected_after_sha256"],
                    "actual_native_entries": observed["entries"], "actual_native_returns": observed["returns"],
                    "selected_native_calls_after_injection": 0, "frozen_old_property_retained": True,
                    "retained_range": list(expected_range), "retained_frame": [scene.frame_current, scene.frame_subframe],
                    "native_fault_identity_preserved": native_failure and error.__cause__ is native_fault,
                    "error": error.to_dict(), "executor_checkpoints_separate_from_domain_native_counts": True}
            else:
                raise AssertionError("Registered cache ignored real typed/signed-zero protected drift")
        finally:
            rigid_body._Boundary.check, rigid_body._Boundary._native_interval = original_check, original_interval
            runtime.permissions, runtime.executor.permissions = previous_permissions
        # All assertions precede these disclosed new fixture writes. They are not
        # production compensation, recovery, or continuation of failed authority.
        del target[key]
        scene.rigidbody_world.point_cache.frame_start = 1
        scene.rigidbody_world.point_cache.frame_end = 3
        scene.frame_set(7, subframe=.25)
        bpy.context.view_layer.update()
        assert context_state() == initial_context and key not in target
        record["explicit_fixture_reset_after_assertions"] = {"property_removed": True, "range": [1, 3],
            "frame": [7, .25], "product_cleanup_or_recovery_claim": False}
        records.append(record)
        print("RIGID_EXACT_COMPARISON_CASE " + canonical(record), flush=True)
    assert len(records) == 9
    return records


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

    # Keep the original five successful registered-history assertions above.
    native_exact_comparison_cases = native_exact_comparisons(runtime, scene, bodies, params, grants)

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
          "native_exact_comparison_cases": native_exact_comparison_cases,
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
    evidence["native_exact_comparison_cases"] = {"case_count": len(native_exact_comparison_cases),
        "provider_before_domain_native": 4, "after_real_reset_return": 4, "after_return_primary_runtime_error": 1,
        "actual_native_property_types_and_scope_values_proven": True,
        "python_equal_but_canonical_different": True, "complete_records_retained_in_evidence_file": True}
    payload = json.dumps(evidence, separators=(",", ":"))
    assert len(payload.encode()) < 60000, "Keep the runner's bounded marker extraction intact"
    print("BLENDER_RIGID_BODY_SCOPE_OK " + payload, flush=True)


if __name__ == "__main__":
    main()
