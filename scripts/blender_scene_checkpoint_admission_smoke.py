"""Small native checkpoint admission probes; no saved project or preferences."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge import checkpoints as checkpoint  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import _scene_checkpoint_admission as admission  # noqa: E402
from blender_codex_bridge.tools import _scene_mutation as proof  # noqa: E402


def main():
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True
    blender_codex_bridge.register()
    runtime = get_runtime()
    runtime.registry.enable_toolset("scene_edit")
    domain_entries = []
    for name in ("scene.configure", "collection.create", "collection.rename", "collection.delete",
                 "camera.configure", "light.configure", "world.configure"):
        spec = runtime.registry.get(name)
        def observed(context, params, *, name=name, handler=spec.handler):
            domain_entries.append(name)
            return handler(context, params)
        runtime.registry._tools[name] = replace(spec, handler=observed)
    grants = {item.value: True for item in Permission}
    provider_hook = [None]

    def provide():
        if provider_hook[0] is not None:
            provider_hook[0]()
        return dict(grants)

    permissions = PermissionManager(provide)
    runtime.permissions = runtime.executor.permissions = permissions
    scene = bpy.context.scene
    light = next(obj for obj in scene.objects if obj.type == "LIGHT")
    mesh = bpy.context.active_object
    initial_context = proof.session(bpy)
    initial_energy = light.data.energy
    original_compositor = scene.compositing_node_group if hasattr(scene, "compositing_node_group") else None
    original_use_nodes = None if hasattr(scene, "compositing_node_group") else scene.use_nodes
    if hasattr(scene, "compositing_node_group"):
        tree = bpy.data.node_groups.new("Owned Checkpoint Compositor", "CompositorNodeTree")
        tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        value = tree.nodes.new("ShaderNodeValue")
        output = tree.nodes.new("NodeGroupOutput")
        tree.links.new(value.outputs[0], output.inputs["Image"])
        scene.compositing_node_group = tree
    else:
        scene.use_nodes = True
        tree = scene.node_tree
        tree.nodes.clear()
        value = tree.nodes.new("CompositorNodeValue")
        output = tree.nodes.new("CompositorNodeComposite")
        tree.links.new(value.outputs[0], output.inputs["Image"])
    bpy.context.view_layer.update()
    namespace = "owned_checkpoint_admission_counter"
    assert namespace not in bpy.app.driver_namespace
    counters = {}

    def count(label, frame):
        counters[label] = counters.get(label, 0) + 1
        return .5 + float(frame) * .001

    bpy.app.driver_namespace[namespace] = count
    cases = []

    def fresh():
        provider_hook[0] = None
        manager = checkpoint.CheckpointManager()
        runtime.checkpoints = runtime.executor.checkpoints = manager
        # Setup is owned disposable fixture data, with a valid reserved value.
        scene[checkpoint.MARKER_KEY] = manager._prefix + "0" * 32
        light.data.energy = initial_energy
        return manager

    def add_driver(label):
        curve = value.outputs[0].driver_add("default_value")
        curve.driver.type = "SCRIPTED"
        curve.driver.expression = f'{namespace}("{label}", frame)'
        return curve

    def reject(params=None):
        try:
            runtime.dispatch("light.configure", params or {"object_name": light.name, "energy": 417.})
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED", error.to_dict()
            return error
        raise AssertionError("Late checkpoint dependency or marker drift was admitted")

    try:
        # A harmless admitted compositor proves ordinary checkpoints still run.
        manager = fresh()
        original_identity = proof.token(scene.original)
        before_role = int(scene.user_of_id(scene)), proof.token(scene.tool_settings.particle_edit.object)
        assert before_role == (0, proof.token(None)), before_role
        ordinary = runtime.dispatch("light.configure", {"object_name": light.name, "energy": 416.})
        assert light.data.energy == 416. and manager._pending is None
        assert int(scene.user_of_id(scene)) == 1 and scene.tool_settings.particle_edit.object == mesh
        assert proof.token(scene.original) == original_identity
        assert ordinary["preservation_scope"]["complete"] is False
        cases.append({"case": "ordinary-before-after", "succeeded": True,
                      "weak_role_transition": "0+None to 1+exact-frozen-active", "original_identity_preserved": True})

        for stage in ("before", "after", "old-editor"):
            manager = fresh()
            retained = None
            if stage == "old-editor":
                assert manager.before_modification("owned retained editor fixture")
                pending = manager._pending
                retained = checkpoint.MeshEditSession(pending, "owned-retained-editor", scene.session_uid,
                                                      mesh.session_uid, mesh.name)
                manager._editor_session, manager._pending = retained, None
            pushes = [0]
            pushed = manager._window.pushed

            def observe_push(*args, pushes=pushes, pushed=pushed, **kwargs):
                pushes[0] += 1
                return pushed(*args, **kwargs)

            manager._window.pushed = observe_push
            step_limit = manager._step_limit
            reads = [0]
            installed = [False]
            label = "late-" + stage

            def late_reader(blender, *, reads=reads, stage=stage, installed=installed, label=label, step_limit=step_limit):
                reads[0] += 1
                if reads[0] == (2 if stage == "after" else 1):
                    installed[0] = True
                    add_driver(label)
                return step_limit(blender)

            manager._step_limit = late_reader
            before_counter = dict(counters)
            error = reject()
            assert installed[0] and counters == before_counter
            assert pushes[0] == (1 if stage == "after" else 0)
            assert light.data.energy == (417. if stage == "after" else initial_energy)
            if retained is not None:
                assert manager._editor_session is retained
            elif stage == "after":
                assert manager._pending is not None
            receipt = error.context["checkpoint_bookkeeping"]
            assert receipt["native_snapshots_completed"] == 0 and receipt["next_write_rejected"] == "native_undo_push"
            assert receipt["marker_writes_completed"] == 2
            cases.append({"case": label, "driver_callbacks": 0, "completed_native_pushes": pushes[0],
                          "requested_edit_retained": stage == "after", "recovery_record_retained": stage != "before",
                          "checkpoint_bookkeeping": receipt})
            # Positive control: the exact denied driver executes on native push.
            manager._step_limit = step_limit
            before_positive = counters.get(label, 0)
            assert "FINISHED" in bpy.ops.ed.undo_push(message="Owned denied-driver positive control")
            positive_delta = counters.get(label, 0) - before_positive
            assert positive_delta > 0, (stage, counters)
            cases[-1]["positive_native_push_callback_delta"] = positive_delta
            tree.animation_data_clear()

        # The authored ledger was captured before the first provider and is
        # retained through the final native readers, including its owned fields.
        for stage in ("first-provider", "first-callback", "before-reader", "before-handler", "after-reader"):
            for field in ("energy", "use_shadow"):
                manager = fresh()
                shadow = light.data.use_shadow
                original = getattr(light.data, field)
                newer = 913. if field == "energy" else not original
                fired, reads = [False], [0]
                pushes_before = manager._window.position
                read_limit = manager._step_limit

                def change(*, fired=fired, field=field, newer=newer):
                    if not fired[0]:
                        fired[0] = True
                        setattr(light.data, field, newer)

                def authored_reader(blender, *, reads=reads, stage=stage, change=change, read_limit=read_limit):
                    reads[0] += 1
                    if (stage == "before-reader" and reads[0] == 1) or (stage == "after-reader" and reads[0] == 2):
                        change()
                    return read_limit(blender)

                manager._step_limit = authored_reader
                if stage == "first-provider":
                    provider_hook[0] = change
                callback_calls = [0]

                def cancelled(*, stage=stage, change=change, callback_calls=callback_calls):
                    callback_calls[0] += 1
                    if ((stage == "first-callback" and callback_calls[0] == 1)
                            or (stage == "before-handler" and callback_calls[0] == 2)):
                        change()

                request = Request("owned-authored-" + stage + field, "light.configure", {"object_name": light.name, "energy": 417.})
                response = runtime.executor.execute_request(request, check_cancelled=cancelled)
                assert fired[0] and not response.ok and response.error["code"] == "NOT_IMPLEMENTED", response.error
                assert getattr(light.data, field) == newer
                assert light.data.energy == (newer if field == "energy" else 417. if stage == "after-reader" else initial_energy)
                assert manager._window.position - pushes_before == (1 if stage in {"before-handler", "after-reader"} else 0)
                cases.append({"case": "authored-" + stage + "-" + field, "newer_value_preserved": True,
                              "completed_native_pushes": manager._window.position - pushes_before,
                              "requested_edit_retained": stage == "after-reader" and field != "energy"})
                provider_hook[0] = None
                light.data.use_shadow = shadow
                light.data.energy = initial_energy

        # All seven cached domain plans protect the same literal Scene ledger
        # before their first provider; none may capture a newer authored value.
        collection = bpy.data.collections.new("Owned Authored Admission Collection")
        scene.collection.children.link(collection)
        camera = scene.camera
        domain_calls = (
            ("scene.configure", {"scene_name": scene.name, "use_gravity": False}),
            ("collection.create", {"scene_name": scene.name, "name": "Owned Rejected Publication"}),
            ("collection.rename", {"collection_name": collection.name, "new_name": "Owned Rejected Rename"}),
            ("collection.delete", {"collection_name": collection.name, "confirm_delete": True}),
            ("camera.configure", {"object_name": camera.name, "lens": 61.}),
            ("light.configure", {"object_name": light.name, "energy": 417.}),
            ("world.configure", {"scene_name": scene.name, "color": [.2, .3, .4]}),
        )
        try:
            for method, params in domain_calls:
                manager = fresh()
                gravity, fired = tuple(scene.gravity), [False]
                newer = tuple(proof.canonical(scene.bl_rna.properties["gravity"], (1., -2., -8.)))
                def newer_gravity():
                    if not fired[0]:
                        fired[0] = True
                        scene.gravity = newer
                provider_hook[0] = newer_gravity
                entries = len(domain_entries)
                response = runtime.executor.execute_request(Request("owned-seven-" + method, method, params))
                assert fired[0] and not response.ok and response.error["code"] == "NOT_IMPLEMENTED", response.error
                assert tuple(scene.gravity) == newer and manager._window.position == 0
                assert len(domain_entries) == entries
                assert bpy.data.collections.get(collection.name) == collection
                assert bpy.data.collections.get("Owned Rejected Publication") is None
                assert bpy.data.collections.get("Owned Rejected Rename") is None
                cases.append({"case": "first-provider-" + method, "newer_gravity_preserved": True,
                              "handler_entered": False, "completed_native_pushes": 0})
                provider_hook[0] = None
                scene.gravity = gravity

            # Both custom readers must distinguish IDProperty scalar types
            # and signed zero through the actual cached registry/provider path.
            custom_key = "owned_checkpoint_custom_scalar"
            custom_changes = ((False, 0), (0, 0.0), (0.0, -0.0))
            for owner_label, owner, method, params in (
                ("Scene", scene, "light.configure", {"object_name": light.name, "energy": 417.}),
                ("Collection", collection, "collection.rename",
                 {"collection_name": collection.name, "new_name": "Owned Rejected Scalar Rename"}),
            ):
                assert custom_key not in owner
                try:
                    for index, (before, after) in enumerate(custom_changes):
                        manager = fresh()
                        owner[custom_key] = {"nested": {"leaf": before}}
                        initial = owner[custom_key]["nested"]["leaf"]
                        assert type(initial) is type(before)
                        fired = [False]
                        def change_custom(*, owner=owner, after=after, fired=fired):
                            if not fired[0]:
                                fired[0] = True
                                group = owner[custom_key]["nested"]
                                del group["leaf"]
                                group["leaf"] = after
                        provider_hook[0] = change_custom
                        entries = len(domain_entries)
                        marker = scene[checkpoint.MARKER_KEY]
                        response = runtime.executor.execute_request(Request(
                            "owned-custom-scalar-" + owner_label + str(index), method, params))
                        assert fired[0] and not response.ok and response.error["code"] == "NOT_IMPLEMENTED", response.error
                        stored = owner[custom_key]["nested"]["leaf"]
                        assert type(stored) is type(after)
                        assert stored.hex() == after.hex() if type(after) is float else stored == after
                        assert manager._window.position == 0 and len(domain_entries) == entries
                        assert scene[checkpoint.MARKER_KEY] == marker and light.data.energy == initial_energy
                        assert bpy.data.collections.get(collection.name) == collection
                        assert bpy.data.collections.get("Owned Rejected Scalar Rename") is None
                        cases.append({"case": "custom-scalar-" + owner_label + "-" + str(index),
                                      "before_type": type(before).__name__, "after_type": type(after).__name__,
                                      "signed_zero": type(after) is float and after.hex().startswith("-"),
                                      "handler_entered": False, "completed_native_pushes": 0,
                                      "newer_custom_value_preserved": True, "marker_unchanged": True})
                        provider_hook[0] = None
                finally:
                    provider_hook[0] = None
                    if custom_key in owner:
                        del owner[custom_key]
        finally:
            provider_hook[0] = None
            bpy.data.collections.remove(collection)

        # A failure after actual native completion retains the measured push,
        # marker and newer content, with no handler entry or automatic retry.
        manager = fresh()
        original_hook = admission.Admission.after_native_push
        shadow = light.data.use_shadow
        hook_calls = []
        def reject_completion(guard):
            hook_calls.append(True)
            original_hook(guard)
            light.data.use_shadow = not shadow
        admission.Admission.after_native_push = reject_completion
        try:
            error = reject()
            receipt = error.context["checkpoint_bookkeeping"]
            assert len(hook_calls) == 1 and receipt["native_snapshots_completed"] == 1
            assert receipt["marker_writes_completed"] == 2 and receipt["next_write_rejected"] == "after_native_undo_push"
            assert not receipt["compensation_performed"] and manager._window.position == 1
            assert light.data.energy == initial_energy and light.data.use_shadow is not shadow
            cases.append({"case": "native-completion-cas-failure", "hook_calls": 1,
                          "newer_value_preserved": True, "checkpoint_bookkeeping": receipt})
        finally:
            admission.Admission.after_native_push = original_hook
            light.data.use_shadow = shadow

        # A provider's independent manager push is not this call's trusted
        # notification, even though its undo window advances by exactly one.
        temporary_scene = bpy.data.scenes.new("Owned Unrelated Push Scene")
        bpy.context.window.scene = temporary_scene
        manager = checkpoint.CheckpointManager()
        runtime.checkpoints = runtime.executor.checkpoints = manager
        temporary_scene[checkpoint.MARKER_KEY] = manager._prefix + "0" * 32
        marker = temporary_scene[checkpoint.MARKER_KEY]
        no_active = runtime.executor.execute_request(Request("owned-null-active", "scene.configure",
            {"scene_name": temporary_scene.name, "use_gravity": False}))
        assert not no_active.ok and no_active.error["code"] == "NOT_IMPLEMENTED", no_active.error
        assert manager._window.position == 0 and manager._pending is None
        assert temporary_scene[checkpoint.MARKER_KEY] == marker and temporary_scene.use_gravity
        cases.append({"case": "null-active-refusal", "completed_native_pushes": 0,
                      "marker_unchanged": True, "requested_edit_retained": False})
        temporary_scene.collection.objects.link(mesh)
        bpy.context.view_layer.objects.active = mesh
        mesh.select_set(True)
        fired = [False]
        provider_receipts = []
        provider_pending = [None]
        entries = len(domain_entries)
        def unrelated_push():
            if not fired[0]:
                fired[0] = True
                assert manager.before_modification("Owned unrelated provider push")
                provider_pending[0] = manager._pending
                provider_receipts.append({"position": manager._window.position,
                    "pending_sequence": None if manager._pending is None else manager._pending.sequence,
                    "pending_label": None if manager._pending is None else manager._pending.label,
                    "scene_self": int(temporary_scene.user_of_id(temporary_scene)),
                    "particle_object": proof.token(temporary_scene.tool_settings.particle_edit.object)})
        provider_hook[0] = unrelated_push
        try:
            response = runtime.executor.execute_request(Request("owned-unrelated-push", "scene.configure",
                {"scene_name": temporary_scene.name, "use_gravity": False}))
            assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED", response.error
            assert fired[0] and manager._window.position == 1 and manager._pending is provider_pending[0] and manager._pending is not None, {
                "provider_receipts": provider_receipts, "fired": fired[0], "position": manager._window.position,
                "pending_sequence": None if manager._pending is None else manager._pending.sequence,
                "pending_label": None if manager._pending is None else manager._pending.label, "error": response.error}
            assert provider_receipts[0]["scene_self"] == 1
            assert provider_receipts[0]["particle_object"] == proof.token(mesh)
            assert temporary_scene.use_gravity and len(domain_entries) == entries
            cases.append({"case": "unrelated-provider-manager-push", "requested_handler_entered": False,
                          "provider_native_pushes": 1, "provider_recovery_record_retained": True})
        finally:
            provider_hook[0] = None
            bpy.context.window.scene = scene
            bpy.data.scenes.remove(temporary_scene)

        # The provider-backed stage cannot overwrite a newer reserved value.
        original_check = checkpoint._CheckpointGuard.check
        phase = [None]

        def stage_check(guard, next_write):
            phase[0] = next_write
            try:
                return original_check(guard, next_write)
            finally:
                phase[0] = None

        checkpoint._CheckpointGuard.check = stage_check
        try:
            for stage, completed in (("delete_marker", 0), ("set_marker", 1), ("native_undo_push", 2)):
                manager = fresh()
                fired = [False]
                newer = "owned newer reserved note " + stage

                def late_marker(stage=stage, fired=fired, newer=newer):
                    if phase[0] == stage and not fired[0]:
                        fired[0] = True
                        scene[checkpoint.MARKER_KEY] = newer

                provider_hook[0] = late_marker
                error = reject()
                assert fired[0] and scene[checkpoint.MARKER_KEY] == newer
                assert light.data.energy == initial_energy
                receipt = error.context["checkpoint_bookkeeping"]
                assert receipt["marker_writes_completed"] == completed
                assert receipt["native_snapshots_completed"] == 0 and receipt["next_write_rejected"] == stage
                cases.append({"case": "newer-marker-" + stage, "newer_value_preserved": True,
                              "checkpoint_bookkeeping": receipt})
        finally:
            checkpoint._CheckpointGuard.check = original_check

        # A known pre-handler admission rejection retains older editor history.
        manager = fresh()
        assert manager.before_modification("owned old editor control")
        retained = checkpoint.MeshEditSession(manager._pending, "owned-no-write-editor", scene.session_uid,
                                              mesh.session_uid, mesh.name)
        manager._editor_session, manager._pending = retained, None
        marker = scene[checkpoint.MARKER_KEY]
        before_counter = dict(counters)
        add_driver("existing-before-factory")
        reject()
        assert counters == before_counter and scene[checkpoint.MARKER_KEY] == marker
        assert manager._editor_session is retained and light.data.energy == initial_energy
        tree.animation_data_clear()
        cases.append({"case": "existing-driver-retains-editor", "driver_callbacks": 0,
                      "marker_unchanged": True, "editor_record_retained": True})

        assert proof.session(bpy) == initial_context
        print("BLENDER_SCENE_CHECKPOINT_ADMISSION_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "cases": cases, "context_preserved": True, "project_saved": False,
            "user_preferences_saved": False, "actual_mesh_edit_recovery_acceptance": False,
            "windows_or_release_acceptance": False}, sort_keys=True))
    finally:
        provider_hook[0] = None
        tree.animation_data_clear()
        bpy.app.driver_namespace.pop(namespace, None)
        if hasattr(scene, "compositing_node_group"):
            scene.compositing_node_group = original_compositor
            bpy.data.node_groups.remove(tree)
        else:
            tree.nodes.clear()
            scene.use_nodes = original_use_nodes
        light.data.energy = initial_energy
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
