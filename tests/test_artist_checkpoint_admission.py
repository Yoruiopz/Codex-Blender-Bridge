"""Native role admission retains one authored Boundary through every call phase."""
from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace as NS

import pytest
from test_artist_loop import loop, preview, rna_env  # noqa: F401
from test_artist_step_evidence import journal  # noqa: F401
from test_checkpoint_snapshots import NativeStack


@pytest.fixture
def admission(journal, addon_package, monkeypatch):  # noqa: F811
    module = importlib.import_module(f"{addon_package}.tools._artist_checkpoint_admission")
    before = journal.executor.checkpoints.before_modification
    after = journal.executor.checkpoints.after_modification
    def guarded(callback):
        def checkpoint(method, **hooks):
            # Mirror the manager's authority and readonly CAS before its first
            # marker/native write; an invocation alone is not a native effect.
            hooks["before_write"]()
            hooks["after_read"]()
            return callback(method, **hooks)
        return checkpoint
    journal.executor.checkpoints.before_modification = guarded(before)
    journal.executor.checkpoints.after_modification = guarded(after)
    captured = []
    bind = module.Admission.bind_checkpoint
    def observe(guard, binding):
        release = bind(guard, binding)
        captured.append(guard)
        return release
    monkeypatch.setattr(module.Admission, "bind_checkpoint", observe)
    return NS(case=journal, module=module, captured=captured)


def test_one_original_boundary_survives_factory_nested_commit_and_finalization(admission):
    case = admission.case
    result = preview(case.env, step_id="revise")
    origin = case.store.previews[result["preview_id"]]["checkpoint_roles"]
    response = case.apply(result)
    assert response.ok, response.error
    outer, child = admission.captured
    assert (outer.method, child.method) == ("task.plan.apply_preview", "transform.set")
    assert outer.boundary is child.boundary and child.parent is outer
    assert outer.boundary.original != outer.boundary.expected
    assert dict(outer.boundary.expected)["location"] == (1., 2., 3.)
    assert outer.roles is child.roles and outer.roles is not origin
    assert outer.preview_origin is origin and origin.expected == 0
    with pytest.raises(FrozenInstanceError):
        origin.expected = 1
    assert not outer.binding.active and not child.binding.active


@pytest.mark.parametrize("fault", ["callback", "new_guard", "readonly", "native_hook", "binding", "all_slots",
                                  "inactive_slots", "boundary", "role_proof", "parent"])
@pytest.mark.parametrize("phase", ["before_checkpoint", "before_field"])
def test_replaced_or_lost_guard_never_rebaselines_or_writes(admission, fault, phase):
    case = admission.case
    result = preview(case.env, step_id="revise")
    fired = []
    def provider():
        if not admission.captured or fired:
            return
        outer = admission.captured[0]
        if phase == "before_field" and case.store.applying_preview is None:
            return
        fired.append(True)
        context = outer.context
        binding = context.checkpoint_admission
        if fault == "callback":
            binding.callback = lambda: None
        elif fault == "new_guard":
            binding.callback = admission.module.Admission(context, binding.method, boundary=outer.boundary)
        elif fault == "readonly":
            binding.readonly_callback = lambda: None
        elif fault == "native_hook":
            binding.native_push_callback = lambda: None
        elif fault == "binding":
            context.checkpoint_admission = None
        elif fault == "boundary":
            binding.callback.boundary = object()
        elif fault == "role_proof":
            binding.callback.boundary.checkpoint_roles = object()
        elif fault == "parent":
            binding.callback.parent = NS(boundary=outer.boundary, consumed=True)
        else:
            if fault == "inactive_slots":
                binding.active = False
            context.checkpoint_admission = context.checkpoint_call_id = context.checkpoint_method = context.checkpoint_params = None
    case.env.provider[0] = provider
    response = case.apply(result)
    assert fired and not response.ok
    assert case.env.obj.location == (0., 0., 0.)
    if phase == "before_checkpoint":
        assert not case.checkpoints
    original = admission.captured[0]._boundary_identity
    assert original.expected == original.original


