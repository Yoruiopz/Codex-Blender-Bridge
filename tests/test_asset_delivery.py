from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.asset_delivery import AssetDeliveryTools

IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))


class Objects(list):
    def __contains__(self, item):
        return any(obj.name == item if isinstance(item, str) else obj is item for obj in self)


def mesh_object(name="Asset"):
    data = NS(library=None, override_library=None, is_editable=True, animation_data=None,
        vertices=[NS(co=(0., 0., 0.), groups=[]), NS(co=(1., 0., 0.), groups=[]), NS(co=(0., 1., 0.), groups=[])],
        polygons=[NS(vertices=(0, 1, 2), use_smooth=False)], uv_layers=[], shape_keys=None,
        color_attributes=[], attributes=[NS(name="position", is_internal=False)], has_custom_normals=False)
    return NS(name=name, type="MESH", data=data, library=None, override_library=None, is_editable=True,
        visible_get=lambda: True, hide_render=False, hide_viewport=False, hide_get=lambda: False,
        hide_select=False, instance_type="NONE", constraints=[], rigid_body=None, parent=None,
        parent_type="OBJECT", matrix_basis=IDENTITY, matrix_parent_inverse=IDENTITY,
        matrix_world=IDENTITY, animation_data=None, modifiers=[], vertex_groups=[], material_slots=[])


def artifact(format):
    if format == "FBX":
        return b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7400) + b"fixture binary payload"
    raw = json.dumps({"asset": {"version": "2.0"}, "meshes": [{}]}).encode()
    raw += b" " * (-len(raw) % 4)
    return b"glTF" + struct.pack("<II", 2, 20 + len(raw)) + struct.pack("<II", len(raw), 0x4E4F534A) + raw


