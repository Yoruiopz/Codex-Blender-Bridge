"""Scene owners use the real registry, executor and native-shaped checkpoint manager."""

from __future__ import annotations

import importlib
import time
from contextlib import suppress
from copy import copy, deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_snapshots import NativeStack, Scene
from test_image_paint import paint_tools  # noqa: F401
from test_paint_jobs import jobs, start  # noqa: F401

pytestmark = [
    pytest.mark.usefixtures("scene_job_manager"),
    pytest.mark.parametrize("scene_job_manager", ("scene", "native_save")),
]


@pytest.fixture
def scene_jobs(addon_package, monkeypatch, request):
    domain = importlib.import_module(f"{addon_package}.scene_jobs")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    executor_module = importlib.import_module(f"{addon_package}.executor")
    permissions_module = importlib.import_module(f"{addon_package}.permissions")
    checkpoints_module = importlib.import_module(f"{addon_package}.checkpoints")
    state_module = importlib.import_module(f"{addon_package}.state")
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    stack = NativeStack()
    stack.bpy.context.preferences.edit.undo_steps = 256
    monkeypatch.setattr(checkpoints_module, "require_blender", lambda: stack.bpy)
    checkpoints = checkpoints_module.CheckpointManager()
    registry, state = registry_module.ToolRegistry(), state_module.BridgeState()
    env = NS(
        domain=domain, registry_module=registry_module, executor_module=executor_module,
        permissions_module=permissions_module, checkpoint_module=checkpoints_module,
        errors=errors, lifecycle=lifecycle, protocol=protocol, stack=stack,
        checkpoints=checkpoints, registry=registry, state=state, events=[],
        drivers=[], advances=[], foreign_entries=[], read_entries=[], provider_calls=0,
        provider_hook=None, advance_hook=None, push_hook=None,
        grants={item.value: True for item in permissions_module.Permission},
    )

    def provider():
        env.provider_calls += 1
        env.events.append("provider")
        hook, env.provider_hook = env.provider_hook, None
        if hook is not None:
            hook()
        return dict(env.grants)

    permissions = permissions_module.PermissionManager(provider)
    executor = None
    callspec = getattr(request.node, "callspec", None)
    manager_kind = "scene" if callspec is None else callspec.params.get("scene_job_manager", "scene")
    options = {"registry": registry, "recovery_limit": getattr(request, "param", 8)}
    if manager_kind == "native_save":
        runtime = importlib.import_module(f"{addon_package}.runtime")
        policy_module = importlib.import_module(f"{addon_package}.native_save_policy")
        grant = policy_module.NativeSaveGrant("inherited-scene-fixture", object())
        assert not grant.active() and grant.status()["armed"] is False
        manager = runtime.NativeSaveJobs(
            lambda: executor.context, budget_ms=lambda: 8., native_save_policy=grant, **options,
        )
    else:
        manager = domain.SceneJobs(lambda: executor.context, budget_ms=lambda: 8., **options)
    executor = executor_module.MainThreadExecutor(
        command_queue=queue_module.CommandQueue(), registry=registry, state=state,
        permissions=permissions, checkpoints=checkpoints, jobs=manager,
    )
    env.manager, env.executor, env.permissions = manager, executor, permissions

    class Driver:
        kind = "fixture.scene_steps"
        label = "Owned fixture Scene steps"
        required_permissions = (permissions_module.Permission.EDIT_SCENE,)

        def __init__(self, context, params):
            self.expected = stack.scene["value"]
            self.count, self.maximum = 0, params.get("steps", 2)
            self.phase, self.done, self.result = "fixture_step_0", False, None
            self.last_context = context
            env.events.append("driver_created")
            env.drivers.append(self)

        def check_after_read(self, context):
            self.last_context = context
            if stack.scene["value"] != self.expected:
                raise errors.BridgeError("NOT_IMPLEMENTED", "Fixture authored state changed.")

        def advance(self, context):
            self.check_after_read(context)
            if env.advance_hook is not None:
                env.advance_hook(context)
            # Trusted drivers place a provider-free safe point immediately
            # before a write; the kernel cannot preempt arbitrary Python.
            context.checkpoint_admission.check_after_read()
            self.expected += 1
            stack.scene["value"] = self.expected
            self.count += 1
            self.phase = f"fixture_step_{self.count}"
            self.done = self.count == self.maximum
            self.result = {"value": self.expected} if self.done else None
            env.advances.append((self.count, self.expected))
            return {"phase": self.phase, "completed": self.count, "total": self.maximum}

        def native_push_delegates(self):
            # This fixture has no native runtime roles to adopt after undo_push.
            return ()

        def after_native_push(self):
            env.events.append("authenticated_push")

    env.driver_type = Driver
    env.start_spec = registry.register(
        "fixture.scene_start", lambda context, params: context.jobs.start_scene(context, params, time_limit=60.),
        modifies=True, permissions=Driver.required_permissions, automatic_checkpoint=False,
        exclusive_mutation=True, checkpoint_owns_finalization=True,
        checkpoint_admission_factory=domain.start_admission(Driver), record_history=False,
    )
    env.foreign_spec = registry.register(
        "fixture.foreign", lambda *_: env.foreign_entries.append(True),
        modifies=True, permissions=Driver.required_permissions,
    )
    env.read_spec = registry.register(
        "fixture.evaluate", lambda *_: env.read_entries.append(True) or {"value": stack.scene["value"]},
        permissions=(permissions_module.Permission.INSPECT_SCENE,), record_history=False,
    )
    registry.register("jobs.inspect", lambda _context, params: manager.inspect(params["job_id"]),
                      permissions=(permissions_module.Permission.INSPECT_SCENE,), record_history=False)
    registry.register("jobs.list", lambda *_: manager.list(), record_history=False)
    registry.register("jobs.cancel", lambda _context, params: manager.cancel(params["job_id"]), record_history=False)
    registry.register("bridge.status", lambda *_: state.snapshot(), record_history=False)
    native_push = stack.bpy.ops.ed.undo_push

    def push(**kwargs):
        result = native_push(**kwargs)
        if env.push_hook is not None:
            env.push_hook()
        return result

    monkeypatch.setattr(stack.bpy.ops.ed, "undo_push", push)

    def start(*, steps=2, delivered=True):
        owner = lifecycle.RequestLifetime(lifecycle.ConnectionLifetime(), float("inf"))
        if delivered:
            owner.acknowledge(True)
        request = protocol.Request("scene-start", env.start_spec.name, {"steps": steps}, _lifecycle=owner)
        response = executor.execute_request(request)
        assert response.ok, response.error
        return NS(owner=owner, accepted=response.result, job=manager.active)

    env.start = start
    return env


def drain(env, maximum=30):
    for _ in range(maximum):
        if not env.manager.tick():
            return env.manager.history[0].summary()
    pytest.fail("Bounded Scene fixture did not reach a terminal record")


def reserve_metadata(env, *, phase="checkpoint_before"):
    job = NS(lifetime=env.lifecycle.RequestLifetime.local(), cancel_reason="", deadline=float("inf"),
             revision=1, phase=phase, checkpoint_manager=env.checkpoints)
    origin = object()
    reservation = env.manager.reservations.reserve(job, origin)
    env.manager.reservations.activate(reservation, origin)
    return NS(job=job, reservation=reservation, service=env.manager.reservations)


