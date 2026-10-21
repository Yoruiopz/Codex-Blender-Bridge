from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.rig_drivers import (
    TOOL_DATA,
    TOOL_NAMES,
    RigDriverTools,
    load_definitions,
)


class Items(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class ID(dict):
    __hash__ = object.__hash__
    __eq__ = object.__eq__

    def __init__(self, name, **attrs):
        super().__init__()
        self.name = name
        self.library = self.override_library = None
        self.is_editable = True
        self.__dict__.update(attrs)


class Variables(list):
    def new(self):
        target = NS(id=None, bone_target="", data_path="", transform_type="LOC_X", transform_space="WORLD_SPACE")
        variable = NS(name="var", type="SINGLE_PROP", targets=[target])
        self.append(variable)
        return variable


def object_id(name="Rig", *, bones=()):
    return ID(name, type="ARMATURE" if bones else "EMPTY", pose=NS(bones=Items(bones)) if bones else None,
              data=ID(name + "Data"), parent=None, parent_type="OBJECT", constraints=[], animation_data=None,
              bl_rna=NS(identifier="Object"), update_tag=lambda: None)


@pytest.fixture
def drivers(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.rig_drivers")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    control = ID('Control"A', parent=None, constraints=[], rotation_mode="XYZ")
    deform = ID("Deform", parent=control, constraints=[], rotation_mode="XYZ")
    obj = object_id(bones=[control, deform])
    other = object_id("Other")
    control['move"X'] = 2.0
    other["value"] = 1.0
    objects = Items([obj, other])
    users = {obj: set(), other: set()}
    bpy = NS(context=NS(mode="OBJECT", scene=NS(objects=objects)), data=NS(user_map=lambda **kwargs: users))
    flags = {"paused": False, "emergency_stopped": False}
    grants = {permission.value: True for permission in permissions.Permission}

    def require(*needed):
        if any(not grants[item.value] for item in needed):
            raise module.BridgeError(module.ErrorCode.PERMISSION_DENIED, "Denied")

    context = NS(require=require, check_cancelled=None, state=NS(snapshot=lambda: dict(flags)))

    def add(path, index):
        if obj.animation_data is None:
            obj.animation_data = NS(action=None, nla_tracks=[], use_tweak_mode=False, drivers=[])
        curve = NS(data_path=path, array_index=index, mute=False, modifiers=[], keyframe_points=[], sampled_points=[],
                   driver=NS(type="AVERAGE", use_self=False, variables=Variables(), is_valid=True))
        obj.animation_data.drivers.append(curve)
        return curve

    def remove(path, index):
        curve = module._curve(obj, path, index)
        if curve is None:
            return False
        obj.animation_data.drivers.remove(curve)
        return True

    obj.driver_add, obj.driver_remove = add, remove
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    return NS(module=module, bpy=bpy, obj=obj, other=other, control=control, deform=deform, context=context,
              flags=flags, grants=grants, users=users)


def add_driver(drivers, **kwargs):
    return drivers.module.driver_add(drivers.context, {"object_name": "Rig", "bone_name": "Deform", "channel": "location", "index": 0,
                                                      "variables": [{"kind": "PROPERTY", "object_name": "Rig", "bone_name": 'Control"A', "property_name": 'move"X'}], **kwargs})


def set_property(drivers, **kwargs):
    return drivers.module.property_set(drivers.context, {"object_name": "Rig", "bone_name": 'Control"A', "property_name": 'move"X', "value": 3.0, **kwargs})


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_unknown_parameters_are_rejected_before_blender(drivers, tool_name):
    with pytest.raises(drivers.module.BridgeError) as error:
        getattr(drivers.module, tool_name.split(".")[1])(None, {"unknown": True})
    assert error.value.code == "INVALID_ARGUMENT"


def test_addon_mcp_metadata_bindings_and_permissions_agree(drivers, addon_package):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry(enabled_toolsets=("rigging",))
    drivers.module.register_tools(registry)
    assert set(registry.list_tools()) == set(TOOL_NAMES)
    assert tuple(item.name for item in load_definitions()) == TOOL_NAMES
    assert tuple(item.name for item in RigDriverTools(None).bindings()) == TOOL_NAMES
    for tool_name, _, modifying, permissions in TOOL_DATA:
        spec = registry.get(tool_name)
        assert spec.modifies is modifying and spec.automatic_checkpoint
        assert spec.toolset == "rigging" and {item.value for item in spec.permissions} == set(permissions)


def test_typed_wrappers_forward_explicit_control_scope():
    class Registry:
        async def call(self, name, params):
            return name, params

    wrapper = RigDriverTools(Registry())
    assert asyncio.run(wrapper.rig_property_set("Rig", "move", 2.0, bone_name="Control", create=True)) == (
        "rig.property_set", {"object_name": "Rig", "bone_name": "Control", "property_name": "move", "value": 2.0, "create": True})
    assert asyncio.run(wrapper.rig_driver_inspect("Rig", "Deform", "location")) == (
        "rig.driver_inspect", {"object_name": "Rig", "bone_name": "Deform", "channel": "location", "index": 0})


def test_quoted_bone_property_paths_are_constructed_and_decoded_without_eval(drivers):
    path = drivers.module._property_path('Control"A', 'move"X')
    assert path == 'pose.bones["Control\\"A"]["move\\"X"]'
    assert drivers.module._property_source(drivers.obj, path) == ('Control"A', 'move"X', drivers.control)
    result = add_driver(drivers)
    assert result["driver"]["variables"][0]["targets"][0]["data_path"] == path
    assert result["driver"]["driver_type"] == "AVERAGE"


@pytest.mark.parametrize("path", ['location', '["move"];__import__("os")', 'pose.bones["Control\\"A"].location', '["missing"]', '__dict__["x"]'])
def test_arbitrary_or_nonproperty_driver_paths_are_refused(drivers, path):
    with pytest.raises(drivers.module.BridgeError):
        drivers.module._property_source(drivers.obj, path)


def test_static_property_source_can_drive_the_same_bone_without_false_transform_cycle(drivers):
    drivers.deform["control"] = 1.0
    result = add_driver(drivers, variables=[{"kind": "PROPERTY", "object_name": "Rig", "bone_name": "Deform", "property_name": "control"}])
    assert result["added"] and not result["dependencies"]["dependency_cycle_detected"]


@pytest.mark.parametrize("source_bone,target_bone", [("Deform", 'Control"A'), ("Deform", "Deform")])
def test_descendant_and_self_transform_cycles_are_rejected_before_allocation(drivers, source_bone, target_bone):
    with pytest.raises(drivers.module.BridgeError, match="cycle"):
        add_driver(drivers, bone_name=target_bone, variables=[{"kind": "TRANSFORM", "object_name": "Rig", "bone_name": source_bone,
                                                            "transform_type": "LOC_X", "transform_space": "WORLD_SPACE"}])
    assert drivers.obj.animation_data is None


def test_ancestor_transform_source_is_valid_and_control_update_retains_driver(drivers):
    result = add_driver(drivers, variables=[{"kind": "TRANSFORM", "object_name": "Rig", "bone_name": 'Control"A', "transform_type": "LOC_X"}])
    assert result["added"]
    changed = set_property(drivers)
    assert changed["value"] == 3.0 and len(drivers.obj.animation_data.drivers) == 1


@pytest.mark.parametrize("problem", ["action", "nla", "constraint", "pose_constraint", "scripted", "modifier", "path", "driven_property", "target_budget", "readonly", "consumer_readonly"])
def test_unreviewed_dependencies_and_ownership_are_denied_before_mutation(drivers, problem):
    if problem in {"scripted", "modifier", "path", "driven_property"}:
        add_driver(drivers)
        existing = drivers.obj.animation_data.drivers[0]
        if problem == "scripted":
            existing.driver.type = "SCRIPTED"
        elif problem == "modifier":
            existing.modifiers = [NS(type="NOISE")]
        else:
            existing.data_path = "[\"move\"]" if problem == "driven_property" else "unknown.path"
    elif problem in {"action", "nla"}:
        drivers.obj.animation_data = NS(action=object() if problem == "action" else None, nla_tracks=[object()] if problem == "nla" else [], use_tweak_mode=False, drivers=[])
    elif problem == "constraint":
        drivers.obj.constraints = [object()]
    elif problem == "pose_constraint":
        drivers.control.constraints = [object()]
    elif problem == "target_budget":
        drivers.obj.pose.bones.extend([ID(f"Bone{i}", constraints=[], parent=None) for i in range(256)])
    elif problem == "readonly":
        drivers.obj.override_library = object()
    else:
        consumer = object_id("Linked Consumer")
        consumer.library = object()
        drivers.users[drivers.obj].add(consumer)
    with pytest.raises(drivers.module.BridgeError):
        set_property(drivers)
    assert drivers.control['move"X'] == 2.0


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 10**1000, "2", None])
def test_numeric_control_validation_is_bounded_and_not_boolean(drivers, value):
    with pytest.raises(drivers.module.BridgeError):
        set_property(drivers, value=value)
    assert drivers.control['move"X'] == 2.0


