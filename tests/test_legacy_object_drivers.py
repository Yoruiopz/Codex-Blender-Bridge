from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
import test_rig_drivers as rig_fixtures


@pytest.fixture
def legacy(addon_package, monkeypatch):
    env = rig_fixtures.drivers.__wrapped__(addon_package, monkeypatch)
    module = importlib.import_module(f"{addon_package}.tools._legacy_object_drivers")
    monkeypatch.setattr(module, "require_blender", lambda: env.bpy)
    monkeypatch.setattr(module.scope, "object_scope", lambda bpy, obj: module.rig.require_local_object(obj, operation="Legacy source scope"))
    env.bpy.context.view_layer = NS(update=lambda: None)
    env.module, env.rig = module, env.module
    return env


def add(env, **changes):
    return env.module.add(env.context, {"object_name": "Rig", "data_path": "location", "index": 0,
        "variables": [{"object_name": "Other", "transform_type": "LOC_X", "transform_space": "WORLD_SPACE"}], **changes})


def remove(env, **changes):
    return env.module.remove(env.context, {"object_name": "Rig", "data_path": "location", "index": 0, **changes})


def test_compatible_transform_driver_setup_and_exact_cleanup(legacy):
    result = add(legacy)
    curve = legacy.rig._curves(legacy.obj)[0]
    assert result["added"] and curve.driver.type == "AVERAGE" and not curve.driver.use_self
    assert not curve.modifiers and not curve.keyframe_points
    variable = curve.driver.variables[0]
    assert variable.name == "source_0" and variable.type == "TRANSFORMS"
    assert variable.targets[0].id is legacy.other and variable.targets[0].transform_space == "WORLD_SPACE"
    assert remove(legacy)["removed"] and not legacy.rig._curves(legacy.obj)


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_unknown_arguments_are_rejected_before_context_or_blender(legacy, operation):
    with pytest.raises(legacy.module.BridgeError) as error:
        getattr(legacy.module, operation)(None, {"unexpected": True})
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("change", ["self", "parent", "constraints", "animation", "linked", "override", "readonly"])
def test_source_independence_and_local_ownership_are_checked_before_allocation(legacy, change):
    if change == "self":
        variables = [{"object_name": "Rig", "transform_type": "LOC_X", "transform_space": "WORLD_SPACE"}]
    else:
        variables = [{"object_name": "Other", "transform_type": "LOC_X", "transform_space": "WORLD_SPACE"}]
        if change == "parent":
            legacy.other.parent = legacy.obj
        elif change == "constraints":
            legacy.other.constraints.append(object())
        elif change == "animation":
            legacy.other.animation_data = NS()
        elif change == "linked":
            legacy.other.library = object()
        elif change == "override":
            legacy.other.override_library = object()
        else:
            legacy.other.is_editable = False
    with pytest.raises(legacy.module.BridgeError):
        add(legacy, variables=variables)
    assert legacy.obj.animation_data is None


@pytest.mark.parametrize("stop", ["paused", "emergency_stopped", "permission", "cancel"])
@pytest.mark.parametrize("stage", ["allocation", "variable", "named", "source", "configured"])
def test_legacy_driver_setup_stops_without_late_edits_or_animdata_clearing(legacy, stop, stage):
    retained = []

    def callback():
        curves = legacy.rig._curves(legacy.obj)
        if not curves:
            return
        curve = curves[0]
        variables = curve.driver.variables
        ready = (stage == "allocation" or (bool(variables) and (
            stage == "variable" or (stage == "named" and variables[0].name == "source_0")
            or (stage == "source" and variables[0].targets[0].id is legacy.other)
            or (stage == "configured" and variables[0].targets[0].transform_type == "LOC_Z"
                and variables[0].targets[0].transform_space == "LOCAL_SPACE" and variables[0].targets[0].id is legacy.other))))
        if not ready:
            return
        if not retained:
            retained.append(legacy.rig._driver_configuration(curve))
        if stop == "permission":
            legacy.grants["EDIT_ANIMATION"] = False
        elif stop == "cancel":
            raise legacy.module.BridgeError(legacy.module.ErrorCode.OPERATION_FAILED, "Caller canceled/disconnected")
        else:
            legacy.flags[stop] = True

    legacy.context.check_cancelled = callback
    with pytest.raises(legacy.module.BridgeError) as error:
        add(legacy, variables=[{"object_name": "Other", "transform_type": "LOC_Z", "transform_space": "LOCAL_SPACE"}])
    assert retained and legacy.obj.animation_data is not None
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    assert legacy.rig._driver_configuration(legacy.rig._curves(legacy.obj)[0]) == retained[0]
    legacy.context.check_cancelled = None
    legacy.flags.update(paused=False, emergency_stopped=False)
    legacy.grants["EDIT_ANIMATION"] = True
    assert remove(legacy)["removed"]


