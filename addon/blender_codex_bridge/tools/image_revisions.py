"""Copy-on-write texture source revisions, never in-place image-buffer reloads."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import reject_unknown_params, require_blender
from . import images
from .material_scope import local_editable
from .shader_scope import bounded_tree, path
from .shader_state import graph_guard

LOGGER = logging.getLogger(__name__)
TARGET_KEYS = ("material_name", "node_name", "group_path", "allow_shared")
SAMPLERS = ("interpolation", "projection", "extension")


def _retained(image: Any) -> dict:
    # Reference counts naturally change after rebinding; they are not metadata loss.
    return {key: value for key, value in images._summary(image).items() if key != "users"}


def refresh_image(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {*TARGET_KEYS, "new_image_name", "filepath"})
    new_name = images._name(params, "new_image_name")
    context.require(Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES)
    bpy = require_blender()
    target = {key: params[key] for key in TARGET_KEYS if key in params}
    material, tree, node, scope, group_scope = images.binding_target(context, target)
    bounded_tree(tree)
    old = node.image
    if old is None:
        raise invalid_argument("Refresh requires a bound image; use image.load/nodes.set_image for a new binding.")
    if (not local_editable(old) or old.source not in {"FILE", "GENERATED"}
            or getattr(old, "is_multiview", False)):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Refresh supports local single-view FILE/GENERATED source images only.")
    for owner in (material, tree, old):
        animation = getattr(owner, "animation_data", None)
        if animation is not None and (getattr(animation, "action", None) is not None
                or len(getattr(animation, "drivers", ())) or len(getattr(animation, "nla_tracks", ()))):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Texture revisions require unanimated material, target tree and image data.")
    if bpy.data.images.get(new_name) is not None:
        raise invalid_argument("The new image name already exists; no implicit reuse or overwrite is allowed.")
    source_path = params.get("filepath")
    if source_path is None:
        if old.source != "FILE":
            raise invalid_argument("A generated image requires an explicit approved filepath for a new FILE version.")
        source_path = str(old.filepath)
    previous = _retained(old)
    if previous["filepath_truncated"]:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Retained source path exceeds its bounded verification window.")
    alpha = old.alpha_mode
    guard = graph_guard(tree, node)
    samplers = {key: getattr(node, key) for key in SAMPLERS}
    images._check(context)
    # This loader owns cleanup if decoding fails, including cancellation and
    # unexpected new users. Do not reinterpret its measured failure verdict.
    loaded = images.load_image(context, {"filepath": source_path, "new_name": new_name,
                                        "colorspace": old.colorspace_settings.name, "alpha_mode": alpha})
    new = None
    try:
        new = images.image_exact(bpy, new_name)
        result = images.set_node_image(context, {**target, "image_name": new_name})
        if (result["source_file_at_binding"] != loaded["source_file"]
                or node.image != new or new.alpha_mode != alpha
                or new.colorspace_settings.name != previous["colorspace"]
                or graph_guard(tree, node) != guard
                or any(getattr(node, key) != value for key, value in samplers.items())
                or _retained(old) != previous):
            raise RuntimeError("Texture revision changed source bytes, retained metadata or graph invariants")
        images._check(context)
        context.require(Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES)
        return {"revision_mode": "new_image_for_node", "material": material.name, "node": node.name,
                "node_tree": tree.name, "group_path": path(params), "ownership": scope,
                "group_ownership": group_scope, "previous_image": images._summary(old),
                "image": images._summary(new), "source_file": loaded["source_file"],
                "sampling": samplers, "previous_buffer_reloaded": False,
                "image_identity_preserved": False, "links_and_socket_defaults_preserved": True,
                "native_decode_interruptible": False, "file_written": False,
                "verification_required": True,
                "verification": "New source/dimensions/color role, node binding and graph invariants checked. Old image retained, not reloaded or copied. Pixel/appearance and recovery require independent verification; old buffers/history are not durable backups."}
    except Exception as exc:
        LOGGER.exception("Versioned texture revision failed; attempting scoped binding/creation restoration")
        restored = False
        cleanup_denied = False
        try:
            node.image = old
            for key, value in samplers.items():
                setattr(node, key, value)
            if new is not None:
                _removed, cleanup_denied = images.cleanup_created_image(context, bpy, new)
            restored = (new is not None and node.image == old and bpy.data.images.get(new_name) is None
                        and _retained(old) == previous and graph_guard(tree, node) == guard
                        and all(getattr(node, key) == value for key, value in samplers.items()))
        except Exception:
            LOGGER.exception("Could not verify scoped texture revision restoration")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Texture revision failed; inspect retained image, binding and cleanup evidence.",
                          {"execution_started": True, "affected_material": material.name,
                           "previous_image": old.name, "requested_new_image": new_name,
                           "rollback_verified": restored, "possible_mutation": not restored,
                           "cleanup_permission_denied": cleanup_denied,
                           "verification_required": True}) from exc


def register_tools(registry: ToolRegistry) -> None:
    registry.register("nodes.refresh_image", refresh_image, toolset="nodes", modifies=True,
                      permissions=(Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES),
                      description="Refresh/relocate one image-node binding through a new approved FILE image version; retain the old image/buffer, never reload it in place.")
