"""Disposable skinned-character weight correction through typed tools.

Run only through run_blender_checks.py. Python setup and independent evaluation
are fixture code; product edits use the structured weight tools exclusively.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission  # noqa: E402
from blender_codex_bridge.tools import weight_brushes  # noqa: E402


class Context:
    def __init__(self):
        self.granted = True
        self.state = SimpleNamespace(snapshot=lambda: {"paused": False, "emergency_stopped": False})
        self.check_cancelled = lambda: None

    def require(self, *permissions):
        if not self.granted and Permission.EDIT_MESH in permissions:
            raise BridgeError("PERMISSION_DENIED", "Fixture denied weight editing")


def memberships(obj):
    names = {group.index: group.name for group in obj.vertex_groups}
    return [{names[member.group]: float(member.weight) for member in vertex.groups}
            for vertex in obj.data.vertices]


def evaluated_vertices(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return [tuple(vertex.co) for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def require_close(actual, expected, message):
    assert math.isclose(actual, expected, rel_tol=0, abs_tol=2e-5), (message, actual, expected)


def main():
    scene = bpy.context.scene
    active = bpy.context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    created = []
    context = Context()
    try:
        data = bpy.data.meshes.new("WeightCharacterMesh")
        data.from_pydata([(-1, 0, 0), (1, 0, 0), (-1, 1, 0), (1, 1, 0), (-1, 2, 0), (1, 2, 0)],
                         [], [(0, 1, 3, 2), (2, 3, 5, 4)])
        character = bpy.data.objects.new("WeightCharacter", data)
        scene.collection.objects.link(character)
        created.append(character)
        left = character.vertex_groups.new(name="Left")
        right = character.vertex_groups.new(name="Right")
        protected_group = character.vertex_groups.new(name="ProtectedDetail")
        left.add(list(range(6)), 1.0, "REPLACE")
        right.add(list(range(6)), 0.0, "REPLACE")
        protected_group.add(list(range(6)), 0.125, "REPLACE")
        protected_group.lock_weight = True

        armature_data = bpy.data.armatures.new("WeightCharacterRigData")
        armature = bpy.data.objects.new("WeightCharacterRig", armature_data)
        scene.collection.objects.link(armature)
        created.append(armature)
        for obj in list(bpy.context.selected_objects):
            obj.select_set(False)
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode="EDIT")
        for name, x in (("Left", -1), ("Right", 1)):
            bone = armature_data.edit_bones.new(name)
            bone.head, bone.tail = (x, 0, 0), (x, 2, 0)
        bpy.ops.object.mode_set(mode="OBJECT")
        armature.pose.bones["Left"].location.x = -0.5
        armature.pose.bones["Right"].location.x = 0.5
        modifier = character.modifiers.new(name="MeasuredSkin", type="ARMATURE")
        modifier.object = armature
        modifier.use_bone_envelopes = False
        modifier.use_vertex_groups = True

        donor_data = bpy.data.meshes.new("WeightSurfaceDonorMesh")
        donor_data.from_pydata([(0.25, 1.5, 0), (1.25, 1.5, 0), (0.75, 2.5, 0)], [], [(0, 1, 2)])
        donor = bpy.data.objects.new("WeightSurfaceDonor", donor_data)
        donor.location.x = 0.25
        scene.collection.objects.link(donor)
        created.append(donor)
        donor_left = donor.vertex_groups.new(name="DonorLeft")
        donor_right = donor.vertex_groups.new(name="DonorRight")
        for index, value in enumerate((0.0, 0.5, 0.0)):
            donor_left.add([index], value, "REPLACE")
            donor_right.add([index], 1.0 - value, "REPLACE")
        donor_left.lock_weight = donor_right.lock_weight = True
        unrelated = bpy.data.objects.new("ProtectedUnrelatedObject", None)
        unrelated.location = (7, 8, 9)
        scene.collection.objects.link(unrelated)
        created.append(unrelated)

        # Restore initial editor context after fixture construction. Product calls
        # must preserve it while editing explicitly named character data.
        for obj in list(bpy.context.selected_objects):
            obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active
        context_before = ([obj.name for obj in bpy.context.selected_objects],
                          bpy.context.view_layer.objects.active.name if active else None,
                          bpy.context.mode, scene.frame_current_final)
        base_geometry = [tuple(vertex.co) for vertex in character.data.vertices]
        donor_before = memberships(donor)
        donor_geometry_before = [tuple(vertex.co) for vertex in donor.data.vertices]
        character_weights_before = memberships(character)
        group_indices_before = (character.vertex_groups.active_index, donor.vertex_groups.active_index)
        component_selection_before = ([vertex.select for vertex in character.data.vertices],
                                      [edge.select for edge in character.data.edges],
                                      [polygon.select for polygon in character.data.polygons])
        protected_before = [row["ProtectedDetail"] for row in memberships(character)]
        unrelated_before = tuple(unrelated.location)
        before = evaluated_vertices(character)
        require_close(before[1][0], 0.5, "Broken right-side skin follows the left bone")

        brush = {"object_name": character.name, "group_name": "Right", "vertex_indices": [1],
                 "strokes": [{"center": [1, 0, 0], "radius": 0.25, "strength": 1.0, "weight": 1.0}],
                 "coordinate_space": "LOCAL", "blend_mode": "MIX", "falloff": "SMOOTH",
                 "protected_groups": ["ProtectedDetail"]}
        context.granted = False
        denied_before = memberships(character)
        try:
            weight_brushes.brush_stroke(context, brush)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Denied edit was accepted")
        finally:
            context.granted = True
        assert memberships(character) == denied_before
        weight_brushes.brush_stroke(context, brush)
        weight_brushes.brush_stroke(context, {**brush, "group_name": "Left", "strokes": [
            {"center": [1, 0, 0], "radius": 0.25, "strength": 1.0, "weight": 0.0}]})
        after_brush = evaluated_vertices(character)
        require_close(after_brush[1][0], 1.5, "Brush-corrected skin follows the right bone")
        require_close(after_brush[3][0], 0.5, "Brush preserves other explicit regions")

        mirror = {"object_name": character.name, "source_vertex_indices": [0, 2, 4], "vertex_indices": [3],
                  "group_mapping": [{"source_group": "Left", "target_group": "Right"},
                                    {"source_group": "Right", "target_group": "Left"}],
                  "axis": "X", "plane_offset": 0.0, "coordinate_space": "LOCAL", "max_distance": 0.001,
                  "protected_groups": ["ProtectedDetail"]}
        right.lock_weight = True
        locked_before = memberships(character)
        try:
            weight_brushes.mirror_geometric(context, mirror)
        except BridgeError:
            pass
        else:
            raise AssertionError("Locked target group was edited")
        finally:
            right.lock_weight = False
        assert memberships(character) == locked_before
        weight_brushes.mirror_geometric(context, mirror)
        after_mirror = evaluated_vertices(character)
        require_close(after_mirror[3][0], 1.5, "Mirrored skin correction follows counterpart bone")

        weight_brushes.transfer_surface(context, {
            "source_object": donor.name, "object_name": character.name,
            "source_polygon_indices": [0], "vertex_indices": [5],
            "group_mapping": [{"source_group": "DonorLeft", "target_group": "Left"},
                              {"source_group": "DonorRight", "target_group": "Right"}],
            "coordinate_space": "WORLD", "max_distance": 0.001, "protected_groups": ["ProtectedDetail"],
        })
        after_surface = evaluated_vertices(character)
        require_close(left.weight(5), 0.125, "Barycentric left influence")
        require_close(right.weight(5), 0.875, "Barycentric right influence")
        require_close(after_surface[5][0], 1.375, "Surface-interpolated skinning deformation")
        assert memberships(donor) == donor_before
        assert [tuple(vertex.co) for vertex in donor.data.vertices] == donor_geometry_before
        assert (character.vertex_groups.active_index, donor.vertex_groups.active_index) == group_indices_before
        assert ([vertex.select for vertex in character.data.vertices],
                [edge.select for edge in character.data.edges],
                [polygon.select for polygon in character.data.polygons]) == component_selection_before
        final_weights = memberships(character)
        assert all(final_weights[index] == character_weights_before[index] for index in (0, 2, 4))
        assert [row["ProtectedDetail"] for row in memberships(character)] == protected_before
        assert [tuple(vertex.co) for vertex in character.data.vertices] == base_geometry
        assert tuple(unrelated.location) == unrelated_before
        for index in (0, 2, 4):
            require_close(after_surface[index][0], before[index][0], "Protected source-side motion")
        assert ([obj.name for obj in bpy.context.selected_objects],
                bpy.context.view_layer.objects.active.name if active else None,
                bpy.context.mode, scene.frame_current_final) == context_before
        print("BLENDER_CODEX_WEIGHT_BRUSHES_SMOKE_OK " + json.dumps({
            "blender_version": bpy.app.version_string,
            "before_right_x": before[1][0], "brush_right_x": after_brush[1][0],
            "mirror_right_x": after_mirror[3][0], "surface_right_x": after_surface[5][0],
            "protected_groups_preserved": True, "source_and_other_objects_preserved": True,
            "evaluated_deformation_verified": True, "full_character_acceptance_verified": False,
            "native_undo_acceptance_verified": False, "project_saved": False,
        }, sort_keys=True))
    finally:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in reversed(created):
            bpy.data.objects.remove(obj, do_unlink=True)


if __name__ == "__main__":
    main()
