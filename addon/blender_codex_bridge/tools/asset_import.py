"""Typed, bounded static imports from a separately approved READ folder.

Native import runs synchronously in a private scene over frozen self-contained
bytes. Publication and cleanup use owned-ID closures, never broad do_unlink.
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import re
import secrets
import time
from array import array
from collections.abc import Mapping
from typing import Any

from .. import scene_evidence
from ..asset_fbx_preflight import preflight_fbx
from ..asset_glb_preflight import preflight_glb
from ..asset_import_source import OwnedInput, read_source
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..preferences import get_preferences
from ..tool_registry import ToolContext, ToolRegistry, check_final_mutation
from ..utils import bool_param, reject_unknown_params, require_blender
from ._object_safety import require_local_editable_id

LOGGER = logging.getLogger(__name__)
SESSION_NONCE = secrets.token_hex(32)
READ = (Permission.INSPECT_SCENE, Permission.ACCESS_EXTERNAL_FILES)
REQUIRED = (
    *READ,
    Permission.EDIT_SCENE,
    Permission.TRANSFORM_OBJECTS,
    Permission.EDIT_MESH,
    Permission.EDIT_MATERIALS,
    Permission.EDIT_ANIMATION,
    Permission.DELETE_OBJECTS,
)
FAMILIES = (
    "actions",
    "armatures",
    "brushes",
    "cache_files",
    "cameras",
    "collections",
    "curves",
    "fonts",
    "grease_pencils",
    "hair_curves",
    "images",
    "lattices",
    "lightprobes",
    "lights",
    "linestyles",
    "masks",
    "materials",
    "meshes",
    "metaballs",
    "movieclips",
    "node_groups",
    "objects",
    "paint_curves",
    "palettes",
    "particles",
    "pointclouds",
    "scenes",
    "screens",
    "shape_keys",
    "sounds",
    "speakers",
    "texts",
    "textures",
    "volumes",
    "window_managers",
    "workspaces",
    "worlds",
)
ALLOWED_NEW = {"scenes", "collections", "objects", "meshes", "materials", "images"}
_QUARANTINED_IMPORT_BUILD = "d13f752e3b9c4f8c261cda552b1021f8bcc0382c"


def _require_native_import_build() -> None:
    """Refuse one observed crashing build without reading scene or caller data."""
    app = getattr(require_blender(), "app", None)
    version = getattr(app, "version", None)
    build = getattr(app, "build_hash", None)
    if type(build) is bytes:
        try:
            build = build.decode("ascii")
        except UnicodeDecodeError:
            return
    if version == (5, 2, 2) and type(build) is str and build in {
        _QUARANTINED_IMPORT_BUILD[:12],
        _QUARANTINED_IMPORT_BUILD,
    }:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            "Typed asset import is quarantined on this Blender build after native Python-GC crashes; the lifetime failure remains unresolved.",
            {
                "reason": "KNOWN_NATIVE_IMPORT_LIFETIME_FAILURE",
                "native_import_quarantined": True,
                "blender_version": [5, 2, 2],
                "blender_build_hash": build,
                "execution_started": False,
                "native_import_started": False,
                "source_accessed": False,
                "staging_allocated": False,
                "owned_ids_allocated": False,
                "project_saved": False,
                "safe_import_verified": False,
            },
        )


class _NativeImportAdmission:
    """Static runtime metadata only; never capture or adopt destination state."""

    __slots__ = ()

    def __call__(self) -> None:
        _require_native_import_build()

    def check_after_read(self) -> None:
        _require_native_import_build()


def _native_import_admission(
    _context: ToolContext, _params: Mapping[str, Any]
) -> _NativeImportAdmission:
    _require_native_import_build()
    return _NativeImportAdmission()


def _gate(context: ToolContext, *, writing=False) -> None:
    required = REQUIRED if writing else READ
    # Check cancellation before permission-provider reads, then finish all
    # provider callbacks before the terminal cancellation/stop-state proof.
    if context.check_cancelled:
        context.check_cancelled()
    context.require(*required)
    if context.check_cancelled:
        context.check_cancelled()
    flags = context.state.snapshot()
    if writing and flags.get("emergency_stopped"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Asset import was emergency-stopped.")
    if writing and flags.get("paused"):
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Asset import is paused.")
    if writing:
        check_final_mutation(context, "asset.import")


def _unsupported(message: str) -> None:
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, message)


def _key(value: Any) -> int | None:
    return int(value.as_pointer()) if value is not None else None


def _uid(value: Any) -> int:
    """Native ID identity, never a reusable memory address or a non-ID RNA wrapper."""
    uid = getattr(value, "session_uid", None)
    if type(uid) is not int or uid <= 0:
        _unsupported(
            "Exact asset import ownership requires Blender native ID session_uid evidence."
        )
    return uid


def _name(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf8")) > 63
        or any(ord(c) < 32 for c in value)
    ):
        raise invalid_argument(label + " requires an exact printable name within 63 UTF-8 bytes.")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    """A compact location summary of already bounded internal evidence."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in before.keys() | after.keys():
            result.extend(_changed_paths(before.get(key), after.get(key), prefix + "." + str(key)))
            if len(result) >= 16:
                return result[:16]
        return result
    return [prefix.lstrip(".")]


