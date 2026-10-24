"""Owned driver/getter controls and rigid-cache evaluation admission failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "addon"))

from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.state import BridgeState  # noqa: E402
from blender_codex_bridge.tool_registry import ToolContext, ToolRegistry  # noqa: E402
from blender_codex_bridge.tools import rigid_body  # noqa: E402

from scripts.blender_rigid_lifecycle_probe_smoke import cache_state, context_state, make_scene  # noqa: E402

NAMESPACE = "bridge_owned_rigid_counter"
MARKER = "BLENDER_RIGID_EVALUATION_DEPENDENCIES_OK "


def handlers():
    names = ("frame_change_pre", "frame_change_post", "depsgraph_update_pre", "depsgraph_update_post")
    return {name: tuple(id(callback) for callback in getattr(bpy.app.handlers, name)) for name in names}


def descriptors(owner, names):
    records = {}
    for name in names:
        prop = owner.bl_rna.properties.get(name)
        records[name] = None if prop is None else {"type": prop.type, "is_runtime": prop.is_runtime,
            "is_registered": prop.is_registered, "is_readonly": prop.is_readonly,
            "fixed_type": getattr(getattr(prop, "fixed_type", None), "identifier", None)}
    return {"owner_rna": owner.bl_rna.identifier, "properties": records}


def main_native_families():
    records, identities = {}, {}
    for prop in bpy.data.bl_rna.properties:
        if prop.type != "COLLECTION":
            continue
        fixed = prop.fixed_type
        base = fixed
        while base is not None and base.identifier != "ID":
            base = base.base
        if base is None:
            continue
        owners = list(getattr(bpy.data, prop.identifier))
        identities[prop.identifier] = {(int(owner.as_pointer()), owner.session_uid) for owner in owners}
        records[prop.identifier] = {"fixed_type": fixed.identifier, "is_runtime": prop.is_runtime, "count": len(owners),
                                    "actual_rna": sorted({owner.bl_rna.identifier for owner in owners})}
    if "all_ids" in identities:
        concrete = set().union(*(values for family, values in identities.items() if family != "all_ids"))
        records["all_ids"]["aggregate_alias_coverage"] = {"equals_concrete_family_union": identities["all_ids"] == concrete,
            "concrete_union_count": len(concrete), "alias_count": len(identities["all_ids"]),
            "only_alias_count": len(identities["all_ids"]-concrete), "only_concrete_count": len(concrete-identities["all_ids"])}
    return records


def graph_setup(scene, body):
    material = bpy.data.materials.new("Owned Evaluation Material")
    material.use_nodes = True
    body.data.materials.append(material)
    tree = material.node_tree
    principled = next(node for node in tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    leaf = bpy.data.node_groups.new("Owned Nested Evaluation Leaf", "ShaderNodeTree")
    leaf.interface.new_socket(name="Factor", in_out="OUTPUT", socket_type="NodeSocketFloat")
    value = leaf.nodes.new("ShaderNodeValue")
    value.outputs[0].default_value = .375
    output = leaf.nodes.new("NodeGroupOutput")
    leaf.links.new(value.outputs[0], output.inputs["Factor"])
    middle = bpy.data.node_groups.new("Owned Nested Evaluation Parent", "ShaderNodeTree")
    middle.interface.new_socket(name="Factor", in_out="OUTPUT", socket_type="NodeSocketFloat")
    middle_leaf = middle.nodes.new("ShaderNodeGroup")
    middle_leaf.node_tree = leaf
    middle_output = middle.nodes.new("NodeGroupOutput")
    middle.links.new(middle_leaf.outputs["Factor"], middle_output.inputs["Factor"])
    nested = tree.nodes.new("ShaderNodeGroup")
    nested.node_tree = middle
    tree.links.new(nested.outputs["Factor"], principled.inputs["Roughness"])
    world = bpy.data.worlds.new("Owned Evaluation World")
    world.use_nodes = True
    scene.world = world
    background = next(node for node in world.node_tree.nodes if node.bl_idname == "ShaderNodeBackground")
    if hasattr(scene, "compositing_node_group"):
        compositor = bpy.data.node_groups.new("Owned Evaluation Compositor", "CompositorNodeTree")
        compositor.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        comp_output = compositor.nodes.new("NodeGroupOutput")
        scene.compositing_node_group = compositor
    else:
        scene.use_nodes = True
        compositor = scene.node_tree
        compositor.nodes.clear()
        comp_output = compositor.nodes.new("CompositorNodeComposite")
    comp_value = compositor.nodes.new("ShaderNodeValue" if hasattr(scene, "compositing_node_group") else "CompositorNodeValue")
    compositor.links.new(comp_value.outputs[0], comp_output.inputs["Image"])
    return [
        ("material_id", material, material, "diffuse_color", 0),
        ("nested_material_tree", leaf, value.outputs[0], "default_value", None),
        ("world_id", world, world, "color", 0),
        ("world_tree", world.node_tree, background.inputs["Strength"], "default_value", None),
        ("compositor_tree", compositor, comp_value.outputs[0], "default_value", None),
    ]


def main():
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True
    scene, bodies, sentinel = make_scene("Owned Evaluation Scope", (0., 0., -9.81))
    main_families = main_native_families()
    print("RIGID_EVALUATION_MAIN_FAMILIES " + json.dumps(main_families), flush=True)
    controls = graph_setup(scene, bodies[0])
    leaf = controls[1][1]
    material, world, compositor = controls[0][1], controls[2][1], controls[4][1]
    group = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeGroup")
    rna_descriptors = {
        "scene": descriptors(scene, ("animation_data", "node_tree", "compositing_node_group")),
        "material": descriptors(material, ("animation_data", "node_tree")),
        "world": descriptors(world, ("animation_data", "node_tree")),
        "shader_tree": descriptors(leaf, ("animation_data", "nodes", "links", "interface")),
        "compositor_tree": descriptors(compositor, ("animation_data", "nodes", "links", "interface")),
        "interface_socket": descriptors(leaf.interface.items_tree[0], ("item_type", "socket_type")),
        "group_node": descriptors(group, ("node_tree",)),
    }
    print("RIGID_EVALUATION_RNA " + json.dumps(rna_descriptors), flush=True)
    counters = {}

    def counter(label, frame):
        counters[label] = counters.get(label, 0)+1
        return .25+float(frame)*.001

    assert NAMESPACE not in bpy.app.driver_namespace
    bpy.app.driver_namespace[NAMESPACE] = counter
    registry = ToolRegistry(enabled_toolsets=("simulation",))
    rigid_body.register(registry)
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    context = ToolContext(state=BridgeState(), permissions=PermissionManager(lambda: grants), registry=registry, checkpoints=None)
    params = {"scene_name": scene.name, "body_names": sorted(obj.name for obj in bodies),
              "constraint_names": [], "operation": "BAKE", "frame_start": 1, "frame_end": 3}
    writes = []
    original_methods = {name: getattr(rigid_body._Boundary, name) for name in ("frame", "reset", "range_field", "native")}

    def no_owned_write(self, *args, **kwargs):
        writes.append({"args": str(args), "kwargs": str(kwargs)})
        raise AssertionError("Evaluation dependency admitted an owned cache/frame write")

    def frozen():
        return {"context": context_state(), "cache": cache_state(scene.rigidbody_world.point_cache),
                "time_scale": scene.rigidbody_world.time_scale, "handlers": handlers(), "counters": dict(counters)}

    def expect_denial(label, call):
        before = frozen()
        try:
            call()
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED", error.to_dict()
            result = {"case": label, "error": error.to_dict(), "owned_writes": len(writes), "counter_unchanged": True,
                      "context_cache_handlers_unchanged": True}
        else:
            raise AssertionError("Evaluation dependency admitted: " + label)
        assert not writes and frozen() == before
        return result

    def install(label, target, path, index):
        curve = target.driver_add(path) if index is None else target.driver_add(path, index)
        curve.driver.type = "SCRIPTED"
        curve.driver.expression = f'{NAMESPACE}("{label}", frame)'
        return curve

    results = []
    try:
        for label, owner, target, path, index in controls:
            scene.frame_set(7, subframe=.25)
            bpy.context.view_layer.update()
            assert bpy.context.view_layer.objects.active is sentinel
            healthy = rigid_body.cache_preview(context, params)
            proposal = {**params, "expected_fingerprint": healthy["expected_fingerprint"]}
            curve = install(label, target, path, index)
            original_handlers = handlers()
            for method in original_methods:
                setattr(rigid_body._Boundary, method, no_owned_write)
            try:
                preview_denial = expect_denial(label+"_preview", lambda: rigid_body.cache_preview(context, params))
                cache_denial = expect_denial(label+"_cache", lambda proposal=proposal: rigid_body.cache(context, proposal))
            finally:
                for method, original in original_methods.items():
                    setattr(rigid_body._Boundary, method, original)
            before = counters.get(label, 0)
            scene.frame_set(2, subframe=0.)
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            frame_delta = counters.get(label, 0)-before
            explicit_error = None
            if not frame_delta:
                try:
                    owner.update_tag()
                    graph.update()
                    owner.evaluated_get(graph)
                except RuntimeError as error:
                    explicit_error = type(error).__name__
            explicit_delta = counters.get(label, 0)-before
            driver_valid = bool(curve.driver.is_valid)
            print("RIGID_EVALUATION_CONTROL " + json.dumps({"case": label, "frame_counter_delta": frame_delta,
                    "explicit_counter_delta": explicit_delta, "driver_valid": driver_valid,
                    "explicit_owner_error": explicit_error}), flush=True)
            assert driver_valid
            assert explicit_delta > 0, (label, frame_delta, explicit_delta)
            assert handlers() == original_handlers
            results.append({"case": label, "preview_denial": preview_denial, "cache_denial": cache_denial,
                            "negative_control": {"frame_set_counter_delta": frame_delta,
                                                 "explicit_graph_counter_delta": explicit_delta, "driver_valid": driver_valid,
                                                 "explicit_owner_error": explicit_error},
                            "execute_python_bridge_permission": grants[Permission.EXECUTE_PYTHON.value]})
            owner.animation_data_clear()
        scene.frame_set(7, subframe=.25)
        bpy.context.view_layer.update()
        healthy = rigid_body.cache_preview(context, params)
        proposal = {**params, "expected_fingerprint": healthy["expected_fingerprint"]}
        label, owner, target, path, index = controls[1]
        provider_calls = [0]

        def late_provider():
            provider_calls[0] += 1
            if provider_calls[0] == 3:
                install("late_nested_material", target, path, index)
            return grants

        context.permissions = PermissionManager(late_provider)
        for method in original_methods:
            setattr(rigid_body._Boundary, method, no_owned_write)
        try:
            late = expect_denial("late_provider_nested_animation", lambda: rigid_body.cache(context, proposal))
            assert provider_calls[0] >= 3
        finally:
            for method, original in original_methods.items():
                setattr(rigid_body._Boundary, method, original)
            context.permissions = PermissionManager(lambda: grants)
            owner.animation_data_clear()
        scene.frame_set(7, subframe=.25)
        bpy.context.view_layer.update()
        getter = {"calls": 0}

        def native_custom_getter(self):
            getter["calls"] += 1
            return .5

        custom = type("BridgeOwnedRigidGetterNode", (bpy.types.Node,), {
            "bl_idname": "BridgeOwnedRigidGetterNode", "bl_label": "Owned Rigid Getter Probe",
            "__module__": __name__, "__annotations__": {"owned_probe": bpy.props.FloatProperty(get=native_custom_getter)},
        })
        bpy.utils.register_class(custom)
        custom_tree = bpy.data.node_groups.new("Owned Custom Getter Dependency", "ShaderNodeTree")
        try:
            node = custom_tree.nodes.new(custom.bl_idname)
            before_getter = getter["calls"]
            custom_denial = expect_denial("custom_node_getter", lambda: rigid_body.cache_preview(context, params))
            assert getter["calls"] == before_getter
            assert node.owned_probe == .5 and getter["calls"] == before_getter+1
            custom_denial.update(getter_invoked_during_admission=False, explicit_getter_control_delta=1)
        finally:
            bpy.data.node_groups.remove(custom_tree)
            bpy.utils.unregister_class(custom)
        assert context_state()["frame"] == 7 and context_state()["subframe"] == .25
        assert not scene.rigidbody_world.point_cache.is_baked
        assert bpy.context.view_layer.objects.active is sentinel
        print(MARKER + json.dumps({"blender_version": bpy.app.version_string, "driver_cases": results,
              "late_provider": late, "custom_getter": custom_denial,
              "native_rna_descriptors": rna_descriptors,
              "native_main_families": main_families,
              "compositor_value_rna": controls[4][2].node.bl_rna.identifier,
              "owned_writes": writes, "release_readiness": "NOT_ASSESSED",
              "handlers_installed_by_fixture": False, "project_saved": False}), flush=True)
    finally:
        for method, original in original_methods.items():
            setattr(rigid_body._Boundary, method, original)
        bpy.app.driver_namespace.pop(NAMESPACE, None)


if __name__ == "__main__":
    main()
