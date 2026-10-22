"""Typed rig edit boundaries in an official-runner disposable process."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _rigging_edit as proof  # noqa: E402


def persistent(rig, skin):
    rest = []
    for record in proof._rest(None, rig):
        custom, _memberships, color = record[4]
        rest.append((*record[:4], (custom, tuple(item.name for item in rig.data.bones[record[0]].collections), color), record[5]))
    geometry = proof.measured._data_state(skin)[1]
    return {"rest": rest, "pose": proof._pose(rig), "action": proof.scope.action_content(rig.animation_data.action),
            "skin_geometry": geometry, "groups": tuple(proof.scope.rna_state(group) for group in skin.vertex_groups),
            "skin_location": tuple(skin.location), "modifier": [(item.name, item.type, item.object.name) for item in skin.modifiers]}


def writer(bundle=None):
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    for name in ("rigging", "animation"):
        runtime.registry.enable_toolset(name)
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    created = runtime.dispatch("rig.create", {"name": "Boundary Rig", "root_bone_name": "Root"})
    rig = bpy.data.objects[created["object"]]
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    def call(method, **params):
        return runtime.dispatch(method, {"object_name": rig.name, **params})
    call("rig.bone_add", bone_name="Child.Temp", head=[0, 0, 1], tail=[0, 0, 2], parent_name="Root", use_connect=True)
    original_radii = (rig.data.bones["Root"].tail_radius, rig.data.bones["Child.Temp"].head_radius)
    call("rig.pose_transform", bone_name="Child.Temp", location=[.15, .25, .35])
    call("rig.bone_update", bone_name="Child.Temp", new_name="Child", use_deform=False, tail=[.25, 0, 2], roll=.1)
    assert math.isclose(rig.pose.bones["Child"].location.x, .15, abs_tol=1e-6)
    assert (rig.data.bones["Root"].tail_radius, rig.data.bones["Child"].head_radius) == original_radii
    call("rig.bone_update", bone_name="Root", new_name="Origin")
    assert rig.data.bones["Child"].parent.name == "Origin"
    call("rig.bone_update", bone_name="Origin", new_name="Root")
    call("rig.bone_add", bone_name="Removable", head=[3, 0, 0], tail=[3, 0, 1])
    call("rig.bone_add", bone_name="Reparented", head=[3, 0, 1], tail=[3, 0, 2], parent_name="Removable")
    before_invalid = proof._session(bpy)
    try:
        call("rig.bone_remove", bone_name="Removable")
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    else:
        raise AssertionError("Children were removed without explicit reparenting")
    assert proof._session(bpy) == before_invalid
    call("rig.bone_remove", bone_name="Removable", reparent_children=True)
    assert set(rig.data.bones.keys()) == {"Root", "Child", "Reparented"} and rig.data.bones["Reparented"].parent is None
    call("rig.pose_transform", bone_name="Child", location=[.2, .3, .4], rotation_euler=[.1, .2, .3])
    target = bpy.data.objects.new("Boundary Constraint Target", None)
    bpy.context.scene.collection.objects.link(target)
    call("rig.constraint_add", bone_name="Child", constraint_type="COPY_LOCATION", name="Owned Copy", target_object=target.name, influence=.25)
    call("rig.constraint_remove", bone_name="Child", constraint_name="Owned Copy")
    data = bpy.data.meshes.new("Boundary Skin Data")
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 1)], [], [(0, 1, 2)])
    skin = bpy.data.objects.new("Boundary Skin", data)
    bpy.context.scene.collection.objects.link(skin)
    group = skin.vertex_groups.new(name="Root")
    group.add([0, 1, 2], 1., "REPLACE")
    modifier = skin.modifiers.new("Skin", "ARMATURE")
    modifier.object = rig
    skin_before = proof.measured._object_state(skin)
    try:
        call("rig.pose_transform", bone_name="Child", location=[1, 0, 0])
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    else:
        raise AssertionError("Unreviewed skin closure was accepted")
    call("rig.pose_transform", bone_name="Child", location=[.5, 0, 0], affected_objects=[skin.name])
    runtime.dispatch("animation.keyframe_insert", {"object_name": rig.name, "data_path": 'pose.bones["Child"].location', "frame": 1, "group": "Child", "affected_objects": [skin.name]})
    action_before = proof.scope.action_content(rig.animation_data.action)
    call("rig.pose_transform", bone_name="Child", location=[.75, 0, 0], affected_objects=[skin.name])
    assert proof.scope.action_content(rig.animation_data.action) == action_before
    assert proof.measured._object_state(skin) == skin_before
    for method, params in (("rig.bone_update", {"bone_name": "Child", "new_name": "Unsafe"}), ("rig.bone_remove", {"bone_name": "Child"})):
        try:
            call(method, affected_objects=[skin.name], **params)
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED"
        else:
            raise AssertionError("Native reference propagation was accepted without a transaction")
    original = proof._authority
    stops = []
    for stop in ("permission", "pause", "emergency", "cancel", "manual"):
        call("rig.pose_transform", bone_name="Child", location=[.75, 0, 0], scale=[1, 1, 1], affected_objects=[skin.name])
        fired = []
        def inject(context, method, permissions, *, stop=stop, fired=fired):
            original(context, method, permissions)
            if method != "rig.pose_transform" or fired or not math.isclose(rig.pose.bones["Child"].location.x, .8, abs_tol=1e-6):
                return
            fired.append(True)
            if stop == "permission":
                grants[Permission.EDIT_ANIMATION.value] = False
            elif stop == "pause":
                runtime.state.set_paused(True)
            elif stop == "emergency":
                runtime.state.set_emergency_stopped(True)
            elif stop == "cancel":
                raise BridgeError("TIMEOUT", "Injected canceled caller")
            else:
                skin.location.z = 7.
            if stop != "manual":
                original(context, method, permissions)
        proof._authority = inject
        try:
            call("rig.pose_transform", bone_name="Child", location=[.8, 0, 0], scale=[2, 2, 2], affected_objects=[skin.name])
        except BridgeError as error:
            assert error.context["possible_mutation"] and not error.context["rollback_verified"]
        else:
            raise AssertionError("Live stop or protected edit was ignored")
        finally:
            proof._authority = original
            grants[Permission.EDIT_ANIMATION.value] = True
            runtime.state.set_paused(False)
            runtime.state.set_emergency_stopped(False)
        assert fired and tuple(rig.pose.bones["Child"].scale) == (1., 1., 1.)
        if stop == "manual":
            assert skin.location.z == 7.
            skin.location.z = 0.
        stops.append(stop)
    call("rig.pose_transform", bone_name="Child", location=[.75, 0, 0], affected_objects=[skin.name])
    assert tuple(rig.pose.bones["Child"].location) == (.75, 0., 0.)
    assert proof.scope.action_content(rig.animation_data.action) == action_before
    assert proof.measured._object_state(skin) == skin_before

    original_allocate = proof.Creation.allocate
    def revoke_new_data(self, callback):
        item = original_allocate(self, callback)
        if item.name == "Retained DataArmature":
            grants[Permission.EDIT_ANIMATION.value] = False
        return item
    proof.Creation.allocate = revoke_new_data
    try:
        runtime.dispatch("rig.create", {"name": "Retained Data"})
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED" and error.context["retained_ids"][0]["name"] == "Retained DataArmature"
        assert not error.context["automatic_id_deletion"]
    else:
        raise AssertionError("Revoked creation continued")
    finally:
        proof.Creation.allocate = original_allocate
        grants[Permission.EDIT_ANIMATION.value] = True
    assert bpy.data.armatures.get("Retained DataArmature") is not None and bpy.data.objects.get("Retained Data") is None

    recovery = runtime.dispatch("rig.create", {"name": "Context Recovery Rig"})
    recovery_rig = bpy.data.objects[recovery["object"]]
    context_fired = []
    def stop_during_edit(context, method, permissions):
        original(context, method, permissions)
        bone = recovery_rig.data.edit_bones.get("Retained Bone") if recovery_rig.mode == "EDIT" else None
        if method == "rig.bone_add" and bone is not None and math.isclose(bone.head.x, 3., abs_tol=1e-6):
            context_fired.append(True)
            grants[Permission.EDIT_ANIMATION.value] = False
            original(context, method, permissions)
    proof._authority = stop_during_edit
    try:
        runtime.dispatch("rig.bone_add", {"object_name": recovery_rig.name, "bone_name": "Retained Bone", "head": [3, 0, 0], "tail": [3, 0, 1]})
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED" and error.context["current_mode"] == "EDIT"
        assert error.context["partial_operation_retained"] and not error.context["context_restored"]
    else:
        raise AssertionError("Canceled Edit Mode context was changed after revocation")
    finally:
        proof._authority = original
        grants[Permission.EDIT_ANIMATION.value] = True
    assert context_fired and recovery_rig.mode == "EDIT"
    assert tuple(recovery_rig.data.edit_bones["Retained Bone"].tail) == (0., 0., 0.)
    # Fixture operator simulates an explicit manual recovery after fresh consent;
    # the failed product request performs no cleanup after authority is revoked.
    bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.context.selected_objects):
        obj.select_set(False)
    for obj in selected:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    result = {"blender_version": bpy.app.version_string,
          "typed_create_rest_pose_constraints": True, "context_restored": True,
          "explicit_skin_closure": True, "existing_action_preserved": True,
          "rename_removal_propagation_refused": True, "live_stops": stops,
          "creation_retains_exact_ids": True, "revocation_retains_edit_context": True,
          "visual_reviewed": False, "durable_recovery_verified": False}
    if bundle is not None:
        # The pose Action is intentionally evaluated before saving and after
        # reopen, so persistent state compares the same animation frame.
        bpy.context.scene.frame_set(1)
        frozen = persistent(rig, skin)
        path = bundle / "rig-edit-boundaries.blend"
        runtime.dispatch("project.save", {"filepath": str(path)})
        manifest = {"file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "content": frozen,
                    "writer_process": os.environ["BRIDGE_TEST_PROCESS_TOKEN"]}
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result.update(project_saved=True, file_sha256=manifest["file_sha256"])
    blender_codex_bridge.unregister()
    return result


def reader(bundle):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    path = bundle / "rig-edit-boundaries.blend"
    assert manifest["writer_process"] != os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["file_sha256"]
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    bpy.context.scene.frame_set(1)
    actual = persistent(bpy.data.objects["Boundary Rig"], bpy.data.objects["Boundary Skin"])
    assert proof._close(json.loads(json.dumps(actual)), manifest["content"])
    return {"fresh_process_reopen_verified": True, "stored_rig_skin_animation_preserved": True,
            "visual_reviewed": False, "full_character_acceptance_verified": False}


def main():
    if "--bridge-phase" not in sys.argv:
        print("BLENDER_RIG_EDIT_BOUNDARIES_OK " + json.dumps(writer()), flush=True)
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    result = writer(args.bridge_bundle) if args.bridge_phase == "writer" else reader(args.bridge_bundle)
    result.update(phase=args.bridge_phase, process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid(), blender_version=bpy.app.version_string)
    print("BLENDER_RIG_EDIT_" + args.bridge_phase.upper() + "_OK " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
