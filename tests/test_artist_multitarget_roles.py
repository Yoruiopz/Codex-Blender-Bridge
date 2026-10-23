"""Previous checkpoint targets stay protected across authenticated A -> B polls."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import checkpoint_completion_support as completion_support
import pytest
from test_scene_checkpoint_roles import roles as roles


@dataclass(frozen=True, slots=True)
class PreviousWitness:
    case: object
    owner: object
    identity: object
    authored: object
    consumers: object

    def check(self, plan):
        case = self.case
        if (not any(owner is self.owner for owner in case.live_objects)
                or case.module.proof.token(self.owner) != self.identity
                or self.owner._values["protected_value"] != self.authored
                or plan.object_references(case.rows(self.owner)) != self.consumers):
            raise case.module.proof.unsupported("Frozen previous target changed.", previous_owner_valid=False)


@pytest.fixture
def targets(roles):
    case = roles
    case.a, case.b = case.active, case.other
    case.c = type(case.a)(dict(case.a._values))
    case.live_objects = [case.a, case.b, case.c]
    case.camera = {owner: 0 for owner in case.live_objects}
    case.extra = {owner: 0 for owner in case.live_objects}
    case.foreign = {owner: 1 for owner in case.live_objects}
    for index, owner in enumerate(case.live_objects):
        owner._values["protected_value"] = 10.0 + index
    case.bpy.context.view_layer.objects.active = case.b
    case.counts["self"] = 1
    case.particle._values["object"] = case.a
    case.captures = []

    def rows(*owners):
        result = []
        for owner in owners:
            weak = int(case.counts["self"] == 1 and case.particle._values["object"] is owner)
            camera = case.camera[owner]
            role = (("SCENE_REFERENCES", camera, weak, (("settings", "unchanged"),) if weak else None)
                    if weak or camera else ("MEMBERSHIP",))
            result.extend([
                (case.module.proof.token(owner), case.module.proof.token(case.scene),
                 2 + camera + case.extra[owner] + weak, role),
                (case.module.proof.token(owner), ("foreign", "consumer"), case.foreign[owner], ("PARENT",)),
            ])
        return tuple(result)

    def factory(bpy, old_object, plan):
        assert bpy is case.bpy
        witness = PreviousWitness(case, old_object, case.module.proof.token(old_object),
            old_object._values["protected_value"], plan.object_references(rows(old_object)))
        case.captures.append((old_object, witness))
        return witness

    def make():
        return case.module.Plan(case.bpy, case.scene, previous_owner_factory=factory)

    def bind_active():
        case.counts["self"] = 1
        case.particle._values["object"] = case.bpy.context.view_layer.objects.active

    case.rows, case.factory, case.make, case.bind_active = rows, factory, make, bind_active
    return case


@pytest.mark.parametrize("initial", ["empty", "same", "previous"])
def test_factory_only_witnesses_an_actual_previous_target(targets, initial):
    case = targets
    if initial == "empty":
        case.counts["self"], case.particle._values["object"] = 0, None
    elif initial == "same":
        case.particle._values["object"] = case.b
    plan = case.make()
    expected_owner = None if initial == "empty" else case.a if initial == "previous" else case.b
    assert plan.expected == (int(initial != "empty"), case.module.proof.token(expected_owner))
    assert len(case.captures) == int(initial == "previous")
    assert (plan.previous_witness is not None) is (initial == "previous")
    before = plan.authored(), plan.object_references(case.rows(case.a, case.b))
    case.complete(plan, effect=case.bind_active)
    assert plan.expected == (1, case.module.proof.token(case.b))
    assert (plan.authored(), plan.object_references(case.rows(case.a, case.b))) == before


def test_default_scene_and_render_plan_still_refuses_another_previous_target(targets):
    case = targets
    with pytest.raises(case.module.proof.BridgeError):
        case.module.Plan(case.bpy, case.scene)
    assert case.captures == []


@pytest.mark.parametrize("returned", [None, object()])
def test_previous_target_requires_a_readonly_witness(targets, returned):
    case = targets
    with pytest.raises(case.module.proof.BridgeError):
        case.module.Plan(case.bpy, case.scene, previous_owner_factory=lambda *_: returned)


def test_origin_keeps_exact_frozen_previous_witness_and_forks_without_recapture(targets, monkeypatch):
    case = targets
    plan = case.make()
    origin = plan.origin()
    witness = plan.previous_witness
    assert origin.previous_witness is witness and len(case.captures) == 1
    with pytest.raises(FrozenInstanceError):
        witness.authored = "new baseline"
    with pytest.raises(FrozenInstanceError):
        origin.previous_witness = None
    monkeypatch.setattr(case.module.Plan, "__init__", lambda *_a, **_kw: pytest.fail("Fork recaptured a live baseline"))
    first, second = origin.fork(), origin.fork()
    assert first is not second and first is not plan
    assert first.previous_witness is second.previous_witness is witness
    assert first.expected == second.expected == origin.expected == (1, case.module.proof.token(case.a))
    case.complete(first, effect=case.bind_active)
    first.check_after_read()
    assert len(case.captures) == 1
    assert first.expected == (1, case.module.proof.token(case.b))
    assert second.expected == plan.expected == origin.expected == (1, case.module.proof.token(case.a))
    for stale in (second.check_after_read, plan.check_after_read, origin.fork):
        with pytest.raises(case.module.proof.BridgeError):
            stale()


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("change", ["authored", "consumer", "camera", "foreign", "removed", "replaced", "identity"])
def test_previous_owner_authored_identity_and_consumers_remain_frozen(targets, phase, change):
    case = targets
    plan = case.make()
    if phase == "after":
        case.complete(plan, effect=case.bind_active)
    if change == "authored":
        case.a._values["protected_value"] += 1
    elif change == "consumer":
        case.extra[case.a] += 1
    elif change == "camera":
        case.camera[case.a] = 1
    elif change == "foreign":
        case.foreign[case.a] += 1
    elif change == "removed":
        case.live_objects.remove(case.a)
    elif change == "replaced":
        replacement = type(case.a)(dict(case.a._values))
        case.live_objects[case.live_objects.index(case.a)] = replacement
    else:
        case.a.session_uid += 1
    expected = plan.expected
    for proof in (plan.check_after_read, plan.authored, plan.fork):
        with pytest.raises(case.module.proof.BridgeError) as caught:
            proof()
        key = "checkpoint_roles_valid" if change == "identity" and phase == "before" else "previous_owner_valid"
        assert caught.value.context[key] is False
    assert plan.expected == expected and len(case.captures) == 1


@pytest.mark.parametrize("wrong", ["third", "none", "extra_scene_self"])
def test_finished_native_push_never_adopts_an_unpredicted_previous_role(targets, wrong):
    case = targets
    plan = case.make()
    def bad_poll():
        case.bind_active()
        if wrong == "third":
            case.particle._values["object"] = case.c
        elif wrong == "none":
            case.particle._values["object"] = None
        else:
            case.counts["self"] = 2
    with pytest.raises(case.module.proof.BridgeError) as caught:
        case.complete(plan, effect=bad_poll)
    assert caught.value.context["checkpoint_roles_valid"] is False
    assert caught.value.context["checkpoint_bookkeeping"]["native_snapshots_completed"] == 1
    assert plan.expected == (1, case.module.proof.token(case.b))


def test_unnotified_manual_retarget_is_rejected_before_any_next_native_push(targets):
    case = targets
    plan = case.make()
    case.bind_active()
    effects = []
    with pytest.raises(case.module.proof.BridgeError):
        case.complete(plan, effect=lambda: effects.append("must not run"))
    assert effects == [] and plan.expected == (1, case.module.proof.token(case.a))
    assert len(case.captures) == 1


@pytest.mark.parametrize("phase", ["before", "after"])
def test_direct_and_replayed_completion_cannot_reauthorize_a_target(targets, phase):
    case = targets
    plan = case.make()
    delivered = case.complete(plan, effect=case.bind_active) if phase == "after" else None
    expected = plan.expected
    callbacks = [plan.after_native_push]
    if delivered is not None:
        callbacks.append(delivered.guard.after_native_push)
    for callback in callbacks:
        with pytest.raises(case.module.proof.BridgeError) as caught:
            callback()
        assert caught.value.context["native_push_completion_valid"] is False
        assert plan.expected == expected
    plan.check_after_read()


def test_previous_witness_denial_prevents_the_native_operator(targets):
    case = targets
    plan = case.make()
    case.a._values["protected_value"] += 1
    effects = []
    with pytest.raises(case.module.proof.BridgeError) as caught:
        case.complete(plan, effect=lambda: effects.append("must not run"))
    assert caught.value.context["previous_owner_valid"] is False
    assert caught.value.context["checkpoint_bookkeeping"]["native_snapshots_completed"] == 0
    assert effects == [] and plan.expected == (1, case.module.proof.token(case.a))


@pytest.mark.parametrize("outcome", ["zero_pushes", "cancelled", "runtime_failure",
    "cancelled_with_role_change", "runtime_failure_with_role_change"])
def test_no_completed_native_push_cannot_advance_a_previous_role(targets, monkeypatch, outcome):
    case = targets
    plan = case.make()
    stack = completion_support.NativeStack()
    calls, effects = [], []
    if outcome == "zero_pushes":
        stack.bpy.context.mode = "EDIT_MESH"
    else:
        def rejected_push(**_kwargs):
            calls.append("native operator entered")
            if outcome.endswith("with_role_change"):
                case.bind_active()
            if outcome.startswith("runtime_failure"):
                raise RuntimeError("fixture failed native operator")
            return {"CANCELLED"}
        stack.bpy.ops.ed.undo_push = rejected_push
    monkeypatch.setattr(completion_support, "NativeStack", lambda: stack)
    with pytest.raises(AssertionError):  # The shared helper requires a completed boundary.
        case.complete(plan, effect=lambda: effects.append("must not run"))
    assert len(calls) == int(outcome != "zero_pushes")
    assert stack.cursor == 0 and effects == []
    assert plan.expected == (1, case.module.proof.token(case.a))
    if outcome.endswith("with_role_change"):
        with pytest.raises(case.module.proof.BridgeError):
            plan.check_after_read()
    else:
        plan.check_after_read()
    with pytest.raises(case.module.proof.BridgeError):
        plan.after_native_push()


def test_a_to_b_to_a_uses_fresh_origins_without_reusing_prior_authority(targets):
    case = targets
    first = case.make()
    first_origin = first.origin()
    case.complete(first, effect=case.bind_active)
    case.bpy.context.view_layer.objects.active = case.a
    second = case.make()
    assert second.previous_witness is not first.previous_witness
    assert second.expected == (1, case.module.proof.token(case.b))
    assert second.active == case.module.proof.token(case.a)
    second_origin = second.origin()
    case.complete(second, effect=case.bind_active)
    second.check_after_read()
    assert second.expected == (1, case.module.proof.token(case.a))
    assert [owner for owner, _witness in case.captures] == [case.a, case.b]
    assert first_origin.expected == (1, case.module.proof.token(case.a))
    assert second_origin.expected == (1, case.module.proof.token(case.b))
    with pytest.raises(case.module.proof.BridgeError):
        first.check_after_read()


@pytest.mark.parametrize("camera_a,camera_b", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_projection_retains_cameras_and_extra_scene_references_for_both_targets(targets, camera_a, camera_b):
    case = targets
    case.camera[case.a], case.camera[case.b] = camera_a, camera_b
    case.extra[case.a], case.extra[case.b] = 3, 4
    plan = case.make()
    before = plan.object_references(case.rows(case.a, case.b))
    assert (before[0][2], before[2][2]) == (5 + camera_a, 6 + camera_b)
    for index, camera in ((0, camera_a), (2, camera_b)):
        assert before[index][3] == (("SCENE_REFERENCES", 1, 0, None) if camera else ("MEMBERSHIP",))
    case.complete(plan, effect=case.bind_active)
    assert plan.object_references(case.rows(case.a, case.b)) == before
    case.extra[case.b] += 1
    after_extra = plan.object_references(case.rows(case.a, case.b))
    assert after_extra[:2] == before[:2] and after_extra[2][2] == before[2][2] + 1
    case.extra[case.a] += 1
    with pytest.raises(case.module.proof.BridgeError):
        plan.check_after_read()
