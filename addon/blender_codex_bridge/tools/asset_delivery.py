"""Reviewed, scoped native GLB/FBX exports with owned no-clobber publication.

This module never imports arbitrary assets into the user's scene. Its native
reader acceptance fixture imports only artifacts generated in its owned bundle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import stat
import struct
import tempfile
import uuid
from collections.abc import Mapping
from copy import deepcopy
from itertools import islice
from pathlib import Path, PureWindowsPath
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..image_files import _absolute, _local_drive
from ..permissions import Permission
from ..preferences import get_preferences
from ..texture_staging import _ancestors, _directory_id, _DirectoryPins
from ..tool_registry import ToolContext, ToolRegistry, check_final_mutation
from ..utils import bool_param, reject_unknown_params, require_blender
from ._object_safety import require_local_editable_id
from .animation import _action_fcurves

LOGGER = logging.getLogger(__name__)
REQUIRED = (Permission.INSPECT_SCENE, Permission.EDIT_SCENE,
            Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT)
MAX_OBJECTS, MAX_VERTICES, MAX_BONES, MAX_FRAMES = 64, 100_000, 256, 250
MAX_BYTES, READ_BYTES = 512 * 1024 * 1024, 65536
FORMAT_LIMITS = ["VERTEX_SPLITS", "AXIS_CONVERSION"]
SESSION_NONCE = uuid.uuid4().hex


def _unsupported(message: str, **evidence) -> None:
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, message, evidence)


def _parameter_facts(params: Mapping[str, Any]) -> tuple:
    if (type(params) is not dict or len(params) > 8
            or any(type(key) is not str for key in params)):
        raise invalid_argument("Asset arguments require a plain bounded parameter object.")
    result = []
    for key, value in sorted(params.items()):
        if type(value) is list:
            if len(value) > 64 or any(type(item) is not str for item in value):
                raise invalid_argument("Asset list arguments require bounded strings.")
            result.append((key, "list", tuple(value)))
        elif type(value) in (str, bool):
            result.append((key, type(value).__name__, value))
        else:
            raise invalid_argument("Unsupported asset argument type.")
    return tuple(result)


class _Entry:
    """Retain exact registered authority before providers; no later adoption."""

    def __init__(self, context: ToolContext, method: str, params: Mapping[str, Any]):
        self.context, self.method, self.original = context, method, params
        self.facts = _parameter_facts(params)
        self.params = deepcopy(params)
        registry = getattr(context, "registry", None)
        if registry is None:
            _unsupported("Asset delivery requires an exact registered request context.")
        self.registry, self.spec = registry, registry.get(method)
        self.services = tuple((name, getattr(context, name, None)) for name in (
            "state", "request_lifecycle", "check_final_request", "check_final_job", "checkpoint_admission"))
        self.stopped: BridgeError | None = None

    def refuse(self, error: Exception) -> BridgeError:
        if self.stopped is None:
            self.stopped = error if isinstance(error, BridgeError) else BridgeError(
                ErrorCode.OPERATION_FAILED, "Asset authority or its measured scope could not be revalidated.")
        return self.stopped

    def final(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            if getattr(self.context, "registry", None) is not self.registry:
                raise invalid_argument("Asset request registry identity changed during authorization.")
            if any(getattr(self.context, name, None) is not service for name, service in self.services):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Asset caller lifecycle service identity changed.")
            if _parameter_facts(self.original) != self.facts:
                raise invalid_argument("Asset request arguments changed during authorization.")
            check_final_mutation(self.context, self.method, expected_spec=self.spec)
        except Exception as error:
            refused = self.refuse(error)
            if refused is error:
                raise
            raise refused from error

    def authorize(self, *, writing: bool = False) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            if self.context.check_cancelled:
                self.context.check_cancelled()
            self.context.require(*(REQUIRED if writing else (Permission.INSPECT_SCENE,)))
            self.final()
        except Exception as error:
            refused = self.refuse(error)
            if refused is error:
                raise
            raise refused from error


def _root() -> str:
    return getattr(get_preferences(), "asset_directory", "")


def _numbers(values) -> list[float]:
    result = [float(value) for value in values]
    if not all(math.isfinite(value) and abs(value) <= 1e9 for value in result):
        raise invalid_argument("Asset values must be finite and bounded.")
    return result


def _matrix(value) -> list[list[float]]:
    return [_numbers(row) for row in value]


def _pointer(value: Any) -> int:
    pointer = value.as_pointer()
    if type(pointer) is not int or pointer <= 0:
        _unsupported("Asset identity requires a positive native pointer.")
    return pointer


def _identity(value: Any) -> tuple[int, int]:
    uid = getattr(value, "session_uid", None)
    if type(uid) is not int or uid <= 0 or not callable(getattr(value, "as_pointer", None)):
        _unsupported("Asset identity requires a native session UID and pointer; no fallback is admitted.")
    return uid, _pointer(value)


def _file_identity(value) -> tuple:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _animation(obj, include: bool) -> list[dict] | dict:
    data = getattr(obj, "animation_data", None)
    if data is None:
        return []
    if len(data.drivers) or len(data.nla_tracks):
        _unsupported("Asset export does not yet support drivers or NLA dependency graphs.", object=obj.name)
    action = data.action
    if action is None:
        return []
    if not include:
        _unsupported("An animated asset requires include_animation=true; animation is never silently dropped.", object=obj.name)
    require_local_editable_id(action, operation="Asset animation export")
    allowed = {"location", "rotation_euler", "rotation_quaternion", "scale"}
    if obj.type == "ARMATURE":
        allowed.update(bone.path_from_id(path) for bone in obj.pose.bones
                       for path in ("location", "rotation_euler", "rotation_quaternion", "scale"))
    curves = []
    slot = getattr(data, "action_slot", None)
    handle = getattr(slot, "handle", None)
    for curve, curve_slot in islice(_action_fcurves(action), 1025):
        if curve_slot is not None and curve_slot != handle:
            continue
        if len(curves) >= 1024 or curve.data_path not in allowed or len(curve.modifiers):
            _unsupported("Only bounded unmodified transform curves are reviewed for sampled asset animation.", object=obj.name)
        if len(curve.keyframe_points) > 2000 or len(getattr(curve, "sampled_points", ())):
            _unsupported("Asset animation requires bounded editable transform keyframes.", object=obj.name)
        curves.append({"path": curve.data_path, "index": curve.array_index,
            "mute": bool(curve.mute), "keys": [
                [_numbers(point.co), point.interpolation, _numbers(point.handle_left), _numbers(point.handle_right)]
                for point in curve.keyframe_points]})
    return {"action_identity": _identity(action), "action_name": action.name,
            "slot_handle": handle, "curves": curves}


def _scope(context: ToolContext, params: Mapping[str, Any], *, entry: _Entry,
           authorize: bool = True) -> tuple[Any, list[Any], dict]:
    if authorize:
        entry.authorize()
    names = params.get("object_names")
    if (not isinstance(names, list) or not 1 <= len(names) <= MAX_OBJECTS
            or any(not isinstance(name, str) or not name.strip() or len(name) > 256
                   or any(ord(c) < 32 for c in name) for name in names)
            or len(set(names)) != len(names)):
        raise invalid_argument("object_names must contain 1-64 distinct exact printable names.")
    format = params.get("format")
    if format not in {"GLB", "FBX"}:
        raise invalid_argument("Asset format must be GLB or FBX.")
    include = bool_param(params, "include_animation", False)
    bpy = require_blender()
    if bpy.context.mode != "OBJECT":
        _unsupported("Asset export requires Object Mode.")
    scene = bpy.context.scene
    if abs(float(scene.unit_settings.scale_length) - 1.) > 1e-8:
        _unsupported("Reviewed asset export requires a unit scale of one metre; no implicit rescaling is performed.")
    if len(bpy.data.objects) > 2048:
        _unsupported("Asset context preservation is bounded to scenes with at most 2048 objects.")
    if include and not 1 <= scene.frame_end - scene.frame_start + 1 <= MAX_FRAMES:
        raise invalid_argument("Animated asset exports support at most 250 integer frames.")
    objects = []
    for name in names:
        matches = list(islice((obj for obj in bpy.data.objects if obj.name == name), 2))
        if len(matches) != 1:
            raise invalid_argument("Asset object name is missing or ambiguous.", object=name)
        obj = matches[0]
        require_local_editable_id(obj, operation="Scoped asset export")
        if obj.type not in {"MESH", "ARMATURE", "EMPTY"}:
            _unsupported("Only local mesh/armature/empty asset objects are reviewed.", object=name)
        if (obj.name not in bpy.context.view_layer.objects or not obj.visible_get()
                or obj.hide_render or obj.hide_select or obj.instance_type != "NONE"):
            _unsupported("Export targets must be visible, selectable, non-instanced members of the current view layer.", object=name)
        if len(obj.constraints) or getattr(obj, "rigid_body", None) is not None:
            _unsupported("Constrained and simulated asset objects require separate dependency acceptance.", object=name)
        if obj.parent is not None and obj.parent.name not in names:
            _unsupported("Every export parent must be explicitly included in object_names.", object=name, parent=obj.parent.name)
        if obj.parent_type not in {"OBJECT", "ARMATURE"}:
            _unsupported("Bone/vertex parenting is not reviewed for asset export.", object=name)
        objects.append(obj)
    records, vertices = [], 0
    for obj in objects:
        if authorize:
            entry.authorize()
        record = {"name": obj.name, "type": obj.type, "identity": _identity(obj),
            "parent": obj.parent.name if obj.parent else None, "matrix_basis": _matrix(obj.matrix_basis),
            "matrix_parent_inverse": _matrix(obj.matrix_parent_inverse), "animation": _animation(obj, include)}
        if obj.data is not None:
            require_local_editable_id(obj.data, operation="Scoped asset data export")
            if getattr(obj.data, "animation_data", None) is not None:
                _unsupported("Animated object data is not reviewed for asset export.", object=obj.name)
            record["data_identity"] = _identity(obj.data)
        if obj.type == "MESH":
            mesh = obj.data
            vertices += len(mesh.vertices)
            if (not len(mesh.vertices) or not len(mesh.polygons)
                    or vertices > MAX_VERTICES or len(mesh.polygons) > MAX_VERTICES
                    or any(len(polygon.vertices) != 3 for polygon in mesh.polygons)
                    or len(mesh.uv_layers) > 1 or mesh.shape_keys is not None
                    or len(mesh.color_attributes) or any(slot.material is not None for slot in obj.material_slots)):
                _unsupported("Reviewed delivery requires material-free triangle meshes, at most one UV layer, no shape keys/color layers and at most 100000 total vertices.", object=obj.name)
            allowed_attributes = {"position", "sharp_face", *(layer.name for layer in mesh.uv_layers)}
            if getattr(mesh, "has_custom_normals", False) or any(
                    not attribute.is_internal and attribute.name not in allowed_attributes
                    for attribute in mesh.attributes):
                _unsupported("Custom normals and custom mesh attributes need explicit downstream loss acceptance.", object=obj.name)
            bones = None
            modifiers = list(obj.modifiers)
            if len(modifiers) > 1 or any(mod.type != "ARMATURE" for mod in modifiers):
                _unsupported("Only one explicitly scoped armature modifier is reviewed; other modifiers are not silently applied.", object=obj.name)
            if modifiers:
                modifier = modifiers[0]
                rig = modifier.object
                if (rig is None or rig not in objects or rig.type != "ARMATURE" or not modifier.show_viewport
                        or not modifier.show_render or not modifier.use_vertex_groups
                        or modifier.use_bone_envelopes or modifier.use_deform_preserve_volume
                        or modifier.vertex_group):
                    _unsupported("Skinning requires an included rig and unmasked linear vertex-group deformation.", object=obj.name)
                bones = {bone.name for bone in rig.data.bones if bone.use_deform}
                record["armature"] = rig.name
            if obj.vertex_groups and bones is None:
                _unsupported("Vertex groups without a reviewed armature would be lost during delivery.", object=obj.name)
            groups = {group.index: group.name for group in obj.vertex_groups}
            weights = []
            for vertex in mesh.vertices:
                if any(not math.isfinite(group.weight) or not 0. <= group.weight <= 1. for group in vertex.groups):
                    raise invalid_argument("Skin weights must be finite values in [0,1].", object=obj.name)
                assignments = [(groups[group.group], float(group.weight)) for group in vertex.groups if group.weight > 0.]
                if bones is not None and (not 1 <= len(assignments) <= 4
                        or any(name not in bones for name, _weight in assignments)
                        or abs(sum(weight for _name, weight in assignments) - 1.) > 1e-5):
                    _unsupported("Each skinned vertex requires 1-4 normalized influences from included deform bones.", object=obj.name)
                weights.append(assignments)
            record.update(vertices=[_numbers(vertex.co) for vertex in mesh.vertices],
                triangles=[list(polygon.vertices) for polygon in mesh.polygons], weights=weights,
                smooth=[bool(polygon.use_smooth) for polygon in mesh.polygons],
                uv=[_numbers(item.uv) for item in mesh.uv_layers[0].data] if mesh.uv_layers else [])
        elif obj.type == "ARMATURE":
            if len(obj.data.bones) > MAX_BONES or obj.data.pose_position != "POSE":
                _unsupported("Rig delivery supports at most 256 bones in Pose evaluation.", object=obj.name)
            if any(len(bone.constraints) or bone.custom_shape is not None for bone in obj.pose.bones):
                _unsupported("Rig constraints/custom shapes must be resolved explicitly before reviewed export.", object=obj.name)
            record["bones"] = [{"name": bone.name, "parent": bone.parent.name if bone.parent else None,
                "matrix_local": _matrix(bone.matrix_local), "deform": bool(bone.use_deform)} for bone in obj.data.bones]
            record["pose"] = [{"name": bone.name, "matrix_basis": _matrix(bone.matrix_basis)} for bone in obj.pose.bones]
            if not include and any(abs(value - (1. if row == column else 0.)) > 1e-7
                    for bone in obj.pose.bones for row, values in enumerate(bone.matrix_basis)
                    for column, value in enumerate(values)):
                _unsupported("Static skin export requires an undeformed rest pose; include sampled animation to deliver a posed rig.", object=obj.name)
        elif obj.modifiers:
            _unsupported("Empty export parents cannot have modifiers.", object=obj.name)
        records.append(record)
    if not any(obj.type == "MESH" for obj in objects):
        raise invalid_argument("An exported asset must contain at least one mesh.")
    signature = {"process_nonce": SESSION_NONCE, "objects": records, "scene": scene.name,
        "scene_identity": _identity(scene), "view_layer_identity": _pointer(bpy.context.view_layer),
        "format": format, "include_animation": include,
        "frames": [scene.frame_start, scene.frame_end], "current_frame": scene.frame_current,
        "subframe": float(scene.frame_subframe), "fps": [scene.render.fps, float(scene.render.fps_base)],
        "unit_system": scene.unit_settings.system, "unit_scale": float(scene.unit_settings.scale_length)}
    fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    losses = [*FORMAT_LIMITS, *(["BONE_AXIS_CONVERSION"] if any(obj.type == "ARMATURE" for obj in objects) else []),
              *(["SAMPLED_INTEGER_FRAMES"] if include else [])]
    return bpy, objects, {"fingerprint": fingerprint, "format": format, "include_animation": include,
        "object_names": names, "objects": [{"name": row["name"], "type": row["type"],
            "vertices": len(row.get("vertices", [])), "triangles": len(row.get("triangles", [])),
            "bones": len(row.get("bones", []))} for row in records],
        "required_accepted_losses": losses, "frame_range": signature["frames"], "fps": signature["fps"],
        "unit_scale_metres": 1., "scope": "Material-free triangulated static/skinned assets; transform animation sampled at integer frames. No arbitrary file import, material/texture, sculpt, simulation, custom-attribute or project-identity preservation claim."}


def export_preview(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_names", "format", "include_animation"})
    entry = _Entry(context, "asset.export_preview", params)
    entry.authorize()
    _bpy, _objects, preview = _scope(context, entry.params, entry=entry, authorize=False)
    entry.final()
    return {**preview, "file_written": False, "native_roundtrip_verified": False}


def _approved_output(raw: str, root_raw: str, format: str) -> tuple[Path, Path]:
    if not root_raw:
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "Choose an Approved Asset Folder in Blender first.")
    root, target = _absolute(root_raw, "Asset folder"), _absolute(raw, "Asset output")
    if target.suffix.lower() != "." + format.lower():
        raise invalid_argument("Asset output extension must match GLB/FBX format.")
    for path in (root, target):
        if any(PureWindowsPath(part).is_reserved() or part.endswith((".", " ")) for part in path.parts[1:]):
            raise invalid_argument("Asset paths cannot use reserved devices or trailing dots/spaces.")
    try:
        folder, parent = root.resolve(strict=True), target.parent.resolve(strict=True)
        if folder == Path(folder.anchor) or not folder.is_dir():
            raise invalid_argument("Approved asset folder must be an existing subdirectory.")
        if not parent.is_relative_to(folder):
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Asset output is outside Blender's approved asset folder.")
        if (not _local_drive(parent) or (os.name != "nt" and len(parent.parts) > 1
                and parent.parts[1] in {"dev", "proc", "sys"})):
            raise invalid_argument("Asset output must use an ordinary local directory.")
        for path in {*_ancestors(root), *_ancestors(target.parent)}:
            _directory_id(path)
    except (OSError, RuntimeError) as exc:
        raise invalid_argument("Asset output needs an existing ordinary local parent.") from exc
    return folder, parent / target.name


def _absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise invalid_argument("Asset output exists; overwrite and automatic rename are forbidden.")


class _Staging:
    def __init__(self, entry, raw, format):
        self.entry, self.context, self.raw, self.format = entry, entry.context, raw, format
        self.root = _root()
        self.folder, self.path = _approved_output(raw, self.root, format)
        self.parent_id = _directory_id(self.path.parent)
        self.directory = self.stage = self.stage_inode = self.directory_id = None
        self.stage_state = None
        self.pins = None
        self.published = self.attempted = self.verified = False
        self.sha256, self.bytes, self.cleanup_status = None, None, "not_created"
        self.source_check = None

    def _scope_operation(self, operation):
        """Uncertain artifact observations never authorize later cleanup."""
        try:
            return operation()
        except Exception as error:
            refused = self.entry.refuse(error)
            if refused is error:
                raise
            raise refused from error

    def write_check(self):
        self.check()
        assert self.source_check is not None
        self.source_check()
        self.entry.final()

    def check(self, *, cleanup=False):
        try:
            self.entry.authorize(writing=True)
            self._location()
            self.entry.final()
        except Exception as error:
            refused = self.entry.refuse(error)
            if refused is error:
                raise
            raise refused from error

    def _location(self):
        if _root() != self.root or _approved_output(self.raw, self.root, self.format) != (self.folder, self.path) or _directory_id(self.path.parent) != self.parent_id:
            raise invalid_argument("Approved asset output location changed; reinspect retained effects.")
        if self.directory is not None and _directory_id(self.directory) != self.directory_id:
            raise invalid_argument("Owned asset staging directory changed.")

    def native_write_check(self):
        def measured():
            self._location()
            self.owned()
            self.entry.final()
        return self._scope_operation(measured)

    def open(self):
        return self._scope_operation(self._open)

    def _open(self):
        self.write_check()
        _absent(self.path)
        self.entry.final()
        self.directory = Path(tempfile.mkdtemp(prefix=".blender-codex-asset-", dir=self.path.parent))
        self.directory_id = _directory_id(self.directory)
        self.cleanup_status = "pending"
        self.pins = _DirectoryPins(self.directory)
        self.stage = self.directory / ("payload." + self.format.lower())
        self.write_check()
        self.entry.final()
        descriptor = os.open(self.stage, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            value = os.fstat(descriptor)
            self.stage_inode = value.st_dev, value.st_ino
            self.stage_state = value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns
        finally:
            os.close(descriptor)

    def owned(self, *, capture=False):
        return self._scope_operation(lambda: self._owned(capture=capture))

    def _owned(self, *, capture=False):
        value = self.stage.lstat()
        if not stat.S_ISREG(value.st_mode) or (value.st_dev, value.st_ino) != self.stage_inode:
            raise self.entry.refuse(invalid_argument("Asset staging entry changed; cleanup/publication refused."))
        if not capture and self.stage_state is not None and _file_identity(value) != self.stage_state:
            raise self.entry.refuse(invalid_argument("Owned artifact state changed after its captured native output."))
        return value

    def capture_native_write(self):
        value = self.owned(capture=True)
        self.stage_state = value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    def hash(self, path, *, authorize=True):
        return self._scope_operation(lambda: self._hash(path, authorize=authorize))

    def _hash(self, path, *, authorize=True):
        if authorize:
            self.check()
        else:
            self.entry.final()
        expected = self.owned()
        path_state = path.lstat()
        if not stat.S_ISREG(path_state.st_mode) or _file_identity(path_state) != _file_identity(expected):
            raise self.entry.refuse(invalid_argument("Asset verification path is not the unchanged owned regular file."))
        if not 0 < expected.st_size <= MAX_BYTES:
            raise invalid_argument("Native asset artifact is empty or exceeds the 512 MiB budget.")
        value = hashlib.sha256()
        with path.open("rb") as stream:
            if (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino) != self.stage_inode:
                raise self.entry.refuse(invalid_argument("Native asset artifact changed before reading."))
            while True:
                if authorize:
                    self.check()
                else:
                    self.entry.final()
                block = stream.read(READ_BYTES)
                if not block:
                    break
                value.update(block)
            actual = os.fstat(stream.fileno())
        if ((actual.st_size, actual.st_mtime_ns) != (expected.st_size, expected.st_mtime_ns)
                or _file_identity(self.owned()) != _file_identity(expected)
                or _file_identity(path.lstat()) != _file_identity(expected)):
            raise self.entry.refuse(invalid_argument("Native asset artifact changed during verification."))
        return value.hexdigest(), actual.st_size

    def seal(self):
        return self._scope_operation(self._seal)

    def _seal(self):
        self.write_check()
        self.owned()
        if set(path.name for path in self.directory.iterdir()) != {self.stage.name}:
            raise self.entry.refuse(BridgeError(ErrorCode.NOT_IMPLEMENTED,
                "Native exporter emitted unreviewed sidecar files; staging retained for inspection."))
        with self.stage.open("r+b") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != self.stage_inode:
                raise self.entry.refuse(invalid_argument("Asset staging changed before native-output inspection."))
            self.write_check()
            self.owned()
            if _file_identity(os.fstat(stream.fileno())) != self.stage_state:
                raise invalid_argument("Opened artifact changed after its captured native output.")
            self.entry.final()
            os.fsync(stream.fileno())
            header = stream.read(28)
            if self.format == "FBX" and not header.startswith(b"Kaydara FBX Binary  \x00\x1a\x00"):
                raise invalid_argument("Native exporter did not emit binary FBX.")
            if self.format == "GLB":
                if len(header) < 20 or header[:4] != b"glTF" or struct.unpack_from("<I", header, 4)[0] != 2 or struct.unpack_from("<I", header, 8)[0] != self.owned().st_size:
                    raise invalid_argument("Native exporter did not emit a complete GLB 2 artifact.")
                length, kind = struct.unpack_from("<II", header, 12)
                if kind != 0x4E4F534A or length > 4 * 1024 * 1024:
                    raise invalid_argument("GLB JSON manifest exceeds the reviewed budget.")
                stream.seek(20)
                manifest = json.loads(stream.read(length))
                if manifest.get("images") or manifest.get("materials") or any("uri" in item for item in manifest.get("buffers", [])):
                    _unsupported("Exported GLB contains unexpected material/image/external dependencies.")
        self.sha256, self.bytes = self.hash(self.stage)

    def publish(self):
        self.check()
        _absent(self.path)
        if self.hash(self.stage, authorize=False) != (self.sha256, self.bytes):
            raise self.entry.refuse(invalid_argument("Native asset bytes changed before publication."))
        assert self.source_check is not None
        self.source_check()
        self.entry.final()
        self.attempted = True
        os.link(self.stage, self.path, follow_symlinks=False)
        self.published = True
        if self.hash(self.path) != (self.sha256, self.bytes):
            raise self.entry.refuse(invalid_argument("Published native asset bytes changed."))
        self.verified = True

    def cleanup(self):
        try:
            if self.directory is not None:
                self.check(cleanup=True)
                assert self.source_check is not None
                self.source_check()
                if self.stage is not None:
                    value = self.owned()
                    if (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns) != self.stage_state:
                        raise self.entry.refuse(invalid_argument("Asset staging bytes changed; cleanup refused."))
                if set(path.name for path in self.directory.iterdir()) != ({self.stage.name} if self.stage is not None else set()):
                    raise self.entry.refuse(invalid_argument("Unexpected entries in asset staging; no recursive cleanup is allowed."))
                if self.stage is not None:
                    self.entry.final()
                    self.stage.unlink()
                if self.pins is not None:
                    self.pins.close()
                    self.pins = None
                self.check(cleanup=True)
                self.source_check()
                if any(self.directory.iterdir()):
                    raise self.entry.refuse(invalid_argument("Owned staging acquired a new member before removal."))
                self.entry.final()
                self.directory.rmdir()
                self.cleanup_status = "removed"
        except Exception as error:
            self.entry.refuse(error)
            self.cleanup_status = "retained"
            LOGGER.exception("Owned asset staging retained; inspect exact external effects")
        finally:
            if self.pins is not None:
                self.pins.close()

    def evidence(self):
        return {"filepath": str(self.path), "file_published": self.published,
            "publication_attempted": self.attempted,
            "publication_outcome_unknown": self.attempted and not self.published,
            "file_sha256": self.sha256, "file_bytes": self.bytes,
            "published_bytes_verified": self.verified, "staging_cleanup": self.cleanup_status,
            "retained_staging_path": str(self.directory) if self.directory is not None and self.cleanup_status != "removed" else None,
            "native_undo_removes_external_file": False, "crash_durability_verified": False,
            "windows_directory_pin_acceptance": "NOT_ASSESSED"}


def _context(bpy):
    layer = bpy.context.view_layer
    active = layer.objects.active
    return {"scene_identity": _identity(bpy.context.scene), "view_layer_identity": _pointer(layer),
        "selection": [(_identity(obj), bool(obj.select_get(view_layer=layer))) for obj in layer.objects],
        "active": _identity(active) if active is not None else None,
        "mode": bpy.context.mode, "frame": bpy.context.scene.frame_current,
        "subframe": float(bpy.context.scene.frame_subframe),
        "objects": [(obj.name, _identity(obj), _identity(obj.data) if obj.data else None,
                     _matrix(obj.matrix_world), bool(obj.hide_render), bool(obj.hide_viewport), bool(obj.hide_get()))
                    for obj in bpy.data.objects]}


class _NativeContext:
    """Model only our selection/active prefix; never adopt exporter output."""

    def __init__(self, entry, bpy, source_check, original, capture_output, artifact_check):
        self.entry, self.bpy, self.source_check = entry, bpy, source_check
        self.capture_output = capture_output
        self.artifact_check = artifact_check
        self.original, self.expected = deepcopy(original), deepcopy(original)
        self.objects = tuple(bpy.context.view_layer.objects)
        self.layer = bpy.context.view_layer
        self.layer_objects = self.layer.objects
        self.active = bpy.context.view_layer.objects.active
        self.started = False
        self.restored = False

    def gate(self, *, native_write=False):
        try:
            self.entry.authorize(writing=True)
            self.source_check()
            if _context(self.bpy) != self.expected:
                raise invalid_argument("Asset context changed outside its owned selection prefix; no restoration is authorized.")
            if native_write:
                self.artifact_check()
            self.entry.final()
        except Exception as error:
            refused = self.entry.refuse(error)
            if refused is error:
                raise
            raise refused from error

    def select(self, obj, value):
        token = _identity(obj)
        after = [(identity, value if identity == token else selected)
                 for identity, selected in self.expected["selection"]]
        self.gate()
        self.expected["selection"] = after
        self.started = True
        obj.select_set(value, view_layer=self.layer)

    def set_active(self, obj):
        token = None if obj is None else _identity(obj)
        self.gate()
        self.expected["active"] = token
        self.started = True
        self.layer_objects.active = obj

    def restore(self):
        # Native exporters must return to the expected frame/source themselves.
        # Unexpected frame/geometry/selection changes never grant a reset write.
        self.gate()
        wanted = dict(self.original["selection"])
        for obj in self.objects:
            token = _identity(obj)
            if dict(self.expected["selection"])[token] != wanted[token]:
                self.select(obj, wanted[token])
        if self.expected["active"] != self.original["active"]:
            self.set_active(self.active)
        self.gate()
        self.restored = self.expected == self.original


def _native(bpy, objects, path, format, include, *, transaction):
    try:
        for obj in transaction.objects:
            transaction.select(obj, False)
        for obj in objects:
            transaction.select(obj, True)
        transaction.set_active(objects[0])
        transaction.gate(native_write=True)
        if format == "GLB":
            result = bpy.ops.export_scene.gltf(filepath=str(path), check_existing=False,
                export_format="GLB", use_selection=True, export_materials="NONE", export_apply=False,
                export_animations=include, export_animation_mode="SCENE", export_skins=True,
                export_cameras=False, export_lights=False, export_extras=False)
        else:
            result = bpy.ops.export_scene.fbx(filepath=str(path), check_existing=False,
                use_selection=True, object_types={"MESH", "ARMATURE", "EMPTY"}, add_leaf_bones=False,
                bake_anim=include, bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False,
                bake_anim_force_startend_keying=True, path_mode="STRIP", use_mesh_modifiers=False,
                use_custom_props=False)
        if result != {"FINISHED"}:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Native asset exporter did not finish.")
        # Anchor the native artifact before restoration can invoke a provider.
        transaction.capture_output()
    finally:
        transaction.restore()


def export_asset(context: ToolContext, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_names", "format", "include_animation", "filepath",
                                  "expected_fingerprint", "accepted_losses"})
    entry = _Entry(context, "asset.export", params)
    entry.authorize(writing=True)
    parameters = entry.params
    bpy, objects, preview = _scope(context, parameters, entry=entry, authorize=False)
    entry.final()
    expected = parameters.get("expected_fingerprint")
    if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected) or expected != preview["fingerprint"]:
        raise invalid_argument("Export requires the exact current preview fingerprint; reinspect stale scope.")
    if parameters.get("accepted_losses") != preview["required_accepted_losses"]:
        raise invalid_argument("accepted_losses must match the reviewed preview's required format limits exactly.")
    entry.authorize(writing=True)
    staging = _Staging(entry, parameters.get("filepath"), preview["format"])
    _absent(staging.path)
    original = _context(bpy)
    def source_check():
        try:
            if _scope(context, parameters, entry=entry, authorize=False)[2]["fingerprint"] != expected:
                raise invalid_argument("Asset source changed after its accepted preview; no further write is authorized.")
        except Exception as error:
            refused = entry.refuse(error)
            if refused is error:
                raise
            raise refused from error
    def complete_check():
        source_check()
        try:
            if _context(bpy) != original:
                raise invalid_argument("Asset context did not return to its original measured state.")
        except Exception as error:
            refused = entry.refuse(error)
            if refused is error:
                raise
            raise refused from error
    staging.source_check = complete_check
    transaction = _NativeContext(entry, bpy, source_check, original,
                                 staging.capture_native_write, staging.native_write_check)
    failure = None
    preserved = False
    try:
        staging.open()
        entry.authorize(writing=True)
        complete_check()
        entry.final()
        _native(bpy, objects, staging.stage, preview["format"], preview["include_animation"], transaction=transaction)
        entry.authorize(writing=True)
        complete_check()
        entry.final()
        preserved = True
        staging.seal()
        staging.publish()
    except Exception as exc:
        failure = exc
    finally:
        staging.cleanup()
    try:
        entry.authorize(writing=True)
        complete_check()
        entry.final()
        preserved = True
    except Exception as error:
        preserved = False
        if failure is None:
            failure = error
    effects = staging.evidence()
    if failure is not None:
        raise BridgeError(failure.code if isinstance(failure, BridgeError) else ErrorCode.OPERATION_FAILED,
            "Asset export did not complete; inspect source and exact external effects before retrying.",
            {"external_effects": effects, "affected_objects": preview["object_names"],
             "execution_started": staging.directory is not None, "source_and_context_preserved": preserved,
             "native_context_restored": transaction.restored,
             "possible_mutation": (not preserved or effects["file_published"]
                                   or effects["publication_outcome_unknown"] or effects["staging_cleanup"] == "retained")}) from failure
    return {"exported": True, "format": preview["format"], "affected_objects": preview["object_names"],
        "preview_fingerprint": expected, "accepted_losses": preview["required_accepted_losses"],
        "source_and_context_preserved": preserved, "external_effects": effects,
        "native_context_restored": transaction.restored,
        "project_saved": False, "native_roundtrip_verified": False,
        "native_export_interruptible": False,
        "verification": "Complete artifact bytes hashed and source/context preserved. Fresh-process reimport and downstream material/animation/appearance acceptance remain separate evidence."}


def register_tools(registry: ToolRegistry) -> None:
    registry.register("asset.export_preview", export_preview, toolset="asset_delivery",
        permissions=(Permission.INSPECT_SCENE,), description="Preview explicit local material-free mesh/rig scope and required GLB/FBX format-loss acknowledgements; no writes.")
    registry.register("asset.export", export_asset, toolset="asset_delivery", modifies=True,
        permissions=REQUIRED, automatic_checkpoint=False, batchable=False,
        description="Export a current fingerprinted static/skinned triangle asset to one approved unused GLB/FBX path; preserve scene/context and retain external effects independently of native undo.")
