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
FIELDS = (
    "transforms",
    "hierarchy",
    "visibility",
    "mesh_geometry",
    "uv",
    "weights",
    "material_slots",
    "shader_inputs",
)
UNMEASURED = [
    "evaluated geometry, modifiers and constraints",
    "animation, drivers and simulation caches",
    "non-mesh object data, rig poses and shape keys",
    "mesh attributes, custom normals and sculpt data",
    "material/shader settings other than root socket defaults, mute state, links and listed Image Texture metadata",
    "nested node-group contents, image pixels/file contents and unlisted image settings",
    "scene, world and render settings",
    "custom properties, selection and viewport state",
    "transitive dependencies and visual appearance",
]


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
    if len(tree.nodes) > 256 or len(tree.links) > 1024:
        raise EvidenceLimit("Shader root exceeds 256 nodes or 1024 links.")
    indices = {}
    for node in tree.nodes:
        yield [
            "node",
            node.name,
            node.bl_idname,
            node.mute,
            _identity(getattr(node, "node_tree", None)),
            _identity(getattr(node, "image", None)),
        ]
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
        if field == "shader_inputs":
            if len(obj.material_slots) > 256:
                raise EvidenceLimit("Material slot evidence exceeds 256 slots.")
            materials = []
            seen = set()
            for slot in obj.material_slots:
                material = slot.material
                if material is None or material in seen:
                    continue
                seen.add(material)
                if material not in cache:
                    cache[material] = _digest(_shader_records(material), budget)
                materials.append([_identity(material), cache[material]])
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
    if {"transforms", "visibility", "shader_inputs"}.intersection(fields):
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
        fields = params.get("fields", list(FIELDS))
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
