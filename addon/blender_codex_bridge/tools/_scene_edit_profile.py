"""Bounded literal Scene/camera/light/World projections for guarded setters."""

from __future__ import annotations

from typing import Any

from ..checkpoints import MARKER_KEY
from . import _scene_collection_scope as collections
from . import _scene_evaluation_scope as evaluation
from . import _scene_mutation as proof
from ._object_safety import require_local_editable_id

SCENE_FIELDS = frozenset({"camera", "use_gravity", "gravity"})
UNIT_FIELDS = frozenset({"system", "scale_length"})
CAMERA_FIELDS = frozenset({"type", "lens", "sensor_width", "clip_start", "clip_end", "ortho_scale"})
CAMERA_DERIVED = frozenset({"angle", "angle_x", "angle_y"})
DOF_FIELDS = frozenset({"use_dof", "focus_object", "focus_distance", "aperture_fstop"})
LIGHT_FIELDS = frozenset({"type", "energy", "color", "shadow_soft_size", "spot_size", "spot_blend"})
WORLD_FIELDS = frozenset({"use_nodes", "color"})


def _unanimated(owner: Any) -> None:
    if owner.animation_data is not None:
        raise proof.unsupported("Animated target data requires a separately reviewed Scene mutation closure.")


def graph(bpy: Any, world: Any, *, mutable: bool, light: bool = False) -> tuple[Any, ...] | None:
    tree = world.node_tree
    if tree is None:
        return None
    proof.descriptors(bpy, tree)
    require_local_editable_id(tree, operation="World graph mutation")
    _unanimated(tree)
    # Loaded factory trees have zero users; 4.5's newly initialized embedded
    # tree retains one constructor user. Neither appears in user_map. Match
    # the independent owner reference and reject every external consumer.
    expected_users = {0} if bpy.app.version >= (5, 0, 0) else {0, 1}
    if not tree.is_embedded_data or tree.users not in expected_users or world.user_of_id(tree) != 1:
        raise proof.unsupported("World graph must remain its exact embedded, unshared native tree.")
    direct = proof.bounded(bpy.data.user_map(subset={tree}).get(tree, ()), 128, "embedded shader users")
    if direct:
        raise proof.unsupported("Embedded shader tree acquired an unexplained native consumer.")
    nodes = proof.bounded(tree.nodes, 2, "World graph nodes")
    links = proof.bounded(tree.links, 1, "World graph links")
    kinds = {node.bl_rna.identifier for node in nodes}
    source_kind, output_kind, socket_name = ("ShaderNodeEmission", "ShaderNodeOutputLight", "Emission") if light else ("ShaderNodeBackground", "ShaderNodeOutputWorld", "Background")
    if len(nodes) != 2 or kinds != {source_kind, output_kind} or len(links) != 1:
        raise proof.unsupported("World configuration currently requires one built-in Background connected to one World Output.")
    records = []
    background, output = None, None
    for node in nodes:
        proof.descriptors(bpy, node)
        if node.bl_rna.identifier == source_kind:
            background = node
        else:
            output = node
        if node.parent is not None or node.mute:
            raise proof.unsupported("Parented or muted World nodes need a wider preservation contract.")
        sockets = []
        for direction in ("inputs", "outputs"):
            for socket in proof.bounded(getattr(node, direction), 8, "World sockets"):
                proof.descriptors(bpy, socket)
                if socket.bl_rna.identifier not in {"NodeSocketColor", "NodeSocketFloat", "NodeSocketShader"}:
                    raise proof.unsupported("World socket type is outside the reviewed native graph.")
                owned = mutable and node.bl_rna.identifier == "ShaderNodeBackground" and direction == "inputs" and socket.identifier in {"Color", "Strength"}
                sockets.append((direction, proof.key(socket), socket.identifier,
                                proof.primitive(bpy, socket, exclude=frozenset({"default_value"}) if owned else frozenset())))
        records.append((proof.key(node), node.bl_rna.identifier, proof.primitive(bpy, node), tuple(sockets)))
    link = links[0]
    if (link.from_node != background or link.from_socket.identifier != socket_name or link.to_node != output
            or link.to_socket.identifier != "Surface" or link.is_muted or not output.is_active_output):
        raise proof.unsupported("World Background must feed the active native World Output Surface directly.")
    return (proof.token(tree), int(tree.users), proof.primitive(bpy, tree), proof.key(tree.nodes.active), tuple(records),
            (proof.key(link), proof.key(link.from_socket), proof.key(link.to_socket)))


