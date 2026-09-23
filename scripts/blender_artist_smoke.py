"""Isolated real-Blender evidence for the unreleased structured artist tools.

Run with --background --factory-startup --python-exit-code 1. Creates only
disposable fixtures and one explicitly named render under build/; no .blend save.
"""

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
from blender_codex_bridge.tools import animation_layers as anim  # noqa: E402
from blender_codex_bridge.tools import compositor, simulation, weights  # noqa: E402
from blender_codex_bridge.tools import geometry_nodes as gn  # noqa: E402


def call(handler, **params):
    runtime = get_runtime()
    name = next(
        name
        for name in runtime.registry.list_tools()
        if runtime.registry.get(name).handler == handler
    )
    return runtime.dispatch(name, params)


def denied(handler, **params):
    try:
        call(handler, **params)
    except BridgeError as exc:
        assert exc.code == "INVALID_ARGUMENT", exc
    else:
        raise AssertionError("Unsafe request accepted")


def empty(name):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    allowed = {permission.value: True for permission in Permission}
    permissions = PermissionManager(lambda: allowed)
    runtime.permissions = runtime.executor.permissions = permissions
    for group in ("weights", "compositor", "animation_layers", "simulation", "geometry_nodes"):
        runtime.dispatch("toolsets.enable", {"name": group})
    for handler, permission in (
        (weights.group_create, "EDIT_MESH"),
        (compositor.create, "EDIT_RENDER"),
        (anim.driver_add, "EDIT_ANIMATION"),
        (simulation.cloth_add, "EDIT_SCENE"),
    ):
        allowed[permission] = False
        try:
            call(handler)
        except BridgeError as exc:
            assert exc.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Permission denial bypassed")
        finally:
            allowed[permission] = True
    scene = bpy.context.scene
    selected = [o.name for o in bpy.context.selected_objects]
    active = bpy.context.view_layer.objects.active
    cube = bpy.data.objects["Cube"]
    for name, value in (("A", 0.2), ("B", 0.3)):
        call(weights.group_create, object_name=cube.name, group_name=name)
        call(
            weights.assign,
            object_name=cube.name,
            group_name=name,
            vertex_indices=list(range(8)),
            weight=value,
        )
    call(
        weights.normalize,
        object_name=cube.name,
        group_names=["A", "B"],
        vertex_indices=list(range(8)),
    )
    assert abs(cube.vertex_groups["A"].weight(0) - 0.4) < 1e-6
    assert abs(cube.vertex_groups["B"].weight(7) - 0.6) < 1e-6
    cube.vertex_groups["A"].lock_weight = True
    denied(weights.assign, object_name=cube.name, group_name="A", vertex_indices=[0], weight=0.9)
    cube.vertex_groups["A"].lock_weight = False
    call(weights.assign, object_name=cube.name, group_name="A", vertex_indices=[0], weight=None)
    assert len(cube.data.vertices[0].groups) == 1
    page = call(weights.inspect, object_name=cube.name, offset=2, max_vertices=2)
    assert page["truncated"]

    source, target = empty("Driver Source"), empty("Driver Target")
    source.location.x = 2
    call(
        anim.driver_add,
        object_name=target.name,
        data_path="location",
        index=0,
        variables=[
            {
                "object_name": source.name,
                "transform_type": "LOC_X",
                "transform_space": "WORLD_SPACE",
            }
        ],
    )
    bpy.context.view_layer.update()
    assert (
        abs(
            target.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation.x
            - 2
        )
        < 1e-5
    )
    denied(
        anim.driver_add,
        object_name=target.name,
        data_path="scale",
        driver_type="SCRIPTED",
        variables=[],
    )
    call(anim.driver_remove, object_name=target.name, data_path="location", index=0)
    assert not target.animation_data.drivers

    actor = empty("NLA Actor")
    actor.location.x = 0
    actor.keyframe_insert(data_path="location", frame=1)
    actor.location.x = 10
    actor.keyframe_insert(data_path="location", frame=11)
    action = actor.animation_data.action
    actor.animation_data.action = None
    call(
        anim.nla_add,
        object_name=actor.name,
        track_name="Motion",
        strip_name="Walk",
        action_name=action.name,
    )
    scene.frame_set(6)
    assert abs(actor.location.x - 5) < 0.01, actor.location.x
    call(
        anim.nla_edit,
        object_name=actor.name,
        track_name="Motion",
        strip_name="Walk",
        settings={"scale": 2.0},
    )
    assert actor.animation_data.nla_tracks["Motion"].strips["Walk"].scale == 2
    call(anim.nla_edit, object_name=actor.name, track_name="Motion", strip_name="Walk", remove=True)
    assert not actor.animation_data.nla_tracks["Motion"].strips

    for kind in ("REPEAT", "SIMULATION"):
        group = f"Artist {kind}"

        def graph(handler, group=group, **params):
            return call(handler, group_name=group, **params)

        graph(gn.create_graph)
        graph(
            gn.zone_create,
            zone_type=kind,
            input_name="Zone In",
            output_name="Zone Out",
            iterations=3,
        )
        graph(gn.zone_item_add, output_name="Zone Out", socket_type="FLOAT", name="Amount")
        tree = bpy.data.node_groups[group]
        assert tree.nodes["Zone In"].paired_output == tree.nodes["Zone Out"]
        graph(gn.add_node, node_type="GeometryNodeTransform", name="Step")
        graph(gn.set_node_input, node_name="Step", socket_name="Translation", value=[1, 0, 0])
        for a, b in (
            ("Group Input", "Zone In"),
            ("Zone In", "Step"),
            ("Step", "Zone Out"),
            ("Zone Out", "Group Output"),
        ):
            graph(
                gn.link_nodes,
                from_node=a,
                from_socket="Geometry",
                to_node=b,
                to_socket="Geometry",
                replace_existing=True,
            )
        obj = bpy.data.objects.new(group, cube.data.copy())
        scene.collection.objects.link(obj)
        graph(gn.attach_graph, object_name=obj.name, modifier_name="Zones")
        scene.frame_set(1)
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        coords = [v.co.x for v in evaluated.data.vertices]
        assert len(coords) == 8
        if kind == "REPEAT":
            assert abs(min(coords) - 2) < 1e-5 and abs(max(coords) - 4) < 1e-5, coords
            denied(
                gn.set_node_input,
                group_name=group,
                node_name="Zone In",
                socket_name="Iterations",
                value=65,
            )
        else:
            initial_x = min(coords)
            scene.frame_set(2)
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            assert abs(min(v.co.x for v in evaluated.data.vertices) - initial_x - 1) < 1e-5
        denied(gn.remove_node, group_name=group, node_name="Zone In")
        graph(gn.zone_remove, output_name="Zone Out")
        assert tree.nodes.get("Zone In") is None and tree.nodes.get("Zone Out") is None

    mesh = bpy.data.meshes.new("Cloth Fixture")
    mesh.from_pydata(
        [(x / 3, y / 3, 2) for y in range(4) for x in range(4)],
        [],
        [
            (y * 4 + x, y * 4 + x + 1, (y + 1) * 4 + x + 1, (y + 1) * 4 + x)
            for y in range(3)
            for x in range(3)
        ],
    )
    cloth = bpy.data.objects.new("Cloth Fixture", mesh)
    scene.collection.objects.link(cloth)
    cp = {"object_name": cloth.name, "modifier_name": "Cloth"}
    call(simulation.cloth_add, **cp)
    call(simulation.configure, **cp, settings={"mass": 0.4, "quality": 2})
    scene.frame_set(7)
    baked = call(simulation.cache, **cp, operation="BAKE", frame_start=1, frame_end=3)
    assert baked["cache"]["baked"] and scene.frame_current == 7
    scene.frame_set(3)
    evaluated = cloth.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert min(v.co.z for v in evaluated.data.vertices) < 1.999
    call(simulation.cache, **cp, operation="FREE")
    assert not cloth.modifiers["Cloth"].point_cache.is_baked
    cloth.modifiers["Cloth"].point_cache.use_disk_cache = True
    # Blender can refuse to enable disk caching for an unsaved fixture.
    if cloth.modifiers["Cloth"].point_cache.use_disk_cache:
        denied(simulation.cache, **cp, operation="BAKE")
    cloth.modifiers["Cloth"].point_cache.use_disk_cache = False

    call(compositor.create, scene_name=scene.name)

    def comp(operation, **params):
        return call(compositor.edit, scene_name=scene.name, operation=operation, **params)

    comp("ADD", node_type="CompositorNodeRGB", node_name="Red")
    tree = (
        scene.compositing_node_group
        if hasattr(scene, "compositing_node_group")
        else scene.node_tree
    )
    color_socket = tree.nodes["Red"].outputs[0].name
    comp("OUTPUT", node_name="Red", socket_name=color_socket, value=[1, 0, 0, 1])
    output = next(
        n for n in tree.nodes if n.bl_idname in {"NodeGroupOutput", "CompositorNodeComposite"}
    )
    comp(
        "LINK",
        from_node="Red",
        from_socket=color_socket,
        to_node=output.name,
        to_socket="Image",
        replace_existing=True,
    )
    denied(
        compositor.edit,
        scene_name=scene.name,
        operation="ADD",
        node_type="CompositorNodeOutputFile",
        node_name="Unsafe",
    )
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.resolution_x = scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    path = ROOT / "build" / f"artist-compositor-{bpy.app.version[0]}.png"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    pixel = list(image.pixels[:4])
    assert pixel[0] > 0.9 and pixel[1] < 0.01 and pixel[2] < 0.01, pixel
    assert [o.name for o in bpy.context.selected_objects] == selected
    assert bpy.context.view_layer.objects.active == active
    print(
        json.dumps(
            {
                "artist_smoke": "PASS",
                "blender": bpy.app.version_string,
                "domains": ["weights", "drivers", "NLA", "zones", "cloth_cache", "compositor"],
                "compositor_pixel": pixel,
                "render": str(path),
            }
        )
    )


try:
    main()
finally:
    blender_codex_bridge.unregister()
