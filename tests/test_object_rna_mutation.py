"""Adversarial live boundaries, field CAS and measured RNA compensation."""
from __future__ import annotations

import importlib
from contextlib import nullcontext
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


@pytest.fixture
def boolean_apply(env, addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.modifiers")
    _mesh(env)
    material = RNA(name="Shared Finish", users=2, session_uid=101)
    env.obj.data.materials = [material]
    env.obj.material_slots = [NS(link="DATA", material=material)]
    cutter_data = RNA(**vars(env.obj.data))
    cutter_data.name, cutter_data.session_uid = "Cutter Mesh", 11
    cutter_data.materials, cutter_data.animation_data = [material], None
    cutter_data.polygons = []
    cutter = RNA(**vars(env.obj))
    cutter.name, cutter.session_uid, cutter.data = "Cutter", 2, cutter_data
    cutter.users, cutter.parent = 1, None
    cutter.material_slots, cutter.modifiers, cutter.constraints = [NS(link="DATA", material=material)], Components(), Components()
    cutter.instance_type, cutter.rigid_body = "NONE", None
    env.bpy.data.objects.append(cutter)
    modifier = env.obj.modifiers.new(name="Owned Boolean", type="BOOLEAN")
    modifier.operand_type, modifier.object = "OBJECT", cutter
    modifier.material_mode, modifier.solver = "INDEX", "EXACT"
    modifier.bl_rna.properties["operand_type"] = prop("operand_type", "ENUM")
    modifier.bl_rna.properties["object"] = prop("object", "POINTER")
    modifier.bl_rna.properties["material_mode"] = prop("material_mode", "ENUM")
    modifier.bl_rna.properties["material_mode"].enum_items = [NS(identifier=value) for value in ("INDEX", "TRANSFER")]
    modifier.bl_rna.properties["solver"] = prop("solver", "ENUM")
    env.context.registry.register("modifier.apply", lambda *_: None, permissions=("TRANSFORM_OBJECTS",), toolset="objects", modifies=True)
    calls = []

    class Apply:
        def poll(self):
            return True

        def __call__(self, **params):
            calls.append(params)
            env.obj.modifiers.remove(modifier)
            return {"FINISHED"}

    env.bpy.ops = NS(object=NS(modifier_apply=Apply()))
    env.bpy.context.temp_override = lambda **_: nullcontext()
    monkeypatch.setattr(module, "require_blender", lambda: env.bpy)
    monkeypatch.setattr(module, "_object", lambda _: env.obj)
    monkeypatch.setattr(module, "clear_selection_references", lambda _: None)
    env.modifiers_module, env.cutter, env.modifier, env.native_calls = module, cutter, modifier, calls
    return env


@pytest.mark.parametrize("bindings", ["foreign", "zero", "same_name", "null", "duplicate"])
def test_boolean_material_conversion_is_refused_before_native_apply(boolean_apply, bindings):
    case = boolean_apply
    material = RNA(name="Finish", users=1, session_uid=101)
    case.obj.data.materials = [material]
    case.obj.material_slots = [NS(link="DATA", material=material)]
    other = RNA(name="Finish", users=1, session_uid=102)
    chosen = {"foreign": [other], "zero": [], "same_name": [other], "null": [None], "duplicate": [material, material]}[bindings]
    case.cutter.data.materials = chosen
    case.cutter.material_slots = [NS(link="DATA", material=item) for item in chosen]
    before = case.module._object_state(case.obj)
    with pytest.raises(case.module.BridgeError) as error:
        case.modifiers_module.apply_modifier(case.context, {"object_name": case.obj.name, "modifier_name": case.modifier.name})
    assert error.value.code == "NOT_IMPLEMENTED"
    assert not case.native_calls and case.obj.modifiers.get(case.modifier.name) is case.modifier
    assert case.module._object_state(case.obj) == before
    assert case.cutter.data.materials == chosen


@pytest.mark.parametrize("dependency", ["collection", "empty", "missing", "modifier", "constraint", "parent", "animation", "data_animation", "shape_keys", "instance", "rigid_body", "field"])
def test_boolean_unreviewed_operand_dependencies_are_refused_before_native_apply(boolean_apply, dependency):
    case = boolean_apply
    if dependency == "collection":
        case.modifier.operand_type = "COLLECTION"
    elif dependency == "empty":
        case.cutter.type = "EMPTY"
    elif dependency == "missing":
        case.modifier.object = None
    elif dependency == "modifier":
        case.cutter.modifiers.new()
    elif dependency == "constraint":
        case.cutter.constraints.new()
    elif dependency == "parent":
        case.cutter.parent = case.obj
    elif dependency == "animation":
        case.cutter.animation_data = object()
    elif dependency == "data_animation":
        case.cutter.data.animation_data = object()
    elif dependency == "shape_keys":
        case.cutter.data.shape_keys = object()
    elif dependency == "instance":
        case.cutter.instance_type = "FACES"
    elif dependency == "rigid_body":
        case.cutter.rigid_body = object()
    else:
        case.cutter.field = NS(type="FORCE")
    with pytest.raises(case.module.BridgeError) as error:
        case.modifiers_module.apply_modifier(case.context, {"object_name": case.obj.name, "modifier_name": case.modifier.name})
    assert error.value.code == "NOT_IMPLEMENTED"
    assert not case.native_calls and case.obj.modifiers.get(case.modifier.name) is case.modifier


def test_boolean_exact_shared_material_id_static_operand_can_apply(boolean_apply):
    case = boolean_apply
    result = case.modifiers_module.apply_modifier(case.context, {"object_name": case.obj.name, "modifier_name": case.modifier.name})
    assert result["verified"] and len(case.native_calls) == 1
    assert not case.obj.modifiers and case.cutter.data.materials == case.obj.data.materials


def test_boolean_material_mode_can_be_inspected_and_corrected_through_typed_tools(boolean_apply):
    case = boolean_apply
    params = {"object_name": case.obj.name, "modifier_name": case.modifier.name}
    inspected = case.modifiers_module.inspect_modifiers(case.context, params)
    assert inspected["modifier"]["settings"]["material_mode"] == "INDEX"
    before_bindings = tuple(case.obj.data.materials), tuple(case.cutter.data.materials)
    result = case.modifiers_module.set_modifier(case.context, {**params, "settings": {"material_mode": "TRANSFER"}})
    assert result["updated_properties"] == ["material_mode"]
    assert case.modifiers_module.inspect_modifiers(case.context, params)["modifier"]["settings"]["material_mode"] == "TRANSFER"
    with pytest.raises(case.module.BridgeError) as error:
        case.modifiers_module.apply_modifier(case.context, params)
    assert error.value.code == "NOT_IMPLEMENTED" and not case.native_calls
    case.modifiers_module.set_modifier(case.context, {**params, "settings": {"material_mode": "INDEX"}})
    assert (tuple(case.obj.data.materials), tuple(case.cutter.data.materials)) == before_bindings
    assert case.modifiers_module.apply_modifier(case.context, params)["verified"]


@pytest.mark.parametrize("mode", ["BY_NAME", "index", True, 0, None])
def test_boolean_material_mode_invalid_enum_is_refused_without_changing_modifier(boolean_apply, mode):
    case = boolean_apply
    before = case.module.component_state(case.modifier)
    with pytest.raises(case.module.BridgeError) as error:
        case.modifiers_module.set_modifier(case.context, {"object_name": case.obj.name, "modifier_name": case.modifier.name,
                                                        "settings": {"material_mode": mode}})
    assert error.value.code == "INVALID_ARGUMENT"
    assert case.module.component_state(case.modifier) == before and not case.native_calls


@pytest.mark.parametrize("change", ["target_object_link", "source_object_link", "source_index", "target_index", "material_mode", "solver", "target_zero", "target_multiple", "target_null"])
def test_boolean_unreviewed_binding_profiles_are_refused_before_native_apply(boolean_apply, change):
    case = boolean_apply
    if change == "target_object_link":
        case.obj.material_slots[0].link = "OBJECT"
    elif change == "source_object_link":
        case.cutter.material_slots[0].link = "OBJECT"
    elif change == "source_index":
        case.cutter.data.polygons.append(NS(material_index=1, vertices=(), loop_start=0, loop_total=0))
    elif change == "target_index":
        case.obj.data.polygons.append(NS(material_index=1, vertices=(), loop_start=0, loop_total=0))
    elif change == "material_mode":
        case.modifier.material_mode = "TRANSFER"
    elif change == "solver":
        case.modifier.solver = "FAST"
    elif change == "target_zero":
        case.obj.data.materials, case.obj.material_slots = [], []
    elif change == "target_multiple":
        case.obj.data.materials *= 2
        case.obj.material_slots *= 2
    else:
        case.obj.data.materials[0], case.obj.material_slots[0].material = None, None
    with pytest.raises(case.module.BridgeError) as error:
        case.modifiers_module.apply_modifier(case.context, {"object_name": case.obj.name, "modifier_name": case.modifier.name})
    assert error.value.code == "NOT_IMPLEMENTED"
    assert not case.native_calls and case.obj.modifiers.get(case.modifier.name) is case.modifier


@pytest.mark.parametrize("change", ["binding", "data", "replacement"])
def test_final_boolean_provider_cannot_replace_or_rebind_frozen_operand(boolean_apply, change):
    case = boolean_apply
    retained = []

    def manual():
        if retained:
            return
        if change == "binding":
            material = RNA(name="Manual Material", users=1, session_uid=103)
            case.cutter.data.materials.append(material)
        elif change == "data":
            replacement = RNA(**vars(case.cutter.data))
            replacement.session_uid = 12
            case.cutter.data = replacement
        else:
            replacement = RNA(**vars(case.cutter))
            replacement.session_uid = 3
            case.bpy.data.objects.remove(case.cutter)
            case.bpy.data.objects.append(replacement)
        retained.append((case.cutter.data, tuple(case.cutter.data.materials), tuple(case.bpy.data.objects)))

    case.provider[0] = manual
    with pytest.raises(case.module.BridgeError):
        case.modifiers_module.apply_modifier(case.context, {"object_name": case.obj.name, "modifier_name": case.modifier.name})
    assert retained and not case.native_calls
    assert (case.cutter.data, tuple(case.cutter.data.materials), tuple(case.bpy.data.objects)) == retained[0]
    assert case.obj.modifiers.get(case.modifier.name) is case.modifier
