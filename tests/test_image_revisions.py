from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError
from test_image_assets import Image, Images, png

from mcp_server.tools.nodes import NodeTools


@pytest.fixture
def revision(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.tools.image_revisions")
    path = tmp_path / "source.png"
    path.write_bytes(png())
    old = Image("Original", str(path), alpha_mode="PREMUL", users=1)
    old.animation_data = None
    collection = Images([old])
    original_load = collection.load
    def load(*args, **kwargs):
        new = original_load(*args, **kwargs)
        new.alpha_mode = "STRAIGHT"
        new.bl_rna = NS(properties={"alpha_mode": NS(type="ENUM", is_readonly=False,
            array_length=0, is_enum_flag=False, enum_items=[NS(identifier=v) for v in ("STRAIGHT", "PREMUL")])})
        return new
    monkeypatch.setattr(collection, "load", load)

    class Node:
        name, bl_idname = "Texture", "ShaderNodeTexImage"
        interpolation, projection, extension = "Closest", "FLAT", "CLIP"
        inputs, outputs = (), ()
        _image = None
        @property
        def image(self):
            return self._image
        @image.setter
        def image(self, value):
            if self._image is not None:
                self._image.users -= 1
            self._image = value
            if value is not None:
                value.users += 1

    node = Node()
    node.image = old  # one separate protected use remains
    tree = NS(name="Root", nodes=[node], links=[], animation_data=None)
    material = NS(name="Material", node_tree=tree, animation_data=None)
    bpy = NS(data=NS(images=collection), context=NS(mode="OBJECT"), types=NS(
        ColorManagedInputColorspaceSettings=NS(bl_rna=NS(properties={"name": NS(enum_items=[NS(identifier="sRGB")])}))))
    grants = {"EDIT_MATERIALS": True, "ACCESS_EXTERNAL_FILES": True}
    def require(*permissions):
        if any(not grants.get(p.value, False) for p in permissions):
            raise module.BridgeError("PERMISSION_DENIED", "denied")
    context = NS(require=require, check_cancelled=None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module.images, "require_blender", lambda: bpy)
    monkeypatch.setattr(module.images, "get_preferences", lambda: NS(texture_directory=str(tmp_path)))
    monkeypatch.setattr(module.images, "binding_target", lambda *_: (material, tree, node, {}, None))
    return module, context, bpy, old, node, material, tree, grants, path


def params(**values):
    return {"material_name": "Material", "node_name": "Texture", "new_image_name": "Revision", **values}


def test_new_version_retains_original_and_role_without_reload(revision):
    module, context, bpy, old, node, *_ = revision
    before = module._retained(old)
    result = module.refresh_image(context, params())
    assert len(bpy.data.images) == 2 and node.image is not old
    assert node.image.alpha_mode == "PREMUL" and node.image.colorspace_settings.name == "sRGB"
    assert node.image.name == "Revision" and old.users == 1
    assert module._retained(old) == before
    assert result["revision_mode"] == "new_image_for_node" and not result["previous_buffer_reloaded"]
    assert not result["image_identity_preserved"] and not result["file_written"]
    assert result["sampling"] == {"interpolation": "Closest", "projection": "FLAT", "extension": "CLIP"}


def test_relocation_never_reads_missing_unloaded_original(revision, tmp_path):
    module, context, _, old, node, *_, source = revision
    target = tmp_path / "relocated.png"
    target.write_bytes(source.read_bytes())
    old.filepath = str(tmp_path / "missing.png")
    old.has_data = False
    result = module.refresh_image(context, params(filepath=str(target)))
    assert not old.has_data and old.filepath.endswith("missing.png")
    assert node.image.filepath == str(target) and result["previous_image"]["loaded_size"] is None


@pytest.mark.parametrize("permission", ["EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES"])
def test_denial_never_probes_or_allocates(revision, monkeypatch, permission):
    module, context, bpy, old, node, _, _, grants, _ = revision
    grants[permission] = False
    monkeypatch.setattr(module.images, "preflight_file", lambda *_: pytest.fail("Denied file probe"))
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert caught.value.code == "PERMISSION_DENIED" and list(bpy.data.images) == [old] and node.image is old


@pytest.mark.parametrize("owner_index", [3, 5, 6])
def test_direct_animation_rejected_before_file_read(revision, monkeypatch, owner_index):
    module, context, bpy, old, node, *_ = revision
    revision[owner_index].animation_data = NS(action=object())
    monkeypatch.setattr(module.images, "preflight_file", lambda *_: pytest.fail("Animated source probe"))
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert caught.value.code == "NOT_IMPLEMENTED" and list(bpy.data.images) == [old] and node.image is old


@pytest.mark.parametrize("change", ["missing", "movie", "multiview", "linked", "name_collision", "generated"])
def test_unsupported_source_and_name_rejected_before_decode(revision, monkeypatch, change):
    module, context, bpy, old, node, *_ = revision
    if change == "missing":
        node.image = None
    elif change == "movie":
        old.source = "MOVIE"
    elif change == "multiview":
        old.is_multiview = True
    elif change == "linked":
        old.library = object()
    elif change == "name_collision":
        old.name = "Revision"
    else:
        old.source = "GENERATED"
    monkeypatch.setattr(module.images, "preflight_file", lambda *_: pytest.fail("Invalid source probe"))
    with pytest.raises(module.BridgeError):
        module.refresh_image(context, params())
    assert len(bpy.data.images) == 1


def test_explicit_file_can_version_a_generated_dirty_or_packed_source(revision):
    module, context, _, old, node, *_, source = revision
    old.source, old.is_dirty, old.packed_file = "GENERATED", True, object()
    module.refresh_image(context, params(filepath=str(source)))
    assert old.is_dirty and old.packed_file is not None
    assert node.image is not old and node.image.source == "FILE" and node.image.packed_file is None


@pytest.mark.parametrize("leave_user", [False, True])
def test_failed_post_binding_revision_restores_old_binding_and_measures_cleanup(revision, monkeypatch, leave_user):
    module, context, bpy, old, node, *_ = revision
    bind = module.images.set_node_image
    def fail(*args, **kwargs):
        bind(*args, **kwargs)
        if leave_user:
            node.image.users += 1  # a separate unexpected consumer must not be forcibly unlinked
        raise RuntimeError("Injected post-binding failure")
    monkeypatch.setattr(module.images, "set_node_image", fail)
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert node.image is old and old.users == 2
    assert caught.value.context["rollback_verified"] is not leave_user
    assert caught.value.context["possible_mutation"] is leave_user
    assert len(bpy.data.images) == (2 if leave_user else 1)


def test_source_changes_between_decode_and_binding_are_not_accepted(revision, monkeypatch):
    module, context, bpy, old, node, *_, source = revision
    bind = module.images.set_node_image
    def changed(*args, **kwargs):
        source.write_bytes(png(width=1))
        return bind(*args, **kwargs)
    monkeypatch.setattr(module.images, "set_node_image", changed)
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert caught.value.context["rollback_verified"] and node.image is old and list(bpy.data.images) == [old]


def test_cancel_after_binding_restores_previous_version(revision, monkeypatch):
    module, context, bpy, old, node, *_ = revision
    bind = module.images.set_node_image
    def cancelled(*args, **kwargs):
        result = bind(*args, **kwargs)
        def cancel():
            raise module.BridgeError("TIMEOUT", "cancelled")
        context.check_cancelled = cancel
        return result
    monkeypatch.setattr(module.images, "set_node_image", cancelled)
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert caught.value.code == "TIMEOUT" and caught.value.context["rollback_verified"]
    assert node.image is old and list(bpy.data.images) == [old]


def test_scope_failure_precedes_decode_and_keeps_old_binding(revision, monkeypatch):
    module, context, bpy, old, node, *_ = revision
    def deny(*_args):
        raise module.BridgeError("INVALID_ARGUMENT", "shared graph needs consent")
    monkeypatch.setattr(module.images, "binding_target", deny)
    monkeypatch.setattr(module.images, "load_image", lambda *_: pytest.fail("Unconsented decode"))
    with pytest.raises(module.BridgeError, match="shared graph"):
        module.refresh_image(context, params())
    assert node.image is old and list(bpy.data.images) == [old]


def test_post_allocation_lookup_failure_retains_possible_mutation_evidence(revision, monkeypatch):
    module, context, bpy, old, node, *_ = revision
    exact = module.images.image_exact
    def fail(bpy, name):
        if name == "Revision":
            raise module.BridgeError("INVALID_ARGUMENT", "unexpected name resolution failure")
        return exact(bpy, name)
    monkeypatch.setattr(module.images, "image_exact", fail)
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert node.image is old and len(bpy.data.images) == 2
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]


