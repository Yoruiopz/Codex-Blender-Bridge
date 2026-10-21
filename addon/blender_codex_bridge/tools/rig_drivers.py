"""Reviewed bone-transform drivers and bounded numeric control properties.

RNA paths are constructed from exact object/bone/property choices. Caller paths,
scripted expressions and dynamic dependency traversal are not accepted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import deque
from collections.abc import Mapping
from itertools import islice
from types import SimpleNamespace
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, int_param, reject_unknown_params, require_blender
from ._object_safety import require_local_editable_id, require_local_object
from .shader_scope import name

LOGGER = logging.getLogger(__name__)
CHANNELS = frozenset({"location", "rotation_euler", "scale"})
DRIVER_TYPES = frozenset({"AVERAGE", "SUM", "MIN", "MAX"})
TRANSFORMS = frozenset(f"{kind}_{axis}" for kind in ("LOC", "ROT", "SCALE") for axis in "XYZ")
SPACES = frozenset({"WORLD_SPACE", "LOCAL_SPACE", "TRANSFORM_SPACE"})
MAX_OBJECTS, MAX_BONES, MAX_DRIVERS, MAX_VARIABLES = 32, 256, 128, 8


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _gate(context: ToolContext) -> None:
    _check(context)
    flags = context.state.snapshot()
    if flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Rig control mutation emergency-stopped.")
    if flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Rig control mutation paused.")
    context.require(Permission.EDIT_ANIMATION)


def _key(owner: Any) -> int:
    return int(owner.as_pointer()) if hasattr(owner, "as_pointer") else id(owner)


def _object(bpy: Any, raw: Any) -> Any:
    exact = name(raw, "object_name")
    matches = list(islice((obj for obj in bpy.context.scene.objects if obj.name == exact), 2))
    if len(matches) != 1:
        raise invalid_argument("Object must resolve exactly in the current scene.", object_name=exact)
    return matches[0]


def _bone(obj: Any, raw: Any) -> Any:
    exact = name(raw, "bone_name")
    if obj.type != "ARMATURE" or getattr(obj, "pose", None) is None:
        raise invalid_argument("Bone controls require a named armature object.")
    if len(obj.pose.bones) > MAX_BONES:
        raise invalid_argument("Pose-bone scope exceeds 256 bones.")
    matches = list(islice((bone for bone in obj.pose.bones if bone.name == exact), 2))
    if len(matches) != 1:
        raise invalid_argument("Pose bone is missing or ambiguous.", bone_name=exact)
    return matches[0]


def _owner(bpy: Any, params: Mapping[str, Any], *, modify: bool) -> tuple[Any, Any, str | None]:
    obj = _object(bpy, params.get("object_name"))
    bone_name = params.get("bone_name")
    owner = obj if bone_name is None else _bone(obj, bone_name)
    if modify:
        if bpy.context.mode not in {"OBJECT", "POSE"}:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Rig control editing requires Object or Pose Mode.")
        require_local_object(obj, operation="Rig control editing")
        if bone_name is not None:
            require_local_editable_id(obj.data, operation="Rig control editing")
    return obj, owner, None if bone_name is None else owner.name


def _property_name(raw: Any) -> str:
    value = name(raw, "property_name")
    if value.startswith("_"):
        raise invalid_argument("Control property names cannot use the reserved underscore prefix.")
    return value


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e6 or not math.isfinite(value):
        raise invalid_argument("Numeric controls require a finite number with magnitude at most 1000000.")
    return value


def _bone_path(bone_name: str) -> str:
    return f"pose.bones[{json.dumps(bone_name, ensure_ascii=False)}]"


def _property_path(bone_name: str | None, key: str) -> str:
    return ("" if bone_name is None else _bone_path(bone_name)) + f"[{json.dumps(key, ensure_ascii=False)}]"


def _property_source(obj: Any, raw: str) -> tuple[str | None, str, Any]:
    """Decode a JSON-quoted property path, never evaluate or resolve caller RNA."""
    if not isinstance(raw, str) or len(raw) > 512:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing driver property path exceeds reviewed scope.")
    bone_name = None
    owner = obj
    suffix = raw
    if raw.startswith("pose.bones["):
        try:
            bone_name, end = json.JSONDecoder().raw_decode(raw, len("pose.bones["))
        except (ValueError, TypeError) as error:
            raise invalid_argument("Existing driver has an unsupported bone path.") from error
        if end >= len(raw) or raw[end] != "]":
            raise invalid_argument("Existing driver has an unsupported bone path.")
        owner = _bone(obj, bone_name)
        suffix = raw[end + 1:]
    try:
        key = _property_name(json.loads(suffix[1:-1])) if suffix.startswith("[") and suffix.endswith("]") else None
    except (ValueError, TypeError) as error:
        raise invalid_argument("Existing driver property path is outside the reviewed numeric-control scope.") from error
    if key is None or raw != _property_path(bone_name, key) or key not in owner:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing driver must reference one exact stored numeric control property.")
    _number(owner[key])
    return bone_name, key, owner


def _channel(params: Mapping[str, Any], obj: Any, bone: Any, *, validate_rotation: bool = False) -> tuple[str, int]:
    channel = params.get("channel")
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise invalid_argument("channel must be location, rotation_euler or scale.")
    if validate_rotation and channel == "rotation_euler" and bone.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
        raise invalid_argument("Euler driver targets require an Euler pose-bone rotation mode.")
    index = int_param(params, "index", 0, minimum=0, maximum=2)
    return _bone_path(bone.name) + "." + channel, index


def _curves(obj: Any) -> Any:
    return getattr(getattr(obj, "animation_data", None), "drivers", ())


def _curve(obj: Any, path: str, index: int) -> Any:
    matches = [curve for curve in _curves(obj) if curve.data_path == path and curve.array_index == index]
    if len(matches) > 1:
        raise invalid_argument("Driver channel is ambiguous.")
    return matches[0] if matches else None


def _target_unit(obj: Any, path: str) -> tuple[int, str | None]:
    if path in CHANNELS:
        return _key(obj), None
    for bone in getattr(getattr(obj, "pose", None), "bones", ()):
        if path in {_bone_path(bone.name) + "." + channel for channel in CHANNELS}:
            return _key(obj), bone.name
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing driver targets are outside reviewed object/bone transform channels.")


def _variable(context: ToolContext, bpy: Any, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("kind"), str) or raw.get("kind") not in {"PROPERTY", "TRANSFORM"}:
        raise invalid_argument("Each variable requires PROPERTY or TRANSFORM kind and explicit object/bone choices.")
    kind = raw["kind"]
    allowed = {"kind", "object_name", "bone_name", "property_name"} if kind == "PROPERTY" else {"kind", "object_name", "bone_name", "transform_type", "transform_space"}
    reject_unknown_params(raw, allowed)
    obj, owner, bone_name = _owner(bpy, raw, modify=False)
    require_local_object(obj, operation="Rig driver source inspection")
    if bone_name is not None:
        require_local_editable_id(obj.data, operation="Rig driver source inspection")
    _check(context)
    result = {"kind": kind, "object": obj, "bone_name": bone_name, "owner_token": _token(obj, owner)}
    if kind == "PROPERTY":
        key = _property_name(raw.get("property_name"))
        if key not in owner:
            raise invalid_argument("Create the exact numeric control property explicitly before adding a driver.")
        _number(owner[key])
        result.update(property_name=key, data_path=_property_path(bone_name, key))
    else:
        transform_type, space = raw.get("transform_type"), raw.get("transform_space", "TRANSFORM_SPACE")
        if not isinstance(transform_type, str) or transform_type not in TRANSFORMS or not isinstance(space, str) or space not in SPACES:
            raise invalid_argument("Transform variables require a reviewed location/rotation/scale component and native transform space.")
        result.update(transform_type=transform_type, transform_space=space)
    return result


def _dependencies(context: ToolContext, bpy: Any, seeds: list[Any], proposed: tuple[Any, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Conservative unit graph: transforms depend on parent units and driver transforms.

    Static numeric properties are leaves, distinct from their owner's transform.
    Unknown actions, constraints, modifiers and scripted/custom-path drivers fail closed.
    """
    pending = deque(seeds)
    seen: set[int] = set()
    edges: dict[tuple[int, str | None], set[tuple[int, str | None]]] = {}
    total_bones = total_drivers = 0
    reviewed: list[str] = []
    while pending:
        _check(context)
        obj = pending.popleft()
        identity = _key(obj)
        if identity in seen:
            continue
        if len(seen) >= MAX_OBJECTS:
            raise invalid_argument("Rig dependency scope exceeds 32 objects.")
        seen.add(identity)
        require_local_object(obj, operation="Rig driver dependency validation")
        reviewed.append(obj.name)
        if len(getattr(obj, "constraints", ())):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Constraint dependencies require a broader reviewed driver workflow.")
        data = getattr(obj, "animation_data", None)
        if data and (data.action is not None or len(data.nla_tracks) or data.use_tweak_mode):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Active actions, NLA and tweak mode are outside this driver dependency contract.")
        parent = getattr(obj, "parent", None)
        if parent is not None:
            if getattr(obj, "parent_type", "OBJECT") != "OBJECT":
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Bone/vertex object-parent dependencies are outside this driver contract.")
            edges.setdefault((identity, None), set()).add((_key(parent), None))
            pending.append(parent)
        bones = getattr(getattr(obj, "pose", None), "bones", ())
        if bones:
            require_local_editable_id(obj.data, operation="Rig driver dependency validation")
        total_bones += len(bones)
        if total_bones > MAX_BONES:
            raise invalid_argument("Rig dependency scope exceeds 256 pose bones.")
        for bone in bones:
            if len(bone.constraints):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Pose constraints require a broader reviewed driver workflow.")
            unit = (identity, bone.name)
            edges.setdefault(unit, set()).add((identity, None))
            if bone.parent is not None:
                edges[unit].add((identity, bone.parent.name))
        curves = _curves(obj)
        total_drivers += len(curves)
        if total_drivers > MAX_DRIVERS:
            raise invalid_argument("Rig dependency scope exceeds 128 drivers.")
        for curve in curves:
            _check(context)
            driver = curve.driver
            if (driver.type not in DRIVER_TYPES or driver.use_self or len(curve.modifiers)
                    or len(curve.keyframe_points) or len(curve.sampled_points)
                    or not 1 <= len(driver.variables) <= MAX_VARIABLES):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing drivers must be non-scripted reviewed transforms without modifiers/keyframes/self or oversized variable lists.")
            unit = _target_unit(obj, curve.data_path)
            if curve.array_index not in {0, 1, 2}:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing driver component is outside reviewed transform channels.")
            for variable in driver.variables:
                if variable.type not in {"SINGLE_PROP", "TRANSFORMS"} or len(variable.targets) != 1:
                    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing driver variables require one numeric property or transform source.")
                target = variable.targets[0]
                source = target.id
                if source is None or getattr(getattr(source, "bl_rna", None), "identifier", None) != "Object":
                    raise invalid_argument("Driver sources must be explicit object datablocks.")
                pending.append(source)
                if variable.type == "SINGLE_PROP":
                    _property_source(source, target.data_path)
                else:
                    if target.transform_type not in TRANSFORMS or target.transform_space not in SPACES:
                        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Existing driver transform settings are outside reviewed scope.")
                    source_bone = target.bone_target or None
                    if source_bone is not None:
                        _bone(source, source_bone)
                    edges.setdefault(unit, set()).add((_key(source), source_bone))
    if proposed is not None:
        target_unit, variables = proposed
        for item in variables:
            if item["kind"] == "TRANSFORM":
                edges.setdefault(target_unit, set()).add((_key(item["object"]), item["bone_name"]))
    # Iterative traversal keeps the finite graph from using Python's recursion stack.
    complete: set[tuple[int, str | None]] = set()
    for start in edges:
        if start in complete:
            continue
        active: set[tuple[int, str | None]] = set()
        stack = [(start, False)]
        while stack:
            unit, leaving = stack.pop()
            if leaving:
                active.remove(unit)
                complete.add(unit)
            elif unit not in complete:
                if unit in active:
                    raise invalid_argument("Driver would introduce or retain a transform/hierarchy dependency cycle.")
                active.add(unit)
                stack.append((unit, True))
                stack.extend((source, False) for source in edges.get(unit, ()))
    return {"reviewed_objects": reviewed, "bone_count": total_bones, "driver_count": total_drivers,
            "dependency_cycle_detected": False, "scope": "Reviewed object/bone transform dependencies and static numeric control leaves; no evaluated motion or full scene dependency certificate."}


