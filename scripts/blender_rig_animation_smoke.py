"""Headless Blender smoke test for structured rigging and animation domains."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy  # type: ignore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "addon"))

from blender_codex_bridge.tools import animation, rigging  # noqa: E402


def main() -> None:
    created_objects: list[str] = []
    try:
        mesh_data = bpy.data.meshes.new("RigSmokeMeshData")
        mesh_data.from_pydata(
            [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
            [],
            [(0, 1, 2)],
        )
        mesh = bpy.data.objects.new("RigSmokeMesh", mesh_data)
        bpy.context.scene.collection.objects.link(mesh)
        created_objects.append(mesh.name)
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh

        created = rigging.create_rig(
            object(),
            {
                "name": "RigSmokeArmature",
                "root_bone_name": "Root",
                "root_head": [0.0, 0.0, 0.0],
                "root_tail": [0.0, 0.0, 1.0],
            },
        )
        armature_name = created["object"]
        created_objects.append(armature_name)
        assert bpy.context.view_layer.objects.active == mesh
        assert mesh.select_get()

        rigging.add_bone(
            object(),
            {
                "object_name": armature_name,
                "bone_name": "Forearm.Temp",
                "head": [0.0, 0.0, 1.0],
                "tail": [0.0, 0.0, 2.0],
                "parent_name": "Root",
                "use_connect": True,
            },
        )
        updated = rigging.update_bone(
            object(),
            {
                "object_name": armature_name,
                "bone_name": "Forearm.Temp",
                "new_name": "Forearm.L",
                "tail": [0.25, 0.0, 2.0],
                "roll": 0.1,
            },
        )
        assert updated["bone"]["name"] == "Forearm.L"

        pose = rigging.pose_transform(
            object(),
            {
                "object_name": armature_name,
                "bone_name": "Forearm.L",
                "rotation_euler": [0.1, 0.2, 0.3],
                "scale": [1.0, 1.0, 1.0],
            },
        )
        assert pose["pose_bone"]["rotation_mode"] == "XYZ"

        target = bpy.data.objects.new("RigSmokeTarget", None)
        bpy.context.scene.collection.objects.link(target)
        created_objects.append(target.name)
        constraint = rigging.add_constraint(
            object(),
            {
                "object_name": armature_name,
                "bone_name": "Forearm.L",
                "constraint_type": "COPY_ROTATION",
                "name": "Smoke Copy Rotation",
                "target_object": target.name,
                "influence": 0.5,
            },
        )
        assert constraint["constraint"]["target"] == target.name
        rigging.remove_constraint(
            object(),
            {
                "object_name": armature_name,
                "bone_name": "Forearm.L",
                "constraint_name": "Smoke Copy Rotation",
            },
        )

        binding = rigging.bind_mesh(
            object(),
            {
                "mesh_object": mesh.name,
                "armature_object": armature_name,
                "method": "EMPTY_GROUPS",
                "parent": True,
            },
        )
        assert binding["parent"] == armature_name
        assert {"Root", "Forearm.L"} <= {group.name for group in mesh.vertex_groups}

        automatic_data = bpy.data.meshes.new("RigSmokeAutomaticMeshData")
        automatic_data.from_pydata(
            [
                (-0.5, -0.5, 0.0),
                (0.5, -0.5, 0.0),
                (0.5, 0.5, 0.0),
                (-0.5, 0.5, 0.0),
                (-0.5, -0.5, 2.0),
                (0.5, -0.5, 2.0),
                (0.5, 0.5, 2.0),
                (-0.5, 0.5, 2.0),
            ],
            [],
            [
                (0, 1, 2, 3),
                (4, 7, 6, 5),
                (0, 4, 5, 1),
                (1, 5, 6, 2),
                (2, 6, 7, 3),
                (4, 0, 3, 7),
            ],
        )
        automatic_mesh = bpy.data.objects.new("RigSmokeAutomaticMesh", automatic_data)
        bpy.context.scene.collection.objects.link(automatic_mesh)
        created_objects.append(automatic_mesh.name)
        automatic_binding = rigging.bind_mesh(
            object(),
            {
                "mesh_object": automatic_mesh.name,
                "armature_object": armature_name,
                "method": "AUTOMATIC",
                "parent": True,
            },
        )
        assert automatic_binding["parent"] == armature_name
        assert automatic_binding["vertex_group_count"] >= 1

        animation.set_range(
            object(),
            {"start": -5, "end": 48, "use_preview": True, "preview_start": 1, "preview_end": 24},
        )
        frame = animation.set_frame(object(), {"frame": 12.5})
        assert math.isclose(frame["frame_final"], 12.5)
        data_path = 'pose.bones["Forearm.L"].rotation_euler'
        inserted = animation.insert_keyframe(
            object(),
            {
                "object_name": armature_name,
                "data_path": data_path,
                "frame": 12.5,
                "index": 1,
                "group": "Forearm.L",
            },
        )
        assert inserted["inserted"] is True
        animation_state = animation.inspect_animation(
            object(),
            {"object_name": armature_name, "max_curves": 32, "max_keyframes": 128},
        )
        assert animation_state["action"] is not None
        assert animation_state["action"]["fcurve_count"] >= 1
        deleted = animation.delete_keyframe(
            object(),
            {
                "object_name": armature_name,
                "data_path": data_path,
                "frame": 12.5,
                "index": 1,
                "group": "Forearm.L",
            },
        )
        assert deleted["deleted"] is True

        rig_state = rigging.inspect_rig(
            object(),
            {"object_name": armature_name, "max_bones": 32, "max_constraints": 64},
        )
        assert rig_state["bone_count"] == 2
        assert rig_state["truncated"] == {"bones": False, "constraints": False}
        removed = rigging.remove_bone(
            object(),
            {
                "object_name": armature_name,
                "bone_name": "Forearm.L",
                "reparent_children": False,
            },
        )
        assert removed["bone_count"] == 1

        print(
            "BLENDER_CODEX_RIG_ANIMATION_SMOKE_OK "
            + json.dumps(
                {
                    "blender_version": bpy.app.version_string,
                    "armature": armature_name,
                    "bound_mesh": mesh.name,
                    "action": animation_state["action"]["name"],
                },
                sort_keys=True,
            )
        )
    finally:
        for name in reversed(created_objects):
            obj = bpy.data.objects.get(name)
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)


if __name__ == "__main__":
    main()
