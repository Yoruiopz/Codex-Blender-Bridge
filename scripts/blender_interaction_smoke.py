"""Isolated Blender smoke test; run with --background --factory-startup."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh  # type: ignore
import bpy  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))

from blender_codex_bridge.checkpoints import CheckpointManager
from blender_codex_bridge.command_queue import CommandQueue
from blender_codex_bridge.errors import BridgeError
from blender_codex_bridge.executor import MainThreadExecutor
from blender_codex_bridge.permissions import Permission, PermissionManager
from blender_codex_bridge.selection import resolve_selection
from blender_codex_bridge.state import BridgeState
from blender_codex_bridge.tool_registry import ToolRegistry
from blender_codex_bridge.tools import interaction


def main() -> None:
    assert bpy.app.background, "This smoke test must not modify an interactive Blender session."
    registry = ToolRegistry(enabled_toolsets=("interaction",))
    interaction.register_tools(registry)
    permissions = {permission.value: True for permission in Permission}
    state = BridgeState()
    executor = MainThreadExecutor(
        command_queue=CommandQueue(),
        registry=registry,
        state=state,
        permissions=PermissionManager(lambda: permissions),
        checkpoints=CheckpointManager(),
    )
    dispatch = executor.dispatch
    cube = bpy.data.objects["Cube"]
    original_counts = (len(cube.data.vertices), len(cube.data.edges), len(cube.data.polygons))
    original_positions = [tuple(vertex.co) for vertex in cube.data.vertices]
    result = dispatch(
        "selection.set", {"object_names": ["Cube", "Camera"], "active_object": "Cube"}
    )
    assert result["selection"]["selected_object_count"] == 2
    result = dispatch("selection.set", {"object_names": ["Camera"], "operation": "REMOVE"})
    assert result["selection"]["active_object"] == "Cube"
    assert result["selection"]["selected_object_count"] == 1
    permissions["EDIT_MESH"] = False
    try:
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "EDIT"})
        raise AssertionError("Permission denial expected")
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    assert cube.mode == "OBJECT"
    permissions["EDIT_MESH"] = True
    entered = dispatch("context.set_mode", {"object_name": "Cube", "mode": "EDIT"})
    assert cube.mode == "EDIT" and entered["selection"]["mode"] == "EDIT_MESH"
    page = dispatch(
        "mesh.components_inspect", {"object_name": "Cube", "element_type": "FACE", "max_items": 2}
    )
    assert page["truncated"] and page["next_offset"] == 2
    assert len(page["items"]) == 2 and page["component_count"] == 6
    assert all(len(item["vertex_indices"]) == 4 for item in page["items"])
    assert all(sum(abs(value) for value in item["center_local"]) == 1.0 for item in page["items"])
    last_page = dispatch(
        "mesh.components_inspect",
        {"object_name": "Cube", "element_type": "FACE", "max_items": 2, "offset": 4},
    )
    assert not last_page["truncated"] and last_page["next_offset"] is None
    result = dispatch(
        "mesh.select_components", {"object_name": "Cube", "element_type": "FACE", "indices": [0]}
    )
    assert result["selected_indices"] == [0]
    assert result["selection"]["mesh_selection"]["selected_faces"] == 1
    selected_page = dispatch(
        "mesh.components_inspect",
        {"object_name": "Cube", "element_type": "FACE", "selected_only": True},
    )
    assert selected_page["matching_component_count"] == 1
    assert selected_page["items"][0]["index"] == 0
    old_id = result["selection"]["mesh_selection"]["selection_id"]
    assert resolve_selection(old_id)["faces"] == [0]
    result = dispatch(
        "mesh.select_components",
        {
            "object_name": "Cube",
            "element_type": "FACE",
            "indices": [1],
            "operation": "ADD",
            "selection_id": old_id,
        },
    )
    assert result["selected_indices"] == [0, 1]
    before_invalid = [face.select for face in bmesh.from_edit_mesh(cube.data).faces]
    try:
        dispatch(
            "mesh.select_components",
            {"object_name": "Cube", "element_type": "FACE", "indices": [0, 999]},
        )
        raise AssertionError("Invalid index expected")
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    assert before_invalid == [face.select for face in bmesh.from_edit_mesh(cube.data).faces]
    result = dispatch(
        "mesh.select_components",
        {"object_name": "Cube", "element_type": "FACE", "indices": [0], "operation": "REMOVE"},
    )
    assert result["selected_indices"] == [1]
    result = dispatch(
        "mesh.select_components", {"object_name": "Cube", "element_type": "EDGE", "indices": [0, 1]}
    )
    assert result["selected_indices"] == [0, 1]
    result = dispatch(
        "mesh.select_components",
        {"object_name": "Cube", "element_type": "VERT", "indices": [0, 1, 2]},
    )
    assert result["selected_indices"] == [0, 1, 2]
    dispatch("context.set_mode", {"object_name": "Cube", "mode": "OBJECT"})
    try:
        resolve_selection(old_id)
        raise AssertionError("Old selection ID should expire after mode switch")
    except BridgeError as error:
        assert error.code == "INVALID_SELECTION"
    assert original_counts == (
        len(cube.data.vertices),
        len(cube.data.edges),
        len(cube.data.polygons),
    )
    assert original_positions == [tuple(vertex.co) for vertex in cube.data.vertices]
    for mode in ("SCULPT", "VERTEX_PAINT", "WEIGHT_PAINT", "TEXTURE_PAINT"):
        dispatch("context.set_mode", {"object_name": "Cube", "mode": mode})
        assert cube.mode == mode
        dispatch("context.set_mode", {"object_name": "Cube", "mode": "OBJECT"})
    armature = bpy.data.objects.new(
        "InteractionArmature", bpy.data.armatures.new("InteractionArmatureData")
    )
    bpy.context.scene.collection.objects.link(armature)
    for mode in ("EDIT", "POSE"):
        dispatch("context.set_mode", {"object_name": armature.name, "mode": mode})
        assert armature.mode == mode
        dispatch("context.set_mode", {"object_name": armature.name, "mode": "OBJECT"})
    result = dispatch("selection.set", {"object_names": []})
    assert result["selection"]["selected_object_count"] == 0
    assert result["selection"]["active_object"] is None
    assert result["operation"]["operation_id"]
    print(
        "BLENDER_CODEX_INTERACTION_SMOKE_OK "
        + json.dumps(
            {"version": bpy.app.version_string, "mesh_counts": original_counts, "saved": False}
        )
    )


if __name__ == "__main__":
    main()
