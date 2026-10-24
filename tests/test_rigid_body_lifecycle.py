"""Adversarial authority, stale-cache, partial-effect and context recovery cases."""

from __future__ import annotations

import asyncio
import importlib
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def rigid_case(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.rigid_body")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions_module = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    errors = importlib.import_module(f"{addon_package}.errors")
    cache = NS(frame_start=1, frame_end=3, frame_step=1, is_baked=False, is_baking=False,
               is_outdated=False, is_frame_skip=False, use_disk_cache=False, use_external=False,
               use_library_path=True, filepath="", name="", index=-1, info="")
    physics = NS(samples={}, resets=0, writes=[], intervals=[], native_calls=[], frame_calls=[],
                 after_native=None, poll_hook=None, frame_hook=None, incomplete=False, fail_native=False,
                 view_layer_updates=0, graph_gets=0)

    class World:
        point_cache = cache
        _time_scale = .75

        @property
        def time_scale(self):
            return self._time_scale

        @time_scale.setter
        def time_scale(self, value):
            self._time_scale = value
            physics.samples.clear()
            physics.resets += 1
            cache.is_outdated = False
            cache.info = ""

    scene = NS(name="Owned", frame_current=7, frame_subframe=.25, gravity=-9.81,
               rigidbody_world=World(), protected_mesh=1, external_users=())

    def expected_matrix(frame, passive=False):
        z = -1. if passive else 3. + scene.gravity*(frame-cache.frame_start)**2*.001
        return ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., z), (0., 0., 0., 1.))

    def evaluated(passive=False):
        matrix = physics.samples.get(scene.frame_current, expected_matrix(cache.frame_start))
        return NS(matrix_world=expected_matrix(cache.frame_start, True) if passive else matrix)

    bodies = {"Body": NS(name="Body", evaluated_get=lambda graph: evaluated()),
              "Floor": NS(name="Floor", evaluated_get=lambda graph: evaluated(True))}

    def frame_set(frame, *, subframe=0.):
        physics.frame_calls.append((frame, subframe))
        if physics.frame_hook is not None:
            physics.frame_hook(frame, subframe)
        scene.frame_current, scene.frame_subframe = frame, subframe
        if not cache.is_baked and cache.frame_start <= frame <= cache.frame_end:
            physics.samples[frame] = expected_matrix(frame)
            cache.info = f"{len(physics.samples)} frames"

    scene.frame_set = frame_set

    class Operator:
        def __init__(self, operation):
            self.operation = operation

        def poll(self):
            if physics.poll_hook is not None:
                physics.poll_hook()
            return True

        def __call__(self, mode, **kwargs):
            assert mode == "EXEC_DEFAULT"
            physics.native_calls.append((self.operation, scene.frame_current, scene.frame_subframe))
            if self.operation == "BAKE":
                frames = [cache.frame_start] if physics.incomplete else range(cache.frame_start, cache.frame_end+1)
                physics.samples = {frame: expected_matrix(frame) for frame in frames}
                cache.is_baked = True
            else:
                cache.is_baked = False
            if physics.after_native is not None:
                physics.after_native()
            if physics.fail_native:
                raise RuntimeError("native bake failed after partial work")
            return {"FINISHED"}

    def update_view_layer():
        physics.view_layer_updates += 1

    def get_graph():
        physics.graph_gets += 1
        return object()

    view_layer = NS(objects=NS(active="SENTINEL"), update=update_view_layer)
    ctx = NS(scene=scene, view_layer=view_layer, active_object="SENTINEL", selected_objects=["SENTINEL"],
             mode="OBJECT", evaluated_depsgraph_get=get_graph)

    @contextmanager
    def override(**kwargs):
        assert kwargs["scene"] is scene and kwargs["point_cache"] is cache
        assert kwargs["object"] is bodies["Body"]
        yield

    ctx.temp_override = override
    bpy = NS(context=ctx, data=NS(objects=bodies),
             ops=NS(ptcache=NS(bake=Operator("BAKE"), free_bake=Operator("FREE"))))

    def current_scene(unused, exact):
        if exact != "Owned" or ctx.scene is not scene:
            raise errors.invalid_argument("actual current Scene changed")
        return scene

    def snapshot(unused, current, params):
        assert current is scene
        if params["body_names"] != ["Body", "Floor"] or params["constraint_names"] != []:
            raise errors.invalid_argument("incomplete whole-world scope")
        return {"protected": (id(scene), id(ctx.view_layer), ctx.mode, ctx.view_layer.objects.active,
                              tuple(ctx.selected_objects), scene.gravity, scene.protected_mesh, scene.external_users,
                              cache.use_disk_cache, cache.use_external),
                "owned": {"frame": (scene.frame_current, scene.frame_subframe),
                          "time_scale": scene.rigidbody_world.time_scale,
                          "range": (cache.frame_start, cache.frame_end)},
                "cache_status": tuple((field, getattr(cache, field)) for field in sorted(module.scope.VOLATILE_CACHE)),
                "body_names": ("Body", "Floor"), "constraint_names": (), "base_vertices": 16}

    grants = {permission.value: True for permission in permissions_module.Permission}
    provider = NS(hook=None)

    def permission_source():
        if provider.hook is not None:
            provider.hook()
        return dict(grants)

    registry = registry_module.ToolRegistry(enabled_toolsets=("simulation",))
    module.register(registry)
    importlib.import_module(f"{addon_package}.tools.rigid_body_jobs").register(registry)
    context = registry_module.ToolContext(state=state_module.BridgeState(),
        permissions=permissions_module.PermissionManager(permission_source), registry=registry, checkpoints=None,
        request_lifecycle=lifecycle.RequestLifetime.local())
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module.scope, "current_scene", current_scene)
    monkeypatch.setattr(module.scope, "snapshot", snapshot)
    params = {"scene_name": "Owned", "operation": "BAKE", "body_names": ["Body", "Floor"], "constraint_names": []}

    def proposal(operation="BAKE", **overrides):
        values = {**params, "operation": operation, **overrides}
        preview = module.cache_preview(context, values)
        return {**values, "expected_fingerprint": preview["expected_fingerprint"]}

    return NS(module=module, context=context, cache=cache, physics=physics, scene=scene, bpy=bpy,
              grants=grants, provider=provider, registry=registry, proposal=proposal, errors=errors,
              lifecycle=lifecycle, params=params)


