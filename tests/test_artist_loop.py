"""Runtime artist references/previews, protected consumers and stale corrections."""
from __future__ import annotations

import importlib
import json
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
import test_object_rna_mutation as rna_fixtures
from test_object_rna_mutation import RNA, Components

rna_env = rna_fixtures.env


@pytest.fixture
def loop(rna_env, addon_package, monkeypatch):
    env = rna_env
    module = importlib.import_module(f"{addon_package}.tools.artist_loop")
    plans = importlib.import_module(f"{addon_package}.tools.task_plan")
    data = importlib.import_module(f"{addon_package}.task_plans")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    env.context.state = state
    env.grants.update(INSPECT_SCENE=True, EDIT_SCENE=True)
    scene = env.bpy.context.scene
    scene.session_uid, scene.objects = 100, env.bpy.data.objects
    env.bpy.context.view_layer.update = lambda: None
    monkeypatch.setattr(module, "require_blender", lambda: env.bpy)
    monkeypatch.setattr(plans, "require_blender", lambda: env.bpy)
    monkeypatch.setattr(module, "pre_closure", lambda _bpy: None)
    monkeypatch.setattr(module, "require_profile", lambda _bpy, _objects: None)
    protected = RNA(**vars(env.obj))
    protected.name, protected.session_uid = "Protected", 2
    protected.modifiers, protected.constraints = Components(), Components()
    protected.user_of_id = lambda target: 0
    scene.objects.append(protected)
    plans.register_tools(env.context.registry)

    def transform(context, params):
        target = scene.objects.get(params["object_name"])
        guard = env.module.Boundary(env.bpy, context, "transform.set", target, transform=True)
        assignments = tuple(env.rna.RNAAssignment(field, tuple(params[field])) for field in ("location", "scale") if field in params)
        guard.apply(target, assignments)
        return {"changed": True, "affected_objects": guard.affected}
    spec = env.context.registry.get("transform.set")
    env.context.registry._tools["transform.set"] = replace(spec, handler=transform, protected_scope_resolver=module.prepare_transform_scope)
    env.loop, env.plans, env.data, env.protected = module, plans, data, protected
    plans.set_plan(env.context, {"goal": "Revise the working prop while preserving Protected",
                               "steps": [{"id": "revise", "description": "Preview and revise prop placement"}],
                               "protected_objects": ["Protected"]})
    return env


def arm(loop):
    return loop.loop.enforce_plan(loop.context, {"enabled": True, "expected_revision": 1})


def reference(loop, **params):
    return loop.loop.resolve_reference(loop.context, params or {"source": "selection"})["reference_id"]


def preview(loop, **params):
    return loop.loop.preview_transform(loop.context, {"reference_id": reference(loop), "expected_revision": 1,
                                                      "location": [1., 2., 3.], **params})


def test_opt_in_protection_is_runtime_only_and_explicitly_reversible(loop):
    before = loop.data.get_task_plans(loop.context.state)
    assert not before.inspect()["protected_scope_enforced"]
    enabled = arm(loop)
    assert enabled["protected_scope_enforced"] and not enabled["host_python_sandbox"]
    raw = loop.data.encode_saved(before.require_plan())
    assert set(json.loads(raw)) == {"schema_version", "plan_id", "revision", "goal", "steps", "protected_objects"}
    for operation, params in ((loop.plans.clear_plan, {"expected_revision": 1}),
                              (loop.plans.load_plan, {"expected_revision": 1})):
        with pytest.raises(Exception, match="Explicitly disable"):
            operation(loop.context, params)
    with pytest.raises(Exception, match="Explicitly disable"):
        before.replace({"goal": "replacement"}, before.scope, 1)
    disabled = loop.loop.enforce_plan(loop.context, {"enabled": False, "expected_revision": 1})
    assert not disabled["protected_scope_enforced"]
    loop.plans.clear_plan(loop.context, {"expected_revision": 1})
    loop.context.state.reset()
    assert not before.inspect()["protected_scope_enforced"] and not before.references and not before.previews


