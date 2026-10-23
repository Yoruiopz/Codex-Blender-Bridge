"""An exclusive native operation owns entry, callbacks, and its cleanup tail."""

from __future__ import annotations

import importlib
from copy import copy
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def exclusive(addon_package):
    registry_module = importlib.import_module(addon_package + ".tool_registry")
    executor_module = importlib.import_module(addon_package + ".executor")
    permission_module = importlib.import_module(addon_package + ".permissions")
    queue_module = importlib.import_module(addon_package + ".command_queue")
    state_module = importlib.import_module(addon_package + ".state")
    errors = importlib.import_module(addon_package + ".errors")
    registry = registry_module.ToolRegistry()
    state = state_module.BridgeState()
    case = NS(
        registry=registry, state=state, errors=errors, registry_module=registry_module,
        hooks={}, events=[], writes=[], factory_context=None, factory_params=None,
    )

    def phase(name):
        case.events.append(name)
        callback = case.hooks.pop(name, None)
        if callback is not None:
            callback()

    def provider():
        phase("provider")
        return {permission.value: True for permission in permission_module.Permission}

    permissions = permission_module.PermissionManager(provider)

    def checkpoint(name):
        def run(*args, **kwargs):
            phase(name)
            gate = kwargs.get("before_write")
            if gate is not None:
                gate()
            return True

        return run

    checkpoints = NS(
        before_modification=checkpoint("checkpoint"),
        after_modification=checkpoint("finalization"),
        finish_editor_session=lambda **kwargs: phase("editor finalization"),
        editor_session_status=lambda: None,
    )
    context = registry_module.ToolContext(state, permissions, registry, checkpoints)

    class FixedContextExecutor(executor_module.MainThreadExecutor):
        @property
        def context(self):
            return context

    executor = FixedContextExecutor(
        command_queue=queue_module.CommandQueue(), registry=registry, state=state,
        permissions=permissions, checkpoints=checkpoints,
    )

    class Guard:
        def __call__(self):
            phase("guard")

        def check_after_read(self):
            phase("guard read")

    def factory(call_context, params):
        case.factory_context, case.factory_params = call_context, params
        phase("factory")
        return Guard()

    def outer(call_context, params):
        phase("native")
        registry_module.check_final_mutation(call_context, "fixture.exclusive")
        case.writes.append("outer")
        return {"edited": True}

    case.outer = registry.register(
        "fixture.exclusive", outer, modifies=True, exclusive_mutation=True,
        permissions=(permission_module.Permission.EDIT_SCENE,),
        checkpoint_admission_factory=factory,
    )
    case.child = registry.register(
        "fixture.child", lambda *_: case.writes.append("child") or {"edited": True},
        modifies=True, permissions=(permission_module.Permission.EDIT_SCENE,),
    )
    registry.register("fixture.inspect", lambda *_: state.snapshot(), record_history=False)
    registry.register(
        "fixture.pause", lambda *_: state.set_paused(True) or {"paused": True},
        record_history=False,
    )
    case.executor, case.context, case.checkpoints = executor, context, checkpoints
    case.phase = phase
    return case


def invoke_outer(case, entry="executor"):
    params = {"task_description": "Import the approved asset"}
    if entry == "executor":
        return case.executor.dispatch("fixture.exclusive", params)
    return case.registry.dispatch("fixture.exclusive", params, case.context)


def assert_reentry(error):
    assert error.code == "OPERATION_FAILED"
    assert error.context["reason"] == "REENTRANT_MUTATION_BLOCKED"
    assert error.context["execution_started"] is False


def assert_released(case):
    assert case.registry._exclusive_mutation_lease is None
    assert case.context.exclusive_mutation_lease is None
    assert case.registry.executing_mutators == 0
    assert case.context.checkpoint_admission is None


@pytest.mark.parametrize(
    "entry,phase",
    [
        ("executor", "factory"), ("executor", "provider"),
        ("executor", "checkpoint"), ("executor", "native"),
        ("executor", "finalization"), ("executor", "editor finalization"),
        ("registry", "factory"), ("registry", "provider"), ("registry", "native"),
    ],
)
@pytest.mark.parametrize("nested", ["executor", "registry", "invoke", "same call"])
def test_exclusive_entry_blocks_nested_mutators_before_their_providers_or_checkpoints(
    exclusive, entry, phase, nested
):
    case = exclusive
    observed = []

    def attempt():
        owner = case.registry._exclusive_mutation_lease
        assert owner is not None and case.context.exclusive_mutation_lease is owner
        previous = case.state.snapshot()
        events_before = list(case.events)
        with pytest.raises(case.errors.BridgeError) as caught:
            if nested == "executor":
                case.executor.dispatch("fixture.child", {})
            elif nested == "registry":
                case.registry.dispatch("fixture.child", {}, case.context)
            elif nested == "invoke":
                case.registry.invoke(case.child, {}, case.context)
            else:
                case.registry.invoke(case.outer, case.factory_params, case.factory_context)
        assert_reentry(caught.value)
        assert case.events == events_before
        assert case.state.snapshot()["current_method"] == previous["current_method"]
        assert case.state.snapshot()["is_executing"] == previous["is_executing"]
        assert case.context.exclusive_mutation_lease is owner
        observed.append(caught.value)

    case.hooks[phase] = attempt
    assert invoke_outer(case, entry)["edited"] is True
    assert len(observed) == 1 and case.writes == ["outer"]
    assert_released(case)


