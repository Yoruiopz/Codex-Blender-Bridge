"""Isolated Geometry Nodes integration smoke; run with --background --factory-startup.

Exercises real Blender RNA and independently measures evaluated mesh topology.
Never saves or modifies the user's running Blender process.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy  # type: ignore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "addon"))

from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.tools import geometry_nodes as gn  # noqa: E402


def main() -> None:
    group_name = "Bridge GN Smoke"
    data = bpy.data.meshes.new("Bridge GN Smoke Mesh")
    obj = bpy.data.objects.new("Bridge GN Smoke Object", data)
    bpy.context.scene.collection.objects.link(obj)
    selection_before = [item.name for item in bpy.context.selected_objects]
    active_before = bpy.context.view_layer.objects.active
    group = None

    def call(handler, **params):
        return handler(None, {"group_name": group_name, **params})

    try:
        created = call(gn.create_graph)
        assert created["node_count"] == 2 and created["link_count"] == 1
        group = bpy.data.node_groups[group_name]
        call(gn.add_interface, name="Grid Width", default_value=4.0)
        call(gn.add_node, node_type="GeometryNodeMeshGrid", name="Grid")
        call(gn.add_node, node_type="GeometryNodeTransform", name="Transform", location=[100, 100])
        call(gn.add_node, node_type="ShaderNodeMath", name="Math", settings={"operation": "ADD"})
        call(
            gn.set_node_properties,
            node_name="Math",
            settings={"operation": "MULTIPLY", "label": "Checked RNA"},
        )
        assert group.nodes["Math"].operation == "MULTIPLY"
        call(gn.set_node_input, node_name="Math", socket_name="Value", socket_index=0, value=2.0)
        call(gn.set_node_input, node_name="Grid", socket_name="Vertices X", value=3)
        call(gn.set_node_input, node_name="Grid", socket_name="Vertices Y", value=2)
        call(gn.set_node_input, node_name="Grid", socket_name="Size Y", value=2.0)
        call(gn.set_node_input, node_name="Transform", socket_name="Translation", value=[1, 0, 0])
        call(gn.set_node_input, node_name="Transform", socket_name="Scale", value=[1, 2, 1])
        call(
            gn.link_nodes,
            from_node="Group Input",
            from_socket="Grid Width",
            to_node="Grid",
            to_socket="Size X",
        )
        call(
            gn.link_nodes,
            from_node="Grid",
            from_socket="Mesh",
            to_node="Transform",
            to_socket="Geometry",
        )
        try:
            call(
                gn.link_nodes,
                from_node="Transform",
                from_socket="Geometry",
                to_node="Group Output",
                to_socket="Geometry",
            )
        except BridgeError as exc:
            assert exc.code == "INVALID_ARGUMENT"
        else:
            raise AssertionError("Occupied graph output accepted implicit replacement")
        call(
            gn.link_nodes,
            from_node="Transform",
            from_socket="Geometry",
            to_node="Group Output",
            to_socket="Geometry",
            replace_existing=True,
        )
        attached = call(gn.attach_graph, object_name=obj.name, modifier_name="Procedural Grid")
        assert attached["modifier"]["node_group"] == group_name
        assert attached["affected_objects"] == [obj.name]
        inspected = call(gn.inspect_graph, max_nodes=2, max_interface_items=1)
        assert inspected["truncated"] and len(inspected["nodes"]) == 2
        assert inspected["truncated_fields"]["interface"]
        # A second object shares the group: mutations now need acknowledgement.
        other = bpy.data.objects.get("Cube")
        assert other is not None
        other.modifiers.new("Smoke Shared", "NODES").node_group = group
        try:
            call(gn.set_node_input, node_name="Grid", socket_name="Size Y", value=3)
        except BridgeError as exc:
            assert exc.code == "INVALID_ARGUMENT" and "allow_shared" in exc.message
        else:
            raise AssertionError("Shared graph edit did not require acknowledgement")
        call(
            gn.set_node_input, node_name="Grid", socket_name="Size Y", value=2.0, allow_shared=True
        )
        other.modifiers.remove(other.modifiers["Smoke Shared"])
        # Failed add/configuration leaves no orphan node.
        before_nodes = len(group.nodes)
        try:
            call(
                gn.add_node,
                node_type="ShaderNodeMath",
                name="Invalid",
                settings={"operation": "NOT_AN_ENUM"},
            )
        except BridgeError as exc:
            assert exc.code == "INVALID_ARGUMENT"
        else:
            raise AssertionError("Invalid enum accepted")
        assert len(group.nodes) == before_nodes and group.nodes.get("Invalid") is None
        try:
            call(
                gn.link_nodes,
                from_node="Math",
                from_socket="Value",
                to_node="Math",
                to_socket="Value",
                to_socket_index=0,
            )
        except BridgeError as exc:
            assert "cycle" in exc.message
        else:
            raise AssertionError("Self-cycle accepted")
        removed = call(gn.remove_node, node_name="Math")
        assert removed["removed"] == "Math" and group.nodes.get("Math") is None
        call(
            gn.unlink_nodes,
            from_node="Grid",
            from_socket="Mesh",
            to_node="Transform",
            to_socket="Geometry",
        )
        call(
            gn.link_nodes,
            from_node="Grid",
            from_socket="Mesh",
            to_node="Transform",
            to_socket="Geometry",
        )
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            assert len(mesh.vertices) == 6, len(mesh.vertices)
            assert len(mesh.polygons) == 2, len(mesh.polygons)
            bounds = [
                [min(v.co[axis] for v in mesh.vertices), max(v.co[axis] for v in mesh.vertices)]
                for axis in range(3)
            ]
            assert bounds == [[-1.0, 3.0], [-2.0, 2.0], [0.0, 0.0]], bounds
            assert len(obj.data.vertices) == 0, "Modifier unexpectedly applied to source data"
            assert [item.name for item in bpy.context.selected_objects] == selection_before
            assert bpy.context.view_layer.objects.active == active_before
            print(
                "BLENDER_CODEX_GEOMETRY_NODES_SMOKE_OK "
                + json.dumps(
                    {
                        "blender_version": bpy.app.version_string,
                        "evaluated_vertices": len(mesh.vertices),
                        "evaluated_faces": len(mesh.polygons),
                        "bounds": bounds,
                        "source_mesh_unchanged": True,
                        "selection_preserved": True,
                        "tools_exercised": 10,
                    },
                    sort_keys=True,
                )
            )
        finally:
            evaluated.to_mesh_clear()
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(data)
        if group is not None:
            bpy.data.node_groups.remove(group)


if __name__ == "__main__":
    main()
