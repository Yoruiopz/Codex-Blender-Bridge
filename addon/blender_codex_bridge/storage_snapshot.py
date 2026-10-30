# SPDX-License-Identifier: GPL-3.0-or-later
"""Private owned native serialization and detached ViewLayer storage evidence.

No public tool or job invokes this prerequisite yet. The future caller must pair
the fresh projection and complete structural guard with its native mutation in
one reviewed, non-yielding turn. Identity checks alone do not prove preservation
of all authored values. The synchronous writer is not preemptible or memory
capped; parser bounds must never be presented as native serialization bounds.
"""
from __future__ import annotations

import math
import os
import re
import stat
import sys
import threading
import time
from dataclasses import dataclass
from inspect import CO_ASYNC_GENERATOR, CO_COROUTINE, CO_GENERATOR, getattr_static
from pathlib import Path
from types import (
    BuiltinFunctionType,
    FunctionType,
    GetSetDescriptorType,
    MemberDescriptorType,
    MethodDescriptorType,
    ModuleType,
)

from .blend_storage_sdna import CYCLES_502_NAMES, CYCLES_NAMES, inspect_view_layer_storage
from .errors import BridgeError, ErrorCode
from .permissions import Permission
from .scene_job_reservations import TURN_METHOD
from .storage_snapshot_effects import (
    _CELL_KIND,
    _CELL_SLOTS,
    SnapshotJournal,
    SnapshotOwner,
    cell_slots,
    cleanup_receipt,
    cleanup_state,
    mint_cleanup_owner,
)
from .tool_registry import check_final_mutation
from .tools import _cloth_scene_consumers as roles
from .tools import _simulation_runtime as runtime

REQUIRED = (Permission.INSPECT_SCENE, Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES)
MIN_MEMORY, MIN_DISK = 8 * 1024**3, 2 * 1024**3
MAX_IDS = 128
FAMILIES = (
    ("scenes", "Scene"), ("collections", "Collection"), ("objects", "Object"), ("meshes", "Mesh"),
    ("materials", "Material"), ("worlds", "World"), ("images", "Image"), ("cameras", "Camera"),
    ("lights", "Light"), ("armatures", "Armature"), ("actions", "Action"), ("node_groups", "NodeTree"),
    ("texts", "Text"), ("screens", "Screen"), ("workspaces", "WorkSpace"), ("window_managers", "WindowManager"),
)
_METHODS = frozenset({"simulation.cache_preview", "simulation.cache_context_prepare",
                      "simulation.cache_job_start", TURN_METHOD})
_ASYNC_FLAGS = CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR
_HEADER_FIELDS = ("name", "type", "subtype", "flag", "len", "totallen")


def refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "The private stored-settings observation is not qualified.",
                       {"reason": reason, "verification_required": True, "runtime_getter_invoked": False,
                        "durable_backup_qualified": False, "full_source_preservation_qualified": False})


def _resource_require(condition, reason):
    if not condition:
        raise refused(reason)


def _resource_text(path, maximum):
    with open(path, "rb") as stream:
        raw = stream.read(maximum + 1)
    _resource_require(0 < len(raw) <= maximum, "RESOURCE_MEASUREMENT_UNAVAILABLE")
    return raw.decode("utf-8", "strict")


def _resource_integer(value):
    _resource_require(type(value) is str and re.fullmatch(r"[0-9]{1,19}", value) is not None,
            "RESOURCE_MEASUREMENT_UNAVAILABLE")
    parsed = int(value)
    _resource_require(0 <= parsed <= 2**63 - 1, "RESOURCE_MEASUREMENT_UNAVAILABLE")
    return parsed


def _visible_cgroup_paths(cgroup, mountinfo):
    rows = [line[3:] for line in cgroup.splitlines() if line.startswith("0::")]
    _resource_require(len(rows) == 1, "RESOURCE_CGROUP_UNAVAILABLE")
    group = rows[0]
    _resource_require(group.startswith("/") and not group.startswith("//") and "\\" not in group
            and len(group.encode("utf-8")) <= 4096
            and not any(ord(char) < 32 or ord(char) == 127 for char in group)
            and not any(part in {".", ".."} for part in group.split("/")), "RESOURCE_CGROUP_UNAVAILABLE")
    mounts = []
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        fields, filesystem = before.split(), after.split()
        if (separator and filesystem and filesystem[0] == "cgroup2" and len(fields) >= 6
                and fields[4] == "/sys/fs/cgroup"):
            mounts.append(fields[3])
    _resource_require(len(mounts) == 1, "RESOURCE_CGROUP_UNAVAILABLE")
    root = mounts[0]
    _resource_require(root.startswith("/") and not root.startswith("//") and "\\" not in root
            and len(root.encode("utf-8")) <= 4096
            and not any(ord(char) < 32 or ord(char) == 127 for char in root)
            and (root == "/.." or not any(part in {".", ".."} for part in root.split("/"))),
            "RESOURCE_CGROUP_UNAVAILABLE")
    # A cgroup namespace may expose its root as / even when mountinfo retains
    # /.. from the supervising namespace. No path outside the visible mount is
    # queried or treated as a known ancestor limit.
    if group == "/" or root in {"/", "/.."}:
        relative = group.lstrip("/")
    else:
        _resource_require(group == root or group.startswith(root.rstrip("/") + "/"), "RESOURCE_CGROUP_UNAVAILABLE")
        relative = group[len(root):].lstrip("/")
    base = Path("/sys/fs/cgroup")
    current, paths = base / relative, []
    while True:
        _resource_require(len(paths) < 128 and (current == base or base in current.parents), "RESOURCE_CGROUP_UNAVAILABLE")
        paths.append(current)
        if current == base:
            return tuple(paths)
        current = current.parent