@pytest.mark.parametrize("variables", [[{"kind": []}], [{"kind": "PROPERTY", "object_name": "Rig", "property_name": "missing"}],
                                     [{"kind": "TRANSFORM", "object_name": "Other", "transform_type": "UNKNOWN"}],
                                     [{"kind": "TRANSFORM", "object_name": "Other", "transform_type": "LOC_X", "data_path": "arbitrary"}], [], [None]])
def test_driver_variables_require_exact_reviewed_choices(drivers, variables):
    with pytest.raises(drivers.module.BridgeError):
        add_driver(drivers, variables=variables)
    assert drivers.obj.animation_data is None


def test_missing_control_needs_explicit_creation_and_readback(drivers):
    with pytest.raises(drivers.module.BridgeError):
        set_property(drivers, property_name="new_control")
    result = set_property(drivers, property_name="new_control", create=True)
    assert result["created"] and drivers.control["new_control"] == 3.0
    inspected = drivers.module.property_inspect(drivers.context, {"object_name": "Rig", "bone_name": 'Control"A', "property_name": "new_control"})
    assert inspected["exists"] and inspected["value"] == 3.0


@pytest.mark.parametrize("revoke", [False, True])
def test_post_allocation_driver_failure_reports_measured_cleanup_or_retention(drivers, revoke):
    def fail_after_allocation():
        if len(drivers.module._curves(drivers.obj)):
            if revoke:
                drivers.grants["EDIT_ANIMATION"] = False
            else:
                raise drivers.module.BridgeError(drivers.module.ErrorCode.OPERATION_FAILED, "Injected fault")

    drivers.context.check_cancelled = fail_after_allocation
    with pytest.raises(drivers.module.BridgeError) as error:
        add_driver(drivers)
    assert error.value.context["rollback_verified"] is (not revoke)
    assert error.value.context["possible_mutation"] is revoke
    assert len(drivers.module._curves(drivers.obj)) == int(revoke)
    assert (error.value.context["retained_driver_path"] is not None) is revoke