def test_permission_revoked_after_binding_is_measured_and_recovered(revision, monkeypatch):
    module, context, bpy, old, node, _, _, grants, _ = revision
    bind = module.images.set_node_image
    def revoked(*args, **kwargs):
        result = bind(*args, **kwargs)
        grants["ACCESS_EXTERNAL_FILES"] = False
        return result
    monkeypatch.setattr(module.images, "set_node_image", revoked)
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert caught.value.code == "PERMISSION_DENIED" and caught.value.context["rollback_verified"]
    assert node.image is old and list(bpy.data.images) == [old]


def test_graph_side_effects_are_not_claimed_restored(revision, monkeypatch):
    module, context, _, old, node, _, tree, *_ = revision
    bind = module.images.set_node_image
    def changed(*args, **kwargs):
        result = bind(*args, **kwargs)
        node.inputs = [NS(identifier="New", bl_idname="NodeSocketFloat", default_value=0.)]
        return result
    monkeypatch.setattr(module.images, "set_node_image", changed)
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    assert node.image is old and tree.nodes == [node]
    assert not caught.value.context["rollback_verified"] and caught.value.context["possible_mutation"]


def test_strict_mcp_inputs_and_forwarding():
    hints = get_type_hints(NodeTools.nodes_refresh_image, include_extras=True)
    for field, value in (("material_name", 1), ("node_name", False), ("new_image_name", []),
                         ("filepath", 3), ("group_path", [True]), ("allow_shared", 1)):
        with pytest.raises(ValidationError):
            TypeAdapter(hints[field]).validate_python(value)
    calls = []
    async def call(method, values):
        calls.append((method, values))
    asyncio.run(NodeTools(NS(call=call)).nodes_refresh_image("Mat", "Tex", "Version", group_path=["Surface"]))
    assert calls == [("nodes.refresh_image", {"material_name": "Mat", "node_name": "Tex",
        "new_image_name": "Version", "group_path": ["Surface"], "allow_shared": False})]
