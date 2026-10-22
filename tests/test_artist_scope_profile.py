"""The first protected transform profile rejects unknown effects before writes."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


def native(**values):
    return NS(**values, bl_rna=NS(properties=[NS(identifier=name, type="POINTER", is_runtime=False) for name in values]))


@pytest.fixture
def profile(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._artist_scope_profile")
    collection = native(children=[])
    scene = native(collection=collection)
    mesh = native(animation_data=None, shape_keys=None)
    obj = native(type="MESH", data=mesh, animation_data=None, modifiers=[], constraints=[],
                 users_scene=[scene], users_collection=[collection], instance_type="NONE", instance_collection=None,
                 field=native(type="NONE"), rigid_body=None, rigid_body_constraint=None, soft_body=None, particle_systems=[])
    data = native(objects=[obj], collections=[collection], scenes=[scene], meshes=[mesh])
    for prop in data.bl_rna.properties:
        prop.type = "COLLECTION"
    handlers = NS(**dict.fromkeys(module.HANDLER_LISTS, ()))
    return NS(module=module, obj=obj, mesh=mesh, scene=scene, collection=collection,
              bpy=NS(data=data, app=NS(handlers=handlers)))


def test_static_shared_mesh_and_readonly_constraint_source_remain_possible(profile):
    other = native(type="MESH", data=profile.mesh, animation_data=None,
                   users_scene=[profile.scene], users_collection=[profile.collection])
    profile.bpy.data.objects.append(other)
    profile.obj.constraints.append(native(type="COPY_LOCATION", target=other))
    profile.module.pre_closure(profile.bpy)
    profile.module.require_profile(profile.bpy, [profile.obj])


@pytest.mark.parametrize("handler_name", ["depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post"])
def test_installed_handlers_are_rejected_without_calling_them(profile, handler_name):
    def forbidden(*_args):
        raise AssertionError("Handler must not execute")
    setattr(profile.bpy.app.handlers, handler_name, [forbidden])
    with pytest.raises(profile.module.BridgeError) as error:
        profile.module.require_profile(profile.bpy, [profile.obj])
    assert error.value.context["inventory"] == handler_name


@pytest.mark.parametrize("owner", ["object", "data", "modifier", "geometry", "attribute"])
def test_runtime_descriptor_is_rejected_before_its_getter(profile, owner):
    class Getter:
        def __init__(self):
            self.bl_rna = NS(properties=[NS(identifier="probe", is_runtime=True)])

        @property
        def probe(self):
            raise AssertionError("Runtime RNA getter must not execute")

    dangerous = Getter()
    if owner == "object":
        dangerous.__dict__.update(vars(profile.obj))
        dangerous.bl_rna.properties.append(NS(identifier="probe", is_runtime=True))
        profile.bpy.data.objects[:] = [dangerous]
        profile.obj = dangerous
    elif owner == "data":
        profile.bpy.data.meshes.append(dangerous)
        profile.obj.data = dangerous
    elif owner == "modifier":
        profile.obj.modifiers.append(dangerous)
    elif owner == "geometry":
        profile.mesh.vertices = [dangerous]
        profile.mesh.bl_rna.properties.append(NS(identifier="vertices", is_runtime=False))
    else:
        profile.mesh.attributes = [native(data=[dangerous])]
        profile.mesh.bl_rna.properties.append(NS(identifier="attributes", is_runtime=False))
    with pytest.raises(profile.module.BridgeError) as error:
        profile.module.require_profile(profile.bpy, [profile.obj])
    assert error.value.context["property"] == "probe"


def test_unused_runtime_fields_on_unread_global_ids_do_not_invoke_getters(profile):
    class Getter:
        bl_rna = NS(properties=[NS(identifier="active_addon", is_runtime=True)])

        @property
        def active_addon(self):
            raise AssertionError("Unmeasured workspace getter must not execute")
    profile.mesh.node_tree = Getter()
    profile.mesh.bl_rna.properties.append(NS(identifier="node_tree", is_runtime=False))
    profile.module.require_profile(profile.bpy, [profile.obj])


@pytest.mark.parametrize("driver_type", ["SCRIPTED", "AVERAGE"])
def test_global_drivers_are_explicitly_unsupported_without_evaluation(profile, driver_type):
    other = native(animation_data=native(drivers=[native(driver=native(type=driver_type))]))
    profile.bpy.data.meshes.append(other)
    with pytest.raises(profile.module.BridgeError) as error:
        profile.module.require_profile(profile.bpy, [profile.obj])
    assert error.value.context["inventory"] == "drivers"


@pytest.mark.parametrize("role", ["field", "rigid_body", "rigid_body_constraint", "soft_body", "particle_systems", "instance_type"])
def test_implicit_physics_and_instances_are_rejected(profile, role):
    setattr(profile.obj, role, {"field": native(type="FORCE"), "particle_systems": [native()], "instance_type": "COLLECTION"}.get(role, native()))
    with pytest.raises(profile.module.BridgeError):
        profile.module.require_profile(profile.bpy, [profile.obj])


@pytest.mark.parametrize("kind", sorted({"COLLISION", "CLOTH", "FLUID", "DYNAMIC_PAINT", "NODES"}))
def test_implicit_modifier_effects_are_rejected(profile, kind):
    profile.obj.modifiers.append(native(type=kind))
    with pytest.raises(profile.module.BridgeError):
        profile.module.require_profile(profile.bpy, [profile.obj])


@pytest.mark.parametrize("change", ["animation", "rig", "shape_keys"])
def test_affected_complex_snapshot_paths_fail_closed(profile, change):
    if change == "animation":
        profile.obj.animation_data = native(drivers=[])
    elif change == "rig":
        profile.obj.type = "ARMATURE"
    else:
        profile.mesh.shape_keys = native(animation_data=None)
    with pytest.raises(profile.module.BridgeError):
        profile.module.require_profile(profile.bpy, [profile.obj])


@pytest.mark.parametrize("inventory", ["objects", "collections", "scenes", "children", "users_scene", "users_collection"])
def test_inventory_and_enqueue_inputs_are_bounded(profile, monkeypatch, inventory):
    limits = {"objects": "MAX_OBJECTS", "collections": "MAX_COLLECTIONS", "scenes": "MAX_SCENES",
              "children": "MAX_COLLECTIONS", "users_scene": "MAX_SCENES", "users_collection": "MAX_OWNING_COLLECTIONS"}
    monkeypatch.setattr(profile.module, limits[inventory], 1)
    owner = profile.bpy.data if inventory in {"objects", "collections", "scenes"} else profile.collection if inventory == "children" else profile.obj
    setattr(owner, inventory, [native(), native()])
    with pytest.raises(profile.module.BridgeError):
        profile.module.pre_closure(profile.bpy)


def test_initial_callback_cannot_install_a_handler_after_terminal_gate(profile):
    calls = []
    def callback():
        calls.append(True)
        profile.bpy.app.handlers.depsgraph_update_pre = [lambda: None]
    with pytest.raises(profile.module.BridgeError):
        profile.module.require_profile(profile.bpy, [profile.obj], callback)
    assert calls == [True]


def test_foreign_owners_and_collection_links_are_not_silently_filtered(profile):
    profile.obj.users_collection = [native(children=[])]
    with pytest.raises(profile.module.BridgeError):
        profile.module.pre_closure(profile.bpy)


def test_geometry_inventory_is_bounded_before_snapshot(profile, monkeypatch):
    monkeypatch.setattr(profile.module, "MAX_GEOMETRY_ELEMENTS", 1)
    profile.mesh.vertices = [native(), native()]
    profile.mesh.bl_rna.properties.append(NS(identifier="vertices", is_runtime=False))
    with pytest.raises(profile.module.BridgeError):
        profile.module.require_profile(profile.bpy, [profile.obj])
