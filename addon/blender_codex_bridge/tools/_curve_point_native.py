"""Ordinary stock-Blender point reads and one canonical Float2 assignment.

This is a closed, synchronous trusted-runtime profile, not a Python sandbox or
persistent non-ID/ABA guarantee. Checkpoint context reads remain explicit and
separate from the literal original capture. No full FCurve.update is issued.
"""

from __future__ import annotations

import inspect
import math
import struct
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from types import CodeType, FunctionType, ModuleType, WrapperDescriptorType
from typing import Any

from .. import permissions as _permission_module
from .. import runtime as _runtime
from ..errors import BridgeError, invalid_argument
from ..task_plans import get_task_plans
from ..utils import require_blender
from . import _animation_scope as scope
from . import _curve_edit_intent as intent
from . import _scene_mutation as native

BUILDS = {(4, 5, 14): b"62c1db4208e8", (5, 2, 2): b"d13f752e3b9c"}
MAX_IDS, MAX_OBJECTS, MAX_ACTIONS = 256, 128, 16
RAW_CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
                "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")
CHANNEL_LENGTHS = (3, 3, 4, 4, 3, 3, 3, 4, 3)
_RUNTIME_CLASS = _runtime.BridgeRuntime
_STATE_CLASS, _REGISTRY_CLASS = _runtime.BridgeState, _runtime.ToolRegistry
_CHECKPOINT_CLASS, _JOBS_CLASS = _runtime.CheckpointManager, _runtime.NativeSaveJobs
_SNAPSHOT, _SNAPSHOT_CODE = _STATE_CLASS.snapshot, _STATE_CLASS.snapshot.__code__
_PREFERENCES, _PERMISSIONS = _runtime._preferences, _runtime.permission_snapshot
_PREFERENCES_CODE, _PERMISSIONS_CODE = _PREFERENCES.__code__, _PERMISSIONS.__code__
_POLICY_MODULE = _runtime._native_save_policy_module
_GRANT_CLASS, _STATEMENT_CLASS = _runtime.NativeSaveGrant, _runtime.GrantStatement
_PERMISSION_CLASS = _permission_module.Permission
_JOBS_MODULE = sys.modules[_JOBS_CLASS.__module__]
_ABSENT = object()
_PURE_TYPE, _PURE_VARS, _PURE_ALL, _PURE_ANY = type, vars, all, any
_PURE_TUPLE, _PURE_ZIP, _PURE_LEN = tuple, zip, len
_PURE_DICT, _PURE_LIST = dict, list
_TYPE_NAMESPACE_DESCRIPTOR = vars(type)["__dict__"]


def _class_items(kind):
    # This native type getset bypasses a replaced Python metaclass getter.
    return _PURE_TUPLE(_TYPE_NAMESPACE_DESCRIPTOR.__get__(kind, _PURE_TYPE).items())


def _code_names(code):
    result = set(code.co_names)
    for child in code.co_consts:
        if type(child) is CodeType:
            result.update(_code_names(child))
    return result


def _function_pin(function):
    """Retain CPython function metadata without executing its body or defaults."""
    assert type(function) is FunctionType
    keywords, closure = function.__kwdefaults__, function.__closure__
    names = sorted(_code_names(function.__code__) | {"__builtins__", "__import__"})
    return (function, function.__code__, function.__globals__, function.__defaults__,
            keywords, None if keywords is None else tuple(keywords.items()), closure,
            None if closure is None else tuple(cell.cell_contents for cell in closure),
            tuple((name, function.__globals__.get(name, _ABSENT))
                  for name in names if name != "_RUNTIME"), function.__builtins__,
            tuple((name, function.__builtins__.get(name, _ABSENT)) for name in names
                  if name != "_RUNTIME" and name not in function.__globals__))


def _same_items(actual, expected):
    return (_PURE_LEN(actual) == _PURE_LEN(expected)
            and _PURE_ALL(_PURE_TYPE(key) is _PURE_TYPE(old_key) and key is old_key and value is old_value
                          for (key, value), (old_key, old_value) in _PURE_ZIP(actual, expected, strict=True)))


_FUNCTION_BINDINGS = (
    (vars(_runtime), "permission_snapshot", _PERMISSIONS),
    (vars(_runtime), "native_save_permission_provider_intact", _runtime.native_save_permission_provider_intact),
    (vars(_runtime), "_preferences", _PREFERENCES),
    (vars(_runtime), "_base_permission_snapshot", _runtime._base_permission_snapshot),
    (vars(_permission_module), "permission_snapshot", _permission_module.permission_snapshot),
    (vars(_RUNTIME_CLASS), "__init__", _RUNTIME_CLASS.__init__),
    *((vars(_GRANT_CLASS), name, vars(_GRANT_CLASS)[name].__func__
       if type(vars(_GRANT_CLASS)[name]) is staticmethod else vars(_GRANT_CLASS)[name])
      for name in ("__init__", "__setattr__", "_main", "_now", "arm", "revoke",
                   "active", "statement", "check", "status")),
    (vars(_STATEMENT_CLASS), "__init__", _STATEMENT_CLASS.__init__),
)
_FUNCTION_PINS = tuple(_function_pin(function) for _, _, function in _FUNCTION_BINDINGS)
_GENERATION = vars(_GRANT_CLASS)["generation"]
_GENERATION_PIN = _function_pin(_GENERATION.fget)
_JOBS_MRO = _JOBS_CLASS.__mro__
_CLASS_PINS = tuple((kind, tuple(vars(kind).items()))
                    for kind in (_RUNTIME_CLASS, *_JOBS_MRO[:-1], _GRANT_CLASS, _STATEMENT_CLASS,
                                 _runtime.PermissionManager, _PERMISSION_CLASS))
