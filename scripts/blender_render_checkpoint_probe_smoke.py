"""Tiny registered render admission/cache proof and explicit SYSTEM refusal."""

from __future__ import annotations

import json
import sys
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

from blender_codex_bridge import render_scope_profile  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import render as render_tools  # noqa: E402


def denied(callback, code):
    try:
        callback()
    except BridgeError as error:
        assert error.code == code, error.to_dict()
        result = error.to_dict()
        error.__traceback__ = error.__cause__ = error.__context__ = None
        return result
    raise AssertionError("Expected explicit render admission refusal")


def main(marker="BLENDER_RENDER_CHECKPOINT_PROBE_OK "):
    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
    try:
        runtime, scene = get_runtime(), bpy.context.scene
        calls, hook, frozen, snapshots = [], [None], [], []
        grants = {permission.value: True for permission in Permission}

        def provider():
            calls.append(True)
            if hook[0] is not None:
                callback, hook[0] = hook[0], None
                callback()
            return grants

        runtime.permissions = runtime.executor.permissions = PermissionManager(provider)
        runtime.registry.enable_toolset("render")
        manager = runtime.checkpoints
        original_snapshot, original_freeze = manager._snapshot, render_tools._freeze_plan

        def snapshot(*args, **kwargs):
            assert kwargs.get("guard") is not None
            snapshots.append(args[1])
            return original_snapshot(*args, **kwargs)

        def freeze(*args, **kwargs):
            before = len(calls)
            plan = original_freeze(*args, **kwargs)
            assert len(calls) == before, "Factory called permission providers"
            frozen.append(plan)
            return plan

        manager._snapshot, render_tools._freeze_plan = snapshot, freeze
        params = {"scene_name": scene.name, "width": 16, "height": 16, "samples": 1, "resolution_percentage": 100}
        before_marker = scene.get("_codex_bridge_undo_marker")
        original_reference = scene.original
        wm_count = bpy.context.window_manager.user_of_id(scene)

        def custom_controls(expected_code):
            records = []
            key = "bcb_owned_render_custom_scalar"
            owners = (scene, bpy.data.materials[0], bpy.context.window_manager)
            variants = (("bool_to_int", False, 0), ("int_to_float", 0, 0.0), ("signed_zero", 0.0, -0.0), ("nested_signed_zero", {"nested": array("d", [0.0])}, {"nested": array("d", [-0.0])}), ("array_float32_to_float64", array("f", [1.0]), array("d", [1.0])), ("empty_group_to_empty_array", {}, array("i")))

            def expected_native(value):
                if type(value) is dict:
                    return "native_group", tuple((name, expected_native(item)) for name, item in value.items())
                if type(value) is array:
                    return "native_array", value.typecode, tuple(expected_native(item) for item in value)
                return render_scope_profile.value(value, custom_scalars=True)

            def assert_native_storage(stored, requested):
                if type(requested) is dict:
                    assert type(stored) is render_scope_profile.IDPropertyGroup
                    assert list(stored.keys()) == list(requested)
                    for name, item in requested.items():
                        assert_native_storage(stored[name], item)
                elif type(requested) is array:
                    assert type(stored) is render_scope_profile.IDPropertyArray
                    assert type(stored.typecode) is str and stored.typecode == requested.typecode
                    assert len(stored) == len(requested)
                    for actual, desired in zip(stored, requested, strict=True):
                        assert_native_storage(actual, desired)
                else:
                    assert type(stored) is type(requested)
                    assert stored.hex() == requested.hex() if type(requested) is float else stored == requested

            for owner in owners:
                assert key not in owner
                for label, initial, changed in variants:
                    owner[key] = initial
                    assert_native_storage(owner[key], initial)
                    before = scene.render.resolution_x, scene.render.resolution_y
                    native_before = len(snapshots)
                    original_projection = render_scope_profile.value(owner[key], custom_scalars=True)

                    def interfere(owner=owner, changed=changed):
                        del owner[key]
                        owner[key] = changed

                    hook[0] = interfere
                    try:
                        error = denied(lambda: runtime.dispatch("render.configure", {**params, "width": 24}), expected_code)
                        observed = render_scope_profile.value(owner[key], custom_scalars=True)
                        assert_native_storage(owner[key], changed)
                        assert observed == expected_native(changed)
                        assert observed != original_projection
                        assert (scene.render.resolution_x, scene.render.resolution_y) == before
                        assert len(snapshots) == native_before
                        records.append({"owner": owner.bl_rna.identifier, "case": label, "refusal": error["code"], "newer_custom_value_preserved": True, "native_checkpoint_calls": 0, "owned_render_writes": 0, "custom_type_or_sign_change_compared": expected_code == "OPERATION_FAILED"})
                    finally:
                        hook[0] = None
                        del owner[key]
            return records

        if bpy.app.build_hash == b"d13f752e3b9c":
            before = scene.render.resolution_x, scene.render.resolution_y, scene.render.filepath
            refusals = []
            for method, arguments in (("render.configure", params), ("render.execute", {"scene_name": scene.name, "width": 16, "height": 16})):
                error = denied(lambda method=method, arguments=arguments: runtime.dispatch(method, arguments), "NOT_IMPLEMENTED")
                assert "SYSTEM storage" in error["message"]
                refusals.append(error)
            custom_records = custom_controls("NOT_IMPLEMENTED")
            grants[Permission.EDIT_RENDER.value] = False
            denial = denied(lambda: runtime.dispatch("render.configure", params), "PERMISSION_DENIED")
            assert snapshots == [] and frozen == []
            assert scene.get("_codex_bridge_undo_marker") == before_marker
            assert before == (scene.render.resolution_x, scene.render.resolution_y, scene.render.filepath)
            evidence = {"system_storage_refused": True, "refusals": refusals, "custom_scalar_controls": custom_records, "authorization_denial_precedes_factory_diagnostic": denial["code"] == "PERMISSION_DENIED", "native_checkpoint_calls": 0, "render_owned_writes": 0, "runtime_getter_fallback_used": False, "complete_authored_preservation_claimed": False}
        else:
            configured = runtime.dispatch("render.configure", params)
            assert configured["verified"] and configured["operation"]["undo_boundary_finalized"]
            assert len(frozen) == 1 and len(snapshots) == 2
            assert frozen[0].boundary.published
            assert scene.original == original_reference
            assert bpy.context.window_manager.user_of_id(scene) == wm_count
            assert scene.user_of_id(scene) == 1
            assert scene.tool_settings.particle_edit.object == bpy.context.view_layer.objects.active
            custom_records = custom_controls("OPERATION_FAILED")
            frozen_before_interference = len(frozen)
            native_before = len(snapshots)
            hook[0] = lambda: setattr(scene.render, "resolution_x", 17)
            interference = denied(lambda: runtime.dispatch("render.configure", {**params, "width": 24}), "OPERATION_FAILED")
            assert scene.render.resolution_x == 17 and len(snapshots) == native_before
            assert len(frozen) == frozen_before_interference + 1
            scene.render.resolution_x = 16  # Explicit fixture manual restoration.
            rendered = runtime.dispatch("render.execute", {"scene_name": scene.name, "width": 16, "height": 16})
            assert rendered["verified"] and Path(rendered["filepath"]).is_file()
            assert len(frozen) == frozen_before_interference + 2 and len(snapshots) == native_before
            assert scene.original == original_reference
            assert bpy.context.window_manager.user_of_id(scene) == wm_count
            evidence = {"configured": configured, "rendered": rendered, "custom_scalar_controls": custom_records, "factory_ledger_reused_through_handler_and_after_checkpoint": True, "entry_provider_authored_drift_refused_before_checkpoint": interference, "scene_original_preserved": True, "window_manager_reference_count_preserved": True, "native_checkpoint_calls": len(snapshots), "factory_capture_called_providers": False}
        print(marker + json.dumps({"version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(), "shared_registry_admission_wired": True, "windows_qualified": False, **evidence}))
    finally:
        bpy.ops.preferences.addon_disable(module="blender_codex_bridge")


if __name__ == "__main__":
    main()
