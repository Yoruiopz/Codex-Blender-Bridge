"""A Scene job retains the starter domain's exact authority across yields."""

from __future__ import annotations

import importlib
from dataclasses import replace

import pytest
from test_scene_jobs import scene_jobs as scene_jobs


def domain_start(env, *, driver_factory=None, declared_permissions=None):
    """Keep the adapter permission tuple deliberately narrower than its spec."""
    permissions = env.permissions_module.Permission
    module = importlib.import_module(f"{env.domain.__package__}.tools.core")
    env.registry.register("toolsets.disable", module.toolsets_disable, record_history=False)
    env.start_spec = env.registry.register(
        "fixture.simulation_start", lambda context, params: context.jobs.start_scene(context, params, time_limit=60.),
        toolset="simulation", modifies=True,
        permissions=(permissions.EDIT_SCENE, permissions.EDIT_ANIMATION) if declared_permissions is None else declared_permissions,
        automatic_checkpoint=False, exclusive_mutation=True, checkpoint_owns_finalization=True,
        checkpoint_admission_factory=env.domain.start_admission(driver_factory or env.driver_type), record_history=False,
    )
    env.registry.enable_toolset("simulation")
    return env.start_spec


def snapshot(env):
    return len(env.stack.frames), dict(env.stack.scene), list(env.advances)


def stopped_without_next_write(env, accepted, before, *, code=None):
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    if code is not None:
        assert terminal["error"]["code"] == code
    assert snapshot(env) == before
    assert env.manager.active is None and env.manager.reservations.owner is None
    assert env.manager.recovery_ledger[accepted.job.job_id]["checkpoint"] == terminal["checkpoint"]
    return terminal


@pytest.mark.parametrize("after_before", [False, True])
def test_disabling_only_accepted_domain_stops_before_another_scene_action(scene_jobs, after_before):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    if after_before:
        assert env.manager.tick()
    before = snapshot(env)
    result = env.executor.dispatch("toolsets.disable", {"name": "simulation"})
    assert result["enabled"] is False and "core" in env.registry.enabled_toolsets
    assert env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id})["terminal"] is False
    assert env.executor.dispatch("jobs.list", {})["jobs"][0]["job_id"] == accepted.job.job_id
    terminal = stopped_without_next_write(env, accepted, before, code="TOOLSET_DISABLED")
    assert terminal["checkpoint"]["before_verified"] is after_before
    assert terminal["checkpoint"]["after_verified"] is False


@pytest.mark.parametrize("after_before", [False, True])
@pytest.mark.parametrize("change", ["same_name", "same_name_weaker_permissions", "removed"])
def test_original_starter_identity_cannot_be_replaced_or_removed_between_turns(scene_jobs, after_before, change):
    env = scene_jobs
    original = domain_start(env)
    accepted = env.start()
    if after_before:
        assert env.manager.tick()
    before = snapshot(env)
    if change == "removed":
        env.registry._tools.pop(original.name)
    else:
        kwargs = {"handler": lambda *_: pytest.fail("Replacement starter must never run")}
        if change == "same_name_weaker_permissions":
            kwargs.update(toolset="core", permissions=frozenset())
        env.registry._tools[original.name] = replace(original, **kwargs)
    stopped_without_next_write(env, accepted, before)


@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("paused", [False, True])
def test_spec_permission_omitted_by_driver_still_required_for_check_only_turn(scene_jobs, delivered, paused):
    env = scene_jobs
    domain_start(env)
    accepted = env.start(delivered=delivered)
    env.state.set_paused(paused)
    permission = env.permissions_module.Permission.EDIT_ANIMATION.value
    env.grants[permission] = False
    before = snapshot(env)
    terminal = stopped_without_next_write(env, accepted, before, code="PERMISSION_DENIED")
    assert permission in terminal["error"]["context"]["missing_permissions"]
    assert not terminal["checkpoint"]["before_verified"]