def test_bake_resets_stale_unbaked_state_and_checks_all_complete_matrices(rigid_case):
    case = rigid_case
    case.physics.samples[3] = ((0.,)*4,)*4
    result = case.module.cache(case.context, case.proposal())
    assert case.physics.resets == 2
    assert case.physics.native_calls == [("BAKE", 1, 0.)]
    assert [row["frame"] for row in result["motion"]["samples"]] == [3, 1, 2]
    assert result["motion"]["maximum_absolute_matrix_error"] == 0.
    assert result["motion"]["all_body_frames_compared"]
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, .25)
    assert result["frame_recovery"] == {"attempted": True, "verified": True}
    assert case.scene.rigidbody_world.time_scale == .75
    assert case.bpy.context.view_layer.objects.active == "SENTINEL"
    assert case.bpy.context.selected_objects == ["SENTINEL"]


def test_false_success_baked_flag_cannot_pass_incomplete_playback(rigid_case):
    case = rigid_case
    case.physics.incomplete = True
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, case.proposal())
    assert caught.value.code == "OPERATION_FAILED"
    assert not caught.value.context["cache_operation_verified"]
    assert caught.value.context["frame_recovery"]["verified"]
    assert case.cache.is_baked
    assert len(case.physics.native_calls) == 1  # No implicit FREE rollback.


@pytest.mark.parametrize("changed", ["gravity", "mesh", "consumer", "frame", "selection", "operation"])
def test_preview_rejects_changed_context_content_consumers_or_operation(rigid_case, changed):
    case = rigid_case
    params = case.proposal()
    if changed == "gravity":
        case.scene.gravity = 0.
    elif changed == "mesh":
        case.scene.protected_mesh = 2
    elif changed == "consumer":
        case.scene.external_users = ("OtherScene",)
    elif changed == "frame":
        case.scene.frame_current = 8
    elif changed == "selection":
        case.bpy.context.selected_objects = ["Body"]
    else:
        params["operation"] = "FREE"
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert not case.physics.native_calls and not case.physics.frame_calls and not case.physics.resets


