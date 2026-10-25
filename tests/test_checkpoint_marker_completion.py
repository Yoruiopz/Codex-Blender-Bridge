"""Marker observations require actual canonical writes, not token-shaped values."""

from __future__ import annotations

from copy import copy, deepcopy
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_completion_auth import authorized, before, completion_env

assert completion_env  # Reuse the registered, invocation-bound portable fixture.


@pytest.fixture
def markers(completion_env):
    env = completion_env
    env.stack.scene.session_uid = 10
    env.stack.scene.as_pointer = lambda: 101
    env.expected = env.manager._marker_evidence(env.stack.bpy)
    env.marker_events, env.marker_evidence = [], []
    env.marker_hook = None
    original_read = env.guard.check_after_read

    def readonly():
        original_read()
        if env.manager._marker_evidence(env.stack.bpy) != env.expected:
            raise env.error("NOT_IMPLEMENTED", "Marker inventory changed outside canonical writes")

    def completed(event):
        predicted = env.completion.claim_marker_write_completion(env.context, env.spec.name, env.guard, event)
        env.marker_events.append(event)
        env.marker_evidence.append(predicted)
        env.expected = predicted
        if env.marker_hook is not None:
            env.marker_hook(event, predicted)

    env.guard.check_after_read = readonly
    env.guard.after_marker_write = completed
    return env


def test_edit_mode_delivers_exact_predicted_inventory_before_readonly_proof_without_native_push(markers):
    env = markers
    env.stack.bpy.context.mode = "EDIT_MESH"
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer) is False
        assert len(env.marker_events) == 1
        assert env.marker_evidence == [env.manager._marker_evidence(env.stack.bpy)]
        token = env.marker_evidence[0][1][0][-1]
        assert env.checkpoints.TOKEN_PATTERN.fullmatch(token)
        assert env.marker_evidence[0] == ((101, 10), (((101, 10), None, None, True, True, token),))
        assert len(env.stack.frames) == 1 and env.completed == []
        assert not hasattr(env.marker_events[0], "__dict__")
        assert env.manager._pending is None


def test_all_actual_deletes_and_sets_get_distinct_receipts_without_replacing_native_push(markers):
    env = markers
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer)
        assert len(env.marker_events) == 3 and len({id(event) for event in env.marker_events}) == 3
        assert [item[1][0][-2] for item in env.marker_evidence] == [True, False, True]
        assert env.completed == [(2, 1)]
        assert env.expected == env.manager._marker_evidence(env.stack.bpy)


@pytest.mark.parametrize("event", [None, object(), "BCB1:" + "a" * 32 + ":" + "b" * 32])
def test_forged_binding_receipt_latches_before_any_marker_write(markers, event):
    env = markers
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            binding.after_marker_write(event)
        with pytest.raises(env.error) as retry:
            before(env, binding, consumer)
        assert retry.value is caught.value and env.marker_events == []
        assert env.checkpoints.MARKER_KEY not in env.stack.scene


@pytest.mark.parametrize("duplicate", [copy, deepcopy])
def test_copied_event_is_not_a_receipt_and_failure_is_sticky(markers, duplicate):
    env = markers
    def copied_first_claim(event):
        env.marker_events.append(event)
        env.completion.claim_marker_write_completion(env.context, env.spec.name, env.guard, duplicate(event))
    env.guard.after_marker_write = copied_first_claim
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        assert caught.value.context["marker_write_completion_valid"] is False
        assert caught.value.context["checkpoint_bookkeeping"]["marker_writes_completed"] == 1
        with pytest.raises(env.error) as retry:
            before(env, binding, consumer)
        assert retry.value is caught.value and len(env.marker_events) == 1
        assert len(env.stack.frames) == 1


def test_consumed_receipt_cannot_replay_inside_or_after_manager_call(markers):
    env = markers
    env.stack.bpy.context.mode = "EDIT_MESH"
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer) is False
        with pytest.raises(env.error) as caught:
            binding.after_marker_write(env.marker_events[0])
        with pytest.raises(env.error) as retry:
            before(env, binding, consumer)
        assert retry.value is caught.value
    with pytest.raises(env.error):
        env.guard.after_marker_write(env.marker_events[0])


