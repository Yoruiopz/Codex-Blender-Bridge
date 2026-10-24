"""Guarded batches must never adopt late edits as a fresh admission baseline."""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_authority import NativeStack


@pytest.fixture
def env(addon_package, monkeypatch):
    batch = importlib.import_module(f"{addon_package}.tools.batch")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    checkpoint_module = importlib.import_module(f"{addon_package}.checkpoints")
    events, factories, handlers, bindings = [], [], [], []
    state = {"owned": 0, "protected": "original"}
    grants = {permission.value: True for permission in permissions.Permission}
    provider_hook, handler_hook, prepare_phase = [None], [None], [None]
    registry = registry_module.ToolRegistry(enabled_toolsets=("batch", "scene_edit"))
    batch.register_tools(registry)

    def provider():
        events.append(("provider", state["owned"], state["protected"]))
        if provider_hook[0] is not None:
            provider_hook[0]()
        return dict(grants)

    stack = NativeStack()
    monkeypatch.setattr(checkpoint_module, "require_blender", lambda: stack.bpy)

    class NativeCheckpoints(checkpoint_module.CheckpointManager):
        """Observe real mocked native pushes without manufacturing completions."""

        def __init__(self):
            super().__init__()
            self.before_hook = self.after_hook = None
            self.before_pushes = self.after_pushes = 0

        def before_modification(self, label, **kwargs):
            if self.before_hook is not None:
                self.before_hook()
            return super().before_modification(label, **kwargs)

        def after_modification(self, label, **kwargs):
            if self.after_hook is not None:
                self.after_hook()
            return super().after_modification(label, **kwargs)

    checkpoints = NativeCheckpoints()
    native_push = stack.bpy.ops.ed.undo_push

    def traced_push(**kwargs):
        result = native_push(**kwargs)
        if "FINISHED" in result:
            message = kwargs["message"]
            if message.startswith("Codex Before: "):
                checkpoints.before_pushes += 1
                events.append(("native_before", message.removeprefix("Codex Before: ")))
            elif message.startswith("Codex After: "):
                checkpoints.after_pushes += 1
                events.append(("native_after", message.removeprefix("Codex After: ")))
        return result

    monkeypatch.setattr(stack.bpy.ops.ed, "undo_push", traced_push)
    context = registry_module.ToolContext(state_module.BridgeState(), permissions.PermissionManager(provider),
                                          registry, checkpoints)
    prepare_call = registry.prepare_call

    def tracked_prepare(method, params, bound_context, **kwargs):
        previous = prepare_phase[0]
        prepare_phase[0] = method
        try:
            return prepare_call(method, params, bound_context, **kwargs)
        finally:
            prepare_phase[0] = previous

    registry.prepare_call = tracked_prepare

    class Guard:
        def __init__(self, name, params):
            self.name, self.params = name, params
            self.expected = dict(state)

        def __call__(self):
            # Real domain admission callbacks resolve live grants before the
            # frozen comparison, then finish with the provider-free gate.
            context.require(permissions.Permission.EDIT_SCENE)
            events.append(("guard", self.name, state["owned"], state["protected"]))
            self.check_after_read()

        def check_after_read(self):
            if state != self.expected:
                raise errors.BridgeError("OPERATION_FAILED", "Admitted closure changed; no fresh baseline is allowed.",
                                         {"scope_stale": True, "verification_required": True})
            registry_module.check_final_mutation(context, self.name)

    def register(name, *, guarded=True, modifies=True):
        def factory(bound_context, params):
            assert bound_context is context
            events.append(("factory", name, state["owned"], state["protected"]))
            guard = Guard(name, params)
            factories.append(guard)
            return guard

        def handler(bound_context, params):
            assert bound_context is context
            binding = context.checkpoint_admission
            if guarded and modifies:
                assert binding is not None and binding.matches(registry.get(name), params, context)
                bindings.append(binding)
            events.append(("handler", name))
            handlers.append(name)
            if modifies:
                delta = params.get("delta", 1)
                state["owned"] += delta
                if guarded:
                    # This models a domain's measured exact owned effect. It
                    # advances no protected field and never adopts live state.
                    binding.callback.expected["owned"] += delta
            if handler_hook[0] is not None:
                handler_hook[0](name)
            return {"changed": modifies, "affected_objects": [name] if modifies else []}

        kwargs = {"checkpoint_admission_factory": factory} if guarded and modifies else {}
        return registry.register(name, handler, toolset="scene_edit", modifies=modifies,
                                 checkpoint_batch_reviewed=guarded,
                                 permissions=(permissions.Permission.EDIT_SCENE,) if modifies else (), **kwargs)

    register("scene.guarded_first")
    register("scene.guarded_second")
    register("scene.legacy", guarded=False)
    register("scene.inspect", guarded=False, modifies=False)
    return NS(batch=batch, registry_module=registry_module, errors=errors, registry=registry, context=context,
              state=state, grants=grants, provider_hook=provider_hook, handler_hook=handler_hook,
              prepare_phase=prepare_phase,
              factories=factories, handlers=handlers, bindings=bindings, events=events,
              checkpoints=checkpoints, register=register)