@pytest.mark.parametrize("stop", ["permission", "disconnect", "expired", "toolset", "pause", "emergency"])
def test_last_permission_provider_cannot_enable_a_late_write_after_stop(rigid_case, stop):
    case = rigid_case
    params = case.proposal()
    count = 0

    def stop_last():
        nonlocal count
        count += 1
        if count != 3:  # cache() initial check, boundary require, registry prepare.
            return
        if stop == "permission":
            case.grants["EDIT_SCENE"] = False
        elif stop == "disconnect":
            owner = case.lifecycle.ConnectionLifetime()
            owner.disconnected.set()
            case.context.request_lifecycle.connection = owner
        elif stop == "expired":
            case.context.request_lifecycle = case.lifecycle.RequestLifetime(deadline=0.)
        elif stop == "toolset":
            case.registry.disable_toolset("simulation")
        elif stop == "pause":
            case.context.state.pause()
        else:
            case.context.state.emergency_stop()

    case.provider.hook = stop_last
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert caught.value.context["execution_started"] is False
    assert not case.physics.native_calls and not case.physics.frame_calls and not case.physics.resets


@pytest.mark.parametrize("late_change", ["mesh", "frame", "disk", "permission", "disconnect"])
def test_native_poll_cannot_publish_unreviewed_late_changes(rigid_case, late_change):
    case = rigid_case

    def change():
        if late_change == "mesh":
            case.scene.protected_mesh = 2
        elif late_change == "frame":
            case.scene.frame_current = 9
        elif late_change == "disk":
            case.cache.use_disk_cache = True
        elif late_change == "permission":
            case.grants["EDIT_ANIMATION"] = False
        else:
            owner = case.lifecycle.ConnectionLifetime()
            owner.disconnected.set()
            case.context.request_lifecycle.connection = owner

    case.physics.poll_hook = change
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, case.proposal())
    assert caught.value.context["execution_started"]
    assert not caught.value.context["cache_operation_started"]
    assert not case.physics.native_calls
    assert not caught.value.context["frame_recovery"]["attempted"]
    if late_change == "frame":
        assert case.scene.frame_current == 9


def test_revocation_during_nonpreemptible_bake_retains_exact_partial_effects(rigid_case):
    case = rigid_case
    case.physics.after_native = lambda: case.grants.update(EDIT_SCENE=False)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, case.proposal())
    result = caught.value.context
    assert caught.value.code == "PERMISSION_DENIED"
    assert result["possible_mutation"] and result["cache_operation_started"]
    assert result["native_calls_preemptible"] is False
    assert not result["frame_recovery"]["attempted"]
    assert case.cache.is_baked and (case.scene.frame_current, case.scene.frame_subframe) == (1, 0.)
    assert all(row["seconds"] >= 0. for row in result["native_intervals"])


def test_primary_native_failure_survives_failed_fractional_frame_restore(rigid_case):
    case = rigid_case
    case.physics.fail_native = True

    def fail_restore(frame, subframe):
        if (frame, subframe) == (7, .25):
            raise ValueError("restoration failed")

    case.physics.frame_hook = fail_restore
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, case.proposal())
    assert caught.value.__cause__.args == ("native bake failed after partial work",)
    assert caught.value.context["primary_error_type"] == "RuntimeError"
    assert caught.value.context["frame_recovery"] == {"attempted": True, "verified": False, "error_type": "ValueError", "error_code": None}


def test_successful_cache_with_failed_context_restore_is_operation_failure(rigid_case):
    case = rigid_case

    def fail_restore(frame, subframe):
        if (frame, subframe) == (7, .25):
            raise RuntimeError("restore refused")

    case.physics.frame_hook = fail_restore
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, case.proposal())
    assert caught.value.context["primary_error_type"] is None
    assert caught.value.context["cache_operation_verified"]
    assert not caught.value.context["frame_recovery"]["verified"]


def test_free_reports_flag_only_and_invalidate_preserves_authored_time_scale(rigid_case):
    case = rigid_case
    case.cache.is_baked = True
    result = case.module.cache(case.context, case.proposal("FREE"))
    assert not case.cache.is_baked and not case.physics.resets
    assert result["free_semantics"] == "NATIVE_BAKED_FLAG_CLEARED_ONLY_NO_DELETION_OR_FRESHNESS_CLAIM"
    result = case.module.cache(case.context, case.proposal("INVALIDATE"))
    assert case.physics.resets == 1 and case.scene.rigidbody_world.time_scale == .75
    assert result["cache_freshness"] == "NOT_ASSESSED" and result["frame_recovery"]["verified"]


