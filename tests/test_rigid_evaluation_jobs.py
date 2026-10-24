"""Real typed rigid driver composed with the registry, executor and Scene kernel."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from test_scene_jobs import scene_jobs  # noqa: F401


@pytest.fixture
def evaluation(scene_jobs, addon_package, monkeypatch):  # noqa: F811
    env = scene_jobs
    module = importlib.import_module(f"{addon_package}.tools.rigid_body_jobs")
    effects = importlib.import_module(f"{addon_package}.scene_job_effects")
    driver_module = importlib.import_module(f"{addon_package}.tools._rigid_evaluation_job")
    bpy, scene = env.stack.bpy, env.stack.scene
    calls, hooks = [], {}

    def called(operation):
        calls.append(operation)
        if operation in hooks:
            hooks[operation]()

    class Cache:
        _start, _end = 1, 250
        is_baked, is_outdated = False, False

        @property
        def frame_start(self):
            return self._start

        @frame_start.setter
        def frame_start(self, value):
            assert value <= self._end
            self._start = value
            called("cache_frame_start_set")

        @property
        def frame_end(self):
            return self._end

        @frame_end.setter
        def frame_end(self, value):
            assert value >= self._start
            self._end = value
            called("cache_frame_end_set")

    cache = Cache()

    class World:
        point_cache = cache
        _time_scale = .75

        @property
        def time_scale(self):
            return self._time_scale

        @time_scale.setter
        def time_scale(self, value):
            self._time_scale = value
            called("world_reset")

    scene.name, scene.frame_current, scene.frame_subframe = "Owned", 7, .25
    scene.rigidbody_world = World()
    scene.gravity, scene.authored = -9.81, 1
    active = NS(type="EMPTY", name="Neutral")
    bpy.context.view_layer = NS(objects=NS(active=active), update=lambda: called("view_layer_update"))
    bpy.context.selected_objects = [active]
    bpy.context.evaluated_depsgraph_get = lambda: called("depsgraph_get") or object()

    def matrix(name):
        z = 3. + scene.gravity*(scene.frame_current-cache.frame_start)**2*.001
        return ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., z), (0., 0., 0., 1.))

    class Evaluated:
        def __init__(self, name):
            self.name = name

        @property
        def matrix_world(self):
            called("matrix_capture")
            return matrix(self.name)

    class Body:
        def __init__(self, name):
            self.name = name

        def evaluated_get(self, graph):
            assert graph is not None
            called("evaluated_get")
            return Evaluated(self.name)

    names = ["Body", "Floor"]
    bpy.data.objects = {name: Body(name) for name in names}

    def frame_set(frame, *, subframe=0.):
        scene.frame_current, scene.frame_subframe = frame, subframe
        called("frame_set")

    scene.frame_set = frame_set

    def current(_bpy, name):
        if name != scene.name or bpy.context.scene is not scene:
            raise env.errors.invalid_argument("Current Scene changed.")
        return scene

    def snapshot(_bpy, target, params):
        assert target is scene
        if sorted(params["body_names"]) != sorted(bpy.data.objects) or params["constraint_names"]:
            raise env.errors.invalid_argument("Whole-world members changed.")
        return {"protected": (scene.authored, scene.gravity, active.name, active.type, bpy.context.mode,
                              tuple(item.name for item in bpy.context.selected_objects)),
                "owned": {"frame": (scene.frame_current, scene.frame_subframe),
                          "range": (cache.frame_start, cache.frame_end), "time_scale": scene.rigidbody_world.time_scale},
                "cache_status": (cache.is_baked, cache.is_outdated), "body_names": tuple(sorted(bpy.data.objects)),
                "constraint_names": (), "base_vertices": 8*len(bpy.data.objects)}

    class Roles:
        def __init__(self, *_):
            pass

        def check_after_read(self):
            pass

        def authored(self):
            return ("frozen-authored-roles",)

        def after_native_push(self):
            pass

    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module.scope, "current_scene", current)
    monkeypatch.setattr(module.scope, "snapshot", snapshot)
    monkeypatch.setattr(module.checkpoint_roles, "Plan", Roles)
    module.register(env.registry)
    env.registry.enable_toolset("simulation")
    params = {"scene_name": scene.name, "body_names": names, "constraint_names": [],
              "frame_start": 1, "frame_end": 3, "time_limit_seconds": 60}

    def preview(**changes):
        values = {**params, **changes}
        return values, env.executor.dispatch(module.PREVIEW, values)

    def start(*, delivered=True, **changes):
        values, inspected = preview(**changes)
        owner = env.lifecycle.RequestLifetime(env.lifecycle.ConnectionLifetime(), float("inf"))
        if delivered:
            owner.acknowledge(True)
        response = env.executor.execute_request(env.protocol.Request(
            "typed-rigid-start", module.START, {**values, "expected_fingerprint": inspected["expected_fingerprint"]},
            _lifecycle=owner))
        assert response.ok, response.error
        return NS(response=response, owner=owner, job=env.manager.active)

    def drain(maximum=120):
        for _ in range(maximum):
            if not env.manager.tick():
                return env.manager.history[0].summary()
        pytest.fail("Typed rigid evaluation did not finish its bounded phases")

    def until(operation):
        for _ in range(120):
            assert env.manager.active is not None
            if operation in calls:
                return
            env.manager.tick()
        pytest.fail("Native-shaped phase did not run")

    return NS(env=env, module=module, effects=effects, driver_module=driver_module, bpy=bpy, scene=scene,
              cache=cache, calls=calls, hooks=hooks, active=active, params=params, preview=preview,
              start=start, drain=drain, until=until, Body=Body)


def test_typed_rigid_job_waits_for_ack_and_returns_motion_without_a_bake(evaluation):
    case, env = evaluation, evaluation.env
    started = case.start(delivered=False)
    assert env.manager.tick() and not case.calls and len(env.stack.frames) == 1
    started.owner.acknowledge(True)
    terminal = case.drain()
    assert terminal["state"] == "SUCCEEDED", terminal
    result = terminal["result"]
    assert result["frames_sampled"] == 3 and result["matrices_sampled"] == 6
    assert len(result["matrix_samples_sha256"]) == 64 and result["endpoints"][0]["displacement_xyz"][2] < 0
    assert result["caller_time_restored"] and not result["bake_completed"] and not result["baked"]
    assert result["cache_coverage"] == "NOT_ASSESSED" and result["physical_correctness"] == "NOT_ASSESSED"
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, .25)
    assert (case.cache.frame_start, case.cache.frame_end) == (1, 3)
    assert case.active.type == "EMPTY" and case.bpy.context.selected_objects == [case.active]
    effects = terminal["native_effects"]
    assert effects["sample_recorded_count"] == 3 and effects["sealed"]
    assert effects["counts_by_operation"]["evaluated_get"] == {"entered": 6, "returned": 6}
    assert len(json.dumps(effects)) <= 8192 and len(env.stack.frames) == 3
    assert started.job.driver is None
    assert env.state.history()[0]["job_evidence"]["native_effects"] == effects
    terminal["native_effects"]["sealed"] = False
    assert env.manager.inspect(started.job.job_id)["native_effects"]["sealed"]


@pytest.mark.parametrize("start,end", [(1, 1), (300, 303), (1, 32)])
def test_zero_motion_and_safe_range_order_with_maximum_result_budget(evaluation, start, end):
    case = evaluation
    case.scene.gravity = 0.
    case.bpy.data.objects = {f"Body{index:02}": case.Body(f"Body{index:02}") for index in range(16)}
    case.start(body_names=list(case.bpy.data.objects), frame_start=start, frame_end=end)
    terminal = case.drain()
    assert terminal["state"] == "SUCCEEDED", terminal
    result = terminal["result"]
    assert result["matrices_sampled"] == 16*(end-start+1)
    assert all(row["displacement_xyz"] == [0., 0., 0.] for row in result["endpoints"])
    assert len(json.dumps(result)) <= 65536 and len(result["endpoints"]) == 16
    assert len(json.dumps(terminal["native_effects"])) <= 8192


@pytest.mark.parametrize("change", ["baked", "active", "span", "constraints", "unknown", "bool_limit"])
def test_unsupported_admission_is_refused_before_markers(evaluation, change):
    case = evaluation
    values = dict(case.params)
    if change == "baked":
        case.cache.is_baked = True
    elif change == "active":
        case.active.type = "MESH"
    elif change == "span":
        values["frame_end"] = 33
    elif change == "constraints":
        values["constraint_names"] = ["Undeclared"]
    elif change == "unknown":
        values["operation"] = "BAKE"
    else:
        values["time_limit_seconds"] = True
    response = case.env.executor.execute_request(case.env.protocol.Request(
        "invalid-rigid", case.module.START, {**values, "expected_fingerprint": "a"*64},
        _lifecycle=case.env.lifecycle.RequestLifetime.local()))
    assert not response.ok and not case.calls
    assert case.env.manager.active is None and len(case.env.stack.frames) == 1
    if change in {"active", "baked"}:
        assert response.error["context"]["entry_effects"]["view_layer_sync_possible"]
        assert response.error["context"]["entry_effects"]["handler_entered"] is False


@pytest.mark.parametrize("operation", ["cache_frame_start_set", "cache_frame_end_set", "world_reset", "frame_set",
                                       "view_layer_update", "depsgraph_get", "evaluated_get", "matrix_capture"])
def test_cancel_inside_selected_native_tail_keeps_literal_return_and_no_later_work(evaluation, operation):
    case, env = evaluation, evaluation.env
    started = case.start()
    case.hooks[operation] = lambda: env.manager.cancel(started.job.job_id)
    terminal = case.drain()
    assert terminal["state"] == "CANCELLED", terminal
    facts = terminal["native_effects"]
    assert facts["counts_by_operation"][operation] == {"entered": 1, "returned": 1}
    assert facts["phases_verified"] < facts["phases_planned"]
    assert terminal["error"]["context"]["possible_mutation"]
    assert not terminal["undo_boundary_finalized"] and started.job.job_id in env.manager.recovery_ledger
    retained = list(case.calls), case.scene.frame_current, case.scene.frame_subframe, len(env.stack.frames)
    for _ in range(3):
        assert not env.manager.tick()
    assert (case.calls, case.scene.frame_current, case.scene.frame_subframe, len(env.stack.frames)) == retained


@pytest.mark.parametrize("operation", ["cache_frame_end_set", "world_reset", "frame_set", "evaluated_get", "matrix_capture"])
def test_native_exception_retains_entered_only_with_no_recovery(evaluation, operation):
    case = evaluation
    case.start()

    def fail():
        raise RuntimeError("Native-shaped call failed after possible effects")

    case.hooks[operation] = fail
    terminal = case.drain()
    assert terminal["state"] == "FAILED" and terminal["error"]["context"]["exception_type"] == "RuntimeError"
    assert terminal["native_effects"]["counts_by_operation"][operation] == {"entered": 1, "returned": 0}
    assert not terminal["undo_boundary_finalized"] and terminal["result"] is None


def test_post_native_allocation_failure_keeps_normal_return_before_failed_publication(evaluation, monkeypatch):
    case = evaluation
    started = case.start()

    def fail(*_args):
        raise MemoryError("Post-return publication allocation")

    monkeypatch.setattr(started.job.driver, "_accept", fail)
    terminal = case.drain()
    assert terminal["state"] == "FAILED"
    assert terminal["error"]["context"]["exception_type"] == "MemoryError"
    assert terminal["native_effects"]["counts_by_operation"]["cache_frame_start_set"] == {"entered": 1, "returned": 1}
    assert terminal["native_effects"]["phases_verified"] == 0


def test_fresh_readonly_permission_observation_inside_body_getter_stops_next_read(evaluation):
    case, env = evaluation, evaluation.env
    started = case.start()
    polls = []

    def revoke_then_inspect():
        env.grants["EDIT_ANIMATION"] = False
        # executor.dispatch creates its ordinary fresh ToolContext, as runtime
        # dispatch does; it shares only the authoritative PermissionManager.
        polls.append(env.executor.dispatch("jobs.inspect", {"job_id": started.job.job_id}))

    case.hooks["evaluated_get"] = revoke_then_inspect
    terminal = case.drain()
    assert polls and polls[0]["kind"] == "rigid_body.evaluation"
    assert terminal["error"]["code"] == "PERMISSION_DENIED"
    assert "matrix_capture" not in case.calls and case.calls.count("evaluated_get") == 1
    assert terminal["native_effects"]["counts_by_operation"]["evaluated_get"] == {"entered": 1, "returned": 1}


@pytest.mark.parametrize("before,after", [(False, 0), (0, 0.), (0., -0.)])
@pytest.mark.parametrize("when", ["gap", "native_return"])
def test_typed_protected_drift_cannot_be_adopted_before_or_after_a_native_call(evaluation, before, after, when):
    case = evaluation
    case.scene.authored = before
    case.start()
    if when == "gap":
        case.until("world_reset")
        previous = list(case.calls)
        case.scene.authored = after
    else:
        previous = None
        case.hooks["world_reset"] = lambda: setattr(case.scene, "authored", after)
    terminal = case.drain()
    assert terminal["error"]["code"] == "INVALID_ARGUMENT", terminal
    assert json.dumps(case.scene.authored) == json.dumps(after)
    if previous is not None:
        assert case.calls == previous
    else:
        assert terminal["native_effects"]["counts_by_operation"]["world_reset"] == {"entered": 1, "returned": 1}
        assert "frame_set" not in case.calls
    assert terminal["result"] is None and not terminal["undo_boundary_finalized"]


def test_signed_zero_owned_frame_drift_after_native_return_is_not_published(evaluation):
    case = evaluation
    case.start()
    case.hooks["frame_set"] = lambda: setattr(case.scene, "frame_subframe", -0.)
    terminal = case.drain()
    assert terminal["error"]["code"] == "INVALID_ARGUMENT"
    assert terminal["native_effects"]["counts_by_operation"]["frame_set"] == {"entered": 1, "returned": 1}
    assert "view_layer_update" not in case.calls and case.scene.frame_subframe.hex() == "-0x0.0p+0"


@pytest.mark.parametrize("stop", ["cancel", "disconnect", "toolset", "emergency"])
def test_granting_phase_provider_stop_refuses_all_following_domain_readers(evaluation, monkeypatch, stop):
    case, env = evaluation, evaluation.env
    started = case.start()
    assert env.manager.tick()  # BEFORE; enter the first real domain phase next.
    driver, reached = started.job.driver, []
    original_check = driver._check

    def reader(*_args):
        reached.append(True)
        pytest.fail("A known stopped owner entered a domain reader")

    def stop_inside_provider():
        if stop == "cancel":
            env.manager.cancel(started.job.job_id)
        elif stop == "disconnect":
            started.owner.connection.disconnected.set()
        elif stop == "toolset":
            env.registry.disable_toolset("simulation")
        else:
            env.state.emergency_stop()
        monkeypatch.setattr(driver.roles, "check_after_read", reader)
        monkeypatch.setattr(case.module.scope, "snapshot", reader)

    def check(context):
        env.provider_hook = stop_inside_provider
        original_check(context)

    monkeypatch.setattr(driver, "_check", check)
    terminal = case.drain()
    assert terminal["state"] in {"FAILED", "CANCELLED"} and not reached and not case.calls
    assert all(value == {"entered": 0, "returned": 0} for value in terminal["native_effects"]["counts_by_operation"].values())


def test_borrowed_graph_and_evaluated_wrappers_do_not_cross_provider_callbacks(evaluation, monkeypatch):
    case, env = evaluation, evaluation.env
    generation = [0]

    def provider():
        generation[0] += 1
        env.provider_hook = provider

    class Borrowed:
        def __init__(self):
            self.generation = generation[0]

        @property
        def matrix_world(self):
            assert self.generation == generation[0], "Evaluated wrapper crossed a provider"
            return ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 3.), (0., 0., 0., 1.))

    class Body:
        def evaluated_get(self, graph):
            assert graph.generation == generation[0], "Dependency graph crossed a provider"
            return Borrowed()

    monkeypatch.setattr(case.bpy.context, "evaluated_depsgraph_get", Borrowed)
    case.bpy.data.objects = {name: Body() for name in case.bpy.data.objects}
    env.provider_hook = provider
    case.start()
    terminal = case.drain()
    assert terminal["state"] == "SUCCEEDED", terminal


def test_matrix_copy_oom_retains_uncertain_declared_interval_not_a_missing_getter_claim(evaluation, monkeypatch):
    case = evaluation
    getter_returns = []

    class IncompleteMatrix:
        def __iter__(self):
            raise MemoryError("Matrix tuple allocation")

    class Evaluated:
        @property
        def matrix_world(self):
            getter_returns.append(True)
            return IncompleteMatrix()

    for body in case.bpy.data.objects.values():
        monkeypatch.setattr(body, "evaluated_get", lambda _graph: Evaluated())
    case.start()
    terminal = case.drain()
    assert getter_returns == [True] and terminal["error"]["context"]["exception_type"] == "MemoryError"
    assert terminal["native_effects"]["counts_by_operation"]["evaluated_get"] == {"entered": 1, "returned": 1}
    assert terminal["native_effects"]["counts_by_operation"]["matrix_capture"] == {"entered": 1, "returned": 0}
    assert terminal["native_effects"]["sample_recorded_count"] == 0 and terminal["result"] is None


@pytest.mark.parametrize("change", ["authored", "disable", "replace", "permission"])
def test_between_phase_changes_stop_the_original_domain_owner(evaluation, change):
    case, env = evaluation, evaluation.env
    case.start()
    case.until("world_reset")
    before = list(case.calls)
    if change == "authored":
        case.scene.authored = 4
    elif change == "disable":
        env.registry.disable_toolset("simulation")
    elif change == "replace":
        original = env.registry.get(case.module.START)
        env.registry._tools[original.name] = replace(original, handler=lambda *_: pytest.fail("Foreign starter entered"))
    else:
        env.grants["EDIT_ANIMATION"] = False
    terminal = case.drain()
    assert terminal["state"] == "FAILED", terminal
    assert case.calls == before and not terminal["undo_boundary_finalized"]
    assert case.scene.authored == (4 if change == "authored" else 1)


def test_start_provider_edit_does_not_become_an_authored_baseline(evaluation):
    case, env = evaluation, evaluation.env
    values, inspected = case.preview()
    env.provider_hook = lambda: setattr(case.scene, "authored", 99)
    response = env.executor.execute_request(env.protocol.Request(
        "changed-after-preview", case.module.START, {**values, "expected_fingerprint": inspected["expected_fingerprint"]},
        _lifecycle=env.lifecycle.RequestLifetime.local()))
    assert not response.ok and response.error["code"] == "INVALID_ARGUMENT"
    assert case.scene.authored == 99 and not case.calls and len(env.stack.frames) == 1


def test_effect_snapshot_oom_retries_terminal_only_without_driver_context_or_duplicate_history(evaluation, monkeypatch):
    case, env = evaluation, evaluation.env
    started = case.start()
    case.until("world_reset")
    env.manager.cancel(started.job.job_id)
    expected = list(case.calls)
    original = case.effects._snapshot
    failure = MemoryError("One-shot effects snapshot allocation")
    attempts = []

    def snapshot(journal):
        if not attempts:
            attempts.append(True)
            raise failure
        return original(journal)

    monkeypatch.setattr(case.effects, "_snapshot", snapshot)
    # Cached status also snapshots, so inject only after the stop is requested.
    with pytest.raises(MemoryError) as caught:
        env.manager.tick()
    assert caught.value is failure and env.manager.active is started.job
    assert started.job.terminal_primary.code == "TIMEOUT" and started.job.native_effects.status.sealed
    monkeypatch.setattr(env.manager, "context_factory", lambda: pytest.fail("Stopped context factory consulted"))
    started.job.driver = NS()  # Terminal must not read any driver property.
    assert not env.manager.tick()
    terminal = env.manager.inspect(started.job.job_id)
    assert terminal["error"]["code"] == "TIMEOUT" and terminal["native_effects"]["evidence_incomplete"]
    assert terminal["native_effects"]["snapshot_allocation_failed"] and case.calls == expected
    assert sum(row["tool"] == "jobs._scene_turn" for row in env.state.history()) == 1
    assert env.manager.reservations.owner is None


@pytest.mark.parametrize("where", ["ledger", "retire"])
def test_receipt_allocation_retry_uses_frozen_effects_and_original_history_only_once(evaluation, monkeypatch, where):
    case, env = evaluation, evaluation.env
    started = case.start()
    case.until("world_reset")
    env.manager.cancel(started.job.job_id)
    original_retire = env.manager._retire
    attempts = []

    def fail_once():
        if not attempts:
            attempts.append(True)
            raise MemoryError("One-shot terminal receipt allocation")

    class Ledger(dict):
        def __setitem__(self, key, value):
            fail_once()
            super().__setitem__(key, value)

    def retire(job):
        fail_once()
        original_retire(job)

    if where == "ledger":
        env.manager.recovery_ledger = Ledger()
    else:
        monkeypatch.setattr(env.manager, "_retire", retire)
    with pytest.raises(MemoryError):
        env.manager.tick()
    native = list(case.calls)
    snapshot = started.job.native_effects_snapshot
    assert snapshot["counts_by_operation"]["world_reset"] == {"entered": 1, "returned": 1}
    assert env.manager.active is started.job and env.manager.reservations.owner is not None
    monkeypatch.setattr(env.manager, "context_factory", lambda: pytest.fail("Stopped context consulted"))
    monkeypatch.setattr(env.domain, "snapshot_native_effects", lambda *_: pytest.fail("Effects snapshot repeated"))
    started.job.driver = NS()
    assert not env.manager.tick()
    terminal = env.manager.inspect(started.job.job_id)
    assert terminal["error"]["code"] == "TIMEOUT" and terminal["native_effects"] == snapshot
    assert case.calls == native and sum(row["tool"] == "jobs._scene_turn" for row in env.state.history()) == 1


def test_history_failure_preserves_primary_effects_and_no_terminal_context_factory(evaluation, monkeypatch):
    case, env = evaluation, evaluation.env
    started = case.start()
    case.until("world_reset")
    env.manager.cancel(started.job.job_id)
    attempts = []

    def failed_history(**_kwargs):
        attempts.append(True)
        raise MemoryError("History unavailable")

    monkeypatch.setattr(env.state, "record_operation", failed_history)
    terminal = case.drain()
    assert terminal["error"]["code"] == "TIMEOUT" and terminal["error"]["context"]["operation_history_unknown"]
    assert terminal["native_effects"]["counts_by_operation"]["world_reset"] == {"entered": 1, "returned": 1}
    assert attempts == [True] and started.job.driver is None


def test_unresolved_effects_remain_discoverable_after_terminal_history_eviction(evaluation):
    case, env = evaluation, evaluation.env
    stopped = case.start()
    case.until("world_reset")
    env.manager.cancel(stopped.job.job_id)
    original = case.drain()["native_effects"]
    assert stopped.job.driver is None
    for _ in range(33):
        env.start(steps=1)
        case.drain()
    assert len(env.manager.history) == 32
    retained = env.manager.inspect(stopped.job.job_id)
    assert retained["terminal_history_evicted"] and retained["native_effects"] == original
    assert stopped.job.job_id in {value["job_id"] for value in env.manager.list(limit=100)["jobs"]}
