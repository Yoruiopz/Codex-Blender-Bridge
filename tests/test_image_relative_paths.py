from __future__ import annotations

import importlib
import os
from array import array
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_image_assets import Image, png, tools  # noqa: F401
from test_image_revisions import params, revision  # noqa: F401

# Imported fixtures deliberately retain their pytest names.
# ruff: noqa: F811


@pytest.fixture
def stored(tools, tmp_path):
    module, bpy, collection, grants, context, path = tools
    project = tmp_path / "project" / "asset.blend"
    project.parent.mkdir()
    project.write_bytes(b"saved project fixture")
    bpy.data.filepath, bpy.data.is_saved = str(project), True
    image = Image("Stored", "//../color.png")
    collection.append(image)
    return NS(module=module, bpy=bpy, collection=collection, grants=grants,
              context=context, path=path, project=project, image=image, root=tmp_path)


def test_saved_parent_relative_binding_preserves_stored_alias_and_buffer(stored):
    env = stored
    before = vars(env.image).copy()
    reference = env.module.source_reference(env.context, env.image)
    proof = env.module.binding_source(env.context, env.image)
    assert reference.path == env.path.resolve() and proof["format"] == "PNG"
    assert reference.evidence()["project_filepath"] == str(env.project)
    assert vars(env.image) == before


def test_absolute_stored_image_needs_no_project_anchor(stored):
    env = stored
    env.image.filepath = str(env.path)
    env.bpy.data.filepath, env.bpy.data.is_saved = "", False
    reference = env.module.source_reference(env.context, env.image)
    assert reference.path == env.path and reference.project_path is None
    assert env.module.binding_source(env.context, env.image)["format"] == "PNG"


def _pixel_source(env, transfer=None):
    paint = importlib.import_module(env.module.__package__ + ".image_paint")
    env.image.channels = 4
    def copy(values):
        values[:] = array("f", [.25, .5, .75, 1.]) * 4
        if transfer is not None:
            transfer()
    class Pixels:
        def __len__(self):
            return 16
        foreach_get = staticmethod(copy)
    env.image.pixels = Pixels()
    return paint


def test_pixel_transfer_rechecks_project_anchor_after_read(stored):
    env = stored
    paint = _pixel_source(env, lambda: setattr(env.bpy.data, "is_saved", False))
    with pytest.raises(env.module.BridgeError, match="saved local project"):
        paint._read(env.context, env.image)


def test_frozen_pixel_file_proof_distinguishes_project_anchors_for_same_texture(stored):
    env = stored
    paint = _pixel_source(env)
    _values, _width, _height, before = paint._read(env.context, env.image)
    replacement = env.project.parent / "renamed.blend"
    replacement.write_bytes(b"project")
    env.bpy.data.filepath = str(replacement)
    _values, _width, _height, after = paint._read(env.context, env.image)
    assert before["file_sha256"] == after["file_sha256"]
    assert before["source_reference"] != after["source_reference"]


def test_frozen_pixel_file_proof_distinguishes_changed_approved_folder(stored, monkeypatch):
    env = stored
    paint = _pixel_source(env)
    _values, _width, _height, before = paint._read(env.context, env.image)
    monkeypatch.setattr(env.module, "get_preferences", lambda: NS(texture_directory=str(env.root.parent)))
    _values, _width, _height, after = paint._read(env.context, env.image)
    assert before["file_sha256"] == after["file_sha256"]
    assert before["source_reference"] != after["source_reference"]


@pytest.mark.parametrize("modifying,permission", [(False, "INSPECT_SCENE"), (True, "EDIT_MATERIALS")])
def test_pixel_source_checks_cannot_revoke_the_authorizing_grant(stored, modifying, permission):
    env = stored
    paint = _pixel_source(env)
    env.context.check_cancelled = lambda: env.grants.update({permission: False})
    with pytest.raises(env.module.BridgeError) as caught:
        paint._read(env.context, env.image, modifying=modifying)
    assert caught.value.code == "PERMISSION_DENIED"