@pytest.mark.parametrize("enabled", [None, 1, "true", [], {}])
def test_enforcement_requires_explicit_boolean(loop, enabled):
    with pytest.raises(Exception, match="explicitly"):
        loop.loop.enforce_plan(loop.context, {"enabled": enabled, "expected_revision": 1})


@pytest.mark.parametrize("fault", ["active_job", "protected_identity", "scene_identity", "missing_protected"])
def test_arming_rejects_stale_or_live_async_scope(loop, fault):
    if fault == "active_job":
        loop.context.jobs = NS(active=object())
    elif fault == "protected_identity":
        loop.protected.session_uid = 99
    elif fault == "scene_identity":
        loop.bpy.context.scene.session_uid = 99
    else:
        loop.bpy.context.scene.objects.remove(loop.protected)
    with pytest.raises(loop.module.BridgeError):
        arm(loop)
    assert not loop.data.get_task_plans(loop.context.state).inspect()["protected_scope_enforced"]


def test_plan_corrections_preserve_generation_and_protected_constraints(loop):
    arm(loop)
    token = reference(loop)
    stamp = loop.loop.policy_stamp(loop.context)
    loop.plans.update_plan(loop.context, {"step_id": "revise", "note": "Shift right after visual comparison", "expected_revision": 1})
    assert loop.loop.policy_stamp(loop.context) == stamp
    assert loop.loop._reference(loop.context, loop.bpy, token) == (loop.obj,)
    assert loop.data.get_task_plans(loop.context.state).require_plan()["protected_objects"] == ["Protected"]


def test_inspection_and_preview_do_not_require_or_grant_edit_permission(loop):
    arm(loop)
    loop.grants["TRANSFORM_OBJECTS"] = False
    result = preview(loop)
    assert loop.obj.location == (0., 0., 0.)
    assert result["changes"] == [{"field": "location", "before": (0., 0., 0.), "requested": (1., 2., 3.)}]
    assert result["affected_objects"] == ["Owner"] and result["scope_complete"]
    assert not result["authority_granted"] and not result["scene_edited"]
    with pytest.raises(Exception, match="permission"):
        loop.loop.apply_preview(loop.context, {"preview_id": result["preview_id"], "expected_revision": 1})
    assert result["preview_id"] in loop.data.get_task_plans(loop.context.state).previews


@pytest.mark.parametrize("fault", ["selection", "active", "mode", "frame", "object_identity", "view_layer", "project"])
def test_reference_context_is_exact_and_never_silently_rebound(loop, fault):
    token = reference(loop)
    if fault == "selection":
        loop.bpy.context.selected_objects = []
    elif fault == "active":
        loop.bpy.context.view_layer.objects.active = loop.protected
    elif fault == "mode":
        loop.bpy.context.mode = "EDIT_MESH"
    elif fault == "frame":
        loop.bpy.context.scene.frame_current += 1
    elif fault == "object_identity":
        loop.obj.session_uid = 99
    elif fault == "view_layer":
        loop.bpy.context.view_layer = NS(objects=loop.bpy.data.objects)
    else:
        loop.bpy.data.filepath = "/new project.blend"
    with pytest.raises(Exception, match="Reference context"):
        loop.loop._reference(loop.context, loop.bpy, token)


def test_reference_resolution_is_bounded_and_never_guesses(loop):
    for params in ({"source": "this"}, {"source": "objects", "object_names": ["owner"]},
                   {"source": "selection", "object_names": ["Owner"]},
                   {"source": "objects", "object_names": ["Owner", "Owner"]}):
        with pytest.raises(loop.module.BridgeError):
            reference(loop, **params)
    first = reference(loop)
    for _ in range(loop.loop.MAX_REFERENCES):
        reference(loop)
    with pytest.raises(Exception, match="evicted"):
        loop.loop._reference(loop.context, loop.bpy, first)