def _inventory(bpy: Any) -> dict[str, dict[int, Any]]:
    result = {
        family: {_uid(item): item for item in getattr(bpy.data, family)}
        for family in FAMILIES
        if hasattr(bpy.data, family)
    }
    if (
        sum(map(len, result.values())) > 4096
        or len(result["objects"]) > 128
        or len(result["materials"]) > 64
        or len(result["images"]) > 32
        or len(result["actions"]) > 64
    ):
        _unsupported(
            "Import preservation is bounded to 4096 IDs, 128 objects, 64 materials/actions and 32 images; narrow the destination first."
        )
    return result


def _id_state(item: Any) -> tuple:
    return (
        _key(item),
        _uid(item),
        item.name,
        (_key(item.library), _uid(item.library))
        if getattr(item, "library", None) is not None
        else None,
        # IDOverrideLibrary is an RNA wrapper, not an ID with session_uid.
        _key(getattr(item, "override_library", None)),
        bool(item.is_editable),
        bool(getattr(item, "use_fake_user", False)),
        bool(getattr(item, "use_extra_user", False)),
        int(item.users),
    )


def _image_state(image: Any, check) -> dict:
    if (
        image.type in {"RENDER_RESULT", "COMPOSITING"}
        and image.source == "VIEWER"
        and not image.has_data
    ):
        # Factory startup has empty Render Result/Viewer Node IDs. Do not query
        # their invalid colorspace enum or admit loaded viewer buffers as textures.
        return {
            "id": _id_state(image),
            "type": image.type,
            "source": image.source,
            "has_data": False,
            "path": image.filepath,
        }
    state = {
        "id": _id_state(image),
        "source": image.source,
        "path": image.filepath,
        "size": list(image.size) if image.has_data else None,
        "alpha": image.alpha_mode,
        "colorspace": image.colorspace_settings.name,
        "has_data": bool(image.has_data),
        "dirty": bool(image.is_dirty),
        "packed": [],
    }
    if image.source not in {"FILE", "GENERATED"} or len(getattr(image, "packed_files", ())) > 1:
        _unsupported(
            "Import preservation currently admits ordinary single-file/generated protected images only: "
            + image.name
            + " ("
            + image.type
            + ", "
            + image.source
            + ")."
        )
    packed = getattr(image, "packed_file", None)
    if packed:
        if packed.size > 64 * 1024 * 1024:
            _unsupported("Protected packed image bytes exceed 64 MiB.")
        state["packed"] = [packed.size, hashlib.sha256(packed.data).hexdigest()]
    if image.has_data:
        size = len(image.pixels)
        if size > 16_777_216 * 4:
            _unsupported("Protected image pixels exceed the bounded 4K-square budget.")
        digest = hashlib.sha256()
        # Slices do not open unloaded source files; has_data was checked first.
        for start in range(0, size, 16384):
            check()
            digest.update(array("f", image.pixels[start : start + 16384]).tobytes())
        state["pixels"] = [size, digest.hexdigest()]
    return state


def _scene_state(scene: Any, ignored_collections=frozenset()) -> dict:
    return {
        "id": _id_state(scene),
        "frame": [scene.frame_current, float(scene.frame_subframe)],
        "range": [scene.frame_start, scene.frame_end],
        "fps": [scene.render.fps, float(scene.render.fps_base)],
        "units": [
            scene.unit_settings.system,
            float(scene.unit_settings.scale_length),
            scene.unit_settings.length_unit,
        ],
        "camera": _key(scene.camera),
        "world": _key(scene.world),
        "root_objects": sorted(_key(obj) for obj in scene.collection.objects),
        "root_children": sorted(
            _key(child)
            for child in scene.collection.children
            if _key(child) not in ignored_collections
        ),
    }