def stop_after_one_advance(env):
    accepted = env.start()
    before = len(env.advances)
    for _ in range(6):
        assert env.manager.tick()
        if len(env.advances) > before:
            break
    else:
        pytest.fail("Scene owner never reached its first bounded domain phase")
    frames, advances = len(env.stack.frames), list(env.advances)
    env.manager.cancel(accepted.job.job_id)
    terminal = drain(env)
    assert terminal["state"] == "CANCELLED"
    assert len(env.stack.frames) == frames and env.advances == advances
    return accepted


def test_scene_owner_waits_for_handoff_before_checkpoint_or_scene_writes(scene_jobs):
    env = scene_jobs
    accepted = env.start(delivered=False)
    frames = len(env.stack.frames)
    assert env.events.index("driver_created") < env.events.index("provider")
    assert env.manager.tick() and len(env.stack.frames) == frames
    assert env.stack.scene["value"] == 0 and env.advances == []
    accepted.owner.acknowledge(True)
    terminal = drain(env)
    assert terminal["state"] == "SUCCEEDED" and env.stack.scene["value"] == 2
    assert len(env.stack.frames) == frames+2 and env.advances == [(1, 1), (2, 2)]
    assert env.manager.active is None and not accepted.owner.connection.background_active.is_set()


def test_start_provider_edit_cannot_become_the_driver_baseline(scene_jobs):
    env = scene_jobs
    env.provider_hook = lambda: env.stack.scene.__setitem__("value", 71)
    response = env.executor.execute_request(env.protocol.Request(
        "stale-start", env.start_spec.name, {"steps": 1},
        _lifecycle=env.lifecycle.RequestLifetime.local(),
    ))
    assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
    assert len(env.drivers) == 1 and env.drivers[0].expected == 0
    assert env.stack.scene["value"] == 71 and env.advances == []
    assert len(env.stack.frames) == 1 and env.manager.active is None


def test_start_allowlist_identity_is_captured_before_permission_providers(scene_jobs):
    env = scene_jobs
    retained = env.registry.get("jobs.inspect")
    env.provider_hook = lambda: env.registry._tools.__setitem__(
        retained.name, replace(retained, handler=lambda *_: pytest.fail("Replacement control entered")),
    )
    response = env.executor.execute_request(env.protocol.Request(
        "changed-controls", env.start_spec.name, {}, _lifecycle=env.lifecycle.RequestLifetime.local(),
    ))
    assert not response.ok and env.provider_hook is None
    assert env.manager.active is None and env.manager.reservations.owner is None
    assert len(env.stack.frames) == 1 and env.advances == []


@pytest.mark.parametrize("target", ["current", "other"])
def test_start_provider_cannot_replace_the_frozen_checkpoint_marker_inventory(scene_jobs, target):
    env = scene_jobs
    other = Scene(value=9)
    env.stack.bpy.data.scenes.append(other)
    selected = env.stack.scene if target == "current" else other
    newer = "Foreign reserved marker written during start permission validation"
    env.provider_hook = lambda: selected.__setitem__(env.checkpoint_module.MARKER_KEY, newer)
    response = env.executor.execute_request(env.protocol.Request(
        "marker-start", env.start_spec.name, {}, _lifecycle=env.lifecycle.RequestLifetime.local(),
    ))
    assert not response.ok and response.error["context"]["checkpoint_marker_unchanged"] is False
    assert selected[env.checkpoint_module.MARKER_KEY] == newer
    assert env.advances == [] and len(env.stack.frames) == 1
    assert env.manager.active is None and env.manager.reservations.owner is None


@pytest.mark.parametrize("kind", ["pending", "editor"])
def test_start_provider_pending_conflict_preserves_foreign_metadata_without_an_orphaned_owner(scene_jobs, kind):
    env = scene_jobs
    foreign = env.checkpoint_module.UndoStep("Foreign start writer", "Foreign exact marker", 91)
    editor = env.checkpoint_module.MeshEditSession(foreign, "foreign editor", 1, 2, "Mesh")

    def mutate():
        if kind == "pending":
            env.checkpoints._pending = foreign
        else:
            env.checkpoints._editor_session = editor

    env.provider_hook = mutate
    response = env.executor.execute_request(env.protocol.Request(
        "pending-start", env.start_spec.name, {}, _lifecycle=env.lifecycle.RequestLifetime.local(),
    ))
    assert not response.ok and env.provider_hook is None
    assert env.checkpoints._pending is (foreign if kind == "pending" else None)
    assert env.checkpoints._editor_session is (editor if kind == "editor" else None)
    assert env.advances == [] and len(env.stack.frames) == 1
    assert env.manager.active is None and env.manager.reservations.owner is None


@pytest.mark.parametrize("fault", ["before_claim", "after_claim", "pending_status", "activation"])
def test_unaccepted_start_metadata_failure_discards_only_its_untouched_claim(scene_jobs, monkeypatch, fault):
    env = scene_jobs
    denied = env.errors.BridgeError("NOT_IMPLEMENTED", "Fixture start metadata failure.", {"reason": fault})
    claim, status = env.checkpoints.claim_pending, env.checkpoints.pending_status
    activation = env.manager.reservations.activate

    def failing_claim(*args, **kwargs):
        if fault == "after_claim":
            claim(*args, **kwargs)
        raise denied

    def failing_status(_handle):
        raise denied

    def failing_activation(_reservation, _origin):
        raise denied

    if fault in {"before_claim", "after_claim"}:
        monkeypatch.setattr(env.checkpoints, "claim_pending", failing_claim)
    elif fault == "pending_status":
        monkeypatch.setattr(env.checkpoints, "pending_status", failing_status)
    else:
        monkeypatch.setattr(env.manager.reservations, "activate", failing_activation)
    response = env.executor.execute_request(env.protocol.Request(
        "start-metadata-failure", env.start_spec.name, {}, _lifecycle=env.lifecycle.RequestLifetime.local(),
    ))
    assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
    assert response.error["message"] == denied.message and response.error["context"]["reason"] == fault
    assert "scene_start_abort_unknown" not in response.error["context"]
    assert env.manager.active is None and env.manager.reservations.owner is None
    assert not env.manager._scene_records and not env.checkpoints._owned_pending
    assert env.checkpoints._owned_claim is None and env.checkpoints._pending is None
    assert len(env.stack.frames) == 1 and env.advances == []
    # A refused metadata transaction does not poison the next authorized start.
    monkeypatch.setattr(env.checkpoints, "claim_pending", claim)
    monkeypatch.setattr(env.checkpoints, "pending_status", status)
    monkeypatch.setattr(env.manager.reservations, "activate", activation)
    env.start(steps=1)
    assert drain(env)["state"] == "SUCCEEDED"


@pytest.mark.parametrize("route", ["executor", "registry", "invoke"])
def test_internal_scene_turn_has_no_public_or_unowned_entry(scene_jobs, route):
    env = scene_jobs
    spec = env.registry.get("jobs._scene_turn")
    assert spec.modifies and spec.exclusive_mutation and not spec.remote and not spec.batchable
    providers = env.provider_calls
    context = env.executor.context
    with pytest.raises(env.errors.BridgeError):
        if route == "executor":
            env.executor.dispatch(spec.name, {})
        elif route == "registry":
            env.registry.dispatch(spec.name, {}, context)
        else:
            env.registry.invoke(spec, {}, context)
    assert env.provider_calls == providers and env.advances == []
    assert env.manager.active is None and len(env.stack.frames) == 1


def test_each_tick_runs_at_most_one_scene_phase_despite_eight_ms_budget(scene_jobs):
    env = scene_jobs
    env.start(steps=3)
    seen = []
    while env.manager.active is not None:
        before = len(env.advances), len(env.stack.frames)
        env.manager.tick()
        after = len(env.advances), len(env.stack.frames)
        assert after[0]-before[0] <= 1 and after[1]-before[1] <= 1
        assert after != (before[0]+1, before[1]+1)
        seen.append(after)
        assert len(seen) < 15
    assert env.advances == [(1, 1), (2, 2), (3, 3)]
    assert len(seen) >= 5


