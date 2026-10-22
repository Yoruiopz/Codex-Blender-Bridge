"""Live-guarded implementation behind the compatible object transform driver API."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import partial
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..utils import int_param, reject_unknown_params, require_blender
from . import _animation_scope as scope
from . import rig_drivers as rig

LOGGER = logging.getLogger(__name__)


def _context(context: Any) -> None:
    if context is None or not all(hasattr(context, field) for field in ("require", "state", "check_cancelled")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Driver mutation requires a live permission/state context.")


def _target(bpy: Any, params: Mapping[str, Any]) -> tuple[Any, str, int]:
    obj, _, _ = rig._owner(bpy, params, modify=True)
    scope.object_scope(bpy, obj)
    path = params.get("data_path")
    if not isinstance(path, str) or path not in rig.CHANNELS:
        raise invalid_argument("data_path must be location, rotation_euler or scale.")
    if path == "rotation_euler" and obj.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
        raise invalid_argument("Euler rotation drivers require an Euler rotation mode.")
    return obj, path, int_param(params, "index", 0, minimum=0, maximum=2)


def _sources(bpy: Any, obj: Any, raw: Any) -> tuple[Any, ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
        raise invalid_argument("variables must contain 1-8 transform sources.")
    prepared = []
    for variable in raw:
        if not isinstance(variable, Mapping) or set(variable) != {"object_name", "transform_type", "transform_space"}:
            raise invalid_argument("Each variable requires object_name, transform_type and transform_space.")
        if (not all(isinstance(value, str) for value in variable.values())
                or variable["transform_type"] not in rig.TRANSFORMS or variable["transform_space"] not in rig.SPACES):
            raise invalid_argument("Unsupported transform channel or space.")
        source = rig._object(bpy, variable["object_name"])
        scope.object_scope(bpy, source)
        if source == obj or source.parent is not None or len(source.constraints) or source.animation_data is not None:
            raise invalid_argument("Driver sources must be distinct independent objects without animation/drivers/constraints.")
        prepared.append((source, variable["transform_type"], variable["transform_space"], rig._token(source, source)))
    return tuple(prepared)


def _siblings(obj: Any, owned: Any) -> tuple[Any, ...]:
    return tuple((rig._key(curve), rig._driver_configuration(curve)) for curve in scope.bounded(rig._curves(obj), 128, "protected driver curves")
                 if owned is None or rig._key(curve) != rig._key(owned))


def add(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "data_path", "index", "driver_type", "variables"})
    _context(context)
    bpy = require_blender()
    obj, path, index = _target(bpy, params)
    kind = params.get("driver_type", "AVERAGE")
    if not isinstance(kind, str) or kind not in rig.DRIVER_TYPES:
        raise invalid_argument("Only non-scripted AVERAGE, SUM, MIN and MAX drivers are supported.")
    if len(rig._curves(obj)) >= 128 or rig._curve(obj, path, index) is not None:
        raise invalid_argument("Target already has a driver or driver capacity is exhausted.")
    sources = _sources(bpy, obj, params.get("variables"))
    dependencies = rig._dependencies(context, bpy, [obj, *[item[0] for item in sources]])
    consumers = rig._consumers(context, bpy, obj)
    siblings = _siblings(obj, None)
    boundary = rig._MutationBoundary(bpy, context, params, obj, obj, "drivers.add")
    validation = rig._validation_context(context)
    curve, curve_id, expected, data_id = None, None, None, scope.key(obj.animation_data)
    mapping_reviewed, started = False, False

    def fresh() -> None:
        boundary.check()
        if _target(bpy, params)[0] != obj or _sources(bpy, obj, params["variables"]) != sources:
            raise invalid_argument("Driver target/source scope changed; further writes refused.")
        data = obj.animation_data
        if scope.key(data) != data_id or (data is not None and (data.action is not None or len(data.nla_tracks) or data.use_tweak_mode)):
            raise invalid_argument("Driver owner animation context changed; further writes refused.")
        current = rig._curve(obj, path, index)
        if curve is None:
            if current is not None:
                raise invalid_argument("Driver channel changed before allocation; existing data is preserved.")
        elif current is None or rig._key(current) != curve_id or rig._driver_configuration(current) != expected:
            raise invalid_argument("Owned driver configuration changed; setup and compensation refused.")
        if _siblings(obj, curve) != siblings:
            raise invalid_argument("Protected driver channels changed; setup and compensation refused.")
        rig._dependencies(validation, bpy, [obj, *[item[0] for item in sources]], ignored_curve=curve)

    def write(operation: Any) -> Any:
        nonlocal expected
        fresh()
        try:
            return operation()
        finally:
            current = rig._curve(obj, path, index)
            if current is not None and rig._key(current) == curve_id:
                expected = rig._driver_configuration(current)

    fresh()
    had_data = obj.animation_data is not None
    try:
        started = True
        curve = obj.driver_add(path, index)
        curve_id, data_id = rig._key(curve), scope.key(obj.animation_data)
        boundary.owned_curve = curve
        expected = rig._driver_configuration(curve)
        removed_keys = write(partial(rig._normalize_new_driver_mapping, curve))
        mapping_reviewed = True
        driver = curve.driver
        write(partial(setattr, driver, "type", kind))
        write(partial(setattr, driver, "use_self", False))
        for modifier in list(curve.modifiers):
            write(partial(curve.modifiers.remove, modifier))
        for variable in list(driver.variables):
            write(partial(driver.variables.remove, variable))
        for ordinal, (source, transform, space, _) in enumerate(sources):
            variable = write(driver.variables.new)
            write(partial(setattr, variable, "name", f"source_{ordinal}"))
            write(partial(setattr, variable, "type", "TRANSFORMS"))
            target = variable.targets[0]
            write(partial(setattr, target, "id", source))
            write(partial(setattr, target, "transform_type", transform))
            write(partial(setattr, target, "transform_space", space))
        fresh()
        obj.update_tag()
        fresh()
        bpy.context.view_layer.update()
        fresh()
        dependencies = rig._dependencies(validation, bpy, [obj, *[item[0] for item in sources]])
        return {"added": True, "native_mapping_keyframes_removed": removed_keys,
                **rig._result(obj, None, dependencies, consumers)}
    except Exception as error:
        LOGGER.exception("Legacy object driver creation failed")
        restored, cleanup_skipped = False, False
        retained = path
        try:
            fresh()
            if not mapping_reviewed:
                cleanup_skipped = True
                raise invalid_argument("Unexpected native mapping retained for inspection.")
            obj.driver_remove(path, index)
            boundary.owned_curve = None
            curve = None
            fresh()
            obj.update_tag()
            fresh()
            restored = had_data and rig._curve(obj, path, index) is None
            retained = None
        except Exception:
            LOGGER.exception("Legacy object driver cleanup refused or failed")
            try:
                current = rig._curve(obj, path, index)
                if current is not None and (curve_id is None or rig._key(current) != curve_id or expected is None
                                            or rig._driver_configuration(current) != expected):
                    cleanup_skipped, retained = True, None
            except Exception:
                cleanup_skipped, retained = True, None
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Object driver creation failed; inspect retained channel and finalized checkpoint.",
                          {"execution_started": started, "possible_mutation": started and not restored, "rollback_verified": restored,
                           "cleanup_skipped": cleanup_skipped, "retained_driver_path": None if restored else retained,
                           "retained_driver_index": None if restored or retained is None else index,
                           "retained_empty_anim_data": not had_data and rig._empty_animation_data(obj),
                           "verification_required": True}) from error


def remove(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "data_path", "index"})
    _context(context)
    bpy = require_blender()
    obj, path, index = _target(bpy, params)
    curve = rig._curve(obj, path, index)
    if curve is None:
        raise invalid_argument("Driver does not exist on the named channel.")
    curve_id, expected = rig._key(curve), rig._driver_configuration(curve)
    siblings = _siblings(obj, curve)
    data_id = scope.key(obj.animation_data)
    dependencies = rig._dependencies(context, bpy, [obj], ignored_curve=curve)
    consumers = rig._consumers(context, bpy, obj)
    boundary = rig._MutationBoundary(bpy, context, params, obj, obj, "drivers.remove")
    boundary.owned_curve = curve
    boundary.consumers = rig._consumer_signature(bpy, obj, owned_curve=curve)
    validation = rig._validation_context(context)
    boundary.check()
    current = rig._curve(obj, path, index)
    if (current is None or rig._key(current) != curve_id or rig._driver_configuration(current) != expected
            or scope.key(obj.animation_data) != data_id or _siblings(obj, curve) != siblings):
        raise invalid_argument("Driver channel/container changed before removal; replacement data is preserved.")
    rig._dependencies(validation, bpy, [obj], ignored_curve=curve)
    try:
        if not obj.driver_remove(path, index):
            raise RuntimeError("Blender refused exact object driver removal")
        boundary.owned_curve = None
        boundary.check()
        if rig._curve(obj, path, index) is not None or _siblings(obj, None) != siblings:
            raise invalid_argument("Driver removal poststate differs from the scoped channel removal.")
        obj.update_tag()
        boundary.check()
        return {"removed": True, **rig._result(obj, None, dependencies, consumers)}
    except Exception as error:
        raise rig._failed(error, "Object driver removal could not be verified; reinspect before retrying.") from error