def available_memory_facts():
    """Sample host and every visible v2 ancestor; this reserves no memory."""
    _resource_require(sys.platform == "linux", "LARGE_IMAGE_RESOURCE_PLATFORM_UNQUALIFIED")
    try:
        meminfo = _resource_text("/proc/meminfo", 16384)
        rows = [line.split() for line in meminfo.splitlines() if line.startswith("MemAvailable:")]
        _resource_require(len(rows) == 1 and len(rows[0]) == 3 and rows[0][2] == "kB", "RESOURCE_MEASUREMENT_UNAVAILABLE")
        host = _resource_integer(rows[0][1]) * 1024
        _resource_require(host <= 2**63 - 1, "RESOURCE_MEASUREMENT_UNAVAILABLE")
        paths = _visible_cgroup_paths(_resource_text("/proc/self/cgroup", 65536),
                                     _resource_text("/proc/self/mountinfo", 1024 * 1024))
        headrooms = []
        for path in paths:
            maximum = _resource_text(path / "memory.max", 64).strip()
            current = _resource_integer(_resource_text(path / "memory.current", 64).strip())
            if maximum != "max":
                headrooms.append(max(0, _resource_integer(maximum) - current))
        visible = min(headrooms) if headrooms else None
        return {"available_memory_bytes": min(host, visible) if visible is not None else host,
                "host_available_memory_bytes": host, "visible_cgroup_headroom_bytes": visible,
                "visible_cgroup_levels": len(paths)}
    except (OSError, UnicodeError, ValueError) as cause:
        raise refused("RESOURCE_MEASUREMENT_UNAVAILABLE") from cause


def _text(value, maximum=4096):
    if (type(value) is not str or not value or "\0" in value
            or len(value.encode("utf-8")) > maximum):
        raise refused("SNAPSHOT_TEXT_SHAPE")
    return value


def _field(bpy, owner, kind, name, category, *, target=None, readonly=True):
    cls = roles._particle_class(bpy, kind)
    metadata = getattr_static(cls, "bl_rna", None)
    # StructRNA is the C declaration name, not a bpy.types export. Bind the
    # actual metadata wrapper to Blender's qualified canonical Struct class.
    metadata_kind = type(metadata)
    if (metadata_kind is not roles._particle_class(bpy, "Struct")
            or getattr_static(owner, "bl_rna", None) is not metadata):
        raise refused("SNAPSHOT_RNA_METADATA_SHADOW")
    for label in ("identifier", "properties"):
        descriptor = getattr_static(metadata_kind, label, None)
        if descriptor is not None and type(descriptor) not in (GetSetDescriptorType, MemberDescriptorType):
            raise refused("SNAPSHOT_RNA_METADATA_SHADOW")
    if metadata.identifier != kind:
        raise refused("SNAPSHOT_RNA_METADATA_IDENTITY")
    roles._particle_field(bpy, owner, kind, name, category, target=target, readonly=readonly)
    return getattr(owner, name)


def _pointer(bpy, owner, kind):
    cls = roles._particle_class(bpy, kind)
    base = bpy.types.bpy_struct
    method = vars(base).get("as_pointer")
    if (type(owner) is not cls or type(method) is not MethodDescriptorType
            or method.__objclass__ is not base or getattr_static(cls, "as_pointer", None) is not method):
        raise refused("SNAPSHOT_NATIVE_POINTER_CHANGED")
    value = method(owner)
    if type(value) is not int or value <= 0:
        raise refused("SNAPSHOT_NATIVE_POINTER_SHAPE")
    return value


def _id(bpy, owner):
    # Native collection refinements include PointLight and ShaderNodeTree.
    # Obtain their actual class name without touching an unqualified owner.
    kind = type.__dict__["__name__"].__get__(type(owner))
    pointer = _pointer(bpy, owner, kind)
    uid = _field(bpy, owner, kind, "session_uid", "INT")
    name = _field(bpy, owner, kind, "name", "STRING", readonly=False)
    users = _field(bpy, owner, kind, "users", "INT")
    fake = _field(bpy, owner, kind, "use_fake_user", "BOOLEAN", readonly=False)
    if (type(uid) is not int or uid <= 0 or type(users) is not int or users < 0 or type(fake) is not bool):
        raise refused("SNAPSHOT_ID_SHAPE")
    return pointer, uid, _text(name, 256), users, fake


