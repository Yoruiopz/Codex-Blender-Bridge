from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from test_scene_mutation_boundaries import RNA, NativeOwner, Properties, f32, prop


@pytest.fixture
def camera_case(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.scene_edit")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state")
    dof_type = type("CameraDOFSettings", (NativeOwner,), {"bl_rna": RNA("CameraDOFSettings", Properties([
        prop("use_dof", "BOOLEAN"), prop("focus_object", "POINTER"), prop("focus_distance"), prop("aperture_fstop"),
    ]))})
    camera_type = type("Camera", (NativeOwner,), {"bl_rna": RNA("Camera", Properties([
        prop("type", "ENUM"), *(prop(name) for name in ("lens", "sensor_width", "clip_start", "clip_end", "ortho_scale")),
    ]))})
    scene_type = type("Scene", (NativeOwner,), {"bl_rna": RNA("Scene", Properties([prop("camera", "POINTER")]))})
    dof = dof_type({"use_dof": False, "focus_object": None, "focus_distance": 10.0, "aperture_fstop": f32(2.8)})
    camera = camera_type({"name": "Camera Data", "users": 1, "type": "PERSP", "lens": 35.0,
                          "sensor_width": 36.0, "clip_start": f32(.1), "clip_end": 1000.0,
                          "ortho_scale": 6.0, "dof": dof})
    obj = NS(name="Camera", type="CAMERA", data=camera, session_uid=100)
    focus = NS(name="Focus", as_pointer=lambda: 1234, session_uid=1234)
    scene = scene_type({"camera": None})
    bpy = NS(types=NS(Camera=camera_type, CameraDOFSettings=dof_type, Scene=scene_type), context=NS(scene=scene))
    registry = registry_module.ToolRegistry(enabled_toolsets=("scene_edit",))
    mod.register_tools(registry)
    grants = {permission.value: True for permission in permissions.Permission}
    context = registry_module.ToolContext(state.BridgeState(), permissions.PermissionManager(lambda: grants), registry, None)
    profiles, lookups = [], []

    def profile(*args, **kwargs):
        profiles.append(kwargs)
        return lambda: ()

    def get_object(name, *, allow_active):
        assert allow_active is False
        lookups.append(name)
        return {obj.name: obj, focus.name: focus}[name]

    monkeypatch.setattr(mod, "get_object", get_object)
    monkeypatch.setattr(mod, "require_blender", lambda: bpy)
    monkeypatch.setattr(mod.proof, "preflight_types", lambda _bpy: None)
    monkeypatch.setattr(mod.profile, "Profile", profile)
    return NS(mod=mod, obj=obj, camera=camera, dof=dof, focus=focus, scene=scene,
              context=context, profiles=profiles, lookups=lookups)


def configure(case, **params):
    return case.mod.configure_camera(case.context, {"object_name": case.obj.name, **params})


@pytest.mark.parametrize("distance", [0, .1, 43.1, 1.0e9])
def test_manual_distance_uses_real_field_float32_prediction_without_enabling_dof(camera_case, distance):
    case = camera_case
    result = configure(case, focus_distance=distance)
    assert case.dof.focus_distance == result["dof"]["focus_distance"] == f32(distance)
    assert case.dof.use_dof is False and case.dof.focus_object is None
    assert case.camera.lens == 35.0 and case.scene.camera is None
    assert case.dof.setter_calls == [("focus_distance", float(distance))]
    assert case.profiles[0]["edit_data"] is True
    assert result["verified"] is True


@pytest.mark.parametrize("clear", [{"clear_focus_object": True}, {"focus_object": None}])
def test_explicit_focus_clear_precedes_manual_distance_and_keeps_dof_disabled(camera_case, clear):
    case = camera_case
    case.dof._values["focus_object"] = case.focus
    result = configure(case, focus_distance=43.1, **clear)
    assert case.dof.setter_calls == [("focus_object", None), ("focus_distance", 43.1)]
    assert result["dof"] == {"enabled": False, "focus_object": None, "focus_distance": f32(43.1), "aperture_fstop": f32(2.8)}