def test_paused_scene_job_retains_its_phase_and_resumes_after_the_timer_gap(scene_jobs):
    env = scene_jobs
    accepted = env.start(steps=2)
    assert env.manager.tick()  # BEFORE has its own scheduler turn.
    before = dict(env.stack.scene), len(env.stack.frames), list(env.advances), accepted.job.phase
    env.state.set_paused(True)
    assert env.manager.tick() and accepted.job.state == "PAUSED"
    assert env.manager.tick() and env.manager.active is accepted.job
    assert (dict(env.stack.scene), len(env.stack.frames), list(env.advances), accepted.job.phase) == before
    assert env.manager.reservations.owner is not None
    env.state.set_paused(False)
    assert drain(env)["state"] == "SUCCEEDED"
    assert env.advances == [(1, 1), (2, 2)] and len(env.stack.frames) == before[1]+1


@pytest.mark.parametrize("during_provider", [False, True])
def test_external_edit_between_turns_is_not_adopted_or_followed_by_another_write(scene_jobs, during_provider):
    env = scene_jobs
    accepted = env.start()
    while not env.advances:
        assert env.manager.tick()
    before = len(env.stack.frames), list(env.advances)
    if during_provider:
        env.provider_hook = lambda: env.stack.scene.__setitem__("value", 71)
    else:
        env.stack.scene["value"] = 71
    terminal = drain(env)
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    assert env.stack.scene["value"] == 71 and (len(env.stack.frames), env.advances) == before
    assert terminal["checkpoint"]["before_verified"] is True
    assert terminal["checkpoint"]["after_verified"] is False
    assert accepted.job.job_id in env.manager.recovery_ledger
    assert env.manager.active is None and env.manager.reservations.owner is None


@pytest.mark.parametrize("during_provider", [False, True])
@pytest.mark.parametrize("target", ["current", "other"])
def test_foreign_marker_drift_between_turns_is_preserved_without_another_write(scene_jobs, target, during_provider):
    env = scene_jobs
    other = Scene(value=9)
    env.stack.bpy.data.scenes.append(other)
    accepted = env.start()
    assert env.manager.tick()  # The BEFORE writer may update only its proven inventory.
    selected = env.stack.scene if target == "current" else other
    newer = "Foreign reserved marker written between Scene turns"

    def mutate():
        selected[env.checkpoint_module.MARKER_KEY] = newer

    before = len(env.stack.frames), list(env.advances)
    if during_provider:
        env.provider_hook = mutate
    else:
        mutate()
    terminal = drain(env)
    assert terminal["state"] == "FAILED"
    assert terminal["error"]["context"]["checkpoint_marker_unchanged"] is False
    assert selected[env.checkpoint_module.MARKER_KEY] == newer
    assert (len(env.stack.frames), env.advances) == before and env.stack.scene["value"] == 0
    assert terminal["checkpoint"]["before_verified"] and not terminal["checkpoint"]["after_verified"]
    assert accepted.job.job_id in env.manager.recovery_ledger
    assert env.manager.active is None and env.manager.reservations.owner is None


@pytest.mark.parametrize("during_provider", [False, True])
@pytest.mark.parametrize("drift", ["claim", "pending", "editor", "clear"])
def test_pending_metadata_drift_between_turns_never_rebases_the_owner(scene_jobs, drift, during_provider):
    env = scene_jobs
    accepted = env.start()
    assert env.manager.tick()
    foreign_step = env.checkpoint_module.UndoStep("Foreign pending writer", "Foreign exact marker", 91)
    foreign_editor = env.checkpoint_module.MeshEditSession(foreign_step, "foreign editor", 1, 2, "Mesh")

    def mutate():
        if drift == "claim":
            env.checkpoints._owned_claim = None
        elif drift == "pending":
            env.checkpoints._pending = foreign_step
        elif drift == "editor":
            env.checkpoints._editor_session = foreign_editor
        else:
            env.checkpoints.clear()

    before = len(env.stack.frames), dict(env.stack.scene), list(env.advances)
    if during_provider:
        env.provider_hook = mutate
    else:
        mutate()
    terminal = drain(env)
    assert terminal["state"] == "FAILED"
    assert terminal["error"]["context"]["reason"] in {"OWNED_PENDING_REPLACED", "OWNED_PENDING_PHASE_REFUSED"}
    assert (len(env.stack.frames), dict(env.stack.scene), env.advances) == before
    if drift == "pending":
        assert env.checkpoints._pending is foreign_step
    if drift == "editor":
        assert env.checkpoints._editor_session is foreign_editor
    assert terminal["checkpoint"]["before_verified"] and not terminal["checkpoint"]["after_verified"]
    assert accepted.job.job_id in env.manager.recovery_ledger
    assert env.manager.active is None and env.manager.reservations.owner is None


@pytest.mark.parametrize("method", ["fixture.foreign", "fixture.evaluate", "fixture.scene_start"])
@pytest.mark.parametrize("route", ["executor", "registry", "invoke"])
def test_active_owner_rejects_foreign_entries_before_their_providers(scene_jobs, method, route):
    env = scene_jobs
    accepted = env.start()
    count, frames, state = env.provider_calls, len(env.stack.frames), env.state.snapshot()
    params = {"steps": 1} if method == "fixture.scene_start" else {}
    context = env.executor.context
    with pytest.raises(env.errors.BridgeError):
        if route == "executor":
            env.executor.dispatch(method, params)
        elif route == "registry":
            env.registry.dispatch(method, params, context)
        else:
            env.registry.invoke(env.registry.get(method), params, context)
    assert env.provider_calls == count and len(env.stack.frames) == frames
    assert env.manager.active is accepted.job and len(env.drivers) == 1
    assert env.foreign_entries == env.read_entries == []
    assert env.state.snapshot()["current_method"] == state["current_method"]


@pytest.mark.parametrize("method", ["fixture.foreign", "fixture.evaluate", "fixture.scene_start"])
def test_same_turn_context_cannot_authorize_reentrant_entries(scene_jobs, method):
    env = scene_jobs
    env.start(steps=1)
    rejected = []

    def reenter(context):
        count = env.provider_calls
        with pytest.raises(env.errors.BridgeError) as caught:
            env.registry.dispatch(method, {}, context)
        rejected.append(caught.value)
        assert env.provider_calls == count

    env.advance_hook = reenter
    assert drain(env)["state"] == "SUCCEEDED"
    assert len(rejected) == 1 and len(env.drivers) == 1
    assert env.foreign_entries == env.read_entries == []


def test_allowed_control_identity_is_frozen_before_its_provider_runs(scene_jobs):
    env = scene_jobs
    accepted = env.start()
    spec = env.registry.get("jobs.inspect")
    foreign = []
    env.provider_hook = lambda: env.registry._tools.__setitem__(
        spec.name, replace(spec, handler=lambda *_: foreign.append(True)),
    )
    with pytest.raises(env.errors.BridgeError):
        env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id})
    assert env.provider_hook is None and foreign == []
    assert env.manager.active is accepted.job and env.stack.scene["value"] == 0


