# SPDX-License-Identifier: GPL-3.0-or-later
"""Finite authored save projection shared with the fixed installed reader.

No Blender import, context/evaluation getter or generic RNA recursion. This is a
declared projection, not all Main/UI/custom/SYSTEM storage or a memory cap.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import struct
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from types import (
    BuiltinFunctionType,
    GetSetDescriptorType,
    MemberDescriptorType,
    MethodDescriptorType,
    ModuleType,
    WrapperDescriptorType,
)

SCHEMA = "stock_native_project_v1"
MAX_MANIFEST = 8 * 1024 * 1024
LEGACY_IMAGE_PIXELS = 1_048_576
MAX_IMAGE_PIXELS = 16_777_216
MAX_PACKED_BYTES = 80 * 1024 * 1024
MAX_SEQUENCER_CHANNELS = 129
LARGE_MEMORY_BYTES = 8 * 1024**3
LARGE_DISK_BYTES = 2 * 1024**3
RESOURCE_KEYS = frozenset({"scope", "available_memory_bytes", "host_available_memory_bytes",
    "visible_cgroup_headroom_bytes", "visible_cgroup_levels", "disk_free_bytes", "aggregate_image_pixels",
    "required_memory_bytes", "required_disk_bytes", "measurement_is_reservation"})
FAMILIES = ("scenes", "collections", "objects", "meshes", "armatures", "actions",
            "materials", "worlds", "images", "cameras", "lights")
UI = {"window_managers", "screens", "workspaces", "all_ids"}
CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
            "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")
ALLOWED_NODES = {"ShaderNodeOutputMaterial", "ShaderNodeBsdfPrincipled", "ShaderNodeTexImage",
                 "ShaderNodeOutputWorld", "ShaderNodeBackground"}
FIELDS = {
    "objects": "type mode data parent parent_type parent_bone matrix_parent_inverse rotation_mode hide_viewport hide_render modifiers constraints vertex_groups animation_data rigid_body rigid_body_constraint particle_systems instance_type pose",
    "meshes": "is_editmode shape_keys vertices loops edges polygons uv_layers materials",
    "armatures": "is_editmode bones",
    "actions": "layers slots",
    "materials": "use_nodes node_tree diffuse_color",
    "worlds": "use_nodes node_tree",
    "images": "source is_dirty has_data packed_file channels size pixels filepath colorspace_settings alpha_mode",
    "scenes": "collection camera world unit_settings frame_start frame_end frame_current frame_subframe render rigidbody_world sequence_editor",
    "collections": "objects children",
    "cameras": "type lens ortho_scale sensor_width sensor_height clip_start clip_end shift_x shift_y",
    "lights": "type color energy",
}

# Metadata inventory for the literal accesses above and in the bounded nested
# projection below. The census reads class descriptors only, never ID values.
# A /N suffix constrains a fixed native array; unmarked shapes are recorded.
DECLARED_RNA = {
    "ID": "name:STRING library:POINTER override_library:POINTER session_uid:INT users:INT use_fake_user:BOOLEAN",
    "BlendData": " ".join(name + ":COLLECTION" for name in FAMILIES),
    "Scene": "collection:POINTER camera:POINTER world:POINTER unit_settings:POINTER frame_start:INT frame_end:INT frame_current:INT frame_subframe:FLOAT render:POINTER rigidbody_world:POINTER sequence_editor:POINTER",
    "SequenceEditor": "strips:COLLECTION strips_all:COLLECTION meta_stack:COLLECTION channels:COLLECTION active_strip:POINTER",
    "SequenceTimelineChannel": "name:STRING lock:BOOLEAN/0 mute:BOOLEAN/0",
    "Object": "type:ENUM mode:ENUM data:POINTER parent:POINTER parent_type:ENUM parent_bone:STRING matrix_parent_inverse:FLOAT/16 rotation_mode:ENUM hide_viewport:BOOLEAN hide_render:BOOLEAN modifiers:COLLECTION constraints:COLLECTION vertex_groups:COLLECTION animation_data:POINTER rigid_body:POINTER rigid_body_constraint:POINTER particle_systems:COLLECTION instance_type:ENUM pose:POINTER",
    "Mesh": "is_editmode:BOOLEAN shape_keys:POINTER vertices:COLLECTION loops:COLLECTION edges:COLLECTION polygons:COLLECTION uv_layers:COLLECTION materials:COLLECTION",
    "MeshVertex": "co:FLOAT/3 groups:COLLECTION",
    "VertexGroupElement": "group:INT weight:FLOAT",
    "MeshEdge": "vertices:INT/2",
    "MeshPolygon": "vertices:INT material_index:INT use_smooth:BOOLEAN",
    "MeshUVLoopLayer": "name:STRING active_render:BOOLEAN data:COLLECTION",
    "MeshUVLoop": "uv:FLOAT/2",
    "Armature": "is_editmode:BOOLEAN bones:COLLECTION",
    "Bone": "name:STRING parent:POINTER head_local:FLOAT/3 tail_local:FLOAT/3 matrix_local:FLOAT/16 use_deform:BOOLEAN",
    "Pose": "bones:COLLECTION",
    "PoseBone": "name:STRING rotation_mode:ENUM constraints:COLLECTION",
    "VertexGroup": "index:INT name:STRING",
    "ArmatureModifier": "name:STRING type:ENUM object:POINTER show_viewport:BOOLEAN show_render:BOOLEAN use_vertex_groups:BOOLEAN",
    "AnimData": "drivers:COLLECTION nla_tracks:COLLECTION action:POINTER action_slot:POINTER",
    "Action": "layers:COLLECTION slots:COLLECTION",
    "ActionLayer": "name:STRING strips:COLLECTION",
    "ActionStrip": "type:ENUM",
    "ActionKeyframeStrip": "channelbags:COLLECTION",
    "ActionChannelbag": "slot_handle:INT fcurves:COLLECTION",
    "ActionSlot": "handle:INT identifier:STRING",
    "FCurve": "modifiers:COLLECTION keyframe_points:COLLECTION data_path:STRING array_index:INT extrapolation:ENUM",
    "Keyframe": "co:FLOAT/2 handle_left:FLOAT/2 handle_right:FLOAT/2 interpolation:ENUM handle_left_type:ENUM handle_right_type:ENUM",
    "Material": "use_nodes:BOOLEAN node_tree:POINTER diffuse_color:FLOAT/4",
    "World": "use_nodes:BOOLEAN node_tree:POINTER",
    "Image": "source:ENUM is_dirty:BOOLEAN has_data:BOOLEAN packed_file:POINTER channels:INT size:INT/2 pixels:FLOAT filepath:STRING colorspace_settings:POINTER alpha_mode:ENUM",
    "PackedFile": "size:INT data:STRING",
    "ColorManagedInputColorspaceSettings": "name:ENUM",
    "Collection": "objects:COLLECTION children:COLLECTION",
    "UnitSettings": "system:ENUM scale_length:FLOAT",
    "RenderSettings": "fps:INT fps_base:FLOAT",
    "Camera": "type:ENUM lens:FLOAT ortho_scale:FLOAT sensor_width:FLOAT sensor_height:FLOAT clip_start:FLOAT clip_end:FLOAT shift_x:FLOAT shift_y:FLOAT",
    "Light": "type:ENUM color:FLOAT/3",
    "NodeTree": "nodes:COLLECTION links:COLLECTION",
    "Node": "name:STRING bl_idname:STRING mute:BOOLEAN inputs:COLLECTION",
    "NodeSocket": "identifier:STRING type:ENUM",
    "NodeLink": "from_node:POINTER from_socket:POINTER to_node:POINTER to_socket:POINTER",
    "ShaderNodeTexImage": "image:POINTER extension:ENUM interpolation:ENUM projection:ENUM",
    "NodeSocketFloat": "default_value:FLOAT",
    "NodeSocketInt": "default_value:INT",
    "NodeSocketBool": "default_value:BOOLEAN",
    "NodeSocketVector": "default_value:FLOAT/3",
    "NodeSocketColor": "default_value:FLOAT/4",
    "NodeSocketShader": "",
    "Property": "identifier:STRING type:ENUM is_runtime:BOOLEAN is_readonly:BOOLEAN",
    "BoolProperty": "array_length:INT",
    "IntProperty": "array_length:INT",
    "FloatProperty": "array_length:INT",
    "Struct": "properties:COLLECTION functions:COLLECTION",
    "Function": "identifier:STRING",
}
for _class in ("AreaLight", "PointLight", "SpotLight", "SunLight"):
    DECLARED_RNA[_class] = "energy:FLOAT"
for _class in sorted(ALLOWED_NODES):
    if _class not in DECLARED_RNA:
        DECLARED_RNA[_class] = ""
DECLARED_RNA["ShaderNodeTree"] = "nodes:COLLECTION links:COLLECTION"
OPTIONAL_RNA = {
    name: "animation_data:POINTER" for name in (
        "Scene", "Mesh", "Armature", "Action", "Material", "World", "Image", "Camera", "Light", "Collection", "NodeTree")
}
OPTIONAL_RNA["Scene"] += " node_tree:POINTER compositing_node_group:POINTER"
OPTIONAL_RNA["SequenceEditor"] = "sequences:COLLECTION sequences_all:COLLECTION"
OPTIONAL_RNA["SequenceTimelineChannel"] = "number:INT/0"
SEQUENCER_WRITABLE_RNA = {"SequenceEditor": {"active_strip"},
                          "SequenceTimelineChannel": {"name", "lock", "mute"}}
_TYPE_DICT = type.__dict__["__dict__"]
_TYPE_MRO = type.__dict__["__mro__"]
_TYPE_NAME = type.__dict__["__name__"]
_TYPE_GET = type.__dict__["__getattribute__"]
_TYPE_CALL = type.__dict__["__call__"]
_MODULE_DICT = ModuleType.__dict__["__dict__"]
OPTIONAL_RNA["PoseBone"] = " ".join(name + ":FLOAT/" + ("4" if "quaternion" in name else "3")
                                    for name in CHANNELS if name.startswith("delta_"))
for _class in ("Object", "PoseBone"):
    DECLARED_RNA[_class] += " " + " ".join(
        name + ":FLOAT/" + ("4" if name in {"rotation_quaternion", "rotation_axis_angle", "delta_rotation_quaternion"} else "3")
        for name in CHANNELS if _class == "Object" or not name.startswith("delta_"))


def descriptor_metadata(descriptor):
    row = {name: getattr(descriptor, name) for name in ("identifier", "type", "is_runtime", "is_readonly")}
    if descriptor.bl_rna.properties.get("array_length") is not None:
        row["array_length"] = descriptor.array_length
    return row


def schema_census(types):
    """Bounded class-RNA census; no instance/value, default or pointee reads."""
    result = {"schema": "native_save_class_metadata_v1", "classes": {}, "mismatches": [],
              "scope": "declared descriptors/functions only; no ID values or hidden-storage proof"}
    for name, required in DECLARED_RNA.items():
        native = getattr(types, name, None)
        row = {"present": native is not None, "fields": {}, "functions": []}
        result["classes"][name] = row
        if native is None:
            result["mismatches"].append({"class": name, "reason": "CLASS_MISSING"})
            continue
        row["functions"] = [function.identifier for function in native.bl_rna.functions]
        for optional, layout in ((False, required), (True, OPTIONAL_RNA.get(name, ""))):
            for item in layout.split():
                field, expected = item.split(":")
                kind, _, shape = expected.partition("/")
                descriptor = native.bl_rna.properties.get(field)
                actual = None if descriptor is None else descriptor_metadata(descriptor)
                row["fields"][field] = {"optional": optional, "metadata": actual}
                reason = None
                if actual is None:
                    reason = None if optional else "FIELD_MISSING"
                elif (actual["identifier"] != field or actual["type"] != kind or actual["is_runtime"] is not False
                      or (name in SEQUENCER_WRITABLE_RNA
                          and actual["is_readonly"] is not (field not in SEQUENCER_WRITABLE_RNA[name]))):
                    reason = "FIELD_METADATA_MISMATCH"
                elif shape and actual.get("array_length") != int(shape):
                    reason = "FIELD_SHAPE_MISMATCH"
                if reason:
                    result["mismatches"].append({"class": name, "field": field, "reason": reason})
    scene = result["classes"]["Scene"]["fields"]
    if scene and not any(scene[name]["metadata"] is not None for name in ("node_tree", "compositing_node_group")):
        result["mismatches"].append({"class": "Scene", "reason": "COMPOSITOR_SCHEMA_MISSING"})
    # These are C Python wrapper methods, not RNA Function descriptors.
    native_id = getattr(types, "ID", None)
    result["python_methods"] = {"ID.as_pointer": native_id is not None and callable(getattr(native_id, "as_pointer", None)),
                                "bpy_prop_array.foreach_get": "C wrapper source binding; not an RNA function"}
    if not result["python_methods"]["ID.as_pointer"]:
        result["mismatches"].append({"class": "ID", "reason": "AS_POINTER_METHOD_MISSING"})
    return result


class ProfileRefused(ValueError):
    pass


def require(value, reason):
    if not value:
        raise ProfileRefused(reason)


@dataclass(frozen=True, slots=True)
class ResourceDirectory:
    """Directory identity only; the source caller still owns live path consent."""
    path: str
    ancestry: tuple


def _open_resource_directory(path):
    require(type(path) is str and 0 < len(path.encode("utf-8")) <= 4096
            and path.startswith("/") and not path.startswith("//") and "\\" not in path
            and not any(ord(char) < 32 or ord(char) == 127 for char in path)
            and not any(part in {".", ".."} for part in path.split("/")), "RESOURCE_DIRECTORY_INVALID")
    parts = Path(path).parts
    require(len(parts) <= 128, "RESOURCE_DIRECTORY_INVALID")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    rows = []
    try:
        info = os.fstat(descriptor)
        rows.append(("/", info.st_dev, info.st_ino))
        for part in parts[1:]:
            opened = os.open(part, flags, dir_fd=descriptor)
            previous, descriptor = descriptor, opened
            os.close(previous)
            info = os.fstat(descriptor)
            require(stat.S_ISDIR(info.st_mode), "RESOURCE_DIRECTORY_INVALID")
            rows.append((part, info.st_dev, info.st_ino))
        return descriptor, tuple(rows)
    except BaseException:
        os.close(descriptor)
        raise


def bind_resource_directory(path):
    """Resolve without following links, before any filesystem-space query."""
    try:
        descriptor, ancestry = _open_resource_directory(path)
        os.close(descriptor)
        return ResourceDirectory(str(Path(path)), ancestry)
    except (OSError, UnicodeError) as cause:
        raise ProfileRefused("RESOURCE_DIRECTORY_UNAVAILABLE") from cause


def _resource_text(path, maximum):
    with open(path, "rb") as stream:
        raw = stream.read(maximum + 1)
    require(0 < len(raw) <= maximum, "RESOURCE_MEASUREMENT_UNAVAILABLE")
    return raw.decode("utf-8", "strict")


def _resource_integer(value):
    require(type(value) is str and re.fullmatch(r"[0-9]{1,19}", value) is not None,
            "RESOURCE_MEASUREMENT_UNAVAILABLE")
    parsed = int(value)
    require(0 <= parsed <= 2**63 - 1, "RESOURCE_MEASUREMENT_UNAVAILABLE")
    return parsed


def _visible_cgroup_paths(cgroup, mountinfo):
    rows = [line[3:] for line in cgroup.splitlines() if line.startswith("0::")]
    require(len(rows) == 1, "RESOURCE_CGROUP_UNAVAILABLE")
    group = rows[0]
    require(group.startswith("/") and not group.startswith("//") and "\\" not in group
            and len(group.encode("utf-8")) <= 4096
            and not any(ord(char) < 32 or ord(char) == 127 for char in group)
            and not any(part in {".", ".."} for part in group.split("/")), "RESOURCE_CGROUP_UNAVAILABLE")
    mounts = []
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        fields, filesystem = before.split(), after.split()
        if (separator and filesystem and filesystem[0] == "cgroup2" and len(fields) >= 6
                and fields[4] == "/sys/fs/cgroup"):
            mounts.append(fields[3])
    require(len(mounts) == 1, "RESOURCE_CGROUP_UNAVAILABLE")
    root = mounts[0]
    require(root.startswith("/") and not root.startswith("//") and "\\" not in root
            and len(root.encode("utf-8")) <= 4096
            and not any(ord(char) < 32 or ord(char) == 127 for char in root)
            and (root == "/.." or not any(part in {".", ".."} for part in root.split("/"))),
            "RESOURCE_CGROUP_UNAVAILABLE")
    # A cgroup namespace may expose its root as / even when mountinfo retains
    # /.. from the supervising namespace. No path outside the visible mount is
    # queried or treated as a known ancestor limit.
    if group == "/" or root in {"/", "/.."}:
        relative = group.lstrip("/")
    else:
        require(group == root or group.startswith(root.rstrip("/") + "/"), "RESOURCE_CGROUP_UNAVAILABLE")
        relative = group[len(root):].lstrip("/")
    base = Path("/sys/fs/cgroup")
    current, paths = base / relative, []
    while True:
        require(len(paths) < 128 and (current == base or base in current.parents), "RESOURCE_CGROUP_UNAVAILABLE")
        paths.append(current)
        if current == base:
            return tuple(paths)
        current = current.parent


def available_memory_facts():
    """Sample host and every visible v2 ancestor; this reserves no memory."""
    require(sys.platform == "linux", "LARGE_IMAGE_RESOURCE_PLATFORM_UNQUALIFIED")
    try:
        meminfo = _resource_text("/proc/meminfo", 16384)
        rows = [line.split() for line in meminfo.splitlines() if line.startswith("MemAvailable:")]
        require(len(rows) == 1 and len(rows[0]) == 3 and rows[0][2] == "kB", "RESOURCE_MEASUREMENT_UNAVAILABLE")
        host = _resource_integer(rows[0][1]) * 1024
        require(host <= 2**63 - 1, "RESOURCE_MEASUREMENT_UNAVAILABLE")
        paths = _visible_cgroup_paths(_resource_text("/proc/self/cgroup", 65536),
                                     _resource_text("/proc/self/mountinfo", 1024 * 1024))
        headrooms = []
        for path in paths:
            maximum = _resource_text(path / "memory.max", 64).strip()
            current = _resource_integer(_resource_text(path / "memory.current", 64).strip())
            if maximum != "max":
                headrooms.append(max(0, _resource_integer(maximum) - current))
        visible = min(headrooms) if headrooms else None
        return {"available_memory_bytes": min(host, visible) if visible is not None else host,
                "host_available_memory_bytes": host, "visible_cgroup_headroom_bytes": visible,
                "visible_cgroup_levels": len(paths)}
    except (OSError, UnicodeError, ValueError) as cause:
        if type(cause) is ProfileRefused:
            raise
        raise ProfileRefused("RESOURCE_MEASUREMENT_UNAVAILABLE") from cause


def validate_resource_facts(facts):
    require(type(facts) is dict and set(facts) == RESOURCE_KEYS, "RESOURCE_FACTS_INVALID")
    require(type(facts["scope"]) is str and facts["scope"] == "LINUX_HOST_AND_VISIBLE_CGROUP_V2"
            and facts["measurement_is_reservation"] is False, "RESOURCE_FACTS_INVALID")
    for name in RESOURCE_KEYS - {"scope", "measurement_is_reservation", "visible_cgroup_headroom_bytes"}:
        require(type(facts[name]) is int and 0 <= facts[name] <= 2**63 - 1, "RESOURCE_FACTS_INVALID")
    visible = facts["visible_cgroup_headroom_bytes"]
    require(visible is None or (type(visible) is int and 0 <= visible <= 2**63 - 1), "RESOURCE_FACTS_INVALID")
    expected_memory = min(facts["host_available_memory_bytes"], visible) if visible is not None else facts["host_available_memory_bytes"]
    require(1 <= facts["visible_cgroup_levels"] <= 128
            and LEGACY_IMAGE_PIXELS < facts["aggregate_image_pixels"] <= MAX_IMAGE_PIXELS
            and facts["required_memory_bytes"] == LARGE_MEMORY_BYTES
            and facts["required_disk_bytes"] == LARGE_DISK_BYTES
            and facts["available_memory_bytes"] == expected_memory,
            "RESOURCE_FACTS_INVALID")
    require(facts["available_memory_bytes"] >= LARGE_MEMORY_BYTES, "LARGE_IMAGE_MEMORY_BUDGET")
    require(facts["disk_free_bytes"] >= LARGE_DISK_BYTES, "LARGE_IMAGE_DISK_BUDGET")
    return facts


def check_large_resources(pixels, directory):
    require(type(pixels) is int and 0 <= pixels <= MAX_IMAGE_PIXELS, "IMAGE_PIXEL_BUDGET")
    if pixels <= LEGACY_IMAGE_PIXELS:
        return None
    require(type(directory) is ResourceDirectory, "RESOURCE_DIRECTORY_REQUIRED")
    descriptor = after = None
    try:
        descriptor, ancestry = _open_resource_directory(directory.path)
        require(ancestry == directory.ancestry, "RESOURCE_DIRECTORY_CHANGED")
        # fstatvfs measures the pinned descriptor, never a freshly resolved path.
        info = os.fstatvfs(descriptor)
        free = info.f_bavail * info.f_frsize
        memory = available_memory_facts()
        after, observed = _open_resource_directory(directory.path)
        require(observed == directory.ancestry, "RESOURCE_DIRECTORY_CHANGED")
        facts = {"scope": "LINUX_HOST_AND_VISIBLE_CGROUP_V2", **memory, "disk_free_bytes": free,
                 "aggregate_image_pixels": pixels, "required_memory_bytes": LARGE_MEMORY_BYTES,
                 "required_disk_bytes": LARGE_DISK_BYTES, "measurement_is_reservation": False}
        return validate_resource_facts(facts)
    except OSError as cause:
        raise ProfileRefused("RESOURCE_DIRECTORY_UNAVAILABLE") from cause
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if after is not None:
            os.close(after)


def projection_image_pixels(value):
    require(type(value) is dict and type(value.get("images")) is list and len(value["images"]) <= 4,
            "IMAGE_PROJECTION_SHAPE")
    total = 0
    for row in value["images"]:
        require(type(row) is dict and type(row.get("size")) is list and len(row["size"]) == 2
                and all(type(v) is int and 0 < v <= 4096 for v in row["size"]), "IMAGE_PROJECTION_SHAPE")
        total += row["size"][0] * row["size"][1]
        require(total <= MAX_IMAGE_PIXELS, "IMAGE_PIXEL_BUDGET")
    return total


def screen(owner, names):
    for name in names:
        descriptor = owner.bl_rna.properties.get(name)
        require(descriptor is not None and descriptor.identifier == name and descriptor.is_runtime is False,
                "NATIVE_DESCRIPTOR_REQUIRED:" + type(owner).__name__ + "." + name)


def canonical(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    require(len(raw) <= MAX_MANIFEST, "PROFILE_MANIFEST_BUDGET")
    return raw


def floats(values):
    require(len(values) <= 16, "PROFILE_VECTOR_SHAPE")
    output = []
    for value in values:
        require(type(value) in {int, float} and math.isfinite(value) and abs(value) <= 1e12,
                "PROFILE_NONFINITE_OR_MAGNITUDE")
        output.append(struct.pack("<f", value).hex())
    return output


def scalar(value):
    if type(value) in {str, bool, int}:
        require(type(value) is not str or len(value.encode()) <= 1024, "PROFILE_STRING_BUDGET")
        return value
    return floats([value])[0]


def identity(owner):
    screen(owner, ["name", "library", "override_library", "session_uid", "users", "use_fake_user"])
    require(owner.library is None and owner.override_library is None, "LINKED_OR_OVERRIDE_UNSUPPORTED")
    pointer, uid = owner.as_pointer(), owner.session_uid
    require(type(pointer) is int and pointer > 0 and type(uid) is int and uid > 0, "ID_IDENTITY_UNAVAILABLE")
    return pointer, uid


def curves(action):
    result = []
    require(len(action.layers) <= 4 and len(action.slots) <= 64, "ACTION_LAYOUT_BUDGET")
    for layer in action.layers:
        require(len(layer.strips) <= 4, "ACTION_LAYOUT_BUDGET")
        for strip in layer.strips:
            require(strip.type == "KEYFRAME", "ACTION_STRIP_UNSUPPORTED")
            require(len(strip.channelbags) <= 32, "ACTION_LAYOUT_BUDGET")
            for bag in strip.channelbags:
                require(len(result) + len(bag.fcurves) <= 64, "ACTION_CURVE_BUDGET")
                for curve in bag.fcurves:
                    require(len(curve.modifiers) == 0, "FCURVE_MODIFIERS_UNSUPPORTED")
                    require(len(curve.keyframe_points) <= 2048, "ACTION_KEY_BUDGET")
                    result.append((layer, strip, bag, curve))
    return result


def driven(owner):
    data = owner.animation_data
    if data is None:
        return set()
    require(not data.drivers and not data.nla_tracks, "DRIVERS_OR_NLA_UNSUPPORTED")
    if data.action is None:
        return set()
    require(data.action_slot is not None, "ACTION_SLOT_UNAVAILABLE")
    result = set()
    for _layer, _strip, bag, curve in curves(data.action):
        if bag.slot_handle == data.action_slot.handle:
            result.add((curve.data_path, curve.array_index))
    return result


def no_animation(owner):
    descriptor = owner.bl_rna.properties.get("animation_data")
    if descriptor is not None:
        screen(owner, ["animation_data"])
        require(owner.animation_data is None, "NON_OBJECT_ANIMATION_UNSUPPORTED")
    return descriptor is not None


def empty_compositor(owner):
    present = []
    for name in ("node_tree", "compositing_node_group"):
        if owner.bl_rna.properties.get(name) is not None:
            screen(owner, [name])
            require(getattr(owner, name) is None, "COMPOSITOR_UNSUPPORTED")
            present.append(name)
    require(present, "COMPOSITOR_SCHEMA_UNSUPPORTED")
    return present


def _sequencer_slot(cls, name, reason):
    # Direct type descriptors bypass custom metaclass/class getters.
    chain = _TYPE_MRO.__get__(cls, type(cls))
    require(type(chain) is tuple and 1 <= len(chain) <= 16, reason)
    for parent in chain:
        namespace = _TYPE_DICT.__get__(parent, type(parent))
        if name in namespace:
            return namespace[name]
    return None


def _sequencer_origin(owner, native_class):
    """Class-only canonical C-origin proof before ANY instance getter.

    Uses the already-loaded stock bpy module, never imports it. The exact
    bpy.types module's bound C resolver bypasses mutable named class aliases.
    This is a finite stock-registry assumption, not a hostile-C-extension proof.
    """
    reason = ("SCENE_CACHE_OR_SEQUENCER_UNSUPPORTED" if native_class == "SequenceEditor"
              else "SEQUENCER_CLASS_UNSUPPORTED")
    require(native_class in SEQUENCER_WRITABLE_RNA, reason)
    cls = type(owner)
    require(_TYPE_NAME.__get__(cls, type(cls)) == native_class, reason)
    meta = type(cls)
    require(_sequencer_slot(meta, "__getattribute__", reason) is _TYPE_GET
            and _sequencer_slot(meta, "__call__", reason) is _TYPE_CALL
            and _sequencer_slot(meta, "__getattr__", reason) is None, reason)
    bpy = sys.modules.get("bpy")
    require(type(bpy) is ModuleType, reason)
    registry = _MODULE_DICT.__get__(bpy).get("types")
    require(type(registry) is ModuleType, reason)
    namespace = _MODULE_DICT.__get__(registry)
    require(type(namespace.get("__name__")) is str and namespace["__name__"] == "bpy.types", reason)
    resolver = namespace.get("__getattr__")
    require(type(resolver) is BuiltinFunctionType and resolver.__self__ is registry
            and resolver.__name__ == "__getattr__" and type(resolver.__module__) is str
            and resolver.__module__ == "bpy.types", reason)
    canonical = resolver(native_class)
    require(canonical is cls, reason)
    chain = _TYPE_MRO.__get__(cls, meta)
    require(len(chain) == 3 and chain[-1] is object
            and _TYPE_NAME.__get__(chain[1], type(chain[1])) == "bpy_struct", reason)
    base = chain[1]
    getter = _sequencer_slot(base, "__getattribute__", reason)
    pointer = _sequencer_slot(base, "as_pointer", reason)
    constructor = _sequencer_slot(base, "__new__", reason)
    initializer = _sequencer_slot(base, "__init__", reason)
    require(type(getter) is WrapperDescriptorType and getter.__objclass__ is base
            and type(pointer) is MethodDescriptorType and pointer.__objclass__ is base
            and type(constructor) is BuiltinFunctionType
            and type(initializer) is WrapperDescriptorType
            and initializer.__objclass__ in (base, object), reason)
    for field, slot in (("__getattribute__", getter), ("as_pointer", pointer),
                        ("__new__", constructor), ("__init__", initializer), ("__getattr__", None)):
        require(_sequencer_slot(cls, field, reason) is slot, reason)
    struct = resolver("Struct")
    require(_sequencer_slot(struct, "__getattribute__", reason) is getter
            and _sequencer_slot(struct, "__getattr__", reason) is None, reason)
    rna = _TYPE_DICT.__get__(cls, meta).get("bl_rna")
    require(type(rna) is struct, reason)
    fields = [item.split(":")[0] for layout in (DECLARED_RNA[native_class], OPTIONAL_RNA[native_class])
              for item in layout.split()]
    for native, names in ((cls, fields), (struct, ("identifier", "properties"))):
        for field in names:
            descriptor = _sequencer_slot(native, field, reason)
            require(descriptor is None or (type(descriptor) in (GetSetDescriptorType, MemberDescriptorType)
                    and descriptor.__objclass__ in _TYPE_MRO.__get__(native, type(native))), reason)
    return rna


def _sequencer_schema(owner, native_class):
    """Qualify finite direct class metadata before reading editor/channel values."""
    rna = _sequencer_origin(owner, native_class)
    try:
        require(rna.identifier == native_class, "SEQUENCER_CLASS_UNSUPPORTED")
        present = set()
        layouts = ((False, DECLARED_RNA[native_class]),
                   (True, OPTIONAL_RNA.get(native_class, "")))
        declared = set()
        for optional, layout in layouts:
            for item in layout.split():
                field, expected = item.split(":")
                declared.add(field)
                kind, _, shape = expected.partition("/")
                descriptor = rna.properties.get(field)
                if descriptor is None:
                    require(optional, "SEQUENCER_SCHEMA_UNSUPPORTED")
                    continue
                metadata = descriptor_metadata(descriptor)
                require(metadata["identifier"] == field and metadata["type"] == kind
                        and metadata["is_runtime"] is False
                        and metadata["is_readonly"] is (field not in SEQUENCER_WRITABLE_RNA[native_class])
                        and (not shape or metadata.get("array_length") == int(shape)),
                        "SEQUENCER_SCHEMA_UNSUPPORTED")
                present.add(field)
        # Unknown editor collections could carry strips/dependencies. A channel
        # admits only its complete reviewed public schema (plus Struct.rna_type).
        for index, descriptor in enumerate(rna.properties):
            require(index < 128, "SEQUENCER_METADATA_BUDGET")
            if descriptor.identifier == "rna_type":
                require(descriptor.type == "POINTER" and descriptor.is_runtime is False
                        and descriptor.is_readonly is True,
                        "SEQUENCER_SCHEMA_UNSUPPORTED")
            require(descriptor.identifier in declared | {"rna_type"}
                    or (native_class == "SequenceEditor" and descriptor.type != "COLLECTION"),
                    "SEQUENCER_SCHEMA_UNSUPPORTED")
        return present
    except (AttributeError, KeyError, TypeError, ValueError) as cause:
        if isinstance(cause, ProfileRefused):
            raise
        raise ProfileRefused("SEQUENCER_SCHEMA_UNSUPPORTED") from cause


def _empty_sequencer_collection(values):
    # One sentinel, no len/list/recursive traversal of a possibly nonempty VSE.
    sentinel = object()
    require(next(iter(values), sentinel) is sentinel, "NONEMPTY_SEQUENCER_UNSUPPORTED")


def empty_sequencer(editor):
    """Project only an existing empty native editor; never create or clear it."""
    present = _sequencer_schema(editor, "SequenceEditor")
    # The C strips_all getter allocates a recursive vector. Qualify top-level
    # emptiness FIRST, including when another empty-looking field is supplied.
    _empty_sequencer_collection(editor.strips)
    _empty_sequencer_collection(editor.meta_stack)
    require(editor.active_strip is None, "NONEMPTY_SEQUENCER_UNSUPPORTED")
    aliases = [name for name in ("sequences", "sequences_all") if name in present]
    if "sequences" in present:
        _empty_sequencer_collection(editor.sequences)
    _empty_sequencer_collection(editor.strips_all)
    if "sequences_all" in present:
        _empty_sequencer_collection(editor.sequences_all)
    native_channels = editor.channels
    count = len(native_channels)
    require(count <= MAX_SEQUENCER_CHANNELS, "SEQUENCER_CHANNEL_BUDGET")
    # Bound even a malformed collection whose count disagrees with iteration.
    sentinel, iterator, ordered = object(), iter(native_channels), []
    for _index in range(MAX_SEQUENCER_CHANNELS + 1):
        channel = next(iterator, sentinel)
        if channel is sentinel:
            break
        require(len(ordered) < MAX_SEQUENCER_CHANNELS, "SEQUENCER_CHANNEL_BUDGET")
        ordered.append(channel)
    require(len(ordered) == count, "SEQUENCER_CHANNEL_LAYOUT_UNSUPPORTED")
    # All channel schemas must pass before ANY channel value is observed.
    schemas = [_sequencer_schema(channel, "SequenceTimelineChannel") for channel in ordered]
    channels = []
    for channel, schema in zip(ordered, schemas, strict=True):
        name, lock, mute = channel.name, channel.lock, channel.mute
        number = channel.number if "number" in schema else "UNOBSERVED"
        require(type(name) is str and type(lock) is bool and type(mute) is bool
                and ("number" not in schema or type(number) is int),
                "SEQUENCER_CHANNEL_VALUE_UNSUPPORTED")
        try:
            require(len(name.encode("utf-8")) <= 1024, "PROFILE_STRING_BUDGET")
        except UnicodeError as cause:
            raise ProfileRefused("SEQUENCER_CHANNEL_VALUE_UNSUPPORTED") from cause
        channels.append({"name": scalar(name), "lock": lock, "mute": mute, "number": number})
    return {"strips": [], "strips_all": [], "meta_stack": [], "active_strip": None,
            "native_empty_aliases": aliases, "channels": channels}


def channels(owner, exclusions, prefix=""):
    return {name: [None if (prefix + name, index) in exclusions else value
                   for index, value in enumerate(channel_values(owner, name))]
            for name in CHANNELS if owner.bl_rna.properties.get(name) is not None}


def channel_values(owner, name):
    screen(owner, [name])
    descriptor = owner.bl_rna.properties[name]
    length = 4 if name in {"rotation_quaternion", "rotation_axis_angle", "delta_rotation_quaternion"} else 3
    require(descriptor.type == "FLOAT" and descriptor.array_length == length, "NATIVE_CHANNEL_SHAPE")
    return floats(getattr(owner, name))


def tree_projection(tree, counts):
    if tree is None:
        return None
    screen(tree, ["nodes", "links"])
    animation_descriptor = no_animation(tree)
    counts["nodes"] += len(tree.nodes)
    counts["links"] += len(tree.links)
    require(counts["nodes"] <= 64 and counts["links"] <= 128, "NODE_BUDGET")
    nodes = []
    for node in tree.nodes:
        require(node.bl_idname in ALLOWED_NODES, "SHADER_NODE_UNSUPPORTED")
        screen(node, ["name", "mute", "inputs"])
        require(len(node.inputs) <= 64, "SHADER_SOCKET_BUDGET")
        inputs = []
        for socket in node.inputs:
            screen(socket, ["identifier", "type"])
            if socket.type == "SHADER":
                default = None
            elif socket.type in {"RGBA", "VECTOR"}:
                default = floats(socket.default_value)
            elif socket.type in {"VALUE", "INT", "BOOLEAN"}:
                default = scalar(socket.default_value)
            else:
                raise ProfileRefused("SHADER_SOCKET_UNSUPPORTED")
            inputs.append([socket.identifier, socket.type, default])
        item = {"name": node.name, "type": node.bl_idname, "mute": node.mute, "inputs": inputs}
        if node.bl_idname == "ShaderNodeTexImage":
            item.update(image=node.image.name if node.image else None, extension=node.extension,
                        interpolation=node.interpolation, projection=node.projection)
        nodes.append(item)
    return {"native_animation_descriptor_present": animation_descriptor,
            "nodes": sorted(nodes, key=lambda row: row["name"]),
            "links": sorted([link.from_node.name, link.from_socket.identifier,
                             link.to_node.name, link.to_socket.identifier] for link in tree.links)}


@dataclass(frozen=True, slots=True)
class Projection:
    raw: bytes
    identities: tuple
    driven_raw: tuple
    losses: tuple = ()
    resource_checks: tuple = ()

    @property
    def digest(self):
        return hashlib.sha256(self.raw).hexdigest()


def capture(data, *, resource_directory=None):
    families = {name: getattr(data, name) for name in FAMILIES}
    require(sum(len(values) for values in families.values()) <= 128, "PROFILE_ID_BUDGET")
    inventory = {name: list(values) for name, values in families.items()}
    require(len(inventory["scenes"]) == 1, "ONE_SCENE_REQUIRED")
    require(sum(map(len, inventory.values())) <= 128 and len(inventory["objects"]) <= 32
            and len(inventory["collections"]) <= 16 and len(inventory["materials"]) <= 8
            and len(inventory["images"]) <= 4, "PROFILE_ID_BUDGET")
    for prop in data.bl_rna.properties:
        if prop.type == "COLLECTION" and prop.identifier not in set(FAMILIES) | UI:
            require(len(getattr(data, prop.identifier)) == 0, "UNSUPPORTED_ID_FAMILY:" + prop.identifier)
    counts = {key: 0 for key in ("vertices", "corners", "bones", "curves", "keys", "pixels", "packed", "nodes", "links", "uv", "weights")}
    result, identities, raw_driven, orphans, resource_checks = {"schema": SCHEMA}, [], [], [], []
    for family, owners in inventory.items():
        rows = []
        for owner in sorted(owners, key=lambda value: value.name):
            identities.append((family, owner.name, *identity(owner)))
            require(len(owner.name.encode()) <= 255, "NAME_BUDGET")
            if family != "scenes" and owner.users == 0 and not owner.use_fake_user:
                orphans.append([family, owner.name])
                continue
            row = {"name": owner.name, "fake_user": owner.use_fake_user}
            screen(owner, FIELDS[family].split())
            if family != "objects":
                row["native_animation_descriptor_present"] = no_animation(owner)
            if family == "objects":
                require(owner.type in {"MESH", "EMPTY", "ARMATURE", "CAMERA", "LIGHT"}
                        and owner.mode == "OBJECT" and not owner.constraints, "OBJECT_PROFILE_UNSUPPORTED")
                require(owner.rigid_body is None and owner.rigid_body_constraint is None
                        and not owner.particle_systems and owner.instance_type == "NONE", "OBJECT_CACHE_OR_INSTANCE_UNSUPPORTED")
                exclusions = driven(owner)
                raw_driven.append((owner.name, tuple((name, tuple(channel_values(owner, name))) for name in CHANNELS)))
                row.update(type=owner.type, data=owner.data.name if owner.data else None,
                           parent=owner.parent.name if owner.parent else None,
                           parent_type=owner.parent_type, parent_bone=owner.parent_bone,
                           parent_inverse=[floats(line) for line in owner.matrix_parent_inverse],
                           rotation_mode=owner.rotation_mode, channels=channels(owner, exclusions),
                           hide_viewport=owner.hide_viewport, hide_render=owner.hide_render,
                           animation=None if owner.animation_data is None or owner.animation_data.action is None else
                           [owner.animation_data.action.name, owner.animation_data.action_slot.handle])
                require(len(owner.modifiers) <= 8 and len(owner.vertex_groups) <= 64, "OBJECT_BINDING_BUDGET")
                row["vertex_groups"] = [[group.index, group.name] for group in owner.vertex_groups]
                modifiers = []
                for modifier in owner.modifiers:
                    require(modifier.type == "ARMATURE", "MODIFIER_UNSUPPORTED")
                    modifiers.append([modifier.name, modifier.type, modifier.object.name if modifier.object else None,
                                      modifier.show_viewport, modifier.show_render, modifier.use_vertex_groups])
                row["modifiers"] = modifiers
                if owner.type == "ARMATURE":
                    pose = []
                    require(len(owner.pose.bones) <= 64, "POSE_BONE_BUDGET")
                    for bone in owner.pose.bones:
                        require(not bone.constraints, "POSE_CONSTRAINTS_UNSUPPORTED")
                        raw_driven.append((owner.name + "/pose/" + bone.name,
                                           tuple((name, tuple(channel_values(bone, name)))
                                                 for name in CHANNELS if bone.bl_rna.properties.get(name) is not None)))
                        prefix = 'pose.bones[' + json.dumps(bone.name, ensure_ascii=False) + '].'
                        pose.append({"name": bone.name, "rotation_mode": bone.rotation_mode,
                                     "channels": channels(bone, exclusions, prefix)})
                    row["pose"] = pose
                for path, index in exclusions:
                    require(path in CHANNELS or re.fullmatch(r'pose\.bones\["(?:[^"\\]|\\.)*"\]\.(location|rotation_euler|rotation_quaternion|scale)', path),
                            "ACTION_PATH_UNSUPPORTED")
                    require(type(index) is int and 0 <= index <= 3, "ACTION_INDEX_UNSUPPORTED")
            elif family == "meshes":
                require(not owner.is_editmode and owner.shape_keys is None, "MESH_EDIT_OR_SHAPE_KEYS_UNSUPPORTED")
                counts["vertices"] += len(owner.vertices)
                counts["corners"] += len(owner.loops)
                require(counts["vertices"] <= 32768 and counts["corners"] <= 131072
                        and len(owner.edges) <= 131072 and len(owner.uv_layers) <= 4, "MESH_BUDGET")
                counts["uv"] += sum(len(uv.data) for uv in owner.uv_layers)
                counts["weights"] += sum(len(vertex.groups) for vertex in owner.vertices)
                require(counts["uv"] <= 131072 and counts["weights"] <= 131072, "MESH_BUDGET")
                require(all(3 <= len(poly.vertices) <= 64 for poly in owner.polygons), "POLYGON_SHAPE")
                row.update(vertices=[floats(vertex.co) for vertex in owner.vertices],
                           edges=[list(edge.vertices) for edge in owner.edges],
                           polygons=[[list(poly.vertices), poly.material_index, poly.use_smooth] for poly in owner.polygons],
                           weights=[[[group.group, scalar(group.weight)] for group in vertex.groups] for vertex in owner.vertices],
                           uv=[{"name": uv.name, "render": uv.active_render,
                                "values": [floats(entry.uv) for entry in uv.data]} for uv in owner.uv_layers],
                           materials=[material.name if material else None for material in owner.materials])
            elif family == "armatures":
                counts["bones"] += len(owner.bones)
                require(counts["bones"] <= 64 and not owner.is_editmode, "ARMATURE_BUDGET_OR_EDIT")
                row["bones"] = [{"name": bone.name, "parent": bone.parent.name if bone.parent else None,
                                 "head": floats(bone.head_local), "tail": floats(bone.tail_local),
                                 "matrix": [floats(line) for line in bone.matrix_local], "deform": bone.use_deform}
                                for bone in owner.bones]
            elif family == "actions":
                values = curves(owner)
                counts["curves"] += len(values)
                counts["keys"] += sum(len(curve.keyframe_points) for _, _, _, curve in values)
                require(counts["curves"] <= 64 and counts["keys"] <= 2048, "ACTION_BUDGET")
                row.update(slots=[[slot.handle, slot.identifier] for slot in owner.slots],
                           curves=[{"layer": layer.name, "slot": bag.slot_handle, "path": curve.data_path,
                                    "index": curve.array_index, "extrapolation": curve.extrapolation,
                                    "keys": [[floats(point.co), floats(point.handle_left), floats(point.handle_right),
                                              point.interpolation, point.handle_left_type, point.handle_right_type]
                                             for point in curve.keyframe_points]} for layer, _, bag, curve in values])
            elif family == "images":
                require(owner.source == "FILE" and not owner.is_dirty and owner.has_data
                        and owner.packed_file is not None and owner.channels == 4, "PACKED_CLEAN_LOADED_FILE_IMAGE_REQUIRED")
                width, height = owner.size
                counts["pixels"] += width * height
                require(0 < width <= 4096 and 0 < height <= 4096 and counts["pixels"] <= MAX_IMAGE_PIXELS, "IMAGE_PIXEL_BUDGET")
                counts["packed"] += owner.packed_file.size
                require(owner.packed_file.size > 0 and counts["packed"] <= MAX_PACKED_BYTES, "PACKED_BYTE_BUDGET")
                facts = check_large_resources(counts["pixels"], resource_directory)
                if facts is not None:
                    resource_checks.append(facts)
                payload = bytes(owner.packed_file.data)
                require(len(payload) == owner.packed_file.size, "PACKED_BYTE_SHAPE")
                pixels = array("f", [0.]) * (width * height * 4)
                require(len(owner.pixels) == len(pixels), "IMAGE_BUFFER_SHAPE")
                owner.pixels.foreach_get(pixels)
                if sys_byteorder() != "little":
                    pixels.byteswap()
                row.update(source=owner.source, filepath=owner.filepath, size=[width, height],
                           colorspace=owner.colorspace_settings.name, alpha_mode=owner.alpha_mode,
                           packed_sha256=hashlib.sha256(payload).hexdigest(), packed_bytes=len(payload),
                           pixels_sha256=hashlib.sha256(memoryview(pixels).cast("B")).hexdigest())
            elif family in {"materials", "worlds"}:
                row.update(use_nodes=owner.use_nodes, tree=tree_projection(owner.node_tree, counts))
                if family == "materials":
                    row["diffuse_color"] = floats(owner.diffuse_color)
            elif family == "collections":
                row.update(objects=sorted(obj.name for obj in owner.objects), children=sorted(c.name for c in owner.children))
            elif family == "scenes":
                require(owner.rigidbody_world is None, "SCENE_CACHE_OR_SEQUENCER_UNSUPPORTED")
                editor = owner.sequence_editor
                if editor is not None:
                    row["sequence_editor"] = empty_sequencer(editor)
                row["native_compositor_descriptors"] = empty_compositor(owner)
                row.update(collection_objects=sorted(obj.name for obj in owner.collection.objects),
                           collection_children=sorted(col.name for col in owner.collection.children),
                           camera=owner.camera.name if owner.camera else None, world=owner.world.name if owner.world else None,
                           units=[owner.unit_settings.system, scalar(owner.unit_settings.scale_length)],
                           frames=[owner.frame_start, owner.frame_end, owner.frame_current, scalar(owner.frame_subframe)],
                           fps=[owner.render.fps, scalar(owner.render.fps_base)])
            elif family == "cameras":
                row.update(type=owner.type, fields={key: scalar(getattr(owner, key)) for key in
                           ("lens", "ortho_scale", "sensor_width", "sensor_height", "clip_start", "clip_end", "shift_x", "shift_y")})
            elif family == "lights":
                row.update(type=owner.type, color=floats(owner.color), energy=scalar(owner.energy))
            rows.append(row)
        result[family] = rows
    # Omitted IDs retain source identity checks, not an authored-content backup.
    return Projection(canonical(result), tuple(identities), tuple(raw_driven),
                      tuple("UNUSED_ID_WITHOUT_FAKE_USER:" + ":".join(value) for value in orphans), tuple(resource_checks))


def sys_byteorder():
    import sys
    return sys.byteorder
