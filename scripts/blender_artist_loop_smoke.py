"""Small disposable native artist loop; run only through the isolated runner."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.task_plans import SCENE_PROPERTY, clear_task_plans, get_task_plans  # noqa: E402


def main():
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    manager = PermissionManager(lambda: grants)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("objects")
    call = runtime.dispatch
    scene, window = bpy.context.scene, bpy.context.window
    mesh = bpy.data.meshes.new("Artist Working Geometry")
    mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
    work = bpy.data.objects.new("Artist Working Prop", mesh)
    scene.collection.objects.link(work)
    protected = bpy.data.objects["Cube"]
    bundled_ui_index = work.active_selection_set
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    work.select_set(True)
    bpy.context.view_layer.objects.active = work
    bpy.context.view_layer.update()
    protected_before = tuple(protected.location), tuple(tuple(vertex.co) for vertex in protected.data.vertices)
    checkpoints = []
    original_checkpoint = runtime.checkpoints.before_modification
    def checkpoint(method, **kwargs):
        checkpoints.append(method)
        return original_checkpoint(method, **kwargs)
    runtime.checkpoints.before_modification = checkpoint
    plan = call("task.plan.set", {"goal": "Place and revise the selected prop while preserving Cube",
        "steps": [{"id": "place", "description": "Resolve, preview, compare and correct prop placement"}],
        "protected_objects": [protected.name]})
    revision = plan["plan"]["revision"]
    call("task.plan.persist", {"confirm": True, "expected_revision": revision})
    saved = scene[SCENE_PROPERTY]
    assert "protection_generation" not in saved and "reference_id" not in saved
    captured = call("task.plan.capture", {"fields": ["transforms", "hierarchy", "mesh_geometry", "material_slots"]})
    assert captured["baseline"]["coverage_complete"], captured
    armed = call("task.plan.enforce", {"enabled": True, "expected_revision": revision})
    assert armed["protected_scope_enforced"] and armed["protection_audit_operation_id"]

    def deny(code, method, **params):
        try:
            call(method, params)
        except BridgeError as error:
            assert error.code == code, error.to_dict()
            return error
        raise AssertionError(f"Expected {method} to fail with {code}")

    def preview(location, scale=None):
        token = call("task.reference.resolve", {"source": "selection"})["reference_id"]
        params = {"reference_id": token, "expected_revision": revision, "location": location}
        if scale is not None:
            params["scale"] = scale
        return call("task.plan.preview_transform", params)

    # Native builtin descriptors pass; preview needs inspect authority only.
    grants[Permission.TRANSFORM_OBJECTS.value] = False
    result = preview([1., 2., 3.])
    assert not result["scene_edited"] and not result["authority_granted"] and tuple(work.location) == (0., 0., 0.)
    deny("PERMISSION_DENIED", "task.plan.apply_preview", preview_id=result["preview_id"], expected_revision=revision)
    grants[Permission.TRANSFORM_OBJECTS.value] = True
    applied = call("task.plan.apply_preview", {"preview_id": result["preview_id"], "expected_revision": revision})
    assert applied["preview_consumed"] and tuple(work.location) == (1., 2., 3.)
    deny("INVALID_ARGUMENT", "task.plan.apply_preview", preview_id=result["preview_id"], expected_revision=revision)
    assert call("task.plan.compare")["evidence"]["status"] == "unchanged_within_scope"
    revision = call("task.plan.update", {"step_id": "place", "note": "Corrected placement after measured comparison", "expected_revision": revision})["plan"]["revision"]
    corrected = preview([2., 2., 3.])
    call("task.plan.apply_preview", {"preview_id": corrected["preview_id"], "expected_revision": revision})
    assert tuple(work.location) == (2., 2., 3.)

    unknown_calls = []
    runtime.registry.register("fixture.unreviewed_edit", lambda *_: unknown_calls.append(True), modifies=True)
    before = len(checkpoints)
    deny("NOT_IMPLEMENTED", "fixture.unreviewed_edit")
    deny("NOT_IMPLEMENTED", "project.save")
    deny("NOT_IMPLEMENTED", "checkpoint.undo_last")
    deny("NOT_IMPLEMENTED", "task.plan.persist", confirm=True, expected_revision=revision)
    deny("INVALID_ARGUMENT", "task.plan.clear", expected_revision=revision)
    assert not unknown_calls and len(checkpoints) == before
    disabled_preview = preview([2., 2., 3.])
    runtime.registry.disable_toolset("objects")
    try:
        deny("TOOLSET_DISABLED", "task.plan.apply_preview", preview_id=disabled_preview["preview_id"], expected_revision=revision)
        assert len(checkpoints) == before
    finally:
        runtime.registry.enable_toolset("objects")
    deny("INVALID_ARGUMENT", "transform.set", object_name=protected.name, location=[4., 5., 6.])

    # Incoming Object chains are effects; an outgoing readonly source is not.
    middle = bpy.data.objects.new("Artist Middle Consumer", None)
    scene.collection.objects.link(middle)
    for chain in (False, True):
        middle.parent = work if chain else None
        protected.parent = middle if chain else work
        before = len(checkpoints)
        deny("INVALID_ARGUMENT", "transform.set", object_name=work.name, location=[7., 0., 0.])
        assert len(checkpoints) == before and tuple(work.location) == (2., 2., 3.)
        protected.parent = None
        middle.parent = None
    source_constraint = work.constraints.new("COPY_LOCATION")
    source_constraint.target = protected
    reference_preview = preview([2., 2., 3.])
    assert reference_preview["affected_objects"] == [work.name]
    work.constraints.remove(source_constraint)

    before_handler = tuple(protected.location)
    handler_calls = []
    def hostile_handler(*_args):
        handler_calls.append(True)
        protected.location.x += 20.
    bpy.app.handlers.depsgraph_update_pre.append(hostile_handler)
    try:
        deny("NOT_IMPLEMENTED", "transform.set", object_name=work.name, location=[9., 0., 0.])
        assert not handler_calls and tuple(protected.location) == before_handler
    finally:
        bpy.app.handlers.depsgraph_update_pre.remove(hostile_handler)
    getter_calls = []
    def hostile_getter(_owner):
        getter_calls.append(True)
        protected.location.x += 30.
        return 0.
    bpy.types.Object.bridge_artist_scope_probe = bpy.props.FloatProperty(get=hostile_getter, set=lambda _owner, _value: None)
    try:
        deny("NOT_IMPLEMENTED", "transform.set", object_name=work.name, location=[9., 0., 0.])
        assert not getter_calls and tuple(protected.location) == before_handler
    finally:
        del bpy.types.Object.bridge_artist_scope_probe
    collision = work.modifiers.new("Artist Unsupported Collision", "COLLISION")
    try:
        deny("NOT_IMPLEMENTED", "transform.set", object_name=work.name, location=[9., 0., 0.])
    finally:
        work.modifiers.remove(collision)
    driver = protected.driver_add("location", 0)
    driver.driver.expression = "0"
    try:
        deny("NOT_IMPLEMENTED", "transform.set", object_name=work.name, location=[9., 0., 0.])
    finally:
        protected.driver_remove("location", 0)
        protected.animation_data_clear()

    # The latest outer permission callback changes live context before preflight.
    adversarial = []
    for fault in ("protected_consumer", "reference_identity", "scene", "layer", "own_channel"):
        candidate = preview([3., 2., 3.])
        fired, replacement = [], []
        old_layer = window.view_layer
        other_scene = bpy.data.scenes.new("Artist Other Scene") if fault == "scene" else None
        other_layer = scene.view_layers.new("Artist Other Layer") if fault == "layer" else None
        old_name = work.name
        def provider(fault=fault, fired=fired, replacement=replacement, old_name=old_name,
                     other_scene=other_scene, other_layer=other_layer):
            if not fired:
                fired.append(True)
                if fault == "protected_consumer":
                    protected.parent = work
                elif fault == "reference_identity":
                    work.name = "Artist Renamed Manual Prop"
                    replacement.append(bpy.data.objects.new(old_name, None))
                    scene.collection.objects.link(replacement[0])
                elif fault == "scene":
                    window.scene = other_scene
                elif fault == "layer":
                    window.view_layer = other_layer
                else:
                    work.location.x = 19.
            return grants
        before = len(checkpoints)
        manager._source = provider
        try:
            deny("INVALID_ARGUMENT", "task.plan.apply_preview", preview_id=candidate["preview_id"], expected_revision=revision)
            assert fired and len(checkpoints) == before
            assert work.location.x == (19. if fault == "own_channel" else 2.)
            adversarial.append(fault)
        finally:
            manager._source = lambda: grants
            if other_scene is not None:
                window.scene = scene
                bpy.data.scenes.remove(other_scene)
            window.view_layer = old_layer
            if other_layer is not None:
                scene.view_layers.remove(other_layer)
            for obj in replacement:
                bpy.data.objects.remove(obj, do_unlink=True)
            work.name = old_name
            protected.parent = None
            work.location = (2., 2., 3.)

    # After one owned field, no next field or compensating write may cross a
    # new protected consumer, explicit policy change, stop or disconnect.
    partial = []
    for fault in ("protected_consumer", "disable", "stop", "disconnect"):
        work.location, work.scale = (2., 2., 3.), (1., 1., 1.)
        candidate = preview([3., 2., 3.], [2., 2., 2.])
        connection = ConnectionLifetime()
        lifetime = RequestLifetime.local()
        lifetime.connection = connection
        fired = []
        def provider(fault=fault, fired=fired, connection=connection):
            if work.location.x == 3. and not fired:
                fired.append(True)
                if fault == "protected_consumer":
                    protected.parent = work
                elif fault == "disable":
                    from blender_codex_bridge.tools.artist_loop import enforce_plan
                    enforce_plan(runtime.executor.context, {"enabled": False, "expected_revision": revision})
                elif fault == "stop":
                    runtime.state.set_emergency_stopped(True)
                else:
                    connection.disconnected.set()
            return grants
        manager._source = provider
        try:
            request = Request(id="artist-partial-"+fault, method="task.plan.apply_preview",
                params={"preview_id": candidate["preview_id"], "expected_revision": revision}, _lifecycle=lifetime)
            try:
                runtime.executor._invoke(request)
            except BridgeError as error:
                assert error.context["possible_mutation"] and not error.context["rollback_verified"], error.to_dict()
            else:
                raise AssertionError("Expected measured partial interruption")
            assert fired and tuple(work.location) == (3., 2., 3.) and tuple(work.scale) == (1., 1., 1.)
            partial.append(fault)
        finally:
            manager._source = lambda: grants
            runtime.state.set_emergency_stopped(False)
            runtime.state.set_paused(False)
            protected.parent = None
            if not call("task.plan.inspect")["protected_scope_enforced"]:
                call("task.plan.enforce", {"enabled": True, "expected_revision": revision})
    work.location, work.scale = (2., 2., 3.), (1., 1., 1.)
    assert call("task.plan.compare")["evidence"]["status"] == "unchanged_within_scope"
    assert protected_before == (tuple(protected.location), tuple(tuple(vertex.co) for vertex in protected.data.vertices))
    runtime.state.set_emergency_stopped(True)
    disabled = call("task.plan.enforce", {"enabled": False, "expected_revision": revision})
    assert disabled["protection_audit_operation_id"]
    runtime.state.set_emergency_stopped(False)
    clear_task_plans(runtime.state)
    loaded = call("task.plan.load")
    assert not loaded["protected_scope_enforced"] and loaded["baseline"] is None
    assert not get_task_plans(runtime.state).references and not get_task_plans(runtime.state).previews
    assert scene[SCENE_PROPERTY] == saved
    assert work.active_selection_set == bundled_ui_index
    print("BLENDER_ARTIST_LOOP_OK " + json.dumps({"blender": bpy.app.version_string,
        "native_builtin_descriptors_accepted": True, "protected_structural_comparison": True,
        "exact_preview_single_use": True, "adversarial_before_checkpoint": adversarial,
        "measured_partial_no_illegal_compensation": partial, "host_handler_invoked": False,
        "runtime_rna_getter_invoked": False, "saved_plan_restored_authority": False,
        "bundled_bone_selection_ui_preserved": True,
        "explicit_disable_audited": True, "appearance_reviewed": False, "project_saved": False,
        "windows_qualified": False, "full_artist_acceptance": False, "finished_monotonic": time.monotonic()}, sort_keys=True), flush=True)
    blender_codex_bridge.unregister()


try:
    main()
except BridgeError as error:
    print("ARTIST_LOOP_BRIDGE_ERROR " + json.dumps(error.to_dict(), sort_keys=True), flush=True)
    raise