@pytest.fixture
def asset(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(addon_package + ".tools.asset_delivery")
    permissions = importlib.import_module(addon_package + ".permissions")
    state = importlib.import_module(addon_package + ".state").BridgeState()
    source, protected = mesh_object(), mesh_object("Protected")
    objects = Objects([source, protected])
    scene = NS(unit_settings=NS(scale_length=1., system="METRIC"), name="Scene",
        frame_start=1, frame_end=2, frame_current=1, frame_subframe=0., render=NS(fps=24, fps_base=1.))
    bpy = NS(data=NS(objects=objects), context=NS(mode="OBJECT", scene=scene,
        view_layer=NS(objects=objects), selected_objects=[protected]))
    objects.active = protected
    grants = {permission.value: True for permission in permissions.Permission}
    manager = permissions.PermissionManager(lambda: grants)
    context = NS(require=lambda *p: manager.require(p), check_cancelled=None, state=state)
    prefs = NS(asset_directory=str(tmp_path))
    monkeypatch.setattr(module, "get_preferences", lambda: prefs)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_native", lambda _bpy, _objects, path, format, _include: path.write_bytes(artifact(format)))
    return NS(module=module, source=source, protected=protected, bpy=bpy, context=context,
              grants=grants, manager=manager, prefs=prefs, root=tmp_path)


def request(env, format="GLB", **updates):
    preview = env.module.export_preview(env.context, {"object_names": ["Asset"], "format": format})
    return {"object_names": ["Asset"], "format": format, "filepath": str(env.root / ("asset." + format.lower())),
            "expected_fingerprint": preview["fingerprint"], "accepted_losses": preview["required_accepted_losses"], **updates}


@pytest.mark.parametrize("format", ["GLB", "FBX"])
def test_export_preserves_source_and_publishes_complete_no_clobber_artifact(asset, format):
    env = asset
    params = request(env, format)
    before = env.module._context(env.bpy)
    result = env.module.export_asset(env.context, params)
    path = Path(params["filepath"])
    assert result["exported"] and result["source_and_context_preserved"]
    assert env.module._context(env.bpy) == before
    effects = result["external_effects"]
    assert path.read_bytes() == artifact(format)
    assert effects["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert effects["file_bytes"] == path.stat().st_size and effects["published_bytes_verified"]
    assert effects["staging_cleanup"] == "removed" and effects["retained_staging_path"] is None
    assert not result["native_roundtrip_verified"] and not result["project_saved"]
    assert not effects["native_undo_removes_external_file"]
    with pytest.raises(env.module.BridgeError, match="exists"):
        env.module.export_asset(env.context, params)
    assert path.read_bytes() == artifact(format)


def test_preview_reads_scene_without_file_grants_or_filesystem_changes(asset):
    env = asset
    env.grants["ACCESS_EXTERNAL_FILES"] = env.grants["SAVE_PROJECT"] = False
    preview = env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB"})
    assert not preview["file_written"] and len(preview["fingerprint"]) == 64
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("permission", ["INSPECT_SCENE", "EDIT_SCENE", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT"])
def test_export_denial_happens_before_path_probes(asset, monkeypatch, permission):
    env = asset
    params = request(env)
    env.grants[permission] = False
    monkeypatch.setattr(env.module, "_approved_output", lambda *_: pytest.fail("Denied output probed"))
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, params)
    assert caught.value.code == "PERMISSION_DENIED"


@pytest.mark.parametrize("change", ["vertex", "transform", "new_parent", "frame"])
def test_changed_preview_scope_rejected_before_staging(asset, change):
    env = asset
    params = request(env)
    if change == "vertex":
        env.source.data.vertices[1].co = (2., 0., 0.)
    elif change == "transform":
        env.source.matrix_basis = ((2., 0., 0., 0.), *IDENTITY[1:])
    elif change == "new_parent":
        env.source.parent = env.protected
    else:
        env.bpy.context.scene.frame_current = 2
    with pytest.raises(env.module.BridgeError):
        env.module.export_asset(env.context, params)
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("value", [[], ["AXIS_CONVERSION"], ["VERTEX_SPLITS", "AXIS_CONVERSION", "OTHER"]])
def test_format_losses_require_exact_preview_acknowledgement(asset, value):
    env = asset
    with pytest.raises(env.module.BridgeError, match="accepted_losses"):
        env.module.export_asset(env.context, request(env, accepted_losses=value))
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("change", ["linked", "override", "readonly", "hidden", "selection_locked", "instanced",
    "mode", "material", "modifier", "shape_keys", "custom_attribute", "custom_normals", "not_triangle", "units", "constraints", "drivers"])
def test_unsupported_scope_is_rejected_before_writes(asset, change):
    env = asset
    obj = env.source
    if change == "linked":
        obj.library = object()
    elif change == "override":
        obj.override_library = object()
    elif change == "readonly":
        obj.is_editable = False
    elif change == "hidden":
        obj.hide_render = True
    elif change == "selection_locked":
        obj.hide_select = True
    elif change == "instanced":
        obj.instance_type = "COLLECTION"
    elif change == "mode":
        env.bpy.context.mode = "EDIT_MESH"
    elif change == "material":
        obj.material_slots = [NS(material=object())]
    elif change == "modifier":
        obj.modifiers = [NS(type="NODES")]
    elif change == "shape_keys":
        obj.data.shape_keys = object()
    elif change == "custom_attribute":
        obj.data.attributes.append(NS(name="artist_data", is_internal=False))
    elif change == "custom_normals":
        obj.data.has_custom_normals = True
    elif change == "not_triangle":
        obj.data.polygons[0].vertices = (0, 1, 2, 0)
    elif change == "units":
        env.bpy.context.scene.unit_settings.scale_length = .01
    elif change == "constraints":
        obj.constraints = [object()]
    else:
        obj.animation_data = NS(drivers=[object()], nla_tracks=[], action=None)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB"})
    assert caught.value.code == "NOT_IMPLEMENTED" and list(env.root.iterdir()) == []


@pytest.mark.parametrize("names", [[], ["Asset", "Asset"], ["Missing"], ["Asset\n"], "Asset", [True], ["Asset"] * 65])
def test_invalid_exact_scope_names_fail(asset, names):
    env = asset
    with pytest.raises(env.module.BridgeError):
        env.module.export_preview(env.context, {"object_names": names, "format": "GLB"})


@pytest.mark.parametrize("raw", ["relative.glb", "//remote/asset.glb", "../asset.glb", "output.fbx"])
def test_invalid_output_paths_leave_no_files(asset, raw):
    env = asset
    with pytest.raises(env.module.BridgeError):
        env.module.export_asset(env.context, request(env, filepath=raw))
    assert list(env.root.iterdir()) == []


def test_empty_approved_asset_folder_blocks_export(asset):
    env = asset
    env.prefs.asset_directory = ""
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    assert caught.value.code == "PERMISSION_DENIED" and list(env.root.iterdir()) == []


def test_existing_competitor_wins_without_overwrite(asset, monkeypatch):
    env = asset
    params = request(env)
    native = env.module._native
    def competing(*args):
        native(*args)
        Path(params["filepath"]).write_bytes(b"competitor")
    monkeypatch.setattr(env.module, "_native", competing)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, params)
    assert Path(params["filepath"]).read_bytes() == b"competitor"
    effects = caught.value.context["external_effects"]
    assert not effects["publication_attempted"] and effects["staging_cleanup"] == "removed"


def test_revoked_file_consent_retains_exact_owned_staging(asset, monkeypatch):
    env = asset
    native = env.module._native
    def revoked(*args):
        native(*args)
        env.grants["ACCESS_EXTERNAL_FILES"] = False
    monkeypatch.setattr(env.module, "_native", revoked)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert effects["staging_cleanup"] == "retained" and Path(effects["retained_staging_path"]).is_dir()
    assert not effects["file_published"] and not Path(effects["filepath"]).exists()


def test_cancellation_after_publication_keeps_final_file_and_effects(asset, monkeypatch):
    env = asset
    original_link = env.module.os.link
    def linked(*args, **kwargs):
        original_link(*args, **kwargs)
        def cancelled():
            raise env.module.BridgeError("TIMEOUT", "caller cancelled")
        env.context.check_cancelled = cancelled
    monkeypatch.setattr(env.module.os, "link", linked)
    params = request(env)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, params)
    effects = caught.value.context["external_effects"]
    assert caught.value.code == "TIMEOUT" and effects["file_published"]
    assert Path(params["filepath"]).read_bytes() == artifact("GLB")
    assert effects["staging_cleanup"] == "removed" and caught.value.context["possible_mutation"]


def test_possible_link_effect_is_reported_unknown_and_never_deleted(asset, monkeypatch):
    env = asset
    link = env.module.os.link
    def uncertain(*args, **kwargs):
        link(*args, **kwargs)
        raise OSError("publication completion unknown")
    monkeypatch.setattr(env.module.os, "link", uncertain)
    params = request(env)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, params)
    effects = caught.value.context["external_effects"]
    assert effects["publication_outcome_unknown"] and not effects["file_published"]
    assert Path(params["filepath"]).is_file() and caught.value.context["possible_mutation"]