class _NativeSource:
    """Selected canonical C fields and the retained native library writer."""
    __slots__ = ("baseline", "bpy", "build", "libraries", "main", "scenes", "writer")

    def __init__(self, bpy, scenes):
        if type(bpy) is not ModuleType:
            raise refused("SNAPSHOT_CANONICAL_BLENDER_MODULE_REQUIRED")
        from . import runtime as bridge_runtime
        if bpy is not vars(bridge_runtime).get("bpy"):
            raise refused("SNAPSHOT_CANONICAL_BLENDER_MODULE_REQUIRED")
        if type(scenes) is not tuple or len(scenes) != 2 or scenes[0] is scenes[1]:
            raise refused("SNAPSHOT_EXACT_TWO_SCENES_REQUIRED")
        self.bpy, self.scenes = bpy, scenes
        self.build = runtime.profile(bpy)
        self.main = bpy.data
        libraries = _field(bpy, self.main, "BlendData", "libraries", "COLLECTION", target="Library")
        library_kind = roles._particle_class(bpy, "BlendDataLibraries")
        native_method = getattr_static(library_kind, "write", None)
        if type(native_method) is not MethodDescriptorType or native_method.__objclass__ is not library_kind:
            raise refused("SNAPSHOT_NATIVE_WRITER_SHADOW")
        # This collection's reviewed native getattr creates a PyCFunction bound
        # to the held collection. Python-added shadow descriptors are refused.
        if getattr_static(type(libraries), "write", None) is not None:
            raise refused("SNAPSHOT_NATIVE_WRITER_SHADOW")
        writer = libraries.write
        if (type(writer) is not BuiltinFunctionType or writer.__name__ != "write"
                or writer.__self__ is not libraries):
            raise refused("SNAPSHOT_NATIVE_WRITER_CHANGED")
        self.libraries, self.writer = libraries, writer
        self.baseline = self.identity()

    def identity(self):
        bpy = self.bpy
        if bpy.data is not self.main or runtime.profile(bpy) != self.build:
            raise refused("SNAPSHOT_MAIN_OR_BUILD_CHANGED")
        main = _pointer(bpy, self.main, "BlendData")
        filepath = _field(bpy, self.main, "BlendData", "filepath", "STRING")
        dirty = _field(bpy, self.main, "BlendData", "is_dirty", "BOOLEAN")
        if type(filepath) is not str or type(dirty) is not bool:
            raise refused("SNAPSHOT_MAIN_FIELDS_CHANGED")
        inventory, total = [], 0
        for family, target in FAMILIES:
            values = _field(bpy, self.main, "BlendData", family, "COLLECTION", target=target)
            size = len(values)
            if type(size) is not int or size < 0 or total + size > MAX_IDS:
                raise refused("SNAPSHOT_MAIN_INVENTORY_BUDGET")
            rows = tuple(_id(bpy, owner) for owner in values)
            if len(rows) != size:
                raise refused("SNAPSHOT_MAIN_INVENTORY_CHANGED")
            inventory.append((family, tuple(sorted(rows))))
            total += size
        if set(owner[0] for owner in inventory[0][1]) != set(_pointer(bpy, scene, "Scene") for scene in self.scenes):
            raise refused("SNAPSHOT_SCENE_SET_CHANGED")
        targets = []
        for scene in self.scenes:
            identity = _id(bpy, scene)
            layers = _field(bpy, scene, "Scene", "view_layers", "COLLECTION", target="ViewLayer")
            if len(layers) != 1:
                raise refused("SNAPSHOT_ONE_LAYER_PER_SCENE_REQUIRED")
            layer = layers[0]
            layer_name = _field(bpy, layer, "ViewLayer", "name", "STRING", readonly=False)
            layer_pointer = _pointer(bpy, layer, "ViewLayer")
            frame = _field(bpy, scene, "Scene", "frame_current", "INT", readonly=False)
            subframe = _field(bpy, scene, "Scene", "frame_subframe", "FLOAT", readonly=False)
            if type(frame) is not int or type(subframe) is not float or not math.isfinite(subframe):
                raise refused("SNAPSHOT_CLOCK_SHAPE")
            targets.append((identity[:3], (layer_pointer, _text(layer_name, 256)), frame, subframe.hex()))
        if getattr_static(type(self.libraries), "write", None) is not None:
            raise refused("SNAPSHOT_NATIVE_WRITER_SHADOW")
        return (self.build, main, filepath, dirty, tuple(inventory), tuple(targets))

    def check(self):
        if self.identity() != self.baseline:
            raise refused("SNAPSHOT_SOURCE_IDENTITY_CHANGED")


def _header(raw):
    if type(raw) is not dict or any(type(key) is not str for key in raw) or set(raw) != set(_HEADER_FIELDS):
        raise refused("SNAPSHOT_RAW_HEADER_SHAPE")
    if (type(raw["name"]) is not str or len(raw["name"]) > 1024
            or any(type(raw[name]) is not int for name in _HEADER_FIELDS[1:])):
        raise refused("SNAPSHOT_RAW_HEADER_SHAPE")
    return tuple(raw[name] for name in _HEADER_FIELDS)


@dataclass(frozen=True, slots=True)
class StorageProjection:
    scene: tuple
    layer: tuple
    state: str
    storage: str
    root_present: bool
    root: tuple | None
    group: tuple | None
    children: tuple
    storage_fingerprint: str


