from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import struct
from dataclasses import replace
from itertools import count
from pathlib import Path
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.asset_delivery import AssetDeliveryTools

IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
NATIVE_IDS = count(1)


def native_id(value):
    value.session_uid = next(NATIVE_IDS)
    value.as_pointer = lambda: value.session_uid * 16
    return value


class Objects(list):
    def __contains__(self, item):
        return any(obj.name == item if isinstance(item, str) else obj is item for obj in self)


def mesh_object(name="Asset"):
    data = NS(library=None, override_library=None, is_editable=True, animation_data=None,
        vertices=[NS(co=(0., 0., 0.), groups=[]), NS(co=(1., 0., 0.), groups=[]), NS(co=(0., 1., 0.), groups=[])],
        polygons=[NS(vertices=(0, 1, 2), use_smooth=False)], uv_layers=[], shape_keys=None,
        color_attributes=[], attributes=[NS(name="position", is_internal=False)], has_custom_normals=False)
    obj = native_id(NS(name=name, type="MESH", data=native_id(data), library=None, override_library=None, is_editable=True,
        visible_get=lambda: True, hide_render=False, hide_viewport=False, hide_get=lambda: False,
        hide_select=False, instance_type="NONE", constraints=[], rigid_body=None, parent=None,
        parent_type="OBJECT", matrix_basis=IDENTITY, matrix_parent_inverse=IDENTITY,
        matrix_world=IDENTITY, animation_data=None, modifiers=[], vertex_groups=[], material_slots=[], selected=False))
    obj.select_get = lambda **_kwargs: obj.selected
    obj.select_set = lambda value, **_kwargs: setattr(obj, "selected", value)
    return obj


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
    protected.selected = True
    scene = native_id(NS(unit_settings=NS(scale_length=1., system="METRIC"), name="Scene",
        frame_start=1, frame_end=2, frame_current=1, frame_subframe=0., render=NS(fps=24, fps_base=1.)))
    bpy = NS(data=NS(objects=objects), context=NS(mode="OBJECT", scene=scene,
        view_layer=NS(objects=objects, as_pointer=lambda: 1024), selected_objects=[protected]))
    objects.active = protected
    grants = {permission.value: True for permission in permissions.Permission}
    manager = permissions.PermissionManager(lambda: grants)
    registry = importlib.import_module(addon_package + ".tool_registry").ToolRegistry(enabled_toolsets=("asset_delivery",))
    module.register_tools(registry)
    context = NS(require=lambda *p: manager.require(p), check_cancelled=None, state=state, registry=registry)
    prefs = NS(asset_directory=str(tmp_path))
    monkeypatch.setattr(module, "get_preferences", lambda: prefs)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    real_native = module._native
    def native_output(_bpy, _objects, path, format, _include, *, transaction):
        path.write_bytes(artifact(format))
        transaction.capture_output()
    monkeypatch.setattr(module, "_native", native_output)
    return NS(module=module, source=source, protected=protected, bpy=bpy, context=context,
              grants=grants, manager=manager, prefs=prefs, root=tmp_path, real_native=real_native, state=state)


def request(env, format="GLB", **updates):
    preview = env.module.export_preview(env.context, {"object_names": ["Asset"], "format": format,
                                                   "include_animation": updates.get("include_animation", False)})
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
    def competing(*args, **kwargs):
        native(*args, **kwargs)
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
    def revoked(*args, **kwargs):
        native(*args, **kwargs)
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
    assert effects["staging_cleanup"] == "retained" and caught.value.context["possible_mutation"]


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
    def changed(*args, **kwargs):
        native(*args, **kwargs)
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
    def sidecar(bpy, objects, path, format, include, **kwargs):
        native(bpy, objects, path, format, include, **kwargs)
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
    rig.data = native_id(NS(library=None, override_library=None, is_editable=True, animation_data=None,
        bones=[NS(name="Root", parent=None, matrix_local=IDENTITY, use_deform=True)], pose_position="POSE"))
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
    env.source.animation_data = NS(drivers=[], nla_tracks=[], action=native_id(NS(name="Motion", library=None,
        override_library=None, is_editable=True, fcurves=[], layers=[])), action_slot=None)
    with pytest.raises(env.module.BridgeError, match="include_animation"):
        env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB"})
    preview = env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB", "include_animation": True})
    assert "SAMPLED_INTEGER_FRAMES" in preview["required_accepted_losses"]
    env.bpy.context.scene.frame_end = 251
    with pytest.raises(env.module.BridgeError, match="250"):
        env.module.export_preview(env.context, {"object_names": ["Asset"], "format": "GLB", "include_animation": True})


