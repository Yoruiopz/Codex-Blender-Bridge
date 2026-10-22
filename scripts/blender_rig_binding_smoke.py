"""Typed bounded binding and measured exact-weight recovery; isolated runner only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
sys.path.insert(0, str(ROOT / "scripts"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _rig_binding as binding  # noqa: E402
from blender_rig_binding_probe_smoke import fixture  # noqa: E402
from blender_rig_binding_probe_smoke import state as raw_state  # noqa: E402


def state(mesh):
    result = raw_state(mesh)
    # Sparse deform storage order is neither group identity nor a weight value.
    # Compare every exact (group index, float32 weight) pair independently.
    result["weights"] = [sorted(memberships) for memberships in result["weights"]]
    return result


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}

    def manager(source=None):
        runtime.permissions = runtime.executor.permissions = PermissionManager(source or (lambda: grants))

    manager()
    runtime.registry.enable_toolset("rigging")
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active

    def call(rig, mesh, method="AUTOMATIC", **params):
        return runtime.dispatch("rig.bind_mesh", {"mesh_object": mesh.name, "armature_object": rig.name, "method": method, **params})

    rig, mesh, modifier = fixture()
    initial = state(mesh)
    result = call(rig, mesh)
    assert result["verified"] and result["preservation"]["unrelated_memberships"]
    assert result["weight_coverage"]["positive_deform_coverage"]
    assert not result["weight_coverage"]["normalization_certified"]
    assert mesh.parent == rig and mesh.modifiers[0] == modifier
    assert state(mesh)["weights"] != initial["weights"]

    # Exact restoration includes every original membership, identity, lock,
    # parent/matrix and modifier. These receipts are not durable backups.
    recovered = []
    original = binding._weight_shape
    for error_kind in (RuntimeError, MemoryError):
        rig2, mesh2, _ = fixture()
        before = state(mesh2)

        def fail(*args, error_kind=error_kind, **kwargs):
            original(*args, **kwargs)
            raise error_kind("injected after verified native output")

        binding._weight_shape = fail
        try:
            call(rig2, mesh2)
        except BridgeError as error:
            assert error.context["rollback_verified"] and not error.context["possible_mutation"], error.to_dict()
        else:
            raise AssertionError("missing injected failure")
        finally:
            binding._weight_shape = original
        assert state(mesh2) == before
        recovered.append(error_kind.__name__)

    # Empty-group binding works with/without parenting and allocates one exact
    # modifier, preserving all existing weights and the physical context.
    for parent in (False, True):
        empty_rig, empty_mesh, old_modifier = fixture()
        empty_mesh.modifiers.remove(old_modifier)
        weights = state(empty_mesh)["weights"]
        response = call(empty_rig, empty_mesh, "EMPTY_GROUPS", parent=parent)
        assert response["verified"] and len(empty_mesh.modifiers) == 1
        assert empty_mesh.modifiers[0].object == empty_rig
        assert (empty_mesh.parent == empty_rig) == parent
        assert state(empty_mesh)["weights"] == weights

    # The other two explicit roots are not silently inferred as foreign scope.
    # Additional consumers must be named exactly before the first write.
    scope_rig, scope_mesh, _ = fixture()
    protected = bpy.data.objects.new("Binding Protected Dependent", None)
    bpy.context.scene.collection.objects.link(protected)
    protected.parent = scope_rig
    before = state(scope_mesh)
    try:
        call(scope_rig, scope_mesh, "EMPTY_GROUPS")
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    else:
        raise AssertionError("implicit dependent scope was accepted")
    assert state(scope_mesh) == before
    call(scope_rig, scope_mesh, "EMPTY_GROUPS", affected_objects=[protected.name])
    assert protected.parent == scope_rig

    # The new mesh-edit grant is authoritative inside Blender.
    denied_rig, denied_mesh, _ = fixture()
    before = state(denied_mesh)
    grants[Permission.EDIT_MESH.value] = False
    try:
        call(denied_rig, denied_mesh)
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    else:
        raise AssertionError("mesh-edit permission was bypassed")
    finally:
        grants[Permission.EDIT_MESH.value] = True
    assert state(denied_mesh) == before
    denied_mesh.vertex_groups["Upper"].lock_weight = True
    before = state(denied_mesh)
    try:
        call(denied_rig, denied_mesh)
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    else:
        raise AssertionError("locked deform weights were replaced")
    assert state(denied_mesh) == before

    retained = []
    for stop in ("permission", "toolset", "pause", "emergency", "cancel", "disconnect", "manual_weight", "manual_active"):
        stopped_rig, stopped_mesh, _ = fixture()
        fired = []

        def inject(stop=stop, fired=fired, stopped_mesh=stopped_mesh, stopped_rig=stopped_rig):
            if fired or stopped_mesh.parent != stopped_rig:
                return
            fired.append(True)
            if stop == "permission":
                grants[Permission.EDIT_MESH.value] = False
            elif stop == "toolset":
                runtime.registry.disable_toolset("rigging")
            elif stop == "pause":
                runtime.state.set_paused(True)
            elif stop == "emergency":
                runtime.state.set_emergency_stopped(True)
            elif stop in {"cancel", "disconnect"}:
                raise BridgeError("TIMEOUT", "Injected canceled/disconnected caller")
            elif stop == "manual_weight":
                stopped_mesh.vertex_groups["ProtectedDetail"].add([0], .789, "REPLACE")
            else:
                bpy.context.view_layer.objects.active = stopped_rig

        def provider(stop=stop, inject=inject):
            if stop not in {"cancel", "disconnect"}:
                inject()
            return grants

        manager(provider)
        request = Request(id="binding-stop-"+stop, method="rig.bind_mesh", params={
            "mesh_object": stopped_mesh.name, "armature_object": stopped_rig.name, "method": "AUTOMATIC"})
        try:
            response = runtime.executor.execute_request(request, check_cancelled=inject if stop in {"cancel", "disconnect"} else None)
            assert not response.ok and response.error, response.to_dict()
            details = response.error["context"]
            assert details["possible_mutation"] and not details["rollback_verified"], response.to_dict()
            assert fired and stopped_mesh.parent == stopped_rig
            assert stopped_mesh.vertex_groups.get("Lower") is not None
            if stop == "manual_weight":
                assert abs(stopped_mesh.vertex_groups["ProtectedDetail"].weight(0)-.789) < 1e-6
            if stop == "manual_active":
                assert bpy.context.view_layer.objects.active == stopped_rig
        finally:
            manager()
            runtime.registry.enable_toolset("rigging")
            grants[Permission.EDIT_MESH.value] = True
            runtime.state.set_paused(False)
            runtime.state.set_emergency_stopped(False)
            bpy.context.view_layer.objects.active = active
        retained.append(stop)
    assert list(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
    print("BLENDER_RIG_BINDING_OK " + json.dumps({"blender_version": bpy.app.version_string,
          "typed_automatic_binding": True, "typed_empty_group_binding": True,
          "existing_membership_identity_restored": True, "recovered_failures": recovered,
          "protected_locked_unrelated_memberships": True, "explicit_consumer_scope": True,
          "live_stops_retain_observed_native_output": retained,
          "native_blocking_seconds": result["native_blocking_seconds"],
          "weight_coverage": result["weight_coverage"], "product_workflow_verified": False,
          "visual_reviewed": False, "durable_recovery_verified": False}), flush=True)
    blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
