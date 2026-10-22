"""Registered Scene mutation boundaries; disposable fixtures, no project save."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _scene_collection_scope as collection_scope  # noqa: E402
from blender_codex_bridge.tools import _scene_edit_profile as profile  # noqa: E402
from blender_codex_bridge.tools import _scene_mutation as proof  # noqa: E402


def geometry(obj):
    raw = {"vertices": [list(v.co) for v in obj.data.vertices], "edges": [list(e.vertices) for e in obj.data.edges],
           "polygons": [list(p.vertices) for p in obj.data.polygons],
           "bindings": [(slot.link, None if slot.material is None else (slot.material.as_pointer(), slot.material.session_uid)) for slot in obj.material_slots]}
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()


def make_getter(captured):
    def read_counter(_owner):
        captured[0] += 1
        return .5
    return read_counter


def main():
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: True for permission in Permission}
    manager = PermissionManager(lambda: dict(grants))
    runtime.permissions = manager
    runtime.executor.permissions = manager
    runtime.registry.enable_toolset("scene_edit")
    scene = bpy.context.scene
    camera = scene.camera
    light = next(obj for obj in scene.objects if obj.type == "LIGHT")
    mesh = next(obj for obj in scene.objects if obj.type == "MESH")
    protected = geometry(mesh)
    original_context = proof.session(bpy)
    results = []
    dependency_controls = []
    invalid_context_methods = []

    def call(method, params):
        result = runtime.dispatch(method, params)
        assert proof.session(bpy) == original_context
        assert geometry(mesh) == protected
        return result

    def reset():
        grants.update({permission.value: True for permission in Permission})
        runtime.state.set_paused(False)
        runtime.state.set_emergency_stopped(False)
        runtime.registry.enable_toolset("scene_edit")
        runtime.permissions = manager
        runtime.executor.permissions = manager

    def failure(method, params, action, *, code=None, restored=None):
        original = proof.Boundary.write
        writes = []
        def inject(boundary, name, value, **kwargs):
            result = original(boundary, name, value, **kwargs)
            writes.append(name)
            if len(writes) == 1:
                action(boundary)
            return result
        proof.Boundary.write = inject
        try:
            try:
                runtime.dispatch(method, params)
            except BridgeError as error:
                if code is not None:
                    assert error.code == code, (error.code, error.context)
                if restored is not None:
                    assert error.context["rollback_verified"] is restored, error.context
                assert error.context["recovery_evidence"]["kind"] == "scene_mutation"
                results.append({"case": action.__name__, "error": error.code, "writes": writes,
                                "rollback_verified": error.context["rollback_verified"],
                                "possible_mutation": error.context["possible_mutation"]})
                return error
            raise AssertionError("Injected Scene mutation was not rejected")
        finally:
            proof.Boundary.write = original

    try:
        call("scene.configure", {"scene_name": scene.name, "unit_system": "METRIC", "unit_scale_length": .01,
                                 "use_gravity": False, "gravity": [0., -.2, -9.81]})
        assert scene.unit_settings.scale_length == proof.canonical(scene.unit_settings.bl_rna.properties["scale_length"], .01)
        call("camera.configure", {"object_name": camera.name, "lens": 43.1, "sensor_width": 37.2,
                                   "clip_start": .02, "clip_end": 400., "dof_enabled": True,
                                   "focus_object": mesh.name, "aperture_fstop": 3.2})
        assert camera.data.dof.focus_object == mesh
        call("camera.configure", {"object_name": camera.name, "clear_focus_object": True})
        call("light.configure", {"object_name": light.name, "energy": 731.2, "color": [.2, .3, .4]})
        call("world.configure", {"scene_name": scene.name, "use_nodes": True, "color": [.1, .2, .3], "strength": .7})
        old_world = scene.world
        call("world.configure", {"scene_name": scene.name, "world_name": "Owned Boundary World", "create": True,
                                  "use_nodes": True, "color": [.17, .29, .43], "strength": .8})
        new_world = scene.world
        assert new_world != old_world and bpy.data.worlds.get(new_world.name) == new_world
        call("world.configure", {"scene_name": scene.name, "world_name": old_world.name})
        assert scene.world == old_world
        created = call("collection.create", {"scene_name": scene.name, "name": "Owned Boundary Collection"})
        collection = bpy.data.collections[created["collection"]]
        identity = proof.token(collection)
        call("collection.rename", {"collection_name": collection.name, "new_name": "Owned Renamed Collection"})
        assert proof.token(collection) == identity
        call("collection.delete", {"collection_name": collection.name, "confirm_delete": True})
        assert bpy.data.collections.get("Owned Renamed Collection") is None

        energy, color = light.data.energy, tuple(light.data.color)
        def fail_after_first(_boundary):
            raise RuntimeError("Owned injected failure after native field publication")
        error = failure("light.configure", {"object_name": light.name, "energy": 222., "color": [.5, .6, .7]},
                        fail_after_first, code="OPERATION_FAILED", restored=True)
        assert light.data.energy == energy and tuple(light.data.color) == color
        # The requested literal fields were restored, while the completed
        # BEFORE/AFTER native checkpoint bookkeeping remains a possible effect.
        assert error.context["possible_mutation"] is True
        assert error.context["recovery_evidence"]["restoration_verified"] is True
        assert error.context["undo_boundary_finalized"] is True

        def revoke(_boundary):
            grants[Permission.EDIT_SCENE.value] = False
        failure("light.configure", {"object_name": light.name, "energy": 333., "color": [.5, .6, .7]},
                revoke, code="PERMISSION_DENIED", restored=False)
        assert light.data.energy == 333. and tuple(light.data.color) == color
        reset()
        light.data.energy = energy

        # Allocation compensation is separately authorized: losing deletion
        # permission retains the owned ID and records it instead of removing it.
        for allow_delete in (True, False):
            reset()
            grants[Permission.DELETE_OBJECTS.value] = allow_delete
            name = "Owned Failed World " + str(allow_delete)
            previous = scene.world
            error = failure("world.configure", {"scene_name": scene.name, "world_name": name, "create": True,
                                                 "use_nodes": True, "color": [.31, .41, .51]},
                            fail_after_first, code="OPERATION_FAILED", restored=allow_delete)
            assert scene.world == previous
            retained = bpy.data.worlds.get(name)
            assert (retained is None) is allow_delete
            if retained is not None:
                assert retained.users == 0
                assert any(item["kind"] == "world_allocation" for item in error.context["recovery_evidence"]["retained_effects"])
                facts = runtime.state.history(1)[0]["recovery_evidence"]
                assert facts["kind"] == "scene_mutation" and not facts["restoration_verified"]
                assert facts["retained_effects"] == [{"kind": "world_allocation", "name": name}]
                grants[Permission.INSPECT_SCENE.value] = False
                hidden = runtime.dispatch("checkpoint.list", {"limit": 1})["operation_history"][0]
                assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"]
                assert name not in json.dumps(hidden)
                reset()
                bpy.data.worlds.remove(retained)
        reset()

        if bpy.app.version < (5, 0, 0):
            lazy = bpy.data.worlds.new("Owned Lazy World")
            lazy.color = (.23, .37, .65)
            assert lazy.node_tree is None and not lazy.use_nodes
            previous = scene.world
            scene.world = lazy
            error = failure("world.configure", {"scene_name": scene.name, "use_nodes": True, "strength": 2.},
                            fail_after_first, code="OPERATION_FAILED", restored=False)
            assert not lazy.use_nodes and lazy.node_tree is not None
            assert any(item["kind"] == "embedded_world_graph_allocation" for item in error.context["recovery_evidence"]["retained_effects"])
            scene.world = previous
            bpy.data.worlds.remove(lazy)

        for allow_delete in (True, False):
            reset()
            grants[Permission.DELETE_OBJECTS.value] = allow_delete
            name = "Owned Failed Collection " + str(allow_delete)
            original_scope = collection_scope.snapshot
            fired = [False]
            def inspect_scope(*args, original_scope=original_scope, fired=fired, name=name, **kwargs):
                observed = original_scope(*args, **kwargs)
                owned = bpy.data.collections.get(name)
                if owned is not None and scene.collection.children.get(name) == owned and not fired[0]:
                    fired[0] = True
                    raise RuntimeError("Owned failure after collection link publication")
                return observed
            collection_scope.snapshot = inspect_scope
            try:
                try:
                    runtime.dispatch("collection.create", {"scene_name": scene.name, "name": name})
                except BridgeError as error:
                    assert error.code == "OPERATION_FAILED" and error.context["rollback_verified"] is allow_delete, error.context
                    results.append({"case": "collection-allocation-cleanup-" + str(allow_delete), "error": error.code,
                                    "rollback_verified": allow_delete, "retained": not allow_delete})
                else:
                    raise AssertionError("Owned collection injection was not reached")
            finally:
                collection_scope.snapshot = original_scope
            retained = bpy.data.collections.get(name)
            assert (retained is None) is allow_delete
            if retained is not None:
                assert scene.collection.children.get(name) == retained
                reset()
                bpy.data.collections.remove(retained)
        reset()

        # Every modifying registration denies its complete permission set before
        # checkpoint markers or native target state can change.
        permission_collection = bpy.data.collections.new("Owned Permission Collection")
        scene.collection.children.link(permission_collection)
        denied_methods = [
            ("scene.configure", {"scene_name": scene.name, "use_gravity": True}),
            ("camera.configure", {"object_name": camera.name, "lens": 61.}),
            ("light.configure", {"object_name": light.name, "energy": 12.}),
            ("world.configure", {"scene_name": scene.name, "strength": 2.}),
            ("collection.create", {"scene_name": scene.name, "name": "Owned Never Allocated"}),
            ("collection.rename", {"collection_name": permission_collection.name, "new_name": "Owned Never Renamed"}),
            ("collection.delete", {"collection_name": permission_collection.name, "confirm_delete": True}),
        ]
        denied = []
        def scalars():
            bg = profile.background(scene.world)
            return (scene.camera.as_pointer(), scene.use_gravity, tuple(scene.gravity), scene.unit_settings.system,
                    scene.unit_settings.scale_length, camera.data.lens, camera.data.sensor_width, light.data.energy,
                    tuple(light.data.color), scene.world.as_pointer(), tuple(scene.world.color),
                    tuple(bg.inputs["Color"].default_value), bg.inputs["Strength"].default_value,
                    tuple(sorted((item.as_pointer(), item.name) for item in bpy.data.collections)),
                    scene.get("_codex_bridge_undo_marker"))
        for method, params in denied_methods:
            before = scalars()
            grants[Permission.EDIT_SCENE.value] = False
            try:
                runtime.dispatch(method, params)
            except BridgeError as error:
                assert error.code == "PERMISSION_DENIED"
            else:
                raise AssertionError("Scene permission denial was bypassed")
            assert scalars() == before and proof.session(bpy) == original_context
            denied.append(method)
            reset()
        grants[Permission.DELETE_OBJECTS.value] = False
        before = scalars()
        try:
            runtime.dispatch("collection.delete", {"collection_name": permission_collection.name, "confirm_delete": True})
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Collection deletion permission was bypassed")
        assert scalars() == before
        reset()

        # Unsupported contents must stay linked, with the same native identity.
        permission_collection.objects.link(mesh)
        before = scalars()
        try:
            runtime.dispatch("collection.delete", {"collection_name": permission_collection.name, "confirm_delete": True})
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED"
        else:
            raise AssertionError("Nonempty collection was orphaned")
        assert permission_collection.objects.get(mesh.name) == mesh and geometry(mesh) == protected
        assert scalars()[:-1] == before[:-1]  # A permitted checkpoint marker is bookkeeping.
        permission_collection.objects.unlink(mesh)
        bpy.data.collections.remove(permission_collection)

        # Explicit names never authorize a mode/Scene switch. These seven
        # invalid contexts leave their own and protected current-Scene data as-is.
        other_scene = bpy.data.scenes.new("Owned Foreign Boundary Scene")
        other_camera = bpy.data.objects.new("Owned Foreign Camera", bpy.data.cameras.new("Owned Foreign Camera Data"))
        other_light = bpy.data.objects.new("Owned Foreign Light", bpy.data.lights.new("Owned Foreign Light Data", "POINT"))
        other_collection = bpy.data.collections.new("Owned Foreign Collection")
        other_scene.collection.objects.link(other_camera)
        other_scene.collection.objects.link(other_light)
        other_scene.collection.children.link(other_collection)
        invalid = [
            ("scene.configure", {"scene_name": other_scene.name, "use_gravity": True}),
            ("camera.configure", {"object_name": other_camera.name, "lens": 61.}),
            ("light.configure", {"object_name": other_light.name, "energy": 12.}),
            ("world.configure", {"scene_name": other_scene.name, "create": True, "world_name": "Owned Never Foreign World"}),
            ("collection.create", {"scene_name": other_scene.name, "name": "Owned Never Foreign Collection"}),
            ("collection.rename", {"collection_name": other_collection.name, "new_name": "Owned Never Foreign Rename"}),
            ("collection.delete", {"collection_name": other_collection.name, "confirm_delete": True}),
        ]
        foreign_before = (other_scene.use_gravity, other_camera.data.lens, other_light.data.energy, other_collection.name,
                          tuple(bpy.data.worlds.keys()), tuple(bpy.data.collections.keys()))
        for method, params in invalid:
            before = scalars()
            try:
                runtime.dispatch(method, params)
            except BridgeError as error:
                assert error.code == "NOT_IMPLEMENTED", error.to_dict()
            else:
                raise AssertionError("Foreign Scene mutation was admitted: " + method)
            assert scalars()[:-1] == before[:-1] and proof.session(bpy) == original_context
            assert (other_scene.use_gravity, other_camera.data.lens, other_light.data.energy, other_collection.name,
                    tuple(bpy.data.worlds.keys()), tuple(bpy.data.collections.keys())) == foreign_before
            invalid_context_methods.append(method)
        bpy.data.objects.remove(other_camera, do_unlink=True)
        bpy.data.objects.remove(other_light, do_unlink=True)
        bpy.data.collections.remove(other_collection)
        bpy.data.scenes.remove(other_scene)

        # Ordinary later evaluation would execute unrelated scripted owners.
        # The bridge admits none of them, even unused data and nested groups.
        namespace = "owned_scene_boundary_counter"
        counters = {}
        def count(label, frame):
            counters[label] = counters.get(label, 0) + 1
            return .25 + float(frame) * .001
        assert namespace not in bpy.app.driver_namespace
        bpy.app.driver_namespace[namespace] = count
        unused_material = bpy.data.materials.new("Owned Unused Animated Material")
        unused_material.use_nodes = True
        unused_world = bpy.data.worlds.new("Owned Unused Animated World")
        unused_world.use_nodes = True
        nested = bpy.data.node_groups.new("Owned Nested Boundary Shader", "ShaderNodeTree")
        nested.interface.new_socket(name="Factor", in_out="OUTPUT", socket_type="NodeSocketFloat")
        nested_value = nested.nodes.new("ShaderNodeValue")
        nested_output = nested.nodes.new("NodeGroupOutput")
        nested.links.new(nested_value.outputs[0], nested_output.inputs["Factor"])
        parent_group = bpy.data.node_groups.new("Owned Parent Boundary Shader", "ShaderNodeTree")
        parent_group.interface.new_socket(name="Factor", in_out="OUTPUT", socket_type="NodeSocketFloat")
        nested_group = parent_group.nodes.new("ShaderNodeGroup")
        nested_group.node_tree = nested
        parent_output = parent_group.nodes.new("NodeGroupOutput")
        parent_group.links.new(nested_group.outputs["Factor"], parent_output.inputs["Factor"])
        material_group = unused_material.node_tree.nodes.new("ShaderNodeGroup")
        material_group.node_tree = parent_group
        principled = next(node for node in unused_material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
        unused_material.node_tree.links.new(material_group.outputs["Factor"], principled.inputs["Roughness"])
        compositor = bpy.data.node_groups.new("Owned Boundary Compositor", "CompositorNodeTree")
        compositor.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        comp_value = compositor.nodes.new("ShaderNodeValue" if hasattr(scene, "compositing_node_group") else "CompositorNodeValue")
        comp_output = compositor.nodes.new("NodeGroupOutput")
        compositor.links.new(comp_value.outputs[0], comp_output.inputs["Image"])
        binding_mesh = bpy.data.meshes.new("Owned Dependency Control Mesh")
        binding_object = bpy.data.objects.new("Owned Dependency Control Object", binding_mesh)
        scene.collection.objects.link(binding_object)
        dependency_collection = bpy.data.collections.new("Owned Static Dependency Collection")
        scene.collection.children.link(dependency_collection)
        dependency_methods = [*denied_methods[:5],
            ("collection.rename", {"collection_name": dependency_collection.name, "new_name": "Owned Never Static Rename"}),
            ("collection.delete", {"collection_name": dependency_collection.name, "confirm_delete": True})]
        controls = [
            ("unused-material", unused_material, unused_material, "diffuse_color", 0),
            ("unused-world", unused_world, unused_world, "color", 0),
            ("nested-shader", nested, nested_value.outputs[0], "default_value", None),
            ("compositor-tree", compositor, comp_value.outputs[0], "default_value", None),
        ]
        original_compositor = scene.compositing_node_group if hasattr(scene, "compositing_node_group") else None
        try:
            for label, owner, target, path, index in controls:
                # Blender 5.2 builds this compositor's animation dependency
                # relations when the tree is already bound at driver creation.
                # Keep the active-tree control distinct from unused-ID cases.
                if label == "compositor-tree" and hasattr(scene, "compositing_node_group"):
                    scene.compositing_node_group = compositor
                    bpy.context.view_layer.update()
                curve = target.driver_add(path) if index is None else target.driver_add(path, index)
                curve.driver.type = "SCRIPTED"
                curve.driver.expression = f'{namespace}("{label}", frame)'
                before_counter = dict(counters)
                before = scalars()
                before_checkpoint = runtime.checkpoints.before_modification
                after_checkpoint = runtime.checkpoints.after_modification
                def checkpoint_stage(original, stage, *, case_label=label):
                    def observe(*args, **kwargs):
                        captured = dict(counters)
                        result = original(*args, **kwargs)
                        print("SCENE_CHECKPOINT_CONTROL " + json.dumps({"case": case_label, "stage": stage,
                              "before": captured, "after": dict(counters)}), flush=True)
                        return result
                    return observe
                runtime.checkpoints.before_modification = checkpoint_stage(before_checkpoint, "before_modification")
                runtime.checkpoints.after_modification = checkpoint_stage(after_checkpoint, "after_modification")
                try:
                    for method, params in dependency_methods:
                        try:
                            runtime.dispatch(method, params)
                        except BridgeError as error:
                            assert error.code == "NOT_IMPLEMENTED", error.to_dict()
                        else:
                            raise AssertionError("Animated global dependency was admitted")
                        assert counters == before_counter and scalars()[:-1] == before[:-1]
                finally:
                    runtime.checkpoints.before_modification = before_checkpoint
                    runtime.checkpoints.after_modification = after_checkpoint
                prior_frame, prior_subframe = scene.frame_current, scene.frame_subframe
                prior_world = scene.world
                prior_compositor = scene.compositing_node_group if hasattr(scene, "compositing_node_group") else None
                prior_use_nodes = None if hasattr(scene, "compositing_node_group") else scene.use_nodes
                if label in {"unused-material", "nested-shader"}:
                    binding_mesh.materials.append(unused_material)
                elif label == "unused-world":
                    scene.world = unused_world
                elif hasattr(scene, "compositing_node_group"):
                    scene.compositing_node_group = compositor
                else:
                    scene.use_nodes = True
                    scene.node_tree.nodes.clear()
                    bound_group = scene.node_tree.nodes.new("CompositorNodeGroup")
                    bound_group.node_tree = compositor
                    bound_output = scene.node_tree.nodes.new("CompositorNodeComposite")
                    scene.node_tree.links.new(bound_group.outputs["Image"], bound_output.inputs["Image"])
                scene.update_tag()
                bpy.context.view_layer.update()
                scene.frame_set(prior_frame + 1)
                bpy.context.view_layer.update()
                graph = bpy.context.evaluated_depsgraph_get()
                owner.update_tag()
                graph.update()
                owner.evaluated_get(graph)
                delta = counters.get(label, 0) - before_counter.get(label, 0)
                print("SCENE_STATIC_CONTROL " + json.dumps({"case": label, "driver_valid": curve.driver.is_valid,
                      "later_binding_and_native_evaluation_counter_delta": delta}), flush=True)
                assert curve.driver.is_valid and delta > 0, (label, delta)
                dependency_controls.append({"kind": label, "methods_refused": 7, "bridge_counter_delta": 0,
                                            "unused_during_bridge_admission": label != "compositor-tree" or not hasattr(scene, "compositing_node_group"),
                                            "later_binding_and_native_evaluation_counter_delta": delta})
                owner.animation_data_clear()
                binding_mesh.materials.clear()
                scene.world = prior_world
                if hasattr(scene, "compositing_node_group"):
                    scene.compositing_node_group = prior_compositor
                elif label == "compositor-tree":
                    scene.node_tree.nodes.clear()
                    scene.use_nodes = prior_use_nodes
                scene.frame_set(prior_frame, subframe=prior_subframe)
                bpy.context.view_layer.update()

            # A permission provider may change unowned data. Its newly added
            # driver never becomes an adopted baseline or a restoration target.
            installed = [False]
            before_counter = dict(counters)
            def late_driver_provider(boundary):
                def provide():
                    if not installed[0]:
                        installed[0] = True
                        curve = unused_material.driver_add("diffuse_color", 0)
                        curve.driver.type = "SCRIPTED"
                        curve.driver.expression = f'{namespace}("late-provider", frame)'
                    return dict(grants)
                boundary.context.permissions = PermissionManager(provide)
            failure("light.configure", {"object_name": light.name, "energy": 719., "color": [.7, .6, .5]},
                    late_driver_provider, code="NOT_IMPLEMENTED", restored=False)
            assert installed[0] and light.data.energy == 719. and tuple(light.data.color) == color and counters == before_counter
            unused_material.animation_data_clear()
            light.data.energy = energy
        finally:
            bpy.app.driver_namespace.pop(namespace, None)
            if hasattr(scene, "compositing_node_group"):
                scene.compositing_node_group = original_compositor
            bpy.data.materials.remove(unused_material)
            bpy.data.worlds.remove(unused_world)
            bpy.data.node_groups.remove(parent_group)
            bpy.data.node_groups.remove(nested)
            bpy.data.node_groups.remove(compositor)
            bpy.data.collections.remove(dependency_collection)
            bpy.data.objects.remove(binding_object, do_unlink=True)
            bpy.data.meshes.remove(binding_mesh)

        def manual_edit(_boundary):
            light.data.use_shadow = not light.data.use_shadow
        before_shadow = light.data.use_shadow
        failure("light.configure", {"object_name": light.name, "energy": 444., "color": [.5, .6, .7]},
                manual_edit, restored=False)
        assert light.data.energy == 444. and light.data.use_shadow is not before_shadow and tuple(light.data.color) == color
        light.data.energy, light.data.use_shadow = energy, before_shadow

        foreign = []
        def acquire_consumer(_boundary):
            foreign.append(bpy.data.objects.new("Protected Foreign Light Consumer", light.data))
        failure("light.configure", {"object_name": light.name, "energy": 555., "color": [.5, .6, .7]}, acquire_consumer, restored=False)
        assert foreign[0].data == light.data and light.data.energy == 555. and tuple(light.data.color) == color
        bpy.data.objects.remove(foreign[0])
        light.data.energy = energy

        def pause(_boundary):
            runtime.state.set_paused(True)
        failure("light.configure", {"object_name": light.name, "energy": 666., "color": [.5, .6, .7]}, pause,
                code="AGENT_PAUSED", restored=False)
        assert light.data.energy == 666. and tuple(light.data.color) == color
        reset()
        light.data.energy = energy

        # Real canonical queue and connection owners stop after the complete
        # native profile comparison, independently of earlier provider checks.
        for when in (2, 3):
            for kind in ("cancel", "queue_deadline", "disconnect", "owner_deadline", "toolset", "pause", "stop"):
                reset()
                lens, sensor = camera.data.lens, camera.data.sensor_width
                life = RequestLifetime(ConnectionLifetime())
                request = Request(id=f"scene-{kind}-{when}", method="camera.configure",
                                  params={"object_name": camera.name, "lens": 52., "sensor_width": 41.}, _lifecycle=life)
                queued = QueuedRequest(request, deadline=time.monotonic() + 300.)
                assert queued.try_start()
                original_check = proof.Boundary.check
                calls = [0]
                def snapshot(instance, *, original_check=original_check, calls=calls, when=when, kind=kind, queued=queued, life=life, **kwargs):
                    observed = original_check(instance, **kwargs)
                    calls[0] += 1
                    if calls[0] == when - 1:
                        if kind == "cancel":
                            queued.cancel_pending(BridgeError("TIMEOUT", "Owned cancellation"))
                        elif kind == "queue_deadline":
                            queued.deadline = 0.
                        elif kind == "disconnect":
                            life.connection.disconnected.set()
                        elif kind == "owner_deadline":
                            life.deadline = 0.
                        elif kind == "toolset":
                            runtime.registry.disable_toolset("scene_edit")
                        elif kind == "pause":
                            runtime.state.set_paused(True)
                        else:
                            runtime.state.set_emergency_stopped(True)
                    return observed
                proof.Boundary.check = snapshot
                try:
                    response = runtime.executor.execute_request(request, check_cancelled=queued.check_active)
                finally:
                    proof.Boundary.check = original_check
                assert not response.ok and calls[0] >= when - 1
                expected_code = {"toolset": "TOOLSET_DISABLED", "pause": "AGENT_PAUSED", "stop": "EMERGENCY_STOPPED"}.get(kind, "TIMEOUT")
                assert response.error["code"] == expected_code, response.error
                assert camera.data.sensor_width == sensor
                assert camera.data.lens == (lens if when == 2 else 52.)
                results.append({"case": f"canonical-{kind}-{when}", "error": expected_code,
                                "owned_first_field_retained": when == 3, "second_field_preserved": True})
                reset()
                camera.data.lens, camera.data.sensor_width = lens, sensor

        getter_controls = []
        for owner_kind, method, params in (("Scene", "scene.configure", {"scene_name": scene.name, "use_gravity": True}),
                                           ("Camera", "camera.configure", {"object_name": camera.name, "lens": 61.}),
                                           ("World", "world.configure", {"scene_name": scene.name, "strength": 1.2})):
            counter = [0]
            getter = make_getter(counter)
            owner_type = getattr(bpy.types, owner_kind)
            owner_type.owned_boundary_getter = bpy.props.FloatProperty(get=getter)
            assert owner_type.bl_rna.properties.get("owned_boundary_getter") is not None
            try:
                try:
                    runtime.dispatch(method, params)
                except BridgeError as error:
                    assert error.code == "NOT_IMPLEMENTED", error.context
                else:
                    raise AssertionError("Runtime getter admission should fail")
                assert counter[0] == 0
                getter_controls.append({"type": owner_kind, "getter_calls": counter[0]})
            finally:
                delattr(owner_type, "owned_boundary_getter")

        assert geometry(mesh) == protected and proof.session(bpy) == original_context
        print("BLENDER_SCENE_EDIT_BOUNDARIES_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "success_methods": 7, "fault_cases": results, "runtime_getter_controls": getter_controls,
            "permission_denial_methods": denied, "separate_delete_denial": True, "nonempty_collection_preserved": True,
            "invalid_context_methods": invalid_context_methods, "static_dependency_controls": dependency_controls,
            "protected_geometry_sha256": protected, "context_preserved": True,
            "project_saved": False, "user_preferences_saved": False,
            "artistic_or_windows_acceptance": False}, sort_keys=True))
    finally:
        reset()
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
