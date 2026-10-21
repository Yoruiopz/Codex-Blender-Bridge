"""Session-local, bounded structural evidence; not a whole-scene preservation verdict."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from typing import Any

from .errors import invalid_argument
from .utils import int_param

LOGGER = logging.getLogger(__name__)
DEFAULT_FIELDS = (
    "transforms",
    "hierarchy",
    "visibility",
    "mesh_geometry",
    "uv",
    "weights",
    "material_slots",
    "shader_inputs",
)
FIELDS = (*DEFAULT_FIELDS, "rig", "animation", "shader_dependencies")
UNMEASURED = [
    "evaluated geometry, modifiers and constraints",
    "animation outside selected object/data/shape-key actions, drivers and NLA; dependency target state, action custom properties and simulation caches",
    "non-mesh object data outside selected armature rest bones/pose transforms; unlisted rig/B-Bone settings and shape-key geometry",
    "mesh attributes, custom normals and sculpt data",
    "material/shader settings outside reviewed per-node properties, color ramps, socket defaults, mute, links and listed Image Texture metadata; material/node-tree animation",
    "nested node-group contents unless shader_dependencies is selected; image pixels/file contents and unlisted image settings",
    "scene, world and render settings",
    "custom properties, selection and viewport state",
    "transitive dependencies and visual appearance",
]


def _properties(owner: Any, names: Iterable[str]) -> dict[str, Any]:
    """Read only enumerated values; never traverse arbitrary RNA or evaluate data paths."""
    return {name: _small(getattr(owner, name)) for name in names if hasattr(owner, name)}


def _pointer(owner: Any) -> int:
    return int(owner.as_pointer()) if hasattr(owner, "as_pointer") else id(owner)


class EvidenceLimit(Exception):
    pass


def _valid_name(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return len(value.encode("utf-8")) <= 63
    except UnicodeError:
        return False


class Budget:
    def __init__(self, maximum: int, check: Callable[[], None] | None):
        self.maximum = maximum
        self.used = 0
        self.bytes_used = 0
        self.check = check

    def take(self) -> None:
        if self.check and self.used % 256 == 0:
            self.check()
        if self.used >= self.maximum:
            raise EvidenceLimit("Element budget exhausted; narrow the object/field scope.")
        self.used += 1


def _identity(value: Any) -> Any:
    if value is None:
        return None
    return {
        "name": value.name,
        "session_uid": getattr(value, "session_uid", None),
        "library": value.library.name if value.library is not None else None,
    }


def _small(value: Any, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 4096:
            raise EvidenceLimit("String evidence exceeds 4096 characters.")
        return value
    if hasattr(value, "session_uid"):
        return _identity(value)
    if isinstance(value, Mapping):
        raise EvidenceLimit("Mapping socket defaults are unsupported.")
    if depth < 2 and hasattr(value, "__len__") and len(value) <= 16:
        return [_small(item, depth + 1) for item in value]
    raise EvidenceLimit("Unsupported or oversized socket value.")


def _digest(records: Iterable[Any], budget: Budget) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    for record in records:
        budget.take()
        encoded = json.dumps(
            record, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if len(encoded) > 16384 or budget.bytes_used + len(encoded) > 64 * 1024 * 1024:
            raise EvidenceLimit("Encoded evidence budget exceeded; narrow the scope.")
        budget.bytes_used += len(encoded)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return {"complete": True, "sha256": digest.hexdigest(), "record_count": count}


def _mesh_records(obj: Any, field: str) -> Iterable[Any]:
    if obj.type != "MESH":
        yield ["not_applicable", obj.type]
        return
    mesh = obj.data
    if mesh.is_editmode:
        raise EvidenceLimit("Base mesh evidence is unavailable while its data is in Edit Mode.")
    if field == "mesh_geometry":
        yield [len(mesh.vertices), len(mesh.edges), len(mesh.loops), len(mesh.polygons)]
        for vertex in mesh.vertices:
            yield ["v", vertex.index, list(vertex.co)]
        for edge in mesh.edges:
            yield ["e", edge.index, list(edge.vertices), edge.use_seam, edge.use_edge_sharp]
        for loop in mesh.loops:
            yield ["l", loop.vertex_index, loop.edge_index]
        for polygon in mesh.polygons:
            yield [
                "p",
                polygon.loop_start,
                polygon.loop_total,
                polygon.material_index,
                polygon.use_smooth,
            ]
    elif field == "uv":
        yield ["active", mesh.uv_layers.active_index]
        for layer in mesh.uv_layers:
            yield ["layer", layer.name, layer.active_render]
            for loop in layer.data:
                yield [list(loop.uv), loop.pin_uv]
    else:
        for group in obj.vertex_groups:
            yield ["group", group.index, group.name, group.lock_weight]
        for vertex in mesh.vertices:
            yield ["vertex", vertex.index]
            for weight in vertex.groups:
                yield [weight.group, weight.weight]


def _shader_records(material: Any) -> Iterable[Any]:
    yield ["material", _identity(material), bool(material.use_nodes)]
    tree = material.node_tree
    if tree is None:
        return
    yield from _tree_records(tree)


def _tree_records(tree: Any) -> Iterable[Any]:
    from .tools.shader_state import node_state

    if len(tree.nodes) > 256 or len(tree.links) > 1024:
        raise EvidenceLimit("Shader tree exceeds 256 nodes or 1024 links.")
    indices = {}
    for node in tree.nodes:
        state = node_state(node)
        yield [
            "node",
            node.name,
            node.bl_idname,
            node.mute,
            _identity(getattr(node, "node_tree", None)),
            _identity(getattr(node, "image", None)),
        ]
        for key, value in sorted(state["settings"].items()):
            yield ["shader_setting", node.name, key, _small(value)]
        ramp = state.get("color_ramp")
        if ramp is not None:
            if ramp["truncated"]:
                raise EvidenceLimit("Color ramp exceeds its 32-stop evidence budget.")
            yield ["color_ramp", node.name, ramp["interpolation"], ramp["color_mode"], ramp["hue_interpolation"]]
            for stop in ramp["elements"]:
                yield ["color_ramp_stop", node.name, stop["index"], stop["position"], stop["color"]]
        if node.bl_idname == "ShaderNodeTexImage":
            image = getattr(node, "image", None)
            yield ["image_texture", node.name,
                   *[getattr(node, key, None) for key in ("interpolation", "projection", "extension")],
                   ([getattr(image, "source", None), _small(str(getattr(image, "filepath", ""))),
                     getattr(getattr(image, "colorspace_settings", None), "name", None),
                     getattr(image, "alpha_mode", None), bool(getattr(image, "packed_file", None))]
                    if image is not None else None)]
        for direction, sockets in (("input", node.inputs), ("output", node.outputs)):
            for index, socket in enumerate(sockets):
                indices[socket.as_pointer()] = index
                yield [
                    direction,
                    node.name,
                    index,
                    socket.identifier,
                    _small(socket.default_value) if hasattr(socket, "default_value") else None,
                ]
    for link in tree.links:
        yield [
            "link",
            link.from_node.name,
            link.from_socket.identifier,
            indices[link.from_socket.as_pointer()],
            link.to_node.name,
            link.to_socket.identifier,
            indices[link.to_socket.as_pointer()],
            link.is_muted,
        ]


def _shader_dependency_records(material: Any) -> Iterable[Any]:
    """Read a bounded reachable shader graph without decoding images or following paths."""
    yield ["material", _identity(material), bool(material.use_nodes)]
    root = material.node_tree
    if root is None:
        return
    seen: set[int] = set()

    def tree_records(tree: Any, path: tuple[str, ...], ancestors: tuple[int, ...]):
        key = _pointer(tree)
        if key in ancestors:
            raise EvidenceLimit("Recursive shader-group dependency cannot be captured faithfully.")
        if len(path) > 8:
            raise EvidenceLimit("Shader dependencies exceed depth 8.")
        yield ["tree_reference", list(path), _identity(tree)]
        if key in seen:
            return
        if len(seen) >= 32:
            raise EvidenceLimit("Shader dependencies exceed 32 distinct trees per material.")
        seen.add(key)
        yield from _tree_records(tree)
        interface = getattr(getattr(tree, "interface", None), "items_tree", ())
        if len(interface) > 128:
            raise EvidenceLimit("Shader interface exceeds 128 items.")
        for index, item in enumerate(interface):
            yield ["interface", index, _properties(item, (
                "name", "identifier", "item_type", "in_out", "socket_type", "default_value",
                "min_value", "max_value", "hide_value", "hide_in_modifier", "attribute_domain",
                "default_attribute_name", "description", "force_non_field", "structure_type",
            )), getattr(getattr(item, "parent", None), "identifier", None)]
        for node in tree.nodes:
            child = getattr(node, "node_tree", None)
            if child is not None:
                yield from tree_records(child, (*path, node.name), (*ancestors, key))

    yield from tree_records(root, (), ())


def _curve_records(curve: Any) -> Iterable[Any]:
    yield ["curve", _properties(curve, (
        "data_path", "array_index", "mute", "lock", "extrapolation", "auto_smoothing",
    )), _properties(curve.group, ("name", "mute", "lock")) if getattr(curve, "group", None) is not None else None]
    # Modifier-specific RNA and envelope/control points require a separate reviewed contract.
    # Refuse a matching digest rather than silently omitting their effect on an animation.
    if len(getattr(curve, "modifiers", ())):
        raise EvidenceLimit("Animation F-Curve modifiers are outside the reviewed evidence scope.")
    for point in getattr(curve, "keyframe_points", ()):
        yield ["keyframe", _properties(point, (
            "co", "handle_left", "handle_right", "handle_left_type", "handle_right_type",
            "interpolation", "easing", "amplitude", "back", "period", "type",
        ))]
    for point in getattr(curve, "sampled_points", ()):
        yield ["sample", _properties(point, ("co",))]
    driver = getattr(curve, "driver", None)
    if driver is not None:
        yield ["driver", _properties(driver, ("type", "expression", "use_self", "is_valid"))]
        for variable in driver.variables:
            yield ["variable", _properties(variable, ("name", "type"))]
            for target in variable.targets:
                yield ["target", _properties(target, (
                    "id", "id_type", "data_path", "bone_target", "transform_type",
                    "transform_space", "rotation_mode", "context_property",
                    "use_fallback_value", "fallback_value",
                ))]


def _action_records(action: Any) -> Iterable[Any]:
    yield ["action", _identity(action), _properties(action, (
        "use_frame_range", "frame_start", "frame_end", "use_cyclic", "is_action_layered",
    ))]
    for slot in getattr(action, "slots", ()):
        yield ["slot", _properties(slot, ("identifier", "target_id_type", "handle"))]
    # Layer and channel-bag metadata carry routing/order; duplicate compatibility views
    # of layered curves are deliberately not traversed through Action.fcurves.
    if getattr(action, "is_action_layered", False):
        for layer in getattr(action, "layers", ()):
            yield ["layer", _properties(layer, ("name", "influence", "mix_mode"))]
            for strip in layer.strips:
                yield ["action_strip", _properties(strip, ("type", "frame_start", "frame_end", "frame_offset"))]
                for bag in getattr(strip, "channelbags", ()):
                    yield ["channelbag", _properties(bag, ("slot_handle",))]
                    for curve in bag.fcurves:
                        yield from _curve_records(curve)
    else:
        for curve in getattr(action, "fcurves", ()):
            yield from _curve_records(curve)


def _animation_records(obj: Any) -> Iterable[Any]:
    """Object/data/shape-key animation definitions, not sampled future motion or targets."""
    owners = [("object", obj), ("data", getattr(obj, "data", None))]
    owners.append(("shape_keys", getattr(getattr(obj, "data", None), "shape_keys", None)))
    actions: set[int] = set()

    def action_records(action: Any):
        yield ["action_reference", _identity(action)]
        if action is not None and _pointer(action) not in actions:
            actions.add(_pointer(action))
            yield from _action_records(action)

    def strip_records(strip: Any, depth: int = 0):
        if depth > 8:
            raise EvidenceLimit("NLA meta-strip evidence exceeds depth 8.")
        yield ["nla_strip", _properties(strip, (
            "name", "type", "frame_start", "frame_end", "action_frame_start", "action_frame_end",
            "scale", "repeat", "influence", "blend_type", "extrapolation", "mute", "blend_in",
            "blend_out", "use_auto_blend", "use_animated_influence", "use_animated_time",
            "use_animated_time_cyclic", "strip_time", "use_reverse", "use_sync_length",
            "action_slot_handle",
        ))]
        yield from action_records(getattr(strip, "action", None))
        for curve in getattr(strip, "fcurves", ()):
            yield from _curve_records(curve)
        for child in getattr(strip, "strips", ()):
            yield from strip_records(child, depth + 1)

    for role, owner in owners:
        if owner is None:
            yield [role, None]
            continue
        yield [role, _identity(owner)]
        data = getattr(owner, "animation_data", None)
        if data is None:
            yield ["animation_data", None]
            continue
        yield ["animation_data", _properties(data, (
            "action_blend_type", "action_extrapolation", "action_influence", "action_slot_handle",
            "use_nla", "use_tweak_mode",
        ))]
        yield from action_records(getattr(data, "action", None))
        for curve in getattr(data, "drivers", ()):
            yield from _curve_records(curve)
        for track in getattr(data, "nla_tracks", ()):
            yield ["track", _properties(track, ("name", "mute", "lock", "is_solo"))]
            for strip in track.strips:
                yield from strip_records(strip)


def _rig_records(obj: Any) -> Iterable[Any]:
    if obj.type != "ARMATURE":
        yield ["not_applicable", obj.type]
        return
    armature = obj.data
    if getattr(armature, "is_editmode", False):
        raise EvidenceLimit("Rest-bone evidence is unavailable in Armature Edit Mode.")
    yield ["armature", _identity(armature), _properties(armature, ("pose_position",))]
    for bone in armature.bones:
        yield ["rest_bone", bone.name, getattr(bone.parent, "name", None), _properties(bone, (
            "head_local", "tail_local", "matrix_local", "use_deform", "use_connect",
            "inherit_scale", "use_inherit_rotation", "use_local_location", "use_relative_parent",
            "envelope_distance", "envelope_weight", "head_radius", "tail_radius",
        ))]
    for bone in getattr(getattr(obj, "pose", None), "bones", ()):
        yield ["pose_bone", bone.name, getattr(getattr(bone, "parent", None), "name", None),
               _properties(bone, (
                   "location", "rotation_mode", "rotation_euler", "rotation_quaternion",
                   "rotation_axis_angle", "scale", "matrix_basis", "matrix", "lock_location",
                   "lock_rotation", "lock_rotation_w", "lock_rotations_4d", "lock_scale",
                   "ik_stretch", "ik_rotation_weight", "ik_linear_weight", "use_ik_rotation_control",
                   "use_ik_linear_control", "lock_ik_x", "lock_ik_y", "lock_ik_z",
                   "use_ik_limit_x", "use_ik_limit_y", "use_ik_limit_z", "ik_min_x", "ik_max_x",
                   "ik_min_y", "ik_max_y", "ik_min_z", "ik_max_z", "ik_stiffness_x",
                   "ik_stiffness_y", "ik_stiffness_z",
               ))]


def _records(obj: Any, field: str) -> Iterable[Any]:
    if field == "transforms":
        yield {
            "matrix_world": [list(row) for row in obj.matrix_world],
            "matrix_local": [list(row) for row in obj.matrix_local],
            "location": list(obj.location),
            "scale": list(obj.scale),
            "rotation_mode": obj.rotation_mode,
            "rotation_euler": list(obj.rotation_euler),
            "rotation_quaternion": list(obj.rotation_quaternion),
            "rotation_axis_angle": list(obj.rotation_axis_angle),
            "delta_location": list(obj.delta_location),
            "delta_scale": list(obj.delta_scale),
            "delta_rotation_euler": list(obj.delta_rotation_euler),
            "delta_rotation_quaternion": list(obj.delta_rotation_quaternion),
            "matrix_parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
            "dimensions": list(obj.dimensions),
        }
    elif field == "hierarchy":
        yield [_identity(obj.parent), obj.parent_type, obj.parent_bone, _identity(obj.data)]
        for collection in sorted(
            obj.users_collection,
            key=lambda item: (
                item.name,
                item.library.name if item.library else "",
                getattr(item, "session_uid", 0) or 0,
            ),
        ):
            yield ["collection", _identity(collection)]
    elif field == "visibility":
        yield [obj.hide_viewport, obj.hide_render, obj.hide_get(), obj.visible_get()]
    elif field in {"mesh_geometry", "uv", "weights"}:
        yield from _mesh_records(obj, field)
    elif field == "rig":
        yield from _rig_records(obj)
    elif field == "animation":
        yield from _animation_records(obj)
    elif field == "material_slots":
        if len(obj.material_slots) > 256:
            raise EvidenceLimit("Material slot evidence exceeds 256 slots.")
        for index, slot in enumerate(obj.material_slots):
            yield [index, slot.link, _identity(slot.material)]


def _capture_field(obj: Any, field: str, budget: Budget, cache: dict) -> dict[str, Any]:
    try:
        shared_key = (
            (field, obj.data.as_pointer())
            if obj.type == "MESH" and field in {"mesh_geometry", "uv"}
            else None
        )
        if shared_key is not None and shared_key in cache:
            return cache[shared_key]
        if field in {"shader_inputs", "shader_dependencies"}:
            if len(obj.material_slots) > 256:
                raise EvidenceLimit("Material slot evidence exceeds 256 slots.")
            materials = []
            seen = set()
            for slot in obj.material_slots:
                material = slot.material
                if material is None or material in seen:
                    continue
                seen.add(material)
                key = (field, _pointer(material))
                if key not in cache:
                    records = _shader_records(material) if field == "shader_inputs" else _shader_dependency_records(material)
                    cache[key] = _digest(records, budget)
                materials.append([_identity(material), cache[key]])
            return _digest(materials, budget)
        if field == "transforms":
            records = list(_records(obj, field))
            result = {**_digest(records, budget), "values": records[0]}
        else:
            result = _digest(_records(obj, field), budget)
        if field in {"mesh_geometry", "uv", "weights"} and obj.type != "MESH":
            result.update(
                {"applicable": False, "reason": "This field measures base mesh data only."}
            )
        if field == "rig" and obj.type != "ARMATURE":
            result.update({"applicable": False, "reason": "This field measures armature rest bones and current pose only."})
        if obj.type == "MESH" and field == "mesh_geometry":
            result["counts"] = {
                "vertices": len(obj.data.vertices),
                "edges": len(obj.data.edges),
                "loops": len(obj.data.loops),
                "polygons": len(obj.data.polygons),
            }
        if shared_key is not None:
            cache[shared_key] = result
        return result
    except EvidenceLimit as error:
        return {"complete": False, "reason": str(error)}
    except (ValueError, TypeError, AttributeError, RuntimeError):
        LOGGER.exception("Could not capture %s evidence for %s", field, obj.name)
        return {"complete": False, "reason": "Blender value could not be captured faithfully."}


def _collect(
    bpy: Any, names: list[str], fields: list[str], maximum: int, check: Callable[[], None] | None
) -> dict[str, Any]:
    if check:
        check()
    if {"transforms", "visibility", "shader_inputs", "shader_dependencies", "rig"}.intersection(fields):
        bpy.context.view_layer.update()
    budget = Budget(maximum, check)
    cache: dict[Any, Any] = {}
    objects = {}
    targets: dict[str, list[Any]] = {name: [] for name in names}
    for index, obj in enumerate(bpy.context.scene.objects):
        if check and index % 256 == 0:
            check()
        if obj.name in targets and len(targets[obj.name]) < 2:
            targets[obj.name].append(obj)
    for name in names:
        matches = targets[name]
        if len(matches) != 1:
            objects[name] = {"resolution": "missing" if not matches else "ambiguous", "fields": {}}
            continue
        obj = matches[0]
        objects[name] = {
            "resolution": "exact",
            "identity": _identity(obj),
            "type": obj.type,
            "fields": {field: _capture_field(obj, field, budget, cache) for field in fields},
        }
    return {
        "scene": _identity(bpy.context.scene),
        "view_layer": bpy.context.view_layer.name,
        "frame": bpy.context.scene.frame_current,
        "objects": objects,
        "elements_read": budget.used,
        "element_limit": maximum,
        "encoded_bytes_read": budget.bytes_used,
        "encoded_byte_limit": 64 * 1024 * 1024,
    }


class SceneEvidenceStore:
    """Keep eight compact immutable baselines; clear when project/session is replaced."""

    def __init__(self) -> None:
        self._snapshots: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def clear(self) -> None:
        self._snapshots.clear()

    def capture(self, bpy: Any, params: Mapping[str, Any], check=None) -> dict[str, Any]:
        names = params.get("object_names")
        if (
            not isinstance(names, list)
            or not 1 <= len(names) <= 32
            or any(not _valid_name(name) for name in names)
            or len(set(names)) != len(names)
        ):
            raise invalid_argument(
                "'object_names' requires 1-32 unique exact names, each at most 63 UTF-8 bytes."
            )
        fields = params.get("fields", list(DEFAULT_FIELDS))
        if (
            not isinstance(fields, list)
            or not fields
            or len(fields) > len(FIELDS)
            or any(not isinstance(field, str) or field not in FIELDS for field in fields)
            or len(set(fields)) != len(fields)
        ):
            raise invalid_argument(
                "'fields' must contain unique supported evidence fields.", supported=list(FIELDS)
            )
        maximum = int_param(params, "max_elements", 200000, minimum=1, maximum=1000000)
        state = _collect(bpy, names, fields, maximum, check)
        unresolved = [
            name for name, obj in state["objects"].items() if obj["resolution"] != "exact"
        ]
        if unresolved:
            raise invalid_argument(
                "Snapshot targets must resolve exactly in the current scene.", unresolved=unresolved
            )
        identifier = f"snap_{uuid.uuid4().hex}"
        self._snapshots[identifier] = {"names": list(names), "fields": list(fields), "state": state}
        while len(self._snapshots) > 8:
            self._snapshots.popitem(last=False)
        return {
            "snapshot_id": identifier,
            "schema_version": 1,
            "fields": list(fields),
            "state": deepcopy(state),
            "coverage_complete": self._complete(state),
            "unmeasured": list(UNMEASURED),
            "user_goal_verified": False,
        }

    @staticmethod
    def _complete(state: Mapping[str, Any]) -> bool:
        return state["scene"]["session_uid"] is not None and all(
            obj["resolution"] == "exact"
            and obj["identity"]["session_uid"] is not None
            and all(field["complete"] for field in obj["fields"].values())
            for obj in state["objects"].values()
        )

    def compare(self, bpy: Any, params: Mapping[str, Any], check=None) -> dict[str, Any]:
        identifier = params.get("snapshot_id")
        if (
            not isinstance(identifier, str)
            or len(identifier) > 64
            or identifier not in self._snapshots
        ):
            raise invalid_argument(
                "Snapshot is unknown, evicted or from a replaced project/session."
            )
        baseline = self._snapshots[identifier]
        before = baseline["state"]
        scene = _identity(bpy.context.scene)
        old_scene = before["scene"]
        same_scene = (
            scene["session_uid"] == old_scene["session_uid"]
            and scene["library"] == old_scene["library"]
            if scene["session_uid"] is not None
            else scene == old_scene
        )
        if not same_scene or bpy.context.view_layer.name != before["view_layer"]:
            raise invalid_argument("Snapshot belongs to a different scene or view layer.")
        maximum = int_param(
            params, "max_elements", before["element_limit"], minimum=1, maximum=1000000
        )
        after = _collect(bpy, baseline["names"], baseline["fields"], maximum, check)
        changes = []
        for name, previous in before["objects"].items():
            current = after["objects"][name]
            if current["resolution"] != "exact":
                changes.append(
                    {
                        "object": name,
                        "field": "presence",
                        "before": "exact",
                        "after": current["resolution"],
                    }
                )
                continue
            for key in ("identity", "type"):
                if previous[key] != current[key]:
                    changes.append(
                        {
                            "object": name,
                            "field": key,
                            "before": previous[key],
                            "after": current[key],
                        }
                    )
            for field in baseline["fields"]:
                old, new = previous["fields"][field], current["fields"][field]
                if old["complete"] and new["complete"] and old["sha256"] != new["sha256"]:
                    changes.append({"object": name, "field": field, "before": old, "after": new})
        complete = self._complete(before) and self._complete(after)
        return {
            "snapshot_id": identifier,
            "schema_version": 1,
            "status": "changed" if changes else "unchanged_within_scope" if complete else "unknown",
            "changes": deepcopy(changes),
            "coverage_complete": complete,
            "fields": list(baseline["fields"]),
            "before_frame": before["frame"],
            "after_frame": after["frame"],
            "before_scene": deepcopy(before["scene"]),
            "state": after,
            "unmeasured": list(UNMEASURED),
            "user_goal_verified": False,
        }