def _guard(
    bpy: Any, ids: dict[str, dict[int, Any]], check=lambda: None, *, ignored_collections=frozenset()
) -> dict:
    """Enumerated measured state; no external path reads, RNA path execution or writes."""
    budget, cache = scene_evidence.Budget(1_000_000, check), {}
    result: dict[str, Any] = {
        "ids": {},
        "objects": {},
        "materials": {},
        "images": {},
        "actions": {},
        "scenes": {},
    }
    current = _inventory(bpy)
    aggregate_pixels = 0
    for family, items in ids.items():
        check()
        if any(key not in current[family] for key in items):
            raise invalid_argument("An import-protected ID was removed or replaced.")
        result["ids"][family] = [_id_state(item) for item in items.values()]
    for key, obj in ids["objects"].items():
        check()
        fields = {
            field: scene_evidence._capture_field(obj, field, budget, cache)
            for field in scene_evidence.FIELDS
            if field != "visibility"
        }
        if any(not value["complete"] for value in fields.values()):
            _unsupported(
                "Import cannot obtain complete bounded preservation evidence for destination geometry, rig, animation or shader dependencies."
            )
        result["objects"][key] = fields
    for key, material in ids["materials"].items():
        check()
        result["materials"][key] = scene_evidence._digest(
            scene_evidence._shader_dependency_records(material), budget
        )
    for key, action in ids["actions"].items():
        check()
        result["actions"][key] = scene_evidence._digest(
            scene_evidence._action_records(action), budget
        )
    for key, image in ids["images"].items():
        aggregate_pixels += int(image.size[0]) * int(image.size[1]) if image.has_data else 0
        if aggregate_pixels > 16_777_216:
            _unsupported("Protected loaded images exceed the aggregate 4K-square pixel budget.")
        result["images"][key] = _image_state(image, check)
    for key, scene in ids["scenes"].items():
        result["scenes"][key] = _scene_state(scene, ignored_collections)
    result["context"] = (
        _key(bpy.context.scene),
        _key(bpy.context.view_layer),
        bpy.context.mode,
        sorted(_key(obj) for obj in bpy.context.selected_objects),
        _key(bpy.context.view_layer.objects.active),
    )
    return result


def _source_root() -> str:
    return getattr(get_preferences(), "asset_source_directory", "")


def _runtime_admission(bpy: Any) -> None:
    if bpy.context.mode != "OBJECT":
        _unsupported("Reviewed asset import requires Object Mode.")
    require_local_editable_id(bpy.context.scene, operation="Asset import destination")
    require_local_editable_id(
        bpy.context.scene.collection, operation="Asset import destination root"
    )
    if abs(bpy.context.scene.unit_settings.scale_length - 1.0) > 1e-8:
        _unsupported(
            "Reviewed import requires one-metre destination units; conversion is explicitly reported."
        )
    # Import extensions can execute hooks even when the file has no extensions.
    # Inspect only enabled add-on modules, not arbitrary importable source paths.
    import sys

    for addon in bpy.context.preferences.addons:
        module = sys.modules.get(addon.module)
        if module is not None and any(
            hasattr(module, key)
            for key in ("glTF2ImportUserExtension", "glTF2ImportUserExtensions")
        ):
            _unsupported(
                "Enabled third-party glTF import hooks require separate behavior/ownership qualification."
            )


def _preview(context: ToolContext, params: Mapping[str, Any], *, writing=False):
    _gate(context, writing=writing)
    format = params.get("format")
    if format not in {"GLB", "FBX"}:
        raise invalid_argument("Asset source format must be GLB or FBX.")
    if bool_param(params, "include_animation", False):
        _unsupported(
            "Source animation/skin import needs separate native and preservation acceptance; it is never silently dropped."
        )
    bpy = require_blender()
    _runtime_admission(bpy)
    ids = _inventory(bpy)
    measured = _guard(bpy, ids, lambda: _gate(context, writing=writing))
    source = read_source(
        params.get("filepath"), format, _source_root(), lambda: _gate(context, writing=writing)
    )
    summary = (preflight_glb if format == "GLB" else preflight_fbx)(
        source.payload, lambda: _gate(context, writing=writing)
    )
    proof = source.proof()
    fingerprint = _hash(
        {"process_nonce": SESSION_NONCE, "source": proof, "summary": summary, "protected": measured}
    )
    return (
        bpy,
        ids,
        measured,
        source,
        {
            "fingerprint": fingerprint,
            "source": proof,
            **summary,
            "include_animation": False,
            "file_written": False,
            "project_saved": False,
            "native_import_interruptible": False,
            "preservation_coverage": "Enumerated geometry/UV/weights/rig/animation/shader definitions, complete loaded pixels/packed bytes, ID ownership and scene/context; not a universal handler or simulation-state guarantee.",
        },
    )


def import_preview(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"filepath", "format", "include_animation"})
    return _preview(context, params)[4]


def _new_ids(bpy: Any, before: dict) -> dict:
    return {
        family: {key: item for key, item in values.items() if key not in before[family]}
        for family, values in _inventory(bpy).items()
    }


