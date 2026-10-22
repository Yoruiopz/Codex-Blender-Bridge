"""Typed complete rig/skin NLA authoring and independent fresh-process rehydration.

Disposable factory fixtures only; run via the isolated phased native runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT/"addon"))
sys.path.insert(0, str(ROOT/"scripts"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import animation_layers as legacy  # noqa: E402
from blender_codex_bridge.tools import nla_lifecycle  # noqa: E402
from native_character_evidence import (  # noqa: E402
    action,
    animation,
    digest,
    evaluated,
    max_difference,
    plain,
    rest,
    rig_rest,
)
from native_fixture_save import serialize_owned_fixture  # noqa: E402

RIG, SKIN, PROTECTED, OTHER_SKIN = "Character Rig", "Character Skin", "Protected Rig", "Protected Skin"
PATH = 'pose.bones["Deform"].rotation_euler'
FRAMES = (1, 6, 11, 16, 21, 26, 31)
ACTION_NAMES = ("Character Zero", "Character Quarter Turn", "Character Overlay", "Protected Motion")


def setup():
    assert not bpy.app.background
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    for toolset in ("animation", "animation_layers", "rigging", "weights"):
        runtime.registry.enable_toolset(toolset)
    return runtime, grants


def deny(runtime, code, method, params):
    try:
        runtime.dispatch(method, params)
    except BridgeError as error:
        assert error.code == code, (method, error.code, error.context)
        return error
    raise AssertionError("Expected refusal: "+method)


def final_provider_cancellation(runtime, grants, module, helper, method, params):
    """A real running queue request must stop before the next RNA allocation."""
    request = Request(id="character-final-provider-cancel", method=method, params=dict(params))
    queued = QueuedRequest(request)
    assert queued.try_start()
    original_authority, original_permissions = getattr(module, helper), runtime.permissions
    inside_provider, injected = False, False

    def provider():
        nonlocal injected
        if inside_provider:
            injected = True
            queued.cancel_pending(BridgeError("TIMEOUT", "Fixture caller canceled inside final permission provider"))
        return grants

    def final_authority(*args):
        nonlocal inside_provider
        inside_provider = True
        try:
            return original_authority(*args)
        finally:
            inside_provider = False

    runtime.permissions = runtime.executor.permissions = PermissionManager(provider)
    setattr(module, helper, final_authority)
    try:
        response = runtime.executor.execute_request(request, check_cancelled=queued.check_active)
        assert injected and not response.ok and response.error["code"] == "TIMEOUT", response.to_dict()
        assert response.error["context"]["possible_mutation"] is False
    finally:
        setattr(module, helper, original_authority)
        runtime.permissions = runtime.executor.permissions = original_permissions


def create_fixture(runtime):
    call = runtime.dispatch
    call("rig.create", {"name": RIG, "root_bone_name": "Root", "root_head": [0., 0., 0.], "root_tail": [0., 1., 0.]})
    call("rig.bone_add", {"object_name": RIG, "bone_name": "Deform", "head": [0., 1., 0.], "tail": [0., 2., 0.], "parent_name": "Root"})
    mesh = bpy.data.meshes.new("Character Skin Data")
    vertices = [(x, y, 0.) for y in (.25, .75, 1., 1.25, 1.75) for x in (-.15, .15)]
    faces = [(2*row, 2*row+1, 2*row+3, 2*row+2) for row in range(4)]
    mesh.from_pydata(vertices, [], faces)
    skin = bpy.data.objects.new(SKIN, mesh)
    bpy.context.scene.collection.objects.link(skin)
    material = bpy.data.materials.new("Shared Protected Procedural Material")
    material.use_nodes = True
    material.diffuse_color = (.2, .45, .12, 1.)
    material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (.2, .45, .12, 1.)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="Character UV")
    for corner, point in zip(uv.data, mesh.loops, strict=True):
        coordinate = mesh.vertices[point.vertex_index].co
        corner.uv = (coordinate.x/.3+.5, coordinate.y/2.)
    attribute = mesh.attributes.new("Protected Rest Mask", "FLOAT", "POINT")
    for index, value in enumerate(attribute.data):
        value.value = index*.125
    call("rig.bind_mesh", {"mesh_object": SKIN, "armature_object": RIG, "method": "EMPTY_GROUPS", "parent": False})
    for name, indices, weight in (("Root", [0, 1, 2, 3], 1.), ("Root", [4, 5], .5),
                                   ("Deform", [4, 5], .5), ("Deform", [6, 7, 8, 9], 1.)):
        call("weights.assign", {"object_name": SKIN, "group_name": name, "vertex_indices": indices, "weight": weight})
    rig = bpy.data.objects[RIG]
    protected = rig.copy()
    protected.name = PROTECTED
    protected.location.x = 4.
    bpy.context.scene.collection.objects.link(protected)
    other = skin.copy()
    other.data = skin.data.copy()
    other.name = OTHER_SKIN
    other.location.x = 4.
    other.modifiers[0].object = protected
    bpy.context.scene.collection.objects.link(other)
    for owner in (rig, protected):
        for bone in owner.pose.bones:
            bone.rotation_mode = "XYZ"
    bpy.context.view_layer.update()
    return rig, skin, protected, other


def author(runtime, owner, dependent, name, angles, end=11):
    made = runtime.dispatch("animation.action_create", {"action_name": name, "slot_name": owner.name, "keep_on_save": True})
    previous = None if owner.animation_data is None else owner.animation_data.action
    runtime.dispatch("animation.action_bind", {"object_name": owner.name, "action_name": name,
        "expected_action_name": None if previous is None else previous.name,
        "slot_identifier": made["slot_identifier"], "affected_objects": [dependent.name]})
    for frame, angle in zip((1, end), angles, strict=True):
        runtime.dispatch("rig.pose_transform", {"object_name": owner.name, "bone_name": "Deform",
            "rotation_euler": [0., 0., angle], "affected_objects": [dependent.name]})
        runtime.dispatch("animation.keyframe_insert", {"object_name": owner.name, "data_path": PATH,
            "index": 2, "frame": frame, "group": "Deform", "affected_objects": [dependent.name]})
    runtime.dispatch("animation.curve_edit", {"object_name": owner.name, "data_path": PATH, "index": 2,
        "slot_identifier": made["slot_identifier"], "affected_objects": [dependent.name],
        "keyframes": [{"frame": frame, "interpolation": "LINEAR"} for frame in (1, end)]})
    return made


def rest_profile():
    return {"skin": rest(bpy.data.objects[SKIN]), "protected_skin": rest(bpy.data.objects[OTHER_SKIN]),
            "rig": rig_rest(bpy.data.objects[RIG]), "protected_rig": rig_rest(bpy.data.objects[PROTECTED])}


def semantics():
    return {"actions": {name: action(bpy.data.actions[name]) for name in ACTION_NAMES},
            "rig": animation(bpy.data.objects[RIG]), "protected_rig": animation(bpy.data.objects[PROTECTED])}


def samples(expected_rest=None):
    result = []
    for frame in FRAMES:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        current_rest = rest_profile()
        result.append({"actor": evaluated(bpy.context.scene, graph, bpy.data.objects[RIG], bpy.data.objects[SKIN]),
                       "protected": evaluated(bpy.context.scene, graph, bpy.data.objects[PROTECTED], bpy.data.objects[OTHER_SKIN]),
                       "protected_rest_sha256": digest(current_rest)})
        if expected_rest is not None:
            assert current_rest == expected_rest, "Base geometry/material/UV/weights/rig hierarchy changed during playback"
    return result


def analytic(records, overlay=False):
    rest_mesh = bpy.data.objects[SKIN].data
    errors = []
    for record in records:
        frame = record["actor"]["frame"]
        angle = -math.pi/4 if overlay else 0. if frame <= 11 else math.pi/2 if frame >= 21 else (frame-11)/10*math.pi/2
        for vertex, actual in zip(rest_mesh.vertices, record["actor"]["vertices"], strict=True):
            x, y, z = vertex.co
            weight = sum(member.weight for member in vertex.groups if bpy.data.objects[SKIN].vertex_groups[member.group].name == "Deform")
            turned = (math.cos(angle)*x-math.sin(angle)*(y-1.), 1.+math.sin(angle)*x+math.cos(angle)*(y-1.), z)
            expected = [weight*turned[index]+(1-weight)*value for index, value in enumerate((x, y, z))]
            errors.append(max_difference(expected, actual))
        matrix = record["actor"]["bones"]["Deform"]
        errors.append(abs(matrix[0][0]-math.cos(angle)))
        errors.append(abs(matrix[1][0]-math.sin(angle)))
    error = max(errors)
    assert error < 2e-5, ("Independent complete skin/pose deformation differs", error, overlay)
    return error


def capture_motion(runtime, bundle, phase, expected_rest):
    """Retain fixed, matched numerical-context images for later artist review."""
    scene = bpy.context.scene
    area = next((item for item in bpy.context.screen.areas if item.type == "VIEW_3D"), None)
    if area is None:
        area = next(item for item in bpy.context.screen.areas if item.type == "NLA_EDITOR")
    original_type, original_frame, original_subframe = area.type, scene.frame_current, scene.frame_subframe
    area.type = "VIEW_3D"  # Fixture-owned UI; no product tool changes editor types.
    space, records = area.spaces.active, []
    region = space.region_3d
    view_fields = ("view_distance", "view_location", "view_rotation", "view_perspective", "view_camera_offset", "view_camera_zoom")
    original_view = {field: plain(getattr(region, field)) for field in view_fields}
    settings = {"light": "STUDIO", "studio_light": "paint.sl", "color_type": "SINGLE",
        "single_color": (.25, .65, .3), "background_type": "VIEWPORT", "background_color": (.04, .04, .04),
        "show_shadows": True, "show_cavity": False, "show_specular_highlight": False, "show_xray": False}
    original_shading = {field: plain(getattr(space.shading, field)) for field in settings}
    camera_settings = {"lens": 50., "clip_start": .01, "clip_end": 100.}
    original_camera = {field: plain(getattr(space, field)) for field in camera_settings}
    folder = bundle/"visuals"
    folder.mkdir(exist_ok=True)
    try:
        for field, value in settings.items():
            setattr(space.shading, field, value)
        for field, value in camera_settings.items():
            setattr(space, field, value)
        for frame in (1, 16, 31):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            assert rest_profile() == expected_rest
            for label, name in (("primary", SKIN), ("protected", OTHER_SKIN)):
                owner = bpy.data.objects[name]
                region.view_rotation, region.view_perspective = (1., 0., 0., 0.), "ORTHO"
                region.view_distance = 3.25
                region.view_location = owner.matrix_world.translation + Vector((0., 1., 0.))
                region.view_camera_offset, region.view_camera_zoom = (0., 0.), 0.
                view = {field: plain(getattr(region, field)) for field in view_fields}
                view["shading"] = {field: plain(getattr(space.shading, field)) for field in settings}
                view["camera"] = {field: plain(getattr(space, field)) for field in camera_settings}
                captured = runtime.dispatch("viewport.capture", {"object_name": name, "view": "current", "shading": "solid",
                    "include_overlays": False, "resolution": [512, 512]})
                assert captured["resolution_matches_request"] and captured["source"] == "viewport_opengl"
                path = folder/f"{phase}-{label}-frame-{frame:03d}.png"
                content = Path(captured["path"]).read_bytes()
                path.write_bytes(content)
                records.append({"object": name, "frame": frame, "relative_path": str(path.relative_to(bundle)),
                    "sha256": hashlib.sha256(content).hexdigest(), "width": captured["width"], "height": captured["height"],
                    "view_settings": view, "capture": {key: value for key, value in captured.items() if key not in {"path", "temporary"}},
                    "artist_visual_review_verified": False})
                assert rest_profile() == expected_rest
    finally:
        scene.frame_set(original_frame, subframe=original_subframe)
        for field, value in original_view.items():
            setattr(region, field, value)
        for field, value in original_shading.items():
            setattr(space.shading, field, value)
        for field, value in original_camera.items():
            setattr(space, field, value)
        area.type = original_type
        bpy.context.view_layer.update()
    return records


def writer(bundle):
    runtime, grants = setup()
    rig, skin, protected, other = create_fixture(runtime)
    a = author(runtime, rig, skin, ACTION_NAMES[0], (0., 0.))
    b = author(runtime, rig, skin, ACTION_NAMES[1], (math.pi/2, math.pi/2))
    c = author(runtime, rig, skin, ACTION_NAMES[2], (-math.pi/4, -math.pi/4), 31)
    author(runtime, protected, other, ACTION_NAMES[3], (0., math.pi/6), 31)
    runtime.dispatch("animation.action_bind", {"object_name": RIG, "action_name": ACTION_NAMES[0],
        "expected_action_name": ACTION_NAMES[2], "slot_identifier": a["slot_identifier"], "affected_objects": [SKIN]})
    profile = rest_profile()
    protected_before = [record["protected"] for record in samples(profile)]
    action_hashes = {name: digest(action(bpy.data.actions[name])) for name in ACTION_NAMES}
    params = {"object_name": RIG, "track_name": "Character Motion", "strip_name": "Left", "expected_action_name": ACTION_NAMES[0]}
    deny(runtime, "NOT_IMPLEMENTED", "nla.push_down", params)  # Omission keeps old single-owner scope.
    deny(runtime, "INVALID_ARGUMENT", "nla.push_down", {**params, "affected_objects": [SKIN], "expected_action_name": "Wrong Action"})
    deny(runtime, "INVALID_ARGUMENT", "nla.push_down", {**params, "affected_objects": [SKIN, OTHER_SKIN]})
    grants[Permission.EDIT_ANIMATION.value] = False
    deny(runtime, "PERMISSION_DENIED", "nla.push_down", {**params, "affected_objects": [SKIN]})
    grants[Permission.EDIT_ANIMATION.value] = True
    assert not len(rig.animation_data.nla_tracks)
    runtime.state.set_paused(True)
    deny(runtime, "AGENT_PAUSED", "nla.push_down", {**params, "affected_objects": [SKIN]})
    runtime.state.set_paused(False)
    runtime.state.set_emergency_stopped(True)
    deny(runtime, "EMERGENCY_STOPPED", "nla.push_down", {**params, "affected_objects": [SKIN]})
    runtime.state.set_emergency_stopped(False)
    runtime.state.set_paused(False)  # Clearing the latch deliberately does not resume edits.
    # A foreign manual consumer edit after preflight must survive the refusal;
    # the fixture explicitly restores its own injected modifier afterwards.
    original_gate, interleaved = legacy._LegacyNlaGuard.gate, False
    def changed_consumer(self):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            skin.modifiers[0].object = protected
        return original_gate(self)
    legacy._LegacyNlaGuard.gate = changed_consumer
    try:
        failed = deny(runtime, "INVALID_ARGUMENT", "nla.push_down", {**params, "affected_objects": [SKIN]})
        assert not failed.context["possible_mutation"] and not len(rig.animation_data.nla_tracks)
        assert skin.modifiers[0].object == protected
    finally:
        legacy._LegacyNlaGuard.gate = original_gate
        skin.modifiers[0].object = rig
    assert rest_profile() == profile
    # An injected failure after the verified strip constructor retains its known
    # allocation identity even before the Python caller receives the return value.
    original_add, injected = legacy._LegacyNlaGuard.add_strip, False
    def fail_after_constructor(self, *args, **kwargs):
        nonlocal injected
        result = original_add(self, *args, **kwargs)
        if not injected:
            injected = True
            raise RuntimeError("Injected after verified native clip constructor")
        return result
    legacy._LegacyNlaGuard.add_strip = fail_after_constructor
    try:
        failed = deny(runtime, "OPERATION_FAILED", "nla.push_down", {**params, "affected_objects": [SKIN]})
        assert failed.context["rollback_verified"] and not failed.context["possible_mutation"]
        assert not len(rig.animation_data.nla_tracks) and rig.animation_data.action.name == ACTION_NAMES[0]
    finally:
        legacy._LegacyNlaGuard.add_strip = original_add
    final_provider_cancellation(runtime, grants, legacy, "_nla_authority", "nla.push_down", {**params, "affected_objects": [SKIN]})
    assert not len(rig.animation_data.nla_tracks) and rig.animation_data.action.name == ACTION_NAMES[0]
    pushed = runtime.dispatch("nla.push_down", {**params, "affected_objects": [SKIN]})
    assert pushed["affected_objects"] == [RIG, SKIN] and rig.animation_data.action is None
    final_provider_cancellation(runtime, grants, nla_lifecycle, "_quiet_authority", "nla.clip_add", {
        "object_name": RIG, "affected_objects": [SKIN], "track_name": "Character Motion", "strip_name": "Canceled Clip",
        "action_name": ACTION_NAMES[1], "slot_identifier": b["slot_identifier"], "frame_start": 21})
    assert [item.name for item in rig.animation_data.nla_tracks["Character Motion"].strips] == ["Left"]
    runtime.dispatch("nla.clip_add", {"object_name": RIG, "affected_objects": [SKIN], "track_name": "Character Motion",
        "strip_name": "Right", "action_name": ACTION_NAMES[1], "slot_identifier": b["slot_identifier"], "frame_start": 21})
    deny(runtime, "NOT_IMPLEMENTED", "nla.transition_add", {"object_name": RIG, "affected_objects": [SKIN],
        "track_name": "Character Motion", "left_strip": "Left", "right_strip": "Right", "new_name": "No Editor"})
    assert len(rig.animation_data.nla_tracks["Character Motion"].strips) == 2
    # Explicit native editor setup belongs to the disposable harness.
    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    area.type = "NLA_EDITOR"
    runtime.dispatch("nla.transition_add", {"object_name": RIG, "affected_objects": [SKIN], "track_name": "Character Motion",
        "left_strip": "Left", "right_strip": "Right", "new_name": "Character Blend"})
    motion = samples(profile)
    maximum = analytic(motion)
    assert [record["protected"] for record in motion] == protected_before
    runtime.dispatch("nla.add_strip", {"object_name": RIG, "affected_objects": [SKIN], "track_name": "Character Overlay",
        "strip_name": "Overlay", "action_name": ACTION_NAMES[2], "slot_identifier": c["slot_identifier"], "frame_start": 1})
    overlay = samples(profile)
    overlay_error = analytic(overlay, True)
    runtime.dispatch("nla.track_reorder", {"object_name": RIG, "affected_objects": [SKIN],
        "track_names": ["Character Overlay", "Character Motion"]})
    revised = samples(profile)
    assert max_difference(revised, motion) < 2e-5 and [record["protected"] for record in revised] == protected_before
    assert {name: digest(action(bpy.data.actions[name])) for name in ACTION_NAMES} == action_hashes
    # Post-setter denial must retain its measured partial state and cannot write
    # unauthorized compensation. Recovery is a separately authorized exact call.
    original_write, revoked = legacy._LegacyNlaGuard.write, False
    def revoke_after_write(self, expected, operation):
        nonlocal revoked
        result = original_write(self, expected, operation)
        if not revoked:
            revoked = True
            grants[Permission.EDIT_ANIMATION.value] = False
        return result
    legacy._LegacyNlaGuard.write = revoke_after_write
    try:
        failed = deny(runtime, "PERMISSION_DENIED", "nla.edit_track", {"object_name": RIG, "affected_objects": [SKIN],
            "track_name": "Character Overlay", "settings": {"mute": True, "lock": True}})
        assert failed.context["possible_mutation"] and not failed.context["rollback_verified"]
        assert rig.animation_data.nla_tracks["Character Overlay"].mute and not rig.animation_data.nla_tracks["Character Overlay"].lock
    finally:
        legacy._LegacyNlaGuard.write = original_write
        grants[Permission.EDIT_ANIMATION.value] = True
    runtime.dispatch("nla.edit_track", {"object_name": RIG, "affected_objects": [SKIN], "track_name": "Character Overlay", "settings": {"mute": False}})
    # Exact transition removal is recovered through the finalized native undo
    # checkpoint, then every pointer is reacquired instead of carrying stale RNA.
    runtime.dispatch("nla.transition_remove", {"object_name": RIG, "affected_objects": [SKIN], "track_name": "Character Motion",
        "left_strip": "Left", "right_strip": "Right", "transition_name": "Character Blend", "confirm": True})
    undone = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
    assert undone["snapshot_marker_verified"]
    assert bpy.data.objects[RIG].animation_data.nla_tracks["Character Motion"].strips["Character Blend"].type == "TRANSITION"
    assert max_difference(samples(profile), revised) < 2e-5
    visuals = capture_motion(runtime, bundle, "writer", profile)
    # Public saving is refused; owned fixture serialization prepares reopen input.
    path = bundle/"character-nla.blend"
    grants[Permission.SAVE_PROJECT.value] = False
    deny(runtime, "PERMISSION_DENIED", "project.save", {"filepath": str(path)})
    assert not path.exists()
    grants[Permission.SAVE_PROJECT.value] = True
    fixture_save = serialize_owned_fixture(runtime, path)
    manifest = {"writer_process": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rest": profile, "semantics": semantics(), "samples": revised, "protected_samples": protected_before,
        "visuals": visuals}
    (bundle/"character-expected.json").write_text(json.dumps(manifest, allow_nan=False), encoding="utf-8")
    return {**fixture_save, "whole_character_typed_action_firsttrack_clip_transition_nonempty_reorder_verified": True,
        "independent_complete_skin_and_bone_error": maximum, "overlay_skin_error": overlay_error,
        "protected_base_geometry_weights_uv_materials_rest_hierarchy_all_frames_verified": True,
        "protected_independent_animation_and_shared_armature_data_preserved": True,
        "permission_closure_denial_late_revocation_separate_recovery_and_native_undo_verified": True,
        "pause_stop_missing_editor_and_manual_consumer_interleaving_refused": True,
        "post_constructor_failure_measured_identity_preserving_compensation_verified": True,
        "final_provider_running_request_cancellation_prevents_legacy_and_lifecycle_rna_allocations": True,
        "matched_fixed_view_skin_images_retained_for_review": len(visuals),
        "fixture_project_serialized": True, "raw_python_permission_enabled": grants[Permission.EXECUTE_PYTHON.value],
        "artist_visual_review_verified": False, "full_character_acceptance_verified": False}


def reader(bundle):
    manifest = json.loads((bundle/"character-expected.json").read_text(encoding="utf-8"))
    assert manifest["writer_process"] != os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    assert hashlib.sha256((bundle/"character-nla.blend").read_bytes()).hexdigest() == manifest["file_sha256"]
    bpy.ops.wm.open_mainfile(filepath=str(bundle/"character-nla.blend"), load_ui=False)
    def verify():
        runtime, _grants = setup()
        fresh = samples(manifest["rest"])
        assert max_difference(rest_profile(), manifest["rest"]) < 1e-7
        semantic_error = max_difference(semantics(), manifest["semantics"])
        assert semantic_error < 1e-7
        assert max_difference(fresh, manifest["samples"]) < 2e-5
        maximum = analytic(fresh)
        assert bpy.data.objects[RIG].data == bpy.data.objects[PROTECTED].data
        assert [record["protected"] for record in fresh] == manifest["protected_samples"]
        # Freshly re-resolve every target/slot. No writer pointer or restoration
        # token supplies authority in this process. load_ui=False deliberately
        # keeps the fresh profile, so explicitly establish its disposable editor.
        area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
        area.type = "NLA_EDITOR"
        runtime.dispatch("nla.track_reorder", {"object_name": RIG, "affected_objects": [SKIN],
            "track_names": ["Character Motion", "Character Overlay"]})
        analytic(samples(manifest["rest"]), True)
        runtime.dispatch("nla.track_reorder", {"object_name": RIG, "affected_objects": [SKIN],
            "track_names": ["Character Overlay", "Character Motion"]})
        assert max_difference(samples(manifest["rest"]), manifest["samples"]) < 2e-5
        visuals = capture_motion(runtime, bundle, "reader", manifest["rest"])
        for current, previous in zip(visuals, manifest["visuals"], strict=True):
            assert current["object"] == previous["object"] and current["frame"] == previous["frame"]
            assert current["view_settings"] == previous["view_settings"]
            assert hashlib.sha256((bundle/previous["relative_path"]).read_bytes()).hexdigest() == previous["sha256"]
        (bundle/"character-reader-visuals.json").write_text(json.dumps(visuals, allow_nan=False), encoding="utf-8")
        result = {"fresh_process_nla_actions_slots_tracks_transitions_controls_semantic_rehydration_verified": True,
            "semantic_maximum_numeric_error": semantic_error, "independent_complete_skin_pose_error": maximum,
            "protected_geometry_weights_uv_materials_rest_rig_and_animation_verified": True,
            "fresh_authorization_new_revision_and_recovery_verified": True, "project_saved_by_reader": False,
            "native_fixture_owned_reopen": True, "product_project_open_tool_implemented": False,
            "matched_fixed_view_skin_images_retained_for_review": len(visuals),
            "artist_visual_review_verified": False, "full_character_acceptance_verified": False}
        finish("reader", result)
    bpy.app.timers.register(lambda: guarded(verify), first_interval=.2)
    return None


def finish(phase, result):
    result.update(phase=phase, process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
        process_id=os.getpid(), blender_version=bpy.app.version_string)
    print("BLENDER_CHARACTER_NLA_"+phase.upper()+"_OK "+json.dumps(result, allow_nan=False), flush=True)
    bpy.ops.wm.quit_blender()


def guarded(function):
    try:
        function()
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    if args.bridge_phase == "writer":
        finish("writer", writer(args.bridge_bundle))
    else:
        reader(args.bridge_bundle)


if __name__ == "__main__":
    bpy.app.timers.register(lambda: guarded(main), first_interval=1.)
