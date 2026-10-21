"""Scoped small cloth simulations with explicit in-memory point-cache baking."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import get_object, int_param, reject_unknown_params, require_blender
from ._mesh_safety import require_local_single_user_mesh
from ._object_safety import require_single_user_object_data
from ._object_scope import MutationGuard, datablock_identity
from ._rna import (
    apply_assignments,
    bounded_name,
    prepare_assignments,
    serialize_properties,
    settings_mapping,
)

SETTINGS = frozenset(
    {
        "quality",
        "mass",
        "air_damping",
        "tension_stiffness",
        "compression_stiffness",
        "shear_stiffness",
        "bending_stiffness",
        "tension_damping",
        "compression_damping",
        "shear_damping",
        "bending_damping",
        "vertex_group_mass",
        "pin_stiffness",
        "time_scale",
    }
)


def _object(params: Mapping[str, Any], modify: bool = False) -> Any:
    obj = get_object(params.get("object_name"), allow_active=False)
    if obj.type != "MESH" or obj.mode != "OBJECT":
        raise invalid_argument("Cloth tools require a mesh in Object Mode.")
    if modify:
        require_local_single_user_mesh(obj)
    return obj


def _modifier(obj: Any, params: Mapping[str, Any]) -> Any:
    name = bounded_name(params.get("modifier_name"), "modifier_name")
    modifier = obj.modifiers.get(name)
    if modifier is None or modifier.type != "CLOTH":
        raise invalid_argument("Named cloth modifier does not exist.")
    return modifier


def _snapshot(obj: Any, modifier: Any) -> dict[str, Any]:
    cache = modifier.point_cache
    return {
        "object": obj.name,
        "affected_objects": [obj.name],
        "modifier_name": modifier.name,
        "settings": serialize_properties(modifier.settings, SETTINGS),
        "cache": {
            "frame_start": cache.frame_start,
            "frame_end": cache.frame_end,
            "baked": cache.is_baked,
            "outdated": cache.is_outdated,
            "disk_cache": cache.use_disk_cache,
            "external": cache.use_external,
        },
    }


def inspect(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "modifier_name"})
    obj = _object(params)
    return _snapshot(obj, _modifier(obj, params))


def cloth_add(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "modifier_name"})
    obj = _object(params, True)
    name = bounded_name(params.get("modifier_name"), "modifier_name", maximum=63)
    if (
        len(name.encode("utf-8")) > 63
        or obj.modifiers.get(name)
        or len(obj.modifiers)
        or len(obj.data.vertices) > 2000
    ):
        raise invalid_argument(
            "Initial cloth workflow requires at most 2000 vertices and an empty modifier stack."
        )
    modifier = obj.modifiers.new(name, "CLOTH")
    modifier.settings.quality = 3
    return _snapshot(obj, modifier)


def configure(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "modifier_name", "settings"})
    obj = _object(params, True)
    modifier = _modifier(obj, params)
    if modifier.point_cache.is_baked:
        raise invalid_argument("Free the bake before changing simulation settings.")
    if modifier.point_cache.use_external or modifier.point_cache.use_disk_cache:
        raise invalid_argument("Only in-memory simulation caches can be configured.")
    settings = settings_mapping(params)
    if "quality" in settings and (
        type(settings["quality"]) is not int or not 1 <= settings["quality"] <= 5
    ):
        raise invalid_argument("Cloth quality must be an integer in [1,5].")
    if (
        settings.get("vertex_group_mass")
        and obj.vertex_groups.get(settings["vertex_group_mass"]) is None
    ):
        raise invalid_argument("Pin vertex group does not exist.")
    apply_assignments(
        modifier.settings,
        prepare_assignments(
            modifier.settings,
            settings,
            allowed=SETTINGS,
            object_pointers=frozenset(),
            bpy=require_blender(),
        ),
    )
    return _snapshot(obj, modifier)


def _cache_guard(bpy: Any, context: Any, obj: Any, modifier: Any, point_cache: Any):
    """Recheck consent and the complete owned target relationship after callbacks."""
    guard = MutationGuard(bpy, context, "simulation.cache")
    mesh = obj.data
    guard.remember(obj, bpy.data.objects)
    guard.remember(mesh, bpy.data.meshes)
    guard.remember(modifier, obj.modifiers)
    guard.remember(point_cache)

    def check():
        guard.check(objects=(obj,))
        require_single_user_object_data(obj, operation="simulation.cache")
        if (
            datablock_identity(obj.data) != datablock_identity(mesh)
            or datablock_identity(modifier.point_cache) != datablock_identity(point_cache)
            or len(obj.modifiers) != 1
            or modifier.type != "CLOTH"
            or len(mesh.vertices) > 2000
            or modifier.settings.quality > 5
            or point_cache.use_external
            or point_cache.use_disk_cache
            or bpy.context.view_layer.objects.get(obj.name) != obj
            or obj.hide_get()
            or not obj.visible_get()
        ):
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Cloth/cache ownership, memory-only budget or visibility changed; no further writes are allowed.",
                {"object": obj.name, "scope_complete": False},
            )

    return check


def cache(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(
        params, {"object_name", "modifier_name", "operation", "frame_start", "frame_end"}
    )
    obj = _object(params, True)
    modifier = _modifier(obj, params)
    operation = params.get("operation")
    if not isinstance(operation, str) or operation not in {"BAKE", "FREE"}:
        raise invalid_argument("operation must be BAKE or FREE.")
    start = int_param(params, "frame_start", 1, minimum=1, maximum=100_000)
    end = int_param(params, "frame_end", 10, minimum=1, maximum=100_000)
    if (
        end < start
        or end - start > 31
        or len(obj.data.vertices) > 2000
        or len(obj.modifiers) != 1
        or modifier.settings.quality > 5
    ):
        raise invalid_argument(
            "Memory-bake budget: one cloth modifier, <=2000 vertices, <=32 frames, quality <=5."
        )
    point_cache = modifier.point_cache
    if point_cache.use_external or point_cache.use_disk_cache:
        raise invalid_argument(
            "Only in-memory caches are supported; external/disk caches are not touched."
        )
    if operation == "BAKE" and point_cache.is_baked:
        raise invalid_argument("Cache is already baked; explicitly FREE it first.")
    bpy = require_blender()
    if (
        bpy.context.view_layer.objects.get(obj.name) != obj
        or obj.hide_get()
        or not obj.visible_get()
    ):
        raise invalid_argument("Simulation object must be visible in the current view layer.")
    check = _cache_guard(bpy, context, obj, modifier, point_cache)
    try:
        check()
    except BridgeError as error:
        error.context.update(execution_started=False, possible_mutation=False)
        raise
    scene = bpy.context.scene
    frame, subframe = scene.frame_current, scene.frame_subframe
    old_range = (point_cache.frame_start, point_cache.frame_end)
    owned_range = old_range
    execution_started = cache_started = range_started = False
    failure: Exception | None = None
    range_recovery: dict[str, Any] = {"attempted": False}
    try:
        if operation == "BAKE":
            for name, value in (("frame_start", start), ("frame_end", end)):
                check()
                if (point_cache.frame_start, point_cache.frame_end) != owned_range:
                    raise RuntimeError("Cache range changed outside the current operation")
                if point_cache.is_baked:
                    raise RuntimeError("Another bake appeared before a range write")
                execution_started = range_started = True
                setattr(point_cache, name, value)
                owned_range = (point_cache.frame_start, point_cache.frame_end)
        with bpy.context.temp_override(
            scene=scene, object=obj, active_object=obj, point_cache=point_cache
        ):
            operator = bpy.ops.ptcache.bake if operation == "BAKE" else bpy.ops.ptcache.free_bake
            if not operator.poll():
                raise invalid_argument("Point-cache operator is unavailable in this context.")
            check()
            if (point_cache.frame_start, point_cache.frame_end) != owned_range:
                raise RuntimeError("Cache range changed before native execution")
            if operation == "BAKE" and point_cache.is_baked:
                raise RuntimeError("Another bake appeared before native execution")
            execution_started = cache_started = True
            result = operator(bake=True) if operation == "BAKE" else operator()
        check()
        if (point_cache.frame_start, point_cache.frame_end) != owned_range:
            raise RuntimeError("Cache range changed during native execution")
        if "FINISHED" not in result or point_cache.is_baked != (operation == "BAKE"):
            raise RuntimeError("Point-cache operation did not reach the requested state")
    except Exception as exc:
        failure = exc
        try:
            if not point_cache.is_baked and range_started:
                check()
                if (point_cache.frame_start, point_cache.frame_end) != owned_range:
                    raise RuntimeError("Newer cache range is retained instead of overwritten")
                range_recovery["attempted"] = True
                for name, value in zip(("frame_start", "frame_end"), old_range, strict=True):
                    check()
                    if (point_cache.frame_start, point_cache.frame_end) != owned_range:
                        raise RuntimeError("Cache range changed before recovery")
                    setattr(point_cache, name, value)
                    owned_range = (point_cache.frame_start, point_cache.frame_end)
                range_recovery["verified"] = (
                    point_cache.frame_start, point_cache.frame_end
                ) == old_range
        except Exception as restoration_error:
            range_recovery.update(verified=False, error_type=type(restoration_error).__name__)
    # Frame restoration can itself fail (for example in a frame-change handler).
    # Measure it independently so it cannot mask a bake/free failure or success.
    frame_recovery: dict[str, Any] = {"attempted": False, "verified": False}
    try:
        observed_frame = (scene.frame_current, scene.frame_subframe)
        check()
        if (scene.frame_current, scene.frame_subframe) != observed_frame:
            raise RuntimeError("Newer frame context is retained instead of overwritten")
        if cache_started:
            frame_recovery["attempted"] = True
            scene.frame_set(frame, subframe=subframe)
        check()
        frame_recovery["verified"] = (
            scene.frame_current == frame and scene.frame_subframe == subframe
        )
    except Exception as restoration_error:
        frame_recovery["error_type"] = type(restoration_error).__name__
    if failure is not None or not frame_recovery["verified"]:
        raise BridgeError(
            failure.code if isinstance(failure, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Point-cache operation or frame restoration failed; inspect before retrying.",
            {
                "object": obj.name,
                "operation": operation,
                "execution_started": execution_started,
                "possible_mutation": execution_started,
                "cache_operation_started": cache_started,
                "verification_required": True,
                "cache_operation_verified": failure is None,
                "primary_error_type": type(failure).__name__ if failure else None,
                "primary_error_code": failure.code if isinstance(failure, BridgeError) else None,
                "range_recovery": range_recovery,
                "frame_recovery": frame_recovery,
                "cache_recovery": "explicit FREE; baked caches are not guaranteed recoverable by global undo",
            },
        ) from failure
    return {
        "operation": operation,
        "cache_recovery": "explicit FREE; no durable backup or transactional undo",
        "frame_restored": frame_recovery["verified"],
        "frame_recovery": frame_recovery,
        "verification_required": True,
        "cache_coverage": "NOT_ASSESSED; baked flag is not complete simulation evidence",
        **_snapshot(obj, modifier),
    }


def register_tools(registry: Any) -> None:
    for name, handler in (
        ("inspect", inspect),
        ("cloth_add", cloth_add),
        ("configure", configure),
        ("cache", cache),
    ):
        permissions = (
            (Permission.INSPECT_SCENE,)
            if name == "inspect"
            else (Permission.EDIT_MESH, Permission.EDIT_SCENE)
        )
        if name == "cache":
            permissions += (Permission.EDIT_ANIMATION,)
        registry.register(
            f"simulation.{name}",
            handler,
            toolset="simulation",
            modifies=name != "inspect",
            permissions=permissions,
            description=f"Scoped cloth simulation {name}; no disk bakes.",
        )