@pytest.mark.parametrize("params", [{}, {"focus_object": "Focus"}, {"clear_focus_object": False}])
def test_final_focus_object_blocks_manual_distance_before_boundary(camera_case, params):
    case = camera_case
    case.dof._values["focus_object"] = case.focus
    with pytest.raises(case.mod.BridgeError) as caught:
        configure(case, focus_distance=12, **params)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert case.dof.focus_object is case.focus and case.dof.focus_distance == 10
    assert case.dof.setter_calls == [] and case.profiles == []
    assert case.lookups == ["Camera"]


def test_new_focus_object_and_distance_are_rejected_even_when_no_existing_focus(camera_case):
    case = camera_case
    with pytest.raises(case.mod.BridgeError) as caught:
        configure(case, focus_object="Focus", focus_distance=12)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert case.dof.setter_calls == [] and case.profiles == []
    assert case.lookups == ["Camera"]


@pytest.mark.parametrize("distance", [True, False, "12", None, [], {}, -0.1, 1.0e9 + 1,
                                      float("nan"), float("inf"), -float("inf"), 10 ** 400])
def test_invalid_distance_is_rejected_before_boundary_or_any_setting(camera_case, distance):
    case = camera_case
    with pytest.raises(case.mod.BridgeError) as caught:
        configure(case, lens=50, dof_enabled=True, focus_distance=distance)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert case.camera.lens == 35 and case.dof.use_dof is False
    assert case.dof.setter_calls == case.camera.setter_calls == [] and case.profiles == []


@pytest.mark.parametrize("owner", ["object", "data"])
@pytest.mark.parametrize("field,value", [("library", "linked.blend"), ("override_library", "override"), ("is_editable", False)])
def test_distance_only_requires_local_editable_nonoverride_owners(camera_case, owner, field, value):
    case = camera_case
    setattr(case.obj if owner == "object" else case.camera, field, value)
    with pytest.raises(case.mod.BridgeError) as caught:
        configure(case, focus_distance=12)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert case.dof.focus_distance == 10 and case.dof.setter_calls == [] and case.profiles == []


def test_distance_only_rejects_shared_camera_before_boundary(camera_case):
    case = camera_case
    case.camera._values["users"] = 2
    with pytest.raises(case.mod.BridgeError) as caught:
        configure(case, focus_distance=12)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert case.dof.focus_distance == 10 and case.dof.setter_calls == [] and case.profiles == []


def test_later_setter_failure_restores_stored_distance_and_original_focus_identity(camera_case):
    case = camera_case
    case.dof._values["focus_object"] = case.focus

    def fail(_owner, _name, _value):
        raise RuntimeError("Aperture setter failed")

    case.dof.setter_hooks["aperture_fstop"] = fail
    with pytest.raises(case.mod.BridgeError) as caught:
        configure(case, clear_focus_object=True, focus_distance=43.1, aperture_fstop=1.4)
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["possible_mutation"] is False
    assert caught.value.context["recovery_evidence"]["restoration_verified"] is True
    assert case.dof.focus_distance == 10 and case.dof.focus_object is case.focus
    assert case.dof.use_dof is False and case.dof.aperture_fstop == f32(2.8)


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("focus_present", [True, False])
def test_receipt_and_object_inspection_always_report_stored_distance(camera_case, addon_package, enabled, focus_present):
    case = camera_case
    case.dof._values.update(use_dof=enabled, focus_object=case.focus if focus_present else None,
                            focus_distance=f32(43.1))
    receipt = configure(case)
    inspector = importlib.import_module(f"{addon_package}.scene_inspector")
    obj = case.obj
    obj.parent, obj.children, obj.users_collection = None, [], []
    obj.material_slots, obj.modifiers, obj.constraints = [], [], []
    obj.rotation_euler, obj.rotation_quaternion, obj.rotation_axis_angle = [0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]
    obj.rotation_mode, obj.location, obj.scale, obj.dimensions = "XYZ", [0, 0, 0], [1, 1, 1], [0, 0, 0]
    obj.matrix_world = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    obj.visible_get, obj.select_get, obj.hide_viewport, obj.hide_render = lambda: True, lambda: False, False, False
    observed = inspector._object_compact(obj, None)
    assert receipt["dof"] == observed["camera"]["dof"]
    assert observed["camera"]["dof"]["focus_distance"] == f32(43.1)
    assert observed["camera"]["dof"]["enabled"] is enabled
    assert case.dof.focus_object is (case.focus if focus_present else None)
    assert case.dof.setter_calls == []