def _consumers(context: ToolContext, bpy: Any, obj: Any) -> dict[str, Any]:
    direct = bpy.data.user_map(subset={obj}).get(obj, set())
    if len(direct) > 100:
        raise invalid_argument("Rig control direct-consumer scope exceeds 100 datablocks.")
    records = []
    for owner in direct:
        _check(context)
        require_local_editable_id(owner, operation="Rig control consumer validation")
        records.append({"name": owner.name, "type": getattr(getattr(owner, "bl_rna", None), "identifier", "unknown")})
    return {"direct_consumers": sorted(records, key=lambda item: (item["type"], item["name"])),
            "direct_consumers_complete": True, "transitive_consumers_verified": False}


def _result(obj: Any, bone_name: str | None, dependencies: dict[str, Any], consumers: dict[str, Any]) -> dict[str, Any]:
    affected = {obj.name, *(item["name"] for item in consumers["direct_consumers"] if item["type"] == "Object")}
    return {"object": obj.name, "bone_name": bone_name, "affected_objects": sorted(affected), "dependencies": dependencies,
            **consumers, "verification_required": True, "evaluated_motion_verified": False, "project_saved": False}


def _token(obj: Any, owner: Any) -> tuple[int, int, int | None]:
    data = getattr(obj, "data", None)
    return _key(obj), _key(owner), None if data is None else _key(data)