def test_protected_direct_and_transitive_consumer_scopes_reject_before_any_write(loop):
    arm(loop)
    for transitive in (False, True):
        loop.users[loop.obj] = {loop.protected}
        loop.protected.user_of_id = lambda target: int(target is loop.obj)
        if transitive:
            middle = RNA(**vars(loop.obj))
            middle.name, middle.session_uid = "Middle", 3
            middle.modifiers, middle.constraints = Components(), Components()
            middle.user_of_id = lambda target: int(target is loop.obj)
            loop.bpy.data.objects.append(middle)
            loop.users[loop.obj] = {middle}
            loop.users[middle] = {loop.protected}
            loop.protected.user_of_id = lambda target, middle=middle: int(target is middle)
        with pytest.raises(Exception, match="intersects protected"):
            preview(loop)
        assert loop.obj.location == loop.protected.location == (0., 0., 0.)


def test_outbound_protected_reference_is_not_an_affected_consumer(loop):
    arm(loop)
    # The working prop reads Protected. Incoming user_map edges from Owner do
    # not imply editing its source, so the normal safe preview remains possible.
    loop.users[loop.protected] = {loop.obj}
    loop.obj.user_of_id = lambda target: int(target is loop.protected)
    result = preview(loop)
    assert result["affected_objects"] == ["Owner"]


@pytest.mark.parametrize("fault", ["channels", "consumers", "identity", "policy"])
def test_stale_preview_refuses_manual_changes_before_consumption(loop, fault):
    arm(loop)
    result = preview(loop)
    if fault == "channels":
        loop.obj.location = (9., 8., 7.)
    elif fault == "consumers":
        stranger = RNA(name="Unknown", bl_rna=NS(identifier="World"), user_of_id=lambda target: 1)
        loop.users[loop.obj].add(stranger)
    elif fault == "identity":
        loop.obj.session_uid += 1
    else:
        loop.loop.enforce_plan(loop.context, {"enabled": False, "expected_revision": 1})
    with pytest.raises(loop.module.BridgeError):
        loop.loop.apply_preview(loop.context, {"preview_id": result["preview_id"], "expected_revision": 1})
    assert loop.obj.location == ((9., 8., 7.) if fault == "channels" else (0., 0., 0.))


def test_exact_preview_applies_once_and_reports_actual_scope(loop):
    arm(loop)
    result = preview(loop)
    applied = loop.loop.apply_preview(loop.context, {"preview_id": result["preview_id"], "expected_revision": 1})
    assert applied["preview_consumed"] and applied["affected_objects"] == ["Owner"]
    assert loop.obj.location == (1., 2., 3.) and loop.protected.location == (0., 0., 0.)
    assert loop.data.get_task_plans(loop.context.state).executing_mutators == 0
    with pytest.raises(Exception, match="consumed"):
        loop.loop.apply_preview(loop.context, {"preview_id": result["preview_id"], "expected_revision": 1})


def test_generation_change_prevents_compensation_or_further_owned_writes(loop):
    arm(loop)
    stamp = loop.loop.policy_stamp(loop.context)
    loop.loop.enforce_plan(loop.context, {"enabled": False, "expected_revision": 1})
    with pytest.raises(Exception, match="compensation"):
        loop.loop.check_affected(loop.context, loop.bpy, (loop.obj,), stamp=stamp)


def test_unreviewed_mutators_fail_closed_only_when_armed(loop):
    loop.loop.require_reviewed_mutator(loop.context, "fixture.unknown", reviewed=False)
    arm(loop)
    with pytest.raises(Exception, match="no reviewed"):
        loop.loop.require_reviewed_mutator(loop.context, "fixture.unknown", reviewed=False)
    loop.loop.require_reviewed_mutator(loop.context, "transform.set", reviewed=True)


