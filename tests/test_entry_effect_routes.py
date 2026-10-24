"""Canonical error evidence reaches direct callers and terminal journals."""

from __future__ import annotations

import contextvars
import importlib
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from test_artist_step_evidence import journal, loop, preview, rna_env  # noqa: F401


@pytest.fixture
def route(addon_package):
    effects = importlib.import_module(f"{addon_package}.entry_effects")
    errors = importlib.import_module(f"{addon_package}.errors")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    executor_module = importlib.import_module(f"{addon_package}.executor")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    registry = registry_module.ToolRegistry(enabled_toolsets=("objects",))
    case = NS(effects=effects, errors=errors, registry=registry, state=state,
              grants={"TRANSFORM_OBJECTS": False, "INSPECT_SCENE": True},
              mark=True, factory_hook=None, provider_hook=None, handler_hook=None,
              providers=[], handlers=[], writes=[])

    def provide():
        case.providers.append(effects.snapshot_entry_effects(effects.current_entry_audit()))
        if case.provider_hook is not None:
            case.provider_hook()
        return dict(case.grants)

    manager = permissions.PermissionManager(provide)

    def factory(context, _params):
        if case.mark:
            effects.mark_view_layer_sync_possible()
        if case.factory_hook is not None:
            case.factory_hook(context)

        class Guard:
            def __call__(self):
                context.require(permissions.Permission.TRANSFORM_OBJECTS)

            def check_after_read(self):
                pass

        return Guard()

    def handler(context, _params):
        case.handlers.append(True)
        if case.handler_hook is not None:
            case.handler_hook(context)
        return {}

    case.spec = registry.register(
        "transform.fixture", handler, modifies=True, automatic_checkpoint=False,
        toolset="objects", permissions=(permissions.Permission.TRANSFORM_OBJECTS,),
        checkpoint_admission_factory=factory,
    )
    checkpoints = NS(
        before_modification=lambda *a, **k: case.writes.append("before"),
        after_modification=lambda *a, **k: case.writes.append("after"),
        finish_editor_session=lambda *a, **k: case.writes.append("finish"),
        editor_session_status=lambda: None,
    )
    case.context = registry_module.ToolContext(state, manager, registry, checkpoints)
    case.executor = executor_module.MainThreadExecutor(
        command_queue=queue.CommandQueue(), registry=registry, state=state,
        permissions=manager, checkpoints=checkpoints,
    )
    return case


def expected(handler=False):
    return {"view_layer_sync_possible": True, "context_change_measured": False,
            "handler_entered": handler, "reinspection_required": True}


@pytest.mark.parametrize("entry", ["executor", "dispatch", "invoke", "held_permit"])
def test_denied_entry_keeps_primary_and_reports_before_scope_exit(route, entry):
    case = route
    primary = case.errors.BridgeError("PERMISSION_DENIED", "Exact denied grant", {"execution_started": False, "possible_mutation": False})
    case.provider_hook = lambda: (_ for _ in ()).throw(primary)
    with pytest.raises(case.errors.BridgeError) as caught:
        if entry == "executor":
            case.executor.dispatch(case.spec.name, {})
        elif entry == "dispatch":
            case.registry.dispatch(case.spec.name, {}, case.context)
        elif entry == "invoke":
            case.registry.invoke(case.spec, {}, case.context)
        else:
            params = {}
            with case.registry.mutation_entry(case.spec, params, case.context) as permit:
                with pytest.raises(case.errors.BridgeError) as inner:
                    case.registry.invoke(case.spec, params, case.context, _permit=permit)
                assert inner.value is primary
                assert inner.value.context["entry_effects"] == expected()
                raise inner.value
    assert caught.value is primary and caught.value.message == "Exact denied grant"
    assert primary.context["execution_started"] is False and primary.context["possible_mutation"] is False
    assert primary.context["entry_effects"] == expected()
    assert primary.context["verification_required"] is True
    assert not case.handlers and not case.writes
    assert case.effects.current_entry_audit() is None
    if entry == "executor":
        assert case.state.history()[0]["entry_effects"] == expected()


def test_omitted_legacy_fields_stay_omitted_and_unmarked_next_entry_is_clean(route):
    with pytest.raises(route.errors.BridgeError) as caught:
        route.executor.dispatch(route.spec.name, {})
    assert caught.value.context["entry_effects"] == expected()
    assert "execution_started" not in caught.value.context
    assert "possible_mutation" not in caught.value.context
    route.mark = False
    with pytest.raises(route.errors.BridgeError) as clean:
        route.executor.dispatch(route.spec.name, {})
    assert "entry_effects" not in clean.value.context
    assert "verification_required" not in clean.value.context
    assert "entry_effects" not in route.state.history()[0]


