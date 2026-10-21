"""Owned native import research, only through the isolated phased runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
from blender_codex_bridge import pixel_codecs  # noqa: E402

FAMILIES = (
    "scenes",
    "collections",
    "objects",
    "meshes",
    "armatures",
    "actions",
    "materials",
    "node_groups",
    "images",
)


def identities():
    return {
        family: {item.as_pointer() for item in getattr(bpy.data, family)} for family in FAMILIES
    }


def writer(bundle):
    from array import array

    obj = bpy.data.objects["Cube"]
    obj.name = "CollisionObject"
    obj.data.name = "CollisionMesh"
    material = bpy.data.materials.new("CollisionMaterial")
    material.use_nodes = True
    obj.data.materials.clear()
    obj.data.materials.append(material)
    values = array("f", [0.2, 0.4, 0.8, 1.0] * 4)
    payload = b"".join(
        step.data for step in pixel_codecs.encode_steps(values, 2, 2, "PNG8", "COLOR")
    )
    image = bpy.data.images.new("CollisionImage", 2, 2)
    image.pack(data=payload, data_len=len(payload))
    image.filepath = str(bundle / "same-path.png")
    image.source = "FILE"
    image_node = material.node_tree.nodes.new("ShaderNodeTexImage")
    image_node.image = image
    material.node_tree.links.new(
        image_node.outputs["Color"],
        material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"],
    )
    glb = bundle / "embedded.glb"
    assert bpy.ops.export_scene.gltf(
        filepath=str(glb),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_image_format="AUTO",
    ) == {"FINISHED"}
    obj.data.materials.clear()
    fbx = bundle / "untextured.fbx"
    assert bpy.ops.export_scene.fbx(
        filepath=str(fbx),
        use_selection=True,
        bake_anim=False,
        path_mode="STRIP",
        object_types={"MESH"},
        add_leaf_bones=False,
    ) == {"FINISHED"}
    manifest = {
        "files": [
            {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "format": path.suffix[1:].upper(),
            }
            for path in (glb, fbx)
        ],
        "image_path": image.filepath,
    }
    (bundle / "import-probe.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def reader(bundle):
    from array import array

    manifest = json.loads((bundle / "import-probe.json").read_text(encoding="utf-8"))
    protected = bpy.data.objects["Cube"]
    protected.name = "CollisionObject"
    protected.data.name = "CollisionMesh"
    material = bpy.data.materials.new("CollisionMaterial")
    material.use_nodes = True
    protected.data.materials.append(material)
    image = bpy.data.images.new("CollisionImage", 2, 2)
    image.filepath = manifest["image_path"]
    image.alpha_mode = "STRAIGHT"
    image.pixels.foreach_set(array("f", [0.7, 0.1, 0.3, 1.0] * 4))
    action = bpy.data.actions.new("CollisionAction")
    protected.animation_data_create().action = action
    protected.rotation_mode = "XYZ"
    destination = bpy.context.scene
    destination.render.fps = 30
    destination.render.fps_base = 1.001
    destination.unit_settings.scale_length = 1.0
    destination.frame_set(9, subframe=0.25)
    selected = [obj.as_pointer() for obj in bpy.context.selected_objects]
    active = bpy.context.view_layer.objects.active

    def protected_state():
        pixels = array("f", [0.0]) * len(image.pixels)
        image.pixels.foreach_get(pixels)
        return {
            "object": protected.as_pointer(),
            "data": protected.data.as_pointer(),
            "matrix": [list(row) for row in protected.matrix_world],
            "material": material.as_pointer(),
            "nodes": [(node.name, node.bl_idname) for node in material.node_tree.nodes],
            "image": image.as_pointer(),
            "pixels": hashlib.sha256(pixels.tobytes()).hexdigest(),
            "alpha": image.alpha_mode,
            "path": image.filepath,
            "action": protected.animation_data.action.as_pointer(),
            "fps": [destination.render.fps, destination.render.fps_base],
            "frame": [destination.frame_current, destination.frame_subframe],
            "units": [destination.unit_settings.system, destination.unit_settings.scale_length],
        }

    before = protected_state()
    results = []
    for record in manifest["files"]:
        path = bundle / record["name"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        baseline = identities()
        scene = bpy.data.scenes.new("Owned Import Stage " + record["format"])
        collection = bpy.data.collections.new("Owned Import Collection " + record["format"])
        scene.collection.children.link(collection)
        scene.render.fps, scene.render.fps_base = (
            destination.render.fps,
            destination.render.fps_base,
        )
        with bpy.context.temp_override(
            scene=scene, view_layer=scene.view_layers[0], collection=collection
        ):
            if record["format"] == "GLB":
                names = set(bpy.ops.import_scene.gltf.get_rna_type().properties.keys())
                args = {
                    "filepath": str(path),
                    "import_pack_images": True,
                    "merge_vertices": False,
                    "bone_heuristic": "BLENDER",
                    "disable_bone_shape": True,
                }
                for key, value in (
                    ("import_scene_extras", False),
                    ("import_scene_as_collection", False),
                    ("import_select_created_objects", False),
                    ("import_unused_materials", False),
                ):
                    if key in names:
                        args[key] = value
                assert bpy.ops.import_scene.gltf(**args) == {"FINISHED"}
            else:
                args = {
                    "filepath": str(path),
                    "use_image_search": False,
                    "use_anim": False,
                    "anim_offset": 0.0,
                    "use_custom_props": False,
                }
                assert bpy.ops.import_scene.fbx(**args) == {"FINISHED"}
        assert bpy.context.scene == destination
        assert protected_state() == before
        created = {
            family: [
                item.name
                for item in getattr(bpy.data, family)
                if item.as_pointer() not in baseline[family]
            ]
            for family in FAMILIES
        }
        imported = [obj for obj in bpy.data.objects if obj.as_pointer() not in baseline["objects"]]
        print(
            "PROBE_IMPORT_OWNERS "
            + json.dumps(
                {
                    "created": created,
                    "links": {
                        obj.name: [owner.name for owner in obj.users_collection] for obj in imported
                    },
                    "stage_objects": list(scene.objects.keys()),
                    "destination_objects": list(destination.objects.keys()),
                }
            ),
            flush=True,
        )
        assert len(imported) == 1 and imported[0].type == "MESH"
        assert len({tuple(vertex.co) for vertex in imported[0].data.vertices}) == 8
        assert all(obj.name in scene.objects for obj in imported)
        for obj in imported:
            collection.objects.link(obj)
            for owner in list(obj.users_collection):
                if owner != collection:
                    assert (
                        owner == scene.collection
                        or owner.as_pointer() not in baseline["collections"]
                    )
                    owner.objects.unlink(obj)
        assert len(created["images"]) == (1 if record["format"] == "GLB" else 0)
        collection_users = [
            (type(user).__name__, user.name)
            for user in bpy.data.user_map(subset={collection}).get(collection, ())
        ]
        scene.collection.children.unlink(collection)
        destination.collection.children.link(collection)
        scene_users = [
            (type(user).__name__, user.name)
            for user in bpy.data.user_map(subset={scene}).get(scene, ())
        ]
        strict_scene_removal = {
            "users": scene.users,
            "fake_user": scene.use_fake_user,
            "extra_user": scene.use_extra_user,
            "mapped_consumers": scene_users,
        }
        assert not scene_users and not scene.objects and not scene.collection.children
        try:
            bpy.data.scenes.remove(scene, do_unlink=False)
            strict_scene_removal["do_unlink_false"] = "removed"
        except RuntimeError as error:
            strict_scene_removal["do_unlink_false"] = str(error)
            assert scene.use_extra_user and scene.users == 1
            bpy.data.scenes.remove(scene, do_unlink=True)
        assert protected_state() == before
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj.as_pointer() in selected)
        bpy.context.view_layer.objects.active = active
        results.append(
            {
                "format": record["format"],
                "created": created,
                "collection_users_before_publication": collection_users,
                "strict_owned_scene_removal": strict_scene_removal,
                "operator_arguments": args,
                "source_unchanged": hashlib.sha256(path.read_bytes()).hexdigest()
                == record["sha256"],
            }
        )
    return {
        "imports": results,
        "protected_same_names_paths_images_materials_action_and_scene_verified": True,
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
        "BLENDER_ASSET_IMPORT_PROBE_"
        + args.bridge_phase.upper()
        + "_OK "
        + json.dumps(
            {
                **result,
                "phase": args.bridge_phase,
                "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
                "process_id": os.getpid(),
                "blender_version": bpy.app.version_string,
                "native_api_research_only": True,
                "release_readiness": "NOT_ASSESSED",
            }
        ),
        flush=True,
    )