def test_native_source_changes_prevent_publication_and_require_reinspection(asset, monkeypatch):
    env = asset
    native = env.module._native
    def changed(*args):
        native(*args)
        env.source.data.vertices[0].co = (5., 0., 0.)
    monkeypatch.setattr(env.module, "_native", changed)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    assert not caught.value.context["source_and_context_preserved"]
    assert caught.value.context["possible_mutation"]
    assert not Path(caught.value.context["external_effects"]["filepath"]).exists()


def test_unexpected_native_sidecars_are_retained_without_recursive_cleanup(asset, monkeypatch):
    env = asset
    native = env.module._native
    def sidecar(bpy, objects, path, format, include):
        native(bpy, objects, path, format, include)
        (path.parent / "unexpected.bin").write_bytes(b"keep evidence")
    monkeypatch.setattr(env.module, "_native", sidecar)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert effects["staging_cleanup"] == "retained"
    assert (Path(effects["retained_staging_path"]) / "unexpected.bin").read_bytes() == b"keep evidence"


def test_changed_staging_bytes_are_not_removed_by_cleanup(asset, monkeypatch):
    env = asset
    original = env.module._Staging.publish
    def changed(self):
        self.stage.write_bytes(b"external staging edit")
        original(self)
    monkeypatch.setattr(env.module._Staging, "publish", changed)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert effects["staging_cleanup"] == "retained"
    assert (Path(effects["retained_staging_path"]) / "payload.glb").read_bytes() == b"external staging edit"