def test_deferred_factory_error_does_not_replace_denied_permission_or_leak_data(route):
    def fail(_context):
        raise route.errors.BridgeError("NOT_IMPLEMENTED", "Private Scene detail", {"object": "Private Cube"})
    route.factory_hook = fail
    with pytest.raises(route.errors.BridgeError) as caught:
        route.executor.dispatch(route.spec.name, {})
    assert caught.value.code == "PERMISSION_DENIED"
    assert "Private" not in str(caught.value.to_dict())
    assert caught.value.context["entry_effects"] == expected()
    assert not route.handlers and not route.writes


def test_generic_factory_failure_and_handler_failure_keep_their_own_meaning(route):
    route.grants["TRANSFORM_OBJECTS"] = True
    route.factory_hook = lambda _ctx: (_ for _ in ()).throw(RuntimeError("factory error"))
    with pytest.raises(route.errors.BridgeError) as caught:
        route.executor.dispatch(route.spec.name, {})
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["execution_started"] is False
    assert caught.value.context["entry_effects"] == expected()
    route.factory_hook = None
    route.handler_hook = lambda _ctx: (_ for _ in ()).throw(RuntimeError("handler error"))
    with pytest.raises(route.errors.BridgeError) as entered:
        route.executor.dispatch(route.spec.name, {})
    assert entered.value.context["execution_started"] is True
    assert entered.value.context["entry_effects"] == expected(True)


def test_caught_child_handler_and_copied_context_fold_into_exact_outer_entry(route):
    route.mark = False
    child_errors = []
    def child(_context, _params):
        route.effects.mark_view_layer_sync_possible()
        raise route.errors.BridgeError("INVALID_ARGUMENT", "Child failed")
    child_spec = route.registry.register("fixture.read", child, modifies=False)
    def nested(context):
        def dispatch_child():
            with pytest.raises(route.errors.BridgeError) as caught:
                route.registry.dispatch(child_spec.name, {}, context)
            child_errors.append(caught.value)
        contextvars.copy_context().run(dispatch_child)
    route.factory_hook = nested
    with pytest.raises(route.errors.BridgeError) as outer:
        route.executor.dispatch(route.spec.name, {})
    assert outer.value.code == "PERMISSION_DENIED"
    assert outer.value.context["entry_effects"] == expected(False)
    assert child_errors[0].context["entry_effects"] == expected(True)
    assert not route.handlers and not route.writes


def test_expired_caller_after_mark_keeps_timeout_without_starting_handler(route):
    def stopped():
        raise route.errors.BridgeError("TIMEOUT", "Expired caller")
    route.provider_hook = stopped
    with pytest.raises(route.errors.BridgeError) as caught:
        route.executor.dispatch(route.spec.name, {})
    assert caught.value.code == "TIMEOUT" and caught.value.context["entry_effects"] == expected()
    assert not route.handlers and not route.writes


def test_two_registries_retained_permit_keeps_exact_handler_attribution(route, addon_package):
    outer = route
    other = globals()["route"].__wrapped__(addon_package)
    outer.grants["TRANSFORM_OBJECTS"] = True
    primary = outer.errors.BridgeError("INVALID_ARGUMENT", "Retained A handler failed")
    outer.handler_hook = lambda _ctx: (_ for _ in ()).throw(primary)
    other.mark = False
    params = {}
    with outer.registry.mutation_entry(outer.spec, params, outer.context) as permit:
        def invoke_retained(_context):
            with pytest.raises(outer.errors.BridgeError) as child:
                outer.registry.invoke(outer.spec, params, outer.context, _permit=permit)
            assert child.value is primary and primary.context["entry_effects"] == expected(True)
        other.factory_hook = invoke_retained
        with pytest.raises(other.errors.BridgeError) as denied:
            other.executor.dispatch(other.spec.name, {})
        assert denied.value.context["entry_effects"] == expected(False)
        assert other.state.history()[0]["entry_effects"] == expected(False)
    assert len(outer.handlers) == 1 and not other.handlers


def test_unknown_nested_request_does_not_borrow_outer_context_evidence(route):
    def unknown(_context):
        with pytest.raises(route.errors.BridgeError) as child:
            route.executor.dispatch("fixture.unknown", {})
        assert child.value.code == "METHOD_NOT_FOUND"
        assert "entry_effects" not in child.value.context
    route.factory_hook = unknown
    with pytest.raises(route.errors.BridgeError) as outer:
        route.executor.dispatch(route.spec.name, {})
    assert outer.value.context["entry_effects"] == expected()


