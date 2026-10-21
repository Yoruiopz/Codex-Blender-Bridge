"""Typed nested interface and paired-zone lifecycle, with independent readback."""

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
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    protected = bpy.data.objects["Cube"]
    protected_vertices = [tuple(vertex.co) for vertex in protected.data.vertices]

    def call(method, **params):
        return runtime.dispatch("geometry_nodes." + method, params)

    def deny(code, method, **params):
        try:
            call(method, **params)
        except BridgeError as error:
            assert error.code == code, error.to_dict()
            return error
        raise AssertionError("Expected " + code)

    def endpoint(node, direction, socket_name):
        return next(socket.identifier for socket in getattr(node, direction) if socket.name == socket_name)

    def bounds(obj):
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            assert len(mesh.vertices) == 4 and len(mesh.polygons) == 1
            return [[min(vertex.co[axis] for vertex in mesh.vertices), max(vertex.co[axis] for vertex in mesh.vertices)] for axis in range(3)]
        finally:
            evaluated.to_mesh_clear()

    child_name = "Lifecycle Child"
    call("create", group_name=child_name, passthrough=False)
    call("interface_add", group_name=child_name, name="Width", default_value=2.)
    call("interface_add", group_name=child_name, name="Second", default_value=3.)
    call("node_add", group_name=child_name, node_type="GeometryNodeMeshGrid", name="Grid")
    for socket_name, value in (("Vertices X", 2), ("Vertices Y", 2), ("Size Y", 2.)):
        call("node_set_input", group_name=child_name, node_name="Grid", socket_name=socket_name, value=value)
    call("link", group_name=child_name, from_node="Group Input", from_socket="Width", to_node="Grid", to_socket="Size X")
    call("link", group_name=child_name, from_node="Grid", from_socket="Mesh", to_node="Group Output", to_socket="Geometry")
    call("zone_create", group_name=child_name, zone_type="REPEAT", input_name="Repeat In", output_name="Repeat Out", iterations=2)
    call("zone_item_add", group_name=child_name, output_name="Repeat Out", socket_type="FLOAT", name="Amount")
    child = bpy.data.node_groups[child_name]
    identifier = next(item["socket_identifier"] for item in call("zone_inspect", group_name=child_name, output_name="Repeat Out")["items"] if item["name"] == "Amount")
    interface_id = next(item.identifier for item in child.interface.items_tree if item.name == "Width")
    objects = []
    for index, width in enumerate((4., 8.)):
        parent_name = "Lifecycle Parent " + str(index)
        call("create", group_name=parent_name, passthrough=False)
        call("group_bind", parent_group_name=parent_name, child_group_name=child_name, node_name="Nested")
        parent = bpy.data.node_groups[parent_name]
        call("group_set_input", group_name=parent_name, node_name="Nested", socket_identifier=interface_id, value=width)
        call("group_link", group_name=parent_name, from_node="Nested", from_socket_identifier=endpoint(parent.nodes["Nested"], "outputs", "Geometry"),
             to_node="Group Output", to_socket_identifier=endpoint(parent.nodes["Group Output"], "inputs", "Geometry"))
        data = bpy.data.meshes.new("Lifecycle Empty " + str(index))
        obj = bpy.data.objects.new("Lifecycle Object " + str(index), data)
        bpy.context.scene.collection.objects.link(obj)
        call("group_attach", group_name=parent_name, object_name=obj.name, modifier_name="Procedural")
        objects.append(obj)
    initial = [bounds(obj) for obj in objects]
    params = {"group_name": child_name, "output_name": "Repeat Out", "socket_identifier": identifier,
              "socket_type": "INT", "input_value": 3, "output_value": 5}
    deny("INVALID_ARGUMENT", "zone_item_convert", **params)
    conversions = []
    for kind, first, second in (("INT", 3, 5), ("VECTOR", [1., 2., 3.], [4., 5., 6.]),
                               ("RGBA", [0.1, 0.2, 0.3, 1.], [0.4, 0.5, 0.6, 0.]),
                               ("BOOLEAN", True, False), ("FLOAT", 2., 6.)):
        result = call("zone_item_convert", **{**params, "socket_type": kind, "input_value": first, "output_value": second, "allow_shared": True})
        assert result["paired_identifiers_preserved"]
        for node_name in ("Repeat In", "Repeat Out"):
            for direction in ("inputs", "outputs"):
                assert next(socket for socket in getattr(child.nodes[node_name], direction) if socket.name == "Amount").identifier == identifier
        conversions.append(kind)
    assert [bounds(obj) for obj in objects] == initial
    for operation, extra in (("RENAME", {"new_name": "Renamed Width"}), ("MOVE", {"to_index": 1}), ("SET_DEFAULT", {"value": 12.})):
        result = call("interface_edit", group_name=child_name, socket_identifier=interface_id, operation=operation, allow_shared=True, **extra)
        assert result["existing_consumer_values_preserved"]
        assert [bounds(obj) for obj in objects] == initial
    assert [item.name for item in child.interface.items_tree if item.item_type == "SOCKET" and item.in_out == "INPUT"] == ["Geometry", "Renamed Width", "Second"]
    # Index 1 leaves the original second INPUT position because Geometry is index 0.
    result = call("interface_edit", group_name=child_name, socket_identifier=interface_id, operation="MOVE", to_index=2, allow_shared=True)
    assert result["value"] == 2
    assert [item.name for item in child.interface.items_tree if item.item_type == "SOCKET" and item.in_out == "INPUT"] == ["Geometry", "Second", "Renamed Width"]

    grants[Permission.EDIT_MESH.value] = False
    deny("PERMISSION_DENIED", "zone_item_convert", **{**params, "allow_shared": True})
    grants[Permission.EDIT_MESH.value] = True
    before = groups._graph_guard(child)
    original_gate, calls = groups._gate, 0

    def fault(context, *required):
        nonlocal calls
        original_gate(context, *required)
        calls += 1
        if calls == 2:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Owned post-write native fixture fault")

    groups._gate = fault
    try:
        error = deny("OPERATION_FAILED", "zone_item_convert", **{**params, "allow_shared": True})
        assert error.context["rollback_verified"] and not error.context["possible_mutation"]
    finally:
        groups._gate = original_gate
    assert groups._graph_guard(child) == before

    # Make converted output observable in evaluated geometry, then refuse linked conversion.
    call("group_link", group_name=child_name, from_node="Repeat Out", from_socket_identifier=identifier,
         to_node="Grid", to_socket_identifier=endpoint(child.nodes["Grid"], "inputs", "Size Y"), allow_shared=True)
    evaluated = [bounds(obj) for obj in objects]
    assert [value[1] for value in evaluated] == [[-3., 3.], [-3., 3.]]
    deny("INVALID_ARGUMENT", "zone_item_convert", **{**params, "allow_shared": True})
    assert [tuple(vertex.co) for vertex in protected.data.vertices] == protected_vertices
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active and bpy.context.mode == "OBJECT"
    print("BLENDER_GEOMETRY_ZONE_LIFECYCLE_OK " + json.dumps({"blender": bpy.app.version_string,
        "typed_conversions": conversions, "stable_paired_identifiers_verified": True,
        "nested_interface_lifecycle_and_consumer_values_verified": True, "evaluated_bounds": evaluated,
        "permission_shared_scope_and_link_denial_verified": True, "owned_failure_compensation_verified": True,
        "protected_mesh_and_context_preserved": True, "project_saved": False, "native_undo_verified": False,
        "bake_lifecycle_exposed": False, "visual_quality_accepted": False, "release_readiness": "NOT_ASSESSED"}))


try:
    main()
finally:
    blender_codex_bridge.unregister()
