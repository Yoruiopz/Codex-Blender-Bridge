"""Typed static import, guarded failure and saved-project reopen; use native runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from blender_asset_import_probe_smoke import writer as create_sources  # noqa: E402


def setup(bundle):
    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime

    runtime, prefs = get_runtime(), get_preferences()
    assert not prefs.allow_external_files and prefs.asset_source_directory == ""
    runtime.registry.enable_toolset("asset_delivery")
    for key in (
        "allow_inspect_scene",
        "allow_external_files",
        "allow_edit_scene",
        "allow_transform_objects",
        "allow_edit_mesh",
        "allow_edit_materials",
        "allow_edit_animation",
        "allow_delete_objects",
    ):
        setattr(prefs, key, True)
    prefs.asset_source_directory = str(bundle)
    prefs.asset_directory = ""
    prefs.allow_save_project = False
    return runtime, prefs


def denied(runtime, code, method, params):
    try:
        runtime.dispatch(method, params)
    except Exception as error:
        assert error.code == code, error
        # The fixture returns structured failure evidence, never native RNA-bearing
        # traceback/cause chains that outlive compensation and database teardown.
        error.__traceback__ = error.__context__ = error.__cause__ = None
        return error
    raise AssertionError("Expected " + method + " to fail with " + code)


def pixel_proof(image):
    values = array("f", [0.0]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return {
        "name": image.name,
        "size": list(image.size),
        "alpha": image.alpha_mode,
        "colorspace": image.colorspace_settings.name,
        "packed_sha256": hashlib.sha256(image.packed_file.data).hexdigest(),
        "pixels_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "pixel_count": len(values),
    }


def durable_state():
    records = []
    for format in ("GLB", "FBX"):
        collection = bpy.data.collections["Imported " + format]
        objects = []
        for obj in collection.objects:
            objects.append(
                {
                    "name": obj.name,
                    "data": obj.data.name,
                    "type": obj.type,
                    "parent": obj.parent.name if obj.parent else None,
                    "matrix": [list(row) for row in obj.matrix_world],
                    "vertices": [list(vertex.co) for vertex in obj.data.vertices],
                    "polygons": [list(polygon.vertices) for polygon in obj.data.polygons],
                    "uv": [[list(loop.uv) for loop in layer.data] for layer in obj.data.uv_layers],
                    "material_names": [slot.material.name for slot in obj.material_slots],
                    "image_bindings": [
                        {
                            "material": slot.material.name,
                            "node": node.name,
                            "image": node.image.name,
                        }
                        for slot in obj.material_slots
                        for node in slot.material.node_tree.nodes
                        if getattr(node, "image", None)
                    ],
                }
            )
        records.append({"format": format, "objects": objects})
    images = [
        pixel_proof(image)
        for image in bpy.data.images
        if image.packed_file and image.name != "CollisionImage"
    ]
    scene = bpy.context.scene
    return {
        "collections": records,
        "images": images,
        "scene": {
            "fps": [scene.render.fps, scene.render.fps_base],
            "frame": [scene.frame_current, scene.frame_subframe],
            "units": [scene.unit_settings.system, scene.unit_settings.scale_length],
        },
        "protected": {
            "object": bpy.data.objects["CollisionObject"].data.name,
            "material": bpy.data.objects["CollisionObject"].material_slots[0].material.name,
            "action": bpy.data.objects["CollisionObject"].animation_data.action.name,
        },
    }


def writer(bundle):
    create_sources(bundle)
    from blender_codex_bridge.tools import asset_import

    runtime, prefs = setup(bundle)
    protected = bpy.data.objects["CollisionObject"]
    material = bpy.data.materials["CollisionMaterial"]
    protected.data.materials.append(material)
    image = bpy.data.images["CollisionImage"]
    image.filepath, image.alpha_mode = str(bundle / "same-path.png"), "STRAIGHT"
    image.pixels.foreach_set(array("f", [0.7, 0.1, 0.3, 1.0] * 4))
    action = bpy.data.actions.new("CollisionAction")
    protected.animation_data_create().action = action
    destination = bpy.context.scene
    destination.render.fps, destination.render.fps_base = 30, 1.001
    destination.frame_set(9, subframe=0.25)
    protected_ids = asset_import._inventory(bpy)
    baseline = asset_import._guard(bpy, protected_ids)
    original_native = asset_import._native
    results = []
    for format, filename in (("GLB", "embedded.glb"), ("FBX", "untextured.fbx")):
        params = {"filepath": str(bundle / filename), "format": format}
        prefs.allow_external_files = False
        denied(runtime, "PERMISSION_DENIED", "asset.import_preview", params)
        prefs.allow_external_files = True
        denied(
            runtime,
            "NOT_IMPLEMENTED",
            "asset.import_preview",
            {**params, "include_animation": True},
        )
        bpy.ops.object.mode_set(mode="EDIT")
        denied(runtime, "NOT_IMPLEMENTED", "asset.import_preview", params)
        bpy.ops.object.mode_set(mode="OBJECT")
        preview = runtime.dispatch("asset.import_preview", params)
        request = {
            **params,
            "collection_name": "Imported " + format,
            "expected_fingerprint": preview["fingerprint"],
            "accepted_losses": preview["required_accepted_losses"],
        }
        denied(
            runtime,
            "INVALID_ARGUMENT",
            "asset.import",
            {**request, "expected_fingerprint": "0" * 64},
        )
        denied(runtime, "INVALID_ARGUMENT", "asset.import", {**request, "accepted_losses": []})
        before_failure = asset_import._inventory(bpy)

        def fail_native(*args):
            original_native(*args)
            raise RuntimeError(
                "Owned fixture injection after native importer allocated its exact IDs"
            )

        asset_import._native = fail_native
        try:
            error = denied(runtime, "OPERATION_FAILED", "asset.import", request)
        finally:
            asset_import._native = original_native
        assert error.context["possible_mutation"] and not error.context["import_published"]
        assert error.context["owned_id_cleanup"] == "removed", error.to_dict()
        assert error.context["external_effects"]["staging_cleanup"] == "removed"
        failure_intervals = error.context["native_blocking_intervals_seconds"]
        error = None
        assert asset_import._inventory(bpy) == before_failure
        assert bpy.data.collections.get(request["collection_name"]) is None
        result = runtime.dispatch("asset.import", request)
        assert result["imported"] and result["protected_measured_state_preserved"]
        assert result["external_effects"]["staging_cleanup"] == "removed"
        assert not result["project_saved"] and not result["native_import_interruptible"]
        assert (
            not result["visual_appearance_verified"] and not result["fresh_process_reopen_verified"]
        )
        collection = bpy.data.collections[result["collection"]]
        assert len(collection.objects) == 1
        imported = collection.objects[0]
        assert imported != protected and imported.data != protected.data
        assert len({tuple(vertex.co) for vertex in imported.data.vertices}) == 8
        assert imported.animation_data is None
        if format == "GLB":
            assert len(result["imported_images"]) == 1
            new_image = bpy.data.images[result["imported_images"][0]]
            assert new_image != image and new_image.packed_file and new_image.has_data
            assert list(new_image.size) == [2, 2]
            assert (
                len(imported.material_slots) == 1
                and imported.material_slots[0].material != material
            )
        else:
            assert not result["imported_images"] and not result["imported_materials"]
        ignored = {
            child.as_pointer()
            for child in destination.collection.children
            if child.name.startswith("Imported ")
        }
        assert asset_import._guard(bpy, protected_ids, ignored_collections=ignored) == baseline
        results.append(
            {
                "format": format,
                "result": result,
                "unique_coordinates": 8,
                "injected_native_failure_owned_resources_removed": True,
                "failure_native_blocking_intervals_seconds": failure_intervals,
            }
        )
    state = durable_state()
    project = bundle / "imported.blend"
    denied(runtime, "PERMISSION_DENIED", "project.save", {"filepath": str(project)})
    assert not project.exists()
    prefs.allow_save_project = True
    assert runtime.dispatch("project.save", {"filepath": str(project)})["saved"]
    manifest = {
        "state": state,
        "project": project.name,
        "project_sha256": hashlib.sha256(project.read_bytes()).hexdigest(),
        "imports": results,
    }
    (bundle / "import-typed.json").write_text(json.dumps(manifest), encoding="utf8")
    # Only owned fixture sources are relocated, after import and the approved save.
    unavailable = bundle / "unavailable"
    unavailable.mkdir()
    for filename in ("embedded.glb", "untextured.fbx"):
        (bundle / filename).rename(unavailable / filename)
    return {
        "imports": results,
        "project_sha256": manifest["project_sha256"],
        "protected_same_name_path_image_material_action_and_context_verified": True,
        "source_files_unavailable_for_reader": True,
        "saved": True,
        "protected_dirty_generated_image_reopen_pixels_certified": False,
    }


def reader(bundle):
    manifest = json.loads((bundle / "import-typed.json").read_text(encoding="utf8"))
    assert not (bundle / "embedded.glb").exists() and not (bundle / "untextured.fbx").exists()
    project = bundle / manifest["project"]
    assert hashlib.sha256(project.read_bytes()).hexdigest() == manifest["project_sha256"]
    bpy.ops.wm.open_mainfile(filepath=str(project), load_ui=False)
    # A new native process has no bridge consent from the saved project.
    _runtime, prefs = setup(bundle)
    assert not prefs.allow_save_project
    assert durable_state() == manifest["state"]
    assert all(
        not scene.name.startswith("Bridge Private Asset Import") for scene in bpy.data.scenes
    )
    return {
        "project_sha256": manifest["project_sha256"],
        "fresh_process_reopen_verified": True,
        "complete_imported_pixels_bindings_geometry_transforms_units_verified": True,
        "source_files_unavailable": True,
        "project_saved": False,
        "release_acceptance": False,
        "imported_images": len(manifest["state"]["images"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    result = (writer if args.bridge_phase == "writer" else reader)(
        args.bridge_bundle.resolve(strict=True)
    )
    print(
        "BLENDER_ASSET_IMPORT_"
        + args.bridge_phase.upper()
        + "_OK "
        + json.dumps(
            {
                **result,
                "phase": args.bridge_phase,
                "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
                "process_id": os.getpid(),
                "blender_version": bpy.app.version_string,
                "release_readiness": "NOT_ASSESSED",
            }
        ),
        flush=True,
    )