def _retained_names(owned: dict | None) -> dict[str, list[str]]:
    """Removed RNA handles must never replace the primary failure evidence."""
    result = {}
    for family, values in (owned or {}).items():
        names = []
        for item in values.values():
            try:
                if _key(item):
                    names.append(item.name)
            except ReferenceError:
                continue
        if names:
            result[family] = names
    return result


def _closure(
    bpy: Any,
    owned: dict,
    stage: Any,
    collection: Any,
    destination: Any,
    *,
    published=False,
    require_loaded=True,
) -> None:
    current = _inventory(bpy)
    if any(
        current[family].get(key) != item
        for family, values in owned.items()
        for key, item in values.items()
    ):
        raise invalid_argument("An import-owned native ID was removed or replaced.")
    if any(values and family not in ALLOWED_NEW for family, values in owned.items()):
        _unsupported("Native import allocated an unreviewed ID family; publication is refused.")
    if set(owned["scenes"]) != {_uid(stage)} or _uid(collection) not in owned["collections"]:
        raise invalid_argument("Native import private scene/collection identity changed.")
    allowed = {_key(item) for values in owned.values() for item in values.values()}
    allowed.add(_key(stage.collection))
    allowed.update(
        _key(material.node_tree) for material in owned["materials"].values() if material.node_tree
    )
    if published:
        allowed.update({_key(destination), _key(destination.collection)})
    for values in owned.values():
        for item in values.values():
            require_local_editable_id(item, operation="Owned asset import publication/cleanup")
            if getattr(item, "use_fake_user", False):
                raise invalid_argument(
                    "Import-owned IDs acquired a fake user; their scope changed."
                )
    users = bpy.data.user_map(
        subset={item for values in owned.values() for item in values.values()}
    )
    for item, consumers in users.items():
        if any(_key(user) not in allowed for user in consumers):
            raise invalid_argument(
                "An imported ID acquired an unexpected protected consumer; cleanup/publication is refused.",
                data=item.name,
            )
    for obj in owned["objects"].values():
        if (
            obj.type not in {"MESH", "EMPTY"}
            or obj.instance_type != "NONE"
            or obj.constraints
            or obj.modifiers
            or obj.animation_data
        ):
            _unsupported("Native imported object graph is outside static mesh/empty scope.")
        if obj.data is not None and _uid(obj.data) not in owned["meshes"]:
            raise invalid_argument("Native import reused protected object data.")
        if obj.parent is not None and _uid(obj.parent) not in owned["objects"]:
            raise invalid_argument("Native import assigned a protected parent.")
        if any(_key(owner) not in allowed for owner in obj.users_collection):
            raise invalid_argument("Imported objects escaped their owned collection scope.")
    for mesh in owned["meshes"].values():
        if (
            mesh.shape_keys
            or mesh.animation_data
            or len(mesh.vertices) > 100_000
            or len(mesh.loops) > 600_000
        ):
            _unsupported("Native imported mesh exceeds reviewed bounds.")
        if any(
            material is not None and _uid(material) not in owned["materials"]
            for material in mesh.materials
        ):
            raise invalid_argument("Native import reused a protected material.")
    for material in owned["materials"].values():
        for node in material.node_tree.nodes if material.node_tree else ():
            if getattr(node, "node_tree", None) is not None:
                _unsupported(
                    "Native generated nested shader groups require a separately reviewed import contract."
                )
            image = getattr(node, "image", None)
            if image is not None and _uid(image) not in owned["images"]:
                raise invalid_argument("Native import reused a protected image.")
    for image in owned["images"].values():
        if (
            image.source != "FILE"
            or image.packed_file is None
            or (require_loaded and not image.has_data)
        ):
            raise invalid_argument(
                "Imported images must have complete loaded pixels and packed embedded bytes."
            )


def _owned_signature(bpy: Any, owned: dict) -> dict:
    # Exclude context and private scene metadata that intentionally change during
    # publication; consumer ownership is validated independently by _closure.
    result = _guard(bpy, owned)
    result.pop("context")
    return result


