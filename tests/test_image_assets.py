from __future__ import annotations

import asyncio
import hashlib
import importlib
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.materials import MaterialTools, load_definitions
from mcp_server.tools.nodes import NodeTools


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)


def png(width=2, height=2, *, extra=b"", data=True):
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + extra + (
        chunk(b"IDAT", zlib.compress(b"\0" + b"\xff" * 8)) if data else b"") + chunk(b"IEND", b"")


def jpeg(marker=0xc0, *, depth=8, width=3, height=2):
    payload = struct.pack(">BHHB", depth, height, width, 3) + bytes((1, 17, 0, 2, 17, 0, 3, 17, 0))
    return b"\xff\xd8\xff" + bytes((marker,)) + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"


@pytest.fixture
def files(addon_package):
    return importlib.import_module(f"{addon_package}.image_files")


@pytest.mark.parametrize("suffix,payload,kind", [(".png", png(), "PNG"), (".jpg", jpeg(), "JPEG"), (".jpeg", jpeg(0xc2), "JPEG")])
def test_reviewed_headers(files, suffix, payload, kind):
    result = files.bitmap_header(payload, suffix)
    assert result["format"] == kind and result["height"] == 2 and result["bit_depth"] == 8


@pytest.mark.parametrize("payload,suffix,code", [
    (b"garbage", ".png", "INVALID_ARGUMENT"), (b"garbage", ".jpg", "INVALID_ARGUMENT"),
    (png()[:-1], ".png", "INVALID_ARGUMENT"), (png() + b"x", ".png", "INVALID_ARGUMENT"),
    (png(data=False), ".png", "INVALID_ARGUMENT"), (png(width=8193), ".png", "INVALID_ARGUMENT"),
    (png(width=8192, height=8192), ".png", "INVALID_ARGUMENT"),
    (png(extra=chunk(b"IHDR", b"x")), ".png", "INVALID_ARGUMENT"),
    (png(extra=chunk(b"acTL", b"x")), ".png", "NOT_IMPLEMENTED"),
    (png(extra=chunk(b"iCCP", b"x")), ".png", "NOT_IMPLEMENTED"),
    (png(extra=chunk(b"zTXt", b"x")), ".png", "NOT_IMPLEMENTED"),
    (png(extra=chunk(b"iTXt", b"x")), ".png", "NOT_IMPLEMENTED"),
    (png()[:20] + b"x" + png()[21:], ".png", "INVALID_ARGUMENT"),
    (jpeg(depth=12), ".jpg", "NOT_IMPLEMENTED"), (jpeg(0xc3), ".jpg", "NOT_IMPLEMENTED"),
    (jpeg(width=0), ".jpg", "INVALID_ARGUMENT"), (png(), ".exr", "NOT_IMPLEMENTED"),
    (jpeg()[:6], ".jpg", "INVALID_ARGUMENT"),
])
def test_bad_or_unreviewed_headers_fail_explicitly(files, payload, suffix, code):
    with pytest.raises(files.BridgeError) as error:
        files.bitmap_header(payload, suffix)
    assert error.value.code == code


def test_preflight_digest_and_local_scope(files, tmp_path):
    target = tmp_path / "texture.png"
    target.write_bytes(png())
    path, metadata = files.preflight_file(str(target), str(tmp_path))
    assert path == target.resolve() and metadata["file_sha256"] == hashlib.sha256(png()).hexdigest()
    assert metadata["file_bytes"] == len(png())
    with pytest.raises(files.BridgeError) as error:
        files.approved_file(str(target), "")
    assert error.value.code == "PERMISSION_DENIED"
    other = tmp_path / "another"
    other.mkdir()
    with pytest.raises(files.BridgeError) as error:
        files.approved_file(str(target), str(other))
    assert error.value.code == "PERMISSION_DENIED"