def lose_authority(env, mode):
    if mode == "pause":
        env.state.set_paused(True)
    elif mode == "stop":
        env.state.set_emergency_stopped(True)
    elif mode == "cancel":
        def cancelled():
            raise env.module.BridgeError("TIMEOUT", "queued request canceled")
        env.context.check_final_request = cancelled
    elif mode in {"disconnect", "expired", "rejected"}:
        lifecycle = importlib.import_module(env.module.__package__.rsplit(".", 1)[0] + ".request_lifecycle")
        lifetime = lifecycle.RequestLifetime(deadline=0. if mode == "expired" else float("inf"))
        if mode == "disconnect":
            lifetime.connection = lifecycle.ConnectionLifetime()
            lifetime.connection.disconnected.set()
        if mode == "rejected":
            lifetime.rejected.set()
        env.context.request_lifecycle = lifetime
    elif mode == "toolset":
        env.context.registry.disable_toolset("asset_delivery")
    elif mode == "spec":
        spec = env.context.registry.get("asset.export")
        env.context.registry._tools["asset.export"] = replace(spec)
    elif mode == "registry":
        previous = env.context.registry
        replacement = type(previous)(enabled_toolsets=("asset_delivery",))
        env.module.register_tools(replacement)
        replacement._tools["asset.export"] = previous.get("asset.export")
        env.context.registry = replacement
    else:
        env.grants["SAVE_PROJECT"] = False


@pytest.mark.parametrize("mode", ["pause", "stop", "cancel", "disconnect", "expired", "rejected", "toolset", "spec", "registry"])
def test_last_grant_provider_cannot_authorize_path_access_after_lifetime_change(asset, monkeypatch, mode):
    env = asset
    params = request(env)
    def provider():
        lose_authority(env, mode)
        return env.grants
    monkeypatch.setattr(env.manager, "_source", provider)
    monkeypatch.setattr(env.module, "_approved_output", lambda *_: pytest.fail("A stopped entry probed a path"))
    with pytest.raises(env.module.BridgeError):
        env.module.export_asset(env.context, params)
    assert list(env.root.iterdir()) == []