@pytest.mark.parametrize("values", [{"operation": True}, {"frame_start": True}, {"frame_end": 50},
                                     {"operation": "FREE", "frame_start": 1}, {"body_names": ["Body"]}])
def test_invalid_or_incomplete_proposals_never_write(rigid_case, values):
    case = rigid_case
    with pytest.raises(case.errors.BridgeError):
        case.module.cache_preview(case.context, {**case.params, **values})
    assert not case.physics.native_calls and not case.physics.frame_calls and not case.physics.resets


def test_cache_registry_declares_full_authority_and_excludes_batching(rigid_case):
    case = rigid_case
    spec = case.registry.get("rigid_body.cache")
    assert {permission.value for permission in spec.permissions} == {"INSPECT_SCENE", "EDIT_SCENE", "EDIT_ANIMATION"}
    assert spec.modifies and spec.automatic_checkpoint and not spec.batchable
    assert not case.registry.get("rigid_body.cache_preview").modifies


def test_mcp_schema_permissions_and_explicit_empty_constraint_scope_match_addon(rigid_case):
    from mcp_server.tools.rigid_body import TOOL_DATA, TOOL_NAMES, RigidBodyTools, load_definitions

    assert tuple(item.name for item in load_definitions()) == TOOL_NAMES
    assert tuple(item.name for item in RigidBodyTools(None).bindings()) == TOOL_NAMES
    for tool_name, _, modifying, permissions in TOOL_DATA:
        spec = rigid_case.registry.get(tool_name)
        assert spec.modifies == modifying and spec.toolset == "simulation"
        assert {permission.value for permission in spec.permissions} == set(permissions)
    calls = []

    class Registry:
        async def call(self, method, values):
            calls.append((method, values))

    asyncio.run(RigidBodyTools(Registry()).rigid_body_cache("Owned", "FREE", ["Body", "Floor"], [], "exact"))
    assert calls == [("rigid_body.cache", {"scene_name": "Owned", "operation": "FREE", "body_names": ["Body", "Floor"],
                                           "constraint_names": [], "expected_fingerprint": "exact"})]


def test_final_scheduler_check_catches_cancel_changed_by_last_permission_provider(rigid_case):
    case = rigid_case
    params = case.proposal()
    canceled = False
    calls = 0

    def provider():
        nonlocal canceled, calls
        calls += 1
        if calls == 3:
            canceled = True

    def final_check():
        if canceled:
            raise case.errors.BridgeError(case.errors.ErrorCode.TIMEOUT, "owner deadline elapsed")

    case.provider.hook = provider
    case.context.check_final_job = final_check
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert caught.value.code == "TIMEOUT"
    assert not caught.value.context["execution_started"]
    assert not case.physics.frame_calls and not case.physics.native_calls


def test_final_denial_after_recovered_success_keeps_partial_effect_metadata(rigid_case):
    case = rigid_case
    params = case.proposal()
    restored_checks = 0

    def deny_final():
        nonlocal restored_checks
        if case.cache.is_baked and (case.scene.frame_current, case.scene.frame_subframe) == (7, .25):
            restored_checks += 1
            if restored_checks == 5:
                case.grants["EDIT_SCENE"] = False

    case.provider.hook = deny_final
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["cache_operation_started"] and caught.value.context["possible_mutation"]
    assert caught.value.context["cache_operation_verified"] and caught.value.context["frame_recovery"]["verified"]
    assert not caught.value.context["final_authority_and_scope_verified"]


def test_native_failure_recovers_declared_range_without_destroying_retained_cache(rigid_case):
    case = rigid_case
    case.physics.fail_native = True
    params = case.proposal(frame_start=2, frame_end=4)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert (case.cache.frame_start, case.cache.frame_end) == (2, 4)
    assert caught.value.context["range_recovery"]["reason"] == "BAKED_CACHE_RETAINED_NO_IMPLICIT_FREE"
    assert caught.value.context["frame_recovery"]["verified"]
    assert case.cache.is_baked