def _projection(proof, target, names):
    if (type(proof) is not dict or any(type(key) is not str for key in proof)
            or type(proof.get("schema")) is not str
            or proof["schema"] != "blend_view_layer_raw_storage_v1"):
        raise refused("SNAPSHOT_RAW_PROOF_SHAPE")
    storage = proof["storage"]
    if (type(storage) is not dict or any(type(key) is not str for key in storage)
            or not {"root_header", "property", "children"}.issubset(storage)
            or any(type(storage.get(name)) is not str for name in
                   ("scene_name", "view_layer_name", "property_name", "storage", "state"))
            or storage.get("scene_name") != target[0][2]
            or storage.get("view_layer_name") != target[1][1]
            or storage.get("property_name") != "cycles" or storage.get("storage") not in {"USER", "SYSTEM"}
            or storage.get("state") not in {"ABSENT", "GROUP"} or type(storage.get("root_present")) is not bool
            or type(storage.get("children")) is not list or len(storage["children"]) > len(names)):
        raise refused("SNAPSHOT_RAW_PROOF_SHAPE")
    fingerprint = proof.get("storage_fingerprint")
    if (type(fingerprint) is not str or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)):
        raise refused("SNAPSHOT_RAW_DIGEST_SHAPE")
    children = []
    for row in storage["children"]:
        if (type(row) is not dict or any(type(key) is not str for key in row)
                or set(row) != {*_HEADER_FIELDS, "value", "value2"}
                or type(row["value"]) is not int or type(row["value2"]) is not int):
            raise refused("SNAPSHOT_RAW_CHILD_SHAPE")
        header = _header({name: row[name] for name in _HEADER_FIELDS})
        if (header[0] not in names or header[1] not in (1, 10)
                or (header[1] == 10 and row["value"] not in (0, 1))):
            raise refused("SNAPSHOT_RAW_CHILD_SHAPE")
        children.append((*header, row["value"], row["value2"]))
    if len({row[0] for row in children}) != len(children):
        raise refused("SNAPSHOT_RAW_CHILD_DUPLICATE")
    if ((storage["state"] == "ABSENT" and (storage["property"] is not None or children))
            or (storage["state"] == "GROUP" and (not storage["root_present"] or storage["property"] is None))
            or (not storage["root_present"] and storage["root_header"] is not None)):
        raise refused("SNAPSHOT_RAW_STATE_SHAPE")
    return StorageProjection(target[0], target[1], storage["state"], storage["storage"], storage["root_present"],
                             None if storage["root_header"] is None else _header(storage["root_header"]),
                             None if storage["property"] is None else _header(storage["property"]),
                             tuple(children), fingerprint)


def _file_identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _sample_resources(root_fd):
    memory = available_memory_facts()
    disk = os.fstatvfs(root_fd)
    if (type(memory) is not dict or type(memory.get("available_memory_bytes")) is not int
            or not 0 <= memory["available_memory_bytes"] <= 2**63 - 1
            or type(disk.f_bavail) is not int or type(disk.f_frsize) is not int):
        raise refused("SNAPSHOT_RESOURCE_MEASUREMENT_UNQUALIFIED")
    available = disk.f_bavail * disk.f_frsize
    if not 0 <= available <= 2**63 - 1:
        raise refused("SNAPSHOT_RESOURCE_MEASUREMENT_UNQUALIFIED")
    return memory["available_memory_bytes"], available


def _live_frame(anchor):
    frame = sys._getframe(1)
    while frame is not None:
        if frame is anchor:
            return True
        frame = frame.f_back
    return False


@dataclass(frozen=True, slots=True, eq=False)
class SnapshotWitness:
    operation: object
    projections: tuple
    binding: tuple
    used: bool = False

    def consume(self, context, bpy, scenes):
        """Consume in the same ordinary call activation; never refresh/adopt."""
        operation = _WITNESS_OPERATION.__get__(self, _WITNESS_KIND)
        source = _OPERATION_SOURCE.__get__(operation, _OPERATION_KIND)
        verify, code, namespace, defaults, keywords, _saved, closures = tuple.__getitem__(source, 7)
        kind, function_kind = type, FunctionType
        failure = refused("SNAPSHOT_SOURCE_BOOTSTRAP_CHANGED")

        def guard():
            if (kind(verify) is not function_kind or verify.__code__ is not code or verify.__globals__ is not namespace
                    or defaults is not None or keywords is not None or closures
                    or verify.__defaults__ is not None or verify.__kwdefaults__ is not None or verify.__closure__ is not None):
                raise failure
            verify(source, context)

        guard()
        if type(self.used) is not bool or self.used:
            raise refused("SNAPSHOT_ONE_USE_OR_TURN_CHANGED")
        _WITNESS_USED.__set__(self, True)
        if type(self.binding) is not tuple or len(self.binding) != 23:
            raise refused("SNAPSHOT_WITNESS_BINDING_SHAPE")
        for row in self.binding:
            if type(row) is not tuple or len(row) != 4:
                raise refused("SNAPSHOT_WITNESS_BINDING_SHAPE")
            owner, cls, slot, expected = row
            if (type(owner) is not cls or type(slot) is not MemberDescriptorType or slot.__objclass__ is not cls
                    or slot.__get__(owner, cls) is not expected):
                raise refused("SNAPSHOT_WITNESS_OWNER_CHANGED")
        if (context is not operation.context or bpy is not operation.bpy
                or type(scenes) is not tuple or len(scenes) != 2
                or any(a is not b for a, b in zip(scenes, operation.scenes, strict=True))
                or not _live_frame(operation.anchor)):
            raise refused("SNAPSHOT_ONE_USE_OR_TURN_CHANGED")
        retired = _CELL_RETIRED.__get__(operation.cell, _CELL_KIND)
        if type(retired) is not bool or retired:
            raise refused("SNAPSHOT_WITNESS_RETIRED")
        operation._control()
        operation.native.check()
        guard()
        operation._control()
        operation._mark("consumed", True)
        return self.projections