def steps(*names):
    return [{"method": name, "params": {"delta": index + 1}} for index, name in enumerate(names)]


def execute(env, names=("scene.guarded_first", "scene.guarded_second")):
    return env.batch.batch_execute(env.context, {"steps": steps(*names), "label": "Guarded logical edit"})


def test_all_guarded_success_keeps_one_checkpoint_and_latest_guard_finalization(env):
    result = execute(env)
    assert result["completed_steps"] == 2
    assert result["operation"] == {"undo_boundary_created": True, "undo_boundary_finalized": True, "scope": "logical_batch"}
    assert env.state == {"owned": 3, "protected": "original"}
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 1
    assert [guard.name for guard in env.factories] == env.handlers == ["scene.guarded_first", "scene.guarded_second"]
    assert env.factories[0].expected["owned"] == 1 and env.factories[1].expected["owned"] == 3
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None
    assert all(not binding.active for binding in env.bindings)
    assert env.registry.executing_mutators == 0


def test_reviewed_transition_retires_predecessor_without_adopting_later_owned_state(env):
    observed = []

    def handler(name):
        if name == "scene.guarded_second":
            first, second = env.bindings
            observed.append((first.active, second.active, second.enclosing))

    env.handler_hook[0] = handler
    result = execute(env)
    assert result["completed_steps"] == 2
    assert observed == [(False, True, None)]
    assert env.factories[0].expected == {"owned": 1, "protected": "original"}
    assert env.factories[1].expected == {"owned": 3, "protected": "original"}
    with pytest.raises(env.errors.BridgeError) as caught:
        env.bindings[0]()
    assert caught.value.context["checkpoint_admission_valid"] is False
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 1


@pytest.mark.parametrize("entry", ("plan", "direct", "executor"))
@pytest.mark.parametrize("position", (0, 1))
def test_unreviewed_guarded_batch_is_refused_before_any_child_capture_or_write(env, entry, position):
    from dataclasses import replace
    names = ("scene.guarded_first", "scene.guarded_second")
    spec = env.registry.get(names[position])
    env.registry._tools[spec.name] = replace(spec, checkpoint_batch_reviewed=False)
    params = {"steps": steps(*names)}
    if entry == "executor":
        protocol = importlib.import_module(f"{env.registry_module.__package__}.protocol")
        response = outer_executor(env).execute_request(protocol.Request("unreviewed-batch", "batch.execute", params))
        assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
        details = response.error["context"]
    else:
        with pytest.raises(env.errors.BridgeError) as caught:
            env.registry.dispatch("batch.plan" if entry == "plan" else "batch.execute", params, env.context)
        assert caught.value.code == "NOT_IMPLEMENTED"
        details = caught.value.context
    assert details["execution_started"] is False
    assert details["checkpoint_batch_composition_reviewed"] is False
    assert details["step_index"] == position
    assert env.handlers == env.factories == []
    assert env.state == {"owned": 0, "protected": "original"}
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None
    assert env.context.checkpoint_finalization_owner is None