@pytest.mark.parametrize("phase", ["before_checkpoint", "before_field"])
def test_manual_authored_changes_are_preserved_without_owned_followup(admission, phase):
    case = admission.case
    result = preview(case.env, step_id="revise")
    fired = []
    def provider():
        if fired or not admission.captured:
            return
        if phase == "before_field" and case.store.applying_preview is None:
            return
        fired.append(True)
        case.env.obj.location = (9., 8., 7.)
    case.env.provider[0] = provider
    response = case.apply(result)
    assert fired and not response.ok and case.env.obj.location == (9., 8., 7.)
    if phase == "before_checkpoint":
        assert not case.checkpoints


@pytest.mark.parametrize("phase", ["before_checkpoint", "before_field"])
def test_role_origin_replacement_is_rejected_before_checkpoint(admission, phase):
    case = admission.case
    result = preview(case.env, step_id="revise")
    saved = case.store.previews[result["preview_id"]]
    original = saved["checkpoint_roles"]
    fired = []
    def provider():
        if phase == "before_field" and case.store.applying_preview is None:
            return
        if not fired:
            fired.append(True)
            saved["checkpoint_roles"] = replace(original, expected=1)
    case.env.provider[0] = provider
    response = case.apply(result)
    assert not response.ok and "retained artist preview changed" in response.error["message"]
    if phase == "before_checkpoint":
        assert not case.checkpoints
    assert case.env.obj.location == (0., 0., 0.)


def test_failed_field_retains_verified_partial_boundary_for_recovery(admission):
    case = admission.case
    result = preview(case.env, step_id="revise", scale=[2., 2., 2.])
    case.env.provider[0] = lambda: case.env.grants.update(TRANSFORM_OBJECTS=False) if case.env.obj.location == (1., 2., 3.) else None
    response = case.apply(result)
    assert not response.ok and case.env.obj.location == (1., 2., 3.) and case.env.obj.scale == (1., 1., 1.)
    outer, child = admission.captured
    assert outer.boundary is child.boundary
    assert dict(outer.boundary.expected)["location"] == (1., 2., 3.)
    assert dict(outer.boundary.expected)["scale"] == (1., 1., 1.)
    assert response.error["context"]["possible_mutation"] and not response.error["context"]["rollback_verified"]


def test_unarmed_broad_transform_has_explicit_non_authored_guard(admission):
    case = admission.case
    request = case.protocol.Request(id="ordinary", method="transform.set", params={"object_name": "Owner", "location": [7., 0., 0.]})
    response = case.executor.execute_request(request)
    assert response.ok, response.error
    assert len(admission.captured) == 1 and admission.captured[0].boundary is None
    assert case.env.obj.location == (7., 0., 0.)


@pytest.mark.parametrize("fault", ["scene", "view_layer"])
@pytest.mark.parametrize("phase", ["before_entry", "entry_provider"])
def test_stale_reference_remains_invalid_before_consulting_native_roles(admission, monkeypatch, fault, phase):
    case = admission.case
    result = preview(case.env, step_id="revise")
    origin = case.store.previews[result["preview_id"]]["checkpoint_roles"]
    original_fork = type(origin).fork
    state = {"drifted": False, "forks": 0}

    def fork(owner):
        assert not state["drifted"], "A stale reference reached the native role origin"
        state["forks"] += 1
        return original_fork(owner)

    def change_context():
        if not state["drifted"]:
            state["drifted"] = True
            if fault == "scene":
                case.env.bpy.context.scene.session_uid = 999
            else:
                case.env.bpy.context.view_layer = NS(objects=case.env.bpy.data.objects)

    monkeypatch.setattr(type(origin), "fork", fork)
    if phase == "before_entry":
        change_context()
    else:
        case.env.provider[0] = change_context
    response = case.apply(result)
    assert not response.ok and response.error["code"] == "INVALID_ARGUMENT"
    if phase == "before_entry":
        assert "Reference context" in response.error["message"]
    assert state["drifted"] and state["forks"] == (0 if phase == "before_entry" else 1)
    assert not case.checkpoints and case.env.obj.location == (0., 0., 0.)


