"""Real checkpoint transfers between artist targets in an owned UI fixture."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.checkpoints import MARKER_KEY  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def main():
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.edit.use_global_undo = True
    blender_codex_bridge.register()
    runtime = get_runtime()
    runtime.registry.enable_toolset("objects")
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    provider_hook = [None]

    def provide():
        if provider_hook[0] is not None:
            provider_hook[0]()
        return dict(grants)

    permissions = PermissionManager(provide)
    runtime.permissions = runtime.executor.permissions = permissions
    call = runtime.dispatch
    scene = bpy.context.scene
    protected = bpy.data.objects["Cube"]
    material = bpy.data.materials.new("Owned Protected Artist Material")
    material.use_nodes = True
    material[MARKER_KEY] = "owned-original-material-value"
    protected.data.materials.clear()
    protected.data.materials.append(material)
    principled = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    principled.inputs["Roughness"].default_value = .37
    principled.inputs["Base Color"].default_value = (.12, .31, .58, 1.)
    first = bpy.data.objects.new("Owned Artist A", None)
    second = bpy.data.objects.new("Owned Artist B", None)
    scene.collection.objects.link(first)
    scene.collection.objects.link(second)

    def select(obj):
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.context.view_layer.update()

    def protected_state():
        # Independent checks of this deliberately tiny authored fixture graph.
        return {
            "object": protected.as_pointer(), "mesh": protected.data.as_pointer(),
            "matrix": [float(value) for row in protected.matrix_world for value in row],
            "vertices": [list(vertex.co) for vertex in protected.data.vertices],
            "edges": [list(edge.vertices) for edge in protected.data.edges],
            "polygons": [list(polygon.vertices) for polygon in protected.data.polygons],
            "parent": None if protected.parent is None else protected.parent.as_pointer(),
            "materials": [item.as_pointer() for item in protected.data.materials],
            "tree": material.node_tree.as_pointer(),
            "nodes": sorted((node.name, node.bl_idname, node.mute, list(node.location))
                            for node in material.node_tree.nodes),
            "links": sorted((link.from_node.name, link.from_socket.identifier,
                             link.to_node.name, link.to_socket.identifier) for link in material.node_tree.links),
            "roughness": float(principled.inputs["Roughness"].default_value),
            "material_custom_marker": material[MARKER_KEY],
            "base_color": list(principled.inputs["Base Color"].default_value),
        }

    def initialize_protected_weak_owner():
        select(protected)
        assert bpy.ops.ed.undo_push(message="Owned previous protected artist target") == {"FINISHED"}
        assert scene.tool_settings.particle_edit.object == protected
        assert scene.user_of_id(scene) == 1

    initialize_protected_weak_owner()
    plan = call("task.plan.set", {
        "goal": "Revise both working props while preserving Cube and its material",
        "steps": [{"id": "place", "description": "Preview and compare both working props"}],
        "protected_objects": [protected.name],
    })
    revision = plan["plan"]["revision"]
    call("task.plan.capture", {"fields": ["transforms", "hierarchy", "mesh_geometry", "material_slots"]})
    call("task.plan.enforce", {"enabled": True, "expected_revision": revision})
    original = protected_state()

    def preview(obj, location):
        select(obj)
        reference = call("task.reference.resolve", {"source": "selection"})["reference_id"]
        return call("task.plan.preview_transform", {
            "reference_id": reference, "expected_revision": revision,
            "location": location, "step_id": "place",
        })["preview_id"]

    transfers = []
    for obj, location in ((first, [1., 2., 0.]), (second, [-2., 1., 0.]), (first, [3., 2., 0.])):
        candidate = preview(obj, location)
        previous = scene.tool_settings.particle_edit.object
        position = runtime.checkpoints._window.position
        result = call("task.plan.apply_preview", {"preview_id": candidate, "expected_revision": revision})
        assert list(obj.location) == location
        assert scene.tool_settings.particle_edit.object == obj and scene.user_of_id(scene) == 1
        assert runtime.checkpoints._window.position == position + 2
        assert runtime.checkpoints._pending is None
        assert protected_state() == original
        call("task.plan.compare", {"step_id": "place", "expected_revision": revision})
        receipts = call("task.plan.inspect")["step_evidence"]["receipts"]
        receipt = next(item for item in receipts if item["operation_id"] == result["operation"]["operation_id"])
        assert receipt["success"] and receipt["step_id"] == "place"
        assert receipt["protected_observation"]["status"] == "unchanged_within_scope"
        assert receipt["protected_observation"]["user_goal_verified"] is False
        transfers.append({"previous": previous.name, "target": obj.name,
                          "completed_native_pushes": 2, "protected_structure_retained": True,
                          "operation_id": receipt["operation_id"]})

    # A change to the previous owner's nested authored material must survive
    # denial, without a native checkpoint or the requested transform afterward.
    denials = []
    for field in ("roughness", "material_custom_marker"):
        initialize_protected_weak_owner()
        candidate = preview(second, [7., 0., 0.])
        marker = scene.get(MARKER_KEY)
        position = runtime.checkpoints._window.position
        location = list(second.location)
        case_before = protected_state()
        fired = []

        def change_previous_material(*, field=field, fired=fired):
            if not fired:
                fired.append(True)
                if field == "roughness":
                    principled.inputs["Roughness"].default_value = .81
                else:
                    material[MARKER_KEY] = "manual-new-material-value"

        provider_hook[0] = change_previous_material
        try:
            call("task.plan.apply_preview", {"preview_id": candidate, "expected_revision": revision})
        except BridgeError as error:
            assert error.code in {"INVALID_ARGUMENT", "NOT_IMPLEMENTED"}, error.to_dict()
            denial = error.code
        else:
            raise AssertionError("Previous owner's authored material change was not detected")
        finally:
            provider_hook[0] = None
        assert fired == [True]
        if field == "roughness":
            assert abs(principled.inputs["Roughness"].default_value - .81) < 1e-6
        else:
            assert material[MARKER_KEY] == "manual-new-material-value"
        assert list(second.location) == location and scene.get(MARKER_KEY) == marker
        assert runtime.checkpoints._window.position == position
        assert scene.tool_settings.particle_edit.object == protected
        changed = protected_state()
        assert {key: value for key, value in changed.items() if key != field} == {
            key: value for key, value in case_before.items() if key != field}
        denials.append({"field": field, "denial_code": denial, "completed_native_pushes": 0,
                        "manual_value_retained": True, "requested_transform_retained": False})
    print("BLENDER_ARTIST_MULTITARGET_OK " + json.dumps({
        "blender_version": bpy.app.version_string, "transfers": transfers,
        "protected_previous_owner_material_drift": denials,
        "scope": "Tiny native static Mesh/Principled previous owner and Empty targets",
        "visual_artist_acceptance": False, "full_workflow_acceptance": False,
        "project_saved": False, "user_preferences_saved": False,
    }), flush=True)


def run():
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