@pytest.mark.parametrize("method", ("batch.plan", "batch.execute"))
@pytest.mark.parametrize("entry", ("direct_provider", "executor_provider", "executor_callback"))
@pytest.mark.parametrize("replacement", ("review_opt_in", "equal_guarded", "unknown_registration"))
@pytest.mark.parametrize("position", (0, 1))
def test_initial_entry_cannot_replace_child_identity_or_promote_review_status(
    env, method, entry, replacement, position,
):
    from dataclasses import replace
    permission = importlib.import_module(f"{env.registry_module.__package__}.permissions")
    names = ["scene.guarded_first", "scene.guarded_second"]
    initial = env.registry.get(names[position])
    if replacement == "review_opt_in":
        initial = replace(initial, checkpoint_batch_reviewed=False)
        env.registry._tools[initial.name] = initial
    elif replacement == "unknown_registration":
        names[position] = "scene.future"
    params, fired = {"steps": steps(*names)}, []
    # Batch itself normally has no required permission provider. Give this
    # synthetic outer spec one so provider entry and cancellation entry can
    # independently exercise the same pre-callback identity capture.
    outer = env.registry.get(method)
    env.registry._tools[method] = replace(outer, permissions=frozenset({permission.Permission.EDIT_SCENE}))

    def change():
        if fired:
            return
        fired.append(True)
        if replacement == "unknown_registration":
            updated = replace(initial, name=names[position])
        else:
            updated = replace(initial, checkpoint_batch_reviewed=True)
            if replacement == "equal_guarded":
                assert updated == initial and updated is not initial
        env.registry._tools[names[position]] = updated

    if entry != "executor_callback":
        env.provider_hook[0] = change
    if entry == "direct_provider":
        with pytest.raises(env.errors.BridgeError) as caught:
            env.registry.dispatch(method, params, env.context)
        assert caught.value.code == "NOT_IMPLEMENTED"
        details = caught.value.context
    else:
        protocol = importlib.import_module(f"{env.registry_module.__package__}.protocol")
        response = outer_executor(env).execute_request(protocol.Request("replace-child-at-entry", method, params),
            check_cancelled=change if entry == "executor_callback" else None)
        assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
        details = response.error["context"]
    assert fired == [True] and details["checkpoint_parameters_unchanged"] is False
    assert env.handlers == env.factories == []
    assert env.state == {"owned": 0, "protected": "original"}
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None
    assert env.context.checkpoint_finalization_owner is None


@pytest.mark.parametrize("change", ("future_params", "finalization_owner"))
def test_transition_provider_cannot_change_whole_plan_before_next_capture(env, change):
    params = {"steps": steps("scene.guarded_first", "scene.guarded_second")}
    second_preflight, changed = [False], []

    def provider():
        if len(env.handlers) != 1:
            return
        if env.prepare_phase[0] == "scene.guarded_second":
            second_preflight[0] = True
        elif second_preflight[0] and not changed:
            changed.append(True)
            if change == "future_params":
                params["steps"][1]["params"]["delta"] = 99
            else:
                env.context.checkpoint_finalization_owner = object()

    env.provider_hook[0] = provider
    with pytest.raises(env.errors.BridgeError) as caught:
        env.batch.batch_execute(env.context, params)
    assert changed == [True] and caught.value.code == "NOT_IMPLEMENTED"
    assert env.handlers == ["scene.guarded_first"] and len(env.factories) == 1
    assert env.state == {"owned": 1, "protected": "original"}
    assert env.checkpoints.before_pushes == 1 and env.checkpoints.after_pushes == 0
    assert caught.value.context["checkpoint_finalization_refused"]["primary_error_preserved"] is True
    assert env.context.checkpoint_admission is None