def test_readonly_nested_dispatch_restores_outer_display_and_keeps_its_lease(exclusive):
    case = exclusive
    observations = []

    def inspect():
        owner = case.context.exclusive_mutation_lease
        assert case.state.snapshot()["current_method"] == "fixture.exclusive"
        result = case.executor.dispatch("fixture.inspect", {})
        assert result["current_method"] == "fixture.exclusive"
        restored = case.state.snapshot()
        assert restored["current_method"] == "fixture.exclusive"
        assert restored["current_task"] == "Import the approved asset"
        assert restored["is_executing"] is True
        assert case.context.exclusive_mutation_lease is owner
        observations.append(result)

    case.hooks["native"] = inspect
    assert invoke_outer(case)["edited"] is True
    assert len(observations) == 1
    assert_released(case)


def test_pause_control_is_allowed_but_prevents_outer_next_write(exclusive):
    case = exclusive

    def pause():
        assert case.executor.dispatch("fixture.pause", {}) == {"paused": True}
        assert case.state.snapshot()["current_method"] == "fixture.exclusive"

    case.hooks["native"] = pause
    with pytest.raises(case.errors.BridgeError) as caught:
        invoke_outer(case)
    assert caught.value.code == "AGENT_PAUSED"
    assert case.writes == []
    assert_released(case)


@pytest.mark.parametrize("phase", ["factory", "provider", "checkpoint", "native", "finalization"])
def test_exception_releases_the_lease_and_next_top_level_mutator_can_run(exclusive, phase):
    case = exclusive
    primary = case.errors.BridgeError("INVALID_ARGUMENT", "injected " + phase + " failure")

    def fail():
        raise primary

    case.hooks[phase] = fail
    with pytest.raises(case.errors.BridgeError) as caught:
        invoke_outer(case)
    assert caught.value is primary
    assert_released(case)
    before = list(case.writes)
    assert case.executor.dispatch("fixture.child", {})["edited"] is True
    assert case.writes == [*before, "child"]


def test_unexpected_native_exception_releases_lease_after_executor_error_conversion(exclusive):
    case = exclusive

    def fail():
        raise RuntimeError("injected native callback failure")

    case.hooks["native"] = fail
    with pytest.raises(case.errors.BridgeError) as caught:
        invoke_outer(case)
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["exception_type"] == "RuntimeError"
    assert_released(case)
    case.executor.dispatch("fixture.child", {})
    assert case.writes == ["child"]


def test_copying_diagnostic_lease_to_a_different_context_does_not_authorize_entry(exclusive):
    case = exclusive

    def attempt():
        other = case.registry_module.ToolContext(
            case.state, case.context.permissions, case.registry, case.checkpoints
        )
        other.exclusive_mutation_lease = case.context.exclusive_mutation_lease
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(case.outer, case.factory_params, other)
        assert_reentry(caught.value)

    case.hooks["native"] = attempt
    invoke_outer(case)
    assert case.writes == ["outer"]
    assert_released(case)


@pytest.mark.parametrize(
    "receipt", ["context lease", "registry owner", "invocation record", "copied permit"]
)
def test_diagnostic_receipts_cannot_be_used_as_canonical_invocation_permits(exclusive, receipt):
    case, params = exclusive, {}
    with case.registry.mutation_entry(case.outer, params, case.context) as permit:
        candidates = {
            "context lease": case.context.exclusive_mutation_lease,
            "registry owner": case.registry._exclusive_mutation_lease,
            "invocation record": case.registry._mutation_interlock.invocation,
            "copied permit": copy(permit),
        }
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(case.outer, params, case.context, _permit=candidates[receipt])
        assert caught.value.context["reason"] == "INVALID_INVOCATION_CONTINUATION"
        assert case.events == [] and case.writes == []
        case.registry.invoke(case.outer, params, case.context, _permit=permit)
    assert case.writes == ["outer"]
    assert_released(case)


