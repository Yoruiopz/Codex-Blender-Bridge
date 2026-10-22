"""Disposable object RNA boundaries and measured native application receipts."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _object_rna_mutation as proof  # noqa: E402
from blender_codex_bridge.tools import modifiers, transforms  # noqa: E402


def mesh_apply_authority(runtime, scene, grants):
    """Real grant checks and native poll interleavings before either operator."""
    denials, operator_calls = [], []
    initial_frame = scene.frame_current
    original_context = (tuple(obj.as_pointer() for obj in bpy.context.selected_objects), bpy.context.view_layer.objects.active, bpy.context.mode)
    for method, module, function, operator_name, toolset in (
        ("modifier.apply", modifiers, modifiers.apply_modifier, "modifier_apply", "modifiers"),
        ("transform.apply", transforms, transforms.apply_transform, "transform_apply", "objects"),
    ):
        native_operator = getattr(bpy.ops.object, operator_name)
        original_blender = module.require_blender
        for registered in (True, False):
            cases = ("initial_denial", "poll_permission", "poll_pause", "poll_emergency", "poll_context", "poll_owned", "poll_false")
            if registered:
                cases += ("poll_toolset",)
            for kind in cases:
                label = f"Apply {method} {registered} {kind}"
                mesh = bpy.data.meshes.new(label + " Mesh")
                mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
                obj = bpy.data.objects.new(label, mesh)
                scene.collection.objects.link(obj)
                params = {"object_name": obj.name}
                if method == "modifier.apply":
                    modifier = obj.modifiers.new("Owned Apply", "TRIANGULATE")
                    params["modifier_name"] = modifier.name
                else:
                    obj.scale = (2., 3., 1.)
                    params["scale"] = True
                before = proof._object_state(obj)
                polls, retained = [], []

                class PollOperator:
                    def poll(self, *, native_operator=native_operator, polls=polls, kind=kind, obj=obj, retained=retained, toolset=toolset):
                        assert native_operator.poll()
                        polls.append(True)
                        if kind == "poll_permission":
                            grants[Permission.EDIT_MESH.value] = False
                        elif kind == "poll_pause":
                            runtime.state.set_paused(True)
                        elif kind == "poll_emergency":
                            runtime.state.set_emergency_stopped(True)
                        elif kind == "poll_context":
                            scene.frame_current = initial_frame + 1
                        elif kind == "poll_owned":
                            obj.data.vertices[0].co.z = 9.
                            # Complete the manual edit's native update before
                            # recording it: automatic texspace bounds are lazy.
                            obj.data.update()
                            bpy.context.view_layer.update()
                            retained.append(proof._object_state(obj))
                        elif kind == "poll_toolset":
                            runtime.registry.disable_toolset(toolset)
                        return kind != "poll_false"

                    def __call__(self, *, method=method, kind=kind, native_operator=native_operator, **kwargs):
                        operator_calls.append((method, kind))
                        return native_operator(**kwargs)

                proxy = SimpleNamespace(data=bpy.data, context=bpy.context,
                                        ops=SimpleNamespace(object=SimpleNamespace(**{operator_name: PollOperator()})))
                module.require_blender = lambda proxy=proxy: proxy
                context = runtime.executor.context
                if not registered:
                    context.registry = None
                grants[Permission.EDIT_MESH.value] = kind != "initial_denial"
                try:
                    if registered:
                        runtime.dispatch(method, params)
                    else:
                        function(context, params)
                except BridgeError as error:
                    expected = {"initial_denial": "PERMISSION_DENIED", "poll_permission": "PERMISSION_DENIED",
                                "poll_pause": "AGENT_PAUSED", "poll_emergency": "EMERGENCY_STOPPED",
                                "poll_context": "INVALID_ARGUMENT", "poll_owned": "INVALID_ARGUMENT",
                                "poll_toolset": "TOOLSET_DISABLED", "poll_false": "BLENDER_CONTEXT_ERROR"}[kind]
                    assert error.code == expected, (label, error.code, expected)
                    if expected == "PERMISSION_DENIED":
                        assert error.context.get("missing_permissions", ["EDIT_MESH"]) == ["EDIT_MESH"]
                else:
                    raise AssertionError("Native application ignored revoked authority or changed scope: " + label)
                finally:
                    module.require_blender = original_blender
                    grants[Permission.EDIT_MESH.value] = True
                    runtime.state.set_paused(False)
                    runtime.state.set_emergency_stopped(False)
                    runtime.registry.enable_toolset(toolset)
                assert not operator_calls, operator_calls
                assert polls == ([] if kind == "initial_denial" else [True])
                observed = proof._object_state(obj)
                expected_state = retained[0] if retained else before
                def first_difference(left, right, path=()):
                    if isinstance(left, tuple) and isinstance(right, tuple) and len(left) == len(right):
                        for ordinal, (old, new) in enumerate(zip(left, right, strict=True)):
                            if old != new:
                                return first_difference(old, new, (*path, ordinal))
                    return {"path": path, "before": repr(left), "after": repr(right)}
                assert observed == expected_state, (label, first_difference(expected_state, observed))
                assert scene.frame_current == (initial_frame + 1 if kind == "poll_context" else initial_frame)
                assert (tuple(item.as_pointer() for item in bpy.context.selected_objects), bpy.context.view_layer.objects.active, bpy.context.mode) == original_context
                scene.frame_current = initial_frame
                denials.append({"method": method, "registered_context": registered, "fault": kind, "operator_calls": 0})
    return {"denials": denials, "complete_mesh_and_context_preserved": True, "manual_edit_retained": True,
            "registered_and_direct_contexts": True, "native_operator_calls": len(operator_calls)}


def boolean_material_boundaries(runtime, scene, grants):
    """Native source snapshots and exact shared-slot preserving application."""
    original_sources, original_native = proof.Boundary.sources, proof.Boundary.native_apply
    operator_entries, cases = [], []

    def cube(name, offset=0.):
        mesh = bpy.data.meshes.new(name + " Mesh")
        geometry = bmesh.new()
        try:
            bmesh.ops.create_cube(geometry, size=2.)
            geometry.to_mesh(mesh)
        finally:
            geometry.free()
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        obj.location.x = offset
        return obj

    def fixture(label):
        target, cutter = cube(label + " Target"), cube(label + " Cutter", 1.)
        target.data.materials.append(bpy.data.materials.new(label + " Target Finish"))
        cutter.data.materials.append(target.data.materials[0])
        runtime.dispatch("modifier.add", {"object_name": target.name, "modifier_type": "BOOLEAN", "modifier_name": "Owned Cut",
                         "settings": {"object": cutter.name, "operation": "DIFFERENCE", "solver": "EXACT"}})
        return target, cutter

    native_profiles = []
    for target_count, cutter_kind in ((0, "ZERO"), (1, "ZERO"), (2, "ZERO"), (1, "SAME"), (2, "SAME"), (1, "FOREIGN")):
        raw_target, raw_cutter = cube(f"Raw {target_count} {cutter_kind} Target"), cube(f"Raw {target_count} {cutter_kind} Cutter", 1.)
        for material_index in range(target_count):
            raw_target.data.materials.append(bpy.data.materials.new(f"Raw Material {target_count} {cutter_kind} {material_index}"))
        if cutter_kind == "SAME":
            raw_cutter.data.materials.append(raw_target.data.materials[0])
        elif cutter_kind == "FOREIGN":
            raw_cutter.data.materials.append(bpy.data.materials.new("Raw Foreign Cutter"))
        raw_modifier = raw_target.modifiers.new("Raw Native Boolean", "BOOLEAN")
        raw_modifier.object, raw_modifier.operation, raw_modifier.solver = raw_cutter, "DIFFERENCE", "EXACT"
        raw_modifier.material_mode = "INDEX"
        raw_before = [None if mat is None else (mat.name, mat.as_pointer()) for mat in raw_target.data.materials]
        with bpy.context.temp_override(object=raw_target, active_object=raw_target, selected_objects=[raw_target], selected_editable_objects=[raw_target]):
            raw_result = bpy.ops.object.modifier_apply(modifier=raw_modifier.name)
        profile = {"blender": bpy.app.version_string, "target_count": target_count, "cutter_kind": cutter_kind,
              "result": sorted(raw_result), "before": raw_before,
              "after": [None if mat is None else (mat.name, mat.as_pointer()) for mat in raw_target.data.materials],
              "face_indices": [int(poly.material_index) for poly in raw_target.data.polygons]}
        native_profiles.append(profile)
        print("BOOLEAN_MATERIAL_PROFILE_PROBE " + json.dumps(profile))

    def counted(self, operation, **kwargs):
        def enter():
            operator_entries.append(self.obj.name)
            return operation()
        return original_native(self, enter, **kwargs)

    proof.Boundary.native_apply = counted
    try:
        target, cutter = fixture("Material Denial")
        cutter.data.materials.clear()
        cutter.data.materials.append(bpy.data.materials.new("Unreviewed Cutter Finish"))
        before = (proof._object_state(target), proof._object_state(cutter))
        try:
            runtime.dispatch("modifier.apply", {"object_name": target.name, "modifier_name": "Owned Cut"})
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED" and "exact nonnull Material ID" in error.message
        else:
            raise AssertionError("Material-bearing cutter reached native apply")
        assert not operator_entries and before == (proof._object_state(target), proof._object_state(cutter))
        cases.append("material_denial_before_native_apply")
        target, cutter = fixture("Zero Slot Denial")
        cutter.data.materials.clear()
        before = (proof._object_state(target), proof._object_state(cutter))
        try:
            runtime.dispatch("modifier.apply", {"object_name": target.name, "modifier_name": "Owned Cut"})
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED" and "one matching nonnull" in error.message
        else:
            raise AssertionError("Zero-slot cutter reached native apply")
        assert not operator_entries and before == (proof._object_state(target), proof._object_state(cutter))
        cases.append("zero_slot_denial_before_native_apply")

        for change in ("binding", "data_replacement", "same_name_replacement"):
            target, cutter = fixture("Final Cutter " + change)
            before_target = proof._object_state(target)
            armed, retained = [], []
            old_manager = runtime.permissions

            def remember(self, assignments, *, target=target, armed=armed):
                original_sources(self, assignments)
                if self.obj == target and self.method == "modifier.apply":
                    armed.append(True)

            def provider(*, change=change, cutter=cutter, armed=armed, retained=retained):
                if armed and not retained:
                    if change == "binding":
                        cutter.data.materials.append(bpy.data.materials.new("Manual Cutter Finish"))
                    elif change == "data_replacement":
                        cutter.data = cutter.data.copy()
                    else:
                        old_name = cutter.name
                        cutter.name += " Retained Original"
                        replacement = bpy.data.objects.new(old_name, cutter.data.copy())
                        scene.collection.objects.link(replacement)
                    retained.append((proof._object_state(cutter), tuple(obj.as_pointer() for obj in bpy.data.objects)))
                return grants

            proof.Boundary.sources = remember
            manager = PermissionManager(provider)
            runtime.permissions = runtime.executor.permissions = manager
            try:
                runtime.dispatch("modifier.apply", {"object_name": target.name, "modifier_name": "Owned Cut"})
            except BridgeError:
                pass
            else:
                raise AssertionError("Final provider's cutter edit was adopted")
            finally:
                proof.Boundary.sources = original_sources
                runtime.permissions = runtime.executor.permissions = old_manager
            assert retained and retained[0] == (proof._object_state(cutter), tuple(obj.as_pointer() for obj in bpy.data.objects))
            assert before_target == proof._object_state(target) and not operator_entries
            cases.append(change + "_retained_before_native_apply")

        target, cutter = fixture("Shared Slot Success")
        target_before, cutter_before = proof._object_state(target), proof._object_state(cutter)
        modifier_identity = target.modifiers["Owned Cut"].as_pointer()
        params = {"object_name": target.name, "modifier_name": "Owned Cut"}
        assert runtime.dispatch("modifier.inspect", params)["modifier"]["settings"]["material_mode"] == "INDEX"
        runtime.dispatch("modifier.set", {**params, "settings": {"material_mode": "TRANSFER"}})
        transfer_state = proof._object_state(target)
        assert runtime.dispatch("modifier.inspect", params)["modifier"]["settings"]["material_mode"] == "TRANSFER"
        try:
            runtime.dispatch("modifier.apply", params)
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED" and "EXACT/INDEX" in error.message
        else:
            raise AssertionError("TRANSFER conversion reached native apply")
        assert not operator_entries and proof._object_state(target) == transfer_state and proof._object_state(cutter) == cutter_before
        runtime.dispatch("modifier.set", {**params, "settings": {"material_mode": "INDEX"}})
        assert proof._object_state(target) == target_before
        assert target.modifiers["Owned Cut"].as_pointer() == modifier_identity
        cases.append("typed_transfer_denial_and_exact_index_correction")
        result = runtime.dispatch("modifier.apply", {"object_name": target.name, "modifier_name": "Owned Cut"})
        assert result["verified"] and operator_entries == [target.name]
        assert not target.modifiers and proof._object_state(cutter) == cutter_before
        assert tuple(target.data.materials) == (bpy.data.materials["Shared Slot Success Target Finish"],)
        assert all(poly.material_index == 0 for poly in target.data.polygons)
        assert len(target.data.vertices) != 0 and proof._object_state(target)[11][1] != target_before[11][1]
        return {"cases": cases, "shared_slot_same_material_id_success": True, "native_operation_entries": len(operator_entries),
                "removed_modifier_identity": modifier_identity, "target_bindings_unchanged": True,
                "cutter_full_stored_state_preserved": True, "native_material_research_profiles": native_profiles,
                "material_mode_inspected_and_corrected_through_typed_tools": True}
    finally:
        proof.Boundary.sources, proof.Boundary.native_apply = original_sources, original_native


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
    boolean_evidence = boolean_material_boundaries(runtime, scene, grants)
    apply_authority = mesh_apply_authority(runtime, scene, grants)
    assert protected.location.x == 41.
    assert tuple(obj.as_pointer() for obj in bpy.context.selected_objects) == selection
    assert bpy.context.view_layer.objects.active == active
    print("BLENDER_CODEX_OBJECT_RNA_MUTATIONS_OK " + json.dumps({"blender": bpy.app.version_string, "stops": stops, "measured_rna_recovery": True,
          "native_apply_context_preserved": True, "protected_object_preserved": True, "windows_qualified": False,
          "native_apply_rollback_claimed": False, "manual_interleavings": adversarial, "activation_probe": activation_probe, "rotation_mode_alias_recovery": True,
          "boolean_material_boundaries": boolean_evidence,
          "mesh_apply_authority": apply_authority,
          "native_blocking_seconds": {"modifier": modifier_applied["native_blocking_seconds"], "transform": transform_applied["native_blocking_seconds"]}}, sort_keys=True))
    blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