def _decode_owned_images(
    bpy: Any,
    context: ToolContext,
    before: dict,
    protected: dict,
    owned: dict,
    signature: dict,
    stage: Any,
    collection: Any,
    destination: Any,
    preview: dict,
    blocking: dict,
) -> dict:
    """Native packed decode is synchronous; admit only exact embedded input bytes."""
    expected = {record["file_sha256"]: record for record in preview["images"]}
    for key, image in owned["images"].items():
        _gate(context, writing=True)
        _closure(bpy, owned, stage, collection, destination, require_loaded=False)
        if _guard(bpy, before) != protected or _owned_signature(bpy, owned) != signature:
            raise invalid_argument(
                "Protected or owned import state changed before packed image decode."
            )
        digest = hashlib.sha256(image.packed_file.data).hexdigest()
        if digest not in expected:
            raise invalid_argument(
                "Native image packed bytes differ from preflighted embedded source images."
            )
        # Reading one pixel materializes the owned packed image; it never opens a
        # caller URI. Complete loaded pixels are then measured by _image_state.
        decode_started = time.monotonic()
        try:
            image.pixels[0]
        finally:
            blocking["largest_packed_image_decode_seconds"] = max(
                blocking["largest_packed_image_decode_seconds"], time.monotonic() - decode_started
            )
        after = _owned_signature(bpy, owned)
        unchanged = {**after, "images": {**after["images"], key: signature["images"][key]}}
        old_metadata = {
            name: value
            for name, value in signature["images"][key].items()
            if name not in {"pixels", "size", "has_data"}
        }
        new_metadata = {
            name: value
            for name, value in after["images"][key].items()
            if name not in {"pixels", "size", "has_data"}
        }
        record = expected[digest]
        if (
            unchanged != signature
            or old_metadata != new_metadata
            or not image.has_data
            or list(image.size) != [record["width"], record["height"]]
            or len(image.pixels) != record["width"] * record["height"] * 4
            or _guard(bpy, before) != protected
        ):
            raise invalid_argument(
                "Owned packed image decode changed unexpected state or dimensions."
            )
        signature = after
    return signature


def _native(bpy: Any, stage: Any, collection: Any, path: Any, format: str) -> None:
    with bpy.context.temp_override(
        scene=stage, view_layer=stage.view_layers[0], collection=collection
    ):
        if format == "GLB":
            properties = set(bpy.ops.import_scene.gltf.get_rna_type().properties.keys())
            kwargs = {
                "filepath": str(path),
                "import_pack_images": True,
                "merge_vertices": False,
                "bone_heuristic": "BLENDER",
                "disable_bone_shape": True,
            }
            for key, value in (
                ("import_scene_extras", False),
                ("import_scene_as_collection", False),
                ("import_select_created_objects", False),
                ("import_unused_materials", False),
            ):
                if key in properties:
                    kwargs[key] = value
            result = bpy.ops.import_scene.gltf(**kwargs)
        else:
            result = bpy.ops.import_scene.fbx(
                filepath=str(path),
                use_image_search=False,
                use_anim=False,
                anim_offset=0.0,
                use_custom_props=False,
            )
        if result != {"FINISHED"}:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Native asset importer did not finish.")


def _restore_selection(bpy: Any, selected: list, active: Any, layer: Any) -> None:
    current = {_key(obj): obj for obj in layer.objects}
    selected_ids = {_key(obj) for obj in selected}
    for key, obj in current.items():
        if obj.select_get(view_layer=layer) != (key in selected_ids):
            obj.select_set(key in selected_ids, view_layer=layer)
    if active is None or _key(active) in current:
        layer.objects.active = active


def _selection_restore_guard(
    bpy: Any,
    before: dict,
    protected: dict,
    owned: dict,
    signature: dict,
    stage: Any,
    collection: Any,
    destination: Any,
) -> None:
    """Only the expected temporary selection difference may precede its restoration."""
    current = _guard(bpy, before, ignored_collections={_key(collection)})
    if current["context"][:3] != protected["context"][:3]:
        raise invalid_argument(
            "Import scene, view layer or mode changed before selection restoration."
        )
    current["context"] = protected["context"]
    if current != protected or _owned_signature(bpy, owned) != signature:
        raise invalid_argument(
            "Protected or import-owned state changed before selection restoration."
        )
    _closure(bpy, owned, stage, collection, destination, published=True)


def _restore_import_selection(
    bpy: Any,
    context: ToolContext,
    before: dict,
    protected: dict,
    owned: dict,
    signature: dict,
    stage: Any,
    collection: Any,
    destination: Any,
    selected: list,
    active: Any,
    layer: Any,
) -> None:
    _gate(context, writing=True)
    _selection_restore_guard(
        bpy, before, protected, owned, signature, stage, collection, destination
    )
    check_final_mutation(context, "asset.import")
    _restore_selection(bpy, selected, active, layer)