@pytest.mark.parametrize("wrong", ["context", "method", "owner", "binding"])
def test_wrong_claim_source_refuses_and_stops_later_writes(markers, monkeypatch, wrong):
    env = markers
    if wrong == "binding":
        monkeypatch.setattr(env.registry_module.CheckpointAdmissionBinding, "after_marker_write",
                            lambda binding, event: env.completion.claim_binding_marker_completion(copy(binding), event))
    else:
        def wrong_first_claim(event):
            env.marker_events.append(event)
            env.completion.claim_marker_write_completion(
                object() if wrong == "context" else env.context,
                "fixture.other" if wrong == "method" else env.spec.name,
                object() if wrong == "owner" else env.guard, event)
        env.guard.after_marker_write = wrong_first_claim
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error):
            before(env, binding, consumer)
        assert len(env.marker_events) == (0 if wrong == "binding" else 1)
        assert len(env.stack.frames) == 1


def test_nested_checkpoint_cannot_borrow_delivery_or_start_a_new_stamp(markers):
    env = markers
    with authorized(env) as (binding, consumer):
        env.marker_hook = lambda *_: before(env, binding, consumer)
        with pytest.raises(env.error):
            before(env, binding, consumer)
        assert len(env.marker_events) == 1 and len(env.stack.frames) == 1


def test_other_context_manager_is_refused_before_reads_and_first_failure_stays_sticky(markers, monkeypatch):
    env = markers
    other = env.checkpoints.CheckpointManager()
    def unreadable(**_kwargs):
        pytest.fail("A manager different from context.checkpoints must not read Blender")
    monkeypatch.setattr(other, "_ensure_undo_enabled", unreadable)
    with authorized(env, manager=other) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer, manager=other)
        with pytest.raises(env.error) as wrong_manager_retry:
            before(env, binding, consumer)
        assert wrong_manager_retry.value is caught.value
        assert env.marker_events == [] and env.checkpoints.MARKER_KEY not in env.stack.scene


def test_out_of_order_issue_from_a_provider_is_not_an_actual_write(markers):
    env = markers
    with authorized(env) as (binding, consumer):
        def premature():
            guard = env.completion._calls[id(consumer)].guard
            env.completion.issue_marker_write_completion(env.manager, guard, env.expected)
        env.hooks.before = premature
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        assert caught.value.context["marker_write_completion_valid"] is False
        assert env.checkpoints.MARKER_KEY not in env.stack.scene and env.marker_events == []


@pytest.mark.parametrize("service", ["state", "request_lifecycle", "check_final_request", "check_final_job", "checkpoints"])
def test_replaced_caller_service_is_refused_before_replacement_hooks_or_write(markers, service):
    env, invoked = markers, []
    replacements = {"state": NS(snapshot=lambda: invoked.append("replacement state") or {}),
                    "request_lifecycle": NS(check=lambda: invoked.append("replacement lifecycle")),
                    "check_final_request": lambda: invoked.append("replacement request"),
                    "check_final_job": lambda: invoked.append("replacement job"), "checkpoints": object()}
    with authorized(env) as (binding, consumer):
        env.hooks.before = lambda: setattr(env.context, service, replacements[service])
        with pytest.raises(env.error):
            before(env, binding, consumer)
        assert invoked == [] and env.marker_events == []
        assert env.checkpoints.MARKER_KEY not in env.stack.scene


@pytest.mark.parametrize("hook", ["owner", "binding"])
def test_replaced_marker_hooks_are_not_adopted(markers, monkeypatch, hook):
    env, invoked = markers, []
    with authorized(env) as (binding, consumer):
        if hook == "owner":
            env.hooks.before = lambda: setattr(binding, "marker_write_callback", lambda _event: invoked.append(True))
        else:
            env.hooks.before = lambda: monkeypatch.setattr(
                type(binding), "after_marker_write", lambda *_: invoked.append(True))
        with pytest.raises(env.error):
            before(env, binding, consumer)
        assert invoked == [] and env.marker_events == []
        assert env.checkpoints.MARKER_KEY not in env.stack.scene