def test_permission_provider_cannot_replace_accepted_request_arguments(asset, monkeypatch):
    env = asset
    params = request(env)
    def provider():
        params["accepted_losses"].reverse()
        return env.grants
    monkeypatch.setattr(env.manager, "_source", provider)
    with pytest.raises(env.module.BridgeError, match="arguments changed"):
        env.module.export_asset(env.context, params)
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("changed", ["object_uid", "data_uid", "process_nonce"])
def test_preview_binds_native_UID_even_at_same_pointer_and_process_nonce(asset, monkeypatch, changed):
    env = asset
    params = request(env)
    if changed == "process_nonce":
        monkeypatch.setattr(env.module, "SESSION_NONCE", "f" * 32)
    else:
        owner = env.source if changed == "object_uid" else env.source.data
        pointer = owner.as_pointer()
        owner.as_pointer = lambda: pointer
        owner.session_uid += 10000
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.export_asset(env.context, params)
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("uid", [None, False, 0, -1, "12"])
def test_asset_identity_does_not_fall_back_when_native_UID_is_unavailable(asset, uid):
    asset.source.session_uid = uid
    with pytest.raises(asset.module.BridgeError) as caught:
        asset.module.export_preview(asset.context, {"object_names": ["Asset"], "format": "GLB"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert list(asset.root.iterdir()) == []


def test_same_pointer_action_replacement_invalidates_animated_preview(asset):
    env = asset
    action = native_id(NS(name="Motion", library=None, override_library=None, is_editable=True, fcurves=[], layers=[]))
    env.source.animation_data = NS(drivers=[], nla_tracks=[], action=action, action_slot=None)
    params = request(env, include_animation=True)
    pointer = action.as_pointer()
    action.as_pointer = lambda: pointer
    action.session_uid += 10000
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.export_asset(env.context, params)
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("state", ["pause", "stop"])
def test_readonly_preview_remains_available_under_pause_and_stop(asset, state):
    lose_authority(asset, state)
    result = asset.module.export_preview(asset.context, {"object_names": ["Asset"], "format": "GLB"})
    assert not result["file_written"] and list(asset.root.iterdir()) == []


def test_terminal_source_scope_measurement_invokes_no_permission_provider(asset, monkeypatch):
    env = asset
    params = {"object_names": ["Asset"], "format": "GLB"}
    entry = env.module._Entry(env.context, "asset.export_preview", params)
    entry.authorize()
    monkeypatch.setattr(env.context, "require", lambda *_: pytest.fail("A provider ran inside the terminal source read"))
    _bpy, objects, preview = env.module._scope(env.context, entry.params, entry=entry, authorize=False)
    entry.final()
    assert objects == [env.source] and len(preview["fingerprint"]) == 64


def native_context_case(env, monkeypatch, after_export):
    writes = []
    for obj in env.bpy.context.view_layer.objects:
        original = obj.select_set
        def selected(value, *, obj=obj, original=original, **kwargs):
            writes.append((obj.name, value))
            original(value, **kwargs)
        monkeypatch.setattr(obj, "select_set", selected)
    def exported(**kwargs):
        Path(kwargs["filepath"]).write_bytes(artifact("GLB"))
        after_export(writes)
        return {"FINISHED"}
    env.bpy.ops = NS(export_scene=NS(gltf=exported))
    monkeypatch.setattr(env.module, "_native", env.real_native)
    return writes


def test_native_context_restores_only_the_predicted_owned_selection_prefix(asset, monkeypatch):
    env = asset
    original = env.module._context(env.bpy)
    writes = native_context_case(env, monkeypatch, lambda _writes: None)
    result = env.module.export_asset(env.context, request(env))
    assert result["exported"] and env.module._context(env.bpy) == original
    assert writes == [("Asset", False), ("Protected", False), ("Asset", True), ("Asset", False), ("Protected", True)]


@pytest.mark.parametrize("mode", ["pause", "stop", "cancel", "disconnect", "expired", "rejected", "toolset", "spec", "registry", "revoke"])
def test_late_grant_provider_stops_context_restore_and_filesystem_cleanup(asset, monkeypatch, mode):
    env = asset
    armed, at_export = [False], []
    def after_export(writes):
        at_export.extend(writes)
        armed[0] = True
    writes = native_context_case(env, monkeypatch, after_export)
    def provider():
        if armed[0]:
            armed[0] = False
            lose_authority(env, mode)
        return env.grants
    monkeypatch.setattr(env.manager, "_source", provider)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    assert writes == at_export == [("Asset", False), ("Protected", False), ("Asset", True)]
    effects = caught.value.context["external_effects"]
    assert effects["staging_cleanup"] == "retained" and not effects["file_published"]
    assert (Path(effects["retained_staging_path"]) / "payload.glb").read_bytes() == artifact("GLB")
    assert not caught.value.context["native_context_restored"]
    assert caught.value.context["possible_mutation"]


@pytest.mark.parametrize("drift", ["selection", "frame", "source"])
def test_manual_drift_is_not_adopted_as_an_owned_native_context_prefix(asset, monkeypatch, drift):
    env = asset
    before_restore = []
    def manual(writes):
        before_restore.extend(writes)
        if drift == "selection":
            env.protected.selected = True
        elif drift == "frame":
            env.bpy.context.scene.frame_current = 2
        else:
            env.source.data.vertices[0].co = (9., 0., 0.)
    writes = native_context_case(env, monkeypatch, manual)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    assert writes == before_restore
    assert caught.value.context["external_effects"]["staging_cleanup"] == "retained"
    assert not caught.value.context["source_and_context_preserved"]


def test_publication_rechecks_source_without_providers_after_last_grant(asset, monkeypatch):
    env = asset
    armed = [False]
    publish = env.module._Staging.publish
    def arm(self):
        armed[0] = True
        return publish(self)
    def provider():
        if armed[0]:
            armed[0] = False
            env.source.data.vertices[0].co = (4., 0., 0.)
        return env.grants
    monkeypatch.setattr(env.module._Staging, "publish", arm)
    monkeypatch.setattr(env.manager, "_source", provider)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert not effects["publication_attempted"] and not Path(effects["filepath"]).exists()
    assert effects["staging_cleanup"] == "retained"


def test_cleanup_rechecks_authority_before_directory_removal_after_owned_unlink(asset, monkeypatch):
    env = asset
    unlink = Path.unlink
    def stopped_after_unlink(path, *args, **kwargs):
        result = unlink(path, *args, **kwargs)
        if path.name == "payload.glb":
            env.state.set_paused(True)
        return result
    monkeypatch.setattr(Path, "unlink", stopped_after_unlink)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert caught.value.code == "AGENT_PAUSED" and effects["file_published"]
    assert Path(effects["filepath"]).is_file()
    assert effects["staging_cleanup"] == "retained"
    assert Path(effects["retained_staging_path"]).is_dir()


@pytest.mark.parametrize("loss", ["pause", "revoke", "source", "selection"])
def test_observed_refusal_is_sticky_before_any_provider_can_regrant_or_resume(asset, monkeypatch, loss):
    env = asset
    at_export, calls = [], []
    def after_export(writes):
        at_export.extend(writes)
        def trying_to_resume():
            calls.append(loss)
            if len(calls) > 1:
                pytest.fail("An observed refusal invoked a later provider to regain authority")
            if loss == "pause":
                env.state.set_paused(True)
            elif loss == "revoke":
                env.grants["SAVE_PROJECT"] = False
            elif loss == "source":
                env.source.data.vertices[0].co = (7., 0., 0.)
            else:
                env.protected.selected = True
            return env.grants
        monkeypatch.setattr(env.manager, "_source", trying_to_resume)
    writes = native_context_case(env, monkeypatch, after_export)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    assert calls == [loss] and writes == at_export
    effects = caught.value.context["external_effects"]
    assert effects["staging_cleanup"] == "retained" and not effects["file_published"]
    assert (Path(effects["retained_staging_path"]) / "payload.glb").read_bytes() == artifact("GLB")


def test_ordinary_native_error_allows_only_live_known_prefix_restoration(asset, monkeypatch):
    env = asset
    before = env.module._context(env.bpy)
    writes = native_context_case(env, monkeypatch, lambda _writes: None)
    def native_error(**_kwargs):
        raise RuntimeError("ordinary exporter failure before file output")
    env.bpy.ops.export_scene.gltf = native_error
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["native_context_restored"]
    assert caught.value.context["source_and_context_preserved"]
    assert env.module._context(env.bpy) == before
    assert len(writes) == 5 and caught.value.context["external_effects"]["staging_cleanup"] == "removed"


def test_staging_CAS_refusal_does_not_reinvoke_a_provider_to_repair_old_state(asset, monkeypatch):
    env = asset
    publish, calls = env.module._Staging.publish, []
    def changed(self):
        self.stage.write_bytes(b"newer manual staging bytes")
        def provider():
            calls.append("provider")
            if len(calls) > 1:
                pytest.fail("Staging CAS refusal retried a permission provider")
            return env.grants
        monkeypatch.setattr(env.manager, "_source", provider)
        return publish(self)
    monkeypatch.setattr(env.module._Staging, "publish", changed)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert calls == ["provider"] and not effects["publication_attempted"]
    assert effects["staging_cleanup"] == "retained"
    assert (Path(effects["retained_staging_path"]) / "payload.glb").read_bytes() == b"newer manual staging bytes"


def test_missing_owned_stage_latches_before_a_later_provider_can_restore_its_inode(asset, monkeypatch):
    env = asset
    original_hash, retried, moved = env.module._Staging.hash, [], []
    def hash_missing(self, path, *, authorize=True):
        if not authorize:
            backup = path.with_name("moved-payload.glb")
            path.rename(backup)
            moved.append(backup)
            def restoring_provider():
                retried.append("restored moved inode")
                backup.rename(path)
                return env.grants
            monkeypatch.setattr(env.manager, "_source", restoring_provider)
        return original_hash(self, path, authorize=authorize)
    monkeypatch.setattr(env.module._Staging, "hash", hash_missing)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert retried == [] and len(moved) == 1
    assert moved[0].read_bytes() == artifact("GLB") and effects["staging_cleanup"] == "retained"
    assert not effects["publication_attempted"]


def test_unreadable_published_verification_path_latches_before_cleanup_provider(asset, monkeypatch):
    env = asset
    lstat, seen, retried = Path.lstat, [False], []
    params = request(env)
    target = Path(params["filepath"])
    def unreadable(path, *args, **kwargs):
        if path == target and path.exists() and not seen[0]:
            seen[0] = True
            raise PermissionError("injected verification identity read failure")
        return lstat(path, *args, **kwargs)
    def provider():
        if seen[0]:
            retried.append("later grant")
        return env.grants
    monkeypatch.setattr(Path, "lstat", unreadable)
    monkeypatch.setattr(env.manager, "_source", provider)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, params)
    effects = caught.value.context["external_effects"]
    # A competing target is absent until the link; its first existing lstat is
    # the post-publication verification read, not the ordinary no-clobber test.
    assert seen[0] and retried == [] and effects["file_published"]
    assert target.read_bytes() == artifact("GLB") and effects["staging_cleanup"] == "retained"


@pytest.mark.parametrize("point", ["pins", "placeholder_fstat"])
def test_open_scope_setup_failure_latches_before_cleanup_provider(asset, monkeypatch, point):
    env = asset
    failed, retried, fd = [False], [], [None]
    class Pins:
        def __init__(self, _path):
            if point == "pins":
                failed[0] = True
                raise OSError("injected directory pin setup failure")
        def close(self):
            pass
    monkeypatch.setattr(env.module, "_DirectoryPins", Pins)
    original_open, original_fstat = env.module.os.open, env.module.os.fstat
    def opened(path, *args, **kwargs):
        result = original_open(path, *args, **kwargs)
        if Path(path).name == "payload.glb":
            fd[0] = result
        return result
    def fstat(descriptor):
        if point == "placeholder_fstat" and descriptor == fd[0] and not failed[0]:
            failed[0] = True
            raise OSError("injected placeholder fstat failure")
        return original_fstat(descriptor)
    def provider():
        if failed[0]:
            retried.append("later grant")
        return env.grants
    monkeypatch.setattr(env.module.os, "open", opened)
    monkeypatch.setattr(env.module.os, "fstat", fstat)
    monkeypatch.setattr(env.manager, "_source", provider)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert failed[0] and retried == [] and effects["staging_cleanup"] == "retained"
    assert Path(effects["retained_staging_path"]).is_dir()


@pytest.mark.parametrize("point,gate_number", [("mkdir", 1), ("placeholder", 2), ("seal_open", 3), ("fsync", 4)])
def test_staging_writes_recheck_complete_source_after_the_last_provider(asset, monkeypatch, point, gate_number):
    env = asset
    write_check, count, armed, writes = env.module._Staging.write_check, [0], [False], []
    def checking(self):
        count[0] += 1
        armed[0] = count[0] == gate_number
        return write_check(self)
    def provider():
        if armed[0]:
            armed[0] = False
            env.source.data.vertices[0].co = (6., 0., 0.)
        return env.grants
    mkdir, opened, fsync, file_open = env.module.tempfile.mkdtemp, env.module.os.open, env.module.os.fsync, Path.open
    def made(*args, **kwargs):
        writes.append("mkdir")
        return mkdir(*args, **kwargs)
    def placeholder(path, *args, **kwargs):
        if Path(path).name == "payload.glb":
            writes.append("placeholder")
        return opened(path, *args, **kwargs)
    def synced(descriptor):
        writes.append("fsync")
        return fsync(descriptor)
    def file_opened(path, mode="r", *args, **kwargs):
        if path.name == "payload.glb" and mode == "r+b":
            writes.append("seal_open")
        return file_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(env.module._Staging, "write_check", checking)
    monkeypatch.setattr(env.manager, "_source", provider)
    monkeypatch.setattr(env.module.tempfile, "mkdtemp", made)
    monkeypatch.setattr(env.module.os, "open", placeholder)
    monkeypatch.setattr(env.module.os, "fsync", synced)
    monkeypatch.setattr(Path, "open", file_opened)
    with pytest.raises(env.module.BridgeError):
        env.module.export_asset(env.context, request(env))
    assert point not in writes
    assert not (env.root / "asset.glb").exists()


@pytest.mark.parametrize("service", ["state", "request_lifecycle", "check_final_request", "check_final_job", "checkpoint_admission"])
def test_last_provider_cannot_replace_the_original_caller_services(asset, monkeypatch, service):
    env = asset
    params = request(env)
    def replaced_hook():
        pytest.fail("Replacement caller service was invoked")
    replacements = {"state": NS(snapshot=replaced_hook), "request_lifecycle": NS(check=replaced_hook),
                    "check_final_request": replaced_hook, "check_final_job": replaced_hook,
                    "checkpoint_admission": NS(check_identity=replaced_hook)}
    def provider():
        setattr(env.context, service, replacements[service])
        return env.grants
    monkeypatch.setattr(env.manager, "_source", provider)
    with pytest.raises(env.module.BridgeError, match="lifecycle service identity changed"):
        env.module.export_asset(env.context, params)
    assert list(env.root.iterdir()) == []


@pytest.mark.parametrize("point", ["restore", "seal_fsync"])
def test_native_artifact_anchor_is_not_replaced_by_later_same_inode_bytes(asset, monkeypatch, point):
    env = asset
    armed, edited = [False], []
    changed = artifact("GLB").replace(b"meshes", b"extras")
    def provider():
        if armed[0]:
            armed[0] = False
            stage = next(env.root.glob(".blender-codex-asset-*")) / "payload.glb"
            stage.write_bytes(changed)
            metadata = stage.stat()
            env.module.os.utime(stage, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 2_000_000_000))
            edited.append(stage)
        return env.grants
    monkeypatch.setattr(env.manager, "_source", provider)
    if point == "restore":
        native_context_case(env, monkeypatch, lambda _writes: armed.__setitem__(0, True))
    else:
        check, count = env.module._Staging.write_check, [0]
        def checking(self):
            count[0] += 1
            if count[0] == 4:
                armed[0] = True
            return check(self)
        monkeypatch.setattr(env.module._Staging, "write_check", checking)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert len(edited) == 1 and edited[0].read_bytes() == changed
    assert not effects["publication_attempted"] and effects["staging_cleanup"] == "retained"


