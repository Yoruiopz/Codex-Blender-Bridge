"""Disposable two-process artist-plan persistence fixture; run through native runner."""

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
from blender_codex_bridge.task_plans import SCENE_PROPERTY  # noqa: E402
from blender_codex_bridge.tools import task_plan  # noqa: E402
from native_fixture_save import serialize_owned_fixture  # noqa: E402


def setup():
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: False for permission in Permission}
    grants[Permission.INSPECT_SCENE.value] = True
    manager = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("objects")
    return runtime, grants


def deny(runtime, code, method, **params):
    try:
        runtime.dispatch(method, params)
    except BridgeError as error:
        assert error.code == code, error.to_dict()
    else:
        raise AssertionError(f"Expected {method} to fail with {code}")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finish(phase, evidence):
    print(f"BLENDER_TASK_PLANS_{phase.upper()}_OK " + json.dumps({
        **evidence, "phase": phase, "process_id": os.getpid(),
        "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
        "blender_version": bpy.app.version_string,
        "protected_scope_enforced": False, "native_undo_verified": False,
        "artistic_quality_accepted": False, "release_readiness": "NOT_ASSESSED",
    }), flush=True)


def persistence_faults(runtime, grants, revision):
    """Probe actual Scene IDProperties after the final permission callback."""
    scene = bpy.context.scene
    source = runtime.permissions._source
    results = []
    try:
        for stage in ("before_write", "after_write"):
            for fault in ("pause", "stop", "consent", "manual_property"):
                scene[SCENE_PROPERTY] = "owned prior text"
                calls = 0
                fired = False

                def provider(stage=stage, fault=fault):
                    nonlocal calls, fired
                    calls += 1
                    trigger = stage == "before_write" or scene[SCENE_PROPERTY] != "owned prior text"
                    if not fired and trigger:
                        fired = True
                        if fault == "pause":
                            runtime.state.set_paused(True)
                        elif fault == "stop":
                            runtime.state.set_emergency_stopped(True)
                        elif fault == "consent":
                            grants[Permission.EDIT_SCENE.value] = False
                        else:
                            scene[SCENE_PROPERTY] = "newer manual text"
                    return grants

                runtime.permissions._source = provider
                try:
                    task_plan.persist_plan(runtime.executor.context, {"confirm": True, "expected_revision": revision})
                except BridgeError as error:
                    assert fired, (stage, fault, calls, error.to_dict())
                    assert error.code == {"pause": "AGENT_PAUSED", "stop": "EMERGENCY_STOPPED",
                                          "consent": "PERMISSION_DENIED", "manual_property": "INVALID_ARGUMENT"}[fault]
                    if stage == "after_write":
                        assert error.context["possible_mutation"] and not error.context["rollback_verified"], error.to_dict()
                        assert error.context["recovery"] == "explicit_recovery_required"
                    current = scene[SCENE_PROPERTY]
                    if fault == "manual_property":
                        assert current == "newer manual text"
                    elif stage == "before_write":
                        assert current == "owned prior text"
                    else:
                        assert json.loads(current)["revision"] == revision
                    results.append({"stage": stage, "fault": fault, "code": error.code,
                                    "newer_property_retained": fault == "manual_property",
                                    "illegal_compensation": False})
                else:
                    raise AssertionError((stage, fault, "persistence should have stopped"))
                finally:
                    runtime.permissions._source = source
                    grants[Permission.EDIT_SCENE.value] = True
                    runtime.state.set_emergency_stopped(False)
                    runtime.state.set_paused(False)
        del scene[SCENE_PROPERTY]
    finally:
        runtime.permissions._source = source
    return results