class SnapshotOperation:
    """One explicit authorized native interval, never a generic read guard."""
    __slots__ = ("anchor", "bpy", "cell", "cleanup_owner", "context", "journal", "native", "root", "scenes", "slots", "source", "started")

    def __init__(self, context, bpy, scenes, root: str, journal: SnapshotJournal):
        from .tools._cloth_cache_source import capture_cloth_sources
        self.source = capture_cloth_sources(context)
        self.context, self.bpy, self.scenes = context, bpy, scenes
        self.root = _text(root)
        if not os.path.isabs(root) or os.path.normpath(root) != root or type(journal) is not SnapshotJournal:
            raise refused("SNAPSHOT_OWNED_ROOT_REQUIRED")
        journal.snapshot()
        self.journal, self.cell, self.slots = journal, None, ()
        self.cleanup_owner = None
        self.started, self.anchor, self.native = False, None, None

    def _control(self):
        method = self.context.checkpoint_method
        if type(method) is not str or method not in _METHODS or threading.current_thread() is not threading.main_thread():
            raise refused("SNAPSHOT_CANONICAL_MAIN_THREAD_ENTRY_REQUIRED")
        check_final_mutation(self.context, method)
        # This writer is a filesystem mutation even if its older caller's
        # metadata still describes a nonmodifying scene-inspection tool.
        flags = self.context.state.snapshot()
        if (type(flags) is not dict or type(flags.get("emergency_stopped")) is not bool
                or type(flags.get("paused")) is not bool):
            raise refused("SNAPSHOT_CONTROL_FLAG_SHAPE")
        if flags["emergency_stopped"]:
            raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Inspection serialization stopped before its next write.")
        if flags["paused"]:
            raise BridgeError(ErrorCode.AGENT_PAUSED, "Inspection serialization paused before its next write.")

    def _mark(self, name, value):
        # Retained C slots allow return/stop facts after source-class replacement
        # without invoking a replacement property on a stopped object.
        for field, slot in self.slots:
            if field == name:
                slot.__set__(self.cell, value)
                return
        raise refused("SNAPSHOT_LITERAL_CELL_UNAVAILABLE")

    def _authorize(self, guard):
        guard()
        context, control = self.context, SnapshotOperation._control
        control(self)
        context.require(*REQUIRED)
        guard()  # First action after the provider, before dynamic dispatch.
        control(self)

    def run(self) -> SnapshotWitness:
        if self.started:
            raise refused("SNAPSHOT_OPERATION_REUSED")
        self.started = True
        self.anchor = sys._getframe(1)
        if self.anchor.f_code.co_flags & _ASYNC_FLAGS:
            raise refused("SNAPSHOT_NONYIELDING_CALLER_REQUIRED")
        root_fd = directory_fd = cell = None
        close = os.close
        source, context = self.source, self.context
        fact = tuple.__getitem__(source, 7)
        verify, code, namespace, defaults, keywords, _saved, closures = fact
        kind, function_kind = type, FunctionType
        if defaults is not None or keywords is not None or closures:
            raise refused("SNAPSHOT_SOURCE_BOOTSTRAP_SHAPE")
        failure = refused("SNAPSHOT_SOURCE_BOOTSTRAP_CHANGED")
        operation_kind = SnapshotOperation
        operation_slots = {name: vars(operation_kind)[name] for name in operation_kind.__slots__}
        fixed = tuple((operation_slots[name], operation_slots[name].__get__(self, operation_kind))
                      for name in ("source", "context", "bpy", "scenes", "root", "journal", "anchor"))
        native = native_facts = None
        native_kind = _NativeSource
        native_slots = tuple(vars(native_kind)[name] for name in native_kind.__slots__)
        journal_kind, journal = SnapshotJournal, self.journal
        journal_slot = vars(journal_kind)["rows"]
        journal_rows = journal_slot.__get__(journal, journal_kind)
        slot_pairs = ()
        owned_facts = ()
        cleanup_owner = cleanup_cell = cleanup_cell_slots = owner_rows = None

        def guard():
            # This local function and its held primitive/function facts are not
            # fetched through a provider-modifiable instance or module helper.
            if (kind(verify) is not function_kind or verify.__code__ is not code
                    or verify.__globals__ is not namespace or verify.__defaults__ is not None
                    or verify.__kwdefaults__ is not None or verify.__closure__ is not None):
                raise failure
            verify(source, context)
            if journal_slot.__get__(journal, journal_kind) is not journal_rows:
                raise failure
            for slot, expected in fixed:
                if slot.__get__(self, operation_kind) is not expected:
                    raise failure
            if native is not None:
                if operation_slots["native"].__get__(self, operation_kind) is not native:
                    raise failure
                for slot, expected in native_facts:
                    if slot.__get__(native, native_kind) is not expected:
                        raise failure
            if cell is not None and (operation_slots["cell"].__get__(self, operation_kind) is not cell
                                     or operation_slots["slots"].__get__(self, operation_kind) is not slot_pairs):
                raise failure
            if operation_slots["cleanup_owner"].__get__(self, operation_kind) is not cleanup_owner:
                raise failure
            if cleanup_cell is not None:
                actual_rows, actual_state, actual_slots = cleanup_state(journal, cell)
                if (actual_rows is not owner_rows or actual_state is not cleanup_cell
                        or actual_slots is not cleanup_cell_slots
                        or dict(cleanup_cell_slots)["owner"].__get__(cleanup_cell, type(cleanup_cell)) is not cleanup_owner):
                    raise failure
            for slot, expected in owned_facts:
                if slot.__get__(cell, slot.__objclass__) is not expected:
                    raise failure

        stopped_slot = failed_slot = None
        try:
            guard()
            self._authorize(guard)
            self.native = native = _NativeSource(self.bpy, self.scenes)
            native_facts = tuple((slot, slot.__get__(native, native_kind)) for slot in native_slots)
            guard()
            self._control()
            root_info = os.lstat(self.root)
            if (not stat.S_ISDIR(root_info.st_mode) or stat.S_IMODE(root_info.st_mode) != 0o700
                    or root_info.st_uid != os.geteuid() or os.path.realpath(self.root) != self.root):
                raise refused("SNAPSHOT_PRIVATE_ROOT_REQUIRED")
            root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            root_identity = root_info.st_dev, root_info.st_ino
            if (os.fstat(root_fd).st_dev, os.fstat(root_fd).st_ino) != root_identity:
                raise refused("SNAPSHOT_ROOT_CHANGED")
            memory, disk = _sample_resources(root_fd)
            if memory < MIN_MEMORY or disk < MIN_DISK:
                raise refused("SNAPSHOT_RESOURCE_FLOOR")
            leaf = "bcb-storage-" + os.urandom(16).hex()
            directory = os.path.join(self.root, leaf)
            filepath = os.path.join(directory, "snapshot.blend")
            self.cell = cell = self.journal.reserve(self.root, directory, filepath, root_identity)
            self.slots = slot_pairs = cell_slots(cell)
            slots = dict(self.slots)
            stopped_slot, failed_slot = slots["stopped"], slots["failed"]
            returned_slot, seconds_slot = slots["native_returned"], slots["native_seconds"]
            self._control()
            self._mark("directory_entered", True)
            os.mkdir(leaf, 0o700, dir_fd=root_fd)
            self._mark("directory_returned", True)
            directory_fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            info = os.fstat(directory_fd)
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or os.listdir(directory_fd):
                raise refused("SNAPSHOT_CHILD_DIRECTORY_CHANGED")
            self._mark("directory_identity", (info.st_dev, info.st_ino))
            cleanup_owner = mint_cleanup_owner(journal, cell, self.root, leaf,
                                               _directory_cleanup_binding(root_info),
                                               _directory_cleanup_binding(info))
            self.cleanup_owner = cleanup_owner
            owner_rows, cleanup_cell, cleanup_cell_slots = cleanup_state(journal, cell)
            owned_facts = tuple((slots[name], slots[name].__get__(cell, slots[name].__objclass__))
                                for name in ("root", "directory", "filepath", "root_identity", "directory_identity"))
            self._authorize(guard)  # Actual authoritative grant immediately before C write.
            self.native.check()
            guard()
            self._control()
            if (os.lstat(self.root).st_dev, os.lstat(self.root).st_ino) != root_identity:
                raise refused("SNAPSHOT_ROOT_CHANGED")
            actual = os.stat(leaf, dir_fd=root_fd, follow_symlinks=False)
            if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino) or os.listdir(directory_fd):
                raise refused("SNAPSHOT_CHILD_DIRECTORY_CHANGED")
            memory, disk = _sample_resources(root_fd)
            self._mark("available_memory_bytes", memory)
            self._mark("available_disk_bytes", disk)
            if memory < MIN_MEMORY or disk < MIN_DISK:
                raise refused("SNAPSHOT_RESOURCE_FLOOR")
            self._control()
            clock = time.monotonic
            started = clock()
            self._mark("native_entered", True)
            self.native.writer(filepath, set(self.scenes), path_remap="NONE", fake_user=False, compress=False)
            returned_slot.__set__(cell, True)
            seconds_slot.__set__(cell, float(clock() - started))
            guard()
            self._control()  # No filesystem inspection or getter after a stop.
            info = os.lstat(filepath)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024**3:
                raise refused("SNAPSHOT_NATIVE_FILE_SHAPE")
            identity = _file_identity(info)
            cleanup_owner = mint_cleanup_owner(journal, cell, self.root, leaf,
                                               tuple.__getitem__(cleanup_owner, 4),
                                               tuple.__getitem__(cleanup_owner, 5), _file_cleanup_binding(info))
            self.cleanup_owner = cleanup_owner
            self._mark("file_identity", identity)
            self._mark("file_bytes", info.st_size)
            self._mark("parser_entered", True)
            names = CYCLES_NAMES if self.native.build[1][0] == 4 else CYCLES_502_NAMES
            projections, digest = [], None
            for target in self.native.baseline[-1]:
                self._control()
                proof = inspect_view_layer_storage(filepath, target[0][2], target[1][1], allowed_names=names)
                guard()
                self._control()
                if (type(proof) is not dict or type(proof.get("file_identity")) is not list
                        or len(proof["file_identity"]) != 4 or any(type(value) is not int for value in proof["file_identity"])
                        or type(proof.get("file_sha256")) is not str or len(proof["file_sha256"]) != 64
                        or any(char not in "0123456789abcdef" for char in proof["file_sha256"])
                        or tuple(proof["file_identity"]) != identity
                        or (digest is not None and proof["file_sha256"] != digest)):
                    raise refused("SNAPSHOT_NATIVE_FILE_CHANGED")
                digest = proof["file_sha256"]
                projections.append(_projection(proof, target, names))
            self._mark("parser_returned", True)
            self._mark("file_sha256", digest)
            guard()
            self._control()
            self.native.check()
            guard()
            self._control()
            self._mark("identity_verified", True)
            binding = tuple((self, operation_kind, slot, expected) for slot, expected in fixed)
            binding += ((self, operation_kind, operation_slots["native"], native),
                        (journal, journal_kind, journal_slot, journal_rows),
                        (self, operation_kind, operation_slots["cell"], cell),
                        (self, operation_kind, operation_slots["slots"], slot_pairs))
            binding += tuple((native, native_kind, slot, expected) for slot, expected in native_facts)
            binding += tuple((cell, slot.__objclass__, slot, expected) for slot, expected in owned_facts)
            return SnapshotWitness(self, tuple(projections), binding)
        except BaseException:
            if cell is not None and stopped_slot is not None:
                stopped_slot.__set__(cell, True)
                failed_slot.__set__(cell, True)
            raise
        finally:
            # Closing held OS descriptors does not inspect/delete native files
            # or restore Blender state. Retained artifacts remain untouched.
            if directory_fd is not None:
                close(directory_fd)
            if root_fd is not None:
                close(root_fd)


