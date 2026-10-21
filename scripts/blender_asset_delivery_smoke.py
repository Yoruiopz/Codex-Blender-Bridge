"""Fresh-process GLB/FBX delivery probe; imports only this fixture's owned artifacts."""

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


def setup(bundle):
    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime
    from blender_codex_bridge.tools import asset_delivery
    runtime, prefs = get_runtime(), get_preferences()
    if "asset.export" not in runtime.registry.list_tools():
        asset_delivery.register_tools(runtime.registry)
    runtime.registry.enable_toolset("asset_delivery")
    assert not prefs.allow_external_files and prefs.asset_directory == ""
    prefs.allow_external_files = prefs.allow_save_project = prefs.allow_edit_scene = True
    prefs.asset_directory = str(bundle)
    return runtime, prefs


def deny(runtime, code, method, params):
    from blender_codex_bridge.errors import BridgeError
    try:
        runtime.dispatch(method, params)
    except BridgeError as error:
        assert error.code == code, error
    else:
        raise AssertionError("Expected rejection: " + method)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def samples(object_name="DeliveryMesh"):
    result = {}
    for frame in (1, 2):
        bpy.context.scene.frame_set(frame)
        graph = bpy.context.evaluated_depsgraph_get()
        points = []
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH" or obj.name != object_name:
                continue
            evaluated = obj.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                points.extend(tuple(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices)
            finally:
                evaluated.to_mesh_clear()
        result[str(frame)] = sorted([list(point) for point in points])
    return result


def fixture():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    mesh = bpy.data.meshes.new("DeliveryMeshData")
    mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("DeliveryMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    armature = bpy.data.armatures.new("DeliveryRigData")
    rig = bpy.data.objects.new("DeliveryRig", armature)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("Root")
    bone.head, bone.tail = (0., 0., 0.), (0., 1., 0.)
    bpy.ops.object.mode_set(mode="OBJECT")
    group = obj.vertex_groups.new(name="Root")
    group.add([0, 1, 2], 1., "REPLACE")
    modifier = obj.modifiers.new("DeliverySkin", "ARMATURE")
    modifier.object = rig
    obj.parent = rig
    pose = rig.pose.bones["Root"]
    pose.rotation_mode = "XYZ"
    pose.rotation_euler.z = 0.
    pose.keyframe_insert(data_path="rotation_euler", frame=1)
    pose.rotation_euler.z = .3
    pose.keyframe_insert(data_path="rotation_euler", frame=2)
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 2
    bpy.context.scene.render.fps = 24
    obj.select_set(True)
    return obj, rig


def writer(bundle):
    fixture()
    runtime, prefs = setup(bundle)
    static_mesh = bpy.data.meshes.new("DeliveryStaticData")
    static_mesh.from_pydata([(2., 0., 0.), (3., 0., 0.), (2., 1., 0.)], [], [(0, 1, 2)])
    static = bpy.data.objects.new("DeliveryStatic", static_mesh)
    bpy.context.scene.collection.objects.link(static)
    original = {"RIGGED_ANIMATED": samples(), "STATIC": samples("DeliveryStatic")}
    records = []
    for scenario in ("STATIC", "RIGGED_ANIMATED"):
        names = ["DeliveryStatic"] if scenario == "STATIC" else ["DeliveryMesh", "DeliveryRig"]
        for format in ("GLB", "FBX"):
            path = bundle / (scenario.lower() + "." + format.lower())
            preview = runtime.dispatch("asset.export_preview", {"object_names": names,
                "format": format, "include_animation": scenario != "STATIC"})
            request = {"object_names": preview["object_names"], "format": format,
                "include_animation": scenario != "STATIC", "filepath": str(path), "expected_fingerprint": preview["fingerprint"],
                "accepted_losses": preview["required_accepted_losses"]}
            prefs.allow_save_project = False
            deny(runtime, "PERMISSION_DENIED", "asset.export", request)
            assert not path.exists()
            prefs.allow_save_project = True
            result = runtime.dispatch("asset.export", request)
            assert result["source_and_context_preserved"] and result["external_effects"]["published_bytes_verified"]
            assert not result["project_saved"] and not result["native_roundtrip_verified"]
            deny(runtime, "INVALID_ARGUMENT", "asset.export", request)
            records.append({"scenario": scenario, "format": format, "file": path.name,
                "sha256": digest(path), "bytes": path.stat().st_size})
    manifest = {"original": original, "records": records}
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {"records": records}


def reader(bundle):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    results = []
    for record in manifest["records"]:
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        path = bundle / record["file"]
        assert digest(path) == record["sha256"]
        if record["format"] == "GLB":
            assert bpy.ops.import_scene.gltf(filepath=str(path)) == {"FINISHED"}
        else:
            assert bpy.ops.import_scene.fbx(filepath=str(path), anim_offset=0.) == {"FINISHED"}
        actual = samples("DeliveryStatic" if record["scenario"] == "STATIC" else "DeliveryMesh")
        expected = manifest["original"][record["scenario"]]
        maximum = max(abs(a - b)
            for frame in expected
            for left, right in zip(expected[frame], actual[frame], strict=True)
            for a, b in zip(left, right, strict=True))
        assert maximum < 1e-5, (record["format"], maximum, actual, expected)
        results.append({"scenario": record["scenario"], "format": record["format"], "maximum_world_vertex_error": maximum,
                        "meshes": len([o for o in bpy.context.scene.objects if o.type == "MESH"]),
                        "armatures": len([o for o in bpy.context.scene.objects if o.type == "ARMATURE"])})
    return {"roundtrips": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    result = writer(args.bridge_bundle) if args.bridge_phase == "writer" else reader(args.bridge_bundle)
    result.update(phase=args.bridge_phase, process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
                  process_id=os.getpid(), blender_version=bpy.app.version_string)
    print("BLENDER_ASSET_DELIVERY_" + args.bridge_phase.upper() + "_OK " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
