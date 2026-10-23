"""A nested cached read keeps its own grants without reviving its Scene parent."""

import pytest
from test_scene_job_authority import domain_start, snapshot
from test_scene_jobs import scene_jobs as scene_jobs


@pytest.mark.parametrize("route", ["same_context", "fresh_context"])
def test_nested_readonly_revocation_stops_outer_pure_gate_without_another_provider(scene_jobs, route):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)
    reads = []

    def inspect(context):
        env.provider_hook = lambda: env.grants.__setitem__(env.permissions_module.Permission.EDIT_ANIMATION.value, False)
        calls = env.provider_calls
        if route == "same_context":
            value = env.registry.dispatch("jobs.inspect", {"job_id": accepted.job.job_id}, context)
        else:
            value = env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id})
        assert value["job_id"] == accepted.job.job_id and env.provider_calls == calls+1
        reads.append(value)
        # No new provider: the actual driver's next safe point is pure.

    env.advance_hook = inspect
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert reads and terminal["state"] == "FAILED"
    assert terminal["error"]["code"] == "PERMISSION_DENIED"
    assert env.permissions_module.Permission.EDIT_ANIMATION.value in terminal["error"]["context"]["missing_permissions"]
    assert snapshot(env) == before
    assert terminal["checkpoint"]["native_snapshots_completed"] == 1 and not terminal["checkpoint"]["after_verified"]


def test_fresh_readonly_revocation_during_native_push_prevents_role_adoption_and_later_marker(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    reads = []

    def after_push():
        env.provider_hook = lambda: env.grants.__setitem__(env.permissions_module.Permission.EDIT_ANIMATION.value, False)
        reads.append(env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id}))

    env.push_hook = after_push
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert reads and terminal["error"]["code"] == "PERMISSION_DENIED"
    assert terminal["checkpoint"]["native_snapshots_completed"] == 1
    assert terminal["checkpoint"]["marker_writes_completed"] == 1
    assert not terminal["checkpoint"]["before_verified"] and not env.advances
    assert env.events.count("authenticated_push") == 0
    assert len(env.stack.frames) == 2


def test_nested_fresh_readonly_inside_later_provider_retains_owner_denial(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)
    reads = []

    def outer_provider():
        env.provider_hook = lambda: env.grants.__setitem__(env.permissions_module.Permission.EDIT_ANIMATION.value, False)
        reads.append(env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id}))

    def advance(context):
        env.provider_hook = outer_provider
        calls = env.provider_calls
        try:
            context.require(env.permissions_module.Permission.EDIT_SCENE)
        finally:
            assert env.provider_calls == calls+2
        pytest.fail("A nested readonly denial must stop the later Scene permission request")

    env.advance_hook = advance
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert reads and terminal["error"]["code"] == "PERMISSION_DENIED" and snapshot(env) == before


@pytest.mark.parametrize("after_before", [False, True])
def test_replaced_original_permission_source_stops_without_reading_replacement(scene_jobs, after_before):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    if after_before:
        assert env.manager.tick()
    before = snapshot(env)
    env.permissions._source = lambda: pytest.fail("Replacement provider must not authorize the accepted job")
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["error"]["context"]["reason"] == "SCENE_START_PERMISSION_SOURCE_CHANGED"
    assert snapshot(env) == before


def test_scene_context_cannot_substitute_another_permission_manager(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)
    original_factory = env.manager.context_factory

    def other_manager():
        context = original_factory()
        context.permissions = env.permissions_module.PermissionManager(
            lambda: pytest.fail("A substitute provider must not authorize the accepted job"))
        return context

    env.manager.context_factory = other_manager
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["error"]["context"]["reason"] == "SCENE_START_PERMISSION_SOURCE_CHANGED"
    assert snapshot(env) == before


def test_caught_nested_provider_failure_cannot_leave_outer_permission_evidence_live(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)

    def provider_failure():
        raise env.errors.BridgeError("PERMISSION_DENIED", "Original permission provider failed.")

    def advance(_context):
        env.provider_hook = provider_failure
        with pytest.raises(env.errors.BridgeError):
            env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id})

    env.advance_hook = advance
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["error"]["code"] == "PERMISSION_DENIED"
    assert terminal["error"]["message"] == "Original permission provider failed."
    assert snapshot(env) == before


def test_caught_readonly_own_grant_denial_does_not_weaken_or_expand_scene_grants(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start(steps=1)
    assert env.manager.tick()
    env.grants[env.permissions_module.Permission.INSPECT_SCENE.value] = False
    denied = []

    def advance(_context):
        with pytest.raises(env.errors.BridgeError) as error:
            env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id})
        denied.append(error.value.context["missing_permissions"])

    env.advance_hook = advance
    assert env.manager.tick() and not env.manager.tick()
    assert accepted.job.summary()["state"] == "SUCCEEDED"
    assert denied == [[env.permissions_module.Permission.INSPECT_SCENE.value]]
    assert env.advances == [(1, 1)]


def test_start_authority_binding_cannot_be_weakened_by_provider_assignment(scene_jobs):
    from dataclasses import FrozenInstanceError, replace

    env = scene_jobs
    original = domain_start(env)
    guarded = []

    def weaken():
        context = env.drivers[-1].last_context
        admission = context.checkpoint_admission.callback
        with pytest.raises(FrozenInstanceError):
            admission.authority = replace(admission.authority, required_permissions=())
        guarded.append(True)
        env.grants[env.permissions_module.Permission.EDIT_ANIMATION.value] = False

    env.provider_hook = weaken
    before = snapshot(env)
    response = env.executor.execute_request(env.protocol.Request(
        "immutable-authority", original.name, {"steps": 1}, _lifecycle=env.lifecycle.RequestLifetime.local()))
    assert not response.ok and response.error["code"] == "PERMISSION_DENIED" and guarded
    assert snapshot(env) == before and env.manager.active is None and env.manager.reservations.owner is None