@pytest.mark.parametrize("raw", ["relative.png", "//server/a.png", "\\\\server\\a.png", "http://host/a.png", "a\nb.png"])
def test_unsafe_paths_rejected(files, tmp_path, raw):
    with pytest.raises(files.BridgeError):
        files.approved_file(raw, str(tmp_path))


def test_traversal_root_regular_file_and_file_size_guards(files, tmp_path, monkeypatch):
    target = tmp_path / "texture.png"
    target.write_bytes(png())
    for root, path in ((str(tmp_path.anchor), str(target)), (str(tmp_path), str(tmp_path)),
                       (str(tmp_path), str(tmp_path / "nested" / ".." / "texture.png"))):
        with pytest.raises(files.BridgeError):
            files.approved_file(path, root)
    monkeypatch.setattr(files, "MAX_FILE_BYTES", 10)
    with pytest.raises(files.BridgeError, match="32 MiB"):
        files.preflight_file(str(target), str(tmp_path))


def test_resolved_escape_denied_before_contents(files, tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    escaped = tmp_path / "outside.png"
    escaped.write_bytes(png())
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        return escaped if path.name == "link.png" else real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(files.BridgeError) as error:
        files.preflight_file(str(root / "link.png"), str(root))
    assert error.value.code == "PERMISSION_DENIED"


def test_mapped_network_drive_is_denied(files, tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_local_drive", lambda _: False)
    with pytest.raises(files.BridgeError, match="network"):
        files.approved_file(str(tmp_path / "x.png"), str(tmp_path))


class Image:
    def __init__(self, name="Image", path="", **values):
        self.name, self.filepath = name, path
        self.source, self.type = "FILE", "IMAGE"
        self.colorspace_settings = NS(name="sRGB")
        self.has_data, self.users, self.use_fake_user = True, 0, False
        self.packed_file, self.library, self.override_library = None, None, None
        self.is_editable, self.is_multiview = True, False
        self._size = (2, 2)
        self.__dict__.update(values)

    @property
    def size(self):
        if not self.has_data:
            pytest.fail("Unloaded image dimensions were probed")
        return self._size


class Images(list):
    def get(self, name):
        return next((i for i in self if i.name == name), None)

    def load(self, filepath, *, check_existing):
        assert check_existing is False
        image = Image(path=filepath)
        self.append(image)
        return image

    def remove(self, image, *, do_unlink):
        assert not do_unlink and image.users == 0
        super().remove(image)


@pytest.fixture
def tools(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.tools.images")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    images = Images()
    bpy = NS(context=NS(mode="OBJECT"), data=NS(images=images, user_map=lambda **_: {}), types=NS(
        ColorManagedInputColorspaceSettings=NS(bl_rna=NS(properties={"name": NS(enum_items=[NS(identifier="sRGB"), NS(identifier="Non-Color")])}))))
    grants = {p.value: True for p in permissions.Permission}
    manager = permissions.PermissionManager(lambda: grants)
    context = NS(require=lambda *p: manager.require(p), check_cancelled=None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "get_preferences", lambda: NS(texture_directory=str(tmp_path)))
    path = tmp_path / "color.png"
    path.write_bytes(png())
    return module, bpy, images, grants, context, path


def test_load_new_image_and_preserve_source_file(tools):
    module, _, images, _, context, path = tools
    result = module.load_image(context, {"filepath": str(path), "new_name": "Color", "colorspace": "Non-Color"})
    assert result["loaded"] and not result["reused_existing"] and not result["file_written"]
    assert result["image"]["name"] == "Color" and result["image"]["colorspace"] == "Non-Color"
    assert len(images) == 1 and path.read_bytes() == png()


@pytest.mark.parametrize("alpha", ["STRAIGHT", "PREMUL", "CHANNEL_PACKED", "NONE"])
def test_explicit_alpha_role_is_set_before_authorized_buffer_verification(tools, monkeypatch, alpha):
    module, _, images, _, context, path = tools
    original_load = images.load
    class AlphaImage(Image):
        @property
        def alpha_mode(self):
            return self._alpha
        @alpha_mode.setter
        def alpha_mode(self, value):
            self._alpha = value
            self.has_data = False
        @property
        def size(self):
            self.has_data = True  # model Blender's authorized lazy decode after an alpha change
            return self._size
    def load(*args, **kwargs):
        original = original_load(*args, **kwargs)
        image = AlphaImage(original.name, original.filepath)
        image._alpha = "STRAIGHT"
        image.bl_rna = NS(properties={"alpha_mode": NS(type="ENUM", array_length=0, is_readonly=False,
            is_enum_flag=False, enum_items=[NS(identifier=v) for v in ("STRAIGHT", "PREMUL", "CHANNEL_PACKED", "NONE")])})
        images[0] = image
        return image
    monkeypatch.setattr(images, "load", load)
    result = module.load_image(context, {"filepath": str(path), "new_name": "Alpha", "alpha_mode": alpha})
    assert result["image"]["alpha_mode"] == alpha and result["image"]["has_data"]


@pytest.mark.parametrize("alpha", [True, 1, "unknown", "alpha_mode.value"])
def test_invalid_alpha_role_fails_before_file_access(tools, monkeypatch, alpha):
    module, _, images, _, context, path = tools
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Invalid alpha probed file"))
    with pytest.raises(module.BridgeError) as caught:
        module.load_image(context, {"filepath": str(path), "new_name": "Alpha", "alpha_mode": alpha})
    assert caught.value.code == "INVALID_ARGUMENT" and not images


def test_new_buffer_metadata_does_not_trigger_lazy_unloaded_decoding(tools):
    module, _, images, _, context, path = tools
    class UnloadedImage(Image):
        @property
        def is_float(self):
            pytest.fail("Image.is_float can acquire an unloaded buffer")
        @property
        def is_dirty(self):
            pytest.fail("Unloaded dirty metadata is not needed")
    image = UnloadedImage("Unloaded", str(path), has_data=False)
    images.append(image)
    for _ in range(2):
        summary = module.inspect_images(context, {"image_name": "Unloaded"})["images"][0]
        assert summary["is_float"] is None and summary["is_dirty"] is None
        assert summary["loaded_size"] is None and not image.has_data


def test_explicit_same_file_loads_have_separate_image_color_roles(tools):
    module, _, images, _, context, path = tools
    module.load_image(context, {"filepath": str(path), "new_name": "Color"})
    module.load_image(context, {"filepath": str(path), "new_name": "Data", "colorspace": "Non-Color"})
    assert len(images) == 2 and images[0] is not images[1]
    assert images[0].colorspace_settings.name == "sRGB" and images[1].colorspace_settings.name == "Non-Color"


@pytest.mark.parametrize("name", ["\ud800", "a\nb", "é" * 32])
def test_invalid_image_names_fail_before_probe(tools, monkeypatch, name):
    module, _, _, _, context, path = tools
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Invalid name reached a file"))
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": name})
    assert error.value.code == "INVALID_ARGUMENT"


def test_external_denial_precedes_any_path_probe(tools, monkeypatch):
    module, _, images, grants, context, path = tools
    grants["ACCESS_EXTERNAL_FILES"] = False
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Denied path was probed"))
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Color"})
    assert error.value.code == "PERMISSION_DENIED" and not images


def test_cancel_after_native_decode_removes_only_new_image(tools):
    module, _, images, _, context, path = tools
    original = Image("Original")
    images.append(original)
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise module.BridgeError("TIMEOUT", "Canceled after decode")

    context.check_cancelled = cancelled
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Color"})
    assert error.value.code == "TIMEOUT" and error.value.context["rollback_verified"]
    assert images == [original] and path.read_bytes() == png()


def test_cleanup_does_not_unlink_unexpected_new_users(tools, monkeypatch):
    module, _, images, _, context, path = tools
    original_load = images.load

    def occupied(*args, **kwargs):
        image = original_load(*args, **kwargs)
        image.users = 1
        image._size = (999, 999)
        return image

    monkeypatch.setattr(images, "load", occupied)
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Color"})
    assert not error.value.context["rollback_verified"] and error.value.context["possible_mutation"]
    assert len(images) == 1


def test_failed_load_does_not_delete_owned_image_without_live_deletion_consent(tools):
    module, _, images, grants, context, path = tools
    grants["DELETE_OBJECTS"] = False
    def cancelled():
        if images:
            raise module.BridgeError("TIMEOUT", "cancelled after allocation")
    context.check_cancelled = cancelled
    with pytest.raises(module.BridgeError) as caught:
        module.load_image(context, {"filepath": str(path), "new_name": "Retained"})
    assert caught.value.code == "TIMEOUT" and caught.value.context["cleanup_permission_denied"]
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]
    assert images.get("Retained") is not None


def test_unused_removal_rechecks_deletion_grant_after_cancellation_checkpoint(tools):
    module, _, images, grants, context, _ = tools
    image = Image("Unused")
    images.append(image)
    context.check_cancelled = lambda: grants.update(DELETE_OBJECTS=False)
    with pytest.raises(module.BridgeError) as caught:
        module.remove_image(context, {"image_name": "Unused", "confirm_unused": True})
    assert caught.value.code == "PERMISSION_DENIED" and images == [image]


@pytest.mark.parametrize("change", ["mode", "color", "collision", "unknown"])
def test_load_prevalidation_does_not_probe_or_allocate(tools, monkeypatch, change):
    module, bpy, images, _, context, path = tools
    params = {"filepath": str(path), "new_name": "Color"}
    if change == "mode":
        bpy.context.mode = "EDIT_MESH"
    elif change == "color":
        params["colorspace"] = "Missing"
    elif change == "collision":
        images.append(Image("Color"))
    else:
        params["texture_directory"] = str(path.parent)
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Invalid request reached disk"))
    with pytest.raises(module.BridgeError):
        module.load_image(context, params)
    assert len(images) == (1 if change == "collision" else 0)


def test_unloaded_inspection_does_not_probe_dimensions_or_disk(tools, monkeypatch):
    module, _, images, _, context, _ = tools
    images.append(Image("Unloaded", has_data=False))
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Inspection read a file"))
    result = module.inspect_images(context, {"image_name": "Unloaded"})
    assert result["images"][0]["loaded_size"] is None and not result["images"][0]["has_data"]


def test_user_evidence_has_one_map_and_global_budget(tools):
    module, bpy, images, _, context, _ = tools
    images.extend(Image(str(i)) for i in range(3))
    users = {i: {Image(str(n)) for n in range(150)} for i in images}
    for owners in users.values():
        for owner in owners:
            owner.bl_rna = NS(identifier="ShaderNodeTree")
    calls = []

    def user_map(**kwargs):
        calls.append(kwargs)
        return users

    bpy.data.user_map = user_map
    result = module.inspect_images(context, {})
    assert len(calls) == 1 and sum(len(i["direct_users"]) for i in result["images"]) == 256
    assert all(i["direct_users_truncated"] for i in result["images"])


def test_remove_unused_image_only_and_never_source(tools):
    module, _, images, _, context, path = tools
    image = Image("Unused", str(path))
    images.append(image)
    with pytest.raises(module.BridgeError):
        module.remove_image(context, {"image_name": "Unused"})
    image.users = 1
    with pytest.raises(module.BridgeError):
        module.remove_image(context, {"image_name": "Unused", "confirm_unused": True})
    image.users = 0
    result = module.remove_image(context, {"image_name": "Unused", "confirm_unused": True})
    assert not images and not result["file_deleted"] and path.read_bytes() == png()


def test_mcp_schema_metadata_and_explicit_null_forwarding(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.images").register_tools(registry)
    definitions = {d.name: d for d in load_definitions()}
    for name in ("image.inspect", "image.load", "image.remove"):
        spec = registry.get(name)
        assert {p.value for p in spec.permissions} == set(definitions[name].required_permissions)
        assert spec.modifies == definitions[name].modifying
    calls = []

    class Registry:
        async def call(self, method, arguments):
            calls.append((method, arguments))
            return {}

    asyncio.run(NodeTools(Registry()).nodes_set_image("Material", "Texture", None))
    assert calls[0][1]["image_name"] is None
    for method, field, value in ((MaterialTools.image_inspect, "offset", True),
                                  (MaterialTools.image_remove, "confirm_unused", 1),
                                  (NodeTools.nodes_set_image, "allow_shared", "true"),
                                  (MaterialTools.image_load, "filepath", 12),
                                  (MaterialTools.image_load, "new_name", False),
                                  (MaterialTools.image_load, "colorspace", 1),
                                  (MaterialTools.image_load, "alpha_mode", True),
                                  (MaterialTools.image_load, "alpha_mode", "UNKNOWN"),
                                  (NodeTools.nodes_set_image, "image_name", 42),
                                  (NodeTools.nodes_set_image, "extension", True)):
        with pytest.raises(ValidationError):
            TypeAdapter(get_type_hints(method, include_extras=True)[field]).validate_python(value)


@pytest.fixture
def binding(tools, addon_package, monkeypatch):
    module, bpy, images, grants, context, path = tools

    class Owner:
        def __init__(self, name, kind="Mesh", **values):
            self.name, self.bl_rna = name, NS(identifier=kind)
            self.library, self.override_library, self.is_editable = None, None, True
            self.__dict__.update(values)

    class Node:
        def __init__(self):
            self.name, self.bl_idname = "Texture", "ShaderNodeTexImage"
            self.image, self.interpolation, self.projection, self.extension = None, "Linear", "FLAT", "REPEAT"
            self.fail = None
            self.bl_rna = NS(properties={key: NS(type="ENUM", is_array=False, is_readonly=False,
                enum_items=[NS(identifier=v) for v in values]) for key, values in {
                    "interpolation": ("Linear", "Closest"), "projection": ("FLAT", "BOX"), "extension": ("REPEAT", "CLIP")}.items()})

        def __setattr__(self, key, value):
            object.__setattr__(self, key, value)
            if getattr(self, "fail", None) == key:
                object.__setattr__(self, "fail", None)
                raise RuntimeError("Injected setter failure after assignment")

    node = Node()
    tree = Owner("Tree", "ShaderNodeTree", nodes=[node], links=[])
    material = Owner("Material", "Material", node_tree=tree, users=1, use_nodes=True)
    obj = Owner("Cube", "Object", material_slots=[NS(material=material)])
    bpy.data.objects = [obj]
    bpy.data.user_map = lambda **_: {material: {Owner("Mesh")}}
    nodes = importlib.import_module(f"{addon_package}.tools.nodes")
    monkeypatch.setattr(nodes, "require_blender", lambda: bpy)
    monkeypatch.setattr(nodes, "_material_graph", lambda _: (material, tree))
    monkeypatch.setattr(nodes, "_node_exact", lambda *_: node)
    image = Image("Loaded", str(path))
    images.append(image)
    params = {"material_name": "Material", "node_name": "Texture", "image_name": "Loaded", "extension": "CLIP"}
    return module, bpy, image, node, material, grants, context, params


def test_file_binding_uses_policy_and_returns_observed_settings(binding):
    module, _, image, node, _, _, context, params = binding
    result = module.set_node_image(context, params)
    assert node.image is image and node.extension == "CLIP"
    assert result["image"]["name"] == "Loaded" and result["source_file_at_binding"]["format"] == "PNG"


def test_file_binding_denial_leaves_node_unchanged(binding, monkeypatch):
    module, _, _, node, _, grants, context, params = binding
    grants["ACCESS_EXTERNAL_FILES"] = False
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Denied source was read"))
    with pytest.raises(module.BridgeError) as error:
        module.set_node_image(context, params)
    assert error.value.code == "PERMISSION_DENIED" and node.image is None and node.extension == "REPEAT"


def test_generated_binding_and_explicit_clear_need_no_external_permission(binding, monkeypatch):
    module, _, image, node, _, grants, context, params = binding
    image.source = "GENERATED"
    grants["ACCESS_EXTERNAL_FILES"] = False
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Generated/clear operation touched disk"))
    module.set_node_image(context, params)
    assert node.image is image
    module.set_node_image(context, {**params, "image_name": None})
    assert node.image is None


def test_shared_material_requires_explicit_consent_before_source_probe(binding, monkeypatch):
    module, _, _, node, material, _, context, params = binding
    material.users = 2
    monkeypatch.setattr(module, "preflight_file", lambda *_: pytest.fail("Unconsented scope read a file"))
    with pytest.raises(module.BridgeError, match="allow_shared"):
        module.set_node_image(context, params)
    assert node.image is None


@pytest.mark.parametrize("change,code", [("unloaded", "NOT_IMPLEMENTED"), ("movie", "NOT_IMPLEMENTED"),
    ("multiview", "NOT_IMPLEMENTED"), ("linked", "NOT_IMPLEMENTED"), ("large", "INVALID_ARGUMENT"),
    ("sampler", "INVALID_ARGUMENT"), ("missing_image_name", "INVALID_ARGUMENT")])
def test_unsupported_or_invalid_bindings_do_not_mutate(binding, change, code):
    module, _, image, node, _, _, context, params = binding
    if change == "unloaded":
        image.has_data = False
    elif change == "movie":
        image.source = "MOVIE"
    elif change == "multiview":
        image.is_multiview = True
    elif change == "linked":
        image.library = object()
    elif change == "large":
        image._size = (9000, 9000)
    elif change == "sampler":
        params["extension"] = "arbitrary.path"
    else:
        params.pop("image_name")
    with pytest.raises(module.BridgeError) as error:
        module.set_node_image(context, params)
    assert error.value.code == code and node.image is None and node.extension == "REPEAT"


@pytest.mark.parametrize("failed", ["image", "extension", "cancel"])
def test_binding_failure_restores_exact_previous_state(binding, failed):
    module, _, _, node, _, _, context, params = binding
    if failed == "cancel":
        calls = 0

        def cancelled():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise module.BridgeError("TIMEOUT", "Canceled")

        context.check_cancelled = cancelled
    else:
        node.fail = failed
    with pytest.raises(module.BridgeError) as error:
        module.set_node_image(context, params)
    assert error.value.context["rollback_verified"] and not error.value.context["possible_mutation"]
    assert node.image is None and node.extension == "REPEAT"


def test_source_change_during_native_load_is_not_accepted(tools, monkeypatch):
    module, _, images, _, context, path = tools
    original = images.load

    def changed(*args, **kwargs):
        image = original(*args, **kwargs)
        path.write_bytes(png(extra=chunk(b"tEXt", b"changed\0value")))
        return image

    monkeypatch.setattr(images, "load", changed)
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Color"})
    assert error.value.context["rollback_verified"] and not images


def test_permission_is_rechecked_immediately_before_decode(tools, monkeypatch):
    module, _, images, grants, context, path = tools
    preflight = module.preflight_file

    def revoked(*args):
        result = preflight(*args)
        grants["ACCESS_EXTERNAL_FILES"] = False
        return result

    monkeypatch.setattr(module, "preflight_file", revoked)
    with pytest.raises(module.BridgeError) as error:
        module.load_image(context, {"filepath": str(path), "new_name": "Color"})
    assert error.value.code == "PERMISSION_DENIED" and not images
