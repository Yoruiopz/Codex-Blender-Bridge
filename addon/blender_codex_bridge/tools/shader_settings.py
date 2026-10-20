"""Typed shader property/ramp revisions with measured, scoped failure evidence."""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import reject_unknown_params, require_blender
from . import nodes
from ._rna import RNAAssignment, apply_assignments, prepare_assignments, settings_mapping
from .shader_scope import bounded_tree, name, object_mode, path
from .shader_state import (
    MAX_STOPS,
    RAMP_SETTINGS,
    SETTINGS,
    descriptors,
    node_state,
    ramp_interpretation,
    ramp_state,
)

LOGGER = logging.getLogger(__name__)
BASE = {"material_name", "node_name", "group_path", "allow_shared"}


def _target(context: Any, params: Mapping[str, Any], *, modify: bool = False) -> tuple[Any, Any, Any]:
    name(params.get("material_name"), "material_name")
    node_name = name(params.get("node_name"), "node_name")
    path(params)
    if modify:
        object_mode(require_blender())
    material, tree = nodes._target_graph(context, params, modify=modify)
    node = nodes._node_exact(tree, node_name)
    if modify:
        bounded_tree(tree)
        for owner in (material, tree):
            animation = getattr(owner, "animation_data", None)
            if animation is not None and (
                getattr(animation, "action", None) is not None
                or len(getattr(animation, "drivers", ()))
                or len(getattr(animation, "nla_tracks", ()))
            ):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                                  "Shader settings/ramp replacement currently requires an unanimated material and target tree.")
    return material, tree, node


def _number(value: Any, field: str, *, minimum: float = 0, maximum: float = 1_000_000) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_argument(f"'{field}' must be a finite number.")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise invalid_argument(f"'{field}' must be a finite bounded number.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise invalid_argument(f"'{field}' is outside its finite bounds.", minimum=minimum, maximum=maximum)
    return struct.unpack("f", struct.pack("f", number))[0]


def _ramp(node: Any) -> Any:
    if node.bl_idname != "ShaderNodeValToRGB" or not hasattr(node, "color_ramp"):
        raise invalid_argument("This operation requires an exact ShaderNodeValToRGB color-ramp node.")
    if not 1 <= len(node.color_ramp.elements) <= MAX_STOPS:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Color ramp exceeds the supported 1-32 stop window.")
    return node.color_ramp


def _guard(tree: Any, node: Any) -> dict[str, Any]:
    def default(socket: Any) -> Any:
        if not hasattr(socket, "default_value"):
            return None
        value = socket.default_value
        if isinstance(value, float) and not math.isfinite(value):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cannot verify non-finite shader socket defaults.")
        if not isinstance(value, (str, bytes)) and hasattr(value, "__len__"):
            if len(value) > 64:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shader default exceeds its bounded verification window.")
            if any(isinstance(item, float) and not math.isfinite(item) for item in value):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cannot verify non-finite shader socket defaults.")
        return nodes._json_value(value)

    if len(node.inputs) > 64 or len(node.outputs) > 64:
        raise invalid_argument("Shader settings support at most 64 sockets per direction.")
    return {
        "links": sorted((link.from_node.name, link.from_socket.identifier,
                         link.to_node.name, link.to_socket.identifier, bool(link.is_muted))
                        for link in tree.links),
        "sockets": [(direction, index, socket.identifier, socket.bl_idname,
                     default(socket))
                    for direction, sockets in (("input", node.inputs), ("output", node.outputs))
                    for index, socket in enumerate(sockets)],
    }


def _check(context: Any) -> None:
    check = getattr(context, "check_cancelled", None)
    if check:
        check()


def inspect_properties(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, {"material_name", "node_name", "group_path", "sample_positions"})
    material, tree, node = _target(context, params)
    result = nodes._post_state(material, tree, node)
    result["editable_settings"] = descriptors(node, SETTINGS.get(node.bl_idname, frozenset()))
    result["group_path"] = path(params)
    samples = params.get("sample_positions")
    if node.bl_idname == "ShaderNodeValToRGB":
        ramp = _ramp(node)
        if samples is None:
            samples = [0, .25, .5, .75, 1]
        if not isinstance(samples, list) or len(samples) > 32:
            raise invalid_argument("'sample_positions' must be an array of at most 32 values.")
        positions = [_number(value, "sample position", maximum=1) for value in samples]
        result["ramp_settings"] = descriptors(ramp, RAMP_SETTINGS)
        samples = []
        for position in positions:
            color = [float(value) for value in ramp.evaluate(position)]
            if len(color) != 4 or not all(math.isfinite(value) for value in color):
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Native color-ramp sampling returned invalid numeric evidence.")
            samples.append({"position": position, "color": color})
        result["samples"] = samples
    elif samples is not None:
        raise invalid_argument("'sample_positions' is only supported for a color-ramp node.")
    return result


def _failure(exc: Exception, rollback_verified: bool, node: Any, *, ramp_before=None) -> BridgeError:
    context = {"node_name": node.name, "rollback_verified": rollback_verified,
               "possible_mutation": not rollback_verified, "execution_started": True,
               "verification_required": True}
    if ramp_before is not None:
        context["before_color_ramp"] = ramp_before
    if isinstance(exc, BridgeError):
        context["cause_code"] = exc.code
    return BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                       "Shader revision failed; inspect the measured recovery evidence before continuing.", context)


