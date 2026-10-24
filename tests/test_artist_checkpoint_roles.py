"""Retained artist evidence excludes only the proven native checkpoint roles."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace as NS

import pytest
from test_scene_checkpoint_roles import roles as roles
from test_scene_mutation_boundaries import RNA, NativeOwner, Properties, prop


@pytest.fixture
def artist_roles(roles):
    case = roles
    case.particle.bl_rna.properties.extend([
        prop("brush_size", "FLOAT"),
        prop("is_editable", "BOOLEAN", is_readonly=True),
    ])
    case.particle._values["brush_size"] = 1.5
    case.particle.getter_hooks["is_editable"] = lambda: pytest.fail(
        "Authored evidence must not invoke the native particle cache poll"
    )
    case.particle.custom_values["artist_note"] = "preserve this setting"
    return case


@pytest.fixture
def brush_roles(artist_roles):
    case = artist_roles
    brush_type = type("ParticleBrush", (NativeOwner,), {"bl_rna": RNA("ParticleBrush", Properties([
        prop("curve", "POINTER", is_readonly=True, fixed_type=NS(identifier="CurveMapping")),
        prop("strength", "FLOAT"), prop("steps", "INT"),
    ]))})
    curve_type = type("CurveMapping", (NativeOwner,), {"bl_rna": RNA("CurveMapping", Properties([
        prop("unreviewed_curve_setting", "FLOAT"),
    ]))})
    case.bpy.types.ParticleBrush, case.bpy.types.CurveMapping = brush_type, curve_type
    case.brush = brush_type({"curve": None, "strength": .5, "steps": 4})
    case.brush.custom_values["artist_brush_note"] = "keep this brush setting"
    case.particle.bl_rna.properties.append(prop("brush", "POINTER", is_readonly=True,
        fixed_type=NS(identifier="ParticleBrush")))
    case.particle._values["brush"] = case.brush
    return case


def brush_plan(case, phase):
    plan = case.module.Plan(case.bpy, case.scene, include_brush=True)
    if phase == "after_trusted_push":
        case.complete(plan)
    return plan


def row(case, *, count=2, camera=0, particle=0, target=None, owner=None):
    target = case.active if target is None else target
    owner = case.scene if owner is None else owner
    role = ("SCENE_REFERENCES", camera, particle,
        (("brush_size", 1.5),) if particle else None) if camera or particle else ("MEMBERSHIP",)
    return case.module.proof.token(target), case.module.proof.token(owner), count, role


def initialized(case):
    case.push()
    return case.module.Plan(case.bpy, case.scene)


def test_authored_evidence_stays_equal_across_only_the_trusted_role_transition(artist_roles):
    case = artist_roles
    plan = case.module.Plan(case.bpy, case.scene)
    before = plan.authored()
    case.complete(plan)
    assert plan.authored() == before
    case.complete(plan)
    assert plan.authored() == before
    assert case.particle.getter_calls == []
    assert case.particle.setter_calls == [] and case.active.setter_calls == []


@pytest.mark.parametrize("change", ["writable_setting", "custom_property", "foreign_scene_consumer"])
def test_authored_evidence_does_not_hide_settings_or_foreign_consumers_before_binding(artist_roles, change):
    case = artist_roles
    plan = case.module.Plan(case.bpy, case.scene)
    before = plan.authored()
    assert plan.expected == (0, case.module.proof.token(None))
    if change == "writable_setting":
        case.particle._values["brush_size"] = 2.5
    elif change == "custom_property":
        case.particle.custom_values["artist_note"] = "a newer manual value"
    else:
        case.counts["window"] += 1
    assert plan.authored() != before
    assert plan.expected == (0, case.module.proof.token(None))


@pytest.mark.parametrize("operation", ["authored", "fork", "object_references"])
def test_an_untrusted_native_role_change_cannot_become_a_new_baseline(artist_roles, operation):
    case = artist_roles
    plan = case.module.Plan(case.bpy, case.scene)
    case.push()
    with pytest.raises(case.module.proof.BridgeError) as caught:
        if operation == "object_references":
            plan.object_references((row(case, count=3, particle=1),))
        else:
            getattr(plan, operation)()
    assert caught.value.context["checkpoint_roles_valid"] is False
    assert plan.expected == (0, case.module.proof.token(None))


@pytest.mark.parametrize("owner", ["active", "settings", "particle", "original"])
def test_retained_owner_drift_rejects_authored_and_object_projection(artist_roles, owner):
    case = artist_roles
    plan = case.module.Plan(case.bpy, case.scene)
    if owner == "active":
        case.bpy.context.view_layer.objects.active = case.other
    elif owner == "settings":
        case.scene._values["tool_settings"] = type(case.settings)({"particle_edit": case.particle})
    elif owner == "particle":
        replacement = type(case.particle)({"object": None, "brush_size": 1.5})
        case.settings._values["particle_edit"] = replacement
    else:
        case.scene._values["original"] = case.other
    for operation in (plan.authored, plan.fork, lambda: plan.object_references((row(case),))):
        with pytest.raises(case.module.proof.BridgeError):
            operation()


def test_fork_keeps_the_exact_origin_and_advances_independently(artist_roles, monkeypatch):
    case = artist_roles
    plan = case.module.Plan(case.bpy, case.scene)
    before = plan.authored()
    def forbidden_constructor(*_args, **_kwargs):
        pytest.fail("Fork must copy retained authority, not construct a fresh live baseline")
    monkeypatch.setattr(case.module.Plan, "__init__", forbidden_constructor)
    forked = plan.fork()
    assert forked is not plan and forked.bpy is plan.bpy and forked.scene is plan.scene
    assert forked.active_validator is plan.active_validator
    assert forked.owners == plan.owners and forked.expected == plan.expected
    assert forked.authored() == before
    case.complete(forked)
    assert forked.authored() == before
    assert plan.expected == (0, case.module.proof.token(None))
    with pytest.raises(case.module.proof.BridgeError):
        plan.check_after_read()


def test_fork_of_an_initialized_origin_keeps_that_exact_phase(artist_roles):
    case = artist_roles
    plan = initialized(case)
    forked = plan.fork()
    assert forked.expected == (1, case.module.proof.token(case.active))
    assert forked.authored() == plan.authored()
    case.particle._values["object"] = case.other
    with pytest.raises(case.module.proof.BridgeError):
        forked.fork()
    assert forked.expected == plan.expected


@pytest.mark.parametrize("camera", [0, 1])
def test_object_projection_subtracts_one_weak_role_and_preserves_camera_counts(artist_roles, camera):
    case = artist_roles
    plan = case.module.Plan(case.bpy, case.scene)
    ordinary_count = 2 + camera
    before = (row(case, count=ordinary_count, camera=camera),)
    assert plan.object_references(before) == before
    case.complete(plan)
    after = (row(case, count=ordinary_count + 1, camera=camera, particle=1),)
    assert plan.object_references(after) == before


@pytest.mark.parametrize("change", ["extra_scene_reference", "camera_reference"])
def test_projection_cannot_normalize_an_extra_reference_into_the_prior_scope(artist_roles, change):
    case = artist_roles
    plan = case.module.Plan(case.bpy, case.scene)
    before = plan.object_references((row(case),))
    case.complete(plan)
    projected = plan.object_references((row(case, count=4, camera=int(change == "camera_reference"), particle=1),))
    assert projected != before
    assert projected[0][2] == 3
    assert projected[0][3] == (("SCENE_REFERENCES", 1, 0, None)
        if change == "camera_reference" else ("MEMBERSHIP",))


def test_projection_leaves_other_objects_and_non_scene_consumers_literal(artist_roles):
    case = artist_roles
    plan = initialized(case)
    other_object = row(case, target=case.other, count=3, camera=1)
    foreign_owner = row(case, owner=case.other, count=7, particle=1)
    raw = (other_object, foreign_owner, row(case, count=3, particle=1))
    projected = plan.object_references(raw)
    assert projected[:2] == raw[:2]
    assert projected[2] == row(case)


def test_weak_role_cannot_be_claimed_for_a_different_object(artist_roles):
    case = artist_roles
    plan = initialized(case)
    with pytest.raises(case.module.proof.BridgeError):
        plan.object_references((row(case, target=case.other, count=3, particle=1),))


@pytest.mark.parametrize("role", [(), ("UNKNOWN",), ("MEMBERSHIP",),
    ("MEMBERSHIP", "extra"), ("SCENE_REFERENCES", 2, 1, None),
    ("SCENE_REFERENCES", 0, 0, None), ("SCENE_REFERENCES", 1, 2, None)])
def test_initialized_projection_rejects_unknown_or_missing_role_metadata(artist_roles, role):
    case = artist_roles
    plan = initialized(case)
    target, owner, count, _role = row(case, count=3, particle=1)
    with pytest.raises(case.module.proof.BridgeError):
        plan.object_references(((target, owner, count, role),))


@pytest.mark.parametrize("count", [-1, 0, 1, True, 3., "3"])
def test_initialized_projection_rejects_counts_that_cannot_have_one_weak_role(artist_roles, count):
    case = artist_roles
    plan = initialized(case)
    with pytest.raises(case.module.proof.BridgeError):
        plan.object_references((row(case, count=count, particle=1),))


def test_authored_checks_the_scene_self_reference_record_independently(artist_roles, monkeypatch):
    case = artist_roles
    plan = initialized(case)
    actual = case.module.proof.references
    def extra_self_reference(bpy, owners):
        identity, users, fake_user, direct = actual(bpy, owners)[0]
        bad = tuple((token, kind, name, 2 if token == identity else count)
            for token, kind, name, count in direct)
        return ((identity, users, fake_user, bad),)
    monkeypatch.setattr(case.module.proof, "references", extra_self_reference)
    with pytest.raises(case.module.proof.BridgeError) as caught:
        plan.authored()
    assert caught.value.context["checkpoint_roles_valid"] is False


def test_artist_active_validator_is_used_without_weakening_the_native_default(artist_roles):
    case = artist_roles
    case.active._values["constraints"] = (object(),)
    with pytest.raises(case.module.proof.BridgeError):
        case.module.Plan(case.bpy, case.scene)
    checked = []
    def artist_validator(bpy, active):
        checked.append((bpy, active))
    plan = case.module.Plan(case.bpy, case.scene, active_validator=artist_validator)
    plan.authored()
    assert checked and all(bpy is case.bpy and active is case.active for bpy, active in checked)


@pytest.mark.parametrize("cache", ["particle_systems", "soft_body"])
def test_custom_active_validator_never_bypasses_explicit_cache_source_denial(artist_roles, cache):
    case = artist_roles
    case.active._values[cache] = (object(),) if cache == "particle_systems" else object()
    with pytest.raises(case.module.proof.BridgeError, match="particle or soft-body"):
        case.module.Plan(case.bpy, case.scene, active_validator=lambda _bpy, _obj: None)


def test_origin_is_frozen_and_keeps_the_original_phase_after_its_plan_advances(brush_roles):
    case = brush_roles
    plan = brush_plan(case, "before_binding")
    origin = plan.origin()
    assert isinstance(origin, case.module.Origin) and origin.include_brush is True
    original_phase = origin.expected
    with pytest.raises(FrozenInstanceError):
        origin.expected = (1, case.module.proof.token(case.active))
    case.complete(plan)
    assert origin.expected == original_phase == (0, case.module.proof.token(None))
    assert plan.expected == (1, case.module.proof.token(case.active))
    with pytest.raises(case.module.proof.BridgeError):
        origin.fork()


@pytest.mark.parametrize("phase", ["before_binding", "after_trusted_push"])
def test_origin_forks_independent_plans_without_reconstructing_or_rebasing(brush_roles, monkeypatch, phase):
    case = brush_roles
    plan = brush_plan(case, phase)
    origin = plan.origin()
    before = plan.authored()
    def forbidden_constructor(*_args, **_kwargs):
        pytest.fail("An Origin fork must not construct a new baseline")
    monkeypatch.setattr(case.module.Plan, "__init__", forbidden_constructor)
    first, second = origin.fork(), origin.fork()
    assert first is not second and first is not plan and second is not plan
    assert first.include_brush is True and first.active_validator is origin.active_validator
    assert first.owners == second.owners == origin.owners
    assert first.expected == second.expected == origin.expected
    assert first.authored() == second.authored() == before
    if phase == "before_binding":
        case.complete(first)
        assert first.authored() == before
        assert second.expected == origin.expected == (0, case.module.proof.token(None))
        with pytest.raises(case.module.proof.BridgeError):
            second.check_after_read()


def test_artist_brush_evidence_stays_equal_across_the_trusted_role_transition(brush_roles):
    case = brush_roles
    plan = brush_plan(case, "before_binding")
    before = plan.authored()
    case.complete(plan)
    assert plan.authored() == before
    assert case.brush.setter_calls == [] and case.particle.setter_calls == []
    assert case.particle.getter_calls == []


@pytest.mark.parametrize("phase", ["before_binding", "after_trusted_push"])
@pytest.mark.parametrize("change", ["root_setting", "root_custom", "brush_setting", "brush_custom"])
def test_artist_authored_evidence_retains_root_and_brush_content_in_both_phases(brush_roles, phase, change):
    case = brush_roles
    plan = brush_plan(case, phase)
    before = plan.authored()
    if change == "root_setting":
        case.particle._values["brush_size"] = 9.5
    elif change == "root_custom":
        case.particle.custom_values["artist_note"] = "new root value"
    elif change == "brush_setting":
        case.brush._values["strength"] = .75
    else:
        case.brush.custom_values["artist_brush_note"] = "new brush value"
    assert plan.authored() != before


@pytest.mark.parametrize("phase", ["before_binding", "after_trusted_push"])
def test_replacement_brush_identity_remains_visible_even_with_identical_content(brush_roles, phase):
    case = brush_roles
    plan = brush_plan(case, phase)
    before = plan.authored()
    replacement = type(case.brush)(dict(case.brush._values))
    replacement.custom_values.update(case.brush.custom_values)
    assert case.module.proof.primitive(case.bpy, replacement) == case.module.proof.primitive(case.bpy, case.brush)
    case.particle._values["brush"] = replacement
    assert plan.authored() != before


def test_artist_brush_profile_refuses_a_missing_brush(brush_roles):
    case = brush_roles
    plan = brush_plan(case, "before_binding")
    case.particle._values["brush"] = None
    with pytest.raises(case.module.proof.BridgeError, match="reviewed native particle brush"):
        plan.authored()


@pytest.mark.parametrize("phase", ["before_binding", "after_trusted_push"])
def test_nonnull_curve_is_refused_before_any_unreviewed_curve_content_read(brush_roles, phase):
    case = brush_roles
    plan = brush_plan(case, phase)
    curve = case.bpy.types.CurveMapping({"unreviewed_curve_setting": .5})
    curve.getter_hooks["unreviewed_curve_setting"] = lambda: pytest.fail("Curve content was read")
    case.brush._values["curve"] = curve
    with pytest.raises(case.module.proof.BridgeError, match="non-null particle brush curve"):
        plan.authored()
    assert curve.getter_calls == []


@pytest.mark.parametrize("child", ["brush", "curve"])
@pytest.mark.parametrize("fault", ["runtime", "writable", "registered", "wrong_native_type"])
def test_artist_child_pointer_descriptors_are_validated_before_their_getters(brush_roles, child, fault):
    case = brush_roles
    plan = brush_plan(case, "before_binding")
    owner = case.particle if child == "brush" else case.brush
    descriptor = owner.bl_rna.properties.get(child)
    if fault == "runtime":
        descriptor.is_runtime = True
    elif fault == "writable":
        descriptor.is_readonly = False
    elif fault == "registered":
        descriptor.is_registered = True
    else:
        descriptor.fixed_type = NS(identifier="UnreviewedNativeType")
    owner.getter_hooks[child] = lambda: pytest.fail("An unreviewed child pointer getter ran")
    with pytest.raises(case.module.proof.BridgeError):
        plan.authored()
    assert owner.getter_calls == []


@pytest.mark.parametrize("phase", ["before_binding", "after_trusted_push"])
def test_unknown_runtime_brush_descriptor_stops_before_child_or_field_getters(brush_roles, phase):
    case = brush_roles
    plan = brush_plan(case, phase)
    case.brush.bl_rna.properties.append(prop("hostile_runtime", "FLOAT", is_runtime=True))
    case.brush.getter_hooks["hostile_runtime"] = lambda: pytest.fail("Runtime brush getter ran")
    case.brush.getter_hooks["curve"] = lambda: pytest.fail("Curve getter ran after unreviewed descriptor")
    with pytest.raises(case.module.proof.BridgeError):
        plan.authored()
    assert case.brush.getter_calls == []