def test_current_reference_still_rejects_an_unsupported_native_role_origin(admission, monkeypatch):
    case = admission.case
    result = preview(case.env, step_id="revise")
    origin = case.store.previews[result["preview_id"]]["checkpoint_roles"]
    primary = case.env.module.BridgeError("NOT_IMPLEMENTED", "Unsupported native role phase",
                                          {"checkpoint_roles_valid": False})

    def unsupported(_owner):
        raise primary

    monkeypatch.setattr(type(origin), "fork", unsupported)
    response = case.apply(result)
    assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
    assert response.error["context"]["checkpoint_roles_valid"] is False
    assert not case.checkpoints and case.env.obj.location == (0., 0., 0.)


@pytest.fixture
def native_checkpoints(admission, addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.checkpoints")
    stack = NativeStack()
    monkeypatch.setattr(module, "require_blender", lambda: stack.bpy)
    manager = module.CheckpointManager()
    admission.case.executor.checkpoints = manager
    return NS(admission=admission, stack=stack, manager=manager, module=module)


def test_only_actual_completed_pushes_advance_the_private_fork(native_checkpoints):
    env = native_checkpoints
    case = env.admission.case
    result = preview(case.env, step_id="revise")
    origin = case.store.previews[result["preview_id"]]["checkpoint_roles"]
    response = case.apply(result)
    assert response.ok, response.error
    assert len(env.stack.frames) == 3  # BEFORE and AFTER, each actual FINISHED.
    outer, child = env.admission.captured
    assert outer._role_delegate is child._role_delegate
    assert outer._role_delegate.expected == 1 and origin.expected == 0
    assert outer.boundary is child.boundary


def test_cancelled_push_cannot_advance_role_phase(native_checkpoints, monkeypatch):
    env = native_checkpoints
    case = env.admission.case
    result = preview(case.env, step_id="revise")
    monkeypatch.setattr(env.stack.bpy.ops.ed, "undo_push", lambda **_kwargs: {"CANCELLED"})
    # Existing manager contract can report no boundary; no completion grant is
    # minted. The normal typed writer may still run, with a truthful false flag.
    response = case.apply(result)
    assert response.ok, response.error
    assert not response.result["operation"]["undo_boundary_created"]
    assert len(env.stack.frames) == 1
    outer, child = env.admission.captured
    assert outer._role_delegate.expected == child._role_delegate.expected == 0
    assert outer.preview_origin.expected == 0


def test_forged_completion_hook_during_provider_never_advances_or_writes(native_checkpoints):
    env = native_checkpoints
    case = env.admission.case
    result = preview(case.env, step_id="revise")
    fired = []
    def provider():
        if env.admission.captured and not fired:
            fired.append(True)
            env.admission.captured[0].after_native_push()
    case.env.provider[0] = provider
    response = case.apply(result)
    assert fired and not response.ok and response.error["context"]["native_push_completion_valid"] is False
    assert len(env.stack.frames) == 1 and case.env.obj.location == (0., 0., 0.)
    assert env.admission.captured[0]._role_delegate.expected == 0


def test_completion_failure_retains_one_snapshot_without_requested_edit_or_retry(native_checkpoints, monkeypatch):
    env = native_checkpoints
    case = env.admission.case
    primary = case.env.module.BridgeError("OPERATION_FAILED", "injected completion proof failure")
    original = env.admission.module.Admission.after_native_push
    def fail(guard):
        original(guard)
        raise primary
    monkeypatch.setattr(env.admission.module.Admission, "after_native_push", fail)
    response = case.apply()
    assert not response.ok and response.error["message"] == primary.message
    assert len(env.stack.frames) == 2 and case.env.obj.location == (0., 0., 0.)
    facts = response.error["context"]["checkpoint_bookkeeping"]
    assert facts["native_snapshots_completed"] == 1 and not facts["compensation_performed"]
    assert env.admission.captured[0].boundary.expected == env.admission.captured[0].boundary.original