def test_dispatch_and_executor_refuse_unknown_mutator_before_checkpoint_or_handler(loop, addon_package):
    arm(loop)
    calls = []
    loop.context.registry.register("fixture.unknown", lambda *_: calls.append("handler"), modifies=True)
    with pytest.raises(loop.module.BridgeError, match="no reviewed"):
        loop.context.registry.dispatch("fixture.unknown", {}, loop.context)
    executor_module = importlib.import_module(f"{addon_package}.executor")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    executor = executor_module.MainThreadExecutor(command_queue=queue.CommandQueue(), registry=loop.context.registry,
        state=loop.context.state, permissions=loop.context.permissions,
        checkpoints=NS(before_modification=lambda _: calls.append("checkpoint"), after_modification=lambda _: True))
    response = executor.execute_request(protocol.Request(id="protected", method="fixture.unknown"))
    assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED" and not calls


def test_protected_transform_is_denied_before_executor_checkpoint(loop, addon_package):
    arm(loop)
    calls = []
    executor_module = importlib.import_module(f"{addon_package}.executor")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    executor = executor_module.MainThreadExecutor(command_queue=queue.CommandQueue(), registry=loop.context.registry,
        state=loop.context.state, permissions=loop.context.permissions,
        checkpoints=NS(before_modification=lambda _: calls.append("checkpoint"), after_modification=lambda _: True))
    response = executor.execute_request(protocol.Request(id="protected", method="transform.set", params={"object_name": "Protected", "location": [2., 3., 4.]}))
    assert not response.ok and response.error["context"]["affected_protected_objects"] == ["Protected"]
    assert not calls and loop.protected.location == (0., 0., 0.)


def test_final_nested_dispatch_provider_cannot_replace_preview_baseline(loop):
    arm(loop)
    result = preview(loop)
    fired = []
    def provider():
        if loop.data.get_task_plans(loop.context.state).applying_preview is not None and not fired:
            fired.append(True)
            loop.obj.location = (9., 8., 7.)
    loop.provider[0] = provider
    with pytest.raises(loop.module.BridgeError, match="authored pre-state"):
        loop.loop.apply_preview(loop.context, {"preview_id": result["preview_id"], "expected_revision": 1})
    assert fired and loop.obj.location == (9., 8., 7.)
    assert loop.data.get_task_plans(loop.context.state).applying_preview is None


@pytest.mark.parametrize("fault", ["new_protected_consumer", "disable", "stop", "disconnect"])
def test_every_field_and_compensation_rechecks_scope_policy_and_lifetime(loop, addon_package, fault):
    arm(loop)
    result = preview(loop, scale=[2., 2., 2.])
    lifetime = importlib.import_module(f"{addon_package}.request_lifecycle")
    connection = lifetime.ConnectionLifetime()
    loop.context.request_lifecycle = lifetime.RequestLifetime.local()
    loop.context.request_lifecycle.connection = connection
    fired = []
    def provider():
        if loop.obj.location != (1., 2., 3.) or fired:
            return
        fired.append(True)
        if fault == "new_protected_consumer":
            loop.users[loop.obj].add(loop.protected)
            loop.protected.user_of_id = lambda target: int(target is loop.obj)
        elif fault == "disable":
            loop.loop.enforce_plan(loop.context, {"enabled": False, "expected_revision": 1})
        elif fault == "stop":
            loop.context.state.set_emergency_stopped(True)
        else:
            connection.disconnected.set()
    loop.provider[0] = provider
    with pytest.raises(loop.module.BridgeError) as error:
        loop.loop.apply_preview(loop.context, {"preview_id": result["preview_id"], "expected_revision": 1})
    assert fired and loop.obj.location == (1., 2., 3.) and loop.obj.scale == (1., 1., 1.)
    assert not error.value.context["rollback_verified"] and error.value.context["possible_mutation"]
    assert loop.protected.location == (0., 0., 0.)