@pytest.mark.parametrize("stop", ["owner_deadline", "owner_disconnect", "job_cancel", "toolset", "pause"])
def test_expensive_scope_read_cannot_publish_a_write_after_final_state_changes(rigid_case, monkeypatch, stop):
    case = rigid_case
    params = case.proposal()
    original_snapshot = case.module.scope.snapshot
    reads = 0
    canceled = False

    def final_job():
        if canceled:
            raise case.errors.BridgeError(case.errors.ErrorCode.TIMEOUT, "canceled during native scope comparison")

    case.context.check_final_job = final_job

    def delayed_snapshot(*args):
        nonlocal reads, canceled
        snapshot = original_snapshot(*args)
        reads += 1
        if reads == 2:  # _preview read, then the first actual write boundary.
            if stop == "owner_deadline":
                case.context.request_lifecycle = case.lifecycle.RequestLifetime(deadline=0.)
            elif stop == "owner_disconnect":
                owner = case.lifecycle.ConnectionLifetime()
                owner.disconnected.set()
                case.context.request_lifecycle.connection = owner
            elif stop == "job_cancel":
                canceled = True
            elif stop == "toolset":
                case.registry.disable_toolset("simulation")
            else:
                case.context.state.set_paused(True)
        return snapshot

    monkeypatch.setattr(case.module.scope, "snapshot", delayed_snapshot)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert caught.value.context["execution_started"] is False
    assert not case.physics.resets and not case.physics.native_calls and not case.physics.frame_calls


def test_registered_official_sdk_schema_exposes_bounded_world_scope_and_advisory_annotations():
    from mcp import Client

    from mcp_server.server import build_runtime

    async def scenario():
        runtime = build_runtime()
        try:
            async with Client(runtime.server) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                preview, mutate = tools["rigid_body.cache_preview"], tools["rigid_body.cache"]
                assert preview.annotations.read_only_hint and not mutate.annotations.read_only_hint
                assert mutate.annotations.destructive_hint
                schema = mutate.input_schema
                assert schema["required"] == ["scene_name", "operation", "body_names", "constraint_names", "expected_fingerprint"]
                fields = schema["properties"]
                assert fields["operation"]["enum"] == ["BAKE", "FREE", "INVALIDATE"]
                assert fields["body_names"]["maxItems"] == 16 and fields["body_names"]["minItems"] == 1
                assert fields["constraint_names"]["maxItems"] == 16
                assert fields["expected_fingerprint"]["pattern"] == "^[0-9a-f]{64}$"
                assert fields["frame_start"]["anyOf"][0]["minimum"] == 1
                assert fields["frame_end"]["anyOf"][0]["maximum"] == 1048574
                disabled = await client.call_tool("rigid_body.inspect", {"scene_name": "Owned"})
                assert disabled.is_error and "TOOLSET_DISABLED" in disabled.content[0].text
        finally:
            await runtime.client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("field,invalid", [("body_names", []), ("body_names", ["Body"]*17),
    ("constraint_names", ["Constraint"]*17), ("frame_start", True), ("frame_end", "3"),
    ("frame_end", 1048575), ("expected_fingerprint", "not-a-preview")])
def test_mcp_boundary_rejects_coercion_and_unbounded_scope(field, invalid):
    from typing import get_type_hints

    from pydantic import TypeAdapter, ValidationError

    from mcp_server.tools.rigid_body import RigidBodyTools

    schema = get_type_hints(RigidBodyTools.rigid_body_cache, include_extras=True)[field]
    with pytest.raises(ValidationError):
        TypeAdapter(schema).validate_python(invalid)


@pytest.mark.parametrize("stop", ["queued_cancel", "queued_expiry"])
def test_canonical_pure_queue_hook_rechecks_after_expensive_scope_read(rigid_case, monkeypatch, addon_package, stop):
    from dataclasses import fields

    case = rigid_case
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    params = case.proposal()
    queued = queue_module.QueuedRequest(protocol.Request(id="native-owner", method="rigid_body.cache", params=params))
    assert queued.try_start()
    class FutureContext(type(case.context)):
        pass

    context = FutureContext(**{field.name: getattr(case.context, field.name) for field in fields(case.context)})
    context.check_cancelled = queued.check_active
    context.check_final_request = queued.check_active  # Canonical runtime-owned pure hook.
    original = case.module.scope.snapshot
    reads = 0

    def snapshot(*args):
        nonlocal reads
        result = original(*args)
        reads += 1
        if reads == 2:
            if stop == "queued_cancel":
                queued.cancel_pending(case.errors.BridgeError(case.errors.ErrorCode.TIMEOUT, "owner canceled"))
            else:
                queued.deadline = 0.
        return result

    monkeypatch.setattr(case.module.scope, "snapshot", snapshot)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(context, params)
    assert caught.value.code == "TIMEOUT" and not caught.value.context["execution_started"]
    assert not case.physics.resets and not case.physics.frame_calls and not case.physics.native_calls
    assert caught.value.context["primary_error"]["context"]["cancellation_requested" if stop == "queued_cancel" else "deadline_expired"]