_WITNESS_KIND = SnapshotWitness
_WITNESS_OPERATION = vars(SnapshotWitness)["operation"]
_WITNESS_USED = vars(SnapshotWitness)["used"]
_OPERATION_KIND = SnapshotOperation
_OPERATION_SOURCE = vars(SnapshotOperation)["source"]

_OPERATION_RUN_CODE = vars(SnapshotOperation)["run"].__code__
_CELL_RETIRED = dict(_CELL_SLOTS)["cleanup_entered"]
_CLEANUP_OWNER_KIND = SnapshotOwner
_CLEANUP_OS_ORIGINS = tuple((name, vars(os).get(name)) for name in
                            ("open", "close", "lstat", "fstat", "stat", "scandir", "unlink", "rmdir", "geteuid"))


def _directory_cleanup_binding(info):
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid()):
        raise refused("SNAPSHOT_CLEANUP_DIRECTORY_UNQUALIFIED")
    return info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)


def _file_cleanup_binding(info):
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
        raise refused("SNAPSHOT_CLEANUP_FILE_UNQUALIFIED")
    return (info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode), info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _cleanup_control(context):
    method = context.checkpoint_method
    if type(method) is not str or method not in _METHODS or threading.current_thread() is not threading.main_thread():
        raise refused("SNAPSHOT_CANONICAL_MAIN_THREAD_ENTRY_REQUIRED")
    check_final_mutation(context, method)
    flags = context.state.snapshot()
    if type(flags) is not dict or any(type(flags.get(name)) is not bool for name in ("paused", "emergency_stopped")):
        raise refused("SNAPSHOT_CONTROL_FLAG_SHAPE")
    if flags["emergency_stopped"]:
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED, "Owned inspection cleanup stopped before its next filesystem operation.")
    if flags["paused"]:
        raise BridgeError(ErrorCode.AGENT_PAUSED, "Owned inspection cleanup paused before its next filesystem operation.")