def _current_owner(bpy: Any, params: Mapping[str, Any], expected: tuple[int, int, int | None]) -> tuple[Any, Any]:
    obj, owner, _ = _owner(bpy, params, modify=True)
    if _token(obj, owner) != expected:
        raise invalid_argument("Rig control target identity changed; reinspect before retrying.")
    return obj, owner


def _validation_context(context: ToolContext) -> Any:
    # The caller has just run the final cancellation/consent gate. This bounded
    # reread must not invoke callbacks that could mutate the state being checked.
    return SimpleNamespace(check_cancelled=None, state=context.state, require=context.require)


def _property_matches(owner: Any, key: str, existed: bool, value: Any) -> bool:
    return (key in owner) is existed and (not existed or (type(owner[key]) is type(value) and owner[key] == value))


def _failed(error: Exception, message: str, *, restored: bool = False, **evidence: Any) -> BridgeError:
    return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED, message,
                       {"execution_started": True, "rollback_verified": restored, "possible_mutation": not restored,
                        "verification_required": True, **evidence})


def property_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "bone_name", "property_name"})
    bpy = require_blender()
    obj, owner, bone_name = _owner(bpy, params, modify=False)
    key = _property_name(params.get("property_name"))
    _check(context)
    return {"object": obj.name, "bone_name": bone_name, "property_name": key,
            "exists": key in owner, "value": _number(owner[key]) if key in owner else None,
            "scope": "One exact numeric object/pose-bone control, without evaluating dependencies."}