@pytest.mark.parametrize("when", ["first_preflight", "between_steps"])
@pytest.mark.parametrize("change", ["future_value", "append_step"])
def test_entire_guarded_plan_is_frozen_before_any_child_provider(env, when, change):
    params = {"steps": steps("scene.guarded_first", "scene.guarded_second")}
    injected = []
    def provider():
        phase = env.prepare_phase[0]
        eligible = ((when == "first_preflight" and phase == "scene.guarded_first")
                    or (when == "between_steps" and len(env.handlers) == 1 and phase == "scene.guarded_second"))
        if eligible and not injected:
            injected.append(True)
            if change == "future_value":
                params["steps"][1]["params"]["delta"] = 99
            else:
                params["steps"].append({"method": "scene.guarded_second", "params": {"delta": 99}})
    env.provider_hook[0] = provider
    with pytest.raises(env.errors.BridgeError) as caught:
        env.batch.batch_execute(env.context, params)
    assert injected and caught.value.code == "NOT_IMPLEMENTED"
    assert env.state["owned"] == (0 if when == "first_preflight" else 1)
    assert env.handlers == ([] if when == "first_preflight" else ["scene.guarded_first"])
    assert len(env.factories) == (0 if when == "first_preflight" else 1)
    assert caught.value.context["execution_started"] is (when == "between_steps")
    assert env.context.checkpoint_admission is None


@pytest.mark.parametrize("names", [("scene.guarded_first", "scene.inspect", "scene.guarded_second"),
                                  ("scene.guarded_first", "scene.guarded_second", "scene.inspect")])
def test_readonly_steps_do_not_disable_or_replace_guarded_mutator_chain(env, names):
    result = execute(env, names)
    assert result["completed_steps"] == 3
    assert env.handlers == list(names)
    assert len(env.factories) == 2
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 1
    assert env.context.checkpoint_admission is None


@pytest.mark.parametrize("names", [("scene.guarded_first", "scene.legacy"),
                                  ("scene.legacy", "scene.guarded_first"),
                                  ("scene.guarded_first", "scene.inspect", "scene.legacy")])
def test_mixed_guarded_and_unguarded_mutators_are_rejected_before_first_checkpoint(env, names):
    with pytest.raises(env.errors.BridgeError) as caught:
        execute(env, names)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert env.handlers == env.factories == []
    assert env.state == {"owned": 0, "protected": "original"}
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


@pytest.mark.parametrize("field,value", [("protected", "manual edit"), ("owned", 99)])
@pytest.mark.parametrize("source", ["permission_provider", "preflight_resolver"])
def test_late_preflight_effect_cannot_be_adopted_by_second_factory(env, monkeypatch, field, value, source):
    injected = []

    def inject():
        in_phase = source != "permission_provider" or env.prepare_phase[0] == "scene.guarded_second"
        if len(env.handlers) == 1 and not injected and in_phase:
            env.state[field] = value
            injected.append(True)
            env.events.append(("foreign_edit", source))

    if source == "permission_provider":
        env.provider_hook[0] = inject
    else:
        prepare = env.registry.prepare_call

        def resolver(method, params, context, **kwargs):
            result = prepare(method, params, context, **kwargs)
            if method == "scene.guarded_second":
                inject()
            return result

        monkeypatch.setattr(env.registry, "prepare_call", resolver)
    with pytest.raises(env.errors.BridgeError) as caught:
        execute(env)
    assert injected == [True]
    assert caught.value.code == "OPERATION_FAILED"
    assert env.handlers == ["scene.guarded_first"]
    assert [guard.name for guard in env.factories] == ["scene.guarded_first"]
    assert env.state[field] == value
    assert env.checkpoints.before_pushes == 1 and env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None
    assert env.registry.executing_mutators == 0


def test_no_provider_runs_between_previous_transition_proof_and_new_factory_baseline(env):
    execute(env)
    second = next(index for index, event in enumerate(env.events)
                  if event[:2] == ("factory", "scene.guarded_second"))
    assert env.events[second - 1][:2] == ("guard", "scene.guarded_first")
    assert not any(event[0] == "provider" for event in env.events[second - 1:second])


