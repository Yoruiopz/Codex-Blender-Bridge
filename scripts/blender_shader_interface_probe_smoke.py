"""Native shader interface identifiers, consumers, defaults and animation hazards.

This is a disposable RNA research fixture, not a public modifying tool. Native
behaviour is measured before any typed interface-edit contract is introduced.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import bpy


def value(item):
    if item is None or isinstance(item, (bool, int, float, str)):
        return item
    return [value(part) for part in item]


def interface(tree, identifier):
    matches = [item for item in tree.interface.items_tree if getattr(item, "identifier", None) == identifier]
    assert len(matches) == 1
    return matches[0]


def socket(sockets, identifier):
    matches = [item for item in sockets if item.identifier == identifier]
    assert len(matches) == 1
    return matches[0]


def channels(tree):
    animation = tree.animation_data
    if animation is None or animation.action is None:
        return []
    action, slot = animation.action, animation.action_slot
    result = []
    for layer in action.layers:
        for strip in layer.strips:
            bag = strip.channelbag(slot)
            if bag is None:
                continue
            for curve in bag.fcurves:
                result.append({"path": curve.data_path, "index": curve.array_index,
                    "keys": [[float(point.co.x), float(point.co.y), point.interpolation] for point in curve.keyframe_points]})
    return sorted(result, key=lambda item: (item["path"], item["index"]))


def tree_reference(tree):
    if not tree.is_embedded_data:
        return {"kind": "GROUP", "name": tree.name}
    for kind, owners in (("Material", bpy.data.materials), ("World", bpy.data.worlds), ("Light", bpy.data.lights)):
        matches = [owner for owner in owners if getattr(owner, "node_tree", None) == tree]
        if matches:
            assert len(matches) == 1
            return {"kind": kind, "name": matches[0].name}
    raise AssertionError("Unidentified embedded node-tree owner")


def tree_key(tree):
    ref = tree_reference(tree)
    return ref["kind"]+"::"+ref["name"]


def graph(tree):
    def sockets(items):
        return [{"identifier": item.identifier, "name": item.name, "type": item.bl_idname,
            "default": value(item.default_value) if hasattr(item, "default_value") else None,
            "linked": bool(item.is_linked), "enabled": bool(item.enabled), "hide": bool(item.hide)}
            for item in items if item.bl_idname != "NodeSocketVirtual"]

    return {"name": tree.name, "owner": tree_reference(tree), "type": tree.bl_idname,
        "interface": [{"identifier": getattr(item, "identifier", None), "name": item.name,
            "kind": item.item_type, "in_out": getattr(item, "in_out", None),
            "socket_type": getattr(item, "socket_type", None),
            "parent": None if item.parent is None else item.parent.name,
            "default": value(item.default_value) if hasattr(item, "default_value") else None}
            for item in tree.interface.items_tree],
        "nodes": [{"name": node.name, "type": node.bl_idname,
            "group": None if getattr(node, "node_tree", None) is None else node.node_tree.name,
            "inputs": sockets(node.inputs), "outputs": sockets(node.outputs)}
            for node in sorted(tree.nodes, key=lambda item: item.name)],
        "links": sorted([link.from_node.name, link.from_socket.identifier, link.to_node.name,
            link.to_socket.identifier, bool(link.is_valid), bool(link.is_muted)] for link in tree.links),
        "animation": channels(tree)}


def snapshot(trees):
    return {tree_key(tree): graph(tree) for tree in trees}


def without_edit(state, group_name, identifier, operation):
    result = json.loads(json.dumps(state))
    for tree in result.values():
        if tree["owner"] == {"kind": "GROUP", "name": group_name}:
            for item in tree["interface"]:
                if item["identifier"] == identifier:
                    if operation == "RENAME":
                        item["name"] = None
                    elif operation == "SET_DEFAULT":
                        item["default"] = None
            if operation == "MOVE":
                tree["interface"].sort(key=lambda item: item["identifier"])
        for node in tree["nodes"]:
            is_source = tree["owner"] == {"kind": "GROUP", "name": group_name} and node["type"] in {"NodeGroupInput", "NodeGroupOutput"}
            if node["group"] != group_name and not is_source:
                continue
            for direction in ("inputs", "outputs"):
                for item in node[direction]:
                    if item["identifier"] == identifier:
                        if operation == "RENAME":
                            item["name"] = None
                        elif operation == "SET_DEFAULT" and is_source and node["type"] == "NodeGroupInput":
                            item["default"] = None
                if operation == "MOVE":
                    node[direction].sort(key=lambda item: item["identifier"])
    return result


def group(name):
    tree = bpy.data.node_groups.new(name, "ShaderNodeTree")
    source = tree.nodes.new("NodeGroupInput")
    source.name = "Group Input"
    output = tree.nodes.new("NodeGroupOutput")
    output.name = "Group Output"
    output.is_active_output = True
    return tree, source, output


def instance(tree, target, name, defaults=None):
    node = tree.nodes.new("ShaderNodeGroup")
    node.name, node.node_tree = name, target
    for identifier, setting in (defaults or {}).items():
        socket(node.inputs, identifier).default_value = setting
    return node


def material(name, target, object_name):
    owner = bpy.data.materials.new(name)
    owner.use_nodes = True
    tree = owner.node_tree
    tree.nodes.clear()
    node = instance(tree, target, "Surface")
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(node.outputs["Shader"], output.inputs["Surface"])
    obj = bpy.data.objects["Cube"].copy()
    obj.name = object_name
    bpy.context.scene.collection.objects.link(obj)
    obj.material_slots[0].link, obj.material_slots[0].material = "OBJECT", owner
    return owner


def setup():
    leaf, source, output = group("Probe Shared Leaf")
    inputs = {}
    for name, kind, setting in (("Roughness", "NodeSocketFloat", .25),
        ("Tint", "NodeSocketColor", (.2, .35, .6, 1.)),
        ("Convertible", "NodeSocketFloat", .4)):
        item = leaf.interface.new_socket(name=name, in_out="INPUT", socket_type=kind)
        item.default_value = setting
        inputs[name] = item.identifier
    for name, kind in (("Scalar", "NodeSocketFloat"), ("Color", "NodeSocketColor"), ("Shader", "NodeSocketShader")):
        leaf.interface.new_socket(name=name, in_out="OUTPUT", socket_type=kind)
    shader = leaf.nodes.new("ShaderNodeBsdfPrincipled")
    leaf.links.new(source.outputs["Roughness"], shader.inputs["Roughness"])
    leaf.links.new(source.outputs["Tint"], shader.inputs["Base Color"])
    leaf.links.new(source.outputs["Roughness"], output.inputs["Scalar"])
    leaf.links.new(source.outputs["Tint"], output.inputs["Color"])
    leaf.links.new(shader.outputs["BSDF"], output.inputs["Shader"])
    outer, _source, outer_output = group("Probe Shared Outer")
    for name, kind in (("Scalar", "NodeSocketFloat"), ("Color", "NodeSocketColor"), ("Shader", "NodeSocketShader")):
        outer.interface.new_socket(name=name, in_out="OUTPUT", socket_type=kind)
    left = instance(outer, leaf, "Left", {inputs["Roughness"]: .2, inputs["Convertible"]: .91})
    right = instance(outer, leaf, "Right", {inputs["Roughness"]: .8, inputs["Convertible"]: .37})
    driver = outer.nodes.new("ShaderNodeValue")
    driver.name, driver.outputs[0].default_value = "Linked Scalar", .6
    outer.links.new(driver.outputs[0], socket(left.inputs, inputs["Roughness"]))
    mix = outer.nodes.new("ShaderNodeMixShader")
    mix.inputs[0].default_value = .5
    outer.links.new(left.outputs["Shader"], mix.inputs[1])
    outer.links.new(right.outputs["Shader"], mix.inputs[2])
    outer.links.new(mix.outputs[0], outer_output.inputs["Shader"])
    outer.links.new(left.outputs["Scalar"], outer_output.inputs["Scalar"])
    outer.links.new(right.outputs["Color"], outer_output.inputs["Color"])
    materials = [material("Probe Material A", outer, "Probe Consumer A"), material("Probe Material B", outer, "Probe Consumer B")]
    world = bpy.data.worlds.new("Probe World")
    world.use_nodes = True
    world.node_tree.nodes.clear()
    world_instance = instance(world.node_tree, outer, "World Group")
    background = world.node_tree.nodes.new("ShaderNodeBackground")
    world_output = world.node_tree.nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(world_instance.outputs["Color"], background.inputs["Color"])
    world.node_tree.links.new(background.outputs[0], world_output.inputs["Surface"])
    bpy.context.scene.world = world
    light = bpy.data.objects["Light"].data
    light.use_nodes = True
    light.node_tree.nodes.clear()
    light_instance = instance(light.node_tree, leaf, "Light Group", {inputs["Roughness"]: .55, inputs["Convertible"]: .66})
    emission = light.node_tree.nodes.new("ShaderNodeEmission")
    light_output = light.node_tree.nodes.new("ShaderNodeOutputLight")
    light.node_tree.links.new(light_instance.outputs["Color"], emission.inputs["Color"])
    light.node_tree.links.new(emission.outputs[0], light_output.inputs["Surface"])
    # A disjoint protected definition/material is a control for broad late edits.
    protected, _protected_source, protected_output = group("Probe Protected Unrelated")
    protected.interface.new_socket(name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    protected_shader = protected.nodes.new("ShaderNodeBsdfDiffuse")
    protected_shader.inputs["Color"].default_value = (.8, .1, .02, 1.)
    protected.links.new(protected_shader.outputs[0], protected_output.inputs["Shader"])
    protected_material = material("Probe Protected Material", protected, "Probe Protected Object")
    trees = [leaf, outer, protected, *(owner.node_tree for owner in materials), world.node_tree,
        light.node_tree, protected_material.node_tree]
    return leaf, outer, inputs, trees


def defaults(trees, group_name, identifier):
    return {tree_key(tree)+"/"+node.name: value(socket(node.inputs, identifier).default_value)
        for tree in trees for node in tree.nodes if getattr(node, "node_tree", None) is not None and node.node_tree.name == group_name}


def move(tree, identifier, peer_index):
    item = interface(tree, identifier)
    peers = [value for value in tree.interface.items_tree if value.item_type == "SOCKET" and value.in_out == item.in_out]
    desired = [value.identifier for value in peers]
    desired.remove(identifier)
    desired.insert(peer_index, identifier)
    items = list(tree.interface.items_tree)
    old_index, target_index = items.index(item), items.index(peers[peer_index])
    tree.interface.move(item, target_index+int(old_index < target_index))
    actual = [value.identifier for value in tree.interface.items_tree if value.item_type == "SOCKET" and value.in_out == item.in_out]
    assert actual == desired, (actual, desired)


def animation_probe():
    scene = bpy.context.scene
    frame, subframe = scene.frame_current, scene.frame_subframe
    leaf, source, output = group("Probe Animated Leaf")
    first_id = leaf.interface.new_socket(name="First", in_out="INPUT", socket_type="NodeSocketFloat").identifier
    second_id = leaf.interface.new_socket(name="Second", in_out="INPUT", socket_type="NodeSocketFloat").identifier
    leaf.interface.new_socket(name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    shader = leaf.nodes.new("ShaderNodeBsdfPrincipled")
    leaf.links.new(source.outputs["First"], shader.inputs["Roughness"])
    leaf.links.new(shader.outputs[0], output.inputs["Shader"])
    owner = material("Probe Animated Material", leaf, "Probe Animated Consumer")
    node = owner.node_tree.nodes["Surface"]
    socket(node.inputs, second_id).default_value = .9
    target = socket(node.inputs, first_id)
    target.default_value = .2
    assert target.keyframe_insert(data_path="default_value", frame=1)
    target.default_value = .8
    assert target.keyframe_insert(data_path="default_value", frame=2)
    paths = channels(owner.node_tree)

    def samples():
        result = {}
        for current in (1, 2):
            scene.frame_set(current)
            bpy.context.view_layer.update()
            result[str(current)] = {identifier: value(socket(node.inputs, identifier).default_value) for identifier in (first_id, second_id)}
        return result

    before = samples()
    move(leaf, first_id, 1)
    after = samples()
    paths_after = channels(owner.node_tree)
    index_alias = any(before[str(current)][second_id] != after[str(current)][second_id] for current in (1, 2))
    move(leaf, first_id, 0)
    socket(node.inputs, second_id).default_value = .9
    recovered = samples()
    assert recovered == before
    scene.frame_set(frame, subframe=subframe)
    return {"first_identifier": first_id, "second_identifier": second_id, "fcurves_before": paths,
        "fcurves_after": paths_after, "same_path_text": paths == paths_after,
        "samples_before": before, "samples_after": after, "animation_index_alias_observed": index_alias,
        "explicit_original_order_and_peer_default_recovery_verified": True}, [leaf, owner.node_tree]


def writer(bundle):
    assert bpy.app.background and not bpy.data.filepath
    leaf, outer, identifiers, trees = setup()
    roughness = identifiers["Roughness"]
    initial = snapshot(trees)
    initial_ids = [item.identifier for item in leaf.interface.items_tree]
    identities = {tree_key(tree): tree.as_pointer() for tree in trees}
    instances_before = defaults(trees, leaf.name, roughness)
    interface(leaf, roughness).name = "Surface Roughness"
    renamed = snapshot(trees)
    assert without_edit(initial, leaf.name, roughness, "RENAME") == without_edit(renamed, leaf.name, roughness, "RENAME")
    move(leaf, roughness, 2)
    reordered = snapshot(trees)
    assert without_edit(renamed, leaf.name, roughness, "MOVE") == without_edit(reordered, leaf.name, roughness, "MOVE")
    interface(leaf, roughness).default_value = .65
    changed_default = snapshot(trees)
    assert without_edit(reordered, leaf.name, roughness, "SET_DEFAULT") == without_edit(changed_default, leaf.name, roughness, "SET_DEFAULT")
    assert defaults(trees, leaf.name, roughness) == instances_before
    assert set(initial_ids) == {item.identifier for item in leaf.interface.items_tree}
    assert all(tree.as_pointer() == identities[tree_key(tree)] for tree in trees)
    fresh = instance(outer, leaf, "Fresh Default Consumer")
    assert abs(socket(fresh.inputs, roughness).default_value-.65) < 1e-6
    conversion_id = identifiers["Convertible"]
    convert_before = defaults(trees, leaf.name, conversion_id)
    interface_default_before = value(interface(leaf, conversion_id).default_value)
    convert_links = snapshot(trees)
    interface(leaf, conversion_id).socket_type = "NodeSocketVector"
    convert_after = defaults(trees, leaf.name, conversion_id)
    interface_default_vector = value(interface(leaf, conversion_id).default_value)
    assert interface(leaf, conversion_id).identifier == conversion_id
    interface(leaf, conversion_id).socket_type = "NodeSocketFloat"
    convert_reverted = defaults(trees, leaf.name, conversion_id)
    interface_default_reverted = value(interface(leaf, conversion_id).default_value)
    interface(leaf, conversion_id).default_value = interface_default_before
    # The probe restores explicit original native defaults; changing socket type
    # back alone must never be described as identity/pixel/animation recovery.
    for tree in trees:
        for node in tree.nodes:
            if getattr(node, "node_tree", None) == leaf:
                socket(node.inputs, conversion_id).default_value = convert_before[tree_key(tree)+"/"+node.name]
    assert snapshot(trees) == convert_links
    conversion = {"interface_default_before": interface_default_before,
        "interface_default_vector": interface_default_vector, "interface_default_type_only_revert": interface_default_reverted,
        "explicit_interface_and_all_instance_default_restoration_verified": True,
        "identifier_stable": interface(leaf, conversion_id).identifier == conversion_id,
        "before": convert_before, "after_vector_conversion": convert_after, "after_type_only_revert": convert_reverted,
        "type_only_revert_restored_instance_defaults": convert_before == convert_reverted,
        "links_unchanged": all(graph(tree)["links"] == convert_links[tree_key(tree)]["links"] for tree in trees),
        "typed_conversion_supported": False}
    animation, animated_trees = animation_probe()
    trees.extend(animated_trees)
    preserved = snapshot(trees)
    consumer_ids = sorted((owner.bl_rna.identifier, owner.name) for owner in bpy.data.user_map(subset={leaf}).get(leaf, ()))
    pending, seen, root_owners = [leaf], set(), set()
    while pending:
        current = pending.pop()
        if current.as_pointer() in seen:
            continue
        seen.add(current.as_pointer())
        assert len(seen) <= 32
        for owner in bpy.data.user_map(subset={current}).get(current, ()):
            if getattr(owner, "bl_idname", None) == "ShaderNodeTree":
                pending.append(owner)
            else:
                root_owners.add((owner.bl_rna.identifier, owner.name))
    assert {name for _kind, name in root_owners} == {"Probe Material A", "Probe Material B", "Probe World", "Light"}
    expected = {"graphs": preserved, "tree_references": [tree_reference(tree) for tree in trees], "leaf": leaf.name,
        "roughness_identifier": roughness, "initial_ids": initial_ids,
        "conversion": conversion, "animation": animation}
    bpy.ops.wm.save_as_mainfile(filepath=str(bundle/"shader-interface.blend"), check_existing=False)
    (bundle/"expected.json").write_text(json.dumps(expected), encoding="utf-8")
    return {"phase": "writer", "blender_version": bpy.app.version_string, "native_only_probe": True,
        "rename_reorder_default_all_nested_consumer_proof": True, "all_original_identifiers_retained": True,
        "existing_instance_defaults_preserved_new_instance_gets_new_default": True,
        "root_consumer_kinds": sorted({kind for kind, _name in root_owners}),
        "transitive_root_owners": sorted(root_owners),
        "direct_consumers": consumer_ids, "conversion": conversion, "animation": animation,
        "typed_interface_edit_tool_implemented": False}


def reader(bundle):
    expected = json.loads((bundle/"expected.json").read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(bundle/"shader-interface.blend"), load_ui=False)
    trees = []
    for ref in expected["tree_references"]:
        if ref["kind"] == "GROUP":
            trees.append(bpy.data.node_groups[ref["name"]])
        else:
            owners = {"Material": bpy.data.materials, "World": bpy.data.worlds, "Light": bpy.data.lights}[ref["kind"]]
            trees.append(owners[ref["name"]].node_tree)
    assert snapshot(trees) == expected["graphs"]
    leaf = bpy.data.node_groups[expected["leaf"]]
    assert set(expected["initial_ids"]) == {item.identifier for item in leaf.interface.items_tree}
    return {"phase": "reader", "blender_version": bpy.app.version_string, "native_only_probe": True,
        "fresh_process_interface_links_defaults_animation_and_all_consumers_verified": True,
        "original_interface_identifier_set_retained": True, "project_saved_by_reader": False,
        "typed_interface_edit_tool_implemented": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    result = (writer if args.bridge_phase == "writer" else reader)(args.bridge_bundle.resolve(strict=True))
    result.update(process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid())
    print("BLENDER_SHADER_INTERFACE_PROBE_"+args.bridge_phase.upper()+"_OK "+json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
