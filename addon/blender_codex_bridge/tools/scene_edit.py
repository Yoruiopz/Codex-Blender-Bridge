"""Structured scene, collection, camera, light, and world configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, get_object, require_blender, similar_names, vector3
from . import _scene_checkpoint_admission as checkpoint_admission
from . import _scene_collection_scope as collection_scope
from . import _scene_edit_profile as profile
from . import _scene_evaluation_scope as evaluation
from . import _scene_mutation as proof
from ._object_safety import require_local_editable_id, require_single_user_object_data

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
    focus_distance: float | None
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


@dataclass(slots=True)
class _CollectionOperation:
    scene: Any
    collection: Any
    boundary: proof.Boundary
    body: Any
    entered: bool = False

    def run(self) -> dict[str, Any]:
        if self.entered:
            raise proof.unsupported("A cached collection operation can enter its owned body only once.")
        self.entered = True
        return self.body()


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


def _settings_boundary(context: ToolContext, method: str, prepared: Any, *, checkpoint_authored: bool = False,
                       checkpoint_roles: Any = None) -> proof.Boundary:
    bpy = require_blender()
    proof.preflight_types(bpy)
    scene = prepared.scene if method == "scene.configure" else bpy.context.scene
    fields: dict[str, proof.Field] = {}
    if method == "scene.configure":
        fields = {field: proof.Field(lambda: scene, field) for field in ("camera", "use_gravity", "gravity")}
        fields.update({"units." + field: proof.Field(lambda: scene.unit_settings, field) for field in ("system", "scale_length")})
        scope = profile.Profile(bpy, scene, method, focus=prepared.camera, physics_sensitive=any(value is not None for value in (
            prepared.unit_system, prepared.unit_scale_length, prepared.use_gravity, prepared.gravity)),
            checkpoint_authored=checkpoint_authored, checkpoint_roles=checkpoint_roles)
    elif method == "camera.configure":
        obj = prepared.obj
        if prepared.active_scene is not None and prepared.active_scene != scene:
            raise proof.unsupported("Active camera assignment requires the actual current Scene.")
        fields = {field: proof.Field(lambda: obj.data, field) for field in profile.CAMERA_FIELDS}
        fields.update({"dof." + field: proof.Field(lambda: obj.data.dof, field) for field in profile.DOF_FIELDS})
        fields["active_camera"] = proof.Field(lambda: scene, "camera")
        scope = profile.Profile(bpy, scene, method, obj=obj, focus=prepared.focus_object, edit_data=bool(
            prepared.camera_type is not None or prepared.numeric or prepared.dof_enabled is not None
            or prepared.set_focus or prepared.focus_distance is not None or prepared.aperture_fstop is not None),
            checkpoint_authored=checkpoint_authored, checkpoint_roles=checkpoint_roles)
    else:
        obj = prepared.obj
        if prepared.light_type is not None and prepared.light_type != obj.data.type:
            raise proof.unsupported("Light subtype conversion needs a complete hidden-setting preservation proof; no type or settings are changed.")
        for field, _value in prepared.numeric:
            if obj.data.bl_rna.properties.get(field) is None:
                raise proof.unsupported("Requested shape setting is unavailable on this exact native Light subtype.", property=field)
        fields = {field: proof.Field(lambda: obj.data, field) for field in profile.LIGHT_FIELDS if obj.data.bl_rna.properties.get(field) is not None}
        scope = profile.Profile(bpy, scene, method, obj=obj, checkpoint_authored=checkpoint_authored,
                                checkpoint_roles=checkpoint_roles)
    return proof.Boundary(bpy, context, method, fields, scope)


def configure_scene(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    admitted = checkpoint_admission.cached(context, "scene.configure")
    prepared = admitted.prepared if admitted is not None else _prepare_scene(params)
    scene = prepared.scene
    require_local_editable_id(scene, operation="Scene configuration")
    boundary = admitted.boundary if admitted is not None else _settings_boundary(context, "scene.configure", prepared)
    try:
        if prepared.set_camera:
            boundary.write("camera", prepared.camera)
        if prepared.unit_system is not None:
            boundary.write("units.system", prepared.unit_system)
        if prepared.unit_scale_length is not None:
            boundary.write("units.scale_length", prepared.unit_scale_length)
        if prepared.use_gravity is not None:
            boundary.write("use_gravity", prepared.use_gravity)
        if prepared.gravity is not None:
            boundary.write("gravity", prepared.gravity)
        boundary.check()
        return {"configured": True, "verified": True, "preservation_scope": proof.preservation_scope(), **_scene_state(scene)}
    except Exception as error:
        raise boundary.failure(error) from error


def _collection_boundary(context: ToolContext, bpy: Any, scene: Any, method: str, read: Any,
                         collection_identity: Any, *, checkpoint_roles: Any = None) -> proof.Boundary:
    proof.preflight_types(bpy)
    static = evaluation.Scope(bpy, scene, method, collection_identity=collection_identity)
    authored = (None if checkpoint_roles is None else profile.Profile(
        bpy, scene, method, checkpoint_authored=True, checkpoint_roles=checkpoint_roles,
        collection_identity=collection_identity))
    def snapshot() -> Any:
        admitted = static()
        proof.current_scene(bpy, scene)
        return proof.session(bpy), proof.runtime(bpy), read(), admitted, None if authored is None else authored()
    return proof.Boundary(bpy, context, method, {}, snapshot)


def create_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    admitted = checkpoint_admission.cached(context, "collection.create")
    plan = admitted.prepared if admitted is not None else _prepare_collection_create(context, params)
    return plan.run()


def _prepare_collection_create(context: ToolContext, params: Mapping[str, Any], *, checkpoint_roles: Any = None) -> _CollectionOperation:
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
        raise invalid_argument("'parent_collection' must belong to the requested scene.")
    created, linked, created_state = None, False, None
    def read() -> Any:
        current = collection_scope.snapshot(bpy, scene, parent, operation="collection.create")
        if created is not None:
            if (bpy.data.collections.get(name) != created or created.name != name or len(created.objects) or len(created.children)
                    or proof.primitive(bpy, created) != created_state or bool(parent.children.get(name) == created) != linked):
                raise proof.unsupported("Owned collection allocation or publication was replaced; cleanup is refused.")
            collection_scope.snapshot(bpy, scene, created, operation="collection.create", allow_unlinked=not linked)
            if linked:
                current = collection_scope.without_owned_child(current, (proof.key(created), created.session_uid))
        elif bpy.data.collections.get(name) is not None:
            raise proof.unsupported("Collection publication name was acquired after preflight.")
        return current
    boundary = _collection_boundary(context, bpy, scene, "collection.create", read,
                                    lambda: None if created is None else proof.token(created), checkpoint_roles=checkpoint_roles)
    def execute() -> dict[str, Any]:
        nonlocal created, linked, created_state
        try:
            boundary.check()
            boundary.final()
            boundary.mark_native()
            boundary.retained_effects = [{"kind": "collection_allocation_attempt", "name": name}]
            created = bpy.data.collections.new(name)
            boundary.retained_effects = [{"kind": "collection_allocation", "name": name, "identity": proof.token(created), "linked": False}]
            if created.name != name or created.users or created.use_fake_user or len(created.objects) or len(created.children):
                raise proof.unsupported("Native collection constructor did not produce the reviewed empty allocation.")
            created_state = proof.primitive(bpy, created)
            checkpoint_admission.note_allocation(context, "collection.create", "collection", created)
            boundary.check()
            boundary.final()
            boundary.mark_native()
            try:
                parent.children.link(created)
            finally:
                linked = parent.children.get(name) == created
                boundary.retained_effects[0]["linked"] = linked
            if not linked:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Native collection link was not published.")
            boundary.check()
            return {"created": True, "verified": True, "preservation_scope": proof.preservation_scope(),
                    "collection": created.name, "parent_collection": parent.name, "scene": scene.name}
        except Exception as error:
            restored = False
            if created is not None:
                try:
                    boundary.check(delete=True)
                    boundary.final()
                    bpy.data.collections.remove(created)
                    created = None
                    linked = False
                    checkpoint_admission.note_allocation(context, "collection.create", "collection", None)
                    boundary.retained_effects = []
                    boundary.check()
                    restored = True
                except Exception:
                    pass
            raise boundary.failure(error, restoration_verified=restored) from error

    return _CollectionOperation(scene, None, boundary, execute)


def rename_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    admitted = checkpoint_admission.cached(context, "collection.rename")
    plan = admitted.prepared if admitted is not None else _prepare_collection_rename(context, params)
    return plan.run()


def _prepare_collection_rename(context: ToolContext, params: Mapping[str, Any], *, checkpoint_roles: Any = None) -> _CollectionOperation:
    bpy = require_blender()
    collection = _collection(_required_name(params, "collection_name"))
    new_name = _required_name(params, "new_name")[:63]
    collision = bpy.data.collections.get(new_name)
    if collision is not None and collision != collection:
        raise invalid_argument(f"Collection '{new_name}' already exists.")
    scene = bpy.context.scene
    if collection == scene.collection:
        raise proof.unsupported("The embedded Scene root cannot be renamed through collection tools.")
    old_name = expected_name = collection.name
    def read() -> Any:
        competing = bpy.data.collections.get(new_name)
        if expected_name == old_name and competing is not None and competing != collection:
            raise proof.unsupported("Collection rename destination was acquired after preflight.")
        return collection_scope.snapshot(bpy, scene, collection, operation="collection.rename", expected_name=expected_name)
    identity = proof.token(collection)
    boundary = _collection_boundary(context, bpy, scene, "collection.rename", read, lambda: identity,
                                    checkpoint_roles=checkpoint_roles)
    def execute() -> dict[str, Any]:
        nonlocal expected_name
        try:
            boundary.check()
            boundary.final()
            boundary.mark_native()
            collection.name = new_name
            expected_name = new_name
            boundary.check()
            return {"renamed": True, "verified": True, "preservation_scope": proof.preservation_scope(),
                    "old_name": old_name, "collection": collection.name}
        except Exception as error:
            restored = False
            if boundary.owned_started:
                try:
                    boundary.check()
                    if bpy.data.collections.get(old_name) not in (None, collection):
                        raise proof.unsupported("Old collection name was acquired; compensation is refused.")
                    boundary.final()
                    collection.name = old_name
                    expected_name = old_name
                    boundary.check()
                    restored = True
                except Exception:
                    pass
            raise boundary.failure(error, restoration_verified=restored) from error

    return _CollectionOperation(scene, collection, boundary, execute)


def delete_collection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    admitted = checkpoint_admission.cached(context, "collection.delete")
    plan = admitted.prepared if admitted is not None else _prepare_collection_delete(context, params)
    return plan.run()


def _prepare_collection_delete(context: ToolContext, params: Mapping[str, Any], *, checkpoint_roles: Any = None) -> _CollectionOperation:
    bpy = require_blender()
    collection = _collection(_required_name(params, "collection_name"))
    if not bool_param(params, "confirm_delete", False):
        raise invalid_argument("Set 'confirm_delete' to true to remove the explicitly scoped empty collection.")
    scene = bpy.context.scene
    if collection == scene.collection or len(collection.objects) or len(collection.children):
        raise proof.unsupported("Collection deletion currently admits only an empty ordinary collection; contents are never orphaned implicitly.")
    name, identity = collection.name, (proof.key(collection), collection.session_uid)
    candidates = (scene.collection, *proof.bounded(bpy.data.collections, 4096, "collections"))
    parents = [parent for parent in candidates if parent.children.get(name) == collection]
    if len(parents) != 1:
        raise proof.unsupported("Collection deletion requires one exact ordinary parent.")
    parent = parents[0]
    before_parent = collection_scope.snapshot(bpy, scene, parent, operation="collection.delete")
    expected_parent = collection_scope.without_owned_child(before_parent, identity)
    removed = False
    def read() -> Any:
        if removed:
            if bpy.data.collections.get(name) is not None:
                raise proof.unsupported("Removed collection name was acquired by newer data.")
            return "removed", identity, collection_scope.snapshot(bpy, scene, parent, operation="collection.delete")
        return "present", collection_scope.snapshot(bpy, scene, collection, operation="collection.delete")
    boundary = _collection_boundary(context, bpy, scene, "collection.delete", read, lambda: identity,
                                    checkpoint_roles=checkpoint_roles)
    predicted_profile = (*boundary.expected_profile[:2], ("removed", identity, expected_parent), *boundary.expected_profile[3:])
    def execute() -> dict[str, Any]:
        nonlocal removed
        try:
            boundary.check()
            boundary.final()
            boundary.mark_native()
            boundary.retained_effects = [{"kind": "collection_removal_attempt", "name": name, "identity": identity}]
            bpy.data.collections.remove(collection)
            if bpy.data.collections.get(name) is not None:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Collection deletion or context preservation could not be verified.")
            removed = True
            boundary.expected_profile = predicted_profile
            boundary.check()
            return {"deleted": True, "verified": True, "preservation_scope": proof.preservation_scope(),
                    "collection": name, "unlinked_objects": [], "unlinked_object_count": 0,
                    "unlinked_objects_truncated": False, "unlinked_children": [], "unlinked_child_count": 0,
                    "unlinked_children_truncated": False, "affected_objects": [], "automatic_rollback_available": False}
        except Exception as error:
            raise boundary.failure(error, restoration_verified=False) from error

    return _CollectionOperation(scene, collection, boundary, execute)


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
    focus_distance = (
        float_param(params, "focus_distance", float(camera.dof.focus_distance), minimum=0.0, maximum=1.0e9)
        if "focus_distance" in params else None
    )
    if focus_distance is not None:
        final_focus = params.get("focus_object") if set_focus else camera.dof.focus_object
        if final_focus is not None:
            raise invalid_argument("Manual 'focus_distance' requires no final focus object; explicitly clear an existing focus object.")
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
        focus_distance=focus_distance,
        aperture_fstop=aperture_fstop,
        active_scene=active_scene,
        set_active_for_scene=set_active_for_scene,
    )


def configure_camera(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    admitted = checkpoint_admission.cached(context, "camera.configure")
    prepared = admitted.prepared if admitted is not None else _prepare_camera(params)
    obj, camera = prepared.obj, prepared.camera
    if (prepared.camera_type is not None or prepared.numeric or prepared.dof_enabled is not None
            or prepared.set_focus or prepared.focus_distance is not None or prepared.aperture_fstop is not None):
        require_single_user_object_data(obj, operation="Camera configuration")
    if prepared.set_active_for_scene and prepared.active_scene is not None:
        require_local_editable_id(prepared.active_scene, operation="Active camera assignment")
    boundary = admitted.boundary if admitted is not None else _settings_boundary(context, "camera.configure", prepared)
    try:
        if prepared.camera_type is not None:
            boundary.write("type", prepared.camera_type)
        for name, value in prepared.numeric:
            boundary.write(name, value)
        if prepared.dof_enabled is not None:
            boundary.write("dof.use_dof", prepared.dof_enabled)
        if prepared.set_focus:
            boundary.write("dof.focus_object", prepared.focus_object)
        if prepared.focus_distance is not None:
            boundary.write("dof.focus_distance", prepared.focus_distance)
        if prepared.aperture_fstop is not None:
            boundary.write("dof.aperture_fstop", prepared.aperture_fstop)
        if prepared.set_active_for_scene and prepared.active_scene is not None:
            boundary.write("active_camera", obj)
        boundary.check()
        return {"configured": True, "verified": True, "preservation_scope": proof.preservation_scope(),
                "object": obj.name, "camera": camera.name,
                "camera_type": camera.type, "lens": float(camera.lens), "sensor_width": float(camera.sensor_width),
                "clip_start": float(camera.clip_start), "clip_end": float(camera.clip_end), "ortho_scale": float(camera.ortho_scale),
                "dof": {"enabled": bool(camera.dof.use_dof), "focus_object": camera.dof.focus_object.name if camera.dof.focus_object else None,
                        "focus_distance": float(camera.dof.focus_distance),
                        "aperture_fstop": float(camera.dof.aperture_fstop)}}
    except Exception as error:
        raise boundary.failure(error, affected=(obj.name,)) from error


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
    admitted = checkpoint_admission.cached(context, "light.configure")
    prepared = admitted.prepared if admitted is not None else _prepare_light(params)
    obj, light = prepared.obj, prepared.light
    if prepared.light_type is not None or prepared.energy is not None or prepared.color is not None or prepared.numeric:
        require_single_user_object_data(obj, operation="Light configuration")
    boundary = admitted.boundary if admitted is not None else _settings_boundary(context, "light.configure", prepared)
    try:
        if prepared.light_type is not None:
            boundary.write("type", prepared.light_type)
        if prepared.energy is not None:
            boundary.write("energy", prepared.energy)
        if prepared.color is not None:
            boundary.write("color", prepared.color)
        for name, value in prepared.numeric:
            boundary.write(name, value)
        boundary.check()
        return {"configured": True, "verified": True, "preservation_scope": proof.preservation_scope(),
                "object": obj.name, "light": light.name,
                "light_type": light.type, "energy": float(light.energy), "color": [float(value) for value in light.color],
                "shadow_soft_size": float(getattr(light, "shadow_soft_size", 0.0)), "spot_size": float(getattr(light, "spot_size", 0.0)),
                "spot_blend": float(getattr(light, "spot_blend", 0.0))}
    except Exception as error:
        raise boundary.failure(error, affected=(obj.name,)) from error


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


def _world_boundary(context: ToolContext, prepared: _PreparedWorld, holder: list[Any], *, checkpoint_authored: bool = False,
                    checkpoint_roles: Any = None) -> proof.Boundary:
    bpy, scene = prepared.bpy, prepared.scene
    proof.preflight_types(bpy)
    def socket(name: str) -> Any:
        node = profile.background(holder[0])
        return None if node is None else node.inputs.get(name)
    fields = {"scene_world": proof.Field(lambda: scene, "world"),
              "world_nodes": proof.Field(lambda: holder[0], "use_nodes"),
              "world_color": proof.Field(lambda: holder[0], "color"),
              "background_color": proof.Field(lambda: socket("Color"), "default_value"),
              "background_strength": proof.Field(lambda: socket("Strength"), "default_value")}
    editing = holder[0] is None or prepared.explicit_use_nodes is not None or prepared.color is not None or prepared.strength is not None
    scope = profile.Profile(bpy, scene, "world.configure", world_getter=lambda: holder[0], edit_world=editing,
                            checkpoint_authored=checkpoint_authored, checkpoint_roles=checkpoint_roles)
    return proof.Boundary(bpy, context, "world.configure", fields, scope)


def _default_world_graph(world: Any) -> None:
    node = profile.background(world)
    if node is None or node.name != "Background":
        raise proof.unsupported("Native World constructor did not produce the reviewed default Background.")
    expected_color = tuple(proof.canonical(node.inputs["Color"].bl_rna.properties["default_value"], (*world.color, 1.0)))
    if (tuple(node.inputs["Color"].default_value) != expected_color or node.inputs["Strength"].default_value != 1.0
            or tuple(node.location) != (-200.0, 100.0)):
        raise proof.unsupported("Native default World shader differs from its independently measured constructor contract.")
    output = next((item for item in world.node_tree.nodes if item.bl_rna.identifier == "ShaderNodeOutputWorld"), None)
    if output is None or output.name != "World Output" or tuple(output.location) != (200.0, 100.0):
        raise proof.unsupported("Native World Output differs from the reviewed constructor.")


def _admit_created_world(boundary: proof.Boundary, world: Any) -> None:
    bpy = boundary.bpy
    proof.descriptors(bpy, world)
    require_local_editable_id(world, operation="World allocation")
    default_color = tuple(proof.canonical(world.bl_rna.properties["color"], (.05, .05, .05)))
    has_graph = bpy.app.version >= (5, 0, 0)
    if (world.users or world.use_fake_user or world.animation_data is not None or tuple(world.color) != default_color
            or bool(world.use_nodes) != has_graph or (world.node_tree is not None) != has_graph or tuple(world.keys())):
        raise proof.unsupported("Native World constructor did not produce the reviewed empty/default allocation.")
    if has_graph:
        _default_world_graph(world)
    live_profile = boundary.profile()
    created_token = proof.token(world)
    if tuple(entry for entry in live_profile["worlds"] if entry[0] != created_token) != boundary.expected_profile["worlds"]:
        raise proof.unsupported("Existing World content changed while allocating an owned World.")
    if {key: val for key, val in live_profile.items() if key != "worlds"} != {key: val for key, val in boundary.expected_profile.items() if key != "worlds"}:
        raise proof.unsupported("Protected Scene data changed during World allocation.")
    predicted = {**boundary.expected, "world_nodes": has_graph, "world_color": default_color,
                 "background_color": (*default_color, 1.0) if has_graph else None,
                 "background_strength": 1.0 if has_graph else None}
    if boundary.read() != predicted:
        raise proof.unsupported("Owned World fields did not match their native constructor prediction.")
    boundary.expected_profile = live_profile
    boundary.expected = predicted


def _admit_world_graph(boundary: proof.Boundary, world: Any) -> None:
    _default_world_graph(world)
    live_profile = boundary.profile()
    old_entries = {entry[0]: entry for entry in boundary.expected_profile["worlds"]}
    current_entries = {entry[0]: entry for entry in live_profile["worlds"]}
    identity = proof.token(world)
    if set(old_entries) != set(current_entries) or old_entries[identity][3] is not None:
        raise proof.unsupported("Native World shader allocation changed an existing graph identity.")
    if current_entries[identity][:3] != old_entries[identity][:3] or any(current_entries[key] != entry for key, entry in old_entries.items() if key != identity):
        raise proof.unsupported("Native World shader allocation changed protected World data.")
    if {key: val for key, val in live_profile.items() if key != "worlds"} != {key: val for key, val in boundary.expected_profile.items() if key != "worlds"}:
        raise proof.unsupported("Protected Scene data changed during World shader allocation.")
    node = profile.background(world)
    expected_color = tuple(proof.canonical(node.inputs["Color"].bl_rna.properties["default_value"], (*world.color, 1.0)))
    boundary.expected_profile = live_profile
    boundary.expected = {**boundary.expected, "background_color": expected_color, "background_strength": 1.0}
    boundary.retained_effects.append({"kind": "embedded_world_graph_allocation", "world": world.name, "identity": proof.token(world.node_tree),
                                      "automatic_identity_restoration_available": False})


def _validate_world_prepared(prepared: _PreparedWorld) -> None:
    bpy, scene = prepared.bpy, prepared.scene
    world = prepared.world
    require_local_editable_id(scene, operation="World assignment")
    changes_world = prepared.explicit_use_nodes is not None or prepared.color is not None or prepared.strength is not None
    if world is not None and changes_world:
        require_local_editable_id(world, operation="World configuration")
        if world.node_tree is not None:
            require_local_editable_id(world.node_tree, operation="World node configuration")
        effective_users = int(world.users) - int(bool(world.use_fake_user))
        if effective_users > int(scene.world == world):
            raise proof.unsupported("World edits require sole ownership by the target Scene.")
    if prepared.explicit_use_nodes is False and prepared.strength is not None:
        raise invalid_argument("Background strength requires nodes; use_nodes=false cannot be combined with strength.")
    if prepared.explicit_use_nodes is False and bpy.app.version >= (5, 0, 0):
        raise proof.unsupported("Blender 5.x always enables native World nodes; disabling them is not a supported conversion.")


def configure_world(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    admitted = checkpoint_admission.cached(context, "world.configure")
    prepared = admitted.prepared if admitted is not None else _prepare_world(params)
    _validate_world_prepared(prepared)
    bpy, scene, world = prepared.bpy, prepared.scene, prepared.world
    created = world is None
    holder = admitted.holder if admitted is not None else [world]
    boundary = admitted.boundary if admitted is not None else _world_boundary(context, prepared, holder)
    initial_profile = boundary.expected_profile
    initial_values = dict(boundary.expected)
    allocated = False
    try:
        if world is None:
            if prepared.new_world_name is None:
                raise RuntimeError("Prepared World allocation has no name.")
            boundary.check()
            if bpy.data.worlds.get(prepared.new_world_name) is not None:
                raise proof.unsupported("World allocation name was acquired after preflight.")
            boundary.final()
            boundary.mark_native()
            boundary.retained_effects = [{"kind": "world_allocation_attempt", "name": prepared.new_world_name}]
            world = bpy.data.worlds.new(prepared.new_world_name)
            holder[0] = world
            allocated = True
            if world.name != prepared.new_world_name:
                raise proof.unsupported("World allocation name did not match its exact unused destination.")
            _admit_created_world(boundary, world)
            checkpoint_admission.note_allocation(context, "world.configure", "world", world)
            boundary.retained_effects = [{"kind": "world_allocation", "name": world.name, "identity": proof.token(world)}]
        if scene.world != world:
            boundary.write("scene_world", world)
        wanted_nodes = prepared.planned_use_nodes if prepared.explicit_use_nodes is not None or prepared.needs_background else None
        if wanted_nodes is not None and bool(world.use_nodes) != wanted_nodes:
            needs_graph = wanted_nodes and world.node_tree is None
            boundary.write("world_nodes", wanted_nodes,
                           after_native=(lambda: _admit_world_graph(boundary, world)) if needs_graph else None)
        if prepared.color is not None:
            boundary.write("world_color", prepared.color)
        if prepared.needs_background:
            if profile.background(world) is None:
                raise proof.unsupported("World has no reviewed connected Background node.")
            if prepared.color is not None:
                boundary.write("background_color", (*prepared.color, 1.0))
            if prepared.strength is not None:
                boundary.write("background_strength", prepared.strength)
        boundary.check()
        node = profile.background(world) if world.use_nodes else None
        return {"configured": True, "verified": True, "preservation_scope": proof.preservation_scope(),
                "created": created, "scene": scene.name, "world": world.name,
                "use_nodes": bool(world.use_nodes), "color": [float(channel) for channel in world.color],
                "background": {"color": list(node.inputs["Color"].default_value), "strength": float(node.inputs["Strength"].default_value)} if node is not None else None,
                "native_allocations": list(boundary.retained_effects), "recovery_evidence": boundary.evidence(False)}
    except Exception as error:
        restored = False
        try:
            restored = boundary.restore() if boundary.attempted else False
            if allocated:
                boundary.check(delete=True)
                if world.users or world.use_fake_user or scene.world == world:
                    raise proof.unsupported("Owned World acquired a consumer; allocation cleanup is refused.")
                boundary.final()
                bpy.data.worlds.remove(world)
                holder[0] = None
                checkpoint_admission.note_allocation(context, "world.configure", "world", None)
                if boundary.profile() != initial_profile or boundary.read() != initial_values:
                    raise proof.unsupported("World cleanup did not restore the exact protected Scene state.")
                boundary.expected_profile, boundary.expected = initial_profile, initial_values
                boundary.retained_effects = []
                boundary.check()
                restored = True
        except Exception:
            pass
        raise boundary.failure(error, restoration_verified=restored) from error


def register_tools(registry: ToolRegistry) -> None:
    scene_common = {
        "permissions": (Permission.EDIT_SCENE,),
        "toolset": "scene_edit",
        "modifies": True,
    }
    registry.register("scene.configure", configure_scene, checkpoint_admission_factory=partial(checkpoint_admission.factory, "scene.configure"), description="Configure an explicit scene's camera, units, and gravity.", **scene_common)
    registry.register("collection.create", create_collection, checkpoint_admission_factory=partial(checkpoint_admission.factory, "collection.create"), description="Create and link a collection under an explicit scene or parent.", **scene_common)
    registry.register("collection.rename", rename_collection, checkpoint_admission_factory=partial(checkpoint_admission.factory, "collection.rename"), description="Rename an explicit collection without collisions.", **scene_common)
    registry.register(
        "collection.delete",
        delete_collection,
        permissions=(Permission.EDIT_SCENE, Permission.DELETE_OBJECTS),
        toolset="scene_edit",
        checkpoint_admission_factory=partial(checkpoint_admission.factory, "collection.delete"),
        modifies=True,
        description="Remove an explicitly confirmed empty collection within the current Scene.",
    )
    registry.register("camera.configure", configure_camera, checkpoint_admission_factory=partial(checkpoint_admission.factory, "camera.configure"), description="Configure camera optics, clipping, depth of field, and active-scene assignment.", **scene_common)
    registry.register("light.configure", configure_light, checkpoint_admission_factory=partial(checkpoint_admission.factory, "light.configure"), description="Configure a named Blender light's energy, color, and supported settings within its current subtype.", **scene_common)
    registry.register("world.configure", configure_world, checkpoint_admission_factory=partial(checkpoint_admission.factory, "world.configure"), description="Create, assign, and configure a scene world and Background node.", **scene_common)


__all__ = ["register_tools"]