def test_cached_inspection_list_and_cancel_controls_work_while_scene_owner_is_active(scene_jobs):
    env = scene_jobs
    accepted = env.start()
    while not env.advances:
        assert env.manager.tick()
    before = len(env.stack.frames), dict(env.stack.scene), list(env.advances)
    inspected = env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id})
    listed = env.executor.dispatch("jobs.list", {})
    assert inspected["job_id"] == accepted.job.job_id and inspected["terminal"] is False
    assert listed["jobs"][0]["job_id"] == accepted.job.job_id
    cancelled = env.executor.dispatch("jobs.cancel", {"job_id": accepted.job.job_id})
    assert cancelled["cancel_requested"] and not cancelled["terminal"]
    assert drain(env)["state"] == "CANCELLED"
    assert (len(env.stack.frames), dict(env.stack.scene), env.advances) == before
    assert env.manager.reservations.owner is None


@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("attempt", ["issue_turn", "scheduler_scope", "tick", "release", "abandon_pending", "finish"])
def test_readonly_control_provider_cannot_become_the_scene_scheduler(scene_jobs, monkeypatch, delivered, attempt):
    env = scene_jobs
    accepted = env.start(delivered=delivered)
    job, service = accepted.job, env.manager.reservations
    owner = service.owner
    before = job.summary()
    before.pop("duration_ms")
    native = deepcopy(env.stack.frames), dict(env.stack.scene), list(env.advances)
    checkpoint = env.checkpoints.pending_status(job.pending)
    factory = env.manager.context_factory
    monkeypatch.setattr(env.manager, "context_factory", lambda: pytest.fail("Reentrant context factory reached"))
    rejected = []

    def reenter():
        with pytest.raises(env.errors.BridgeError) as caught:
            if attempt == "issue_turn":
                service.issue_turn(job.reservation, job.phase, job.revision)
            elif attempt == "scheduler_scope":
                with service.scheduler_scope(job.reservation):
                    pytest.fail("Readonly provider acquired scheduler authority")
            elif attempt == "release":
                service.release(job.reservation)
            elif attempt == "abandon_pending":
                env.checkpoints.abandon_pending(job.pending, job.reservation, "Foreign readonly provider")
            elif attempt == "finish":
                env.manager._finish(job, "CANCELLED")
            else:
                env.manager.tick()
        rejected.append(caught.value.context["reason"])
        assert not job.in_tick

    env.provider_hook = reenter
    inspected = env.executor.dispatch("jobs.inspect", {"job_id": job.job_id})
    assert inspected["job_id"] == job.job_id and inspected["terminal"] is False
    reason = "SCENE_SCHEDULER_REENTRY" if attempt in {"scheduler_scope", "tick", "finish"} else "INVALID_SCENE_SCHEDULER_ORIGIN"
    assert rejected == [reason]
    after = job.summary()
    after.pop("duration_ms")
    assert after == before and service.owner is owner and env.manager.active is job
    assert env.checkpoints.pending_status(job.pending) == checkpoint
    assert (env.stack.frames, dict(env.stack.scene), env.advances) == native
    assert service._scheduler is None and not service._turns and env.manager.recovery_ledger == {}
    monkeypatch.setattr(env.manager, "context_factory", factory)


@pytest.mark.parametrize("stop", ["deadline", "cancel", "disconnect", "permission"])
def test_paused_or_undelivered_stopped_owner_starts_no_checkpoint(scene_jobs, stop):
    env = scene_jobs
    accepted = env.start(delivered=False)
    env.state.set_paused(True)
    assert env.manager.tick() and env.manager.active is accepted.job
    before = len(env.stack.frames), dict(env.stack.scene)
    if stop == "deadline":
        accepted.job.deadline = 0
    elif stop == "cancel":
        env.manager.cancel(accepted.job.job_id)
    elif stop == "disconnect":
        accepted.owner.connection.disconnected.set()
    else:
        env.grants[env.permissions_module.Permission.EDIT_SCENE.value] = False
    terminal = drain(env)
    assert terminal["state"] == ("FAILED" if stop == "permission" else "CANCELLED")
    assert (len(env.stack.frames), dict(env.stack.scene)) == before and env.advances == []
    assert env.manager.active is None and not accepted.owner.connection.background_active.is_set()


@pytest.mark.parametrize("kind", ["pending", "editor"])
def test_foreign_pending_and_editor_sessions_refuse_before_any_blender_reader(scene_jobs, monkeypatch, kind):
    env = scene_jobs
    owner = reserve_metadata(env)
    legacy = env.checkpoint_module.UndoStep("foreign pending", "foreign marker", 17)
    session = env.checkpoint_module.MeshEditSession(legacy, "foreign editor", 1, 2, "Mesh")
    pending, editor = (legacy, None) if kind == "pending" else (None, session)
    env.checkpoints._pending, env.checkpoints._editor_session = pending, editor
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    with pytest.raises(env.errors.BridgeError):
        env.checkpoints.claim_pending(owner.reservation, "Rejected Scene owner")
    assert env.checkpoints._pending is pending and env.checkpoints._editor_session is editor
    assert owner.service.owner is not None


@pytest.mark.parametrize("fault", ["foreign", "copy", "closed", "replay"])
def test_turn_origins_reject_before_providers_or_checkpoint_readers(scene_jobs, monkeypatch, fault):
    env = scene_jobs
    owner = reserve_metadata(env)
    context = env.executor.context
    with owner.service.scheduler_scope(owner.reservation) as origin:
        token = owner.service.issue_turn(owner.reservation, owner.job.phase, owner.job.revision, origin=origin)
        if fault == "foreign":
            supplied = object()
        elif fault == "copy":
            supplied = copy(token)
        elif fault == "closed":
            owner.service.close_turn(token)
            supplied = token
        else:
            owner.service.check_entry(env.registry.get("jobs._scene_turn"), context, token)
            supplied = token
        providers = env.provider_calls
        monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
        with pytest.raises(env.errors.BridgeError):
            env.registry.invoke_scene_turn(supplied, {}, context, env.checkpoints)
        owner.service.close_turn(token)
    assert env.provider_calls == providers and env.advances == []
    assert not env.checkpoints._undo_steps and len(env.stack.frames) == 1
    assert owner.service.owner is not None


def test_turn_sequence_and_exact_reservation_cannot_be_copied_or_released_midturn(scene_jobs):
    env = scene_jobs
    owner = reserve_metadata(env)
    with pytest.raises(env.errors.BridgeError):
        owner.service.issue_turn(copy(owner.reservation), owner.job.phase, owner.job.revision)
    with owner.service.scheduler_scope(owner.reservation) as origin:
        for phase, revision in (("other phase", 1), (owner.job.phase, 2)):
            with pytest.raises(env.errors.BridgeError):
                owner.service.issue_turn(owner.reservation, phase, revision, origin=origin)
        token = owner.service.issue_turn(owner.reservation, owner.job.phase, owner.job.revision, origin=origin)
        with pytest.raises(env.errors.BridgeError):
            owner.service.release(owner.reservation, origin=origin)
        assert owner.service.owner is not None
        owner.service.close_turn(copy(token))
        with pytest.raises(env.errors.BridgeError):
            owner.service.release(owner.reservation, origin=origin)
        owner.service.close_turn(token)
        owner.service.release(owner.reservation, origin=origin)
    assert owner.service.owner is None