def background(world: Any) -> Any | None:
    tree = None if world is None else world.node_tree
    if tree is None:
        return None
    return next((node for node in tree.nodes if node.bl_rna.identifier == "ShaderNodeBackground"), None)


def _world_users(bpy: Any, scene: Any, world: Any, *, editing: bool) -> Any:
    require_local_editable_id(world, operation="World mutation")
    direct = proof.bounded(bpy.data.user_map(subset={world}).get(world, ()), 128, "World users")
    foreign = []
    total = 0
    for owner in direct:
        proof.descriptors(bpy, owner)
        count = int(owner.user_of_id(world))
        if owner.bl_rna.identifier != "Scene" or owner.world != world or count != 1:
            raise proof.unsupported("World has an unreviewed non-Scene or extra datablock consumer.")
        total += count
        if owner != scene:
            foreign.append((proof.token(owner), owner.name, count))
    if total != int(world.users) - int(bool(world.use_fake_user)):
        raise proof.unsupported("World native users do not match complete Scene bindings.")
    if editing and foreign:
        raise proof.unsupported("World edits require sole ownership by the actual target Scene.")
    if int(scene.user_of_id(world)) != int(scene.world == world):
        raise proof.unsupported("Scene holds unreviewed references to the World.")
    return tuple(sorted(foreign)), bool(world.use_fake_user)


def _object_users(bpy: Any, scene: Any, obj: Any, camera: Any | None) -> Any:
    incoming = proof.bounded(bpy.data.user_map(subset={obj}).get(obj, ()), 128, "Object users")
    containers = tuple(proof.bounded(obj.users_collection, 32, "Object collections"))
    expected = {proof.key(collection): 1 for collection in containers}
    roots = int(scene.collection.objects.get(obj.name) == obj)
    bases = sum(layer.objects.get(obj.name) == obj for layer in proof.bounded(scene.view_layers, 256, "view layers"))
    known_scene = roots + bases + int(scene.camera == obj)
    particle = scene.tool_settings.particle_edit
    proof.descriptors(bpy, particle)
    known_scene += int(particle.object == obj)
    if known_scene:
        expected[proof.key(scene)] = known_scene
    if camera is not None and camera.dof.focus_object == obj:
        expected[proof.key(camera)] = 1
    actual = {proof.key(owner): int(owner.user_of_id(obj)) for owner in incoming}
    if actual != expected or len(actual) != len(incoming):
        raise proof.unsupported("Object has consumers outside reviewed Scene membership and owned camera bindings.")
    # Scene.camera and CameraDOF.focus_object are native weak references on both
    # reviewed versions: user_map counts them, Object.users does not.
    real_users = len(containers)
    if int(obj.users) - int(bool(obj.use_fake_user)) != real_users:
        raise proof.unsupported("Object native user counts include unreviewed references.")
    return tuple(sorted(proof.token(collection) for collection in containers)), bool(obj.use_fake_user)


