"""Scene compositor editing on Blender 4.5 and 5.x, without file/script nodes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import invalid_argument
from ..permissions import Permission
from ..utils import bool_param, int_param, reject_unknown_params, require_blender
from . import geometry_nodes as geometry
from . import nodes
from ._rna import apply_assignments, bounded_name, prepare_assignments, settings_mapping

SAFE_NODES = frozenset(
    {
        "CompositorNodeRLayers",
        "CompositorNodeComposite",
        "NodeGroupOutput",
        "CompositorNodeRGB",
        "CompositorNodeValue",
        "CompositorNodeMixRGB",
        "CompositorNodeBlur",
        "CompositorNodeBrightContrast",
        "CompositorNodeGamma",
        "CompositorNodeHueSat",
        "CompositorNodeInvert",
        "CompositorNodeMath",
        "CompositorNodeAlphaOver",
        "CompositorNodeGlare",
        "CompositorNodeViewer",
        "NodeReroute",
        "NodeFrame",
    }
)
PROPERTIES = frozenset(
    {
        "label",
        "location",
        "mute",
        "hide",
        "blend_type",
        "use_alpha",
        "use_clamp",
        "operation",
        "filter_type",
        "size_x",
        "size_y",
        "use_relative",
        "factor_x",
        "factor_y",
    }
)


def _scene(params: Mapping[str, Any]) -> Any:
    name = bounded_name(params.get("scene_name"), "scene_name")
    scene = require_blender().data.scenes.get(name)
    if scene is None:
        raise invalid_argument("Scene not found.", scene_name=name)
    return scene


def _tree(scene: Any, *, modify: bool = False) -> Any:
    tree = (
        getattr(scene, "compositing_node_group", None)
        if hasattr(scene, "compositing_node_group")
        else scene.node_tree
    )
    if tree is None:
        raise invalid_argument("Scene has no compositor graph; use compositor.create first.")
    if modify:
        geometry._editable(scene)
        geometry._editable(tree)
        if hasattr(scene, "compositing_node_group") and tree.users > 1:
            raise invalid_argument(
                "Shared compositor groups require a separate explicit ownership workflow."
            )
        if len(tree.nodes) > 512 or len(tree.links) > 2048:
            raise invalid_argument("Compositor graph exceeds editing limits.")
        if any(node.bl_idname not in SAFE_NODES for node in tree.nodes):
            raise invalid_argument(
                "Graph contains unreviewed nodes; file/image/script/nested nodes are not edited implicitly."
            )
    return tree


def inspect(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"scene_name", "max_nodes", "max_links"})
    scene = _scene(params)
    maximum = int_param(params, "max_nodes", 100, minimum=1, maximum=256)
    max_links = int_param(params, "max_links", 200, minimum=1, maximum=512)
    tree = _tree(scene)
    return {
        "scene": scene.name,
        "tree": tree.name,
        "nodes": [nodes._node_summary(node, max_sockets=32) for node in list(tree.nodes)[:maximum]],
        "links": [nodes._link_summary(link) for link in list(tree.links)[:max_links]],
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "truncated": len(tree.nodes) > maximum or len(tree.links) > max_links,
        "supported_node_types": sorted(SAFE_NODES),
    }


def create(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"scene_name"})
    scene = _scene(params)
    geometry._editable(scene)
    bpy = require_blender()
    if hasattr(scene, "compositing_node_group"):
        if scene.compositing_node_group is not None:
            raise invalid_argument("Compositor already exists; it is not replaced implicitly.")
        tree = bpy.data.node_groups.new(f"{scene.name} Compositor", "CompositorNodeTree")
        try:
            tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            output = tree.nodes.new("NodeGroupOutput")
            render = tree.nodes.new("CompositorNodeRLayers")
            render.scene = scene
            tree.links.new(render.outputs["Image"], output.inputs["Image"])
            scene.compositing_node_group = tree
        except Exception:
            bpy.data.node_groups.remove(tree)
            raise
    else:
        if scene.node_tree is not None:
            raise invalid_argument("Compositor already exists; it is not replaced implicitly.")
        scene.use_nodes = True
    return {"created": True, **inspect(context, {"scene_name": scene.name})}


def edit(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    operation = params.get("operation")
    common = {"scene_name", "operation"}
    options = {
        "ADD": {"node_type", "node_name", "settings"},
        "REMOVE": {"node_name"},
        "SET": {"node_name", "settings"},
        "INPUT": {"node_name", "socket_name", "socket_index", "value"},
        "OUTPUT": {"node_name", "socket_name", "socket_index", "value"},
        "LINK": {
            "from_node",
            "from_socket",
            "from_socket_index",
            "to_node",
            "to_socket",
            "to_socket_index",
            "replace_existing",
        },
        "UNLINK": {
            "from_node",
            "from_socket",
            "from_socket_index",
            "to_node",
            "to_socket",
            "to_socket_index",
        },
    }
    if not isinstance(operation, str) or operation not in options:
        raise invalid_argument("operation must be ADD, REMOVE, SET, INPUT, OUTPUT, LINK or UNLINK.")
    reject_unknown_params(params, common | options[operation])
    scene = _scene(params)
    tree = _tree(scene, modify=True)
    bpy = require_blender()
    if operation == "ADD":
        node_type = bounded_name(params.get("node_type"), "node_type")
        name = bounded_name(params.get("node_name"), "node_name", maximum=63)
        if (
            len(name.encode("utf-8")) > 63
            or node_type not in SAFE_NODES
            or tree.nodes.get(name)
            or len(tree.nodes) >= 512
        ):
            raise invalid_argument("Node type/name unavailable or graph full.")
        node = tree.nodes.new(node_type)
        try:
            node.name = name
            apply_assignments(
                node,
                prepare_assignments(
                    node,
                    settings_mapping(params, required=False),
                    allowed=PROPERTIES,
                    object_pointers=frozenset(),
                    bpy=bpy,
                ),
            )
            if node_type == "CompositorNodeRLayers":
                node.scene = scene
        except Exception:
            tree.nodes.remove(node)
            raise
    elif operation in {"SET", "REMOVE", "INPUT", "OUTPUT"}:
        node = nodes._node_exact(tree, bounded_name(params.get("node_name"), "node_name"))
        if operation == "REMOVE":
            tree.nodes.remove(node)
        elif operation == "SET":
            apply_assignments(
                node,
                prepare_assignments(
                    node,
                    settings_mapping(params),
                    allowed=PROPERTIES,
                    object_pointers=frozenset(),
                    bpy=bpy,
                ),
            )
        else:
            if operation == "OUTPUT" and node.bl_idname not in {
                "CompositorNodeRGB",
                "CompositorNodeValue",
            }:
                raise invalid_argument("OUTPUT edits are limited to RGB and Value constants.")
            socket = nodes._socket_exact(
                node,
                "output" if operation == "OUTPUT" else "input",
                bounded_name(params.get("socket_name"), "socket_name"),
                params.get("socket_index"),
            )
            if "value" not in params or (operation == "INPUT" and socket.is_linked):
                raise invalid_argument(
                    "A value is required; linked inputs cannot be edited implicitly."
                )
            socket.default_value = nodes._coerce_default_value(socket, params["value"])
    else:
        source_node, source = nodes._endpoint(tree, params, "from", "output")
        target_node, target = nodes._endpoint(tree, params, "to", "input")
        if operation == "UNLINK":
            for link in list(tree.links):
                if link.from_socket == source and link.to_socket == target:
                    tree.links.remove(link)
        else:
            replace = bool_param(params, "replace_existing", False)
            if len(tree.links) >= 2048 or (target.is_linked and not replace):
                raise invalid_argument(
                    "Link limit reached or occupied input requires replace_existing."
                )
            geometry._check_link(tree, source_node, source, target_node, target)
            tree.links.new(source, target)
    return {"edited": operation, **inspect(context, {"scene_name": scene.name})}


def register_tools(registry: Any) -> None:
    for name, handler in (("inspect", inspect), ("create", create), ("edit", edit)):
        registry.register(
            f"compositor.{name}",
            handler,
            toolset="compositor",
            modifies=name != "inspect",
            permissions=(Permission.INSPECT_SCENE,)
            if name == "inspect"
            else (Permission.EDIT_RENDER,),
            description=f"Structured scene compositor {name}, with reviewed node/socket contracts.",
        )