@pytest.mark.parametrize("raw,saved", [("", False), ("", True), ("relative.blend", True),
    ("//remote/project.blend", True), ("missing.blend", True)])
def test_relative_source_never_uses_working_directory_or_invalid_anchor(stored, raw, saved):
    env = stored
    env.bpy.data.filepath, env.bpy.data.is_saved = raw, saved
    with pytest.raises(env.module.BridgeError):
        env.module.source_reference(env.context, env.image)


def test_existing_project_path_is_still_rejected_when_unsaved(stored):
    env = stored
    env.bpy.data.is_saved = False
    with pytest.raises(env.module.BridgeError, match="saved local project"):
        env.module.source_reference(env.context, env.image)


@pytest.mark.parametrize("raw", ["//", "///etc/passwd", "//C:/image.png", "//../color.png\n",
    "//" + "x" * 4095, "//\ud800.png", "color.png"])
def test_bad_stored_paths_fail_explicitly(stored, raw):
    env = stored
    env.image.filepath = raw
    with pytest.raises(env.module.BridgeError):
        env.module.source_reference(env.context, env.image)


@pytest.mark.parametrize("change", ["linked", "override", "readonly", "multiview", "generated"])
def test_unsupported_stored_ownership_rejected_before_resolution(stored, monkeypatch, change):
    env = stored
    if change == "linked":
        env.image.library = object()
    elif change == "override":
        env.image.override_library = object()
    elif change == "readonly":
        env.image.is_editable = False
    elif change == "multiview":
        env.image.is_multiview = True
    else:
        env.image.source = "GENERATED"
    monkeypatch.setattr(Path, "resolve", lambda *_a, **_k: pytest.fail("Unsupported source probed filesystem"))
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.source_reference(env.context, env.image)
    assert caught.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("after_callback", [False, True])
def test_denied_source_does_not_probe_any_path(stored, monkeypatch, after_callback):
    env = stored
    if after_callback:
        env.context.check_cancelled = lambda: env.grants.update(ACCESS_EXTERNAL_FILES=False)
    else:
        env.grants["ACCESS_EXTERNAL_FILES"] = False
    monkeypatch.setattr(Path, "resolve", lambda *_a, **_k: pytest.fail("Denied source probed filesystem"))
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.source_reference(env.context, env.image)
    assert caught.value.code == "PERMISSION_DENIED"


def test_relative_escape_is_resolved_and_denied(stored, tmp_path):
    env = stored
    outside = tmp_path.parent / (tmp_path.name + "-outside.png")
    outside.write_bytes(png())
    env.image.filepath = "//../../" + outside.name
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.source_reference(env.context, env.image)
    assert caught.value.code == "PERMISSION_DENIED"


def _symlink(link, target):
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Host cannot create fixture symlink: {exc}")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink traversal semantics")
def test_parent_components_are_resolved_after_aliases_not_removed_lexically(stored):
    env = stored
    nested = env.root / "other" / "nested"
    nested.mkdir(parents=True)
    target = nested.parent / "color.png"
    target.write_bytes(png())
    _symlink(env.project.parent / "link", nested)
    env.image.filepath = "//link/../color.png"
    reference = env.module.source_reference(env.context, env.image)
    assert reference.path == target


def test_in_root_source_alias_is_allowed_but_retargeting_is_rejected(stored):
    env = stored
    alias = env.project.parent / "linked.png"
    _symlink(alias, env.path)
    env.image.filepath = "//linked.png"
    reference = env.module.source_reference(env.context, env.image)
    replacement = env.root / "replacement.png"
    replacement.write_bytes(png())
    alias.unlink()
    _symlink(alias, replacement)
    with pytest.raises(env.module.BridgeError, match="retargeted"):
        reference.check(env.context)


def test_binding_reuses_the_supplied_source_reference_instead_of_recapturing(stored):
    env = stored
    reference = env.module.source_reference(env.context, env.image)
    env.image.filepath = str(env.path)
    with pytest.raises(env.module.BridgeError, match="changed"):
        env.module.binding_source(env.context, env.image, source=reference)