def test_mutable_job_permission_tuple_cannot_weaken_accepted_starter_or_driver_grants(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    accepted.job.required_permissions = ()
    permission = env.permissions_module.Permission.EDIT_ANIMATION.value
    env.grants[permission] = False
    before = snapshot(env)
    terminal = stopped_without_next_write(env, accepted, before, code="PERMISSION_DENIED")
    assert permission in terminal["error"]["context"]["missing_permissions"]
    assert terminal["checkpoint"]["before_verified"] and not terminal["checkpoint"]["after_verified"]


def test_driver_permission_beyond_starter_spec_remains_required_after_mutable_tuple_changes(scene_jobs):
    env = scene_jobs
    permission = env.permissions_module.Permission
    domain_start(env, declared_permissions=(permission.EDIT_ANIMATION,))
    accepted = env.start()
    assert env.manager.tick()
    accepted.job.required_permissions = (permission.EDIT_ANIMATION,)
    accepted.job.driver.required_permissions = (permission.EDIT_ANIMATION,)
    env.grants[permission.EDIT_SCENE.value] = False
    before = snapshot(env)
    terminal = stopped_without_next_write(env, accepted, before, code="PERMISSION_DENIED")
    assert permission.EDIT_SCENE.value in terminal["error"]["context"]["missing_permissions"]


@pytest.mark.parametrize("change", ["disable", "replace", "revoke_extra_permission"])
def test_live_turn_provider_cannot_retain_only_the_core_turn_authority(scene_jobs, change):
    env = scene_jobs
    original = domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)

    def invalidate():
        if change == "disable":
            env.registry.disable_toolset("simulation")
        elif change == "replace":
            env.registry._tools[original.name] = replace(original, handler=lambda *_: None)
        else:
            env.grants[env.permissions_module.Permission.EDIT_ANIMATION.value] = False

    env.provider_hook = invalidate
    code = "TOOLSET_DISABLED" if change == "disable" else "PERMISSION_DENIED" if change == "revoke_extra_permission" else None
    stopped_without_next_write(env, accepted, before, code=code)
    assert env.provider_hook is None


@pytest.mark.parametrize("change", ["disable", "replace"])
def test_original_domain_is_rechecked_at_driver_final_gate_after_read(scene_jobs, change):
    env = scene_jobs
    original = domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)

    def invalidate(_context):
        if change == "disable":
            env.registry.disable_toolset("simulation")
        else:
            env.registry._tools[original.name] = replace(original, handler=lambda *_: None)

    env.advance_hook = invalidate
    stopped_without_next_write(env, accepted, before,
                               code="TOOLSET_DISABLED" if change == "disable" else None)


@pytest.mark.parametrize("change", ["disable", "replace"])
def test_starter_authority_lost_inside_native_before_push_stops_role_adoption_and_later_stamps(scene_jobs, change):
    env = scene_jobs
    original = domain_start(env)
    accepted = env.start()
    frames = len(env.stack.frames)

    def invalidate():
        if change == "disable":
            env.registry.disable_toolset("simulation")
        else:
            env.registry._tools[original.name] = replace(original, handler=lambda *_: None)

    env.push_hook = invalidate
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    assert terminal["error"]["code"] == ("TOOLSET_DISABLED" if change == "disable" else "NOT_IMPLEMENTED")
    assert len(env.stack.frames) == frames+1 and env.advances == []
    assert terminal["checkpoint"]["native_snapshots_completed"] == 1
    assert terminal["checkpoint"]["marker_writes_completed"] == 1
    assert not terminal["checkpoint"]["before_verified"] and not terminal["checkpoint"]["after_verified"]
    assert env.events.count("authenticated_push") == 0
    before = snapshot(env)
    assert not env.manager.tick() and snapshot(env) == before


@pytest.mark.parametrize("at", ["factory", "provider"])
def test_starter_replacement_during_admission_never_becomes_accepted_authority(scene_jobs, at):
    env = scene_jobs

    def factory(context, params):
        driver = env.driver_type(context, params)
        if at == "factory":
            original = env.start_spec
            env.registry._tools[original.name] = replace(original, toolset="core", permissions=frozenset())
        return driver

    original = domain_start(env, driver_factory=factory)
    if at == "provider":
        env.provider_hook = lambda: env.registry._tools.__setitem__(
            original.name, replace(original, toolset="core", permissions=frozenset()))
    before = snapshot(env)
    response = env.executor.execute_request(env.protocol.Request(
        "changed-domain-start", original.name, {"steps": 1}, _lifecycle=env.lifecycle.RequestLifetime.local()))
    assert not response.ok and snapshot(env) == before
    assert env.manager.active is None and env.manager.reservations.owner is None
    assert env.checkpoints._owned_claim is None and not env.checkpoints._owned_pending