@pytest.mark.parametrize("fault", ["missing", "foreign", "copy", "expired"])
def test_scheduler_origin_requires_the_live_exact_caller_local_identity(scene_jobs, monkeypatch, fault):
    env = scene_jobs
    owner = reserve_metadata(env)
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    with owner.service.scheduler_scope(owner.reservation) as origin:
        if fault != "expired":
            supplied = {"missing": None, "foreign": object(), "copy": copy(origin)}[fault]
            with pytest.raises(env.errors.BridgeError) as caught:
                owner.service.issue_turn(owner.reservation, owner.job.phase, owner.job.revision, origin=supplied)
            assert caught.value.context["reason"] == "INVALID_SCENE_SCHEDULER_ORIGIN"
    if fault == "expired":
        with pytest.raises(env.errors.BridgeError) as caught:
            owner.service.issue_turn(owner.reservation, owner.job.phase, owner.job.revision, origin=origin)
        assert caught.value.context["reason"] == "INVALID_SCENE_SCHEDULER_ORIGIN"
    assert owner.service.owner is not None and owner.service._scheduler is None
    assert not owner.service._turns and len(env.stack.frames) == 1


@pytest.mark.parametrize("check_only", [False, True])
def test_scene_turn_purpose_cannot_be_changed_by_its_caller(scene_jobs, monkeypatch, check_only):
    env = scene_jobs
    owner = reserve_metadata(env)
    providers = env.provider_calls
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    with owner.service.scheduler_scope(owner.reservation) as origin:
        token = owner.service.issue_turn(owner.reservation, owner.job.phase, owner.job.revision,
                                         origin=origin, check_only=check_only)
        with pytest.raises(env.errors.BridgeError, match="purpose"):
            env.registry.invoke_scene_turn(token, {}, env.executor.context, env.checkpoints, check_only=not check_only)
        owner.service.close_turn(token)
    assert env.provider_calls == providers and len(env.stack.frames) == 1
    assert owner.service.owner is not None and not env.advances


def test_even_a_local_actual_scene_turn_requires_the_start_delivery_receipt(scene_jobs, monkeypatch):
    env = scene_jobs
    accepted = env.start(delivered=False)
    job, service = accepted.job, env.manager.reservations
    providers = env.provider_calls
    checkpoint = env.checkpoints.pending_status(job.pending)
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    with service.scheduler_scope(job.reservation) as origin:
        token = service.issue_turn(job.reservation, job.phase, job.revision, origin=origin)
        with pytest.raises(env.errors.BridgeError) as caught:
            env.registry.invoke_scene_turn(token, {}, env.executor.context, env.checkpoints)
        assert caught.value.context["reason"] == "SCENE_START_NOT_DELIVERED"
        service.close_turn(token)
    assert env.manager.active is job and job.state == "QUEUED" and not job.in_tick
    assert env.checkpoints.pending_status(job.pending) == checkpoint
    assert env.provider_calls == providers and len(env.stack.frames) == 1 and env.advances == []


def test_a_scene_turn_without_native_consumer_cannot_write_an_owned_checkpoint(scene_jobs, monkeypatch):
    env = scene_jobs
    owner = reserve_metadata(env)
    pending = env.checkpoints.claim_pending(owner.reservation, "Owned fixture boundary")
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    with owner.service.scheduler_scope(owner.reservation) as origin:
        token = owner.service.issue_turn(owner.reservation, owner.job.phase, owner.job.revision, origin=origin)
        with pytest.raises(env.errors.BridgeError):
            env.checkpoints.before_modification("Owned fixture boundary", pending=pending, turn=token,
                before_write=lambda: None, after_read=lambda: None, after_native_push=lambda: None)
        owner.service.close_turn(token)
    assert len(env.stack.frames) == 1 and env.checkpoint_module.MARKER_KEY not in env.stack.scene


def test_copied_native_consumer_fails_before_checkpoint_blender_access(scene_jobs, monkeypatch):
    env = scene_jobs
    original = env.checkpoints.before_modification
    substituted = []

    def copied_consumer(*args, **kwargs):
        consumer = kwargs["after_native_push"]
        kwargs["after_native_push"] = copy(consumer)
        substituted.append(True)
        # Start/preflight marker evidence may read Blender. A forged consumer
        # must be rejected before the actual checkpoint function can read it.
        monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected checkpoint read"))
        return original(*args, **kwargs)

    monkeypatch.setattr(env.checkpoints, "before_modification", copied_consumer)
    env.start()
    terminal = drain(env)
    assert terminal["state"] == "FAILED" and substituted == [True]
    assert env.advances == [] and len(env.stack.frames) == 1
    assert env.checkpoint_module.MARKER_KEY not in env.stack.scene


def test_owned_pending_handles_reject_copies_without_touching_the_original(scene_jobs, monkeypatch):
    env = scene_jobs
    owner = reserve_metadata(env)
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    pending = env.checkpoints.claim_pending(owner.reservation, "Owned fixture boundary")
    before = env.checkpoints.pending_status(pending)
    with pytest.raises(env.errors.BridgeError):
        env.checkpoints.pending_status(copy(pending))
    with pytest.raises(env.errors.BridgeError):
        env.checkpoints.abandon_pending(pending, copy(owner.reservation), "Foreign cancellation")
    assert env.checkpoints.pending_status(pending) == before


def test_abandoning_an_owned_handle_never_clears_a_newer_foreign_pending_step(scene_jobs, monkeypatch):
    env = scene_jobs
    owner = reserve_metadata(env)
    pending = env.checkpoints.claim_pending(owner.reservation, "Owned fixture boundary")
    newer = env.checkpoint_module.UndoStep("Newer writer", "Newer exact marker", 91)
    env.checkpoints._pending = newer
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    # Refusal is safe; adopting or clearing the newer step is not.
    with owner.service.scheduler_scope(owner.reservation) as origin, suppress(env.errors.BridgeError):
        env.checkpoints.abandon_pending(pending, owner.reservation, "Stopped old owner", origin=origin)
    assert env.checkpoints._pending is newer


@pytest.mark.parametrize("loss", ["claim_cleared", "checkpoint_clear"])
@pytest.mark.parametrize("method", ["create", "before_modification", "after_modification",
                                    "finish_editor_session", "restore_operation", "undo_last", "restore_last"])
def test_retained_pending_claim_loss_keeps_legacy_native_writers_fenced(scene_jobs, monkeypatch, loss, method):
    env = scene_jobs
    owner = reserve_metadata(env)
    pending = env.checkpoints.claim_pending(owner.reservation, "Retained owned boundary")
    if loss == "claim_cleared":
        env.checkpoints._owned_claim = None
    else:
        env.checkpoints.clear()
    retained = env.checkpoints.pending_status(pending)
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    args = ("Foreign legacy writer",) if method in {"create", "before_modification", "after_modification"} else ()
    with pytest.raises(env.errors.BridgeError) as caught:
        getattr(env.checkpoints, method)(*args)
    assert caught.value.context["reason"] == "OWNED_PENDING_CONFLICT"
    assert env.checkpoints.pending_status(pending) == retained
    assert owner.service.owner is not None and len(env.stack.frames) == 1


@pytest.mark.parametrize("stop", ["marker_delete", "native_push"])
def test_partial_before_failure_retains_actual_marker_and_native_receipts(scene_jobs, monkeypatch, stop):
    env = scene_jobs
    old_checkpoint = env.checkpoints.create("Retained earlier checkpoint")
    if stop == "marker_delete":
        class StopOnMarkerDelete(Scene):
            def __delitem__(self, key):
                super().__delitem__(key)
                if key == env.checkpoint_module.MARKER_KEY:
                    env.manager.cancel_all("Stopped after first owned marker deletion")

        scene = StopOnMarkerDelete(env.stack.scene)
        env.stack.scene = env.stack.bpy.context.scene = scene
        env.stack.bpy.data.scenes = [scene]
    else:
        env.push_hook = lambda: env.manager.cancel_all("Stopped after actual native push")
    accepted = env.start()
    frames, position = len(env.stack.frames), env.checkpoints._window.position
    terminal = drain(env)
    assert terminal["state"] == "CANCELLED" and env.advances == []
    facts = terminal["error"]["context"]["checkpoint_bookkeeping"]
    assert facts["marker_writes_completed"] == (1 if stop == "marker_delete" else 2)
    assert facts["native_snapshots_completed"] == (0 if stop == "marker_delete" else 1)
    assert facts["compensation_performed"] is False
    assert len(env.stack.frames) == frames+facts["native_snapshots_completed"]
    assert env.checkpoints._window.position == position+facts["native_snapshots_completed"]
    assert env.checkpoints.list() == [old_checkpoint]
    assert accepted.job.job_id in env.manager.recovery_ledger
    assert env.manager.recovery_ledger[accepted.job.job_id]
    assert env.manager.active is None and env.manager.reservations.owner is None