def test_strict_mcp_schema_and_exact_forwarding():
    hints = get_type_hints(AssetDeliveryTools.asset_export, include_extras=True)
    for name, value in (("object_names", [True]), ("format", "OBJ"), ("filepath", 3),
                        ("include_animation", 1), ("expected_fingerprint", "wrong"), ("accepted_losses", ["ANY"])):
        with pytest.raises(ValidationError):
            TypeAdapter(hints[name]).validate_python(value)
    calls = []
    async def call(method, values):
        calls.append((method, values))
    tool = AssetDeliveryTools(NS(call=call))
    asyncio.run(tool.asset_export(["Mesh"], "GLB", "/approved/a.glb", "a" * 64, ["VERTEX_SPLITS", "AXIS_CONVERSION"]))
    assert calls == [("asset.export", {"object_names": ["Mesh"], "format": "GLB", "filepath": "/approved/a.glb",
        "expected_fingerprint": "a" * 64, "accepted_losses": ["VERTEX_SPLITS", "AXIS_CONVERSION"], "include_animation": False})]


def rigged(env):
    rig = mesh_object("Rig")
    rig.type = "ARMATURE"
    rig.data = NS(library=None, override_library=None, is_editable=True, animation_data=None,
        bones=[NS(name="Root", parent=None, matrix_local=IDENTITY, use_deform=True)], pose_position="POSE")
    rig.pose = NS(bones=[NS(name="Root", matrix_basis=IDENTITY, constraints=[], custom_shape=None,
        path_from_id=lambda path: 'pose.bones["Root"].' + path)])
    env.bpy.data.objects.append(rig)
    env.source.vertex_groups = [NS(index=0, name="Root")]
    env.source.modifiers = [NS(type="ARMATURE", object=rig, show_viewport=True, show_render=True,
        use_vertex_groups=True, use_bone_envelopes=False, use_deform_preserve_volume=False, vertex_group="")]
    for vertex in env.source.data.vertices:
        vertex.groups = [NS(group=0, weight=1.)]
    return rig


def test_skin_preview_records_rig_and_normalized_influences(asset):
    env = asset
    rigged(env)
    preview = env.module.export_preview(env.context, {"object_names": ["Asset", "Rig"], "format": "GLB"})
    assert preview["objects"][1]["bones"] == 1
    assert "BONE_AXIS_CONVERSION" in preview["required_accepted_losses"]


@pytest.mark.parametrize("change", ["missing_rig", "unnormalized", "unweighted", "unknown_bone", "envelope", "preserve_volume", "mask", "pose", "nan"])
def test_unreviewed_skinning_fails_before_publication(asset, change):
    env = asset
    rig = rigged(env)
    names = ["Asset", "Rig"]
    if change == "missing_rig":
        names = ["Asset"]
    elif change == "unnormalized":
        env.source.data.vertices[0].groups[0].weight = .5
    elif change == "unweighted":
        env.source.data.vertices[0].groups = []
    elif change == "unknown_bone":
        env.source.vertex_groups[0].name = "Missing"
    elif change == "envelope":
        env.source.modifiers[0].use_bone_envelopes = True
    elif change == "preserve_volume":
        env.source.modifiers[0].use_deform_preserve_volume = True
    elif change == "mask":
        env.source.modifiers[0].vertex_group = "Root"
    elif change == "pose":
        rig.pose.bones[0].matrix_basis = ((2., 0., 0., 0.), *IDENTITY[1:])
    else:
        env.source.data.vertices[0].groups[0].weight = float("nan")
    with pytest.raises(env.module.BridgeError):
        env.module.export_preview(env.context, {"object_names": names, "format": "GLB"})
    assert list(env.root.iterdir()) == []


def test_animation_is_never_silently_omitted_and_requires_sampled_limits(asset):
    env = asset
    env.source.animation_data = NS(drivers=[], nla_tracks=[], action=NS(name="Motion", library=None,
        override_library=None, is_editable=True, fcurves=[], layers=[]), action_slot=None)
    with pytest.raises(env.module.BridgeError, match="include_animation"):
        env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB"})
    preview = env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB", "include_animation": True})
    assert "SAMPLED_INTEGER_FRAMES" in preview["required_accepted_losses"]
    env.bpy.context.scene.frame_end = 251
    with pytest.raises(env.module.BridgeError, match="250"):
        env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB", "include_animation": True})
