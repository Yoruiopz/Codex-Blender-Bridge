"""Isolated typed nested-GN workflow with independent evaluated mesh evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError, ErrorCode  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import geometry_node_groups as groups  # noqa: E402


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: True for permission in Permission}
    manager = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("geometry_nodes")
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active

    def call(method, **params):
        return runtime.dispatch("geometry_nodes." + method, params)

    def interface(tree, socket_name, direction="INPUT"):
        return next(item for item in tree.interface.items_tree if item.item_type == "SOCKET" and item.name == socket_name and item.in_out == direction)

    def endpoint(tree, node_name, socket_name, direction):
        node = tree.nodes[node_name]
        sockets = node.inputs if direction == "INPUT" else node.outputs
        return next(item.identifier for item in sockets if item.name == socket_name)

    def bounds(obj):
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            assert len(mesh.vertices) == 6 and len(mesh.polygons) == 2
            return [[min(vertex.co[axis] for vertex in mesh.vertices), max(vertex.co[axis] for vertex in mesh.vertices)] for axis in range(3)]
        finally:
            evaluated.to_mesh_clear()

    child_name, parent_name, protected_name = "Typed GN Child", "Typed GN Parent", "Protected GN Parent"
    call("create", group_name=child_name, passthrough=False)
    call("interface_add", group_name=child_name, name="Width", default_value=2.0)
    call("node_add", group_name=child_name, node_type="GeometryNodeMeshGrid", name="Grid")
    for socket_name, value in (("Vertices X", 3), ("Vertices Y", 2), ("Size Y", 2.0)):
        call("node_set_input", group_name=child_name, node_name="Grid", socket_name=socket_name, value=value)
    call("link", group_name=child_name, from_node="Group Input", from_socket="Width", to_node="Grid", to_socket="Size X")
    call("link", group_name=child_name, from_node="Grid", from_socket="Mesh", to_node="Group Output", to_socket="Geometry")
    base = bpy.data.meshes.new("Shared Empty Base")
    objects = []
    for tree_name, object_name, width in ((parent_name, "Typed GN Target", 4.0), (protected_name, "Typed GN Protected", 2.0)):
        call("create", group_name=tree_name, passthrough=False)
        call("interface_add", group_name=tree_name, name="Width", default_value=width)
        if tree_name == parent_name:
            for input_name, socket_type in (("Offset", "NodeSocketVector"), ("Enabled", "NodeSocketBool"),
                                            ("Segments", "NodeSocketInt"), ("Tint", "NodeSocketColor"), ("Label", "NodeSocketString")):
                call("interface_add", group_name=tree_name, name=input_name, socket_type=socket_type)
        call("group_bind", parent_group_name=tree_name, child_group_name=child_name, node_name="Nested")
        tree = bpy.data.node_groups[tree_name]
        for source, source_socket, target, target_socket in (("Group Input", "Width", "Nested", "Width"), ("Nested", "Geometry", "Group Output", "Geometry")):
            call("group_link", group_name=tree_name, from_node=source, from_socket_identifier=endpoint(tree, source, source_socket, "OUTPUT"),
                 to_node=target, to_socket_identifier=endpoint(tree, target, target_socket, "INPUT"))
        obj = bpy.data.objects.new(object_name, base)
        bpy.context.scene.collection.objects.link(obj)
        call("group_attach", group_name=tree_name, object_name=obj.name, modifier_name="Procedural")
        objects.append(obj)
    target, protected = objects
    protected_bounds = bounds(protected)
    assert bounds(target) == [[-2.0, 2.0], [-1.0, 1.0], [0.0, 0.0]]
    root = bpy.data.node_groups[parent_name]
    width_socket = interface(root, "Width")
    identifier = width_socket.identifier
    result = call("modifier_set_input", object_name=target.name, modifier_name="Procedural", socket_identifier=identifier, value=6.0)
    assert result["group_definition_changed"] is False
    assert bounds(target) == [[-3.0, 3.0], [-1.0, 1.0], [0.0, 0.0]]
    assert bounds(protected) == protected_bounds
    width_socket.name = "Renamed Width"  # Explicit fixture-only manual edit.
    inspected = call("modifier_inspect", object_name=target.name, modifier_name="Procedural")
    width_record = next(item for item in inspected["inputs"] if item["identifier"] == identifier)
    assert width_record["name"] == "Renamed Width" and width_record["value"] == 6.0
    for input_name, value in (("Offset", [1.0, 2.0, 3.0]), ("Enabled", True), ("Segments", 3),
                              ("Tint", [0.25, 0.5, 0.75, 1.0]), ("Label", "typed value")):
        result = call("modifier_set_input", object_name=target.name, modifier_name="Procedural", socket_identifier=interface(root, input_name).identifier, value=value)
        assert result["value"] == value

    original = bpy.data.node_groups[child_name]
    copied = call("group_copy_for_node", parent_group_name=parent_name, node_name="Nested", new_group_name="Isolated GN Child")
    assert copied["deep_copy"] is False and root.nodes["Nested"].node_tree != original
    isolated = root.nodes["Nested"].node_tree
    y_identifier = endpoint(isolated, "Grid", "Size Y", "INPUT")
    try:
        call("group_set_input", group_name=isolated.name, node_name="Grid", socket_identifier=y_identifier, value=4.0)
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    else:
        raise AssertionError("Nested parent scope did not require shared acknowledgement")
    call("group_set_input", group_name=isolated.name, node_name="Grid", socket_identifier=y_identifier, value=4.0, allow_shared=True)
    assert bounds(target) == [[-3.0, 3.0], [-2.0, 2.0], [0.0, 0.0]]
    assert bounds(protected) == protected_bounds
    assert original.nodes["Grid"].inputs["Size Y"].default_value == 2.0

    try:
        call("group_bind", parent_group_name=isolated.name, child_group_name=parent_name, node_name="Cycle", allow_shared=True)
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT" and "recursive" in error.message
    else:
        raise AssertionError("Recursive dependency was accepted")
    assert isolated.nodes.get("Cycle") is None

    grants[Permission.TRANSFORM_OBJECTS.value] = False
    try:
        call("modifier_set_input", object_name=target.name, modifier_name="Procedural", socket_identifier=identifier, value=8.0)
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    else:
        raise AssertionError("Modifier edit bypassed live permission")
    assert target.modifiers["Procedural"][identifier] == 6.0
    grants[Permission.TRANSFORM_OBJECTS.value] = True

    # A post-allocation fault restores binding but respects denied datablock deletion.
    grants[Permission.DELETE_OBJECTS.value] = False
    original_gate = groups._gate

    def fail_after_copy(context, *required):
        original_gate(context, *required)
        if bpy.data.node_groups.get("Retained GN Copy") is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Fixture post-allocation fault")

    groups._gate = fail_after_copy
    try:
        call("group_copy_for_node", parent_group_name=parent_name, node_name="Nested", new_group_name="Retained GN Copy")
    except BridgeError as error:
        assert error.context["cleanup_denied"] and error.context["binding_restored"]
        assert error.context["possible_mutation"] and not error.context["rollback_verified"]
        assert error.context["retained_group"] == "Retained GN Copy"
    else:
        raise AssertionError("Injected copy failure was not reported")
    finally:
        groups._gate = original_gate
    assert root.nodes["Nested"].node_tree == isolated
    retained = bpy.data.node_groups["Retained GN Copy"]
    assert retained.users == 0
    grants[Permission.DELETE_OBJECTS.value] = True
    removed = call("group_remove", group_name=retained.name, confirm_unused=True)
    assert removed["forced_unlink"] is False
    assert bounds(protected) == protected_bounds
    assert len(base.vertices) == 0 and base.users == 2
    assert bpy.context.mode == "OBJECT" and list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    print("BLENDER_GEOMETRY_NODE_GROUPS_OK " + json.dumps({
        "blender": bpy.app.version_string, "nested_group_and_modifier_constants_verified": True,
        "evaluated_vertices": 6, "evaluated_faces": 2,
        "target_bounds": bounds(target), "protected_bounds": protected_bounds,
        "instance_isolation_and_socket_identifiers_verified": True,
        "permissions_failure_and_retained_cleanup_verified": True,
        "selection_mode_and_shared_base_preserved": True,
        "project_saved": False, "native_undo_verified": False,
        "visual_quality_verified": False,
    }))


try:
    main()
finally:
    blender_codex_bridge.unregister()