def test_local_undo_cannot_implicitly_bypass_protection(loop):
    arm(loop)
    calls = []
    loop.context.registry.register("checkpoint.undo_last", lambda *_: calls.append("undo"), modifies=True, remote=False)
    with pytest.raises(loop.module.BridgeError, match="no reviewed"):
        loop.context.registry.prepare("checkpoint.undo_last", loop.context, allow_recovery=True)
    assert not calls
    # Explicit disable remains possible under emergency stop for local recovery.
    loop.context.state.set_emergency_stopped(True)
    result = loop.loop.enforce_plan(loop.context, {"enabled": False, "expected_revision": 1})
    assert not result["protected_scope_enforced"] and result["enforcement_changed_explicitly"]


def test_batch_internal_preflight_resolves_protected_affected_scope(loop, addon_package):
    arm(loop)
    batch = importlib.import_module(f"{addon_package}.tools.batch")
    with pytest.raises(loop.module.BridgeError, match="intersects protected"):
        batch.batch_plan(loop.context, {"steps": [{"method": "transform.set", "params": {"object_name": "Protected", "location": [1., 0., 0.]}}]})


def test_incomplete_registered_resolver_never_enters_handler(loop):
    arm(loop)
    calls = []
    loop.context.registry.register("fixture.incomplete", lambda *_: calls.append("handler"), modifies=True,
                                   protected_scope_resolver=lambda *_: {"scope_complete": False})
    with pytest.raises(loop.module.BridgeError, match="incomplete"):
        loop.context.registry.dispatch("fixture.incomplete", {}, loop.context)
    assert not calls


def test_bundled_runtime_bone_selection_ui_is_excluded_before_snapshot_getter(loop):
    class UIGetter(RNA):
        @property
        def active_selection_set(self):
            raise AssertionError("Artist snapshots must not invoke the excluded UI getter")
    obj = UIGetter(**vars(loop.obj))
    fields = obj.bl_rna.properties.copy()
    fields["active_selection_set"] = NS(identifier="active_selection_set", type="INT", is_readonly=False)
    obj.bl_rna = NS(identifier="Object", properties=type(loop.obj.bl_rna.properties)(fields))
    loop.module._object_state(obj, artist_profile=True)
    with pytest.raises(AssertionError, match="excluded UI getter"):
        loop.module._object_state(obj)


def test_synchronous_unknown_mutator_cannot_enable_protection_mid_handler(loop):
    calls = []
    def handler(context, _params):
        loop.loop.enforce_plan(context, {"enabled": True, "expected_revision": 1})
        calls.append("unsafe edit")
    loop.context.registry.register("fixture.unarmed_writer", handler, modifies=True)
    with pytest.raises(loop.module.BridgeError, match="inside another executing"):
        loop.context.registry.dispatch("fixture.unarmed_writer", {}, loop.context)
    store = loop.data.get_task_plans(loop.context.state)
    assert not calls and not store.inspect()["protected_scope_enforced"] and store.executing_mutators == 0
    assert arm(loop)["protected_scope_enforced"]


def test_direct_batch_cannot_arm_during_unreviewed_child_and_counter_unwinds(loop, addon_package):
    batch = importlib.import_module(f"{addon_package}.tools.batch")
    calls = []
    def handler(context, _params):
        loop.loop.enforce_plan(context, {"enabled": True, "expected_revision": 1})
        calls.append("unsafe edit")
    loop.context.registry.register("fixture.writer", handler, toolset="objects", modifies=True)
    loop.context.checkpoints = NS(before_modification=lambda _: False, after_modification=lambda _: False)
    with pytest.raises(loop.module.BridgeError, match="inside another executing"):
        batch.batch_execute(loop.context, {"steps": [{"method": "fixture.writer"}]})
    assert not calls and loop.data.get_task_plans(loop.context.state).executing_mutators == 0
    assert arm(loop)["protected_scope_enforced"]


