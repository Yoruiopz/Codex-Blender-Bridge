# SPDX-License-Identifier: GPL-3.0-or-later
"""Private live Approved Project Folder observation; no registered caller.

This prerequisite grants no filesystem authority and performs no IO. Native
route acceptance requires separate official-build fixtures. A future caller
must source-qualify the exact helper before dispatch and use ``read_current``
after every authorizing provider, and after a live post-writer stop check.
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
from types import BuiltinFunctionType, FunctionType, MethodDescriptorType, ModuleType

from . import current_pixels_graph as graph
from . import preferences, runtime
from .errors import BridgeError, ErrorCode
from .permissions import Permission
from .storage_snapshot import _live_frame
from .storage_snapshot_service import StorageSnapshotService
from .tool_registry import ToolContext, check_final_mutation
from .tools import _cloth_cache_source as sources

REQUIRED = (Permission.INSPECT_SCENE, Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES)
_DECLARATION = (("name", "Approved Project Folder"),
                ("description", "Local .blend artifact folder; the separate native-save session permission covers normal callback/catalog effects outside it. Not configurable through MCP"),
                ("subtype", "DIR_PATH"), ("default", ""), ("attr", "project_directory"))
# Establish CPython's warning-cache binding before immutable source capture.
__warningregistry__ = {}


def refused(reason):
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "Live local storage approval is unavailable.",
                       {"reason": reason, "native_root_authority_qualified": False,
                        "shipping_caller_qualified": False})


def _source(context):
    """Extend the existing immutable verifier with a FIXED defining closure."""
    original = sources.capture_cloth_sources(context)
    module_rows, classes, functions, tables = [list(tuple.__getitem__(original, i)) for i in range(4)]
    constants = []
    package = __package__
    for name in ("storage_snapshot_approval", "preferences", "storage_snapshot_service",
                 "current_pixels_graph", "current_pixels_contract"):
        module = importlib.import_module(package + "." + name)
        namespace = sources._namespace(module)
        module_rows.append((module, tuple(namespace.items())))
        for value in namespace.values():
            selected = (value,) if type(value) is FunctionType else ()
            if type(value) is type or (preferences.BlenderCodexBridgePreferences is not None
                                        and value is preferences.BlenderCodexBridgePreferences):
                fields = sources._namespace(value)
                if fields.get("__module__") != namespace["__name__"]:
                    continue
                classes.append(sources._class(value))
                constants.extend(item for item in fields.values() if type(item) is dict)
                selected = tuple(fn for item in fields.values() for fn in (
                    (item,) if type(item) is FunctionType else
                    (item.__func__,) if type(item) in (classmethod, staticmethod) else
                    tuple(fn for fn in (item.fget, item.fset, item.fdel) if fn is not None)
                    if type(item) is property else ()))
            for function in selected:
                fact = sources._function(function)
                functions.append(fact)
                constants.extend((fact[3], fact[4]))
                table = function.__builtins__
                if not any(table is old for old, _saved in tables):
                    if type(table) is not dict or any(type(key) is not str for key in table):
                        raise refused("ROOT_APPROVAL_SOURCE_BUILTINS")
                    tables.append((table, tuple(table.items())))
            if type(value) in (dict, list, tuple, set, frozenset):
                constants.append(value)
    rows = tuple(tuple.__iter__(original))
    combined = tuple.__new__(sources.ClothSourceWitness,
        (tuple(module_rows), tuple(classes), tuple(functions), tuple(tables),
         rows[4] + sources._plain_tables(constants), *rows[5:]))
    combined.verify(context)
    return combined


def _held_guard(source, context):
    verify, code, namespace, defaults, keywords, _saved, closures = tuple.__getitem__(source, 7)
    native = tuple.__getitem__(source, 6)
    kind, function_kind, failure = native[0], native[4], native[10]
    def guard():
        if (kind(verify) is not function_kind or verify.__code__ is not code or verify.__globals__ is not namespace
                or defaults is not None or keywords is not None or closures
                or verify.__defaults__ is not None or verify.__kwdefaults__ is not None or verify.__closure__ is not None):
            raise failure
        verify(source, context)
    guard()
    return guard


def _root(value):
    if type(value) is not str:
        raise refused("ROOT_APPROVAL_EXACT_TEXT_REQUIRED")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as cause:
        raise refused("ROOT_APPROVAL_EXACT_TEXT_REQUIRED") from cause
    if (not 0 < size <= 4096 or "\\" in value or value.startswith("//")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or not os.path.isabs(value) or os.path.normpath(value) != value
            or value == os.path.abspath(os.sep)
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])):
        raise refused("ROOT_APPROVAL_ORDINARY_ABSOLUTE_REQUIRED")
    return value


def _declaration_clause_facts(function, original, keywords):
    """Bounded literal facts from ALREADY read marker slots; no new getters.

    These diagnostics grant nothing and never format or traverse foreign
    objects. Preserve the original declaration refusal even for malformed data.
    """
    type_name = type.__dict__["__name__"]
    def name(value):
        label = type_name.__get__(type(value))
        return label[:128] if type(label) is str else None
    def text(value, maximum):
        part = value[:maximum]
        try:
            part.encode("utf-8", "strict")
        except UnicodeError:
            return None, True
        return part, len(value) > maximum
    rows, truncated = [], False
    if type(keywords) is dict:
        for index, (key, value) in enumerate(dict.items(keywords)):
            if index >= 16:
                truncated = True
                break
            key_text, key_truncated = text(key, 64) if type(key) is str else (None, False)
            value_text, value_truncated = None, False
            if type(value) is str:
                value_text, value_truncated = text(value, 512)
            elif type(value) is bool or value is None or (type(value) is int and value.bit_length() <= 256):
                value_text = value
            rows.append({"name": key_text, "name_kind": name(key), "name_truncated": key_truncated,
                         "value": value_text, "value_kind": name(value), "value_truncated": value_truncated})
    return {"function_kind": name(function), "function_is_builtin": type(function) is BuiltinFunctionType,
            "function_matches_original": function is original, "keywords_exact_dict": type(keywords) is dict,
            "keyword_count": len(keywords) if type(keywords) is dict else None,
            "keywords": rows, "rows_truncated": truncated,
            "expected_keyword_names": [key for key, _value in _DECLARATION]}


def _declaration(bpy):
    cls = preferences.BlenderCodexBridgePreferences
    if cls is None:
        raise refused("ROOT_APPROVAL_PREFERENCES_UNREGISTERED")
    marker_kind, origins = graph._deferred_type(bpy)
    fields = graph._class_dict(cls)
    annotations = fields.get("__annotations__")
    if type(annotations) is not dict or any(type(key) is not str for key in annotations):
        raise refused("ROOT_APPROVAL_DECLARATION_CHANGED")
    marker = annotations.get("project_directory")
    if type(marker) is not marker_kind:
        raise refused("ROOT_APPROVAL_DECLARATION_CHANGED")
    function_slot, keyword_slot = origins[5]
    function, keywords = function_slot.__get__(marker, marker_kind), keyword_slot.__get__(marker, marker_kind)
    props = ModuleType.__getattribute__(origins[1], "__dict__")
    if (type(function) is not BuiltinFunctionType or function is not props.get("StringProperty")
            or type(keywords) is not dict or len(keywords) != len(_DECLARATION)
            or any(type(key) is not str or type(value) is not str for key, value in keywords.items())
            or any(keywords.get(key) != value for key, value in _DECLARATION)):
        error = refused("ROOT_APPROVAL_CALLBACK_OR_DECLARATION_CHANGED")
        try:  # noqa: SIM105 - keep primary without a context-manager dispatch.
            error.context["declaration_clause"] = _declaration_clause_facts(function, props.get("StringProperty"), keywords)
        except Exception:
            # Optional diagnostics must never replace the original refusal.
            pass
        raise error
    return cls, annotations, marker, marker_kind, origins, function_slot, keyword_slot, function, keywords, tuple(keywords.items())


def _declaration_unchanged(bpy, fact):
    cls, annotations, marker, marker_kind, origins, function_slot, keyword_slot, function, keywords, saved = fact
    props = ModuleType.__getattribute__(origins[1], "__dict__")
    if (preferences.BlenderCodexBridgePreferences is not cls
            or graph._class_dict(cls).get("__annotations__") is not annotations
            or annotations.get("project_directory") is not marker or type(marker) is not marker_kind
            or props.get("_PropertyDeferred") is not marker_kind or props.get("StringProperty") is not function
            or graph._class_find(marker_kind, "function") is not function_slot
            or graph._class_find(marker_kind, "keywords") is not keyword_slot
            or ModuleType.__getattribute__(bpy, "__dict__").get("props") is not origins[1]
            or function_slot.__get__(marker, marker_kind) is not function
            or keyword_slot.__get__(marker, marker_kind) is not keywords
            or type(keywords) is not dict or len(keywords) != len(saved)
            or any(type(key) is not str or type(value) is not str for key, value in keywords.items())
            or any(keywords.get(key) is not value for key, value in saved)):
        raise refused("ROOT_APPROVAL_DECLARATION_CHANGED")


def _collection_get(collection, key):
    kind = type(collection)
    descriptor = graph._class_find(kind, "get")
    slot = graph._class_find(kind, "__getattribute__")
    flags = type.__dict__["__flags__"].__get__(kind, type)
    if (type(kind) is not type or type(flags) is not int or not flags & (1 << 8)
            or type(slot) is not graph.WrapperDescriptorType
            or not any(slot.__objclass__ is parent for parent in graph._class_mro(kind))
            or graph._class_find(kind, "__get__") is not None
            or type(descriptor) is not MethodDescriptorType or descriptor.__objclass__ is not kind
            or graph._class_find(kind, "__getattr__") is not None):
        raise refused("ROOT_APPROVAL_NATIVE_COLLECTION_CHANGED")
    getter = descriptor.__get__(collection, kind)
    if type(getter) is not BuiltinFunctionType or getter.__self__ is not collection:
        raise refused("ROOT_APPROVAL_NATIVE_COLLECTION_CHANGED")
    return getter(key), (kind, descriptor, slot)


def _route(bpy, declaration):
    """Read only the finite supported native preference route and its metadata."""
    proofs = {kind: graph._constructor_proof(bpy, kind) for kind in
              ("Context", "Preferences", "Addon", "Struct", "Property",
               "PointerProperty", "CollectionProperty", "StringProperty")}
    for kind in ("PointerProperty", "CollectionProperty", "StringProperty"):
        graph._unshadowed(proofs[kind][0], ("identifier", "type", "is_readonly", "is_runtime",
                                           "is_registered", "subtype", "fixed_type"))
    graph._unshadowed(proofs["Struct"][0], ("identifier", "properties"))
    metadata_origins = []

    def field(owner, kind, name, category, target):
        cls, rna, native_get, pointer, _origins = proofs[kind]
        graph._unshadowed(cls, (name,))
        if type(owner) is not cls:
            raise refused("ROOT_APPROVAL_NATIVE_ROUTE_OWNER_CHANGED")
        prop, get_origin = _collection_get(rna.properties, name)
        if (type(prop) is not proofs[category + "Property"][0]
                or prop.identifier != name or prop.type != category.upper()
                or prop.is_readonly is not True or prop.is_runtime is not False
                or prop.is_registered is not False or prop.fixed_type.identifier != target):
            raise refused("ROOT_APPROVAL_NATIVE_ROUTE_FIELD_CHANGED")
        metadata_origins.extend((prop, get_origin[0], get_origin[1], get_origin[2], pointer(rna)))
        return native_get(owner, name)

    context = ModuleType.__getattribute__(bpy, "__dict__").get("context")
    prefs = field(context, "Context", "preferences", "Pointer", "Preferences")
    addons = field(prefs, "Preferences", "addons", "Collection", "Addon")
    addon, collection_origin = _collection_get(addons, __package__)
    if addon is None:
        raise refused("ROOT_APPROVAL_PREFERENCES_UNREGISTERED")
    owner = field(addon, "Addon", "preferences", "Pointer", "AddonPreferences")
    cls = declaration[0]
    # This explicit registered class is the sole exception, not a generic
    # registered-property reader or a relaxed storage_snapshot._field.
    proof = graph._constructor_proof(bpy, "BlenderCodexBridgePreferences", cls)
    if type(owner) is not cls or graph._class_find(cls, "project_directory") is not None:
        raise refused("ROOT_APPROVAL_PREFERENCES_OWNER_CHANGED")
    rna, native_get, pointer = proof[1:4]
    prop, property_origin = _collection_get(rna.properties, "project_directory")
    property_proof = proofs["StringProperty"]
    if (type(prop) is not property_proof[0]
            or prop.identifier != "project_directory" or prop.type != "STRING"
            or prop.is_readonly is not False or prop.is_runtime is not True or prop.is_registered is not True
            or prop.subtype != "DIR_PATH"):
        raise refused("ROOT_APPROVAL_REGISTERED_FIELD_CHANGED")
    if preferences.get_preferences() is not owner:
        raise refused("ROOT_APPROVAL_GETTER_ROUTE_CHANGED")
    identity = (context, prefs, addons, *collection_origin, addon, owner, cls, rna, prop,
                *metadata_origins, *property_origin, pointer(rna), property_proof[3](prop), native_get)
    return identity


def _same_route(actual, original):
    return (len(actual) == len(original)
            and all(value == old if type(old) is int and type(value) is int else value is old
                    for value, old in zip(actual, original, strict=True)))


def _control(context):
    if threading.current_thread() is not threading.main_thread():
        raise refused("ROOT_APPROVAL_MAIN_THREAD_REQUIRED")
    check_final_mutation(context, context.checkpoint_method)
    flags = context.state.snapshot()
    if type(flags) is not dict or any(type(flags.get(name)) is not bool for name in ("paused", "emergency_stopped")):
        raise refused("ROOT_APPROVAL_CONTROL_CHANGED")
    if flags["emergency_stopped"] or flags["paused"]:
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags["emergency_stopped"] else ErrorCode.AGENT_PAUSED,
                          "Local storage approval stopped before its next getter.")


class LocalRootApproval(tuple):
    """Exact current-activation local approval, never a cached permission grant."""
    __slots__ = ()

    @classmethod
    def capture(cls, context):
        if cls is not LocalRootApproval or type(context) is not ToolContext:
            raise refused("ROOT_APPROVAL_CANONICAL_RUNTIME_REQUIRED")
        source = _source(context)
        guard = _held_guard(source, context)
        owner = runtime._RUNTIME
        if (type(context) is not ToolContext or type(owner) is not runtime._CANONICAL_RUNTIME_CLASS
                or owner is None or owner._registered is not True
                or not runtime.native_save_permission_provider_intact()):
            raise refused("ROOT_APPROVAL_CANONICAL_RUNTIME_REQUIRED")
        service = context.storage_snapshots
        if (type(service) is not StorageSnapshotService or owner.storage_snapshots is not service
                or owner._storage_snapshot_origin is not service or service._owner is not owner
                or owner.executor.storage_snapshots is not service
                or any(getattr(context, name) is not getattr(owner, name) for name in
                       ("state", "registry", "permissions", "checkpoints", "jobs"))):
            raise refused("ROOT_APPROVAL_RUNTIME_SERVICE_CHANGED")
        _control(context)
        guard()
        bpy = runtime.bpy
        if type(bpy) is not ModuleType or preferences.bpy is not bpy:
            raise refused("ROOT_APPROVAL_CANONICAL_BLENDER_REQUIRED")
        graph._deferred_type(bpy)
        declaration = _declaration(bpy)
        guard()
        _control(context)
        guard()
        route = _route(bpy, declaration)
        guard()
        _control(context)
        guard()
        anchor = sys._getframe(1)
        if anchor.f_code.co_flags & 0x2A0:  # generator, coroutine, async generator
            raise refused("ROOT_APPROVAL_NONYIELDING_ACTIVATION_REQUIRED")
        result = tuple.__new__(cls, (source, context, owner, service, bpy, declaration, route, None, anchor))
        result.check_source()
        return result

    def check_source(self):
        # Bootstrap the held pure verifier before any dynamic helper dispatch.
        raw = ().__class__.__getitem__
        source, context = raw(self, 0), raw(self, 1)
        verify, code, namespace, defaults, keywords, _saved, closures = raw(source, 7)
        native = raw(source, 6)
        if (native[0](verify) is not native[4] or verify.__code__ is not code or verify.__globals__ is not namespace
                or defaults is not None or keywords is not None or closures
                or verify.__defaults__ is not None or verify.__kwdefaults__ is not None or verify.__closure__ is not None):
            raise native[10]
        verify(source, context)
        if type(self) is not LocalRootApproval:
            raise refused("ROOT_APPROVAL_EXACT_OWNER_REQUIRED")
        owner, service, bpy, declaration, _route_fact, root = tuple.__getitem__(self, slice(2, 8))
        if (runtime._RUNTIME is not owner or owner._registered is not True or runtime.bpy is not bpy
                or type(owner) is not runtime._CANONICAL_RUNTIME_CLASS
                or owner.storage_snapshots is not service or owner._storage_snapshot_origin is not service
                or context.storage_snapshots is not service or service._owner is not owner
                or owner.executor.storage_snapshots is not service
                or any(getattr(context, name) is not getattr(owner, name) for name in
                       ("state", "registry", "permissions", "checkpoints", "jobs"))
                or not _live_frame(raw(self, 8))
                or (root is not None and type(root) is not str)):
            raise refused("ROOT_APPROVAL_RUNTIME_SERVICE_CHANGED")
        _declaration_unchanged(bpy, declaration)

    def authorize(self):
        self.check_source()
        context = tuple.__getitem__(self, 1)
        guard = _held_guard(tuple.__getitem__(self, 0), context)
        _control(context)
        guard()
        self.check_source()
        context.require(*REQUIRED)
        guard()
        self.check_source()
        _control(context)
        guard()
        self.check_source()
        value = self._read_root()
        original = tuple.__getitem__(self, 7)
        if original is not None:
            if value != original:
                raise refused("ROOT_APPROVAL_VALUE_CHANGED")
            return self
        return tuple.__new__(LocalRootApproval, (*tuple.__getitem__(self, slice(0, 7)), value,
                                                tuple.__getitem__(self, 8)))

    @property
    def approved_root(self):
        self.check_source()
        value = tuple.__getitem__(self, 7)
        if value is None:
            raise refused("ROOT_APPROVAL_INITIAL_PERMISSION_REQUIRED")
        return value

    def _read_root(self):
        self.check_source()
        context, bpy = tuple.__getitem__(self, 1), tuple.__getitem__(self, 4)
        guard = _held_guard(tuple.__getitem__(self, 0), context)
        _control(context)  # A stopped writer never reaches any native getter.
        guard()
        self.check_source()
        route = _route(bpy, tuple.__getitem__(self, 5))
        guard()
        self.check_source()
        _control(context)
        guard()
        self.check_source()
        if not _same_route(route, tuple.__getitem__(self, 6)):
            raise refused("ROOT_APPROVAL_NATIVE_ROUTE_CHANGED")
        value = _root(route[-1](route[7], "project_directory"))
        guard()
        self.check_source()
        _control(context)
        guard()
        self.check_source()
        return value

    def read_current(self):
        # Immutable approved tuples cannot adopt a provider-rewritten baseline.
        self.check_source()
        original = self.approved_root
        value = self._read_root()
        if value != original:
            raise refused("ROOT_APPROVAL_VALUE_CHANGED")
        return value
