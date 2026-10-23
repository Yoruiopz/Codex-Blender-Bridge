"""A completed native push is the sole authority for ParticleEdit weak roles."""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from checkpoint_completion_support import complete_plan_push
from test_scene_mutation_boundaries import RNA, NativeOwner, Properties, prop


@pytest.fixture
def roles(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools._scene_checkpoint_roles")
    classes = {}
    for kind, fields in {
        "Scene": (("tool_settings", "ToolSettings"), ("original", "ID")),
        "ToolSettings": (("particle_edit", "ParticleEdit"),),
        "ParticleEdit": (("object", "Object"),), "Object": (("soft_body", "SoftBodySettings"),),
    }.items():
        descriptors = Properties([prop(name, "POINTER", is_readonly=True, fixed_type=NS(identifier=fixed))
                                  for name, fixed in fields])
        classes[kind] = type(kind, (NativeOwner,), {"bl_rna": RNA(kind, descriptors)})
    object_values = {"animation_data": None, "parent": None, "constraints": (), "modifiers": (),
                     "rigid_body": None, "rigid_body_constraint": None, "instance_type": "NONE",
                     "particle_systems": (), "soft_body": None}
    active, other = classes["Object"](object_values), classes["Object"](object_values)
    particle = classes["ParticleEdit"]({"object": None})
    settings = classes["ToolSettings"]({"particle_edit": particle})
    scene = classes["Scene"]({"name": "Scene", "users": 1, "use_fake_user": False,
                               "tool_settings": settings})
    scene._values["original"] = scene
    counts = {"self": 0, "window": 2}
    scene.user_of_id = lambda owner: counts["self"] if owner is scene else 0
    window = NS(as_pointer=lambda: 77, session_uid=8, bl_rna=NS(identifier="WindowManager"),
                name="WinMan", user_of_id=lambda _scene: counts["window"])
    def users(*, subset):
        assert subset == {scene}
        return {scene: (window, scene) if counts["self"] else (window,)}
    bpy = NS(types=NS(**classes), data=NS(user_map=users), context=NS(view_layer=NS(objects=NS(active=active))))
    def push():
        counts["self"] = 1
        particle._values["object"] = active
    case = NS(module=module, bpy=bpy, scene=scene, particle=particle, settings=settings,
              active=active, other=other, counts=counts, push=push)
    def complete(plan, *, effect=push):
        return complete_plan_push(addon_package, monkeypatch, plan, effect=effect)
    case.complete = complete
    return case


def test_only_trusted_completion_advances_the_exact_predicted_roles(roles):
    case = roles
    plan = case.module.Plan(case.bpy, case.scene)
    before = plan.references()
    case.push()  # An unrelated provider/native action cannot authorize itself.
    with pytest.raises(case.module.proof.BridgeError) as caught:
        plan.check_after_read()
    assert caught.value.context["checkpoint_roles_valid"] is False
    assert plan.expected == (0, (None, None))
    native_effects = []
    with pytest.raises(case.module.proof.BridgeError):
        case.complete(plan, effect=lambda: native_effects.append("must not run"))
    assert native_effects == [] and plan.expected == (0, (None, None))
    # Restore the unchanged retained origin, then earn the one allowed transition.
    case.counts["self"] = 0
    case.particle._values["object"] = None
    delivered = case.complete(plan)
    assert delivered.stack.cursor == 1
    plan.check_after_read()
    assert plan.references() == before
    assert plan.expected == (1, case.module.proof.token(case.active))
    case.complete(plan)  # Later legitimate pushes retain the same fixed roles.
    assert plan.references() == before


def test_hook_never_adopts_a_different_live_object_or_original(roles):
    case = roles
    plan = case.module.Plan(case.bpy, case.scene)
    def wrong_owner_push():
        case.push()
        case.particle._values["object"] = case.other
    with pytest.raises(case.module.proof.BridgeError) as caught:
        case.complete(plan, effect=wrong_owner_push)
    assert caught.value.context["checkpoint_roles_valid"] is False
    assert caught.value.context["checkpoint_bookkeeping"]["native_snapshots_completed"] == 1
    assert plan.expected == (1, case.module.proof.token(case.active))
    case.particle._values["object"] = case.active
    case.scene._values["original"] = case.other
    with pytest.raises(case.module.proof.BridgeError):
        plan.check_after_read()


@pytest.mark.parametrize("initialized", [False, True])
def test_direct_hook_cannot_claim_a_completed_native_push(roles, initialized):
    case = roles
    if initialized:
        case.push()
    plan = case.module.Plan(case.bpy, case.scene)
    expected = plan.expected
    with pytest.raises(case.module.proof.BridgeError) as caught:
        plan.after_native_push()
    assert caught.value.context["native_push_completion_valid"] is False
    assert plan.expected == expected
    plan.check_after_read()


@pytest.mark.parametrize("count,target", [(0, "active"), (1, "none"), (1, "other"), (2, "active"), (-1, "none")])
def test_initial_role_pair_has_no_wildcard_or_extra_self_alias(roles, count, target):
    case = roles
    case.counts["self"] = count
    case.particle._values["object"] = {"active": case.active, "other": case.other, "none": None}[target]
    with pytest.raises(case.module.proof.BridgeError):
        case.module.Plan(case.bpy, case.scene)


def test_initialized_roles_are_frozen_and_foreign_consumers_remain_visible(roles):
    case = roles
    case.push()
    plan = case.module.Plan(case.bpy, case.scene)
    before = plan.references()
    case.counts["window"] += 1
    assert plan.references() != before
    case.counts["self"] += 1
    with pytest.raises(case.module.proof.BridgeError):
        plan.references()


@pytest.mark.parametrize("owner,field", [("scene", "tool_settings"), ("scene", "original"),
                                          ("settings", "particle_edit"), ("particle", "object")])
def test_role_descriptors_fail_before_corresponding_getters(roles, owner, field):
    case = roles
    target = getattr(case, owner)
    descriptor = target.bl_rna.properties.get(field)
    descriptor.is_runtime = True
    target.getter_hooks[field] = lambda: pytest.fail("Unreviewed role getter ran")
    with pytest.raises(case.module.proof.BridgeError):
        case.module.Plan(case.bpy, case.scene)
    assert target.getter_calls == []


def test_exposed_scene_role_is_refused_without_reading_it(roles):
    case = roles
    case.particle.bl_rna.properties.append(prop("scene", "POINTER", is_readonly=True))
    case.particle.getter_hooks["scene"] = lambda: pytest.fail("Unreviewed ParticleEdit.scene getter ran")
    with pytest.raises(case.module.proof.BridgeError):
        case.module.Plan(case.bpy, case.scene)
    assert case.particle.getter_calls == []


def test_null_active_object_is_refused_before_any_checkpoint_write(roles):
    case = roles
    case.bpy.context.view_layer.objects.active = None
    with pytest.raises(case.module.proof.BridgeError, match="non-null frozen active"):
        case.module.Plan(case.bpy, case.scene)


@pytest.mark.parametrize("field,value", [("modifiers", (object(),)), ("particle_systems", (object(),)),
                                          ("soft_body", object())])
def test_active_cache_sources_cannot_expand_the_sole_native_role_prediction(roles, field, value):
    case = roles
    case.active._values[field] = value
    with pytest.raises(case.module.proof.BridgeError):
        case.module.Plan(case.bpy, case.scene)