def test_untrusted_success_result_does_not_create_step_context_evidence(journal):  # noqa: F811
    candidate = preview(journal.env, step_id="revise")
    registry = journal.env.context.registry
    spec = registry.get("task.plan.apply_preview")
    def result_with_fake_evidence(context, params):
        return {**spec.handler(context, params), "entry_effects": expected()}
    registry._tools[spec.name] = replace(spec, handler=result_with_fake_evidence)
    response = journal.apply(candidate)
    assert response.ok, response.error
    assert "entry_effects" not in journal.inspect()["receipts"][0]
    assert "entry_effects" not in journal.env.context.state.history()[0]


def test_annotation_allocation_failure_after_handler_write_preserves_primary(route, monkeypatch):
    route.grants["TRANSFORM_OBJECTS"] = True
    retained = []
    primary = route.errors.BridgeError("PERMISSION_DENIED", "Retained primary after write")
    def write_then_fail(_context):
        retained.append("owned write completed")
        raise primary
    def unavailable(_audit):
        raise MemoryError("optional evidence allocation")
    route.handler_hook = write_then_fail
    monkeypatch.setattr(route.effects, "snapshot_entry_effects", unavailable)
    # The provider spy also uses the snapshot helper; omit that observation so
    # only terminal annotation exercises the injected allocation failure.
    route.executor.permissions._source = lambda: dict(route.grants)
    with pytest.raises(route.errors.BridgeError) as caught:
        route.executor.dispatch(route.spec.name, {})
    assert caught.value is primary and retained == ["owned write completed"]
    assert "entry_effects" not in primary.context


def test_step_receipt_and_history_capture_effects_before_outer_entry_closes(journal):  # noqa: F811
    candidate = preview(journal.env, step_id="revise")
    journal.env.grants["TRANSFORM_OBJECTS"] = False
    response = journal.apply(candidate)
    assert not response.ok and response.error["code"] == "PERMISSION_DENIED"
    receipt = journal.inspect()["receipts"][0]
    assert receipt["outcome"] == "rejected" and receipt["handler_entered"] is False
    assert receipt["execution_started"] is None and receipt["possible_mutation"] is None
    assert receipt["entry_effects"] == response.error["context"]["entry_effects"] == expected()
    assert journal.env.context.state.history()[0]["entry_effects"] == expected()
    assert not journal.checkpoints


@pytest.mark.parametrize("reader", ["context", "session", "roles", "selection_reference"])
def test_known_reader_is_marked_before_first_getter_raises(addon_package, monkeypatch, reader):
    effects = importlib.import_module(f"{addon_package}.entry_effects")
    artist = importlib.import_module(f"{addon_package}.tools.artist_loop")
    object_rna = importlib.import_module(f"{addon_package}.tools._object_rna_mutation")
    roles = importlib.import_module(f"{addon_package}.tools._scene_checkpoint_roles")
    class Getter:
        def __getattr__(self, name):
            assert effects.snapshot_entry_effects(effects.current_entry_audit()) == expected()
            raise RuntimeError("getter failed: " + name)
    if reader in {"context", "selection_reference"}:
        host = NS(context=Getter())
        monkeypatch.setattr(artist, "require_blender", lambda: host)
        monkeypatch.setattr(artist, "_inspect_gate", lambda _ctx: None)
        call = (lambda: artist._context(host)) if reader == "context" else (
            lambda: artist.resolve_reference(None, {"source": "selection"}))
    elif reader == "session":
        monkeypatch.setattr(object_rna.scope, "action_token", lambda _x: "token")
        monkeypatch.setattr(object_rna.scope, "key", lambda _x: 1)
        class Context:
            scene, view_layer = object(), object()
            @property
            def mode(self):
                return Getter().mode
        def call():
            return object_rna.Boundary._session(NS(bpy=NS(context=Context(), data=NS(filepath=""))))
    else:
        monkeypatch.setattr(roles, "_pointer", lambda *_args: object())
        monkeypatch.setattr(roles.proof, "descriptors", lambda *_args: ())
        def call():
            return roles.Plan._read(NS(bpy=NS(context=NS(view_layer=NS(objects=Getter()))), scene=object()))
    with effects.entry_audit() as audit:
        with pytest.raises(RuntimeError, match="getter failed"):
            call()
        assert effects.snapshot_entry_effects(audit) == expected()
