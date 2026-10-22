"""Owned native automatic-weight mutation/restoration probe; isolated runner only."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

from blender_codex_bridge.tools import _animation_scope as scope  # noqa: E402
from blender_codex_bridge.utils import preserved_object_context  # noqa: E402


def fixture():
    data = bpy.data.armatures.new("Binding Probe Armature")
    rig = bpy.data.objects.new("Binding Probe Rig", data)
    bpy.context.scene.collection.objects.link(rig)
    with preserved_object_context():
        for obj in list(bpy.context.selected_objects):
            obj.select_set(False)
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="EDIT")
        root, tip = data.edit_bones.new("Upper"), data.edit_bones.new("Lower")
        root.head, root.tail = (0, 0, 0), (0, 0, 1)
        tip.head, tip.tail, tip.parent, tip.use_connect = (0, 0, 1), (0, 0, 2), root, True
        bpy.ops.object.mode_set(mode="OBJECT")
    vertices = [(x, y, z) for z in (0., 1., 2.) for x, y in ((-.3, -.3), (.3, -.3), (.3, .3), (-.3, .3))]
    faces = [(3, 2, 1, 0), (8, 9, 10, 11)] + [(level*4+i, level*4+(i+1)%4, (level+1)*4+(i+1)%4, (level+1)*4+i) for level in range(2) for i in range(4)]
    mesh_data = bpy.data.meshes.new("Binding Probe Skin Data")
    mesh_data.from_pydata(vertices, [], faces)
    mesh = bpy.data.objects.new("Binding Probe Skin", mesh_data)
    bpy.context.scene.collection.objects.link(mesh)
    upper = mesh.vertex_groups.new(name="Upper")
    protected = mesh.vertex_groups.new(name="ProtectedDetail")
    for index in range(len(vertices)):
        upper.add([index], .1+.06*index, "REPLACE")
        protected.add([index], .123, "REPLACE")
    protected.lock_weight = True
    modifier = mesh.modifiers.new("Existing Rig Modifier", "ARMATURE")
    modifier.object = rig
    return rig, mesh, modifier


def state(mesh):
    return {"groups": [(scope.key(group), group.name, group.index, group.lock_weight) for group in mesh.vertex_groups],
            "weights": [[(member.group, member.weight) for member in vertex.groups] for vertex in mesh.data.vertices],
            "parent": scope.key(mesh.parent), "matrix_basis": [list(row) for row in mesh.matrix_basis],
            "matrix_parent_inverse": [list(row) for row in mesh.matrix_parent_inverse],
            "world": [list(row) for row in mesh.matrix_world],
            "modifiers": [(scope.key(modifier), scope.rna_state(modifier)) for modifier in mesh.modifiers]}


def main():
    rig, mesh, modifier = fixture()
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    original = state(mesh)
    before = {group.name: [(index, member.weight) for index, vertex in enumerate(mesh.data.vertices) for member in vertex.groups if member.group == group.index] for group in mesh.vertex_groups}
    started = time.monotonic()
    with bpy.context.temp_override(object=rig, active_object=rig,
                                   selected_objects=[mesh, rig], selected_editable_objects=[mesh, rig]):
        assert bpy.ops.object.parent_set(type="ARMATURE_AUTO", keep_transform=True) == {"FINISHED"}
    native_seconds = time.monotonic()-started
    after = state(mesh)
    assert after["weights"] != original["weights"]
    assert mesh.parent == rig and mesh.modifiers[0] == modifier and len(mesh.modifiers) == 1
    protected = mesh.vertex_groups["ProtectedDetail"]
    assert protected.lock_weight and [(index, member.weight) for index, vertex in enumerate(mesh.data.vertices) for member in vertex.groups if member.group == protected.index] == before["ProtectedDetail"]
    lower = mesh.vertex_groups["Lower"]
    assert lower.index == len(original["groups"])
    mesh.vertex_groups.remove(lower)
    for name, memberships in before.items():
        group = mesh.vertex_groups[name]
        group.remove(list(range(len(mesh.data.vertices))))
        for index, weight in memberships:
            group.add([index], weight, "REPLACE")
    mesh.parent = None
    mesh.matrix_parent_inverse = original["matrix_parent_inverse"]
    mesh.matrix_basis = original["matrix_basis"]
    bpy.context.view_layer.update()
    restored = state(mesh)
    assert restored == original, (restored, original)
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    print("BLENDER_RIG_BINDING_PROBE_OK " + json.dumps({"blender_version": bpy.app.version_string,
        "existing_deform_weights_changed": True, "locked_unrelated_group_preserved": True,
        "existing_modifier_identity_preserved": True, "new_lower_group_created": True,
        "full_weight_parent_matrix_modifier_restoration_verified": True, "native_blocking_seconds": native_seconds,
        "temporary_override_preserves_physical_selection_and_active": True,
        "product_workflow_verified": False}), flush=True)


if __name__ == "__main__":
    main()