_MODULE_PINS = tuple((module, name, vars(module).get(name, _ABSENT)) for module, names in (
    (_runtime, ("NativeSaveJobs", "NativeSaveGrant", "GrantStatement", "Permission", "PermissionManager",
                "_native_save_policy_module")),
    (_permission_module, ("Permission", "PREFERENCE_PROPERTIES")),
    (_POLICY_MODULE, ("NativeSaveGrant", "GrantStatement", "POLICY_VERSION", "math", "threading", "time")),
    (_JOBS_MODULE, ("NativeSaveJobs",)),
    (threading, ("current_thread", "main_thread", "get_ident", "_active", "_main_thread")),
    (_POLICY_MODULE.math, ("isfinite", "ceil")), (_POLICY_MODULE.time, ("monotonic",)),
) for name in names)
_THREAD_PINS = tuple(_function_pin(function) for function in (threading.current_thread, threading.main_thread))
_MAIN_THREAD, _MAIN_THREAD_ID = threading._main_thread, threading.get_ident()
_PREFERENCE_MAP = _permission_module.PREFERENCE_PROPERTIES
_PREFERENCE_ITEMS = tuple(_PREFERENCE_MAP.items())
_ENUM_MAP, _ENUM_NAMES = vars(_PERMISSION_CLASS)["_member_map_"], vars(_PERMISSION_CLASS)["_member_names_"]
_ENUM_ITEMS, _ENUM_NAME_ITEMS = tuple(_ENUM_MAP.items()), tuple(_ENUM_NAMES)
_ENUM_VALUES = tuple((member, tuple(vars(member).items())) for _, member in _ENUM_ITEMS)
_ENUM_META = type(_PERMISSION_CLASS)
_ENUM_VALUE = vars(Enum)["value"]
_ENUM_VALUE_MRO = type(_ENUM_VALUE).__mro__
_ENUM_PARENT_PINS = tuple((kind, tuple(vars(kind).items()))
                         for kind in (Enum, _ENUM_META, *_ENUM_VALUE_MRO[:-1]))
_ENUM_DESCRIPTOR_ITEMS = tuple(vars(_ENUM_VALUE).items())
_ENUM_FUNCTION_PINS = (_function_pin(vars(_ENUM_META)["__iter__"]), _function_pin(_ENUM_VALUE.fget),
                       _function_pin(vars(type(_ENUM_VALUE))["__get__"]))


def _function_intact(pin):
    function, code, namespace, defaults, keywords, items, closure, cells, bindings, builtins, fallbacks = pin
    if (_PURE_TYPE(function) is not FunctionType or function.__code__ is not code
            or function.__globals__ is not namespace or function.__defaults__ is not defaults
            or function.__kwdefaults__ is not keywords or function.__closure__ is not closure
            or function.__builtins__ is not builtins or _PURE_TYPE(builtins) is not _PURE_DICT):
        return False
    if keywords is not None and (_PURE_TYPE(keywords) is not _PURE_DICT
                                 or not _same_items(_PURE_TUPLE(keywords.items()), items)):
        return False
    if closure is not None:
        try:
            if _PURE_ANY(cell.cell_contents is not old for cell, old in _PURE_ZIP(closure, cells, strict=True)):
                return False
        except ValueError:
            return False
    return (_PURE_ALL(namespace.get(name, _ABSENT) is expected for name, expected in bindings)
            and _PURE_ALL(builtins.get(name, _ABSENT) is expected for name, expected in fallbacks))


def _permission_dependencies():
    """Independently authenticate the whole reviewed overlay; call no provider.

    Runtime's retained guard constants are dependencies, not an attestation. The
    grant's volatile epoch, expiry and active statement are deliberately absent.
    """
    if (_PURE_ANY(_PURE_TYPE(module) is not ModuleType or _PURE_VARS(module).get(name, _ABSENT) is not value
                 for module, name, value in _MODULE_PINS)
            or _PURE_ANY(_PURE_TYPE(kind) is not _PURE_TYPE
                         or not _same_items(_class_items(kind), items)
                         for kind, items in _CLASS_PINS if kind is not _PERMISSION_CLASS)
            or not _same_items(_class_items(_PERMISSION_CLASS), _CLASS_PINS[-1][1])
            or _JOBS_CLASS.__mro__ is not _JOBS_MRO
            or _PURE_TYPE(_PERMISSION_CLASS) is not _ENUM_META
            or _PURE_ANY(not _same_items(_class_items(kind), items)
                         for kind, items in _ENUM_PARENT_PINS)
            or _PURE_TYPE(_ENUM_VALUE).__mro__ is not _ENUM_VALUE_MRO
            or not _same_items(_PURE_TUPLE(_PURE_VARS(_ENUM_VALUE).items()), _ENUM_DESCRIPTOR_ITEMS)):
        raise refused("The closed point permission dependency graph changed before native getters.")
    for namespace, name, function in _FUNCTION_BINDINGS:
        actual = namespace.get(name, _ABSENT)
        if _PURE_TYPE(actual) is staticmethod:
            actual = actual.__func__
        if actual is not function:
            raise refused("The closed point permission dependency graph changed before native getters.")
    if (not _PURE_ALL(_function_intact(pin) for pin in (*_FUNCTION_PINS, _GENERATION_PIN,
                                                      *_THREAD_PINS, *_ENUM_FUNCTION_PINS))
            or _permission_module.PREFERENCE_PROPERTIES is not _PREFERENCE_MAP
            or _PURE_TYPE(_PREFERENCE_MAP) is not _PURE_DICT
            or not _same_items(_PURE_TUPLE(_PREFERENCE_MAP.items()), _PREFERENCE_ITEMS)
            or _PURE_TYPE(_ENUM_MAP) is not _PURE_DICT or not _same_items(_PURE_TUPLE(_ENUM_MAP.items()), _ENUM_ITEMS)
            or _PURE_TYPE(_ENUM_NAMES) is not _PURE_LIST or _PURE_LEN(_ENUM_NAMES) != _PURE_LEN(_ENUM_NAME_ITEMS)
            or _PURE_ANY(a is not b for a, b in _PURE_ZIP(_ENUM_NAMES, _ENUM_NAME_ITEMS, strict=True))
            or _PURE_ANY(not _same_items(_PURE_TUPLE(_PURE_VARS(member).items()), items)
                         for member, items in _ENUM_VALUES)
            or _PURE_TYPE(threading._active) is not _PURE_DICT
            or threading._active.get(_MAIN_THREAD_ID) is not _MAIN_THREAD):
        raise refused("The closed point permission dependency graph changed before native getters.")