def set_properties(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, BASE | {"settings"})
    material, tree, node = _target(context, params, modify=True)
    allowed = SETTINGS.get(node.bl_idname, frozenset())
    if not allowed:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "This shader node has no reviewed editable properties; inspect supported settings first.")
    assignments = prepare_assignments(node, settings_mapping(params), allowed=allowed,
                                      object_pointers=frozenset(), bpy=require_blender())
    for item in assignments:
        if item.name == "uv_map" and item.value:
            name(item.value, "uv_map")
    before = node_state(node)
    if any(item.name not in before["settings"] for item in assignments):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cannot capture the requested shader settings for verified recovery.")
    guard = _guard(tree, node)
    _check(context)
    try:
        apply_assignments(node, assignments)
        if _guard(tree, node) != guard:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED,
                              "This setting changed socket structure/defaults or graph links; an explicit rewiring workflow is required.")
        actual = node_state(node)["settings"]
        if any(actual.get(item.name) != item.value for item in assignments):
            raise RuntimeError("Native properties did not match the requested values")
    except Exception as exc:
        LOGGER.exception("Shader property revision failed; attempting scoped property restoration")
        restored = False
        try:
            apply_assignments(node, tuple(RNAAssignment(key, value) for key, value in before["settings"].items()))
            restored = node_state(node) == before and _guard(tree, node) == guard
        except Exception:
            LOGGER.exception("Could not verify scoped shader property restoration")
        raise _failure(exc, restored, node) from exc
    return {"updated_properties": [item.name for item in assignments], "group_path": path(params),
            "links_and_socket_defaults_preserved": True, **nodes._post_state(material, tree, node)}


def _replace(ramp: Any, state: dict[str, Any]) -> None:
    # ColorRamp RNA elements are index-backed: do not retain wrappers over inserts/removals.
    while len(ramp.elements) > 1:
        ramp.elements.remove(ramp.elements[-1])
    ramp.elements[0].position = state["elements"][0]["position"]
    for item in state["elements"][1:]:
        ramp.elements.new(item["position"])
    # Assign colors only once the final sorted index order exists, including equal positions.
    for index, item in enumerate(state["elements"]):
        ramp.elements[index].color = item["color"]
    for key in sorted(RAMP_SETTINGS):
        setattr(ramp, key, state[key])


def set_color_ramp(context: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    reject_unknown_params(params, BASE | {"stops", *RAMP_SETTINGS})
    material, tree, node = _target(context, params, modify=True)
    ramp = _ramp(node)
    raw = params.get("stops")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_STOPS:
        raise invalid_argument("'stops' must contain 1-32 complete position/color objects.")
    stops = []
    for index, stop in enumerate(raw):
        if not isinstance(stop, Mapping) or set(stop) != {"position", "color"}:
            raise invalid_argument("Every stop must contain exactly 'position' and 'color'.")
        color = stop["color"]
        if not isinstance(color, list) or len(color) != 4:
            raise invalid_argument("A stop's scene-linear RGBA color must have exactly four components.")
        position = _number(stop["position"], "position", maximum=1)
        rgba = [_number(value, "color component") for value in color]
        prepare_assignments(ramp.elements[0], {"color": rgba, "position": position},
                            allowed=frozenset({"color", "position"}), object_pointers=frozenset(), bpy=require_blender())
        if stops and position < stops[-1]["position"]:
            raise invalid_argument("Stops must be ordered by nondecreasing position; tied positions retain the requested color index order.")
        stops.append({"index": index, "position": position, "color": rgba})
    assignments = prepare_assignments(ramp, {key: params[key] for key in sorted(RAMP_SETTINGS) if key in params},
                                      allowed=RAMP_SETTINGS, object_pointers=frozenset(), bpy=require_blender())
    before = ramp_state(ramp)
    desired = {**before, **{item.name: item.value for item in assignments},
               "elements": stops, "element_count": len(stops), "truncated": False}
    desired.update(ramp_interpretation(desired))
    guard = _guard(tree, node)
    _check(context)
    try:
        _replace(ramp, desired)
        if ramp_state(ramp) != desired or _guard(tree, node) != guard:
            raise RuntimeError("Native color-ramp revision did not preserve the requested state and graph invariants")
    except Exception as exc:
        LOGGER.exception("Color-ramp revision failed; attempting measured local restoration")
        restored = False
        try:
            _replace(ramp, before)
            restored = ramp_state(ramp) == before and _guard(tree, node) == guard
        except Exception:
            LOGGER.exception("Could not verify local color-ramp restoration")
        raise _failure(exc, restored, node, ramp_before=before) from exc
    return {"replaced_stops": True, "group_path": path(params), "color_space": "scene_linear_rgba",
            "links_and_socket_defaults_preserved": True, **nodes._post_state(material, tree, node)}


def register_tools(registry: Any) -> None:
    registry.register("nodes.inspect_properties", inspect_properties, toolset="nodes",
                      permissions=(Permission.INSPECT_SCENE,),
                      description="Inspect one shader node's reviewed settings, native enums and full color ramp with bounded samples.")
    for method, handler in (("set_properties", set_properties), ("set_color_ramp", set_color_ramp)):
        registry.register(f"nodes.{method}", handler, toolset="nodes", modifies=True,
                          permissions=(Permission.EDIT_MATERIALS,),
                          description="Revise reviewed shader settings or a complete color ramp, preserving links/defaults and measured failure evidence.")