@pytest.mark.parametrize("invalid", ["header", "json", "dependency"])
def test_semantically_invalid_native_artifacts_latch_before_cleanup_provider(asset, monkeypatch, invalid):
    env = asset
    if invalid == "header":
        payload = b"invalid native GLB header"
    else:
        raw = b"not-json" if invalid == "json" else json.dumps({"asset": {"version": "2.0"}, "images": [{}]}).encode()
        raw += b" " * (-len(raw) % 4)
        payload = b"glTF" + struct.pack("<II", 2, 20 + len(raw)) + struct.pack("<II", len(raw), 0x4E4F534A) + raw
    observed, retried = [False], []
    def emitted(_bpy, _objects, path, _format, _include, *, transaction):
        path.write_bytes(payload)
        transaction.capture_output()
    def provider():
        if observed[0]:
            retried.append("grant after invalid artifact")
        return env.grants
    opened, loads = Path.open, env.module.json.loads
    class Stream:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def read(self, *args):
            value = self.stream.read(*args)
            if invalid == "header":
                observed[0] = True
            return value
    def file_open(path, mode="r", *args, **kwargs):
        stream = opened(path, mode, *args, **kwargs)
        return Stream(stream) if path.name == "payload.glb" and mode == "r+b" else stream
    def parsed(value, *args, **kwargs):
        if type(value) is bytes:
            observed[0] = True
        return loads(value, *args, **kwargs)
    monkeypatch.setattr(env.module, "_native", emitted)
    monkeypatch.setattr(env.manager, "_source", provider)
    monkeypatch.setattr(Path, "open", file_open)
    monkeypatch.setattr(env.module.json, "loads", parsed)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert observed[0] and retried == [] and not effects["publication_attempted"]
    assert effects["staging_cleanup"] == "retained"
    assert (Path(effects["retained_staging_path"]) / "payload.glb").read_bytes() == payload