def _grant_origin(active):
    """Read only screened Python instance storage, never a grant property."""
    attributes = vars(active)
    grant = attributes.get("native_save_policy")
    if (type(grant) is not _GRANT_CLASS or grant is not attributes.get("_native_save_policy_origin")
            or vars(active.jobs).get("native_save_policy") is not grant):
        raise refused("The canonical point native-save grant owner changed.")
    authority = object.__getattribute__(grant, "_authority")
    generation = object.__getattribute__(grant, "_generation")
    owner_thread = object.__getattribute__(grant, "_thread")
    if (type(authority) is not object or authority is not attributes.get("_native_save_local_authority")
            or type(generation) is not str or generation is not attributes.get("_native_save_generation")
            or type(owner_thread) is not int or owner_thread != threading.get_ident()
            or object.__getattribute__(grant, "_sealed") is not True
            or type(attributes.get("_registered")) is not bool):
        raise refused("The canonical point native-save grant authority changed.")
    return grant, authority, generation, owner_thread


def refused(message: str, **facts: Any) -> BridgeError:
    return BridgeError("NOT_IMPLEMENTED", message,
                       {"curve_point_profile": "RAW_FREE_POINT_V1", "complete_hidden_state_qualified": False, **facts})


_LOCAL_NAMESPACE = globals()
_LOCAL_BUILTINS = (_PURE_TYPE, _PURE_VARS, _PURE_ALL, _PURE_ANY, _PURE_TUPLE,
                   _PURE_ZIP, _PURE_LEN, _PURE_DICT, _PURE_LIST)
_LOCAL_HELPER_PINS = tuple((name, _function_pin(function)) for name, function in (
    ("_permission_dependencies", _permission_dependencies), ("_function_intact", _function_intact),
    ("_same_items", _same_items), ("_class_items", _class_items),
    ("_grant_origin", _grant_origin), ("refused", refused),
))


def bounded(values: Any, limit: int, label: str) -> tuple:
    return native.bounded(values, limit, "point " + label)


def identity(owner: Any) -> tuple[int, int] | None:
    if owner is None:
        return None
    pointer, uid = owner.as_pointer(), owner.session_uid
    if type(pointer) is not int or type(uid) is not int or pointer <= 0 or uid <= 0:
        raise refused("Point ownership requires positive native ID pointers and session UIDs.")
    return pointer, uid


def pointer(owner: Any) -> int:
    value = owner.as_pointer()
    if type(value) is not int or value <= 0:
        raise refused("Point descendants require a positive native allocation address.")
    return value


def raw_tuple(values: Any) -> tuple:
    result = tuple(values)
    if any(type(v) is not float or not math.isfinite(v) for v in result):
        raise refused("Raw point preservation requires finite native floating values.")
    return result


def native_slots(bpy: Any) -> tuple:
    classes = (bpy.types.FCurve, bpy.types.Keyframe)
    result = []
    for name in ("__getattribute__", "__setattr__"):
        slots = tuple(inspect.getattr_static(cls, name, None) for cls in classes)
        first = slots[0]
        if (any(type(slot) is not WrapperDescriptorType or slot is not first for slot in slots)
                or first.__name__ != name or first.__objclass__.__name__ != "bpy_struct"
                or any(first.__objclass__ not in cls.__mro__ for cls in classes)):
            raise refused("Point fields require the genuine shared native RNA slot; no fallback.")
        result.append(first)
    return tuple(result)


class Leaf:
    """The only retained point wrapper lives solely around the native call."""

    __slots__ = ("field", "owner", "setter", "value")

    def __init__(self, owner: Any, setter: Any, field: str, value: tuple[float, float]):
        self.owner, self.setter, self.field, self.value = owner, setter, field, value

    def __call__(self) -> None:
        self.setter(self.owner, self.field, self.value)

    def clear(self) -> None:
        self.owner = self.setter = None


@dataclass(frozen=True, slots=True)
class ActiveWitness:
    reader: Any
    name: str
    owner_id: tuple[int, int]
    before: tuple

    def check(self, _plan: Any) -> None:
        obj = self.reader.bpy.data.objects.get(self.name)
        if obj is None or identity(obj) != self.owner_id or self.reader.object_record(obj, static=True) != self.before:
            raise refused("The separate unanimated checkpoint owner changed.")