def test_diagnostic_record_cannot_change_minted_identity_or_reset_consumption(exclusive):
    case, params = exclusive, {}
    with case.registry.mutation_entry(case.outer, params, case.context) as permit:
        record = case.registry._mutation_interlock.invocation
        diagnostic = getattr(record, "state", record)
        lookalike = copy(permit)
        with pytest.raises((AttributeError, TypeError)):
            diagnostic.continuation_id = id(lookalike)
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(case.outer, params, case.context, _permit=lookalike)
        assert caught.value.context["reason"] == "INVALID_INVOCATION_CONTINUATION"
        assert case.events == [] and case.writes == []
        case.registry.invoke(case.outer, params, case.context, _permit=permit)
        with pytest.raises((AttributeError, TypeError)):
            diagnostic.consumed = False
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(case.outer, params, case.context, _permit=permit)
        assert caught.value.context["reason"] == "INVALID_INVOCATION_CONTINUATION"
    assert case.writes == ["outer"]
    assert_released(case)


def test_canonical_invocation_permit_is_single_use(exclusive):
    case = exclusive
    params = {}
    with case.registry.mutation_entry(case.child, params, case.context) as permit:
        assert case.registry.invoke(case.child, params, case.context, _permit=permit)["edited"]
        with pytest.raises(case.errors.BridgeError):
            case.registry.invoke(case.child, params, case.context, _permit=permit)
    assert case.writes == ["child"]
    assert_released(case)


@pytest.mark.parametrize("drift", ["context", "params", "spec"])
def test_continuation_for_another_call_cannot_be_used_but_original_remains_valid(exclusive, drift):
    case, params = exclusive, {}
    with case.registry.mutation_entry(case.child, params, case.context) as permit:
        target, forwarded, context = case.child, params, case.context
        if drift == "context":
            context = case.registry_module.ToolContext(
                case.state, case.context.permissions, case.registry, case.checkpoints
            )
        elif drift == "params":
            forwarded = dict(params)
        else:
            target = case.outer
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(target, forwarded, context, _permit=permit)
        assert caught.value.context["reason"] == "INVALID_INVOCATION_CONTINUATION"
        assert case.writes == []
        case.registry.invoke(case.child, params, case.context, _permit=permit)
    assert case.writes == ["child"]
    assert_released(case)


def test_ordinary_nested_mutations_keep_existing_composition_behavior(exclusive):
    case = exclusive

    def compose(context, params):
        case.registry.dispatch("fixture.child", {}, context)
        case.writes.append("composite")
        return {"composed": True}

    ordinary = case.registry.register("fixture.compose", compose, modifies=True)
    assert ordinary.exclusive_mutation is False
    assert case.executor.dispatch("fixture.compose", {})["composed"] is True
    assert case.writes == ["child", "composite"]
    assert_released(case)


def test_exclusive_operation_cannot_adopt_a_baseline_inside_an_ordinary_mutator(exclusive):
    case = exclusive

    def compose(context, params):
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.dispatch("fixture.exclusive", {}, context)
        assert_reentry(caught.value)
        case.writes.append("ordinary")
        return {"edited": True}

    case.registry.register("fixture.compose", compose, modifies=True)
    case.executor.dispatch("fixture.compose", {})
    assert "factory" not in case.events
    assert case.writes == ["ordinary"]
    assert_released(case)