def test_post_creation_property_failure_restores_original_absence(drivers):
    def fail_after_creation():
        if "new_control" in drivers.control:
            raise drivers.module.BridgeError(drivers.module.ErrorCode.OPERATION_FAILED, "Injected fault")

    drivers.context.check_cancelled = fail_after_creation
    with pytest.raises(drivers.module.BridgeError) as error:
        set_property(drivers, property_name="new_control", create=True)
    assert error.value.context["rollback_verified"] and "new_control" not in drivers.control


def test_exact_driver_removal_and_inspection_preserve_other_channels(drivers):
    add_driver(drivers)
    add_driver(drivers, index=1)
    removed = drivers.module.driver_remove(drivers.context, {"object_name": "Rig", "bone_name": "Deform", "channel": "location", "index": 0})
    assert removed["removed"] and len(drivers.obj.animation_data.drivers) == 1
    assert drivers.obj.animation_data.drivers[0].array_index == 1
    inspected = drivers.module.driver_inspect(drivers.context, {"object_name": "Rig", "bone_name": "Deform", "channel": "location", "index": 0})
    assert inspected["driver"] is None


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped", "permission"])
def test_live_control_gates_prevent_mutation(drivers, flag):
    if flag == "permission":
        drivers.grants["EDIT_ANIMATION"] = False
    else:
        drivers.flags[flag] = True
    with pytest.raises(drivers.module.BridgeError):
        set_property(drivers)
    assert drivers.control['move"X'] == 2.0


def install_gate_hook(drivers, monkeypatch, hook):
    original = drivers.module._gate
    calls = []

    def gate(context):
        original(context)
        calls.append(None)
        hook(len(calls))

    monkeypatch.setattr(drivers.module, "_gate", gate)


