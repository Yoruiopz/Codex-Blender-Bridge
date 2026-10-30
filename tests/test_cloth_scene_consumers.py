"""Declared source slots must not be reconstructed from aggregate observations."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class Owner:
    def __init__(self, pointer, uid):
        self.pointer, self.session_uid = pointer, uid
        self.counts = {}
        self.users, self.use_fake_user = 1, False
    def as_pointer(self):
        return self.pointer
    def user_of_id(self, target):
        return self.counts[target]


@pytest.fixture
def scene_case(addon_package):
    m = importlib.import_module(f"{addon_package}.tools._cloth_scene_consumers")
    errors = importlib.import_module(f"{addon_package}.errors")
    home, target, wm = Owner(10, 1), Owner(20, 2), Owner(30, 3)
    workspace = (40, 4)
    wm.counts = {home: 1, target: 1}
    mapping = {home: {wm}, target: {wm}}
    home.frame_current, home.frame_subframe = 1, 0.0
    window = NS(as_pointer=lambda: 60, workspace=Owner(40, 4), screen=Owner(70, 7))
    bpy = NS(app=NS(build_hash=b"62c1db4208e8", version=(4, 5, 14)),
             data=NS(user_map=lambda **kwargs: mapping, as_pointer=lambda: 80),
             context=NS(window=window, scene=home, view_layer=NS(as_pointer=lambda: 90)))
    build = ("62c1db4208e8", (4, 5, 14), "USER")
    plan = m.DeclaredRoles(build, ((10, 1), (20, 2)),
                           (m.Role((30, 3), "window.scene", (20, 2)),
                            m.Role((30, 3), "window.unpinned_scene", (10, 1))),
                           (((10, 1), 1), ((20, 2), 1)), m.context(bpy))
    return NS(m=m, errors=errors, home=home, target=target, wm=wm, bpy=bpy,
              mapping=mapping, plan=plan, workspace=workspace)


def test_declared_different_scene_window_roles_are_separate(scene_case):
    c = scene_case
    before = c.plan
    rows = c.m.verify(c.bpy, before, (c.home, c.target))
    assert rows == (((10, 1), (((30, 3), 1),), 1, False),
                    ((20, 2), (((30, 3), 1),), 1, False))
    assert c.plan is before


def test_same_scene_roles_require_two_references_not_learned_one(scene_case):
    c = scene_case
    plan = c.m.completed_unpinned_exit(c.plan, window_manager=(30, 3), scene=(20, 2),
                                      source_workspace=c.workspace, source_unpinned=True, completed=True)
    c.mapping[c.home] = set()
    with pytest.raises(c.errors.BridgeError):
        c.m.verify(c.bpy, plan, (c.home, c.target))
    c.wm.counts[c.target] = 2
    assert c.m.verify(c.bpy, plan, (c.home, c.target))


@pytest.mark.parametrize("completion", [False, None, 1, "FINISHED"])
def test_queued_or_guessed_completion_cannot_advance_role(scene_case, completion):
    c = scene_case
    with pytest.raises(c.errors.BridgeError):
        c.m.completed_unpinned_exit(c.plan, window_manager=(30, 3), scene=(20, 2),
                                    source_workspace=c.workspace, source_unpinned=True, completed=completion)
    assert c.plan.expected((10, 1)) == (((30, 3), 1),)


def test_new_raw_alias_same_aggregate_total_is_rejected(scene_case):
    c = scene_case
    foreign = Owner(50, 5)
    foreign.counts[c.target] = 1
    c.mapping[c.target] = {foreign}
    with pytest.raises(c.errors.BridgeError):
        c.m.verify(c.bpy, c.plan, (c.home, c.target))


def test_scene_original_cannot_be_claimed_as_a_counted_slot(scene_case):
    c = scene_case
    with pytest.raises(c.errors.BridgeError):
        c.m.Role((20, 2), "scene.original", (20, 2))


def test_unexpected_particle_self_reference_is_not_subtracted(scene_case):
    c = scene_case
    c.target.counts[c.target] = 1
    c.mapping[c.target].add(c.target)
    with pytest.raises(c.errors.BridgeError):
        c.m.verify(c.bpy, c.plan, (c.home, c.target))


def test_uid_replacement_same_address_refuses(scene_case):
    c = scene_case
    c.target.session_uid += 1
    with pytest.raises(c.errors.BridgeError):
        c.m.verify(c.bpy, c.plan, (c.home, c.target))


@pytest.mark.parametrize("users", [0, 2, True, 1.0])
def test_user_accounting_is_exact_and_separate_from_query_counts(scene_case, users):
    c = scene_case
    c.target.users = users
    with pytest.raises(c.errors.BridgeError):
        c.m.verify(c.bpy, c.plan, (c.home, c.target))


def test_fake_user_accounted_separately(scene_case):
    c = scene_case
    c.target.users, c.target.use_fake_user = 2, True
    rows = c.m.verify(c.bpy, c.plan, (c.home, c.target))
    assert rows[1][-2:] == (2, True)


def test_duplicate_native_slot_cannot_hide_two_counts(scene_case):
    c = scene_case
    with pytest.raises(c.errors.BridgeError):
        c.m.DeclaredRoles(c.plan.build, c.plan.scenes, (*c.plan.roles, c.plan.roles[0]),
                         c.plan.real_users, c.plan.context)


def test_query_layout_sync_is_measured_and_cannot_be_rebased(scene_case):
    c = scene_case
    def query(**kwargs):
        c.bpy.context.window.screen = Owner(71, 8)
        return c.mapping
    c.bpy.data.user_map = query
    with pytest.raises(c.errors.BridgeError) as caught:
        c.m.verify(c.bpy, c.plan, (c.home, c.target))
    assert caught.value.context["reason"] == "SCENE_QUERY_LAYOUT_OR_CONTEXT_CHANGED"


def test_user_of_id_layout_sync_is_also_checked(scene_case):
    c = scene_case
    def count(target):
        c.bpy.context.window.screen = Owner(71, 8)
        return 1
    c.wm.user_of_id = count
    with pytest.raises(c.errors.BridgeError) as caught:
        c.m.verify(c.bpy, c.plan, (c.home, c.target))
    assert caught.value.context["reason"] == "SCENE_QUERY_LAYOUT_OR_CONTEXT_CHANGED"


def test_pinned_null_slot_does_not_establish_unpinned_exit(scene_case):
    c = scene_case
    with pytest.raises(c.errors.BridgeError):
        c.m.completed_unpinned_exit(c.plan, window_manager=(30, 3), scene=(20, 2),
                                    source_workspace=c.workspace, source_unpinned=False, completed=True)


def test_unpinned_exit_preserves_latent_pin_reference(scene_case):
    c = scene_case
    latent = c.m.Role(c.workspace, "workspace.pin_scene", (10, 1))
    plan = c.m.DeclaredRoles(c.plan.build, c.plan.scenes, (*c.plan.roles, latent),
                            c.plan.real_users, c.plan.context)
    advanced = c.m.completed_unpinned_exit(plan, window_manager=(30, 3), scene=(20, 2),
                                          source_workspace=c.workspace, source_unpinned=True, completed=True)
    assert latent in advanced.roles


@pytest.mark.parametrize("bad_build", [([1], (4, 5, 14), "USER"),
                                     ("62c1db4208e8", [4, 5, 14], "USER"),
                                     ("62c1db4208e8", (True, 5, 14), "USER")])
def test_malformed_unhashable_build_is_structured_refusal(scene_case, bad_build):
    c = scene_case
    with pytest.raises(c.errors.BridgeError):
        c.m.DeclaredRoles(bad_build, c.plan.scenes, c.plan.roles, c.plan.real_users, c.plan.context)


@pytest.mark.parametrize("bad_scenes", [([10, 1], (20, 2)), ((True, 1),), ((0, 1),)])
def test_malformed_identity_is_rejected_before_set_conversion(scene_case, bad_scenes):
    c = scene_case
    with pytest.raises(c.errors.BridgeError):
        c.m.DeclaredRoles(c.plan.build, bad_scenes, c.plan.roles, c.plan.real_users, c.plan.context)


@pytest.fixture
def particle_preparation(addon_package, monkeypatch):
    # Modeled synchronous native callback; real native provenance is separate.
    m = importlib.import_module(f"{addon_package}.tools._cloth_scene_consumers")
    errors = importlib.import_module(f"{addon_package}.errors")
    flags = {"writes": 0, "requirements": 0, "object_reads": 0, "deny": None, "after_write": None,
             "object": None, "native_scene": None, "boolean": False}
    class Empty(Owner):
        pass
    scene, empty = Owner(10, 1), Empty(20, 2)
    empty.__dict__.update(type="EMPTY", data=None, modifiers=(), particle_systems=(), soft_body=None,
                          library=None, override_library=None, is_editable=True)
    scene.frame_current, scene.frame_subframe = 1, 0.
    layer = Owner(30, 3)
    layer.objects = NS(active=empty)
    bpy = NS(app=NS(build_hash=b"62c1db4208e8", version=(4, 5, 14)), data=NS(as_pointer=lambda: 40),
             context=NS(mode="OBJECT", scene=scene, view_layer=layer,
                        window=NS(as_pointer=lambda: 50, workspace=Owner(60, 6), screen=Owner(70, 7))))
    class Particle(Owner):
        @property
        def show_particles(self):
            return flags["boolean"]
        @show_particles.setter
        def show_particles(self, value):
            flags["writes"] += 1
            flags["boolean"] = value
            flags["native_scene"], flags["object"] = bpy.context.scene, layer.objects.active
            if flags["after_write"] is not None:
                flags["after_write"]()
        @property
        def object(self):
            flags["object_reads"] += 1
            return flags["object"]
    particle, tools = Particle(80, 8), Owner(90, 9)
    def require(*permissions):
        flags["requirements"] += 1
        assert permissions == (m.Permission.EDIT_SCENE, m.Permission.EDIT_ANIMATION)
        if flags["requirements"] == flags["deny"]:
            raise errors.BridgeError("PERMISSION_DENIED", "Modeled live permission loss")
    monkeypatch.setattr(m, "_particle_class", lambda _bpy, kind: Empty if kind == "Object" else object)
    monkeypatch.setattr(m, "_particle_field", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(m, "_particle_settings", lambda *_args: (tools, particle))
    return NS(m=m, errors=errors, bpy=bpy, scene=scene, empty=empty, layer=layer, particle=particle, tools=tools,
              flags=flags, effects=[], context=NS(require=require), check=lambda: None)


def test_particle_self_role_comes_from_transition_not_measured_counts(particle_preparation):
    c = particle_preparation
    role = c.m.authenticate_particle_role(c.bpy, c.context, c.scene, c.empty, c.check, c.effects)
    assert role == c.m.Role((10, 1), "particle.scene", (10, 1))
    assert c.flags["writes"] == 1 and c.flags["boolean"] is False
    assert c.flags["native_scene"] is c.scene and c.flags["object"] is c.empty
    assert c.effects[0]["entered"] and c.effects[0]["returned"]
    assert c.effects[0]["latent_scene_object_references_assigned_verified"]
    assert c.effects[0]["hidden_Main_passivity_qualified"] is False


@pytest.mark.parametrize("deny", [1, 2, 3])
def test_particle_preparation_denial_retains_entry_return_without_late_reads(particle_preparation, deny):
    c = particle_preparation
    c.flags["deny"] = deny
    with pytest.raises(c.errors.BridgeError):
        c.m.authenticate_particle_role(c.bpy, c.context, c.scene, c.empty, c.check, c.effects)
    assert c.flags["writes"] == (1 if deny == 3 else 0) and c.flags["object_reads"] == 0
    if c.effects:
        assert c.effects[0]["entered"] is (deny == 3) and c.effects[0]["returned"] is (deny == 3)
        assert c.effects[0]["latent_scene_object_references_assigned_verified"] is False


@pytest.mark.parametrize("field,value", [("type", "MESH"), ("data", object()), ("modifiers", [object()]),
    ("particle_systems", [object()]), ("soft_body", object()), ("library", object()), ("is_editable", False)])
def test_particle_role_requires_owned_empty_with_no_cache(particle_preparation, field, value):
    c = particle_preparation
    setattr(c.empty, field, value)
    with pytest.raises(c.errors.BridgeError):
        c.m.authenticate_particle_role(c.bpy, c.context, c.scene, c.empty, c.check, c.effects)
    assert c.flags["writes"] == 0 and c.effects == []


@pytest.mark.parametrize("change", ["context", "particle_identity", "object_witness"])
def test_particle_return_is_not_authority_after_changed_scope(particle_preparation, change):
    c = particle_preparation
    def changed():
        if change == "context":
            c.scene.frame_current += 1
        elif change == "particle_identity":
            c.particle.pointer += 1
        else:
            c.flags["object"] = None
    c.flags["after_write"] = changed
    with pytest.raises(c.errors.BridgeError):
        c.m.authenticate_particle_role(c.bpy, c.context, c.scene, c.empty, c.check, c.effects)
    assert c.flags["writes"] == 1 and c.effects[0]["returned"]
    assert c.effects[0]["latent_scene_object_references_assigned_verified"] is False


@pytest.mark.parametrize("provider_call", [2, 3])
def test_late_particle_field_shadow_is_guarded_before_foreign_getter(particle_preparation, monkeypatch, provider_call):
    c = particle_preparation
    foreign_calls = []
    original = type(c.particle).show_particles
    def foreign(_owner):
        foreign_calls.append(True)
        raise AssertionError("Unqualified foreign getter")
    changed = property(foreign, original.fset)
    def metadata_guard(_bpy, owner, _kind, name, *_args, **_kwargs):
        if name == "show_particles" and vars(type(owner)).get(name) is changed:
            raise c.errors.BridgeError("NOT_IMPLEMENTED", "Modeled changed native field declaration")
    before = c.context.require
    def provider(*permissions):
        before(*permissions)
        if c.flags["requirements"] == provider_call:
            monkeypatch.setattr(type(c.particle), "show_particles", changed)
    monkeypatch.setattr(c.m, "_particle_field", metadata_guard)
    c.context.require = provider
    with pytest.raises(c.errors.BridgeError):
        c.m.authenticate_particle_role(c.bpy, c.context, c.scene, c.empty, c.check, c.effects)
    assert foreign_calls == [] and c.flags["writes"] == (1 if provider_call == 3 else 0)


def test_role_mismatch_retains_compared_facts_without_adopting_them(scene_case):
    c = scene_case
    c.wm.counts[c.home] = 2
    before = c.plan
    with pytest.raises(c.errors.BridgeError) as failure:
        c.m.verify(c.bpy, before, (c.home, c.target))
    assert failure.value.context["reason"] == "SCENE_CONSUMER_ROLES_CHANGED"
    assert failure.value.context["scene"] == (10, 1)
    assert failure.value.context["expected"] == (((30, 3), 1),)
    assert failure.value.context["observed"] == (((30, 3), 2),)
    assert c.plan is before and before.expected((10, 1)) == (((30, 3), 1),)