def cleanup_step(context, journal, owner):
    """Clean one originally issued artifact in an exclusive private namespace.

    This is not a filesystem search or a recovery/backup API. Unknown partial
    native files are retained. POSIX cannot condition unlink on an inode: the
    existing exclusive Bridge-owned0700 namespace assumption remains required.
    The original physical root inode is authority. An ancestor alias may resolve
    to that same inode; no alias, ancestor or approval root is ever removed.
    """
    from .tools._cloth_cache_source import capture_cloth_sources
    source = capture_cloth_sources(context)
    fact = tuple.__getitem__(source, 7)
    verify, code, namespace, defaults, keywords, _saved, closures = fact
    if defaults is not None or keywords is not None or closures:
        raise refused("SNAPSHOT_SOURCE_BOOTSTRAP_SHAPE")
    failure = refused("SNAPSHOT_CLEANUP_SOURCE_CHANGED")
    if (SnapshotOwner is not _CLEANUP_OWNER_KIND or type(owner) is not _CLEANUP_OWNER_KIND
            or tuple.__len__(owner) != 7):
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    issued_journal, cell, root, leaf, root_binding, directory_binding, file_binding = tuple.__iter__(owner)
    if (issued_journal is not journal or type(root) is not str or not root or not os.path.isabs(root)
            or os.path.normpath(root) != root or type(leaf) is not str or len(leaf) != 44
            or not leaf.startswith("bcb-storage-") or any(ch not in "0123456789abcdef" for ch in leaf[12:])):
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    for binding, length in ((root_binding, 4), (directory_binding, 4)):
        if (type(binding) is not tuple or len(binding) != length
                or any(type(item) is not int or item < 0 for item in binding) or binding[-1] != 0o700):
            raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    if file_binding is not None and (type(file_binding) is not tuple or len(file_binding) != 8
            or any(type(item) is not int or item < 0 for item in file_binding) or file_binding[4] != 1):
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    owner_rows, state, state_slots = cleanup_state(journal, cell)
    state_kind = type(state)
    state_descriptors = dict(state_slots)
    expected = {name: slot.__get__(state, state_kind) for name, slot in state_slots}
    if expected["owner"] is not owner or any(type(value) is not bool for name, value in expected.items() if name != "owner"):
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    # Journal values remain receipts. They may invalidate cleanup, never adopt
    # another path or replace the original immutable owner facts.
    slots = dict(cell_slots(cell))
    row_facts = tuple((slots[name], value) for name, value in (
        ("root", root), ("directory", os.path.join(root, leaf)),
        ("filepath", os.path.join(root, leaf, "snapshot.blend")),
        ("root_identity", root_binding[:2]), ("directory_identity", directory_binding[:2])))
    cell_kind = type(cell)
    row_flags = {name: slots[name].__get__(cell, cell_kind) for name in ("cleanup_entered", "cleanup_returned")}
    if any(type(value) is not bool for value in row_flags.values()):
        raise refused("SNAPSHOT_CLEANUP_OWNER_CHANGED")
    # Preallocate both returned-FD slots before entering filesystem code. A
    # MemoryError after open must not lose the only reference to its raw FD.
    held_close, descriptors, opened = os.close, [None, None], 0
    in_error = False

    def guard():
        if (type(verify) is not FunctionType or verify.__code__ is not code or verify.__globals__ is not namespace
                or verify.__defaults__ is not None or verify.__kwdefaults__ is not None or verify.__closure__ is not None):
            raise failure
        verify(source, context)
        for name, function in _CLEANUP_OS_ORIGINS:
            if type(function) is not BuiltinFunctionType or vars(os).get(name) is not function:
                raise failure
        rows, current, current_slots = cleanup_state(journal, cell)
        if rows is not owner_rows or current is not state or current_slots is not state_slots:
            raise failure
        for name, slot in state_slots:
            if slot.__get__(state, state_kind) is not expected[name]:
                raise failure
        for slot, saved in row_facts:
            value = slot.__get__(cell, cell_kind)
            if type(value) is not type(saved):
                raise failure
            if type(saved) is tuple and (len(value) != len(saved) or any(type(item) is not int for item in value)):
                raise failure
            if value != saved:
                raise failure
        for name, saved in row_flags.items():
            if slots[name].__get__(cell, cell_kind) is not saved:
                raise failure

    def safe():
        guard()
        _cleanup_control(context)

    def authorize():
        safe()
        context.require(*REQUIRED)
        safe()

    def mark(name, value):
        state_descriptors[name].__set__(state, value)
        expected[name] = value

    def filesystem(function, *args, opening=False, **kwargs):
        nonlocal opened
        authorize()
        result = function(*args, **kwargs)
        if opening:
            descriptors[opened] = result
            opened += 1
        safe()
        return result

    def final_filesystem(function, *args, **kwargs):
        # A fresh provider precedes this final CAS phase. Never call another
        # provider between its path/content comparisons and the mutation.
        safe()
        result = function(*args, **kwargs)
        safe()
        return result

    def names(directory):
        authorize()
        # Native context ownership closes the iterator on errors/stops without
        # growing a post-scandir Python list of resource references.
        with os.scandir(directory) as iterator:
            safe()
            result = []
            for _ in range(2):
                authorize()
                try:
                    entry = next(iterator)
                except StopIteration:
                    safe()
                    return result
                safe()
                name = entry.name
                if type(name) is not str:
                    raise refused("SNAPSHOT_CLEANUP_ENTRY_UNQUALIFIED")
                result.append(name)
        raise refused("SNAPSHOT_CLEANUP_UNEXPECTED_ENTRIES")

    def check_directories(root_fd, child_fd, *, final=False):
        read = final_filesystem if final else filesystem
        if (_directory_cleanup_binding(read(os.lstat, root)) != root_binding
                or _directory_cleanup_binding(read(os.fstat, root_fd)) != root_binding
                or _directory_cleanup_binding(read(os.stat, leaf, dir_fd=root_fd, follow_symlinks=False)) != directory_binding
                or _directory_cleanup_binding(read(os.fstat, child_fd)) != directory_binding):
            raise refused("SNAPSHOT_CLEANUP_DIRECTORY_CHANGED")

    try:
        guard()
        if expected["rmdir_returned"]:
            return cleanup_receipt(journal, owner)
        authorize()
        slots["cleanup_entered"].__set__(cell, True)
        row_flags["cleanup_entered"] = True
        root_fd = filesystem(os.open, root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, opening=True)
        if (_directory_cleanup_binding(filesystem(os.lstat, root)) != root_binding
                or _directory_cleanup_binding(filesystem(os.fstat, root_fd)) != root_binding):
            raise refused("SNAPSHOT_CLEANUP_ROOT_CHANGED")
        child_fd = filesystem(os.open, leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd, opening=True)
        check_directories(root_fd, child_fd)
        entries = names(child_fd)
        if expected["unlink_returned"]:
            if entries:
                raise refused("SNAPSHOT_CLEANUP_UNEXPECTED_ENTRIES")
        elif file_binding is None:
            if entries:
                mark("retained_unknown", True)
                return cleanup_receipt(journal, owner)
        else:
            if entries != ["snapshot.blend"]:
                raise refused("SNAPSHOT_CLEANUP_FILE_CHANGED")
            info = filesystem(os.stat, "snapshot.blend", dir_fd=child_fd, follow_symlinks=False)
            if _file_cleanup_binding(info) != file_binding:
                raise refused("SNAPSHOT_CLEANUP_FILE_CHANGED")
            check_directories(root_fd, child_fd)
            authorize()
            check_directories(root_fd, child_fd, final=True)
            info = final_filesystem(os.stat, "snapshot.blend", dir_fd=child_fd, follow_symlinks=False)
            if _file_cleanup_binding(info) != file_binding:
                raise refused("SNAPSHOT_CLEANUP_FILE_CHANGED")
            safe()
            mark("unlink_entered", True)
            os.unlink("snapshot.blend", dir_fd=child_fd)
            mark("unlink_returned", True)  # Literal return before stop/source checks.
            safe()
        check_directories(root_fd, child_fd)
        if names(child_fd):
            raise refused("SNAPSHOT_CLEANUP_UNEXPECTED_ENTRIES")
        authorize()
        check_directories(root_fd, child_fd, final=True)
        safe()
        mark("rmdir_entered", True)
        os.rmdir(leaf, dir_fd=root_fd)
        mark("rmdir_returned", True)
        slots["cleanup_returned"].__set__(cell, True)
        row_flags["cleanup_returned"] = True
        safe()
        return cleanup_receipt(journal, owner)
    except BaseException:
        in_error = True
        mark("failed", True)
        raise
    finally:
        # Closing already-held resources is permitted even after a stop; it
        # neither inspects paths nor performs file deletion or Blender work.
        close_error = None
        descriptor = descriptors[1]
        if descriptor is not None:
            try:
                held_close(descriptor)
            except BaseException as error:
                mark("close_failed", True)
                if close_error is None:
                    close_error = error
        descriptor = descriptors[0]
        if descriptor is not None:
            try:
                held_close(descriptor)
            except BaseException as error:
                mark("close_failed", True)
                if close_error is None:
                    close_error = error
        if close_error is not None and not in_error:
            mark("failed", True)
            raise close_error
