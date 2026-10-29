"""Guarded checkpoint writes retain recovery evidence across executor failures."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from types import SimpleNamespace as NS
from typing import Any

import pytest
from test_checkpoint_snapshots import NativeStack, Scene


@pytest.fixture
def guarded_executor(addon_package: str, monkeypatch: Any) -> Any:
    checkpoint = importlib.import_module(f"{addon_package}.checkpoints")
    executor_module = importlib.import_module(f"{addon_package}.executor")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    plans = importlib.import_module(f"{addon_package}.task_plans")
    stack = NativeStack()
    monkeypatch.setattr(checkpoint, "require_blender", lambda: stack.bpy)
    manager = checkpoint.CheckpointManager()
    retained_checkpoint = manager.create("Retained earlier checkpoint")
    assert manager.before_modification("earlier.edit")
    stack.scene["value"] = 1
    assert manager.after_modification("earlier.edit")
    registry = registry_module.ToolRegistry(enabled_toolsets=("scene_edit",))
    grants = {item.value: True for item in permission_module.Permission}
    permissions = permission_module.PermissionManager(lambda: dict(grants))
    context = registry_module.ToolContext(state, permissions, registry, manager)
    case = NS(
        checkpoint=checkpoint, executor_module=executor_module,
        registry_module=registry_module, registry=registry, state=state, plans=plans,
        permissions=permissions, context=context, stack=stack, manager=manager,
        retained_checkpoint=retained_checkpoint, static={"profile": "valid"},
        captures=[], checks=[], handlers=[], checkpoint_calls=[], pushes=[],
        guard_hook=None, readonly_hook=None, readonly_checks=[], handler_hook=None,
        denial=checkpoint.BridgeError(
            checkpoint.ErrorCode.NOT_IMPLEMENTED, "Static checkpoint profile changed",
            {"execution_started": False, "static_profile_valid": False},
        ),
    )

    def factory(call_context: Any, params: Mapping[str, Any]) -> Any:
        frozen = tuple(sorted(case.static.items()))
        case.captures.append(NS(context=call_context, params=params, frozen=frozen,
                                previous=call_context.checkpoint_admission))

        class Guard:
            def __call__(self) -> None:
                case.checks.append(call_context.checkpoint_admission)
                if case.guard_hook is not None:
                    case.guard_hook()
                if tuple(sorted(case.static.items())) != frozen:
                    raise case.denial

            def check_after_read(self) -> None:
                method = call_context.checkpoint_method
                case.readonly_checks.append(call_context.checkpoint_admission)
                if case.readonly_hook is not None:
                    case.readonly_hook()
                if tuple(sorted(case.static.items())) != frozen:
                    raise case.denial
                registry_module.check_final_mutation(call_context, method)

        return Guard()

    def handler(call_context: Any, params: Mapping[str, Any]) -> Mapping[str, Any]:
        case.handlers.append(call_context.checkpoint_admission)
        if case.handler_hook is not None:
            return case.handler_hook(call_context, params)
        stack.scene["value"] = params.get("value", 2)
        return {"value": stack.scene["value"]}

    def register(method: str, *, automatic_checkpoint: bool = True) -> Any:
        return registry.register(
            method, handler, modifies=True, toolset="scene_edit",
            permissions=(permission_module.Permission.EDIT_SCENE,),
            automatic_checkpoint=automatic_checkpoint,
            checkpoint_admission_factory=factory,
            checkpoint_batch_reviewed=True,  # Synthetic composition fixture only.
        )

    case.spec = register("scene.guarded")
    case.without_checkpoint = register("scene.without_checkpoint", automatic_checkpoint=False)
    case.outer_spec = register("scene.outer", automatic_checkpoint=False)

    class FixedContextExecutor(executor_module.MainThreadExecutor):
        @property
        def context(self) -> Any:
            return context

    case.executor = FixedContextExecutor(
        command_queue=queue.CommandQueue(), registry=registry, state=state,
        permissions=permissions, checkpoints=manager,
    )

    def spy(name: str) -> None:
        original = getattr(manager, name)

        def observe(*args: Any, **kwargs: Any) -> Any:
            case.checkpoint_calls.append((name, args, kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(manager, name, observe)

    for name in ("before_modification", "after_modification", "finish_editor_session",
                 "_finish_editor_session", "editor_session_status"):
        spy(name)
    push = stack.bpy.ops.ed.undo_push

    def native_push(**kwargs: Any) -> Any:
        case.pushes.append(kwargs)
        return push(**kwargs)

    monkeypatch.setattr(stack.bpy.ops.ed, "undo_push", native_push)
    return case


def assert_context_restored(case: Any) -> None:
    assert case.context.checkpoint_admission is None
    assert case.context.checkpoint_call_id is None
    assert case.context.checkpoint_method is None
    assert case.context.checkpoint_params is None
    assert case.context.checkpoint_finalization_owner is None
    assert case.registry.executing_mutators == 0
    assert case.plans.get_task_plans(case.state).executing_mutators == 0
    assert all(not binding.active for binding in case.checks)


def recovery_records(case: Any) -> tuple[Any, ...]:
    return (case.manager._pending, case.manager._editor_session,
            tuple(case.manager._undo_steps), case.manager.list(),
            case.manager._window.position)


def editor_session(case: Any) -> Any:
    case.stack.scene.session_uid = 11
    case.stack.bpy.context.active_object = NS(name="Existing mesh", session_uid=22)
    case.stack.bpy.context.objects_in_mode = [case.stack.bpy.context.active_object]
    session = case.checkpoint.MeshEditSession(
        case.manager._undo_steps[0], "retained-editor-group", 11, 22, "Existing mesh",
    )
    case.manager._editor_session = session
    return session


def invalidate_from_reader(case: Any, monkeypatch: Any, reader: str) -> None:
    def invalidate() -> None:
        case.static["profile"] = "late reader edit"

    if reader == "marker":
        class Reader(Scene):
            def get(self, key: str, default: Any = None) -> Any:
                value = super().get(key, default)
                if key == case.checkpoint.MARKER_KEY:
                    invalidate()
                return value

        replacement = Reader(case.stack.scene)
        if hasattr(case.stack.scene, "session_uid"):
            replacement.session_uid = case.stack.scene.session_uid
        case.stack.scene = case.stack.bpy.context.scene = replacement
        case.stack.bpy.data.scenes = [replacement]
    else:
        original = case.manager._step_limit

        def preference(blender: Any) -> int | None:
            value = original(blender)
            invalidate()
            return value

        monkeypatch.setattr(case.manager, "_step_limit", preference)


def test_initial_admission_denial_never_enters_checkpoint_or_finalization(guarded_executor: Any) -> None:
    case = guarded_executor
    session = editor_session(case)
    before_records, before_scene, frames = recovery_records(case), dict(case.stack.scene), len(case.stack.frames)

    def deny() -> None:
        raise case.denial

    case.guard_hook = deny
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 3})

    assert caught.value is case.denial
    assert case.handlers == [] and case.context.handler_entries == 0
    assert [name for name, _, _ in case.checkpoint_calls] == ["editor_session_status"]
    assert len(case.checks) == len(case.captures) == 1
    assert case.pushes == [] and len(case.stack.frames) == frames
    assert dict(case.stack.scene) == before_scene
    assert recovery_records(case) == before_records
    assert case.manager._editor_session is session
    assert caught.value.context["undo_group"]["group_id"] == session.group_id
    assert caught.value.context["undo_group"]["state"] == "deferred"
    assert_context_restored(case)


@pytest.mark.parametrize("reader", ["marker", "preferences"])
def test_checkpoint_reader_side_effect_is_rejected_before_native_push(
    guarded_executor: Any, monkeypatch: Any, reader: str,
) -> None:
    case = guarded_executor
    before_records, frames = recovery_records(case), len(case.stack.frames)
    invalidate_from_reader(case, monkeypatch, reader)
    before_scene = dict(case.stack.scene)

    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 4})

    assert caught.value is case.denial
    assert case.static == {"profile": "late reader edit"}
    assert case.handlers == [] and case.context.handler_entries == 0
    assert case.pushes == [] and len(case.stack.frames) == frames
    assert recovery_records(case) == before_records
    evidence = caught.value.context["checkpoint_bookkeeping"]
    assert evidence == {
        "marker_writes_completed": 0 if reader == "marker" else 2,
        "native_snapshots_completed": 0,
        "next_write_rejected": "delete_marker" if reader == "marker" else "native_undo_push",
        "compensation_performed": False,
    }
    if reader == "marker":
        assert dict(case.stack.scene) == before_scene
    else:
        assert dict(case.stack.scene) != before_scene
        assert caught.value.context["possible_mutation"]
        assert caught.value.context["verification_required"]
    assert [name for name, _, _ in case.checkpoint_calls] == [
        "before_modification", "editor_session_status",
    ]
    assert_context_restored(case)


@pytest.mark.parametrize("route", ["after", "finish_editor", "before_with_old_editor"])
@pytest.mark.parametrize("reader", ["marker", "preferences"])
def test_guarded_finalization_denial_retains_pending_and_existing_editor_records(
    guarded_executor: Any, monkeypatch: Any, route: str, reader: str,
) -> None:
    case = guarded_executor
    assert case.manager.before_modification("pending.edit")
    pending = case.manager._pending
    session = editor_session(case)
    params: dict[str, Any] = {}
    before_records, frames = recovery_records(case), len(case.stack.frames)
    case.checkpoint_calls.clear()
    case.pushes.clear()

    with case.registry.checkpoint_admission(case.spec, params, case.context) as binding:
        invalidate_from_reader(case, monkeypatch, reader)

        def gate() -> None:
            binding()
            case.registry_module.check_final_mutation(case.context, case.spec.name)

        with pytest.raises(case.checkpoint.BridgeError) as caught:
            if route == "after":
                case.manager.after_modification("pending.edit", before_write=gate,
                                                after_read=binding.check_after_read)
            elif route == "finish_editor":
                case.manager.finish_editor_session(before_write=gate, after_read=binding.check_after_read)
            else:
                case.manager.before_modification("next.edit", before_write=gate,
                                                 after_read=binding.check_after_read)
        assert caught.value is case.denial
        assert binding.stopped is case.denial
        assert case.manager._pending is pending
        assert case.manager._editor_session is session
        assert recovery_records(case) == before_records
        assert case.pushes == [] and len(case.stack.frames) == frames
        evidence = caught.value.context["checkpoint_bookkeeping"]
        assert evidence["marker_writes_completed"] == (0 if reader == "marker" else 2)
        assert evidence["native_snapshots_completed"] == 0
        assert evidence["next_write_rejected"] == (
            "delete_marker" if reader == "marker" else "native_undo_push"
        )
        assert not evidence["compensation_performed"]

    assert_context_restored(case)


@pytest.mark.parametrize("automatic_checkpoint", [False, True])
def test_secondary_finalization_denial_preserves_primary_tool_bridge_error(
    guarded_executor: Any, automatic_checkpoint: bool,
) -> None:
    case = guarded_executor
    primary = case.checkpoint.BridgeError(
        case.checkpoint.ErrorCode.INVALID_ARGUMENT, "Exact primary tool failure", {"fixture": 17},
    )
    session = editor_session(case) if not automatic_checkpoint else None
    frames = len(case.stack.frames)
    before_steps = tuple(case.manager._undo_steps)

    def failed_writer(_context: Any, _params: Any) -> Any:
        case.stack.scene["value"] = 9
        case.static["profile"] = "manual edit while writer unwound"
        raise primary

    case.handler_hook = failed_writer
    method = "scene.guarded" if automatic_checkpoint else "scene.without_checkpoint"
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch(method, {"value": 9})

    assert caught.value is primary
    assert primary.code == "INVALID_ARGUMENT" and primary.message == "Exact primary tool failure"
    assert primary.context["fixture"] == 17
    assert primary.context["checkpoint_finalization_refused"] == {
        "code": "NOT_IMPLEMENTED",
        "bookkeeping": {
            "marker_writes_completed": 0, "native_snapshots_completed": 0,
            "next_write_rejected": "delete_marker", "compensation_performed": False,
        },
        "primary_error_preserved": True,
    }
    assert case.stack.scene["value"] == 9
    assert case.static["profile"] == "manual edit while writer unwound"
    assert len(case.handlers) == case.context.handler_entries == 1
    assert tuple(case.manager._undo_steps) == before_steps
    if automatic_checkpoint:
        assert case.manager._pending is not None
        assert len(case.stack.frames) == frames + 1 and len(case.pushes) == 1
        assert primary.context["execution_started"] and primary.context["verification_required"]
    else:
        assert case.manager._editor_session is session
        assert primary.context["undo_group"]["state"] == "deferred"
        assert len(case.stack.frames) == frames and case.pushes == []
    assert_context_restored(case)


def test_successful_writer_then_finalization_denial_keeps_truthful_execution_evidence(
    guarded_executor: Any,
) -> None:
    case = guarded_executor
    frames, before_steps = len(case.stack.frames), tuple(case.manager._undo_steps)

    def writer(_context: Any, _params: Any) -> Mapping[str, Any]:
        case.stack.scene["value"] = 10
        case.static["profile"] = "late protected change"
        return {"value": 10}

    case.handler_hook = writer
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 10})

    assert caught.value is case.denial
    assert case.stack.scene["value"] == 10
    assert len(case.handlers) == case.context.handler_entries == 1
    assert case.manager._pending is not None
    assert tuple(case.manager._undo_steps) == before_steps
    assert len(case.stack.frames) == frames + 1 and len(case.pushes) == 1
    assert caught.value.context["execution_started"]
    assert caught.value.context["possible_mutation"]
    assert caught.value.context["verification_required"]
    assert caught.value.context.get("requested_edit_started") is not False
    assert caught.value.context["undo_boundary_finalized"] is False
    assert_context_restored(case)


@pytest.mark.parametrize("automatic_checkpoint", [False, True])
def test_known_no_execution_handler_rejection_only_reads_old_editor_status(
    guarded_executor: Any, automatic_checkpoint: bool,
) -> None:
    case = guarded_executor
    session = editor_session(case)
    if automatic_checkpoint:
        case.stack.bpy.context.mode = "EDIT_MESH"
    primary = case.checkpoint.BridgeError(
        case.checkpoint.ErrorCode.NOT_IMPLEMENTED, "Guarded handler refused before edit",
        {"execution_started": False},
    )
    frames, before_steps, value = len(case.stack.frames), tuple(case.manager._undo_steps), case.stack.scene["value"]

    def rejected(_context: Any, _params: Any) -> Any:
        raise primary

    case.handler_hook = rejected
    method = "scene.guarded" if automatic_checkpoint else "scene.without_checkpoint"
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch(method, {"value": 11})

    assert caught.value is primary
    assert caught.value.context["execution_started"] is False
    assert case.manager._editor_session is session
    assert caught.value.context["undo_group"]["state"] == "deferred"
    assert caught.value.context["undo_group"]["group_id"] == session.group_id
    assert tuple(case.manager._undo_steps) == before_steps
    assert len(case.stack.frames) == frames and case.pushes == []
    assert case.stack.scene["value"] == value
    assert len(case.handlers) == case.context.handler_entries == 1
    assert [name for name, _, _ in case.checkpoint_calls] == (
        ["before_modification", "editor_session_status"] if automatic_checkpoint else
        ["editor_session_status"]
    )
    assert_context_restored(case)


@pytest.mark.parametrize("outcome", ["success", "admission", "bridge", "runtime"])
def test_executor_restores_enclosing_admission_on_every_exit(guarded_executor: Any, outcome: str) -> None:
    case = guarded_executor
    outer_params = {"scope": "outer"}
    primary = case.checkpoint.BridgeError(case.checkpoint.ErrorCode.INVALID_ARGUMENT, "Tool refused")

    def deny() -> None:
        raise case.denial

    def failed(_context: Any, _params: Any) -> Any:
        if outcome == "bridge":
            raise primary
        raise RuntimeError("Native-shaped handler failed")

    with case.registry.checkpoint_admission(case.outer_spec, outer_params, case.context) as outer:
        finalization_owner = object()
        case.context.checkpoint_finalization_owner = finalization_owner
        if outcome == "admission":
            case.guard_hook = deny
        elif outcome in {"bridge", "runtime"}:
            case.handler_hook = failed
        if outcome == "success":
            result = case.executor.dispatch("scene.guarded", {"value": 12})
            assert result["value"] == 12
            assert result["operation"]["undo_boundary_finalized"]
        else:
            with pytest.raises(case.checkpoint.BridgeError) as caught:
                case.executor.dispatch("scene.guarded", {"value": 12})
            if outcome == "admission":
                assert caught.value is case.denial
            elif outcome == "bridge":
                assert caught.value is primary
            else:
                assert caught.value.code == "OPERATION_FAILED"
                assert isinstance(caught.value.__cause__, RuntimeError)
        assert case.context.checkpoint_admission is outer and outer.active
        assert case.context.checkpoint_call_id is outer.call_id
        assert case.context.checkpoint_method == case.outer_spec.name
        assert case.context.checkpoint_params is outer_params
        assert case.context.checkpoint_finalization_owner is finalization_owner
        assert case.registry.executing_mutators == 0
        assert case.plans.get_task_plans(case.state).executing_mutators == 0
        assert all(not binding.active for binding in case.checks)
        assert case.captures[-1].previous is outer
        case.guard_hook = None
        outer()

    assert_context_restored(case)


@pytest.mark.parametrize("loss", ["parameters", "unbounded_parameters", "call_id"])
def test_partial_handler_edit_then_binding_denial_retains_primary_and_mutation_evidence(
    guarded_executor: Any, loss: str,
) -> None:
    case = guarded_executor
    frames, before_steps = len(case.stack.frames), tuple(case.manager._undo_steps)
    primary_errors = []

    def partial_writer(context: Any, params: Any) -> Any:
        binding = context.checkpoint_admission
        case.stack.scene["value"] = 13
        if loss == "parameters":
            params["value"] = 13.0
        elif loss == "unbounded_parameters":
            params["value"] = [0] * 4097
        else:
            context.checkpoint_call_id = object()
        try:
            case.registry_module.check_final_mutation(context, "scene.guarded")
        except case.checkpoint.BridgeError as error:
            primary_errors.append((error, dict(error.context), binding))
            raise
        raise AssertionError("Lost binding unexpectedly admitted the next write")

    case.handler_hook = partial_writer
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 13})

    primary, initial_context, binding = primary_errors[0]
    assert caught.value is primary and primary.code == "NOT_IMPLEMENTED"
    assert initial_context == {
        {"parameters": "checkpoint_parameters_unchanged",
         "unbounded_parameters": "checkpoint_parameters_bounded",
         "call_id": "checkpoint_admission_valid"}[loss]: False,
    }
    assert binding.stopped is primary
    assert primary.context["execution_started"] is True
    assert primary.context["possible_mutation"] is True
    assert primary.context["verification_required"] is True
    assert primary.context["checkpoint_finalization_refused"] == {
        "code": "NOT_IMPLEMENTED",
        "bookkeeping": {
            "marker_writes_completed": 0, "native_snapshots_completed": 0,
            "next_write_rejected": "delete_marker", "compensation_performed": False,
        },
        "primary_error_preserved": True,
    }
    assert case.stack.scene["value"] == 13
    assert len(case.handlers) == case.context.handler_entries == 1
    assert case.manager._pending is not None
    assert tuple(case.manager._undo_steps) == before_steps
    assert len(case.stack.frames) == frames + 1 and len(case.pushes) == 1
    assert case.pushes[0]["message"] == "Codex Before: scene.guarded"
    assert [name for name, _, _ in case.checkpoint_calls] == [
        "before_modification", "after_modification", "editor_session_status",
    ]
    assert_context_restored(case)


@pytest.mark.parametrize("stage", ["first_marker", "after_checkpoint", "old_editor"])
def test_one_shot_runtime_provider_failure_stops_checkpoint_writes_and_retains_recovery(
    guarded_executor: Any, stage: str,
) -> None:
    case = guarded_executor
    session = editor_session(case) if stage == "old_editor" else None
    before_steps, checkpoints = tuple(case.manager._undo_steps), case.manager.list()
    frames, position, before_scene = len(case.stack.frames), case.manager._window.position, dict(case.stack.scene)
    provider_state = {"armed": False, "raised": False, "after_handler": False, "failed_call": 0}
    provider_calls = []
    runtime = RuntimeError("Private provider failure detail")

    # Use the real coherent-grant reader while allowing its source to fail once.
    permissions_module = importlib.import_module(case.permissions.__module__)

    def source() -> Mapping[str, bool]:
        provider_calls.append(True)
        if provider_state["armed"] and not provider_state["raised"]:
            provider_state["raised"] = True
            provider_state["failed_call"] = len(provider_calls)
            raise runtime
        return {permission.value: True for permission in permissions_module.Permission}

    case.context.permissions = permissions_module.PermissionManager(source)
    case.guard_hook = lambda: case.context.require(permissions_module.Permission.EDIT_SCENE)

    class Reader(Scene):
        def get(self, key: str, default: Any = None) -> Any:
            value = super().get(key, default)
            if key == case.checkpoint.MARKER_KEY and (
                stage != "after_checkpoint" or provider_state["after_handler"]
            ):
                provider_state["armed"] = True
            return value

    replacement = Reader(case.stack.scene)
    if hasattr(case.stack.scene, "session_uid"):
        replacement.session_uid = case.stack.scene.session_uid
    case.stack.scene = case.stack.bpy.context.scene = replacement
    case.stack.bpy.data.scenes = [replacement]

    if stage == "after_checkpoint":
        def writer(_context: Any, _params: Any) -> Mapping[str, Any]:
            case.stack.scene["value"] = 14
            provider_state["after_handler"] = True
            return {"value": 14}

        case.handler_hook = writer

    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 14})

    error = caught.value
    assert error.code == "OPERATION_FAILED" and error.__cause__ is runtime
    assert error.context["checkpoint_admission_valid"] is False
    assert error.context["verification_required"] is True
    assert "Private provider failure detail" not in error.message
    assert provider_state["raised"]
    assert len(provider_calls) == provider_state["failed_call"]
    binding = case.checks[-1]
    assert binding.stopped is error
    assert error.context["checkpoint_bookkeeping"] == {
        "marker_writes_completed": 0, "native_snapshots_completed": 0,
        "next_write_rejected": "delete_marker", "compensation_performed": False,
    }
    assert tuple(case.manager._undo_steps) == before_steps
    assert case.manager.list() == checkpoints
    assert case.manager._editor_session is session
    if stage == "after_checkpoint":
        assert case.stack.scene["value"] == 14
        assert len(case.handlers) == case.context.handler_entries == 1
        assert case.manager._pending is not None
        assert len(case.stack.frames) == frames + 1 and len(case.pushes) == 1
        assert case.manager._window.position == position + 1
        assert error.context["execution_started"] is True
        assert error.context["possible_mutation"] is True
    else:
        assert dict(case.stack.scene) == before_scene
        assert case.handlers == [] and case.context.handler_entries == 0
        assert case.manager._pending is None
        assert len(case.stack.frames) == frames and case.pushes == []
        assert case.manager._window.position == position
    # Its provider would now grant access again. The stopped call must not read
    # that provider or create any marker/snapshot while unwinding or retried.
    calls, after_records, after_scene = len(provider_calls), recovery_records(case), dict(case.stack.scene)
    with pytest.raises(case.checkpoint.BridgeError) as retry:
        binding()
    assert retry.value is error
    assert len(provider_calls) == calls
    assert recovery_records(case) == after_records and dict(case.stack.scene) == after_scene
    assert_context_restored(case)


@pytest.mark.parametrize("write", ["delete_marker", "native_undo_push"])
def test_readonly_proof_rejects_static_change_from_marker_cas_after_last_provider(
    guarded_executor: Any, monkeypatch: Any, write: str,
) -> None:
    case = guarded_executor
    before_records, frames = recovery_records(case), len(case.stack.frames)
    trace = []
    armed = {"reader": False, "native_push_provider": False}
    permissions_module = importlib.import_module(case.permissions.__module__)

    def provider() -> Mapping[str, bool]:
        trace.append("provider")
        return {permission.value: True for permission in permissions_module.Permission}

    case.context.permissions = permissions_module.PermissionManager(provider)

    def last_provider() -> None:
        case.context.require(permissions_module.Permission.EDIT_SCENE)
        if ((write == "delete_marker" and len(case.checks) == 2)
                or (write == "native_undo_push" and armed["native_push_provider"])):
            armed["reader"] = True

    case.guard_hook = last_provider
    case.readonly_hook = lambda: trace.append("readonly proof")

    class Reader(Scene):
        def get(self, key: str, default: Any = None) -> Any:
            value = super().get(key, default)
            if key == case.checkpoint.MARKER_KEY and armed["reader"]:
                armed["reader"] = False
                trace.append("CAS reader changed static state")
                case.static["profile"] = "late CAS reader edit"
            return value

    replacement = Reader(case.stack.scene)
    case.stack.scene = case.stack.bpy.context.scene = replacement
    case.stack.bpy.data.scenes = [replacement]
    before_scene = dict(replacement)
    if write == "native_undo_push":
        original = case.manager._step_limit

        def preference(blender: Any) -> int | None:
            value = original(blender)
            armed["native_push_provider"] = True
            return value

        monkeypatch.setattr(case.manager, "_step_limit", preference)

    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 15})

    assert caught.value is case.denial
    assert trace[-2:] == ["CAS reader changed static state", "readonly proof"]
    assert case.static == {"profile": "late CAS reader edit"}
    assert case.readonly_checks
    assert case.readonly_checks[-1].stopped is caught.value
    assert case.handlers == [] and case.context.handler_entries == 0
    assert case.pushes == [] and len(case.stack.frames) == frames
    assert recovery_records(case) == before_records
    assert caught.value.context["checkpoint_bookkeeping"] == {
        "marker_writes_completed": 0 if write == "delete_marker" else 2,
        "native_snapshots_completed": 0, "next_write_rejected": write,
        "compensation_performed": False,
    }
    if write == "delete_marker":
        assert dict(case.stack.scene) == before_scene
    else:
        assert dict(case.stack.scene) != before_scene
        assert caught.value.context["possible_mutation"] is True
    assert_context_restored(case)


def test_executor_detects_all_admission_metadata_cleared_after_before_checkpoint(
    guarded_executor: Any,
) -> None:
    case = guarded_executor
    protocol = importlib.import_module(f"{case.executor_module.__package__}.protocol")
    request = protocol.Request(id="clear-after-before", method="scene.guarded", params={"value": 16})
    frames, before_steps, checkpoints = len(case.stack.frames), tuple(case.manager._undo_steps), case.manager.list()
    callbacks = []

    def after_before() -> None:
        callbacks.append(True)
        if len(callbacks) == 2:
            case.context.checkpoint_admission = None
            case.context.checkpoint_call_id = None
            case.context.checkpoint_method = None
            case.context.checkpoint_params = None
            case.context.checkpoint_finalization_owner = None
            case.static["profile"] = "protected edit after BEFORE"

    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor._invoke(request, check_cancelled=after_before)

    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["checkpoint_admission_valid"] is False
    assert caught.value.context["requested_edit_started"] is False
    assert caught.value.context["execution_started"] is True
    assert caught.value.context["checkpoint_bookkeeping_changed"] is True
    assert case.static == {"profile": "protected edit after BEFORE"}
    assert len(callbacks) == 2 and len(case.captures) == 1
    assert case.handlers == [] and case.context.handler_entries == 0
    assert case.checks[0].stopped is caught.value
    assert case.manager._pending is not None
    assert tuple(case.manager._undo_steps) == before_steps and case.manager.list() == checkpoints
    assert len(case.stack.frames) == frames + 1 and len(case.pushes) == 1
    assert case.pushes[0]["message"] == "Codex Before: scene.guarded"
    assert [name for name, _, _ in case.checkpoint_calls] == [
        "before_modification", "editor_session_status",
    ]
    assert_context_restored(case)


def test_nested_dispatch_provider_cannot_adopt_changed_parent_static_state(
    guarded_executor: Any,
) -> None:
    case = guarded_executor
    permissions_module = importlib.import_module(case.permissions.__module__)
    phase, provider_calls = {"child": False}, []
    frames, before_steps = len(case.stack.frames), tuple(case.manager._undo_steps)

    def provider() -> Mapping[str, bool]:
        provider_calls.append(True)
        if phase["child"]:
            case.static["profile"] = "child provider changed protected state"
        return {permission.value: True for permission in permissions_module.Permission}

    case.context.permissions = permissions_module.PermissionManager(provider)

    def parent(context: Any, _params: Any) -> Mapping[str, Any]:
        phase["child"] = True
        return case.registry.dispatch("scene.without_checkpoint", {"value": 17}, context)

    case.handler_hook = parent
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.guarded", {"value": 17})

    assert caught.value is case.denial
    assert case.static == {"profile": "child provider changed protected state"}
    assert len(provider_calls) == 2
    assert len(case.captures) == 2
    assert case.captures[1].previous is case.handlers[0]
    assert case.captures[0].frozen == case.captures[1].frozen == (("profile", "valid"),)
    assert len(case.handlers) == case.context.handler_entries == 1
    assert case.handlers[0].method == "scene.guarded"
    assert case.handlers[0].stopped is caught.value
    assert case.manager._pending is not None
    assert tuple(case.manager._undo_steps) == before_steps
    assert len(case.stack.frames) == frames + 1 and len(case.pushes) == 1
    assert case.stack.scene["value"] == 1
    assert_context_restored(case)


def test_executor_first_permission_provider_cannot_retarget_the_previously_captured_parameters(
    guarded_executor: Any,
) -> None:
    case = guarded_executor
    protocol = importlib.import_module(f"{case.executor_module.__package__}.protocol")
    permissions_module = importlib.import_module(case.permissions.__module__)
    request = protocol.Request(id="retarget-at-entry", method="scene.guarded", params={"value": 1})
    before_records, before_scene, frames = recovery_records(case), dict(case.stack.scene), len(case.stack.frames)
    provider_calls, captured_values = [], []
    factory = case.spec.checkpoint_admission_factory
    from dataclasses import replace

    def capture(context: Any, params: Mapping[str, Any]) -> Any:
        captured_values.append(params["value"])
        return factory(context, params)

    case.registry._tools[case.spec.name] = replace(case.spec, checkpoint_admission_factory=capture)

    def provider() -> Mapping[str, bool]:
        provider_calls.append(True)
        if len(provider_calls) == 1:
            request.params["value"] = 99
        return {permission.value: True for permission in permissions_module.Permission}

    case.context.permissions = permissions_module.PermissionManager(provider)
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor._invoke(request)

    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["checkpoint_parameters_unchanged"] is False
    assert "execution_started" not in caught.value.context
    assert request.params == {"value": 99}
    assert len(provider_calls) == 1
    assert len(case.captures) == 1 and captured_values == [1]
    assert case.captures[0].frozen == (("profile", "valid"),)
    assert case.checks == case.readonly_checks == []
    assert case.handlers == [] and case.context.handler_entries == 0
    assert [name for name, _, _ in case.checkpoint_calls] == ["editor_session_status"]
    assert case.pushes == []
    assert len(case.stack.frames) == frames and dict(case.stack.scene) == before_scene
    assert recovery_records(case) == before_records
    assert_context_restored(case)


def test_failed_editor_finalization_is_not_retried_or_its_measured_receipt_overwritten(
    guarded_executor: Any, monkeypatch: Any,
) -> None:
    case = guarded_executor
    session = editor_session(case)
    before_records, frames = recovery_records(case), len(case.stack.frames)
    before_marker = case.stack.scene[case.checkpoint.MARKER_KEY]
    receipts = []
    original = case.checkpoint._CheckpointGuard._run

    def observe(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return original(self, *args, **kwargs)
        except case.checkpoint.BridgeError as error:
            receipts.append((error, dict(error.context["checkpoint_bookkeeping"])))
            raise

    monkeypatch.setattr(case.checkpoint._CheckpointGuard, "_run", observe)

    def fail_after_markers() -> None:
        # Handler admission, delete marker and set marker have passed. The
        # fourth live check is the first attempt to push this editor snapshot.
        if len(case.checks) == 4:
            case.static["profile"] = "deny after two marker writes"

    case.guard_hook = fail_after_markers
    with pytest.raises(case.checkpoint.BridgeError) as caught:
        case.executor.dispatch("scene.without_checkpoint", {"value": 9})

    expected = {
        "marker_writes_completed": 2, "native_snapshots_completed": 0,
        "next_write_rejected": "native_undo_push", "compensation_performed": False,
    }
    assert caught.value is case.denial
    assert receipts == [(caught.value, expected)]
    assert caught.value.context["checkpoint_bookkeeping"] == expected
    assert caught.value.context["execution_started"] is True
    assert caught.value.context["possible_mutation"] is True
    assert caught.value.context["checkpoint_authority_rejected"] is True
    assert caught.value.context["undo_group"]["state"] == "deferred"
    assert caught.value.context["undo_group"]["group_id"] == session.group_id
    assert case.stack.scene["value"] == 9
    assert case.stack.scene[case.checkpoint.MARKER_KEY] != before_marker
    assert case.manager._editor_session is session
    assert recovery_records(case) == before_records
    assert len(case.handlers) == case.context.handler_entries == 1
    assert len(case.stack.frames) == frames and case.pushes == []
    names = [name for name, _, _ in case.checkpoint_calls]
    assert names.count("finish_editor_session") == 1
    assert "before_modification" not in names and "after_modification" not in names
    assert_context_restored(case)


def test_guarded_batch_outer_executor_only_reads_old_editor_status_after_child_scope_closes(
    guarded_executor: Any,
) -> None:
    case = guarded_executor
    batch = importlib.import_module(f"{case.executor_module.__package__}.tools.batch")
    batch.register_tools(case.registry)
    case.registry.enable_toolset("batch")
    session = editor_session(case)
    case.stack.bpy.context.mode = "EDIT_MESH"
    frames, before_steps, attempts = len(case.stack.frames), tuple(case.manager._undo_steps), session.attempts

    def child_returns_to_object_mode(_context: Any, _params: Any) -> Mapping[str, Any]:
        case.stack.scene["value"] = 10
        case.stack.bpy.context.mode = "OBJECT"
        return {"value": 10}

    case.handler_hook = child_returns_to_object_mode
    result = case.executor.dispatch("batch.execute", {
        "label": "Guarded deferred edit",
        "steps": [{"method": "scene.guarded", "params": {"value": 10}}],
    })

    assert result["completed_steps"] == 1
    assert result["operation"]["undo_group"]["state"] == "deferred"
    assert result["operation"]["undo_group"]["group_id"] == session.group_id
    assert result["operation"]["undo_boundary_finalized"] is False
    assert case.stack.bpy.context.mode == "OBJECT"
    assert case.stack.scene["value"] == 10
    assert case.manager._editor_session is session and session.attempts == attempts + 1
    assert tuple(case.manager._undo_steps) == before_steps
    assert case.manager._pending is None
    assert len(case.stack.frames) == frames and case.pushes == []
    assert len(case.captures) == len(case.handlers) == 1
    assert case.context.handler_entries == 2  # Outer batch and its single child.
    assert not case.handlers[0].active
    assert [name for name, _, _ in case.checkpoint_calls] == [
        "before_modification", "editor_session_status",
    ]
    assert_context_restored(case)


@pytest.mark.parametrize("stage", ("first_provider", "after_child", "after_batch"))
@pytest.mark.parametrize("loss", ("clear", "wrong", "delete", "all_slots"))
def test_guarded_batch_finalization_owner_loss_never_enables_legacy_native_finish(
    guarded_executor: Any, stage: str, loss: str,
) -> None:
    from dataclasses import replace
    case = guarded_executor
    batch = importlib.import_module(f"{case.executor_module.__package__}.tools.batch")
    batch.register_tools(case.registry)
    case.registry.enable_toolset("batch")
    session = editor_session(case)
    case.stack.bpy.context.mode = "EDIT_MESH"
    frames, steps = len(case.stack.frames), tuple(case.manager._undo_steps)
    fired = []

    def lose() -> None:
        if fired:
            return
        fired.append(True)
        if loss == "delete":
            del case.context.checkpoint_finalization_owner
        elif loss == "all_slots":
            for name in ("checkpoint_admission", "checkpoint_call_id", "checkpoint_method", "checkpoint_params", "checkpoint_finalization_owner"):
                setattr(case.context, name, None)
        else:
            case.context.checkpoint_finalization_owner = object() if loss == "wrong" else None

    def child(_context: Any, _params: Any) -> Mapping[str, Any]:
        case.stack.scene["value"] = 10
        case.stack.bpy.context.mode = "OBJECT"
        return {"value": 10}

    case.handler_hook = child
    if stage == "first_provider":
        permission = importlib.import_module(f"{case.executor_module.__package__}.permissions")
        def provider() -> dict[str, bool]:
            if getattr(case.context, "checkpoint_finalization_owner", None) is not None:
                lose()
            return {item.value: True for item in permission.Permission}
        case.context.permissions = permission.PermissionManager(provider)
    elif stage == "after_child":
        case.guard_hook = lambda: lose() if case.handlers else None
    else:
        original = case.registry.get("batch.execute")
        def after_batch(context: Any, params: Any) -> Any:
            result = original.handler(context, params)
            lose()
            return result
        case.registry._tools[original.name] = replace(original, handler=after_batch)

    with pytest.raises(case.checkpoint.BridgeError):
        case.executor.dispatch("batch.execute", {"steps": [{"method": "scene.guarded", "params": {"value": 10}}]})
    assert fired == [True]
    assert len(case.stack.frames) == frames and case.pushes == []
    assert case.manager._editor_session is session and tuple(case.manager._undo_steps) == steps
    assert all(name not in {"finish_editor_session", "after_modification"} for name, _, _ in case.checkpoint_calls)
    assert len(case.handlers) == (0 if stage == "first_provider" else 1)
    assert_context_restored(case)


def test_glb_executor_context_carries_runtime_owned_service_before_provider_entry(addon_package, monkeypatch):
    runtime_module = importlib.import_module(f"{addon_package}.runtime")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    owner = runtime_module.BridgeRuntime()
    owner._registered = True
    monkeypatch.setattr(runtime_module, "_RUNTIME", owner)
    owner.registry.enable_toolset("asset_delivery")
    context = owner.executor.context
    context.request_lifecycle = lifecycle.RequestLifetime(connection=lifecycle.ConnectionLifetime())
    context.glb_method = "asset.glb_stage_preview"
    service = context.glb_stage
    assert service is owner.glb_stage is owner._glb_stage_origin
    owner.glb_stage = object()
    with pytest.raises(runtime_module.BridgeError) as failure:
        service.check_context(context, context.request_lifecycle.connection, service._generation)
    assert failure.value.context["reason"] == "GLB_RUNTIME_SERVICE_OR_SESSION_CHANGED"
    assert owner.executor.glb_stage is owner._glb_stage_origin
    assert not service.store._records


@pytest.mark.parametrize("route", ["request", "job_context_factory"])
def test_glb_context_getter_origin_checked_before_foreign_callback(addon_package, monkeypatch, route):
    runtime_module = importlib.import_module(f"{addon_package}.runtime")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    owner = runtime_module.BridgeRuntime()
    owner._registered = True
    monkeypatch.setattr(runtime_module, "_RUNTIME", owner)
    callbacks = []

    def foreign_context(_executor):
        callbacks.append("FOREIGN_CONTEXT_GETTER")
        raise AssertionError("foreign context getter ran before source guard")

    monkeypatch.setattr(type(owner.executor), "context", property(foreign_context))
    with pytest.raises(runtime_module.BridgeError) as failure:
        if route == "request":
            owner.executor._invoke(protocol.Request(id="factory-origin-model", method="scene.inspect", params={}))
        else:
            owner.jobs.context_factory()
    assert failure.value.context["reason"] == "GLB_CANONICAL_CONTEXT_FACTORY_CHANGED"
    assert callbacks == []


def test_glb_context_slot_shadow_rejected_before_context_constructor_callback(addon_package, monkeypatch):
    runtime_module = importlib.import_module(f"{addon_package}.runtime")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    owner = runtime_module.BridgeRuntime()
    owner._registered = True
    monkeypatch.setattr(runtime_module, "_RUNTIME", owner)
    callbacks = []

    def foreign_slot(_context, _value):
        callbacks.append("FOREIGN_CONTEXT_SLOT")
        raise AssertionError("foreign context slot invoked")

    monkeypatch.setattr(registry_module.ToolContext, "state", property(lambda _context: None, foreign_slot))
    with pytest.raises(runtime_module.BridgeError):
        owner.jobs.context_factory()
    assert callbacks == []


@pytest.mark.parametrize("method", ["asset.glb_stage_create_start", "asset.glb_stage_publish_start"])
def test_glb_denied_start_grants_precede_native_marker_capture(addon_package, monkeypatch, method):
    runtime_module = importlib.import_module(f"{addon_package}.runtime")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    owner = runtime_module.BridgeRuntime()
    owner._registered = True
    monkeypatch.setattr(runtime_module, "_RUNTIME", owner)
    owner.registry.enable_toolset("asset_delivery")
    context = owner.executor.context
    context.request_lifecycle = lifecycle.RequestLifetime(connection=lifecycle.ConnectionLifetime())
    markers = []

    def forbidden_marker():
        markers.append("NATIVE_MARKER_CAPTURE")
        pytest.fail("missing GLB grants reached native checkpoint markers")

    monkeypatch.setattr(owner.checkpoints, "capture_job_markers", forbidden_marker)
    spec, params = owner.registry.get(method), {}
    with owner.registry.mutation_entry(spec, params, context), pytest.raises(runtime_module.BridgeError) as failure:
        spec.checkpoint_admission_factory(context, params)
    assert failure.value.code == runtime_module.ErrorCode.PERMISSION_DENIED.value
    assert markers == [] and owner.jobs.active is None
