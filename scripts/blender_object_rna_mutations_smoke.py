"""Disposable object RNA boundaries and measured native application receipts."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _object_rna_mutation as proof  # noqa: E402


def main():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    for toolset in ("objects", "modifiers", "constraints"):
        runtime.registry.enable_toolset(toolset)
    scene = bpy.context.scene
    def empty(name):
        obj = bpy.data.objects.new(name, None)
        scene.collection.objects.link(obj)
        return obj
    owner, source, protected = (empty(name) for name in ("RNA Owner", "RNA Source", "RNA Protected"))
    protected.location.x = 41.
    selection = tuple(obj.as_pointer() for obj in bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    def call(method, obj=owner, **params):
        return runtime.dispatch(method, {"object_name": obj.name, **params})
    call("transform.set", location=[1., 2., 3.], rotation=[.1, .2, .3], scale=[1., 2., 1.])
    assert tuple(owner.location) == (1., 2., 3.)
    call("transform.translate", offset=[1., 0., 0.], space="WORLD")
    assert math.isclose(owner.location.x, 2., abs_tol=1e-6)
    call("transform.rotate", rotation=[0., 0., .1], space="LOCAL")
    call("transform.scale", factor=2.)
    for mode in ("QUATERNION", "ZYX", "AXIS_ANGLE", "XYZ"):
        call("transform.set", rotation_mode=mode, location=list(owner.location))
        assert owner.rotation_mode == mode
    call("constraint.add", constraint_type="COPY_LOCATION", constraint_name="Owned Copy", settings={"target": source.name, "influence": .5})
    call("constraint.set", constraint_name="Owned Copy", settings={"influence": .25, "mute": True})
    call("constraint.add", constraint_type="LIMIT_LOCATION", constraint_name="Sibling Limit", settings={"use_min_x": True})
    call("constraint.remove", constraint_name="Sibling Limit")
    call("constraint.remove", constraint_name="Owned Copy")
    mesh = bpy.data.meshes.new("RNA Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    target = bpy.data.objects.new("RNA Mesh Owner", mesh)
    scene.collection.objects.link(target)
    activation_probe = []
    for removed_index in range(3):
        native = [target.modifiers.new(f"Activation Probe {i}", kind) for i, kind in enumerate(("BEVEL", "SOLIDIFY", "TRIANGULATE"))]
        native[removed_index].is_active = True
        before_active = [item.is_active for item in native]
        target.modifiers.remove(native[removed_index])
        after_active = [item.is_active for item in target.modifiers]
        expected_active = [index == min(removed_index, 1) for index in range(2)]
        assert after_active == expected_active
        activation_probe.append({"removed": removed_index, "before": before_active, "after": after_active})
        for item in list(target.modifiers):
            target.modifiers.remove(item)
    print("RNA_NATIVE_ACTIVATION_PROBE " + json.dumps(activation_probe), flush=True)
    call("modifier.add", target, modifier_type="BEVEL", modifier_name="Owned Bevel", settings={"width": .1, "segments": 2})
    call("modifier.set", target, modifier_name="Owned Bevel", settings={"width": .2, "segments": 3})
    native_before = proof.component_state(target.modifiers[0])
    original_authority = proof.Boundary._authority
    stops = []
    for stop in ("permission", "pause", "emergency", "cancel"):
        call("modifier.set", target, modifier_name="Owned Bevel", settings={"width": .2, "segments": 3})
        fired = []
        def after_field(self, *, stop=stop, fired=fired):
            original_authority(self)
            if self.obj != target or not math.isclose(target.modifiers[0].width, .4, abs_tol=1e-6):
                return
            fired.append(True)
            if stop == "permission":
                grants[Permission.TRANSFORM_OBJECTS.value] = False
            elif stop == "pause":
                runtime.state.set_paused(True)
            elif stop == "emergency":
                runtime.state.set_emergency_stopped(True)
            else:
                raise BridgeError("TIMEOUT", "Injected caller cancellation")
            original_authority(self)
        proof.Boundary._authority = after_field
        try:
            call("modifier.set", target, modifier_name="Owned Bevel", settings={"width": .4, "segments": 5})
        except BridgeError as error:
            assert error.context["possible_mutation"] and not error.context["rollback_verified"]
        else:
            raise AssertionError("Live stop was ignored")
        finally:
            proof.Boundary._authority = original_authority
            grants[Permission.TRANSFORM_OBJECTS.value] = True
            runtime.state.set_paused(False)
            runtime.state.set_emergency_stopped(False)
        assert fired and target.modifiers[0].segments == 3
        assert math.isclose(target.modifiers[0].width, .4, abs_tol=1e-6)
        stops.append(stop)
    call("modifier.set", target, modifier_name="Owned Bevel", settings={"width": .2, "segments": 3})
    assert proof.component_state(target.modifiers[0]) == native_before
    fired = []
    def one_shot(self):
        original_authority(self)
        if self.obj == target and not fired and math.isclose(target.modifiers[0].width, .4, abs_tol=1e-6):
            fired.append(True)
            raise RuntimeError("Injected postwrite failure")
    proof.Boundary._authority = one_shot
    try:
        call("modifier.set", target, modifier_name="Owned Bevel", settings={"width": .4, "segments": 5})
    except BridgeError as error:
        assert error.context["rollback_verified"] and not error.context["possible_mutation"]
    else:
        raise AssertionError("Missing injected failure")
    finally:
        proof.Boundary._authority = original_authority
    assert proof.component_state(target.modifiers[0]) == native_before
    adversarial = []
    for change in ("foreign_component", "protected_vertex", "exact_replacement"):
        call("modifier.set", target, modifier_name="Owned Bevel", settings={"width": .2, "segments": 3})
        fired = []
        retained = []
        def manual(self, *, change=change, fired=fired, retained=retained):
            original_authority(self)
            if self.obj != target or fired:
                return
            current = target.modifiers.get("Owned Bevel")
            if change != "exact_replacement" and not math.isclose(current.width, .4, abs_tol=1e-6):
                return
            fired.append(True)
            if change == "foreign_component":
                target.modifiers.new("Manual Component", "SOLIDIFY")
            elif change == "protected_vertex":
                target.data.vertices[0].co.z = 8.
            else:
                target.modifiers.remove(current)
                replacement = target.modifiers.new("Owned Bevel", "BEVEL")
                replacement.width, replacement.segments = .8, 9
            retained.append((proof._components(target, "modifiers"), tuple(tuple(vertex.co) for vertex in mesh.vertices)))
        proof.Boundary._authority = manual
        try:
            call("modifier.set", target, modifier_name="Owned Bevel", settings={"width": .4, "segments": 5})
        except BridgeError as error:
            assert not error.context["rollback_verified"]
        else:
            raise AssertionError("Manual interleaving was adopted")
        finally:
            proof.Boundary._authority = original_authority
        assert fired and retained[0] == (proof._components(target, "modifiers"), tuple(tuple(vertex.co) for vertex in mesh.vertices))
        adversarial.append(change)
        if change == "foreign_component":
            call("modifier.remove", target, modifier_name="Manual Component")
        elif change == "protected_vertex":
            mesh.vertices[0].co.z = 0.
    mode_before = proof._channels(owner)
    fired = []
    def mode_failure(self):
        original_authority(self)
        if self.obj == owner and owner.rotation_mode == "QUATERNION" and not fired:
            fired.append(True)
            raise RuntimeError("One-shot rotation-mode alias failure")
    proof.Boundary._authority = mode_failure
    try:
        call("transform.set", rotation_mode="QUATERNION", location=list(owner.location))
    except BridgeError as error:
        assert error.context["rollback_verified"]
    else:
        raise AssertionError("Missing mode failure")
    finally:
        proof.Boundary._authority = original_authority
    assert fired and proof._channels(owner) == mode_before
    call("modifier.remove", target, modifier_name="Owned Bevel")
    call("modifier.add", target, modifier_type="TRIANGULATE", modifier_name="Apply Me")
    modifier_applied = call("modifier.apply", target, modifier_name="Apply Me")
    target.scale = (2., 3., 1.)
    transform_applied = call("transform.apply", target, scale=True)
    assert tuple(target.scale) == (1., 1., 1.) and not target.modifiers
    assert protected.location.x == 41.
    assert tuple(obj.as_pointer() for obj in bpy.context.selected_objects) == selection
    assert bpy.context.view_layer.objects.active == active
    print("BLENDER_CODEX_OBJECT_RNA_MUTATIONS_OK " + json.dumps({"blender": bpy.app.version_string, "stops": stops, "measured_rna_recovery": True,
          "native_apply_context_preserved": True, "protected_object_preserved": True, "windows_qualified": False,
          "native_apply_rollback_claimed": False, "manual_interleavings": adversarial, "activation_probe": activation_probe, "rotation_mode_alias_recovery": True,
          "native_blocking_seconds": {"modifier": modifier_applied["native_blocking_seconds"], "transform": transform_applied["native_blocking_seconds"]}}, sort_keys=True))
    blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