def test_driver_installed_by_final_gate_is_not_reused_or_erased(drivers, monkeypatch):
    path = drivers.module._bone_path("Deform") + ".location"
    protected = []

    def hook(ordinal):
        if ordinal == 1:
            curve = drivers.obj.driver_add(path, 0)
            curve.modifiers.append(NS(type="PROTECTED"))
            variable = curve.driver.variables.new()
            variable.name = "Protected variable"
            protected.append(curve)

    install_gate_hook(drivers, monkeypatch, hook)
    with pytest.raises(drivers.module.BridgeError, match="no existing curve"):
        add_driver(drivers)
    assert drivers.obj.animation_data.drivers == protected
    assert protected[0].modifiers[0].type == "PROTECTED"
    assert protected[0].driver.variables[0].name == "Protected variable"


@pytest.mark.parametrize("replace", [False, True])
def test_post_write_driver_replacement_or_edit_is_never_deleted(drivers, monkeypatch, replace):
    path = drivers.module._bone_path("Deform") + ".location"
    protected = []

    def hook(ordinal):
        if ordinal == 2:
            if replace:
                drivers.obj.driver_remove(path, 0)
                curve = drivers.obj.driver_add(path, 0)
                curve.driver.variables.new()
            else:
                curve = drivers.module._curve(drivers.obj, path, 0)
            curve.driver.variables[0].name = "Manual replacement"
            curve.modifiers.append(NS(type="PROTECTED"))
            protected.append(curve)

    install_gate_hook(drivers, monkeypatch, hook)
    with pytest.raises(drivers.module.BridgeError) as error:
        add_driver(drivers)
    assert error.value.context["cleanup_skipped"] and error.value.context["possible_mutation"]
    assert not error.value.context["rollback_verified"] and error.value.context["retained_driver_path"] is None
    assert drivers.obj.animation_data.drivers == protected
    assert protected[0].driver.variables[0].name == "Manual replacement"
    assert protected[0].modifiers[0].type == "PROTECTED"


@pytest.mark.parametrize("gate_ordinal", [1, 2])
def test_property_changed_in_gate_is_not_overwritten_by_edit_or_compensation(drivers, monkeypatch, gate_ordinal):
    def hook(ordinal):
        if ordinal == gate_ordinal:
            drivers.control['move"X'] = 42.0

    install_gate_hook(drivers, monkeypatch, hook)
    with pytest.raises(drivers.module.BridgeError):
        set_property(drivers)
    assert drivers.control['move"X'] == 42.0


def test_target_identity_replaced_in_final_gate_is_not_edited(drivers, monkeypatch):
    replacement = object_id("Rig", bones=[ID("Deform", parent=None, constraints=[], rotation_mode="XYZ")])

    def hook(ordinal):
        if ordinal == 1:
            drivers.bpy.context.scene.objects[0] = replacement

    install_gate_hook(drivers, monkeypatch, hook)
    with pytest.raises(drivers.module.BridgeError, match="identity changed"):
        add_driver(drivers)
    assert replacement.animation_data is None and drivers.obj.animation_data is None


def test_final_gate_rotation_mode_change_revalidates_euler_target(drivers, monkeypatch):
    def hook(ordinal):
        if ordinal == 1:
            drivers.deform.rotation_mode = "QUATERNION"

    install_gate_hook(drivers, monkeypatch, hook)
    with pytest.raises(drivers.module.BridgeError, match="Euler"):
        add_driver(drivers, channel="rotation_euler")
    assert drivers.obj.animation_data is None


def test_driver_remove_does_not_delete_replacement_created_in_final_gate(drivers, monkeypatch):
    add_driver(drivers)
    path = drivers.module._bone_path("Deform") + ".location"
    protected = []

    def hook(ordinal):
        if ordinal == 1:
            drivers.obj.driver_remove(path, 0)
            replacement = drivers.obj.driver_add(path, 0)
            replacement.driver.variables.new().name = "Protected"
            protected.append(replacement)

    install_gate_hook(drivers, monkeypatch, hook)
    with pytest.raises(drivers.module.BridgeError, match="no replacement curve"):
        drivers.module.driver_remove(drivers.context, {"object_name": "Rig", "bone_name": "Deform", "channel": "location", "index": 0})
    assert drivers.obj.animation_data.drivers == protected
