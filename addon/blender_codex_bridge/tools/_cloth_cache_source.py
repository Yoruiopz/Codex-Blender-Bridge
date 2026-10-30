# SPDX-License-Identifier: GPL-3.0-or-later
"""Held source and canonical context endpoints for detached cloth observation.

Capture occurs before the first permission provider. Verification examines only
ordinary Python namespaces, function facts and exact built-in data slots. It
never calls a provider, cancellation hook, Blender/RNA getter or context factory.
This is a fixed in-process qualification boundary, not a Python security sandbox.
"""
from __future__ import annotations

import importlib
import math
import operator
import os
import pathlib
import re
import sys
from types import (
    BuiltinFunctionType,
    CodeType,
    FunctionType,
    GenericAlias,
    GetSetDescriptorType,
    MethodDescriptorType,
    MethodType,
    ModuleType,
    WrapperDescriptorType,
)

from ..errors import BridgeError, ErrorCode

_MODULES = (
    "tools._cloth_cache_source", "storage_snapshot", "storage_snapshot_effects", "blend_storage_sdna",
    "tools._cloth_cache_scope", "tools._cloth_cache_job", "tools._cloth_scene_consumers", "tools._simulation_runtime",
    "tool_registry", "state", "permissions", "request_lifecycle", "command_queue", "protocol", "executor",
    "scene_jobs", "scene_job_authority", "scene_job_reservations", "scene_job_effects", "scene_job_evidence",
    "checkpoints", "checkpoint_completion", "operation_lease", "task_plans", "errors",
    "runtime", "native_save_jobs", "geometry_preview_jobs", "jobs", "utils", "entry_effects",
    "native_save_profile", "job_controller", "glb_stage_runtime", "glb_stage_protected_mesh",
    "glb_stage_state", "scene_evidence",
)
_STDLIB = ("os", "stat", "time", "sys", "threading", "hashlib", "json", "json.encoder", "json.decoder",
           "json.scanner", "inspect", "dataclasses", "types", "pathlib", "math", "struct", "_thread",
           "io", "_io", "contextlib", "re", "operator")
_CONTEXT = (
    "state", "registry", "permissions", "checkpoints", "jobs", "request_lifecycle", "request_id",
    "check_cancelled", "check_final_request", "check_final_job", "checkpoint_admission", "checkpoint_call_id",
    "checkpoint_method", "checkpoint_params", "checkpoint_finalization_owner", "exclusive_mutation_lease",
    "glb_stage", "evidence",
)
_HOOKS = ("check_cancelled", "check_final_request", "check_final_job")
_PATH_GETTER_KIND = operator.attrgetter
_PATH_GETTER_REDUCE = vars(_PATH_GETTER_KIND)["__reduce__"]
_PATH_GETTER_CALL = vars(_PATH_GETTER_KIND)["__call__"]
_PURE_PATH_KIND = pathlib.PurePath
_PURE_PATH_DEFINING_MODULE = importlib.import_module(_PURE_PATH_KIND.__module__)
_PATH_PROPERTIES = tuple((name, vars(_PURE_PATH_KIND).get(name), argument)
                         for name, argument in (("drive", "_drv"), ("root", "_root")))
_PATH_PROPERTY_SLOTS = tuple(vars(property)[name] for name in ("fget", "fset", "fdel"))
_PATH_PROPERTY_BINDINGS = tuple((descriptor, tuple((slot, slot.__get__(descriptor, property))
                                                  for slot in _PATH_PROPERTY_SLOTS))
                                for _name, descriptor, _argument in _PATH_PROPERTIES if type(descriptor) is property)


def _refused(reason):
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "The retained cloth source/context proof is unavailable.",
                       {"reason": reason, "source_verifier_invoked_blender": False, "verification_required": True})


def _function(function):
    if type(function) is not FunctionType:
        raise _refused("CLOTH_SOURCE_FUNCTION_UNQUALIFIED")
    keywords = function.__kwdefaults__
    if keywords is not None and (type(keywords) is not dict or any(type(k) is not str for k in keywords)):
        raise _refused("CLOTH_SOURCE_KEYWORDS_UNQUALIFIED")
    try:
        cells = tuple((cell, cell.cell_contents) for cell in function.__closure__ or ())
    except ValueError as cause:
        raise _refused("CLOTH_SOURCE_CLOSURE_UNQUALIFIED") from cause
    return (function, function.__code__, function.__globals__, function.__defaults__, keywords,
            () if keywords is None else tuple(keywords.items()), cells)


