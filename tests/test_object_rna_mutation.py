"""Adversarial live boundaries, field CAS and measured RNA compensation."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class Properties(dict):
    def __iter__(self):
        return iter(self.values())


def prop(name, kind="FLOAT", readonly=False):
    return NS(identifier=name, type=kind, is_readonly=readonly, array_length=0,
              hard_min=-1e9, hard_max=1e9, is_enum_flag=False, enum_items=[])


class RNA(NS):
    __hash__ = object.__hash__
    __eq__ = object.__eq__
    __ne__ = object.__ne__


class Items(list):
    active = None

    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Components(Items):
    def new(self, name="Bevel", type="BEVEL"):
        component = RNA(name=name, type=type, width=1., segments=1,
                        bl_rna=NS(properties=Properties((p.identifier, p) for p in (prop("name", "STRING"), prop("width"), prop("segments", "INT")))))
        self.append(component)
        return component


@pytest.fixture
def env(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools._object_rna_mutation")
    rna = importlib.import_module(f"{addon_package}.tools._rna")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    obj = RNA(name="Owner", session_uid=1, type="EMPTY", data=None, library=None, override_library=None, is_editable=True,
              mode="OBJECT", location=(0., 0., 0.), rotation_mode="XYZ", rotation_euler=(0., 0., 0.),
              rotation_quaternion=(1., 0., 0., 0.), rotation_axis_angle=(0., 0., 1., 0.), scale=(1., 1., 1.),
              modifiers=Components(), constraints=Components(), users_collection=[], animation_data=None,
              bl_rna=NS(identifier="Object", properties=Properties((p.identifier, p) for p in (prop("name", "STRING"), prop("location"), prop("rotation_mode", "ENUM"), prop("scale")))))
    objects = Items([obj])
    objects.active = obj
    scene = RNA(name="Scene", frame_current=1, frame_subframe=0., collection=NS(objects=Items()), view_layers=[])
    obj.users_scene = [scene]
    users = {obj: set()}
    bpy = NS(context=NS(scene=scene, view_layer=NS(objects=objects), mode="OBJECT", selected_objects=[obj]),
             data=NS(filepath="", objects=objects, user_map=lambda *, subset: {value: users.get(value, set()) for value in subset}))
    flags = {"paused": False, "emergency_stopped": False}
    grants = {"TRANSFORM_OBJECTS": True}
    provider = [None]
    def allowed():
        if provider[0]:
            provider[0]()
        return grants
    registry = registry_module.ToolRegistry(enabled_toolsets=("objects", "modifiers", "constraints"))
    for name in ("modifier.set", "modifier.add", "modifier.remove", "constraint.set", "transform.set"):
        registry.register(name, lambda *_: None, permissions=(permissions.Permission.TRANSFORM_OBJECTS,), toolset="objects", modifies=True)
    context = registry_module.ToolContext(state=NS(snapshot=lambda: dict(flags)), permissions=permissions.PermissionManager(allowed), registry=registry, checkpoints=None)
    monkeypatch.setattr(module, "require_object_scope", lambda bpy, target, **kw: module.require_local_object(target, operation="test"))
    return NS(module=module, rna=rna, bpy=bpy, obj=obj, context=context, flags=flags, grants=grants, provider=provider, users=users)


def boundary(env, *, transform=False):
    return env.module.Boundary(env.bpy, env.context, "transform.set" if transform else "modifier.set", env.obj,
                               kind=None if transform else "modifiers", transform=transform)


def test_direct_batch_measures_requested_fields_and_protects_siblings(env):
    owned = env.obj.modifiers.new()
    other = env.obj.modifiers.new(name="Protected")
    guard = boundary(env)
    env.rna.apply_assignments(owned, (env.rna.RNAAssignment("width", 2.), env.rna.RNAAssignment("segments", 4)), boundary=guard)
    assert owned.width == 2. and owned.segments == 4
    assert other.width == 1. and other.segments == 1
    assert guard.affected == [env.obj.name]


@pytest.mark.parametrize("stop", ["permission", "paused", "emergency_stopped", "cancel"])
def test_no_late_field_or_compensation_after_live_stop(env, stop):
    owned = env.obj.modifiers.new()
    guard = boundary(env)
    retained = []
    def callback():
        if owned.width != 2.:
            return
        retained.append((owned.width, owned.segments))
        if stop == "permission":
            env.grants["TRANSFORM_OBJECTS"] = False
        elif stop == "cancel":
            raise env.module.BridgeError("TIMEOUT", "Caller expired")
        else:
            env.flags[stop] = True
    env.context.check_cancelled = callback
    with pytest.raises(env.module.BridgeError) as caught:
        env.rna.apply_assignments(owned, (env.rna.RNAAssignment("width", 2.), env.rna.RNAAssignment("segments", 4)), boundary=guard)
    assert retained and (owned.width, owned.segments) == (2., 1)
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]


@pytest.mark.parametrize("change", ["owned", "sibling", "identity", "scene", "selection", "animation", "consumer"])
def test_provider_changes_after_first_field_are_preserved(env, change):
    owned = env.obj.modifiers.new()
    sibling = env.obj.modifiers.new(name="Protected")
    guard = boundary(env)
    fired = []
    def callback():
        if owned.width != 2. or fired:
            return
        fired.append(True)
        if change == "owned":
            owned.width = 9.
        elif change == "sibling":
            sibling.width = 7.
        elif change == "identity":
            env.obj.session_uid += 1
        elif change == "scene":
            env.bpy.context.scene = NS()
        elif change == "selection":
            env.bpy.context.selected_objects = []
        elif change == "animation":
            env.obj.animation_data = NS(action=None, drivers=[], nla_tracks=[])
        else:
            extra = RNA(name="Foreign", bl_rna=NS(identifier="World"), user_of_id=lambda _: 1)
            env.users[env.obj].add(extra)
    env.provider[0] = callback
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("width", 2.), env.rna.RNAAssignment("segments", 4)))
    assert fired and owned.segments == 1
    assert not caught.value.context["rollback_verified"]
    assert owned.width == (9. if change == "owned" else 2.)
    assert sibling.width == (7. if change == "sibling" else 1.)


def test_one_shot_boundary_failure_restores_exact_snapshot(env):
    owned = env.obj.modifiers.new()
    guard = boundary(env)
    fired = []
    def callback():
        if owned.width == 2. and not fired:
            fired.append(True)
            raise RuntimeError("one-shot postwrite failure")
    env.context.check_cancelled = callback
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("width", 2.), env.rna.RNAAssignment("segments", 4)))
    assert fired and (owned.width, owned.segments) == (1., 1)
    assert caught.value.context["rollback_verified"] and not caught.value.context["possible_mutation"]


def test_implicit_coupled_setter_delta_is_never_adopted_or_overwritten(env):
    class Coupled(RNA):
        def __setattr__(self, field, value):
            super().__setattr__(field, value)
            if field == "width" and value == 2.:
                super().__setattr__("segments", 9)
    original = env.obj.modifiers.new()
    owned = Coupled(**vars(original))
    env.obj.modifiers[:] = [owned]
    guard = boundary(env)
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("width", 2.),))
    assert (owned.width, owned.segments) == (2., 9)
    assert not caught.value.context["rollback_verified"]


def test_last_permission_provider_cannot_start_write_after_pausing(env):
    owned = env.obj.modifiers.new()
    guard = boundary(env)
    env.provider[0] = lambda: env.flags.update(paused=True)
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("width", 2.),))
    assert owned.width == 1. and caught.value.code == "AGENT_PAUSED"
    assert not caught.value.context["execution_started"]


def test_transform_snapshot_preserves_other_rotation_modes_and_protected_channels(env):
    guard = boundary(env, transform=True)
    guard.apply(env.obj, (env.rna.RNAAssignment("location", (1., 2., 3.)),))
    assert env.obj.location == (1., 2., 3.)
    assert env.obj.scale == (1., 1., 1.) and env.obj.rotation_quaternion == (1., 0., 0., 0.)


def test_allocation_receipt_retained_when_stop_prevents_setup(env):
    guard = boundary(env)
    def callback():
        if env.obj.modifiers:
            env.flags["paused"] = True
    env.context.check_cancelled = callback
    with pytest.raises(env.module.BridgeError):
        guard.allocate(lambda: env.obj.modifiers.new(), "BEVEL")
    assert len(env.obj.modifiers) == 1 and guard.allocated is env.obj.modifiers[0]
    with pytest.raises(env.module.BridgeError):
        guard.remove(guard.allocated)
    assert len(env.obj.modifiers) == 1


@pytest.mark.parametrize("stop", ["TIMEOUT", "PERMISSION_DENIED", "TOOLSET_DISABLED", "AGENT_PAUSED", "EMERGENCY_STOPPED"])
def test_transient_stop_is_latched_against_later_compensation(env, stop):
    owned = env.obj.modifiers.new()
    guard = boundary(env)
    fired = []
    def callback():
        if owned.width == 2. and not fired:
            fired.append(True)
            raise env.module.BridgeError(stop, "One-shot stop")
    env.context.check_cancelled = callback
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("width", 2.),))
    assert fired and owned.width == 2.
    assert guard.stopped is not None and not caught.value.context["rollback_verified"]


def test_float_tolerance_never_accepts_an_unrequested_sibling_delta(env):
    class Coupled(RNA):
        def __setattr__(self, field, value):
            super().__setattr__(field, value)
            if field == "width" and value == 2.:
                sibling.width += 1e-7
    original = env.obj.modifiers.new()
    owned = Coupled(**vars(original))
    sibling = env.obj.modifiers.new(name="Protected")
    env.obj.modifiers[0] = owned
    guard = boundary(env)
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("width", 2.),))
    assert sibling.width > 1. and owned.width == 2.
    assert not caught.value.context["rollback_verified"]


def test_local_object_consumer_closure_is_reported_and_protected(env):
    consumer = RNA(**vars(env.obj))
    consumer.name, consumer.session_uid = "Dependent", 2
    consumer.modifiers, consumer.constraints = Components(), Components()
    consumer.user_of_id = lambda value: int(value is env.obj)
    env.bpy.data.objects.append(consumer)
    env.users[env.obj].add(consumer)
    guard = boundary(env, transform=True)
    guard.apply(env.obj, (env.rna.RNAAssignment("location", (1., 2., 3.)),))
    assert set(guard.affected) == {"Owner", "Dependent"}
    assert consumer.location == (0., 0., 0.)
    consumer.location = (99., 0., 0.)
    with pytest.raises(env.module.BridgeError):
        guard.write(env.obj, "scale", (2., 2., 2.))
    assert env.obj.scale == (1., 1., 1.)


def test_pointer_source_foreign_consumers_are_checked_after_own_reference_delta(env):
    owned = env.obj.modifiers.new()
    owned.target = None
    owned.bl_rna.properties["target"] = prop("target", "POINTER")
    source = RNA(**vars(env.obj))
    source.name, source.session_uid = "Source", 2
    source.modifiers, source.constraints = Components(), Components()
    env.bpy.data.objects.append(source)
    foreign = RNA(name="Foreign", user_of_id=lambda _: 1)
    env.obj.user_of_id = lambda value: sum(getattr(item, "target", None) is value for item in env.obj.modifiers)
    def user_map(*, subset):
        return {value: (set(env.users.get(value, set())) | ({env.obj} if value is source and env.obj.user_of_id(source) else set())) for value in subset}
    env.bpy.data.user_map = user_map
    guard = boundary(env)
    fired = []
    def callback():
        if owned.target is source and not fired:
            fired.append(True)
            env.users.setdefault(source, set()).add(foreign)
    env.context.check_cancelled = callback
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("target", source), env.rna.RNAAssignment("width", 2.)))
    assert fired and owned.target is source and owned.width == 1.
    assert not caught.value.context["rollback_verified"]


def _mesh(env):
    env.obj.type = "MESH"
    env.obj.data = RNA(name="Mesh", session_uid=10, users=1, library=None, override_library=None,
                       is_editable=True, materials=[], shape_keys=None, vertices=[], edges=[], loops=[], polygons=[], attributes=[],
                       bl_rna=NS(properties=Properties({"name": prop("name", "STRING")})))
    return env.obj.data


@pytest.mark.parametrize("field,value", [("name", "Foreign Mesh Name"), ("users", 2), ("library", object()), ("is_editable", False)])
def test_native_apply_never_adopts_mesh_metadata_or_ownership_changes(env, field, value):
    mesh = _mesh(env)
    owned = env.obj.modifiers.new(type="TRIANGULATE")
    guard = boundary(env)
    def operation():
        env.obj.modifiers.remove(owned)
        setattr(mesh, field, value)
        return {"FINISHED"}
    with pytest.raises(env.module.BridgeError) as caught:
        guard.native_apply(operation, removed=owned)
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]
    assert getattr(mesh, field) == value and not env.obj.modifiers


def test_native_apply_receipt_precedes_the_postwrite_provider_callback(env):
    mesh = _mesh(env)
    owned = env.obj.modifiers.new(type="TRIANGULATE")
    guard = boundary(env)
    fired = []
    def callback():
        if not env.obj.modifiers and not fired:
            fired.append(True)
            mesh.name = "Manual metadata edit"
    env.context.check_cancelled = callback
    def operation():
        env.obj.modifiers.remove(owned)
        return {"FINISHED"}
    with pytest.raises(env.module.BridgeError) as caught:
        guard.native_apply(operation, removed=owned)
    assert fired and mesh.name == "Manual metadata edit"
    assert not caught.value.context["rollback_verified"]


def test_last_permission_provider_cannot_disable_the_toolset_then_write(env):
    owned = env.obj.modifiers.new()
    guard = boundary(env)
    calls = []
    def callback():
        calls.append(True)
        if len(calls) == 2:
            env.context.registry.disable_toolset("objects")
    env.provider[0] = callback
    with pytest.raises(env.module.BridgeError) as caught:
        guard.apply(owned, (env.rna.RNAAssignment("width", 2.),))
    assert caught.value.code == "TOOLSET_DISABLED" and owned.width == 1.
    assert not caught.value.context["execution_started"]
