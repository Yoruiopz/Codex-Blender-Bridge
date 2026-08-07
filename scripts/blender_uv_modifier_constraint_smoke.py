"""Headless Blender smoke test for UV, modifier, and constraint domains."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy  # type: ignore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "addon"))

from blender_codex_bridge import selection  # noqa: E402
from blender_codex_bridge.tools import constraints, modifiers, uv  # noqa: E402


def main() -> None:
    created_objects: list[str] = []
    try:
        bpy.ops.mesh.primitive_cube_add()
        mesh = bpy.context.object
        assert mesh is not None
        mesh.name = "DomainSmokeMesh"
        created_objects.append(mesh.name)

        target = bpy.data.objects.new("DomainSmokeTarget", None)
        bpy.context.scene.collection.objects.link(target)
        created_objects.append(target.name)

        added_modifier = modifiers.add_modifier(
            object(),
            {
                "object_name": mesh.name,
                "modifier_type": "BEVEL",
                "modifier_name": "Safe Bevel",
                "settings": {"width": 0.05, "segments": 2},
            },
        )
        assert abs(added_modifier["created"]["settings"]["width"] - 0.05) < 1e-6
        modifiers.set_modifier(
            object(),
            {
                "object_name": mesh.name,
                "modifier_name": "Safe Bevel",
                "settings": {"width": 0.075},
            },
        )
        inspected_width = modifiers.inspect_modifiers(
            object(), {"object_name": mesh.name, "modifier_name": "Safe Bevel"}
        )["modifier"]["settings"]["width"]
        assert abs(inspected_width - 0.075) < 1e-6

        added_constraint = constraints.add_constraint(
            object(),
            {
                "object_name": mesh.name,
                "constraint_type": "COPY_LOCATION",
                "constraint_name": "Follow Target",
                "settings": {"target": target.name, "influence": 0.5},
            },
        )
        assert added_constraint["created"]["settings"]["target"] == target.name
        constraints.set_constraint(
            object(),
            {
                "object_name": mesh.name,
                "constraint_name": "Follow Target",
                "settings": {"use_offset": True},
            },
        )

        bpy.context.view_layer.objects.active = mesh
        mesh.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        selection_state = selection.inspect_selection({"create_selection_id": True})
        selection_id = selection_state["mesh_selection"]["selection_id"]
        unwrapped = uv.unwrap(
            object(),
            {
                "object_name": mesh.name,
                "selection_id": selection_id,
                "uv_layer": "SmokeUV",
                "create_if_missing": True,
                "method": "ANGLE_BASED",
                "margin": 0.001,
            },
        )
        assert unwrapped["faces_affected"] == 6
        projected = uv.smart_project(
            object(),
            {
                "object_name": mesh.name,
                "selection_id": selection_id,
                "uv_layer": "SmokeUV",
                "angle_limit": 1.0,
                "island_margin": 0.001,
            },
        )
        assert projected["faces_affected"] == 6
        packed = uv.pack_islands(
            object(),
            {
                "object_name": mesh.name,
                "selection_id": selection_id,
                "uv_layer": "SmokeUV",
                "margin": 0.001,
            },
        )
        assert packed["post_state"]["island_count"] >= 1
        uv_state = uv.inspect_uv(
            object(),
            {
                "object_name": mesh.name,
                "selection_id": selection_id,
                "uv_layer": "SmokeUV",
                "selected_only": True,
            },
        )
        assert uv_state["analysis"]["scoped_face_count"] == 6

        bpy.ops.object.mode_set(mode="OBJECT")
        modifiers.remove_modifier(
            object(),
            {"object_name": mesh.name, "modifier_name": "Safe Bevel"},
        )
        modifiers.add_modifier(
            object(),
            {
                "object_name": mesh.name,
                "modifier_type": "TRIANGULATE",
                "modifier_name": "Apply Me",
            },
        )
        applied = modifiers.apply_modifier(
            object(),
            {"object_name": mesh.name, "modifier_name": "Apply Me"},
        )
        assert applied["modifier_count_after"] == 0
        constraints.remove_constraint(
            object(),
            {"object_name": mesh.name, "constraint_name": "Follow Target"},
        )

        print(
            "BLENDER_CODEX_UV_MODIFIER_CONSTRAINT_SMOKE_OK "
            + json.dumps(
                {
                    "blender_version": bpy.app.version_string,
                    "mesh": mesh.name,
                    "uv_layer": unwrapped["uv_layer"],
                    "island_count": uv_state["analysis"]["island_count"],
                },
                sort_keys=True,
            )
        )
    finally:
        if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for name in reversed(created_objects):
            obj = bpy.data.objects.get(name)
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)


if __name__ == "__main__":
    main()