def writer(bundle):
    runtime, grants = setup()
    call = runtime.dispatch
    protected = bpy.data.objects["Cube"]
    before = tuple(protected.location)
    selected = [obj.name for obj in bpy.context.selected_objects]
    active = bpy.context.view_layer.objects.active.name
    created = call("task.plan.set", {
        "goal": "Create a variant while preserving Cube",
        "steps": [{"id": "inspect", "description": "Inspect protected object"}, {"id": "variant", "description": "Create and compare variant"}],
        "protected_objects": [protected.name],
    })
    assert created["plan"]["revision"] == 1 and not created["protected_scope_enforced"]
    original_id = created["plan"]["plan_id"]
    baseline = call("task.plan.capture", {"fields": ["transforms", "hierarchy"]})
    assert baseline["baseline"]["coverage_complete"], baseline
    grants[Permission.TRANSFORM_OBJECTS.value] = True
    variant = call("object.create", {"object_type": "EMPTY", "name": "Plan Variant"})
    call("transform.set", {"object_name": variant["object"], "location": [2., 3., 4.]})
    assert call("task.plan.compare")["evidence"]["status"] == "unchanged_within_scope"
    # Advisory scope does not silently claim global mutator enforcement. A typed
    # protected edit is permitted and independently detected by comparison.
    call("transform.set", {"object_name": protected.name, "location": [before[0] + 1., before[1], before[2]]})
    changed = call("task.plan.compare")["evidence"]
    assert changed["status"] == "changed" and changed["coverage_complete"], changed
    call("transform.set", {"object_name": protected.name, "location": list(before)})
    assert call("task.plan.compare")["evidence"]["status"] == "unchanged_within_scope"
    updated = call("task.plan.update", {"step_id": "inspect", "status": "completed", "note": "Measured transforms and hierarchy", "expected_revision": 1})
    assert updated["plan"]["revision"] == 2
    deny(runtime, "INVALID_ARGUMENT", "task.plan.update", step_id="variant", status="completed", expected_revision=1)
    runtime.state.client_connected()
    runtime.state.client_disconnected()
    assert call("task.plan.inspect")["plan"]["plan_id"] == original_id
    assert SCENE_PROPERTY not in bpy.context.scene
    deny(runtime, "PERMISSION_DENIED", "task.plan.persist", confirm=True, expected_revision=2)
    grants[Permission.EDIT_SCENE.value] = True
    deny(runtime, "INVALID_ARGUMENT", "task.plan.persist", confirm=False, expected_revision=2)
    runtime.state.set_paused(True)
    deny(runtime, "AGENT_PAUSED", "task.plan.persist", confirm=True, expected_revision=2)
    runtime.state.set_paused(False)
    persistence_gates = persistence_faults(runtime, grants, 2)
    persisted = call("task.plan.persist", {"confirm": True, "expected_revision": 2})
    assert not persisted["project_saved"] and bpy.data.filepath == ""
    saved_plan = json.loads(bpy.context.scene[SCENE_PROPERTY])
    assert "snapshot_id" not in saved_plan
    assert selected == [obj.name for obj in bpy.context.selected_objects]
    assert bpy.context.view_layer.objects.active.name == active and bpy.context.mode == "OBJECT"
    project = bundle / "task-plan.blend"
    deny(runtime, "PERMISSION_DENIED", "project.save", filepath=str(project))
    assert not project.exists()
    grants[Permission.SAVE_PROJECT.value] = grants[Permission.ACCESS_EXTERNAL_FILES.value] = True
    fixture_save = serialize_owned_fixture(runtime, project)
    manifest = {"project": project.name, "sha256": digest(project), "plan": saved_plan, "protected_location": list(before)}
    (bundle / "task-plan-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    finish("writer", {"structured_plan_revision_verified": True, "advisory_change_detection_and_explicit_recovery_verified": True,
        "reconnect_retention_verified": True, "permission_pause_and_save_denial_verified": True,
        "persistence_provider_gates": persistence_gates,
        **fixture_save, "explicit_disposable_project_saved": True, "project_sha256": manifest["sha256"]})


def reader(bundle, manifest):
    project = bundle / manifest["project"]
    assert digest(project) == manifest["sha256"]
    bpy.ops.wm.open_mainfile(filepath=str(project))
    runtime, grants = setup()
    call = runtime.dispatch
    assert call("task.plan.inspect")["active"] is False
    assert not grants[Permission.EDIT_SCENE.value] and not grants[Permission.SAVE_PROJECT.value]
    loaded = call("task.plan.load")
    assert loaded["plan"] == manifest["plan"] and loaded["baseline"] is None
    deny(runtime, "INVALID_ARGUMENT", "task.plan.compare")
    assert tuple(bpy.data.objects["Cube"].location) == tuple(manifest["protected_location"])
    baseline = call("task.plan.capture", {"fields": ["transforms", "hierarchy"]})
    assert baseline["baseline"]["coverage_complete"]
    assert call("task.plan.compare")["evidence"]["status"] == "unchanged_within_scope"
    before = call("task.plan.inspect")
    original = bpy.context.scene[SCENE_PROPERTY]
    # Test-only corruption of owned disposable scene data exercises the public
    # parser; product tools never evaluate saved text or gain fresh-file consent.
    for raw in ("{", "[]", '{"schema_version":1,"schema_version":1}', "x" * 65537):
        bpy.context.scene[SCENE_PROPERTY] = raw
        deny(runtime, "INVALID_ARGUMENT", "task.plan.load", expected_revision=2)
        assert call("task.plan.inspect") == before
    bpy.context.scene[SCENE_PROPERTY] = original
    grants[Permission.INSPECT_SCENE.value] = False
    deny(runtime, "PERMISSION_DENIED", "task.plan.inspect")
    grants[Permission.INSPECT_SCENE.value] = True
    call("task.plan.clear", {"expected_revision": 2})
    assert bpy.context.scene[SCENE_PROPERTY] == original
    assert call("task.plan.load")["baseline"] is None
    runtime.state.reset()
    assert call("task.plan.inspect")["active"] is False
    assert digest(project) == manifest["sha256"]
    finish("reader", {"fresh_process_explicit_load_verified": True, "transient_baseline_not_restored": True,
        "malformed_saved_data_rejected_without_plan_change": True, "inspection_denial_verified": True,
        "runtime_reset_verified": True, "project_file_unchanged": True, "project_saved": False})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bundle = args.bridge_bundle.resolve(strict=True)
    try:
        if args.bridge_phase == "writer":
            writer(bundle)
        else:
            manifest = json.loads((bundle / "task-plan-manifest.json").read_text(encoding="utf-8"))
            reader(bundle, manifest)
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
