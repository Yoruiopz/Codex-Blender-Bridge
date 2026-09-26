"""Isolated slot-ownership regression; no user .blend is opened or saved."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    manager = PermissionManager(lambda: {p.value: True for p in Permission})
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("materials")
    cube = bpy.data.objects["Cube"]
    original = bpy.data.materials.new("Ownership Original")
    replacement = bpy.data.materials.new("Ownership Replacement")
    cube.data.materials.clear()
    cube.data.materials.append(original)
    duplicate = bpy.data.objects.new("Protected Duplicate", cube.data)
    bpy.context.scene.collection.objects.link(duplicate)
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    geometry = [tuple(v.co) for v in cube.data.vertices]
    indices = [p.material_index for p in cube.data.polygons]
    for method in (
        "material.assign",
        "material.unassign",
        "material.slot_add",
        "material.slot_remove",
    ):
        params = {"object_name": cube.name, "slot_index": 0}
        if method in {"material.assign", "material.slot_add"}:
            params["material_name"] = replacement.name
        try:
            runtime.dispatch(method, params)
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED", error
        else:
            raise AssertionError(f"{method} accepted shared object data")
        assert cube.data == duplicate.data and cube.data.users == 2
        assert list(cube.data.materials) == [original]
        assert duplicate.material_slots[0].material == original
        assert cube.active_material_index == 0
        assert [p.material_index for p in cube.data.polygons] == indices
    # Test fixture explicitly separates data. Production tools never do this implicitly.
    duplicate.data = duplicate.data.copy()
    result = runtime.dispatch(
        "material.assign",
        {"object_name": cube.name, "material_name": replacement.name, "slot_index": 0},
    )
    assert result["affected_objects"] == [cube.name]
    assert cube.material_slots[0].material == replacement
    assert duplicate.material_slots[0].material == original
    runtime.dispatch("material.unassign", {"object_name": cube.name, "slot_index": 0})
    assert cube.material_slots[0].material is None
    runtime.dispatch(
        "material.slot_add", {"object_name": cube.name, "material_name": original.name}
    )
    assert len(cube.material_slots) == 2
    runtime.dispatch("material.slot_remove", {"object_name": cube.name, "slot_index": 1})
    assert len(cube.material_slots) == 1 and cube.material_slots[0].material is None
    assert duplicate.material_slots[0].material == original
    assert [tuple(v.co) for v in cube.data.vertices] == geometry
    assert (
        list(bpy.context.selected_objects) == selected
        and bpy.context.view_layer.objects.active == active
    )
    print(
        json.dumps(
            {
                "material_ownership_smoke": "PASS",
                "blender": bpy.app.version_string,
                "denied_shared_mutators": 4,
                "protected_duplicate_unchanged": True,
                "single_user_mutators_verified": 4,
                "project_saved": False,
            }
        )
    )


try:
    main()
finally:
    blender_codex_bridge.unregister()