def _rehome_owned(
    bpy: Any,
    before: dict,
    protected: dict,
    owned: dict,
    signature: dict,
    stage: Any,
    collection: Any,
    destination: Any,
    *,
    context: ToolContext | None = None,
) -> dict:
    # All source/permission callbacks have finished. Recheck the whole protected
    # context and exact owned closure before touching any collection membership.
    objects = list(owned["objects"].values())
    if any(obj.name not in stage.objects for obj in objects):
        raise invalid_argument("Imported objects were not contained in the private scene.")
    if _guard(bpy, before) != protected or _owned_signature(bpy, owned) != signature:
        raise invalid_argument("Imported definitions changed before owned rehoming.")
    _closure(bpy, owned, stage, collection, destination)
    if context is not None:
        check_final_mutation(context, "asset.import")
    for obj in objects:
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        for owner in list(obj.users_collection):
            if owner != collection:
                owner.objects.unlink(obj)
    return _owned_signature(bpy, owned)


def _remove_private_scene(bpy: Any, stage: Any) -> None:
    """Native Scenes retain an internal extra user; mapped/UI consumers forbid removal."""
    if (
        stage == bpy.context.scene
        or stage.objects
        or stage.collection.children
        or stage.use_fake_user
        or stage.users != int(stage.use_extra_user)
        or bpy.data.user_map(subset={stage}).get(stage, ())
        or any(
            window.scene == stage
            for manager in bpy.data.window_managers
            for window in manager.windows
        )
    ):
        raise invalid_argument(
            "Private import scene gained contents, a real consumer or a UI owner; removal is refused."
        )
    # 4.5/5.2 native probes demonstrate do_unlink=False rejects the sole internal
    # extra user. No ID/UI edges exist here to sever; never clear user counts.
    bpy.data.scenes.remove(stage, do_unlink=True)


def _cleanup(
    bpy: Any,
    context: ToolContext,
    before: dict,
    owned: dict,
    signature: dict,
    stage: Any,
    collection: Any,
    destination: Any,
    *,
    published: bool,
    protected: dict,
    native_format: str,
    blocking: dict,
) -> str:
    try:
        _gate(context, writing=True)
        # Every callback ends before identity/configuration/ownership checks.
        if _new_ids(bpy, before) != owned or _owned_signature(bpy, owned) != signature:
            return "retained_newer_or_unmeasured_owned_state"
        _closure(
            bpy, owned, stage, collection, destination, published=published, require_loaded=False
        )
        if _guard(bpy, before) != protected:
            return "retained_protected_state_changed"
        if native_format == "FBX":
            # Blender's native FBX helper graph has parent/child Python cycles
            # holding imported RNA. 5.2 failure->remove->reimport can crash during
            # shutdown collection after pointer reuse. Release cycles while all
            # IDs still exist, then treat finalizers as an untrusted callback.
            # This synchronous cleanup tail has no hard cancellation guarantee.
            started = time.monotonic()
            try:
                gc.collect()
            finally:
                blocking["fbx_cycle_release_seconds"] = time.monotonic() - started
            _gate(context, writing=True)
            _runtime_admission(bpy)
            if _new_ids(bpy, before) != owned or _owned_signature(bpy, owned) != signature:
                return "retained_newer_or_unmeasured_owned_state"
            _closure(
                bpy,
                owned,
                stage,
                collection,
                destination,
                published=published,
                require_loaded=False,
            )
            if _guard(bpy, before) != protected:
                return "retained_protected_state_changed"
        # Check the full closure once, then callback-free explicit unlink/removal.
        # Pre-existing consumers are never implicitly severed. Only the empty
        # private Scene's proven sole internal extra user needs do_unlink=True.
        check_final_mutation(context, "asset.import")
        for obj in owned["objects"].values():
            obj.parent = None
        for obj in owned["objects"].values():
            for owner in list(obj.users_collection):
                owner.objects.unlink(obj)
        for obj in owned["objects"].values():
            if obj.users:
                return "retained_unexpected_object_users"
            bpy.data.objects.remove(obj, do_unlink=False)
        for family in ("meshes", "materials", "images"):
            for item in owned[family].values():
                if item.users:
                    return "retained_unexpected_data_users"
                getattr(bpy.data, family).remove(item, do_unlink=False)
        roots = [stage.collection, *owned["collections"].values()]
        if published:
            roots.append(destination.collection)
        for parent in roots:
            for child in list(parent.children):
                if _uid(child) in owned["collections"]:
                    parent.children.unlink(child)
        for item in owned["collections"].values():
            if item.users:
                return "retained_unexpected_collection_users"
            bpy.data.collections.remove(item, do_unlink=False)
        _remove_private_scene(bpy, stage)
        return "removed"
    except Exception:
        LOGGER.info(
            "Owned asset import cleanup retained resources because live consent/ownership/configuration was not proven.",
            exc_info=True,
        )
        return "retained_ownership_consent_or_stop"


