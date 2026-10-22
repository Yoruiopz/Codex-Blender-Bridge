"""Typed Action lifecycle, measured recovery and fresh-process retention fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _animation_scope as scope  # noqa: E402
from blender_codex_bridge.tools import animation_lifecycle as lifecycle  # noqa: E402
from native_fixture_save import serialize_owned_fixture  # noqa: E402


def setup():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    runtime.registry.enable_toolset("animation")
    return runtime, grants


def deny(runtime, code, method, params):
    try:
        runtime.dispatch(method, params)
    except BridgeError as error:
        assert error.code == code, (method, error)
        return error
    raise AssertionError("Expected refusal: " + method)


def object_new(name):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def populate(action, slot, values):
    bag = action.layers[0].strips[0].channelbag(slot, ensure=True)
    curve = bag.fcurves.new(data_path="location", index=0)
    for frame, value in zip((1., 11.), values, strict=True):
        point = curve.keyframe_points.insert(frame, value)
        point.interpolation = "LINEAR"
    curve.update()


def samples(actor, protected):
    values = []
    for frame in (1, 6, 11):
        bpy.context.scene.frame_set(frame)
        values.append([actor.location.x, protected.location.x])
    return values


def writer(bundle):
    runtime, grants = setup()
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    actor, protected = object_new("Lifecycle Actor"), object_new("Lifecycle Protected")
    call = runtime.dispatch
    created = call("animation.action_create", {"action_name": "Lifecycle Source", "slot_name": "Actor", "keep_on_save": False})
    source = bpy.data.actions[created["action"]]
    actor_slot = source.slots[0]
    protected_slot = source.slots.new("OBJECT", "Protected")
    populate(source, actor_slot, (0., 10.))
    populate(source, protected_slot, (50., 60.))
    for obj, slot in ((actor, actor_slot), (protected, protected_slot)):
        call("animation.action_bind", {"object_name": obj.name, "action_name": source.name, "expected_action_name": None,
             "slot_identifier": slot.identifier, "affected_objects": []})
    baseline = samples(actor, protected)
    assert baseline == [[0., 50.], [5., 55.], [10., 60.]], baseline
    frozen_source = scope.action_content(source)
    source_key, protected_binding = scope.action_token(source), scope.binding(protected)
    target = call("animation.action_create", {"action_name": "Lifecycle Revision", "slot_name": "Actor", "keep_on_save": True})
    revision = bpy.data.actions[target["action"]]
    populate(revision, revision.slots[0], (20., 40.))
    request = {"object_name": actor.name, "action_name": revision.name, "expected_action_name": source.name,
               "slot_identifier": revision.slots[0].identifier, "affected_objects": []}
    grants[Permission.EDIT_ANIMATION.value] = False
    deny(runtime, "PERMISSION_DENIED", "animation.action_bind", request)
    grants[Permission.EDIT_ANIMATION.value] = True
    deny(runtime, "INVALID_ARGUMENT", "animation.action_bind", {**request, "slot_identifier": "OBMissing"})
    assert scope.binding(protected) == protected_binding and actor.animation_data.action == source

    # Inject a known post-assignment failure. Compensation is permitted only
    # while exact IDs/content/consumers/live consent still match this operation.
    original_check, injected = lifecycle._Binding.check, False

    def fail_once(boundary):
        nonlocal injected
        result = original_check(boundary)
        if not injected and actor.animation_data.action == revision:
            injected = True
            raise RuntimeError("Injected Action post-assignment failure")
        return result

    lifecycle._Binding.check = fail_once
    try:
        error = deny(runtime, "OPERATION_FAILED", "animation.action_bind", request)
        assert injected and error.context["rollback_verified"] and not error.context["possible_mutation"], error.context
    finally:
        lifecycle._Binding.check = original_check
    assert actor.animation_data.action == source and actor.animation_data.action_slot == actor_slot

    # Revocation after the first native assignment must retain that observed
    # partial result, with no untracked compensating edit after consent is lost.
    revoked = False

    def revoke_after_assignment(boundary):
        nonlocal revoked
        if not revoked and actor.animation_data.action == revision:
            grants[Permission.EDIT_ANIMATION.value] = False
            revoked = True
        return original_check(boundary)

    lifecycle._Binding.check = revoke_after_assignment
    try:
        error = deny(runtime, "PERMISSION_DENIED", "animation.action_bind", request)
        assert revoked and not error.context["rollback_verified"] and error.context["possible_mutation"]
        assert actor.animation_data.action == revision
    finally:
        lifecycle._Binding.check = original_check
        grants[Permission.EDIT_ANIMATION.value] = True
    call("animation.action_bind", {"object_name": actor.name, "action_name": source.name, "expected_action_name": revision.name,
         "slot_identifier": actor_slot.identifier, "affected_objects": []})
    assert samples(actor, protected) == baseline

    # Metadata applies to the shared ID, so explicit shared acknowledgement is
    # mandatory. Source keys/slots and protected binding survive its rename.
    deny(runtime, "INVALID_ARGUMENT", "animation.action_update", {"action_name": source.name, "new_name": "Lifecycle Shared Source"})
    call("animation.action_update", {"action_name": source.name, "new_name": "Lifecycle Shared Source", "allow_shared": True})
    assert scope.action_token(source) == source_key and scope.action_content(source) == frozen_source
    assert scope.binding(protected) == protected_binding
    call("animation.action_bind", {**request, "expected_action_name": source.name})
    revised = samples(actor, protected)
    assert revised == [[20., 50.], [30., 55.], [40., 60.]], revised
    assert scope.action_content(source) == frozen_source

    call("animation.action_create", {"action_name": "Lifecycle Retained", "slot_name": "Keeper", "keep_on_save": True})
    call("animation.action_create", {"action_name": "Lifecycle Session Only", "slot_name": "Orphan", "keep_on_save": False})
    call("animation.action_create", {"action_name": "Lifecycle Removed", "slot_name": "Removed", "keep_on_save": False})
    deny(runtime, "INVALID_ARGUMENT", "animation.action_remove", {"action_name": revision.name, "confirm": True})
    grants[Permission.DELETE_OBJECTS.value] = False
    deny(runtime, "PERMISSION_DENIED", "animation.action_update", {"action_name": "Lifecycle Retained", "keep_on_save": False})
    deny(runtime, "PERMISSION_DENIED", "animation.action_remove", {"action_name": "Lifecycle Removed", "confirm": True})
    grants[Permission.DELETE_OBJECTS.value] = True
    call("animation.action_remove", {"action_name": "Lifecycle Removed", "confirm": True})
    assert bpy.data.actions.get("Lifecycle Removed") is None
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active

    # Public saving is refused; fixture-only serialization tests native retention.
    path = bundle / "action-lifecycle.blend"
    grants[Permission.SAVE_PROJECT.value] = False
    deny(runtime, "PERMISSION_DENIED", "project.save", {"filepath": str(path)})
    assert not path.exists()
    grants[Permission.SAVE_PROJECT.value] = True
    fixture_save = serialize_owned_fixture(runtime, path)
    manifest = {"sampled_motion": revised, "source_content_sha256": scope.digest(scope.action_content(source)),
                "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "writer_process": os.environ["BRIDGE_TEST_PROCESS_TOKEN"]}
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {**manifest, **fixture_save, "permission_denials_verified": True, "invalid_slot_rejected": True,
            "identity_preserving_compensation_verified": True, "late_revocation_retains_partial_result": True,
            "protected_action_preserved": True, "project_saved": True, "full_character_acceptance_verified": False}


def reader(bundle):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    path = bundle / "action-lifecycle.blend"
    assert manifest["writer_process"] != os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["file_sha256"]
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    runtime, _ = setup()
    actor, protected = bpy.data.objects["Lifecycle Actor"], bpy.data.objects["Lifecycle Protected"]
    assert samples(actor, protected) == manifest["sampled_motion"]
    retained = runtime.dispatch("animation.action_inspect", {"action_name": "Lifecycle Retained"})
    assert retained["retention"] == "FAKE_USER" and retained["real_users"] == 0
    assert bpy.data.actions.get("Lifecycle Session Only") is None
    assert bpy.data.actions.get("Lifecycle Removed") is None
    assert scope.digest(scope.action_content(protected.animation_data.action)) == manifest["source_content_sha256"]
    return {"fresh_process_reopen_verified": True, "sampled_motion": manifest["sampled_motion"],
            "retained_unbound_action_present": True, "session_only_action_absent": True,
            "removed_action_absent": True, "protected_content_preserved": True,
            "full_character_acceptance_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    result = writer(args.bridge_bundle) if args.bridge_phase == "writer" else reader(args.bridge_bundle)
    result.update(phase=args.bridge_phase, process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
                  process_id=os.getpid(), blender_version=bpy.app.version_string)
    print("BLENDER_ACTION_LIFECYCLE_" + args.bridge_phase.upper() + "_OK " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
