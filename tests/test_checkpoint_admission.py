"""Request-owned checkpoint admission binding and registry entry contracts."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from types import SimpleNamespace as NS
from typing import Any

import pytest
from test_checkpoint_authority import authority

assert authority  # Reuse actual native-shaped manager completion, never a fabricated event.


@pytest.fixture
def admission(addon_package: str) -> Any:
    module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    plans = importlib.import_module(f"{addon_package}.task_plans")
    state = state_module.BridgeState()
    registry = module.ToolRegistry(enabled_toolsets=("scene_edit",))
    grants = {item.value: True for item in permissions.Permission}
    context = module.ToolContext(
        state, permissions.PermissionManager(lambda: dict(grants)), registry, NS()
    )
    case = NS(
        module=module, errors=errors, permissions=permissions, plans=plans,
        state=state, registry=registry, context=context, grants=grants,
        events=[], captures=[], checks=[], handlers=[], factory_hooks={},
        callback_hooks={}, readonly_hooks={}, readonly_checks=[], handler_hooks={}, specs={},
    )

    def observe(phase: str, method: str, call_context: Any, params: Any) -> Any:
        entry = NS(
            phase=phase, method=method, context=call_context, params=params,
            binding=call_context.checkpoint_admission,
            call_id=call_context.checkpoint_call_id,
            mutators=registry.executing_mutators,
            plan_mutators=plans.get_task_plans(call_context.state).executing_mutators,
        )
        case.events.append(entry)
        return entry

    def factory(method: str) -> Callable[..., Any]:
        def capture(call_context: Any, params: Mapping[str, Any]) -> Any:
            captured = observe("capture", method, call_context, params)
            case.captures.append(captured)
            if hook := case.factory_hooks.get(method):
                hook(call_context, params)

            class Guard:
                def __call__(self) -> None:
                    checked = observe("check", method, call_context, params)
                    checked.capture = captured
                    case.checks.append(checked)
                    if hook := case.callback_hooks.get(method):
                        hook(call_context, params)

                def check_after_read(self) -> None:
                    case.readonly_checks.append(call_context.checkpoint_admission)
                    if hook := case.readonly_hooks.get(method):
                        hook(call_context, params)
                    module.check_final_mutation(call_context, method)

            captured.guard = Guard()
            return captured.guard

        return capture

    def register(method: str, *, guarded: bool = True, modifies: bool = True) -> Any:
        def handler(call_context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
            case.handlers.append(observe("handler", method, call_context, params))
            if hook := case.handler_hooks.get(method):
                hook(call_context, params)
            return {"method": method, "value": params.get("value")}

        spec = registry.register(
            method, handler, permissions=(permissions.Permission.EDIT_SCENE,),
            toolset="scene_edit", modifies=modifies,
            checkpoint_admission_factory=factory(method) if guarded else None,
        )
        case.specs[method] = spec
        return spec

    case.register = register
    register("scene.one")
    register("scene.two")
    register("scene.legacy", guarded=False)
    return case


def assert_clean(case: Any) -> None:
    assert case.context.checkpoint_admission is None
    assert case.context.checkpoint_call_id is None
    assert case.context.checkpoint_method is None
    assert case.context.checkpoint_params is None
    assert case.context.checkpoint_finalization_owner is None
    assert case.registry.executing_mutators == 0
    assert case.plans.get_task_plans(case.state).executing_mutators == 0


def assert_invalid(
    case: Any, callback: Callable[[], Any], *, known_not_started: bool = False,
) -> Any:
    with pytest.raises(case.errors.BridgeError) as caught:
        callback()
    assert caught.value.code == case.errors.ErrorCode.NOT_IMPLEMENTED
    expected = {"checkpoint_admission_valid": False}
    if known_not_started:
        expected["execution_started"] = False
    assert caught.value.context == expected
    return caught.value


def test_direct_dispatch_creates_checks_and_retires_request_binding(admission: Any) -> None:
    case, params = admission, {"value": 3}

    assert case.registry.dispatch("scene.one", params, case.context) == {
        "method": "scene.one", "value": 3,
    }

    assert [event.phase for event in case.events] == ["capture", "check", "handler"]
    capture, check, handler = case.events
    assert capture.binding is None and capture.call_id is None
    assert capture.params is params and check.params is params and handler.params is params
    assert check.binding is handler.binding
    assert check.call_id is handler.call_id is handler.binding.call_id
    assert check.binding.params is params and check.binding.context is case.context
    assert check.binding.method == "scene.one"
    assert not check.binding.active
    assert [(event.mutators, event.plan_mutators) for event in case.events] == [
        (0, 0), (1, 1), (1, 1),
    ]
    assert case.context.handler_entries == 1
    assert_invalid(case, check.binding)
    assert_clean(case)


def test_serial_dispatch_never_reuses_completed_binding_even_with_same_params(admission: Any) -> None:
    case, params = admission, {"value": 4}
    for _ in range(2):
        case.registry.dispatch("scene.one", params, case.context)

    first, second = case.checks
    assert len(case.captures) == 2
    assert first.binding is not second.binding
    assert first.call_id is not second.call_id
    assert not first.binding.active and not second.binding.active
    assert case.context.handler_entries == 2
    assert_clean(case)


def test_exact_enclosing_binding_is_reused_until_its_owner_exits(admission: Any) -> None:
    case, params = admission, {"value": 5}
    spec = case.specs["scene.one"]

    with case.registry.checkpoint_admission(spec, params, case.context) as binding:
        assert binding.active and binding.matches(spec, params, case.context)
        binding()
        case.registry.invoke(spec, params, case.context)
        assert len(case.captures) == 1 and len(case.checks) == 2
        assert all(check.binding is binding for check in case.checks)
        assert case.handlers[0].binding is binding
        assert binding.active and case.context.checkpoint_admission is binding

    assert not binding.active
    assert_invalid(case, binding)
    assert_clean(case)


@pytest.mark.parametrize("method, equal_params", [("scene.one", True), ("scene.two", False)])
def test_equal_mapping_or_different_step_requires_fresh_binding(
    admission: Any, method: str, equal_params: bool,
) -> None:
    case, params = admission, {"value": 6}
    nested_params = dict(params) if equal_params else params
    outer_spec, inner_spec = case.specs["scene.one"], case.specs[method]

    with case.registry.checkpoint_admission(outer_spec, params, case.context) as outer:
        case.registry.invoke(inner_spec, nested_params, case.context)
        inner = case.handlers[-1].binding
        assert inner is not outer and not inner.active
        assert inner.params is nested_params and inner.method == method
        assert case.captures[-1].binding is outer
        assert case.context.checkpoint_admission is outer and outer.active
        assert case.context.checkpoint_call_id is outer.call_id
        outer()

    assert len(case.captures) == 2
    assert_clean(case)


def test_wrong_call_token_cannot_reuse_or_directly_call_outer_binding(admission: Any) -> None:
    case, params = admission, {"value": 7}
    spec = case.specs["scene.one"]

    with case.registry.checkpoint_admission(spec, params, case.context) as outer:
        replacement_token = object()
        case.context.checkpoint_call_id = replacement_token
        primary = assert_invalid(case, outer)
        assert assert_invalid(case, lambda: case.registry.invoke(spec, params, case.context)) is primary
        assert case.context.checkpoint_admission is outer
        assert case.context.checkpoint_call_id is replacement_token
        assert assert_invalid(case, outer) is primary
        case.context.checkpoint_call_id = outer.call_id
        assert assert_invalid(case, outer) is primary

    assert len(case.captures) == 1
    assert case.handlers == [] and case.checks == []
    assert_clean(case)


def test_inactive_binding_restored_by_caller_is_replaced_for_invoke(admission: Any) -> None:
    case, params = admission, {"value": 8}
    spec = case.specs["scene.one"]
    with case.registry.checkpoint_admission(spec, params, case.context) as stale:
        pass
    case.context.checkpoint_admission = stale
    case.context.checkpoint_call_id = stale.call_id

    assert_invalid(case, stale)
    case.registry.invoke(spec, params, case.context)
    fresh = case.handlers[-1].binding
    assert fresh is not stale and not fresh.active
    assert case.context.checkpoint_admission is stale
    assert case.context.checkpoint_call_id is stale.call_id
    assert_invalid(case, stale)
    assert len(case.captures) == 2
    case.context.checkpoint_admission = case.context.checkpoint_call_id = None
    assert_clean(case)


def test_binding_from_another_context_is_not_reused(admission: Any) -> None:
    case, params = admission, {"value": 9}
    spec = case.specs["scene.one"]
    other = case.module.ToolContext(
        case.state, case.context.permissions, case.registry, NS(),
    )

    with case.registry.checkpoint_admission(spec, params, case.context) as outer:
        other.checkpoint_admission, other.checkpoint_call_id = outer, outer.call_id
        assert not outer.matches(spec, params, other)
        case.registry.invoke(spec, params, other)
        inner = case.handlers[-1].binding
        assert inner is not outer and inner.context is other and not inner.active
        assert other.checkpoint_admission is outer and other.checkpoint_call_id is outer.call_id
        assert case.context.checkpoint_admission is outer and outer.active
        outer()

    assert len(case.captures) == 2
    assert_clean(case)


def test_temporarily_displaced_binding_remains_stopped_after_restoration(admission: Any) -> None:
    case, params = admission, {"value": 10}
    spec = case.specs["scene.one"]

    with case.registry.checkpoint_admission(spec, params, case.context) as outer:
        with case.registry.checkpoint_admission(spec, params, case.context) as inner:
            assert outer.active and inner.active
            primary = assert_invalid(case, outer)
            assert assert_invalid(case, inner) is primary
            assert inner.stopped is primary
            assert assert_invalid(case, lambda: case.registry.invoke(spec, params, case.context)) is primary
        assert not inner.active
        assert case.context.checkpoint_admission is outer
        assert case.context.checkpoint_call_id is outer.call_id
        assert assert_invalid(case, outer) is primary
        assert outer.stopped is primary

    assert [check.binding for check in case.checks] == [inner]
    assert case.handlers == [] and case.context.handler_entries == 0
    assert_clean(case)


def test_failed_nested_guard_latches_parent_drift_without_replacing_primary_denial(admission: Any) -> None:
    case, params, drift = admission, {"value": 10}, [False]
    parent_denial = case.errors.BridgeError(case.errors.ErrorCode.NOT_IMPLEMENTED, "Parent authored state changed",
                                           {"checkpoint_admission_valid": False})
    child_denial = case.errors.BridgeError(case.errors.ErrorCode.PERMISSION_DENIED, "Child permission denied")

    def parent_readonly(_context: Any, _params: Any) -> None:
        if drift[0]:
            raise parent_denial

    def child_provider(_context: Any, _params: Any) -> None:
        drift[0] = True
        raise child_denial

    case.readonly_hooks["scene.one"] = parent_readonly
    case.callback_hooks["scene.two"] = child_provider
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(case.specs["scene.two"], params, case.context)
        assert caught.value is child_denial
        assert outer.stopped is parent_denial
        inner = case.checks[0].binding
        assert inner.stopped is child_denial and not inner.active
        drift[0] = False
        assert assert_invalid(case, outer) is parent_denial
        assert len(case.checks) == 1
        assert case.handlers == [] and case.context.handler_entries == 0

    assert_clean(case)


@pytest.mark.parametrize("kind", ["runtime", "bridge"])
def test_factory_exception_preserves_enclosing_binding_and_primary_error(
    admission: Any, kind: str,
) -> None:
    case, params = admission, {"value": 11}
    error = (RuntimeError("capture failed") if kind == "runtime" else
             case.errors.BridgeError(case.errors.ErrorCode.NOT_IMPLEMENTED, "capture refused"))

    def fail(_context: Any, _params: Any) -> None:
        raise error

    case.factory_hooks["scene.two"] = fail
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(case.specs["scene.two"], params, case.context)
        if kind == "bridge":
            assert caught.value is error
        else:
            assert caught.value.code == case.errors.ErrorCode.OPERATION_FAILED
            assert caught.value.__cause__ is error
            assert caught.value.context == {
                "execution_started": False, "checkpoint_admission_valid": False,
                "verification_required": True,
            }
            assert "capture failed" not in caught.value.message
        assert case.context.checkpoint_admission is outer and outer.active
        assert case.context.checkpoint_call_id is outer.call_id
        assert case.captures[-1].binding is outer
        assert case.captures[-1].mutators == 0
        assert case.context.handler_entries == 0
        assert case.handlers == case.checks == []
        assert case.readonly_checks == [outer]
        outer()

    assert_clean(case)


@pytest.mark.parametrize("invalid_callback", [None, False, 1, "guard", object()])
def test_noncallable_factory_result_refuses_before_replacing_outer_context(
    admission: Any, invalid_callback: Any,
) -> None:
    case, params = admission, {"value": 12}
    handler_calls = []
    invalid = case.registry.register(
        "scene.invalid", lambda _context, _params: handler_calls.append(True),
        toolset="scene_edit", modifies=True,
        checkpoint_admission_factory=lambda _context, _params: invalid_callback,
    )

    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        assert_invalid(case, lambda: case.registry.invoke(invalid, params, case.context),
                       known_not_started=True)
        assert case.context.checkpoint_admission is outer and outer.active
        assert case.context.checkpoint_call_id is outer.call_id
        assert handler_calls == [] and case.context.handler_entries == 0
        assert case.registry.executing_mutators == 0
        outer()

    assert_clean(case)


@pytest.mark.parametrize("kind", ["runtime", "bridge"])
def test_nested_handler_exception_retires_inner_binding_and_restores_outer(
    admission: Any, kind: str,
) -> None:
    case, params = admission, {"value": 13}
    error = (RuntimeError("handler failed") if kind == "runtime" else
             case.errors.BridgeError(case.errors.ErrorCode.INVALID_ARGUMENT, "handler refused"))

    def fail(_context: Any, _params: Any) -> None:
        raise error

    case.handler_hooks["scene.two"] = fail
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        with pytest.raises(type(error)) as caught:
            case.registry.invoke(case.specs["scene.two"], params, case.context)
        assert caught.value is error
        inner = case.handlers[-1].binding
        assert not inner.active and outer.active
        assert case.context.checkpoint_admission is outer
        assert case.context.checkpoint_call_id is outer.call_id
        assert case.registry.executing_mutators == 0
        assert case.plans.get_task_plans(case.state).executing_mutators == 0
        outer()

    assert case.context.handler_entries == 1
    assert_clean(case)


def test_nested_context_body_exception_restores_the_exact_enclosing_pair(admission: Any) -> None:
    case, params = admission, {"value": 14}
    error = RuntimeError("body failed")
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        with (pytest.raises(RuntimeError) as caught,
              case.registry.checkpoint_admission(case.specs["scene.two"], params, case.context) as inner):
            raise error
        assert caught.value is error
        assert not inner.active and outer.active
        assert case.context.checkpoint_admission is outer
        assert case.context.checkpoint_call_id is outer.call_id
        outer()

    assert case.handlers == []
    assert_clean(case)


@pytest.mark.parametrize("kind", ["runtime", "bridge"])
def test_callback_exception_prevents_handler_and_balances_inflight_counters(
    admission: Any, kind: str,
) -> None:
    case = admission
    error = (RuntimeError("check failed") if kind == "runtime" else
             case.errors.BridgeError(case.errors.ErrorCode.PERMISSION_DENIED, "check refused"))

    def fail(_context: Any, _params: Any) -> None:
        raise error

    case.callback_hooks["scene.one"] = fail
    with pytest.raises(case.errors.BridgeError) as caught:
        case.registry.dispatch("scene.one", {"value": 15}, case.context)
    if kind == "bridge":
        assert caught.value is error
    else:
        assert caught.value.code == case.errors.ErrorCode.OPERATION_FAILED
        assert caught.value.__cause__ is error
        assert caught.value.context == {
            "checkpoint_admission_valid": False, "verification_required": True,
        }
        assert "check failed" not in caught.value.message
    assert [event.phase for event in case.events] == ["capture", "check"]
    assert case.handlers == [] and case.context.handler_entries == 0
    assert not case.checks[-1].binding.active
    assert case.checks[-1].binding.stopped is caught.value
    assert_clean(case)


def test_admission_bridge_failure_latches_and_cannot_rebaseline_the_same_call(admission: Any) -> None:
    case, params = admission, {"value": 16}
    error = case.errors.BridgeError(case.errors.ErrorCode.PERMISSION_DENIED, "grant revoked")

    def fail(_context: Any, _params: Any) -> None:
        raise error

    case.callback_hooks["scene.one"] = fail
    spec = case.specs["scene.one"]
    with case.registry.checkpoint_admission(spec, params, case.context) as binding:
        with pytest.raises(case.errors.BridgeError) as first:
            binding()
        assert first.value is error and binding.stopped is error
        del case.callback_hooks["scene.one"]
        with pytest.raises(case.errors.BridgeError) as second:
            case.registry.invoke(spec, params, case.context)
        assert second.value is error
        assert len(case.captures) == len(case.checks) == 1
        assert case.handlers == [] and case.context.handler_entries == 0
        assert binding.active

    assert_clean(case)


@pytest.mark.parametrize("change", ["call_id", "binding", "active"])
def test_identity_changed_during_callback_refuses_before_handler(admission: Any, change: str) -> None:
    case = admission

    def invalidate(context: Any, _params: Any) -> None:
        if change == "call_id":
            context.checkpoint_call_id = object()
        elif change == "binding":
            context.checkpoint_admission = None
        else:
            context.checkpoint_admission.active = False

    case.callback_hooks["scene.one"] = invalidate
    assert_invalid(case, lambda: case.registry.dispatch("scene.one", {"value": 17}, case.context))
    assert len(case.checks) == 1
    assert case.handlers == [] and case.context.handler_entries == 0
    assert not case.checks[0].binding.active
    assert case.checks[0].binding.stopped is not None
    assert_clean(case)


@pytest.mark.parametrize("gate", ["request", "job", "toolset", "pause", "stop"])
def test_pure_final_gate_runs_after_admission_and_before_handler(admission: Any, gate: str) -> None:
    case = admission
    error = case.errors.BridgeError(case.errors.ErrorCode.NOT_IMPLEMENTED, "caller ended")

    def fail() -> None:
        raise error

    def invalidate(context: Any, _params: Any) -> None:
        if gate == "request":
            context.check_final_request = fail
        elif gate == "job":
            context.check_final_job = fail
        elif gate == "toolset":
            case.registry.disable_toolset("scene_edit")
        elif gate == "pause":
            case.state.set_paused(True)
        else:
            case.state.set_emergency_stopped(True)

    case.callback_hooks["scene.one"] = invalidate
    with pytest.raises(case.errors.BridgeError) as caught:
        case.registry.dispatch("scene.one", {"value": 18}, case.context)
    expected = {
        "request": case.errors.ErrorCode.NOT_IMPLEMENTED,
        "job": case.errors.ErrorCode.NOT_IMPLEMENTED,
        "toolset": case.errors.ErrorCode.TOOLSET_DISABLED,
        "pause": case.errors.ErrorCode.AGENT_PAUSED,
        "stop": case.errors.ErrorCode.EMERGENCY_STOPPED,
    }
    assert caught.value.code == expected[gate]
    assert [event.phase for event in case.events] == ["capture", "check"]
    assert case.handlers == [] and case.context.handler_entries == 0
    assert_clean(case)


def test_legacy_call_temporarily_clears_enclosing_admission_and_restores_it(admission: Any) -> None:
    case, params = admission, {"value": 19}

    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        case.registry.invoke(case.specs["scene.legacy"], params, case.context)
        legacy = case.handlers[-1]
        assert legacy.binding is None and legacy.call_id is not None
        assert legacy.call_id is not outer.call_id
        assert case.context.checkpoint_admission is outer
        assert case.context.checkpoint_call_id is outer.call_id
        assert outer.active
        outer()

    assert len(case.captures) == 1
    assert_clean(case)


def test_nested_handler_dispatch_preserves_outer_binding_and_mutator_depth(admission: Any) -> None:
    case, params = admission, {"value": 20}
    restored = []

    def nested(context: Any, _params: Any) -> None:
        outer, call_id = context.checkpoint_admission, context.checkpoint_call_id
        case.registry.dispatch("scene.two", params, context)
        restored.append((context.checkpoint_admission is outer,
                         context.checkpoint_call_id is call_id,
                         case.registry.executing_mutators,
                         case.plans.get_task_plans(case.state).executing_mutators))

    case.handler_hooks["scene.one"] = nested
    case.registry.dispatch("scene.one", params, case.context)
    assert restored == [(True, True, 1, 1)]
    assert [(event.method, event.mutators, event.plan_mutators) for event in case.handlers] == [
        ("scene.one", 1, 1), ("scene.two", 2, 2),
    ]
    assert case.handlers[0].binding is not case.handlers[1].binding
    assert all(not handler.binding.active for handler in case.handlers)
    assert case.context.handler_entries == 2
    assert_clean(case)


def test_decorator_passes_admission_factory_to_registered_tool(admission: Any) -> None:
    case, callbacks = admission, []

    def factory(context: Any, params: Mapping[str, Any]) -> Any:
        assert context is case.context and params == {"value": 21}

        class Guard:
            def __call__(self) -> None:
                callbacks.append(context.checkpoint_admission)

            def check_after_read(self) -> None:
                pass

        return Guard()

    @case.registry.tool(
        "scene.decorated", modifies=True, toolset="scene_edit",
        checkpoint_admission_factory=factory,
    )
    def handler(context: Any, _params: Mapping[str, Any]) -> dict[str, bool]:
        assert callbacks == [context.checkpoint_admission]
        return {"checked": True}

    spec = case.registry.get("scene.decorated")
    assert spec.handler is handler and spec.checkpoint_admission_factory is factory
    assert case.registry.dispatch("scene.decorated", {"value": 21}, case.context) == {"checked": True}
    assert len(callbacks) == 1 and not callbacks[0].active
    assert_clean(case)


def test_default_context_and_legacy_spec_have_no_admission_requirement(admission: Any) -> None:
    case = admission
    assert case.specs["scene.legacy"].checkpoint_admission_factory is None
    assert case.context.checkpoint_admission is None and case.context.checkpoint_call_id is None
    case.registry.dispatch("scene.legacy", {"value": 22}, case.context)
    assert case.captures == [] and case.checks == []
    assert case.handlers[0].binding is None
    assert case.handlers[0].call_id is not None
    assert case.context.handler_entries == 1
    assert_clean(case)


@pytest.mark.parametrize("before, after", [(True, 1), (1, 1.0), (0.0, -0.0)])
@pytest.mark.parametrize("changed", [False, True])
def test_live_provider_cannot_substitute_equal_values_with_different_types_or_signed_zero(
    admission: Any, before: Any, after: Any, changed: bool,
) -> None:
    case = admission
    params = {"value": {"nested": [before]}}
    mapping_identity, nested_identity = id(params), id(params["value"]["nested"])
    provider_calls = []

    def provider() -> Mapping[str, bool]:
        provider_calls.append(True)
        if len(provider_calls) == 2:
            params["value"]["nested"][0] = after if changed else before
        return dict(case.grants)

    case.context.permissions = case.permissions.PermissionManager(provider)
    case.callback_hooks["scene.one"] = lambda context, _params: context.require(
        case.permissions.Permission.EDIT_SCENE,
    )
    # Python equality alone admits all three substitutions, including signed zero.
    assert before == after
    if changed:
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.dispatch("scene.one", params, case.context)
        assert caught.value.code == case.errors.ErrorCode.NOT_IMPLEMENTED
        assert caught.value.context == {
            "checkpoint_parameters_unchanged": False,
        }
        assert case.handlers == [] and case.context.handler_entries == 0
        assert case.checks[0].binding.stopped is caught.value
    else:
        case.registry.dispatch("scene.one", params, case.context)
        assert len(case.handlers) == case.context.handler_entries == 1
    assert len(provider_calls) == 2
    assert len(case.captures) == len(case.checks) == 1
    assert id(params) == mapping_identity and id(params["value"]["nested"]) == nested_identity
    assert_clean(case)


@pytest.mark.parametrize("before, after", [(True, 1), (1, 1.0), (0.0, -0.0)])
def test_final_request_gate_parameter_change_is_rejected_without_another_provider_call(
    admission: Any, before: Any, after: Any,
) -> None:
    case, provider_calls = admission, []
    params = {"value": [before]}

    def provider() -> Mapping[str, bool]:
        provider_calls.append(True)
        return dict(case.grants)

    def last_gate() -> None:
        if case.checks:
            params["value"][0] = after

    case.context.permissions = case.permissions.PermissionManager(provider)
    case.context.check_final_request = last_gate
    with pytest.raises(case.errors.BridgeError) as caught:
        case.registry.dispatch("scene.one", params, case.context)
    assert caught.value.code == case.errors.ErrorCode.NOT_IMPLEMENTED
    assert caught.value.context == {
        "checkpoint_parameters_unchanged": False,
    }
    assert len(provider_calls) == 1
    assert len(case.captures) == len(case.checks) == 1
    assert case.handlers == [] and case.context.handler_entries == 0
    assert_clean(case)


@pytest.mark.parametrize("rejection", ["changed", "unbounded"])
def test_restored_parameters_cannot_resume_a_call_after_direct_identity_denial(
    admission: Any, rejection: str,
) -> None:
    case, params = admission, {"value": 1}
    spec = case.specs["scene.one"]

    with case.registry.checkpoint_admission(spec, params, case.context) as binding:
        params["value"] = 1.0 if rejection == "changed" else [0] * 4097
        with pytest.raises(case.errors.BridgeError) as first:
            binding()
        assert first.value.context == {
            "checkpoint_parameters_unchanged" if rejection == "changed" else "checkpoint_parameters_bounded": False,
        }
        assert binding.stopped is first.value
        params["value"] = 1
        with pytest.raises(case.errors.BridgeError) as restored:
            binding()
        assert restored.value is first.value
        with pytest.raises(case.errors.BridgeError) as invoked:
            case.registry.invoke(spec, params, case.context)
        assert invoked.value is first.value
        assert case.checks == [] and case.handlers == []
        assert len(case.captures) == 1 and case.context.handler_entries == 0

    assert_clean(case)


def test_initial_bounded_parameter_rejection_retains_known_no_handler_evidence(admission: Any) -> None:
    case, params = admission, {"value": 1}

    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(case.specs["scene.two"], {"value": [0] * 4097}, case.context)
        assert caught.value.context == {"checkpoint_parameters_bounded": False}
        assert case.context.checkpoint_admission is outer and outer.active
        assert case.context.checkpoint_call_id is outer.call_id
        assert case.context.checkpoint_method == "scene.one"
        assert case.context.checkpoint_params is params
        assert len(case.captures) == 1 and case.handlers == []
        assert case.checks == []
        assert case.context.handler_entries == 0
        outer()

    assert_clean(case)


@pytest.mark.parametrize("readonly", ["missing", None, False, 1, "proof"])
def test_guard_without_callable_readonly_proof_is_refused_before_context_replacement(
    admission: Any, readonly: Any,
) -> None:
    case, params, calls = admission, {"value": 1}, []

    class Guard:
        def __call__(self) -> None:
            calls.append("provider-backed guard")

    guard = Guard()
    if readonly != "missing":
        guard.check_after_read = readonly
    spec = case.registry.register(
        "scene.no_readonly", lambda *_: calls.append("handler"),
        modifies=True, toolset="scene_edit",
        checkpoint_admission_factory=lambda *_: guard,
    )
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        assert_invalid(case, lambda: case.registry.invoke(spec, params, case.context),
                       known_not_started=True)
        assert case.context.checkpoint_admission is outer and outer.active
        assert case.context.checkpoint_call_id is outer.call_id
        assert case.context.checkpoint_method == "scene.one"
        assert case.context.checkpoint_params is params
        assert calls == [] and case.context.handler_entries == 0

    assert_clean(case)


def test_readonly_bound_method_is_resolved_once_before_any_live_provider(admission: Any) -> None:
    case, params, stages = admission, {"value": 1}, []

    def provider() -> Mapping[str, bool]:
        stages.append("provider")
        return dict(case.grants)

    case.context.permissions = case.permissions.PermissionManager(provider)

    class Guard:
        @property
        def check_after_read(self) -> Callable[[], None]:
            stages.append("resolve readonly")
            return self.readonly

        def __call__(self) -> None:
            case.context.require(case.permissions.Permission.EDIT_SCENE)

        def readonly(self) -> None:
            stages.append("readonly")

    guard = Guard()
    spec = case.registry.register(
        "scene.resolved_readonly", lambda *_: None, modifies=True,
        checkpoint_admission_factory=lambda *_: guard,
    )
    with case.registry.checkpoint_admission(spec, params, case.context) as binding:
        assert stages == ["resolve readonly"]
        guard.readonly = lambda: stages.append("replacement must not run")
        binding()
        binding.check_after_read()
        binding()
        binding.check_after_read()
        assert stages == ["resolve readonly", "provider", "readonly", "provider", "readonly"]

    assert_clean(case)


def test_native_push_hook_is_resolved_once_and_finishes_with_provider_free_cached_readonly(admission: Any, authority: Any, monkeypatch: Any) -> None:
    case, params, stages = admission, {"value": 1}, []
    actual, expected = [0], [0]

    def provider() -> Mapping[str, bool]:
        stages.append("provider")
        return dict(case.grants)

    case.context.permissions = case.permissions.PermissionManager(provider)

    class Guard:
        @property
        def check_after_read(self) -> Callable[[], None]:
            stages.append("resolve readonly")
            return self.readonly

        @property
        def after_native_push(self) -> Callable[[], None]:
            stages.append("resolve native hook")
            return self.native_hook

        def __call__(self) -> None:
            case.context.require(case.permissions.Permission.EDIT_SCENE)

        def native_hook(self) -> None:
            stages.append("native hook")
            expected[0] = 1

        def readonly(self) -> None:
            stages.append("readonly")
            assert actual == expected
            case.module.check_final_mutation(case.context, "scene.resolved_native_hook")

    guard = Guard()
    spec = case.registry.register("scene.resolved_native_hook", lambda *_: None, modifies=True,
                                  checkpoint_admission_factory=lambda *_: guard)
    push = authority.stack.bpy.ops.ed.undo_push
    def actual_push(**kwargs: Any) -> Any:
        result = push(**kwargs)
        actual[0] = 1
        return result
    monkeypatch.setattr(authority.stack.bpy.ops.ed, "undo_push", actual_push)
    with (case.registry.mutation_entry(spec, params, case.context) as permit,
          case.registry.checkpoint_admission(spec, params, case.context) as binding):
        assert stages == ["resolve readonly", "resolve native hook"]
        guard.native_hook = lambda: stages.append("replacement native hook must not run")
        guard.readonly = lambda: stages.append("replacement readonly must not run")
        with case.registry.native_push_completion(permit, binding, authority.manager, final_check=lambda: None) as consumer:
            assert authority.manager.before_modification(spec.name, before_write=binding,
                after_read=binding.check_after_read, after_native_push=consumer)
        assert stages.count("native hook") == 1
        native_index = stages.index("native hook")
        assert stages[native_index + 1] == "readonly"
        assert all("replacement" not in stage for stage in stages)

    assert_clean(case)


def test_absent_native_push_hook_still_requires_readonly_and_latches_its_denial(admission: Any, authority: Any, monkeypatch: Any) -> None:
    case, params = admission, {"value": 1}
    primary = case.errors.BridgeError(case.errors.ErrorCode.NOT_IMPLEMENTED, "Readonly native completion refused")

    pushed = [False]
    push = authority.stack.bpy.ops.ed.undo_push
    def actual_push(**kwargs: Any) -> Any:
        result = push(**kwargs)
        pushed[0] = True
        return result
    monkeypatch.setattr(authority.stack.bpy.ops.ed, "undo_push", actual_push)
    def deny(_context: Any, _params: Any) -> None:
        if pushed[0]:
            raise primary

    case.readonly_hooks["scene.one"] = deny
    spec = case.specs["scene.one"]
    with (case.registry.mutation_entry(spec, params, case.context) as permit,
          case.registry.checkpoint_admission(spec, params, case.context) as binding):
        assert binding.native_push_callback is None
        with (case.registry.native_push_completion(permit, binding, authority.manager, final_check=lambda: None) as consumer,
              pytest.raises(case.errors.BridgeError) as first):
            authority.manager.before_modification(spec.name, before_write=binding,
                after_read=binding.check_after_read, after_native_push=consumer)
        assert first.value is primary and binding.stopped is primary
        for callback in (binding.after_native_push, binding, binding.check_after_read):
            with pytest.raises(case.errors.BridgeError) as retry:
                callback()
            assert retry.value is primary
        assert case.readonly_checks and all(item is binding for item in case.readonly_checks)
        assert case.handlers == []

    assert_clean(case)


def test_readonly_descriptor_failure_is_bounded_and_preserves_enclosing_context(admission: Any) -> None:
    case, params = admission, {"value": 1}
    runtime = RuntimeError("Private readonly descriptor detail")

    class Guard:
        def __call__(self) -> None:
            raise AssertionError("Provider-backed callback must not be entered")

        @property
        def check_after_read(self) -> Any:
            raise runtime

    spec = case.registry.register(
        "scene.broken_readonly_descriptor", lambda *_: None, modifies=True,
        checkpoint_admission_factory=lambda *_: Guard(),
    )
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as outer:
        with pytest.raises(case.errors.BridgeError) as caught:
            case.registry.invoke(spec, params, case.context)
        assert caught.value.code == case.errors.ErrorCode.OPERATION_FAILED
        assert caught.value.__cause__ is runtime
        assert caught.value.context["execution_started"] is False
        assert caught.value.context["checkpoint_admission_valid"] is False
        assert "Private readonly descriptor detail" not in caught.value.message
        assert case.context.checkpoint_admission is outer and outer.active
        assert case.context.checkpoint_call_id is outer.call_id
        assert case.handlers == case.checks == []
        assert case.readonly_checks == [outer]

    assert_clean(case)


@pytest.mark.parametrize("kind", ["runtime", "bridge"])
def test_readonly_failure_latches_without_falling_back_to_provider_callback(
    admission: Any, kind: str,
) -> None:
    case, params = admission, {"value": 1}
    primary = (RuntimeError("Private readonly failure detail") if kind == "runtime" else
               case.errors.BridgeError(case.errors.ErrorCode.NOT_IMPLEMENTED, "Readonly proof denied"))

    def fail(_context: Any, _params: Any) -> None:
        raise primary

    case.readonly_hooks["scene.one"] = fail
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as binding:
        with pytest.raises(case.errors.BridgeError) as first:
            binding.check_after_read()
        if kind == "bridge":
            assert first.value is primary
        else:
            assert first.value.code == case.errors.ErrorCode.OPERATION_FAILED
            assert first.value.__cause__ is primary
            assert "Private readonly failure detail" not in first.value.message
        assert binding.stopped is first.value
        del case.readonly_hooks["scene.one"]
        for callback in (binding, binding.check_after_read):
            with pytest.raises(case.errors.BridgeError) as retry:
                callback()
            assert retry.value is first.value
        assert case.readonly_checks == [binding]
        assert case.checks == [] and case.handlers == []
        assert [event.phase for event in case.events] == ["capture"]

    assert_clean(case)


@pytest.mark.parametrize("change", ["binding", "call_id", "method", "params_identity", "params_content"])
def test_readonly_context_or_parameter_change_stays_denied_after_restoration(
    admission: Any, change: str,
) -> None:
    case, params = admission, {"value": 1}

    def invalidate(context: Any, raw: Any) -> None:
        if change == "binding":
            context.checkpoint_admission = None
        elif change == "call_id":
            context.checkpoint_call_id = object()
        elif change == "method":
            context.checkpoint_method = "scene.two"
        elif change == "params_identity":
            context.checkpoint_params = dict(raw)
        else:
            raw["value"] = 1.0

    case.readonly_hooks["scene.one"] = invalidate
    with case.registry.checkpoint_admission(case.specs["scene.one"], params, case.context) as binding:
        with pytest.raises(case.errors.BridgeError) as first:
            binding.check_after_read()
        assert first.value.code == case.errors.ErrorCode.NOT_IMPLEMENTED
        assert binding.stopped is first.value
        case.context.checkpoint_admission = binding
        case.context.checkpoint_call_id = binding.call_id
        case.context.checkpoint_method = "scene.one"
        case.context.checkpoint_params = params
        params["value"] = 1
        del case.readonly_hooks["scene.one"]
        for callback in (binding, binding.check_after_read):
            with pytest.raises(case.errors.BridgeError) as retry:
                callback()
            assert retry.value is first.value
        assert case.readonly_checks == [binding]
        assert case.checks == [] and case.handlers == []

    assert_clean(case)


def test_initial_permission_provider_cannot_retarget_the_previously_captured_parameters(admission: Any) -> None:
    case, params, provider_calls, captured_values = admission, {"value": 1}, [], []
    case.factory_hooks["scene.one"] = lambda _context, raw: captured_values.append(raw["value"])

    def provider() -> Mapping[str, bool]:
        provider_calls.append(True)
        if len(provider_calls) == 1:
            params["value"] = 99
        return dict(case.grants)

    case.context.permissions = case.permissions.PermissionManager(provider)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.registry.dispatch("scene.one", params, case.context)
    assert caught.value.code == case.errors.ErrorCode.NOT_IMPLEMENTED
    assert caught.value.context["checkpoint_parameters_unchanged"] is False
    assert "execution_started" not in caught.value.context
    assert params == {"value": 99}
    assert len(provider_calls) == 1
    assert len(case.captures) == 1 and captured_values == [1]
    assert case.checks == case.readonly_checks == []
    assert case.handlers == [] and case.context.handler_entries == 0
    assert_clean(case)