@pytest.mark.parametrize("change", ["permission", "folder", "filepath", "anchor", "deleted", "unsaved"])
def test_preflight_rechecks_live_stored_reference(stored, monkeypatch, change):
    env = stored
    reference = env.module.source_reference(env.context, env.image)
    def changed_preflight(raw, root, check):
        check()
        if change == "permission":
            env.grants["ACCESS_EXTERNAL_FILES"] = False
        elif change == "folder":
            monkeypatch.setattr(env.module, "get_preferences", lambda: NS(texture_directory=str(env.project.parent)))
        elif change == "filepath":
            env.image.filepath = str(env.path)
        elif change == "anchor":
            replacement = env.project.parent / "renamed.blend"
            replacement.write_bytes(b"project")
            env.bpy.data.filepath = str(replacement)
        elif change == "deleted":
            env.path.unlink()
        else:
            env.bpy.data.is_saved = False
        check()
        pytest.fail("Changed source was accepted")
    monkeypatch.setattr(env.module, "preflight_file", changed_preflight)
    with pytest.raises(env.module.BridgeError):
        env.module._source_file(env.context, str(reference.path), source=reference)


@pytest.mark.parametrize("raw", ["//../color.png", "../color.png"])
def test_explicit_load_paths_remain_absolute(stored, raw):
    env = stored
    with pytest.raises(env.module.BridgeError):
        env.module.load_image(env.context, {"filepath": raw, "new_name": "Rejected"})
    assert list(env.collection) == [env.image]


def _relative_revision(revision, tmp_path):
    module, context, bpy, old, *_ = revision
    project = tmp_path / "project" / "asset.blend"
    project.parent.mkdir()
    project.write_bytes(b"project")
    bpy.data.filepath, bpy.data.is_saved = str(project), True
    old.filepath = "//../source.png"
    return module, context, bpy, old, project


def test_default_refresh_versions_saved_relative_source_without_reloading_old(revision, tmp_path):
    module, context, bpy, old, _ = _relative_revision(revision, tmp_path)
    before = module._retained(old)
    result = module.refresh_image(context, params())
    assert result["image"]["filepath"] == str(tmp_path / "source.png")
    assert module._retained(old) == before and old.users == 1
    assert bpy.data.images.get("Revision") is not old


def test_explicit_relocation_does_not_resolve_missing_relative_old_source(revision, tmp_path):
    module, context, bpy, old, _ = _relative_revision(revision, tmp_path)
    old.filepath, old.has_data = "//missing.png", False
    bpy.data.filepath, bpy.data.is_saved = "", False
    module.refresh_image(context, params(filepath=str(tmp_path / "source.png")))
    assert old.filepath == "//missing.png" and not old.has_data


def test_explicit_relative_relocation_is_rejected(revision, tmp_path):
    module, context, _, old, _ = _relative_revision(revision, tmp_path)
    with pytest.raises(module.BridgeError):
        module.refresh_image(context, params(filepath="//../source.png"))
    assert old.filepath == "//../source.png"


@pytest.mark.parametrize("allow_cleanup", [False, True])
def test_anchor_change_after_allocation_reports_actual_cleanup_permission(revision, tmp_path, monkeypatch, allow_cleanup):
    module, context, bpy, old, _ = _relative_revision(revision, tmp_path)
    revision[7]["DELETE_OBJECTS"] = allow_cleanup
    original_load = bpy.data.images.load
    def load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        bpy.data.is_saved = False
        return result
    monkeypatch.setattr(bpy.data.images, "load", load)
    with pytest.raises(module.BridgeError) as caught:
        module.refresh_image(context, params())
    evidence = caught.value.context
    assert evidence["cleanup_permission_denied"] is not allow_cleanup
    assert evidence["rollback_verified"] is allow_cleanup
    assert evidence["possible_mutation"] is not allow_cleanup
    assert old.filepath == "//../source.png" and revision[4].image is old
    assert len(bpy.data.images) == (1 if allow_cleanup else 2)
