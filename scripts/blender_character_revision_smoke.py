"""Bounded typed IK, elbow-weight repair and animated-control revision benchmark.

Run only through the isolated native runner on a disposable factory scene. Raw
APIs construct the provided asset and camera apparatus, observe evaluated data,
and render evidence. Every artist operation uses a registered typed tool. This
does not qualify protected capture, global undo, durable recovery or delivery.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sys
import tempfile
import traceback
from itertools import islice
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
sys.path.insert(0, str(ROOT / "scripts"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import rig_ik  # noqa: E402
from native_character_evidence import (  # noqa: E402
    action,
    animation,
    digest,
    max_difference,
    plain,
    rest,
    rig_rest,
    rna,
)
from native_character_revision_evidence import (  # noqa: E402
    distance,
    ik_metrics,
    lbs_vertices,
    point,
    sanity_checks,
)

RIG, SKIN = "Revision Rig", "Revision Skin"
PROTECTED_RIG, PROTECTED_SKIN = "Protected Revision Rig", "Protected Revision Skin"
TARGET, POLE = "Revision Target", "Revision Pole"
CONSTRAINT = "Revision IK"
PROTECTED_ACTION, TARGET_ACTION = "Protected Revision Motion", "Revised Target Motion"
BONES = ("Upper", "Lower", "Protected")
FRAMES = (1, 4, 6, 11, 16, 19, 21)
POSES = ((1.1, 1.1, 0.), (1.2, .9, .1), (.9, 1.2, .1))
ELBOW = list(range(24, 32))
PROTECTED_VERTICES = list(range(56, 64))
POSE_PATH = 'pose.bones["Lower"].rotation_euler'
TOLERANCE = 2e-4


def matrix(value: Any) -> list[list[float]]:
    return [[float(item) for item in row] for row in value]


def custom_properties(owner: Any) -> dict[str, Any]:
    # Native RNA structs expose ID-property keys, rather than dictionary iteration.
    keys = tuple(owner.keys())
    return {key: plain(owner[key]) for key in keys}


def property_metadata(owner: Any) -> dict[str, Any]:
    """Bounded raw schema evidence retained before the local serializer runs."""
    properties = owner.bl_rna.properties
    return {"type": owner.bl_rna.identifier, "property_count": len(properties),
            "truncated": len(properties) > 256,
            "properties": [{"identifier": prop.identifier, "type": prop.type, "readonly": bool(prop.is_readonly)}
                           for prop in islice(properties, 256)]}


def armature_snapshot(armature: Any) -> dict[str, Any]:
    """Review the two mutable Armature collections instead of skipping them.

    Rest bone geometry/settings/membership are also retained by rig_rest. Bone
    Collection roots, full order, hierarchy, identities, settings, custom data,
    active collection, and exact members are explicitly bounded here.
    """
    metadata = property_metadata(armature)
    assert not metadata["truncated"]
    writable_collections = {prop["identifier"] for prop in metadata["properties"]
                            if prop["type"] == "COLLECTION" and not prop["readonly"]}
    assert writable_collections <= {"collections", "collections_all"}, ("Unreviewed Armature collection", metadata)
    assert len(armature.collections) <= 16 and len(armature.collections_all) <= 16
    roots, collections = list(armature.collections), list(armature.collections_all)
    identities = {collection.as_pointer() for collection in collections}
    assert len(identities) == len(collections)
    records = []
    for collection in collections:
        collection_metadata = property_metadata(collection)
        assert not collection_metadata["truncated"]
        mutable = {prop["identifier"] for prop in collection_metadata["properties"]
                   if prop["type"] == "COLLECTION" and not prop["readonly"]}
        assert mutable <= {"children", "bones"}, ("Unreviewed Bone Collection collection", collection_metadata)
        assert len(collection.children) <= 16 and len(collection.bones) <= len(BONES)
        parent = collection.parent
        assert parent is None or parent.as_pointer() in identities
        assert all(child.as_pointer() in identities for child in collection.children)
        assert all(bone.name in BONES for bone in collection.bones)
        records.append({"identity": collection.as_pointer(), "name": collection.name,
                        "parent": None if parent is None else parent.as_pointer(),
                        "children": [child.as_pointer() for child in collection.children],
                        "members": [{"identity": bone.as_pointer(), "name": bone.name} for bone in collection.bones],
                        "settings": rna(collection, {"children", "bones"}),
                        "custom_properties": custom_properties(collection)})
    active = armature.collections.active
    assert active is None or active.as_pointer() in identities
    assert {collection.as_pointer() for collection in roots} == {
        collection.as_pointer() for collection in collections if collection.parent is None}
    return {"settings": rna(armature, {"use_extra_user", "collections", "collections_all"}),
            "root_order": [collection.as_pointer() for collection in roots],
            "all_order": [collection.as_pointer() for collection in collections],
            "active": None if active is None else active.as_pointer(), "collections": records}


def context_state(layer: Any) -> dict[str, Any]:
    """Read stored-layer flags before any global context/selection getters."""
    selection = [[obj.name, bool(obj.select_get(view_layer=layer))] for obj in layer.objects]
    active = layer.objects.active
    return {"layer": layer.name, "selection": selection,
            "active": None if active is None else active.name,
            "mode": None if active is None else active.mode}


class Proof:
    def __init__(self, runtime: Any, layer: Any, folder: Path):
        self.runtime, self.layer, self.folder = runtime, layer, folder
        self.data: dict[str, Any] = {
            "blender_version": bpy.app.version_string, "process_id": os.getpid(),
            "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "provided_asset_setup": "raw fixture-only geometry, materials, UVs, weights, shared-rest alias, camera and lights",
            "artist_operations": "registered runtime.dispatch only",
            "native_observations": "raw fixture-only frame evaluation, full evaluated vertices/bones, RNA snapshots and camera renders",
            "brief": {"repair": "Only elbow ring: Upper=.5 Lower=.5; preserve locked Detail=.125 and every other membership",
                      "ik": "Connected two-link, preserved lengths, exact target and positive projected-pole elbow branch",
                      "animation": "Independent target Action revised to piecewise linear travel through three reachable poses",
                      "protected": "Complete shared rest data, independently animated alias/skin, unconstrained limb, UVs and materials"},
            "calls": [], "observations": {}, "visuals": [], "completed": False,
            "limitations": {"full_character_acceptance_verified": False, "native_undo_verified": False,
                            "durable_recovery_verified": False, "project_saved": False,
                            "protected_public_capture_qualified": False, "visual_review_completed": False},
        }
        self.flush()

    def flush(self) -> None:
        raw = (json.dumps(self.data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        assert len(raw) < 12 * 1024 * 1024, "Bounded fixture evidence exceeded 12 MiB"
        (self.folder / "character-revision-evidence.json").write_bytes(raw)

    def observe(self, label: str, value: Any) -> Any:
        self.data["observations"][label] = value
        self.flush()  # Preserve native inputs/output before checking any oracle.
        return value

    def call(self, method: str, params: dict[str, Any]) -> Any:
        before = context_state(self.layer)
        row = {"method": method, "params": copy.deepcopy(params), "context_before": before}
        self.data["calls"].append(row)
        self.flush()
        try:
            result = self.runtime.dispatch(method, params)
        except BridgeError as error:
            row["error"] = {"code": error.code, "message": error.message, "context": error.context}
            row["context_after"] = context_state(self.layer)
            self.flush()
            assert row["context_after"] == before, ("Tool changed stored selection/context", method)
            raise
        row["result"], row["context_after"] = result, context_state(self.layer)
        self.flush()
        assert row["context_after"] == before, ("Tool changed stored selection/context", method)
        return result

    def reject(self, code: str, method: str, params: dict[str, Any]) -> BridgeError:
        try:
            self.call(method, params)
        except BridgeError as error:
            assert error.code == code, (method, error.code, error.context)
            return error
        raise AssertionError("Expected explicit refusal: " + method)


def provided_asset(scene: Any, layer: Any) -> tuple[Any, ...]:
    """Construct the small, deliberately defective source asset; no user scene."""
    armature = bpy.data.armatures.new("Revision Shared Rest Data")
    rig = bpy.data.objects.new(RIG, armature)
    scene.collection.objects.link(rig)
    layer.update()  # Settle owned collection membership before taking snapshots.
    selection = [(obj, obj.select_get(view_layer=layer)) for obj in layer.objects]
    active = layer.objects.active
    for obj, _selected in selection:
        obj.select_set(False, view_layer=layer)
    rig.select_set(True, view_layer=layer)
    layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    upper = armature.edit_bones.new("Upper")
    upper.head, upper.tail = (0., 0., 0.), (.25, 1., 0.)
    lower = armature.edit_bones.new("Lower")
    lower.head, lower.tail, lower.parent, lower.use_connect = upper.tail, (0., 2., 0.), upper, True
    protected_bone = armature.edit_bones.new("Protected")
    protected_bone.head, protected_bone.tail = (3., 0., 0.), (3., 1., 0.)
    bpy.ops.object.mode_set(mode="OBJECT")
    for obj, selected in selection:
        obj.select_set(selected, view_layer=layer)
    layer.objects.active = active
    for bone in rig.pose.bones:
        bone.rotation_mode = "XYZ"

    vertices, faces = [], []
    rows = (.1, .4, .75, 1., 1.25, 1.6, 1.9)
    for y in rows:
        x = .25 * (y if y <= 1. else 2. - y)
        vertices.extend((x + .14 * math.cos(angle * math.tau / 8), y, .14 * math.sin(angle * math.tau / 8))
                        for angle in range(8))
    for row in range(6):
        for angle in range(8):
            faces.append((row * 8 + angle, row * 8 + (angle + 1) % 8,
                          (row + 1) * 8 + (angle + 1) % 8, (row + 1) * 8 + angle))
    faces.extend((tuple(reversed(range(8))), tuple(range(48, 56))))
    for y in (.2, .8):
        vertices.extend((3. + .12 * math.cos(angle * math.tau / 4), y, .12 * math.sin(angle * math.tau / 4))
                        for angle in range(4))
    faces.extend((56 + angle, 56 + (angle + 1) % 4, 60 + (angle + 1) % 4, 60 + angle) for angle in range(4))
    faces.extend(((59, 58, 57, 56), (60, 61, 62, 63)))
    mesh = bpy.data.meshes.new("Revision Skin Rest Geometry")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    skin = bpy.data.objects.new(SKIN, mesh)
    scene.collection.objects.link(skin)
    modifier = skin.modifiers.new("Revision Vertex Group Skin", "ARMATURE")
    modifier.object = rig
    modifier.use_deform_preserve_volume = False
    modifier.use_bone_envelopes = False
    groups = {name: skin.vertex_groups.new(name=name) for name in BONES}
    for row, upper_weight in enumerate((1., 1., .75, 1., .25, 0., 0.)):
        indices = list(range(row * 8, (row + 1) * 8))
        groups["Upper"].add(indices, upper_weight, "REPLACE")
        groups["Lower"].add(indices, 1. - upper_weight, "REPLACE")
    groups["Protected"].add(PROTECTED_VERTICES, 1., "REPLACE")
    detail = skin.vertex_groups.new(name="ProtectedDetail")
    detail.add(list(range(len(vertices))), .125, "REPLACE")
    detail.lock_weight = True
    for name, color in (("Revision Blue", (.035, .25, .65, 1.)),
                        ("Elbow Repair Orange", (.9, .22, .035, 1.)),
                        ("Protected Green", (.03, .5, .18, 1.))):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.diffuse_color = color
        material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = color
        material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = .6
        mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.material_index = 2 if min(polygon.vertices) >= 56 else 1 if 16 <= polygon.index < 32 else 0
        polygon.use_smooth = False
    uv = mesh.uv_layers.new(name="Protected Explicit UV")
    for loop, value in zip(mesh.loops, uv.data, strict=True):
        vertex = mesh.vertices[loop.vertex_index]
        value.uv = ((loop.vertex_index % 8) / 8., vertex.co.y / 2.)
    attribute = mesh.attributes.new("Protected Rest Mask", "FLOAT", "POINT")
    for index, value in enumerate(attribute.data):
        value.value = index / 128.
    alias = rig.copy()  # Before IK: shared rest, independent pose and animation.
    alias.name, alias.location.x = PROTECTED_RIG, 4.
    scene.collection.objects.link(alias)
    other = skin.copy()
    other.data = skin.data.copy()
    other.name, other.location.x = PROTECTED_SKIN, 4.
    other.modifiers[0].object = alias
    scene.collection.objects.link(other)
    target, pole = bpy.data.objects.new(TARGET, None), bpy.data.objects.new(POLE, None)
    scene.collection.objects.link(target)
    scene.collection.objects.link(pole)
    target.location, pole.location = POSES[0], (0., 0., 2.)
    target.empty_display_type = pole.empty_display_type = "PLAIN_AXES"
    target.empty_display_size = pole.empty_display_size = .15
    bpy.data.objects["Cube"].hide_render = True
    layer.update()  # All fixture-owned links and raw setup settle BEFORE baselines.
    return rig, skin, alias, other, target, pole


def camera_apparatus(scene: Any, layer: Any) -> None:
    from mathutils import Vector

    camera = bpy.data.objects["Camera"]
    camera.location = (4., -5., 3.5)
    camera.rotation_euler = (Vector((1.35, 1., .1)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type, camera.data.ortho_scale = "ORTHO", 4.7
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.device, scene.cycles.samples = "CPU", 16
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    light = bpy.data.lights.new("Revision Fixture Fill", "AREA")
    light.energy, light.shape, light.size = 600., "DISK", 5.
    lamp = bpy.data.objects.new("Revision Fixture Fill", light)
    scene.collection.objects.link(lamp)
    lamp.location = (1., -2., 4.)
    lamp.rotation_euler = (Vector((1., 1., 0.)) - lamp.location).to_track_quat("-Z", "Y").to_euler()
    layer.update()


def raw_profile(scene: Any, layer: Any, rig: Any, skin: Any, target: Any, pole: Any) -> dict[str, Any]:
    """All native inputs for an independent host-side recomputation, not a tool."""
    before = context_state(layer)
    layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated_rig, evaluated_skin = rig.evaluated_get(graph), skin.evaluated_get(graph)
    mesh = evaluated_skin.to_mesh()
    try:
        output = [list(evaluated_skin.matrix_world @ vertex.co) for vertex in mesh.vertices]
    finally:
        evaluated_skin.to_mesh_clear()
    result = {
        "frame": scene.frame_current, "subframe": scene.frame_subframe,
        "rig_world": matrix(evaluated_rig.matrix_world), "mesh_world": matrix(evaluated_skin.matrix_world),
        "vertices": [{"co": list(vertex.co), "memberships": [
            {"group": skin.vertex_groups[item.group].name, "weight": float(item.weight)} for item in vertex.groups]}
            for vertex in skin.data.vertices],
        "rest_bones": {bone.name: {"matrix": matrix(bone.matrix_local), "head": list(bone.head_local),
                                  "tail": list(bone.tail_local), "use_deform": bool(bone.use_deform)} for bone in rig.data.bones},
        "pose_bones": {bone.name: {"matrix": matrix(bone.matrix), "head": list(bone.head), "tail": list(bone.tail)}
                       for bone in evaluated_rig.pose.bones},
        "evaluated_vertices_world": output,
        "target_world": list(target.evaluated_get(graph).matrix_world.translation),
        "pole_world": list(pole.evaluated_get(graph).matrix_world.translation),
        "stored_context_before": before, "stored_context_after": context_state(layer),
    }
    return result


def protected_semantics(rig: Any, skin: Any) -> dict[str, Any]:
    active = None if rig.animation_data is None else rig.animation_data.action
    return {"rig_rest": rig_rest(rig), "skin_rest": rest(skin), "animation": animation(rig),
            "armature_settings": armature_snapshot(rig.data),
            "object_authored_state": {obj.name: {
                "world": matrix(obj.matrix_world), "basis": matrix(obj.matrix_basis),
                "parent": plain(obj.parent), "parent_type": obj.parent_type, "parent_bone": obj.parent_bone,
                "location": list(obj.location), "rotation_mode": obj.rotation_mode,
                "rotation_euler": list(obj.rotation_euler), "rotation_quaternion": list(obj.rotation_quaternion),
                "rotation_axis_angle": list(obj.rotation_axis_angle), "scale": list(obj.scale),
                "delta_location": list(obj.delta_location), "delta_rotation_euler": list(obj.delta_rotation_euler),
                "delta_rotation_quaternion": list(obj.delta_rotation_quaternion), "delta_scale": list(obj.delta_scale),
                "hide_render": obj.hide_render, "hide_viewport": obj.hide_viewport, "hide_select": obj.hide_select,
                "custom_properties": custom_properties(obj)}
                for obj in (rig, skin)},
            "rest_custom_properties": custom_properties(rig.data),
            "action": None if active is None else action(active),
            "constraints": {bone.name: [rna(item) for item in bone.constraints] for bone in rig.pose.bones},
            "identities": {"rig": rig.as_pointer(), "rest": rig.data.as_pointer(), "skin": skin.as_pointer(),
                           "mesh": skin.data.as_pointer(), "action": None if active is None else active.as_pointer(),
                           "materials": [material.as_pointer() for material in skin.data.materials]}}


def protected_pose(rig: Any) -> dict[str, Any]:
    return {bone.name: {"writable_settings": rna(bone),
                        "custom_properties": custom_properties(bone)}
            for bone in rig.pose.bones}


def author_protected(proof: Proof, rig: Any, skin: Any) -> dict[str, Any]:
    made = proof.call("animation.action_create", {"action_name": PROTECTED_ACTION, "slot_name": rig.name, "keep_on_save": True})
    proof.call("animation.action_bind", {"object_name": rig.name, "action_name": PROTECTED_ACTION,
               "expected_action_name": None, "slot_identifier": made["slot_identifier"], "affected_objects": [skin.name]})
    for frame, angle in ((1, -.25), (21, .35)):
        proof.call("rig.pose_transform", {"object_name": rig.name, "bone_name": "Lower",
                   "rotation_euler": [0., 0., angle], "affected_objects": [skin.name]})
        proof.call("animation.keyframe_insert", {"object_name": rig.name, "data_path": POSE_PATH, "index": 2,
                   "frame": frame, "group": "Protected Lower", "affected_objects": [skin.name]})
    proof.call("animation.curve_edit", {"object_name": rig.name, "data_path": POSE_PATH, "index": 2,
               "slot_identifier": made["slot_identifier"], "affected_objects": [skin.name],
               "keyframes": [{"frame": frame, "interpolation": "LINEAR"} for frame in (1, 21)]})
    return made


def diagnostic(proof: Proof, rig: Any, skin: Any, target: Any) -> dict[str, Any]:
    result = proof.call("rig.deformation_inspect", {"object_name": rig.name, "mesh_object": skin.name,
                       "bone_names": list(BONES), "vertex_indices": list(range(len(skin.data.vertices))),
                       "coordinate_space": "WORLD", "target_object": target.name, "tip_bone_name": "Lower"})
    raw = proof.observe("diagnostic_raw_" + str(len(proof.data["calls"])),
                        raw_profile(bpy.context.scene, proof.layer, rig, skin, target, bpy.data.objects[POLE]))
    assert result["object"] == rig.name and result["mesh_object"] == skin.name and result["frame"] == raw["frame"]
    assert result["topology_correspondence_verified"] and result["complete_weight_coverage"]
    assert result["base_vertex_count"] == result["sampled_vertex_count"] == len(raw["vertices"]) == 64
    assert result["sampled_bone_count"] == len(BONES)
    assert result["geometry_coordinate_space"] == result["bone_coordinate_space"] == "WORLD"
    assert [item["vertex_index"] for item in result["vertex_samples"]] == list(range(64))
    assert [item["vertex_index"] for item in result["weights"]] == list(range(64))
    expected_points = lbs_vertices(raw)
    groups = {group.name: group for group in skin.vertex_groups}
    for index, (vertex, sample, weights) in enumerate(zip(raw["vertices"], result["vertex_samples"], result["weights"], strict=True)):
        assert max_difference(sample["evaluated"], raw["evaluated_vertices_world"][index]) < 2e-5
        assert max_difference(sample["evaluated"], expected_points[index]) < 2e-5
        assert max_difference(sample["base"], point(raw["mesh_world"], vertex["co"])) < 2e-5
        expected_memberships = [{**member, "deforming": member["group"] in BONES,
                                 "locked": groups[member["group"]].lock_weight} for member in vertex["memberships"]]
        assert weights["memberships"] == expected_memberships
        assert abs(weights["deform_weight_sum"] - 1.) < 1e-7
    assert [bone["name"] for bone in result["bones"]] == list(BONES)
    for bone in result["bones"]:
        observed = raw["pose_bones"][bone["name"]]
        assert max_difference(bone["head"], point(raw["rig_world"], observed["head"])) < 2e-5
        assert max_difference(bone["tail"], point(raw["rig_world"], observed["tail"])) < 2e-5
    assert result["unmatched_groups"] == ["ProtectedDetail"]
    assert max_difference(result["endpoint_target"]["target"], raw["target_world"]) < 2e-5
    assert max_difference(result["endpoint_target"]["tip"], point(raw["rig_world"], raw["pose_bones"]["Lower"]["tail"])) < 2e-5
    return result


def validate_curve_inspection(result: dict[str, Any], axis: int, slot: str, *, linear: bool) -> None:
    assert result["object"] == TARGET and result["action"] == TARGET_ACTION and result["slot_identifier"] == slot
    assert result["data_path"] == "location" and result["index"] == axis
    assert result["point_count"] == result["returned_points"] == 3 and not result["truncated"]
    assert result["point_offset"] == 0 and result["next_offset"] is None
    assert [key["frame"] for key in result["keyframes"]] == [1., 11., 21.]
    for key, pose in zip(result["keyframes"], POSES, strict=True):
        assert abs(key["value"] - pose[axis]) < 2e-6
        if linear:
            assert key["interpolation"] == "LINEAR"


def validate_curve_samples(result: dict[str, Any], axis: int, slot: str) -> None:
    assert result["object"] == TARGET and result["action"] == TARGET_ACTION and result["slot_identifier"] == slot
    assert result["data_path"] == "location" and result["index"] == axis
    assert result["point_count"] == 3 and result["sample_count"] == len(FRAMES)
    assert [item["requested_frame"] for item in result["samples"]] == list(FRAMES)
    assert [item["evaluated_frame"] for item in result["samples"]] == list(FRAMES)
    assert result["evaluation_scope"] == "ACTIVE_ACTION_FCURVE" and not result["scene_evaluated"]
    assert not any(result[field] for field in ("includes_nla", "includes_drivers", "includes_constraints", "includes_deformation"))


def validate_lbs(record: dict[str, Any]) -> float:
    error = max_difference(lbs_vertices(record), record["evaluated_vertices_world"])
    assert error < 2e-5, ("Independent complete LBS mismatch", error)
    assert record["stored_context_before"] == record["stored_context_after"]
    for vertex in record["vertices"]:
        weights = {member["group"]: member["weight"] for member in vertex["memberships"]}
        assert abs(sum(value for name, value in weights.items() if name in BONES) - 1.) < 1e-7
        assert weights["ProtectedDetail"] == .125
    return error


def validate_ik(record: dict[str, Any]) -> dict[str, Any]:
    metrics = ik_metrics(record)
    for field in ("root_error", "joint_gap", "endpoint_target_distance", "upper_length_error", "lower_length_error",
                  "pole_plane_error", "positive_branch_error"):
        assert metrics[field] < TOLERANCE, (field, metrics)
    assert metrics["positive_pole_halfspace"] > .1
    assert all(abs(length - math.sqrt(17.) / 4.) < 1e-7 for length in metrics["rest_lengths"])
    return metrics


def capture(proof: Proof, scene: Any, label: str) -> dict[str, Any]:
    """Fixture camera rendering only; no protected product capture claim."""
    path = proof.folder / (label + ".png")
    previous = scene.render.filepath
    before = context_state(proof.layer)
    try:
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    finally:
        scene.render.filepath = previous
    result = {"label": label, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "frame": scene.frame_current, "camera": matrix(scene.camera.matrix_world),
              "ortho_scale": scene.camera.data.ortho_scale, "resolution": [512, 512],
              "engine": scene.render.engine, "samples": scene.cycles.samples,
              "view_transform": scene.view_settings.view_transform,
              "scope": "FIXTURE_CAMERA_RENDER", "reviewed": False,
              "context_before": before, "context_after": context_state(proof.layer)}
    proof.data["visuals"].append(result)
    proof.flush()
    assert result["context_after"] == before
    return result


def constraint_state(constraint: Any) -> dict[str, Any]:
    return {"identity": constraint.as_pointer(), "writable_configuration": rna(constraint)}


def main() -> None:
    assert bpy.app.background, "Use the isolated background native runner"
    bpy.context.preferences.use_preferences_save = False
    scene, layer = bpy.context.scene, bpy.context.scene.view_layers[0]
    folder = Path(tempfile.gettempdir()) / "character-revision-evidence"
    folder.mkdir()
    blender_codex_bridge.register()
    proof = None
    try:
        runtime = get_runtime()
        grants = {permission.value: permission not in {Permission.EXECUTE_PYTHON, Permission.SAVE_PROJECT} for permission in Permission}
        runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
        for toolset in ("rigging", "weights", "animation", "objects"):
            runtime.registry.enable_toolset(toolset)
        rig, skin, alias, other, target, pole = provided_asset(scene, layer)
        camera_apparatus(scene, layer)
        proof = Proof(runtime, layer, folder)
        proof.observe("source_sha256", {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), ROOT / "scripts/native_character_revision_evidence.py", ROOT / "scripts/native_character_evidence.py")})
        proof.observe("oracle_sanity", sanity_checks())
        assert len(skin.data.vertices) == 64 and rig.data == alias.data and skin.data != other.data
        assert not skin.parent and not rig.parent and not alias.pose.bones["Lower"].constraints
        author_protected(proof, alias, other)

        # Raw fixture-only observations establish a different protected baseline
        # at EVERY sampled frame, including complete pose, evaluated bones/skin.
        protected_baseline = {}
        for frame in FRAMES:
            scene.frame_set(frame)
            layer.update()
            protected_baseline[str(frame)] = {"raw": raw_profile(scene, layer, alias, other, target, pole),
                                               "pose": protected_pose(alias)}
        scene.frame_set(1)
        layer.update()
        proof.observe("protected_corresponding_frames_before_semantics", protected_baseline)
        assert len(rig.data.collections_all) <= 16
        proof.observe("armature_schema_before_semantics", {
            "armature": property_metadata(rig.data),
            "bone_collections": [{"name": collection.name, "metadata": property_metadata(collection)}
                                 for collection in rig.data.collections_all]})
        frozen_protected = protected_semantics(alias, other)
        frozen_rest = rig_rest(rig)
        initial_skin = rest(skin)
        proof.observe("provided_asset", {"skin": initial_skin, "rig": frozen_rest,
                      "protected_semantics": frozen_protected, "protected_corresponding_frames": protected_baseline})
        for frame, row in protected_baseline.items():
            validate_lbs(row["raw"])
            expected_angle = -.25 + .6 * (int(frame) - 1) / 20.
            assert max_difference(row["pose"]["Lower"]["writable_settings"]["rotation_euler"], [0., 0., expected_angle]) < 2e-6
        assert max_difference(protected_baseline["1"]["raw"]["evaluated_vertices_world"],
                              protected_baseline["21"]["raw"]["evaluated_vertices_world"]) > .1
        initial_context = context_state(layer)

        def protected_check(label: str) -> None:
            observed = protected_semantics(alias, other)
            raw = raw_profile(scene, layer, alias, other, target, pole)
            current_pose = protected_pose(alias)
            proof.observe(label, {"semantics_sha256": digest(observed), "raw": raw, "pose": current_pose})
            assert observed == frozen_protected, "Protected rest, complete weights, materials or animation changed"
            baseline = protected_baseline[str(scene.frame_current)]
            # Target/pole locations are active workflow inputs, not part of the
            # independent alias's dependency closure. Compare pose/skin only.
            assert max_difference(raw["pose_bones"], baseline["raw"]["pose_bones"]) < 2e-5
            assert max_difference(raw["evaluated_vertices_world"], baseline["raw"]["evaluated_vertices_world"]) < 2e-5
            assert max_difference(current_pose, baseline["pose"]) < 2e-5
            assert rig_rest(rig) == frozen_rest
            validate_lbs(raw)

        diagnostic(proof, rig, skin, target)
        scope = {"object_name": rig.name, "root_bone_name": "Upper", "tip_bone_name": "Lower",
                 "target_object": target.name, "pole_object": pole.name,
                 "affected_meshes": [skin.name], "constraint_name": CONSTRAINT}
        proof.call("rig.ik_configure", {**scope, "create": True, "pole_angle": 0., "influence": 1.,
                                       "iterations": 128, "use_stretch": False})
        constraint = rig.pose.bones["Lower"].constraints[CONSTRAINT]
        trial = proof.observe("static_pole_zero_trial", raw_profile(scene, layer, rig, skin, target, pole))
        trial_metrics = proof.observe("static_pole_zero_metrics", ik_metrics(trial))
        # The desired positive branch is fixed independently of Blender. Inspect
        # angle zero, then make one bounded typed correction if the brief misses.
        chosen_angle = 0.
        if trial_metrics["positive_branch_error"] >= TOLERANCE:
            chosen_angle = math.pi
            proof.call("rig.ik_configure", {**scope, "pole_angle": chosen_angle})
        fixed = proof.observe("static_chosen_branch", raw_profile(scene, layer, rig, skin, target, pole))
        proof.observe("static_chosen_metrics", ik_metrics(fixed))
        validate_ik(fixed)
        validate_lbs(fixed)
        proof.observe("observed_pole_convention", {"chosen_angle": chosen_angle,
                      "scope": "This Blender build and fixture rest orientation only", "desired_branch": "positive projected pole"})

        # Ordinary permission refusal and the previously admitted measured IK
        # post-write fault pattern are exercised while every IK input is STATIC.
        before_constraint = proof.observe("constraint_before_denial", constraint_state(constraint))
        before_failure_skin = rest(skin)
        grants[Permission.EDIT_ANIMATION.value] = False
        try:
            proof.reject("PERMISSION_DENIED", "rig.ik_configure", {**scope, "influence": .3})
        finally:
            grants[Permission.EDIT_ANIMATION.value] = True
        proof.observe("constraint_after_denial", constraint_state(constraint))
        assert constraint_state(constraint) == before_constraint and rest(skin) == before_failure_skin
        original_check, injected = rig_ik._Boundary.check, False

        def fail_after_output(boundary: Any, **kwargs: Any) -> Any:
            nonlocal injected
            result = original_check(boundary, **kwargs)
            if not injected and boundary.constraint is not None and abs(boundary.constraint.influence - .4) < 1e-6:
                injected = True
                raise RuntimeError("Injected measured postwrite failure")
            return result

        rig_ik._Boundary.check = fail_after_output
        try:
            error = proof.reject("OPERATION_FAILED", "rig.ik_configure", {**scope, "influence": .4})
        finally:
            rig_ik._Boundary.check = original_check
        recovered = proof.observe("constraint_after_compensation", {
            "constraint": constraint_state(constraint), "injection_observed": injected,
            "skin": rest(skin), "raw": raw_profile(scene, layer, rig, skin, target, pole)})
        assert injected and error.context["rollback_verified"] and not error.context["possible_mutation"]
        assert recovered["constraint"] == before_constraint and recovered["skin"] == before_failure_skin
        assert max_difference(recovered["raw"]["evaluated_vertices_world"], fixed["evaluated_vertices_world"]) < 2e-5
        protected_check("protected_after_static_recovery")

        bad = proof.observe("bad_elbow_skin", raw_profile(scene, layer, rig, skin, target, pole))
        diagnostic(proof, rig, skin, target)
        desired = {index: {"Upper": .5, "Lower": .5, "ProtectedDetail": .125} for index in ELBOW}
        desired_before = lbs_vertices(bad, desired)
        before_error = max(distance(bad["evaluated_vertices_world"][index], desired_before[index]) for index in ELBOW)
        proof.observe("repair_reference", {"indices": ELBOW, "desired_memberships": desired,
                      "desired_vertices_before": desired_before, "before_max_elbow_error": before_error})
        assert before_error > .03, "Provided defect must have a measurable posed consequence"
        capture(proof, scene, "01-before-elbow-repair")
        brush = {"object_name": skin.name, "vertex_indices": ELBOW,
                 "strokes": [{"center": [.25, 1., 0.], "radius": .2, "strength": 1., "weight": .5}],
                 "coordinate_space": "LOCAL", "blend_mode": "MIX", "falloff": "CONSTANT"}
        locked_before = rest(skin)
        proof.reject("INVALID_ARGUMENT", "weights.brush_stroke", {**brush, "group_name": "ProtectedDetail"})
        assert rest(skin) == locked_before
        for group in ("Upper", "Lower"):
            proof.call("weights.brush_stroke", {**brush, "group_name": group, "protected_groups": ["ProtectedDetail"]})
        repaired_rest = rest(skin)
        expected_rest = copy.deepcopy(initial_skin)
        group_indices = {group["name"]: group["index"] for group in initial_skin["groups"]}
        for index in ELBOW:
            weights = dict(expected_rest["vertices"][index]["weights"])
            weights[group_indices["Upper"]], weights[group_indices["Lower"]] = .5, .5
            expected_rest["vertices"][index]["weights"] = sorted([group, value] for group, value in weights.items())
        repaired = proof.observe("repaired_elbow_skin", raw_profile(scene, layer, rig, skin, target, pole))
        proof.observe("repaired_complete_rest", repaired_rest)
        assert repaired_rest == expected_rest, "Repair changed data outside the two declared group patches"
        validate_lbs(repaired)
        validate_ik(repaired)
        after_error = max_difference(lbs_vertices(repaired, desired), repaired["evaluated_vertices_world"])
        proof.observe("repair_comparison", {"before_max_elbow_error": before_error, "after_all_vertex_desired_error": after_error})
        assert after_error < 2e-5
        assert repaired["evaluated_vertices_world"][56:] == bad["evaluated_vertices_world"][56:]
        capture(proof, scene, "02-after-elbow-repair")
        diagnostic(proof, rig, skin, target)
        protected_check("protected_after_weight_repair")

        for index, pose in enumerate(POSES):
            proof.call("transform.set", {"object_name": target.name, "location": list(pose)})
            raw = proof.observe("static_pose_" + str(index), raw_profile(scene, layer, rig, skin, target, pole))
            proof.observe("static_pose_metrics_" + str(index), ik_metrics(raw))
            validate_ik(raw)
            validate_lbs(raw)
            diagnostic(proof, rig, skin, target)
            assert rest(skin) == repaired_rest
            assert raw["evaluated_vertices_world"][56:] == repaired["evaluated_vertices_world"][56:]
            protected_check("protected_at_static_pose_" + str(index))

        # From here IK is never reconfigured: animated controls fall outside the
        # static IK authoring contract. Ordinary Action tools declare exact users.
        made = proof.call("animation.action_create", {"action_name": TARGET_ACTION, "slot_name": target.name, "keep_on_save": True})
        affected = [rig.name, skin.name]
        proof.call("animation.action_bind", {"object_name": target.name, "action_name": TARGET_ACTION,
                   "expected_action_name": None, "slot_identifier": made["slot_identifier"], "affected_objects": affected})
        for frame, pose in zip((1, 11, 21), POSES, strict=True):
            proof.call("transform.set", {"object_name": target.name, "location": list(pose)})
            for axis in range(3):
                proof.call("animation.keyframe_insert", {"object_name": target.name, "data_path": "location", "index": axis,
                           "frame": frame, "group": "Target Travel", "affected_objects": affected})
        curve_scope = {"object_name": target.name, "data_path": "location", "slot_identifier": made["slot_identifier"]}
        for axis in range(3):
            inspected = proof.call("animation.curve_inspect", {**curve_scope, "index": axis})
            validate_curve_inspection(inspected, axis, made["slot_identifier"], linear=False)
            sampled_before = proof.call("animation.curve_sample", {**curve_scope, "index": axis, "frames": list(FRAMES)})
            validate_curve_samples(sampled_before, axis, made["slot_identifier"])
            proof.call("animation.curve_edit", {**curve_scope, "index": axis, "affected_objects": affected,
                       "keyframes": [{"frame": frame, "interpolation": "LINEAR"} for frame in (1, 11, 21)]})
            inspected_after = proof.call("animation.curve_inspect", {**curve_scope, "index": axis})
            validate_curve_inspection(inspected_after, axis, made["slot_identifier"], linear=True)
            sampled = proof.call("animation.curve_sample", {**curve_scope, "index": axis, "frames": list(FRAMES)})
            validate_curve_samples(sampled, axis, made["slot_identifier"])
            for item in sampled["samples"]:
                frame = item["requested_frame"]
                segment = 0 if frame <= 11 else 1
                factor = (frame - (1 if segment == 0 else 11)) / 10.
                expected = POSES[segment][axis] + factor * (POSES[segment + 1][axis] - POSES[segment][axis])
                assert abs(item["value"] - expected) < 2e-6
        proof.observe("target_complete_action", {"animation": animation(target), "action": action(target.animation_data.action)})

        motion = []
        for frame in FRAMES:
            proof.call("animation.set_frame", {"frame": frame})
            raw = proof.observe("animated_frame_" + str(frame), raw_profile(scene, layer, rig, skin, target, pole))
            metrics = proof.observe("animated_metrics_" + str(frame), ik_metrics(raw))
            lbs_error = validate_lbs(raw)
            validate_ik(raw)
            segment = 0 if frame <= 11 else 1
            factor = (frame - (1 if segment == 0 else 11)) / 10.
            expected_target = [POSES[segment][axis] + factor * (POSES[segment + 1][axis] - POSES[segment][axis]) for axis in range(3)]
            assert distance(raw["target_world"], expected_target) < 2e-6
            diagnosed = diagnostic(proof, rig, skin, target)
            assert diagnosed["topology_correspondence_verified"] and diagnosed["base_vertex_count"] == 64
            assert diagnosed["endpoint_target"]["distance"] < TOLERANCE
            assert diagnosed["unmatched_groups"] == ["ProtectedDetail"]
            assert all(abs(item["deform_weight_sum"] - 1.) < 1e-7 for item in diagnosed["weights"])
            assert all(item["locked"] for vertex in diagnosed["weights"] for item in vertex["memberships"] if item["group"] == "ProtectedDetail")
            assert rest(skin) == repaired_rest
            assert max_difference(raw["evaluated_vertices_world"][56:], repaired["evaluated_vertices_world"][56:]) < 2e-5
            protected_check("protected_at_animated_frame_" + str(frame))
            motion.append({"frame": frame, "lbs_max_error": lbs_error, "ik": metrics})
            if frame in (1, 11, 21):
                capture(proof, scene, "03-motion-frame-" + str(frame))
        proof.observe("motion_summary", motion)
        assert context_state(layer) == initial_context
        assert constraint_state(constraint) == before_constraint
        proof.data["completed"] = True
        proof.flush()
        evidence_path = folder / "character-revision-evidence.json"
        print("BLENDER_CHARACTER_REVISION_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "evidence_file": str(evidence_path),
            "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            "source_vertices": 64, "diagnosed_all_vertices": True, "sampled_frames": list(FRAMES),
            "matched_camera_images": len(proof.data["visuals"]), "artist_operations_registered": True,
            "complete_protected_corresponding_frames_preserved": True,
            "constraint_identity_preserving_measured_compensation": True,
            "desired_elbow_error_before": before_error, "desired_elbow_error_after": after_error,
            **proof.data["limitations"]}, allow_nan=False), flush=True)
    except BaseException as error:
        if proof is not None:
            proof.data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
            proof.flush()
        raise
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