@pytest.mark.parametrize("clear", ["state", "checkpoint", "history"])
def test_diagnostic_or_checkpoint_clearing_cannot_unlock_a_live_scene_owner(scene_jobs, clear):
    env = scene_jobs
    accepted = env.start()
    if clear == "state":
        env.state.reset()
    elif clear == "checkpoint":
        env.checkpoints.clear()
    else:
        env.manager.history.clear()
    providers = env.provider_calls
    assert env.manager.active is accepted.job and env.manager.reservations.owner is not None
    with pytest.raises(env.errors.BridgeError):
        env.executor.dispatch(env.foreign_spec.name, {})
    assert env.provider_calls == providers and env.foreign_entries == []
    assert env.manager.active is accepted.job and not accepted.job.summary()["terminal"]


@pytest.mark.parametrize("when", ["start_provider", "turn_provider", "advance"])
def test_raw_state_reset_invalidates_the_origin_before_the_next_scene_write(scene_jobs, monkeypatch, when):
    env = scene_jobs
    if when == "start_provider":
        env.provider_hook = env.state.reset
        monkeypatch.setattr(env.checkpoints, "before_modification", lambda *_args, **_kwargs: pytest.fail("Unexpected checkpoint write"))
        response = env.executor.execute_request(env.protocol.Request(
            "reset-start", env.start_spec.name, {}, _lifecycle=env.lifecycle.RequestLifetime.local(),
        ))
        assert not response.ok and response.error["context"]["reason"] == "SCENE_RUNTIME_RESET"
        assert env.manager.active is None and env.manager.reservations.owner is None
        assert env.advances == [] and len(env.stack.frames) == 1 and env.stack.scene["value"] == 0
        return
    accepted = env.start()
    assert env.manager.tick()  # Complete BEFORE before exercising the gap.
    before = len(env.stack.frames), dict(env.stack.scene)
    if when == "turn_provider":
        env.provider_hook = env.state.reset
    else:
        env.advance_hook = lambda _context: env.state.reset()
    monkeypatch.setattr(env.checkpoints, "after_modification", lambda *_args, **_kwargs: pytest.fail("Unexpected checkpoint write"))
    monkeypatch.setattr(env.stack.bpy.ops.ed, "undo_push", lambda **_kwargs: pytest.fail("Unexpected native push"))
    terminal = drain(env)
    assert terminal["state"] == "FAILED" and terminal["error"]["context"]["reason"] == "SCENE_RUNTIME_RESET"
    assert env.advances == [] and (len(env.stack.frames), dict(env.stack.scene)) == before
    assert accepted.job.job_id in env.manager.recovery_ledger
    assert env.manager.active is None and env.manager.reservations.owner is None


def test_terminal_history_failure_retains_recovery_evidence_before_releasing_owner(scene_jobs, monkeypatch):
    env = scene_jobs
    accepted = env.start()
    while not env.advances:
        assert env.manager.tick()

    def unavailable_history(**_kwargs):
        raise RuntimeError("Fixture operation history unavailable")

    monkeypatch.setattr(env.state, "record_operation", unavailable_history)
    env.manager.cancel(accepted.job.job_id)
    terminal = drain(env)
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    assert accepted.job.job_id in env.manager.recovery_ledger
    assert env.manager.recovery_ledger[accepted.job.job_id]
    assert env.manager.active is None and env.manager.reservations.owner is None


def test_before_push_history_failure_preserves_primary_timeout_and_partial_native_facts(scene_jobs, monkeypatch):
    env = scene_jobs
    accepted = env.start()

    def unavailable_history(**_kwargs):
        raise RuntimeError("Fixture operation history unavailable after native BEFORE")

    monkeypatch.setattr(env.state, "record_operation", unavailable_history)
    env.push_hook = lambda: env.manager.cancel_all("Stopped after actual native BEFORE push")
    terminal = drain(env)
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    assert terminal["error"]["code"] == "TIMEOUT"
    context = terminal["error"]["context"]
    assert context["operation_history_unknown"] and context["possible_mutation"]
    facts = context["checkpoint_bookkeeping"]
    assert facts["native_snapshots_completed"] == 1 and facts["marker_writes_completed"] == 1
    assert facts["compensation_performed"] is False
    assert terminal["checkpoint"]["native_snapshots_completed"] == 1
    assert env.advances == [] and len(env.stack.frames) == 2
    assert env.manager.recovery_ledger[accepted.job.job_id]["error"] == terminal["error"]
    assert env.manager.active is None and env.manager.reservations.owner is None


