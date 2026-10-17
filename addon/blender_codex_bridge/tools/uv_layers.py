"""Explicit Object Mode UV-layer lifecycle, with no implicit mode changes."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, reject_unknown_params, require_blender
from ._mesh_safety import require_local_single_user_mesh
from .mesh import _id_name
from .uv import _mesh_object

MAX_LAYERS = 8
MAX_LOOPS = 200_000


def _object(params: Mapping[str, Any]) -> Any:
    _id_name(params.get("object_name"), "object_name")
    obj = _mesh_object(params)
    if obj.mode != "OBJECT" or require_blender().context.mode != "OBJECT":
        raise BridgeError(ErrorCode.INVALID_MODE, "UV-layer lifecycle requires Object Mode; no implicit mode switching is performed.")
    require_local_single_user_mesh(obj)
    if any(not getattr(data, "is_editable", True) for data in (obj, obj.data)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV-layer editing requires editable object and mesh data.")
    if len(obj.data.loops) > MAX_LOOPS or len(obj.data.uv_layers) > MAX_LAYERS:
        raise invalid_argument("UV-layer lifecycle exceeds its 200,000-corner / eight-layer budget.")
    return obj


def _state(obj: Any) -> dict[str, Any]:
    layers = obj.data.uv_layers
    return {"layers": [layer.name for layer in layers],
            "active": layers.active.name if layers.active else None,
            "render": next((layer.name for layer in layers if layer.active_render), None),
            "clone": next((layer.name for layer in layers if layer.active_clone), None)}


def _restore_flags(obj: Any, state: Mapping[str, Any]) -> None:
    layers = obj.data.uv_layers
    if state["active"] is not None:
        layers.active_index = list(layers.keys()).index(state["active"])
    for field, attribute in (("render", "active_render"), ("clone", "active_clone")):
        if state[field] is not None:
            setattr(layers[state[field]], attribute, True)


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def _layer(obj: Any, value: Any) -> Any:
    name = _id_name(value, "uv_layer")
    layer = obj.data.uv_layers.get(name)
    if layer is None:
        raise invalid_argument("The named UV layer does not exist.", uv_layer=name)
    return layer


def _unused(obj: Any, value: Any) -> str:
    name = _id_name(value, "new_name")
    if obj.data.uv_layers.get(name) is not None or any(obj.data.attributes.get(candidate) is not None
           for candidate in (name, f".pn.{name}", f".vs.{name}", f".es.{name}")):
        raise invalid_argument("The requested name is already used by a mesh attribute.", new_name=name)
    return name


def _result(obj: Any, before: Mapping[str, Any], *, changed: bool = True) -> dict[str, Any]:
    return {"object": obj.name, "affected_objects": [obj.name], "changed": changed,
            "before": dict(before), "after": _state(obj), "topology_changed": False,
            "selection_changed": False, "verification_required": True}


def _read_buffer(obj: Any, name: str, attribute: str, prop: str, width: int) -> list[Any]:
    values = [0.0 if width == 2 else False] * (len(obj.data.loops) * width)
    data = getattr(obj.data.uv_layers[name], attribute)
    if attribute == "uv" and len(data) != len(obj.data.loops):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV coordinate storage has an unsupported length.")
    if len(data):
        if len(data) != len(obj.data.loops):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV attribute has an unsupported storage length.")
        data.foreach_get(prop, values)
    return values


def _write_buffer(obj: Any, name: str, attribute: str, prop: str, values: list[Any]) -> None:
    data = getattr(obj.data.uv_layers[name], attribute)
    if len(data) == 0:
        if not any(values):
            return  # Absent optional boolean storage represents all-false values.
        if attribute != "pin":
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This UV selection storage cannot be initialized safely.")
        # 5.1 exposes .pin as a read-only collection but does not allocate its backing attribute.
        attribute_name = f".pn.{name}"
        if obj.data.attributes.get(attribute_name) is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV pin backing attribute has incompatible storage.")
        obj.data.attributes.new(name=attribute_name, type="BOOLEAN", domain="CORNER")
        data = obj.data.uv_layers[name].pin  # Attribute allocation can invalidate prior RNA wrappers.
    if len(data) != len(obj.data.loops):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "UV destination has an unsupported storage length.")
    data.foreach_set(prop, values)


def layer_create(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "new_name", "copy_from"})
    obj = _object(params)
    name = _unused(obj, params.get("new_name"))
    if len(obj.data.uv_layers) >= MAX_LAYERS:
        raise invalid_argument("A mesh may have at most eight UV layers through this tool.")
    source_name = params.get("copy_from")
    source = _layer(obj, source_name) if source_name is not None else None
    probe = source if source is not None else obj.data.uv_layers.active
    per_layer_selection = bool(probe is not None and hasattr(probe, "vertex_selection") and hasattr(probe, "edge_selection"))
    buffers = {}
    if source is not None:
        # Modern bulk collections avoid legacy MeshUVLoop per-corner RNA writes.
        for attribute, prop, width in (("uv", "vector", 2), ("pin", "value", 1),
                                       ("vertex_selection", "value", 1), ("edge_selection", "value", 1)):
            if attribute in {"vertex_selection", "edge_selection"} and not per_layer_selection:
                continue  # Blender 5.1 stores UV selection once on the mesh, not per layer.
            buffers[attribute] = (prop, width, _read_buffer(obj, source_name, attribute, prop, width))
    before = _state(obj)
    created_name = None
    _check(context)
    try:
        created = obj.data.uv_layers.new(name=name, do_init=False)
        created_name = created.name if created is not None else None
        if created_name != name:
            raise RuntimeError("Blender did not create the exact requested layer name")
        for attribute, (prop, width, values) in buffers.items():
            _write_buffer(obj, name, attribute, prop, values)
            if _read_buffer(obj, name, attribute, prop, width) != values:
                raise RuntimeError("UV-layer copy postcondition mismatch")
        per_layer_selection = hasattr(obj.data.uv_layers[name], "vertex_selection")
        _restore_flags(obj, before)
        _check(context)
    except Exception as error:
        logging.getLogger(__name__).exception("UV-layer creation failed on %s", obj.name)
        restored = False
        try:
            if created_name is not None:
                current = obj.data.uv_layers.get(created_name)
                if current is not None:
                    obj.data.uv_layers.remove(current)
            _restore_flags(obj, before)
            restored = _state(obj) == before
        except Exception:
            logging.getLogger(__name__).exception("UV-layer creation rollback failed")
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "UV-layer creation failed; inspect recovery evidence.",
                          {"object": obj.name, "execution_started": True, "verification_required": True,
                           "rollback_verified": restored, "rollback_scope": "layer inventory and activation flags"}) from error
    result = _result(obj, before)
    result.update({"created_layer": name, "copy_from": source_name,
                   "initialization": "COPY_UV_AND_PIN" if source_name is not None else "ZERO_UNPINNED",
                   "uv_selection_policy": ("COPY_PER_LAYER" if source_name is not None else "ZERO_PER_LAYER")
                   if per_layer_selection else "PRESERVE_MESH_GLOBAL"})
    return result


def layer_rename(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "new_name"})
    obj = _object(params)
    layer = _layer(obj, params.get("uv_layer"))
    old_name = layer.name
    name = _id_name(params.get("new_name"), "new_name")
    before = _state(obj)
    if name != old_name:
        _unused(obj, name)
        _check(context)
        try:
            layer.name = name
            if layer.name != name:
                raise RuntimeError("Blender renamed the layer unexpectedly")
        except Exception as error:
            logging.getLogger(__name__).exception("UV-layer rename failed")
            restored = False
            try:
                layer.name = old_name
                restored = _state(obj) == before
            except Exception:
                logging.getLogger(__name__).exception("UV-layer rename rollback failed")
            raise BridgeError(ErrorCode.OPERATION_FAILED, "UV-layer rename failed; inspect recovery evidence.",
                              {"execution_started": True, "verification_required": True, "rollback_verified": restored}) from error
    result = _result(obj, before, changed=name != old_name)
    result["warnings"] = ["Named references in materials, Geometry Nodes or other consumers are not rewritten; inspect them."]
    return result


def layer_activate(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "for_render", "for_clone"})
    render = bool_param(params, "for_render", False)
    clone = bool_param(params, "for_clone", False)
    obj = _object(params)
    layer = _layer(obj, params.get("uv_layer"))
    before = _state(obj)
    _check(context)
    try:
        obj.data.uv_layers.active_index = list(obj.data.uv_layers.keys()).index(layer.name)
        if render:
            layer.active_render = True
        if clone:
            layer.active_clone = True
    except Exception as error:
        logging.getLogger(__name__).exception("UV-layer activation failed")
        try:
            _restore_flags(obj, before)
        except Exception:
            logging.getLogger(__name__).exception("UV-layer activation rollback failed")
        raise BridgeError(ErrorCode.OPERATION_FAILED, "UV-layer activation failed; inspect recovery evidence.",
                          {"execution_started": True, "verification_required": True, "rollback_verified": _state(obj) == before}) from error
    return _result(obj, before, changed=_state(obj) != before)


def layer_remove(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"object_name", "uv_layer", "confirm_remove"})
    if not bool_param(params, "confirm_remove", False):
        raise invalid_argument("Set confirm_remove=true to acknowledge loss of this UV layer's coordinates, pins and selection.")
    obj = _object(params)
    layer = _layer(obj, params.get("uv_layer"))
    before = _state(obj)
    _check(context)
    obj.data.uv_layers.remove(layer)
    result = _result(obj, before)
    result["warnings"] = ["Layer data was removed; active/render/clone layers may fall back. Named consumers are not rewritten. Inspect or use snapshot recovery."]
    return result


def register_tools(registry: ToolRegistry) -> None:
    for name, handler, description in (
        ("uv.layer_create", layer_create, "Create a named zero UV layer or copy coordinates/pins in Object Mode; copy per-layer UV selection where available, preserve mesh-global selection otherwise."),
        ("uv.layer_rename", layer_rename, "Rename an Object Mode mesh UV layer without rewriting named consumers."),
        ("uv.layer_activate", layer_activate, "Explicitly select the active UV layer and optionally its render/clone roles in Object Mode."),
        ("uv.layer_remove", layer_remove, "Remove a named Object Mode UV layer only with explicit data-loss confirmation."),
    ):
        registry.register(name, handler, permissions=(Permission.EDIT_MESH,), toolset="uv", modifies=True, description=description)
