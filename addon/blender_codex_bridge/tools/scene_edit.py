"""Structured scene, collection, camera, light, and world configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from itertools import islice
from typing import Any

from ..errors import invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, get_object, require_blender, similar_names, vector3

_UNIT_SYSTEMS = {"NONE", "METRIC", "IMPERIAL"}
_CAMERA_TYPES = {"PERSP", "ORTHO", "PANO"}
_LIGHT_TYPES = {"POINT", "SUN", "SPOT", "AREA"}


@dataclass(frozen=True, slots=True)
class _PreparedScene:
    scene: Any
    set_camera: bool
    camera: Any | None
    unit_system: str | None
    unit_scale_length: float | None
    use_gravity: bool | None
    gravity: tuple[float, float, float] | None


@dataclass(frozen=True, slots=True)
class _PreparedCamera:
    obj: Any
    camera: Any
    camera_type: str | None
    numeric: tuple[tuple[str, float], ...]
    dof_enabled: bool | None
    set_focus: bool
    focus_object: Any | None
    aperture_fstop: float | None
    active_scene: Any | None
    set_active_for_scene: bool


@dataclass(frozen=True, slots=True)
class _PreparedLight:
    obj: Any
    light: Any
    light_type: str | None
    energy: float | None
    color: tuple[float, ...] | None
    numeric: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class _PreparedWorld:
    bpy: Any
    scene: Any
    world: Any | None
    new_world_name: str | None
    explicit_use_nodes: bool | None
    planned_use_nodes: bool
    color: tuple[float, ...] | None
    strength: float | None
    needs_background: bool


def _restore_attribute(owner: Any, name: str, value: Any) -> None:
    """Best-effort RNA restoration that never hides the original apply failure."""

    with suppress(Exception):
        setattr(owner, name, value)


def _copied_rna_value(value: Any) -> Any:
    if isinstance(value, (str, bytes)):
        return value
    try:
        return tuple(value)
    except TypeError:
        return value


def _node_input(node: Any, name: str) -> Any | None:
    inputs = getattr(node, "inputs", None)
    if inputs is None:
        return None
    with suppress(AttributeError, KeyError, TypeError):
        socket = inputs.get(name)
        if socket is not None:
            return socket
    with suppress(KeyError, TypeError):
        return inputs[name]
    return None


def _world_node_snapshot(world: Any) -> tuple[tuple[Any, ...], tuple[tuple[Any, Any], ...]]:
    node_tree = getattr(world, "node_tree", None)
    nodes = tuple(node_tree.nodes) if node_tree is not None else ()
    socket_values: list[tuple[Any, Any]] = []
    for node in nodes:
        if getattr(node, "type", None) != "BACKGROUND":
            continue
        for socket_name in ("Color", "Strength"):
            socket = _node_input(node, socket_name)
            if socket is not None:
                socket_values.append(
                    (socket, _copied_rna_value(socket.default_value))
                )
    return nodes, tuple(socket_values)


def _remove_new_world_nodes(world: Any, original_nodes: tuple[Any, ...]) -> None:
    node_tree = getattr(world, "node_tree", None)
    if node_tree is None:
        return
    original_ids = {id(node) for node in original_nodes}
    for node in tuple(node_tree.nodes):
        if id(node) not in original_ids:
            with suppress(Exception):
                node_tree.nodes.remove(node)


def _required_name(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise invalid_argument(
            f"'{key}' must be a non-empty string of at most 256 characters.",
            parameter=key,
        )
    return value.strip()


def _scene(name: str) -> Any:
    bpy = require_blender()
    scene = bpy.data.scenes.get(name)
    if scene is None:
        raise invalid_argument(
            f"Scene '{name}' does not exist.",
            available_similar_scenes=similar_names(name, bpy.data.scenes.keys()),
        )
    return scene


def _collection(name: str) -> Any:
    bpy = require_blender()
    collection = bpy.data.collections.get(name)
    if collection is None:
        raise invalid_argument(
            f"Collection '{name}' does not exist.",
            available_similar_collections=similar_names(name, bpy.data.collections.keys()),
        )
    return collection


def _collection_belongs_to_scene(collection: Any, scene: Any) -> bool:
    root = scene.collection
    if collection == root:
        return True
    return collection in root.children_recursive


def _color(value: Any, key: str, *, components: int = 3) -> tuple[float, ...]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != components
    ):
        raise invalid_argument(f"'{key}' must contain exactly {components} numbers.", parameter=key)
    result: list[float] = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise invalid_argument(f"'{key}' must contain only numbers.", parameter=key)
        converted = float(component)
        if not math.isfinite(converted) or converted < 0.0 or converted > 100.0:
            raise invalid_argument(
                f"'{key}' components must be finite values from 0 to 100.",
                parameter=key,
            )
        result.append(converted)
    return tuple(result)


def _scene_state(scene: Any) -> dict[str, Any]:
    return {
        "scene": scene.name,
        "camera": scene.camera.name if scene.camera else None,
        "world": scene.world.name if scene.world else None,
        "unit_system": scene.unit_settings.system,
        "unit_scale_length": float(scene.unit_settings.scale_length),
        "use_gravity": bool(scene.use_gravity),
        "gravity": [float(value) for value in scene.gravity],
    }


def _prepare_scene(params: Mapping[str, Any]) -> _PreparedScene:
    scene = _scene(_required_name(params, "scene_name"))
    clear_camera = bool_param(params, "clear_camera", False)
    if clear_camera and params.get("camera_object") is not None:
        raise invalid_argument("Use either 'camera_object' or 'clear_camera', not both.")

    set_camera = clear_camera or "camera_object" in params
    camera = None
    if not clear_camera and "camera_object" in params:
        camera_name = params.get("camera_object")
        if camera_name is not None:
            camera = get_object(camera_name, allow_active=False)
            if camera.type != "CAMERA" or camera.name not in scene.objects:
                raise invalid_argument(
                    "'camera_object' must name a camera in the target scene.",
                    camera_object=camera.name,
                    scene=scene.name,
                )

    unit_system = None
    if "unit_system" in params:
        value = params.get("unit_system")
        if not isinstance(value, str) or value.upper() not in _UNIT_SYSTEMS:
            raise invalid_argument("Unsupported unit system.", supported=sorted(_UNIT_SYSTEMS))
        unit_system = value.upper()
    unit_scale_length = (
        float_param(
            params,
            "unit_scale_length",
            float(scene.unit_settings.scale_length),
            minimum=1.0e-9,
            maximum=1.0e9,
        )
        if "unit_scale_length" in params
        else None
    )
    use_gravity = (
        bool_param(params, "use_gravity", bool(scene.use_gravity))
        if "use_gravity" in params
        else None
    )
    gravity = vector3(params.get("gravity"), "gravity") if "gravity" in params else None
    return _PreparedScene(
        scene=scene,
        set_camera=set_camera,
        camera=camera,
        unit_system=unit_system,
        unit_scale_length=unit_scale_length,
        use_gravity=use_gravity,
        gravity=gravity,
    )


def configure_scene(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    prepared = _prepare_scene(params)
    scene = prepared.scene
    saved = {
        "camera": scene.camera,
        "unit_system": scene.unit_settings.system,
        "unit_scale_length": float(scene.unit_settings.scale_length),
        "use_gravity": bool(scene.use_gravity),
        "gravity": _copied_rna_value(scene.gravity),
    }
    try:
        if prepared.set_camera:
            scene.camera = prepared.camera
        if prepared.unit_system is not None:
            scene.unit_settings.system = prepared.unit_system
        if prepared.unit_scale_length is not None:
            scene.unit_settings.scale_length = prepared.unit_scale_length
        if prepared.use_gravity is not None:
            scene.use_gravity = prepared.use_gravity
        if prepared.gravity is not None:
            scene.gravity = prepared.gravity
        return {"configured": True, **_scene_state(scene)}
    except Exception:
        _restore_attribute(scene, "camera", saved["camera"])
        _restore_attribute(scene.unit_settings, "system", saved["unit_system"])
        _restore_attribute(
            scene.unit_settings,
            "scale_length",
            saved["unit_scale_length"],
        )
        _restore_attribute(scene, "use_gravity", saved["use_gravity"])
        _restore_attribute(scene, "gravity", saved["gravity"])
        raise


def create_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    name = _required_name(params, "name")[:63]
    if bpy.data.collections.get(name) is not None:
        raise invalid_argument(f"Collection '{name}' already exists.")
    scene = _scene(_required_name(params, "scene_name"))
    parent_name = params.get("parent_collection")
    if parent_name is not None and (not isinstance(parent_name, str) or not parent_name.strip()):
        raise invalid_argument("'parent_collection' must be a non-empty string or null.")
    parent = _collection(parent_name.strip()) if isinstance(parent_name, str) else scene.collection
    if not _collection_belongs_to_scene(parent, scene):
        raise invalid_argument(
            "'parent_collection' must belong to the requested scene.",
            parent_collection=parent.name,
            scene=scene.name,
        )
    collection = bpy.data.collections.new(name)
    try:
        parent.children.link(collection)
    except Exception:
        bpy.data.collections.remove(collection)
        raise
    return {
        "created": True,
        "collection": collection.name,
        "parent_collection": parent.name,
        "scene": scene.name,
    }


def rename_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    collection = _collection(_required_name(params, "collection_name"))
    new_name = _required_name(params, "new_name")[:63]
    collision = bpy.data.collections.get(new_name)
    if collision is not None and collision != collection:
        raise invalid_argument(f"Collection '{new_name}' already exists.")
    old_name = collection.name
    collection.name = new_name
    return {"renamed": True, "old_name": old_name, "collection": collection.name}


def delete_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    bpy = require_blender()
    collection = _collection(_required_name(params, "collection_name"))
    if not bool_param(params, "confirm_delete", False):
        raise invalid_argument(
            "Set 'confirm_delete' to true; removing a collection may unlink its contents."
        )
    object_names = [obj.name for obj in islice(collection.objects, 100)]
    child_names = [child.name for child in islice(collection.children, 100)]
    object_count = len(collection.objects)
    child_count = len(collection.children)
    name = collection.name
    bpy.data.collections.remove(collection)
    return {
        "deleted": True,
        "collection": name,
        "unlinked_objects": object_names,
        "unlinked_object_count": object_count,
        "unlinked_objects_truncated": object_count > len(object_names),
        "unlinked_children": child_names,
        "unlinked_child_count": child_count,
        "unlinked_children_truncated": child_count > len(child_names),
        "affected_objects": object_names,
    }


def _prepare_camera(params: Mapping[str, Any]) -> _PreparedCamera:
    obj = get_object(_required_name(params, "object_name"), allow_active=False)
    if obj.type != "CAMERA":
        raise invalid_argument(f"Object '{obj.name}' is not a camera.", object_type=obj.type)
    camera = obj.data

    camera_type = None
    if "camera_type" in params:
        value = params.get("camera_type")
        if not isinstance(value, str) or value.upper() not in _CAMERA_TYPES:
            raise invalid_argument("Unsupported camera type.", supported=sorted(_CAMERA_TYPES))
        camera_type = value.upper()
    numeric = {
        "lens": (1.0, 2000.0),
        "sensor_width": (1.0, 1000.0),
        "clip_start": (1.0e-5, 1.0e9),
        "clip_end": (1.0e-4, 1.0e12),
        "ortho_scale": (1.0e-5, 1.0e9),
    }
    numeric_values: list[tuple[str, float]] = []
    for name, (minimum, maximum) in numeric.items():
        if name in params:
            numeric_values.append(
                (
                    name,
                    float_param(
                        params,
                        name,
                        float(getattr(camera, name)),
                        minimum=minimum,
                        maximum=maximum,
                    ),
                )
            )
    numeric_lookup = dict(numeric_values)
    clip_start = numeric_lookup.get("clip_start", float(camera.clip_start))
    clip_end = numeric_lookup.get("clip_end", float(camera.clip_end))
    if clip_end <= clip_start:
        raise invalid_argument("Camera 'clip_end' must be greater than 'clip_start'.")

    dof_enabled = (
        bool_param(params, "dof_enabled", bool(camera.dof.use_dof))
        if "dof_enabled" in params
        else None
    )
    clear_focus = bool_param(params, "clear_focus_object", False)
    if clear_focus and params.get("focus_object") is not None:
        raise invalid_argument("Use either 'focus_object' or 'clear_focus_object', not both.")
    set_focus = clear_focus or "focus_object" in params
    focus_object = None
    if not clear_focus and "focus_object" in params:
        focus_name = params.get("focus_object")
        if focus_name is not None:
            focus_object = get_object(focus_name, allow_active=False)

    aperture_fstop = (
        float_param(
            params,
            "aperture_fstop",
            float(camera.dof.aperture_fstop),
            minimum=0.1,
            maximum=128.0,
        )
        if "aperture_fstop" in params
        else None
    )

    active_scene = None
    set_active_for_scene = False
    if "set_active_for_scene" in params:
        set_active_for_scene = bool_param(params, "set_active_for_scene", False)
        scene_name = _required_name(params, "scene_name")
        active_scene = _scene(scene_name)
        if obj.name not in active_scene.objects:
            raise invalid_argument("Camera must belong to the requested scene.")

    return _PreparedCamera(
        obj=obj,
        camera=camera,
        camera_type=camera_type,
        numeric=tuple(numeric_values),
        dof_enabled=dof_enabled,
        set_focus=set_focus,
        focus_object=focus_object,
        aperture_fstop=aperture_fstop,
        active_scene=active_scene,
        set_active_for_scene=set_active_for_scene,
    )


def configure_camera(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    prepared = _prepare_camera(params)
    obj = prepared.obj
    camera = prepared.camera
    saved_numeric = {
        name: _copied_rna_value(getattr(camera, name)) for name, _value in prepared.numeric
    }
    saved = {
        "camera_type": camera.type,
        "dof_enabled": bool(camera.dof.use_dof),
        "focus_object": camera.dof.focus_object,
        "aperture_fstop": float(camera.dof.aperture_fstop),
        "active_camera": (
            prepared.active_scene.camera if prepared.active_scene is not None else None
        ),
    }
    try:
        if prepared.camera_type is not None:
            camera.type = prepared.camera_type
        for name, value in prepared.numeric:
            setattr(camera, name, value)
        if prepared.dof_enabled is not None:
            camera.dof.use_dof = prepared.dof_enabled
        if prepared.set_focus:
            camera.dof.focus_object = prepared.focus_object
        if prepared.aperture_fstop is not None:
            camera.dof.aperture_fstop = prepared.aperture_fstop
        if prepared.set_active_for_scene and prepared.active_scene is not None:
            prepared.active_scene.camera = obj
        return {
            "configured": True,
            "object": obj.name,
            "camera": camera.name,
            "camera_type": camera.type,
            "lens": float(camera.lens),
            "sensor_width": float(camera.sensor_width),
            "clip_start": float(camera.clip_start),
            "clip_end": float(camera.clip_end),
            "ortho_scale": float(camera.ortho_scale),
            "dof": {
                "enabled": bool(camera.dof.use_dof),
                "focus_object": camera.dof.focus_object.name if camera.dof.focus_object else None,
                "aperture_fstop": float(camera.dof.aperture_fstop),
            },
        }
    except Exception:
        if prepared.active_scene is not None:
            _restore_attribute(prepared.active_scene, "camera", saved["active_camera"])
        _restore_attribute(camera.dof, "aperture_fstop", saved["aperture_fstop"])
        _restore_attribute(camera.dof, "focus_object", saved["focus_object"])
        _restore_attribute(camera.dof, "use_dof", saved["dof_enabled"])
        for name, value in saved_numeric.items():
            _restore_attribute(camera, name, value)
        _restore_attribute(camera, "type", saved["camera_type"])
        raise


def _prepare_light(params: Mapping[str, Any]) -> _PreparedLight:
    obj = get_object(_required_name(params, "object_name"), allow_active=False)
    if obj.type != "LIGHT":
        raise invalid_argument(f"Object '{obj.name}' is not a light.", object_type=obj.type)
    light = obj.data

    light_type = None
    if "light_type" in params:
        value = params.get("light_type")
        if not isinstance(value, str) or value.upper() not in _LIGHT_TYPES:
            raise invalid_argument("Unsupported light type.", supported=sorted(_LIGHT_TYPES))
        light_type = value.upper()
    energy = (
        float_param(params, "energy", float(light.energy), minimum=0.0, maximum=1.0e12)
        if "energy" in params
        else None
    )
    color = _color(params.get("color"), "color") if "color" in params else None
    numeric_specs = {
        "shadow_soft_size": (0.0, 1.0e9, 0.0),
        "spot_size": (0.001, math.pi, 0.001),
        "spot_blend": (0.0, 1.0, 0.0),
    }
    numeric_values: list[tuple[str, float]] = []
    for name, (minimum, maximum, fallback) in numeric_specs.items():
        if name in params:
            numeric_values.append(
                (
                    name,
                    float_param(
                        params,
                        name,
                        float(getattr(light, name, fallback)),
                        minimum=minimum,
                        maximum=maximum,
                    ),
                )
            )
    return _PreparedLight(
        obj=obj,
        light=light,
        light_type=light_type,
        energy=energy,
        color=color,
        numeric=tuple(numeric_values),
    )


def configure_light(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    prepared = _prepare_light(params)
    obj = prepared.obj
    light = prepared.light
    saved_numeric = {
        name: _copied_rna_value(getattr(light, name))
        for name, _value in prepared.numeric
        if hasattr(light, name)
    }
    saved = {
        "light_type": light.type,
        "energy": float(light.energy),
        "color": _copied_rna_value(light.color),
    }
    try:
        if prepared.light_type is not None:
            light.type = prepared.light_type
            for name, _value in prepared.numeric:
                if name not in saved_numeric and hasattr(light, name):
                    saved_numeric[name] = _copied_rna_value(getattr(light, name))
        if prepared.energy is not None:
            light.energy = prepared.energy
        if prepared.color is not None:
            light.color = prepared.color
        for name, value in prepared.numeric:
            if hasattr(light, name):
                setattr(light, name, value)
        return {
            "configured": True,
            "object": obj.name,
            "light": light.name,
            "light_type": light.type,
            "energy": float(light.energy),
            "color": [float(value) for value in light.color],
            "shadow_soft_size": float(getattr(light, "shadow_soft_size", 0.0)),
            "spot_size": float(getattr(light, "spot_size", 0.0)),
            "spot_blend": float(getattr(light, "spot_blend", 0.0)),
        }
    except Exception:
        for name, value in saved_numeric.items():
            _restore_attribute(light, name, value)
        _restore_attribute(light, "color", saved["color"])
        _restore_attribute(light, "energy", saved["energy"])
        _restore_attribute(light, "type", saved["light_type"])
        raise


def _prepare_world(params: Mapping[str, Any]) -> _PreparedWorld:
    bpy = require_blender()
    scene = _scene(_required_name(params, "scene_name"))
    world_name = params.get("world_name")
    create = bool_param(params, "create", False)
    if world_name is not None and (not isinstance(world_name, str) or not world_name.strip()):
        raise invalid_argument("'world_name' must be a non-empty string or null.")
    world = bpy.data.worlds.get(world_name.strip()) if isinstance(world_name, str) else scene.world
    new_world_name = None
    if world is None:
        if not create:
            raise invalid_argument("The requested scene has no world; set 'create' to true.")
        new_world_name = (
            world_name.strip() if isinstance(world_name, str) else f"{scene.name} World"
        )[:63]

    explicit_use_nodes = None
    if "use_nodes" in params:
        explicit_use_nodes = bool_param(
            params,
            "use_nodes",
            bool(world.use_nodes) if world is not None else False,
        )
    color = _color(params.get("color"), "color") if "color" in params else None
    strength = (
        float_param(
            params,
            "strength",
            1.0,
            minimum=0.0,
            maximum=1.0e6,
        )
        if "strength" in params
        else None
    )
    planned_use_nodes = (
        explicit_use_nodes
        if explicit_use_nodes is not None
        else bool(world.use_nodes) if world is not None else False
    )
    if strength is not None:
        planned_use_nodes = True
    needs_background = strength is not None or (color is not None and planned_use_nodes)
    return _PreparedWorld(
        bpy=bpy,
        scene=scene,
        world=world,
        new_world_name=new_world_name,
        explicit_use_nodes=explicit_use_nodes,
        planned_use_nodes=planned_use_nodes,
        color=color,
        strength=strength,
        needs_background=needs_background,
    )


def configure_world(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    prepared = _prepare_world(params)
    scene = prepared.scene
    world = prepared.world
    created = world is None
    previous_scene_world = scene.world
    saved_use_nodes = bool(world.use_nodes) if world is not None else None
    saved_color = _copied_rna_value(world.color) if world is not None else None
    original_nodes, saved_socket_values = (
        _world_node_snapshot(world) if world is not None else ((), ())
    )
    created_world = None
    try:
        if world is None:
            if prepared.new_world_name is None:
                raise RuntimeError("Prepared world creation has no data-block name.")
            world = prepared.bpy.data.worlds.new(prepared.new_world_name)
            created_world = world
        scene.world = world
        if prepared.explicit_use_nodes is not None:
            world.use_nodes = prepared.explicit_use_nodes
        if prepared.color is not None:
            world.color = prepared.color
        if prepared.needs_background:
            if not world.use_nodes:
                world.use_nodes = True
            background = next(
                (node for node in world.node_tree.nodes if node.type == "BACKGROUND"),
                None,
            )
            if background is None:
                background = world.node_tree.nodes.new("ShaderNodeBackground")
            if prepared.color is not None:
                background.inputs["Color"].default_value = (*prepared.color, 1.0)
            if prepared.strength is not None:
                background.inputs["Strength"].default_value = prepared.strength
        background = None
        if world.use_nodes and world.node_tree:
            background = next(
                (node for node in world.node_tree.nodes if node.type == "BACKGROUND"),
                None,
            )
        return {
            "configured": True,
            "created": created,
            "scene": scene.name,
            "world": world.name,
            "use_nodes": bool(world.use_nodes),
            "color": [float(value) for value in world.color],
            "background": (
                {
                    "color": [
                        float(value)
                        for value in background.inputs["Color"].default_value
                    ],
                    "strength": float(background.inputs["Strength"].default_value),
                }
                if background is not None
                else None
            ),
        }
    except Exception:
        _restore_attribute(scene, "world", previous_scene_world)
        if created_world is not None:
            with suppress(Exception):
                prepared.bpy.data.worlds.remove(created_world, do_unlink=True)
        elif world is not None:
            _remove_new_world_nodes(world, original_nodes)
            for socket, value in saved_socket_values:
                _restore_attribute(socket, "default_value", value)
            _restore_attribute(world, "color", saved_color)
            _restore_attribute(world, "use_nodes", saved_use_nodes)
        raise


def register_tools(registry: ToolRegistry) -> None:
    scene_common = {
        "permissions": (Permission.EDIT_SCENE,),
        "toolset": "scene_edit",
        "modifies": True,
    }
    registry.register("scene.configure", configure_scene, description="Configure an explicit scene's camera, units, and gravity.", **scene_common)
    registry.register("collection.create", create_collection, description="Create and link a collection under an explicit scene or parent.", **scene_common)
    registry.register("collection.rename", rename_collection, description="Rename an explicit collection without collisions.", **scene_common)
    registry.register(
        "collection.delete",
        delete_collection,
        permissions=(Permission.EDIT_SCENE, Permission.DELETE_OBJECTS),
        toolset="scene_edit",
        modifies=True,
        description="Remove an explicitly confirmed collection and report unlinked contents.",
    )
    registry.register("camera.configure", configure_camera, description="Configure camera optics, clipping, depth of field, and active-scene assignment.", **scene_common)
    registry.register("light.configure", configure_light, description="Configure a named Blender light's type, energy, color, and shape settings.", **scene_common)
    registry.register("world.configure", configure_world, description="Create, assign, and configure a scene world and Background node.", **scene_common)


__all__ = ["register_tools"]