def property_set(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "bone_name", "property_name", "value", "create"})
    bpy = require_blender()
    obj, owner, bone_name = _owner(bpy, params, modify=True)
    key, value = _property_name(params.get("property_name")), _number(params.get("value"))
    create = bool_param(params, "create", False)
    existed = key in owner
    if not existed and not create:
        raise invalid_argument("Missing numeric controls require explicit create=true.")
    if len(owner.keys()) >= 128 and not existed:
        raise invalid_argument("Numeric control ownership exceeds 128 custom properties.")
    previous = _number(owner[key]) if existed else None
    token = _token(obj, owner)
    dependencies = _dependencies(context, bpy, [obj])
    consumers = _consumers(context, bpy, obj)
    _gate(context)
    _current_owner(bpy, params, token)
    if not _property_matches(owner, key, existed, previous):
        raise invalid_argument("Numeric control changed after inspection; reinspect before retrying.")
    validation = _validation_context(context)
    dependencies = _dependencies(validation, bpy, [obj])
    consumers = _consumers(validation, bpy, obj)
    try:
        owner[key] = value
        obj.update_tag()
        _gate(context)
        _current_owner(bpy, params, token)
        if key not in owner or _number(owner[key]) != value:
            raise RuntimeError("Numeric control readback mismatch")
        return {"property_name": key, "created": not existed, "previous_value": previous, "value": owner[key],
                **_result(obj, bone_name, dependencies, consumers)}
    except Exception as error:
        LOGGER.exception("Numeric rig control edit failed")
        restored = False
        try:
            context.require(Permission.EDIT_ANIMATION)
            _current_owner(bpy, params, token)
            if _property_matches(owner, key, existed, previous):
                restored = True
            elif not _property_matches(owner, key, True, value):
                raise invalid_argument("Control ownership/value changed after the write; automatic compensation skipped.")
            elif existed:
                owner[key] = previous
            elif key in owner:
                del owner[key]
            obj.update_tag()
            restored = (_number(owner[key]) == previous) if existed else key not in owner
        except Exception:
            LOGGER.exception("Numeric rig control recovery failed")
        raise _failed(error, "Rig control edit failed; inspect control/recovery evidence.", restored=restored) from error