def _native_path_accessor(module, owner, function):
    """Only original immutable CPython PurePath drive/root C accessors.

    Python3.11 implements these properties with operator.attrgetter. Qualify
    their immutable native arguments before a provider; later verification
    holds the module, class and property identities without invoking them.
    """
    if (module is not pathlib or owner is not _PURE_PATH_KIND
            or _namespace(pathlib).get("PurePath") is not _PURE_PATH_KIND
            or _namespace(operator).get("attrgetter") is not _PATH_GETTER_KIND
            or type(function) is not _PATH_GETTER_KIND):
        raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_ORIGIN_CHANGED")
    native = type.__dict__["__dict__"].__get__(_PATH_GETTER_KIND)
    flags = type.__dict__["__flags__"].__get__(_PATH_GETTER_KIND)
    if (type(flags) is not int or not flags & (1 << 8)  # CPython immutable native type.
            or type(_PATH_GETTER_REDUCE) is not MethodDescriptorType
            or _PATH_GETTER_REDUCE.__objclass__ is not _PATH_GETTER_KIND
            or type(_PATH_GETTER_CALL) is not WrapperDescriptorType
            or _PATH_GETTER_CALL.__objclass__ is not _PATH_GETTER_KIND
            or native.get("__reduce__") is not _PATH_GETTER_REDUCE
            or native.get("__call__") is not _PATH_GETTER_CALL):
        raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_NATIVE_CHANGED")
    fields = _namespace(owner)
    for name, descriptor, expected in _PATH_PROPERTIES:
        if (type(descriptor) is not property or fields.get(name) is not descriptor
                or descriptor.fget is not function or descriptor.fset is not None or descriptor.fdel is not None):
            continue
        reduced = _PATH_GETTER_REDUCE(function)  # Held immutable C method, never a path/Blender read.
        if (type(reduced) is not tuple or len(reduced) != 2 or reduced[0] is not _PATH_GETTER_KIND
                or type(reduced[1]) is not tuple or len(reduced[1]) != 1
                or type(reduced[1][0]) is not str or reduced[1][0] != expected):
            raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_ARGUMENT_CHANGED")
        return
    raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_PROPERTY_CHANGED")


def _path_property_origins():
    if (_namespace(pathlib).get("PurePath") is not _PURE_PATH_KIND
            or _namespace(operator).get("attrgetter") is not _PATH_GETTER_KIND
            or _namespace(_PURE_PATH_DEFINING_MODULE).get("PurePath") is not _PURE_PATH_KIND):
        raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_ORIGIN_CHANGED")
    fields = _namespace(_PURE_PATH_KIND)
    module_name = fields.get("__module__")
    defining_name = _namespace(_PURE_PATH_DEFINING_MODULE).get("__name__")
    if (type(module_name) is not str or module_name not in {"pathlib", "pathlib._local"}
            or type(defining_name) is not str or defining_name != module_name):
        raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_ORIGIN_CHANGED")
    for name, descriptor, _argument in _PATH_PROPERTIES:
        if type(descriptor) is not property or fields.get(name) is not descriptor:
            raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_PROPERTY_CHANGED")
    for descriptor, slots in _PATH_PROPERTY_BINDINGS:
        for slot, expected in slots:
            if slot.__get__(descriptor, property) is not expected:
                raise _refused("CLOTH_SOURCE_PATH_ACCESSOR_PROPERTY_CHANGED")


def _namespace(owner):
    if type(owner) is ModuleType:
        result = ModuleType.__getattribute__(owner, "__dict__")
    else:
        result = type.__dict__["__dict__"].__get__(owner)
    if len(result) > 4096 or any(type(key) is not str for key in result):
        raise _refused("CLOTH_SOURCE_NAMESPACE_UNQUALIFIED")
    return result


def _class(owner):
    namespace = _namespace(owner)
    return owner, type(owner), type.__dict__["__mro__"].__get__(owner), tuple(namespace.items())


def _instance(value, allowed):
    """Qualify Python instance shape before reading any instance field."""
    if not any(type(value) is candidate for candidate in allowed):
        raise _refused("CLOTH_SOURCE_CONTEXT_UNQUALIFIED")
    for owner in type.__dict__["__mro__"].__get__(type(value)):
        namespace = _namespace(owner)
        if "__getattr__" in namespace or ("__getattribute__" in namespace
                and namespace["__getattribute__"] is not object.__getattribute__):
            raise _refused("CLOTH_SOURCE_CONTEXT_UNQUALIFIED")
    descriptor = next((row["__dict__"] for owner in type.__dict__["__mro__"].__get__(type(value))
                       for row in (_namespace(owner),) if "__dict__" in row), None)
    if descriptor is None:
        return None
    if type(descriptor) is not GetSetDescriptorType:
        raise _refused("CLOTH_SOURCE_CONTEXT_UNQUALIFIED")
    namespace = descriptor.__get__(value, type(value))
    if type(namespace) is not dict or any(type(key) is not str for key in namespace):
        raise _refused("CLOTH_SOURCE_CONTEXT_UNQUALIFIED")
    for owner in type.__dict__["__mro__"].__get__(type(value)):
        for name, item in _namespace(owner).items():
            if name in namespace:
                descriptors = any("__get__" in _namespace(base)
                                  for base in type.__dict__["__mro__"].__get__(type(item)))
                if type(item) in (FunctionType, property, staticmethod, classmethod) or descriptors:
                    raise _refused("CLOTH_SOURCE_SHADOW_ENDPOINT")
    return descriptor


def _plain_tables(values):
    """Retain mutable source tables by identity, never arbitrary equality/hash."""
    pending, seen, result = list(values), set(), []
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if len(seen) > 32768:
            raise _refused("CLOTH_SOURCE_TABLE_BUDGET")
        if type(value) is dict:
            if len(value) > 4096:
                raise _refused("CLOTH_SOURCE_TABLE_BUDGET")
            rows = tuple(value.items())
            result.append((value, dict, rows))
            pending.extend(child for pair in rows for child in pair)
        elif type(value) is list or type(value) is set:
            if len(value) > 4096:
                raise _refused("CLOTH_SOURCE_TABLE_BUDGET")
            rows = tuple(value)
            result.append((value, type(value), rows))
            pending.extend(rows)
        elif type(value) is tuple or type(value) is frozenset:
            if len(value) > 4096:
                raise _refused("CLOTH_SOURCE_TABLE_BUDGET")
            pending.extend(value)
    return tuple(result)


