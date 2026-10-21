from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.rig_ik import TOOL_DATA, TOOL_NAMES, RigIKTools, load_definitions


class Items(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class ID:
    def __init__(self, name, **attrs):
        self.name, self.library, self.override_library, self.is_editable = name, None, None, True
        self.__dict__.update(attrs)


class Constraint:
    def __init__(self):
        self.name, self.type = "IK", "IK"
        self.target = self.pole_target = self.space_object = None
        self.subtarget = self.pole_subtarget = ""
        self.chain_count, self.iterations = 0, 500
        self.use_tail = self.use_stretch = self.use_location = True
        self.use_rotation = self.mute = False
        self.influence, self.pole_angle = 1.0, 0.0
        self.ik_type, self.owner_space, self.target_space = "COPY_POSE", "WORLD", "WORLD"
        self.fail = None

    def __setattr__(self, key, value):
        if self.__dict__.get("fail") == key:
            self.__dict__["fail"] = None
            self.__dict__[key] = value
            raise RuntimeError("Partial native setter")
        super().__setattr__(key, value)


class Constraints(Items):
    def new(self, kind):
        item = Constraint()
        self.append(item)
        return item


@pytest.fixture
def ik(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.rig_ik")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    matrix = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
    root = ID("Upper", parent=None, children=Items(), constraints=Constraints(), location=(0, 0, 0), rotation_mode="XYZ")
    tip = ID("Lower", parent=root, children=Items(), constraints=Constraints(), location=(0, 0, 0), rotation_mode="XYZ")
    root.children.append(tip)
    for bone in (root, tip):
        bone.bone = ID(bone.name, head_local=(0, 0, 0), tail_local=(0, 1, 0), use_deform=True, use_connect=bone == tip, length=1.)
    rig = ID("Rig", type="ARMATURE", pose=NS(bones=Items([root, tip]), ik_solver="LEGACY"), data=ID("Rig Data"))
    target, pole = ID("Target", type="EMPTY", data=None), ID("Pole", type="EMPTY", data=None)
    modifier = ID("Skin", type="ARMATURE", object=rig, use_vertex_groups=True, use_bone_envelopes=False,
                  use_deform_preserve_volume=False, use_multi_modifier=False, vertex_group="", show_viewport=True, show_render=True)
    mesh = ID("Skin", type="MESH", data=ID("Skin Data"), modifiers=Items([modifier]))
    objects = Items([rig, target, pole, mesh])
    scene = ID("Scene", objects=objects)
    for obj in objects:
        obj.parent, obj.constraints, obj.animation_data = None, Constraints(), None
        obj.mode, obj.matrix_world = "OBJECT", matrix
        obj.users_collection, obj.users_scene = [], [scene]
    mesh.user_of_id = lambda obj: int(obj == rig)
    rig.user_of_id = lambda obj: sum(int(constraint.target == obj) + int(constraint.pole_target == obj) for constraint in tip.constraints)
    external = {}

    def users(**kwargs):
        result = {rig: {mesh}, target: set(), pole: set(), mesh: set()}
        for constraint in tip.constraints:
            for control in (constraint.target, constraint.pole_target):
                if control in result:
                    result[control].add(rig)
        for obj, consumers in external.items():
            result[obj].update(consumers)
        return result

    bpy = NS(context=NS(mode="OBJECT", scene=scene, view_layer=NS(objects=objects, update=lambda: None)),
             data=NS(objects=objects, user_map=users, filepath=""))
    flags = {"paused": False, "emergency_stopped": False}
    grants = {item.value: True for item in permission_module.Permission}
    permissions = permission_module.PermissionManager(lambda: grants)
    registry = registry_module.ToolRegistry(enabled_toolsets=("rigging",))
    module.register_tools(registry)
    context = registry_module.ToolContext(state=NS(snapshot=lambda: dict(flags)), permissions=permissions,
                                          registry=registry, checkpoints=None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    params = {"object_name": "Rig", "root_bone_name": "Upper", "tip_bone_name": "Lower", "target_object": "Target",
              "pole_object": "Pole", "affected_meshes": ["Skin"], "constraint_name": "Limb IK"}
    return NS(module=module, context=context, bpy=bpy, rig=rig, root=root, tip=tip, target=target, pole=pole,
              mesh=mesh, modifier=modifier, params=params, grants=grants, flags=flags, external=external)


def configure(ik, **kwargs):
    return ik.module.ik_configure(ik.context, {**ik.params, "create": not bool(ik.tip.constraints), **kwargs})


def test_metadata_and_typed_wrapper_contracts(ik):
    assert set(ik.context.registry.list_tools()) == set(TOOL_NAMES)
    assert tuple(item.name for item in load_definitions()) == TOOL_NAMES
    assert tuple(item.name for item in RigIKTools(None).bindings()) == TOOL_NAMES
    for tool_name, _, modifies, needed in TOOL_DATA:
        spec = ik.context.registry.get(tool_name)
        assert spec.modifies == modifies and {item.value for item in spec.permissions} == set(needed)
        assert spec.toolset == "rigging" and spec.automatic_checkpoint

    class Registry:
        async def call(self, tool_name, params):
            return tool_name, params

    name, params = asyncio.run(RigIKTools(Registry()).rig_ik_configure("Rig", "Upper", "Lower", "Target", "Pole", ["Skin"], "Limb IK", create=True))
    assert name == "rig.ik_configure" and params["affected_meshes"] == ["Skin"] and params["iterations"] == 128


def test_creates_inspects_updates_and_removes_explicit_two_bone_ik(ik):
    result = configure(ik)
    assert result["created"] and result["affected_objects"] == ["Rig", "Skin"]
    constraint = ik.tip.constraints[0]
    assert constraint.target == ik.target and constraint.pole_target == ik.pole and constraint.chain_count == 2
    assert not constraint.use_stretch and constraint.iterations == 128
    inspected = ik.module.ik_inspect(ik.context, {"object_name": "Rig", "tip_bone_name": "Lower", "constraint_name": "Limb IK"})
    assert inspected["constraint"]["target"] == "Target"
    configure(ik, create=False, pole_angle=1.5, influence=.5)
    assert constraint.pole_angle == 1.5 and constraint.influence == .5
    result = ik.module.ik_remove(ik.context, {**ik.params, "confirm": True})
    assert result["removed"] and not ik.tip.constraints and not result["automatic_recreation_attempted"]


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_unknown_arguments_rejected_before_blender(ik, tool_name):
    with pytest.raises(ik.module.BridgeError) as error:
        getattr(ik.module, tool_name.split(".")[1])(None, {"unknown": 1})
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("changes", [{"pole_angle": True}, {"pole_angle": 4}, {"pole_angle": float("nan")},
    {"iterations": True}, {"iterations": 513}, {"influence": -1}, {"use_stretch": "yes"},
    {"affected_meshes": [None]}, {"affected_meshes": [[]]}, {"affected_meshes": ["Skin", "Skin"]},
    {"affected_meshes": []}, {"constraint_name": "é" * 40}, {"pole_object": "Target"}])
def test_invalid_or_incomplete_explicit_inputs_never_allocate(ik, changes):
    with pytest.raises(ik.module.BridgeError):
        configure(ik, **changes)
    assert not ik.tip.constraints


@pytest.mark.parametrize("problem", ["shared_scene", "linked_rig", "linked_data", "mode", "disconnected", "extra_child", "zero_length", "other_constraint", "action", "parented_control", "envelopes", "extra_modifier", "external_consumer", "custom_reference"])
def test_ownership_and_unreviewed_dependencies_rejected_before_allocation(ik, problem):
    if problem == "shared_scene":
        ik.rig.users_scene.append(object())
    elif problem == "linked_rig":
        ik.rig.library = object()
    elif problem == "linked_data":
        ik.rig.data.override_library = object()
    elif problem == "mode":
        ik.bpy.context.mode = "POSE"
    elif problem == "disconnected":
        ik.tip.bone.use_connect = False
    elif problem == "extra_child":
        ik.root.children.append(object())
    elif problem == "zero_length":
        ik.root.bone.length = 0
    elif problem == "other_constraint":
        ik.root.constraints.append(Constraint())
    elif problem == "action":
        ik.rig.animation_data = NS(action=object(), drivers=[], nla_tracks=[], use_tweak_mode=False)
    elif problem == "parented_control":
        ik.target.parent = ik.rig
    elif problem == "envelopes":
        ik.modifier.use_bone_envelopes = True
    elif problem == "extra_modifier":
        ik.mesh.modifiers.append(object())
    elif problem == "external_consumer":
        ik.external[ik.rig] = {ID("Protected consumer")}
    else:
        ik.mesh.user_of_id = lambda obj: 2
    with pytest.raises(ik.module.BridgeError):
        configure(ik)
    assert not ik.tip.constraints


@pytest.mark.parametrize("change", ["permission", "pause", "emergency", "mode", "identity", "control", "consumer", "bone", "constraint"])
def test_final_gate_revalidates_live_consent_and_frozen_scope(ik, change):
    def callback():
        if change == "permission":
            ik.grants["EDIT_ANIMATION"] = False
        elif change in {"pause", "emergency"}:
            ik.flags["paused" if change == "pause" else "emergency_stopped"] = True
        elif change == "mode":
            ik.bpy.context.mode = "POSE"
        elif change == "identity":
            ik.bpy.data.objects.remove(ik.target)
            ik.bpy.data.objects.append(ID("Target", type="EMPTY", data=None))
        elif change == "control":
            ik.target.matrix_world = ((2.,),)
        elif change == "consumer":
            ik.external[ik.rig] = {ID("Protected")}
        elif change == "bone":
            ik.root.location = (1, 0, 0)
        else:
            installed = ik.tip.constraints.new("IK")
            installed.name = "Limb IK"

    ik.context.check_cancelled = callback
    with pytest.raises(ik.module.BridgeError):
        configure(ik)
    assert len(ik.tip.constraints) == int(change == "constraint")


def test_known_partial_setter_is_compensated_without_rebuilding_constraint(ik):
    configure(ik)
    constraint = ik.tip.constraints[0]
    constraint.fail = "pole_angle"
    with pytest.raises(ik.module.BridgeError) as error:
        configure(ik, create=False, pole_angle=.75)
    assert error.value.context["rollback_verified"] and not error.value.context["possible_mutation"]
    assert ik.tip.constraints == [constraint] and constraint.pole_angle == 0


@pytest.mark.parametrize("change", ["permission", "pause", "emergency", "cancel", "replacement", "newer_setting", "new_consumer", "delete_denied"])
def test_post_allocation_failures_preserve_unowned_or_unpermitted_state(ik, change):
    fired = False
    newer = None

    def callback():
        nonlocal fired, newer
        if fired and change == "cancel":
            raise ik.module.BridgeError(ik.module.ErrorCode.OPERATION_FAILED, "Canceled")
        if fired or not ik.tip.constraints:
            return
        fired = True
        if change == "permission":
            ik.grants["EDIT_ANIMATION"] = False
        elif change in {"pause", "emergency"}:
            ik.flags["paused" if change == "pause" else "emergency_stopped"] = True
        elif change == "cancel":
            raise ik.module.BridgeError(ik.module.ErrorCode.OPERATION_FAILED, "Canceled")
        elif change == "replacement":
            ik.tip.constraints.clear()
            newer = ik.tip.constraints.new("IK")
            newer.name = "Limb IK"
        elif change == "newer_setting":
            ik.tip.constraints[0].influence = .37
        elif change == "new_consumer":
            ik.external[ik.rig] = {ID("New Consumer")}
        else:
            ik.grants["DELETE_OBJECTS"] = False
            ik.tip.constraints[0].fail = "chain_count"

    ik.context.check_cancelled = callback
    with pytest.raises(ik.module.BridgeError) as error:
        configure(ik)
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    assert len(ik.tip.constraints) == 1
    if newer:
        assert ik.tip.constraints[0] == newer
    if change == "newer_setting":
        assert ik.tip.constraints[0].influence == .37


def test_postwrite_update_failure_restores_existing_settings(ik):
    configure(ik)
    constraint = ik.tip.constraints[0]
    failed = False

    def update():
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("Update failed")

    ik.bpy.context.view_layer.update = update
    with pytest.raises(ik.module.BridgeError) as error:
        configure(ik, create=False, pole_angle=1.0)
    assert error.value.context["rollback_verified"] and constraint.pole_angle == 0


def test_remove_replacement_at_final_gate_is_never_deleted(ik):
    configure(ik)
    replacement = Constraint()
    replacement.name = "Limb IK"
    ik.context.check_cancelled = lambda: ik.tip.constraints.__setitem__(slice(None), [replacement])
    with pytest.raises(ik.module.BridgeError):
        ik.module.ik_remove(ik.context, {**ik.params, "confirm": True})
    assert ik.tip.constraints == [replacement]


def test_delete_requires_explicit_confirmation_and_independent_permission(ik):
    configure(ik)
    with pytest.raises(ik.module.BridgeError):
        ik.module.ik_remove(ik.context, ik.params)
    ik.grants["DELETE_OBJECTS"] = False
    with pytest.raises(ik.module.BridgeError) as error:
        ik.module.ik_remove(ik.context, {**ik.params, "confirm": True})
    assert error.value.code == "PERMISSION_DENIED" and len(ik.tip.constraints) == 1


def test_partial_native_allocation_error_reports_unknown_retained_constraint(ik):
    def partial(kind):
        constraint = Constraint()
        constraint.name = "Partially Allocated IK"
        ik.tip.constraints.append(constraint)
        raise RuntimeError("Allocation failed after native insert")

    ik.tip.constraints.new = partial
    with pytest.raises(ik.module.BridgeError) as error:
        configure(ik)
    evidence = error.value.context
    assert evidence["execution_started"] and evidence["possible_mutation"] and not evidence["rollback_verified"]
    assert evidence["observed_tip_constraint_names"] == ["Partially Allocated IK"]
    assert evidence["retained_constraint_name"] is None and len(ik.tip.constraints) == 1


def test_complete_native_writable_configuration_detects_unlisted_setting_edit(ik):
    configure(ik)
    constraint = ik.tip.constraints[0]
    constraint.native_extra = 1.
    constraint.bl_rna = NS(properties=[NS(identifier="native_extra", is_readonly=False, type="FLOAT")])
    fired = False

    def callback():
        nonlocal fired
        if not fired and constraint.influence == .6:
            fired = True
            constraint.native_extra = 2.

    ik.context.check_cancelled = callback
    with pytest.raises(ik.module.BridgeError) as error:
        configure(ik, create=False, influence=.6)
    assert not error.value.context["rollback_verified"] and not error.value.context["retained_configuration_matches_owned_write"]
    assert constraint.influence == .6 and constraint.native_extra == 2.


def test_native_constraint_keys_can_exist_without_idproperty_support(ik):
    configure(ik)
    constraint = ik.tip.constraints[0]

    def unsupported():
        raise TypeError("this type doesn't support IDProperties")

    constraint.keys = unsupported
    result = configure(ik, create=False, pole_angle=.25)
    assert result["constraint"]["pole_angle"] == .25


def test_same_length_rest_roll_basis_change_at_gate_is_rejected(ik):
    ik.root.bone.matrix_local = ((1., 0.), (0., 1.))
    ik.context.check_cancelled = lambda: setattr(ik.root.bone, "matrix_local", ((0., 1.), (-1., 0.)))
    with pytest.raises(ik.module.BridgeError):
        configure(ik)
    assert not ik.tip.constraints
