"""Permission-controlled image assets; no file writing, implicit reuse or existing-image edits."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..image_files import MAX_DIMENSION, MAX_FILE_BYTES, MAX_PIXELS, file_limits, preflight_file
from ..permissions import Permission
from ..preferences import get_preferences
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, int_param, reject_unknown_params, require_blender
from .material_scope import local_editable

LOGGER = logging.getLogger(__name__)


def _check(context: ToolContext) -> None:
    if context.check_cancelled:
        context.check_cancelled()


def cleanup_created_image(context: ToolContext, bpy: Any, image: Any) -> tuple[bool, bool]:
    """Only for a handle allocated by this operation; never forced unlink or implicit deletion consent."""
    if image.users != 0 or image.use_fake_user:
        return False, False
    try:
        context.require(Permission.DELETE_OBJECTS)
    except BridgeError as error:
        if error.code == ErrorCode.PERMISSION_DENIED.value:
            return False, True
        raise
    if image.users != 0 or image.use_fake_user:
        return False, False
    bpy.data.images.remove(image, do_unlink=False)
    return True, False


def _name(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise invalid_argument(f"'{key}' must be a non-empty name of at most 63 UTF-8 bytes.")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise invalid_argument(f"'{key}' must be valid UTF-8 text.") from exc
    if len(encoded) > 63:
        raise invalid_argument(f"'{key}' must contain at most 63 UTF-8 bytes.")
    return value


def image_exact(bpy: Any, name: str) -> Any:
    matches = list(islice((image for image in bpy.data.images if image.name == name), 2))
    if len(matches) != 1:
        raise invalid_argument("Image name is missing or ambiguous across libraries.", image_name=name)
    return matches[0]


def _object_mode(bpy: Any) -> None:
    if bpy.context.mode != "OBJECT":
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Image asset mutations currently require Object Mode for verified recovery.")


def _root() -> str:
    return getattr(get_preferences(), "texture_directory", "")


def _source_file(context: ToolContext, raw: str):
    context.require(Permission.ACCESS_EXTERNAL_FILES)
    _check(context)
    root = _root()
    def check():
        context.require(Permission.ACCESS_EXTERNAL_FILES)
        _check(context)
        if _root() != root:
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Approved texture folder changed during preflight; reinspect before retrying.")
        context.require(Permission.ACCESS_EXTERNAL_FILES)  # A cancellation callback can also revoke consent.
    path, proof = preflight_file(raw, root, check)
    return path, {**proof, "_approved_root": root}


def _load_gate(context: ToolContext, approved_root: str | None = None) -> None:
    context.require(Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES)
    _check(context)
    # The caller owns its registry/toolset gate: nodes.refresh_image also uses
    # this loader and must not acquire an undocumented materials-toolset gate.
    state = getattr(context, "state", None)
    flags = state.snapshot() if state else {}
    if flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Image loading emergency-stopped.")
    if flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Image loading is paused.")
    if approved_root is not None and _root() != approved_root:
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "Approved texture folder changed before native loading/mutation; reinspect before retrying.")
    context.require(Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES)


def _exr_interpretation(header: dict, color: str, alpha: str | None) -> None:
    if header.get("format") != "EXR":
        return
    if color not in {"Linear Rec.709", "Non-Color"} or alpha not in {"PREMUL", "CHANNEL_PACKED"}:
        raise invalid_argument("Reviewed EXR needs explicit Linear Rec.709/Non-Color and PREMUL/CHANNEL_PACKED interpretation; file hints do not choose it.")
    if color == "Non-Color" and alpha != "CHANNEL_PACKED":
        raise invalid_argument("Non-Color EXR requires CHANNEL_PACKED to keep independent data channels.")


def _summary(image: Any) -> dict:
    loaded = bool(image.has_data)
    simple = loaded and image.source in {"FILE", "GENERATED"} and not getattr(image, "is_multiview", False)
    # Image.size can lazily load a file. Never ask for it on an unloaded image during inspection.
    return {"name": image.name, "source": image.source, "type": image.type,
            "has_data": loaded, "loaded_size": [int(v) for v in image.size] if simple else None,
            "filepath": str(image.filepath)[:4096], "filepath_truncated": len(str(image.filepath)) > 4096,
            "colorspace": image.colorspace_settings.name,
            "alpha_mode": getattr(image, "alpha_mode", None),
            "is_dirty": bool(getattr(image, "is_dirty", False)) if loaded else None,
            # Image.is_float acquires an ImBuf and can decode from disk. Only
            # inspect it when this exact simple image already has a buffer.
            "is_float": bool(getattr(image, "is_float", False)) if simple else None,
            "packed": image.packed_file is not None, "users": int(image.users),
            "fake_user": bool(image.use_fake_user), "local_editable": bool(local_editable(image)),
            "pixel_contents_verified": False}


def binding_source(context: ToolContext, image: Any) -> dict | None:
    """Validate an existing loaded image without changing/reloading it; reusable by group binding."""
    if not local_editable(image) or image.source not in {"FILE", "GENERATED"} or getattr(image, "is_multiview", False):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Binding supports local editable single-view FILE/GENERATED images only.")
    if not image.has_data:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Load the image buffer explicitly before binding it; no implicit reload is performed.")
    source = None
    if image.source == "FILE":
        context.require(Permission.ACCESS_EXTERNAL_FILES)
        _path, header = _source_file(context, str(image.filepath))
        _exr_interpretation(header, image.colorspace_settings.name, image.alpha_mode)
        source = {k: v for k, v in header.items() if not k.startswith("_")}
    size = tuple(int(v) for v in image.size)
    if len(size) != 2 or min(size) < 1 or max(size) > MAX_DIMENSION or size[0] * size[1] > MAX_PIXELS:
        raise invalid_argument("Loaded image exceeds texture binding limits.")
    return source


def inspect_images(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "offset", "max_images"})
    offset = int_param(params, "offset", 0, minimum=0, maximum=1_000_000)
    maximum = int_param(params, "max_images", 32, minimum=1, maximum=64)
    bpy = require_blender()
    name = params.get("image_name")
    images = [image_exact(bpy, _name(params, "image_name"))] if name is not None else list(islice(bpy.data.images, offset, offset + maximum))
    records = []
    user_map = bpy.data.user_map(subset=set(images)) if images else {}
    remaining_users = 256
    for image in images:
        _check(context)
        owners = user_map.get(image, set())
        limit = min(100, remaining_users)
        direct = sorted(({"name": owner.name, "type": owner.bl_rna.identifier}
                         for owner in islice(owners, limit)), key=lambda item: (item["type"], item["name"]))
        remaining_users -= len(direct)
        records.append({**_summary(image), "direct_users": direct, "direct_user_count": len(owners),
                        "direct_users_truncated": len(owners) > limit})
    total = 1 if name is not None else len(bpy.data.images)
    root = _root()
    return {"images": records, "total_images": total, "offset": 0 if name is not None else offset,
            "truncated": name is None and offset + len(images) < total,
            "next_offset": offset + len(images) if name is None and offset + len(images) < total else None,
            "policy": {"approved_texture_directory": root[:4096], "directory_truncated": len(root) > 4096,
                       "max_file_bytes": MAX_FILE_BYTES, "format_file_byte_limits": file_limits(),
                       "max_dimension": MAX_DIMENSION, "max_pixels": MAX_PIXELS,
                       "formats": ["PNG", "8-bit JPEG", "uncompressed RGBA FLOAT32 EXR"], "remote_policy_changes_supported": False},
            "inspection_scope": "Existing datablock metadata/direct users, not file contents, transitive consumers or pixel arrays; unloaded image sizes are not probed."}


def load_image(context: ToolContext, params: Mapping[str, Any]) -> dict:
    from ._rna import apply_assignments, prepare_assignments

    reject_unknown_params(params, {"filepath", "new_name", "colorspace", "alpha_mode"})
    name = _name(params, "new_name")
    raw = params.get("filepath")
    color = params.get("colorspace", "sRGB")
    alpha = params.get("alpha_mode")
    if alpha is not None and (not isinstance(alpha, str) or alpha not in {"STRAIGHT", "PREMUL", "CHANNEL_PACKED", "NONE"}):
        raise invalid_argument("'alpha_mode' must be a reviewed native alpha identifier.")
    if not isinstance(color, str) or not color.strip() or len(color) > 128:
        raise invalid_argument("'colorspace' must be an explicit bounded color-space name.")
    _load_gate(context)
    bpy = require_blender()
    _object_mode(bpy)
    if bpy.data.images.get(name) is not None:
        raise invalid_argument("The requested image name already exists; no image is reused implicitly.")
    available = {item.identifier for item in bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"].enum_items}
    if color not in available:
        raise invalid_argument("The requested color space is unavailable in this Blender OCIO configuration.", colorspace=color)
    _check(context)
    path, preflight = _source_file(context, raw)
    _exr_interpretation(preflight, color, alpha)
    _check(context)
    _load_gate(context, preflight["_approved_root"])
    image = None
    created_image_name = None
    before = len(bpy.data.images)
    try:
        _object_mode(bpy)
        image = bpy.data.images.load(str(path), check_existing=False)
        created_image_name = image.name
        _load_gate(context, preflight["_approved_root"])
        image.name = name
        created_image_name = image.name
        image.use_fake_user = False
        image.colorspace_settings.name = color
        if alpha is not None and image.alpha_mode != alpha:
            apply_assignments(image, prepare_assignments(image, {"alpha_mode": alpha},
                allowed=frozenset({"alpha_mode"}), object_pointers=frozenset(), bpy=bpy))
        _check(context)
        _load_gate(context, preflight["_approved_root"])
        actual = tuple(int(v) for v in image.size)  # Explicit authorized decode, never a read-only probe.
        allowed_sizes = {(preflight["width"], preflight["height"])}
        if preflight["format"] == "JPEG":
            allowed_sizes.add((preflight["height"], preflight["width"]))  # Native EXIF orientation.
        if (not image.has_data or image.source != "FILE" or image.name != name or not local_editable(image)
                or actual not in allowed_sizes
                or image.colorspace_settings.name != color):
            raise RuntimeError("Loaded image did not match verified source metadata")
        if alpha is not None and image.alpha_mode != alpha:
            raise RuntimeError("Loaded image alpha mode did not match the requested role")
        if preflight["format"] == "EXR" and (image.channels != 4 or not image.is_float):
            raise RuntimeError("Reviewed EXR did not produce a four-channel native float buffer")
        checked_path, after = _source_file(context, str(image.filepath))
        if checked_path != path or after != preflight:
            raise RuntimeError("Texture source changed during native decoding")
        _load_gate(context, preflight["_approved_root"])
        return {"loaded": True, "reused_existing": False, "image": _summary(image),
                "source_file": {k: v for k, v in preflight.items() if not k.startswith("_")},
                "native_decode_interruptible": False, "file_written": False,
                "verification": "Source bytes/header and loaded dimensions/color space checked; not a pixel-content or artistic certificate."}
    except Exception as exc:
        LOGGER.exception("Image loading failed; attempting cleanup of only the newly created image")
        recovered = False
        cleanup_denied = False
        try:
            if image is not None:
                removed, cleanup_denied = cleanup_created_image(context, bpy, image)
                if removed:
                    image = None
            recovered = image is None and len(bpy.data.images) == before
        except Exception:
            LOGGER.exception("Image loading cleanup failed")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Image loading did not complete; inspect image state before continuing.",
                          {"execution_started": True, "requested_image": name,
                           "rollback_verified": recovered, "possible_mutation": not recovered,
                           "cleanup_permission_denied": cleanup_denied,
                           "created_image_name": created_image_name,
                           "retained_image_name": created_image_name if image is not None else None}) from exc


def remove_image(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"image_name", "confirm_unused"})
    name = _name(params, "image_name")
    if not bool_param(params, "confirm_unused", False):
        raise invalid_argument("Set 'confirm_unused' to true to remove this exact unused image datablock.")
    bpy = require_blender()
    _object_mode(bpy)
    image = image_exact(bpy, name)
    if not local_editable(image):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Image removal requires local, editable, non-override data.")
    if image.users != 0 or image.use_fake_user:
        raise invalid_argument("Image is still in use or has a fake user; no forced unlink is performed.", users=image.users)
    _check(context)
    context.require(Permission.EDIT_MATERIALS, Permission.DELETE_OBJECTS)
    bpy.data.images.remove(image, do_unlink=False)
    return {"removed_image": name, "file_deleted": False, "remaining_same_name": sum(i.name == name for i in bpy.data.images)}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("image.inspect", inspect_images, toolset="materials", permissions=(Permission.INSPECT_SCENE,),
                      description="Inspect bounded existing image metadata/direct users without loading unloaded buffers.")
    registry.register("image.load", load_image, toolset="materials", modifies=True,
                      permissions=(Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES),
                      description="Load a new bounded PNG/JPEG/plain FLOAT RGBA EXR texture from Blender's approved folder; no implicit reuse or file writes.")
    registry.register("image.remove", remove_image, toolset="materials", modifies=True,
                      permissions=(Permission.EDIT_MATERIALS, Permission.DELETE_OBJECTS),
                      description="Remove one explicitly confirmed unused local image datablock, never its source file.")
    registry.register("nodes.set_image", set_node_image, toolset="nodes", modifies=True,
                      permissions=(Permission.EDIT_MATERIALS,),
                      description="Bind/clear a loaded image and sampling settings at the root or explicit group_path; FILE images also require approved-path/external-file checks.")


def binding_target(context: ToolContext, params: Mapping[str, Any]) -> tuple[Any, Any, Any, dict, dict | None]:
    """Resolve and authorize one exact image node before file access/allocation."""
    from .material_scope import editable_material_scope
    from .nodes import _node_exact, _target_graph

    material, tree = _target_graph(context, params, modify=True)
    bpy = require_blender()
    _object_mode(bpy)
    scope = editable_material_scope(bpy, material, params)
    group_scope = None
    if tree != material.node_tree:
        from .shader_scope import ownership

        group_scope = ownership(bpy, tree, context.check_cancelled)
    if len(tree.nodes) > 256 or len(tree.links) > 1024:
        raise invalid_argument("Texture binding supports at most 256 root nodes / 1024 links.")
    node = _node_exact(tree, _name(params, "node_name"))
    if node.bl_idname != "ShaderNodeTexImage":
        raise invalid_argument("The exact target must be an Image Texture node.")
    return material, tree, node, scope, group_scope


def set_node_image(context: ToolContext, params: Mapping[str, Any]) -> dict:
    from ._rna import prepare_assignments

    reject_unknown_params(params, {"material_name", "node_name", "image_name", "interpolation", "projection", "extension", "allow_shared", "group_path"})
    if "image_name" not in params:
        raise invalid_argument("'image_name' is required; pass null explicitly to clear the binding.")
    material, tree, node, scope, group_scope = binding_target(context, params)
    bpy = require_blender()
    keys = frozenset({"interpolation", "projection", "extension"})
    settings = {key: params[key] for key in keys if key in params}
    assignments = prepare_assignments(node, settings, allowed=keys, object_pointers=frozenset(), bpy=bpy)
    image = image_exact(bpy, _name(params, "image_name")) if params["image_name"] is not None else None
    source = binding_source(context, image) if image is not None else None
    previous_image = node.image
    previous_name = previous_image.name if previous_image else None
    previous_settings = {key: getattr(node, key) for key in settings}
    previous_links = tuple(link.as_pointer() for link in tree.links)
    _check(context)
    context.require(Permission.EDIT_MATERIALS)
    if image is not None and image.source == "FILE":
        context.require(Permission.ACCESS_EXTERNAL_FILES)
    try:
        node.image = image
        for assignment in assignments:
            setattr(node, assignment.name, assignment.value)
        _check(context)
        if node.image != image or any(getattr(node, a.name) != a.value for a in assignments):
            raise RuntimeError("Texture binding readback did not match")
        if tuple(link.as_pointer() for link in tree.links) != previous_links:
            raise RuntimeError("Texture assignment unexpectedly changed graph links")
        return {"material": material.name, "node": node.name, "previous_image": previous_name,
                "image": _summary(image) if image else None,
                "sampling": {key: getattr(node, key) for key in sorted(keys)}, "ownership": scope,
                "node_tree": tree.name, "group_ownership": group_scope,
                "source_file_at_binding": source, "file_written": False,
                "verification": "Binding/settings/unchanged link identities checked; existing buffer not reloaded and pixel/file currency not certified."}
    except Exception as exc:
        LOGGER.exception("Texture binding failed; attempting scoped restoration")
        restored = False
        try:
            node.image = previous_image
            for key, value in previous_settings.items():
                setattr(node, key, value)
            restored = (node.image == previous_image and all(getattr(node, key) == value for key, value in previous_settings.items())
                        and tuple(link.as_pointer() for link in tree.links) == previous_links)
        except Exception:
            LOGGER.exception("Texture binding restoration failed")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Texture binding did not complete; reinspect the material.",
                          {"execution_started": True, "affected_material": material.name,
                           "rollback_verified": restored, "possible_mutation": not restored}) from exc
