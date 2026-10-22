"""Persistent, explicitly scoped cinematic controls with live CAS compensation.

The first domain deliberately accepts static procedural scenes only. Rendering is
a bounded native call, not a transactional sandbox for arbitrary user handlers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path

from .. import cinematic_variants as records
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import reject_unknown_params, require_blender
from ._object_safety import require_local_editable_id, require_single_user_object_data
from ._object_scope import datablock_identity, require_object_scope
from .mesh_surface import _capture

LOGGER = logging.getLogger(__name__)
INSPECT = (Permission.INSPECT_SCENE,)
EDIT = (*INSPECT, Permission.EDIT_SCENE)
APPLY = (*EDIT, Permission.TRANSFORM_OBJECTS)
PREVIEW = (*APPLY, Permission.CAPTURE_VIEWPORT)
BASE_PARAMS = {"expected_library_revision", "expected_library_fingerprint"}
RECORD_PARAMS = BASE_PARAMS | {"variant_id"}
CONTROL_TRANSFORMS = {"location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
    "matrix_world", "matrix_basis", "matrix_local", "dimensions"}
ALLOWED_NODES = {"ShaderNodeOutputMaterial", "ShaderNodeBsdfPrincipled", "ShaderNodeTexChecker", "ShaderNodeUVMap",
    "ShaderNodeTexCoord", "ShaderNodeRGB", "ShaderNodeValue", "ShaderNodeBackground", "ShaderNodeOutputWorld",
    "ShaderNodeEmission", "ShaderNodeOutputLight"}
_PREVIEWS: dict[str, str] = {}


def _gate(context, permissions, *, recovery=False):
    # Resolve every callback-backed permission read before the final cancellation
    # and callback-free stop flags. Callers then compare pure scope/state before
    # each write; a provider-induced pause, stop or context change cannot pass a
    # stale final guard, including while compensating an owned publication.
    context.require(*permissions)
    context.require(*permissions)
    # Recovery retains the same live request/toolset authority as a forward
    # write. Lost callers cannot authorize additional compensation mutations.
    if context.check_cancelled:
        context.check_cancelled()
    lifetime = getattr(context, "request_lifecycle", None)
    if lifetime is not None:
        lifetime.check()
    registry = getattr(context, "registry", None)
    if registry is not None and "scene_edit" not in registry.enabled_toolsets:
        raise BridgeError(ErrorCode.TOOLSET_DISABLED, "Cinematic toolset was disabled during live authorization.")
    flags = context.state.snapshot() if getattr(context, "state", None) else {}
    modifying = any(permission != Permission.INSPECT_SCENE for permission in permissions)
    if modifying and flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Cinematic operation emergency-stopped.")
    if modifying and flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Cinematic operation paused.")


def _value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise invalid_argument("Cinematic evidence requires finite native values.")
        return value
    return [_value(item) for item in value]



def _redundant_camera_compatibility(owner, values):
    """Recognize only Blender's exact redundant pre-4.0 Cycles camera payload.

    Blender 4.5 adds this compatibility dictionary on save. Its values already
    have native RNA proof; arbitrary cycles properties must remain protected.
    """
    if getattr(owner.bl_rna, "identifier", None) != "Camera" or not isinstance(values, dict):
        return False
    fields = {"fisheye_fov", "fisheye_lens", "fisheye_polynomial_k0", "fisheye_polynomial_k1",
        "fisheye_polynomial_k2", "fisheye_polynomial_k3", "fisheye_polynomial_k4",
        "latitude_min", "latitude_max", "longitude_min", "longitude_max", "panorama_type"}
    if set(values) != fields:
        return False
    expected = {name: _value(getattr(owner, name)) for name in fields if name != "panorama_type"}
    enum = owner.bl_rna.properties["panorama_type"].enum_items.get(owner.panorama_type)
    if enum is None:
        return False
    expected["panorama_type"] = enum.value
    return values == expected and all(type(values[name]) is type(expected[name]) for name in fields)


def _primitive(owner, exclude=()):
    """Protect native writable primitive settings without following ID pointers."""
    result = {}
    for prop in owner.bl_rna.properties:
        key = prop.identifier
        if key in exclude or prop.is_readonly or prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            continue
        value = getattr(owner, key)
        if isinstance(value, set):
            value = sorted(value)
        result[key] = _value(value)
    try:
        custom_keys = tuple(owner.keys())
    except (AttributeError, TypeError):
        # All bpy_struct values expose keys(), but native structs such as
        # sockets can explicitly lack IDProperty storage.
        custom_keys = ()
    if custom_keys:
        budget = [0]

        def custom(value, depth=0):
            budget[0] += 1
            if depth > 8 or budget[0] > 4096:
                raise invalid_argument("Protected custom properties exceed depth eight or 4096 values.")
            if hasattr(value, "as_pointer"):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Protected custom properties contain unsupported native references.")
            if hasattr(value, "keys"):
                return {key: custom(value[key], depth+1) for key in sorted(value.keys())}
            if value is None or isinstance(value, (str, bool, int, float)):
                return _value(value)
            try:
                return [custom(item, depth+1) for item in value]
            except TypeError as error:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Protected custom properties contain unsupported native references.") from error

        properties = {key: custom(owner[key]) for key in sorted(custom_keys)
            if key not in {records.PROPERTY, "_codex_bridge_undo_marker"}}
        if "cycles" in properties and _redundant_camera_compatibility(owner, properties["cycles"]):
            del properties["cycles"]
            if properties:
                result["custom_properties"] = properties
        else:
            result["custom_properties"] = properties
    return result


def _no_animation(owner):
    if getattr(owner, "animation_data", None):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic variants require unanimated controls and protected static scene data.")


def _graph(owner, exclude=()):
    _no_animation(owner)
    result = {"properties": _primitive(owner, exclude)}
    tree = getattr(owner, "node_tree", None)
    if tree is None:
        return result
    _no_animation(tree)
    if len(tree.nodes) > 64 or len(tree.links) > 256:
        raise invalid_argument("Cinematic procedural shader proof exceeds 64 nodes or 256 links.")
    nodes = []
    for node in tree.nodes:
        if node.bl_idname not in ALLOWED_NODES or getattr(node, "object", None) is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic rendering accepts only reviewed procedural shader nodes without external image, group or object dependencies.")
        sockets = []
        for direction in ("inputs", "outputs"):
            for socket in getattr(node, direction):
                sockets.append((direction, socket.identifier, socket.bl_idname, _primitive(socket)))
        nodes.append((node.name, node.bl_idname, _primitive(node), sockets))
    result["nodes"] = sorted(nodes)
    result["links"] = sorted((link.from_node.name, link.from_socket.identifier, link.to_node.name,
                              link.to_socket.identifier, bool(link.is_muted)) for link in tree.links)
    return result


def _control(obj):
    kind = obj.type
    fields = records.CAMERA_FIELDS if kind == "CAMERA" else (*records.LIGHT_COMMON, *records.LIGHT_SHAPE[obj.data.type])
    settings = {field: _value(getattr(obj.data, field)) for field in fields}
    if kind == "CAMERA":
        settings.update({"dof."+field: _value(getattr(obj.data.dof, field)) for field in records.DOF_FIELDS})
        settings["dof.focus_object"] = None if obj.data.dof.focus_object is None else obj.data.dof.focus_object.name
    result = {"object_name": obj.name, "data_name": obj.data.name, "object_type": kind, "data_type": obj.data.type,
        "location": list(obj.location), "rotation_mode": obj.rotation_mode,
        "rotation": list(obj.rotation_quaternion if obj.rotation_mode == "QUATERNION" else obj.rotation_euler),
        "scale": list(obj.scale), "settings": settings}
    return records.validate_control(result, kind)


def _controls(bpy, camera_name, light_names):
    result = []
    for name, kind in [(camera_name, "CAMERA"), *((name, "LIGHT") for name in light_names)]:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != kind:
            raise invalid_argument("Explicit cinematic reference is missing or has changed type.", object=name)
        require_object_scope(bpy, obj, operation="Cinematic variants")
        require_single_user_object_data(obj, operation="Cinematic variants")
        if obj.parent or len(obj.children) or len(obj.constraints) or len(obj.modifiers):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic controls require independent unparented objects without children, constraints or modifiers.")
        if (tuple(obj.delta_location) != (0., 0., 0.) or tuple(obj.delta_rotation_euler) != (0., 0., 0.)
                or tuple(obj.delta_rotation_quaternion) != (1., 0., 0., 0.) or tuple(obj.delta_scale) != (1., 1., 1.)
                or any(obj.lock_location) or any(obj.lock_rotation) or any(obj.lock_scale) or obj.lock_rotation_w):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic controls require identity deltas and unlocked transforms.")
        for owner in (obj, obj.data):
            _no_animation(owner)
        if obj.type == "LIGHT":
            _graph(obj.data, set(_control(obj)["settings"]))
        _control(obj)
        result.append(obj)
    if len({datablock_identity(obj) for obj in result}) != len(result):
        raise invalid_argument("Cinematic controls must be distinct objects.")
    users = bpy.data.user_map(subset=set(result))
    scene = bpy.context.scene
    if len(scene.view_layers) > 8:
        raise invalid_argument("Cinematic scope supports at most eight view layers.")
    for obj in result:
        containers = {datablock_identity(item) for item in obj.users_collection}
        incoming = list(users.get(obj, ()))
        expected = int(scene.collection.objects.get(obj.name) == obj)+sum(layer.objects.get(obj.name) == obj for layer in scene.view_layers)+int(scene.camera == obj)
        if (len(incoming) > 256 or any(collection.user_of_id(obj) != 1 for collection in obj.users_collection)
                or scene.user_of_id(obj) != expected or any(datablock_identity(user) not in containers and user != scene for user in incoming)):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic control has an unreviewed incoming consumer (including camera markers/focus references).")
    return result


def _mesh(obj):
    import bmesh

    mesh = obj.data
    if mesh.shape_keys or mesh.has_custom_normals or len(obj.modifiers) or len(obj.constraints):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Protected cinematic assets currently require static base meshes without modifiers, shape keys, constraints or custom normals.")
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        for sequence in (bm.verts, bm.edges, bm.faces):
            sequence.ensure_lookup_table()
            sequence.index_update()
        result = _capture(obj, bm)
    finally:
        bm.free()
    # Portable content proof is independent of process pointers. A separate
    # runtime guard retains exact object/data identities for every live write.
    result["base"].pop("ownership")
    result["base"]["materials"] = [material.name if material else None for material in mesh.materials]
    result["metadata"]["scenes"] = sorted(scene.name for scene in obj.users_scene)
    result["metadata"]["collections"] = sorted(collection.name for collection in obj.users_collection)
    result["metadata"]["slots"] = [(slot.material.name if slot.material else None, slot.link) for slot in obj.material_slots]
    result["settings"] = _primitive(mesh)
    result["materials"] = [(slot.material.name, _graph(slot.material)) if slot.material else None for slot in obj.material_slots]
    return result


def _collections(root):
    pending, result, seen = [root], [], set()
    while pending:
        item = pending.pop()
        if datablock_identity(item) in seen:
            continue
        seen.add(datablock_identity(item))
        if len(seen) > 128:
            raise invalid_argument("Cinematic collection proof exceeds 128 collections.")
        result.append((item.name, _primitive(item), sorted(obj.name for obj in item.objects), sorted(child.name for child in item.children)))
        pending.extend(item.children)
    return sorted(result)


def _layer_collection(root, depth=0):
    if depth > 16:
        raise invalid_argument("Cinematic view-layer collection nesting exceeds sixteen levels.")
    return (root.collection.name, _primitive(root), [_layer_collection(child, depth+1) for child in root.children])



def _static_dependencies(scene):
    if (getattr(scene, "background_set", None) is not None or getattr(scene, "rigidbody_world", None) is not None
            or getattr(scene.render, "use_freestyle", False)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic static proof rejects background scenes, rigid-body worlds and Freestyle dependencies.")
    for layer in scene.view_layers:
        if len(getattr(layer, "aovs", ())) or len(getattr(layer, "lightgroups", ())):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic static proof rejects unreviewed AOV and light-group collections.")
    for obj in scene.objects:
        if (getattr(obj, "rigid_body", None) is not None or getattr(obj, "rigid_body_constraint", None) is not None
                or (getattr(obj, "field", None) is not None and obj.field.type != "NONE")):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic static proof rejects unreviewed physical dependencies.")
        if obj.type == "CAMERA" and len(getattr(obj.data, "background_images", ())):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic static proof rejects camera background-image dependencies.")


def _profile(bpy, controls, protected):
    scene = bpy.context.scene
    require_local_editable_id(scene, operation="Cinematic variants")
    _static_dependencies(scene)
    if bpy.context.mode != "OBJECT" or scene.render.engine not in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic variants require Object Mode and the current EEVEE renderer.")
    sequencer = scene.sequence_editor
    strips = () if sequencer is None else getattr(sequencer, "strips_all", getattr(sequencer, "sequences_all", ()))
    # In 5.2 use_nodes is deprecated and always true even without a graph;
    # inspect actual compositor owners and actual sequencer strips instead.
    if (getattr(scene, "node_tree", None) is not None or getattr(scene, "compositing_node_group", None) is not None
            or len(strips) or len(scene.timeline_markers)
            or len(scene.objects) > 64 or scene.render.use_multiview or scene.view_settings.use_curve_mapping):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic proof requires at most 64 static objects without compositor, sequencer, timeline markers, view curves or multiview rendering.")
    # Native handlers can mutate protected scene state during refresh/render.
    # Revalidate after every call and never replay handlers as compensation.
    control_names = {obj.name for obj in controls}
    mesh_names = {obj.name for obj in scene.objects if obj.type == "MESH"}
    if set(protected) != mesh_names:
        raise invalid_argument("protected_objects must explicitly list every scene mesh, including hidden and shared-data consumers.")
    objects = []
    for obj in sorted(scene.objects, key=lambda item: item.name):
        require_local_editable_id(obj, operation="Cinematic preservation proof")
        _no_animation(obj)
        if obj.type not in {"MESH", "CAMERA", "LIGHT", "EMPTY"} or obj.instance_type != "NONE" or len(obj.particle_systems):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic proof supports static meshes, plain cameras/lights and non-instanced empties only.")
        if obj.type == "EMPTY" and obj.data is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Image empties are outside the procedural cinematic reference domain.")
        if obj.type == "LIGHT" and obj.name not in control_names:
            raise invalid_argument("Every scene light must be explicitly included in light_objects.")
        if obj.parent or len(obj.constraints) or len(obj.modifiers):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic proof currently requires unparented unmodified scene objects.")
        item = {"name": obj.name, "type": obj.type, "properties": _primitive(obj, CONTROL_TRANSFORMS if obj.name in control_names else ()),
            "collections": sorted(collection.name for collection in obj.users_collection), "hidden": bool(obj.hide_get())}
        if obj.data:
            require_local_editable_id(obj.data, operation="Cinematic preservation proof")
            _no_animation(obj.data)
            if obj.type == "MESH":
                item["data"] = _mesh(obj)
            else:
                mutable = set(_control(obj)["settings"]) if obj.name in control_names else set()
                if obj.type == "CAMERA" and obj.name in control_names:
                    # Writable angle aliases are derived from the captured
                    # lens/sensor settings; they change with the owned lens.
                    mutable.update({"angle", "angle_x", "angle_y"})
                item["data"] = _primitive(obj.data, {key for key in mutable if not key.startswith("dof.")})
                if obj.type == "LIGHT":
                    item["light_graph"] = _graph(obj.data, mutable)
                if obj.type == "CAMERA":
                    if obj.data.dof.focus_object is not None:
                        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cinematic cameras require focus distance without focus-object dependencies.")
                    item["dof"] = _primitive(obj.data.dof, records.DOF_FIELDS if obj.name in control_names else ())
        objects.append(item)
    world = None if scene.world is None else (scene.world.name, _graph(scene.world))
    result = {"scene": scene.name, "objects": objects, "collections": _collections(scene.collection), "world": world,
        "render": _primitive(scene.render), "image": _primitive(scene.render.image_settings),
        "view": _primitive(scene.view_settings), "display": _primitive(scene.display_settings),
        "eevee": _primitive(scene.eevee), "frame": [scene.frame_current, scene.frame_subframe],
        "scene_settings": _primitive(scene, {"frame_current", "frame_subframe"}),
        "empty_sequencer": None if sequencer is None else _primitive(sequencer),
        "layers": [(layer.name, _primitive(layer), _layer_collection(layer.layer_collection)) for layer in scene.view_layers]}
    if len(json.dumps(result, allow_nan=False).encode()) > 524_288:
        raise invalid_argument("Cinematic protected evidence exceeds 512 KiB; narrow the scene.")
    return result


def _runtime(bpy):
    scene = bpy.context.scene
    owners = [scene, *scene.view_layers, scene.world, *scene.objects]
    pending, seen = [scene.collection], set()
    while pending:
        collection = pending.pop()
        if datablock_identity(collection) in seen:
            continue
        seen.add(datablock_identity(collection))
        if len(seen) > 128:
            raise invalid_argument("Cinematic runtime collection scope exceeds 128 collections.")
        owners.append(collection)
        pending.extend(collection.children)
    owners.extend(obj.data for obj in scene.objects if obj.data)
    owners.extend(slot.material for obj in scene.objects for slot in obj.material_slots if slot.material)
    owners.extend(owner.node_tree for owner in tuple(owners) if owner is not None and getattr(owner, "node_tree", None))
    return {"ids": sorted((owner.bl_rna.identifier, owner.name, datablock_identity(owner), getattr(owner, "session_uid", None)) for owner in owners if owner is not None),
        "mode": bpy.context.mode, "filepath": bpy.data.filepath,
        "selected": sorted(datablock_identity(obj) for obj in bpy.context.view_layer.objects
            if obj.select_get(view_layer=bpy.context.view_layer)),
        "active": None if bpy.context.view_layer.objects.active is None else datablock_identity(bpy.context.view_layer.objects.active),
        "camera": None if scene.camera is None else datablock_identity(scene.camera)}


def _library(scene, params):
    raw = scene.get(records.PROPERTY)
    library = records.read_library(raw)
    revision = params.get("expected_library_revision")
    if type(revision) is not int or revision != library["revision"] or params.get("expected_library_fingerprint") != records.fingerprint(raw):
        raise invalid_argument("Cinematic operation requires the current inspected library revision and JSON fingerprint.")
    return raw, library


def inspect(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, set())
    _gate(context, INSPECT)
    bpy = require_blender()
    raw = bpy.context.scene.get(records.PROPERTY)
    library = records.read_library(raw)
    return {**library, "library_fingerprint": records.fingerprint(raw), "project_saved": False,
        "fresh_preview_required": True, "authority_loaded": False}


def capture(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, BASE_PARAMS | {"label", "camera_object", "light_objects", "protected_objects", "variant_id"})
    _gate(context, EDIT)
    bpy = require_blender()
    scene = bpy.context.scene
    raw, library = _library(scene, params)
    camera = records.name(params.get("camera_object"))
    lights = records.names(params.get("light_objects"), "light_objects", 8)
    protected = sorted(records.names(params.get("protected_objects"), "protected_objects", 32))
    controls = _controls(bpy, camera, lights)
    profile, runtime = _profile(bpy, controls, protected), _runtime(bpy)
    identifier = params.get("variant_id")
    if identifier is not None and identifier not in {record["variant_id"] for record in library["variants"]}:
        raise invalid_argument("Replacement variant_id must already exist in the inspected library.")
    record = {"variant_id": identifier or "v_"+uuid.uuid4().hex, "label": params.get("label"),
        "camera": _control(controls[0]), "lights": [_control(obj) for obj in controls[1:]],
        "protected_objects": protected, "profile_sha256": records.digest(profile)}
    records.validate_record(record)
    updated = {**library, "revision": library["revision"]+1,
        "variants": [item for item in library["variants"] if item["variant_id"] != identifier]+[record]}
    encoded = records.encode_library(updated)
    _gate(context, EDIT)
    if (_runtime(bpy) != runtime or _profile(bpy, _controls(bpy, camera, lights), protected) != profile
            or scene.get(records.PROPERTY) != raw):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Cinematic capture context or protected state changed; reinspect.")
    try:
        scene[records.PROPERTY] = encoded
        _gate(context, EDIT)
        if (scene.get(records.PROPERTY) != encoded or _runtime(bpy) != runtime
                or _profile(bpy, _controls(bpy, camera, lights), protected) != profile):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Cinematic capture write or protected-state readback did not verify.")
    except Exception as error:
        raise BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Cinematic metadata capture did not complete; reinspect the current library.",
            {"possible_mutation": True, "execution_started": True,
             "verification_required": True, "rollback_verified": False}) from error
    return {"changed": True, "variant": record, "revision": updated["revision"],
        "library_fingerprint": records.fingerprint(encoded), "project_saved": False, "authority_loaded": False}


def _prepare(context, params, permissions):
    _gate(context, permissions)
    bpy = require_blender()
    raw, library = _library(bpy.context.scene, params)
    candidates = [item for item in library["variants"] if item["variant_id"] == params.get("variant_id")]
    if len(candidates) != 1:
        raise invalid_argument("variant_id must name one inspected stored variant.")
    record = candidates[0]
    names = [item["object_name"] for item in record["lights"]]
    controls = _controls(bpy, record["camera"]["object_name"], names)
    desired = [record["camera"], *record["lights"]]
    current = [_control(obj) for obj in controls]
    for before, after in zip(current, desired, strict=True):
        if any(before[key] != after[key] for key in ("object_name", "data_name", "object_type", "data_type", "rotation_mode")):
            raise invalid_argument("Stored cinematic references need exact current name, type, data and rotation-mode rebind.")
    profile = _profile(bpy, controls, record["protected_objects"])
    if records.digest(profile) != record["profile_sha256"]:
        raise invalid_argument("Stored variant protected assets or render/world/time profile changed; capture a new reviewed variant.")
    runtime = _runtime(bpy)
    fingerprint = records.digest({"runtime": runtime, "profile": profile, "raw": raw, "current": current, "desired": desired})
    return bpy, raw, record, controls, current, desired, profile, runtime, fingerprint


def _writes(controls, current, desired):
    writes = []
    for obj, before, after in zip(controls, current, desired, strict=True):
        for key in ("location", "rotation", "scale"):
            if before[key] != after[key]:
                attr = ("rotation_quaternion" if obj.rotation_mode == "QUATERNION" else "rotation_euler") if key == "rotation" else key
                writes.append((obj, attr, before[key], after[key]))
        for key, value in after["settings"].items():
            if before["settings"][key] != value:
                owner, attr = (obj.data.dof, key[4:]) if key.startswith("dof.") else (obj.data, key)
                writes.append((owner, attr, before["settings"][key], value))
    return writes


class _Transaction:
    def __init__(self, context, prepared, permissions):
        self.context, self.permissions = context, permissions
        (self.bpy, self.raw, self.record, self.controls, self.before, self.desired,
         self.profile, self.runtime, self.fingerprint) = prepared
        self.attempted = []

    def validate(self, expected, *, recovery=False, profile=None, runtime=None):
        _gate(self.context, self.permissions, recovery=recovery)
        controls = _controls(self.bpy, self.controls[0].name, [obj.name for obj in self.controls[1:]])
        if (self.bpy.context.scene.get(records.PROPERTY) != self.raw or _runtime(self.bpy) != (self.runtime if runtime is None else runtime)
                or _profile(self.bpy, controls, self.record["protected_objects"]) != (self.profile if profile is None else profile)
                or [_control(obj) for obj in controls] != expected):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Cinematic context, ownership, protected data or control output changed; no further writes are allowed.")

    def run(self):
        expected = self.before
        for owner, attr, before, after in _writes(self.controls, self.before, self.desired):
            self.validate(expected)
            self.attempted.append((owner, attr, before, after))
            setattr(owner, attr, after)
            # The typed native getter must round-trip the exact captured value.
            if _value(getattr(owner, attr)) != after:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Cinematic setter did not match captured native values.")
            expected = self.expected_after(expected, owner, attr, after)
            self.validate(expected)
        self.bpy.context.view_layer.update()
        self.validate(self.desired)

    def restore(self):
        # Each attempted field must still hold the before value or the exact
        # value this operation tried to assign. A partial vector or user edit
        # refuses compensation instead of silently replacing that state.
        live = [_control(obj) for obj in self.controls]
        allowed = json.loads(json.dumps(self.before))
        for index, obj in enumerate(self.controls):
            for owner, attr, _before, _after in self.attempted:
                if owner == obj:
                    key = "rotation" if attr.startswith("rotation_") else attr
                    allowed[index][key] = live[index][key]
                elif owner == obj.data or (obj.type == "CAMERA" and owner == obj.data.dof):
                    key = "dof."+attr if owner != obj.data else attr
                    allowed[index]["settings"][key] = live[index]["settings"][key]
        if live != allowed:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Unowned cinematic controls changed; compensation refused.")
        for owner, attr, before, after in self.attempted:
            if _value(getattr(owner, attr)) not in (before, after):
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Cinematic output was replaced; compensation refused.")
        self.validate(live, recovery=True)
        expected = live
        for owner, attr, before, after in reversed(self.attempted):
            self.validate(expected, recovery=True)
            if _value(getattr(owner, attr)) not in (before, after):
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Cinematic output was replaced; compensation refused.")
            setattr(owner, attr, before)
            expected = self.expected_after(expected, owner, attr, before)
            self.validate(expected, recovery=True)
        self.bpy.context.view_layer.update()
        self.validate(self.before, recovery=True)

    def expected_after(self, expected, owner, attr, value):
        expected = json.loads(json.dumps(expected))
        for index, obj in enumerate(self.controls):
            if owner == obj:
                expected[index]["rotation" if attr.startswith("rotation_") else attr] = value
            elif owner == obj.data:
                expected[index]["settings"][attr] = value
            elif obj.type == "CAMERA" and owner == obj.data.dof:
                expected[index]["settings"]["dof."+attr] = value
        return expected


def _failure(transaction, error, effects=None):
    restored = False
    try:
        transaction.restore()
        restored = True
    except Exception:
        LOGGER.exception("Cinematic compensation could not be verified")
    return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
        "Cinematic operation did not complete; inspect current controls and recovery evidence.",
        {"execution_started": bool(transaction.attempted), "rollback_verified": restored,
         "possible_mutation": bool(transaction.attempted) and not restored,
         "affected_objects": [obj.name for obj in transaction.controls], "verification_required": True,
         **({"external_effects": effects} if effects else {})})


def _artifact(path):
    result = {"filepath": str(path)}
    if path.is_file():
        size = path.stat().st_size
        result["file_bytes"] = size
        if size <= 16_777_216:
            result["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _render(transaction, expected, path, effects):
    """Pin a camera and fixed matched image profile; restore only owned outputs."""
    from ..viewport import _png_dimensions

    bpy, scene = transaction.bpy, transaction.bpy.context.scene
    profile = json.loads(json.dumps(transaction.profile))
    runtime = json.loads(json.dumps(transaction.runtime))
    # JSON conversion changes tuples in runtime/profile into lists; compare
    # canonical hashes in this capture guard while retaining native controls.
    def check(*, recovery=False):
        _gate(transaction.context, PREVIEW, recovery=recovery)
        controls = _controls(bpy, transaction.controls[0].name, [obj.name for obj in transaction.controls[1:]])
        if (scene.get(records.PROPERTY) != transaction.raw or records.digest(_runtime(bpy)) != records.digest(runtime)
                or records.digest(_profile(bpy, controls, transaction.record["protected_objects"])) != records.digest(profile)
                or [_control(obj) for obj in controls] != expected):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Matched capture context or protected state changed; restoration requires explicit recovery.")

    writes = [(scene, "camera", scene.camera, transaction.controls[0], None),
        (scene.render, "filepath", scene.render.filepath, str(path), "render"),
        (scene.render, "resolution_x", scene.render.resolution_x, 384, "render"),
        (scene.render, "resolution_y", scene.render.resolution_y, 256, "render"),
        (scene.render, "resolution_percentage", scene.render.resolution_percentage, 100, "render"),
        (scene.render, "use_border", scene.render.use_border, False, "render"),
        (scene.render, "use_crop_to_border", scene.render.use_crop_to_border, False, "render"),
        (scene.render.image_settings, "file_format", scene.render.image_settings.file_format, "PNG", "image"),
        (scene.render.image_settings, "color_mode", scene.render.image_settings.color_mode, "RGBA", "image"),
        (scene.render.image_settings, "color_depth", scene.render.image_settings.color_depth, "8", "image")]
    for name in ("taa_samples", "taa_render_samples"):
        if hasattr(scene.eevee, name):
            writes.append((scene.eevee, name, getattr(scene.eevee, name), 16, "eevee"))
    if hasattr(scene.eevee, "use_raytracing"):
        writes.append((scene.eevee, "use_raytracing", scene.eevee.use_raytracing, False, "eevee"))
    attempted, error = [], None
    try:
        if path.exists():
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Managed preview output is unexpectedly occupied.")
        for owner, attr, before, after, group in writes:
            check()
            attempted.append((owner, attr, before, after, group))
            setattr(owner, attr, after)
            if group is None:
                runtime["camera"] = datablock_identity(after)
            else:
                profile[group][attr] = _value(after)
            check()
        effects["render_result_replaced"] = True
        if bpy.ops.render.render(write_still=True, use_viewport=False, scene=scene.name) != {"FINISHED"}:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Matched native camera render did not finish.")
        check()
        if _png_dimensions(path) != (384, 256):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Managed camera image dimensions did not verify.")
    except Exception as failure:
        error = failure
    try:
        check(recovery=True)
        for owner, attr, before, after, group in reversed(attempted):
            check(recovery=True)
            actual = getattr(owner, attr)
            if group is None:
                if actual != after:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Active camera changed during capture; restoration refused.")
            elif _value(actual) != _value(after):
                raise BridgeError(ErrorCode.OPERATION_FAILED, "A capture setting changed; restoration refused.")
            setattr(owner, attr, before)
            if group is None:
                runtime["camera"] = None if before is None else datablock_identity(before)
            else:
                profile[group][attr] = _value(before)
            check(recovery=True)
        transaction.validate(expected, recovery=True)
    except Exception as recovery_error:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Matched capture settings could not be restored safely.",
            {"possible_mutation": True, "capture_settings_restored": False}) from recovery_error
    if error is not None:
        raise error


def preview(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, RECORD_PARAMS)
    prepared = _prepare(context, params, PREVIEW)
    transaction = _Transaction(context, prepared, PREVIEW)
    root = Path(tempfile.mkdtemp(prefix="blender-codex-cinematic-")).resolve()
    paths = [root/"current.png", root/"candidate.png"]
    effects = {"artifacts": [], "render_result_replaced": False, "native_undo_removes_external_file": False}
    try:
        transaction.validate(transaction.before)
        _render(transaction, transaction.before, paths[0], effects)
        transaction.run()
        _render(transaction, transaction.desired, paths[1], effects)
        transaction.restore()
        _gate(context, PREVIEW)
        transaction.validate(transaction.before)
    except Exception as error:
        effects["artifacts"] = [_artifact(path) for path in paths if path.exists()]
        failure = _failure(transaction, error, effects)
        if isinstance(error, BridgeError) and error.context.get("possible_mutation"):
            failure.context.update(possible_mutation=True, capture_settings_restored=False)
        raise failure from error
    effects["artifacts"] = [_artifact(path) for path in paths]
    if any("file_sha256" not in item for item in effects["artifacts"]):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Matched preview artifacts could not be completely verified.", {"external_effects": effects})
    token = records.digest({"state": prepared[-1], "nonce": uuid.uuid4().hex})
    while len(_PREVIEWS) >= 8:
        del _PREVIEWS[next(iter(_PREVIEWS))]
    _PREVIEWS[token] = prepared[-1]
    return {"changed": False, "variant_id": prepared[2]["variant_id"], "fingerprint": token,
        "before_controls": prepared[4], "candidate_controls": prepared[5],
        "current_capture": effects["artifacts"][0], "candidate_capture": effects["artifacts"][1],
        "image_profile": {"width": 384, "height": 256, "format": "PNG", "samples": 16, "raytracing": False},
        "restoration_verified": True, "protected_profile_preserved": True, "project_saved": False,
        "external_effects": effects, "verification_required": True,
        "limitations": "Static procedural EEVEE scenes only. Native refresh/render is uninterruptible until it returns; guards detect subsequent changes. Preview PNGs remain managed temporary files; Render Result is replaced and native undo does not remove files. Compare composition and lighting before apply."}


def apply(context: ToolContext, params: Mapping) -> dict:
    reject_unknown_params(params, RECORD_PARAMS | {"expected_fingerprint"})
    prepared = _prepare(context, params, APPLY)
    token = params.get("expected_fingerprint")
    if not isinstance(token, str) or _PREVIEWS.get(token) != prepared[-1]:
        raise invalid_argument("Applying a cinematic variant requires its fresh current preview fingerprint.")
    del _PREVIEWS[token]
    transaction = _Transaction(context, prepared, APPLY)
    try:
        transaction.run()
    except Exception as error:
        raise _failure(transaction, error) from error
    return {"changed": prepared[4] != prepared[5], "variant_id": prepared[2]["variant_id"],
        "controls": prepared[5], "protected_profile_preserved": True, "project_saved": False,
        "affected_objects": [obj.name for obj in prepared[3]], "verification_required": True}


def register_tools(registry: ToolRegistry) -> None:
    for name, handler, permissions, modifying, description in (
        ("scene.variant.inspect", inspect, INSPECT, False, "Inspect strict inert Scene-stored cinematic variant records and current library CAS."),
        ("scene.variant.capture", capture, EDIT, True, "Capture exact current camera/light controls and explicit protected static scene profile into bounded Scene JSON; does not save."),
        ("scene.variant.preview", preview, PREVIEW, True, "Render matched current/candidate camera images, restore owned controls and capture settings, and issue a fresh session fingerprint."),
        ("scene.variant.apply", apply, APPLY, True, "Apply an exact fresh cinematic preview with live consent, scope and protected-state checks and guarded compensation.")):
        registry.register(name, handler, toolset="scene_edit", permissions=permissions, modifies=modifying,
            batchable=False, description=description)