class Profile:
    def __init__(self, bpy: Any, scene: Any, method: str, *, obj: Any = None, focus: Any = None,
                 world: Any = None, world_getter: Any = None, edit_data: bool = True, edit_world: bool = False,
                 physics_sensitive: bool = False, checkpoint_authored: bool = False,
                 checkpoint_roles: Any = None, collection_identity: Any = None):
        self.bpy, self.scene, self.method = bpy, scene, method
        self.obj, self.focus, self.world = obj, focus, world
        self.world_getter = world_getter
        self.edit_data, self.edit_world = edit_data, edit_world
        self.physics_sensitive = physics_sensitive
        self.checkpoint_authored = checkpoint_authored
        self.checkpoint_roles = checkpoint_roles
        self.evaluation = evaluation.Scope(bpy, scene, method, world_getter=world_getter,
                                           new_world=method == "world.configure" and world_getter is not None and world_getter() is None,
                                           edit_world=edit_world, collection_identity=collection_identity)
        self.previous_world = scene.world if method == "world.configure" else None
        objects = [owner for owner in (obj, focus) if owner is not None]
        if obj is not None and obj.type == "CAMERA" and obj.data.dof.focus_object is not None:
            objects.append(obj.data.dof.focus_object)
        self.objects = tuple({proof.key(owner): owner for owner in objects}.values())

    def __call__(self) -> dict[str, Any]:
        bpy, scene = self.bpy, self.scene
        proof.preflight_types(bpy)
        static = self.evaluation()
        if self.physics_sensitive:
            evaluation.require_no_physics(bpy)
        proof.current_scene(bpy, scene)
        proof.runtime(bpy)
        scene_exclude = SCENE_FIELDS if self.method == "scene.configure" else frozenset({"camera"}) if self.method == "camera.configure" else frozenset({"world"}) if self.method == "world.configure" else frozenset()
        scene_settings = proof.primitive(bpy, scene, exclude=scene_exclude)
        if self.checkpoint_authored:
            # Only this exact actual checkpoint Scene's reserved slot is owned
            # by CheckpointManager's marker CAS. All other custom data remains.
            scene_settings = scene_settings[0], tuple(item for item in scene_settings[1] if item[0] != MARKER_KEY)
        result = {"evaluation": static, "session": proof.session(bpy), "scene": (proof.token(scene), scene_settings),
                  "units": proof.primitive(bpy, scene.unit_settings, exclude=UNIT_FIELDS if self.method == "scene.configure" else frozenset()),
                  "runtime": proof.runtime(bpy), "scene_references": (proof.references(bpy, (scene,))
                    if self.checkpoint_roles is None else self.checkpoint_roles.references())}
        object_records = []
        camera = self.obj.data if self.obj is not None and self.obj.type == "CAMERA" else None
        for obj in self.objects:
            evaluation.require_plain_object(bpy, obj)
            require_local_editable_id(obj, operation="Scene mutation Object")
            if (bpy.data.objects.get(obj.name) != obj or tuple(obj.users_scene) != (scene,)
                    or bpy.context.view_layer.objects.get(obj.name) != obj or obj.mode != "OBJECT"):
                raise proof.unsupported("Scene mutation Objects must remain in the actual current Scene/view layer.")
            membership = tuple(collections.snapshot(bpy, scene, collection, operation=self.method) for collection in obj.users_collection)
            object_records.append((proof.token(obj), proof.primitive(bpy, obj), _object_users(bpy, scene, obj, camera), membership))
        result["objects"] = tuple(sorted(object_records))
        if self.obj is not None:
            obj, data = self.obj, self.obj.data
            proof.descriptors(bpy, data)
            require_local_editable_id(data, operation="Camera/light mutation")
            _unanimated(data)
            storage = bpy.data.cameras if obj.type == "CAMERA" else bpy.data.lights
            if storage.get(data.name) != data:
                raise proof.unsupported("Camera/light native storage binding changed.")
            if self.edit_data:
                users = proof.bounded(bpy.data.user_map(subset={data}).get(data, ()), 128, "camera/light users")
                if users != (obj,) or obj.user_of_id(data) != 1 or int(data.users) - int(bool(data.use_fake_user)) != 1:
                    raise proof.unsupported("Camera/light edits require an exact sole Object data consumer.")
            exclude = CAMERA_FIELDS | CAMERA_DERIVED if obj.type == "CAMERA" else LIGHT_FIELDS
            result["data"] = (proof.token(data), proof.primitive(bpy, data, exclude=exclude), bool(data.use_fake_user))
            if obj.type == "CAMERA":
                result["dof"] = (proof.key(data.dof), proof.primitive(bpy, data.dof, exclude=DOF_FIELDS))
            else:
                result["light_graph"] = graph(bpy, data, mutable=False, light=True)
        requested = self.world_getter() if self.world_getter is not None else self.world
        worlds = {proof.key(owner): owner for owner in (requested, self.previous_world) if owner is not None}
        world_records = []
        for world in worlds.values():
            proof.descriptors(bpy, world)
            _unanimated(world)
            if bpy.data.worlds.get(world.name) != world:
                raise proof.unsupported("World native storage binding changed.")
            editing = self.edit_world and world == requested
            world_records.append((proof.token(world), proof.primitive(bpy, world, exclude=WORLD_FIELDS if editing else frozenset()),
                                  _world_users(bpy, scene, world, editing=editing), graph(bpy, world, mutable=editing)))
        result["worlds"] = tuple(sorted(world_records))
        return result