def test_unchanged_noncore_starter_completes_with_original_and_driver_permissions(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start(steps=1)
    for _ in range(8):
        if not env.manager.tick():
            break
    terminal = accepted.job.summary()
    assert terminal["state"] == "SUCCEEDED" and terminal["result"] == {"value": 1}
    assert env.advances == [(1, 1)] and terminal["checkpoint"]["after_verified"]


@pytest.mark.parametrize("route", ["context", "permissions", "prepare", "snapshot", "is_allowed"])
@pytest.mark.parametrize("stop", ["revoke_extra", "cancel"])
def test_late_subset_permission_read_cannot_drop_starter_grants_or_owned_stop(scene_jobs, route, stop):
    env = scene_jobs
    domain_start(env)
    permission = env.permissions_module.Permission
    subset = env.registry.register("fixture.simulation_subset", lambda *_: None, toolset="simulation",
                                   permissions=(permission.EDIT_SCENE,), modifies=True)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)
    observations = []

    def narrow_read(context):
        def invalidate():
            if stop == "revoke_extra":
                env.grants[permission.EDIT_ANIMATION.value] = False
            else:
                env.manager.cancel(accepted.job.job_id)

        env.provider_hook = invalidate
        count = env.provider_calls
        try:
            if route == "context":
                context.require(permission.EDIT_SCENE)
            elif route == "permissions":
                context.permissions.require((permission.EDIT_SCENE,))
            elif route == "prepare":
                context.registry.prepare(subset.name, context)
            elif route == "snapshot":
                context.permissions.snapshot()
            else:
                context.permissions.is_allowed(permission.EDIT_SCENE)
        finally:
            observations.append(env.provider_calls-count)

    env.advance_hook = narrow_read
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert observations == [1] and env.provider_hook is None
    assert terminal["state"] == ("FAILED" if stop == "revoke_extra" else "CANCELLED")
    assert terminal["result"] is None
    assert terminal["error"]["code"] == ("PERMISSION_DENIED" if stop == "revoke_extra" else "TIMEOUT")
    if stop == "revoke_extra":
        assert permission.EDIT_ANIMATION.value in terminal["error"]["context"]["missing_permissions"]
    else:
        assert terminal["error"]["context"]["reason"] == "explicit cancellation"
    assert snapshot(env) == before and terminal["checkpoint"]["native_snapshots_completed"] == 1
    assert terminal["checkpoint"]["before_verified"] and not terminal["checkpoint"]["after_verified"]
    assert env.manager.recovery_ledger[accepted.job.job_id]["checkpoint"] == terminal["checkpoint"]


@pytest.mark.parametrize("inspection_granted", [False, True])
def test_nested_readonly_permission_scope_delegates_then_outer_turn_rechecks_full_union(scene_jobs, inspection_granted):
    env = scene_jobs
    domain_start(env)
    permission = env.permissions_module.Permission
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)
    observed = []

    def read_nested(context):
        env.grants[permission.EDIT_ANIMATION.value] = False
        env.grants[permission.INSPECT_SCENE.value] = inspection_granted
        try:
            result = context.registry.dispatch("jobs.inspect", {"job_id": accepted.job.job_id}, context)
        except env.errors.BridgeError as error:
            assert not inspection_granted and error.code == "PERMISSION_DENIED"
            assert error.context["missing_permissions"] == [permission.INSPECT_SCENE.value]
            observed.append("readonly_denied_own_grant")
        else:
            assert inspection_granted and result["job_id"] == accepted.job.job_id and not result["terminal"]
            observed.append("readonly_returned")
        context.require(permission.EDIT_SCENE)

    env.advance_hook = read_nested
    terminal = stopped_without_next_write(env, accepted, before, code="PERMISSION_DENIED")
    assert observed == (["readonly_returned"] if inspection_granted else ["readonly_denied_own_grant"])
    assert terminal["error"]["context"]["missing_permissions"] == [permission.EDIT_ANIMATION.value]


def test_fresh_readonly_control_does_not_inherit_scene_turn_required_grants(scene_jobs):
    env = scene_jobs
    domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    env.grants[env.permissions_module.Permission.EDIT_ANIMATION.value] = False
    before = snapshot(env)
    result = env.executor.dispatch("jobs.inspect", {"job_id": accepted.job.job_id})
    assert result["job_id"] == accepted.job.job_id and not result["terminal"]
    assert snapshot(env) == before
    stopped_without_next_write(env, accepted, before, code="PERMISSION_DENIED")


@pytest.mark.parametrize("read", ["snapshot", "is_allowed"])
def test_nested_readonly_permission_queries_report_original_grants_without_turn_union(scene_jobs, read):
    env = scene_jobs
    permission = env.permissions_module.Permission

    def status(context, _params):
        if read == "snapshot":
            allowed = context.permissions.snapshot()[permission.EDIT_ANIMATION.value]
        else:
            allowed = context.permissions.is_allowed(permission.EDIT_ANIMATION)
        return {"original_extra_grant": allowed}

    original = env.registry.get("bridge.status")
    env.registry._tools[original.name] = replace(original, handler=status)
    domain_start(env)
    accepted = env.start()
    assert env.manager.tick()
    before = snapshot(env)
    observed = []

    def read_control(context):
        env.grants[permission.EDIT_ANIMATION.value] = False
        result = context.registry.dispatch("bridge.status", {}, context)
        assert result == {"original_extra_grant": False}
        observed.append(result)
        context.require(permission.EDIT_SCENE)

    env.advance_hook = read_control
    terminal = stopped_without_next_write(env, accepted, before, code="PERMISSION_DENIED")
    assert observed == [{"original_extra_grant": False}]
    assert terminal["error"]["context"]["missing_permissions"] == [permission.EDIT_ANIMATION.value]
