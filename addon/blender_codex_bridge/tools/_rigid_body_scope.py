"""Bounded whole-world rigid-body evidence; snapshots are not recovery backups."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from . import _animation_scope as evidence
from . import _rigid_evaluation_scope as evaluation
from . import _rigid_snapshot_scope as snapshot_scope
from ._object_rna_mutation import _scene_reference, object_state
from ._object_safety import require_local_editable_id, require_single_user_object_data
from .shader_scope import name

MAX_BODIES = 16
MAX_VERTICES = 2048
MAX_FRAMES = 32
MAX_SCENE_OBJECTS = 256
CACHE_FIELDS = ("frame_start", "frame_end", "frame_step", "is_baked", "is_baking",
                "is_outdated", "is_frame_skip", "use_disk_cache", "use_external",
                "use_library_path", "filepath", "name", "index", "info")
VOLATILE_CACHE = frozenset({"is_baked", "is_baking", "is_outdated", "is_frame_skip", "info"})
RANGE_FIELDS = frozenset({"frame_start", "frame_end"})
HANDLERS = ("frame_change_pre", "frame_change_post", "depsgraph_update_pre", "depsgraph_update_post")


def bounded(items: Any, maximum: int, label: str) -> list[Any]:
    return evidence.bounded(items, maximum, f"rigid-body {label}")


def token(owner: Any) -> tuple[Any, ...]:
    return evidence.action_token(owner)


def _kind(owner: Any) -> str:
    return str(getattr(getattr(owner, "bl_rna", None), "identifier", type(owner).__name__))


def cache_state(cache: Any) -> dict[str, Any]:
    return {field: evidence.value(getattr(cache, field)) for field in CACHE_FIELDS if hasattr(cache, field)}


def current_scene(bpy: Any, scene_name: Any) -> Any:
    exact = name(scene_name, "scene_name")
    scene = bpy.context.scene
    if scene.name != exact or bpy.data.scenes.get(exact) != scene:
        raise invalid_argument("scene_name must resolve exactly to the actual current Scene.")
    window = getattr(bpy.context, "window", None)
    if window is None or window.scene != scene or window.view_layer != bpy.context.view_layer:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Rigid-body execution requires the actual window's current Scene and view layer.")
    return scene


def context_state(bpy: Any) -> Any:
    ctx = bpy.context
    selected = tuple(sorted(token(obj) for obj in bounded(ctx.selected_objects, MAX_SCENE_OBJECTS, "selection")))
    return (token(ctx.scene), evidence.key(ctx.view_layer), evidence.key(ctx.window), bpy.data.filepath,
            ctx.mode, selected, token(ctx.view_layer.objects.active))


def time_state(scene: Any) -> tuple[int, float]:
    return int(scene.frame_current), float(scene.frame_subframe)


def explicit_names(raw: Any, parameter: str, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) > maximum:
        raise invalid_argument(f"{parameter} must explicitly list at most {maximum} names.")
    values = tuple(name(item, parameter) for item in raw)
    if len(set(values)) != len(values):
        raise invalid_argument(f"{parameter} must not repeat names.")
    return tuple(sorted(values))


def _members(collection: Any, label: str) -> tuple[Any, ...]:
    if collection is None:
        return ()
    return tuple(sorted(bounded(collection.all_objects, MAX_BODIES, label), key=lambda obj: obj.name))


def inventory(bpy: Any, scene: Any) -> dict[str, Any]:
    world = scene.rigidbody_world
    if world is None:
        return {"scene": scene.name, "world_present": False, "body_names": [], "constraint_names": [],
                "scope_complete": False, "unsupported_reasons": ["NO_RIGID_BODY_WORLD"], "truncated": False}
    bodies, constraints = _members(world.collection, "world bodies"), _members(world.constraints, "world constraints")
    ids = {scene, *(obj for obj in bodies), *(obj.data for obj in bodies if obj.data is not None)}
    ids.update(item for item in (world.collection, world.constraints) if item is not None)
    users = bpy.data.user_map(subset=ids)
    owners = []
    for owner in sorted(ids, key=lambda item: (_kind(item), item.name)):
        direct = bounded(users.get(owner, ()), 64, "direct ID consumers")
        owners.append({"name": owner.name, "type": _kind(owner), "identity": token(owner),
                       "users": int(owner.users), "local_editable": owner.library is None and owner.override_library is None and bool(owner.is_editable),
                       "direct_users": [{"name": item.name, "type": _kind(item), "references": int(item.user_of_id(owner))}
                                        for item in sorted(direct, key=lambda item: (_kind(item), item.name))]})
    return {"scene": scene.name, "world_present": True,
            "world_collection": getattr(world.collection, "name", None),
            "constraint_collection": getattr(world.constraints, "name", None),
            "body_names": [obj.name for obj in bodies], "constraint_names": [obj.name for obj in constraints],
            "bodies": [{"name": obj.name, "type": obj.type, "rigid_body_type": getattr(obj.rigid_body, "type", None),
                        "collision_shape": getattr(obj.rigid_body, "collision_shape", None),
                        "vertices": len(obj.data.vertices) if obj.type == "MESH" else None} for obj in bodies],
            "constraints": [{"name": obj.name, "type": getattr(obj.rigid_body_constraint, "type", None)} for obj in constraints],
            "owners": owners, "cache": cache_state(world.point_cache), "truncated": False}


def _unanimated(owner: Any) -> None:
    if getattr(owner, "animation_data", None) is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body lifecycle requires unanimated inputs; Action, NLA and driver dependencies need a broader proven closure.")


def _collection_references(bpy: Any, scene: Any, body_collection: Any, constraint_collection: Any) -> Any:
    """Initial explicit native subset: two independent direct children of the Scene root."""
    root = scene.collection
    require_local_editable_id(root, operation="Rigid-body lifecycle")
    if len(scene.view_layers) != 1 or scene.view_layers[0] != bpy.context.view_layer:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The initial native-proven rigid-body scope requires one actual current view layer.")
    collections = (body_collection, constraint_collection)
    if body_collection is None or constraint_collection is None or body_collection == constraint_collection:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body scope requires distinct explicit body and constraint collections.")
    root_children = bounded(root.children, 128, "Scene root collections")
    records = []
    for collection in collections:
        require_local_editable_id(collection, operation="Rigid-body lifecycle")
        _unanimated(collection)
        if collection not in root_children or len(collection.children):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body scope currently requires flat body/constraint collections directly under the current Scene root.")
        direct = bounded(bpy.data.user_map(subset={collection}).get(collection, ()), 64, "collection consumers")
        # Native 4.5/5.2 expose three references from this one Scene: root
        # membership, its one view-layer collection and the rigid world.
        # Only two contribute to collection.users. The independent counters
        # and exact sole consumer must all match; neither alone proves scope.
        if len(direct) != 1 or token(direct[0]) != token(scene) or int(scene.user_of_id(collection)) != 3:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body collection has shared, instanced or unexplained consumers.", {"collection": collection.name, "scope_complete": False})
        if int(collection.users)-int(bool(collection.use_fake_user)) != 2:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body collection native users do not match its root and whole-world references.")
        records.append((token(collection), evidence.rna_state(collection), int(collection.users), bool(collection.use_fake_user),
                        tuple(token(obj) for obj in bounded(collection.objects, MAX_BODIES, "direct collection bodies")),
                        tuple((token(owner), int(owner.user_of_id(collection))) for owner in direct)))
    return token(root), tuple(token(child) for child in root_children), tuple(records)


def _object_references(bpy: Any, scene: Any, bodies: tuple[Any, ...]) -> Any:
    users = bpy.data.user_map(subset=set(bodies))
    records = []
    for obj in bodies:
        incoming = bounded(users.get(obj, ()), 64, "body consumers")
        membership = tuple(bounded(obj.users_collection, 8, "body memberships"))
        if membership != (scene.rigidbody_world.collection,):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Every body must belong only to the explicit whole-world body collection.")
        if tuple(obj.users_scene) != (scene,) or bpy.context.view_layer.objects.get(obj.name) != obj:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Every body must belong only to the actual current Scene and view layer.")
        for owner in incoming:
            count = int(owner.user_of_id(obj))
            if owner == membership[0] and count == 1:
                role = ("BODY_MEMBERSHIP",)
            else:
                role = _scene_reference(bpy, scene, owner, obj)
                if role is None:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "A rigid body has an external or unexplained consumer.", {"object": obj.name, "scope_complete": False})
            records.append((token(obj), token(owner), count, role))
        data_users = bounded(bpy.data.user_map(subset={obj.data}).get(obj.data, ()), 8, "body mesh consumers")
        if len(data_users) != 1 or data_users[0] != obj or int(obj.user_of_id(obj.data)) != 1:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body mesh has unexplained native consumers.")
    return tuple(sorted(records))


def _scene_inputs(bpy: Any, scene: Any, bodies: tuple[Any, ...]) -> Any:
    objects = bounded(scene.objects, MAX_SCENE_OBJECTS, "Scene objects")
    world = scene.rigidbody_world
    for obj in objects:
        if obj.rigid_body is not None and obj not in bodies:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Scene has rigid-body objects outside the declared world collection.")
        if getattr(getattr(obj, "field", None), "type", "NONE") != "NONE":
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Force-field dependencies require a separately proven rigid-body scope.")
        _unanimated(obj)
        if obj.data is not None:
            _unanimated(obj.data)
            keys = getattr(obj.data, "shape_keys", None)
            if keys is not None:
                _unanimated(keys)
        if obj not in bodies and (len(obj.modifiers) or len(obj.constraints) or obj.parent is not None or getattr(obj, "rigid_body_constraint", None) is not None):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Other Scene objects with modifiers or constraints require an evaluation scope beyond this initial whole-world subset.")
    handlers = bpy.app.handlers
    if any(len(getattr(handlers, field)) for field in HANDLERS):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Frame/dependency-graph handlers prevent a closed rigid-body evaluation contract.")
    if world.effector_weights.collection is not None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Effector collection dependencies require a separately proven scope.")
    incoming = bounded(bpy.data.user_map(subset={scene}).get(scene, ()), 64, "Scene consumers")
    # Native undo_push initializes a non-evaluated Scene's runtime original ID
    # to itself. user_map then exposes one loopback reference, without changing
    # real users. This is checkpoint bookkeeping, not a new external consumer.
    # Normalize only that measured exact self/original/extra-user combination;
    # custom or other extra Scene references still fail their count checks.
    loopbacks = [owner for owner in incoming if token(owner) == token(scene)]
    if loopbacks and (len(loopbacks) != 1 or int(scene.user_of_id(scene)) != 1
                      or scene.original != scene or scene.is_evaluated or not scene.use_extra_user):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Scene has an unexplained self-reference beyond native checkpoint bookkeeping.")
    external = [owner for owner in incoming if token(owner) != token(scene)]
    if (len(external) != 1 or external[0] != bpy.context.window_manager or _kind(external[0]) != "WindowManager"
            or int(external[0].user_of_id(scene)) != 1 or int(scene.users)-int(bool(scene.use_fake_user)) != 1):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The simulation Scene has external consumers outside the current window context.")
    render = scene.render
    return (tuple((token(obj), obj.type, token(getattr(obj, "rigid_body", None))) for obj in objects),
            tuple((token(owner), int(owner.user_of_id(scene))) for owner in external),
            evidence.value(scene.gravity), bool(scene.use_gravity),
            int(scene.frame_start), int(scene.frame_end), int(scene.frame_step), int(render.fps), evidence.value(float(render.fps_base)),
            evidence.rna_state(scene.unit_settings), evidence.rna_state(world.effector_weights), evaluation.snapshot(bpy))


def snapshot(bpy: Any, scene: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Read complete initial supported dependency scope without invoking providers."""
    require_local_editable_id(scene, operation="Rigid-body lifecycle")
    _unanimated(scene)
    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.INVALID_MODE, "Rigid-body lifecycle requires Object Mode without switching context.")
    world = scene.rigidbody_world
    if world is None or not bool(world.enabled):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "An enabled whole-world rigid-body setup is required.")
    bodies, constraints = _members(world.collection, "world bodies"), _members(world.constraints, "world constraints")
    body_names = explicit_names(params.get("body_names"), "body_names", maximum=MAX_BODIES)
    constraint_names = explicit_names(params.get("constraint_names"), "constraint_names", maximum=MAX_BODIES)
    if tuple(obj.name for obj in bodies) != body_names or tuple(obj.name for obj in constraints) != constraint_names:
        raise invalid_argument("Explicit names must match every body and constraint in the whole world; inspect again.")
    if not bodies or constraints:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The initial rigid-body lifecycle needs 1-16 bodies and no constraints; constraints remain an open native-proof target.")
    if not 1 <= world.substeps_per_frame <= 4 or not 1 <= world.solver_iterations <= 8 or not .1 <= world.time_scale <= 1.:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body solver budget requires 1-4 substeps, 1-8 iterations and time scale 0.1-1.")
    cache = world.point_cache
    if cache.use_disk_cache or cache.use_external or cache.is_baking or cache.frame_step != 1:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body lifecycle currently requires an idle memory-only step-one cache; disk/external caches remain unproven.")
    vertices = 0
    for obj in bodies:
        if obj.type != "MESH" or obj.mode != "OBJECT" or obj.rigid_body is None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Every declared world member must be an Object Mode mesh with a native rigid body.")
        require_single_user_object_data(obj, operation="Rigid-body lifecycle")
        _unanimated(obj)
        _unanimated(obj.data)
        if (len(obj.modifiers) or len(obj.constraints) or obj.parent is not None or len(obj.children)
                or obj.data.shape_keys is not None or getattr(obj, "rigid_body_constraint", None) is not None):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Initial rigid bodies require independent unmodified meshes without parenting, constraints or shape keys.")
        if obj.rigid_body.type not in {"ACTIVE", "PASSIVE"} or obj.rigid_body.collision_shape != "BOX" or obj.rigid_body.kinematic:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Initial rigid bodies require proven active/passive BOX collisions without animated kinematic bodies.")
        if not obj.visible_get() or obj.hide_get():
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "All rigid bodies must be visible in the actual current view layer.")
        vertices += len(obj.data.vertices)
    if vertices > MAX_VERTICES:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rigid-body lifecycle exceeds 2048 total base vertices.")
    snapshot_scope.preflight(bpy, scene, bodies)
    collections = _collection_references(bpy, scene, world.collection, world.constraints)
    references = _object_references(bpy, scene, bodies)
    scene_inputs = _scene_inputs(bpy, scene, bodies)
    controls = cache_state(cache)
    protected = (context_state(bpy), token(scene), evidence.key(world), evidence.key(cache), collections, references,
                 scene_inputs, evidence.rna_state(world, exclude=frozenset({"time_scale"})),
                 tuple((object_state(obj, exclude_object_rna=snapshot_scope.IGNORED_OBJECT_RUNTIME), evidence.rna_state(obj.rigid_body)) for obj in bodies),
                 tuple((field, value) for field, value in controls.items() if field not in VOLATILE_CACHE | RANGE_FIELDS))
    return {"protected": protected, "owned": {"frame": time_state(scene), "time_scale": float(world.time_scale),
                                               "range": (int(cache.frame_start), int(cache.frame_end))},
            "cache_status": tuple((field, value) for field, value in controls.items() if field in VOLATILE_CACHE),
            "body_names": body_names, "constraint_names": constraint_names, "base_vertices": vertices}
