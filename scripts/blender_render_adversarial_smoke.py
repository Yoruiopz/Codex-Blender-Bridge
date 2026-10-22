"""Actual RNA boundaries, controlled faults, and tiny native render effects."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

from blender_codex_bridge import render_scope_profile, render_staging  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.preferences import get_preferences  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tool_registry import ToolContext  # noqa: E402
from blender_codex_bridge.tools import render  # noqa: E402
from blender_codex_bridge.tools._render_boundary import Boundary  # noqa: E402


def denied(callback, code=None):
    try:
        callback()
    except BridgeError as error:
        assert code is None or error.code == code, error.to_dict()
        # Keep structured receipts, not RNA-bearing traceback/cause cycles
        # across later owned-ID fixture cleanup or native database teardown.
        error.__traceback__ = error.__context__ = error.__cause__ = None
        return error
    raise AssertionError("Expected explicit refusal")


def settings(scene):
    return tuple(
        getattr(scene.render, name)
        for name in (
            "filepath",
            "resolution_x",
            "resolution_y",
            "resolution_percentage",
            "use_border",
            "use_crop_to_border",
        )
    )


def getter_for(calls):
    def getter(_owner):
        calls.append(True)
        return 1.0

    return getter


def differences(before, after):
    result = []

    def compare(left, right, path=""):
        if left == right or len(result) >= 20:
            return
        if (
            isinstance(left, (tuple, list))
            and isinstance(right, (tuple, list))
            and len(left) == len(right)
        ):
            for i, (a, b) in enumerate(zip(left, right, strict=True)):
                compare(a, b, path + "/" + str(i))
        else:
            result.append({"path": path, "before": left, "after": right})

    compare(before, after)
    return result


def main():
    if bpy.app.build_hash == b"d13f752e3b9c":
        sys.path.insert(0, str(ROOT / "scripts"))
        from blender_render_checkpoint_probe_smoke import main as refusal_probe

        refusal_probe("BLENDER_RENDER_ADVERSARIAL_OK ")
        return
    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
    records = []
    try:
        runtime, scene = get_runtime(), bpy.context.scene
        grants, provider_hook = {p.value: True for p in Permission}, [None]

        def provider():
            if provider_hook[0]:
                provider_hook[0]()
            return grants

        permissions = PermissionManager(provider)
        runtime.permissions = runtime.executor.permissions = permissions
        runtime.registry.enable_toolset("render")
        runtime.dispatch(
            "render.configure",
            {
                "scene_name": scene.name,
                "width": 16,
                "height": 16,
                "samples": 1,
                "resolution_percentage": 100,
            },
        )

        def context(method="render.configure"):
            queue = QueuedRequest(Request(id="render-native-boundary", method=method))
            assert queue.try_start()
            return ToolContext(
                runtime.state,
                permissions,
                runtime.registry,
                runtime.checkpoints,
                check_cancelled=queue.check_active,
                check_final_request=lambda: QueuedRequest.check_active(queue),
            ), queue

        baseline = settings(scene)
        grants["CAPTURE_VIEWPORT"] = False
        denied(
            lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
            "PERMISSION_DENIED",
        )
        assert settings(scene) == baseline
        grants["CAPTURE_VIEWPORT"] = True
        records.append({"case": "registered_capture_permission_denial", "no_owned_write": True})

        # Controlled injections run around actual native RNA reads and setters.
        # They are fixture hooks, never a claim that Blender setters call Python.
        for fault, code in [
            ("cancel", "TIMEOUT"),
            ("deadline", "TIMEOUT"),
            ("pause", "AGENT_PAUSED"),
            ("stop", "EMERGENCY_STOPPED"),
            ("permission", "PERMISSION_DENIED"),
            ("toolset", "TOOLSET_DISABLED"),
            ("manual", "OPERATION_FAILED"),
        ]:
            ctx, queue = context()
            boundary = Boundary(
                ctx,
                bpy,
                scene,
                "render.configure",
                [(scene.render, "resolution_x", 32), (scene.render, "resolution_y", 48)],
            )
            read = boundary.read
            fired = [False]

            def injected(owner, name, *, fault=fault, read=read, fired=fired, queue=queue):
                result = read(owner, name)
                if not fired[0] and name == "resolution_x" and result == 32:
                    fired[0] = True
                    if fault == "cancel":
                        queue.cancel_pending(BridgeError("TIMEOUT", "controlled disconnect"))
                    elif fault == "deadline":
                        queue.deadline = 0
                    elif fault == "pause":
                        runtime.state.set_paused(True)
                    elif fault == "stop":
                        runtime.state.set_emergency_stopped(True)
                    elif fault == "permission":
                        grants["EDIT_RENDER"] = False
                    elif fault == "toolset":
                        runtime.registry.disable_toolset("render")
                    else:
                        scene.render.resolution_x = 77
                return result

            boundary.read = injected
            denied(boundary.apply, code)
            recovery = boundary.restore()
            assert not recovery["restored"] and scene.render.resolution_y == 16
            assert scene.render.resolution_x == (77 if fault == "manual" else 32)
            records.append(
                {
                    "case": "actual_rna_" + fault + "_after_first_owned_setter",
                    "recovery": recovery,
                    "retained_width": scene.render.resolution_x,
                    "second_setter_blocked": True,
                }
            )
            runtime.state.set_paused(False)
            runtime.state.set_emergency_stopped(False)
            runtime.registry.enable_toolset("render")
            grants["EDIT_RENDER"] = True
            scene.render.resolution_x = scene.render.resolution_y = 16  # Explicit fixture cleanup.

        ctx, queue = context()
        boundary = Boundary(
            ctx, bpy, scene, "render.configure", [(scene.render, "resolution_x", 32)]
        )
        snapshot = render_scope_profile.snapshot
        armed = [True]

        def after_cas(*args, **kwargs):
            result = snapshot(*args, **kwargs)
            if armed[0]:
                armed[0] = False
                queue.cancel_pending(BridgeError("TIMEOUT", "controlled cancel after complete CAS"))
            return result

        render_scope_profile.snapshot = after_cas
        try:
            denied(boundary.apply, "TIMEOUT")
            assert scene.render.resolution_x == 16
        finally:
            render_scope_profile.snapshot = snapshot
        records.append({"case": "pure_terminal_cancel_after_complete_cas", "no_owned_write": True})

        material = bpy.data.materials.get("Material")
        principled = next(
            n for n in material.node_tree.nodes if n.bl_rna.identifier == "ShaderNodeBsdfPrincipled"
        )
        ior = next(s for s in principled.inputs if s.identifier == "Subsurface IOR")
        other = next(s for s in principled.inputs if s.identifier == "Roughness")
        for target, label in [(ior, "derived_availability"), (other, "unrelated_availability")]:
            for when in ("constructor_provider", "later_provider"):
                original = target.enabled
                ctx, _ = context("render.execute")

                def interfere(target=target, original=original):
                    provider_hook[0] = None
                    target.enabled = not original

                try:
                    if when == "constructor_provider":
                        provider_hook[0] = interfere
                        denied(
                            lambda ctx=ctx: Boundary(
                                ctx,
                                bpy,
                                scene,
                                "render.execute",
                                [(scene.render, "resolution_x", 32)],
                            ),
                            "OPERATION_FAILED",
                        )
                    else:
                        boundary = Boundary(
                            ctx, bpy, scene, "render.execute", [(scene.render, "resolution_x", 32)]
                        )
                        provider_hook[0] = interfere
                        denied(boundary.apply, "OPERATION_FAILED")
                    assert target.enabled != original and scene.render.resolution_x == 16
                finally:
                    provider_hook[0] = None
                    target.enabled = original
                records.append({"case": label + "_" + when, "no_owned_write": True})

        for kind in (
            "Scene",
            "RenderSettings",
            "ImageFormatSettings",
            "SceneEEVEE",
            "RaytraceEEVEE",
            "Object",
            "Mesh",
            "Material",
            "World",
            "PointLight",
            "ViewLayer",
            "ViewLayerEEVEE",
            "ShaderNodeTree",
            "ShaderNodeBsdfPrincipled",
            "NodeSocketFloatFactor",
            "MaterialSlot",
            "ObjectLightLinking",
            "UnitSettings",
            "UVLoopLayers",
        ):
            owner_type, calls = getattr(bpy.types, kind), []

            owner_type.bridge_render_unreviewed = bpy.props.FloatProperty(get=getter_for(calls))
            before = settings(scene)
            try:
                registered = (
                    owner_type.bl_rna.properties.get("bridge_render_unreviewed") is not None
                )
                if registered:
                    denied(
                        lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
                        "NOT_IMPLEMENTED",
                    )
                assert calls == [] and settings(scene) == before, (kind, calls)
            finally:
                delattr(owner_type, "bridge_render_unreviewed")
            records.append(
                {
                    "case": "runtime_getter_" + kind,
                    "getter_calls": len(calls),
                    "native_rna_registration_supported": registered,
                    "no_owned_write": True,
                }
            )

        cube = next(obj for obj in scene.objects if obj.type == "MESH")
        mesh = cube.data
        mesh.materials.append(bpy.data.materials.get("Dots Stroke"))
        slot = cube.material_slots[len(cube.material_slots) - 1]
        slot.link = "OBJECT"
        slot.material = bpy.data.materials.get("Dots Stroke")
        extra_uv = mesh.uv_layers.new(name="RenderProtectedUV")
        mesh.uv_layers.active_index = 0
        for label, owner, name, changed in [
            ("nonactive_object_material_binding", slot, "material", material),
            (
                "light_linking_collection",
                bpy.data.objects.get("Light").light_linking,
                "receiver_collection",
                bpy.data.collections[0],
            ),
            ("uv_active_selector", mesh.uv_layers, "active_index", 1),
            ("scene_unit_scale", scene.unit_settings, "scale_length", 2.0),
            (
                "collection_object_light_linking",
                bpy.data.collections[0]
                .collection_objects[
                    next(
                        i
                        for i, member in enumerate(bpy.data.collections[0].objects)
                        if member == cube
                    )
                ]
                .light_linking,
                "link_state",
                "EXCLUDE",
            ),
            (
                "scene_root_child_light_linking",
                scene.collection.collection_children[0].light_linking,
                "link_state",
                "EXCLUDE",
            ),
        ]:
            original = getattr(owner, name)
            ctx, _ = context()
            boundary = Boundary(
                ctx, bpy, scene, "render.configure", [(scene.render, "resolution_x", 32)]
            )

            def interfere(owner=owner, name=name, changed=changed):
                provider_hook[0] = None
                setattr(owner, name, changed)

            provider_hook[0] = interfere
            try:
                denied(boundary.apply, "OPERATION_FAILED")
                assert getattr(owner, name) == changed and scene.render.resolution_x == 16
                assert not boundary.restore()["restored"]
            finally:
                provider_hook[0] = None
                setattr(owner, name, original)
            records.append(
                {
                    "case": "provider_" + label,
                    "newer_dependency_preserved": True,
                    "no_owned_write": True,
                }
            )
        mesh.uv_layers.remove(extra_uv)
        mesh.materials.pop(index=len(mesh.materials) - 1)

        copied = mesh.copy()
        cube.data = copied
        copied.normals_split_custom_set([(0.0, 0.0, 1.0)] * len(copied.loops))
        try:
            assert copied.has_custom_normals
            before = settings(scene)
            denied(
                lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
                "NOT_IMPLEMENTED",
            )
            assert settings(scene) == before
        finally:
            cube.data = mesh
            bpy.data.meshes.remove(copied)
        records.append({"case": "authored_custom_split_normals_refused", "no_owned_write": True})

        callbacks = []
        wrong_id = (
            "BLENDER_EEVEE" if bpy.app.build_hash == b"62c1db4208e8" else "BLENDER_EEVEE_NEXT"
        )

        class OtherVersionEngine(bpy.types.RenderEngine):
            bl_idname = wrong_id
            bl_label = "Unreviewed opposite-version engine"

            def render(self, _depsgraph):
                callbacks.append("render")

            def update(self, _data, _depsgraph):
                callbacks.append("update")

            def update_render_passes(self, _scene, _layer):
                callbacks.append("passes")

        bpy.utils.register_class(OtherVersionEngine)
        original_engine = scene.render.engine
        marker = scene.get("_codex_bridge_undo_marker")
        before = settings(scene)
        try:
            # The dynamic engine enum may expose no items through static RNA.
            # Confirm the actual registered Python engine class independently.
            assert bpy.types.RenderEngine.bl_rna_get_subclass_py(
                OtherVersionEngine.bl_rna.identifier
            ) is OtherVersionEngine
            available = render._enum_values(scene.render, "engine")
            selectable = wrong_id in available
            denied(
                lambda: runtime.dispatch(
                    "render.configure", {"scene_name": scene.name, "engine": wrong_id}
                ),
                "NOT_IMPLEMENTED" if selectable or not available else "INVALID_ARGUMENT",
            )
            assert (
                callbacks == []
                and settings(scene) == before
                and scene.render.engine == original_engine
            )
            assert scene.get("_codex_bridge_undo_marker") == marker
            if selectable:
                scene.render.engine = wrong_id  # Explicit fixture selection, not a tool-owned setter.
                prior = list(callbacks)
                denied(
                    lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
                    "NOT_IMPLEMENTED",
                )
                assert callbacks == prior and settings(scene) == before
            records.append(
                {
                    "case": "registered_opposite_version_python_engine",
                    "engine": wrong_id,
                    "engine_enum": sorted(available),
                    "actual_engine_selection_supported": selectable,
                    "actual_execute_refusal_verified": selectable,
                    "callbacks_during_planned_engine_dispatch": 0,
                    "callbacks_during_execute_dispatch": 0 if selectable else None,
                    "render_calls": callbacks.count("render"),
                    "checkpoint_marker_preserved": True,
                }
            )
        finally:
            scene.render.engine = original_engine
            bpy.utils.unregister_class(OtherVersionEngine)

        for label, owner, data_path in [
            ("unused_material", bpy.data.materials.new("RenderUnusedDriver"), "diffuse_color"),
            ("unused_world", bpy.data.worlds.new("RenderUnusedWorld"), "color"),
            (
                "embedded_tree",
                material.node_tree,
                'nodes["Principled BSDF"].inputs["Roughness"].default_value',
            ),
        ]:
            calls = []
            bpy.app.driver_namespace["bridge_render_driver_probe"] = lambda calls=calls: (
                calls.append(True) or 0.5
            )
            curve = (
                owner.driver_add(data_path, 0)
                if label != "embedded_tree"
                else owner.driver_add(data_path)
            )
            curve.driver.expression = "bridge_render_driver_probe()"
            prior = len(calls)
            try:
                denied(
                    lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
                    "NOT_IMPLEMENTED",
                )
                assert len(calls) == prior
            finally:
                owner.driver_remove(
                    data_path, 0
                ) if label != "embedded_tree" else owner.driver_remove(data_path)
                owner.animation_data_clear()
                if label == "unused_material":
                    bpy.data.materials.remove(owner)
                elif label == "unused_world":
                    bpy.data.worlds.remove(owner)
                bpy.app.driver_namespace.pop("bridge_render_driver_probe", None)
            records.append(
                {"case": label + "_driver", "evaluations_during_dispatch": len(calls) - prior}
            )

        # Actual native rendering, approved folder and atomic late-target race.
        prefs, link = get_preferences(), render_staging.os.link
        old_folder = prefs.asset_directory
        output = Path(tempfile.mkdtemp(prefix="render-boundary-acceptance-", dir=bpy.app.tempdir))
        target = output / "late-target.png"
        prefs.asset_directory = str(output)
        before = settings(scene)

        def race(source, destination):
            assert Path(destination) == target
            target.write_bytes(b"foreign target created immediately before link")
            return link(source, destination)

        render_staging.os.link = race
        original_init, captured = Boundary.__init__, []

        def record_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured.append(self)

        Boundary.__init__ = record_init
        try:
            error = denied(
                lambda: runtime.dispatch(
                    "render.execute", {"scene_name": scene.name, "filepath": str(target)}
                ),
                "INVALID_ARGUMENT",
            )
            assert target.read_bytes() == b"foreign target created immediately before link"
            assert settings(scene) == before
            assert (
                error.context["native_render_completed"]
                and error.context["render_settings_recovery"]["restored"]
            )
            assert error.context["external_effects"]["file_published"] is False
            records.append(
                {
                    "case": "native_render_atomic_no_clobber_race",
                    "error": error.to_dict(),
                    "foreign_file_preserved": True,
                    "settings_preserved": True,
                }
            )
        except Exception:
            if captured:
                boundary = captured[-1]
                print(
                    "NATIVE_RENDER_ADVERSARIAL_DRIFT "
                    + json.dumps(
                        differences(
                            boundary.native_protected
                            if boundary.native_completed
                            else boundary.protected,
                            render_scope_profile.snapshot(bpy, scene, boundary.owned),
                        )
                    ),
                    flush=True,
                )
            raise
        finally:
            Boundary.__init__ = original_init
            render_staging.os.link = link
            prefs.asset_directory = old_folder

        # Even an independently predicted derived flag cannot be changed by a
        # permission provider after the observed native outcome has been sealed.
        seal, before = Boundary.seal_native_outcome, settings(scene)
        sealed_flag = [None]

        def seal_then_interfere(self):
            seal(self)
            sealed_flag[0] = ior.enabled

            def interfere():
                provider_hook[0] = None
                ior.enabled = not sealed_flag[0]

            provider_hook[0] = interfere

        Boundary.seal_native_outcome = seal_then_interfere
        try:
            error = denied(
                lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
                "OPERATION_FAILED",
            )
            assert (
                error.context["native_render_completed"]
                and error.context["native_dependency_evidence"]["outcome_sealed"]
            )
            assert not error.context["render_settings_recovery"]["restored"]
            assert ior.enabled != sealed_flag[0]
            assert error.context["external_effects"]["file_published"] is False
            records.append(
                {
                    "case": "derived_socket_provider_change_after_native_seal",
                    "error": error.to_dict(),
                    "newer_flag_preserved": True,
                    "product_recovery_blocked": True,
                }
            )
        finally:
            Boundary.seal_native_outcome = seal
            provider_hook[0] = None
            ior.enabled = sealed_flag[0]
            for name, original in zip(
                (
                    "filepath",
                    "resolution_x",
                    "resolution_y",
                    "resolution_percentage",
                    "use_border",
                    "use_crop_to_border",
                ),
                before,
                strict=True,
            ):
                setattr(
                    scene.render, name, original
                )  # Explicit fixture cleanup, not product recovery.

        # The real native operator completes inside a controlled failing wrapper.
        native, original_require = bpy.ops.render.render, render.require_blender
        primary = BridgeError(
            "BLENDER_CONTEXT_ERROR", "controlled failure after actual native effect"
        )

        class NativeFailure:
            def poll(self):
                return native.poll()

            def __call__(self, **kwargs):
                assert native(**kwargs) == {"FINISHED"}
                raise primary

        proxy = SimpleNamespace(
            app=bpy.app,
            data=bpy.data,
            context=bpy.context,
            types=bpy.types,
            ops=SimpleNamespace(render=SimpleNamespace(render=NativeFailure())),
        )
        render.require_blender = lambda: proxy
        try:
            error = denied(
                lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
                "BLENDER_CONTEXT_ERROR",
            )
            assert error is primary and error.context["native_render_started"]
            assert (
                not error.context["native_render_completed"]
                and error.context["render_result_replacement_possible"]
            )
            assert error.context["external_effects"]["render_result_replaced"] is None
            assert error.context["external_effects"]["render_result_replacement_possible"]
            assert (
                error.context["native_blocking_seconds"] >= 0
                and error.context["native_call_interruptible"] is False
            )
            retained = error.context["external_effects"]["retained_staging_path"]
            assert retained and Path(retained).is_file()
            records.append(
                {"case": "actual_native_effect_then_controlled_failure", "error": error.to_dict()}
            )
        finally:
            render.require_blender = original_require

        before = settings(scene)
        if hasattr(scene, "compositing_node_group"):
            tree = bpy.data.node_groups.new("UnreviewedRenderCompositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        else:
            scene.use_nodes = True
            tree = scene.node_tree
        tree.nodes.new("CompositorNodeOutputFile")
        compositor_refusal = denied(
            lambda: runtime.dispatch("render.execute", {"scene_name": scene.name}),
            "NOT_IMPLEMENTED",
        )
        assert settings(scene) == before
        records.append(
            {
                "case": "compositor_file_output_refused",
                "refusal": compositor_refusal.to_dict(),
                "direct_compositor_reader_reached": "Compositor graphs" in compositor_refusal.message,
                "compositor_rendering_accepted": False,
                "no_owned_write": True,
                "native_operator_not_started": True,
            }
        )
        print(
            "BLENDER_RENDER_ADVERSARIAL_OK "
            + json.dumps(
                {
                    "version": bpy.app.version_string,
                    "build_hash": bpy.app.build_hash.decode(),
                    "cases": records,
                }
            )
        )
    except Exception:
        print("NATIVE_RENDER_PARTIAL_CASES " + json.dumps(records), flush=True)
        raise
    finally:
        bpy.ops.preferences.addon_disable(module="blender_codex_bridge")


if __name__ == "__main__":
    main()
