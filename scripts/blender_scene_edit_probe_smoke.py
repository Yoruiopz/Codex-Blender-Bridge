"""Owned native settings research; run only through run_blender_checks.py."""

from __future__ import annotations

import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import bpy


def value(raw):
    if isinstance(raw, set):
        return sorted(raw)
    if raw is None or isinstance(raw, (str, bool, int, float)):
        return raw
    return [value(item) for item in raw]


def primitive(owner):
    return {p.identifier: value(getattr(owner, p.identifier)) for p in owner.bl_rna.properties
            if not p.is_readonly and not p.is_runtime and p.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}}


def descriptors(owner):
    return {"type": owner.bl_rna.identifier,
            "runtime": [{"name": p.identifier, "type": p.type, "readonly": p.is_readonly,
                         "registered": p.is_registered, "array": p.array_length if p.type in {"BOOLEAN", "INT", "FLOAT"} else 0,
                         "fixed_type": p.fixed_type.identifier if p.type in {"POINTER", "COLLECTION"} else None}
                        for p in owner.bl_rna.properties if p.is_runtime],
            "custom": list(owner.keys()) if isinstance(owner, bpy.types.ID) else []}


def changed(before, after):
    return {name: [before.get(name, "ABSENT"), after.get(name, "ABSENT")]
            for name in sorted(set(before) | set(after)) if before.get(name, "ABSENT") != after.get(name, "ABSENT")}