class Reader:
    """Literal original fields, fresh Action membership and trusted call origin."""

    def __init__(self, context: Any, params: dict):
        self.context, self.params = context, params
        self.origin = self._ordinary_origin()
        self.bpy = require_blender()
        if (sys.platform != "linux" or tuple(self.bpy.app.version) not in BUILDS
                or self.bpy.app.build_hash != BUILDS[tuple(self.bpy.app.version)]):
            raise refused("Point authoring admits only the two source-reviewed official Linux builds.")
        self._slots = native_slots(self.bpy)
        self._hooks = self.hooks()
        self.name = params["object_name"]
        self.ids = None
        self.role_plan: Any = None
        self.plan_store = get_task_plans(context.state)
        if self.plan_store.protection is not None:
            raise refused("Initial raw point edits require advisory task scope; enforcement is retained.")
        self.plan_origin = (self.plan_store, self.plan_store.plan, self.plan_store.baseline,
                            self.plan_store.protection, self.plan_store.protection_generation,
                            self.plan_store.evidence_epoch)
        from ..tool_registry import _checkpoint_parameters
        self.plan_semantic = _checkpoint_parameters((self.plan_store.plan, self.plan_store.scope,
            self.plan_store.baseline, self.plan_store.protection, self.plan_store.protection_generation,
            self.plan_store.evidence_epoch))
        self._screen()
        obj = self.bpy.data.objects.get(self.name)
        if obj is None:
            raise invalid_argument("The explicit point-edit Object is missing.")
        self.ids = identity(obj), identity(obj.animation_data.action)
        self.original_literal = self.literal()

    def hooks(self):
        functions = (Reader._ordinary_origin, Reader.check_origin, Reader._screen, Reader._screen_action,
                     Reader.schema, Reader.selected, Reader.literal,
                     Reader.resolve, Reader.prepare, Reader.leaf, Reader.object_record, Reader.action_content,
                     Reader.preservation, Reader.roles, Reader.inventory, Reader.target_consumers,
                     Leaf.__call__, Leaf.clear,
                     identity, pointer, native_slots, bounded, raw_tuple, inspect.getattr_static,
                     _permission_dependencies, _function_intact, _same_items, _class_items, _grant_origin)
        return (Reader, Leaf, *functions,
                *(getattr(function, "__code__", None) for function in functions))

    def _ordinary_origin(self):
        # Authenticate our local proof graph inline before calling any of it.
        # Import-time pins are independent of the runtime's self-attestation.
        native_type, native_tuple, native_dict = ().__class__.__class__, ().__class__, {}.__class__
        native_str, native_function = "".__class__, (lambda: None).__class__
        native_code = (lambda: None).__code__.__class__
        tuple_length = native_tuple.__len__
        if (native_type(_LOCAL_NAMESPACE) is not native_dict
                or native_type(_LOCAL_BUILTINS) is not native_tuple or tuple_length(_LOCAL_BUILTINS) != 9
                or native_type(_LOCAL_HELPER_PINS) is not native_tuple or tuple_length(_LOCAL_HELPER_PINS) != 6):
            raise BridgeError("NOT_IMPLEMENTED", "The local point dependency root shape changed.")
        for row in _LOCAL_HELPER_PINS:
            if (native_type(row) is not native_tuple or tuple_length(row) != 2
                    or native_type(row[0]) is not native_str or native_type(row[1]) is not native_tuple
                    or tuple_length(row[1]) != 11):
                raise BridgeError("NOT_IMPLEMENTED", "The local point dependency pin shape changed.")
            pin = row[1]
            if (native_type(pin[0]) is not native_function or native_type(pin[1]) is not native_code
                    or pin[2] is not _LOCAL_NAMESPACE or pin[0].__globals__ is not _LOCAL_NAMESPACE
                    or pin[3] is not None or pin[4] is not None or pin[5] is not None
                    or pin[6] is not None or pin[7] is not None
                    or native_type(pin[8]) is not native_tuple or tuple_length(pin[8]) > 128
                    or native_type(pin[9]) is not native_dict or pin[0].__builtins__ is not pin[9]
                    or native_type(pin[10]) is not native_tuple or tuple_length(pin[10]) > 128):
                raise BridgeError("NOT_IMPLEMENTED", "The local point dependency pin contents changed.")
            for rows in (pin[8], pin[10]):
                for binding in rows:
                    if (native_type(binding) is not native_tuple or tuple_length(binding) != 2
                            or native_type(binding[0]) is not native_str):
                        raise BridgeError("NOT_IMPLEMENTED", "The local point dependency binding shape changed.")
        if (_PURE_TYPE is not _LOCAL_BUILTINS[0] or _PURE_VARS is not _LOCAL_BUILTINS[1]
                or _PURE_ALL is not _LOCAL_BUILTINS[2] or _PURE_ANY is not _LOCAL_BUILTINS[3]
                or _PURE_TUPLE is not _LOCAL_BUILTINS[4] or _PURE_ZIP is not _LOCAL_BUILTINS[5]
                or _PURE_LEN is not _LOCAL_BUILTINS[6] or _PURE_DICT is not _LOCAL_BUILTINS[7]
                or _PURE_LIST is not _LOCAL_BUILTINS[8]):
            raise BridgeError("NOT_IMPLEMENTED", "The local point dependency proof changed before callbacks.")
        for name, pin in _LOCAL_HELPER_PINS:
            function, code, namespace, defaults, keywords, items, closure, cells, bindings, builtins, fallbacks = pin
            if (_LOCAL_NAMESPACE.get(name) is not function or _PURE_TYPE(function) is not FunctionType
                    or function.__code__ is not code or function.__globals__ is not namespace
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
                    or function.__closure__ is not closure or function.__builtins__ is not builtins
                    or _PURE_TYPE(builtins) is not _PURE_DICT
                    or _PURE_ANY(namespace.get(key, _ABSENT) is not value for key, value in bindings)
                    or _PURE_ANY(builtins.get(key, _ABSENT) is not value for key, value in fallbacks)):
                raise BridgeError("NOT_IMPLEMENTED", "The local point dependency proof changed before callbacks.")
            if keywords is not None and (
                _PURE_TYPE(keywords) is not _PURE_DICT or _PURE_LEN(keywords) != _PURE_LEN(items)
                or _PURE_ANY(key is not old_key or value is not old_value
                             for (key, value), (old_key, old_value)
                             in _PURE_ZIP(keywords.items(), items, strict=True))
            ):
                raise BridgeError("NOT_IMPLEMENTED", "The local point dependency proof changed before callbacks.")
            if closure is not None:
                try:
                    changed = _PURE_ANY(cell.cell_contents is not old
                                        for cell, old in _PURE_ZIP(closure, cells, strict=True))
                except ValueError:
                    changed = True
                if changed:
                    raise BridgeError("NOT_IMPLEMENTED", "The local point dependency proof changed before callbacks.")
        _permission_dependencies()
        from ..command_queue import QueuedRequest
        from ..executor import MainThreadExecutor
        from ..permissions import PermissionManager
        from ..tool_registry import ToolContext

        c, active = self.context, _runtime._RUNTIME
        if (threading.current_thread() is not threading.main_thread() or type(c) is not ToolContext
                or type(active) is not _RUNTIME_CLASS or _runtime.BridgeRuntime is not _RUNTIME_CLASS
                or c.state is not active.state or c.registry is not active.registry
                or c.permissions is not active.permissions or c.checkpoints is not active.checkpoints
                or type(active.executor) is not MainThreadExecutor
                or active.executor.state is not c.state or active.executor.registry is not c.registry
                or active.executor.permissions is not c.permissions or active.executor.checkpoints is not c.checkpoints
                or active.executor.jobs is not c.jobs or c.jobs is not active.jobs
                or type(c.state) is not _STATE_CLASS or type(c.registry) is not _REGISTRY_CLASS
                or type(c.checkpoints) is not _CHECKPOINT_CLASS or type(active.jobs) is not _JOBS_CLASS
                or getattr(c.state.snapshot, "__func__", None) is not _SNAPSHOT
                or _SNAPSHOT.__code__ is not _SNAPSHOT_CODE
                or active.jobs.active is not None or type(c.permissions) is not PermissionManager
                or c.check_final_job is not None):
            raise refused("Point fields require canonical ordinary Runtime/Executor services.")
        source = c.permissions._source
        codes = tuple(item for item in _RUNTIME_CLASS.__init__.__code__.co_consts
                      if type(item) is CodeType and set(item.co_names) == {"permission_snapshot", "_preferences"})
        if (type(source) is not FunctionType or len(codes) != 1 or source.__code__ is not codes[0]
                or source.__globals__ is not vars(_runtime) or source.__closure__ is not None
                or source.__defaults__ is not None or source.__kwdefaults__ is not None
                or _runtime._preferences is not _PREFERENCES or _PREFERENCES.__code__ is not _PREFERENCES_CODE
                or _runtime.permission_snapshot is not _PERMISSIONS or _PERMISSIONS.__code__ is not _PERMISSIONS_CODE):
            raise refused("Unreviewed point permission providers are refused before native getters.")
        cancel, final = c.check_cancelled, c.check_final_request
        if cancel is None:
            if final is not None:
                raise refused("A direct point call has an unknown final-request hook.")
            request = None
        else:
            request = getattr(cancel, "__self__", None)
            codes = tuple(item for item in MainThreadExecutor._invoke_owned.__code__.co_consts
                          if type(item) is CodeType and item.co_freevars == ("queued_owner",))
            if (type(request) is not QueuedRequest or getattr(cancel, "__func__", None) is not QueuedRequest.check_active
                    or type(final) is not FunctionType or len(codes) != 1 or final.__code__ is not codes[0]
                    or final.__closure__ is None or len(final.__closure__) != 1
                    or final.__closure__[0].cell_contents is not request
                    or c.request_lifecycle is not request.request._lifecycle):
                raise refused("Unknown point cancellation hooks are refused before native reads.")
        return (active, active.executor, active.jobs, c.state, c.registry, c.permissions, c.checkpoints,
                source, source.__code__, source.__globals__, _runtime._preferences, _PREFERENCES.__code__,
                _runtime.permission_snapshot, _PERMISSIONS.__code__, cancel, final, c.request_lifecycle,
                *_grant_origin(active))

    def check_origin(self):
        now = self._ordinary_origin()
        if len(now) != len(self.origin) or any(a is not b for a, b in zip(now, self.origin, strict=True)):
            raise refused("The original ordinary point-call services or hooks changed.")
        if self.hooks() != self._hooks:
            raise refused("A retained native point reader or leaf implementation changed.")
        store, plan, baseline, protection, generation, epoch = self.plan_origin
        if (getattr(self.context.state, "_artist_task_plans", None) is not store
                or store.plan is not plan or store.baseline is not baseline or store.protection is not protection
                or store.protection_generation != generation or store.evidence_epoch != epoch):
            raise refused("The original point task-plan policy was invalidated.")
        from ..tool_registry import _checkpoint_parameters
        if _checkpoint_parameters((store.plan, store.scope, store.baseline, store.protection,
                                   store.protection_generation, store.evidence_epoch)) != self.plan_semantic:
            raise refused("The original point task-plan policy changed in place.")

    def schema(self, owner: Any, fields: dict) -> None:
        kind = owner.bl_rna.identifier
        canonical = getattr(self.bpy.types, kind, None)
        if canonical is None or type(owner) is not canonical or canonical.bl_rna != owner.bl_rna:
            raise refused("Point evidence requires canonical native RNA classes.")
        for name, (wanted, size) in fields.items():
            prop = owner.bl_rna.properties.get(name)
            if (prop is None or prop.is_runtime or prop.is_registered or prop.type != wanted
                    or (size is not None and prop.array_length != size)):
                raise refused("A declared point preservation descriptor changed.", owner_type=kind, property=name)

    def _screen_action(self, action):
        native.descriptors(self.bpy, action)
        if action.library is not None or action.override_library is not None or not action.is_editable:
            raise refused("Linked, override or uneditable Actions are not point-editable.")
        if action.asset_data is not None or tuple(action.keys()):
            raise refused("Asset/custom-property Actions need another authoring profile.")
        for collection in (action.slots, action.layers, action.pose_markers):
            for owner in bounded(collection, 64, "Action children"):
                native.descriptors(self.bpy, owner)
        if not action.is_action_layered:
            for group in bounded(action.groups, 64, "legacy Action groups"):
                native.descriptors(self.bpy, group)
                native.descriptors(self.bpy, group.colors)
        for layer in bounded(action.layers, 16, "Action layers"):
            for strip in bounded(layer.strips, 32, "Action strips"):
                native.descriptors(self.bpy, strip)
                for bag in bounded(strip.channelbags, 64, "Action channelbags"):
                    native.descriptors(self.bpy, bag)
                    for group in bounded(bag.groups, 64, "Action groups"):
                        native.descriptors(self.bpy, group)
                        native.descriptors(self.bpy, group.colors)
        curves = scope.curve_inventory(action)
        if len(curves) > 32:
            raise refused("The point Action profile admits at most 32 curves.")
        total = 0
        for _slot, curve in curves:
            native.descriptors(self.bpy, curve)
            if curve.sampled_points or curve.modifiers or curve.driver is not None:
                raise refused("Point edits require ordinary unsampled modifier-free driver-free curves.")
            points = bounded(curve.keyframe_points, 1024, "Action keys")
            total += len(points)
            if total > 1024:
                raise refused("The complete point Action exceeds 1024 keyframes.")
            for point in points:
                native.descriptors(self.bpy, point)

    def _screen(self):
        scenes = bounded(self.bpy.data.scenes, 1, "Scenes")
        if len(scenes) != 1:
            raise refused("Initial point edits require exactly one Scene.")
        self.scene = scenes[0]
        layers = bounded(self.scene.view_layers, 1, "Scene ViewLayers")
        if len(layers) != 1:
            raise refused("Initial point edits require one Scene/ViewLayer.")
        self.layer = layers[0]
        managers = bounded(self.bpy.data.window_managers, 1, "window managers")
        if len(managers) != 1:
            raise refused("Initial point edits require one native WindowManager.")
        windows = bounded(managers[0].windows, 1, "Windows")
        if len(windows) != 1 or windows[0].scene != self.scene:
            raise refused("Initial point edits require one current Window/Scene.")
        self.window = windows[0]
        for field in native.HANDLERS:
            if getattr(self.bpy.app.handlers, field):
                raise refused("Frame/dependency callbacks need separate point-window qualification.")
        objects = bounded(self.bpy.data.objects, MAX_OBJECTS, "Main Objects")
        target = self.bpy.data.objects.get(self.name)
        for obj in objects:
            self.object_record(obj, static=obj != target)
        if target is None or target.type != "EMPTY" or target.data is not None:
            raise refused("The first point profile edits an explicit local Empty's transform curves.")
        if (tuple(target.users_scene) != (self.scene,) or tuple(target.users_collection) != (self.scene.collection,)
                or target.hide_viewport or self.layer.layer_collection.exclude):
            raise refused("The point target needs direct visible ownership by the sole Scene master.")
        data = target.animation_data
        if (data is None or data.action is None or data.drivers or data.nla_tracks or data.use_tweak_mode
                or not data.use_nla or data.action_blend_type != "REPLACE" or data.action_influence != 1.0):
            raise refused("Point authoring requires one ordinary active Action binding.")
        native.descriptors(self.bpy, data)
        actions = bounded(self.bpy.data.actions, MAX_ACTIONS, "Main Actions")
        for action in actions:
            self._screen_action(action)
        if data.action not in actions or data.action.users - int(data.action.use_fake_user) != 1:
            raise refused("The active point Action must have exactly one real user.")
        if (getattr(data.action, "is_action_layered", False)
                and (data.action_slot is None or data.action_slot.target_id_type != "OBJECT")):
            raise refused("Layered point Actions require one assigned OBJECT slot.")
        self.inventory()
        self.target_consumers(target)

    def inventory(self):
        """Bounded ID headers/animation roots, including exposed embedded trees."""
        rows, aliases = [], []
        for prop in bounded(self.bpy.data.bl_rna.properties, 128, "Main schema"):
            if prop.type != "COLLECTION":
                continue
            if prop.is_runtime or prop.is_registered:
                raise refused("Runtime Main declarations are outside the point profile.")
            values = bounded(getattr(self.bpy.data, prop.identifier), MAX_IDS, "Main family")
            if prop.identifier == "all_ids":
                aliases.append(frozenset(identity(owner) for owner in values))
                continue
            if values and prop.identifier in {"libraries", "texts"}:
                raise refused("Linked-library/Text roots need separate point-window qualification.")
            for owner in values:
                self.schema(owner, {"name": ("STRING", None), "library": ("POINTER", None),
                                    "override_library": ("POINTER", None), "users": ("INT", 0),
                                    "use_fake_user": ("BOOLEAN", 0), "use_extra_user": ("BOOLEAN", 0)})
                if owner.library is not None or owner.override_library is not None:
                    raise refused("All admitted point-window Main IDs must be local and nonoverride.")
                if owner.bl_rna.identifier != "Object" or owner.name != self.name:
                    animation = owner.bl_rna.properties.get("animation_data")
                    if animation is not None:
                        self.schema(owner, {"animation_data": ("POINTER", None)})
                        if owner.animation_data is not None:
                            raise refused("Unrelated Main animation can change during native checkpointing.")
                embedded = []
                for field in ("node_tree", "compositing_node_group"):
                    descriptor = owner.bl_rna.properties.get(field)
                    if descriptor is None:
                        continue
                    self.schema(owner, {field: ("POINTER", None)})
                    child = getattr(owner, field)
                    if child is not None:
                        self.schema(child, {"animation_data": ("POINTER", None)})
                        if child.animation_data is not None:
                            raise refused("Embedded animation needs separate checkpoint preservation.")
                        embedded.append((field, identity(child)))
                rows.append((prop.identifier, identity(owner), owner.name, int(owner.users),
                             bool(owner.use_fake_user), bool(owner.use_extra_user), tuple(embedded)))
                if len(rows) > MAX_IDS:
                    raise refused("The complete point Main inventory exceeds 256 IDs.")
        keys = frozenset(row[1] for row in rows)
        if len(keys) != len(rows) or any(alias != keys for alias in aliases):
            raise refused("Main concrete families and their native all_ids alias disagree.")
        return tuple(rows)

    def target_consumers(self, obj):
        from ._scene_checkpoint_roles import _pointer

        if self.role_plan is None:
            settings = _pointer(self.bpy, self.scene, "tool_settings", "ToolSettings")
            particle = _pointer(self.bpy, settings, "particle_edit", "ParticleEdit")
            weak = identity(_pointer(self.bpy, particle, "object", "Object"))
            self_count = int(self.scene.user_of_id(self.scene))
            if (self_count, weak) != (0, None) and (self_count != 1 or weak is None):
                raise refused("Unclassified initial checkpoint weak roles cannot authorize point consumers.")
        else:
            self.role_plan.check_after_read()
            self_count, weak = self.role_plan.expected
        extra = int(self_count == 1 and weak == identity(obj))
        expected_scene = 2 + extra  # One master link and one sole ViewLayer Base.
        users = bounded(self.bpy.data.user_map(subset={obj}).get(obj, ()), 16, "Object consumers")
        rows = []
        for owner in users:
            count = int(owner.user_of_id(obj))
            if owner == self.scene and count == expected_scene:
                rows.append((identity(owner), count-extra, "SCENE_MASTER_AND_BASE"))
            elif owner == self.scene.collection and count == 1:
                rows.append((identity(owner), 1, "MASTER_COLLECTION"))
            else:
                raise refused("The animated point Object has an unreviewed external consumer.")
        if not rows:
            raise refused("The animated point Object has no complete native consumer evidence.")
        return tuple(sorted(rows))

    def object_record(self, obj, *, static=False):
        fields: dict[str, tuple[str, int | None]] = {
            name: ("FLOAT", length) for name, length in zip(RAW_CHANNELS, CHANNEL_LENGTHS, strict=True)}
        fields.update({"name": ("STRING", None), "mode": ("ENUM", None), "type": ("ENUM", None),
                       "animation_data": ("POINTER", None), "parent": ("POINTER", None),
                       "rotation_mode": ("ENUM", None), "hide_viewport": ("BOOLEAN", 0),
                       "hide_render": ("BOOLEAN", 0), "hide_select": ("BOOLEAN", 0)})
        self.schema(obj, fields)
        if (obj.library is not None or obj.override_library is not None or not obj.is_editable
                or obj.mode != "OBJECT" or obj.parent is not None or obj.constraints or obj.modifiers
                or obj.instance_type != "NONE" or (static and obj.animation_data is not None)
                or tuple(obj.keys())):
            raise refused("Point preservation requires unparented ordinary Objects without live dependencies.")
        return (identity(obj), obj.name, obj.type, identity(obj.data), obj.rotation_mode,
                tuple((field, raw_tuple(getattr(obj, field))) for field in RAW_CHANNELS),
                obj.hide_viewport, obj.hide_render, obj.hide_select,
                tuple(identity(c) for c in obj.users_collection), tuple(identity(s) for s in obj.users_scene))

    def literal(self):
        """Declared source before roles/providers; no selected/active/context getter."""
        objects = bounded(self.bpy.data.objects, MAX_OBJECTS, "Main Objects")
        rows = tuple(self.object_record(obj, static=obj.name != self.name) for obj in objects)
        scene = self.scene
        return (rows, identity(scene), int(scene.frame_current), float(scene.frame_subframe),
                identity(scene.camera), identity(scene.world),
                (scene.unit_settings.system, float(scene.unit_settings.scale_length)),
                self.bpy.data.filepath, pointer(self.layer), pointer(self.window),
                identity(self.window.screen), identity(self.window.workspace), self.inventory())

    def prepare(self):
        self.check_origin()
        selected = self.selected()
        if (identity(selected["object"]), identity(selected["action"])) != self.ids:
            raise refused("Original point Object/Action identity changed before planning.")
        current = float(self.scene.frame_current) + float(self.scene.frame_subframe)
        # A current-pose change belongs to a separately qualified checkpoint profile.
        for frame, values in selected["prepared"]:
            point = next(p for p in selected["curve"].keyframe_points if float(p.co[0]) == frame)
            if "co" in values and frame == current and not intent.same(tuple(values["co"]), tuple(point.co)):
                raise refused("The first raw point profile does not revise the current pose's key value.")
        action, data = selected["action"], selected["object"].animation_data
        for handle, curve in scope.curve_inventory(action):
            if data.action_slot is not None and handle != data.action_slot.handle:
                continue
            if curve.data_path not in {"location", "rotation_euler", "scale"} or not 0 <= curve.array_index < 3:
                raise refused("Initial point curves address only explicit XYZ Object channels.")
            matches = [p for p in curve.keyframe_points if float(p.co[0]) == current]
            actual = getattr(selected["object"], curve.data_path)[curve.array_index]
            if (len(matches) != 1 or struct.pack("<f", actual) != struct.pack("<f", matches[0].co[1])
                    or selected["object"].rotation_mode != "XYZ"):
                raise refused("Initial point edits require an unchanged existing current key and coherent raw channels.")
        return selected

    def selected(self):
        """Resolve explicit direct Main/slot membership without context helpers."""
        from . import animation_curves as module

        obj = self.bpy.data.objects.get(self.name)
        if obj is None or obj.animation_data is None or obj.animation_data.action is None:
            raise refused("The explicit original point Object/Action is missing.")
        data, action = obj.animation_data, obj.animation_data.action
        curves, slot = module._slot_curves(data, action, self.params.get("slot_identifier"))
        path, index = self.params["data_path"], self.params.get("index", 0)
        matches = [curve for curve in curves if curve.data_path == path and curve.array_index == index]
        if len(matches) != 1:
            raise invalid_argument("Choose one existing explicit Object transform curve.")
        curve = matches[0]
        points = bounded(curve.keyframe_points, 1024, "selected curve points")
        prepared, seen = [], set()
        for edit in self.params["keyframes"]:
            frame = module._number(edit["frame"], "frame")
            candidates = [p for p in points if struct.pack("<f", p.co[0]) == struct.pack("<f", frame)]
            if len(candidates) != 1 or pointer(candidates[0]) in seen:
                raise invalid_argument("Each point edit must identify a distinct existing native frame.")
            point = candidates[0]
            seen.add(pointer(point))
            values = {field: tuple(float(v) for v in edit[field]) for field in intent.FIELDS if field in edit}
            if not values:
                raise invalid_argument("Each edit must supply a raw point field.")
            prepared.append((float(point.co[0]), values))
        inventory = scope.curve_inventory(action)
        ordinal = [i for i, (_handle, item) in enumerate(inventory) if pointer(item) == pointer(curve)]
        if len(ordinal) != 1:
            raise refused("The explicit point curve is not unique in its Action.")
        return {"object": obj, "action": action, "curve": curve, "slot": slot, "path": path,
                "index": index, "ordinal": ordinal[0], "prepared": tuple(prepared), "extrapolation": None}

    def roles(self):
        from ._scene_checkpoint_roles import Plan

        def witness(_bpy, owner, _plan):
            if owner.type != "EMPTY" or owner.data is not None:
                raise refused("The checkpoint's previous weak owner needs the separate static Empty profile.")
            owner_id = identity(owner)
            if owner_id is None:
                raise refused("The checkpoint's previous weak owner is absent.")
            return ActiveWitness(self, owner.name, owner_id, self.object_record(owner, static=True))

        plan = Plan(self.bpy, self.scene, include_brush=True, previous_owner_factory=witness)
        active = next((obj for obj in self.bpy.data.objects if identity(obj) == plan.owners[-1]), None)
        if active is None or active.name == self.name or active.type != "EMPTY" or active.data is not None:
            raise refused("Point checkpoints require a separate unanimated active Empty.")
        active_witness = witness(self.bpy, active, plan)
        if not intent.same(self.literal(), self.original_literal):
            raise refused("Checkpoint context acquisition changed the original declared source; no baseline adopted.",
                          context_sync_possible=True)
        self.role_plan = plan
        return plan, active_witness

    def action_content(self, action):
        self._screen_action(action)
        return scope.action_content(action)

    def resolve(self):
        self.check_origin()
        if self.ids is None:
            raise refused("Point ownership was not captured before resolution.")
        obj = self.bpy.data.objects.get(self.name)
        if obj is None or identity(obj) != self.ids[0] or obj.animation_data is None:
            raise refused("The original point Object no longer belongs to current Main.")
        action = obj.animation_data.action
        if action is None or identity(action) != self.ids[1] or self.bpy.data.actions.get(action.name) != action:
            raise refused("The original point Action or binding changed.")
        self._screen()
        selected = self.selected()
        return selected["object"], selected["action"], selected["curve"]

    def preservation(self, roles):
        from . import animation_curves as module

        self.check_origin()
        obj, action, _curve = self.resolve()
        users = scope.action_users(self.bpy, action)
        references = users["references"]
        if len(references) != 1 or references[0][0:2] != identity(obj) or references[0][4] != 1:
            raise refused("Point Action consumers are not the one retained Object binding.")
        user_facts = tuple(users[field] for field in
                           ("users", "fake_user", "references", "real_users", "direct_users_complete"))
        other = tuple((identity(a), a.name, module._curve_structure(a), self.action_content(a))
                      for a in self.bpy.data.actions if a != action)
        return (self.literal(), scope.binding(obj), scope.animation_context(obj), user_facts,
                self.target_consumers(obj), module._curve_structure(action), other, roles.authored())

    def leaf(self, curve, field, frame, value, *, expected, preservation, roles):
        if field not in {"co", "handle_left", "handle_right"} or type(value) is not tuple or len(value) != 2:
            raise refused("Only prebuilt raw Float2 point assignments may reach native entry.")
        # Capture the primitive argument object before the final complete CAS.
        pair = tuple(value)
        if any(type(v) is not float or not math.isfinite(v) for v in pair):
            raise refused("The native point argument is not a finite exact builtin Float2.")
        # Screens and role reads happen before the last full source comparison.
        _obj, action, fresh = self.resolve()
        if pointer(fresh) != pointer(curve):
            raise refused("The native point curve changed after its complete prefix comparison.")
        curve = fresh = action = _obj = None
        if not intent.same(self.preservation(roles), preservation):
            raise refused("Point preservation changed during final native leaf acquisition.")
        selected = self.selected()
        action, fresh = selected["action"], selected["curve"]
        if not intent.same(self.action_content(action), expected):
            raise refused("The complete Action differs from its final independently predicted prefix.")
        # Literal descendant reacquisition follows the full source comparison;
        # no role/context read or provider executes with the point retained.
        points = [p for p in fresh.keyframe_points if struct.pack("<f", p.co[0]) == struct.pack("<f", frame)]
        if len(points) != 1:
            raise refused("The exact original point is absent or ambiguous.")
        owner = points[0]
        self.schema(owner, {field: ("FLOAT", 2)})
        prop = owner.bl_rna.properties[field]
        if prop.is_readonly or any(not prop.hard_min <= v <= prop.hard_max for v in pair):
            raise refused("The native point property would reject or clamp the planned Float2.")
        slots = native_slots(self.bpy)
        if any(a is not b for a, b in zip(slots, self._slots, strict=True)):
            raise refused("The genuine native point slot changed.")
        # No providers, context/Action read or yield occurs after this leaf returns.
        result = Leaf(owner, slots[1], field, pair)
        owner = action = fresh = selected = None
        points = []
        return result