def test_failed_recovery_ledger_retention_keeps_the_owner_fenced(scene_jobs):
    env = scene_jobs
    accepted = env.start()
    while not env.advances:
        assert env.manager.tick()

    class UnavailableLedger(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("Fixture recovery ledger unavailable")

    env.manager.recovery_ledger = UnavailableLedger(env.manager.recovery_ledger)
    env.manager.cancel(accepted.job.job_id)
    with pytest.raises(RuntimeError, match="recovery ledger unavailable"):
        env.manager.tick()
    assert env.manager.active is accepted.job and env.manager.reservations.owner is not None
    assert not accepted.job.in_tick and not env.manager.history
    assert not accepted.job.summary()["terminal"]
    providers = env.provider_calls
    with pytest.raises(env.errors.BridgeError):
        env.executor.dispatch(env.foreign_spec.name, {})
    assert env.provider_calls == providers and env.foreign_entries == []


@pytest.mark.parametrize("scene_jobs", [2], indirect=True)
def test_recovery_ledger_capacity_refuses_new_work_without_evicting_receipts(scene_jobs):
    env = scene_jobs
    for _ in range(2):
        stopped = stop_after_one_advance(env)
        assert stopped.job.job_id in env.manager.recovery_ledger
    retained = dict(env.manager.recovery_ledger)
    frames, advances = len(env.stack.frames), list(env.advances)
    response = env.executor.execute_request(env.protocol.Request(
        "ledger-full", env.start_spec.name, {"steps": 1},
        _lifecycle=env.lifecycle.RequestLifetime.local(),
    ))
    assert not response.ok and env.manager.active is None
    assert env.manager.recovery_ledger == retained
    assert len(env.stack.frames) == frames and env.advances == advances


@pytest.mark.parametrize("scene_jobs", [64], indirect=True)
def test_recovery_receipt_survives_thirty_three_terminal_summary_evictions(scene_jobs, monkeypatch):
    env = scene_jobs
    first = stop_after_one_advance(env)
    receipt = deepcopy(env.manager.recovery_ledger[first.job.job_id])
    retired = [first.job]
    for _ in range(33):
        retired.append(env.start(steps=1).job)
        assert drain(env)["state"] == "SUCCEEDED"
    assert len(env.manager.history) == 32
    assert all(job.job_id != first.job.job_id for job in env.manager.history)
    assert env.manager.recovery_ledger[first.job.job_id] == receipt
    assert env.manager.active is None and env.manager.reservations.owner is None
    assert env.manager._scene_records == {} and all(job.driver is None for job in retired)
    providers = env.provider_calls
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Unexpected Blender read"))
    old = env.manager.inspect(first.job.job_id)
    assert old["job_id"] == first.job.job_id and old["terminal"] is True
    assert old["checkpoint"] == receipt["checkpoint"] and env.provider_calls == providers


def test_image_jobs_keep_their_multiple_cooperative_steps_per_tick(request, monkeypatch, scene_job_manager):
    env = request.getfixturevalue("jobs")
    domain = importlib.import_module(env.module.__package__ + ".scene_jobs")
    registry_module = importlib.import_module(env.module.__package__ + ".tool_registry")
    original_context = env.context()
    manager = None

    def context():
        return registry_module.ToolContext(
            original_context.state, original_context.permissions, original_context.registry,
            original_context.checkpoints, jobs=manager,
        )

    if scene_job_manager == "native_save":
        runtime = importlib.import_module(env.module.__package__ + ".runtime")
        policy_module = importlib.import_module(env.module.__package__ + ".native_save_policy")
        grant = policy_module.NativeSaveGrant("inherited-scene-image-fixture", object())
        assert not grant.active() and grant.status()["armed"] is False
        manager = runtime.NativeSaveJobs(
            context, budget_ms=lambda: 8., registry=original_context.registry, native_save_policy=grant,
        )
    else:
        manager = domain.SceneJobs(context, budget_ms=lambda: 8., registry=original_context.registry)
    env.manager, env.context = manager, context
    original_steps, measured = env.paint.brush.paint_steps, []

    def many_steps(*args, **kwargs):
        for index in range(25):
            measured.append(index)
            yield {"phase": "fixture_private_image_work", "completed": index+1, "total": 25}
        return (yield from original_steps(*args, **kwargs))

    monkeypatch.setattr(env.paint.brush, "paint_steps", many_steps)
    monkeypatch.setattr(time, "perf_counter", lambda: 0.)
    accepted = start(env)
    assert not manager.tick()
    terminal = manager.inspect(accepted["job_id"])
    assert terminal["state"] == "SUCCEEDED" and measured == list(range(25))
    assert terminal["undo_boundary_finalized"] and env.images.get("Painted") is not None


def storage_model(env, monkeypatch):
    """Concrete source-seal model; no result here qualifies a native helper."""
    import sys
    from types import ModuleType

    effects = importlib.import_module(env.domain.__package__ + ".mesh_storage_effects")
    driver_module = ModuleType(env.domain.__package__ + ".tools._mesh_storage_job")
    original_source = importlib.import_module(env.domain.__package__ + ".mesh_storage_source")
    original_seal = original_source.SourceSeal
    source_module = ModuleType(env.domain.__package__ + ".mesh_storage_source")
    vars(source_module).update(vars(original_source))
    env.storage_source_calls = 0

    class SourceSeal(tuple):
        __slots__ = ()

        def __new__(cls):
            return tuple.__new__(cls, original_seal.capture())

        def verify(self):
            env.storage_source_calls += 1
            original_seal.verify(self)

    source_module.SourceSeal = SourceSeal

    class MeshStorageDriver(env.driver_type):
        def __init__(self, context, params):
            super().__init__(context, params)
            self.source_seal = SourceSeal()
            self.storage_effects = effects.MeshStorageJournal(("uv",))
            journal = object.__new__(effects.PreparationJournal)
            row = dict.fromkeys(("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
                                 "after_storage_observed", "verified", "baseline_conflict"), False)
            row.update(name="uv", action="MATERIALIZE_SINGLE", entry_kind="FOREACH_GET", before_storage="SINGLE",
                       after_storage=None, readback_entries=0, readback_returns=0, logical_values_sha256=None,
                       retained_physical_transition="NOT_ENTERED")
            journal._cells, journal._plan = (row,), object()
            self.storage_effects.attach(0, journal)
            self.cell = row

        def advance(self, context):
            progress = super().advance(context)
            for flag in ("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
                         "after_storage_observed", "verified"):
                self.cell[flag] = True
            self.cell.update(after_storage="ARRAY", readback_entries=self.count, readback_returns=self.count,
                             logical_values_sha256="a" * 64, retained_physical_transition="OBSERVED_SINGLE_TO_ARRAY")
            return progress

    MeshStorageDriver.__module__ = driver_module.__name__
    driver_module.MeshStorageDriver = MeshStorageDriver
    monkeypatch.setitem(sys.modules, driver_module.__name__, driver_module)
    monkeypatch.setitem(sys.modules, source_module.__name__, source_module)
    env.start_spec = env.registry.register("fixture.storage_start",
        lambda context, params: context.jobs.start_scene(context, params, time_limit=60.),
        modifies=True, permissions=MeshStorageDriver.required_permissions, automatic_checkpoint=False,
        exclusive_mutation=True, checkpoint_owns_finalization=True, record_history=False,
        protected_scope_resolver=lambda _context, _params: {"scope_complete": True},
        checkpoint_admission_factory=env.domain.start_admission(MeshStorageDriver))
    env.storage_effects_module, env.storage_driver_type = effects, MeshStorageDriver
    return env


# This exercises 33 real jobs with every source check; give the aggregate
# workload a bounded budget instead of the default ten-second single test cap.
@pytest.mark.timeout(30)
def test_storage_terminal_journal_survives_driver_retirement_and_history_eviction(scene_jobs, monkeypatch):
    env = storage_model(scene_jobs, monkeypatch)
    stopped = stop_after_one_advance(env)
    job = stopped.job
    receipt = deepcopy(env.manager.recovery_ledger[job.job_id])
    assert receipt["summary"]["storage_effects"]["rows"][0]["verified"]
    assert receipt["summary"]["storage_effects"]["sealed"]
    assert job.driver is None and job.storage_driver_proof is None and job.storage_reader_proof is None
    assert job.storage_effects.sealed
    for _ in range(33):
        env.start(steps=1)
        assert drain(env)["state"] == "SUCCEEDED"
    assert all(record.job_id != job.job_id for record in env.manager.history)
    providers, sources = env.provider_calls, env.storage_source_calls
    monkeypatch.setattr(env.checkpoint_module, "require_blender", lambda: pytest.fail("Stopped native read"))
    inspected = env.manager.inspect(job.job_id)
    assert inspected["storage_effects"] == receipt["summary"]["storage_effects"]
    assert inspected["terminal_history_evicted"] and env.provider_calls == providers and env.storage_source_calls == sources
    history = next(record for record in env.state.history(100) if record["operation_id"] == job.operation_id)
    assert history["job_evidence"]["storage_effects"] == inspected["storage_effects"]


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("replacement", ["instance", "class", "seal"])
def test_storage_post_provider_callback_replacement_refused_without_execution(scene_jobs, monkeypatch, paused, replacement):
    env = storage_model(scene_jobs, monkeypatch)
    accepted = env.start(delivered=False)
    driver = accepted.job.driver
    frames = deepcopy(env.stack.frames)
    env.state.set_paused(paused)
    foreign = []

    def replace_callback():
        if replacement == "instance":
            driver.check_after_read = lambda _context: foreign.append("instance")
        elif replacement == "class":
            monkeypatch.setattr(type(driver), "check_after_read", lambda _self, _context: foreign.append("class"))
        else:
            monkeypatch.setattr(type(driver.source_seal), "verify", lambda _self: foreign.append("seal"))

    env.provider_hook = replace_callback
    terminal = drain(env)
    assert terminal["state"] == "FAILED" and terminal["error"]["context"]["reason"] == "MESH_STORAGE_DRIVER_SOURCE_CHANGED"
    assert foreign == [] and env.advances == [] and env.stack.frames == frames


def test_storage_snapshot_allocation_failure_retains_owner_then_retries_without_providers(scene_jobs, monkeypatch):
    env = storage_model(scene_jobs, monkeypatch)
    accepted = env.start()
    for _ in range(6):
        env.manager.tick()
        if env.advances:
            break
    env.manager.cancel(accepted.job.job_id)
    original = env.domain._storage_snapshot
    attempts = []

    def exhausted(job, *, seal=False):
        attempts.append(job)
        raise MemoryError("injected snapshot allocation")

    monkeypatch.setattr(env.domain, "_storage_snapshot", exhausted)
    with pytest.raises(MemoryError):
        env.manager.tick()
    assert env.manager.active is accepted.job and accepted.job.state == "FINALIZING"
    assert accepted.job.driver is not None and accepted.job.storage_effects_snapshot is None
    providers, sources = env.provider_calls, env.storage_source_calls
    frames, advances = len(env.stack.frames), list(env.advances)
    monkeypatch.setattr(env.domain, "_storage_snapshot", original)
    monkeypatch.setattr(env.manager, "context_factory", lambda: pytest.fail("Stopped context factory"))
    assert not env.manager.tick()
    assert accepted.job.state == "CANCELLED" and accepted.job.driver is None
    assert env.provider_calls == providers and env.storage_source_calls == sources
    assert (len(env.stack.frames), env.advances) == (frames, advances) and attempts == [accepted.job]


def test_storage_terminal_never_calls_replaced_stopped_driver(scene_jobs, monkeypatch):
    env = storage_model(scene_jobs, monkeypatch)
    accepted = env.start()
    for _ in range(6):
        env.manager.tick()
        if env.advances:
            break
    driver = accepted.job.driver
    env.manager.cancel(accepted.job.job_id)
    source_count, providers = env.storage_source_calls, env.provider_calls
    foreign = []
    for name in ("check_after_read", "advance", "native_push_delegates", "after_native_push"):
        monkeypatch.setattr(type(driver), name, lambda *_args: foreign.append("stopped callback"))
    assert not env.manager.tick()
    assert accepted.job.state == "CANCELLED" and accepted.job.driver is None
    assert accepted.job.storage_effects_snapshot["rows"][0]["verified"]
    assert foreign == [] and env.storage_source_calls == source_count and env.provider_calls == providers


def test_storage_terminal_descriptor_default_poison_refuses_then_retries_without_callbacks(scene_jobs, monkeypatch):
    env = storage_model(scene_jobs, monkeypatch)
    accepted = env.start()
    env.manager.cancel(accepted.job.job_id)
    keywords = env.storage_effects_module.snapshot_storage_effects.__kwdefaults__
    held = keywords["_names"]
    calls = []

    class Foreign:
        def __get__(self, *_args):
            calls.append("foreign descriptor")
            raise AssertionError

    monkeypatch.setitem(keywords, "_names", Foreign())
    with pytest.raises(env.errors.BridgeError) as failure:
        env.manager.tick()
    assert failure.value.context["reason"] == "MESH_STORAGE_EFFECTS_SOURCE_CHANGED"
    assert accepted.job.state == "FINALIZING" and env.manager.active is accepted.job and calls == []
    providers, sources = env.provider_calls, env.storage_source_calls
    monkeypatch.setitem(keywords, "_names", held)
    assert not env.manager.tick()
    assert accepted.job.state == "CANCELLED" and calls == []
    assert env.provider_calls == providers and env.storage_source_calls == sources


def test_storage_foreign_helper_cell_key_refused_without_equality_then_repaired(scene_jobs, monkeypatch):
    env = storage_model(scene_jobs, monkeypatch)
    accepted = env.start()
    driver = accepted.job.driver
    env.manager.cancel(accepted.job.job_id)
    calls = []

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, _other):
            calls.append("foreign equality")
            return True

    key = Key("name")
    driver.cell.pop("name")
    driver.cell[key] = "uv"
    calls.clear()
    with pytest.raises(env.errors.BridgeError) as failure:
        env.manager.tick()
    assert failure.value.context["reason"] == "MESH_STORAGE_EFFECTS_INVALID" and calls == []
    assert env.manager.active is accepted.job and driver.storage_effects.cells[0] is driver.cell
    providers, sources = env.provider_calls, env.storage_source_calls
    driver.cell.pop(key)
    driver.cell["name"] = "uv"
    assert not env.manager.tick()
    assert calls == [] and env.provider_calls == providers and env.storage_source_calls == sources


