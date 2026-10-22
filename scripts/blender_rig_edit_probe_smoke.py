"""Disposable rest/pose/context behavior research; official runner only."""

from __future__ import annotations

import json

import bpy


def main():
    data = bpy.data.armatures.new("Rest Probe Data")
    rig = bpy.data.objects.new("Rest Probe Rig", data)
    bpy.context.scene.collection.objects.link(rig)
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active

    def temporary(mode):
        if mode == "EDIT":
            for item in list(bpy.context.selected_objects):
                item.select_set(False)
            rig.select_set(True)
            bpy.context.view_layer.objects.active = rig
        assert bpy.ops.object.mode_set(mode=mode) == {"FINISHED"}
        if mode == "OBJECT":
            rig.select_set(False)
            for item in selected:
                item.select_set(True)
            bpy.context.view_layer.objects.active = active

    temporary("EDIT")
    assert rig.mode == "EDIT"
    parent = data.edit_bones.new("Parent")
    parent.head, parent.tail = (0, 0, 0), (0, 0, 1)
    child = data.edit_bones.new("Child")
    child.head, child.tail, child.parent, child.use_connect = (0, 0, 1), (0, 0, 2), parent, True
    protected = data.edit_bones.new("Protected")
    protected.head, protected.tail = (3, 0, 0), (3, 0, 1)
    temporary("OBJECT")
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    before = {bone.name: (list(bone.head_local), list(bone.tail_local)) for bone in data.bones}
    temporary("EDIT")
    data.edit_bones["Parent"].tail = (.25, 0, 1.)
    direct = {bone.name: (list(bone.head), list(bone.tail)) for bone in data.edit_bones}
    temporary("OBJECT")
    after = {bone.name: (list(bone.head_local), list(bone.tail_local)) for bone in data.bones}
    assert direct["Child"][0] == after["Child"][0] == [.25, 0., 1.]
    assert before["Protected"] == after["Protected"]

    data.bones["Parent"].tail_radius = .05
    data.bones["Child"].head_radius = .1
    radius_before_object = (data.bones["Parent"].tail_radius, data.bones["Child"].head_radius)
    temporary("EDIT")
    parent, child = data.edit_bones["Parent"], data.edit_bones["Child"]
    radius_before = (parent.tail_radius, child.head_radius)
    child.tail.x += .25
    radius_coupled = (parent.tail_radius, child.head_radius)
    temporary("OBJECT")
    data.bones["Parent"].tail_radius = radius_before_object[0]
    data.bones["Child"].head_radius = radius_before_object[1]
    radius_restored = (data.bones["Parent"].tail_radius, data.bones["Child"].head_radius)
    print("RIG_RADIUS_PROBE " + json.dumps({"before": radius_before, "coupled": radius_coupled, "object_restored": radius_restored}))
    assert radius_restored == radius_before_object

    mesh_data = bpy.data.meshes.new("Rest Probe Skin Data")
    mesh_data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 1)], [], [(0, 1, 2)])
    skin = bpy.data.objects.new("Rest Probe Skin", mesh_data)
    bpy.context.scene.collection.objects.link(skin)
    group = skin.vertex_groups.new(name="Child")
    group.add([0, 1, 2], 1., "REPLACE")
    modifier = skin.modifiers.new("Skin", "ARMATURE")
    modifier.object = rig
    prop = bpy.data.objects.new("Rest Probe Bone Parent", None)
    bpy.context.scene.collection.objects.link(prop)
    prop.parent, prop.parent_type, prop.parent_bone = rig, "BONE", "Child"
    follower = bpy.data.objects.new("Rest Probe Constraint", None)
    bpy.context.scene.collection.objects.link(follower)
    constraint = follower.constraints.new("COPY_LOCATION")
    constraint.target, constraint.subtarget = rig, "Child"
    rig.pose.bones["Child"].keyframe_insert(data_path="location", frame=1)
    action = rig.animation_data.action
    slot = rig.animation_data.action_slot
    curves = action.layers[0].strips[0].channelbag(slot).fcurves
    paths_before = [curve.data_path for curve in curves]
    temporary("EDIT")
    data.edit_bones["Child"].name = "Renamed"
    temporary("OBJECT")
    paths_after = [curve.data_path for curve in curves]
    assert skin.vertex_groups.get("Renamed") is not None and skin.vertex_groups.get("Child") is None
    assert prop.parent_bone == constraint.subtarget == "Renamed"
    assert paths_before != paths_after and all('"Renamed"' in path for path in paths_after)
    assert rig.animation_data.action == action
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    print("RIG_RNA_COLLECTIONS " + json.dumps({label: [(prop.identifier, prop.type) for prop in owner.bl_rna.properties if not prop.is_readonly and prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}] for label, owner in (("Armature", data), ("Bone", data.bones[0]), ("PoseBone", rig.pose.bones[0]))}))
    print("RIG_RNA_SELECTION " + json.dumps({label: [prop.identifier for prop in owner.bl_rna.properties if "select" in prop.identifier] for label, owner in (("Bone", data.bones[0]), ("PoseBone", rig.pose.bones[0]))}))
    print("BLENDER_RIG_EDIT_PROBE_OK " + json.dumps({"blender_version": bpy.app.version_string,
        "physical_context_restore_preserves_global_selection_active": True,
        "mode_override_targets_actual_view_layer_active": True,
        "connected_child_head_follows_parent_tail": True,
        "protected_rest_bone_preserved": True,
        "rename_propagates_vertex_group_action_path_bone_parent_constraint": True,
        "action_identity_preserved": True, "product_workflow_verified": False}), flush=True)


if __name__ == "__main__":
    main()
