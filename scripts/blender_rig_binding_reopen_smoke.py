"""Typed automatic binding authoring and independent fresh-process evidence."""
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
sys.path.insert(0, str(ROOT / "scripts"))
import blender_codex_bridge  # noqa: E402
import native_character_evidence as evidence  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_rig_binding_probe_smoke import fixture  # noqa: E402


def setup():
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
    for toolset in ("rigging", "animation"):
        runtime.registry.enable_toolset(toolset)
    return runtime, grants


def persistent(rig, mesh):
    def color(bone):
        return {"settings": evidence.rna(bone.color), "custom": evidence.rna(bone.color.custom)}
    return {"mesh": evidence.rest(mesh), "rig": evidence.rig_rest(rig),
            "rig_settings": evidence.rna(rig.data, {"collections", "use_extra_user"}),
            "pose": [{"name": bone.name, "stored": evidence.rna(bone, {"matrix", "matrix_channel", "matrix_basis"}), "color": color(bone)} for bone in rig.pose.bones],
            "bone_colors": [color(bone) for bone in rig.data.bones],
            "collections": [evidence.rna(collection) for collection in rig.data.collections_all],
            "action": evidence.action(rig.animation_data.action)}


def samples(rig, mesh):
    values = []
    for frame in (1, 6, 11):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        values.append(evidence.evaluated(bpy.context.scene, bpy.context.evaluated_depsgraph_get(), rig, mesh))
    bpy.context.scene.frame_set(1)
    return values


def writer(bundle):
    runtime, grants = setup()
    rig, mesh, modifier = fixture()
    uv = mesh.data.uv_layers.new(name="ProtectedUV")
    for index, loop in enumerate(uv.data):
        loop.uv = ((index % 4)/3, (index // 4)/10)
        loop.pin_uv = index % 3 == 0
    colors = mesh.data.color_attributes.new(name="ProtectedTint", type="FLOAT_COLOR", domain="CORNER")
    for item in colors.data:
        item.color = (.2, .4, .6, 1.)
    detail = mesh.data.attributes.new(name="ProtectedDetailValue", type="FLOAT", domain="POINT")
    for index, item in enumerate(detail.data):
        item.value = .125*index
    material = bpy.data.materials.new("Binding Protected Material")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (.2, .4, .6, 1.)
    shader.inputs["Roughness"].default_value = .35
    mesh.data.materials.append(material)
    mesh.data.edges[0].use_seam = True
    mesh.data.polygons[0].use_smooth = True
    original_mesh = evidence.rest(mesh)
    try:
        bound = runtime.dispatch("rig.bind_mesh", {"mesh_object": mesh.name, "armature_object": rig.name, "method": "AUTOMATIC"})
    except BridgeError as error:
        print("BINDING_REOPEN_DIAGNOSTIC " + json.dumps(error.to_dict()), flush=True)
        raise
    assert bound["verified"] and mesh.modifiers[0] == modifier
    after = evidence.rest(mesh)
    for field in ("edges", "polygons", "uv_layers", "attributes", "materials"):
        assert after[field] == original_mesh[field], field
    for vertex, before in zip(after["vertices"], original_mesh["vertices"], strict=True):
        assert vertex["co"] == before["co"]
        assert [item for item in vertex["weights"] if item[0] == 1] == [item for item in before["weights"] if item[0] == 1]
    for frame, x in ((1, 0.), (11, .5)):
        runtime.dispatch("rig.pose_transform", {"object_name": rig.name, "bone_name": "Upper", "location": [x, 0., 0.], "affected_objects": [mesh.name]})
        runtime.dispatch("animation.keyframe_insert", {"object_name": rig.name, "data_path": 'pose.bones["Upper"].location', "frame": frame, "group": "Upper", "affected_objects": [mesh.name]})
    motion = samples(rig, mesh)
    assert evidence.max_difference(motion[0]["vertices"], motion[2]["vertices"]) > .1
    frozen = persistent(rig, mesh)
    path = bundle / "automatic-binding.blend"
    grants[Permission.SAVE_PROJECT.value] = False
    try:
        runtime.dispatch("project.save", {"filepath": str(path)})
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED" and not path.exists()
    else:
        raise AssertionError("save permission bypassed")
    grants[Permission.SAVE_PROJECT.value] = True
    saved = runtime.dispatch("project.save", {"filepath": str(path)})
    assert saved["saved"]
    manifest = {"writer_process": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "content": frozen, "motion": motion, "rig": rig.name, "mesh": mesh.name,
                "native_blocking_seconds": bound["native_blocking_seconds"]}
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    blender_codex_bridge.unregister()
    return {"project_saved": True, "file_sha256": manifest["file_sha256"], "typed_auto_binding": True,
            "complete_base_attributes_uv_material_bindings_and_protected_weights": True,
            "sampled_vertices": len(mesh.data.vertices)*len(motion), "native_blocking_seconds": bound["native_blocking_seconds"],
            "visual_reviewed": False, "full_character_acceptance_verified": False}


def reader(bundle):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    path = bundle / "automatic-binding.blend"
    assert manifest["writer_process"] != os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["file_sha256"]
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    setup()
    rig, mesh = bpy.data.objects[manifest["rig"]], bpy.data.objects[manifest["mesh"]]
    motion = samples(rig, mesh)
    maximum_motion_error = evidence.max_difference(motion, manifest["motion"])
    assert maximum_motion_error <= 1e-6, maximum_motion_error
    actual = persistent(rig, mesh)
    maximum_stored_error = evidence.max_difference(actual, manifest["content"])
    assert maximum_stored_error <= 1e-6, maximum_stored_error
    assert mesh.parent == rig and len(mesh.modifiers) == 1 and mesh.modifiers[0].object == rig
    assert mesh.vertex_groups["ProtectedDetail"].lock_weight
    blender_codex_bridge.unregister()
    return {"fresh_process_reopen_verified": True, "file_sha256": manifest["file_sha256"],
            "complete_stored_content_compared": True, "sampled_vertex_and_bone_motion_compared": True,
            "maximum_motion_error": maximum_motion_error, "maximum_stored_error": maximum_stored_error,
            "visual_reviewed": False, "full_character_acceptance_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    result = writer(args.bridge_bundle) if args.bridge_phase == "writer" else reader(args.bridge_bundle)
    result.update(phase=args.bridge_phase, process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid(), blender_version=bpy.app.version_string)
    print("BLENDER_RIG_BINDING_" + args.bridge_phase.upper() + "_OK " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