def _driver_summary(curve: Any) -> dict[str, Any] | None:
    if curve is None:
        return None
    driver = curve.driver
    if len(driver.variables) > MAX_VARIABLES:
        raise invalid_argument("Driver inspection exceeds eight variables.")
    variables = []
    for variable in driver.variables:
        if len(variable.targets) > 2:
            raise invalid_argument("Driver target scope exceeds two targets per variable.")
        variables.append({"name": variable.name, "type": variable.type,
                          "targets": [{"object": getattr(target.id, "name", None), "bone_name": target.bone_target or None,
                                       "data_path": str(target.data_path)[:512], "data_path_truncated": len(str(target.data_path)) > 512,
                                       "transform_type": target.transform_type, "transform_space": target.transform_space,
                                       "rotation_mode": getattr(target, "rotation_mode", None)} for target in variable.targets]})
    return {"data_path": curve.data_path, "index": curve.array_index, "driver_type": driver.type,
            "muted": bool(curve.mute), "valid": bool(driver.is_valid), "variables": variables,
            "reviewed_driver_type": driver.type in DRIVER_TYPES,
            "modifier_count": len(curve.modifiers), "script_expression_returned": False}


def _driver_configuration(curve: Any) -> dict[str, Any]:
    result = _driver_summary(curve)
    if result is None:
        raise invalid_argument("Driver disappeared during ownership verification.")
    result.pop("valid")  # Native validity can change during dependency evaluation.
    expression = str(getattr(curve.driver, "expression", ""))
    if len(expression) > 4096:
        raise invalid_argument("Driver expression metadata exceeds its ownership-verification budget.")
    return {**result, "expression_sha256": hashlib.sha256(expression.encode()).hexdigest(),
            "use_self": bool(curve.driver.use_self), "keyframe_count": len(curve.keyframe_points),
            "sample_count": len(curve.sampled_points)}


def driver_inspect(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "bone_name", "channel", "index"})
    bpy = require_blender()
    obj, bone, bone_name = _owner(bpy, params, modify=False)
    if bone_name is None:
        raise invalid_argument("Bone driver inspection requires an explicit bone_name.")
    path, index = _channel(params, obj, bone)
    if len(_curves(obj)) > MAX_DRIVERS:
        raise invalid_argument("Driver inspection exceeds 128 curves.")
    _check(context)
    return {"object": obj.name, "bone_name": bone_name, "channel": params["channel"], "index": index,
            "driver": _driver_summary(_curve(obj, path, index)), "evaluation_verified": False}