def _hook(value, name, context, modules):
    """Admit actual executor/Scene scheduler endpoints, not caller functions."""
    if value is None:
        return None
    queue, executor, scene = (modules[key] for key in ("command_queue", "executor", "scene_jobs"))
    if type(value) is MethodType:
        if (name != "check_cancelled" or value.__func__ is not queue.QueuedRequest.check_active
                or type(value.__self__) is not queue.QueuedRequest):
            raise _refused("CLOTH_SOURCE_CONTEXT_HOOK_UNQUALIFIED")
        fact = _function(value.__func__)
        return value, value.__self__, fact
    if type(value) is not FunctionType or value.__defaults__ is not None or value.__kwdefaults__ is not None:
        raise _refused("CLOTH_SOURCE_CONTEXT_HOOK_UNQUALIFIED")
    fact = _function(value)
    cells = dict(zip(value.__code__.co_freevars, (row[1] for row in fact[6]), strict=True))
    if name == "check_final_request":
        parent = executor.MainThreadExecutor.__dict__["_invoke_owned"]
        codes = tuple(code for code in parent.__code__.co_consts
                      if type(code) is CodeType and code.co_freevars == ("queued_owner",))
        if (len(codes) != 1 or value.__code__ is not codes[0] or value.__globals__ is not vars(executor)
                or type(cells.get("queued_owner")) is not queue.QueuedRequest):
            raise _refused("CLOTH_SOURCE_CONTEXT_HOOK_UNQUALIFIED")
    else:
        methods = ("_context",) if name == "check_cancelled" else ("_context", "_tick_check", "_advance_work")
        codes = tuple(code for method in methods for code in scene.SceneJobs.__dict__[method].__code__.co_consts
                      if type(code) is CodeType and code.co_name == "<lambda>")
        if (not any(value.__code__ is code for code in codes) or value.__globals__ is not vars(scene)
                or cells.get("self") is not context.jobs or context.jobs is None
                or ("context" in cells and cells["context"] is not context)):
            raise _refused("CLOTH_SOURCE_CONTEXT_HOOK_UNQUALIFIED")
        if "job" in cells and type(cells["job"]) is not scene.SceneJob:
            raise _refused("CLOTH_SOURCE_CONTEXT_HOOK_UNQUALIFIED")
        if "token" in cells and type(cells["token"]) is not modules["scene_job_reservations"].SceneTurn:
            raise _refused("CLOTH_SOURCE_CONTEXT_HOOK_UNQUALIFIED")
    return value, None, fact


class ClothSourceWitness(tuple):
    """Immutable held registration; verification runs no Blender or provider callbacks."""
    __slots__ = ()

    def verify(self, context):
        # Native tuple/function/namespace operations are held inside this exact
        # registration; no replaceable module helper runs during verification.
        raw = ().__class__.__getitem__
        native = raw(self, 6)
        kind, length, str_kind, dict_kind, fn_kind, module_kind, method_kind = native[:7]
        module_dict, class_dict, class_mro, failure, context_kind, slot_rows = native[7:13]
        for table, saved in raw(self, 3):
            if kind(table) is not dict_kind or length(table) != length(saved):
                raise failure
            for key in table:
                if kind(key) is not str_kind:
                    raise failure
            for key, item in saved:
                if key not in table or table[key] is not item:
                    raise failure
        for module, saved in raw(self, 0):
            if kind(module) is not module_kind:
                raise failure
            namespace = module_dict(module, "__dict__")
            if length(namespace) != length(saved):
                raise failure
            for key in namespace:
                if kind(key) is not str_kind:
                    raise failure
            for key, item in saved:
                if key not in namespace or namespace[key] is not item:
                    raise failure
        for owner, owner_kind, mro, saved in raw(self, 1):
            if kind(owner) is not owner_kind or class_mro(owner) is not mro:
                raise failure
            namespace = class_dict(owner)
            if length(namespace) != length(saved):
                raise failure
            for key in namespace:
                if kind(key) is not str_kind:
                    raise failure
            for key, item in saved:
                if key not in namespace or namespace[key] is not item:
                    raise failure
        property_kind, bindings = raw(self, 9)
        for descriptor, slots in bindings:
            if kind(descriptor) is not property_kind:
                raise failure
            for slot, expected in slots:
                if slot.__get__(descriptor, property_kind) is not expected:
                    raise failure
        # No unverified function is called; defaults and closure contents are
        # inspected by identity rather than custom equality or representation.
        for function, code, namespace, defaults, keywords, saved, cells in raw(self, 2):
            if (kind(function) is not fn_kind or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not keywords):
                raise failure
            if keywords is not None:
                if kind(keywords) is not dict_kind or length(keywords) != length(saved):
                    raise failure
                for key in keywords:
                    if kind(key) is not str_kind:
                        raise failure
                for key, item in saved:
                    if key not in keywords or keywords[key] is not item:
                        raise failure
            closure = function.__closure__ or ()
            if length(closure) != length(cells):
                raise failure
            for index, (cell, item) in enumerate(cells):
                if closure[index] is not cell:
                    raise failure
                try:
                    if cell.cell_contents is not item:
                        raise failure
                except ValueError:
                    raise failure from None
        for table, table_kind, saved in raw(self, 4):
            if kind(table) is not table_kind or length(table) != length(saved):
                raise failure
            actual = table.items() if table_kind is dict_kind else table
            for current, expected in zip(actual, saved, strict=True):
                if table_kind is dict_kind:
                    if current[0] is not expected[0] or current[1] is not expected[1]:
                        raise failure
                elif current is not expected:
                    raise failure
        for table, expected_kind, item_kind in raw(self, 8):
            if kind(table) is not expected_kind:
                raise failure
            for item in table:
                if kind(item) is not item_kind:
                    raise failure
        original, rows, hooks, objects = raw(self, 5)
        if kind(context) is not context_kind or context is not original:
            raise failure
        for (name, descriptor), (row_name, expected) in zip(slot_rows, rows, strict=True):
            if name is not row_name or descriptor.__get__(context, context_kind) is not expected:
                raise failure
        for value, owner, fact in hooks:
            if kind(value) is method_kind:
                if value.__self__ is not owner or value.__func__ is not fact[0]:
                    raise failure
            elif kind(value) is not fn_kind:
                raise failure
        for value, expected_kind, descriptor, saved, slots, booleans in objects:
            if kind(value) is not expected_kind:
                raise failure
            for slot, expected in slots:
                if slot.__get__(value, expected_kind) is not expected:
                    raise failure
            for _key, slot in booleans:
                if slot is not None and kind(slot.__get__(value, expected_kind)) is not native[14]:
                    raise failure
            if descriptor is None:
                continue
            namespace = descriptor.__get__(value, expected_kind)
            if kind(namespace) is not dict_kind:
                raise failure
            for key in namespace:
                if kind(key) is not str_kind:
                    raise failure
            for key, item in saved:
                if key not in namespace or namespace[key] is not item:
                    raise failure
            for key, slot in booleans:
                if slot is None and (key not in namespace or kind(namespace[key]) is not native[14]):
                    raise failure
            if value is rows[0][1]:
                count = namespace.get("connected_clients")
                if kind(count) is not native[15] or count < 0:
                    raise failure
            # An instance may not introduce a callable shadow of a class
            # endpoint after capture. Ordinary mutable service data is allowed.
            for owner in class_mro(expected_kind):
                for key, item in class_dict(owner).items():
                    if kind(item) in native[13] and key in namespace:
                        raise failure