def graph(world):
    tree = world.node_tree
    if tree is None:
        return None
    return {"identity": tree.as_pointer(), "nodes": [{"name": n.name, "type": n.bl_idname, "identity": n.as_pointer(),
            "properties": primitive(n), "inputs": [{"identifier": s.identifier, "type": s.bl_idname,
              "properties": primitive(s)} for s in n.inputs]} for n in tree.nodes],
            "links": [(link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) for link in tree.links]}


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))
    from blender_codex_bridge.checkpoints import CheckpointManager
    from blender_codex_bridge.tools import _scene_edit_profile as profile
    from blender_codex_bridge.tools import _scene_mutation as proof

    scene = bpy.context.scene
    cp = CheckpointManager()
    def checkpoint_roles():
        particle = scene.tool_settings.particle_edit
        properties = proof.descriptors(bpy, particle)
        object_prop = next(prop for prop in properties if prop.identifier == "object")
        assert object_prop.type == "POINTER" and object_prop.is_readonly and not object_prop.is_runtime
        # is_editable/is_hair getters call PE_get_current and can themselves
        # write these weak native roles. Never use them as a passive probe.
        scene_exposed = any(prop.identifier == "scene" for prop in properties)
        return {"scene_original": proof.token(scene.original), "scene_references": proof.references(bpy, (scene,)),
                "particle_edit_type": particle.bl_rna.identifier, "particle_object": proof.token(particle.object),
                "particle_scene_rna_exposed": scene_exposed,
                "active_object": proof.token(bpy.context.active_object),
                "world_tree_users": None if scene.world is None or scene.world.node_tree is None else scene.world.node_tree.users}
    before_profile = profile.Profile(bpy, scene, "scene.configure")()
    before_roles = checkpoint_roles()
    assert cp.before_modification("Owned Scene checkpoint role research")
    after_profile = profile.Profile(bpy, scene, "scene.configure")()
    after_roles = checkpoint_roles()
    checkpoint_delta = {"before_roles": before_roles, "after_roles": after_roles,
                        "profile_changed_keys": [name for name in before_profile if before_profile[name] != after_profile[name]],
                        "scene_primitive_changed_fields": [before[0] for before, after in zip(before_profile["scene"][1][0], after_profile["scene"][1][0], strict=True) if before != after],
                        "scene_custom_before": before_profile["scene"][1][1], "scene_custom_after": after_profile["scene"][1][1]}
    assert cp.after_modification("Owned Scene checkpoint role research")
    checkpoint_delta["finalized_roles"] = checkpoint_roles()
    factory_world = scene.world
    def tree_info(owner):
        tree = owner.node_tree
        return {"users": tree.users, "embedded": tree.is_embedded_data, "extra_user": tree.use_extra_user,
                "fake_user": tree.use_fake_user, "references": owner.user_of_id(tree),
                "direct": [(user.bl_rna.identifier, user.name, user.user_of_id(tree)) for user in bpy.data.user_map(subset={tree}).get(tree, ())]}
    factory_tree = tree_info(factory_world)
    camera = scene.camera.data
    light = bpy.data.lights.new("Owned Probe Light", "POINT")
    light.energy = 321.0
    light.color = (0.2, 0.3, 0.4)
    light_states = [{"type": light.type, "state": primitive(light)}]
    for kind in ("SPOT", "AREA", "SUN", "POINT", "SPOT"):
        light.type = kind
        light = bpy.data.lights.get(light.name)
        if kind == "SPOT":
            light.spot_size = .9
            light.spot_blend = .3
        light_states.append({"type": light.type, "state": primitive(light)})
    light_deltas = [{"before": a["type"], "after": b["type"], "changes": changed(a["state"], b["state"])}
                    for a, b in pairwise(light_states)]
    camera_states = [{"type": camera.type, "state": primitive(camera)}]
    for kind in ("ORTHO", "PANO", "PERSP"):
        camera.type = kind
        camera_states.append({"type": kind, "state": primitive(camera)})
    world = bpy.data.worlds.new("Owned Probe World")
    world_states = [{"use_nodes": world.use_nodes, "graph": graph(world)}]
    for enabled in (True, False, True):
        world.use_nodes = enabled
        world_states.append({"use_nodes": world.use_nodes, "graph": graph(world)})
    root = scene.collection
    parent = bpy.data.collections.new("Owned Probe Parent")
    child = bpy.data.collections.new("Owned Probe Child")
    root.children.link(parent)
    parent.children.link(child)
    ownership = []
    for layers in (1, 2):
        if layers == 2:
            scene.view_layers.new("Owned Probe Layer")
        users = bpy.data.user_map(subset={root, parent, child})
        ownership.append({"layers": layers, "collections": [
            {"name": col.name, "users": col.users, "scene_references": scene.user_of_id(col),
             "parents": [(p.name, p.user_of_id(col)) for p in (root, parent) if p.user_of_id(col)],
             "direct": [{"type": owner.bl_rna.identifier, "name": owner.name, "references": owner.user_of_id(col)}
                        for owner in users.get(col, ())]} for col in (root, parent, child)]})
    scene.unit_settings.scale_length = .01
    camera.lens = 43.1
    world.color = (.1, .2, .3)
    result = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
        "checkpoint_deltas": checkpoint_delta,
        "descriptors": {name: descriptors(owner) for name, owner in (("Scene", scene), ("Object", scene.camera),
          ("Camera", camera), ("CameraDOFSettings", camera.dof), ("Light", light), ("World", world),
          ("NodeTree", world.node_tree), ("Collection", parent), ("UnitSettings", scene.unit_settings))},
        "light_deltas": light_deltas, "camera_deltas": [changed(a["state"], b["state"]) for a, b in pairwise(camera_states)],
        "world_states": world_states, "collection_ownership": ownership,
        "float_roundtrip": {"scale_length": scene.unit_settings.scale_length, "lens": camera.lens, "color": list(world.color)},
        "handler_lengths": {name: len(getattr(bpy.app.handlers, name)) for name in ("depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post")},
        "math_pi": math.pi}
    result["factory_tree_before_checkpoint"] = factory_tree
    bpy.ops.ed.undo_push(message="Owned Scene Probe Checkpoint")
    result["factory_tree_after_checkpoint"] = tree_info(factory_world)
    owned_camera = bpy.data.objects.new("Owned Probe Camera", bpy.data.cameras.new("Owned Probe Camera Data"))
    scene.collection.objects.link(owned_camera)
    focus = bpy.data.objects.new("Owned Probe Focus", None)
    scene.collection.objects.link(focus)
    result["object_user_controls"] = {"camera_before": owned_camera.users, "focus_before": focus.users}
    scene.camera = owned_camera
    result["object_user_controls"].update(camera_after=owned_camera.users,
        camera_scene_references=scene.user_of_id(owned_camera))
    owned_camera.data.dof.focus_object = focus
    result["object_user_controls"].update(focus_after=focus.users,
        focus_camera_references=owned_camera.data.user_of_id(focus))
    result["light_node_tree"] = None if light.node_tree is None else {
        "tree_users": light.node_tree.users, "is_embedded_data": light.node_tree.is_embedded_data,
        "owner_references": light.user_of_id(light.node_tree),
        "nodes": [(n.bl_idname, [(s.identifier, value(s.default_value)) for s in n.inputs if hasattr(s, "default_value")]) for n in light.node_tree.nodes],
        "links": [(ln.from_node.bl_idname, ln.from_socket.identifier, ln.to_node.bl_idname, ln.to_socket.identifier) for ln in light.node_tree.links]}
    result["world_node_tree"] = {"tree_users": world.node_tree.users, "is_embedded_data": world.node_tree.is_embedded_data,
                                "owner_references": world.user_of_id(world.node_tree)}
    result["new_tree_after_checkpoint"] = tree_info(world)
    if bpy.app.version < (5, 0, 0):
        colored_world = bpy.data.worlds.new("Owned Colored Lazy World")
        colored_world.color = (.23, .37, .65)
        colored_world.use_nodes = True
        colored_bg = next(n for n in colored_world.node_tree.nodes if n.type == "BACKGROUND")
        result["colored_lazy_graph"] = {"world_color": list(colored_world.color), "background_color": list(colored_bg.inputs["Color"].default_value)}
    print("BLENDER_SCENE_EDIT_PROBE_OK " + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