def test_checkpoint_reader_effect_is_refused_before_initial_native_push(env):
    env.checkpoints.before_hook = lambda: env.state.__setitem__("protected", "late checkpoint-reader edit")
    with pytest.raises(env.errors.BridgeError):
        execute(env)
    assert env.state == {"owned": 0, "protected": "late checkpoint-reader edit"}
    assert env.handlers == [] and len(env.factories) == 1
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


def test_post_handler_scope_failure_refuses_next_factory_and_final_checkpoint(env):
    def corrupt(_name):
        env.state["protected"] = "native callback edit"

    env.handler_hook[0] = corrupt
    with pytest.raises(env.errors.BridgeError):
        execute(env)
    assert env.handlers == ["scene.guarded_first"] and len(env.factories) == 1
    assert env.state == {"owned": 1, "protected": "native callback edit"}
    assert env.checkpoints.before_pushes == 1 and env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None


def test_history_callback_effect_is_not_adopted_at_next_step(env, monkeypatch):
    record = env.context.state.record_operation
    injected = []

    def history(**kwargs):
        result = record(**kwargs)
        if kwargs.get("tool") == "scene.guarded_first" and not injected:
            env.state["protected"] = "history callback edit"
            injected.append(True)
        return result

    monkeypatch.setattr(env.context.state, "record_operation", history)
    with pytest.raises(env.errors.BridgeError):
        execute(env)
    assert injected == [True]
    assert env.handlers == ["scene.guarded_first"] and len(env.factories) == 1
    assert env.state["protected"] == "history callback edit"
    assert env.checkpoints.after_pushes == 0


def test_latest_guard_is_rechecked_after_final_checkpoint_readers(env):
    env.checkpoints.after_hook = lambda: env.state.__setitem__("protected", "late finalization edit")
    with pytest.raises(env.errors.BridgeError):
        execute(env)
    assert env.handlers == ["scene.guarded_first", "scene.guarded_second"]
    assert env.state == {"owned": 3, "protected": "late finalization edit"}
    assert env.checkpoints.before_pushes == 1 and env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


def test_call_identity_tampering_during_later_provider_cannot_create_new_binding(env):
    injected = []

    def tamper():
        if len(env.handlers) == 1 and not injected and env.prepare_phase[0] == "scene.guarded_second":
            env.context.checkpoint_call_id = object()
            injected.append(True)

    env.provider_hook[0] = tamper
    with pytest.raises(env.errors.BridgeError) as caught:
        execute(env)
    assert injected == [True] and caught.value.code == "NOT_IMPLEMENTED"
    assert env.handlers == ["scene.guarded_first"] and len(env.factories) == 1
    assert env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


@pytest.mark.parametrize("failure", ["PERMISSION_DENIED", "TOOLSET_DISABLED", "TIMEOUT"])
def test_late_authority_failure_retains_first_effect_without_new_admission_or_push(env, failure):
    injected = []

    def revoke():
        if len(env.handlers) != 1 or injected or env.prepare_phase[0] != "scene.guarded_second":
            return
        injected.append(True)
        if failure == "PERMISSION_DENIED":
            env.grants["EDIT_SCENE"] = False
        elif failure == "TOOLSET_DISABLED":
            env.registry.disable_toolset("scene_edit")
        else:
            env.context.check_final_request = lambda: (_ for _ in ()).throw(env.errors.BridgeError("TIMEOUT", "Caller disconnected"))

    env.provider_hook[0] = revoke
    with pytest.raises(env.errors.BridgeError) as caught:
        execute(env)
    assert caught.value.code == failure and injected == [True]
    assert env.handlers == ["scene.guarded_first"] and len(env.factories) == 1
    assert env.state == {"owned": 1, "protected": "original"}
    assert env.checkpoints.before_pushes == 1 and env.checkpoints.after_pushes == 0