def test_storage_held_source_checker_uses_native_bindings_not_mutable_module_builtins(scene_jobs, monkeypatch):
    env = storage_model(scene_jobs, monkeypatch)
    accepted = env.start(delivered=False)
    proof = accepted.job.storage_driver_proof
    calls = []

    def foreign(*_args, **_kwargs):
        calls.append("foreign builtin")
        raise AssertionError

    for name in ("type", "len", "any", "zip"):
        monkeypatch.setattr(env.domain, name, foreign, raising=False)
    # Isolated source-checker model only. The real SourceSeal additionally
    # refuses module namespace changes before returning to the scheduler.
    with pytest.raises(env.errors.BridgeError) as failure:
        env.domain._check_storage_driver(proof)
    assert failure.value.context["reason"] == "STORAGE_SOURCE_CHANGED"
    assert calls == []


def test_storage_terminal_reader_uses_held_native_bindings_and_error_then_retries(scene_jobs, monkeypatch):
    env = storage_model(scene_jobs, monkeypatch)
    accepted = env.start()
    env.manager.cancel(accepted.job.job_id)
    keywords = env.storage_effects_module.snapshot_storage_effects.__kwdefaults__
    held = keywords["_names"]
    calls = []

    class Foreign:
        def __get__(self, *_args):
            calls.append("foreign descriptor")
            raise AssertionError

    def foreign(*_args, **_kwargs):
        calls.append("foreign checker binding")
        raise AssertionError

    monkeypatch.setitem(keywords, "_names", Foreign())
    with pytest.raises(env.errors.BridgeError) as failure:
        env.manager.tick()
    assert failure.value.context["reason"] == "MESH_STORAGE_EFFECTS_SOURCE_CHANGED"
    assert accepted.job.state == "FINALIZING" and env.manager.active is accepted.job
    providers, sources = env.provider_calls, env.storage_source_calls
    reader = env.domain._storage_snapshot
    with monkeypatch.context() as stopped_source:
        for name in ("type", "len", "any", "zip", "refused"):
            stopped_source.setattr(env.domain, name, foreign, raising=False)
        # Isolate the retained reader from unrelated scheduler methods, which
        # still use their own module's globals. A stopped source verifier is
        # intentionally unavailable; even refusal must use its retained error.
        with pytest.raises(env.errors.BridgeError) as failure:
            reader(accepted.job, seal=True)
        assert failure.value.context["reason"] == "MESH_STORAGE_EFFECTS_SOURCE_CHANGED"
    assert calls == [] and env.manager.active is accepted.job
    monkeypatch.setitem(keywords, "_names", held)
    monkeypatch.setattr(env.manager, "context_factory", lambda: pytest.fail("Stopped context factory"))
    assert not env.manager.tick()
    assert accepted.job.state == "CANCELLED" and accepted.job.driver is None
    assert env.provider_calls == providers and env.storage_source_calls == sources and calls == []
