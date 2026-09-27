"""Isolated slot-ownership regression; no user .blend is opened or saved."""

from __future__ import annotations

import json
import sys
import tempfile
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
    runtime.registry.enable_toolset("nodes")
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
    # Shader scope is independent of slot ownership: two separate meshes still share Paint.
    runtime.dispatch("material.unassign", {"object_name": cube.name, "slot_index": 0})
    assert cube.material_slots[0].material is None
    runtime.dispatch(
        "material.slot_add", {"object_name": cube.name, "material_name": original.name}
    )
    assert len(cube.material_slots) == 2
    runtime.dispatch("material.slot_remove", {"object_name": cube.name, "slot_index": 1})
    assert len(cube.material_slots) == 1 and cube.material_slots[0].material is None
    assert duplicate.material_slots[0].material == original
    cube.data.materials[0] = original
    original.use_nodes = True
    tree = original.node_tree
    principled = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    roughness = principled.inputs["Roughness"].default_value
    graph_before = (len(tree.nodes), len(tree.links))
    usage = runtime.dispatch("material.inspect", {"material_name": original.name})
    ownership = usage["materials"][0]["ownership"]
    assert ownership["affected_objects"] == sorted([cube.name, duplicate.name])
    assert ownership["direct_user_count"] == 2 and ownership["requires_shared_consent"]
    for method in (
        "material.set_principled",
        "nodes.add",
        "nodes.remove",
        "nodes.rename",
        "nodes.set_input",
        "nodes.link",
        "nodes.unlink",
        "material.delete",
    ):
        params = {"material_name": original.name, "roughness": 0.123, "only_if_unused": False}
        try:
            runtime.dispatch(method, params)
        except BridgeError as error:
            assert error.code == "INVALID_ARGUMENT" and "allow_shared" in error.message, error
        else:
            raise AssertionError(f"{method} accepted an unacknowledged shared material")
        assert (len(tree.nodes), len(tree.links)) == graph_before
        assert principled.inputs["Roughness"].default_value == roughness
        assert duplicate.material_slots[0].material == original

    shared = {"material_name": original.name, "allow_shared": True}
    result = runtime.dispatch("material.set_principled", {**shared, "roughness": 0.123})
    assert result["ownership"]["affected_object_count"] == 2
    assert abs(principled.inputs["Roughness"].default_value - 0.123) < 1e-6
    runtime.dispatch("nodes.add", {**shared, "node_type": "ShaderNodeRGB", "name": "ScopeRGB"})
    runtime.dispatch("nodes.rename", {**shared, "node_name": "ScopeRGB", "new_name": "ScopedRGB"})
    runtime.dispatch(
        "nodes.set_input",
        {**shared, "node_name": principled.name, "socket_name": "Roughness", "value": roughness},
    )
    endpoints = {
        **shared,
        "from_node": "ScopedRGB",
        "from_socket": "Color",
        "to_node": principled.name,
        "to_socket": "Base Color",
    }
    runtime.dispatch("nodes.link", endpoints)
    assert principled.inputs["Base Color"].is_linked
    runtime.dispatch("nodes.unlink", endpoints)
    assert not principled.inputs["Base Color"].is_linked
    runtime.dispatch("nodes.remove", {**shared, "node_name": "ScopedRGB"})
    assert (len(tree.nodes), len(tree.links)) == graph_before
    assert principled.inputs["Roughness"].default_value == roughness

    # Deletion must not invalidate an edit-mode mesh's material slots.
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        runtime.dispatch("material.delete", {**shared, "only_if_unused": False})
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED", error
    else:
        raise AssertionError("Forced unlink accepted Edit Mode")
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    original_name = original.name
    result = runtime.dispatch("material.delete", {**shared, "only_if_unused": False})
    assert result["ownership_before"]["affected_object_count"] == 2
    assert bpy.data.materials.get(original_name) is None
    assert cube.material_slots[0].material is None and duplicate.material_slots[0].material is None
    # A real linked datablock, not a mock of Blender's library/editability properties.
    replacement.use_nodes = True
    with tempfile.TemporaryDirectory(prefix="bridge-material-library-") as directory:
        library_path = str(Path(directory) / "fixture.blend")
        bpy.data.libraries.write(library_path, {replacement})
        with bpy.data.libraries.load(library_path, link=True) as (_source, target):
            target.materials = [replacement.name]
        linked = target.materials[0]
        assert linked.library is not None
        for method in ("material.set_principled", "nodes.add"):
            try:
                runtime.dispatch(method, {"material_name": linked.name, "allow_shared": True})
            except BridgeError as error:
                assert error.code == "INVALID_ARGUMENT" and "ambiguous" in error.message, error
            else:
                raise AssertionError("Ambiguous material name was accepted")
        replacement.name = "Unique Local Material"
        for method in (
            "material.set_principled",
            "nodes.add",
            "nodes.remove",
            "nodes.rename",
            "nodes.set_input",
            "nodes.link",
            "nodes.unlink",
            "material.delete",
        ):
            try:
                runtime.dispatch(
                    method,
                    {"material_name": linked.name, "allow_shared": True, "only_if_unused": False},
                )
            except BridgeError as error:
                assert error.code == "NOT_IMPLEMENTED", error
            else:
                raise AssertionError(f"{method} accepted a linked material")
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
                "protected_duplicate_preserved_on_denial": True,
                "single_user_mutators_verified": 4,
                "denied_shared_shader_and_delete_mutators": 8,
                "acknowledged_shared_mutators_verified": 8,
                "edit_mode_forced_unlink_denied": True,
                "linked_material_mutators_denied": 8,
                "project_saved": False,
            }
        )
    )


try:
    main()
finally:
    blender_codex_bridge.unregister()