@pytest.mark.parametrize("returned", [None, 7])
def test_declared_factory_with_invalid_result_fails_closed_before_native_push(env, returned):
    env.registry.register("scene.invalid_admission", lambda _c, _p: env.handlers.append("invalid"),
                          toolset="scene_edit", modifies=True,
                          checkpoint_batch_reviewed=True,
                          checkpoint_admission_factory=lambda _c, _p: returned)
    with pytest.raises(env.errors.BridgeError):
        execute(env, ("scene.invalid_admission",))
    assert env.handlers == []
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


def test_factory_rejection_restores_enclosing_context_without_checkpoint(env):
    primary = env.errors.BridgeError("NOT_IMPLEMENTED", "Factory profile is unsupported")

    def reject(_context, _params):
        raise primary

    env.registry.register("scene.rejected", lambda _c, _p: env.handlers.append("rejected"),
                          toolset="scene_edit", modifies=True, checkpoint_admission_factory=reject,
                          checkpoint_batch_reviewed=True)
    with pytest.raises(env.errors.BridgeError) as caught:
        execute(env, ("scene.rejected",))
    assert caught.value.code == primary.code and "Factory profile" in caught.value.message
    assert env.handlers == [] and env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


def test_legacy_batches_and_plan_keep_default_none_behavior(env):
    plan = env.batch.batch_plan(env.context, {"steps": steps("scene.guarded_first", "scene.guarded_second")})
    assert plan["ready"] and env.factories == env.handlers == []
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    result = execute(env, ("scene.legacy", "scene.legacy"))
    assert result["completed_steps"] == 2 and env.state["owned"] == 3
    assert env.factories == [] and env.checkpoints.before_pushes == env.checkpoints.after_pushes == 1
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


def test_direct_binding_lifetime_restores_previous_slots_on_exception(env):
    spec, params = env.registry.get("scene.guarded_first"), {"delta": 1}
    previous = object()
    env.context.checkpoint_call_id = previous
    with (pytest.raises(RuntimeError, match="handler error"),
          env.registry.checkpoint_admission(spec, params, env.context) as binding):
        assert binding is env.context.checkpoint_admission and binding.matches(spec, params, env.context)
        binding()
        raise RuntimeError("handler error")
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is previous
    with pytest.raises(env.errors.BridgeError, match="completed call"):
        binding()


def test_nested_readonly_binding_restores_exact_enclosing_guard(env):
    outer_spec, outer_params = env.registry.get("scene.guarded_first"), {}
    read_spec, read_params = env.registry.get("scene.inspect"), {}
    with env.registry.checkpoint_admission(outer_spec, outer_params, env.context) as outer:
        call_id = env.context.checkpoint_call_id
        with env.registry.checkpoint_admission(read_spec, read_params, env.context) as inner:
            assert inner is None and env.context.checkpoint_admission is None
        assert env.context.checkpoint_admission is outer and env.context.checkpoint_call_id is call_id
        outer()


def test_callback_provider_cannot_tamper_binding_identity_before_native_checkpoint_write(env):
    checkpoint_reader_active, injected = [False], []
    env.checkpoints.before_hook = lambda: checkpoint_reader_active.__setitem__(0, True)

    def tamper():
        if checkpoint_reader_active[0] and not injected:
            env.context.checkpoint_call_id = object()
            injected.append(True)

    env.provider_hook[0] = tamper
    with pytest.raises(env.errors.BridgeError):
        execute(env)
    assert injected == [True]
    assert env.handlers == [] and len(env.factories) == 1
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