def test_additive_review_metadata_preserves_existing_fields_and_defaults(loop):
    reviewed = loop.context.registry.get("transform.set").metadata(enabled=True)
    unreviewed = loop.context.registry.get("modifier.set").metadata(enabled=True)
    assert reviewed["protected_scope_reviewed"] is True and unreviewed["protected_scope_reviewed"] is False
    assert set(reviewed) == {"name", "toolset", "description", "required_permissions", "modifies", "enabled", "remote", "protected_scope_reviewed"}


def test_disabled_nested_transform_is_rejected_at_preview_preflight(loop):
    arm(loop)
    result = preview(loop)
    loop.context.registry.disable_toolset("objects")
    with pytest.raises(loop.module.BridgeError, match="transform toolset is disabled"):
        loop.context.registry.prepare_call("task.plan.apply_preview", {"preview_id": result["preview_id"], "expected_revision": 1}, loop.context)
    assert result["preview_id"] in loop.data.get_task_plans(loop.context.state).previews
    assert loop.obj.location == (0., 0., 0.)


def test_no_arbitrary_cancellation_provider_runs_after_final_inspection_permission(loop):
    permission_seen = []
    def provider():
        permission_seen.append(True)
    loop.provider[0] = provider
    def cancelled():
        if permission_seen:
            loop.grants["INSPECT_SCENE"] = False
            raise AssertionError("An arbitrary callback ran after the final permission snapshot")
    loop.context.check_cancelled = cancelled
    assert reference(loop)
    assert loop.grants["INSPECT_SCENE"]


def test_disconnection_during_final_preview_reader_prevents_token_publication(loop, addon_package, monkeypatch):
    arm(loop)
    lifetime = importlib.import_module(f"{addon_package}.request_lifecycle")
    connection = lifetime.ConnectionLifetime()
    loop.context.request_lifecycle = lifetime.RequestLifetime.local()
    loop.context.request_lifecycle.connection = connection
    original = loop.loop._profile
    def profile(boundary):
        result = original(boundary)
        connection.disconnected.set()
        return result
    monkeypatch.setattr(loop.loop, "_profile", profile)
    with pytest.raises(loop.module.BridgeError, match="disconnected"):
        preview(loop)
    assert not loop.data.get_task_plans(loop.context.state).previews
    assert loop.obj.location == (0., 0., 0.)


def test_disable_lifetime_revoked_by_last_permission_provider_retains_protection(loop, addon_package):
    arm(loop)
    lifetime = importlib.import_module(f"{addon_package}.request_lifecycle")
    connection = lifetime.ConnectionLifetime()
    loop.context.request_lifecycle = lifetime.RequestLifetime.local()
    loop.context.request_lifecycle.connection = connection
    loop.provider[0] = lambda: connection.disconnected.set()
    with pytest.raises(loop.module.BridgeError, match="disconnected"):
        loop.loop.enforce_plan(loop.context, {"enabled": False, "expected_revision": 1})
    assert loop.data.get_task_plans(loop.context.state).inspect()["protected_scope_enforced"]


@pytest.mark.parametrize("fault", ["cancel", "inspect_denied"])
def test_cancelled_or_denied_explicit_disable_retains_constraints_and_audit(loop, fault):
    arm(loop)
    store = loop.data.get_task_plans(loop.context.state)
    stamp = loop.loop.policy_stamp(loop.context)
    history = loop.context.state.history()
    if fault == "cancel":
        def cancel():
            raise loop.module.BridgeError("TIMEOUT", "caller cancelled")
        loop.context.check_cancelled = cancel
    else:
        loop.grants["INSPECT_SCENE"] = False
    with pytest.raises(loop.module.BridgeError):
        loop.loop.enforce_plan(loop.context, {"enabled": False, "expected_revision": 1})
    assert store.inspect()["protected_scope_enforced"] and loop.loop.policy_stamp(loop.context) == stamp
    assert loop.context.state.history() == history