def capture_cloth_sources(context):
    """Capture fixed loaded source and actual context endpoints pre-provider."""
    _path_property_origins()
    package = __package__.rsplit(".", 1)[0]
    modules = {name: importlib.import_module(package + "." + name) for name in _MODULES}
    source_modules = tuple(modules.values()) + tuple(importlib.import_module(name) for name in _STDLIB)
    # Python3.13 reexports PurePath from pathlib._local. Capture that exact
    # loaded module with the same class/function/global rules as Python3.11.
    if not any(_PURE_PATH_DEFINING_MODULE is module for module in source_modules):
        source_modules += (_PURE_PATH_DEFINING_MODULE,)
    if not any(os.path is module for module in source_modules):
        source_modules += (os.path,)
    # CPython 3.10 uses sre_compile/sre_parse; newer versions use re's
    # private modules. Hold the actual fixed compiler/parser entries used by re,
    # without importing a version-specific name or accepting a caller module.
    compiler = vars(re).get("_compiler", vars(re).get("sre_compile"))
    if type(compiler) is not ModuleType:
        raise _refused("CLOTH_SOURCE_REGEX_BACKEND_UNQUALIFIED")
    parser = vars(compiler).get("_parser", vars(compiler).get("sre_parse"))
    if type(parser) is not ModuleType:
        raise _refused("CLOTH_SOURCE_REGEX_BACKEND_UNQUALIFIED")
    for module in (compiler, parser):
        if not any(module is old for old in source_modules):
            source_modules += (module,)
    modules["types"] = importlib.import_module("types")
    # Native modules are fixed dependencies of the canonical runtime, never
    # caller-provided registration inputs. Reading their Python dictionaries
    # cannot trigger a dynamic bpy.types lookup or an RNA property getter.
    native_modules = ()
    native_bpy = _namespace(modules["runtime"]).get("bpy")
    if native_bpy is not None:
        if type(native_bpy) is not ModuleType:
            raise _refused("CLOTH_SOURCE_NATIVE_MODULE_UNQUALIFIED")
        native_types = _namespace(native_bpy).get("types")
        if type(native_types) is not ModuleType:
            raise _refused("CLOTH_SOURCE_NATIVE_TYPES_UNQUALIFIED")
        native_modules = (native_bpy, native_types)
    registry = modules["tool_registry"]
    if type(context) is not registry.ToolContext:
        raise _refused("CLOTH_SOURCE_CONTEXT_UNQUALIFIED")
    classes, functions, module_rows, tables, constants = [], [], [], [], []
    for module in source_modules:
        namespace = _namespace(module)
        if type(namespace.get("__name__")) is not str:
            raise _refused("CLOTH_SOURCE_NAMESPACE_UNQUALIFIED")
        module_rows.append((module, tuple(namespace.items())))
        for name, value in namespace.items():
            if name.isupper():
                constants.append(value)
            selected = (value,) if type(value) is FunctionType else ()
            actual_kind = type(value)
            actual_mro = type.__dict__["__mro__"].__get__(actual_kind)
            if (any(base is type for base in actual_mro)
                    and type(_namespace(value).get("__module__")) is str
                    and _namespace(value)["__module__"] == namespace["__name__"]):
                classes.append(_class(value))
                fields = _namespace(value)
                constants.extend(item for item in fields.values() if type(item) is dict)
                selected = tuple(function for item in fields.values() for function in (
                    (item,) if type(item) is FunctionType else
                    (item.__func__,) if type(item) in (classmethod, staticmethod) else
                    tuple(fn for fn in (item.fget, item.fset, item.fdel) if fn is not None)
                    if type(item) is property else ()))
            for function in selected:
                if (type(function) in (BuiltinFunctionType, MethodDescriptorType, WrapperDescriptorType)
                        or function is GenericAlias):
                    continue  # Native immutable entry identity is held by its class namespace.
                if type(function) is _PATH_GETTER_KIND:
                    _native_path_accessor(module, value, function)
                    continue
                fact = _function(function)
                functions.append(fact)
                constants.extend((fact[3], fact[4]))
                builtins = function.__builtins__
                if not any(builtins is table for table, _ in tables):
                    if type(builtins) is not dict or any(type(key) is not str for key in builtins):
                        raise _refused("CLOTH_SOURCE_BUILTINS_UNQUALIFIED")
                    tables.append((builtins, tuple(builtins.items())))
    for module in native_modules:
        namespace = _namespace(module)
        module_rows.append((module, tuple(namespace.items())))
        for value in namespace.values():
            if type(value) is FunctionType:
                functions.append(_function(value))
                globals_table = value.__globals__
                if (type(globals_table) is not dict or len(globals_table) > 4096
                        or any(type(key) is not str for key in globals_table)):
                    raise _refused("CLOTH_SOURCE_NATIVE_GLOBALS_UNQUALIFIED")
                if not any(globals_table is table for table, _ in tables):
                    tables.append((globals_table, tuple(globals_table.items())))
    slots = tuple((name, registry.ToolContext.__dict__[name]) for name in _CONTEXT)
    rows = {name: descriptor.__get__(context, registry.ToolContext) for name, descriptor in slots}
    hooks = tuple(fact for name in _HOOKS for fact in (_hook(rows[name], name, context, modules),) if fact is not None)
    functions.extend(fact[2] for fact in hooks)
    objects, typed_tables = [], []

    def retain(value, allowed, names=(), booleans=()):
        descriptor = _instance(value, allowed)
        fields = {} if descriptor is None else descriptor.__get__(value, type(value))
        saved, slots = [], []
        for name in names:
            if name in fields:
                saved.append((name, fields[name]))
            else:
                slot = next((row[name] for owner in type.__dict__["__mro__"].__get__(type(value))
                             for row in (_namespace(owner),) if name in row), None)
                if type(slot) is not modules["types"].MemberDescriptorType:
                    raise _refused("CLOTH_SOURCE_CONTEXT_SLOT_UNQUALIFIED")
                slots.append((slot, slot.__get__(value, type(value))))
        flags = []
        for name in booleans:
            slot = None
            if name in fields:
                flag = fields[name]
            else:
                slot = next((row[name] for owner in type.__dict__["__mro__"].__get__(type(value))
                             for row in (_namespace(owner),) if name in row), None)
                if type(slot) is not modules["types"].MemberDescriptorType:
                    raise _refused("CLOTH_SOURCE_CONTEXT_FLAG_UNQUALIFIED")
                flag = slot.__get__(value, type(value))
            if type(flag) is not bool:
                raise _refused("CLOTH_SOURCE_CONTEXT_FLAG_UNQUALIFIED")
            flags.append((name, slot))
        objects.append((value, type(value), descriptor, tuple(saved), tuple(slots), tuple(flags)))
        return fields

    def retain_factory(value, allowed, names=()):
        # Every field read by the checked factory is ordinary instance data.
        # Reject even a custom data descriptor before inspecting that instance.
        if not any(type(value) is kind for kind in allowed):
            raise _refused("CLOTH_SOURCE_CONTEXT_FACTORY_UNQUALIFIED")
        for parent in type.__dict__["__mro__"].__get__(type(value)):
            namespace = _namespace(parent)
            if any(name in namespace for name in names):
                raise _refused("CLOTH_SOURCE_CONTEXT_FACTORY_UNQUALIFIED")
        return retain(value, allowed, names)

    # These identities are not a new permission grant and are never invoked.
    state_fields = retain(rows["state"], (modules["state"].BridgeState,), ("_lock",),
                          booleans=("server_running", "paused", "emergency_stopped", "is_executing"))
    if type(state_fields.get("connected_clients")) is not int or state_fields["connected_clients"] < 0:
        raise _refused("CLOTH_SOURCE_STATE_COUNT_UNQUALIFIED")
    thread_module = importlib.import_module("_thread")
    if type(state_fields["_lock"]) is not thread_module.RLock:
        raise _refused("CLOTH_SOURCE_STATE_LOCK_UNQUALIFIED")
    registry_fields = retain(rows["registry"], (registry.ToolRegistry,),
                             ("_mutation_interlock", "_scene_reservations", "_tools", "_enabled_toolsets"))
    tool_table, enabled = registry_fields["_tools"], registry_fields["_enabled_toolsets"]
    if (type(tool_table) is not dict or len(tool_table) > 4096 or any(type(key) is not str for key in tool_table)
            or type(enabled) is not set or any(type(item) is not str for item in enabled)):
        raise _refused("CLOTH_SOURCE_REGISTRY_STORAGE_UNQUALIFIED")
    constants.append(tool_table)
    typed_tables.append((enabled, set, str))
    for spec in tool_table.values():
        retain(spec, (registry.ToolSpec,), registry.ToolSpec.__slots__)
    interlock_fields = retain(registry_fields["_mutation_interlock"], (modules["operation_lease"].MutationInterlock,),
                              ("owner", "invocation", "_entries", "_consumed"))
    if type(interlock_fields["_entries"]) is not list or type(interlock_fields["_consumed"]) is not set:
        raise _refused("CLOTH_SOURCE_REGISTRY_STORAGE_UNQUALIFIED")
    constants.extend((interlock_fields["_entries"], interlock_fields["_consumed"]))
    retain(registry_fields["_scene_reservations"], (modules["scene_job_reservations"].SceneJobReservations,),
           ("registry", "_turns", "_retained"))
    if rows["checkpoint_admission"] is not None:
        retain(rows["checkpoint_admission"], (registry.CheckpointAdmissionBinding,),
               registry.CheckpointAdmissionBinding.__slots__)

    if rows["checkpoints"] is not None:
        retain(rows["checkpoints"], (modules["checkpoints"].CheckpointManager,))
    factory_permissions = None
    if rows["jobs"] is not None:
        # The registration-time witness is pure, held and verified before any
        # external helper, property, factory or permission provider can run.
        checked = _CHECKED_FACTORY_SOURCE
        function, code, namespace, defaults, keywords, _saved, cells = tuple.__getitem__(checked, 7)
        if (function is not _CHECKED_FACTORY_VERIFY or function.__code__ is not code
                or function.__globals__ is not namespace or function.__defaults__ is not defaults
                or function.__kwdefaults__ is not keywords
                or len(function.__closure__ or ()) != len(cells)):
            raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
        function(checked, None)
        for name, module in _CHECKED_FACTORY_MODULES:
            if modules[name] is not module or sys.modules.get(package + "." + name) is not module:
                raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
        runtime = modules["runtime"]
        if (runtime.checked_executor_context is not _CHECKED_FACTORY_HELPER
                or runtime.BridgeRuntime is not _CHECKED_RUNTIME_TYPE
                or runtime._CANONICAL_RUNTIME_CLASS is not _CHECKED_RUNTIME_TYPE
                or runtime._RUNTIME_CONSTRUCTOR_CODE is not _CHECKED_RUNTIME_CODE):
            raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
        fields = retain_factory(rows["jobs"], (modules["scene_jobs"].SceneJobs, modules["native_save_jobs"].NativeSaveJobs),
                        ("context_factory",))
        fact = _function(fields["context_factory"])
        codes = tuple(code for code in runtime._RUNTIME_CONSTRUCTOR_CODE.co_consts
                      if type(code) is CodeType and code.co_freevars == ("self",)
                      and code.co_names == ("checked_executor_context", "executor"))
        if (len(codes) != 1 or fact[1] is not codes[0] or fact[2] is not vars(runtime)
                or fact[3] is not None or fact[4] is not None or len(fact[6]) != 1
                or type(fact[6][0][1]) is not runtime._CANONICAL_RUNTIME_CLASS):
            raise _refused("CLOTH_SOURCE_CONTEXT_FACTORY_UNQUALIFIED")
        functions.append(fact)
        owner = fact[6][0][1]
        owned = retain_factory(owner, (runtime._CANONICAL_RUNTIME_CLASS,),
            ("jobs", "executor", "state", "registry", "permissions", "checkpoints", "glb_stage", "_glb_stage_origin"))
        execution = retain_factory(owned["executor"], (modules["executor"].MainThreadExecutor,),
            ("state", "registry", "permissions", "checkpoints", "jobs", "glb_stage", "evidence"))
        if (any(owned[name] is not rows[name] for name in ("state", "registry", "checkpoints", "jobs", "glb_stage"))
                or any(execution[name] is not rows[name] for name in ("state", "registry", "checkpoints", "jobs", "glb_stage", "evidence"))
                or execution["permissions"] is not owned["permissions"]):
            raise _refused("CLOTH_SOURCE_CONTEXT_FACTORY_UNQUALIFIED")
        factory_permissions = owned["permissions"]
        service = owned["glb_stage"]
        service_fields = retain_factory(service, (modules["glb_stage_runtime"].GLBStageService,),
            ("runtime", "state", "registry", "checkpoints", "jobs", "_executor_origin", "store", "_records", "_origins"))
        if (service_fields["runtime"] is not owner or service_fields["_executor_origin"] is not owned["executor"]
                or owned["_glb_stage_origin"] is not service
                or any(service_fields[name] is not rows[name] for name in ("state", "registry", "checkpoints", "jobs"))):
            raise _refused("CLOTH_SOURCE_CONTEXT_FACTORY_UNQUALIFIED")
        retain_factory(service_fields["store"], (modules["glb_stage_state"].GLBStageStore,))
        retain_factory(execution["evidence"], (modules["scene_evidence"].SceneEvidenceStore,))
        records, originals = service_fields["_records"], service_fields["_origins"]
        expected = (owner, rows["state"], rows["registry"], rows["checkpoints"], rows["jobs"], service_fields["store"], records)
        if (type(records) is not dict or any(type(name) is not str for name in records)
                or type(originals) is not tuple or len(originals) != len(expected)
                or any(a is not e for a, e in zip(originals, expected, strict=True))):
            raise _refused("CLOTH_SOURCE_CONTEXT_FACTORY_UNQUALIFIED")
    manager = rows["permissions"]
    for _ in range(4):
        permitted = (modules["permissions"].PermissionManager, modules["scene_job_authority"].SceneJobPermissions)
        descriptor = _instance(manager, permitted)
        fields = descriptor.__get__(manager, type(manager))
        names = ("base", "service") if type(manager) is permitted[1] else ("_source",)
        saved = tuple((name, fields[name]) for name in names if name in fields)
        if len(saved) != len(names):
            raise _refused("CLOTH_SOURCE_PERMISSION_MANAGER_UNQUALIFIED")
        objects.append((manager, type(manager), descriptor, saved, (), ()))
        if type(manager) is permitted[0]:
            provider = fields["_source"]
            if type(provider) is MethodType:
                functions.append(_function(provider.__func__))
            elif type(provider) is FunctionType:
                functions.append(_function(provider))
            else:
                raise _refused("CLOTH_SOURCE_PROVIDER_UNQUALIFIED")
            break
        service_fields = retain(fields["service"], (modules["scene_job_reservations"].SceneJobReservations,),
                                ("registry",))
        if service_fields["registry"] is not rows["registry"]:
            raise _refused("CLOTH_SOURCE_PERMISSION_MANAGER_UNQUALIFIED")
        manager = fields["base"]
    else:
        raise _refused("CLOTH_SOURCE_PERMISSION_MANAGER_UNQUALIFIED")
    if factory_permissions is not None and manager is not factory_permissions:
        raise _refused("CLOTH_SOURCE_CONTEXT_FACTORY_UNQUALIFIED")
    lifetime = rows["request_lifecycle"]
    if lifetime is not None:
        life_module = modules["request_lifecycle"]
        retain(lifetime, (life_module.RequestLifetime,), ("connection", "deadline", "delivered", "rejected"))
        if type(lifetime.deadline) is not float or math.isnan(lifetime.deadline):
            raise _refused("CLOTH_SOURCE_LIFETIME_UNQUALIFIED")
        if lifetime.connection is not None:
            retain(lifetime.connection, (life_module.ConnectionLifetime,), ("disconnected", "background_active"))
        events = (lifetime.delivered, lifetime.rejected)
        if lifetime.connection is not None:
            events += (lifetime.connection.disconnected, lifetime.connection.background_active)
        for event in events:
            retain(event, (life_module.threading.Event,), booleans=("_flag",))
    # Bind each queued hook's lock and actual request; source-matching code alone
    # cannot bless an unrelated owner or arbitrary context callback.
    queued_owners = []
    for _value, owner, fact in hooks:
        candidates = (owner,) if owner is not None else tuple(item for _, item in fact[6])
        for owner in candidates:
            if type(owner) is not modules["command_queue"].QueuedRequest or any(owner is item for item in queued_owners):
                continue
            queued_owners.append(owner)
            retain(owner, (modules["command_queue"].QueuedRequest,), ("request", "deadline", "_lock"),
                   booleans=("_stop_requested",))
            if type(owner.deadline) is not float or not math.isfinite(owner.deadline):
                raise _refused("CLOTH_SOURCE_QUEUED_DEADLINE_UNQUALIFIED")
            if type(owner._lock) is not thread_module.LockType:
                raise _refused("CLOTH_SOURCE_QUEUED_LOCK_UNQUALIFIED")
            retain(owner.request, (modules["protocol"].Request,), ("id", "_lifecycle"))
            if (owner.request._lifecycle is not lifetime or type(owner.request.id) is not str
                    or type(rows["request_id"]) is not str or owner.request.id != rows["request_id"]):
                raise _refused("CLOTH_SOURCE_QUEUED_OWNER_UNQUALIFIED")
    # Generated dataclass methods may retain Python factory functions only in
    # closure cells. Hold their actual code as well as the cell/value identity.
    pending, seen, expanded = list(functions), set(), []
    while pending:
        fact = pending.pop()
        if id(fact[0]) in seen:
            continue
        seen.add(id(fact[0]))
        if len(seen) > 16384:
            raise _refused("CLOTH_SOURCE_FUNCTION_BUDGET")
        expanded.append(fact)
        pending.extend(_function(value) for _cell, value in fact[6] if type(value) is FunctionType)
    functions = expanded
    for function, _code, _namespace_fact, defaults, keywords, *_ in functions:
        constants.extend((defaults, keywords))
        table = function.__builtins__
        if not any(table is old for old, _ in tables):
            if type(table) is not dict or any(type(key) is not str for key in table):
                raise _refused("CLOTH_SOURCE_BUILTINS_UNQUALIFIED")
            tables.append((table, tuple(table.items())))
    native = (type, len, str, dict, FunctionType, ModuleType, MethodType, ModuleType.__getattribute__,
              type.__dict__["__dict__"].__get__, type.__dict__["__mro__"].__get__,
              _refused("CLOTH_SOURCE_OR_CONTEXT_CHANGED"), registry.ToolContext, slots,
              (FunctionType, property, staticmethod, classmethod), bool, int)
    witness = tuple.__new__(ClothSourceWitness, (tuple(module_rows), tuple(classes), tuple(functions), tuple(tables),
        _plain_tables(constants), (context, tuple(rows.items()), hooks, tuple(objects)), native,
        _function(ClothSourceWitness.__dict__["verify"]), tuple(typed_tables),
        (property, _PATH_PROPERTY_BINDINGS + _CHECKED_FACTORY_PROPERTIES)))
    witness.verify(context)
    return witness