def test_latched_guard_denial_cannot_resume_finalization_after_grant_is_restored(env):
    revoked = []

    def transient_revoke():
        if len(env.handlers) == 1 and env.prepare_phase[0] is None and not revoked:
            env.grants["EDIT_SCENE"] = False
            revoked.append(True)

    env.provider_hook[0] = transient_revoke
    env.checkpoints.after_hook = lambda: env.grants.__setitem__("EDIT_SCENE", True)
    with pytest.raises(env.errors.BridgeError) as caught:
        execute(env)
    assert caught.value.code == "PERMISSION_DENIED" and revoked == [True]
    assert env.grants["EDIT_SCENE"] is True  # A later host change cannot revive this call.
    assert env.handlers == ["scene.guarded_first"] and len(env.factories) == 1
    assert env.state == {"owned": 1, "protected": "original"}
    assert env.checkpoints.before_pushes == 1 and env.checkpoints.after_pushes == 0


def test_readonly_handler_cannot_hide_state_change_before_next_guarded_step(env):
    def observer(name):
        if name == "scene.inspect":
            env.state["protected"] = "unexpected observer edit"

    env.handler_hook[0] = observer
    with pytest.raises(env.errors.BridgeError):
        execute(env, ("scene.guarded_first", "scene.inspect", "scene.guarded_second"))
    assert env.handlers == ["scene.guarded_first", "scene.inspect"]
    assert len(env.factories) == 1 and env.state["protected"] == "unexpected observer edit"
    assert env.checkpoints.before_pushes == 1 and env.checkpoints.after_pushes == 0
    assert env.context.checkpoint_admission is None and env.context.checkpoint_call_id is None


def outer_executor(env):
    package = env.registry_module.__package__
    executor_module = importlib.import_module(f"{package}.executor")
    queue = importlib.import_module(f"{package}.command_queue")

    class FixedExecutor(executor_module.MainThreadExecutor):
        @property
        def context(self):
            return env.context

    return FixedExecutor(command_queue=queue.CommandQueue(), registry=env.registry, state=env.context.state,
                         permissions=env.context.permissions, checkpoints=env.checkpoints)


@pytest.mark.parametrize("entry", ("direct", "executor_provider", "executor_callback"))
@pytest.mark.parametrize("promotion", (None, "method", "spec"))
def test_outer_batch_entry_freezes_guarded_plan_and_refuses_late_promotion(env, entry, promotion):
    names = ("scene.legacy", "scene.legacy") if promotion else ("scene.guarded_first", "scene.guarded_second")
    params = {"steps": steps(*names)}
    fired = []

    def retarget():
        if not fired:
            fired.append(True)
            if promotion == "method":
                params["steps"][1]["method"] = "scene.guarded_second"
            elif promotion == "spec":
                from dataclasses import replace
                legacy = env.registry.get("scene.legacy")
                env.registry._tools[legacy.name] = replace(legacy, checkpoint_admission_factory=env.registry.get("scene.guarded_second").checkpoint_admission_factory)
            else:
                params["steps"][1]["params"]["delta"] = 99

    if entry == "direct":
        env.provider_hook[0] = retarget
        with pytest.raises(env.errors.BridgeError) as caught:
            env.registry.dispatch("batch.execute", params, env.context)
        assert caught.value.code == "NOT_IMPLEMENTED"
    else:
        protocol = importlib.import_module(f"{env.registry_module.__package__}.protocol")
        request = protocol.Request("batch-first-entry", "batch.execute", params)
        if entry == "executor_provider":
            env.provider_hook[0] = retarget
        response = outer_executor(env).execute_request(request, check_cancelled=retarget if entry == "executor_callback" else None)
        assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
    assert fired == [True]
    assert env.state["owned"] == 0 and env.handlers == env.factories == []
    assert env.checkpoints.before_pushes == env.checkpoints.after_pushes == 0


def test_legacy_outer_batch_does_not_gain_guarded_parameter_bounds(env):
    # Opaque input is handled by this legacy handler and is deliberately beyond
    # the opt-in bounded freezer's admitted request values.
    params = {"steps": [{"method": "scene.legacy", "params": {"delta": 1, "opaque": object()}}]}
    result = env.registry.dispatch("batch.execute", params, env.context)
    assert result["completed_steps"] == 1 and env.state["owned"] == 1
    assert env.factories == []