def driver_add(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "bone_name", "channel", "index", "driver_type", "variables"})
    bpy = require_blender()
    obj, bone, bone_name = _owner(bpy, params, modify=True)
    if bone_name is None:
        raise invalid_argument("Bone driver targets require an explicit bone_name.")
    path, index = _channel(params, obj, bone, validate_rotation=True)
    kind = params.get("driver_type", "AVERAGE")
    raw_variables = params.get("variables")
    if not isinstance(kind, str) or kind not in DRIVER_TYPES or not isinstance(raw_variables, list) or not 1 <= len(raw_variables) <= MAX_VARIABLES:
        raise invalid_argument("Driver requires AVERAGE/SUM/MIN/MAX and one to eight explicit variables.")
    variables = [_variable(context, bpy, item) for item in raw_variables]
    dependencies = _dependencies(context, bpy, [obj, *[item["object"] for item in variables]], ((_key(obj), bone_name), variables))
    consumers = _consumers(context, bpy, obj)
    if len(_curves(obj)) >= MAX_DRIVERS or _curve(obj, path, index) is not None:
        raise invalid_argument("Target already has a driver or its driver capacity is exhausted.")
    curve = None
    curve_key = None
    owned_config = None
    token = _token(obj, bone)
    _gate(context)
    _current_owner(bpy, params, token)
    _channel(params, obj, bone, validate_rotation=True)
    if _curve(obj, path, index) is not None:
        raise invalid_argument("Driver channel changed after inspection; no existing curve is reused or overwritten.")
    validation = _validation_context(context)
    current_variables = [_variable(validation, bpy, item) for item in raw_variables]
    for old, current in zip(variables, current_variables, strict=True):
        if old["owner_token"] != current["owner_token"]:
            raise invalid_argument("Driver source identity changed after inspection; reinspect before retrying.")
    _dependencies(validation, bpy, [obj, *[item["object"] for item in current_variables]], ((_key(obj), bone_name), current_variables))
    _consumers(validation, bpy, obj)
    try:
        curve = obj.driver_add(path, index)
        curve_key = _key(curve)
        driver = curve.driver
        driver.type = kind
        driver.use_self = False
        # These belong only to the newly allocated curve, never an existing driver.
        for modifier in list(curve.modifiers):
            curve.modifiers.remove(modifier)
        for variable in list(driver.variables):
            driver.variables.remove(variable)
        for ordinal, item in enumerate(variables):
            variable = driver.variables.new()
            variable.name = f"v{ordinal}"
            variable.type = "SINGLE_PROP" if item["kind"] == "PROPERTY" else "TRANSFORMS"
            target = variable.targets[0]
            target.id = item["object"]
            if item["kind"] == "PROPERTY":
                target.data_path = item["data_path"]
            else:
                target.bone_target = item["bone_name"] or ""
                target.transform_type = item["transform_type"]
                target.transform_space = item["transform_space"]
        obj.update_tag()
        owned_config = _driver_configuration(curve)
        _gate(context)
        _current_owner(bpy, params, token)
        current_curve = _curve(obj, path, index)
        if current_curve is None or _key(current_curve) != curve_key or _driver_configuration(current_curve) != owned_config:
            raise invalid_argument("Driver ownership/configuration changed after allocation; reinspect before recovery.")
        if _curve(obj, path, index) != curve or curve.driver.type != kind or len(curve.driver.variables) != len(variables):
            raise RuntimeError("Bone driver readback mismatch")
        for ordinal, (observed, expected) in enumerate(zip(driver.variables, variables, strict=True)):
            target = observed.targets[0]
            if (observed.name != f"v{ordinal}" or target.id != expected["object"]
                    or observed.type != ("SINGLE_PROP" if expected["kind"] == "PROPERTY" else "TRANSFORMS")):
                raise RuntimeError("Bone driver variable readback mismatch")
            if expected["kind"] == "PROPERTY":
                if target.data_path != expected["data_path"]:
                    raise RuntimeError("Bone driver property path readback mismatch")
            elif (target.bone_target != (expected["bone_name"] or "") or target.transform_type != expected["transform_type"]
                  or target.transform_space != expected["transform_space"]):
                raise RuntimeError("Bone driver transform source readback mismatch")
        dependencies = _dependencies(validation, bpy, [obj])
        return {"added": True, "channel": params["channel"], "index": index, "driver": _driver_summary(curve),
                **_result(obj, bone_name, dependencies, consumers)}
    except Exception as error:
        LOGGER.exception("Bone driver creation failed")
        restored = False
        cleanup_skipped = False
        retained = path
        try:
            context.require(Permission.EDIT_ANIMATION)
            _current_owner(bpy, params, token)
            current_curve = _curve(obj, path, index)
            if current_curve is not None and (curve_key is None or _key(current_curve) != curve_key
                                              or owned_config is None or _driver_configuration(current_curve) != owned_config):
                cleanup_skipped = True
                retained = None  # This may be someone else's replacement; never suggest deleting it as ours.
                raise invalid_argument("Driver ownership/configuration changed; automatic cleanup skipped.")
            if current_curve is not None:
                obj.driver_remove(path, index)
            restored = _curve(obj, path, index) is None
            obj.update_tag()
        except Exception:
            LOGGER.exception("Bone driver cleanup failed")
        raise _failed(error, "Bone driver creation failed; inspect channel and recovery evidence.", restored=restored,
                      cleanup_skipped=cleanup_skipped, retained_driver_path=None if restored else retained,
                      retained_driver_index=None if restored or retained is None else index) from error


