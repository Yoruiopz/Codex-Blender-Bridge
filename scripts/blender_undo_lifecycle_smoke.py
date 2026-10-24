"""Native undo/redo invalidation in an isolated interactive (not background) Blender."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace as NS

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.checkpoints import MARKER_KEY, CheckpointManager  # noqa: E402
from blender_codex_bridge.command_queue import CommandQueue, QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.executor import MainThreadExecutor  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.state import BridgeState  # noqa: E402
from blender_codex_bridge.task_plans import get_task_plans  # noqa: E402
from blender_codex_bridge.tool_registry import ToolContext, ToolRegistry, check_final_mutation  # noqa: E402
from blender_codex_bridge.tools import artist_loop, batch  # noqa: E402
from blender_codex_bridge.tools._object_rna_mutation import Boundary  # noqa: E402


def _checkpoint_preflight_case(entry, stop):
    calls = []

    class MeasuredManager(CheckpointManager):
        def before_modification(self, tool, **kwargs):
            calls.append("before")
            return super().before_modification(tool, **kwargs)

        def _stamp(self, blender, **kwargs):
            calls.append("marker")
            return super()._stamp(blender, **kwargs)

        def _snapshot(self, blender, label, **kwargs):
            calls.append("native_undo_snapshot")
            return super()._snapshot(blender, label, **kwargs)

    manager, state = MeasuredManager(), BridgeState()
    registry = ToolRegistry(enabled_toolsets=("objects",))
    batch.register_tools(registry)
    registry.enable_toolset("batch")
    lifetime = RequestLifetime(ConnectionLifetime())
    request = Request("checkpoint-native-" + entry + stop, "object.fixture", {}, _lifecycle=lifetime)
    queued = QueuedRequest(request, deadline=float("inf"))
    assert queued.try_start()
    reads = {"provider": 0, "scope": 0}

    def stop_now():
        if stop in {"queued", "provider_queued"}:
            queued.cancel_pending(BridgeError("TIMEOUT", "Fixture caller canceled"))
        elif stop == "queued_deadline":
            queued.deadline = 0.
        elif stop == "disconnect":
            lifetime.connection.disconnected.set()
        elif stop == "lifetime_deadline":
            lifetime.deadline = 0.
        elif stop == "toolset":
            registry.disable_toolset("objects")
        elif stop == "pause":
            state.set_paused(True)
        else:
            state.set_emergency_stopped(True)

    def provider():
        reads["provider"] += 1
        if stop == "provider_queued" and reads["provider"] == (2 if entry == "batch" else 1):
            stop_now()
        return {"TRANSFORM_OBJECTS": True}

    def resolve(_context, _params):
        reads["scope"] += 1
        if stop != "provider_queued" and reads["scope"] == (2 if entry == "batch" else 1):
            stop_now()
        return {"scope_complete": True}

    def edit(_context, _params):
        calls.append("handler")
        bpy.data.objects["Cube"].location.x += 1.

    registry.register("object.fixture", edit, toolset="objects", modifies=True,
                      permissions=(Permission.TRANSFORM_OBJECTS,), protected_scope_resolver=resolve)
    if stop != "provider_queued":
        get_task_plans(state).protection = {"fixture_policy": True}
    executor = MainThreadExecutor(command_queue=CommandQueue(), registry=registry, state=state,
                                  permissions=PermissionManager(provider), checkpoints=manager)
    markers = {scene.name: scene.get(MARKER_KEY) for scene in bpy.data.scenes}
    location = tuple(bpy.data.objects["Cube"].location)
    if entry == "executor":
        response = executor.execute_request(request, check_cancelled=queued.check_active)
        assert not response.ok, response.to_dict()
        code = response.error["code"]
    else:
        context = executor.context
        context.check_cancelled = context.check_final_request = queued.check_active
        context.request_lifecycle = lifetime
        try:
            batch.batch_execute(context, {"steps": [{"method": "object.fixture"}]})
        except BridgeError as error:
            assert not error.context["failed_step_started"] and not error.context["execution_started"]
            code = error.code
        else:
            raise AssertionError("Stopped batch entered its writer")
    assert code == {"toolset": "TOOLSET_DISABLED", "pause": "AGENT_PAUSED", "emergency": "EMERGENCY_STOPPED"}.get(stop, "TIMEOUT"), code
    assert not calls, calls
    assert markers == {scene.name: scene.get(MARKER_KEY) for scene in bpy.data.scenes}
    assert tuple(bpy.data.objects["Cube"].location) == location
    assert manager._pending is None and not manager.list()


def checkpoint_preflight_authority():
    """Actual native markers/undo remain untouched by rejected new requests."""
    tested = 0
    for entry in ("executor", "batch"):
        for stop in ("queued", "queued_deadline", "disconnect", "lifetime_deadline", "toolset", "pause", "emergency", "provider_queued"):
            _checkpoint_preflight_case(entry, stop)
            tested += 1
    return {"new_request_denied_before_native_marker_and_undo_push": tested}


def _checkpoint_internal_case(route, where, kind):
    """Fault injection surrounds actual native Scene readers and owned writes."""
    scene = bpy.context.scene
    prior_marker = scene.get(MARKER_KEY)
    extra = bpy.data.scenes.new("Owned checkpoint authority fixture")
    writes, pushes = [], []
    enabled = False
    registry = ToolRegistry()
    registry.register("fixture.edit", lambda *_: None, modifies=True)
    lifetime = RequestLifetime(ConnectionLifetime())
    request = Request("internal-checkpoint-" + route + where + kind, "fixture.edit", {}, _lifecycle=lifetime)
    queued = QueuedRequest(request, deadline=float("inf"))
    assert queued.try_start()

    def stop():
        if kind == "cancel":
            queued.cancel_pending(BridgeError("TIMEOUT", "Fixture canceled inside native marker reader"))
        else:
            lifetime.deadline = 0.

    class SceneReader:
        def __init__(self, native):
            self.native = native

        def __getattr__(self, name):
            return getattr(self.native, name)

        def __contains__(self, key):
            return key in self.native

        def get(self, key, default=None):
            value = self.native.get(key, default)
            if enabled and where == "marker_read" and key == MARKER_KEY:
                stop()
            return value

        def __delitem__(self, key):
            del self.native[key]
            writes.append("delete")
            if enabled and where == "after_delete":
                stop()

        def __setitem__(self, key, value):
            self.native[key] = value
            writes.append("set")

    def push(**kwargs):
        pushes.append("native_push")
        return bpy.ops.ed.undo_push(**kwargs)

    class NativeReaderManager(CheckpointManager):
        def _ensure_undo_enabled(self, *, require_object_mode=True):
            blender = super()._ensure_undo_enabled(require_object_mode=require_object_mode)
            if not enabled:
                return blender
            return NS(context=NS(scene=SceneReader(blender.context.scene), mode=blender.context.mode,
                                 preferences=blender.context.preferences),
                      data=NS(scenes=[SceneReader(item) for item in blender.data.scenes]),
                      ops=NS(ed=NS(undo_push=push)))

        def _step_limit(self, blender):
            result = super()._step_limit(blender)
            if enabled and where == "preference_read":
                stop()
            return result

    manager = NativeReaderManager()
    try:
        previous = manager.create("Earlier real native checkpoint")
        extra[MARKER_KEY] = manager._prefix + "a" * 32
        before = {item.name: item.get(MARKER_KEY) for item in bpy.data.scenes}
        state = BridgeState()
        context = ToolContext(state, PermissionManager(lambda: {}), registry, manager,
                              request_lifecycle=lifetime, check_final_request=queued.check_active)
        enabled = True
        try:
            if route == "create":
                manager.create("Rejected real native checkpoint", before_write=lambda: check_final_mutation(context, "fixture.edit"))
            else:
                manager.before_modification("fixture.edit", before_write=lambda: check_final_mutation(context, "fixture.edit"))
        except BridgeError as error:
            assert error.code == "TIMEOUT" and error.context["checkpoint_authority_rejected"], error.to_dict()
            evidence = error.context["checkpoint_bookkeeping"]
            error_context = error.context
        else:
            raise AssertionError("Native checkpoint continued after owner loss")
        assert not pushes and evidence["native_snapshots_completed"] == 0
        assert manager.list() == [previous]
        if where == "marker_read":
            assert not writes and evidence["marker_writes_completed"] == 0
            assert before == {item.name: item.get(MARKER_KEY) for item in bpy.data.scenes}
        elif where == "after_delete":
            assert writes == ["delete"] and evidence["marker_writes_completed"] == 1
            assert error_context["possible_mutation"] and not evidence["compensation_performed"]
            assert sum(item.get(MARKER_KEY) is not None for item in (scene, extra)) == 1
        else:
            assert writes == ["delete", "delete", "set"] and evidence["marker_writes_completed"] == 3
            assert evidence["next_write_rejected"] == "native_undo_push"
    finally:
        # This is owned fixture teardown, never request-time compensation.
        if prior_marker is None:
            if MARKER_KEY in scene:
                del scene[MARKER_KEY]
        else:
            scene[MARKER_KEY] = prior_marker
        bpy.data.scenes.remove(extra)


def checkpoint_internal_authority():
    tested = 0
    for route in ("before", "create"):
        for where in ("marker_read", "after_delete", "preference_read"):
            for kind in ("cancel", "expiry"):
                _checkpoint_internal_case(route, where, kind)
                tested += 1
    return {"native_checkpoint_internal_owner_loss_cases": tested,
            "partial_marker_bookkeeping_reported_without_compensation": True}


def _handler_entry_case(route):
    baseline = bpy.data.objects["Cube"].location.x
    calls, snapshots = [], []
    first_entered, scope_reads = [], []
    registry = ToolRegistry(enabled_toolsets=("objects",))
    batch.register_tools(registry)
    registry.enable_toolset("batch")
    state = BridgeState()
    lifetime = RequestLifetime(ConnectionLifetime())
    request = Request("native-last-handler-" + route, "object.fixture", {}, _lifecycle=lifetime)
    queued = QueuedRequest(request, deadline=float("inf"))
    assert queued.try_start()

    def cancel():
        queued.cancel_pending(BridgeError("TIMEOUT", "Canceled in last native handler preflight"))

    def provider():
        if route == "direct" or (route == "batch_second" and first_entered):
            cancel()
        return {"TRANSFORM_OBJECTS": True}

    def resolve(_context, _params):
        scope_reads.append(True)
        if route == "post_checkpoint" and len(scope_reads) == 2:
            cancel()
        return {"scope_complete": True}

    class Manager(CheckpointManager):
        def before_modification(self, method, **kwargs):
            snapshots.append("before")
            return super().before_modification(method, **kwargs)

        def after_modification(self, method):
            snapshots.append("after")
            return super().after_modification(method)

    manager = Manager()

    def edit(_context, _params):
        calls.append("first")
        first_entered.append(True)
        bpy.data.objects["Cube"].location.x = baseline + 1.
        return {"object": "Cube"}

    registry.register("object.fixture", edit, toolset="objects", modifies=True,
                      permissions=(Permission.TRANSFORM_OBJECTS,), protected_scope_resolver=resolve)
    registry.register("object.second", lambda *_: calls.append("late second"), toolset="objects", modifies=True,
                      permissions=(Permission.TRANSFORM_OBJECTS,))
    executor = MainThreadExecutor(command_queue=CommandQueue(), registry=registry, state=state,
                                  permissions=PermissionManager(provider), checkpoints=manager)
    context = executor.context
    context.request_lifecycle, context.check_final_request = lifetime, queued.check_active
    if route == "post_checkpoint":
        get_task_plans(state).protection = {"fixture": True}
        response = executor.execute_request(request, check_cancelled=queued.check_active)
        assert not response.ok and response.error["code"] == "TIMEOUT"
        assert not response.error["context"]["requested_edit_started"]
    else:
        try:
            if route == "direct":
                registry.dispatch("object.fixture", {}, context)
            else:
                batch.batch_execute(context, {"steps": [{"method": "object.fixture"}, {"method": "object.second"}]})
        except BridgeError as error:
            assert error.code == "TIMEOUT", error.to_dict()
            if route == "batch_second":
                assert not error.context["failed_step_started"] and error.context["completed_steps"] == 1
        else:
            raise AssertionError("Stopped native call entered a late handler")
    assert calls == (["first"] if route == "batch_second" else [])
    assert snapshots == {"direct": [], "post_checkpoint": ["before"], "batch_second": ["before", "after"]}[route]
    assert registry.executing_mutators == get_task_plans(state).executing_mutators == 0
    if route == "batch_second":
        assert bpy.data.objects["Cube"].location.x == baseline + 1.
        assert manager.restore_operation()["snapshot_marker_verified"]
    assert bpy.data.objects["Cube"].location.x == baseline


def handler_entry_authority():
    for route in ("direct", "post_checkpoint", "batch_second"):
        _handler_entry_case(route)
    return {"native_final_handler_entry_routes": ["direct", "post_checkpoint", "batch_second"],
            "earlier_batch_writer_recovery_retained": True}


def artist_history_handles(runtime):
    """Manual/native recovery cannot revive handles for an identical pre-state."""
    manager = runtime.checkpoints
    manager.clear()
    permissions = PermissionManager(lambda: {"INSPECT_SCENE": True, "TRANSFORM_OBJECTS": True})
    runtime.permissions = runtime.executor.permissions = permissions
    runtime.registry.enable_toolset("objects")
    working = bpy.data.objects.new("Artist History Working", None)
    bpy.context.scene.collection.objects.link(working)
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    working.select_set(True)
    bpy.context.view_layer.objects.active = working
    bpy.context.view_layer.update()
    plan = runtime.dispatch("task.plan.set", {
        "goal": "Revise the prop while retaining protected Cube",
        "steps": [{"id": "revise", "description": "Preview and compare placement"}],
        "protected_objects": ["Cube"],
    })
    revision = plan["plan"]["revision"]
    runtime.dispatch("task.plan.capture", {"fields": ["transforms", "hierarchy"]})
    runtime.dispatch("task.plan.enforce", {"enabled": True, "expected_revision": revision})
    store = get_task_plans(runtime.state)
    expected_plan, expected_protection, expected_baseline = store.plan, store.protection, store.baseline

    def pair():
        reference = runtime.dispatch("task.reference.resolve", {"source": "selection"})["reference_id"]
        preview = runtime.dispatch("task.plan.preview_transform", {
            "reference_id": reference, "expected_revision": revision, "location": [5., 0., 0.], "step_id": "revise",
        })["preview_id"]
        return reference, preview

    def boundary():
        return Boundary(bpy, runtime.executor.context, "transform.set", bpy.data.objects["Artist History Working"], transform=True)

    def retained():
        assert get_task_plans(runtime.state) is store
        assert store.plan is expected_plan and store.protection is expected_protection
        assert store.baseline is expected_baseline and store.inspect()["protected_scope_enforced"]
        assert store.executing_mutators == 0

    def stale(reference, preview):
        before = tuple(bpy.data.objects["Artist History Working"].location)
        for method, params in (
            ("task.plan.preview_transform", {"reference_id": reference, "expected_revision": revision, "location": [8., 0., 0.]}),
            ("task.plan.apply_preview", {"preview_id": preview, "expected_revision": revision}),
        ):
            try:
                runtime.dispatch(method, params)
            except BridgeError as error:
                assert error.code == "INVALID_ARGUMENT", error.to_dict()
            else:
                raise AssertionError("Native history revived a stale artist handle")
        assert tuple(bpy.data.objects["Artist History Working"].location) == before
        retained()

    # Retain a real outer executor receipt and a measured protected-only
    # observation before native history moves. Neither is a completion claim.
    _, receipt_preview = pair()
    applied = runtime.dispatch("task.plan.apply_preview", {
        "preview_id": receipt_preview, "expected_revision": revision})
    receipt_operation = applied["operation"]["operation_id"]
    receipt_id = applied["step_receipt_id"]

    def receipt():
        entries = runtime.dispatch("task.plan.inspect")["step_evidence"]["receipts"]
        entry = next(item for item in entries if item["receipt_id"] == receipt_id)
        assert entry["operation_id"] == receipt_operation
        assert entry["success"] and entry["outcome"] == "completed"
        assert store.plan["steps"][0]["status"] == "pending"
        return entry

    runtime.dispatch("task.plan.compare", {"step_id": "revise", "expected_revision": revision})
    assert receipt()["protected_observation"]["validity"] == "recorded"
    assert receipt()["history_state"] == "current_runtime_generation"
    bpy.data.objects["Artist History Working"].location.x = 0.
    bpy.ops.ed.undo_push(message="Artist history exact zero pre-state")
    zero_reference, zero_preview = pair()
    zero_context, zero_profile = artist_loop._context(bpy), artist_loop._profile(boundary())
    working.location.x = 1.
    bpy.ops.ed.undo_push(message="Artist history alternate one pre-state")
    one_reference, one_preview = pair()
    one_context, one_profile = artist_loop._context(bpy), artist_loop._profile(boundary())
    active_boundary = boundary()
    generation = store.protection_generation
    assert bpy.ops.ed.undo() == {"FINISHED"}
    assert store.protection_generation > generation and not store.references and not store.previews
    assert bpy.data.objects["Artist History Working"].location.x == 0.
    assert receipt()["history_state"] == "historical_after_generation_change"
    assert receipt()["protected_observation"]["validity"] == "stale"
    undo_context_same = artist_loop._context(bpy) == zero_context
    undo_profile_same = artist_loop._profile(boundary()) == zero_profile
    stale(zero_reference, zero_preview)
    try:
        active_boundary.write(active_boundary.obj, "location", (9., 0., 0.))
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT", error.to_dict()
    else:
        raise AssertionError("A pre-undo Boundary wrote after the policy epoch changed")
    assert bpy.data.objects["Artist History Working"].location.x == 0.
    redo_reference, redo_preview = pair()
    runtime.dispatch("task.plan.compare", {"step_id": "revise", "expected_revision": revision})
    assert receipt()["protected_observation"]["validity"] == "recorded"
    generation = store.protection_generation
    assert bpy.ops.ed.redo() == {"FINISHED"}
    assert store.protection_generation > generation and not store.references and not store.previews
    assert bpy.data.objects["Artist History Working"].location.x == 1.
    assert receipt()["protected_observation"]["validity"] == "stale"
    redo_context_same = artist_loop._context(bpy) == one_context
    redo_profile_same = artist_loop._profile(boundary()) == one_profile
    stale(one_reference, one_preview)
    stale(redo_reference, redo_preview)

    # Trusted fixture recovery exercises the handler's recovery_in_progress path;
    # the public whole-scene undo tool remains unreviewed/denied while armed.
    assert manager.before_modification("artist working-only recovery fixture")
    bpy.data.objects["Artist History Working"].location.x = 2.
    assert manager.after_modification("artist working-only recovery fixture")
    own_reference, own_preview = pair()
    generation = store.protection_generation
    assert manager.restore_operation()["snapshot_marker_verified"]
    assert store.protection_generation > generation and not store.references and not store.previews
    assert bpy.data.objects["Artist History Working"].location.x == 1.
    stale(own_reference, own_preview)
    comparison = runtime.dispatch("task.plan.compare")["evidence"]
    assert comparison["status"] == "unchanged_within_scope" and comparison["coverage_complete"]
    return {"manual_undo_redo_artist_handles_invalidated": True,
            "known_bridge_recovery_artist_handles_invalidated": True,
            "actual_native_history_retains_step_operation_provenance": True,
            "native_undo_redo_invalidates_step_protected_observations": True,
            "step_status_remains_user_claim": True,
            "armed_plan_protection_baseline_retained": True,
            "pre_undo_boundary_epoch_rejected": True,
            "undo_same_native_context": undo_context_same, "undo_same_authored_profile": undo_profile_same,
            "redo_same_native_context": redo_context_same, "redo_same_authored_profile": redo_profile_same}


def run():
    try:
        assert not bpy.app.background
        blender_codex_bridge.register()
        checkpoint_authority = checkpoint_preflight_authority()
        checkpoint_authority.update(checkpoint_internal_authority())
        checkpoint_authority.update(handler_entry_authority())
        manager = get_runtime().checkpoints
        inspection = PermissionManager(lambda: {"INSPECT_SCENE": True})
        get_runtime().permissions = get_runtime().executor.permissions = inspection
        evidence = get_runtime().dispatch("scene.snapshot", {"object_names": ["Cube"]})
        baseline = bpy.data.objects["Cube"].location.x
        manager.create("Measured snapshot baseline")
        assert manager.before_modification("first")
        bpy.data.objects["Cube"].location.x = 1.0
        assert manager.after_modification("first")
        assert manager.before_modification("second_with_native_steps")
        bpy.data.objects["Cube"].location.x = 2.0
        bpy.ops.ed.undo_push(message="Fixture internal native step")
        bpy.ops.transform.translate("EXEC_DEFAULT", True, value=(1.0, 0.0, 0.0))
        assert manager.after_modification("second_with_native_steps")
        assert bpy.data.objects["Cube"].location.x == 3.0
        result = get_runtime().dispatch(
            "checkpoint.undo_last",
            {
                "confirm_global_undo": True,
                "restore_snapshot": True,
            },
        )
        assert result["snapshot_marker_verified"] and result["undo_steps"] >= 3
        assert bpy.data.objects["Cube"].location.x == 1.0
        assert manager.restore_operation()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        comparison = get_runtime().dispatch("scene.compare", {"snapshot_id": evidence["snapshot_id"]})
        assert comparison["status"] == "unchanged_within_scope" and comparison["coverage_complete"]
        assert manager.restore_last()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        # A global named checkpoint remains usable after an Edit Mode round trip.
        import bmesh

        vertices_before = [tuple(v.co) for v in bpy.data.objects["Cube"].data.vertices]
        manager.create("Before editor-specific changes")
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="EDIT")
        assert not manager.before_modification("editor_mesh_change")
        mesh = bmesh.from_edit_mesh(bpy.data.objects["Cube"].data)
        mesh.verts.ensure_lookup_table()
        mesh.verts[0].co.x += 0.7
        bmesh.update_edit_mesh(bpy.data.objects["Cube"].data)
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="OBJECT")
        assert manager.restore_last()["snapshot_marker_verified"]
        assert bpy.context.mode == "OBJECT"
        assert [tuple(v.co) for v in bpy.data.objects["Cube"].data.vertices] == vertices_before

        def fail_after_mutating(_context, _params):
            bpy.data.objects["Cube"].location.x = 6.0
            raise RuntimeError("injected unexpected handler failure")

        get_runtime().registry.register("fixture.fail", fail_after_mutating, modifies=True)
        try:
            get_runtime().dispatch("fixture.fail")
        except BridgeError as error:
            assert error.context["undo_boundary_finalized"] and error.context["execution_started"]
        else:
            raise AssertionError("Injected handler failure succeeded")
        assert bpy.data.objects["Cube"].location.x == 6.0
        assert manager.restore_operation()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        # Restore a named checkpoint directly over multiple logical operations.
        manager.create("Multi operation baseline")
        for coordinate in (4.0, 5.0):
            assert manager.before_modification("data_edit")
            bpy.data.objects["Cube"].location.x = coordinate
            assert manager.after_modification("data_edit")
        assert manager.restore_last()["snapshot_marker_verified"]
        assert bpy.data.objects["Cube"].location.x == baseline
        # An evicted target must fail and return to the measured guard, not claim success.
        previous_limit = bpy.context.preferences.edit.undo_steps
        bpy.context.preferences.edit.undo_steps = 2
        try:
            assert manager.before_modification("evicted")
            bpy.data.objects["Cube"].location.x = 9.0
            assert manager.after_modification("evicted")
            for index in range(8):
                bpy.data.objects["Cube"].location.x = 10.0 + index
                bpy.ops.ed.undo_push(message="Eviction fixture")
            try:
                manager.restore_operation()
            except BridgeError as error:
                assert error.context["return_to_guard_verified"], error
            else:
                raise AssertionError("Evicted snapshot was reported restored")
            assert bpy.data.objects["Cube"].location.x == 17.0
        finally:
            bpy.context.preferences.edit.undo_steps = previous_limit
        manager.clear()
        manager.create("Disposable lifecycle fixture")
        assert manager.before_modification("fixture.data_edit")
        bpy.data.objects["Cube"].location.x = 2.0
        manager.after_modification("fixture.data_edit")
        bpy.ops.ed.undo_push(message="Manual fixture snapshot")
        assert manager.list()
        assert bpy.ops.ed.undo() == {"FINISHED"}
        assert manager.list() == []
        before = bpy.data.objects["Cube"].location.x
        try:
            manager.restore_operation()
        except BridgeError as error:
            assert error.code == "OPERATION_FAILED" and "No tracked" in error.message
        else:
            raise AssertionError("Stale bridge history survived native undo")
        assert bpy.data.objects["Cube"].location.x == before
        assert bpy.ops.ed.redo() == {"FINISHED"}
        assert manager.list() == []
        artist_handles = artist_history_handles(get_runtime())
        # Re-registration must not leak duplicate native handlers.
        blender_codex_bridge.unregister()
        blender_codex_bridge.register()
        from blender_codex_bridge.runtime import _before_external_undo_redo

        assert bpy.app.handlers.undo_pre.count(_before_external_undo_redo) == 1
        assert bpy.app.handlers.redo_pre.count(_before_external_undo_redo) == 1
        blender_codex_bridge.unregister()
        assert _before_external_undo_redo not in bpy.app.handlers.undo_pre
        assert _before_external_undo_redo not in bpy.app.handlers.redo_pre
        print(
            "BLENDER_UNDO_LIFECYCLE_OK "
            + json.dumps(
                {
                    "blender": bpy.app.version_string,
                    **checkpoint_authority,
                    **artist_handles,
                    "native_undo_redo_invalidation": True,
                    "stale_bridge_undo_refused_without_mutation": True,
                    "handler_lifecycle_verified": True,
                    "object_mode_transform_snapshot_restoration_verified": True,
                    "internal_native_steps_and_checkpoint_restore_verified": True,
                    "evicted_target_returns_to_guard": True,
                    "global_checkpoint_after_edit_mode_round_trip": True,
                    "unexpected_partial_failure_has_recoverable_snapshot": True,
                    "full_recovery_acceptance_verified": False,
                "numeric_baseline_comparison_after_recovery": True,
                    "project_saved": False,
                }
            ),
            flush=True,
        )
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
