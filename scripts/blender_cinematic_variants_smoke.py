"""Typed cinematic variant writer/reader, matched renders and native recovery."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"addon"))
sys.path.insert(0, str(ROOT/"scripts"))
import blender_codex_bridge  # noqa: E402
from blender_cinematic_variant_probe_smoke import camera_point, image_bytes  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError, ErrorCode  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import scene_variants as domain  # noqa: E402
from native_camera_evidence import compare_rgba8  # noqa: E402


def setup():
    scene = bpy.context.scene
    cube = bpy.data.objects["Cube"]
    cube.name = "Protected Hero Prop"
    material = bpy.data.materials.new("Protected Procedural Metal")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (.12, .35, .55, 1.)
    shader.inputs["Metallic"].default_value = .15
    shader.inputs["Roughness"].default_value = .35
    cube.data.materials.clear()
    cube.data.materials.append(material)
    density = cube.data.attributes.new("Protected Density", "FLOAT", "POINT")
    for index, item in enumerate(density.data):
        item.value = .125*index
    cube.data.uv_layers.new(name="Protected UV")
    alias = bpy.data.objects.new("Protected Shared Consumer", cube.data)
    alias.location = (3., 0., 0.)
    scene.collection.objects.link(alias)
    mesh = bpy.data.meshes.new("Protected Floor Data")
    mesh.from_pydata([(-5., -5., -1.01), (5., -5., -1.01), (5., 5., -1.01), (-5., 5., -1.01)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new("Protected Floor", mesh)
    scene.collection.objects.link(floor)
    camera = bpy.data.objects["Camera"]
    camera.name = "Variant Camera"
    camera_point(camera, (5., -6., 4.))
    alternate = bpy.data.objects.new("Protected Active Camera", bpy.data.cameras.new("Protected Active Camera Data"))
    scene.collection.objects.link(alternate)
    camera_point(alternate, (-5., -6., 3.))
    scene.camera = alternate
    lights = [bpy.data.objects["Light"]]
    lights[0].name = "Variant Key"
    lights[0].data.type = "AREA"
    for name in ("Variant Fill",):
        light = bpy.data.objects.new(name, bpy.data.lights.new(name+" Data", "AREA"))
        scene.collection.objects.link(light)
        lights.append(light)
    for light, location, energy, color in zip(lights, ((4., -4., 6.), (-4., -1., 3.)), (750., 300.), ((1., .72, .4), (.35, .6, 1.)), strict=True):
        camera_point(light, location)
        light.data.energy, light.data.color = energy, color
        light.data.shape, light.data.size, light.data.size_y = "RECTANGLE", 4., 2.5
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (.05, .05, .05, 1.)
    background.inputs["Strength"].default_value = .25
    bpy.context.view_layer.update()
    print("CINEMATIC_LIGHT_GRAPH_SCHEMA "+json.dumps([{ "name": obj.name, "use_nodes": obj.data.use_nodes,
        "nodes": None if obj.data.node_tree is None else [node.bl_idname for node in obj.data.node_tree.nodes]}
        for obj in lights]), flush=True)
    print("CINEMATIC_SCENE_DEFAULT_FLAGS "+json.dumps({"use_nodes": scene.use_nodes,
        "sequence_editor": bool(scene.sequence_editor), "markers": len(scene.timeline_markers),
        "objects": len(scene.objects), "multiview": scene.render.use_multiview,
        "use_curve_mapping": scene.view_settings.use_curve_mapping,
        "node_tree": None if getattr(scene, "node_tree", None) is None else [node.bl_idname for node in scene.node_tree.nodes],
        "compositing_node_group": str(getattr(scene, "compositing_node_group", None))}), flush=True)
    return camera, lights, sorted(obj.name for obj in scene.objects if obj.type == "MESH")


def cas(runtime):
    state = runtime.dispatch("scene.variant.inspect")
    return {"expected_library_revision": state["revision"], "expected_library_fingerprint": state["library_fingerprint"]}


def numeric():
    camera = bpy.data.objects["Variant Camera"]
    lights = [bpy.data.objects[name] for name in ("Variant Key", "Variant Fill")]
    return [domain._control(obj) for obj in (camera, *lights)]


def restore_native(values):
    for value in values:
        obj = bpy.data.objects[value["object_name"]]
        obj.location, obj.scale = value["location"], value["scale"]
        obj.rotation_quaternion = value["rotation"]
        for key, setting in value["settings"].items():
            owner, attr = (obj.data.dof, key[4:]) if key.startswith("dof.") else (obj.data, key)
            setattr(owner, attr, setting)
    bpy.context.view_layer.update()



def provider_boundary_faults(runtime, params, a, b):
    """Actual RNA boundaries: a granting provider may also change live state."""
    context = runtime.executor.context
    manager = context.permissions
    outcomes = []
    for recovery in (False, True):
        for signal in ("paused", "emergency_stopped", "mode", "toolset", "queued_cancel", "queued_expiry", "disconnect", "handoff_rejected"):
            prepared = domain._prepare(context, params, domain.APPLY)
            transaction = domain._Transaction(context, prepared, domain.APPLY)
            if recovery:
                transaction.run()
                assert numeric() == b
            expected = numeric()
            original_source, poisoned = manager._source, [False]
            lifetime = RequestLifetime(ConnectionLifetime())
            queued = QueuedRequest(Request(id="cinematic-native-"+signal, method="scene.variant.apply", params=params, _lifecycle=lifetime))
            assert queued.try_start()
            original_cancel, original_lifetime = context.check_cancelled, context.request_lifecycle
            context.check_cancelled, context.request_lifecycle = queued.check_active, lifetime

            def provider(poisoned=poisoned, signal=signal, original_source=original_source, queued=queued, lifetime=lifetime):
                # The transaction is already prepared; poison the next real
                # granting boundary, independent of permissions in the batch.
                if not poisoned[0]:
                    poisoned[0] = True
                    if signal == "mode":
                        assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
                    elif signal in {"paused", "emergency_stopped"}:
                        getattr(runtime.state, "set_"+signal)(True)
                    elif signal == "toolset":
                        runtime.registry.disable_toolset("scene_edit")
                    elif signal == "queued_cancel":
                        queued.cancel_pending(BridgeError("TIMEOUT", "Canonical cinematic request canceled"))
                    elif signal == "queued_expiry":
                        queued.deadline = 0
                    elif signal == "disconnect":
                        lifetime.connection.disconnected.set()
                    else:
                        lifetime.acknowledge(False)
                return original_source()

            manager._source = provider
            try:
                try:
                    (transaction.restore if recovery else transaction.run)()
                    raise AssertionError("Provider-induced stop/context change allowed a write")
                except BridgeError as error:
                    wanted = {"paused": "AGENT_PAUSED", "emergency_stopped": "EMERGENCY_STOPPED", "mode": "INVALID_MODE",
                        "toolset": "TOOLSET_DISABLED"}.get(signal, "TIMEOUT")
                    assert error.code == wanted, error.to_dict()
                    if recovery:
                        failure = domain._failure(transaction, error)
                        assert failure.context["possible_mutation"] and not failure.context["rollback_verified"]
                assert poisoned[0] and numeric() == expected
                if not recovery:
                    assert transaction.attempted == []
                if signal in {"paused", "emergency_stopped"}:
                    assert runtime.dispatch("scene.variant.inspect")["variants"]
            finally:
                manager._source = original_source
                context.check_cancelled, context.request_lifecycle = original_cancel, original_lifetime
                runtime.registry.enable_toolset("scene_edit")
                runtime.state.set_paused(False)
                runtime.state.set_emergency_stopped(False)
                if bpy.context.mode != "OBJECT":
                    assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}
            if recovery:
                transaction.context = runtime.executor.context
                transaction.restore()
            assert numeric() == a
            outcomes.append({"signal": signal, "recovery": recovery,
                "provider_granted_permissions": True, "zero_unpermitted_control_writes": True,
                "canonical_queued_request_and_lifetime": True,
                "read_only_inspection_available": signal in {"paused", "emergency_stopped"},
                "explicit_fresh_authority_restores_original_controls": True})
    return outcomes


def writer(runtime, grants, bundle):
    camera, lights, protected = setup()
    a = numeric()
    denied_capture = {"label": "Denied scope", "camera_object": camera.name,
        "light_objects": [obj.name for obj in lights], "protected_objects": protected, **cas(runtime)}
    raw = bpy.context.scene.get(domain.records.PROPERTY)
    grants[Permission.EDIT_SCENE.value] = False
    try:
        runtime.dispatch("scene.variant.capture", denied_capture)
        raise AssertionError("Permission-denied capture unexpectedly succeeded")
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED"
    finally:
        grants[Permission.EDIT_SCENE.value] = True
    assert bpy.context.scene.get(domain.records.PROPERTY) == raw and numeric() == a
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        try:
            runtime.dispatch("scene.variant.capture", denied_capture)
            raise AssertionError("Edit Mode capture unexpectedly succeeded")
        except BridgeError as error:
            assert error.code == "INVALID_MODE"
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    assert bpy.context.scene.get(domain.records.PROPERTY) == raw and numeric() == a
    profile_a = domain._profile(bpy, [bpy.data.objects[value["object_name"]] for value in a], protected)
    first = runtime.dispatch("scene.variant.capture", {"label": "Warm wide", "camera_object": camera.name,
        "light_objects": [obj.name for obj in lights], "protected_objects": protected, **cas(runtime)})
    camera_point(camera, (4., -5., 3.))
    camera.data.lens, camera.data.shift_x = 62., .08
    lights[0].data.energy, lights[0].data.color = 1000., (.25, .55, 1.)
    lights[1].data.energy, lights[1].data.color = 175., (1., .4, .15)
    bpy.context.view_layer.update()
    b = numeric()
    profile_b = domain._profile(bpy, [bpy.data.objects[value["object_name"]] for value in b], protected)
    assert profile_a == profile_b  # Owned camera/light changes do not alter the protected profile.
    second = runtime.dispatch("scene.variant.capture", {"label": "Cool close-up", "camera_object": camera.name,
        "light_objects": [obj.name for obj in lights], "protected_objects": protected, **cas(runtime)})
    restore_native(a)
    selection = sorted(obj.name for obj in bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active.name
    scene_camera = bpy.context.scene.camera.name
    profile = domain._profile(bpy, [bpy.data.objects[value["object_name"]] for value in a], protected)
    params_preview = {"variant_id": second["variant"]["variant_id"], **cas(runtime)}
    background = camera.data.background_images.new()
    try:
        runtime.dispatch("scene.variant.preview", params_preview)
        raise AssertionError("An unreviewed camera background was omitted")
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    finally:
        camera.data.background_images.remove(background)
    assert bpy.ops.scene.view_layer_add_aov() == {"FINISHED"}
    assert len(bpy.context.view_layer.aovs) == 1
    try:
        runtime.dispatch("scene.variant.preview", params_preview)
        raise AssertionError("An unreviewed view-layer AOV was omitted")
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    finally:
        assert bpy.ops.scene.view_layer_remove_aov() == {"FINISHED"}
        assert len(bpy.context.view_layer.aovs) == 0
    hero = bpy.data.objects["Protected Hero Prop"]
    hero["Unreviewed Native Reference"] = bpy.data.objects["Protected Shared Consumer"]
    try:
        runtime.dispatch("scene.variant.preview", params_preview)
        raise AssertionError("An unreviewed protected custom ID reference was omitted")
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
    finally:
        del hero["Unreviewed Native Reference"]
    density = hero.data.attributes["Protected Density"].data[0]
    original_density = density.value
    density.value = .875
    try:
        runtime.dispatch("scene.variant.preview", params_preview)
        raise AssertionError("Changed protected mesh attribute unexpectedly accepted")
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    finally:
        density.value = original_density
    raw = bpy.context.scene[domain.records.PROPERTY]
    bpy.context.scene[domain.records.PROPERTY] = " "+raw
    try:
        runtime.dispatch("scene.variant.preview", params_preview)
        raise AssertionError("Changed raw JSON unexpectedly accepted old CAS")
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    finally:
        bpy.context.scene[domain.records.PROPERTY] = raw
    assert numeric() == a
    preview = runtime.dispatch("scene.variant.preview", params_preview)
    assert numeric() == a and bpy.context.scene.camera.name == scene_camera
    assert sorted(obj.name for obj in bpy.context.selected_objects) == selection
    assert bpy.context.view_layer.objects.active.name == active
    _, _, pixels_a = image_bytes(Path(preview["current_capture"]["filepath"]))
    _, _, pixels_b = image_bytes(Path(preview["candidate_capture"]["filepath"]))
    changed = compare_rgba8(pixels_a, pixels_b, 384, 256)
    assert changed["changed_pixels"] > 384*256//10
    params = {"variant_id": second["variant"]["variant_id"], **cas(runtime), "expected_fingerprint": preview["fingerprint"]}
    provider_faults = provider_boundary_faults(runtime, params, a, b)
    # Failure immediately after an actual native field write must compensate.
    original = domain._Transaction.validate

    def injected(self, expected, **kwargs):
        original(self, expected, **kwargs)
        if self.attempted and not kwargs.get("recovery"):
            raise BridgeError(ErrorCode.TIMEOUT, "Fixture injected late failure")

    domain._Transaction.validate = injected
    try:
        try:
            runtime.dispatch("scene.variant.apply", params)
            raise AssertionError("Injected apply unexpectedly succeeded")
        except BridgeError as error:
            assert error.context["execution_started"] and error.context["rollback_verified"]
    finally:
        domain._Transaction.validate = original
    assert numeric() == a
    fresh = runtime.dispatch("scene.variant.preview", {"variant_id": second["variant"]["variant_id"], **cas(runtime)})
    runtime.dispatch("scene.variant.apply", {**params, "expected_fingerprint": fresh["fingerprint"]})
    assert numeric() == b
    restored = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
    assert restored["snapshot_marker_verified"] and numeric() == a
    assert domain._profile(bpy, [bpy.data.objects[value["object_name"]] for value in a], protected) == profile
    # An explicit separate SAVE_PROJECT + ACCESS_EXTERNAL_FILES grant makes
    # persistence durable; capture/preview/apply never save implicitly.
    grants[Permission.SAVE_PROJECT.value] = grants[Permission.ACCESS_EXTERNAL_FILES.value] = True
    runtime.dispatch("project.save", {"filepath": str(bundle/"variants.blend")})
    grants[Permission.SAVE_PROJECT.value] = grants[Permission.ACCESS_EXTERNAL_FILES.value] = False
    expected = {"a": a, "b": b, "a_id": first["variant"]["variant_id"], "b_id": second["variant"]["variant_id"],
        "old_token": fresh["fingerprint"], "library": runtime.dispatch("scene.variant.inspect"),
        "protected": protected, "profile": profile, "writer_current_capture": preview["current_capture"],
        "changed": changed}
    (bundle/"variants-expected.json").write_text(json.dumps(expected), encoding="utf-8")
    return {"phase": "writer", "blender_version": bpy.app.version_string,
        "matched_full_image_comparison": changed, "late_failure_compensated": True,
        "native_undo_verified": True, "explicit_separate_project_save": True,
        "permission_denial_invalid_mode_protected_attribute_and_json_cas_verified": True,
        "protected_custom_native_reference_rejected": True,
        "camera_background_and_aov_dependencies_rejected": True,
        "granting_provider_boundary_faults": provider_faults,
        "protected_shared_mesh_material_uv_scalar_preserved": True, "captures": preview["external_effects"]["artifacts"]}


def reader(runtime, _grants, bundle):
    expected = json.loads((bundle/"variants-expected.json").read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(bundle/"variants.blend"), load_ui=False)
    assert numeric() == expected["a"]
    try:
        runtime.dispatch("scene.variant.inspect")
        raise AssertionError("Project metadata implicitly enabled the scene_edit toolset")
    except BridgeError as error:
        assert error.code == "TOOLSET_DISABLED"
    runtime.registry.enable_toolset("scene_edit")
    profile_reopened = domain._profile(bpy, [bpy.data.objects[value["object_name"]] for value in expected["a"]], expected["protected"])
    assert domain.records.digest(profile_reopened) == domain.records.digest(expected["profile"])
    library = runtime.dispatch("scene.variant.inspect")
    assert library["variants"] == expected["library"]["variants"]
    params = {"variant_id": expected["b_id"], **cas(runtime)}
    try:
        runtime.dispatch("scene.variant.apply", {**params, "expected_fingerprint": expected["old_token"]})
        raise AssertionError("Saved token granted permission to apply")
    except BridgeError as error:
        assert error.code == "INVALID_ARGUMENT"
    preview = runtime.dispatch("scene.variant.preview", params)
    assert numeric() == expected["a"]
    _, _, old_a = image_bytes(Path(expected["writer_current_capture"]["filepath"]))
    _, _, reopened_a = image_bytes(Path(preview["current_capture"]["filepath"]))
    reopen_comparison = compare_rgba8(old_a, reopened_a, 384, 256)
    assert reopen_comparison["changed_pixels"] == 0
    runtime.dispatch("scene.variant.apply", {**params, "expected_fingerprint": preview["fingerprint"]})
    assert numeric() == expected["b"]
    restore = runtime.dispatch("scene.variant.preview", {"variant_id": expected["a_id"], **cas(runtime)})
    runtime.dispatch("scene.variant.apply", {"variant_id": expected["a_id"], **cas(runtime), "expected_fingerprint": restore["fingerprint"]})
    assert numeric() == expected["a"]
    assert bpy.data.objects["Protected Hero Prop"].data == bpy.data.objects["Protected Shared Consumer"].data
    return {"phase": "reader", "blender_version": bpy.app.version_string,
        "fresh_process_library_and_exact_numeric_controls_verified": True,
        "stored_token_rejected_fresh_rebind_required": True, "full_rgba8_reopen_comparison": reopen_comparison,
        "a_b_a_typed_workflow_verified": True, "project_saved_by_reader": False,
        "captures": preview["external_effects"]["artifacts"]+restore["external_effects"]["artifacts"],
        "universal_artist_protection_reference_understanding_complete": False}


def run():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
        parser.add_argument("--bridge-bundle", type=Path, required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {permission.value: permission in (Permission.INSPECT_SCENE, Permission.EDIT_SCENE,
            Permission.TRANSFORM_OBJECTS, Permission.CAPTURE_VIEWPORT) for permission in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        runtime.registry.enable_toolset("scene_edit")
        result = (writer if args.bridge_phase == "writer" else reader)(runtime, grants, args.bridge_bundle.resolve(strict=True))
        result.update(process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid())
        print("BLENDER_CINEMATIC_VARIANTS_"+args.bridge_phase.upper()+"_OK "+json.dumps(result), flush=True)
    except Exception as error:
        if isinstance(error, BridgeError):
            print("CINEMATIC_VARIANTS_FAILURE "+json.dumps(error.to_dict()), flush=True)
        traceback.print_exc()
    finally:
        bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=.5)
    return None


bpy.app.timers.register(run, first_interval=1.)