@pytest.fixture
def import_cleanup(exclusive, addon_package, monkeypatch):
    """Real import compensation with a live object and visible removal attempts."""
    case = exclusive
    module = importlib.import_module(addon_package + ".tools.asset_import")
    module.register_tools(case.registry)
    case.registry.enable_toolset("asset_delivery")
    removed = []
    obj = NS(parent=None, users_collection=[], users=0)
    owned = {
        "objects": {1: obj}, "meshes": {}, "materials": {}, "images": {},
        "collections": {}, "scenes": {},
    }
    protected, signature = {"protected": "unchanged"}, {"owned": "unchanged"}
    monkeypatch.setattr(module, "_new_ids", lambda *args: owned)
    monkeypatch.setattr(module, "_owned_signature", lambda *args: signature)
    monkeypatch.setattr(module, "_closure", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_guard", lambda *args, **kwargs: protected)
    monkeypatch.setattr(module, "_runtime_admission", lambda *args: None)
    monkeypatch.setattr(module, "_remove_private_scene", lambda *args: removed.append("scene"))
    bpy = NS(data=NS(objects=NS(remove=lambda *args, **kwargs: removed.append("object"))))
    stage = NS(collection=NS(children=[]))

    def cleanup():
        return module._cleanup(
            bpy, case.context, {}, owned, signature, stage, None, None,
            published=False, protected=protected, native_format="GLB", blocking={},
        )

    return NS(case=case, module=module, cleanup=cleanup, removed=removed)


def test_asset_import_is_the_opt_in_nonbatchable_exclusive_tool(import_cleanup):
    case = import_cleanup.case
    spec = case.registry.get("asset.import")
    assert spec.exclusive_mutation is True and spec.batchable is False
    assert case.registry.get("asset.import_preview").exclusive_mutation is False


@pytest.mark.parametrize("slot", ["registry removed", "registry replaced", "context removed", "context replaced"])
def test_actual_import_gate_rejects_lost_or_wrong_owner_without_releasing_foreign_lease(
    import_cleanup, slot
):
    env, foreign = import_cleanup, object()
    case = env.case
    spec, params = case.registry.get("asset.import"), {}
    with (
        pytest.raises(case.errors.BridgeError) as caught,
        case.registry.mutation_entry(spec, params, case.context),
    ):
        if slot.startswith("registry"):
            case.registry._exclusive_mutation_lease = None if slot.endswith("removed") else foreign
        else:
            case.context.exclusive_mutation_lease = None if slot.endswith("removed") else foreign
        env.module._gate(case.context, writing=True)
    assert caught.value.context["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"
    assert env.removed == []
    if slot == "registry replaced":
        assert case.registry._exclusive_mutation_lease is foreign
    if slot == "context replaced":
        assert case.context.exclusive_mutation_lease is foreign


@pytest.mark.parametrize("slot", ["registry", "context"])
def test_actual_import_gate_rechecks_lease_after_live_permission_provider(import_cleanup, slot):
    env, case = import_cleanup, import_cleanup.case
    spec, params = case.registry.get("asset.import"), {}
    observed = []

    def revoke():
        observed.append("provider")
        if slot == "registry":
            case.registry._exclusive_mutation_lease = None
        else:
            case.context.exclusive_mutation_lease = None

    with (
        pytest.raises(case.errors.BridgeError) as caught,
        case.registry.mutation_entry(spec, params, case.context),
    ):
        case.hooks["provider"] = revoke
        env.module._gate(case.context, writing=True)
    assert observed == ["provider"]
    assert caught.value.context["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"
    assert env.removed == []


def test_actual_import_handler_without_its_registered_lease_cannot_reach_source_preview(
    import_cleanup, monkeypatch
):
    env, case = import_cleanup, import_cleanup.case
    monkeypatch.setattr(
        env.module, "require_blender", lambda: NS(app=NS(version=(4, 5, 1), build_hash=b"other"))
    )
    monkeypatch.setattr(env.module, "_preview", lambda *args, **kwargs: pytest.fail("source preview entered"))
    with pytest.raises(case.errors.BridgeError) as caught:
        env.module.import_asset(case.context, {"collection_name": "Imported Asset", "format": "GLB"})
    assert caught.value.context["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"
    assert env.removed == []


@pytest.mark.parametrize("slot", ["registry", "context"])
def test_actual_import_cleanup_retains_owned_ids_when_owner_drifts_during_last_read(
    import_cleanup, monkeypatch, slot
):
    env, foreign = import_cleanup, object()
    case = env.case

    def drift(*args, **kwargs):
        if slot == "registry":
            case.registry._exclusive_mutation_lease = foreign
        else:
            case.context.exclusive_mutation_lease = foreign
        return {"protected": "unchanged"}

    monkeypatch.setattr(env.module, "_guard", drift)
    spec, params = case.registry.get("asset.import"), {}
    result = None
    with (
        pytest.raises(case.errors.BridgeError),
        case.registry.mutation_entry(spec, params, case.context),
    ):
        result = env.cleanup()
    assert result.startswith("retained_")
    assert env.removed == []


def test_actual_import_cleanup_can_remove_exact_owned_closure_with_live_owner(import_cleanup):
    env, case = import_cleanup, import_cleanup.case
    spec, params = case.registry.get("asset.import"), {}
    with case.registry.mutation_entry(spec, params, case.context):
        assert env.cleanup() == "removed"
    assert env.removed == ["object", "scene"]
    assert_released(case)


def test_primary_failure_is_preserved_when_lease_changes_during_unwinding(exclusive):
    case, foreign = exclusive, object()
    primary = case.errors.BridgeError("INVALID_ARGUMENT", "native import failed")

    def fail():
        case.registry._exclusive_mutation_lease = foreign
        raise primary

    case.hooks["native"] = fail
    with pytest.raises(case.errors.BridgeError) as caught:
        invoke_outer(case)
    assert caught.value is primary
    assert caught.value.code == "INVALID_ARGUMENT"
    assert caught.value.context["exclusive_mutation_lease_drift"]["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"
    assert case.registry._exclusive_mutation_lease is foreign
    assert case.writes == []
