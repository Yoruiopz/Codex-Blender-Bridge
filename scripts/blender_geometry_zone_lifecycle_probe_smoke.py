"""Disposable native API research; use the isolated, phased native runner only.

Direct RNA below is fixture research, not an exposed arbitrary-Python workflow.
All file creation/deletion is explicitly confined to the runner-owned bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import bpy


def socket(node, direction, identifier):
    return next(item for item in getattr(node, direction) if item.identifier == identifier)


def snapshot(tree):
    return {"nodes": [{"name": node.name, "type": node.bl_idname,
        "inputs": [{"name": item.name, "id": item.identifier, "type": item.type,
                    "value": list(item.default_value) if hasattr(item, "default_value") and item.type in {"VECTOR", "RGBA"} else getattr(item, "default_value", None)} for item in node.inputs],
        "outputs": [{"name": item.name, "id": item.identifier, "type": item.type} for item in node.outputs]} for node in tree.nodes],
        "links": [[link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier] for link in tree.links]}


def zone_probe(kind):
    tree = bpy.data.node_groups.new("Probe " + kind, "GeometryNodeTree")
    output = tree.nodes.new("GeometryNode" + kind + "Output")
    source = tree.nodes.new("GeometryNode" + kind + "Input")
    assert source.pair_with_output(output)
    items = output.repeat_items if kind == "Repeat" else output.state_items
    item = items.new("FLOAT", "Numeric")
    identifier = next(value.identifier for value in output.inputs if value.name == item.name)
    socket(source, "inputs", identifier).default_value = 2.25
    socket(output, "inputs", identifier).default_value = 3.75
    math = tree.nodes.new("ShaderNodeMath")
    tree.links.new(math.outputs[0], socket(output, "inputs", identifier))
    before = snapshot(tree)
    result = {"before": before, "identifier": identifier, "item_public_identifier": hasattr(item, "identifier"), "conversions": []}
    for target in ("INT", "FLOAT", "VECTOR", "RGBA", "BOOLEAN", "FLOAT"):
        item.socket_type = target
        result["conversions"].append({"type": target, "snapshot": snapshot(tree),
            "paired_identifier_preserved": all(any(value.identifier == identifier for value in getattr(node, direction))
                 for node, direction in ((source, "inputs"), (source, "outputs"), (output, "inputs"), (output, "outputs")))})
    assert all(entry["paired_identifier_preserved"] for entry in result["conversions"])
    return result


def interface_probe():
    child = bpy.data.node_groups.new("Probe Interface Child", "GeometryNodeTree")
    value = child.interface.new_socket(name="Value", in_out="INPUT", socket_type="NodeSocketFloat")
    other = child.interface.new_socket(name="Other", in_out="INPUT", socket_type="NodeSocketFloat")
    child.nodes.new("NodeGroupInput")
    parent = bpy.data.node_groups.new("Probe Interface Parent", "GeometryNodeTree")
    node = parent.nodes.new("GeometryNodeGroup")
    node.node_tree = child
    socket(node, "inputs", value.identifier).default_value = 7.25
    identifier = value.identifier
    before = snapshot(parent)
    value.name = "Renamed Value"
    # Native move accepts an insertion boundary, not the final forward index.
    child.interface.move(value, 2)
    assert [item.identifier for item in child.interface.items_tree] == [other.identifier, identifier]
    value.default_value = 4.5
    after = snapshot(parent)
    assert value.identifier == identifier
    assert socket(node, "inputs", identifier).default_value == 7.25
    assert other.identifier != identifier
    value.socket_type = "NodeSocketInt"
    converted = snapshot(parent)
    assert value.identifier == identifier
    return {"identifier": identifier, "before": before, "rename_move_default": after, "type_conversion": converted,
            "existing_instance_value_preserved_for_rename_move_default": True}


def evaluate(obj, frames):
    result = []
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            assert len(mesh.vertices) == 1
            result.append([round(float(value), 6) for value in mesh.vertices[0].co])
        finally:
            evaluated.to_mesh_clear()
    return result


def new_simulation():
    mesh = bpy.data.meshes.new("Probe Bake Mesh")
    mesh.from_pydata([(0, 0, 0)], [], [])
    obj = bpy.data.objects.new("Probe Bake Object", mesh)
    bpy.context.scene.collection.objects.link(obj)
    tree = bpy.data.node_groups.new("Probe Bake Graph", "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input, group_output = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    source, output = tree.nodes.new("GeometryNodeSimulationInput"), tree.nodes.new("GeometryNodeSimulationOutput")
    assert source.pair_with_output(output)
    transform = tree.nodes.new("GeometryNodeTransform")
    transform.name = "Increment"
    transform.inputs["Translation"].default_value = (1., 0., 0.)
    for first, last in ((group_input.outputs["Geometry"], source.inputs["Geometry"]),
                        (source.outputs["Geometry"], transform.inputs["Geometry"]),
                        (transform.outputs["Geometry"], output.inputs["Geometry"]),
                        (output.outputs["Geometry"], group_output.inputs["Geometry"])):
        tree.links.new(first, last)
    modifier = obj.modifiers.new("Probe Bake", "NODES")
    modifier.node_group = tree
    obj.use_simulation_cache = True
    bpy.context.view_layer.objects.active = obj
    bpy.context.view_layer.update()
    evaluate(obj, [1])
    assert len(modifier.bakes) == 1
    bake = modifier.bakes[0]
    bake.use_custom_simulation_frame_range = True
    bake.frame_start, bake.frame_end = 1, 3
    modifier.bake_target = bake.bake_target = "PACKED"
    assert not modifier.bake_directory and not bake.directory
    return obj, modifier, bake, transform


def modifier_property_probe():
    mesh = bpy.data.meshes.new("Probe Modifier Properties Mesh")
    obj = bpy.data.objects.new("Probe Modifier Properties", mesh)
    bpy.context.scene.collection.objects.link(obj)
    tree = bpy.data.node_groups.new("Probe Modifier Properties Graph", "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    modifier = obj.modifiers.new("Properties", "NODES")
    modifier.node_group = tree

    def keys_or_error():
        try:
            return {"keys": list(modifier.keys())}
        except TypeError as error:
            return {"error_type": type(error).__name__, "error_message": str(error)}

    empty = keys_or_error()
    try:
        assert modifier.get("fixture_missing", None) is None and "fixture_missing" not in modifier
        empty_lookup = {"missing_value_absent": True}
    except TypeError as error:
        empty_lookup = {"error_type": type(error).__name__, "error_message": str(error)}
    # Explicit fixture allocation proves there were no hidden pre-existing values.
    try:
        modifier.id_properties_ensure()
        ensured = keys_or_error()
        assert ensured == {"keys": []}
    except TypeError as error:
        ensured = {"error_type": type(error).__name__, "error_message": str(error)}
    constant = tree.interface.new_socket(name="Value", in_out="INPUT", socket_type="NodeSocketFloat")
    properties = getattr(modifier, "properties", None)
    if properties is not None:
        print("PROBE_MODIFIER_PROPERTIES_RNA " + json.dumps({"modifier_rna": list(modifier.bl_rna.properties.keys()),
              "properties_rna": list(properties.bl_rna.properties.keys())}), flush=True)
        inputs = properties.inputs
        print("PROBE_MODIFIER_INPUTS_RNA " + json.dumps({"inputs_rna": list(inputs.bl_rna.properties.keys())}), flush=True)
        field = getattr(inputs, constant.identifier)
        print("PROBE_MODIFIER_INPUT_RNA " + json.dumps({"input_rna": list(field.bl_rna.properties.keys())}), flush=True)
        field.value = 7.5
        constant_values = {constant.identifier: field.value}
        assert constant_values[constant.identifier] == 7.5
        print("PROBE_MODIFIER_INPUT_TYPES " + json.dumps({"type": field.type,
              "options": [item.identifier for item in field.bl_rna.properties["type"].enum_items]}), flush=True)
        field.type = "ATTRIBUTE"
        field.attribute_name = "probe_attribute"
        attribute_values = {constant.identifier: field.value, constant.identifier + "_use_attribute": field.type == "ATTRIBUTE",
                            constant.identifier + "_attribute_name": field.attribute_name}
    else:
        modifier[constant.identifier] = 7.5
        constant_values = {key: modifier[key] for key in modifier.keys()}  # noqa: SIM118 - bpy_struct iteration is not IDProp iteration.
        assert constant_values[constant.identifier] == 7.5
        modifier[constant.identifier + "_use_attribute"] = True
        modifier[constant.identifier + "_attribute_name"] = "probe_attribute"
        attribute_values = {key: modifier[key] for key in modifier.keys()}  # noqa: SIM118 - bpy_struct iteration is not IDProp iteration.
    assert attribute_values[constant.identifier + "_use_attribute"]
    fields = {}
    if properties is not None:
        geometry = next(item for item in tree.interface.items_tree if item.in_out == "INPUT" and item.socket_type == "NodeSocketGeometry")
        geometry_field = getattr(modifier.properties.inputs, geometry.identifier)
        fields["geometry_input"] = list(geometry_field.bl_rna.properties.keys())
        fields["geometry_input_mode"] = {"type": geometry_field.type,
            "options": [item.identifier for item in geometry_field.bl_rna.properties["type"].enum_items]}
        for kind in ("NodeSocketInt", "NodeSocketBool", "NodeSocketVector", "NodeSocketColor", "NodeSocketString"):
            added = tree.interface.new_socket(name=kind, in_out="INPUT", socket_type=kind)
            fields[kind] = list(getattr(modifier.properties.inputs, added.identifier).bl_rna.properties.keys())
        added = tree.interface.new_socket(name="Numeric Output", in_out="OUTPUT", socket_type="NodeSocketFloat")
        fields["numeric_output"] = list(getattr(modifier.properties.outputs, added.identifier).bl_rna.properties.keys())
    return {"empty_geometry_only": empty, "empty_lookup": empty_lookup, "empty_after_explicit_ensure": ensured,
            "constants": constant_values, "attributes": attribute_values,
            "native_rna_type": modifier.bl_rna.identifier, "typed_fields": fields}


def emit(phase, evidence):
    print("BLENDER_GEOMETRY_ZONE_LIFECYCLE_PROBE_" + phase.upper() + "_OK " + json.dumps({
        **evidence, "phase": phase, "process_id": os.getpid(),
        "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "blender_version": bpy.app.version_string,
        "native_api_research_only": True, "release_readiness": "NOT_ASSESSED"}), flush=True)


def writer(bundle):
    # Explicit native-test consent; paths are never accepted from a bridge caller.
    consent = {"ACCESS_EXTERNAL_FILES": True, "SAVE_PROJECT": True, "DELETE_OBJECTS": True}
    assert all(consent.values())
    zones = [zone_probe(kind) for kind in ("Repeat", "Simulation")]
    interface = interface_probe()
    modifier_properties = modifier_property_probe()
    obj, modifier, bake, transform = new_simulation()
    kwargs = {"session_uid": obj.session_uid, "modifier_name": modifier.name, "bake_id": bake.bake_id}
    started = time.monotonic()
    assert bpy.ops.object.geometry_node_bake_single("EXEC_DEFAULT", **kwargs) == {"FINISHED"}
    blocking_ms = round((time.monotonic() - started) * 1000, 3)
    baked = evaluate(obj, [1, 2, 3])
    transform.inputs["Translation"].default_value = (10., 0., 0.)
    assert evaluate(obj, [3, 1, 2]) == [baked[2], baked[0], baked[1]]
    assert bpy.ops.object.geometry_node_bake_delete_single("EXEC_DEFAULT", **kwargs) == {"FINISHED"}
    freed = evaluate(obj, [1, 2, 3])
    assert freed != baked
    assert bpy.ops.object.geometry_node_bake_single("EXEC_DEFAULT", **kwargs) == {"FINISHED"}
    # Packed FREE can still delete a stored disk path. Prove this only on owned sentinels.
    sentinel = bundle / "owned-delete-sentinel"
    for folder in ("meta", "blobs"):
        directory = sentinel / folder
        directory.mkdir(parents=True)
        (directory / "owned-sentinel.txt").write_text("native test owns this file", encoding="utf-8")
    bake.use_custom_path = True
    bake.directory = str(sentinel)
    assert bake.bake_target == "PACKED"
    assert bpy.ops.object.geometry_node_bake_delete_single("EXEC_DEFAULT", **kwargs) == {"FINISHED"}
    assert not (sentinel / "meta").exists() and not (sentinel / "blobs").exists()
    bake.use_custom_path, bake.directory = False, ""
    transform.inputs["Translation"].default_value = (2., 0., 0.)
    assert bpy.ops.object.geometry_node_bake_single("EXEC_DEFAULT", **kwargs) == {"FINISHED"}
    expected = evaluate(obj, [1, 2, 3])
    project = bundle / "packed-gn-probe.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(project)) == {"FINISHED"}
    manifest = {"project": project.name, "sha256": hashlib.sha256(project.read_bytes()).hexdigest(), "expected": expected,
                "object": obj.name, "modifier": modifier.name, "bake_id": bake.bake_id, "graph": modifier.node_group.name,
                "zones": zones, "interface": interface, "native_blocking_ms": blocking_ms,
                "modifier_property_probe": modifier_properties,
                "packed_free_deleted_owned_stored_path_sentinels": True,
                "bake_public_properties": sorted(bake.bl_rna.properties.keys())}
    (bundle / "geometry-zone-probe.json").write_text(json.dumps(manifest), encoding="utf-8")
    emit("writer", manifest)


def reader(bundle):
    manifest = json.loads((bundle / "geometry-zone-probe.json").read_text(encoding="utf-8"))
    project = bundle / manifest["project"]
    assert hashlib.sha256(project.read_bytes()).hexdigest() == manifest["sha256"]
    assert bpy.ops.wm.open_mainfile(filepath=str(project)) == {"FINISHED"}
    obj = bpy.data.objects[manifest["object"]]
    modifier = obj.modifiers[manifest["modifier"]]
    assert modifier.bakes[0].bake_id == manifest["bake_id"]
    bpy.data.node_groups[manifest["graph"]].nodes["Increment"].inputs["Translation"].default_value = (100., 0., 0.)
    assert evaluate(obj, [3, 1, 2]) == [manifest["expected"][index] for index in (2, 0, 1)]
    assert hashlib.sha256(project.read_bytes()).hexdigest() == manifest["sha256"]
    emit("reader", {"fresh_process_packed_playback_verified": True, "expected": manifest["expected"], "project_unchanged": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bundle = args.bridge_bundle.resolve(strict=True)
    (writer if args.bridge_phase == "writer" else reader)(bundle)
