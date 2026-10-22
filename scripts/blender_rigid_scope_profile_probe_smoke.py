"""Private structural Mesh/external-WM research; no complete Scene admission."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from addon import blender_codex_bridge  # noqa: E402
from addon.blender_codex_bridge.errors import BridgeError  # noqa: E402
from addon.blender_codex_bridge.tools import _rigid_authored_scope as mesh_scope  # noqa: E402
from addon.blender_codex_bridge.tools import _rigid_scene_consumers as roles  # noqa: E402
from scripts.blender_rigid_lifecycle_probe_smoke import context_state  # noqa: E402

MARKER = "BLENDER_RIGID_SCOPE_PROFILE_PROBE_OK "


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def refusal(callback):
    try:
        callback()
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED", error.to_dict()
        return error.to_dict()
    raise AssertionError("An unsupported private research scope was accepted")


def all_meshes():
    return mesh_scope.snapshot_meshes(bpy, tuple(bpy.data.meshes),
        tuple(obj for obj in bpy.data.objects if obj.type == "MESH"))


def main():
    assert not bpy.app.background
    assert os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"), "Use the isolated native runner"
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    scene = bpy.context.scene
    assert len(bpy.data.scenes) == 1
    assert {"Cube", "Camera", "Light"}.issubset(scene.objects.keys())
    context = context_state()
    native_ids = {owner.as_pointer() for owner in (*bpy.data.objects, *bpy.data.meshes, *bpy.data.collections)}
    before_roles = roles.external_scene_roles(bpy, scene)
    assert dict(before_roles)["scene_self_scope_qualified"] is False
    before_meshes = all_meshes()
    assert bpy.ops.ed.undo_push.poll()
    assert bpy.ops.ed.undo_push(message="Owned private rigid profile research") == {"FINISHED"}
    after_roles, after_meshes = roles.external_scene_roles(bpy, scene), all_meshes()
    assert dict(after_roles)["scene_self_scope_qualified"] is False
    assert before_meshes == after_meshes
    assert context_state() == context
    negatives = {}
    wm = bpy.context.window_manager
    alias_key = "_owned_rigid_profile_scene_alias"
    assert alias_key not in wm
    try:
        wm[alias_key] = scene
        negatives["raw_ui_id_alias"] = refusal(lambda: roles.external_scene_roles(bpy, scene))
    finally:
        del wm[alias_key]
    assert roles.external_scene_roles(bpy, scene) == after_roles

    scalar_key = "_owned_rigid_profile_scalar_kind"
    for label, owner, capture in (
        ("window_manager", wm, lambda: roles.external_scene_roles(bpy, scene)),
        ("mesh", bpy.data.objects["Cube"].data, all_meshes),
    ):
        assert scalar_key not in owner
        snapshots = []
        try:
            for value in (False, 0, 0.0, -0.0):
                if scalar_key in owner:
                    del owner[scalar_key]
                owner[scalar_key] = value
                assert type(owner[scalar_key]) is type(value)
                if type(value) is float:
                    assert owner[scalar_key].hex() == value.hex()
                state = capture()
                assert all(state != previous for previous in snapshots), label
                snapshots.append(state)
        finally:
            if scalar_key in owner:
                del owner[scalar_key]
    negatives["custom_scalar_types_and_signed_zero_preserved"] = True
    assert roles.external_scene_roles(bpy, scene) == after_roles
    assert all_meshes() == after_meshes

    getter_calls = []
    runtime_name = "owned_rigid_profile_runtime_probe"
    assert not hasattr(bpy.types.Mesh, runtime_name)

    def getter(owner):
        getter_calls.append(owner.as_pointer())
        raise AssertionError("Runtime Mesh getter was invoked")

    setattr(bpy.types.Mesh, runtime_name, bpy.props.FloatProperty(get=getter, set=lambda owner, value: None))
    try:
        negatives["runtime_mesh_getter"] = refusal(all_meshes)
        assert getter_calls == []
    finally:
        delattr(bpy.types.Mesh, runtime_name)
    assert all_meshes() == after_meshes

    cube = bpy.data.objects["Cube"]
    shared = bpy.data.objects.new("Owned Rigid Shared Mesh Probe", cube.data)
    try:
        compared = dict(mesh_scope.snapshot_meshes(bpy, (cube.data, cube.data), (cube, shared)))
        counts = dict(compared["aggregate_counts"])
        assert counts["meshes"] == 1 and counts["consumers"] == 2
    finally:
        bpy.data.objects.remove(shared)
    assert all_meshes() == after_meshes

    uv_mesh = cube.data.copy()
    try:
        assert len(uv_mesh.uv_layers) == 1
        added = uv_mesh.uv_layers.new(name="Owned Selector Probe")
        expected = mesh_scope.snapshot_meshes(bpy, (uv_mesh,), ())
        old_index = uv_mesh.uv_layers.active_index
        uv_mesh.uv_layers.active_index = 1 - old_index
        changed = mesh_scope.snapshot_meshes(bpy, (uv_mesh,), ())
        assert changed != expected
        uv_mesh.uv_layers.active_index = old_index
        assert mesh_scope.snapshot_meshes(bpy, (uv_mesh,), ()) == expected
        old_render = next(layer for layer in uv_mesh.uv_layers if layer.active_render)
        other = next(layer for layer in uv_mesh.uv_layers if layer != old_render)
        other.active_render = True
        assert mesh_scope.snapshot_meshes(bpy, (uv_mesh,), ()) != expected
        old_render.active_render = True
        assert mesh_scope.snapshot_meshes(bpy, (uv_mesh,), ()) == expected
        for selector in ("uv_layer_clone", "uv_layer_stencil"):
            original = getattr(uv_mesh, selector)
            other_layer = next(layer for layer in uv_mesh.uv_layers if layer != original)
            setattr(uv_mesh, selector, other_layer)
            assert mesh_scope.snapshot_meshes(bpy, (uv_mesh,), ()) != expected
            setattr(uv_mesh, selector, original)
            assert mesh_scope.snapshot_meshes(bpy, (uv_mesh,), ()) == expected
        uv_mesh.uv_layers.remove(added)
        negatives["uv_selector_changes_detected"] = {"active_index": True, "active_render": True,
                                                     "clone_and_stencil": True,
                                                     "identity_basis": "Mesh ID plus structural layer index and values"}
    finally:
        bpy.data.meshes.remove(uv_mesh)
    assert all_meshes() == after_meshes

    attribute_mesh = cube.data.copy()
    owned_material = bpy.data.materials.new("Owned Mesh Binding Probe")
    try:
        attribute_mesh.materials.append(owned_material)
        expected = mesh_scope.snapshot_meshes(bpy, (attribute_mesh,), ())
        attribute_mesh.materials.pop(index=len(attribute_mesh.materials) - 1)
        assert mesh_scope.snapshot_meshes(bpy, (attribute_mesh,), ()) != expected
        first_color = attribute_mesh.color_attributes.new("Owned First Color", "FLOAT_COLOR", "CORNER")
        attribute_mesh.color_attributes.new("Owned Second Color", "FLOAT_COLOR", "CORNER")
        attribute_mesh.color_attributes.active_color = first_color
        expected = mesh_scope.snapshot_meshes(bpy, (attribute_mesh,), ())
        attribute_mesh.color_attributes.active_color_index = 1
        assert mesh_scope.snapshot_meshes(bpy, (attribute_mesh,), ()) != expected
        negatives["material_binding_and_color_selectors_detected"] = True
    finally:
        bpy.data.meshes.remove(attribute_mesh)
        bpy.data.materials.remove(owned_material)
    assert all_meshes() == after_meshes

    normal_mesh = cube.data.copy()
    try:
        normal_mesh.normals_split_custom_set([(1., 0., 0.)] * len(normal_mesh.loops))
        assert normal_mesh.has_custom_normals
        negatives["custom_split_normals"] = refusal(lambda: mesh_scope.snapshot_meshes(bpy, (normal_mesh,), ()))
    finally:
        bpy.data.meshes.remove(normal_mesh)
    assert all_meshes() == after_meshes
    assert context_state() == context
    assert {owner.as_pointer() for owner in (*bpy.data.objects, *bpy.data.meshes, *bpy.data.collections)} == native_ids
    report = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode("ascii"),
              "ordinary_scene_preserved": True, "context_preserved": True,
              "mesh_snapshot_before": before_meshes, "mesh_snapshot_after_checkpoint": after_meshes,
              "structural_mesh_uv_match": True, "external_roles_before": before_roles,
              "external_roles_after_checkpoint": after_roles, "scene_self_scope_qualified": False,
              "shared_mesh_memoization": True, "negatives": negatives, "runtime_getter_calls": getter_calls,
              "fixture_owned_native_mutations": True, "full_main_shader_lightlink_scope_qualified": False,
              "production_cache_admission_qualified": False, "canonical_request_recovery_qualified": False,
              "public_setup_api_added": False, "project_saved": False, "release_readiness": "NOT_ASSESSED"}
    path = Path(os.environ["TMPDIR"]) / "rigid-scope-profile-research.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(MARKER + json.dumps({"blender_version": bpy.app.version_string,
        "build_hash": report["build_hash"], "evidence": str(path),
        "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "structural_mesh_uv_match": True, "scene_self_scope_qualified": False,
        "negative_cases": sorted(negatives), "release_readiness": "NOT_ASSESSED"}), flush=True)


def timer():
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()


bpy.app.timers.register(timer, first_interval=.25)
