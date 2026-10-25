"""Registered native save workflow on an owned private display; no child launcher."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import sys
import tempfile
import time
import traceback
import zlib
from itertools import islice
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
FACTORY_FAMILIES = ("objects", "meshes", "cameras", "lights", "materials", "palettes", "linestyles")
HEADER_FIELDS = ("name", "session_uid", "users", "use_fake_user", "is_runtime_data", "is_embedded_data",
                 "is_evaluated", "library", "override_library")
VSE_COLLECTIONS = frozenset({"sequences", "sequences_all", "strips", "strips_all", "meta_stack", "channels"})
PROFILE_CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
                    "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")
DEFAULT_CHANNEL_BUILDS = {"62c1db4208e8": False, "d13f752e3b9c": True}


def default_channel_snapshot(editor, *, build_hash):
    """Prove the complete public default records before owned VSE deletion."""
    result = {"schema": "owned_default_channels_v1", "build_hash": build_hash, "count": None,
              "channel_class": "SequenceTimelineChannel", "number_descriptor_present": None,
              "index_descriptor_present": None, "rows": [], "class_schema": None,
              "fingerprint": None, "default_match": False, "errors": []}
    if type(build_hash) is not str or build_hash not in DEFAULT_CHANNEL_BUILDS:
        result["errors"].append({"code": "CHANNEL_BUILD_UNSUPPORTED"})
        return result
    number_present = DEFAULT_CHANNEL_BUILDS[build_hash]
    try:
        channels = _native_field(editor, "channels", "COLLECTION")
        result["count"] = len(channels)
        if result["count"] != 129:
            result["errors"].append({"code": "CHANNEL_COUNT_UNSUPPORTED"})
            return result
        owners = list(islice(iter(channels), 130))
        if len(owners) != 129:
            result["errors"].append({"code": "CHANNEL_ITERATION_CHANGED"})
            return result
        expected = {"rna_type": ("POINTER", True), "name": ("STRING", False),
                    "lock": ("BOOLEAN", False), "mute": ("BOOLEAN", False)}
        if number_present:
            expected["number"] = "INT", True
        # Qualify every record's native metadata before any authored value read.
        for position, channel in enumerate(owners):
            try:
                native = channel.bl_rna
                assert native.identifier == "SequenceTimelineChannel"
                assert len(native.properties) == len(expected) and len(native.functions) == 0
                properties = list(islice(iter(native.properties), len(expected) + 1))
                assert len(properties) == len(expected) and {item.identifier for item in properties} == set(expected)
                schema = {"properties": [], "functions": []}
                for name, (kind, readonly) in expected.items():
                    descriptor = native.properties.get(name)
                    assert descriptor is not None and descriptor.identifier == name and descriptor.type == kind
                    assert descriptor.is_runtime is False and descriptor.is_readonly is readonly
                    metadata = {"identifier": name, "type": descriptor.type, "is_runtime": descriptor.is_runtime,
                                "is_readonly": descriptor.is_readonly}
                    if kind in {"BOOLEAN", "INT"}:
                        assert type(descriptor.array_length) is int and descriptor.array_length == 0
                        metadata["array_length"] = descriptor.array_length
                    schema["properties"].append(metadata)
                if result["class_schema"] is None:
                    result["class_schema"] = schema
                assert result["class_schema"] == schema
            except Exception as cause:
                result["errors"].append({"code": "CHANNEL_SCHEMA_UNSUPPORTED", "position": position,
                                          "error_type": type(cause).__name__})
        if result["errors"]:
            return result
        result["number_descriptor_present"] = number_present
        result["index_descriptor_present"] = False
        for position, channel in enumerate(owners):
            try:
                pointer = channel.as_pointer()
                assert type(pointer) is int and pointer > 0
                row = {"position": position, "pointer": pointer, "name": _native_field(channel, "name", "STRING"),
                       "lock": _native_field(channel, "lock", "BOOLEAN"), "mute": _native_field(channel, "mute", "BOOLEAN")}
                if number_present:
                    row["number"] = _native_field(channel, "number", "INT")
                result["rows"].append(row)
                valid = (type(row["name"]) is str and row["name"] == "Channel " + str(position)
                         and row["lock"] is False and row["mute"] is False)
                if number_present:
                    valid = valid and type(row["number"]) is int and row["number"] == position
                if not valid:
                    result["errors"].append({"code": "CHANNEL_VALUES_NONDEFAULT", "position": position})
            except Exception as cause:
                result["errors"].append({"code": "CHANNEL_READ_ERROR", "position": position,
                                          "error_type": type(cause).__name__})
        payload = {"build_hash": build_hash, "class_schema": result["class_schema"], "rows": result["rows"]}
        result["fingerprint"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        result["default_match"] = len(result["rows"]) == 129 and not result["errors"]
    except Exception as cause:
        result["errors"].append({"code": "CHANNEL_READ_ERROR", "error_type": type(cause).__name__})
    return result


def _violation(rows, code, owner, field=None, **facts):
    if len(rows) < 256:
        rows.append({"code": code, "owner": owner, **({"field": field} if field else {}), **facts})
    else:
        raise AssertionError("Owned value diagnostic violation budget")


def _native_field(owner, name, kind):
    descriptor = owner.bl_rna.properties.get(name)
    assert descriptor is not None and descriptor.identifier == name and descriptor.type == kind
    assert descriptor.is_runtime is False
    return getattr(owner, name)


def _pointer_value(value):
    return {"present": value is not None, "rna_type": value.bl_rna.identifier if value is not None else None,
            "pointer": value.as_pointer() if value is not None else None}


def scene_value_snapshot(data, *, build_hash=None):
    """Literal owned-setup observations, never a production preservation getter."""
    result = {"schema": "native_save_scene_values_v1", "scenes": [], "violations": []}
    assert len(data.scenes) <= 4, "Owned Scene diagnostic budget"
    for scene in data.scenes:
        row = {"name": scene.name, "identity": id_header(scene), "compositor": {}}
        result["scenes"].append(row)
        try:
            rigid = _native_field(scene, "rigidbody_world", "POINTER")
            row["rigidbody_world"] = _pointer_value(rigid)
            if rigid is not None:
                _violation(result["violations"], "SCENE_RIGIDBODY_WORLD_PRESENT", scene.name, "rigidbody_world")
        except Exception as cause:
            row["rigidbody_world"] = {"observed": False, "error_type": type(cause).__name__}
            _violation(result["violations"], "SCENE_VALUE_READ_ERROR", scene.name, "rigidbody_world", error_type=type(cause).__name__)
        try:
            editor = _native_field(scene, "sequence_editor", "POINTER")
            detail = {**_pointer_value(editor), "collections": {}, "unknown_collections": [], "errors": [],
                      "empty_candidate": False}
            row["sequence_editor"] = detail
            if editor is not None:
                _violation(result["violations"], "SCENE_SEQUENCE_EDITOR_PRESENT", scene.name, "sequence_editor")
                for descriptor in editor.bl_rna.properties:
                    if descriptor.type != "COLLECTION":
                        continue
                    name = descriptor.identifier
                    if name not in VSE_COLLECTIONS or descriptor.is_runtime is not False:
                        detail["unknown_collections"].append(name)
                        _violation(result["violations"], "SCENE_SEQUENCE_EDITOR_UNKNOWN_COLLECTION", scene.name, name)
                        continue
                    try:
                        count = len(_native_field(editor, name, "COLLECTION"))
                        assert 0 <= count <= 1024, "Owned VSE collection budget"
                        detail["collections"][name] = {"count": count, "metadata": {
                            "identifier": name, "type": descriptor.type, "is_runtime": descriptor.is_runtime}}
                        if name == "channels" and count:
                            detail["channel_defaults"] = default_channel_snapshot(editor, build_hash=build_hash)
                            if not detail["channel_defaults"]["default_match"]:
                                _violation(result["violations"], "SCENE_SEQUENCE_EDITOR_CHANNELS_NONDEFAULT", scene.name, "channels")
                    except Exception as cause:
                        detail["errors"].append({"field": name, "error_type": type(cause).__name__})
                        _violation(result["violations"], "SCENE_VALUE_READ_ERROR", scene.name, name, error_type=type(cause).__name__)
                if editor.bl_rna.properties.get("active_strip") is not None:
                    detail["active_strip"] = {"descriptor_present": True, **_pointer_value(_native_field(editor, "active_strip", "POINTER"))}
                else:
                    detail["active_strip"] = {"descriptor_present": False}
                    _violation(result["violations"], "SCENE_SEQUENCE_EDITOR_ACTIVE_UNOBSERVED", scene.name, "active_strip")
                detail["empty_candidate"] = bool(detail["collections"]) and (
                    not detail["unknown_collections"] and not detail["errors"]
                    and all(value["count"] == 0 for name, value in detail["collections"].items() if name != "channels")
                    and (detail["collections"].get("channels", {}).get("count") == 0
                         or detail.get("channel_defaults", {}).get("default_match") is True)
                    and detail["active_strip"].get("descriptor_present") is True
                    and detail["active_strip"].get("present") is False)
        except Exception as cause:
            detail = row.setdefault("sequence_editor", {"observed": False, "collections": {}, "errors": []})
            detail["empty_candidate"] = False
            detail["errors"].append({"error_type": type(cause).__name__})
            _violation(result["violations"], "SCENE_VALUE_READ_ERROR", scene.name, "sequence_editor", error_type=type(cause).__name__)
        for name in ("node_tree", "compositing_node_group", "animation_data"):
            if scene.bl_rna.properties.get(name) is None:
                row["compositor"][name] = {"descriptor_present": False}
                continue
            try:
                value = _native_field(scene, name, "POINTER")
                row["compositor"][name] = {"descriptor_present": True, **_pointer_value(value)}
                if value is not None:
                    _violation(result["violations"], "SCENE_COMPOSITOR_OR_ANIMATION_PRESENT", scene.name, name)
            except Exception as cause:
                row["compositor"][name] = {"descriptor_present": True, "observed": False, "error_type": type(cause).__name__}
                _violation(result["violations"], "SCENE_VALUE_READ_ERROR", scene.name, name, error_type=type(cause).__name__)
    return result


def clear_owned_empty_sequence_editors(data, *, attested, preflight, build_hash=None):
    """Only a verified empty VSE in this disposable factory process may clear."""
    assert attested is True
    before = scene_value_snapshot(data, build_hash=build_hash)
    result = {"before": before, "cleared": [], "after": None}
    assert preflight["schema"] == "native_save_value_preflight_v1" and preflight["complete"] is True
    assert before == preflight["scene_values"], "Owned Scene values changed since the retained batch"
    assert all(row["code"] == "SCENE_SEQUENCE_EDITOR_PRESENT" for row in preflight["violations"]), "Other profile violations prohibit cleanup"
    assert len(before["scenes"]) == 1
    for scene, row in zip(data.scenes, before["scenes"], strict=True):
        assert scene.library is None and scene.override_library is None
        assert row["rigidbody_world"].get("present") is False, "Never remove an owned/unknown rigid world"
        editor = row["sequence_editor"]
        if editor.get("present") is False:
            continue
        assert editor.get("present") is True and editor["empty_candidate"], "Nonempty/unknown VSE remains retained"
        function = scene.bl_rna.functions.get("sequence_editor_clear")
        assert function is not None and function.identifier == "sequence_editor_clear"
        original = scene.sequence_editor
        assert original is not None and original.as_pointer() == editor["pointer"]
        scene.sequence_editor_clear()
        assert scene.sequence_editor is None
        channels = editor.get("channel_defaults")
        result["cleared"].append({"scene": scene.name, "before_pointer": editor["pointer"], "after_present": False,
                                  "owned_default_channel_records_deleted": 129 if channels else 0,
                                  "channel_fingerprint": channels["fingerprint"] if channels else None})
    result["after"] = scene_value_snapshot(data, build_hash=build_hash)
    return result


def value_preflight(data, *, build_hash=None):
    """Batch every existing profile predicate during owned setup; no repair."""
    scene_values = scene_value_snapshot(data, build_hash=build_hash)
    result = {"schema": "native_save_value_preflight_v1", "scene_values": scene_values,
              "observations": {}, "totals": {}, "violations": list(scene_values["violations"]), "complete": False}
    violations, observations = result["violations"], result["observations"]
    totals = {key: 0 for key in ("ids", "vertices", "corners", "edges", "uv", "weights", "bones", "curves", "keys", "pixels", "packed", "nodes", "links")}
    result["totals"] = totals

    def check(value, code, owner, field=None, **facts):
        if not value:
            _violation(violations, code, owner, field, **facts)

    def bounded(values, limit, owner, field):
        count = len(values)
        check(count <= limit, "VALUE_BUDGET", owner, field, count=count, limit=limit)
        return list(values) if count <= limit else []

    def numeric(values, owner, field):
        count = len(values)
        check(count <= 16 and all(type(value) in {int, float} and math.isfinite(value) and abs(value) <= 1e12
                                 for value in values), "PROFILE_NONFINITE_OR_MAGNITUDE", owner, field)

    def animation(owner):
        if owner.bl_rna.properties.get("animation_data") is not None:
            check(owner.animation_data is None, "NON_OBJECT_ANIMATION_UNSUPPORTED", owner.name, "animation_data")

    def action_values(action, *, count_totals=True):
        rows = []
        layers = bounded(action.layers, 4, action.name, "layers")
        bounded(action.slots, 64, action.name, "slots")
        for layer in layers:
            for strip in bounded(layer.strips, 4, action.name, "strips"):
                check(strip.type == "KEYFRAME", "ACTION_STRIP_UNSUPPORTED", action.name, "strip.type")
                if strip.type != "KEYFRAME":
                    continue
                for bag in bounded(strip.channelbags, 32, action.name, "channelbags"):
                    for curve in bounded(bag.fcurves, 64, action.name, "fcurves"):
                        if count_totals:
                            totals["curves"] += 1
                        check(not curve.modifiers, "FCURVE_MODIFIERS_UNSUPPORTED", action.name, "curve.modifiers")
                        points = bounded(curve.keyframe_points, 2048, action.name, "keyframe_points")
                        if count_totals:
                            totals["keys"] += len(curve.keyframe_points)
                        for point in points:
                            for field in ("co", "handle_left", "handle_right"):
                                numeric(getattr(point, field), action.name, field)
                        rows.append({"path": curve.data_path, "index": curve.array_index, "keys": len(curve.keyframe_points),
                                     "slot_handle": bag.slot_handle})
        return rows

    families = ("scenes", "collections", "objects", "meshes", "armatures", "actions", "materials", "worlds", "images", "cameras", "lights")
    totals["ids"] = sum(len(getattr(data, family)) for family in families)
    check(len(data.scenes) == 1, "ONE_SCENE_REQUIRED", "Main", "scenes")
    for descriptor in data.bl_rna.properties:
        if descriptor.type == "COLLECTION" and descriptor.identifier not in set(families) | {"window_managers", "screens", "workspaces", "all_ids"}:
            check(len(getattr(data, descriptor.identifier)) == 0, "UNSUPPORTED_ID_FAMILY", "Main", descriptor.identifier)
    if totals["ids"] > 128:
        check(False, "AGGREGATE_VALUE_BUDGET", "Main", "ids", count=totals["ids"], limit=128)
        return result
    for family in families:
        values = getattr(data, family)
        owners = bounded(values, {"objects": 32, "collections": 16, "materials": 8, "images": 4}.get(family, 128), "Main", family)
        observations[family] = []
        for owner in owners:
            row = {"name": owner.name, "users": owner.users, "fake_user": owner.use_fake_user}
            observations[family].append(row)
            try:
                check(owner.library is None and owner.override_library is None, "LINKED_OR_OVERRIDE_UNSUPPORTED", owner.name)
                pointer = owner.as_pointer()
                check(type(owner.session_uid) is int and owner.session_uid > 0 and type(pointer) is int and pointer > 0,
                      "ID_IDENTITY_UNAVAILABLE", owner.name)
                check(len(owner.name.encode()) <= 255, "NAME_BUDGET", owner.name)
                if family != "scenes" and owner.users == 0 and not owner.use_fake_user:
                    row["saved_omission"] = True
                    continue
                if family != "objects":
                    animation(owner)
                if family == "objects":
                    modifiers = bounded(owner.modifiers, 8, owner.name, "modifiers")
                    row.update(type=owner.type, mode=owner.mode, constraints=len(owner.constraints),
                               rigid_body=owner.rigid_body is not None, rigid_body_constraint=owner.rigid_body_constraint is not None,
                               particles=len(owner.particle_systems), instance_type=owner.instance_type,
                               modifier_types=[modifier.type for modifier in modifiers])
                    row["parent"] = owner.parent.name if owner.parent else None
                    row["armature_bindings"] = [modifier.object.name if modifier.object else None
                                               for modifier in modifiers if modifier.type == "ARMATURE"]
                    check(owner.type in {"MESH", "EMPTY", "ARMATURE", "CAMERA", "LIGHT"} and owner.mode == "OBJECT" and not owner.constraints,
                          "OBJECT_PROFILE_UNSUPPORTED", owner.name)
                    check(owner.rigid_body is None and owner.rigid_body_constraint is None and not owner.particle_systems and owner.instance_type == "NONE",
                          "OBJECT_CACHE_OR_INSTANCE_UNSUPPORTED", owner.name)
                    bounded(owner.vertex_groups, 64, owner.name, "vertex_groups")
                    for field in PROFILE_CHANNELS:
                        numeric(getattr(owner, field), owner.name, field)
                    for line in owner.matrix_parent_inverse:
                        numeric(line, owner.name, "matrix_parent_inverse")
                    check(all(kind == "ARMATURE" for kind in row["modifier_types"]), "MODIFIER_UNSUPPORTED", owner.name)
                    anim = owner.animation_data
                    if anim is not None:
                        check(not anim.drivers and not anim.nla_tracks, "DRIVERS_OR_NLA_UNSUPPORTED", owner.name)
                        if anim.action is not None:
                            check(anim.action_slot is not None, "ACTION_SLOT_UNAVAILABLE", owner.name)
                            row["action_binding"] = {"action": anim.action.name,
                                                     "slot_handle": anim.action_slot.handle if anim.action_slot else None}
                            for curve in action_values(anim.action, count_totals=False):
                                if anim.action_slot is not None and curve["slot_handle"] == anim.action_slot.handle:
                                    path = curve["path"]
                                    check(path in PROFILE_CHANNELS or re.fullmatch(
                                        r'pose\.bones\["(?:[^"\\]|\\.)*"\]\.(location|rotation_euler|rotation_quaternion|scale)', path),
                                        "ACTION_PATH_UNSUPPORTED", owner.name, path)
                                    check(type(curve["index"]) is int and 0 <= curve["index"] <= 3,
                                          "ACTION_INDEX_UNSUPPORTED", owner.name, path)
                    if owner.type == "ARMATURE":
                        for bone in bounded(owner.pose.bones, 64, owner.name, "pose.bones"):
                            check(not bone.constraints, "POSE_CONSTRAINTS_UNSUPPORTED", owner.name, bone.name)
                            for field in PROFILE_CHANNELS:
                                if bone.bl_rna.properties.get(field) is not None:
                                    numeric(getattr(bone, field), owner.name, "pose." + field)
                elif family == "meshes":
                    row.update(is_editmode=owner.is_editmode, shape_keys=owner.shape_keys is not None,
                               vertices=len(owner.vertices), corners=len(owner.loops), edges=len(owner.edges), uv_layers=len(owner.uv_layers))
                    check(not owner.is_editmode and owner.shape_keys is None, "MESH_EDIT_OR_SHAPE_KEYS_UNSUPPORTED", owner.name)
                    totals["vertices"] += len(owner.vertices)
                    totals["corners"] += len(owner.loops)
                    totals["edges"] += len(owner.edges)
                    for vertex in bounded(owner.vertices, 32768, owner.name, "vertices"):
                        numeric(vertex.co, owner.name, "vertex.co")
                        totals["weights"] += len(vertex.groups)
                        if totals["weights"] > 131072:
                            continue  # Record the aggregate violation without copying excess weights.
                        for group in bounded(vertex.groups, 131072, owner.name, "vertex.groups"):
                            numeric([group.weight], owner.name, "weight")
                    for polygon in bounded(owner.polygons, 131072, owner.name, "polygons"):
                        check(3 <= len(polygon.vertices) <= 64, "POLYGON_SHAPE", owner.name)
                    for uv in bounded(owner.uv_layers, 4, owner.name, "uv_layers"):
                        totals["uv"] += len(uv.data)
                        if totals["uv"] > 131072:
                            continue
                        for entry in bounded(uv.data, 131072, owner.name, "uv.data"):
                            numeric(entry.uv, owner.name, "uv")
                elif family == "armatures":
                    row.update(is_editmode=owner.is_editmode, bones=len(owner.bones))
                    check(not owner.is_editmode, "ARMATURE_BUDGET_OR_EDIT", owner.name)
                    totals["bones"] += len(owner.bones)
                    for bone in bounded(owner.bones, 64, owner.name, "bones"):
                        numeric(bone.head_local, owner.name, "head_local")
                        numeric(bone.tail_local, owner.name, "tail_local")
                        for line in bone.matrix_local:
                            numeric(line, owner.name, "matrix_local")
                elif family == "actions":
                    row["curves"] = action_values(owner)
                elif family == "images":
                    row.update(source=owner.source, is_dirty=owner.is_dirty, has_data=owner.has_data,
                               packed=owner.packed_file is not None)
                    valid = owner.source == "FILE" and not owner.is_dirty and owner.has_data and owner.packed_file is not None
                    check(valid, "PACKED_CLEAN_LOADED_FILE_IMAGE_REQUIRED", owner.name)
                    if valid:
                        width, height = owner.size
                        row.update(size=[width, height], channels=owner.channels, packed_bytes=owner.packed_file.size,
                                   colorspace=owner.colorspace_settings.name, alpha_mode=owner.alpha_mode)
                        totals["pixels"] += width * height
                        totals["packed"] += owner.packed_file.size
                        check(owner.channels == 4 and 0 < width <= 4096 and 0 < height <= 4096,
                              "IMAGE_PIXEL_BUDGET", owner.name)
                        check(0 < owner.packed_file.size <= 20 * 1024 * 1024, "PACKED_BYTE_BUDGET", owner.name)
                        if owner.packed_file.size > 0 and totals["packed"] <= 20 * 1024 * 1024:
                            check(len(bytes(owner.packed_file.data)) == owner.packed_file.size, "PACKED_BYTE_SHAPE", owner.name)
                        check(len(owner.pixels) == width * height * 4, "IMAGE_BUFFER_SHAPE", owner.name)
                elif family in {"materials", "worlds"}:
                    row.update(use_nodes=owner.use_nodes, node_tree=owner.node_tree is not None)
                    if family == "materials":
                        numeric(owner.diffuse_color, owner.name, "diffuse_color")
                    tree = owner.node_tree
                    if tree is not None:
                        animation(tree)
                        totals["nodes"] += len(tree.nodes)
                        totals["links"] += len(tree.links)
                        row["node_types"] = []
                        for node in bounded(tree.nodes, 64, owner.name, "nodes"):
                            row["node_types"].append(node.bl_idname)
                            check(node.bl_idname in {"ShaderNodeOutputMaterial", "ShaderNodeBsdfPrincipled", "ShaderNodeTexImage", "ShaderNodeOutputWorld", "ShaderNodeBackground"},
                                  "SHADER_NODE_UNSUPPORTED", owner.name, node.bl_idname)
                            for socket in bounded(node.inputs, 64, owner.name, "node.inputs"):
                                if socket.type in {"RGBA", "VECTOR"}:
                                    numeric(socket.default_value, owner.name, "socket.default_value")
                                elif socket.type == "VALUE":
                                    numeric([socket.default_value], owner.name, "socket.default_value")
                                else:
                                    check(socket.type in {"SHADER", "INT", "BOOLEAN"}, "SHADER_SOCKET_UNSUPPORTED", owner.name, socket.type)
                elif family == "scenes":
                    numeric([owner.unit_settings.scale_length, owner.frame_subframe, owner.render.fps_base], owner.name, "scene_scalars")
                elif family == "cameras":
                    numeric([getattr(owner, field) for field in ("lens", "ortho_scale", "sensor_width", "sensor_height", "clip_start", "clip_end", "shift_x", "shift_y")], owner.name, "camera_scalars")
                elif family == "lights":
                    numeric(owner.color, owner.name, "color")
                    numeric([owner.energy], owner.name, "energy")
            except Exception as cause:
                row["read_error_type"] = type(cause).__name__
                _violation(violations, "VALUE_READ_ERROR", owner.name, family, error_type=type(cause).__name__)
    for field, limit in {"ids": 128, "vertices": 32768, "corners": 131072, "edges": 131072, "uv": 131072,
                         "weights": 131072, "bones": 64, "curves": 64, "keys": 2048, "pixels": 1048576,
                         "packed": 20 * 1024 * 1024, "nodes": 64, "links": 128}.items():
        check(totals[field] <= limit, "AGGREGATE_VALUE_BUDGET", "Main", field, count=totals[field], limit=limit)
    result["complete"] = not any(row["code"] in {"VALUE_READ_ERROR", "SCENE_VALUE_READ_ERROR", "SCENE_SEQUENCE_EDITOR_UNKNOWN_COLLECTION",
                                                "SCENE_SEQUENCE_EDITOR_ACTIVE_UNOBSERVED"}
                                 for row in violations)
    return result


def id_header(owner):
    fields, absent = {}, []
    for name in HEADER_FIELDS:
        if owner.bl_rna.properties.get(name) is None:
            absent.append(name)
            continue
        value = getattr(owner, name)
        fields[name] = ({"name": value.name, "rna_type": value.bl_rna.identifier}
                        if name in {"library", "override_library"} and value is not None else value)
    return {"rna_type": owner.bl_rna.identifier, "pointer": owner.as_pointer(),
            "fields": fields, "absent_descriptors": absent}


def data_inventory(data):
    """Detached diagnostics during owned setup only; never an armed-source read."""
    result = {}
    for descriptor in data.bl_rna.properties:
        if descriptor.type != "COLLECTION":
            continue
        owners = getattr(data, descriptor.identifier)
        rows = []
        for owner in owners:
            row = id_header(owner)
            if descriptor.identifier == "images":
                image, absent = {}, []
                for name in ("source", "type", "is_dirty", "has_data", "filepath", "packed_file"):
                    if owner.bl_rna.properties.get(name) is None:
                        absent.append(name)
                    else:
                        value = getattr(owner, name)
                        image[name] = ({"size": value.size} if value is not None else None) if name == "packed_file" else value
                row.update(image=image, image_absent_descriptors=absent)
            rows.append(row)
        result[descriptor.identifier] = {"count": len(owners), "ids": rows}
    return result


def setup_bindings(data):
    """Record the declared owned Scene/UI pointer fields around setup cleanup."""
    rows = []
    for scene in data.scenes:
        for name in ("camera", "world"):
            value = getattr(scene, name)
            rows.append({"owner": scene.name, "field": name, "value": id_header(value) if value else None})
    for screen in data.screens:
        for area_index, area in enumerate(screen.areas):
            for space_index, space in enumerate(area.spaces):
                for name in ("image", "camera", "pin_id", "clip", "mask", "node_tree"):
                    if space.bl_rna.properties.get(name) is not None:
                        value = getattr(space, name)
                        rows.append({"screen": screen.name, "area": area_index, "space": space_index,
                                     "rna_type": space.bl_rna.identifier, "field": name,
                                     "value": id_header(value) if value is not None else None})
    return rows


def clean_factory_data(data, *, attested):
    assert attested is True, "Only the isolated fresh factory process owns this setup cleanup"
    removed = []
    for family in FACTORY_FAMILIES:
        owners = getattr(data, family)
        for owner in list(owners):
            header = id_header(owner)
            assert owner.library is None and owner.override_library is None, header
            removed.append({"family": family, "id": header})
            owners.remove(owner, do_unlink=True)
    for owner in list(data.images):
        descriptor = owner.bl_rna.properties.get("is_runtime_data")
        runtime = descriptor is not None and owner.is_runtime_data is True
        if owner.source == "VIEWER" or runtime:
            assert owner.library is None and owner.override_library is None
            removed.append({"family": "images", "id": id_header(owner)})
            data.images.remove(owner, do_unlink=True)
    return removed


def unsupported_remainders(inventory, families, ui_families):
    return {name: row for name, row in inventory.items()
            if row["count"] and (name not in set(families) | set(ui_families) or name == "images")}


def persist_failure(proof, report, cause, *, bridge_error_type):
    failure = {"stage": proof["stage"], "exception_type": type(cause).__name__}
    if isinstance(cause, bridge_error_type):
        failure["bridge_error"] = cause.to_dict()
    proof.setdefault("failures", []).append(failure)
    report.write_text(json.dumps(proof, indent=2) + "\n")


def fixture(bundle):
    scene, layer = bpy.context.scene, bpy.context.view_layer
    mesh = bpy.data.meshes.new("Artist Base Mesh")
    mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
    uv = mesh.uv_layers.new(name="Artist UV")
    for entry, value in zip(uv.data, ((0., 0.), (1., 0.), (0., 1.)), strict=True):
        entry.uv = value
    obj = bpy.data.objects.new("Artist Mesh", mesh)
    scene.collection.objects.link(obj)
    armature = bpy.data.armatures.new("Artist Rig Data")
    rig = bpy.data.objects.new("Artist Rig", armature)
    scene.collection.objects.link(rig)
    layer.update()
    layer.objects.active = rig
    rig.select_set(True)
    assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
    bone = armature.edit_bones.new("Root")
    bone.head, bone.tail = (0., 0., 0.), (0., 1., 0.)
    assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}
    group = obj.vertex_groups.new(name="Root")
    group.add([0, 1, 2], 1., "REPLACE")
    obj.modifiers.new("Artist Skin", "ARMATURE").object = rig
    obj.parent = rig
    actor = bpy.data.objects.new("Artist Dirty Animation", None)
    scene.collection.objects.link(actor)
    for owner, path, index, values in (
        (rig, 'pose.bones["Root"].rotation_euler', 2, (0., .3)),
        (actor, "location", 0, (20., 30.)),
    ):
        action = bpy.data.actions.new(owner.name + " Action")
        slot = action.slots.new("OBJECT", owner.name)
        strip = action.layers.new("Artist Layer").strips.new(type="KEYFRAME")
        curve = strip.channelbag(slot, ensure=True).fcurves.new(data_path=path, index=index)
        curve.keyframe_points.add(2)
        for point, frame, value in zip(curve.keyframe_points, (1., 2.), values, strict=True):
            point.co = frame, value
        curve.update()
        owner.animation_data_create().action = action
        owner.animation_data.action_slot = slot
    material = bpy.data.materials.new("Artist Textured Material")
    material.use_nodes = True
    mesh.materials.append(material)
    textures = bundle / "artifacts" / "textures"
    textures.mkdir()
    rgba = bytes((255, 0, 31, 255, 0, 255, 63, 128, 31, 63, 255, 64, 128, 64, 32, 0))

    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff)

    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)) + chunk(
        b"IDAT", zlib.compress(b"\0" + rgba[:8] + b"\0" + rgba[8:])) + chunk(b"IEND", b"")
    for name, role, alpha in (("Artist Color", "sRGB", "STRAIGHT"), ("Artist Data", "Non-Color", "CHANNEL_PACKED")):
        path = textures / (name + ".png")
        path.write_bytes(payload)
        image = bpy.data.images.load(str(path), check_existing=False)
        image.name, image.alpha_mode = name, alpha
        image.colorspace_settings.name = role
        image.pack()
        image.filepath = "//textures/" + path.name
        image.pixels[0]
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes.get("Principled BSDF").inputs[
            "Base Color" if role == "sRGB" else "Roughness"])
    return scene, layer, obj, rig, actor


def main():
    sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
    from blender_artist_sidebar_smoke import owned_process_exit, private_display_manifest

    private_display_manifest()
    assert not bpy.app.background and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert (tuple(bpy.app.version), bpy.app.build_hash.decode()) in {
        ((4, 5, 14), "62c1db4208e8"), ((5, 2, 2), "d13f752e3b9c")}
    assert bpy.app.build_type.decode() == "Release" and os.environ.get("BRIDGE_TEST_PROCESS_TOKEN")
    bundle = Path(tempfile.mkdtemp(prefix="registered native save "))
    report = bundle / "registered-native-save.json"
    proof = {"completed": False, "source_build": bpy.app.build_hash.decode(), "rows": [],
             "stage": "owned_setup", "inventories": {}, "scene_values": {}, "value_preflights": {},
             "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": os.getpid(),
             "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    runtime, bridge_error_type = None, ()
    try:
        artifacts = bundle / "artifacts"
        artifacts.mkdir(mode=0o700)
        (artifacts / "moved folder").mkdir(mode=0o700)
        proof["inventories"]["process_startup"] = data_inventory(bpy.data)
        proof["scene_values"]["process_startup"] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
        report.write_text(json.dumps(proof, indent=2) + "\n")
        bpy.context.preferences.use_preferences_save = False
        paths = bpy.context.preferences.filepaths
        paths.file_preview_type, paths.save_version = "NONE", 1
        paths.use_auto_save_temporary_files = False
        assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.native_save_profile import FAMILIES, UI, schema_census
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        from blender_isolated_asset_preview_probe_smoke import raw_selection

        bridge_error_type = BridgeError

        runtime, prefs = get_runtime(), get_preferences()
        prefs.auto_start = False
        prefs.allow_inspect_scene = prefs.allow_external_files = prefs.allow_save_project = True
        prefs.project_directory = str(artifacts)
        proof["inventories"]["factory_before_cleanup"] = data_inventory(bpy.data)
        proof["scene_values"]["before_setup_bindings"] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
        proof["setup_bindings_before"] = setup_bindings(bpy.data)
        proof["scene_values"]["after_setup_bindings"] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
        protected_headers = {name: [id_header(owner) for owner in getattr(bpy.data, name)]
                             for name in ("scenes", "screens", "window_managers", "workspaces")}
        proof["stage"] = "factory_cleanup"
        proof["factory_removed"] = clean_factory_data(bpy.data, attested="--factory-startup" in sys.argv)
        proof["inventories"]["factory_after_cleanup"] = data_inventory(bpy.data)
        proof["scene_values"]["after_factory_cleanup"] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
        proof["setup_bindings_after"] = setup_bindings(bpy.data)
        proof["scene_values"]["after_final_setup_bindings"] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
        assert protected_headers == {name: [id_header(owner) for owner in getattr(bpy.data, name)]
                                     for name in protected_headers}, "Setup replaced a preserved Scene/UI ID"
        proof["unsupported_after_cleanup"] = unsupported_remainders(
            proof["inventories"]["factory_after_cleanup"], FAMILIES, UI)
        report.write_text(json.dumps(proof, indent=2) + "\n")
        assert not proof["unsupported_after_cleanup"], proof["unsupported_after_cleanup"]
        proof["stage"] = "declared_class_schema"
        proof["schema_census"] = schema_census(bpy.types)
        report.write_text(json.dumps(proof, indent=2) + "\n")
        assert not proof["schema_census"]["mismatches"], proof["schema_census"]["mismatches"]
        proof["stage"] = "artist_asset_creation"
        _scene, layer, obj, _rig, actor = fixture(bundle)
        obj.name = "Artist Generic Renamed Mesh"
        obj.data.name = "Artist Generic Renamed Data"
        # All source buffers were loaded/packed by owned setup. Fresh readers
        # must succeed with the external source folder unavailable.
        (artifacts / "textures").rename(bundle / "unavailable external textures")
        proof["inventories"]["artist_before_intents"] = data_inventory(bpy.data)
        proof["scene_values"]["after_asset_creation"] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
        proof["stage"] = "owned_value_preflight_before_clear"
        before_clear = value_preflight(bpy.data, build_hash=proof["source_build"])
        proof["value_preflights"]["before_owned_clear"] = before_clear
        report.write_text(json.dumps(proof, indent=2) + "\n")
        proof["owned_empty_sequence_clear"] = clear_owned_empty_sequence_editors(
            bpy.data, attested="--factory-startup" in sys.argv, preflight=before_clear, build_hash=proof["source_build"])
        proof["value_preflights"]["after_owned_clear"] = value_preflight(bpy.data, build_hash=proof["source_build"])
        report.write_text(json.dumps(proof, indent=2) + "\n")
        assert proof["value_preflights"]["after_owned_clear"]["complete"]
        assert not proof["value_preflights"]["after_owned_clear"]["violations"]
        sentinel = bundle / "owned callback outside project folder.txt"
        sentinel.write_text("0\n")
        callbacks = {"count": 0, "revoke": False}

        def save_post(*_args):
            callbacks["count"] += 1
            sentinel.write_text(str(callbacks["count"]) + "\n")
            if callbacks["revoke"]:
                runtime.revoke_native_save_effects()

        bpy.app.handlers.save_post.append(save_post)

        def dispatch(method, params):
            proof["stage"] = "dispatch:" + method
            try:
                return runtime.dispatch(method, params)
            except BridgeError as error:
                persist_failure(proof, report, error, bridge_error_type=BridgeError)
                raise

        def denied(method, params, code, reasons=None):
            before = callbacks["count"]
            try:
                dispatch(method, params)
            except BridgeError as error:
                assert error.code == code, error.to_dict()
                if reasons is not None:
                    assert error.context.get("reason") in reasons, error.to_dict()
                proof.setdefault("denials", []).append({"method": method, "code": code})
            else:
                raise AssertionError("Expected a native-save denial")
            assert callbacks["count"] == before

        original = artifacts / "original project.blend"
        denied("project.native_save_preview", {"mode": "SAVE_AS", "filepath": str(original),
                                               "overwrite_policy": "NATIVE_NEW_EXPECTED"}, "PERMISSION_DENIED")
        denied("project.save", {"filepath": str(original)}, "NOT_IMPLEMENTED")
        assert not original.exists() and not runtime.permissions.snapshot()["NATIVE_SAVE_EFFECTS"]
        assert bpy.ops.blender_codex_bridge.arm_native_save("EXEC_DEFAULT") == {"FINISHED"}
        assert runtime.permissions.snapshot()["NATIVE_SAVE_EFFECTS"]
        base_params = {"mode": "COPY_NEW", "filepath": str(artifacts / "invalid context.blend"),
                       "overwrite_policy": "NO_CLOBBER"}
        runtime.state.set_paused(True)
        denied("project.native_save_preview", base_params, "AGENT_PAUSED")
        runtime.state.set_paused(False)
        runtime.state.set_emergency_stopped(True)
        denied("project.native_save_preview", base_params, "EMERGENCY_STOPPED")
        runtime.state.set_emergency_stopped(False)
        runtime.state.set_paused(False)  # Clearing emergency stop intentionally does not resume.
        layer.objects.active = obj
        obj.select_set(True, view_layer=layer)
        assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
        denied("project.native_save_preview", base_params, "NOT_IMPLEMENTED",
               reasons={"OBJECT_PROFILE_UNSUPPORTED", "MESH_EDIT_OR_SHAPE_KEYS_UNSUPPORTED"})
        assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}  # Owned setup only.
        proof["scene_values"]["after_negative_edit_mode"] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
        proof["value_preflights"]["after_negative_edit_mode"] = value_preflight(bpy.data, build_hash=proof["source_build"])
        report.write_text(json.dumps(proof, indent=2) + "\n")
        tasks = [
            ("initial", "SAVE_AS", original, "NATIVE_NEW_EXPECTED"),
            ("copy", "COPY_NEW", artifacts / "artist portable copy.blend", "NO_CLOBBER"),
            ("current", "SAVE_CURRENT", original, "NATIVE_REPLACE_EXPECTED"),
            ("as_new", "SAVE_AS", artifacts / "moved folder" / "artist project.blend", "NATIVE_NEW_EXPECTED"),
            ("as_replace", "SAVE_AS", artifacts / "moved folder" / "artist project.blend", "NATIVE_REPLACE_EXPECTED"),
            ("cancel_reader", "COPY_NEW", artifacts / "cancelled reader copy.blend", "NO_CLOBBER"),
            ("revoke_reader", "COPY_NEW", artifacts / "reader revoked copy.blend", "NO_CLOBBER"),
            ("revoke", "COPY_NEW", artifacts / "revoked copy.blend", "NO_CLOBBER"),
            ("manual", "COPY_NEW", artifacts / "stale copy.blend", "NO_CLOBBER"),
        ]
        active = {"index": -1, "job": None, "task": None, "manual_edit": None, "started": time.monotonic()}

        def begin():
            active["index"] += 1
            if active["index"] >= len(tasks):
                return False
            task, mode, path, overwrite = tasks[active["index"]]
            if task == "copy":
                obj.data.vertices[0].co.x = .125  # New unsaved authored work must reach this output.
            if task == "as_replace":
                obj.data.vertices[0].co.z = .25
            if task in {"revoke", "manual"}:
                assert bpy.ops.blender_codex_bridge.arm_native_save("EXEC_DEFAULT") == {"FINISHED"}
            active["reader_interrupted"] = False
            callbacks["revoke"] = task == "revoke"
            actor.hide_set(False, view_layer=layer)
            for owner in layer.objects:
                owner.select_set(False, view_layer=layer)
            actor.select_set(True, view_layer=layer)
            layer.objects.active = actor
            layer.update()  # Fixture setup before the pending raw diagnostic, never a backend repair.
            proof["scene_values"]["pre_positive:" + task] = scene_value_snapshot(bpy.data, build_hash=proof["source_build"])
            batch = value_preflight(bpy.data, build_hash=proof["source_build"])
            proof["value_preflights"]["pre_positive:" + task] = batch
            report.write_text(json.dumps(proof, indent=2) + "\n")
            assert batch["complete"] and not batch["violations"], batch["violations"]
            actor.hide_set(True, view_layer=layer)
            actor.location = (0., 0., 0.)
            active["raw_before_entry"] = {"selection": raw_selection(layer), "location": list(actor.location)}
            value = dispatch("project.native_save_preview", {"mode": mode, "filepath": str(path),
                                                                      "overwrite_policy": overwrite})
            accepted = dispatch("project.native_save_start", {"preview_id": value["preview_id"],
                "expected_fingerprint": value["fingerprint"], "mode": mode, "filepath": str(path),
                "overwrite_policy": overwrite, "accepted_losses": value["required_accepted_losses"],
                "time_limit_seconds": 120})
            assert accepted["accepted"] and not accepted["job_completed"]
            active["raw_after_start"] = {"selection": raw_selection(layer), "location": list(actor.location)}
            active["task"], active["job"] = task, accepted["job_id"]
            return True

        def poll():
            status = 1
            try:
                assert time.monotonic() - active["started"] < 300, "Native save fixture deadline"
                row = dispatch("jobs.inspect", {"job_id": active["job"]})
                proof["last_job_observation"] = row
                report.write_text(json.dumps(proof, indent=2) + "\n")
                if not row["terminal"]:
                    if (active["task"] in {"cancel_reader", "revoke_reader"}
                            and row["progress"].get("phase") == "fresh_process_reopen"
                            and not active["reader_interrupted"]):
                        if active["task"] == "cancel_reader":
                            dispatch("jobs.cancel", {"job_id": active["job"]})
                        else:
                            assert bpy.ops.blender_codex_bridge.revoke_native_save("EXEC_DEFAULT") == {"FINISHED"}
                        active["reader_interrupted"] = True
                    if (active["task"] == "manual" and row["progress"].get("phase") == "fresh_process_reopen"
                            and active["manual_edit"] is None):
                        obj.data.vertices[0].co.y = .625
                        active["manual_edit"] = list(obj.data.vertices[0].co)
                    return .02
                task = active["task"]
                callbacks["revoke"] = False
                if task not in {"revoke", "manual", "cancel_reader", "revoke_reader"}:
                    assert row["state"] == "SUCCEEDED", row
                    assert row["result"]["fresh_process_reopen_verified"]
                    assert row["external_effects"]["published_bytes_verified"]
                else:
                    assert row["state"] in {"FAILED", "CANCELLED"} and row["result"] is None
                    assert row["external_effects"]["native_save"]["native_save_completed"]
                    assert not tasks[active["index"]][2].exists()
                    if task == "manual":
                        assert active["manual_edit"] is not None
                        assert list(obj.data.vertices[0].co) == active["manual_edit"]
                    if task in {"cancel_reader", "revoke_reader"}:
                        assert active["reader_interrupted"]
                        assert row["external_effects"]["native_save"]["worker_reaped"]
                proof["rows"].append({"case": task, "job": row, "callback_count": callbacks["count"],
                    "raw_before_entry": active["raw_before_entry"], "raw_after_start": active["raw_after_start"],
                    "raw_after_terminal": {"selection": raw_selection(layer), "location": list(actor.location)},
                    "raw_scope": "Complete registered preflight/native/reader workflow; synchronization allowed, no isolated native-call causation or raw-preservation claim"})
                if begin():
                    return .02
                layer.update()  # Owned scope-test setup after all native jobs, not a protected/read-purity claim.
                plan = dispatch("task.plan.set", {"goal": "Keep this mesh", "steps": [
                    {"id": "saved", "description": "Verify native delivery"}], "protected_objects": [obj.name]})
                dispatch("task.plan.enforce", {"enabled": True, "expected_revision": plan["plan"]["revision"]})
                denied("project.native_save_preview", {"mode": "COPY_NEW", "filepath": str(artifacts / "protected copy.blend"),
                                                       "overwrite_policy": "NO_CLOBBER"}, "NOT_IMPLEMENTED")
                proof.update(completed=True, real_local_ui_grant_and_runtime_permissions=True,
                             callback_kind="OWNED_PYTHON_SAVE_POST_NOT_NATIVE_C_CATALOG",
                             callback_path=str(sentinel), callback_count=callbacks["count"],
                             actual_current_filepath=bpy.data.filepath,
                             manual_edit_preserved=active["manual_edit"], protected_scope_still_enforced=True,
                             external_source_folder_unavailable=True,
                             full_project_or_H01_or_1_0_qualified=False, windows_qualified=False)
                report.write_text(json.dumps(proof, indent=2) + "\n")
                print("BLENDER_NATIVE_PROJECT_SAVING_OK " + json.dumps({"blender_version": bpy.app.version_string,
                    "report": str(report), "cases": len(proof["rows"]), "public_end_to_end_fixture": True}), flush=True)
                status = 0
            except Exception as cause:
                persist_failure(proof, report, cause, bridge_error_type=BridgeError)
                traceback.print_exc()
                report.write_text(json.dumps(proof, indent=2) + "\n")
                runtime.jobs.cancel_all("owned fixture failure")
            owned_process_exit(status)

        assert begin()
        bpy.app.timers.register(poll, first_interval=.02)
    except Exception as cause:
        persist_failure(proof, report, cause, bridge_error_type=bridge_error_type)
        traceback.print_exc()
        if runtime is not None:
            runtime.jobs.cancel_all("owned fixture setup failure")
        report.write_text(json.dumps(proof, indent=2) + "\n")
        owned_process_exit(1)


if __name__ == "__main__":
    main()
