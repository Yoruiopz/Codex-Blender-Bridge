# SPDX-License-Identifier: GPL-3.0-or-later
"""Finite authored save projection shared with the fixed installed reader.

No Blender import, context/evaluation getter or generic RNA recursion. This is a
declared projection, not all Main/UI/custom/SYSTEM storage or a memory cap.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from array import array
from dataclasses import dataclass

SCHEMA = "stock_native_project_v1"
MAX_MANIFEST = 8 * 1024 * 1024
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
                elif actual["identifier"] != field or actual["type"] != kind or actual["is_runtime"] is not False:
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

    @property
    def digest(self):
        return hashlib.sha256(self.raw).hexdigest()


def capture(data):
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
    result, identities, raw_driven, orphans = {"schema": SCHEMA}, [], [], []
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
                require(0 < width <= 4096 and 0 < height <= 4096 and counts["pixels"] <= 1048576, "IMAGE_PIXEL_BUDGET")
                counts["packed"] += owner.packed_file.size
                require(owner.packed_file.size > 0 and counts["packed"] <= 20 * 1024 * 1024, "PACKED_BYTE_BUDGET")
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
                           pixels_sha256=hashlib.sha256(pixels.tobytes()).hexdigest())
            elif family in {"materials", "worlds"}:
                row.update(use_nodes=owner.use_nodes, tree=tree_projection(owner.node_tree, counts))
                if family == "materials":
                    row["diffuse_color"] = floats(owner.diffuse_color)
            elif family == "collections":
                row.update(objects=sorted(obj.name for obj in owner.objects), children=sorted(c.name for c in owner.children))
            elif family == "scenes":
                require(owner.rigidbody_world is None and owner.sequence_editor is None, "SCENE_CACHE_OR_SEQUENCER_UNSUPPORTED")
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
                      tuple("UNUSED_ID_WITHOUT_FAKE_USER:" + ":".join(value) for value in orphans))


def sys_byteorder():
    import sys
    return sys.byteorder