def test_changed_readback_is_not_adopted_as_the_predicted_marker(markers):
    env = markers
    scene_type = type(env.stack.scene)
    class Changed(scene_type):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if key == env.checkpoints.MARKER_KEY:
                super().__setitem__(key, value + "newer")
    scene = Changed(env.stack.scene)
    scene.session_uid, scene.as_pointer = 10, lambda: 101
    env.stack.scene = env.stack.bpy.context.scene = scene
    env.stack.bpy.data.scenes = [scene]
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error):
            before(env, binding, consumer)
        predicted = env.marker_evidence[0][1][0][-1]
        assert env.checkpoints.TOKEN_PATTERN.fullmatch(predicted)
        assert scene[env.checkpoints.MARKER_KEY] == predicted + "newer"
        assert len(env.marker_events) == 1 and len(env.stack.frames) == 1


def test_marker_setter_unknown_result_is_retained_without_receipt_or_retry(markers):
    env = markers
    scene_type = type(env.stack.scene)
    class Failed(scene_type):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if key == env.checkpoints.MARKER_KEY:
                raise RuntimeError("Private native-shaped write failed after changing data")
    scene = Failed(env.stack.scene)
    scene.session_uid, scene.as_pointer = 10, lambda: 101
    env.stack.scene = env.stack.bpy.context.scene = scene
    env.stack.bpy.data.scenes = [scene]
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        facts = caught.value.context["checkpoint_bookkeeping"]
        assert facts["marker_write_attempts"] == 1 and facts["marker_write_outcome_unknown"]
        assert facts["marker_writes_completed"] == 0 and caught.value.context["possible_mutation"]
        assert env.marker_events == [] and env.checkpoints.MARKER_KEY in scene
        with pytest.raises(env.error) as retry:
            before(env, binding, consumer)
        assert retry.value is caught.value and len(env.stack.frames) == 1


@pytest.mark.parametrize("operation", ["set", "delete"])
def test_post_write_prediction_failure_retains_marker_accounting_and_never_resumes(markers, monkeypatch, operation):
    env, observed = markers, []
    if operation == "delete":
        env.stack.scene[env.checkpoints.MARKER_KEY] = env.manager._prefix + "c" * 32
        env.expected = env.manager._marker_evidence(env.stack.bpy)
    def failed_delta(_before, scene, value):
        if value is None:
            assert env.checkpoints.MARKER_KEY not in scene
        else:
            assert scene[env.checkpoints.MARKER_KEY] == value
        observed.append(value)
        raise MemoryError("Private allocation failure after actual marker write")
    monkeypatch.setattr(env.manager, "_marker_delta", failed_delta)
    with authorized(env) as (binding, consumer):
        with pytest.raises(env.error) as caught:
            before(env, binding, consumer)
        context = caught.value.context
        facts = context["checkpoint_bookkeeping"]
        assert context["checkpoint_authority_rejected"] and context["execution_started"]
        assert context["possible_mutation"] and context["verification_required"]
        assert facts["marker_writes_completed"] == 1 and facts["native_snapshots_completed"] == 0
        assert facts["marker_write_attempts"] == 1 and facts["marker_write_outcome_unknown"]
        assert not facts["compensation_performed"]
        assert observed == [None if operation == "delete" else env.stack.scene[env.checkpoints.MARKER_KEY]]
        assert env.marker_events == [] and len(env.stack.frames) == 1
        with pytest.raises(env.error) as retry:
            before(env, binding, consumer)
        assert retry.value is caught.value and len(observed) == 1


def test_owned_marker_observer_is_composed_once_per_actual_write(markers, monkeypatch):
    env, observed = markers, []
    bind = env.checkpoints.bind_native_push_guard
    def bind_with_owned_observer(manager, guard):
        bind(manager, guard)
        guard.marker_observer = observed.append
    monkeypatch.setattr(env.checkpoints, "bind_native_push_guard", bind_with_owned_observer)
    with authorized(env) as (binding, consumer):
        assert before(env, binding, consumer)
        assert observed == env.marker_evidence and len(observed) == 3