@pytest.mark.parametrize("stage", ["scene_frame_set", "view_layer_update", "evaluated_depsgraph_get",
                                   "cache_range_setter", "same_value_world_reset", "native_bake"])
@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("stop", ["queued_cancel", "queued_expiry", "disconnect", "pause", "emergency", "toolset", "job_cancel"])
def test_every_native_tail_stops_at_its_own_boundary_without_late_readback(
    rigid_case, monkeypatch, addon_package, stage, when, stop,
):
    case = rigid_case
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    params = case.proposal()
    queued = queue_module.QueuedRequest(protocol.Request(id="native-stage-owner", method="rigid_body.cache", params=params))
    assert queued.try_start()
    case.context.check_cancelled = case.context.check_final_request = queued.check_active
    canceled = [False]

    def final_job():
        if canceled[0]:
            raise case.errors.BridgeError(case.errors.ErrorCode.TIMEOUT, "Canceled inside a native tail")

    case.context.check_final_job = final_job
    original = case.module._Boundary._native_interval
    capture = case.module.scope.snapshot
    reads = []
    fired = []
    entries = []

    def snapshot(*args):
        reads.append(True)
        return capture(*args)

    def revoke():
        if stop == "queued_cancel":
            queued.cancel_pending(case.errors.BridgeError(case.errors.ErrorCode.TIMEOUT, "Canceled inside a native tail"))
        elif stop == "queued_expiry":
            queued.deadline = 0.
        elif stop == "disconnect":
            owner = case.lifecycle.ConnectionLifetime()
            owner.disconnected.set()
            case.context.request_lifecycle.connection = owner
        elif stop == "pause":
            case.context.state.set_paused(True)
        elif stop == "emergency":
            case.context.state.set_emergency_stopped(True)
        elif stop == "toolset":
            case.registry.disable_toolset("simulation")
        else:
            canceled[0] = True
        fired.append(len(reads))

    def interval(self, current, callback):
        if current == stage and when == "before" and not fired:
            revoke()

        def observed():
            entries.append(current)
            result = callback()
            if current == stage and when == "after" and not fired:
                revoke()
            return result

        return original(self, current, observed)

    monkeypatch.setattr(case.module.scope, "snapshot", snapshot)
    monkeypatch.setattr(case.module._Boundary, "_native_interval", interval)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert fired and len(reads) == fired[0]  # No readback/recovery capture after owner/stop latch.
    assert entries.count(stage) == (when == "after")
    assert not caught.value.context["frame_recovery"]["attempted"]
    assert not caught.value.context["frame_recovery"]["verified"]
    assert caught.value.context["possible_mutation"] == (stage != "cache_range_setter" or when == "after")
    assert caught.value.context["cache_operation_started"] == (stage == "native_bake" and when == "after")
    expected_code = {"pause": "AGENT_PAUSED", "emergency": "EMERGENCY_STOPPED", "toolset": "TOOLSET_DISABLED"}.get(stop, "TIMEOUT")
    assert caught.value.code == expected_code
    if stage == "scene_frame_set":
        assert case.physics.view_layer_updates == case.physics.graph_gets == 0
        assert not case.physics.native_calls
        assert (case.scene.frame_current, case.scene.frame_subframe) == ((1, 0.) if when == "after" else (7, .25))
    elif stage == "view_layer_update":
        assert case.physics.view_layer_updates == (when == "after")
        assert case.physics.graph_gets == 0 and not case.physics.native_calls
    elif stage == "evaluated_depsgraph_get":
        assert case.physics.view_layer_updates == 1 and case.physics.graph_gets == (when == "after")
        assert not case.physics.native_calls