# Immutable registration-time source origins. This proof contains no Blender
# owner, operation facts or context factory result, and never executes a helper.
def _checked_factory_registration():
    package = __package__.rsplit(".", 1)[0]
    modules = tuple((name, importlib.import_module(package + "." + name)) for name in
        ("jobs", "glb_stage_runtime", "glb_stage_protected_mesh", "job_controller", "glb_stage_state", "scene_evidence", "executor"))
    jobs, glb = dict(modules)["jobs"], dict(modules)["glb_stage_runtime"]
    if (glb.checked_executor_context is not jobs._PREPARED_CONTEXT_HELPER
            or type(glb._EXECUTOR_CONTEXT_PROPERTY) is not property
            or glb._EXECUTOR_CONTEXT_PROPERTY.fget is not glb._EXECUTOR_CONTEXT_GETTER
            or glb._EXECUTOR_CONTEXT_PROPERTY.fset is not None or glb._EXECUTOR_CONTEXT_PROPERTY.fdel is not None
            or glb._EXECUTOR_CONTEXT_GETTER.__code__ is not glb._EXECUTOR_CONTEXT_GETTER_CODE):
        raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
    # jobs holds original helper facts from its earlier trusted import. A helper
    # changed before this module's FIRST import must not become a new baseline.
    for function, fact, dependencies in jobs._PREPARED_CONTEXT_FUNCTIONS:
        if (type(function) is not FunctionType or function is not fact[0]
                or function.__code__ is not fact[1] or function.__globals__ is not fact[2]
                or function.__defaults__ is not fact[3] or function.__kwdefaults__ is not fact[4]):
            raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
        namespace = function.__globals__
        if (type(namespace) is not dict or any(type(name) is not str for name in namespace)
                or any(namespace.get(name, jobs._PREPARED_MISSING) is not value for name, value in dependencies)):
            raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
        closure = function.__closure__ or ()
        if len(closure) != len(fact[5]):
            raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
        for actual, (cell, expected) in zip(closure, fact[5], strict=True):
            try:
                if actual is not cell or actual.cell_contents is not expected:
                    raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
            except ValueError:
                raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED") from None
    rows, classes, functions, tables, constants, properties = [], [], [], [], [], []
    for _name, module in modules:
        namespace = _namespace(module)
        rows.append((module, tuple(namespace.items())))
        for value in namespace.values():
            selected = (value,) if type(value) is FunctionType else ()
            if type(value) is type and _namespace(value).get("__module__") == namespace["__name__"]:
                classes.append(_class(value))
                fields = _namespace(value)
                selected = tuple(fn for raw in fields.values() for fn in (
                    (raw,) if type(raw) is FunctionType else (raw.__func__,) if type(raw) in (classmethod, staticmethod) else
                    tuple(fn for fn in (raw.fget, raw.fset, raw.fdel) if fn is not None) if type(raw) is property else ()))
                for raw in fields.values():
                    if type(raw) is property:
                        properties.append((raw, tuple((slot, slot.__get__(raw, property)) for slot in _PATH_PROPERTY_SLOTS)))
            for function in selected:
                functions.append(_function(function))
                table = function.__builtins__
                if not any(table is original for original, _saved in tables):
                    tables.append((table, tuple(table.items())))
        constants.extend(namespace.values())
    runtime = importlib.import_module(package + ".runtime")
    runtime_type = runtime._CANONICAL_RUNTIME_CLASS
    classes.append(_class(runtime_type))
    functions.extend(_function(value) for value in _namespace(runtime_type).values() if type(value) is FunctionType)
    # Include the exact original authority classes referenced by the checked
    # helper, even when they are imported aliases rather than module owners.
    jobs = dict(modules)["jobs"]
    for cls, mro, saved, facts in jobs._PREPARED_CONTEXT_CLASSES:
        classes.append((cls, type(cls), mro, saved))
        for old in facts:
            if old[0].__code__ is not old[1]:
                raise _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED")
            functions.append(_function(old[0]))
    verify = ClothSourceWitness.__dict__["verify"]
    native = (type, len, str, dict, FunctionType, ModuleType, MethodType, ModuleType.__getattribute__,
              type.__dict__["__dict__"].__get__, type.__dict__["__mro__"].__get__,
              _refused("CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED"), type(None), (),
              (FunctionType, property, staticmethod, classmethod), bool, int)
    proof = tuple.__new__(ClothSourceWitness, (tuple(rows), tuple(classes), tuple(functions), tuple(tables),
        _plain_tables(constants), (None, (), (), ()), native, _function(verify), (), (property, tuple(properties))))
    return modules, proof, verify, tuple(properties)


_CHECKED_FACTORY_MODULES, _CHECKED_FACTORY_SOURCE, _CHECKED_FACTORY_VERIFY, _CHECKED_FACTORY_PROPERTIES = _checked_factory_registration()
_CHECKED_FACTORY_HELPER = dict(_CHECKED_FACTORY_MODULES)["jobs"]._PREPARED_CONTEXT_HELPER
_CHECKED_RUNTIME_TYPE = importlib.import_module(__package__.rsplit(".", 1)[0] + ".runtime")._CANONICAL_RUNTIME_CLASS
_CHECKED_RUNTIME_CODE = _CHECKED_RUNTIME_TYPE.__init__.__code__
