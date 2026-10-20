"""Reviewed shader settings and bounded state shared by inspectors and typed edits."""

from __future__ import annotations

import math
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ._rna import serialize_properties

MAX_STOPS = 32
MAX_ENUM_ITEMS = 128
SETTINGS = {
    "ShaderNodeMath": frozenset({"operation", "use_clamp"}),
    "ShaderNodeVectorMath": frozenset({"operation"}),
    "ShaderNodeTexNoise": frozenset({"noise_dimensions", "noise_type", "normalize"}),
    "ShaderNodeTexVoronoi": frozenset({"voronoi_dimensions", "distance", "feature", "normalize"}),
    "ShaderNodeTexWave": frozenset({"wave_type", "bands_direction", "rings_direction", "wave_profile"}),
    "ShaderNodeTexGradient": frozenset({"gradient_type"}),
    "ShaderNodeMixRGB": frozenset({"blend_type", "use_alpha", "use_clamp"}),
    "ShaderNodeMix": frozenset({"data_type", "blend_type", "factor_mode", "clamp_factor", "clamp_result"}),
    "ShaderNodeMapRange": frozenset({"data_type", "interpolation_type", "clamp"}),
    "ShaderNodeClamp": frozenset({"clamp_type"}),
    "ShaderNodeNormalMap": frozenset({"space", "uv_map"}),
    "ShaderNodeVectorTransform": frozenset({"vector_type", "convert_from", "convert_to"}),
    "ShaderNodeBsdfPrincipled": frozenset({"distribution", "subsurface_method"}),
}
RAMP_SETTINGS = frozenset({"interpolation", "color_mode", "hue_interpolation"})


def graph_guard(tree: Any, node: Any) -> dict[str, Any]:
    """Bounded semantic links and complete target socket/default state for revisions."""
    from . import nodes

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
        raise invalid_argument("Shader revisions support at most 64 sockets per direction.")
    return {
        "links": sorted((link.from_node.name, link.from_socket.identifier,
                         link.to_node.name, link.to_socket.identifier, bool(link.is_muted))
                        for link in tree.links),
        "sockets": [(direction, index, socket.identifier, socket.bl_idname, default(socket))
                    for direction, sockets in (("input", node.inputs), ("output", node.outputs))
                    for index, socket in enumerate(sockets)],
    }


def ramp_interpretation(state: dict[str, Any]) -> dict[str, Any]:
    rgb = state["color_mode"] == "RGB"
    return {"interpolation_active": rgb,
            "effective_interpolation": state["interpolation"] if rgb else "LINEAR",
            "hue_interpolation_active": not rgb}


def ramp_state(ramp: Any) -> dict[str, Any]:
    elements = []
    for index, element in enumerate(islice(ramp.elements, MAX_STOPS)):
        position = float(element.position)
        color = [float(value) for value in element.color]
        if len(color) != 4 or not all(math.isfinite(value) for value in [position, *color]):
            raise ValueError("Color ramp contains non-finite or malformed native state.")
        elements.append({"index": index, "position": position, "color": color})
    state = {"interpolation": ramp.interpolation, "color_mode": ramp.color_mode,
             "hue_interpolation": ramp.hue_interpolation,
             "element_count": len(ramp.elements), "elements": elements,
             "truncated": len(ramp.elements) > len(elements)}
    return {**state, **ramp_interpretation(state)}


def node_state(node: Any) -> dict[str, Any]:
    allowed = SETTINGS.get(node.bl_idname, frozenset())
    result = {"settings": serialize_properties(node, allowed)}
    if node.bl_idname == "ShaderNodeValToRGB" and hasattr(node, "color_ramp"):
        result["color_ramp"] = ramp_state(node.color_ramp)
    return result


def descriptors(owner: Any, allowed: frozenset[str]) -> dict[str, Any]:
    result = {}
    properties = getattr(getattr(owner, "bl_rna", None), "properties", None)
    for name in sorted(allowed):
        prop = properties.get(name) if properties is not None else None
        if prop is None:
            result[name] = {"available": False}
            continue
        record = {"available": True, "type": prop.type, "readonly": bool(prop.is_readonly)}
        if prop.type == "ENUM":
            record["identifiers"] = [item.identifier for item in islice(prop.enum_items, MAX_ENUM_ITEMS)]
            record["truncated"] = len(prop.enum_items) > len(record["identifiers"])
        elif prop.type in {"INT", "FLOAT"}:
            for key in ("hard_min", "hard_max"):
                value = getattr(prop, key, None)
                record[key] = value if value is not None and math.isfinite(value) else None
        result[name] = record
    return result
