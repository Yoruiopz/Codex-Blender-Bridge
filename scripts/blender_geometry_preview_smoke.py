"""Owned registered geometry job acceptance; the fixture never launches a child."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
MARKER = "BLENDER_GEOMETRY_PREVIEW_OK "


def main():
    from blender_artist_sidebar_smoke import owned_process_exit, private_display_manifest

    assert (
        not bool(getattr(bpy.app, "background", True))
        and "--factory-startup" in sys.argv
        and "--disable-autoexec" in sys.argv
    )
    private_display_manifest()  # Must attest before owned exit or setup.
    assert (
        tuple(bpy.app.version) in {(4, 5, 14), (5, 2, 2)}
        and bpy.app.build_type.decode() == "Release"
    )
    assert bpy.app.build_hash.decode() in {"62c1db4208e8", "d13f752e3b9c"}
    import tempfile

    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime
    from blender_isolated_asset_preview_probe_smoke import bits, raw_selection, token

    status = 1
    runtime = None
    proof = {"completed": False, "blender_version": bpy.app.version_string, "calls": []}
    output = Path(tempfile.gettempdir()) / "registered-geometry-preview.json"
    try:
        assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
        runtime, prefs = get_runtime(), get_preferences()
        prefs.auto_start = False
        prefs.allow_inspect_scene = prefs.allow_viewport_capture = prefs.allow_external_files = True
        proof["serialization_controls_before"] = {
            "preferences_save": bpy.context.preferences.use_preferences_save,
            "temporary_autosave": bpy.context.preferences.filepaths.use_auto_save_temporary_files,
        }
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
        scene, layer = bpy.context.scene, bpy.context.view_layer
        mesh = bpy.data.meshes.new("Registered Geometry Source Mesh")
        mesh.from_pydata([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.5)], [], [(0, 1, 2)])
        mesh.update()
        target = bpy.data.objects.new("Registered Geometry Source", mesh)
        scene.collection.objects.link(target)
        protected = bpy.data.objects.new("Registered Geometry Protected", None)
        scene.collection.objects.link(protected)
        material = bpy.data.materials.new("Registered Source Material Sentinel")
        material.diffuse_color = (0.3, 0.5, 0.7, 0.8)
        mesh.materials.append(material)
        target["preview_keep_ref"] = protected
        actor = bpy.data.objects.new("Registered Dirty Animation", None)
        scene.collection.objects.link(actor)
        # Setup only: materialize linked Objects before real plan references
        # resolve. No source sync is permitted after the pending-state setup.
        layer.update()
        action = bpy.data.actions.new("Registered Dirty Action")
        slot = action.slots.new("OBJECT", actor.name)
        strip = action.layers.new("Owned Layer").strips.new(type="KEYFRAME")
        curve = strip.channelbag(slot, ensure=True).fcurves.new(data_path="location", index=0)
        curve.keyframe_points.add(2)
        curve.keyframe_points[0].co, curve.keyframe_points[1].co = (1.0, 20.0), (10.0, 30.0)
        curve.update()
        actor.animation_data_create().action = action
        actor.animation_data.action_slot = slot
        plan = runtime.dispatch(
            "task.plan.set",
            {
                "goal": "Observe authored geometry without source edits",
                "steps": [{"id": "preview", "description": "Inspect geometry"}],
                "protected_objects": [protected.name, actor.name],
            },
        )
        runtime.dispatch(
            "task.plan.enforce", {"enabled": True, "expected_revision": plan["plan"]["revision"]}
        )
        for obj in layer.objects:
            obj.select_set(False, view_layer=layer)
        protected.select_set(True, view_layer=layer)
        layer.objects.active = protected
        layer.update()
        protected.hide_set(True, view_layer=layer)
        actor.location = (0.0, 0.0, 0.0)

        def object_fields(obj):
            return {
                "identity": token(obj),
                "rotation_mode": obj.rotation_mode,
                "channels": {
                    name: bits(getattr(obj, name))
                    for name in (
                        "location",
                        "rotation_euler",
                        "rotation_quaternion",
                        "rotation_axis_angle",
                        "scale",
                        "delta_location",
                        "delta_rotation_euler",
                        "delta_rotation_quaternion",
                        "delta_scale",
                    )
                },
                "visibility": {
                    name: bool(getattr(obj, name))
                    for name in ("hide_viewport", "hide_render", "hide_select")
                },
                "parent": None if obj.parent is None else token(obj.parent),
                "users": int(obj.users),
            }

        def projection():
            # Independent literal authored fields. No context/active/selected,
            # select_get/hide_get, dimensions, matrix, bounds or evaluation getter.
            data = actor.animation_data
            return {
                "target": {
                    **object_fields(target),
                    "mesh_identity": token(mesh),
                    "mesh_users": int(mesh.users),
                    "vertices": [bits(v.co) for v in mesh.vertices],
                    "edges": [list(e.vertices) for e in mesh.edges],
                    "faces": [
                        {
                            "vertices": list(p.vertices),
                            "material_index": int(p.material_index),
                            "smooth": bool(p.use_smooth),
                        }
                        for p in mesh.polygons
                    ],
                    "material_bindings": [token(m) for m in mesh.materials],
                    "known_USER_reference": {
                        "property": "preview_keep_ref",
                        "identity": token(target["preview_keep_ref"]),
                    },
                },
                "protected": object_fields(protected),
                "actor": object_fields(actor),
                "action": {
                    "identity": token(action),
                    "users": int(action.users),
                    "binding": {
                        "action": token(data.action),
                        "slot_pointer": int(data.action_slot.as_pointer()),
                        "slot_handle": int(data.action_slot.handle),
                    },
                    "slots": [
                        [int(s.as_pointer()), int(s.handle), s.identifier] for s in action.slots
                    ],
                    "layers": [
                        {
                            "pointer": int(layer_item.as_pointer()),
                            "name": layer_item.name,
                            "strips": [
                                {
                                    "pointer": int(strip_item.as_pointer()),
                                    "type": strip_item.type,
                                    "bags": [
                                        {
                                            "pointer": int(bag.as_pointer()),
                                            "slot_handle": int(bag.slot_handle),
                                            "curve_pointers": [
                                                int(fc.as_pointer()) for fc in bag.fcurves
                                            ],
                                        }
                                        for bag in strip_item.channelbags
                                    ],
                                }
                                for strip_item in layer_item.strips
                            ],
                        }
                        for layer_item in action.layers
                    ],
                    "curve": {
                        "pointer": int(curve.as_pointer()),
                        "data_path": curve.data_path,
                        "array_index": int(curve.array_index),
                        "extrapolation": curve.extrapolation,
                        "keys": [
                            {
                                "pointer": int(p.as_pointer()),
                                "co": bits(p.co),
                                "handle_left": bits(p.handle_left),
                                "handle_right": bits(p.handle_right),
                                "handle_left_type": p.handle_left_type,
                                "handle_right_type": p.handle_right_type,
                                "interpolation": p.interpolation,
                                "easing": p.easing,
                            }
                            for p in curve.keyframe_points
                        ],
                    },
                },
                "material": {
                    "identity": token(material),
                    "users": int(material.users),
                    "diffuse": bits(material.diffuse_color),
                },
                "raw_selected": raw_selection(layer),
                "frame": [scene.frame_current, scene.frame_subframe],
            }

        before = projection()
        from blender_codex_bridge.task_plans import get_task_plans

        store = get_task_plans(runtime.state)
        baseline, protection = store.baseline, store.protection
        accepted = runtime.dispatch(
            "preview.geometry_start", {"object_name": target.name, "time_limit_seconds": 120}
        )
        after = projection()
        assert (
            before == after
            and before["raw_selected"]
            and before["actor"]["channels"]["location"][0] == "00000000"
        )
        assert before["action"]["curve"]["keys"][0]["co"][1] == "0000a041"
        assert (
            store.baseline is baseline and store.protection is protection and protection is not None
        )
        proof.update(
            before_public_entry=before,
            after_public_entry=after,
            source_preserved_around_registered_start=True,
            real_task_plan_enforcement=True,
            protected_baseline_present_before=baseline is not None,
            protected_baseline_present_after=store.baseline is not None,
            protected_baseline_identity_preserved=store.baseline is baseline,
            populated_protected_data_baseline_qualified=False,
            projection_scope="Declared target topology/raw channels, protected Object channels/raw visibility, known Action layout/keys/handles/bindings, known material and USER-reference identities; fixture-only raw selected Base diagnostic.",
            protected_baseline_rebased=False,
            accepted=accepted,
        )
        job_id = accepted["job_id"]
        started = time.monotonic()
        phase = "success"

        def tick():
            nonlocal status, phase, job_id
            try:
                if time.monotonic() - started > 125:
                    raise AssertionError("Registered geometry job exceeded fixture deadline")
                row = runtime.dispatch("jobs.inspect", {"job_id": job_id})
                if not row["terminal"]:
                    if phase == "revoke_wait" and row["progress"].get("phase") == "worker_running":
                        prefs.allow_viewport_capture = False
                        phase = "revoked"
                    return 0.05
                if phase == "cancel":
                    assert row["state"] == "CANCELLED" and row["result"] is None, row
                    proof["calls"].append(
                        {"case": "explicit_cancel_before_worker", "terminal": row}
                    )
                    next_job = runtime.dispatch(
                        "preview.geometry_start",
                        {"object_name": target.name, "time_limit_seconds": 120},
                    )
                    job_id, phase = next_job["job_id"], "revoke_wait"
                    return 0.05
                if phase == "revoked":
                    assert row["state"] == "CANCELLED" and row["result"] is None, row
                    assert (
                        row["external_effects"]["worker_reaped"]
                        and row["external_effects"]["staging_cleanup"] == "complete"
                    )
                    prefs.allow_viewport_capture = True
                    proof["calls"].append({"case": "revoke_running_worker", "terminal": row})
                    proof["completed"] = True
                    output.write_text(json.dumps(proof, indent=2) + "\n")
                    print(
                        MARKER
                        + json.dumps(
                            {
                                "blender_version": bpy.app.version_string,
                                "receipt": str(output),
                                "completed": True,
                            }
                        ),
                        flush=True,
                    )
                    status = 0
                    owned_process_exit(status)
                    return None
                assert phase == "success" and row["state"] == "SUCCEEDED", row
                image = runtime.dispatch(
                    "preview.geometry_image", {"preview_id": row["result"]["preview_id"]}
                )
                assert image["scene_changed"] is False and image["project_saved"] is False
                assert store.protection is protection and store.baseline is baseline
                proof.update(
                    completed=False,
                    terminal=row,
                    image_sha256=image["image_sha256"],
                    image=image,
                    worker_and_source_process_separate=True,
                    visual_review_performed=False,
                    original_viewport_qualified=False,
                    full_H02_or_F01_qualified=False,
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                )
                with output.with_suffix(".png").open("xb") as stream:
                    stream.write(base64.b64decode(image["png_base64"], validate=True))
                output.write_text(json.dumps(proof, indent=2) + "\n")
                from blender_codex_bridge.errors import BridgeError

                target.location.x += 0.25  # Explicit disposable manual edit after positive proof.
                try:
                    runtime.dispatch(
                        "preview.geometry_image", {"preview_id": row["result"]["preview_id"]}
                    )
                    raise AssertionError("Stale geometry image was returned")
                except BridgeError as error:
                    assert error.context.get("reason") == "STALE_SOURCE"
                    proof["calls"].append({"case": "stale_fetch", "error": error.to_dict()})
                prefs.allow_viewport_capture = False
                try:
                    runtime.dispatch("preview.geometry_start", {"object_name": target.name})
                    raise AssertionError("Denied geometry start was accepted")
                except BridgeError as error:
                    assert error.code == "PERMISSION_DENIED"
                    proof["calls"].append({"case": "denied_start", "error": error.to_dict()})
                finally:
                    prefs.allow_viewport_capture = True
                cancelled = runtime.dispatch(
                    "preview.geometry_start",
                    {"object_name": target.name, "time_limit_seconds": 120},
                )
                runtime.dispatch("jobs.cancel", {"job_id": cancelled["job_id"]})
                job_id, phase = cancelled["job_id"], "cancel"
                return 0.05
            except Exception:
                proof["failure"] = traceback.format_exc()
                output.write_text(json.dumps(proof, indent=2) + "\n")
            if status:
                runtime.jobs.cancel_all("geometry fixture failed")
            owned_process_exit(status)
            return None

        bpy.app.timers.register(tick, first_interval=0.05)
        return
    except Exception:
        proof["failure"] = traceback.format_exc()
        output.write_text(json.dumps(proof, indent=2) + "\n")
        if runtime is not None:
            runtime.jobs.cancel_all("geometry fixture setup failed")
        owned_process_exit(status)


if __name__ == "__main__":
    main()