@pytest.mark.parametrize("change", ["target", "source", "consumer", "sibling", "scene", "animdata"])
def test_setup_refuses_manual_identity_scope_and_container_changes(legacy, change):
    retained = []

    def callback():
        curves = legacy.rig._curves(legacy.obj)
        if not curves or retained:
            return
        retained.append(legacy.rig._driver_configuration(curves[0]))
        if change == "target":
            legacy.obj.session_uid = 77
        elif change == "source":
            legacy.other.session_uid = 77
        elif change == "consumer":
            legacy.users[legacy.obj].add(legacy.other)
        elif change == "sibling":
            legacy.obj.driver_add("scale", 1)
        elif change == "scene":
            legacy.bpy.context.scene = NS(objects=legacy.bpy.context.scene.objects)
        else:
            legacy.obj.animation_data = NS(action=None, nla_tracks=[], use_tweak_mode=False, drivers=list(curves))

    legacy.context.check_cancelled = callback
    with pytest.raises(legacy.module.BridgeError) as error:
        add(legacy)
    assert retained and error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    assert legacy.rig._driver_configuration(legacy.rig._curves(legacy.obj)[0]) == retained[0]
    if change == "sibling":
        assert len(legacy.rig._curves(legacy.obj)) == 2


def test_final_remove_gate_never_deletes_a_same_channel_replacement(legacy):
    add(legacy)
    replaced = []

    def callback():
        if replaced:
            return
        legacy.obj.driver_remove("location", 0)
        replaced.append(legacy.obj.driver_add("location", 0))

    legacy.context.check_cancelled = callback
    with pytest.raises(legacy.module.BridgeError):
        remove(legacy)
    assert legacy.rig._curves(legacy.obj) == replaced


def test_one_shot_failure_cleanup_retains_new_animdata_without_false_rollback(legacy):
    fired = False

    def callback():
        nonlocal fired
        curves = legacy.rig._curves(legacy.obj)
        if not fired and curves and curves[0].driver.variables and curves[0].driver.variables[0].targets[0].id is legacy.other:
            fired = True
            raise RuntimeError("One-shot native setup failure")

    legacy.context.check_cancelled = callback
    with pytest.raises(legacy.module.BridgeError) as error:
        add(legacy)
    assert fired and not legacy.rig._curves(legacy.obj) and legacy.obj.animation_data is not None
    assert error.value.context["retained_empty_anim_data"] and error.value.context["retained_driver_path"] is None
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]


def test_one_shot_failure_with_original_animdata_has_measured_recovery(legacy):
    legacy.obj.animation_data = NS(action=None, nla_tracks=[], use_tweak_mode=False, drivers=[])
    original = legacy.obj.animation_data
    fired = False

    def callback():
        nonlocal fired
        curves = legacy.rig._curves(legacy.obj)
        if not fired and curves and curves[0].driver.variables and curves[0].driver.variables[0].targets[0].id is legacy.other:
            fired = True
            raise RuntimeError("One-shot native setup failure")

    legacy.context.check_cancelled = callback
    with pytest.raises(legacy.module.BridgeError) as error:
        add(legacy)
    assert fired and legacy.obj.animation_data is original and not legacy.rig._curves(legacy.obj)
    assert error.value.context["rollback_verified"] and not error.value.context["possible_mutation"]


def test_history_inventory_growth_keeps_original_structured_failure_and_retained_data(legacy):
    def callback():
        curves = legacy.rig._curves(legacy.obj)
        if len(curves) == 1:
            curves.extend([curves[0]] * 128)

    legacy.context.check_cancelled = callback
    with pytest.raises(legacy.module.BridgeError) as error:
        add(legacy)
    assert len(legacy.rig._curves(legacy.obj)) == 129
    assert error.value.context["possible_mutation"] and error.value.context["cleanup_skipped"]
    assert error.value.context["retained_driver_path"] is None
