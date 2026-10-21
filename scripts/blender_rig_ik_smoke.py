"""Disposable native two-bone IK behavior probe; run only through the native runner."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import rig_ik  # noqa: E402


def main() -> None:
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: True for permission in Permission}
    permissions = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = permissions
    runtime.registry.enable_toolset("rigging")
    runtime.registry.enable_toolset("objects")
    armature = bpy.data.armatures.new("IK Probe Data")
    rig = bpy.data.objects.new("IK Probe Rig", armature)
    bpy.context.scene.collection.objects.link(rig)
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    for obj in selected:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    upper = armature.edit_bones.new("Upper")
    upper.head, upper.tail = (0, 0, 0), (0.25, 1, 0)
    lower = armature.edit_bones.new("Lower")
    lower.head, lower.tail, lower.parent, lower.use_connect = upper.tail, (0, 2, 0), upper, True
    protected = armature.edit_bones.new("Protected")
    protected.head, protected.tail = (3, 0, 0), (3, 1, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.select_set(False)
    for obj in selected:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active
    target = bpy.data.objects.new("IK Probe Target", None)
    pole = bpy.data.objects.new("IK Probe Pole", None)
    bpy.context.scene.collection.objects.link(target)
    bpy.context.scene.collection.objects.link(pole)
    target.location, pole.location = (1.1, 1.1, 0), (0, 0, 2)
    alias = rig.copy()
    alias.name = "Protected Shared Rest Rig"
    bpy.context.scene.collection.objects.link(alias)
    skin_data = bpy.data.meshes.new("IK Skin Data")
    skin_data.from_pydata([(0.15, 1.25, 0), (0.35, 1.25, 0), (0.1, 1.8, 0), (0.3, 1.8, 0),
                          (3, .25, 0), (3.2, .25, 0), (3, .75, 0)], [], [(0, 1, 3, 2), (4, 5, 6)])
    skin = bpy.data.objects.new("IK Character Skin", skin_data)
    bpy.context.scene.collection.objects.link(skin)
    modifier = skin.modifiers.new("Skin", "ARMATURE")
    modifier.object = rig
    upper_group, lower_group = skin.vertex_groups.new(name="Upper"), skin.vertex_groups.new(name="Lower")
    upper_group.add([0, 1], .5, "REPLACE")
    lower_group.add([0, 1], .5, "REPLACE")
    lower_group.add([2, 3], 1., "REPLACE")
    skin.vertex_groups.new(name="Protected").add([4, 5, 6], 1., "REPLACE")
    detail = skin.vertex_groups.new(name="ProtectedDetail")
    detail.add(list(range(7)), .25, "REPLACE")
    detail.lock_weight = True

    def skin_state():
        return ([list(vertex.co) for vertex in skin.data.vertices], [list(edge.vertices) for edge in skin.data.edges],
                [list(face.vertices) for face in skin.data.polygons],
                [[(item.group, item.weight) for item in vertex.groups] for vertex in skin.data.vertices],
                [(group.name, group.lock_weight) for group in skin.vertex_groups])

    frozen_skin = skin_state()
    frozen_rest = [[list(row) for row in bone.matrix_local] for bone in rig.data.bones]

    scope = {"object_name": rig.name, "root_bone_name": "Upper", "tip_bone_name": "Lower", "target_object": target.name,
             "pole_object": pole.name, "affected_meshes": [skin.name], "constraint_name": "Probe IK"}

    def call(tool, **params):
        return runtime.dispatch("rig." + tool, params)

    def diagnosed():
        return call("deformation_inspect", object_name=rig.name, mesh_object=skin.name, bone_names=["Upper", "Lower", "Protected"],
                    vertex_indices=list(range(7)), coordinate_space="WORLD", target_object=target.name, tip_bone_name="Lower")

    def points():
        bpy.context.view_layer.update()
        evaluated = skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
        geometry = evaluated.to_mesh()
        try:
            return [list(vertex.co) for vertex in geometry.vertices]
        finally:
            evaluated.to_mesh_clear()

    rest_points = points()
    constraint = rig.pose.bones["Lower"].constraints.new("IK")
    constraint.name, constraint.target, constraint.pole_target = "Probe IK", target, pole
    constraint.use_stretch, constraint.use_tail, constraint.iterations = False, True, 128

    def measured() -> dict:
        bpy.context.view_layer.update()
        evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        lower_pose, upper_pose = evaluated.pose.bones["Lower"], evaluated.pose.bones["Upper"]
        return {"endpoint": list(lower_pose.tail), "elbow": list(upper_pose.tail),
                "distance": (lower_pose.tail - target.location).length,
                "protected": [list(evaluated.pose.bones["Protected"].head), list(evaluated.pose.bones["Protected"].tail)]}

    constraint.chain_count = 1
    wrong = measured()
    before_diagnostic = diagnosed()
    configured = call("ik_configure", **scope, pole_angle=0.)
    assert configured["affected_objects"] == [rig.name, skin.name] and not configured["created"]
    correct = measured()
    correct_points = points()
    diagnostic = diagnosed()
    assert diagnostic["endpoint_target"]["distance"] < 1e-4 and diagnostic["topology_correspondence_verified"]
    assert all(item["deform_weight_sum"] == 1. for item in diagnostic["weights"])
    assert diagnostic["unmatched_groups"] == ["ProtectedDetail"]
    assert correct_points[4:] == rest_points[4:] and correct_points[:4] != rest_points[:4]
    assert all(item["locked"] for sample in diagnostic["weights"] for item in sample["memberships"] if item["group"] == "ProtectedDetail")
    runtime.dispatch("transform.set", {"object_name": target.name, "location": [1.2, .9, .1]})
    moved_control = diagnosed()
    assert moved_control["endpoint_target"]["distance"] < 1e-4
    assert points()[:4] != correct_points[:4] and points()[4:] == rest_points[4:]
    runtime.dispatch("transform.set", {"object_name": target.name, "location": [1.1, 1.1, 0.]})
    call("ik_configure", **scope, pole_angle=math.pi)
    opposite = measured()
    assert wrong["distance"] > 0.1, wrong
    assert correct["distance"] < 1e-4 and opposite["distance"] < 1e-4, (correct, opposite)
    assert abs(correct["elbow"][2] - opposite["elbow"][2]) > 0.5, (correct, opposite)
    assert correct["protected"] == wrong["protected"] == opposite["protected"]
    evaluated_alias = alias.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert list(evaluated_alias.pose.bones["Lower"].tail) == [0., 2., 0.]
    assert alias.data == rig.data and len(alias.pose.bones["Lower"].constraints) == 0
    before_settings = rig_ik._configuration(constraint)
    grants[Permission.EDIT_ANIMATION.value] = False
    try:
        call("ik_configure", **scope, influence=.3)
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    else:
        raise AssertionError("IK bypassed denied animation permission")
    assert rig_ik._configuration(constraint) == before_settings
    grants[Permission.EDIT_ANIMATION.value] = True

    # Native failure after observed output: measured compensation restores exactly
    # this operation's settings while preserving the native constraint identity.
    original_check = rig_ik._Boundary.check
    failed = False

    def fail_after_output(boundary, **kwargs):
        nonlocal failed
        result = original_check(boundary, **kwargs)
        if not failed and boundary.constraint is not None and abs(boundary.constraint.influence-.4) < 1e-6:
            failed = True
            raise RuntimeError("Injected measured postwrite failure")
        return result

    rig_ik._Boundary.check = fail_after_output
    try:
        call("ik_configure", **scope, influence=.4)
    except BridgeError as error:
        assert error.context["rollback_verified"] and not error.context["possible_mutation"]
    else:
        raise AssertionError("Injected IK failure was hidden")
    finally:
        rig_ik._Boundary.check = original_check
    assert rig_ik._configuration(constraint) == before_settings
    removed = call("ik_remove", **scope, confirm=True)
    assert removed["removed"] and not rig.pose.bones["Lower"].constraints
    assert points() == rest_points
    created = call("ik_configure", **scope, create=True, pole_angle=0.)
    assert created["created"] and diagnosed()["endpoint_target"]["distance"] < 1e-4
    call("ik_remove", **scope, confirm=True)
    assert skin_state() == frozen_skin
    assert [[list(row) for row in bone.matrix_local] for bone in rig.data.bones] == frozen_rest
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    print("BLENDER_CODEX_RIG_IK_SMOKE_OK " + json.dumps({"blender": bpy.app.version_string,
          "native_probe_only": False, "wrong_chain": wrong, "two_bone": correct, "opposite_pole": opposite,
          "diagnosed_before_distance": before_diagnostic["endpoint_target"]["distance"],
          "measured_skin_vertices": diagnostic["base_vertex_count"], "protected_limb_and_shared_rest_alias_preserved": True,
          "deform_only_weights_exclude_locked_detail": True, "typed_create_update_remove_and_owned_compensation_verified": True,
          "typed_control_motion_followed_by_evaluated_skin": True, "rest_geometry_groups_and_all_base_weights_preserved": True,
          "full_character_acceptance_verified": False, "native_undo_verified": False, "project_saved": False}))


try:
    main()
finally:
    blender_codex_bridge.unregister()