@pytest.mark.parametrize("changed", ["replacement", "same_inode"])
def test_final_native_gate_rechecks_the_owned_file_after_its_last_provider(asset, monkeypatch, changed):
    env = asset
    armed, calls, native_calls = [False], [], []
    writes = native_context_case(env, monkeypatch, lambda _writes: native_calls.append("native exporter"))
    gate = env.module._NativeContext.gate
    def gated(self, *, native_write=False):
        armed[0] = native_write
        return gate(self, native_write=native_write)
    def provider():
        if armed[0]:
            armed[0] = False
            calls.append(changed)
            path = next(env.root.glob(".blender-codex-asset-*")) / "payload.glb"
            if changed == "replacement":
                path.rename(path.with_name("original-placeholder.glb"))
            path.write_bytes(b"newer manual file")
        return env.grants
    monkeypatch.setattr(env.module._NativeContext, "gate", gated)
    monkeypatch.setattr(env.manager, "_source", provider)
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.export_asset(env.context, request(env))
    effects = caught.value.context["external_effects"]
    assert calls == [changed] and native_calls == []
    assert writes == [("Asset", False), ("Protected", False), ("Asset", True)]
    assert not effects["publication_attempted"] and effects["staging_cleanup"] == "retained"
    assert (Path(effects["retained_staging_path"]) / "payload.glb").read_bytes() == b"newer manual file"