def import_asset(context: ToolContext, params: Mapping[str, Any]) -> dict:
    _require_native_import_build()
    reject_unknown_params(
        params,
        {
            "filepath",
            "format",
            "include_animation",
            "collection_name",
            "expected_fingerprint",
            "accepted_losses",
        },
    )
    _gate(context, writing=True)
    collection_name = _name(params.get("collection_name"), "collection_name")
    bpy, before, protected, source, preview = _preview(context, params, writing=True)
    expected = params.get("expected_fingerprint")
    if (
        not isinstance(expected, str)
        or not re.fullmatch("[0-9a-f]{64}", expected)
        or expected != preview["fingerprint"]
    ):
        raise invalid_argument(
            "Import requires the exact current source/destination preview fingerprint."
        )
    if params.get("accepted_losses") != preview["required_accepted_losses"]:
        raise invalid_argument("accepted_losses must repeat the preview list exactly.")
    if bpy.data.collections.get(collection_name) is not None:
        raise invalid_argument("collection_name must be unused; no silent rename or replacement.")
    destination, layer = bpy.context.scene, bpy.context.view_layer
    selected, active = list(bpy.context.selected_objects), layer.objects.active
    staging = OwnedInput(source)
    stage = collection = owned = signature = None
    allocated: dict[str, dict[int, Any]] = {"scenes": {}, "collections": {}}
    published, native_started, preserved, cleanup = False, False, False, "not_allocated"
    blocking = {
        "native_import_seconds": 0.0,
        "fbx_cycle_release_seconds": 0.0,
        "largest_packed_image_decode_seconds": 0.0,
        "publication_view_layer_update_seconds": 0.0,
    }
    failure = None
    try:
        staging.create(lambda: _gate(context, writing=True))
        _gate(context, writing=True)
        _runtime_admission(bpy)
        source.verify(_source_root(), lambda: _gate(context, writing=True))
        staging.verify(lambda: _gate(context, writing=True))
        if (
            _guard(bpy, before) != protected
            or _inventory(bpy) != before
            or bpy.data.collections.get(collection_name) is not None
        ):
            raise invalid_argument(
                "Destination or collection availability changed before native import."
            )
        check_final_mutation(context, "asset.import")
        stage = bpy.data.scenes.new("Bridge Private Asset Import")
        allocated["scenes"][_uid(stage)] = stage
        collection = bpy.data.collections.new(collection_name)
        allocated["collections"][_uid(collection)] = collection
        stage.collection.children.link(collection)
        stage.render.fps, stage.render.fps_base = (
            destination.render.fps,
            destination.render.fps_base,
        )
        check_final_mutation(context, "asset.import")
        native_started = True
        native_start = time.monotonic()
        try:
            _native(bpy, stage, collection, staging.path, preview["format"])
        finally:
            blocking["native_import_seconds"] = time.monotonic() - native_start
            # Seal the native allocation immediately, before cancellation/user
            # callbacks can install new consumers or edit its owned contents.
            owned = _new_ids(bpy, before)
            signature = _owned_signature(bpy, owned)
        _gate(context, writing=True)
        _closure(bpy, owned, stage, collection, destination, require_loaded=False)
        signature = _decode_owned_images(
            bpy,
            context,
            before,
            protected,
            owned,
            signature,
            stage,
            collection,
            destination,
            preview,
            blocking,
        )
        _closure(bpy, owned, stage, collection, destination)
        if _guard(bpy, before) != protected:
            raise invalid_argument(
                "Native import changed measured protected data or destination context."
            )
        source.verify(_source_root(), lambda: _gate(context, writing=True))
        staging.verify(lambda: _gate(context, writing=True))
        objects = list(owned["objects"].values())
        if len(objects) != preview["objects"]:
            raise invalid_argument(
                "Native import object count differs from complete source preflight."
            )
        # Native glTF honors private scene, but not collection override. Move only
        # its frozen owned objects; no callback between final guard and writes.
        signature = _rehome_owned(
            bpy, before, protected, owned, signature, stage, collection, destination, context=context
        )
        _gate(context, writing=True)
        _runtime_admission(bpy)
        source.verify(_source_root(), lambda: _gate(context, writing=True))
        staging.verify(lambda: _gate(context, writing=True))
        if _guard(bpy, before) != protected or _owned_signature(bpy, owned) != signature:
            raise invalid_argument("Protected or import-owned state changed before publication.")
        _closure(bpy, owned, stage, collection, destination)
        # Publication is intentionally one native main-thread boundary. Retain
        # published resources on cancellation; never perform a late blind undo.
        check_final_mutation(context, "asset.import")
        stage.collection.children.unlink(collection)
        destination.collection.children.link(collection)
        published = True
        signature = _owned_signature(bpy, owned)
        # A newly linked collection is not immediately in view_layer.objects.
        # Update its native membership before restoring per-view-layer selection.
        membership_started = time.monotonic()
        try:
            check_final_mutation(context, "asset.import")
            layer.update()
        finally:
            blocking["publication_view_layer_update_seconds"] = (
                time.monotonic() - membership_started
            )
        _restore_import_selection(
            bpy,
            context,
            before,
            protected,
            owned,
            signature,
            stage,
            collection,
            destination,
            selected,
            active,
            layer,
        )
        _gate(context, writing=True)
        _closure(bpy, owned, stage, collection, destination, published=True)
        final_protected = _guard(bpy, before, ignored_collections={_key(collection)})
        preserved = final_protected == protected
        if not preserved or _owned_signature(bpy, owned) != signature:
            raise invalid_argument(
                "Published import or protected data changed during final verification: "
                + str(_changed_paths(protected, final_protected))
            )
        staging.verify(lambda: _gate(context, writing=True))
        # Private-scene deletion is a separate live deletion boundary, checking
        # exact zero-user ownership after the final callback.
        _gate(context, writing=True)
        _closure(bpy, owned, stage, collection, destination, published=True)
        if _guard(bpy, before, ignored_collections={_key(collection)}) != protected:
            raise invalid_argument(
                "Protected destination changed at final private-scene cleanup boundary."
            )
        if _owned_signature(bpy, owned) != signature:
            raise invalid_argument(
                "Owned imported definitions changed at final private-scene cleanup boundary."
            )
        stage_key = _uid(stage)
        check_final_mutation(context, "asset.import")
        _remove_private_scene(bpy, stage)
        owned["scenes"].pop(stage_key, None)
        cleanup = "published_private_scene_removed"
    except Exception as error:
        # Keep detailed failure diagnostics local before releasing RNA-bearing
        # traceback frames. Removed owned IDs must not survive in an exception
        # cycle until Blender's database teardown.
        LOGGER.info("Asset import failed before completion.", exc_info=True)
        failure = error.with_traceback(None)
        if owned is not None and signature is not None and stage is not None:
            # A published import remains inspectable; native undo is the explicit
            # project recovery mechanism. Remove only unpublished exact closure.
            cleanup = (
                "published_retained"
                if published
                else _cleanup(
                    bpy,
                    context,
                    before,
                    owned,
                    signature,
                    stage,
                    collection,
                    destination,
                    published=False,
                    protected=protected,
                    native_format=preview["format"],
                    blocking=blocking,
                )
            )
    finally:
        staging.cleanup(lambda: _gate(context, writing=True))
    evidence = {
        "external_effects": staging.evidence(),
        "native_import_started": native_started,
        "import_published": published,
        "owned_id_cleanup": cleanup,
        "protected_measured_state_preserved": preserved,
        "project_saved": False,
        "native_import_interruptible": False,
        "native_blocking_intervals_seconds": blocking,
        "owned_allocation_inventory_complete": owned is not None,
        "unmeasured_native_resources_possible": native_started and owned is None,
        "source": source.proof(),
    }
    if failure is not None:
        raise BridgeError(
            failure.code if isinstance(failure, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Asset import did not complete; inspect exact scene resources/effects before retrying.",
            {
                **evidence,
                "possible_mutation": native_started or stage is not None,
                "cause": failure.to_dict()
                if isinstance(failure, BridgeError)
                else {"code": "OPERATION_FAILED"},
                "retained_owned_ids": _retained_names(owned if owned is not None else allocated)
                if cleanup != "removed"
                else {},
            },
        ) from failure
    return {
        **evidence,
        "imported": True,
        "collection": collection.name,
        "imported_objects": [obj.name for obj in owned["objects"].values()],
        "imported_materials": [item.name for item in owned["materials"].values()],
        "imported_images": [item.name for item in owned["images"].values()],
        "preview_fingerprint": expected,
        "accepted_losses": preview["required_accepted_losses"],
        "structural_verification": "Complete source admission, fresh owned ID closure, packed image availability, protected measured definitions/pixels and destination context verified.",
        "visual_appearance_verified": False,
        "fresh_process_reopen_verified": False,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "asset.import_preview",
        import_preview,
        toolset="asset_delivery",
        permissions=READ,
        description="Read an approved self-contained static GLB or material-free FBX and preview exact source/destination fingerprint and conversion limits.",
    )
    registry.register(
        "asset.import",
        import_asset,
        toolset="asset_delivery",
        permissions=REQUIRED,
        modifies=True,
        batchable=False,
        exclusive_mutation=True,
        checkpoint_admission_factory=_native_import_admission,
        description="Import a fingerprinted bounded static GLB/FBX over frozen private source bytes into one new owned collection, preserving measured destination state; no project save.",
    )