def driver_remove(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "bone_name", "channel", "index"})
    bpy = require_blender()
    obj, bone, bone_name = _owner(bpy, params, modify=True)
    if bone_name is None:
        raise invalid_argument("Bone driver removal requires an explicit bone_name.")
    path, index = _channel(params, obj, bone)
    dependencies = _dependencies(context, bpy, [obj])
    consumers = _consumers(context, bpy, obj)
    curve = _curve(obj, path, index)
    if curve is None:
        raise invalid_argument("The exact bone channel has no driver.")
    previous = _driver_summary(curve)
    token, curve_key, configuration = _token(obj, bone), _key(curve), _driver_configuration(curve)
    _gate(context)
    _current_owner(bpy, params, token)
    current = _curve(obj, path, index)
    if current is None or _key(current) != curve_key or _driver_configuration(current) != configuration:
        raise invalid_argument("Driver changed after inspection; no replacement curve is removed.")
    validation = _validation_context(context)
    _dependencies(validation, bpy, [obj])
    _consumers(validation, bpy, obj)
    try:
        if not obj.driver_remove(path, index):
            raise RuntimeError("Blender refused bone driver removal")
        obj.update_tag()
        _gate(context)
        _current_owner(bpy, params, token)
        if _curve(obj, path, index) is not None:
            raise RuntimeError("Bone driver removal readback mismatch")
        dependencies = _dependencies(validation, bpy, [obj])
        return {"removed": True, "channel": params["channel"], "index": index, "previous_driver": previous,
                **_result(obj, bone_name, dependencies, consumers)}
    except Exception as error:
        LOGGER.exception("Bone driver removal failed")
        raise _failed(error, "Bone driver removal failed; reinspect and recover the checkpoint if needed.") from error


TOOL_DATA = (
    ("rig.property_inspect", property_inspect, False, (Permission.INSPECT_SCENE,), "Inspect one exact numeric object or pose-bone control property."),
    ("rig.property_set", property_set, True, (Permission.EDIT_ANIMATION,), "Create or set an explicit bounded numeric rig control with dependency review."),
    ("rig.driver_inspect", driver_inspect, False, (Permission.INSPECT_SCENE,), "Inspect a driver on an exact pose-bone transform component."),
    ("rig.driver_add", driver_add, True, (Permission.EDIT_ANIMATION,), "Add a non-scripted pose-bone driver from reviewed numeric controls or transforms."),
    ("rig.driver_remove", driver_remove, True, (Permission.EDIT_ANIMATION,), "Remove one exact reviewed pose-bone transform driver."),
)


def register_tools(registry: ToolRegistry) -> None:
    for tool_name, handler, modifying, permissions, description in TOOL_DATA:
        registry.register(tool_name, handler, permissions=permissions, toolset="rigging", modifies=modifying, description=description)
